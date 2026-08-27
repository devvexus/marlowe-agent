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
            // `done` is gone: a run ends when the model replies without calling a tool (M2 C2e).
            // Exposing a tool whose only job was ending would advertise a control token the loop
            // no longer reads.
            ExposedSet::new(vec![ToolId::new("recall"), ToolId::new("remember")])
                .expect("two tools"),
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
        // **Only what can actually run.** `recall` and `use` are registered and unimplemented —
        // exposing a tool the host cannot execute gave the model something it could see, call
        // correctly, and never run, which is what made "check the weather" produce a model
        // arguing with an error it could not read.
        //
        // **`web` came back in M2 C2f**, which is the rule working rather than an exception to it:
        // it has an executor now (`marlowe-exec`, fetch-only over `marlowe-net`), so
        // `verify_every_exposed_tool_is_runnable` permits it. It was removed and restored by the
        // same check, without anyone having to remember either time.
        // **`recall` joined in M2 Session D**, by the same rule that brought `web` back in C2f: it
        // has an executor now (`crate::recall` in the daemon, over the belief store), so
        // `verify_every_exposed_tool_is_runnable` permits it. Exposing it is what makes memory
        // reachable at all — auto-injection is gated at 10% coverage and withholds unmatured
        // beliefs entirely, so without this tool a memory written a minute ago is unreachable by
        // any path. §5.5: *"recall recovered by making the agent's explicit memory search tool
        // excellent."*
        //
        // **`use` joined in M2 C3 (ADR-051)**, by the identical rule a third time. It has an
        // executor now — `marlowe_daemon::skills::SkillTools`, over the installed skill registry —
        // so `verify_every_exposed_tool_is_runnable` permits it. It had been
        // registered-and-unrunnable since Session A, and exposing it is what makes an installed
        // skill reachable at all: a skills library the model cannot see is a directory.
        //
        // Three tools have now been restored by this guard and none by anybody remembering to.
        // That is the property: the exposed set is DERIVED from what is runnable rather than
        // maintained beside it.
        // **`write` joined when `edit` was split in two.** `edit` used to carry both modes,
        // separated by an optional parameter, and a model asked to write a file reached for the
        // shell instead -- no builtin was named for the verb. Splitting them is only useful if
        // BOTH are exposed, which is this line.
        let tools = [
            "read", "write", "edit", "find", "bash", "web", "recall", "use", "ask", "remember",
            "run",
        ]
        .iter()
        .map(|t| ToolId::new(*t))
        .collect();
        Self::new(
            ExposedSet::new(tools).expect("eleven fits in thirteen"),
            // **ADR-032 §3.1: nothing reachable by default, each host by human approval.**
            //
            // Not `DenyAll`, which is structural and unwidenable — the quarantined reader holds
            // that, and §5's narrowing rule depends on it. Not `Allow { hosts }`, which is a list
            // somebody guessed at in advance. The set starts **empty**, so brief §8's
            // allowlist-by-default holds with an empty default rather than a `*`, and it grows one
            // host at a time by a person who was shown the blast radius.
            EgressPolicy::AllowApproved { granted: Vec::new() },
            InterruptPolicy::Interruptible,
            ModelRoute::Orchestrator,
            true,
            false,
        )
        .expect("the interactive profile reads nothing untrusted")
    }

    /// [`Self::interactive`] plus the tools an installed MCP server contributes. ADR-052 §5.
    ///
    /// # Why widening exists here and nowhere else
    ///
    /// `narrowed` has no counterpart on purpose: a **spawn** may only narrow, because privilege
    /// must not grow with depth, and `WidenedPastParent` enforces it. This is not that. It is how
    /// a top-level profile is *built* — the exposed set has always been chosen at construction —
    /// and it takes no parent, so there is nothing for it to grow past. A child of the profile
    /// this returns is still narrowed against it, unchanged.
    ///
    /// # The budget refuses, and the message says which tool to drop
    ///
    /// The interactive set is eleven of ARCHITECTURE §5's thirteen, so **two MCP tools fit and a
    /// third does not**. The cap moved with ADR-058 precisely so that splitting `write` out of
    /// `edit` did not take that two down to one: a fix to Marlowe's own surface must not be paid
    /// for out of a user's server allowance. That is a real constraint on a real product and it refuses at load rather than
    /// silently dropping the overflow: a server whose third tool quietly vanished would look like
    /// a server with a broken tool. `ExposureError::TooMany` carries the count and the remedy.
    ///
    /// A user who needs more MCP tools than that has to give something up, and it should be their
    /// choice which — so the refusal names the budget rather than this function picking a victim.
    pub fn interactive_with(extra: Vec<ToolId>) -> Result<Self, ProfileError> {
        let base = Self::interactive();
        let mut tools: Vec<ToolId> = base.exposed_tools.iter().cloned().collect();
        tools.extend(extra);
        Ok(Self::new(
            ExposedSet::new(tools)?,
            base.egress,
            base.interrupt,
            base.model_route,
            base.may_write_memory,
            base.reads_untrusted,
        )?)
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
        // Two since `done` was removed — consolidation recalls and remembers, and ends by replying.
        //
        // **`recall` has no executor yet**, so this profile would fail
        // `verify_every_exposed_tool_is_runnable` against `FileSystemTools`. It is left as
        // declared because consolidation is not wired until M2 D, and the guard firing at that
        // point is the guard working — not a surprise to design around now.
        assert_eq!(c.exposed_tools().len(), 2);

        let i = CapabilityProfile::interactive();
        // **Eleven as of the write/edit split, and ONE under the budget.** `web` rejoined in C2f,
        // `recall` in Session D, `use` in C3 -- each at the moment it gained an executor, added by
        // the same guard without anyone having to remember. That is the point of
        // `verify_every_exposed_tool_is_runnable`: the exposed set is derived from what is
        // runnable rather than maintained beside it.
        //
        // **The eleventh is `write`, and it did NOT cost an MCP slot.** Against the old cap of
        // twelve it would have taken a server from two tools to one; ADR-058 moved the cap to
        // thirteen instead, because a fix to Marlowe's own surface must not be paid for out of a
        // user's server allowance. `composition_root.rs` asserts the two slots rather than the
        // total, so the next builtin that would eat one fails the suite.
        assert_eq!(i.exposed_tools().len(), 11);
        assert!(
            i.exposed_tools().iter().any(|t| t.as_str() == "recall"),
            "recall is what makes a memory written a minute ago reachable at all: auto-injection \
             withholds unmatured beliefs and covers 10% of queries even after they mature"
        );
        assert!(
            i.exposed_tools().iter().any(|t| t.as_str() == "use"),
            "`use` is what makes an installed skill reachable: nothing else loads a SKILL.md, \
             and a skills library the model cannot see is a directory"
        );
        assert_eq!(
            *i.egress(),
            EgressPolicy::AllowApproved { granted: Vec::new() },
            "the set starts EMPTY: egress is granted per host by a human, never assumed. This is              not DenyAll — that is structural and unwidenable, and the quarantined reader holds it"
        );
        assert!(i.egress().may_ask(), "an ungranted host is a question here, not a refusal");
        assert!(
            !CapabilityProfile::quarantined_reader().egress().may_ask(),
            "the quarantined reader may never ask its way onto the network"
        );
    }

    #[test]
    fn a_child_cannot_be_widened_past_its_parent() {
        let narrow = CapabilityProfile::new(
            ExposedSet::new(vec![ToolId::new("read"), ToolId::new("find")]).unwrap(),
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

/// **A tool in the exposed set with no executor is unrepresentable, not merely wrong.**
///
/// # The fifth instance
///
/// The model can see the tool, call it correctly, and get back `has no executor in this build` —
/// a failure it cannot interpret and cannot route around. It has happened five times:
///
/// | Tool | What the model got |
/// |---|---|
/// | `done` (M2 C2b) | routed to the tool host, which had no executor; the model retried for 155 s |
/// | `web` | same, and it is what made "check the weather" unanswerable |
/// | `recall` | same |
/// | `use` | same |
///
/// Every one of them passed every unit test, because each half was right in isolation: the
/// registry registered the tool, the profile exposed it, and the host correctly reported that it
/// could not run it. **Nothing owned the seam.** This does.
///
/// The check runs where the two sides meet — a profile and a host — and it is a **load-time
/// error**. A daemon that starts and then fails every third tool call presents as a broken model;
/// a daemon that refuses to start names the tool and the fix in one line.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error(
    "the capability profile exposes {} the tool host cannot run: {}.
     A tool the model can see and call but never execute returns an error it cannot interpret.      Either give it an executor or stop exposing it.
     Loop-control tools ({}) are exempt: ARCHITECTURE §3 handles them as ModelStep variants.",
    if .0.len() == 1 { "a tool".to_string() } else { format!("{} tools", .0.len()) },
    .0.join(", "),
    crate::driver::CONTROL_TOOLS.join(", ")
)]
pub struct UnrunnableTools(pub Vec<String>);

/// Verify that every exposed tool can actually be reached.
///
/// Call this once, at startup, before a model is ever offered the set.
pub fn verify_every_exposed_tool_is_runnable(
    exposed: &ExposedSet,
    host: &dyn crate::driver::ToolHost,
) -> Result<(), UnrunnableTools> {
    let runnable: std::collections::BTreeSet<String> =
        host.executes().into_iter().map(|t| t.as_str().to_string()).collect();
    let unrunnable: Vec<String> = exposed
        .iter()
        .map(|t| t.as_str().to_string())
        .filter(|name| {
            !runnable.contains(name) && !crate::driver::CONTROL_TOOLS.contains(&name.as_str())
        })
        .collect();
    if unrunnable.is_empty() {
        Ok(())
    } else {
        Err(UnrunnableTools(unrunnable))
    }
}
