# ADR-067 · Admission control refuses; it does not queue — and `RunStatus::Queued` does not move

**Status:** PROPOSED — needs the human's approval. DESIGN ONLY, NO CODE.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | nothing. It answers AGENT-DIRECTORY §2/§2a and ROADMAP M3 Session C item (5) by **declining** the shape both of them reach for first |
| **Depends on** | ADR-023 (the latch, and `composes_spawn_targets`), ADR-039/ADR-041 (the quarantined reader, which §2.6 deliberately exempts), ADR-044 (`auto` resolves the embedder against free VRAM *at load*), ADR-045 §4 (`ReserveReading`'s tier table and its `reason`), ADR-062 (the discipline of pinning a port and saying in the ADR that nothing calls it), M3-DESIGN §6 (the daemon holds one connection per turn), §7, §11 |
| **Contract change** | **YES, and it is part of why the status line reads as it does.** `EventKind` gains `SpawnRefused`. `CONTRACTS.md` line 113: *"Closed set. Adding a kind is a minor version bump; changing one is major."* Nothing else moves — `RunStatus` gains no variant and no wire spelling changes |
| **§13-guarded files** | **None touched.** Verified against `python .claude/hooks/protect-boundaries.py --list-protected`: `driver.rs`, `profile.rs`, `adjudicate.rs`, `egress.rs`, `taint.rs`, `scope/`, `journal.rs`, `signature.rs`, `memory.rs`, `mcp.rs`, `pin.rs`, `steer.rs`, `provenance.rs`, `trust.rs`, `persona/`. The new port goes in a NEW `crates/marlowe-loop/src/capacity.rs`, not `driver.rs`, for exactly this reason. `crates/marlowe-journal/src/event.rs` is **not** on the list; `journal.rs` and `signature.rs` are, and are untouched |
| **Code change** | **None taken.** This is a design record; the build is M3 Session C's, after approval |
| **Adversarial verdict on the design this ADR records** | **sound-with-fixes**, with one fatal finding. §6 carries it |

---

## 1 · The question, and what the code answers

AGENT-DIRECTORY §2a asks what a spawn does when the card is full, and offers *"the cheapest honest
option"* — a reason field on `RunStatus::Queued`. ROADMAP M3 Session C item (5) asks for a per-role
queue. **Both presuppose a wait. There is nothing in the shipped product that can wait, and the
reason field cannot be read at the surface it was proposed for.** So the decision is the narrow one:
**admission control refuses at the spawn site; it does not queue; `RunStatus` does not move in
Session C.**

### 1.1 · Nothing can produce a wait — four reads, not an argument

| Claim | Established by |
|---|---|
| `Engine::spawn` runs its child **inline**, on the calling thread | `crates/marlowe-loop/src/engine.rs:2892` — `self.run(&mut child_run, &mut child_state, &mut child_provenance, &mut child_ports)`. At most one model call is in flight per process |
| There is exactly **one distinct model** in the product | `grep -rn "Routing::new\|Routing::uniform"`: every production construction is `Routing::uniform` — `agent.rs:47`, `daemon.rs:1263`, `:1338`, `:1503`, `:1889`, `:1976`. `Routing::new` has **one** non-test caller and it is `Routing::uniform` itself, `routing.rs:102` |
| The role never reaches the wire | `crates/marlowe-provider/src/ollama.rs:300` — `let model = self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator).to_string();`, a literal |
| `CapabilityProfile::model_route()` has **zero call sites in the workspace** | `grep -rn "model_route()" --include=*.rs crates/` returns **nothing at all** — not even the definition, which reads `model_route(&self)` at `profile.rs:280`. Written at four sites, read at none |

A per-role queue keyed on a field with no reader, over a population of one model, drained by a loop
that cannot run two things at once, is three declared controls stacked on each other. It is instance
#16 three deep.

### 1.2 · The reason field loses at the exact surface it was added for

`crates/marlowe-daemon/src/roster.rs:71` reduces a serialized status to its serde **key**:

```rust
fn status_word(v: &serde_json::Value) -> Option<String> {
    match v {
        serde_json::Value::String(s) => Some(s.clone()),
        serde_json::Value::Object(m) => m.keys().next().cloned(),
        _ => None,
    }
}
```

So `{"queued":{"reason":"capacity"}}` reaches the run table, `watch_client::state_of` and Session G's
directory as the bare word `queued` — byte-identical to the transient. The reason would be a field
with no reader at the one place it exists to be read, with a green serde round-trip test asserting
its value. And it is not free: `Queued` stops being a unit variant, its wire spelling changes from
`"queued"` to an object, and `state_of("queued")` (`watch_client.rs:210`) stops matching.

---

## 2 · The decision

### 2.1 · One definition of residency — `crates/marlowe-provider/src/ollama_ps.rs` (NEW)

Two things already answer *"what is on this card"*: `hybrid.rs:313 unload_resident_ollama_models`
reads `/api/ps` over HTTP (`:315` iterates `ps["models"]`), and `vram.rs`'s `Reserve::read`
(`crates/marlowe-memory/src/cue/dense/vram.rs:188`) asks the same question through the `ollama ps`
CLI plus `ollama list`. A third reader is the project's most-logged shape and the reason
`io_concurrency()` and `blocks_composed_targets` exist. So the parse is extracted, not added:

```rust
//! What Ollama currently holds on this card. ONE definition: `hybrid.rs`'s eviction path and the
//! spawn admission gate read the same parse. `/api/ps` lists ONLY resident models — a model that
//! is not loaded has no row, and no field of this struct can describe it.
pub struct Resident {
    pub model: String,
    /// `/api/ps` `size`: the runner's total bytes.
    pub size_bytes: u64,
    /// `/api/ps` `size_vram`: how many of those are ON the device.
    pub size_vram_bytes: u64,
}

/// `None` means the question could not be answered — no Ollama, no reply. NOT the same answer as
/// an empty `Vec` ("Ollama is up and holds nothing"), the distinction `vram::Probe::free_bytes`
/// already draws between `None` and `Some(0)` (vram.rs:55).
pub fn resident_models() -> Option<Vec<Resident>>;

/// On-disk bytes from `ollama list`, for a model that is NOT resident. A KNOWN UNDERSTATEMENT:
/// vram.rs:156 records `marlowe-red:9b` at 5.8 GB on disk and 6.6 GB resident at 32k context,
/// ~+14%. No multiplier is invented — vram.rs:160 refuses "a multiplier nobody measured" and so
/// does this.
pub fn on_disk_bytes(model: &str) -> Option<u64>;
```

`unload_resident_ollama_models` is refactored to iterate `resident_models()`. **That is what makes it
one definition rather than two: break the parse and `hybrid`'s own eviction test goes red as well as
the admission tests.**

### 2.2 · `crates/marlowe-loop/src/capacity.rs` (NEW — deliberately not `driver.rs`)

```rust
use crate::profile::ModelRoute;

/// Where a size came from, because the two sources answer different questions and one of them is
/// known to be low. The verdict names it; the journal records it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SizeSource {
    /// `/api/ps` `size`, read while the model is resident. Authoritative.
    ApiPsResident,
    /// `ollama list`, read for a model that is not loaded. Understates by ~14% (vram.rs:156).
    OllamaListOnDisk,
}

/// One reading of model residency, taken at an instant.
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
    /// THE ONLY WAY IN. Private fields, no `Deserialize`; if one is ever needed it routes through
    /// here with `#[serde(try_from = "…")]` — ledger #12, serde is a way in.
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

    /// THE DEGREE, per-mille, so no float equality reaches a decision path and the number the user
    /// reads is the number the record carries. 1000 = fully on the GPU.
    /// **REPORTING ONLY — see §3. The policy below compares bytes, not this.**
    pub fn gpu_permille(&self) -> u32 {
        if self.size_bytes == 0 { return 0; }
        ((u128::from(self.size_vram_bytes) * 1000) / u128::from(self.size_bytes)) as u32
    }

    /// The POLICY over the degree, all-or-nothing. STATE.md's "42/48 layers is healthy" is about
    /// the shelved llama.cpp hybrid serving tier 1; the agent pool is not that.
    pub fn fully_on_device(&self) -> bool {
        self.resident && self.size_bytes > 0 && self.size_vram_bytes == self.size_bytes
    }

    pub fn model(&self) -> &str { &self.model }
    pub fn free_bytes(&self) -> u64 { self.free_bytes }
    pub fn size_source(&self) -> SizeSource { self.size_source }
}

