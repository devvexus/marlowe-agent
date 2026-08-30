# ADR-065 · Escalation routes on `Run::parent` and one inherited bit, and TERMINATE is a variant the agent cannot name

**Status:** PROPOSED — needs the human's approval. **DESIGN ONLY, NO CODE.** Nothing in this ADR has
been built, and one of its two structural changes edits a §13-guarded file.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | nothing. **M3-DESIGN §11's TERMINATE row was already amended at `2fe2986`** and §9.1 with it; this ADR is the design behind those rows, not a second edit of them |
| **Depends on** | M3-DESIGN §1, §2.3, §3.1–§3.6, §9.1 (A8), §11; ADR-023 (the latch), ADR-030 §5 (`Notice` has no `String`), ADR-036 §5 (the authority rule at a saturated floor), ADR-039 / ADR-041 (quarantined reads, and the group as the unit), ADR-055 (the control-plane listener), ADR-057 (who declares a child's contract), ADR-062 (`ingest` has no correct production caller) |
| **Contract change** | **Yes, and it is the human's.** `CONTRACTS.md` §5's pinned `Run` gains `raises_to: RaisesTo`; a new §5.2 pins the escalation record. `TurnEvent` (§13) is untouched, `MemoryHost` (§12.1) is untouched, `SpawnRequest` gains nothing |
| **Code change** | **None yet, and one of the two files is guarded.** `crates/marlowe-loop/src/driver.rs` is on `PROTECTED` (verified: `python .claude/hooks/protect-boundaries.py --list-protected`) and needs `ModelStep::Escalate`, `EscalationRequest`, `EscalationPort` and `NoEscalation`. `profile.rs`, `adjudicate.rs`, `taint.rs` and `provenance.rs` are deliberately untouched |
| **Verified at** | HEAD `2fe2986`, 2026-08-30. Every line number below was re-run today; §9 lists the ones that had drifted, **including two the adversarial critique itself got wrong** |

---

## 1 · The question, and the finding that reframed it

M3-DESIGN §3 asks for a channel that lets a stuck agent reach a human, calls it *"the single most
dangerous channel in the system"*, and §3.4 states the property the whole design exists to hold:

> **TERMINATE IS RENDERED BY THE HARNESS AND THE AGENT DOES NOT KNOW IT EXISTS.** Not in its tool
> set, not in its system prompt, not describable, not styleable, not annotatable.

The question this ADR answers is narrower than "how does escalation work": **what carries the routing
decision, and what makes the escape hatch's invisibility a property of a type rather than a sentence
in a prompt?**

### 1.1 · The finding that came first, because it changes what may be asserted

The acceptance row §11 shipped for §3.4 was *"TERMINATE present in an agent's `request_body` — **0
occurrences**, over every agent type."* **That row is red on a correct build, from two production
sources that have nothing to do with the escape hatch.** Re-measured today at `2fe2986`:

```
$ grep -n "orphan_policy" -A4 crates/marlowe-tools/src/builtin.rs
691:                    "orphan_policy",
692-                    ArgumentRole::Target,
693-                    Text,
694-                    false,
695-                    "`terminate` (default) ends the child when this run ends; `detach` lets it
                        outlive this run. Omit unless you specifically want it to survive you."

$ grep -n "OrphanPolicy::Terminate" crates/marlowe-loop/src/engine.rs
2152:            OrphanPolicy::Terminate,
2731:                    OrphanPolicy::Terminate => "terminate",
3240:        || !matches!(req.orphan, OrphanPolicy::Terminate)
```

`builtin.rs:695` is the `run` tool's `orphan_policy` parameter description, and it ships in the tool
schema to every model holding `run`. `engine.rs:2731` renders the policy into the spawn receipt that
is pushed into the parent's history, so it is in the parent's next request body too.

**The row was measuring a spelling; §3.4 is about an object.** `OrphanPolicy::Terminate` is a
declared, model-nameable, harmless lifecycle value — `builtin.rs:902` asserts
`run.role_of("orphan_policy") == Some(ArgumentRole::Target)`, so it is adjudicated like every other
target and is *supposed* to be nameable. The escape hatch is a harness-rendered control the agent
must not be able to invoke, describe, suppress or style. Two unrelated things share the word.

**The cheap repair is the defect.** Narrowing the search — case-sensitive `TERMINATE`, or excluding
the tool schema, or grepping only for a longer label — restores a green cell over a property nobody
checked. That is instance #15 committed against the acceptance table itself, and it is the reason
this ADR opens with a measurement rather than a design.

§11 already carries this amendment at `2fe2986` and replaces the one row with three. **This ADR does
not edit it and inherits its constraint verbatim**, including the sentence that binds the test set
below:

> The third is the one with teeth, and it is the only one of the three the original row gestured at.
> **The first two are satisfiable by an empty implementation; the third is not.**

Two consequences worth stating plainly, because both are places a future session would report a zero
it did not earn:

* **Row 1 — *"the escape hatch is in no agent's exposed set"* — is green today and will be green
  forever.** There is no `terminate` tool in `builtin_registry()` and this design adds none, so the
  assertion is trivially true on an empty implementation. It is a regression guard, not evidence.
* **Row 2 must be read from the running process.** A body built inside a test process is the
  `persona_emission.rs` failure aimed at a security measurement. The seam that makes this possible
  **now exists**: `Daemon::ask_streaming_with_driver` (`daemon.rs:1772`), whose own doc says *"This is
  the seam, and it exists so that a real daemon turn can be measured."* ADR-062 §6.5's *"`Daemon::turn`
  constructs its model driver internally with no seam"* was true when written and is no longer true —
  corrected here rather than left to be inherited.

---

## 2 · The decision

Six parts. Where a type is involved it is written as Rust, because the whole argument is that the
enforcement is in the signature.

### 2.1 · One inherited bit, not a five-value level

**`AgentLevel` is dropped.** Escalation routing reads exactly two things: *may this run raise*, and
*who is above it*. The second is `Run::parent`, which already has one definition. The first is the
only fact the tree cannot recompute, so it is inherited the way `trust_floor` is inherited
(`run.rs:654`: `trust_floor: parent.trust_floor`).

```rust
// crates/marlowe-loop/src/run.rs — NOT §13-guarded

/// Where an escalation raised by THIS run goes. **Derived at construction from the parent's own
/// value and from the profile.** No setter, no `SpawnRequest` field, no `From<&str>`.
///
/// It deliberately encodes only what routing reads. M3-DESIGN §1's five levels are a description
/// of the tree; `Run::parent` already answers "where am I", and a second encoding of it diverges
/// the moment `adopted_by` or `detached` runs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RaisesTo {
    /// The conversational run. Nobody above it. §3.1.
    Nobody,
    /// Created by the conversational run, so a top-agent: its escalation reaches the USER, and
    /// §3.2's recipient is the user, never Marlowe.
    User,
    /// Reaches its parent and only its parent.
    Parent,
    /// **Structural.** A run whose profile reads untrusted content may not raise at all: its
    /// window holds raw attacker bytes (ADR-041), so its question is a statement about the model
    /// and not about the page. `CapabilityProfile::new` already makes `reads_untrusted` imply an
    /// empty tool set at load time, so this rides an invariant that exists.
    Refused,
}
```

`Run` gains a private `raises_to`, with `pub fn raises_to(&self) -> RaisesTo`. The three
constructors, all in `run.rs`:

```rust
// Run::root   — daemon.rs:2609, and control.rs's test helper
raises_to: RaisesTo::Nobody,

// Run::child  — engine.rs:2146 (condense_batch) and engine.rs:2666 (Engine::spawn)
raises_to: if profile.reads_untrusted() {           // profile.rs:286
        RaisesTo::Refused
    } else {
        match parent.raises_to {
            RaisesTo::Nobody  => RaisesTo::User,
            RaisesTo::Refused => RaisesTo::Refused,
            _                 => RaisesTo::Parent,
        }
    },

// Run::restored — one more explicit parameter, no default
raises_to,
```

**`Run::child` reads it off the `profile` argument it already takes, so `condense_batch`'s
quarantined reader classifies correctly without `condense_batch` changing at all.** That is not a
convenience; it is the defect that killed the first design (§7), where the reader came out `Worker`
and was handed a live route to its parent.

**`may_hold_create_grant` is deleted rather than built.** See §3 — its refusal is unreachable behind
the narrowing check at `engine.rs:2630-2641`, so its only enforcement site could never see it false.

**Durability.** `Checkpoint` (`durable.rs:87-108`) gains `pub raises_to: RaisesTo` with **no
`#[serde(default)]`**, and `CHECKPOINT_VERSION` (`durable.rs:79`, currently `1`) is bumped. The
refusal path already exists and is already tested: `control.rs:238` compares `cp.version` against
`CHECKPOINT_VERSION` and returns the named error, and `control.rs:351` is the test that drives it. A
`#[serde(default)]` here would make every existing checkpoint decode into a run whose escalation
routing is whatever serde chose — the permissive-default family, on a security field, in the
milestone whose subject is durable resume.

### 2.2 · Routing, with the detached case audible

```rust
// crates/marlowe-loop/src/escalation.rs — NEW, not guarded

/// **There is no arm that returns the conversational run, and that absence IS §3.2.**
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EscalationRoute {
    Parent(RunId),
    User,
    /// Nobody above, or a run that may not raise. Carries WHY, because a channel that goes
    /// quiet is not a channel that is closed.
    NotRaisable(NotRaisableReason),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NotRaisableReason {
    /// The conversational run: §3.1, nobody above.
    Root,
    /// A quarantined reader.
    ReadsUntrusted,
    /// `OrphanPolicy::Detach` cut the parent link (`durable.rs:375-378`). The raiser is told, and
    /// the journal records it.
    Detached,
}

pub fn escalation_route(run: &Run) -> EscalationRoute {
    match (run.raises_to(), run.parent) {
        (RaisesTo::Refused, _)      => EscalationRoute::NotRaisable(NotRaisableReason::ReadsUntrusted),
        (RaisesTo::Nobody, _)       => EscalationRoute::NotRaisable(NotRaisableReason::Root),
        (RaisesTo::User, _)         => EscalationRoute::User,
        (RaisesTo::Parent, Some(p)) => EscalationRoute::Parent(p),
        (RaisesTo::Parent, None)    => EscalationRoute::NotRaisable(NotRaisableReason::Detached),
    }
}
```

Every `NotRaisable` writes `EventKind::RunFailed` (`marlowe-journal/src/event.rs:63`) with the reason
and pushes a harness-authored constant into the raiser's own window, on the `UNDESCRIBED_SOURCE`
precedent (`engine.rs:238`) — one shared constant, not a literal at each end. `QuarantineRefusal`
(`engine.rs:278-293`) already carries the closest existing statement of the same thing, and its
`Escalated` variant's doc reads *"it is a statement about the model, not about the page"*, so the
reader's refusal is a wording the codebase already owns.

`Run::adopted_by` needs no change: `RaisesTo` encodes no depth, so an adopted child correctly raises
to whoever its parent now is. That is the whole reason the bit is `RaisesTo` and not a level.

### 2.3 · The port — the seam the first design left open

`marlowe-loop` cannot see `marlowe-daemon`, so `Ports` is how anything leaves the loop. `Ports`
(`engine.rs:219-229`) holds `driver, summarizer, tools, memory, approvals, sink, control, clock,
recorder` and nothing for escalation. **Both changes below are in
`crates/marlowe-loop/src/driver.rs`, which is §13-guarded. A human must approve them, and a
`DECISIONS.md` entry arrives with them.**

```rust
// crates/marlowe-loop/src/driver.rs — §13-GUARDED

pub enum ModelStep {
    Say(String),
    ToolCall { calls: Vec<ToolInvocation> },
    MemoryWrite(ClaimRequest),
    Spawn(SpawnRequest),
    /// **Unchanged and unrepurposed.** This is `ask` — the conversational run putting a question
    /// to the user. `Engine` refuses it from any run whose `raises_to` is not `Nobody`.
    Ask(String),
    /// §2.3's typed upward record. No free paragraph.
    Escalate(EscalationRequest),
}

/// What a model may supply. **The recipient is not here** — it is `escalation_route`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EscalationRequest {
    pub severity: EscalationSeverity,
    pub category: EscalationCategory,
    /// A journal-addressed handle the harness turns into a path. **Not `ContentRef`** — §2.6.
    pub artifact: Option<ArtifactHandle>,
    /// §9.1 A8's middle arm only. `EscalationArm::Typed` refuses `Some` by name.
    pub sentence: Option<ValidatedSentence>,
}

/// How an escalation leaves the loop.
pub trait EscalationPort {
    fn raise(&mut self, run: RunId, route: EscalationRoute, req: EscalationRequest)
        -> Result<EscalationId, EscalationRefused>;
}

/// The default: nothing is raised. **On `NoControl`'s precedent, which is in this same file at
/// `driver.rs:692` and is passed by `condense_batch` at `engine.rs:2264` (`let mut no_control =
/// crate::NoControl;`).**
pub struct NoEscalation;
impl EscalationPort for NoEscalation {
    fn raise(&mut self, _: RunId, _: EscalationRoute, _: EscalationRequest)
        -> Result<EscalationId, EscalationRefused> { Err(EscalationRefused::NoDesk) }
}
```

`Ports` gains `pub escalations: &'a mut dyn EscalationPort`. **The quarantined reader's child `Ports`
is at `engine.rs:2265-2275` — `memory: None` is line 2269 — and that is where `&mut NoEscalation` is
passed, beside the existing `memory: None`.** The ordinary spawn's child `Ports` is the *other* site,
`engine.rs:2881-2891` with `memory: None` at 2885, and it passes the real port. The adversarial
critique named `engine.rs:2880-2891` as "the quarantined-reader child `Ports`"; it is the ordinary
spawn's, and taking that citation at face value would have withheld the port from every ordinary
child and handed it to the quarantined reader — the exact inversion of the design. Corrected in §9.

**Lifecycle.** `PauseReason` (`run.rs:195-199`, an unguarded harness enum, currently
`{BudgetExhausted, AwaitingApproval, AwaitingAnswer}`) gains `AwaitingEscalation { id: EscalationId }`.
`LoopOutcome` gains **`Raised(EscalationId)` as a new variant**; `Escalated { question }` is untouched
— see §4.

### 2.4 · The desk, journal-backed

```rust
// crates/marlowe-daemon/src/escalation.rs — NEW

pub struct EscalationDesk { pending: BTreeMap<EscalationId, Pending> }   // HashMap is banned
struct Pending { escalation: Escalation, at: Recipient, opened_ms: i64 }

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Recipient { Run(RunId), User }

impl EscalationDesk {
    /// **Rebuilt from the journal at boot**, so a pending escalation survives a restart in the
    /// milestone whose subject is durable runs. Every `Pending` is written through the existing
    /// `Recorder` path — one definition of the pending set, not an in-memory second one.
    pub fn from_journal(j: &dyn JournalRead) -> Self;

    /// One hop. `by` MUST be the run this escalation is currently addressed to, and the desk is
    /// the authority for that — not the model that named the id.
    ///
    /// **This is ADR-036 §5's authority rule at a saturated floor.** Inside an escalation every
    /// value is `UntrustedContent`, so ADR-023's floor reads "blocked" for every pending id and
    /// discriminates none. What survives saturation is who addressed it here.
    pub fn advance(&mut self, id: EscalationId, by: RunId, route: EscalationRoute)
        -> Result<Recipient, AdvanceError>;

    /// §3.2, enforced by the SIGNATURE. No `body` parameter, no `&Escalation` return, and no
    /// method on this type hands text to a loop. Marlowe "cannot read it" because there is
    /// nothing to call, not because he was asked not to.
    pub fn secretary_notice(&self, id: EscalationId) -> Option<Notice>;

    pub fn resolve(&mut self, id: EscalationId, choice: Choice) -> Result<Resolution, ResolveError>;
}
```

The escalation window rides the **ADR-055 control-plane listener**, which is a real second listener
on its own advertised port: `crates/marlowe-daemon/src/control_plane.rs`, whose header reads *"The
control plane — a **second listener**, so `/steer` from outside is real rather than queued"* and
*"The thread started here **never touches `Daemon`**."* It never rides the conversation socket, so
`CONTRACTS.md` §13's pinned `TurnEvent` changes nothing and the body never touches Marlowe's
`Ports.sink` or `SessionState`. (The first design cited `marlowe-daemon/src/watch.rs`; **there is no
`watch.rs`** — the files are `control_plane.rs` and `watch_client.rs`.)

`Notice` (`marlowe-view/src/notice.rs:84`) gains one variant, holding no `String`, per ADR-030 §5:

```rust
EscalationRaised { severity: EscalationSeverity, by: Echo }
```

`by` is composed at the producer as `Echo::new(format!("{level_word} {}",
marlowe_loop::run::sayable(&id.to_string())))`. **`sayable` (`run.rs:109`) is the single definition of
how a run is printed**, and its own doc says why: *"a second place deciding what an unparseable id
looks like is a second answer to the same question."* No `AgentLabel`, and no hex prefix — `sayable`
returns a mnemonic (`brave-storm`), which is precisely what that doc prefers over *"one
unrecognisable string [replaced] with a different one."* Zero model bytes reach it.

> **`Echo` is not a validating constructor, and this ADR does not pretend otherwise.**
> `notice.rs:68` is `pub struct Echo(pub String)` with a public field and an `Echo::new` that does no
> normalisation. ADR-030 §5's "no `String`" is therefore a discipline about *who composes the value*,
> not a check the type performs. The containment here rests entirely on the composition site being
> harness-authored. Any future `Echo` built from model bytes needs `sanitize_line` at that site, and
> nothing in the type will remind anyone.

### 2.5 · §3.3's two sentences go in Marlowe's stable tier and nobody else's

`SessionState::governance` is copied into **every** child: `engine.rs:2205-2208` (the quarantined
reader) and `engine.rs:2796-2800` (an ordinary spawn), both `for c in &state.governance {
child_state.assert_governance(c.clone()); }`. So §3.3's explanation must not go there. Put it there
and *"That content came from untrusted sources. If it carried an injection, propagating it to me is
the failure worth preventing"* arrives in the system message of every worker that reads a hostile
page — a description of the containment architecture, in the window holding the attacker's text.

`SessionState` gains:

```rust
/// Stable-tier facts for the conversational run ALONE. Rebuilt into the stable tier by
/// `Assembler::assemble` beside `governance` (`context.rs:642`), and copied by NEITHER child loop.
pub secretary_notes: Vec<GovernanceConstraint>,
```

Asserted once at session construction in `daemon.rs`, unconditionally, **before any escalation
exists** — which is the property "stable tier, not retrievable memory" actually buys, and the reason
a lazy assertion at the first escalation would be a weaker design that passes the same test.

### 2.6 · The record, and the artifact that is not a `ContentRef`

```rust
// crates/marlowe-contract/src/escalation.rs — NEW

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Escalation {
    pub id: EscalationId,
    pub raised_by: RunId,
    pub severity: EscalationSeverity,
    pub category: EscalationCategory,
    pub artifact: Option<ArtifactHandle>,
    /// The approving chain, newest last. Appended by `EscalationDesk::advance`, never by a model.
    pub lineage: Vec<RunId>,
    pub sentence: Option<ValidatedSentence>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationSeverity { Advisory, Blocking, Critical }

/// Closed, on ADR-030 §5's growth rule.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationCategory {
    BlockedByPermission, ScopeContradiction, ExternalSystemRefused,
    ConflictingInstructions, SuspectedInjection, IrreversibleActionRequired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ValidatedSentence(String);

impl ValidatedSentence {
    pub const MAX_CHARS: usize = 200;
    pub fn normalise(raw: &str) -> Result<Self, TextRejected> {
        let one = crate::text::sanitize_line(raw.trim());          // text.rs:156
        if one.chars().count() > Self::MAX_CHARS { return Err(TextRejected::TooLong); }
        if !one.chars().all(crate::text::is_renderable) {          // text.rs:78
            return Err(TextRejected::Unrenderable);
        }
        Ok(Self(one.into_owned()))
    }
    pub fn as_str(&self) -> &str { &self.0 }
}

/// **Hand-written, on `GovernanceConstraint`'s model (`marlowe-loop/src/context.rs:408-425`).**
/// `#[derive(Deserialize)]` is a field-wise way in past `normalise`, and a checkpoint, an MCP
/// descriptor and a spawn request are all ways in (#12).
impl<'de> Deserialize<'de> for ValidatedSentence { /* String::deserialize -> normalise -> de::Error */ }

pub struct OptionLabel(String);   // same discipline, MAX_CHARS = 72, same hand-written Deserialize
```

**`EscalationSeverity` is named that way on purpose.** A bare `Severity { Advisory, … }` would sit
beside `Urgency { Advisory, Immediate }` (`driver.rs:658-663`), sharing a variant name with a
different meaning in the same crate graph.

`EscalationSeverity` is what `EscalationRequest` carries, so **a model chooses its own severity.**
That is deliberate and it is bounded: severity selects rendering and ordering, never a capability,
never a recipient — the recipient is `escalation_route`, which reads the tree. A model that inflates
every escalation to `Critical` costs a human's attention and nothing else, and §11's *"escalations
reaching the user per project-hour, with false-escalation rate"* is where that shows up. **Nothing
here should ever gate a permission on `severity`.**

#### The artifact, and a type that does not exist

`ContentRef` is pinned in `CONTRACTS.md` §2 as `{ hash, bytes, media, summary: ResultSummary, trust,
evicted }` and **carries a summary**, so attacker-shaped prose would cross upward inside the record
§2.3 calls typed, without anyone dereferencing anything. So the field is a hash-only handle.

**But it cannot be written as the strengthened design writes it, and this is the ADR's clearest
"cannot be built as specified":**

```
$ grep -rn "ContentRef" --include=*.rs crates/          # doc comments only, in marlowe-exec,
                                                        # marlowe-journal, marlowe-loop, marlowe-view
$ grep -rn "pub struct ContentHash\|type ContentHash" --include=*.rs crates/
                                                        # (nothing)
```

`ContentRef` is not a Rust type and neither is `ContentHash`. `ArtifactHandle(pub ContentHash)` names
two types that do not exist. **The buildable version is `ArtifactHandle(String)` with a validating
constructor that accepts only hex of the declared width**, on the precedent that already exists and
already argues this case: `marlowe-extract`'s `DocumentRef` (`store.rs:44-64`), whose `hash` is
`String` — *"Content address. Hex of a 128-bit hash over the extracted text"* — and whose module
header (`store.rs:30-33`) is the argument in full:

> No title. No headings. No description. No snippet. Every one of those is attacker-authored text and
> putting any of them on the reference would quietly restore the thing this removes.

The surface composes the path the user opens from the handle. The record carries no text.

`ArgumentRole`'s own definition settles the open question the first design referred upward:
`manifest.rs:84-86` reads *"Tool selection, recipient, path, host, amount, **identifier**"* under
`Target`. **A model-chosen artifact identifier is a `Target` by the existing vocabulary**, so it is
annotated as one in `escalate`'s manifest and adjudicated, rather than raised as undecided.

### 2.7 · The window, and TERMINATE

`crates/marlowe-view/Cargo.toml` has an **empty `[dependencies]`** section and a package description
reading *"Shapes only — nothing here can produce a value."* Adding `marlowe-contract` to it is a
change of stance on a zero-dependency crate and **gets its own `DECISIONS.md` entry**, with the
reason stated rather than assumed: the alternative is a second definition of `is_renderable`
(`marlowe-contract/src/text.rs:78`) inside the shapes crate, and two answers to *"which characters
may reach a terminal"* on the surface where SECURITY-AUDIT B1 and B2 live is the worse trade.

**It is not claimed as an existing precedent, and the critique and the first design are each half
right about that.** `marlowe-surface/Cargo.toml` does carry the *argument* verbatim —
*"`marlowe-contract` is the deepest crate in the workspace and holds no producer, so this does not
weaken the note above"* — so the reasoning is established. What is not established is that
`marlowe-view` may have a dependency at all; its `[dependencies]` is empty and its description says
so. The argument transfers; the precedent does not.

```rust
// crates/marlowe-view/src/escalation.rs — NEW

/// **There is no field for TERMINATE, and that is §3.4's structural invisibility.** A producer
/// cannot supply it, label it, style it, annotate it or move it, because the type has nowhere to
/// put any of those. It is `BlastRadius`'s argument inverted: there, a surface cannot show what
/// it was never given; here, a surface cannot omit what it was never given.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EscalationView {
    pub raised_by: Echo,
    pub severity: EscalationSeverity,
    pub category: EscalationCategory,
    options: Vec<AgentOption>,        // private; bounded at construction
    pub cost: TerminationCost,
    pub evidence: SourceEvidence,     // NOT `Provenance` — see below
    pub artifact: Option<ArtifactPath>,
}

