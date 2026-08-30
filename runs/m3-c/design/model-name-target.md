# model-name-target: A model role is a TARGET — and Session C enforces it by withholding it structurally, because `model_route` currently has zero readers

**Adversary verdict:** sound-with-fixes

**Fatal:** The design's remedy for instance #16 ships a fresh instance of #16: it adds `CallLimits.route` and names exactly one reader (`crates/marlowe-provider/src/ollama.rs:300`), while the daemon ships three `ModelDriver` implementations (`ModelProviderChoice::{Ollama, OpenRouter, LlamaCpp}`, `crates/marlowe-daemon/src/daemon.rs:67,81`). `LlamaCppDriver::request_body` sends `"model": self.model` at `llamacpp.rs:1069` and `OpenRouterDriver::request_body` sends `"model": self.model` at `openrouter/driver.rs:210` — neither holds a `Routing`, neither would read the new field. After the change a grep for readers of `model_route` returns a hit and reads as a positive result on two paths where nothing honours it, which is strictly worse than today's visibly-dead field.

## Ledger instances the adversary says this re-commits

- #16 (a declared control nothing reads) — `CallLimits.route` has one named reader, `ollama.rs:300`, and none on the llama.cpp (`llamacpp.rs:1069`) or OpenRouter (`openrouter/driver.rs:210`) paths, both of which the daemon selects between.
- #16 again — `ModelRoute::Summarizer` and `Routing`'s `summarizer` field (`routing.rs:39`) still have zero readers after the change: no `CapabilityProfile` constructor produces `Summarizer`, and compaction goes through the separate `trait Summarizer` port (`driver.rs:330`, `PassthroughSummarizer` at `daemon.rs:635`) which never sees a `CallLimits`. The design claims the reader gap is closed.
- #15 (an assertion that reads identically whether the mechanism works) — T2 and T3 assert `RunSpawned["model_route"] == "worker"`, the same string HEAD's hardcoded `ModelRoute::Worker` at `engine.rs:2654` already produces; the only discriminating case offered is a `Summarizer`-parent run that no production profile constructor can create.
- #15 again — T1 asserts `body["model"]` only, so it is green on a build where the routed model is correct but `num_ctx` (`ollama.rs`'s `context_tokens`, set once at `daemon.rs:2121`) and the `max_tokens` clamp still describe the orchestrator.
- Two definitions of one fact — after this change the model a request goes to is decided by `Routing::model_for(limits.route)` while the window, the output clamp and the user-facing `model_disclosure` (`daemon.rs:1390`) are all still decided from the single `config.model`. This is the 'two numbers, disagreeing' failure ollama.rs's own `context_tokens` doc records from M2 C2e.
- A measurement/citation carried across a boundary — five of five `daemon.rs` `Routing::uniform` line numbers are wrong (actual: 1263, 1338, 1503, 1889, 1976), `profile.rs:223` is a `.claude/worktrees/` copy (HEAD: `:280`), `DECISIONS.md:1030` should be `:1038`, and `crates/marlowe/src/agent.rs:47` — a sixth production `Routing::uniform` — is omitted. Same family as the roadmap row with five of seven citations wrong.
- #17 — CLEAN. No limit is written as 0. Capabilities are withheld structurally (`ExposedSet::empty()`, an absent `route` field, an absent `role` parameter), and `may_grant` is a comparison over `strength()`, not a counter. `Budget::exhausted`'s `spent >= budget` (`budget.rs:110`) is untouched.
- #12 — CLEAN, and worth pinning so it stays clean. `SpawnRequest` derives only `Debug, Clone, PartialEq, Eq` (`driver.rs:58`) — no `Deserialize`. `CapabilityProfile`'s hand-written `Deserialize` (`profile.rs:353-379`) routes through `CapabilityProfile::new`, and adding `ModelRoute::for_child` opens no new serde path. When `SpawnRequest.route` lands in Session G, no `#[derive(Deserialize)]` may land with it.
- #19 — the design handles it correctly for T4 (the five-name set and the three-name Target subset are both written as literals, independent of the manifest, which strictly improves on `builtin.rs:907-908`'s `role_of("share") == None` absence-assertions), and it flags T5's own value table as the residual #19 shape. This is the strongest part of the design and should be kept verbatim.

## Defects (9)

### THE FIX RE-COMMITS INSTANCE #16 ON TWO OF THE THREE SHIPPED DRIVER PATHS. The design adds `CallLimits.route` and names exactly one reader: `crates/marlowe-provider/src/ollama.rs:300`. There are three production `ModelDriver` implementations, and the daemon selects among all three — `ModelProviderChoice::{Ollama, OpenRouter, LlamaCpp}` at `crates/marlowe-daemon/src/daemon.rs:67` and `:81`. `LlamaCppDriver::request_body` (`crates/marlowe-provider/src/llamacpp.rs:1062`) sends `"model": self.model` at `:1069`; `OpenRouterDriver::request_body` (`crates/marlowe-openrouter/src/driver.rs:196`) sends `"model": self.model` at `:210`. Neither holds a `Routing`. Neither would read `limits.route`.

- **Why:** The design's own stated purpose is to close a declared-control-nothing-reads gap before anyone is allowed to name the field on the wire. It ships a new field that is read on one of three provider paths and unread on the other two — instance #16 committed inside the answer to an instance-#16 question, which is the exact stacking ADR-057 §4 took a milestone to find. And it is worse than the status quo: today `model_route` is visibly dead everywhere; after this change it is live on Ollama and silently dead on llama.cpp and OpenRouter, so the next session's grep for a reader returns a hit and reads as a positive result (instance #18's shape).
- **Fix:** Read the field on all three, and make the incoherent configuration unreachable rather than documented. (a) `LlamaCppDriver` and `OpenRouterDriver` take a `Routing` instead of a bare `model: String`, and each `request_body` does `let model = self.routing.model_for(limits.route).to_string();` — one line per driver, three readers. (b) Their constructors return `Err` on a routing they cannot yet honour, so a mismatch is a load-time error, not a default.

### `ModelRoute::Summarizer` STILL HAS ZERO READERS AFTER THE CHANGE, AND THE DESIGN PRESENTS THE READER GAP AS CLOSED. No `CapabilityProfile` constructor ever produces `Summarizer`: `quarantined_reader()` is `Worker` (`profile.rs:147`), `consolidation()` is `Worker` (`:165`), `interactive()` is `Orchestrator` (`:222`), `interactive_with` inherits `base.model_route` (`:265`). `for_child` can only return `Summarizer` from a `Summarizer` parent, which nothing constructs. The real compaction summarizer is a different port entirely — `pub trait Summarizer { fn summarize(&mut self, view: &ContextView) -> String; }` at `crates/marlowe-loop/src/driver.rs:330`, implemented by `PassthroughSummarizer` at `crates/marlowe-daemon/src/daemon.rs:635`, which touches neither `Routing` nor `CallLimits`.

- **Why:** One third of `Routing`'s table (`routing.rs:39`'s `summarizer` field) stays dead, and `routing_is_by_role_and_the_table_is_the_only_place_a_model_is_named` (`routing.rs:117`) stays green over it — because it builds its own `Routing` inside the test and asks `model_for` directly. That test would be identical if no run in the product ever reached the table, which is precisely the reading the design says it exists to prevent.
- **Fix:** State it: the ADR must say `ModelRoute::Summarizer` remains unrouted after Session C, name `ports.summarizer` / `PassthroughSummarizer` as the reason, and either (i) route the compaction call by adding `fn summarize(&mut self, view: &ContextView, route: ModelRoute)` to the `Summarizer` trait — a §13-guarded `driver.rs` edit, therefore Session G and the human's — or (ii) record it in SECURITY-AUDIT's family-#16 roll alongside `model_route` as a second, still-open entry. Do not claim the gap is closed while a third of the table has no reader.

### T2 AND T3 ASSERT A JOURNAL FIELD WHOSE VALUE IS UNCHANGED AT HEAD — INSTANCE #15. Both read `RunSpawned["model_route"] == "worker"`. HEAD already hardcodes `ModelRoute::Worker` at `crates/marlowe-loop/src/engine.rs:2654`, so on today's build, on a build with `for_child`, and on a build where `from_args` reads a `role` key into a field that is then ignored, all three print `"worker"`. The only case the design offers that discriminates is a `Summarizer`-parent spawn — a state no production profile constructor can produce (see defect 2), i.e. the layer-3-unreachability critique reproduced inside the test that is supposed to close the question.

