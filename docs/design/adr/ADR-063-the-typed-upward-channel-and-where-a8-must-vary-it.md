# ADR-063 · The typed upward channel, and where A8 must vary it

**Status:** PROPOSED — needs the human's approval. DESIGN ONLY, NO CODE. (M3 Session C, 2026-08-30)

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | M3-DESIGN §2.3 in two directions — `severity` is **kept** and made harness-derived, `artifact_ref` is **deferred** (§4.3, §4.4). Records M3-DESIGN §9.1's 2026-08-30 A8 amendment as the decision this ADR implements, and names one sentence in it that contradicts §5 of this ADR (§8.3) |
| **Depends on** | ADR-023 (the `(action, target)` latch, and `Run::trust_floor`'s monotonicity), ADR-039 / ADR-041 (the quarantined read and its group unit), ADR-057 (`SpawnRequest::from_args` — the one-definition rule this ADR extends to `ask`), ADR-062 (layer 3 is unreachable in the shipped daemon, which bounds what an A8 sheet may be read as evidence for), M3-DESIGN §2, §3, §9.1, REDTEAM-SESSION §3.1 and §4 |
| **Contract change** | **Yes, and it is small.** `CONTRACTS.md` §12 gains `Escalation` and `Lineage`; a new §13.1 pins `protocol::Event` as the daemon wire enum. `LoopOutcome` is **not** pinned anywhere (`grep -c LoopOutcome docs/design/CONTRACTS.md` → **0**) and `SpawnRequest` is pinned only as a method signature (`CONTRACTS.md:941`, `fn spawn(&self, req: SpawnRequest) -> RunId`), so neither of the two shape changes at the loop boundary is a pinned-contract change. No `EventKind` variant is added. No `Channel` variant is added; `trust_for_channel` is untouched |
| **Code change** | **None yet — this is design.** When built: one new unguarded file (`crates/marlowe-loop/src/upward.rs`), edits to `engine.rs`, `builtin.rs`, `protocol.rs`, `daemon.rs`, `ollama.rs` and the two other provider folds, **and one §13-guarded file — `crates/marlowe-loop/src/driver.rs`** (§7.1) |

---

## 1 · The finding: the first design's three arms would have emitted byte-identical product behaviour

M3-DESIGN §9.1 A8 asks one question — *"upward channel shape: fully typed / typed + one validated
sentence / free text (**control, expected to fail**)"* — and §9.1's own sentence about it is the
reason this ADR exists:

> **A8's third arm is the vacuity control for the entire §2 invariant.** If free-text upward performs
> identically on the red-team set, the typing is decorative and the finding is worth more than the
> feature.

The design this ADR replaces read §2.3 literally, typed `LoopOutcome::Escalated { question: String }`
into a record, and switched the three arms inside that record's constructor on `(Run::parent,
UpwardShape)`. **That is a channel with no traffic on it**, and the reason is one line of already-shipped
code.

### 1.1 · The child→parent hop was closed nine months of commits ago, and the closure is the problem

`Engine::spawn`'s note match begins at `crates/marlowe-loop/src/engine.rs:2910` (`let note = match
outcome {`). The comment immediately above it, at `:2900`, states the rule:

> **The `push` below is outside this match, so EVERY branch crosses at `AgentInferred`.** `validate`
> governs exactly one of them. […] `Escalated { question }` was the worst: a model-written string,
> interpolated verbatim, one trust class above its origin. […] The rule now is that **only a
> validated result carries content**. Everything else is a fixed harness-authored string.

And the `Escalated` arm, at `engine.rs:2936`, does exactly what it says:

```rust
LoopOutcome::Escalated { question } => {
    self.record(ports, EventKind::RunFailed, run, state,
        json!({ "child": child_id.to_string(), "escalated": question }));
    "[child asked a question; a child cannot escalate to the parent's window and its \
     question was not carried across]"
        .to_string()
}
```

So a child's `Escalated` **never reaches `daemon.rs`** and never becomes an outward event. The first
design's discriminator was `run.parent`: `None` → `UpwardNote::Principal` (shape ignored outright),
`Some(_)` → a note computed and then discarded three frames up the stack. `--upward-shape typed` and
`--upward-shape free-text` would have produced identical bytes on every surface.

**A control that cannot vary anything is worse than no control**, because a sheet of three identical
cells reads character-for-character like the positive finding — *"the typing is decorative"* — which
is the finding A8 exists to produce.

### 1.2 · Where the traffic actually is

`REDTEAM-SESSION.md:127` names pass 1's attack surface: *"the condensed summary re-entering a parent
at `AgentInferred`, and the typed upward channels C ships."* That crossing is `req.contract.validate`
then `result.render()` at `engine.rs:2911-2912`, and the push at `engine.rs:3035-3043`:

```rust
let mut returned = Block::new(SourceKind::ChildResults, note, TrustClass::AgentInferred);
…
state.push(returned);
```

`crates/marlowe-loop/src/run.rs:229-247`, the doc comment on `FieldSpec`, says why it is the one that
matters, and it does not oversell itself:

> The contract is the single place where content crosses from `UntrustedContent` to `AgentInferred`
> […] The bandwidth is still not zero and this file will not pretend otherwise — a summary of a page
> is attacker-influenced prose no matter how it is typed.

The first design declared that hop *"closed by `OutputContract`/`FieldSpec` (CONTRACTS §5.1)"* and out
of scope. §5.1 pins the **quarantined reader's** contract — its `source_N` slots — and an ordinary
child's `OutputContract` arrives on `SpawnRequest`, which is unpinned. The hop is neither closed nor
out of scope; it is the hop under test.

### 1.3 · What the first design's two flagship tests would have read

Both are instance #15 — an assertion whose reading is the same whether or not the mechanism works —
and it is worth being exact about which failure each is, because they are different ones.

| Test, as first proposed | What it would actually have measured |
|---|---|
| `every_escalation_row_names_its_arm` | The journal row `upward_shape: "free_text"` is written from the CLI flag at the moment the record is built. **It prints `free_text` on a build where every note is discarded** — which is this build. The row moves with the flag, not with the channel. This is instance #15's exact shape: the trust-floor banner fired on *floor moved* while its text asserted *floor reached untrusted* |
| `a_typed_escalation_carries_none_of_the_models_question` | Its subject — a child's `Escalated` reaching an outward frame — cannot occur, so both halves could only be green over an `Escalation` the test constructs inside its own process. That is the `persona_emission.rs` family (a test on the source cannot see the running process) aimed at a security measurement |

---

## 2 · The decision

**A8's arm varies `Engine::spawn`'s note match — the only place a child's words cross into a
parent — and nowhere else.** The root→user hop is not an upward hop: `Run::root` has `parent: None`
(`run.rs:571`) and speaks to its own principal, so it is left exactly as it is.

### 2.1 · The three arms, at `engine.rs:2910`

```rust
/// The arm travels WITH the bytes it produced, so a report cell cannot lose track of what made it.
pub struct CrossedNote { pub text: String, pub shape: UpwardShape }

let note = match self.upward_shape {
    // ARM (a) TYPED — today's code, byte for byte: `req.contract.validate` then `result.render()`,
    // a harness constant on every non-`Completed` outcome. The product default.
    UpwardShape::Typed => self.typed_note(&req.contract, outcome, &child_run, &child_budget),

    // ARM (b) TYPED + ONE VALIDATED SENTENCE — arm (a) plus one `headline` field produced by a
    // QUARANTINED child over the child's own result: `ExposedSet::empty()`, `EgressPolicy::DenyAll`,
    // `Budget::slice_for_quarantined_read` (budget.rs:278), the same machinery `condense_batch`
    // uses, under `OutputContract::structured("one line for the parent",
    //     vec![FieldSpec::line("headline").capped(200)])`.
    // FAIL CLOSED: any non-`Completed` validator outcome omits the field entirely.
    UpwardShape::TypedPlusValidatedSentence => { /* … */ }

    // ARM (c) FREE TEXT — THE CONTROL, EXPECTED TO FAIL. The child's last assistant message,
    // verbatim, `validate` NOT called. It deliberately reopens the hole `engine.rs:2900` closed.
    UpwardShape::FreeText => { /* … */ }
};
```

The arm is journalled at the site that produced it: one `self.record(ports, EventKind::RunCompleted,
run, state, json!({ "child": …, "upward_shape": …, "note": … }))` beside the push at
`engine.rs:3043`. `RunCompleted` already exists in `CONTRACTS.md` §1.1's closed set, so **no event
kind is added and §1.1 does not move.** The journal is not model-reachable (invariant 8), which is
what makes journalling the free-text note verbatim acceptable — `engine.rs:2939` already journals a
child's full escalated question for the same reason.

### 2.2 · `UpwardShape` — one owner, no default

`crates/marlowe-loop/src/upward.rs`, a new file, **not §13-guarded** (verified:
`python .claude/hooks/protect-boundaries.py --list-protected` lists fifteen entries and no
`marlowe-loop` file but `driver.rs`, `profile.rs`, `provenance.rs` and `steer.rs`).

```rust
/// M3-DESIGN §9.1 arm A8. No `Default`, no `unwrap_or`: every construction site names an arm,
/// so adding the parameter is a compile error at each site rather than a value silently inherited.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpwardShape { Typed, TypedPlusValidatedSentence, FreeText }

pub struct UnknownShape;

impl UpwardShape {
    pub const ALL: [UpwardShape; 3] =
        [Self::Typed, Self::TypedPlusValidatedSentence, Self::FreeText];

    /// The ONE producer of the string a journal row and a report cell carry.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Typed => "typed",
            Self::TypedPlusValidatedSentence => "validated_sentence",
            Self::FreeText => "free_text",
        }
    }

    /// Total, with an error arm. An unrecognised value REFUSES; it never falls back to `Typed`.
    /// A mistyped arm that silently measures the product under the control's label is the exact
    /// failure this session exists to detect.
    pub fn parse(s: &str) -> Result<Self, UnknownShape> {
        let k = s.replace('-', "_");
        Self::ALL.iter().copied().find(|v| v.as_str() == k).ok_or(UnknownShape)
    }
}
```

It is stored on `Engine`, set by a new final parameter to `Engine::new`. **The count, corrected:**
`grep -rn "Engine::new(" --include=*.rs crates/` returns **30** sites — **1 production**
(`crates/marlowe-daemon/src/daemon.rs:2085`), **2 examples**
(`crates/marlowe-exec/examples/batch_parallelism.rs:185`,
`crates/marlowe-exec/examples/deep_research_attack.rs:287`) and **27 tests**. The adversarial critique
said *"1 production … and 29 tests"*; the production figure and the line number are right and the
remainder splits 2/27, which matters only because an example is a binary someone runs and a test is
not. Every one of the 29 non-production sites passes `UpwardShape::Typed` explicitly.

### 2.3 · The record, with authority read once

```rust
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]   // Serialize ONLY — no Deserialize, no public
pub struct Escalation {                             // struct literal, so §12's serde bypass has no door
    pub run_id: RunId,
    pub category: EscalationCategory,
    /// What the model asked for, beside what it got. A row showing only the granted value cannot
    /// tell "asked for nothing" from "asked and was refused", and the second is the security event.
    pub category_requested: Option<EscalationCategory>,
    pub lineage: Lineage,
    /// The root's own question to its principal. `None` for any run with a parent — a child's
    /// question does not cross, and never did (`engine.rs:2936`).
    principal_question: Option<String>,
}