impl EscalationView {
    pub const MAX_AGENT_OPTIONS: usize = 4;
    /// Refused, never truncated. A ceiling on a `Vec` checked at construction, deliberately NOT a
    /// `Budget` dimension: `Budget::exhausted` compares `spent >= budget`, so a bound expressed as
    /// a counter reads as already-spent (#17).
    pub fn new(/* … */) -> Result<Self, TooManyOptions>;
    pub fn options(&self) -> &[AgentOption];
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Choice { Agent(u8), Terminate }

/// What the human reads. Harness-authored, fixed position, always present.
pub const TERMINATE_LABEL: &str = "terminate this agent and the runs under it";

/// **What the TEST reads, and it is deliberately not the word `terminate`.** That word occurs in
/// `run`'s `orphan_policy` description (`marlowe-tools/src/builtin.rs:695`) and in the spawn
/// receipt (`marlowe-loop/src/engine.rs:2731`), so a zero over that substring is RED on a correct
/// build — and the cheap repair is to weaken the search until the zero means nothing (§1.1).
/// This token exists nowhere else in the workspace and in no type a `ModelDriver` can reach.
pub const TERMINATE_CANARY: &str = "harness-escape-hatch-6b1f";
```

**`SourceEvidence`, not `Provenance`.** `pub enum Provenance` in `marlowe-view` would collide with
`marlowe-loop/src/provenance.rs`'s taint attribution — layer-3 machinery, and a §13-guarded file —
and with `marlowe-memory/src/gate/`. Three definitions of one load-bearing word, two of them
security machinery.

```rust
/// §3.6. **Total** — `NoExternalSources` is a claim a producer makes on purpose, exactly as
/// `Novelty::Routine` is (`marlowe-view/src/approval.rs`), not an `Option` a producer can omit
/// while nothing reports the omission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SourceEvidence {
    NoExternalSources,
    External { sources: u32, most_recent: SourceTrace },
}

