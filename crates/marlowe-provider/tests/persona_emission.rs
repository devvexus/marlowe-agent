//! **The persona reaches the outbound request, or this fails.**
//!
//! Addendum C §C6 puts the persona in the stable tier of the system prompt. The only check worth
//! having is that it arrives in the bytes the provider is sent.
//!
//! # Loading is not emission, and this project has paid for that distinction twice
//!
//! A test that read `persona/v1.md` and asserted it was non-empty would prove the file loaded. It
//! would pass with the persona wired to nothing, and it would have passed for every day of M2 C2c,
//! when the artifact did not exist and a 40-word `const` went to the model under a doc comment
//! claiming it "carries the persona (Addendum C)".
//!
//! The same shape, three times, in three subsystems:
//!
//! | Weaker claim | Stronger claim |
//! |---|---|
//! | `get_providers()` lists CUDA as *registered* | where the nodes actually **ran** (M0c L) |
//! | the §13 hook's matcher recognises a path string | an **observed** permission prompt on a real edit |
//! | `persona/v1.md` loaded | the persona text is **in the request body** |
//!
//! Each weaker claim is true, cheap, and answers a question adjacent to the one being asked.

use marlowe_contract::TrustClass;
use marlowe_loop::{Assembler, Block, CallLimits, ContextView, SessionId, SessionState, SourceKind};
use marlowe_provider::{OllamaDriver, Routing};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId};

/// A phrase from `persona/v1.md` distinctive enough that no other stable-tier text would contain
/// it, and short enough to survive reflowing the artifact.
///
/// **Not the whole file**, deliberately: asserting byte equality would make every wording change a
/// test failure, which trains people to update the assertion without reading it. A marker fails
/// when the persona stops arriving and passes when it is merely edited.
const MARKER: &str = "You are not impressed";

fn view_with_persona() -> ContextView {
    // Built the way the daemon builds it: the persona goes into `identity`, the assembler puts
    // identity in the stable tier, and the driver turns the stable tier into `system` messages.
    let persona = include_str!("../../../persona/v1.md");
    let mut state = SessionState::new(SessionId::new(), persona);
    state.push(Block::new(
        SourceKind::History,
        "read notes.md".to_string(),
        TrustClass::UserAsserted,
    ));
    Assembler::new(8_192, 1_024).assemble(&state)
}

fn driver() -> OllamaDriver {
    OllamaDriver::new(
        marlowe_provider::LocalEndpoint::default_ollama(),
        Routing::uniform(marlowe_provider::DEFAULT_MODEL).expect("a uniform route"),
        builtin_registry().expect("the builtins are compiled in"),
    )
}

fn limits() -> CallLimits {
    CallLimits { max_output_tokens: 512 }
}

#[test]
fn the_persona_reaches_the_outbound_request_body() {
    let tools = ExposedSet::new(vec![ToolId::new("read")]).expect("one tool fits");
    let body = driver().request_body(&view_with_persona(), &tools, limits());

    let messages = body
        .get("messages")
        .and_then(|m| m.as_array())
        .expect("the request carries messages");

    // The parse is asserted before the presence is. A reader that found no messages would
    // otherwise report "no persona" for a body full of it — and would report the same thing if the
    // persona were genuinely absent. Two different failures must not print the same way.
    assert!(!messages.is_empty(), "no messages in the body: {body}");

    let system: String = messages
        .iter()
        .filter(|m| m.get("role").and_then(|r| r.as_str()) == Some("system"))
        .filter_map(|m| m.get("content").and_then(|c| c.as_str()))
        .collect::<Vec<_>>()
        .join("\n");

    assert!(
        !system.is_empty(),
        "the request has no system message at all, so nothing could carry the persona: {body}"
    );
    assert!(
        system.contains(MARKER),
        "the persona did not reach the outbound request.\n\n\
         Addendum C §C6 puts it in the stable tier of the system prompt, and §C0 makes it apply to \
         anything producing user-visible prose. A persona that loads and never reaches the wire is \
         the exact failure this test exists for — the model sounds generic and nothing reports a \
         problem.\n\n\
         system tier was:\n{system}"
    );
}