impl Escalation {
    /// THE ONLY CONSTRUCTOR.
    pub fn raise(run: &Run, req: &AskRequest) -> Escalation {
        // AUTHORITY, read once from where ADR-023 latched it (`run.rs:605`). `Lineage` is DERIVED
        // from this same binding, so the number shown to the human and the number that refused the
        // category are one expression and a caller cannot invert them by handing in a struct.
        let floor = run.trust_floor();
        let category = match req.category {
            Some(c) if !marlowe_permission::blocks_composed_targets(floor) => c,
            _ => EscalationCategory::Unclassified,
        };
        Escalation {
            run_id: run.id,
            category,
            category_requested: req.category,
            lineage: Lineage { floor },
            principal_question: run.parent.is_none().then(|| req.question.clone()),
        }
    }
    pub fn principal_question(&self) -> Option<&str> { self.principal_question.as_deref() }
    /// Derived, never stored — one copy of the fact.
    pub fn severity(&self) -> Severity { self.category.severity() }
}
```

**This reverses the first design's `raise(run_id, req, lineage, …)`.** That signature took `lineage:
Lineage` as a parameter and guarded on `blocks_composed_targets(lineage.floor)`, defending it as
*"deliberately reading the DISPLAYED field rather than calling `run.trust_floor()` a second time"*.
That inverts authority and display: any caller constructing `Lineage { floor: UserAsserted, .. }` — a
test helper, a resume path, §3.6's window renderer when it lands — hands a tainted run its chosen
category back, and no test written against the first design would catch it, because every one of them
constructs `Lineage` honestly. `marlowe_permission::blocks_composed_targets` is `pub` at
`crates/marlowe-permission/src/adjudicate.rs:50` and is **called, not modified**; `Engine::spawn`
already sets that precedent.

### 2.4 · `severity` stays, and is harness-derived

```rust
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
    /// **THE READER of `category`.** Total; a new variant is a compile error here.
    pub fn severity(self) -> Severity {
        match self {
            Self::IntegritySuspected | Self::IrreversibleAhead => Severity::Critical,
            Self::Blocked | Self::ContradictoryBrief
            | Self::BudgetCeilingReached | Self::Unclassified => Severity::Normal,
        }
    }
}
```

The first design deleted `severity` on the ground that nothing reads it. **Both halves of that were
wrong and the correction is made here rather than quietly.** Its words were:

> *"Nothing would read it that `category` does not already decide, and two model-chosen dimensions
> that both answer 'how urgent' are two answers to one question."*

`severity` **is** read: M3-DESIGN §3.2 renders it — *"A `critical` escalation has been raised by
`CodeProjectLeader`"* — and §9.1's A7 arm is named *"severity-gated"*. And deleting it revisits a
settled entry the design never cited. `DECISIONS.md`'s 2026-08-29 entry — *"A NARROW decision on
M3-DESIGN §12 item 5, and the item stays open"* — reads:

> **Decided:** a typed upward return — M3-DESIGN §2.3's `{ run_id, severity, category (fixed enum),
> artifact_ref, lineage[] }` — **needs no `Channel` and no trust class.**

The record shape including `severity` is quoted inside a settled decision, and CLAUDE.md's rule is
*"Decisions in `DECISIONS.md` are settled. Argue explicitly to revisit one; do not quietly design
around it."*

**The defect the first design correctly smelled was not "nothing reads it".** It was that the *model*
would choose the adjective that lands inside harness chrome — M3-DESIGN §3.4's objection to the
attacker-controlled options list, one field over. One model-chosen input (`category`, adjudicated by
the floor), one derivation, three consumers preserved verbatim: §3.2's sentence renders
`severity.as_str()`, A7 stays literally *"severity-gated"*, and the wire's `interrupt` reads
`interrupts()`. Stored nowhere.

### 2.5 · `category` gets a producer, or the whole chain is instance #16

`ask`'s registration at `crates/marlowe-tools/src/builtin.rs:699-717` declares **exactly one**
parameter — `question`, `ArgumentRole::Payload` — and `control_step` at
`crates/marlowe-provider/src/ollama.rs:1023` is:

```rust
"ask" => ModelStep::Ask(text("question").unwrap_or(body)),
```

Without a manifest parameter there is no `Args` entry, so `EscalationCategory::parse` would have zero
callers, `Unclassified` would be the only category the product could ever emit, `severity()` would be
a constant, and `a_tainted_run_cannot_choose_its_escalation_category` would assert on a state the
product cannot enter. `builtin.rs`'s own comment on this exact manifest records the precedent:

> **`options` is gone, for `web`'s `query` reason.** `control_step` reads `question` (falling back to
> the message body) and nothing else, and `ModelStep::Ask` carries a single `String` — so a model
> that listed options had them silently dropped on the way to a user who never saw them.

So `ask` gains one parameter:

```rust
documented("category", ArgumentRole::Target, Text, false,
  "One of: blocked, contradictory_brief, irreversible_ahead, budget_ceiling_reached, \
   integrity_suspected. It decides whether the user is interrupted now or sees this when they \
   next look. Omit it and the harness classifies. A name outside this list is ignored."),
