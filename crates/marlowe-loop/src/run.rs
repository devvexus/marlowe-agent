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
use marlowe_contract::TrustClass;
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
    pub fields: Vec<FieldSpec>,
    /// The aggregate cap, across all fields. Per-field caps are on [`FieldSpec`].
    pub max_chars: usize,
}

/// What one field may contain. **A shape, not just a name.**
///
/// # Why the type exists at all
///
/// The contract is the single place where content crosses from `UntrustedContent` to
/// `AgentInferred` — `Engine::spawn` pushes a validated child result into the parent at the
/// trusted class, by declaration rather than by lineage. That crossing is the whole of §8.2's
/// trifecta break, and `validate` is the only thing standing in it.
///
/// Before this type, `validate` checked that the right field *names* were present and that the
/// total length was under a cap. **It constrained no value.** A child talked into emitting the
/// attacker's text filled the declared field with it, passed validation, and the text arrived in
/// the parent's window one trust class above where it started, with the page's origin nowhere in
/// the record. Names and a size limit are not a boundary; they are a boundary's label.
///
/// The bandwidth is still not zero and this file will not pretend otherwise — a summary of a page
/// is attacker-influenced prose no matter how it is typed. What the constraints buy is that the
/// prose is **bounded, sanitized, and structurally unable to forge the record it arrives in**, and
/// that §5.6 then governs the rest: it may inform analysis, and layer 3 still refuses to let it
/// choose a target.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FieldSpec {
    pub name: String,
    pub ty: FieldType,
    /// Per-field cap, in characters. Separate from the contract's aggregate cap because one
    /// oversized field and twenty small ones are different failures.
    pub max_chars: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldType {
    /// Prose that may run to several lines. Newlines and tabs are permitted; every other
    /// control character is not.
    Text,
    /// Prose on exactly one line. Reach for this whenever the field is a label, a verdict or a
    /// name — a value that cannot contain a newline cannot contribute a line to the rendered
    /// block at all.
    Line,
}

/// A default generous enough for a page summary and far short of a page.
pub const DEFAULT_FIELD_MAX_CHARS: usize = 2_000;

impl FieldSpec {
    pub fn text(name: impl Into<String>) -> Self {
        Self { name: name.into(), ty: FieldType::Text, max_chars: DEFAULT_FIELD_MAX_CHARS }
    }

    pub fn line(name: impl Into<String>) -> Self {
        Self { name: name.into(), ty: FieldType::Line, max_chars: 200 }
    }

    pub fn capped(mut self, max_chars: usize) -> Self {
        self.max_chars = max_chars;
        self
    }

    /// **The value check.** Length, then character class, in that order so an enormous hostile
    /// value is refused before it is scanned.
    ///
    /// The character rule is an allowlist by exclusion: every C0 control is refused except the
    /// two that carry meaning in prose, plus `DEL` and the C1 block. That is not tidiness —
    /// `ESC` is `U+001B`, so refusing C0 is what stops a fetched page writing ANSI escape
    /// sequences through a child, through a parent, and onto a terminal. Nothing else in this
    /// path would catch it: the journal stores bytes faithfully and the renderer prints what it
    /// is given.
    pub fn validate_value(&self, value: &str) -> Result<(), ContractViolation> {
        let chars = value.chars().count();
        if chars > self.max_chars {
            return Err(ContractViolation::FieldTooLong {
                field: self.name.clone(),
                chars,
                max: self.max_chars,
            });
        }
        for c in value.chars() {
            let permitted = match c {
                '\n' | '\t' => self.ty == FieldType::Text,
                _ => is_renderable(c),
            };
            if !permitted {
                return Err(ContractViolation::DisallowedCharacter {
                    field: self.name.clone(),
                    codepoint: c as u32,
                });
            }
        }
        Ok(())
    }
}