- **Why:** Ask what T3 prints if the thing it names is broken. `a_model_that_names_a_model_role_is_not_given_one` prints `"worker"` when `from_args` correctly ignores `role`, AND when `from_args` silently drops it, AND when `from_args` parses it into a field `Engine::spawn` never consults. It only reddens under the one three-part mutation the design authored it against. That is a test written to a mutation, not to a property.
- **Fix:** Assert the property directly and cheaply. `SpawnRequest` derives `PartialEq` (`crates/marlowe-loop/src/driver.rs:58`), so: `assert_eq!(SpawnRequest::from_args(&args_with_role_level_and_model), SpawnRequest::from_args(&args_without))` — one line, in `crates/marlowe-loop/src/driver.rs`'s own `mod tests` or in `spawn_from_a_model_reply.rs`, reddening the instant ANY of the three spellings gains a reader in `from_args`, independent of the journal, `Engine::spawn` and the driver. Keep the journal assertion as an audit check and label it as one. For T2, assert the bytes: drive the spawn with a driver that records `limits.route` per call (the pattern `quarantine_batch.rs:201` already uses, where the parameter is `l:` rather than `_l:`) and assert the recorded sequence, not the payload.

### THE CONTEXT WINDOW, THE `max_tokens` CLAMP AND THE USER-FACING DISCLOSURE DO NOT FOLLOW THE ROUTE — TWO NUMBERS DISAGREEING, INSIDE THE FIX THAT WAS WRITTEN TO END THAT. `OllamaDriver::new` builds `capability` from `routing.model_for(ModelRoute::Orchestrator)` (`ollama.rs:242`), one `context_tokens` is set for the driver's whole life (`daemon.rs:2120-2121`, `.with_capability(capability_for(&self.config.model)).with_context_tokens(self.config.context_tokens)`), `num_ctx` goes on every request, and the Engine's assembler window is derived from the same value — ollama.rs's own field doc says so. `llamacpp.rs:1080` and `openrouter/driver.rs:214` clamp `max_tokens` to `self.context_tokens / 4`. The user-visible `model_disclosure` is `capability_for(&self.config.model).disclosure()` (`daemon.rs:1390`, also `:1314`).

- **Why:** Route a call to a different model and the window, the output clamp and the tool-call reliability figure shown to the human all still describe the orchestrator. ollama.rs's `context_tokens` doc records exactly this failure from M2 C2e — *'two numbers, disagreeing, with §6's compaction trigger computed from the wrong one'* — and the design reintroduces it one level up. T1 asserts `body["model"]` only, so T1 is green with the window wrong; that is the assert-a-proxy family applied to the design's own headline test.
- **Fix:** Make it a load-time error, not a documented hazard. Extend `Availability::probe` (`crates/marlowe-provider/src/ollama.rs:128`), which already iterates `routing.models()` at `:152` against `/api/tags`: for each routed model also read its `context_length` (`GET /api/show`; the measurement in this session's brief read 32768 for all three roles from `/api/ps`) and add `Availability::WindowTooSmall { model, reports: u32, configured: u32 }`, refusing at startup when any routed model's window is below the configured `context_tokens`. That is a command printing a number, it lives in an unguarded file, and it needs no `daemon.rs` edit. Additionally, T1 must assert `body["num_ctx"]` alongside `body["model"]` so the two cannot drift silently.

### THE COST FIGURE FOR THE `CallLimits` CHANGE IS WRONG BY ROUGHLY 4x. The design says: *'Every construction site today is a struct literal (~8, all in tests), so adding this field is a COMPILE ERROR at each one.'* Measured: `grep -rn "CallLimits {" --include=*.rs crates/ | grep -v "pub struct CallLimits"` returns **31 sites across 17 files**, including `crates/marlowe-openrouter/examples/live_probe.rs:93`, `crates/marlowe-exec/examples/batch_parallelism.rs`, `crates/marlowe-exec/examples/deep_research_attack.rs`, and one production site, `crates/marlowe-loop/src/budget.rs:145`.

- **Why:** The compile-error-at-every-site property is the right argument and the reason to have no `Default` impl — that part stands. But a session that budgets for 8 edits and finds 31, four of them in `examples/` that a `cargo test` does not compile by default, will reach for `#[derive(Default)]` or `..Default::default()` under time pressure, which is exactly the silent-inheritance the design forbids in its own comment.
- **Fix:** State 31/17 in the ADR with the grep beside it, and pre-commit to the no-`Default` rule with a guard: add `route` with **no** `Default` impl on `CallLimits` and no `#[serde(default)]`, and make the ADR say that the 31 mechanical edits are the deliverable, not an obstacle to it.

### `for_child` MAKES THE ROLE A FUNCTION OF DEPTH WHERE `AGENT-DIRECTORY.md` REQUIRES IT TO BE A FUNCTION OF AGENT KIND, AND THE DESIGN DOES NOT SAY SO. `for_child(Orchestrator) = Worker` and `for_child(Worker) = Worker` collapse every descendant to one role. AGENT-DIRECTORY §2 'The requirement, as given': *'Four model roles exist… The spawner names the model: when the harness emits a `run` it says which role it wants, and the corresponding model serves it.'* M3-DESIGN §1.1: *'At spawn Marlowe declares which kind it is: master | worker.'* §1.3: worker tool sets are per type.

- **Why:** Two consequences the ADR leaves unrecorded. (1) Three of the four configured roles become unreachable, so the co-residency arithmetic §2 is built on has nothing to route to. (2) AGENT-DIRECTORY §2a — *'ADMISSION CONTROL — added 2026-08-30, and it is Session C's problem, not Session G's'* — specifies a **per-role queue** (`RunStatus::Queued` already exists and is pinned). Under `for_child` that queue has exactly one role, which makes the mechanism degenerate before it is built. Deferring is defensible; deferring silently is how a placeholder becomes the design.
- **Fix:** Ship `for_child` as an explicitly named STOPGAP. Its doc comment must say: the route is currently determined by depth, the kind→route table is Session G's and the human's, and §2a's per-role queue is unimplementable until that table exists. Add a line to `open_for_human`: *'the kind→route table — which of the four roles a `master`, a `worker`, an `extractor` and the unnamed fourth get — is the human's, and `for_child` is a one-role placeholder standing in for it.'* Do not let `for_child` be cited later as the answer to 'how does a child get its role'.

### WRONG LINE CITATIONS, AND ONE PRODUCTION CALL SITE MISSED ENTIRELY. The design cites production `Routing::uniform` at `daemon.rs:1196, 1271, 1436, 1780, 1867`. Measured on HEAD 186b5d5: `crates/marlowe-daemon/src/daemon.rs:1263, 1338, 1503, 1889, 1976` — five for five wrong — and it omits `crates/marlowe/src/agent.rs:47`, a sixth production `Routing::uniform(DEFAULT_MODEL)` on the CLI/eval-adapter path. It cites `CapabilityProfile::model_route()` at `profile.rs:223`; on HEAD it is `:280`. It cites ADR-008's amendment at `DECISIONS.md:1030`; it is `:1038`.

- **Why:** `profile.rs:223` is the line number in `.claude/worktrees/agent-ac68c320701f55af4/crates/marlowe-loop/src/profile.rs` — the design read a worktree copy, not the checkout, for at least some of its citations. That is hazard form 1/2 from CLAUDE.md's parallel-sessions table, and it is how the roadmap row with five of seven wrong citations happened. The missed `agent.rs:47` matters substantively: it is the binary CLAUDE.md's own `--eval-adapter` provider-check command runs.
- **Fix:** Re-cite every line against `git show 186b5d5`. Add `crates/marlowe/src/agent.rs:47` to the list of production `Routing` sites, so 'every production routing is uniform' rests on six sites and not five. Cite the ADR-008 amendment as `DECISIONS.md:1038`.

### THE ARGUMENT 'THE ROLE IS A TARGET UNDER THE MECHANISM AS IT ALREADY STANDS' CITES A MECHANISM THAT DOES NOT RUN ON THIS PATH. `adjudicate`'s §2 target loop (`crates/marlowe-permission/src/adjudicate.rs:299-320`, with `manifest.role_of(name).unwrap_or(ArgumentRole::Target)` at `:304`) is reached only from `tool_batch`. A `run` call becomes `ModelStep::Spawn` in the Ollama adapter (`crates/marlowe-provider/src/ollama.rs:1045`, the only such mapping in the workspace) and goes from the loop's match at `engine.rs:1330` straight to `Engine::spawn`, whose own comment at `:2582` says it *'never reaches self.adjudicator'*. So `run`'s manifest roles have NO reader on any enforcing path; the enforcement is `composes_spawn_targets` at `engine.rs:3237`, a hand-written mirror.

- **Why:** The conclusion — no `adjudicate.rs` edit is needed — is correct. The reason given is not, and a reader who acts on the stated reason will look for the check in `adjudicate` and find a loop that never executes for `run`, then either conclude the role is unprotected or 'fix' it by routing spawns through the adjudicator, which is a §13-guarded change nobody decided.
- **Fix:** Restate the argument on the mechanism that actually runs: `orphan_policy` is a closed two-value enum declared `ArgumentRole::Target` in `builtin.rs` and enforced by the `!matches!(req.orphan, OrphanPolicy::Terminate)` clause of `composes_spawn_targets`. A closed enum choosing which inference engine makes every subsequent decision is a target a fortiori, on the same mirror. Say explicitly that `adjudicate` is not on the spawn path and that this is why T5 (the manifest↔mirror coupling test) is the load-bearing test in the set.

### THE RECEIPT DOES NOT NAME THE ROUTE, AND ADR-057 §2 IS THE STANDING RULE THAT IT MUST. `Engine::spawn` pushes `[spawned] tools: {…} · budget: {n} tokens · orphan: {…} · returns: {…}` at `crates/marlowe-loop/src/engine.rs:2726-2737`. The comment immediately above it (`:2696`) states the principle: *'Six of a spawn's seven fields are supplied by rule when the parent does not name them, and CLAUDE.md's standing warning is about defaults that make a mismatch unobservable. The answer is not to refuse a model that omitted a field — it is to say what it got.'* The design puts the route in the `RunSpawned` journal payload and in two tests, and nowhere the parent can see.

- **Why:** A harness-chosen route that the parent cannot observe is the same shape as the pre-ADR-057 budget: the parent asked for a child, got one on some model, and had no way to find out which. When a routing is non-uniform this is the difference between a parent that knows its child ran on a 2B and one that reads a thin result as a task failure.
- **Fix:** Add one field to the receipt line: `· model: {role}` (the role name, never a model tag — the tag is `Routing`'s and belongs nowhere else, per `routing.rs`'s header). It is harness-authored, a closed enum, and needs no sanitisation. Assert it in `receipt_for` (`crates/marlowe-provider/tests/spawn_from_a_model_reply.rs:249`), whose mutation is: delete the field from the format string and the receipt assertion fails by name.

## STRENGTHENED — WHAT GETS BUILT

## A model role is a TARGET. Session C records that, closes the reader gap on ALL THREE driver paths, and withholds the role from the model structurally.

### The answer, and what it rests on

A model role is a **target** under ADR-023, not a payload and not a third thing. The argument is the mirror that actually runs, not the adjudicator: `run`'s `orphan_policy` is a closed two-value enum that chooses only a child's *lifetime*, it is declared `ArgumentRole::Target` in `crates/marlowe-tools/src/builtin.rs`, and it is enforced by the `!matches!(req.orphan, OrphanPolicy::Terminate)` clause of `composes_spawn_targets` (`crates/marlowe-loop/src/engine.rs:3237`). A closed enum that chooses the inference engine executing every subsequent decision a child makes is a target a fortiori; calling it a payload retroactively de-targets `orphan_policy`.

**State plainly that `adjudicate` is NOT on this path.** `ModelStep::Spawn` is produced only at `crates/marlowe-provider/src/ollama.rs:1045` and goes from `engine.rs:1330` straight to `Engine::spawn`, which never calls `self.adjudicator` (its own comment, `engine.rs:2582`). So `run`'s manifest roles have no reader on any enforcing path; `composes_spawn_targets` is a hand-written mirror of them, and T5 below is the only thing coupling the two. The correct conclusion is unchanged — **no edit to `crates/marlowe-permission/src/adjudicate.rs` or `taint.rs`** — but for this reason, not the one the reviewed design gave.

### What Session C ships

**1. `crates/marlowe-loop/src/profile.rs` — §13-GUARDED. A HUMAN MUST APPROVE THIS EDIT.**

```rust
impl ModelRoute {
    /// The route a child of a run at `parent` gets.
    ///
    /// **A STOPGAP, and it must be read as one.** The route is currently a function of the
    /// child's DEPTH. `AGENT-DIRECTORY.md` §2 requires it to be a function of the child's
    /// KIND — *"the spawner names the model: when the harness emits a `run` it says which
    /// role it wants"* — and M3-DESIGN §1.1 has Marlowe declaring `master` or `worker` at
    /// spawn. This function collapses every descendant to one role, which means three of the
    /// four configured roles are unreachable and §2a's PER-ROLE QUEUE has exactly one role.
    /// The kind -> route table is Session G's and the human's. Do not cite this function as
    /// the answer to "how does a child get its role".
    ///
    /// **Total, and a function of the parent alone** — no argument, no model input, so there
    /// is no value here for untrusted content to have chosen. Replaces the hardcoded
    /// `ModelRoute::Worker` at `engine.rs:2654`.
    ///
    /// No wildcard arm: ADR-008's 2026-08-10 amendment (`DECISIONS.md:1038`) asks for a
    /// fourth variant, and when it lands this is a compile error, not a silent inheritance.
    pub fn for_child(parent: ModelRoute) -> ModelRoute {
        match parent {
            ModelRoute::Orchestrator => ModelRoute::Worker,
            ModelRoute::Worker       => ModelRoute::Worker,
            ModelRoute::Summarizer   => ModelRoute::Summarizer,
        }
    }
}
```

Nothing else in `profile.rs` changes: `CapabilityProfile::new`'s signature, its three quarantine invariants, the hand-written `Deserialize` at `:353` and `grant_egress_host` are untouched, and no new mutable route into the struct is opened.

**2. `crates/marlowe-loop/src/budget.rs` — not guarded.**

```rust
pub struct CallLimits {
    pub max_output_tokens: u64,
    /// Which model this call goes to. ADR-008: routing is by task role, declared in
    /// `CapabilityProfile`. **No default, no `Default` impl, no `#[serde(default)]`.**
    /// There are 31 construction sites across 17 files
    /// (`grep -rn "CallLimits {" --include=*.rs crates/ | grep -v "pub struct CallLimits"`),
    /// including three under `examples/` that `cargo test` does not compile by default.
    /// Adding this field is a compile error at every one of them, and the 31 mechanical
    /// edits ARE the deliverable — reaching for `..Default::default()` reintroduces exactly
    /// the silent inheritance this field exists to prevent.
    pub route: ModelRoute,
}