/// `host` is the host the EGRESS layer resolved, never a string the agent wrote.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceTrace { pub host: HostLabel, pub fetched_ms_ago: u64 }
```

#### `TERMINATE_LABEL` says less than the first draft's did, because the harness cannot keep that promise

The first design's label was *"terminate this agent and everything under it"*. **The harness cannot
do that.** `Control::cancel` is per-run and `control.rs:337` is a test named
`cancelling_one_run_does_not_cancel_its_sibling`. `CONTRACTS.md` §5 pins *"Children outlive parents.
Parent completion does not kill a child."* `settle_orphan` (`durable.rs:361-383`) makes
`OrphanPolicy::Detach` set `cp.parent = None` and the run survive. There is no subtree cancel in the
workspace.

§3.5's entire subject is that *"reverts the scope"* is three different promises and TERMINATE must
tell the truth about which it keeps. So the cost type gains the shortfall as a field:

```rust
/// §3.5, derived from the journal. The model contributes nothing and is never asked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerminationCost {
    pub runs: u32,
    pub age_ms: u64,
    pub spend_micros_usd: u64,
    pub artifacts: u32,
    pub irreversible: Vec<IrreversibleAct>,
    /// **What TERMINATE will NOT stop**, computed by replaying the subtree's declared policies.
    pub survivors: Vec<Survivor>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Survivor { pub run: Echo, pub policy: OrphanPolicyLabel }
