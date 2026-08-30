# escalation-terminate: Escalation routes on the run tree, not on a model's word; TERMINATE is a variant the type cannot omit

**Adversary verdict:** broken

**Fatal:** The §11 acceptance row it is built to satisfy cannot be measured the way it proposes: `terminate` already appears in every agent's `request_body` from two production sources — the `run` tool's `orphan_policy` description (`crates/marlowe-tools/src/builtin.rs:695`) and the spawn receipt (`crates/marlowe-loop/src/engine.rs:2731`) — so `terminate_appears_in_no_agents_request_body` is red on a correct build, and the only cheap repair is to weaken the search until the zero stops being evidence. That is instance #15 committed against the acceptance table itself.

## Ledger instances the adversary says this re-commits

- **#15 (an assertion that reads the same whether or not the mechanism works)** — `terminate_appears_in_no_agents_request_body`: `terminate` occurs in `builtin.rs:695` and `engine.rs:2731` today, so the zero is either red or weakened, and a weakened version reads identically on a build with every guard deleted.
- **#15, second instance** — `a_worker_escalation_stops_at_its_master_and_never_reaches_the_root` asserts "the root's `SessionState` gains zero blocks" and "no `Recipient::Run(root_id)` is ever produced." Both are true on today's HEAD: `engine.rs:2936` already swallows a child's escalation into a harness constant. Two of four assertions are green before the feature exists.
- **#16 (a declared control nothing reads)** — `AgentLevel::may_hold_create_grant`. The narrowing check at `engine.rs:2631-2640` plus the design's own level table make `(Worker|ToolSpawned, grant=true)` unreachable, so its only enforcement site can never see it false. Same shape as `inline_threshold_bytes: 0`.
- **#16, second instance** — `AgentLevel::ToolSpawned`. `condense_batch` builds the quarantined reader via `Run::child` at `engine.rs:2146`, not `Engine::spawn`, so it classifies as `Worker`; and a `Worker` never holds `run`, so it can never spawn. The variant the `NotRaisable` route hangs on is constructed by nothing.
- **#16, third instance** — `EscalationRequest`/`ModelStep::Escalate` is declared with no port to carry it: `Ports` (`engine.rs:217-227`) has no escalation member and `marlowe-loop` cannot see `marlowe-daemon`. The named reader `Engine::escalate` has no destination.
- **#12 (a validating constructor `serde` routes around)** — `ValidatedSentence` and `OptionLabel` derive `Serialize` only; "`Deserialize` routes through it" is a comment with no impl and no test. The in-repo pattern to copy is `GovernanceConstraint`'s hand-written `Deserialize` at `context.rs:403-425`.
- **#14 (a citation whose subject moved)** — `daemon.rs:2486` is `WorkspaceScope::new()`, not `Run::root` (2609); `run.rs:680` is `last_checkpoint: None`, not `trust_floor` (682). Both inherited from `ROADMAP.md:860`, whose own parenthesis says five of seven citations there had drifted and to re-verify.
- **Two definitions of one fact, four times** — `AgentLevel` stored on `Run` beside `Run::parent` (and falsified by `adopted_by`/`detached`); `AgentLabel::for_run` beside `marlowe-loop/src/run.rs:107`'s `sayable`, which exists specifically to be the only answer; `Provenance` in `marlowe-view` beside `marlowe-loop/src/provenance.rs:38` and `marlowe-memory/src/gate/mod.rs:356`; `Severity::Advisory` beside `Urgency::Advisory` (`driver.rs:658`).
- **#17 — correctly avoided, and worth recording as a pass.** The rejected-alternatives list refuses an escalation budget of 0 by name, and `MAX_AGENT_OPTIONS` is a construction-time `Err`, not a `Budget` dimension. Every withholding in the design is structural. That half of the design is right and the strengthened version keeps it.
- **#19 — correctly anticipated, and worth keeping.** The design's own risk list says that if either new `escalation.rs` is later added to `PROTECTED`, the row goes into CLAUDE.md's table and into `EXPECTED_PROTECTED` in `boundary_hook.rs` in the same commit. That is the right reading of the fix and should survive into the built version.

## Defects (21)

### **The headline acceptance test is red on the current tree, from two production sources.** `terminate_appears_in_no_agents_request_body` asserts "`terminate` (case-insensitive) occurs 0 times in the serialized JSON" over 18 bodies. `crates/marlowe-tools/src/builtin.rs:695` is the `run` tool's `orphan_policy` parameter description: "`terminate` (default) ends the child when this run ends; `detach` lets it outlive this run." That schema goes to every model holding `run` — every top-agent, every master, and Marlowe. `crates/marlowe-loop/src/engine.rs:2731` renders `OrphanPolicy::Terminate => "terminate"` into the spawn receipt pushed into the parent's window as `SourceKind::History`, so it is in the parent's next request body too.

- **Why:** The design has exactly two exits and both are the defect. Weaken the search (exclude the tool schema, or search only `TERMINATE_LABEL`) and §11's row stops measuring the property while still printing a zero — instance #15 committed against the acceptance table itself. Or rename a live tool parameter to protect a test, which is the scoreboard reshaping the product. The assertion's subject is "the escape hatch is unknown to the agent"; what it measures is "a byte string is absent", and those stopped being the same question the moment `orphan_policy` was documented.
- **Fix:** Assert on a canary that could only come from the harness's terminate row. `pub const TERMINATE_CANARY: &str = "harness-escape-hatch-6b1f";` in `crates/marlowe-view/src/escalation.rs`, embedded in `Choice::Terminate`'s wire spelling and in the surface's fixed row, and present in no type any `ModelDriver` can reach. Assert zero occurrences of the canary AND of `TERMINATE_LABEL`, plus the persona positive control, plus a NEGATIVE CONTROL the design lacks: one body deliberately built with an `EscalationView` serialized into the brief, asserted to CONTAIN the canary — otherwise the search itself is unproven and a zero could mean "the substring scan is broken".

### **The upward channel has no port. `ModelStep::Escalate` has nowhere to go.** `Ports` (`crates/marlowe-loop/src/engine.rs:217-227`) holds `driver, summarizer, tools, memory, approvals, sink, control, clock, recorder` — nothing for escalation. `EscalationDesk` is placed in `crates/marlowe-daemon/src/escalation.rs`, and `marlowe-daemon` depends on `marlowe-loop`, not the reverse. `enforcement_sites` names `crates/marlowe-loop/src/engine.rs::Engine::escalate` as the reader of `Escalation::sentence` and `Run::level`, and that function has no destination for the record it builds.

- **Why:** This is the seam, and CLAUDE.md's rule is that nothing testing halves can see one — the `done`-to-tool-host failure is the same shape. Both halves here are individually coherent: the loop can construct an `EscalationRequest`, the desk can route one. Nothing connects them, and the design never notices because every test it proposes lives on one side or the other.
- **Fix:** Add the port in `driver.rs` (already the §13-guarded file the design is asking about, so it costs no second approval): `pub trait EscalationPort { fn raise(&mut self, run: RunId, route: EscalationRoute, req: EscalationRequest) -> Result<EscalationId, EscalationRefused>; }` with `pub struct NoEscalation;` returning `Err(EscalationRefused::NoDesk)` — the `NoControl` precedent at `control.rs:113-131`. `Ports` gains `pub escalations: &'a mut dyn EscalationPort`. The quarantined-reader child `Ports` (`engine.rs:2880-2891`) passes `&mut NoEscalation` structurally, beside `memory: None`.

### **The quarantined reader is classified `Worker`, not `ToolSpawned`, so its escalation routes to its parent.** `condense_batch` builds the reader at `engine.rs:2146` with `Run::child(child_id, run, …, CapabilityProfile::quarantined_reader(), …)` and never through `Engine::spawn`. Under `AgentLevel::child(parent_level, child_holds_create_grant)` with the grant read from `req.tools.contains("run")`, the reader has no `SpawnRequest` at all; the nearest available answer is `false`, giving `(TopAgent, false) => Worker` or `(Master, false) => Worker`. `escalation_route(Worker, Some(p)) => Master(p)`. The `ToolSpawned` arm is only reached from `(Worker, _)`, and a `Worker` by the design's own table never holds `run`, so it can never spawn — **`AgentLevel::ToolSpawned` is unreachable from `AgentLevel::child` in the shipped call graph.**

- **Why:** The design's single strongest security claim — "a tool-spawned agent's window holds raw untrusted bytes (ADR-041), so its question is a statement about the model, not about the page" — is attached to a variant nothing constructs, while the run that actually holds those bytes is given a live route upward. The level is derived from a model-composed `Target` (`req.tools` is `ArgumentRole::Target`, `builtin.rs`), not from the tree, which contradicts the design's own title.
- **Fix:** Derive the refusal from the fact `CapabilityProfile::new` already enforces at load time: `profile.reads_untrusted()`. A run that reads untrusted content may not raise, whatever made it and whatever its parent was. That is a structural withholding, not a table lookup, and it holds for the fact extractor in `SCOPED-MEMORY.md` §4 as well.

