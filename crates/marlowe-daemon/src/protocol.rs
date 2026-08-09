//! What crosses the client/daemon boundary. ARCHITECTURE §6.
//!
//! # The boundary is the point, not the transport
//!
//! §6 splits the binary into a thin client and a daemon **because of invariant 6**: if the client
//! owned the run, closing the terminal would end it. So the shape of this protocol is constrained
//! by one rule — **the client may hold nothing the daemon does not have.** A request names a
//! session and a message; a response is a stream of render-only events. There is no request that
//! hands the client a `Run`, a `Checkpoint`, or a `ContextView`, and there must not be one.
//!
//! That is also why the client can paint before this connection resolves (§B13's 150 ms first
//! frame): there is nothing in the first frame that comes from here.
//!
//! # NDJSON over loopback
//!
//! Same framing as the §4.0 eval transport, for the same reason it gives: the wire log is
//! readable with ordinary tools. One JSON value per line, `\n`-terminated, flushed per frame.

use serde::{Deserialize, Serialize};

/// Client → daemon.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Request {
    /// What is the daemon, and is it healthy? Answered without touching a model.
    Status,
    /// Start a turn. The daemon owns the run; the client gets events.
    Ask { session: String, message: String },
    /// List runs the daemon owns. **Read-only** — the client cannot mutate a run through it.
    Runs,
    /// Approve or decline a pending decision (§B9). The harness enforces; the model never sees
    /// this path.
    Approve { decision: u64, granted: bool },
    /// Stop the daemon.
    ///
    /// **Invariant 6 says a run survives the client that started it, not that the daemon is
    /// immortal.** Without this there is no way to stop one at all: closing the TUI leaves it
    /// listening, and the next launch reconnects to it — which is how a fixed build gets tested
    /// against a stale binary. It refuses while a run is live, so the invariant still holds where
    /// it means something.
    Shutdown,
}

/// Daemon → client. Render-only, mirroring `TurnEvent` plus the frames a client needs to know
/// the turn is over.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event {
    /// The daemon's identity and health, including what §B5's band needs.
    Status(StatusReport),
    Text { delta: String },
    /// A chunk of the model's reasoning. **Not the answer**, and never part of the transcript.
    Reasoning { delta: String },
    /// The speech streamed so far this turn was reasoning. The client moves it, and no text that
    /// belonged inside a think block is left in the response colour.
    SpeechRetracted,
    /// §B6's one line per call.
    Tool { id: u64, verb: String, target: String, state: String, summary: String },
    Compacted { turns: u32 },
    /// Invariant 4. Carries the **remedy**, not just the fact.
    Degraded { what: String, remedy: String },
    /// §B9. The client renders; the daemon decides.
    Approval { decision: u64, verb: String, scope: String, reversible: bool },
    /// The turn ended. `outcome` distinguishes completed / paused / escalated / failed.
    Done { outcome: String, detail: String, spend_micros_usd: u64, elapsed_ms: u64 },
    /// A run the daemon owns.
    Run { id: String, status: String, tokens: u64, depth: u8 },
    Error { detail: String },
}

/// What `Status` answers. Everything §B5's band and the first-run disclosure need, in one frame.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StatusReport {
    pub version: String,
    /// The workspace the run is scoped to. First-run onboarding states this (ADR-002).
    pub workspace: String,
    pub model: String,
    /// ADR-028 requirement 2 — carries its denominator, or says NOT MEASURED.
    pub model_disclosure: String,
    /// `None` when everything is ready. Otherwise the specific remedy.
    pub degraded: Option<String>,
    /// ADR-029: **the active provider is announced, never silently chosen.** This is read from
    /// the field the profile row already stamps; it is not a second source of the same fact.
    pub rerank_provider: String,
    /// Runs the daemon currently owns. Non-zero across a client restart is what makes
    /// invariant 6 observable rather than asserted.
    pub live_runs: usize,
}

