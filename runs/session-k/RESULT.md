# M0b Session K — the fine-tuned reranker ships, K1 is amended, M0b closes

**This is the first session since H to change the scored path, and the first ever to ship a change
that was significant on held-out with the power to have detected an effect.**

| | |
|---|---|
| **1. The Session J fine-tune is SHIPPED** | `rerank.rs` re-pinned to `ms-marco-MiniLM-L-2-v2-ft-session-j`, **f32**. Held-out R@1 **0.5764 → 0.6725**. Every standing check re-run on the shipped graph. **ADR-020.** |
| **2. The precision change removes a hazard** | int8 → f32 takes ADR-015's shape-binding off the scored path: batch invariance **0.000000**, padding invariance **0.000000**, re-measured not inherited. |
| **3. K1 is amended and the threshold is NOT moved** | Judged on a published curve; a **new** flatness kill condition is added. **ADR-019.** |
| **4. The curve is published and an operating point is declared** | `docs/design/PRECISION-COVERAGE.md` + a versioned artifact beside the frozen gate. |

---

## Part 1 — what shipped, and the numbers from the BINARY

All held-out, n = 229, read by `tools/analyze_cue_overlap.py` from the binary's own dump — the same
tool and the same population every published R@1 in this project has used since Session C.

| held-out, n=229 | Session H (int8) | **Session K (shipped)** | delta |
|---|---|---|---|
| **R@1** | 0.5764 | **0.6725** | **+0.0961** |
| **R@5** | 0.8428 | **0.8865** | +0.0437 |
| **R@10** | 0.9039 | **0.9039** | **+0.0000** |
| **input recall** (207/229) | 0.9039 | **0.9039** | **+0.0000** |
| **conditional accuracy** (154/207) | 0.6377 | **0.7440** | **+0.1063** |
| **retrieval P95, warm, full split** | 149 ms | **211 ms** | budget 300 ms — **PASSES** |
| **retrieval P95, cache-COLD, 40-case subset** | — | **238 ms** | budget 300 ms — **PASSES** |
| tokens over budget | 0 | **0** | budget 7,000 |

**Read this against conditional accuracy, not R@1 alone** — STATE.md's standing instruction, and
here it is unusually clean. `R@1 = input_recall × conditional_accuracy` factors exactly:
`0.6725 = 0.9039 × 0.7440`. **Input recall did not move by a single case.** A cross-encoder cannot
change what is in the slate handed to it, only the order within it, and the measurement says exactly
that. **The entire gain is conditional accuracy, +0.1063.**

**R@10 is unchanged at 0.9039 and that is not a disappointment — it is the same caution Session H
recorded.** This is a top-1 mechanism reordering ten candidates. At top-10 the shipped ranker still
sits below dense alone (0.9039 vs 0.9170). Do not read its R@10 as a capability.

**The unchanged components are bit-identical to Session H**, which is the control on the whole
change:

| | Session H | Session K |
|---|---|---|
| lexical | 0.5415 | **0.5415** |
| dense | 0.4454 | **0.4454** |
| fitted_gate | 0.5371 | **0.5371** |
| either-cue oracle | 0.6463 | **0.6463** |

Only the reranked level moved. Nothing else did.

### The delta against Session J's *measurement* is +0.0699; against what was *shipped* it is +0.0961

Both are true and they answer different questions. ADR-018's `+0.0699` is fine-tuned L-2 f32 against
**un-tuned L-2 f32** — the contrast that isolates domain adaptation, and the one with the McNemar
test behind it (discordant 38, `p = 0.0139`). `+0.0961` is what a user gets, because the thing being
replaced was the **int8** graph. **Quote +0.0699 for the effect of fine-tuning and +0.0961 for the
effect of this session. Never quote +0.0961 as the fine-tuning effect** — part of it is the int8-to-
f32 precision change, which ADR-015 measured separately.

### Latency: 149 → 211 ms warm, 238 ms cold. Both inside the budget.

Projected ~274 ms before the run (Session H's 149 ms, swapping 89 ms/query of int8 rerank for
214 ms/query of f32). **Measured 211 ms warm on the full split, 238 ms cache-cold on the bounded
40-case subset.** The projection was pessimistic because the rerank stage overlaps other per-query
work.

