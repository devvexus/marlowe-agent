//! **The client-side producer.** This is what makes `marlowe --tui` talk to the real engine.
//!
//! ARCHITECTURE §6 splits the binary into a thin client and a daemon. The surface renders a
//! `SessionView` and returns `Intent`s; the daemon speaks `Request`/`Event`. [`LiveSession`] is the
//! adapter between them, and it is the last piece of M2 C2d — everything else in that session was
//! scaffolding for this one connection.
//!
//! # It holds a view, and that is not the same as holding run state
//!
//! `Client` deliberately holds nothing (`tests/split.rs` asserts its whole surface). This holds a
//! `SessionView`, which is a **projection** the daemon produced — the same thing a rendered frame
//! is. Closing the client drops it; the run is untouched, and reconnecting rebuilds it from
//! `Status`. That is §2.14's *"surfaces are projections"* rather than a cache of the daemon's state.
//!
//! # The turn runs on a thread, because a blocking read is a frozen terminal
//!
//! `Client::send` blocks until the daemon closes the connection. Calling it from the event loop
//! would stop the repaint and swallow every keystroke for the length of the turn — and M2's first
//! real run spent **155 seconds** in one turn, so this is not hypothetical. The request goes to a
//! worker thread and events arrive on a channel that [`Produce::tick`] drains, which keeps every
//! frame a pure function of `(state, now_ms)`.

use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::thread;

use marlowe_view::view::{Intent, IntentError, SessionView};
use marlowe_view::Produce;

use crate::client::Client;
use crate::project;
use crate::protocol::Event;

/// A live session against a running daemon.
pub struct LiveSession {
    client: Client,
    view: SessionView,
    /// Events from the in-flight turn, if one is running.
    inbox: Option<Receiver<Event>>,
    /// Set when the daemon could not be reached at all. Invariant 4: degrade visibly.
    unreachable: Option<String>,
}

impl LiveSession {
    /// Connect and build the first view from `Status`.
    ///
    /// **A daemon that cannot be reached is not an error here.** §B13 budgets 150 ms to first
    /// frame and §6 says the split is what buys it, so the surface must be able to paint before
    /// this resolves. An unreachable daemon produces a view whose band says so, with the remedy —
    /// which is invariant 4, and is strictly better than refusing to start.
    pub fn connect(session: &str) -> Self {
        Self::connect_with(Client::new(session))
    }

    /// Connect on a chosen port. **The isolation lever**: two sessions on one machine share the
    /// default port, so anything needing a clean daemon uses a scratch one rather than stopping
    /// the other session's. See STATE.md — this is the shared-resource hazard in its fifth form.
    pub fn connect_on(session: &str, port: u16) -> Self {
        Self::connect_with(Client::new(session).with_port(port))
    }

    fn connect_with(client: Client) -> Self {
        match client.status() {
            Ok(events) => {
                let report = events.iter().find_map(|e| match e {
                    Event::Status(r) => Some(r.clone()),
                    _ => None,
                });
                match report {
                    Some(r) => {
                        let mut view = project::view_from_status(&r);
                        // **Ask for the runs too.** Without this the Runs pane renders empty while
                        // the daemon owns runs — a pane that looks connected and shows nothing,
                        // which is indistinguishable from "there are none". Invariant 6 is only
                        // observable if a reconnecting client can see the runs it left behind.
                        if let Ok(runs) = client.send(&crate::protocol::Request::Runs) {
                            project::apply_events(&mut view, &runs);
                        }
                        Self { view, client, inbox: None, unreachable: None }
                    }
                    None => Self::degraded(client, "the daemon answered without a status frame"),
                }
            }
            Err(e) => Self::degraded(client, &e.to_string()),
        }
    }

    fn degraded(client: Client, detail: &str) -> Self {
        let mut view = project::view_from_status(&crate::protocol::StatusReport {
            version: env!("CARGO_PKG_VERSION").to_string(),
            workspace: String::new(),
            model: "none".into(),
            model_disclosure: "NOT MEASURED — no daemon".into(),
            degraded: Some(format!("{detail} · start one with `marlowe --serve`")),
            rerank_provider: "unavailable".into(),
            live_runs: 0,
        });
        view.status.detail = format!("{detail} · start one with `marlowe --serve`");
        Self { client, view, inbox: None, unreachable: Some(detail.to_string()) }
    }

    /// Whether a daemon answered. Printed at startup — ADR-029's rule generalised: **the active
    /// producer is announced, never silently chosen.**
    pub fn is_connected(&self) -> bool {
        self.unreachable.is_none()
    }

    /// Start a turn, and **say so in the band**.
    ///
    /// §B5: motion means Marlowe is working. A 155-second turn on a responsive terminal that says
    /// nothing is only marginally better than one that freezes — the user cannot tell it from a
    /// dropped keystroke. `thinking` is the state §B5 has for exactly this.
    fn start_turn(&mut self, message: String) {
        self.view.status.state = marlowe_view::StatusState::Thinking;
        self.view.status.detail = "working on it — esc to interrupt".into();
        let client = self.client.clone();
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            match client.ask(&message) {
                Ok(events) => {
                    for e in events {
                        if tx.send(e).is_err() {
                            return;
                        }
                    }
                }
                Err(e) => {
                    let _ = tx.send(Event::Error { detail: e.to_string() });
                }
            }
        });
        self.inbox = Some(rx);
    }
}