/// Whether a character may appear in a contract value.
///
/// **Moved to `marlowe_contract::text` on 2026-08-17 and re-exported here**, because it had
/// exactly one caller — [`FieldSpec::validate_value`], twenty lines above — and the three render
/// sites that needed it most were not among them. The §B9 approval prompt printed the model's
/// composed `bash` command unfiltered as a direct result. It lives in the deepest crate in the
/// workspace so that the value check and every render site read **one** definition; the reasoning
/// and the audit history are in that module's header.
///
/// This re-export is kept so existing callers and `condense_integrity.rs` do not move.
pub use marlowe_contract::text::is_renderable;

/// A sane default for a worker return: enough for findings, far short of a transcript.
pub const DEFAULT_RESULT_MAX_CHARS: usize = 4_000;

impl OutputContract {
    /// Text fields at the default cap. The shape every existing caller wants.
    pub fn new(description: impl Into<String>, fields: &[&str]) -> Self {
        Self {
            description: description.into(),
            fields: fields.iter().map(|f| FieldSpec::text(*f)).collect(),
            max_chars: DEFAULT_RESULT_MAX_CHARS,
        }
    }

    /// A contract whose fields are typed and capped individually.
    /// **The aggregate is derived from the per-field caps, not fixed.** Audit findings C3 and E8.
    ///
    /// It was a flat [`DEFAULT_RESULT_MAX_CHARS`] — 4,000 — while the quarantined reader's own
    /// contract declares `about`(600) plus six `source_N`(1,500), which is **9,600**. So the
    /// contract asked for more than it would accept: at six sources the aggregate capped the whole
    /// reply at roughly 571 characters per field, and no correct answer existed.
    ///
    /// That is not merely a tight budget, it is E8's engine. A violation does not fail the child —
    /// it is pushed into the child's window and the loop `continue`s — so the child retried an
    /// arithmetically unsatisfiable instruction until `MAX_STEPS` or its token slice was gone, and
    /// the parent absorbed the whole retry loop through `run.spent.add(&child_run.spent)`. A page
    /// inducing a verbose summary burned up to a quarter of the parent's budget per group and
    /// returned nothing for all six documents.
    ///
    /// The sum plus a small allowance for the field headers themselves is the honest number: a
    /// contract's aggregate should be *satisfiable by filling every field it declares*.
    pub fn structured(description: impl Into<String>, fields: Vec<FieldSpec>) -> Self {
        let per_field: usize = fields.iter().map(|f| f.max_chars).sum();
        // `saturating_add` because `answer()` declares `usize::MAX`; a contract mixing that with
        // anything else must not wrap to a cap of nearly zero.
        let headroom = fields.len().saturating_mul(64);
        let max_chars = per_field.saturating_add(headroom).max(DEFAULT_RESULT_MAX_CHARS);
        Self { description: description.into(), fields, max_chars }
    }

    /// The contract a top-level interactive run finishes against.
    ///
    /// **`max_chars` is `usize::MAX` and that is deliberate.** A root run's "child result" is the
    /// answer to the user, which is not crossing a trust boundary and is not being condensed into
    /// anybody's window — it IS the window. Capping it here would truncate ordinary replies to a
    /// person, which is a product defect wearing a security cap. The bound that matters applies to
    /// results crossing INTO a parent, and every such contract is constructed with a real cap.
    pub fn answer() -> Self {
        Self {
            description: "answer the user's request".into(),
            fields: vec![FieldSpec {
                name: "answer".into(),
                ty: FieldType::Text,
                max_chars: usize::MAX,
            }],
            max_chars: usize::MAX,
        }
    }

    pub fn field_names(&self) -> impl Iterator<Item = &str> {
        self.fields.iter().map(|f| f.name.as_str())
    }