```

`ArgumentRole::Target` is the correct role by `manifest.rs:84`'s own definition — *"tool selection,
recipient, path, host, amount, identifier"* — and it is the role the `(action, target)` split
governs. `ParamType::Text` is right here and not a shortcut: `manifest.rs:96` says *"a parameter whose
type says nothing about enforcement is `ParamType::Text`, and `Text` in a `Target` role is still
provenance-checked; it simply has no second, type-specific wall behind it."* The second wall for
`category` is `raise`'s floor check.

### 2.6 · One definition of what `ask` means, in `driver.rs`

`SpawnRequest::from_args`'s doc at `crates/marlowe-loop/src/driver.rs:103-115` states the rule:

> `SpawnRequest` is defined here and `Engine::spawn` enforces here, so **a second provider that wrote
> its own mapping would be a second definition of the contract** — the two-sides-silently-disagree
> shape this project keeps recording. The adapter's job is to recognise that the model named `run`;
> deciding what a `run` call *means* is the loop's.

Three adapters exist (`ollama.rs`, `marlowe-openrouter`, the llamacpp fold), so three mappings of
`category` would be three answers to *"did the model ask to interrupt the human"*.

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AskRequest {
    pub question: String,
    /// `None` when the model named none OR named one outside the closed set — not a default:
    /// `raise` substitutes `Unclassified` and the row records `requested: null`, so "did not ask"
    /// and "asked and was refused" stay distinct.
    pub category: Option<EscalationCategory>,
}

impl AskRequest {
    /// Total, one rule per field, for `SpawnRequest::from_args`'s stated reason.
    pub fn from_args(args: &Args, message: &serde_json::Value) -> Self { /* … */ }
}

pub enum ModelStep { /* … */ Ask(AskRequest) }   // was Ask(String)
```

`from_args` takes `message` as well as `args` because `control_step`'s `body` fallback
(`ollama.rs:1005-1016`) is what supplies `question` when the model names no field, and that fallback
must not fork per provider either. `ollama.rs:1023` reduces to
`"ask" => ModelStep::Ask(AskRequest::from_args(args, message)),` with no policy in it.

### 2.7 · The wire

