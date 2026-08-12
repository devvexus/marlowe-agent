//! The model call, and everything the loop needs from the world outside it.
//!
//! The loop is a state machine over injected ports. That is what makes "one loop, many
//! capability profiles" testable: a scripted driver and a real provider client are the same
//! shape, and consolidation is a profile rather than a second `while`.
//!
//! **No provider client lives here.** M2's later sessions add one; this file pins what it must
//! satisfy, including the part a provider client is most likely to get wrong —
//! [`CallLimits::max_output_tokens`] is a **hard cap that must be passed to the provider**, not
//! a hint the harness checks afterwards. See `budget`.

use marlowe_permission::{Args, BlastRadius};
use marlowe_tools::{ExposedSet, ResultSummary, ToolId};
use serde::{Deserialize, Serialize};

use crate::budget::{Budget, BudgetShare, CallLimits};
use crate::context::ContextView;
use crate::run::{CondensedResult, OrphanPolicy, OutputContract};
use crate::turn::TurnEvent;

/// What one model call cost. Folded into the run's `spent` immediately after the call.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct Usage {
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub micros_usd: u64,
    pub wall_ms: u64,
}

impl Usage {
    pub fn as_budget(&self) -> Budget {
        Budget {
            tokens: self.prompt_tokens.saturating_add(self.completion_tokens),
            wall_ms: self.wall_ms,
            tool_calls: 0,
            subagents: 0,
            depth: 0,
            micros_usd: self.micros_usd,
        }
    }
}

/// The model's request to write a belief.
///
/// **A request, not a write.** CONTRACTS §3.5 names the hazard: the model-visible tool is
/// called `remember`, which reads like a write, and it is not. This type is deliberately not
/// §3.5's `Claim` — it is what the *model* supplies, and the harness turns it into a `Claim`
/// after resolving derivation, computing effective trust, signing and appending. Naming them
/// the same type is how a bypass "for performance" gets written.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClaimRequest {
    pub text: String,
    pub payload_kind: String,
    pub derived_from: Vec<String>,
}

/// §10.1: ad-hoc spawning, no predeclared graph. Every field here is **declared at spawn**.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpawnRequest {
    /// A self-contained brief. The child gets a fresh window and does not know its siblings
    /// exist, so anything not in here is not available to it.
    pub task: String,
    pub contract: OutputContract,
    /// Declared, never inferred. Recorded and unused at M2; M3 is what makes it mean something.
    pub orphan: OrphanPolicy,
    pub share: BudgetShare,
    /// A **narrowing** of the parent's set. There is no widening path.
    pub tools: Vec<ToolId>,
    /// Sets the quarantined-reader profile, which forces the tool set empty. A spawn asking
    /// for both is a load-time error — see `profile`.
    pub reads_untrusted: bool,
}

/// One call inside a [`ModelStep::ToolCall`] batch.
///
/// **`id` is assigned by the HARNESS, never read from the model.** It is what a result is
/// attributed to: `/api/chat` carries `tool_calls[].id` on the assistant message and
/// `tool_call_id` on each result, and without it a batch of three calls to the same tool comes
/// back as three results the model cannot tell apart — which is the failure that makes a partial
/// batch failure unreadable. Taking the model's own id would let it collide two results
/// deliberately.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolInvocation {
    pub id: String,
    pub tool: ToolId,
    pub args: Args,
}

