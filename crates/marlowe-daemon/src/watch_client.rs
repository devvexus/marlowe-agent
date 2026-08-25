//! **The projection a run window renders.** `M3-DESIGN.md` §6.
//!
//! # What used to be here, and why it is gone
//!
//! This file also held a `ControlClient` — connect, authenticate, send one control-plane request.
//! **Session A's [`crate::Client`] does all of that and does it better**: `Client::control()` reads
//! the advertised port, and `control_or_main` falls back to the main port when no control plane is
//! listening, so a caller cannot get it right for `/runs` and wrong for `/steer`. Two clients for
//! one daemon is the two-definitions shape, and the one that survives is the one that already
//! handles the fall-back.
//!
//! What is left is the part A did not build: folding output frames into a [`RunView`].
//!
//! # The projection holds frames, not a transcript
//!
//! A window could accumulate entries as they arrive and never look back. It does not, and the
//! reason is §6.6: *"The window renders the same control-plane state the Runs tab reports and never
//! keeps its own."* Frames are kept **by sequence** and re-projected on every poll, so a re-sent
//! growing tail overwrites rather than appends — and a window that reconnects to a daemon that
//! restarted shows what the daemon has, not what the window remembers.

use std::collections::BTreeMap;

use marlowe_view::notice::Speech;
use marlowe_view::run::{CheckpointView, OrphanPolicyLabel, RunState, RunView};
use marlowe_view::{Entry, ResultSummary, ToolCall, ToolLineState};

use crate::protocol::{Event, RunFrame};

/// Folds control-plane frames into the [`RunView`] a window draws.
#[derive(Debug, Default)]
pub struct RunProjection {
    id: String,
    detail: Option<Event>,
    /// **Keyed by sequence, not appended**, so a re-sent growing tail overwrites. See the header.
    frames: BTreeMap<u64, RunFrame>,
    latest: u64,
}

impl RunProjection {
    pub fn new(run: impl Into<String>) -> Self {
        Self { id: run.into(), ..Default::default() }
    }

    /// What to pass as `since` on the next poll.
    ///
    /// The **highest** sequence, not one past it: the tail frame is still growing, and asking from
    /// one past it would freeze a live run's last paragraph at whatever it held when it was first
    /// seen. `ControlPlane::frames_since` filters on `seq >= since` to match.
    pub fn since(&self) -> u64 {
        self.latest
    }

    pub fn apply(&mut self, events: &[Event]) {
        for e in events {
            match e {
                Event::RunDetail { .. } => self.detail = Some(e.clone()),
                Event::RunOutput { seq, frame } => {
                    self.frames.insert(*seq, frame.clone());
                    self.latest = self.latest.max(*seq);
                }
                _ => {}
            }
        }
    }

    pub fn has_detail(&self) -> bool {
        self.detail.is_some()
    }

    /// The view, or `None` before the first answer.
    ///
    /// **`None` rather than an invented default.** `RunView` has no `Default` for exactly this
    /// reason: a window that could conjure one would show an identity panel full of zeroes, which
    /// is a claim about a run rather than an absence of one.
    pub fn view(&self) -> Option<RunView> {
        let Some(Event::RunDetail {
            status,
            parent,
            elapsed_ms,
            spend_micros_usd,
            ceiling_micros_usd,
            spent_tokens,
            granted_tokens,
            depth,
            last_checkpoint_step,
            resumable,
            orphan_policy,
            pending_steers,
            ..
        }) = &self.detail
        else {
            return None;
        };

        Some(RunView {
            id: short_id(&self.id),
            state: state_of(status),
            parent: parent.as_deref().map(short_id),
            elapsed_ms: *elapsed_ms,
            spend_micros_usd: *spend_micros_usd,
            ceiling_micros_usd: *ceiling_micros_usd,
            spent_tokens: *spent_tokens,
            granted_tokens: *granted_tokens,
            depth: *depth,
            checkpoint: CheckpointView {
                last_completed: *last_checkpoint_step,
                resumable: *resumable,
            },
            orphan_policy: policy_of(orphan_policy),
            pending_steers: *pending_steers,
            output: self.entries(),
            // §6.3's placeholders. **Empty because nothing produces them**, which is a fact and
            // stays one for a childless run after the roster lands.
            subagents: Vec::new(),
            budget: Vec::new(),
            scope_memory: Vec::new(),
            meetings: Vec::new(),
        })
    }