```

**Layout, not assertion.** `crates/marlowe-surface/src/escalation.rs::layout` computes the terminate
row **first** from the frame height and gives the option list what remains, scrolling within it.
SECURITY-AUDIT B3's defect is a modal sized from unwrapped content, which ratatui clips silently;
reserving the row first makes the escape hatch un-displaceable by growth in `IrreversibleAct` or
`survivors`.

---

## 3 · Where every field is read — and the four that are dropped for lack of a reader

Instance #16 is this project's most-repeated defect: a declared control nothing consults, with a
green test asserting the declaration. The table names a reader for every field this ADR introduces,
or drops it.

| Field | The function that reads it |
|---|---|
| `Run::raises_to` | `escalation::escalation_route`; `Engine`'s `ModelStep::Ask` arm (`engine.rs:1236`), which refuses any run whose value is not `Nobody`; `Engine`'s `Escalate` arm |
| `Checkpoint::raises_to` | `Run::restored`; `control.rs:238`'s version comparison refuses an older blob before the field is read at all |
| `NotRaisableReason` | `Engine`'s escalate arm, which selects the harness constant pushed into the raiser's window and the `EventKind::RunFailed` payload |
| `Ports::escalations` | `Engine`'s `ModelStep::Escalate` arm — the only caller of `EscalationPort::raise` |
| `PauseReason::AwaitingEscalation` | `RunStatus` rendering, and `Engine`'s resume path; the `id` is what `EscalationDesk::resolve` is keyed on |
| `LoopOutcome::Raised` | `daemon.rs`'s outcome match; `engine.rs`'s child-return `note` match (§4) |
| `EscalationRequest::severity` / `category` | `EscalationDesk::advance` (stored on `Escalation`), then `EscalationView` → the surface's rows |
| `EscalationRequest::sentence` | `Engine`'s escalate arm, which refuses `Some` by name under `EscalationArm::Typed`; the surface's body row only when the arm permits it |
| `EscalationRequest::artifact` | The surface's artifact row, which composes a path from the handle; adjudicated as an `ArgumentRole::Target` at `escalate`'s manifest |
| `Escalation::lineage` | `EscalationDesk::advance` appends; `EscalationView`'s approving-chain rows render |
| `Pending::at` | `EscalationDesk::advance`, which returns `AdvanceError::NotYours` when `by != at`. **This is the saturated-floor guard** and is the one field whose deletion no existing mechanism would notice: ADR-023's floor reads "blocked" for every pending id and discriminates none |
| `Pending::opened_ms` | `TerminationCost::age_ms` is a *run* age; `opened_ms` is the escalation's. **Flagged**: if the window does not render "raised N minutes ago", drop it |
| `TerminationCost`'s six fields | `TerminationCost::rows`, one row per field, guarded by `every_termination_cost_field_is_rendered` (§5, test 14) |
| `SourceEvidence` | `SourceEvidence::row`, produced by `provenance_from_journal` counting `ToolCompleted` rows for tools whose manifest declares a `Url` `Target` |
| `TERMINATE_CANARY` | `Choice::Terminate`'s wire spelling, and the two assertions in test 1 and test 9. **It is read by the product, not only by tests** — a canary that only tests read is a test fixture, and a fixture cannot go missing from a body |

**Dropped, deliberately, and each is the preferred outcome:**

1. **`AgentLevel`, all five variants.** Two definitions of tree position, the second of which
   `Run::adopted_by` and `Run::detached` silently falsify — both set `parent` and leave a
   construction-derived level untouched, and `escalation_route(Master, None)` and
   `escalation_route(Worker, None)` both returned `NotRaisable`, so after a `Detach` an escalation
   vanished with no event and no note. Replaced by `RaisesTo` plus `Run::parent`.
2. **`AgentLevel::may_hold_create_grant`.** Its enforcement site could never see it false. The
   narrowing check at `engine.rs:2630-2641` refuses any `t` in `req.tools` not in
   `run.profile.exposed_tools()`, so a child gets `run` only if the parent holds `run`; every run
   holding `run` is a level for which the method returns `true`. A test of it would be green with the
   method returning `true` unconditionally and green again with it deleted — `inline_threshold_bytes`
   exactly. The invariant is worth having and is asserted where it *can* fail, in test 2.
3. **`AgentLabel::for_run`.** A second answer to a question `run.rs:100-114` explicitly closed, and
   its proposed rendering (`top-agent 4f2a91`) is the hex prefix that doc rejects by name.
4. **`EscalationRequest::forwarding: Option<EscalationId>`.** `EscalationDesk::advance(id, by, route)`
   already expresses *"forward the escalation addressed to me"*, and `Pending::at` is the authority
   for whether it is addressed to you. A second way in is a second definition of the same act, and
   the model would be naming an id on both paths. If forwarding needs a distinct shape it should
   arrive with the reader that distinguishes it.

---

## 4 · Why the alternatives lost

Recorded rather than deleted, because this project records rejected alternatives.

**Collapse `LoopOutcome::Escalated { question: String }` into `Escalated(EscalationId)`.** This was
the first design's own recommendation and it **destroys the `ask` tool**. `engine.rs:1236-1245`
produces that variant from `ModelStep::Ask` — Marlowe's *"put a question to the user and wait"* — and
`daemon.rs:2899` is `LoopOutcome::Escalated { question } => ("escalated", question.clone())`, which
is how the user learns what was asked. Two different facts would share one variant and the more
common one would lose its payload. **`Raised(EscalationId)` is a new variant and `Escalated` is left
alone**; the child-return match at `engine.rs:2936` gains one arm returning a harness constant,
matching the discipline the existing `Escalated` arm already keeps.

**Put `AgentLevel` (or `RaisesTo`) on `CapabilityProfile`, beside `reads_untrusted`.** Two reasons and
the second is decisive. `profile.rs` is §13-guarded, so a routing field there makes every M3 tree
change a boundary prompt for no security gain; and the value is a property of the *tree*, which
`CapabilityProfile::new` cannot see — so it would have to be supplied, i.e. declared, i.e. reachable
from a spawn request, which is the model-declared value this design exists to avoid. This is ADR-032's
argument for keeping the granted egress set on the profile, run in the opposite direction: **put the
value where the invariant that constrains it is already enforced.** For `RaisesTo` that is `Run`,
whose constructors are the only writers and which already inherits `trust_floor` the same way.

**Add `kind: AgentKind { Master, Worker }` to `SpawnRequest`.** Nothing would read it. A master is a
child whose `exposed_tools` contains `run`, and `Engine::spawn` already checks every requested id
against the parent's set. A second field carrying the same fact is #16 by construction, and it would
land in the same commit as Session C's `role` field, doubling the pinning cost of a shape that is not
pinned yet. If the two ever disagreed, **the tool set is what the child actually gets.**

**Keep `ModelStep::Ask(String)` for agents and let the harness validate the string, avoiding a
§13-guarded edit.** That is the free-text arm shipped as the product. §2's invariant is that nothing
but typed structure crosses upward, and a validated paragraph is still a paragraph: `severity`,
`category` and `lineage` would have to be inferred from prose by something, and whatever infers them
is a model reading attacker-shaped text on the decision path. It also leaves A8 with no way to
express its first arm. The guarded edit is real and the human must approve it; the alternative is to
build the thing §9.1 predicts will fail and ship it as the default.

**Give `EscalationDesk` a `body(&self, id) -> Option<&str>` and rely on Marlowe's profile not
exposing a tool that calls it.** *"Cannot read it"* would then be a fact about a registry entry, and
the registry is configuration — an MCP descriptor, a skill, a future `recall` variant or a
well-meaning debugging path could all reach it. **The signature with no body parameter cannot be
reached by adding a caller.** Same reasoning as `BlastRadius` having no field for the command.

**Let a spawner supply a human-readable agent name (§3.2's `CodeProjectLeader`).** A model-chosen
display string rendered to a human about to choose between labelled options can name itself
`Marlowe`, `SYSTEM`, or the label of an adjacent option. `sayable` is harness-derived and is what
`/runs` and `/watch` already address. A real name is worth having and belongs with Session C's `role`
field in one deliberate pinning act.

**Express the quarantined reader's inability to escalate as an escalation budget of `0`.** Instance
#17 verbatim. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on iteration one and
the reader pauses before its first model call — the exact failure ADR-041 produced, where containment
stayed perfect and every page came back as *"the content could not be condensed"*. The capability is
withheld structurally: `RaisesTo::Refused` has no route, and there is no counter.

**Carry the escalation to the user on `TurnEvent` / the conversation socket.** It halts the
conversation, which §0 exists to stop, and it routes attacker-shaped prose through the pane Marlowe
is speaking in — so *"Marlowe cannot read it"* would rest on a filter rather than on a channel he is
not on. `control_plane.rs` already exists as a second listener on an advertised port.

**Weaken the `terminate` substring search until the acceptance zero comes back.** Named here as a
rejected alternative rather than as an oversight, because it is the one a future session will reach
for first. §1.1 is why.

---

## 5 · The tests, each with the mutation that reddens it

A test whose reading is the same whether or not the mechanism works is instance #15 and is not
proposed. Where an assertion is green on today's HEAD before anything is built, that is said.

1. **`terminate_never_reaches_a_model`** — `crates/marlowe-provider/tests/terminate_is_absent_from_the_request_body.rs`.
   6 profiles × 3 adapters = 18 bodies. Asserts `TERMINATE_CANARY` and `TERMINATE_LABEL` occur zero
   times; the persona marker present 18/18 (positive control, so a body that failed to build cannot
   report a clean zero); `bodies.len() == 18` with non-empty `messages`; and a **leak control** — a
   nineteenth body deliberately built with an `EscalationView` serialized into the brief, asserted to
   **contain** the canary, so the search itself is proven. *Mutation:* put `TERMINATE_CANARY` in
   `governance_prompt()` → red. *Mutation on the leak control:* break the substring scan → the
   nineteenth assertion fails before any zero is reported. **This test is not §11's row 2** — it
   reads bodies built in a test process. It is a breadth check across adapters, and test 9 is the
   acceptance measurement.
2. **`no_reachable_spawn_gives_a_leaf_the_create_grant`** — `crates/marlowe-loop/tests/escalation_routing.rs`.
   Exhaustive over (parent `RaisesTo` × tool sets containing and omitting `run`), asserting no
   reachable pair produces a `RaisesTo::Refused` run holding `run`, with a header naming the
   narrowing check at `engine.rs:2630-2641` as the reason. *Mutation:* delete the narrowing check →
   red. This is what replaces `may_hold_create_grant`: a future relaxation of `composes_spawn_targets`
   (`engine.rs:3237`) or of the narrowing turns the test red rather than turning a dead method live.
3. **`a_quarantined_reader_cannot_raise_and_the_refusal_is_audible`** — same file. Drives a real
   `condense_batch` read, has the reader emit `ModelStep::Escalate`, asserts `escalation_route` is
   `NotRaisable(ReadsUntrusted)`, that the desk received nothing, and that the reader's own window
   gained the harness constant. *Mutation:* derive the refusal from `req.tools` instead of
   `profile.reads_untrusted()` → the reader classifies `Parent` → red. **This is the assertion the
   first design could not make**, because its `ToolSpawned` variant was constructed by nothing.
4. **`a_worker_escalation_stops_at_its_master_and_never_reaches_the_root`** — same file. A real
   four-level tree through `Engine::spawn`; asserts the desk's delivered `Recipient` is the master's
   `RunId`, `lineage == [worker]` then `[worker, master]`, and that the root's `SessionState` gained
   zero blocks. **Plus a negative control, without which this test is worthless**: the same tree
   re-run through a `RouteOverride` double returning `Recipient::Run(root_id)`, asserting the root's
   window **does** gain the block. Two of the original four assertions are green on today's HEAD —
   `engine.rs:2936` already swallows a child's `Escalated` into a harness constant, so nothing crosses
   today either.
5. **`an_agent_cannot_reach_the_user_through_the_secretarys_door`** — same file. A child emits
   `ModelStep::Ask`; asserts a named refusal block and that no `LoopOutcome::Escalated` escapes.
   *Mutation:* delete the `raises_to` check in the `Ask` arm at `engine.rs:1236` → red. The precedent
   is `MemoryWrite`'s `if !run.profile.may_write_memory()` refusal a few lines below at
   `engine.rs:1260`, which `memory_write_ownership.rs` already covers. The first design stated this
   invariant in a doc comment and tested it nowhere, at a site CLAUDE.md names as the unguarded call
   site whose deletion evaporates a boundary with every guarded file untouched.
6. **`a_detached_run_that_raises_is_told_so`** — same file. `OrphanPolicy::Detach`, then raise;
   asserts `NotRaisable(Detached)`, one `EventKind::RunFailed` row, and the constant in the raiser's
   window. *Mutation:* collapse the reason to a bare `NotRaisable` → the event carries no reason → red.
7. **`a_checkpoint_without_a_route_is_refused_by_name`** — `crates/marlowe-loop/tests/durable_route.rs`.
   A previous-version blob decodes to the named `ResumeError`. *Mutation:* `#[serde(default)]` on
   `raises_to` → the blob decodes → red.