impl Budget {
    pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens, route }
    }
}
```

**3. `crates/marlowe-loop/src/engine.rs` — not guarded.**

```rust
// :794   let limits = run.budget.call_limits(&run.spent);
        let limits = run.budget.call_limits(&run.spent, run.profile.model_route());

// :2654  ModelRoute::Worker,
        ModelRoute::for_child(run.profile.model_route()),

// :2726 the ADR-057 §2 receipt gains one clause — the ROLE, never a model tag
        "[spawned] tools: {granted_tools} · budget: {} tokens · model: {} · orphan: {} · returns: {}",
        //                                            ^ "orchestrator" | "worker" | "summarizer"

// :2582 the refusal sentence gains four words, ready for Session G
//   "...so a child's tools, budget, orphan policy AND MODEL ROLE can no longer be composed here..."

// in the RunSpawned payload — AUDIT ONLY, EXPLICITLY NOT THE ENFORCEMENT
        "model_route": child_profile.model_route(),
```

**4. All THREE production drivers read `limits.route`.** This is the correction that matters most.

```rust
// crates/marlowe-provider/src/ollama.rs:300
        let model = self.routing.model_for(limits.route).to_string();

// crates/marlowe-provider/src/llamacpp.rs:1069 — LlamaCppDriver takes a `Routing`, not `model: String`
        "model": self.routing.model_for(limits.route),

// crates/marlowe-openrouter/src/driver.rs:210 — same change
        "model": self.routing.model_for(limits.route),
