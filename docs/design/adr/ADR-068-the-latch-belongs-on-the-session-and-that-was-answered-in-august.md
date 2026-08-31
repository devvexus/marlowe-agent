# ADR-068 · The latch belongs on the session, and that was answered in August

**Status:** **Accepted as a recording, M3 Session C, 2026-08-31, by Matthew. THE SCOPE CHANGE ITSELF
REMAINS DEFERRED.** ***“PROPOSED — needs the human’s approval. DESIGN ONLY, NO CODE”* — the second
half still stands.** What is accepted is §1’s finding, that `SECURITY-AUDIT.md` §8 is **half-fixed** by
`6a1f4f5` and the half that is missing is the one §8 named, together with §3’s mechanism as the shape
the build will take when it is authorised. **Nothing in §3 or §4 is built, and §9.1’s question —
whether the second clause is built at all — is not answered here.**

> **THE DEADLINE, CONFIRMED BY THE HUMAN ON ACCEPTANCE AND UNCHANGED FROM `DECISIONS.md`’s
> 2026-08-30 entry: DECIDED BEFORE SESSION D STARTS, NOT AFTER.** D is what gives `ingest` its first
> correct caller, and on that day the per-turn reset becomes live **together with** the compaction
> stamp and the trim marker in the same path. A decision taken after D has shipped is a decision taken
> with the hole already open.
>
> **Deferring is safe today only because layer 3 is unreachable, and that is a command rather than a
> citation:** `grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"`
> returns nothing. The day it does not, this deferral expires whether or not anyone re-reads this
> line.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | `SECURITY-AUDIT.md` §8's second instance, one clause (§9.4 below): the audit calls the RUN-scoped egress grant *"a second instance of §8"*, and it is the **opposite** instance. Records `SECURITY-AUDIT.md` §8 as **half-fixed** by `6a1f4f5` rather than fixed. Corrects `crates/marlowe-loop/src/durable.rs`'s `decode_all` doc comment, which claims a property the file does not have (§4.2) |
| **Depends on** | ADR-023 (the latch, and its stated per-run scope), ADR-032 §3.1 (the egress grant's scope — **separated**, not answered), ADR-038 / ADR-039 / ADR-041 (why no reachable path taints a parent today), ADR-053 (what a checkpoint must carry), ADR-062 (`ingest` has no correct production caller), M3-DESIGN §2.1 and §7, `SECURITY-AUDIT.md` §8, CONTRACTS §5, §6, §12 |
| **Contract change** | **None for the recording.** Three deliberate amendments **if** the build is approved (§10) — CONTRACTS §6 gains a sentence, §5's `Run` gains `trust_floor`, and `CHECKPOINT_VERSION` 1 → 2 is a §12 wire change |
| **Code change** | **None.** One test may land with zero product change (§7.1). Everything else in §3 and §4 is specified and **not built** |

Every line number below was re-read at HEAD `03fb1d6` on 2026-08-30. `crates/marlowe-daemon/src/daemon.rs`
is under concurrent edit by another session; its numbers are the most likely to drift and every one of
them is also given by symbol. ROADMAP line 860 is the standing warning that this exact row's citations
have drifted before.

---

## 1 · The finding: §8 is half-fixed, and the half that is missing is the one it named

`SECURITY-AUDIT.md` §8 (lines 126–131), dated 2026-08-12, in full:

> Compaction stamps a summary of an untrusted window at a **fixed** `AgentInferred`, and the trim
> omission marker is built at a **hardcoded** `AgentObserved`. Within a run the latch absorbs both;
> across turns it does not, because `Daemon::ask` builds a fresh `Run::root` at `UserAsserted` over a
> persisted `SessionState`. **The latch belongs on the session, not the Run.**

E5's fix line spells out that this is an *and*: stamp `min(AgentInferred, floor_of(replaced))`, **and**
persist the latched floor on the session, not only the `Run` — *"the object that outlives the turn is
where a monotonic latch belongs."*

**`6a1f4f5` built the first clause and not the second.** The three facts that make the second clause
still true are each a read, not an argument:

| Fact | Where, verified at `03fb1d6` |
|---|---|
| A fresh `Run` per user message | `Daemon::ask_streaming_with`, `let mut run = Run::root(` — `daemon.rs:2609` |
| …at the top of the lattice | `trust_floor: TrustClass::UserAsserted` — `run.rs:680` |
| …over a `SessionState` that survives the turn | `self.sessions.insert(session.to_string(), SessionMemory { state, provenance })` — `daemon.rs:2885`, into `sessions: BTreeMap<String, SessionMemory>` — `daemon.rs:777`, struct at `:667` |

So the run-level latch (`Run::latch_trust_floor`, `run.rs:613-616`, strictly monotone downward) is
reset to `UserAsserted` by every user message, and nothing carries the class across the boundary
except the blocks themselves.

### 1.1 · What is NOT claimed, stated before the mechanism rather than after it

**There is no demonstrated reachable path today that raises the floor across a turn boundary.** After
`6a1f4f5`, injected-memory blocks accumulate in `state.volatile` with no retain (`daemon.rs:2752-2758`),
compaction stamps `min` into the summary, and the daemon's only volatile removal (`daemon.rs:2828`)
touches `Skills` blocks that are constructed at `TrustClass::UserAsserted` (`daemon.rs:2830-2834`).
ADR-062 §1.1 establishes the stronger fact upstream of all of it: **`ingest_external` has no caller**,
so layer 3 cannot fire in a parent run at all. Re-verified for this entry:

```
$ grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"
                                           # (nothing)
```

**The property is therefore upheld today by three per-lever propagations rather than by a latch** —
which is precisely the arrangement ADR-023 rejected *within* a run, relocated to the conversation. The
session latch is the backstop that makes those levers non-load-bearing. It must exist before Session D
gives layer 3 a reachable trigger; it does not need to exist this week, and §9.6 says who decides when.

---

## 2 · WHICH ARCHITECTURE THIS IS FOR — read this before the mechanism

Two architectures are in play and the entry is worthless without saying which one it is a fix for.

- **SHIPPED.** `Daemon::ask_streaming_with` builds a fresh `Run::root` per user message
  (`daemon.rs:2609`) at `UserAsserted` (`run.rs:680`), over a `SessionState` in an in-memory
  `BTreeMap` (`daemon.rs:777`). **N runs per conversation.**
- **M3-DESIGN §2.1's TARGET** (`docs/design/M3-DESIGN.md:104-110`, quoted verbatim): *"Layer 3's floor
  is **monotonic and latched per run**, and Marlowe is a *permanent* run. So a Marlowe who ingests one
  research finding **can never compose a target again — not for that task, for his life.** … **The
  liaison pattern is not ergonomics; it is the only shape that survives ADR-023.**"* **One run per
  process.**

**This entry is a fix for the SHIPPED architecture. Under §2.1's architecture it is redundant**, and if
the permanent run lands, `SessionState::trust_floor` is **removed in the same commit**. Leaving both
would be two fields answering one question — *what may this conversation compose* — differing only in
an architecture that no longer exists. That is this project's most-logged defect shape, and creating it
by taking a decision to close a gap that an architecture change closes on its own would be the
expensive version of it.

**§2.1 also means the human is not being asked a fresh question.** He has already committed, on paper,
to a *stronger* version of the same answer for M3's target. §9.2 narrows what is actually open to the
part §2.1 does not cover.

---

## 3 · The decision: LATCH ON ARRIVAL, not on removal

### 3.1 · Why not a removal door — the first design, and what killed it

The obvious mechanism is a removal door: enumerate the levers that shorten the window, make each one
propagate `min` into the surviving floor, and pin the list with a test. **That was the first design and
it is rejected.** Three reasons, each a fact rather than a preference:

1. **The enumeration was already wrong.** The first design asserted *"today exactly three writers"* of
   the volatile tier — `SessionState::push` (`context.rs:451`), `Assembler::clear_tool_results`
   (`context.rs:772`, mutating `state.volatile[i]` at `:785`), and `Assembler::compact`
   (`state.volatile = next`, `context.rs:904`). There are **five**. `daemon.rs:2828` runs
   `state.volatile.retain(|b| b.source != marlowe_loop::SourceKind::Skills)` — a **removal**, on every
   non-resume turn — and `:2830` pushes a `Skills` block straight onto `volatile`, deliberately
   bypassing `push` because `SourceKind::Skills` maps to `Tier::Context` and `push` would route it back
   into the system message (`daemon.rs:2816-2818` says exactly that).
2. **The test that pinned the list could not see the two it missed.** The first design's
   `every_writer_of_the_volatile_tier_is_pinned` grepped `crates/marlowe-loop/src/**/*.rs`. The two
   live writers are in `crates/marlowe-daemon`. **Ledger instance #14 exactly: a guard whose subject is
   outside its search path reports nothing and reads as working.**
3. **The doc and the code disagreed in the door itself.** `replace_volatile`'s comment said it *"latches
   the floor over every block that is LEAVING"*; its body was `self.volatile.iter().map(|b| b.trust).min()`
   — the min over the **entire** old tier, kept blocks included. A mechanism whose comment describes a
   narrower behaviour than its code is how a later session "fixes" it into the narrower behaviour and
   removes the backstop.

### 3.2 · Latch when a block ARRIVES

Then **no removal lever — present, future, in-crate, in the daemon, or in a session nobody has written
yet — can raise the floor**, because removal is irrelevant to a value recorded at push time. There is
no list, so there is nothing that can fail to see itself grow.

**Over-latching is free, and that is why this works.**
`blocks_composed_targets(origin) = origin <= TrustClass::UntrustedContent`
(`crates/marlowe-permission/src/adjudicate.rs:50-52`, read at HEAD). `UntrustedContent = 0`,
`AgentInferred = 1`, `AgentObserved = 2`. So latching to `AgentInferred` or `AgentObserved` from
ordinary `History`, `Skills`, `Summary` and `ToolResults` blocks costs a conversation **nothing that
any adjudication reads**. Only class `0` changes an outcome.

### 3.3 · One definition of the latch

`crates/marlowe-loop/src/run.rs` already holds the rule at `:613-616`. A second hand-written copy on
`SessionState` — which the first design proposed, defending it as *"a deliberate mirror: same
signature, same return contract, so the two cannot drift in meaning"* — is the shape whose removal
**closed ledger instance #15**: `marlowe_permission::blocks_composed_targets` was made the single
definition called by both the adjudicator and the loop, and `engine.rs:874-876` says why in the repo's
own words. Two copies of a rule do not fail to drift because a comment says they must not.

```rust
// crates/marlowe-loop/src/run.rs

/// The monotone trust latch. ONE definition. `Run` and `SessionState` each hold one and neither
/// restates the rule — the same reason `blocks_composed_targets` is a single function called by
/// both the adjudicator and the loop (engine.rs:874-876).
///
/// No `Default`, and `TrustClass` must not gain one. `#[derive(Default)]` on that enum yields
/// `UntrustedContent = 0` — every fresh conversation reads as fully tainted — and `#[default]` on
/// `UserAsserted` is a fail-open reachable from any struct that derives `Default`. Ledger #17's
/// question, "does this code read the extreme value as a floor or a ceiling", has no good answer
/// here, so the value is written out at one site instead.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct TrustFloor(TrustClass);

impl TrustFloor {
    pub const fn user_asserted() -> Self { Self(TrustClass::UserAsserted) }
    pub fn get(self) -> TrustClass { self.0 }
    /// Lowers only. Returns the new value iff it moved.
    pub fn latch(&mut self, observed: TrustClass) -> Option<TrustClass> {
        if observed < self.0 { self.0 = observed; Some(observed) } else { None }
    }
}
```

`Run::latch_trust_floor` becomes `self.trust_floor.latch(observed)`. **Its public signature does not
change**, so `engine.rs:877`, `provenance.rs`, `durable_resume.rs`, `spawn_and_budget.rs` and
`crates/marlowe-daemon/tests/layer3_refuses_a_composed_target_from_an_ingested_belief.rs` all keep
compiling and every existing mutation result about it stays valid.

### 3.4 · `SessionState`

```rust
// crates/marlowe-loop/src/context.rs — struct today at :420-431

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]                 // already present at :420; MUST survive §3.5
pub struct SessionState {
    pub session: SessionId,
    pub identity: String,
    pub governance: Vec<GovernanceConstraint>,
    pub context_blocks: Vec<Block>,

