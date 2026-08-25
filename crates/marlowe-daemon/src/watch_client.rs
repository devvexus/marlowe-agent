//! **The client half of the control plane, and the projection a window renders.**
//! `M3-DESIGN.md` §6.
//!
//! Two things live here and they are deliberately separate:
//!
//! 1. [`ControlClient`] — connect, authenticate, send one control-plane request, read the answer.
//!    It is the conversation client's shape with a different port and a smaller vocabulary.
//! 2. [`RunProjection`] — fold [`Event::RunDetail`] and [`Event::RunOutput`] into a
//!    [`marlowe_view::RunView`]. **This is where "one state, two renderings" is made true**: the
//!    projection holds only what the last poll said, and every poll replaces it.
//!
//! # The projection holds frames, not a transcript
//!
//! A window could accumulate entries as they arrive and never look back. It does not, and the
//! reason is §6.6: *"The window renders the same control-plane state the Runs tab reports and never
//! keeps its own."* Frames are kept **by sequence** and re-projected into entries on every poll, so
//! a re-sent tail overwrites rather than appends — and a window that reconnects to a daemon that
//! restarted shows what the daemon has, not what the window remembers.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

use marlowe_view::notice::Speech;
use marlowe_view::run::{CheckpointView, OrphanPolicyLabel, ResumeState, RunState, RunView};
use marlowe_view::{Entry, ResultSummary, ToolCall, ToolLineState};

use crate::protocol::{read_line, write_line, Event, Request, RunFrame};

/// Why a window could not reach a run. **Each variant is a different thing to do about it**, which
/// is the whole reason this is not one `String`.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum WatchError {
    #[error(
        "no daemon has published a control port for this profile. Start one with \
         `marlowe --serve`, or open the TUI, which starts one"
    )]
    NoDaemon,
    #[error(
        "a daemon published port {port} and nothing is listening there. It has stopped since; \
         start it again with `marlowe --serve`"
    )]
    Stale { port: u16 },
    #[error("{detail}")]
    Refused { detail: String },
    #[error("the control plane closed the connection: {detail}")]
    Closed { detail: String },
}

/// Speaks to the control plane. One request per connection, like the conversation client.
#[derive(Debug, Clone)]
pub struct ControlClient {
    profile_root: PathBuf,
    token: String,
    port: u16,
}

impl ControlClient {
    /// Find the running daemon's control plane for this profile.
    ///
    /// **A missing port file and a dead port are different errors**, and both are reported as
    /// themselves — see [`WatchError`]. Collapsing them into "not running" sends somebody looking
    /// for a daemon that is right there, or starting a second one on top of a first.
    pub fn connect(profile_root: impl Into<PathBuf>) -> Result<Self, WatchError> {
        let profile_root = profile_root.into();
        let port = crate::watch::read_port(&profile_root).ok_or(WatchError::NoDaemon)?;
        let token = crate::auth::read_token(&profile_root).ok_or(WatchError::NoDaemon)?;
        let me = Self { profile_root, token, port };
        // Probe now rather than on the first poll, so the refusal names the cause instead of
        // arriving as a blank window that never fills.
        me.open()?;
        Ok(me)
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn profile_root(&self) -> &Path {
        &self.profile_root
    }

    fn open(&self) -> Result<TcpStream, WatchError> {
        let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, self.port));
        let stream = TcpStream::connect_timeout(&addr, Duration::from_millis(1_500))
            .map_err(|_| WatchError::Stale { port: self.port })?;
        stream.set_read_timeout(Some(Duration::from_secs(10))).ok();
        Ok(stream)
    }

    pub fn send(&self, request: &Request) -> Result<Vec<Event>, WatchError> {
        let stream = self.open()?;
        let mut writer = stream
            .try_clone()
            .map_err(|e| WatchError::Closed { detail: e.to_string() })?;
        // The preamble, then the request — the connection is authenticated, not the request.
        writeln!(writer, "{}", self.token).map_err(|e| WatchError::Closed { detail: e.to_string() })?;
        write_line(&mut writer, request).map_err(|e| WatchError::Closed { detail: e.to_string() })?;

        let mut reader = BufReader::new(stream);
        let mut events = Vec::new();
        loop {
            // LOOP-EXEMPT: reading a response stream, not a driving loop.
            let mut line = String::new();
            match reader.read_line(&mut line) {
                Ok(0) => break,
                Ok(_) if line.trim().is_empty() => continue,
                Ok(_) => match serde_json::from_str::<Event>(line.trim()) {
                    Ok(Event::Error { detail }) if detail.starts_with(crate::auth::REFUSED) => {
                        return Err(WatchError::Refused { detail });
                    }
                    Ok(e) => events.push(e),
                    Err(e) => return Err(WatchError::Closed { detail: e.to_string() }),
                },
                Err(e) => return Err(WatchError::Closed { detail: e.to_string() }),
            }
        }
        Ok(events)
    }

    pub fn watch(&self, run: &str, since: u64) -> Result<Vec<Event>, WatchError> {
        self.send(&Request::Watch { run: run.to_string(), since })
    }

    /// **A write.** ADR-054: the text crosses unvalidated and the daemon's `admit` is the only
    /// thing that turns it into a `SteerMessage`. A cap here would be a second cap.
    pub fn steer(&self, run: &str, text: &str) -> Result<(), WatchError> {
        accepted(self.send(&Request::Steer { run: run.to_string(), text: text.to_string() })?)
    }

    pub fn cancel(&self, run: &str) -> Result<(), WatchError> {
        accepted(self.send(&Request::CancelRun { run: run.to_string() })?)
    }

    pub fn resume(&self, run: &str) -> Result<(), WatchError> {
        accepted(self.send(&Request::ResumeRun { run: run.to_string() })?)
    }

    /// Every run the daemon holds, as `RunDetail` frames. What `/runs` from outside reads.
    pub fn runs(&self) -> Result<Vec<Event>, WatchError> {
        self.send(&Request::Runs)
    }
}

