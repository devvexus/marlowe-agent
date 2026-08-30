# upward-channel: An escalation is a record, `severity` is not one of its fields, and A8's arm is a flag the running process journals

**Adversary verdict:** broken

**Fatal:** `UpwardShape` changes no byte the product emits, so A8 as designed measures the flag rather than the channel. The only discriminator is `run.parent`. For `parent: None` the match arm is `(None, _) => UpwardNote::Principal` — shape ignored outright. For `parent: Some(_)` the note is computed and then thrown away: `Engine::spawn`'s note match (`crates/marlowe-loop/src/engine.rs:2910-2947`) already replaces a child's `LoopOutcome::Escalated { question }` with the fixed harness string "[child asked a question; a child cannot escalate to the parent's window and its question was not carried across]", so a child's `Escalated` never reaches `daemon.rs:2899` and never becomes `Event::Escalation`. The design says so itself — "the child→parent hop was closed at engine.rs:~2900 … I am designing only for [run→OUT]" — then builds three arms whose sole discriminator is that closed hop. `--upward-shape typed` and `--upward-shape free-text` therefore produce byte-identical product behaviour. `a_typed_escalation_carries_none_of_the_models_question` can only be green by constructing an `Escalation` inside the test process and serialising it there — the `persona_emission.rs` failure aimed at a security measurement — and `every_escalation_row_names_its_arm` is instance #15 verbatim: the journal row would read `upward_shape: "free_text"` on a build where every note is deleted, because the row moves with the flag, not with the channel.

## Ledger instances the adversary says this re-commits

- #16 (a declared control nothing reads) — `EscalationCategory::parse`: no caller, because `ask`'s manifest (builtin.rs:697-716) declares only `question` and `control_step` (ollama.rs:1023) reads only `question`.
- #16 — the entire `BudgetExtension` / `ExtensionReason` / `ExtensionEvidence` record set: zero hits for "extension" or "envelope" under `crates/marlowe-loop/src/`, no `ModelStep` variant, no tool, no producer; and the design proposes pinning it in CONTRACTS §12.
- #16 — `Escalation.artifact`: its claimed write-side enforcement (`PathScope::open` inside `raise`) is impossible at the signature given, since `Adjudicator::scope` is private in a §13-guarded file and `raise` receives no workspace or globs.
- #16 — `Lineage.external_sources`: the design's own enforcement-site row says "IN SESSION C IT ENFORCES NOTHING", leaving `--dev` and a report script as its only readers.
- #16 — `Escalation.category_requested`: its stated reader is a journal payload and `tools/a8_report.py`; with no manifest parameter for `category`, `requested` is `null` on every row the product can produce.
- #15 (an assertion that reads identically whether the mechanism worked) — `every_escalation_row_names_its_arm` reads `upward_shape` from the running process's journal, which moves with the CLI flag and not with the channel; the row prints `free_text` on a build where every note is discarded, which is this build.
- #15 — `a_typed_escalation_carries_none_of_the_models_question`: a child's `LoopOutcome::Escalated` is consumed by `Engine::spawn`'s note match at engine.rs:2936 and never reaches `Event::Escalation`, so both halves of the nonce test can only be green over an `Escalation` the test constructs itself — a source-level assertion on a security measurement, the `persona_emission.rs` family.
- #19 (a self-check whose input is the object it checks) — `tools/a8_report.py`'s mixed-arm refusal: a cell whose rows all lack `upward_shape` reads as one arm and passes. The proposed mitigation, "assert that constructor count", is a second grep over the same object.
- #12 (serde as a way in) — soft: `protocol::Event` derives `Deserialize` (protocol.rs:217) and the frame's `category`, `shape` and `note_kind` are bare `String`s that re-enter Rust without passing `UpwardShape::parse` or `EscalationCategory::parse`.
- Axis 6, two definitions of one fact — `Lineage.external_sources` beside the journal's per-`finish_call` trust classes; `note_kind`'s four inline literals beside `UpwardNote`'s serde spelling; `category: String` on the wire with no named `as_str`.
- Axis 7, a decision that is the human's taken implicitly — deleting `severity` revisits `DECISIONS.md:3319-3321` (2026-08-29), which quotes the record shape including `severity`; the design escalates the M3-DESIGN §2.3 half but never cites the settled entry.
- NOT committed, and recorded because the review must be defensible: #17 is clean. `max_grants_per_run` is >= 1 on every arm with the `0 >= 0` reasoning stated in the doc comment, and `UpwardShape::Typed` withholds structurally (a variant, not a counter). The design named the trap and avoided it. Also verified TRUE and left standing: `ContentRef` has no Rust implementation anywhere under `crates/`; the driver.rs hook-entry quote is verbatim accurate and its "`ModelStep` is not the boundary" reading is correct; `blocks_composed_targets` is `pub` at `adjudicate.rs:50` and `Engine::spawn` already calls it; SECURITY-AUDIT finding 6 is real, open, and cited rather than re-derived; `SpawnRequest`'s fields are genuinely unpinned and `LoopOutcome` is genuinely absent from CONTRACTS; and the rejections of a `cfg`-feature arm and an env-var arm (`minimal_env()` is a fixed allowlist) are both right.

## Defects (12)

### A8 is pointed at a hop that carries nothing, and away from the hop REDTEAM pass 1 actually measures. `REDTEAM-SESSION.md` §4 pass 1 names the attack surface as "the condensed summary re-entering a parent at `AgentInferred`, and the typed upward channels C ships." The channel that crosses upward in this codebase is `OutputContract`/`FieldSpec` → `CondensedResult::render()`, applied at `engine.rs:2911-2916`. `crates/marlowe-loop/src/run.rs:230-247` states it plainly: "The contract is the single place where content crosses from `UntrustedContent` to `AgentInferred` … the bandwidth is still not zero and this file will not pretend otherwise — a summary of a page is attacker-influenced prose no matter how it is typed." The design declares that hop "closed by `OutputContract`/`FieldSpec` (CONTRACTS §5.1)" and out of scope, substituting a channel with no traffic for the one under test.

- **Why:** M3-DESIGN §9.1: "A8's third arm is the vacuity control for the entire §2 invariant." REDTEAM §3.1: "Sessions D and E are built on the assumption that typed upward containment works. End of C is the last cheap moment to discover that it does not." An A8 run on this design returns three identical cells, which reads as "typing is decorative" — the exact finding the arm exists to detect — while actually meaning the arm never varied anything.
- **Fix:** Move `UpwardShape` to `Engine::spawn`'s note match, the one place a child's words cross into a parent. Arm (a) Typed = today's code unchanged (`req.contract.validate` then `result.render()`, harness constants on every other outcome). Arm (b) = Typed plus one `FieldSpec::line("headline").capped(200)` produced by a quarantined child through the existing `condense_batch` machinery, omitted on any non-`Completed` outcome. Arm (c) FreeText = the child's last assistant message verbatim with `validate` NOT called — the control, which deliberately reopens the hole the comment at engine.rs:2900-2907 closed, and which takes its own `DECISIONS.md` entry. Note §5.1 pins only the QUARANTINED READER's contract (`source_N` slots); an ordinary child's `OutputContract` arrives on `SpawnRequest`, which is unpinned, so varying it is legal without a pinned-contract change.

### `AskRequest.category` has no producer, so `EscalationCategory::parse` has zero callers and `Unclassified` is the only category the product can ever emit. `ask`'s registration in `crates/marlowe-tools/src/builtin.rs:697-716` declares exactly one parameter — `question`, `ArgumentRole::Payload`. `control_step` at `crates/marlowe-provider/src/ollama.rs:1023` builds `ModelStep::Ask(text("question").unwrap_or(body))`. The design touches neither file and never names them.

- **Why:** Instance #16 inside the design's own new code. `disposition()` becomes a constant in the product, `Event::Escalation { interrupt }` is a constant byte, and `a_tainted_run_cannot_choose_its_escalation_category` asserts on a state the product cannot enter. `builtin.rs`'s own comment records the precedent — `options` was deleted from this exact manifest because "a model that listed options had them silently dropped on the way to a user who never saw them." The design re-commits that defect one field over.
- **Fix:** Add `category` (and `artifact_path`) to the `ask` manifest as `ArgumentRole::Target`, with the five spellings named in the description. Add `AskRequest::from_args(args: &Args, message: &serde_json::Value) -> AskRequest` to `driver.rs` beside `SpawnRequest::from_args`, and reduce `ollama.rs:1023` to `"ask" => ModelStep::Ask(AskRequest::from_args(args, message))`.

### A second definition of what `ask` means, per provider. `SpawnRequest::from_args`'s doc in `driver.rs` states the rule the design ignores: "`SpawnRequest` is defined here and `Engine::spawn` enforces here, so a second provider that wrote its own mapping would be a second definition of the contract — the two-sides-silently-disagree shape this project keeps recording." The design defines `AskRequest` in driver.rs, names no constructor, and leaves the parse to land in each adapter's `control_step`.

- **Why:** Three adapters already exist (`ollama.rs`, marlowe-openrouter, the llamacpp fold). Three mappings of `category` is three answers to "did the model ask to interrupt the human", diverging silently.
- **Fix:** `AskRequest::from_args` in `driver.rs`, total, with a fixed rule for every field, exactly as `SpawnRequest::from_args` is. Adapters recognise the tool name and nothing more.

### `Escalation::raise` makes the security decision from a caller-supplied copy of the floor and calls that one-definition. Its guard is `blocks_composed_targets(lineage.floor)`, and `lineage: Lineage` is a parameter. The enforcement-site entry defends this as "deliberately reading the DISPLAYED field rather than calling run.trust_floor() a second time". That inverts authority and display.

- **Why:** Any caller that builds `Lineage { floor: UserAsserted, .. }` — a test helper, a resume path, the §3.6 window renderer later — hands a tainted run its chosen category back, and no proposed test catches it because every proposed test constructs `Lineage` honestly. `run.trust_floor()` (run.rs:605) is the latched authority ADR-023 put on the `Run`; a struct field is a copy of it.
- **Fix:** `raise(run: &Run, req: &AskRequest, artifact: Option<ArtifactRef>)` reads `let floor = run.trust_floor();` once, uses it for the guard, and DERIVES `Lineage { floor }` from that same binding. One expression, display derived from authority, not the reverse.

### `Escalation::raise` cannot resolve `ArtifactRef`, so the field's only enforcement is unimplementable at the signature given. The signature takes `artifact: Option<ArtifactRef>` already constructed, while the enforcement-site row claims "raise resolves it through PathScope::open before construction". `PathScope::open` (`crates/marlowe-permission/src/scope/mod.rs:186`) needs `declared: &[PathGlob]`, `workspace: &Path` and `access` — none of which `raise` has. The scope lives inside `Adjudicator<S>` as a private field (`adjudicate.rs:254-262`) with no accessor, and `adjudicate.rs` is §13-guarded. `ScopedPath` also yields no `bytes: u64`; that needs a stat the design never mentions.