```rust
Escalation {
    run: String,
    category: String,                 // EscalationCategory::as_str — the one producer
    category_requested: Option<String>,
    severity: String,                 // Severity::as_str
    interrupt: bool,                  // Escalation::severity().interrupts()
    question: Option<String>,         // Escalation::principal_question() — `None` for any child
    floor: String,
},
```

`protocol::Event` derives `Deserialize` (`crates/marlowe-daemon/src/protocol.rs:217`, enum at `:219`),
which makes the wire an outside-input path: family #12, `serde` as a way in. Every enum crossing it
gets an `as_str`, nothing in `daemon.rs` formats an enum with `{:?}`, and a round-trip test asserts
`serde_json::to_value(v) == json!(v.as_str())` for every variant, so the serde spelling and the
`as_str` spelling cannot become two answers.

**`note` and `note_kind` are NOT on this frame, and `NoteKind` is not created.** The critique's tenth
defect asked for `note_kind`'s four inline string literals to become a real enum with one producer.
That fix is correct about the family and is satisfied by **deletion**: once the arm moved to
`Engine::spawn` (§2.1) the escalation record carries no note at all, so a `NoteKind` enum would be a
type with no producer — instance #16 committed inside the ADR that is auditing for it. What crosses
under an arm is a parent-window fact and is journalled at `engine.rs:3043`; it is not a property of an
escalation frame.

---

## 3 · Where every field is read

Instance #16 is this project's most-repeated defect — *"ask of any control: is there a line of code
that reads it?"* — so every field introduced here is listed with the function that reads it, **or is
dropped**. Six are dropped, and that is the more useful half of the table.

| Field / type | The function that READS it | If the reader is deleted |
|---|---|---|
| `UpwardShape` | `Engine::spawn`'s note match (`engine.rs:2910`), which selects which bytes are pushed at `:3043` | All three arms produce the same parent window; `the_arm_decides_what_crosses_from_a_child` fails on its `FreeText` half by **nonce**, not by label |
| `UpwardShape::as_str` | the `RunCompleted` payload at `engine.rs:3043`; `tools/a8_report.py` groups cells by the exact bytes | A cell's arm is knowable only from the launch command |
| `UpwardShape::parse` | `main.rs`'s flag parse, in `--reranking`'s refusal style (`crates/marlowe/src/main.rs:741`, `std::process::exit(2)`) | A mistyped arm silently measures the product under the control's label |
| `EscalationCategory` | `EscalationCategory::severity()` — total match, a new variant is a compile error | `interrupt` becomes a constant on the wire |
| `EscalationCategory::parse` | `AskRequest::from_args` in `driver.rs`, fed by the new `category` parameter in `builtin.rs` | **This is the caller whose absence makes the whole chain #16** (§2.5) |
| `Severity` / `interrupts()` | `Event::Escalation { interrupt }` in `daemon.rs`; `severity.as_str()` in M3-DESIGN §3.2's rendered sentence | `IrreversibleAhead` and `Blocked` emit the same frame |
| `category_requested` | the `ApprovalRequested` payload at `engine.rs:1236`; `a8_report.py` counts substitutions per arm | The journal can no longer tell *"asked for nothing"* from *"asked for `IntegritySuspected` and was refused because the floor had latched"*, and the second is the security event |
| `Lineage.floor` | `Escalation::raise`'s guard — **derived from `run.trust_floor()` in the same expression that enforces on it** | The number shown and the number enforced become two quantities that can disagree |
| ~~`Lineage.external_sources`~~ | **DROPPED.** The journal already records every `finish_call` with its result's trust class; a monotonic counter on `Run` is a second answer that disagrees across a turn boundary, where `Run::root` is rebuilt (named as a blocker in `crates/marlowe-daemon/tests/layer3_refuses_a_composed_target_from_an_ingested_belief.rs`'s own header). Derive the count at render time when §3.6's window lands | — |
| ~~`Escalation.artifact` / `ArtifactRef`~~ | **DEFERRED — and it cannot be built as the critique specified. See §4.4** | — |
| ~~`Escalation.note` / `UpwardNote` / `NoteKind`~~ | **DROPPED** (§2.7) | — |
| ~~`BudgetExtension`, `ExtensionReason`, `ExtensionEvidence`~~ | **DEFERRED — no producer exists. See §4.5** | — |

---

## 4 · Why the alternatives lost, and what cannot be built as specified

### 4.1 · Rejected: select the arm with a Cargo feature or `#[cfg(test)]`

The control would then measure a different binary from the product. That is the `persona_emission.rs`
family — a test on the source cannot see a stale deployment — and REDTEAM-SESSION §3 only counts a
control that runs the same path. A CLI flag on the shipped binary gives three invocations of one
artifact, which `--reranking off` and `--embedder-provider cpu` already establish as this project's
pattern. **See §8.3: M3-DESIGN's own A8 amendment says the opposite, and the conflict is unresolved
and the human's.**

### 4.2 · Rejected: select the arm with an environment variable

`minimal_env()` in the eval harness (§4.0.9) is a fixed allowlist — the same mechanism that stops
`MARLOWE_CUDA_LIB_DIR` surviving a spawn, which is why `tools/score_longmemeval.py` translates it onto
`PATH`. An env-var arm would silently fall back to the product default under exactly the harness that
runs the red-team set, and every cell would be labelled by a launch script that had no effect. Argv is
what the harness controls.

### 4.3 · Rejected: delete `severity`, as the first design proposed

Covered in §2.4. Recorded rather than deleted because it is the design's largest reversal: the
argument *"nothing reads it"* was checkable and false, and the check is two greps of M3-DESIGN.

### 4.4 · `artifact_ref` is deferred, because BOTH routes to a resolved path go through a §13-guarded file

The critique's fifth defect is right that `Escalation::raise` cannot resolve an `ArtifactRef`:
`PathScope::open` (`crates/marlowe-permission/src/scope/mod.rs:186`) needs `declared: &[PathGlob]`, a
`workspace: &Path` and an `Access`, none of which `raise` has, and `Adjudicator<S>`'s `scope` field is
private at `adjudicate.rs:254-256` with no accessor.

**Its proposed fix does not work either, and this is a finding of this ADR rather than of the
critique.** The fix reads:

> Getting the scope there costs either `pub fn scope(&self) -> &S` on the guarded `Adjudicator`, or an
> `S: PathScope + Clone` bound so `Engine::new` keeps its own handle (**the non-guarded route, and the
> one to prefer**).