### **`AgentLevel::may_hold_create_grant` can never return false at its enforcement site — instance #16 in a new dress.** The narrowing check at `engine.rs:2631-2640` refuses any `t` in `req.tools` not in `run.profile.exposed_tools()`. So a child gets `run` only if the parent holds `run`. By the design's own table, any run holding `run` is `Secretary`, `TopAgent` or `Master`, for all of which `may_hold_create_grant` is `true`. The `(Worker, grant=true)` and `(ToolSpawned, grant=true)` cases the method exists to refuse are unreachable.

- **Why:** `enforcement_sites` lists it as read by `Engine::spawn` "in the same block as the existing narrowing check", and a test of it would be green on a build where the method returned `true` unconditionally, and green again if it were deleted. That is the `inline_threshold_bytes` shape exactly: a declared control whose reader can never see it false.
- **Fix:** Delete the method. If the invariant is wanted, assert it where it can fail: an exhaustive table test over the level/grant product asserting that no reachable `(parent_level, tools)` pair yields a run at a leaf level holding a create grant — and state in the test's header that the narrowing check is what makes it unreachable, so a future relaxation of `composes_spawn_targets` or the narrowing turns the test red rather than turning the method live.

### **Storing the level on `Run` creates a second definition of tree position, and `Run::adopted_by` / `Run::detached` can silently falsify it.** `run.rs:735-745`: `adopted_by` sets `parent = Some(new_parent)`, `detached` sets `parent = None`. Both leave a construction-derived `level` untouched. `escalation_route(Master, None)` and `escalation_route(Worker, None)` both return `NotRaisable`, so after `OrphanPolicy::Detach` an agent's escalation **vanishes with no event, no window, and no note in anyone's context**.

- **Why:** "What is this run doing / where is it" is already answered by `Run::parent` and `settle_orphan` (`durable.rs:360-385`). A second answer that only the constructor writes is the project's most-logged shape, and its failure here is silence on the highest-consequence channel in the system.
- **Fix:** Store the one bit the tree genuinely cannot recompute — `RaisesTo` — and read `run.parent` for the recipient, so there is exactly one answer to "who is above me". And make the detached case **emit**: `EventKind::RunFailed` with a named reason plus a harness constant into the raiser's window, on the `QuarantineRefusal` precedent. A channel that goes quiet is not a channel that is closed.

### **A stored level is a durable-format change the design does not mention.** `Checkpoint` (`crates/marlowe-loop/src/durable.rs:87-108`) carries `version: u16` against `CHECKPOINT_VERSION`, and `ResumeError` has a variant for "a version this build will not read". `Run::restored` takes twelve explicit parameters and the design says only that it "carries it".

- **Why:** Adding a field to `Checkpoint` without a version bump makes every existing checkpoint decode into a run whose escalation routing is whatever `serde` defaults to — the permissive-default family, on a security field, in the milestone whose entire subject is durable resume.
- **Fix:** Bump `CHECKPOINT_VERSION`, add `raises_to: RaisesTo` (no `#[serde(default)]`), extend `Run::restored`, and add `a_checkpoint_without_a_route_is_refused_by_name` in `marlowe-loop/tests/` — a v-1 checkpoint blob decoding to `Err(ResumeError::UnreadableVersion)`. Mutation: add `#[serde(default)]` and it goes red.

### **`AgentLevel::Secretary // 1 — the permanent run. One, ever (§0)` is false of the shipped daemon, and the design contradicts itself about it.** `crates/marlowe-daemon/src/daemon.rs:2609` builds a fresh `Run::root` per user message. The design's own `open_for_human` item 2 records the rebuild and never notices it falsifies the comment two hundred lines above it.

- **Why:** Every routing statement anchored on "the secretary" is anchored on a run id that changes every turn. "Is my parent the secretary" — the test for top-agent-ness, the only level that reaches the user — is unanswerable across a turn boundary. A comment asserting a property the code contradicts is how a reader concludes the property holds.
- **Fix:** Do not anchor on identity. `RaisesTo::User` is decided once, at the moment the permanent run spawns a child, and is carried by the child for its life — the `trust_floor` inheritance pattern. Nothing then needs to re-answer "which run is Marlowe" on a later turn.

### **`TERMINATE_LABEL = "terminate this agent and everything under it"` is a promise the harness cannot keep, and §3.5 is the section that forbids exactly this.** `Control::cancel` is per-run and `crates/marlowe-loop/src/control.rs:337` is a test named `cancelling_one_run_does_not_cancel_its_sibling`. CONTRACTS §5 pins "Children outlive parents. Parent completion does not kill a child." `settle_orphan` (`durable.rs:369-382`) makes `OrphanPolicy::Detach` set `parent = None` and survive. There is no subtree cancel in the workspace. `TerminationCost::irreversible` lists `FilesWritten`, `CommitsPushed`, `MessagesSent`, `ProcessesRun` and has no variant for "three children detach and keep running."

- **Why:** §3.5's whole subject is that *"reverts the scope"* is three different promises and TERMINATE must tell the truth about which it keeps. The design writes a label that over-promises and a cost type that cannot express the shortfall — so the one row the harness authors specifically because the agent would lie is itself inaccurate.
- **Fix:** Add `pub survivors: Vec<Survivor>` with `pub struct Survivor { pub run: RunId, pub policy: OrphanPolicyLabel }`, computed by replaying the subtree's declared policies, rendered as its own row. Label becomes "terminate this agent and the runs under it" with the survivor row beneath. Test `terminate_names_the_children_it_cannot_kill`: build a subtree with one `Detach` child, assert the rendered frame contains that child's `sayable` name in the survivors row. Mutation: derive `survivors` from `Vec::new()` → red.

### **`ContentRef` is not a Rust type, and as pinned it carries prose upward.** `grep -rn "ContentRef" --include=*.rs crates/` returns only doc comments in `marlowe-exec`. `CONTRACTS.md:176` pins it as `{ hash, bytes, media, summary: ResultSummary, trust, evicted }`. `ResultSummary` carries a `detail` string (`engine.rs:3124` builds one with `with_detail(vec![Metric::State("refused")], why.to_string())`). §2.3 says an artifact is "a path the *user* opens".

- **Why:** The design's enforcement site says the artifact is "rendered as an openable path only, never dereferenced into the window" — but a `ContentRef` **contains** a summary, so attacker-shaped prose crosses upward inside the record §2 calls typed, without being dereferenced at all. That is the free-text arm A8 exists to prove unsafe, smuggled inside the typed arm and therefore invisible to A8's own comparison.
- **Fix:** `pub struct ArtifactHandle(pub ContentHash);` — hash only, no summary, no preview, no media label a producer chose. The surface composes the path from the hash. And record that `ArgumentRole`'s own definition already answers the design's open question: `marlowe-tools/src/manifest.rs:85` reads "Tool selection, recipient, path, host, amount, **identifier**" — a model-chosen artifact id is a `Target` by the existing vocabulary, so it is adjudicated rather than referred to the human as undecided.

### **§3.3's governance sentences leak into every agent's system prompt, and the proposed test cannot see it.** `assert_governance` appends to `SessionState::governance`; `Assembler::assemble` rebuilds the stable tier from it (`context.rs:642`). But `engine.rs:2206-2208` and `engine.rs:2798-2800` both copy the parent's governance into every child's `SessionState` — the quarantined reader included, with the comment "a child must not be a way out of the parent's constraints." `state.identity` is cloned at both sites too.

- **Why:** "That content came from untrusted sources. If it carried an injection, propagating it to me is the failure worth preventing" would arrive in the system message of every worker that ever reads a hostile page — a description of the containment architecture, in the window of the run holding the attacker's text. The design's test `the_escalation_explanation_is_in_the_stable_tier_of_the_outbound_body` asserts presence in Marlowe's body and never absence anywhere else, so it is green on the leaking build.
- **Fix:** A Marlowe-only stable-tier source: `SessionState::secretary_notes: Vec<GovernanceConstraint>`, rebuilt into the stable tier by `Assembler::assemble` beside `governance`, and copied by neither child loop. Test `the_escalation_explanation_is_in_marlowes_body_and_in_no_agents`: present in the root's captured body, absent in all agent bodies. Mutation: add `secretary_notes` to either child-copy loop → red.

### **Collapsing `LoopOutcome::Escalated { question: String }` into `Escalated(EscalationId)` destroys the `ask` tool.** `engine.rs:1236-1245` produces that variant from `ModelStep::Ask` — Marlowe's own "put a question to the user and wait" (`builtin.rs`: "Put a question to the user and wait. The run pauses until they answer"). `daemon.rs:2899` is `LoopOutcome::Escalated { question } => ("escalated", question.clone())` — the question text is how the user learns what was asked.

