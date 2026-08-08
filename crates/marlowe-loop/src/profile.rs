//! CONTRACTS.md §5 — `CapabilityProfile`.
//!
//! > One loop. Research, voice, coding, automation, consolidation, and quarantined reading are
//! > **capability profiles** — differing in tool exposure, budgets, and interrupt policy — not
//! > variants.
//!
//! The named constructors in this file are that sentence made executable. There is no
//! `ConsolidationLoop` and no `QuarantinedReader` type; there is one loop and
//! [`CapabilityProfile::consolidation`] / [`CapabilityProfile::quarantined_reader`].
//!
//! # The load-time error, and why it is a constructor
//!
//! CONTRACTS §5:
//!
//! > `reads_untrusted && !exposed_tools.is_empty()` is a load-time error. That is §8.2's
//! > structural trifecta break, expressed as a type invariant rather than a guideline.
//!
//! Every field is private and [`CapabilityProfile::new`] is the only way in — including for
//! `serde`, which routes through it. A public-field struct with a `validate()` method beside it
//! would leave the invalid state constructible, and a test asserting `validate()` returns an
//! error would then be measuring a function nobody has to call.

use marlowe_permission::EgressPolicy;
use marlowe_tools::{ExposedSet, ExposureError, ToolId};
use serde::{Deserialize, Serialize};

/// §9's mid-tool interrupt policy. **In code, not a config knob** — the brief is explicit that
/// tool semantics belong in code review.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InterruptPolicy {
    /// A user is present and may cut in mid-turn. Idempotent reads complete; mutations cancel
    /// on contradiction.
    Interruptible,
    /// No interactive surface. Steering still applies, at iteration boundaries — a child that
    /// cannot be steered is a child you discover has failed at minute 60.
    Unattended,
}

/// ADR-008 — routing is by **task role**, declared here, never by user preference.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelRoute {
    /// Strong model: orchestration and synthesis.
    Orchestrator,
    /// Fast and cheap: subagent search, extraction, classification, consolidation.
    Worker,
    /// Cheapest: the compaction summarizer. Named separately because §6 requires compaction to
    /// fire at 70% rather than at exhaustion, and the whole point is that this call is cheap
    /// enough to make that affordable.
    Summarizer,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ProfileError {
    #[error(
        "a profile with `reads_untrusted` exposes {count} tool(s). The component that reads \
         untrusted content has no tool access and returns structured analysis only (brief §8.2). \
         This is the structural trifecta break and it is a load-time error, not a warning"
    )]
    QuarantineWithTools { count: usize },

    #[error(
        "a profile with `reads_untrusted` also sets `may_write_memory`. A quarantined reader \
         that can write beliefs is memory laundering with the derivation step built in (§14.6, \
         HP6)"
    )]
    QuarantineMayWriteMemory,

    #[error(
        "a profile with `reads_untrusted` also grants egress. Reading untrusted content and \
         reaching the network are two legs of the trifecta in one component (§8.1)"
    )]
    QuarantineWithEgress,

    #[error(
        "a child profile exposes `{tool}`, which its parent does not have. Privilege must not \
         grow with depth — a spawn is a narrowing, and there is no widening path"
    )]
    WidenedPastParent { tool: ToolId },

    #[error(transparent)]
    Exposure(#[from] ExposureError),
}

/// CONTRACTS.md §5.
///
/// `exposed_tools` is an [`ExposedSet`] rather than a bare `Vec<ToolId>`. That is the pinned
/// field's own invariant — §5 annotates it `INVARIANT: len() <= 12` and §7.2 says the
/// constructor is what enforces it — and the serialized form is identical, because
/// `ExposedSet` is `serde(transparent)` over the same vector. The schema is unchanged; the
/// invariant moved from a comment into the type.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CapabilityProfile {
    exposed_tools: ExposedSet,
    egress: EgressPolicy,
    interrupt: InterruptPolicy,
    model_route: ModelRoute,
    may_write_memory: bool,
    reads_untrusted: bool,
}

