# five-levels: Level is derived by the harness and lives on the profile; role is declared by the spawner and is a Target — and neither field ships without its reader

**Adversary verdict:** sound-with-fixes

**Fatal:** `disposition` is a declared control with no reader that distinguishes its two values on Marlowe's own spawn path — `child_of(Secretary, Manage)` and `child_of(Secretary, Work)` both return `TopAgent`, `CapabilityProfile::new` has no `TopAgent` arm, and the design's own test asserts *the same answer for both inputs*, so it is green whether `disposition` is plumbed through or dropped on the floor. M3-DESIGN §1.1's distinction ("`master` … gets a create grant" vs "`worker` — will do the task itself") is unenforced, a work-disposed top-agent can hold `run` and `bash` at once, and the design ships instance #16 with its proxy test pre-written, in the very design whose stated blocking finding is instance #16.

## Ledger instances the adversary says this re-commits

- **#16 (a declared control nothing reads)** — `SpawnRequest.disposition`. Its only consumer is `AgentLevel::child_of`, which returns `TopAgent` for both of its values on the Secretary path, and the `TopAgent` arm of `CapabilityProfile::new` is `_ => {}`. Nothing reads the difference.
- **#16** — `run.rs::escalation_target` and `EscalationTarget`. Zero callers proposed anywhere; the `enforcement_sites` row names `escalation_target` as its own reader. Same shape as SECURITY-AUDIT H4 (`Transport::manifest_provenance`, filed there as family #16).
- **#16** — `ModelRoute::Summarizer` remains without a production producer after the change (verified: no `ModelRoute::Summarizer` construction under `crates/` outside `routing.rs`'s own match arm and its unit test), so the third column of the role table is configured and never selected.
- **#16** — `CapabilityProfile::may_create_agents`'s `level.may_hold_create_grant()` conjunct: a method the design never defines, restating an invariant `CapabilityProfile::new` already enforces.
- **#15 (an assertion that reads the same either way)** — `the_role_table_leaves_room_for_the_embedder` asserts `free_vram_mib >= EMBEDDER_RESERVE_MIB` against a guessed constant. The embedder silently on CPU with 1,100 MiB free prints PASS. The design names the real instrument (the shipped binary's `…ExecutionProvider` line) and demotes it to a control.
- **#15** — `terminate_appears_in_no_agents_request_body_at_any_level` builds its profiles and its request body inside the test process. It prints 0 occurrences whether or not the deployed daemon's persona, skills or stable tier leak the word. M3-DESIGN §3.4 forbids exactly this: *"Asserting a flag is set is the declaration, not the enforcement."*
- **#15** — `marlowe_only_ever_creates_a_top_agent`'s headline assertion is that both dispositions give the same answer. It is green under the mutation `disposition: parse_disposition(...)` → `Disposition::Work`.
- **#12 (a validating constructor `serde` routes around)** — in a new form: `CallLimits` gains a **public** `route` field with no constructor and ~8 struct-literal sites across four crates, so a route can be set without passing through `Budget::call_limits` and without agreeing with the run's profile. Same argument profile.rs:300-322 makes against holding the granted egress set on the `Run`.
- **#14 (a guard whose subject moved)** — every `Routing::uniform` line citation in the design is wrong (design: 1196/1271/1436/1780/1867; actual: daemon.rs 1263/1338/1503/1889/1976) and `crates/marlowe/src/agent.rs:47` is missed entirely. A six-site prescription with one test that can reach one site.
- **#17 (a zero limit read as already-exhausted)** — correctly avoided in the master rule; re-opened by the unqualified claim "the tree is four deep by construction", which is false of `Engine::condense_batch`'s direct `Run::child` at engine.rs:2146 and is the argument the design uses to say `Budget.depth` never needs to be 0.
- **Two definitions of one fact** — the design's "a worker can never address Marlowe" enforcement duplicates containment the loop already provides structurally at `engine.rs:2935`, where a child's `LoopOutcome::Escalated` is replaced with a fixed harness string. Adding a routing function beside it creates a second answer to "where does an escalation go", and the two can drift.
- **"Defaults that make a mismatch unobservable"** — `parse_role`'s unrecognised-takes-Worker default is justified by a spawn receipt that does not carry the role (`engine.rs:2755` prints tools, budget, orphan, returns and nothing else). The named mitigation has no site.

## Defects (13)

### **FATAL — `disposition` is a declared control with no reader that distinguishes its two values on the one path M3-DESIGN §1.1 names.** `child_of(Secretary, Manage)` and `child_of(Secretary, Work)` both return `TopAgent`; `CapabilityProfile::new`'s proposed level match has `AgentLevel::TopAgent` falling into `_ => {}`; and the `CreateGrantBelowMaster` refusal fires only on `Worker | ToolSpawned`. So after `child_of` runs, nothing consults `disposition` again on Marlowe's own spawn. §1.1 is explicit that the two words mean different grants — *"`master` … Gets a create grant and an agent budget"* versus *"`worker` — will do the task itself"* — and the design enforces neither. A Secretary spawning `disposition: work, exposed_tools: "run bash"` yields a top-agent holding `run` AND `bash`: a worker that can create agents and edit. The design's own test makes this invisible: `marlowe_only_ever_creates_a_top_agent` asserts *the same answer for both inputs*, so it is green whether `disposition` is plumbed through or dropped on the floor at `SpawnRequest::from_args`. That is instance #16 shipped with its green proxy test already written.

- **Why:** This is the field the whole design is built around and it is the eighth repeat of the project's most-shipped defect, in the design that opens by naming it as the blocking finding. It also unenforces §1.2 one level up: a work-disposed top-agent holding `run` can create a Master, and a Master's MANAGEMENT_TOOLS restriction is the only thing standing between the tree and a `master` with `edit`.
- **Fix:** Carry the grant in the level, not beside it: `AgentLevel::TopAgent { manages: bool }`. `child_of(Secretary, Manage) = TopAgent{manages:true}`, `child_of(Secretary, Work) = TopAgent{manages:false}`; `child_of(TopAgent{manages:false}, _) = Err`. Extend `CreateGrantBelowMaster` to fire on `TopAgent{manages:false}` as well as `Worker | ToolSpawned` — then a `Work` declaration and a `run` in the tool list cannot silently agree either. Rewrite the test as `child_of(Secretary, Manage) != child_of(Secretary, Work)` **and** `CapabilityProfile::new(set![run], .., TopAgent{manages:false}, ..).is_err()`. Mutation that reddens it: replace `parse_disposition(text("disposition"))` with `Disposition::Work` in `from_args`.

### **`CapabilityProfile::may_create_agents()` calls `self.level.may_hold_create_grant()`, a method the design never defines — and it is a second definition of a fact the constructor already holds.** If `CapabilityProfile::new` refuses `run` on every level that may not hold it (`CreateGrantBelowMaster`), then by construction no profile at such a level contains `run`, and the `level.may_hold_create_grant() &&` conjunct can only ever be redundant — or, if it ever disagrees with the constructor, silently wrong. Two definitions of "may this run create agents" is the project's most-logged shape.

- **Why:** The redundant conjunct is where the two sides drift. Add a sixth level, forget to add it to `may_hold_create_grant`, and a profile that the constructor happily built reports `false` at the spawn gate — a level that exists and cannot act, with no test red anywhere.
- **Fix:** Delete `may_hold_create_grant` entirely. `pub fn may_create_agents(&self) -> bool { self.exposed_tools.contains(&ToolId::new("run")) }`. The invariant lives in `new`; the accessor reads the set. Add `a_profile_that_may_create_agents_is_exactly_one_that_holds_run` in `crates/marlowe-loop/tests/agent_levels.rs`, iterating all five levels.

### **`escalation_target` has zero callers, and its subject is already structurally contained — so it is #16 on top of a second definition of one fact.** Verified at `crates/marlowe-loop/src/engine.rs:2935`: a child's `LoopOutcome::Escalated { question }` is journalled and replaced with the fixed harness string `"[child asked a question; a child cannot escalate to the parent's window and its question was not carried across]"`. A worker already cannot address anybody, let alone Marlowe. The design's two proposed enforcements — no recipient parameter, no `Secretary` variant — therefore guard a door the loop already welded shut, and its `enforcement_sites` row names `escalation_target` as its own reader. Meanwhile the requirement M3-DESIGN §3 actually states — *"An agent that is genuinely stuck must be able to reach a human"*, *"starts at the agent's direct master and must be approved at each level"* — has **no mechanism at all** in this design: no `LoopOutcome` variant, no change to the `note` match at engine.rs:2911, no queue. The easy half (routing that cannot be reached) has been substituted for the hard half (a channel that does not exist).

