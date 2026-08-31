
---

# CRITIQUE (sound-with-fixes)

**Fatal:** The design's remedy for instance #16 ships a fresh instance of #16: it adds `CallLimits.route` and names exactly one reader (`crates/marlowe-provider/src/ollama.rs:300`), while the daemon ships three `ModelDriver` implementations (`ModelProviderChoice::{Ollama, OpenRouter, LlamaCpp}`, `crates/marlowe-daemon/src/daemon.rs:67,81`). `LlamaCppDriver::request_body` sends `"model": self.model` at `llamacpp.rs:1069` and `OpenRouterDriver::request_body` sends `"model": self.model` at `openrouter/driver.rs:210` — neither holds a `Routing`, neither would read the new field. After the change a grep for readers of `model_route` returns a hit and reads as a positive result on two paths where nothing honours it, which is strictly worse than today's visibly-dead field.

## Strengthened

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

# CRITIQUE (sound-with-fixes)

**Fatal:** The `CHECKPOINT_VERSION` 1 → 2 bump does not refuse a v1 checkpoint by name — it makes it silently vanish. `JournalCheckpoints::decode_all` (durable.rs:238-248) drops undecodable payloads with `.ok()` by deliberate design (895 legacy `{"step": n}` events), and the version check lives at control.rs:238, downstream of that decode. Adding a required `trust_floor` field to `SessionState` under `deny_unknown_fields` makes every v1 payload fail `from_value`, so it never reaches the version check, never becomes `ResumeError::UnsupportedVersion`, and the daemon reports "staged no checkpoint" instead. The design's named test `a_version_1_checkpoint_is_refused_by_name` asserts an error the code cannot produce, and the obvious way to make it pass is `#[serde(default)]` — the exact fail-open the design exists to prevent.

## Strengthened

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

# CRITIQUE (sound-with-fixes)

**Fatal:** `disposition` is a declared control with no reader that distinguishes its two values on Marlowe's own spawn path — `child_of(Secretary, Manage)` and `child_of(Secretary, Work)` both return `TopAgent`, `CapabilityProfile::new` has no `TopAgent` arm, and the design's own test asserts *the same answer for both inputs*, so it is green whether `disposition` is plumbed through or dropped on the floor. M3-DESIGN §1.1's distinction ("`master` … gets a create grant" vs "`worker` — will do the task itself") is unenforced, a work-disposed top-agent can hold `run` and `bash` at once, and the design ships instance #16 with its proxy test pre-written, in the very design whose stated blocking finding is instance #16.

## Strengthened

## What survives, and it is the majority

Four of the design's core judgments are correct and verified against HEAD 186b5d5, and the strengthened design keeps them without change:

1. **The blocking finding is real.** `grep -rn "model_route()" --include=*.rs crates/` returns exactly one hit — the accessor's own definition at `profile.rs:280`. Zero readers. `Routing::new` has zero production callers; every production site is `Routing::uniform`. `ollama.rs:300` reads `self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator)` — hardcoded. Adding `role` without completing the chain is #16 for a third time in one path, and the design is right to make the chain a precondition.
2. **`ModelRoute`, not a new enum.** Correct, for the reason given: `routing.rs`'s header already binds it to a task role, `Routing::model_for` already matches it exhaustively with no wildcard arm (so a fourth variant is a compile error until the table has a model — contract_impact (c) is *already true* and needs recording, not building), and `Engine::spawn` already hardcodes a value for it at `engine.rs:2654`.
3. **`may_create_agents` closes a real, uncovered gap, and it is H2's and not new.** Verified: `ollama.rs:1045` maps `"run" => ModelStep::Spawn(SpawnRequest::from_args(args))`; `Engine::spawn` (engine.rs:2530-2680) checks task, composed targets, budget grant, subagent count, narrowing-against-the-parent's-set, and `CapabilityProfile::new` — and **never checks that the parent's exposed set contains `run`**. SECURITY-AUDIT H2's parenthetical *"`run` was deliberately routed back through `ToolCall` for exactly this reason"* is stale as of ADR-057. Cite H2; do not file it as new.
4. **Structural withholding over counters, and every rejected alternative.** The `edit_calls: 0` rejection, the level-on-`Run` rejection (the `grant_egress_host` argument transfers exactly), the `role: String` rejection, the inheritance rejection, and the "declared, never inferred" rejection are all correct and all stay.

Everything below is what changes.

---

## §1 — Levels, with the disposition carried IN the level

`crates/marlowe-loop/src/profile.rs` — **§13-GUARDED, HUMAN APPROVAL REQUIRED.**

```rust
/// M3-DESIGN §1. **Position in the organisation, not capability.**
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLevel {
    Secretary,
    /// §1.1: Marlowe spawns exactly one kind of thing, and declares *which kind it is*.
    /// `manages` IS that declaration, carried in the level so it cannot be recorded and
    /// then ignored — which is what a separate `disposition` field beside the level would be.
    TopAgent { manages: bool },
    Master,
    Worker,
    ToolSpawned,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition { Work, Manage }

impl AgentLevel {
    /// **Total over the level axis, no wildcard.** A sixth level fails to compile here.
    /// It NEVER returns `ToolSpawned` — that level is reachable only through the harness's
    /// own named constructors, so no model call can produce one (#17: withheld structurally).
    ///
    /// **Total over MODEL-INITIATED spawns only.** The harness's own children —
    /// `quarantined_reader` at `engine.rs:2146`, SCOPED-MEMORY §4's fact extractor — are built
    /// by named constructor and never routed through here, so §1's level 5 sits under any of
    /// levels 1-4. `Budget.depth` still bounds that path and is never 0.
    pub fn child_of(parent: AgentLevel, d: Disposition) -> Result<AgentLevel, LevelRefusal> {
        use AgentLevel::*; use Disposition::*;
        match (parent, d) {
            // §1.1: both arms answer TopAgent — but they are DIFFERENT TopAgents.
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
        matches!(self, AgentLevel::Secretary | AgentLevel::TopAgent { manages: true } | AgentLevel::Master)
    }
}
```

The seventh field and the three new load-time errors:

```rust
pub struct CapabilityProfile {
    exposed_tools: ExposedSet,
    egress: EgressPolicy,
    interrupt: InterruptPolicy,
    model_route: ModelRoute,
    level: AgentLevel,          // NEW — private, constructor-validated, serde-routed
    may_write_memory: bool,
    reads_untrusted: bool,
}

#[error("a {level:?} profile exposes `{tool}`, which is not in MANAGEMENT_TOOLS. M3-DESIGN §1.2: \
         a master holds no working tools STRUCTURALLY — the tool is absent from the set, not \
         forbidden by instruction, and never a counter of zero (#17)")]
MasterHoldsWorkingTool { level: AgentLevel, tool: ToolId },

#[error("a tool-spawned agent exposes {count} tool(s). §1.4: no tools, no persistence, destroyed \
         on return. Strictly wider than the quarantine check — SCOPED-MEMORY §4's fact extractor \
         is tool-spawned and does NOT set `reads_untrusted`, so it is covered by nothing today")]
ToolSpawnedWithTools { count: usize },

#[error("a {level:?} profile holds `run`, the create grant. §1.1: a top-agent spawned to WORK \
         does not orchestrate, and §1: a worker spawns nothing")]
CreateGrantNotHeldAtThisLevel { level: AgentLevel },
```

In `CapabilityProfile::new`, after the three existing quarantine checks — **note the wildcard-free match; `Secretary` is a NAMED arm carrying the reason it is unrestricted, not a `_`:**

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
    // §1's table: "full conversational set". Whether §1.2's structural rule extends to level 1
    // is a question M3-DESIGN §1 does not answer, and `interactive()` currently holds `bash`
    // and `edit`. NAMED rather than swept into `_` so the answer is visible and escalable.
    AgentLevel::Secretary => {}
    // Per-type sets are §1.3 configuration, not a constructor rule.
    AgentLevel::TopAgent { .. } | AgentLevel::Worker => {}
}
```

```rust
pub fn level(&self) -> AgentLevel { self.level }

/// **The create grant IS holding `run`.** ONE definition — `new` above guarantees that no
/// profile at a level which may not hold it contains it, so there is nothing else to consult.
pub fn may_create_agents(&self) -> bool {
    self.exposed_tools.contains(&ToolId::new("run"))
}
```

`Raw` gains `level: AgentLevel` with **no `#[serde(default)]`**. A pre-Session-C checkpoint fails to deserialize with a named serde error. That is the correct trade and a real cost against Session A's shipped resume (`runs/session-a-m3/live/`) — it is the human's to accept, not a footnote.

**All five named constructors get an explicit level** (the design specified two): `quarantined_reader() -> ToolSpawned`; `consolidation() -> Worker`; `interactive() -> Secretary`; `interactive_with() -> Secretary`; `narrowed(tools, level)` takes it explicitly, and its hardcoded `ModelRoute::Worker` at `profile.rs:344` becomes `self.model_route` — a narrowing does not change which model serves the run. Record in `narrowed`'s doc comment that it has **zero production callers**, so this change is currently unobservable.

`MANAGEMENT_TOOLS` in `crates/marlowe-tools/src/builtin.rs`, beside `BUILTIN_TOOLS`:

```rust
/// M3-DESIGN §1.2's master set, as names. **The one definition.** It lists only management
/// tools that EXIST. §1.2 names eight capabilities; six do not exist yet and naming them here
/// would make the master rule vacuously permissive — instance #16 in a constant.
pub const MANAGEMENT_TOOLS: [&str; 2] = ["run", "ask"];
```

**No `escalate` builtin in Session C.** `BUILTIN_TOOLS` is `[&str; 12]` and `builtin.rs:749` asserts that count; `MAX_EXPOSED_TOOLS = 14` and `interactive()` holds 12, so a thirteenth builtin spends one of the exactly two MCP slots ADR-058 was raised to protect. When `escalate` lands it arrives with `[&str; 13]`, the updated assertion, an executor (or `verify_every_exposed_tool_is_runnable` refuses exposure), and either a named MCP-allowance reduction or an ADR-058 amendment — the human's.

---

## §2 — The spawn shape

`crates/marlowe-loop/src/driver.rs` — **§13-GUARDED, HUMAN APPROVAL REQUIRED.**