impl CapabilityProfile {
    /// The only constructor.
    pub fn new(
        exposed_tools: ExposedSet,
        egress: EgressPolicy,
        interrupt: InterruptPolicy,
        model_route: ModelRoute,
        may_write_memory: bool,
        reads_untrusted: bool,
    ) -> Result<Self, ProfileError> {
        if reads_untrusted {
            // The pinned check.
            if !exposed_tools.is_empty() {
                return Err(ProfileError::QuarantineWithTools { count: exposed_tools.len() });
            }
            // Two checks the contract does not state. They are strictly narrower than what §5
            // requires — no profile that satisfied the original is rejected here unless it also
            // recombined a trifecta leg — and both close a hole the empty tool set alone does
            // not: `remember` is not the only way to write memory (the loop's MemoryWrite step
            // is), and egress needs no tool at all if the profile grants it.
            if may_write_memory {
                return Err(ProfileError::QuarantineMayWriteMemory);
            }
            if egress != EgressPolicy::DenyAll {
                return Err(ProfileError::QuarantineWithEgress);
            }
        }
        Ok(Self {
            exposed_tools,
            egress,
            interrupt,
            model_route,
            may_write_memory,
            reads_untrusted,
        })
    }

    /// §8.2's quarantined reader: reads untrusted content, has **no tool access**, and returns
    /// structured analysis only. The one profile ADR-002 keeps a kernel sandbox for.
    pub fn quarantined_reader() -> Self {
        Self::new(
            ExposedSet::empty(),
            EgressPolicy::DenyAll,
            InterruptPolicy::Unattended,
            ModelRoute::Worker,
            false,
            true,
        )
        .expect("the quarantined reader is the shape the invariant describes")
    }

    /// ARCHITECTURE §2.6 — consolidation is a run on the one loop with a memory-only profile
    /// and a hard step budget. It is not a second loop.
    pub fn consolidation() -> Self {
        Self::new(
            ExposedSet::new(vec![ToolId::new("recall"), ToolId::new("remember"), ToolId::new("done")])
                .expect("three tools"),
            EgressPolicy::DenyAll,
            InterruptPolicy::Unattended,
            ModelRoute::Worker,
            true,
            false,
        )
        .expect("consolidation reads nothing untrusted")
    }

    /// The interactive coding profile: all eleven, no egress until the user grants it.
    pub fn interactive() -> Self {
        let tools = marlowe_tools::BUILTIN_TOOLS.iter().map(|t| ToolId::new(*t)).collect();
        Self::new(
            ExposedSet::new(tools).expect("eleven fits in twelve"),
            EgressPolicy::DenyAll,
            InterruptPolicy::Interruptible,
            ModelRoute::Orchestrator,
            true,
            false,
        )
        .expect("the interactive profile reads nothing untrusted")
    }

    pub fn exposed_tools(&self) -> &ExposedSet {
        &self.exposed_tools
    }
    pub fn egress(&self) -> &EgressPolicy {
        &self.egress
    }
    pub fn interrupt(&self) -> InterruptPolicy {
        self.interrupt
    }
    pub fn model_route(&self) -> ModelRoute {
        self.model_route
    }
    pub fn may_write_memory(&self) -> bool {
        self.may_write_memory
    }
    pub fn reads_untrusted(&self) -> bool {
        self.reads_untrusted
    }

    /// Narrow a profile for a child. **Widening is not offered** — there is no method that
    /// hands a child a tool the parent did not have, so privilege cannot grow with depth.
    pub fn narrowed(&self, tools: Vec<ToolId>) -> Result<Self, ProfileError> {
        for t in &tools {
            if !self.exposed_tools.contains(t) {
                return Err(ProfileError::WidenedPastParent { tool: t.clone() });
            }
        }
        Self::new(
            ExposedSet::new(tools)?,
            self.egress.clone(),
            self.interrupt,
            ModelRoute::Worker,
            self.may_write_memory,
            self.reads_untrusted,
        )
    }
}

