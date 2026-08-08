//! ARCHITECTURE §3 — **the** agent loop.
//!
//! One loop. Research, voice, coding, automation, unattended triggers, quarantined reading and
//! consolidation are `CapabilityProfile` values over this function. There is no second driving
//! loop in this crate, and `tests/hp10_budgets.rs` fails the build if one appears.
//!
//! A subagent is this same function, re-entered. That is not a shortcut around a scheduler — it
//! is what "one loop" means when the parent blocks: the child runs the identical code with its
//! own `Run`, its own `SessionState`, and its own `Provenance`. M3 replaces the recursion with a
//! scheduler and the `Run` object is already shaped for it.
//!
//! # Reading the order of the hard stops
//!
//! Budget, then cancellation, then steering, then assembly, then the call. Every one of them is
//! **before any model spend**, and the budget check is first because it is the only one whose
//! failure mode is money.

use marlowe_contract::{Clock, TrustClass};
use marlowe_journal::EventKind;
use marlowe_permission::{
    Adjudicator, Args, BlockReason, EgressPolicy, Outcome, PathScope, Request, Tier,
};
use marlowe_tools::{ExposedSet, Metric, ResultSummary, ToolId, ToolRegistry};
use serde_json::json;
use std::path::PathBuf;

use crate::budget::Budget;
use crate::context::{
    Assembler, Block, PrefixCache, SessionState, SourceKind, COMPACTION_TRIGGER,
};
use crate::driver::{
    ApprovalGate, ClockSource, Control, MemoryHost, ModelDriver, ModelStep, SpawnRequest,
    Summarizer, ToolBody, ToolHost, TurnSink,
};
use crate::profile::{CapabilityProfile, InterruptPolicy, ModelRoute};
use crate::provenance::Provenance;
use crate::record::Recorder;
use crate::run::{
    CondensedResult, PauseReason, Run, RunId, RunStatus, SessionId,
};
use crate::turn::{ToolLineState, TurnEvent};

/// The structural bound on a non-converging run.
///
/// Failure paths table: *"Non-converging retry — bounded structurally by tool-call and step
/// caps, not by hoping."* The token budget bounds a run that spends; this bounds one that does
/// not, which is the case a scripted or misbehaving driver produces.
pub const MAX_STEPS: u32 = 400;

/// How many tool results survive observation masking. §6's cheaper lever.
pub const KEEP_TOOL_RESULTS: usize = 3;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopOutcome {
    Completed(CondensedResult),
    /// Hit a cap. **Pauses and asks** — never fails silently, never spends past the line.
    Paused { reason: PauseReason },
    /// `ask`. The run does not hold a channel open; it resumes on an answer.
    Escalated { question: String },
    Cancelled,
    Failed { error: String },
}

/// Everything outside the loop that the loop needs.
pub struct Ports<'a> {
    pub driver: &'a mut dyn ModelDriver,
    pub summarizer: &'a mut dyn Summarizer,
    pub tools: &'a mut dyn ToolHost,
    pub memory: Option<&'a mut dyn MemoryHost>,
    pub approvals: &'a mut dyn ApprovalGate,
    pub sink: &'a mut dyn TurnSink,
    pub control: &'a mut dyn Control,
    pub clock: &'a mut dyn ClockSource,
    pub recorder: &'a mut dyn Recorder,
}

pub struct Engine<S: PathScope> {
    registry: ToolRegistry,
    adjudicator: Adjudicator<S>,
    assembler: Assembler,
    cache: PrefixCache,
    workspace: PathBuf,
    /// From the trust ledger at M6; from the run's autonomy control at M2.
    tier: Tier,
    next_call_id: u64,
}

impl<S: PathScope> Engine<S> {
    pub fn new(
        registry: ToolRegistry,
        scope: S,
        window_tokens: u32,
        reserve_tokens: u32,
        workspace: PathBuf,
        tier: Tier,
    ) -> Self {
        Self {
            registry,
            adjudicator: Adjudicator::new(scope),
            assembler: Assembler::new(window_tokens, reserve_tokens),
            cache: PrefixCache::default(),
            workspace,
            tier,
            next_call_id: 1,
        }
    }

