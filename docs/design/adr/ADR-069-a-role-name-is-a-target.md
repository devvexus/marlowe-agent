# ADR-069 · A role name is a target — and Session C earns the right to say so by giving the field a reader on all three driver paths

**Status:** PROPOSED — needs the human's approval. DESIGN ONLY, NO CODE.

It edits a §13-guarded file (`crates/marlowe-loop/src/profile.rs`), it leaves the naming of the
fourth model role to the human, and it records one thing the reviewed design asked for that **cannot
be built as specified** (§5.3). Nothing here has been approved by anyone.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | ADR-008 by reference only — its 2026-08-10 amendment (`DECISIONS.md:1038`) asks for a fourth `ModelRoute` variant that has never been added, and this ADR does not add it. Corrects ROADMAP's M3 Session C row where it says CONTRACTS §5 pins `SpawnRequest` (§9). Corrects `ollama.rs:186`'s doc comment for `MODEL_CONTEXT_CEILING` (§5.3) |
| **Depends on** | ADR-023 (the `(action, target)` latch), ADR-008 (tiered routing), ADR-057 (§1 `from_args`, §2 the receipt, §5 structural withholding), ADR-041 (the group unit and `BudgetShare`), ADR-044 (the embedder's provider resolves against free VRAM at load), ADR-046 (OpenRouter is opt-in), ADR-060 (the llama.cpp path), M3-DESIGN §1, §7, §9.1, AGENT-DIRECTORY §2 / §2a |
| **Contract change** | **None.** `CapabilityProfile.model_route: ModelRoute` is already pinned at `CONTRACTS.md:952`; it gains a comment and no schema moves. `CallLimits`, `ModelDriver` and `SpawnRequest`'s **shape** are pinned nowhere — `grep -n SpawnRequest docs/design/CONTRACTS.md` returns exactly one hit, `:941`, which pins `fn spawn(&self, req: SpawnRequest) -> RunId`, the method and not the fields |
| **Code change** | Specified, not written. `profile.rs` (§13-guarded, human approval required), `budget.rs`, `engine.rs`, `ollama.rs`, `llamacpp.rs`, `openrouter/driver.rs`. **`driver.rs` is deliberately NOT touched: `SpawnRequest.route` is Session G's and the human's** |

---

## 1 · The question, and where it came from

ROADMAP's M3 Session C row asks it in its own words, and this ADR is the answer to that sentence and
nothing wider:

> **the security question §3 raises and does not answer: if a spawner names a model, is that name a
> target under ADR-023? A downgrade and an upgrade are both attacker-useful, and a model name is not
> in layer 3's list.**

**The answer is that a model role is a TARGET.** Not a payload, and not a third thing.

But the answer alone is worth very little this session, and saying why is the whole ADR. **The field
that would carry it has no reader at all today.** Measured on HEAD `03fb1d6`, 2026-08-30:

```
$ grep -rn "\.model_route()" --include=*.rs crates/
                                           # (nothing)
```

`CapabilityProfile::model_route()` is defined at `crates/marlowe-loop/src/profile.rs:280` and called
by nothing in the workspace. `OllamaDriver::request_body` hardcodes the route it uses:

```rust
// crates/marlowe-provider/src/ollama.rs:300
let model = self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator).to_string();
```

`Engine::spawn` hardcodes the child's:

```rust
// crates/marlowe-loop/src/engine.rs:2654 — the fourth argument to CapabilityProfile::new
ModelRoute::Worker,
```

and every production `Routing` is `Routing::uniform`, so `model_for` returns the same string for all
three roles regardless. **Six production sites**, re-measured on HEAD rather than carried:

```
$ grep -rn "Routing::uniform" --include=*.rs crates/*/src/
crates/marlowe-daemon/src/daemon.rs:1263
crates/marlowe-daemon/src/daemon.rs:1338
crates/marlowe-daemon/src/daemon.rs:1503
crates/marlowe-daemon/src/daemon.rs:1889
crates/marlowe-daemon/src/daemon.rs:1976
crates/marlowe/src/agent.rs:47                  # the CLI / --eval-adapter path
```

So the entire subagent tree runs on the secretary model today, `ModelRoute::Worker` at
`engine.rs:2654` reaches nothing, and ADR-008's cost lever — *"strong model for orchestration, fast
cheap models for subagent search"* — is declared in `routing.rs`'s header, pinned in `CONTRACTS.md`,
and inert in the product.

**That is instance #16, live at HEAD, and it is not in `SECURITY-AUDIT.md`'s family-#16 roll.** The
roll at `SECURITY-AUDIT.md:135` names eight — `BASH_TIMEOUT_MS`, `manifest_provenance()`,
~~`EgressPolicy::grant`~~ (closed 2026-08-29), `NeedsApproval { tier }`, `inline_threshold_bytes`,
invariant 8's profile-root rule, `NoControl`, and `recall`'s maturation label. `model_route` should
be the ninth, **LOW severity — a cost and quality defect, not a containment one** — and
`Routing.summarizer` the tenth (§5.2). I checked the list before claiming the absence.

**Which is why declaring the answer is not the deliverable.** Shipping a model-facing `role`
parameter on `run` now, declared `ArgumentRole::Target`, would put a green manifest test
(`run.role_of("role") == Some(Target)`) on top of a field nothing honours: instance #16 stacked on a
dead path, which is the exact pair ADR-057 §4 took a milestone to find and which stayed invisible
because neither half was visible from the other. **Read the field before letting anyone name it.**

---

## 2 · Why a role is a target, argued on the mechanism that actually runs

### 2.1 · `adjudicate` is NOT on the spawn path, and the reviewed design's argument named it anyway

The first draft of this decision argued from `adjudicate.rs`'s §2 target loop —
`manifest.role_of(name).unwrap_or(ArgumentRole::Target)` at
`crates/marlowe-permission/src/adjudicate.rs:304`, with the fail-closed default meaning a role could
be added without touching a §13-guarded enum. **The conclusion it drew was right and the reason was
wrong, and a reader acting on the stated reason would look for the check in a loop that never runs
for a spawn.**

That loop is reached only from `tool_batch`. A `run` call becomes `ModelStep::Spawn` at exactly one
construction site in the workspace —

```
$ grep -rn "ModelStep::Spawn(" --include=*.rs crates/*/src/
crates/marlowe-provider/src/ollama.rs:1045:  "run" => ModelStep::Spawn(marlowe_loop::SpawnRequest::from_args(args)),
```

— and goes from the loop's match at `engine.rs:1330` straight to `Engine::spawn`, whose own comment
says so:

> `ModelStep::Spawn` goes straight here from the loop's match and never reaches `self.adjudicator`,
> which only `tool_batch` calls. — `crates/marlowe-loop/src/engine.rs:2582`

**A correction to the critique's phrasing, because it matters for test coverage.** *"The only such
mapping in the workspace"* is true of the *construction site* and could be misread as *"only the
Ollama provider can spawn"*. All three drivers share that one function: `LlamaCppDriver` calls
`crate::ollama::parse_step` at `llamacpp.rs:1449` and `OpenRouterDriver` calls
`marlowe_provider::ollama::parse_step` at `openrouter/driver.rs:677`. **One definition, three
providers** — which is why the manifest↔mirror coupling test (T5, §7) covers all three at once, and
why a second provider writing its own mapping would be the two-definitions failure `driver.rs`'s own
`from_args` header already refuses.

### 2.2 · The mirror is where the argument lives

The enforcement for a spawn is a hand-written mirror of `run`'s manifest:

```rust
// crates/marlowe-loop/src/engine.rs:3237
fn composes_spawn_targets(req: &SpawnRequest) -> bool {
    !req.tools.is_empty()
        || req.grant_tokens.is_some()
        || !matches!(req.orphan, OrphanPolicy::Terminate)
}
```

fired at `engine.rs:2600` under `blocks_composed_targets(run.trust_floor())`.

`orphan_policy` is a **closed two-value enum that chooses only a child's lifetime**. It is declared
`ArgumentRole::Target` in `crates/marlowe-tools/src/builtin.rs:691-692` and it is enforced by the
third clause above. **A closed enum that chooses the inference engine executing every subsequent
decision a child makes is a target a fortiori.** Calling a role a payload retroactively de-targets
`orphan_policy` by the identical argument, and `orphan_policy` is settled.

The supporting structural point: `model_route` already sits in the pinned `CapabilityProfile`
(`CONTRACTS.md:952`) beside `exposed_tools` and `egress`, which are uncontroversially the child's
capability declaration. The role is already classified, in the pinned contract, as part of what a
child *is*.

**Therefore: no edit to `crates/marlowe-permission/src/adjudicate.rs` or `taint.rs`.** Same
conclusion as the first draft, different and correct reason.

---

## 3 · What Session C ships, and what it withholds

**Withheld structurally, which is the ADR-057 §5 treatment of `share` and `reads_untrusted`:**
`SpawnRequest` gains **no** `route` field, and `run`'s manifest gains **no** `role` parameter. A
model cannot reach what it cannot name. `SpawnRequest::from_args` (`driver.rs:115`) is total and
reads only the five declared parameters; a spelling it does not read is a spelling that does not
exist.

**Built, so that the answer becomes enforceable rather than decorative:** the route is threaded from
the profile through `CallLimits` into all three drivers' request bodies, and the child's route stops
being a constant.

### 3.1 · `crates/marlowe-loop/src/profile.rs` — §13-GUARDED. A HUMAN MUST APPROVE THIS EDIT

```rust
impl ModelRoute {
    /// The route a child of a run at `parent` gets.
    ///
    /// **A STOPGAP, and it must be read as one.** The route here is a function of the child's
    /// DEPTH. `AGENT-DIRECTORY.md` §2 requires it to be a function of the child's KIND — *"the
    /// spawner names the model: when the harness emits a `run` it says which role it wants, and
    /// the corresponding model serves it"* (`AGENT-DIRECTORY.md:111-112`) — and M3-DESIGN §1 has
    /// FIVE levels, with §1.1 having Marlowe declare `master` or `worker` at spawn. This function
    /// collapses all of them to one route, so three of the four configured roles are unreachable
    /// and `AGENT-DIRECTORY.md` §2a's PER-ROLE admission queue has exactly one role. The
    /// kind -> route table is Session G's and the human's. **Do not cite this function as the
    /// answer to "how does a child get its role".**
    ///
    /// **Total, and a function of the parent alone** — no argument, no model input, so there is no
    /// value here for untrusted content to have chosen. Replaces the hardcoded `ModelRoute::Worker`
    /// at `engine.rs:2654`.
    ///
    /// No wildcard arm: ADR-008's 2026-08-10 amendment (`DECISIONS.md:1038`) asks for a fourth
    /// variant, and when it lands this is a compile error rather than a silent inheritance.
    pub fn for_child(parent: ModelRoute) -> ModelRoute {
        match parent {
            ModelRoute::Orchestrator => ModelRoute::Worker,
            ModelRoute::Worker       => ModelRoute::Worker,
            ModelRoute::Summarizer   => ModelRoute::Summarizer,
        }
    }
}
```

Nothing else in the file changes. `CapabilityProfile::new`'s signature, its three quarantine
invariants, the hand-written `Deserialize` at `profile.rs:353-379` that routes through the validating
constructor, and `grant_egress_host` are untouched, and **no new mutable route into the struct is
opened** — the reason ADR-032 gave for putting the granted egress set on the profile rather than
beside it on the `Run` applies here one field over.

### 3.2 · `crates/marlowe-loop/src/budget.rs` — not guarded

```rust
pub struct CallLimits {
    pub max_output_tokens: u64,
    /// Which model this call goes to. ADR-008: routing is by task role, declared in
    /// `CapabilityProfile`. **No default, no `Default` impl, no `#[serde(default)]`.**
    pub route: ModelRoute,
}

