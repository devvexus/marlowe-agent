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
cargo test --workspace                       # 49 passing
cargo build --release                        # -> target/release/marlowe.exe
```

**Scoring M0b against M0a** — this is the only number that counts. `{profile_root}` is a literal
token the harness replaces with a fresh empty directory on every spawn; it is required, because
each spawn must start from empty state.

```bash
cd eval
TARGET="exec://../target/release/marlowe.exe --eval-adapter --profile-root {profile_root}"

PYTHONPATH=src python -m marlowe_eval.cli conformance --target "$TARGET"   # section 4 + clock probe
PYTHONPATH=src python -m marlowe_eval.cli run --target "$TARGET" --out runs/a
PYTHONPATH=src python -m marlowe_eval.cli repro --runs 2 --target "$TARGET"
```

Toolchain on Windows: MSVC (`rustup default stable-x86_64-pc-windows-msvc`) plus the VS C++
workload and Windows SDK — `rusqlite`'s bundled SQLite compiles C, and ADR-004's ONNX runtime
will want MSVC too.