    pub fn assembler(&self) -> &Assembler {
        &self.assembler
    }

    pub fn cache(&self) -> &PrefixCache {
        &self.cache
    }

    /// The loop.
    pub fn run(
        &mut self,
        run: &mut Run,
        state: &mut SessionState,
        provenance: &mut Provenance,
        ports: &mut Ports<'_>,
    ) -> LoopOutcome {
        run.status = RunStatus::Running;
        let mut steps: u32 = 0;

        loop {
            // ── hard stops, checked before any model spend ───────────────────────────
            if let Some(dimension) = run.budget.exhausted(&run.spent) {
                return self.pause(run, state, ports, dimension.0);
            }
            if !run.budget.has_room_for_a_call(&run.spent) {
                // The floor. Issuing a call here spends the remainder on a step too small to
                // finish anything, which is "spending past the line" with the arithmetic
                // technically inside it.
                return self.pause(run, state, ports, "tokens");
            }
            steps += 1;
            if steps > MAX_STEPS {
                return self.pause(run, state, ports, "steps");
            }
            if ports.control.cancelled() {
                self.record(ports, EventKind::RunCancelled, run, state, json!({}));
                run.status = RunStatus::Cancelled;
                return LoopOutcome::Cancelled;
            }

            // ── mid-flight steering, no restart (§10.1) ──────────────────────────────
            if let Some(steer) = ports.control.take_steer() {
                self.record(
                    ports,
                    EventKind::SteerReceived,
                    run,
                    state,
                    json!({ "text": steer.text }),
                );
                // Steering is the user speaking, so it is user-asserted and it is attributed.
                provenance.attribute_user_message(&steer.text);
                state.push(Block::new(
                    SourceKind::History,
                    format!("[steer] {}", steer.text),
                    TrustClass::UserAsserted,
                ));
            }

            // ── assemble the view ────────────────────────────────────────────────────
            let view = self.assembler.assemble(state);

            // ── context pressure, before the call, never at exhaustion ───────────────
            if view.fill_pct >= COMPACTION_TRIGGER {
                // Append BEFORE discard — invariant 1, not negotiable and not concurrent.
                let summary = ports.summarizer.summarize(&view);
                self.record(
                    ports,
                    EventKind::SessionSummarized,
                    run,
                    state,
                    json!({ "chars": summary.len() }),
                );
                let child = SessionId::new();
                self.record(
                    ports,
                    EventKind::SessionSpawned,
                    run,
                    state,
                    json!({ "parent": state.session.to_string(), "child": child.to_string() }),
                );

                // Only now. The summary and the lineage are durable.
                self.assembler.compact(state, child, summary, &mut self.cache);
                run.session = state.session;
                ports.sink.emit(TurnEvent::Compacted { turns: state.compactions });

                // A compaction that leaves the window still over the trigger would spin here
                // forever, and a spin looks exactly like a hang. Checking the *result* rather
                // than comparing successive iterations is what makes this detect the real
                // condition: the non-volatile tiers alone no longer fit.
                let after = self.assembler.assemble(state);
                if after.fill_pct >= COMPACTION_TRIGGER {
                    return self.fail(
                        run,
                        state,
                        ports,
                        format!(
                            "compaction left context at {:.2} of the effective window, still at \
                             or above the {COMPACTION_TRIGGER} trigger; the stable and context \
                             tiers alone do not fit",
                            after.fill_pct
                        ),
                    );
                }
                continue;
            }
            if self.assembler.over_budget(state, SourceKind::ToolResults) {
                // The cheaper lever first (§6). `continue` only if it actually reclaimed
                // something — masking that changed nothing and looped would be a hang.
                if self.assembler.clear_tool_results(state, KEEP_TOOL_RESULTS) > 0 {
                    continue;
                }
                // Nothing left to mask. The per-source trimmer shapes the view instead, and
                // the run proceeds rather than stalling on pressure it cannot relieve.
            }

            // ── the model call, with failover ────────────────────────────────────────
            let limits = run.budget.call_limits(&run.spent);
            let call = match ports.driver.call(&view, run.profile.exposed_tools(), limits) {
                Ok(c) => c,
                Err(e) => {
                    if e.retriable && ports.driver.failover(&e) {
                        self.record(
                            ports,
                            EventKind::ProviderFailedOver,
                            run,
                            state,
                            json!({ "detail": e.detail }),
                        );
                        ports.sink.emit(TurnEvent::Degraded {
                            what: crate::turn::DegradedPath::ProviderFailedOver,
                        });
                        continue;
                    }
                    return self.fail(run, state, ports, e.detail);
                }
            };
            run.spent.add(&call.usage.as_budget());
            self.record(
                ports,
                EventKind::ModelStep,
                run,
                state,
                json!({ "tokens": call.usage.prompt_tokens + call.usage.completion_tokens }),
            );

            // ── interrupts: the user may cut in mid-turn ─────────────────────────────
            if run.profile.interrupt() == InterruptPolicy::Interruptible {
                if let Some(text) = ports.control.take_interrupt() {
                    self.record(ports, EventKind::Interrupted, run, state, json!({}));
                    provenance.attribute_user_message(&text);
                    state.push(Block::new(
                        SourceKind::History,
                        format!("[user, interrupting] {text}"),
                        TrustClass::UserAsserted,
                    ));
                    continue;
                }
            }

            match call.step {
                ModelStep::Say(text) => {
                    ports.sink.emit(TurnEvent::TextDelta(text.clone()));
                    state.push(Block::new(
                        SourceKind::History,
                        text,
                        TrustClass::AgentInferred,
                    ));
                }

                ModelStep::Done(result) => {
                    match run.output_contract.validate(&result) {
                        Ok(()) => {
                            self.record(
                                ports,
                                EventKind::RunCompleted,
                                run,
                                state,
                                json!({ "fields": result.fields.keys().collect::<Vec<_>>() }),
                            );
                            run.status = RunStatus::Completed;
                            ports.sink.emit(TurnEvent::Done {
                                spend_micros_usd: run.spent.micros_usd,
                                elapsed_ms: run.spent.wall_ms,
                                fill_pct: view.fill_pct,
                            });
                            return LoopOutcome::Completed(result);
                        }
                        Err(v) => {
                            // A contract violation is a tool error into context, not a crash:
                            // the child gets to try again inside its own budget.
                            state.push(Block::new(
                                SourceKind::History,
                                format!("[output contract] {v}"),
                                TrustClass::AgentObserved,
                            ));
                        }
                    }
                }

                ModelStep::Ask(question) => {
                    self.record(
                        ports,
                        EventKind::ApprovalRequested,
                        run,
                        state,
                        json!({ "question": question }),
                    );
                    run.status = RunStatus::Paused { reason: PauseReason::AwaitingAnswer };
                    return LoopOutcome::Escalated { question };
                }

                ModelStep::ToolCall { tool, args } => {
                    self.tool_call(run, state, provenance, ports, &view, tool, args);
                }

                ModelStep::MemoryWrite(claim) => {
                    if !run.profile.may_write_memory() {
                        state.push(Block::new(
                            SourceKind::History,
                            "[remember refused] this run's profile may not write memory",
                            TrustClass::AgentObserved,
                        ));
                    } else {
                        // `remember` is a REQUEST. The harness adjudicates, stamps and appends;
                        // there is no unsigned write path (invariant 2). The loop does not
                        // append a MemoryWritten event itself — that is the memory component's
                        // to emit, because it is the one that signs.
                        let outcome = match ports.memory.as_mut() {
                            Some(m) => m.remember(run.id, &claim),
                            None => Err("memory is not wired in this build".to_string()),
                        };
                        let (kind, text) = match &outcome {
                            Ok(receipt) => {
                                (EventKind::MemoryWritten, format!("[remembered] {receipt}"))
                            }
                            Err(why) => {
                                (EventKind::MemoryWriteRejected, format!("[not remembered] {why}"))
                            }
                        };
                        self.record(ports, kind, run, state, json!({ "text": text }));
                        state.push(Block::new(
                            SourceKind::History,
                            text,
                            TrustClass::AgentObserved,
                        ));
                    }
                }

                ModelStep::Spawn(req) => {
                    self.spawn(run, state, ports, req);
                }
            }

            // ── checkpoint every iteration: resume at the last completed step ────────
            let seq = self.record(ports, EventKind::Checkpointed, run, state, json!({ "step": steps }));
            run.last_checkpoint = seq;
        }
    }