**It passes, and the margin is now thin.** The cold read is the one that matters for a fresh
profile, and 238/300 leaves **62 ms**. A future change adding ~60 ms/query to retrieval breaks the
budget, and K1's precision numbers are *defined at these budgets* — a violation would make them
void, not caveated.

The cold read is taken on a bounded subset for the measured reason CLAUDE.md records: on a cold
cache the implementation embeds a whole session's turns inside one §4.6 ingest call, and some
LongMemEval sessions exceed the harness's §4.0.7 30-second deadline. Retrieval P95 is a per-query
property, so a bounded subset measures the same quantity with smaller n. **No quality number is read
from that pass**, and `--max-cases` refuses to combine with one.

### Standing checks, in the order they were run

| check | result |
|---|---|
| **`repro --runs 2`, cold, no cache** | **byte-identical** — `e796c12e…` twice |
| **`conformance`, BEFORE any quality number** | **REJECTED, 0 findings, `fail_no_time_dependence`** — the unchanged baseline for every session since B. The gate still abstains everywhere; ADR-016 is why, and it is not a retrieval-quality statement |
| **second implementation reproduces the first** | **PASS, EXACT** — binary **0.6725** = Session J's offline reconstruction **0.6725**, as Session H's 0.5764 = 0.5764 did |
| `cargo test --workspace` | **190 passing** (from 188; two new structural tests) |
| `cd eval && pytest` | **72** — `eval/` untouched |
| five determinism checks, **re-taken on the shipped graph** | **all PASS** — discrimination, determinism, batch invariance **0.000000**, padding invariance **0.000000**, torch-vs-ORT **0.000001** |
| Rust graph vs ONNX reference logits | **PASS** at 1e-3 on 8 fixture cases |
| ONNX graph optimization level pinned both sides | **PASS** — `ORT_ENABLE_BASIC` / `Level1` |
| every model pinned by sha256 | **PASS** |

### What changed in the code, and the two defaults that were deleted

`rerank.rs`: `MODEL_FILE` `model_int8.onnx` → `model.onnx`; both digests re-pinned; a named
`SupersededGraph` load error so a stale `--reranking` path reports **what happened** rather than
"file not found"; module docs rewritten because **the batch-1 rationale changed** — f32 *is*
batch-invariant, and batch 1 is now kept because invariance is a per-graph measurement a re-pin does
not inherit, not because the shipped graph fails it.

**Deliberately no table of accepted graphs.** A loader that accepts two graphs lets a target string
name one scorer and measure another.

Two defaults removed, both of the kind CLAUDE.md names:

1. **`score_longmemeval.py --reranking` defaulted to the int8 directory.** The moment the shipped
   graph moved, that default would have scored the **old** graph and written the result under the
   shipped label. Now required; the module-level `_reranking` initializer is `None` so a path that
   forgets to set it makes the binary refuse to start.
2. **`session_j_verify_export.py --out-dir` defaulted to `runs/session-j/`.** Re-running it in a
   later session silently **overwrote Session J's record of what Session J measured.** Now required.

---

## Part 2 — K1, amended. ADR-019.

Pinned in `ROADMAP.md` → "K1 — amended 2026-08-08" and brief §5.7.1. The proposal file is marked
**ADOPTED** with pointers rather than deleted.

**The threshold is not moved.** `0.95` is not lowered and no number in the original is relaxed. The
criterion's *shape* changes from a single point to a published curve, and a **new** kill condition is
added that did not exist before: **if the curve is flat — precision at 10% coverage not materially
above precision at 100% — the project is reconsidered.** An amendment that only widened a target
would be worthless. This one adds a way to fail.

**Condition 3 is binding, not advisory:** a configuration that injects at low precision to raise
coverage **fails outright**.

**And, in ADR-016's own terms: the 0.3739 ceiling never measured retrieval quality.** A perfect
retrieval system scores **0.8483** on the shipped gate against a 0.95 threshold, because
`fit_isotonic`'s smallest expressible block spans 100% of queries and the gate has no vocabulary for
confident subsets. **This invalidates no retrieval measurement** — R@1, R@5, R@10, conditional
accuracy, the oracle and every closed mechanism were measured against gold turns with the gate
uninvolved. It invalidates the interpretation of one number.

---

## Part 3 — the curve is published, and the head got worse while the body got better

