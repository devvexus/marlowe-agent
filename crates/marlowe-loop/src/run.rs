//! CONTRACTS.md §5 — runs as first-class objects.
//!
//! **M2 ships ephemeral spawning: the parent blocks, the child returns, the child dies with the
//! parent.** M3 makes the lifecycle durable — children outliving parents, mid-flight steering,
//! checkpoint resume. The `Run` object and `OrphanPolicy` are implemented **in full now**, and
//! `OrphanPolicy` is *recorded and unused*, because that is what lets M3 extend this rather
//! than replace it. A field added at M3 is a migration; a field recorded from the first spawn
//! is a lifecycle that was always declared.
//!
//! # Children return findings, not transcripts
//!
//! §10.1: *"Each worker gets a self-contained task description, an output contract, and a fresh
//! context window, and does not know the others exist."* §10.2: *"Subagents return findings, not
//! transcripts. The orchestrator's context must never accumulate raw worker history."*
//!
//! Two things enforce it here, and neither is a length check on prose:
//!
//! 1. The loop's spawn returns a [`CondensedResult`] — a map of the fields the parent asked
//!    for. The child's `Checkpoint`, its transcript, and its tool results are owned by the
//!    child's own state and are dropped when it returns. There is no accessor that hands a
//!    parent a child's history, so "never accumulates" is a property of the call signature.
//! 2. [`OutputContract::validate`] rejects an unnamed field and a body over the cap. A child
//!    that tried to return its transcript under a field the parent did not ask for is refused,
//!    and one that tried to stuff it into a named field hits `max_chars`.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::budget::{Budget, Dimension};
use crate::profile::CapabilityProfile;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct RunId(pub Uuid);

impl RunId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }

    /// Deterministic ids for tests and for replay. A run id in the journal that changed between
    /// two identical runs would break the bit-identity claim the standing `repro` check rests
    /// on, so the deterministic constructor is the one tests use.
    pub fn from_name(name: &str) -> Self {
        Self(Uuid::new_v5(&Uuid::NAMESPACE_OID, name.as_bytes()))
    }
}

impl Default for RunId {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for RunId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct SessionId(pub Uuid);

impl SessionId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
    pub fn from_name(name: &str) -> Self {
        Self(Uuid::new_v5(&Uuid::NAMESPACE_OID, name.as_bytes()))
    }
}

impl Default for SessionId {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for SessionId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// CONTRACTS.md §5. **Declared at spawn, NEVER inferred.**
///
/// At M2 this is recorded and unused: the parent blocks on the child, so no child can be
/// orphaned. Recording it is not ceremony — it is the difference between M3 extending this
/// design and M3 replacing it, and the value is already in the journal when M3 arrives.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OrphanPolicy {
    /// Reparent to another run when the parent ends.
    Adopt { by: RunId },
    /// Keep running with no parent.
    Detach,
    /// End with the parent.
    Terminate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PauseReason {
    BudgetExhausted { dimension: String },
    AwaitingApproval,
    AwaitingAnswer,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    Queued,
    Running,
    WaitingApproval { decision: marlowe_permission::DecisionId },
    WaitingEvent { until: Option<i64> },
    Paused { reason: PauseReason },
    Completed,
    Failed { error: String },
    Cancelled,
}

/// What a child must return, declared by the parent at spawn.
///
/// `max_chars` is a **hard** cap and not a hint. §10.2's failure mode is an orchestrator whose
/// context fills with worker history; a cap the child could talk its way past would be a
/// convention, and conventions are what the parent's context accumulates.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OutputContract {
    /// One line naming what the parent wants. Rendered into the child's brief.
    pub description: String,
    /// The fields the child must fill. Nothing else is accepted.
    pub fields: Vec<String>,
    pub max_chars: usize,
}

/// A sane default for a worker return: enough for findings, far short of a transcript.
pub const DEFAULT_RESULT_MAX_CHARS: usize = 4_000;

impl OutputContract {
    pub fn new(description: impl Into<String>, fields: &[&str]) -> Self {
        Self {
            description: description.into(),
            fields: fields.iter().map(|f| (*f).to_string()).collect(),
            max_chars: DEFAULT_RESULT_MAX_CHARS,
        }
    }

    /// The contract a top-level interactive run finishes against.
    pub fn answer() -> Self {
        Self::new("answer the user's request", &["answer"])
    }

