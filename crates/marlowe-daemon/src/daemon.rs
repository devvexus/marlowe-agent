//! The daemon. Owns the journal, the engine, and the run table.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use marlowe_contract::TrustClass;
use marlowe_exec::FileSystemTools;
use marlowe_journal::{Journal, Profile};
use crate::clock::SystemClock;
use marlowe_loop::{
    ApprovalGate, Budget, CapabilityProfile, ClockSource, Engine, GovernanceConstraint,
    JournalRecorder, LoopOutcome, MemoryRecorder, NoControl, OutputContract, Ports, Provenance,
    Run, RunId, SessionId, SessionState, Summarizer, ToolLineState, TurnEvent, TurnSink,
    MEMORY_TOKEN_BUDGET,
};
use marlowe_permission::scope::WorkspaceScope;
use marlowe_permission::{BlastRadius, Tier};
use marlowe_provider::{capability_for, Availability, LocalEndpoint, OllamaDriver, Routing};
use marlowe_tools::builtin_registry;

use crate::protocol::{Event, Request, StatusReport};
use crate::DEFAULT_DAEMON_PORT;

#[derive(Debug, thiserror::Error)]
pub enum DaemonError {
    #[error("could not open the profile at {root}: {detail}")]
    Profile { root: String, detail: String },
    #[error("could not listen on 127.0.0.1:{port}: {detail}")]
    Listen { port: u16, detail: String },
    #[error(
        "path scoping refuses to run here: {detail}. The daemon does not start without it — a \
         harness with filesystem tools and no wall is the configuration ADR-002 removed the \
         kernel backstop from"
    )]
    Scope { detail: String },
    #[error("{detail}")]
    Setup { detail: String },
    /// The fifth instance of the `done` defect, refused at startup. See
    /// `marlowe_loop::profile::UnrunnableTools`.
    #[error("{0}")]
    UnrunnableTools(#[from] marlowe_loop::UnrunnableTools),
}

pub struct DaemonConfig {
    pub profile_root: PathBuf,
    pub workspace: PathBuf,
    pub port: u16,
    pub model: String,
    /// ADR-029: the active rerank provider, **announced** rather than silently chosen. Read from
    /// the field the profile row stamps; this crate does not derive a second one.
    pub rerank_provider: String,
    /// `--dev`: write raw provider frames and the outbound request to stderr.
    pub dev: bool,
    /// Whether the model separates reasoning into the `thinking` channel.
    ///
    /// Declared here so a run states it rather than inheriting whatever the provider defaults to.
    pub thinking: bool,
    /// The context window in tokens. **One number**: it becomes both `num_ctx` on every request
    /// and the assembler's window, so §6's 70% compaction trigger is computed against the window
    /// the provider actually has.
    pub context_tokens: u32,
    /// The cross-encoder directory. `None` makes memory **write-only**, announced by
    /// [`crate::memory::RetrievalState`] and printed by `--status`.
    ///
    /// Not required, deliberately, and this is the one place this session accepts an absent
    /// dependency rather than a load-time error. The eval adapter requires it because a run without
    /// it measures a different system under the same label; the product's failure mode is
    /// different — refusing to start would make a 60 MB model an install-time dependency of being
    /// able to talk at all, which is K6. What must never happen is retrieval silently not running,
    /// and that is what the announcement closes.
    pub reranking: Option<PathBuf>,
}

impl DaemonConfig {
    pub fn new(profile_root: PathBuf, workspace: PathBuf) -> Self {
        Self {
            profile_root,
            workspace,
            port: DEFAULT_DAEMON_PORT,
            model: marlowe_provider::DEFAULT_MODEL.to_string(),
            // Until retrieval is wired (M2 D) there is no profile row to read, and inventing a
            // value here would be the second source ADR-029 forbids. The honest value is that
            // nothing has announced one yet.
            rerank_provider: "not-wired".to_string(),
            dev: false,
            thinking: true,
            context_tokens: marlowe_provider::DEFAULT_CONTEXT_TOKENS,
            reranking: None,
        }
    }
}

/// A run the daemon owns, as the client is allowed to see it.
#[derive(Debug, Clone)]
pub struct RunSummary {
    pub id: String,
    pub status: String,
    pub tokens: u64,
    pub depth: u8,
}

/// Turns a loop event into a wire event. Render-only.
///
/// `TurnEvent::Done` returns `None`: the loop's own Done carries no outcome, and the daemon emits
/// a richer one after `engine.run` returns. Under the old collecting sink that was fixed up by
/// `retain`ing it out of the vector afterwards — **which streaming makes impossible**, because a
/// written event cannot be recalled. Filtering at the point of emission is the same correction
/// made where it still works.
fn to_wire(event: TurnEvent) -> Option<Event> {
    Some(match event {
        TurnEvent::TextDelta(t) => Event::Text { delta: t },
        TurnEvent::ReasoningDelta(t) => Event::Reasoning { delta: t },
        TurnEvent::SpeechRetracted => Event::SpeechRetracted,
            TurnEvent::ToolLine { id, verb, target, state } => {
                let (state, summary) = match state {
                    ToolLineState::Running { elapsed_ms } => {
                        ("running".to_string(), format!("{elapsed_ms} ms"))
                    }
                    ToolLineState::Ok(s) => ("ok".to_string(), s.render()),
                    ToolLineState::Failed(s) => ("failed".to_string(), s.render()),
                };
                Event::Tool { id, verb, target, state, summary }
            }
            TurnEvent::Compacted { turns } => Event::Compacted { turns },
            TurnEvent::Degraded { what } => Event::Degraded {
                what: what.headline().to_string(),
                // The specific remedy is the provider's to state; the loop only knows the class.
                remedy: "see `marlowe --status`".to_string(),
            },
            // **The prompt the GATE sends is the one that carries a decision id.** This one is
            // the loop announcing that it is about to ask, so it is render-only and its id is 0.
            TurnEvent::ApprovalPrompt(br) => Event::Approval {
                decision: 0,
                verb: br.verb,
                scope: br.scope,
                reversible: br.reversible,
                novelty: br.novelty.map(|n| format!("{n:?}")),
            },
        TurnEvent::Done { .. } => return None,
    })
}

/// A sink that hands each event to a callback **as the loop produces it**.
///
/// # This is the structural half of streaming
///
/// The previous sink was `struct Collector { events: Vec<Event> }`, and `Daemon::ask` returned
/// that vector — so the daemon computed every model call and every tool execution before writing
/// a single byte to the socket. Layers 1 and 4 could stream perfectly and the user would still see
/// nothing until the turn was over, because the middle held everything.
///
/// The callback is what lets `serve_one` write-and-flush per event and `ask` collect into a `Vec`
/// for the in-process path, without two sinks that could drift.
struct CallbackSink<F: FnMut(Event)> {
    on_event: F,
}

