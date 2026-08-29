# Marlowe

An agent harness: the runtime around a language model that gives it memory, tools, durable
execution, and earned autonomy. Terminal-native. Not a chat wrapper, not a framework.

**Core abstraction:** Everything Marlowe knows, is doing, or has done is a materialized view
over one append-only, provenance-signed event log — and the agent loop is a transaction that
reads a view, acts, and appends.

## Three things that are already decided

**1. Memory is the spine, not a subsystem.** Context engineering, skills, trust classes,
subagent returns, and self-improvement are all consequences of the memory design. If memory
is a module the rest of the system calls, the design is wrong. When a choice trades memory
quality against anything else, memory wins.

**2. Memory is invisible in the interface.** The user experiences it through the agent knowing
things, not through panels, scores, or citations. Retrieval instrumentation exists only under
`--dev`. See `03-addendum-terminal.md` §B1 — this is binding, and an earlier draft got it wrong.

**3. Marlowe has a persona, and it is not configurable.** Anything producing user-visible prose
carries it — including subagent summaries and noticing text. It lives in the stable tier, is
versioned as an artifact, and is provider-independent. See `04-addendum-persona.md`. The
requirement most likely to erode silently is §C4 (anti-sycophancy); its probe set is a standing
regression test, and a model swap that moves the score is blocking.

## The five layers — the security model, and it is not negotiable knowledge

Untrusted content and memory poisoning are defended by **five named layers**. Know them by number.

1. **Quarantine.** The component that reads untrusted content has `reads_untrusted: true` and an
   **empty tool set** — `reads_untrusted && !exposed_tools.is_empty()` is a **load-time error**, so a
   reader that can act cannot be constructed. It returns structured analysis to something that never
   sees the raw text. Brief §8.2, CONTRACTS §5, M2 Session A.
   **SHIPPED AND ROUTED as of M2 Session E (ADR-039), and both halves are now real.** The load-time
   error was built in Session A; the *routing* was missing until E, so between C2f and E `web` handed
   raw page text into the run holding `bash` — §8.2's second sentence violated in the product.
   `Engine::condense_batch` now sends every untrusted tool result through a quarantined child and
   hands the parent a validated summary. **Keyed on the trust class, not the tool name**: the trigger
   is `blocks_composed_targets`, the same function the adjudicator enforces on, so a new tool
   returning untrusted content is covered without anyone remembering to add it.

   **The unit is the GROUP, not the call, as of ADR-041.** N fetched pages cost **one** child, one
   model call and one subagent slot — it was one of each *per page*, which made a thirty-page
   research pass impossible (it paused at the 8-subagent cap, and the eighth reader held ~0.3% of
   the budget because `BudgetShare::Small` slices *remaining*). Containment is unchanged: same empty
   tool set, same `DenyAll` egress, same validated contract, same fail-closed paths. What was
   per-page was only the cost. The trade is that one context holds several attacker-controlled
   documents, so A can influence how B is described — a **fidelity** risk, not an escalation one,
   bounded by `MAX_SOURCES_PER_READER = 6`.
   **Consequence to know before touching layer 3: no tool result can taint a parent any more.** The
   only remaining source of `UntrustedContent` in a run's own window is **injected memory**. A test
   that establishes taint via a tool result now establishes nothing — four had to move, and one went
   green and vacuous on the way.

   **AND THE SENTENCE THAT USED TO END THAT PARAGRAPH — *"layer 3 is still reachable and
   non-vacuous"* — IS FALSE OF THE DAEMON. Corrected 2026-08-12, and it is the most important thing
   on this page.** The chain is four links and each was checked by grep, not by argument:
   injected memory is untrusted only if some belief is `UntrustedContent`; a belief is
   `UntrustedContent` only from `ingest` (`trust_for_channel` maps Web/Email/Messaging/Mcp/File) or
   from `remember_claim` with an already-bottomed floor, which is circular; and **`ingest` had
   exactly one caller in the workspace, the `--eval-adapter`.**

   **AMENDED 2026-08-29 (ADR-062), AND THE CONCLUSION IS UNCHANGED.** `ingest` now has **two**
   non-test callers — `crates/marlowe/src/adapter.rs` (the eval adapter) and
   `crates/marlowe-daemon/src/memory.rs` (`DaemonMemory::ingest_external`). `Channel::` now appears
   in `marlowe-daemon` too, inside `ingest_external` and nowhere else. **`ingest_external` has no
   caller of its own**, so every sentence below still holds.

   **THE PRESCRIBED CHECK BELOW WAS RETIRED BY THAT SAME BRANCH, AND SAYING SO IS THE POINT.**
   `grep -rn "\bingest("` now returns a daemon hit and reads as though the daemon ingests. It does
   not. The command that still discriminates:

   ```
   grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"
   ```

   **Zero non-definition hits means the latch is still unreachable.** A check that goes green while
   the product is unchanged is worse than no check, which is why the old one is named as retired
   rather than quietly replaced.

   So **in the shipped interactive product the latch cannot fire in a parent run at all.** It is not
   broken; it is *unreachable*, because ADR-041 removed the only reachable trigger and the
   replacement trigger has no production ingest path behind it. Every test that establishes taint by
   hand-pushing an `InjectedMemory` block is measuring a state the product cannot enter — the
   green-and-vacuous family applied to the layer's **only** remaining entry point.

   This does not make ADR-041 wrong and does not mean the guard should be removed. It means the
   number of live defences is smaller than this document has been claiming, and that the moment
   `ingest` is wired into the product — a `web`-derived belief, an inbound-mail channel, MCP output
   — layer 3 goes live *together with* two known defects in the same path (the compaction stamp and
   the trim marker, below).

   **The order used to read "fix the two first, then wire ingest". Its first half is DONE
   (`6a1f4f5`); its second half is now established as WRONG, so the rule is superseded rather than
   satisfied.** ADR-062: M3-DESIGN §2.1 forbids tainting the one permanent run and §7 gives workers
   no `MemoryWrite` (`memory: None` is hardcoded at both child `Ports` sites), so the two rows are
   disjoint and **no run in the current architecture may correctly hold an untrusted belief.** The
   rule is now: **fix the two — done — then STOP.** Wiring waits on scoped memory (ROADMAP M3
   Session D) and on ADR-062 §4's origin decision, which is a pinned-contract question and the
   human's.

   A live probe, not a unit test, is what closes it — ingest one `Channel::Web` belief into a real
   profile, retrieve it, and assert on a refused composed target **across two turns**. (Never on
   `TrustFloorLatched`: instance #15 below is that event, and it fires on every run that has ever
   run. Ask `marlowe_permission::blocks_composed_targets`.) **That probe still cannot be written,
   and that IS the finding, now recorded:**
   `crates/marlowe-daemon/tests/layer3_refuses_a_composed_target_from_an_ingested_belief.rs` goes as
   far as it honestly can — a real `ingest`, a real store, a real maturation window, a real
   adjudication, refused — and its header names the three blockers: `Daemon::turn` builds its model
   driver internally with no seam, `retrieve` abstains on `NoReranker` with no cross-encoder loaded,
   and a turn boundary rebuilds `Run::root`. It substitutes `daemon.rs`'s injected-memory push with
   its own, **and that production line has zero coverage** — laundered to `UserAsserted` or deleted
   outright, the whole daemon crate stays green (`runs/m3-mutation/finding1*.txt`). Cover it before
   `ingest` gets a caller.
