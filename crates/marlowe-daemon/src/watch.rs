//! **The control plane a run window speaks to.** `M3-DESIGN.md` §6.
//!
//! # Why this is a second listener rather than another arm of `handle`
//!
//! The daemon serves **one connection at a time**, and says so: *"a second client is a M3 concern
//! and pretending to handle it now would be a concurrency story nobody tested."* The whole of a
//! turn — a two-minute model call included — is served on the connection that asked for it.
//!
//! A window is a second process, and the moment it matters is **while a turn is running**. Served
//! on the conversation port it would be answered only between turns: blank exactly when there is
//! something to watch, and a steer that arrived after the run it was correcting had finished.
//!
//! So the control plane binds its own port and is served by its own thread, from state behind an
//! `Arc<Mutex<_>>` that the turn publishes into. **The turn path is not restructured and not
//! touched.** That is the point of doing it this way rather than making `serve` concurrent: making
//! the whole daemon multi-connection is real work with a real blast radius, and it is the control
//! plane's own milestone step, not a window's to do on the way past.
//!
//! What this costs, stated rather than buried: **two ports and one token**. The token is the same
//! and the loopback binding is the same; the second port is bound as `:0` and published to
//! `control.port` in the profile root, so there is nothing to configure and nothing to guess. See
//! [`port_path`] for why it is published rather than derived — the first design was `port + 1` and
//! it took another process's port. What it buys is that a window works while a run is running,
//! which is the only time a window is worth anything.
//!
//! # A poll, not a subscription
//!
//! [`crate::protocol::Request::Watch`] asks *what is true now, and what has happened since frame
//! N*. The daemon answers and closes. That makes §6.6's *"one state, two renderings"* literal —
//! the window re-projects the daemon's answer and holds nothing between polls — and it means a
//! window that dies, or a daemon that restarts, leaves nothing to clean up.
//!
//! # Text frames coalesce, and that is what bounds the memory
//!
//! A token-by-token frame log for a long run is unbounded memory in a process that must not die.
//! So consecutive `TextDelta`s append to the **same** frame under the same sequence number, and a
//! poll returns frames with `seq >= since` — the growing tail is re-sent and the client overwrites
//! it by sequence. Frames per run are therefore proportional to turns, not to tokens.
//!
//! [`MAX_FRAMES`] bounds it anyway, because "proportional to turns" is still unbounded over a day.
//! **Dropping is reported, never silent**: `first_seq` moves, and a window that asked for something
//! older is told so rather than shown a gap it cannot see. The journal is the record; this is a
//! window.

