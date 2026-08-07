# State

**Updated:** 2026-08-06 — M0b Session I complete. **NO CODE SHIPPED, deliberately.** R@1 stays
**0.5764**. Three findings, each of which changes what the next session does; the sweep was not run.
**Current milestone:** M0b — Sessions A–I complete.

## Next action

**Session J — R@1, resumed at Phase 2. Phase 0 and Phase 1 are BANKED; do not repeat them.**

Session I measured the ground and then had its scope narrowed. Everything below is already on disk
and must not be re-derived: the fit/held-out identity, the failure decomposition, the depth table,
8 rerankers pinned by revision AND sha256, the model gate with measured cost, and the truncation
reachability grid. `runs/session-i/RESULT.md` and `PREREGISTRATION.json`.

### Read every result against CONDITIONAL ACCURACY

`R@1 = input_recall × conditional_accuracy`, exactly. Held-out: **0.5764 = 0.9039 × 0.6377**. Only
conditional accuracy is what capacity, context or length normalization can move; input recall is set
by depth and pruning. **R@1 alone hides which factor moved.**

| what R@1 ≥ 0.80 demands, fit | depth 10 | depth 20 | depth 30 |
|---|---|---|---|
| input recall | 0.9214 | 0.9738 | **0.9825** (= the whole pruned pool) |
| conditional accuracy required | 0.8682 | 0.8215 | 0.8142 |

Conditional accuracy is **0.6730** today. The most favourable depth still asks for a **21% relative
improvement in discrimination**; depth 10 asks for 29%. A 0.72 outcome is the predicted range.

### The order for Session J, and why

**The capacity hypothesis was tested once and came back null with power** (arm 2 row below), so the
order below leads with normalization rather than with a bigger model.

1. **Arm 7 — length normalization of the rerank score. THE NAMED NEXT LEVER.** Promoted by Session
   I's central finding: the seq-256 cap is an accidental length normalizer, and the rank-1
   distractor on failures is 1.9× gold's length and 4× over-represented as assistant-authored.
   Normalize explicitly and the sequence length stops being load-bearing. This is also the only
   route by which raising sequence length ever becomes viable. **Measure it across at least two
   capacities:** the seq-512 penalty is −0.0917 on L-2 (p=0.0002) but −0.0088 on L-6 (p=0.73), so
   the length bias is substantially a weak-model artifact and normalization may interact with depth.
2. **Fine-tuning the cross-encoder on the fit split — now UNBLOCKED.** CUDA works (see corrections
   §3). 251 fit cases with gold labels is a real training set, and domain-adapting from web passages
   to conversational turns is the standard way to close exactly this gap. Not an LLM call at
   inference. Needs its own registration and a stricter held-out discipline than anything used so
   far.
3. **Capacity, on f32 only** — the ladder is fetched and gated. **bge-base and jina-v2 are ~7.6
   s/query at depth 20 and cannot ship on ADR-003's 1-vCPU target**; if either wins on quality, the
   cascade becomes the shipping question, not an optional arm.
4. **Depth {10, 20, 30}** — 20 captures 86% of the available input-recall headroom, 30 saturates.
5. **Context**, restricted to the reachable cells in `truncation-grid.json` — a per-neighbour cap of
   32–64 at seq 512. **Uncapped context is unreachable at every sequence length these models
   support** and would measure truncation.

### Arms, current status