impl<F: FnMut(Event)> TurnSink for CallbackSink<F> {
    fn emit(&mut self, event: TurnEvent) {
        if let Some(e) = to_wire(event) {
            (self.on_event)(e);
        }
    }
}

/// M2's approval gate: **deny by default**.
///
/// A daemon with no interactive surface attached cannot ask, and a gate that auto-approved
/// because nobody was listening would make §8.2's "approvals are enforced by the harness" a
/// statement about a code path that never runs. The interactive gate arrives with the TUI.
struct DenyUnattended;

impl ApprovalGate for DenyUnattended {
    fn await_approval(&mut self, _radius: &BlastRadius) -> bool {
        false
    }
}

/// The interactive gate: **asks the client that opened this connection, and blocks.**
///
/// # Why it round-trips on the existing connection rather than waiting for `Request::Approve`
///
/// The daemon is serial — `serve` accepts one connection, serves it to completion, then accepts
/// the next. A client that answered on a *second* connection would be talking to a listener that
/// is not listening: the turn holding the first connection is exactly what is blocked. So the
/// approval travels on the socket that is already open. The daemon writes `Event::Approval` and
/// then reads one line back.
///
/// **It holds its own clones of the socket**, rather than sharing the event writer. Two mutable
/// borrows of one writer would not compile, and the alternative — routing the prompt through the
/// event callback and the answer through somewhere else — would split one exchange across two
/// mechanisms. Writes are sequential on one thread, so ordering on the wire is preserved.
///
/// **Every failure is a denial.** A hung-up client, a malformed reply, a reply naming a different
/// decision: all return `false`. §8.2 puts enforcement in the harness, and a gate that approved
/// because it could not hear the answer would be enforcement in name only.
struct SocketApprovals {
    writer: TcpStream,
    reader: BufReader<TcpStream>,
    next_decision: u64,
    /// The reason given with the most recent decline, read back by the loop.
    last_reason: Option<String>,
}

impl SocketApprovals {
    fn new(writer: TcpStream, reader: BufReader<TcpStream>) -> Self {
        Self { writer, reader, next_decision: 1, last_reason: None }
    }
}

impl ApprovalGate for SocketApprovals {
    /// A client is on the other end of this socket, so somebody can be asked.
    fn is_interactive(&self) -> bool {
        true
    }

    fn decline_reason(&self) -> Option<String> {
        self.last_reason.clone()
    }

    fn await_approval(&mut self, radius: &BlastRadius) -> bool {
        let decision = self.next_decision;
        self.next_decision += 1;

        // §B9 wants the blast radius stated rather than the command. `scope` carries every
        // declared Target — including the numeric ones, which `ArgValue::render` made visible in
        // M2 C2f; before that a spend ceiling was silently absent from this line.
        //
        // **`novelty` is carried as an Option and is NOT defaulted.** §B9 asks for a novelty
        // reason and a ceiling; the ceiling has no producer yet (the trust ledger is M6). Sending
        // `"routine"` because nothing said otherwise would be a claim about promotion logic
        // nobody has written. Absent renders as absent.
        let prompt = Event::Approval {
            decision,
            verb: radius.verb.clone(),
            scope: radius.scope.clone(),
            reversible: radius.reversible,
            novelty: radius.novelty.as_ref().map(|n| format!("{n:?}")),
        };
        if crate::protocol::write_line(&mut self.writer, &prompt).is_err() {
            return false;
        }

        // Cleared before the ask, so a reason from an earlier decline cannot be reported against
        // this one.
        self.last_reason = None;

        let mut line = String::new();
        match self.reader.read_line(&mut line) {
            Ok(0) | Err(_) => false,
            Ok(_) => match serde_json::from_str::<Request>(line.trim()) {
                // The reply must name the decision it is answering. A client that answered a
                // stale prompt would otherwise approve whatever is pending now.
                Ok(Request::Approve { decision: d, granted, reason }) if d == decision => {
                    if !granted {
                        self.last_reason = reason.filter(|r| !r.trim().is_empty());
                    }
                    granted
                }
                _ => false,
            },
        }
    }
}

/// A summarizer that refuses to invent a summary it did not produce.
struct PassthroughSummarizer;

impl Summarizer for PassthroughSummarizer {
    fn summarize(&mut self, view: &marlowe_loop::ContextView) -> String {
        // Until a cheap model is routed for this (ADR-008), compaction keeps the most recent
        // volatile text rather than fabricating a summary. Stated plainly because a summarizer
        // that silently returned "" would make governance survival untestable for the wrong
        // reason — it would pass while doing nothing.
        view.volatile
            .iter()
            .rev()
            .take(3)
            .map(|b| b.text.as_str())
            .collect::<Vec<_>>()
            .join("\n")
    }
}

/// Everything a conversation carries from one turn to the next.
///
/// # Why this exists
///
/// It did not, and Marlowe could not summarize the conversation he was in. `ask_streaming` built
/// a fresh `SessionState` on **every** request, so the model was handed the identity block,
/// governance, and one user message — turn 1, every time. Asking "what did we just discuss?"
/// produced an honest answer about an empty history, which reads as amnesia and is worse than a
/// crash, because nothing in the system reports a fault.
///
/// The session **id** was already stable (`SessionId::from_name`), which is what made this hard to
/// see: everything downstream was correctly keyed to a conversation that was never stored.
///
/// `Provenance` travels with the state because it is the attribution of *those* blocks. Rebuilding
/// it per turn would leave the assembled history with no record of which parts came from the user,
/// which is what ADR-023's taint computation reads.
struct SessionMemory {
    state: SessionState,
    provenance: Provenance,
}

/// The one place a tool host is built.
///
/// **A single constructor is the fix for a real gap**, not a tidy-up. `verify_every_exposed_tool_is_runnable`
/// is only evidence about the turn if it is handed the same host the turn runs; two construction
/// sites is two hosts that can drift, and the drift is invisible in the direction that matters —
/// a runtime host missing an executor the verified one had would pass startup and fail on the call.
fn build_tool_host(
    workspace: &std::path::Path,
    beliefs: std::sync::Arc<std::sync::Mutex<marlowe_memory::BeliefStore>>,
) -> Result<crate::recall::RecallTools<FileSystemTools<WorkspaceScope>>, DaemonError> {
    let scope = WorkspaceScope::new().map_err(|e| DaemonError::Scope { detail: e.to_string() })?;
    Ok(crate::recall::RecallTools::new(
        FileSystemTools::new(scope, workspace.to_path_buf()),
        beliefs,
    ))
}

