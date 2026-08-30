# latch-scope: ADR-023's trust floor latches on the CONVERSATION, not the Run — SECURITY-AUDIT §8's answer is recorded, not re-opened, and it does NOT extend to the egress grant

**Adversary verdict:** sound-with-fixes

**Fatal:** The `CHECKPOINT_VERSION` 1 → 2 bump does not refuse a v1 checkpoint by name — it makes it silently vanish. `JournalCheckpoints::decode_all` (durable.rs:238-248) drops undecodable payloads with `.ok()` by deliberate design (895 legacy `{"step": n}` events), and the version check lives at control.rs:238, downstream of that decode. Adding a required `trust_floor` field to `SessionState` under `deny_unknown_fields` makes every v1 payload fail `from_value`, so it never reaches the version check, never becomes `ResumeError::UnsupportedVersion`, and the daemon reports "staged no checkpoint" instead. The design's named test `a_version_1_checkpoint_is_refused_by_name` asserts an error the code cannot produce, and the obvious way to make it pass is `#[serde(default)]` — the exact fail-open the design exists to prevent.

## Ledger instances the adversary says this re-commits

- #14 (a guarded path outside the guard's search scope) — the proposed `every_writer_of_the_volatile_tier_is_pinned` greps `crates/marlowe-loop/src/**/*.rs`, so it structurally cannot see `crates/marlowe-daemon/src/daemon.rs:2828`'s `state.volatile.retain(...)`, a live removal lever running on every non-resume turn, nor `:2830`'s direct push. The design asserts "today exactly three writers"; there are at least five.
- #15 (an assertion that reads the same either way) — `a_version_1_checkpoint_is_refused_by_name` claims to distinguish refusal from a defaulted restore, but `decode_all`'s `.ok()` filter means the code path under test produces "no checkpoint", not a named refusal. Also the design's claim that the run-level latch absorbs compaction ignores that engine.rs's compaction branch `continue`s at :782, upstream of the latch at :877 — so on that iteration the latch observes nothing and E5's stamp is the only carrier.
- #16 (a declared control nothing reads) — narrowly avoided for `SessionState::trust_floor` (the reader `.min(state.trust_floor())` at engine.rs:877 is named and real), but reintroduced by `replace_volatile`'s doc/code mismatch: the comment declares a rule ("latches over every block that is LEAVING") that no line of code implements — the body mins over the whole old tier including kept blocks.
- #12 (serde routes around a validating constructor) — correctly identified for the new field, but incompletely: `SessionState` already carries `#[serde(deny_unknown_fields)]`, and a hand-written `Deserialize` that does not reproduce it on its inner wire struct silently drops a protection that exists today, with no test in the workspace that would notice.
- #19 (a self-check whose input is the object it checks) — the pinned-writer set is correctly held outside the code being checked, which is the right form; but the set is pinned over the wrong SCOPE, so it can only ever see the subset of writers the grep can reach. Growth of the set outside `marlowe-loop/src` is invisible to it, which is the same blind spot one level out.
- Two definitions of one fact — `SessionState::latch_trust_floor` restates `Run::latch_trust_floor`'s body (run.rs:613-616) verbatim, defended as a deliberate mirror. This is the shape instance #15's closure removed by making `blocks_composed_targets` the single definition; engine.rs:875-876 says so in this repo's own words. It also creates a second field answering "what may this conversation compose", which becomes a live duplicate the moment M3-DESIGN §2.1's permanent-run architecture lands.
- Line-citation drift (instance #14's family aimed at documentation) — every daemon citation is stale at HEAD 186b5d5: `Run::root` is :2609 not :2486; `SessionId::from_name` is :2608 not :2484-2488; `SessionMemory` is :667 not :601; the end-of-turn `sessions.insert` is :2885 not :2762. These were copied from ROADMAP line 860, the row that says in its own text that five of its seven citations had drifted and to re-verify rather than trust them.

## Defects (11)

### FATAL — the `CHECKPOINT_VERSION` 1 → 2 bump does NOT produce a refusal by name; it makes every existing checkpoint SILENTLY DISAPPEAR. `JournalCheckpoints::decode_all` (crates/marlowe-loop/src/durable.rs:238-248) reads `.filter_map(|(_,_,payload)| serde_json::from_value::<Checkpoint>(payload).ok())` — undecodable payloads are dropped, deliberately, because 895 pre-M3 `{"step": n}` events live in the journal. The version check is at crates/marlowe-loop/src/control.rs:238 and runs on ALREADY-DECODED checkpoints. Adding a required `trust_floor` to `SessionState` under `#[serde(deny_unknown_fields)]` makes a v1 payload fail `from_value`, so it never reaches line 238 and never becomes `ResumeError::UnsupportedVersion`.

- **Why:** The design's own test `a_version_1_checkpoint_is_refused_by_name` asserts an error naming `CHECKPOINT_VERSION` and the missing field. No code path can produce that error, so the test is unwritable as specified and the person writing it would either weaken it or (worse) make it pass by adding `#[serde(default)]` — the exact fail-open the design says it is preventing. The shipped behaviour is worse than the test: a run mid-conversation at upgrade time reports "staged no checkpoint" (daemon.rs ~1808) rather than "version 1, this build writes 2". That is a default that makes a mismatch unobservable, ROADMAP line 832's "100% resume from last checkpoint — MET for daemon restart" quietly stops being true, and nothing goes red.
- **Fix:** Decode the version BEFORE the body, and distinguish legacy-no-version from known-version-mismatch. In `decode_all`, first `#[derive(Deserialize)] struct VersionProbe { version: u16 }` via `serde_json::from_value::<VersionProbe>(payload.clone())`: `Err` ⇒ pre-M3 legacy, skip silently (the 895 events, unchanged); `Ok(v)` with `v.version != CHECKPOINT_VERSION` ⇒ carry it forward as a typed refusal rather than a skip, so `control.rs:238` still fires by name; `Ok` and matching ⇒ decode the full `Checkpoint`, and a failure there is now a genuine corruption and must NOT be swallowed. Change `decode_all`'s return type to carry that distinction (`Vec<Result<Checkpoint, ResumeError>>` or a small `enum DecodedCheckpoint { Ok(Checkpoint), Legacy, Unsupported { found: u16 } }`). Mutation that reddens the new test: revert `decode_all` to `.ok()` — a v1 checkpoint then reports "no checkpoint" and the assertion on `ResumeError::UnsupportedVersion` fails.

### "Today exactly three writers of the volatile tier" is FALSE, and the proposed pinning test is structurally incapable of seeing the ones it misses. `crates/marlowe-daemon/src/daemon.rs:2828` runs `state.volatile.retain(|b| b.source != marlowe_loop::SourceKind::Skills)` — a REMOVAL, on every non-resume turn — and `:2830` pushes a `Skills` block straight onto `volatile`, deliberately bypassing `SessionState::push` because `Skills` maps to `Tier::Context`. `crates/marlowe-loop/src/durable.rs:148` reads it. Tests in `marlowe-exec` (`adr023_live.rs:249`) and five `marlowe-loop` test files touch it too. The design's `every_writer_of_the_volatile_tier_is_pinned` greps `crates/marlowe-loop/src/**/*.rs` only.

- **Why:** Instance #14 exactly: a guard whose subject is outside its search path reports nothing and looks like it is working. A test that pins three writers, is green, and cannot see the two live out-of-crate writers is a proxy for the property, not the property. It is also the second-order version of the bug the design is trying to fix — the daemon's `retain` is a removal lever the design's own enumeration says does not exist.
- **Fix:** Two changes. (1) The grep scope becomes `crates/**/src/**/*.rs` — the whole workspace, matching what `crates/marlowe/tests/determinism_guard.rs` already does — and the test moves into `crates/marlowe/tests/` so it is reachable from a `--workspace` run rather than only from `-p marlowe-loop` (CLAUDE.md's per-crate-hides-a-guard rule). (2) Better: make the grep redundant by construction — private `volatile` puts the compiler on it for every module outside `context`, and the daemon's `retain`/`push` must migrate to named doors. Keep the grep anyway, scoped to `crates/marlowe-loop/src/context.rs` alone (the one module privacy does not cover), with the expected set pinned in the test file and a `assert!(!found.is_empty())` control first.

### `replace_volatile`'s doc and its code disagree. The doc says it "latches the floor over every block that is LEAVING"; the body is `self.volatile.iter().map(|b| b.trust).min()` — the min over the ENTIRE old tier, including every block that is kept in `next`. And once the daemon's per-turn `Skills` retain routes through it, that whole-tier min runs on every single turn.

- **Why:** A mechanism whose comment describes a narrower behaviour than the code is how a later session "fixes" it into the narrower behaviour and removes the backstop. It is also a second definition of when the floor moves, competing with the engine's `view.trust_floor()` at engine.rs:877 — and the two answer the same question by different routes.
- **Fix:** Do not build a removal door at all. Latch on ARRIVAL: `SessionState::push` calls `self.latch_trust_floor(block.trust)` before routing to a tier. Then no removal lever — present, future, in-crate or in the daemon — can raise the floor, because the floor was recorded when the block came in and removal is irrelevant to it. This is free: `blocks_composed_targets` is `origin <= TrustClass::UntrustedContent` (adjudicate.rs:50-52), so latching to `AgentInferred` or `AgentObserved` from ordinary History and Skills blocks costs the run nothing that matters. `volatile` still goes private, but now for one narrow reason — so `push` is the only door in — rather than to police a list of removal levers.

### Two definitions of the monotone latch. The design proposes `SessionState::latch_trust_floor` with `if observed < self.trust_floor { ... }` and says it "mirrors `Run::latch_trust_floor` deliberately: same signature, same return contract, so the two cannot drift in meaning." `crates/marlowe-loop/src/run.rs:613-616` already holds that body. Two copies of a rule do not fail to drift because a comment says they must not.

- **Why:** This is the shape instance #15's closure removed: the fix there was making `marlowe_permission::blocks_composed_targets` the SINGLE definition called by both the adjudicator and the loop, precisely because "restating it here as a constant is how the screen and the wall drift apart again" (engine.rs:875-876, in this repo's own words). Proposing a second hand-written latch reintroduces the pattern one file over.
- **Fix:** One definition. Add to `crates/marlowe-loop/src/run.rs`:

```rust
/// The monotone trust latch. ONE definition; `Run` and `SessionState` both hold one of these
/// and neither restates the rule.
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

`Run::latch_trust_floor` becomes `self.trust_floor.latch(observed)`; `SessionState::latch_trust_floor` becomes the same call. No `Default` on `TrustFloor` — `user_asserted()` is the one written-out site, which is the design's own (correct) #17 argument about `TrustClass`.

### Every daemon line citation is wrong, and they were inherited from a ROADMAP row that flags itself as drifted. Verified at HEAD 186b5d5: `Run::root` is built at daemon.rs:2609, not :2486. `SessionId::from_name(session)` for the turn is at :2608, not :2484-2488. `struct SessionMemory` is at :667, not :601. `self.sessions.insert(...)` at end of turn is at :2885, not :2762. The design's `engine.rs` and `run.rs` citations (877, 2600, 3237, 613, 680, 654) all check out; the daemon ones do not.

- **Why:** ROADMAP line 860 says of this exact row: *"Five of the seven citations in this row had drifted... instance #14's family aimed at a roadmap row, so re-verify before citing rather than trusting these."* The design copied the stale numbers instead of re-verifying, in a document whose job is to be built from. A builder following `daemon.rs:2486` lands in the middle of a driver-construction match arm.
- **Fix:** Cite by symbol and re-verify at write time: `Daemon::ask_streaming_with`'s `Run::root` build (daemon.rs:2609), the turn's `session_id` resolution (`resumed.as_ref().map_or_else(|| SessionId::from_name(session), |c| c.session)`, :2608), `struct SessionMemory { state, provenance }` (:667), the end-of-turn `self.sessions.insert` (:2885), the daemon's Skills retain/push (:2828, :2830), the injected-memory push (:2752-2758). Every line number in the entry gets `(verified <date> at <sha>)`.

### The design names one child `SessionState::new` site (engine.rs:2205) and misses the second (engine.rs:2796, the `condense_batch` quarantined-reader path). Both construct a child window and both would need the seed the design proposes.

- **Why:** A carry enforced at one of two construction sites is the "pick the wrong constructor" failure the design itself rejects three alternatives to avoid. Under the design's removal-door mechanism the quarantined reader's child window would start at `UserAsserted` while `Run::child` gave it the parent's floor — the two halves of one child disagreeing, which is the thing the seed exists to prevent.
- **Fix:** Under latch-on-push the seeding is unnecessary at both sites — the child's brief and its untrusted content are `push`ed, so the child's own floor is derived from what it holds and `Run::child` (run.rs:654 `trust_floor: parent.trust_floor`) still carries the parent's. If a seed is kept anyway, it goes in a single `SessionState::for_child(run: &Run, identity: &str, governance: &[GovernanceConstraint])` constructor used by BOTH engine.rs:2205 and engine.rs:2796, so there is no per-site call to forget.

### A fourth reset door, never named: the daemon restart. `Daemon::sessions` is `BTreeMap<String, SessionMemory>` (daemon.rs:777) and `SessionMemory { state, provenance }` (:667) is IN-MEMORY ONLY — it is not persisted anywhere. `ask_streaming_with` does `self.sessions.remove(session).unwrap_or_else(|| SessionMemory { state: SessionState::new(session_id, identity_block()), .. })` (:2670). After a daemon restart, an ordinary next message on the same session name gets a brand-new `SessionState` at `UserAsserted`. The design's checkpoint work covers only the explicit `Request::Resume` path.

- **Why:** The design's headline is "the object that outlives the turn is where a monotonic latch belongs." `SessionState` outlives the turn but not the PROCESS. This is precisely the failure durable.rs's own module header names — *"the restart would have become the trim, with no error, no event, and a green test suite"* — relocated from the run to the conversation, and the design would ship with it unnamed. Nothing here is a security regression today (layer 3 is unreachable), but the entry would record a claim stronger than the mechanism.
- **Fix:** State the scope precisely in the entry: the carried floor survives a turn boundary and an explicit `Request::Resume`; it does NOT survive daemon restart on the ordinary path, because `Daemon::sessions` is not durable. Then either (a) record making conversation state durable as a separate, later decision with its own name, or (b) accept restart-as-reset explicitly and say so, in which case it joins the reset-door question already listed for the human — a restart is a door that RAISES a floor and belongs in the same paragraph as `/reset` and `SessionState::clear()`. Do not leave it implicit.

### The design's vacuity argument is stated without the loop ordering that determines whether it is true. `Engine::run` assembles at engine.rs:736, and the compaction branch `continue`s at :782 — BEFORE the latch at :877. Same for `clear_tool_results`, which `continue`s at :787. So on the iteration compaction fires, `Run::latch_trust_floor` never sees the pre-compaction view at all.

- **Why:** It changes what is load-bearing. The design says "within a run the latch absorbs both levers" (quoting SECURITY-AUDIT §8) and that the session carry is therefore untestable today. But on a first-iteration compaction the run-level latch is NOT a backstop — E5's `min(AgentInferred, floor_of_discarded)` stamp is the ONLY thing carrying the class, inside the run as well as across the boundary. The rejected-alternative-5 claim ("no discriminating probe can be written today") is right for the wrong reason, and a builder reading it would not know which mutation to reach for.
- **Fix:** State the ordering as a fact in the entry, with the line numbers, and add it to the risks: `latch_trust_floor` at :877 is downstream of two `continue`s, so any lever that shortens the window and `continue`s is unobserved by the run latch on that iteration. Under latch-on-push this becomes moot — the floor was recorded at `push`, upstream of every `continue` — which is a second, independent reason to prefer arrival-latching to a removal door.

### Scope: the entry answers a question M3-DESIGN §2.1 has already partly answered, and does not say which architecture it is for. §2.1 (lines 104-110) states that Marlowe IS a permanent run, that his floor is "monotonic and latched per run", that he "can never compose a target again — not for that task, for his life", and that "the liaison pattern is not ergonomics; it is the only shape that survives ADR-023." The design hands "is one poisoned belief permanent for the conversation?" to the human as open, without noting that §2.1 already commits to a stronger version of the same answer for the M3 target architecture.

- **Why:** Two things. (1) The human is being asked to decide something a design document he owns already records, without being told that. (2) If C/D moves Marlowe to one permanent run per conversation, then `SessionState::trust_floor` and `Run::trust_floor` become two fields answering "what may this conversation compose", differing only in an architecture that no longer exists — the project's most-logged shape, created by a decision taken to close a gap that the architecture change closes on its own.
- **Fix:** The entry must open by naming both architectures and saying which it is for: the SHIPPED daemon (a fresh `Run::root` per user message, daemon.rs:2609) versus M3-DESIGN §2.1's target (one permanent run). Record that the session-scoped latch is a fix for the FIRST and is redundant under the SECOND, and that if §2.1's permanent run lands, `SessionState::trust_floor` must be REMOVED in the same commit rather than left as a second definition. Quote §2.1 to the human as prior art on the product consequence, and narrow his question to the one §2.1 does not answer: whether the shipped per-turn architecture should behave like §2.1's before §2.1 arrives.

### `SessionState` already carries `#[serde(deny_unknown_fields)]` (context.rs line above :421) alongside `#[derive(..., Deserialize)]`. The design replaces the derive with a hand-written `Deserialize` and does not say that the unknown-field rejection must be reproduced inside it.

- **Why:** A hand-written deserializer that builds an inner `Wire` struct without `deny_unknown_fields` silently drops a protection that exists today, and no test in the workspace asserts it — the loss is invisible. This is the same shape as the design's own #16 warning, applied to a serde attribute rather than a field.
- **Fix:** The inner wire struct carries `#[serde(deny_unknown_fields)]` explicitly, following the pattern `GovernanceConstraint`'s hand-written `Deserialize` already uses at context.rs:408-417 and `Block`'s at :357. Add `a_session_state_payload_with_an_unknown_field_is_refused` to `crates/marlowe-loop/tests/durable_resume.rs`; mutation that reddens it: drop the attribute from the wire struct.

### Cost understated: privatising `SessionState::volatile` is a cross-crate API break the design does not price. Direct `state.volatile` users outside `context.rs`: `crates/marlowe-daemon/src/daemon.rs:2828, :2830, :2992`; `crates/marlowe-loop/src/durable.rs:148`; and integration tests in `crates/marlowe-loop/tests/{compaction.rs:349,351, shortening_never_raises_the_floor.rs:88,103,137,161,178, spawn_and_budget.rs:443,1149,1165,1964,1973,1978}` plus `crates/marlowe-exec/tests/adr023_live.rs:249` — integration tests are external crates, so a private field breaks all of them. Rust privacy is per-module, so `durable.rs` breaks too even inside `marlowe-loop`.

- **Why:** The design's `guarded_files: []` and "no product change in Session C" framing is right, but the BUILD it specifies is much larger than "one door and a min", and daemon.rs — a file another agent is editing right now — is in it. Under-pricing this is how the cheaper wrong version lands later as ergonomics.
- **Fix:** Price it in the entry: `pub fn volatile(&self) -> &[Block]` covers all read sites (durable.rs:148, daemon.rs:2992, and every test) with a mechanical edit; the two daemon WRITE sites need doors. Under latch-on-push those become `state.push(Block::new(SourceKind::Skills, hits, TrustClass::UserAsserted))` — which requires `SourceKind::Skills` to stop routing to `Tier::Context` in `push`, or a `state.push_volatile(block)` that forces the tier and latches — plus `state.retain_volatile(|b| b.source != SourceKind::Skills)` for the removal, which under arrival-latching does not need to latch anything at all.

## STRENGTHENED — WHAT GETS BUILT

## ADR-0XX — ADR-023's trust floor latches on the CONVERSATION, not the `Run`. SECURITY-AUDIT §8's answer is RECORDED; the mechanism is specified but NOT built in Session C; the egress grant's scope is answered separately.

Verified against HEAD `186b5d5`, 2026-08-30. Every line number below was re-read at that sha; re-verify before citing (ROADMAP line 860 is the standing warning about this row's own citations).

---

### 1. What is decided, and what is not

**Decided (this entry):** `SECURITY-AUDIT.md` §8's answer, dated 2026-08-12, is recorded rather than re-derived: *"Within a run the latch absorbs both; across turns it does not, because `Daemon::ask` builds a fresh `Run::root` at `UserAsserted` over a persisted `SessionState`. The latch belongs on the session, not the Run."* E5's fix line makes it an "and": *"stamp `min(AgentInferred, floor_of(replaced))`, **and** persist the latched floor on the session, not only the Run."* `6a1f4f5` built the first clause (E5 + F1) and not the second. §8 is **half-fixed**, and this entry says so.

**NOT decided here, and explicitly the human's:** whether the second clause is BUILT. See §7.

**Session C's product change: none.** One test lands (§6.1). No `crates/` behaviour moves.

**No §13-guarded file is touched, and that is not why this is safe.** `run.rs`, `context.rs`, `engine.rs`, `durable.rs`, `daemon.rs` are all absent from `PROTECTED` in `.claude/hooks/protect-boundaries.py`, so nothing would prompt. The gate is the standing rule that a settled decision (`ADR-023`: *"monotonic and latched per run"*) is revisited explicitly, plus the product consequence in §7.

### 2. WHICH ARCHITECTURE THIS IS FOR — read this before the mechanism

Two architectures are in play and the entry is worthless without saying which.

- **SHIPPED:** `Daemon::ask_streaming_with` builds a fresh `Run::root` per user message (`daemon.rs:2609`) at `trust_floor: TrustClass::UserAsserted` (`run.rs:680`), over a `SessionState` held in `Daemon::sessions: BTreeMap<String, SessionMemory>` (`daemon.rs:777`, struct at `:667`). N runs per conversation.
- **M3-DESIGN §2.1's TARGET:** *"Layer 3's floor is monotonic and latched per run, and Marlowe is a **permanent** run… a Marlowe who ingests one research finding **can never compose a target again — not for that task, for his life**… the liaison pattern is not ergonomics; it is the only shape that survives ADR-023."* One run per conversation, or per process.

This entry is a fix for the **SHIPPED** architecture. **Under §2.1's architecture it is redundant**, and if the permanent run lands, `SessionState::trust_floor` is REMOVED in the same commit — leaving it would be two fields answering "what may this conversation compose", which is this project's most-logged defect shape.

§2.1 also means the human is not being asked a fresh question: he has already committed, on paper, to a *stronger* version of the same answer for M3's target. §7 narrows what is actually open.

### 3. The mechanism — LATCH ON ARRIVAL, not on removal

The obvious design is a removal door: enumerate the levers that shorten the window and make each propagate `min`. **That is rejected.** A list of levers cannot see itself grow (#19), and the enumeration is already wrong today — `daemon.rs:2828` runs `state.volatile.retain(|b| b.source != marlowe_loop::SourceKind::Skills)` on every non-resume turn, out of crate, and a `crates/marlowe-loop/src/**` grep cannot see it (#14).

**Latch when a block ARRIVES.** Then no removal lever — present, future, in-crate, in the daemon, or in a session nobody has written yet — can raise the floor, because removal is irrelevant to a value recorded at push time. There is no list.

**Over-latching is free, and that is why this works.** `blocks_composed_targets(origin) = origin <= TrustClass::UntrustedContent` (`adjudicate.rs:50-52`), so latching to `AgentInferred` (1) or `AgentObserved` (2) from ordinary `History`, `Skills` and `ToolResults` blocks costs a conversation nothing. Only class `0` changes an outcome.

**One definition of the latch.** In `crates/marlowe-loop/src/run.rs`:

```rust
/// The monotone trust latch. ONE definition. `Run` and `SessionState` each hold one and
/// neither restates the rule — the same reason `blocks_composed_targets` is a single function
/// called by both the adjudicator and the loop (engine.rs:875).
///
/// No `Default`, and `TrustClass` must not gain one: `#[derive(Default)]` on that enum yields
/// `UntrustedContent = 0` (every fresh conversation reads as fully tainted), and `#[default]`
/// on `UserAsserted` is a fail-open reachable from any struct deriving `Default`. Ledger #17 —
/// does this code read the extreme value as a floor or a ceiling — has no good answer, so the
/// value is written out at one site.
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

`Run::latch_trust_floor` (`run.rs:613`) becomes `self.trust_floor.latch(observed)`. Its public signature is unchanged, so `engine.rs:877`, `durable_resume.rs`, `spawn_and_budget.rs` and the daemon's layer-3 probe all keep compiling.

In `crates/marlowe-loop/src/context.rs`:

```rust
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionState {
    pub session: SessionId,
    pub identity: String,
    pub governance: Vec<GovernanceConstraint>,
    pub context_blocks: Vec<Block>,

    /// PRIVATE, for exactly one reason: so `push` is the only way a block enters, and the
    /// arrival latch cannot be bypassed. Not to police removal — removal is irrelevant here.
    volatile: Vec<Block>,

    pub lineage: u32,
    pub compactions: u32,

    /// ADR-023's floor, held on the object that outlives the TURN. Monotonic; never rises.
    /// Private: the only writer is `push`.
    trust_floor: TrustFloor,
}

impl SessionState {
    /// Hand-written, NOT derived — `TrustFloor` has no `Default` on purpose. See its doc.
    fn default() -> Self { /* ..., trust_floor: TrustFloor::user_asserted() */ }

    pub fn volatile(&self) -> &[Block] { &self.volatile }
    pub fn trust_floor(&self) -> TrustClass { self.trust_floor.get() }

    /// THE ONLY DOOR IN, and the only writer of `trust_floor`.
    pub fn push(&mut self, block: Block) {
        self.trust_floor.latch(block.trust);          // <- arrival latch, before routing
        match block.source.tier() {
            Tier::Stable => unreachable!(/* unchanged */),
            Tier::Context => self.context_blocks.push(block),
            Tier::Volatile => self.volatile.push(block),
        }
    }

    /// For `SourceKind::Skills`, which maps to `Tier::Context` but is deliberately carried in
    /// the volatile tier so it is replaced rather than accumulated (daemon.rs:2819-2830's
    /// comment states why). Latches on arrival exactly as `push` does.
    pub fn push_volatile(&mut self, block: Block) {
        self.trust_floor.latch(block.trust);
        self.volatile.push(block);
    }

    /// Removal. Latches NOTHING — deliberately, and the doc says so rather than implying it.
    /// Under arrival-latching a removal cannot raise the floor, so there is nothing to carry.
    pub fn retain_volatile(&mut self, f: impl FnMut(&Block) -> bool) { self.volatile.retain(f); }

    /// Compaction's replacement. Also latches nothing, for the same reason; the incoming
    /// summary block enters through this call's own `latch` on each element of `next`.
    pub fn replace_volatile(&mut self, next: Vec<Block>) {
        for b in &next { self.trust_floor.latch(b.trust); }
        self.volatile = next;
    }
}
```

**Reproduce `deny_unknown_fields` in the hand-written `Deserialize`.** Follow `GovernanceConstraint`'s pattern at `context.rs:408-417` and `Block`'s at `:357`:

```rust
/// `serde` is a way in (#12) and a checkpoint is the caller. A field-wise derive would let a
/// stale or hand-edited checkpoint declare `UserAsserted` over a window whose own blocks are
/// `UntrustedContent` — the turn-boundary hole reopened through the resume path, which is
/// exactly why `Run::restored` exists ("the restart would have become the trim", durable.rs:26).
///
/// The clamp is `min(declared, min over the state's own blocks)`, so a forged floor can only
/// ever be LOWER than claimed. The inner wire struct carries `deny_unknown_fields` because the
/// derive it replaces did, and losing that would be silent.
impl<'de> Deserialize<'de> for SessionState { /* clamped; wire struct deny_unknown_fields */ }
```

**Call-site migration, priced honestly.** Read sites take the accessor mechanically: `durable.rs:148`, `daemon.rs:2992`, and every test (`compaction.rs:349,351`; `shortening_never_raises_the_floor.rs:88,103,137,161,178`; `spawn_and_budget.rs:443,1149,1165,1964,1973,1978`; `marlowe-exec/tests/adr023_live.rs:249`). Rust privacy is per-module, so `durable.rs` needs the accessor even inside `marlowe-loop`. Two daemon WRITE sites move: `daemon.rs:2828` → `state.retain_volatile(|b| b.source != SourceKind::Skills)`, `daemon.rs:2830` → `state.push_volatile(...)`. **`daemon.rs` is in the blast radius and another agent is editing it; this migration is sequenced after that work, not concurrent with it.**

**No change to `crates/marlowe-loop/src/engine.rs:877`.** The run latch stays `run.latch_trust_floor(view.trust_floor())`. The conversation floor is carried by `SessionState` and enters the run through the seed below — not by a second `min` at the latch site, which would be a second place answering "what floor does this run start at".

**The seed, at ONE site.** `Run::root` stays at `TrustClass::UserAsserted` (`run.rs:680`) and gains no parameter — a defaulted or `Option` parameter is the "sensible default that makes a mismatch unobservable" family, and two named constructors move the failure to picking the wrong one. Instead, `Engine::run` seeds once, before its first iteration, from the state it was handed:

```rust
// crates/marlowe-loop/src/engine.rs, before the loop
// The conversation's floor is a lower bound on this run's. `Daemon::ask_streaming_with`
// rebuilds `Run::root` at UserAsserted per user message (daemon.rs:2609); this line is what
// makes that rebuild harmless. There is no caller to get it right.
run.latch_trust_floor(state.trust_floor());
```

**Child windows: both sites, one constructor.** `SessionState::new` is called for a child at `engine.rs:2205` (spawn) and `engine.rs:2796` (`condense_batch`'s quarantined reader). Both route through one `SessionState::for_child(&Run, identity, &[GovernanceConstraint])` so no per-site step can be forgotten. Under arrival-latching the child's own floor derives from its brief and its content; `Run::child` still carries `parent.trust_floor` (`run.rs:654`) unchanged.

**A loop-ordering fact the entry must record**, because it decides which mutation reddens what: `Engine::run` assembles at `engine.rs:736`, and the compaction branch `continue`s at `:782` and `clear_tool_results` at `:787` — both UPSTREAM of the latch at `:877`. So on an iteration where compaction fires, the run latch never observes the pre-compaction view at all, and E5's `min(AgentInferred, floor_of_discarded)` stamp is the sole carrier even *within* the run. Arrival-latching makes this moot: the floor was recorded at `push`, upstream of every `continue`.

### 4. The checkpoint path — and the version bump that must NOT be naive

`Checkpoint` (`durable.rs:87`) already carries the RUN's `trust_floor` (`:135`) and now also carries it inside `state`. Two copies drift, so `Checkpoint::restore` (`:144`) resolves DOWNWARD:

```rust
let floor = self.trust_floor.min(self.state.trust_floor());
// ... Run::restored(..., floor)   // restored's last parameter, run.rs:719
```

**`CHECKPOINT_VERSION` 1 → 2, and the decode path must change WITH it.** `JournalCheckpoints::decode_all` (`durable.rs:238-248`) reads:

```rust
.filter_map(|(_, _, payload)| serde_json::from_value::<Checkpoint>(payload).ok())
```

Undecodable payloads are dropped **on purpose** — the live journal holds 895 pre-M3 `{"step": n}` events — and the version check is at `control.rs:238`, *downstream of that decode*. Adding a required field makes a v1 payload fail `from_value`, so **it never reaches the version check**: the run reports "staged no checkpoint" (`daemon.rs` ~:1808) rather than a named version refusal, and ROADMAP line 832's *"100% resume from last checkpoint — MET for daemon restart"* quietly stops being true with nothing red.

Fix, and it ships in the same commit as the bump:

```rust
#[derive(Deserialize)]
struct VersionProbe { version: u16 }

enum Decoded { Ok(Checkpoint), Legacy, Unsupported { found: u16 } }

// in decode_all, per payload:
//   from_value::<VersionProbe>(payload.clone()) Err  => Decoded::Legacy   (the 895; skip, silent)
//   Ok(v) if v.version != CHECKPOINT_VERSION    => Decoded::Unsupported   (reaches control.rs:238)
//   otherwise decode the full Checkpoint; a failure HERE is corruption and is NOT swallowed.
```

`control.rs`'s `ResumeError::UnsupportedVersion { found, expected }` (`:48-50`) is unchanged and now actually reachable for a v1 payload.

**A fourth reset door, named rather than left implicit.** `Daemon::sessions` is in-memory and not persisted; `ask_streaming_with` constructs a fresh `SessionState` when `sessions.remove` misses (`daemon.rs:2670`). So the carried floor survives a **turn boundary** and an explicit `Request::Resume` — and **does not survive a daemon restart** on the ordinary path. That is the same "restart becomes the trim" failure `durable.rs`'s header names at run scope, relocated to the conversation. It is recorded here, not fixed here, and it joins §7's reset-door question.

### 5. What is NOT claimed

After E5/F1 there is **no demonstrated reachable path** that raises the floor across a turn boundary: injected-memory blocks accumulate in `state.volatile` (`daemon.rs:2752-2758`, no retain), compaction stamps `min` into the summary, and the daemon's only removal (`:2828`) touches `Skills` blocks at `UserAsserted`. The property is currently upheld by three per-lever propagations rather than by a latch — which is the arrangement ADR-023 rejected *within* a run. The conversation latch is the backstop that makes those levers non-load-bearing, and it must exist before Session D gives layer 3 a reachable trigger.

### 6. Tests

**6.1 — the one test Session C lands, with zero product change.**

`crates/marlowe/tests/volatile_tier_writers_are_pinned.rs` (in `marlowe`'s test target, not `marlowe-loop`'s, so a `--workspace` run reaches it and a `-p marlowe-loop` habit cannot hide it — CLAUDE.md's per-crate rule).

Greps **`crates/**/src/**/*.rs`** — the whole workspace, matching `crates/marlowe/tests/determinism_guard.rs`'s scope — for writes to and removals from `SessionState`'s volatile tier, and compares against `EXPECTED_VOLATILE_WRITERS` pinned in the test file. Today that set is **five**, not three: `context.rs` `SessionState::push`, `Assembler::clear_tool_results`, `Assembler::compact`; and `daemon.rs`'s `state.volatile.retain(...)` and `state.volatile.push(...)`. A control asserts the enumeration is **non-empty first**, so a broken regex cannot pass by comparing nothing against nothing. The expected set lives outside the code being checked (#19-resistant).

- *Mutation:* add `pub fn drop_volatile(&mut self) { self.volatile.clear(); }` to `SessionState`. Fails by name, printing the new site.
- *Negative control:* rename an existing writer without adding one — must also fail, proving the pin is on the SET and not on a count.
- *Scope control:* delete `daemon.rs:2828`'s retain. Must fail. **This is the assertion that the old, `marlowe-loop`-scoped version of this test could not make**, and it is why the scope widened.

**6.2 — the build's tests, specified now so a cheaper wrong version cannot land later as ergonomics.**

`crates/marlowe-loop/tests/adr023_across_the_turn_boundary.rs` (new). Three tests, and the second and third are what make the first mean anything.

1. `a_second_run_over_the_same_session_still_refuses_a_composed_target` — turn 1 drives `Engine::run` with run A over `SessionState` S holding an `InjectedMemory` block whose class came from a real `DaemonMemory::ingest_external(Channel::Web, ..)` **called from the test** over a real Journal/Profile (`grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns exactly two definition hits — `daemon/src/memory.rs:542`, `loop/src/driver.rs:573` — and no production caller). Turn 2 builds a FRESH `Run::root` at `UserAsserted` over the SAME S, which is what `daemon.rs:2609` does, and drives a scripted model proposing a composed target. Asserts `Outcome::Blocked { reason: BlockReason::UntrustedTarget { origin } }` and `marlowe_permission::blocks_composed_targets(origin)`. **NEVER asserts on `DegradedPath::TrustFloorLatched` or `EventKind::TrustFloorLatched`** — instance #15: that event fires on every run that has ever run.
   *Mutations:* delete the `run.latch_trust_floor(state.trust_floor())` seed → turn 2 becomes `Allowed`, failing at the OUTCOME, not at a state read. Make `SessionState::push`'s `latch` call a no-op → same red, distinguishing the write from the read.

2. `the_untrusted_block_is_actually_gone_from_the_session_before_turn_two` — between turns, forces the carrier out of S and asserts positively that no block in `state.volatile()` is at or below `UntrustedContent` and zero `SourceKind::InjectedMemory` blocks remain. **Without this, test 1 is a proxy**: injected-memory blocks accumulate in the shipped product, so turn 2's refusal would be produced by block carriage and would read identically. The standing rule — any assertion whose subject is "X was removed" carries an assertion that X was removed.
   *Mutation:* skip the removal step. **This test fails; test 1 stays GREEN.** That divergence is the measurement proving test 1 needs test 2. The file header states that this removal is not reachable in the shipped product, the way `layer3_refuses_a_composed_target_from_an_ingested_belief.rs` does.

3. `a_conversation_that_never_read_anything_untrusted_runs_the_same_call` — identical two-turn shape, no ingest, no injected block; turn 2's composed target is `Allowed` and executes.
   *Mutation:* `state.trust_floor.latch(UntrustedContent)` unconditionally in `push`. **This control goes RED while tests 1 and 2 go GREEN** — the exact `mut6-taint-everything` signature already recorded in the layer-3 probe's header, where the security probe passed *harder* under the mutation and only the controls caught it.

`crates/marlowe-loop/tests/durable_resume.rs` gains three:

4. `a_checkpoint_cannot_declare_a_floor_higher_than_its_own_blocks` — deserialize a `Checkpoint` whose `state.trust_floor` and run-level `trust_floor` are both `UserAsserted` while a block in `state.volatile` is `UntrustedContent`; assert restored `Run::trust_floor()` is `UntrustedContent`. Control: a genuinely clean checkpoint is NOT lowered, so the clamp is not "always return the bottom".
   *Mutations:* replace the hand-written `Deserialize` with a field-wise derive; separately, drop `.min(self.state.trust_floor())` in `restore` — each reddens it, isolating the deserializer from the resolution.

5. `a_version_1_checkpoint_is_refused_by_name_not_skipped` — a serialized v1 payload (with a `version` key, no session-level floor) yields `ResumeError::UnsupportedVersion { found: 1, expected: 2 }` naming both, and a legacy `{"step": n}` payload (no `version` key) is still skipped silently.
   *Mutation:* revert `decode_all` to `.filter_map(... .ok())` → the v1 payload reports "no checkpoint" and this fails. **No other test in the workspace moves**, which is why it exists. Second mutation: add `#[serde(default)]` to the new field → the v1 payload decodes at `UserAsserted`; same red.

6. `a_session_state_payload_with_an_unknown_field_is_refused` — the hand-written `Deserialize` keeps what the derive had.
   *Mutation:* drop `deny_unknown_fields` from the inner wire struct.

### 7. Open — the human's, and narrowed

1. **Whether the second clause is BUILT.** Not the hook — none of these files is in `PROTECTED`. The gate is that ADR-023's recorded wording is *"monotonic and latched per run"*.
2. **The product consequence, with §2.1 as prior art.** M3-DESIGN §2.1 already states, for M3's target architecture, that a tainted Marlowe *"can never compose a target again — not for that task, for his life"* and calls the liaison pattern *"the only shape that survives ADR-023."* So the question is not "is one poisoned belief permanent for the conversation" in the abstract — it is whether the **shipped per-turn** architecture should behave like §2.1's before §2.1 arrives.
3. **Whether a reset door exists, and what authorises it.** Session-scoping creates demand for one (DoS). A door that RAISES a floor is privilege-widening — `steer.rs`'s shape — and if built it belongs in `PROTECTED` and in CLAUDE.md's table in the same commit. There are now **four** de-facto reset points to rule on together: a new conversation, an explicit approval, a `/reset`, and **a daemon restart** (§4), which today resets silently. It must not arrive later as ergonomics (`SessionState::clear()`).
4. **The egress grant's scope, answered SEPARATELY.** ROADMAP *Waiting on the human* item 4 calls the latch and ADR-032 §3.1's per-host grant *"the same session-versus-run question."* They are **opposites**. Widening the LATCH can only ever remove privilege — a conversation floor is by construction ≤ every turn's floor — so its worst failure is a visibly over-refusing conversation. Widening the GRANT adds privilege for longer and its worst failure is silent. They also differ in §13 exposure: the latch touches no `PROTECTED` file; the grant lives in `profile.rs` and `adjudicate.rs`, both guarded, under an ADR that is `Status: PROPOSED` while already built. **One "yes, session-scoped" ruling would quietly do both.**
5. **Whether `crates/marlowe-loop/src/run.rs` joins the boundary hook.** `latch_trust_floor` (now `TrustFloor::latch`) is the whole of layer 3's per-run half and nothing guards the file. Adding a path is monotone in the human's favour and M3-D3 established it needs no escalation — but the CLAUDE.md row and the `EXPECTED_PROTECTED` entry ship in the same commit. Checked: no `run.rs` §13 entry in `SECURITY-AUDIT.md`.
6. **Which session builds it — C, D, or neither until a lever changes.** No reachable path raises the floor across a turn boundary today, so the build has no discriminating probe. The trigger is Session D's `ingest` caller, or §6.1's pinned-writers test going red.

### 8. Rejected

- **Argue against §8; keep the latch on the `Run` — the per-turn reset is DoS resistance.** Strongest counter, and `run.rs`'s own doc already answered it inside a run: *"one poisoned page would pin the window open for the rest of the run, converting a security property into a denial of service."* Reply: the reset must not be **silent and automatic**. A per-turn reset restores composed-target authority with no human act, no event and nothing on screen — the property ADR-023's latch was introduced to remove. DoS argues for a **door** (§7.3), not against the latch.
- **A removal door (`replace_volatile` latching over what leaves).** Rejected for arrival-latching. Its doc and code disagreed (whole tier vs. leaving blocks); the daemon's per-turn `Skills` retain would have routed through it, latching min-over-everything every turn anyway; and it keeps the invariant as a list of levers, which is #19. Arrival-latching has one writer and no list.
- **Answer the latch and the egress grant together.** §7.4.
- **Hold the floor on `SessionMemory` (`daemon.rs:667`) beside `state`, copied at `:2885` and read at `:2609`.** The mirror of what ADR-032 rejected for the grant: *"put the granted set beside the policy on the Run and consult it there, and the invariant is bypassed rather than enforced."* The object holding the blocks is `SessionState`; a floor beside it drifts from it — `Assembler::compact` rotates `state.session` and replaces `state.volatile` without touching a neighbour field. It also puts a security carry in an unguarded, uncontracted daemon field maintained by hand-copies, with an early `return` between read and write.
- **A parameter or `Option<TrustClass>` on `Run::root`, or a second `Run::for_turn`.** A defaulted/optional parameter is the "default that makes a mismatch unobservable" family — `None` reads as a new conversation and the hole returns silently. Two constructors move the failure to picking the wrong one. The seed inside `Engine::run` has no caller to get it right.
- **Mirror `Run::latch_trust_floor` as a second hand-written method on `SessionState`.** Two copies of a rule do not fail to drift because a comment says they must not. `TrustFloor` is the single definition — the same move that closed #15 by making `blocks_composed_targets` single.
- **Build it in Session C.** (1) Revisits ADR-023's stated scope. (2) Its cost is a product question (§7.2). (3) No discriminating probe exists today — a two-turn test that merely re-assembles is green with or without the carry, and building a security mechanism whose only test is vacuous is how #15 happened.
- **Make untrusted blocks untrimmable / pin the window open.** Already rejected verbatim in `run.rs`'s doc; at conversation scope it is strictly worse.

### 9. Contract impact

**For the recording: none.** `CONTRACTS.md` §5's pinned `Run` (line 905) does not list `trust_floor` at all, and §6's `Session` does not either. Writing the entry moves no pinned schema.

**For the build: three deliberate amendments.** (1) §6 gains a sentence — the latched floor is a property of the **conversation chain** and is carried across the turn boundary; §6 is where *"a long conversation is a chain, never an overwritten transcript"* already lives. (2) `CHECKPOINT_VERSION` 1 → 2 is a wire change to a §12 type, plus the `decode_all` change of §4. (3) §5 gains `trust_floor: TrustClass` on `Run`, because a reader of §5 currently cannot see the mechanism ADR-023 turns on.

**Two pre-existing drifts, raised rather than silently repaired** (contracts are pinned; if one is wrong, stop and raise it): §5's `Run` lists `result: Option<ContentRef>`, which the code does not have, and omits `trust_floor`, which it does; §12's `Checkpoint` lists `transcript_ref`, `pending_calls` and `guidance`, none of which exist in `crates/marlowe-loop/src/durable.rs`, while omitting `profile`, `budget`, `spent`, `trust_floor`, `contract_retries` and `state`, all of which do. Neither is caused by this decision and neither is repaired inside it. Separately: `SpawnRequest`'s fields are **not** pinned in `CONTRACTS.md` — §5 pins only `fn spawn(&self, req: SpawnRequest) -> RunId` at line 941; the ROADMAP row claiming otherwise is wrong.

### 10. Risks

- **The probe can be vacuous and read exactly like a working one.** Injected-memory blocks accumulate (`daemon.rs:2752-2758`, no retain), so a two-turn test refuses on turn 2 whether or not any conversation latch exists. Test 6.2.2 is not optional; without it, 6.2.1 measures block carriage and calls it a latch.
- **The mirror risk: the discriminating case is a state the product cannot enter.** Forcing removal in a test is the same green-and-vacuous family the layer-3 file already declares about hand-pushed `InjectedMemory`. Not a reason to skip it — a reason the header must say what it measures.
- **#16 is the likeliest way this ships wrong.** `SessionState::trust_floor` could be added, serialized, checkpointed and asserted on with no reader in the enforcement path. The named readers are the seed at the top of `Engine::run` and `Checkpoint::restore`'s `min`. A grep for readers of the field is the thirty-second check and it is prescribed here.
- **`daemon.rs` is in the blast radius.** The `volatile` privatisation touches `:2828`, `:2830`, `:2992` on a file under concurrent edit. Sequenced, not concurrent.
- **A latent divergence found while reading, NOT filed as a security finding and not in `SECURITY-AUDIT.md` (checked: no `session_id`/rotation entry).** `Assembler::compact` rotates `state.session`; `engine.rs:760` updates `run.session` to match; but the daemon builds each turn's `Run` with `SessionId::from_name(session)` unless resuming (`daemon.rs:2608`). After any compaction the run's session id and the state's disagree, and memory writes and retrieval scope on a session id. Needs verification before it is filed, and it must NOT be bundled here — changing which id a memory write carries can make earlier beliefs unretrievable.
- **"Session" is ambiguous in three ways and the entry says which it means.** `Daemon::sessions` is an in-memory `BTreeMap` keyed by the client's session NAME and is not persisted; `SessionState::session` is a `SessionId` that ROTATES on compaction; `CONTRACTS.md` §6's `Session` is a durable record whose `parent` makes a conversation a chain. **The latch belongs to the CHAIN, and is held on the `SessionState` object rather than keyed on any id** — keying it on `SessionId` would reintroduce the reset at every compaction, which is the per-turn hole in a second place.

---

## Original recommendation

Record `SECURITY-AUDIT.md` §8 as written; do not argue against it. Its answer, dated **2026-08-12**, is: *"Within a run the latch absorbs both; across turns it does not, because `Daemon::ask` builds a fresh `Run::root` at `UserAsserted` over a persisted `SessionState`. **The latch belongs on the session, not the Run.**"* — and E5's fix line spells out that this is an *"and"*: *"stamp `min(AgentInferred, floor_of(replaced))`, **and persist the latched floor on the session, not only the Run** — the object that outlives the turn is where a monotonic latch belongs."* **`6a1f4f5` built the first clause (E5+F1) and not the second**, so §8 is half-fixed, not fixed. Session C's job is the `DECISIONS.md` entry (M3-D5) and nothing in `crates/`: extending the latch's scope revisits a settled decision's stated wording (*"monotonic and latched per run"*) and carries a user-visible product cost (M3-DESIGN §2.1 — one untrusted belief ends composed targets for the whole conversation), which is the human's call and not an agent's. **The entry must also split the question the ROADMAP couples.** ROADMAP *Waiting on the human* item 4 calls the latch and ADR-032 §3.1's per-host egress grant *"the same session-versus-run question"*. They are opposites: widening the latch's scope only ever **removes** privilege and its worst failure is a visibly over-refusing conversation; widening the grant's scope **adds** privilege for longer and its worst failure is silent. One "yes, session-scoped" ruling would quietly do both. And state honestly what is not being claimed: after E5/F1 there is **no demonstrated reachable path** that raises the floor across a turn boundary — every shortening lever now propagates `min` into a block that stays in `SessionState`. The property is currently upheld by three per-lever propagations rather than by a latch, which is exactly the arrangement ADR-023 rejected *within* a run; the session latch is the backstop that makes those levers non-load-bearing, and it must exist before Session D gives layer 3 a reachable trigger.

### Types

```rust
// ─────────────────────────────────────────────────────────────────────────────
// NOTHING BELOW IS BUILT IN SESSION C. This is the shape the DECISIONS entry
// records so the build is not re-designed from scratch, and so a later session
// cannot land a cheaper wrong version as ergonomics.
// NO CHANGE IS PROPOSED TO ANY §13-GUARDED FILE. In particular:
//   - crates/marlowe-loop/src/driver.rs      UNCHANGED (no MemoryHost change)
//   - crates/marlowe-loop/src/profile.rs     UNCHANGED (that is the EGRESS half)
//   - crates/marlowe-permission/src/adjudicate.rs UNCHANGED (read-only: it stays
//     the single enforcement site, via blocks_composed_targets)
//   - crates/marlowe-loop/src/provenance.rs  UNCHANGED (it already reads
//     run.trust_floor() at provenance.rs:90)
// ─────────────────────────────────────────────────────────────────────────────

// ── crates/marlowe-loop/src/context.rs ───────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionState {
    pub session: SessionId,
    pub identity: String,
    pub governance: Vec<GovernanceConstraint>,
    pub context_blocks: Vec<Block>,

    /// **PRIVATE as of this decision, and that is the whole mechanism.**
    ///
    /// Today three sites write this tier (`SessionState::push` at context.rs:458,
    /// `clear_tool_results` at :785, `Assembler::compact` at :904). A future fourth that
    /// removed a block without propagating its class would silently restore privilege at the
    /// next turn boundary, and nothing would report it. A list of levers checked by a test
    /// that iterates the list is ledger instance #19, so the invariant is moved into the type:
    /// the only removal door latches the floor over what leaves.
    volatile: Vec<Block>,

    pub lineage: u32,
    pub compactions: u32,

    /// **ADR-023's latch, held on the object that outlives the turn.** Monotonic; never rises.
    /// Not `pub`: the only writes are `latch_trust_floor` and `replace_volatile`.
    trust_floor: TrustClass,
}

impl SessionState {
    /// Hand-written, NOT derived. `TrustClass` has no `Default` and must not gain one:
    /// `#[derive(Default)]` on that enum yields `UntrustedContent = 0` (every fresh
    /// conversation reads as tainted), and `#[default]` on `UserAsserted` is a fail-open
    /// default reachable from any struct that derives `Default`. Ledger #17's question — does
    /// this code read the extreme value as a floor or a ceiling — has no good answer here, so
    /// the value is written out at one site instead.
    fn default() -> Self { /* ..., trust_floor: TrustClass::UserAsserted */ }

    pub fn volatile(&self) -> &[Block] { &self.volatile }

    pub fn trust_floor(&self) -> TrustClass { self.trust_floor }

    /// Lower the conversation's floor. **Never raises it.** Mirrors `Run::latch_trust_floor`
    /// deliberately: same signature, same return contract, so the two cannot drift in meaning.
    pub fn latch_trust_floor(&mut self, observed: TrustClass) -> Option<TrustClass> {
        if observed < self.trust_floor { self.trust_floor = observed; Some(observed) } else { None }
    }

    /// The ONE door that removes blocks from the volatile tier. Latches the floor over every
    /// block that is leaving, before it leaves.
    ///
    /// `Assembler::compact`'s `state.volatile = next` (context.rs:904) becomes a call to this.
    /// A caller that forgets to propagate a class cannot exist, because the propagation is not
    /// the caller's to perform.
    pub fn replace_volatile(&mut self, next: Vec<Block>) {
        let leaving = self.volatile.iter().map(|b| b.trust).min();
        if let Some(f) = leaving { self.latch_trust_floor(f); }
        self.volatile = next;
    }
}

/// **`serde` is a way in (ledger #12), and a checkpoint is the caller.** A field-wise
/// `Deserialize` would let a hand-edited or stale checkpoint declare `UserAsserted` over a
/// window whose own blocks are `UntrustedContent` — the turn-boundary hole reopened through
/// the resume path, which is exactly why `Run::restored` exists.
///
/// The clamp is `min(declared, min over the state's own blocks)`, so a forged floor can only
/// ever be LOWER than claimed. Disagreement fails closed.
impl<'de> Deserialize<'de> for SessionState { /* clamped; never field-wise */ }

// ── crates/marlowe-loop/src/engine.rs — the single latch site (today line 877) ─

// BEFORE
//   if let Some(floor) = run.latch_trust_floor(view.trust_floor()) { ... }
// AFTER
//   The floor is the worst of what THIS window shows and what this CONVERSATION has ever
//   shown. The second term is the entire turn-boundary property: `Daemon::ask_streaming_with`
//   rebuilds `Run::root` at `UserAsserted` per user message (daemon.rs:2486, run.rs:680), and
//   this `min` is what makes that rebuild harmless. The run's floor is still what the
//   adjudicator reads, so nothing downstream changes.
let observed = view.trust_floor().min(state.trust_floor());
state.latch_trust_floor(observed);
if let Some(floor) = run.latch_trust_floor(observed) { /* unchanged emit, still gated on
                                                          blocks_composed_targets */ }

// ── crates/marlowe-loop/src/engine.rs:2205 — the child's state ────────────────
// A child gets a fresh SessionState at UserAsserted while `Run::child` gives it the parent's
// floor. Seed the child's state from the child's RUN so the two halves of a child cannot
// disagree. No new constructor: the existing monotonic method is the door.
let mut child_state = SessionState::new(child_run.session, state.identity.clone());
child_state.latch_trust_floor(child_run.trust_floor());

// ── crates/marlowe-loop/src/durable.rs ───────────────────────────────────────
// `Checkpoint` already carries `trust_floor` (the RUN's, durable.rs:135) and now also carries
// it inside `state`. Two copies is the shape that drifts, so `restore` resolves DOWNWARD:
pub const CHECKPOINT_VERSION: u16 = 2;   // was 1. A v1 checkpoint is REFUSED BY NAME, not
                                         // defaulted: `#[serde(default)]` on the new field
                                         // would be a sensible default that makes the
                                         // mismatch unobservable.
// in Checkpoint::restore:
let floor = self.trust_floor.min(self.state.trust_floor());
// ...Run::restored(..., floor)

// ── UNCHANGED, and named so a build does not "tidy" them ─────────────────────
// Run::root stays at TrustClass::UserAsserted (run.rs:680). No new Run constructor, no
// Option<TrustClass> parameter, no daemon-side field copy: the carry is enforced in the loop
// where it cannot be forgotten by a caller, not at a construction site where it can.
// crates/marlowe-daemon/src/daemon.rs requires NO EDIT for this decision.
```

### Enforcement sites

- `SessionState::trust_floor (the carried floor)` -> **crates/marlowe-loop/src/engine.rs, Engine::run's per-iteration latch block (today line 877) — `view.trust_floor().min(state.trust_floor())`** | breaks: Turn 2 of a conversation that read untrusted content in turn 1 starts at UserAsserted and composes targets again. adr023_across_the_turn_boundary.rs's second turn goes from Blocked to Allowed. This is the ONLY read; without it the field is ledger instance #16 and a test asserting `state.trust_floor() == UntrustedContent` would be green on a build where the control does nothing.
- `SessionState::latch_trust_floor (monotonic writer)` -> **called from the same engine.rs latch block, and from SessionState::replace_volatile (crates/marlowe-loop/src/context.rs)** | breaks: The floor is never recorded on the object that survives the turn; identical failure to the above. Making it raise as well as lower (dropping the `observed < self.trust_floor` guard) lets a clean turn 3 wash out a tainted turn 1 — the trim hole, relocated to the turn boundary.
- `SessionState::replace_volatile (the one removal door) and the privatisation of `volatile`` -> **crates/marlowe-loop/src/context.rs, Assembler::compact (the `state.volatile = next` at line 904 becomes this call); enforced by the compiler for every future writer** | breaks: Compaction drops the block carrying UntrustedContent and latches nothing, so the class survives only as long as E5's `min` on the summary text block. Leaving `volatile` public keeps the invariant as a list of levers, which is ledger #19: a fourth lever can be added and nothing goes red.
- `Run::trust_floor (existing; the enforcement copy)` -> **crates/marlowe-loop/src/provenance.rs:90 `Provenance::taint_for` — `view.trust_floor().min(latched)`; crates/marlowe-loop/src/engine.rs:2600 `blocks_composed_targets(run.trust_floor()) && composes_spawn_targets(&req)`; and via TaintSet into crates/marlowe-permission/src/adjudicate.rs:309 `blocks_composed_targets(origin)`** | breaks: Existing coverage: marlowe-loop mut1c reddened 9 tests across injection_attempts.rs and spawn_and_batch. Unchanged by this decision — named so a build does not relocate enforcement to the session copy and leave two definitions of what a run may compose.
- `Checkpoint::restore's downward resolution `self.trust_floor.min(self.state.trust_floor())`` -> **crates/marlowe-loop/src/durable.rs, Checkpoint::restore, feeding Run::restored's trust_floor argument** | breaks: The two copies of the floor in one checkpoint can disagree, and the disagreement resolves in whichever direction the code happens to pick. With the min, a drift can only cost privilege; without it, a resume is a second turn boundary with the same hole.
- `CHECKPOINT_VERSION = 2 and the by-name refusal of v1` -> **crates/marlowe-loop/src/durable.rs decode path (the version check that must accompany the bump)** | breaks: A v1 checkpoint deserialized with `#[serde(default)]` on the new field restores a latched conversation at UserAsserted — a silent fail-open on the one path the project already fixed once (Run::restored's own doc: "a restart would have become the trim").

### Rejected

- **Argue against §8 and keep the latch on the Run — the per-turn reset is denial-of-service resistance, so one hostile page cannot brick a conversation.** - This is the strongest counter-argument and it is the same one run.rs already answered inside a run: "making untrusted blocks untrimmable was the alternative and is worse... converting a security property into a denial of service." The reply is that the reset must not be SILENT and AUTOMATIC. A per-turn reset restores composed-target authority with no human act, no event, and nothing on screen — precisely the property ADR-023's latch was introduced to remove. If recovery is wanted, it is an explicit door (a new conversation, or an approval), which is a privilege-widening path and therefore a separate, guarded decision. The DoS concern argues for a door, not against the latch.
- **Answer the latch and ADR-032 §3.1's per-host egress grant together, as ROADMAP item 4 frames them ("the same session-versus-run question").** - Opposite monotonicity. Widening the LATCH's scope can only ever remove privilege — a session floor is by construction <= every turn's floor — so its worst failure is a conversation that visibly over-refuses. Widening the GRANT's scope adds privilege for longer, and its worst failure is a host that stays reachable after the human stopped watching, which is silent. One ruling would do both. They also differ in §13 exposure: the latch's implementation touches no PROTECTED file, while the grant lives in profile.rs and adjudicate.rs, both guarded, under an ADR that is still Status: PROPOSED while already built.
- **Hold the carried floor on the daemon's `SessionMemory` (daemon.rs:601) beside `state` and `provenance`, copied from `run.trust_floor()` at the end-of-turn insert (daemon.rs:2762) and read at the `Run::root` build (daemon.rs:2486).** - It is the shape ADR-032's own reasoning rejected for the egress grant, in the mirror direction: "put the granted set beside the policy on the Run and consult it there, and the invariant is bypassed rather than enforced." Here the object that HOLDS the untrusted blocks is SessionState; a floor held beside it drifts from it — `Assembler::compact` rotates `state.session` and replaces `state.volatile` without touching a neighbour field. It also puts a security carry in an unguarded, uncontracted daemon field maintained by a hand-copy at each site, on a file another agent is editing, with an early `return` (daemon.rs:1802) between the read and the write.
- **Add the carried floor as a parameter or `Option<TrustClass>` on `Run::root`, or add a second constructor `Run::for_turn`, so the daemon passes the session's floor at construction.** - A defaulted or optional parameter is the "default that makes a mismatch unobservable" family that has produced four bugs here — `None` reads as a new conversation and the hole returns silently. Two named constructors move the failure to picking the wrong one at a single call site, with the same silence. Enforcing the carry inside the loop's existing latch line makes it impossible to forget: there is no caller to get it right.
- **Build the session-scoped latch in Session C rather than only recording it.** - Three reasons and the third is decisive. (1) It revisits ADR-023's stated scope ("monotonic and latched per run"), and DECISIONS entries are settled. (2) Its cost is user-visible and is a product question, not a technical one: M3-DESIGN §2.1 — one ingested belief ends composed targets for the rest of the conversation. (3) No discriminating probe can be written today: after 6a1f4f5 every shortening lever propagates `min` into a block that stays in SessionState, so a two-turn test that merely re-assembles is green with or without the carry. Building a security mechanism whose only test is vacuous is how instance #15 happened.
- **Make the untrusted blocks untrimmable / pin the window open so the class can never leave.** - Already rejected in run.rs's own doc comment on `trust_floor`, verbatim: "one poisoned page would pin the window open for the rest of the run, converting a security property into a denial of service." Re-proposing it at session scope makes it strictly worse — the window would be pinned for the conversation.

### Tests

- `every_writer_of_the_volatile_tier_is_pinned` in `crates/marlowe-loop/tests/shortening_never_raises_the_floor.rs`
  - asserts: Greps crates/marlowe-loop/src/**/*.rs for assignments to and mutations of `SessionState::volatile`, and compares the found set against `EXPECTED_VOLATILE_WRITERS` pinned in the test file — today exactly three: context.rs `SessionState::push`, `Assembler::clear_tool_results`, `Assembler::compact`. A control asserts the enumeration is non-empty FIRST, so a broken regex cannot pass by comparing nothing against nothing (the M3-D3 lesson). The expected set lives outside the code being checked, which is what makes it #19-resistant. THIS IS THE ONE TEST SESSION C CAN LAND WITH ZERO PRODUCT CHANGE, and it is what makes 'record now, build later' safe: it fails when a new lever appears, which is the event that would make the unbuilt latch load-bearing.
  - red on: Add `pub fn drop_volatile(&mut self) { self.volatile.clear(); }` to `SessionState` in crates/marlowe-loop/src/context.rs. The test fails by name, printing the new site. Negative control: renaming an existing writer without adding one must also fail, proving the pin is on the set and not on a count.
- `a_second_run_over_the_same_session_still_refuses_a_composed_target` in `crates/marlowe-loop/tests/adr023_across_the_turn_boundary.rs (new)`
  - asserts: Reproduces the daemon's turn boundary at loop level, which needs no model-driver seam: turn 1 drives `Engine::run` with run A over `SessionState` S, where S holds an `InjectedMemory` block whose class came from a REAL `DaemonMemory::ingest_external(Channel::Web, ..)` over a real Journal/Profile (a test caller — `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns exactly two definition hits). Turn 2 constructs a FRESH `Run::root` at `UserAsserted` over the SAME S — byte-for-byte what daemon.rs:2486 does — and drives a scripted model proposing a composed target. Asserts `Outcome::Blocked { reason: BlockReason::UntrustedTarget { origin } }` and `marlowe_permission::blocks_composed_targets(origin)`. NEVER asserts on `DegradedPath::TrustFloorLatched` or `EventKind::TrustFloorLatched`: instance #15 — that event fires on every run that has ever run, because the stable tier's Identity block moves the floor on the first assemble.
  - red on: Delete `.min(state.trust_floor())` from the engine.rs latch site (today line 877). Turn 2 becomes `Allowed` and the test fails at the outcome, not at a state read. Second mutation: make `SessionState::latch_trust_floor` a no-op returning `None` — same red, which distinguishes the read from the write.
- `the_untrusted_block_is_actually_gone_from_the_session_before_turn_two` in `crates/marlowe-loop/tests/adr023_across_the_turn_boundary.rs (new)`
  - asserts: Between the two turns, forces the carrier out of S (compaction, or an explicit removal the test performs and DECLARES it performs) and then asserts positively that no block in `state.volatile()` is at or below `TrustClass::UntrustedContent` and that zero `SourceKind::InjectedMemory` blocks remain. Without this, the previous test is a proxy: after E5/F1 every shortening lever leaves a `min`-carrying block behind, so turn 2's refusal would be produced by block carriage rather than by the latch and would read identically. This is the standing rule that any assertion whose subject is 'X was removed' carries an assertion that X was removed — the same control `adr023_live.rs` needed. The test header must state that this removal is currently NOT reachable in the shipped product, so the pair is honest about what it measures.
  - red on: Skip the removal step (leave the InjectedMemory block in S). This test fails by name; the previous test stays GREEN, which is the measurement proving the previous test needs this one.
- `the_control_a_conversation_that_never_read_anything_untrusted_runs_the_same_call` in `crates/marlowe-loop/tests/adr023_across_the_turn_boundary.rs (new)`
  - asserts: Identical two-turn shape with no ingest and no injected block; turn 2's composed target is `Allowed` and executes. Without it the probe above cannot distinguish a working latch from a build that stamps the bottom of the lattice everywhere — the mut6 row in layer3_refuses_a_composed_target_from_an_ingested_belief.rs, where the security probe passed HARDER under the mutation and only the controls caught it.
  - red on: `state.latch_trust_floor(TrustClass::UntrustedContent)` unconditionally at the engine latch site. This control goes red while the two probes above go green — the exact mut6 signature.
- `a_checkpoint_cannot_declare_a_floor_higher_than_its_own_blocks` in `crates/marlowe-loop/tests/durable_resume.rs`
  - asserts: Deserializes a `Checkpoint` whose `state.trust_floor` is `UserAsserted` while a block in `state.volatile` is `UntrustedContent`, and whose run-level `trust_floor` is `UserAsserted`. Asserts the restored `Run::trust_floor()` is `UntrustedContent`. This is ledger #12 applied to the new field: the validating constructor must be the only way in, and serde is a way in. A control deserializes a genuinely clean checkpoint and asserts the floor is NOT lowered, so the clamp is not just 'always return the bottom'.
  - red on: Replace the hand-written `Deserialize for SessionState` with `#[derive(Deserialize)]` (field-wise). The forged floor survives and the restored run composes targets; the test fails at the restored floor. Second mutation: drop the `.min(self.state.trust_floor())` in `Checkpoint::restore` — same red, isolating the resolution from the deserializer.
- `a_version_1_checkpoint_is_refused_by_name` in `crates/marlowe-loop/tests/durable_resume.rs`
  - asserts: A serialized v1 checkpoint (no session-level floor) is rejected with an error naming CHECKPOINT_VERSION and the missing field, rather than restored with a default. Prefer a load-time error to a sensible default: the default here would be `UserAsserted`, which is fail-open on the one path Run::restored's own doc calls out — 'a restart would have become the trim'.
  - red on: Add `#[serde(default)]` to `SessionState::trust_floor`. The v1 checkpoint decodes silently at `UserAsserted` and this test fails; note that NO OTHER TEST in the workspace would move, which is why this one exists.

### Contract impact

**For the recording — which is all Session C should do — none.** `CONTRACTS.md` §5's pinned `Run` does not list `trust_floor` at all (the code's field is private and was added under ADR-023 without a §5 amendment), and §6's `Session` does not either. So writing the DECISIONS entry moves no pinned schema. **For the build, exactly three amendments, and each must be a deliberate act rather than a side effect.** (1) §12 gains the session-level floor: either as a field on the `Checkpoint` entry or, better, a sentence in §6 saying the latched floor is a property of the conversation and is carried across the turn boundary — §6 is where "a long conversation is a chain, never an overwritten transcript" already lives, and the floor is a property of the chain. (2) `CHECKPOINT_VERSION` 1 → 2 is a wire change to a §12 type and is named in the entry. (3) §5 should gain `trust_floor: TrustClass` on `Run`, because it is missing today and a reader of §5 cannot see the mechanism ADR-023 turns on. **Two pre-existing drifts found while checking this, raised rather than silently fixed** (contracts are pinned; if one is wrong, stop and raise it): §5's `Run` lists `result: Option<ContentRef>`, which the code does not have, and omits `trust_floor`, which it does; and §12's `Checkpoint` lists `transcript_ref`, `pending_calls` and `guidance`, none of which exist in `crates/marlowe-loop/src/durable.rs`, while omitting `profile`, `budget`, `spent`, `trust_floor`, `contract_retries` and `state`, all of which do. Neither drift is caused by this decision and neither should be repaired inside it.

### Guarded

[]

### For the human

['**Accepting the scope change itself.** ADR-023\'s recorded wording is *"monotonic and latched per run"*; SECURITY-AUDIT §8 says the object should be the conversation. Recording §8\'s answer is the ROADMAP\'s own instruction and is safe. CHANGING THE LATCH\'S SCOPE IN CODE IS NOT, and the reason is NOT the hook: `run.rs`, `context.rs`, `engine.rs`, `durable.rs` and `daemon.rs` are all outside `PROTECTED`, so nothing would prompt. The gate is the standing rule that a settled decision is revisited explicitly, plus the product consequence below.', '**The product consequence, which is a human\'s judgement and has no technical answer.** M3-DESIGN §2.1: a session-scoped latch means that once a conversation holds one untrusted belief, Marlowe cannot compose a target for the rest of that conversation — no file write, no recipient, no path. Today this costs nothing observable (layer 3 is unreachable; `web` results no longer taint a parent). The moment Session D wires `ingest`, it becomes the product\'s felt behaviour. "Is one poisoned belief permanent for the conversation?" is the question being answered, and it is Matthew\'s.', "**Whether a reset door exists at all, and what authorises it.** Session-scoping creates demand for one (the DoS argument above). A door that RAISES a floor is a privilege-widening path — the same shape `steer.rs` is guarded for — and if it is ever built it belongs in `PROTECTED` and in CLAUDE.md's table in the same commit. It must not arrive later as ergonomics (`SessionState::clear()`, a `/reset` that quietly rebuilds state). Naming it now is what stops that.", "**The egress grant's scope, answered SEPARATELY.** ADR-032 §3.1's grant expiring with the `Run` means the human is re-asked about an already-approved host on his next message. That is the privilege-INCREASING direction, it touches `crates/marlowe-loop/src/profile.rs` and `crates/marlowe-permission/src/adjudicate.rs` (both §13-guarded), and ADR-032 is `Status: PROPOSED` while already built — the only unaccepted-and-shipped ADR in the set. It should not inherit this entry's answer.", "**Whether `crates/marlowe-loop/src/run.rs` joins the boundary hook.** `Run::latch_trust_floor`'s monotonicity is the whole of layer 3's per-run half and nothing guards the file. Adding a path is monotone in the human's favour and M3-D3 established it needs no escalation — but it needs its CLAUDE.md row and its `EXPECTED_PROTECTED` entry in the same commit, and it is an addition to the §13 surface, so it is recorded here as the human's rather than taken. It is not in SECURITY-AUDIT.md (checked: no `run.rs` §13 entry, no `protect-boundaries` mention).", "**Which session builds the carry — C, D, or neither until a lever changes.** The honest state is that no reachable path currently raises the floor across a turn boundary, so the build has no discriminating probe today. The trigger to build is either Session D's `ingest` caller or the pinned-writers test above going red."]

### Risks

["**The probe can be vacuous and read exactly like a working one — instance #15's shape at the turn boundary.** After 6a1f4f5 the class is carried by blocks that stay in `SessionState`, so a two-turn test that merely re-assembles refuses the composed target on turn 2 WHETHER OR NOT any session-level latch exists. The discriminating case requires the carrier to be gone from `SessionState`, and no shipped lever does that. Any future 'the latch survives the turn boundary' test without the removal control is measuring block carriage and calling it a latch.", "**The mirror risk: the discriminating case is a state the product cannot enter.** Forcing the removal in a test is the same green-and-vacuous family the layer-3 file already declares about hand-pushed `InjectedMemory` blocks. This is not a reason to skip the test; it is a reason the test's header must say what it measures, as `layer3_refuses_a_composed_target_from_an_ingested_belief.rs` does.", "**Instance #16 is the likeliest way this ships wrong.** `SessionState::trust_floor` is a field that could be added, serialized, checkpointed, and asserted on (`assert_eq!(state.trust_floor(), UntrustedContent)`) with NO reader in the enforcement path — green on a build where the control does nothing, exactly like `inline_threshold_bytes`. The single named reader is the `.min(state.trust_floor())` at engine.rs's latch site, and a grep for readers of the field is the thirty-second check.", "**Instance #17, in the one place it fits here.** Do not express 'no taint yet' as a numeric or derived zero. `TrustClass::UntrustedContent = 0` is the BOTTOM; a `#[derive(Default)]` on `TrustClass` — which a struct-level `Default` would silently pull in — makes every fresh conversation read as fully tainted, and the fix that looks obvious (`#[default]` on `UserAsserted`) is fail-open in the serde path. Hand-write `Default for SessionState`.", '**Instance #19, which is why `volatile` goes private.** The alternative design — a list of shortening levers, each independently propagating `min`, checked by a test that enumerates the levers — cannot see the list grow or shrink. `crates/marlowe-loop/tests/shortening_never_raises_the_floor.rs` is that list today. The type-level door plus a pinned-writers set with a non-empty control is the form that survives.', "**Instance #12 on the resume path.** `SessionState` derives `Deserialize`. A checkpoint is outside input, and it is the one place a floor can be declared rather than derived. Without the clamp, a resume becomes a second turn boundary with the identical hole — the failure `Run::restored`'s own doc already names ('a restart would have become the trim').", "**Two copies of the floor in one `Checkpoint`.** The run's (durable.rs:135) and the state's. They can disagree. Resolving downward in `restore` makes a drift cost privilege rather than grant it; resolving any other way, or not resolving at all, is a silent fail-open.", "**A latent divergence found while reading, NOT filed as a security finding and NOT in SECURITY-AUDIT.md (checked).** `Assembler::compact` rotates `state.session = child` (context.rs:904 area), while the daemon builds each turn's `Run` with `SessionId::from_name(session)` (daemon.rs:2484-2488). After any compaction the `Run`'s session id and the `SessionState`'s session id disagree, and memory writes and retrieval scope on a session id. Whether that is a bug depends on which id each side uses; it needs verification before it is filed, and it must NOT be bundled into this decision — changing which id a memory write carries can make earlier beliefs unretrievable.", "**The scope of 'session' is ambiguous in three ways and the entry must say which one it means.** `Daemon::sessions` is an in-memory `BTreeMap` keyed by the client's session NAME (not persisted); `SessionState::session` is a `SessionId` that ROTATES on every compaction; `CONTRACTS.md` §6's `Session` is a durable record whose `parent` field makes a conversation a chain. The latch belongs to the CHAIN. A design that keys the floor on `SessionId` reintroduces the hole at every compaction, because the key rotates — which is precisely the per-turn reset in a second place."]
