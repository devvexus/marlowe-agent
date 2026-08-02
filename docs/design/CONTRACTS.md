# Marlowe — Pinned Contracts

**Status:** Pinned. **If one of these is wrong, stop and raise it. Never silently change a
schema** — other work depends on it, and future sessions build against these in parallel
without seeing each other.

Normative notation is Rust. Boundaries that cross a process or language line additionally pin
a JSON wire format, and the JSON is normative for those.

**Versioning.** Every contract carries `CONTRACT_VERSION`. A breaking change requires a new
major version and an entry in `DECISIONS.md`; the old version must remain readable for one
major cycle because the journal is append-only and old events must stay replayable forever.

```rust
pub const CONTRACT_VERSION: (u16, u16) = (1, 0);
```

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
    pub signature:  Signature,          // HMAC over (seq, ts, trace, actor, kind, payload)
}

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

---

## 4. Retrieval and the injection gate — the M0a↔M0b boundary

**This interface is load-bearing for the M0a/M0b split.** M0a (the eval harness) is built
against it *without knowledge of the retriever*, so it is pinned here, in this document,
before either exists. JSON is normative — the scorer is Python, the implementation is Rust.

### 4.1 Request

```json
{
  "contract_version": "1.0",
  "query_id":   "q-0041",
  "session_id": "s-7",
  "turn_index": 3,
  "query_text": "why is the ingest job timing out again",
  "now_ms":     1785312000000,
  "budget":     { "max_tokens": 7000, "max_latency_ms": 300 }
}
```

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

### 4.2b Rust binding

The JSON above is **normative** for this boundary — M0a is Python and M0b is Rust, so the wire
format is the contract and these types are its binding, not the other way round.

```rust
pub struct RetrievalRequest {
    pub query_id: QueryId, pub session_id: SessionId, pub turn_index: u32,
    pub query_text: String, pub now: Timestamp, pub budget: RetrievalBudget,
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
```

`cost` being non-optional in the type is the point: §5.7's *"report the pair"* cannot be
forgotten if a result without its cost cannot be constructed.

### 4.3 Candidate-set contract

```rust
/// Auto-injection reads the LIVE-ONLY hot index. This is a REQUIREMENT, not an optimization:
/// see DECISIONS.md ADR-003 and the measured curve.
pub fn injection_candidates(ix: &IndexSet) -> CandidateSet {
    ix.hot()          // fidelity > Tombstone AND superseded_by IS NULL, by construction
}

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
property, and only one of them is the target. See `DECISIONS.md` HP1.

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

pub struct ParamSpec { pub name: String, pub role: ArgumentRole, pub ty: ParamType }

pub enum ManifestProvenance { FirstParty, UserReviewed { at: Timestamp }, ThirdParty }
```

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

## 8. Tool-result summary contract (§B3)

Every tool declares how its result renders as **one line**. `done` is not acceptable.

```rust
pub struct SummarySpec {
    pub verb: &'static str,               // "read", "bash", "edit", "web"
    pub target: fn(&Args) -> String,
    pub summarize: fn(&Output) -> ResultSummary,
    pub is_failure: fn(&Output) -> bool,  // failures AUTO-EXPAND (§B3)
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
`inline_threshold_bytes`. One contract serves terminal craft (§B3), the token budget (§6), and
containment (§8.2) simultaneously.

---

## 9. Permission, approval, trust ledger

```rust
pub struct PermissionDecision {
    pub id: DecisionId,
    pub tool: ToolId,
    pub action_class: ActionClass,
    pub outcome: Outcome,
    pub blast_radius: BlastRadius,        // what the USER is shown, §B6
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
    if m.consequence < ConsequenceLevel::Consequential { return Ok(()); }
    for p in m.params.iter().filter(|p| p.role == ArgumentRole::Target) {
        if taint.of(&p.name) <= TrustClass::UntrustedContent {
            return Err(BlockReason::UntrustedTarget { param: p.name.clone(), origin: .. });
        }
    }
    Ok(())   // Payload fields are unchecked BY DESIGN. Untrusted prose may fill them.
}
```

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
    Degraded { what: DegradedPath },      // ONE word on the input line, §B4
    ApprovalPrompt(BlastRadius),          // the only bordered element in the product
    Done { spend: Money, elapsed: Duration, fill_pct: f32 },
}

pub enum ToolLineState { Running { elapsed_ms: u64 }, Ok(ResultSummary), Failed(ResultSummary) }
```

**There is no `MemoryInjected` variant in `TurnEvent`, and there must never be one.** Memory
gets no representation in the interface (§B1). Diagnostics reach `--dev` through a separate
channel that is not part of `TurnEvent`.