/// Spare device memory a spawn must leave behind, WITH THE BRANCH THAT PRODUCED IT.
/// Shaped after `vram::ReserveReading` (vram.rs:179) for the same stated reason: several branches
/// return the same number, so the number cannot say which one answered and the reason has to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Headroom { bytes: u64, reason: String }

impl Headroom {
    /// Zero is refused at construction. A limit written as zero reads as "fill the card exactly".
    /// Ledger #17 inverted: on the budget path a zero meant "already exhausted" and read as
    /// permission withheld; here it would mean "no reserve" and read as permission granted.
    pub fn new(bytes: u64, reason: String) -> Result<Self, CapacityError> {
        if bytes == 0 { return Err(CapacityError::ZeroHeadroom); }
        Ok(Self { bytes, reason })
    }
    pub fn bytes(&self) -> u64 { self.bytes }
    pub fn reason(&self) -> &str { &self.reason }
}

/// The verdict.
///
/// **THERE IS NO `Queue` VARIANT AND ITS ABSENCE IS THE DECISION** (§1.1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Admission {
    Admit  { model: String, marginal_bytes: u64, source: SizeSource },
    Refuse { model: String, needs_bytes: u64, source: SizeSource,
             free_bytes: u64, headroom_bytes: u64, headroom_reason: String },
    /// Resident and split across CPU and GPU. Measured, not declared.
    RefuseSplit { model: String, on_device_bytes: u64, size_bytes: u64, gpu_permille: u32 },
    /// No reading, OR a not-resident model whose footprint no source could supply.
    /// FAIL OPEN, argued: capacity is a performance control whose failure mode is slowness, not
    /// privilege. Failing closed stops every machine with no `nvidia-smi` — an AMD card, a Mac —
    /// from spawning at all, on the "all consumer hardware" target STATE.md names. Not silent:
    /// journalled on every spawn.
    Unmeasured { why: String },
}

impl Admission {
    /// The wire tag on the journal row. Stable: a journal query greps for it.
    pub fn tag(&self) -> &'static str; // admitted | refused_no_room | refused_cpu_split | unmeasured
    /// Harness-authored, one sentence, carrying EVERY number the verdict holds. This string is
    /// what `spawn_refused` is called with, so the branch is the reader.
    pub fn explain(&self) -> String;
    /// The journal payload. Every field of every variant appears here.
    pub fn payload(&self, role: ModelRoute) -> serde_json::Value;
}

/// THE WHOLE DECISION, AS A PURE FUNCTION OF A READING. One definition, three consumers:
/// `Engine::spawn` branches on it, `spawn_refused` journals `payload()`, `--status` renders the
/// reading behind it. The shape `blocks_composed_targets` already has.
pub fn admit(reading: Option<&Residency>, headroom: &Headroom) -> Admission {
    let Some(r) = reading else {
        return Admission::Unmeasured { why: "no residency reading was available".into() };
    };
    if r.resident && !r.fully_on_device() { return Admission::RefuseSplit { /* … */ }; }

    // A NOT-RESIDENT MODEL WHOSE SIZE NOBODY COULD SUPPLY IS UNMEASURED, NEVER `needs = 0`.
    // `/api/ps` has no row for it; a zero here reads as "costs nothing" and admits. This guard is
    // the fatal finding of §6.1 and it is the difference between a gate and a decoration.
    if !r.resident && r.size_bytes == 0 {
        return Admission::Unmeasured { why: format!(
            "{} is not loaded and neither `/api/ps` nor `ollama list` reported a size", r.model) };
    }

    // A resident model costs nothing more: Ollama shares weights across requests to the same
    // model, so "three workers of one role" multiplies the KV cache, not the weights.
    let needs = if r.resident { 0 } else { r.size_bytes };
    if needs.saturating_add(headroom.bytes()) > r.free_bytes { return Admission::Refuse { /* … */ }; }
    Admission::Admit { model: r.model.clone(), marginal_bytes: needs, source: r.size_source }
}

pub trait CapacityHost {
    fn residency(&mut self, route: ModelRoute) -> Option<Residency>;
}
```

### 2.3 · The port is REQUIRED and NAMED, never `Option`

```rust
// crates/marlowe-loop/src/engine.rs
pub enum CapacityPort<'a> {
    Enforced(&'a mut dyn CapacityHost),
    /// This build does not gate spawns on capacity. **A STATED CHOICE, not an omission** —
    /// `vram::Probe`'s and `Tier1Runtime`'s discipline: a variant that kept compiling would leave
    /// every call site meaning "unenforced" BY OMISSION.
    Unenforced,
}
```

**Blast radius, measured this session rather than guessed: `grep -rn "Ports {" --include=*.rs
crates/ | wc -l` → 70, across 24 files.** Every one becomes a compile error that has to state which
it means. `Engine::spawn`'s child `Ports` (`engine.rs:2885`, where `memory: None` is hardcoded) and
`condense_batch`'s (`engine.rs:2269`) both pass `Unenforced` — §2.6.

### 2.4 · The production implementation, in the only crate that can hold it

Verified from `Cargo.toml`: `marlowe-provider` does not depend on `marlowe-memory`; `marlowe-loop`
depends on neither. The residency half (`/api/ps`) is reachable only from `marlowe-provider`; the
free-VRAM half (`vram::Probe::free_bytes`, `crates/marlowe-memory/src/cue/dense/vram.rs:55`) only
from `marlowe-memory`. **Only `marlowe-daemon` sees both.** Without naming this, the shipped daemon
builds an unenforced port, every verdict is `Unmeasured`, and the gate exists only in test doubles.

```rust
// crates/marlowe-daemon/src/capacity.rs (NEW)
pub struct OllamaCapacity { endpoint: LocalEndpoint, routing: Routing, probe: vram::Probe }

