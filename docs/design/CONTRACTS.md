# Marlowe — Pinned Contracts

**Status:** Pinned. **If one of these is wrong, stop and raise it. Never silently change a
schema** — other work depends on it, and future sessions build against these in parallel
without seeing each other.

Normative notation is Rust. Boundaries that cross a process or language line additionally pin
a JSON wire format, and the JSON is normative for those.

**Versioning.** Every contract carries `CONTRACT_VERSION`. A breaking change requires a new
major version and an entry in `DECISIONS.md`. Two different retention rules apply, and
conflating them breaks ADR-003:

| Contract class | Old versions must stay decodable |
|---|---|
| **Journal event payloads** (§1) | **Forever. No expiry, ever.** |
| Everything else — wire formats, APIs, manifests | One major cycle |

The journal rule is strict because **rebuild-from-log is the migration story** (ADR-003): every
index is rebuildable from the log, which is what makes schema evolution a rebuild rather than a
data migration. An event kind that stops decoding makes every event after it unreplayable, which
destroys invariant 7 and the migration path in the same stroke. A deprecated event kind may stop
being *written*; it may never stop being *read*.

```rust
pub const CONTRACT_VERSION: (u16, u16) = (1, 0);
```

**Pin record, 2026-08-02 — §4.0 added; §4.1's clock normalized; §§4.2/4.6/4.7 tightened.**
Normalizing the retrieval request's bare `now_ms` into `clock: { now_ms }` is a breaking change
to the wire format, which the rule above would ordinarily answer with a major bump. **No bump
was taken**, on the grounds that no implementation has ever consumed this contract — M0b does
not exist, and the only reader is the M0a harness, which was updated in the same change. A
major version exists to give implementers a migration signal, and there is nobody to signal.
Recorded here rather than assumed: if you would rather this were `(2, 0)`, it is a one-line
change plus a `DECISIONS.md` entry, and the harness follows.

---

## 1. Journal

The append-only, provenance-signed event log. The only source of truth.

```rust
/// Monotonic within a profile. Gaps are impossible; the sequence is the ordering.
pub type Seq = u64;
pub type TraceId = Uuid;

pub struct JournalEvent {
    pub seq:        Seq,
    pub ts:         Timestamp,          // UTC millis, harness clock, never model-supplied
    pub trace_id:   TraceId,            // invariant 7: replay key
    pub session_id: Option<SessionId>,
    pub run_id:     Option<RunId>,
    pub actor:      Actor,              // who caused this. NEVER `Model`.
    pub kind:       EventKind,
    pub payload:    EventPayload,       // small, structured; large content goes by ContentRef

    // ── tamper-evidence over the SEQUENCE, not just over each event ──────
    pub prev_signature: Signature,      // the predecessor's signature; GENESIS for seq 1
    pub signature:      Signature,      // HMAC over (seq, ts, trace, actor, kind,
                                        //            payload, prev_signature)
}
```

**The log is a hash chain, and that is stronger than per-event signing on purpose.**

A signature covering only its own event stops **forgery**: an event cannot be inserted or
rewritten without the key. It does not stop **deletion or reordering** — a well-formed event
removed from the middle leaves every remaining signature valid.

That gap matters more here than it would in most logs, because of what §5.4 asks of
forgetting. Forgetting must remove *accessibility* while the log preserves *availability*;
if a row can be deleted undetectably, then `DELETE` becomes an alternative implementation of
forgetting that destroys availability instead — and it is the one implementation that leaves
no trace of having run. Invariant 7 (*every autonomous action is reconstructable*) and
§5.4's worst-failure clause (*a memory the user can no longer surface but the system
silently acted on*) both rest on that not being possible.

Chaining closes it: removing or reordering any event invalidates every signature after it,
so `verify_chain` on open localizes the break to the row where it happened.

**Pin record, 2026-08-03 — §1 amended to specify the chain.** Adding `prev_signature` and
extending the signed tuple is a breaking change to the event schema, which §0's rule would
ordinarily answer with a major version bump. **No bump was taken**, on the same grounds as
the §4.0 pin: no journal has ever been written outside the M0b test suite that landed in the
same change, so there is no data to migrate and no implementer to signal. The rule exists to
give implementers a migration path, and there are none.

Recorded here rather than in a source comment, deliberately. The implementation reached this
design first; leaving §1 describing the weaker scheme would have left a pinned contract and
its implementation in contradiction, to be resolved by whoever read them next — and that is
not a decision to leave to a default. Same handling as brief §8.2, which was amended to match
ADR-002 rather than left as a deviation.

```rust
// The chain's base case. A profile's first event chains from this constant.
pub const GENESIS: Signature = "genesis";

/// The model is not in this enum. That is the point: the model requests, the harness appends.
pub enum Actor {
    Harness,                  // the loop's own bookkeeping
    User { surface: Surface },
    Permission,               // ONLY component that may emit tier-granting events
    Consolidation { run: RunId },
    Trigger { trigger: TriggerId },
    Tool { tool: ToolId, run: RunId },
}
```

### 1.1 Event kinds

Closed set. Adding a kind is a minor version bump; changing one is major.

```rust
pub enum EventKind {
    // ── conversation & runs ──────────────────────────────────────────────
    TurnStarted, ModelStep, Interrupted, Checkpointed,
    RunSpawned, RunPaused, RunCompleted, RunFailed, RunCancelled,
    SteerReceived, ProviderFailedOver,

    // ── tools & permission ───────────────────────────────────────────────
    ToolRequested, PermissionDecided, ApprovalRequested, ApprovalGranted,
    ApprovalDenied, ToolCompleted, ToolFailed, EgressBlocked,

    // ── memory: writes ───────────────────────────────────────────────────
    MemoryWritten,            // the ONLY way a belief comes into existence
    MemoryWriteRejected,
    MemoryInjected,           // what the gate admitted, and why. Enables §5.7 audit.
    MemoryRecalled,           // explicit `recall` tool use

    // ── memory: forgetting is events, not computed state ─────────────────
    FidelityDemoted { to: FidelityTier },
    Superseded      { by: MemoryId },
    Tombstoned,
    Redacted        { subject: SubjectKey },   // destructive; see §3.4
    BlobEvicted     { blob: ContentHash },

    // ── consolidation ────────────────────────────────────────────────────
    ConsolidationRan, BeliefsMerged, ContradictionResolved, SkillInduced,

    // ── sessions & lineage ───────────────────────────────────────────────
    SessionStarted, SessionSummarized, SessionSpawned, SessionClosed,

    // ── trust ledger: appendable ONLY by Actor::Permission ────────────────
    ActionObserved, PromotionProposed, TierGranted, TierDemoted, VerificationSampled,

    // ── triggers ─────────────────────────────────────────────────────────
    TriggerFired, NoticingRaised, NoticingDismissed,
}
```

**Invariant (enforced at append):** `TierGranted` and `TierDemoted` are rejected unless
`actor == Actor::Permission`. Because the model can never be an `Actor`, self-promotion is
unrepresentable rather than merely forbidden (§A8.4: *self-granted promotions — zero,
structurally impossible*).

### 1.2 The append API

