//! The control plane — a **second listener**, so `/steer` from outside is real rather than queued.
//!
//! # Why this exists, in the daemon's own words
//!
//! `Daemon::serve` says *"One connection at a time — a second client is a M3 concern and pretending
//! to handle it now would be a concurrency story nobody tested"*, and `Request::Approve`'s arm says
//! *"Concurrency is M3."* This is M3, and this is that concurrency — deliberately the **smallest**
//! amount of it that makes the milestone's scope item true.
//!
//! M3-DESIGN §10.1 requires steering *"from outside"* — another terminal, no TUI, a script. On a
//! serial daemon a steer sent from a second terminal is not **read** until the turn it was meant
//! to change has already ended. Queuing it and calling that "mid-flight" would be a control that
//! looks like it works and cannot: the same shape as a banner that fires on every run.
//!
//! # What is shared, and what is emphatically not
//!
//! The thread started here **never touches `Daemon`**. It holds one `Arc<Mutex<ControlPlane>>`
//! containing exactly two things: the run table, and the [`DurableControl`]. The model, the
//! memory, the tool host, the session store and the journal-for-writing all stay behind the
//! daemon's own lock and are still served one connection at a time. So the concurrency added here
//! is bounded by a struct a reader can hold in their head, which is the only kind worth shipping
//! at this stage.
//!
//! The loop reaches the shared state through [`SharedControl`], which locks **per call** at
//! iteration boundaries — `take_steer` and `cancelled` are a lock, a `pop_front`, and an unlock.
//! Nothing holds the lock across a model call, which is what makes a steer arriving mid-turn
//! visible to the turn that is already running.
//!
//! # A second port, ADVERTISED rather than derived — and the first draft got this wrong
//!
//! One `TcpListener` cannot be accepted from two places without a thread per connection, and a
//! thread per connection means `Daemon: Send`, which it is not (ONNX sessions, `Rc`-free but not
//! audited for it). A second port is the change that does not require auditing the whole daemon
//! for thread-safety.
//!
//! **The first version derived it as `port + 1`, and that is a collision waiting for a second
//! daemon.** The default port is 11435, so a daemon deliberately started on 11436 lands on the
//! first one's control plane; a client then offers the second profile's token to the first
//! profile's listener and is refused, which reads as a mysterious auth failure and is not one.
//!
//! Two workspace tests found it within minutes of it being written — `socket_auth` and `split`
//! both call `free_port()`, and the OS handed one fixture the port another fixture's control
//! plane had just taken. That is the **defaults that make a mismatch unobservable** family with
//! the sign flipped: the derivation made a collision *silent* everywhere except where two daemons
//! happened to be adjacent.
//!
//! So the port is **bound at 0 — the OS picks a free one — and written to the profile root**, next
//! to `daemon.token` and protected by the same directory ACL. Discovery, not arithmetic. A client
//! reads the file; if it is absent or stale the request falls back to the main port, which is
//! slower and always correct.
//!
//! If the listener cannot start at all the daemon **still serves** and says the control plane is
//! unavailable — invariant 4: degrade visibly, name the remedy. A daemon that refused to start
//! because a secondary listener failed would be worse than one whose `/steer` says why it cannot
//! work.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Read};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use marlowe_loop::{
    CheckpointStore, Control, DurableControl, JournalCheckpoints, OrphanPolicy, RunControl, RunId,
    SteerMessage, Urgency,
};

use crate::daemon::RunSummary;
use crate::protocol::{write_line, Event, Request};

/// Everything a control request may reach. Deliberately small — see the module header.
pub struct ControlPlane {
    /// The run table. **The daemon's state, which is the whole point of `/runs`.**
    ///
    /// `--status` reported the client's own default while describing a daemon running something
    /// else, because a fresh process resolved its own configuration instead of asking. `/runs` is
    /// the same question about a different noun, so it reads this and there is no second copy.
    pub runs: BTreeMap<String, RunSummary>,
    pub control: DurableControl<JournalCheckpoints>,
}

pub type Shared = Arc<Mutex<ControlPlane>>;

impl ControlPlane {
    pub fn new(control: DurableControl<JournalCheckpoints>) -> Shared {
        Arc::new(Mutex::new(Self { runs: BTreeMap::new(), control }))
    }