impl marlowe_loop::CapacityHost for OllamaCapacity {
    fn residency(&mut self, route: ModelRoute) -> Option<Residency> {
        let model = self.routing.model_for(route).to_string();
        let free = self.probe.free_bytes()?;                      // one definition
        let ps = marlowe_provider::ollama_ps::resident_models()?; // one definition
        match ps.iter().find(|r| r.model == model) {
            Some(r) => Residency::new(model, true, r.size_bytes,
                                      SizeSource::ApiPsResident, r.size_vram_bytes, free).ok(),
            None => {
                let d = marlowe_provider::ollama_ps::on_disk_bytes(&model).unwrap_or(0);
                Residency::new(model, false, d, SizeSource::OllamaListOnDisk, 0, free).ok()
            }
        }
    }
}
```

`Headroom` is constructed at exactly one site, `marlowe_daemon::capacity::headroom_for(...)`, and
carries its reason — *"one embedder session, 838,860,800 B, so ADR-044's `auto` can still resolve to
CUDA"*. **`crates/marlowe-daemon/src/daemon.rs` is under concurrent edit by other sessions as this is
written**: the wiring is two lines in it, one constructor beside the driver build and one field in
the `Ports` literal in `Daemon::ask_streaming_with`. Coordinate; do not race.

### 2.5 · The refusal is JOURNALLED, and that is the contract change

`Engine::spawn_refused` (`crates/marlowe-loop/src/engine.rs:3112`) emits a `TurnEvent::ToolLine`,
calls `tool_error`, and **appends nothing to the journal**. So:

* `EventKind::SpawnRefused` is added to `crates/marlowe-journal/src/event.rs` (not §13-guarded;
  `journal.rs` and `signature.rs` are, and are untouched).
* `spawn_refused` gains a `payload: serde_json::Value` argument and records it. `RosterRecorder`
  needs no arm — its `match kind` ends in `_ => {}`.
* The row carries `admission.payload(role)`:
  `{role, model, verdict, needs_bytes, size_source, free_bytes, headroom_bytes, headroom_reason,
  gpu_permille}`.
* `Admit` and `Unmeasured` ride on the existing `RunSpawned` payload under key `"admission"`.

**This is what makes the egress-style measurement possible** — *"N spawn decisions since the flip, M
refused"*, out of the signed journal rather than argued — and it is what gives every `Admission`
field a production reader (§3).

### 2.6 · What does NOT get the gate

`condense_batch` (`engine.rs:2269`'s child `Ports`) passes `CapacityPort::Unenforced`. A quarantined
reader runs on the model the parent is already using, at zero marginal residency; there is nothing to
admit. Worse, a capacity check that can refuse layer 1 hands anyone able to raise VRAM pressure — a
game, enough browser tabs — a way to make quarantined reads fail, **converting a resource condition
into a containment-quality denial**. The ordinary spawned child (`engine.rs:2885`) is also
`Unenforced`: it was admitted at its own spawn site, and re-checking inside would be a second answer
to a question already answered.

### 2.7 · `CallLimits::route`, stated honestly

```rust
// crates/marlowe-loop/src/budget.rs — CallLimits appears nowhere in CONTRACTS.md.
pub struct CallLimits { pub max_output_tokens: u64, pub route: ModelRoute }
impl Budget { pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits { … } }
```

Reader: `crates/marlowe-provider/src/ollama.rs:300`, replacing the hardcoded
`self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator)`. Call site: `engine.rs:794`,
`run.budget.call_limits(&run.spent, run.profile.model_route())` — **the first caller
`CapabilityProfile::model_route()` has ever had** (§1.1: zero today).

**Stated here, in the test header, and in STATE.md, not glossed: this changes no product behaviour
today.** `Routing::uniform` is the only production constructor, so all three routes return one tag.
A three-model `Routing` needs config the daemon does not have; that is Session G's window. **Recorded
now rather than discovered then:** `OllamaDriver::new` (`ollama.rs:242`) caches
`ModelCapability::unmeasured(routing.model_for(…))` — a second place naming a model, wrong for two of
three routes the moment routing is real.

---

## 3 · Where every field is READ — and the three that are dropped

Instance #16 is this project's most-repeated defect and this decision is fixing one, so the table is
the load-bearing part of the ADR.

| Field | The function that reads it | What breaks if the reader goes |
|---|---|---|
| `Residency::{size_bytes, size_vram_bytes}` | `capacity.rs :: Residency::fully_on_device` — the policy, and it compares **bytes** | "never a CPU split" becomes a declaration; a 60/40 model runs at a tenth of the speed and nothing reports why |
| `Residency::resident` | `capacity.rs :: admit` — chooses `needs = 0` vs `needs = size_bytes` | a resident model is charged its weights twice, so the second worker of the same role is refused on a card with room |
| `Residency::free_bytes` | `capacity.rs :: admit` — the `needs + headroom > free` comparison | admission has no ceiling; Ollama answers by evicting something, silently, in a log that cannot see us |
| `Residency::size_source` | `Residency::new` (rejects `resident && != ApiPsResident`), `Admission::explain`, `Admission::payload` | the ~14% understatement is laundered into a confident refusal |
| `Residency::model` | `Admission::explain`, into `spawn_refused`'s text | the refusal names a role; `ollama pull` and `ollama ps` both take a tag, so the user cannot act on it |
| `Headroom::bytes` | `capacity.rs :: admit` (the comparison), `Headroom::new` (the zero refusal) | headroom becomes a `u64` that can be `0`, and `0` reads as "fill the card exactly" |
| `Headroom::reason` | `Admission::explain`, `Admission::payload` | several branches return the same number and it cannot say which answered — `ReserveReading`'s recorded lesson, re-committed |
| `Admission` (the enum) | `Engine::spawn` branches on it; `spawn_refused` journals `payload()` | the gate is decorative — and note the anti-#16 property: it is a **branch**, not a stored field, so deleting what reads it deletes the gate and test 1 sees that |
| every numeric field of every `Admission` variant | `Admission::explain` (into the user-visible refusal) **and** `Admission::payload` (into the `SpawnRefused` / `RunSpawned` row) | `inline_threshold_bytes` at eight fields, in a design filed under a heading naming `inline_threshold_bytes` |
| `Unmeasured::why` | `Admission::payload`; test 4 asserts the string reaches the row | the fail-open becomes silent, which is the only thing that would make it wrong |
| `CallLimits::route` | `ollama.rs:300 :: OllamaDriver::request_body` | every child runs on the orchestrator model — today's behaviour |
| `CapabilityProfile::model_route()` | `engine.rs:794`, via `Budget::call_limits` | its first reader ever; without it ROADMAP items (4) and (5) both key on a field nothing consults |
| `RunSummary::parent` (NEW, at `crates/marlowe-daemon/src/daemon.rs:302`) | `ControlPlane::executing_runs` | `executing_runs` collapses into `live_runs`, which is the number that currently lies |

### 3.1 · Dropped, for lack of a reader — which is the preferred outcome

* **`Admission::admitted() -> bool` is DROPPED.** The reviewed design defined it and then said
  `Engine::spawn` branches on `Refuse | RefuseSplit` directly. A predicate with no call site is the
  defect this table exists to prevent; `Engine::spawn` matches the enum.
* **A `DegradedPath::CapacityUnmeasured` banner is DROPPED before it is written.** It would fire on
  every spawn on every machine with no `nvidia-smi` — a latch that fires on everything, which is
  precisely what the trust-floor banner did (instance #15). The verdict is journalled per spawn and
  surfaced once in `--status`; it is never bannered.
* **`gpu_permille` is kept but demoted in writing.** It is read by `explain` and `payload` and
  printed in `--status`. **It does not gate anything** — `fully_on_device` compares bytes. Saying so
  here is what stops a later session citing it as the enforcement.

---

## 4 · Why the alternatives lost

**`RunStatus::Queued { reason: QueueReason }` — AGENT-DIRECTORY §2a's "cheapest honest option".**
It is neither cheap nor honest, and §1.2 is the reason: `roster.rs:71` keeps the serde key and
discards the object, so the reason is unreadable at the run table, at `state_of`, and in Session G's
directory. Making it readable means teaching `status_word` to special-case one variant — a second
decoder beside `JournalCheckpoints`, which `roster.rs`'s own header refuses. And the wire spelling of
`Queued` changes from `"queued"` to an object, breaking `state_of("queued")` at
`watch_client.rs:210`.

**Add `RunStatus::WaitingCapacity { role, model }` to CONTRACTS §5 now, so Session G is a window
rather than a contract change.** Nothing in C could produce it (§1.1). A variant with no producer is
`Channel::Agent`'s situation — accepted once, deliberately, with the human's approval and a written
note that it must not be read as a live path (ADR-062 §4, M3-D1). **Twice is a habit.** C ships the
compile-time guard instead (§5, test 7), so the later addition is loud.

**Block inside `Engine::spawn` until a slot frees — the literal reading of "waits for one of the same
type to finish".** `Engine::spawn` runs on the thread that serves the conversation, and M3-DESIGN
§6's first unanticipated finding is that *"the daemon is serial… one connection is held for the whole
of a turn"*. A wait there freezes the surface with no indication why — CLAUDE.md's *"heavy work never
runs on the main daemon thread"* — and costs M3-DESIGN §11's **conversation availability 100%**, the
milestone's own acceptance row. Under an inline spawn the waiting the human describes is already
enforced by the call graph: a second worker cannot start until the first returns.

**Derive capacity from `OLLAMA_MAX_LOADED_MODELS` / `OLLAMA_NUM_PARALLEL`.** AGENT-DIRECTORY §2 is
explicit that *"`/api/ps` is the measurement; the env vars are only declarations"*, and on this
machine `OLLAMA_MAX_LOADED_MODELS` is unset while Ollama's own default resolved to at least three —
the session that produced this design measured all three roles co-resident at 10,849,836,070 B. An
env var also describes the server's policy, not the card's state: it cannot see the desktop's tier 0,
which is the term that turns *"10.0 GB of 16, leaving headroom"* into 1,053 MiB free.

**A constant — `MAX_RESIDENT_MODELS = 3`, or a fixed byte reserve.** Three is true only given this
desktop's tier-0 occupancy, which is unmeasurable in advance and changed by a browser tab. STATE.md's
open item *THREE CONSTANTS ENCODE A 16 GB CARD* is this mistake one card size down;
`marlowe_net::io_concurrency()` is the project's pattern for the alternative — one derived definition
every caller routes through. The reserve is supplied by the daemon, which knows the embedder's
per-session size, and compared in the loop; neither side keeps a second copy.

**Fail closed when residency cannot be read.** `vram.rs:9` records why the probe is `nvidia-smi`: it
ships with the driver, so its absence is close to *"there is no NVIDIA card"*. Failing closed means no
AMD card, no Mac, no CPU-only Ollama can ever spawn a child, on exactly the *all consumer hardware*
target STATE.md names as unsolved. Capacity is a performance control whose failure mode is slowness,
not privilege, so the security argument for fail-closed does not reach it — and the fail-open is
journalled on every spawn, not silent.

**Set `OLLAMA_KEEP_ALIVE=-1` to satisfy "agents are kept warm".** It reverses a recorded decision in
the widest possible way — STATE.md records the variable as set and then deliberately reverted,
because *"pinning 6.7 GB forever is the wrong trade for a trivial saving"* — and a global pins every
model on the machine, including ones this harness did not load, which `hybrid.rs` already records
Ollama gives no way to distinguish. **The narrower per-request `keep_alive` is not taken here
either; see §8.**

---

## 5 · Tests, each with the mutation that reddens it

No test below reads the same whether or not the mechanism works. Where one would, it is named as such
and paired.

1. **`crates/marlowe-loop/tests/spawn_admission.rs :: a_spawn_that_does_not_fit_is_refused_by_name_with_every_number_and_no_child_is_created`.**
   Fixed host returning `Residency::new("marlowe-mini:4b-super", false, 3_271_515_176,
   SizeSource::OllamaListOnDisk, 0, 1_104_150_528)` and `Headroom::new(838_860_800, …)`. Asserts:
   **zero `RunSpawned`**, one `SpawnRefused` whose payload carries all six numbers, a
   `ToolLine{verb:"spawn", target:"refused"}`, and a `[run blocked]` block naming the tag.
   *Anti-proxy: the assertion is the absence of a run, not the presence of a message.*
   Mutations: `admit` returns `Admit` unconditionally → a child appears; drop `free_bytes` from
   `explain()` → the substring assertion fails; delete the `record` call in `spawn_refused` → the
   payload assertion fails.
2. **`… :: a_model_that_is_not_loaded_and_has_no_reported_size_is_unmeasured_not_free`.**
   `resident: false, size_bytes: 0` yields `Unmeasured`, **not** `Admit`. This is the test the
   reviewed design lacked and it is the one that matters most — it is the difference between a gate
   and a decoration (§6.1). Mutation: remove the guard so `needs = if resident {0} else {size_bytes}`
   stands alone → the verdict becomes `Admit` and the assertion fails.
3. **`… :: a_resident_model_split_across_cpu_and_gpu_is_refused_even_though_it_is_loaded`.**
   `Residency::new(…, true, 5_832_064_368, ApiPsResident, 3_000_000_000, …)` → `RefuseSplit` with
   `gpu_permille == 514`, and the per-mille in the text. Mutation: `fully_on_device` →
   `size_vram_bytes > 0` → `Admit`.
4. **`… :: a_build_with_capacity_unenforced_still_spawns_and_the_journal_says_so`.** With
   `CapacityPort::Unenforced` the child **is** created and `RunSpawned` carries
   `"admission":"unmeasured"` with its `why`. **This is the negative control: without it, a gate that
   refused everything unconditionally would pass 1–3.** Mutations: fail closed → no child; stop
   writing the `admission` key → the fail-open becomes silent and the assertion fails.
5. **`crates/marlowe-loop/src/capacity.rs` unit tests.** `Headroom::new(0, _) == Err(ZeroHeadroom)`,
   no `Default`, no second constructor; `Residency::new` refuses `size_vram > size`,
   `resident && size == 0`, and `resident && source != ApiPsResident`. Mutations: return `Ok`
   unconditionally; add `#[derive(Default)]`; make the fields `pub`.