```rust
pub trait Journal {
    /// The ONLY write path. Stamps seq, ts, and signature. There is no unsigned variant.
    fn append(&self, req: AppendRequest) -> Result<Seq, AppendError>;

    /// Operator and audit only. NOT registered as a tool at any exposure tier, and the
    /// journal path is outside the model's filesystem scope. See ARCHITECTURE §4 invariant 8.
    fn replay(&self, filter: ReplayFilter, cap: OperatorCapability) -> EventStream;
}
```

---

## 2. Content store

```rust
pub struct ContentRef {
    pub hash:    ContentHash,       // blake3; content-addressed, dedup for free
    pub bytes:   u64,
    pub media:   MediaType,
    pub summary: ResultSummary,     // §8 — survives eviction
    pub trust:   TrustClass,        // origin-bound at capture, immutable
    pub evicted: bool,              // true => bytes gone, summary + hash remain
}
```

Eviction leaves the ref. `evicted: true` with an intact summary is how §5.4's
"never silently delete" holds for content: the system can always say *what* it had.

---

## 3. Memory

### 3.1 The envelope

One envelope for every belief. This is what makes memory the spine rather than a module: a
commitment and a preference carry identical provenance machinery.

```rust
pub struct MemoryEntry {
    pub id:            MemoryId,
    pub payload:       Payload,          // closed set, §3.2
    pub embedding_ref: Option<VectorId>,

    // ── provenance (brief §5.6; invariant 2) ─────────────────────────────
    pub source:        Source,
    pub trust_class:   TrustClass,       // OWN class, before propagation
    pub effective_trust: TrustClass,     // AFTER worst-case propagation, §3.3 — use this
    pub derivation:    Vec<MemoryId>,    // FULL lineage, not just immediate parents
    pub origin_event:  Seq,              // the MemoryWritten event that created it
    pub signature:     Signature,        // write-time integrity binding

    // ── lifecycle ────────────────────────────────────────────────────────
    pub created_at:    Timestamp,
    pub last_accessed: Timestamp,
    pub access_count:  u32,
    pub confidence:    f32,              // 0.0..=1.0
    pub activation:    f32,              // decay + retrieval-induced interference
    pub fidelity:      FidelityTier,
    pub silent_until:  Option<Timestamp>, // §5.3 engram maturation: low-activation entry state
    pub supersedes:    Vec<MemoryId>,
    pub superseded_by: Option<MemoryId>,
    pub subjects:      Vec<SubjectKey>,  // for per-person crypto-shredding, §3.4
}

pub enum FidelityTier { Record = 3, Summary = 2, Gist = 1, Tombstone = 0 }
```

### 3.2 Payloads

Closed set. Adding a variant is a minor bump. This is where the secretary layer lives — as
memory, not beside it.

```rust
pub enum Payload {
    Episode      { text: String, session: SessionId, outcome: Option<Outcome> },
    Fact         { text: String, entities: Vec<EntityId> },
    Entity       { kind: EntityKind, names: Vec<String>, attrs: Map<String, Value> },
    Edge         { from: EntityId, to: EntityId, rel: Relation, weight: f32 },
    Procedure    { skill_id: SkillId, version: u32 },
    Commitment   (Commitment),          // §9
    Person       (Person),              // §9
    Relationship (Relationship),        // §9
    VoiceParams  { person: EntityId, params: Map<String, Value> },
    Noticing     { class: NoticingClass, rationale: Vec<MemoryId> },
}
```

### 3.3 Trust classes and worst-case propagation

```rust
/// Ordered. Higher is more trusted. The ordering IS the propagation rule.
#[derive(PartialOrd, Ord)]
pub enum TrustClass {
    UntrustedContent = 0,   // web, inbound mail, MCP server output, third-party skill output
    AgentInferred    = 1,   // the model concluded it
    AgentObserved    = 2,   // the HARNESS computed it: exit codes, hashes, line counts
    UserAsserted     = 3,   // the user said it, on an authenticated surface
}
```

**Propagation algorithm.** Computed once at write time and stored, because parents' effective
trust is already transitively minimal:

```rust
fn effective_trust(own: TrustClass, parents: &[MemoryEntry]) -> TrustClass {
    parents.iter().map(|p| p.effective_trust).chain(once(own)).min().unwrap()
}
```

This is what defeats memory laundering (§14.6). A fact the agent wrote in fluent prose,
derived through four LLM transformations from a web page, carries `UntrustedContent` — no
content signal is consulted, because content signals are structurally insufficient here.

**The distinction that makes this usable:** trust class tracks *the authority of the origin*,
not the safety of the bytes.
- Facts **the harness computed** (exit code, file hash, test count) are `AgentObserved`.
- Facts **the model extracted from bytes** inherit the bytes' origin class.

So `pytest` exiting 1 is `AgentObserved`; the model's reading of the failure message in a
vendored `README` is `UntrustedContent`. Both are useful; only one may target a gated call.

### 3.4 Subject keys and redaction

```rust
/// Minimum granularity is per-(profile, person). Deleting one contact must never force
/// shredding a scope that takes others with it.
pub struct SubjectKey { pub profile: ProfileId, pub person: Option<EntityId> }
```

Each record is encrypted under a per-record DEK; the DEK is wrapped once per subject.
`Redacted` destroys one subject's wraps.

**Accepted limitation, recorded not hidden:** a multi-subject record survives until its last
subject wrap is destroyed. Deleting person A does not remove A's contribution from a record
also keyed to B. See `DECISIONS.md` ADR-003.

### 3.5 The memory API

```rust
pub trait Memory {
    /// A REQUEST, not a write. The model supplies a claim and nothing else. The harness
    /// assigns the id, resolves derivation, computes effective_trust, signs, and appends —
    /// or rejects. Invariant 2 depends on there being no other path.
    ///
    /// NAMING HAZARD: the model-visible tool is called `remember`, which reads like a write.
    /// It is not. Implementers must not add a bypass "for performance".
    fn remember(&self, run: RunId, claim: Claim) -> Result<WriteReceipt, Rejected>;

    fn recall(&self, req: RecallRequest) -> RecallResult;      // explicit; sees tombstones
    fn correct(&self, run: RunId, target: MemoryId, correction: Claim) -> WriteReceipt;
    fn forget(&self, subject: SubjectKey, mode: ForgetMode) -> RedactionReceipt;
}

pub struct Claim {
    pub payload:      Payload,
    pub asserted_by:  Source,
    pub derived_from: Vec<MemoryId>,     // may be empty; harness verifies each exists
}

pub struct WriteReceipt {
    pub id: MemoryId, pub seq: Seq,
    pub effective_trust: TrustClass,     // may be LOWER than requested — worst-case wins
    pub silent_until: Option<Timestamp>, // new beliefs enter silent (§5.3)
}

pub enum Rejected {
    UnknownParent(MemoryId),
    TrustFloorViolated { requested: TrustClass, permitted: TrustClass },
    QuotaExceeded,
    ContradictsPinned { pinned: MemoryId },
}

pub enum ForgetMode { Decay, Tombstone, RedactDestructive }
```

### 3.6 Recall