- **Why:** Two different facts — the secretary asking the user a question, and an agent raising a typed record — would share one variant, and the more common one loses its payload. The design's contract_impact says only that `daemon.rs:2899` "follows", with no account of where the question goes.
- **Fix:** Leave `LoopOutcome::Escalated { question }` alone (it is `ask`, not escalation, and is arguably misnamed). Add `LoopOutcome::Raised(EscalationId)` as a new variant. The child-return `note` match at `engine.rs:2936` gains one arm returning a harness constant, matching the existing `Escalated` arm's discipline.

### **No lifecycle: nothing says what the raising run does while a human decides, and the desk does not survive a restart.** `PauseReason` (`run.rs:195-199`) is `{BudgetExhausted, AwaitingApproval, AwaitingAnswer}` — the design adds no variant. `EscalationDesk { pending: BTreeMap<…> }` is in-memory only. Children run **inline and synchronously** inside the parent's `Engine::run` (`engine.rs:2893`), and M3-DESIGN §6 records that "the daemon is serial… one connection is held for the whole of a turn."

- **Why:** A worker raising an escalation is four stack frames inside a turn that holds the daemon's only connection. There is no story for how the desk reaches a human, how a `Choice` comes back, or what the run's status is meanwhile — and in a milestone whose subject is durable runs, a pending escalation evaporates on restart while the run it belongs to resumes from a checkpoint that never mentioned it.
- **Fix:** `PauseReason::AwaitingEscalation { id: EscalationId }` (harness enum, `run.rs` is unguarded), `RunStatus::Paused` carrying it, and `EscalationDesk` writing every `Pending` through the existing `Recorder` journal path and rebuilding `pending` from the journal at boot — one definition of the pending set, on the substrate §3.5 already relies on. Test `a_pending_escalation_survives_a_daemon_restart`: raise, drop the desk, rebuild from the journal, assert the same id at the same recipient. Mutation: keep the `BTreeMap` and skip the journal write → red.

### **The `Ask`-refusal invariant has no test.** `recommendation` and the `ModelStep` doc comment both say "`Engine` refuses it at any level above `AgentLevel::Secretary`." None of the eight proposed tests exercises it. Its site is `crates/marlowe-loop/src/engine.rs`, which CLAUDE.md names explicitly as the unguarded call site whose deletion "would evaporate the boundary while every file above stayed untouched."

- **Why:** Deleting the check turns nothing red, and §3.1's "a worker can never address Marlowe" would then rest on a comment. The existing precedent is `MemoryWrite`'s `if !run.profile.may_write_memory()` refusal at `engine.rs:1260`, which is covered by `memory_write_ownership.rs`.
- **Fix:** `an_agent_cannot_reach_the_user_through_the_secretarys_door` in `crates/marlowe-loop/tests/escalation_routing.rs`: drive a child that emits `ModelStep::Ask`, assert the outcome is a refusal block naming the reason and that no `LoopOutcome::Escalated` escapes to the daemon. Mutation: delete the `raises_to` check in the `Ask` arm → red.

### **The #12 discipline is asserted in a comment and implemented nowhere.** `ValidatedSentence` and `OptionLabel` derive `Serialize` only; the doc says "`Deserialize` routes through it" and no impl is shown, no test proposed. `Escalation` likewise derives `Serialize` only, which makes the journal-durable version of the previous defect impossible to write.

- **Why:** This is the one family CLAUDE.md records as "the first that was caught by design rather than by failure", and the design claims the credit without doing the work. The in-repo pattern is thirty lines away: `GovernanceConstraint`'s hand-written `Deserialize` at `crates/marlowe-loop/src/context.rs:403-425`.
- **Fix:** Hand-written `Deserialize` for both newtypes, routing through `normalise`, on the `GovernanceConstraint` model. Test `a_checkpointed_option_label_with_an_escape_is_refused_at_decode` in `crates/marlowe-contract/tests/escalation_labels.rs`: `serde_json::from_str::<OptionLabel>("\"a\\u001b[2Kb\"")` is `Err`. Mutation: `#[derive(Deserialize)]` → the field-wise decode succeeds → red.

### **`marlowe-view` has zero dependencies, and the claimed precedent does not exist.** `crates/marlowe-view/Cargo.toml` has an empty `[dependencies]` section; its package description reads "Shapes only — nothing here can produce a value." `approval.rs` is the demonstration: `RiskTier`, `Effect`, `Novelty`, `Ceiling`, `Offered` are all declared locally. The design asserts the new edge lands "on exactly the precedent marlowe-surface's Cargo.toml already records" — a different crate, one layer up.

- **Why:** A false precedent is how an architectural stance gets reversed without anyone deciding to reverse it. The direction may well be right; the claim that it is already established is what makes it unreviewable.
- **Fix:** Add the dependency **as a recorded decision**, not as a precedent: a `DECISIONS.md` entry saying `marlowe-view` gains `marlowe-contract` because the alternative — a local `is_renderable` in the shapes crate — is a second definition of the predicate that `sanitize_line` and `text.rs:78` already own, and two definitions of "which characters may reach a terminal" is the worse trade on the surface where B1 and B2 live.

### **Three name collisions, each on a load-bearing word.** `pub enum Provenance` in `marlowe-view` collides with `marlowe-loop/src/provenance.rs:38` (the taint attribution map — layer-3 machinery) and `marlowe-memory/src/gate/mod.rs:356`. `AgentLabel::for_run(level, run) -> "top-agent 4f2a91"` is a second answer to a question `marlowe-loop/src/run.rs:100-111` explicitly closed: `sayable()`, "Every surface that prints a run goes through this rather than calling `RunId::mnemonic` after its own parse — a second place deciding what an unparseable id looks like is a second answer to the same question" — and `4f2a91` is precisely the hex prefix that doc rejects as "one unrecognisable string [replaced] with a different one". `Severity {Advisory, Blocking, Critical}` sits beside `Urgency {Advisory, Immediate}` (`driver.rs:658`), sharing a variant name with a different meaning.

- **Why:** The design is otherwise careful about one-definition discipline and then breaks it three times in its own type list. The `sayable` one is the worst because the escalation window is where a user matches a name against `/runs`.
- **Fix:** Rename the view enum `SourceEvidence`. Compose the agent label as `format!("{} {}", level_word, marlowe_loop::run::sayable(&id.to_string()))` — harness-authored level word, existing single definition of the name. Rename `Severity` to `EscalationSeverity`, or reuse `RiskTier` if the ladders coincide.

### **The routing test's strongest-sounding assertions are green today, before anything is built.** `a_worker_escalation_stops_at_its_master_and_never_reaches_the_root` asserts "no `Recipient::Run(root_id)` is ever produced" and "the root's `SessionState` gains zero blocks." `engine.rs:2936` already handles a child's `Escalated` by pushing a fixed harness constant — "a child cannot escalate to the parent's window and its question was not carried across" — so nothing crosses today either. The proposed vacuity control ("the worker's escalate step was actually reached") does not close it: reaching the step says nothing about whether routing did anything.

- **Why:** Two of the four assertions would read identically on a build with `escalation_route` deleted. The one that carries weight — "the desk's delivered recipient is the master's RunId" — is buried among three that do not.
- **Fix:** Make the positive delivery the headline and add a real negative control: a second run of the same tree through a `RouteOverride` test double that deliberately returns `Recipient::Run(root_id)`, asserting the root's window DOES gain the block. If the negative control cannot make the assertion fire, the assertion was never watching.

### **The `RecordingDriver` daemon tests can pass by not running.** ROADMAP's C row records that "provider selection `return`s at `:1802` when `Availability::probe` reports no model, so nothing in-process reaches `:2629` at all", and the reranker preconditions are worktree-scoped (`models/` is gitignored, present here, absent in worktrees).

- **Why:** Three of the design's eight tests are `marlowe-daemon` integration tests whose value is that they observe the running process. On a machine or worktree without the model they either skip or never reach a model call — and a skipped test prints nothing and reads green, which is the deployment-staleness family the `--dev` outbound dump exists to close.
- **Fix:** Adopt the `cross_encoder_reference.rs` idiom named in ROADMAP: skip **loudly**, and **fail** rather than pass when the precondition resolves write-only. `captured.len() >= 1` must be a hard assertion, not a guard that turns into an early return.

### **Nothing checks that a spawning run was ever exposed `run`.** `Engine::spawn` validates the child's requested tools against the parent's set (`engine.rs:2631-2640`) but never that the parent holds `run` itself; `ModelStep::Spawn` goes straight from the loop's match (`engine.rs:1330`) to `self.spawn`, bypassing the adjudicator, and the provider maps any tool call named `run` (`ollama.rs:1045`).