```rust
pub struct SpawnRequest {
    // task, contract, orphan, share, grant_tokens, tools, tools_declared, reads_untrusted
    /// **Which model serves the child.** `ModelRoute`, not a second enum. A **Target** under
    /// ADR-023: it decides capability and spend, and a downgrade ("make it dumber before an
    /// attack") and an upgrade ("burn the budget") are both attacker-useful. Default `Worker` —
    /// the CHEAP end, so forgetting the field costs nothing.
    pub role: ModelRoute,
    /// §1.1's one question: *can one agent do this alone?* A **Target**: it decides whether the
    /// child may hold the create grant, via `AgentLevel::child_of`.
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

Both read from `args`, not withheld (ADR-057 §5 withholds `share` and `reads_untrusted` because those reach a security control directly; the requirement here is literally *"the spawner names the model"*, and the spawner is a model). The security answer is the Target declaration plus the receipt, below.

`composes_spawn_targets` (`engine.rs:3227`, not 3237) gains two disjuncts:

```rust
fn composes_spawn_targets(req: &SpawnRequest) -> bool {
    !req.tools.is_empty()
        || req.grant_tokens.is_some()
        || !matches!(req.orphan, OrphanPolicy::Terminate)
        || req.role != ModelRoute::Worker
        || req.disposition != Disposition::Work
}
```

Its doc comment records the limitation it inherits rather than presenting the disjuncts as complete: **the function reads the value, not the declaration** — a latched run that types `model_role: worker` is indistinguishable from one that named nothing. That is the existing choice for the other three fields, stated so nobody reads this as more than it is.

**THE RECEIPT CARRIES THE ROLE.** `engine.rs:2755`'s format string becomes:

```rust
"[spawned] role: {role} · {disposition} · tools: {granted_tools} · budget: {} tokens · orphan: {} · returns: {}"
```

Both rendered from the harness's own enums, never from `args`. This is what makes `parse_role`'s total default legitimate instead of unobservable — the design named this mitigation and left it with no site.

---

## §3 — The reader chain, and where it stops in Session C

**`SpawnRequest.role` → `engine.rs:2654` (replacing the hardcoded `ModelRoute::Worker` in the `CapabilityProfile::new` call at `engine.rs:2644`) → the child's `profile.model_route()` → `engine.rs:794` → `CallLimits.route` → `ollama.rs:300`.** Verified end to end: children are driven through the same loop (`self.run(&mut child_run, …)` at `engine.rs:2895`), and `engine.rs:794`'s `run.budget.call_limits(&run.spent)` is the sole call site of `call_limits` in the workspace.

`crates/marlowe-loop/src/budget.rs` — **not guarded**, and the field is **private**:

```rust
pub struct CallLimits { max_output_tokens: u64, route: ModelRoute }
impl CallLimits {
    pub fn max_output_tokens(&self) -> u64 { self.max_output_tokens }
    pub fn route(&self) -> ModelRoute { self.route }
    #[cfg(any(test, feature = "test-util"))]
    pub fn for_test(max_output_tokens: u64, route: ModelRoute) -> Self { Self { max_output_tokens, route } }
}
impl Budget {
    pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens, route }
    }
}
```

Public fields would be a second way to name a route that the run's profile did not declare — the same objection `profile.rs:300-322` makes against holding the granted egress set on the `Run`. The ~8 existing `CallLimits { max_output_tokens: N }` literals in `marlowe-daemon/tests`, `marlowe-loop/tests` and `marlowe-openrouter/examples` move to `for_test`.

`ollama.rs:300` becomes `self.routing.model_for(limits.route()).to_string()`; the same substitution in `llamacpp.rs` and `marlowe-openrouter/src/driver.rs`.

**THE CHAIN STOPS AT `Routing::uniform` IN SESSION C, DELIBERATELY, AND IT IS SAID OUT LOUD.** Another agent is editing `crates/marlowe-daemon/src/daemon.rs` in this session; the design under review prescribed five edits there and its five line numbers were all wrong (actual: 1263, 1338, 1503, 1889, 1976 — plus `crates/marlowe/src/agent.rs:47`, which it missed). Session C makes **no daemon.rs edit**. It ships the three unguarded-by-that-session links, marks `a_child_spawned_at_the_summarizer_role_is_called_on_the_summarizer_model` `#[ignore]` with a header naming exactly what is missing, and records in STATE.md that until the daemon's routing lands the wire test is the only exercise. An ignored test whose header says why is honest; a green one over a half-chain is #16.

**When the daemon edit does land, it is ONE function, not six sites:** `impl Daemon { fn routing(&self) -> Result<Routing, RoutingError> }`, called by all five daemon sites; `agent.rs:47` keeps `uniform` explicitly with a comment saying a one-shot CLI has no role table.

