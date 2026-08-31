# ADR-066 · A budget is granted, never sliced — and the envelope is one field on `Run`, not a scope object

**Status:** **Accepted, M3 Session C, 2026-08-31, by Matthew. MOSTLY NOT BUILT, and that is the
decision rather than a delay.** ***“PROPOSED — needs the human’s approval. DESIGN ONLY, NO CODE”* was
true when written and is now false of exactly one section.** §1.3’s missing floor landed at
`723a972`: `Budget::slice_for_quarantined_read` reads `MIN_CHILD_TOKENS` and fails closed, as `grant`
already did, and its doc comment records that the floor is a lower bound rather than the right number
— what it closes is a reader that could not afford *any* first call, not one that cannot afford
*this* one. **Nothing else here is built:** `committed`, `envelope`, `EventKind::BudgetExtended` and
the `CHECKPOINT_VERSION` bump are specified and unwritten, and neither pinned contract has moved.

> **§1 IS AMENDED: TWO OF ITS THREE CLAIMED DEFECTS IN SHIPPED CODE ARE NOT DEFECTS.** Established by
> reading, and written in place at §1.1 and §1.2. §1’s own sentence — *“Four things are wrong anyway.
> Three are defects in shipped code”* — now reads: **one** defect, fixed at `723a972`; **one correct
> design** mistaken for decay (§1.1, `subagents`); **one structurally real hazard the current
> architecture cannot reach** (§1.2, the clamp against `spent`); and §1.4’s acceptance row, which
> stands exactly as written.