2. **Trust class propagation.** Every belief carries its origin, and trust propagates **worst-case
   over full lineage**. Four LLM rewrites later, a web page is still `UntrustedContent`. This is what
   stops laundering. Brief §5.6 and §8; `trust.rs`; M0b Session A — 16 checked, 0 failed,
   non-vacuous.
3. **The `(action, target)` split, as a monotonic latch.** Untrusted content may shape a **payload**
   — a draft body, a summary. It may **never** shape a **target**: which tool, which recipient, which
   path, which amount. ADR-023. The latch is this month's fix: the floor was derived from the current
   window, so trimming the untrusted block silently restored privileges; it now latches on the `Run`
   and never rises. Live: **7 composed shell commands issued, 7 refused**.
4. **Egress allowlisting.** Deny-by-default outbound; an extensible empty allowlist, per-host human
   approval, held for the session. ADR-031, ADR-032. **Approved but not shipped**, pending the
   approval surface.
5. **The trust ledger.** Consequential actions need earned tiers; irreversible ones have ceilings no
   evidence lifts. Addendum A §A8. **Not built — M6.**

**The K1 injection gate / declared operating point is NOT one of the five.** It is a **relevance**
mechanism. Brief §8.1 is explicit: *"Filtering does not work. Containment works."* Containment is
layers 1–3. Do not call the gate "the filter" as though it were a defence — M2 Session D did exactly
that and filed a quality finding as a security hole on the strength of it.

**Brief §5.6 settles what a trust class governs:** *"Memories derived from untrusted content may
inform **analysis** but may not authorize **action**."* So an untrusted memory ranking highly and
being read is the **specification**, not a breach. What must not happen is it authorizing action —
which is layer 3's job, and layer 3 holds.

