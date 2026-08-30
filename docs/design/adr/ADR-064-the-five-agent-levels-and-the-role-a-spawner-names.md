# ADR-064 · The five agent levels are a field on the profile, the disposition is carried inside the level, and the role a spawner names ships only as far as its reader chain reaches

**Status:** PROPOSED — needs the human's approval. DESIGN ONLY, NO CODE.

Two §13-guarded files are edited (`crates/marlowe-loop/src/profile.rs`, `crates/marlowe-loop/src/driver.rs`), two pinned contracts move (`CONTRACTS.md` §5's `CapabilityProfile`, and `SpawnRequest` pinned for the first time), and one item below is the human's by name (the fourth `ModelRoute` variant). Nothing here has been approved by anyone and no code has been written against it.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | nothing yet. If accepted it obliges an edit to `CONTRACTS.md` §5 (§7 below), which also corrects two **already-stale** lines there that are unrelated to this decision |
| **Depends on** | M3-DESIGN §1, §1.1–§1.4, §3.1, §3.4; ADR-008 (tiered routing and its 2026-08-10 amendment); ADR-023 (the `(action, target)` latch); ADR-041 (the group unit and the zero-budget lesson); ADR-044 (the embedder resolves its provider against free VRAM at load); ADR-057 (who declares a child's contract, and §5's withheld fields); ADR-058 (`MAX_EXPOSED_TOOLS = 14`); ADR-062 (the label-before-the-reader order); SECURITY-AUDIT H2 and H4 |
| **Contract change** | **Yes, two.** `CapabilityProfile` gains a seventh field pinned by membership; `SpawnRequest`'s whole shape is pinned for the first time. Both are escalated, not taken — M3-D1's precedent |
| **Code change** | **None. Nothing in this ADR has been built.** Every line number and count below was read at HEAD `03fb1d6` |

---

## 1 · The question, and the finding that decides how much of it may be answered

M3-DESIGN §1 states five levels and three structural rules about them — a master holds no working tools, a tool-spawned agent holds none at all, and Marlowe spawns exactly one kind of thing. None of the three exists in the code. Separately, AGENT-DIRECTORY §2 and ADR-008 want the spawner to name which model serves a child. The question this ADR answers is how both arrive without shipping a declaration nothing reads.

**The finding that constrains the answer: the model-routing chain is already broken in two places, and adding a third link at the top would be instance #16 for the third time in one code path.** Measured at HEAD `03fb1d6`:

```
$ grep -rn "model_route()" --include=*.rs crates/
crates/marlowe-loop/src/profile.rs:280:    pub fn model_route(&self) -> ModelRoute {

$ grep -rn "Routing::new" --include=*.rs crates/
crates/marlowe-provider/src/routing.rs:118:        let r = Routing::new("qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b").unwrap();

$ grep -rn "ModelRoute::Summarizer" --include=*.rs crates/
crates/marlowe-provider/src/routing.rs:71:            ModelRoute::Summarizer => &self.summarizer,
crates/marlowe-provider/src/routing.rs:121:        assert_eq!(r.model_for(ModelRoute::Summarizer), "qwen3.5:2b");
```

The accessor's only hit is its own definition — **zero readers**. `Routing::new`'s only hit is a unit test — **zero production callers**; every production site is `Routing::uniform`, which answers one model for all three roles. `ModelRoute::Summarizer`'s only hits are the match arm that consumes it and the unit test that asserts on it — **zero producers**. And `crates/marlowe-provider/src/ollama.rs:300` reads

```rust
let model = self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator).to_string();
```

so the model on the wire is a constant. `profile.rs:456` asserts `"model_route": "worker"` — the value of the field, not the fate of a byte, which is `inline_threshold_bytes` exactly (instance #16).

**So `role` lands with its chain or it does not land.** That judgment is the design's and it is correct. What follows is what the chain can actually reach, which is less than the design claimed and less than its critique claimed.

### 1.1 · The citation audit, including the correction that was itself wrong

The adversarial critique's first useful act was to re-measure the design's line numbers and find five of five wrong. It did not re-measure the rest, and one of its own corrections is an error. Both commits below were read with `git show`, so the drift question is settled rather than argued: **`crates/marlowe-loop/src/engine.rs` is byte-identical on all six anchors at `186b5d5` and at `03fb1d6`.**

| Anchor | Design says | Critique says | Actual at `186b5d5` **and** `03fb1d6` |
|---|---|---|---|
| `Routing::uniform` in `daemon.rs` | 1196, 1271, 1436, 1780, 1867 | **1263, 1338, 1503, 1889, 1976** | **1263, 1338, 1503, 1889, 1976** — critique right |
| `crates/marlowe/src/agent.rs` | not mentioned | `:47` | **`:47`** — critique right, and it is a sixth production site |
| the hardcoded `ModelRoute::Worker` in `Engine::spawn` | 2654 | 2654 | **2654** — both right |
| the spawn receipt's format string | 2755 | 2755 | **2728** |
| the child's swallowed `Escalated` | 2935 | 2935, *"Verified at"* | **2944** |
| `Engine::spawn` | 2530–2680 | 2530–2680 | **2528** |
| the quarantined child's `Run::child` | 2146 | 2146 | **2150** |
| `composes_spawn_targets` | 3237 | **"3227, not 3237"** | **3237 — the design was right and the correction introduced the error** |

Four of the design's citations were repeated by its critique without being checked, and one correct citation was "corrected" into a wrong one. This is instance #14's family aimed at a document: a claim about a path with nothing checking it. **The rule this ADR adopts, from ADR-062's Verification section: cite a symbol where a line number would be an unverified claim, and give a line number only where it was read this session.** Every line number in this file was read at `03fb1d6`.

**And the point proved itself before this ADR was finished.** Every number in the table above was read from the committed tree at `03fb1d6`. Within the same session, another agent's uncommitted edits to `crates/marlowe-loop/src/engine.rs` moved all five anchors again — the receipt to 2758, the swallowed `Escalated` to 2993, `Engine::spawn` to 2558, the quarantined child to 2180, `composes_spawn_targets` to 3335. **Nothing in this ADR's reasoning changes and every number in it is stale in the working tree**, which is precisely why they are stated with the commit they were read at and why the symbol name is the durable half of each citation. Verify with `git show 03fb1d6:<path>`, never with a bare `grep` over a checkout two sessions are writing to.

The `profile.rs` citations drift the same way and are corrected here in place: `consolidation()` is at **156** (design: 141), `quarantined_reader()` at **142** with its `ModelRoute::Worker` at **147** (design: 150), `narrowed()` at **332** with its hardcoded `ModelRoute::Worker` at **342** (design: 331 and 344), `interactive()` at **173** and `interactive_with()` at **257** (both right). The argument for holding a widening inside the type that owns the invariant lives in `grant_egress_host`'s doc comment at **296–325** — the design cited 190–215, the critique 300–322.

---

## 2 · The decision

### 2.1 · `AgentLevel` is a private, constructor-validated field on `CapabilityProfile`, and the disposition is carried **inside** the level

`crates/marlowe-loop/src/profile.rs` — **§13-guarded. A human must approve this file's edit.**

```rust
/// M3-DESIGN §1. **Position in the organisation, not capability.** Capability is the
/// `ExposedSet`; this is what constrains which sets are constructible.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLevel {
    Secretary,
    /// §1.1: Marlowe spawns exactly one kind of thing and declares *which kind it is*.
    /// `manages` IS that declaration, carried in the level so it cannot be recorded and
    /// then ignored — which is what a separate `disposition` field beside the level was.
    TopAgent { manages: bool },
    Master,
    Worker,
    ToolSpawned,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition { Work, Manage }

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("a {parent:?} cannot create a {wanted:?} child: Marlowe creates only top-agents, a \
         top-agent creates only if it was spawned to manage, a master creates only workers, \
         and a worker creates nothing")]
pub struct LevelRefusal { pub parent: AgentLevel, pub wanted: Disposition }

impl AgentLevel {
    /// **Total over the level axis, no wildcard.** A sixth level fails to compile here.
    /// It NEVER returns `ToolSpawned` — that level is reachable only through the harness's own
    /// named constructors, so no model call can produce one. Withheld structurally (#17).
    ///
    /// **Total over MODEL-INITIATED spawns only.** The harness's own children — the quarantined
    /// reader built by `CapabilityProfile::quarantined_reader()` at `engine.rs:2150`, and
    /// SCOPED-MEMORY §4's fact extractor — are built by named constructor and are never routed
    /// through here, so §1's level 5 sits under any of levels 1–4. `Budget.depth` still bounds
    /// that path and is never 0 on it.
    pub fn child_of(parent: AgentLevel, d: Disposition) -> Result<AgentLevel, LevelRefusal> {
        use AgentLevel::*; use Disposition::*;
        match (parent, d) {
            // §1.1: both arms answer "a top-agent" — but they are DIFFERENT top-agents.
            (Secretary, Manage) => Ok(TopAgent { manages: true }),
            (Secretary, Work)   => Ok(TopAgent { manages: false }),
            (TopAgent { manages: true }, Manage) => Ok(Master),
            (TopAgent { manages: true }, Work)   => Ok(Worker),
            // §1's table: level 3 is "spawned by a top-agent WITH THE CREATE GRANT".
            (TopAgent { manages: false }, _) => Err(LevelRefusal { parent, wanted: d }),
            (Master, Work) => Ok(Worker),
            (Master, Manage) | (Worker, _) | (ToolSpawned, _) =>
                Err(LevelRefusal { parent, wanted: d }),
        }
    }

    /// One definition of "which levels may hold the create grant", read ONLY by
    /// `CapabilityProfile::new`. There is no second consultation at the spawn gate.
    fn may_hold_create_grant(self) -> bool {
        matches!(self, Self::Secretary | Self::TopAgent { manages: true } | Self::Master)
    }
}
```

Three new load-time errors, and the checks that raise them, appended to `CapabilityProfile::new` after the existing quarantine checks:

```rust
if exposed_tools.contains(&ToolId::new("run")) && !level.may_hold_create_grant() {
    return Err(ProfileError::CreateGrantNotHeldAtThisLevel { level });
}
match level {
    AgentLevel::ToolSpawned if !exposed_tools.is_empty() =>
        return Err(ProfileError::ToolSpawnedWithTools { count: exposed_tools.len() }),
    AgentLevel::ToolSpawned => {}
    AgentLevel::Master => {
        for t in exposed_tools.iter() {
            if !marlowe_tools::MANAGEMENT_TOOLS.contains(&t.as_str()) {
                return Err(ProfileError::MasterHoldsWorkingTool { level, tool: t.clone() });
            }
        }
    }
    // §1's table says "full conversational set". Whether §1.2's structural rule extends to
    // level 1 is a question M3-DESIGN §1 does not answer, and `interactive()` currently holds
    // `bash`, `edit`, `write` and `web`. NAMED rather than swept into `_`, so the answer is
    // visible and escalable. See ADR-064 §9 item 4.
    AgentLevel::Secretary => {}
    // Per-type sets are §1.3 configuration, not a constructor rule.
    AgentLevel::TopAgent { .. } | AgentLevel::Worker => {}
}
```

**There is no wildcard arm.** A sixth `AgentLevel` variant is a compile error here, which is the #19-safe shape: the check's coverage is not a list it maintains.

`ToolSpawnedWithTools` is **strictly wider than the existing quarantine check** and that width is the point: SCOPED-MEMORY §4's fact extractor is a tool-spawned agent that does *not* set `reads_untrusted`, so today nothing would stop it being constructed with tools.

`may_create_agents` has **one** definition and it reads the set:

```rust
pub fn level(&self) -> AgentLevel { self.level }

/// **The create grant IS holding `run`.** `new` above guarantees no profile at a level which
/// may not hold it contains it, so there is nothing else to consult.
pub fn may_create_agents(&self) -> bool {
    self.exposed_tools.contains(&ToolId::new("run"))
}
```

**All five named constructors get an explicit level**, not two: `quarantined_reader() -> ToolSpawned`; `consolidation() -> Worker`; `interactive() -> Secretary`; `interactive_with() -> Secretary`; and `narrowed(tools, level)` takes it explicitly, with its hardcoded `ModelRoute::Worker` at `profile.rs:342` becoming `self.model_route` — a narrowing does not change which model serves the run. `narrowed` has **zero production callers** (`grep -rn "\.narrowed(" crates/ --include="*.rs"` returns four hits, all in `crates/marlowe-daemon/tests/composition_root.rs` and `profile.rs`'s own unit tests), so that last change is currently unobservable and its doc comment must say so.

`Raw` gains `level: AgentLevel` with **no `#[serde(default)]`**. A checkpoint written before this lands fails to deserialize with a named serde error. That is a real cost against Session A's shipped resume and it is the human's to accept (§9 item 5), not a footnote — but a default here would silently restore a master holding working tools, which is the "defaults that make a mismatch unobservable" family at a security invariant.

### 2.2 · `MANAGEMENT_TOOLS` lists only tools that exist

`crates/marlowe-tools/src/builtin.rs` — **not §13-guarded** (confirmed: `python .claude/hooks/protect-boundaries.py --list-protected` lists `crates/marlowe-tools/src/pin.rs`, not `builtin.rs`).

```rust
/// M3-DESIGN §1.2's master set, as names. **The one definition.** §1.2 names eight
/// capabilities — communicate, question, answer, meeting control, todo management,
/// create/delete agent, budget allocation, escalate — and six do not exist. Naming them here
/// would make the master rule vacuously permissive: instance #16 in a constant.
pub const MANAGEMENT_TOOLS: [&str; 2] = ["run", "ask"];
```

**No `escalate` builtin.** `crates/marlowe-tools/src/builtin.rs:36` is `pub const BUILTIN_TOOLS: [&str; 12]` and `builtin.rs:749` asserts `assert_eq!(BUILTIN_TOOLS.len(), 12, ...)`; `crates/marlowe-tools/src/exposure.rs:35` is `pub const MAX_EXPOSED_TOOLS: usize = 14` and `interactive()` holds twelve (`"read", "write", "edit", "glob", "grep", "bash", "web", "recall", "use", "ask", "remember", "run"`). A thirteenth builtin spends one of the exactly two MCP slots ADR-058 raised the cap to protect. When `escalate` lands it arrives with `[&str; 13]`, the updated assertion and its message, an executor (or `verify_every_exposed_tool_is_runnable` refuses exposure), and either a named halving of the MCP allowance or an ADR-058 amendment — the human's.

### 2.3 · `SpawnRequest` gains `role` and `disposition`, both declared **Targets**

`crates/marlowe-loop/src/driver.rs` — **§13-guarded. A human must approve this file's edit.**

```rust
pub struct SpawnRequest {
    // task, contract, orphan, share, grant_tokens, tools, tools_declared, reads_untrusted
    /// **Which model serves the child.** `ModelRoute`, not a second enum. A **Target** under
    /// ADR-023: it decides capability and spend, and a downgrade ("make it dumber before an
    /// attack") and an upgrade ("burn the budget") are both attacker-useful. Default `Worker` —
    /// the CHEAP end, so forgetting the field costs nothing.
    pub role: ModelRoute,
    /// §1.1's one question: *can one agent do this alone?* A **Target**: it decides whether the
    /// child may hold the create grant, through `AgentLevel::child_of`.
    pub disposition: Disposition,
}

fn parse_role(s: &str) -> ModelRoute {
    match s.trim().to_ascii_lowercase().as_str() {
        "orchestrator" => ModelRoute::Orchestrator,
        "summarizer"   => ModelRoute::Summarizer,
        _              => ModelRoute::Worker,
    }
}
fn parse_disposition(s: &str) -> Disposition {
    match s.trim().to_ascii_lowercase().as_str() {
        "manage" | "master" => Disposition::Manage,
        _                   => Disposition::Work,
    }
}
```

Both are read from `args`, not withheld. ADR-057 §5 withholds `share` and `reads_untrusted` because a model naming them reaches a security control directly; here the requirement is literally *"the spawner names the model"* and the spawner of a delegated task is a model. The security answer is the Target declaration plus the receipt.

`composes_spawn_targets` at **`engine.rs:3237`** gains two disjuncts:

```rust
fn composes_spawn_targets(req: &SpawnRequest) -> bool {
    !req.tools.is_empty()
        || req.grant_tokens.is_some()
        || !matches!(req.orphan, OrphanPolicy::Terminate)
        || req.role != ModelRoute::Worker
        || req.disposition != Disposition::Work
}
```

Its doc comment must record the limitation it inherits rather than presenting the disjuncts as complete: **the function reads the value, not the declaration.** A latched run that types `model_role: worker` is indistinguishable from one that named nothing. That is the existing choice for the other three fields and it is stated so nobody reads this as more than it is.

**The receipt carries the role.** `engine.rs:2728`'s format string becomes

```rust
"[spawned] role: {role} · {disposition} · tools: {granted_tools} · budget: {} tokens · orphan: {} · returns: {}"
```

with both rendered from the harness's own enums, never from `args`. This is not decoration: `SpawnRequest::from_args`'s own doc comment already argues that its totality is safe *"because `Engine::spawn` echoes what it granted into the parent's window — a default a model cannot see is the 'defaults that make a mismatch unobservable' family, and the receipt is what closes it."* The receipt at HEAD prints tools, budget, orphan and returns, and no role. **Extending the default rule to two more fields without extending the receipt would be relying on a mitigation that does not exist for them.**

---

## 3 · Where every field is read, and the two that are dropped

Instance #16 is this project's most-repeated defect. Each field this ADR introduces is listed with **the function that reads it**, or is dropped.

| Field / item | The function that reads it | What breaks if the reader goes |
|---|---|---|
| `CapabilityProfile.level` | `CapabilityProfile::new` — three match arms and the create-grant check; `AgentLevel::child_of` via `Engine::spawn` | A master is constructible holding `edit`; §1.2 becomes an instruction |
| `AgentLevel::may_hold_create_grant` | `CapabilityProfile::new`, **and nowhere else** | A worker profile holding `run` is constructible |
| `CapabilityProfile::may_create_agents()` | `Engine::spawn`, as its **first** refusal | The gap that exists today (§4.2) stays open |
| `SpawnRequest.disposition` | `AgentLevel::child_of` — **and the two arms differ** (`TopAgent{manages:true}` vs `{false}`), which is what the first design lacked | Every top-agent may create agents regardless of what was declared |
| `SpawnRequest.role` | passed to `CapabilityProfile::new` at `engine.rs:2654` in place of the hardcoded `ModelRoute::Worker`; then `composes_spawn_targets` at `engine.rs:3237`; then the chain in §4 | Every child runs on whatever `Routing` answers for `Worker`, and a latched run may choose a child's model |
| `CallLimits.route` | `OllamaDriver::request_body` at `ollama.rs:300`, replacing the `ModelRoute::Orchestrator` constant | The chain ends one link short of the wire |
| `CapabilityProfile::model_route()` (**exists, zero readers today**) | `engine.rs:794` — `run.budget.call_limits(&run.spent, run.profile.model_route())`. This is the accessor's **first** reader | It is already effectively removed |
| `MANAGEMENT_TOOLS` | `CapabilityProfile::new`'s `Master` arm | §1.2's stated failure goes live |
| **`EscalationTarget` / `escalation_target`** | **DROPPED — no reader.** See §5.3 | — |
| **`may_hold_create_grant` as a second conjunct in `may_create_agents`** | **DROPPED — redundant with the constructor.** See §5.4 | — |
| **`ModelRoute::Summarizer` as a configured third column** | **GATED — no producer.** See §4.3 | — |

`CallLimits`'s field is **private** with an accessor, and `Budget::call_limits(&self, spent, route)` becomes its only production constructor:

```rust
pub struct CallLimits { max_output_tokens: u64, route: ModelRoute }
impl CallLimits {
    pub fn max_output_tokens(&self) -> u64 { self.max_output_tokens }
    pub fn route(&self) -> ModelRoute { self.route }
    #[cfg(any(test, feature = "test-util"))]
    pub fn for_test(max_output_tokens: u64, route: ModelRoute) -> Self { /* .. */ }
}
```

A public `route` would be a second way to name a model the run's profile did not declare — the objection `grant_egress_host`'s doc comment (`profile.rs:296–325`) makes against holding the granted egress set on the `Run`, with a struct literal instead of `serde`. **The migration cost is larger than the design stated.** The design said *"~8 struct-literal sites across four crates"*; measured:

```
$ grep -rn "CallLimits { max_output_tokens" crates/ --include="*.rs" | grep -v "src/budget.rs" | wc -l
23
```

**23 sites across six directories** — `marlowe-provider/tests` (8), `marlowe-openrouter/tests` (4), `marlowe-daemon/tests` (2), `marlowe-loop/tests` (1), `marlowe-openrouter/examples` (1), and the remainder spread across the same trees. That does not change the decision; it changes the size of the diff, and a number stated three times too small is how a session runs out of time.

---

## 4 · The reader chain, and the three places it stops — two of which neither the design nor its critique found

The chain: **`SpawnRequest.role` → `engine.rs:2654` → the child's `profile.model_route()` → `engine.rs:794` → `CallLimits.route` → `ollama.rs:300`.** `engine.rs:794` is the sole call site of `Budget::call_limits` in the workspace (`grep -rn "call_limits" crates/ --include="*.rs"` returns the definition at `budget.rs:144`, three unit-test calls inside `budget.rs`, and `engine.rs:794`), and children are driven through the same loop, so the chain is real as far as it goes.

### 4.1 · It stops at `Routing::uniform`, deliberately, and this is said out loud

```
$ grep -rn "Routing::uniform" crates/ --include="*.rs" | grep "/src/"
crates/marlowe/src/agent.rs:47
crates/marlowe-daemon/src/daemon.rs:1263, 1338, 1503, 1889, 1976
```

Six production sites, and `Routing::uniform` collapses all three roles onto one model name. Another agent is editing `crates/marlowe-daemon/src/daemon.rs` in this session, which is hazard forms 3, 4 and 5 in CLAUDE.md's parallel-sessions table, and the design's five stale line numbers are precisely what a concurrent edit produces. **So no `daemon.rs` edit is prescribed here.**

When the daemon edit lands it is **one function, not six sites**: `impl Daemon { fn routing(&self) -> Result<Routing, RoutingError> }`, called by all five daemon sites; `agent.rs:47` keeps `uniform` explicitly with a comment saying a one-shot CLI has no role table. Prescribing six independent edits is itself the defect — a test can only exercise the site its fixture reaches, so a missed site stays green forever. The guard is `the_daemon_builds_its_routing_in_exactly_one_place`, which greps `crates/marlowe-daemon/src/*.rs` for `Routing::uniform(`, asserts zero hits and prints the count: its input is the source tree, not a list it maintains (#19-safe).

Until then, `Orchestrator` and `Worker` resolve to the same string in the shipped binary, and the wire test is `#[ignore]` with a header naming exactly what is missing. **An ignored test whose header says why is honest; a green one over a half-chain is #16.**

### 4.2 · A second, unrelated gap the chain exposes: nothing checks that a spawner holds `run`

`crates/marlowe-provider/src/ollama.rs:1045` is `"run" => ModelStep::Spawn(marlowe_loop::SpawnRequest::from_args(args))`. `Engine::spawn` (from `engine.rs:2528`) checks the task, `tools_declared`, composed targets, the budget grant, the subagent count and the narrowing against the parent's set — and **never checks that the parent's exposed set contains `run`**, because `ModelStep::Spawn` does not reach `adjudicate`, which is where the exposure check lives.

This is **SECURITY-AUDIT H2's gap applied to `run`, not a new finding**, and H2's own parenthetical is stale: it says *"`run` was deliberately routed back through `ToolCall` for exactly this reason"*, which `ollama.rs:1045` contradicts at HEAD. Cite H2. Do not file it as new — that would be the third re-derivation this milestone has produced.

### 4.3 · `ModelRoute::Summarizer` is configured and never selected, so two routes ship wired and the third stays gated

After this change `Summarizer` is producible only by a model typing `model_role: summarizer` into a `run` call — and `composes_spawn_targets` refuses exactly that under a latched floor. The daemon's table therefore ships with **`Orchestrator` and `Worker` selected by real code paths**, `models().len() == 2` asserted from `Daemon::routing()`, and the third column `uniform`-fed until the human answers whether `quarantined_reader()` should carry `ModelRoute::Summarizer`. It is the only credible producer — condensation is its whole job — but ADR-008's own 2026-08-10 amendment says compression is not extraction, and that is the human's question, not a session's (§9 item 3).

### 4.4 · **NEW, and neither document has it: `ollama.rs:242` is a second `ModelRoute::Orchestrator` hardcode, and it is the one this chain cannot fix**

```rust
// crates/marlowe-provider/src/ollama.rs:241-244, in OllamaDriver::new
let capability = ModelCapability::unmeasured(routing.model_for(
    marlowe_loop::ModelRoute::Orchestrator,
));
```

The driver's `capability` — and, separately, its `context_tokens`, which starts at `DEFAULT_CONTEXT_TOKENS` and is set per **daemon config** by `with_context_tokens` at `daemon.rs:2121`, `:2288` and `:2375` — are **per-driver, set once**. `request_body` sends `"num_ctx": self.context_tokens` at `ollama.rs:545`. So after this change one request body carries a **`model` chosen per call** and a **`num_ctx` chosen per process**.

`ollama.rs:230–237` describes exactly this failure, in its own words, as the M2 C2e bug:

> *"Ollama defaults this to 2048 regardless of what the model supports, and until M2 C2e nothing set it — so a 262,144-token model ran in a 2,048-token window and silently truncated history, injected memory and tool results. Worse, the assembler was packing to 32,000: two numbers, disagreeing … **This is the single source.** `Engine`'s assembler window is derived from the same value."*

Role routing re-opens it. A child routed to a smaller model is sent a `num_ctx` sized for the orchestrator, and the assembler packs to the same wrong number. **This is not a reason to abandon role routing; it is a link of the chain that this ADR cannot close and must not pretend to.** The honest scope is: land the model name, and record that **the window is not yet a function of the role**. Closing it means making `ModelCapability` and `context_tokens` per-route rather than per-driver, which is a `ModelDriver` shape question and is not this session's.

The failure mode if it is left unsaid is the one the comment already names: two numbers disagreeing, with no error.

### 4.5 · **NEW: the prescribed "same substitution in `llamacpp.rs` and `marlowe-openrouter/src/driver.rs`" has no site in either**

```
$ grep -rn "model_for" crates/marlowe-provider/src/llamacpp.rs crates/marlowe-openrouter/src/driver.rs
(nothing)
```

Neither driver holds a `Routing` at all. `llamacpp.rs:1069` sends `"model": self.model` — a single field — and its own doc comment at `llamacpp.rs:952` says why: *"`llama-server` serves whatever it was launched with and does not route on"* that field. `marlowe-openrouter/src/driver.rs:210` sends `"model": self.model`, also a single field.

**So role routing is an Ollama capability, and llama.cpp cannot have it without a second server process per role.** The design's one-line prescription implied three parallel edits; there is one. This belongs in the ADR rather than being discovered by whoever tries the substitution, and it is a real constraint on ADR-060's local runtime: **a role table and a single `llama-server` are incompatible by construction.**

---

## 5 · Why the alternatives lost

### 5.1 · Express "a master holds no working tools" as a budget — `edit_calls: 0`, or `tool_calls: 0`

Rejected. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on the first iteration: the master pauses before its first model call while looking perfectly configured. That is instance #17, it is named as the trap in M3-DESIGN §1.2, and it is what silently stopped the quarantine from reading anything at all (ADR-041). Capability is withheld structurally — the tool is not in the set — and every counter stays at 1 or above. `budget.rs:293–304` already carries this reasoning at the one place it was learned.

### 5.2 · Hold `level` on the `Run`, beside the latched trust floor

Rejected, and the argument is `grant_egress_host`'s verbatim (`profile.rs:296–325`). The invariant "a master's set contains only management tools" is a statement **about the exposed set**, and the exposed set lives inside `CapabilityProfile` behind a validating constructor. Hold the level on the `Run` and consult it beside the profile and the invariant is bypassed rather than enforced: a `Master` run could be constructed with an `edit`-holding profile and **every profile test would stay green**. `Run` also has no validating constructor to route `Deserialize` through, so a checkpoint could restore a master with working tools (#12).

### 5.3 · Build `EscalationTarget` and `escalation_target` now

Rejected — **cut from this decision entirely**, and the reason is the one the critique found. The proposed enum and routing function have **zero callers**, and their subject is already structurally contained: at `engine.rs:2944` a child's `LoopOutcome::Escalated { question }` is journalled and replaced with the fixed harness string *"[child asked a question; a child cannot escalate to the parent's window and its question was not carried across]"*. A worker cannot address anybody today, Marlowe included. Adding a routing function beside that is a second definition of one fact, and the two can drift; and a pure function with no caller, tested in isolation, is `Transport::manifest_provenance` — SECURITY-AUDIT **H4**, already filed there as family #16.

**The half that was substituted for is the hard half.** M3-DESIGN §3 requires that *"an agent that is genuinely stuck must be able to reach a human"*, starting at its direct master and approved at each level. There is **no mechanism at all**: no `LoopOutcome` variant, no arm in the `note` match, no queue. The easy half — routing that cannot be reached — was standing in for it.

So: **record in `STATE.md` and in `SECURITY-AUDIT.md`'s ledger that §3's upward channel is unbuilt and unrouted, citing `engine.rs:2944` as the current containment.** If it is funded later it needs a carrier: `LoopOutcome::EscalationRaised { severity, category, artifact: Option<ContentRef> }` — §2.3's typed record, no free text — plus the arm in the `note` match that forwards it when the parent is a `Master` or a `TopAgent { manages: true }` and refuses it by name otherwise, with `escalation_target` called **there** and nowhere else. That needs §2.3's `Category` enum, which is a pinned-contract question and unanswered.

One test survives the cut, because the absence it defends is real and cheap: `no_escalation_tool_has_a_recipient_parameter`, over `ask` as it appears in `ToolRegistry::builtin()` (the registry, not a literal), with a header recording that the **primary** containment is `engine.rs:2944` and this is belt-and-braces.

### 5.4 · Keep `level.may_hold_create_grant()` as a conjunct inside `may_create_agents()`

Rejected. If `CapabilityProfile::new` refuses `run` on every level that may not hold it, then by construction no profile at such a level contains `run`, and the conjunct can only ever be redundant — or, if it ever disagrees with the constructor, silently wrong. Two definitions of "may this run create agents" is this project's most-logged shape. Add a sixth level, forget to add it to `may_hold_create_grant`, and a profile the constructor happily built reports `false` at the spawn gate: a level that exists and cannot act, with nothing red anywhere. The invariant lives in `new`; the accessor reads the set.

### 5.5 · A new `ModelRole` enum on `SpawnRequest`, separate from `ModelRoute`

Rejected. Two definitions of one thing. `ModelRoute` is already *"a task role, declared in `CapabilityProfile`, never a model or a provider"*, `Routing::model_for` already matches it exhaustively with no wildcard arm at `routing.rs:65–71` (so a fourth variant is a compile error until the table has a model for it — a property that needs **recording**, not building), and `Engine::spawn` already hardcodes a value for it at `engine.rs:2654`. Using it means `role` parameterises an existing constant rather than adding a second vocabulary `Routing` would then need two tables for.

### 5.6 · `role: String`, an open set, so the fourth role needs no code change

Rejected on three counts. A typo routes to a default nobody chose — "defaults that make a mismatch unobservable", four bugs in this project already. `Routing` loses exhaustiveness, so a role with no model has to fall back, and the fallback is either the expensive model or a runtime error at call time instead of load time. And AGENT-DIRECTORY §2a's per-role admission queue keys on the role; a `String` key makes the queue's key space attacker-influenced and unbounded.

### 5.7 · Let a child inherit its parent's role, as `Run::child` inherits `trust_floor`

Rejected. Inheritance is right for a floor because a floor may only fall. A model choice may go either way, and inheriting upward capability is the failure: every descendant of a top-agent would run the 9B. The measurement the design offers for this — 1,053 MiB free with three models co-resident — is **cited here, not relied on**, because it was taken on a desktop holding 5,086 MiB before anything loaded (§9 item 7). The argument that survives without it is structural: chosen-by-spawner with the cheap default is the shape where forgetting the field costs nothing.

### 5.8 · Derive `disposition` from whether `exposed_tools` names `run`

Rejected. That is inference, and M3-DESIGN §5 says declared at spawn, never inferred — the same argument ADR-057's amendment used to make `exposed_tools` required rather than defaulted. Keeping both and letting `CapabilityProfile::new` refuse the disagreement (`Work` + `run` in the tool list → `CreateGrantNotHeldAtThisLevel`) is strictly better: the two cannot silently disagree, and the refusal names which one to change.

### 5.9 · Add `role` in this session and wire the reader chain later

Rejected, and it is the reason §1 exists. This is instance #16 for the third time in one code path, on top of two live ones. The green-and-vacuous test writes itself — `assert_eq!(req.role, ModelRoute::Summarizer)` passes on a build where the child runs on the orchestrator model. A shape pinned without reachability is CONTRACTS §12.1's `ingest_external` situation, which was only honest because it **said so**; §7(d) below makes this pin say so too.

---

## 6 · The tests, each with the mutation that turns it red

Every row names the mutation, because a test whose reading is the same either way is instance #15 and must not be proposed.

| # | Test | File | Asserts | Mutation that reddens it |
|---|---|---|---|---|
| 1 | `the_two_dispositions_do_not_produce_the_same_top_agent` | `crates/marlowe-loop/tests/agent_levels.rs` | `child_of(Secretary, Manage) != child_of(Secretary, Work)`; both `child_of(TopAgent{manages:false}, _)` are `Err`; `new(set!["run"], .., TopAgent{manages:false}, ..)` is `Err(CreateGrantNotHeldAtThisLevel)` | Replace `parse_disposition(text("disposition"))` with `Disposition::Work` in `from_args` — **red**. The first design's version of this test was **green** under that mutation; see §8 |
| 2 | `a_master_cannot_hold_a_working_tool` | same | For **each** of `bash, read, write, edit, glob, grep, web, recall, remember, use` written out literally: at `Master` it is `Err(MasterHoldsWorkingTool{tool})`, at `Worker` it is `Ok`. Plus the #17 control: the master's companion `Budget` has `tool_calls >= 1` and `subagents >= 1` | Delete the `Master` arm — ten reds. Express the rule as `Budget{tool_calls:0,..}` instead — the dimension assertion reds |
| 3 | `management_tools_and_working_tools_are_disjoint_and_the_list_has_not_shrunk` | same | `MANAGEMENT_TOOLS == ["run","ask"]` written **literally in the test**; disjoint from a literal working-tool list; every name resolves in `ToolRegistry::builtin()` | Add `"edit"` — disjointness reds. **Remove `"ask"`** — the literal reds. #19: test 2's input *is* `MANAGEMENT_TOOLS`, so test 2 alone cannot see the list shrink |
| 4 | `the_level_table_is_total_and_never_produces_a_tool_spawned` | same | All ten `(level, disposition)` pairs of `child_of`, and: no input yields `ToolSpawned` | Add `(Master, Manage) => Ok(Master)` — the tree becomes unbounded, red |
| 5 | `every_named_profile_declares_its_level` | same | A wildcard-free `match` over `AgentLevel` mapping each level to the constructor(s) producing it | A sixth variant fails to **compile**. #19-safe: coverage cannot silently shrink |
| 6 | `a_profile_that_may_create_agents_is_exactly_one_that_holds_run` | same | Over all five levels: `p.may_create_agents() == p.exposed_tools().contains("run")` | Reintroduce a `may_hold_create_grant()` conjunct — red at any level that can hold `run` |
| 7 | `a_level_cannot_be_widened_by_deserialization` | same | `"level":"master"` + `"exposed_tools":["edit"]` errors naming the management rule; `level` **absent** errors naming the missing field | Add `#[serde(default)]` to `Raw.level` — the absent case greens. Or replace the hand-written `Deserialize` with a derive — #12 |
| 8 | `a_run_without_the_create_grant_cannot_spawn` | `crates/marlowe-loop/tests/spawn_and_budget.rs` | Drive a real `ModelStep::Spawn` on a run whose set lacks `run`: refused by a message naming the create grant, **`EventKind::RunSpawned` appears 0 times**, the parent's window holds the refusal. **This fails at HEAD** (§4.2) — cite SECURITY-AUDIT H2 | Delete the `may_create_agents()` check at the top of `Engine::spawn`. Assert on the **count**, not the string: a message-only test greens if the refusal is emitted *and* the child spawns |
| 9 | `a_spawn_receipt_names_the_role_that_was_actually_granted` | same | Emit `model_role: "conductor"` — an unrecognised word — and assert the parent's window block contains `role: worker` and `work` | Drop the role from `engine.rs:2728`'s format string — red. This is what makes `parse_role`'s total default observable |
| 10 | `a_latched_run_cannot_choose_a_childs_model_or_disposition` | `crates/marlowe-loop/tests/adr023_spawn_targets.rs` | Unit: `composes_spawn_targets` false at every default, true when **only** `role` moves, true when **only** `disposition` moves. Loop: latch to `UntrustedContent`, emit `model_role: orchestrator`, assert refused and 0 `RunSpawned` | Remove either disjunct at `engine.rs:3237` — the corresponding unit case reads `false` and the loop half spawns |
| 11 | `a_child_spawned_at_the_summarizer_role_is_called_on_the_summarizer_model` | `crates/marlowe-provider/tests/model_role_reaches_the_wire.rs` — **`#[ignore]`, header names the missing daemon link** | **Bytes, not fields.** `Routing::new("role-orch","role-work","role-summ")`; child at `role: Summarizer`; `request_body(..)["model"] == "role-summ"` for the child's call and `"role-orch"` for the parent's. **Prints both strings** | Restore the `ModelRoute::Orchestrator` hardcode at `ollama.rs:300` — both read `role-orch`. Or drop `req.role` in `Engine::spawn` — the child reads `role-work`. **Never write `assert_eq!(req.role, Summarizer)`**: green under both |
| 12 | `call_limits_has_one_production_constructor` | `crates/marlowe-loop/tests/call_limits_one_constructor.rs` | Greps `crates/*/src/` for `CallLimits {`; asserts exactly one hit, in `budget.rs`; prints it | Build a `CallLimits` literal in `ollama.rs` — count reads 2, red |
| 13 | `no_escalation_tool_has_a_recipient_parameter` | `crates/marlowe-tools/tests/escalation_manifest.rs` | For `ask` **as it appears in `ToolRegistry::builtin()`**: no parameter is `ArgumentRole::Target`, no parameter name in `["to","recipient","agent","run","addressee","target"]`. Header records `engine.rs:2944` as the primary containment | Add `documented("recipient", ArgumentRole::Target, Text, …)` to `ask` — red |
| 14 | `the_daemon_builds_its_routing_in_exactly_one_place` | `crates/marlowe-daemon/tests/role_routing.rs` — **deferred with the daemon edit** | Greps `crates/marlowe-daemon/src/*.rs` for `Routing::uniform(`, asserts 0, **prints the count**; then `Daemon::routing()` over a two-tag config gives `models().len() == 2` and two distinct strings | Restore any one `uniform` — count reads 1, red |

### 6.1 · Three tests the strengthened design proposed that must NOT be written as specified

**`no_production_budget_sets_a_dimension_to_zero` is red at HEAD and is measuring the wrong thing.** It was proposed as a #17 guard whose input is the source tree — greps `crates/*/src/` for `depth: 0`, `subagents: 0` and `tool_calls: 0` and asserts zero hits. Measured:

```
$ grep -rn "\bdepth: 0," crates/ --include="*.rs" | grep "/src/" | wc -l
11
```

and the eleven are not what the test is looking for. Most are not `Budget` at all — `daemon.rs:337` is a protocol `Event::Run` for an accepted run, `project.rs:807`/`:844`/`:994`, `protocol.rs:488` and `watch_client.rs:312` are the same shape, and `window.rs:1215` and `run.rs:316` are view fixtures; in every one of them `depth: 0` correctly means *"the root run, depth zero in the tree"*. Of the two that **are** `Budget`, both are correct: `driver.rs:35–37` is `Usage::as_budget`, which zeroes `tool_calls`, `subagents` and `depth` because it is a **spend counter, not a cap**, and a spend legitimately starts at zero; and `budget.rs:307` is `slice_for_quarantined_read`, which sets `depth: 0` **deliberately**, with a comment at `budget.rs:293–304` explaining that `tool_calls: 1` and `subagents: 1` are 1 rather than 0 *for exactly the #17 reason* while `depth: 0` is how a spawn is refused.

`Budget` is one type used for both caps and spends, and a grep over a token cannot tell them apart. The test would go red on correct, shipped, ADR-041 code — and a session would then "fix" the code to satisfy it. **`Budget::exhausted` does not compare `depth` against `spent` at all** (`budget.rs`: *"`depth` is not compared against `spent`: it is a property of the run's position in the tree, checked at spawn"*), so the dimension the test worries about most is the one `exhausted` never reads. The honest replacement is narrow and typed rather than textual, and it is folded into test 2 where a master is actually built: assert the master's companion budget has `tool_calls >= 1` and `subagents >= 1`, and assert `Budget::interactive().depth >= 1` (it is 3).

**`the_role_table_leaves_room_for_the_embedder` must not assert free VRAM.** `assert!(free_vram_mib >= EMBEDDER_RESERVE_MIB)` against a guessed constant reads identically whether the embedder resolved to CUDA: the embedder silently on CPU with 1,100 MiB free prints PASS. That is instance #15's definition. And the baseline it would be measured against included 5,086 MiB held by the desktop, so the test goes red when someone opens Discord — a measurement whose value is set by the desktop is scoped to a system nobody controls. If it is written at all it is `#[ignore]`, it asserts the **provider string from the shipped binary** (`target/release/marlowe.exe --eval-adapter …` and the `embedder asked for auto, running on <X>ExecutionProvider` line), and `/api/ps` totals and free MiB are **printed as diagnostics, never asserted**. Its header states that the desktop's ~5 GB is part of the system under measurement, so a failure means *"not on this machine, in this state"* — which is the true claim.

**`terminate_appears_in_no_agents_request_body_at_any_level` must not build its own view.** M3-DESIGN §3.4 says *"test it where the bytes go … asserting a flag is set is the declaration, not the enforcement"*, and a test-local `fn profile_for(level)` plus a test-built `ContextView` prints 0 whether or not the word arrives from the persona artifact, an installed skill, a governance constraint or the daemon's stable tier — which is where a leak would come from. It builds the body through the **daemon's own** assembly path, its mutation is *put `TERMINATE` in `persona/v1.md`*, and it is paired with a non-optional `--dev` outbound dump from the **shipped** binary saved under `runs/<session>/`. That pairing is the M2 C2e lesson: a test on the source cannot see a stale deployment. The wildcard-free `match` over `AgentLevel` is kept — that half was the correct #19 defence — and only the subject moves.

---

## 7 · Contract impact

**(1) `CONTRACTS.md` §5 — `CapabilityProfile` gains a seventh field**, `level: AgentLevel`, pinned **by membership** (five variants, one carrying a `bool`), with the three new load-time errors stated in the same register as the existing `reads_untrusted && !exposed_tools.is_empty()` sentence: `ToolSpawned ⟹ empty`; `Master ⟹ ⊆ MANAGEMENT_TOOLS`; `contains("run") ⟹ level.may_hold_create_grant()`.

**While there, two lines of §5 are already stale and must be fixed in the same edit or the pin is decorative.** `docs/design/CONTRACTS.md:949` reads `pub exposed_tools: Vec<ToolId>, // INVARIANT: len() <= 12` where `exposure.rs:35` is `MAX_EXPOSED_TOOLS = 14` (ADR-058), and §5 shows **every field `pub`** where the code has all six private behind accessors since M2 Session A. Neither error is caused by this decision and both are inherited by anyone who reads the pin.

**(2) `CONTRACTS.md` §5 — pin `SpawnRequest`'s shape for the first time.** `grep -n "SpawnRequest" docs/design/CONTRACTS.md` returns exactly one hit, line 941, pinning only `fn spawn(&self, req: SpawnRequest) -> RunId`; `LoopOutcome` is not in `CONTRACTS.md` at all. Pinning now is what makes a later window a window rather than a contract change, and it obliges four things:

 (a) Every field with its type **and** its declared / derived / withheld status. ADR-057 §5's rule about `share` and `reads_untrusted` currently lives only in a doc comment. The shape becomes ten fields: the eight at HEAD (`task`, `contract`, `orphan`, `share`, `grant_tokens`, `tools`, `tools_declared`, `reads_untrusted`) plus `role` and `disposition`.

 (b) **Which enums are pinned by MEMBERSHIP and which by NAME ONLY.** `AgentLevel`, `Disposition`, `OrphanPolicy`, `BudgetShare`, `RunStatus`, `Channel`: membership — a variant needs the human, which is M3-D1's precedent. **`ModelRoute`: name only, and that sentence is the entire mechanism by which a fourth role arrives without an ADR.** Without it written down a later session correctly concludes it needs one.

 (c) A statement that `Routing::model_for` matches `ModelRoute` **exhaustively, with no wildcard arm** — already true at `routing.rs:65–71`, so this is recording rather than building. It is what stops a fourth role arriving half-wired.

 (d) **A reachability sentence, and it must be honest about where the chain stops.** §12.1 pins `ingest_external` and says it has no production caller; this pin must say: the chain is complete from `SpawnRequest.role` through `engine.rs:2654` → `CallLimits` → `ollama.rs:300`; **it terminates in `Routing::uniform` until the daemon's `routing()` lands**, so `Orchestrator` and `Worker` resolve to the same model in the shipped binary; **the window (`num_ctx`) is not a function of the role at all** (§4.4); and **`llamacpp` and `openrouter` cannot route by role** (§4.5). A pin that claims a complete chain it does not have is worse than §12.1's, which was honest only because it said so.

**(3) Unchanged.** `RunControl`, `Run`, and §12's six loop-boundary types. `CallLimits` is pinned nowhere and needs no entry.

**(4) A documentation cost that is not a contract cost.** `AGENT-DIRECTORY.md` §2 labels the roles secretary / agent / extractor; `ModelRoute` says Orchestrator / Worker / Summarizer. Record the mapping as a **table in `CONTRACTS.md` beside the enum**, so a later window's labels are a rendering of the enum rather than a second enum. **Flag, do not resolve**, the wobble underneath it: ADR-008's 2026-08-10 amendment says compression is not extraction, while §2 calls the 2b model the "extractor" and `Summarizer` is the compaction summarizer.

---

## 8 · The adversarial pass, recorded rather than hidden

The design in `runs/m3-c/design/five-levels.md` was reviewed adversarially before this ADR was written. **Verdict: `sound-with-fixes`**, with one fatal finding and twelve further defects. The first draft is not presented here as though it had been right.

### 8.1 · The fatal finding, and what it changed

> **`disposition` was a declared control with no reader that distinguished its two values on the one path M3-DESIGN §1.1 names.**

In the first design `AgentLevel` was a plain five-variant enum and `disposition` was a separate field beside it. `child_of(Secretary, Manage)` and `child_of(Secretary, Work)` **both returned `TopAgent`**; `CapabilityProfile::new`'s level match had `TopAgent` falling into `_ => {}`; and the `CreateGrantBelowMaster` refusal fired only on `Worker | ToolSpawned`. So after `child_of` ran, nothing consulted `disposition` again on Marlowe's own spawn path. §1.1 is explicit that the two words mean different grants — *"`master` … Gets a create grant and an agent budget"* versus *"`worker` — will do the task itself"* — and neither was enforced. **A Secretary spawning `disposition: work, exposed_tools: "run bash"` yielded a top-agent holding `run` and `bash` at once: a worker that can create agents and edit.**

The test made it invisible. `marlowe_only_ever_creates_a_top_agent`'s headline assertion was that **both dispositions give the same answer**, so it was green whether `disposition` was plumbed through or dropped on the floor at `SpawnRequest::from_args`. That is instance #16 shipped with its green proxy test already written, **in the design whose own stated blocking finding was instance #16**.

**What changed because of it:** the disposition moved *inside* the level — `TopAgent { manages: bool }` — so the two answers are different values of the same type and cannot be recorded and then ignored; `child_of(TopAgent { manages: false }, _)` became `Err`; the create-grant refusal became a check on `may_hold_create_grant()` rather than a two-variant match; and the test was rewritten so its headline assertion is `child_of(Secretary, Manage) != child_of(Secretary, Work)`, with the mutation `parse_disposition(...) → Disposition::Work` naming what turns it red. Test 1 in §6 is that rewrite.

### 8.2 · The other defects, and their disposition here

| Critique's finding | Disposition in this ADR |
|---|---|
| `may_hold_create_grant` as a conjunct in `may_create_agents` is a second definition | Accepted — §5.4, the conjunct is deleted |
| `escalation_target` has zero callers and its subject is already contained | Accepted — §5.3, both cut, and §3's missing channel is recorded rather than papered over |
| Every `Routing::uniform` citation wrong; `agent.rs` missed; six edit sites | Accepted — §1.1 and §4.1, one function, and a guard whose input is the source tree |
| `the_role_table_leaves_room_for_the_embedder` is #15 and desktop-dependent | Accepted — §6.1 |
| `terminate_…` asserts on a body the test builds | Accepted — §6.1 |
| `escalate` as a thirteenth builtin costs a red assertion and an MCP slot | Accepted — §2.2, deferred |
| `Summarizer` has no producer | Accepted — §4.3, two routes wired, third gated |
| `CallLimits.route` public is #12 with a struct literal | Accepted — §3, and the migration is 23 sites, not 8 |
| Four of five named constructors unassigned | Accepted — §2.1, all five pinned |
| The Secretary's `_ => {}` decides a boundary question silently | Accepted — §2.1, a named arm carrying the question; §9 item 4 |
| No `daemon.rs` edit while another session holds it | Accepted — §4.1 |
| "four deep by construction" is false of `condense_batch` | Accepted — stated precisely in `child_of`'s doc comment |
| The receipt was named as a mitigation and had no site | Accepted — §2.3, `engine.rs:2728` |
| **`composes_spawn_targets` is at 3227, not 3237** | **Rejected — the correction is wrong.** `git show` at `186b5d5` and `03fb1d6` both give 3237 (§1.1) |
| **`no_production_budget_sets_a_dimension_to_zero` as a source-tree grep** | **Rejected — red at HEAD and measuring the wrong thing** (§6.1) |

### 8.3 · What the adversarial pass did **not** find, and this ADR did

Three things, all measured this session: the second `ModelRoute::Orchestrator` hardcode at `ollama.rs:242` and the per-driver `num_ctx` that role routing silently desynchronises (§4.4); the absence of any `Routing` in `llamacpp.rs` and `marlowe-openrouter/src/driver.rs`, which makes the prescribed substitution siteless in two of three drivers (§4.5); and the four uncorrected line citations plus one wrong correction (§1.1). **A citation audit that stops when it finds one bad family is the same shape as a per-crate test run: it answers an adjacent question and reads identically when the answer is no.**

---

## 9 · What is the human's

1. **Both pinned-contract acts** — `CapabilityProfile`'s seventh field, and `SpawnRequest`'s first pin. M3-D1's precedent is escalate, not take.
2. **Both §13-guarded file edits.** `crates/marlowe-loop/src/profile.rs` and `crates/marlowe-loop/src/driver.rs` are both in `PROTECTED` (verified: `python .claude/hooks/protect-boundaries.py --list-protected`). `crates/marlowe-permission/src/adjudicate.rs` is **not** touched — `blocks_composed_targets` is unchanged and `composes_spawn_targets` lives in the unguarded `engine.rs`. Neither `memory.rs`, `steer.rs`, `mcp.rs`, `pin.rs`, `trust.rs`, the journal nor `persona/` is touched, so **no new `PROTECTED` row is owed and no new row in CLAUDE.md's §13 table.**
3. **The fourth `ModelRoute` variant's name, and whether it is ADR-008's compression role.** Not invented here. ADR-008's 2026-08-10 amendment already asked for a fourth role — compression — and it never landed. Whether the human's fourth role *is* that one decides four variants or five, and four `Routing` columns or five. The amendment calls compression the enforcement point for brief §10 and, post-ADR-037 §6, the security interface. **Under the same question: should `quarantined_reader()` carry `ModelRoute::Summarizer`?** It is the only credible producer for the third column, and it is the same compression-versus-extraction wobble.
4. **Does §1.2's structural rule extend to level 1?** This ADR makes `interactive()` a `Secretary` with **no** tool restriction, as a named match arm carrying the question rather than a `_`. `interactive()` holds `bash`, `edit`, `write` and `web`. §1's table says "full conversational set"; §2's liaison pattern exists because Marlowe must not do the work himself. M3-DESIGN §1 does not answer it, and answering it with a wildcard is how a decision gets made by nobody.
5. **Breaking pre-Session-C checkpoints.** Accept the named serde failure on resume, or fund a one-shot migration. `#[serde(default)]` is not on the table: it would silently restore a master holding working tools.
6. **Is `role` a Target under ADR-023?** This ADR answers **yes**, with one disjunct at an existing latch — cheap and reversible, but it narrows what a latched run may do, so it is accepted rather than taken. AGENT-DIRECTORY §3 item 4 asks for it answered explicitly rather than by omission.
7. **Which models go in the default table is a VRAM decision, and the arithmetic on record is contradicted by measurement.** AGENT-DIRECTORY §2 says three models take *"10.0 GB of the card's 16, leaving headroom for the KV cache, the embedder and the reranker."* The design reports a `/api/ps` reading of 5,086 MiB held by the desktop before anything loaded and a final state of 14,993 MiB used / **1,053 MiB free**. **That number is cited here, not relied on**: it was taken on a machine holding Opera GX, Discord, Steam and Wallpaper Engine, so it is scoped to a desktop state nobody controls and must be re-measured, not carried. ADR-044 resolves the embedder's provider against free VRAM **at load**, so shipping a three-model table is what puts the embedder on CPU with a correct-looking log line.
8. **SECURITY-AUDIT §8 / ROADMAP M3-C item (2): "the latch belongs on the session, not the `Run`."** Untouched here and still unrecorded in `DECISIONS.md`. It is adjacent — `Run::root` is rebuilt every turn at `UserAsserted`, so the composed-target refusal this ADR adds for `role` is **per-turn** — but it is a separate decision and it is the human's.
9. **`escalate` as a thirteenth builtin**, costing a red `assert_eq!(BUILTIN_TOOLS.len(), 12)` and one of ADR-058's two MCP slots — or a paired increase of `MAX_EXPOSED_TOOLS`, which is an ADR-058 amendment.

---

## 10 · What this ADR does NOT close

* **It does not build M3-DESIGN §3's upward channel.** §5.3 cuts the routing function and records that *"an agent that is genuinely stuck must be able to reach a human"* has **no mechanism** — no `LoopOutcome` variant, no arm in the `note` match, no queue. The current containment is `engine.rs:2944` swallowing a child's `Escalated` into a fixed harness string, and that is containment, not a channel.
* **It does not make the model window a function of the role.** §4.4: `"model"` becomes per-call and `num_ctx` stays per-process. Closing it is a `ModelDriver` shape question.
* **It does not give llama.cpp or OpenRouter role routing.** §4.5: neither driver holds a `Routing`, and `llama-server` serves one model per process by design. Role routing is Ollama-only until someone decides otherwise, and ADR-060's local runtime should hear that.
* **It does not complete the routing table.** The chain terminates in `Routing::uniform` until a `daemon.rs` edit that this session must not make (§4.1), and the wire test is `#[ignore]` with a header saying why.
* **It does not give `ModelRoute::Summarizer` a producer.** §4.3.
* **It does not close SECURITY-AUDIT H2.** The `may_create_agents` check closes H2's gap **for `run`**; `remember` and `ask` still bypass the adjudicator entirely, and `CapabilityProfile::narrowed` still copies `may_write_memory` while narrowing `exposed_tools`.
* **It does not wire `ingest` and adds no producer for `Channel::Agent`.** `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns only definitions. Layer 3 stays unreachable in the shipped daemon, which is the correct state per ADR-062.
* **It does not claim the latch does work inside a research subtree.** ADR-036 §5's saturation applies directly: where every source is `UntrustedContent`, every spawn is equally tainted, the floor discriminates nothing, and the surviving question is *who asserted the role*. This ADR does not answer that. The blast radius is bounded — a closed enum of local model tags, so a wrong choice costs spend and capability, not egress — but the mechanism is not doing work there and must not be claimed to be.
* **It does not touch `OLLAMA_NUM_PARALLEL=1` or the synchronous child drive.** `Engine::spawn` runs children synchronously, so the tree is depth-first and blocking whatever the role table says. A roster showing three agents "running" tells the truth about intent and a lie about execution. The `role` field is what first makes that visible to a user.
* **It does not design admission control.** Its per-role queue keys on `ModelRoute` — one more argument for the closed enum — and `RunStatus::Queued`'s conflation of *constructed* with *blocked behind busy workers* is a separate decision.

---

## Verification

Symbol names are used where a line number would be a claim about a path with nothing checking it (family #14). Everything below was read at HEAD **`03fb1d6`** unless a second commit is named.

| Claim | How established |
|---|---|
| `model_route()` has zero readers | `grep -rn "model_route()" --include=*.rs crates/` — one hit, its own definition at `profile.rs:280` |
| `Routing::new` has zero production callers | `grep -rn "Routing::new"` — one hit, `routing.rs:118`, a unit test |
| `ModelRoute::Summarizer` has zero producers | `grep -rn "ModelRoute::Summarizer"` — `routing.rs:71` (the consuming arm) and `:121` (a unit test) |
| Six production `Routing::uniform` sites | `grep -rn "Routing::uniform" \| grep /src/` — `agent.rs:47`, `daemon.rs:1263, 1338, 1503, 1889, 1976` |
| `ollama.rs:300` hardcodes `Orchestrator` | read |
| **A second hardcode at `ollama.rs:242`, and `num_ctx` is per-driver** | read: `OllamaDriver::new`; `request_body`'s `"num_ctx": self.context_tokens` at `:545`; `with_context_tokens` called from `daemon.rs:2121, :2288, :2375` |
| **`llamacpp.rs` and `marlowe-openrouter/src/driver.rs` hold no `Routing`** | `grep -rn "model_for"` over both — empty; `"model": self.model` at `llamacpp.rs:1069` and `driver.rs:210`; `llamacpp.rs:952`'s own comment |
| `engine.rs` is identical at `186b5d5` and `03fb1d6` on all six anchors | `git show <commit>:crates/marlowe-loop/src/engine.rs \| grep -n …`, run for both |
| The receipt is at 2728, the swallowed `Escalated` at 2944, `Engine::spawn` at 2528, the quarantined child at 2150, `composes_spawn_targets` at 3237 | same command, both commits |
| `Engine::spawn` never checks exposure of `run` | read `engine.rs:2528`–2600: task, `tools_declared`, composed targets — no `exposed_tools` consultation; `ollama.rs:1045` maps `run` to `ModelStep::Spawn` |
| `BUILTIN_TOOLS` is `[&str; 12]` with a length assertion | read: `builtin.rs:36`, `builtin.rs:749` |
| `MAX_EXPOSED_TOOLS = 14`; `interactive()` holds twelve including `bash`, `edit`, `run` | read: `exposure.rs:35`, `profile.rs:173`–222 |
| `narrowed` has zero production callers | `grep -rn "\.narrowed("` — four hits, all tests |
| 23 `CallLimits` struct-literal sites outside `budget.rs` | `grep -rn "CallLimits { max_output_tokens" \| grep -v src/budget.rs \| wc -l` |
| `call_limits` has one call site in the workspace | `grep -rn "call_limits"` — `budget.rs:144` (definition), three `budget.rs` unit-test calls, `engine.rs:794` |
| **11 `depth: 0,` sites under `crates/*/src/`, and none is a `Budget` cap that should change** | `grep -rn "\bdepth: 0," \| grep /src/`, then each read: `daemon.rs:337` is `Event::Run`, `budget.rs:307` is the deliberate quarantine slice, `driver.rs:37` is `Usage::as_budget`, a spend |
| `Budget::exhausted` does not compare `depth` | read `budget.rs`'s `exhausted` and its comment |
| CONTRACTS §5 pins `len() <= 12` and shows all fields `pub` | read `CONTRACTS.md:949`; `grep -n "SpawnRequest" docs/design/CONTRACTS.md` returns one hit, `:941` |
| Both edited files are `PROTECTED`; `builtin.rs` and `engine.rs` are not | `python .claude/hooks/protect-boundaries.py --list-protected` |
| SECURITY-AUDIT H2's `run` parenthetical is stale | read `SECURITY-AUDIT.md:1034`–1043 against `ollama.rs:1045` |

**Nothing in this table was established by running `cargo`.** Another session is building; every claim above is a read or a grep, and that distinction is stated rather than implied, because a table of greps reads like a table of tests. **The two claims that most need a run before anyone acts on them** are §4.4's window desynchronisation — which should be confirmed in a `--dev` outbound dump from the shipped binary showing `model` and `num_ctx` disagreeing, not in a unit test — and §6.1's assertion that the proposed zero-dimension guard is red at HEAD.