The explicit path (§5.5: *"recall recovered by making the agent's explicit memory search tool
excellent"*). Unlike auto-injection it sees tombstones and unmatured entries.

```rust
pub struct RecallRequest {
    pub run: RunId,
    pub clock: Clock,
    pub query: String,
    pub filter: RecallFilter,
    pub limit: u16,
}

pub struct RecallFilter {
    pub entities: Vec<EntityId>,
    pub time_range: Option<TimeRange>,
    pub payload_kinds: Vec<PayloadKind>,
    pub min_trust: Option<TrustClass>,
    pub include_tombstones: bool,       // default TRUE — this is the "I used to know" path
    pub include_superseded: bool,       // default false
}

pub struct RecallResult {
    pub items: Vec<Recalled>,
    pub cost: RetrievalCost,
}

/// NOT the same type as InjectedMemory. A tombstone has no content, and InjectedMemory.content
/// is a non-optional String — reusing it would force either a lie ("") or a panic.
pub struct Recalled {
    pub id: MemoryId,
    pub fidelity: FidelityTier,
    pub effective_trust: TrustClass,
    pub matured: bool,                  // false => excluded from auto-injection, per §4.3
    pub body: RecalledBody,
}

pub enum RecalledBody {
    /// fidelity Record | Summary | Gist — progressively shorter, always present
    Content { text: String },
    /// fidelity Tombstone — the memory is gone; this is the epitaph
    Tombstone(TombstoneStub),
}

/// Enough to answer "I used to know something about this" (§5.4) and to ground an honest
/// abstention (§17.9) — and deliberately not enough to reconstruct what was forgotten.
pub struct TombstoneStub {
    pub entities: Vec<EntityId>,        // what it was ABOUT
    pub time_range: TimeRange,          // when the underlying events happened
    pub forgotten_at: Timestamp,
    pub reason: ForgetReason,
}

pub enum ForgetReason {
    Decayed,                            // activation fell below the retention floor
    Superseded { by: MemoryId },
    UserRequested,                      // ForgetMode::Tombstone or RedactDestructive
    BlobEvicted,                        // content store reclaimed the bytes (§2)
}
```

`ForgetReason::UserRequested` is distinguishable from the rest on purpose: *"you asked me to
forget that"* and *"that decayed"* are different answers, and only one of them should ever be
offered to re-learn.

---

## 4. The M0a↔M0b boundary

**This is load-bearing for the M0a/M0b split.** M0a (the eval harness) is built against it
*without knowledge of the retriever*, so it is pinned here, in this document, before either
exists. JSON is normative — the scorer is Python, the implementation is Rust.

**The boundary is three interfaces, not one.** Retrieval alone is enough to build the
injection-precision judge, but not the LongMemEval, LoCoMo, or poisoning adapters — those need a
contracted way to write a history and to ask a question. All three get identical treatment:

| Interface | § | What M0a does with it |
|---|---|---|
| **Ingest** | 4.6 | Load a benchmark history; drive the poisoning suite |
| **Answer** | 4.7 | Ask a question, score the answer and the abstention |
| **Retrieve** | 4.1–4.4 | Score injection precision, tokens, latency |

**M0b may expose no other surface to M0a.** If the harness needs a fourth, the split is leaking
and the fix belongs here, not in the harness.

### 4.0 Transport

§§4.1–4.7 pin *what* crosses this boundary. This section pins *how*. It is framing and nothing
else: it adds no field that carries meaning, and it is not a fourth interface.

#### 4.0.1 Channel

The implementation exposes an **eval adapter**: a process that reads request frames on stdin
and writes response frames on stdout. `stderr` is diagnostic only and is never parsed.

The harness spawns the process, owns its lifetime, and closes stdin to end the run. It never
attaches to a process it did not start — a run whose outcome depends on state the harness did
not establish is not reproducible, and fails quietly rather than loudly.

This does not conflict with ADR-002. The daemon still owns the journal, the indexes, and the
socket; an implementation satisfies §4.0 with a thin forwarding mode (`marlowe --eval-adapter`)
that reads a frame, hands `body` to the daemon, and writes the response back. That bridge
belongs to the implementation, not to the harness — connection policy, socket paths and daemon
lifecycle are each a source of run-to-run variance, and none of them should live inside the
thing doing the measuring.

#### 4.0.2 Encoding and framing

**Newline-delimited JSON.** One JSON value per line.

- UTF-8, no BOM.
- Each frame is terminated by a single `\n` (U+000A). A `\r\n` terminator is a protocol error.
  Implementations on Windows must set stdout to binary/raw mode.
- A frame contains no literal newline. RFC 8259 requires control characters inside strings to
  be escaped, so a correctly serialized JSON value satisfies this without extra discipline.
  **Pretty-printed output is a protocol error**, not a tolerated variation.
- The implementation **must flush stdout after each response frame.** A response sitting in a
  buffer is indistinguishable from a hang.
- Maximum frame size is 64 MiB. An overlong line is `malformed_frame`.

Chosen over length-prefixing because the wire log *is* the reproducibility artifact: a third
party can read, diff and replay it with ordinary tools, where length-prefixed frames require
writing a decoder before you can look at your own data.

#### 4.0.3 Frames

Request:

```json
{"op": "ingest", "body": { "...": "the §4.6 request, verbatim" }}
```

`op` ∈ `ingest` | `retrieve` | `answer`, selecting §4.6, §§4.1–4.4, and §4.7 respectively.

Response, when a §4 response exists:

```json
{"op": "ingest", "body": { "...": "the §4.6 response, verbatim" }}
```

Response, when no §4 response exists:

```json
{"op": "ingest", "error": {"kind": "internal_error", "detail": "index not loaded"}}
```

**Frame rules.** `op` must echo the request's. Exactly one of `body` and `error` is present.
Any additional key at frame level is a protocol error. `body` is the §4 JSON **verbatim,
byte-for-byte** — no compression, no batching, no envelope metadata.

#### 4.0.4 `error` is the absence of a §4 response, not a variant of one

§4.6's `rejected` is a **successful** response: the implementation understood the request and
refused a write, and the poisoning suite asserts on exactly that. It travels in `body`.

`error` means the request produced no §4 response at all. `kind` is a closed set in two
classes, handled differently because they mean different things:

| Class | `kind` | Meaning | Harness behaviour |
|---|---|---|---|
| **A — the request was bad** | `malformed_frame`, `unknown_op`, `malformed_body`, `contract_version_unsupported` | The harness or the version pairing is at fault | Abort the run. A defect, not a measurement. |
| **B — the implementation failed** | `internal_error` | The system under test failed on a well-formed request | Record a failed unit and continue. A **result**, and it appears in the report. |

`error` is a frame-level key that is not a §4 message, and that tension is deliberate rather
than overlooked: an implementation needs a way to say *"no §4 response exists for this
request"* without dying. The alternatives are worse — an error shape inside a §4 payload would
genuinely change §4, and process death for every internal failure would make a recoverable bug
indistinguishable from a crash and throw away the rest of the run.

#### 4.0.5 Ordering and correlation

**Strictly serial.** The harness writes one request and reads exactly one response before
writing the next. There is never more than one outstanding request, so **there are no
correlation ids** — correlation is positional.

It is additionally checked, so a desynchronized stream fails loudly rather than silently
misattributing a result: the response `body` must echo the request's `query_id` (`retrieve`,
`answer`) or `session_id` (`ingest`). A mismatch is a protocol error and aborts the run.

#### 4.0.6 Startup and shutdown

