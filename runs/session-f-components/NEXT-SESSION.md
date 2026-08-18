# Next session — start here

Read `STATE.md`'s **OUTSTANDING** section first; it is the top of the file and it is current as of
2026-08-18. Everything below that section is history.

## First command, before anything else

```
cargo build --release
cargo test --workspace --jobs 4 --no-fail-fast > runs/<session>/suite.txt 2>&1
grep -E "^test result" runs/<session>/suite.txt
```

**The last recorded 944 passed / 0 failed predates the final agent's work**, so it is stale. Do not
quote it. `--workspace` and `--no-fail-fast` both matter: the guards in `crates/marlowe/tests/` only
run under `--workspace`, and two sessions reported green on a red tree by running per-crate.

## What is genuinely open

**1. The four M2 acceptance benchmarks** — SWE-bench Verified, Terminal-Bench 2.0, τ-bench, BFCL.
Deferred by the human twice, and correctly: **no harness for any of them exists in this repo**
(`eval/src/marlowe_eval/suites/` is memory-only). This is integrating four external harnesses
against a 9B local model — a milestone with its own scope, not a session's work. Recorded UNMET AND
UNSCHEDULED in `ROADMAP.md`. **Scope it before starting it.**

**2. CI has never executed.** `.github/workflows/ci.yml` is committed (`9591ef4`), valid YAML, matrix
`ubuntu-latest` + `windows-latest`. The first push is the test. `models/` and `data/` are gitignored
and never vendored, so a fresh runner has neither — the workflow's skip manifest exists to make that
gap legible rather than silent.

**3. `auto_sessions` discards its warm-up result.** A failed warm-up collapses the per-session cost
estimate to a 188 MB floor against a real 690–800 MB, so ORT's allocator rather than the budget stops
the loop. Measured, deliberately unfixed: its failure branch cannot be driven from a test, and an
untestable budget change is the shape that goes green and does nothing.

**4. `--serve` never announces the resolved rerank provider** — it exists only on `--status`. A
daemon silently on CPU and one on CUDA print identical startup lines. One line; ADR-029's
*announced, never inferred* applied to one surface and not the other.

**5. M1's accent row, by-eye half.** Arithmetic is asserted (`e21cae7`). §B13 asks for confirmation
by eye on both backgrounds and a number is not an eye. **Human action, not agent work.**

## The ordering constraint — get this wrong and three defects go live together

**Fix the compaction stamp (E5) and the trim marker (F1) BEFORE `ingest` is wired into the product.**
Layer 3's latch is unreachable in the shipped daemon today; the moment `ingest` has a production path
it goes live *alongside* those two known defects in the same path.

## The finding that reframes the quality numbers

`memory.rs:94-98`, written by whoever built it, before anyone went looking:

> *"The dense cue scores 0.0 for every candidate without vectors, so retrieval here is **lexical +
> rerank**."*

The daemon runs **lexical + rerank**. The benchmark runs **lexical + dense + rerank**. **Every
published retrieval number — R@1 0.6725 included — was measured with a cue the product does not
have.** See `docs/design/EVAL-PRODUCT-DIVERGENCE.md`, and note its counter-example: the reranker is
NOT divergent, so this is three specific components rather than a subsystem.

## What was settled and should not be re-litigated

- **The VRAM reserve against external processes was CONSIDERED AND REJECTED** by the human. *"Our
  memory for our application is our memory."* It is unbounded by construction. What replaces it is an
  ordering **within** Marlowe's footprint: **LLM first, voice second, everything else wherever it
  fits.** Matters when changing models. Two amendments were overturned to get here — do not re-derive
  the rejected version.
- `MAX_SEQ_LEN` is 1024, chosen from the token-length distribution rather than by sweeping R@1.
- Embedder and reranker both default to `auto` (ADR-044, ADR-045).
- `MARLOWE_CUDA_LIB_DIR` must point at torch's lib dir for CUDA to construct. No CUDA Toolkit needed.

## Traps this session paid for

- `cargo run --example` does **not** rebuild `marlowe.exe`. A source edit is not a deployed change —
  check mtimes before attributing a measurement to a change.
- `cmd | tail` returns **tail's** exit status. A failed run reported as exit 0.
- `pgrep -f` does not see Windows processes. A completion check fired on a 6.7 MB partial dump that
  later reached 72.8 MB.
- **A control proves the instrument can detect a difference; it does not prove it was ever pointed at
  anything.** Gate 1's first run printed a clean PASS over zero comparisons — every scoring call had
  been refused for exceeding a measured batch bound, and both existing controls passed.
- `examples/rerank_gate1.rs` reads a dump that has since been deleted. Gate 1's result stands; the
  example needs the dump regenerated to re-run, and exits with a clean `SKIP:`.

## Disk

`runs/session-l` is **6.2 GB** and predates this session. It is where the remaining space is — but
`session-l/RESULT.md` is the artifact proving CUDA has always worked from Rust, which corrected a
wrong conclusion this session. Read before clearing.