8. **`a_pending_escalation_survives_a_daemon_restart`** — `crates/marlowe-daemon/tests/escalation_durability.rs`.
   Raise, drop the desk, `EscalationDesk::from_journal`, assert the same id at the same recipient.
   *Mutation:* keep the `BTreeMap` and skip the `Recorder` write → red.
9. **`terminate_never_reaches_a_model_on_a_real_daemon_turn`** — `crates/marlowe-daemon/tests/terminate_never_reaches_a_model.rs`.
   **This is §11 row 2.** A `RecordingDriver: ModelDriver` through `Daemon::ask_streaming_with_driver`
   (`daemon.rs:1772`) captures every `(ContextView, ExposedSet, CallLimits)` the **running** process
   hands it. `captured.len() >= 1` is a hard assertion, not a guard that early-returns: ROADMAP's C
   row records that provider selection returns early when `Availability::probe` finds no model, and a
   skipped integration test prints nothing and reads green. The `cross_encoder_reference.rs` idiom —
   skip loudly, fail when the precondition resolves write-only.
10. **`the_escalation_explanation_is_in_marlowes_body_and_in_no_agents`** — `crates/marlowe-daemon/tests/escalation_explanation.rs`.
    Fresh conversation, **no escalation**: both §3.3 sentences in the `system` role of the first
    captured body; then a forced compaction past 0.70 fill, still there; then absent in all agent
    bodies. *Mutation:* copy `secretary_notes` in either child loop (`engine.rs:2205-2208` or
    `:2796-2800`) → red. *Mutation:* assert lazily at the first escalation → the pre-escalation
    assertion fails. The first design's version asserted presence in Marlowe's body only, and was
    green on the leaking build.