**Two routes wired, the third gated.** `ModelRoute::Summarizer` has zero production producers today and would still have zero after this change — the only construction anywhere under `crates/` is `routing.rs`'s own `model_for` arm and its unit test. So the daemon's configured table ships with `Orchestrator` and `Worker` selected by real code paths and `models().len() == 2` asserted; the third column stays `uniform`-fed until the human answers whether `quarantined_reader()` should carry `ModelRoute::Summarizer` (the obvious producer — condensation is its job — but ADR-008's 2026-08-10 amendment says compression ≠ extraction, and that is exactly the wobble the design correctly flagged and must not resolve).

---

## §4 — Escalation: cut, or built with its carrier

`escalation_target` and `EscalationTarget` as designed have **zero callers**, and their subject is already structurally contained: `engine.rs:2935` replaces a child's `LoopOutcome::Escalated { question }` with a fixed harness string. A worker cannot address anybody today, Marlowe included. Adding a routing function beside that is a second definition of one fact.

**Session C's scope is (a):**

**(a) Cut both.** Record in STATE.md and in `docs/design/SECURITY-AUDIT.md`'s ledger that §3's upward channel is unbuilt and unrouted, citing `engine.rs:2935` as the current containment, and that §3.1's *"an agent that is genuinely stuck must be able to reach a human"* has **no mechanism**. Keep one test, because the absence it defends is real and cheap:

**(b) If the human funds it,** it needs the carrier the design omitted: a new `LoopOutcome::EscalationRaised { severity: Severity, category: Category, artifact: Option<ContentRef> }` — §2.3's typed record, no free text — plus the arm in the `note` match at `engine.rs:2911` that forwards it when the parent is a `Master` or a `TopAgent { manages: true }` and refuses it by name otherwise, with `escalation_target` called *there* and nowhere else. That needs §2.3's `Category` enum, which is a pinned-contract question and unanswered.

---

## §5 — Tests. Every one names its file and the mutation that reddens it.

| # | Test | File | Asserts | Mutation |
|---|---|---|---|---|
| 1 | `the_two_dispositions_do_not_produce_the_same_top_agent` | `crates/marlowe-loop/tests/agent_levels.rs` | `child_of(Secretary, Manage) != child_of(Secretary, Work)`; `child_of(TopAgent{manages:false}, Manage).is_err()` and `(.., Work).is_err()`; `CapabilityProfile::new(set!["run"], .., TopAgent{manages:false}, ..)` is `Err(CreateGrantNotHeldAtThisLevel)` | Replace `parse_disposition(text("disposition"))` with `Disposition::Work` in `from_args` — red. *(The design's version was green under this mutation. This is the fatal fix.)* |
| 2 | `a_master_cannot_hold_a_working_tool` | same | For **each** of `bash, read, write, edit, glob, grep, web, recall, remember, use` enumerated literally: `new(set![t], DenyAll, Unattended, Worker, Master, false, false)` is `Err(MasterHoldsWorkingTool{tool:t})`, and the same set at `Worker` is `Ok`. Plus the #17 control: the companion `Budget`'s six dimensions are each ≥ 1 | Delete the `Master` arm — ten reds. Or express the rule as `Budget{tool_calls:0,..}` — the dimension assertion reds |
| 3 | `management_tools_and_working_tools_are_disjoint_and_the_list_has_not_shrunk` | same | `MANAGEMENT_TOOLS == ["run","ask"]` written **literally in the test**; `MANAGEMENT_TOOLS ∩ WORKING_TOOLS == ∅` with the second list also literal; every name resolves in `ToolRegistry::builtin()` | Add `"edit"` — disjointness reds. **Remove `"ask"`** — the literal reds. #19: test 2's input *is* `MANAGEMENT_TOOLS`, so it cannot see the list shrink |
| 4 | `the_level_table_is_total_and_never_produces_a_tool_spawned` | same | The whole `child_of` table, all eleven `(level, disposition)` pairs, and: no input yields `ToolSpawned` | Add `(Master, Manage) => Ok(Master)` — the tree becomes unbounded, red |
| 5 | `every_named_profile_declares_its_level` | same | A wildcard-free `match` over `AgentLevel` mapping each level to the constructor(s) producing it; `quarantined_reader()==ToolSpawned`, `consolidation()==Worker`, `interactive()==Secretary` | A sixth `AgentLevel` variant fails to **compile**. #19-safe: coverage cannot silently shrink |
| 6 | `a_profile_that_may_create_agents_is_exactly_one_that_holds_run` | same | Over all five levels: `p.may_create_agents() == p.exposed_tools().contains("run")` | Reintroduce a `level.may_hold_create_grant() &&` conjunct at a level that can hold `run` — red |
| 7 | `a_level_cannot_be_widened_by_deserialization` | same | `from_str::<CapabilityProfile>` with `"level":"master"` + `"exposed_tools":["edit"]` errors naming the management rule; `level` **absent** errors naming the missing field | Add `#[serde(default)]` to `Raw.level` — the absent case greens. Or replace the hand-written `Deserialize` with a derive — #12 |
| 8 | `no_production_budget_sets_a_dimension_to_zero` | same | Greps `crates/*/src/` for `depth: 0`, `subagents: 0`, `tool_calls: 0`; asserts **0** hits; **prints the count** | Add `Budget{depth:0,..}` anywhere in production — red. #17, with the source tree as input rather than a maintained list |
| 9 | `a_run_without_the_create_grant_cannot_spawn` | `crates/marlowe-loop/tests/spawn_and_budget.rs` | Drive a real `ModelStep::Spawn` on a run whose set lacks `run`. Refused by a message naming the create grant; **`EventKind::RunSpawned` appears 0 times**; the parent's window holds the refusal. **Fails at HEAD** — `ollama.rs:1045` maps `run` to `Spawn` with no exposure check and `Engine::spawn` adds none. Cite SECURITY-AUDIT **H2**; do not file as new | Delete the `may_create_agents()` check at the top of `Engine::spawn`. Assert on the **count**, not the string — a message-only test greens if the refusal is emitted *and* the child spawns |
| 10 | `a_spawn_receipt_names_the_role_that_was_actually_granted` | same | Emit `model_role: "conductor"` (unrecognised); assert the parent's window block contains `role: worker` and `work` | Drop the role from `engine.rs:2755`'s format string — red. This is what makes `parse_role`'s default observable |
| 11 | `a_latched_run_cannot_choose_a_childs_model_or_disposition` | `crates/marlowe-loop/tests/adr023_spawn_targets.rs` | Unit: `composes_spawn_targets` false at every default, true when **only** `role` moves, true when **only** `disposition` moves. Loop: latch to `UntrustedContent`, emit `model_role: orchestrator`, assert refused and 0 `RunSpawned` | Remove either disjunct from `engine.rs:3227` — the corresponding unit case reads `false` and the loop half spawns |
| 12 | `a_child_spawned_at_the_summarizer_role_is_called_on_the_summarizer_model` | `crates/marlowe-provider/tests/model_role_reaches_the_wire.rs` — **`#[ignore]` in C, header names the missing daemon link** | Bytes, not fields. `Routing::new("role-orch","role-work","role-summ")`; child at `role: Summarizer`; `request_body(..)["model"] == "role-summ"` for the child's call, `"role-orch"` for the parent's. **Prints both strings** | Restore the `ModelRoute::Orchestrator` hardcode at `ollama.rs:300` — both read `role-orch`. Or drop `req.role` in `Engine::spawn` — the child reads `role-work`. **Never write** `assert_eq!(req.role, Summarizer)`: green under both |
| 13 | `the_daemon_builds_its_routing_in_exactly_one_place` | `crates/marlowe-daemon/tests/role_routing.rs` — deferred with the daemon edit | Greps `crates/marlowe-daemon/src/*.rs` for `Routing::uniform(`; asserts **0** hits; **prints the count**. Then `Daemon::routing()` from a two-tag config gives `models().len() == 2` and two distinct strings | Restore any one `uniform` — count reads 1, red. Six edit sites become one, and the guard's input is the source tree |
| 14 | `no_escalation_tool_has_a_recipient_parameter` | `crates/marlowe-tools/tests/escalation_manifest.rs` | For `ask` in `ToolRegistry::builtin()` (registry, not a literal): no parameter is `ArgumentRole::Target`, no parameter name in `["to","recipient","agent","run","addressee","target"]`. Header records that the **primary** containment is `engine.rs:2935` swallowing a child's `Escalated`, and this is belt-and-braces | Add `documented("recipient", ArgumentRole::Target, Text, …)` to `ask` — red |
| 15 | `terminate_appears_in_no_agents_request_body_at_any_level` | `crates/marlowe-daemon/tests/terminate_is_invisible.rs` — **daemon, not provider** | Builds the body through the **daemon's own** assembly path (the `Assembler` + stable-tier construction `ask_streaming_with` uses), per level, via a wildcard-free `match`. `"TERMINATE"` occurs **0** times; no exposed set contains it. Prints the per-level count | Put `TERMINATE` in `persona/v1.md` — red. A test-local `ContextView` would print 0 here and that is why the subject moved. **Paired, non-optional:** a `--dev` outbound dump from the shipped binary, grepped, saved to `runs/<session>/` — §3.4's "where the bytes go", and the M2 C2e lesson that a test on the source cannot see a stale deployment |
| 16 | `the_role_table_leaves_room_for_the_embedder` | `crates/marlowe-daemon/tests/role_residency.rs`, `#[ignore]` | **Asserts the provider string, not free VRAM.** Start the daemon with the configured table, then run the shipped binary: `target/release/marlowe.exe --eval-adapter --profile-root <tmp> --embedder-model models/jina-embeddings-v2-small-en --reranking off < /dev/null`; assert stdout contains `CUDAExecutionProvider`. `/api/ps` totals and free MiB are **printed as diagnostics, never asserted** | Point a second `ModelRoute` at `marlowe-dawn:9b-super`. Header states the desktop's ~5,086 MiB is part of the system under measurement, so a failure means "not on this machine, in this state" |
| 17 | `call_limits_has_one_production_constructor` | `crates/marlowe-loop/tests/call_limits_one_constructor.rs` | Greps `crates/*/src/` for `CallLimits {`; asserts exactly one hit, in `budget.rs`; prints it | Build a `CallLimits` literal in `ollama.rs` — count 2, red. #12's family closed at a struct literal |

---

## §6 — Contract impact

**1. CONTRACTS §5 — `CapabilityProfile` gains a seventh field.** `level: AgentLevel`, pinned **by membership** (five variants, one of them carrying a `bool`), alongside the three new load-time errors stated in the same register as the existing `reads_untrusted && !exposed_tools.is_empty()` sentence: `ToolSpawned ⟹ empty`; `Master ⟹ ⊆ MANAGEMENT_TOOLS`; `contains("run") ⟹ level.may_hold_create_grant()`. Note while there: §5's `exposed_tools: Vec<ToolId> // INVARIANT: len() <= 12` is **already stale** — `MAX_EXPOSED_TOOLS = 14` (ADR-058) and §5 shows every field `pub` where the code has them private. Fix both in the same edit or the pin is decorative.

**2. CONTRACTS §5 — pin `SpawnRequest`'s ten-field shape for the first time.** The measured fact stands: `grep -n SpawnRequest docs/design/CONTRACTS.md` returns exactly one hit, line 941, pinning only `fn spawn(&self, req: SpawnRequest) -> RunId`; `LoopOutcome` is not in CONTRACTS at all. Pinning now is what makes Session G a window rather than a contract change, and it obliges four things:

  (a) Every field with its type **and** its declared/derived/withheld status — ADR-057 §5's line about `share` and `reads_untrusted` currently lives only in a doc comment.
  (b) **Which enums are pinned by MEMBERSHIP and which by NAME ONLY.** `AgentLevel`, `Disposition`, `OrphanPolicy`, `BudgetShare`, `RunStatus`, `Channel`: membership — a variant needs the human (M3-D1's precedent). **`ModelRoute`: name only, and that sentence is the entire mechanism by which the fourth role arrives without an ADR.** Without it written down, a later session correctly concludes it needs one and C's reason for existing evaporates.
  (c) A statement that `Routing::model_for` matches `ModelRoute` **exhaustively, no wildcard** — already true at `routing.rs:65-71`, so this is recording, not building. It is what stops a fourth role arriving half-wired.
  (d) **A reachability sentence, and it must be honest about where the chain stops.** §12.1 pins `ingest_external` and says it has no production caller; §5's `role` pin says: the chain is complete from `SpawnRequest.role` through `engine.rs:2644` → `CallLimits` → `ollama.rs:300`, **and terminates in `Routing::uniform` until the daemon's `routing()` lands**, so `Orchestrator` and `Worker` resolve to the same model in the shipped binary today. A pin that claims a complete chain it does not have is worse than §12.1's, which was only honest because it said so.

**3. Unchanged.** `RunControl`, `Run`, and CONTRACTS §12's six loop-boundary types. `CallLimits` is pinned nowhere and needs no entry.

**4. A documentation cost that is not a contract cost.** `AGENT-DIRECTORY.md` §2 labels the roles secretary / agent / extractor; `ModelRoute` says Orchestrator / Worker / Summarizer. Record the mapping as a **table in CONTRACTS beside the enum**, so Session G's window labels are a rendering of the enum rather than a second enum. Flag, do not resolve, the wobble the design correctly surfaced: ADR-008's 2026-08-10 amendment says compression ≠ extraction while §2 calls the 2b model the "extractor".

---

## §7 — Guarded files, and what a human must approve

**Both §13-guarded files are edited.** `crates/marlowe-loop/src/profile.rs` (M2 A) gains `AgentLevel`, `Disposition`, `LevelRefusal`, a seventh field, three `ProfileError` variants, a seventh argument to `new`, the `Raw` field, and a level argument to `narrowed`. `crates/marlowe-loop/src/driver.rs` (M3-D3) gains `role` and `disposition` on `SpawnRequest` plus two total parsers. `crates/marlowe-permission/src/adjudicate.rs` is **not** touched — `blocks_composed_targets` is unchanged and `composes_spawn_targets` lives in unguarded `engine.rs`. Neither `memory.rs`, `steer.rs`, `mcp.rs`, `pin.rs`, `trust.rs`, the journal nor `persona/` is touched. No new `PROTECTED` row is owed, so no new §13 table row either.

**Open, and each is the human's:**

1. **The fourth `ModelRoute` variant's name** — not invented here. And under it: **ADR-008's 2026-08-10 amendment already asked for a fourth role (compression) and it never landed.** Whether the human's fourth role *is* that one decides four variants or five, and four `Routing` columns or five. The amendment calls compression the enforcement point for brief §10 and, post-ADR-037 §6, the security interface — not a naming detail.
2. **Is `role` a Target under ADR-023?** This design answers **yes** with one disjunct at an existing latch — cheap and reversible, but it narrows what a latched run may do, so it is accepted, not taken. AGENT-DIRECTORY §3 item 4 asks for it answered explicitly rather than by omission.
3. **Both pinned-contract acts** — the seventh field, and `SpawnRequest`'s first pin. M3-D1's precedent is escalate, not take.
4. **Breaking pre-Session-C checkpoints.** Accept the named serde failure on resume, or fund a one-shot migration. `#[serde(default)]` is not on the table: it would silently restore a master holding working tools.
5. **Does §1.2's structural rule extend to level 1?** `interactive()` holds `bash`, `edit`, `write` and `web`, and this design makes it a `Secretary` with **no** tool restriction — a NAMED arm in `new`'s match, with the question in the comment, not a `_`. §1's table says "full conversational set" and §2's liaison pattern says Marlowe should not do the work. Unanswered by M3-DESIGN, and answering it by wildcard is how a decision gets made by nobody.
6. **Should `quarantined_reader()` carry `ModelRoute::Summarizer`?** It is the only credible production producer for the third route, and it is exactly the compression-vs-extraction question in (1). Until answered, `Summarizer` ships unselected and the table has two live columns.
7. **`escalate` as a thirteenth builtin** — costs a red `assert_eq!(BUILTIN_TOOLS.len(), 12)` and one of ADR-058's two MCP slots. Deferred out of Session C.
8. **AGENT-DIRECTORY §2's arithmetic is contradicted by measurement, and the role DEFAULTS depend on it.** §2 says the three models take "10.0 GB of the card's 16, leaving headroom for the KV cache, the embedder and the reranker." Measured today via `/api/ps`: 5,086 MiB held by the desktop before anything loaded; final state 14,993 MiB used, **1,053 MiB free**. ADR-044 resolves the embedder's provider against free VRAM **at load**, so shipping a three-model table is what puts the embedder on CPU with a correct-looking log line. Which models go in the default table is a VRAM decision.
9. **SECURITY-AUDIT §8 / ROADMAP M3-C item (2): "the latch belongs on the session, not the Run."** Untouched here and still unrecorded in `DECISIONS.md` seventeen days after it was answered. Adjacent — `Run::root` is rebuilt every turn at `UserAsserted`, so the `role` refusal this design adds is per-turn — but separate, and the human's.

---

## §8 — Standing risks, restated where the design understated them

- **Instance #16 is still this session's likeliest failure, now in three places rather than one:** `model_route()` (zero readers, closed by `engine.rs:794`), `Routing::new` (zero production callers, deferred with the daemon edit and marked `#[ignore]`), and `Summarizer` (zero producers, so the third column ships unselected). Test 12 asserts `request_body["model"]` — the bytes.
- **Test 12 is in-process, and in-process is the pipe-tested-guard family** (`persona_emission.rs`, M2 C2d/C2e). Session C also owns the model-driver seam (`Daemon::turn` builds its `Box<dyn ModelDriver>` inline, no seam), so the honest close is a `--dev` outbound dump from the shipped binary showing the child's model name. Say this in STATE.md rather than discovering it.
- **A saturated floor, ADR-036 §5.** `composes_spawn_targets` refuses a role choice under a latched floor, but §2.1 makes the Secretary a run that may never latch and `Run::root` is rebuilt per turn, so the refusal is per-turn. Inside a research subtree where every source is `UntrustedContent`, every spawn is equally tainted and the floor discriminates nothing; the surviving question is *who asserted the role*, and this design does not answer it. Bounded — a closed enum of local models, so the blast radius is spend and capability, not egress — but the mechanism is not doing work there and must not be claimed to be.
- **Shipping tiered routing changes the VRAM picture and every prior measurement is scoped to a one-model machine.** Today every production site is `uniform`, so one model loads. Re-measure retrieval timings and the embedder-provider line after the daemon edit; do not cite.
- **`OLLAMA_NUM_PARALLEL=1` means the ladder buys no concurrency**, and `Engine::spawn` drives children **synchronously** (`self.run(&mut child_run, …)` at `engine.rs:2895`), so the tree is depth-first and blocking regardless. A roster showing three agents "running" tells the truth about intent and a lie about execution — AGENT-DIRECTORY §3 item 7. Untouched here; the `role` field is what first makes it visible to a user.
- **Admission control (roadmap item 5) consumes this shape and is not designed here.** Its per-role queue keys on `ModelRoute` — one more argument for the closed enum — and `RunStatus::Queued`'s conflation of *constructed* with *blocked behind busy workers* is a separate decision (HEAD 186b5d5 pinned the state; what it means is open).
- **Nothing here wires `ingest`.** `grep -rn "ingest_external(" --include=*.rs crates/*/src/` returns exactly two hits — `marlowe-daemon/src/memory.rs:542` and `marlowe-loop/src/driver.rs:573`, both definitions. No producer for `Channel::Agent` is added; that consumer is Session D's. Layer 3 stays unreachable in the shipped daemon, which is correct per ADR-062.

---

# CRITIQUE (sound-with-fixes)

**Fatal:** The gate cannot refuse in the shipped product and cannot be recorded when it does. `/api/ps` only lists RESIDENT models, so the one branch that refuses — `needs = size_bytes` when `resident == false` — reads a field its named producer cannot supply; in production it is `0`, `needs + headroom > free` collapses to `headroom > free`, and the model's footprint never enters the decision. The design's test hides this by hand-building a non-resident `Residency` carrying a `size_bytes` obtainable only from `/api/ps` while resident. Compounding it: no production `CapacityHost` impl is named and the crate graph forbids both obvious homes (`marlowe-provider` cannot see `marlowe_memory::…::vram::free_bytes`; `marlowe-loop` can see neither), so the daemon would build `Ports { capacity: None }` and every verdict would be `Unmeasured`; and `Engine::spawn_refused` (engine.rs:3112) appends nothing to the journal, so `refused_no_room` and `refused_cpu_split` are unreachable on the `RunSpawned` row the design says carries them — the egress-style measurement the design leans on is impossible for the exact branch it exists to create.

## Strengthened

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

# CRITIQUE (broken)

**Fatal:** The §11 acceptance row it is built to satisfy cannot be measured the way it proposes: `terminate` already appears in every agent's `request_body` from two production sources — the `run` tool's `orphan_policy` description (`crates/marlowe-tools/src/builtin.rs:695`) and the spawn receipt (`crates/marlowe-loop/src/engine.rs:2731`) — so `terminate_appears_in_no_agents_request_body` is red on a correct build, and the only cheap repair is to weaken the search until the zero stops being evidence. That is instance #15 committed against the acceptance table itself.

## Strengthened

## Escalation routes on `Run::parent` and one inherited bit; TERMINATE is a variant with a canary

The bones of the reviewed design are right and are kept: capabilities withheld structurally rather than by a counter, closed enums, validating constructors, `EscalationRoute` with no arm naming the secretary, and no field on the view type for the escape hatch. What follows fixes the twenty-one places where a claim did not survive the source.

---

### 1. One inherited bit, not a five-value level

`AgentLevel` is dropped. Escalation routing reads exactly two things: *may this run raise*, and *who is above it*. The second is `Run::parent`, which already has one definition — do not build a second. The first is the one fact the tree cannot recompute, so it is inherited the way `trust_floor` is.

```rust
// crates/marlowe-loop/src/run.rs — NOT §13-guarded

/// Where an escalation raised by THIS run goes. **Derived at construction from the parent's own
/// value and from the profile.** No setter, no `SpawnRequest` field, no `From<&str>`.
///
/// It deliberately encodes only what routing reads. M3-DESIGN §1's five levels are a description
/// of the tree; `Run::parent` already answers "where am I", and a second encoding of it diverges
/// the moment `adopted_by` or `detached` runs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RaisesTo {
    /// The conversational run. Nobody above it. §3.1.
    Nobody,
    /// This run was created by the conversational run, so it is a top-agent and its escalation
    /// reaches the USER — and §3.2's recipient is the user, never Marlowe.
    User,
    /// This run's escalation reaches its parent and only its parent.
    Parent,
    /// **Structural.** A run whose profile reads untrusted content may not raise at all: its
    /// window holds raw attacker bytes (ADR-041), so its question is a statement about the model
    /// and not about the page. `CapabilityProfile::new` already makes `reads_untrusted` imply an
    /// empty tool set at load time, so this is enforced by an invariant that exists.
    Refused,
}
```

`Run` gains `raises_to: RaisesTo`, private, with `pub fn raises_to(&self) -> RaisesTo`. The three constructors, all in `run.rs`:

```rust
// Run::root  — daemon.rs:2609 and control.rs's test helper
raises_to: RaisesTo::Nobody,

// Run::child — engine.rs:2146 (condense_batch) and engine.rs:2666 (Engine::spawn)
raises_to: if profile.reads_untrusted() {
        RaisesTo::Refused
    } else {
        match parent.raises_to {
            RaisesTo::Nobody  => RaisesTo::User,
            RaisesTo::Refused => RaisesTo::Refused,
            _                 => RaisesTo::Parent,
        }
    },

// Run::restored — durable.rs:153, one more parameter, no default
raises_to,
```

`Run::child` reads it off the `profile` argument it already takes, so **`condense_batch`'s quarantined reader classifies correctly without `condense_batch` changing at all** — which is the defect that killed the reviewed version, where the reader came out `Worker` and got a live route to its parent.

`may_hold_create_grant` is deleted. Its refusal is unreachable behind the narrowing check at `engine.rs:2631-2640`; the invariant is asserted instead, in a place where it can fail (test 2 below).

**Durability.** `Checkpoint` (`durable.rs:87-108`) gains `pub raises_to: RaisesTo` with **no `#[serde(default)]`**, and `CHECKPOINT_VERSION` is bumped. A checkpoint from the previous version decodes to `Err`, surfaced as the existing "a version this build will not read" `ResumeError`.

---

### 2. Routing, with the detached case audible

```rust
// crates/marlowe-loop/src/escalation.rs — NEW, not guarded

/// **There is no arm that returns the conversational run, and that absence IS §3.2.**
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EscalationRoute {
    Parent(RunId),
    User,
    /// Nobody above, or a run that may not raise. Carries WHY, because a channel that goes
    /// quiet is not a channel that is closed.
    NotRaisable(NotRaisableReason),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NotRaisableReason {
    /// The conversational run: §3.1, nobody above.
    Root,
    /// A quarantined reader.
    ReadsUntrusted,
    /// `OrphanPolicy::Detach` cut the parent link (`durable.rs:373`). The raiser is told, and
    /// the journal records it. This was the reviewed design's silent hole.
    Detached,
}

pub fn escalation_route(run: &Run) -> EscalationRoute {
    match (run.raises_to(), run.parent) {
        (RaisesTo::Refused, _)      => EscalationRoute::NotRaisable(NotRaisableReason::ReadsUntrusted),
        (RaisesTo::Nobody, _)       => EscalationRoute::NotRaisable(NotRaisableReason::Root),
        (RaisesTo::User, _)         => EscalationRoute::User,
        (RaisesTo::Parent, Some(p)) => EscalationRoute::Parent(p),
        (RaisesTo::Parent, None)    => EscalationRoute::NotRaisable(NotRaisableReason::Detached),
    }
}
```

Every `NotRaisable` writes `EventKind::RunFailed` with the reason and pushes a harness-authored constant into the raiser's own window, on the `UNDESCRIBED_SOURCE` / `QuarantineRefusal` precedent — one shared constant, not a literal at each end.

`adopted_by` needs no change: `RaisesTo` encodes no depth, so an adopted child still correctly raises to whoever its parent now is.

---

### 3. The port — the seam the reviewed design left open

`marlowe-loop` cannot see `marlowe-daemon`, so `Ports` is how anything leaves the loop. Both changes are in `crates/marlowe-loop/src/driver.rs`, **§13-GUARDED — A HUMAN MUST APPROVE THIS, and it should arrive with a `DECISIONS.md` entry.**

```rust
// crates/marlowe-loop/src/driver.rs — §13-GUARDED

pub enum ModelStep {
    Say(String),
    ToolCall { calls: Vec<ToolInvocation> },
    MemoryWrite(ClaimRequest),
    Spawn(SpawnRequest),
    /// **Unchanged and unrepurposed.** This is `ask` — the conversational run putting a question
    /// to the user. `Engine` refuses it from any run whose `raises_to` is not `Nobody`.
    Ask(String),
    /// §2.3's typed upward record. No free paragraph.
    Escalate(EscalationRequest),
}

/// What a model may supply. **The recipient is not here** — it is `escalation_route`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EscalationRequest {
    pub severity: EscalationSeverity,
    pub category: EscalationCategory,
    /// A hash the harness turns into a path. **Not `ContentRef`** — see §6.
    pub artifact: Option<ArtifactHandle>,
    /// §9.1 A8's middle arm only. `EscalationArm::Typed` refuses `Some` by name.
    pub sentence: Option<ValidatedSentence>,
    pub forwarding: Option<EscalationId>,
}

/// How an escalation leaves the loop. The `NoControl` precedent (`control.rs:113-131`).
pub trait EscalationPort {
    fn raise(&mut self, run: RunId, route: EscalationRoute, req: EscalationRequest)
        -> Result<EscalationId, EscalationRefused>;
}

pub struct NoEscalation;
impl EscalationPort for NoEscalation {
    fn raise(&mut self, _: RunId, _: EscalationRoute, _: EscalationRequest)
        -> Result<EscalationId, EscalationRefused> { Err(EscalationRefused::NoDesk) }
}
```

`Ports` (`engine.rs:217-227`) gains `pub escalations: &'a mut dyn EscalationPort`. The quarantined-reader child `Ports` at `engine.rs:2880-2891` passes `&mut NoEscalation` — structurally, beside the existing `memory: None`, and belt-and-braces with `RaisesTo::Refused`.

**Lifecycle.** `PauseReason` (`run.rs:195`, harness enum, unguarded) gains `AwaitingEscalation { id: EscalationId }`. `LoopOutcome` gains `Raised(EscalationId)` — a **new** variant; `Escalated { question }` is untouched, so `ask` keeps its text at `daemon.rs:2899` and the child-return arm at `engine.rs:2936` keeps its wording. A new arm returns a harness constant for `Raised`.

---

### 4. The desk, journal-backed

```rust
// crates/marlowe-daemon/src/escalation.rs — NEW

pub struct EscalationDesk { pending: BTreeMap<EscalationId, Pending> }  // HashMap is banned
struct Pending { escalation: Escalation, at: Recipient, opened_ms: i64 }

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Recipient { Run(RunId), User }

impl EscalationDesk {
    /// **Rebuilt from the journal at boot**, so a pending escalation survives a restart in the
    /// milestone whose subject is durable runs. Every `Pending` is written through the existing
    /// `Recorder` path — one definition of the pending set, not an in-memory second one.
    pub fn from_journal(j: &dyn JournalRead) -> Self;

    /// One hop. `by` MUST be the run this escalation is currently addressed to.
    ///
    /// ADR-036 §5's authority rule at a saturated floor: inside an escalation every value is
    /// `UntrustedContent`, so ADR-023's floor reads "blocked" for every pending id and
    /// discriminates none. What survives saturation is who addressed it here.
    pub fn advance(&mut self, id: EscalationId, by: RunId, route: EscalationRoute)
        -> Result<Recipient, AdvanceError>;

    /// §3.2, enforced by the SIGNATURE. No `body` parameter, no `&Escalation` return, and no
    /// method on this type hands text to a loop.
    pub fn secretary_notice(&self, id: EscalationId) -> Option<Notice>;

    pub fn resolve(&mut self, id: EscalationId, choice: Choice) -> Result<Resolution, ResolveError>;
}
```

The window rides the **ADR-055 control-plane listener** (`marlowe-daemon/src/{watch,watch_client}.rs`, a second listener on its own published port), never the conversation socket — so `CONTRACTS.md` §13's pinned `TurnEvent` changes nothing and the body never touches Marlowe's `Ports.sink` or `SessionState`.

`Notice` gains one variant, no `String`, per ADR-030 §5:

```rust
EscalationRaised { severity: EscalationSeverity, by: Echo }
```

`by` is `Echo::new(format!("{} {}", level_word, marlowe_loop::run::sayable(&id.to_string())))`, composed by the producer. **`sayable` is the single definition of how a run is printed** (`run.rs:100-111`) — no `AgentLabel`, no hex prefix, zero model bytes.

---

### 5. §3.3, in Marlowe's stable tier and nobody else's

`SessionState::governance` is copied into every child at `engine.rs:2206-2208` and `engine.rs:2798-2800`. So the escalation explanation does **not** go there. `SessionState` gains:

```rust
/// Stable-tier facts for the conversational run ALONE. Rebuilt into the stable tier by
/// `Assembler::assemble` beside `governance`, and copied by NEITHER child loop — §3.3's two
/// sentences describe the containment architecture, and an agent's window is the last place
/// that belongs.
pub secretary_notes: Vec<GovernanceConstraint>,
```

Asserted once at session construction in `daemon.rs`, unconditionally, before any escalation exists — so a compaction between the event and the assertion cannot open the window. Read by `Assembler::assemble` (`context.rs:635-645`), into the stable tier, into the system message, into `request_body`.

---

### 6. The record, and the artifact that is not `ContentRef`

```rust
// crates/marlowe-contract/src/escalation.rs — NEW

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Escalation {
    pub id: EscalationId,
    pub raised_by: RunId,
    pub severity: EscalationSeverity,
    pub category: EscalationCategory,
    pub artifact: Option<ArtifactHandle>,
    /// The approving chain, newest last. Appended by `EscalationDesk::advance`, never by a model.
    pub lineage: Vec<RunId>,
    pub sentence: Option<ValidatedSentence>,
}

/// A journal-addressed artifact. **Hash only.** CONTRACTS §2's `ContentRef` carries
/// `summary: ResultSummary` — a place for attacker-shaped prose to cross upward inside a record
/// §2 calls typed, without anyone dereferencing anything. `ContentRef` also does not exist as a
/// Rust type: `grep -rn "ContentRef" --include=*.rs crates/` returns doc comments only.
/// The surface composes the path the user opens; the record carries no text.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArtifactHandle(pub ContentHash);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationSeverity { Advisory, Blocking, Critical }   // renamed: `Urgency::Advisory`
                                                               // already exists, driver.rs:658

/// Closed. ADR-030 §5's growth rule.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationCategory {
    BlockedByPermission, ScopeContradiction, ExternalSystemRefused,
    ConflictingInstructions, SuspectedInjection, IrreversibleActionRequired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ValidatedSentence(String);

impl ValidatedSentence {
    pub const MAX_CHARS: usize = 200;
    pub fn normalise(raw: &str) -> Result<Self, TextRejected> {
        let one = crate::text::sanitize_line(raw.trim());
        if one.chars().count() > Self::MAX_CHARS { return Err(TextRejected::TooLong); }
        if !one.chars().all(crate::text::is_renderable) { return Err(TextRejected::Unrenderable); }
        Ok(Self(one.into_owned()))
    }
    pub fn as_str(&self) -> &str { &self.0 }
}

/// **Hand-written, on `GovernanceConstraint`'s model (`marlowe-loop/src/context.rs:403-425`).**
/// `#[derive(Deserialize)]` would be a field-wise way in past `normalise` — a checkpoint, an MCP
/// descriptor and a spawn request are all ways in (#12).
impl<'de> Deserialize<'de> for ValidatedSentence { /* String::deserialize → normalise → de::Error */ }

pub struct OptionLabel(String);   // same discipline, MAX_CHARS = 72, same hand-written Deserialize
```

`ArgumentRole`'s own definition (`marlowe-tools/src/manifest.rs:85`: *"Tool selection, recipient, path, host, amount, **identifier**"*) already settles that a model-chosen `ArtifactHandle` is a **Target**. It is annotated as one in `escalate`'s manifest and adjudicated; it is not referred upward as undecided.

---

### 7. The window, and TERMINATE

`crates/marlowe-view` today has an **empty `[dependencies]`** and the package description *"Shapes only"*. Adding `marlowe-contract` to it is a real change of stance and gets a `DECISIONS.md` entry saying so, with the reason: the alternative is a second definition of `is_renderable` (`marlowe-contract/src/text.rs:78`) inside the shapes crate, and two answers to *"which characters may reach a terminal"* on the surface where SECURITY-AUDIT B1 and B2 live is the worse trade. It is not claimed as an existing precedent, because it is not one.

```rust
// crates/marlowe-view/src/escalation.rs — NEW

/// **There is no field for TERMINATE, and that is §3.4's structural invisibility.**
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EscalationView {
    pub raised_by: Echo,
    pub severity: EscalationSeverity,
    pub category: EscalationCategory,
    options: Vec<AgentOption>,        // private; bounded at construction
    pub cost: TerminationCost,
    pub evidence: SourceEvidence,     // renamed: `Provenance` is taken twice already
    pub artifact: Option<ArtifactPath>,
}

impl EscalationView {
    pub const MAX_AGENT_OPTIONS: usize = 4;
    /// Refused, never truncated. A ceiling on a Vec at construction — deliberately NOT a
    /// `Budget` dimension, because `Budget::exhausted` compares `spent >= budget` (#17).
    pub fn new(/* … */) -> Result<Self, TooManyOptions>;
    pub fn options(&self) -> &[AgentOption];
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Choice { Agent(u8), Terminate }

/// What the human reads.
pub const TERMINATE_LABEL: &str = "terminate this agent and the runs under it";

/// **What the TEST reads, and it is deliberately not the word `terminate`.**
/// `terminate` occurs in `run`'s `orphan_policy` description (`marlowe-tools/src/builtin.rs:695`)
/// and in the spawn receipt (`marlowe-loop/src/engine.rs:2731`), so a zero over that substring is
/// RED on a correct build — and the cheap repair is to weaken the search until the zero means
/// nothing. This token exists nowhere else in the workspace and in no type a `ModelDriver` can
/// reach. It is the escape hatch's wire identity in `Choice::Terminate`'s serialization.
pub const TERMINATE_CANARY: &str = "harness-escape-hatch-6b1f";

/// §3.5, derived from the journal. The model contributes nothing and is never asked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerminationCost {
    pub runs: u32,
    pub age_ms: u64,
    pub spend_micros_usd: u64,
    pub artifacts: u32,
    pub irreversible: Vec<IrreversibleAct>,
    /// **What TERMINATE will NOT stop.** `Control::cancel` is per-run — `control.rs:337` is
    /// `cancelling_one_run_does_not_cancel_its_sibling` — and CONTRACTS §5 pins "Children outlive
    /// parents", with `settle_orphan` (`durable.rs:373`) making `Detach` survive. §3.5 is the
    /// section that says TERMINATE must tell the truth about what it cannot undo; the reviewed
    /// design's label promised "everything under it" with no way to express the shortfall.
    pub survivors: Vec<Survivor>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Survivor { pub run: Echo, pub policy: OrphanPolicyLabel }

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IrreversibleAct {
    FilesWritten { count: u32, within: PathLabel },
    CommitsPushed { count: u32 },
    MessagesSent { medium: Medium, count: u32 },
    ProcessesRun { count: u32, reached_network: bool },
}

/// §3.6. **Total** — `NoExternalSources` is a claim a producer makes on purpose, exactly as
/// `Novelty::Routine` is (`marlowe-view/src/approval.rs`), not an `Option` a producer can omit
/// while nothing reports the omission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SourceEvidence {
    NoExternalSources,
    External { sources: u32, most_recent: SourceTrace },
}

/// `host` is `marlowe_permission::egress::Host` — the host the EGRESS layer resolved, never a
/// string the agent wrote.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceTrace { pub host: HostLabel, pub fetched_ms_ago: u64 }
```

**Layout, not assertion.** `crates/marlowe-surface/src/escalation.rs::layout` computes the terminate row **first** from the frame height and gives the option list what remains, scrolling within it. B3's defect is a modal sized from unwrapped content; reserving the row makes the escape hatch un-displaceable by growth in `IrreversibleAct` or `survivors`.

---

### 8. Tests — each names its file and the mutation that reddens it

1. **`terminate_never_reaches_a_model`** — `crates/marlowe-provider/tests/terminate_is_absent_from_the_request_body.rs`. 6 profiles × 3 adapters = 18 bodies. Prints `canary: 0/18 · label: 0/18 · persona present 18/18 · leak control found canary: yes`. Four assertions: `TERMINATE_CANARY` and `TERMINATE_LABEL` occur zero times; the persona marker is present 18/18 (positive control, so an empty body cannot report a clean zero); `bodies.len() == 18` and each has non-empty `messages` (vacuity); and a **leak control** — a nineteenth body built with an `EscalationView` deliberately serialized into the brief, asserted to CONTAIN the canary, so the search itself is proven. *Mutation:* put `TERMINATE_CANARY` in `governance_prompt()` → red. *Mutation on the leak control:* break the substring scan → the nineteenth assertion fails before any zero is reported.
2. **`no_reachable_spawn_gives_a_leaf_the_create_grant`** — `crates/marlowe-loop/tests/escalation_routing.rs`. Exhaustive over `(parent RaisesTo × tools containing/omitting "run")`, asserting no reachable pair produces a run with `RaisesTo::Refused` holding `run`, and that the narrowing check at `engine.rs:2631-2640` is what makes it so. *Mutation:* delete the narrowing check → red.
3. **`a_quarantined_reader_cannot_raise_and_the_refusal_is_audible`** — same file. Drives a real `condense_batch` read, has the reader emit `ModelStep::Escalate`, asserts `escalation_route` is `NotRaisable(ReadsUntrusted)`, that the desk received nothing, and that the reader's own window gained the harness constant. *Mutation:* derive the refusal from `req.tools` instead of `profile.reads_untrusted()` → the reader classifies `Parent` → red. **This is the assertion the reviewed design could not make**, because its `ToolSpawned` arm was unreachable.
4. **`a_worker_escalation_stops_at_its_master_and_never_reaches_the_root`** — same file. Real four-level tree through `Engine::spawn`; asserts the desk's delivered `Recipient` is the master's `RunId`, `lineage == [worker]` then `[worker, master]`, and the root's `SessionState` gained zero blocks. **Plus a negative control**: the same tree re-run through a `RouteOverride` double returning `Recipient::Run(root_id)`, asserting the root's window DOES gain the block — without which the zero-blocks assertion is green on today's HEAD, where `engine.rs:2936` already swallows a child's escalation.
5. **`an_agent_cannot_reach_the_user_through_the_secretarys_door`** — same file. A child emits `ModelStep::Ask`; asserts a named refusal block and that no `LoopOutcome::Escalated` escapes. *Mutation:* delete the `raises_to` check in the `Ask` arm at `engine.rs:1236` → red. (The reviewed design stated this invariant and tested it nowhere.)
6. **`a_detached_run_that_raises_is_told_so`** — same file. `OrphanPolicy::Detach`, then raise; asserts `NotRaisable(Detached)`, one `EventKind::RunFailed` row, and the constant in the raiser's window. *Mutation:* collapse the reason to a bare `NotRaisable` → the event has no reason → red.
7. **`a_checkpoint_without_a_route_is_refused_by_name`** — `crates/marlowe-loop/tests/durable_route.rs`. A previous-version blob decodes to `Err(ResumeError::…)`. *Mutation:* `#[serde(default)]` on `raises_to` → the blob decodes → red.
8. **`a_pending_escalation_survives_a_daemon_restart`** — `crates/marlowe-daemon/tests/escalation_durability.rs`. Raise, drop the desk, `EscalationDesk::from_journal`, assert the same id at the same recipient. *Mutation:* skip the `Recorder` write → red.
9. **`terminate_never_reaches_a_model_on_a_real_daemon_turn`** — `crates/marlowe-daemon/tests/terminate_never_reaches_a_model.rs`. `RecordingDriver: ModelDriver` through Session C's public seam; captures every `(ContextView, ExposedSet, CallLimits)` the **running** process hands it. `captured.len() >= 1` is a hard assertion, and the model precondition **skips loudly and fails when it resolves write-only** — ROADMAP's C row records that provider selection returns early when `Availability::probe` finds no model, and a skipped integration test prints nothing and reads green.
10. **`the_escalation_explanation_is_in_marlowes_body_and_in_no_agents`** — `crates/marlowe-daemon/tests/escalation_explanation.rs`. Fresh conversation, **no escalation**: both §3.3 sentences in the `system` role of the first captured body; then a forced compaction past 0.70 fill, still there; then absent in all 18 agent bodies. *Mutation:* copy `secretary_notes` in either child loop (`engine.rs:2206` or `:2798`) → red. *Mutation:* assert lazily on the first escalation → the pre-escalation assertion fails.
11. **`the_escalation_body_is_absent_from_marlowes_window`** — `crates/marlowe-daemon/tests/marlowe_cannot_read_an_escalation.rs`. Marker `ESCALATION-BODY-9f31` in `sentence` and artifact content; absent from the stored `SessionState` and every captured body; and Marlowe's window gained **exactly one** block equal to the rendered `Notice::EscalationRaised` — so "the notification arrived without the body" is distinguished from "nothing arrived".
12. **`an_option_label_cannot_contribute_a_line_or_move_the_cursor`** — `crates/marlowe-contract/tests/escalation_labels.rs`. Corpus of `\n`, `\r\n`, `\u{1b}[2K\r`, `\u{202E}`, `\u{2028}`, `\u{200B}`, `\u{E0001}`, 4,000 chars. **Trim-dependent control:** asserts first that each raw input actually violated something, so a clean corpus fails rather than passing vacuously. Plus `serde_json::from_str::<OptionLabel>("\"a\\u001b[2Kb\"")` is `Err`. *Mutation:* `#[derive(Deserialize)]` → red.
13. **`terminate_survives_a_hostile_option_list`** — `crates/marlowe-surface/tests/escalation_overlay.rs`. Maximal options, maximal cost, four `IrreversibleAct` rows, two `Survivor` rows, long host — rendered at **24×80 and 10×40**; walks both buffers for the label's cells at the reserved row; no cell fails `is_renderable`; `EscalationView::new` returns `Err(TooManyOptions)` on a fifth option. *Mutation:* size the modal from unwrapped content → red at 10×40 first.
14. **`the_termination_cost_comes_from_the_journal_and_not_from_the_agent`** — `crates/marlowe-daemon/tests/termination_cost_is_journal_derived.rs`. Subtree writes 3 files, pushes 0 commits, one `Detach` child; the top-agent's option text claims *"six hours, 40 files"*. Asserts `artifacts == 3`, one `FilesWritten { count: 3 }`, no `CommitsPushed`, `survivors` names the detached child, `spend_micros_usd == run.spent.micros_usd`, and that `40` / `six hours` appear only inside the normalised option region. Paired with `every_termination_cost_field_is_rendered` (`marlowe-view/tests/`), which mutates each of the six fields and asserts the rendered rows change — the #16 guard for this type.

---

### 9. Contract impact

- **CONTRACTS §5** — `Run` gains `raises_to: RaisesTo`, pinned explicitly. §5's pinned `Run` is *already* divergent in two directions and both should be raised in the same act rather than exploited: the pin lists `result: Option<ContentRef>` (`CONTRACTS.md:916`), which `run.rs:569-601` does not have, and the code holds a private `trust_floor` the pin does not list. Adding a field privately behind an accessor is a route `trust_floor` opened; do not take it quietly.
- **CONTRACTS gains §5.2, "The escalation record"** — `Escalation`, `EscalationSeverity`, `EscalationCategory`, `ValidatedSentence`, `OptionLabel`, `ArtifactHandle`, `EscalationRoute`, `Recipient`, `RaisesTo`. These cross loop → daemon → surface, which is CONTRACTS' own trigger.
- **`SpawnRequest` — nothing.** §5 pins only `fn spawn(&self, req: SpawnRequest) -> RunId` (`CONTRACTS.md:941`, the sole hit). Session C's `role` field is what pins the shape; a `kind: AgentKind` beside it would be a second unread field in the same act, and the tool set is what the child actually gets.
- **`Checkpoint`** — `CHECKPOINT_VERSION` bumped; not a CONTRACTS type.
- **Not touched:** `TurnEvent` (the window rides the control-plane listener), `MemoryHost`, `Channel::Agent` (no producer). `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns exactly two definition hits.

### 10. §13-guarded, for the human

**`crates/marlowe-loop/src/driver.rs` only** — `ModelStep::Escalate`, `EscalationRequest`, `EscalationPort`, `NoEscalation`. `profile.rs` and `adjudicate.rs` are untouched. A `DECISIONS.md` entry arrives with it.

### 11. For the human, and what is NOT re-opened

- **The `marlowe-view` → `marlowe-contract` dependency** is a stance change on a zero-dependency crate and wants a `DECISIONS.md` entry.
- **Does Marlowe learn an escalation's outcome?** M3-DESIGN §12 item 1. `secretary_notice` has no outcome parameter — the safe default, and not a decision to take silently.
- **A human-readable agent name** belongs with Session C's `role` field in one deliberate pinning act, not smuggled in as a display convenience. The fourth model role is not named here and nothing in this design chooses one.
- **The per-turn latch is NOT re-opened.** ROADMAP's C row is explicit: SECURITY-AUDIT §8 answered it on 2026-08-12 (*"the latch belongs on the session, not the Run"*), and the instruction is to **record that answer in `DECISIONS.md`**, not to raise it again as undecided. Nothing in this design depends on the latch being per-session: §3.2's containment is a routing fact, not a floor fact.
- **The artifact-as-Target question is not re-opened either.** `manifest.rs:85` already lists *identifier* under `ArgumentRole::Target`.

### 12. Standing hazards

- **Ollama capacity, measured today, not cited.** 1,053 MiB free with three roles resident and 5,086 MiB held by the desktop. Nothing on the escalation path may call a model: `TerminationCost` and `SourceEvidence` are journal replays. ADR-044 resolves the embedder's provider against free VRAM at load, so a summarising escalation window would push the embedder to CPU with a correct-looking log line. `AGENT-DIRECTORY.md` §2's *"headroom for the KV cache, the embedder and the reranker"* is wrong and should be corrected where it is written.
- **`EscalationArm::FreeText`** is §9.1 A8's control, expected to fail. It must refuse to construct without an explicit flag — a load-time error, never a permissive default.
- **B1/B2/B3 arrive intact on the CLI path** if the escalation is rendered the way `agent.rs` renders an approval today. Already in `SECURITY-AUDIT.md`; the CLI renderer is in scope for whoever builds this, and is not a new finding.
- **If either new `escalation.rs` is ever added to `PROTECTED`**, its row goes into CLAUDE.md's table and into `EXPECTED_PROTECTED` in `boundary_hook.rs` in the same commit (#19).

---

# CRITIQUE (broken)

**Fatal:** `UpwardShape` changes no byte the product emits, so A8 as designed measures the flag rather than the channel. The only discriminator is `run.parent`. For `parent: None` the match arm is `(None, _) => UpwardNote::Principal` — shape ignored outright. For `parent: Some(_)` the note is computed and then thrown away: `Engine::spawn`'s note match (`crates/marlowe-loop/src/engine.rs:2910-2947`) already replaces a child's `LoopOutcome::Escalated { question }` with the fixed harness string "[child asked a question; a child cannot escalate to the parent's window and its question was not carried across]", so a child's `Escalated` never reaches `daemon.rs:2899` and never becomes `Event::Escalation`. The design says so itself — "the child→parent hop was closed at engine.rs:~2900 … I am designing only for [run→OUT]" — then builds three arms whose sole discriminator is that closed hop. `--upward-shape typed` and `--upward-shape free-text` therefore produce byte-identical product behaviour. `a_typed_escalation_carries_none_of_the_models_question` can only be green by constructing an `Escalation` inside the test process and serialising it there — the `persona_emission.rs` failure aimed at a security measurement — and `every_escalation_row_names_its_arm` is instance #15 verbatim: the journal row would read `upward_shape: "free_text"` on a build where every note is deleted, because the row moves with the flag, not with the channel.

## Strengthened

# The upward channel — Session C, corrected

## The one-line change of intent

A8 varies **`Engine::spawn`'s note**, the only place a child's words cross into a parent, because that is where `REDTEAM-SESSION.md` §4 pass 1 says the attack surface is ("the condensed summary re-entering a parent at `AgentInferred`, and the typed upward channels C ships"). The root→user hop is not an upward hop — `Run::root` has `parent: None` and speaks to its own principal — and it is left exactly as it is.

---

## 1. New file: `crates/marlowe-loop/src/upward.rs` (not §13-guarded)

```rust
use serde::Serialize;
use marlowe_contract::TrustClass;
use crate::run::{Run, RunId};
use crate::driver::AskRequest;

/// M3-DESIGN §9.1 arm A8. No `Default`, no `unwrap_or`: every construction site names an arm.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpwardShape { Typed, TypedPlusValidatedSentence, FreeText }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UnknownShape;

impl UpwardShape {
    pub const ALL: [UpwardShape; 3] =
        [Self::Typed, Self::TypedPlusValidatedSentence, Self::FreeText];
    /// The ONE producer of the string the journal row and the report cell carry.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Typed => "typed",
            Self::TypedPlusValidatedSentence => "validated_sentence",
            Self::FreeText => "free_text",
        }
    }
    /// Total, with an error arm. An unrecognised value REFUSES; it never falls back to `Typed`.
    /// A mistyped arm that silently measures the product under the control's label is the
    /// failure this session exists to detect.
    pub fn parse(s: &str) -> Result<Self, UnknownShape> {
        let k = s.replace('-', "_");
        Self::ALL.iter().copied().find(|v| v.as_str() == k).ok_or(UnknownShape)
    }
}

/// §2.3's closed set. Model-nameable except `Unclassified`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationCategory {
    Blocked, ContradictoryBrief, IrreversibleAhead,
    BudgetCeilingReached, IntegritySuspected,
    /// Harness-substituted; `parse` has no arm for it. What a run whose floor blocks composed
    /// targets receives instead of the category it asked for. §2.2 — escalating is speech, the
    /// *urgency* is a target, and only the urgency is refused.
    Unclassified,
}