impl Budget {
    /// The cap handed to the provider for the next call. **This is the line.**
    pub fn call_limits(&self, spent: &Budget, route: ModelRoute) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens, route }
    }
}
```

**The cost, measured rather than estimated, because the reviewed design was wrong about it by ~4x —
and a session that budgets for 8 edits and finds 32 reaches for `..Default::default()` under time
pressure, which is precisely the silent inheritance the missing `Default` exists to prevent.**

```
$ grep -rn "CallLimits {" --include=*.rs crates/ | grep -v "pub struct CallLimits" | wc -l
32
$ ... | sed 's/:[0-9]*:.*//' | sort -u | wc -l
17
```

**32 construction sites across 17 files** on HEAD `03fb1d6`. The reviewed design said *"~8, all in
tests"*; the critique measured 31/17 on `186b5d5`; the checkout has moved and it is 32 now. Four are
under `examples/` (`crates/marlowe-openrouter/examples/live_probe.rs` and three in `marlowe-exec`),
which **`cargo test` does not compile by default**, so those four break a `cargo build --examples`
rather than the suite. **The 32 mechanical edits ARE the deliverable, not an obstacle to it.**

The compile-error-at-every-site property is the entire argument for the field having no default. It
holds only while `CallLimits` has no `Default` impl and no `#[serde(default)]`, and that is written
down here so a later session cannot add one as a convenience.

### 3.3 · `crates/marlowe-loop/src/engine.rs` — not guarded

```rust
// :794   was: let limits = run.budget.call_limits(&run.spent);
        let limits = run.budget.call_limits(&run.spent, run.profile.model_route());

// :2654  was: ModelRoute::Worker,   (the 4th argument to CapabilityProfile::new)
        ModelRoute::for_child(run.profile.model_route()),

// :2728  the ADR-057 §2 receipt gains one clause — the ROLE NAME, never a model tag
        "[spawned] tools: {granted_tools} · budget: {} tokens · model: {} · orphan: {} · returns: {}",
        //                                            ^ "orchestrator" | "worker" | "summarizer"

// :2601-2606  the refusal sentence gains three words, ready for Session G
//   "...so a child's tools, budget, orphan policy AND MODEL ROLE can no longer be composed here..."

// :2678-2687  the RunSpawned payload — AUDIT ONLY, EXPLICITLY NOT THE ENFORCEMENT
        "model_route": child_route,
```