```

**5. THE WINDOW FOLLOWS THE ROUTE, OR THE PRODUCT REFUSES TO START.** `crates/marlowe-provider/src/ollama.rs:128`'s `Availability::probe` already iterates `routing.models()` (`:152`) against `/api/tags`. Extend it: for each routed model also read `context_length` from `GET /api/show`, and add

```rust
Availability::WindowTooSmall { model: String, reports: u32, configured: u32 },
```

refusing at startup when any routed model's window is below the driver's configured `context_tokens`. A load-time error in preference to a sensible default. This closes the second-definition hazard the reviewed design left open: today `capability` is built from `routing.model_for(Orchestrator)` (`ollama.rs:242`), `context_tokens` is set once (`daemon.rs:2120-2121`), `num_ctx` rides every request, the assembler window is derived from the same value, and `llamacpp.rs:1080` / `openrouter/driver.rs:214` clamp `max_tokens` to `context_tokens / 4`. Route the model without this check and every one of those describes the orchestrator while the bytes go elsewhere — ollama.rs's own field doc records that exact failure from M2 C2e. **No `daemon.rs` edit is required for this** (another agent holds that file).

### Explicitly NOT shipped in Session C, and why

`SpawnRequest` gains **no** `route` field. `run`'s manifest gains **no** `role` parameter. Both are §13-guarded (`driver.rs`) or model-facing, and both would be adjudicated correctly and honoured by nothing until the four-role table exists. Session G lands them together with these two lines, pre-pinned here so the wrong-order change is impossible to make quietly:

```rust
// crates/marlowe-loop/src/driver.rs  ** §13-GUARDED — SESSION G, THE HUMAN'S **
pub struct SpawnRequest {
    // ... existing EIGHT fields (task, contract, orphan, share, grant_tokens,
    //     tools, tools_declared, reads_untrusted), unchanged ...
    /// `None` means the harness decides: `ModelRoute::for_child(parent)`.
    /// `Some(_)` is a **COMPOSED TARGET** under ADR-023.
    /// NO `#[derive(Deserialize)]` may land on this struct with it — instance #12.
    pub route: Option<ModelRoute>,
}

// crates/marlowe-loop/src/engine.rs:3237
fn composes_spawn_targets(req: &SpawnRequest) -> bool {
    !req.tools.is_empty()
        || req.grant_tokens.is_some()
        || !matches!(req.orphan, OrphanPolicy::Terminate)
        || req.route.is_some()            // ← the target check for the role
}

// crates/marlowe-loop/src/profile.rs — the upgrade ceiling, independent of the latch
impl ModelRoute {
    /// Explicit, NOT `derive(Ord)`: declaration order makes the strongest variant the
    /// smallest, so `<=` would read backwards at every call site.
    pub fn strength(self) -> u8 {
        match self { Self::Orchestrator => 2, Self::Worker => 1, Self::Summarizer => 0 }
    }
    pub fn may_grant(self, requested: ModelRoute) -> bool {
        requested.strength() <= self.strength()
    }
}
```

**Downgrade is deliberately NOT bounded and must not be "fixed" with a floor.** Layer 1's containment does not depend on the reader's competence — `ExposedSet::empty()` and `EgressPolicy::DenyAll` hold whatever model runs — so a dumber reader produces a worse summary, not an escalation. A fidelity risk of the class ADR-041 already concedes and §9.1's A3/A8 already measure.

### The tests. Each names its file and the mutation that reddens it.

**T1 — `the_model_and_the_window_in_the_request_body_both_follow_the_route`**, new file `crates/marlowe-provider/tests/model_route_reaches_the_request_body.rs`. Over `Routing::new("orch-m","work-m","summ-m")` — three DISTINCT names, with the reason in the file — assert `driver.request_body(&view, &tools, CallLimits { max_output_tokens: 256, route: ModelRoute::Worker })["model"] == "work-m"` and `["num_ctx"]` equals the window the routed model reports, then the same for `Orchestrator` → `"orch-m"`. **Carries its negative control in the same test**: `Routing::uniform("one")` returns `"one"` for both routes — which is what production runs today — so a test written against `uniform` would be green whether or not the route is read. **Repeat all of it against `LlamaCppDriver` and `OpenRouterDriver` in the same file**; a driver whose `request_body` ignores `limits.route` fails by name. *Mutation:* restore `model_for(ModelRoute::Orchestrator)` at `ollama.rs:300` — reads `left: "orch-m", right: "work-m"`. *Second mutation:* leave `llamacpp.rs:1069` as `self.model` — the llama.cpp arm fails identically.

**T2 — `a_child_is_routed_below_its_parent_and_the_bytes_say_so`**, `crates/marlowe-loop/tests/spawn_and_budget.rs`. Drive a real spawn from an `Orchestrator` root with a `ModelDriver` that **records `limits.route` on every call** — the pattern `crates/marlowe-loop/tests/quarantine_batch.rs:201` already uses, where the parameter is `l:` rather than `_l:`. Assert the recorded sequence is `[Orchestrator, Worker]` at depth 1 and `[Orchestrator, Worker, Worker]` at depth 2. Assert the journal payload separately and label that assertion **audit, not enforcement**. *Mutation:* make `for_child` return its argument — reads `left: [Orchestrator, Orchestrator], right: [Orchestrator, Worker]`. *Second mutation:* revert `engine.rs:794` to a fixed route — every recorded route becomes identical.

**T3 — `a_model_that_names_a_model_role_produces_an_identical_spawn_request`**, `crates/marlowe-loop/src/driver.rs`'s own `mod tests` (or `crates/marlowe-provider/tests/spawn_from_a_model_reply.rs` if `driver.rs` is not to be touched at all). `SpawnRequest` derives `PartialEq`, so this is one assertion:

```rust
let with    = SpawnRequest::from_args(&args(json!({"task":"t","exposed_tools":"",
                  "role":"high","level":"High","model":"marlowe-dawn:9b-super"})));
let without = SpawnRequest::from_args(&args(json!({"task":"t","exposed_tools":""})));
assert_eq!(with, without, "no spelling of a model role may reach `from_args`");
```

Three spellings because a future session will pick one of them. This is the structural-withholding assertion, sibling to ADR-057 §5's treatment of `share` and `reads_untrusted`. *Mutation:* have `from_args` read any of `role`/`level`/`model` into any field — fails immediately, with no dependence on `Engine::spawn`, the journal, or a driver.

**T4 — `run_declares_exactly_five_parameters_and_exactly_three_are_targets`**, `crates/marlowe-tools/src/builtin.rs` `mod tests`, beside `the_child_capability_arguments_are_targets` at `:897`. The full parameter-name set of `run`'s manifest equals the literal `["task","output_contract","exposed_tools","budget_tokens","orphan_policy"]` and the Target subset equals `["exposed_tools","budget_tokens","orphan_policy"]`, **both written out independently of the manifest** — instance #19 discipline, and a strict improvement on `:907-908`'s `role_of("share") == None`, which cannot see the set grow in any other direction. The comment must name M3-DESIGN §1.1's `master`/`worker` **kind** parameter as the expected next addition, and state that adding it requires a `composes_spawn_targets` clause and a T5 row in the same commit. *Mutation:* add any parameter to `run`'s registration — fails naming it; `:900-902` stay green through all of them.

**T5 — `every_target_run_declares_is_refused_under_a_latched_floor`**, `crates/marlowe-provider/tests/spawn_from_a_model_reply.rs`, generalising `a_latched_run_cannot_compose_a_childs_budget_or_lifetime` (`:667`). Two parts. (a) A table `param -> a JSON value that is not the harness default` must have a row for **every** `ArgumentRole::Target` parameter in `registry.manifest(&ToolId::new("run")).params()`, failing by name if one is missing — **the table's completeness is checked against the manifest, not against itself**, and the comment must say that simplifying this to iterate the table instead of the manifest silently removes the only coupling between `composes_spawn_targets` and the manifest it mirrors. (b) For each row, the existing `spawn_count` helper (`:589`) reports `clean == 1` and `tainted == 0` with the floor asserted at `UntrustedContent` — the pair discipline the file already documents, because `RunSpawned == 0` is also what a build that cannot spawn at all looks like. *Mutation:* declare a new Target on `run` without a `composes_spawn_targets` clause — (a) fails by name. *Independently:* delete `|| req.grant_tokens.is_some()` — (b) fails for `budget_tokens` with `left: 1, right: 0`.

**T6 — `the_quarantined_readers_call_carries_a_different_route_than_its_parents`**, `crates/marlowe-loop/tests/quarantine_batch.rs`. Record `limits.route` on every `ModelDriver::call` across one `condense_batch` from an `Orchestrator` parent: the parent's calls carry `Orchestrator`, the quarantined reader's carries `Worker` (`CapabilityProfile::quarantined_reader()`, `profile.rs:147`), and the sequence contains both. *Mutation:* revert `engine.rs:794` to a fixed route — every recorded route becomes identical.

**T7 — `the_receipt_names_the_model_role`**, `crates/marlowe-provider/tests/spawn_from_a_model_reply.rs`, using the existing `receipt_for` helper (`:249`). *Mutation:* drop `· model: {}` from the format string at `engine.rs:2726` — fails by name.

**T8 — LIVE CHECK, not a unit test.** Per CLAUDE.md's pipe-tested-guard rule; record under `runs/<session>/`. Configure a non-uniform routing (three distinct tags), run one `run` call in the TUI under `--dev`, and read the outbound-request dump: **two distinct `"model"` values and two coherent `"num_ctx"` values** across the parent's and the child's bodies. Then `GET /api/ps` for residency, and `target/release/marlowe.exe --eval-adapter --profile-root "$(mktemp -d)" --embedder-model models/jina-embeddings-v2-small-en --reranking off < /dev/null` for the provider line. *Expected failure reading:* run it under `Routing::uniform` — production's configuration today — and both bodies read the same `"model"`. That is what the wiring doing nothing looks like, which is why the live check must deliberately use three tags.

### Residual #16, recorded rather than claimed closed

**`ModelRoute::Summarizer` still has no reader after Session C**, and the ADR must say so. No `CapabilityProfile` constructor produces it (`quarantined_reader` and `consolidation` are `Worker`, `interactive` is `Orchestrator`, `interactive_with` inherits), and compaction runs through a different port — `trait Summarizer` at `crates/marlowe-loop/src/driver.rs:330`, implemented by `PassthroughSummarizer` at `crates/marlowe-daemon/src/daemon.rs:635` — which never sees a `CallLimits`. So `Routing`'s `summarizer` field stays dead and `routing_is_by_role_and_the_table_is_the_only_place_a_model_is_named` (`routing.rs:117`) stays green over a dead third of the table, because it builds its own `Routing` inside the test. Routing compaction requires changing the `Summarizer` trait signature, which is a §13-guarded `driver.rs` edit: **Session G, and the human's.**

### SECURITY-AUDIT

Add `model_route` as the **ninth** entry in the family-#16 roll at `docs/design/SECURITY-AUDIT.md:135` (which currently names eight: `BASH_TIMEOUT_MS`, `manifest_provenance()`, ~~`EgressPolicy::grant`~~ closed, `NeedsApproval { tier }`, `inline_threshold_bytes`, invariant 8's profile-root rule, `NoControl`, `recall`'s maturation label). **LOW severity — a cost and quality defect, not a containment one.** Evidence: `grep -rn "\.model_route()" --include=*.rs crates/` returns **zero**; `ollama.rs:300` hardcodes `Orchestrator`; `Engine::spawn` passes `driver: ports.driver` straight to the child (`engine.rs:2883`); and every production `Routing` is `uniform` — `crates/marlowe-daemon/src/daemon.rs:1263, 1338, 1503, 1889, 1976` **and `crates/marlowe/src/agent.rs:47`**, six sites. Add `Routing.summarizer` as the tenth.

### Contract impact

**No schema change.** `CapabilityProfile.model_route: ModelRoute` is already pinned at `docs/design/CONTRACTS.md:952`; it gains one comment in `orphan_policy`'s style: `// a TARGET: declared at spawn by the harness, never composed by a model`. `CallLimits`, `ModelDriver` and `SpawnRequest` are pinned nowhere (§12 pins five loop-boundary types plus §12.1's `MemoryHost`), so `CallLimits.route` is not a pinned-contract change. **`SpawnRequest`'s fields should NOT be pinned this session** — ROADMAP's M3 Session C row saying "CONTRACTS §5 pins it" is false: `grep -n SpawnRequest docs/design/CONTRACTS.md` returns one hit, line **941**, pinning `fn spawn(&self, req: SpawnRequest) -> RunId`, the method and not the shape. Pin it in Session G, once, with `route` included. New `DECISIONS.md` entry: **"A model role is a target."** ADR-008 amended by reference only (`DECISIONS.md:1038`).