Full table and the declared point: `docs/design/PRECISION-COVERAGE.md`. Artifact:
`crates/marlowe-memory/artifacts/precision-coverage-heldout-v1.json`.

> ### DECLARED OPERATING POINT — coverage **10.0%**, precision **0.9130** (21/23), CI **[0.7196, 0.9893]**, margin ≥ 1.1651

**The prediction was published before the measurement, and it held.** Session J measured
fine-tuning as helping the *body* of the ranking and stopping at the top decile, so the shipped
graph was expected to read **worse at the head** than the int8 configuration it replaces:

| at 10% coverage | superseded int8 | **shipped fine-tune** |
|---|---|---|
| precision | **0.9565** (22/23) | **0.9130** (21/23) |
| 95% CI | [0.7805, 0.9989] | [0.7196, 0.9893] |
| at 100% coverage | 0.5764 | **0.6725** |

**Confirmed.** One case of 23 flipped at the operating point, against +22 of 229 across the split.
The two are statistically indistinguishable at the head with overlapping intervals — **and that is
the finding.** +0.0961 R@1 bought nothing where the criterion reads.

**K1, original form: still not reached.** No coverage level clears 0.95 with its interval lower
bound above the threshold. Shipping a materially better model did not change that answer.

**K1, amended flatness kill: NOT met.** precision@10 `0.9130` vs precision@100 `0.6725`,
delta **+0.2405**, with ci_low@10 `0.7196` > `0.6725`. **The confidence signal carries real
information**, so the failure the criterion exists to catch is not present.

**The conformal reading reproduces Session J exactly** — τ = 1.4639 at α = 0.05, measured
`P(inject | wrong)` = **0.0133** against the 0.05 bound, precision 0.9333 (14/15) at 6.55% coverage.
Identical to Session J's offline read, through a code path that did not exist then. **The guarantee
and the precision are reported as separate quantities and never conflated:** the bound covers
`P(inject | wrong)`; K1 asks for `P(correct | injected)`, a selective risk it does not cover.

**Global τ only.** Largest wrong-query calibration set is 12, against a registered floor of 40. The
per-group n is published beside the refusal.

---

## A defect this session introduced and caught — tenth instance of the family

**The first draft of `publish_precision_coverage.py` measured a ranking that does not exist, and
nothing crashed.**

It joined gold through `score_longmemeval.read_scored` and re-implemented the shipped ordering
locally. `read_scored` **drops `survived_pruning` and `rerank_score`** — so every row's
`rerank_score` came back `None`, the ranker fell through to the *gate* order, and it produced a
complete, plausible, correctly-formatted precision/coverage curve. **It read R@1 = 0.5411 where the
binary reads 0.6725.** Its own population rule also disagreed, giving n = 245 and n = 231 against
the canonical 229.

**It was caught only by demanding an exact match against `analyze_cue_overlap.py`**, which is where
this project's binary-side R@1 has been read since Session C.

The fix is structural, not a corrected copy:

1. `order_of`, `gate_order`, `shipped_order`, `hit`, `read_dump` and `columns` are lifted to module
   scope in `analyze_cue_overlap.py` and **imported** by the publisher. **The refactor was verified
   to leave `cue-overlap.json` byte-identical** before anything was built on it.
2. The publisher **refuses to write** unless its held-out R@1 equals `cue-overlap.json`'s exactly.
   The check is enforced in code rather than remembered.

**Tenth instance of two-sides-silently-disagree**, and the first where the second implementation was
written *in the same session* as the check that caught it. `read_scored` and `read_dump` are two
readers of one dump with different column sets; that is the shape to watch for.

---

## Part 4 — what a later session inherits

1. **Head separability is the named lever, and it is not more R@1.** +0.0961 R@1 in the binary, and
   the operating point barely moved. See `PRECISION-COVERAGE.md`.
2. **The human label set is now drawable.** True injection precision has still never been computed.
3. **`MAX_SEQ_LEN` stays 256** and the 7.86% gold truncation stays a priced defect. ADR-017's
   closure was withdrawn on held-out; do not re-open without a relevance-fitted estimator.
4. **Do not re-quantize the shipped graph without re-measuring `[1, 256]`.** ADR-015's shape-binding
   is a property of int8 graphs, and the fine-tuned graph has never been measured that way.