11. **`the_escalation_body_is_absent_from_marlowes_window`** — `crates/marlowe-daemon/tests/marlowe_cannot_read_an_escalation.rs`.
    Marker `ESCALATION-BODY-9f31` in `sentence` and artifact content; absent from the stored
    `SessionState` and every captured body; and Marlowe's window gained **exactly one** block equal to
    the rendered `Notice::EscalationRaised` — so *"the notification arrived without the body"* is
    distinguished from *"nothing arrived"*.
12. **`an_option_label_cannot_contribute_a_line_or_move_the_cursor`** — `crates/marlowe-contract/tests/escalation_labels.rs`.
    Corpus of `\n`, `\r\n`, `\u{1b}[2K\r`, `\u{202E}`, `\u{2028}`, `\u{200B}`, `\u{E0001}`, 4,000
    chars. **Trim-dependent control:** asserts first that each raw input actually violated something,
    so a clean corpus fails rather than passing vacuously — `adr023_live.rs`'s first-run failure in a
    new place. Plus `serde_json::from_str::<OptionLabel>("\"a\\u001b[2Kb\"")` is `Err`.
    *Mutation:* `#[derive(Deserialize)]` → the field-wise decode succeeds → red.
13. **`terminate_survives_a_hostile_option_list`** — `crates/marlowe-surface/tests/escalation_overlay.rs`.
    Maximal options, maximal cost, four `IrreversibleAct` rows, two `Survivor` rows, a long host —
    rendered at **24×80 and 10×40**; walks both buffers for the label's cells at the reserved row; no
    cell fails `is_renderable`; `EscalationView::new` returns `Err(TooManyOptions)` on a fifth option.
    *Mutation:* size the modal from unwrapped content → **red at 10×40 before it is red at 24×80**,
    which is why both sizes are in the test rather than one.
14. **`the_termination_cost_comes_from_the_journal_and_not_from_the_agent`** — `crates/marlowe-daemon/tests/termination_cost_is_journal_derived.rs`.
    A subtree writes 3 files, pushes 0 commits, one `Detach` child; the top-agent's option text claims
    *"six hours, 40 files"*. Asserts `artifacts == 3`, one `FilesWritten { count: 3 }`, no
    `CommitsPushed`, `survivors` names the detached child by its `sayable` name,
    `spend_micros_usd == run.spent.micros_usd`, and that `40` and `six hours` appear only inside the
    normalised option region. Paired with `every_termination_cost_field_is_rendered`
    (`marlowe-view/tests/`), which mutates each of the six fields and asserts the rendered rows change
    — the #16 guard for this type.