/// M3-DESIGN §2.3 names `severity`; §3.2 renders it; §9.1 A7 is "severity-gated". All three stand.
/// **HARNESS-DERIVED, NEVER MODEL-CHOSEN** — that is the whole correction. §3.4's objection to the
/// options list, one field over: a compromised top-agent does not pick the adjective that lands
/// inside harness chrome.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity { Critical, Normal }

impl Severity {
    pub fn as_str(self) -> &'static str {
        match self { Self::Critical => "critical", Self::Normal => "normal" }
    }
    /// Reader: `Event::Escalation { interrupt }`.
    pub fn interrupts(self) -> bool { matches!(self, Self::Critical) }
}

impl EscalationCategory {
    /// `Unclassified` is deliberately absent: the substitution is the harness's and must be
    /// unreachable by naming it.
    pub const ALL: [EscalationCategory; 5] = [
        Self::Blocked, Self::ContradictoryBrief, Self::IrreversibleAhead,
        Self::BudgetCeilingReached, Self::IntegritySuspected,
    ];
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Blocked => "blocked",
            Self::ContradictoryBrief => "contradictory_brief",
            Self::IrreversibleAhead => "irreversible_ahead",
            Self::BudgetCeilingReached => "budget_ceiling_reached",
            Self::IntegritySuspected => "integrity_suspected",
            Self::Unclassified => "unclassified",
        }
    }
    /// **THE READER of `category`.** Total; a new variant is a compile error here.
    pub fn severity(self) -> Severity {
        match self {
            Self::IntegritySuspected | Self::IrreversibleAhead => Severity::Critical,
            Self::Blocked | Self::ContradictoryBrief
            | Self::BudgetCeilingReached | Self::Unclassified => Severity::Normal,
        }
    }
    /// Model-facing. Called by `AskRequest::from_args` — the caller that makes this not #16.
    pub fn parse(s: &str) -> Option<Self> {
        let k = s.trim().to_ascii_lowercase();
        Self::ALL.iter().copied().find(|v| v.as_str() == k)
    }
}