`Engine::new` currently moves its `scope` straight into `Adjudicator::new(scope)`
(`engine.rs:531-551`), so `Engine` holds no scope of its own. And the `Clone` route is not
non-guarded: **`WorkspaceScope` does not implement `Clone`** — `crates/marlowe-permission/src/scope/mod.rs:218-224`
is `#[derive(Debug)] pub struct WorkspaceScope { _gated: () }`, and the private field is there on
purpose:

> Zero-sized proof that `WorkspaceScope::new()` ran and the platform check passed. Having a private
> field is what stops `WorkspaceScope {}` being written at a call site, which would be a construction
> that skipped the gate.

`grep -n Clone crates/marlowe-permission/src/scope/mod.rs` returns three hits and none is
`WorkspaceScope`. Adding the derive is an edit to `/marlowe-permission/src/scope/` — a **directory
prefix in `PROTECTED_DIRS`**, guarded since M2 Session A. So both named routes edit a §13 file.

A third route exists and needs no guarded edit: `WorkspaceScope::new()` is already called at four
sites in `daemon.rs` (`:715`, `:905`, `:2071`, `:2484`), so `Engine::new` could take a second,
independently-gated `S`. It is rejected — an eighth positional parameter across 30 call sites, 29 of
which would pass `Unavailable`, which **refuses every path**, so every artifact in every test would
resolve to `None` and the resolution path would have no coverage in any test that did not construct a
real `WorkspaceScope`.

**The correct long-term route is the one that closes an open audit finding.** `Adjudicator::adjudicate`
already resolves `ParamType::Path` parameters and returns `Adjudication { handles: BTreeMap<String,
ScopedPath> }` (`adjudicate.rs:176-180`, resolving at `:343`). Declaring `artifact_path` as
`ParamType::Path, ArgumentRole::Target` and routing `ask` through the adjudicator gives the resolved
handle for free **and** a journalled `PermissionDecided` row — which is exactly
`SECURITY-AUDIT.md` §6, *"`remember` and `ask` never reach the adjudicator"*, open in the standing
ledger. That is a consequence level, a blast radius and an approval path in `adjudicate.rs`: a
session's work, not this one's.

So: **`artifact` does not ship in Session C.** Shipping it unresolved would be the model's own path
string echoed to a client that would re-resolve it — instance #16 with a path-traversal edge, on the
surface M3-DESIGN §3.6 calls *"the highest-value display attack in the product"*. This is a deviation
from §2.3's literal record shape and is flagged in §7.

### 4.5 · The §4.1/§4.2 budget-extension record set is deferred

`grep -rniE "extension|envelope" crates/marlowe-loop/src/` returns zero hits. There is no `ModelStep`
variant, no tool registration, no `Args` mapping, and the first design proposed none while also
proposing to **pin the whole record set in `CONTRACTS.md` §12**. `Run::request_extension` would have no
production caller; `ExtensionReason::max_grants_per_run` — advertised as *"THE READER of
`reason_code`"* — would read a field on a record nothing constructs; and
`an_extension_request_has_no_place_to_put_a_sentence` would pin the JSON key set of a type the product
never emits. That is instance #16 at subsystem scale with a green test on top.

It ships when `ModelStep::RequestBudget(BudgetExtensionRequest)`, a `request_budget` registration in
`builtin.rs` with `reason` as a `Target`, and `BudgetExtensionRequest::from_args` land in the same
commit. Until then M3-DESIGN §4.1's second upward channel is unbuilt and `STATE.md` should say the
escalation channel shipped and the budget channel did not.

**One thing from that half is worth keeping and is recorded rather than lost.** The first design's
`max_grants_per_run` is `>= 1` on every arm, with the `0 >= 0` reasoning written out in its doc
comment — instance #17 (`Budget::exhausted` compares `spent >= budget`, so a zero dimension means
*already exhausted*, not *may not use*). The design named the trap and avoided it; the adversarial
pass verified that and said so.

### 4.6 · Rejected: `LoopOutcome::AskedUser { question }` as a separate variant

It reads cleaner and costs a match arm at every `LoopOutcome` site plus the daemon and the
child-return path. `Escalation::raise` already has `run.parent` in hand and gets the same structural
separation in one constructor, keeping the discriminator where a reviewer looks. **Recorded rather
than dismissed: if a later session finds `principal_question` populated for a run with a parent, the
variant split is the fix.**

### 4.7 · Rejected: put `UpwardShape` on `CapabilityProfile`

`crates/marlowe-loop/src/profile.rs` is §13-guarded, and the profile is where capabilities live, not
where measurement settings live. `CapabilityProfile::new`'s invariant (`reads_untrusted ⟹ DenyAll`)
has nothing to say about an arm selector, so the type's validating constructor would be enforcing
nothing about it. `Engine` already holds `tier`, which is the same kind of per-process policy input.

### 4.8 · Rejected: `artifact_ref` as a `ContentRef`

`grep -rn "struct ContentRef" --include=*.rs crates/` returns nothing — `ContentRef` is pinned in
`CONTRACTS.md` §2 and has no Rust implementation. The only content store that exists is
`marlowe_extract`'s `DocumentStore`, scoped to fetched web documents. Choosing it would mean building
a general content store inside Session C. This rejection survives §4.4's deferral: when `artifact`
does ship it is a `ScopedPath::relative()`, not a `ContentRef`.

---

## 5 · Tests, each with the mutation that reddens it

No test below reads the same whether or not the mechanism works — that is instance #15 and is the bar
this table has to clear.