    /// One adjudicated tool call.
    #[allow(clippy::too_many_arguments)]
    fn tool_call(
        &mut self,
        run: &mut Run,
        state: &mut SessionState,
        provenance: &Provenance,
        ports: &mut Ports<'_>,
        view: &crate::context::ContextView,
        tool: ToolId,
        args: Args,
    ) {
        let call_id = self.next_call_id;
        self.next_call_id += 1;

        self.record(
            ports,
            EventKind::ToolRequested,
            run,
            state,
            json!({ "tool": tool.as_str() }),
        );

        let Some(manifest) = self.registry.manifest(&tool) else {
            // Not registered. Blocked here rather than at execution, so the reason reads as
            // "no such tool" and not as a fault in a tool that does not exist.
            self.tool_error(state, &tool, "no such tool is registered");
            return;
        };
        let manifest = manifest.clone();

        // Provenance is computed HERE, by the harness, from the view the model actually saw.
        let taint = provenance.taint_for(&args, view);

        let adjudication = self.adjudicator.adjudicate(Request {
            manifest: &manifest,
            args: &args,
            taint: &taint,
            exposed: run.profile.exposed_tools(),
            egress: run.profile.egress(),
            workspace: &self.workspace,
            tier: self.tier,
            novelty: None,
        });
        self.record(
            ports,
            EventKind::PermissionDecided,
            run,
            state,
            serde_json::to_value(&adjudication.decision).unwrap_or(json!({})),
        );

        match &adjudication.decision.outcome {
            Outcome::Blocked { reason } => {
                if let BlockReason::EgressNotAllowed { host } = reason {
                    self.record(
                        ports,
                        EventKind::EgressBlocked,
                        run,
                        state,
                        json!({ "host": host }),
                    );
                }
                let why = format!("{reason:?}");
                self.tool_error(state, &tool, &why);
                return;
            }
            Outcome::NeedsApproval { .. } => {
                self.record(
                    ports,
                    EventKind::ApprovalRequested,
                    run,
                    state,
                    json!({ "tool": tool.as_str() }),
                );
                ports
                    .sink
                    .emit(TurnEvent::ApprovalPrompt(adjudication.decision.blast_radius.clone()));
                if !ports.approvals.await_approval(&adjudication.decision.blast_radius) {
                    self.record(ports, EventKind::ApprovalDenied, run, state, json!({}));
                    // The loop continues; it does not retry around a refusal.
                    self.tool_error(state, &tool, "declined");
                    return;
                }
                self.record(ports, EventKind::ApprovalGranted, run, state, json!({}));
            }
            Outcome::Allowed | Outcome::AllowedBatched { .. } => {}
        }

        ports.sink.emit(TurnEvent::ToolLine {
            id: call_id,
            verb: tool.to_string(),
            target: adjudication.decision.blast_radius.scope.clone(),
            state: ToolLineState::Running { elapsed_ms: 0 },
        });

        let outcome = ports.tools.execute(&tool, &args, &adjudication);
        run.spent.add(&Budget { tool_calls: 1, wall_ms: outcome.wall_ms, ..Budget::default() });

        self.record(
            ports,
            if outcome.failed { EventKind::ToolFailed } else { EventKind::ToolCompleted },
            run,
            state,
            json!({ "tool": tool.as_str(), "summary": outcome.summary.render() }),
        );
        ports.sink.emit(TurnEvent::ToolLine {
            id: call_id,
            verb: tool.to_string(),
            target: adjudication.decision.blast_radius.scope.clone(),
            state: if outcome.failed {
                ToolLineState::Failed(outcome.summary.clone())
            } else {
                ToolLineState::Ok(outcome.summary.clone())
            },
        });

        // §2.8's two axes, kept independent: SIZE decides inline vs reference, ORIGIN decides
        // the trust class. A workspace read can inline *and* carry untrusted_content.
        let text = match &outcome.body {
            ToolBody::Inline(s) => format!("{} · {}", outcome.summary.render(), s),
            ToolBody::Reference { hash, bytes } => {
                format!("{} · ref {hash} ({bytes} B)", outcome.summary.render())
            }
        };
        state.push(Block::new(SourceKind::ToolResults, text, outcome.trust));
    }