6. **`crates/marlowe-provider/tests/the_route_chooses_the_model.rs :: a_worker_call_names_the_worker_model`.**
   Built with `Routing::new("marlowe-dawn:9b-super", "marlowe-mini:4b-super", "marlowe-mini:2b")` —
   **three distinct names, stated in the test header, because with `Routing::uniform` (which is what
   production uses) the test is vacuous and passes on the broken build.** Mutation: restore the
   `Orchestrator` literal at `ollama.rs:300` → the worker case names the 9b.
7. **`crates/marlowe-daemon/tests/every_status_word_reaches_a_state_the_window_understands.rs`.**
   Pin the wire alphabet **by hand**, independent of every producer:
   `pub const EVERY_STATUS_WORD: [&str; 15]` in `roster.rs` = the 8 `RunStatus` serde keys
   (`run.rs:203-212`) + `cancelling` (`control_plane.rs:477`) + `interrupted` (`:137`) + `unknown`
   (`:257`, `:294`) + `adopted` / `detached` / `terminated` (`durable.rs:426-428`) + `no_checkpoint`
   (`engine.rs:2491`). Asserts (a) `state_of(w)` is never the `other =>` fallback
   (`watch_client.rs:224`) for any `w`; (b) a new exhaustive `marlowe_loop::run::status_word(v)`
   returns a member for every `RunStatus` variant; (c) `OrphanOutcome::verb()` returns a member for
   every variant; (d) `roster::status_word(&to_value(v))` agrees with `run::status_word(v)`.
   **RED ON THE CURRENT TREE**: `waiting_approval`, `waiting_event`, `paused` and all four fate words
   hit the fallback today and render to the user as raw wire tokens.
   Mutations: add a `RunStatus` variant → `run::status_word`'s exhaustive match **fails to compile**;
   add a fate → (c) red; delete a `state_of` arm → (a) red; **shrink the pinned array → (b) or (c)
   red, because the array is not derived from what it checks** — instance #19, closed by pinning the
   set from outside the set.
   Two notes that must be in the header or it reads as two definitions: `roster::status_word` is a
   **decoder** over arbitrary JSON (its domain includes payloads that are not a `RunStatus` at all)
   and `run::status_word` is the **definition**; (d) asserts the decoder agrees with the definition
   on the definition's whole domain. `roster::status_word` is private today and becomes `pub(crate)`
   for this. And `run::status_word` **does not exist yet** — `grep -rn "fn status_word"` returns only
   `roster.rs:71`.