- **Why:** Pre-existing, and the design makes it consequential: a run that emits an unoffered `run` call creates a child whose level — and therefore whose ability to reach a human — is decided by a call the harness never agreed to.
- **Fix:** One line in `Engine::spawn`, before the task check: refuse by name when `!run.profile.exposed_tools().contains(&ToolId::new("run"))`, through the existing `spawn_refused`. Test `a_run_that_was_not_given_run_cannot_spawn`. Not a new security finding — check `SECURITY-AUDIT.md` before filing it as one.

### **The terminate row is asserted on-screen rather than reserved.** `terminate_survives_a_hostile_option_list` renders at 24x80 with `MAX_AGENT_OPTIONS = 4` and walks the buffer. `TerminationCost::irreversible` is a growing enum by its own stated rule, `survivors` adds rows, and `Provenance::External` adds one more.

- **Why:** It is B3's defect with a fixed number substituted for a layout invariant. The moment the cost section grows by two rows, or someone opens a 10-line pane, the fixed bottom row leaves the buffer and ratatui clips it silently — on the row that is the escape hatch.
- **Fix:** Lay the terminate row out **first**, from the frame height, and give the option list what remains, scrolling within it. Assert at 24x80 **and** 10x40 with a maximal cost block: the label's cells are present at the bottom row at both sizes. Mutation: size the modal from the unwrapped content and render with wrapping → red at 10x40 before it is red at 24x80.

### **Two citations are stale, both inherited from a roadmap row that warns about exactly that.** The design cites `daemon.rs:2486`'s `Run::root` — line 2486 is `let tool_scope = match WorkspaceScope::new()`; the `Run::root` build is at **2609**. It cites `run.rs:680` for `trust_floor: UserAsserted` — 680 is `last_checkpoint: None`; the floor is at **682**. `daemon.rs:2899` and `engine.rs:3237` are correct.

- **Why:** The source row (`ROADMAP.md:860`) says in its own parenthesis "Five of the seven citations in this row had drifted… re-verify before citing rather than trusting these." The design cited without re-verifying, which is instance #14's family aimed at a design document.
- **Fix:** Cite by symbol and re-verify by grep at write time. Two of the design's own claims — that CONTRACTS §5's pinned `Run` lists a `result` the code lacks, and that the code holds a `trust_floor` the pin lacks — I checked and both are correct, which is what makes the two stale line numbers worth naming rather than waving through.

## STRENGTHENED — WHAT GETS BUILT

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

## Original recommendation

Add `AgentLevel` as a private, constructor-derived field on `Run` (never on `CapabilityProfile`, never on `SpawnRequest`), computed by `AgentLevel::child(parent_level, child_holds_create_grant)` where the grant is read from `req.tools.contains("run")` — a value `Engine::spawn` already validates, so no new declared field and no new #16. Escalation routing is then a total function `escalation_route(level, parent) -> EscalationRoute`, whose closed return type has **no arm naming the secretary**: `TopAgent => User`, `Master|Worker => Master(parent)`, `Secretary|ToolSpawned => NotRaisable`. §3.2's "Marlowe cannot read it" is enforced by a signature, not a prompt: `EscalationDesk::secretary_notice(&self, id) -> Option<Notice>` takes no body and returns a closed `Notice` variant carrying only `Severity` and a run-id-derived `AgentLabel`, and the window opens on the ADR-055 control-plane listener so the body never touches Marlowe's `Ports.sink` or `SessionState`. §3.3's two sentences are a `const` asserted once per conversation through `GovernanceConstraint::asserted`, unconditionally and before any escalation exists — read by `Assembler::assemble` into the stable tier, which compaction cannot trim. §3.4's TERMINATE is a `Choice::Terminate` variant and a `TERMINATE_LABEL` const rendered from a fixed row: `EscalationView` has **no field** for it, so a producer cannot supply, style, annotate or move it — the inverse of `BlastRadius`'s "a surface cannot show what it was never given". The §11 zero is only evidence when it ships with a positive control (the persona marker) and a `calls >= 1` vacuity guard, asserted on the bytes three adapters' `request_body` produced and once more through the Session-C model-driver seam on a real daemon turn.

### Types

