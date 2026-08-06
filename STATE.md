# State

**Updated:** 2026-08-06 — M0b Session G complete. **The query side is measured and three of four
named mechanisms are closed. The problem has moved: it is ranking inside a correct session.**
**Current milestone:** M0b — Sessions A–G complete. Session H is scoped below.

## Next action

**Session H — measure in-session reranking, then QA accuracy.**

Session G's failure decomposition is the reframe. At N=3 session pruning, the residual splits
**4 wrong-session against 77 right-session-wrong-rank — 19.2 to 1**. Selecting which of ~48
sessions holds the answer is close to solved. What is not solved is ranking inside a correct
**~47-turn** session.

Sessions D, E and F attacked arbitration over a **~487-turn** pool. That is what carries the 0.6435
either-cue oracle cap. **Ranking 47 topically coherent turns is a different problem and is not known
to carry the same bound.** Session G did not measure it.

**The pass condition is already registered**, before any result exists, in
`runs/session-g/REGISTERED-QUESTION-in-session-rerank.json`. Read it first; do not restate or move
it. Two sub-questions, both paired McNemar at α=0.05:

1. **Q1, quality:** rerank all ~50 candidates in the N=3 pruned pool vs all ~487 unpruned.
2. **Q2, equal cost:** at a fixed budget of **10** reranked pairs, does drawing them from the pruned
   pool beat drawing them from the unpruned pool?

Both pass at **Δ ≥ +0.05, p < 0.05**, and both carry an absolute floor: **reranked top-1 > 0.5415**,
the best single cue. A reranker that does not beat BM25 alone is not a reranker.

**A better session scorer is worth approximately nothing — four cases. Do not build one.**

**Second deliverable: QA accuracy**, dropped from Session G for lack of credentials and rolled here.
It needs an API key and a small HTTP client in `tools/` — a credential, not a design question.
Build it in `tools/` as an offline measurement over retrieval output; **ROADMAP M0b is exercised
through the eval harness only**, and an answer stage on the measured path is milestone drift.
**Registered in advance: a strong QA number does not satisfy K1 and a weak one does not refute the
design.** Report it with its answer model named — Mastra moved 84.23 → 94.87 on model alone.

**Still standing:** do not scope cues 3–5; do not lower the threshold; do not re-tune the calibration
resolution; do not re-attempt consolidation without a fresh pre-registration; do not attack
arbitration over the full pool again.

## Session G — what closed, and what the numbers were

Full write-up in `runs/session-g/RESULT.md`. Pre-registration committed at `db114e8`, before any pool
was reconstructed. **ADR-013.** Nothing shipped: no gate refit, no artifact minted, binary untouched.

| arm | verdict | number |
|---|---|---|
| 1 · session pruning | **oracle read VACUOUS**; value is pool reduction | 10.3% pool, 98.25% gold retention at N=3 |
| 2 · PRF + entity expansion | **HARMFUL**, both configs | −0.2358 / −0.1179, p < 0.001 |
| 3 · hypothetical answer embedding | **PREMISE REFUTED** | answer-for-question **−0.2227**; realizable +0.0218 at p=0.27 |
| 4 · temporal anchoring | **NOT REACHED**; the corpus explains it | **1 of 59** temporal questions carries a window |
| combined (1 + 3) | sub-additive as registered | +0.0044; rewrite alone nets +5 cases, combined +1 |

**Arm 3's premise is refuted, not merely unsupported.** The brief specified embedding a plausible
answer *rather than* the question. Embedding the **released gold answer** instead of the question
costs **−0.2227**. Answers do not resemble the searched turns better than questions do. The gain
appears only when the answer *augments* the question (+0.0917) — query augmentation, gold-label
upper bound, unattainable because it requires knowing the answer.

**Arm 4 is closed only as a retrieval-side hard constraint on this corpus.** LongMemEval's temporal
questions are interval arithmetic over two named **events**, not queries over a **window**. Mastra's
three-date structure does its work at the **answer stage**. That remains open and untested.

### The cross-encoder is fast enough and not deterministic