use std::collections::{BTreeMap, VecDeque};
use std::io::{BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use crate::protocol::{read_line, write_line, Event, Request, RunFrame};

/// How many frames one run keeps. Frames coalesce, so this is turns-worth, not tokens-worth.
///
/// **Reported when it bites.** See the module header: a window that has fallen off the end is told,
/// because a gap a reader cannot see is worse than a shorter history.
pub const MAX_FRAMES: usize = 2_000;

/// How many steers may queue for one run before the plane refuses.
///
/// **Refuses, not drops.** A steer that vanished is exactly finding E10's failure — *"the user's
/// correction vanished with no error"* — and a queue that silently discards the oldest is that
/// failure with a bound on it.
pub const MAX_PENDING_STEERS: usize = 16;

/// What a window draws, as the daemon holds it. Mirrors [`Event::RunDetail`] field for field, so
/// there is no second idea of what a run looks like on the wire.
#[derive(Debug, Clone)]
pub struct RunDetail {
    pub status: String,
    pub detail: String,
    pub started_ms: u64,
    pub finished_ms: u64,
    pub spend_micros_usd: u64,
    pub ceiling_micros_usd: u64,
    pub last_checkpoint: Option<u64>,
    pub resume_from: Option<u64>,
    pub resume_refused: String,
    pub orphan_policy: String,
}

#[derive(Debug)]
struct Watched {
    detail: RunDetail,
    frames: VecDeque<(u64, RunFrame)>,
    next_seq: u64,
    first_seq: u64,
    /// Steers admitted by the door and waiting for the next iteration boundary.
    steers: VecDeque<marlowe_loop::driver::SteerMessage>,
    cancel: bool,
    /// Set by a window; the run path clears it after answering. Not a bool the run reads forever.
    resume_requested: bool,
}

/// Every run a window could be watching. **Shared with the turn, read by the control listener.**
#[derive(Debug, Default)]
pub struct ControlPlane {
    runs: BTreeMap<String, Watched>,
}

impl ControlPlane {
    pub fn new() -> Self {
        Self::default()
    }

    /// Begin watching a run. Called when the daemon accepts the work, **before anything can fail**
    /// — the same reason `Daemon::ask` records the run first: a turn that degraded is still a turn
    /// that happened, and a window opened on it must not be told it does not exist.
    pub fn open(&mut self, run: &str, detail: RunDetail) {
        self.runs.insert(
            run.to_string(),
            Watched {
                detail,
                frames: VecDeque::new(),
                next_seq: 1,
                first_seq: 1,
                steers: VecDeque::new(),
                cancel: false,
                resume_requested: false,
            },
        );
    }

    /// Append one frame, coalescing consecutive prose of the same kind.
    pub fn push(&mut self, run: &str, frame: RunFrame) {
        let Some(w) = self.runs.get_mut(run) else { return };

        // Coalesce into the tail when it is the same kind of prose. This is what keeps the frame
        // count proportional to turns rather than to tokens.
        let coalesced = match (&frame, w.frames.back_mut()) {
            (RunFrame::Text { delta }, Some((_, RunFrame::Text { delta: tail }))) => {
                tail.push_str(delta);
                true
            }
            (RunFrame::Reasoning { delta }, Some((_, RunFrame::Reasoning { delta: tail }))) => {
                tail.push_str(delta);
                true
            }
            // **A tool line REPLACES its own earlier frame rather than adding one.** §B6: the
            // close must replace the open line, not scroll a second one in beneath it — the same
            // property `quarantine_batch.rs` asserts for the quarantined reader's line.
            (RunFrame::Tool { id, .. }, _) => {
                let id = *id;
                match w
                    .frames
                    .iter_mut()
                    .find(|(_, f)| matches!(f, RunFrame::Tool { id: other, .. } if *other == id))
                {
                    Some((_, slot)) => {
                        *slot = frame.clone();
                        true
                    }
                    None => false,
                }
            }
            _ => false,
        };
        if coalesced {
            return;
        }

        let seq = w.next_seq;
        w.next_seq += 1;
        w.frames.push_back((seq, frame));
        while w.frames.len() > MAX_FRAMES {
            w.frames.pop_front();
            w.first_seq += 1;
        }
    }

    pub fn set_detail(&mut self, run: &str, f: impl FnOnce(&mut RunDetail)) {
        if let Some(w) = self.runs.get_mut(run) {
            f(&mut w.detail);
        }
    }

    /// Everything a `Watch` is answered with: the detail, then the frames from `since`.
    ///
    /// `seq >= since`, not `>`, because the tail frame grows — see the module header.
    pub fn snapshot(&self, run: &str, since: u64) -> Option<Vec<Event>> {
        let w = self.runs.get(run)?;
        let mut out = vec![Event::RunDetail {
            id: run.to_string(),
            status: w.detail.status.clone(),
            detail: w.detail.detail.clone(),
            started_ms: w.detail.started_ms,
            finished_ms: w.detail.finished_ms,
            spend_micros_usd: w.detail.spend_micros_usd,
            ceiling_micros_usd: w.detail.ceiling_micros_usd,
            last_checkpoint: w.detail.last_checkpoint,
            resume_from: w.detail.resume_from,
            resume_refused: w.detail.resume_refused.clone(),
            orphan_policy: w.detail.orphan_policy.clone(),
            latest_seq: w.next_seq.saturating_sub(1),
        }];
        // **A window that has fallen off the end is told, rather than shown a seamless gap.**
        if since > 0 && since < w.first_seq {
            out.push(Event::Degraded {
                what: format!("{} earlier frames are no longer held", w.first_seq - since),
                remedy: "the journal has the whole run; a window keeps the recent tail".into(),
            });
        }
        for (seq, frame) in &w.frames {
            if *seq >= since {
                out.push(Event::RunOutput { seq: *seq, frame: frame.clone() });
            }
        }
        Some(out)
    }

    /// Queue an **already-admitted** steer. ADR-054: this takes a `SteerMessage`, so there is no
    /// way to reach a run from here without having gone through the door.
    pub fn queue_steer(
        &mut self,
        run: &str,
        message: marlowe_loop::driver::SteerMessage,
    ) -> Result<(), String> {
        let Some(w) = self.runs.get_mut(run) else {
            return Err(format!("no run {run}"));
        };
        if w.steers.len() >= MAX_PENDING_STEERS {
            return Err(format!(
                "{MAX_PENDING_STEERS} steers are already waiting for run {run}. They apply at \
                 iteration boundaries, so this one is refused rather than dropped — send it again \
                 once the run has caught up"
            ));
        }
        w.steers.push_back(message);
        Ok(())
    }

    pub fn take_steer(&mut self, run: &str) -> Option<marlowe_loop::driver::SteerMessage> {
        self.runs.get_mut(run)?.steers.pop_front()
    }

    pub fn request_cancel(&mut self, run: &str) -> Result<(), String> {
        match self.runs.get_mut(run) {
            Some(w) => {
                w.cancel = true;
                Ok(())
            }
            None => Err(format!("no run {run}")),
        }
    }

    pub fn is_cancelled(&self, run: &str) -> bool {
        self.runs.get(run).is_some_and(|w| w.cancel)
    }

    pub fn request_resume(&mut self, run: &str) -> Result<(), String> {
        match self.runs.get_mut(run) {
            Some(w) => {
                w.resume_requested = true;
                Ok(())
            }
            None => Err(format!("no run {run}")),
        }
    }

    pub fn take_resume(&mut self, run: &str) -> bool {
        match self.runs.get_mut(run) {
            Some(w) => std::mem::take(&mut w.resume_requested),
            None => false,
        }
    }

    /// Ids of every run the plane holds, newest last. `/runs` from outside reads this.
    pub fn ids(&self) -> Vec<String> {
        self.runs.keys().cloned().collect()
    }
}

/// A [`marlowe_loop::driver::Control`] backed by the plane, so a window's steer reaches a **running**
/// loop at its next iteration boundary.
///
/// This is what makes the window's field a real mid-flight steer rather than a message queued for
/// the next turn — §10.1's *"mid-flight, no restart"*.
pub struct PlaneControl {
    plane: Arc<Mutex<ControlPlane>>,
    run: String,
}

impl PlaneControl {
    pub fn new(plane: Arc<Mutex<ControlPlane>>, run: impl Into<String>) -> Self {
        Self { plane, run: run.into() }
    }
}

impl marlowe_loop::driver::Control for PlaneControl {
    fn cancelled(&self) -> bool {
        self.plane
            .lock()
            .map(|p| p.is_cancelled(&self.run))
            .unwrap_or(false)
    }

    fn take_steer(&mut self) -> Option<marlowe_loop::driver::SteerMessage> {
        self.plane.lock().ok()?.take_steer(&self.run)
    }
}

/// Where the control port is published, beside the token that protects it.
///
/// # `port + 1` was the first design and it was wrong
///
/// Deriving the control port from the conversation port needs no discovery and no file, which is
/// why it was written that way. It is also **someone else's port**: the daemon's own port is often
/// an ephemeral one, ephemeral ports are handed out consecutively, and `port + 1` is therefore
/// very likely to be the next process's. Three tests failed on exactly that — one daemon's control
/// listener holding another daemon's conversation port, which presents as `ConnectionRefused` and
/// as a hang, neither of which points at the cause.
///
/// So the listener binds `:0`, learns what it was given, and **publishes** it. That is the same
/// shape `daemon.token` already uses, in the same directory the OS already makes unreadable to
/// other users, and it is ADR-029's rule applied to a port: announced, never inferred.
pub fn port_path(profile_root: &std::path::Path) -> std::path::PathBuf {
    profile_root.join("control.port")
}

/// The control port for a running daemon, or `None` if none has published one.
///
/// `None` and a stale value are different failures and the caller must say which: a missing file
/// means no daemon has run for this profile, and a file pointing at a closed port means one ran and
/// stopped. A client that reported both as "not running" would send somebody looking for a daemon
/// that is right there.
pub fn read_port(profile_root: &std::path::Path) -> Option<u16> {
    std::fs::read_to_string(port_path(profile_root))
        .ok()?
        .trim()
        .parse()
        .ok()
}

/// Serve the control plane until `shutdown`. Runs on its own thread.
///
/// **Authentication is the connection's, exactly as on the conversation port** — one preamble line,
/// the same token. A per-request token field would have to go on every variant and the one somebody
/// forgot would be an unauthenticated request that deserialized fine.
pub fn serve(
    profile_root: std::path::PathBuf,
    token: String,
    plane: Arc<Mutex<ControlPlane>>,
    shutdown: Arc<AtomicBool>,
) -> std::io::Result<()> {
    // **Port zero, then publish.** See [`port_path`] for what deriving it from the conversation
    // port did instead.
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, 0));
    let listener = TcpListener::bind(addr)?;
    let port = listener.local_addr()?.port();
    std::fs::create_dir_all(&profile_root).ok();
    std::fs::write(port_path(&profile_root), port.to_string())?;
    // So the loop can notice a shutdown that arrived while it was blocked in `accept`.
    listener.set_nonblocking(false).ok();

    for incoming in listener.incoming() {
        // LOOP-EXEMPT: an accept loop, not an agent loop.
        if shutdown.load(Ordering::Relaxed) {
            break;
        }
        let Ok(stream) = incoming else { continue };
        let _ = serve_one(stream, &token, &plane);
        if shutdown.load(Ordering::Relaxed) {
            break;
        }
    }
    // **Unpublished on the way out.** A file pointing at a closed port is a client told
    // `ConnectionRefused` by something that looks like a running daemon, which is a worse failure
    // than "no daemon has run here".
    let _ = std::fs::remove_file(port_path(&profile_root));
    Ok(())
}