    /// PRIVATE, for exactly one reason: so `push`/`push_volatile` are the only ways a block
    /// enters and the arrival latch cannot be bypassed. NOT to police removal — under arrival
    /// latching, removal is irrelevant to the floor.
    volatile: Vec<Block>,                     // `pub` today at :430

    pub lineage: u32,
    pub compactions: u32,

    /// ADR-023's floor, held on the object that outlives the TURN. Monotonic; never rises.
    /// Private: the only writers are the doors below.
    trust_floor: TrustFloor,
}

impl SessionState {
    /// Hand-written, NOT derived — `TrustFloor` has no `Default` on purpose. See its doc.
    fn default() -> Self { /* ..., trust_floor: TrustFloor::user_asserted() */ }

    pub fn volatile(&self) -> &[Block] { &self.volatile }
    pub fn trust_floor(&self) -> TrustClass { self.trust_floor.get() }

    /// A DOOR IN, and a writer of `trust_floor`. Body unchanged below the latch line.
    pub fn push(&mut self, block: Block) {
        self.trust_floor.latch(block.trust);   // <- arrival latch, BEFORE routing
        match block.source.tier() {
            Tier::Stable => unreachable!(/* unchanged, context.rs:453-456 */),
            Tier::Context => self.context_blocks.push(block),
            Tier::Volatile => self.volatile.push(block),
        }
    }

