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

  The ledger, for the last three, because the count is only useful if it is auditable:
  **12** — `Deserialize` routing around a validating constructor (M2 A; the first caught by design).
  **13** — R@1 counting a superseded fact as a hit, so every R@1 in the project was inflated
  (M0c; `docs/design/HARM-WEIGHTED-PRECISION.md`). **14** — a guarded path that moved, below.
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

Verified live on 2026-08-08: each new path above was pipe-tested against the hook, and
`engine.rs` was confirmed to return no decision — so the gap is measured, not assumed.

**As each component lands, add its path to the hook.** A component with no entry is unguarded
regardless of what this list says — the entry is the enforcement, and the list is only a map of it.

The hook returns `ask`, not `deny`. The boundary is against the agent changing safety machinery on
its own initiative, not against the project evolving it; a human who reads the reason and approves
has made the decision the boundary exists to require. A change here should arrive with a
`DECISIONS.md` entry.

Verified live on 2026-08-03: the blocking logic was pipe-tested against each protected path, and
the hook was shown to fire on a real `Edit`.

**Building a listed component in its assigned milestone is not "touching" it.** The boundary is
against a later session — or the agent's own self-improvement at M9 — modifying safety machinery
that already exists. M0b Session A writes trust-class propagation for the first time; that is the
milestone's scope, not a violation. Once it exists, changes to it need an explicit decision.

## Build and test

Two artifacts, deliberately separate (ADR-001): the harness is Python, the implementation is Rust.

```bash
# The scoreboard. Never modified to accommodate an implementation.
cd eval && python -m pytest                  # 72 passing

# The implementation.
cargo test --workspace                       # 375 passing (273 before M2 Session A)
cargo build --release                        # -> target/release/marlowe.exe
```

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
TARGET="exec://../target/release/marlowe.exe --eval-adapter --profile-root {profile_root} \
        --embedder-model ../models/jina-embeddings-v2-small-en \
        --reranking ../models/ms-marco-MiniLM-L-2-v2-ft-session-j"

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
       --reranking models/ms-marco-MiniLM-L-2-v2-ft-session-j   # REQUIRED since Session K
python tools/analyze_cue_overlap.py --run runs/session-f/heldout --record-verdict
```

**`--reranking` is required in `score_longmemeval.py` too, and that is a Session K change with a
reason.** It defaulted to the int8 directory. The moment the shipped graph moved, that default
would have scored the **old** graph and written the result under the shipped label, with nothing
observing the mismatch — the exact pattern this file warns about four paragraphs down.

**The precision/coverage curve is a published artifact, not a run output.** The amended K1 (2026-08-08)
requires it to ship with the product:

```bash
python tools/score_longmemeval.py --out runs/session-k --fit-only --reranking <DIR>   # tau calibration
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
       --embedding-cache <fresh empty dir>
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