/// ARCHITECTURE §3's `match step`. Closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ModelStep {
    /// Prose for the user. Streams to the surface as `TurnEvent::TextDelta`.
    Say(String),
    /// One or more tool calls the model emitted **in a single message**.
    ///
    /// **No taint field.** Provenance is computed by the harness from the context view; a
    /// model that could label its own arguments would be the security boundary.
    ///
    /// # Why a batch is one step rather than several
    ///
    /// The model emitted every call in this vector **before seeing any of their results**. That is
    /// not an implementation detail — it is what makes computing taint **once for the batch**
    /// correct rather than a shortcut. No call here can have been shaped by another call's output,
    /// because none of that output existed when the model composed them.
    ///
    /// It also makes the batch the right unit for the latch: the results all enter the view
    /// together, the floor latches from the **worst** of them at the top of the next iteration, and
    /// the next batch is adjudicated against the lowered floor. See `Engine::tool_batch`.
    ToolCall { calls: Vec<ToolInvocation> },
    MemoryWrite(ClaimRequest),
    Spawn(SpawnRequest),
    /// Escalate with a decision package. The run does not hold a channel open.
    Ask(String),
}

impl ModelStep {
    /// The single-call case, which is most of them. Exists so a batch of one does not have to be
    /// spelled out at every construction site, and so there is **one** representation of a tool
    /// call rather than a scalar variant and a vector variant that drift.
    pub fn one_call(tool: ToolId, args: Args) -> Self {
        ModelStep::ToolCall {
            calls: vec![ToolInvocation { id: "call_1".to_string(), tool, args }],
        }
    }
}

// **There is no `Done` variant, and that is M2 C2e's correction.**
//
// A run used to end only when the model emitted `done`. Measured against the shipped model, that
// is not a contract a small model honours: `marlowe --ask "Hello marlowe"` produced **100 model
// calls** and stopped at the token budget, twice, by two different routes — once emitting `done`
// as plain prose that the adapter did not recognise, once never emitting it at all.
//
// **Completion is now the ABSENCE of an action.** A turn that produces prose and calls no tool is
// finished; that is what "the model answered you" means, and it needs nothing from the model
// except the answer it was already giving. `done` asked a 9B model to remember a control token in
// order for the loop to stop, and made forgetting it indistinguishable from working.
//
// `ask`, `remember` and `run` remain control steps: each *does* something beyond ending, so
// naming it is the only way to express it.

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{detail}")]
pub struct ProviderError {
    pub detail: String,
    /// Whether failover to another provider could plausibly help. A non-retriable error fails
    /// the run loudly rather than cycling through providers that will all refuse.
    pub retriable: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModelCall {
    pub usage: Usage,
    pub step: ModelStep,
}

/// The provider port.
pub trait ModelDriver {
    fn call(
        &mut self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
    ) -> Result<ModelCall, ProviderError>;

    /// The same call, handing each text chunk to `on_delta` **as it arrives**.
    ///
    /// # Why this is a second method with a default rather than a change to `call`
    ///
    /// `call` returns a completed `ModelCall`, so a provider that streams has nowhere to put the
    /// partial text — which is why M2's turns arrived as one block however well the transport
    /// streamed. Adding a parameter to `call` would break every implementation for the benefit of
    /// the one that can stream; a defaulted sibling breaks none, and a provider that cannot stream
    /// is *correct* to deliver its text once at the end.
    ///
    /// **The contract is that `on_delta` receives exactly the text that ends up in the returned
    /// `ModelStep::Say`, in order.** A caller that emits the deltas must therefore not also emit
    /// the finished string — see `engine.rs`, where doing both would double every reply.
    fn call_streaming(
        &mut self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
        _on_delta: &mut dyn FnMut(&str),
    ) -> Result<ModelCall, ProviderError> {
        self.call(view, tools, limits)
    }

    /// As [`Self::call_streaming`], but reasoning chunks go to `on_reasoning` and answer chunks to
    /// `on_delta`. A provider that does not distinguish them sends everything to `on_delta`.
    fn call_streaming_split(
        &mut self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
        on_delta: &mut dyn FnMut(&str),
        _on_reasoning: &mut dyn FnMut(&str),
        // Called when a `</think>` proves every chunk handed to `on_delta` this turn was
        // reasoning. See `marlowe_provider::ThinkSplitter`.
        _on_retract: &mut dyn FnMut(),
    ) -> Result<ModelCall, ProviderError> {
        self.call_streaming(view, tools, limits, on_delta)
    }

