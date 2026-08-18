# CI — what runs, when, and what it deliberately does not cover

`.github/workflows/ci.yml`. One workflow file, on purpose.

## When it runs

| trigger | when |
|---|---|
| `workflow_dispatch` | manually, whenever you want it — Actions tab, "Run workflow" |
| `schedule` | **Mondays 04:00 UTC** |

**It does NOT run on push and it does NOT run on pull requests.** That was the original
configuration and it was changed 2026-08-18 at the human's request: a suite this size on every push
is noise, and a check people learn to ignore has already stopped being a check.

**Why it is not `workflow_dispatch` alone.** ADR-027 calls the path-traversal suite a **standing
two-platform requirement**, and before this file existed it had been run by hand exactly once —
2026-08-08, at the close of M2 Session B — and nothing re-ran it for nine days. Manual-only puts it
straight back to *"runs when somebody remembers"*, which is the condition the file was written to
fix. A week is short enough that a break is attributable to a handful of commits and long enough to
stay quiet.

**If the weekly run is ever disabled, the two-platform requirement is a recollection again.** Say so
in `ROADMAP.md` rather than leaving the row reading as enforced.

Cron fires on the default branch only. `concurrency` cancels a superseded run per ref.

## What it runs

### Job `eval` — ubuntu-latest

`cd eval && python -m pytest`. The scoreboard, 72 tests. **Needs no models and no corpus**, so it is
the one job that is fully covered on a fresh runner.

### Job `workspace` — matrix: **ubuntu-latest AND windows-latest**

Both, and the reason is that the halves do not overlap. The symlink traversal classes cannot run on
Windows without elevation and the POSIX walk never executes there; the Windows pinning never
executes on Linux. **A TUI or a wall verified on one platform is not verified**, and ROADMAP.md says
so in those words.

| step | what it is for |
|---|---|
| `cargo test --workspace --no-fail-fast` | the whole suite |
| **Traversal suite — Linux**, `MARLOWE_TRAVERSAL_STRICT=1`, **every class must RUN** | the path-scoping wall |
| **Traversal suite — Windows**, only the symlink class may be unrunnable | the other half of it |
| **§13 boundary hook** — `protect-boundaries.py --self-check` | catches a guarded path being renamed |
| **Determinism guard** | lives in `crates/marlowe/tests/`; **invisible to per-crate runs** |
| **Skip manifest** — never fails | prints what did not run for want of `models/` |

## Three deliberate choices

**1. "Every class must RUN", not "the suite passed."** A traversal suite that silently skips all
eleven classes also passes. Session B's close recorded **11/11 RAN**; asserting the count is the
check, and asserting the exit code is not.

**2. `--workspace` AND the determinism guard named explicitly.** Two ways for one guard to be
missed, closed twice. The guards in `crates/marlowe/tests/` **only run under `--workspace`** — which
is precisely how two sessions reported the suite green while the tree was red, both having run
per-crate. `--no-fail-fast` matters for the same class of reason: `cargo test` stops at the first
failing binary, so a run whose purpose is a count needs it or it silently covers less than it looks.

**3. The skip manifest never fails the build.** `models/` and `data/` are gitignored and **never
vendored**, so a fresh runner has neither. Every model-dependent test skips, loudly, by design. The
manifest prints which ones — because the alternative is a green badge quietly covering less than it
appears to, and that is worse than a red one.

## What CI does NOT cover — read this before reading a green badge as more than it is

- **The embedder, the reranker, the cross-encoder reference, every retrieval number.** No `models/`
  on a runner, so they skip.
- **Any quality figure.** No `data/` corpus, so R@1 and the precision/coverage curve are not
  computable there.
- **K6** — install to first useful output. Needs a container and a pulled model.
- **The accent row's by-eye half.** §B13 asks for confirmation by eye on both backgrounds and a
  number is not an eye.
- **CUDA anything.** Runners have no NVIDIA device and no `MARLOWE_CUDA_LIB_DIR`; `auto` correctly
  resolves to CPU, which means the GPU paths are exercised nowhere but locally.

## Status

**As of 2026-08-18 this workflow has NEVER EXECUTED.** The YAML parses, the matrix is right and the
commands match what runs locally — but a workflow that has never run is a claim, not a guard. **The
first dispatch is the test**, and failures on it should be expected and read as the point rather
than as a setback.
