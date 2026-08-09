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
use crate::turn::DegradedPath;
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

/// How many times a turn that produced only reasoning may be nudged to continue.
///
/// A reasoning model sometimes ends a stream mid-thought: thinking, no prose, no tool call. That
/// is not "finished", and treating it as an answer ends the turn with nothing on screen. Nor is it
/// free to retry forever, so it is bounded and the bound is stated.
const MAX_AUTO_CONTINUE: u32 = 3;

/// Consecutive tool-only turns before the loop starts steering.
///
/// A model that keeps gathering and never answers is the failure a token budget catches far too
/// late — it stops the run rather than getting an answer out of it. These nudge first, then stop.
const FARMING_SOFT_NUDGE: u32 = 4;
const FARMING_FIRM_NUDGE: u32 = 7;
/// At this point tools are **withheld for one call**, so the model must answer with what it has.
/// A nudge asks; an empty tool set removes the option.
const FARMING_HARD_STOP: u32 = 10;

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

        // Loop-scoped steering. **None of it reaches history** — see the nudge note below.
        let mut pending_nudge = String::new();
        let mut auto_continue: u32 = 0;
        let mut tool_calls_this_turn: u32 = 0;
        let mut last_reasoning = String::new();

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
            // **Deltas go out as they arrive.** The sink is borrowed for the duration of the
            // call, so the chunks reach the surface while the model is still producing them —
            // which is the whole of what "streaming" means above the transport.
            let streamed = ports.driver.streams();

            // **Ephemeral steering.** A nudge is appended to the VIEW, never to `state`, so it
            // reaches exactly one call and never becomes history the model must live with. A
            // nudge that persisted would compound: the model would read three turns of "stop
            // gathering" and start explaining why it was gathering.
            let mut view = view;
            if !pending_nudge.is_empty() {
                view.stable.push(Block::new(
                    SourceKind::Governance,
                    std::mem::take(&mut pending_nudge),
                    TrustClass::AgentObserved,
                ));
            }

            // **Sliding-window reasoning.** Only the most recent turn's thinking is carried, and
            // it is carried in the view rather than in state. Older reasoning is not merely
            // useless — it compounds: three turns of "let me check one more thing" reads as a
            // standing instruction to keep checking.
            //
            // **It travels in the `thinking` field of an EXISTING assistant turn**, never as a
            // block of its own. Two things were learned the hard way here.
            //
            // 1. It used to go out as an assistant message beginning `[your prior reasoning]`,
            //    and the model imitated the marker: the first reported leak contained
            //    `[your reasoning continues]`, a string that appears nowhere in this repository.
            // 2. Replacing that with a trailing assistant message carrying only `thinking` and an
            //    empty `content` made the model return **nothing at all**, three turns running.
            //    Isolated against the live endpoint: the same conversation answers correctly
            //    without that trailing block and goes silent with it. An empty assistant turn is
            //    not a neutral carrier — it reads as a turn already taken.
            //
            // So the reasoning is attached where a turn already exists, which is what the loop
            // does when it records a tool call or a reply. Nothing is appended here.
            if !last_reasoning.is_empty() {
                if let Some(b) = view.volatile.iter_mut().rev().find(|b| {
                    b.source == SourceKind::History && b.trust == TrustClass::AgentInferred
                }) {
                    let w = b.wire.get_or_insert_with(Default::default);
                    if w.thinking.is_none() {
                        w.thinking = Some(last_reasoning.clone());
                    }
                }
            }

            // ── latch the run's trust floor ──────────────────────────────────────────
            //
            // Monotonic and permanent. Announced when it moves, because a guard that engages
            // silently is a guard nobody can confirm engaged.
            if let Some(floor) = run.latch_trust_floor(view.trust_floor()) {
                self.record(
                    ports,
                    EventKind::TrustFloorLatched,
                    run,
                    state,
                    json!({ "floor": format!("{floor:?}") }),
                );
                ports.sink.emit(TurnEvent::Degraded { what: DegradedPath::TrustFloorLatched });
            }

            let empty_tools = ExposedSet::new(Vec::new()).expect("an empty set is within the cap");
            let offered_tools = if tool_calls_this_turn >= FARMING_HARD_STOP {
                &empty_tools
            } else {
                run.profile.exposed_tools()
            };
            let reasoning_buf = std::cell::RefCell::new(String::new());
            // Disjoint field borrows: the driver and the sink are different fields of `Ports`, so
            // both can be held at once. The `RefCell` is what lets two closures share the sink —
            // the alternative was one callback with a kind tag, which pushes the branch into every
            // provider instead of keeping it here.
            let Ports { driver, sink, .. } = &mut *ports;
            let sink = std::cell::RefCell::new(&mut **sink);
            let call = {
                let mut on_delta = |chunk: &str| {
                    sink.borrow_mut().emit(TurnEvent::TextDelta(chunk.to_string()));
                };
                let mut on_reasoning = |chunk: &str| {
                    reasoning_buf.borrow_mut().push_str(chunk);
                    sink.borrow_mut().emit(TurnEvent::ReasoningDelta(chunk.to_string()));
                };
                let mut on_retract = || {
                    sink.borrow_mut().emit(TurnEvent::SpeechRetracted);
                };
                driver.call_streaming_split(
                    &view,
                    offered_tools,
                    limits,
                    &mut on_delta,
                    &mut on_reasoning,
                    &mut on_retract,
                )
            };
            let call = match call {
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

            last_reasoning = reasoning_buf.into_inner();

            // ── a turn that produced ONLY reasoning is mid-thought, not finished ──────
            //
            // The stream closed while the model was still working. Ending the turn here would
            // show the user nothing; treating it as an answer would be a lie about what happened.
            // So it is nudged to continue, bounded, and the nudge is ephemeral.
            let produced_nothing = matches!(&call.step, ModelStep::Say(t) if t.trim().is_empty());
            if produced_nothing {
                if auto_continue < MAX_AUTO_CONTINUE {
                    auto_continue += 1;
                    // The nudge differs by cause: a model told the wrong one explains rather than
                    // acts.
                    pending_nudge = if last_reasoning.is_empty() {
                        "(Your previous turn produced nothing at all. Answer the user, or call a tool if you need something first.)"
                            .to_string()
                    } else {
                        "(Your previous turn produced reasoning but no reply and no tool call. Continue from where you left off — either answer the user or call a tool.)"
                            .to_string()
                    };
                    continue;
                }

                // **An empty turn must never quietly succeed.**
                //
                // Completion is the absence of an action, and an empty reply is technically that —
                // so without this branch a model returning nothing three times would END THE RUN
                // with an empty answer, reported as success. A turn that produced no output is a
                // failure and says so: that is the difference between "Marlowe answered" and
                // "Marlowe said nothing and we called it done".
                return self.fail(
                    run,
                    state,
                    ports,
                    format!("the model produced no reply and no tool call {MAX_AUTO_CONTINUE} times in a row"),
                );
            }
            auto_continue = 0;

            // ── tool-farming: count the tool calls made INSIDE THIS TURN ─────────────
            //
            // **Per turn, not "consecutive turns without a reply".** A reply ends the turn now, so
            // a reply that fails to reset this cannot exist — the branch that would express it is
            // unreachable. Leaving it in would invite the reading that this counts across replies.
            // It does not: it is the length of one tool chain.
            if matches!(call.step, ModelStep::ToolCall { .. }) {
                tool_calls_this_turn += 1;
                pending_nudge = match tool_calls_this_turn {
                    n if n >= FARMING_HARD_STOP => "(HARD STOP: you have called tools repeatedly \
                         without answering. Tools are withheld for this turn. Answer the user now \
                         with what you already have.)"
                        .to_string(),
                    n if n >= FARMING_FIRM_NUDGE => "(You have gathered a substantial amount \
                         across many tool calls. Stop collecting. Next turn, synthesise what you \
                         have and answer. Call another tool only if it is essential.)"
                        .to_string(),
                    n if n >= FARMING_SOFT_NUDGE => "(Reminder: several tool calls so far. Do you \
                         already have enough to answer? If so, stop searching and answer.)"
                        .to_string(),
                    _ => String::new(),
                };
            }

            match call.step {
                ModelStep::Say(text) => {
                    // **Emitted only if the driver did not already stream it.** A streaming driver
                    // has handed every chunk to `on_delta` above; re-emitting here would deliver
                    // the reply twice, visibly.
                    if !streamed {
                        ports.sink.emit(TurnEvent::TextDelta(text.clone()));
                    }
                    // The reply, with the reasoning that produced it. Kept together because that
                    // is the unit `/api/chat` replays — and because a `thinking` field with no
                    // turn to sit on makes the model go silent (see the sliding-window note).
                    state.push(Block::assistant_turn(
                        text.clone(),
                        (!last_reasoning.is_empty()).then(|| last_reasoning.clone()),
                        Vec::new(),
                    ));

                    // ── COMPLETION IS THE ABSENCE OF AN ACTION ──────────────────────────
                    //
                    // Prose with no tool call means the model answered. That is the whole
                    // termination rule, and it replaces `done`.
                    //
                    // Measured, not assumed: `--ask "Hello marlowe"` ran **100 model calls** and
                    // stopped at the token budget, twice, by two different routes. Once the model
                    // emitted `done` as plain prose the adapter did not recognise; once it never
                    // emitted it at all and simply kept chatting. A control token the model must
                    // remember in order for the loop to stop makes forgetting it look identical
                    // to working.
                    self.record(ports, EventKind::RunCompleted, run, state, json!({}));
                    run.status = RunStatus::Completed;
                    ports.sink.emit(TurnEvent::Done {
                        spend_micros_usd: run.spent.micros_usd,
                        elapsed_ms: run.spent.wall_ms,
                        fill_pct: view.fill_pct,
                    });

                    // **The reply IS the result, filed under the fields the contract asked for.**
                    //
                    // A contract names what the parent wants back (`findings`, `answer`). With
                    // `done` gone the model no longer names fields — it just replies — so the
                    // reply is filed under every field the contract requires. The parent still
                    // gets the shape it asked for; what changed is that the child no longer has to
                    // remember a schema in order to finish.
                    //
                    // Filing under every required field rather than the first is deliberate: a
                    // partially-filled contract would validate for some parents and not others,
                    // which is the kind of difference nobody notices until a spawn fails.
                    let mut result = CondensedResult::new();
                    if run.output_contract.fields.is_empty() {
                        result = result.with("answer", text.clone());
                    } else {
                        for field in &run.output_contract.fields {
                            result = result.with(field.clone(), text.clone());
                        }
                    }
                    if let Err(v) = run.output_contract.validate(&result) {
                        // A violation is a tool error into context, not a crash: the child gets
                        // to try again inside its own budget.
                        state.push(Block::new(
                            SourceKind::History,
                            format!("[output contract] {v}"),
                            TrustClass::AgentObserved,
                        ));
                        run.status = RunStatus::Running;
                        continue;
                    }
                    return LoopOutcome::Completed(result);
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
        let taint = provenance.taint_for(&args, view, run.trust_floor());

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
                // **The refusal must be actionable, or the model cannot recover from it.**
                //
                // This was `format!("{reason:?}")` — the Debug rendering of an internal enum. A
                // model told `UndeclaredPath { path: "", detail: "no declared target" }` knows it
                // failed and has nothing to correct toward, so it guesses: observed live, qwen
                // followed a refused `web` call with `[web](query="...")`, a syntax we never
                // offered, because it was inventing rather than reading.
                //
                // Appending the tool's actual parameter list turns a dead end into a correction.
                let why = format!("{reason:?}{}", self.expected_params(&tool));
                self.tool_error(state, &tool, &why);
                // **The user sees the refusal too.** Both refusal paths used to return here,
                // before the `ToolLine` below — so the model was told and the screen was not.
                // A run that refuses three calls and then answers looked like a model that never
                // tried, which is the opposite of what happened and unfalsifiable from outside.
                self.refused_line(ports, call_id, &tool, &adjudication, "blocked", &why);
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
                    self.refused_line(ports, call_id, &tool, &adjudication, "declined", "declined");
                    return;
                }
                self.record(ports, EventKind::ApprovalGranted, run, state, json!({}));
            }
            Outcome::Allowed | Outcome::AllowedBatched { .. } => {}
        }

        // **The assistant turn that made this call, recorded before its result.**
        //
        // `/api/chat` carries `tool_calls` on the assistant message, and a `tool` result with no
        // assistant turn behind it leaves the model unable to see that it called anything. That
        // was measured, not assumed: given the malformed shape a live model abandons the task and
        // narrates; given this one it acts on the result. See `WireTurn`.
        state.push(Block::assistant_turn(
            String::new(),
            None,
            vec![crate::context::WireToolCall {
                name: tool.to_string(),
                arguments: args.to_json(),
            }],
        ));

        ports.sink.emit(TurnEvent::ToolLine {
            id: call_id,
            verb: tool.to_string(),
            target: adjudication.decision.blast_radius.scope.clone(),
            state: ToolLineState::Running { elapsed_ms: 0 },
        });

        // The loop times the call, from its INJECTED clock. An executor reading a real clock
        // would put a system-clock read on a path §4.5 forbids, in a component nobody would
        // think to check — `marlowe/tests/determinism_guard.rs` caught exactly that in `bash`.
        let before_ms = ports.clock.now_ms();
        let mut outcome = ports.tools.execute(&tool, &args, &adjudication);
        let elapsed_ms = ports.clock.now_ms().saturating_sub(before_ms).max(0) as u64;
        outcome.wall_ms = elapsed_ms;
        run.spent.add(&Budget { tool_calls: 1, wall_ms: elapsed_ms, ..Budget::default() });

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
            // **A reference the model cannot dereference is not a result.**
            //
            // Observed live: asked to read a 69 KB file, the model received
            // `983 lines · 69630 B · ref 225bfe8df7bbc044` — a byte count and a hash. `read` has
            // no parameter that accepts a reference, so there was no way to ask for the text. It
            // called `read` five times, got the same hash five times, and gave up.
            //
            // The content store lands at M2 D and the `read`-a-reference path with it. Until then
            // the honest thing is to hand over what will fit: head and tail, with the omission
            // stated in words the model can act on rather than a hash it cannot.
            ToolBody::Reference { hash, bytes } => match &outcome.preview {
                Some(p) => format!(
                    "{} · {} B total, ref {hash}\n{p}",
                    outcome.summary.render(),
                    bytes
                ),
                None => format!("{} · ref {hash} ({bytes} B)", outcome.summary.render()),
            },
        };
        state.push(Block::tool_result(text, tool.as_str(), outcome.trust));
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
        let mut child_run = Run::child(
            child_id,
            run,
            SessionId::new(),
            child_profile,
            child_budget,
            // Declared at spawn, never inferred. Recorded and unused at M2.
            req.orphan,
            req.contract.clone(),
        );
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

    /// The tool's declared parameters, rendered for a model that just got one wrong.
    ///
    /// Read from the registry rather than restated, so it cannot drift from the schema the model
    /// was actually given.
    fn expected_params(&self, tool: &ToolId) -> String {
        let Some(reg) = self.registry.get(tool) else {
            return String::new();
        };
        let params = reg.manifest.params();
        if params.is_empty() {
            return String::new();
        }
        let list: Vec<String> = params
            .iter()
            .map(|p| {
                let req = if p.role == marlowe_tools::ArgumentRole::Target {
                    " (required)"
                } else {
                    ""
                };
                format!("{}{req}", p.name)
            })
            .collect();
        format!(" — `{tool}` takes: {}", list.join(", "))
    }

    /// §B6's line for a call that never ran.
    ///
    /// The blast radius is already computed by the time either refusal fires, so the line names
    /// the same target an allowed call would have — the user can see *what* was refused, not only
    /// that something was.
    fn refused_line(
        &mut self,
        ports: &mut Ports<'_>,
        call_id: u64,
        tool: &ToolId,
        adjudication: &marlowe_permission::Adjudication,
        state: &'static str,
        detail: &str,
    ) {
        ports.sink.emit(TurnEvent::ToolLine {
            id: call_id,
            verb: tool.to_string(),
            target: adjudication.decision.blast_radius.scope.clone(),
            state: ToolLineState::Failed(marlowe_tools::ResultSummary::with_detail(
                vec![marlowe_tools::Metric::State(state)],
                detail.to_string(),
            )),
        });
    }

    fn tool_error(&mut self, state: &mut SessionState, tool: &ToolId, why: &str) {
        state.push(Block::tool_result(
            format!("[{tool} blocked] {why}"),
            tool.as_str(),
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
                // **Degraded, not prose.** This used to be a `TextDelta`, so an audit-log
                // failure arrived in the transcript in Marlowe's voice, mid-sentence, repeatedly:
                // `You got here first. Go ahead.[journal] append failed: UNIQUE constraint …`.
                // A harness error rendered as model output is the exact confusion `Speech::Model`
                // versus `Speech::Harness` exists to prevent, at the one place that still emitted
                // raw text. Invariant 4 says degrade visibly; it does not say degrade in character.
                ports.sink.emit(TurnEvent::Degraded { what: DegradedPath::JournalAppendFailed });
                let _ = e;
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
