//! **Reasoning must never render in the response colour.**
//!
//! Observed live on 2026-08-09, asking Marlowe for the weather in Cass Lake. The model thought
//! (1688 characters, collapsed), called `web` twice, got a failure it could not read, and then
//! kept reasoning — and the transcript rendered that reasoning as Marlowe speaking, ending with a
//! literal `</think>` printed to the user.
//!
//! Two failures from one cause:
//!
//! 1. **Reasoning shown as speech.** The channel split was made in the provider, and content that
//!    was still inside a think block went out as `TextDelta`.
//! 2. **The turn ended.** The loop completes on prose-with-no-tool-call — the correct rule — and
//!    leaked reasoning *is* prose as far as the loop can see. So the run stopped mid-thought and
//!    the user got a chain of thought as the answer.
//!
//! The fix is in one place, `marlowe_provider::ThinkSplitter`, and the second failure is a
//! consequence of the first: with reasoning routed correctly the turn's prose is **empty**, which
//! is not a completion.

use marlowe_daemon::{apply_events, view_from_status, Event, StatusReport};
use marlowe_view::{Entry, Speech};

fn view() -> marlowe_view::SessionView {
    view_from_status(&StatusReport {
        version: "0.1.0".into(),
        workspace: "/ws".into(),
        model: "qwen3.5:9b".into(),
        model_disclosure: "local".into(),
        degraded: None,
        rerank_provider: "cpu".into(),
        live_runs: 0,
    })
}

fn spoken(v: &marlowe_view::SessionView) -> String {
    v.transcript
        .iter()
        .filter_map(|e| match e {
            Entry::Said(Speech::Model(t)) => Some(t.as_str()),
            _ => None,
        })
        .collect()
}

fn thought(v: &marlowe_view::SessionView) -> String {
    v.transcript
        .iter()
        .filter_map(|e| match e {
            Entry::Reasoning { text, .. } => Some(text.as_str()),
            _ => None,
        })
        .collect()
}

/// **The Cass Lake transcript, replayed.** Reasoning streamed as speech, then retracted.
#[test]
fn retracted_speech_moves_into_the_thinking_block_and_leaves_the_transcript() {
    let mut v = view();
    apply_events(
        &mut v,
        &[
            Event::Reasoning { delta: "The user wants weather. I will search.".into() },
            Event::Tool {
                id: 1,
                verb: "web".into(),
                target: "cass lake mn weather".into(),
                state: "failed".into(),
                summary: String::new(),
            },
            // The model kept reasoning, and it arrived in `content`.
            Event::Text { delta: "I see the tool output shows just \"tool\" -- possibly ".into() },
            Event::Text { delta: "indicating some kind of error or limitation.".into() },
            // …and then closed the block it had opened before `content` began.
            Event::SpeechRetracted,
        ],
    );

    assert_eq!(
        spoken(&v),
        "",
        "reasoning was left in the transcript as Marlowe's speech: {:?}",
        spoken(&v)
    );
    assert!(
        thought(&v).contains("I see the tool output shows just"),
        "the retracted text must land in the thinking block, not vanish: {:?}",
        thought(&v)
    );
    assert!(
        !thought(&v).contains("</think>") && !spoken(&v).contains("</think>"),
        "a closing tag must never be text anywhere"
    );
}

/// A real answer after the retraction survives it. The correction is scoped to what was
/// outstanding, not to everything the turn ever said.
#[test]
fn speech_after_a_retraction_is_kept() {
    let mut v = view();
    apply_events(
        &mut v,
        &[
            Event::Text { delta: "still thinking about this".into() },
            Event::SpeechRetracted,
            Event::Text { delta: "It is 12°C in Cass Lake.".into() },
        ],
    );
    assert_eq!(spoken(&v), "It is 12°C in Cass Lake.");
    assert_eq!(thought(&v), "still thinking about this");
}

/// A retraction with nothing outstanding is ordinary, not an error: every nested
/// `<think>…</think>` in content produces one without any speech having been emitted.
#[test]
fn a_retraction_with_nothing_outstanding_is_harmless() {
    let mut v = view();
    apply_events(&mut v, &[Event::Reasoning { delta: "weighing".into() }, Event::SpeechRetracted]);
    assert_eq!(spoken(&v), "");
    assert_eq!(thought(&v), "weighing");
}

