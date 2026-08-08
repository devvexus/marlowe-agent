//! The loop's write path to the journal.
//!
//! ARCHITECTURE §7: *"Loop → Journal: **Nothing directly.** Requests only, via the harness."*
//! and *"Harness → Journal: `JournalEvent` (typed, signed)"*. The loop is harness code, so it
//! may append with `Actor::Harness`; what it may never do is hand the model a path to this.
//! There is no `ModelStep` variant that names an event kind, and there must not be one.
//!
//! A port rather than a concrete `Journal` for one reason that is not testing convenience: the
//! loop must be constructible in a context that has no profile on disk (the first frame, before
//! a daemon exists), and the alternative to a port there is an `Option<Journal>` with a silent
//! no-op branch — a write path that sometimes does not write, which is the shape that makes an
//! audit trail unfalsifiable.

use marlowe_contract::Clock;
use marlowe_journal::{Actor, AppendRequest, EventKind, Journal, Seq};

use crate::run::{RunId, SessionId};

pub trait Recorder {
    fn append(
        &mut self,
        clock: Clock,
        kind: EventKind,
        run: RunId,
        session: SessionId,
        payload: serde_json::Value,
    ) -> Result<Seq, String>;
}

/// The real one.
pub struct JournalRecorder<'a> {
    journal: &'a mut Journal,
    trace_id: uuid::Uuid,
}

impl<'a> JournalRecorder<'a> {
    pub fn new(journal: &'a mut Journal, trace_id: uuid::Uuid) -> Self {
        Self { journal, trace_id }
    }
}

impl Recorder for JournalRecorder<'_> {
    fn append(
        &mut self,
        clock: Clock,
        kind: EventKind,
        run: RunId,
        session: SessionId,
        payload: serde_json::Value,
    ) -> Result<Seq, String> {
        self.journal
            .append(
                clock,
                AppendRequest {
                    trace_id: self.trace_id,
                    session_id: Some(session.to_string()),
                    run_id: Some(run.to_string()),
                    actor: Actor::Harness,
                    kind,
                    payload,
                },
            )
            .map(|e| e.seq)
            .map_err(|e| e.to_string())
    }
}

/// An in-memory recorder, for tests and for the pre-daemon path.
///
/// It records the same sequence the journal would. It is **not** a no-op: a recorder that
/// dropped events would let a test assert on an audit trail that does not exist.
#[derive(Debug, Default)]
pub struct MemoryRecorder {
    pub events: Vec<(EventKind, RunId, serde_json::Value)>,
}

impl MemoryRecorder {
    pub fn kinds(&self) -> Vec<EventKind> {
        self.events.iter().map(|(k, _, _)| *k).collect()
    }

    pub fn count(&self, kind: EventKind) -> usize {
        self.events.iter().filter(|(k, _, _)| *k == kind).count()
    }

    pub fn payloads(&self, kind: EventKind) -> Vec<&serde_json::Value> {
        self.events.iter().filter(|(k, _, _)| *k == kind).map(|(_, _, p)| p).collect()
    }
}

impl Recorder for MemoryRecorder {
    fn append(
        &mut self,
        _clock: Clock,
        kind: EventKind,
        run: RunId,
        _session: SessionId,
        payload: serde_json::Value,
    ) -> Result<Seq, String> {
        self.events.push((kind, run, payload));
        Ok(self.events.len() as Seq)
    }
}