    /// Whether this driver actually streams. **Announced, not inferred**: the engine has to know
    /// whether the deltas it saw were the whole reply or nothing at all, and guessing from "did I
    /// receive any" would be wrong for an empty response.
    fn streams(&self) -> bool {
        false
    }

    /// Whether another provider can take this run. Returning `true` means run state is
    /// preserved across the switch — invariant 4's *degrade, never break*.
    fn failover(&mut self, _error: &ProviderError) -> bool {
        false
    }
}

/// The compaction summarizer. Separate from [`ModelDriver`] because ADR-008 routes it to the
/// cheapest model, and because the assembler must be able to compact without the run's own
/// provider being available.
pub trait Summarizer {
    fn summarize(&mut self, view: &ContextView) -> String;
}

/// What a tool execution produced. The loop never sees raw bytes above the tool's
/// `inline_threshold_bytes`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolOutcome {
    pub summary: ResultSummary,
    pub body: ToolBody,
    /// Origin-bound at capture, immutable. §2.8's second axis.
    pub trust: marlowe_contract::TrustClass,
    pub failed: bool,
    pub wall_ms: u64,
    /// Head and tail of a body too large to inline.
    ///
    /// **A reference the model cannot dereference is not a result.** `read` has no parameter that
    /// accepts a hash, so a 69 KB file came back as `ref 225bfe8df7bbc044` and the model called
    /// `read` five times getting the same hash. Until the content store and the reference-reading
    /// path land at M2 D, this is what actually reaches attention.
    ///
    /// `None` when the body was inlined whole — there is nothing to preview.
    pub preview: Option<String>,
}

/// §2.8's first axis: inline vs. reference, driven by **size**. Independent of trust.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolBody {
    Inline(String),
    /// Content-addressed. The bytes are in the content store; the loop holds the hash.
    Reference { hash: String, bytes: u64 },
}

/// One already-adjudicated call, handed to [`ToolHost::execute_batch`].
///
/// **Carrying the `Adjudication` is what makes this safe.** A host receives these only after the
/// permission layer has allowed each one individually; the batch is a scheduling unit, never a
/// permission unit. There is no path by which a host can execute something that was not
/// adjudicated on its own.
pub struct BatchItem<'a> {
    pub tool: &'a ToolId,
    pub args: &'a Args,
    pub adjudication: &'a marlowe_permission::Adjudication,
}

/// The execution port. Implementations land in Session C.
pub trait ToolHost {
    fn execute(
        &mut self,
        tool: &ToolId,
        args: &Args,
        adjudication: &marlowe_permission::Adjudication,
    ) -> ToolOutcome;