### Guarded files

- `crates/marlowe-loop/src/profile.rs` — **EDITED. §13-GUARDED. HUMAN APPROVAL REQUIRED** for `ModelRoute::for_child`.
- `crates/marlowe-loop/src/driver.rs` — **READ ONLY, and staying untouched is the recommendation.** `SpawnRequest.route` is Session G's and the human's.
- `crates/marlowe-permission/src/adjudicate.rs`, `taint.rs` — **READ ONLY.** No change to `blocks_composed_targets`, no change to the §2 target loop, no new `ArgumentRole` variant. Not because the adjudicator already covers the role — it is not on the spawn path at all — but because `composes_spawn_targets` is.
- `crates/marlowe-daemon/src/daemon.rs` — **NOT TOUCHED.** Another agent holds it, and none of the above requires it.

### Open for the human

1. **The name of the fourth role — and, before naming it, whether it is already named.** ADR-008's amendment (`DECISIONS.md:1038`) says `ModelRoute` gains a **compression** role and calls it the enforcement point for brief §10's condensed structured returns, i.e. the quarantined reader. `ModelRoute` still has three variants; `quarantined_reader()` is routed `Worker`. `AGENT-DIRECTORY.md:53` says four roles with three named. These may be the same gap or two. Not merged here.
2. **The kind → route table.** M3-DESIGN §1.1's `master`/`worker` declaration and §1.3's per-type worker profiles need the role to vary by KIND; `for_child` varies it by DEPTH. Which role a master, a worker, an extractor and the unnamed fourth get is the human's, and it blocks `AGENT-DIRECTORY.md` §2a's per-role admission queue — which §2a says is **Session C's problem, not Session G's**. Session C is therefore shipping a placeholder where §2a expects a table, and that is recorded rather than resolved.
3. **Approving the §13 edit to `profile.rs`.**
4. **Whether a route a USER names in the Session G window is `UserAsserted` and therefore always granted**, including upgrading a whole worker subtree to the orchestrator model. Same run-vs-session shape as SECURITY-AUDIT §8 on ADR-023's latch and ADR-032 §3.1's grant. Three questions, one shape.
5. **Whether Marlowe's own route is user-selectable at all.** `04-addendum-persona.md` is binding and §C4's anti-sycophancy probe set is a standing regression test a model swap is blocking on. `for_child` never changes the root's route, so Session C does not touch this; the Session G window's "secretary model" dropdown does.
6. **`SpawnRequest` pinned now or in G with `route` included.** Recommendation: G.

### The VRAM sentence, corrected before G builds on it

`AGENT-DIRECTORY.md:55` — *"10.0 GB of the card's 16, leaving headroom for the KV cache, the embedder and the reranker"* — is false. Measured on this machine 2026-08-30 via `GET /api/ps`: 5,086 MiB held by the desktop before any model loaded; all three roles co-resident at 10,849,836,070 B (`marlowe-dawn:9b-super` 5,832,064,368; `marlowe-mini:4b-super` 3,271,515,176; `marlowe-mini:2b` 1,746,256,526), each reporting `context_length: 32768`; final state **14,993 MiB used, 1,053 MiB free**. ADR-044 resolves the embedder's provider against **free VRAM at load**, so the embedder falls to CPU with a correct-looking log line. Not Session C's to fix — Session C ships under `uniform` — but the sentence must be corrected before G builds on it, and the check is the `--eval-adapter` provider line already in `CLAUDE.md`.

---

## Original recommendation

A model role is a **target**, not a payload, and not a third thing. The mechanism decides it: `adjudicate.rs` §2 discriminates targets by a per-parameter `ArgumentRole::Target` declaration with `unwrap_or(Target)` as the fail-closed default — it is not a type list, so nothing has to be added to a §13-guarded enum to include it — and `orphan_policy`, a closed two-word enum that chooses only a child's *lifetime*, is already declared `Target` and already covered by `composes_spawn_targets`. A closed enum that chooses the inference engine executing every subsequent decision the child makes is a target a fortiori; arguing "the set is closed and small" would retroactively de-target `orphan_policy`. But the enforcement Session C should ship is **structural withholding, not a second gate**: `SpawnRequest` gains no `route` field, `run`'s manifest gains no `role` parameter, and the ADR pre-pins the two lines Session G must land with the parameter (`composes_spawn_targets` gains `|| req.route.is_some()`, and `Engine::spawn` gains the `may_grant` narrowing). The reason is measured, not stylistic: **`CapabilityProfile::model_route()` has ZERO call sites in the entire repository** (`grep -rn "\.model_route()" --include=*.rs .` returns 0), `OllamaDriver::request_body` hardcodes `model_for(ModelRoute::Orchestrator)` at `ollama.rs:300`, every production `Routing` is `Routing::uniform`, and `Engine::spawn` passes `driver: ports.driver` straight through — so the entire subagent tree runs on the secretary model today and `ModelRoute::Worker` at `engine.rs:2654` reaches nothing. Shipping a model-facing `role` parameter now would put a manifest test asserting `role_of("role") == Target` on top of a field nothing honours: instance #16 stacked on a dead path, which is the exact pair ADR-057 §4 took a milestone to find. So Session C's work on item (4) is: record the answer, and **close the reader gap so the answer is enforceable** — thread `ModelRoute` through `CallLimits` into `request_body`, and replace the hardcoded child route with `ModelRoute::for_child(parent)`, a total function of the parent alone with no model input and therefore no composable value.

### Types