pub struct Daemon {
    config: DaemonConfig,
    /// One log, two writers inside a turn: the loop's recorder and the memory host.
    journal: std::sync::Arc<std::sync::Mutex<Journal>>,
    /// M2 Session D. `memory: None` used to be passed to every turn — which was concealing that
    /// there was no single-claim write path to wire, not merely that it was unwired.
    memory: crate::memory::DaemonMemory,
    runs: BTreeMap<String, RunSummary>,
    /// Keyed by the client's session name — the same key `SessionId::from_name` derives from.
    sessions: BTreeMap<String, SessionMemory>,
    shutdown: Arc<AtomicBool>,
    /// The socket token. See [`crate::auth`] — loopback is per-machine, not per-user.
    ///
    /// Held on the daemon rather than re-read per connection: a token file replaced under a running
    /// daemon must not change who it will serve, and re-reading would make that possible for anyone
    /// who could write the profile root.
    token: String,
}

impl Daemon {

    /// How many history blocks this conversation is carrying. **Test surface for the session
    /// store** — the amnesia bug was invisible from outside because the session *id* was stable
    /// while the state behind it was not.
    pub fn session_turn_count(&self, session: &str) -> usize {
        self.sessions.get(session).map_or(0, |m| m.state.history_len())
    }

    /// Append a user turn to a session's history without calling a model.
    ///
    /// Exists so the store can be driven in a test that must not depend on Ollama being up.
    pub fn remember_user_turn(&mut self, session: &str, message: &str) {
        let session_id = SessionId::from_name(session);
        let memory = self.sessions.remove(session).unwrap_or_else(|| SessionMemory {
            state: SessionState::new(session_id, identity_block()),
            provenance: Provenance::new(),
        });
        let SessionMemory { mut state, mut provenance } = memory;
        provenance.attribute_user_message(message);
        state.push(marlowe_loop::Block::new(
            marlowe_loop::SourceKind::History,
            message,
            TrustClass::UserAsserted,
        ));
        self.sessions.insert(session.to_string(), SessionMemory { state, provenance });
    }

    pub fn open(config: DaemonConfig) -> Result<Self, DaemonError> {
        // Path scoping must be constructible before anything else. A daemon that started on an
        // unverified platform and refused paths later would present as broken tools.
        WorkspaceScope::new().map_err(|e| DaemonError::Scope { detail: e.to_string() })?;

        let profile = if config.profile_root.join("profile.json").exists() {
            Profile::open(&config.profile_root)
        } else {
            Profile::init(&config.profile_root)
        }
        .map_err(|e| DaemonError::Profile {
            root: config.profile_root.display().to_string(),
            detail: e.to_string(),
        })?;

        let journal = Journal::open(&profile).map_err(|e| DaemonError::Profile {
            root: config.profile_root.display().to_string(),
            detail: e.to_string(),
        })?;

        // **Shared, because one turn has two writers.** The loop records through it and the memory
        // host signs through it, and a second `Journal` would be a second append-only log — the
        // one thing this project's core abstraction says there is exactly one of. See
        // `marlowe_loop::record::SharedJournalRecorder`.
        let journal = std::sync::Arc::new(std::sync::Mutex::new(journal));

        // **Beliefs are rebuilt from the log here**, which is what makes memory durable across a
        // restart without any new persistence machinery. A derivation failure stops the daemon
        // rather than starting it with an empty store: a silently forgotten store is
        // indistinguishable from a first run, and would report itself healthy.
        let memory = crate::memory::DaemonMemory::open(
            std::sync::Arc::clone(&journal),
            profile.manifest().derivation_version,
            config.reranking.as_deref(),
        )
        .map_err(|e| DaemonError::Profile {
            root: config.profile_root.display().to_string(),
            detail: format!("the belief store could not be derived from the journal: {e}"),
        })?;

        // **Refuse to start rather than offer a tool that cannot run.** A daemon that starts and
        // then fails every `recall` call presents as a broken model; this names the tool instead.
        //
        // **It verifies the host it will actually use.** Until M2 Session D this checked a bare
        // `FileSystemTools` while the turn ran a different object — and when `recall` gained its
        // executor the guard refused a daemon that could in fact run it. It failed loudly, which
        // was luck: the same gap in the other direction — a runtime host with FEWER executors than
        // the verified one — would pass here and fail on the turn, which is precisely the `done`
        // defect that cost a run 155 seconds. `build_tool_host` is now the only way to construct
        // one, so the two cannot differ.
        marlowe_loop::verify_every_exposed_tool_is_runnable(
            CapabilityProfile::interactive().exposed_tools(),
            &build_tool_host(&config.workspace, memory.beliefs())?,
        )?;

        // **Minted before the listener binds, and a failure here refuses to start.** A daemon that
        // could not establish a token would otherwise have to choose between serving everyone and
        // serving no one, and the first of those is the vulnerability this closes.
        let token = crate::auth::ensure_token(&config.profile_root).map_err(|e| {
            DaemonError::Profile {
                root: config.profile_root.display().to_string(),
                detail: format!("the socket token could not be established: {e}"),
            }
        })?;

        Ok(Self {
            config,
            journal,
            memory,
            runs: BTreeMap::new(),
            sessions: BTreeMap::new(),
            shutdown: Arc::new(AtomicBool::new(false)),
            token,
        })
    }

    /// What the retrieval half of memory is doing. Printed at startup; see
    /// [`crate::memory::RetrievalState`].
    pub fn memory_state(&self) -> &crate::memory::RetrievalState {
        self.memory.state()
    }