    /// Execute a whole adjudicated batch, **returning outcomes in input order**.
    ///
    /// # Why this exists, and why it is defaulted
    ///
    /// The model emits every call in a batch *before seeing any of their results* — see
    /// [`ModelStep::ToolCall`], where that is established as a correctness property rather than an
    /// observation. Calls in one batch therefore cannot have influenced one another, which is
    /// exactly the condition under which running them concurrently changes nothing about what
    /// they compute.
    ///
    /// The loop used to call [`ToolHost::execute`] in a `for` loop, so thirty `web` fetches cost
    /// thirty sequential round trips. Measured on the real `Engine`: an 8-call batch of 250 ms
    /// calls took **2008 ms with a maximum of 1 execution in flight**.
    ///
    /// **The default implementation is the old behaviour, exactly.** A host that does not override
    /// this is serial and correct, so no existing implementor changes meaning by the trait growing
    /// this method — and a host overrides it only when it can say something specific about which
    /// of *its* tools are safe to overlap. That judgement belongs to the host, which knows what
    /// its executors touch; it does not belong to the loop, which does not.
    ///
    /// # The contract an override must honour
    ///
    /// 1. **Return exactly `items.len()` outcomes, in input order.** The loop attributes results
    ///    to calls positionally.
    /// 2. **Never reorder observable side effects that could conflict.** Concurrency is a promise
    ///    the host makes about its own executors, not one the loop makes on its behalf.
    /// 3. **Never execute an item the loop did not hand over.** Every item here was adjudicated.
    fn execute_batch(&mut self, items: &[BatchItem<'_>]) -> Vec<ToolOutcome> {
        items
            .iter()
            .map(|i| self.execute(i.tool, i.args, i.adjudication))
            .collect()
    }

    /// Every tool this host has an executor for.
    ///
    /// **Required, with no default.** A default of "all" would restore exactly the situation this
    /// exists to make impossible, and a default of "none" would be a lie every host has to
    /// remember to correct. See [`crate::profile::UnrunnableTools`].
    fn executes(&self) -> Vec<ToolId>;
}

/// Tools that are **loop control**, not tool-host executions.
///
/// ARCHITECTURE §3's match handles these as `ModelStep` variants: they escalate, request a memory
/// write, and spawn a child. They are representable without the host having an executor, which is
/// why they are exempt from the check below.
pub const CONTROL_TOOLS: [&str; 3] = ["ask", "remember", "run"];

/// The memory port. Wired to `marlowe-memory` in Session D.
pub trait MemoryHost {
    /// Adjudicate, stamp, sign, append — or reject. There is no other write path.
    ///
    /// # `run_floor` is required, and passing it is the whole of ADR-038
    ///
    /// A model-authored claim is written at `min(AgentInferred, run_floor)`. `trust_for_channel`
    /// cannot answer this — it is total over `Channel` with no default arm, and a model is not a
    /// channel, correctly, because §3.3 binds trust to *origin* and the model is not an origin.
    ///
    /// **Bare `AgentInferred` is a laundering path and it is reachable today.** A run that fetches
    /// a page and then calls `remember` would write attacker-shaped text one full class above
    /// `UntrustedContent`, with the page's origin nowhere in the record, and that memory would then
    /// compete for rank 1 at injection on equal terms with everything else. `profile.rs`'s
    /// `reads_untrusted && may_write_memory` guard does not cover it: that closes the *quarantined
    /// reader*, and an ordinary `interactive()` run reads untrusted content and may write memory,
    /// both by design.
    ///
    /// **It is a parameter rather than something the implementation reaches for**, for the same
    /// reason `Provenance::taint_for` takes `latched` rather than deriving it: the run owns the
    /// latch, the latch is monotonic, and a host that re-derived the floor could derive a higher
    /// one. Writing a memory composes a *durable* target out of run content — the longest-lived
    /// composition the system performs — so this is the one place the latch must not be computed
    /// and then discarded.
    ///
    /// The implementation applies the `min`, not the caller: the trust computation belongs in the
    /// crate that owns §3.3, and a loop that handed down a finished class would be a second
    /// implementation of it.
    /// # `session` is required, and without it a written claim is unreachable
    ///
    /// Retrieval scopes candidates by `e.source_session_id == session_id`. A claim written with no
    /// session — or with a placeholder — is a belief that exists, is signed, is durable, and can
    /// **never be retrieved**. That failure is silent in exactly the wrong way: `remember` returns
    /// a receipt, the journal shows the write, and every later query behaves as though the memory
    /// were not there.
    ///
    /// Taken as a parameter rather than held on the host because one host serves every session.
    /// It mirrors `Recorder::append`, which takes run **and** session for the same reason.
    /// # `now_ms` comes from the run's clock, and a host must never read its own
    ///
    /// A belief's `created_at` and its maturation deadline are the same time base the run is
    /// journalled against. A memory host reading a system clock would put the write at a different
    /// instant from the `MemoryWritten` event recording it — two components disagreeing about now,
    /// in a log whose whole value is that it can be replayed. §4.5's rule is scoped to the §4.1/4.6
    /// paths; this is the same discipline applied where it is not strictly required, because the
    /// alternative is a second clock nobody declared.
    fn remember(
        &mut self,
        run: crate::run::RunId,
        session: crate::run::SessionId,
        claim: &ClaimRequest,
        run_floor: marlowe_contract::TrustClass,
        now_ms: i64,
    ) -> Result<String, String>;
}

/// The surface port. Render-only: §2.14, surfaces hold no policy.
pub trait TurnSink {
    fn emit(&mut self, event: TurnEvent);
}

impl TurnSink for () {
    fn emit(&mut self, _event: TurnEvent) {}
}

/// Approvals are **enforced by the harness, not requested by the model** (§8.2).
pub trait ApprovalGate {
    /// **Whether a human is actually there to ask.**
    ///
    /// Defaulted `false`, which is the safe direction: a gate that cannot ask says so.
    ///
    /// # Why the loop needs this and `await_approval`'s bool is not enough
    ///
    /// `false` from `await_approval` conflates two situations that call for opposite behaviour
    /// from the model:
    ///
    /// - **Nobody could be asked.** Retrying anything in this class will fail identically, so the
    ///   right move is to say the tool is unavailable and carry on without it.
    /// - **Somebody was asked and said no.** A human is present and can approve a *different*
    ///   call. Giving up on the whole capability is wrong.
    ///
    /// Observed live the first time the TUI window shipped: declined once, the model was handed
    /// *"no interactive approval surface is attached to this run"* — a false statement, since the
    /// surface was on screen — and refused to attempt anything further, citing a hard block. The
    /// message was written for the unattended case and reused for the attended one.
    fn is_interactive(&self) -> bool {
        false
    }