8. **`crates/marlowe-daemon/tests/a_serial_tree_is_not_reported_as_parallel.rs`.** A
   parent→child→grandchild chain, all `running`: `live_runs() == 3` (`control_plane.rs:213` counts
   rows whose status is literally `"running"`), `executing_runs() == 1`. **Second case:** a parent
   whose only child settled as `terminated` reports `executing_runs() == 1`, because
   `is_terminal_word` (`roster.rs:59`) matches only `completed | failed | cancelled` while
   `RunCompleted` writes the fate word into the child's row. Mutations: delegate `executing_runs` to
   `live_runs` → 3; revert terminality to the three-word list → 0 on the second case.
   Files, cited correctly: `RunSummary` gains `parent: Option<String>` at
   **`crates/marlowe-daemon/src/daemon.rs:302`** (**not** `control_plane.rs`), set in `roster.rs`'s
   `RunSpawned` arm where both ids are already in hand; `executing_runs` on `ControlPlane`; a field
   beside `pub live_runs: usize` at **`protocol.rs:400`**; the print at **`agent.rs:648`**
   (`writeln!(out, "  runs        {} live", r.live_runs)`) becomes `runs  3 live · 1 executing`.
   *The reviewed design wrote this line two ways — `3 live · 1 executing` in one place and
   `3 admitted · 1 executing` in another. `live` is the word, because `live_runs` is the field it
   prints.*
9. **The command that prints a number, on the SHIPPED binary** — `runs/m3c-admission/capacity.txt`.
   `--status` gains `capacity  1053 MiB free · dawn:9b-super 1000‰ · mini:4b-super 1000‰ ·
   mini:2b 1000‰`, baselined against the design session's measurement (16,376 MiB total, 5,086 MiB
   held by the desktop before any model loaded, 10,849,836,070 B of weights resident, 1,053 MiB
   free). **There is no mutation for a printed number** and it is therefore never listed alone. What
   it catches that the unit tests cannot: a reading taken through `ollama list` rather than `/api/ps`
   reports the three models at ~10.0 GB and the card as having headroom — AGENT-DIRECTORY §2's
   arithmetic error reproduced by the instrument.
10. **And the one that proves the PRODUCTION path can refuse, which no unit test can.**
    `MARLOWE_CAPACITY_HEADROOM_BYTES=12884901888 target/release/marlowe.exe` → one `run` spawn on
    this box → a refusal in the transcript and **exactly one `SpawnRefused` row in the signed
    journal**, printed. Recorded in `runs/m3c-admission/live-refusal.txt`. **Without this, the gate's
    only exercise is a test double and §6.1 recurs.** The env var is a measurement-only override on
    `headroom_for`, inheriting `Probe::Fixed`'s rule verbatim (`vram.rs:38` — *"not a configuration
    knob and nothing in the product constructs one"*): nothing in the product sets it, and it never
    becomes a way to declare a card the machine does not have.