```rust
// ═════ crates/marlowe-loop/src/run.rs — NOT §13-guarded ══════════════════════════
//
// M3-DESIGN §1's five levels, as a property of the RUN TREE rather than of anything a
// model declares. No setter, no `From<&str>`, no `SpawnRequest` field.

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLevel {
    Secretary,   // 1 — the permanent run. One, ever (§0).
    TopAgent,    // 2 — the only thing Marlowe creates (§1.1).
    Master,      // 3 — holds the create grant, no working tools (§1.2).
    Worker,      // 4 — per-type tool set (§1.3).
    ToolSpawned, // 5 — quarantined reader, fact extractor. No tools (§1.4).
}

impl AgentLevel {
    /// The level a child occupies. `child_holds_create_grant` is
    /// `req.tools.contains(&ToolId::new("run"))` — a value `Engine::spawn` already
    /// checks against the parent's exposed set, so this adds no declared field.
    ///
    /// `None` at the bottom refuses a spawn BY NAME. It is deliberately not expressed as
    /// `depth: 0`, which `Budget::exhausted` would read as *already exhausted* (#17).
    pub fn child(self, child_holds_create_grant: bool) -> Option<AgentLevel> {
        match (self, child_holds_create_grant) {
            (AgentLevel::Secretary, _) => Some(AgentLevel::TopAgent),
            (AgentLevel::TopAgent, true) | (AgentLevel::Master, true) => Some(AgentLevel::Master),
            (AgentLevel::TopAgent, false) | (AgentLevel::Master, false) => Some(AgentLevel::Worker),
            (AgentLevel::Worker, _) => Some(AgentLevel::ToolSpawned),
            (AgentLevel::ToolSpawned, _) => None,
        }
    }

    /// §1's table: the create grant belongs to masters. A `Worker` asked for `run` becomes a
    /// `ToolSpawned` child above, and this refuses it — so §1.4's "no tools" cannot be
    /// contradicted by a master handing `run` to a leaf.
    pub fn may_hold_create_grant(self) -> bool {
        matches!(self, AgentLevel::Secretary | AgentLevel::TopAgent | AgentLevel::Master)
    }
}

pub struct Run {
    // … existing fields unchanged …
    /// Derived at construction. `Run::root` => `Secretary`; `Run::child` => the table above;
    /// `Run::restored` carries it, for the reason `trust_floor`'s own doc gives: a resume that
    /// rebuilt a worker through `root` would make a restart into a promotion.
    level: AgentLevel,
}

impl Run {
    pub fn level(&self) -> AgentLevel { self.level }
}

// ═════ crates/marlowe-loop/src/escalation.rs — NEW, not guarded ══════════════════

/// Where an escalation raised at this level goes NEXT. M3-DESIGN §3.1.
///
/// **There is no arm that returns the secretary, and that absence IS the enforcement of §3.2.**
/// Marlowe is not unreachable because a prompt asks a model not to reach him; he is unreachable
/// because no `(level, parent)` pair maps to him.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EscalationRoute {
    /// The direct master. §3.1: approved at each level.
    Master(RunId),
    /// §3.1: only a top-agent reaches the user — and Marlowe is not the recipient.
    User,
    /// The secretary has nobody above him. A tool-spawned agent's window holds raw untrusted
    /// bytes (ADR-041), so its question is a statement about the model, not about the page —
    /// `QuarantineRefusal::Escalated` already says exactly that and keeps saying it.
    NotRaisable,
}

pub fn escalation_route(level: AgentLevel, parent: Option<RunId>) -> EscalationRoute {
    match (level, parent) {
        (AgentLevel::Secretary, _) | (AgentLevel::ToolSpawned, _) => EscalationRoute::NotRaisable,
        (AgentLevel::TopAgent, _) => EscalationRoute::User,
        (AgentLevel::Master, Some(p)) | (AgentLevel::Worker, Some(p)) => EscalationRoute::Master(p),
        (AgentLevel::Master, None) | (AgentLevel::Worker, None) => EscalationRoute::NotRaisable,
    }
}

// ═════ crates/marlowe-loop/src/driver.rs — §13-GUARDED. HUMAN APPROVAL REQUIRED ══
//
// Two changes, both in the guarded file. See `guarded_files`.

pub enum ModelStep {
    Say(String),
    ToolCall { calls: Vec<ToolInvocation> },
    MemoryWrite(ClaimRequest),
    Spawn(SpawnRequest),
    /// Marlowe asking the USER. Root-only from here on: `Engine` refuses it at any level above
    /// `AgentLevel::Secretary`, so an agent cannot reach the user through the secretary's door.
    Ask(String),
    /// M3-DESIGN §2.3's typed upward record. **No free paragraph.**
    Escalate(EscalationRequest),
}

/// What a model may supply. **The recipient is not here** — it is `escalation_route`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EscalationRequest {
    pub severity: Severity,
    pub category: EscalationCategory,
    /// A path the USER opens. Never inlined into any window above the raiser.
    pub artifact: Option<ContentRef>,
    /// §9.1 arm A8's middle arm ONLY. `EscalationArm::Typed` — the shipped default — refuses a
    /// `Some` at the seam with a named error rather than silently dropping it.
    pub sentence: Option<ValidatedSentence>,
    /// Forwarding an escalation already addressed to THIS run, rather than raising a new one.
    /// The desk is the authority for "addressed to you"; the model only names an id.
    pub forwarding: Option<EscalationId>,
}

// `LoopOutcome::Escalated { question: String }` becomes `Escalated(EscalationId)`.
// engine.rs, daemon.rs:2899 and the child-return `note` match follow. The `note` arm gets
// SIMPLER, not richer: a child's escalation still crosses as a harness constant.

// ═════ crates/marlowe-contract/src/escalation.rs — NEW ═══════════════════════════

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Escalation {
    pub id: EscalationId,
    pub raised_by: RunId,
    pub severity: Severity,
    pub category: EscalationCategory,
    pub artifact: Option<ContentRef>,
    /// The approving chain, newest last. Appended by `EscalationDesk::advance`, never by a model.
    pub lineage: Vec<RunId>,
    pub sentence: Option<ValidatedSentence>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity { Advisory, Blocking, Critical }

/// Closed. A category the set cannot express is an escalation the product does not route —
/// the growth rule `Effect` and `Notice` already carry (ADR-030 §5).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EscalationCategory {
    BlockedByPermission,
    ScopeContradiction,
    ExternalSystemRefused,
    ConflictingInstructions,
    SuspectedInjection,
    IrreversibleActionRequired,
}

/// One line, sanitised, capped. **The only constructor**, and `Deserialize` routes through it —
/// a spawn request, an MCP descriptor and a checkpoint are all ways in (#12).
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

/// An option label a model wrote. Same constructor discipline, a tighter cap, and it exists
/// because §3.6 is a DECISION surface: SECURITY-AUDIT B1/B2 are this exact shape one surface over.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OptionLabel(String);
impl OptionLabel {
    pub const MAX_CHARS: usize = 72;
    pub fn normalise(raw: &str) -> Result<Self, TextRejected> { /* as above, at 72 */ }
}

// ═════ crates/marlowe-daemon/src/escalation.rs — NEW ═════════════════════════════

pub struct EscalationDesk { pending: BTreeMap<EscalationId, Pending> }   // BTreeMap: HashMap banned

struct Pending { escalation: Escalation, at: Recipient, opened_ms: i64 }

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Recipient { Run(RunId), User }

impl EscalationDesk {
    /// One hop. **`by` must be the run this escalation is currently addressed to.**
    ///
    /// This is ADR-036 §5's authority rule at a saturated floor. Inside an escalation every
    /// value is `UntrustedContent`, so ADR-023's floor cannot tell one pending id from another
    /// — it reads "blocked" for all of them and therefore says nothing about any of them. What
    /// discriminates is WHO addressed it here, and the desk is the authority for that, not the
    /// model that named the id.
    pub fn advance(&mut self, id: EscalationId, by: RunId, level: AgentLevel, parent: Option<RunId>)
        -> Result<Recipient, AdvanceError>;

    /// §3.2, and the enforcement is the SIGNATURE. There is no `body` parameter, no
    /// `&Escalation` return, and no method on this type that hands text to a loop. Marlowe
    /// "cannot read it" because there is nothing to call, not because he was asked not to.
    pub fn secretary_notice(&self, id: EscalationId) -> Option<Notice>;
}

// `Notice`, in marlowe-view, gains ONE variant. ADR-030 §5's no-`String` rule holds:
//     EscalationRaised { severity: Severity, by: AgentLabel }
// `AgentLabel::for_run(level, run)` is derived from the run id and the level word — e.g.
// `top-agent 4f2a91`. NO model bytes: a model-chosen display name shown to a human choosing
// between options is an agent that can call itself `Marlowe`, or `SYSTEM`.

// ═════ crates/marlowe-view/src/escalation.rs — NEW ═══════════════════════════════
// (adds ONE dependency edge: marlowe-view -> marlowe-contract, on exactly the precedent
//  marlowe-surface's Cargo.toml already records — the deepest crate, no producer in it.)

/// What the escalation window draws.
///
/// **There is no field for TERMINATE, and that is §3.4's structural invisibility.** A producer
/// cannot supply it, label it, style it, annotate it or move it, because the type has nowhere to
/// put any of those. It is the argument `BlastRadius` makes about the command, inverted: there,
/// a surface cannot show what it was never given; here, a surface cannot omit what it was never
/// given.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EscalationView {
    pub raised_by: AgentLabel,
    pub severity: Severity,
    pub category: EscalationCategory,
    options: Vec<AgentOption>,          // private; bounded at construction
    pub cost: TerminationCost,
    pub provenance: Provenance,
    pub artifact: Option<ArtifactPath>,
}

impl EscalationView {
    /// Bounded, and refused at construction rather than truncated at render. Thirty options
    /// push a fixed bottom row off a 24-line terminal — SECURITY-AUDIT B3's clipping finding,
    /// aimed at the one surface where the clipped row is the escape hatch.
    pub const MAX_AGENT_OPTIONS: usize = 4;
    pub fn new(/* … */) -> Result<Self, TooManyOptions>;
    pub fn options(&self) -> &[AgentOption];
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AgentOption { pub label: OptionLabel, pub consequence: OptionLabel }

/// **`Terminate` is a variant, not an index.** No agent-supplied option can be it, at any
/// index, under any label, however the list is ordered.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Choice { Agent(u8), Terminate }

/// Harness-authored, fixed position, always present. Not derived from anything a producer sends.
pub const TERMINATE_LABEL: &str = "terminate this agent and everything under it";

/// §3.5, derived from the journal. The model contributes nothing and is never asked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerminationCost {
    pub runs: u32,
    pub age_ms: u64,
    pub spend_micros_usd: u64,
    pub artifacts: u32,
    /// What terminating does NOT undo. Closed; grows only when the journal can prove a new
    /// consequence, never to carry a string a caller already has.
    pub irreversible: Vec<IrreversibleAct>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IrreversibleAct {
    FilesWritten { count: u32, within: PathLabel },
    CommitsPushed { count: u32 },
    MessagesSent { medium: Medium, count: u32 },
    ProcessesRun { count: u32, reached_network: bool },
}

/// §3.6: *"show provenance, not just a caution."* **Total** — `NoExternalSources` is a claim a
/// producer makes on purpose, exactly as `Novelty::Routine` is, and not an `Option` a producer
/// can omit while nothing reports the omission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Provenance {
    NoExternalSources,
    External { sources: u32, most_recent: SourceTrace },
}

/// `host` comes from `marlowe_permission::egress::Host` — the host the EGRESS layer resolved,
/// never a string the agent wrote. Under a saturated floor, who asserted it is the only
/// question left.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceTrace { pub host: HostLabel, pub fetched_ms_ago: u64 }
```

### Enforcement sites