It changes a **pinned contract twice** (`CONTRACTS.md` §5's `Run`, and §1.1's closed `EventKind`
list), it depends on a scope question `SECURITY-AUDIT.md` §8 already puts on the human, and its
central number — the default envelope for a top-agent — is the user's money. None of those is a
session's to take. `cargo` was not run while writing this; another session is building.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | M3-DESIGN §4's *"deducted from the parent's pool"*, which is true of the document and false of the code (§1.2). M3-DESIGN §4.1's model-supplied extension request, **narrowed** to a harness-derived raise (§4.1). `BudgetShare::Standard`'s doc comment, which says *"One quarter"* while `numerator()` returns 3 (§1.5) |
| **Depends on** | ADR-023 (the `(action, target)` latch), ADR-039 / ADR-041 (the quarantined read and its group unit), ADR-053 (what a checkpoint must carry, and its *"No new `EventKind`"*), ADR-057 (who declares a child's contract), M3-DESIGN §1, §4, §9.1 A4, §11, §12 item 4 |
| **Contract change** | **Yes, twice.** `CONTRACTS.md` §5: `Run` gains `committed: Budget` and `envelope: Budget` with the invariant `budget <= envelope`. `CONTRACTS.md` §1.1: one `EventKind` variant, `BudgetExtended`. `durable::Checkpoint` gains `committed` and bumps `CHECKPOINT_VERSION` — versioned, not pinned |
| **Code change** | **None taken.** Three defects in shipped code are established by reading (§1.1–§1.3) and none is fixed here |
| **§13-guarded files** | `crates/marlowe-loop/src/driver.rs` is **read, never edited**, and §4.1 and §4.2 are rejected specifically to keep it that way. `profile.rs`, `adjudicate.rs`, `egress.rs`, `taint.rs`, `memory.rs`, `pin.rs`, `steer.rs`, `provenance.rs`, `scope/`, `trust.rs`: untouched |

---

## 1 · The finding

M3-DESIGN §4's headline — *"a budget is an explicit grant at spawn, deducted from the parent's
pool"* — **is already built and must not be rebuilt.** Verified by reading
`crates/marlowe-loop/src/budget.rs`: `Budget::grant` takes its share of the **original** clamped by
`remaining`, refuses by name with both numbers through
`GrantRefused::{NoDepth, PoolEmpty, MoreThanRemains, BelowFloor, PoolTooSmall}`, floors tokens at
`MIN_CHILD_TOKENS = MEASURED_CHILD_FIRST_CALL_TOKENS(3_089) + MIN_CALL_TOKENS(512) = 3_601`
(budget.rs:80), keeps `depth` structural, and floors every dimension at 1 through
`at_least_one_u{16,32,64}`. `slice_for` is gone. `SpawnRequest::grant_tokens` exists
(driver.rs:73) and is already a Target under ADR-023 (`composes_spawn_targets`, engine.rs:3237,
called at engine.rs:2600).

**Four things are wrong anyway. Three are defects in shipped code; the fourth is that the acceptance
row for all of them is measured on a tree the product does not build.**

### 1.1 · `subagents` is still sliced from the remainder, in the dimension §4 did not look at

> **AMENDED 2026-08-31 — THIS IS NOT A DEFECT. `subagents` IS A CONSUMED POOL, NOT A SHARE.** The
> section’s claim is that this line *“takes a share of what remains”* and that **two siblings doing
> identical work are offered 7 and 6**, *“exactly the decay M3-DESIGN §4 abolished”*. The arithmetic is
> right; the reading of it is wrong. **`share.apply_*` is not called here.** The expression is
> `left.subagents.saturating_sub(1)` — a **decrement**, not a geometric slice — and the line’s own
> comment says why: *“A child may not spawn more children than its parent had left, and it starts one
> short because it is itself one of them.”*
>
> Tokens, wall time and tool calls are **shares of the original**, so taking them from the remainder
> would compound geometrically down the tree, and that is what §4 abolished. A subagent slot is not a
> share of anything: it is a **seat**, which `Engine::spawn` consumes one of per spawn
> (`run.spent.add(&Budget { subagents: 1, ..Budget::default() })`) and which
> `run.spent.subagents >= run.budget.subagents` refuses against. **A second sibling genuinely has one
> fewer seat to hand down, because one of the seats is the first sibling.** Offering both 7 would let
> the tree admit more agents than the pool holds.
>
> **So `a_second_sibling_is_offered_the_same_allocation_as_the_first` is green on a correct build**,
> and the charge that its one-dimension assertion hides a bug reads the wrong way round: `subagents`
> is the one dimension in which equality between siblings is not the property wanted. Nothing here is
> fixed, because nothing here is broken.

```
crates/marlowe-loop/src/budget.rs:237
    subagents: at_least_one_u16(left.subagents.saturating_sub(1), left.subagents),
```

`left` is `self.remaining(spent)`. Every other dimension in that constructor takes
`of_original(..)` or `share.apply_u32(self.tool_calls)` — a share of the **original**. This one
takes a share of what remains. **Two siblings doing identical work are offered 7 and 6**, which is
exactly the decay M3-DESIGN §4 abolished, surviving because §4 was written about tokens.

The existing control cannot see it. `a_second_sibling_is_offered_the_same_allocation_as_the_first`
(budget.rs:527) is *named* for this property and asserts `first.tokens == second.tokens` — **one
dimension.** It is green on the shipped build, on the line above, today.

### 1.2 · `grant` clamps against `spent`, and `spent` moves only when a child returns

> **AMENDED 2026-08-31 — STRUCTURALLY REAL, AND UNREACHABLE IN THE CURRENT ARCHITECTURE.** This
> section already says *“This is harmless in the shipped binary and it must be said in those words”*.
> The human’s ruling is the stronger form, and it moves the item out of *“defects in shipped code”*
> and into a constraint on fan-out. `Engine::spawn` calls
> `self.run(&mut child_run, &mut child_state, &mut child_provenance, &mut child_ports)`
> **synchronously** and folds `run.spent.add(&child_run.spent)` immediately after it returns — at all
> three child sites: the ordinary spawn, `condense_batch`’s quarantined reader, and arm (b)’s
> validator. **A child’s usage is therefore in `spent` before the next grant is computed, and a parent
> never holds two outstanding grants.** There is no state the shipped product can enter in which the
> clamp is wrong.
>
> **It becomes live the day a child runs concurrently, and not before**, which is why it is recorded
> rather than fixed. A fix written today would be a change nothing can exercise, and its test would be
> measuring a state the product cannot enter — the shape ADR-062 records for layer 3.
>
> *(The line numbers in this section have drifted and the symbols have not. At acceptance the grant is
> `run.budget.grant(&run.spent, req.share, req.grant_tokens)` at `engine.rs:2831`, the three folds are
> at `:2468`, `:3187` and `:3515`, and `slice_for_quarantined_read(&run.spent)` is at `:2304`.)*

```
engine.rs:2618   let child_budget = match run.budget.grant(&run.spent, req.share, req.grant_tokens)
engine.rs:2897   run.spent.add(&child_run.spent);          // after the child finishes
engine.rs:2116   let Some(child_budget) = run.budget.slice_for_quarantined_read(&run.spent) else
engine.rs:2279   run.spent.add(&child_run.spent);          // the quarantined reader, same shape
```

The deduction is **accounting, not admission**. A grant is a promise about the future; `spent` is
the past. With two children outstanding, both are offered a share of a pool that has already been
given away.

**This is harmless in the shipped binary and it must be said in those words.** `Engine::spawn` runs
its child inline and settles at :2897, so a parent never holds two outstanding grants. It becomes an
N-fold overcommit the moment M3 fans out, which is M3's entire premise.

### 1.3 · The quarantined reader has no floor, and the shipped leaf is starved

`slice_for_quarantined_read` (budget.rs:278) is the one budget-granting function that does not read
`MIN_CHILD_TOKENS`. Its whole guard is:

```
crates/marlowe-loop/src/budget.rs:279-282
    let left = self.remaining(spent);
    if left.tokens == 0 || left.wall_ms == 0 {
        return None;
    }
```

Walking the **shipped** ladder — `Budget::interactive()` is `tokens: 200_000, wall_ms: 600_000,
subagents: 8, depth: 3` (budget.rs:99-108), `BudgetShare::Standard` is 3/8 (`numerator()`,
budget.rs:383), `QUARANTINED_READ_NUMERATOR/DENOMINATOR` is 2/8 (budget.rs:251-252):

| Level (M3-DESIGN §1 names) | tokens | fraction of root | wall_ms |
|---|---|---|---|
| 1 `[Mrlw]` root | 200,000 | 100% | 600,000 |
| 2 `[Ta]` | 75,000 | 37.5% | 225,000 |
| 3 `[Ma]` | 28,125 | 14.06% | 84,375 |
| 4 `[Wa]` | 10,546 | **5.27%** | 31,640 |
| 5 `[TSa]` quarantined reader | **2,636** | 1.318% | 7,910 |

**2,636 tokens against a measured first call of 3,089** (`MEASURED_CHILD_FIRST_CALL_TOKENS`,
budget.rs:54, read from the journal at seq 4597) **and a `MIN_CHILD_TOKENS` of 3,601.** The reader
cannot finish a sentence. It does not fail — it returns a worse summary, which is
indistinguishable from a page that had little to say, and which ADR-041's own commentary says
nobody can audit.

### 1.4 · The acceptance row prints 1.98% and passes, on a tree the product never builds

```
crates/marlowe-loop/src/budget.rs:506
    fn a_leaf_at_depth_four_is_inside_the_declared_band() {
        let root = Budget { depth: 4, ..Budget::interactive() };
        ...four `grant`s at BudgetShare::Standard...
        assert!(share >= 0.01, ...); assert!(share <= 0.05, ...);
```

`Budget::interactive().depth == 3`. The test constructs `depth: 4` by hand and composes four
`grant`s; the shipped daemon builds three `grant` levels and then a `slice_for_quarantined_read`.
**The percentage it prints, 1.98%, is not the product's leaf**, and it is a percentage rather than a
token count — so it reads identically whether the leaf can speak or not. **Instance #15's shape, in
the acceptance row for the section this ADR is about.** The band's own doc comment
(budget.rs:361-362) presents 1.98% as the measurement that justified moving `Standard` from 2/8 to
3/8.

### 1.5 · Citations corrected in place, because this repo's most recent commit is about drifted ones

The design this ADR is drawn from cited `daemon.rs:2486` for `Run::root` and `daemon.rs:2564` for
`Budget::interactive()`, and scoped itself by saying *"the conversational root at :2564 is
untouched"* — implying two `Run::root` builds in that file.

```
$ grep -n "Run::root\|Budget::interactive()" crates/marlowe-daemon/src/daemon.rs
2609:        let mut run = Run::root(
2620:            Budget::interactive(),
```

**One `Run::root` call in the file, at 2609, not 2486; `Budget::interactive()` at 2620, not 2564.**
There is no second root to leave untouched, so a scope claim resting on distinguishing them cannot
be checked by reading it. Corrected here, and this ADR cites
`crates/marlowe-daemon/src/daemon.rs::Daemon::ask_streaming_with` by symbol thereafter.

Two more corrections, both made rather than quietly used: `Dimension` is at budget.rs:86, not :83;
and `BudgetShare::Standard`'s doc comment reads **"The default for a worker. One quarter."**
(budget.rs:372) while `numerator()` returns **3** (budget.rs:383). A reader who trusts the comment
computes `(2/8)^4 = 0.39%` and concludes the leaf is starved by a factor of five more than it is. It
is a declared value disagreeing with the code, in the function whose number the acceptance row is
about.

### 1.6 · A live instance #19 in `turn.rs`, found while reading, recorded not claimed

```
crates/marlowe-loop/src/turn.rs:78    pub enum TurnEvent {          // 8 variants:
    TextDelta, ReasoningDelta, SpeechRetracted, ToolLine, Compacted, Degraded, ApprovalPrompt, Done
crates/marlowe-loop/src/turn.rs:115  let names = [ ...7 strings, SpeechRetracted absent... ];
crates/marlowe-loop/src/turn.rs:128  assert_eq!(names.len(), 7, "a variant was added; ...");
```

**Eight variants, seven names, and the assertion is green.** `names` is hand-written, not derived
from the enum, so the check's input is not the object it checks — a variant was added and the count
never moved.

This matters to this ADR beyond the ledger. The design under review **rejected the `TurnEvent` route
on the strength of this check**, writing that it *"can see an addition (by failing the count) but not
a deletion."* It can see neither, and it had already missed one. The correct mechanism was declined
on a property nobody checked. §2.7 adopts the `TurnEvent` route and repairs the check in the same
commit; `SpeechRetracted`'s absence is **pre-existing**, found by reading, and belongs in `STATE.md`
as such rather than as this session's work.

---

## 2 · The decision

### 2.1 · `Run::committed`, and `obligations()` as the only argument a grant is ever given

```rust
// crates/marlowe-loop/src/run.rs
pub struct Run {
    // ... every existing field ...
    /// Granted to children that have not yet settled. **Private**: `obligations()` is the only
    /// reader, so no call site can consult `spent` where it meant `spent + committed`.
    committed: Budget,
}

impl Run {
    /// What the pool already owes. The ONLY argument `Budget::grant` and
    /// `Budget::slice_for_quarantined_read` are ever given.
    ///
    /// **`wall_ms` is NOT summed.** Wall-clock is shared under fan-out: two children running
    /// concurrently for 60 s consume 60 s of the parent's wall, not 120 s. Reserving it
    /// additively would refuse the second concurrent child a budget it never spends, in the
    /// milestone whose premise is fan-out.
    pub fn obligations(&self) -> Budget {
        Budget {
            tokens:     self.spent.tokens.saturating_add(self.committed.tokens),
            tool_calls: self.spent.tool_calls.saturating_add(self.committed.tool_calls),
            subagents:  self.spent.subagents.saturating_add(self.committed.subagents),
            micros_usd: self.spent.micros_usd.saturating_add(self.committed.micros_usd),
            wall_ms:    self.spent.wall_ms,
            depth:      self.spent.depth,
        }
    }
    pub fn commit(&mut self, granted: &Budget);                    // add, wall_ms excluded
    pub fn settle(&mut self, promised: &Budget, actual: &Budget);  // committed -= promised; spent += actual
}
```

`Budget` gains `saturating_sub` mirroring the existing `add` (budget.rs:315), because `settle` has
no operation today.

**Wired at both grant sites, not one.** `Engine::spawn` calls `run.commit(&child_budget)`
immediately after the successful `grant` at engine.rs:2618 and **before** the
`self.run(&mut child_run, ..)` recursion; `run.settle(&child_budget, &child_run.spent)` replaces the
bare `run.spent.add(&child_run.spent)` at engine.rs:2897. `Engine::condense_batch` does the same
around engine.rs:2116 and :2279. Committing the reader is not symmetry for its own sake: it is what
lets `spawn`'s subagent-cap check at **engine.rs:2625** (`if run.spent.subagents >= run.budget.subagents`)
see condensation headcount at all, which is half of audit finding E13.

**What is honest about `committed` today, in the words `STATE.md` must carry:** `Engine::spawn` runs
its child inline, so **the overcommit this field prevents cannot occur in the shipped binary until
spawn is concurrent.** It is the layer-3 shape — a guard that is correct, tested, and measuring a
state the product cannot enter. What *is* live is the value: `committed` is non-zero on every real
spawn and every real condensation, so `obligations()` is exercised on the product path even while the
refusal it enables is unreachable.

### 2.2 · `subagents` is granted from the original

```rust
subagents: at_least_one_u16(
    share.apply_u16(self.subagents).saturating_sub(1).min(left.subagents),
    left.subagents,
),
```
plus the helper missing beside `apply_u32` (budget.rs:392):
```rust
fn apply_u16(self, v: u16) -> u16 { ((v as u64).saturating_mul(self.numerator()) / 8) as u16 }
```
The `saturating_sub(1)` stays and keeps its existing reason — a child is itself one of its parent's
subagents. What moves is the base: the original, not the remainder. The stale
`BudgetShare::Standard` doc comment is fixed in the same commit: *"Three eighths. Moved from 2/8 in
M3 Session A — see the type's header."*

### 2.3 · The quarantined reader gets a floor, and **the constant is not written until it is read**

```rust
/// Journal-read, not derived from a convention. Take it the way 3_089 was taken:
/// `tools/read_journal.py --all`, a real `condense_batch` child's `Usage`, prompt + completion.
pub const MEASURED_QUARANTINED_READ_TOKENS: u64 = /* READ IT FIRST — this ADR does not supply it */;
pub const MIN_QUARANTINED_READ_TOKENS: u64 = MEASURED_QUARANTINED_READ_TOKENS + MIN_CALL_TOKENS;

pub fn slice_for_quarantined_read(&self, obligations: &Budget) -> Option<Budget> {
    let left = self.remaining(obligations);
    if left.tokens < MIN_QUARANTINED_READ_TOKENS || left.wall_ms == 0 { return None; }
    // tokens: share(self.tokens).min(left.tokens).max(MIN_QUARANTINED_READ_TOKENS)
    //   -- the guard above makes the `max` unable to exceed what remains, exactly as `grant` does.
    // tool_calls: 1, subagents: 1, depth: 0 -- unchanged, and #17-correct.
}
```

**The reviewed design shipped a number and this one refuses to.** Its constant was
`MEASURED_CHILD_FIRST_CALL_TOKENS + ((600 + MAX_SOURCES_PER_READER * 1_500) / 4) + MIN_CALL_TOKENS
= 6,001`, where the `/ 4` is a chars-to-tokens convention nobody measured and which the design's own
`risks` section admitted was invented. **A derived constant with one invented term reads identically
to a fully measured one**, which is the family that produces instance #16. `MIN_CHILD_TOKENS` was
built out of a journal reading; this one gets the same treatment or it does not get written.

**And the number has a side effect the reviewed design did not look at.** `condense_batch` chunks by
`MAX_SOURCES_PER_READER = 6` (engine.rs:64, used at engine.rs:2043), so a 12-page fetch is **two**
readers. At the `[Wa]` level's 10,546 tokens, a 6,001 floor takes 57% of the worker's entire pool for
the first group of at most six pages and then refuses the second — `left = 4,545 < 6,001`. The fix
would convert *"a degraded summary nobody can audit"* into *"the second half of the page set was
never read"*, and a band test that walks one reader reads the same either way. **§5.1's band test
walks two groups and prints the outcome of each.** The `None` path already has an honest message at
engine.rs:2119-2123.

### 2.4 · The envelope is one field on `Run`, set at construction

```rust
// crates/marlowe-loop/src/run.rs
pub struct Run {
    // ...
    /// The ceiling the harness may raise `budget` to WITHOUT asking (M3-DESIGN §4.2).
    ///
    /// INVARIANT, enforced in `root`, `child` and `restored` — the only builders:
    /// `budget <= envelope` in every dimension. `Run` derives `Debug, Clone` and no
    /// `Deserialize` (run.rs:568), and this field is NOT checkpointed (§2.8), so there is no
    /// serde way in.
    ///
    /// `Run::child` sets `envelope = budget`: a worker has no headroom, so every extension
    /// below the top-agent travels up — M3-DESIGN §3.1's "approved at each level", structurally.
    envelope: Budget,
}
```

`Run::root` gains an explicit `envelope: Budget` parameter with **no default**, so the caller must
state it. `Daemon::ask_streaming_with` — the single `Run::root` build in `daemon.rs` — passes
`Budget::interactive()`, i.e. `envelope == budget`, **which is today's behaviour exactly**.

### 2.5 · Extension is a raise **to** the envelope — no delta, no counter, no zero

```rust
// crates/marlowe-loop/src/budget.rs
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Extension {
    /// Headroom existed. `budget[d]` is now `envelope[d]`. Announce, journal, continue.
    Raised { dimension: Dimension, from: u64, to: u64 },
    /// `budget[d] == envelope[d]` already. Ask the user; a refusal pauses as today.
    AtCeiling { dimension: Dimension, ceiling: u64, spent: u64 },
}

impl Budget {
    /// **Pure arithmetic in one dimension. It decides; the caller acts.**
    ///
    /// There is no increment type and no amount, so there is no number a model could have
    /// shaped and no zero to misread as "already exhausted". After a `Raised`,
    /// `budget[d] == envelope[d]`, so the same dimension can never raise twice — **the number of
    /// within-envelope raises per run is bounded at six by construction**, with no counter, no
    /// increment, and nothing to forget to reset.
    pub fn raise_to_envelope(&mut self, envelope: &Budget, spent: &Budget, d: Dimension) -> Extension;
}
```

`depth` is not raisable and always returns `AtCeiling`: a run out of depth is out of tree, not out of
budget.

### 2.6 · **One** extension site, covering **both** pause paths

The shipped loop has two token pauses, not one:

```
crates/marlowe-loop/src/engine.rs:698   if let Some(dimension) = run.budget.exhausted(&run.spent) {
                                            return self.pause(run, state, ports, dimension.0); }
crates/marlowe-loop/src/engine.rs:701   if !run.budget.has_room_for_a_call(&run.spent) {
                                            return self.pause(run, state, ports, "tokens"); }
```

A run with 200 tokens left is **not** exhausted (`spent < budget`) and pauses at the second — the
floor firing, not the cap, which is the common shape of a token pause. Hooking only `exhausted`
bypasses the envelope entirely on the more frequent path, and the suite stays green because tests
drive the `exhausted` arm.

```rust
let fired = run.budget.exhausted(&run.spent)
    .or_else(|| (!run.budget.has_room_for_a_call(&run.spent)).then(|| Dimension("tokens")));
if let Some(d) = fired {
    match self.try_extend(run, ports, d) {
        Extension::Raised { dimension, from, to } => {
            self.record(ports, EventKind::BudgetExtended, run, state,
                json!({ "dimension": dimension.0, "from": from, "to": to }));
            ports.sink.emit(TurnEvent::BudgetRaised { dimension, from, to });
            // fall through; continue the loop
        }
        Extension::AtCeiling { dimension, ceiling, spent } => {
            if !ports.approvals.await_approval(&ceiling_radius(run, dimension, ceiling, spent)) {
                return self.pause(run, state, ports, dimension.0);
            }
            // an approval raises `run.budget` for THIS request only; `envelope` does not move.
        }
    }
}
```

`fn ceiling_radius(run: &Run, d: Dimension, ceiling: u64, spent: u64) -> BlastRadius` is the **named
reader** of those three numbers. `BlastRadius` is
`{ verb: String, scope: String, reversible: bool, novelty: Option<NoveltyReason> }`
(`crates/marlowe-permission/src/decision.rs:79-84`), so:

```rust
BlastRadius {
    verb: format!("raise this run's {} ceiling", d.0),
    scope: format!("{spent} of {ceiling} {} spent; the run is not finished", d.0),
    reversible: true,
    novelty: None,
}
```

**`driver.rs` is §13-guarded and is not edited.** `ApprovalGate::await_approval(&mut self, radius:
&BlastRadius) -> bool` (driver.rs:647) is reused exactly as it stands.

**An approval raises `run.budget` only, never `envelope`.** Ratcheting the ceiling one plausible
approval at a time is the click-through failure M3-DESIGN §4.2 exists to prevent, relocated one level
down with the user doing the clicking.

### 2.7 · The user-visible half travels in the loop's own channel

```rust
// crates/marlowe-loop/src/turn.rs — one new variant
/// Harness-authored, no model text. M3-DESIGN §4.2's "merely announces".
BudgetRaised { dimension: Dimension, from: u64, to: u64 },
```

**`marlowe_daemon::announce::say` is not used, because that call cannot compile.**
`crates/marlowe-daemon/Cargo.toml:11` declares `marlowe-loop.workspace = true`; `marlowe-loop`'s own
dependencies are `marlowe-contract`, `marlowe-journal`, `marlowe-permission`, `marlowe-tools`,
`serde`, `serde_json`, `blake3`, `thiserror`, `uuid`. The edge runs daemon → loop, and the reviewed
design's only announcement path ran the other way. **This is the fatal finding, and §6 records what
it would have cost.**

**`turn.rs`'s self-check is repaired in the same commit**, per §1.6: derive `names` from the enum's
own source with the `include_str!` + `split_once("pub enum TurnEvent {")` technique
`crates/marlowe-surface/tests/b13_memory_surface.rs:104` already uses, and pin the expected count in
a const written **outside** the derived list, so the count and the membership are asserted from two
places. That is the closure CLAUDE.md's instance #19 prescribes: *ask of any self-check whether its
input is the same object it is checking.*

### 2.8 · Checkpoint: `committed` yes, `envelope` **no**

`durable::Checkpoint` (durable.rs:87) gains `committed: Budget` and nothing else.

**`envelope` is deliberately not checkpointed.** `Checkpoint` derives `Serialize, Deserialize` with
`deny_unknown_fields`, `Budget` derives `Deserialize` with `deny_unknown_fields` and **no validating
constructor** (budget.rs:28-30), and a checkpoint declaring `envelope: { micros_usd: u64::MAX,
tokens: u64::MAX, .. }` beside a smaller `budget` would satisfy the invariant `budget <= envelope`
and restore a laundered spend ceiling from a file. That is family #12 — *a validating constructor
must be the only way in, and `serde` is a way in* — applied to the one value in the system that is
money. `Run::restored` takes `envelope` from the live caller.

`CHECKPOINT_VERSION: u16 = 1 -> 2` (durable.rs:79); `control.rs:238` already refuses a mismatch by
name. **A v1 checkpoint is refused, not defaulted**: `committed: 0` reads as *"nothing owed"* and
would re-grant budget a live `OrphanPolicy::Detach` child still holds — instance #17 on the resume
path.

---

## 3 · Where every field is READ

Instance #16 is this project's most-repeated defect. For each field this decision introduces, the
function that reads it — or the statement that it was dropped for lack of one, which is the preferred
outcome and happened three times.

| Field / type | Read by | Where |
|---|---|---|
| `Run::committed` | `Run::obligations()` — **the only reader; the field is private** | run.rs |
| `Run::obligations()` | `Budget::grant`'s `remaining` argument | engine.rs:2618, replacing `&run.spent` |
| | `Budget::slice_for_quarantined_read`'s argument | engine.rs:2116, replacing `&run.spent` |
| | the `RunSpawned` payload's `obligations_tokens` | `Engine::spawn`'s `self.record` |
| `Run::envelope` | `Budget::raise_to_envelope`, once per fired dimension | `Engine::try_extend`, engine.rs:~698 |
| | `Run::{root,child,restored}`'s invariant check | run.rs:658, :633, :707 |
| `Extension::Raised{dimension,from,to}` | the `BudgetExtended` journal payload; `TurnEvent::BudgetRaised`'s three fields | engine.rs, then `marlowe-surface`'s renderer |
| `Extension::AtCeiling{dimension,ceiling,spent}` | `ceiling_radius`, which turns all three into `BlastRadius.verb` and `.scope` | engine.rs |
| `MEASURED_QUARANTINED_READ_TOKENS` | `MIN_QUARANTINED_READ_TOKENS` | budget.rs |
| `MIN_QUARANTINED_READ_TOKENS` | `slice_for_quarantined_read`'s early return **and** its `.max()` | budget.rs:278 |
| `BudgetShare::apply_u16` | `grant`'s `subagents` arm | budget.rs:237 |
| `Budget::saturating_sub` | `Run::settle` | run.rs |
| `Checkpoint::committed` | `Run::restored` | durable.rs, control.rs |

**Dropped for lack of a reader — three, and each was in the reviewed design as a named type:**

* **`SpendEnvelope::set_at_ms: i64`** — no reader named anywhere. Deleted with its parent type.
* **`EnvelopeAuthor::User { surface: SurfaceId }`** — `SurfaceId` **does not exist**:
  `grep -rn "struct SurfaceId\|enum SurfaceId" --include=*.rs crates/` returns nothing. Neither
  `surface` nor the enum had a reader beyond a test asserting a variant name. Deleted (§4.3).
* **`ExtensionReason::RanOutOf { dimension }`** — a single-variant enum wrapping `Dimension`
  (budget.rs:86), which already travels upward inside `PauseReason::BudgetExhausted { dimension:
  String }` (run.rs:196) and appears a third time as `BlockReason::BudgetExceeded { dimension:
  &'static str }` (decision.rs:93). Its one named reader was the announce format string that cannot
  compile (§2.7). Deleted; `Dimension` is passed directly.

**`BudgetDelta` is deleted for a stronger reason than "no reader" — §6.**

---

## 4 · Why the alternatives lost

Recorded rather than deleted, per the working agreement.

**4.1 · M3-DESIGN §4.1 as written: a model-supplied `{run_id, amount, reason_code, evidence_ref}`,
arriving as a new `ModelStep` variant or a loop-control tool.** It costs a **§13-guarded edit to
`driver.rs`** — `ModelStep`, `SpawnRequest` and `ApprovalGate` all live there — and it puts
model-chosen bits, an amount and a code, on an upward channel whose entire payload is a number. The
harness already knows everything the request needs: `Budget::exhausted` returns the dimension that
fired and the amount is arithmetic against the envelope. **The cost of the narrowing is stated rather
than hidden:** a harness-derived extension fires only *after* exhaustion, so it is a retry-on-empty
and **cannot express "this job is three times my estimate"**. §4.1's own escape hatch is the argument
for accepting that — *"if a request genuinely needs free text it is not a budget request, it is an
escalation, and it takes that path"* — and escalation is M3-DESIGN §3's channel, which Session C
builds anyway. Recorded as a **deliberate narrowing, not an omission**: if the human wants §4.1 as
written, the price is a guarded edit plus a reopened ADR-023 question.

**4.2 · A `BudgetAuthority` port in `Ports`, with the daemon owning the ceiling.** A trait added to
the §13-guarded `driver.rs` and threaded through every construction site in the workspace, for a
value that is fixed at spawn and never changes mid-run. One field on `Run` carries the same
information, survives the checkpoint, and reuses one existing port, one existing modal and one
existing `TurnEvent::ApprovalPrompt`.

**4.3 · `SpendEnvelope` + `EnvelopeAuthor` as a project-scoped object in a new
`crates/marlowe-daemon/src/scope.rs`.** Rejected on three counts. Its `SurfaceId` does not exist and
two of its three fields have no reader (§3). Its claimed structural property is **false**:
`EnvelopeAuthor` was defended as *"the same structural withholding as `ExposedSet::empty()`"*, but
`ExposedSet::empty()` withholds a capability because there is no tool to call, whereas
`EnvelopeAuthor::User` is a `pub` variant of a `pub` enum that **any code in any crate can
construct**, including agent-driven daemon paths. It records a claim about authorship; it does not
establish one. And it creates **two definitions of the ceiling** — `Run::envelope` and
`SpendEnvelope::ceiling` — with no stated precedence and no path by which a mid-turn raise reaches a
live `Run`: either the raise silently does nothing or the scope object is decorative, and both
objects keep reporting a ceiling while one is wrong. That is this project's single most-logged shape.

**4.4 · Holding outstanding commitments in `Engine`, beside `self.children`.** Avoids a CONTRACTS §5
change and is wrong for one reason: `OrphanPolicy::Detach` means children outlive parents, so a
commitment must survive a WAL resume or a restarted parent re-grants budget a live detached child
still holds. `durable::Checkpoint` is what survives.

**4.5 · Fixing the starved leaf by raising `QUARANTINED_READ_NUMERATOR` from 2/8 to 4/8.** It fixes
the leaf by breaking the common case: a quarantined read is usually at depth one, where 4/8 hands
half of a 200k conversational run to one page-reading child. The binding constraint at depth is a
floor, not a fraction — which is exactly what `grant` already does
(`.min(left).max(MIN_CHILD_TOKENS)`) and what `slice_for_quarantined_read` was written without. **A
share for the rich case, a floor for the poor case**, with a named refusal when even the floor does
not fit.

**4.6 · Approving an over-ceiling extension raises the envelope.** The ratchet §4.2 exists to
prevent, weaponised: each individual approval looks reasonable. Kept from the reviewed design, which
was right about it.

**4.7 · A percentage-only band assertion, as budget.rs:506 does today.** 1.318% is inside [1%, 5%]
and buys 2,636 tokens, below both the 3,601 floor and the 3,089 measured first call. **The percentage
reads identically whether the leaf can speak or not**, which is this project's definition of a proxy.
Tokens against the floor first, fraction against the band second, `wall_ms` third.

**4.8 · A latched-run guard on the extension path
(`a_latched_run_cannot_ask_for_more_budget`).** Considered and **declined**, with the reason recorded
so it can be reinstated. The reviewed design's rationale was *"the amount is a number untrusted
content could have shaped"* — but under raise-to-envelope **there is no amount**, by that same
design's headline and by its own rejection of §4.1. The guard therefore has no rationale under its
own design, and adding a new consequence to ADR-023's latch is a scope decision CLAUDE.md and
`SECURITY-AUDIT.md` §8 both put on the human. **A later session reviving model-supplied amounts
reinstates this guard as part of that work** — and asserts on
`marlowe_permission::blocks_composed_targets(run.trust_floor())`, never on `TrustFloorLatched`, which
is instance #15 and fires on every run that has ever run.

---

## 5 · The tests, each with the mutation that turns it red

No test below reads the same whether or not its mechanism works. Where the honest reading is weaker
than the tempting one, the weaker one is written down.

### 5.1 · `crates/marlowe-loop/tests/leaf_budget_band.rs::the_shipped_tree_leaf_clears_the_floor_and_the_band`

Walks the **shipped** ladder — `Budget::interactive()` (depth 3, the value
`Daemon::ask_streaming_with` builds), then `[Ta] -> [Ma] -> [Wa]` via `Budget::grant`, then **two**
quarantined-read groups via `slice_for_quarantined_read`, because `MAX_SOURCES_PER_READER = 6` makes
a 12-page fetch two readers. Prints one row per level and per group: tokens, fraction of root,
`wall_ms`, and the floor each must clear. Reads
`crates/marlowe-loop/artifacts/budget-bands-v1.json` via `include_str!` and **fails with "no
pre-registration"** if the artifact is absent, rather than assuming a band.

```
cargo test -p marlowe-loop --test leaf_budget_band -- --nocapture > runs/m3-session-c/leaf-band.txt
```

**It is red before the fix, which is the evidence it is not a proxy**: today it prints
`TSa group 1: 2636 tokens 1.318% floor 3601 STARVED`. Mutations: reverting the
`MIN_QUARANTINED_READ_TOKENS` floor reddens the token row; putting `BudgetShare::Standard` back to
2/8 reddens the fraction row; deleting the artifact reddens it as a missing pre-registration;
deleting the second group's row hides the refusal the floor causes, which is the outcome §2.3 exists
to surface.

### 5.2 · `crates/marlowe-loop/tests/spawn_and_budget.rs::a_spawn_reserves_before_the_child_runs`

`EventKind::RunSpawned`'s payload gains `"obligations_tokens"`. Through the test `Recorder`, a real
spawn of grant G from pool P must report `obligations_tokens >= G` **on the `RunSpawned` emitted
while the child is still running**. Mutations: delete `run.commit(&child_budget)` from
`Engine::spawn` → the payload reads 0 → red; replace `settle` with the old `spent.add` → a nested
spawn's payload double-counts → red. **This assertion is on the product path, not on a hand-built
`Run`** — which is the difference between it and its unit companion.

`two_outstanding_grants_cannot_exceed_the_pool` stays as the unit companion: commit 150k of 200k,
then `grant(&run.obligations(), Large, Some(150_000))` must be
`GrantRefused::MoreThanRemains { want: 150_000, left: 50_000 }`. **And `STATE.md` records, in these
words, that the overcommit it prevents cannot occur in the shipped binary until spawn is
concurrent** — the layer-3 shape, named rather than reported as *"budgets are now reserved"*.

### 5.3 · `budget.rs (mod tests)::a_second_sibling_is_offered_the_same_headcount_as_the_first`

The existing `a_second_sibling_is_offered_the_same_allocation_as_the_first` (budget.rs:527) asserts
`.tokens` only. This adds `.subagents`, `.wall_ms`, `.tool_calls` and `.micros_usd` to the same
property. Mutation: restore `subagents: at_least_one_u16(left.subagents.saturating_sub(1),
left.subagents)` — **the line as shipped at budget.rs:237** — and the second sibling gets 6 where the
first got 7. **The current test is green on that build**, which is why the assertion has to name the
dimension.

### 5.4 · `crates/marlowe-loop/tests/budget_envelope.rs`

* **`a_run_whose_envelope_equals_its_budget_asks_rather_than_raising`** — built on the shipped
  `Budget::interactive()` root, driving **both** pause paths (cap and floor), counting
  `ApprovalGate` calls: exactly one per exhaustion, `run.budget` unchanged on decline,
  `PauseReason::BudgetExhausted`. **This is the product's current behaviour and it runs on every
  build.** Mutation: clamp to `u64::MAX` instead of `envelope` → nothing asks → red.
* **`an_extension_fires_on_the_call_floor_as_well_as_the_cap`** — a run at `budget.tokens - 200`
  spent, which is not `exhausted` and pauses at engine.rs:701. Mutation: hook only the `exhausted`
  arm → the floor path bypasses the envelope → red. Without this test the §2.6 fix is unmeasured on
  the more common of the two paths.
* **`an_extension_inside_the_envelope_is_granted_without_asking`** — `envelope.tokens == 4 *
  budget.tokens`: `await_approval` called **zero** times, `run.budget.tokens == envelope.tokens`, one
  `EventKind::BudgetExtended`, one `TurnEvent::BudgetRaised` naming the dimension. Mutations: compare
  against `budget` instead of `envelope` → everything asks → red; delete the sink emit → red on the
  event count.
* **`a_dimension_raises_at_most_once`** — exhaust tokens twice with headroom: exactly one `Raised`,
  then `AtCeiling`. **The bound is asserted rather than argued**, which is the difference between
  this design and one with a counter.
* **`a_child_has_no_headroom_of_its_own`** — `Run::child` sets `envelope = budget`, so a worker's
  exhaustion always reaches `AtCeiling`. Mutation: let `child` inherit the parent's envelope → red.
* **`a_v1_checkpoint_is_refused_rather_than_defaulted`** — §2.8.

### 5.5 · `budget.rs (mod tests)::a_quarantined_read_below_the_floor_is_refused_by_name_rather_than_starved`

A parent with `left.tokens` anywhere in `[1, MIN_QUARANTINED_READ_TOKENS)` returns `None`, so
`condense_batch` emits its existing honest message at engine.rs:2119 rather than spawning a reader
that pauses before its first call. Every `Some` it returns clears `MIN_CALL_TOKENS`. Mutation: delete
the early return → the function returns `Some(2_636)` for the shipped depth case and the assertion
fails on that exact figure.

### 5.6 · What is **not** proposed, and why

`the_model_has_no_word_for_the_envelope` was in the reviewed design as two halves. Half (a) —
`SpawnRequest::from_args` given `{"envelope": …, "ceiling": …, "spend_limit": …}` produces a request
byte-identical to the same args without those keys — is kept, and it is **the weaker claim**: it
tests the parser, not the wire. Half (b) — *"the manifest declares no parameter whose name matches
envelope/ceiling/limit"* — **is dropped**. It reads identically if the ceiling is reachable under any
other name, or through the existing `grant_tokens`, which is precisely the shape of instance #15. The
live version of that claim is a `--dev` outbound-request dump on a real turn, which needs Session C's
model-driver seam; it is **named as unavailable rather than substituted for**.

### 5.7 · M3-DESIGN §9.1's A4 arm, which the reviewed design did not run

A4 is *"budget allocation — slice-remaining (current), flat grant, grant + extension, grant +
envelope"*, primary metric *"leaf starvation; interruption count"*. **The reviewed design shipped one
arm, measured leaf starvation only, and counted no interruptions** — substituting a static arithmetic
band for the measured arm, scoring the half that was already fine and leaving unmeasured the half
that says whether the envelope earns its complexity. **Interruption count is the entire justification
for the envelope**, because §4.2's sentence is about a user who learns to click through.

`try_extend` increments per-run `raises` and `ceiling_asks`, carried in the `RunCompleted` payload;
`tools/score_agent_arms.py --arm a4` prints both plus per-level leaf tokens for each of A4's four
cells against a pre-registered band. **Un-instrumented control: the same task set with
`envelope == budget` on every run**, which is today's system.

---

## 6 · The adversarial pass, recorded rather than hidden

**The critique's verdict on the first design was `broken`, and the headline feature is what broke.**

> **Fatal:** *"The envelope — the design's own headline — is unbuildable as written and its central
> number is undefined."*

Three defects composed into it, and each is worth keeping because each is a family this repo already
counts.

**(a) An infinite announce/journal loop at the site reached on every budget pause.** The first
design's `Budget::extend(&self, obligations, envelope, want: BudgetDelta)` took the amount as a
parameter and **named no producer for it**. `BudgetDelta` derived `Default`, so the all-zero want was
free to construct — and `extend` returned `Granted { delta: 0 }` for it, not `Refused`. That
announces, journals a `BudgetExtended`, raises nothing, and returns to a loop whose very next
iteration hits the same exhaustion check. **Instance #17 exactly: a zero read as a floor where the
code means a ceiling**, in a design whose own comment said it created two types to avoid a second
reading of zero. Nothing bounded the number of within-envelope extensions either, so once a `want`
existed, auto-extension on exhaustion would have made `budget` advisory and the envelope the only
real cap — the design's own rejected alternative #6, relocated one level down with the harness doing
the clicking. **What changed:** `BudgetDelta` is deleted; extension is a raise of the fired dimension
to the envelope's value in one step, which has no amount, no zero, and a bound of six per run by
construction rather than by a counter (§2.5).

**(b) The mechanism's single named user-visible reader could not compile.** The design routed the
announcement through `marlowe_daemon::announce::say`, called from
`crates/marlowe-loop/src/engine.rs`. `crates/marlowe-daemon/Cargo.toml:11` declares
`marlowe-loop.workspace = true`; the edge runs daemon → loop. **The feature would have shipped as a
silent budget raise with a journal entry nobody sees**, and `ExtensionReason` would have become
instance #16 verbatim — a reason code whose only reader is a test asserting its value. **What
changed:** the announcement travels in the loop's own upward channel as `TurnEvent::BudgetRaised`
(§2.7), and `ExtensionReason` is deleted.

**(c) The design rejected the correct mechanism on a property it did not check.** It declined the
`TurnEvent` route because `turn.rs:128`'s self-check *"can see an addition (by failing the count) but
not a deletion."* It can see neither — `names` is hand-written — **and it had already missed one**
(§1.6). The design walked past a live instance #19 in the file it was reading and used a false
property to justify a worse design. **What changed:** the `TurnEvent` route is adopted and the check
is repaired in the same commit, with the pre-existing miss recorded as pre-existing.

**The critique's own verdict on the rest is kept:** *"The diagnostic half (starved leaf, subagents
still sliced from the remainder, `grant` clamping against `spent` rather than obligations) is
verified correct against source and survives."* §1.1–§1.4 are that half, re-verified independently
for this ADR against the line numbers printed in §8.

