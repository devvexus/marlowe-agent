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

/// ARCHITECTURE §3's `match step`. Closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ModelStep {
    /// Prose for the user. Streams to the surface as `TurnEvent::TextDelta`.
    Say(String),
    /// **No taint field.** Provenance is computed by the harness from the context view; a
    /// model that could label its own arguments would be the security boundary.
    ToolCall { tool: ToolId, args: Args },
    MemoryWrite(ClaimRequest),
    Spawn(SpawnRequest),
    /// Escalate with a decision package. The run does not hold a channel open.
    Ask(String),
    /// Finish against the run's output contract.
    Done(CondensedResult),
}

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
}

/// §2.8's first axis: inline vs. reference, driven by **size**. Independent of trust.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolBody {
    Inline(String),
    /// Content-addressed. The bytes are in the content store; the loop holds the hash.
    Reference { hash: String, bytes: u64 },
}

/// The execution port. Implementations land in Session C.
pub trait ToolHost {
    fn execute(
        &mut self,
        tool: &ToolId,
        args: &Args,
        adjudication: &marlowe_permission::Adjudication,
    ) -> ToolOutcome;
}

/// The memory port. Wired to `marlowe-memory` in Session D.
pub trait MemoryHost {
    /// Adjudicate, stamp, sign, append — or reject. There is no other write path.
    fn remember(&mut self, run: crate::run::RunId, claim: &ClaimRequest) -> Result<String, String>;
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