| arm | status after Session I |
|---|---|
| **7 — structural features / length normalization** | **THE NAMED NEXT LEVER.** Promoted from optional by Session I's central finding. Not yet run. |
| **0 — sequence length** | **MEASURED AND CLOSED ON ITS OWN.** seq 512 is −0.0917 R@1, p=0.0002. Only viable alongside arm 7. See corrections §1. |
| **2 — capacity** | **ONE READ, AND IT IS A NULL WITH POWER.** L-6 f32 vs L-2 f32 at depth 10 seq 256: **+0.0131 R@1, discordant 27, exact p = 0.7011**, α attainable. Tripling depth is indistinguishable from noise. **Not closed** — says nothing about bge/jina/mxbai, which are fetched and gated — but the capacity hypothesis is downgraded and **arm 7 should outrank it**. Run on **f32 only**, corrections §2. |
| **3 — depth** | **UNMEASURED.** Saturates at 30; 20 captures 86% of the headroom. Table above. |
| **1 — context** | **UNMEASURED.** Reachable only with a per-neighbour cap of 32–64 at seq 512; `truncation-grid.json` has the cells. |
| **4 — cascade** | **CONDITIONAL, and it is the SHIPPING question** if a large model wins: bge-base and jina-v2 are ~7.6 s/query at depth 20. |
| **5 — ensemble** | **CONDITIONAL** on Spearman < 0.7 between architectures. Report ρ first. |
| **6 — per-query normalization** | **RECLASSIFIED, not deferred. It CANNOT move R@1** — a strictly increasing within-query transform against a within-query ordering read, i.e. an identity, the same defect as ADR-011 and ADR-013. It belongs to the coverage curve, where the decision is cross-query. **Do not register an R@1 band on it.** |

### The named alternative to isotonic recalibration, for the GATE REFIT session

**Conformal risk control on the top1−top2 rerank logit margin.** Not a Session I arm — Session I's
job is to make the precision-at-coverage curve readable, and adopting an injection rule is the gate
refit's decision. Recorded here so the refit session does not rediscover it.

The mechanism: nonconformity score = the rerank logit gap between rank 1 and rank 2; on a
calibration set take the `(1−α)(1+1/n)` quantile as τ; at test time inject rank 1 only if its margin
≥ τ, else abstain. Distribution-free, finite-sample bound on the false-injection rate, no fitted
curve and no pooling across queries. **It targets exactly what Session D measured** — isotonic
regression over pooled margins collapsing to a step function with no resolution at the head, which
is where the operating point reads — and it is Session E's confirmed diagnosis (query-local beats
pooled) applied to the gate rather than to the features. §5.5 is precision-first and K1 carries no
coverage term, so ≥0.95 precision on a confident subset satisfies it as written.

**Falsifiable in an afternoon, offline:** compute (top1 − top2) on fit, plot precision against
coverage, check threshold stability across the fit/held-out boundary. If no coverage level reaches
0.95 precision, the method is closed cheaply.

**Two cautions, both load-bearing.** The source research report's performance projections
(0.5764 → 0.685 → 0.735 → 0.785 → 0.835) are **chained assumptions, not measurements** — each step
an assumed lift on the previous, and several of its citations could not be verified. This project
has watched additive projections fail six times. **Take the mechanism; do not take the numbers.**
And see the group-conditional warning under Known issues: global τ first.

**A structural note this session proved:** per-query normalization of rerank scores **cannot move
R@1**, because it is a strictly increasing transform within a query and R@1 is a within-query
ordering read. It is an identity, like Session H's arm 1. It matters only for cross-query decisions
— which is exactly the coverage curve. Do not register an R@1 band on it.

### Reporting

- **The frontier: R@1 against cost for every configuration**, not a single best number.
- **Input recall for every configuration**, since it caps R@1.
- If a configuration reaches **0.80**, name it and its cost.
- **If nothing reaches 0.80, the decomposition of what still fails is the deliverable**, in the
  same way Session G's 19:1 was.

### Registration requirements

- **ADR-014, binding:** state the minimum discordant count at which your α is attainable, and
  confirm the arms disagree that often **on the exact contrast the test consumes**, not a proxy.
  Session H's registered α was unreachable at any outcome.
- **ADR-010:** verify each arm can move R@1 before registering a band.
- **ADR-013:** verify each read can vary.
- **A guard whose primary read directly measures the guard's concern is subordinate to that read**,
  not an independent stop (ADR-014 corollary).

**Still standing:** do not scope cues 3–5; do not lower the threshold; do not re-tune the
calibration resolution; do not re-attempt consolidation, PRF or entity expansion, HyDE, or session
pruning as a quality mechanism; do not attack arbitration over the full pool. **Do not refit the
gate in this session** — it is a different number and would confound the R@1 read.

## Session H — the numbers

Full write-up in `runs/session-h/RESULT.md`. Pre-registration at `ab80870`. **ADR-014.**