/// Deserialization routes through [`CapabilityProfile::new`].
///
/// Without this the invariant would hold for every profile built in code and fail for every
/// profile read from a file — which is the only place an attacker-shaped one could come from.
impl<'de> Deserialize<'de> for CapabilityProfile {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Raw {
            exposed_tools: ExposedSet,
            #[serde(default)]
            egress: EgressPolicy,
            interrupt: InterruptPolicy,
            model_route: ModelRoute,
            may_write_memory: bool,
            reads_untrusted: bool,
        }
        let r = Raw::deserialize(d)?;
        CapabilityProfile::new(
            r.exposed_tools,
            r.egress,
            r.interrupt,
            r.model_route,
            r.may_write_memory,
            r.reads_untrusted,
        )
        .map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn one_tool() -> ExposedSet {
        ExposedSet::new(vec![ToolId::new("read")]).unwrap()
    }

    #[test]
    fn a_spawn_that_reads_untrusted_with_any_tool_fails_at_load_time() {
        // CONTRACTS §5's pinned load-time error, and M2's first report item.
        let e = CapabilityProfile::new(
            one_tool(),
            EgressPolicy::DenyAll,
            InterruptPolicy::Unattended,
            ModelRoute::Worker,
            false,
            true,
        )
        .unwrap_err();
        assert_eq!(e, ProfileError::QuarantineWithTools { count: 1 });
        assert!(
            e.to_string().contains("trifecta"),
            "the refusal must name what it is protecting: {e}"
        );
    }

    #[test]
    fn the_empty_tool_set_is_the_only_quarantined_shape() {
        // ...and the empty set alone is not sufficient. Both extra refusals close a leg that
        // needs no tool.
        assert!(CapabilityProfile::new(
            ExposedSet::empty(),
            EgressPolicy::DenyAll,
            InterruptPolicy::Unattended,
            ModelRoute::Worker,
            false,
            true,
        )
        .is_ok());

        assert_eq!(
            CapabilityProfile::new(
                ExposedSet::empty(),
                EgressPolicy::DenyAll,
                InterruptPolicy::Unattended,
                ModelRoute::Worker,
                true, // may_write_memory
                true,
            )
            .unwrap_err(),
            ProfileError::QuarantineMayWriteMemory
        );

        assert_eq!(
            CapabilityProfile::new(
                ExposedSet::empty(),
                EgressPolicy::allow(&["example.com"]),
                InterruptPolicy::Unattended,
                ModelRoute::Worker,
                false,
                true,
            )
            .unwrap_err(),
            ProfileError::QuarantineWithEgress
        );
    }

    #[test]
    fn deserialization_cannot_bypass_the_invariant() {
        // The path that matters: a profile arriving from a file. Without a constructor-routed
        // Deserialize, this is where a quarantined reader with tools would be born, and every
        // in-code test would still pass.
        let json = r#"{
            "exposed_tools": ["read"],
            "egress": "deny_all",
            "interrupt": "unattended",
            "model_route": "worker",
            "may_write_memory": false,
            "reads_untrusted": true
        }"#;
        let err = serde_json::from_str::<CapabilityProfile>(json).unwrap_err().to_string();
        assert!(err.contains("trifecta"), "{err}");
    }

    #[test]
    fn the_named_profiles_are_the_capability_profiles_not_variants() {
        let q = CapabilityProfile::quarantined_reader();
        assert!(q.reads_untrusted() && q.exposed_tools().is_empty() && !q.may_write_memory());

        let c = CapabilityProfile::consolidation();
        assert!(c.may_write_memory() && !c.reads_untrusted());
        assert_eq!(c.exposed_tools().len(), 3);

        let i = CapabilityProfile::interactive();
        assert_eq!(i.exposed_tools().len(), 11);
        assert_eq!(*i.egress(), EgressPolicy::DenyAll, "egress is granted, never assumed");
    }

    #[test]
    fn a_child_cannot_be_widened_past_its_parent() {
        let narrow = CapabilityProfile::new(
            ExposedSet::new(vec![ToolId::new("read"), ToolId::new("done")]).unwrap(),
            EgressPolicy::DenyAll,
            InterruptPolicy::Unattended,
            ModelRoute::Orchestrator,
            false,
            false,
        )
        .unwrap();
        assert!(narrow.narrowed(vec![ToolId::new("read")]).is_ok());
        assert!(
            narrow.narrowed(vec![ToolId::new("bash")]).is_err(),
            "privilege must not grow with depth"
        );
    }
}