/// **The split happens in the provider, so the loop sees prose only when there is prose.**
///
/// This is the second half of the bug: a turn whose entire content was reasoning must not look
/// like an answer. Asserted on the splitter directly, because that is where the loop's input is
/// decided.
#[test]
fn a_turn_that_was_entirely_reasoning_yields_no_prose_for_the_loop() {
    use marlowe_provider::{Segment, ThinkSplitter};

    let mut s = ThinkSplitter::new();
    let mut prose = String::new();
    let mut retracted = false;
    for chunk in [
        "I see the tool output shows just \"tool\" -- possibly indicating",
        " some kind of error or limitation with how `use` works here.",
        "\n\n[your reasoning continues]\n</thi",
        "nk>",
    ] {
        let split = s.feed(chunk);
        if split.retract_speech {
            prose.clear();
            retracted = true;
        }
        for seg in &split.segments {
            if let Segment::Speech(t) = seg {
                prose.push_str(t);
            }
        }
    }
    for seg in &s.finish().segments {
        if let Segment::Speech(t) = seg {
            prose.push_str(t);
        }
    }

    assert!(retracted, "the closing tag must retract the reasoning that preceded it");
    assert_eq!(
        prose, "",
        "the loop would read this as an answer and end the run mid-thought: {prose:?}"
    );
}

/// **The prompt may only name tools that exist.**
///
/// `--dev`'s outbound dump on the Cass Lake run showed the system prompt still saying *"Answer
/// with `done` when the task is complete"* — long after `done` was removed from the vocabulary
/// because a small model cannot be trusted to emit a terminator reliably. So every turn told the
/// model to finish by calling a tool that would be routed to a tool host with no executor for it.
///
/// Nothing could catch this: the loop was right, the provider was right, and the prompt is a
/// string. This is the guard for it — a claim about a name needs a test that the name still
/// exists.
/// Every backticked lowercase word in `prompt` that is not a registered tool.
fn unknown_tools_named_in(prompt: &str) -> Vec<String> {
    let registry = marlowe_tools::builtin_registry().unwrap();
    prompt
        .split('`')
        .skip(1)
        .step_by(2)
        .map(str::trim)
        .filter(|w| !w.is_empty() && w.chars().all(|c| c.is_ascii_lowercase()))
        .filter(|w| registry.get(&marlowe_tools::ToolId::new(*w)).is_none())
        .map(str::to_string)
        .collect()
}

#[test]
fn the_system_prompt_names_no_tool_that_does_not_exist() {
    let prompt = marlowe_daemon::governance_prompt();
    assert!(
        unknown_tools_named_in(prompt).is_empty(),
        "the system prompt names {:?}, which are not registered tools. Prompt was:\n{prompt}",
        unknown_tools_named_in(prompt)
    );
}

/// **The negative control, and it is the whole reason the test above is worth having.**
///
/// The current prompt contains no backticks at all, so the assertion passes over an empty list —
/// it would go green against a prompt naming anything. That is a vacuous test, and shipping one
/// here would have been the same mistake in a smaller box. This pins the checker against the
/// exact string that shipped broken.
#[test]
fn the_guard_catches_the_prompt_that_actually_shipped() {
    let shipped = "Use a tool when the user asks for something a tool can do. Answer with `done` \
                   when the task is complete.";
    assert_eq!(
        unknown_tools_named_in(shipped),
        vec!["done".to_string()],
        "the checker must reject the prompt that told the model to call a removed tool"
    );

    // …and it must not reject a prompt that names a real one.
    assert!(unknown_tools_named_in("Call `read` to read a file.").is_empty());
}

/// **The conversation survives the turn.**
///
/// `ask_streaming` built a fresh `SessionState` on every request, so Marlowe was handed turn 1
/// every time and could not summarize a conversation he was in. Asserted on the daemon's own
/// store, driven through two turns on one session name.
#[test]
fn a_second_turn_on_the_same_session_can_see_the_first() {
    let scratch = std::env::temp_dir().join(format!("marlowe-session-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();

    let mut config = marlowe_daemon::DaemonConfig::new(scratch.clone(), scratch.clone());
    config.port = 0;
    let Ok(mut daemon) = marlowe_daemon::Daemon::open(config) else {
        // No profile/scope on this platform; the store is still covered by the unit tests.
        return;
    };

    let turns = daemon.session_turn_count("cli");
    assert_eq!(turns, 0, "a session that has never spoken has no history");

    daemon.remember_user_turn("cli", "my favourite colour is green");
    assert_eq!(
        daemon.session_turn_count("cli"),
        1,
        "the first turn must be stored, or the second turn starts from nothing"
    );

    daemon.remember_user_turn("cli", "what did I just say?");
    assert_eq!(
        daemon.session_turn_count("cli"),
        2,
        "the second turn must ADD to the first, not replace it — this is the amnesia bug"
    );

    let _ = std::fs::remove_dir_all(&scratch);
}