| | before | after |
|---|---|---|
| R@1 | 0.5348 | **0.5764** |
| R@5 | 0.8130 | **0.8428** |
| R@10 | 0.8826 | **0.9039** |
| oracle R@1 | 0.6435 | 0.6463 — **pinned, not a measurement** |
| ceiling | 0.3739 | 0.3739 — **pinned, not a measurement** |
| retrieval P95 | 33 ms cold subset | **149 ms** warm, full split, passes 300 ms |

Shipped ranker **0.5764** against best single cue **0.5415**: **+0.0349**. Sessions D, E and F each
shipped a fusion that did not clear that bar. **At top-10 the shipped ranker is BELOW dense alone**
(0.9039 vs 0.9170) — it is a top-1 mechanism reordering ten candidates, and that is a caution about
reading its R@10.

**The registered question FAILS both sub-questions.** Q1 +0.0131, Q2 +0.0044 against +0.05. Floor
met in both. **The reranker gains +0.0393 over the gate whether or not pruning ran**; Q1 and Q2
differ on 3 and 1 cases of 229. **Session pruning is closed as a quality mechanism** and survives
only as a cost mechanism. Session G's 19:1 decomposition was a true description of *where* errors
are and a false lead about *what fixes them*.

### The K1-relevant number

**The reranker is provably NOT capped by the either-cue oracle.** Presence ceiling **0.9825**
against the 0.6435 cap, measured on fit before building, per ADR-010. It is free to reach ~0.98 and
reads 0.5764 against a held-out oracle of 0.6463.

> **The bound looks like a property of the task, not of the combiner.** Sessions D and E were capped
> *by their shape*. This one is not, and performs in the same neighbourhood anyway.

### ADR-014's binding lesson — verify the CONTRAST can vary

**The registered α was unreachable.** Exact McNemar is a binomial over discordant pairs; minimum
attainable p is `2/2^n` — 0.25 at n=3, 1.0 at n=1. Q1 had 3 discordant pairs, Q2 had 1. `p < 0.05`
was not attainable at any outcome. **The significance half of both verdicts is uninformative by
construction and must not be quoted as evidence of absence.** The delta half is sound and carries
the conclusion. `runs/session-h/POWER-DEFECT.md`.

The ADR-013 instrument check **passed and measured the wrong contrast** —
reranked-vs-the-ranking-it-replaces, where the test consumes reranked-pruned-vs-reranked-unpruned.

> **Binding: a pre-registration using a paired test MUST state the minimum discordant count at which
> its α is attainable, and its instrument check MUST confirm the arms disagree that often, on the
> exact contrast rather than a proxy.**

Third member of one family, each arriving a level deeper: ADR-011 the mechanism could not move the
metric; ADR-013 the read could not vary; ADR-014 the contrast could not reach significance.

### The sessionizer failed its registered guard and the session proceeded deliberately

Pool inflation **1.546×** against ≤1.5×. `runs/session-h/BAND-FAILURE-ARGUMENT.md`, written before
the reranker was built. **The band was not edited.** The argument is *not* that the miss was small:
the guard is a proxy for gold damage, and the quantity it proxies for was measured directly and is
exactly zero — gold retention Δ +0.0000, completeness 1.0000, zero gold sessions split. **Do not
inherit "proceeded past a failed band because it was close" — that is not what happened.**

## Built

**M0b Session H** — first change to the scored retrieval path since C. **188 tests passing** (from
175), `eval/` unchanged at **72**.

`retrieve.rs`: `session_keys`, `surviving_sessions`, pruning after `features::extract_all`, two new
ranking levels above the untouched three. `rerank.rs`: L-2-int8 via `ort`, digests pinned at load,
**batch 1 structurally**, provider required to register via `error_on_failure()`. `occurred_at_ms`
on the payload and entry, `DERIVATION_VERSION` 1 → 2. `--reranking` required with an explicit value.
New in `tools/`: `session_h_pools.py`, `preregister_session_h.py`, `reach_session_h_pruning.py`,
`reach_rerank_fit.py`, `answer_registered_question.py`, `make_cross_encoder_fixtures.py`.