    pub fn shutdown_handle(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.shutdown)
    }

    pub fn live_runs(&self) -> usize {
        self.runs.values().filter(|r| r.status == "running").count()
    }

    /// What §B5's band and first-run onboarding need, without touching a model.
    pub fn status(&self) -> StatusReport {
        let endpoint = LocalEndpoint::default_ollama();
        let routing = Routing::uniform(&self.config.model);
        // **One probe, two answers.** The availability check already enumerates what the endpoint
        // holds, so asking again for the picker would be a second source of the same fact — the
        // shape ADR-029 forbids for `rerank_provider` and the shape this project has logged a dozen
        // instances of.
        let mut models: Vec<String> = Vec::new();
        let degraded = match &routing {
            Err(e) => Some(e.to_string()),
            Ok(r) => {
                let a = Availability::probe(&endpoint, r);
                match &a {
                    Availability::Ready { models: m } => models = m.clone(),
                    Availability::ModelMissing { available, .. } => models = available.clone(),
                    _ => {}
                }
                (!a.is_ready()).then(|| a.remedy())
            }
        };
        // Cloud tags are dropped rather than shown: `Routing::uniform` refuses them, so offering
        // one in a picker builds a control whose only outcome is a refusal. `marlowe --models`
        // lists them *and* marks them refused, which is the right place for that — a list a person
        // reads, not a control a person operates.
        models.retain(|m| !marlowe_provider::is_cloud_tag(m));
        // The configured model is always selectable, even with the endpoint down. A picker that
        // omitted the value it is currently reporting would be internally inconsistent.
        if !models.iter().any(|m| *m == self.config.model) {
            models.push(self.config.model.clone());
        }
        models.sort();
        // **Announced, loudly, and ahead of everything else.** A daemon serving stale code
        // produces symptoms that look like bugs in whatever was just changed, and the reflex is to
        // debug the change. Invariant 4's rule applies: degrade visibly, and name the remedy.
        let degraded = crate::staleness::stale_against_source().or(degraded);
        StatusReport {
            version: env!("CARGO_PKG_VERSION").to_string(),
            workspace: self.config.workspace.display().to_string(),
            model: self.config.model.clone(),
            // **Keyed to the model this daemon actually routes to.** Handing back the default's
            // measured reliability for a user-chosen model would report one model's number under
            // another's name -- see `capability_for`.
            model_disclosure: capability_for(&self.config.model).disclosure(),
            degraded,
            rerank_provider: self.config.rerank_provider.clone(),
            live_runs: self.live_runs(),
            models,
        }
    }

    /// Switch the model this daemon routes to. **Refused by name if the endpoint does not have it.**
    ///
    /// A silent accept would leave the picker showing a model that every subsequent turn fails
    /// against, and the failure would present as a broken model rather than as a bad choice.
    pub fn set_model(&mut self, model: &str) -> Result<(), String> {
        if model == self.config.model {
            return Ok(());
        }
        let endpoint = LocalEndpoint::default_ollama();
        let routing = Routing::uniform(model).map_err(|e| e.to_string())?;
        match Availability::probe(&endpoint, &routing) {
            Availability::Ready { .. } => {
                self.config.model = model.to_string();
                Ok(())
            }
            other => Err(other.remedy()),
        }
    }

    /// One turn, start to finish. The daemon owns the run for its whole life.
    /// One turn, collecting every event. The in-process path (`marlowe --ask` with no daemon)
    /// and the tests use this; `serve_one` uses [`Self::ask_streaming`].
    pub fn ask(&mut self, session: &str, message: &str) -> Vec<Event> {
        let mut out = Vec::new();
        self.ask_streaming(session, message, |e| out.push(e));
        out
    }

    /// One turn, emitting each event **as it is produced**.
    pub fn ask_streaming(
        &mut self,
        session: &str,
        message: &str,
        mut on_event: impl FnMut(Event),
    ) {
        self.ask_streaming_with(session, message, &mut DenyUnattended, on_event)
    }

    /// As [`Self::ask_streaming`], with the approval gate supplied by the caller.
    ///
    /// **`serve_one` passes a gate that round-trips on the live connection.** The daemon is
    /// serial: it serves one request at a time, so a `Request::Approve` arriving on a *second*
    /// connection could not be read while the turn holding the first is still running. The
    /// approval therefore travels on the connection that is already open — the daemon writes
    /// `Event::Approval` and blocks reading one line back.
    pub fn ask_streaming_with(
        &mut self,
        session: &str,
        message: &str,
        approvals: &mut dyn ApprovalGate,
        mut on_event: impl FnMut(Event),
    ) {
        // The run is recorded FIRST, before anything can fail. The daemon accepted the work, so
        // the record is the daemon's from that moment — a turn that degraded is still a turn
        // that happened, and a client asking `runs` after one must not be told nothing occurred.
        // Recording it only on success made a degraded turn indistinguishable from no turn.
        let run_id = RunId::new();
        self.runs.insert(
            run_id.to_string(),
            RunSummary { id: run_id.to_string(), status: "running".into(), tokens: 0, depth: 0 },
        );
        let mark = |runs: &mut BTreeMap<String, RunSummary>, status: &str, tokens: u64| {
            if let Some(s) = runs.get_mut(&run_id.to_string()) {
                s.status = status.to_string();
                s.tokens = tokens;
            }
        };

        let endpoint = LocalEndpoint::default_ollama();
        let routing = match Routing::uniform(&self.config.model) {
            Ok(r) => r,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                on_event(Event::Error { detail: e.to_string() });
                return;
            }
        };

        let availability = Availability::probe(&endpoint, &routing);
        if !availability.is_ready() {
            mark(&mut self.runs, "degraded", 0);
            // Invariant 4: a declared, actionable state — not a crash and not a silent stub.
            on_event(Event::Degraded {
                what: "no model available".into(),
                remedy: availability.remedy(),
            });
            on_event(Event::Done {
                outcome: "degraded".into(),
                detail: availability.remedy(),
                spend_micros_usd: 0,
                elapsed_ms: 0,
            });
            return;
        }

        let registry = match builtin_registry() {
            Ok(r) => r,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                on_event(Event::Error { detail: e.to_string() });
                return;
            }
        };
        let scope = match WorkspaceScope::new() {
            Ok(s) => s,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                on_event(Event::Error { detail: e.to_string() });
                return;
            }
        };
        // **Derived, not restated.** The assembler's window is the same number the driver sends
        // as `num_ctx`. Before C2e these were 32_000 and (unset -> 2048): the assembler packed
        // 32k of context into a 2k window and §6's trigger fired against a window that did not
        // exist. `tests/context_window.rs` fails if they ever diverge again.
        let window = self.config.context_tokens;
        let reserve = (window / 16).max(512);
        let mut engine = Engine::new(
            registry,
            scope,
            window,
            reserve,
            self.config.workspace.clone(),
            Tier::Act,
        );

        let mut driver = OllamaDriver::new(
            endpoint,
            routing,
            builtin_registry().expect("the builtins loaded a moment ago"),
        )
        .with_capability(capability_for(&self.config.model))
        .with_context_tokens(self.config.context_tokens)
        .with_thinking(self.config.thinking);

        // **`--dev`: the provider's own wire, before interpretation.**
        //
        // A slow turn and a hung one look identical from outside, and this is the only view that
        // separates *the model is emitting slowly* from *nothing is arriving*. It writes to the
        // daemon's stderr rather than the transcript: it is a diagnostic, and §B1's rule that
        // instrumentation lives under `--dev` applies to the provider seam as much as to memory.
        if self.config.dev {
            // The outbound request, once per model call. This is the reading that settles whether
            // the persona reached the model — the constructed-body test cannot.
            driver = driver.with_request_dump(Box::new(|body| {
                let system: Vec<&str> = body
                    .get("messages")
                    .and_then(|m| m.as_array())
                    .map(|ms| {
                        ms.iter()
                            .filter(|m| m.get("role").and_then(|r| r.as_str()) == Some("system"))
                            .filter_map(|m| m.get("content").and_then(|c| c.as_str()))
                            .collect()
                    })
                    .unwrap_or_default();
                eprintln!("[dev] ===== OUTBOUND REQUEST =====");
                eprintln!(
                    "[dev] model={} num_ctx={} num_predict={}",
                    body.get("model").and_then(|m| m.as_str()).unwrap_or("?"),
                    body.pointer("/options/num_ctx")
                        .map(|v| v.to_string())
                        .unwrap_or_else(|| "UNSET (Ollama defaults to 2048)".into()),
                    body.pointer("/options/num_predict")
                        .map(|v| v.to_string())
                        .unwrap_or_else(|| "unset".into()),
                );
                eprintln!("[dev] system messages: {}", system.len());
                for (i, sys) in system.iter().enumerate() {
                    eprintln!("[dev] --- system[{i}] ({} chars) ---", sys.len());
                    for line in sys.lines() {
                        eprintln!("[dev] | {line}");
                    }
                }

                // **Every message, with its role.** The dump printed only the system tier, so the
                // shape of the conversation — the thing that decides whether the model can see its
                // own previous tool calls — was the one part of the request `--dev` could not
                // show. An instrument that omits the interesting half is how a wrong answer looks
                // authoritative.
                if let Some(msgs) = body.get("messages").and_then(|m| m.as_array()) {
                    eprintln!("[dev] --- conversation ({} messages) ---", msgs.len());
                    for (i, m) in msgs.iter().enumerate() {
                        let role = m.get("role").and_then(|r| r.as_str()).unwrap_or("?");
                        let content =
                            m.get("content").and_then(|c| c.as_str()).unwrap_or("");
                        let calls = m
                            .get("tool_calls")
                            .and_then(|t| t.as_array())
                            .map(|a| a.len())
                            .unwrap_or(0);
                        let name = m.get("tool_name").and_then(|n| n.as_str()).unwrap_or("");
                        eprintln!(
                            "[dev] [{i:>3}] {role:<9} {:>5} chars  tool_calls={calls}  tool_name={name:?}  {:?}",
                            content.len(),
                            content.chars().take(70).collect::<String>()
                        );
                    }
                }
                eprintln!(
                    "[dev] tools offered: {}",
                    body.get("tools")
                        .and_then(|t| t.as_array())
                        .map(|a| a
                            .iter()
                            .filter_map(|t| t.pointer("/function/name").and_then(|n| n.as_str()))
                            .collect::<Vec<_>>()
                            .join(", "))
                        .unwrap_or_else(|| "NONE".into())
                );
                // **The literal bytes.** Every summary above is a rendering of this; when the two
                // disagree the summary is wrong, and only this settles it.
                if std::env::var("MARLOWE_DUMP_BODY").is_ok() {
                    eprintln!("[dev] ===== RAW BODY =====");
                    eprintln!("{}", serde_json::to_string_pretty(body).unwrap_or_default());
                }
                eprintln!("[dev] ===== END REQUEST =====");
            }));

            let mut n: u64 = 0;
            driver = driver.with_raw_frames(Box::new(move |frame| {
                n += 1;
                let think = frame
                    .get("message")
                    .and_then(|m| m.get("thinking"))
                    .and_then(|c| c.as_str())
                    .unwrap_or("");
                let text = frame
                    .get("message")
                    .and_then(|m| m.get("content"))
                    .and_then(|c| c.as_str())
                    .unwrap_or("");
                if !think.is_empty() {
                    eprintln!("[dev] frame {n:>4}  THINK {:>4} bytes", think.len());
                }
                let done = frame.get("done").and_then(|d| d.as_bool()).unwrap_or(false);
                eprintln!(
                    "[dev] frame {n:>4}  {:>5} bytes  done={done}  {:?}",
                    text.len(),
                    text.chars().take(60).collect::<String>()
                );
            }));
        }
        let tool_scope = match WorkspaceScope::new() {
            Ok(s) => s,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                on_event(Event::Error { detail: e.to_string() });
                return;
            }
        };
        // **`recall` gets its executor here.** STATE.md predicted the consequence: `consolidation()`
        // exposes `recall`, so `verify_every_exposed_tool_is_runnable` would refuse the moment
        // memory was wired — *"the guard firing then is the guard working"*. It fires against a
        // host that can now answer, which is the resolution rather than an exemption.
        let _ = tool_scope;
        let mut tools = match build_tool_host(&self.config.workspace, self.memory.beliefs()) {
            Ok(h) => h,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                on_event(Event::Error { detail: e.to_string() });
                return;
            }
        };
        let mut summarizer = PassthroughSummarizer;
        let mut sink = CallbackSink { on_event: &mut on_event };
        let mut control = NoControl;
        let mut clock = SystemClock;

        let session_id = SessionId::from_name(session);
        let mut run = Run::root(
            run_id,
            session_id,
            CapabilityProfile::interactive(),
            Budget::interactive(),
            OutputContract::answer(),
        );
        // **Resumed, not rebuilt.** Governance is asserted once when the conversation starts;
        // `assert_governance` appends, so re-asserting per turn would grow the stable tier by two
        // blocks a turn until compaction had nothing left to trim.
        let workspace_rule = format!(
            "The workspace is {}. Every path you name is relative to it.",
            self.config.workspace.display()
        );
        let memory = self.sessions.remove(session).unwrap_or_else(|| {
            let mut state = SessionState::new(session_id, identity_block());
            // §6: governance lives in the stable tier and is re-asserted structurally. The
            // workspace scope is a user-visible constraint, so it is stated to the model as one.
            state.assert_governance(GovernanceConstraint::asserted(&workspace_rule));
            // **This told the model to call a tool that does not exist.** `done` was removed from
            // the vocabulary when completion became the *absence* of an action — a small model
            // cannot be trusted to emit a terminator reliably, so the loop ends on prose with no
            // tool call. The prompt was not updated with it, so every turn instructed the model to
            // finish with `done`, and the model tried. Found in `--dev`'s outbound dump on a real
            // run; no test could see it, because nothing asserts that the prompt names only tools
            // that exist.
            state.assert_governance(GovernanceConstraint::asserted(governance_prompt()));
            SessionMemory { state, provenance: Provenance::new() }
        });
        let SessionMemory { mut state, mut provenance } = memory;
        provenance.attribute_user_message(message);
        state.push(marlowe_loop::Block::new(
            marlowe_loop::SourceKind::History,
            message,
            TrustClass::UserAsserted,
        ));

        // ── §4.2 retrieval, before the model speaks ────────────────────────────────────
        //
        // **M2 Session D, and the half that makes memory a product feature rather than a
        // measurement.** `select_for_injection` had exactly one caller — the eval adapter — so
        // conformance, `repro` and the poisoning suite all exercised injection while the daemon,
        // the thing a person actually talks to, contained no retrieval at all. A property measured
        // on one path and claimed for another is this project's most-logged mistake, and D2 shipped
        // it before D2b caught it.
        //
        // **§B1 is binding: none of this is visible in the interface.** No banner, no citation, no
        // tool line. The user experiences memory through Marlowe knowing things. The diagnostic
        // goes to the daemon's stderr under `--dev` only.
        //
        // The block carries the memories' own trust floor, never a class chosen here. Injecting an
        // untrusted memory at a higher class is precisely the laundering §3.3 exists to close, and
        // `ContextView::trust_floor` is `min` over all blocks including this one — so a recalled
        // web-derived belief correctly drops the run's floor and blocks composed targets.
        let now_for_memory = clock.now_ms();
        let retrieved = self.memory.retrieve(session, message, now_for_memory, MEMORY_TOKEN_BUDGET);
        if self.config.dev {
            eprintln!(
                "[dev] memory: {} · injected {} · margin {:?} · abstained {:?}",
                self.memory.state().headline(),
                retrieved.count,
                retrieved.margin,
                retrieved.abstention.map(|a| a.as_str()),
            );
        }
        if !retrieved.is_empty() {
            state.push(marlowe_loop::Block::new(
                marlowe_loop::SourceKind::InjectedMemory,
                retrieved.text.clone(),
                retrieved.floor,
            ));
        }

        let trace = run.trace_id;
        let mut recorder =
            marlowe_loop::record::SharedJournalRecorder::new(std::sync::Arc::clone(&self.journal), trace);
        let outcome = {
            let mut ports = Ports {
                driver: &mut driver,
                summarizer: &mut summarizer,
                tools: &mut tools,
                memory: Some(&mut self.memory),
                approvals,
                sink: &mut sink,
                control: &mut control,
                clock: &mut clock,
                recorder: &mut recorder,
            };
            engine.run(&mut run, &mut state, &mut provenance, &mut ports)
        };
        drop(sink);

        // **The turn's history goes back into the conversation.** `engine.run` has pushed the
        // model's prose and every tool result onto `state`; dropping it here is precisely the bug
        // this store exists for.
        self.sessions.insert(session.to_string(), SessionMemory { state, provenance });

        let (status, detail) = match &outcome {
            // **Empty, and that is the fix for a double-send.**
            //
            // M2 C2e made the reply the result, so `CondensedResult` now holds the SAME text the
            // model already streamed as `TextDelta`s. Rendering it here put it on screen twice:
            // once as the answer, then again as `answer: Hello.` — observed live.
            //
            // The turn's prose reaches the user through the stream. `Done` carries the OUTCOME,
            // not a second copy of the content; a client that wants the structured result asks
            // for the run, which is the only place it belongs.
            LoopOutcome::Completed(_) => ("completed", String::new()),
            LoopOutcome::Paused { reason } => ("paused", format!("{reason:?}")),
            LoopOutcome::Escalated { question } => ("escalated", question.clone()),
            LoopOutcome::Cancelled => ("cancelled", String::new()),
            LoopOutcome::Failed { error } => ("failed", error.clone()),
        };
        mark(&mut self.runs, status, run.spent.tokens);

        // The loop's own Done was filtered at emission (`to_wire`), so this is the only one.
        on_event(Event::Done {
            outcome: status.into(),
            detail,
            spend_micros_usd: run.spent.micros_usd,
            elapsed_ms: run.spent.wall_ms,
        });
    }

    pub fn runs(&self) -> Vec<Event> {
        self.runs
            .values()
            .map(|r| Event::Run {
                id: r.id.clone(),
                status: r.status.clone(),
                tokens: r.tokens,
                depth: r.depth,
            })
            .collect()
    }

    /// Answer a request, emitting each event **as it is produced**.
    ///
    /// `Ask` streams; everything else is a single frame and has nothing to stream.
    fn handle(
        &mut self,
        request: Request,
        approvals: &mut dyn ApprovalGate,
        mut on_event: impl FnMut(Event),
    ) {
        match request {
            Request::Status => on_event(Event::Status(self.status())),
            Request::Ask { session, message } => {
                self.ask_streaming_with(&session, &message, approvals, on_event)
            }
            Request::Runs => {
                for e in self.runs() {
                    on_event(e);
                }
            }
            // The gate is not wired to a surface yet; refusing is the honest answer rather than
            // recording an approval nobody gave.
            Request::Replay { session } => {
                // **The turn is reconstructed, not summarised.** A first version emitted only the
                // prose and a bare tool verb, so a reopened window lost every thinking block and
                // every tool line's target and result — the conversation came back and the work
                // behind it did not.
                //
                // Order falls out of the block order and does not need buffering: each assistant
                // turn is pushed BEFORE the result it produced, so reasoning precedes its tool
                // line exactly as it did live.
                if let Some(mem) = self.sessions.get(&session) {
                    // The call an upcoming tool result belongs to, so its line can name a target.
                    let mut pending: Option<(String, String)> = None;
                    for block in mem.state.volatile.iter() {
                        let wire = block.wire.as_ref();
                        match block.source {
                            marlowe_loop::SourceKind::History => {
                                if let Some(t) = wire.and_then(|w| w.thinking.as_ref()) {
                                    on_event(Event::Reasoning { delta: t.clone() });
                                }
                                if let Some(c) =
                                    wire.and_then(|w| w.tool_calls.first())
                                {
                                    // The first string argument is what §B6 shows as the target,
                                    // which is the same thing `blast_radius` reads.
                                    let target = c
                                        .arguments
                                        .as_object()
                                        .and_then(|o| {
                                            o.values().find_map(|v| v.as_str().map(String::from))
                                        })
                                        .unwrap_or_default();
                                    pending = Some((c.name.clone(), target));
                                }
                                if !block.text.is_empty() {
                                    if block.trust == TrustClass::AgentInferred {
                                        on_event(Event::Text { delta: block.text.clone() });
                                    } else {
                                        on_event(Event::User { text: block.text.clone() });
                                    }
                                }
                            }
                            marlowe_loop::SourceKind::ToolResults => {
                                let (verb, target) = pending.take().unwrap_or_else(|| {
                                    (
                                        wire.and_then(|w| w.tool_name.clone())
                                            .unwrap_or_else(|| "tool".into()),
                                        String::new(),
                                    )
                                });
                                let failed = wire.is_some_and(|w| w.tool_failed);
                                on_event(Event::Tool {
                                    id: 0,
                                    verb,
                                    target,
                                    state: if failed { "failed".into() } else { "ok".into() },
                                    summary: wire
                                        .and_then(|w| w.tool_summary.clone())
                                        .unwrap_or_default(),
                                });
                            }
                            _ => {}
                        }
                    }
                }
            }
            Request::SetModel { model } => {
                // Answered with a fresh `Status`, never with a bare acknowledgement. The client
                // then re-projects the daemon's own report — including the new disclosure — rather
                // than patching its view with what it hoped had happened.
                match self.set_model(&model) {
                    Ok(()) => on_event(Event::Status(self.status())),
                    Err(detail) => on_event(Event::Error { detail }),
                }
            }
            Request::Shutdown => {
                // **Refused while a run is live.** That is exactly what invariant 6 protects: the
                // work outlives the window. An idle daemon protects nothing and is only in the
                // way.
                let live = self.runs.values().filter(|r| r.status == "running").count();
                if live > 0 {
                    on_event(Event::Error {
                        detail: format!(
                            "{live} run(s) still in flight; the daemon keeps them (invariant 6). \
                             Stop it again once they finish."
                        ),
                    });
                } else {
                    self.shutdown.store(true, Ordering::Relaxed);
                    on_event(Event::Done {
                        outcome: "shutdown".into(),
                        detail: String::new(),
                        spend_micros_usd: 0,
                        elapsed_ms: 0,
                    });
                }
            }
            // **An approval arriving on its OWN connection cannot be honoured, and the reason is
            // the daemon's serialism rather than a missing feature.** The turn that raised the
            // prompt is holding the only connection being served; a second one is not read until
            // that turn finishes, by which time the decision it answers has already been denied.
            // The live path answers on the connection the prompt arrived on — see
            // `SocketApprovals`. This arm stays so the wire shape is total, and it says why.
            Request::Approve { .. } => on_event(Event::Error {
                detail: "an approval must be answered on the connection that asked for it. This                          daemon serves one connection at a time, so a decision sent on a second                          connection is read only after the turn it answers has already been                          denied. Concurrency is M3."
                    .into(),
            }),
        }
    }

    /// Serve until shut down. One connection at a time — a second client is a M3 concern and
    /// pretending to handle it now would be a concurrency story nobody tested.
    pub fn serve(mut self) -> Result<(), DaemonError> {
        let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, self.config.port));
        let listener = TcpListener::bind(addr).map_err(|e| DaemonError::Listen {
            port: self.config.port,
            detail: e.to_string(),
        })?;
        let shutdown = Arc::clone(&self.shutdown);
        let state = Mutex::new(&mut self);

        for incoming in listener.incoming() {
            // LOOP-EXEMPT: an accept loop, not an agent loop. HP10's check is scoped to
            // `marlowe-loop`; this is stated so a reader does not go looking.
            if shutdown.load(Ordering::Relaxed) {
                break;
            }
            let Ok(stream) = incoming else { continue };
            let mut guard = state.lock().expect("the daemon is single-threaded");
            let _ = guard.serve_one(stream);
            drop(guard);
            // **Checked after serving, not only before accepting.** `incoming()` blocks, so a
            // shutdown request set the flag and then the loop sat waiting for a connection that
            // would never come — the daemon answered "shutdown" and kept listening. Verified by
            // connecting again afterwards rather than by trusting the reply.
            if shutdown.load(Ordering::Relaxed) {
                break;
            }
        }
        Ok(())
    }

    fn serve_one(&mut self, stream: TcpStream) -> std::io::Result<()> {
        let mut writer = stream.try_clone()?;
        let mut reader = BufReader::new(stream);

        // ---- Authentication, before anything is parsed as a request ----------------------------
        //
        // **The CONNECTION is authenticated, not the request.** `Request` is an internally-tagged
        // enum, so a token field would have to go on every variant and every variant's construction
        // site — and the one variant somebody forgot would be an unauthenticated request that
        // deserialized fine. One preamble line cannot be forgotten per-variant.
        //
        // **Bounded, because the daemon is serial.** `serve` holds one connection at a time, so a
        // peer that connects and says nothing would hang every other client. That is true of the
        // request read as well and always has been; it is closed here because this is the read a
        // port scanner reaches first. The timeout is cleared before the turn, where a two-minute
        // model call is working rather than dead.
        reader
            .get_ref()
            .set_read_timeout(Some(std::time::Duration::from_secs(5)))
            .ok();
        let mut preamble = String::new();
        let offered = match reader.read_line(&mut preamble) {
            Ok(0) => return Ok(()), // Connected and hung up. A probe, not a client.
            Ok(_) => preamble.trim().to_string(),
            // A peer that connects and sends nothing gets nothing. Writing the refusal would tell
            // a scanner a daemon is here; closing tells it only that something accepted.
            Err(_) => return Ok(()),
        };
        if !crate::auth::matches(&self.token, &offered) {
            crate::protocol::write_line(
                &mut writer,
                &Event::Error { detail: crate::auth::refusal() },
            )?;
            return Ok(());
        }
        reader.get_ref().set_read_timeout(None).ok();
        // ----------------------------------------------------------------------------------------

        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            return Ok(());
        }
        let request: Request = match serde_json::from_str(line.trim()) {
            Ok(r) => r,
            Err(e) => {
                crate::protocol::write_line(
                    &mut writer,
                    &Event::Error { detail: format!("malformed request: {e}") },
                )?;
                return Ok(());
            }
        };
        // **Write and flush per event.** `write_line` already flushes — §4.0.2's rule that a
        // response sitting in a buffer is indistinguishable from a hang, which is exactly what the
        // whole turn used to be.
        //
        // A write failure means the client hung up. It cannot be propagated out of the callback,
        // so it is captured and returned after the turn: aborting mid-turn would leave the run
        // half-recorded, and the daemon owns the run whether or not anyone is listening
        // (invariant 6).
        // **The gate holds its own clones.** See `SocketApprovals`: the event writer is borrowed
        // by the callback below, and one exchange split across two mechanisms would be worse than
        // a second file descriptor.
        //
        // **The ORIGINAL reader is moved in, not a second one over the same socket.** A fresh
        // `BufReader` would start with an empty buffer while this one may already hold bytes the
        // client sent after the request line — those bytes would be stranded in a reader nobody
        // reads again. It is not reachable today, because the client cannot answer a prompt it has
        // not been sent yet, but a second buffer over one socket is a bug waiting for a client
        // that pipelines.
        let mut approvals = match writer.try_clone() {
            Ok(w) => Some(SocketApprovals::new(w, reader)),
            // A socket that cannot be cloned cannot carry an approval, and the honest gate for
            // that is the one that denies.
            Err(_) => None,
        };
        let mut deny = DenyUnattended;
        let gate: &mut dyn ApprovalGate = match approvals.as_mut() {
            Some(a) => a,
            None => &mut deny,
        };

        let mut write_err: Option<std::io::Error> = None;
        self.handle(request, gate, |event| {
            if write_err.is_some() {
                return;
            }
            if let Err(e) = crate::protocol::write_line(&mut writer, &event) {
                write_err = Some(e);
            }
        });
        match write_err {
            Some(e) => Err(e),
            None => writer.flush(),
        }
    }
}