- **Why:** As written the field ships as the model's own path string echoed back to a client that would re-resolve it — instance #16 with a path-traversal edge, on the surface M3-DESIGN §3.6 calls "the highest-value display attack in the product".
- **Fix:** Resolve at the `ModelStep::Ask` site in `engine.rs`, where the workspace and profile are in hand, and pass the resolved `Option<ArtifactRef>` into `raise`. Getting the scope there costs either `pub fn scope(&self) -> &S` on the guarded `Adjudicator`, or an `S: PathScope + Clone` bound so `Engine::new` keeps its own handle (the non-guarded route, and the one to prefer). Drop `bytes` — nothing reads it. If neither route is taken, defer `artifact` entirely; do not ship the field.

### The whole §4.1/§4.2 budget-extension half has no producer anywhere. `grep -rni "extension|envelope" crates/marlowe-loop/src/` returns zero hits. There is no `ModelStep` variant, no tool registration, no `Args` mapping, and the design proposes none.

- **Why:** Instance #16 at subsystem scale. `Run::request_extension` would have no production caller; `ExtensionReason::max_grants_per_run` — advertised as "THE READER of reason_code" — would read a field on a record nothing constructs; `ExtensionEvidence`'s claimed reader (the §4.2 announcement string in daemon.rs) has no path to reach it; and `an_extension_request_has_no_place_to_put_a_sentence` pins the JSON key set of a type the product never emits, which is a green test over a mechanism that never ran. The design then proposes PINNING all of it in `CONTRACTS.md` §12.
- **Fix:** Either ship the producer in the same session — `ModelStep::RequestBudget(BudgetExtensionRequest)`, a `request_budget` registration in `builtin.rs` with `reason` as a Target, and `BudgetExtensionRequest::from_args` in driver.rs — or cut §4.1/§4.2 from Session C entirely and say in `STATE.md` that the escalation channel shipped and the budget channel did not. Do not pin an unproduced record in CONTRACTS.

### `severity`'s deletion overrules a settled `DECISIONS.md` entry the design never cites, and the argument for deleting it is the wrong diagnosis. `DECISIONS.md:3319-3321` (2026-08-29) reads: "a typed upward return — M3-DESIGN §2.3's `{ run_id, severity, category (fixed enum), artifact_ref, lineage[] }` — needs no `Channel` and no trust class." The record shape including `severity` is quoted inside a settled decision. And `severity` is not unread: M3-DESIGN §3.2 renders it ("A `critical` escalation has been raised by `CodeProjectLeader`") and §9.1's A7 is named "severity-gated".

- **Why:** CLAUDE.md: "Decisions in `DECISIONS.md` are settled. Argue explicitly to revisit one; do not quietly design around it." The `contract_impact` cites only M3-DESIGN §2.3 and misses the DECISIONS entry, so the human would be asked to approve a smaller change than the one being made. The real defect the design correctly smelled is not "nothing reads it" — it is that the MODEL chooses the adjective that lands in harness chrome, which is §3.4's objection one field over.
- **Fix:** Keep `severity` and make it harness-derived: `EscalationCategory::severity() -> Severity` with `Severity::{Critical, Normal}` and `Severity::interrupts()`. One model-chosen input (`category`, adjudicated), one derivation chain, three consumers preserved verbatim — §3.2's sentence renders `severity.as_str()`, §9.1 A7 stays literally "severity-gated", and `Event::Escalation { interrupt }` reads `interrupts()`. Store it nowhere; expose `Escalation::severity(&self)` so there is no second copy. Cite the DECISIONS entry when raising it.

### `Lineage.external_sources` is a second answer to "what has this run read", and the design admits it enforces nothing. The journal already records every `finish_call` with its result's trust class. A monotonic counter on `Run` can disagree with the journal across a turn boundary — `crates/marlowe-daemon/tests/layer3_refuses_a_composed_target_from_an_ingested_belief.rs`'s own header names "a turn boundary rebuilds `Run::root`" as a blocker.

- **Why:** Axis 6, the project's most-logged shape, on a field the design's own risk list calls "the weakest field in the design". A field whose stated Session-C readers are `--dev` and a report script is a declaration with a delay fuse.
- **Fix:** Cut it. `Lineage { floor }` only. When §3.6's provenance line lands, derive the count from the journal at render time — one definition, and it survives a `Run::root` rebuild.

### `tools/a8_report.py`'s mixed-arm refusal is a self-check whose input is the object it checks (#19), and its failure mode is silence. If `upward_shape` stops being emitted, every row in a cell carries the same value — absent — and the check sees one arm and passes, printing a plausible rate. The design's own risk list half-notices this and proposes "the report should assert that constructor count", which is itself a grep over the object being checked.

- **Why:** REDTEAM pass 1's primary evidence would be a complete, plausible, wrong table — hazard form 6 aimed at a security measurement.
- **Fix:** Pin the expected set outside the data: `a8_report.py --run <dir> --expect-arms typed,validated_sentence,free_text` refuses a cell whose rows carry no `upward_shape` key at all, refuses a cell carrying two, and refuses a sheet missing any expected arm. Membership and count both asserted from a source that is not the journal.

### The wire frame introduces spellings with no named producer, and `Event` derives `Deserialize` (`protocol.rs:217`). The proposed frame carries `category: String`, `shape: String`, `note_kind: String` — and while `UpwardShape::as_str` is named as the one producer of `shape`, nothing produces `category` (no `EscalationCategory::as_str` is proposed) and `note_kind`'s four literals "none|validated|unvalidated|principal" are inline in protocol.rs with no producer at all.

- **Why:** A hand-written `format!("{category:?}")` in daemon.rs and serde's `rename_all = "snake_case"` give two spellings of one enum. #12-adjacent on the way back in: the wire is the outside-input path and it routes around `UpwardShape::parse`.
- **Fix:** Give every enum on the wire an `as_str` in `upward.rs` and derive the serde spelling from it in a round-trip test (`for v in ALL { assert_eq!(to_value(v), json!(v.as_str())) }`). Make `note_kind` a real enum with its own `as_str`. Nothing in `daemon.rs` formats an enum with `{:?}`.

### The `types` block does not compile as written, and the cost of the `Engine` field is understated. `#[derive(Serialize)]` and `thiserror::Error` are used with no `use serde::Serialize;` in the shown import list. `ExtensionEvidence { exhausted: Option<Dimension> }` derives `Serialize`, but `Dimension` is `pub struct Dimension(pub &'static str)` at `budget.rs:86` with no `Serialize` derive — and `PauseReason::BudgetExhausted { dimension: String }` already establishes the spelling. `Engine::new` has 30 call sites across the workspace (1 production at `daemon.rs:2085` — not 2069 — and 29 tests); a seventh positional parameter is a 29-file mechanical sweep in which the arm is chosen by whoever runs sed, which is the "control that arrives by default" hazard displaced rather than removed.

- **Why:** Minor individually, but the design is what gets built, and a `Serialize` on a non-Serialize type is a build break at the exact seam the session is judged on.
- **Fix:** Import serde; store `exhausted: Option<String>` matching `PauseReason`; give `Engine` a private `upward_shape` set by `Engine::new`'s new final parameter, with the 29 test sites passing `UpwardShape::Typed` explicitly and a grep-backed test asserting exactly one non-test site passes anything else.

### Citation drift, and one enum conflation. `daemon.rs:2776` is actually 2899; `Engine::new` is `daemon.rs:2085`, not 2069. `CONTRACTS.md` §13 ("Surfaces") pins `TurnEvent`, not `protocol::Event` — `TurnEvent` has `Done { spend, elapsed, fill_pct }` and no `detail` field at all, so "§13 gains `Event::Escalation`" and "`Event::Done`'s `detail` documentation must record …" describe a type that section does not contain.

- **Why:** "Five of the seven line citations in Session C's own row had drifted" is the head of this branch's log. And the `Done.detail` claim is vacuous besides: the only run that reaches `daemon.rs:2899` is `Run::root`, so "`Done.detail` no longer carries model prose for any run with a parent" is already true and changes nothing.
- **Fix:** Cite by symbol and file, not by line. If `protocol::Event` is to be pinned, pin it in a new §13.1 that names it as the daemon wire enum and states its relationship to `TurnEvent`.

## STRENGTHENED — WHAT GETS BUILT

# The upward channel — Session C, corrected

## The one-line change of intent

A8 varies **`Engine::spawn`'s note**, the only place a child's words cross into a parent, because that is where `REDTEAM-SESSION.md` §4 pass 1 says the attack surface is ("the condensed summary re-entering a parent at `AgentInferred`, and the typed upward channels C ships"). The root→user hop is not an upward hop — `Run::root` has `parent: None` and speaks to its own principal — and it is left exactly as it is.

---

## 1. New file: `crates/marlowe-loop/src/upward.rs` (not §13-guarded)