**Earlier sessions:** A (workspace, contracts, journal, memory) · B (lexical cue, frozen gate) ·
C (dense cue) · D (max fusion, **failed floor**, ADR-010) · E (per-query features, **failed floor**,
ADR-011) · F (consolidation, **null**, ADR-012) · G (query side measured, ADR-013).

## Standing checks — re-run on every cue, feature or pool change

- **Offline reachability work must pass a reconstruction fidelity gate first.**
- **A second implementation of a scored-path component must reproduce the first.** Session H: binary
  0.5764 = offline reconstruction 0.5764, exactly.
- **Pin the ONNX graph optimization level on both sides.** `ort` uses `Level1`; Python defaults to
  `ORT_ENABLE_ALL`, and they fuse the int8 graph differently — **logits 0.0699 apart on identical
  token ids**, nearly twice the batch-invariance failure that blocked adoption in Session G.
  **Seventh instance of the silent-disagreement pattern.**
- **The artifact the driver reads must be the artifact the run scored with.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue.
- **The unchanged-cue check is a NULL INSTRUMENT for a pruning change** — it reads exactly the three
  quantities the partition-independent max-aggregation identity pins. Its silence is not evidence.
- **`repro --runs 2`, WITHOUT a cache.** Run it *early*. Also catches a batch-invariance regression.
- **The embedding cache's byte-identity test.**
- **`cargo test --workspace` (188) and `cd eval && python -m pytest` (72).**

## Open gaps — each with a named closing condition

### §4.3 maturation has no contract-level coverage
**Closing condition: the gate begins injecting.** It still does not: max calibrated precision
**0.3739** against a 0.95 threshold. Conformance run first, REJECTED with 0 findings, as
pre-registered. **The gate refit is the only named path to closing this, and it is not Session I.**

### The exported ONNX weights are not independently validated against the published model
**Closing condition: a maintained load path for `jina-embeddings-v2-small-en` outside
`transformers.onnx`, or an alternative authority.** Unchanged. The cross-encoder is a
maintainer-published Xenova export pinned by sha256 — **any reranker adopted in Session I must meet
the same bar, or it creates a second instance of this gap.**

## Corrections to earlier sessions, measured in Session I

Recorded here rather than only in `runs/session-i/`, because a later session inherits this file and
would otherwise inherit the superseded claim.

**1. The shipped reranker truncates gold in 1 case in 13 — AND RAISING THE SEQUENCE LENGTH IS A
MEASURED REGRESSION. Both halves of this are binding.**

`rerank.rs` pins `MAX_SEQ_LEN = 256`. On fit, query + gold turn fits in 256 in only **211/229 =
0.9214** of cases; gold p95 is 270 word pieces and its maximum is 681 against a ~237 document
budget. **R@1 0.5764 was measured on a configuration that scores 7.86% of gold turns on a
fragment.** The defect is real and is NOT closed.

**The obvious fix was tried and it costs −0.0917 R@1.** L-2 **f32**, depth 10, window 0, fit,
everything but sequence length identical:

| | R@1 | conditional accuracy |
|---|---|---|
| seq 256 | 0.5983 | 0.6493 |
| seq 512 | 0.5066 | 0.5498 |

Discordant 31 (5 gained, 26 lost), exact McNemar **p = 0.0002, α attainable** — this significance
statement carries information, unlike Session H's.

**The mechanism, which is what a later session must inherit.** The rank-1 distractor on failures
goes from 50.0% assistant-authored at 157 median word pieces (seq 256) to **74.3% at 487** (seq 512),
against gold that is 87.7% user-authored at a median of 70. **Truncation at 256 was SUPPRESSING the
length bias, not manufacturing it.** The cap is doing two opposing jobs — it costs the 7.86% of gold
that does not fit, and earns more back by capping how much score a long distractor can accumulate.
**Removing the cap removes the normalization.**

> **Do not raise the sequence length again on its own.** It is only viable alongside **explicit
> length normalization of the rerank score** — arm 7, structural features, now **promoted from
> deferred to the named next lever for R@1**.

**The two 0.9214 readings are independent; the match is arithmetic coincidence** — checked, not
assumed. Gold-in-slate and gold-fits-in-256 are *different* sets of 211: 194 overlap, 17 exclusive
to each, 1 in neither. P(A∧B) = 0.8472 against an independence prediction of 0.8490. **The joint
figure is the real headroom: only 0.8472 of cases have gold both in the slate and untruncated.**