    /// The second door, for `SourceKind::Skills`: it maps to `Tier::Context` but is deliberately
    /// carried in the volatile tier so it is replaced rather than accumulated, and so it rides the
    /// cached prefix's tail (daemon.rs:2808-2818 states the measured reason). Latches identically.
    pub fn push_volatile(&mut self, block: Block) {
        self.trust_floor.latch(block.trust);
        self.volatile.push(block);
    }

    /// Removal. Latches NOTHING — deliberately, and the doc says so rather than implying it.
    /// Under arrival latching a removal cannot raise the floor, so there is nothing to carry.
    pub fn retain_volatile(&mut self, f: impl FnMut(&Block) -> bool) { self.volatile.retain(f); }

    /// Compaction's replacement (context.rs:904's `state.volatile = next`). Latches over what
    /// ARRIVES, not over what leaves — the incoming summary and the preserved live turn.
    pub fn replace_volatile(&mut self, next: Vec<Block>) {
        for b in &next { self.trust_floor.latch(b.trust); }
        self.volatile = next;
    }
}
```

**Two doors, not one, and that is a cost of the arrival design rather than a free win.** The daemon's
`Skills` push exists to defeat `push`'s tier routing, so it cannot go through `push`. `push_volatile`
is the honest shape: a second door that latches identically. The alternative — making `Skills` route
to `Tier::Volatile` in `SourceKind::tier()` — moves a measured performance decision
(`daemon.rs:2808-2814`: *"±164 chars between consecutive turns, costing a full re-evaluation of ~9,900
tokens"*) into a security refactor, and is out of scope here.

### 3.5 · `serde` is a way in, and a checkpoint is the caller

`SessionState` carries `#[serde(deny_unknown_fields)]` **today** at `context.rs:420`. **The first
design replaced the derive with a hand-written `Deserialize` and did not say the unknown-field
rejection must be reproduced inside it** — a silent loss of a protection that exists now, with no test
in the workspace that would notice. It follows the pattern already in the file: `Block`'s hand-written
`Deserialize` at `context.rs:357`, `GovernanceConstraint`'s at `:408`.

