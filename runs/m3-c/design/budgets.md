# budgets: A grant is a reservation, not a promise; the envelope is a scope-scoped ceiling the model has no word for; and the depth-4 leaf the acceptance row is about is starved today while the test that measures it prints 1.98% and passes

**Adversary verdict:** broken

**Fatal:** The envelope — the design's own headline — is unbuildable as written and its central number is undefined. `Budget::extend(.., want: BudgetDelta)` has no producer named anywhere in the design; `BudgetDelta` derives `Default`, so the degenerate all-zero want returns `Granted { delta: 0 }`, which announces, journals a `BudgetExtended`, raises nothing, and returns to a loop whose very next iteration hits the same exhaustion check — an unbounded announce/journal cycle at the site reached on every budget pause in the product. Nothing bounds the number of within-envelope extensions either, so once a `want` IS defined, auto-extension on exhaustion makes `budget` advisory and the envelope the only real cap: the design's own rejected alternative #5 ("each individual approval looks reasonable") relocated one level down, with the harness doing the clicking. And the mechanism's single named user-visible reader cannot compile: `crates/marlowe-daemon/Cargo.toml:11` declares `marlowe-loop.workspace = true`, while `crates/marlowe-loop/Cargo.toml`'s dependencies are contract/journal/permission/tools only — so `engine.rs` calling `marlowe_daemon::announce::say` is a reverse dependency edge. The diagnostic half (starved leaf, subagents still sliced from the remainder, `grant` clamping against `spent` rather than obligations) is verified correct against source and survives.

## Ledger instances the adversary says this re-commits

- #16 — `EnvelopeAuthor::User { surface: SurfaceId }`: `SurfaceId` has no definition under `crates/`, and `surface` has no named reader.
- #16 — `SpendEnvelope::set_at_ms: i64`: no reader named anywhere in the design.
- #16 — `ExtensionReason::RanOutOf { dimension }`: its one named reader is `marlowe_daemon::announce::say` called from `marlowe-loop`, a reverse crate dependency that cannot compile; the field's only remaining reader is the test asserting its value.
- #16 — `ExtensionOutcome::AsksTheUser { want, ceiling, already }`: `ApprovalGate::await_approval(&mut self, radius: &BlastRadius) -> bool` (driver.rs:647) takes only `BlastRadius { verb, scope, reversible, novelty }`, all strings. No function is named that turns those three numbers into the modal's text.
- #17 — `#[derive(Default)] pub struct BudgetDelta`: the all-zero delta is free to construct and `extend` returns `Granted { delta: 0 }` for it — a raise that grants nothing while reporting success, at the site reached on every budget pause.
- #17 — `Run::commit(&granted)` reserving `wall_ms`: a concurrency-shared dimension reserved additively, so the second concurrent child is refused wall it would never spend.
- #15 — `the_only_author_of_a_ceiling_is_a_person` asserts `const EXPECTED_AUTHORS: [&str; 1]`, a variant NAME. It reads identically on a build where `SpendEnvelope::raise` ignores its `by` argument entirely.
- #15 — `the_model_has_no_word_for_the_envelope` half (b): "the manifest declares no parameter whose name matches envelope/ceiling/limit" reads identically if the ceiling is reachable under any other name, or through the existing `budget_tokens`.
- #19 — the design cites `turn.rs:128` and states its failure mode backwards ("it can see an addition by failing the count"). It cannot: `names` is hand-written, and `TurnEvent` currently has 8 variants against a green `names.len() == 7`, because `SpeechRetracted` was added and never listed. A live #19 in the file the design read.
- #19 — `crates/marlowe-loop/artifacts/budget-bands-v1.json` is editable by the session it constrains. The design names this honestly as mitigated-not-closed, which is the correct disposition, but the mitigation is auditability, not a check.
- #12 — `Checkpoint` (durable.rs:87) derives `Deserialize` with `deny_unknown_fields`, and `Budget` has no validating constructor. Adding `envelope: Budget` to it makes a spend ceiling constructible from a file: `envelope.micros_usd = u64::MAX` beside a smaller `budget` satisfies the design's stated invariant. `EnvelopeAuthor` not deriving `Deserialize` protects nothing, because `EnvelopeAuthor` is not in the checkpoint.
- #14 (documentation form) — `daemon.rs:2486` and `:2564` are drifted (actual: `Run::root` at 2609, `Budget::interactive()` at 2620), and the scope claim "the conversational root at :2564 is untouched" implies a second `Run::root` call site that does not exist in that file.

## Defects (16)

### `marlowe-loop` cannot call `marlowe_daemon::announce::say`. The enforcement_sites entry for `ExtensionReason` names "the announce string built at the extension site in crates/marlowe-loop/src/engine.rs and passed to crates/marlowe-daemon/src/announce.rs::say". `crates/marlowe-daemon/Cargo.toml:11` has `marlowe-loop.workspace = true`; `crates/marlowe-loop/Cargo.toml`'s `[dependencies]` are marlowe-contract, marlowe-journal, marlowe-permission, marlowe-tools, serde, serde_json, blake3, thiserror, uuid. The edge runs daemon to loop.

- **Why:** Section 4.2's whole product behaviour is "Marlowe grants within it and merely announces". The design's only announcement path does not exist, so the feature ships as a silent budget raise with a journal entry nobody sees — and `ExtensionReason::RanOutOf` becomes instance #16 verbatim, a reason code whose only reader is a test asserting its value.
- **Fix:** Announce through the loop's own upward channel: `ports.sink.emit(TurnEvent::BudgetRaised { dimension, from, to })`, one new harness-authored variant in `crates/marlowe-loop/src/turn.rs`. Delete `ExtensionReason` — `Dimension` already exists in `budget.rs` and already travels upward inside `PauseReason::BudgetExhausted`.

### `want: BudgetDelta` has no producer, `BudgetDelta` derives `Default`, and nothing bounds the extension count. `extend(&self, obligations, envelope, want)` takes the amount as a parameter; the recommendation says "the amount is arithmetic against the envelope" but no function computes it. `BudgetDelta::default()` is all zeros and the design says zero there means "no more of this" — but `extend` returns `Granted { delta: 0, .. }`, not `Refused`.

- **Why:** An extension that grants nothing while reporting success, at the site the loop reaches on every exhaustion, is an infinite announce/journal loop. And a delta type with a Default is a second reading of zero on a budget-shaped value — the exact setup the design says it created two types to avoid.
- **Fix:** Delete `BudgetDelta`. Extension is a raise of the FIRED dimension to the envelope's value in that dimension, in one step: `Budget::raise_to_envelope(&mut self, envelope: &Budget, spent: &Budget, d: Dimension) -> Extension`. After a raise `budget[d] == envelope[d]`, so the same dimension can never raise twice — within-envelope raises are bounded at six per run by construction, with no counter, no increment, and no zero to misread.

### The extension hook covers only one of the two token-pause paths. `crates/marlowe-loop/src/engine.rs:698` is `if let Some(dimension) = run.budget.exhausted(&run.spent) { return self.pause(...) }`; line 700 is `if !run.budget.has_room_for_a_call(&run.spent) { return self.pause(run, state, ports, "tokens") }`. The design hooks only the first.

- **Why:** A run with 200 tokens left is NOT exhausted (`spent < budget`) and pauses at line 700 — the floor firing, not the cap, which is the common shape of a token pause. It would bypass the envelope entirely: the user sees the interruption section 4.2 exists to prevent, on a run with headroom, and the suite is green because the tests drive the `exhausted` arm.
- **Fix:** One private `fn try_extend(&mut self, run: &mut Run, ports: &mut Ports<'_>, d: Dimension) -> Extension`, consulted by BOTH sites before either calls `self.pause`. Test `an_extension_fires_on_the_call_floor_as_well_as_the_cap` with a run at `budget.tokens - 200` spent: red if only `exhausted` is hooked.

### The design's instance-#19 citation has the failure mode backwards, and the check it cites is failing right now. The file is `crates/marlowe-loop/src/turn.rs` (not `crates/marlowe-daemon/src/turn.rs`, which does not exist). `pub enum TurnEvent` at :78 has EIGHT variants — TextDelta, ReasoningDelta, SpeechRetracted, ToolLine, Compacted, Degraded, ApprovalPrompt, Done. The test's `names` array at :123 lists SEVEN; `SpeechRetracted` is absent and `assert_eq!(names.len(), 7)` at :128 is green.

- **Why:** The design wrote that the check "can see an addition (by failing the count) but not a deletion", and used that to reject the TurnEvent route. It cannot see an addition either — `names` is hand-written, not derived from the enum — and it already missed one. The design rejected the correct mechanism on the strength of a property it did not check, and walked past a live #19 in the file it was reading.
- **Fix:** Add the `TurnEvent::BudgetRaised` variant and repair the check in the same commit: derive `names` from the enum's own source with the `include_str!` + `split_once("pub enum TurnEvent {")` technique `crates/marlowe-surface/tests/b13_memory_surface.rs:104` already uses, and pin the expected count in a const written outside the derived list. Record `SpeechRetracted`'s absence in STATE.md as a pre-existing live #19, not as new work.

### `EnvelopeAuthor::User { surface: SurfaceId }` — `SurfaceId` does not exist anywhere under `crates/` (`grep -rn "struct SurfaceId\|enum SurfaceId" --include=*.rs crates/` returns nothing), and neither `surface` nor `SpendEnvelope::set_at_ms` has a named reader. The "match with no wildcard arm" over a single variant permits everything and refuses nothing, and `EnvelopeAuthor::User` is a pub variant of a pub enum, constructible from any code in any crate — including agent-driven daemon paths.