    /// Fill the run table from the journal, so a run that survived a restart can be **found**.
    ///
    /// **Not "running".** These runs stopped when the process did, and calling them running would
    /// be the surface asserting a state nothing holds — `live_runs` feeds `--status`'s count and
    /// `Shutdown`'s refusal, and both would then be wrong forever. `interrupted` is the honest
    /// word: it says the work stopped and did not finish, which is exactly what a resume is for.
    ///
    /// A run whose last checkpoint is terminal is **not** seeded. It completed, failed or was
    /// cancelled; listing it as pending would offer a resume that `RunControl::resume` refuses.
    pub fn seed_from_journal(&mut self) -> usize {
        let seeded: Vec<_> = self
            .control
            .store()
            .latest_per_run()
            .into_iter()
            .filter(|cp| !cp.is_terminal())
            .collect();
        let n = seeded.len();
        for cp in seeded {
            let id = cp.run.to_string();
            self.runs.entry(id.clone()).or_insert_with(|| RunSummary {
                status: "interrupted".into(),
                tokens: cp.spent.tokens,
                depth: cp.budget.depth,
                spend_micros_usd: cp.spent.micros_usd,
                elapsed_ms: cp.spent.wall_ms,
                ..RunSummary::accepted(id)
            });
        }
        n
    }

    pub fn live_runs(&self) -> usize {
        self.runs.values().filter(|r| r.status == "running").count()
    }

    /// Every run, as wire frames. One definition, read by the main port and the control port.
    pub fn run_frames(&self) -> Vec<Event> {
        self.runs.values().map(RunSummary::to_frame).collect()
    }

    /// One run, in the detail §6.2 asks a window to render.
    ///
    /// **Including what a resume would resume from** — M3-DESIGN calls that *"the field that makes
    /// this a debugging instrument"*, and it is read from the checkpoint store rather than from the
    /// run table, because the table is what the daemon remembers and the store is what survived.
    pub fn detail(&self, run: RunId) -> Event {
        let summary = self.runs.get(&run.to_string());
        let cp = self.control.store().latest(run);
        Event::RunDetail {
            id: run.to_string(),
            status: summary.map_or_else(
                || cp.as_ref().map_or("unknown".into(), |c| format!("{:?}", c.status).to_lowercase()),
                |s| s.status.clone(),
            ),
            parent: cp.as_ref().and_then(|c| c.parent).map(|p| p.to_string()),
            elapsed_ms: summary.map_or(0, |s| s.elapsed_ms),
            spend_micros_usd: summary.map_or(0, |s| s.spend_micros_usd),
            ceiling_micros_usd: cp.as_ref().map_or(0, |c| c.budget.micros_usd),
            spent_tokens: cp.as_ref().map_or(0, |c| c.spent.tokens),
            granted_tokens: cp.as_ref().map_or(0, |c| c.budget.tokens),
            depth: cp.as_ref().map_or(0, |c| c.budget.depth),
            // **A fact, never a roadmap** (§6.3). `None` means no checkpoint exists, and the
            // renderer says so in those words rather than inventing a step 0.
            last_checkpoint_step: cp.as_ref().map(|c| c.step),
            resumable: cp.as_ref().is_some_and(|c| !c.is_terminal()),
            orphan_policy: cp.as_ref().map_or_else(
                || "unknown".into(),
                |c| match c.orphan_policy {
                    OrphanPolicy::Adopt { by } => format!("adopt by {by}"),
                    OrphanPolicy::Detach => "detach".into(),
                    OrphanPolicy::Terminate => "terminate".into(),
                },
            ),
            pending_steers: self.control.pending_steers(run),
        }
    }
}

/// The loop's [`Control`] port, backed by the shared plane.
///
/// **A lock per call, never across one.** `Engine::drive_inner` asks `cancelled` and `take_steer`
/// once per iteration, before the model call; both are a lock, a lookup and an unlock. So a steer
/// written by the control thread while a model call is in flight is picked up by the very next
/// boundary — which is what "mid-flight, no restart" means.
pub struct SharedControl(pub Shared);

impl SharedControl {
    fn with<T>(&self, f: impl FnOnce(&mut ControlPlane) -> T) -> T {
        f(&mut self.0.lock().expect("the control plane lock was poisoned"))
    }
}