- **Why:** Axis 8. §3 is the section the design claims to satisfy, and §3 is about a channel existing. A pure function tested in isolation, with no caller, is exactly `Transport::manifest_provenance` (SECURITY-AUDIT H4) — filed there as family #16 already.
- **Fix:** Either (a) cut `EscalationTarget`/`escalation_target` from Session C entirely and record in STATE.md that §3's upward channel is unbuilt and unrouted, citing engine.rs:2935 as the current containment; or (b) if C is to build it, the design must name the carrier: a new `LoopOutcome::EscalationRaised { severity: Severity, category: Category, artifact: Option<ContentRef> }` — §2.3's typed record, no free text — plus the arm in the `note` match at engine.rs:2911 that either forwards it (parent is a Master or a manage-disposed TopAgent) or refuses it by name, with `escalation_target` called *there* and nowhere else. Option (a) is the honest Session C scope; option (b) needs a §2.3 category enum the human has not pinned. Do not ship the routing function without one of the two.

### **Every `Routing::uniform` line citation is wrong, and one whole file is missing.** Design: *"replacing `Routing::uniform(&self.config.model)` at :1196, :1271, :1436, :1780, :1867."* Measured at HEAD 186b5d5: `crates/marlowe-daemon/src/daemon.rs` **1263, 1338, 1503, 1889, 1976** — five for five wrong — plus `crates/marlowe/src/agent.rs:47`, which the design does not mention. Six production sites. Prescribing six independent edits is itself the defect: the design's test `three_configured_roles_resolve_to_three_models` can only exercise whichever site its fixture happens to reach, so a missed site stays green forever.

- **Why:** A previous roadmap row had five of seven citations wrong and it is a named lesson in this file's own history. More importantly: six edit sites means six places to forget, and the CLI (`agent.rs`) would silently keep collapsing three roles onto one model with every daemon test green.
- **Fix:** One function, one caller-set. Add `impl Daemon { fn routing(&self) -> Result<Routing, RoutingError> }` in `crates/marlowe-daemon/src/daemon.rs` and make all five daemon sites call it; `agent.rs` keeps `uniform` explicitly and says why (a one-shot CLI has no role table). Assert it from outside: `crates/marlowe-daemon/tests/role_routing.rs::the_daemon_builds_its_routing_in_exactly_one_place` greps `crates/marlowe-daemon/src/*.rs` for `Routing::uniform(` and asserts **0** hits, printing the count. Mutation: restore any one `uniform` call — count reads 1, red. That guard's input is the source tree, not a list the guard maintains (#19-safe).

### **`the_role_table_leaves_room_for_the_embedder` is instance #15, and it is machine-state-dependent.** `assert!(free_vram_mib >= EMBEDDER_RESERVE_MIB)` reads identically whether the embedder actually resolved to CUDA — the threshold constant is guessed, ADR-044 resolves against free VRAM *at load* with its own arithmetic, and the design demotes the one instrument that answers the real question (the shipped binary's `embedder asked for auto, running on <X>ExecutionProvider` line) to a "paired control". Worse: the measured baseline includes **5,086 MiB held by Opera GX, Discord, Steam and Wallpaper Engine**. The test goes red when the user opens Discord and green when they close it, and neither transition is about the role table.

- **Why:** Ask what this prints if the thing it names is broken: the embedder silently on CPU with 1,100 MiB free prints PASS. That is the definition of a proxy. And a measurement whose value is set by the desktop is scoped to a system nobody controls — the "re-measure, do not cite" rule applied to a test.
- **Fix:** Invert it. The assertion is on the provider string from the **shipped** binary, not on free VRAM: `crates/marlowe-daemon/tests/role_residency.rs` (`#[ignore]`, run explicitly) starts the daemon with the configured three-model table, then runs `target/release/marlowe.exe --eval-adapter --profile-root <tmp> --embedder-model models/jina-embeddings-v2-small-en --reranking off < /dev/null`, and asserts the stdout line contains `CUDAExecutionProvider`, printing the whole line plus `/api/ps`'s per-model resident bytes and free MiB **as diagnostics, not assertions**. Mutation that reddens it: point a second `ModelRoute` at `marlowe-dawn:9b-super`. State in the test header that the desktop's ~5 GB is part of the system under measurement, so a failure means "not on this machine, in this state" — which is the true claim.

### **`terminate_appears_in_no_agents_request_body_at_any_level` asserts on profiles the test constructs itself.** M3-DESIGN §3.4 is explicit: *"Test it where the bytes go: assert TERMINATE appears in neither the agent's exposed set nor its `request_body`. Asserting a flag is set is the declaration, not the enforcement."* A local `fn profile_for(level) -> CapabilityProfile` plus a test-built `ContextView` cannot see the word arrive from the persona artifact, an installed skill's text, a governance constraint, or the daemon's stable tier — which is where a leak would actually come from. It prints 0 in all those cases.

- **Why:** This is `persona_emission.rs` again (M2 C2e, pipe-tested-guard family, fourth subsystem): a test on a body built inside the test process, passing while the deployed daemon served something else. The design even quotes §3.4's sentence and then writes the version §3.4 forbids.
- **Fix:** Keep the wildcard-free `match` over `AgentLevel` — that part is the correct #19 defence and a sixth variant should be a compile error. Change the **subject**: build the body through the daemon's own assembly path (`crates/marlowe-daemon/tests/terminate_is_invisible.rs`, using the same `Assembler` + stable-tier construction `Daemon::ask_streaming_with` uses) rather than a test-local view, and add a second, non-negotiable check outside the process — a `--dev` outbound-request dump from the shipped binary, greppable for `TERMINATE`, recorded in `runs/<session>/`. Mutation: put `TERMINATE` in `persona/v1.md`. The in-process test must go red on that, or it is testing its own reconstruction.

### **Registering a new `escalate` builtin costs more than the design says, and one cost is a red test.** `crates/marlowe-tools/src/builtin.rs:36` is `pub const BUILTIN_TOOLS: [&str; 12]` — a fixed-length array — and `builtin.rs:749` asserts `assert_eq!(BUILTIN_TOOLS.len(), 12, "ADR-006's eleven, less `done`, plus `write` and `glob`")`. A thirteenth builtin breaks both. It also spends one of exactly two MCP slots: `MAX_EXPOSED_TOOLS = 14` (`exposure.rs:35`), `interactive()` holds 12, and ADR-058 raised the cap *specifically* so two MCP tools fit — profile.rs's own comment says "a fix to Marlowe's own surface must not be paid for out of a user's server allowance." And CONTRACTS §5 still pins `exposed_tools: Vec<ToolId> // INVARIANT: len() <= 12`.