```rust
use serde::Serialize;
use marlowe_contract::TrustClass;
use crate::run::{Run, RunId};
use crate::driver::AskRequest;

/// M3-DESIGN §9.1 arm A8. No `Default`, no `unwrap_or`: every construction site names an arm.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpwardShape { Typed, TypedPlusValidatedSentence, FreeText }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UnknownShape;

impl UpwardShape {
    pub const ALL: [UpwardShape; 3] =
        [Self::Typed, Self::TypedPlusValidatedSentence, Self::FreeText];
    /// The ONE producer of the string the journal row and the report cell carry.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Typed => "typed",
            Self::TypedPlusValidatedSentence => "validated_sentence",
            Self::FreeText => "free_text",
        }
    }
    /// Total, with an error arm. An unrecognised value REFUSES; it never falls back to `Typed`.
    /// A mistyped arm that silently measures the product under the control's label is the
    /// failure this session exists to detect.
    pub fn parse(s: &str) -> Result<Self, UnknownShape> {
        let k = s.replace('-', "_");
        Self::ALL.iter().copied().find(|v| v.as_str() == k).ok_or(UnknownShape)
    }
}

/// §2.3's closed set. Model-nameable except `Unclassified`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationCategory {
    Blocked, ContradictoryBrief, IrreversibleAhead,
    BudgetCeilingReached, IntegritySuspected,
    /// Harness-substituted; `parse` has no arm for it. What a run whose floor blocks composed
    /// targets receives instead of the category it asked for. §2.2 — escalating is speech, the
    /// *urgency* is a target, and only the urgency is refused.
    Unclassified,
}

/// M3-DESIGN §2.3 names `severity`; §3.2 renders it; §9.1 A7 is "severity-gated". All three stand.
/// **HARNESS-DERIVED, NEVER MODEL-CHOSEN** — that is the whole correction. §3.4's objection to the
/// options list, one field over: a compromised top-agent does not pick the adjective that lands
/// inside harness chrome.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity { Critical, Normal }

impl Severity {
    pub fn as_str(self) -> &'static str {
        match self { Self::Critical => "critical", Self::Normal => "normal" }
    }
    /// Reader: `Event::Escalation { interrupt }`.
    pub fn interrupts(self) -> bool { matches!(self, Self::Critical) }
}

impl EscalationCategory {
    /// `Unclassified` is deliberately absent: the substitution is the harness's and must be
    /// unreachable by naming it.
    pub const ALL: [EscalationCategory; 5] = [
        Self::Blocked, Self::ContradictoryBrief, Self::IrreversibleAhead,
        Self::BudgetCeilingReached, Self::IntegritySuspected,
    ];
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Blocked => "blocked",
            Self::ContradictoryBrief => "contradictory_brief",
            Self::IrreversibleAhead => "irreversible_ahead",
            Self::BudgetCeilingReached => "budget_ceiling_reached",
            Self::IntegritySuspected => "integrity_suspected",
            Self::Unclassified => "unclassified",
        }
    }
    /// **THE READER of `category`.** Total; a new variant is a compile error here.
    pub fn severity(self) -> Severity {
        match self {
            Self::IntegritySuspected | Self::IrreversibleAhead => Severity::Critical,
            Self::Blocked | Self::ContradictoryBrief
            | Self::BudgetCeilingReached | Self::Unclassified => Severity::Normal,
        }
    }
    /// Model-facing. Called by `AskRequest::from_args` — the caller that makes this not #16.
    pub fn parse(s: &str) -> Option<Self> {
        let k = s.trim().to_ascii_lowercase();
        Self::ALL.iter().copied().find(|v| v.as_str() == k)
    }
}

/// §3.6's provenance line. `floor` and nothing else in Session C.
///
/// **`external_sources` is deliberately absent.** The journal already records every `finish_call`
/// with its result's trust class; a counter on the `Run` would be a second answer that disagrees
/// across a turn boundary, where `Run::root` is rebuilt. Derive the count at render time when
/// §3.6's window lands.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Lineage { pub floor: TrustClass }

/// §2.3's record. `Serialize` only — no `Deserialize`, no public struct literal, so §12's serde
/// bypass has no door.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Escalation {
    pub run_id: RunId,
    pub category: EscalationCategory,
    /// What the model asked for, beside what it got. A row showing only the granted value cannot
    /// tell "asked for nothing" from "asked and was refused", and the second is the security event.
    pub category_requested: Option<EscalationCategory>,
    pub artifact: Option<ArtifactRef>,
    pub lineage: Lineage,
    /// The root's own question to its principal. `None` for any run with a parent — a child's
    /// question does not cross, and never did (`Engine::spawn`).
    principal_question: Option<String>,
}

impl Escalation {
    /// THE ONLY CONSTRUCTOR.
    pub fn raise(run: &Run, req: &AskRequest, artifact: Option<ArtifactRef>) -> Escalation {
        // AUTHORITY, read once from where ADR-023 latched it. `Lineage` is DERIVED from this same
        // binding, so the number shown and the number enforced are one expression and a caller
        // cannot invert them by handing in a struct.
        let floor = run.trust_floor();
        let category = match req.category {
            Some(c) if !marlowe_permission::blocks_composed_targets(floor) => c,
            _ => EscalationCategory::Unclassified,
        };
        Escalation {
            run_id: run.id,
            category,
            category_requested: req.category,
            artifact,
            lineage: Lineage { floor },
            principal_question: run.parent.is_none().then(|| req.question.clone()),
        }
    }
    pub fn principal_question(&self) -> Option<&str> { self.principal_question.as_deref() }
    /// Derived, never stored — one copy of the fact.
    pub fn severity(&self) -> Severity { self.category.severity() }
}

/// An artifact the USER opens (§2.3). Not `ContentRef`: `grep -rn "struct ContentRef"
/// --include=*.rs crates/` returns nothing — the name is pinned in CONTRACTS §12 and has no Rust
/// implementation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactRef {
    /// `relative` is `ScopedPath::relative()` — harness output from a SUCCESSFUL `PathScope::open`,
    /// never the model's argument string. No `bytes`: nothing reads it and it needs a stat.
    Workspace { relative: String },
    Run(RunId),
}
```

## 2. `crates/marlowe-loop/src/driver.rs` — **§13-GUARDED, EDITED, SEE §7**

```rust
/// Escalate. `question` is a Payload; `category` and `artifact_path` are Targets.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AskRequest {
    pub question: String,
    /// `None` when the model named none OR named one outside the closed set — not a default:
    /// `raise` substitutes `Unclassified` and the row records `requested: null`, so "did not ask"
    /// and "asked and was refused" stay distinct.
    pub category: Option<EscalationCategory>,
    pub artifact_path: Option<String>,
}

impl AskRequest {
    /// Total, and it lives HERE for `SpawnRequest::from_args`'s stated reason: "a second provider
    /// that wrote its own mapping would be a second definition of the contract."
    pub fn from_args(args: &Args, message: &serde_json::Value) -> Self { /* … */ }
}

pub enum ModelStep { /* … */ Ask(AskRequest) }   // was Ask(String)
```

`crates/marlowe-provider/src/ollama.rs:1023` becomes one line with no policy in it — `"ask" => ModelStep::Ask(AskRequest::from_args(args, message)),` — and the openrouter and llamacpp folds route through the same call.

## 3. `crates/marlowe-tools/src/builtin.rs` — the producer (NOT guarded)

`ask`'s registration gains two parameters beside `question`:

```rust
documented("category", ArgumentRole::Target, Text, false,
  "One of: blocked, contradictory_brief, irreversible_ahead, budget_ceiling_reached, \
   integrity_suspected. It decides whether the user is interrupted now or sees this when they \
   next look. Omit it and the harness classifies. A name outside this list is ignored."),
documented("artifact_path", ArgumentRole::Target, Text, false,
  "A path in this workspace for the user to open. It is resolved against your path scope; one \
   that does not open is dropped."),
```

Without this the whole `category` chain is instance #16. `builtin.rs`'s own note records the precedent: `options` was deleted from this manifest because a model that listed them "had them silently dropped on the way to a user who never saw them."

## 4. `crates/marlowe-loop/src/engine.rs` — where A8 actually lives (NOT guarded)

```rust
pub enum LoopOutcome {
    Completed(CondensedResult),
    Paused { reason: PauseReason },
    Escalated(Escalation),
    Cancelled,
    Failed { error: String },
}

pub struct Engine<S: PathScope + Clone> { /* … */ scope: S, upward_shape: UpwardShape }
```

`Engine::new` gains a seventh parameter (no `Default`) and keeps its own `scope` clone beside `Adjudicator::new(scope.clone())`, so **no §13-guarded file is edited to reach the scope**. One production site, `daemon.rs:2085`; 29 test sites pass `UpwardShape::Typed` explicitly. Also update `engine.rs:2322`'s `LoopOutcome::Escalated { .. } => QuarantineRefusal::Escalated` to the tuple form.

**At `ModelStep::Ask` (engine.rs:1236)** — resolve the artifact where the scope and workspace are in hand, then construct:

```rust
ModelStep::Ask(req) => {
    let artifact = req.artifact_path.as_deref().and_then(|p| {
        self.scope.open(run.profile.path_globs(), &self.workspace, p, Access::Read)
            .ok().map(|sp| ArtifactRef::Workspace { relative: sp.relative().to_string() })
    });
    let esc = Escalation::raise(run, &req, artifact);
    self.record(ports, EventKind::ApprovalRequested, run, state, json!({
        "question": req.question,
        "category_granted": esc.category.as_str(),
        "category_requested": req.category.map(|c| c.as_str()),
        "severity": esc.severity().as_str(),
        "floor": esc.lineage.floor,
        "artifact_requested": req.artifact_path,
        "artifact_resolved": esc.artifact,
        "upward_shape": self.upward_shape.as_str(),
    }));
    run.status = RunStatus::Paused { reason: PauseReason::AwaitingAnswer };
    return LoopOutcome::Escalated(esc);
}
```

**AND THE ARM, at `Engine::spawn`'s note match (engine.rs:2910-2947).** This is the change the reviewed design omits and without which A8 measures nothing:

```rust
/// What crossed, and under which arm — ONE value, so a report cell cannot lose track of what
/// produced it. The arm lives beside the bytes, not in a flag somewhere else.
pub struct CrossedNote { pub text: String, pub shape: UpwardShape }