- `Run::level (AgentLevel)` -> **crates/marlowe-loop/src/escalation.rs::escalation_route; crates/marlowe-loop/src/engine.rs::Engine::spawn (child level + may_hold_create_grant refusal); crates/marlowe-loop/src/engine.rs::Engine::escalate (refuses ModelStep::Ask above Secretary)** | breaks: Escalation has no routing table at all: every raise falls through to whatever the caller passes, and `a_worker_escalation_stops_at_its_master_and_never_reaches_the_root` goes red on its first assertion. A worker's question reaches Marlowe's window and §2.1's permanent-run argument is defeated.
- `AgentLevel::may_hold_create_grant` -> **crates/marlowe-loop/src/engine.rs::Engine::spawn, in the same block as the existing `run.profile.exposed_tools().contains(t)` narrowing check** | breaks: A master hands `run` to a leaf; the leaf is `ToolSpawned` by the table and §1.4's 'no tools' is contradicted by a run that can spawn. The depth budget still bounds it, so nothing crashes — the ladder just grows sideways with no name for what happened.
- `EscalationRoute (the closed return type with no Secretary arm)` -> **crates/marlowe-daemon/src/escalation.rs::EscalationDesk::advance — the single match that decides where a hop lands** | breaks: §3.2 degrades from a routing fact to a sentence in a prompt. The absence of the arm is the whole mechanism; a `Secretary(RunId)` arm added later would compile everywhere and be invisible in review.
- `Pending::at (the desk's authority for 'addressed to you')` -> **crates/marlowe-daemon/src/escalation.rs::EscalationDesk::advance, which returns AdvanceError::NotYours when `by != at`** | breaks: A latched master forwards an escalation addressed to a sibling subtree. ADR-023's floor cannot catch it: inside an escalation every id is UntrustedContent, so the floor reads 'blocked' for all of them and discriminates none — this is the saturated-floor case, and `at` is the provenance that survives it.
- `Escalation::lineage` -> **crates/marlowe-daemon/src/escalation.rs::EscalationDesk::advance (appends `by`); crates/marlowe-view/src/escalation.rs::EscalationView::provenance_rows (renders the approving chain)** | breaks: 'Approved at each level' becomes unauditable — a delivered escalation carries no evidence that any intermediate master saw it, and the acceptance row for §3.1 has nothing to count.
- `Escalation::artifact (ContentRef)` -> **crates/marlowe-surface/src/escalation.rs::draw_artifact_row — rendered as an openable path only, never dereferenced into the window** | breaks: §2.3's 'an artifact is a path the USER opens' collapses into inlined prose, which is the free-text arm A8 exists to prove is unsafe.
- `Escalation::sentence (Option<ValidatedSentence>)` -> **crates/marlowe-loop/src/engine.rs::Engine::escalate, which refuses `Some` under EscalationArm::Typed by name; crates/marlowe-surface/src/escalation.rs::draw_body when the arm permits it** | breaks: A8's middle arm is unrunnable and the three arms stop being one type with a switch, becoming three code paths that can drift — which is exactly the condition under which A8's result stops being about the channel shape.
- `TerminationCost::{runs, age_ms, spend_micros_usd, artifacts, irreversible}` -> **crates/marlowe-view/src/escalation.rs::TerminationCost::rows — one row per field, and `every_termination_cost_field_is_rendered` mutates each field and asserts the rendering changes** | breaks: This is instance #16 waiting to happen: a field the producer computes from the journal and the renderer silently drops, with a green test asserting the field's value. §3.4's whole point is that the harness states the cost because the agent would lie about it — a cost nothing prints is the agent's number by default.
- `Provenance (total enum, no Option)` -> **crates/marlowe-view/src/escalation.rs::Provenance::row; produced by crates/marlowe-daemon/src/escalation.rs::provenance_from_journal, counting ToolCompleted rows for tools whose manifest declares a Url Target** | breaks: §3.6's checkable claim reverts to 'if this seems tainted', which asks the user to detect a well-written lie. As an `Option` it would additionally be a producer that can omit the line with nothing reporting the omission.
- `OptionLabel / ValidatedSentence validating constructors (sanitize_line + is_renderable + cap), Deserialize routed through them` -> **crates/marlowe-daemon/src/escalation.rs::EscalationDesk::accept, which is the only construction site for an AgentOption; crates/marlowe-surface/src/escalation.rs::draw_options renders `label.as_str()` and composes nothing** | breaks: SECURITY-AUDIT B1 and B2 reappear on the one surface where they are worst: an ESC or a newline in an option label repaints the line the human is reading in order to choose, and a bidi override swaps what an option reads as against what it is.
- `EscalationView::MAX_AGENT_OPTIONS = 4, refused at construction` -> **crates/marlowe-view/src/escalation.rs::EscalationView::new (returns Err(TooManyOptions)); asserted by terminate_survives_a_hostile_option_list** | breaks: Thirty options push the fixed TERMINATE row off a 24-line terminal — SECURITY-AUDIT B3's clipping defect, on the row that is the escape hatch. Note it is a ceiling on a Vec checked at construction, deliberately not a Budget dimension, because `Budget::exhausted` reads a bound as already-spent (#17).
- `Choice::Terminate + TERMINATE_LABEL const, and the ABSENCE of a terminate field on EscalationView` -> **crates/marlowe-surface/src/escalation.rs::draw_terminate_row (emits the const at a fixed row); crates/marlowe-daemon/src/escalation.rs::EscalationDesk::resolve (matches the variant)** | breaks: If it became a field, a compromised top-agent could label it, reorder it, style it or omit it — §3.4's four prohibitions, all of which are currently unstatable because there is no field. The declaration test (`!exposed.contains("terminate")`) would stay green throughout.
- `ESCALATION_GOVERNANCE (§3.3's two sentences)` -> **crates/marlowe-loop/src/context.rs::Assembler::assemble, which loops `for c in &state.governance` into the stable tier, into the system message, into request_body** | breaks: A retrieval miss or a compaction pass leaves Marlowe improvising an account of his own security architecture — the failure §3.3 names. Asserted once at session construction rather than lazily at the first escalation, so a compaction between the event and the assertion cannot open the window.

### Rejected

