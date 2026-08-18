# Registered BEFORE the CUDA scoring run was started

Written and committed **before `score_longmemeval.py --embedder-provider cuda` was launched**, against
a baseline that already exists (`runs/session-e-maxseq/fit-1024/fit/`, session-level top-1 **0.9008**,
218/242, CPU, `MAX_SEQ_LEN` 1024). A prediction stated after seeing the result is a description.

The verdict rule below was fixed by the human in advance and is not mine to move after the fact.

---

## What is being asked, and it is NOT the tolerance

CUDA embeddings miss the HuggingFace reference by median **3.072e-5** / max **1.063e-4**, against a
`MAX_ABS_DIFF` of 1e-4 and a CPU reading of **1.043e-7** — roughly 500x further out across the whole
distribution. That fails the fixture and currently blocks defaulting the embedder to CUDA.

**Tolerance is not the question anyone cares about. The question is whether it changes a decision.**
This is the measurement ADR-029 took for the cross-encoder: it met the identical wall, declined to
widen the byte-identity gate, and **amended the requirement to ranking equivalence after measuring
it** — 0 of 229 slates reordered, 0 top-1 changes, R@1/R@5/R@10 identical. The same measurement, on
the embedder, is what this run is.

## What actually changes between the two runs

**Every vector in the store.** That is the difference from the `MAX_SEQ_LEN` comparison and it is
why the control has to be read the other way round. At 8192 → 1024 exactly **453 of 246,750 turns**
(0.18%) re-embedded and everything else was bit-identical; **206 candidate rows** moved their
`dense_cosine`. Here the provider changes, so every turn and every query re-embeds, and the cache
namespaces on `provider` (`CacheIdentity`), so none of the CPU vectors can be served under the CUDA
label.

What does **not** change: `lexical_bm25` and every lexical feature (BM25 reads text, not vectors);
the cross-encoder, which stays on CPU by default and scores text pairs, so an unchanged slate gets
an unchanged `rerank_score`; the frozen gate; `MAX_SEQ_LEN`; the split.

Magnitudes, derived rather than guessed. A per-component absolute difference of ~3e-5 on a 512-dim
unit vector gives `||Δ|| ≈ sqrt(512) · 3e-5 ≈ 6.8e-4`, hence `cos(CPU, CUDA) ≈ 1 − ||Δ||²/2 ≈
1 − 2.3e-7` — which is exactly the **0.99999970** min cosine already measured, so the arithmetic and
the measurement agree. A query-document cosine then moves by at most `||Δq|| + ||Δd||`, order
**1e-4 to 1e-3** worst case, typically far less. Fused scores and margins sit at 0.2–0.4, so a
decision flips only where two candidates are separated by less than that.

## The prediction

1. **Top-1 picks are identical, 242 / 242.** That is the central estimate, not a hedge. One
   discordant pair I would call noise-consistent and would still read as "below the decision
   threshold". **Three or more discordant pairs, or any one-sided pattern (all gains or all
   losses), falsifies "numerical noise" and means the provider difference is reaching decisions.**

2. **Session-level top-1 stays 0.9008 (218/242)**, following from 1.

3. **McNemar is non-significant**, and with so few discordant pairs it has almost no power — which
   is the point rather than a weakness. This is not a quality intervention and a significant result
   would mean something is wrong, not that CUDA is better.

4. **The control reads the OPPOSITE way to the `MAX_SEQ_LEN` run, and this is the prediction most
   likely to catch a vacuous result.** There I predicted a handful of rows moving; here I predict
   **> 99% of the 117,890 candidate rows change `dense_cosine`**, because every vector re-embeds.
   **If fewer than 90% of rows move, the run did not use CUDA and every number in it is vacuous** —
   the stale-binary / silent-fallback failure, which has already happened once tonight. `score`
   moves on essentially every row too, since `dense_z` is derived from the cosine.

5. **Candidate row counts are within a handful of 117,890.** Consolidation dedups at cosine 0.98;
   a ~1e-4 perturbation can only cross that threshold for a pair already sitting within 1e-4 of it.
   A difference of more than ~20 rows would need explaining, and "the vectors moved slightly" would
   not be the explanation.

## What would falsify the approach

Any of: three or more discordant top-1 pairs; a one-sided direction in which queries move; or a row
count materially different from the baseline. None of those is explainable by "every vector moved in
the seventh decimal place", and each would mean the provider is a different **scorer** in the sense
that matters rather than only in the sense the fixture measures.

## The verdict rule, fixed in advance by the human

> If top-1 picks are identical, the tolerance failure is numerical noise below the decision
> threshold and CUDA is safe to default. If picks move, report which and by how much and DO NOT
> default it. Either way do not widen `MAX_ABS_DIFF` and do not regenerate the fixture.

`MAX_ABS_DIFF` is untouched, `embedding-reference.json` is untouched, and this run cannot change
either — it reads them not at all.

## What this comparison is and is not

**Session-level top-1 computed from the fit dump**, not the published turn-level R@1, and not a
held-out read. None is spent here: the comparison that means something is baseline-vs-treatment on
this machine through the same code path, which is what `fit-1024/` exists for. Comparing against the
published 0.7555 from another day would be the carried-measurement error this project logs.

---

# The other three measurements, registered at the same time

## Ollama coexistence (task 2)

6. **`auto_sessions` already derives the width from live free memory** — it re-reads the device on
   every decision and requires a whole spare session of headroom — so I predict the answer to "is it
   derived from an idle reading" is **already no**, and the work is to *measure* it under
   coexistence rather than to build it. If that is wrong the code is what says so.

7. **With `llama-server` resident at ~11.5 GB of 16.4, `auto` opens 3 or fewer sessions and does not
   OOM.** ~4.8 GB free against a warmed per-session cost of ~600 MB, and the one-spare-session rule
   leaves real slack. **`--embedder-provider cuda` applies no budget at all** (its own `reason`
   string says so), so that arm is the one that can fail, and if it does, failing is correct — it is
   the refusal arm.

## Per-session footprint (task 4)

8. **No single session is anywhere near 4 GB, on host or device.** Predicted: host peak ~300–400 MB
   for one CPU session at `MAX_SEQ_LEN`, of which the `[8, N, N]` int64 ALiBi matrix is **64.0 MB**
   (`8 · 1024² · 8 = 67,108,864`); device roughly the graph plus that matrix plus a CUDA context,
   so several hundred MB, not gigabytes. The 4.9 GB device peak at 8 workers is ~612 MB/session and
   is consistent with that.

9. **Total scales roughly linearly in the worker count.** Non-linear growth would mean an allocation
   per *call* rather than per *session*, or at a length nobody asked for.

10. A caution I am registering against myself, because it was committed twice tonight: **the byte
    count 4,294,967,296 does not identify a tensor.** `1 × 8 heads × 8192² × 8 (int64)` and
    `2 batch × 8 heads × 8192² × 4 (f32)` give the identical total. Where I decompose a measured
    figure I will say whether the decomposition is unique, and where it is not I will say the match
    is consistent rather than confirming.
