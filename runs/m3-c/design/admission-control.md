# admission-control: Admission control refuses; it does not queue — and `RunStatus::Queued` does not move, because the queue has no producer in a serial loop

**Adversary verdict:** sound-with-fixes

**Fatal:** The gate cannot refuse in the shipped product and cannot be recorded when it does. `/api/ps` only lists RESIDENT models, so the one branch that refuses — `needs = size_bytes` when `resident == false` — reads a field its named producer cannot supply; in production it is `0`, `needs + headroom > free` collapses to `headroom > free`, and the model's footprint never enters the decision. The design's test hides this by hand-building a non-resident `Residency` carrying a `size_bytes` obtainable only from `/api/ps` while resident. Compounding it: no production `CapacityHost` impl is named and the crate graph forbids both obvious homes (`marlowe-provider` cannot see `marlowe_memory::…::vram::free_bytes`; `marlowe-loop` can see neither), so the daemon would build `Ports { capacity: None }` and every verdict would be `Unmeasured`; and `Engine::spawn_refused` (engine.rs:3112) appends nothing to the journal, so `refused_no_room` and `refused_cpu_split` are unreachable on the `RunSpawned` row the design says carries them — the egress-style measurement the design leans on is impossible for the exact branch it exists to create.

## Ledger instances the adversary says this re-commits