**No handshake.** `contract_version` is present in every §4 body, so version disagreement is
detectable per-message and needs no negotiation round. The first frame on the wire is a
request. The harness signals end of run by closing stdin; the implementation flushes and exits
0. Anything an implementation wishes to announce at startup goes to stderr.

#### 4.0.7 Failure semantics

| Condition | Classification | Effect on the report |
|---|---|---|
| Class B `error` frame | Failed unit | Scored and reported |
| EOF or process exit mid-request | `implementation_crashed`. **No retry** — a retry makes the outcome depend on timing | Run marked crashed; remaining units not attempted; the report is emitted, because a crash is a result |
| Class A `error`, frame-rule violation, `op` mismatch, id mismatch | Protocol error | Run aborts; no report |
| **Harness-imposed deadline exceeded** | A wall-clock decision by the harness | Run marked `timing_tainted`: **no headline report, hash not comparable** |
| **Implementation exceeds `budget.max_latency_ms`** | **Not a transport event.** A valid §4 response was returned; the miss is in `cost.latency_ms` | **Scored and reported normally** |

The last two rows are distinct and must not be conflated. An implementation missing the 300 ms
P95 is a *result the eval exists to produce*; it is never a reason a run cannot report. The
harness deadline exists only to bound a hung process, and is therefore set far above any
budget: **no lower than 100× the request's `max_latency_ms`, floored at 30 s.**

#### 4.0.8 Determinism

The transport contributes nothing to a run's identity: no ids, no timestamps, no sequence
numbers, no retries, no concurrency, no buffering-dependent ordering. For a given §4 body the
frame bytes are a pure function of that body.

`cost.latency_ms` is self-reported and varies between runs by nature. It is therefore excluded
from any bit-identity claim — recorded and scored rather than hashed.

#### 4.0.9 Language-agnosticism

A conforming implementation needs a UTF-8 line reader on stdin, a JSON parser, a JSON writer,
and a flush. Nothing else — no shared library, no generated bindings, no runtime schema
negotiation, nothing from the harness's side but the bytes. The harness's Python types are a
*binding* of this contract; the wire format is the contract.

The harness spawns the target's argv unmodified, with a declared minimal environment, so a run
does not inherit ambient state a third party cannot reproduce.

### 4.1 Retrieval request

```json
{
  "contract_version": "1.0",
  "clock":      { "now_ms": 1785312000000 },
  "query_id":   "q-0041",
  "session_id": "s-7",
  "turn_index": 3,
  "query_text": "why is the ingest job timing out again",
  "budget":     { "max_tokens": 7000, "max_latency_ms": 300 }
}
```

**The clock has one shape on all three interfaces: `clock: { now_ms }`.** An earlier draft put
a bare `now_ms` at the top level of this request only. That was a wart — §4.5 already said
"required on all three interfaces", and a third-party implementer hit the inconsistency on
their first request.

### 4.2 Response

```json
{
  "contract_version": "1.0",
  "query_id": "q-0041",
  "abstained": false,
  "abstention_reason": null,
  "injected": [
    { "memory_id": "m-8814", "content": "pinned client version dropped when Dockerfile rebuilt",
      "score": 0.91, "calibrated_precision": 0.96,
      "fidelity": "summary", "effective_trust": "agent_observed", "payload_kind": "fact" }
  ],
  "considered": 143,
  "gate": { "version": "frozen-v1", "threshold": 0.71, "adaptive": false },
  "cost": {
    "retrieval_tokens": 812,
    "latency_ms": { "total": 118, "embed": 12, "cues": 61, "fuse": 32, "gate": 13 }
  }
}
```

**`cost` is REQUIRED.** A response without it is a protocol error, not a warning. This is how
§5.7's *"report the pair — every accuracy number ships with its token cost and latency, or it
does not ship"* becomes structural instead of remembered.

`abstention_reason` ∈ `no_candidate_above_threshold | no_candidates | budget_exhausted |
degraded_path`. Abstention is a first-class outcome, not an empty list (§5.5).

**Abstention and injection are mutually exclusive, in both directions.** All three of these
are protocol errors, not hedges:

| Response | Why it is an error |
|---|---|
| `abstained: true` with a non-empty `injected` | An implementation with something to inject has not abstained |
| `abstained: false` with a non-null `abstention_reason` | A reason without the outcome it explains |
| `abstained: false` with an empty `injected` | Injecting nothing *is* the abstention outcome (`no_candidates`); reporting it as a non-abstention makes the same event scoreable two ways |

This is the same distinction §4.7 draws for `answered: false` with a populated `answer`, and it
exists for the same reason: **a schema that lets two outcomes blur is a schema that will let a
confabulation score as an abstention.** All four `abstention_reason` values describe having
nothing to inject, so the mapping is total — every response either injects something or
abstains, and never both or neither.

### 4.2b Rust binding

The JSON above is **normative** for this boundary — M0a is Python and M0b is Rust, so the wire
format is the contract and these types are its binding, not the other way round.

```rust
pub struct RetrievalRequest {
    pub clock: Clock,                 // §4.5 — same shape on all three interfaces
    pub query_id: QueryId, pub session_id: SessionId, pub turn_index: u32,
    pub query_text: String, pub budget: RetrievalBudget,
}

pub struct RetrievalResult {
    pub query_id: QueryId,
    pub abstained: bool,
    pub abstention_reason: Option<AbstentionReason>,
    pub injected: Vec<InjectedMemory>,
    pub considered: u32,
    pub gate: GateStamp,
    pub cost: RetrievalCost,          // NOT Option. A result without cost is unrepresentable.
}

pub struct RetrievalCost {
    pub retrieval_tokens: u32,
    pub latency: LatencyBreakdown,    // total, embed, cues, fuse, gate
}

pub struct InjectedMemory {
    pub memory_id: MemoryId,
    pub content: String,              // non-optional: a tombstone can never appear here (§4.3)
    pub score: f32,
    pub calibrated_precision: f32,
    pub fidelity: FidelityTier,
    pub effective_trust: TrustClass,
    pub payload_kind: PayloadKind,
}

/// The ONLY source of time on any path reachable from §§4.1, 4.6, 4.7. See §4.5.
#[derive(Copy, Clone)]
pub struct Clock { pub now: Timestamp }
```

`cost` being non-optional in the type is the point: §5.7's *"report the pair"* cannot be
forgotten if a result without its cost cannot be constructed.

### 4.3 Candidate-set contract

```rust
/// Auto-injection reads the LIVE-ONLY hot index. This is a REQUIREMENT, not an optimization:
/// see DECISIONS.md ADR-003 and the measured curve.
///
/// THREE exclusions, not two. The third is easy to lose:
///   1. tombstones          — fidelity > Tombstone
///   2. superseded entries  — superseded_by IS NULL
///   3. UNMATURED entries   — silent_until <= clock.now
pub fn injection_candidates(ix: &IndexSet, clock: Clock) -> CandidateSet {
    ix.hot()                                  // (1) and (2) hold by construction
      .filter(|m| m.silent_until.map_or(true, |t| t <= clock.now))   // (3)
}
```