15. **`terminate_names_the_children_it_cannot_kill`** — `crates/marlowe-view/tests/`. A subtree with
    one `Detach` child; asserts the rendered frame contains that child's name in the survivors row.
    *Mutation:* derive `survivors` from `Vec::new()` → red. This is the test that keeps
    `TERMINATE_LABEL` honest.
16. **`an_agent_cannot_suppress_reorder_or_restyle_the_escape_hatch`** — `crates/marlowe-surface/tests/`.
    **This is §11 row 3, the only one of the three not satisfiable by an empty implementation.** The
    agent's own option text contains `TERMINATE_LABEL` and Box-Drawing / Block-Elements chrome
    glyphs; asserts both are neutralised in the rendered buffer — `chrome::mark_reserved`
    (`marlowe-surface/src/chrome.rs:134`) already substitutes every reserved codepoint in model text —
    and that the harness row is still at the reserved position and still the only cell matching
    `Choice::Terminate`. *Mutation:* render agent option text without `mark_reserved` → the forged
    row appears and the "only one" assertion fires.

---

## 6 · What this decision does NOT close, and what is the human's

### 6.1 · The human's, by name

* **The §13-guarded edit.** `crates/marlowe-loop/src/driver.rs` is on `PROTECTED`. `ModelStep::Escalate`,
  `EscalationRequest`, `EscalationPort` and `NoEscalation` all land in it. Nothing else in this design
  touches a guarded path — `profile.rs`, `adjudicate.rs`, `taint.rs`, `provenance.rs`, `egress.rs`,
  `steer.rs`, `memory.rs`, `mcp.rs` and `pin.rs` are untouched, and `EventKind` lives in
  `journal/event.rs`, which is not guarded (only `journal.rs` and `signature.rs` are). A
  `DECISIONS.md` entry arrives with it, per the hook's own convention.
* **The pinned contract.** `CONTRACTS.md` §5's `Run` gains `raises_to`, and a new §5.2 pins the
  escalation record. **§5's pinned `Run` is already divergent from the code in two directions** — the
  pin lists `result: Option<ContentRef>` which `run.rs` does not have, and the code holds a private
  `trust_floor` the pin does not list (`run.rs:680`). Adding a field privately behind an accessor is a
  route `trust_floor` opened. **Do not take it quietly**: pin the field, and raise the pre-existing
  divergence separately rather than exploiting it. A pinned struct that has silently stopped
  describing the type is the documentation half of instance #14.
* **The `marlowe-view` → `marlowe-contract` dependency**, which changes the stance of a
  zero-dependency crate whose description says *"Shapes only."* Its own `DECISIONS.md` entry.
* **Is the ADR-023 latch per-run or per-session?** `daemon.rs:2609` builds a fresh `Run::root` per
  user message at `trust_floor: TrustClass::UserAsserted` (`run.rs:680`), so §2.1's *"a Marlowe who
  ingests one finding can never compose a target again, for his life"* is not true of the shipped
  daemon. **This is not re-opened here.** SECURITY-AUDIT §8 answered it on 2026-08-12 and the standing
  instruction is to record that answer in `DECISIONS.md`, not to raise it again. Nothing in this
  design depends on it: §3.2's containment is a routing fact, not a floor fact.
* **The fourth model role is not named here**, and nothing in this design chooses one. The escalation
  window's own routing stays `ModelRoute::Worker`, unchanged.
* **A human-readable agent name** belongs with Session C's `role` field in one deliberate
  `SpawnRequest` pinning act, not smuggled in as a display convenience.
* **Does Marlowe learn an escalation's outcome?** M3-DESIGN §12 item 1. `secretary_notice` has no
  outcome parameter, which is the safe default and is also not a decision a session should take
  silently: *"the top-agent was terminated"* is arguably a fact Marlowe needs in order not to keep
  referring to work that no longer exists.

### 6.2 · Not closed, and not the human's — just unbuilt

* **There is no lifecycle story for how a pending escalation reaches a human on a serial daemon.**
  Children run inline and synchronously inside the parent's `Engine::run` (`engine.rs:2879-2894`), and
  M3-DESIGN §6 records that the daemon is serial and one connection is held for the whole of a turn.
  A worker raising an escalation is four stack frames deep inside a turn that holds the conversation
  socket. `PauseReason::AwaitingEscalation` and the journal-backed desk make the *state* durable and
  addressable; they do not make the *delivery* concurrent. `control_plane.rs` is the listener that can
  carry it, and the design of that hand-off is not in this ADR.
* **`ArtifactHandle` cannot be written as `ArtifactHandle(pub ContentHash)`** — neither `ContentRef`
  nor `ContentHash` exists as a Rust type (§2.6). The buildable shape is a validated hex `String` on
  `DocumentRef`'s precedent, and whoever builds it should confirm the width against the store rather
  than inherit `128-bit` from this sentence.
* **`EscalationId` does not exist** and is assumed throughout. It should be a `Uuid` newtype on
  `RunId`'s model (`run.rs:37`), and it should not be `Uuid::new_v4` if the desk's journal rebuild
  needs it to be reproducible from the event — that is a decision for whoever writes `from_journal`.
* **`Choice::Terminate` has no keybind.** §11's amended row 2 asserts *"its harness-authored label
  **and keybind** appear in no `request_body`"*, and this design specifies no key. The surface's key
  handling for the escalation overlay is unaddressed and the row cannot be fully satisfied until it
  exists.
* **`EscalationArm::FreeText` is §9.1 A8's control and must refuse to construct without an explicit
  flag** — a load-time error, never a permissive default. A control expected to fail that is reachable
  by omission is the "defaults that make a mismatch unobservable" family in its most expensive form.
  §9.1's amendment at `2fe2986` also moved where A8's arms vary — to `Engine::spawn`'s note match —
  and this ADR does not restate that; it only keeps `EscalationRequest::sentence` as the shape arm (b)
  needs.
* **Nothing checks that a spawning run was ever exposed `run`.** `Engine::spawn` (`engine.rs:2528`)
  validates the child's requested tools against the parent's set but never that the parent holds `run`
  itself, and `ModelStep::Spawn` goes from the loop's match straight to `self.spawn`. Pre-existing;
  this design makes it consequential, because a run that emits an unoffered `run` call creates a child
  whose `RaisesTo` — and therefore whose ability to reach a human — follows from a call the harness
  never agreed to. **Check `SECURITY-AUDIT.md` before filing this as new.**
* **SECURITY-AUDIT B1, B2 and B3 arrive intact on the CLI path** if the escalation is rendered the way
  `agent.rs` renders an approval today. The CLI renderer is in scope for whoever builds this and is
  not a new finding.
* **Ollama capacity, measured on this machine and not to be cited later.** Nothing on the escalation
  path may call a model: `TerminationCost` and `SourceEvidence` are journal replays. ADR-044 resolves
  the embedder's provider against free VRAM at load, so a summarising escalation window would push the
  embedder to CPU with a correct-looking log line. Any later change that summarises an escalation
  re-opens this **on numbers that must be re-measured rather than quoted from here.**
* **If either new `escalation.rs` is ever added to `PROTECTED`**, its row goes into CLAUDE.md's table
  and into `EXPECTED_PROTECTED` in `boundary_hook.rs:109` **in the same commit** — instance #19's fix.

---

## 7 · The adversarial pass, recorded rather than hidden