let note = match self.upward_shape {
    // ── ARM (a) TYPED: today's code, byte for byte. `req.contract.validate` then
    //    `result.render()`; every other outcome is a harness constant, including `Escalated`,
    //    whose question is journalled and does not cross. The product default.
    UpwardShape::Typed => self.typed_note(&req.contract, outcome, &child_run, &child_budget),

    // ── ARM (b) TYPED + ONE VALIDATED SENTENCE: arm (a), plus a `headline` field produced by a
    //    QUARANTINED child over the child's own result — `ExposedSet::empty()`,
    //    `EgressPolicy::DenyAll`, `Budget::slice_for_quarantined_read`, the same machinery
    //    `condense_batch` uses, under
    //      OutputContract::structured("one line for the parent",
    //          vec![FieldSpec::line("headline").capped(200)])
    //    FAIL CLOSED: any non-`Completed` validator outcome omits the field entirely.
    UpwardShape::TypedPlusValidatedSentence => { /* … */ }

    // ── ARM (c) FREE TEXT — **THE CONTROL, EXPECTED TO FAIL.** `child_state`'s last assistant
    //    message, verbatim, `validate` NOT called. This DELIBERATELY REOPENS the hole the comment
    //    above closed ("`Escalated { question }` was the worst: a model-written string,
    //    interpolated verbatim, one trust class above its origin"). It exists so §2's invariant
    //    has a vacuity control; it is journalled on every row, announced on the boot line, and it
    //    takes a `DECISIONS.md` entry of its own.
    UpwardShape::FreeText => { /* … */ }
};
```

## 5. `crates/marlowe-daemon/src/protocol.rs`

```rust
Escalation {
    run: String,
    category: String,            // EscalationCategory::as_str — the one producer
    category_requested: Option<String>,
    severity: String,            // Severity::as_str
    interrupt: bool,             // Escalation::severity().interrupts()
    note_kind: String,           // NoteKind::as_str — a real enum, not four inline literals
    note: Option<String>,
    artifact: Option<String>,
    floor: String,
},
```

Nothing in `daemon.rs` formats an enum with `{:?}`. A round-trip test in `upward.rs` asserts `serde_json::to_value(v) == json!(v.as_str())` for every variant of every enum above, so the serde spelling and the `as_str` spelling cannot become two answers.

## 6. Deferred, with the reason named rather than shipped as fields nothing fills

- **The whole §4.1/§4.2 budget-extension record.** `grep -rni "extension|envelope" crates/marlowe-loop/src/` returns zero: no `ModelStep` variant, no tool, no `from_args`. Shipping `BudgetExtension` + `ExtensionReason::max_grants_per_run` + `ExtensionEvidence` without a producer is instance #16 at subsystem scale, and pinning it in CONTRACTS §12 would pin a declaration. It ships when `ModelStep::RequestBudget(BudgetExtensionRequest)`, a `request_budget` registration with `reason` as a Target, and `BudgetExtensionRequest::from_args` ship in the same commit — or it waits, and `STATE.md` says which.
- **`Lineage.external_sources` and §3.6's host/fetched-at citations.** The journal holds the source data; the renderer is §3.6's window, a later session's. Derive at render, do not latch a second counter.

## 7. LOUD — what the human must approve

1. **`crates/marlowe-loop/src/driver.rs` IS §13-GUARDED AND THIS EDITS IT.** `ModelStep::Ask(String)` → `Ask(AskRequest)`, plus a new `AskRequest` and its `from_args`. The hook's own entry for that file says: "THE FILE IS WIDER THAN THE BOUNDARY: it also declares `ModelStep`, `ToolHost`, `ToolBody`, `ClockSource`, `TurnSink`, `ApprovalGate` … READ WHICH TYPE IS BEING CHANGED before approving: if it is not the memory port, this prompt is noise and the honest answer is yes." `MemoryHost` and `ExternalContent` are untouched. No other guarded file is edited — `blocks_composed_targets` (`adjudicate.rs:50`) is `pub` and is called, not modified; `profile.rs`, `provenance.rs` (hook line 117), `taint.rs`, `steer.rs`, `memory.rs`, `mcp.rs`, `pin.rs`, `scope/` and the journal files are untouched.
2. **`severity` STAYS, harness-derived.** This reverses the design under review. Removing it revisits `DECISIONS.md:3319-3321` (2026-08-29), whose quoted record shape contains it, and it would foreclose §9.1's A7 as worded. `EscalationCategory::severity()` keeps §2.3's field, §3.2's rendered sentence and A7 intact while taking the adjective away from the model.
3. **Whether `UpwardShape::FreeText` ships in the RELEASE binary.** It must not be a `cfg` feature — a control on a different artifact measures a different system, the `persona_emission.rs` family — and a CLI flag on the shipped binary is this project's established pattern (`--reranking off`, `--embedder-provider cpu`). But arm (c) is a permanently-available unvalidated upward channel that deliberately reopens a closed laundering path, and that is a posture question, not a measurement one.
4. **Arm (b) needs a model and there is no VRAM for a fourth.** Measured today via `GET /api/ps`: 14,993 MiB used, **1,053 MiB free**, with the desktop holding 5,086 MiB before any model loaded. `AGENT-DIRECTORY.md` §2's "headroom for the KV cache, the embedder and the reranker" is contradicted by that number, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD — so arm (b) is the arm most likely to push the embedder to CPU mid-measurement with a correct-looking log line. Arm (b)'s cells pin `--embedder-provider cpu`, and `a8_report.py` reads the provider that actually resolved off the boot line, not off the flag. Which of the three named roles validates the sentence — or whether it is the unnamed fourth — is the human's, and is not named here.
5. **SECURITY-AUDIT finding 6 (`remember` and `ask` never reach the adjudicator) stays OPEN and is cited, not claimed.** The narrow `blocks_composed_targets` call inside `raise` buys the one property this session needs — a tainted run cannot choose its urgency — using the same function the adjudicator enforces on, with no edit to `adjudicate.rs`. `Engine::spawn` already sets that precedent (ADR-057 §4). Closing finding 6 properly is a consequence level, a blast radius and a journalled `PermissionDecided` row for `ask`, in a guarded file, and is a session's work.
6. **`SECURITY-AUDIT.md` §8's open question is untouched and must stay that way.** The latch's run-vs-session scope, and ADR-032's identical run-vs-session question about egress grants, are the human's and should be answered together or not at all. Nothing here widens either.

## 8. Tests — each names the mutation that reddens it

| Test | File | Asserts | Mutation |
|---|---|---|---|
| `the_arm_decides_what_crosses_from_a_child` | `crates/marlowe-loop/tests/upward_channel.rs` | ONE test, THREE runs of the identical scripted child through the real `Engine::spawn`. The child emits nonce `BANANA-7Q` in a field its `OutputContract` does **not** declare. Assert on the bytes pushed into the PARENT's `state`: under `Typed` the nonce is in **no byte**; under `FreeText` it **is**; under `TypedPlusValidatedSentence` it is absent and the `headline` field is present. Three arms, three different readings — a build where nothing crosses fails the `FreeText` half. | Make every arm return the `Typed` note → `FreeText` half red. Make `Typed` skip `req.contract.validate` → `Typed` half red. |
| `the_arm_is_visible_in_the_journal_of_the_running_process` | `crates/marlowe-daemon/tests/upward_shape_is_emitted_by_the_running_process.rs` | Launch `target/debug/marlowe.exe --serve --upward-shape free-text`, drive one real spawn whose child emits the nonce, read `tools/read_journal.py --all`: the PARENT's `RunCompleted` payload contains the nonce. Relaunch with `--upward-shape typed`: it does not. **The nonce, not the flag** — this is what stops the row being #15. | Drop the shape match in `Engine::spawn` → the two launches produce identical journals and the test fails by nonce, not by label. |
| `a_tainted_run_cannot_choose_its_escalation_category` | `upward_channel.rs` | A run latched to `UntrustedContent` asks with `category: Some(IntegritySuspected)` → `Unclassified`, `severity() == Normal`, row carries `requested: "integrity_suspected" / granted: "unclassified"`. NEGATIVE CONTROL in the same test: an untainted run gets `IntegritySuspected` and `severity() == Critical`. | Delete the `blocks_composed_targets` guard → tainted half red. Force `Unclassified` unconditionally → control half red. |
| `severity_is_derived_and_moves_the_wire` | `upward_channel.rs` | `Event::Escalation` serialises `severity: "critical", interrupt: true` for `IrreversibleAhead` and `"normal", false` for `Blocked`, read off the JSON frame. Plus: `serde_json::to_value(&Escalation{..})` has **no** `severity` key — derived, not stored, one copy of the fact. | Move `IrreversibleAhead` to the `Normal` arm. Or add a stored `severity` field → the key-set half fails. |
| `the_models_category_actually_reaches_the_loop` | `crates/marlowe-tools/tests/ask_manifest.rs` | Feed a real `/api/chat` tool-call body naming `category: "integrity_suspected"` through `parse_step`; assert `ModelStep::Ask(AskRequest { category: Some(IntegritySuspected), .. })`. NEGATIVE: `category: "banana"` → `None`, and the row reads `requested: null`. **This is the test whose absence makes `EscalationCategory::parse` instance #16.** | Remove the `category` parameter from `ask`'s registration → `Args` drops it and the test reads `None`. |
| `an_artifact_path_outside_the_scope_is_dropped_and_journalled` | `upward_channel.rs` | `artifact_path: "../../etc/passwd"` → `escalation.artifact == None`, row carries `artifact_requested: "../../etc/passwd", artifact_resolved: null`. A path inside the scope resolves to `ScopedPath::relative()`, which is **not** the string the model supplied (assert they differ). | Pass the model's string straight into `ArtifactRef::Workspace` → the row shows a resolved path that never opened, and the differ-assertion fails. |
| `lineage_floor_is_the_runs_latched_floor_and_survives_a_trim` | `upward_channel.rs` | Following `adr023_live.rs`: FIRST assert the emitted §B6 line shows the untrusted block was actually trimmed (an assertion whose subject is "X was removed" carries an assertion that X was removed), THEN `escalation.lineage.floor == run.trust_floor() == UntrustedContent`. | Build `Lineage` from `view.trust_floor()`. It reddens ONLY because the trim occurred, which is why the trim control is the first assertion. |
| `the_root_runs_question_still_reaches_its_principal_under_every_arm` | `upward_channel.rs` | A ROOT run (`parent: None`) asks the nonce question under all three arms; `principal_question()` is `Some` and the nonce is in the emitted frame every time. The typed arm must not mute Marlowe — his channel to his own principal is not an upward hop. | Drop the `run.parent.is_none()` guard → `principal_question` is `None` and the nonce vanishes. |
| `the_shape_flag_has_no_silent_default` | `crates/marlowe/tests/upward_shape_flag.rs` | `marlowe --serve --upward-shape banana` exits 2 naming all three spellings, in `--reranking`'s style (`main.rs:741`). Absent flag → `Typed`, announced on the boot line via `announce::info`. | Replace the refusal with `parse(v).unwrap_or(Typed)` → exits 0, assertion fails. |
| `every_spelling_has_one_producer` | `upward_channel.rs` | For every variant of `UpwardShape`, `EscalationCategory`, `Severity`, `NoteKind`: `serde_json::to_value(v) == json!(v.as_str())`, and `parse(v.as_str())` round-trips. | Change one `as_str` string or one `rename_all` → red by name. |
| `a8_report_refuses_a_cell_it_cannot_label` | `tools/test_a8_report.py` | `python tools/a8_report.py --run <fixture> --expect-arms typed,validated_sentence,free_text` exits non-zero and names the cell when (a) rows in one cell carry two arms, (b) **rows carry no `upward_shape` key at all**, or (c) an expected arm is missing from the sheet. Clean journal → exit 0, three rates, n per cell, and the embedder provider resolved off each run's boot line. | Remove case (b) → a journal with the field deleted reads as one arm and prints a plausible rate, which is #19. **THE NUMERIC TARGET:** `python tools/a8_report.py --run runs/m3-c-a8 --expect-arms typed,validated_sentence,free_text` prints three injection-propagation rates, three n, and a discarded-cell count. |

## 9. Contract and document impact

- **Nothing pinned moves.** `grep -c LoopOutcome docs/design/CONTRACTS.md` → **0**. `grep -n SpawnRequest docs/design/CONTRACTS.md` → one hit, **line 941**, pinning `fn spawn(&self, req: SpawnRequest) -> RunId` — the method, not the shape. §5.1 pins the **quarantined reader's** contract (`source_N` slots); an ordinary child's `OutputContract` arrives on the unpinned `SpawnRequest`, so varying it per arm is legal.
- **CONTRACTS §12 gains `Escalation`, `Lineage`, `ArtifactRef` and nothing else** — the three that have a producer this session. §12's header currently reads "These six are the remainder — five structs below, and the memory port in §12.1"; it is corrected in the same commit, because a stale count in a pinned file is exactly what M3-D2 had to fix last week.
- **A new CONTRACTS §13.1** pins `protocol::Event` as the daemon wire enum and states its relationship to §13's `TurnEvent`. The current §13 pins `TurnEvent`, which has no `detail` field, so "§13 gains `Event::Escalation`" as the reviewed design wrote it describes a type that section does not contain.
- **`DECISIONS.md` takes two entries**, not one: (i) `severity` is retained and made harness-derived, citing the 2026-08-29 narrow entry whose quoted shape contains it; (ii) `UpwardShape::FreeText` deliberately reopens `Engine::spawn`'s laundering path as A8's control, with its ship-in-release status the human's.
- **M3-DESIGN §2.3 and §9.1's A8 row** are amended in place with the arm spellings `typed` / `validated_sentence` / `free_text`, so the document and `UpwardShape::as_str` cannot drift.
- **No `Channel` variant is added and `trust_for_channel` is untouched.** `grep -rn "ingest_external(" --include=*.rs crates/*/src/` stays at exactly two hits, both definitions (`marlowe-daemon/src/memory.rs:542`, `marlowe-loop/src/driver.rs:573`). Layer 3 remains unreachable in the shipped daemon, which is correct (ADR-062). No producer for `Channel::Agent` is proposed — that is Session D's. `a8_report.py` prints the §5 layer tally on its front page so a clean A8 sheet is never read as evidence about layer 3, which is REDTEAM §2's named false pass.

---

## Original recommendation

`LoopOutcome::Escalated { question: String }` becomes `LoopOutcome::Escalated(Escalation)`, a record in a new unguarded module `crates/marlowe-loop/src/upward.rs` whose single constructor `Escalation::raise` is the only way in. **Only one hop is untyped and I am designing only for it**: the child→parent hop was closed at `engine.rs:~2900` (harness constants, question redirected to the journal), the quarantined-reader hop is closed by `OutputContract`/`FieldSpec` (CONTRACTS §5.1), and the untyped hop is run→OUT at `daemon.rs:2776`, where model prose becomes `Event::Done.detail` and then `Entry::Said(Speech::Model(..))` in `project.rs:359`. That hop is *legitimate today* — the only run reaching it is `Run::root`, i.e. Marlowe speaking to his own principal — so the design must not mute it, and the structural discriminator is `Run::parent`: `None` yields `UpwardNote::Principal`, `Some(_)` yields whatever `UpwardShape` allows. **I am removing `severity` from M3-DESIGN §2.3.** Nothing would read it that `category` does not already decide, and two model-chosen dimensions that both answer "how urgent" are two answers to one question; `EscalationCategory::disposition() -> Disposition` is the single reader and the wire's `interrupt` bool changes on it. `artifact_ref` is **not** `ContentRef` — that type has no Rust implementation anywhere in `crates/` (only doc-comment mentions); the only content store is `marlowe-extract`'s `DocumentStore`, scoped to fetched web documents — so it is `ArtifactRef::Workspace { relative, bytes }` where `relative` is `ScopedPath::relative()` produced by a successful harness-side `PathScope::open`, never the model's argument string. `lineage[]` is a **rendering, not a computation**: §3.6's claim that "Layer 2 already computes lineage" is true for beliefs (`MemoryEntry.derivation`) and **false for runs** — `effective_trust` reduces to a class and `Provenance` is a per-argument map, neither of which is a source list — so Session C ships `Lineage { floor, external_sources }` only, `floor` read straight off `Run::trust_floor()` and `external_sources` latched at `finish_call` on the `blocks_composed_targets` predicate. Host/time citations are deferred with the reason named rather than shipped as fields nothing fills.

### Types

```rust
// ─────────────────────────────────────────────────────────────────────────────
// NEW FILE: crates/marlowe-loop/src/upward.rs   (not §13-guarded)
// M3-DESIGN §2.3 and §4.1. Re-exported from lib.rs beside `LoopOutcome`.
// ─────────────────────────────────────────────────────────────────────────────
use marlowe_contract::TrustClass;
use crate::budget::{Budget, Dimension};
use crate::run::{Run, RunId};

/// M3-DESIGN §9.1 arm A8. **Deliberately no `Default` impl and no `unwrap_or`.**
/// Every construction site must name an arm, so adding this parameter is a compile
/// error at each site rather than a value silently inherited. Instance #16's cheapest
/// preventative: a control that arrives by default is a control nobody selected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpwardShape {
    /// Arm (a). No model text crosses at all.
    Typed,
    /// Arm (b). One quarantine-validated line.
    TypedPlusValidatedSentence,
    /// Arm (c). **THE CONTROL, EXPECTED TO FAIL.** REDTEAM-SESSION §3.1 calls this
    /// "the vacuity control for the entire §2 invariant".
    FreeText,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UnknownShape;

impl UpwardShape {
    /// The ONE producer of the string a journal row and a report cell carry. There is
    /// no second spelling anywhere: `tools/a8_report.py` matches these exact bytes.
    pub fn as_str(self) -> &'static str {
        match self {
            UpwardShape::Typed => "typed",
            UpwardShape::TypedPlusValidatedSentence => "validated_sentence",
            UpwardShape::FreeText => "free_text",
        }
    }
    /// Total, with an error arm. An unrecognised value is a REFUSAL, never a fall back
    /// to `Typed` — a mistyped arm that silently measures the product under the
    /// control's label is the failure this whole session exists to detect.
    pub fn parse(s: &str) -> Result<Self, UnknownShape> {
        match s {
            "typed" => Ok(UpwardShape::Typed),
            "validated_sentence" | "validated-sentence" => Ok(UpwardShape::TypedPlusValidatedSentence),
            "free_text" | "free-text" => Ok(UpwardShape::FreeText),
            _ => Err(UnknownShape),
        }
    }
}

/// §2.3: "a category comes from a closed set."
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationCategory {
    Blocked,
    ContradictoryBrief,
    IrreversibleAhead,
    BudgetCeilingReached,
    IntegritySuspected,
    /// **Harness-substituted and NOT model-nameable** — `parse` has no arm for it.
    /// What a run whose floor blocks composed targets receives instead of the category
    /// it asked for. ADR-023 applied without closing the channel: the escalation still
    /// happens, the tainted run just does not get to choose whether a human is
    /// interrupted. §2.2 is explicit that "escalating is speech, not a target"; the
    /// *urgency* is a target, and only the urgency is refused.
    Unclassified,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    /// The human is pulled off what they were doing.
    Interrupt,
    /// The human sees it when they look. **The run is `Paused { AwaitingAnswer }` either
    /// way** — disposition decides attention, never whether work proceeds.
    Queue,
}

impl EscalationCategory {
    /// **THE READER OF `category`, and the whole reason the enum is closed.**
    /// Total match; a new variant is a compile error here.
    pub fn disposition(self) -> Disposition {
        match self {
            EscalationCategory::IntegritySuspected
            | EscalationCategory::IrreversibleAhead => Disposition::Interrupt,
            EscalationCategory::Blocked
            | EscalationCategory::ContradictoryBrief
            | EscalationCategory::BudgetCeilingReached
            | EscalationCategory::Unclassified => Disposition::Queue,
        }
    }
    /// Model-facing spelling. **No `Unclassified` arm**: the substitution is the
    /// harness's and must be unreachable by naming it.
    pub fn parse(s: &str) -> Option<Self> { /* five arms; None otherwise */ }
}