**One buildability detail the reviewed design got wrong, stated because an ADR whose code does not
compile is worth less than one that says why.** The design writes the journal line as
`"model_route": child_profile.model_route()`. `child_profile` is **moved** into `Run::child` at
`engine.rs:2669`, four lines before the `self.record(...)` call at `:2673`. `ModelRoute` derives
`Copy` (`profile.rs:41`), so the fix is one line above the move — `let child_route =
child_profile.model_route();` — and the payload reads `child_route`. `ModelRoute` also derives
`Serialize` with `#[serde(rename_all = "snake_case")]`, so the emitted value is `"worker"`, the
spelling `profile.rs:456` already asserts.

**Why the receipt clause is not optional.** ADR-057 §2's principle is written at `engine.rs:2696-2699`:

> Six of a spawn's seven fields are supplied by rule when the parent does not name them, and
> CLAUDE.md's standing warning is about *"defaults that make a mismatch unobservable"*. The answer is
> not to refuse a model that omitted a field — it is to say what it got.

A harness-chosen route the parent cannot observe is the pre-ADR-057 budget in a new place: the parent
asked for a child, got one on some model, and had no way to find out which. Under a non-uniform
routing that is the difference between a parent that knows its child ran on a 2B and one that reads a
thin result as a task failure. The role name is harness-authored and a closed enum, so unlike
`returns` it needs no `sanitize_line`.

---

## 4 · All three drivers read the field — and one of them cannot, which is this ADR's most useful paragraph

### 4.1 · The critique's fatal finding, carried in rather than hidden

**Adversary verdict on the reviewed design: `sound-with-fixes`.** Its fatal finding, in its own
words:

> The design's remedy for instance #16 ships a fresh instance of #16: it adds `CallLimits.route` and
> names exactly one reader (`crates/marlowe-provider/src/ollama.rs:300`), while the daemon ships
> three `ModelDriver` implementations.

That is correct and it is why this ADR has its present shape. `ModelProviderChoice`
(`crates/marlowe-daemon/src/daemon.rs:63`) has three variants — `Ollama`, `OpenRouter { model }`,
`LlamaCpp { endpoint, sampling }` — and the daemon selects among all three (`daemon.rs:2115`,
`:2282`, `:2367`). `LlamaCppDriver::request_body` sends `"model": self.model` at `llamacpp.rs:1069`;
`OpenRouterDriver::request_body` sends `"model": self.model` at `openrouter/driver.rs:210`. Neither
holds a `Routing`. Neither would read `limits.route`.

**And it is worse than the status quo.** Today `model_route` is visibly dead on every path. Wire it
on one of three and the next session's `grep` for a reader returns a hit and reads as a **positive**
result on two paths where nothing honours it — instance #18's shape, a diagnostic that retires by
going green, aimed at the fix for instance #16.

### 4.2 · Ollama and OpenRouter: a real reader, one line each

```rust
// crates/marlowe-provider/src/ollama.rs:300
let model = self.routing.model_for(limits.route).to_string();

// crates/marlowe-openrouter/src/driver.rs:210 — OpenRouterDriver takes a `Routing`, not `model: String`
"model": self.routing.model_for(limits.route),
```

OpenRouter is a hosted service that genuinely dispatches on the `"model"` field, so the value sent
decides which weights answer. The reader is honest there.

**One consequence recorded rather than fixed.** `routing.rs`'s header calls `Routing` *"ADR-008's
tiered routing, as a table over **local** models"*, and its only constructor guard is `is_cloud_tag`,
which matches Ollama tag syntax (`-cloud`, `:cloud`, `-cloud:`, `:cloud-`, `routing.rs:29-33`). An
OpenRouter model id such as `anthropic/claude-…` matches none of those, so handing a `Routing` to
`OpenRouterDriver` makes that guard **inert on that path**. It does not become wrong — it becomes
silent, which is the shape this project logs. The real gate on OpenRouter is ADR-046's opt-in, stated
in the variant's own doc at `daemon.rs:67`: *"Opt-in only, and never reachable except by an explicit
`--provider openrouter`."* **Naming this is the whole mitigation**; generalising `Routing` beyond
local tags is a separate decision and is not taken here.

### 4.3 · llama.cpp CANNOT be routed, and the critique's fix would manufacture instance #15 there

**This is the finding.** The critique's fix (a) says *"`LlamaCppDriver` … takes a `Routing` instead
of a bare `model: String`, and each `request_body` does
`let model = self.routing.model_for(limits.route).to_string();` — one line per driver, three
readers."* **On the llama.cpp path that line changes a string in a request and cannot change which
weights answer it.** Two doc comments in the code say so, and neither was written for this argument:

> Sent as `"model"`. `llama-server` serves whatever it was launched with and **does not route on
> this**, but it is what the request records, so it is the configured name rather than a placeholder.
> — `crates/marlowe-provider/src/llamacpp.rs:952-954`

> The model NAME is not in here: `llama-server` serves whatever it was launched with, and
> `config.model` is what this daemon believes that to be.
> — `crates/marlowe-daemon/src/daemon.rs:73-74`, on `ModelProviderChoice::LlamaCpp`

So a test asserting `body["model"] == "work-m"` on the llama.cpp arm would be **green on a build
where every call in the tree runs the orchestrator's weights**. That is instance #15 exactly — an
assertion that reads identically whether or not the mechanism works — manufactured inside the fix for
instance #16, one layer deeper than the stacking the critique correctly refused. **A three-reader
grep would then return three hits, two honest and one cosmetic, and the cosmetic one would carry a
green test.**

**The decision is instead the critique's own fix (b), applied to this arm only: a load-time refusal.**

```rust
// crates/marlowe-provider/src/llamacpp.rs — LlamaCppDriver::build
//
// `llama-server` serves ONE weight set, chosen when it was launched. A routing table naming more
// than one distinct model is therefore a configuration this driver cannot honour, and the only
// honest response is to refuse it by name at load rather than to send a routed string over
// unrouted weights.
if routing.models().len() > 1 {
    return Err(ResolveError::UnroutableRouting {
        models: routing.models().iter().map(|m| m.to_string()).collect(),
    });
}
```

With the refusal in place, `self.routing.model_for(limits.route)` is **provably** route-invariant on
that path, so the reader may land and the field is genuinely read on all three — but the property the
llama.cpp test asserts is **the refusal**, never the body byte. Stated as a rule so a later session
cannot add the tempting assertion: **no test on the llama.cpp arm may assert that `body["model"]`
differs by route.** It cannot differ, and a test saying it does would be asserting the string rather
than the fate of the tokens — `persona/v1.md` *loaded* versus the persona text being in the request
body, one subsystem over.

`ResolveError` already exists and `LlamaCppDriver::build` is already documented as the place where
*"every load-time refusal is here, so a caller cannot skip one"* (`llamacpp.rs:965-967`). The variant
is additive to an unpinned error enum in an unguarded file.

---

## 5 · Where every field is READ, and what is DROPPED for lack of a reader

Instance #16 is this project's most-repeated defect, so this section is a table with a function name
in every row or an explicit admission that there is none.