**Five further defects it named, each carried into the decision rather than argued away:**
`Run::commit` reserving `wall_ms` additively would refuse the second concurrent child a budget it
never spends (→ §2.1's excluded dimension); the checkpointed `envelope` is a serde way into a money
ceiling (→ §2.8); the extension hook covered only one of two pause paths (→ §2.6); the
`MIN_QUARANTINED_READ_TOKENS` floor refuses the second reader group of a 12-page fetch (→ §2.3 and
§5.1); and three APIs the design presented as call-ready do not exist — `BudgetShare::apply_u16`
(only `apply_u64` and `apply_u32` are defined, budget.rs:388-392), `Budget::sub` (only `add`,
budget.rs:315), and `SurfaceId` (nowhere under `crates/`).

**An ADR that reads as though its first draft were right is worth less than one that shows what
nearly shipped.** What nearly shipped was an unbounded announce loop behind an uncompilable
announcement.

---

## 7 · What this decision does NOT close

* **It does not fix anything.** No code is written. §1.1, §1.2 and §1.3 are three defects in the
  shipped binary established by reading, and they are still there.
* **It does not supply `MEASURED_QUARANTINED_READ_TOKENS`.** The constant is deliberately left
  unwritten (§2.3). Until it is read from a real `condense_batch` child's `Usage` via
  `tools/read_journal.py --all`, `slice_for_quarantined_read` has no floor and the leaf stays
  starved. **Writing a plausible number is the failure this ADR is refusing.**
* **It does not make `Run::committed` load-bearing in the product.** `Engine::spawn` runs its child
  inline, so the overcommit the field prevents cannot occur until spawn is concurrent. Correct,
  tested, and measuring a state the product cannot enter.
* **It does not exercise the raise.** Shipping `envelope == budget` everywhere means every budget
  pause in the product reaches `AtCeiling` and asks. `Extension::Raised`, `EventKind::BudgetExtended`
  and `TurnEvent::BudgetRaised` are **exercised only by tests** until a non-default envelope exists.
  That is the label-before-the-reader pattern held deliberately for one release, and it must be
  written in `STATE.md` in those words rather than as *"the envelope is built"*.
* **It does not decide `BudgetShare::Standard`.** §2.2 fixes the doc comment to match the code; it
  does not argue that 3/8 is right.
* **It does not reconcile `CONTRACTS.md` §5.** That block is **already stale** and the edit must
  reconcile it or the pin is decorative: it lists `result: Option<ContentRef>` and
  `trace_id: TraceId`, neither of which the shipped `Run` has, and omits `trust_floor`, which it
  does.
* **It does not touch `CONTRACTS.md` §12.** §12 (line 1396) defines a `Checkpoint` with
  `transcript_ref` and `pending_calls` that `durable::Checkpoint` does not have. **Two definitions of
  one pinned type already disagree**; whoever edits §12 decides which is the contract.
* **It does not file the starved leaf as a security finding.** A starved quarantined reader **fails
  closed** — it returns nothing and the parent is told so. But the observable symptom, *"the content
  could not be condensed"*, is indistinguishable from a page that had little to say, which is the
  output ADR-041's own commentary says nobody can audit. `grep` of `SECURITY-AUDIT.md` and `STATE.md`
  returns nothing for the `MIN_CHILD_TOKENS` asymmetry; it is newer than that audit.
* **It does not resolve `slice_for_quarantined_read`'s false doc comment.** The comment claims a
  quarantined reader *"structurally cannot call `run`"* because it holds `ExposedSet::empty()`.
  `Engine::spawn` never consults the caller's exposed set — the only thing stopping a toolless child
  from spawning is `depth: 0` returning `GrantRefused::NoDepth`. Containment holds because both are
  set; **the stated reason is not the operative one.** It matters to anyone tempted to relax depth
  for toolless children. Related to `SECURITY-AUDIT.md` C12 and cited rather than re-filed.
* **The band artifact is editable by the session it constrains.** `budget-bands-v1.json` is checked
  in, so a session that cannot hit the band can widen it. Instance #19's family — a check whose input
  is reachable by the thing being checked. **Mitigated, not closed**: the test prints the band and
  the measured number together into `runs/<session>/leaf-band.txt`, so a widening is auditable
  against an earlier run file. `tools/preregister_budget_bands.py` refusing to overwrite is the same
  discipline `preregister_split.py` uses, and the same discipline anyone can bypass with an editor.
* **`wall_ms` can starve the leaf after the token fix ships, with the band green.** The `[TSa]` wall
  budget is `(3/8)^3 * (2/8) * 600,000 = 7,910 ms`, and Session C measured Ollama
  cold-load-plus-one-token at 3,212–5,442 ms for the mini models. If the role is not resident, most
  of the leaf's wall is a model load. A band asserting tokens only is the same proxy one dimension
  over, which is why §5.1's artifact carries a `wall_ms` row per level.

---

## 8 · What is the human's

1. **The default envelope for a top-agent.** `Budget::interactive()` is 200,000 tokens / $2.00 /
   8 subagents / 10 minutes, hardcoded for a run that lives one turn. A top-agent is project-scoped
   and outlives a turn, so its ceiling is a different number and **it is the user's money.** This
   decision ships `envelope == budget` — every extension asks — precisely so the number can be
   decided without blocking the mechanism.
2. **Per top-agent scope, or per project?** §4.2 says the user sets a ceiling *"at spawn"*, which
   reads per-scope; ten scopes may then each spend the ceiling, and a per-project ceiling is what
   actually bounds a day's spend. **This is the same shape as ADR-032 §3.1's flagged
   *"session-scoped"* looseness on egress grants, and the same question `SECURITY-AUDIT.md` §8 asks
   about ADR-023's latch — *"the latch belongs on the session, not the Run"*.** Recording the
   ceiling's scope must not silently settle the latch's scope. They are the same question and the
   human owns both.
3. **What "depth 4" means in M3-DESIGN §11, and whether `BudgetShare::Standard = 3/8` follows.**
   §1's table numbers `[Wa]` Worker-agent as **level 4** and `[TSa]` Tool-spawned as level 5; §11's
   row is *"Leaf budget share at depth 4"*. The reviewed design silently read it as `[TSa]` (1.318%)
   and never argued. **Under §1's own numbering, level 4 is `[Wa]` at 10,546 / 200,000 = 5.27% —
   above the reviewed design's declared [1%, 5%] band, on the ceiling side.** The three cannot all be
   right as written. §5.1's artifact therefore asserts only what §11 says unambiguously — every level
   ≥ 1% of root, and every level clears its own token floor — and **encodes no upper band**, because
   a pre-registered artifact is only worth having if its subject is settled.
4. **M3-DESIGN §12 item 4 — token pool, headcount, or both.** **Both, and they already are both.**
   They bind at wildly different N: money binds at 200,000 / 3,601 ≈ 55 agents, the card binds at 3.
   Neither can be dropped. **The shape is recommended; the number is not a design agent's call.**
   Measured on this machine this session: three roles co-resident at **14,993 MiB used, 1,053 MiB
   free**, with 5,086 MiB held by the desktop before any model loaded. `AGENT-DIRECTORY.md` §2's
   *"10.0 GB … leaving headroom for the KV cache, the embedder and the reranker"* is contradicted by
   that measurement, and ADR-044 resolves the embedder's provider against **free VRAM at load** — so
   the embedder falls to CPU with a correct-looking log line. Whether `subagents = 8` stays 8 or
   becomes a function of residency interacts with Session C's admission control (ROADMAP C item 5)
   and with audit finding **E13** (`condense_batch` does not check the subagent cap `spawn` checks at
   engine.rs:2625, so a research pass exhausts the 8-subagent budget on condensations).
5. **Whether §4.1's model-supplied `reason_code` and `evidence_ref` are given up or deferred.** This
   ADR recommends harness-derived reasons and **drops `evidence_ref` entirely**, because nothing in
   the current product opens an artifact ref from an approval modal and a field nothing reads is
   instance #16. If the human wants §4.1 as written, the price is a **§13-guarded edit to
   `driver.rs`** plus a `DECISIONS.md` entry, and §4.8's latch guard comes back with it.
6. **Two pinned-contract edits.** `CONTRACTS.md` §5 (`Run` gains two fields and an invariant) and
   §1.1 (`EventKind::BudgetExtended`). ADR-053's *"No new `EventKind`. CONTRACTS §1.1 pins the kind
   list"* (ADR-053:138) is **cited and distinguished, not ignored**: a settlement was already
   expressible as `RunCompleted`, whereas **a raise nobody was asked about is expressible as
   nothing** — the ApprovalRequested/Granted/Denied trio cannot carry the one spending path in the
   product that involves no human. Without the variant, that path has no audit trail.

---

## 9 · Sequencing, and one file another agent is holding

`crates/marlowe-daemon/src/daemon.rs` is not §13-guarded, but **another agent is editing it in this
session.** The only change wanted there is one argument at `Daemon::ask_streaming_with`'s single
`Run::root` build. **Sequence it after that agent lands.**

`SpawnRequest` gains no field. `grant_tokens` already exists (driver.rs:73), and its shape is **not**
pinned: `grep -n SpawnRequest docs/design/CONTRACTS.md` returns exactly line 941,
`fn spawn(&self, req: SpawnRequest) -> RunId`. Session C's `role` field is therefore the first
pinning of that shape, and this decision rides along at zero cost.

`grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"` still
returns nothing after this change. Nothing here wires `ingest`.

---

## Verification

Symbol names where a line number would be a claim about a path with nothing checking it (family #14).
Everything below was established by **reading the file named**, in this working tree, on 2026-08-30.
**`cargo` was not run**: another session is building, and no claim below needs it.

| Claim | How established |
|---|---|
| `subagents` is sliced from the remainder | read: budget.rs:237 |
| its control asserts one dimension | read: budget.rs:527, `assert_eq!(first.tokens, second.tokens)` |
| `grant` clamps against `spent` | read: engine.rs:2618, `&run.spent` |
| `spent` moves only on return | read: engine.rs:2897 (spawn), engine.rs:2279 (quarantined reader) |
| the quarantined reader has no floor | read: budget.rs:278-282 — the guard is `left.tokens == 0` or `left.wall_ms == 0` |
| `MIN_CHILD_TOKENS = 3_601`, from a measured 3_089 | read: budget.rs:45, :54, :80 |
| the shipped root is `depth: 3` | read: `Budget::interactive`, budget.rs:99-108 |
| `Standard` is 3/8 while its doc says "One quarter" | read: budget.rs:372 against budget.rs:383 |
| the acceptance test builds `depth: 4` by hand | read: budget.rs:506 |
| the shipped leaf is 2,636 tokens | **arithmetic** over the four constants above: 200,000 → 75,000 → 28,125 → 10,546 → 2,636. Not measured on a running product |
| two token-pause paths, not one | read: engine.rs:698 and engine.rs:701 |
| `[Wa]` is §1 level 4 and measures 5.27% | read: M3-DESIGN §1's table; arithmetic as above |
| `TurnEvent` has 8 variants and its check asserts 7 | read: turn.rs:78-105 against turn.rs:115-128 |
| `marlowe-loop` cannot call into `marlowe-daemon` | read: `crates/marlowe-daemon/Cargo.toml:11` against `crates/marlowe-loop/Cargo.toml`'s `[dependencies]` |
| `BlastRadius` has four fields, all it can carry | read: decision.rs:79-84 |
| `await_approval` takes only a `BlastRadius` | read: driver.rs:647 |
| `driver.rs` is §13-guarded | `python .claude/hooks/protect-boundaries.py --list-protected` |
| `Run` derives no `Deserialize` | read: run.rs:568 (`#[derive(Debug, Clone)]`) |
| `Budget` derives `Deserialize` with no validating constructor | read: budget.rs:28-30 |
| `Checkpoint` is `deny_unknown_fields`, version 1, refused on mismatch | read: durable.rs:79, :86-88; control.rs:238 |
| three definitions of "which dimension ran out" | read: budget.rs:86, run.rs:196, decision.rs:93 |
| `MAX_SOURCES_PER_READER = 6`, chunked | read: engine.rs:64, engine.rs:2043 |
| `spawn`'s subagent cap does not see condensations | read: engine.rs:2625 |
| **`daemon.rs` has ONE `Run::root`, at 2609** | `grep -n "Run::root\|Budget::interactive()" crates/marlowe-daemon/src/daemon.rs` → 2609, 2620 |
| `SurfaceId` does not exist | `grep -rn "struct SurfaceId\|enum SurfaceId" --include=*.rs crates/` → nothing |
| `apply_u16` and `Budget::sub` do not exist | read: budget.rs:388-392, budget.rs:315 |
| ADR-053 forbids new `EventKind`s | read: ADR-053:138 |
| `SpawnRequest`'s shape is not pinned | `grep -n SpawnRequest docs/design/CONTRACTS.md` → line 941 only |
| the VRAM figures | **measured this session**, three roles co-resident |

**The band table in §1.3 and the 5.27% in §8 item 3 are arithmetic over read constants, not
measurements of a running product.** That distinction is stated rather than implied, because a table
of derived numbers reads like a table of measurements — and §5.1 exists to turn them into a command
that prints one.