/// **The persona, from the artifact.** Addendum C §C6: *"Versioned as an artifact, `persona/vN.md`
/// … **not a string in the code** and not a user setting."*
///
/// Until M2 C2d this was a 40-word `const` whose doc comment claimed it "carries the persona
/// (Addendum C)". It carried no part of Addendum C, and nothing tested the claim. `include_str!`
/// makes the artifact the single source and a change to it a reviewable diff.
///
/// **The check that matters is emission, not loading.** See
/// `marlowe-provider/tests/persona_emission.rs`.
///
/// **v2 as of M2 C2f.** It is 8.7× the size of v1 — ~3,544 tokens against ~409 by the assembler's
/// three-chars-per-token estimator, which is **11.5% of the 30,720-token effective window**,
/// permanently, in every request. That is a real cost and it is deliberate; it is recorded here
/// because a stable-tier artifact that grows silently is a compaction trigger that fires earlier
/// than anyone expects, with nothing naming the cause. The stable tier is not trimmable
/// (`SourceKind::trimmable`), so it will never be truncated to fit — it will push everything else
/// out first.
const PERSONA: &str = include_str!("../../../persona/v2.md");

/// The run's identity, which §C6 places in the stable tier *alongside* the persona rather than as
/// part of it. Kept separate so the artifact stays deployment-independent: a persona that named
/// the workspace would not be the same artifact across two runs.
const IDENTITY_FACTS: &str =
    "You are running as a terminal-native agent harness. Say what you did and what you did not, \
     and never claim a result you did not produce.";