impl Produce for LiveSession {
    fn view(&self) -> &SessionView {
        &self.view
    }

    /// **Exhaustive, with no catch-all.** ADR-030 §6: adding an `Intent` variant must be a build
    /// error here, not a silent no-op. Every arm either acts or refuses **by name**.
    fn apply(&mut self, intent: Intent) -> Result<(), IntentError> {
        match intent {
            Intent::Send(text) => {
                self.view.transcript.push(marlowe_view::Entry::User(text.clone()));
                self.start_turn(text);
                Ok(())
            }
            Intent::Interrupt => Err(IntentError::NotBuilt {
                capability: marlowe_view::notice::Capability::InterruptingALiveTurn,
                arrives: marlowe_view::notice::Milestone::M2SessionE,
            }),
            // **The one real dependency, and it refuses rather than fabricating.**
            // `Event::Approval` carries {decision, verb, scope, reversible} — no novelty and no
            // ceiling. Building a `BlastRadius` from it would mean defaulting both, and a defaulted
            // ceiling is a claim about promotion logic nobody made. ADR-030 §8.
            Intent::Approve { .. } => Err(IntentError::NotBuilt {
                capability: marlowe_view::notice::Capability::ApprovalOverWire,
                arrives: marlowe_view::notice::Milestone::M2SessionE,
            }),
            Intent::ForceState(_) => Err(IntentError::NotADemo("/state")),
            Intent::Undo(_) => Err(IntentError::NotBuilt {
                capability: marlowe_view::notice::Capability::Undo,
                arrives: marlowe_view::notice::Milestone::M2SessionD,
            }),
            Intent::Compact => Err(IntentError::NotBuilt {
                capability: marlowe_view::notice::Capability::CompactOnDemand,
                arrives: marlowe_view::notice::Milestone::M2SessionD,
            }),
            Intent::Select { control, option } => {
                // The daemon runs one model in one workspace, so the only selectable value is the
                // one already live. Selecting it is a no-op; selecting anything else is refused by
                // name rather than silently ignored.
                let p = self.view.picker(control);
                if option == p.selected {
                    Ok(())
                } else {
                    Err(IntentError::NoSuchOption {
                        control,
                        given: p
                            .options
                            .get(option)
                            .cloned()
                            .unwrap_or_else(|| option.to_string()),
                    })
                }
            }
        }
    }

    /// Drain whatever the in-flight turn has produced. Non-blocking.
    fn tick(&mut self, _now_ms: u64) {
        let Some(rx) = &self.inbox else { return };
        let mut batch = Vec::new();
        loop {
            // LOOP-EXEMPT: draining a channel, not a driving loop.
            match rx.try_recv() {
                Ok(e) => batch.push(e),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    self.inbox = None;
                    break;
                }
            }
        }
        if !batch.is_empty() {
            project::apply_events(&mut self.view, &batch);
        }
    }

    fn is_busy(&self) -> bool {
        self.inbox.is_some()
    }

    /// A turn is in flight, so the loop should keep repainting rather than blocking on input.
    fn next_beat_in(&self, _now_ms: u64) -> Option<u64> {
        self.inbox.as_ref().map(|_| 50)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_absent_daemon_degrades_visibly_rather_than_refusing_to_start() {
        // Invariant 4, and §B13's first-frame budget: the surface must paint. A client that
        // returned Err here would make "no daemon yet" indistinguishable from "broken build".
        let s = LiveSession::connect_on_port("t", 1);
        assert!(!s.is_connected());
        assert!(s.view().status.degraded.is_some(), "the band must say so");
        assert!(
            s.view().status.detail.contains("marlowe --serve"),
            "a degraded state the user cannot act on is a crash with better manners: {}",
            s.view().status.detail
        );
    }

    #[test]
    fn every_intent_the_surface_can_form_is_answered_or_refused_by_name() {
        // ADR-030 §6. A silent no-op would make a working build and a broken one look identical,
        // so each unimplemented arm must produce an error a user can read.
        let mut s = LiveSession::connect_on_port("t", 1);
        for intent in [
            Intent::Interrupt,
            Intent::Approve { granted: true },
            Intent::ForceState(marlowe_view::StatusState::Idle),
            Intent::Undo(1),
            Intent::Compact,
        ] {
            let e = s.apply(intent.clone()).expect_err("must refuse, not silently succeed");
            let msg = e.to_string();
            assert!(!msg.is_empty(), "{intent:?} refused with an empty reason");
            assert!(
                msg.contains("not built") || msg.contains("scripted stub"),
                "{intent:?} refused without naming why: {msg}"
            );
        }
    }

    #[test]
    fn selecting_the_value_that_is_already_live_is_not_an_error() {
        let mut s = LiveSession::connect_on_port("t", 1);
        assert!(s.apply(Intent::Select { control: marlowe_view::ControlId::Model, option: 0 }).is_ok());
        assert!(s
            .apply(Intent::Select { control: marlowe_view::ControlId::Model, option: 7 })
            .is_err());
    }
}

#[cfg(test)]
impl LiveSession {
    /// Connect against a chosen port, so a test can point at one nothing is listening on.
    pub fn connect_on_port(session: &str, port: u16) -> Self {
        let client = Client::new(session).with_port(port);
        match client.status() {
            Ok(_) => Self::degraded(client, "unexpected answer in a test"),
            Err(e) => Self::degraded(client, &e.to_string()),
        }
    }
}