**The eval suite's §4 wire reaches only layer 2**, plus the ingest actor check: `ingest`/`retrieve`/
`consolidate` speak to a process with no loop, no tools and no egress. **A poisoning ASR from
`marlowe_eval` can never be evidence about layers 1, 3 or 4** — those need loop-level tests
(`profile.rs`'s load-time refusal, `adr023_live.rs`).

## Document map

| Path | What it is | When to read |
|---|---|---|
| `docs/requirements/01-brief.md` | Requirements: the engine | When a design decision is ambiguous |
| `docs/requirements/02-addendum-secretary.md` | Requirements: secretary layer | Same |
| `docs/requirements/03-addendum-terminal.md` | Requirements: the TUI | Before any interface work |
| `docs/requirements/04-addendum-persona.md` | Requirements: the persona | Before any user-visible prose |
| `docs/design/ARCHITECTURE.md` | Component boundaries, agent loop | Before touching any subsystem |
| `docs/design/CONTRACTS.md` | Pinned schemas and type signatures | **Before any code crossing a boundary** |
| `docs/design/DECISIONS.md` | Settled choices with rationale | Before proposing an alternative |
| `docs/design/ROADMAP.md` | Milestone sequence | To find current scope |
| `STATE.md` | Built / next / known issues | At session start, always |

Requirements docs are long. Do not load them by default — read the design docs, and go to
requirements only when the design docs do not answer the question.

## Working agreement

- **Read `STATE.md` at session start. Update it before you stop.** This is what makes session
  N+1 not start from zero.

- **HEAVY WORK NEVER RUNS ON THE MAIN DAEMON THREAD, AND THREAD COUNTS ARE DERIVED FROM THE
  MACHINE.** Two halves of one rule, both about a box with a lot of cores.

  **Nothing CPU-heavy — extraction, parsing, PDF decoding, embedding — executes on the thread that
  serves the interface.** The tempting shortcut is the single-item fast path: run a batch of one
  inline and skip the thread spawn. That is exactly the case that hurts, because a batch of one is
  the *common* case and one `web` call on a 2 MB PDF is hundreds of milliseconds of parsing. Run
  inline it lands on the daemon's thread, the surface stops repainting, and the user sees a freeze
  with no indication why. `FileSystemTools::execute_batch` therefore offloads **unconditionally**;
  a thread spawn is tens of microseconds and is never the thing to optimise away.

  **No hardcoded thread counts, pool sizes or fan-out widths.** `marlowe_net::io_concurrency()` is
  the single definition and everything routes through it — `marlowe-exec`'s `batch_concurrency()`
  and `corpus::default_concurrency()` both delegate rather than keeping a second constant that
  would drift. It is **4 x cores, floor 8**, and the multiple is the point: a fetch is blocked on a
  socket with the CPU idle, so sizing an I/O pool to the core count leaves most of the machine
  parked. CPU-bound work is the opposite and needs no arithmetic — `extract_many` runs on `rayon`'s
  global pool, which is already the core count. Pass `0` as a concurrency argument to mean *decide
  for me*; workers are then capped at the amount of work, so a two-document corpus does not spawn
  sixty-four threads.
- **Contracts in `CONTRACTS.md` are pinned.** If one is wrong, stop and raise it. Never silently
  change a schema — other work depends on it.
- **One milestone at a time.** Scope is whatever `ROADMAP.md` marks current. If a task pulls you
  outside it, note it in `STATE.md` and stop.
- **Decisions in `DECISIONS.md` are settled.** Argue explicitly to revisit one; do not quietly
  design around it.
- **Every numeric target becomes an executable test.** A target that is not a command printing a
  number does not exist.
- **Do not author the memory eval.** `eval/` is the scoreboard. It is not modified to accommodate
  an implementation. If a test fails, the implementation is wrong until proven otherwise.
- **Assert the property you care about, not a proxy that moves with it.** A measurement can answer a
  question *adjacent* to the one being asked, and the adjacent answer looks authoritative.
  `tier=truecolor` printed beside a white screen. `scroll` incrementing while the view sat still. A
  green hover test over an event that never arrived. A run recorded as passing on Windows Terminal
  when only a headless buffer had been diffed. **Fourteen instances across M0b, M1, M0c and M2** —
  in code, in defaults, in verification methods, in measurement targets, and once in a guard. Before
  believing a number, ask what it would read if the thing you actually care about were broken; if
  the answer is "the same", it is a proxy and it is not evidence.

  The ledger, for the last four, because the count is only useful if it is auditable:
  **12** — `Deserialize` routing around a validating constructor (M2 A; the first caught by design).
  **13** — R@1 counting a superseded fact as a hit, so every R@1 in the project was inflated
  (M0c; `docs/design/HARM-WEIGHTED-PRECISION.md`). **14** — a guarded path that moved, below.
  **15** — the trust-floor banner, which is the widest gap yet between what fired and what was
  claimed (M2 C2f).

- **A PRESCRIBED DIAGNOSTIC CAN BE RETIRED BY THE VERY CHANGE THAT MAKES IT MATTER, AND IT
  RETIRES BY GOING GREEN.** The **eighteenth** instance, found closing M3 Session B2, and it is the
  first one committed against *this file*.

  The layer-3 paragraph above named one command as *"the check that would have caught this
  earlier"*: `grep -rn "\bingest("` for callers. `673bcd2` added `DaemonMemory::ingest_external`,
  which calls `ingest` and **has no caller of its own**. The command now returns a daemon hit. A
  reader running the prescribed check concludes the daemon ingests; the product's reachability is
  **completely unchanged**.

  Nothing was broken and nothing was hidden. The port is deliberate, the commit message says so, and
  the check answers a question — *"does anything call `ingest`"* — that used to be the same question
  as *"can the daemon become tainted"* and silently stopped being it. The discriminating command is
  one level down (`ingest_external(` in `crates/*/src/`, minus the definition), and it had to be
  written down because the old one now reads as a positive result.

  **Ask of any command a document prescribes: what makes this the same question as the one being
  asked, and what change would separate them?** The answer is usually a call graph, and a call graph
  is exactly what a session is about to alter. This is the pipe-tested-guard family aimed at
  documentation instead of code: a check that answers an adjacent question reads identically to one
  that answers the real one — and unlike a stale guarded path, which goes silent, a retired grep
  goes **loud and affirmative**, which is worse.

- **A ZERO BUDGET DIMENSION MEANS "ALREADY EXHAUSTED", NOT "MAY NOT USE".** The **seventeenth**
  instance, found building ADR-041, and it is the cheapest possible mistake to make.

  The quarantined reader holds no tools, so expressing that as `tool_calls: 0, subagents: 0` reads
  like documentation. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fired on the
  reader's **first iteration**: it paused before its first model call, returned nothing, and every
  fetched page came back to the parent as *"the content could not be condensed"*. **A quarantine
  that had silently stopped reading anything at all**, with the containment still perfect and the
  product useless.

  Nothing was broken in the budget code; the number meant the opposite of what it looked like.
  Capabilities are withheld **structurally** — `ExposedSet::empty()` means there is no tool to call,
  `depth: 0` means `slice_for` refuses a spawn — and the counters are `1` purely so the check does
  not fire on entry. **Ask of any limit written as zero: does this code read zero as a floor or as a
  ceiling?**

- **A DECLARED CONTROL THAT NOTHING READS, with a green test asserting the declaration.** The
  **sixteenth** instance, found in M2 Session E while establishing layer 1's blast radius.

  `web`'s registration carries `inline_threshold_bytes: 0` and the comment *"Never inlined. §8.2: raw
  untrusted bytes do not reach attention."* **No code reads that field.** `marlowe-exec`'s `body_for`
  decides inline-vs-reference against a global `MAX_INLINE_BYTES = 8_192`, so every fetched page under
  8 KB went into the model's context verbatim — measured in a live `--dev` dump, injected comment and
  all.

  The test is the part to remember. `web_is_inert_and_never_inlines` asserts
  `web.summary.inline_threshold_bytes == 0` — **the value of the field, not the fate of a byte.** It
  is green on a build where the control does nothing, and it would be green if the executor were
  deleted. Same family as `persona/v1.md` *loaded* versus the persona text being *in the request
  body*: a property asserted where it is declared rather than where it is enforced.

  **Ask of any control: is there a line of code that reads it?** A grep for readers of the field
  returned the definition, the constructor, and that test. That grep is thirty seconds and it is the
  whole check.

- **The banner said "read untrusted content" and the trigger was the string `"Marlowe."`.** The
  fifteenth instance, and the one to quote when explaining the family, because the distance between
  the event and the claim is the largest this project has produced.

  The loop emitted `Degraded{TrustFloorLatched}` whenever the run's floor **moved**; the surface
  renders that as *"read untrusted · composed targets blocked"*. A run starts at `UserAsserted`, and
  the assembler constructs the stable tier on every assemble with the `Identity` block —
  `"Marlowe."` — at `AgentObserved`. **So it fired on the first assemble of every run that has ever
  run**, before the model spoke and before any tool existed in the turn; the first assistant turn
  (`AgentInferred`) fired it again. The negative control reads `left: 2, right: 0`: **two banners on
  a run with no tools at all**, both clauses false.

  Nothing was broken. The trust class at ingest was right, the floor arithmetic was right, and
  `adjudicate` blocks at `<= UntrustedContent` exactly as specified. **The event fired on *floor
  moved*, the text asserted *floor reached untrusted*, and the banner read identically whether or
  not the guard worked** — so it was never evidence about the guard, and a latch that fires on
  everything means nothing at the moment it starts to matter. Closed by making
  `marlowe_permission::blocks_composed_targets` the single definition, called by the adjudicator at
  its enforcement site *and* by the loop to decide whether to speak.

- **A UNIFORMLY-TAINTED POPULATION IS WHERE A TRUST FLOOR RUNS OUT, and this constrains every
  future use of the taint mechanism.** Found designing ADR-036 §5, and it is the most general thing
  this project has produced.

  The taint machinery is a **floor**: `min` over a lineage, `min` over a window, latched monotonic
  per run. A floor discriminates only while the population it covers is *mixed*. In a research
  worker every source is `UntrustedContent` — arXiv and Crossref included, because §2.8 binds trust
  to origin — so **the floor is already at the bottom, every value is equally tainted, and the
  mechanism has no remaining power to tell one from another.** It is not broken and it has not
  failed; it is saturated, and a saturated floor is silent in exactly the way a green probe beside a
  hung product is silent.

  **The question that survives saturation is not "how trusted is this value" but "who asserted
  it".** ADR-036 §5 is one instance: an identifier from a channel authoritative for that namespace
  is an identity, and the same identifier printed on a fetched page is a *claim*. Both are
  `UntrustedContent`. The floor cannot separate them; provenance can.

  Generalised, for the next domain: **wherever a value chosen by untrusted content determines an
  outcome, ask who asserted it — even when there is no tool, no argument and no permission check in
  sight.** And ask it *especially* where everything is tainted, because that is precisely where the
  existing guard reads "blocked" for every value and therefore says nothing about any of them.
  Four unexamined places are listed as open question 0 in `STATE.md`.

  **This is why ADR-023 is a floor AND ADR-036 needs an authority rule** — two mechanisms, because
  they answer different questions, and the second only becomes visible once the first saturates.

- **A TEMPLATE IS NOT WHAT THE MODEL RECEIVED, and the control took one command.** M2 C2f, while
  chasing a persona that appeared not to apply. Ollama's `/api/show` reports this model's template
  as `{{ .Prompt }}` — thirteen characters, rendering neither `.System` nor `.Messages` — and the
  obvious reading is that the system prompt is discarded. It is not: Ollama uses a built-in
  renderer for the architecture and ignores that field.

  The conclusion was announced before it was tested, and it was wrong. What caught it was a
  **BANANA control** — a system message saying *reply with exactly the word BANANA* — which came
  back `BANANA`. One command, and it was only run because the conclusion was too convenient.

  Same family as `get_providers()` reporting *registered* rather than *where nodes ran*: a
  description of a mechanism is not a measurement of its output. **Ask what the model actually
  received, not what the configuration says it should have.**

- **A trim-dependent assertion needs a control that fails when no trim occurred.** Second subsystem
  after the three-attempt `Notice` control, and the same question in a new place: *would this still
  fail if the thing it names never happened?*

  `adr023_live.rs` asserts the trust floor holds **after the untrusted block is trimmed out of the
  view**. Its first run passed — at a 4 KB window where both pages fitted, **nothing was trimmed,
  and the property the test is named for never occurred**. The window size, not the code, decided
  whether the test tested anything, and it reported success either way.

  Two further attempts failed for real reasons worth keeping: `clear_tool_results` **preserves the
  trust class**, so masking alone can never raise the view's floor; and a fetch-succeeded guard
  reading the *view* is in direct opposition to the property, passing only when the eviction did
  **not** happen. The guard now reads the emitted §B6 line, which survives both masking and
  trimming. **Any assertion whose subject is "X was removed" carries an assertion that X was
  removed.**
- **A measurement is scoped to the system it was taken on. Carrying it forward requires
  re-measuring, not citing.** The sibling of the rule above, and the harder one to catch: the number
  is *correct*, the reasoning about it is sound, and it is simply **about a different system**. There
  is nothing wrong to find by re-reading it — which is why it survives review and gets quoted for
  sessions.

  **Four instances, and the fourth is what named the family:**

  **1.** Session G measured int8 batch invariance and the reading did not transfer to f32 — the
  origin of the standing rule that *determinism, batch and padding invariance are re-measured PER
  GRAPH and never inherited*. **2.** ADR-015's shape-binding is a property of **int8** graphs;
  reading it as a property of the architecture put ADR-014's neighbourhood wrong until it was
  corrected. **3.** ADR-017's closure was measured on **fit** and withdrawn on held-out. **4.**
  ADR-003's spike measured **94.9 ms → 16.2 ms** for a physical storage index under concurrent
  durable writes; the retrieval path iterates an in-memory `BTreeMap`, where the same stage measures
  **3.83 ms at 113k entries — 1.78% of P95**, a factor of ~25 apart (M0c Session L; ADR-003
  AMENDMENT 2026-08-08).

  **The tell is that the number arrives with a citation instead of a command.** Before reusing a
  measurement across a boundary — a different graph, a different split, a different code path, a
  different thread count, a different machine — ask *what system was this taken on, and is that the
  system I am about to act on?* If the answer needs an argument, it needs a measurement.

  **Session L is also the counter-example that keeps this honest.** Session K's *"batching buys
  nothing here"* was **correct**, and it was retired anyway on a profile showing the rerank
  dominates — which establishes that the rerank is worth attacking, not that batching is how. The
  measured answer was a **12% regression at one thread**, and multi-threading was **+158.9 ms**. So
  the rule cuts both ways: an old number can be wrongly *carried*, and it can be wrongly *discarded*.
- **Watch for defaults that make a mismatch unobservable.** A fallback value, a permissive
  default, a re-resolved path — each lets two sides silently disagree while the test goes green
  because the failing path stopped existing. This pattern has produced four bugs in this project
  already. Prefer a load-time error to a sensible default.
- **A validating constructor must be the only way in, and `serde` is a way in.** `ExposedSet`,
  `CapabilityManifest` and `CapabilityProfile` route `Deserialize` through their constructors. A
  field-wise deserialize leaves every in-code test green while the one path that reads outside input
  — a config file, an MCP descriptor, a spawn request — skips the check entirely.

  **This is the twelfth instance, and it is the first that was caught by design rather than by
  failure.** The other eleven were found after they had shipped, by a screenshot or a number that
  did not add up. This one was closed before it could exist, because the family was named and the
  question "what would this read if the property were broken?" was asked of the serde path
  specifically. That is what naming a failure family is *for*; recognising it only in hindsight is
  the cheaper half.
- **A pipe-tested guard is not a verified guard, and the same shape has now appeared in FOUR
  subsystems.** The weaker claim is always true, cheap, and adjacent:

  | Weaker, and what it actually proves | Stronger, and what the question was |
  |---|---|
  | `get_providers()` lists CUDA as **registered** | where the nodes **ran** (M0c L) |
  | the §13 hook's matcher recognises a path string | an **observed prompt** on a real edit |
  | `persona/v1.md` **loaded** | the persona text is **in the request body** (M2 C2d) |
  | **the source emits it** | **the running process emits it** (M2 C2e) |

  **The fourth is the one that cost a session two turns.** `persona_emission.rs` asserts on a body
  built inside the test process. It passed while the deployed daemon served a binary from before
  the persona commit — so the persona was correct, the test was green, and the model had never seen
  it. A test on the source cannot see a stale deployment.

  **The instrument that closes it is `--dev`'s outbound-request dump**: the bytes the *running*
  process sent. Any future prompt or persona change is verified there, not in a unit test.

  **Each was found separately, in a different subsystem, by someone who had read the previous one.**
  That is why the rule is stated here rather than in a session note.

  **And it was committed again, mid-session, on this exact subject.** C2d pipe-tested the hook with
  a shell-escaped Windows path, got silence, and reported *"the §13 boundary is decorative on
  Windows"* as the session's biggest finding. The hook was fine; the `\` never survived `echo`.
  **The measurement was of bash's escaping, read as a property of the hook.** Testing `reason_for`
  directly took one command and would have caught it before the claim. Ask of any probe: *what else
  could produce this reading?*

- **A guarded path that moved is unguarded, and the guard says nothing.** The **fourteenth**
  instance, and the first where *the guard itself* is what quietly stopped existing.

  M2 Session B split `crates/marlowe-permission/src/scope.rs` into `scope/{mod,request,glob,walk}.rs`.
  The §13 hook's entry named the old file, matched nothing, and **path scoping — the wall, with no
  kernel behind it — was silently unprotected.** No error, no warning, no failing test. The hook
  still ran, still worked, and still guarded every other entry, which is exactly why nothing looked
  wrong.

  **Every other entry in that table has the same failure mode**, and it fires on the most ordinary
  action there is: renaming a file. Two fixes, and both are needed — a directory prefix survives a
  split, and `protect-boundaries.py --self-check <repo>` fails when any guarded path does not exist,
  run by `marlowe-permission/tests/boundary_hook.rs` so a stale entry fails the build. A negative
  control confirms it is not decorative: renaming a guarded file makes it fail by name.

  Generalised: **a guard is a claim about a path, and a claim about a path needs a test that the
  path is still there.** Ask of any protective mechanism — what would this report if its subject
  moved? If the answer is "nothing", the mechanism is a comment.

- **A boundary is not verified until something crosses it. M2 produced this a second time, and
  the first real run is what found it.** Four of the eleven tools — `done`, `ask`, `remember`,
  `run` — are **loop control**, not tool-host executions: they are `ModelStep` variants in
  ARCHITECTURE §3's match. The Ollama adapter mapped every tool call to `ModelStep::ToolCall`, so
  `done` went to the tool host, which has no executor for it, and failed.

  The model then spent **155 seconds** trying to act on a failure it could not interpret, until
  the token budget paused it. **Every unit test passed throughout** — `parse_step` correctly turned
  a tool call into a `ToolCall`, and the tool host correctly reported no executor. Each half was
  right in isolation; the seam between them was wrong, and nothing that tests halves can see a
  seam.

  This is the same lesson M1 produced with scroll, double-dimming and `NO_COLOR`: three bugs found
  by *using* it that no test caught. **Budget one real end-to-end run per milestone as
  verification, not as a demo.**

  **The budget backstop worked on its first real encounter.** `Budget::exhausted` paused the run
  rather than letting it spend indefinitely — the mechanism `budget.rs` was written for, now
  **exercised rather than assumed**. A cap that has never fired is a cap nobody has tested.

## Parallel sessions share a checkout until they do not

**Use `git worktree`.** Two sessions in one checkout share one `HEAD`, and this project has now
produced the hazard in **five distinct forms** in a single day. None lost work; all four of the
first four cost time and one produced a false report.

| # | Form | What happened |
|---|---|---|
| 1 | A branch switch redirects the other session's commits | `git checkout -b m2-loop` at `ed25914`; the retrieval session's next two commits landed on `m2-loop` while `retrieval-m0c` stayed put |
| 2 | The checkout moves under a running session | A fix moved `HEAD` to `retrieval-m0c` mid-session; the next commit landed there |
| 3 | `git add -A` sweeps the other session's in-flight edits | Five of their files went into a commit under someone else's message. `git reset --soft` unpicks it without touching the working tree |
| 4 | **A session reports a real error in the other's mid-edit** | A `profile.write` arity mismatch was accurate when observed and had been resolved minutes earlier |
| 5 | **…and it happens in both directions** | A missing `DegradedPath::ModelUnavailable` was reported against `marlowe-loop` between the tool call that *used* it and the tool call that *defined* it, seconds apart |
| 6 | **One session's build invalidates another's measurement** | A 16-core `cargo build` ran straight through a parallel session's timed queries and inflated every stage ~10%. The table it produced looked complete and was wrong |

**7 — and this one was self-inflicted, on this machine, in this project.** Checking a result with
`cargo test --workspace ... ; cargo test --workspace ...` in one command runs the suite **twice**.
The two runs race over one `target/` and one set of scratch ports, and the second reported **two
failures that do not exist** — 572 pass cleanly when the suite is run once. The same double
invocation, repeated all session, is also the likeliest trigger for a **0x139 kernel bugcheck**
under memory exhaustion: a 16-core rebuild plus ONNX Runtime with the CUDA feature is not a load to
run two of.

**Run the suite ONCE, to a file, and grep the file as many times as you like.** Bound compilation
with `--jobs 4`. A cheap-looking `cmd; cmd` that re-runs the expensive thing is the shape to watch
for — it does not read as a second run.

**And run it with `--no-fail-fast`, or the file records a third of the workspace as though it were
all of it.** `cargo test` stops at the first failing binary; every binary it reached still printed
`test result: ok`, so the file looks complete. Two sessions reported green off per-crate runs that
could not reach a workspace-level guard at all. See "Build and test" below — this is the same rule
and it is stated in both places on purpose, because this section is the one people read when a
number looks wrong.

**6 is the one that does not announce itself.** Forms 1–5 produce a wrong branch, a swept file or
a false error report — all visible. A build stealing CPU from a timed query produces a **complete,
plausible table that is simply wrong**, and the only reason it was caught is that the measuring
session had kept an **un-instrumented control** to compare against. That is the standing lesson
applied to wall-clock: *a number is not evidence unless you know what it would read if the thing
you care about were fine.* **Any timed measurement in a shared checkout needs a control, and any
session about to build should say so first.**

**4 and 5 are the same failure and they are worth naming together.** Both reports were correct
about a state that had already stopped existing. A build error observed in a shared checkout is a
*snapshot*, not a fact — and the reflex it provokes, fixing the other session's code, is exactly
wrong, because only its author knows the intent. **Re-verify before reporting a build break, and
say when it was observed.**

## Do not touch

Per brief §13.

- The permission and approval layer
- Path scoping and egress rules
- Audit logging
- Memory provenance and trust-class propagation
- The trust ledger's promotion logic
- The persona artifact (`persona/vN.md`)

**Enforcement status, stated accurately (2026-08-03).** An earlier version of this file claimed
these were "enforced by PreToolUse hooks — the hooks are the real boundary" when **no hooks
existed at all**. The claim was also unimplementable as written: a matcher needs concrete paths,
and five of the six entries named components that did not exist yet.

**A hook now exists, and here is exactly what it covers.** `.claude/settings.json` runs
`.claude/hooks/protect-boundaries.py` on `Edit|Write|NotebookEdit`. It is **partial by
construction** and the gap is the point:

| Entry | Guarded path | Status |
|---|---|---|
| Memory provenance and trust-class propagation | `crates/marlowe-memory/src/trust.rs` | **Enforced** |
| Audit logging — the signed write path | `crates/marlowe-journal/src/{signature,journal}.rs` | **Enforced** |
| The persona artifact | any `persona/` directory | **Enforced** (pre-emptively) |
| The permission and approval layer | `crates/marlowe-permission/src/{adjudicate,taint}.rs`, `crates/marlowe-loop/src/{profile,provenance}.rs` | **Enforced** (M2 A) |
| Path scoping and egress rules | `crates/marlowe-permission/src/{scope,egress}.rs` | **Enforced** (M2 A) |
| The trust ledger's promotion logic | — | **Not enforced; does not exist yet** (M6) |

**One gap in this that the hook cannot close, named rather than left implicit.** The layer is
guarded; **the loop's call into it is not**. `crates/marlowe-loop/src/engine.rs` is ordinary
milestone work and guarding it would make every loop change ask, but deleting the `adjudicate`
call from it would evaporate the boundary while every file above stayed untouched. What stands
behind that is a test, not the hook:
`marlowe-loop/tests/spawn_and_budget.rs::a_tool_call_whose_target_came_from_untrusted_content_is_blocked_by_the_loop`
drives a real blocked call **through the loop**. If the call site goes, that test fails.

**PIPE-VERIFIED, which is weaker than live-verified (downgraded 2026-08-09).** On 2026-08-08 each
path above was *pipe-tested* — JSON fed to the hook's stdin, decision read from stdout — and
`engine.rs` confirmed to return no decision. **A pipe test proves the matcher recognises a string.
It does not prove the hook fires when the agent edits the file.** Those are different questions and
only an **observed permission prompt on a real edit** answers the second: the wiring in
`settings.json`, the matcher, the harness's permission mode and the path format it passes all sit
between the two, and a pipe test sees none of them.

Every claim in this table is currently pipe-verified only. **Downgrade each to live-verified
individually, by editing the file and observing the prompt** — not in a batch, because one observed
prompt says nothing about the other entries.

**As each component lands, add its path to the hook.** A component with no entry is unguarded
regardless of what this list says — the entry is the enforcement, and the list is only a map of it.

The hook returns `ask`, not `deny`. The boundary is against the agent changing safety machinery on
its own initiative, not against the project evolving it; a human who reads the reason and approves
has made the decision the boundary exists to require. A change here should arrive with a
`DECISIONS.md` entry.

**Pipe-verified 2026-08-03**, with one entry shown to fire on a real `Edit`. The rest are matcher
checks — see the downgrade above.

**Building a listed component in its assigned milestone is not "touching" it.** The boundary is
against a later session — or the agent's own self-improvement at M9 — modifying safety machinery
that already exists. M0b Session A writes trust-class propagation for the first time; that is the
milestone's scope, not a violation. Once it exists, changes to it need an explicit decision.

## Build and test

Two artifacts, deliberately separate (ADR-001): the harness is Python, the implementation is Rust.

```bash
# The scoreboard. Never modified to accommodate an implementation.
cd eval && python -m pytest                  # 72 passing

# The implementation. --no-fail-fast IS NOT OPTIONAL -- see below.
cargo test --workspace --jobs 4 --no-fail-fast > runs/<session>/suite.txt 2>&1
# 922 passing, 0 failing, 2 ignored (ADR-044, 2026-08-17), with MARLOWE_CUDA_LIB_DIR set.
# Tally the FILE, do not trust a tail: 83 `test result` lines, and one FAILED among them
# is invisible in the last twenty.
cargo build --release                        # -> target/release/marlowe.exe
```

### `MARLOWE_CUDA_LIB_DIR` — set it, or this machine silently runs the embedder on CPU

**The embedder defaults to `auto` (ADR-044): GPU where a CUDA session constructs, CPU otherwise.**
The variable is the *only* thing standing between those two outcomes here, and an unset variable is
not an error — it is a slower run with a correct-looking log line.

```bash
# torch 2.5.1+cu121 ships CUDA 12.1 and cuDNN 9 in its own lib dir (4.2 GB of them). NO CUDA
# TOOLKIT IS INSTALLED AND NONE IS NEEDED -- ADR-015 said so, and a session was lost concluding
# "the DLL cannot be found" meant "the DLL does not exist". `cuda_libs.rs` reads this and adds the
# directories to ORT's DLL search path; that is the one reader.
export MARLOWE_CUDA_LIB_DIR="$USERPROFILE/AppData/Local/Programs/Python/Python311/Lib/site-packages/torch/lib"
```

**The one command that says which provider actually resolved — read it from the SHIPPED binary,
never from `cargo run --example`, which builds a different artifact:**

```bash
target/release/marlowe.exe --eval-adapter --profile-root "$(mktemp -d)" \
    --embedder-model models/jina-embeddings-v2-small-en --reranking off < /dev/null
# marlowe: embedder asked for auto, running on CUDAExecutionProvider with 8 of 8 worker session(s)
#          ^ CPUExecutionProvider here means the variable is unset, or the card is full.
```

**It does NOT survive the eval harness.** §4.0.9 spawns the target with a declared minimal
environment and `minimal_env()` is a fixed allowlist that does not include it. `PATH` is on that
allowlist and `PATH` is what the Windows loader actually reads, so `tools/score_longmemeval.py`
translates the variable onto `PATH` in its own process before anything spawns and records what it
did in `ENVIRONMENT.json`. `eval/` is the scoreboard and was not modified for this.

### `--no-fail-fast`, and the two sessions that reported green without it

**Amended 2026-08-17, because two things in the line above were false.**

**1. `cargo test` FAIL-FASTS AT THE FIRST FAILING BINARY.** It does not run the rest. A workspace
run that hits a failure in `marlowe` stops there and **never compiles or runs `marlowe-extract`,
`marlowe-surface` or anything after it** — and the output looks like a completed run, because every
binary it did reach printed `test result: ok`. Session E's first run covered roughly a third of the
workspace and read as complete. **Any run whose purpose is a COUNT needs `--no-fail-fast`.** A run
whose purpose is "did my change break this" does not.

**2. THE PER-CRATE HABIT HID A GUARD FOR TWO SESSIONS.** Working per-crate (`cargo test -p <crate>`)
is right for iteration and it is **structurally incapable** of seeing a workspace-level guard.
`crates/marlowe/tests/determinism_guard.rs` greps every `.rs` file under `crates/` and lives in
`marlowe`'s test target, so **no `-p` command that does not name `marlowe` can ever run it** — and
the crates it was failing on were `marlowe-net`, `marlowe-extract`, `marlowe-exec` and
`marlowe-loop`, none of which is `marlowe`.

**Named, so the correction is auditable rather than a tidy-up: the tools/parallelism session
(`1d3a428`) and the layer-1/security session (`e35dd9a` and its neighbours) both reported green, and
both were wrong.** Each listed per-crate counts — *"`marlowe-loop` 89, `marlowe-extract` 57,
`marlowe-daemon` 53"* — which were accurate and which could not have revealed the failure. Session E
inherited the same habit and reported *"every crate green"* on the same basis before checking.

**So: per-crate while working; `--workspace --no-fail-fast` ONCE, to a file, before any claim that
the tree is green.** The count in that claim comes from the file, not from memory.

**This is the same family as everything else in this document.** A per-crate suite answers *"is this
crate's own test target passing"*, which is adjacent to *"is the tree green"* and reads identically
when the answer is no. Ask what the number would read if the thing you care about were broken.

**Scoring M0b against M0a** — this is the only number that counts. `{profile_root}` is a literal
token the harness replaces with a fresh empty directory on every spawn; it is required, because
each spawn must start from empty state.

```bash
cd eval
# --embedder-model is REQUIRED and has no default (Session C). A target without it fails as
# `implementation_crashed` on every interface, which reads like a protocol bug and is not one.
#
# --reranking is REQUIRED and has no default (Session H), and it takes an EXPLICIT value: either
# a model directory or the literal `off`. It is deliberately not a bare boolean — a default-off
# switch forgotten in a target string measures the un-reranked system under a reranked label.
# `off` is the pruning-only ablation and is a recorded choice; omitting the flag refuses to start.
#
# THE PINNED GRAPH IS THE SESSION J FINE-TUNE, f32 (Session K, ADR-018/ADR-020). The old int8
# directory is refused BY NAME — a stale path gets an error naming the swap, not "file not found".
#
# --embedder-provider is SPELLED OUT here even though it has a default, because ADR-044 made that
# default `auto`, and `auto` resolves against free VRAM AT LOAD. Two spawns of `repro` on one
# machine can then open different widths, or different providers, because something else started
# on the card in between - and worker-count invariance is measured on CPU, not on CUDA. Pin `cpu`
# or `cuda` for anything reproducible or published; `auto` is the product default, not a
# measurement setting.
TARGET="exec://../target/release/marlowe.exe --eval-adapter --profile-root {profile_root} \
        --embedder-model ../models/jina-embeddings-v2-small-en \
        --reranking ../models/ms-marco-MiniLM-L-2-v2-ft-session-j \
        --embedder-provider cpu"

PYTHONPATH=src python -m marlowe_eval.cli conformance --target "$TARGET"   # section 4 + clock probe
PYTHONPATH=src python -m marlowe_eval.cli run --target "$TARGET" --out runs/a
PYTHONPATH=src python -m marlowe_eval.cli repro --runs 2 --target "$TARGET"
```

**Omit `--embedding-cache` for `repro`.** Two cold runs re-embed everything, which makes the
determinism check cover the embedder across process spawns as well as the ranking. It is slower and
it is the stronger check.

**The gate, and the real corpus.** The frozen gate is a **build-time artifact** — the binary
refuses to start without one and there is no default weight vector, so a fresh clone reproduces
the number rather than inheriting it. The corpus is never vendored (`data/` is gitignored);
`fetch.py` pins its digest.

```bash
python tools/preregister_split.py       # ONCE, in Session B. Never re-run.
python tools/dump_consolidation.py      # the dry-run sweep; APPLIES NOTHING
python tools/preregister_session_f.py   # this session's bands, BEFORE any fit
python tools/fit_gate.py                # refuses without the split OR the pre-registration
cargo build --release                   # embeds the artifact via include_str!
python tools/score_longmemeval.py --out runs/session-f \
       --reranking models/ms-marco-MiniLM-L-2-v2-ft-session-j \
       --embedder-provider cpu     # BOTH required: Session K, then ADR-044
python tools/analyze_cue_overlap.py --run runs/session-f/heldout --record-verdict
```

**`--embedder-provider` is required in `score_longmemeval.py` as of ADR-044, for the identical
reason.** It used to pass through to the binary's default, that default was `cpu`, and ADR-044
changed it to `auto`. The same command that measured CPU last week now measures whatever the card
had free at that instant — a published number silently relabelled by a default nobody typed.

**`--reranking` is required in `score_longmemeval.py` too, and that is a Session K change with a
reason.** It defaulted to the int8 directory. The moment the shipped graph moved, that default
would have scored the **old** graph and written the result under the shipped label, with nothing
observing the mismatch — the exact pattern this file warns about four paragraphs down.

**The precision/coverage curve is a published artifact, not a run output.** The amended K1 (2026-08-08)
requires it to ship with the product:

```bash
python tools/score_longmemeval.py --out runs/session-k --fit-only --reranking <DIR> \
       --embedder-provider <cpu|cuda>          # tau calibration
python tools/publish_precision_coverage.py --run runs/session-k --reranking-label <NAME>
# -> crates/marlowe-memory/artifacts/precision-coverage-heldout-v1.json
# -> docs/design/PRECISION-COVERAGE.md
```

**The conformal guarantee and the measured precision are two different quantities and are never
conflated.** The marginal bound covers `P(inject | wrong)`; K1 asks for `P(correct | injected)`,
a selective risk it does not cover. Both are reported, on separate lines, always.

**Session H's rerank stage has a second pinned model and its own fixture.** The cross-encoder is
digest-pinned at load exactly as the embedder is, and the hand-rolled BERT *pair* encoder is a
second implementation of a scored-path component, so the standing check applies to it. **Every
argument is required — Session K made the fixture a per-graph artifact, and a default `--model-dir`
would regenerate one graph's reference from another graph's weights:**

```bash
python tools/make_cross_encoder_fixtures.py \
    --model-dir models/ms-marco-MiniLM-L-2-v2-ft-session-j \
    --model-file model.onnx \
    --out crates/marlowe-memory/tests/fixtures/cross-encoder-reference-ft-session-j.json
cargo test -p marlowe-memory --test cross_encoder_reference   # NEVER regenerate to make it pass
```

**Pin the ONNX graph optimization level on both sides.** `ort` builds at `Level1`; Python's default
is `ORT_ENABLE_ALL`, and the two fuse this int8 graph differently — identical token ids, logits
**0.0699** apart, nearly twice the batch-invariance failure that blocked adoption in Session G. Every
Python tool that scores with the cross-encoder sets `ORT_ENABLE_BASIC` explicitly. An offline
measurement taken at a different level measures a different scorer.

**The quantized graph is bound to its tensor shape in EVERY dimension — `[1, 256]` is load-bearing
exactly as batch = 1 is.** Session I re-padded bit-identical token ids to a longer tensor, changing
nothing but the shape: int8 moved by a median **0.0109** logits and **padding alone flipped top-1 in
15% of cases**, while all eight f32 graphs were invariant to **0.000000**. **Any sweep that varies
sequence length runs f32, or its cells are different scorers.** This also corrects ADR-014's
neighbourhood: the batch-invariance failure was *quantization*, not architecture. See ADR-015.

**The SHIPPED path is f32 as of Session K, so it no longer carries that hazard — and the check is
still per-graph.** Moving to the fine-tuned graph (ADR-018) removed quantization from the scored
path: batch invariance **0.000000**, padding invariance **0.000000**, re-measured on the shipped
graph rather than inherited. **Batch stays 1 structurally anyway**, because invariance is a
measurement a re-pin does not inherit. Any future re-quantization re-opens ADR-015 on a graph
nobody has measured that way, and `[1, 256]` would have to be re-verified, not assumed.

**The cache-cold latency read cannot be taken over the full split, and the reason is measured.** On
a cold cache the implementation must embed a whole session's turns inside one §4.6 ingest call, and
some LongMemEval sessions exceed the harness's §4.0.7 30-second deadline — which aborts the run
before it scores anything. Retrieval P95 is a *per-query* property, so it is read from a bounded
subset instead, and `--max-cases` refuses to combine with a quality number.

```bash
python tools/score_longmemeval.py --out <scratch> --heldout-only --max-cases 40 \
       --embedding-cache <fresh empty dir> --embedder-provider <cpu|cuda>
```

**`tools/` imports `marlowe_eval` as a library and changes nothing in it.** The harness
deliberately exposes no real-corpus path to `run`; adding `--corpus-path` would be the
implementation reshaping the scoreboard's interface for its own convenience. If that flag is
right long-term it is an M0a change, argued separately.

**Pre-registration is a file, not an intention.** `tools/split.json` and
`runs/session-b/PREREGISTRATION.json` are written before the fit, and `fit_gate.py` refuses to
run without them. Bands, budget conditions and the poisoning-vacuity prediction all live there,
so a green suite can never be read as evidence for something nobody predicted.

Toolchain on Windows: MSVC (`rustup default stable-x86_64-pc-windows-msvc`) plus the VS C++
workload and Windows SDK — `rusqlite`'s bundled SQLite compiles C, and ADR-004's ONNX runtime
will want MSVC too.