/// §3.6's provenance line. `floor` and nothing else in Session C.
///
/// **`external_sources` is deliberately absent.** The journal already records every `finish_call`
/// with its result's trust class; a counter on the `Run` would be a second answer that disagrees
/// across a turn boundary, where `Run::root` is rebuilt. Derive the count at render time when
/// §3.6's window lands.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Lineage { pub floor: TrustClass }

/// §2.3's record. `Serialize` only — no `Deserialize`, no public struct literal, so §12's serde
/// bypass has no door.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Escalation {
    pub run_id: RunId,
    pub category: EscalationCategory,
    /// What the model asked for, beside what it got. A row showing only the granted value cannot
    /// tell "asked for nothing" from "asked and was refused", and the second is the security event.
    pub category_requested: Option<EscalationCategory>,
    pub artifact: Option<ArtifactRef>,
    pub lineage: Lineage,
    /// The root's own question to its principal. `None` for any run with a parent — a child's
    /// question does not cross, and never did (`Engine::spawn`).
    principal_question: Option<String>,
}

impl Escalation {
    /// THE ONLY CONSTRUCTOR.
    pub fn raise(run: &Run, req: &AskRequest, artifact: Option<ArtifactRef>) -> Escalation {
        // AUTHORITY, read once from where ADR-023 latched it. `Lineage` is DERIVED from this same
        // binding, so the number shown and the number enforced are one expression and a caller
        // cannot invert them by handing in a struct.
        let floor = run.trust_floor();
        let category = match req.category {
            Some(c) if !marlowe_permission::blocks_composed_targets(floor) => c,
            _ => EscalationCategory::Unclassified,
        };
        Escalation {
            run_id: run.id,
            category,
            category_requested: req.category,
            artifact,
            lineage: Lineage { floor },
            principal_question: run.parent.is_none().then(|| req.question.clone()),
        }
    }
    pub fn principal_question(&self) -> Option<&str> { self.principal_question.as_deref() }
    /// Derived, never stored — one copy of the fact.
    pub fn severity(&self) -> Severity { self.category.severity() }
}