| Test | File | Asserts | Mutation that reddens it |
|---|---|---|---|
| `the_arm_decides_what_crosses_from_a_child` | `crates/marlowe-loop/tests/upward_channel.rs` | ONE test, THREE runs of the identical scripted child through the real `Engine::spawn`. The child emits nonce `BANANA-7Q` in a field its `OutputContract` does **not** declare. Assert on the bytes pushed into the PARENT's `state` at `engine.rs:3043`: under `Typed` the nonce is in **no byte**; under `FreeText` it **is**; under `TypedPlusValidatedSentence` it is absent and `headline` is present | Make every arm return the `Typed` note → the `FreeText` half goes red. Make `Typed` skip `req.contract.validate` → the `Typed` half goes red. **A build where nothing crosses at all fails the `FreeText` half**, which is what the first design's version could not do |
| `the_arm_is_visible_in_the_journal_of_the_running_process` | `crates/marlowe-daemon/tests/upward_shape_is_emitted_by_the_running_process.rs` | Launch `target/debug/marlowe.exe --serve --upward-shape free-text`, drive one real spawn whose child emits the nonce, read `tools/read_journal.py --all`: the parent's `RunCompleted` payload contains **the nonce**. Relaunch with `--upward-shape typed`: it does not | Drop the shape match in `Engine::spawn` → the two launches produce identical journals and the test fails **by nonce, not by label**. This is the correction to `every_escalation_row_names_its_arm`, which read the flag |
| `a_tainted_run_cannot_choose_its_escalation_category` | `upward_channel.rs` | A run latched to `UntrustedContent` asks with `category: Some(IntegritySuspected)` → granted `Unclassified`, `severity() == Normal`, row carries `requested: "integrity_suspected" / granted: "unclassified"`. **NEGATIVE CONTROL in the same test:** an untainted run gets `IntegritySuspected` and `severity() == Critical` | Delete the `blocks_composed_targets` guard → the tainted half goes red. Force `Unclassified` unconditionally → the control half goes red. **Both are needed**; one test cannot see both |
| `severity_is_derived_and_moves_the_wire` | `upward_channel.rs` | `Event::Escalation` serialises `severity: "critical", interrupt: true` for `IrreversibleAhead` and `"normal", false` for `Blocked`, read off the JSON frame. Plus: `serde_json::to_value(&escalation)` has **no** `severity` key | Move `IrreversibleAhead` to the `Normal` arm. Or add a stored `severity` field → the key-set half fails |
| `the_models_category_actually_reaches_the_loop` | `crates/marlowe-tools/tests/ask_manifest.rs` | Feed a real `/api/chat` tool-call body naming `category: "integrity_suspected"` through `parse_step`; assert `ModelStep::Ask(AskRequest { category: Some(IntegritySuspected), .. })`. NEGATIVE: `category: "banana"` → `None`, and the row reads `requested: null` | Remove the `category` parameter from `ask`'s registration → `Args` drops it and the test reads `None`. **This is the test whose absence makes `EscalationCategory::parse` instance #16** |
| `lineage_floor_is_the_runs_latched_floor_and_survives_a_trim` | `upward_channel.rs` | Following `crates/marlowe-exec/tests/adr023_live.rs`: **FIRST** assert the emitted §B6 line shows the untrusted block was actually trimmed, **THEN** `escalation.lineage.floor == run.trust_floor() == UntrustedContent` | Build `Lineage` from `view.trust_floor()`. It reddens **only because the trim occurred**, which is why the trim control is the first assertion and not an afterthought — an assertion whose subject is *"X was removed"* carries an assertion that X was removed |
| `the_root_runs_question_still_reaches_its_principal` | `upward_channel.rs` | A ROOT run (`parent: None`) asks the nonce question under all three arms; `principal_question()` is `Some` and the nonce is in the emitted frame every time. The typed arm must not mute Marlowe — his channel to his own principal is not an upward hop | Drop the `run.parent.is_none()` guard → `principal_question` is `None` and the nonce vanishes |
| `the_shape_flag_has_no_silent_default` | `crates/marlowe/tests/upward_shape_flag.rs` | `marlowe --serve --upward-shape banana` exits 2 naming all three spellings, in `--reranking`'s style (`main.rs:741`). Absent flag → `Typed`, announced on the boot line | Replace the refusal with `parse(v).unwrap_or(Typed)` → exits 0 and the exit-code assertion fails |
| `every_spelling_has_one_producer` | `upward_channel.rs` | For every variant of `UpwardShape`, `EscalationCategory` and `Severity`: `serde_json::to_value(v) == json!(v.as_str())`, and `parse(v.as_str())` round-trips | Change one `as_str` string or one `rename_all` → red by name |
| `a8_report_refuses_a_cell_it_cannot_label` | `tools/test_a8_report.py` | `python tools/a8_report.py --run <fixture> --expect-arms typed,validated_sentence,free_text` exits non-zero and names the cell when (a) rows in one cell carry two arms, (b) **rows carry no `upward_shape` key at all**, or (c) an expected arm is missing from the sheet | Remove case (b) → a journal with the field deleted reads as one arm and prints a plausible rate, which is **instance #19**: a self-check whose input is the object it checks. Pinning the expected arms on the command line puts membership and count outside the data |

**The numeric target, as a command that prints a number:**

```
python tools/a8_report.py --run runs/m3-c-a8 --expect-arms typed,validated_sentence,free_text
```

It prints three injection-propagation rates, three `n`, a discarded-cell count, **the embedder
provider that actually resolved off each run's boot line** (not off the flag — ADR-044 makes `auto`
resolve against free VRAM at load), and the §5 layer tally on its front page, so a clean A8 sheet is
never read as evidence about layer 3.

---

## 6 · What this decision does NOT close

* **It does not make layer 3 reachable, and A8 is not evidence about it.** ADR-062 stands unchanged:
  `grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"` returns
  nothing, so the shipped daemon cannot enter the state layer 3 defends. A8 measures the **channel**,
  not the latch. REDTEAM-SESSION §2's named false pass is a clean A8 sheet read as a taint-class
  result, and `a8_report.py` printing the layer tally is the mitigation, not a fix.
* **It does not close `SECURITY-AUDIT.md` §6.** `ask` still never reaches the adjudicator. The narrow
  `blocks_composed_targets` call inside `raise` buys one property — a tainted run cannot choose its
  urgency — using the same function the adjudicator enforces on, with no edit to `adjudicate.rs`. The
  finding is cited, not claimed, and §4.4 shows it is also the correct route to `artifact_ref`.
* **It does not touch `SECURITY-AUDIT.md` §8 or ADR-032's identical question.** The latch's
  run-vs-session scope and the egress grant's run-vs-session scope are the human's and should be
  answered together or not at all. Nothing here widens either.
* **It does not close M3-DESIGN §12 item 5.** The 2026-08-29 `DECISIONS.md` entry settled that a typed
  upward return needs no `Channel`; the meeting utterance (§5.2) and the harness-mediated reader
  (ADR-062 §4) remain open consumers of that missing slot. No `Channel` variant is added here.