**2. QUANTIZATION, NOT ARCHITECTURE — and it fails in a second dimension. `[1, 256]` is
load-bearing on the shipped int8 graph exactly as batch = 1 is.**

All eight f32 graphs are batch-invariant to **0.000000**; only int8 L-2 fails, at 0.0958. This file
previously read as though batching were unsafe for cross-encoders generally. It is not.

**Session I found the same artifact in the sequence dimension.** With identical token ids, stripped
of padding and re-padded to a longer tensor — content bit-identical, only the shape different:

| padding-only, 600 pairs | median \|Δlogit\| | p95 | max | **top-1 flips from padding alone** |
|---|---|---|---|---|
| L-2 **int8** | 0.010904 | 0.046044 | 0.417379 | **9/60 = 15%** |
| L-2 **f32** | 0.000000 | 0.000000 | 0.000000 | **0/60** |

**STANDING CHECK: any sweep that varies sequence length runs f32, or its cells are different
scorers.** The first read of the truncation contrast was taken on int8 and is VOID for that reason.
**int8 and f32 both landing on −0.0917 is coincidence and is not corroboration** — both lost a net
21 of 229, but the discordance differs (27 vs 31). Eighth instance of two-sides-silently-disagree.

**3. CUDA IS FIXED. Nothing was missing and no download is required.**

Driver 610.74 / CUDA UMD 13.3, RTX 4080 SUPER, **no CUDA Toolkit installed and none needed**.
`torch 2.5.1+cu121` already bundles what ORT 1.24 requires in `site-packages/torch/lib`:
`cublas64_12.dll`, `cublasLt64_12.dll`, `cudnn64_9.dll`, `cudart64_12.dll`. They were simply not on
ORT's DLL search path. The exact fix, so a fresh environment reproduces it:

```python
import os
os.add_dll_directory(os.path.join(os.path.dirname(__import__("torch").__file__), "lib"))
import onnxruntime as ort            # AFTER add_dll_directory, never before
sess = ort.InferenceSession(model, opts, providers=["CUDAExecutionProvider"])
assert "CUDAExecutionProvider" in sess.get_providers()   # asserted, never assumed
```

Verified: `['CUDAExecutionProvider', 'CPUExecutionProvider']`, forward pass returns a finite logit.

**Clean up first:** `onnxruntime` 1.23.2 **and** `onnxruntime-gpu` 1.24.2 are both installed into
the same package directory; 1.24.2 currently wins. Uninstall the CPU package.

**The determinism boundary was NOT crossed and stands for whoever uses this:** GPU for offline
fit-split selection only; the published held-out number is taken on CPU, single-threaded;
GPU-vs-CPU ranking agreement verified before any GPU cell is trusted. **GPU is not adopted for
shipped inference** — that needs its own ADR covering determinism and the VPS target.
**This unblocks fine-tuning, which is now the strongest remaining lever.**

**3. Depth is not merely "not closed" — it SATURATES AT 30, and Session H's read was L-2-specific.**
Input recall by gate-key rank, fit split: depth 10 **0.9214**, depth 20 **0.9738**, depth 30
**0.9825**, depth 50 and 100 also 0.9825 — depth 30 *is* the whole pruned pool. Depth 20 captures
86% of the available headroom. Session H's "reranking ~50 scores the same as 10" was reranking ~30
effective candidates with a model too weak to exploit them: depth handed L-2 +0.0611 of input
recall and L-2 returned −0.0374 of conditional accuracy. **Session pruning remains closed as a
quality mechanism; that is a different claim and is unaffected.**

**4. The failure mode is only 58% same-session.** Any brief describing it as same-session
discrimination is wrong by that margin — on fit-split failures the rank-1 distractor shares gold's
true session 58.0% of the time and its derived session 59.4%. (`docs/RESEARCH-BRIEF-retrieval.md`
is named as carrying this framing and is **not in this repository**; the correction has to be
applied wherever it actually lives.)

## Known issues