    /// §10.1's ad-hoc spawn. **The parent blocks; the child returns findings.**
    fn spawn(
        &mut self,
        run: &mut Run,
        state: &mut SessionState,
        ports: &mut Ports<'_>,
        req: SpawnRequest,
    ) {
        // Depth and subagent count are declared caps, checked before anything is created.
        let Some(child_budget) = run.budget.slice_for(&run.spent, req.share) else {
            self.tool_error(state, &ToolId::new("run"), "depth budget exhausted");
            return;
        };
        if run.spent.subagents >= run.budget.subagents {
            self.tool_error(state, &ToolId::new("run"), "subagent budget exhausted");
            return;
        }

        // A narrowing, never a widening.
        for t in &req.tools {
            if !run.profile.exposed_tools().contains(t) {
                self.tool_error(
                    state,
                    &ToolId::new("run"),
                    &format!("`{t}` is not available to this run and cannot be given to a child"),
                );
                return;
            }
        }

        // The load-time error. A quarantined reader with tools is refused here, and the invalid
        // profile is never constructed — the requested tool set is not silently dropped.
        let child_profile = match CapabilityProfile::new(
            match ExposedSet::new(req.tools.clone()) {
                Ok(s) => s,
                Err(e) => {
                    self.tool_error(state, &ToolId::new("run"), &e.to_string());
                    return;
                }
            },
            if req.reads_untrusted { EgressPolicy::DenyAll } else { run.profile.egress().clone() },
            InterruptPolicy::Unattended,
            ModelRoute::Worker,
            !req.reads_untrusted && run.profile.may_write_memory(),
            req.reads_untrusted,
        ) {
            Ok(p) => p,
            Err(e) => {
                self.tool_error(state, &ToolId::new("run"), &e.to_string());
                return;
            }
        };

        let child_id = RunId::new();
        let mut child_run = Run {
            id: child_id,
            parent: Some(run.id),
            session: SessionId::new(),
            trace_id: run.trace_id, // one trace across the tree — invariant 7's replay key
            status: RunStatus::Queued,
            profile: child_profile,
            budget: child_budget,
            spent: Budget::default(),
            // Declared at spawn, never inferred. Recorded and unused at M2.
            orphan_policy: req.orphan,
            output_contract: req.contract.clone(),
            last_checkpoint: None,
        };
        self.record(
            ports,
            EventKind::RunSpawned,
            run,
            state,
            json!({
                "child": child_id.to_string(),
                "orphan_policy": req.orphan,
                "budget_tokens": child_budget.tokens,
                "depth": child_budget.depth,
                "reads_untrusted": req.reads_untrusted,
            }),
        );

        // A fresh context window and a self-contained brief. The child does not know its
        // siblings exist, because nothing about them is in here.
        let mut child_state = SessionState::new(child_run.session, state.identity.clone());
        // Governance is inherited: a child must not be a way out of the parent's constraints.
        for c in &state.governance {
            child_state.assert_governance(c.clone());
        }
        child_state.push(Block::new(
            SourceKind::History,
            format!("{}\n\nReturn: {}", req.task, req.contract.description),
            TrustClass::AgentInferred,
        ));
        // A fresh tracker. The child does not inherit the parent's attributions, so a string
        // the *user* typed to the parent is not user-asserted inside a child that never saw it.
        let mut child_provenance = Provenance::new();

        let outcome = self.run(&mut child_run, &mut child_state, &mut child_provenance, ports);

        // The child's spend is the parent's spend. A budget that did not roll up would let a
        // tree cost arbitrarily more than the root declared.
        run.spent.add(&child_run.spent);
        run.spent.add(&Budget { subagents: 1, ..Budget::default() });

        let note = match outcome {
            LoopOutcome::Completed(result) => match req.contract.validate(&result) {
                Ok(()) => result.render(),
                Err(v) => format!("[child returned an invalid result] {v}"),
            },
            LoopOutcome::Paused { reason } => format!("[child paused] {reason:?}"),
            LoopOutcome::Escalated { question } => format!("[child asked] {question}"),
            LoopOutcome::Cancelled => "[child cancelled]".to_string(),
            LoopOutcome::Failed { error } => format!("[child failed] {error}"),
        };

        // **This is the only thing that crosses back.** `child_state` — the child's transcript,
        // its tool results, everything it read — is dropped at the end of this function. There
        // is no accessor that would hand it to the parent, which is what makes §10.2's "the
        // orchestrator's context must never accumulate raw worker history" structural.
        state.push(Block::new(SourceKind::ChildResults, note, TrustClass::AgentInferred));
    }

