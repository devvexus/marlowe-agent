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
            TurnEvent::ApprovalPrompt(br) => Event::Approval {
                decision: 0,
                verb: br.verb,
                scope: br.scope,
                reversible: br.reversible,
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

pub struct Daemon {
    config: DaemonConfig,
    journal: Journal,
    runs: BTreeMap<String, RunSummary>,
    /// Keyed by the client's session name — the same key `SessionId::from_name` derives from.
    sessions: BTreeMap<String, SessionMemory>,
    shutdown: Arc<AtomicBool>,
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

        // **Refuse to start rather than offer a tool that cannot run.** A daemon that starts and
        // then fails every `web` call presents as a broken model; this names the tool instead.
        // Checked here, before a port is bound or a journal is opened, because it is a statement
        // about the build and not about this machine.
        {
            let scope = WorkspaceScope::new().map_err(|e| DaemonError::Scope { detail: e.to_string() })?;
            let host = FileSystemTools::new(scope, config.workspace.clone());
            marlowe_loop::verify_every_exposed_tool_is_runnable(
                CapabilityProfile::interactive().exposed_tools(),
                &host,
            )?;
        }

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

        Ok(Self {
            config,
            journal,
            runs: BTreeMap::new(),
            sessions: BTreeMap::new(),
            shutdown: Arc::new(AtomicBool::new(false)),
        })
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
        // **Announced, loudly, and ahead of everything else.** A daemon serving stale code
        // produces symptoms that look like bugs in whatever was just changed, and the reflex is to
        // debug the change. Invariant 4's rule applies: degrade visibly, and name the remedy.
        let degraded = crate::staleness::stale_against_source().or(degraded);
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
        .with_capability(default_capability())
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
        let mut tools = FileSystemTools::new(tool_scope, self.config.workspace.clone());
        let mut summarizer = PassthroughSummarizer;
        let mut approvals = DenyUnattended;
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
    fn handle(&mut self, request: Request, mut on_event: impl FnMut(Event)) {
        match request {
            Request::Status => on_event(Event::Status(self.status())),
            Request::Ask { session, message } => {
                self.ask_streaming(&session, &message, on_event)
            }
            Request::Runs => {
                for e in self.runs() {
                    on_event(e);
                }
            }
            // The gate is not wired to a surface yet; refusing is the honest answer rather than
            // recording an approval nobody gave.
            Request::Approve { .. } => on_event(Event::Error {
                detail: "approvals need an attached surface; the daemon does not self-approve"
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
        // **Write and flush per event.** `write_line` already flushes — §4.0.2's rule that a
        // response sitting in a buffer is indistinguishable from a hang, which is exactly what the
        // whole turn used to be.
        //
        // A write failure means the client hung up. It cannot be propagated out of the callback,
        // so it is captured and returned after the turn: aborting mid-turn would leave the run
        // half-recorded, and the daemon owns the run whether or not anyone is listening
        // (invariant 6).
        let mut write_err: Option<std::io::Error> = None;
        self.handle(request, |event| {
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

/// How the loop's termination rule is stated to the model.
///
/// **Public so it can be asserted on.** It said *"Answer with `done` when the task is complete"*
/// for as long as `done` had not existed, and nothing could see it — the loop was right, the
/// provider was right, and a prompt is just a string until something reads it. It is a function
/// rather than a literal so `the_system_prompt_names_no_tool_that_does_not_exist` has a subject.
pub fn governance_prompt() -> &'static str {
    "Use a tool when the user asks for something a tool can do. You may call tools while      reasoning. When the task is complete, reply to the user in prose and call no tool — that is      what ends the turn."
}