/// An artifact the USER opens (§2.3). Not `ContentRef`: `grep -rn "struct ContentRef"
/// --include=*.rs crates/` returns nothing — the name is pinned in CONTRACTS §12 and has no Rust
/// implementation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactRef {
    /// `relative` is `ScopedPath::relative()` — harness output from a SUCCESSFUL `PathScope::open`,
    /// never the model's argument string. No `bytes`: nothing reads it and it needs a stat.
    Workspace { relative: String },
    Run(RunId),
}
```

## 2. `crates/marlowe-loop/src/driver.rs` — **§13-GUARDED, EDITED, SEE §7**

```rust
/// Escalate. `question` is a Payload; `category` and `artifact_path` are Targets.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AskRequest {
    pub question: String,
    /// `None` when the model named none OR named one outside the closed set — not a default:
    /// `raise` substitutes `Unclassified` and the row records `requested: null`, so "did not ask"
    /// and "asked and was refused" stay distinct.
    pub category: Option<EscalationCategory>,
    pub artifact_path: Option<String>,
}

impl AskRequest {
    /// Total, and it lives HERE for `SpawnRequest::from_args`'s stated reason: "a second provider
    /// that wrote its own mapping would be a second definition of the contract."
    pub fn from_args(args: &Args, message: &serde_json::Value) -> Self { /* … */ }
}