- **Why:** Two fields with no reader is instance #16 twice, in the type whose entire job is to be the ceiling's authority. The structural claim is false: `ExposedSet::empty()` withholds a capability because there is no tool to call; `EnvelopeAuthor::User` withholds nothing because anyone can write it. The type records a claim about who raised the ceiling; it does not establish one. Its test asserts `const EXPECTED_AUTHORS: [&str; 1]` — a variant NAME — which reads identically whether the ceiling is enforced or not (#15).
- **Fix:** Delete `SpendEnvelope` and `EnvelopeAuthor` from this session. One ceiling in one place: `Run::envelope: Budget`, set only by `Run::root`/`Run::child`/`Run::restored`. The project-scoped ceiling that outlives a turn is the same question SECURITY-AUDIT section 8 raises about the latch, it is the human's, and it belongs with Session D's scoped state.

### A checkpointed `envelope` is a serde way into a money ceiling (#12). `crates/marlowe-loop/src/durable.rs:87` derives `Serialize, Deserialize` on `Checkpoint` with `deny_unknown_fields`; `Budget` (budget.rs:31) derives `Deserialize` with no validating constructor. A checkpoint declaring `envelope: { micros_usd: u64::MAX, tokens: u64::MAX, .. }` alongside a smaller `budget` satisfies the design's only stated invariant (`budget <= envelope`) and restores a laundered ceiling. `EnvelopeAuthor` not deriving `Deserialize` protects nothing, because `EnvelopeAuthor` is not in the checkpoint at all.

- **Why:** `CHECKPOINT_VERSION` (durable.rs:79, refused at control.rs:238) stops OLD files, not crafted new ones. This is the exact shape `profile.rs` exists to prevent, applied to the one value that is a spend ceiling, on the one path that reads outside input.
- **Fix:** Do not checkpoint `envelope`. `Checkpoint` gains `committed` only; `Run::restored` takes `envelope` from the live caller. Bump `CHECKPOINT_VERSION: u16 = 1 -> 2` and add `a_v1_checkpoint_is_refused_rather_than_defaulted` — `committed: 0` on restore reads as "nothing owed" and re-grants budget a live `OrphanPolicy::Detach` child still holds.

### Two definitions of the ceiling. `Run::envelope: Budget` and `SpendEnvelope::ceiling: Budget` both answer "what may this scope spend", with no stated precedence, no path by which a mid-turn `SpendEnvelope::raise` reaches a live `Run`, and a `SpendEnvelope::raise` whose refusal condition ("lowering below what is already committed") reads a `committed` that lives on `Run`, in another crate, on another object.

- **Why:** This is the project's single most-logged shape. A user raises the scope ceiling mid-turn and the running run's copy is stale — the raise silently does nothing, or the run's copy wins and the scope object is decorative. Either way both objects keep reporting a ceiling and one is wrong.
- **Fix:** One field, on `Run`, set at construction. Defer the scope-scoped object entirely.

### `Run::commit(&granted)` reserves `wall_ms` additively. Wall-clock is not additive under fan-out: two children running concurrently for 60 s consume 60 s of the parent's wall, not 120 s. The design also passes `obligations()` to `slice_for_quarantined_read` but names `commit` only at `Engine::spawn`, so the quarantined reader's grant is reserved nowhere — at exactly the site ADR-041 made a group.

- **Why:** `run.spent.add(&child_run.spent)` at engine.rs:2279 and :2897 already over-counts wall additively, but today that is a reporting inaccuracy. Feeding it into `obligations()` and thence into `grant`'s admission check converts it into a refusal: the second concurrent child is denied wall budget it would never have spent, in the milestone whose premise is fan-out. And the un-committed reader leaves `Engine::spawn`'s admission check at engine.rs:2626 unable to see condensation headcount — audit finding E13, unchanged.
- **Fix:** `obligations()` sums only the additive dimensions — tokens, tool_calls, subagents, micros_usd — and returns `self.spent.wall_ms` unchanged, with the two-concurrent-children argument in the doc comment. `condense_batch` commits and settles the reader's grant around engine.rs:2116/2279 exactly as `spawn` does around :2618/:2897.

### `ExtensionReason::RanOutOf { dimension }` is a fourth definition of "which dimension ran out". `Dimension(&'static str)` is at budget.rs:83; `PauseReason::BudgetExhausted { dimension: String }` at run.rs:196 already carries it upward; `BlockReason::BudgetExceeded { dimension: &'static str }` at `crates/marlowe-permission/src/decision.rs:93` is a third. A single-variant enum wrapping an existing type, whose only reader is a format string, is ceremony.

- **Why:** Same family as the ceiling duplication, and it becomes a #16 the moment the format string moves.
- **Fix:** Delete it. Pass `Dimension` directly.

### The band artifact would freeze a reading of section 11 that section 1 contradicts, and under the other reading the shipped system already fails the design's own ceiling. M3-DESIGN section 1 numbers `[Wa]` Worker-agent as level 4 and `[TSa]` Tool-spawned as level 5; section 11's row is "Leaf budget share at depth 4". The design silently reads it as the TSa (1.318%) and never argues. Under section 1's numbering, level 4 is the Wa at 10,546 / 200,000 = 5.27% — above the design's declared [1%, 5%] band, on the ceiling side.

- **Why:** A pre-registered artifact is only worth having if its subject is settled. Encoding one reading makes a contested interpretation look measured, and the widening that follows would be invisible.
- **Fix:** The artifact carries one measured row per section 1 level, labelled by section 1's own names (Mrlw/Ta/Ma/Wa/TSa), and asserts only what section 11 says unambiguously: every level >= 1% of root, and every level clears its own token floor. The band's upper bound and the identity of "depth 4" go to the human alongside the `BudgetShare::Standard = 3/8` question, because the three cannot all be right as written.

### `MIN_QUARANTINED_READ_TOKENS = 6,001` is unmeasured in one term and unmeasured in its side effect. The `(600 + MAX_SOURCES_PER_READER * 1_500) / 4` divisor is invented (the design admits this in `risks` and ships the constant anyway). Worse: at the depth-4 worker's 10,546 tokens one reader takes 6,001 — 57% of the worker's whole budget for one group of at most 6 pages — and a second group is refused, because left = 4,545 < 6,001. `condense_batch` chunks by `MAX_SOURCES_PER_READER` at engine.rs:2043, so a 12-page fetch is two readers.

- **Why:** The fix converts "a degraded summary nobody can audit" into "the second half of the page set was never read", and the single-path band test walks one reader and cannot see it — the same proxy the design correctly diagnosed in `a_leaf_at_depth_four_is_inside_the_declared_band`, reproduced one level over.
- **Fix:** Do not write the constant until the number is read: `MIN_QUARANTINED_READ_TOKENS = MEASURED_QUARANTINED_READ_TOKENS + MIN_CALL_TOKENS`, with the measured term read from a real `condense_batch` child's `Usage` via `tools/read_journal.py --all` — the same command and idiom that produced `MEASURED_CHILD_FIRST_CALL_TOKENS = 3_089` at seq 4597. And the band test walks TWO groups, asserting the second reader is either granted at or above the floor or refused BY NAME, printing which.

### `a_latched_run_cannot_ask_for_more_budget` contradicts the design's own rationale and quietly extends ADR-023's latch to a new decision. The stated reason is "the amount is a number untrusted content could have shaped" — but this design's amount is harness-derived, by its own headline and by its own rejection of section 4.1.

- **Why:** Under raise-to-envelope there is no model-chosen number for the latch to bite on, so the guard has no rationale under its own design. Adding a new consequence to the latch is a scope question CLAUDE.md and SECURITY-AUDIT section 8 both put on the human — the design flags the latch's scope in `open_for_human` while silently widening its effect.
- **Fix:** Drop the guard. Record it as considered and declined, with the reason, so a later session reviving model-supplied amounts (section 4.1) knows to reinstate it.

### Three call-ready APIs in the design do not exist. `BudgetShare::apply_u16` — `crates/marlowe-loop/src/budget.rs` has `apply_u64` and `apply_u32` only. `Budget::sub` — `impl Budget` has `add` and nothing else, so `Run::settle`'s "sub promise, add actual" has no operation. `SurfaceId` — nowhere in `crates/`.

- **Why:** The design presents its `types` block as buildable Rust and its enforcement_sites table as a list of real readers. Two of the three missing APIs sit inside the functions the design says are the fix.
- **Fix:** Add `BudgetShare::apply_u16` beside its siblings; give `Budget` a `saturating_sub` mirroring `add`; delete `SurfaceId`.

### Line citations drifted, three of them load-bearing. `Run::root` in `crates/marlowe-daemon/src/daemon.rs` is at 2609, not 2486; `Budget::interactive()` is at 2620, not 2564. There is exactly ONE `Run::root` call in that file, so "the conversational root at :2564 is untouched" implies a second root build that does not exist. (Credit where due: budget.rs:237, budget.rs:527, engine.rs:2116/2279/2618/2897/3237 and turn.rs:128's line number all check out.)

- **Why:** The most recent commit on this repo is about five of seven citations in a roadmap row having drifted. A design whose scope claim — "only the top-agent's root changes" — rests on distinguishing two call sites, one of which does not exist, cannot be scoped by reading it.
- **Fix:** Cite by symbol and file, not by line: `crates/marlowe-daemon/src/daemon.rs::Daemon::ask_streaming_with`, the single `Run::root` build. If a second root for top-agents is intended, say it is being created, not that it already exists.

### Section 9.1's A4 arm is not run. A4 is "budget allocation — slice-remaining (current), flat grant, grant + extension, grant + envelope", primary metric "leaf starvation; interruption count". The design ships one arm and measures leaf starvation only. Nothing in it counts an interruption.

- **Why:** Interruption count is the entire justification for the envelope — section 4.2's sentence is about a user who learns to click through. The design substitutes a static arithmetic band for the measured arm section 9 asks for, scoring the half of A4 that was already fine and leaving unmeasured the half that would say whether the envelope earns its complexity.
- **Fix:** `try_extend` increments per-run `raises` and `ceiling_asks`, carried in the `RunCompleted` payload; `tools/score_agent_arms.py --arm a4` prints both plus per-level leaf tokens for each of A4's four cells against a pre-registered band. Un-instrumented control: the same task set with `envelope == budget` on every run, which is today's system.