    /// Why the last refusal was refused, when the human gave a reason.
    ///
    /// **Defaulted, so no existing gate had to change.** A gate that cannot collect a reason
    /// returns `None` and the model is told only that it was declined — which is what every gate
    /// did before this existed.
    ///
    /// It is a second method rather than a richer return type because the alternative was
    /// rewriting every implementation and every test double to carry a field almost all of them
    /// would leave empty. The reason belongs to the *refusal*, and asking for it after the answer
    /// is the shape that matches.
    fn decline_reason(&self) -> Option<String> {
        None
    }

    fn await_approval(&mut self, radius: &BlastRadius) -> bool;
}

/// Steering and cancellation. §10.1's mid-flight steer, at iteration boundaries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SteerMessage {
    pub text: String,
    pub urgency: Urgency,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Urgency {
    /// Applies at the next iteration.
    Advisory,
    /// Also interrupts in-flight work.
    Immediate,
}

pub trait Control {
    fn cancelled(&self) -> bool {
        false
    }
    fn take_steer(&mut self) -> Option<SteerMessage> {
        None
    }
    /// A user cutting in mid-turn.
    fn take_interrupt(&mut self) -> Option<String> {
        None
    }
}

/// The default: nothing steers, nothing cancels, nothing interrupts. Used by children, which
/// at M2 are not independently addressable — that is M3.
#[derive(Debug, Default)]
pub struct NoControl;

impl Control for NoControl {}

/// The time base. §4.5's discipline applied outside §4: **never a system clock on a path a
/// test drives**, so a run at a fixed clock reproduces bit-identically.
pub trait ClockSource {
    fn now_ms(&mut self) -> i64;
}

/// A clock that advances by a fixed step on each read. Deterministic, and the one tests use.
#[derive(Debug, Clone)]
pub struct SteppingClock {
    now: i64,
    step: i64,
}

impl SteppingClock {
    pub fn new(start_ms: i64, step_ms: i64) -> Self {
        Self { now: start_ms, step: step_ms }
    }
}

impl ClockSource for SteppingClock {
    fn now_ms(&mut self) -> i64 {
        let now = self.now;
        self.now += self.step;
        now
    }
}