- #16 — `Admission`'s eight numeric fields (`marginal_bytes`, `needs_bytes`, `free_bytes`, `headroom_bytes`, `on_device_bytes`, `size_bytes`, `gpu_permille`, `why`) have no production reader: `explain()` is a `String::new()` stub and `tag()` discards all of them.
- #16 — the enforcement row for `Residency::model` names `roster.rs :: RosterRecorder::append` as a reader; that arm reads only `payload["child"]` and `payload["depth"]` (roster.rs:95–105).
- #16 — `Admission::admitted()` is defined with no named call site; `Engine::spawn` is said to branch on `Refuse | RefuseSplit` directly.
- #16 — `CallLimits::route` gives `CapabilityProfile::model_route()` a reader at the type level only: `Routing::uniform` is the sole production constructor (verified: `Routing::new` has zero non-test callers), so `model_for(Worker)` and `model_for(Orchestrator)` return the same tag and no product behaviour changes.
- #15 — `a_spawn_that_does_not_fit_is_refused…` passes on a build whose gate never refuses, because the test double supplies a `size_bytes` for a non-resident model that `/api/ps` cannot produce.
- #15 — the `--status` capacity line (`1053 MiB free · resident 1000‰ …`) reads identically whether `admit` ever refuses anything; the design admits "there is no mutation for a printed number" and still lists it as the acceptance command.
- #15 — `a_quarantined_read_is_never_refused_for_capacity` reads identically on a build with no capacity code at all; its only stated mutation ADDS the coupling it forbids.
- #17 (producer side, not constructor side) — a non-resident model's `size_bytes: 0` is read as "costs nothing" and therefore as permissive, where it means "footprint unknown". `Headroom::new(0)` closes the constructor half and leaves this half open, while the design claims both directions are asserted.
- #19 — `EVERY_WORD.len() == 8` derived from the `RunStatus` variant list is a self-check whose input is the object it checks; and the `state_of` test enumerates only `RunStatus` keys while the wire alphabet also carries `cancelling`, `interrupted`, `adopted`, `detached`, `terminated`, `no_checkpoint`.
- #12 — `Residency` is a pub-field struct with no validating constructor: `size_vram_bytes > size_bytes` is constructible, so `gpu_permille() > 1000` and `fully_on_device()` is a false negative on nonsense input.
- #14/#18 family, aimed at citations — `RunSummary` is at `daemon.rs:302` not `control_plane.rs`; `vram.rs` is at `crates/marlowe-memory/src/cue/dense/vram.rs`, unreachable from both crates the design places code in; the `--status` count lives at `protocol.rs:400` and `agent.rs:648`, neither cited.
- Two-definitions shape (the project's most-logged, and the reason `blocks_composed_targets` and `io_concurrency()` exist) — a third reader of `/api/ps` beside `hybrid.rs:313` and `vram.rs`'s `Reserve::read`; a second "bytes that must be left alone" beside `ReserveReading`, with its `reason` string dropped; a second wire-word derivation beside `roster.rs:71`.

## Defects (11)

### THE REFUSAL BRANCH HAS NO PRODUCER FOR THE FIELD IT DECIDES ON. `Residency` is documented as `GET /api/ps` for `size`/`size_vram`. `/api/ps` lists ONLY resident models (verified: `crates/marlowe-provider/src/hybrid.rs:297` — "`GET /api/ps` lists resident models"; :315 iterates `ps["models"]`). So when `resident == false` there is no row and `size_bytes` cannot come from the named instrument. `admit`'s only real refusal is `needs = size_bytes` on exactly that branch. In production `size_bytes` would be `0`, `needs = 0`, and the comparison degenerates to `headroom > free` — the model's size never enters the decision. The test hides this by hand-building `{resident:false, size_bytes: 3_271_515_176}`, a number obtainable only from `/api/ps` WHILE RESIDENT, i.e. this session's own measurement fed back through a double.

- **Why:** This is instance #15 with the numbers reversed: the test double supplies a value the production producer structurally cannot, so `a_spawn_that_does_not_fit_is_refused` is green on a build whose gate admits everything. It is also instance #17's shape at the producer rather than the constructor — a `0` that means "unknown footprint" is read as "costs nothing" and therefore as permissive. The design explicitly claims it closed #17 in both directions; it closed it at `Headroom::new` and left it open at `Residency`.
- **Fix:** Make the size carry its source and refuse to guess. `pub enum SizeSource { ApiPsResident(u64), OllamaListOnDisk(u64) }`; `Residency::size()` returns the enum, `admit` matches on it and names it in the refusal text and the journal row. `OllamaListOnDisk` is a KNOWN understatement (`crates/marlowe-memory/src/cue/dense/vram.rs`, Reserve's doc: `marlowe-red:9b` 5.8 GB on disk vs 6.6 GB resident, ~+14%) — record that as the residual gap and let `Headroom` be the mitigation, exactly as vram.rs does, rather than inventing a multiplier. When neither source answers, return `Admission::Unmeasured`, never `size_bytes: 0`.

### A CAPACITY REFUSAL CANNOT BE JOURNALLED ON `RunSpawned`, BECAUSE A REFUSED SPAWN EMITS NO EVENT AT ALL. `Engine::spawn_refused` (engine.rs:3112–3131, read in full) emits one `TurnEvent::ToolLine` and calls `tool_error`; it appends NOTHING to the journal. The design's own test 1 asserts "zero `EventKind::RunSpawned` in the recorder" on a refusal, while `Admission::tag()`'s `refused_no_room` and `refused_cpu_split` arms are said to be "read by `RosterRecorder::append` into the `RunSpawned` row". Those two statements cannot both be true.

- **Why:** The design's stated evidence model is the egress precedent — "37 `web` decisions since the flip, every one `needs_approval`, measured in the signed journal, not argued". For refusals that measurement is impossible as designed: the two refusal tags are unreachable on the only path that records anything, so the enforcement-table row "`Admission` verdict … read by `RosterRecorder::append`" is instance #16 on the design's own central type. It also means a user whose spawn was refused has one transient `ToolLine` and no durable record.
- **Fix:** Add `EventKind::SpawnRefused` and record it from `spawn_refused` with the full decision, not a tag: `{ "role", "model", "verdict", "needs_bytes", "size_source", "free_bytes", "headroom_bytes", "headroom_reason", "gpu_permille" }`. Note this makes `contract_impact` NON-empty: CONTRACTS.md §1.1 (line 113) says the `EventKind` set is closed and "adding a kind is a minor version bump". `RosterRecorder` needs no arm — its `match kind` has a `_ => {}`. Mutation that reddens: delete the `record` call in `spawn_refused` and `a_refused_spawn_leaves_a_row_in_the_journal` fails.

### EIGHT FIELDS ON `Admission` HAVE NO PRODUCTION READER, IN A DESIGN WHOSE PURPOSE IS TO FIX INSTANCE #16. `explain()` is left as `/* … */ String::new()`. The only production consumer named is `tag()`, which discards every number. So `Admit::marginal_bytes`, `Refuse::{needs_bytes, free_bytes, headroom_bytes}`, `RefuseSplit::{on_device_bytes, size_bytes, gpu_permille}` and `Unmeasured::why` are written and never read outside a test. `Admission::admitted()` has no named caller either (the design says `Engine::spawn` branches on `Refuse|RefuseSplit` directly). And the enforcement row for `Residency::model` claims it is read by `roster.rs :: RosterRecorder::append` — verified false: that arm reads only `payload["child"]` and `payload["depth"]` (roster.rs:95–105).

- **Why:** This is `inline_threshold_bytes` again, at eight fields instead of one, filed under a heading that names `inline_threshold_bytes`. A design that ships this reads as having fixed #16 while committing it.
- **Fix:** Specify `explain()` concretely and make it the text `spawn_refused` is called with, so the branch is the reader: `Refuse` → "{model} is not loaded and needs {needs} ({source}); the card has {free} free and this run must leave {headroom} ({headroom_reason}). Nothing was spawned."; `RefuseSplit` → "…{permille}‰ on the GPU…". Journal every number per the fix above. Delete `admitted()` unless a named call site exists. Delete `Unmeasured::why` or make it the text of the `--status` capacity line. Rule to carry: no field on `Admission` ships without a line in `spawn_refused` or the journal payload that reads it.

### NO PRODUCTION `CapacityHost` IMPLEMENTATION IS NAMED, AND THE CRATE GRAPH FORBIDS THE OBVIOUS HOMES. Verified from Cargo.toml: `marlowe-provider` depends on `marlowe-loop` but NOT on `marlowe-memory`; `marlowe-loop` depends on neither provider nor memory; only `marlowe-daemon` depends on both. The residency half (`/api/ps`) is reachable only from `marlowe-provider`; the free-VRAM half (`vram::free_bytes`) only from `marlowe-memory`. The design stops at "the loop cannot depend on the provider" and never says where the impl lives — so as written the shipped daemon builds `Ports` with `capacity: None`, every admission is `Unmeasured`, and the gate is exercised only by test doubles.

- **Why:** Combined with `Routing::uniform` being the only production constructor (verified: `Routing::new` has zero non-test callers), the shipped product would admit unconditionally on two independent grounds. The `--status` acceptance line "dawn:9b-super resident 1000‰…" cannot be printed at all without an impl, so the design's one command-that-prints-a-number is unbuildable from the design.
- **Fix:** Name it: `crates/marlowe-daemon/src/capacity.rs`, `pub struct OllamaCapacity { endpoint: LocalEndpoint, routing: Routing, probe: marlowe_memory::cue::dense::vram::Probe }` implementing `marlowe_loop::CapacityHost`, wired into the `Ports` literal in `Daemon::ask_streaming_with`. Say out loud that `daemon.rs` is being edited concurrently and that this is two lines in it. Add the acceptance run that proves the production path fires (see `strengthened` §8).

### THREE DEFINITIONS OF "WHAT IS RESIDENT ON THIS CARD", AND A SECOND DEFINITION OF "WHAT MUST BE LEFT ALONE". `hybrid.rs:313 unload_resident_ollama_models` already reads `/api/ps` over HTTP. `vram.rs`'s `Reserve::read` already answers the same question via the `ollama ps` CLI plus `ollama list` for size. The design adds a third reader and calls the existing one a reason not to. `Headroom` is likewise a second answer to `ReserveReading`'s question (bytes + a `reason` string, derived not constant, ADR-045 §4's tier table) with the `reason` dropped.

- **Why:** This is the project's single most-logged shape, and the design cites `io_concurrency()` — one definition, every caller routed through it — in the paragraph where it creates the duplicate. Two readers of `/api/ps` will disagree the first time Ollama changes a field name, and only one of them has a test.
- **Fix:** One definition: new `crates/marlowe-provider/src/ollama_ps.rs` — `pub struct Resident { pub model: String, pub size_bytes: u64, pub size_vram_bytes: u64 }`, `pub fn resident_models() -> Option<Vec<Resident>>`. Refactor `unload_resident_ollama_models` to iterate it (mutation: break the parse and `hybrid`'s own eviction test goes red too, which is the point of one definition). Give `Headroom` a `reason: String` and construct it only in `marlowe_daemon::capacity::headroom_for(...)`, mirroring `ReserveReading`.

### CITATIONS THAT DO NOT RESOLVE — the roadmap-row failure repeated. `RunSummary` is at `crates/marlowe-daemon/src/daemon.rs:302`, NOT `control_plane.rs`, so the proposed `parent` field lands in the file another agent is editing right now. `vram.rs` is at `crates/marlowe-memory/src/cue/dense/vram.rs`, in a crate neither `marlowe-loop` nor `marlowe-provider` can reach — cited five times with no path. `--status`'s `runs N live` is printed at `crates/marlowe/src/agent.rs:648` off `protocol.rs:400`'s `pub live_runs: usize`, neither of which the design mentions, so "switched to print both numbers" is a three-file wire change presented as a method on `ControlPlane`.

- **Why:** Correct where it counted (`ollama.rs:300`, `engine.rs:2654`, `roster.rs`'s serde-key reduction, `profile.rs:280` with zero callers, CONTRACTS:941/952 — all re-verified and all right), so the wrong ones read as trustworthy. `RunSummary` in particular is a live collision.
- **Fix:** Cite `daemon.rs:302` for `RunSummary`, `protocol.rs:400` and `agent.rs:648` for the status line, and the full vram.rs path; state the `daemon.rs` collision explicitly.

### `executing_runs` IS WRONG ON THE TERMINALITY IT DEPENDS ON. "Live and holds no non-terminal child" needs a terminal-word test; the only one is `roster.rs:59 is_terminal_word`, which matches `completed | failed | cancelled`. But `RunCompleted` writes `payload["fate"]` into the child's status (roster.rs:149–158) and the fates are `adopted`, `detached`, `terminated` (`durable.rs:424 OrphanOutcome::verb`) plus the literal `no_checkpoint` (engine.rs:2491). A detached or adopted child therefore reads as non-terminal forever and its parent is never "executing" — `executing_runs` would report 0 on a machine making a call.

- **Why:** The whole point of the method is to stop `--status` telling "the truth about intent and a lie about execution". Undercounting to 0 is a second, opposite lie, and the proposed test (a parent→child→grandchild chain, all `running`) cannot see it: it never settles a child.
- **Fix:** Define terminality once over the full wire alphabet (below) and reuse it in both `is_terminal_word` and `executing_runs`. Add a second case to the test: a parent whose only child settled as `detached` must report `executing_runs() == 1`. Mutation: revert terminality to the three-word list — red.

### THE `state_of` TEST ENUMERATES THE WRONG ALPHABET. The design is RIGHT that `waiting_approval`, `waiting_event` and `paused` fall into `watch_client.rs:223`'s `other =>` arm and render as raw tokens — verified, and it is a real live defect. But `state_of`'s input is the UNION of three producers: `RunStatus` serde keys (via `Checkpointed`, roster.rs:120), the control-plane literals `cancelling` (control_plane.rs:477) and `interrupted` (:137), and the four fate words above. A test that iterates `RunStatus` variants asserts a subset, goes green, and leaves `adopted`/`detached`/`terminated`/`no_checkpoint` rendering raw.

- **Why:** An assertion over a list that is not the wire's alphabet reads identically to one that is — the family the whole ledger is about. And `EVERY_WORD.len() == 8` derived from `RunStatus` is #19 exactly: its input is the object it checks.
- **Fix:** Pin the union by hand in `roster.rs` as `pub const EVERY_STATUS_WORD: [&str; 15]`, independent of every producer. Assert (a) `state_of(w)` is not the fallback for each `w`, (b) `run::status_word(v)` is in the list for every `RunStatus` variant, (c) `OrphanOutcome::verb()` is in it for every variant, (d) the two control-plane literals are in it. Mutations: add a `RunStatus` variant → `run::status_word`'s exhaustive match fails to compile; add a fate → (c) red; delete a `state_of` arm → (a) red; shrink the pinned array → (b) or (c) red because the array is not derived from them.

### `Residency` HAS NO VALIDATING CONSTRUCTOR AND `CallLimits::route` DOES NOT CHANGE THE PRODUCT. `Residency` is a pub-field struct: `size_vram_bytes > size_bytes` is constructible, making `gpu_permille() > 1000` and `fully_on_device()` false-negative on a nonsense value. Separately, `CallLimits.route` genuinely gives `model_route()` its first reader (verified: zero callers today) — but `Routing::uniform` is the only production constructor, so `model_for(Worker)` and `model_for(Orchestrator)` return the same tag and the product's behaviour is byte-identical. The design's own test uses `Routing::new`, which nothing in production calls.

- **Why:** The design presents `CallLimits.route` as "the test that ends instance #16 on `model_route`". It ends it at the type level and not in the product, and a green wire test over a routing shape the daemon never builds is the weaker claim standing in for the stronger one. Also missed: `OllamaDriver::new` (ollama.rs:241–243) caches `ModelCapability::unmeasured(model_for(Orchestrator))` — with three real routes that capability is wrong for two of them, a second place naming a model.
- **Fix:** `Residency::new(...) -> Result<Residency, CapacityError>` refusing `size_vram_bytes > size_bytes` and `resident && size_bytes == 0`; private fields, no `Deserialize` (and if one is ever needed, `#[serde(try_from = "...")]` through the constructor — #12). Keep `CallLimits.route`, and state in the test header AND in STATE.md that the product still runs one model until the daemon constructs a three-model `Routing`, which is Session G's window. Flag the per-route `ModelCapability` as a known second definition rather than discovering it later.

### "NEVER A CPU SPLIT" IS NOT ENFORCED, ONLY OBSERVED ONE SPAWN LATE — and the enforcement table overclaims it. Ollama decides layer offload at load; refusing after `/api/ps` reports a split means the split model already loaded and already served. The risks list concedes this ("catches it on the NEXT spawn"), while the enforcement row says the field pair "makes the degree/all-or-nothing reconciliation real rather than a sentence".

- **Why:** AGENT-DIRECTORY §2a's requirement is "a model is fully resident or it does not run". As designed, a split model runs to completion at a tenth of the speed and is refused only the next time somebody spawns.
- **Fix:** State the scope honestly in one sentence and put the closure in `open_for_human`: preventing a split load needs a per-request `options.num_gpu`, which is a provider-behaviour decision of the same class as `keep_alive`. Keep `RefuseSplit` as the detector; do not claim it as the enforcement. The degree/policy reconciliation sentence itself is correct and worth keeping verbatim.

### THE `keep_alive` NARROWING IS ASSERTED IN THE RECOMMENDATION AND DEFERRED IN `open_for_human` AT THE SAME TIME. The recommendation says "'kept warm' is expressed as a per-request `keep_alive` in the body this harness sends" as settled; `open_for_human` says it "needs a `DECISIONS.md` entry before it ships". No enforcement row, no test, no reader in `request_body`.

- **Why:** Axis 7. STATE.md records `OLLAMA_KEEP_ALIVE` as set then deliberately reverted; moving the same behaviour into the request body is a narrowing of a recorded decision and it is the human's. A design that states it twice, once as decided, is how a reversal arrives as a side effect.
- **Fix:** Strike it from Session C entirely. One line in `open_for_human`, nothing in `types`, nothing in `request_body`. The reasoning for why the narrowing is defensible is good and should survive as the argument the human is asked to rule on.

## STRENGTHENED — WHAT GETS BUILT

## The decision, unchanged in its spine

**Admission control REFUSES; it does not queue. `RunStatus` does not move in Session C.** Everything below is the same recommendation with the producers, the readers and the journal row supplied.

Three findings the reviewed design got right and that survive verbatim, because they are load-bearing:

1. **A reason field on `Queued` loses at the surface it was added for.** `roster.rs:71` reduces a status to its serde key — `Value::Object(m) => m.keys().next()` — so `{"queued":{"reason":"capacity"}}` reaches the run table, `watch_client::state_of` and Session G's directory as the bare word `queued`. AGENT-DIRECTORY §2a's "cheapest honest option" is instance #16 at the exact surface it was proposed for. Do not do it.
2. **Do not add `RunStatus::WaitingCapacity` in C.** Nothing can produce it: `Engine::spawn` runs its child inline (`self.run(&mut child_run, …)`, engine.rs:2892), `Routing::new` has zero non-test callers so there is one distinct model in the product, and `OLLAMA_NUM_PARALLEL=1` admits one request per model. A variant with no producer is `Channel::Agent`'s situation, accepted once with the human's approval and a written note; twice is a habit.
3. **Do not block inside `Engine::spawn`.** It runs on the thread that serves the conversation and the daemon holds one connection for the whole turn (M3-DESIGN §6, finding 1). A wait there costs §11's "conversation availability 100%".

---

## §1. One definition of residency — `crates/marlowe-provider/src/ollama_ps.rs` (NEW)

```rust
//! What Ollama currently holds on this card. ONE definition: `hybrid.rs`'s eviction path
//! and the spawn admission gate read the same parse. `/api/ps` lists ONLY resident models —
//! a model that is not loaded has no row, and no field of this struct can describe it.
use std::time::Duration;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Resident {
    pub model: String,
    /// `/api/ps` `size`: the runner's total bytes.
    pub size_bytes: u64,
    /// `/api/ps` `size_vram`: how many of those are ON the device.
    pub size_vram_bytes: u64,
}

/// `None` means the question could not be answered — no Ollama, no reply. That is NOT the
/// same answer as an empty Vec ("Ollama is up and holds nothing"), the distinction
/// `vram::Probe::free_bytes` already draws between `None` and `Some(0)`.
pub fn resident_models() -> Option<Vec<Resident>>;

/// On-disk bytes from `ollama list`, for a model that is NOT resident. A KNOWN
/// UNDERSTATEMENT of the resident footprint — `crates/marlowe-memory/src/cue/dense/vram.rs`
/// measures `marlowe-red:9b` at 5.8 GB on disk and 6.6 GB resident at 32k, ~+14%. No
/// multiplier is invented here; vram.rs refuses "a multiplier nobody measured" and so does this.
pub fn on_disk_bytes(model: &str) -> Option<u64>;
```

`hybrid.rs::unload_resident_ollama_models` is refactored to iterate `resident_models()` rather than re-parsing `ps["models"]` at :315. That is what makes it one definition and not two: **break the parse and `hybrid`'s own eviction test goes red as well as the admission tests.**

## §2. `crates/marlowe-loop/src/capacity.rs` (NEW — deliberately not `driver.rs`)

```rust
use crate::profile::ModelRoute;

/// Where a size came from, because the two sources answer different questions and one of
/// them is known to be low. The verdict names it; the journal records it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SizeSource {
    /// `/api/ps` `size`, read while the model is resident. Authoritative.
    ApiPsResident,
    /// `ollama list`, read for a model that is not loaded. Understates by ~14% (vram.rs).
    OllamaListOnDisk,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Residency {
    model: String,
    resident: bool,
    size_bytes: u64,
    size_source: SizeSource,
    size_vram_bytes: u64,
    free_bytes: u64,
}

impl Residency {
    /// THE ONLY WAY IN. No `Deserialize`; if one is ever needed it routes through here with
    /// `#[serde(try_from = "…")]` (ledger #12 — serde is a way in).
    pub fn new(
        model: String, resident: bool, size_bytes: u64,
        size_source: SizeSource, size_vram_bytes: u64, free_bytes: u64,
    ) -> Result<Self, CapacityError> {
        if size_vram_bytes > size_bytes { return Err(CapacityError::MoreOnDeviceThanExists); }
        if resident && size_bytes == 0 { return Err(CapacityError::ResidentWithNoSize); }
        if resident && size_source != SizeSource::ApiPsResident {
            return Err(CapacityError::ResidentSizeFromTheWrongSource);
        }
        Ok(Self { model, resident, size_bytes, size_source, size_vram_bytes, free_bytes })
    }
    /// THE DEGREE, per-mille, so no float equality reaches a decision path and the number
    /// the user reads is the number the policy compared. 1000 = fully on the GPU.
    pub fn gpu_permille(&self) -> u32 {
        if self.size_bytes == 0 { return 0; }
        ((u128::from(self.size_vram_bytes) * 1000) / u128::from(self.size_bytes)) as u32
    }
    /// The POLICY over the degree, all-or-nothing. STATE.md's "42/48 layers is healthy" is
    /// about the shelved llama.cpp hybrid serving tier 1; the agent pool is not that.
    pub fn fully_on_device(&self) -> bool {
        self.resident && self.size_bytes > 0 && self.size_vram_bytes == self.size_bytes
    }
    pub fn model(&self) -> &str { &self.model }
    pub fn free_bytes(&self) -> u64 { self.free_bytes }
    pub fn size_source(&self) -> SizeSource { self.size_source }
}

/// Spare device memory a spawn must leave behind, WITH THE BRANCH THAT PRODUCED IT.
/// Shaped after `vram::ReserveReading` for the same reason: five branches can return the
/// same number, so the number cannot say which one answered and the reason has to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Headroom { bytes: u64, reason: String }

impl Headroom {
    /// Zero is refused at construction. A limit written as zero reads as "fill the card
    /// exactly"; free VRAM is an instant and tier 0 — the desktop — held 5,086 MiB on this
    /// machine before any model loaded. Ledger #17, inverted.
    pub fn new(bytes: u64, reason: String) -> Result<Self, CapacityError> {
        if bytes == 0 { return Err(CapacityError::ZeroHeadroom); }
        Ok(Self { bytes, reason })
    }
    pub fn bytes(&self) -> u64 { self.bytes }
    pub fn reason(&self) -> &str { &self.reason }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Admission {
    Admit  { model: String, marginal_bytes: u64, source: SizeSource },
    Refuse { model: String, needs_bytes: u64, source: SizeSource,
             free_bytes: u64, headroom_bytes: u64, headroom_reason: String },
    /// Resident and split across CPU and GPU. Measured, not declared.
    RefuseSplit { model: String, on_device_bytes: u64, size_bytes: u64, gpu_permille: u32 },
    /// No reading, OR a not-resident model whose footprint no source could supply.
    /// FAIL OPEN, argued: capacity is a performance control whose failure mode is slowness,
    /// not privilege. Failing closed stops every machine with no `nvidia-smi` — an AMD card,
    /// a Mac — from spawning at all, on the "all consumer hardware" target STATE.md names.
    /// It is not silent: it is journalled on every spawn.
    Unmeasured { why: String },
}

impl Admission {
    /// The wire tag on the journal row. Stable: a journal query greps for it.
    pub fn tag(&self) -> &'static str { /* admitted | refused_no_room | refused_cpu_split | unmeasured */ }
    /// Harness-authored, one sentence, EVERY number the verdict carries. This string is what
    /// `spawn_refused` is called with, so the branch is the reader — the numbers are not
    /// stored anywhere to be reported later. Ledger #16: an `Admission` field on a struct is
    /// the next `inline_threshold_bytes`.
    ///
    ///   Refuse → "marlowe-mini:4b-super is not loaded and needs 3,271,515,176 bytes
    ///             (ollama list, on-disk — the resident footprint is larger); the card has
    ///             1,104,150,528 free and this run must leave 838,860,800 for the embedder's
    ///             session. Nothing was spawned."
    ///   RefuseSplit → "…is loaded but only 514‰ of it is on the GPU…"
    pub fn explain(&self) -> String;
    /// The journal payload. Every field of every variant appears here.
    pub fn payload(&self, role: ModelRoute) -> serde_json::Value;
}

/// THE WHOLE DECISION, AS A PURE FUNCTION OF A READING. One definition, three consumers:
/// `Engine::spawn` branches on it, `spawn_refused` journals `payload()`, `--status` renders
/// the reading behind it. The shape `blocks_composed_targets` already has.
pub fn admit(reading: Option<&Residency>, headroom: &Headroom) -> Admission {
    let Some(r) = reading else {
        return Admission::Unmeasured { why: "no residency reading was available".into() };
    };
    if r.resident && !r.fully_on_device() { return Admission::RefuseSplit { /* … */ }; }
    // A resident model costs nothing more: Ollama shares weights across requests to the same
    // model, so "three workers of one role" multiplies the KV cache, not the weights
    // (AGENT-DIRECTORY §2a's first reading).
    let needs = if r.resident { 0 } else { r.size_bytes };
    // A not-resident model whose size nobody could supply is UNMEASURED, never `needs = 0`.
    // `/api/ps` has no row for it; a zero here would read as "costs nothing" and admit —
    // ledger #17's shape arriving from the producer instead of the constructor.
    if !r.resident && r.size_bytes == 0 {
        return Admission::Unmeasured { why: format!("{} is not loaded and neither `/api/ps` nor `ollama list` reported a size", r.model) };
    }
    if needs.saturating_add(headroom.bytes()) > r.free_bytes { return Admission::Refuse { /* … */ }; }
    Admission::Admit { model: r.model.clone(), marginal_bytes: needs, source: r.size_source }
}

pub trait CapacityHost {
    fn residency(&mut self, route: ModelRoute) -> Option<Residency>;
}
```

## §3. The port on `Ports` is REQUIRED and NAMED, not `Option`

```rust
// crates/marlowe-loop/src/engine.rs
pub enum CapacityPort<'a> {
    Enforced(&'a mut dyn CapacityHost),
    /// This build does not gate spawns on capacity. **A STATED CHOICE, not an omission** —
    /// exactly `vram::Reserve::None`'s and `Tier1Runtime`'s discipline: "a `ForTier1(&str)`
    /// that kept compiling would leave every call site meaning Ollama BY OMISSION."
    Unenforced,
}
pub struct Ports<'a> {
    // … the nine that exist …
    pub capacity: CapacityPort<'a>,
}
```

Blast radius, measured rather than guessed: **70 `Ports {` literals across 24 files**. Every one becomes a compile error that must state which it means. `Engine::spawn`'s child `Ports` (engine.rs:2880) and `condense_batch`'s (engine.rs:~2270) both pass `CapacityPort::Unenforced` — see §6.

## §4. The production implementation, named, in the only crate that can hold it

Verified from `Cargo.toml`: `marlowe-provider` does not depend on `marlowe-memory`; `marlowe-loop` depends on neither. Only `marlowe-daemon` sees both halves.

```rust
// crates/marlowe-daemon/src/capacity.rs (NEW)
pub struct OllamaCapacity { endpoint: LocalEndpoint, routing: Routing, probe: vram::Probe }
impl marlowe_loop::CapacityHost for OllamaCapacity {
    fn residency(&mut self, route: ModelRoute) -> Option<Residency> {
        let model = self.routing.model_for(route).to_string();
        let free = self.probe.free_bytes()?;                     // vram::free_bytes, one definition
        let ps = marlowe_provider::ollama_ps::resident_models()?; // one definition
        match ps.iter().find(|r| r.model == model) {
            Some(r) => Residency::new(model, true,  r.size_bytes, SizeSource::ApiPsResident,   r.size_vram_bytes, free).ok(),
            None => {
                let d = marlowe_provider::ollama_ps::on_disk_bytes(&model).unwrap_or(0);
                Residency::new(model, false, d, SizeSource::OllamaListOnDisk, 0, free).ok()
            }
        }
    }
}
```

`Headroom` is constructed once, in `marlowe_daemon::capacity::headroom_for(embedder_session_bytes, probe)`, and carries its reason ("one embedder session, 838,860,800 B, so ADR-044's `auto` can still resolve to CUDA"). **`crates/marlowe-daemon/src/daemon.rs` is being edited by another agent right now**: this is two lines in it — one constructor beside the driver build, one field in the `Ports` literal in `Daemon::ask_streaming_with`. Coordinate, do not race.

## §5. The refusal is JOURNALLED — and this IS a contract change

`Engine::spawn_refused` (engine.rs:3112–3131) emits a `ToolLine` and a blocked-tool block and **appends nothing to the journal**. So:

- Add `EventKind::SpawnRefused` to `crates/marlowe-journal/src/event.rs`. **CONTRACTS.md §1.1 (line 113) says the kind set is closed and "adding a kind is a minor version bump" — so `contract_impact` is NOT none.** (`crates/marlowe-journal/src/{signature,journal}.rs` is §13-guarded; `event.rs` is not.)
- `spawn_refused` gains a `payload: serde_json::Value` argument and records it. `RosterRecorder` needs no arm — its `match kind` ends in `_ => {}`.
- The row carries `admission.payload(role)`: `{role, model, verdict, needs_bytes, size_source, free_bytes, headroom_bytes, headroom_reason, gpu_permille}`. **This is what makes every `Admission` field have a production reader**, and it is what makes the egress-style measurement possible: "N spawn decisions since the flip, M refused" out of the signed journal.
- `Admit` and `Unmeasured` ride on the existing `RunSpawned` payload under key `"admission"`, same shape.

## §6. What does NOT get the gate, and why

`condense_batch` passes `CapacityPort::Unenforced`. A quarantined reader runs on the model the parent is already using, at zero marginal residency — there is nothing to admit. Worse, a capacity check that can refuse layer 1 hands anyone who can raise VRAM pressure (launch a game, open enough tabs) a way to make quarantined reads fail, converting a resource condition into a containment-quality denial. The spawned child (engine.rs:2880) is also `Unenforced`: it was already admitted at its own spawn site, and re-checking inside would be a second answer to a question already answered.

## §7. `CallLimits::route`, stated honestly

```rust
// crates/marlowe-loop/src/budget.rs — CallLimits is not pinned in CONTRACTS.
pub struct CallLimits { pub max_output_tokens: u64, pub route: ModelRoute }
impl Budget { pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits { … } }
```

Reader: `crates/marlowe-provider/src/ollama.rs:300`, replacing the hardcoded `self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator)`. Call site: `engine.rs:794`, `run.budget.call_limits(&run.spent, run.profile.model_route())` — **the first caller `CapabilityProfile::model_route()` has ever had** (verified: `grep -rn "model_route()"` returns only the definition at `profile.rs:280`).

**Stated in the test header, in STATE.md, and not glossed: this changes no product behaviour today.** `Routing::uniform` is the only production constructor (`agent.rs:47`, `daemon.rs:1263/1338/1503/1889/1976`), so all three routes return one tag. A three-model `Routing` needs config the daemon does not have; that is Session G's window. **Also recorded as a known second definition to close then, not discovered later:** `OllamaDriver::new` (ollama.rs:241–243) caches `ModelCapability::unmeasured(model_for(Orchestrator))`, which is wrong for two of three routes the moment routing is real.

## §8. Tests — each names its file and the mutation that reddens it

1. `crates/marlowe-loop/tests/spawn_admission.rs :: a_spawn_that_does_not_fit_is_refused_by_name_with_every_number_and_no_child_is_created` — fixed host returning `Residency::new("marlowe-mini:4b-super", false, 3_271_515_176, SizeSource::OllamaListOnDisk, 0, 1_104_150_528)`, `Headroom::new(838_860_800, …)`. Asserts: zero `RunSpawned`, one `SpawnRefused` whose payload carries all six numbers, a `ToolLine{verb:"spawn", target:"refused"}`, and a `[run blocked]` block naming the TAG. **Anti-proxy: the assertion is the absence of a run, not the presence of a message.** Mutations: `admit` returns `Admit` unconditionally → a child appears; drop `free_bytes` from `explain()` → substring fails; delete `record` in `spawn_refused` → the payload assertion fails.
2. `…:: a_model_that_is_not_loaded_and_has_no_reported_size_is_unmeasured_not_free` — `size_bytes: 0, resident: false` yields `Unmeasured`, NOT `Admit`. **This is the test the reviewed design lacked and the one that matters most: it is the difference between a gate and a decoration.** Mutation: restore `let needs = if resident {0} else {size_bytes}` without the guard → verdict becomes `Admit` and the assertion fails.
3. `…:: a_resident_model_split_across_cpu_and_gpu_is_refused_even_though_it_is_loaded` — `Residency::new(…, true, 5_832_064_368, ApiPsResident, 3_000_000_000, …)` → `RefuseSplit{gpu_permille: 514}`, per-mille in the text. Mutation: `fully_on_device` → `size_vram_bytes > 0` → `Admit`.
4. `…:: a_build_with_capacity_unenforced_still_spawns_and_the_journal_says_so` — `CapacityPort::Unenforced` → child created, `RunSpawned` carries `"admission":"unmeasured"`. **Negative control**: without it a gate refusing everything passes 1–3. Mutation: fail closed → no child.
5. `crates/marlowe-loop/src/capacity.rs` unit tests — `Headroom::new(0, _) == Err(ZeroHeadroom)`, no `Default`, no second constructor; `Residency::new` refuses `size_vram > size` and `resident && size == 0`. Mutations: return `Ok` unconditionally; add `#[derive(Default)]`.
6. `crates/marlowe-provider/tests/the_route_chooses_the_model.rs :: a_worker_call_names_the_worker_model` — `Routing::new("marlowe-dawn:9b-super","marlowe-mini:4b-super","marlowe-mini:2b")`, THREE DISTINCT NAMES stated in the header because `Routing::uniform` makes it vacuous. Mutation: restore the `Orchestrator` literal at ollama.rs:300.
7. `crates/marlowe-daemon/tests/every_status_word_reaches_a_state_the_window_understands.rs` — pin the wire alphabet BY HAND, independent of every producer: `pub const EVERY_STATUS_WORD: [&str; 15]` in `roster.rs` = the eight `RunStatus` keys + `cancelling` (control_plane.rs:477) + `interrupted` (:137) + `adopted`/`detached`/`terminated` (`durable.rs:424`) + `no_checkpoint` (engine.rs:2491) + `unknown` (control_plane.rs:257). Asserts (a) `state_of(w)` is never the `other =>` fallback for any `w`; (b) `marlowe_loop::run::status_word(v)` ∈ the list for every `RunStatus`; (c) `OrphanOutcome::verb()` ∈ the list for every variant; (d) `roster::status_word(&to_value(v))` agrees with `run::status_word(v)`. **RED ON THE CURRENT TREE** — `waiting_approval`, `waiting_event`, `paused` and all four fate words hit `watch_client.rs:223`'s fallback today and render as raw tokens. Mutations: add a `RunStatus` variant → `run::status_word`'s exhaustive match fails to COMPILE; add a fate → (c) red; delete a `state_of` arm → (a) red; **shrink the pinned array → (b) or (c) red, because the array is not derived from what it checks** (ledger #19).
   On the two derivations: `roster::status_word` is a DECODER over arbitrary JSON (its domain includes payloads that are not `RunStatus` at all); `run::status_word` is the DEFINITION. (d) asserts the decoder agrees with the definition on the definition's whole domain. Say that in the header, or it reads as two definitions.
8. `crates/marlowe-daemon/tests/a_serial_tree_is_not_reported_as_parallel.rs` — parent→child→grandchild all `running`: `live_runs() == 3`, `executing_runs() == 1`. **Second case, which the reviewed design would have failed:** a parent whose only child settled as `detached` reports `executing_runs() == 1`, because `is_terminal_word` (roster.rs:59) covers only `completed|failed|cancelled` while `RunCompleted` writes `adopted`/`detached`/`terminated`/`no_checkpoint` (roster.rs:149–158). Terminality is defined once over `EVERY_STATUS_WORD` and reused. Mutations: delegate `executing_runs` to `live_runs` → 3; revert terminality to three words → 0 on the second case.
   Files this actually touches, cited correctly: `RunSummary` gains `parent: Option<String>` at **`crates/marlowe-daemon/src/daemon.rs:302`** (not `control_plane.rs`), set in `roster.rs`'s `RunSpawned` arm where both ids are already in hand; `executing_runs` on `ControlPlane`; a field beside `pub live_runs: usize` at **`protocol.rs:400`**; the print at **`agent.rs:648`** becomes `runs  3 live · 1 executing`.
9. **The command that prints a number, on the SHIPPED binary** — `runs/m3c-admission/capacity.txt`. `--status` gains `capacity  1053 MiB free · dawn:9b-super 1000‰ · mini:4b-super 1000‰ · mini:2b 1000‰`, baselined against this session's measurement (16,376 MiB total, 5,086 MiB held by the desktop before any model, 10,849,836,070 B resident, 1,053 MiB free).
10. **And the one that proves the PRODUCTION path can refuse, which no unit test can.** `MARLOWE_CAPACITY_HEADROOM_BYTES=12884901888 target/release/marlowe.exe` → one `run` spawn on this box → a refusal in the transcript and exactly one `SpawnRefused` row in the signed journal, printed. Recorded in `runs/m3c-admission/live-refusal.txt`. Without this, the gate's only exercise is a test double and every finding above recurs. (The env var is a measurement-only override on `headroom_for`, documented as `Probe::Fixed` is: nothing in the product sets it.)

## §9. Scope — what stays the human's, and what this design does NOT take

- **The fourth model role's name.** Not guessed. `admit` is written over `ModelRoute`'s existing three arms so a fourth is a compile error.
- **`OLLAMA_KEEP_ALIVE`.** Struck from Session C entirely — no `keep_alive` in `request_body`, no type, no test. The argument for narrowing the reverted global into a per-request value scoped to our models is sound and is recorded as the question the human is asked; it is not taken here.
- **`num_gpu` / preventing a split LOAD.** `RefuseSplit` detects a split; it cannot prevent Ollama from loading one, so a split model runs to completion and is refused on the NEXT spawn. Stated as the residual, not claimed as enforcement.
- **Whether concurrency is wanted at all** against `NUM_PARALLEL=1`'s prefix-cache protection (a 148-byte prefix change cost 1.45 s here). That decides whether `WaitingCapacity` ever gets a producer.
- **Whether a spawner-named role is a TARGET under ADR-023** (AGENT-DIRECTORY §3 item 4). Today `Engine::spawn` hardcodes `ModelRoute::Worker` (engine.rs:2654) and nothing model-supplied reaches the gate, so `adjudicate.rs` is untouched. The moment `run` carries a role, both a downgrade and an upgrade are attacker-useful and `composes_spawn_targets` (engine.rs:3237) needs a fourth clause. **Do not let that arrive as a side effect of this design.**
- **`AGENT-DIRECTORY.md` §2's arithmetic is wrong and it is human-authored**: "10.0 GB of the card's 16, leaving headroom" against a measured 1,053 MiB free with all three roles resident. Since ADR-044 resolves the embedder against free VRAM AT LOAD, co-residency means the embedder silently resolves to CPU with a correct-looking log line. Correcting it is the human's; `Headroom`'s reason string is what stops the same arithmetic being re-committed in code.
- **§13-guarded files: `driver.rs`, `profile.rs`, `adjudicate.rs` are NOT touched** by anything above. If the human prefers `CapacityHost` to sit beside the other ports in `driver.rs`, that is a guarded edit needing approval and a `DECISIONS.md` entry — say so before making it.
- **`ingest` stays unwired**: `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns exactly two hits, both definitions.

## §10. Contract impact — NOT none

`EventKind` gains `SpawnRefused`: CONTRACTS §1.1, a minor version bump, and the pinned list at line 116 must be edited (it is already drifting — `TrustFloorLatched` is in the code and not in that list; fix both in the same commit). `RunStatus` is unchanged, no variant added, every wire spelling identical. `CapabilityProfile` unchanged — `model_route` is already pinned at §5:952 and merely gains its first reader. `SpawnRequest` untouched; note that §5:941 pins only `fn spawn(&self, req: SpawnRequest) -> RunId`, never the struct's fields, so item (4)'s role field is a first pinning, not a move. `CallLimits`, `Budget::call_limits`, `Ports`, `RunSummary`, `LoopOutcome` appear nowhere in CONTRACTS. `CHECKPOINT_VERSION` does not move. **What C owes §5 in prose:** that `Queued` means constructed-not-yet-started, that capacity-waiting will be a distinct variant and never a reason on `Queued`, and that the variant lands with the concurrency that produces it — the discipline §12.1 used when it pinned `ingest_external` and said in its own words that nothing calls it.

## §11. Risks that remain after all of the above

- The reading is an instant; tier 0 held 5,086 MiB before any model loaded and is not ours to schedule. `Headroom` is the whole mitigation, which is why zero is refused at construction.
- `ollama list` understates by ~14%, so a not-resident admission can still split. `SizeSource` makes the weaker number visible in the refusal and the journal instead of laundering it.
- One HTTP round trip per spawn on the turn thread, bounded by `http::get_json`'s 5 s deadline — the same cost `hybrid.rs` already pays. It must never become a poll and must never run per loop iteration.
- **Instance #16 is the risk this design is most exposed to, because it is fixing one.** `Admission` must never become a field on `Run` or `RunSummary` "for the directory". It is a branch and a journal row; delete what reads it and test 1 goes red.
- The fixed `CapacityHost` and the `MARLOWE_CAPACITY_HEADROOM_BYTES` override inherit `Probe::Fixed`'s rule verbatim: nothing in the product constructs them, and neither becomes a config knob letting someone declare a card the machine does not have.

---

## Original recommendation

Capacity-waiting is **in principle** a distinct `RunStatus` variant and **never** a reason on `Queued` — a reason field loses at `roster.rs::status_word`, which reduces every status to its serde *key*, so `{"queued":{"reason":…}}` reaches the roster, `state_of` and Session G's directory as the bare word `queued`: the "cheapest honest option" is instance #16 at the exact surface it was added for. But the variant is **not added in Session C**, because nothing can produce it: `Engine::spawn` runs its child inline (`self.run(&mut child_run, …)`, engine.rs ~2884), so at most one model call is in flight per process, `Routing::new` has zero production callers (only `Routing::uniform` delegates to it) so there is exactly **one distinct model** in the shipped product, and `OllamaDriver::request_body` hardcodes `ModelRoute::Orchestrator` (ollama.rs:300) so `CapabilityProfile::model_route()` has **zero callers in the entire workspace** — the per-role queue's key is a declared control nothing reads. So C ships the admission **decision**, not the wait: `admit(reading, headroom)` as a pure function over a measured `/api/ps` + free-VRAM reading, consulted at the one spawn site, refusing (never blocking) with both numbers, fail-**open** when unmeasurable and journalled on `RunSpawned` rather than bannered (ledger #15). C also ships the three things that make the queue possible later and are non-vacuous now: `CallLimits.route` gives `model_route` its first reader; `ControlPlane::executing_runs` stops `--status` reporting a depth-3 inline tree as "3 live" on a machine making one call; and an exhaustive `status_word(&RunStatus)` makes the eventual `WaitingCapacity` variant a **compile error** in three mirrors instead of a silent drift into `state_of`'s `other =>` arm. On the two standing decisions: (1) `OLLAMA_KEEP_ALIVE` stays reverted as a global env var and `-1` is refused — "kept warm" is expressed as a **per-request `keep_alive`** in the body this harness sends, which is scoped to our models and revocable, a narrowing of the recorded decision rather than a reversal; (2) "never CPU-split" and "the offload check is a DEGREE" are not in conflict and here is the sentence — **the measurement is a degree (`size_vram/size` from `/api/ps`, reported as `gpu_permille`), the agent pool's policy over that degree is all-or-nothing**, and the shelved hybrid's rule, if it returns, governs tier-1 serving and not the pool.

### Types

```rust
// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/capacity.rs — NEW FILE. Deliberately NOT driver.rs:
// driver.rs is §13-guarded for the memory and approval ports, and capacity is neither.
// ─────────────────────────────────────────────────────────────────────────────
use crate::profile::ModelRoute;

/// One reading of model residency, taken at an instant. `GET /api/ps` for `size`/`size_vram`,
/// the device for `free`. **The env vars are declarations; this is the measurement**
/// (AGENT-DIRECTORY §2). Every field has a reader in `admit` — see the enforcement table.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Residency {
    /// The tag this role resolves to, so a refusal can NAME the model rather than a role.
    pub model: String,
    /// Whether `/api/ps` listed it at all. Decides marginal cost 0 vs `size_bytes`.
    pub resident: bool,
    /// `/api/ps` `size`: the runner's total bytes.
    pub size_bytes: u64,
    /// `/api/ps` `size_vram`: how many of those are ON the device.
    pub size_vram_bytes: u64,
    /// Device memory free right now, net of tier 0. Measured 1,053 MiB on this box with all
    /// three roles resident — which is less than one embedder session, so ADR-044's `auto`
    /// resolves the embedder to CPU. AGENT-DIRECTORY §2's "leaving headroom" is wrong.
    pub free_bytes: u64,
}

impl Residency {
    /// **THE DEGREE, in per-mille rather than a float**, so the number reported to the user and
    /// the number the policy compares cannot disagree about rounding, and no float equality
    /// appears on a decision path. 1000 = fully on the GPU.
    pub fn gpu_permille(&self) -> u32 {
        if self.size_bytes == 0 { return 0; }
        ((u128::from(self.size_vram_bytes) * 1000) / u128::from(self.size_bytes)) as u32
    }
    /// The POLICY over the degree, all-or-nothing. STATE.md's "42/48 layers is healthy" is about
    /// the shelved hybrid serving tier 1; a worker model on the CPU is 10x slower and the
    /// alternative — not spawning it — is cheap.
    pub fn fully_on_device(&self) -> bool {
        self.resident && self.size_bytes > 0 && self.size_vram_bytes == self.size_bytes
    }
}

/// Spare device memory a spawn must leave behind, in bytes.
///
/// **Zero is refused at construction.** Ledger #17 inverted: a limit written as zero reads as
/// "fill the card exactly", and `vram.rs`'s own header says a free-memory reading is an instant
/// another process can allocate between. A load-time error, not a sensible default.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Headroom(u64);

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum CapacityError {
    #[error(
        "a headroom of zero bytes means `fill the card exactly`. Free VRAM is a measurement at \
         an instant and another process can allocate between two readings; tier 0 — the desktop \
         — held 5,086 MiB on this machine before any model loaded"
    )]
    ZeroHeadroom,
}

impl Headroom {
    pub fn new(bytes: u64) -> Result<Self, CapacityError> {
        if bytes == 0 { return Err(CapacityError::ZeroHeadroom); }
        Ok(Self(bytes))
    }
    pub fn bytes(self) -> u64 { self.0 }
}

/// The verdict.
///
/// **THERE IS NO `Queue` VARIANT AND ITS ABSENCE IS THE DECISION.** `Engine::spawn` runs its
/// child inline, so a wait here is a wait on the thread that serves the conversation — which
/// M3-DESIGN §11 costs at 100% availability and CLAUDE.md forbids outright. A `Queue` variant
/// nothing can enter would be `Channel::Agent`'s shape a second time.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Admission {
    Admit { model: String, marginal_bytes: u64 },
    Refuse { model: String, needs_bytes: u64, free_bytes: u64, headroom_bytes: u64 },
    /// Resident and split across CPU and GPU. "Never a CPU split", measured rather than declared.
    RefuseSplit { model: String, on_device_bytes: u64, size_bytes: u64, gpu_permille: u32 },
    /// No reading could be taken. **Fail OPEN, argued rather than assumed**: capacity is a
    /// performance control whose failure mode is slowness, not privilege, and failing closed
    /// would stop every machine with no `nvidia-smi` — an AMD card, a Mac — from spawning at all,
    /// on exactly the "all consumer hardware" target STATE.md names. It is not a silent default:
    /// the tag is journalled on every `RunSpawned`.
    Unmeasured { why: String },
}

impl Admission {
    pub fn admitted(&self) -> bool {
        !matches!(self, Admission::Refuse { .. } | Admission::RefuseSplit { .. })
    }
    /// The wire tag on `RunSpawned`. Stable: a journal query greps for it.
    pub fn tag(&self) -> &'static str {
        match self {
            Admission::Admit { .. } => "admitted",
            Admission::Refuse { .. } => "refused_no_room",
            Admission::RefuseSplit { .. } => "refused_cpu_split",
            Admission::Unmeasured { .. } => "unmeasured",
        }
    }
    /// Harness-authored, one sentence, **both numbers**. A refusal carrying one number cannot be
    /// acted on; `Budget::grant` already refuses with both and this follows it.
    pub fn explain(&self) -> String { /* … */ String::new() }
}