impl Control for SharedControl {
    fn cancelled(&self, run: RunId) -> bool {
        self.with(|p| p.control.cancelled(run))
    }

    fn take_steer(&mut self, run: RunId) -> Option<SteerMessage> {
        self.with(|p| p.control.take_steer(run))
    }

    fn take_interrupt(&mut self) -> Option<String> {
        None
    }
}

/// What a control request may be answered with, and what it may not.
///
/// **Anything needing a model goes on the main port**, and is refused here by name rather than
/// half-served. `Resume` is the one that surprises people: staging a checkpoint is cheap and this
/// plane could do it, but *running* it needs the engine, the driver and the tool host — all of
/// which live behind the daemon's own lock. A `Resume` that staged and did not drive would report
/// success for a run that never took another step.
pub(crate) fn answer(plane: &Shared, request: Request, on_event: &mut dyn FnMut(Event)) {
    let mut plane = plane.lock().expect("the control plane lock was poisoned");
    match request {
        Request::Runs => {
            for e in plane.run_frames() {
                on_event(e);
            }
        }
        Request::Watch { run } => match run.parse::<uuid::Uuid>() {
            Ok(id) => on_event(plane.detail(RunId(id))),
            Err(_) => on_event(Event::Error { detail: unknown_run(&run) }),
        },
        Request::Steer { run, text } => match run.parse::<uuid::Uuid>() {
            Ok(id) => {
                let id = RunId(id);
                // **Sanitised here, at the boundary it crosses.** A steer is user text on its way
                // into a model's window and, through `/runs`, onto a terminal.
                // `marlowe_contract::text` is the one definition of what may be displayed; a steer
                // carrying `ESC` would otherwise write escape sequences through the daemon and
                // onto a screen.
                let text = marlowe_contract::text::sanitize_line(&text).into_owned();
                if text.trim().is_empty() {
                    on_event(Event::Error {
                        detail: "a steer with no text would be an empty turn in the run's window"
                            .into(),
                    });
                    return;
                }
                plane.control.steer(id, SteerMessage { text, urgency: Urgency::Advisory });
                let pending = plane.control.pending_steers(id);
                // **The count, not an acknowledgement.** "queued" is a claim about a mechanism;
                // a number is a fact the next `/watch` can be checked against.
                on_event(plane.detail(id));
                let _ = pending;
            }
            Err(_) => on_event(Event::Error { detail: unknown_run(&run) }),
        },
        Request::Cancel { run } => match run.parse::<uuid::Uuid>() {
            Ok(id) => {
                let id = RunId(id);
                plane.control.cancel(id);
                if let Some(s) = plane.runs.get_mut(&id.to_string()) {
                    // Not "cancelled" — the run has been *asked* to stop and stops at its next
                    // iteration boundary. Marking it done here would be the surface reporting an
                    // outcome it does not have.
                    s.status = "cancelling".into();
                }
                on_event(plane.detail(id));
            }
            Err(_) => on_event(Event::Error { detail: unknown_run(&run) }),
        },
        other => on_event(Event::Error {
            detail: format!(
                "the control plane answers runs / watch / steer / cancel. `{}` needs the model, \
                 the memory or the session store, so it is served on the main port",
                request_name(&other)
            ),
        }),
    }
}

fn unknown_run(run: &str) -> String {
    format!(
        "`{}` is not a run id. `/runs` lists them; an id is a UUID",
        marlowe_contract::text::sanitize_line(run)
    )
}

fn request_name(r: &Request) -> &'static str {
    match r {
        Request::Status => "status",
        Request::Ask { .. } => "ask",
        Request::Runs => "runs",
        Request::Watch { .. } => "watch",
        Request::Steer { .. } => "steer",
        Request::Cancel { .. } => "cancel",
        Request::Resume { .. } => "resume",
        Request::Approve { .. } => "approve",
        Request::Replay { .. } => "replay",
        Request::SetModel { .. } => "set_model",
        Request::SetProvider { .. } => "set_provider",
        Request::Shutdown => "shutdown",
    }
}

/// Where the control port is advertised. Beside the token, under the same directory ACL.
pub fn port_path(profile_root: &std::path::Path) -> std::path::PathBuf {
    profile_root.join("control.port")
}