```rust
/// `serde` is a way in (#12) and a checkpoint is the caller. A field-wise derive would let a stale
/// or hand-edited checkpoint declare `UserAsserted` over a window whose own blocks are
/// `UntrustedContent` — the turn-boundary hole reopened through the resume path, which is exactly
/// why `Run::restored` exists ("the restart would have become the trim", durable.rs:27).
///
/// The clamp is `min(declared, min over the state's own blocks)`, so a forged floor can only ever
/// be LOWER than claimed. The inner wire struct carries `deny_unknown_fields` because the derive
/// it replaces did, and losing that would be silent.
impl<'de> Deserialize<'de> for SessionState { /* clamped; wire struct deny_unknown_fields */ }
```

### 3.6 · The seed, at ONE site, and why it is not on `Run::root`

`Run::root` stays at `TrustClass::UserAsserted` (`run.rs:680`) and gains **no** parameter.
`Engine::run` seeds once, before its first iteration, from the state it was handed:

```rust
// crates/marlowe-loop/src/engine.rs, before the loop
// The conversation's floor is a lower bound on this run's. `Daemon::ask_streaming_with` rebuilds
// `Run::root` at UserAsserted per user message (daemon.rs:2609); this line is what makes that
// rebuild harmless. There is no caller to get it right.
run.latch_trust_floor(state.trust_floor());
```

**`engine.rs:877` does not change.** The per-iteration latch stays `run.latch_trust_floor(view.trust_floor())`.
Putting a second `min` there — which the first design proposed as
`view.trust_floor().min(state.trust_floor())` — would make two lines answer *what floor does this run
start at*, and the emit gate at `:902` would then be reading a value composed at its own site.

**A loop-ordering fact that decides which mutation reddens what**, and which the first design's vacuity
argument was stated without: `Engine::run` assembles at `engine.rs:736`; the compaction branch
`continue`s at **`:781`** and `clear_tool_results` at **`:787`** — both **upstream** of the latch at
`:877`. (The adversarial pass wrote `:782` for the first of these; corrected here from a read at
`03fb1d6`.) So on an iteration where compaction fires, the run latch never observes the pre-compaction
view at all, and E5's `min(AgentInferred, floor_of_discarded)` stamp is the sole carrier of the class
**even within the run**. Arrival latching makes this moot — the floor was recorded at `push`, upstream
of every `continue` — and that is a second, independent reason to prefer it to a removal door.

### 3.7 · Child windows: both sites, one constructor

`SessionState::new` is called for a child at **two** sites: `engine.rs:2205` (an ordinary spawn) and
`engine.rs:2796` (`condense_batch`'s quarantined reader). **The first design named only the first.**
Both route through one `SessionState::for_child(&Run, identity, &[GovernanceConstraint])` so there is
no per-site step to forget. Under arrival latching the child's floor derives from what it is pushed —
its brief and its content — and `Run::child` still carries `parent.trust_floor` unchanged (`run.rs:654`).

---

## 4 · The checkpoint path, and the version bump that must NOT be naive

### 4.1 · The fatal finding of the adversarial pass

`Checkpoint` (`durable.rs:87-108`) already carries the **run's** `trust_floor` (`:102`, set from
`run.trust_floor()` at `:135`) and, once `SessionState` gains one, a second copy inside `state` (`:107`).
Two copies drift, so `Checkpoint::restore` (`:144`) must resolve **downward**:

```rust
let floor = self.trust_floor.min(self.state.trust_floor());
// ... feeds Run::restored's last parameter (run.rs:719)
```

The first design bumped `CHECKPOINT_VERSION` 1 → 2 and named a test
`a_version_1_checkpoint_is_refused_by_name`. **The adversarial pass's verdict was `sound-with-fixes`,
and this was its fatal finding: the bump does not refuse a v1 checkpoint by name — it makes every
existing checkpoint silently vanish.** The chain, all read at `03fb1d6`:

- `Checkpoint` carries `#[serde(deny_unknown_fields)]` at `durable.rs:86`, and adding a required
  `state.trust_floor` makes a v1 payload fail `serde_json::from_value`.
- The decode drops failures on purpose: `.filter_map(|(_, _, payload)| serde_json::from_value::<Checkpoint>(payload).ok())`.
  The reason is stated at `durable.rs:233-236` — *"the live journal holds 895 pre-M3 `{"step": n}`
  events, and a build that refused to start on them would make this change a migration."*
- The version check is **downstream** of that decode, at `control.rs:238`.

So a v1 payload never reaches the version check, never becomes an error naming the version, and the run
reports **"no checkpoint"** instead. ROADMAP line 832's *"100% resume from last checkpoint — **MET for
daemon restart**"* quietly stops being true and nothing goes red. **The obvious way to make the named
test pass is `#[serde(default)]` on the new field — the exact fail-open the design exists to prevent.**

### 4.2 · Two corrections to the adversarial pass's own fix, both from reading HEAD

**(a) The variant is `UnknownVersion`, not `UnsupportedVersion`.** Both the design and the critique
named `ResumeError::UnsupportedVersion { found, expected }`. No such variant exists. It is
`ResumeError::UnknownVersion { run: RunId, found: u16, expected: u16 }` at `control.rs:54`, whose
message (`:49-53`) already says the right thing: *"It is refused rather than read with defaults: every
field this build would default is a security property, and the default of each one is its permissive
value."* A test asserting a variant that does not exist is unwritable, and a builder would have
discovered that only after writing the fix.

**(b) The fix must land in `latest`, and `decode_all`'s doc comment is false.** The critique's fix
targets `JournalCheckpoints::decode_all` (`durable.rs:237-248`). **`DurableControl::resume` does not
call it.** `resume` calls `self.store.latest(run)` (`control.rs:237`), and
`JournalCheckpoints::latest` (`durable.rs:283-300`) holds its **own** duplicate
`.filter_map(|(_, _, payload)| serde_json::from_value::<Checkpoint>(payload).ok())` at `:298`.
`decode_all` is reached only by `latest_per_run` (`:277`). And `decode_all`'s own doc at `:235-236`
says:

> **Both readers go through here so the skip cannot be right in one and forgotten in the other.**

**That sentence is false at `03fb1d6`.** There are two implementations of one rule, and the resume path
— the path the failing test drives — goes through the copy the fix did not name. A fix applied only to
`decode_all` would leave the fatal defect intact while `a_version_1_checkpoint_is_refused_by_name`
looked addressed. This is instance #16's family in a doc comment: a declared property with no line of
code behind it, and the correction is owed whichever way the human rules on §9.1.

### 4.3 · The fix, if the build is approved

```rust
#[derive(Deserialize)]
struct VersionProbe { version: u16 }        // deliberately NOT deny_unknown_fields

enum Decoded { Ok(Checkpoint), Legacy, Unsupported { found: u16 } }

// ONE helper, called by BOTH `decode_all` and `latest`, per payload:
//   from_value::<VersionProbe>(&payload) Err       => Decoded::Legacy        (the 895; skip, silent)
//   Ok(v) if v.version != CHECKPOINT_VERSION       => Decoded::Unsupported   (reaches control.rs:238)
//   otherwise decode the full Checkpoint; a failure HERE is corruption and is NOT swallowed.
```

`ResumeError::UnknownVersion` is unchanged and becomes **reachable for a v1 payload for the first
time**. The 895 legacy events are unaffected: they carry `step` and no `version`, so `VersionProbe`
fails on them exactly as intended.

### 4.4 · The existing version test is green under the fatal defect, and that is a pre-existing #15

`control.rs:346-364`, `a_checkpoint_of_an_unknown_version_is_refused_rather_than_read_with_defaults`,
does this:

```rust
let mut store = MemoryCheckpoints::new();
let mut cp = Checkpoint::capture(&run, &SessionState::default(), 3, 0);
cp.version = CHECKPOINT_VERSION + 7;
store.write(&cp, a_clock()).unwrap();
```

It builds a checkpoint with the **current** struct shape, changes one integer, and stores it in
`MemoryCheckpoints` — an in-memory store that never serializes through the journal and never touches
either `.ok()` filter. **It cannot see a payload of a different shape and it cannot see the decode
path.** It would stay green through the entire fatal defect. It is not wrong about what it asserts; it
answers a question adjacent to the one §4.1 asks, and it reads identically either way. Recorded here
rather than fixed.

### 4.5 · A fourth reset door, named rather than left implicit: the daemon restart

`Daemon::sessions` is `BTreeMap<String, SessionMemory>` (`daemon.rs:777`) and
`SessionMemory { state, provenance }` (`:667`) is **in-memory only** — nothing persists it.
`ask_streaming_with` constructs a fresh `SessionState` when the lookup misses:

```rust
// daemon.rs:2630
let memory = self.sessions.remove(session).unwrap_or_else(|| {
    let mut state = SessionState::new(session_id, identity_block());
    ...
```

(The critique cited `:2670` for this; corrected to `:2630` from a read at `03fb1d6`.)

So the carried floor survives a **turn boundary** and an explicit `Request::Resume`, and **does not
survive a daemon restart** on the ordinary path. That is the same *"the restart would have become the
trim"* failure `durable.rs`'s own module header names at run scope (`durable.rs:27`), relocated to the
conversation. **The first design's headline was "the object that outlives the turn is where a
monotonic latch belongs" — and `SessionState` outlives the turn but not the process.** It is recorded
here, not fixed here, and it joins §9.3's reset-door question as the fourth de-facto door.

---

## 5 · Where every field is READ

Ledger instance #16 is this project's most-repeated defect — a declared control nothing consults, with
a green test asserting the declaration. This section exists so that the grep for readers takes thirty
seconds instead of a session.

| Field or method the decision introduces | The function that READS it | What breaks if the read is deleted |
|---|---|---|
| `SessionState::trust_floor` (the carried floor) | **`Engine::run`'s seed, `run.latch_trust_floor(state.trust_floor())`, §3.6** — and nothing else in the enforcement path | Turn 2 of a conversation that read untrusted content in turn 1 starts at `UserAsserted` and composes targets again. §7.2 test 1 goes `Blocked` → `Allowed`. **Without this line the field is instance #16 and `assert_eq!(state.trust_floor(), UntrustedContent)` would be green on a build where the control does nothing** |
| `SessionState::trust_floor`, second reader | **`Checkpoint::restore`'s `self.trust_floor.min(self.state.trust_floor())`** (`durable.rs:144`, feeding `Run::restored`'s last argument, `run.rs:719`) | Two copies of the floor in one checkpoint disagree and the disagreement resolves in whichever direction the code happens to pick. A resume becomes a second turn boundary with the same hole |
| `TrustFloor::latch` (the single monotone writer) | Called from `Run::latch_trust_floor` (`run.rs:613`), from `SessionState::push`, `push_volatile` and `replace_volatile` | Dropping the `observed < self.0` guard lets a clean turn 3 wash out a tainted turn 1 — the trim hole relocated to the turn boundary |
| `TrustFloor::get` | `Run::trust_floor()` (`run.rs:605`) and `SessionState::trust_floor()`, whose existing consumers are `Provenance::taint_for`, `engine.rs:2600`'s spawn gate, and `adjudicate`'s `blocks_composed_targets(origin)` | Existing coverage; unchanged by this decision, named so a build does not relocate enforcement onto the session copy and leave two definitions of what a run may compose |
| `SessionState::volatile()` (the read accessor) | `durable.rs:148`, `daemon.rs:2992`, and every test listed in §6.5 | Mechanical; no security property |
| `retain_volatile` / `push_volatile` | `daemon.rs:2828` and `:2830` respectively | Mechanical migration; `push_volatile` also latches |
| **`SessionState::latch_trust_floor` as a public method** | **DROPPED.** No reader outside the doors, so it is not exposed | — |
| **A `TrustFloor` field on `SessionMemory`** | **DROPPED for lack of a reader that could not drift.** See §6.4 | — |