/// **The whole decision, as a pure function of a reading.** One definition, three consumers:
/// `Engine::spawn` branches on it, `RosterRecorder` journals its tag, Session G's directory
/// renders it. The shape `blocks_composed_targets` already has, for the same reason M2 C2f gives.
pub fn admit(reading: Option<&Residency>, headroom: Headroom) -> Admission {
    let Some(r) = reading else {
        return Admission::Unmeasured { why: "no residency reading was available".into() };
    };
    if r.resident && !r.fully_on_device() {
        return Admission::RefuseSplit {
            model: r.model.clone(),
            on_device_bytes: r.size_vram_bytes,
            size_bytes: r.size_bytes,
            gpu_permille: r.gpu_permille(),
        };
    }
    // A resident model costs nothing more to use. Ollama shares weights across requests to the
    // same model, so "three workers of one role" multiplies the KV cache, not the weights.
    let needs = if r.resident { 0 } else { r.size_bytes };
    if needs.saturating_add(headroom.bytes()) > r.free_bytes {
        return Admission::Refuse {
            model: r.model.clone(),
            needs_bytes: needs,
            free_bytes: r.free_bytes,
            headroom_bytes: headroom.bytes(),
        };
    }
    Admission::Admit { model: r.model.clone(), marginal_bytes: needs }
}