**What is deliberately NOT proposed.** The reviewed design listed
`a_quarantined_read_is_never_refused_for_capacity`. It reads identically on a build with no capacity
code at all, and its only stated mutation *adds* the coupling it forbids — instance #15 with the
mutation pointing the wrong way. §2.6 states the exemption in prose instead, which is the honest form
of that claim.

---

## 6 · The adversarial pass, recorded rather than hidden

The design was reviewed adversarially before this ADR was written. **Verdict: `sound-with-fixes`.**
Eleven defects, one fatal. The fixes are folded into §2–§5 above; what follows is what nearly
shipped, because an ADR that reads as though the first draft were right is worth less than one that
shows what it had to survive.

### 6.1 · THE FATAL FINDING: the refusal branch had no producer for the field it decided on

The reviewed design documented `Residency` as *"`GET /api/ps` for `size`/`size_vram`"*. **`/api/ps`
lists only RESIDENT models** — `hybrid.rs:297` says so in its own comment, and `:315` iterates
`ps["models"]`. So when `resident == false` there is no row and `size_bytes` cannot come from the
named instrument. `admit`'s only real refusal was `needs = size_bytes` **on exactly that branch**. In
production `size_bytes` would be `0`, `needs` would be `0`, and `needs + headroom > free` collapses
to `headroom > free` — **the model's footprint never enters the decision.**

The design's own test hid this by hand-building `{resident: false, size_bytes: 3_271_515_176}` — a
number obtainable only from `/api/ps` *while resident*, i.e. the session's own measurement fed back
through a double. **So `a_spawn_that_does_not_fit_is_refused` was green on a build whose gate admits
everything.** Instance #15 with the numbers reversed, and instance #17 at the producer rather than
the constructor: a `0` meaning *"footprint unknown"* read as *"costs nothing"* and therefore as
permissive. The design claimed it had closed #17 **in both directions**; it closed it at
`Headroom::new` and left it wide open at `Residency`.

What changed because of it: `SizeSource` (§2.2), so a size carries its origin and the refusal names
it; the `!resident && size_bytes == 0 → Unmeasured` guard in `admit`; and **test 2**, which did not
exist in the reviewed design at all.

### 6.2 · The other ten, and what each changed

| Defect | What changed |
|---|---|
| **A capacity refusal cannot be journalled on `RunSpawned`, because a refused spawn emits no event at all.** `spawn_refused` (`engine.rs:3112`) appends nothing. The design's test 1 asserted *zero* `RunSpawned` on a refusal while its enforcement table said `refused_no_room` is *"read by `RosterRecorder::append` into the `RunSpawned` row"* — both cannot be true | §2.5: `EventKind::SpawnRefused`, and the contract impact moved from a flat *"None"* to a minor version bump |
| **Eight `Admission` fields had no production reader**, in a design whose stated purpose was fixing instance #16. `explain()` was left as `String::new()`; `tag()` discards every number | §3's table; `explain()` specified as the text `spawn_refused` is called with, so the branch is the reader; `payload()` as the journal row |
| **No production `CapacityHost` impl was named, and the crate graph forbids both obvious homes** — so the shipped daemon would build `capacity: None` and every verdict would be `Unmeasured` | §2.4 names `crates/marlowe-daemon/src/capacity.rs`, and §2.3 replaces `Option` with a named `Unenforced` so an omission cannot masquerade as a choice |
| **Three definitions of "what is resident", and a second definition of "what must be left alone"** — `hybrid.rs:313`, `vram.rs`'s `Reserve::read`, and the design's new reader; `Headroom` duplicating `ReserveReading` with the `reason` dropped | §2.1 extracts one parse and refactors `hybrid` onto it; `Headroom` gains `reason` |
| **Citations that do not resolve.** `RunSummary` is at `daemon.rs:302`, not `control_plane.rs`; `vram.rs` is at `crates/marlowe-memory/src/cue/dense/vram.rs`, in a crate neither `marlowe-loop` nor `marlowe-provider` can reach; `--status` prints from `protocol.rs:400` and `agent.rs:648`, neither cited | Every citation in this ADR was re-verified against the tree at `186b5d5`; the corrected paths are used throughout, and the `daemon.rs` concurrent-edit collision is stated at §2.4 |
| **`executing_runs` was wrong on the terminality it depends on** | §5 test 8's second case — **but the finding itself needed correcting; see §6.3** |
| **The `state_of` test enumerated the wrong alphabet** — `RunStatus` variants are a subset of the wire's words, and `EVERY_WORD.len() == 8` derived from that list is instance #19 exactly | §5 test 7: 15 words pinned by hand from four producers, with (b)/(c) reddening if the array shrinks |
| **`Residency` had no validating constructor** — `size_vram_bytes > size_bytes` was constructible, making `gpu_permille() > 1000` and `fully_on_device()` a false negative on nonsense input | §2.2's `Residency::new`, private fields, no `Deserialize` (instance #12) |
| **`CallLimits::route` does not change the product** — it gives `model_route()` a reader at the type level while `Routing::uniform` keeps all three routes identical | §2.7 says so in the ADR, the test header and STATE.md, and records `ollama.rs:242`'s cached `ModelCapability` as the known second definition to close in Session G |
| **"Never a CPU split" is not enforced, only observed one spawn late** — Ollama decides layer offload at load, so a split model has already loaded and already served by the time `/api/ps` reports it | §8 carries it as a residual with a named closure (`options.num_gpu`), and `RefuseSplit` is described as the **detector**, never the enforcement |
| **The `keep_alive` narrowing was asserted as settled and deferred to the human in the same document** | Struck from Session C entirely: nothing in `types`, nothing in `request_body`, one line in §8 |

### 6.3 · Two corrections to the critique itself, made in place

**The critique wrote that four fate words break `is_terminal_word`. Two of them are correct as they
stand, and the correction matters because test 8 is built on it.** `roster.rs:55-58`'s own comment:
*"`detached` and `adopted` are deliberately absent. They are orphan fates, and both mean the child is
still going — under a new parent, or under none."* A detached child **is** live, so treating it as
non-terminal is right rather than a defect. **The genuine gap is `terminated` and `no_checkpoint`**,
which mean the child has stopped and which `is_terminal_word` rejects. Test 8's second case is
written on `terminated` for that reason, not on `detached`.

**The critique wrote that `Routing::new` has zero non-test callers. It has exactly one**,
`routing.rs:102`, inside `Routing::uniform` itself. The conclusion is unchanged and slightly
stronger: every production construction reaches `new` **through** `uniform`, so all three routes are
the same tag by construction rather than by convention.

