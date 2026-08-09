//! Scripted ports for driving the one loop in a test.
//!
//! The driver is a **queue**, and that is sound rather than lucky: at M2 a spawn blocks the
//! parent, so parent and child steps interleave in exactly one order. When M3 makes runs
//! concurrent this file needs a per-run script, and the fact that it does is a useful signal
//! that the lifecycle actually changed.

#![allow(dead_code)]

use std::collections::VecDeque;

use marlowe_contract::TrustClass;
use marlowe_loop::{
    ApprovalGate, ClaimRequest, ClockSource, ContextView, MemoryHost, ModelCall, ModelDriver,
    ModelStep, ProviderError, RunId, Summarizer, ToolBody, ToolHost, ToolOutcome, TurnEvent,
    TurnSink, Usage,
};
use marlowe_permission::{Adjudication, Args, BlastRadius};
use marlowe_tools::{ExposedSet, Metric, ResultSummary, ToolId};

/// A model that says what it was told to say, and records what it was allowed to return.
pub struct ScriptDriver {
    pub steps: VecDeque<ModelCall>,
    /// Every `max_output_tokens` the loop handed over, in order. This is the evidence that the
    /// cap is derived from what remains rather than being a constant.
    pub limits_seen: Vec<u64>,
    /// The rendered view for each call, so a test can assert on what the model could see.
    pub views_seen: Vec<String>,
    pub failover_ok: bool,
}

impl ScriptDriver {
    pub fn new(steps: Vec<ModelCall>) -> Self {
        Self {
            steps: steps.into(),
            limits_seen: Vec::new(),
            views_seen: Vec::new(),
            failover_ok: false,
        }
    }
}

impl ModelDriver for ScriptDriver {
    fn call(
        &mut self,
        view: &ContextView,
        _tools: &ExposedSet,
        limits: marlowe_loop::CallLimits,
    ) -> Result<ModelCall, ProviderError> {
        self.limits_seen.push(limits.max_output_tokens);
        self.views_seen.push(view.rendered());
        match self.steps.pop_front() {
            Some(c) => Ok(c),
            None => Err(ProviderError {
                detail: "the script ran out of steps".into(),
                retriable: false,
            }),
        }
    }

    fn failover(&mut self, _error: &ProviderError) -> bool {
        self.failover_ok
    }
}

pub fn say(text: &str, tokens: u64) -> ModelCall {
    ModelCall {
        usage: Usage { completion_tokens: tokens, ..Usage::default() },
        step: ModelStep::Say(text.into()),
    }
}

pub fn step(step: ModelStep, tokens: u64) -> ModelCall {
    ModelCall { usage: Usage { completion_tokens: tokens, ..Usage::default() }, step }
}

/// A summarizer that returns **nothing**.
///
/// Deliberately hostile. A cooperative summarizer would let a test pass against an
/// implementation that merely asked the model to preserve governance constraints.
#[derive(Default)]
pub struct EmptySummarizer;

impl Summarizer for EmptySummarizer {
    fn summarize(&mut self, _view: &ContextView) -> String {
        String::new()
    }
}

/// A summarizer that returns a short marker, for tests that need to see the seam.
pub struct MarkerSummarizer(pub String);

impl Summarizer for MarkerSummarizer {
    fn summarize(&mut self, _view: &ContextView) -> String {
        self.0.clone()
    }
}

#[derive(Default)]
pub struct ScriptedTools {
    pub calls: Vec<(String, Args)>,
    pub body: Option<String>,
    pub trust: Option<TrustClass>,
}

impl ToolHost for ScriptedTools {
    /// A scripted host answers for whatever it was scripted with, plus the builtins tests drive.
    fn executes(&self) -> Vec<marlowe_tools::ToolId> {
        marlowe_tools::BUILTIN_TOOLS.iter().map(|t| marlowe_tools::ToolId::new(*t)).collect()
    }

    fn execute(&mut self, tool: &ToolId, args: &Args, _a: &Adjudication) -> ToolOutcome {
        self.calls.push((tool.to_string(), args.clone()));
        ToolOutcome {
            summary: ResultSummary::new(vec![Metric::State("ok")]),
            body: ToolBody::Inline(self.body.clone().unwrap_or_else(|| "ok".into())),
            trust: self.trust.unwrap_or(TrustClass::AgentObserved),
            failed: false,
            wall_ms: 1,
        }
    }
}

pub struct FixedApprovals(pub bool);

impl ApprovalGate for FixedApprovals {
    fn await_approval(&mut self, _radius: &BlastRadius) -> bool {
        self.0
    }
}

#[derive(Default)]
pub struct CollectingSink {
    pub events: Vec<TurnEvent>,
}

impl CollectingSink {
    /// Everything the surface was told, concatenated. Used to prove a child *did* say the thing
    /// a parent's context must not contain — without it, an assertion that the marker is absent
    /// from the parent would pass vacuously if the child never produced it.
    pub fn text(&self) -> String {
        self.events
            .iter()
            .filter_map(|e| match e {
                TurnEvent::TextDelta(t) => Some(t.clone()),
                _ => None,
            })
            .collect::<Vec<_>>()
            .join("\n")
    }
}

impl TurnSink for CollectingSink {
    fn emit(&mut self, event: TurnEvent) {
        self.events.push(event);
    }
}

#[derive(Default)]
pub struct RecordingMemory {
    pub claims: Vec<ClaimRequest>,
}

impl MemoryHost for RecordingMemory {
    fn remember(&mut self, _run: RunId, claim: &ClaimRequest) -> Result<String, String> {
        self.claims.push(claim.clone());
        Ok(format!("m-{}", self.claims.len()))
    }
}

/// A clock that never moves, so wall-clock never becomes the dimension a budget test trips on
/// by accident.
pub struct FrozenClock(pub i64);

impl ClockSource for FrozenClock {
    fn now_ms(&mut self) -> i64 {
        self.0
    }
}

/// A tool call that carries no meaning beyond "keep going and add bulk to history".
///
/// **Why tests that grow context use this rather than `say`.** M2 C2e made completion the absence
/// of an action: a reply with no tool call ends the turn. That is the product's termination rule,
/// so a test that grew context with five consecutive `say` steps was exercising a loop that no
/// longer exists — it would now end on the first one.
///
/// A multi-step turn in the real product is a sequence of tool calls followed by one reply, and
/// that is what these helpers build. The bulk arrives as tool *results*, which is also where bulk
/// actually comes from.
pub fn work(tokens: u64) -> ModelCall {
    step(
        ModelStep::ToolCall {
            tool: marlowe_tools::ToolId::new("read"),
            args: marlowe_permission::Args::new()
                .with("path", marlowe_permission::ArgValue::Text("./notes.md".into())),
        },
        tokens,
    )
}