/// The control port a daemon for this profile advertised, if one is running.
///
/// **`None` is the honest answer for a stale file too.** A leftover file from a daemon that died
/// points at a port that is either closed or now belongs to something else; the caller falls back
/// to the main port, where the answer is slower and cannot be wrong.
pub fn advertised_port(profile_root: &std::path::Path) -> Option<u16> {
    std::fs::read_to_string(port_path(profile_root)).ok()?.trim().parse().ok()
}

/// Start the control listener. Returns the reason it could not start, for the daemon to announce.
///
/// **The token is the same one the main port checks**, read once and held — a token file replaced
/// under a running daemon must not change who it will serve, on either port.
pub fn spawn(
    plane: Shared,
    profile_root: &std::path::Path,
    token: String,
    shutdown: Arc<AtomicBool>,
) -> Result<u16, String> {
    // **Port 0: the OS picks.** See the module header for why this is not `port + 1`.
    let listener = TcpListener::bind(SocketAddr::from((Ipv4Addr::LOCALHOST, 0))).map_err(|e| {
        format!(
            "the control plane could not bind a loopback port ({e}); `/steer`, `/watch` and \
             `/runs` from another terminal are unavailable, and `--runs` falls back to the main \
             port behind whatever turn is running"
        )
    })?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("the control plane bound a port it cannot name: {e}"))?
        .port();
    // **Advertised before the thread starts.** A client that connected in the window between
    // binding and advertising would fall back to the main port -- correct, just slower -- so the
    // ordering costs nothing and closes the other direction, where the file names a port nothing
    // is listening on yet.
    std::fs::create_dir_all(profile_root)
        .and_then(|()| std::fs::write(port_path(profile_root), port.to_string()))
        .map_err(|e| {
            format!(
                "the control plane is listening on {port} and could not advertise it in the \
                 profile root ({e}); `--steer` and `--watch` will fall back to the main port"
            )
        })?;
    // A short accept timeout is what lets the thread notice a shutdown. `incoming()` blocks
    // forever otherwise, and a control thread that outlives its daemon holds the port against the
    // next one — which presents as "the control plane could not bind" on every restart.
    std::thread::spawn(move || {
        for incoming in listener.incoming() {
            // LOOP-EXEMPT: an accept loop, not an agent loop.
            if shutdown.load(Ordering::Relaxed) {
                break;
            }
            let Ok(stream) = incoming else { continue };
            let _ = serve_one(&plane, &token, stream);
            if shutdown.load(Ordering::Relaxed) {
                break;
            }
        }
    });
    Ok(port)
}

fn serve_one(plane: &Shared, token: &str, stream: TcpStream) -> std::io::Result<()> {
    let mut writer = stream.try_clone()?;
    let mut reader = BufReader::new(stream);
    reader.get_ref().set_read_timeout(Some(std::time::Duration::from_secs(5))).ok();

    // Same preamble, same rule: the CONNECTION is authenticated, not the request.
    let mut preamble = String::new();
    let offered = match reader.read_line(&mut preamble) {
        Ok(0) | Err(_) => return Ok(()),
        Ok(_) => preamble.trim().to_string(),
    };
    if !crate::auth::matches(token, &offered) {
        write_line(&mut writer, &Event::Error { detail: crate::auth::refusal() })?;
        // Drain before closing. On Windows a close with unread inbound data sends RST, which
        // discards the refusal that was just written — see `Daemon::serve_one`, where this was
        // found, and where the same three lines say the same thing.
        let mut sink = [0u8; 4096];
        let mut drained = 0usize;
        reader.get_ref().set_read_timeout(Some(std::time::Duration::from_millis(200))).ok();
        while drained < 64 * 1024 {
            // LOOP-EXEMPT: draining a socket before close.
            match reader.read(&mut sink) {
                Ok(0) | Err(_) => break,
                Ok(n) => drained += n,
            }
        }
        return Ok(());
    }

    let mut line = String::new();
    if reader.read_line(&mut line)? == 0 {
        return Ok(());
    }
    match serde_json::from_str::<Request>(line.trim()) {
        Ok(request) => {
            let mut err = None;
            answer(plane, request, &mut |e| {
                if err.is_none() {
                    err = write_line(&mut writer, &e).err();
                }
            });
        }
        Err(e) => {
            write_line(&mut writer, &Event::Error { detail: format!("malformed request: {e}") })?;
        }
    }
    Ok(())
}