Exclusion (3) is §5.3's **engram maturation** and it is a security property, not a quality
tweak: newly consolidated beliefs enter in a low-activation silent state and require
corroboration or elapsed stability before they can influence reasoning. It is *the cheapest
available defence against single-exposure poisoning* — a fact planted once cannot be injected
until it has survived a maturation window during which contradiction can supersede it. An
implementation that filters only on fidelity and supersession has silently removed that defence
while still passing every latency and precision test, because the attack is temporally decoupled
from its trigger.

Unmatured entries **are** reachable by explicit `recall` — the maturation bar is on *unprompted
influence*, not on existence.

```rust
/// Tombstones are reachable HERE and only here, plus the abstention check. They must never
/// compete for injection precision — a tombstone is the absence of a memory, and scoring it
/// as a candidate would penalise the headline metric for working correctly.
pub fn recall_candidates(ix: &IndexSet) -> CandidateSet { ix.hot().union(ix.cold()) }
```

### 4.4 Gate

```rust
pub struct Gate {
    pub version:   GateVersion,
    pub weights:   FrozenWeights,     // build-time artifact; NOT learned at runtime in M0
    pub threshold: f32,               // expressed in CALIBRATED PRECISION units, not score
    pub adaptive:  bool,              // false for M0. M10 may set true, see ROADMAP.
}
```

**Supervision asymmetry — pinned regardless of any later adaptivity milestone:**

```rust
pub enum GateSignal {
    /// WEAK NEGATIVE ONLY. Never a positive.
    Unused { memory: MemoryId },
    /// Positives come only from these two.
    JudgedRelevant { memory: MemoryId, judge: JudgeId },
    UserCorrection { memory: MemoryId },
}
```

Rationale, recorded because it is easy to "optimise" away: a naive utilization reward would let
a poisoned memory train the gate to prefer it. Attention-grabbing and correct are not the same
property, and only one of them is the target. See `DECISIONS.md` HP1 for the normative freeze
scope, which covers more than this struct.

### 4.5 The injectable clock

A clock on the retrieval request alone is not enough. Staleness half-life (§5.7) is *"time
before a superseded fact stops being retrieved"* — measuring it requires writing fact A at T₁,
writing its replacement at T₂, and querying at T₃, with all three controlled. A write path that
reads a system clock makes that unmeasurable and makes every decay-dependent result
irreproducible.

```json
{ "clock": { "now_ms": 1785312000000 } }
```

**Normative and binding: on any path reachable from §§4.1, 4.6, or 4.7, the implementation MUST
NOT read a system clock.** Every timestamp is derived from the `clock` supplied by the caller.
In production the harness supplies the real clock; under eval M0a supplies a synthetic one. Same
code path, so the eval exercises the shipping behaviour rather than a test double.

`clock` is required on all three interfaces. Decay, activation, `silent_until` maturation, and
supersession recency all read it.

### 4.6 Ingest

Loads a history. Also how the poisoning suite plants its attacks.

```json
{
  "contract_version": "1.0",
  "clock": { "now_ms": 1780000000000 },
  "session_id": "lme-s-0007",
  "turns": [
    { "turn_id": "t-1", "speaker": "user", "text": "I moved off Postgres in April",
      "occurred_at_ms": 1775000000000,
      "origin": { "channel": "terminal", "actor": "user", "ref": null } },
    { "turn_id": "t-2", "speaker": "tool", "text": "<fetched page body>",
      "occurred_at_ms": 1775000060000,
      "origin": { "channel": "web", "actor": "tool:web", "ref": "https://example.invalid/x" } }
  ]
}
```

**M0a declares `origin`. It never declares `trust_class`.** The harness derives trust from origin
by its own rules, exactly as in production. This is not a stylistic choice — letting the eval set
trust directly would let it bypass the mechanism it exists to test, and the laundering suite
specifically needs to assert that a claim entering through `channel: "web"` comes out
`untrusted_content` no matter how many derivations it passes through.

#### `channel` and `speaker` are closed sets

```rust
pub enum Channel {
    Terminal, Voice, Messaging, Email, Web, Mcp, ToolOutput, File,
}
pub enum Speaker { User, Assistant, Tool }
```

Wire values are snake_case: `terminal · voice · messaging · email · web · mcp · tool_output ·
file`, and `user · assistant · tool`.

**An unrecognized value is a load-time error on both sides. It is never mapped to a default.**
This is load-bearing, not tidiness. The laundering suite's entire assertion is that a claim
entering as `channel: "web"` comes out `untrusted_content` — which requires both sides to agree
on that string. An implementation that quietly mapped an unknown channel to some default would
make the suite pass while measuring nothing, and if that default were trusted it would do so
while actively hiding the failure. Same failure class as any silent fallback: the test goes
green because the code path it exercises no longer exists.

Response — the poisoning suite asserts on this:

```json
{
  "contract_version": "1.0",
  "session_id": "lme-s-0007",
  "written":  [ { "turn_id": "t-1", "memory_ids": ["m-1"], "effective_trust": "user_asserted" } ],
  "rejected": [ { "turn_id": "t-9", "reason": "unknown_parent" } ],
  "cost": { "ingest_tokens": 0, "latency_ms": { "total": 41 } }
}
```

`effective_trust` in the response is what the harness *derived*, which is the value the laundering
tests compare against. `rejected` is a first-class outcome: a suite that plants a malformed or
unauthorized write must be able to see it refused rather than infer refusal from absence.

### 4.7 Answer

LongMemEval and LoCoMo score answers, not retrieval. Abstention is scored explicitly (§5.5).

```json
{ "contract_version": "1.0", "clock": { "now_ms": 1785312000000 },
  "query_id": "q-0041", "session_id": "lme-s-0007",
  "question": "What database am I using?" }
```

```json
{
  "contract_version": "1.0",
  "query_id": "q-0041",
  "answered": true,
  "answer": "You moved off Postgres in April; you're on SQLite now.",
  "abstained": false,
  "abstention_reason": null,
  "grounded_in": ["m-8814", "m-9002"],
  "retrieval": { "...": "the §4.2 RetrievalResult that fed this answer" },
  "cost": {
    "prompt_tokens": 5120, "completion_tokens": 88, "retrieval_tokens": 812,
    "latency_ms": { "total": 1840, "retrieval": 118, "generation": 1722 }
  }
}
```

- **`retrieval` is embedded, not referenced.** Injection precision and answer correctness must be
  joinable on a single record, or the headline metric cannot be attributed to a retrieval
  decision — which is the whole point of measuring both.
- **`answered: false` with a populated `answer` is a protocol error.** The honest "no" (§17.9) is
  a distinct outcome from a hedged answer, and a schema that lets them blur is a schema that will
  let a confabulation score as an abstention.
- **`abstained: true` requires an empty `grounded_in`, and `answered: false` requires
  `abstained: true`.** By symmetry with §4.2, and for the same reason. A refusal that cites
  grounding is claiming to have answered from evidence while reporting that it declined, and an
  unanswered question that is not an abstention is an outcome the scorer has no bin for — it
  would be counted as neither a correct refusal nor an incorrect answer, which is how a
  systematic failure disappears from a report.
- **`cost` is required here too**, and separates retrieval from generation tokens — §5.7's
  ≤7,000 budget is a *retrieval* budget, and folding generation into it would hide a miss.

---

## 5. Runs