fn serve_one(
    stream: TcpStream,
    token: &str,
    plane: &Arc<Mutex<ControlPlane>>,
) -> std::io::Result<()> {
    let mut writer = stream.try_clone()?;
    let mut reader = BufReader::new(stream);

    reader
        .get_ref()
        .set_read_timeout(Some(std::time::Duration::from_secs(5)))
        .ok();

    let mut preamble = String::new();
    let offered = {
        use std::io::BufRead;
        match reader.read_line(&mut preamble) {
            Ok(0) => return Ok(()),
            Ok(_) => preamble.trim().to_string(),
            Err(_) => return Ok(()),
        }
    };
    if !crate::auth::matches(token, &offered) {
        write_line(&mut writer, &Event::Error { detail: crate::auth::refusal() })?;
        // Drain before closing, for the reason `daemon.rs` records: closing a socket with unread
        // inbound data makes Windows send an RST, which destroys the refusal that was just
        // written — and the client then cannot tell "refused" from "the daemon hung up".
        let mut sink = [0u8; 4096];
        let mut drained = 0usize;
        while drained < 64 * 1024 {
            // LOOP-EXEMPT: draining a socket before close.
            match reader.read(&mut sink) {
                Ok(0) | Err(_) => break,
                Ok(n) => drained += n,
            }
        }
        return Ok(());
    }

    let request: Option<Request> = read_line(&mut reader)?;
    let Some(request) = request else { return Ok(()) };

    for e in answer(request, plane) {
        write_line(&mut writer, &e)?;
    }
    writer.flush()
}