    /// Names, then **values**, then the aggregate.
    ///
    /// The middle step is the one that did not exist. See [`FieldSpec`] for why its absence made
    /// the `AgentInferred` crossing in `Engine::spawn` unsound.
    pub fn validate(&self, result: &CondensedResult) -> Result<(), ContractViolation> {
        for name in result.fields.keys() {
            if !self.fields.iter().any(|f| &f.name == name) {
                return Err(ContractViolation::UnknownField { field: name.clone() });
            }
        }
        for spec in &self.fields {
            let Some(value) = result.fields.get(&spec.name) else {
                return Err(ContractViolation::MissingField { field: spec.name.clone() });
            };
            spec.validate_value(value)?;
        }
        // `chars().count()`, not `len()`. The per-field caps count characters, and an aggregate
        // counted in bytes would disagree with them on any non-ASCII page — the two limits would
        // then mean different things while reading as one policy.
        let total: usize = result.fields.values().map(|v| v.chars().count()).sum();
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
    #[error("field `{field}` is {chars} characters and the contract caps it at {max}")]
    FieldTooLong { field: String, chars: usize, max: usize },
    #[error(
        "field `{field}` contains the control character U+{codepoint:04X}, which a returned value \
         may not carry. ESC (U+001B) is the one that matters: a fetched page must not be able to \
         write terminal escape sequences through a child and onto a screen"
    )]
    DisallowedCharacter { field: String, codepoint: u32 },
}

// **Every variant names a field or a number and none of them interpolates a VALUE.** A violation
// message is written into the parent's context, so a message quoting the offending text would be
// the laundering path the validation exists to close — refused content arriving anyway, inside
// the error that refused it.

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
    ///
    /// # A value may not forge a field
    ///
    /// This used to be `format!("{k}: {v}")` joined by newlines, and the parent only ever sees the
    /// flattened string — so a value containing `"\nanswer: …"` produced a line indistinguishable
    /// from a real field header. Field *names* were whitelisted by `validate`; the rendered
    /// representation was not, which put the check and the thing it protects on opposite sides of
    /// a format string.
    ///
    /// The fix is structural rather than a matter of escaping: **a field header is the only thing
    /// that starts at column 0, and every line contributed by a value is indented.** A value line
    /// reading `answer: x` renders as `  answer: x` and cannot be read back as a header, whatever
    /// it contains. `FieldType::Line` values cannot contribute a second line at all.
    pub fn render(&self) -> String {
        let mut out = String::new();
        for (k, v) in self.fields.iter() {
            out.push_str(k);
            out.push_str(":\n");
            for line in v.lines() {
                out.push_str("  ");
                out.push_str(line);
                out.push('\n');
            }
        }
        out.trim_end().to_string()
    }

    /// Read a child's prose reply back into the fields its contract asked for.
    ///
    /// # Why this exists at all
    ///
    /// Audit findings C3 and E2. A child finishes by *speaking*, and the loop used to file that one
    /// reply under **every** declared field — so a six-source contract came back with six identical
    /// slots, and §5.1's *"the parent attributes findings by slot"* had nothing to attribute. A
    /// hostile page's prose was printed verbatim under a trusted document's label with nothing
    /// forged. The suite missed it because the scripted reply is 29 characters and the test asserts
    /// the labels are *present*, not that the slots *differ*.
    ///
    /// The child is already instructed to *"fill one field per source, using the labels exactly as
    /// given"*, so parsing labelled output back is the protocol; the absence of a parser was the
    /// gap.
    ///
    /// # The three rules, each of which is a defence
    ///
    /// 1. **A header is a declared field name, at column 0, followed by `:`.** Nothing else opens a
    ///    field, so a value cannot introduce a field the contract never asked for — the same
    ///    column-0 rule [`Self::render`] relies on, read in the other direction.
    /// 2. **First occurrence wins.** A later `source_1:` inside another value cannot overwrite what
    ///    was already attributed.
    /// 3. **Unmatched fields stay absent**, so the contract's own `validate` fails and the parent
    ///    reports that the content could not be condensed. Absent beats invented.
    ///
    /// Returns `None` when the reply names no declared field at all — the child answered in prose,
    /// which for a multi-field contract is not an answer.
    pub fn parse_fields(text: &str, fields: &[FieldSpec]) -> Option<Self> {
        let mut out = Self::new();
        let mut current: Option<&str> = None;
        let mut buf: Vec<&str> = Vec::new();

        let flush = |out: &mut Self, name: Option<&str>, buf: &mut Vec<&str>| {
            if let Some(n) = name {
                // Only if absent: rule 2.
                if !out.fields.contains_key(n) {
                    out.fields.insert(n.to_string(), buf.join("\n").trim().to_string());
                }
            }
            buf.clear();
        };

        for line in text.lines() {
            // Rule 1: no `trim_start`. An indented `source_2:` is a value line, exactly as
            // `render` guarantees when it writes one.
            let header = line.split_once(':').and_then(|(name, rest)| {
                fields.iter().find(|f| f.name == name).map(|f| (f.name.as_str(), rest))
            });
            match header {
                Some((name, rest)) => {
                    flush(&mut out, current, &mut buf);
                    current = Some(name);
                    if !rest.trim().is_empty() {
                        buf.push(rest.trim_start());
                    }
                }
                None => buf.push(line),
            }
        }
        flush(&mut out, current, &mut buf);

        if out.fields.is_empty() {
            None
        } else {
            Some(out)
        }
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
    /// **The latched trust floor. Monotonic: it only ever falls.**
    ///
    /// ADR-023 says *"**once a run has read untrusted content**, every model-composed Target in
    /// that run is blocked"* — a property of the RUN, permanent from the moment it holds.
    ///
    /// It was derived from `ContextView::trust_floor()`, the minimum trust class of the blocks
    /// **currently in the view**. `ToolResults` — where untrusted content lands — is trimmable, so
    /// the assembler could drop the untrusted block to stay inside its budget and the floor would
    /// **rise again**. The run would silently regain privileges it was supposed to have lost, with
    /// no error and no event.
    ///
    /// Making untrusted blocks untrimmable was the alternative and is worse: one poisoned page
    /// would pin the window open for the rest of the run, converting a security property into a
    /// denial of service.
    ///
    /// **The new loop is what made this reachable.** With `done` removed and multi-step work
    /// actually happening, a run can now last long enough for trimming to occur mid-run — which it
    /// structurally could not before.
    trust_floor: TrustClass,
}