---

## 7 · A defect found while verifying this ADR's citations, which is NOT this decision's to fix

Reading `settle_children` to check the terminality claim turned up something neither the design nor
the critique names, and it is recorded here because `executing_runs` is about to be built on top of
the table it corrupts.

`Engine::settle_children` records the **child's** amended checkpoint under the **parent's** run id:

```rust
// crates/marlowe-loop/src/engine.rs:2499  — `run` here is the PARENT
self.record(ports, EventKind::Checkpointed, run, state, serde_json::to_value(&amended)…);
```

`Engine::record` (`engine.rs:3195`) appends with `run.id`. `RosterRecorder`'s `Checkpointed` arm
(`roster.rs:109`) then keys the roster row off the **event's** run id —
`plane.runs.get_mut(&run.to_string())` — not off the checkpoint's own `run` field, which is the
child. The payload is the child's amended checkpoint, carrying the child's `status`
(`RunStatus::Cancelled` for `OrphanPolicy::Terminate`, `durable.rs:372`), the child's `spent.tokens`
and the child's `spent.micros_usd`. So on the terminate path:

* the **child's** row never receives its own amended `cancelled` at all — it keeps whatever the
  following `RunCompleted` arm writes, which is the fate word `terminated`, and
  `is_terminal_word("terminated")` is **false**;
* the **parent's** row is written with the child's status, tokens and spend, and — because
  `cancelled` *is* terminal — with the child's `wall_ms` as the parent's `elapsed_ms`.

`RunCompleted`'s arm (`roster.rs:145`) keys correctly off `payload["child"]`; only the `Checkpointed`
arm is misattributed. The parent's row is largely overwritten afterwards by `daemon.rs:2903`'s
`mark(&plane, status, run.spent.tokens)` and `:2914`'s `s.elapsed_ms = run.spent.wall_ms`, so the
parent-side effect is transient — **but M3-DESIGN §6.2's window is a live surface and the transient
is exactly what it renders**, and `settle_children` also runs on the pause path, where the parent
stays live.

**This is established by reading, not by running.** No `cargo` was invoked while writing this ADR;
another session is building. It is stated here rather than fixed because it is not admission
control's to fix, and because ADR-062's closing note applies: reachability is the kind of claim this
project has been wrong about in both directions, and this one wants a measurement before anyone acts
on it. **Test 8 must not be written against the parent's row until it is settled.**

**A second, smaller one, found the same way and free to state:** `state_of` has an arm for the word
`"waiting"` (`watch_client.rs:213`) that **no producer emits** — `RunStatus::WaitingEvent`
serializes to `waiting_event`, and `"waiting"` is the *view's* own label
(`marlowe-view/src/run.rs:53`). It is a reader with no writer, the mirror image of instance #16, and
it is why `EVERY_STATUS_WORD` must be the alphabet of **producers**: `"waiting"` does not belong in
the pinned array, and test 7 (a) would be weakened rather than strengthened by adding it.

---

## 8 · What this decision does NOT close, and what is the human's

* **The fourth model role's name.** Four roles were specified and three named. Not guessed here.
  `admit` and `CallLimits::route` are written over `ModelRoute`'s existing three arms, so a fourth is
  a **compile error** rather than a silent omission.
* **`OLLAMA_KEEP_ALIVE`.** Struck from Session C entirely. The argument for narrowing the reverted
  global into a **per-request** `keep_alive` in the body this harness sends — scoped to our models,
  revocable, read by one line in `request_body` — is sound and is recorded as the question the human
  is asked. **It is a narrowing of a recorded decision and it needs a `DECISIONS.md` entry before it
  ships.** It is not taken here, and it is not half-taken here, which is how the reviewed design had
  it.
* **`options.num_gpu`, and preventing a split LOAD.** `RefuseSplit` **detects** a split; it cannot
  stop Ollama loading one, so a split model runs to completion at a tenth of the speed and is refused
  on the *next* spawn. That is the residual, stated as one. Closing it is a per-request
  provider-behaviour decision of the same class as `keep_alive`.
* **Whether concurrency is wanted at all**, against `OLLAMA_NUM_PARALLEL=1`'s prefix-cache
  protection — STATE.md, 2026-08-27: a 148-byte prefix change cost 1.45 s on this machine, so it is a
  measured trade and not a preference. **This is what decides whether `WaitingCapacity` ever gets a
  producer**, and therefore whether §4's second rejected alternative is ever revisited.
* **Whether a spawner-named role is a TARGET under ADR-023** (AGENT-DIRECTORY §3 item 4). Today
  `Engine::spawn` hardcodes `ModelRoute::Worker` (`engine.rs:2654`) and nothing model-supplied
  reaches the gate, so `adjudicate.rs` is untouched by this decision. The moment `run` carries a
  role, **both a downgrade (make the system dumber before an attack) and an upgrade (exhaust budget)
  are attacker-useful**, and `composes_spawn_targets` (`engine.rs:3237`) needs a fourth clause.
  **Do not let that arrive as a side effect of this design.**
* **`AGENT-DIRECTORY.md` §2's arithmetic, which is human-authored.** *"10.0 GB of the card's 16,
  leaving headroom"* against a measured 1,053 MiB free with all three roles resident. Since ADR-044
  resolves the embedder's provider against free VRAM **at load**, co-residency means the embedder
  silently resolves to CPU with a correct-looking log line. Correcting a brief the human wrote is
  theirs; `Headroom`'s `reason` string is what stops the same arithmetic being re-committed in code.
* **`RunStatus::WaitingCapacity` in CONTRACTS §5 when concurrency lands.** A pinned-contract act,
  deferred here rather than taken quietly, with the guard that makes deferring safe (test 7) shipping
  in C.
* **If the human prefers `CapacityHost` beside the other ports in `driver.rs`, that is a §13-guarded
  edit**, needs approval, and needs a `DECISIONS.md` entry. It is not taken by inference from this
  ADR.
* **§7's misattributed `Checkpointed` row, and `state_of`'s dead `"waiting"` arm.** Filed, not fixed,
  not owned by this decision.
* **`ingest` stays unwired.**
  `grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"` returns
  nothing; nothing in this decision changes that.

---

## 9 · Contract impact — NOT none, and that is half the reason for the status line

* **`EventKind` gains `SpawnRefused`.** CONTRACTS.md line 113: *"Closed set. Adding a kind is a minor
  version bump; changing one is major."* This is the minor bump, and it is a pinned-contract act.