* **It does not fix `remember`'s second-definition hazard, and that hazard is now visible.**
  `ollama.rs:1024-1028` constructs `ClaimRequest` inline in the adapter, exactly as `ask` did. Moving
  `ask` to `AskRequest::from_args` fixes one of the two and leaves the other, so a second provider
  writing its own `remember` mapping remains possible. `remember` is `Consequential` and documented as
  *"the highest-privilege operation in the system"*, so this is worth a session; it is out of scope
  here and is recorded so it is not inherited silently.
* **It does not build M3-DESIGN §4.1/§4.2** (§4.5), or §3.6's host/fetched-at citations, or the
  escalation window itself.
* **It does not claim arm (b) can be run on this machine as configured.** §7.4.

---

## 7 · WHAT IS THE HUMAN'S

### 7.1 · `crates/marlowe-loop/src/driver.rs` is §13-guarded and this edits it

Verified: `python .claude/hooks/protect-boundaries.py --list-protected` lists it. `ModelStep::Ask(String)`
becomes `Ask(AskRequest)`, and `AskRequest` plus its `from_args` are new types in that file. The hook's
own entry for it (`.claude/hooks/protect-boundaries.py:99-113`) says:

> THE FILE IS WIDER THAN THE BOUNDARY: it also declares `ModelStep`, `ToolHost`, `ToolBody`,
> `ClockSource`, `TurnSink`, `ApprovalGate` and a dozen more […] **READ WHICH TYPE IS BEING CHANGED
> before approving: if it is not the memory port, this prompt is noise and the honest answer is yes.**

`MemoryHost` and `ExternalContent` are untouched. **No other guarded file is edited** — `adjudicate.rs`
is called (`blocks_composed_targets` is already `pub` at `:50`), not modified; `profile.rs`,
`provenance.rs`, `taint.rs`, `steer.rs`, `memory.rs`, `mcp.rs`, `pin.rs`, `scope/`, `egress.rs` and the
journal files are untouched — **and §4.4's deferral of `artifact_ref` is what keeps `scope/mod.rs` off
that list.** If the human wants `artifact_ref` in Session C, the honest price is a guarded edit, and it
should be approved as such rather than reached by an ergonomic route.

### 7.2 · Two deviations from M3-DESIGN §2.3, in opposite directions

§2.3 specifies `{ run_id, severity, category (fixed enum), artifact_ref, lineage[] }`. This ADR
**keeps `severity`** (reversing the design under review, and honouring the settled 2026-08-29
`DECISIONS.md` entry that quotes the shape) and **defers `artifact_ref`** (§4.4). Both are the human's
because §2.3 is the human's document. The asymmetry is deliberate: `severity` is retained with a
harness-owned derivation, `artifact_ref` is postponed with a named route back.

### 7.3 · Whether `UpwardShape::FreeText` ships in the release binary — AND THERE IS A DIRECT CONFLICT IN THE DOCUMENTS

M3-DESIGN §9.1's 2026-08-30 A8 amendment says:

> Arm (c) deliberately reopens the hole the comment at `engine.rs:2900` closed, so it **takes its own
> `DECISIONS.md` entry and must be unreachable in a shipped build rather than merely off by default.**

§4.1 of this ADR argues the opposite: a `cfg`-gated control measures a different artifact, which is
the `persona_emission.rs` family aimed at the one measurement whose null result and positive result
are otherwise indistinguishable. **Both sentences cannot hold.** The options are (a) a CLI flag on the
shipped binary — this project's established pattern, and a permanently-available unvalidated upward
channel; (b) a `cfg` feature — a control on a different binary; (c) a signed, journalled,
boot-announced dev mode, which is a different design and a session of its own. This is a security
posture question, not a measurement one, and it is not a session's to take. **It takes its own
`DECISIONS.md` entry either way.**

### 7.4 · Arm (b) needs a model, and there is no VRAM for a fourth

Measured by the design session via `GET /api/ps`: **14,993 MiB used, 1,053 MiB free**, with the desktop
holding 5,086 MiB before any model loaded. That figure is carried from the design document, not
re-taken by this ADR — it is a measurement of one machine at one moment and the rule about carrying
measurements across systems applies to it. `AGENT-DIRECTORY.md` §2's *"headroom for the KV cache, the
embedder and the reranker"* is contradicted by it, and ADR-044 resolves the embedder's provider
against free VRAM **at load**, so arm (b) is the arm most likely to push the embedder to CPU
mid-measurement with a correct-looking log line. Arm (b)'s cells pin `--embedder-provider cpu`, and the
report reads the provider that actually resolved off the boot line. **Which of the named roles
validates the sentence — or whether it is the unnamed fourth — is the human's, and is not named here.**

### 7.5 · The contract acts, to be done deliberately

`CONTRACTS.md` §12 gains `Escalation` and `Lineage`. **Its header sentence must be corrected in the
same commit.** It currently reads *"These six are the remainder — five structs below, and the memory
port in §12.1"*, and that is accurate today: the five are `ToolCall`, `TaintSet`, `ContextView`,
`Checkpoint`, `SteerMessage` (counted at `CONTRACTS.md:1360-1415`). It becomes seven structs and eight
items, and M3-D2 had to fix a stale count in this exact sentence last week. A new **§13.1** pins
`protocol::Event` as the daemon wire enum and states its relationship to §13's `TurnEvent` — necessary
because **§13 pins `TurnEvent`, which has no `detail` field at all**, so the first design's *"§13 gains
`Event::Escalation`"* and *"`Event::Done`'s `detail` documentation must record …"* described a type
that section does not contain.

---

## 8 · The adversarial pass, recorded

**The verdict on the first design was `broken`**, and the fatal finding is §1 of this ADR: `UpwardShape`
changed no byte the product emits, so A8 as designed would have measured the flag rather than the
channel. That is not a detail that was cleaned up on the way to a good design; it was the design's
central mechanism, and it is why this ADR's §2 puts the arm somewhere else entirely.

Twelve defects were raised. Nine are carried into the decision above; three are recorded here.

### 8.1 · What the critique got right that this ADR would not have found on its own

The `raise(…, lineage: Lineage, …)` signature (§2.3), the missing `category` producer (§2.5), the
per-provider mapping (§2.6), the unresolvable `ArtifactRef` (§4.4), the producerless budget-extension
half (§4.5), the `severity` deletion overruling a settled entry (§2.4), `external_sources` as a second
answer (§3), the report's #19 self-check (§5), and the wire's unproduced spellings (§2.7). Also
recorded: it verified that the design **did not** commit instance #17 and said so, which is what makes
the rest of the list worth reading.