/// A write is `Accepted` or it is an error. **Silence is neither**, and treating an empty answer as
/// success is how a steer that never arrived reads as one that did — finding E10's shape.
fn accepted(events: Vec<Event>) -> Result<(), WatchError> {
    for e in &events {
        match e {
            Event::Accepted { .. } => return Ok(()),
            Event::Error { detail } => return Err(WatchError::Refused { detail: detail.clone() }),
            _ => {}
        }
    }
    Err(WatchError::Closed {
        detail: "the control plane neither accepted nor refused it".into(),
    })
}

/// Folds control-plane frames into the [`RunView`] a window draws.
#[derive(Debug, Default)]
pub struct RunProjection {
    id: String,
    detail: Option<Event>,
    /// **Keyed by sequence, not appended**, so a re-sent growing tail overwrites. See the header.
    frames: BTreeMap<u64, RunFrame>,
    /// The highest sequence seen, which is what the next poll asks from.
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
    /// seen.
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

    /// Whether a detail frame has ever arrived. A window with none has nothing true to draw.
    pub fn has_detail(&self) -> bool {
        self.detail.is_some()
    }

    /// The view, or `None` before the first answer.
    ///
    /// **`None` rather than an invented default.** `RunView` has no `Default` for exactly this
    /// reason: a window that could conjure one would show a run's identity panel filled with
    /// zeroes, which is a claim about a run rather than an absence of one.
    pub fn view(&self) -> Option<RunView> {
        let Some(Event::RunDetail {
            status,
            detail,
            started_ms,
            finished_ms,
            spend_micros_usd,
            ceiling_micros_usd,
            last_checkpoint,
            resume_from,
            resume_refused,
            orphan_policy,
            ..
        }) = &self.detail
        else {
            return None;
        };

        Some(RunView {
            id: short_id(&self.id),
            state: state_of(status, detail),
            started_ms: *started_ms,
            finished_ms: (*finished_ms != 0).then_some(*finished_ms),
            spend_micros_usd: *spend_micros_usd,
            ceiling_micros_usd: *ceiling_micros_usd,
            checkpoint: CheckpointView {
                last_completed: *last_checkpoint,
                resume: match resume_from {
                    Some(seq) => ResumeState::From { seq: *seq },
                    None => ResumeState::Refused(resume_refused.clone()),
                },
            },
            orphan_policy: policy_of(orphan_policy),
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
                // **The speech so far this turn was reasoning after all.** The window moves it,
                // so no text that belonged inside a think block is left in the response colour —
                // the same correction the main pane makes on `SpeechRetracted`.
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
        // A reasoning block followed by anything is finished thinking. Marking it `done` is what
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
/// **Unknown words become `Paused` carrying the word itself**, rather than a silent default. A
/// status the window does not recognise is a fact it should still show — the alternative is a
/// window that renders a run it does not understand and looks fine doing it.
fn state_of(status: &str, detail: &str) -> RunState {
    match status {
        "queued" => RunState::Queued,
        "running" => RunState::Running,
        "waiting" => RunState::WaitingEvent,
        "completed" => RunState::Completed,
        "cancelled" => RunState::Cancelled,
        "failed" => RunState::Failed { error: detail.to_string() },
        "paused" => RunState::Paused { reason: detail.to_string() },
        other => RunState::Paused { reason: other.to_string() },
    }
}

fn policy_of(s: &str) -> OrphanPolicyLabel {
    match s {
        "terminate" => OrphanPolicyLabel::Terminate,
        other if other.starts_with("adopt:") => {
            OrphanPolicyLabel::Adopt { by: short_id(&other["adopt:".len()..]) }
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
    // **The summary arrives already rendered** — the daemon called `ResultSummary::render` on the
    // typed form before it crossed the wire. It is carried as the expansion `detail` rather than
    // re-parsed back into metrics: parsing a string the harness formatted, to rebuild the values it
    // was formatted from, is a second definition of §B6's summary grammar and it would be wrong the
    // first time a metric changed.
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
            detail: String::new(),
            started_ms: 1_000,
            finished_ms: 0,
            spend_micros_usd: 120_000,
            ceiling_micros_usd: 3_000_000,
            last_checkpoint: Some(41),
            resume_from: None,
            resume_refused: "no durable checkpoint".into(),
            orphan_policy: "detach".into(),
            latest_seq: 0,
        }
    }

    #[test]
    fn a_projection_with_no_answer_yet_has_no_view_rather_than_an_invented_one() {
        // `RunView` has no `Default` precisely so this cannot be a screen of zeroes presented as a
        // run's identity.
        let p = RunProjection::new("r");
        assert!(p.view().is_none());
        assert!(!p.has_detail());
    }

    #[test]
    fn a_re_sent_tail_overwrites_rather_than_appending() {
        // The failure this prevents: a live run's last paragraph arriving twice, once half-written
        // and once whole, one under the other.
        let mut p = RunProjection::new("r");
        p.apply(&[detail_event("running"), Event::RunOutput {
            seq: 1,
            frame: RunFrame::Text { delta: "half".into() },
        }]);
        p.apply(&[Event::RunOutput { seq: 1, frame: RunFrame::Text { delta: "half a line".into() } }]);
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
        let v = p.view().unwrap();
        assert_eq!(
            v.output,
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
    fn a_refused_resume_becomes_the_control_planes_words_and_not_a_rewording() {
        let mut p = RunProjection::new("r");
        p.apply(&[detail_event("running")]);
        let v = p.view().unwrap();
        assert_eq!(v.checkpoint.resume, ResumeState::Refused("no durable checkpoint".into()));
        assert_eq!(v.checkpoint.last_completed, Some(41));
    }

    #[test]
    fn a_status_the_window_does_not_know_is_shown_rather_than_defaulted_away() {
        let mut p = RunProjection::new("r");
        p.apply(&[detail_event("marinating")]);
        let v = p.view().unwrap();
        assert_eq!(v.state, RunState::Paused { reason: "marinating".into() });
    }

    #[test]
    fn a_finished_run_reports_a_finish_time_and_a_live_one_does_not() {
        let mut p = RunProjection::new("r");
        p.apply(&[detail_event("running")]);
        assert_eq!(p.view().unwrap().finished_ms, None, "0 must read as absent, not as the epoch");
    }

    #[test]
    fn a_write_that_was_neither_accepted_nor_refused_is_an_error() {
        // Silence is not success. Finding E10's shape: a steer that vanished with no error.
        assert!(accepted(Vec::new()).is_err());
        assert!(accepted(vec![Event::Accepted { what: "steer".into() }]).is_ok());
        assert!(accepted(vec![Event::Error { detail: "no run".into() }]).is_err());
    }
}