    pub fn validate(&self, result: &CondensedResult) -> Result<(), ContractViolation> {
        for name in result.fields.keys() {
            if !self.fields.iter().any(|f| f == name) {
                return Err(ContractViolation::UnknownField { field: name.clone() });
            }
        }
        for name in &self.fields {
            if !result.fields.contains_key(name) {
                return Err(ContractViolation::MissingField { field: name.clone() });
            }
        }
        let total: usize = result.fields.values().map(String::len).sum();
        if total > self.max_chars {
            return Err(ContractViolation::TooLong { chars: total, max: self.max_chars });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ContractViolation {
    #[error("the output contract does not name a field `{field}`")]
    UnknownField { field: String },
    #[error("the output contract requires a field `{field}` and the result has none")]
    MissingField { field: String },
    #[error(
        "a result of {chars} characters exceeds the contract's {max}. A parent's context must \
         never accumulate a child's raw history (§10.2), and this cap is what makes that \
         structural rather than hoped for"
    )]
    TooLong { chars: usize, max: usize },
}

/// What a child hands back. **Fields only** — there is no transcript field and there must never
/// be one.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CondensedResult {
    pub fields: BTreeMap<String, String>,
}

impl CondensedResult {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with(mut self, field: impl Into<String>, value: impl Into<String>) -> Self {
        self.fields.insert(field.into(), value.into());
        self
    }

    pub fn get(&self, field: &str) -> Option<&str> {
        self.fields.get(field).map(String::as_str)
    }

    /// How this result renders into the parent's context. One block, not a conversation.
    pub fn render(&self) -> String {
        self.fields
            .iter()
            .map(|(k, v)| format!("{k}: {v}"))
            .collect::<Vec<_>>()
            .join("\n")
    }
}

/// CONTRACTS.md §5.
#[derive(Debug, Clone)]
pub struct Run {
    pub id: RunId,
    pub parent: Option<RunId>,
    pub session: SessionId,
    pub trace_id: Uuid,
    pub status: RunStatus,
    pub profile: CapabilityProfile,
    pub budget: Budget,
    pub spent: Budget,
    /// Declared at spawn, never inferred. Recorded and unused at M2.
    pub orphan_policy: OrphanPolicy,
    pub output_contract: OutputContract,
    pub last_checkpoint: Option<u64>,
}

impl Run {
    pub fn root(
        id: RunId,
        session: SessionId,
        profile: CapabilityProfile,
        budget: Budget,
        output_contract: OutputContract,
    ) -> Self {
        Self {
            id,
            parent: None,
            session,
            trace_id: Uuid::new_v5(&Uuid::NAMESPACE_OID, id.to_string().as_bytes()),
            status: RunStatus::Queued,
            profile,
            budget,
            spent: Budget::default(),
            // A root run has no parent to be orphaned from. `Terminate` rather than `Detach`
            // so that the value is never mistaken for a request to survive its starter.
            orphan_policy: OrphanPolicy::Terminate,
            output_contract,
            last_checkpoint: None,
        }
    }

    /// The budget dimension that has run out, if any.
    pub fn exhausted(&self) -> Option<Dimension> {
        self.budget.exhausted(&self.spent)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_contract_refuses_a_field_it_did_not_name() {
        let c = OutputContract::new("summarise", &["summary"]);
        let smuggled = CondensedResult::new()
            .with("summary", "ok")
            .with("transcript", "...the entire conversation...");
        assert_eq!(
            c.validate(&smuggled),
            Err(ContractViolation::UnknownField { field: "transcript".into() })
        );
    }

    #[test]
    fn a_contract_refuses_a_transcript_stuffed_into_a_named_field() {
        // The other half: naming the field correctly does not buy unbounded length.
        let c = OutputContract { max_chars: 100, ..OutputContract::new("s", &["summary"]) };
        let fat = CondensedResult::new().with("summary", "x".repeat(101));
        assert!(matches!(c.validate(&fat), Err(ContractViolation::TooLong { .. })));
    }

    #[test]
    fn a_missing_field_is_a_violation_not_an_empty_string() {
        let c = OutputContract::new("s", &["summary", "confidence"]);
        let partial = CondensedResult::new().with("summary", "ok");
        assert_eq!(
            c.validate(&partial),
            Err(ContractViolation::MissingField { field: "confidence".into() })
        );
    }

    #[test]
    fn condensed_result_has_no_transcript_field() {
        // Executable documentation. The type is a map with a validating contract in front of
        // it; if someone adds `pub transcript: String`, the contract stops being the only way
        // in and this test is what has to be argued past.
        let json = serde_json::to_string(&CondensedResult::new().with("answer", "42")).unwrap();
        assert_eq!(json, r#"{"fields":{"answer":"42"}}"#);
    }

    #[test]
    fn run_ids_are_reproducible_when_named() {
        assert_eq!(RunId::from_name("root"), RunId::from_name("root"));
        assert_ne!(RunId::from_name("root"), RunId::from_name("child"));
    }
}