```rust
// ═══ SESSION C — WRITTEN ═══════════════════════════════════════════════════════════
//
// 1. crates/marlowe-loop/src/profile.rs   ** §13-GUARDED — HUMAN APPROVAL REQUIRED **

impl ModelRoute {
    /// The route a child of a run at `parent` gets. **Total, and a function of the parent
    /// alone** — no argument, no model input, so there is no value here for untrusted
    /// content to have chosen. This replaces the hardcoded `ModelRoute::Worker` at
    /// `engine.rs:2654`, which is where a child's route is decided today.
    ///
    /// No wildcard arm: ADR-008's 2026-08-10 amendment asks for a fourth variant, and when
    /// it lands this is a compile error rather than a silent inheritance.
    pub fn for_child(parent: ModelRoute) -> ModelRoute {
        match parent {
            ModelRoute::Orchestrator => ModelRoute::Worker,
            ModelRoute::Worker       => ModelRoute::Worker,
            ModelRoute::Summarizer   => ModelRoute::Summarizer,
        }
    }
}

// 2. crates/marlowe-loop/src/budget.rs    (not guarded)

pub struct CallLimits {
    pub max_output_tokens: u64,
    /// Which model this call goes to. ADR-008: routing is by task role, declared in
    /// `CapabilityProfile`. **No default and no `Default` impl.** Every construction site
    /// today is a struct literal (~8, all in tests), so adding this field is a COMPILE
    /// ERROR at each one rather than a silent inheritance of `Orchestrator` — a load-time
    /// error in preference to a sensible default.
    pub route: ModelRoute,
}

impl Budget {
    pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens, route }
    }
}

// 3. crates/marlowe-loop/src/engine.rs    (not guarded — ordinary milestone work)

// :794   let limits = run.budget.call_limits(&run.spent);
        let limits = run.budget.call_limits(&run.spent, run.profile.model_route());

// :2654  ModelRoute::Worker,
        ModelRoute::for_child(run.profile.model_route()),

// in the RunSpawned payload — AUDIT ONLY, EXPLICITLY NOT THE ENFORCEMENT
        "model_route": child_profile.model_route(),

// 4. crates/marlowe-provider/src/ollama.rs (not guarded)

// :300   let model = self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator)...
        let model = self.routing.model_for(limits.route).to_string();


// ═══ SPECIFIED HERE, DELIBERATELY NOT WRITTEN IN SESSION C ═════════════════════════
// Each of these is read by nothing until `SpawnRequest.route` exists. Writing them now
// would be instance #16 committed while answering an instance-#16 question.
//
// crates/marlowe-loop/src/driver.rs       ** §13-GUARDED — Session G, the human's **

pub struct SpawnRequest {
    // ... existing eight fields, unchanged ...
    /// `None` means the harness decides: `ModelRoute::for_child(parent)`.
    /// `Some(_)` is a **COMPOSED TARGET** under ADR-023.
    pub route: Option<ModelRoute>,
}

// crates/marlowe-loop/src/engine.rs:3237
fn composes_spawn_targets(req: &SpawnRequest) -> bool {
    !req.tools.is_empty()
        || req.grant_tokens.is_some()
        || !matches!(req.orphan, OrphanPolicy::Terminate)
        || req.route.is_some()            // ← the target check for the role
}

// crates/marlowe-loop/src/profile.rs — the upgrade ceiling, independent of the latch
impl ModelRoute {
    /// Explicit, NOT `derive(Ord)`: declaration order makes the strongest variant the
    /// smallest, so `<=` would read backwards at every call site.
    pub fn strength(self) -> u8 {
        match self { Self::Orchestrator => 2, Self::Worker => 1, Self::Summarizer => 0 }
    }
    /// A narrowing, never a widening — the same rule `Engine::spawn` already applies to
    /// the tool set. Withheld structurally; there is no counter and no zero.
    pub fn may_grant(self, requested: ModelRoute) -> bool {
        requested.strength() <= self.strength()
    }
}

// crates/marlowe-loop/src/engine.rs, beside the existing tool-narrowing loop (~2635)
if let Some(r) = req.route {
    if !run.profile.model_route().may_grant(r) {
        self.spawn_refused(state, ports,
            "a child cannot be routed to a stronger model than this run holds");
        return;
    }
}

// and the existing refusal sentence at engine.rs:2603 gains four words:
//   "...so a child's tools, budget, orphan policy AND MODEL ROLE can no longer be
//    composed here — spawn with none of them and the child gets the safe defaults..."

// NAMING: there is exactly ONE type. `ModelRoute` is already pinned in CONTRACTS §5.
// AGENT-DIRECTORY's High/Medium/Low is a RENDERING of it in the Session G window, never a
// second `AgentLevel` enum beside it. And the field is `route`, not `role`: `ArgumentRole`
// already means Target-vs-Payload in the adjudicator this decision is about.
```

### Enforcement sites

- `CallLimits.route (new)` -> **crates/marlowe-provider/src/ollama.rs :: OllamaDriver::request_body (line 300, replacing the hardcoded ModelRoute::Orchestrator)** | breaks: Every model call in the tree goes to the orchestrator model again — the state the product is in today. T1 reads `left: "orch", right: "work"`.
- `CapabilityProfile::model_route() (EXISTS, currently ZERO callers in the repo)` -> **crates/marlowe-loop/src/engine.rs :: Engine::run line 794 (`run.budget.call_limits(&run.spent, run.profile.model_route())`) and Engine::spawn line 2654** | breaks: The field returns to being a declared control nothing reads — the ninth member of SECURITY-AUDIT's family-#16 list, which does not yet name it. T1 and T6 both go red.
- `ModelRoute::for_child (new, profile.rs, §13-guarded)` -> **crates/marlowe-loop/src/engine.rs :: Engine::spawn, line 2654, the argument to CapabilityProfile::new** | breaks: A child's route is either hardcoded again or inherited from the parent; an Orchestrator parent's children all run the 9B, which is ADR-008's cost lever inverted. T2 reads `left: "orchestrator", right: "worker"`.
- `RunSpawned journal payload gains "model_route" — AUDIT ONLY, NOT ENFORCEMENT` -> **crates/marlowe-loop/tests/spawn_and_budget.rs (T2) and crates/marlowe-provider/tests/spawn_from_a_model_reply.rs (T3), by the same route `spawned[0]["reads_untrusted"]` is already read at spawn_and_budget.rs:189** | breaks: T2 and T3 cannot observe the child's route at all. Stated explicitly as observability: a journal field is a record of a decision, never the making of one, and anyone citing it as the guard has made the #16 mistake.
- `INVARIANT: `run` declares no model-role parameter (structural withholding, ADR-057 §5's treatment of `share` and `reads_untrusted`)` -> **crates/marlowe-tools/src/builtin.rs :: mod tests (T4), which pins the exact five-name parameter set and the exact three-name Target subset as literals written independently of the manifest** | breaks: A future session adds a `role` parameter, `from_args` ignores it, and the model is silently disobeyed — or `from_args` honours it and `composes_spawn_targets` does not cover it. T4 fails by name on the first, T5 on the second.
- `INVARIANT: every parameter `run` declares ArgumentRole::Target is refused under a latched floor (couples the manifest to composes_spawn_targets, which is a hand-written mirror of it)` -> **crates/marlowe-provider/tests/spawn_from_a_model_reply.rs (T5), which iterates `registry.manifest(&ToolId::new("run")).params()` and requires a table row for every Target** | breaks: The two definitions drift silently — exactly what happened between M2 and ADR-057 §4, where three Targets were declared in a manifest and enforced by nothing, invisibly, because the path was dead.
- `SpawnRequest.route (Session G, NOT written now)` -> **crates/marlowe-loop/src/engine.rs :: composes_spawn_targets line 3237, and the may_grant narrowing beside the existing tool-narrowing loop** | breaks: N/A in Session C — the field does not exist, which is the point. When it lands, T5 turns red if the clause does not land with it.

### Rejected