```rust
pub struct Run {
    pub id: RunId,
    pub parent: Option<RunId>,
    pub session: SessionId,
    pub trace_id: TraceId,
    pub status: RunStatus,
    pub profile: CapabilityProfile,
    pub budget: Budget,
    pub spent: Budget,
    pub orphan_policy: OrphanPolicy,   // declared at spawn, NEVER inferred
    pub output_contract: OutputContract,
    pub result: Option<ContentRef>,
    pub last_checkpoint: Option<Seq>,
}

pub enum RunStatus {
    Queued, Running,
    WaitingApproval { decision: DecisionId },
    WaitingEvent    { until: Option<Timestamp> },
    Paused          { reason: PauseReason },
    Completed, Failed { error: String }, Cancelled,
}

/// Children outlive parents. Parent completion does not kill a child.
pub enum OrphanPolicy { Adopt { by: RunId }, Detach, Terminate }

pub struct Budget {
    pub tokens: u64, pub wall_ms: u64, pub tool_calls: u32,
    pub subagents: u16, pub depth: u8, pub micros_usd: u64,
}
```

**Hitting a cap pauses and asks. It never fails silently and never spends past the line.**

```rust
pub trait RunControl {
    fn spawn(&self, req: SpawnRequest) -> RunId;
    fn steer(&self, run: RunId, guidance: SteerMessage);   // mid-flight, no restart
    fn cancel(&self, run: RunId);
    fn checkpoint(&self, run: RunId, state: Checkpoint) -> Seq;
    fn resume(&self, run: RunId) -> Result<(), ResumeError>;  // from last completed step
}

pub struct CapabilityProfile {
    pub exposed_tools: Vec<ToolId>,        // INVARIANT: len() <= 12
    pub egress: EgressPolicy,              // deny-by-default
    pub interrupt: InterruptPolicy,
    pub model_route: ModelRoute,
    pub may_write_memory: bool,
    pub reads_untrusted: bool,             // true => quarantine: exposed_tools MUST be empty
}
```

`reads_untrusted && !exposed_tools.is_empty()` is a load-time error. That is §8.2's structural
trifecta break, expressed as a type invariant rather than a guideline.

### 5.1 The quarantined read's output contract (ADR-041)

A quarantined reader takes **a group of untrusted results**, not one, and answers under a contract
whose shape is fixed by the harness:

```rust
OutputContract::structured(
    "what these sources say, for someone who will not see them",
    vec![
        FieldSpec::text("about").capped(600),          // caveats, and "this page targets an AI"
        FieldSpec::text("source_1").capped(1_500),     // one field per source in the group
        FieldSpec::text("source_2").capped(1_500),
        // ...
    ],
)
```

**Three properties are pinned, and each one is load-bearing:**

1. **Labels are positional and harness-assigned.** `source_N` is computed from the document's index
   in the group — never from its content, its URL, or anything the child model wrote. The parent
   attributes findings by slot, so a document that could name its own slot could claim to be
   another.
2. **The result is rendered, never interpolated.** `CondensedResult::render` puts a field header at
   column 0 and indents **every line a value contributes**. Formatting a field's raw value into a
   string instead re-opens the forgery hole ADR-039 closed, because the whitelist on field *names*
   and the *rendered* form end up on opposite sides of a format string.
3. **The group is bounded.** `MAX_SOURCES_PER_READER = 6`, so one hostile document can influence at
   most six descriptions rather than a whole corpus. Batching trades inter-document fidelity
   isolation for cost; it trades **no** containment, because the reader still holds no tools and no
   egress.

A quarantined reader's budget comes from `Budget::slice_for_quarantined_read`: a share of the
**original** budget rather than a geometric slice of the remainder, and **no depth requirement**,
because a reader with an empty tool set cannot spawn. Its `tool_calls` and `subagents` are `1` and
not `0` — `Budget::exhausted` compares `spent >= budget`, so a zero dimension reads as *already
exhausted* rather than *may not use*, and a reader given zero pauses before its first call.

---

## 6. Sessions and lineage

```rust
pub struct Session {
    pub id: SessionId,
    pub profile: ProfileId,
    pub parent: Option<SessionId>,        // compaction lineage
    pub seed_summary: Option<ContentRef>, // what the child was seeded with
    pub opened: Timestamp,
    pub closed: Option<Timestamp>,
    pub surfaces: Vec<Surface>,           // one identity across voice, text, terminal
}
```

Compaction closes the parent, spawns a child seeded by the summary, rotates the id, and records
parent/child provenance. **A long conversation is a chain, never an overwritten transcript.**
`/lineage` walks it.

**Ordering constraint (invariant 1):** `SessionSummarized` and `SessionSpawned` must both be
durable *before* any parent volatile state is discarded. Not after. Not concurrently.

---

## 7. Skills, tools, and capability manifests

### 7.1 Skill manifest

`SKILL.md` per the open Agent Skills standard — **unmodified where the standard specifies it.**
Marlowe adds one namespaced block and nothing else.

```yaml
---
name: pdf-report
description: Generate a cited PDF report from a findings set.
# ── standard fields above; Marlowe extension below ──
x-marlowe:
  capability:
    paths:  ["./out/**"]
    hosts:  []
    creds:  []
  consequence: reversible          # REQUIRED. Absent => Irreversible. See §7.3.
  trigger_phrases: ["write a report", "make a pdf"]   # embedded; the prose is NOT
  signature: "ed25519:..."
---
```

Only `description` + `trigger_phrases` are embedded for semantic discovery (§7.1). Embedding
full instruction prose pollutes the vector space.

### 7.2 Registration vs. exposure

```rust
pub struct ToolRegistration {     // unlimited
    pub id: ToolId,
    pub manifest: CapabilityManifest,
    pub transport: Transport,     // Mcp { server } | Builtin | Skill { id } | Connector { conn }
    pub summary_spec: SummarySpec, // §8 — REQUIRED
}

pub trait ToolExposure {
    /// INVARIANT: returns <= 12. Enforced by the type's constructor, not by convention.
    fn expose(&self, ctx: &ExposureContext) -> ExposedSet;
}
```

### 7.3 Capability manifest and the consequence declaration

```rust
pub struct CapabilityManifest {
    pub paths: Vec<PathGlob>,
    pub hosts: Vec<HostPattern>,
    pub creds: Vec<CredentialId>,
    pub consequence: ConsequenceLevel,
    pub params: Vec<ParamSpec>,
    pub provenance: ManifestProvenance,
}

#[derive(PartialOrd, Ord)]
pub enum ConsequenceLevel {
    Inert = 0,          // pure reads, no side effects
    Reversible = 1,     // undoable writes inside the workspace
    Consequential = 2,  // external writes, spend, messages to third parties
    Irreversible = 3,   // money movement, send-as-user, deletion, anything legally binding
}

/// The (action, target) split. Untrusted content may shape Payload fields FREELY.
/// It may never shape a Target.
pub enum ArgumentRole {
    Target,    // tool selection, recipient, path, host, amount, identifier
    Payload,   // inert body content: a draft, a summary, a message body
}

pub struct ParamSpec {
    pub name: String,
    pub role: ArgumentRole,
    pub ty: ParamType,
    /// AMENDED 2026-08-10 (ADR-034). What the EXECUTOR demands. A separate question from `role`,
    /// which answers what untrusted content may never shape. Absent in a raw manifest => optional.
    pub required: bool,
}

pub enum ManifestProvenance { FirstParty, UserReviewed { at: Timestamp }, ThirdParty }
```