| Field / item this decision introduces | The function that reads it |
|---|---|
| `CallLimits.route` | `OllamaDriver::request_body` (`ollama.rs:300`), `OpenRouterDriver::request_body` (`openrouter/driver.rs:210`), `LlamaCppDriver::request_body` (`llamacpp.rs:1069`, provably route-invariant behind the §4.3 refusal) |
| `Budget::call_limits`'s new `route` parameter | the Engine's model-call site, `engine.rs:794` — the one place a `CallLimits` is built in production outside `budget.rs` |
| `ModelRoute::for_child` | `Engine::spawn`, `engine.rs:2654`, as the fourth argument to `CapabilityProfile::new` |
| `CapabilityProfile::model_route()` (**exists, zero callers today**) | gains two: `engine.rs:794` and `engine.rs:2654` |
| `ResolveError::UnroutableRouting` | `LlamaCppDriver::build`, surfaced by the daemon's existing `ResolveError` handling at `daemon.rs:2367` |
| The receipt's `· model: {role}` clause | the parent's own window, and `receipt_for` (`spawn_from_a_model_reply.rs:249`) in T7 |
| `RunSpawned`'s `"model_route"` payload key | **AUDIT ONLY. Its only readers are T2 and a human reading the journal, and that is stated in the code comment as well as here.** A future session reading *"the route is journalled"* as *"the route is checked"* repeats the `inline_threshold_bytes` reading exactly |

### 5.1 · Dropped: `SpawnRequest.route`, `run`'s `role` parameter, `ModelRoute::strength`, `ModelRoute::may_grant`

**Not written in Session C, for lack of a reader that could honour them**, and that is a preferred
outcome rather than a deferral. Each is specified in §11.1 so the wrong-order change cannot be made
quietly, and each lands in Session G *with* its enforcement clause in the same commit.

### 5.2 · NOT closed: `ModelRoute::Summarizer` still has no reader after Session C

**The reviewed design presented the reader gap as closed. One third of `Routing`'s table stays dead.**

No `CapabilityProfile` constructor produces `Summarizer`: `quarantined_reader()` is `Worker`
(`profile.rs:147`), `consolidation()` is `Worker` (`:165`), `interactive()` is `Orchestrator`
(`:222`), `interactive_with` inherits `base.model_route` (`:265`). `for_child` can only return
`Summarizer` from a `Summarizer` parent, which nothing constructs.

The real compaction summarizer is a **different port**:
`pub trait Summarizer { fn summarize(&mut self, view: &ContextView) -> String; }` at
`crates/marlowe-loop/src/driver.rs:330-331`, implemented by `PassthroughSummarizer` at
`crates/marlowe-daemon/src/daemon.rs:633-635`. It never sees a `CallLimits` and therefore can never
see a route.

So `routing.rs:39`'s `summarizer` field stays unreachable, and
`routing_is_by_role_and_the_table_is_the_only_place_a_model_is_named` (`routing.rs:117`) **stays green
over it** — because it constructs its own `Routing` inside the test and asks `model_for` directly.
That test would read identically if no run in the product ever reached the table, which is the exact
reading the design says it exists to prevent.

**Routing compaction requires changing the `Summarizer` trait signature, in `driver.rs`, which is
§13-guarded: Session G, and the human's.** Until then `Routing.summarizer` belongs in
`SECURITY-AUDIT.md`'s family-#16 roll as a tenth entry alongside `model_route`. **Do not claim the
gap is closed while a third of the table has no reader.**

### 5.3 · WHAT CANNOT BE BUILT AS SPECIFIED: the critique's `Availability::WindowTooSmall`

The critique's fix for the two-numbers-disagreeing defect asks for a load-time refusal:

> Extend `Availability::probe` (`crates/marlowe-provider/src/ollama.rs:128`), which already iterates
> `routing.models()` at `:152` against `/api/tags`: for each routed model also read its
> `context_length` (`GET /api/show`; the measurement in this session's brief read **32768** for all
> three roles from `/api/ps`) and add `Availability::WindowTooSmall { model, reports, configured }`,
> refusing at startup when any routed model's window is below the configured `context_tokens`.

**The mechanism is right. The number it was justified with is a proxy, and measuring it refutes the
premise.** Taken on this machine, 2026-08-30, with nothing resident:

```
$ curl -s http://127.0.0.1:11434/api/ps
{"models":[]}

$ for m in marlowe-dawn:9b-super marlowe-mini:4b-super marlowe-mini:2b; do
    curl -s http://127.0.0.1:11434/api/show -d "{\"model\":\"$m\"}"   # model_info
  done
marlowe-dawn:9b-super      qwen35  262144
marlowe-mini:4b-super      qwen35  262144
marlowe-mini:2b            qwen35  262144
```

**Three things follow, and each kills a version of the check.**

1. **32,768 is not what any model reports. It is `DEFAULT_CONTEXT_TOKENS` — the value Marlowe
   *sends*.** `crates/marlowe-provider/src/ollama.rs:180`: `pub const DEFAULT_CONTEXT_TOKENS: u32 =
   32_768;`, carried on every request as `num_ctx` (`ollama.rs:545`). A `/api/ps` read of
   `context_length` reports the **loaded** window, which Ollama sets *from that very request*. So the
   proposed check would compare `num_ctx` against a number derived from `num_ctx` — a load-time
   refusal that can never fire, reading the same whether or not it works. **Instance #15 inside the
   fix for the two-numbers-disagreeing hazard.**
2. **`/api/ps` cannot answer at load in any case.** It returned `{"models":[]}` above. At daemon
   start nothing is resident, so the check reads an empty array and either refuses everything or
   passes everything vacuously. The discriminating source is `/api/show`'s
   `model_info["<arch>.context_length"]`, which is available before a load.
3. **Read from `/api/show`, the check is correct and would never fire on this machine.** All three
   roles report 262,144 against a configured 32,768. That is a *true negative*, not evidence the
   check works, so **it must ship with a negative control**: a `Routing` naming a model whose
   reported window is genuinely below `context_tokens`, asserted refused by name. Without that arm
   the test is green on a build where `WindowTooSmall` is never constructed.

**The repo already holds the correct number and one stale comment beside it.** `ollama.rs:186`
declares `pub const MODEL_CONTEXT_CEILING: u32 = 262_144;` — *"What `qwen3.5:9b` reports it supports,
recorded so a model swap has something to compare to"* — and the read above matches it exactly for
all three current roles. **Its doc comment's closing words, *"Recorded, not used"*, are false**, and I
checked before filing it as another family-#16 entry: `crates/marlowe/src/main.rs:341` reads it as
the upper bound of the `--context-tokens` flag, and `agent.rs:133` and `context_window.rs:75` read it
too. The comment needs correcting, not the constant. **That near-miss is why this ADR re-measures
every number it repeats.**

### 5.4 · What still does not follow the route, stated as a live hazard rather than a fixed one

Even with §5.3's refusal built, three things continue to describe the **orchestrator** while the
bytes may go elsewhere:

| Thing | Where it is decided |
|---|---|
| The window (`num_ctx`, and the assembler's packing target derived from it) | one value for the driver's life: `daemon.rs:2120-2121`, `.with_capability(capability_for(&self.config.model)).with_context_tokens(self.config.context_tokens)`; sent at `ollama.rs:545` |
| The `max_tokens` clamp | `context_tokens / 4` at `ollama.rs:541`, `llamacpp.rs:1080`, `openrouter/driver.rs:214` |
| The user-facing tool-call reliability figure | `model_disclosure: capability_for(&self.config.model).disclosure()`, `daemon.rs:1390` (also `:1314`) |

`ollama.rs`'s own field doc records this failure from M2 C2e in the same words — *"a 262,144-token
model ran in a 2,048-token window… the assembler was packing to 32,000: **two numbers, disagreeing**,
with §6's compaction trigger computed from the wrong one"* (`ollama.rs:228-234`). **Session C does not
close it and must not claim to.** It is inert today because production is `Routing::uniform`, and it
goes live the day Session G configures three tags. The load-time refusal in §5.3 bounds the worst
case (a routed model that cannot hold the configured window); making the window, the clamp and the
disclosure *per-route* is a `daemon.rs` change, another agent holds that file, and it is Session G's.

---

## 6 · Why the alternatives lost

**1. A model role is a PAYLOAD — content the child reasons about, like `task` and
`output_contract`.** Payload in this codebase means prose handed to the child; a target is a value
the harness itself acts on. The route is consumed by `Routing::model_for` inside the harness and is
never shown to the child, and it selects the engine that composes every target the child will later
emit — upstream of `exposed_tools`, which is uncontroversially a Target. Decisive: `orphan_policy` is
a closed two-value enum choosing only a lifetime and it is already `Target`
(`builtin.rs:691-692`); calling the route a payload de-targets it by the same argument.

**2. A third `ArgumentRole::Hint` variant, for values that are neither target nor payload.**
`adjudicate.rs:304` reads `manifest.role_of(name).unwrap_or(ArgumentRole::Target)` — the default for
an undeclared name is Target, deliberately, so a tool cannot accept a target it never listed. A third
variant turns a fail-closed binary into a three-way choice and puts all eleven builtin manifests up
for re-audit inside a §13-guarded file, to answer a question the existing binary already answers.

**3. Ship the model-facing `role` parameter on `run` in Session C.** §1: the field has zero readers,
`request_body` hardcodes `Orchestrator`, production routing is `uniform`. The parameter would be
adjudicated correctly and honoured by nothing, with `run.role_of("role") == Some(Target)` green on
top — instance #16 layered on a dead path.

**4. A new `AgentLevel { High, Medium, Low }` enum on `SpawnRequest`, matching AGENT-DIRECTORY's
vocabulary, mapped to `ModelRoute` at the provider.** Two definitions of one thing on opposite sides
of the profile. `CapabilityProfile.model_route: ModelRoute` is pinned at `CONTRACTS.md:952` and
`routing.rs:9` already declares the table *"the only place a model name appears"*. High/Medium/Low is
a **rendering** for the Session G window, not a second type. The field is also named `route`, not
`role`, because `ArgumentRole` already means Target-vs-Payload in the adjudicator this decision is
about.

**5. Hold the granted route on the `Run` beside `trust_floor`, as ADR-023's latch is held.**
ADR-032's own recorded reason, one field over: `CapabilityProfile::new` holds the quarantine
invariants and the child is constructed *from* the profile, so a route held beside it is a second
definition of what the child is — `quarantined_reader()`'s harness-fixed route could be bypassed
while every quarantine test stayed green.

**6. Derive the route at spawn from an LLM assessment of the task** (M3-DESIGN §9.1's arm A1(b)), so
the spawner never names it at all. **This loses on security, not on quality.** It makes the route a
function of an attacker-shapeable payload with no argument, no tool call and no permission check in
sight — a laundering path *around* the target check rather than through it. If A1 runs as an arm, the
route must be excluded from what the assessment may choose, or the arm is a security experiment
wearing a quality label.

**7. Wire the route on Ollama alone and document the other two as future work** — the reviewed
design's actual proposal. §4.1: instance #16 committed inside the answer to an instance-#16 question,
and strictly worse than the visibly-dead field it replaces, because the next grep for a reader
returns a hit.

**8. Give `LlamaCppDriver` a `Routing` and let it send the routed name** — the critique's own fix,
refused for the llama.cpp arm only. §4.3: `llama-server` does not route on that field, so the
assertion would be about a string sent over unrouted weights.

---

## 7 · The tests, each with the mutation that turns it red

**T1 — `the_model_in_the_request_body_follows_the_route_on_every_provider_that_can_route`**, new file
`crates/marlowe-provider/tests/model_route_reaches_the_request_body.rs`.
Over `Routing::new("orch-m","work-m","summ-m")` — three **distinct** names, with the reason stated in
the file — assert `driver.request_body(&view, &tools, CallLimits { max_output_tokens: 256, route:
ModelRoute::Worker })["model"] == "work-m"`, then `Orchestrator` → `"orch-m"`. **The negative control
lives in the same test:** `Routing::uniform("one")` returns `"one"` for both routes — which is what
production runs today — so a test written against `uniform` would be green whether or not the route
is read at all. Repeated against `OpenRouterDriver` in the same file. *Mutation:* restore
`model_for(ModelRoute::Orchestrator)` at `ollama.rs:300` — reads `left: "orch-m", right: "work-m"`.
*Second mutation:* leave `openrouter/driver.rs:210` as `self.model` — the OpenRouter arm fails
identically. **The llama.cpp arm is deliberately absent here; see T1b.**

**T1b — `a_routing_llama_server_cannot_honour_is_refused_at_build`**, same file.
`LlamaCppDriver::build(endpoint, Routing::new("a","b","c"), …)` returns
`Err(ResolveError::UnroutableRouting { .. })` naming all three; `Routing::uniform("a")` builds.
*Mutation:* delete the `routing.models().len() > 1` guard — the refusal case builds and the test
fails by name. **Its comment must say why there is no body assertion here**: `llama-server` serves
one weight set (`llamacpp.rs:952`), so a `body["model"]` assertion on this arm would be green over
unrouted weights.

**T2 — `a_child_is_routed_below_its_parent_and_the_bytes_say_so`**,
`crates/marlowe-loop/tests/spawn_and_budget.rs`.
Drive a real spawn from an `Orchestrator` root with a `ModelDriver` that **records `limits.route` on
every call** — the pattern `crates/marlowe-loop/tests/quarantine_batch.rs:197-201` already uses, where
the parameter is `l:` rather than `_l:`. Assert the recorded sequence is `[Orchestrator, Worker]` at
depth 1 and `[Orchestrator, Worker, Worker]` at depth 2. Assert the `RunSpawned` payload separately,
the way `spawned[0]["reads_untrusted"]` is already read at `spawn_and_budget.rs:189`, and **label
that assertion audit, not enforcement**. *Mutation:* make `for_child` return its argument — reads
`left: [Orchestrator, Orchestrator], right: [Orchestrator, Worker]`. *Second mutation:* revert
`engine.rs:794` to a fixed route — every recorded route becomes identical.

> **Why the journal assertion alone is not enough, and why the reviewed design's T2/T3 were instance
> #15.** Both asserted `RunSpawned["model_route"] == "worker"`. `engine.rs:2654` already hardcodes
> `ModelRoute::Worker`, so **today's build, a build with `for_child`, and a build where `from_args`
> reads a `role` key into a field nothing consults all print `"worker"`.** The recorded-route
> sequence is the property; the journal key is the audit trail.

**T3 — `a_model_that_names_a_model_role_produces_an_identical_spawn_request`**,
`crates/marlowe-provider/tests/spawn_from_a_model_reply.rs` — **not** `driver.rs`'s own `mod tests`,
because `driver.rs` is §13-guarded and this ADR's recommendation is that it stays untouched.
`SpawnRequest` derives `PartialEq` (`driver.rs:58`) and `from_args` is `pub`, so this is one
assertion:

```rust
let with    = SpawnRequest::from_args(&args(json!({"task":"t","exposed_tools":"",
                  "role":"high","level":"High","model":"marlowe-dawn:9b-super"})));
let without = SpawnRequest::from_args(&args(json!({"task":"t","exposed_tools":""})));
assert_eq!(with, without, "no spelling of a model role may reach `from_args`");
```

Three spellings, because a future session will pick one of them. This is the structural-withholding
assertion, sibling to ADR-057 §5's treatment of `share` and `reads_untrusted`. *Mutation:* have
`from_args` read any of `role` / `level` / `model` into any field — fails immediately, **with no
dependence on `Engine::spawn`, the journal, or a driver.**

**T4 — `run_declares_exactly_five_parameters_and_exactly_three_are_targets`**,
`crates/marlowe-tools/src/builtin.rs` `mod tests`, beside `the_child_capability_arguments_are_targets`
at `:897`. The full parameter-name set of `run`'s manifest equals the literal
`["task","output_contract","exposed_tools","budget_tokens","orphan_policy"]` and the Target subset
equals `["exposed_tools","budget_tokens","orphan_policy"]`, **both written out independently of the
manifest**. That is instance #19 discipline and a strict improvement on `builtin.rs:907-908`'s
`role_of("share") == None`, which asserts one absence and cannot see the set grow in any other
direction. The comment must name M3-DESIGN §1.1's `master` / `worker` **kind** parameter as the
expected next addition and state that adding it requires a `composes_spawn_targets` clause and a T5
row in the same commit. *Mutation:* add any parameter to `run`'s registration — fails naming it;
`builtin.rs:900-902` stay green through all of them.

**T5 — `every_target_run_declares_is_refused_under_a_latched_floor`**,
`crates/marlowe-provider/tests/spawn_from_a_model_reply.rs`, generalising
`a_latched_run_cannot_compose_a_childs_budget_or_lifetime` (`:667`). Two parts. **(a)** A table
`param -> a JSON value that is not the harness default` must have a row for **every**
`ArgumentRole::Target` parameter in `registry.manifest(&ToolId::new("run")).params()`, failing by
name if one is missing — **the table's completeness is checked against the manifest, not against
itself** — and the comment must say that simplifying this to iterate the table would silently remove
the only coupling between `composes_spawn_targets` (`engine.rs:3237`) and the manifest it mirrors.
**(b)** For each row the existing `spawn_count` helper (`:589`) reports `clean == 1` and
`tainted == 0` with the floor asserted at `UntrustedContent` — the pair discipline the file already
documents, because `RunSpawned == 0` is also what a build that cannot spawn at all looks like.
*Mutation:* declare a new Target on `run` without a `composes_spawn_targets` clause — (a) fails by
name. *Independently:* delete `|| req.grant_tokens.is_some()` — (b) fails for `budget_tokens` with
`left: 1, right: 0`. **T5 is the load-bearing test in this set**, because `adjudicate` is not on the
spawn path (§2.1) and `composes_spawn_targets` is a hand-written mirror with nothing else holding it
to the manifest.

**T6 — `the_quarantined_readers_call_carries_a_different_route_than_its_parents`**,
`crates/marlowe-loop/tests/quarantine_batch.rs`. Record `limits.route` on every `ModelDriver::call`
across one `condense_batch` from an `Orchestrator` parent: the parent's calls carry `Orchestrator`,
the quarantined reader's carries `Worker` (`CapabilityProfile::quarantined_reader()`,
`profile.rs:147`), and the recorded sequence contains both. The reader's route is the harness's
regardless of anything the parent asked for, which is what keeps layer 1's reader off the model a
compromised parent would prefer. *Mutation:* revert `engine.rs:794` to a fixed route — every recorded
route becomes identical.

**T7 — `the_receipt_names_the_model_role`**,
`crates/marlowe-provider/tests/spawn_from_a_model_reply.rs`, using the existing `receipt_for` helper
(`:249`). *Mutation:* drop `· model: {}` from the format string at `engine.rs:2728` — fails by name.

**T8 — `a_routed_model_whose_window_is_smaller_than_the_configured_one_is_refused_at_startup`**, in
`crates/marlowe-provider` — **and it ships with the negative control §5.3 requires.** A scripted
`/api/show` response reporting a window below `DEFAULT_CONTEXT_TOKENS` produces
`Availability::WindowTooSmall { model, reports, configured }`; a second arm reporting **262,144** —
the value all three current roles actually report — produces `Ready`. Without the second arm the test
is green on a build that never constructs the variant. *Mutation:* delete the comparison — the first
arm reads `Ready`.

**T9 — LIVE CHECK, not a unit test.** Per CLAUDE.md's pipe-tested-guard rule; record under
`runs/<session>/`. Configure a non-uniform routing (three distinct tags), run one `run` call in the
TUI under `--dev`, and read the **outbound-request dump** — the bytes the running process sent, not a
body built inside a test process. Expect **two distinct `"model"` values** across the parent's and
the child's bodies. Then `GET /api/ps` for residency, and the `--eval-adapter` provider line from
`CLAUDE.md` for the embedder. *Expected failure reading:* run it under `Routing::uniform` —
production's configuration today — and both bodies read the same `"model"`. **That is what the wiring
doing nothing looks like, which is why the live check must deliberately use three tags.**

---

## 8 · The adversarial pass, recorded

**Verdict: `sound-with-fixes`.** Nine defects were filed against the first design. What each changed:

| # | The defect | What it changed here |
|---|---|---|
| 1 | **FATAL** — one reader on one of three driver paths | §4. All three read it; llama.cpp gets a load-time refusal instead of a cosmetic reader (§4.3) |
| 2 | `ModelRoute::Summarizer` still unread, presented as closed | §5.2, recorded as an open family-#16 entry rather than claimed closed |
| 3 | T2/T3 asserted a journal value unchanged at HEAD — instance #15 | §7. T2 records the route sequence; T3 compares two `SpawnRequest`s |
| 4 | Window, clamp and disclosure do not follow the route | §5.3 and §5.4 — and the fix's own premise was measured and refuted |
| 5 | `CallLimits` cost wrong by ~4x | §3.2, 32 sites / 17 files, re-measured on HEAD |
| 6 | `for_child` makes the role a function of depth where AGENT-DIRECTORY needs kind | §3.1's doc comment says STOPGAP in those words; §11 item 3 |
| 7 | Five of five `Routing::uniform` citations wrong; `agent.rs:47` missed | §9 — every citation re-measured, and the checkout has moved again since |
| 8 | The `adjudicate` argument names a path that does not run | §2.1 |
| 9 | The receipt does not name the route | §3.3, one clause, T7 |

**What nearly shipped, stated plainly.** The first design's remedy for a
declared-control-nothing-reads defect would have created one: a field read on the Ollama path and
silently unread on llama.cpp and OpenRouter, with a grep for readers returning a hit. And its own
headline test asserted `body["model"]` only, so it would have been green with the window still
describing the orchestrator.

**What the critique itself got wrong, found here.** Its fix (a) — three drivers take a `Routing` and
each reads `limits.route` — is right for Ollama and OpenRouter and **manufactures instance #15 on the
llama.cpp path** (§4.3). Its `WindowTooSmall` fix cites *"32768 for all three roles from `/api/ps`"*;
32,768 is `DEFAULT_CONTEXT_TOKENS`, the number Marlowe **sends**, `/api/ps` reports the loaded window
derived from it, and `/api/show` reads **262,144** for all three (§5.3). Two proxies inside the fixes
for two proxies — and neither was found by re-reading, both by running a command.

---

## 9 · Citations re-measured, because HEAD moved twice

The critique corrected five wrong `daemon.rs` line numbers against `186b5d5` and identified the
cause: the first design had read `.claude/worktrees/agent-ac68c320701f55af4/…` rather than the
checkout — hazard forms 1 and 2 from CLAUDE.md's parallel-sessions table. **HEAD is now `03fb1d6`,
not `186b5d5`, and every line cited in this ADR was re-measured against it today.**

| Cited as | Verified on `03fb1d6` |
|---|---|
| `Routing::uniform` production sites | `daemon.rs:1263, 1338, 1503, 1889, 1976` **and `crates/marlowe/src/agent.rs:47`** — six, unchanged from the critique's reading. `ollama.rs:1134` is inside `#[cfg(test)]` and is not one |
| `CapabilityProfile::model_route()` | `profile.rs:280` (the first design said `:223`, a worktree copy) |
| ADR-008's amendment | `DECISIONS.md:1038` (the first design said `:1030`) |
| The `[spawned]` receipt | `engine.rs:2728` (the design said `:2726`) |
| `composes_spawn_targets` | `engine.rs:3237` — unchanged |
| *"never reaches `self.adjudicator`"* | `engine.rs:2582` — unchanged |
| `ModelProviderChoice` | `daemon.rs:63` (the critique said `:67, :81`, which are variant lines) |
| `CallLimits {` construction sites | **32 across 17 files**, up from the critique's 31/17 |
| AGENT-DIRECTORY's VRAM sentence | **already corrected at HEAD.** The design's closing section asks for *"the VRAM sentence, corrected before G builds on it"*; `03fb1d6` — *"The headroom was arithmetic, and the desktop was holding five gigabytes"* — added the amendment at `AGENT-DIRECTORY.md:71-95`, including `size_vram` summing to 10,849,836,070 B and the final **14,993 MiB used / 1,053 MiB free**. Nothing is owed here |
| ROADMAP's *"CONTRACTS §5 pins it"* about `SpawnRequest` | **false.** `grep -n SpawnRequest docs/design/CONTRACTS.md` returns one hit, `:941`, pinning the method signature. The shape is unpinned |

---

## 10 · What this decision does NOT close

* **It does not make the product route anything.** Every production `Routing` is `uniform`, so
  `model_for` returns one string for all three roles and threading the route changes **not one byte
  on the wire today**. That is safe, and it means a green suite proves nothing about the running
  product. T9 is the only instrument that can — the `persona/v1.md`-loaded-versus-in-the-body lesson,
  one subsystem over.
* **It does not close instance #16 for `ModelRoute::Summarizer` or `Routing.summarizer`** (§5.2). A
  third of the table stays dead and `routing.rs:117` stays green over it.
* **It does not make the window, the `max_tokens` clamp or `model_disclosure` follow the route**
  (§5.4). The load-time refusal bounds the worst case; per-route windows are a `daemon.rs` change and
  Session G's.
* **It does not give a child's route a relationship to the child's KIND.** `for_child` is a function
  of depth over a five-level design (M3-DESIGN §1). Three of the four configured roles stay
  unreachable and AGENT-DIRECTORY §2a's **per-role admission queue has exactly one role** — which
  §2a says is *"Session C's problem, not Session G's"*. **Session C ships a placeholder where §2a
  expects a table. That is recorded, not resolved.**
* **It does not name the fourth role**, and it does not merge the two candidate gaps (§11 item 2).
* **It does not bound downgrade, and that is deliberate.** `may_grant` (Session G) bounds upgrades
  only; forcing a subtree onto the smallest model is always a narrowing. Layer 1's containment does
  not depend on the reader's competence — `ExposedSet::empty()` and `EgressPolicy::DenyAll` hold
  whatever model runs — so a dumber quarantined reader produces a worse summary, not an escalation.
  A **fidelity** risk of the class ADR-041 already concedes and §9.1's A3/A8 already measure. Someone
  will later read *"downgrade is attacker-useful"* and add a floor; the floor would buy nothing and
  would make a legitimate cheap delegation impossible.
* **It does not resolve `Routing`'s local-tag guard on the OpenRouter path** (§4.2). `is_cloud_tag`
  becomes inert there; the gate is ADR-046's opt-in, and generalising the type is a separate
  decision.
* **It adds a fifth place to STATE.md's open question 0, and it is a fifth, not one of the four.**
  CLAUDE.md's saturation lesson says a floor discriminates only over a mixed population.
  `blocks_composed_targets` is a **gate** (`origin <= UntrustedContent`), not a comparator, so over a
  uniformly tainted population it fires **always**, not never — on the spawn path the floor works
  precisely where a research worker is uniformly tainted. What saturation reaches is the
  **fallback**: when the gate fires the value falls to a default, and *"who asserted the default"*
  must not answer *"a model"*. `ModelRoute::for_child(parent)` is that answer — a total function of
  the parent's own declared route, terminating at `CapabilityProfile::interactive()`'s `Orchestrator`
  (`profile.rs:222`), which the user's configuration set. The genuinely saturated version is
  M3-DESIGN §9.1's arm **A1(b), LLM assessment at spawn**: every candidate task string in a research
  worker is `UntrustedContent`, and the assessment has no argument and no permission check in sight.
  The existing four (ranking inputs, cache keys, derivation lineage, merge decisions) are all inside
  memory; **this one is inside the control plane.**

---

## 11 · What is the human's

1. **Approving the §13 edit to `crates/marlowe-loop/src/profile.rs`** for `ModelRoute::for_child`.
   Nothing else in that file changes.
2. **The name of the fourth role — and, before naming it, whether it is already named.** ADR-008's
   amendment (`DECISIONS.md:1038`) says *"`ModelRoute` gains a compression role"* and calls it the
   enforcement point for brief §10's condensed structured returns — i.e. the quarantined reader.
   `ModelRoute` still has three variants and `quarantined_reader()` is routed `Worker`.
   `AGENT-DIRECTORY.md:53` shows a fourth role, unnamed, with three named. **These may be the same
   gap or two.** Not merged here, because a role invented by an implementer becomes a default nobody
   chose.
3. **The kind → route table.** Which route a `master`, a `worker`, an extractor and the unnamed
   fourth get. M3-DESIGN §1's five levels and §1.3's per-type worker profiles need the route to vary
   by **kind**; `for_child` varies it by **depth**, and it blocks AGENT-DIRECTORY §2a's per-role
   admission queue, which §2a assigns to Session C.
4. **Whether a route a USER names in the Session G window is `UserAsserted` and therefore always
   granted** — including upgrading a whole worker subtree to the orchestrator model. **Same shape as
   two other open questions:** `SECURITY-AUDIT.md` §8's *"the latch belongs on the session, not the
   Run"*, and ADR-032 §3.1's grant scope. Three questions, one shape, all the human's.
5. **Whether Marlowe's own route is user-selectable at all.** `04-addendum-persona.md` is binding and
   §C4's anti-sycophancy probe set is a standing regression test that a model swap is **blocking**
   on. `for_child` never changes the root's route, so Session C does not touch this; the Session G
   window's "secretary model" control does.
6. **Whether `SpawnRequest` is pinned in `CONTRACTS.md` §5 now or in Session G with `route`
   included.** Recommendation: **G**, once, rather than pinning a shape that is about to grow a
   field. ROADMAP's C row says §5 already pins it; §9 shows it does not.
7. **Whether `LlamaCppDriver` refusing a non-uniform routing (§4.3) is the right trade**, or whether
   the llama.cpp path should be excluded from routing entirely. The refusal is the conservative
   reading of `llamacpp.rs:952`; the alternative introduces a second concept — *providers that route*
   versus *providers that do not* — in a place that currently has one.

### 11.1 · Pre-pinned for Session G, so the wrong-order change cannot be made quietly

```rust
// crates/marlowe-loop/src/driver.rs   ** §13-GUARDED — SESSION G, THE HUMAN'S **
pub struct SpawnRequest {
    // ... the existing EIGHT fields (task, contract, orphan, share, grant_tokens,
    //     tools, tools_declared, reads_untrusted), unchanged ...
    /// `None` means the harness decides: `ModelRoute::for_child(parent)`.
    /// `Some(_)` is a **COMPOSED TARGET** under ADR-023.
    /// NO `#[derive(Deserialize)]` may land on this struct with it — instance #12.
    pub route: Option<ModelRoute>,
}