- **A model role is a PAYLOAD — content the child reasons about, like `task` and `output_contract`.** - Payload in this codebase means prose handed to the child; target means a value the harness itself acts on. The route is consumed by `Routing::model_for` inside the harness, never shown to the child, and it selects the engine that composes every target the child will later emit — it sits upstream of `exposed_tools`, which is uncontroversially a Target. And `orphan_policy` — a closed two-value enum choosing only a child's lifetime — is already `Target`; calling the route a payload de-targets `orphan_policy` by the same argument.
- **A third thing: a new `ArgumentRole::Hint` variant for values that are neither target nor payload.** - `adjudicate.rs` §2 reads `manifest.role_of(name).unwrap_or(ArgumentRole::Target)` — the default for an undeclared name is Target, deliberately, so that a tool cannot accept a target it never listed. A third variant turns a fail-closed binary into a three-way choice and puts all ten builtin manifests up for re-audit, in a §13-guarded file, to answer a question that the existing binary already answers correctly.
- **Ship the model-facing `role` parameter on `run` in Session C, declared `ArgumentRole::Target`, with `composes_spawn_targets` extended.** - `CapabilityProfile::model_route()` has zero call sites, `request_body` hardcodes `Orchestrator`, and production routing is `Routing::uniform` — so the parameter would be adjudicated correctly and then honoured by nothing, with `run.role_of("role") == Target` green on top. Instance #16 layered on a dead path, which is precisely the pair ADR-057 §4 describes and which stayed invisible for a milestone because neither half was visible from the other. Read the field before you let anyone name it.
- **A new `AgentLevel { High, Medium, Low }` enum on `SpawnRequest`, matching AGENT-DIRECTORY's own vocabulary, mapped to `ModelRoute` at the provider.** - Two definitions of the same thing on opposite sides of the profile — the two-sides-silently-disagree shape this project logs repeatedly. `CapabilityProfile.model_route: ModelRoute` is already pinned in CONTRACTS §5 and `routing.rs` already declares it *the only place a model name appears*. High/Medium/Low is a rendering for the Session G window, not a second type.
- **Hold the granted route on the `Run` beside `trust_floor`, as the latch is held.** - ADR-032's own recorded reason, one field over: `CapabilityProfile::new` holds the quarantine invariants and the child is constructed *from* the profile, so a route held beside it is a second definition of what the child is, and `quarantined_reader()`'s harness-fixed route could be bypassed while every quarantine test stayed green.
- **Derive the route at spawn from an LLM assessment of the task (M3-DESIGN §9.1 arm A1(b)), so the spawner never names it at all.** - It loses on security, not on quality. It makes the route a function of an attacker-shapeable payload with no argument, no tool call and no permission check in sight — a laundering path *around* the target check rather than through it. If A1 is run as an arm, the route must be excluded from what the assessment may choose, or the arm is a security experiment wearing a quality label.

### Tests

- `the_model_in_the_request_body_follows_the_runs_route` in `crates/marlowe-provider/tests/model_route_reaches_the_request_body.rs (new)`
  - asserts: Over `Routing::new("orch-m","work-m","summ-m")` — three DISTINCT names, and the file says why — `driver.request_body(&view, &tools, CallLimits { max_output_tokens: 256, route: ModelRoute::Worker })["model"] == "work-m"`, and the same call with `route: Orchestrator` gives `"orch-m"`. Carries its negative control in the same test: `Routing::uniform("one")` returns `"one"` for both routes, which is what PRODUCTION runs today — so a test written against `uniform` would be green whether or not the route is read, and that is the proxy this test exists to avoid. Asserts the bytes sent, not the table, per the persona/pipe-tested-guard rule.
  - red on: Restore `let model = self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator)` at ollama.rs:300 — i.e. HEAD as it stands today. Reads `left: "orch-m", right: "work-m"`.
- `a_child_is_routed_below_its_parent_and_the_root_is_not` in `crates/marlowe-loop/tests/spawn_and_budget.rs`
  - asserts: Drive a real spawn from an `Orchestrator` root and read the journal the way `spawned[0]["reads_untrusted"]` is already read at line 189: `RunSpawned["model_route"] == "worker"`. Then a depth-2 spawn: the grandchild is also `"worker"`, never `"orchestrator"`.
  - red on: Make `ModelRoute::for_child` return its argument (inheritance instead of descent). The depth-1 case reads `left: "orchestrator", right: "worker"`. Second mutation: restore the hardcoded `ModelRoute::Worker` at engine.rs:2654 — reddens the Summarizer-parent case, which is why that case is in the test.
- `a_model_that_names_a_model_role_is_not_given_one` in `crates/marlowe-provider/tests/spawn_from_a_model_reply.rs`
  - asserts: A `run` call carrying `{"task":"t","exposed_tools":"","role":"high","level":"High","model":"marlowe-dawn:9b-super"}` from a CLEAN root at `Orchestrator` spawns one child whose journalled `model_route` is `"worker"`. The three spellings are all there because a future session will pick one of them. This is the structural-withholding assertion, the sibling of ADR-057 §5's treatment of `share` and `reads_untrusted`.
  - red on: Wire `SpawnRequest::from_args` to read `role` into a new `route` field that `Engine::spawn` honours, WITHOUT extending `composes_spawn_targets` — the exact wrong-order change this ADR exists to block. Reads `left: "orchestrator", right: "worker"`.
- `run_declares_exactly_five_parameters_and_exactly_three_are_targets` in `crates/marlowe-tools/src/builtin.rs, mod tests, beside the existing role_of assertions at lines 899-902`
  - asserts: The FULL parameter-name set of `run`'s manifest equals the literal `["task","output_contract","exposed_tools","budget_tokens","orphan_policy"]`, and the Target subset equals the literal `["exposed_tools","budget_tokens","orphan_policy"]`. Both written out independently of the manifest — instance #19 discipline: asserting the absence of the single name `role` cannot see the set grow in any other direction, and a check whose input is the object it checks cannot see that object change size.
  - red on: Add any parameter to `run`'s registration — `role` as Target, `role` as Payload, or anything else. Fails naming the added parameter. The existing lines 900-902 stay green through all three.
- `every_target_run_declares_is_refused_under_a_latched_floor` in `crates/marlowe-provider/tests/spawn_from_a_model_reply.rs, generalising a_latched_run_cannot_compose_a_childs_budget_or_lifetime (line 667)`
  - asserts: Two parts. (a) A small table `param -> a JSON value that is not the harness default` has a row for EVERY `ArgumentRole::Target` parameter in `registry.manifest(&ToolId::new("run")).params()`, failing by name if one is missing — the table's completeness is checked against the manifest, not against itself. (b) For each row, the existing `spawn_count` helper reports `clean == 1` and `tainted == 0` with the floor asserted at `UntrustedContent` — the pair discipline the file already documents, because `RunSpawned == 0` is also what a build that cannot spawn at all looks like. This is the only thing coupling `composes_spawn_targets` (a hand-written mirror) to the manifest it mirrors.
  - red on: Declare a new Target parameter on `run` without adding a clause to `composes_spawn_targets` — part (a) fails naming it. Independently: delete `|| req.grant_tokens.is_some()` from composes_spawn_targets — part (b) fails for `budget_tokens` with `left: 1, right: 0`.
- `the_quarantined_readers_call_carries_a_different_route_than_its_parents` in `crates/marlowe-loop/tests/quarantine_batch.rs (the driver at line 195 already receives `l: CallLimits` un-underscored)`
  - asserts: Record `limits.route` on every `ModelDriver::call`. Over one `condense_batch` from an `Orchestrator` parent: the parent's calls carry `Orchestrator` and the quarantined reader's call carries `Worker`, and the sequence contains both. The reader's route is the harness's — `CapabilityProfile::quarantined_reader()` — regardless of anything the parent asked for, which is what keeps layer 1's reader off the model a compromised parent would prefer.
  - red on: Revert engine.rs:794 to `run.budget.call_limits(&run.spent)` with a fixed `Orchestrator` route. Every recorded route becomes identical: `left: [Orchestrator, Orchestrator], right: [Orchestrator, Worker]`.
- `LIVE CHECK (not a unit test) — the route reaches the running process, not just the source` in `manual, per CLAUDE.md's pipe-tested-guard rule; record the output under runs/<session>/`
  - asserts: Configure a NON-uniform routing (three distinct tags) and run one `run` call in the TUI under `--dev`, reading the outbound-request dump: two distinct `"model"` values across the parent's and the child's bodies. Then, on the same machine, `GET /api/ps` for residency and `target/release/marlowe.exe --eval-adapter --profile-root "$(mktemp -d)" --embedder-model models/jina-embeddings-v2-small-en --reranking off < /dev/null` for the provider line. Both are commands printing a number.
  - red on: Run it under `Routing::uniform` — which is what production configures today — and the two bodies read the same `"model"`. That is the reading to expect if the wiring did nothing, and it is why the live check must deliberately use three tags.

### Contract impact

