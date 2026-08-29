# ADR-062 · `ingest` has no correct production caller, and that is the build order rather than an oversight

**Status:** Accepted, M3 Session B2, 2026-08-29. **Nothing is wired by this decision.**

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | ADR-039's final Consequence, one sentence (§6.2). Records ADR-038's `min`, and the two `min`s added by `6a1f4f5`, as vacuous on every reachable path (§6.1). Replaces CLAUDE.md's layer-3 ordering rule and its prescribed grep. Replaces M3-DESIGN §8's opening and closing sentences, and ROADMAP's M3 "then wire, then test" bullet |
| **Depends on** | ADR-023 (the latch), ADR-038 (the claim's floor), ADR-039 / ADR-041 (quarantined read routing and its group unit), ADR-044, M3-DESIGN §2.1, §7, §8, CONTRACTS §3.3 |
| **Contract change** | **None.** No schema moves, no `Channel` variant is added, no trust class changes |
| **Code change** | Two defects in the uncalled port, fixed (§6.3). **`MemoryHost::ingest_external` stays declared and uncalled, deliberately** |

---

## 1 · The finding

**`marlowe_memory::ingest` has no correct production caller, and until `673bcd2` it had no
production caller at all.** The consequence is the one CLAUDE.md's layer-3 paragraph states, and it
is worth one sentence: **the shipped daemon cannot enter the state layer 3 defends, so a test that
asserts that boundary passes with every guard deleted.**

The check is a command, not an argument — and **the command has changed, which is itself a finding**
(§6.4):

```
$ grep -rn "\bingest(" --include=*.rs crates/ | grep -v /tests/
crates/marlowe/src/adapter.rs:346          # --eval-adapter
crates/marlowe-daemon/src/memory.rs:604    # DaemonMemory::ingest_external -- added 673bcd2
crates/marlowe-memory/src/ingest.rs:30     # the definition

$ grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"
                                           # (nothing)
```

**The second grep is the whole finding: the port exists and nothing invokes it.** The first one used
to answer the same question and no longer does.

That state is committed on purpose. `673bcd2`'s message says so — *"the next commit is visibly the
one that makes it load bearing rather than a diff in which the port and its caller are
indistinguishable."* It is instance #16's exact shape, held deliberately for one commit, and this
ADR is the record of why the next commit is not that one.

### 1.1 · Why the latch cannot fire without it

Four links, each checked by grep rather than reasoned:

1. Injected memory is untrusted only if some belief is `UntrustedContent`.
2. A belief becomes `UntrustedContent` from `ingest` (`trust_for_channel` maps
   Web / Email / Messaging / Mcp / File) or from `remember_claim` under an already-bottomed floor —
   which is circular, and `driver.rs` says so in its own words.
3. ADR-039 / ADR-041 removed tool results as a taint source: no untrusted tool result reaches a
   parent's window at all, so a fetch no longer moves a parent's floor.
4. `ingest`'s only caller with a caller of its own is the eval adapter.

So `blocks_composed_targets` is `false` for every reachable parent-run floor in the shipped daemon.
The guard is correct, enforced at one site, and **unreachable**.

---

## 2 · Why it cannot simply be wired

Two constraints, each verified in code, and the conclusion is their composition rather than either
one alone.

### 2.1 · Marlowe must never be tainted

M3-DESIGN §2.1: layer 3's floor is monotonic and latched per run, and **Marlowe is a permanent
run — spawned by nobody, one instance ever.** So a Marlowe who ingests one untrusted belief

> can never compose a target again — not for that task, for his life.

Today the daemon has exactly one run and it is Marlowe. Wiring `ingest` at the condense site would
taint him permanently on the first `web` call: the C2f complaint restored in a form no restart-free
mechanism can lift.

**The answer to permanent taint is never a clearing mechanism.** A clear would un-latch a floor
ADR-023 makes monotonic on purpose, and monotonicity is the entire content of the guard. §2.1 names
the actual answer: *"the liaison pattern is not ergonomics; it is the only shape that survives
ADR-023."*

### 2.2 · Workers hold no `MemoryWrite`

M3-DESIGN §7: *"workers do not hold `MemoryWrite` until scoped memory exists."* Not aspiration —
both child `Ports` constructions hardcode it:

| Site | Child | `memory` |
|---|---|---|
| `engine.rs:2215` | the quarantined reader | `None` |
| `engine.rs:2831` | an ordinary spawn | `None` |

A run that may correctly hold an untrusted belief exists in the design and does not exist in the
build.

### 2.3 · The composition, which is the part to keep

| | may be tainted | may write memory |
|---|---|---|
| **The parent run (Marlowe)** | **no** — §2.1, and permanently | yes (`daemon.rs` passes `memory: Some(..)`) |
| **Any child run** | yes — its floor drops and dies with it | **no** — §7, `memory: None` at both sites |

> **There is no run in the current architecture that may correctly hold an untrusted belief.**

The two rows are disjoint and their intersection is empty. That is a property of the build order —
scoped memory has not been built — not a defect to work around. Working around either half means
either tainting the permanent run, or handing a worker the highest-privilege operation in the system
before the design that scopes it exists.

---

## 3 · The verdict on "same bytes, two classes"

The question the session set out to settle: the condensed summary enters the parent's window at
`AgentInferred` (the `note` closure, `engine.rs:2001-2009`) and ingesting it would store it at
`UntrustedContent`. Same bytes, two classes, one turn.

### 3.1 · The contradiction dissolves at the object boundary, and the resolution is not to pick one class

**The two stamps are on two different objects with two different lifetimes.** A `Block` is a value
in one run's window and dies with the run. A `MemoryEntry` outlives every run, is auto-injectable
into windows that do not exist yet, and is pushed back into a future run at `retrieved.floor`
(`daemon.rs`'s injected-memory push).

ADR-039 argued the crossing for the first object, in its own terms: the summary is *"capped,
sanitized, and structurally unable to forge the record it arrives in."* Three properties, all about
a value **inside one window**. ADR-038 named the asymmetry from the other side: *"writing a memory
is composing a durable target out of run content — the longest-lived composition the system
performs."*

So two classes on the same bytes is the **correct** shape, not an incoherence — provided neither is
derived from the other. **The error, in either direction:**

* *Promoting the store class because the window says `AgentInferred`* extends a declaration crossing
  argued for a run-scoped value into a permanent, cross-run one. That is strictly more than ADR-039
  established, and nobody has written the durable version of that argument.
* *Demoting the window block because the store would say `UntrustedContent`* makes
  `view.trust_floor()` latch on every fetch, reproducing exactly the complaint ADR-039 was built to
  close — *"after fetching web data all his tools get turned off. seems dumb."* The containment
  marker that would separate the two concerns does not exist, is §13 territory, and cannot be built
  by inference from this ADR.

### 3.2 · The store class is `UntrustedContent`

Settled, and **not as a tie-break between two readings.** The reason is narrower and it is about
evidence rather than semantics: storing at `AgentInferred` asserts a property — that the declaration
crossing survives an unbounded lifetime and repeated auto-injection — that nobody has argued and no
test measures. CLAUDE.md's standing question applies directly: *what would this read if the property
were broken?* It would read `AgentInferred`, identically.

CONTRACTS §3.3 is the second reason and points the same way: *"a fact the model extracted from bytes
inherits the bytes' origin class."* A condensed summary is exactly that. Audit finding E5
(`6a1f4f5`) ruled this way for `compact` three days earlier, in the same words — *"right about the
SPEAKER, wrong about the ORIGIN"* — and a condensation is one rewrite by the same argument.

### 3.3 · The window stamp stands, as a bounded exception with a stated expiry

`AgentInferred` in the `note` closure is **not** revised here. The honest record of what it is:

> A run-scoped privilege decision, valid for the window it was made in, **invalid the moment those
> bytes are offered to a durable store.**

Writing it that way is the point: it is what stops a future session citing that line as precedent
for ingesting at `AgentInferred`, which is the shape this contradiction takes on its next reading.

**And `Block.trust` is thereby established as overloaded**, carrying two independent questions:
*whose authority is behind this content* (layer 2, §3.3) and *should this run lose composed targets*
(layer 3, ADR-023). The quarantined reader is precisely where they come apart, because containment
changes the second without touching the first. `context.rs` documents the field as *"Origin-bound.
The assembler never derives this from content — §3.3's rule"*, and that comment is false of its one
interesting construction site. Separating the privilege bit from the origin bit is named design
work, it is §13 territory, and it wants a `DECISIONS.md` entry before any code. **It earns nothing
until `ingest` has a caller**: a field stamped `UntrustedContent` plus a marker exempting it from the
latch is byte-identical in behaviour to today, and a test asserting the class would be asserting a
declaration nothing reads.

---

## 4 · WHAT IS NOT DECIDED, AND IT IS THE HUMAN'S: the origin

The class is settled. **The origin such a belief would be recorded under is not, and this ADR does
not manufacture one.**

`Channel::Web` records something the harness knows to be false. The page did not emit those bytes.
Every structural property of a condensed summary is harness-authored — the brief the reader answers,
the slot labels (*"assigned here, never taken from the content"*), the field set, the caps, the
renderer, the character check. `trust_for_channel` is **total over a closed set with no default
arm**, and `trust.rs`'s header says why: *"an unrecognized value is a load-time error on both sides.
It is never mapped to a default."* An origin that is not in the set is therefore a decision by
construction, and passing `Channel::Web` uses the channel table to answer a question ADR-038 already
established it cannot answer — *"a model is not a channel."*

M3-DESIGN §8 raises the same question one step later and refuses to answer it by borrowing:

> There is no `Channel::Agent` and no trust class for an agent's speech. **Either add one, or record
> a decision that typed upward structure needs none.**

| Option | What it says | Cost |
|---|---|---|
| **A. `Channel::Web`** | the belief's origin is the page | Records a provenance the harness knows to be false, on a field documented as *"provenance for a human reading the journal"*. Cheapest; the class comes out right for the wrong reason, and the wrong reason is what a later session inherits |
| **B. Add `Channel::Agent`** (or `HarnessMediated`), mapped to `UntrustedContent` | the origin is a harness-mediated reader over external bytes | Honest, and it settles one of §8's adjacent cases at the same time. Costs a `Channel` variant — a **contract change**, wire-visible, `trust_for_channel`'s exhaustive match and the eval side both. Not a decision a session may take alone |
| **C. Carry the page as lineage and let `min` do it** | the belief's parent is the page | **Not expressible today** — see §5. Would need `ingest` to take a derivation, and the page to be a belief in the first place |

**Option B is where this ADR would go if it were entitled to go anywhere.** It is not: it changes a
pinned contract, and there is no correct caller to exercise it (§2), so shipping the variant first is
the label-before-the-reader pattern this repo keeps logging.

### 4.1 · This does NOT close M3-DESIGN §12 item 5

§2.3 of M3-DESIGN answers the **typed upward return** — `{ run_id, severity, category, artifact_ref,
lineage[] }` carries no classifiable prose and is never ingested, so it needs no `Channel`. That is a
narrow decision and it is recorded in `DECISIONS.md`. **Two other consumers of the same missing slot
remain open**, and either would still need the variant on the day typed structure is proven to need
none:

1. **The meeting utterance** (M3-DESIGN §5.2, *"clone, and quarantine the utterance"*) — a lateral
   agent utterance is neither the downward instruction §2 declares safe nor the typed upward record
   §2.3 governs. ROADMAP Session E.
2. **The harness-mediated reader** — this ADR's §4. A condensed summary is not agent speech at all,
   so §2.3's argument does not reach it.

---

## 5 · Why the channel choice carries the entire class — the structural finding

**Layer 2's `min`-over-lineage cannot express "this belief came from a page", on either production
write path:**

* **`ingest`**: `let derivation: Vec<String> = Vec::new();` is hardcoded, with a comment saying
  Session A writes no derived beliefs. `effective_trust(own, &[])` is therefore the identity, and
  `trust_for_channel(channel)` alone decides the class. There is no parameter through which a caller
  could say otherwise.
* **`remember`**: `derived_from` is model-supplied and is a list of **belief ids** resolved against
  the store. **A fetched page has no belief id**, so a claim derived from a condensed summary cannot
  name the page as a parent even if the model wanted to.

So layer 2's headline — *"four LLM rewrites later, a web page is still `UntrustedContent`"* — is
implemented correctly in `trust.rs` and, on the ingest path, **has nothing to operate on.** The
channel field is the only lever there is.

**That is why `Channel::Web` would not be a provenance blemish. It would be the class.** Setting it
wrong does not mislabel a correct decision; it *is* the decision, made by a field whose documented
job is to record where something came from.

---

## 6 · Filable today, independent of `ingest`

### 6.1 · THREE `min`s are the identity function on every reachable path, not one

ADR-038's `remember_claim` computes `min(AgentInferred, run_floor)`, justified by one worked
example: *"a run that fetches a page and then calls `remember` would write attacker-shaped text at
`AgentInferred`."* **True when written in M2 Session D. ADR-039 (Session E) removed the floor
movement that was its only trigger**, and §1.1's chain shows no other production source of
`UntrustedContent` in a parent's window. Memory is live in the product, `remember` is in the
interactive exposed set, and the loop hands the latched floor to the host.

**So today a run fetches a page, reads the condensed note, and writes a sentence out of it durably at
`AgentInferred` — precisely the scenario ADR-038 was accepted to prevent, now unreachable by its own
formula.** Family #14: a guarded path whose trigger a later change removed, with the guard reporting
nothing.

**And `6a1f4f5` — this branch's own two fixes — added two more of exactly the same shape.** This is
not a criticism of them; they are correct, they were the right order, and the alternative was
shipping the laundering. It is a reachability fact that has to be recorded beside them or the next
citation reads *"the trim marker is guarded"* as *"a fetched page is guarded"*:

| `min` | Where | Reachable today |
|---|---|---|
| ADR-038's `min(AgentInferred, run_floor)` | `claim.rs`, `remember_claim` | **no** |
| **F1** — the omitted-block class folded into the trim marker | `context.rs`, `trim_to_budget` | **no** |
| **E5** — the compaction summary stamped `min(AgentInferred, discarded_floor)` | `context.rs`, the compaction path | **no** |

All three need an `UntrustedContent` block in a **parent's** window. F1's own comment states the
premise: *"Since ADR-041 removed tool results as a taint source, `InjectedMemory` is the only
remaining `UntrustedContent` carrier in a parent's window."* `InjectedMemory` is pushed from
`DaemonMemory::retrieve`, which can only return an `UntrustedContent` belief that `ingest` wrote, and
`ingest_external` has no caller. **All three go live on the same day, and it is the day this ADR
defers.**

The mutations that turned E5 and F1 red were driven from hand-pushed untrusted blocks. That is
evidence about the assembler, and it is not evidence about a fetched page.

Verify by enumerating producers of `UntrustedContent` blocks in a parent window; do not verify by
re-reading ADR-038, which is where it looks fine.

### 6.2 · ADR-039's Consequences contains a false sentence that contradicts a bullet three above it

ADR-039's last Consequence, of the condensed summary: *"it may inform **analysis**, and layer 3 still
refuses to let it choose a **target**."*

**Layer 3 does not refuse.** `blocks_composed_targets(origin) = origin <= UntrustedContent`,
`AgentInferred = 1`, `UntrustedContent = 0`, so the predicate is false and `taint_for` assigns the
window floor — `AgentInferred` — to every model-composed argument. A 1,500-character `source_1` field
asserting a command reaches the parent at `AgentInferred` and the resulting target is adjudicated
clean. That contradicts the bullet three above it in the same document (*"a run that reaches
`UntrustedContent` still loses composed targets"*), which is true and is about a different thing.

Family #16 in documentation rather than code: **it is the sentence a future session would cite as
evidence the path is guarded.** The correction is owed whichever way §4 goes. The right statement is
ADR-039's own honest bullet plus M3-DESIGN §2.2 point 3 — *"no layer defends against a document being
wrong, and none could"* — i.e. the residual channel is accepted and bounded, not closed by layer 3.

### 6.3 · Defects in the uncalled port — three found, three fixed on this branch

Fixed rather than filed, because they must not be waiting when the port acquires a caller. All three
were reachable only through a method nothing calls, so **none of them was ever a live product bug**,
and none of these fixes changes any product behaviour.

**(a) The id collapsed an ADR-041 group.** `ingest_external` built
`turn_id: format!("external:{run}:{now_ms}")`, and `memory_id` is `m-{session}-{turn_id}-{index}`
with `index` always `0` for the one-turn request it sends and **no timestamp by design**. ADR-041's
group read handles up to `MAX_SOURCES_PER_READER = 6` sources in one turn at one clock reading, so
six ingests collided on one id; `BeliefStore::insert` is a `BTreeMap` insert, so **the journal kept
all six events and the derived store kept the last** — no error, no event, no failing test.

Fixed by deriving the turn id from `(channel, reference, text)`, length-prefixed, through
`Uuid::new_v5`. **Time had to leave, not merely be insufficient**: a `memory_id` containing a
timestamp fails the clock probe's translation invariance.
Red-before-green: `runs/m3-mutation/mut5-id-collision.txt` (`left: 1, right: 6`, and two more).

**Two properties of the fix, both bounded and both stated rather than implied.** The channel is
encoded through the **pinned serde spelling**, not `Debug` — a `Debug` derive is not a stable format,
and a source-only variant rename would silently fork the store — and
`external_turn_id_is_pinned_to_the_wire_spelling` asserts a whole derived id against a literal.
And `run` stays in the id, so **the anti-corroboration property is intra-run only**: production
`RunId`s are `Uuid::new_v4`, so the id is reproducible within a run (replay and resume carry the
persisted id) and different across runs, turns and restarts, by construction. Whether identity should
be global is an open question, recorded, not a settled trade.

**(b) A re-ingest resurrected a tombstoned or superseded belief.** Content-derived identity is what
made this reachable, and it arrived with the fix for (a). `BeliefStore::insert` overwrites the entry
wholesale, and `derive` replays with the same insert, so a second `MemoryWritten` for one id restores
the text `Tombstoned` cleared, resets `fidelity` to `Record`, and clears `superseded_by` — in the
live store **and** in the journal rebuild. Concretely: the user says *forget that*, the same page is
fetched again in the same run, and the forgotten belief is back at full fidelity and readmitted as an
injection candidate by §4.3 exclusion (1).

Fixed by making a repeat write on an already-known id a **no-op that returns the class the store
already holds** — the caller is told what this origin's class is, which is what it asked, and nothing
is journalled. Red-before-green, measured this session: with the guard disabled,
`a_tombstoned_belief_stays_dead_when_the_same_source_is_ingested_again` reads
`left: Record, right: Tombstone` and `a_supersession_survives_a_re_ingest_of_the_superseded_source`
reads `left: None`.

**The guard is at the caller, not inside `marlowe_memory::ingest`, deliberately.** `ingest` is the
§4.6 path the eval harness drives; `eval/` is the scoreboard and changing what a repeated turn id
means there would change the scoreboard's behaviour to accommodate an implementation. **The general
property — that `BeliefStore::insert` on a live id resurrects it, and that `derive` agrees — is
untouched and is raised here rather than fixed.** It is currently unreachable outside this path
because every other writer produces fresh ids, and it becomes a real defect the moment any writer
can repeat one.

**(c) `RecordingMemory` returned a hardcoded `Ok(TrustClass::UntrustedContent)`** — the double's
constant, green with `trust_for_channel`, `ingest` and the daemon impl all deleted. It was moved to a
value no test can want. **It went to `UserAsserted` first, and that was wrong for a second-order
reason worth keeping**: `UserAsserted` is the top of the lattice, so `min(UserAsserted, x) == x` — it
is the identity element of the operation every propagation path is built from, and a double whose
stub is the identity under `min` leaves a run untainted for free. It is now `AgentInferred`, the one
variant `trust_for_channel` returns for **no channel at all**. The method is also **unreachable** —
nothing in `marlowe-loop` calls it — and the comment now says so, because a comment describing tests
that do not exist is instance #16 inside a comment written to avoid instance #16.

### 6.4 · The prescribed diagnostic was retired by this branch, and it retired by going green

CLAUDE.md named `grep -rn "\bingest("` as *"the check that would have caught this earlier"*.
`673bcd2` gave it a second, callerless hit. A reader running the prescribed check now concludes the
daemon ingests; reachability is unchanged. **Instance #18**, logged in CLAUDE.md's ledger, and the
replacement command is in §1.

### 6.5 · `daemon.rs`'s injected-memory push has zero coverage, and it is the only production line the chain runs through

```rust
if !retrieved.is_empty() {
    state.push(Block::new(SourceKind::InjectedMemory, retrieved.text.clone(), retrieved.floor))
}
```

Two mutations, both measured: replacing `retrieved.floor` with `TrustClass::UserAsserted`
(`runs/m3-mutation/finding1-floor-laundered.txt`) and guarding the whole push with `if false &&`
(`finding1b-push-deleted.txt`). Both: `EXIT=0`, 21 `test result` lines, **zero failures across the
whole `marlowe-daemon` crate.** A one-line edit that hands the model untrusted memory stamped
`UserAsserted` — defeating layers 2 and 3 together — is invisible to the entire suite.

It cannot be closed today: `Daemon::turn` constructs its model driver internally with no seam, and
`retrieve` abstains on `NoReranker` with no cross-encoder in the worktree. The probe file
**mirrors** this line rather than executing it and says so at the site. **Sequence: expose the driver
seam, then a daemon-level test that plants a matured belief, drives one real turn, and asserts
`blocks_composed_targets` on the class the pushed block actually carries. Do that before `ingest`
gets a caller.**

---

## 7 · What unblocks this

**`SCOPED-MEMORY.md`, ROADMAP M3 Session D at the earliest.** It is the design that gives a worker a
bank of its own to write into — the missing row in §2.3's table: a run that may be tainted *and* may
write memory, because what it writes is scoped and reaches Marlowe only by instillation, as typed
structure. Its own header lists **Blocks: workers holding `MemoryWrite` (M3 §7)**, and it is marked
*design; no scoping exists in the code today*. Spine-level work, not a session.

**And when a caller does exist, note what stands between an ingested belief and an observable
refusal** — every one of these produces the same reading as a working guard, *"no composed target was
refused"*:

| Gate | Where |
|---|---|
| A six-hour maturation window | `ingest.rs`'s `silent_until`, `MATURATION_WINDOW_MS` in `entry.rs`; no bypass in `DaemonMemory::retrieve` |
| `Abstention::NoReranker` — **a daemon started without `--reranking` auto-injects nothing, ever** | `operating_point.rs` |
| `Abstention::NoRunnerUp` — a profile holding exactly one planted belief can never inject | same |
| Rank-1 and rank-2 both inside `RERANK_BUDGET = 10`, and a margin ≥ 1.165071 at ~10% coverage | same |

Only the first is exercised by anything in the workspace. A real probe is a live one, and it cannot
be a two-turn real-time test. That is a finding about the probe, not a reason to weaken the gates.

---

## 8 · What this session did instead, and why that is the honest maximum

It recorded the finding and did not wire the port. Concretely: this ADR; the three defects in §6.3
fixed; two probe files
(`crates/marlowe-daemon/tests/layer3_refuses_a_composed_target_from_an_ingested_belief.rs`,
`crates/marlowe-daemon/tests/external_ingest_identity.rs`) built to the strongest honest level;
**fourteen mutation runs with a log each** in `runs/m3-mutation/`; and `673bcd2` left standing as a
declared-and-uncalled port with a commit message that says so.

**The alternative was available and every version of it is worse.** Wiring at `engine.rs:2291` is a
small diff — the insertion point is known, `per_source` is `vec![None; fresh.len()]` and the
fail-closed predicate `read_ok` is already the right shape — and it would have produced a session
that looked finished. It would have tainted Marlowe permanently on the first `web` call, under an
origin nobody decided, to make a latch fire that then sits behind four abstention gates.

**A green test named for a property it cannot see is what this project counts instances of.** Writing
down that the property is currently unreachable, and why, is what makes session N+1 not re-derive it
— the same standard `6a1f4f5` applied to its own untestable exclusion: *saying so beats a test named
for a property it cannot see.*

---

## 9 · The six sentences this session is tempted to write, beside the honest ones

The tempting reading is the one the artifacts genuinely support at a glance. That is why both are
written down.

| Tempting | Honest |
|---|---|
| "Layer 3 is now load-bearing" | Layer 3's refusal is exercised end to end against a belief the real `ingest` wrote and the real store held. The step that would put that belief in a window — retrieval, then `daemon.rs`'s push — is **not** exercised, and nothing calls `ingest_external`, so the shipped daemon still cannot enter the state. **The test file was renamed for exactly this reason**; its old name asserted the property its own header denied |
| "`ingest` now has a production caller" | `marlowe_memory::ingest` gained a second non-test caller. `MemoryHost::ingest_external` has none. The count that discriminates is callers of `ingest_external` in a `src/` path: **zero** |
| "The two defects are fixed and mutation-checked" | Correct as behaviour. The mutations were driven from hand-pushed untrusted blocks — a state the product cannot enter. **Evidence about the assembler, not about a fetched page** (§6.1) |
| The probe's mutation table proves non-vacuity | One of its rows reads *"`latch_trust_floor(UntrustedContent)` unconditionally — probe 1 stays GREEN, all three controls RED"*. Probe 1 alone cannot distinguish a working latch from a latch stamped everywhere. **The row means nothing unless it is reported with the controls** |
| "The id collision is fixed" | Fixed for sources distinguishable by `(channel, reference, text)` **within one run**. Two ingests identical in all three collapse to one belief — chosen, documented, and a property of the contract rather than a bug fix. It was also fixed on a path with no caller, so it was never reachable in the product |
| "CLAUDE.md's ordering rule is satisfied" | Its first half is done. Its second half is now established as wrong, so the rule is **superseded, not satisfied** |

---

## 10 · What this ADR does NOT claim

* **It does not claim layer 3 is broken.** It is correct, enforced at one site, and unreachable.
  Those are different words and the difference is the whole ADR.
* **It does not decide the origin.** §4 is a question for the human with three costed options, not a
  recommendation dressed as a finding. Option B is identified as likely and explicitly not taken.
* **It does not close M3-DESIGN §12 item 5.** §4.1 records the narrow half and keeps the rest open.
* **It does not revise the window stamp.** §3.3 records what it is and what it is not, so it cannot
  be cited as precedent for a durable class.
* **It does not claim the condensed summary is safe.** ADR-039 already conceded the channel is
  bounded and non-zero, and M3-DESIGN §2.2 concedes the upward channel is the deliberate hole with a
  human at the end of it. Nothing here narrows either.
* **§6.1's reachability is argued from grep, not measured.** Reachability is exactly the kind of
  claim this project has been wrong about **in both directions**. Measure it before acting on it, and
  measure it on the shipped daemon rather than in a unit test — the `persona_emission.rs` lesson.

---

## Verification

Symbol names rather than line numbers where a line number would be a claim about a path with nothing
checking it (family #14).

| Claim | How established |
|---|---|
| `ingest` had one production caller before `673bcd2`, two after | `grep -rn "\bingest("`, §1 |
| **`ingest_external` has no call site** | `grep -rn "ingest_external(" crates/*/src/` minus the definition — empty |
| Both child `Ports` hardcode `memory: None` | read: `engine.rs:2215`, `engine.rs:2831` |
| The condensed note is stamped `AgentInferred` | read: the `note` closure, `engine.rs:2001-2009` |
| …by four branches through three push sites | read: `engine.rs:2055`, `:2064`, `:2399`. **A test asserting "the condensed note is `AgentInferred`" is green with the reader deleted** |
| `blocks_composed_targets(AgentInferred)` is false | read: `adjudicate.rs` against `common.rs`'s lattice (`UntrustedContent = 0`, `AgentInferred = 1`) |
| `ingest`'s lineage is structurally empty | read: `ingest.rs`, `derivation` is a hardcoded `Vec::new()` |
| `remember`'s lineage is model-supplied belief ids | read: `ollama.rs`, `claim.rs`, `builtin.rs` |
| The id collision overwrote in the derived store | **measured**: `runs/m3-mutation/mut5-id-collision.txt` |
| A re-ingest resurrected a tombstone | **measured this session**: guard disabled → `left: Record, right: Tombstone` |
| The channel spelling is load-bearing | **measured**: `Debug` restored → `external_turn_id_is_pinned_to_the_wire_spelling` alone goes red |
| `daemon.rs`'s injected-memory push has zero coverage | **measured**: `runs/m3-mutation/finding1-floor-laundered.txt`, `finding1b-push-deleted.txt` — both `EXIT=0`, zero failures |
| The refusal is a real adjudication, not a state read | **measured**: `runs/m3-mutation/mut3-no-target-check.txt` — the adjudicator's target-provenance loop deleted, and the test prints the exfiltration command executing |
| The latch is not behaviourally load-bearing in the daemon probe | **measured**: `mut1b.txt` (green with the latch dead and one assertion suspended), `mut1c-loop.txt` (9 red in `marlowe-loop`) |

**§1.1's reachability chain and §5's lineage claim were established by reading and grepping, not by
running anything.** Everything in the table marked *measured* has a log. That distinction is stated
rather than implied, because a table of greps reads like a table of tests.
