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
    ApprovalGate, Budget, CapabilityProfile, Engine, GovernanceConstraint,
    JournalRecorder, LoopOutcome, MemoryRecorder, NoControl, OutputContract, Ports, Provenance,
    Run, RunId, SessionId, SessionState, Summarizer, ToolLineState, TurnEvent, TurnSink,
};
use marlowe_permission::scope::WorkspaceScope;
use marlowe_permission::{BlastRadius, Tier};
use marlowe_provider::{default_capability, Availability, LocalEndpoint, OllamaDriver, Routing};
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
}

pub struct DaemonConfig {
    pub profile_root: PathBuf,
    pub workspace: PathBuf,
    pub port: u16,
    pub model: String,
    /// ADR-029: the active rerank provider, **announced** rather than silently chosen. Read from
    /// the field the profile row stamps; this crate does not derive a second one.
    pub rerank_provider: String,
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

/// Collects turn events for one connection. Render-only.
#[derive(Default)]
struct Collector {
    events: Vec<Event>,
}

impl TurnSink for Collector {
    fn emit(&mut self, event: TurnEvent) {
        let e = match event {
            TurnEvent::TextDelta(t) => Event::Text { delta: t },
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
            TurnEvent::ApprovalPrompt(br) => Event::Approval {
                decision: 0,
                verb: br.verb,
                scope: br.scope,
                reversible: br.reversible,
            },
            TurnEvent::Done { spend_micros_usd, elapsed_ms, .. } => Event::Done {
                outcome: "completed".into(),
                detail: String::new(),
                spend_micros_usd,
                elapsed_ms,
            },
        };
        self.events.push(e);
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

pub struct Daemon {
    config: DaemonConfig,
    journal: Journal,
    runs: BTreeMap<String, RunSummary>,
    shutdown: Arc<AtomicBool>,
}

impl Daemon {
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

        Ok(Self { config, journal, runs: BTreeMap::new(), shutdown: Arc::new(AtomicBool::new(false)) })
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
        let degraded = match &routing {
            Err(e) => Some(e.to_string()),
            Ok(r) => {
                let a = Availability::probe(&endpoint, r);
                (!a.is_ready()).then(|| a.remedy())
            }
        };
        StatusReport {
            version: env!("CARGO_PKG_VERSION").to_string(),
            workspace: self.config.workspace.display().to_string(),
            model: self.config.model.clone(),
            model_disclosure: default_capability().disclosure(),
            degraded,
            rerank_provider: self.config.rerank_provider.clone(),
            live_runs: self.live_runs(),
        }
    }

    /// One turn, start to finish. The daemon owns the run for its whole life.
    pub fn ask(&mut self, session: &str, message: &str) -> Vec<Event> {
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
                return vec![Event::Error { detail: e.to_string() }];
            }
        };

        let availability = Availability::probe(&endpoint, &routing);
        if !availability.is_ready() {
            mark(&mut self.runs, "degraded", 0);
            // Invariant 4: a declared, actionable state — not a crash and not a silent stub.
            return vec![
                Event::Degraded {
                    what: "no model available".into(),
                    remedy: availability.remedy(),
                },
                Event::Done {
                    outcome: "degraded".into(),
                    detail: availability.remedy(),
                    spend_micros_usd: 0,
                    elapsed_ms: 0,
                },
            ];
        }

        let registry = match builtin_registry() {
            Ok(r) => r,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                return vec![Event::Error { detail: e.to_string() }];
            }
        };
        let scope = match WorkspaceScope::new() {
            Ok(s) => s,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                return vec![Event::Error { detail: e.to_string() }];
            }
        };
        let mut engine = Engine::new(
            registry,
            scope,
            32_000,
            2_000,
            self.config.workspace.clone(),
            Tier::Act,
        );

        let mut driver = OllamaDriver::new(
            endpoint,
            routing,
            builtin_registry().expect("the builtins loaded a moment ago"),
        )
        .with_capability(default_capability());
        let tool_scope = match WorkspaceScope::new() {
            Ok(s) => s,
            Err(e) => {
                mark(&mut self.runs, "failed", 0);
                return vec![Event::Error { detail: e.to_string() }];
            }
        };
        let mut tools = FileSystemTools::new(tool_scope, self.config.workspace.clone());
        let mut summarizer = PassthroughSummarizer;
        let mut approvals = DenyUnattended;
        let mut sink = Collector::default();
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
        let mut state = SessionState::new(session_id, identity_block());
        // §6: governance lives in the stable tier and is re-asserted structurally. The workspace
        // scope is a user-visible constraint, so it is stated to the model as one.
        state.assert_governance(GovernanceConstraint::asserted(&format!(
            "The workspace is {}. Every path you name is relative to it.",
            self.config.workspace.display()
        )));
        state.assert_governance(GovernanceConstraint::asserted(
            "Use a tool when the user asks for something a tool can do. Answer with `done` when \
             the task is complete.",
        ));

        let mut provenance = Provenance::new();
        provenance.attribute_user_message(message);
        state.push(marlowe_loop::Block::new(
            marlowe_loop::SourceKind::History,
            message,
            TrustClass::UserAsserted,
        ));

        let trace = run.trace_id;
        let mut recorder = JournalRecorder::new(&mut self.journal, trace);
        let outcome = {
            let mut ports = Ports {
                driver: &mut driver,
                summarizer: &mut summarizer,
                tools: &mut tools,
                memory: None,
                approvals: &mut approvals,
                sink: &mut sink,
                control: &mut control,
                clock: &mut clock,
                recorder: &mut recorder,
            };
            engine.run(&mut run, &mut state, &mut provenance, &mut ports)
        };

        let (status, detail) = match &outcome {
            LoopOutcome::Completed(r) => ("completed", r.render()),
            LoopOutcome::Paused { reason } => ("paused", format!("{reason:?}")),
            LoopOutcome::Escalated { question } => ("escalated", question.clone()),
            LoopOutcome::Cancelled => ("cancelled", String::new()),
            LoopOutcome::Failed { error } => ("failed", error.clone()),
        };
        mark(&mut self.runs, status, run.spent.tokens);

        let mut events = sink.events;
        events.retain(|e| !matches!(e, Event::Done { .. }));
        events.push(Event::Done {
            outcome: status.into(),
            detail,
            spend_micros_usd: run.spent.micros_usd,
            elapsed_ms: run.spent.wall_ms,
        });
        events
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

    fn handle(&mut self, request: Request) -> Vec<Event> {
        match request {
            Request::Status => vec![Event::Status(self.status())],
            Request::Ask { session, message } => self.ask(&session, &message),
            Request::Runs => self.runs(),
            // The gate is not wired to a surface yet; refusing is the honest answer rather than
            // recording an approval nobody gave.
            Request::Approve { .. } => vec![Event::Error {
                detail: "approvals need an attached surface; the daemon does not self-approve"
                    .into(),
            }],
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
        }
        Ok(())
    }

    fn serve_one(&mut self, stream: TcpStream) -> std::io::Result<()> {
        let mut writer = stream.try_clone()?;
        let mut reader = BufReader::new(stream);
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
        for event in self.handle(request) {
            crate::protocol::write_line(&mut writer, &event)?;
        }
        writer.flush()
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
const PERSONA: &str = include_str!("../../../persona/v1.md");

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