- **Why:** The design lists `escalate` in `MANAGEMENT_TOOLS`'s prose and in a test manifest without ever saying it is a new builtin, so the cost is invisible in the plan and arrives as a red assertion mid-session — plus a user's MCP allowance halved by a rule nobody agreed to.
- **Fix:** Do not register `escalate` in Session C. `MANAGEMENT_TOOLS = ["run", "ask"]` is the honest starting set — both exist, both are runnable, both are already in `BUILTIN_TOOLS`. Fold the escalation-recipient check into `no_escalation_tool_has_a_recipient_parameter` over `ask` alone. When `escalate` lands (with §3's carrier, above), it arrives with: `[&str; 13]`, the updated `assert_eq!` and its message, an executor so `verify_every_exposed_tool_is_runnable` permits exposure, and an explicit note that the MCP allowance drops to one — or a paired increase of `MAX_EXPOSED_TOOLS`, which is an ADR-058 amendment and the human's.

### **`ModelRoute::Summarizer` still has zero production producers after this design lands, so the third column of `Routing` is dead and the test that would catch it is written against a config the test supplies.** Verified: no `ModelRoute::Summarizer` construction exists anywhere under `crates/` outside `routing.rs`'s own `model_for` arm and its unit test. After the change, `Summarizer` is producible only by a model typing `model_role: summarizer` into a `run` call — and `composes_spawn_targets` refuses exactly that under a latched floor. `three_configured_roles_resolve_to_three_models` asserts `models().len() == 3` on a routing the test constructs, so it is green with the third column never selected by anything.

- **Why:** It is #16 one layer out from the one the design correctly identified. The design's whole argument is "the field lands with the chain or it does not land" — and for one of three routes the chain terminates in a column no production code path selects. Shipping a three-model table then makes three models co-resident (1,053 MiB free, measured) to serve two.
- **Fix:** Ship **two** routes wired and the third gated, or give `Summarizer` a producer in the same session. The obvious producer is `CapabilityProfile::quarantined_reader()`, whose whole job in `Engine::condense_batch` is condensation and which currently carries `ModelRoute::Worker` (profile.rs:150) — but ADR-008's own 2026-08-10 amendment says compression ≠ extraction, and the design's `open_for_human` already flags that wobble. So: **do not decide it here.** Session C ships `Routing` with `Orchestrator` and `Worker` selected by real code paths and asserts `models().len() == 2` from the daemon's `routing()`; the third column stays `uniform`-fed until the human answers whether the quarantined reader is `Summarizer`. Add `a_route_with_no_production_producer_is_not_configured` in `crates/marlowe-provider/tests/`: grep `crates/*/src/` for each `ModelRoute::` variant and assert every variant reachable in the configured table has at least one non-test construction, printing the per-variant count.

### **`CallLimits` has public fields and no constructor, so `route` gains a second way in that bypasses the profile.** `pub struct CallLimits { pub max_output_tokens: u64, pub route: ModelRoute }` is constructed as a struct literal at ~8 sites across `marlowe-daemon/tests`, `marlowe-openrouter/examples`, `marlowe-loop/tests` and `marlowe-daemon/tests/context_window.rs`. Adding a public `route` means any of them — and any future driver — can name a route the run's profile did not. That is the same objection profile.rs:300-322 makes about holding the granted egress set on the `Run`: the invariant ("a call's model is the one this run's profile declares") would be bypassable rather than enforced, and every profile test stays green.

- **Why:** #12's family with a struct literal instead of `serde`. `Budget::call_limits` is meant to be the one place the pair is assembled; a public field means it is not.
- **Fix:** Make the field private with an accessor: `pub struct CallLimits { max_output_tokens: u64, route: ModelRoute }`, `pub fn max_output_tokens(&self) -> u64`, `pub fn route(&self) -> ModelRoute`, and `CallLimits::for_test(tokens, route)` behind `#[cfg(any(test, feature = "test-util"))]` for the eight existing literals. `Budget::call_limits(&self, spent, route)` is then the only production constructor. Assert it: `crates/marlowe-loop/tests/call_limits_one_constructor.rs` greps `crates/*/src/` for `CallLimits {` and asserts exactly one hit, in `budget.rs`. Mutation: build a `CallLimits` literal in `ollama.rs` — count reads 2, red.

### **The receipt is named as the mitigation for `parse_role`'s total default and does not carry the role.** The design says *"the spawn receipt says which role was actually granted — so a spawner naming the fourth role before the enum has it is TOLD it did not land."* The receipt is `engine.rs:2755`: `"[spawned] tools: {granted_tools} · budget: {} tokens · orphan: {} · returns: {}"`. No role, no disposition. The claimed mitigation has no site.

- **Why:** The design's own argument for accepting an unrecognised-role-takes-Worker default is that the receipt closes it — CLAUDE.md's "defaults that make a mismatch unobservable" family. Without the receipt line, the default *is* unobservable, and this is the exact reasoning ADR-057 §2 used to legitimise six other defaults.
- **Fix:** Name the edit. `engine.rs:2755`'s format string becomes `"[spawned] role: {role} · {disposition} · tools: {granted_tools} · budget: {} tokens · orphan: {} · returns: {}"`, with both rendered from the harness's own enums (never from `args`). Assert it in `crates/marlowe-loop/tests/spawn_and_budget.rs::a_spawn_receipt_names_the_role_that_was_actually_granted`: emit `model_role: "conductor"` (an unrecognised word), assert the parent's window contains `role: worker`. Mutation: drop the role from the format string — red.

### **Every named profile constructor needs a level and the design assigns one to only two of five.** `CapabilityProfile::new` gains a seventh argument; the design names `quarantined_reader() -> ToolSpawned` and implies `Engine::spawn` supplies one. It never says what `consolidation()` (profile.rs:141, holds `recall`+`remember` — cannot be Master, cannot be ToolSpawned since its set is non-empty), `interactive()` (profile.rs:173), `interactive_with()` (profile.rs:257, the daemon's root at daemon.rs:1044 and 2616), or `narrowed()` (profile.rs:331, hardcodes `ModelRoute::Worker` and has **zero production callers**) receive. Four guesses at a §13-guarded constructor.

- **Why:** The seventh argument is the whole mechanism; leaving four of its call sites unspecified is where the level becomes whatever the implementer typed. And `narrowed`'s hardcoded `ModelRoute::Worker` is a **second place the route is decided** that the design never reconciles with `SpawnRequest.role` — if `narrowed` ever gains a production caller, it silently resets the route.
- **Fix:** Pin all five in the design: `quarantined_reader() -> ToolSpawned`; `consolidation() -> Worker`; `interactive() -> Secretary`; `interactive_with() -> Secretary`; `narrowed(tools, level)` takes the level explicitly and its `ModelRoute::Worker` hardcode becomes `self.model_route` (a narrowing does not change which model serves the run — and record in the doc comment that this function has no production caller, so the change is currently unobservable). Assert: `crates/marlowe-loop/tests/agent_levels.rs::every_named_profile_declares_its_level`, a wildcard-free `match` over `AgentLevel` mapping each level to the constructor(s) that produce it, so a sixth variant is a compile error.

### **Two scope decisions taken silently.** (1) **The Secretary gets no tool restriction.** The design's level match has `AgentLevel::Secretary` falling into `_ => {}`, so `interactive()` — `bash`, `edit`, `write`, `web`, all twelve — is a valid Secretary. M3-DESIGN §1's table says the Secretary holds a *"full conversational set"*, which is not the same phrase as `interactive()`'s twelve, and §2's liaison pattern exists because Marlowe must not do the work himself. Whether §1.2's structural rule extends upward to level 1 is a question §1 does not answer, and `_ => {}` answers it "no" without saying so. (2) **The design prescribes five edits to `crates/marlowe-daemon/src/daemon.rs`, which another agent is editing in this session.** Hazard forms 3, 4 and 5 in CLAUDE.md's parallel-sessions table, and the design's five line numbers are already stale (see above) which is precisely what a concurrent edit produces.

- **Why:** (1) is a boundary question the human owns under §13's spirit — it decides whether Marlowe can `bash`. Answering it with a wildcard arm is how a decision gets made by nobody. (2) is the shape that produced a false build-break report in this project twice in one day.
- **Fix:** (1) Make it explicit and escalate: either add `AgentLevel::Secretary => { /* full conversational set, deliberately unrestricted — §1's table */ }` as a named arm with the sentence in it, or add a `SECRETARY_TOOLS` restriction. Either way it goes in `open_for_human` as *"does §1.2's structural rule apply to level 1?"*, with the observation that `interactive()` currently holds `bash` and `edit`. Do not leave it as `_`. (2) Session C makes **no** daemon.rs edit. The `Daemon::routing()` extraction is deferred to a turn where daemon.rs is not held by another session, or handed to that session as a request; C ships `SpawnRequest.role` → `engine.rs:2644` → `CallLimits` → `ollama.rs:300` (three unguarded-by-the-other-session files) and records in STATE.md that the chain terminates in `uniform` until the daemon edit lands, with `a_child_spawned_at_the_summarizer_role_...` marked `#[ignore]` and the reason named. An ignored test whose header says why is honest; a green one over an incomplete chain is #16.

### **"The tree is four deep by construction" is false of the product, and the claim reads identically either way.** `Engine::condense_batch` builds its quarantined child at `crates/marlowe-loop/src/engine.rs:2146` with a direct `Run::child(..., CapabilityProfile::quarantined_reader(), ...)` — it never goes through `Engine::spawn` and would never call `AgentLevel::child_of`. So a Worker at level 4 that holds `web` does produce a level-5 `ToolSpawned` reader, exactly as §1's table intends, and `child_of(Worker, _) = Err` says nothing about it. The design's claim is true only of model-initiated spawns and is stated unqualified.

- **Why:** Small on its own, load-bearing in combination: the design uses "four deep by construction" to argue that `Budget.depth` never has to be zero (its #17 defence). `Budget.depth` still bounds the harness path, and `depth` for a level-4 worker's quarantined child is where a `0` would actually be tempting.
- **Fix:** State it precisely in the `child_of` doc comment: *"Total over MODEL-INITIATED spawns. The harness's own children — `quarantined_reader` at engine.rs:2146, SCOPED-MEMORY §4's fact extractor — are built by named constructor and are not routed through here; §1's level 5 sits under any of levels 1-4. `Budget.depth` still bounds that path and is never 0."* Add to `agent_levels.rs`: assert `Budget::interactive().depth >= 1` and that no production `Budget` literal sets `depth: 0` or `subagents: 0` (grep `crates/*/src/` for `depth: 0`, assert 0 hits, print the count) — a #17 guard whose input is the source tree, not a list.

## STRENGTHENED — WHAT GETS BUILT

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

## Original recommendation

Two orthogonal axes, two types, never one field. `AgentLevel` (position in the org chart) is a private field on `CapabilityProfile`, **derived** by `AgentLevel::child_of(parent_level, disposition)` — a wildcard-free table whose Secretary row returns `TopAgent` for both dispositions (§1.1) and whose `Worker` row returns `Err`, so the tree is four deep by construction rather than by a `depth` counter. §1.2's trap is answered in `CapabilityProfile::new`: a `Master` exposing a tool outside `MANAGEMENT_TOOLS` is a **load-time error**, and every budget dimension stays ≥ 1. "A worker can never address Marlowe" is enforced by the **absence of a recipient parameter** on `ask`/`escalate` plus an `EscalationTarget` enum with no Secretary variant — the ADR-057 `adopt` precedent: a recipient that cannot be supplied cannot be named. `SpawnRequest` gains `role: ModelRoute` (the type that already exists — do not invent a second `ModelRole`) and `disposition: Disposition`; both are read from `args`, both are declared `ArgumentRole::Target`, and both join `composes_spawn_targets`, which answers AGENT-DIRECTORY §3 item 4 with one line at an existing latch. **The blocking finding: `CapabilityProfile::model_route` has ZERO readers under `crates/` today** (`grep -rn "model_route()"` → 0 hits; `ollama.rs:300` hardcodes `Orchestrator`) **and `Routing::new` has zero production callers** (every site is `Routing::uniform(&self.config.model)`). Adding `role` without completing the four-link reader chain — `SpawnRequest.role` → `engine.rs:2654` → `CallLimits.route` → `ollama.rs:300` → a real `Routing::new` — ships instance #16 for the third time in one code path. The field lands with the chain or it does not land.

### Types

```rust
// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/profile.rs   ***§13-GUARDED — HUMAN APPROVAL REQUIRED***
// ─────────────────────────────────────────────────────────────────────────────

/// M3-DESIGN §1. **Position in the organisation, not capability.** Capability is the
/// `ExposedSet`; this is what constrains which sets are constructible.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLevel { Secretary, TopAgent, Master, Worker, ToolSpawned }

/// §1.1's one question: *can one agent do this alone?* The single bit a spawner declares.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition { Work, Manage }

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("a {parent:?} cannot create a {wanted:?} child: Marlowe creates only top-agents, a \
         master creates only workers, and a worker creates nothing")]
pub struct LevelRefusal { pub parent: AgentLevel, pub wanted: Disposition }

impl AgentLevel {
    /// **Total over the level axis, no wildcard.** A sixth level fails to compile here.
    /// It NEVER returns `ToolSpawned`: that level is reachable only through the harness's own
    /// named constructors, so no model call can produce one. Withheld structurally (#17).
    pub fn child_of(parent: AgentLevel, d: Disposition) -> Result<AgentLevel, LevelRefusal> {
        use AgentLevel::*; use Disposition::*;
        match (parent, d) {
            // §1.1: BOTH arms answer TopAgent. The disposition still decides the tool class;
            // it does not decide the level. "Marlowe spawns exactly one kind of thing."
            (Secretary, Manage) | (Secretary, Work) => Ok(TopAgent),
            (TopAgent, Manage) => Ok(Master),
            (TopAgent, Work)   => Ok(Worker),
            (Master,   Work)   => Ok(Worker),
            // Depth 4 is structural: no Master-from-Master, no Worker-spawns-anything.
            (Master, Manage) | (Worker, _) | (ToolSpawned, _) =>
                Err(LevelRefusal { parent, wanted: d }),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CapabilityProfile {
    exposed_tools: ExposedSet,
    egress: EgressPolicy,
    interrupt: InterruptPolicy,
    model_route: ModelRoute,
    level: AgentLevel,          // NEW — private, constructor-validated, serde-routed
    may_write_memory: bool,
    reads_untrusted: bool,
}

// Three new ProfileError variants, all load-time:
#[error("a {level:?} profile exposes `{tool}`, which is not in MANAGEMENT_TOOLS. M3-DESIGN §1.2: \
         a master holds no working tools STRUCTURALLY — the tool is absent from the set, not \
         forbidden by instruction, and never expressed as a counter of zero (instance #17)")]
MasterHoldsWorkingTool { level: AgentLevel, tool: ToolId },

#[error("a tool-spawned agent exposes {count} tool(s). §1.4: no tools, no persistence, destroyed \
         on return. Strictly wider than the quarantine check — the fact extractor is tool-spawned \
         and does NOT set `reads_untrusted`, so it is covered by nothing today")]
ToolSpawnedWithTools { count: usize },

#[error("a {level:?} profile holds `run`, the create grant. §1: a worker spawns nothing")]
CreateGrantBelowMaster { level: AgentLevel },

impl CapabilityProfile {
    pub fn new(
        exposed_tools: ExposedSet, egress: EgressPolicy, interrupt: InterruptPolicy,
        model_route: ModelRoute, level: AgentLevel,
        may_write_memory: bool, reads_untrusted: bool,
    ) -> Result<Self, ProfileError> { /* existing three checks, then: */
        match level {
            AgentLevel::ToolSpawned if !exposed_tools.is_empty() =>
                return Err(ProfileError::ToolSpawnedWithTools { count: exposed_tools.len() }),
            AgentLevel::Master => {
                for t in exposed_tools.iter() {
                    if !marlowe_tools::MANAGEMENT_TOOLS.contains(&t.as_str()) {
                        return Err(ProfileError::MasterHoldsWorkingTool { level, tool: t.clone() });
                    }
                }
            }
            AgentLevel::Worker | AgentLevel::ToolSpawned
                if exposed_tools.contains(&ToolId::new("run")) =>
                return Err(ProfileError::CreateGrantBelowMaster { level }),
            _ => {}
        }
        /* ... */
    }

    pub fn level(&self) -> AgentLevel { self.level }
    /// **The create grant IS holding `run`.** One definition, read by `Engine::spawn`.
    pub fn may_create_agents(&self) -> bool {
        self.level.may_hold_create_grant() && self.exposed_tools.contains(&ToolId::new("run"))
    }
}

// `Raw` gains `level: AgentLevel` with NO `#[serde(default)]`. A checkpoint written before
// Session C fails to deserialize with a named serde error. Prefer a load-time error to a
// default that makes the mismatch unobservable.

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/driver.rs   ***§13-GUARDED — HUMAN APPROVAL REQUIRED***
// ─────────────────────────────────────────────────────────────────────────────

pub struct SpawnRequest {
    // ... task, contract, orphan, share, grant_tokens, tools, tools_declared, reads_untrusted
    /// **Which model serves the child.** `ModelRoute`, not a second enum: routing.rs's header
    /// already says it "names a task role and never a model or a provider", and it is already
    /// the field on `CapabilityProfile` that `Engine::spawn` hardcodes to `Worker`. This
    /// parameterises an existing constant rather than adding machinery.
    ///
    /// A **Target** under ADR-023: it decides capability and spend, and both a downgrade
    /// ("make the system dumber before an attack") and an upgrade ("exhaust the budget") are
    /// attacker-useful. AGENT-DIRECTORY §3 item 4, answered rather than omitted.
    ///
    /// Default `Worker` — the CHEAP end. A default at the expensive end would put every
    /// unnamed child on the 9B with nothing observing it.
    pub role: ModelRoute,
    /// §1.1. A **Target**: it decides whether the child may hold the create grant.
    pub disposition: Disposition,
}

/// Total, per ADR-057. **An unrecognised role takes the cheap default and the spawn receipt
/// says which role was actually granted** — so a spawner naming the fourth role before the
/// enum has it is TOLD it did not land, instead of a default arriving unobserved.
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
// In from_args:  role: parse_role(text("model_role")),
//                disposition: parse_disposition(text("disposition")),
// NOT withheld like `share`/`reads_untrusted` (ADR-057 §5): the requirement is literally
// "the spawner names the model", and the spawner of a delegated task is a model. Withholding
// it makes the feature unreachable and pushes it back to G as a contract change.

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/budget.rs   (NOT guarded — the deliberate carrier choice)
// ─────────────────────────────────────────────────────────────────────────────

pub struct CallLimits {
    pub max_output_tokens: u64,
    /// **Which model serves this call.** Until this field, `CapabilityProfile::model_route`
    /// had zero readers under `crates/` and `OllamaDriver::request_body` hardcoded
    /// `ModelRoute::Orchestrator`. `CallLimits` is the carrier because it already crosses to
    /// every provider and adding a field to it changes NO `ModelDriver` signature — so the
    /// §13-guarded diff stays confined to `SpawnRequest`.
    pub route: ModelRoute,
}
impl Budget {
    pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens, route }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-loop/src/run.rs   (NOT guarded)
// ─────────────────────────────────────────────────────────────────────────────

/// Where an escalation goes. **There is no `Secretary` variant, and that absence IS the
/// enforcement of §3.2**: Marlowe cannot be an escalation recipient because no value of this
/// type can name him. He receives a notification carrying `{severity, category, agent}` and
/// no free text and no artifact — §2.3's typed record, with nothing to read.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EscalationTarget {
    /// §3.1: starts at the direct master, approved at each level.
    Master(RunId),
    /// §3.1: only a top-agent reaches the user, and the window is the user and the top-agent.
    Human { via: RunId },
}

/// **Total over `AgentLevel`, no wildcard.** A pure function of the run tree — there is no
/// argument anywhere in which an agent names its recipient.
pub fn escalation_target(level: AgentLevel, run: RunId, parent: Option<RunId>)
    -> Option<EscalationTarget>
{
    match level {
        AgentLevel::TopAgent => Some(EscalationTarget::Human { via: run }),
        AgentLevel::Master | AgentLevel::Worker => parent.map(EscalationTarget::Master),
        AgentLevel::Secretary => None,   // he holds the conversation; he speaks, he does not escalate
        // Belt and braces, SAID SO: its set is empty, so it holds no `ask` to reach this with.
        // This arm is totality, not a defence, and must not be counted as one.
        AgentLevel::ToolSpawned => None,
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// crates/marlowe-tools/src/builtin.rs   (NOT guarded)
// ─────────────────────────────────────────────────────────────────────────────

/// M3-DESIGN §1.2's master set, as names. **The one definition.** It lists only management
/// tools that EXIST; it grows in Session C as `communicate`, `todo`, `budget` and the meeting
/// controls land. `recall`/`remember`/`web`/`read` are deliberately absent: a master that can
/// read the repo will read the repo.
pub const MANAGEMENT_TOOLS: [&str; 2] = ["run", "ask"];

// `ask` and the new `escalate` registrations declare NO parameter with a recipient. Every
// parameter is `ArgumentRole::Payload` (severity, category, artifact_ref). ADR-057 §2's
// precedent, verbatim: "a policy whose argument cannot be supplied cannot be declared."
```

### Enforcement sites

- `CapabilityProfile.level: AgentLevel` -> **crates/marlowe-loop/src/profile.rs :: CapabilityProfile::new (three match arms); crates/marlowe-loop/src/engine.rs :: Engine::spawn (calls AgentLevel::child_of at the site that today hardcodes ModelRoute::Worker, engine.rs:2654); crates/marlowe-loop/src/run.rs :: escalation_target** | breaks: A master could be constructed holding `edit`; §1.2 becomes an instruction instead of a structure. A worker could be spawned as a direct child of Marlowe, violating §1.1. escalation_target loses its only discriminator and every level routes identically.
- `CapabilityProfile::may_create_agents() — the create grant IS holding `run`` -> **crates/marlowe-loop/src/engine.rs :: Engine::spawn, as its FIRST refusal, before the task check** | breaks: The gap that exists today: `control_step` (ollama.rs:1045) maps a `run` tool call to ModelStep::Spawn without consulting the ExposedSet, and Engine::spawn never checks it either — ModelStep::Spawn does not reach adjudicate.rs:288, which is where the exposure check lives. This is SECURITY-AUDIT H2's exposure-check gap, applied to `run`. Without this reader the create grant is a declared control nothing reads (#16), and a worker that hallucinates a `run` call spawns.
- `SpawnRequest.role: ModelRoute` -> **crates/marlowe-loop/src/engine.rs :: Engine::spawn — passed to CapabilityProfile::new in place of the hardcoded ModelRoute::Worker at engine.rs:2654; and crates/marlowe-loop/src/engine.rs :: composes_spawn_targets (engine.rs:3237)** | breaks: Every child runs on whatever `Routing` answers for `Worker` regardless of what the spawner asked for, and a latched run can choose the child's model — the AGENT-DIRECTORY §3.4 downgrade/upgrade attack, unguarded.
- `SpawnRequest.disposition: Disposition` -> **crates/marlowe-loop/src/engine.rs :: Engine::spawn — the only argument to AgentLevel::child_of besides the parent's level; and composes_spawn_targets** | breaks: Every child becomes a Worker, masters cannot be created at all, and the create grant is unreachable — §1's level 3 stops existing. Note the deliberate cross-check: a spawn declaring `Work` while naming `run` in `exposed_tools` is refused by CapabilityProfile::new's CreateGrantBelowMaster, so the declaration and the tool list cannot silently disagree.
- `CallLimits.route: ModelRoute` -> **crates/marlowe-provider/src/ollama.rs :: OllamaDriver::request_body (line 300, replacing the hardcoded `marlowe_loop::ModelRoute::Orchestrator`); crates/marlowe-provider/src/llamacpp.rs; crates/marlowe-openrouter/src/driver.rs** | breaks: The chain ends one link short of the wire and `role` becomes instance #16 for the third time in this path. This is the field that makes the model name on the outbound request a function of the spawn.
- `CapabilityProfile.model_route (EXISTING, currently unread)` -> **crates/marlowe-loop/src/engine.rs:794 — `run.budget.call_limits(&run.spent, run.profile.model_route())`. This is the accessor's FIRST reader: `grep -rn "model_route()" --include=*.rs crates/` returns ZERO hits at HEAD 186b5d5.** | breaks: It is already removed, in effect. The field is set at four construction sites, has a public accessor, is pinned in CONTRACTS §5, and nothing consults it; profile.rs:456 asserts `"model_route": "worker"` — the VALUE of the field, not the fate of a byte. Identical in shape to `inline_threshold_bytes`.
- `Routing::new — role → model table` -> **crates/marlowe-daemon/src/daemon.rs — replacing `Routing::uniform(&self.config.model)` at :1196, :1271, :1436, :1780, :1867. `Routing::new` has ZERO production callers at HEAD; every one is `uniform`, which collapses all three roles onto one model.** | breaks: ADR-008's tiered routing stays declared and unshipped, and routing.rs:118-121 (`model_for(Orchestrator) == "qwen3.5:9b"` …) stays green on a build where no production path ever constructs a three-model table. The whole reader chain terminates in a table that answers the same string for every role.
- `INVARIANT: Master ⟹ exposed_tools ⊆ MANAGEMENT_TOOLS (§1.2, expressed as absence, never as a counter)` -> **crates/marlowe-loop/src/profile.rs :: CapabilityProfile::new, the AgentLevel::Master arm; MANAGEMENT_TOOLS is defined once in crates/marlowe-tools/src/builtin.rs** | breaks: A master with `edit` is constructible, and §1.2's stated failure — "not because it is disobedient, because it is capable and the work is right there" — is live. Note what is NOT done: no budget dimension is set to 0. Budget::exhausted compares `spent >= budget`, so `edit_calls: 0` fires on iteration one (instance #17).
- `INVARIANT: ToolSpawned ⟹ exposed_tools.is_empty() (§1.4)` -> **crates/marlowe-loop/src/profile.rs :: CapabilityProfile::new, the AgentLevel::ToolSpawned arm** | breaks: This is strictly WIDER than the existing `reads_untrusted ⟹ empty` check and that width is the point: SCOPED-MEMORY §4's fact extractor is a tool-spawned agent that does NOT read untrusted content, so today nothing would stop it being constructed with tools.
- `INVARIANT: a worker can never address Marlowe (§3.1)` -> **Two independent sites. (a) crates/marlowe-tools/src/builtin.rs — the `ask`/`escalate` registrations declare no recipient parameter, so there is no argument in which any agent can name him. (b) crates/marlowe-loop/src/run.rs :: escalation_target — the EscalationTarget enum has no Secretary variant, and the TopAgent arm returns Human{via}, never Master(parent), even though a top-agent's parent IS the secretary.** | breaks: Deleting (a) lets a compromised worker name the secretary run id and the routing function has to defend against it — a check instead of a structure. Deleting (b) makes a top-agent's escalation route to `Master(secretary_run)`, which is §2.1's exact catastrophe: Marlowe is a permanent run whose floor latches monotonically, so one finding costs him composed targets for his life.
- `INVARIANT: AgentLevel::child_of never returns ToolSpawned; the tree is 4 deep` -> **crates/marlowe-loop/src/profile.rs :: AgentLevel::child_of — the wildcard-free match itself. ToolSpawned is produced only by CapabilityProfile::quarantined_reader() and its siblings, which the harness builds in Engine::condense_batch.** | breaks: Depth would have to be bounded by Budget.depth, which is a counter — and expressing "may not spawn" as `depth: 0` is instance #17. Bounding it in the level table means the numeric depth budget keeps meaning what it means and never has to be zero.

### Rejected

- **Express "a master holds no working tools" as a budget: `edit_calls: 0`, or `tool_calls: 0` on a master's Budget.** - Instance #17, named in M3-DESIGN §1.2 as the trap. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on the first iteration: the master pauses before its first model call while looking perfectly configured. That is exactly what silently stopped the quarantine reading anything at all (ADR-041). Capability is withheld structurally — the tool is not in the set — and every counter stays at 1 or above.
- **Put `level` on `Run` beside the profile, where `trust_floor` already lives.** - The argument is `grant_egress_host`'s, verbatim (profile.rs:190-215): the invariant "a master's set contains only management tools" is a statement ABOUT the exposed set, and the exposed set lives inside `CapabilityProfile` behind a validating constructor. Hold the level on the `Run` and consult it beside the profile and the invariant is bypassed rather than enforced — a `Master` run could be constructed with an `edit`-holding profile, and every profile test would stay green. `Run` also has no validating constructor to route `Deserialize` through, so a checkpoint could restore a master with working tools (#12).
- **A new `ModelRole` enum on `SpawnRequest`, separate from the existing `ModelRoute`.** - Two definitions of one thing — the two-sides-silently-disagree shape this project has logged repeatedly. `ModelRoute` is already "a task role, declared in `CapabilityProfile`, never a model or a provider" (ADR-008, routing.rs header), it is already the field the child's profile is built with, and `Engine::spawn` already hardcodes a value for it at engine.rs:2654. Using it means `role` parameterises an existing constant rather than adding a second vocabulary that `Routing` would then need two tables for.
- **`role: String` (an open set), so the fourth role needs no code change at all.** - Three failures. (1) A typo routes to a default nobody chose — "defaults that make a mismatch unobservable", four bugs in this project already. (2) `Routing` loses exhaustiveness: a role with no model in the table has to fall back, and the fallback is the expensive model or a runtime error at call time instead of load time. (3) AGENT-DIRECTORY §2a's per-role admission queue keys on the role; a `String` key makes the queue's key space attacker-influenced and unbounded. A closed enum plus a total `parse_role` gets the same reachability with a load-time compile error when the table is incomplete.
- **Withhold `role` from `args` the way ADR-057 §5 withholds `share` and `reads_untrusted`.** - §5 withholds those two because a model naming them reaches a SECURITY control — `reads_untrusted` sets the quarantine profile, `share` sizes a slice. `role` is different in kind: the requirement is literally "the spawner names the model" (AGENT-DIRECTORY §2), and the spawner of a delegated task is a model. Withholding it makes the feature unreachable and pushes the whole thing into Session G as a pinned-contract change, which is precisely what the roadmap's item (4) exists to avoid. The security concern is answered instead by declaring it a Target, which reuses the latch already at the spawn site and costs one disjunct.
- **Add `role` to `SpawnRequest` in C and wire the reader chain in G, when the configuration window exists.** - Instance #16 for the third time in one code path, on top of two live ones (`model_route` unread, `Routing::new` uncalled). The green-and-vacuous test writes itself: `assert_eq!(req.role, ModelRoute::Summarizer)` passes on a build where the child runs on the orchestrator model. The whole point of pinning the shape in C is that G becomes a window; a shape pinned without reachability is CONTRACTS §12.1's `ingest_external` situation, which was only honest because it SAID so. A role pin that says the same thing has pinned nothing useful.
- **Let a child inherit its parent's `role`, mirroring how `Run::child` inherits `trust_floor`.** - Inheritance is right for a floor because a floor may only fall. A model choice may go either way, and inheriting upward-capability is the failure: every descendant of a top-agent would run the 9B. Measured today on this machine, the three roles co-resident leave 1,053 MiB free — there is no room for a second 9B, so inheritance would either evict (≈10.5 s cold reload, AGENT-DIRECTORY §2's own inversion) or run the whole tree on one model. Chosen-by-spawner with the CHEAP default is the shape where forgetting the field costs nothing.
- **Derive `disposition` from whether `exposed_tools` names `run`, so there is one field instead of two.** - That is inference, and §5 says declared at spawn, never inferred (the same argument ADR-057's amendment used to make `exposed_tools` required rather than defaulted). Keeping both and letting `CapabilityProfile::new` refuse the disagreement — `Work` + `run` in the tool list → `CreateGrantBelowMaster` — is strictly better: the two cannot silently disagree, and the refusal names which one to change.

### Tests

- `a_master_cannot_hold_a_working_tool` in `crates/marlowe-loop/tests/agent_levels.rs`
  - asserts: For EACH of `bash`, `read`, `write`, `edit`, `glob`, `grep`, `web`, `recall`, `remember`, `use` — enumerated, not sampled — `CapabilityProfile::new(ExposedSet::new(vec![t]), DenyAll, Unattended, Worker, AgentLevel::Master, false, false)` is `Err(MasterHoldsWorkingTool { tool: t })`, and the same set at `AgentLevel::Worker` is `Ok`. Plus the #17 control in the same test: the master profile's companion `Budget` has every one of its six dimensions >= 1.
  - red on: Delete the `AgentLevel::Master` arm from `CapabilityProfile::new` (the ten Err assertions go green-to-red). Separately: express the rule as `Budget { tool_calls: 0, .. }` on the master instead — the dimension assertion turns red, which is the point of carrying it in this test.
- `management_tools_and_working_tools_are_disjoint_and_the_list_has_not_shrunk` in `crates/marlowe-loop/tests/agent_levels.rs`
  - asserts: `MANAGEMENT_TOOLS` equals the literal `["run", "ask"]` written out IN THE TEST, independent of the constant; and `MANAGEMENT_TOOLS ∩ BUILTIN_TOOLS_THAT_ACT == ∅` where the second list is also written out literally. Every name in `MANAGEMENT_TOOLS` resolves to a registered tool in `ToolRegistry::builtin()`.
  - red on: Add `"edit"` to `MANAGEMENT_TOOLS` — red on the disjointness. REMOVE `"ask"` from it — red on the literal, which is the instance #19 defence: the previous test's input IS `MANAGEMENT_TOOLS`, so it cannot see that list shrink, and a shrunk list makes the master rule quietly more restrictive with no failure anywhere.
- `marlowe_only_ever_creates_a_top_agent` in `crates/marlowe-loop/tests/agent_levels.rs`
  - asserts: `AgentLevel::child_of(Secretary, Manage) == Ok(TopAgent)` AND `child_of(Secretary, Work) == Ok(TopAgent)` — the same answer for both inputs. Then the whole table: `(TopAgent, Manage) -> Master`, `(TopAgent, Work) -> Worker`, `(Master, Work) -> Worker`, and `(Master, Manage)`, `(Worker, *)`, `(ToolSpawned, *)` all `Err`. And: no input produces `ToolSpawned`.
  - red on: Change `(Secretary, Work) => Ok(Worker)` — the tempting shortcut, and it makes a worker a direct report of the secretary. Or add a `(Master, Manage) => Ok(Master)` arm, which makes the tree unbounded in depth.
- `a_worker_can_never_address_marlowe` in `crates/marlowe-loop/tests/escalation_routing.rs`
  - asserts: Build a real four-level chain of `Run`s (Secretary root, TopAgent child, Master grandchild, Worker great-grandchild) via `Run::child`. Then: `escalation_target(Worker, w, Some(m)) == Some(Master(m))`; `escalation_target(Master, m, Some(t)) == Some(Master(t))`; `escalation_target(TopAgent, t, Some(secretary_id)) == Some(Human { via: t })` and `!matches!(.., Master(_))` even though its parent IS the secretary; and for every level, `escalation_target(..) != Some(Master(secretary_id))`.
  - red on: Change the `TopAgent` arm to `parent.map(EscalationTarget::Master)` — one plausible-looking simplification that would route the escalation to Marlowe and cost him composed targets permanently (§2.1).
- `no_escalation_tool_has_a_recipient_parameter` in `crates/marlowe-tools/tests/escalation_manifest.rs`
  - asserts: For `ask` and `escalate` in `ToolRegistry::builtin()`: no parameter is `ArgumentRole::Target`, and no parameter name is in `["to","recipient","agent","run","addressee","target"]`. Asserts on the manifest the registry actually holds, not on a literal in the test.
  - red on: Add `documented("recipient", ArgumentRole::Target, Text, false, ...)` to the `escalate` registration. This is the structural half of the rule above — ADR-057 §2's `adopt` precedent: a recipient that cannot be supplied cannot be named, so the routing function never has to defend against one.
- `a_run_without_the_create_grant_cannot_spawn` in `crates/marlowe-loop/tests/spawn_and_budget.rs`
  - asserts: Drive a real `ModelStep::Spawn` through `Engine::run` on a run whose `ExposedSet` does NOT contain `run`. Assert: the spawn is refused with a message naming the create grant, `EventKind::RunSpawned` appears ZERO times in the recorder, and the parent's window holds the refusal. THIS TEST FAILS AT HEAD 186b5d5 — `control_step` (ollama.rs:1045) maps `run` to `ModelStep::Spawn` without consulting the exposed set, and `Engine::spawn` never checks it either, because `ModelStep::Spawn` does not reach `adjudicate.rs:288`.
  - red on: Delete the `run.profile.may_create_agents()` check from the top of `Engine::spawn`. Assert on the RunSpawned count, not on the refusal string — a test that only checks the message would stay green if the refusal were emitted AND the child spawned anyway.
- `a_child_spawned_at_the_summarizer_role_is_called_on_the_summarizer_model` in `crates/marlowe-provider/tests/model_role_reaches_the_wire.rs`
  - asserts: The END of the reader chain, asserted on the bytes. Build `Routing::new("role-orch", "role-work", "role-summ")`, spawn a child with `role: Summarizer`, and assert `OllamaDriver::request_body(...)["model"] == "role-summ"` for the child's call and `"role-orch"` for the parent's. Prints the two model strings so the run has a number to read.
  - red on: Restore the hardcoded `marlowe_loop::ModelRoute::Orchestrator` at ollama.rs:300 — both assertions read `"role-orch"`. Or drop `req.role` on the floor in `Engine::spawn` and keep `ModelRoute::Worker` at engine.rs:2654 — the child reads `"role-work"`. The proxy version to NOT write is `assert_eq!(req.role, Summarizer)`, which is green under both mutations.
- `three_configured_roles_resolve_to_three_models` in `crates/marlowe-daemon/tests/role_routing.rs`
  - asserts: Build the daemon's routing from a config naming three distinct local tags and assert `routing.models().len() == 3` and that `model_for` answers a different string for each role. Prints the three tags.
  - red on: Revert the daemon to `Routing::uniform(&self.config.model)` — `models().len()` reads 1. This is the test that stops ADR-008's tiered routing being declared-and-unshipped; `routing.rs:118-121` cannot catch it because it constructs its own three-model table inside a unit test.
- `a_latched_run_cannot_choose_a_childs_model_or_disposition` in `crates/marlowe-loop/tests/adr023_spawn_targets.rs`
  - asserts: Unit half: `composes_spawn_targets` is `false` for a request at every default (`role: Worker`, `disposition: Work`, no tools, no grant, `orphan: Terminate`) and `true` when ONLY `role` moves, and `true` when ONLY `disposition` moves. Loop half: latch a run's floor to `UntrustedContent`, emit a spawn naming `model_role: orchestrator`, assert refused with the existing composed-targets message and zero `RunSpawned`.
  - red on: Remove the `req.role != ModelRoute::Worker` disjunct from `composes_spawn_targets` (engine.rs:3237) — the unit half's role-only case reads `false` and the loop half spawns. This is AGENT-DIRECTORY §3 item 4 answered as an executable check rather than by omission.
- `a_level_cannot_be_widened_by_deserialization` in `crates/marlowe-loop/tests/agent_levels.rs`
  - asserts: `serde_json::from_str::<CapabilityProfile>(r#"{"exposed_tools":["edit"],"egress":"deny_all","interrupt":"unattended","model_route":"worker","level":"master","may_write_memory":false,"reads_untrusted":false}"#)` is an error naming the management-tool rule. And a JSON with `level` ABSENT is an error naming the missing field — no `#[serde(default)]`.
  - red on: Add `#[serde(default)]` to `level` in `Raw` (the absent-field case goes green and every pre-C checkpoint silently restores as `Secretary` or whatever the default is). Or replace the hand-written `Deserialize` with a field-wise derive — instance #12, at the new field.
- `terminate_appears_in_no_agents_request_body_at_any_level` in `crates/marlowe-provider/tests/terminate_is_invisible.rs`
  - asserts: M3-DESIGN §11's acceptance row, now enumerable because levels exist. A local `fn profile_for(level: AgentLevel) -> CapabilityProfile` matches all five levels with NO wildcard; the test builds a request body per level and asserts `"TERMINATE"` occurs 0 times in the serialized body and that no exposed set contains it. Prints the occurrence count (0) per level.
  - red on: Add a `terminate` tool to `MANAGEMENT_TOOLS`, or put the word in any level's system prompt. A sixth `AgentLevel` variant fails to COMPILE in `profile_for`, which is the #19 defence — the test's coverage cannot silently shrink because its input is an exhaustive match, not a list.
- `the_role_table_leaves_room_for_the_embedder` in `crates/marlowe-daemon/tests/role_residency.rs (ignored by default; run explicitly)`
  - asserts: After the daemon loads its configured role table, read `GET /api/ps` and assert `free_vram_mib >= EMBEDDER_RESERVE_MIB`. Prints total, resident-per-model and free. Established fact this defends: three roles resident today leave 1,053 MiB free, and ADR-044 resolves the embedder's provider against FREE VRAM AT LOAD — so it falls to CPU with a correct-looking log line. AGENT-DIRECTORY §2's "leaving headroom" is contradicted by measurement.
  - red on: Add a fourth 9B-class model to the default role table, or point two roles at `marlowe-dawn:9b-super`. The paired control is the one command that says what actually resolved: `target/release/marlowe.exe --eval-adapter --embedder-model models/jina-embeddings-v2-small-en --reranking off` printing `CUDAExecutionProvider` vs `CPUExecutionProvider` — read from the SHIPPED binary, never from `cargo run --example`.

### Contract impact

Three changes, and two of them are pinned-contract acts that are the human's under M3-D1's precedent.

**1. CONTRACTS §5 — `CapabilityProfile` gains a seventh field.** `pub level: AgentLevel`, with `AgentLevel` pinned BY MEMBERSHIP (five variants) and the new load-time errors stated alongside the existing `reads_untrusted && !exposed_tools.is_empty()` sentence: `ToolSpawned ⟹ exposed_tools.is_empty()`, `Master ⟹ exposed_tools ⊆ MANAGEMENT_TOOLS`, `Worker|ToolSpawned ⟹ !exposed_tools.contains("run")`. Same register as the existing line — a type invariant rather than a guideline.

**2. CONTRACTS §5 — pin `SpawnRequest` for the first time, and YES, C should do it.** The measured fact stands: §5 pins only `fn spawn(&self, req: SpawnRequest) -> RunId` (line 941, the sole hit); `LoopOutcome` is not in CONTRACTS at all. Pinning the whole ten-field shape now is what makes Session G a window rather than a contract change, which is the roadmap's own stated reason for putting item (4) in C. Pinning a shape for the first time is cheaper than moving a pinned one — but it obliges four things:

  (a) Every field listed with its type AND its declared/derived/withheld status, because ADR-057 §5's line (`share` and `reads_untrusted` are not `args`-derived) is currently only in a doc comment.
  (b) **A sentence naming which enums in the spawn shape are pinned by MEMBERSHIP and which by NAME ONLY.** `AgentLevel`, `Disposition`, `OrphanPolicy`, `BudgetShare`, `RunStatus` and `Channel` are membership-pinned — adding a variant needs the human, as M3-D1 established. **`ModelRoute` is pinned by name only, and that is the entire mechanism by which the fourth role arrives without a contract change.** Its variant list is ordinary crate work. Without this sentence written down, a later session adding the fourth role will correctly conclude it needs an ADR and the roadmap's reason for putting the field in C evaporates.
  (c) A statement that `Routing::model_for` matches `ModelRoute` **exhaustively with no wildcard arm**, so a new variant is a compile error until the table has a model for it. That is what stops a fourth role arriving half-wired — load-time error over sensible default, enforced by the type system.
  (d) **A reachability sentence, and it must be the opposite of §12.1's.** §12.1 pins `ingest_external` and says honestly that it has no production caller. §5's `role` pin must say the chain is complete and name it: `SpawnRequest.role` → `engine.rs:2654` → `CallLimits.route` → `ollama.rs:300` → `Routing::new` in the daemon. A pinned shape with an incomplete chain has pinned nothing.

**3. CONTRACTS §5 — `RunControl`/`Run` unchanged.** `escalation_target` and `EscalationTarget` live in `marlowe-loop` and are not boundary types; `CallLimits` is not pinned anywhere and needs no entry. `CONTRACTS §12`'s six loop-boundary types are untouched.

**Not free, and it must be stated: the `level` field breaks pre-Session-C checkpoints.** `DurableRun.profile: CapabilityProfile` (durable.rs:98) round-trips through the validating constructor, and `Raw` carries `deny_unknown_fields` with no `#[serde(default)]`. A checkpoint written before C fails to resume with a named serde error. That is the correct trade — a default here is the "makes a mismatch unobservable" family, and a silently-defaulted level would restore a master holding working tools — but it is a real cost against Session A's shipped resume (`runs/session-a-m3/live/`), so it is the human's to accept rather than a footnote.

**A documentation cost that is not a contract cost: AGENT-DIRECTORY §2's role labels.** Its table says secretary / agent / extractor; `ModelRoute` says Orchestrator / Worker / Summarizer. Session C must record the mapping as a TABLE in CONTRACTS beside the enum, so Session G's window labels are a rendering of the enum rather than a second enum. Two names for one role is the two-sides-silently-disagree shape. And the mapping has a real wobble that C must not paper over — ADR-008's own 2026-08-10 amendment says compression ≠ extraction, while AGENT-DIRECTORY calls the 2b model the "extractor" and `ModelRoute::Summarizer` is the compaction summarizer. Flag; do not resolve.

### Guarded

['crates/marlowe-loop/src/profile.rs', 'crates/marlowe-loop/src/driver.rs']

### For the human

['**BOTH GUARDED FILES ARE EDITED AND A HUMAN MUST APPROVE BOTH.** `crates/marlowe-loop/src/driver.rs` (§13, added by M3-D3) gains `role: ModelRoute` and `disposition: Disposition` on `SpawnRequest` plus two total parsers in `from_args`. `crates/marlowe-loop/src/profile.rs` (§13, M2 A) gains `AgentLevel`, `Disposition`, a seventh field on `CapabilityProfile`, three `ProfileError` variants, a seventh argument to `new`, the corresponding `Raw` field, and a level argument to `narrowed`. `crates/marlowe-permission/src/adjudicate.rs` is NOT touched — `blocks_composed_targets` is unchanged and `composes_spawn_targets` lives in the unguarded `engine.rs`. Neither `marlowe-daemon/src/memory.rs`, `steer.rs`, `mcp.rs`, `pin.rs`, `trust.rs`, the journal nor `persona/` is touched. Whoever lands this adds no `PROTECTED` row, so no new row is owed to the §13 table.', "**The fourth `ModelRoute` variant's name.** Not invented here. And the question that sits under it, which this design surfaced rather than settled: **ADR-008's 2026-08-10 amendment ALREADY asked `ModelRoute` to gain a fourth role — compression — and it never landed.** Whether the human's unnamed fourth role IS ADR-008's compression role, or a fifth beside it, decides whether `ModelRoute` ends with four variants or five and whether `Routing` gets four columns or five. The amendment's own words are that compression is the enforcement point for brief §10 and, after ADR-037 §6, the security interface — so this is not a naming detail.", "**Is `role` a Target under ADR-023?** This design answers YES and enforces it by adding one disjunct to `composes_spawn_targets`, on the reasoning that layer 3 governs *what happens* rather than *what is said* and a model choice is both a capability and an amount. AGENT-DIRECTORY §3 item 4 asks for this to be answered explicitly rather than by omission; the answer is cheap and reversible, but it is the human's to accept because it narrows what a latched run may do.", "**Both pinned-contract acts** — `CapabilityProfile`'s seventh field, and pinning `SpawnRequest`'s whole shape for the first time. M3-D1's precedent is that a pinned-contract change is escalated, not taken.", '**Breaking pre-Session-C checkpoints.** Accept the named serde failure on resume, or fund a one-shot migration. A `#[serde(default)]` is not on the table — it would silently restore a master holding working tools.', '**AGENT-DIRECTORY §2\'s own arithmetic is contradicted by this session\'s measurement and the role DEFAULTS depend on it.** §2 says the three models take "10.0 GB of the card\'s 16, leaving headroom for the KV cache, the embedder and the reranker." Measured today via `/api/ps`: 5,086 MiB were held by the desktop before anything loaded, and the final state is 14,993 MiB used / **1,053 MiB free**. ADR-044 resolves the embedder\'s provider against free VRAM AT LOAD, so shipping a three-model table is what makes the embedder fall to CPU with a correct-looking log line. Which models go in the default table is therefore a VRAM decision, not a naming one.', '**SECURITY-AUDIT §8 / ROADMAP M3-C item (2): "the latch belongs on the session, not the Run."** Untouched by this design and still unrecorded in `DECISIONS.md` seventeen days after it was answered. It is adjacent — `Run::root` is rebuilt every turn at `UserAsserted` (daemon.rs:2486, run.rs:680), so the composed-targets refusal this design adds for `role` is also per-turn — but it is a separate decision and it is the human\'s.', '**Whether `MANAGEMENT_TOOLS` starts at `["run", "ask"]`.** §1.2\'s list names eight capabilities and six of them do not exist yet. Starting with the two that do is honest; starting with eight names, six of which resolve to nothing, would make the master rule vacuously permissive in exactly the way instance #16 describes.']

### Risks

['**Instance #16, third occurrence in one code path, and it is the likeliest failure of this session.** Two live instances already exist and both are in the chain this design completes: `CapabilityProfile::model_route()` has zero readers under `crates/` at HEAD, and `Routing::new` has zero production callers. If C lands `role` and defers the wiring, the green-and-vacuous test writes itself (`assert_eq!(req.role, Summarizer)`) and reads identically on a build where every child runs on the orchestrator model. The mitigation is that `a_child_spawned_at_the_summarizer_role_is_called_on_the_summarizer_model` asserts on `request_body["model"]` — the bytes — not on the field.', "**The wire test is an in-process test, which is the pipe-tested-guard family (`persona_emission.rs`, M2 C2d/C2e).** It asserts on a body built inside the test process and cannot see a stale deployment or a daemon that never reaches the code path. Session C also owns the model-driver seam (`Daemon::turn` builds its `Box<dyn ModelDriver>` inline, no seam), so the honest close is a `--dev` outbound-request dump from the SHIPPED binary showing the child's model name. The unit test is necessary and not sufficient, and this must be said in STATE.md rather than discovered.", '**The `may_create_agents` check closes a gap that is SECURITY-AUDIT H2\'s, not a new finding.** H2 records that `remember` and `ask` bypass the adjudicator entirely — including "the exposure check" at adjudicate.rs:288 — and claims `run` was routed back through `ToolCall` for that reason. That claim does not hold at HEAD: `control_step` (ollama.rs:1045) maps `run` straight to `ModelStep::Spawn`, and `Engine::spawn` checks task, tools_declared, composed targets, budget and narrowing — never exposure. So H2\'s gap covers `run` too. Filing it as new would be the third re-derivation this milestone has produced; cite H2.', '**Instance #17 in a new place.** The obvious way to express "a worker spawns nothing" is `Budget { depth: 0 }` or `subagents: 0`, and `Budget::exhausted` reads both as already-exhausted. This design bounds the tree in `AgentLevel::child_of`\'s table instead, so the numeric depth budget keeps meaning what it means. Anyone tempted to "simplify" by moving the bound into the budget re-opens ADR-041\'s exact failure — a worker that pauses before its first model call while looking perfectly configured.', "**Instance #19, at two new lists.** `MANAGEMENT_TOOLS` and the set of `AgentLevel` variants are both lists that a check derives its own input from. `a_master_cannot_hold_a_working_tool` iterates `MANAGEMENT_TOOLS`, so removing an entry from it turns nothing red — the same shape as deleting a `PROTECTED` row. Closed by pinning the expected membership as literals in the test, and by making the TERMINATE test's per-level coverage come from a wildcard-free `match` (a compile error) rather than from an `ALL` array (silently short).", '**`MANAGEMENT_TOOLS` could be made vacuous by growth.** As C lands `communicate`, `todo`, `budget` and the meeting controls, each addition widens what a master may hold. The disjointness test is the only thing standing between that and a master with `edit` — and it is one careless `MANAGEMENT_TOOLS.push` from being a list that contains every builtin, at which point §1.2 is a comment. The disjointness assertion must name the working tools literally, in the test, so a widened constant fails rather than passes.', '**A saturated floor, in the ADR-036 §5 sense.** `composes_spawn_targets` refuses a role choice under a latched floor — but M3-DESIGN §2.1 makes the secretary a run that may never latch, and ROADMAP C(2) records that `Run::root` is rebuilt every turn at `UserAsserted`, so the refusal is per-turn. Inside a research subtree where every source is `UntrustedContent`, every spawn is equally tainted and the floor discriminates nothing; the question that survives is who ASSERTED the role, and this design does not answer it. It is bounded — the roles are a closed enum of three known-local models, so the blast radius of a wrong choice is spend and capability, not egress — but the mechanism is not doing work there and should not be claimed to be.', "**Shipping tiered routing changes the VRAM picture, and the measurement that would catch it does not exist yet.** Today every production site calls `Routing::uniform`, so exactly one model is ever loaded. The moment `Routing::new` gets a production caller, three models co-reside and 1,053 MiB is free — below what ADR-044's `auto` needs to put the embedder on the card. This is a measurement scoped to a system that is about to change: every retrieval timing and every embedder-provider line taken before this lands is about a one-model machine. Re-measure, do not cite.", '**`OLLAMA_NUM_PARALLEL=1` means the role ladder does not buy concurrency.** Four co-resident models still admit one request each at a time, and STATE.md records that this was set deliberately to protect the prefix cache. A directory (or a roster) showing three agents running on a machine that serialises them is telling the truth about intent and a lie about execution — AGENT-DIRECTORY §3 item 7. This design does not touch it and does not depend on it, but the `role` field is what makes the discrepancy visible to a user for the first time.', "**Admission control (roadmap item 5) consumes this shape and is NOT designed here.** The per-role queue keys on `ModelRoute`, which is one more argument for the closed enum, and `RunStatus::Queued`'s conflation of *constructed, not yet started* with *blocked behind three busy workers* is a separate decision. If admission control lands before the role field's reader chain, the queue is built against a routing table that answers the same model for every key.", '**Nothing here wires `ingest`.** `grep -rn "ingest_external(" --include=*.rs crates/*/src/` returns exactly two hits, both definitions (memory.rs:542, driver.rs:573), and this design adds no producer for `Channel::Agent`. Layer 3 stays unreachable in the shipped daemon, which is the correct state per ADR-062.']