### `BudgetShare::Standard`'s doc comment says "One quarter" while `numerator()` returns 3 (3/8). The design's whole depth-4 arithmetic depends on 3/8 and it edits this function without fixing the doc.

- **Why:** A reader who trusts the comment computes (2/8)^4 = 0.39% and concludes the leaf is starved by a factor of five more than it is. It is a declared value that disagrees with the code, in the function whose number the acceptance row is about.
- **Fix:** One-line doc fix in the same commit: "Three eighths. Moved from 2/8 in M3 Session A — see the type's header."

## STRENGTHENED — WHAT GETS BUILT

# BUDGETS — M3 SESSION C, AS IT SHOULD BE BUILT

The design under review had four findings. Three are verified correct against source and are kept; the fourth (the envelope) is rebuilt.

## PART 0 — ALREADY BUILT; DO NOT REBUILD

Verified in `crates/marlowe-loop/src/budget.rs`: `Budget::grant` takes its share of the ORIGINAL clamped by `remaining`, refuses by name with both numbers (`GrantRefused::{NoDepth, PoolEmpty, MoreThanRemains, BelowFloor, PoolTooSmall}`), floors tokens at `MIN_CHILD_TOKENS = MEASURED_CHILD_FIRST_CALL_TOKENS(3_089) + MIN_CALL_TOKENS(512) = 3_601`, keeps depth structural, and floors every dimension at 1 via `at_least_one_u{16,32,64}`. `slice_for` is gone. `SpawnRequest::grant_tokens` exists (driver.rs:73) and is already a Target under ADR-023 (`composes_spawn_targets`, engine.rs:3237, called at engine.rs:2600).

## PART 1 — THE THREE REAL DEFECTS IN SHIPPED CODE

### 1a. `subagents` is still sliced from the remainder

`budget.rs:237` reads `subagents: at_least_one_u16(left.subagents.saturating_sub(1), left.subagents)` — a share of what REMAINS, which is what section 4 abolished, surviving in the dimension section 4 did not look at. Two siblings doing identical work are offered 7 and 6.

```rust
subagents: at_least_one_u16(
    share.apply_u16(self.subagents).saturating_sub(1).min(left.subagents),
    left.subagents,
),
```
plus the missing helper beside `apply_u32`:
```rust
fn apply_u16(self, v: u16) -> u16 { ((v as u64).saturating_mul(self.numerator()) / 8) as u16 }
```
Also fix the stale doc: `BudgetShare::Standard` says "One quarter" and `numerator()` returns 3.

### 1b. `grant` clamps against `spent`, and `spent` moves only when a child RETURNS

`Engine::spawn` grants at engine.rs:2618 against `run.spent`; `run.spent.add(&child_run.spent)` runs at engine.rs:2897 (and :2279 for the quarantined reader), after the child finishes. Harmless while `self.run(&mut child_run, ..)` is inline; an N-fold overcommit the moment M3 fans out.

```rust
// crates/marlowe-loop/src/run.rs
pub struct Run {
    // ... every existing field ...
    /// Granted to children that have not yet settled. **Private**: `obligations()` is the only reader.
    committed: Budget,
}

impl Run {
    /// What the pool already owes. The ONLY argument `grant` and
    /// `slice_for_quarantined_read` are ever given.
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
    pub fn commit(&mut self, granted: &Budget);                       // add, wall_ms excluded
    pub fn settle(&mut self, promised: &Budget, actual: &Budget);     // committed -= promised; spent += actual
}
```
`Budget` gains `saturating_sub` mirroring `add`.

**Make it live, not unit-only.** `Engine::spawn` calls `run.commit(&child_budget)` immediately after the successful `grant` and BEFORE the `self.run(&mut child_run, ..)` recursion; `run.settle(&child_budget, &child_run.spent)` replaces the bare `run.spent.add(&child_run.spent)`. `Engine::condense_batch` does the same around engine.rs:2116/2279 — which also closes half of audit finding E13, because the reader's headcount is reserved before it runs and `spawn`'s admission check at engine.rs:2626 can see it. `committed` is therefore non-zero on **every real spawn in the shipped binary**, not only under concurrency.

### 1c. The quarantined reader has no floor

`slice_for_quarantined_read` is the one budget-granting function that does not read `MIN_CHILD_TOKENS`. Walking the SHIPPED ladder — `Budget::interactive().depth == 3`, `Standard == 3/8` — 200,000 -> 75,000 -> 28,125 -> 10,546, then `QUARANTINED_READ_NUMERATOR/DENOMINATOR == 2/8` gives **2,636**, against a measured first call of 3,089.

**Do not write the constant until the number is read.** In the idiom of `MIN_CHILD_TOKENS`:
```rust
/// Journal-read, not derived from a convention. Take it the way 3_089 was taken:
/// `tools/read_journal.py --all`, a real `condense_batch` child's `Usage`, prompt+completion.
pub const MEASURED_QUARANTINED_READ_TOKENS: u64 = /* READ IT FIRST */;
pub const MIN_QUARANTINED_READ_TOKENS: u64 = MEASURED_QUARANTINED_READ_TOKENS + MIN_CALL_TOKENS;

pub fn slice_for_quarantined_read(&self, obligations: &Budget) -> Option<Budget> {
    let left = self.remaining(obligations);
    if left.tokens < MIN_QUARANTINED_READ_TOKENS || left.wall_ms == 0 { return None; }
    // tokens: share(self.tokens).min(left.tokens).max(MIN_QUARANTINED_READ_TOKENS)
    //   -- the guard above makes the max unable to exceed what remains, exactly as in `grant`.
    // tool_calls: 1, subagents: 1, depth: 0  -- unchanged, and #17-correct.
}
```
The `None` path already has an honest message at engine.rs:2119-2123.

**Measure the side effect the reviewed design missed.** `condense_batch` chunks by `MAX_SOURCES_PER_READER = 6` (engine.rs:2043), so a 12-page fetch is two readers. At the depth-4 worker the floor takes a majority of the worker's pool for the first group and refuses the second. The band test walks TWO groups and prints which outcome each got.

## PART 2 — THE ENVELOPE, REBUILT

### 2a. One ceiling, one place

No `SpendEnvelope`, no `EnvelopeAuthor`, no `crates/marlowe-daemon/src/scope.rs`.

```rust
// crates/marlowe-loop/src/run.rs
pub struct Run {
    // ...
    /// The ceiling the harness may raise `budget` to WITHOUT asking (M3-DESIGN section 4.2).
    ///
    /// INVARIANT, enforced in `root`, `child` and `restored` — the only builders:
    /// `budget <= envelope` in every dimension. `Run` derives no `Deserialize`, and this
    /// field is NOT checkpointed (2e), so there is no serde way in.
    ///
    /// `Run::child` sets `envelope = budget`: a worker has no headroom, so every extension
    /// below the top-agent travels up — section 3.1's "approved at each level", structurally.
    envelope: Budget,
}
```
`Run::root` gains an explicit `envelope: Budget` parameter — no default, so the caller must state it. `crates/marlowe-daemon/src/daemon.rs::Daemon::ask_streaming_with` (the file's single `Run::root` build; cite by symbol, the lines drift) passes `Budget::interactive()`, i.e. `envelope == budget`, which is today's behaviour exactly.

**This is not dead code.** Every budget pause in the shipped product now traverses `try_extend`, finds `budget[d] == envelope[d]`, and routes to the ask. The reader is exercised on the real path; only the raise awaits a number.

### 2b. Extension is a raise TO the envelope — no delta, no counter, no zero

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
    /// `budget[d] == envelope[d]`, so the same dimension can never raise twice — **the number
    /// of within-envelope raises per run is bounded at six by construction.**
    pub fn raise_to_envelope(&mut self, envelope: &Budget, spent: &Budget, d: Dimension) -> Extension;
}
```
`depth` is not raisable — a run out of depth is out of tree, not out of budget — and returns `AtCeiling`.

### 2c. ONE extension site, covering BOTH pause paths

`crates/marlowe-loop/src/engine.rs`, replacing lines 698-703:
```rust
let fired = run.budget.exhausted(&run.spent)
    .or_else(|| (!run.budget.has_room_for_a_call(&run.spent)).then(|| Dimension("tokens")));