**No schema change, and one annotation.** `CapabilityProfile.model_route: ModelRoute` is ALREADY pinned in CONTRACTS §5 (line 952) — the role is already classified, in the pinned contract, as part of a child's capability declaration alongside `exposed_tools` and `egress`, which is itself a supporting argument that it is a target. §5's line gains one comment in `orphan_policy`'s existing style: `pub model_route: ModelRoute,   // a TARGET: declared at spawn by the harness, never composed by a model`. `CallLimits`, `ModelDriver` and `SpawnRequest` are not pinned anywhere (§12 pins five loop-boundary types plus §12.1's `MemoryHost`; `CallLimits` is not among them), so adding `CallLimits.route` is not a pinned-contract change. **`SpawnRequest`'s fields should NOT be pinned in this session**, and ROADMAP's M3 Session C row saying "CONTRACTS §5 pins it" is false and should be corrected: `grep -n SpawnRequest docs/design/CONTRACTS.md` returns one hit, line 941, pinning `fn spawn(&self, req: SpawnRequest) -> RunId` — the method, not the shape. Pinning a shape that is about to grow a `route` field means pinning it and then moving it; pin it in Session G, once, with `route` included. New DECISIONS.md entry required: **"A model role is a target."** ADR-023's list ("which tool, which recipient, which path, which amount") is prose in DECISIONS.md and the brief, not an enum in code — the adjudicator enumerates targets per manifest parameter with a fail-closed default — so extending that list needs a DECISIONS entry and requires **no edit to `adjudicate.rs`**. ADR-008 is amended by reference only (its 2026-08-10 amendment already asks for a fourth `ModelRoute` variant that has never been added).

### Guarded

["crates/marlowe-loop/src/profile.rs — EDITED IN SESSION C. `ModelRoute::for_child` is added to a §13-guarded file. The human must approve. Nothing else in the file changes: `CapabilityProfile::new`'s signature, its three quarantine invariants and `grant_egress_host` are untouched, and no new mutable route into the struct is opened.", "crates/marlowe-loop/src/driver.rs — READ ONLY IN SESSION C, and this ADR's central recommendation is that it STAYS untouched now. `SpawnRequest.route` is specified above and belongs to Session G; adding it is a §13-guarded edit and is the human's.", 'crates/marlowe-permission/src/adjudicate.rs — READ ONLY. NOT edited, and this is worth stating positively: the answer requires no change to `blocks_composed_targets`, no change to the §2 target loop, and no new `ArgumentRole` variant. The role is a target under the mechanism as it already stands.', 'crates/marlowe-permission/src/taint.rs — READ ONLY. Unchanged; per-value provenance already covers a `route` parameter the day one exists, because `TaintSet::of` fails closed on an untracked name.']

### For the human

["THE NAME OF THE FOURTH ROLE — and, before naming it, whether it is already named. ADR-008's 2026-08-10 amendment (DECISIONS.md:1030) says in terms: *`ModelRoute` gains a compression role*, distinguishes it from extraction, and calls it the enforcement point for brief §10's condensed structured returns — i.e. the quarantined reader. `ModelRoute` still has three variants; `quarantined_reader()` is routed `Worker`. AGENT-DIRECTORY §2 says four roles with three named. These may be the same gap or two different ones. An implementer must not merge them silently, and I have not.", 'Approving the §13 edit to `crates/marlowe-loop/src/profile.rs` for `ModelRoute::for_child`.', "Whether a route a USER names in the Session G window is `UserAsserted` and therefore always granted — including an upgrade of a whole worker subtree to the orchestrator model. That is the `may_grant` ceiling question, and it is the same run-vs-session question SECURITY-AUDIT §8 raises about ADR-023's latch and ADR-032 §3.1's grant. Three open questions, one shape, all the human's.", "Whether Marlowe's own route is user-selectable at all. AGENT-DIRECTORY §3 item 8: the persona is not configurable (04-addendum-persona.md, binding) and §C4's anti-sycophancy probe set is a standing regression test a model swap is BLOCKING on. `for_child` never changes the root's route, so Session C does not touch this — but the Session G window's 'secretary model' dropdown does.", 'Whether `SpawnRequest` is pinned in CONTRACTS §5 now or in Session G with `route` included. My recommendation is G; the cost either way is small and the choice is a pinned-contract question.']

### Risks

["**SATURATION, ANSWERED DIRECTLY, AND THE ANSWER IS THAT THE ROLE IS NOT THE FIFTH PLACE — A1(b) IS.** CLAUDE.md's lesson is that a floor discriminates only over a MIXED population. But `blocks_composed_targets` is a *gate* (`origin <= UntrustedContent`), not a comparator: over a saturated population a gate fires ALWAYS, not never. So on the spawn path the floor works precisely where a research worker is uniformly tainted — the route simply cannot be composed there. What saturation does reach is the FALLBACK: when the gate fires the value falls to a default, and 'who asserted the default' must not answer 'a model'. `ModelRoute::for_child(parent)` is that answer — a total function of the parent's own declared route, terminating at `CapabilityProfile::interactive()`'s `Orchestrator`, which the user's configuration set. The genuinely saturated version of this question is M3-DESIGN §9.1 arm **A1(b), 'LLM assessment at spawn'**: every candidate task string in a research worker is `UntrustedContent`, the floor is at the bottom for all of them, and the assessment has no argument and no permission check in sight. **That is a fifth place for STATE.md open question 0, and it is a fifth, not one of the four** — the four (ranking inputs, cache keys, derivation lineage, merge decisions) are all inside memory; this one is inside the control plane.", "**DOWNGRADE IS NOT BOUNDED BY THE CEILING AND MUST NOT BE 'FIXED' WITH ONE.** `may_grant` bounds the upgrade attack only; forcing a subtree onto the smallest model is always a narrowing. That is accepted, and the argument is mechanical: layer 1's containment does not depend on the reader's competence — `ExposedSet::empty()` and `EgressPolicy::DenyAll` hold whatever model runs — so a dumber quarantined reader produces a worse summary, not an escalation. It is a FIDELITY risk of exactly the class ADR-041 already concedes and §9.1's A3/A8 already measure. Someone will later read 'downgrade is attacker-useful' and add a floor; the floor would buy nothing and would make a legitimate cheap delegation impossible.", "**INSTANCE #16, LIVE AT HEAD, AND NOT IN THE AUDIT'S LIST.** `.model_route()` has zero callers repo-wide; `request_body` hardcodes `Orchestrator`; `Engine::spawn` passes the parent's driver straight to the child. SECURITY-AUDIT §'s family-#16 roll (line 135) names eight — `BASH_TIMEOUT_MS`, `manifest_provenance()`, `EgressPolicy::grant` (closed), `NeedsApproval { tier }`, `inline_threshold_bytes`, invariant 8's profile-root rule, `NoControl`, `recall`'s maturation label — and `model_route` is not among them. I checked before claiming it. It should be added as the ninth, LOW severity (a cost and quality defect, not a containment one), with the note that `routing_is_by_role_and_the_table_is_the_only_place_a_model_is_named` (routing.rs:117) is green on a build where no run's route reaches the table, because it builds its own `Routing` inside the test.", '**THE FIX IS BEHAVIOURALLY INERT IN PRODUCTION, WHICH MAKES IT UNVERIFIABLE BY ORDINARY USE.** Every production `Routing` is `Routing::uniform(config.model)` (daemon.rs:1196, 1271, 1436, 1780, 1867), so `model_for` returns the same string for all three roles and threading the route changes not one byte on the wire. This is genuinely safe — the VRAM consequence arrives only when Session G configures distinct models — but it means a green suite proves nothing about the running product. The live check must deliberately configure three tags. Same family as `persona/v1.md` loading versus the persona being in the request body.', "**THE VRAM ARITHMETIC IN AGENT-DIRECTORY §2 IS WRONG AND ADR-044 TURNS THAT INTO A SILENT DOWNGRADE.** Measured on this machine today: 5,086 MiB held by the desktop before any model loaded; all three roles co-resident at 10,849,836,070 B; final state **14,993 MiB used, 1,053 MiB free**. §2's *'10.0 GB of the card's 16, leaving headroom for the KV cache, the embedder and the reranker'* is not true — 1,053 MiB is not headroom, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD, so the embedder falls to CPU with a correct-looking log line. This is not Session C's to fix (Session C ships under `uniform`), but the sentence must be corrected before G builds on it, and the check is the `--eval-adapter` provider line already in CLAUDE.md.", "**`composes_spawn_targets` STAYS A HAND-WRITTEN MIRROR OF `run`'s MANIFEST.** T5 is the only thing coupling them, and T5's own value table is a list — the #19 shape. It is written so the table's completeness is checked *against the manifest* rather than against itself, which is the closure; but if someone later simplifies T5 to iterate the table instead of the manifest, the coupling silently stops existing and the suite stays green. The comment in T5 must say so.", "**`RunSpawned.model_route` will be mistaken for the enforcement.** It is an audit field whose only readers are two tests and a human reading the journal. A future session reading 'the route is journalled' as 'the route is checked' repeats the `inline_threshold_bytes` reading exactly. The ADR text and the code comment both say NOT THE ENFORCEMENT."]