pub enum ModelStep { /* … */ Ask(AskRequest) }   // was Ask(String)
```

`crates/marlowe-provider/src/ollama.rs:1023` becomes one line with no policy in it — `"ask" => ModelStep::Ask(AskRequest::from_args(args, message)),` — and the openrouter and llamacpp folds route through the same call.

## 3. `crates/marlowe-tools/src/builtin.rs` — the producer (NOT guarded)

`ask`'s registration gains two parameters beside `question`:

```rust
documented("category", ArgumentRole::Target, Text, false,
  "One of: blocked, contradictory_brief, irreversible_ahead, budget_ceiling_reached, \
   integrity_suspected. It decides whether the user is interrupted now or sees this when they \
   next look. Omit it and the harness classifies. A name outside this list is ignored."),
documented("artifact_path", ArgumentRole::Target, Text, false,
  "A path in this workspace for the user to open. It is resolved against your path scope; one \
   that does not open is dropped."),
```

Without this the whole `category` chain is instance #16. `builtin.rs`'s own note records the precedent: `options` was deleted from this manifest because a model that listed them "had them silently dropped on the way to a user who never saw them."

## 4. `crates/marlowe-loop/src/engine.rs` — where A8 actually lives (NOT guarded)

```rust
pub enum LoopOutcome {
    Completed(CondensedResult),
    Paused { reason: PauseReason },
    Escalated(Escalation),
    Cancelled,
    Failed { error: String },
}

pub struct Engine<S: PathScope + Clone> { /* … */ scope: S, upward_shape: UpwardShape }
```

`Engine::new` gains a seventh parameter (no `Default`) and keeps its own `scope` clone beside `Adjudicator::new(scope.clone())`, so **no §13-guarded file is edited to reach the scope**. One production site, `daemon.rs:2085`; 29 test sites pass `UpwardShape::Typed` explicitly. Also update `engine.rs:2322`'s `LoopOutcome::Escalated { .. } => QuarantineRefusal::Escalated` to the tuple form.

**At `ModelStep::Ask` (engine.rs:1236)** — resolve the artifact where the scope and workspace are in hand, then construct:

```rust
ModelStep::Ask(req) => {
    let artifact = req.artifact_path.as_deref().and_then(|p| {
        self.scope.open(run.profile.path_globs(), &self.workspace, p, Access::Read)
            .ok().map(|sp| ArtifactRef::Workspace { relative: sp.relative().to_string() })
    });
    let esc = Escalation::raise(run, &req, artifact);
    self.record(ports, EventKind::ApprovalRequested, run, state, json!({
        "question": req.question,
        "category_granted": esc.category.as_str(),
        "category_requested": req.category.map(|c| c.as_str()),
        "severity": esc.severity().as_str(),
        "floor": esc.lineage.floor,
        "artifact_requested": req.artifact_path,
        "artifact_resolved": esc.artifact,
        "upward_shape": self.upward_shape.as_str(),
    }));
    run.status = RunStatus::Paused { reason: PauseReason::AwaitingAnswer };
    return LoopOutcome::Escalated(esc);
}
```

**AND THE ARM, at `Engine::spawn`'s note match (engine.rs:2910-2947).** This is the change the reviewed design omits and without which A8 measures nothing:

```rust
/// What crossed, and under which arm — ONE value, so a report cell cannot lose track of what
/// produced it. The arm lives beside the bytes, not in a flag somewhere else.
pub struct CrossedNote { pub text: String, pub shape: UpwardShape }