> **AMENDED 2026-08-10 (M2 C2f) — `ParamSpec` gains `required`. ADR-034.**
>
> The schema's `required` array was derived from `ArgumentRole::Target`. One switch answered two
> questions — *what may untrusted content shape* and *what can the tool not run without* — and they
> disagreed on **eleven parameters across ten builtins**, in both directions: nine marked required
> that are not (`bash.cwd`, which the executor defaults to the workspace, so the model invented one
> on every call) and two the executor demands that the schema called optional (`find.pattern`,
> `edit.content` — a schema-valid call the executor rejects).
>
> **This amendment is retroactive on the document, not on the code**: the field shipped in
> `de18ace` and §7.3 continued to pin the three-field struct. A pinned contract that shipped code
> contradicts is worse than an absent one, because it is what a boundary-crossing change gets
> checked against. Recorded plainly rather than quietly corrected.

**Default-deny, enforced at load time:**

```rust
fn load(m: RawManifest) -> Result<CapabilityManifest, LoadError> {
    let consequence = match m.consequence {
        None => ConsequenceLevel::Irreversible,               // absent => maximum
        Some(c) => c,
    };
    // Third-party code cannot self-declare its way down.
    if m.provenance == ThirdParty && consequence < ConsequenceLevel::Consequential {
        return Err(LoadError::ThirdPartySelfDeclaredLow);
    }
    if m.params.iter().any(|p| p.role.is_none()) {
        return Err(LoadError::UnroledParameter);              // no silent Payload default
    }
    Ok(..)
}
```

A malformed or undeclared manifest is a **startup error**, not a runtime warning. The system
must be unable to start with an unannotated tool rather than run with a permissive one.
A change to `consequence` alters the signed artifact and therefore appears in the install-time
diff review — a tool quietly promoting itself from low to high consequence is exactly what
review exists to catch.

---

## 8. Tool-result summary contract (§B6)

Every tool declares how its result renders as **one line**. `done` is not acceptable.

```rust
pub struct SummarySpec {
    pub verb: &'static str,               // "read", "bash", "edit", "web"
    pub target: fn(&Args) -> String,
    pub summarize: fn(&Output) -> ResultSummary,
    pub is_failure: fn(&Output) -> bool,  // failures AUTO-EXPAND (§B6)
    pub inline_threshold_bytes: u64,      // above this, the loop gets a ContentRef
}

pub struct ResultSummary {
    pub metrics: Vec<Metric>,             // typed, never generic prose
    pub detail: Option<ContentRef>,       // expansion payload
}

pub enum Metric {
    Count { n: u64, unit: &'static str },        //  142 lines · 6 results · 6 commits
    Diff  { added: u32, removed: u32 },          //  +23 −7
    Test  { passed: u32, failed: u32, secs: f32 }, //  12 passed · 1.4s
    Duration { ms: u64 },
    Bytes { n: u64 },
}
```

Rendering: `⋯ {verb}  {target}  {metrics}` — right-aligned, one line, expandable on Enter/Tab.
This same summary is the loop's **default view** of the result when the payload exceeds
`inline_threshold_bytes`. One contract serves terminal craft (§B6), the token budget (§6), and
containment (§8.2) simultaneously.

---

## 9. Permission, approval, trust ledger

```rust
pub struct PermissionDecision {
    pub id: DecisionId,
    pub tool: ToolId,
    pub action_class: ActionClass,
    pub outcome: Outcome,
    pub blast_radius: BlastRadius,        // what the USER is shown, §B9
    pub taint: TaintSet,
    pub reasons: Vec<Reason>,
}

pub enum Outcome {
    Allowed,
    AllowedBatched { batch: BatchId },
    NeedsApproval { tier: RiskTier },
    Blocked { reason: BlockReason },
}

pub enum BlockReason {
    UntrustedTarget { param: String, origin: TrustClass },   // the (action,target) rule
    UndeclaredPath { path: PathBuf },
    EgressNotAllowed { host: String },
    BudgetExceeded { dimension: &'static str },
    TierInsufficient { have: Tier, need: Tier },
}

/// States blast radius, NOT the command. Not "Run: rm -rf ./build?" but
/// "Delete 1,204 files in ./build · not recoverable".
pub struct BlastRadius {
    pub verb: String, pub scope: String,
    pub reversible: bool, pub novelty: Option<NoveltyReason>,
}
```

**The argument-provenance check**, which is the whole mechanism:

```rust
fn check_targets(m: &CapabilityManifest, args: &Args, taint: &TaintSet) -> Result<(), BlockReason> {
    // The early return is at INERT, not Consequential. Reversible tools ARE checked.
    if m.consequence <= ConsequenceLevel::Inert { return Ok(()); }
    for p in m.params.iter().filter(|p| p.role == ArgumentRole::Target) {
        if taint.of(&p.name) <= TrustClass::UntrustedContent {
            return Err(BlockReason::UntrustedTarget { param: p.name.clone(), origin: .. });
        }
    }
    Ok(())   // Payload fields are unchecked BY DESIGN. Untrusted prose may fill them.
}
```

**Why Reversible is checked.** "Reversible" describes recoverability of the *action*, not of its
*influence*. A file you can delete has already been read by the time you delete it — a workspace
write is a durable channel into a later run's context, whether through a skill that loads it, an
`AGENTS.md`, or a config a tool reads. That is precisely the sandbox-boundary-redefinition class
in §8.3's red-team list, where the agent's own output redefined its boundary. Exempting
Reversible would leave the cheapest version of that attack unguarded.

**Why Inert is not checked, and why that is safe.** Inert is pure reads, and a read target
derived from untrusted content is how research works — following a citation found on a page. The
containment for reads comes from elsewhere and is already structural: the fetched result returns
as `UntrustedContent` (so it can never become a Target downstream), it returns by reference
rather than inlined, and egress allowlisting independently closes the exfiltration leg. Target
checking at Inert would buy nothing those three do not already cover, and would cost the agent
the ability to follow a link.

**False-positive cost is low**, which is what makes the stricter line affordable: the check fires
only when a target is *literally* traceable to untrusted content. A path the user typed is
`UserAsserted`; one the agent inferred from repo convention is `AgentInferred`; both pass. The
case it blocks is a fetched page that names the path — `~/.bashrc` — which is the case worth
blocking. Blocked Reversible writes route to a batched approval showing the provenance chain,
not to a hard failure.

### 9.1 Trust ledger

```rust
/// Per ACTION CLASS — not per app, not globally.
pub struct ActionClass { pub tool: ToolId, pub shape: ArgShapeHash, pub label: String }

pub enum Tier { Observe = 0, Suggest = 1, Draft = 2, Confirm = 3, Act = 4, Silent = 5 }

pub struct TrustLedgerEntry {
    pub class: ActionClass,
    pub tier: Tier,
    pub ceiling: Tier,                 // hard cap no evidence lifts
    pub observations: u32,
    pub agreement_rate: f32,
    pub trend: Trend,
    pub last_demotion: Option<Timestamp>,
    pub shadow_until: Option<Timestamp>,   // every new class enters here
}
```