impl Run {
    /// The run's trust floor: the worst class it has ever been exposed to.
    pub fn trust_floor(&self) -> TrustClass {
        self.trust_floor
    }

    /// Lower the floor if this view is worse than anything seen before. **Never raises it.**
    ///
    /// Returns `Some(new_floor)` when it actually moved, so the caller can record and announce
    /// the change — a guard that engages silently is a guard nobody can confirm engaged.
    pub fn latch_trust_floor(&mut self, observed: TrustClass) -> Option<TrustClass> {
        if observed < self.trust_floor {
            self.trust_floor = observed;
            Some(observed)
        } else {
            None
        }
    }

    /// A child of `parent`. **Inherits the parent's latched floor.**
    ///
    /// A spawn is a narrowing and there is no widening path (§5), so a child can never be *less*
    /// tainted than the run that created it — its task string was model-composed from the parent's
    /// window, and starting it clean would launder exactly what ADR-023 blocks.
    ///
    /// The quarantined-reader pattern still works, and this is why it is the *only* thing that
    /// works: an UNTAINTED orchestrator spawns a reader, the reader's own floor drops when it
    /// reads the page, and the structured findings it returns carry a class the orchestrator can
    /// act on. The orchestrator never saw the page, so its floor never moved.
    #[allow(clippy::too_many_arguments)]
    pub fn child(
        id: RunId,
        parent: &Run,
        session: SessionId,
        profile: CapabilityProfile,
        budget: Budget,
        orphan_policy: OrphanPolicy,
        output_contract: OutputContract,
    ) -> Self {
        Self {
            id,
            parent: Some(parent.id),
            session,
            trace_id: parent.trace_id, // one trace across the tree — invariant 7's replay key
            status: RunStatus::Queued,
            profile,
            budget,
            spent: Budget::default(),
            orphan_policy,
            output_contract,
            last_checkpoint: None,
            trust_floor: parent.trust_floor,
        }
    }

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
            // The highest class: nothing untrusted has been seen yet.
            trust_floor: TrustClass::UserAsserted,
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