| model | 1 thread P95 | 16 thread | truncation | bar (240 ms) | batch determinism |
|---|---|---|---|---|---|
| L-6 int8 | 273.47 ms | 121.18 ms | 0.4050 | ✗ | **FAIL** (0.050) |
| **L-2 int8** | **92.41 ms** | 45.36 ms | 0.4050 | **✓** | **FAIL** (0.037) |

**L-2-int8 clears the latency bar with 147 ms to spare and is NOT ADOPTED**, on two independently
registered grounds: batch invariance fails for int8 where the spike's fp32 L-6 passed at exactly
0.000e+00, and arm 1's shortlist-equivalence condition failed at every N and every ranker
(oracle R@10 0.9563 against a required 0.9769). **Determinism is re-verified per graph, never
inherited across a quantization or model change.**

**No GPU number exists.** `get_available_providers()` listed CUDA, it failed to load on missing
cuBLAS/cuDNN, and ORT fell back to CPU silently — producing a "CUDA" figure within 1% of the
1-thread CPU one. Providers are now asserted against `get_providers()` after construction.
**Sixth instance of the two-sides-silently-disagree pattern**, first in a hardware binding.

### The pre-registration lesson — ADR-013, and it is binding

Arm 1's registered primary read was **vacuous**: `oracle@1` returned +0.0000 at every N in both
modes because under max aggregation a session's score *is* its best turn's score, so pruning cannot
displace the top-1 turn. Proven, not argued — **458/458 case-cue pairs, zero violations**.

The registration did the ADR-010 reach check correctly: it verified the **shape** can move the
metric. It did not verify the **read** can vary.

> **Check that the READ can vary, not only that the SHAPE can move the metric.** Different
> questions; only the first has been asked so far.

Second miss: the registration fixed N and every read but **not the session scoring rule**. Three
variants were declared before running and all reported; the best is **not quotable** as the arm's
result. A registration that fixes bands but leaves a free hyperparameter has not fixed the
experiment.

## Built

**M0b Session G** — measurement only, **zero implementation change**. **175 tests passing**,
`eval/` unchanged and still printing **72**.

New in `tools/`: `preregister_session_g.py`, `preregister_in_session_rerank.py`, `reach_pools.py`,
`reach_embed.py`, `reach_lexical.py`, `reach_arm1_pruning.py`, `reach_arm4_temporal.py`,
`reach_arm23_query.py`, `reach_additivity.py`, `reach_cross_encoder.py`.

**Earlier sessions:** A (workspace, contracts, journal, memory) · B (lexical cue, frozen gate) ·
C (dense cue, jina-v2-small) · D (max fusion, **failed floor**, ADR-010) · E (per-query features,
**failed floor**, ADR-011) · F (consolidation, **null**, ADR-012). See git history and
`runs/session-*/RESULT.md`.

## Standing checks — re-run on every cue, feature or pool change

- **Offline reachability work must pass a reconstruction fidelity gate first.** Session G's rebuilt
  pools reproduce Session F's published held-out top-1 exactly (0.5415 / 0.4454 / 0.6463) before any
  arm number is quoted. A delta against a wrong baseline looks exactly like a result.
- **A second implementation of a scored-path component must reproduce the first on unmodified
  input.** Session G's Python query embedder matches Rust's cached vectors to **7.45e-08**
  elementwise; Python BM25 reproduces the stored column at Spearman **1.000000**. Where Rust's own
  cache holds a vector, **do not recompute it** — the smaller the second implementation, the less
  there is to disagree.
- **The artifact the driver reads must be the artifact the run scored with.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue, read
  against the sweep of the feature the curve was **fit on** (margin, not raw).
- **The unchanged-cue check.** Registered as **will not fire** in Session G — no implementation
  change shipped. It must be pre-registered to fire in any session that changes the pool.
- **`repro --runs 2`, WITHOUT an embedding cache.** Run it *early*.
- **The embedding cache's byte-identity test.**
- **`cargo test --workspace` and `cd eval && python -m pytest` printing 72 unchanged.**

## Open gaps — each with a named closing condition

### §4.3 maturation has no contract-level coverage
**Closing condition: the gate begins injecting.** Clock probe fails `no_time_dependence`;
conformance REJECTED with 0 section-4 findings. Both are consequences of the empty injected set and
the probe is **correct** to fail. **When the gate starts injecting, re-run `conformance` FIRST.**