* **The pinned `EventKind` list at CONTRACTS.md lines 114–124 is already drifting and must be fixed
  in the same commit.** Measured: `grep -n "TrustFloorLatched" docs/design/CONTRACTS.md` returns
  **nothing** (exit 1), while the variant is in the code at `crates/marlowe-journal/src/event.rs:82`
  with a doc comment explaining why it is journalled. A pinned list that has silently fallen behind
  the type it pins is the same family as the §13 table that ran three rows behind the hook for two
  milestones: the mechanism held and the map went quiet.
* **`RunStatus` is unchanged.** No variant added, none renamed, every wire spelling identical, so
  `roster.rs`, `marlowe-view/src/run.rs::RunState` and `watch_client.rs` all keep matching.
* **`CapabilityProfile` is unchanged.** `model_route` is already pinned at CONTRACTS.md:952 and
  merely gains its first reader.
* **`SpawnRequest` is untouched.** Note that CONTRACTS.md:941 pins only
  `fn spawn(&self, req: SpawnRequest) -> RunId` and never the struct's fields, so ROADMAP item (4)'s
  role field would be a **first pinning**, not a move.
* `CallLimits`, `Budget::call_limits`, `Ports`, `RunSummary`, `LoopOutcome` appear nowhere in
  `CONTRACTS.md`. `CHECKPOINT_VERSION` does not move — `Checkpoint`'s shape is unchanged.
* **What C owes §5 in prose:** that `Queued` means *constructed, not yet started*; that
  capacity-waiting will be a distinct variant and **never** a reason on `Queued`; and that the
  variant lands with the concurrency that produces it — the discipline ADR-062 used when it pinned
  `ingest_external` and said in its own words that nothing calls it.

---

## 10 · What this ADR does NOT claim

* **It does not claim the gate is a defence.** Capacity is a performance control. It fails open,
  deliberately (§2.2), and nothing about it belongs among the five layers or beside them.
* **It does not claim "never a CPU split" is enforced.** §8 says it is detected one spawn late, and
  §6.2 records that the reviewed design's enforcement table overclaimed it.
* **It does not claim `CallLimits::route` changes product behaviour.** §2.7 says it does not, and
  test 6 is written with three distinct model names precisely because the production `Routing` would
  make it vacuous.
* **It does not claim the `--status` line is evidence the gate works.** Test 9 has no mutation and is
  never listed alone; test 10 is the one that exercises the production path, and if test 10 cannot be
  produced then the gate has not been shown to fire at all.
* **It does not claim the wire alphabet is complete.** Fifteen words are pinned by hand from four
  producers. A sixteenth is caught only if it is a `RunStatus` variant (a compile error) or an
  `OrphanOutcome` (assertion c). **A new bare literal written into `s.status` anywhere else is not
  caught**, and saying so beats a test named for a property it cannot see.
* **§7's finding is argued from reading, not measured.** No `cargo` command was run.

---

## Verification

Symbol names are used where a line number would be a claim about a path with nothing checking it
(family #14). Everything below was established against the tree at `186b5d5`, 2026-08-30.

| Claim | How established |
|---|---|
| `Engine::spawn` runs its child inline | read: `engine.rs:2892` |
| `model_route()` has zero call sites in the workspace | `grep -rn "model_route()" --include=*.rs crates/` — **empty**; the definition at `profile.rs:280` reads `model_route(&self)` and does not match the pattern |
| `Routing::new` has one non-test caller, `Routing::uniform` | `grep -rn "Routing::new\|Routing::uniform"` — `routing.rs:102`, plus six `uniform` sites in production and the remainder in tests |
| `request_body` hardcodes the orchestrator route | read: `ollama.rs:300` |
| `spawn_refused` appends nothing to the journal | read: `engine.rs:3112` onward |
| `/api/ps` lists only resident models | read: `hybrid.rs:297` (the comment) and `:315` (the iteration) |
| `ollama list` understates the resident footprint by ~14% | read: `vram.rs:156` — 5.8 GB on disk, 6.6 GB resident at 32k; `:160` refuses "a multiplier nobody measured" |
| `status_word` keeps the serde key and discards the object | read: `roster.rs:71-77` |
| `is_terminal_word` matches three words, and `detached`/`adopted` are deliberately excluded | read: `roster.rs:55-61` |
| The four fate words | read: `durable.rs:426-428` (`OrphanOutcome::verb`), `engine.rs:2491` (`no_checkpoint`) |
| `state_of`'s fallback, and its dead `"waiting"` arm | read: `watch_client.rs:209-225`; `grep -rn '"waiting"'` shows the producers are `marlowe-view/src/run.rs:53` and `marlowe-surface/src/commands.rs:339`, neither of which is a daemon run status |
| `RunStatus` has 8 variants under `rename_all = "snake_case"` | read: `run.rs:202-212` |
| `RunSummary` is in `daemon.rs`, not `control_plane.rs`, and has no `parent` field | read: `daemon.rs:302-325` |
| `live_runs` counts rows whose status is literally `"running"` | read: `control_plane.rs:213` |
| `--status` prints `runs {} live` | read: `agent.rs:648`, off `protocol.rs:400`'s `pub live_runs: usize` |
| **70 `Ports {` literals across 24 files** | **measured**: `grep -rn "Ports {" --include=*.rs crates/ \| wc -l` → 70; the same grep with `-l` → 24 |
| Both child `Ports` hardcode `memory: None` | read: `engine.rs:2269`, `engine.rs:2885`. **ADR-062 cited these as `2215` and `2831`; the lines have drifted and the property has not** |
| `EventKind` is a closed set and adding one is a minor bump | read: `CONTRACTS.md:113` |
| `TrustFloorLatched` is in the code and absent from CONTRACTS' pinned list | **measured**: `grep -n "TrustFloorLatched" docs/design/CONTRACTS.md` exits 1; `event.rs:82` has it |
| No §13-guarded file is touched | **measured**: `python .claude/hooks/protect-boundaries.py --list-protected` — 15 entries, none of them `engine.rs`, `event.rs`, `roster.rs`, `daemon.rs`, `control_plane.rs`, `budget.rs`, `ollama.rs`, `hybrid.rs`, or either new file |
| The settle path records the child's checkpoint under the parent's id | read: `engine.rs:2499` with `record`'s `run.id` at `engine.rs:3195`, against `roster.rs:109`'s `plane.runs.get_mut(&run.to_string())` |
| 16,376 MiB total / 5,086 MiB tier 0 / 10,849,836,070 B resident / 1,053 MiB free | **NOT measured by this ADR.** Carried from the design session that produced `runs/m3-c/design/admission-control.md`. Test 9 is what re-takes it on the shipped binary, and CLAUDE.md's rule about carrying a measurement across a boundary is the reason it is not simply cited |

**No `cargo` command was run while writing this ADR** — another session was building, and CLAUDE.md's
shared-checkout form 6 (a build stealing CPU produces a complete, plausible table that is wrong) cuts
both ways: a measurement taken now would be as untrustworthy as the one it displaced.