/// The ONE free-text slot. The arm lives in the VARIANT, not in a flag beside it, so a
/// report cell cannot lose track of what produced it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UpwardNote {
    /// Arm (a).
    None,
    /// Arm (b). `FieldType::Line`, `<= NOTE_MAX_CHARS`, produced by a QUARANTINED child
    /// under an `OutputContract` — never by the escalating run itself.
    Validated(String),
    /// Arm (c) ONLY. Constructed nowhere else.
    Unvalidated(String),
    /// The permanent conversational run speaking to its own principal. `parent: None`
    /// means there is no level between this run and the user for prose to launder
    /// through, so §2 does not reach it. **A distinct variant from `Unvalidated` on
    /// purpose**: the product's ordinary behaviour and A8's control must never render
    /// as the same cell.
    Principal(String),
}

pub const NOTE_MAX_CHARS: usize = 200;

/// An artifact the USER opens (§2.3: "an artifact is a path the user opens").
///
/// **Not `ContentRef`.** CONTRACTS §2 pins that type; no Rust `struct ContentRef` exists
/// in `crates/` — the only content store is `marlowe_extract::store::DocumentStore`,
/// scoped to fetched web documents and holding no agent work product.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactRef {
    /// `relative` is `ScopedPath::relative()` — what a SUCCESSFUL `PathScope::open`
    /// returned, harness output rather than the model's argument. `bytes` is measured
    /// off the open handle. A path that does not open is dropped and journalled; it is
    /// never echoed back as a string a client would re-resolve.
    Workspace { relative: String, bytes: u64 },
    /// The run itself: `/watch <id>`. No file needed.
    Run(RunId),
}

/// §3.6's provenance line. **A RENDERING of what the `Run` already owns.**
///
/// Two definitions of lineage is this project's most-logged shape, so neither field here
/// is computed a second way. `floor` is `Run::trust_floor()` verbatim — not
/// `ContextView::trust_floor()`, which is exactly the trimmable quantity ADR-023's latch
/// replaced. `external_sources` is latched on the `Run` at `finish_call`, beside the
/// floor and for the same reason: a trim removes a block from the view and must not
/// remove it from the account of what the run has read.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Lineage {
    pub floor: TrustClass,
    pub external_sources: u32,
}

/// §2.3's record: `{ run_id, category, artifact_ref, lineage[] }`.
///
/// **`severity` is absent and its absence is the decision.** See `disposition()`.
///
/// No `Deserialize`. The type crosses outward only, flattened into
/// `protocol::Event::Escalation`; nothing outside this crate constructs one, so §12's
/// serde bypass has no door to route through.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Escalation {
    pub run_id: RunId,
    pub category: EscalationCategory,
    /// What the model asked for, kept beside what it got. A journal row that showed only
    /// the granted value could not distinguish "asked for nothing" from "asked and was
    /// refused" — and the second is the security event.
    pub category_requested: Option<EscalationCategory>,
    pub artifact: Option<ArtifactRef>,
    pub lineage: Lineage,
    note: UpwardNote,
    shape: UpwardShape,
}

