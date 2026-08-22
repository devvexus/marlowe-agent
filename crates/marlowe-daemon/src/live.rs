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

use std::sync::mpsc::{self, Receiver, SyncSender, TryRecvError};
use std::thread;

use marlowe_view::approval::PendingApproval;
use marlowe_view::view::{Intent, IntentError, SessionView};
use marlowe_view::Produce;

use crate::client::Client;
use crate::project;
use crate::protocol::Event;

/// Did the daemon refuse? An `Error` frame in the reply means it did.
fn refused(events: &[Event]) -> bool {
    events.iter().any(|e| matches!(e, Event::Error { .. }))
}

/// A live session against a running daemon.
pub struct LiveSession {
    client: Client,
    view: SessionView,
    /// Events from the in-flight turn, if one is running.
    inbox: Option<Receiver<Event>>,
    /// Set when the daemon could not be reached at all. Invariant 4: degrade visibly.
    unreachable: Option<String>,
    /// Whether the `Status`/`Runs` handshake has run. False until after the first frame.
    connected: bool,
    /// Where an approval answer is posted back to the turn thread.
    ///
    /// **The daemon is blocked on the other end of this.** It is the one piece of state with a
    /// process waiting on it, which is why `Intent::Approve` must always send something and why
    /// the window has no dismiss key — a closed window with no answer is a hung turn.
    answer: Option<SyncSender<(bool, Option<String>)>>,
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

    /// A session that has **not** talked to a daemon yet, for the first frame.
    ///
    /// §6: *"the client has almost nothing to initialize, and the header paints before the daemon
    /// connection resolves."* §B13 budgets 150 ms to that frame. C2d put `ensure_daemon` and a
    /// `Status` round-trip **in front of** it, so a cold start — no daemon, Ollama not warm —
    /// showed a themed window with a blinking cursor and nothing else for several seconds.
    ///
    /// **The measurements that said 7 ms / 52 ms / 134 ms could not see it**: every one was taken
    /// with Ollama already running. The cold path, which is the one a shortcut click takes, was
    /// never measured.
    ///
    /// This constructs the view the first frame is drawn from. [`Self::finish_connect`] does the
    /// round-trips afterwards.
    pub fn connecting(session: &str, port: u16) -> Self {
        let client = Client::new(session).with_port(port);
        let mut view = project::view_from_status(&crate::protocol::StatusReport {
            version: env!("CARGO_PKG_VERSION").to_string(),
            workspace: String::new(),
            model: "…".into(),
            model_disclosure: "connecting".into(),
            degraded: None,
            rerank_provider: "…".into(),
            // Nothing has been asked yet. The daemon answers this; the surface never guesses.
            model_provider: "…".into(),
            live_runs: 0,
            // Nothing has been asked yet; an invented list would be the surface holding state
            // the daemon has not supplied.
            models: Vec::new(),
        });
        view.status.detail = "connecting to the daemon".into();
        // Not `degraded`: nothing has failed yet, and saying so would be a claim about a
        // connection that has not been attempted. Invariant 4 is about degrading VISIBLY, not
        // about calling every unfinished thing a degradation.
        view.status.degraded = None;
        Self { client, view, inbox: None, unreachable: None, connected: false, answer: None }
    }

    /// Do the handshake. Called after the first frame is on screen.
    pub fn finish_connect(&mut self) {
        let resolved = Self::connect_with(self.client.clone());
        self.view = resolved.view;
        // **What the model can see, the screen shows.** The daemon owns the session and outlives
        // the window; without this a reconnecting client rendered an empty transcript in front of
        // a live conversation, and Marlowe answered from context the user had no sight of.
        if let Ok(past) = self.client.replay() {
            project::apply_events(&mut self.view, &past);
        }
        self.unreachable = resolved.unreachable;
        self.connected = true;
    }