if let Some(d) = fired {
    match self.try_extend(run, ports, d) {
        Extension::Raised { dimension, from, to } => {
            self.record(ports, EventKind::BudgetExtended, run, state,
                json!({ "dimension": dimension.0, "from": from, "to": to }));
            ports.sink.emit(TurnEvent::BudgetRaised { dimension, from, to });
            // fall through, continue the loop
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
Line 700's floor pause is thereby covered — a run with 200 tokens left is not `exhausted` and would otherwise have bypassed the envelope.

`fn ceiling_radius(run: &Run, d: Dimension, ceiling: u64, spent: u64) -> BlastRadius` is the **named reader** of those three numbers: `BlastRadius { verb: "raise this run's <d> ceiling", scope: format!("{spent} of {ceiling} {}; the run is not finished", d.0), reversible: true, novelty: None }`. `driver.rs` is section-13 PROTECTED and is **not edited**: `ApprovalGate::await_approval(&mut self, radius: &BlastRadius) -> bool` is reused exactly as it stands.

**An approval raises `run.budget` only, never `envelope`.** Ratcheting the ceiling one plausible approval at a time is the click-through failure section 4.2 exists to prevent. (Kept from the reviewed design's rejected alternative #5 — it is right.)

### 2d. The user-visible half, in the loop's own channel

One new variant in `crates/marlowe-loop/src/turn.rs`:
```rust
/// Harness-authored, no model text. Section 4.2's "merely announces".
BudgetRaised { dimension: Dimension, from: u64, to: u64 },
```
`marlowe_daemon::announce::say` is NOT used: `crates/marlowe-daemon/Cargo.toml:11` depends on `marlowe-loop`, so the reverse edge does not exist.

**And `turn.rs`'s self-check is repaired in the same commit, because it is blind today.** `TurnEvent` has eight variants; the `names` array at :123 has seven and `assert_eq!(names.len(), 7)` at :128 is green because `SpeechRetracted` was added and never listed. Derive `names` from the enum's own source with the `include_str!` + `split_once("pub enum TurnEvent {")` technique `crates/marlowe-surface/tests/b13_memory_surface.rs:104` already uses, and pin the expected count in a const written outside the derived list. `SpeechRetracted`'s absence goes into STATE.md as a **pre-existing live instance #19**, found while reading, not claimed as this session's work.

### 2e. Checkpoint

`durable::Checkpoint` gains `committed: Budget` and nothing else. `envelope` is deliberately not checkpointed: `Checkpoint` derives `Deserialize`, `Budget` has no validating constructor, and a checkpoint declaring `envelope.micros_usd = u64::MAX` beside a smaller `budget` would satisfy the invariant and launder a spend ceiling through a file — family #12, on money. `Run::restored` takes `envelope` from the live caller.

`CHECKPOINT_VERSION: u16 = 1 -> 2` (durable.rs:79); `control.rs:238` already refuses a mismatch. A v1 checkpoint is REFUSED, not defaulted — `committed: 0` reads as "nothing owed" and would re-grant budget a live `OrphanPolicy::Detach` child still holds.

## PART 3 — WHAT GETS MEASURED

### 3a. `crates/marlowe-loop/artifacts/budget-bands-v1.json`

Written once by `tools/preregister_budget_bands.py`, which refuses to overwrite an existing artifact (the `tools/preregister_split.py` discipline). One row per M3-DESIGN section 1 level, **labelled by section 1's own names** — Mrlw, Ta, Ma, Wa, TSa — carrying `tokens`, `fraction_of_root`, `wall_ms`, and the floor each must clear.

**It asserts only what section 11 says unambiguously:** every level >= 1% of root, and every level clears its own token floor. It does NOT encode an upper band, because section 11's "depth 4" and section 1's numbering disagree: section 1 makes `[Wa]` level 4, and `[Wa]` measures 10,546 / 200,000 = 5.27%, above the reviewed design's [1%, 5%] ceiling. Which run section 11 names, and whether `BudgetShare::Standard = 3/8` follows, go to the human together.

### 3b. `crates/marlowe-loop/tests/leaf_budget_band.rs`

Walks the SHIPPED ladder — `Budget::interactive()` (depth 3, the value the daemon builds), Ta -> Ma -> Wa via `Budget::grant`, then TWO quarantined-read groups via `slice_for_quarantined_read`, because `MAX_SOURCES_PER_READER = 6` makes a 12-page fetch two readers. Prints one row per level and per group; reads the artifact via `include_str!` and FAILS with "no pre-registration" if it is absent.
```
cargo test -p marlowe-loop --test leaf_budget_band -- --nocapture > runs/m3-session-c/leaf-band.txt
```
**Red before the fix**, which is the evidence it is not a proxy: today it prints `TSa group 1: 2636 tokens 1.318% floor 3601 STARVED`. Reverting the floor reddens the token row; putting `Standard` back to 2/8 reddens the fraction row; deleting the artifact reddens it as a missing pre-registration; deleting the second group's row hides the outcome the floor causes.

### 3c. `crates/marlowe-loop/tests/spawn_and_budget.rs::a_spawn_reserves_before_the_child_runs`

`EventKind::RunSpawned`'s payload gains `"obligations_tokens"`. Through the test `Recorder`, a real spawn of grant G from pool P must report `obligations_tokens >= G` **on the `RunSpawned` emitted while the child is still running**. Mutation: delete `run.commit(&child_budget)` from `Engine::spawn` -> the payload reads 0 -> red. Replace `settle` with the old `spent.add` -> a nested spawn's payload double-counts -> red. This assertion is on the product path, not on a hand-built `Run`.

The unit companion `two_outstanding_grants_cannot_exceed_the_pool` (commit 150k of 200k, then `grant(&run.obligations(), Large, Some(150_000))` must be `GrantRefused::MoreThanRemains { want: 150_000, left: 50_000 }`) stays, and STATE.md records in these words that **the overcommit it prevents cannot occur in the shipped binary until spawn is concurrent** — the layer-3 shape, named rather than reported as "budgets are now reserved".

### 3d. `crates/marlowe-loop/tests/budget_envelope.rs`

- `a_run_whose_envelope_equals_its_budget_asks_rather_than_raising` — built on the SHIPPED `Budget::interactive()` root, both pause paths (cap and floor), counting `ApprovalGate` calls: exactly one per exhaustion, `run.budget` unchanged on decline, `PauseReason::BudgetExhausted`. **This is the product's current behaviour and it runs on every build.** Mutation: clamp to `u64::MAX` instead of `envelope` -> nothing asks -> red.
- `an_extension_inside_the_envelope_is_granted_without_asking` — `envelope.tokens == 4 * budget.tokens`: `await_approval` called ZERO times, `run.budget.tokens == envelope.tokens`, one `EventKind::BudgetExtended`, one `TurnEvent::BudgetRaised` naming the dimension. Mutation: compare against `budget` instead of `envelope` -> everything asks -> red; delete the sink emit -> red on the event count.
- `a_dimension_raises_at_most_once` — exhaust tokens twice with headroom: exactly one `Raised`, then `AtCeiling`. This is the bound, asserted rather than argued.
- `a_child_has_no_headroom_of_its_own` — `Run::child` sets `envelope = budget`; a worker's exhaustion always reaches `AtCeiling`. Mutation: let `child` inherit the parent's envelope -> red.
- `a_v1_checkpoint_is_refused_rather_than_defaulted`.

### 3e. Section 9.1's A4 arm, which the reviewed design did not run

A4 is `{slice-remaining, flat grant, grant + extension, grant + envelope}` on `{leaf starvation, interruption count}`. `try_extend` increments per-run `raises` and `ceiling_asks`, carried in the `RunCompleted` payload; `tools/score_agent_arms.py --arm a4` prints both plus per-level leaf tokens for each cell against a pre-registered band. **Un-instrumented control: the same task set with `envelope == budget` on every run**, which is today's system.

## PART 4 — CONTRACTS AND GUARDED FILES

**CONTRACTS section 5** (line 905). `Run` gains `committed: Budget` and `envelope: Budget` with the invariant `budget <= envelope`. **The section 5 block is already stale and the edit must reconcile it or the pin is decorative**: it lists `result: Option<ContentRef>` and `trace_id: TraceId`, neither of which the shipped `Run` has, and omits `trust_floor`, which it does.

**CONTRACTS section 1.1** gains `EventKind::BudgetExtended`. ADR-053's "No new EventKind" (`docs/design/adr/ADR-053-what-a-checkpoint-must-carry.md:138`) is cited and distinguished: a settlement was already expressible as `RunCompleted`; a raise nobody was asked about is expressible as nothing, and the ApprovalRequested/Granted/Denied trio cannot carry the one spending path in the product that involves no human.

**`SpawnRequest` gains no field.** `grant_tokens` already exists (driver.rs:73). Its shape is NOT pinned in CONTRACTS — `grep -n SpawnRequest docs/design/CONTRACTS.md` returns exactly line 941, `fn spawn(&self, req: SpawnRequest) -> RunId` — so Session C's `role` field is the first pinning of that shape and this decision rides along at zero cost.

**Noted, not fixed here:** CONTRACTS section 12 (line 1396) defines a `Checkpoint` with `transcript_ref` and `pending_calls` that `durable::Checkpoint` does not have. Two definitions of one pinned type already disagree; whoever edits section 12 decides which is the contract.

**Section-13 guarded files.** `crates/marlowe-loop/src/driver.rs` is PROTECTED (`.claude/hooks/protect-boundaries.py:99`) and is **read only** — `SpawnRequest`, `ModelStep` and `ApprovalGate` all live there, and both obvious envelope designs (a `ModelStep::RequestExtension`, a `BudgetAuthority` port) edit it. Both are rejected specifically to avoid it, and **a later session reviving model-supplied extension requests (section 4.1 as written) touches a guarded file and needs a human's approval plus a DECISIONS.md entry.** `profile.rs`, `adjudicate.rs`, `memory.rs`, `pin.rs`, `steer.rs`, `provenance.rs`: untouched. `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns two definitions and zero call sites after this change. `crates/marlowe-daemon/src/daemon.rs` gains exactly one argument at its single `Run::root` build — **sequence it after the agent currently editing that file lands.**

## PART 5 — REJECTED, RECORDED

1. **Section 4.1's model-supplied `{run_id, amount, reason_code, evidence_ref}`.** Costs a guarded `driver.rs` edit and puts model-chosen bits on an upward channel. Narrowed deliberately, and the cost is stated: harness-derived extension fires only AFTER exhaustion, so it is a retry-on-empty and cannot express "this job is three times my estimate". If the human wants 4.1 as written, that is the price and it is a guarded edit.
2. **A `BudgetDelta` increment type.** Its `Default` is an all-zero want that `extend` reports as `Granted`; raise-to-envelope has no amount and needs no second reading of zero.
3. **`SpendEnvelope` + `EnvelopeAuthor` in the daemon.** `SurfaceId` does not exist; `surface` and `set_at_ms` have no readers; a pub one-variant enum records a claim about authorship rather than establishing one, since any code in any crate can construct it. Two objects answering "what may this scope spend" is the project's most-logged shape.
4. **A `BudgetAuthority` port in `Ports`.** A guarded `driver.rs` edit, threaded through every construction site, for a value fixed at spawn.
5. **Commitments in `Engine` beside `self.children`.** `OrphanPolicy::Detach` means children outlive parents, so a commitment must survive a WAL resume; `durable::Checkpoint` is what survives.
6. **Raising `QUARANTINED_READ_NUMERATOR` from 2/8 to 4/8.** Fixes the leaf by handing half a 200k conversational run to one page-reading child at depth one. A share for the rich case, a floor for the poor case.
7. **Approving an over-ceiling extension raises the envelope.** The ratchet section 4.2 exists to prevent.
8. **A latched-run guard on the extension path.** Under raise-to-envelope there is no model-shaped number for ADR-023 to bite on, and adding a new consequence to the latch is the human's (SECURITY-AUDIT section 8). Declined for this session with the reason recorded, so a session reviving 4.1 reinstates it.

## PART 6 — FOR THE HUMAN

1. **The default envelope for a top-agent.** Ships as `envelope == budget` (every extension asks), so the number can be decided without blocking the mechanism.
2. **Per top-agent scope or per project?** Section 4.2's "at spawn" reads per-scope; ten scopes may then each spend the ceiling. Same shape as ADR-032 section 3.1's flagged "session-scoped" looseness on egress grants, and the same question SECURITY-AUDIT section 8 asks about ADR-023's latch.
3. **What "depth 4" means in section 11**, given section 1 numbers `[Wa]` as level 4 and `[Wa]` measures 5.27%, and whether `BudgetShare::Standard = 3/8` follows from that answer.
4. **Section 12 item 4 — token pool, headcount, or both.** Both, and they already are both: money binds at 200,000/3,601 ~= 55 agents, the card binds at 3. Neither can be dropped. The SHAPE is recommended; the NUMBER is not a design agent's call. Measured on this machine today: three roles co-resident at 14,993 MiB used, 1,053 MiB free, with 5,086 MiB held by the desktop before any model loaded. `AGENT-DIRECTORY.md` section 2's "10.0 GB ... leaving headroom for the KV cache, the embedder and the reranker" is contradicted by that measurement, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD — so the embedder falls to CPU with a correct-looking log line. This interacts with Session C's admission control (ROADMAP C item 5) and with audit finding E13 (`condense_batch` does not check the subagent cap `spawn` checks, so a research pass exhausts the 8-subagent budget on condensations).

---

## Original recommendation

§4's headline is already built and must not be rebuilt: `Budget::grant` (budget.rs:177) takes its share of the ORIGINAL clamped by what remains, refuses by name with both numbers, floors at `MIN_CHILD_TOKENS`, keeps depth structural, and floors every dimension at 1; `slice_for` is gone and `SpawnRequest::grant_tokens` already exists and is already a Target under ADR-023 (`composes_spawn_targets`, engine.rs:3237). Three things are genuinely missing and one shipped number is wrong. (1) **"Deducted from the parent's pool" is true of the document and false of the code**: `grant` clamps against `run.spent`, and `spent` only moves when a child *returns* (engine.rs:2897), so the deduction is accounting, not admission — harmless while spawn is synchronous, an N-fold overcommit the moment M3 fans out. Add `Run::committed` and `Run::obligations()`, and make `obligations()` the only argument `grant` and `slice_for_quarantined_read` are ever given. (2) **The §11 leaf is starved and the test cannot see it.** `Budget::interactive().depth == 3`, so the depth-4 leaf in the shipped tree is the tool-spawned quarantined reader, whose budget comes from `slice_for_quarantined_read` — the one budget-granting function that does **not** read `MIN_CHILD_TOKENS`. Measured: 200,000 → 75,000 → 28,125 → 10,546 → **2,636 tokens**, against a `MIN_CHILD_TOKENS` of 3,601 and a measured first call of 3,089. The leaf cannot finish a sentence, and `a_leaf_at_depth_four_is_inside_the_declared_band` prints **1.98%** and passes because it composes four `grant`s on a `depth: 4` budget the product never builds. The percentage is the proxy; the token count against the floor is the property. Fix `slice_for_quarantined_read` with a derived `MIN_QUARANTINED_READ_TOKENS = 6,001`, and replace the test with a pre-registered band artifact asserting tokens **and** fraction **and** wall_ms per level. (3) **The envelope is two fields on `Run`, not a new port**: `envelope: Budget` (the ceiling the harness may raise `budget` to without asking) and the invariant `budget <= envelope` in every dimension. Extension is **harness-initiated and harness-derived** — it fires where `Budget::exhausted` already fires, before the pause, with the reason being the dimension that fired; inside the envelope it raises `budget`, journals `BudgetExtended` and calls `announce::say(Info, …)`; past the envelope it calls the existing `ApprovalGate::await_approval`. `Run::child` sets `envelope == budget`, so no child can self-extend and every extension below the top-agent travels up, which is §3.1's routing for free. On §12 item 4: **both, and they already are both — but only one of them was fixed.** `tokens` bounds money, `subagents` bounds tree size, and `grant` still derives `subagents` from the *remainder* (`left.subagents - 1`, budget.rs:237), which is the exact slicing §4 abolished surviving in the dimension §4 did not look at. They are not redundant because they bind at wildly different N — money binds at 200,000/3,601 ≈ 55 agents, the card binds at 3 — so neither can be dropped. The *number* is the human's.

### Types

```rust
// ═══ crates/marlowe-loop/src/budget.rs ═══════════════════════════════════════

/// The smallest budget in which a quarantined reader can describe a FULL group.
///
/// Derived, not chosen, in the idiom of `MIN_CHILD_TOKENS`:
///   `MEASURED_CHILD_FIRST_CALL_TOKENS`            3,089  one measured first call
/// + (600 + MAX_SOURCES_PER_READER * 1_500) / 4    2,400  the §5.1 contract's own output caps
/// + `MIN_CALL_TOKENS`                               512  room to close
/// = 6,001
///
/// `grant` has read `MIN_CHILD_TOKENS` since 2026-08-26 and this function never has. The
/// asymmetry is instance #16: a control read by one of the two sites that hand out budgets.
pub const MIN_QUARANTINED_READ_TOKENS: u64 =
    MEASURED_CHILD_FIRST_CALL_TOKENS
        + ((600 + MAX_SOURCES_PER_READER as u64 * 1_500) / 4)
        + MIN_CALL_TOKENS;

/// An INCREMENT, and deliberately not a `Budget`.
///
/// On a `Budget`, zero in a dimension means **already exhausted** — `exhausted` compares
/// `spent >= budget`. Here it means "no more of this". Two readings of zero on one type is
/// instance #17's setup, so these are different types and neither coerces to the other.
///
/// **No `depth`.** Depth is structural and is never extended: a run that has run out of depth
/// has run out of tree, not out of budget.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct BudgetDelta {
    pub tokens: u64,
    pub wall_ms: u64,
    pub tool_calls: u32,
    pub subagents: u16,
    pub micros_usd: u64,
}

/// Why the harness asked for more. **Harness-derived, never model-supplied.**
///
/// It is the dimension `Budget::exhausted` returned, which is the one fact about the request
/// that no model authored. §4.1's three-code enum is the rejected alternative: it puts
/// model-chosen bits on the one upward channel whose payload is a number.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum ExtensionReason {
    RanOutOf { dimension: Dimension },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExtensionOutcome {
    /// Inside the envelope. Raised, announced, and **nobody was asked** — §4.2's whole point.
    Granted { delta: BudgetDelta, headroom_left: Budget },
    /// Past the ceiling. §4.2's meeting, carrying the three numbers the user decides on.
    AsksTheUser { want: BudgetDelta, ceiling: Budget, already: Budget },
    /// Room in the envelope and still refused, with the numbers.
    Refused { reason: GrantRefused },
}

impl Budget {
    /// Field-wise sum. `add` mutates; this is the value form `Run::obligations` needs.
    pub fn plus(&self, other: &Budget) -> Budget { /* saturating, depth = self.depth */ }

    /// §4.2. **Pure arithmetic: it decides, it does not act.**
    ///
    /// `envelope >= self` in every dimension by construction (`Run`'s constructors are the
    /// only builders and they enforce it), so a raise can never exceed the ceiling by
    /// clamping rather than by a check that could be forgotten.
    pub fn extend(
        &self,
        obligations: &Budget,
        envelope: &Budget,
        want: BudgetDelta,
    ) -> ExtensionOutcome { /* ... */ }

    /// AMENDED: the floor `grant` has enforced since 2026-08-26, at the second site that
    /// hands out budgets. Below it, refuse — `condense_batch`'s honest "no budget remained
    /// to condense it" already exists at engine.rs:2119 and is the right message.
    pub fn slice_for_quarantined_read(&self, obligations: &Budget) -> Option<Budget> {
        let left = self.remaining(obligations);
        if left.tokens < MIN_QUARANTINED_READ_TOKENS { return None; }
        let tokens = share(self.tokens).min(left.tokens).max(MIN_QUARANTINED_READ_TOKENS);
        // ... wall_ms, micros_usd unchanged; tool_calls: 1, subagents: 1, depth: 0 (#17)
    }

    /// AMENDED: `subagents` is a HEADCOUNT GRANT, not a slice of the remainder.
    /// Was `at_least_one_u16(left.subagents.saturating_sub(1), left.subagents)` — a share of
    /// what REMAINS, which is what §4 abolished, in the dimension §4 did not look at. Two
    /// siblings doing identical work got 7 and 6.
    ///   subagents: at_least_one_u16(
    ///       share.apply_u16(self.subagents).saturating_sub(1).min(left.subagents),
    ///       left.subagents,
    ///   ),
}

// ═══ crates/marlowe-loop/src/run.rs ══════════════════════════════════════════

pub struct Run {
    // ... every field as pinned in CONTRACTS §5 ...
    pub budget: Budget,
    pub spent: Budget,

    /// **NEW.** Granted to children that have not yet returned.
    ///
    /// A grant is a PROMISE; `spent` is the past. `grant` clamps against `remaining(spent)`
    /// and `spent` only moves at engine.rs:2897, when a child returns — so with two children
    /// outstanding both are offered a share of a pool that has already been given away.
    /// Harmless while `Engine::spawn` runs children inline; an N-fold overcommit the moment
    /// M3 fans out, which is M3's entire premise.
    pub committed: Budget,

    /// **NEW.** The ceiling the harness may raise `budget` to WITHOUT asking (§4.2).
    ///
    /// INVARIANT, enforced in every constructor: `budget <= envelope` in every dimension.
    /// `Run::child` sets `envelope = budget`, so a child has no headroom and every extension
    /// below the top-agent travels up — §3.1's "approved at each level", structurally.
    /// `Run::root` for an ordinary conversational turn also sets `envelope = budget`, so
    /// today's behaviour (every extension asks) is the default and the safe direction.
    /// **Never model-supplied: `SpawnRequest` has no field for it and never gains one.**
    pub envelope: Budget,
}

impl Run {
    /// What the pool already owes. **The only argument `grant` should ever be given.**
    pub fn obligations(&self) -> Budget { self.spent.plus(&self.committed) }

    /// Reserve at spawn. Called by `Engine::spawn` immediately after a successful `grant`.
    pub fn commit(&mut self, granted: &Budget) { self.committed.add(granted); }

    /// Release the promise, charge the actual. Replaces the bare
    /// `run.spent.add(&child_run.spent)` at engine.rs:2279 and :2897.
    pub fn settle(&mut self, promised: &Budget, actual: &Budget) { /* sub promise, add actual */ }
}

// ═══ crates/marlowe-daemon/src/scope.rs — Session C creates this file ════════

/// The user's ceiling on one top-agent scope.
///
/// **Project-scoped, not run-scoped, and that is the load-bearing part.** `Run::root` is
/// rebuilt every turn at `daemon.rs:2486` with a hardcoded `Budget::interactive()`, so a
/// ceiling held on the run dies at the turn boundary — exactly the defect SECURITY-AUDIT §8
/// records about ADR-023's latch ("the latch belongs on the session, not the Run"). A
/// top-agent is project-scoped and outlives a turn, so its ceiling must too.
pub struct SpendEnvelope {
    ceiling: Budget,
    set_by: EnvelopeAuthor,
    set_at_ms: i64,
}

/// **One variant, and the single variant IS the mechanism.**
///
/// There is no `Agent`, so no code path can construct an agent-authored raise — the same
/// structural withholding as `ExposedSet::empty()`, not a permission check. `raise`'s match
/// has no wildcard arm, so adding a variant is a COMPILE ERROR, not a test failure.
///
/// **Deliberately NOT `Deserialize`.** Serde is a way in (family #12); a ceiling must not be
/// constructible from a config file, an MCP descriptor, or a spawn request.
pub enum EnvelopeAuthor {
    User { surface: SurfaceId },
}

impl SpendEnvelope {
    /// Only a `User` may raise, and lowering below what is already committed is refused with
    /// both numbers rather than retroactively invalidating a live child's grant.
    pub fn raise(&mut self, to: Budget, by: EnvelopeAuthor) -> Result<(), EnvelopeRefused>;
}

// ═══ crates/marlowe-journal/src/event.rs ═════════════════════════════════════
//     EventKind += BudgetExtended     // pinned list, CONTRACTS §1.1 — argued below
```

### Enforcement sites

- `Run::committed` -> **crates/marlowe-loop/src/run.rs::Run::obligations, called at crates/marlowe-loop/src/engine.rs::Engine::spawn (the `run.budget.grant(...)` at :2618) and Engine::condense_batch (the `slice_for_quarantined_read` at :2116); written by Run::commit (engine.rs::spawn, right after a successful grant) and Run::settle (engine.rs:2279 and :2897, replacing the bare `run.spent.add(&child_run.spent)`)** | breaks: `two_outstanding_grants_cannot_exceed_the_pool` goes red today, without concurrency: commit a 150k grant, then ask for another and it must be `GrantRefused::MoreThanRemains`. If `obligations()` returns `self.spent` alone, the second grant succeeds and the parent has promised 300k out of a 200k pool.
- `Run::envelope` -> **crates/marlowe-loop/src/budget.rs::Budget::extend (the `envelope` parameter), called from crates/marlowe-loop/src/engine.rs at the site where `Budget::exhausted` returns `Some(dimension)` — before the `PauseReason::BudgetExhausted` pause is emitted** | breaks: `an_extension_inside_the_envelope_is_granted_without_asking` goes red: with no envelope every extension routes to `ApprovalGate::await_approval`, which is the click-through interruption §4.2 exists to prevent. Its paired negative control (`envelope == budget` must always ask) goes red in the other direction if `extend` ignores the ceiling.
- `INVARIANT budget <= envelope, in every dimension` -> **crates/marlowe-loop/src/run.rs::Run::root, Run::child and Run::restored — all three constructors, which are the only builders; `Budget::extend` then clamps to `envelope` rather than checking against it** | breaks: `a_child_has_no_headroom_of_its_own` goes red: `Run::child` sets `envelope = budget`, so a worker cannot self-extend and every extension travels up. Drop the invariant and a master can hand a worker a ceiling, which reintroduces the compounding §4 abolished, one document later.
- `BudgetDelta (the type, as distinct from Budget)` -> **crates/marlowe-loop/src/budget.rs::Budget::extend takes it by value; nothing else constructs one** | breaks: Nothing turns red — a type distinction is enforced by the compiler, not by a test, and that is the point. Collapse `BudgetDelta` into `Budget` and `extend(want: Budget)` accepts a value whose zeros mean 'already exhausted' at every other site in the crate. The check is `cargo build`, not an assertion.
- `ExtensionReason::RanOutOf { dimension }` -> **the harness-authored announce string built at the extension site in crates/marlowe-loop/src/engine.rs and passed to crates/marlowe-daemon/src/announce.rs::say(AnnounceLevel::Info, ..); and the `EventKind::BudgetExtended` journal payload written by Engine::record** | breaks: `the_announce_line_names_the_dimension_that_fired` goes red. If nothing rendered it, this field would be instance #16 verbatim — a reason code set and never consulted, with a green test asserting its value.
- `EnvelopeAuthor::User (the single variant)` -> **crates/marlowe-daemon/src/scope.rs::SpendEnvelope::raise — a match with no wildcard arm** | breaks: Adding an `Agent` variant is a COMPILE ERROR at that match, which is the load-time error this project prefers to a sensible default. Deleting the match's exhaustiveness (adding `_ => {}`) is what a test must catch: `the_only_author_of_a_ceiling_is_a_person` asserts against a pinned `const EXPECTED_AUTHORS: [&str; 1]` rather than by iterating the enum, because a check whose input is the object it checks cannot see that object change (instance #19).
- `MIN_QUARANTINED_READ_TOKENS` -> **crates/marlowe-loop/src/budget.rs::Budget::slice_for_quarantined_read — both as the refusal threshold and as the `.max()` floor on the granted figure** | breaks: `the_shipped_tree_leaf_clears_the_floor_and_the_band` goes red printing `level 4 [TSa] 2636 tokens 1.318% floor 3601 STARVED`. It is red TODAY, before the fix, which is the evidence that the assertion is not a proxy.
- `subagents granted from the ORIGINAL rather than sliced from the remainder` -> **crates/marlowe-loop/src/budget.rs::Budget::grant, the `subagents:` arm of the returned Budget; the resulting figure is read by Budget::exhausted (the `spent.subagents >= self.subagents` arm) and by Engine::spawn's admission check at engine.rs:2625** | breaks: `a_second_sibling_is_offered_the_same_HEADCOUNT_as_the_first` goes red. The existing `a_second_sibling_is_offered_the_same_allocation_as_the_first` (budget.rs:527) asserts only `.tokens`, so it is green on a build where the headcount still decays 7, 6, 5 across identical siblings.
- `crates/marlowe-loop/artifacts/budget-bands-v1.json (the pre-registered band)` -> **crates/marlowe-loop/tests/leaf_budget_band.rs, via include_str! — the frozen-gate pattern the reranker's precision-coverage artifact already uses** | breaks: The test fails with 'no pre-registration' rather than assuming a band. A band embedded in an assertion (which is what budget.rs:506 does today) is a number chosen after seeing the result; a band in a checked-in artifact is a visible diff in whatever commit widens it.
- `EventKind::BudgetExtended` -> **crates/marlowe-loop/src/engine.rs::Engine::record at the extension site; read back by crates/marlowe-loop/tests/budget_envelope.rs through the test Recorder, and by any journal query reconstructing why a run's ceiling moved** | breaks: `an_extension_inside_the_envelope_leaves_a_record` goes red. This is the one spending path in the product where NOBODY is asked, so the approval trio (ApprovalRequested/Granted/Denied) cannot carry it — which is precisely why it is worth a pinned-list change and ADR-053's 'no new EventKind' precedent does not transfer: a settlement was already expressible as RunCompleted; a silent raise is expressible as nothing.

### Rejected

- **Model-supplied extension requests, exactly as M3-DESIGN §4.1 specifies them: `{run_id, amount, reason_code, evidence_ref}` with `reason_code` from a three-value enum, arriving as a new `ModelStep` variant or a loop-control tool.** - It costs a §13-guarded edit to `driver.rs` (`ModelStep`, `SpawnRequest`'s neighbours) and it puts model-chosen bits — an amount and a code — on an upward channel whose entire payload is a number, which is the ADR-023 question §4.2 asks me to close rather than open. The harness already knows everything the request needs: `Budget::exhausted` returns the dimension that fired, and the amount is arithmetic against the envelope. §4.1's own escape hatch is the argument for the narrowing — 'if a request genuinely needs free text it is not a budget request, it is an escalation, and it takes that path' — and escalation is §3's channel, which Session C builds anyway. Recorded as a deliberate narrowing of §4.1, not an omission.
- **Hold the envelope on a new `BudgetAuthority` port in `Ports`, consulted upward by the loop, with the daemon owning the `SpendEnvelope`.** - It adds a trait to `crates/marlowe-loop/src/driver.rs`, which is §13-guarded, and it threads a port through every construction site in the workspace for a value that is fixed at spawn and never changes mid-run. Two fields on `Run` carry the same information, survive the checkpoint, render in the window's existing spend-against-ceiling row (`control_plane.rs:285`), and reuse `ApprovalGate::await_approval` for the meeting — one existing port, one existing modal, one existing `TurnEvent::ApprovalPrompt`. It also avoids adding a `TurnEvent` variant, whose self-check (`turn.rs:128`, `names.len() == 7`) is instance #19's shape: its input is the list it checks.
- **Keep `Run` as pinned and hold outstanding commitments in `Engine`, beside the existing `self.children: Map<RunId, Vec<(RunId, OrphanPolicy)>>`.** - It avoids a CONTRACTS §5 change and it is wrong for one reason: `OrphanPolicy::Detach` means children outlive parents, so a commitment must survive a WAL resume or a restarted parent re-grants budget already held by a live detached child. `durable::Checkpoint` is what survives, and it carries `budget` and `spent` because they are `Run` fields. An engine-side map is exactly the 'a guarded path that moved' shape applied to state: correct, invisible after a restart, and silent about it.
- **Fix the starved leaf by raising `QUARANTINED_READ_NUMERATOR` from 2/8 to 4/8.** - It fixes the leaf by breaking the common case. The quarantined read is usually at depth one, where 4/8 hands half of a 200k conversational run to one page-reading child. The binding constraint at depth is not the fraction, it is a floor — which is precisely the shape `grant` already uses (`.min(left).max(MIN_CHILD_TOKENS)`) and which `slice_for_quarantined_read` was written without. A share for the rich case and a floor for the poor case, with a named refusal when even the floor does not fit.
- **Approving an over-ceiling extension raises the envelope itself, so the user is not asked again about the same scope.** - It is the click-through failure §4.2 names, weaponised. An agent that can produce a plausible over-ceiling request repeatedly ratchets the ceiling one approval at a time, and each individual approval looks reasonable. An approval raises `run.budget` for that request only; raising the ceiling is a separate, explicit user act on the scope. This is the fourth leg of the ADR-023 answer and it is the one that is a policy choice rather than a type.
- **Make the leaf-band acceptance a percentage-only assertion, as `a_leaf_at_depth_four_is_inside_the_declared_band` does today.** - 1.318% is inside [1%, 5%] and buys 2,636 tokens, which is below `MIN_CHILD_TOKENS` (3,601) and below the measured first call (3,089). The percentage reads identically whether the leaf can speak or not, which is the definition of a proxy in this project. The band asserts tokens against the floor, fraction against the band, and wall_ms against the measured cold-load time, in that order of authority.

### Tests

- `the_shipped_tree_leaf_clears_the_floor_and_the_band` in `crates/marlowe-loop/tests/leaf_budget_band.rs`
  - asserts: Walks the SHIPPED ladder — `Budget::interactive()` (depth 3, the value `daemon.rs:2564` builds) → Ta → Ma → Wa via `Budget::grant`, then the tool-spawned leaf via `slice_for_quarantined_read`, because level 5 is depth-exempt — and prints one row per level: tokens, fraction of root, wall_ms, and the floor each must clear. Asserts every row against `crates/marlowe-loop/artifacts/budget-bands-v1.json`, read with include_str!, and FAILS with 'no pre-registration' if the artifact is absent rather than assuming a band. Command: `cargo test -p marlowe-loop --test leaf_budget_band -- --nocapture > runs/m3-session-c/leaf-band.txt`.
  - red on: It is RED BEFORE THE FIX, which is the evidence it is not a proxy: today it prints `level 4 [TSa] 2636 tokens 1.318% wall 7910ms floor 3601 STARVED`. After the fix, reverting the `MIN_QUARANTINED_READ_TOKENS` floor in `slice_for_quarantined_read` reddens it on the token row; putting `BudgetShare::Standard` back to 2/8 reddens it on the fraction row; deleting the artifact reddens it as a missing pre-registration.
- `two_outstanding_grants_cannot_exceed_the_pool` in `crates/marlowe-loop/tests/spawn_and_budget.rs`
  - asserts: A `Run::root` with 200,000 tokens: `run.commit(&first_grant)` for 150,000, then `run.budget.grant(&run.obligations(), BudgetShare::Large, Some(150_000))` must return `GrantRefused::MoreThanRemains { want: 150_000, left: 50_000 }` — both numbers, as every other refusal does. This is the property that makes §4's 'deducted from the parent's pool' true of the code and not only of the document, and it is testable today, before spawn is concurrent.
  - red on: Make `Run::obligations()` return `self.spent` instead of `self.spent.plus(&self.committed)`, or delete the `run.commit(&child_budget)` call from `Engine::spawn`: the second grant then succeeds and the parent has promised 300,000 out of a 200,000 pool.
- `an_extension_inside_the_envelope_is_granted_without_asking_and_one_past_it_asks` in `crates/marlowe-loop/tests/budget_envelope.rs`
  - asserts: Two arms against a counting `ApprovalGate`. Arm 1 — a run with `envelope.tokens == 4 * budget.tokens` runs out of tokens: `await_approval` is called ZERO times, `run.budget.tokens` has risen, one `EventKind::BudgetExtended` is in the recorder, and one `AnnounceLevel::Info` line naming the dimension was issued. Arm 2, the NEGATIVE CONTROL — a run with `envelope == budget` (the default, and every `Run::child`) runs out: `await_approval` is called EXACTLY once, and on a decline `run.budget` is unchanged and the run pauses with `PauseReason::BudgetExhausted`. Without arm 2 the test is green on a build where nothing ever asks.
  - red on: Compare against `budget` instead of `envelope` in `Budget::extend` and arm 1 goes red (everything asks); clamp to `u64::MAX` instead of `envelope` and arm 2 goes red (nothing asks); delete the `announce::say` call and arm 1 goes red on the announcement count.
- `a_latched_run_cannot_ask_for_more_budget` in `crates/marlowe-loop/tests/budget_envelope.rs`
  - asserts: A run whose floor has latched to `UntrustedContent` hits its token cap: the extension is refused and the run pauses, because the amount is a number untrusted content could have shaped. The threshold asserted on is `marlowe_permission::blocks_composed_targets(run.trust_floor())` — the single definition the adjudicator enforces on — NEVER on `TrustFloorLatched`, which fires on every run that has ever run (instance #15). The paired positive control is a run at `UserAsserted` with the identical budget state, which extends.
  - red on: Remove the `blocks_composed_targets` guard from the extension site and the latched arm extends. Replace it with a `TrustFloorLatched` event check and BOTH arms pass, which is the mutation the instance-#15 control is there to catch.
- `a_quarantined_read_below_the_floor_is_refused_by_name_rather_than_starved` in `crates/marlowe-loop/src/budget.rs (mod tests)`
  - asserts: A parent with `left.tokens` anywhere in [1, MIN_QUARANTINED_READ_TOKENS) returns `None` from `slice_for_quarantined_read`, so `condense_batch` emits its existing honest message at engine.rs:2119 ('the content was not read: no budget remained to condense it') instead of spawning a reader that pauses before its first call. And every `Some` it does return clears `MIN_CALL_TOKENS` — the same relationship `a_granted_child_can_always_make_at_least_one_call` asserts for `grant`.
  - red on: Delete the `left.tokens < MIN_QUARANTINED_READ_TOKENS` early return: the function returns `Some(2_636)` for the depth-4 case and the assertion that every returned budget clears the floor fails on that exact figure.
- `the_model_has_no_word_for_the_envelope` in `crates/marlowe-loop/tests/budget_envelope.rs`
  - asserts: Two halves. (a) `SpawnRequest::from_args` given `{"task": …, "exposed_tools": "", "envelope": 10000000, "ceiling": 10000000, "spend_limit": 10000000}` produces a request byte-identical to the same args without those keys — the shape ADR-057 §5 already uses for `share` and `reads_untrusted`. (b) `run`'s registered manifest declares no parameter whose name matches envelope/ceiling/limit, asserted against the manifest the tool host actually registers.
  - red on: Add an `envelope` read to `SpawnRequest::from_args` (half a), or add the parameter to `run`'s manifest (half b). Half (a) alone is the weaker claim — it tests the parser, not the wire — so the live half is the `--dev` outbound-request dump on a real turn, which needs Session C's model-driver seam and is named as such rather than claimed.
- `a_second_sibling_is_offered_the_same_headcount_as_the_first` in `crates/marlowe-loop/src/budget.rs (mod tests)`
  - asserts: The existing `a_second_sibling_is_offered_the_same_allocation_as_the_first` (budget.rs:527) asserts only `.tokens`. This adds `.subagents`, `.wall_ms`, `.tool_calls` and `.micros_usd` to the same property: two siblings doing identical work get identical allocations in EVERY dimension until the pool is genuinely gone. This is §12 item 4's answer made executable — the headcount is granted from the original, not sliced from the remainder.
  - red on: Restore `subagents: at_least_one_u16(left.subagents.saturating_sub(1), left.subagents)` — the line as shipped at budget.rs:237 — and the second sibling gets 6 where the first got 7. The current test is green on that build, which is why the assertion has to name the dimension.

### Contract impact

Four changes, three of them to pinned text. (1) CONTRACTS §5, `Run`: two new fields, `committed: Budget` and `envelope: Budget`, with the invariant `budget <= envelope` stated where the struct is pinned. (2) CONTRACTS §5, a new §5.2 pinning `BudgetDelta`, `ExtensionReason`, `ExtensionOutcome`, `SpendEnvelope` and `EnvelopeAuthor`, plus the sentence that `EnvelopeAuthor` is not `Deserialize` and why. (3) CONTRACTS §1.1, `EventKind`: one variant, `BudgetExtended`. This is a pinned-list change and ADR-053's precedent ("No new EventKind. CONTRACTS §1.1 pins the kind list") is cited and DISTINGUISHED rather than ignored: a settlement was already expressible as `RunCompleted`, whereas a within-envelope raise is expressible as nothing, and §4.2's defining property is that nobody is asked — so the ApprovalRequested/Granted/Denied trio cannot carry it. Without it, the one spending path in the product that involves no human has no audit trail. (4) NOT a CONTRACTS change but a versioned one: `durable::Checkpoint` gains `committed` and `envelope` and `CHECKPOINT_VERSION` bumps; a checkpoint written before the bump must be REFUSED at restore, not defaulted — `envelope: 0` would read as "already at the ceiling" and `committed: 0` as "nothing owed", which is instance #17 in both directions on the resume path. Two things this decision explicitly does NOT change: `SpawnRequest` gains no field (`grant_tokens` already exists; the roadmap's claim that CONTRACTS §5 pins `SpawnRequest`'s fields is false — line 941 pins only `fn spawn(&self, req: SpawnRequest) -> RunId` — so C's `role` field is the first pinning of that shape and §4 rides along at zero cost), and `Budget`'s six dimensions are unchanged. Noted in passing, not fixed here: CONTRACTS §12 defines a `Checkpoint` with `transcript_ref`, `pending_calls` and `guidance` that the shipped `durable::Checkpoint` does not have, while ADR-053 says `Checkpoint` "was named there and never defined". Two definitions of one pinned type already disagree; whoever edits §12 for this must decide which one is the contract.

### Guarded

["crates/marlowe-loop/src/driver.rs — READ ONLY IN THIS DESIGN, AND DELIBERATELY SO. `SpawnRequest`, `ModelStep` and `ApprovalGate` all live here, and the two obvious designs (a `ModelStep::RequestExtension` variant, or a new `BudgetAuthority` port) both edit it. Both were rejected specifically to avoid it. If a later session revives model-supplied extension requests, that session touches a §13-guarded file and needs a human's approval plus a DECISIONS.md entry. SAYING THIS LOUDLY BECAUSE THE ALTERNATIVE IS THE MORE OBVIOUS DESIGN.", 'crates/marlowe-loop/src/profile.rs — NOT TOUCHED. `CapabilityProfile::quarantined_reader()` is unchanged; the leaf fix is entirely in `budget.rs`.', 'crates/marlowe-permission/src/adjudicate.rs — NOT TOUCHED. The latched-run guard on the extension path calls the existing `marlowe_permission::blocks_composed_targets` from `marlowe-loop/src/engine.rs`, which is ordinary milestone work, exactly as `Engine::spawn` already does at engine.rs:3237.', 'crates/marlowe-daemon/src/memory.rs — NOT TOUCHED. Nothing here wires `ingest`; `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns two definitions and zero call sites after this change.', "crates/marlowe-daemon/src/daemon.rs — not §13-guarded, but ANOTHER AGENT IS EDITING IT RIGHT NOW. The only change this design wants there is that a top-agent's `Run::root` takes its envelope from the scope instead of `envelope = budget`; the conversational root at :2564 is untouched. Sequence that after the other agent lands."]

### For the human

["THE DEFAULT ENVELOPE FOR A TOP-AGENT. `Budget::interactive()` is 200,000 tokens / $2.00 / 8 subagents / 10 minutes and it is hardcoded at daemon.rs:2564 for a run that lives one turn. A top-agent is project-scoped and outlives a turn, so its ceiling is a different number and it is the user's money. The design ships with `envelope == budget` (every extension asks) as the safe default precisely so this number can be decided without blocking the mechanism.", "WHETHER THE ENVELOPE IS PER TOP-AGENT SCOPE OR PER PROJECT. §4.2 says the user sets a ceiling 'at spawn', which reads per-scope. A per-scope ceiling means ten scopes may each spend the ceiling; a per-project ceiling is what actually bounds a day's spend. This is the same shape as ADR-032 §3.1's flagged 'session-scoped' looseness on egress grants, and both are the human's.", "`Budget::interactive().subagents = 8` VERSUS WHAT FITS ON THE CARD — §12 item 4's number, as opposed to its shape. Measured on this machine today: three roles co-resident at 14,993 MiB used and 1,053 MiB FREE, with 5,086 MiB held by the desktop before any model loaded. AGENT-DIRECTORY.md §2's claim of '10.0 GB … leaving headroom for the KV cache, the embedder and the reranker' is contradicted by that measurement, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD — so the embedder silently falls to CPU with a correct-looking log line. Whether the headcount bound stays 8 or becomes a function of residency is a product decision that interacts with Session C's admission control (ROADMAP C item 5), and it is not a design agent's call. I recommend the SHAPE (a token pool and a headcount, both, granted the same way) and leave the NUMBER open.", "SECURITY-AUDIT §8's STANDING ANSWER, WHICH THIS DESIGN LEANS ON WITHOUT RE-OPENING. §8 states 'the latch belongs on the session, not the Run'. My envelope is scope-scoped for the identical reason — `Run::root` is rebuilt every turn at daemon.rs:2486 — and ROADMAP's C row requires that answer be recorded in DECISIONS.md before Session D depends on it. Recording the ceiling's scope must not silently settle the latch's scope; they are the same question and the human owns both.", "WHETHER §4.1's MODEL-SUPPLIED `reason_code` AND `evidence_ref` ARE BEING GIVEN UP OR DEFERRED. I recommend harness-derived reasons and drop `evidence_ref` entirely, because nothing in the current product opens an artifact ref from an approval modal and a field nothing reads is instance #16. If the human wants §4.1 as written, the cost is a §13-guarded edit to driver.rs and a re-opened ADR-023 question about a model-chosen amount."]

### Risks

["`Run::committed` is unit-enforced and PRODUCT-UNREACHABLE until spawn is concurrent. `Engine::spawn` runs its child inline (`self.run(&mut child_run, …)` around engine.rs:2880) and settles at :2897, so a parent never has two outstanding grants and the overcommit the field prevents cannot occur in the shipped binary. This is exactly the layer-3 shape — a guard that is correct, tested, and measuring a state the product cannot enter — and it MUST be written into STATE.md in those words rather than reported as 'budgets are now reserved'. The loop-level test lands with concurrency; only the unit-level one is honest today.", "`MIN_QUARANTINED_READ_TOKENS`'s chars-to-tokens divisor of 4 is the one INVENTED step in an otherwise derived constant, and a derived constant with one convention in it reads identically to a fully measured one — the family that produced instance #16. `MEASURED_CHILD_FIRST_CALL_TOKENS` was read out of the journal at seq 4597; the same command applies here — read a real `condense_batch` child's `Usage` from the journal and replace the divisor. Until then the doc comment must say which of its three terms is measured and which is not.", "THE BAND ARTIFACT IS EDITABLE BY THE SESSION IT CONSTRAINS. `crates/marlowe-loop/artifacts/budget-bands-v1.json` is checked in, so a session that cannot hit the band can widen it. This is instance #19's family — a check whose input is reachable by the thing being checked — and it is MITIGATED, NOT CLOSED: the test prints the band and the measured number together into `runs/<session>/leaf-band.txt`, so a later widening is auditable against an earlier run file. `tools/preregister_budget_bands.py` refusing to overwrite an existing artifact is the same discipline `preregister_split.py` uses and the same discipline anyone can bypass with an editor.", "THE WALL-CLOCK DIMENSION CAN STARVE THE LEAF AFTER THE TOKEN FIX SHIPS, WITH THE BAND GREEN. The depth-4 leaf's wall budget is (3/8)^3 x (2/8) x 600,000 = 7,910 ms, and this session measured Ollama cold-load-plus-one-token at 3,212-5,442 ms for the mini models. If the extractor role is not resident, most of the leaf's wall budget is a model load. A band that asserts tokens only is the same proxy one dimension over, which is why the artifact carries a `wall_ms` row per level and the test prints it.", 'ADDING A `TurnEvent` VARIANT WOULD HAVE WALKED INTO INSTANCE #19. `turn.rs:128` asserts `names.len() == 7` against a list defined inside the same test — its input is the object it checks, so it can see an addition (by failing the count) but not a deletion. This design adds no variant, reusing `announce::say` and `ApprovalGate`, and that is a reason as well as a convenience. A later session that wants a `BudgetExtended` TurnEvent inherits the problem.', "`slice_for_quarantined_read`'s doc comment claims a quarantined reader 'structurally cannot call `run`' because it holds `ExposedSet::empty()`. Checked: `Engine::spawn` never consults the caller's exposed set — the only thing stopping a toolless child from spawning is `depth: 0` returning `GrantRefused::NoDepth`. Containment holds because both are set, but the STATED reason is not the operative one, which is the 'assert the property you care about' family aimed at a comment. It matters to anyone tempted to relax depth for toolless children — I considered it for SCOPED-MEMORY §4's fact extractor and rejected it for this reason. The extractor should take a `slice_for_*` sibling with `depth: 0`, never a `grant`. Related to SECURITY-AUDIT C12 (quarantine recursion bounded circumstantially, LOW) and cited rather than re-filed as new.", "THE STARVED LEAF IS A QUALITY FINDING WITH A SECURITY SHAPE, AND IT IS NOT IN SECURITY-AUDIT. C4 and C5 (the #17 zeros) are recorded and FIXED; the `MIN_CHILD_TOKENS` asymmetry is newer than that audit and grep of SECURITY-AUDIT.md and STATE.md returns nothing for it. It is not filed as a security finding because a starved quarantined reader FAILS CLOSED — it returns nothing and the parent is told so — but the observable symptom is 'the content could not be condensed', which is indistinguishable from a page that had little to say, and that is the output ADR-041's own commentary says nobody can audit."]