let note = match self.upward_shape {
    // ── ARM (a) TYPED: today's code, byte for byte. `req.contract.validate` then
    //    `result.render()`; every other outcome is a harness constant, including `Escalated`,
    //    whose question is journalled and does not cross. The product default.
    UpwardShape::Typed => self.typed_note(&req.contract, outcome, &child_run, &child_budget),

    // ── ARM (b) TYPED + ONE VALIDATED SENTENCE: arm (a), plus a `headline` field produced by a
    //    QUARANTINED child over the child's own result — `ExposedSet::empty()`,
    //    `EgressPolicy::DenyAll`, `Budget::slice_for_quarantined_read`, the same machinery
    //    `condense_batch` uses, under
    //      OutputContract::structured("one line for the parent",
    //          vec![FieldSpec::line("headline").capped(200)])
    //    FAIL CLOSED: any non-`Completed` validator outcome omits the field entirely.
    UpwardShape::TypedPlusValidatedSentence => { /* … */ }

    // ── ARM (c) FREE TEXT — **THE CONTROL, EXPECTED TO FAIL.** `child_state`'s last assistant
    //    message, verbatim, `validate` NOT called. This DELIBERATELY REOPENS the hole the comment
    //    above closed ("`Escalated { question }` was the worst: a model-written string,
    //    interpolated verbatim, one trust class above its origin"). It exists so §2's invariant
    //    has a vacuity control; it is journalled on every row, announced on the boot line, and it
    //    takes a `DECISIONS.md` entry of its own.
    UpwardShape::FreeText => { /* … */ }
};
```

## 5. `crates/marlowe-daemon/src/protocol.rs`

```rust
Escalation {
    run: String,
    category: String,            // EscalationCategory::as_str — the one producer
    category_requested: Option<String>,
    severity: String,            // Severity::as_str
    interrupt: bool,             // Escalation::severity().interrupts()
    note_kind: String,           // NoteKind::as_str — a real enum, not four inline literals
    note: Option<String>,
    artifact: Option<String>,
    floor: String,
},
```

Nothing in `daemon.rs` formats an enum with `{:?}`. A round-trip test in `upward.rs` asserts `serde_json::to_value(v) == json!(v.as_str())` for every variant of every enum above, so the serde spelling and the `as_str` spelling cannot become two answers.

## 6. Deferred, with the reason named rather than shipped as fields nothing fills

- **The whole §4.1/§4.2 budget-extension record.** `grep -rni "extension|envelope" crates/marlowe-loop/src/` returns zero: no `ModelStep` variant, no tool, no `from_args`. Shipping `BudgetExtension` + `ExtensionReason::max_grants_per_run` + `ExtensionEvidence` without a producer is instance #16 at subsystem scale, and pinning it in CONTRACTS §12 would pin a declaration. It ships when `ModelStep::RequestBudget(BudgetExtensionRequest)`, a `request_budget` registration with `reason` as a Target, and `BudgetExtensionRequest::from_args` ship in the same commit — or it waits, and `STATE.md` says which.
- **`Lineage.external_sources` and §3.6's host/fetched-at citations.** The journal holds the source data; the renderer is §3.6's window, a later session's. Derive at render, do not latch a second counter.

## 7. LOUD — what the human must approve

1. **`crates/marlowe-loop/src/driver.rs` IS §13-GUARDED AND THIS EDITS IT.** `ModelStep::Ask(String)` → `Ask(AskRequest)`, plus a new `AskRequest` and its `from_args`. The hook's own entry for that file says: "THE FILE IS WIDER THAN THE BOUNDARY: it also declares `ModelStep`, `ToolHost`, `ToolBody`, `ClockSource`, `TurnSink`, `ApprovalGate` … READ WHICH TYPE IS BEING CHANGED before approving: if it is not the memory port, this prompt is noise and the honest answer is yes." `MemoryHost` and `ExternalContent` are untouched. No other guarded file is edited — `blocks_composed_targets` (`adjudicate.rs:50`) is `pub` and is called, not modified; `profile.rs`, `provenance.rs` (hook line 117), `taint.rs`, `steer.rs`, `memory.rs`, `mcp.rs`, `pin.rs`, `scope/` and the journal files are untouched.
2. **`severity` STAYS, harness-derived.** This reverses the design under review. Removing it revisits `DECISIONS.md:3319-3321` (2026-08-29), whose quoted record shape contains it, and it would foreclose §9.1's A7 as worded. `EscalationCategory::severity()` keeps §2.3's field, §3.2's rendered sentence and A7 intact while taking the adjective away from the model.
3. **Whether `UpwardShape::FreeText` ships in the RELEASE binary.** It must not be a `cfg` feature — a control on a different artifact measures a different system, the `persona_emission.rs` family — and a CLI flag on the shipped binary is this project's established pattern (`--reranking off`, `--embedder-provider cpu`). But arm (c) is a permanently-available unvalidated upward channel that deliberately reopens a closed laundering path, and that is a posture question, not a measurement one.
4. **Arm (b) needs a model and there is no VRAM for a fourth.** Measured today via `GET /api/ps`: 14,993 MiB used, **1,053 MiB free**, with the desktop holding 5,086 MiB before any model loaded. `AGENT-DIRECTORY.md` §2's "headroom for the KV cache, the embedder and the reranker" is contradicted by that number, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD — so arm (b) is the arm most likely to push the embedder to CPU mid-measurement with a correct-looking log line. Arm (b)'s cells pin `--embedder-provider cpu`, and `a8_report.py` reads the provider that actually resolved off the boot line, not off the flag. Which of the three named roles validates the sentence — or whether it is the unnamed fourth — is the human's, and is not named here.
5. **SECURITY-AUDIT finding 6 (`remember` and `ask` never reach the adjudicator) stays OPEN and is cited, not claimed.** The narrow `blocks_composed_targets` call inside `raise` buys the one property this session needs — a tainted run cannot choose its urgency — using the same function the adjudicator enforces on, with no edit to `adjudicate.rs`. `Engine::spawn` already sets that precedent (ADR-057 §4). Closing finding 6 properly is a consequence level, a blast radius and a journalled `PermissionDecided` row for `ask`, in a guarded file, and is a session's work.
6. **`SECURITY-AUDIT.md` §8's open question is untouched and must stay that way.** The latch's run-vs-session scope, and ADR-032's identical run-vs-session question about egress grants, are the human's and should be answered together or not at all. Nothing here widens either.

## 8. Tests — each names the mutation that reddens it

| Test | File | Asserts | Mutation |
|---|---|---|---|
| `the_arm_decides_what_crosses_from_a_child` | `crates/marlowe-loop/tests/upward_channel.rs` | ONE test, THREE runs of the identical scripted child through the real `Engine::spawn`. The child emits nonce `BANANA-7Q` in a field its `OutputContract` does **not** declare. Assert on the bytes pushed into the PARENT's `state`: under `Typed` the nonce is in **no byte**; under `FreeText` it **is**; under `TypedPlusValidatedSentence` it is absent and the `headline` field is present. Three arms, three different readings — a build where nothing crosses fails the `FreeText` half. | Make every arm return the `Typed` note → `FreeText` half red. Make `Typed` skip `req.contract.validate` → `Typed` half red. |
| `the_arm_is_visible_in_the_journal_of_the_running_process` | `crates/marlowe-daemon/tests/upward_shape_is_emitted_by_the_running_process.rs` | Launch `target/debug/marlowe.exe --serve --upward-shape free-text`, drive one real spawn whose child emits the nonce, read `tools/read_journal.py --all`: the PARENT's `RunCompleted` payload contains the nonce. Relaunch with `--upward-shape typed`: it does not. **The nonce, not the flag** — this is what stops the row being #15. | Drop the shape match in `Engine::spawn` → the two launches produce identical journals and the test fails by nonce, not by label. |
| `a_tainted_run_cannot_choose_its_escalation_category` | `upward_channel.rs` | A run latched to `UntrustedContent` asks with `category: Some(IntegritySuspected)` → `Unclassified`, `severity() == Normal`, row carries `requested: "integrity_suspected" / granted: "unclassified"`. NEGATIVE CONTROL in the same test: an untainted run gets `IntegritySuspected` and `severity() == Critical`. | Delete the `blocks_composed_targets` guard → tainted half red. Force `Unclassified` unconditionally → control half red. |
| `severity_is_derived_and_moves_the_wire` | `upward_channel.rs` | `Event::Escalation` serialises `severity: "critical", interrupt: true` for `IrreversibleAhead` and `"normal", false` for `Blocked`, read off the JSON frame. Plus: `serde_json::to_value(&Escalation{..})` has **no** `severity` key — derived, not stored, one copy of the fact. | Move `IrreversibleAhead` to the `Normal` arm. Or add a stored `severity` field → the key-set half fails. |
| `the_models_category_actually_reaches_the_loop` | `crates/marlowe-tools/tests/ask_manifest.rs` | Feed a real `/api/chat` tool-call body naming `category: "integrity_suspected"` through `parse_step`; assert `ModelStep::Ask(AskRequest { category: Some(IntegritySuspected), .. })`. NEGATIVE: `category: "banana"` → `None`, and the row reads `requested: null`. **This is the test whose absence makes `EscalationCategory::parse` instance #16.** | Remove the `category` parameter from `ask`'s registration → `Args` drops it and the test reads `None`. |
| `an_artifact_path_outside_the_scope_is_dropped_and_journalled` | `upward_channel.rs` | `artifact_path: "../../etc/passwd"` → `escalation.artifact == None`, row carries `artifact_requested: "../../etc/passwd", artifact_resolved: null`. A path inside the scope resolves to `ScopedPath::relative()`, which is **not** the string the model supplied (assert they differ). | Pass the model's string straight into `ArtifactRef::Workspace` → the row shows a resolved path that never opened, and the differ-assertion fails. |
| `lineage_floor_is_the_runs_latched_floor_and_survives_a_trim` | `upward_channel.rs` | Following `adr023_live.rs`: FIRST assert the emitted §B6 line shows the untrusted block was actually trimmed (an assertion whose subject is "X was removed" carries an assertion that X was removed), THEN `escalation.lineage.floor == run.trust_floor() == UntrustedContent`. | Build `Lineage` from `view.trust_floor()`. It reddens ONLY because the trim occurred, which is why the trim control is the first assertion. |
| `the_root_runs_question_still_reaches_its_principal_under_every_arm` | `upward_channel.rs` | A ROOT run (`parent: None`) asks the nonce question under all three arms; `principal_question()` is `Some` and the nonce is in the emitted frame every time. The typed arm must not mute Marlowe — his channel to his own principal is not an upward hop. | Drop the `run.parent.is_none()` guard → `principal_question` is `None` and the nonce vanishes. |
| `the_shape_flag_has_no_silent_default` | `crates/marlowe/tests/upward_shape_flag.rs` | `marlowe --serve --upward-shape banana` exits 2 naming all three spellings, in `--reranking`'s style (`main.rs:741`). Absent flag → `Typed`, announced on the boot line via `announce::info`. | Replace the refusal with `parse(v).unwrap_or(Typed)` → exits 0, assertion fails. |
| `every_spelling_has_one_producer` | `upward_channel.rs` | For every variant of `UpwardShape`, `EscalationCategory`, `Severity`, `NoteKind`: `serde_json::to_value(v) == json!(v.as_str())`, and `parse(v.as_str())` round-trips. | Change one `as_str` string or one `rename_all` → red by name. |
| `a8_report_refuses_a_cell_it_cannot_label` | `tools/test_a8_report.py` | `python tools/a8_report.py --run <fixture> --expect-arms typed,validated_sentence,free_text` exits non-zero and names the cell when (a) rows in one cell carry two arms, (b) **rows carry no `upward_shape` key at all**, or (c) an expected arm is missing from the sheet. Clean journal → exit 0, three rates, n per cell, and the embedder provider resolved off each run's boot line. | Remove case (b) → a journal with the field deleted reads as one arm and prints a plausible rate, which is #19. **THE NUMERIC TARGET:** `python tools/a8_report.py --run runs/m3-c-a8 --expect-arms typed,validated_sentence,free_text` prints three injection-propagation rates, three n, and a discarded-cell count. |

## 9. Contract and document impact

- **Nothing pinned moves.** `grep -c LoopOutcome docs/design/CONTRACTS.md` → **0**. `grep -n SpawnRequest docs/design/CONTRACTS.md` → one hit, **line 941**, pinning `fn spawn(&self, req: SpawnRequest) -> RunId` — the method, not the shape. §5.1 pins the **quarantined reader's** contract (`source_N` slots); an ordinary child's `OutputContract` arrives on the unpinned `SpawnRequest`, so varying it per arm is legal.
- **CONTRACTS §12 gains `Escalation`, `Lineage`, `ArtifactRef` and nothing else** — the three that have a producer this session. §12's header currently reads "These six are the remainder — five structs below, and the memory port in §12.1"; it is corrected in the same commit, because a stale count in a pinned file is exactly what M3-D2 had to fix last week.
- **A new CONTRACTS §13.1** pins `protocol::Event` as the daemon wire enum and states its relationship to §13's `TurnEvent`. The current §13 pins `TurnEvent`, which has no `detail` field, so "§13 gains `Event::Escalation`" as the reviewed design wrote it describes a type that section does not contain.
- **`DECISIONS.md` takes two entries**, not one: (i) `severity` is retained and made harness-derived, citing the 2026-08-29 narrow entry whose quoted shape contains it; (ii) `UpwardShape::FreeText` deliberately reopens `Engine::spawn`'s laundering path as A8's control, with its ship-in-release status the human's.
- **M3-DESIGN §2.3 and §9.1's A8 row** are amended in place with the arm spellings `typed` / `validated_sentence` / `free_text`, so the document and `UpwardShape::as_str` cannot drift.
- **No `Channel` variant is added and `trust_for_channel` is untouched.** `grep -rn "ingest_external(" --include=*.rs crates/*/src/` stays at exactly two hits, both definitions (`marlowe-daemon/src/memory.rs:542`, `marlowe-loop/src/driver.rs:573`). Layer 3 remains unreachable in the shipped daemon, which is correct (ADR-062). No producer for `Channel::Agent` is proposed — that is Session D's. `a8_report.py` prints the §5 layer tally on its front page so a clean A8 sheet is never read as evidence about layer 3, which is REDTEAM §2's named false pass.

---

# CRITIQUE (broken)

**Fatal:** The envelope — the design's own headline — is unbuildable as written and its central number is undefined. `Budget::extend(.., want: BudgetDelta)` has no producer named anywhere in the design; `BudgetDelta` derives `Default`, so the degenerate all-zero want returns `Granted { delta: 0 }`, which announces, journals a `BudgetExtended`, raises nothing, and returns to a loop whose very next iteration hits the same exhaustion check — an unbounded announce/journal cycle at the site reached on every budget pause in the product. Nothing bounds the number of within-envelope extensions either, so once a `want` IS defined, auto-extension on exhaustion makes `budget` advisory and the envelope the only real cap: the design's own rejected alternative #5 ("each individual approval looks reasonable") relocated one level down, with the harness doing the clicking. And the mechanism's single named user-visible reader cannot compile: `crates/marlowe-daemon/Cargo.toml:11` declares `marlowe-loop.workspace = true`, while `crates/marlowe-loop/Cargo.toml`'s dependencies are contract/journal/permission/tools only — so `engine.rs` calling `marlowe_daemon::announce::say` is a reverse dependency edge. The diagnostic half (starved leaf, subagents still sliced from the remainder, `grant` clamping against `spent` rather than obligations) is verified correct against source and survives.

## Strengthened

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