/// What reaches the stable tier: persona first, then the run's facts.
fn identity_block() -> String {
    format!("{PERSONA}\n{IDENTITY_FACTS}")
}

/// A recorder for a daemon with no journal on disk — used by tests, never by `serve`.
pub fn memory_recorder() -> MemoryRecorder {
    MemoryRecorder::default()
}

/// How the loop's termination rule is stated to the model.
///
/// **Public so it can be asserted on.** It said *"Answer with `done` when the task is complete"*
/// for as long as `done` had not existed, and nothing could see it — the loop was right, the
/// provider was right, and a prompt is just a string until something reads it. It is a function
/// rather than a literal so `the_system_prompt_names_no_tool_that_does_not_exist` has a subject.
pub fn governance_prompt() -> &'static str {
    "Use a tool when the user asks for something a tool can do. You may call tools while      reasoning. When the task is complete, reply to the user in prose and call no tool — that is      what ends the turn."
}

#[cfg(test)]
mod approval_gate_tests {
    use super::*;
    use marlowe_permission::BlastRadius;
    use std::io::Write as _;

    fn radius() -> BlastRadius {
        BlastRadius {
            verb: "web".into(),
            scope: "https://example.com/".into(),
            reversible: true,
            novelty: None,
        }
    }

    /// A connected pair, so the gate is exercised over a real socket rather than a mock. The
    /// client half is returned for the test to answer on.
    fn pair() -> (SocketApprovals, TcpStream) {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind");
        let addr = listener.local_addr().expect("addr");
        let client = TcpStream::connect(addr).expect("connect");
        let (server, _) = listener.accept().expect("accept");
        let reader = BufReader::new(server.try_clone().expect("clone"));
        (SocketApprovals::new(server, reader), client)
    }