/// **The whole control-plane surface, in one total function**, so a request that reaches this port
/// and is not a control-plane request is refused by name rather than answered vaguely.
fn answer(request: Request, plane: &Arc<Mutex<ControlPlane>>) -> Vec<Event> {
    match request {
        Request::Watch { run, since } => {
            let p = plane.lock().expect("the control plane lock was poisoned");
            match p.snapshot(&run, since) {
                Some(events) => events,
                None => vec![Event::Error { detail: format!("no run {run}") }],
            }
        }
        Request::Steer { run, text } => {
            // **The door.** ADR-054: this is the only thing between a socket and a run's
            // `UserAsserted` provenance, and it is the same call `/steer` makes.
            match marlowe_loop::steer::admit(
                marlowe_loop::steer::SteerOrigin::Human,
                &text,
                marlowe_loop::driver::Urgency::Advisory,
            ) {
                Ok(message) => {
                    let mut p = plane.lock().expect("the control plane lock was poisoned");
                    match p.queue_steer(&run, message) {
                        Ok(()) => vec![Event::Accepted { what: "steer".into() }],
                        Err(detail) => vec![Event::Error { detail }],
                    }
                }
                Err(refused) => vec![Event::Error { detail: refused.to_string() }],
            }
        }
        Request::CancelRun { run } => {
            let mut p = plane.lock().expect("the control plane lock was poisoned");
            match p.request_cancel(&run) {
                Ok(()) => vec![Event::Accepted { what: "cancel".into() }],
                Err(detail) => vec![Event::Error { detail }],
            }
        }
        Request::ResumeRun { run } => {
            let mut p = plane.lock().expect("the control plane lock was poisoned");
            match p.request_resume(&run) {
                Ok(()) => vec![Event::Accepted { what: "resume".into() }],
                Err(detail) => vec![Event::Error { detail }],
            }
        }
        Request::Runs => {
            let p = plane.lock().expect("the control plane lock was poisoned");
            p.ids()
                .iter()
                .filter_map(|id| p.snapshot(id, u64::MAX))
                .map(|mut v| v.remove(0))
                .collect()
        }
        // **Refused by name.** The conversation port answers these; a vague reply here would send
        // somebody looking for a bug in the wrong process.
        other => vec![Event::Error {
            detail: format!(
                "the control port answers watch, steer, cancel_run, resume_run and runs. \
                 {} belongs on the conversation port",
                match other {
                    Request::Ask { .. } => "ask",
                    Request::Status => "status",
                    Request::Replay { .. } => "replay",
                    Request::Approve { .. } => "approve",
                    Request::SetModel { .. } => "set_model",
                    Request::SetProvider { .. } => "set_provider",
                    Request::Shutdown => "shutdown",
                    _ => "that request",
                }
            ),
        }],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn detail() -> RunDetail {
        RunDetail {
            status: "running".into(),
            detail: String::new(),
            started_ms: 1_000,
            finished_ms: 0,
            spend_micros_usd: 0,
            ceiling_micros_usd: 3_000_000,
            last_checkpoint: None,
            resume_from: None,
            resume_refused: String::new(),
            orphan_policy: "detach".into(),
        }
    }

    fn frames(events: &[Event]) -> Vec<(u64, RunFrame)> {
        events
            .iter()
            .filter_map(|e| match e {
                Event::RunOutput { seq, frame } => Some((*seq, frame.clone())),
                _ => None,
            })
            .collect()
    }

    #[test]
    fn consecutive_prose_coalesces_into_one_frame_so_the_log_is_turns_not_tokens() {
        let mut p = ControlPlane::new();
        p.open("r", detail());
        for word in ["the ", "answer ", "is ", "four"] {
            p.push("r", RunFrame::Text { delta: word.into() });
        }
        let f = frames(&p.snapshot("r", 0).unwrap());
        assert_eq!(f.len(), 1, "four deltas became {} frames: {f:?}", f.len());
        assert_eq!(f[0].1, RunFrame::Text { delta: "the answer is four".into() });
    }

    #[test]
    fn a_tool_line_closing_replaces_its_open_line_rather_than_adding_a_second() {
        // §B6, and the same property `quarantine_batch.rs` asserts for the reader's line: a close
        // that scrolled a second line in would make every call look like two.
        let mut p = ControlPlane::new();
        p.open("r", detail());
        p.push("r", RunFrame::Tool {
            id: 7,
            verb: "read".into(),
            target: "notes.md".into(),
            state: "running".into(),
            summary: "0 ms".into(),
        });
        p.push("r", RunFrame::Tool {
            id: 7,
            verb: "read".into(),
            target: "notes.md".into(),
            state: "ok".into(),
            summary: "48 lines".into(),
        });
        let f = frames(&p.snapshot("r", 0).unwrap());
        assert_eq!(f.len(), 1, "the close added a second line: {f:?}");
        assert!(matches!(&f[0].1, RunFrame::Tool { state, .. } if state == "ok"));
    }

    #[test]
    fn a_poll_resends_the_growing_tail_and_the_client_overwrites_by_sequence() {
        // `seq >= since`, not `>`. With `>` the last frame would freeze at whatever it held on the
        // poll that first saw it, and a live run's final paragraph would never finish arriving.
        let mut p = ControlPlane::new();
        p.open("r", detail());
        p.push("r", RunFrame::Text { delta: "half".into() });
        let first = frames(&p.snapshot("r", 0).unwrap());
        assert_eq!(first.len(), 1);

        p.push("r", RunFrame::Text { delta: " a sentence".into() });
        let second = frames(&p.snapshot("r", first[0].0).unwrap());
        assert_eq!(second.len(), 1, "the tail was not re-sent");
        assert_eq!(second[0].1, RunFrame::Text { delta: "half a sentence".into() });
    }

    #[test]
    fn a_window_that_fell_off_the_end_is_told_rather_than_shown_a_seamless_gap() {
        let mut p = ControlPlane::new();
        p.open("r", detail());
        // Distinct kinds so nothing coalesces: each is its own frame.
        for i in 0..(MAX_FRAMES + 10) {
            if i % 2 == 0 {
                p.push("r", RunFrame::Text { delta: format!("t{i}") });
            } else {
                p.push("r", RunFrame::Reasoning { delta: format!("r{i}") });
            }
        }
        let events = p.snapshot("r", 1).unwrap();
        assert!(
            events.iter().any(|e| matches!(e, Event::Degraded { what, .. } if what.contains("no longer held"))),
            "frames were dropped and the window was not told"
        );
        assert!(frames(&events).len() <= MAX_FRAMES);
    }

    #[test]
    fn a_full_steer_queue_refuses_rather_than_dropping_the_oldest() {
        // Finding E10's failure was *"the user's correction vanished with no error"*. A ring buffer
        // here would be that failure with a bound on it.
        let mut p = ControlPlane::new();
        p.open("r", detail());
        let msg = || {
            marlowe_loop::steer::admit(
                marlowe_loop::steer::SteerOrigin::Human,
                "stop",
                marlowe_loop::driver::Urgency::Advisory,
            )
            .unwrap()
        };
        for _ in 0..MAX_PENDING_STEERS {
            p.queue_steer("r", msg()).expect("within the queue");
        }
        let e = p.queue_steer("r", msg()).unwrap_err();
        assert!(e.contains("refused rather than dropped"), "{e}");
        assert_eq!(p.take_steer("r").map(|m| m.text), Some("stop".into()), "the oldest survived");
    }

    #[test]
    fn steering_a_run_the_plane_does_not_hold_is_an_error_and_not_a_silent_success() {
        let mut p = ControlPlane::new();
        assert!(p.queue_steer("nope", marlowe_loop::steer::admit(
            marlowe_loop::steer::SteerOrigin::Human,
            "stop",
            marlowe_loop::driver::Urgency::Advisory,
        ).unwrap()).is_err());
        assert!(p.request_cancel("nope").is_err());
        assert!(p.request_resume("nope").is_err());
    }

    #[test]
    fn the_control_port_refuses_a_conversation_request_by_name() {
        let plane = Arc::new(Mutex::new(ControlPlane::new()));
        let out = answer(Request::Ask { session: "s".into(), message: "hi".into() }, &plane);
        match &out[0] {
            Event::Error { detail } => {
                assert!(detail.contains("ask"), "{detail}");
                assert!(detail.contains("conversation port"), "{detail}");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn a_steer_through_the_control_port_goes_through_the_door() {
        // ADR-054's *"the same adjudication `/steer` does — never a side door that skips it"*,
        // asserted at the enforcement site: the port's own handler, not a helper beside it.
        let plane = Arc::new(Mutex::new(ControlPlane::new()));
        plane.lock().unwrap().open("r", detail());

        // Refused by the door, with the door's own words.
        let long = "x".repeat(marlowe_loop::MAX_STEER_CHARS + 1);
        let out = answer(Request::Steer { run: "r".into(), text: long }, &plane);
        match &out[0] {
            Event::Error { detail } => assert!(
                detail.contains(&marlowe_loop::MAX_STEER_CHARS.to_string()),
                "the refusal is not the door's: {detail}"
            ),
            other => panic!("expected the door's refusal, got {other:?}"),
        }
        assert!(plane.lock().unwrap().take_steer("r").is_none(), "a refused steer was queued");

        // And the control: an ordinary one is admitted, sanitised, and queued.
        let out = answer(
            Request::Steer { run: "r".into(), text: "stop \u{202e}now".into() },
            &plane,
        );
        assert_eq!(out[0], Event::Accepted { what: "steer".into() });
        let queued = plane.lock().unwrap().take_steer("r").expect("queued");
        assert!(!queued.text.contains('\u{202e}'), "the door did not sanitise: {}", queued.text);
    }

    #[test]
    fn a_published_port_round_trips_and_a_missing_one_is_none() {
        let dir = std::env::temp_dir().join(format!("marlowe-watch-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let _ = std::fs::remove_file(port_path(&dir));
        assert_eq!(read_port(&dir), None, "no daemon has run here");
        std::fs::write(port_path(&dir), "51234").unwrap();
        assert_eq!(read_port(&dir), Some(51234));
        let _ = std::fs::remove_file(port_path(&dir));
    }
}