impl Escalation {
    /// **THE ONLY CONSTRUCTOR.** `note` and `shape` are private; there is no struct
    /// literal path from outside this module.
    ///
    /// `validator` is the quarantined child that produces arm (b)'s sentence. It is a
    /// `&mut dyn` port rather than something built here so that a test drives the arm
    /// without a model, and so arm (b) reuses `condense_batch`'s existing machinery
    /// (`ExposedSet::empty()`, `EgressPolicy::DenyAll`,
    /// `Budget::slice_for_quarantined_read`) rather than a second one.
    pub fn raise(
        run: &Run,
        req: &AskRequest,
        lineage: Lineage,
        artifact: Option<ArtifactRef>,
        shape: UpwardShape,
        validator: &mut dyn SentenceValidator,
    ) -> Escalation {
        // ── THE CATEGORY IS A TARGET; THE QUESTION IS A PAYLOAD ──────────────────
        // `blocks_composed_targets` is the same function `adjudicate` enforces on and
        // the same trigger `condense_batch` keys on (ADR-039's precedent: key on the
        // class, never on a name). Reading it off `lineage.floor` rather than off
        // `run` a second time is what keeps the displayed floor and the enforced floor
        // ONE quantity — mutate the display and the enforcement changes with it.
        let category = match req.category {
            Some(c) if !marlowe_permission::blocks_composed_targets(lineage.floor) => c,
            _ => EscalationCategory::Unclassified,
        };
        let note = match (run.parent, shape) {
            (None, _) => UpwardNote::Principal(req.question.clone()),
            (Some(_), UpwardShape::Typed) => UpwardNote::None,
            // FAIL CLOSED. A validator that failed, paused or was cancelled yields
            // `None`, never the raw question.
            (Some(_), UpwardShape::TypedPlusValidatedSentence) => validator
                .one_line(&req.question, NOTE_MAX_CHARS)
                .map(UpwardNote::Validated)
                .unwrap_or(UpwardNote::None),
            (Some(_), UpwardShape::FreeText) => UpwardNote::Unvalidated(req.question.clone()),
        };
        Escalation {
            run_id: run.id,
            category,
            category_requested: req.category,
            artifact,
            lineage,
            note,
            shape,
        }
    }

    pub fn note(&self) -> &UpwardNote { &self.note }
    pub fn shape(&self) -> UpwardShape { self.shape }
    /// Reader of `category`. `daemon.rs` calls this to set the wire's `interrupt`.
    pub fn disposition(&self) -> Disposition { self.category.disposition() }
}

pub trait SentenceValidator {
    /// `None` on any non-`Completed` outcome or any contract violation.
    fn one_line(&mut self, question: &str, max_chars: usize) -> Option<String>;
}

// ─────────────────────────────────────────────────────────────────────────────
// §4.1 — the budget-extension record
// ─────────────────────────────────────────────────────────────────────────────

/// **There is no free-text field and there must never be one.** §4.1: a request that
/// genuinely needs prose is not a budget request, it is an escalation, and it takes that
/// path. The absence IS the mechanism — instance #17's lesson stated in the other
/// direction: withhold structurally, never with a counter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BudgetExtension {
    pub run_id: RunId,
    pub amount: Budget,
    pub reason: ExtensionReason,
    pub evidence: ExtensionEvidence,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtensionReason {
    ScopeLargerThanEstimated,
    RetryAfterFailure,
    SourceSetExpanded,
}

impl ExtensionReason {
    /// **THE READER of `reason_code`.** How many times one run may be extended for this
    /// reason before the request stops being a budget request and becomes an escalation
    /// (`EscalationCategory::BudgetCeilingReached`).
    ///
    /// **Every value is >= 1, and that is instance #17 written into a table.** The check
    /// is `granted_so_far >= cap`; a cap of 0 would refuse the FIRST request while
    /// reading like documentation of "may not extend".
    pub fn max_grants_per_run(self) -> u32 {
        match self {
            ExtensionReason::RetryAfterFailure => 1,
            ExtensionReason::ScopeLargerThanEstimated => 2,
            ExtensionReason::SourceSetExpanded => 3,
        }
    }
    pub fn parse(s: &str) -> Option<Self> { /* three arms; None otherwise */ }
}

/// **Harness-computed, every field.** §3.4's argument applied to numbers instead of an
/// options list: evidence a model writes is not evidence. A model has no way to name a
/// journal `Seq`, and a field it could fill would be the thing a compromised agent
/// forges first.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ExtensionEvidence {
    pub granted: Budget,
    pub spent: Budget,
    pub exhausted: Option<Dimension>,
    pub steps: u32,
    pub children_completed: u32,
    pub children_failed: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ExtensionRefused {
    #[error("this run has already been extended {granted} time(s) for `{reason:?}`, and the cap \
             is {cap}. A further request is an escalation, not a budget request (§4.1)")]
    ReasonCapReached { reason: ExtensionReason, granted: u32, cap: u32 },
    #[error("an extension of {want} tokens would take this run to {would_be}, past the \
             pre-authorised envelope of {ceiling}")]
    PastEnvelope { want: u64, would_be: u64, ceiling: u64 },
}

// ─────────────────────────────────────────────────────────────────────────────
// CHANGES TO EXISTING FILES
// ─────────────────────────────────────────────────────────────────────────────

// crates/marlowe-loop/src/engine.rs  (NOT §13-guarded)
pub enum LoopOutcome {
    Completed(CondensedResult),
    Paused { reason: PauseReason },
    /// `ask`. **A record, not a paragraph** (M3-DESIGN §2.3). The run does not hold a
    /// channel open; it resumes on an answer.
    Escalated(Escalation),
    Cancelled,
    Failed { error: String },
}

// engine.rs: Engine gains one field, named at its single production construction site
// (daemon.rs:2069). No Default, so the arm is always chosen explicitly.
pub struct Engine<S: PathScope> { /* … */ upward_shape: UpwardShape }

// ── §13-GUARDED FILE — crates/marlowe-loop/src/driver.rs — SEE `guarded_files` ──
/// Escalate. **`question` is a Payload; `category` and `artifact_path` are Targets** —
/// they choose whether a human is interrupted and what the human opens.
pub struct AskRequest {
    pub question: String,
    /// `None` when the model named none OR named one outside the closed set. **Not a
    /// default**: `raise` substitutes `Unclassified` and the journal row records
    /// `requested: null`, so "did not ask" and "asked and was refused" stay distinct.
    pub category: Option<EscalationCategory>,
    pub artifact_path: Option<String>,
}
pub enum ModelStep { /* … */ Ask(AskRequest) }   // was Ask(String)

// crates/marlowe-loop/src/run.rs  (NOT §13-guarded)
impl Run {
    /// Latched beside `trust_floor`, incremented at `finish_call` when a tool result's
    /// class satisfies `blocks_composed_targets`. Monotonic; a trim cannot lower it.
    pub fn external_sources(&self) -> u32;
    pub fn note_external_source(&mut self);
    /// Cumulative, per reason. `BTreeMap`, not `HashMap` — banned under `crates/`.
    pub fn request_extension(&mut self, ext: &BudgetExtension, ceiling: &Budget)
        -> Result<(), ExtensionRefused>;
}