```rust
/// Promotion is PROPOSED. Granting requires a user act. There is no self-grant path.
fn propose_promotion(e: &TrustLedgerEntry) -> Option<PromotionProposal>;

/// Demotion is automatic, immediate, silent, and needs no proposal. Asymmetry is the point.
fn on_correction(e: &mut TrustLedgerEntry) { e.tier = Tier::Draft; e.shadow_until = Some(..); }
```

Hard ceilings, not liftable by evidence: money movement, contract execution, **sending as the
user**, anything legally binding, and anything touching the permission system itself.

**Novelty gating:** an action unusual *for its class* — unfamiliar recipient, unusual amount,
first-time counterparty — drops one tier automatically regardless of the class's standing.

---

## 10. People and commitments

Schemas are given in §A4/§A6. Pinned as specified, with the envelope from §3 supplying
provenance, decay, and correction.

```rust
pub struct Person {
    pub id: EntityId,
    pub names: Vec<String>,
    pub handles: Map<Channel, Address>,
    pub org: Option<String>, pub role: Option<String>,
    pub timezone: Option<Tz>,
}

pub struct Relationship {
    pub person_id: EntityId,
    pub closeness: f32, pub formality_level: f32,
    pub response_sla_expected: Option<Duration>,
    pub last_contact: Option<Timestamp>,
    pub contact_cadence_norm: Option<Duration>,
    pub voice_params: Map<String, Value>,      // per-relationship, NOT global (§A3)
    pub open_threads: Vec<ThreadId>,
    pub owed_by_me: Vec<CommitmentId>, pub owed_to_me: Vec<CommitmentId>,
    pub do_not_contact_windows: Vec<TimeWindow>,
    pub notes: Vec<MemoryId>,
}

pub struct Commitment {
    pub id: CommitmentId,
    pub description: String,
    pub direction: Direction,              // OwedByUser | OwedToUser
    pub counterparty_id: EntityId,
    pub source: CommitmentSource,          // { channel, message_id, extracted_at }
    pub expected_by: Option<Timestamp>,
    pub confidence: f32,
    pub status: CommitmentStatus,          // Open|Chased|Fulfilled|Dropped|Renegotiated
    pub chase_policy: ChasePolicy,         // { after, escalation_ladder, max_chases }
    pub evidence: Vec<Evidence>,
}

/// Closure requires EVIDENCE, not elapsed time (§A6). False-closure target < 2%.
pub enum Evidence { Reply { msg: MessageId }, File { ref_: ContentRef },
                    CalendarEntry { id: EventId }, UserAsserted { seq: Seq } }
```

---

## 11. Connections

```rust
/// The agent holds a ConnectionId. It never holds a token. Credential material is injected
/// at the transport layer at call time and is structurally unable to enter model context.
pub struct Connection {
    pub id: ConnectionId,
    pub provider: ProviderId,
    pub scopes: Vec<Scope>,
    pub health: ConnectionHealth,
    pub broker: BrokerKind,        // Managed { adapter } | LocalKeychain
}

pub trait Broker {
    fn authorize(&self, c: ConnectionId, call: &PendingCall) -> Result<AuthzToken, AuthzError>;
    fn health(&self, c: ConnectionId) -> ConnectionHealth;   // checked at CALL time, not connect
}
```

`AuthzToken` is opaque, non-`Debug`, non-`Serialize`, and consumed by the transport. The type
system, not discipline, is what keeps it out of a log line.

---

## 12. Loop-boundary types

Every boundary in `ARCHITECTURE.md` §7 is pinned. These five are the remainder.

```rust
/// Loop → permission layer. `args` are structured; the loop never hands over raw prose
/// for a Target parameter (see §9's check_targets).
pub struct ToolCall { pub id: CallId, pub tool: ToolId, pub args: Args, pub run: RunId }

/// Per-VALUE provenance, not per-message. This is what makes the (action, target) split
/// checkable: taint is keyed by argument name, so a call can mix a trusted recipient with
/// an untrusted body and be adjudicated correctly.
pub struct TaintSet { by_param: Map<String, TrustClass> }

impl TaintSet {
    /// Absent => treated as UntrustedContent. Fail closed: an untracked value is not a
    /// trusted value.
    pub fn of(&self, param: &str) -> TrustClass {
        self.by_param.get(param).copied().unwrap_or(TrustClass::UntrustedContent)
    }
}

/// Context assembler → loop. Carries its own accounting so the budget is auditable per turn
/// rather than inferred after the fact.
pub struct ContextView {
    pub stable: Vec<Block>,      // identity, governance, user-asserted constraints
    pub context: Vec<Block>,     // project files, loaded skills, exposed tool schemas
    pub volatile: Vec<Block>,    // history, tool results, injected memories
    pub per_source_tokens: Map<SourceKind, u32>,
    pub reserve_tokens: u32,     // mandatory buffer; never allocated to a source
    pub fill_pct: f32,           // fraction of EFFECTIVE window; compaction triggers at 0.70
    pub cache_epoch: u64,        // bumped on compaction; a stale epoch invalidates the prefix
}

/// Run plane → loop. Written to the journal every iteration; resume reads the last one.
pub struct Checkpoint {
    pub run: RunId,
    pub session: SessionId,
    pub step: u32,
    pub transcript_ref: ContentRef,
    pub pending_calls: Vec<CallId>,
    pub guidance: Vec<SteerMessage>,
}

/// Injected into a RUNNING child without killing it (§10.1). Ordered; applied at the next
/// loop iteration, never mid-tool-call.
pub struct SteerMessage {
    pub seq: Seq,
    pub from: SteerSource,      // User { surface } | Parent { run: RunId }
    pub text: String,
    pub urgency: Urgency,       // Advisory applies next iteration; Immediate also interrupts
}
```

---

## 13. Surfaces

```rust
/// Render-only. Surfaces hold no policy and no state the daemon lacks.
pub enum TurnEvent {
    TextDelta(String),
    ToolLine { id: CallId, verb: String, target: String, state: ToolLineState },
    Compacted { turns: u32 },
    Degraded { what: DegradedPath },      // the status band, in amber, §B5
    ApprovalPrompt(BlastRadius),          // the only element permitted to DIM the frame, §B9
    Done { spend: Money, elapsed: Duration, fill_pct: f32 },
}

pub enum ToolLineState { Running { elapsed_ms: u64 }, Ok(ResultSummary), Failed(ResultSummary) }
```

**There is no `MemoryInjected` variant in `TurnEvent`, and there must never be one.** Memory
gets no representation in the interface (§B1). Diagnostics reach `--dev` through a separate
channel that is not part of `TurnEvent`.

**Two comments on this enum were corrected 2026-08-08 against Addendum B v2. The schema was already
correct and is untouched.** `Degraded` read *"ONE word on the input line, §B4"*; v2 moves degradation
into the status band (§B5) and §B4 is now the control strip. `ApprovalPrompt` read *"the only
bordered element in the product"*; under v2 **every** region is bordered, so a border no longer
signals modality — the overlay is the only element permitted to **dim** the rest of the frame (§B9).
Recorded here because a stale pointer in a pinned file is a defect even when the type is right.