### The exported ONNX weights are not independently validated against the published model
**Closing condition: a maintained load path for `jinaai/jina-embeddings-v2-small-en` that does not
go through `transformers.onnx`, or an alternative authority for the same weights.** **Do not close
this by regenerating the fixture from Rust.** Session G did not create a second instance — both
cross-encoders are maintainer-published Xenova exports, pinned by sha256 in
`runs/session-g/cross-encoder-recost.json`.

## Known issues

- **Every Session G number is HELD-OUT and is therefore headroom, not validation.** Anything
  promoted from it must have its band re-derived on the **fit** split before being built. Quoting a
  Session G figure in Session H as evidence a shipped mechanism generalizes would be the same
  measurement on the same cases. Disclosed in the pre-registration, not discovered after.
- **The additivity read's subsumption rule is defective as registered.** It declares "A subsumes B"
  when B recovers ≤2 cases A does not, with no precondition that A recover anything. Arm 1 recovers
  **zero** cases, so every pairwise verdict involving it fires trivially. Those rows in
  `additivity.json` mean nothing. Fix the rule before reusing it.
- **Consolidation's retrieval effect is untested at realistic duplicate density.**
- **Trust propagation through a derived belief is STILL unexercised.**
- **The 230 → 229 denominator change must not be ignored in any cross-session comparison.** Session
  G's arms are all **paired within one reconstruction** at n=229, which sidesteps it; the raw 229
  figures (oracle 0.6463) are **not** comparable to Session E's re-based 0.6435.
- **Retrieval P95 is 33 ms COLD on a 40-case SUBSET, and the subset is forced.**
- **Every poisoning ASR is 0.000 and VACUOUS. Do not quote it as a security result.** **K3 is the
  exception and still meaningful: unsigned-write ASR 0.000, 4/4 visibly rejected.**
- **The maturation window is 6h and is under tuning pressure. Do not adjust it to make a suite go
  green.**
- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token).
- **`considered` costs a full-store scan per query.** ADR-003's physical live-only hot index removes
  it. Session-level pruning would reduce it further as a side effect, not as its purpose.
- **Retrieval is scoped to the request's `session_id`** — a scope filter, not a relevance judgment.
  Session boundaries inside a haystack are still unused **in the binary**; Session G measured them
  offline only.
- **`--suite poisoning` writes an empty `run.jsonl`**; **`timing_tainted` is not wired into
  `report.json`**. Harness observations, **not** things to fix in `eval/`.
- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run the **`cleaned`**
  variant; comparison against a published number is invalid unless that number states its variant.
- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.**
- **The headline metric has never been produced.** No human label set exists, so every run reports
  `injection_precision_human: null`.
- **The permission layer has no kernel backstop (ADR-002, revised).**
- **M1's §B9 suite must run on both native Windows Terminal and a Linux terminal emulator.**

## Open questions for the human

1. **The K1 conversation — live, and Session G sharpened it rather than answering it.**
   Four structural fixes moved the ceiling 0.309 → 0.374 against a frozen 0.95, and the two-cue
   top-1 oracle is 0.65 over the **full pool**. Session G's contribution is that **the full pool may
   be the wrong denominator**: the 19:1 decomposition says the live problem is ranking ~47 in-session
   turns, and the 0.65 cap was measured over ~487. Session H measures whether that changes anything.

   External framing unchanged: **no published system reports injection precision at all**, the
   closest independent work on admission thresholds tops out near 0.58, and every system reaching
   90%+ spends materially more than 300 ms. **L-2-int8 now measures at 92 ms for 10 pairs**, so the
   budget objection to a reranker is weaker than it was — determinism, not latency, is what blocks
   it. The question remains *"is 0.95 the right bar"* and *"is 300 ms the right budget"*, and 300 ms
   exists for voice, which is M7.

   Comparable numbers: **R@5 0.813 fused / 0.831 dense / 0.839 RRF against an 0.887 oracle; R@10
   0.883 against 0.944.** QA accuracy still unmeasured; Session H measures it.

2. **The M0a human label set is your deliverable, not the agent's.** ≥400 judged injections, ≥50 per
   category, judge blinded. **Still not drawable at this operating point.**

3. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