// crates/marlowe-loop/src/engine.rs:3237 — the target check for the role
fn composes_spawn_targets(req: &SpawnRequest) -> bool {
    !req.tools.is_empty()
        || req.grant_tokens.is_some()
        || !matches!(req.orphan, OrphanPolicy::Terminate)
        || req.route.is_some()
}

// crates/marlowe-loop/src/profile.rs — the upgrade ceiling, independent of the latch
impl ModelRoute {
    /// Explicit, NOT `derive(Ord)`: declaration order makes the strongest variant the smallest,
    /// so `<=` would read backwards at every call site.
    pub fn strength(self) -> u8 {
        match self { Self::Orchestrator => 2, Self::Worker => 1, Self::Summarizer => 0 }
    }
    /// A narrowing, never a widening — the rule `Engine::spawn` already applies to the tool set.
    /// Withheld structurally; there is no counter and no zero (instance #17).
    pub fn may_grant(self, requested: ModelRoute) -> bool {
        requested.strength() <= self.strength()
    }
}
```

**These four land in one commit or none.** `SpawnRequest.route` without the
`composes_spawn_targets` clause is the exact wrong-order change T3 and T5 exist to block.

---

## 12 · Verification

Symbol names rather than line numbers wherever a line number would be a claim about a path with
nothing checking it (family #14). **Everything marked *measured* was run today, 2026-08-30, on
`03fb1d6`. Everything marked *read* was established by opening the file.**

| Claim | How established |
|---|---|
| `CapabilityProfile::model_route()` has zero callers | **measured**: `grep -rn "\.model_route()" --include=*.rs crates/` — empty |
| `request_body` hardcodes the orchestrator route | **read**: `ollama.rs:300` |
| The child's route is a constant | **read**: `engine.rs:2654` |
| Six production `Routing::uniform` sites | **measured**: `grep -rn "Routing::uniform" crates/*/src/`, minus `ollama.rs:1134` (inside `#[cfg(test)]`) |
| 32 `CallLimits` construction sites across 17 files | **measured**: `grep -rn "CallLimits {" --include=*.rs crates/ \| grep -v "pub struct CallLimits"` |
| Three driver implementations, all selectable | **read**: `daemon.rs:63-85`, and the construction sites `daemon.rs:2115`, `:2282`, `:2367` |
| `LlamaCppDriver` sends `self.model`; OpenRouter the same | **read**: `llamacpp.rs:1069`, `openrouter/driver.rs:210` |
| **`llama-server` does not route on `"model"`** | **read**, two independent doc comments: `llamacpp.rs:952-954` and `daemon.rs:73-74` |
| All three drivers share one `ModelStep::Spawn` construction | **measured**: one hit for `ModelStep::Spawn(` in `crates/*/src/` (`ollama.rs:1045`), reached from `llamacpp.rs:1449` and `openrouter/driver.rs:677` |
| `adjudicate` is not on the spawn path | **read**: `engine.rs:2582`; `adjudicate.rs:304`'s loop is reached only from `tool_batch` |
| `orphan_policy` is a declared Target | **read**: `builtin.rs:691-692`; enforced at `engine.rs:3237` |
| `run` declares exactly five parameters, three Target | **read**: `builtin.rs:647-693` — `task` and `output_contract` are `Payload` |
| `ModelRoute::Summarizer` has no producing constructor | **read**: `profile.rs:147`, `:165`, `:222`, `:265` |
| Compaction runs through a different port | **read**: `driver.rs:330-331`, `daemon.rs:633-635` |
| `SpawnRequest` has no `Deserialize` | **read**: `driver.rs:58` — `#[derive(Debug, Clone, PartialEq, Eq)]`. Instance #12 stays closed, and **no `#[derive(Deserialize)]` may land with `route` in Session G** |
| `child_profile` is moved before the journal record | **read**: `engine.rs:2669` then `:2673`; `ModelRoute` is `Copy` at `profile.rs:41` |
| **All three roles report a 262,144-token window** | **measured**: `GET /api/show` for `marlowe-dawn:9b-super`, `marlowe-mini:4b-super`, `marlowe-mini:2b` → `qwen35.context_length: 262144` |
| **`/api/ps` cannot answer at load** | **measured**: `{"models":[]}` with nothing resident |
| 32,768 is the configured window, not a reported one | **read**: `ollama.rs:180`, sent as `num_ctx` at `ollama.rs:545` |
| `MODEL_CONTEXT_CEILING`'s *"Recorded, not used"* is false | **measured**: `grep -rn MODEL_CONTEXT_CEILING` → `main.rs:341`, `agent.rs:133`, `context_window.rs:75` |
| `SpawnRequest`'s shape is unpinned | **measured**: `grep -n SpawnRequest docs/design/CONTRACTS.md` → one hit, `:941` |
| `model_route` is absent from the family-#16 roll | **read**: `SECURITY-AUDIT.md:135-138`, eight entries, one struck |
| The VRAM correction has already landed | **read**: `AGENT-DIRECTORY.md:71-95`, added by `03fb1d6` |

**No `cargo` command was run for this ADR** — another session holds the build — so **nothing in this
document is a claim that the specified code compiles or that any test passes.** The `child_profile`
move in §3.3 is exactly the class of thing a compile would have caught and a careful reading nearly
did not; treat the rest of the Rust here on the same terms.