    fn tool_error(&mut self, state: &mut SessionState, tool: &ToolId, why: &str) {
        state.push(Block::new(
            SourceKind::ToolResults,
            format!("[{tool} blocked] {why}"),
            // The harness computed this, so it is agent-observed. A blocked-call notice that
            // inherited the call's own taint would be unreadable by the very next step.
            TrustClass::AgentObserved,
        ));
    }

    fn pause(
        &mut self,
        run: &mut Run,
        state: &mut SessionState,
        ports: &mut Ports<'_>,
        dimension: &str,
    ) -> LoopOutcome {
        let reason = PauseReason::BudgetExhausted { dimension: dimension.to_string() };
        self.record(
            ports,
            EventKind::RunPaused,
            run,
            state,
            json!({ "dimension": dimension, "spent_tokens": run.spent.tokens }),
        );
        // §A7: never fail silently. The decision package is the pause reason plus what it cost.
        ports.sink.emit(TurnEvent::Done {
            spend_micros_usd: run.spent.micros_usd,
            elapsed_ms: run.spent.wall_ms,
            fill_pct: 0.0,
        });
        run.status = RunStatus::Paused { reason: reason.clone() };
        LoopOutcome::Paused { reason }
    }

    fn fail(
        &mut self,
        run: &mut Run,
        state: &mut SessionState,
        ports: &mut Ports<'_>,
        error: String,
    ) -> LoopOutcome {
        self.record(ports, EventKind::RunFailed, run, state, json!({ "error": error }));
        run.status = RunStatus::Failed { error: error.clone() };
        LoopOutcome::Failed { error }
    }

    fn record(
        &mut self,
        ports: &mut Ports<'_>,
        kind: EventKind,
        run: &Run,
        state: &SessionState,
        payload: serde_json::Value,
    ) -> Option<u64> {
        let clock = Clock::new(ports.clock.now_ms());
        match ports.recorder.append(clock, kind, run.id, state.session, payload) {
            Ok(seq) => Some(seq),
            Err(e) => {
                // A failed append is not survivable in silence: the audit trail is invariant 7
                // and a run that continued past a dropped event would be unreconstructable.
                // It is surfaced rather than swallowed; the loop's own failure path handles it
                // on the next iteration through `RunFailed`.
                ports.sink.emit(TurnEvent::TextDelta(format!("[journal] append failed: {e}")));
                None
            }
        }
    }
}

/// The §8 one-line summary for a call the harness refused. `done` is not acceptable, so a
/// refusal reports what it was.
pub fn blocked_summary(why: &str) -> ResultSummary {
    ResultSummary::with_detail(vec![Metric::State("blocked")], why)
}
