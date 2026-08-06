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
- **Watch for defaults that make a mismatch unobservable.** A fallback value, a permissive
  default, a re-resolved path — each lets two sides silently disagree while the test goes green
  because the failing path stopped existing. This pattern has produced four bugs in this project
  already. Prefer a load-time error to a sensible default.

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
| The permission and approval layer | — | **Not enforced; does not exist yet** |
| Path scoping and egress rules | — | **Not enforced; does not exist yet** |
| The trust ledger's promotion logic | — | **Not enforced; does not exist yet** |

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
cargo test --workspace                       # 188 passing
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
TARGET="exec://../target/release/marlowe.exe --eval-adapter --profile-root {profile_root} \
        --embedder-model ../models/jina-embeddings-v2-small-en \
        --reranking ../models/ms-marco-MiniLM-L-2-v2-int8"

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
python tools/score_longmemeval.py --out runs/session-f
python tools/analyze_cue_overlap.py --run runs/session-f/heldout --record-verdict
```

**Session H's rerank stage has a second pinned model and its own fixture.** The cross-encoder is
digest-pinned at load exactly as the embedder is, and the hand-rolled BERT *pair* encoder is a
second implementation of a scored-path component, so the standing check applies to it:

```bash
python tools/make_cross_encoder_fixtures.py   # HF tokenizers + ONNX reference; NEVER regenerated
                                              # to make the Rust test pass
cargo test -p marlowe-memory --test cross_encoder_reference
```

**Pin the ONNX graph optimization level on both sides.** `ort` builds at `Level1`; Python's default
is `ORT_ENABLE_ALL`, and the two fuse this int8 graph differently — identical token ids, logits
**0.0699** apart, nearly twice the batch-invariance failure that blocked adoption in Session G. Every
Python tool that scores with the cross-encoder sets `ORT_ENABLE_BASIC` explicitly. An offline
measurement taken at a different level measures a different scorer.

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