#[test]
fn the_persona_is_in_the_stable_tier_and_not_a_user_turn() {
    // §C6: stable tier, so it is cache-friendly and survives compaction structurally. If it
    // arrived as a `user` message it would still be "present" and a naive contains() over the
    // whole body would still pass — while being re-sent every turn and dropped by compaction.
    let tools = ExposedSet::new(vec![ToolId::new("read")]).expect("one tool fits");
    let body = driver().request_body(&view_with_persona(), &tools, limits());
    let messages = body.get("messages").and_then(|m| m.as_array()).expect("messages");

    let carrying: Vec<&str> = messages
        .iter()
        .filter(|m| {
            m.get("content")
                .and_then(|c| c.as_str())
                .is_some_and(|c| c.contains(MARKER))
        })
        .filter_map(|m| m.get("role").and_then(|r| r.as_str()))
        .collect();

    assert_eq!(
        carrying,
        vec!["system"],
        "the persona must appear exactly once, in the system role. Found it in {carrying:?}"
    );
}

/// The artifact is the source, and nothing may quietly reintroduce a copy in the code.
///
/// §C6: *"Not a string in the code."* A second copy would drift from the artifact, and the diff
/// review the artifact exists to enable would be reviewing the wrong text.
#[test]
fn the_persona_text_exists_in_exactly_one_place() {
    use std::path::Path;
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().expect("crates/");
    let mut copies = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for e in entries.flatten() {
            let p = e.path();
            if p.is_dir() {
                if p.file_name().is_some_and(|n| n == "target") {
                    continue;
                }
                stack.push(p);
            } else if p.extension().is_some_and(|x| x == "rs") {
                // This file names the marker in order to assert on it.
                if p.file_name().is_some_and(|n| n == "persona_emission.rs") {
                    continue;
                }
                if std::fs::read_to_string(&p).unwrap_or_default().contains(MARKER) {
                    copies.push(p.display().to_string());
                }
            }
        }
    }
    assert!(
        copies.is_empty(),
        "the persona text appears inside Rust source, which §C6 forbids — the artifact is the \
         single source and a copy will drift from it:\n{}",
        copies.join("\n")
    );
}

/// **Marlowe's own words go out as `assistant`, never as `user`.**
///
/// The bug this pins was invisible from every unit test and obvious the moment a human read the
/// screen: every non-stable block was sent as `role: "user"`, so the model received its own last
/// reply attributed to the user and answered it.
///
///     Hello. What do you need?   →   Nothing in particular.   →   Nothing yet either.
///
/// `/api/chat` carries four roles for exactly this reason. Collapsing them threw away the
/// distinction the endpoint exists to make, and the symptom looked like a model defect.
#[test]
fn history_roles_follow_who_actually_said_it() {
    use marlowe_loop::{Assembler, Block, CallLimits, SessionId, SessionState, SourceKind};

    let mut state = SessionState::new(SessionId::new(), "identity");
    state.push(Block::new(SourceKind::History, "what is 2+2", TrustClass::UserAsserted));
    state.push(Block::new(SourceKind::History, "Four.", TrustClass::AgentInferred));
    state.push(Block::new(SourceKind::ToolResults, "48 lines", TrustClass::AgentObserved));
    let view = Assembler::new(16_384, 1_024).assemble(&state);

    let tools = ExposedSet::new(vec![ToolId::new("read")]).expect("one tool fits");
    let body = driver().request_body(&view, &tools, CallLimits { max_output_tokens: 128 });
    let messages = body.get("messages").and_then(|m| m.as_array()).expect("messages");

    let role_of = |needle: &str| -> Option<String> {
        messages
            .iter()
            .find(|m| {
                m.get("content")
                    .and_then(|c| c.as_str())
                    .is_some_and(|c| c.contains(needle))
            })
            .and_then(|m| m.get("role").and_then(|r| r.as_str()))
            .map(str::to_string)
    };

    assert_eq!(role_of("what is 2+2").as_deref(), Some("user"));
    assert_eq!(
        role_of("Four.").as_deref(),
        Some("assistant"),
        "Marlowe's own reply reached the model as a USER turn, so it will answer itself. Body:\n{body:#}"
    );
    assert_eq!(role_of("48 lines").as_deref(), Some("tool"));

    // And the persona is still where §C6 puts it.
    assert_eq!(role_of("identity").as_deref(), Some("system"));
}