- **Read Session I against CONDITIONAL ACCURACY, not R@1 alone.** R@1 factors exactly into
  `input_recall × conditional_accuracy`. Held-out: 0.5764 = 0.9039 × 0.6377. Only the second factor
  is what capacity or context can move, and R@1 alone hides which one did.
- **The fit/held-out gap is CASE MIX and the issue is closed.** Both halves reproduce through one
  function to +0.0000 — held-out 0.5764 against the binary, fit 0.6201 against Session H's offline
  tool. 81% of the gap is conditional accuracy (+0.0353 of +0.0437), not slate quality.
- **Per-category reads are unstable across the split and this is a finding AGAINST
  group-conditional conformal, not a caveat on it.** `multi-session` conditional accuracy is 0.7222
  fit / 0.5690 held-out; `single-session-preference` is 0.3077 / 0.5000 at n=15 per half. A
  group-conditional τ would be calibrated on 15–61 cases and the finite-sample conformal bound
  degrades as 1/n per group. **Global τ first. Group-conditional only where a group has the n to
  support it**, and the per-group n reported beside any threshold.
- **Turn-pair chunking is untested and is a candidate for any session that touches ingest** —
  indexing a user question with its assistant answer as one unit rather than as separate turns.
  Cheap, mechanically sensible, and it addresses fragment boundaries directly. More interesting
  than it looks: 87.7% of gold is user-authored, while the distractors that beat it are 47.1%
  assistant-authored and 1.9× longer at the median.
- **Do not quote Session H's McNemar p-values.** The test had no power; see ADR-014.
- **Session pruning is closed as a QUALITY mechanism.** It remains a cost mechanism.
- **The fit/held-out gap on a parameter-free component is unexplained.** Fit split read 0.6245,
  held-out 0.5764. The cross-encoder is pre-trained and applied as-is, so there is little to overfit
  — most likely case mix, but a 5-point gap on a component with no fitted parameters warrants a
  check that the two pipelines are identical. **Session I should confirm rather than assume.**
- **CUDA fails to load** — listed by `get_available_providers()`, missing cuBLAS/cuDNN, silently
  fell back to CPU in Session G. Providers are now asserted after construction. **This blocks the
  fine-tuning lever named above.**
- **The additivity read's subsumption rule is defective as registered.** Fix before reusing.
- **Consolidation's retrieval effect is untested at realistic duplicate density.**
- **Trust propagation through a derived belief is STILL unexercised.**
- **The 230 → 229 denominator change must not be ignored in any cross-session comparison.**
- **Every poisoning ASR is 0.000 and VACUOUS.** K3 is the exception and still meaningful.
- **The maturation window is 6h and under tuning pressure. Do not adjust it to make a suite green.**
- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token).
- **`considered` costs a full-store scan per query.** ADR-003's live-only hot index removes it.
- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run **`cleaned`**.
- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.**
- **The headline metric has never been produced.** No human label set exists.
- **The permission layer has no kernel backstop (ADR-002, revised).**
- **M1's §B9 suite must run on both native Windows Terminal and a Linux terminal emulator.**

## Open questions for the human

1. **The K1 conversation, sharpened by Session H into a specific claim.** Four sessions attacked
   arbitration and were capped by the 0.6435 either-cue oracle *because of their shape*. Session H
   shipped a mechanism **provably not capped** — presence ceiling 0.9825 — and it reads 0.5764
   against an oracle of 0.6463. **If the bound is a property of the task rather than the combiner,
   more arbitration work is not the answer**, and the remaining named levers are reranker quality
   (Session I), the gate refit, and the answer stage.

   Comparable numbers: **R@1 0.576, R@5 0.843, R@10 0.904** against oracles of 0.646 / 0.891 / 0.948.
   Injection precision is still 0.3739 against a frozen 0.95. QA accuracy still unmeasured.

2. **The M0a human label set is your deliverable.** ≥400 judged injections, ≥50 per category, judge
   blinded. **Still not drawable at this operating point.**

3. **QA accuracy needs an API credential.** A key and a small HTTP client in `tools/` — a
   credential, not a design question. Offline measurement over retrieval output only; an answer
   stage on the measured path is milestone drift.

4. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*