/// Read one NDJSON value per line.
pub fn read_line<T: for<'de> Deserialize<'de>>(
    reader: &mut impl std::io::BufRead,
) -> std::io::Result<Option<T>> {
    let mut line = String::new();
    if reader.read_line(&mut line)? == 0 {
        return Ok(None);
    }
    if line.trim().is_empty() {
        return Ok(None);
    }
    serde_json::from_str(&line)
        .map(Some)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
}

/// Write one NDJSON value and flush. **A response sitting in a buffer is indistinguishable from
/// a hang** — the same rule §4.0.2 states for the eval transport.
pub fn write_line<T: Serialize>(
    writer: &mut impl std::io::Write,
    value: &T,
) -> std::io::Result<()> {
    let mut s = serde_json::to_string(value)?;
    s.push('\n');
    writer.write_all(s.as_bytes())?;
    writer.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_request_or_event_hands_the_client_run_state() {
        // ARCHITECTURE §2.14: surfaces hold no state the daemon lacks, and §6 splits the binary
        // because of invariant 6. A frame carrying a Checkpoint, a ContextView or a transcript
        // would let a client hold something the daemon owns — and would make "closing the
        // terminal ends the run" true again by the back door.
        let json = serde_json::to_string(&Event::Done {
            outcome: "completed".into(),
            detail: "42".into(),
            spend_micros_usd: 0,
            elapsed_ms: 10,
        })
        .unwrap();
        for forbidden in ["checkpoint", "transcript", "context_view", "provenance", "taint"] {
            assert!(!json.contains(forbidden), "`{forbidden}` crossed the boundary: {json}");
        }

        // And the Run frame is a summary, not the object.
        let run = serde_json::to_string(&Event::Run {
            id: "r".into(),
            status: "running".into(),
            tokens: 10,
            depth: 0,
        })
        .unwrap();
        assert!(!run.contains("profile"), "{run}");
        assert!(!run.contains("budget"), "{run}");
    }

    #[test]
    fn a_degraded_event_carries_its_remedy() {
        // Invariant 4 as a wire requirement: a client that received only "degraded" could not
        // tell the user what to do, and a degraded state a user cannot act on is a crash with
        // better manners.
        let e = Event::Degraded {
            what: "no model available".into(),
            remedy: "start it with `ollama serve`".into(),
        };
        let json = serde_json::to_string(&e).unwrap();
        assert!(json.contains("ollama serve"), "{json}");
    }

    #[test]
    fn frames_round_trip_as_ndjson() {
        let mut buf: Vec<u8> = Vec::new();
        write_line(&mut buf, &Request::Ask { session: "s".into(), message: "hi".into() }).unwrap();
        assert!(buf.ends_with(b"\n"), "every frame is newline-terminated");
        assert_eq!(buf.iter().filter(|b| **b == b'\n').count(), 1, "no embedded newlines");

        let mut reader = std::io::BufReader::new(&buf[..]);
        let back: Option<Request> = read_line(&mut reader).unwrap();
        assert_eq!(back, Some(Request::Ask { session: "s".into(), message: "hi".into() }));
    }

    #[test]
    fn the_status_report_announces_the_provider_rather_than_implying_it() {
        // ADR-029, inherited: the active provider is announced, never silently chosen, because
        // an unannounced fallback is indistinguishable from the failure mode it resembles.
        // `rerank_provider` is a REQUIRED field — a client cannot render the band without it,
        // so there is no path where it is quietly omitted.
        let r = StatusReport {
            version: "0.1.0".into(),
            workspace: "/ws".into(),
            model: "qwen3.5:9b".into(),
            model_disclosure: "qwen3.5:9b · tool calls 12/12".into(),
            degraded: None,
            rerank_provider: "cpu-sequential".into(),
            live_runs: 0,
        };
        let json = serde_json::to_string(&r).unwrap();
        assert!(json.contains("rerank_provider"), "{json}");
        // Not an Option: a missing announcement must be a compile error, not a None.
        let parsed: StatusReport = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.rerank_provider, "cpu-sequential");
    }
}