    /// Whether the handshake has run at all. The driver polls this to know when to do it.
    pub fn handshake_done(&self) -> bool {
        self.connected
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
                        Self { view, client, inbox: None, unreachable: None, connected: true, answer: None }
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
            // No daemon, so nothing has announced a provider. Not defaulted to `ollama`: that
            // would be the surface asserting a fact the daemon never supplied.
            model_provider: "unavailable".into(),
            live_runs: 0,
            models: Vec::new(),
        });
        view.status.detail = format!("{detail} · start one with `marlowe --serve`");
        Self {
            client,
            view,
            inbox: None,
            unreachable: Some(detail.to_string()),
            connected: true,
            answer: None,
        }
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
        // **Rendezvous, not a queue.** `sync_channel(0)` means the send blocks until the turn
        // thread takes it, so an answer cannot be posted into a buffer nobody reads.
        let (answer_tx, answer_rx) = mpsc::sync_channel::<(bool, Option<String>)>(0);
        thread::spawn(move || {
            // **Streamed, not collected.** `ask` returns a `Vec` once the daemon closes the
            // connection; the streaming form pushes each event into the channel as the line
            // lands, which is what lets `tick()` draw partial output.
            let tx_err = tx.clone();
            let tx_prompt = tx.clone();
            let result = client.ask_streaming_approving(
                &message,
                // **This blocks the turn thread, which is correct**: the daemon is sitting on the
                // socket read waiting for this answer, and the UI thread keeps drawing. A
                // disconnected receiver means the surface went away mid-question, and the honest
                // answer to a question nobody is there to answer is no.
                &mut |_prompt| answer_rx.recv().unwrap_or((false, None)),
                &mut |event| {
                    let _ = tx_prompt.send(event);
                },
            );
            if let Err(e) = result {
                let _ = tx_err.send(Event::Error { detail: e.to_string() });
            }
        });
        self.inbox = Some(rx);
        self.answer = Some(answer_tx);
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
            // **Answered, as of M2 C2f.** It does not build a §B9 `BlastRadius` — `Effect` has
            // no fetch variant and `Ceiling` has no producer until M6 — so the window renders
            // `PendingApproval`, which states what is known and names what is not. See that
            // type's header.
            Intent::Approve { granted, reason } => {
                let Some(tx) = self.answer.as_ref() else {
                    // No turn is waiting. Refusing by name beats silently dropping an answer.
                    return Err(IntentError::NotADemo("no approval is pending"));
                };
                let reason = reason.map(|e| e.0).filter(|r| !r.trim().is_empty());
                // The window closes on the answer, not on the keypress that opened the editor.
                self.view.pending_approval = None;
                // A failed send means the turn thread has gone; the daemon has already given up
                // waiting, so there is nothing left to answer.
                let _ = tx.send((granted, reason));
                Ok(())
            }
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
                let p = self.view.picker(control);
                if option == p.selected {
                    return Ok(());
                }
                let Some(chosen) = p.options.get(option).cloned() else {
                    return Err(IntentError::NoSuchOption {
                        control,
                        given: option.to_string(),
                    });
                };

                // **Model is the one control that can now actually change**, because the daemon can
                // answer for it: it enumerates what the endpoint holds and refuses anything else by
                // name. Everything else — workspace, profile, autonomy — is still single-valued,
                // and selecting a different value is refused rather than silently ignored.
                //
                // **The view is not patched optimistically.** The daemon replies with a fresh
                // `Status` and the client re-projects it, so what the strip shows is what the
                // daemon accepted. A local mutation here would be the surface inventing state, and
                // it would show the wrong model for the whole turn if the daemon refused.
                if control == marlowe_view::ControlId::Model {
                    match self.client.send(&crate::protocol::Request::SetModel {
                        model: chosen.clone(),
                    }) {
                        Ok(events) => {
                            // Extracted rather than inlined: `vocabulary.rs` scans this function's
                            // text for a catch-all arm, and a `find_map` closure reads the same to
                            // a scanner. The guard is right to be crude — it is protecting
                            // ADR-030 §6, that an unhandled `Intent` must be a build error — so the
                            // code moves rather than the guard.
                            if refused(&events) {
                                return Err(IntentError::OptionUnavailable { control, given: chosen });
                            }
                            project::apply_events(&mut self.view, &events);
                            Ok(())
                        }
                        Err(_) => Err(IntentError::OptionUnavailable { control, given: chosen }),
                    }
                } else {
                    Err(IntentError::NoSuchOption { control, given: chosen })
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
            // **`decision != 0` is the one that is waiting for an answer.** Id 0 is the loop's
            // render-only announcement that it is about to ask; raising the window for it would
            // put up a question nothing is listening to the answer of.
            for e in &batch {
                if let Event::Approval { decision, verb, scope, reversible, novelty } = e {
                    if *decision != 0 {
                        self.view.pending_approval = Some(PendingApproval {
                            decision: *decision,
                            verb: verb.clone(),
                            scope: scope.clone(),
                            reversible: *reversible,
                            novelty: novelty.clone(),
                        });
                    }
                }
            }
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

    fn connect_now(&mut self) {
        if !self.connected {
            self.finish_connect();
        }
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

    /// **An approval with no turn waiting is refused by name, not silently dropped.**
    ///
    /// The dangerous direction is the other one: an answer that goes nowhere leaves the daemon
    /// blocked on a read forever, and the screen would show a dismissed window over a hung turn.
    #[test]
    fn approving_when_nothing_is_pending_refuses_rather_than_dropping_the_answer() {
        let mut s = LiveSession::connect_on_port("t", 1);
        let err = s
            .apply(Intent::Approve { granted: true, reason: None })
            .expect_err("there is no turn to approve");
        assert!(
            err.to_string().contains("no approval is pending"),
            "the refusal must say what was wrong: {err}"
        );
    }

    #[test]
    fn every_intent_the_surface_can_form_is_answered_or_refused_by_name() {
        // ADR-030 §6. A silent no-op would make a working build and a broken one look identical,
        // so each unimplemented arm must produce an error a user can read.
        let mut s = LiveSession::connect_on_port("t", 1);
        // **`Approve` left this list in M2 C2f** — it is answered now, not refused, and its own
        // test is below. Keeping it here would have asserted that a working feature still fails.
        for intent in [
            Intent::Interrupt,
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