**The critique's verdict on the first design was `broken`.** It is quoted rather than paraphrased
because the reason is the finding:

> **Fatal:** The §11 acceptance row it is built to satisfy cannot be measured the way it proposes:
> `terminate` already appears in every agent's `request_body` from two production sources … so
> `terminate_appears_in_no_agents_request_body` is red on a correct build, and the only cheap repair
> is to weaken the search until the zero stops being evidence. That is instance #15 committed against
> the acceptance table itself.

Twenty-one defects were raised. Six changed the design's structure and are named here as defects of
the **first** design, because an ADR that reads as though the first draft were right is worth less
than one that shows what nearly shipped.

| # | Defect of the first design | What changed |
|---|---|---|
| 1 | **The headline acceptance test is red from two production sources.** Its only exits were to weaken the search (#15 against the acceptance table) or rename a live tool parameter to protect a test | `TERMINATE_CANARY` as the wire identity, asserted alongside `TERMINATE_LABEL`, with a **leak control** proving the search itself. §11's own amendment supersedes the row (§1.1) |
| 2 | **`ModelStep::Escalate` had nowhere to go.** `Ports` has no escalation member and `marlowe-loop` cannot see `marlowe-daemon`; the named reader `Engine::escalate` had no destination. Every proposed test lived on one side of the seam, so nothing could see it | `EscalationPort` + `NoEscalation` in `driver.rs`, `Ports.escalations`. This is the `done`-to-tool-host failure's shape: two individually coherent halves and no seam |
| 3 | **The quarantined reader classified as `Worker`, and got a live route to its parent.** `condense_batch` builds it via `Run::child` (`engine.rs:2146`), never `Engine::spawn`, so the level derived from `req.tools` had no `SpawnRequest` to read; and `AgentLevel::ToolSpawned` — the variant the whole `NotRaisable` argument hung on — was **constructed by nothing** (#16) | `RaisesTo::Refused` derived from `profile.reads_untrusted()`, which `Run::child` already receives. **The design's strongest security claim was attached to an unreachable variant while the run that actually holds attacker bytes could raise** |
| 4 | **`AgentLevel` on `Run` was a second definition of tree position**, falsified silently by `adopted_by` and `detached`; after a `Detach` an escalation vanished with no event and no window note | `RaisesTo` (one inherited bit) + `Run::parent`, and `NotRaisableReason::Detached` made audible |
| 5 | **`may_hold_create_grant` could never return false at its enforcement site** (#16), and `ContentRef` carried a `summary` upward — free text smuggled inside the typed arm, invisible to A8's own comparison | Method deleted, invariant asserted where it can fail (test 2); `ArtifactHandle`, hash only |
| 6 | **`LoopOutcome::Escalated { question }` was to be collapsed**, destroying `ask`; §3.3's sentences were to go in `governance`, which both child loops copy; `TERMINATE_LABEL` promised what `Control::cancel` cannot deliver | `Raised` as a new variant; `secretary_notes`; a narrower label plus `survivors` |

Two of the critique's own observations are recorded as **passes**, because a review that only finds
defects teaches less: the first design refused an escalation budget of `0` by name (#17 avoided), and
it anticipated #19 by writing down that a new `PROTECTED` row must land in CLAUDE.md's table and in
`EXPECTED_PROTECTED` in the same commit. Both survive into this ADR.

---

## 8 · What this ADR does NOT claim

* **It does not claim the escalation channel is safe.** M3-DESIGN §2.2 concedes the upward channel is
  the deliberate hole with a human at the end of it, and §3 calls it the most dangerous channel in the
  system. Nothing here narrows that; it bounds what crosses and who sees it.
* **It does not claim §11's rows are satisfied.** Row 1 is green on an empty implementation, row 2
  needs the running process and a keybind that does not exist, and row 3 is the only one with teeth.
* **It does not claim the tests exist.** None is written. Every "mutation → red" above is a
  prediction, not a measurement, and this ADR contains **no** measured red-before-green run.
* **It does not re-open the latch's scope, the artifact-as-`Target` question, or `Channel::Agent`.**
  The first is SECURITY-AUDIT §8's and the human's; the second is answered by `manifest.rs:84-86`; the
  third gains no producer here — `grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v
  "fn ingest_external"` still returns nothing, and ADR-062's conclusion is untouched.
* **It does not claim `Echo` sanitises anything.** §2.4 says the opposite, in place.

---

## 9 · Citations re-verified at `2fe2986`, including two the critique got wrong

Line numbers in this repo drift, and the critique corrected several of the first design's. **Two of
its own corrections are themselves wrong on today's tree**, which is the point of running the check
rather than inheriting it — ROADMAP's C row already warns in its own parenthesis that five of seven
citations in it had drifted.

| Claim | As cited | Verified today | Effect |
|---|---|---|---|
| `run` tool's `orphan_policy` description | `builtin.rs:695` | `builtin.rs:695` | correct |
| The spawn receipt's terminate spelling | `engine.rs:2731` | `engine.rs:2731` | correct |
| `Run::root` in the daemon | design said `daemon.rs:2486`; critique said `2609` | **`daemon.rs:2609`** | critique correct; `2486` is `WorkspaceScope::new()` |
| `trust_floor: UserAsserted` in `Run::root` | design said `run.rs:680`; **critique "corrected" it to `682`** | **`run.rs:680`** (`678` is `last_checkpoint: None`) | **the design was right and the correction was wrong** |
| `NoControl`, the fallback-port precedent | critique said `control.rs:113-131` | **`driver.rs:692`**, used at `engine.rs:2264` | wrong file; the precedent is real and is in the guarded file itself, which strengthens the fix |
| The quarantined reader's child `Ports` | critique said `engine.rs:2880-2891` | **`engine.rs:2265-2275`** (`memory: None` at 2269). `2881-2891` is the **ordinary spawn's** | **inverting these would withhold the port from ordinary children and hand it to the quarantined reader** |
| `Ports` | `engine.rs:217-227` | `engine.rs:219-229` | cosmetic |
| The narrowing check | `engine.rs:2631-2640` | `engine.rs:2630-2641` | cosmetic |
| The governance copy loops | `engine.rs:2206-2208`, `2798-2800` | `engine.rs:2205-2208`, `2796-2800` | cosmetic |
| `ArgumentRole::Target` lists *identifier* | `manifest.rs:85` | `manifest.rs:84-86` | cosmetic; the quoted text is exact |
| `GovernanceConstraint`'s hand-written `Deserialize` | `context.rs:403-425` | `context.rs:408-425` | cosmetic |
| The ADR-055 listener | `marlowe-daemon/src/{watch,watch_client}.rs` | **`control_plane.rs`** and `watch_client.rs`; **there is no `watch.rs`** | corrected |
| `ContentRef` / `ContentHash` as Rust types | assumed to exist | **neither exists**; `grep -rn "ContentRef" --include=*.rs crates/` returns doc comments only | §2.6 — cannot be built as specified |
| `Daemon` has no model-driver seam | ADR-062 §6.5 | **`ask_streaming_with_driver`, `daemon.rs:1772`** | ADR-062's sentence is stale; the daemon tests are writable |
| `marlowe-view` has an empty `[dependencies]` | claimed | confirmed | the stance change is real |
| `marlowe-surface` already depends on `marlowe-contract` with the argument written down | claimed as the precedent | confirmed in its `Cargo.toml` comment | the **argument** transfers, the **precedent** does not (§2.7) |

**Everything in this table was established by reading and grepping the tree at `2fe2986`. Nothing in
this ADR was established by running a test, because no code exists to run.** That distinction is
stated rather than implied, because a table of greps reads like a table of tests.