- **Put `AgentLevel` on `CapabilityProfile` (marlowe-loop/src/profile.rs) beside `reads_untrusted`, so the level travels with the capability set.** - Two reasons and the second is decisive. (1) `profile.rs` is §13-guarded; putting a routing field there makes every M3 tree change a boundary prompt for no security gain. (2) The level is a property of the TREE, and `CapabilityProfile::new` cannot see a parent — so it would have to be supplied, i.e. declared, i.e. reachable from a spawn request, which is precisely the model-declared value the design exists to avoid. This is the same argument ADR-032 makes for keeping the granted egress set on the profile rather than the `Run`, run in the opposite direction: put the value where the invariant that constrains it is already enforced.
- **Add `kind: AgentKind { Master, Worker }` to `SpawnRequest`, since §1.1 says Marlowe declares the kind at spawn.** - Nothing would read it. The declaration is already expressible and already validated: a master is a child whose `exposed_tools` contains `run`, and `Engine::spawn` already checks every requested id against the parent's set. A second field carrying the same fact is instance #16 by construction — a declared control with a green test asserting its value — and it would land in the same commit as Session C's `role` field, doubling the pinning cost of a shape that is not pinned yet. If the two ever disagreed, the tool set is what the child actually gets.
- **Carry the escalation to the user on `TurnEvent` / the conversation socket, as `Event::Done { outcome: "escalated", detail }` does today.** - It halts the conversation, which is the one thing M3 §0 exists to stop, and it routes attacker-shaped prose through the pane Marlowe is speaking in. Worse, it would put the body inside the turn Marlowe's own `Ports.sink` serves, so 'Marlowe cannot read it' would rest on a filter rather than on a channel he is not on. The ADR-055 control-plane listener already exists as a second listener on a published port and already carries `/watch` windows; an escalation window IS a window on a run. CONTRACTS §13's pinned `TurnEvent` then needs no change at all.
- **Keep `ModelStep::Ask(String)` for agents and let the harness validate the string, rather than adding a §13-guarded `ModelStep::Escalate` variant.** - It is the free-text arm shipped as the product. §2's invariant is that nothing but typed structure crosses upward, and a validated paragraph is still a paragraph: `severity`, `category` and `lineage` would have to be inferred from prose by something, and whatever infers them is a model reading attacker-shaped text on the decision path. It also leaves A8 with no way to express its first arm. The guarded edit is real and the human must approve it; the alternative is to build the thing A8 predicts will fail and call it the default.
- **Give `EscalationDesk` a `body(&self, id) -> Option<&str>` accessor and rely on Marlowe's profile not exposing a tool that calls it.** - 'Cannot read it' would then be a fact about a registry entry rather than about the type, and the registry is configuration — an MCP descriptor, a skill, a future `recall` variant, or a well-meaning debugging path could all reach it. The signature with no body parameter is the version that cannot be reached by adding a caller. Same reasoning as `BlastRadius` having no field for the command.
- **Let a spawner supply a human-readable agent name (§3.2's `CodeProjectLeader`) so escalations name something the user recognises.** - A model-chosen display string rendered to a human who is about to choose between labelled options can name itself `Marlowe`, `SYSTEM`, or the label of an adjacent option. `AgentLabel::for_run(level, run)` derives `top-agent 4f2a91` from the run id and the level word, with zero model bytes, and the run id is what `/runs` and `/watch` already address. A human-readable name is worth having and belongs with Session C's `role` field, in one deliberate `SpawnRequest` pinning act — not smuggled in as a display convenience.
- **Express the quarantined reader's inability to escalate as an escalation budget of 0, alongside its `tool_calls: 1, subagents: 1`.** - Instance #17, verbatim. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on iteration one and the reader would pause before its first model call — the exact failure ADR-041 produced, where containment stayed perfect and the product returned 'the content could not be condensed' for every page. The capability is withheld structurally: `AgentLevel::ToolSpawned` has an `EscalationRoute::NotRaisable` arm, and there is no counter.

### Tests

- `a_worker_escalation_stops_at_its_master_and_never_reaches_the_root` in `crates/marlowe-loop/tests/escalation_routing.rs`
  - asserts: Builds a real four-level tree through `Engine::spawn` (root -> top-agent -> master -> worker), has the worker emit `ModelStep::Escalate`, and asserts on the fate of the bytes rather than on the routing table: the desk's delivered recipient is the master's RunId; no `Recipient::Run(root_id)` is ever produced across the whole run; the root's `SessionState` gains zero blocks; and `lineage == [worker_id]` at the first hop, `[worker_id, master_id]` after the master forwards. Includes a vacuity control: asserts the worker's escalate step was actually reached (>= 1 `Escalate` observed), because every one of the above reads identically on a run where nothing escalated.
  - red on: Change `escalation_route`'s `(AgentLevel::TopAgent, _) => User` arm to `(AgentLevel::TopAgent, Some(p)) => Master(p)`: the top-agent's parent is the root, `Recipient::Run(root_id)` appears, and the assertion fires by name. Independently: deleting the `at != by` check in `EscalationDesk::advance` lets the worker forward straight past its master and the lineage-length assertion fails.
- `terminate_appears_in_no_agents_request_body` in `crates/marlowe-provider/tests/terminate_is_absent_from_the_request_body.rs`
  - asserts: Prints and asserts a number: over 6 profiles (secretary, top-agent-master, top-agent-worker, master, worker, quarantined reader) x 3 adapters (`OllamaDriver`, `LlamaCppDriver`, `OpenRouterDriver`) = 18 bodies, `terminate` (case-insensitive) occurs 0 times in the serialized JSON, and `TERMINATE_LABEL` occurs 0 times. THE CONTROL, which is what makes the zero evidence: the persona marker `"You are not impressed"` is asserted PRESENT in 18/18 first, so a body that failed to build, serialized empty, or dropped its messages cannot report a clean zero. Output line: `terminate: 0 occurrences / 18 bodies; persona marker present 18/18`.
  - red on: Register a `terminate` entry in `builtin_registry()`, or add the word to `governance_prompt()` / `IDENTITY_FACTS`: the count goes non-zero. Reddening the CONTROL: delete the persona from the assembled view and the 18/18 assertion fails first, so the test can never report a zero it did not earn.
- `terminate_never_reaches_a_model_on_a_real_daemon_turn` in `crates/marlowe-daemon/tests/terminate_never_reaches_a_model.rs`
  - asserts: The deployment-verified half, and it is why Session C's model-driver seam is a prerequisite rather than a nicety. A `RecordingDriver: ModelDriver` is injected through the new public door, captures every `(ContextView, ExposedSet, CallLimits)` the running daemon hands it, and drives a real turn that spawns a top-agent which raises a real escalation. Asserts `captured.len() >= 1` (vacuity), that the persona marker is present in every captured body (control), and that `TERMINATE_LABEL` and `terminate` appear in none. This is the assertion §3.4 asks for, at the place CLAUDE.md names: the bytes the running process sent, not a body built in a test process.
  - red on: Add a `terminate: Option<AgentOption>` field to `EscalationView` and populate it from the escalation record, then have the loop echo the offered options into the raiser's window: the token appears in a captured body. Reddening the vacuity guard: return `Err` from provider selection so no model call happens — `captured.len() >= 1` fails instead of the zero being reported as success.
- `the_escalation_body_is_absent_from_marlowes_window` in `crates/marlowe-daemon/tests/marlowe_cannot_read_an_escalation.rs`
  - asserts: Plants a distinctive marker (`ESCALATION-BODY-9f31`) inside the escalation's `sentence` and `artifact` content, raises it from a top-agent, then runs one further Marlowe turn through the `RecordingDriver` seam. Asserts the marker appears in NEITHER the serialized `SessionState` the daemon stored for that session NOR any captured `request_body`; and that Marlowe's window DID gain exactly one block, whose text equals the rendered `Notice::EscalationRaised { severity, by }` — so the test distinguishes 'the notification arrived without the body' from 'nothing arrived at all', which is the #15 gap.
  - red on: Change `EscalationDesk::secretary_notice` to take the `Escalation` and interpolate `sentence` into the notice — the marker appears in `SessionState` and both assertions fire. Independently: delete the notice push entirely and the 'exactly one block' assertion fails, so silence cannot pass as containment.
- `the_escalation_explanation_is_in_the_stable_tier_of_the_outbound_body` in `crates/marlowe-daemon/tests/escalation_explanation_is_stable_tier.rs`
  - asserts: Opens a fresh conversation, takes NO escalation at all, and asserts both of §3.3's sentences appear in the `system` role of the first captured `request_body` — establishing that the fact is present before any escalation exists, which is the property 'stable tier, not retrievable memory' actually buys. Then forces a compaction (drive the assembler past 0.70 fill) and asserts they are still there. Control: the persona marker is asserted present in the same bodies.
  - red on: Delete the `state.assert_governance(GovernanceConstraint::asserted(ESCALATION_GOVERNANCE))` line in `daemon.rs`'s session construction — both sentences vanish from the system message. Moving the assertion to fire lazily on the first escalation reddens the first assertion, which is the one that distinguishes this design from the retrievable-memory version.
- `an_option_label_cannot_contribute_a_line_or_move_the_cursor` in `crates/marlowe-contract/tests/escalation_labels.rs`
  - asserts: Feeds `OptionLabel::normalise` and `ValidatedSentence::normalise` a corpus: `\n`, `\r\n`, `\u{1b}[2K\r`, `\u{202E}`, `\u{2028}`, `\u{200B}`, a tag-block codepoint `\u{E0001}`, and a 4,000-char string. Asserts each accepted result is exactly one line, every char satisfies `is_renderable`, and length <= MAX_CHARS. THE TRIM-DEPENDENT CONTROL: asserts first that each raw input actually contained a forbidden character or exceeded the cap — otherwise the test passes on a clean corpus while asserting nothing, which is `adr023_live.rs`'s first-run failure in a new place.
  - red on: Replace `sanitize_line` with `str::trim` in `OptionLabel::normalise`: the newline and ESC cases fail the one-line and `is_renderable` assertions. Reddening the control: replace the hostile corpus with clean strings and the pre-assertion fails, so a vacuous run reports as a failure rather than a pass.
- `terminate_survives_a_hostile_option_list` in `crates/marlowe-surface/tests/escalation_overlay.rs`
  - asserts: Renders the escalation overlay into a 24x80 headless `Buffer` with `MAX_AGENT_OPTIONS` options each at `OptionLabel::MAX_CHARS`, a maximal `TerminationCost` (four `IrreversibleAct` rows), and a long `SourceTrace` host. Walks the buffer and asserts `TERMINATE_LABEL`'s cells are present, at the fixed bottom row, and that no cell in the frame holds a character failing `is_renderable`. Also asserts `EscalationView::new` returns `Err(TooManyOptions)` for a fifth option rather than truncating.
  - red on: Size the modal from the unwrapped line count and render with wrapping — SECURITY-AUDIT B3's actual defect, which ratatui clips silently: the TERMINATE row leaves the buffer and the cell walk finds nothing. Independently: change `new` to `options.truncate(MAX_AGENT_OPTIONS)` and the `Err` assertion fails.
- `the_termination_cost_comes_from_the_journal_and_not_from_the_agent` in `crates/marlowe-daemon/tests/termination_cost_is_journal_derived.rs`
  - asserts: Builds a subtree that really writes 3 files and pushes 0 commits, while the top-agent's option text claims `six hours, 40 files, migration half-done`. Asserts `cost.artifacts == 3`, `cost.irreversible` contains exactly one `FilesWritten { count: 3, .. }` and no `CommitsPushed`, `cost.spend_micros_usd == run.spent.micros_usd` read off the run, and that the strings `40` and `six hours` appear ONLY inside the normalised agent option region of the rendered frame and nowhere in the cost rows.
  - red on: Derive `artifacts` from a field on the `Escalation` record instead of replaying `ToolCompleted` over the subtree — the count becomes 40 and the first assertion fires. Independently: `every_termination_cost_field_is_rendered` in `marlowe-view/tests/` mutates each of the five fields in turn and asserts the rendered rows change, so dropping a row from `TerminationCost::rows` reddens it — that is the #16 guard for this type.

### Contract impact

Three changes, and one of them is smaller than it looks.

**(1) CONTRACTS §5 — `Run` gains `level: AgentLevel`, pinned explicitly.** Note first that §5's pinned `Run` is ALREADY divergent from the code in two directions: the pin lists `result: Option<ContentRef>` which `marlowe-loop/src/run.rs:570-601` does not have, and the code holds a private `trust_floor: TrustClass` which the pin does not list. So `level` could be added privately, with a `level()` accessor, moving no pinned field at all — `trust_floor` set that precedent. I recommend against taking that route quietly: pin `AgentLevel` and the field in §5, and raise the pre-existing `result`/`trust_floor` divergence separately rather than exploiting it. A pinned struct that has silently stopped describing the type is the documentation half of instance #14.

**(2) CONTRACTS gains a new §5.2, "The escalation record."** `Escalation`, `Severity`, `EscalationCategory`, `ValidatedSentence`, `OptionLabel`, `EscalationRoute`, `Recipient`. These cross loop -> daemon -> surface, which is CONTRACTS' own trigger ("before any code crossing a boundary"). Pinning a shape for the first time is cheap; moving it after D and E build on it is not.

**(3) `SpawnRequest` — NOTHING, and this is a deliberate refusal.** The measured fact stands: §5 pins only `fn spawn(&self, req: SpawnRequest) -> RunId`, and `grep -n SpawnRequest docs/design/CONTRACTS.md` returns one hit at line 941. This design adds no field to it. Session C's `role` field (ROADMAP C item 4) is the change that will pin the shape; adding `kind: AgentKind` alongside it would put a second unread field into the same pinning act.

**Not touched:** CONTRACTS §13's `TurnEvent` gains nothing, because the escalation window rides the ADR-055 control-plane listener rather than the conversation socket. §12.1's `MemoryHost` is untouched and no `ingest_external` caller is proposed — `grep -rn "ingest_external(" --include=*.rs crates/*/src/` still returns two definition hits and zero call sites. `Channel::Agent` gains no producer.

**`LoopOutcome::Escalated { question: String }` -> `Escalated(EscalationId)`** is a change to an unpinned type (`LoopOutcome` appears nowhere in CONTRACTS.md) and needs no contract act — only `daemon.rs:2899`'s `("escalated", question.clone())` and the child-return `note` arm follow, and the latter gets simpler rather than richer.

### Guarded

['crates/marlowe-loop/src/driver.rs']

### For the human

["**The `ModelStep::Escalate` variant is a §13-guarded edit and needs an explicit approval.** `driver.rs` entered `PROTECTED` at M3-D3 as 'the memory and approval ports'. Adding a variant to `ModelStep` and a new `EscalationRequest` type in that file is the change; `Ask` is kept and narrowed to the secretary rather than repurposed. A `DECISIONS.md` entry should arrive with it, per the hook's own convention. Nothing else in this design touches a guarded path — `profile.rs` and `adjudicate.rs` are deliberately untouched, and `EventKind` lives in `journal/event.rs`, which is not guarded (only `journal.rs` and `signature.rs` are).", "**Is the ADR-023 latch per-run or per-session?** §2.1's argument for the entire liaison pattern — 'a Marlowe who ingests one finding can never compose a target again, for his life' — is only true if the latch is per-session. In the shipped daemon it is not: `daemon.rs:2486`'s `Run::root` is rebuilt every turn at `trust_floor: UserAsserted` (`run.rs:680`). This is NOT a new finding — SECURITY-AUDIT.md §8 states it, ROADMAP's C row item 2 carries it, and M3 B2 already burned a session re-deriving it. But it is the load-bearing premise of the design I am recommending, and it is the human's per ADR-032's own note that the same question about session-vs-run scope is theirs. If the latch stays per-turn, §3.2's containment is stronger than it needs to be, and someone will eventually argue for relaxing it on that basis.", "**Is `EscalationRequest::artifact` (a `ContentRef`) a Target under ADR-023?** The recipient is fixed by `escalation_route`, so no recipient is composed. But a ContentRef is an identifier chosen by a model, rendered to a human as something to open. This is the same unanswered question ROADMAP's C row raises about a model naming its own model role ('a downgrade and an upgrade are both attacker-useful, and a model name is not in layer 3's list'). Both should be answered together, and the answer belongs in `run`'s manifest as an `ArgumentRole`, which is where the adjudicator would read it.", "**M3-DESIGN §12 item 1: does Marlowe learn an escalation's OUTCOME?** The design as specified tells him a `critical` escalation was raised and nothing else. It is silent on what he learns when the user chooses. `EscalationDesk::secretary_notice` has no outcome parameter, which is the safe default and also a decision I should not take: 'the top-agent was terminated' is arguably a fact Marlowe needs in order not to keep referring to work that no longer exists.", "**A human-readable agent name.** I recommend `AgentLabel::for_run(level, run)` -> `top-agent 4f2a91`, with zero model bytes, because a model-chosen display name on a decision surface can call itself `Marlowe`. §3.2's own example is `CodeProjectLeader`. If a real name is wanted, it is a `SpawnRequest` field and should land in the same pinning act as Session C's `role` field, not separately.", "**The fourth model role is not named here**, and the escalation window's own model routing is left as `ModelRoute::Worker` unchanged. Nothing in this design chooses a role for a top-agent."]

### Risks

["**The §11 acceptance row is the single most likely place this goes quietly wrong, and it is instance #15's exact shape.** 'TERMINATE present in an agent's `request_body` — 0 occurrences' reads identically on a build where no model call happened at all, where the body serialized empty, and where every guard was deleted. That is why the persona-marker positive control and the `captured.len() >= 1` vacuity guard are not optional extras: without them the row is a proxy that moves with the thing it is meant to measure. Anyone tempted to drop the control 'because the zero is what we care about' has recreated the defect.", "**Instance #16 on `TerminationCost`.** Five fields computed from the journal and rendered by one function is exactly the `inline_threshold_bytes` shape: a producer that computes a field the renderer drops, with a green test asserting the field's value. `every_termination_cost_field_is_rendered` mutates each field and asserts the rendering changes; if that test is ever weakened to assert field values instead, the whole type becomes decorative and §3.4's 'the harness states the cost because the agent would lie about it' silently reverts to the agent's numbers.", "**The saturated floor, and it is the reason `Pending::at` exists.** Inside an escalation every value is `UntrustedContent` — the option labels, the sentence, the artifact, the forwarded id. ADR-023's floor reads 'blocked' for all of them and therefore says nothing about any of them; this is the ADR-036 §5 case exactly. The question that survives is who asserted it, and the desk is the authority. Any future shortcut that lets a run forward an escalation by id without the `at == by` check reopens it, and no existing guard would notice — the floor would still be latched, the banner would still be correct, and the wrong escalation would move.", "**Instance #17 is one refactor away throughout.** Three places invite a zero: the quarantined reader's inability to escalate, a master's inability to hold working tools, and `MAX_AGENT_OPTIONS`. All three are structural here — a missing enum arm, an absent tool id, and a construction-time refusal — but each reads naturally as a budget dimension, and `Budget::exhausted` compares `spent >= budget`. A reviewer who 'tidies' any of them into a counter gets a run that pauses before its first model call while looking perfectly configured.", "**Instance #14 aimed at the new file.** `crates/marlowe-loop/src/escalation.rs` and `crates/marlowe-daemon/src/escalation.rs` will eventually be split or renamed, and if either is later added to `PROTECTED`, its row must go into CLAUDE.md's table in the same commit and into `EXPECTED_PROTECTED` in `boundary_hook.rs` — the #19 fix. A guard derived from the list it checks cannot see the list shrink.", '**The escalation window is a second decision surface, and the first one has three open findings.** SECURITY-AUDIT B1 (terminal escape injection on the CLI render path), B2 (CLI approval prompt unfiltered and unbounded) and B3 (TUI overlay clips its own consequence line) are all unclaimed and all describe the approval overlay. This design routes every agent byte through validating constructors and bounds the option list, which is the right shape — but if the CLI path renders the escalation the way `agent.rs` renders an approval today, B1 and B2 arrive intact on the higher-consequence surface. The CLI renderer is in scope for whoever builds this, and it is not a new finding.', "**Ollama capacity is measured on THIS machine, TODAY, with 5,086 MiB held by the desktop.** The escalation path must not add a model call: `provenance_from_journal` and `TerminationCost` are journal replays and touch neither the embedder nor the reranker. That is deliberate, because ADR-044 resolves the embedder's provider against free VRAM at load and the measurement says 1,053 MiB free — `AGENT-DIRECTORY.md` §2's 'headroom for the KV cache, the embedder and the reranker' is wrong, and an escalation window that wanted a model would silently push the embedder to CPU with a correct-looking log line. Any later change that summarises an escalation for the user re-opens this, on numbers that must be re-measured rather than cited.", "**A8's arm switch must not be a default.** `EscalationArm::FreeText` is a control expected to fail and exists only for the red-team harness. It should refuse to construct without an explicit flag — a load-time error, not a permissive default — or the arm that §9.1 predicts will fail becomes reachable in the shipped product by omission, which is the 'defaults that make a mismatch unobservable' family in its most expensive form.", '**`Engine::spawn`\'s existing `composes_spawn_targets` check now interacts with the level table.** The level is derived from `req.tools.contains("run")`, and a latched run is already refused a spawn that names any tool. So a latched master cannot create another master — which is correct, and is an emergent property nobody declared. It should be asserted rather than left to inspection, because a future relaxation of `composes_spawn_targets` would silently change who can hold the create grant.']