/// The port. `marlowe-loop` cannot depend on `marlowe-provider` (the dependency runs the other
/// way), and a loop that shelled out to `ollama` itself would be a second definition of residency
/// beside `marlowe_provider::hybrid::unload_resident_ollama_models`.
pub trait CapacityHost {
    /// `None` means the question could not be answered — no Ollama, no device, no reply. That is
    /// **not** the same answer as "nothing is resident", exactly as `vram::Probe::free_bytes`
    /// separates `None` from `Some(0)`.
    fn residency(&mut self, route: ModelRoute) -> Option<Residency>;
}

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/budget.rs — CallLimits is NOT pinned in CONTRACTS.
// ─────────────────────────────────────────────────────────────────────────────
pub struct CallLimits {
    pub max_output_tokens: u64,
    /// **Which role's model serves this call — the first reader `CapabilityProfile::model_route`
    /// has ever had.** Written at four sites, read at zero, since M2. Not `Option`, not defaulted:
    /// `Budget::call_limits` now takes it, so every construction site is a compile error until it
    /// states one.
    pub route: ModelRoute,
}

impl Budget {
    pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens, route }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/engine.rs — Ports is not pinned in CONTRACTS.
// ─────────────────────────────────────────────────────────────────────────────
pub struct Ports<'a> {
    // … the nine that exist …
    /// `None` = this build cannot measure residency. Admission is then `Unmeasured`, the spawn
    /// proceeds, and the tag reaches the journal. **Not a banner**: a `Degraded` line that fires
    /// on every spawn of every run with no probe is ledger #15 — a latch that fires on everything
    /// means nothing at the moment it starts to matter.
    pub capacity: Option<&'a mut dyn CapacityHost>,
}

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/run.rs — RunStatus IS UNCHANGED. This is the guard that
// makes adding `WaitingCapacity` later a compile error rather than a silent drift.
// ─────────────────────────────────────────────────────────────────────────────
/// The one word a `RunStatus` reduces to on the wire.
///
/// **Exhaustive, no wildcard arm.** `roster.rs::status_word` derives the same word from serde's
/// key and `watch_client::state_of` maps it to `RunState`; that chain has a permissive
/// `other => RunState::Paused { reason: <raw wire token> }` at the end, so a new variant renders
/// as an unstyled token today and nothing fails. Adding a variant is now a compile error HERE,
/// which is the moment its `state_of` arm has to be written.
pub fn status_word(s: &RunStatus) -> &'static str {
    match s {
        RunStatus::Queued => "queued",
        RunStatus::Running => "running",
        RunStatus::WaitingApproval { .. } => "waiting_approval",
        RunStatus::WaitingEvent { .. } => "waiting_event",
        RunStatus::Paused { .. } => "paused",
        RunStatus::Completed => "completed",
        RunStatus::Failed { .. } => "failed",
        RunStatus::Cancelled => "cancelled",
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-daemon/src/control_plane.rs — RunSummary is not pinned.
// ─────────────────────────────────────────────────────────────────────────────
pub struct RunSummary {
    // … existing fields …
    /// The spawning run, recorded where `RosterRecorder` already knows both ids: `RunSpawned` is
    /// appended under the PARENT and names the child in its payload. Read by `executing_runs`.
    pub parent: Option<String>,
}

impl ControlPlane {
    /// Runs with a model call **in flight** — not runs whose loop is on the stack.
    ///
    /// `live_runs` counts `status == "running"`, and under an inline `Engine::spawn` every
    /// ancestor of a working child is ALSO `Running`. A depth-3 tree therefore prints
    /// `runs 3 live` on a machine that, under `OLLAMA_NUM_PARALLEL=1` and a synchronous spawn,
    /// is making exactly one call. **That is the directory telling the truth about intent and a
    /// lie about execution**, and it is already shipped in `--status`.
    ///
    /// A run is executing iff it is live and holds no non-terminal child.
    pub fn executing_runs(&self) -> usize { /* … */ 0 }
}
```

### Enforcement sites

- `Residency::size_vram_bytes and Residency::size_bytes` -> **crates/marlowe-loop/src/capacity.rs :: Residency::fully_on_device (policy) and Residency::gpu_permille (reporting); both reached from capacity.rs::admit's RefuseSplit branch** | breaks: "never a CPU split" becomes a declaration with no measurement — a model split 60/40 between GPU and CPU is admitted, runs at a tenth of the speed, and nothing reports why. This is the field pair that makes the degree/all-or-nothing reconciliation real rather than a sentence.
- `Residency::free_bytes` -> **crates/marlowe-loop/src/capacity.rs :: admit — the `needs + headroom > free` comparison in the Refuse branch** | breaks: admission has no ceiling and every spawn is admitted; on this machine that means loading a 4th model against 1,053 MiB free, which Ollama answers by evicting something — silently, in a log that cannot see us (vram.rs's own recorded failure mode).
- `Residency::resident` -> **crates/marlowe-loop/src/capacity.rs :: admit — chooses `needs = 0` (already loaded, weights shared) vs `needs = size_bytes`** | breaks: a resident model is charged its full weight again, so the second spawn of the SAME role is refused on a card that has room — the doc's first reading of "3 workers, out of memory" gets the wrong bottleneck, which AGENT-DIRECTORY §2a explicitly warns about.
- `Residency::model` -> **crates/marlowe-loop/src/engine.rs :: Engine::spawn (into spawn_refused's text) and crates/marlowe-daemon/src/roster.rs :: RosterRecorder::append (the RunSpawned payload)** | breaks: the refusal names a role instead of a tag, and a user cannot act on it — `ollama pull` and `ollama ps` both take a tag.
- `Headroom (and its refusal of zero)` -> **crates/marlowe-loop/src/capacity.rs :: admit (the comparison) and Headroom::new (the load-time refusal); constructed in crates/marlowe-daemon/src/daemon.rs where the embedder's per-session size is known** | breaks: headroom becomes a u64 that can be 0, and 0 reads as "fill the card exactly" — the free-memory reading is an instant, tier 0 is unmeasurable in advance, and the card ends at 1,053 MiB free.
- `CallLimits::route` -> **crates/marlowe-provider/src/ollama.rs :: OllamaDriver::request_body — `self.routing.model_for(limits.route)`, replacing the hardcoded `ModelRoute::Orchestrator` literal at line 300** | breaks: every child runs on the orchestrator model regardless of its profile — which is the shipped behaviour today, and the reason the per-role queue currently has a population of one.
- `CapabilityProfile::model_route (pinned in CONTRACTS §5:952, written at four sites, READ AT ZERO — verified: `model_route()` has no caller in the workspace)` -> **crates/marlowe-loop/src/engine.rs:794 :: Engine::run — `run.budget.call_limits(&run.spent, run.profile.model_route())`, which is its first reader ever** | breaks: instance #16 stands: `Engine::spawn` writes `ModelRoute::Worker` into every child profile (engine.rs:2654) and nothing consults it. Both ROADMAP item (4) (the role field) and item (5) (the per-role queue) key on a field with no reader.
- `Admission verdict (the whole enum)` -> **crates/marlowe-loop/src/engine.rs :: Engine::spawn — branches to spawn_refused on Refuse/RefuseSplit and proceeds otherwise; Admission::tag() is read by crates/marlowe-daemon/src/roster.rs :: RosterRecorder::append into the RunSpawned row** | breaks: the gate is decorative. Note the anti-#16 property: the verdict is not stored on a struct, it is a branch — deleting the branch deletes the only thing that reads it, and the mutation test catches that.
- `RunSummary::parent` -> **crates/marlowe-daemon/src/control_plane.rs :: ControlPlane::executing_runs** | breaks: `executing_runs` cannot distinguish a blocked ancestor from a working leaf and collapses into `live_runs`, which is the number that currently lies.
- `status_word(&RunStatus) exhaustiveness` -> **crates/marlowe-daemon/tests/run_status_words_reach_the_window.rs, and (as the single definition of the wire word) crates/marlowe-daemon/src/roster.rs::status_word's assertion against it** | breaks: a `WaitingCapacity` added by a later session serialises to a word `state_of` does not know, falls into its `other =>` arm, and renders to the user as the literal token `waiting_capacity` styled as a pause — the three-way mirror disagreeing silently, which is the failure this decision was asked to prevent.

### Rejected

- **`RunStatus::Queued { reason: QueueReason }` — AGENT-DIRECTORY §2a's "cheapest honest option"** - It is neither cheap nor honest, and the code says so. `roster.rs::status_word` reduces a status to its serde KEY (`serde_json::Value::Object(m) => m.keys().next()`), so `{"queued":{"reason":"capacity"}}` reaches the run table, `watch_client::state_of` and Session G's directory as the bare word `queued` — identical to the transient. The reason would be a field with no reader at the one surface it was added for, with a green serde round-trip test asserting its value: instance #16 in its purest form. Making it read requires teaching `status_word` to special-case one variant, i.e. a second decoder beside `JournalCheckpoints`, which roster.rs's own header refuses. And it is not free: `Queued` stops being a unit variant, its wire spelling changes from `"queued"` to an object, and `state_of("queued")` stops matching.
- **Add `RunStatus::WaitingCapacity { role, model }` to CONTRACTS §5 now, so Session G is a window rather than a contract change (the argument ROADMAP makes for item (4)'s role field)** - The role field's consumer is Session G; this variant's consumer is concurrent execution, which no session row owns. Nothing in C could produce it: `Engine::spawn` calls `self.run(child)` inline, `Routing::new` has zero production callers so there is one distinct model, and `NUM_PARALLEL=1` admits one request per model. A variant with no producer is `Channel::Agent`'s situation — which this project accepted once, deliberately, with the human's approval and a written note that it must not be read as a live path. Doing it a second time for a state whose producer is unscheduled trades a real instance-#16 for an imagined convenience. C ships the compile-time guard instead, so the later addition is loud.
- **Block inside `Engine::spawn` until a slot frees — the literal reading of "waits for one of the same type to finish"** - `Engine::spawn` runs on the thread that serves the conversation, and the daemon holds one connection for the whole of a turn (M3-DESIGN §6's first unanticipated finding). A capacity wait there freezes the surface with no indication why — CLAUDE.md's "heavy work never runs on the main daemon thread" — and costs M3-DESIGN §11's "conversation availability 100%", the milestone's own acceptance row. Under an inline spawn the waiting the human describes is already enforced by the call graph: a second worker cannot start until the first returns.
- **Derive capacity from `OLLAMA_MAX_LOADED_MODELS` / `OLLAMA_NUM_PARALLEL` / `OLLAMA_KEEP_ALIVE`** - AGENT-DIRECTORY §2 is explicit — "`/api/ps` is the measurement; the env vars are only declarations" — and on this machine `OLLAMA_MAX_LOADED_MODELS` is **unset**, so reading it yields nothing while Ollama's own default resolved to ≥ 3 (measured: all three roles co-resident at 10,849,836,070 B). An env var also describes the server's policy, not the card's state: it cannot see the desktop's 5,086 MiB of tier 0, which is the term that turns "10.0 GB of 16, leaving headroom" into 1,053 MiB free.
- **Set `OLLAMA_KEEP_ALIVE=-1` (or any global value) to satisfy "agents are kept warm"** - It reverses a recorded decision — STATE.md: set, then deliberately reverted, because "pinning 6.7 GB forever is the wrong trade for a trivial saving" — and it does so in the widest possible way: a global env var pins EVERY model on the machine, including ones this harness did not load, and `hybrid.rs::unload_resident_ollama_models` already records that Ollama gives no way to tell whose is whose. The narrower mechanism that the same reasoning permits is a **per-request** `keep_alive` in the body this harness sends, scoped to our models, revocable, and read by a line of code in `request_body`. That is a narrowing, and it still needs a `DECISIONS.md` entry.
- **A constant — `MAX_RESIDENT_MODELS = 3`, or a fixed byte reserve** - 3 is true only given this desktop's 5,086 MiB of tier 0, which is unmeasurable in advance and changed by a browser tab. STATE.md's open item `THREE CONSTANTS ENCODE A 16 GB CARD` is exactly this mistake one card size down, and `marlowe_net::io_concurrency()` is the project's pattern for the alternative: one derived definition every caller routes through. The reserve is supplied by the daemon (which knows the embedder's per-session size) and compared in the loop; neither side keeps a second copy.
- **Fail closed when residency cannot be read** - `vram.rs` reads free memory via `nvidia-smi`, which ships with the NVIDIA driver. Failing closed means no machine without one — an AMD card, a Mac, a CPU-only Ollama — can ever spawn a child, on exactly the "all consumer hardware" target STATE.md names as unsolved. Capacity is a performance control whose failure mode is slowness, not privilege, so the security argument for fail-closed does not apply; and the default is not silent, because `Admission::Unmeasured`'s tag is journalled on every `RunSpawned`.
- **Gate `Engine::condense_batch` on the same admission check, for symmetry** - A quarantined reader runs on the same model the parent is already using, in the same process, at zero marginal residency — so there is nothing to admit. Worse, a capacity check that can refuse layer 1 hands anyone who can raise VRAM pressure (launch a game; open enough browser tabs) a way to make quarantined reads fail, converting a resource condition into a containment-quality denial. `condense_batch` already fails closed on its own, returning a refusal string and no raw bytes.

### Tests

- `a_spawn_that_does_not_fit_is_refused_by_name_with_both_numbers_and_no_child_is_created` in `crates/marlowe-loop/tests/spawn_admission.rs`
  - asserts: With a fixed `CapacityHost` returning `{model: "marlowe-mini:4b-super", resident: false, size_bytes: 3_271_515_176, free_bytes: 1_104_150_528 /* 1,053 MiB, measured */}` and `Headroom::new(838_860_800)`, a scripted driver emitting `ModelStep::Spawn` produces: zero `EventKind::RunSpawned` in the recorder, a `ToolLine{verb:"spawn", target:"refused"}`, and a `[run blocked]` block in the parent's window containing the model TAG, the needed bytes and the free bytes. Anti-proxy note: if the gate were deleted the child WOULD be created, so the assertion is on the absence of a run rather than on the presence of a message.
  - red on: Make `capacity::admit` return `Admission::Admit` unconditionally — a child is created and `RunSpawned` appears. Separately: drop `free_bytes` from `Admission::explain` — the substring assertion on the second number fails.
- `a_resident_model_that_is_split_across_cpu_and_gpu_is_refused_even_though_it_is_loaded` in `crates/marlowe-loop/tests/spawn_admission.rs`
  - asserts: `Residency{resident: true, size_bytes: 5_832_064_368, size_vram_bytes: 3_000_000_000}` yields `Admission::RefuseSplit{gpu_permille: 514}`, and the refusal text carries the per-mille. This is the only test that distinguishes "never a CPU split" as a MEASUREMENT from the same words as a declaration, and it is where the degree/policy reconciliation is pinned.
  - red on: Change `Residency::fully_on_device` to `size_vram_bytes > 0` (any GPU presence admits) — the verdict becomes `Admit`. Also: return `resident` alone without consulting `size_vram_bytes` — same red.
- `a_machine_with_no_capacity_probe_still_spawns_and_the_journal_says_unmeasured` in `crates/marlowe-loop/tests/spawn_admission.rs`
  - asserts: With `Ports { capacity: None, .. }` the child IS created, and the `RunSpawned` payload carries `"admission": "unmeasured"`. This is the negative control for the two tests above — without it, a gate that refused everything unconditionally would pass both.
  - red on: Make `admit` return `Refuse` on `None` (fail closed) — the child is not created. Separately: stop writing the `admission` key into the `RunSpawned` payload — the fail-open becomes silent and the assertion on the payload fails.
- `a_headroom_of_zero_is_refused_at_construction` in `crates/marlowe-loop/src/capacity.rs (unit test)`
  - asserts: `Headroom::new(0) == Err(CapacityError::ZeroHeadroom)`, and there is no other constructor and no `Default`. Ledger #17 in the correct direction: the zero that would read as permissive cannot be built.
  - red on: Change `Headroom::new` to `Ok(Self(bytes))` unconditionally, or add `#[derive(Default)]`.
- `a_worker_call_names_the_worker_model_and_an_orchestrator_call_names_the_orchestrator` in `crates/marlowe-provider/tests/the_route_chooses_the_model.rs`
  - asserts: With `Routing::new("marlowe-dawn:9b-super", "marlowe-mini:4b-super", "marlowe-mini:2b")` — THREE DISTINCT NAMES, because with `Routing::uniform` (which is what production uses today) this test is vacuous and would pass on the broken build — `request_body(view, tools, CallLimits{route: ModelRoute::Worker, ..})["model"] == "marlowe-mini:4b-super"` and the `Orchestrator` case names the 9b. This is the test that ends instance #16 on `CapabilityProfile::model_route`.
  - red on: Restore the literal `self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator)` at ollama.rs:300 — the worker case names the 9b. Second mutation: build the test with `Routing::uniform` — the test still passes, which is why the three distinct names are part of the assertion and are stated in the test's own header.
- `the_status_line_counts_model_calls_and_not_stack_frames` in `crates/marlowe-daemon/tests/a_serial_tree_is_not_reported_as_parallel.rs`
  - asserts: A control plane seeded with a parent→child→grandchild chain, all `status: "running"`, reports `live_runs() == 3` and `executing_runs() == 1`. This is what stops the directory "telling the truth about intent and a lie about execution" — and `--status`'s `runs N live` is switched to print both numbers.
  - red on: Make `executing_runs` delegate to `live_runs` (or drop `RunSummary::parent` and count live rows) — it reports 3.
- `every_run_status_has_a_word_and_every_word_reaches_a_state_the_window_understands` in `crates/marlowe-daemon/tests/run_status_words_reach_the_window.rs`
  - asserts: For every `RunStatus` variant, `roster::status_word(&serde_json::to_value(v))` equals `marlowe_loop::run::status_word(v)` (the two derivations agree), and `watch_client::state_of(word)` is NOT the fallback `RunState::Paused{reason: word}`. THIS TEST IS RED ON THE CURRENT TREE — `waiting_approval`, `waiting_event` and `paused` all fall into `state_of`'s `other =>` arm today and render a raw wire token to the user — so it is not vacuous and its fix is three arms in `state_of`. Honest limit, stated in the test header: the compile error covers a variant ADDED (the risk this decision creates); a pinned `EVERY_WORD.len() == 8` beside it covers the list shrinking (#19); neither can prove the array was extended correctly.
  - red on: Add a variant to `RunStatus` — `marlowe_loop::run::status_word`'s exhaustive match fails to COMPILE, which is the build failure this decision promises in place of a silent three-way drift. Delete an arm from `state_of` — the corresponding variant hits the fallback and the assertion fails.
- `a_quarantined_read_is_never_refused_for_capacity` in `crates/marlowe-loop/tests/spawn_admission.rs`
  - asserts: With a `CapacityHost` that refuses every role, `condense_batch` still runs its quarantined child and the parent receives a validated `CondensedResult` — not a `QuarantineRefusal`. Layer 1 must not become deniable by raising VRAM pressure.
  - red on: Add the `admit` call to `condense_batch`'s child construction — the parent gets a refusal and the untrusted group goes undescribed.
- `the shipped binary prints the capacity reading (a command, not a unit test)` in `runs/m3c-admission/capacity.txt — produced by `target/release/marlowe.exe --status``
  - asserts: `--status` gains one line: `capacity  1053 MiB free · dawn:9b-super resident 1000‰ · mini:4b-super resident 1000‰ · mini:2b resident 1000‰`, and `runs  3 admitted · 1 executing`. The recorded baseline is this session's measurement (16,376 MiB total, 5,086 MiB held by the desktop before any model, 10,849,836,070 B of weights resident, 1,053 MiB free). Read from the SHIPPED binary, never from `cargo run --example`.
  - red on: There is no mutation for a printed number — which is why it is paired with the unit tests above rather than standing alone. What it catches that they cannot: a reading taken through `ollama list` (on-disk size) rather than `/api/ps` (`size_vram`) reports the three models at ~10.0 GB and the card as having headroom, which is AGENT-DIRECTORY §2's error reproduced by the instrument.

### Contract impact

**None.** Verified rather than assumed: `grep -n "SpawnRequest\|RunStatus\|Queued" docs/design/CONTRACTS.md` returns lines 910, 920–921 and 941 only. `RunStatus` is unchanged — no variant added, none renamed, the wire spelling of every existing variant identical, so `roster.rs`, `marlowe-view/src/run.rs::RunState` and `watch_client.rs:211` all keep matching. `CapabilityProfile` is unchanged: `model_route` is already pinned at CONTRACTS §5:952 and merely gains its first reader. `SpawnRequest` is untouched by this decision (the role field is ROADMAP item (4), a separate act — and note that §5 pins only `fn spawn(&self, req: SpawnRequest) -> RunId`, never the struct's fields). The four types that change — `CallLimits`, `Budget::call_limits`, `Ports`, `RunSummary` — appear nowhere in `CONTRACTS.md`; `LoopOutcome` appears nowhere either and is unchanged. `CHECKPOINT_VERSION` does not move, because `Checkpoint`'s shape is unchanged. What C *does* owe the contract is a sentence in §5 recording the decision itself: that `Queued` means constructed-not-yet-started, that capacity-waiting will be a distinct variant and never a reason on `Queued`, and that the variant lands with the concurrency that produces it — the same discipline §12.1 used when it pinned `ingest_external` and said in its own words that nothing calls it.

### Guarded

['crates/marlowe-loop/src/driver.rs — NOT TOUCHED BY THE RECOMMENDED SHAPE, and that is deliberate: `CapacityHost` goes in a new `crates/marlowe-loop/src/capacity.rs` because driver.rs is guarded for the memory and approval ports and capacity is neither. IF the human prefers the port to sit beside the other nine, that edit is §13-guarded and needs approval — say so before making it, and add a `DECISIONS.md` entry.', "crates/marlowe-loop/src/profile.rs — NOT TOUCHED. `model_route()` already exists at profile.rs:280 with zero callers; giving it a reader is a change in engine.rs, not here. Any temptation to add a role/model field to `CapabilityProfile` (for ROADMAP item (4)) IS a guarded edit and is not this decision's.", "crates/marlowe-permission/src/adjudicate.rs — NOT TOUCHED. The admission verdict is a function of a harness-chosen `ModelRoute` and a device reading; nothing model-supplied enters it, so it needs no adjudication today. The moment a model can NAME a role (item (4)), that stops being true and adjudicate.rs is where it lands — the human's, per AGENT-DIRECTORY §3 item 4."]

### For the human

["The fourth model role's name. Four were specified, three named; not guessed here, and admission is written over `ModelRoute`'s existing three arms so that adding a fourth is a compile error rather than a silent omission.", 'Whether the spawner-supplied role/level is a TARGET under ADR-023 (AGENT-DIRECTORY §3 item 4; ROADMAP item (4)). Today the gate reads `ModelRoute::Worker`, hardcoded by `Engine::spawn`, so nothing untrusted reaches it. The moment `run` carries a role, both a downgrade (make the system dumber before an attack) and an upgrade (exhaust budget) become attacker-useful, and `composes_spawn_targets` would need a fourth clause. Do not let that arrive as a side effect of this design.', "Whether concurrency is wanted at all, against `OLLAMA_NUM_PARALLEL=1`'s prefix-cache protection — AGENT-DIRECTORY §3 item 2 names it as the human's, and it is what decides whether `WaitingCapacity` ever gets a producer. A 148-byte prefix change already cost 1.45 s on this machine (STATE.md, 2026-08-27), so this is a measured trade and not a preference.", 'The `OLLAMA_KEEP_ALIVE` narrowing: the global env var stays reverted and `-1` is refused; "kept warm" becomes a per-request `keep_alive` value in the body this harness sends, chosen from measured free VRAM. That is a narrowing of a recorded decision, not an oversight and not a reversal — it needs a `DECISIONS.md` entry before it ships.', '`AGENT-DIRECTORY.md` §2\'s arithmetic is wrong and it is a human-authored brief: "10.0 GB of the card\'s 16, leaving headroom for the KV cache, the embedder and the reranker" against a measured 1,053 MiB free with all three roles resident. Since ADR-044 resolves the embedder\'s provider against free VRAM AT LOAD, co-residency of all roles means the embedder silently resolves to CPU with a correct-looking log line. Correcting a brief the human wrote is theirs to approve.', 'Adding `RunStatus::WaitingCapacity` to CONTRACTS §5 when concurrency lands — a pinned-contract act, deferred here rather than taken quietly, with the guard that makes deferring safe shipping in C.']

### Risks

["**A variant added later still drifts if the guard is deleted.** `status_word`'s exhaustive match is a compile error only while it exists; deleting the function turns nothing red except the one test that calls it. That is ledger #19's shape — a check whose subject can be removed — and it is only partly closed: the pinned `EVERY_WORD.len() == 8` catches the list shrinking, nothing catches the function being deleted wholesale. Stated rather than papered over.", '**`ollama list` understates a model\'s resident footprint by ~14%** (vram.rs\'s own recorded gap: 5.8 GB on disk, 6.6 GB resident at 32k context). `admit` therefore admits a not-yet-resident model that may then split. The `RefuseSplit` reading catches it on the NEXT spawn, not this one, and no multiplier is invented to close it — vram.rs refuses "a multiplier nobody measured" and so does this.', "**The reading is an instant.** Tier 0 held 5,086 MiB before any model loaded and is not ours to schedule; a game launching between the reading and Ollama's load makes the verdict wrong. `Headroom` is the whole mitigation, which is why zero is refused at construction rather than defaulted.", '**Instance #15 is one careless line away.** A `DegradedPath::CapacityUnmeasured` banner would fire on every spawn on every machine with no probe — a latch that fires on everything, which is what the trust-floor banner did. The verdict is therefore journalled on `RunSpawned` and surfaced once in `--status`, never bannered per spawn.', '**Instance #16 is the risk this design is most exposed to, because it is fixing one.** `Admission` must never be stored on a struct and reported; it is a branch in `Engine::spawn`, so deleting what reads it deletes the gate and the mutation test sees it. If a later session adds an `admission: Admission` field to `Run` or `RunSummary` "for the directory", that field is the next `inline_threshold_bytes`.', "**Instance #17's mirror image.** `Headroom(0)`, `MAX_RESIDENT_MODELS = 0`, `size_bytes: 0` — every zero on this path reads as permissive rather than restrictive, which is the opposite of the budget case and just as wrong. `admit` returns `gpu_permille = 0` for `size_bytes == 0` (refuse), and `Headroom::new(0)` is an error; both directions are asserted.", "**Reading residency costs an HTTP round trip on the turn thread**, once per spawn, bounded by `http::get_json`'s 5 s deadline. That is the same cost `hybrid.rs` already pays and it is not on the scored path — but it is on the thread that serves the conversation, so it must never grow into a poll, and it must not run per loop iteration.", "**`Probe::Fixed`'s discipline must carry over.** vram.rs is explicit that nothing in the product constructs a `Fixed` probe — it exists so the exhaustion path can be driven deliberately. The fixed `CapacityHost` used by the tests above is the same shape and must acquire the same rule, or a config knob appears that lets someone declare a card size the machine does not have."]