### 8.2 · Citations the critique corrected, and one it got slightly wrong

The design cited `daemon.rs:2776` for the outward hop (actually `:2899`) and `daemon.rs:2069` for
`Engine::new` (actually **`:2085`**, verified here). Both corrections stand. The critique's own
*"1 production … and 29 tests"* splits **2 examples / 27 tests** (§2.2). The branch this work sits on
has *"Five of the seven line citations in Session C's own row had drifted"* as a commit subject, so
citations here are by **symbol and file** wherever a line number would be a claim about a path with
nothing checking it.

### 8.3 · What this ADR found that the critique did not

Three things, and the first two are the reason §4.4 and §2.7 read as they do.

1. **The critique's own fix for `ArtifactRef` does not work.** It called `S: PathScope + Clone` *"the
   non-guarded route, and the one to prefer"*. `WorkspaceScope` is not `Clone`
   (`scope/mod.rs:218-224`), and `/marlowe-permission/src/scope/` is a guarded directory prefix. Both
   named routes edit a §13 file, which is what turns "resolve it at the `ModelStep::Ask` site" into
   "defer the field".
2. **`NoteKind` has no producer once the arm moves.** The critique asked for it to become a real enum;
   after §2.1 the escalation record carries no note, so the enum would be #16 committed inside the
   fix for #16. Deleted instead.
3. **M3-DESIGN §9.1's amendment and this ADR's §4.1 contradict each other on whether arm (c) may exist
   in a shipped build** (§7.3). Neither document acknowledges the other.

---

## 9 · Verification

Symbol and file rather than line number wherever a line number would be an unchecked claim.

| Claim | How established |
|---|---|
| A child's `Escalated` is replaced by a harness constant and never crosses | read: `crates/marlowe-loop/src/engine.rs:2936-2946`, and the rule at `:2900` |
| The note match is at `engine.rs:2910`; the validated crossing at `:2911-2912`; the push at `:3035-3043` | `grep -n "let note = match outcome"`, `grep -n "Ok(()) => result.render()"`, `grep -n AgentInferred` |
| `ask` declares exactly one parameter | read: `crates/marlowe-tools/src/builtin.rs:699-717` |
| `control_step` reads only `question` | read: `crates/marlowe-provider/src/ollama.rs:1023` |
| `blocks_composed_targets` is `pub` and callable without editing a guarded file | read: `crates/marlowe-permission/src/adjudicate.rs:50` |
| `run.trust_floor()` is the latched authority; `run.parent` is the hop discriminator | read: `crates/marlowe-loop/src/run.rs:605`, `:571` |
| `Adjudicator<S>.scope` is private with no accessor | read: `crates/marlowe-permission/src/adjudicate.rs:254-256` |
| `PathScope::open` needs globs, workspace and access | read: `crates/marlowe-permission/src/scope/mod.rs:186-193` |
| **`WorkspaceScope` is not `Clone`** | read: `crates/marlowe-permission/src/scope/mod.rs:218-224`; `grep -n Clone` on that file returns three hits, none of them this type |
| `scope/` is a guarded directory prefix; `driver.rs` is a guarded file; `engine.rs`, `builtin.rs`, `protocol.rs`, `daemon.rs` are not | `python .claude/hooks/protect-boundaries.py --list-protected` — fifteen entries |
| `Engine::new` has 30 call sites: 1 production, 2 examples, 27 tests | `grep -rn "Engine::new(" --include=*.rs crates/ \| sed 's/:.*//' \| sort \| uniq -c` |
| `Engine::new` moves its scope into the adjudicator and keeps none | read: `crates/marlowe-loop/src/engine.rs:531-551`, and the struct at `:397-425` |
| `Adjudication` already returns resolved `ScopedPath` handles | read: `crates/marlowe-permission/src/adjudicate.rs:176-180`, resolving at `:343` |
| `LoopOutcome` is not pinned; `SpawnRequest` is pinned only as a method signature | `grep -c LoopOutcome docs/design/CONTRACTS.md` → **0**; `grep -n SpawnRequest` → one hit, `:941` |
| §12's *"six … five structs below"* is accurate today | counted at `docs/design/CONTRACTS.md:1360-1415`: `ToolCall`, `TaintSet`, `ContextView`, `Checkpoint`, `SteerMessage` |
| §13 pins `TurnEvent`, which has no `detail` field | read: `docs/design/CONTRACTS.md:1513-1527` |
| `protocol::Event` derives `Deserialize` | read: `crates/marlowe-daemon/src/protocol.rs:217`, enum at `:219` |
| `RunCompleted` is already in §1.1's closed set, so no event kind is added | read: `docs/design/CONTRACTS.md:111-150` |
| `severity` has readers in M3-DESIGN | read: §3.2 (*"A `critical` escalation has been raised by `CodeProjectLeader`"*) and §9.1's A7 row (*"severity-gated"*) |
| The 2026-08-29 `DECISIONS.md` entry quotes the record shape including `severity` | read: `docs/design/DECISIONS.md`, *"A NARROW decision on M3-DESIGN §12 item 5"* |
| REDTEAM pass 1's surface is the condensed summary re-entering a parent | read: `docs/design/REDTEAM-SESSION.md:127` |
| `SECURITY-AUDIT` §6 (`ask` never reaches the adjudicator) is open | read: `docs/design/SECURITY-AUDIT.md:112-117` |
| `ingest_external` still has no caller | `grep -rn "ingest_external(" --include=*.rs crates/*/src/ \| grep -v "fn ingest_external"` — empty (ADR-062's discriminating command) |
| The budget-extension half has no producer | `grep -rniE "extension\|envelope" crates/marlowe-loop/src/` — zero hits |
| The 1,053 MiB free-VRAM figure | **carried, not re-measured.** Taken by the design session via `GET /api/ps`; re-take it before acting on it (§7.4) |

**Nothing in this ADR was measured by running the suite.** `cargo` was not invoked — another session
is building, and hazard form 6 is a parallel build producing a complete, plausible, wrong table. Every
claim above is a read or a grep, and the distinction is stated rather than implied, because a table of
greps reads like a table of tests.