// crates/marlowe-daemon/src/protocol.rs
/// One escalation, in full. **`Done.detail` no longer carries model prose for any run
/// with a parent** — this is the carrier, and `interrupt` comes from
/// `Escalation::disposition()`.
Escalation {
    run: String,
    category: String,
    category_requested: Option<String>,
    interrupt: bool,
    /// Emitted by the RUNNING process. The A8 report reads this, never the launch script.
    shape: String,
    note: Option<String>,
    note_kind: String,          // "none" | "validated" | "unvalidated" | "principal"
    artifact: Option<String>,
    floor: String,
    external_sources: u32,
},
```

### Enforcement sites

- `UpwardShape (the A8 arm selector)` -> **crates/marlowe-loop/src/upward.rs :: Escalation::raise — the (run.parent, shape) match** | breaks: All three arms collapse to one behaviour. `a_typed_escalation_carries_none_of_the_models_question` goes red on its FreeText half (the nonce stops appearing) or its Typed half (the nonce starts appearing), depending on which arm survives. There is no build in which both halves pass without this match.
- `EscalationCategory (closed enum)` -> **crates/marlowe-loop/src/upward.rs :: EscalationCategory::disposition, called from crates/marlowe-daemon/src/daemon.rs :: ask_streaming_with when building Event::Escalation { interrupt }** | breaks: `interrupt` becomes a constant on the wire. `disposition_is_read_and_changes_the_wire` goes red: IrreversibleAhead and Blocked emit the same frame. This is the #16 defence for the field — a line of code reads it and an observable byte changes.
- `Escalation.category_requested` -> **crates/marlowe-loop/src/engine.rs — the EventKind::ApprovalRequested payload ({"requested": …, "granted": …}); tools/a8_report.py counts substitutions per arm** | breaks: The journal can no longer distinguish 'asked for nothing' from 'asked for IntegritySuspected and was refused because the floor had latched'. The second is the security event and it becomes invisible. `a_tainted_run_cannot_choose_its_escalation_category` asserts both halves of the row.
- `Lineage.floor` -> **crates/marlowe-loop/src/upward.rs :: Escalation::raise — `blocks_composed_targets(lineage.floor)` is the substitution guard, deliberately reading the DISPLAYED field rather than calling run.trust_floor() a second time** | breaks: The one-definition property goes with it: the number shown to the human and the number that refused the category become two quantities that can disagree. Hardcode `lineage.floor = UserAsserted` and `a_tainted_run_cannot_choose_its_escalation_category` goes red — the tainted run gets IntegritySuspected.
- `Lineage.external_sources` -> **tools/a8_report.py (per-arm covariate) and crates/marlowe/src/dump.rs under --dev. IN SESSION C IT ENFORCES NOTHING — stated rather than hidden; its enforcement site is §3.6's escalation-window provenance line, which is a later session's** | breaks: Nothing in the product. This is the weakest field in the design and I am naming it as such. It is kept because it has a real producer (Run::note_external_source at finish_call) and a real test with a negative control, not because anything gates on it.
- `Escalation.artifact (ArtifactRef)` -> **crates/marlowe-loop/src/upward.rs :: Escalation::raise resolves it through PathScope::open before construction (the write-side enforcement); read-side in Session C is crates/marlowe/src/dump.rs and tools/a8_report.py only** | breaks: The resolution is the enforcement, not the render: `an_artifact_path_that_does_not_open_is_dropped_not_echoed` goes red if raise stops calling PathScope::open and passes the model's string through. Like external_sources, its DISPLAY reader is the escalation window and arrives later — I am flagging this rather than letting a later session discover it.
- `Escalation.note / UpwardNote` -> **crates/marlowe-daemon/src/daemon.rs — Event::Escalation { note, note_kind }; tools/a8_report.py — the dependent variable of arm A8** | breaks: A8 has no measurable output. The whole arm becomes unrunnable, which REDTEAM-SESSION §3.1 calls losing 'the vacuity control for the entire §2 invariant'.
- `Escalation.shape (private, journalled)` -> **crates/marlowe-loop/src/engine.rs — ApprovalRequested payload `"upward_shape"`; tools/a8_report.py groups cells by it and REFUSES a cell whose rows carry more than one value** | breaks: A cell's arm would be known only from the launch command. A mislabelled run then produces a complete, plausible number that is simply wrong — hazard form 6 aimed at a security measurement. `every_escalation_row_names_its_arm` reads it out of the journal of the RUNNING process, not the source.
- `ExtensionReason (reason_code)` -> **crates/marlowe-loop/src/upward.rs :: ExtensionReason::max_grants_per_run, called from crates/marlowe-loop/src/run.rs :: Run::request_extension** | breaks: Extensions become uncapped per reason and a non-converging retry loop can extend forever. `a_second_retry_extension_becomes_an_escalation` goes red. Without this reader `reason_code` would be instance #16 exactly — a closed enum on a record that nothing consults.
- `BudgetExtension.amount` -> **crates/marlowe-loop/src/run.rs :: Run::request_extension, checked against the envelope ceiling; refuses by name with BOTH numbers, matching Budget::grant's existing GrantRefused::MoreThanRemains style** | breaks: §4.2's envelope stops bounding anything and every extension reaches the user. `an_extension_past_the_envelope_is_refused_by_name` goes red.
- `ExtensionEvidence (all six fields)` -> **crates/marlowe-daemon/src/daemon.rs — the §4.2 in-envelope announcement string; and the ApprovalRequested/RunPaused journal payload** | breaks: The announcement becomes 'the run wants more budget' with no numbers, which is what §4.2 warns produces an interruption the user learns to click through.
- `INVARIANT: no free-text field on BudgetExtension` -> **crates/marlowe-loop/tests/budget_extension.rs :: an_extension_request_has_no_place_to_put_a_sentence — pins the JSON key set literally, independently of the type being checked** | breaks: §4.1's routing rule silently reverses: a request needing prose stops becoming an escalation and carries the prose instead. Pinning the key set OUTSIDE the object is the #19 discipline — a check that iterated the struct's own fields could not see a field added.
- `INVARIANT: severity does not exist` -> **nothing — that is the finding. M3-DESIGN §2.3 specifies it; no consumer in §3, §4, §9 or CONTRACTS reads it that `category` does not already decide** | breaks: n/a — it is removed. Retaining it is the defect: a second model-chosen urgency dimension beside `category` is two answers to one question, and §3.2's rendered sentence ('a `critical` escalation') would put an attacker-chosen adjective inside harness chrome. `disposition()` produces the harness's own words instead.

### Rejected

- **Keep `severity` as a field on the record, as M3-DESIGN §2.3 literally specifies.** - Instance #16 by construction. A grep for readers returns the definition, the constructor, and a test asserting the field's value — the exact shape of `inline_threshold_bytes`. Worse, the only plausible reader (does this interrupt the human) is the same decision `category` already forces, so shipping both is two model-chosen dimensions that can disagree, with a green test on each. And §3.2's proposed rendering — 'A `critical` escalation has been raised' — puts an adjective a compromised top-agent chose inside harness chrome, which is §3.4's own objection to the options list applied one field over.
- **Make `artifact_ref` a `ContentRef` (CONTRACTS §2) and put the escalation's detail in the content store.** - `ContentRef` has no Rust implementation. `grep -rn "struct ContentRef" --include=*.rs crates/` returns nothing; the eight `ContentRef` hits under `crates/*/src/` are all doc comments. The only content store that exists is `marlowe_extract::store::DocumentStore`, which is scoped to FETCHED WEB DOCUMENTS (its own header says a `DocumentRef` deliberately carries no title, description or snippet) and holds no agent work product. Choosing it would mean building a general content store inside Session C, which is not this session's scope. `ScopedPath::relative()` needs nothing new and reuses the one machinery that already answers 'is this path inside what this run may touch'.
- **Compute `lineage[]` fresh at escalation time from the `ContextView` — count the blocks whose class is at or below `UntrustedContent`.** - It is the ADR-023 hole in counting form. `ToolResults` is trimmable, so the assembler dropping a block to stay in budget would lower the count — the same reason `Run::latch_trust_floor` exists and the same reason `provenance.rs` takes `latched` as a parameter rather than deriving it. A count that shrinks when the window shrinks is a second, disagreeing definition of what the run has read, which is the shape this project logs most often. `external_sources` is therefore latched on the `Run` at `finish_call`, monotonic, beside the floor.
- **Select the A8 arm with a Cargo feature flag (`--features free-text-upward`) or `#[cfg(test)]`.** - The control would then measure a different binary from the product. That is precisely the family `persona_emission.rs` fell into — a test on the source cannot see a stale deployment — and REDTEAM-SESSION §3 says the control is only worth running if it is the same path. A CLI flag on the shipped binary gives three invocations of one artifact, which is what `--reranking off` and `--embedder-provider cpu` already establish as this project's pattern.
- **Select the arm with an environment variable (`MARLOWE_UPWARD_SHAPE`), like `MARLOWE_DUMP_BODY`.** - CLAUDE.md's own §4.0.9 note records that `MARLOWE_CUDA_LIB_DIR` does not survive a harness spawn because `minimal_env()` is a fixed allowlist — so an env-var arm would silently fall back to the product default under exactly the harness that runs the red-team set, and every cell would be labelled by a launch script that had no effect. A flag is argv and argv is what the harness controls.
- **Route `ask` through the full adjudicator so `category` gets a proper permission decision (SECURITY-AUDIT finding 6).** - Finding 6 is an OPEN entry in the standing ledger and re-deriving it as new is the error a previous session already made. Closing it means `ask` acquires a `CapabilityManifest` consequence level, a blast radius, an approval path and a journalled `PermissionDecided` row — a session's work, in `adjudicate.rs`, which is §13-guarded. Calling `blocks_composed_targets` directly from `raise` buys the one property this decision needs (a tainted run cannot choose its urgency) using the same function the adjudicator enforces on, with no edit to a guarded permission file. Finding 6 stays open and I am citing it, not claiming it.
- **Add a `LoopOutcome::AskedUser { question }` variant so the root's conversational ask is structurally separate from an agent escalation.** - It reads cleaner and it costs a match arm at every one of the ~20 `LoopOutcome` sites plus the daemon and the child-return path. `UpwardNote::Principal` gets the same structural separation inside the one constructor that already has `run.parent` in hand, and it keeps the discriminator in the place a reviewer looks — `Escalation::raise`'s match — rather than spread across every match site in the workspace. Recorded rather than dismissed: if a later session finds `Principal` being constructed for a child, the variant split is the fix.
- **Put `UpwardShape` on `CapabilityProfile`, where the load-time validating constructor would enforce it per run.** - `profile.rs` is §13-guarded and the profile is where CAPABILITIES live, not where measurement settings live. Adding an arm selector there would make every A8 run an edit to a guarded security type, and `CapabilityProfile::new`'s invariant (`reads_untrusted ⟹ DenyAll`) has nothing to say about it. The engine is the right owner: it already holds `tier`, which is the same kind of per-process policy input.

### Tests

- `a_typed_escalation_carries_none_of_the_models_question` in `crates/marlowe-loop/tests/upward_channel.rs`
  - asserts: A scripted driver on a CHILD run (parent: Some) emits `ask` with a question containing the nonce `BANANA-7Q`. Under `UpwardShape::Typed`, the nonce appears in NO BYTE of `serde_json::to_string(&Event::Escalation{..})` — the fate of the bytes, not the value of `note`. THE SAME TEST re-runs the identical driver under `UpwardShape::FreeText` and asserts the nonce IS present. Without that second half the assertion passes on a build where escalation is broken and nothing is emitted at all.
  - red on: In `Escalation::raise`, change the `(Some(_), UpwardShape::Typed)` arm to `UpwardNote::Unvalidated(req.question.clone())` — the Typed half goes red. Independently, make every arm return `UpwardNote::None` — the FreeText half goes red.
- `the_root_runs_own_question_still_reaches_the_user_under_the_typed_arm` in `crates/marlowe-loop/tests/upward_channel.rs`
  - asserts: A ROOT run (parent: None) under `UpwardShape::Typed` asks the nonce question. `escalation.note()` is `UpwardNote::Principal` and the nonce IS in the emitted frame. This is the test that stops the typed arm silently muting Marlowe — the product's conversational channel is not an upward hop.
  - red on: Reorder `raise`'s match so `shape` is examined before `run.parent` (i.e. drop the `(None, _)` first arm) — the root's question becomes `UpwardNote::None` and the nonce vanishes.
- `a_tainted_run_cannot_choose_its_escalation_category` in `crates/marlowe-loop/tests/upward_channel.rs`
  - asserts: A run latched to `UntrustedContent` asks with `category: Some(IntegritySuspected)`; the result is `category == Unclassified`, `disposition() == Queue`, and the journal row carries `requested: "integrity_suspected", granted: "unclassified"`. NEGATIVE CONTROL in the same test: an UNTAINTED run asking for the same category GETS it and `disposition() == Interrupt`. Without the control the first half is green on a build where every category is `Unclassified`.
  - red on: Delete the `blocks_composed_targets(lineage.floor)` guard in `raise` so the model's category is always honoured — the tainted half goes red. Or force `Unclassified` unconditionally — the control half goes red.
- `disposition_is_read_and_changes_the_wire` in `crates/marlowe-loop/tests/upward_channel.rs`
  - asserts: `Event::Escalation` serialises with `interrupt: true` for `IrreversibleAhead` and `interrupt: false` for `Blocked`, read off the JSON frame rather than off `disposition()`'s return value. This is the #16 defence for `category`: a line of code reads it and an observable byte moves.
  - red on: Move `IrreversibleAhead` from the `Interrupt` arm to the `Queue` arm of `EscalationCategory::disposition`.
- `lineage_floor_is_the_runs_latched_floor_and_survives_a_trim` in `crates/marlowe-loop/tests/upward_channel.rs`
  - asserts: Following `adr023_live.rs`'s shape at a window small enough to evict: FIRST assert the emitted §B6 line shows the untrusted block was actually trimmed (the trim-dependent-assertion rule — an assertion whose subject is 'X was removed' carries an assertion that X was removed), THEN escalate and assert `escalation.lineage.floor == run.trust_floor() == UntrustedContent`.
  - red on: Build `Lineage` from `view.trust_floor()` instead of `run.trust_floor()`. It goes red ONLY because the trim occurred, which is why the trim control is the first assertion and not an afterthought.
- `external_sources_counts_reads_and_a_run_with_none_reports_zero` in `crates/marlowe-loop/tests/upward_channel.rs`
  - asserts: After two untrusted tool results, `escalation.lineage.external_sources == 2`. NEGATIVE CONTROL: a run with no tool calls at all reports `0`. The control is the point — instance #15 was a latch that fired on every run that has ever run, and a counter with no zero case reads identically.
  - red on: Call `Run::note_external_source` unconditionally each iteration rather than on `blocks_composed_targets(result_class)` — the zero control goes red with `left: 2, right: 0`.
- `a_second_retry_extension_becomes_an_escalation` in `crates/marlowe-loop/tests/budget_extension.rs`
  - asserts: One `RetryAfterFailure` extension is granted; the second is `Err(ExtensionRefused::ReasonCapReached { cap: 1, granted: 1 })` and the run's outcome is `Escalated` with `category == BudgetCeilingReached`. Paired with `a_first_retry_extension_is_granted`, which is the #17 tripwire.
  - red on: `max_grants_per_run` returning `u32::MAX` reddens this test. `max_grants_per_run` returning `0` reddens its pair — `0 >= 0` refuses the FIRST request while the table reads like documentation. Both mutations must be checked; one test cannot see both.
- `an_extension_request_has_no_place_to_put_a_sentence` in `crates/marlowe-loop/tests/budget_extension.rs`
  - asserts: `serde_json::to_value(&extension)` has exactly the key set `["amount", "evidence", "reason", "run_id"]`, written out literally in the test. The expected set is pinned OUTSIDE the object being checked — a check that iterated the struct's own fields is the #19 shape and could not see a field added.
  - red on: Add `pub note: String` to `BudgetExtension` — the key-set equality fails by name. This is the executable form of §4.1's 'a request needing free text is an escalation'.
- `every_escalation_row_names_its_arm` in `crates/marlowe-daemon/tests/upward_shape_is_emitted_by_the_running_process.rs`
  - asserts: Launch `target/debug/marlowe.exe --serve --upward-shape free-text`, drive one child escalation, then read the journal (`tools/read_journal.py --all`) and assert the `ApprovalRequested` row carries `upward_shape == "free_text"`. THE RUNNING PROCESS EMITS IT — a source-level assertion here would be the `persona_emission.rs` failure repeated on a security measurement.
  - red on: Drop `"upward_shape"` from the `ApprovalRequested` payload in `engine.rs`. Second mutation: launch with `--upward-shape typed` while the test asserts `free_text` — red, which is exactly the mislabelled-arm case `tools/a8_report.py`'s mixed-arm refusal exists for.
- `the_shape_flag_has_no_silent_default` in `crates/marlowe/tests/upward_shape_flag.rs`
  - asserts: `marlowe --serve --upward-shape banana` exits 2 with a message naming all three spellings, in the style of `--reranking`'s refusal block at main.rs:741. An ABSENT flag resolves to `Typed` (the product default) and the boot line announces which arm is active via `announce::info`.
  - red on: Replace the refusal with `UpwardShape::parse(v).unwrap_or(UpwardShape::Typed)` — the process exits 0 and the test's exit-code assertion fails. This is the 'prefer a load-time error to a sensible default' rule as a command that prints a number.
- `a8_report_refuses_a_cell_whose_rows_carry_two_arms` in `tools/test_a8_report.py`
  - asserts: `python tools/a8_report.py --run <fixture>` on a journal whose rows mix `typed` and `free_text` inside one cell exits non-zero and names the cell. On a clean journal it exits 0 and prints per-arm injection-propagation rate and n. THIS IS THE NUMERIC TARGET: `python tools/a8_report.py --run runs/m3-c-a8` prints three rates and the count of discarded cells.
  - red on: Remove the mixed-arm check — the tool exits 0 and prints a plausible rate for a cell produced by two different channel shapes, which is hazard form 6 aimed at REDTEAM-SESSION's primary evidence.

### Contract impact

**Nothing pinned moves, and that is a measured fact rather than a hope.** `grep -c LoopOutcome docs/design/CONTRACTS.md` returns **0** — `LoopOutcome` is not in CONTRACTS at all. `grep -n SpawnRequest docs/design/CONTRACTS.md` returns exactly one hit, **line 941**, and it pins `fn spawn(&self, req: SpawnRequest) -> RunId` — the method, not the shape. So `LoopOutcome::Escalated`'s change is not a pinned-contract change and needs no human sign-off on that ground. **What IS a contract act, and should be done deliberately in the same commit:** (1) `CONTRACTS.md` §12 ("Loop-boundary types") gains `Escalation`, `Lineage`, `UpwardNote`, `ArtifactRef`, `BudgetExtension`, `ExtensionEvidence` — and §12's header sentence, corrected from "these five" to "these six" only last week by M3-D2, must be corrected again to name the true count. (2) `CONTRACTS.md` §13 (Surfaces) gains `Event::Escalation`, because it is a wire type a client parses; `Event::Done`'s `detail` documentation must record that it now carries model prose **only for a run with `parent: None`**. (3) `CONTRACTS.md` §5's `RunStatus` is unchanged. (4) **No `Channel` variant is added and `trust_for_channel` is untouched** — the 2026-08-29 DECISIONS entry already settled that a typed upward return needs no `Channel` and no trust class, and this design is that object. `ingest_external(` stays at zero non-definition call sites. (5) `DECISIONS.md` needs one entry, because removing `severity` contradicts M3-DESIGN §2.3's literal record and §2.3 is the human's design doc. (6) M3-DESIGN §2.3 and §9.1's A8 row need amending in place with the arm spellings (`typed` / `validated_sentence` / `free_text`) so the document and `UpwardShape::as_str` cannot drift.

### Guarded

['crates/marlowe-loop/src/driver.rs']

### For the human

["**LOUD: `crates/marlowe-loop/src/driver.rs` IS §13-GUARDED AND THIS DESIGN EDITS IT.** `ModelStep::Ask(String)` becomes `ModelStep::Ask(AskRequest)`, and `AskRequest` is a new type in that file. The hook's own entry for this file says most edits to it are ordinary loop work and instructs the approver to READ WHICH TYPE IS BEING CHANGED — the guarded subject is `MemoryHost` and `ExternalContent`, and neither is touched. `ModelStep` is named in that same entry as one of the non-boundary types. The honest answer at the prompt is probably yes, but it is the human's prompt and I am not deciding it. No other guarded file is edited: `adjudicate.rs` is called (`blocks_composed_targets` is already `pub`), not modified; `profile.rs`, `provenance.rs`, `taint.rs`, `steer.rs`, `memory.rs`, `mcp.rs`, `pin.rs`, `scope/` and the journal files are untouched.", "**Removing `severity` from M3-DESIGN §2.3.** §2.3 is the human's design record and it names the field explicitly. My argument is that it is instance #16 and that `category` + a harness-owned `disposition()` covers every consumer, but overruling a named field in a design doc is the human's call, and it forecloses §9.1's A7 'severity-gated' arm as literally worded (A7 would become 'category-gated', which I believe is the same arm with better hygiene).", '**Whether `UpwardShape::FreeText` ships in the RELEASE binary.** I recommend yes, because a control that runs on a different artifact measures a different system — but a permanently-available unvalidated upward channel in a shipped binary is a security posture question, not a measurement question. If the answer is no, the control must still not be a `cfg` feature; the alternative is a signed, journalled, boot-announced dev mode, and that is a different design.', '**Whether `ask` should route through the full adjudicator (SECURITY-AUDIT finding 6, already in the ledger).** I propose the narrow fix — one `blocks_composed_targets` call inside `Escalation::raise` — which buys the property without editing `adjudicate.rs`. Closing finding 6 properly means a consequence level, a blast radius and a journalled `PermissionDecided` row for `ask`, in a §13 file. That is a scoping decision.', "**Where the §4.2 pre-authorised envelope's ceiling lives.** I have designed `Run::request_extension(ext, ceiling)` taking the ceiling as a parameter and left its owner open. Putting it on the `Run` inherits ADR-032's unresolved run-vs-session scope question, which `SECURITY-AUDIT.md` §8 already flags as the human's for the trust-floor latch. The two should be answered together or not at all.", "**The fourth model role is not named here.** Four roles were specified; three are named (`marlowe-dawn:9b-super`, `marlowe-mini:4b-super`, `marlowe-mini:2b`). Arm (b)'s `SentenceValidator` is the natural home for a small quarantined validator, and I am deliberately not naming which model fills it.", "**The meeting utterance's `Channel`** (§5.2) remains the third unresolved consumer of the DECISIONS 2026-08-29 entry. Nothing here touches it."]

### Risks

["**`artifact` and `lineage.external_sources` have no ENFORCING reader in Session C — only `--dev` and the report.** Their display reader is §3.6's escalation-window provenance line, which is a later session's. That is instance #16's shape with a delay fuse: fields that are correct, tested, and gate nothing until the window ships. I am naming it rather than dressing the fields up. The mitigation is that each has a real producer and a test with a negative control (`external_sources == 0` on a run with no tool calls; `PathScope::open` refusing a bad path), so a later session inherits a working field, not a declaration.", "**`lineage.citations` (host + fetched-at, §3.6's checkable provenance) is DEFERRED and the design is weaker for it.** The citation's host lives on the tool call's resolved Target argument and threading it through `finish_call` is real work that belongs with the window that renders it. Shipping the field empty in Session C would be instance #16 in its purest form — a field the harness declares and nothing can fill. The cost is that §3.6's 'the only thing that makes the human's role real' does not arrive in this session.", "**A model-chosen `category` can force an interrupt** by naming `IntegritySuspected` on an untainted run. Bounded rather than closed: the worst case is a spurious interrupt into harness chrome where TERMINATE is always present and harness-rendered. The reverse — a compromised agent choosing `Blocked` to suppress attention — is the more dangerous direction, and the mitigation is structural rather than clever: the run is `Paused { AwaitingAnswer }` regardless of disposition, so under-reporting delays a human's attention and never lets work proceed. §11 already asks for false-escalation rate as a reported number.", "**Arm (b) costs one extra quarantined model call per escalation on a card with 1,053 MiB free.** Measured today via `GET /api/ps`: the three roles hold 10,849,836,070 B against 10,960 MiB free after the desktop's 5,086 MiB, leaving 14,993 MiB used. `AGENT-DIRECTORY.md` §2's claim of 'headroom for the KV cache, the embedder and the reranker' is contradicted by that measurement, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD — so arm (b) is the arm most likely to push the embedder to CPU mid-measurement and silently relabel a timing. Arm (b)'s cells need `--embedder-provider cpu` pinned, and the A8 report should carry the provider that actually resolved, read from the boot line rather than from the flag.", "**The three arms must not be run in one shared checkout while anything builds.** Hazard form 6: a 16-core build inflated a parallel session's timings ~10% and produced a complete, plausible, wrong table. A8's primary metric is a rate rather than a latency, so it is less exposed — but utility retention (REDTEAM §4, '§8.3 reported as ASR AND utility retention') is not, and that half is timing-adjacent.", "**Every taint-class cell taken at pass 1 is still vacuous and this design does not change that.** `ingest_external(` remains at zero non-definition call sites; layer 3 is unreachable in the shipped daemon and correctly so (ADR-062). A8 measures the CHANNEL, not the latch. A report that lets a clean A8 sheet read as evidence about layer 3 is REDTEAM-SESSION §2's named false pass, and `tools/a8_report.py` should print the §5 layer tally on its front page for exactly that reason.", "**Instance #18 risk against my own prescription.** `tools/a8_report.py`'s mixed-arm refusal answers 'did every row in this cell carry the same arm'. That is the same question as 'was this cell produced by one channel shape' only while `upward_shape` is the sole thing that varies the shape. A later session adding a second selector — a per-run override, a profile field, a steer — separates them, and the check goes loud and affirmative. The discriminating property to re-derive at that point is that `Escalation::raise`'s match is the ONLY site reading a shape; the report should assert that constructor count rather than the flag."]