    /// Frames, in sequence, as the transcript vocabulary the conversation pane already uses.
    fn entries(&self) -> Vec<Entry> {
        let mut out: Vec<Entry> = Vec::new();
        for frame in self.frames.values() {
            match frame {
                RunFrame::Text { delta } => out.push(Entry::Said(Speech::Model(delta.clone()))),
                RunFrame::Reasoning { delta } => {
                    out.push(Entry::Reasoning { text: delta.clone(), done: false })
                }
                // **The speech so far this turn was reasoning after all.** The window moves it, so
                // no text that belonged inside a think block is left in the response colour — the
                // same correction the main pane makes on `SpeechRetracted`.
                RunFrame::SpeechRetracted => {
                    if let Some(Entry::Said(Speech::Model(text))) = out.pop() {
                        out.push(Entry::Reasoning { text, done: true });
                    }
                }
                RunFrame::Tool { id, verb, target, state, summary } => {
                    out.push(Entry::Tools(vec![tool_call(*id, verb, target, state, summary)]))
                }
                RunFrame::Compacted { turns } => out.push(Entry::Compacted { turns: *turns }),
            }
        }
        // A reasoning block with anything after it is finished thinking. Marking it `done` is what
        // stops a completed run showing `thinking…` forever.
        let last = out.len().saturating_sub(1);
        for (i, e) in out.iter_mut().enumerate() {
            if let Entry::Reasoning { done, .. } = e {
                if i < last {
                    *done = true;
                }
            }
        }
        out
    }
}

/// The first eight characters of a run id. Long enough to be unambiguous among a day's runs, short
/// enough to sit in a titlebar beside a status word.
pub fn short_id(id: &str) -> String {
    id.chars().take(8).collect()
}

/// The daemon's status word as the render-only state.
///
/// **An unrecognised word is shown, never defaulted away.** A status the window does not know is
/// still a fact it should display; the alternative is a window rendering a run it does not
/// understand and looking fine doing it.
fn state_of(status: &str) -> RunState {
    match status {
        "queued" => RunState::Queued,
        "running" => RunState::Running,
        "waiting" => RunState::WaitingEvent,
        "completed" => RunState::Completed,
        "cancelled" => RunState::Cancelled,
        // Session A's word for a run the daemon has *asked* to stop. It has not stopped yet, so it
        // is not `Cancelled` — that would be the surface reporting an outcome it does not have.
        "cancelling" => RunState::Paused { reason: "cancelling at its next step".into() },
        // Session A's word for a run that stopped because the process did. This is the state a
        // resume exists for, and it must not read as a failure.
        "interrupted" => RunState::Paused { reason: "interrupted — the daemon stopped".into() },
        "failed" => RunState::Failed { error: String::new() },
        other => RunState::Paused { reason: other.to_string() },
    }
}

/// Session A's `orphan_policy` string. **Parsed, never re-derived** — it is declared at spawn.
fn policy_of(s: &str) -> OrphanPolicyLabel {
    match s {
        "terminate" => OrphanPolicyLabel::Terminate,
        other if other.starts_with("adopt by ") => {
            OrphanPolicyLabel::Adopt { by: short_id(&other["adopt by ".len()..]) }
        }
        _ => OrphanPolicyLabel::Detach,
    }
}