**The dropped rows are the point of this section.** The first design proposed a public
`SessionState::latch_trust_floor` mirroring `Run`'s; under arrival latching nothing outside `push`,
`push_volatile` and `replace_volatile` has any reason to call it, and a public monotone-lowering method
is a lever a later session can reach for. It is not exposed.

---

## 6 · Why the alternatives lost

### 6.1 · Argue against §8; keep the latch on the `Run`, because the per-turn reset is DoS resistance

The strongest counter, and `run.rs:593-595` already answered it **inside** a run, in its own words:
*"Making untrusted blocks untrimmable was the alternative and is worse: one poisoned page would pin the
window open for the rest of the run, converting a security property into a denial of service."*

**Reply: the reset must not be silent and automatic.** A per-turn reset restores composed-target
authority with no human act, no event, and nothing on screen — the exact property ADR-023's latch was
introduced to remove. The DoS concern argues for a **door** (§9.3), not against the latch.

### 6.2 · A removal door — `replace_volatile` latching over what LEAVES

Rejected in §3.1: the enumeration was already wrong by two, the pinning test could not see the two it
missed (#14), the door's doc and body disagreed, and it keeps the invariant as a list of levers that
cannot see itself grow (#19). Arrival latching has doors instead of a list.

### 6.3 · A parameter or `Option<TrustClass>` on `Run::root`, or a second `Run::for_turn`

A defaulted or optional parameter is the *"default that makes a mismatch unobservable"* family that has
produced four bugs in this project: `None` reads as a new conversation and the hole returns silently.
Two named constructors move the failure to picking the wrong one at a call site, with the same silence.
The seed inside `Engine::run` (§3.6) has **no caller to get it right**.

### 6.4 · Hold the floor on the daemon's `SessionMemory` (`daemon.rs:667`), beside `state`

This is the mirror of what ADR-032 rejected for the egress grant, quoted from CLAUDE.md's own summary
of it: *"put the granted set beside the policy on the `Run` and consult it there, and the invariant is
bypassed rather than enforced."* Here the object that **holds the blocks** is `SessionState`; a floor
held beside it drifts from it — `Assembler::compact` rotates `state.session` and replaces
`state.volatile` (`context.rs:904`) without touching a neighbour field. It also puts a security carry
in an unguarded, uncontracted daemon field maintained by hand-copies at `:2630` and `:2885`, in a file
another agent is editing.

### 6.5 · Do it cheaply: leave `volatile` public and just add the field

Priced, because under-pricing is how the cheaper wrong version lands later as ergonomics.
Privatising `SessionState::volatile` is a cross-crate API break. Rust privacy is per-module, so
`durable.rs:148` breaks even inside `marlowe-loop`; integration tests are external crates, so all of
them break. The full set of `SessionState.volatile` users outside `context.rs`, read at `03fb1d6`:

- **Product:** `daemon.rs:2828` (write), `:2830` (write), `:2992` (read); `durable.rs:148` (read).
- **Tests:** `marlowe-exec/tests/adr023_live.rs:249`; `marlowe-loop/tests/compaction.rs:349,351`;
  `shortening_never_raises_the_floor.rs:88,103,137,161,178`;
  `spawn_and_budget.rs:443,1149,1165,1964,1973,1978`.

Reads take `volatile()` mechanically. The two daemon writes take the doors of §3.4. **This is a
larger build than "one door and a min", and `daemon.rs` is in it, so the migration is sequenced after
the concurrent daemon work rather than run alongside it.**

**A hazard in the enumeration itself, which neither the design nor the adversarial pass named.**
`ContextView` also has a `pub volatile: Vec<Block>` (`context.rs:471`), and `engine.rs:818` does
`view.volatile.push(Block::new(SourceKind::Governance, ...))`. A regex on `\.volatile` sweeps a
**different type** into the pinned set — the provider crate alone contributes six such hits
(`ollama.rs:362,376`, `wire.rs:189,196`, and two in its tests). §7.1's test must discriminate
`SessionState` from `ContextView` or it is measuring a set that is not the one it is named for.

### 6.6 · Build it in Session C rather than only recording it

Three reasons and the third is decisive. (1) It revisits ADR-023's stated scope, *"monotonic and
latched per run"* (`DECISIONS.md:2453`, and M3-DESIGN §2.1 line 105 restates it). (2) Its cost is a
product question, not a technical one (§9.2). (3) **No discriminating probe can be written today** — §1.1
— so the only available test is one that is green with or without the mechanism, and building a
security mechanism whose only test is vacuous is how instance #15 happened.

### 6.7 · Answer the latch and the egress grant together

§9.4. They are opposites.

### 6.8 · Make untrusted blocks untrimmable / pin the window open

Rejected verbatim in `run.rs:593-595` at run scope. At conversation scope it is strictly worse.

---

## 7 · Tests, each with the mutation that turns it red

**No test below asserts on `DegradedPath::TrustFloorLatched` or `EventKind::TrustFloorLatched`.** That
is ledger instance #15: the event fires on every run that has ever run, because the stable tier's
`Identity` block moves the floor on the first assemble. The assertion is always on
`marlowe_permission::blocks_composed_targets` and on an `Outcome`.

### 7.1 · The one test Session C could land, with zero product change

`crates/marlowe/tests/volatile_tier_writers_are_pinned.rs` — in **`marlowe`'s** test target, not
`marlowe-loop`'s, so a `--workspace --no-fail-fast` run reaches it and a `-p marlowe-loop` habit cannot
hide it. `crates/marlowe/tests/determinism_guard.rs` is the precedent: it walks `crates/` by
`read_dir` recursion from that same test target, for the same reason.

Greps **the whole workspace's `crates/*/src/`** for writes to and removals from **`SessionState`'s**
volatile tier — discriminating it from `ContextView`'s field per §6.5 — and compares against
`EXPECTED_VOLATILE_WRITERS` pinned in the test file. **Today that set is five, not three:**
`context.rs` `SessionState::push` (`:451`), `Assembler::clear_tool_results` (`:772`, mutating at
`:785`), `Assembler::compact` (`:904`), and `daemon.rs`'s `state.volatile.retain` (`:2828`) and
`state.volatile.push` (`:2830`). A control asserts the enumeration is **non-empty first**, so a broken
regex cannot pass by comparing nothing against nothing. The expected set lives outside the code being
checked (#19-resistant).

- *Mutation:* add `pub fn drop_volatile(&mut self) { self.volatile.clear(); }` to `SessionState`.
  Fails by name, printing the new site.
- *Negative control:* rename an existing writer without adding one — must also fail, proving the pin is
  on the **set** and not on a count.
- *Scope control:* delete `daemon.rs:2828`'s retain. **Must fail. This is the assertion the
  `marlowe-loop`-scoped version could not make**, and it is the whole reason the scope widened.
- *Type control:* add a `view.volatile.push(...)` to `engine.rs`. **Must NOT fail** — it is a
  `ContextView`, and a test that reddens here is measuring the wrong type.

**This test is what makes "record now, build later" safe**: it goes red on the event that would make the
unbuilt latch load-bearing.

### 7.2 · The build's tests, specified now so a cheaper wrong version cannot land later as ergonomics

`crates/marlowe-loop/tests/adr023_across_the_turn_boundary.rs` (new). **Three tests, and the second and
third are what make the first mean anything.**

1. **`a_second_run_over_the_same_session_still_refuses_a_composed_target`.** Turn 1 drives `Engine::run`
   with run A over `SessionState` S holding an `InjectedMemory` block whose class came from a real
   `DaemonMemory::ingest_external(..)` **called from the test** over a real Journal/Profile. Turn 2
   builds a **fresh** `Run::root` at `UserAsserted` over the **same** S — what `daemon.rs:2609` does —
   and drives a scripted model proposing a composed target. Asserts `Outcome::Blocked` and
   `blocks_composed_targets(origin)`.
   *Mutations:* delete the `run.latch_trust_floor(state.trust_floor())` seed → turn 2 becomes
   `Allowed`, failing at the **outcome**, not at a state read. Separately, make `push`'s `latch` call a
   no-op → same red, which distinguishes the write from the read.
2. **`the_untrusted_block_is_actually_gone_from_the_session_before_turn_two`.** Between turns, forces
   the carrier out of S and asserts **positively** that no block in `state.volatile()` is at or below
   `UntrustedContent` and that zero `SourceKind::InjectedMemory` blocks remain.
   *Mutation:* skip the removal step. **This test fails; test 1 stays GREEN.** That divergence is the
   measurement proving test 1 needs test 2 — without it, test 1 refuses on turn 2 because the block is
   still there and reads identically to a working latch. The standing rule: any assertion whose subject
   is *"X was removed"* carries an assertion that X was removed. The file header must state that this
   removal is **not reachable in the shipped product**, the way
   `layer3_refuses_a_composed_target_from_an_ingested_belief.rs` does.
3. **`a_conversation_that_never_read_anything_untrusted_runs_the_same_call`.** Identical two-turn shape,
   no ingest, no injected block; turn 2's composed target is `Allowed` and executes.
   *Mutation:* latch `UntrustedContent` unconditionally in `push`. **This control goes RED while tests
   1 and 2 go GREEN** — the `mut6-taint-everything` signature already recorded in the layer-3 probe's
   header, where the security probe passed *harder* under the mutation and only the controls caught it.

`crates/marlowe-loop/tests/durable_resume.rs` gains three:

4. **`a_checkpoint_cannot_declare_a_floor_higher_than_its_own_blocks`.** Deserialize a `Checkpoint`
   whose `state.trust_floor` and run-level `trust_floor` are both `UserAsserted` while a block in
   `state.volatile` is `UntrustedContent`; assert the restored `Run::trust_floor()` is
   `UntrustedContent`. **Control:** a genuinely clean checkpoint is **not** lowered, so the clamp is not
   "always return the bottom".
   *Mutations:* replace the hand-written `Deserialize` with a field-wise derive; separately, drop
   `.min(self.state.trust_floor())` in `restore` — each reddens it, isolating the deserializer from the
   resolution.
5. **`a_version_1_checkpoint_is_refused_by_name_not_skipped`.** A serialized v1 payload — a real JSON
   value with a `version` key and no session-level floor, **written through `JournalCheckpoints`, not
   `MemoryCheckpoints`** (§4.4) — yields `ResumeError::UnknownVersion { run, found: 1, expected: 2 }`,
   and a legacy `{"step": n}` payload with no `version` key is **still skipped silently**.
   *Mutations:* revert the decode to `.filter_map(... .ok())` → the v1 payload reports "no checkpoint"
   and this fails; **no other test in the workspace moves**, which is why it exists. Second: add
   `#[serde(default)]` to the new field → the v1 payload decodes at `UserAsserted`; same red. Third,
   and this is the §4.2(b) control: apply the fix to `decode_all` **only** and leave
   `JournalCheckpoints::latest`'s copy at `:298` untouched → still red, because `resume` goes through
   `latest`.
6. **`a_session_state_payload_with_an_unknown_field_is_refused`.** The hand-written `Deserialize` keeps
   what the derive at `context.rs:420` had.
   *Mutation:* drop `deny_unknown_fields` from the inner wire struct.

---

## 8 · The adversarial pass, recorded rather than hidden

The design in `runs/m3-c/design/latch-scope.md` was reviewed adversarially before this ADR was written.
**Verdict: `sound-with-fixes`.** Its fatal finding is §4.1 above, and it is carried here as a named
defect of the *first* design because an ADR that reads as though the first draft were right is worth
less than one that shows what nearly shipped.

| What the first design said | What the pass found | What changed |
|---|---|---|
| Bump `CHECKPOINT_VERSION` and add a required field; a v1 checkpoint is *"refused by name"* | The refusal is **unreachable**: `deny_unknown_fields` makes v1 fail `from_value`, and the version check is downstream of a deliberate `.ok()` skip. The named test asserts an error no code path produces, and the way to make it pass is `#[serde(default)]` — the fail-open it exists to prevent | §4.3's version-probe decode, in the same commit as the bump. **And two further corrections found here: the variant is `UnknownVersion`, and the fix must land in `latest`, not `decode_all` (§4.2)** |
| *"Today exactly three writers of the volatile tier"*, pinned by a `marlowe-loop/src` grep | **Five.** The two it missed are in `daemon.rs` and are structurally outside the grep's scope — instance #14 | Arrival latching, so there is no list; and §7.1's test moved to `crates/marlowe/tests/` with workspace scope |
| A removal door whose doc says it latches over *"every block that is LEAVING"* | The body mins over the **entire** old tier, kept blocks included | Removal door deleted; latch on arrival |
| `SessionState::latch_trust_floor` as *"a deliberate mirror"* of `Run`'s | Two copies of a rule; the shape whose removal closed #15 | One `TrustFloor` type, §3.3 |
| Daemon citations `:2486`, `:2484-2488`, `:601`, `:2762` | **All four stale**, copied from a ROADMAP row that says in its own text that five of its seven citations had drifted | Re-verified at `03fb1d6`: `:2609`, `:2608`, `:667`, `:2885` |
| One child `SessionState::new` site (`engine.rs:2205`) | **Two** — `:2796` is the quarantined reader's | `SessionState::for_child`, §3.7 |
| Three reset doors | **Four** — a daemon restart resets silently, because `Daemon::sessions` is not persisted | §4.5, and §9.3 |
| *"Within a run the latch absorbs both levers"* | True, but the compaction branch `continue`s **upstream** of the latch, so on that iteration the run latch observes nothing | §3.6's ordering paragraph |
| Hand-written `Deserialize` | Would silently drop the `deny_unknown_fields` the derive has today | §3.5, and test 7.2.6 |
| *"Guarded: []"*, cost framed as *"no product change"* | The `volatile` privatisation is a cross-crate API break touching a file under concurrent edit | §6.5, priced |

**Two corrections the adversarial pass itself needed**, both from re-reading HEAD rather than from
argument: `engine.rs`'s compaction `continue` is at **`:781`**, not `:782`; and the daemon's ordinary
fresh-state construction is at **`:2630`**, not `:2670`. Line numbers in this repo drift, which is the
same reason the pass gave for correcting the design's.

---

## 9 · What this decision does NOT close, and what is the human's

### 9.1 · Whether the second clause is BUILT — the decision this ADR does not take

**Not the hook.** `run.rs`, `context.rs`, `engine.rs`, `durable.rs` and `daemon.rs` are all absent from
`PROTECTED` — verified: `python .claude/hooks/protect-boundaries.py --list-protected` lists fifteen
paths and none of them is any of those five. **Nothing would prompt.** The gate is the standing rule
that a settled decision is revisited explicitly: ADR-023's recorded wording is *"monotonic and latched
per run"*, and this changes the object it latches on.

**One §13-guarded file is adjacent and is deliberately not touched:**
`crates/marlowe-loop/src/provenance.rs` is on the protected list, and `Provenance::taint_for` is one of
the readers of `Run::trust_floor()`. This decision reads it and changes nothing in it.

### 9.2 · The product consequence, with §2.1 as prior art

M3-DESIGN §2.1 already states, for M3's target architecture, that a tainted Marlowe *"can never compose
a target again — not for that task, for his life"* and calls the liaison pattern *"the only shape that
survives ADR-023."* **So the question is not "is one poisoned belief permanent for the conversation" in
the abstract — it is whether the SHIPPED per-turn architecture should behave like §2.1's before §2.1
arrives.** Today the answer costs nothing observable (§1.1). The moment Session D wires `ingest`, it
becomes the product's felt behaviour: no file write, no recipient, no path, for the rest of that
conversation.

### 9.3 · Whether a reset door exists at all, and what authorises it

Session-scoping creates demand for one. A door that **raises** a floor is privilege-widening —
`steer.rs`'s shape, and `steer.rs` is in `PROTECTED` for exactly that reason — and if built it belongs
in `PROTECTED` and in CLAUDE.md's table **in the same commit**. There are **four** de-facto reset points
to rule on together: a new conversation, an explicit approval, a `/reset`, and **a daemon restart**
(§4.5), which today resets silently and is a door nobody chose. It must not arrive later as ergonomics
— a `SessionState::clear()`, or a `/reset` that quietly rebuilds state.

### 9.4 · The egress grant's scope, answered SEPARATELY — and `SECURITY-AUDIT.md` §8's own coupling is wrong

ROADMAP *Waiting on the human* item 4 calls the latch and ADR-032 §3.1's per-host grant *"the same
session-versus-run question"*, and `SECURITY-AUDIT.md`'s Agent-D block (line 688) goes further: *"The
grant is scoped to the `Run`, so §8 above now has a second instance."*

**They are opposites, and this is the clause this ADR amends.** Widening the **latch** can only ever
**remove** privilege — a conversation floor is by construction ≤ every turn's floor — so its worst
failure is a visibly over-refusing conversation. Widening the **grant** **adds** privilege for longer,
and its worst failure is a host that stays reachable after the human stopped watching, which is silent.
They also differ in §13 exposure: the latch touches no `PROTECTED` file; the grant lives in
`profile.rs` and `adjudicate.rs`, **both guarded**, under an ADR that is `Status: PROPOSED` while
already built — the only unaccepted-and-shipped ADR in the set. **One "yes, session-scoped" ruling
would quietly do both, and it should not.**

### 9.5 · Whether `crates/marlowe-loop/src/run.rs` joins the boundary hook

`Run::latch_trust_floor` — `TrustFloor::latch` under §3.3 — is the whole of layer 3's per-run half, and
nothing guards the file. Adding a path is monotone in the human's favour, but the CLAUDE.md row and the
`EXPECTED_PROTECTED` entry ship in the same commit (the M3 B3 rule: *"whoever adds a path to
`PROTECTED` adds its row here in the same commit"*). Checked: there is no `run.rs` §13 entry in
`SECURITY-AUDIT.md`. Recorded as the human's rather than taken.

### 9.6 · Which session builds it — C, D, or neither until a lever changes

No reachable path raises the floor across a turn boundary today (§1.1), so the build has **no
discriminating probe**. The trigger is either Session D's `ingest` caller or §7.1's pinned-writers test
going red. Naming the trigger is what makes deferral a decision rather than a delay.

### 9.7 · Not decided, and not raised as findings

- **`SessionState::trust_floor` under M3-DESIGN §2.1's permanent run.** §2 says it is removed in the
  same commit. Nothing here schedules that commit.
- **A latent divergence found while reading, NOT filed as a security finding.** `Assembler::compact`
  rotates `state.session` (`context.rs:904` area) and `engine.rs:760` updates `run.session` to match;
  but the daemon builds each turn's `Run` with `SessionId::from_name(session)` unless resuming
  (`daemon.rs:2608`). After any compaction the run's session id and the state's disagree, and memory
  writes and retrieval scope on a session id. Checked: no `session_id`/rotation entry in
  `SECURITY-AUDIT.md`. It needs verification before it is filed and it **must not** be bundled here —
  changing which id a memory write carries can make earlier beliefs unretrievable.
- **`decode_all`'s false doc comment (§4.2b) and the duplicated `.ok()` filter.** A real defect in a
  file this ADR does not otherwise touch. Raised, not repaired.

---

## 10 · Contract impact

**For the recording: none.** `CONTRACTS.md` §5's pinned `Run` (line 905) does not list `trust_floor` at
all, and §6's `Session` (line 1004) does not either. Writing this entry moves no pinned schema.

**For the build: three deliberate amendments, each a decision rather than a side effect.**
(1) §6 gains a sentence — the latched floor is a property of the **conversation chain** and is carried
across the turn boundary. §6 is where *"A long conversation is a chain, never an overwritten
transcript"* already lives (line 1013), and the floor is a property of the chain.
(2) `CHECKPOINT_VERSION` 1 → 2 is a wire change to a §12 type (line 1396), plus the decode change of §4.3.
(3) §5's `Run` gains `trust_floor: TrustClass`, because a reader of §5 currently cannot see the
mechanism ADR-023 turns on.

**Two pre-existing drifts, raised rather than silently repaired** — contracts are pinned, and if one is
wrong the rule is to stop and raise it:

- §5's `Run` (line 905) lists `pub result: Option<ContentRef>` (line 916), which
  `crates/marlowe-loop/src/run.rs` does not have, and omits `trust_floor` (`run.rs:600`), which it does.
- §12's `Checkpoint` (line 1396) lists `transcript_ref`, `pending_calls` and `guidance`, **none of which
  exist** in `crates/marlowe-loop/src/durable.rs:87-108`, while omitting `version`, `parent`, `trace_id`,
  `status`, `profile`, `budget`, `spent`, `trust_floor`, `orphan_policy`, `output_contract`,
  `contract_retries` and `state`, **all of which do**.

Neither drift is caused by this decision and neither is repaired inside it.

**Also corrected in passing:** `SpawnRequest`'s fields are **not** pinned in `CONTRACTS.md` — §5 pins
only `fn spawn(&self, req: SpawnRequest) -> RunId` at line 941. A ROADMAP row claiming otherwise is
wrong.

---

## 11 · Risks

- **The probe can be vacuous and read exactly like a working one.** Injected-memory blocks accumulate in
  `state.volatile` (`daemon.rs:2752-2758`, no retain), so a two-turn test refuses on turn 2 whether or
  not any conversation latch exists. **Test 7.2.2 is not optional**; without it, 7.2.1 measures block
  carriage and calls it a latch.
- **The mirror risk: the discriminating case is a state the product cannot enter.** Forcing removal in a
  test is the same green-and-vacuous family the layer-3 probe already declares about hand-pushed
  `InjectedMemory` blocks. Not a reason to skip it — a reason the header must say what it measures.
- **#16 is the likeliest way this ships wrong.** `SessionState::trust_floor` could be added, serialized,
  checkpointed and asserted on with no reader in the enforcement path. §5 names the two readers, and a
  grep for readers of the field is the thirty-second check.
- **#17, in the one place it fits.** Do not express "no taint yet" as a derived zero.
  `UntrustedContent = 0` is the **bottom**; a struct-level `#[derive(Default)]` that pulled in a
  `Default for TrustClass` would make every fresh conversation read as fully tainted, and the obvious
  fix — `#[default]` on `UserAsserted` — is fail-open in the serde path. `TrustFloor` has no `Default`
  and `SessionState::default` is hand-written.
- **`daemon.rs` is in the blast radius** (§6.5), on a file another session is editing. Sequenced, not
  concurrent.
- **"Session" is ambiguous in three ways and this entry says which it means.** `Daemon::sessions` is an
  in-memory `BTreeMap` keyed by the client's session **name** and is not persisted (`daemon.rs:776-777`);
  `SessionState::session` is a `SessionId` that **rotates** on compaction; `CONTRACTS.md` §6's `Session`
  is a durable record whose `parent` makes a conversation a chain. **The latch belongs to the CHAIN and
  is held on the `SessionState` object rather than keyed on any id.** Keying it on `SessionId` would
  reintroduce the reset at every compaction — the per-turn hole in a second place.

---

## 12 · Verification

Symbol names alongside line numbers, because a line number is a claim about a path with nothing checking
it (family #14). Everything below was **read** at `03fb1d6` on 2026-08-30. **Nothing in this ADR was
measured by running a test; `cargo` was not invoked, because another session is building.** That
distinction is stated rather than implied — a table of reads reads like a table of tests.

| Claim | How established |
|---|---|
| A fresh `Run::root` per user message, at `UserAsserted`, over a persisted `SessionState` | read: `daemon.rs:2609`, `run.rs:680`, `daemon.rs:777` / `:667` / `:2885` |
| `Run::latch_trust_floor` is strictly monotone downward | read: `run.rs:613-616` |
| `blocks_composed_targets(origin) = origin <= UntrustedContent` | read: `adjudicate.rs:50-52` |
| **Five** writers of `SessionState`'s volatile tier, not three | read: `context.rs:451`, `:772`/`:785`, `:904`; `daemon.rs:2828`, `:2830` |
| `ContextView` has its own `volatile` field, and `engine.rs` writes it | read: `context.rs:471`, `engine.rs:818` — the enumeration hazard of §6.5 |
| `SessionState` carries `deny_unknown_fields` **today** | read: `context.rs:420` |
| Hand-written `Deserialize` is the file's existing pattern | read: `context.rs:357` (`Block`), `:408` (`GovernanceConstraint`) |
| The decode drops undecodable payloads on purpose, for 895 legacy events | read: `durable.rs:233-236`, `:246` |
| **`resume` goes through `latest`, not `decode_all`, and `latest` has its own `.ok()` filter** | read: `control.rs:237`, `durable.rs:283-300` (filter at `:298`), `decode_all` used only by `latest_per_run` at `:277` |
| **`decode_all`'s "both readers go through here" is false** | same reads — two `filter_map(...ok())` sites |
| The version check is downstream of the decode | read: `control.rs:238` |
| The variant is `UnknownVersion { run, found, expected }` | read: `control.rs:54` |
| **The existing version test cannot see the fatal defect** | read: `control.rs:346-364` — `MemoryCheckpoints`, current struct shape, one integer changed |
| `Checkpoint` carries the run's floor and `state` | read: `durable.rs:86` (`deny_unknown_fields`), `:102`, `:107`, `:135`, `:144-148` |
| Two child `SessionState::new` sites | read: `engine.rs:2205`, `engine.rs:2796` |
| Compaction and `clear_tool_results` `continue` upstream of the latch | read: `engine.rs:736`, `:781`, `:787`, `:877` |
| The daemon's ordinary path builds a fresh `SessionState` on a miss | read: `daemon.rs:2630` |
| `ingest_external` has no production caller | `grep -rn "ingest_external(" --include=*.rs crates/*/src/ \| grep -v "fn ingest_external"` → empty |
| None of the five touched files is `PROTECTED`; `provenance.rs` is | `python .claude/hooks/protect-boundaries.py --list-protected` |
| §8's text, and its "second instance" clause | read: `SECURITY-AUDIT.md:126-131`, `:688` |
| M3-DESIGN §2.1's permanent-run commitment | read: `M3-DESIGN.md:102-110` |
| CONTRACTS drifts in §5 and §12 | read: `CONTRACTS.md:905-918`, `:1004-1014`, `:1396-1403` against `run.rs:600`, `durable.rs:87-108` |
| ROADMAP's acceptance row and its coupling of latch to grant | read: `ROADMAP.md:832`, `:69-86` |