    fn answer(client: &mut TcpStream, line: &str) {
        client.write_all(line.as_bytes()).expect("write");
        client.write_all(b"\n").expect("newline");
        client.flush().expect("flush");
    }

    #[test]
    fn a_granted_decision_is_approved_and_the_prompt_names_the_blast_radius() {
        let (mut gate, mut client) = pair();
        answer(&mut client, r#"{"op":"approve","decision":1,"granted":true}"#);
        assert!(gate.await_approval(&radius()));

        // §B9: the prompt states the blast radius, not the command. Read it back off the wire —
        // asserting on a struct built in the test would prove nothing about what was sent.
        let mut sent = String::new();
        BufReader::new(client).read_line(&mut sent).expect("the prompt was written");
        assert!(sent.contains("example.com"), "the scope must reach the client: {sent}");
        assert!(sent.contains("\"decision\":1"), "the prompt must carry its id: {sent}");
    }

    #[test]
    fn a_declined_decision_is_denied() {
        let (mut gate, mut client) = pair();
        answer(&mut client, r#"{"op":"approve","decision":1,"granted":false}"#);
        assert!(!gate.await_approval(&radius()));
    }

    /// **Every failure is a denial**, and each of these is a separate way to fail. A gate that
    /// approved because it could not hear the answer would make §8.2's "the harness enforces"
    /// a statement about a code path that does not run.
    #[test]
    fn silence_a_malformed_reply_and_a_stale_decision_id_are_all_denials() {
        // Hung up without answering.
        let (mut gate, client) = pair();
        drop(client);
        assert!(!gate.await_approval(&radius()), "a client that hung up has not approved");

        // Answered with something that is not a decision.
        let (mut gate, mut client) = pair();
        answer(&mut client, "not json at all");
        assert!(!gate.await_approval(&radius()), "a malformed reply is not an approval");

        // Answered a DIFFERENT decision — the stale-prompt case. Without the id check this
        // would approve whatever happens to be pending now.
        let (mut gate, mut client) = pair();
        answer(&mut client, r#"{"op":"approve","decision":99,"granted":true}"#);
        assert!(
            !gate.await_approval(&radius()),
            "a reply naming another decision must not approve this one"
        );
    }

    /// Ids increment, so two prompts in one turn cannot be confused for each other.
    #[test]
    fn each_prompt_in_a_turn_gets_its_own_decision_id() {
        let (mut gate, mut client) = pair();
        answer(&mut client, r#"{"op":"approve","decision":1,"granted":true}"#);
        assert!(gate.await_approval(&radius()));
        // The second prompt is decision 2; answering it with 1 again must fail.
        answer(&mut client, r#"{"op":"approve","decision":1,"granted":true}"#);
        assert!(
            !gate.await_approval(&radius()),
            "re-sending the previous decision must not approve the next one"
        );
    }
}