/// One §B6 line off the wire.
///
/// **`verb` is matched against the builtins**, exactly as `project.rs` does and for the same
/// reason: `ToolCall::verb` is `&'static str` because §B6's vocabulary is closed, and an arbitrary
/// string off the wire is not one. This is the second reader of that mapping and it is a copy —
/// noted here rather than left to be discovered, because the honest fix is for `project.rs` to
/// export it, and doing that from a window session would edit the main pane's render path.
fn tool_call(id: u64, verb: &str, target: &str, state: &str, summary: &str) -> ToolCall {
    let verb: &'static str = match verb {
        "read" => "read",
        "edit" => "edit",
        "find" => "find",
        "run" => "run",
        "bash" => "bash",
        "web" => "web",
        "recall" => "recall",
        "remember" => "remember",
        "use" => "use",
        "ask" => "ask",
        "subagent" => "subagent",
        _ => "tool",
    };
    // **The summary arrives already rendered** — the daemon called `ResultSummary::render` before
    // it crossed the wire. It is carried as the expansion `detail` rather than parsed back into
    // metrics: parsing a string the harness formatted, to rebuild the values it was formatted from,
    // is a second definition of §B6's summary grammar and would be wrong the first time a metric
    // changed.
    let summary_line = ResultSummary::with_detail(Vec::new(), summary.to_string());
    ToolCall {
        id,
        verb,
        target: target.to_string(),
        state: match state {
            "failed" => ToolLineState::Failed(summary_line),
            "running" => ToolLineState::Running { elapsed_ms: 0 },
            _ => ToolLineState::Ok(summary_line),
        },
        collapsed: Vec::new(),
        // §B6 auto-expands a failure. The window inherits that rather than deciding it again.
        expanded: state == "failed",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn detail_event(status: &str) -> Event {
        Event::RunDetail {
            id: "a1b2c3d4e5f6".into(),
            status: status.into(),
            parent: None,
            elapsed_ms: 93_000,
            spend_micros_usd: 120_000,
            ceiling_micros_usd: 3_000_000,
            spent_tokens: 400,
            granted_tokens: 50_000,
            depth: 0,
            last_checkpoint_step: Some(41),
            resumable: true,
            orphan_policy: "detach".into(),
            pending_steers: 0,
        }
    }

    #[test]
    fn a_projection_with_no_answer_yet_has_no_view_rather_than_an_invented_one() {
        let p = RunProjection::new("r");
        assert!(p.view().is_none());
        assert!(!p.has_detail());
    }

    #[test]
    fn a_re_sent_tail_overwrites_rather_than_appending() {
        // The failure this prevents: a live run's last paragraph arriving twice, once half-written
        // and once whole, one under the other.
        let mut p = RunProjection::new("r");
        p.apply(&[
            detail_event("running"),
            Event::RunOutput { seq: 1, frame: RunFrame::Text { delta: "half".into() } },
        ]);
        p.apply(&[Event::RunOutput {
            seq: 1,
            frame: RunFrame::Text { delta: "half a line".into() },
        }]);
        let v = p.view().unwrap();
        assert_eq!(v.output.len(), 1, "the tail appended instead of overwriting: {:?}", v.output);
        assert_eq!(v.output[0], Entry::Said(Speech::Model("half a line".into())));
    }

    #[test]
    fn the_next_poll_asks_from_the_highest_sequence_not_one_past_it() {
        let mut p = RunProjection::new("r");
        p.apply(&[Event::RunOutput { seq: 7, frame: RunFrame::Text { delta: "x".into() } }]);
        assert_eq!(p.since(), 7, "asking from 8 would freeze frame 7 while it was still growing");
    }

    #[test]
    fn retracted_speech_becomes_a_finished_thought_rather_than_staying_an_answer() {
        let mut p = RunProjection::new("r");
        p.apply(&[
            detail_event("running"),
            Event::RunOutput { seq: 1, frame: RunFrame::Text { delta: "let me think".into() } },
            Event::RunOutput { seq: 2, frame: RunFrame::SpeechRetracted },
        ]);
        assert_eq!(
            p.view().unwrap().output,
            vec![Entry::Reasoning { text: "let me think".into(), done: true }],
            "text that belonged in a think block was left in the response colour"
        );
    }

    #[test]
    fn a_finished_run_does_not_show_thinking_forever() {
        let mut p = RunProjection::new("r");
        p.apply(&[
            detail_event("completed"),
            Event::RunOutput { seq: 1, frame: RunFrame::Reasoning { delta: "weighing".into() } },
            Event::RunOutput { seq: 2, frame: RunFrame::Text { delta: "four".into() } },
        ]);
        let v = p.view().unwrap();
        assert!(
            matches!(v.output[0], Entry::Reasoning { done: true, .. }),
            "a reasoning block with an answer after it is finished: {:?}",
            v.output
        );
    }

    #[test]
    fn the_checkpoint_comes_through_as_the_two_facts_it_is() {
        let mut p = RunProjection::new("r");
        p.apply(&[detail_event("running")]);
        let v = p.view().unwrap();
        assert_eq!(v.checkpoint.last_completed, Some(41));
        assert!(v.checkpoint.resumable);
    }

    /// **Session A's two words for a stopped run, and neither may read as a failure.**
    ///
    /// `interrupted` is what a run that died with the daemon is called — the state a resume exists
    /// for. `cancelling` is a run that has been *asked* to stop and has not yet. Rendering either
    /// in the failure colour would tell the user something went wrong when nothing did.
    #[test]
    fn sessions_a_own_status_words_survive_the_projection() {
        for (word, expected) in [
            ("interrupted", "interrupted"),
            ("cancelling", "cancelling"),
        ] {
            let mut p = RunProjection::new("r");
            p.apply(&[detail_event(word)]);
            let v = p.view().unwrap();
            match &v.state {
                RunState::Paused { reason } => {
                    assert!(reason.contains(expected), "{word}: {reason}")
                }
                other => panic!("{word} rendered as {other:?}, which is not what it means"),
            }
            assert_ne!(v.state.tone(), marlowe_view::Tone::Red, "{word} read as a failure");
        }
    }

    #[test]
    fn a_status_the_window_does_not_know_is_shown_rather_than_defaulted_away() {
        let mut p = RunProjection::new("r");
        p.apply(&[detail_event("marinating")]);
        assert_eq!(
            p.view().unwrap().state,
            RunState::Paused { reason: "marinating".into() }
        );
    }

    #[test]
    fn an_adopted_runs_policy_names_the_run_that_adopted_it() {
        // Session A formats this as `adopt by <uuid>`; parsing it wrong would silently render
        // every adopted run as detached, which is the opposite claim about its children.
        assert_eq!(
            policy_of("adopt by a1b2c3d4e5f6"),
            OrphanPolicyLabel::Adopt { by: "a1b2c3d4".into() }
        );
        assert_eq!(policy_of("detach"), OrphanPolicyLabel::Detach);
        assert_eq!(policy_of("terminate"), OrphanPolicyLabel::Terminate);
    }
}
