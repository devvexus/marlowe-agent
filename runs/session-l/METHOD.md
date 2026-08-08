# M0c Session L — retrieval latency: the method, written before the numbers

This file fixes how the profile is taken, so the table that follows cannot be read as having
chosen its own measurement conditions. Numbers land in `RESULT.md`.

## The instrument

`marlowe --eval-adapter --profile-retrieval <FILE>` writes one NDJSON row per §4.2 call:
the query embedding, nine pipeline stages, the span they were taken inside, and the residual
between the two — all in **microseconds**.

**The memory crate reads no clock.** §4.5 forbids one on any path reachable from §4.1/4.6/4.7 and
`determinism_guard.rs` enforces it by file name. `marlowe_memory::probe` therefore announces stage
*boundaries* and measures nothing; `marlowe::elapsed::StageTimer`, inside the existing fence, is
what turns them into durations. The allowlist did not grow. The shape is ADR-027's `WalkObserver`:
a deterministic observation point, `()` in production.

**One call site, not two.** The probe is `Option<&mut StageTimer>`, so a run without
`--profile-retrieval` is a true baseline and the profiled path cannot drift from the shipped one.
A second `select_for_injection` written "for profiling" would be the two-sides-silently-disagree
pattern applied to a measurement.

**The profile is written after `cost.latency_ms` is read.** Profiling cannot inflate the number it
exists to explain. The gate-feature dump stays *inside* the span, where it has been for every
published latency in this project — moving it now would change the baseline as a side effect of
adding an instrument.

## What the residual is for

`residual_us = span_us − Σ stages`. A breakdown that does not add up can hide exactly the cost it
was built to find: a profile whose stages covered 60% of the span would still produce a plausible
ranking, and the missing 40% would be silently attributed by the reader to whichever stage they
already suspected. `tools/profile_retrieval.py` prints the residual share and returns **REFUSED**
above 5%.

`unattributed_ms = total − span − embed` is named separately: response serialization and the
gate-feature dump. Both are inside `cost.latency_ms` and outside every stage.

**This check has already earned its place.** The first draft read `span` inside the profile
writer, which runs *after* the gate-feature dump has written ~500 JSON rows — so `span` absorbed
~1.5 ms of diagnostic I/O and reported it as pipeline residual, while the `unattributed` column
that existed to catch precisely that read zero. The instrument was misattributing its own overhead
to the thing it measures. `span_us` is now captured by the caller the instant the pipeline returns.

## Conditions held fixed across every cell

| | |
|---|---|
| ONNX intra/inter threads | **1**, both embedder and cross-encoder (`with_intra_threads(1)`) |
| ONNX graph optimization | **Level1**, pinned both sides |
| `--embedder-workers` | default (`min(available, 8)` = 8). Ingest only; the query embed uses `sessions[0]` alone, so the timed retrieval span is single-threaded |
| rerank depth | `RERANK_BUDGET` = 10, batch 1, seq 256, f32 |
| graph | `ms-marco-MiniLM-L-2-v2-ft-session-j`, sha256 `9c222dac…` |
| binary | sha256 recorded **before and after** every run; a run whose binary changed under it is discarded |

The binary digest guard is not ceremonial: a second session is working in this same checkout
(HEAD moved `1c6dc0e` → `e8e6dd0` mid-session, `crates/marlowe-exec/` appeared). A concurrent
rebuild could swap `marlowe.exe` between two cells of a sweep, and the sweep would then compare two
binaries under one label.

## The two populations, and why both are needed

`--max-cases 40` subsets the corpus by case **and drops the sessions with it**, so the 40-case cold
read holds a store of ~19k memories where a full held-out pass holds ~113k (`considered` reads
113,000 on a typical query in `runs/session-k/heldout`, peaking at 121,470).

The candidate scan is the one stage whose cost scales with **store size rather than query count**.
So the cold cell understates precisely the stage ADR-003 is about, and a profile taken only there
would retire the hot-index question on a measurement that could not see it.

| cell | cache | cases | store | what it is for |
|---|---|---|---|---|
| cold-40 | fresh empty dir | 40 | ~19k | the headline **cold P95**, and the query forward pass |
| warm-249 | shared | 249 | ~113k | the **candidate scan** at production store size |

Cold is the number quoted. STATE.md records the trap explicitly: a warm cache removes the query's
forward pass from the timed span. The profile carries `embed_was_cached` per row, so a warm run
cannot be reported as cold — `tools/profile_retrieval.py` prints `COLD`/`WARM`/`MIXED` and states
that a MIXED profile is two populations whose percentiles belong to neither.

## What is reported

Full distribution per stage — P50, P90, P95, P99, max — never P95 alone. A change that improves
P95 and worsens P99 is worse for a system with a hard deadline.

**Per-stage P95s are not presented as shares of the total P95.** They are taken over different
queries and do not sum; a percentage breakdown built from them is arithmetic nobody performed.
Three separate things are reported instead: the per-stage distribution, the decomposition of the
single query sitting at the P95 of total latency (a real breakdown of a real request), and the
mean share across queries.
