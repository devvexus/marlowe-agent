# M0c Session M — the GPU budget is not the constraint, and nine rerankers say so

**Pre-registration committed at `4373111`, before any pool was reconstructed.** Every band and
prediction below was fixed in that file first. **Nothing shipped**: no artifact minted, no gate
refit, `crates/` unchanged apart from nothing at all.

---

## The answer, in one table

Fit split, n = 229, CUDA batched, RTX 4080 SUPER, seq 256.

| model | params | depth | R@1 | R@1_cur | input recall | cond. acc | ms p50 | tier |
|---|---|---|---|---|---|---|---|---|
| **L-2-ft-session-j** *(shipped)* | 16M | 10 | **0.7555** | 0.6987 | 0.9214 | 0.8200 | **7.0** | A |
| L-2-ft-session-j | 16M | 20 | 0.7686 | 0.7074 | 0.9738 | 0.7893 | 14.2 | A |
| L-2-ft-session-j | 16M | 30 | 0.7686 | 0.7074 | 0.9825 | 0.7823 | 21.8 | A |
| L-6-ft-session-j | 23M | 10 | 0.7467 | 0.6856 | 0.9214 | 0.8104 | 10.4 | A |
| L-6-ft-session-j | 23M | 20 | 0.7642 | 0.7031 | 0.9738 | 0.7848 | 23.1 | A |
| **L-6-ft-session-j** | 23M | **30** | **0.7729** | **0.7118** | 0.9825 | 0.7866 | **37.1** | **A** |
| L-12-v2 | 33M | 30 | 0.6332 | 0.5677 | 0.9825 | 0.6445 | 64.2 | A |
| bge-reranker-base | **278M** | 20 | 0.6114 | 0.5721 | 0.9738 | 0.6279 | 75.1 | B |
| bge-reranker-base | **278M** | 30 | 0.6070 | 0.5677 | 0.9825 | 0.6178 | 116.4 | B |
| mxbai-rerank-base-v1 | 184M | 30 | 0.5983 | 0.5371 | 0.9825 | 0.6089 | 203.7 | B |
| jina-v2-base-multilingual | **278M** | 30 | 0.4891 | 0.4629 | 0.9825 | 0.4978 | 131.2 | B |

Full 30-cell grid in `frontier.json`.

**Best cell: `ms-marco-MiniLM-L-6-v2-ft-session-j` at depth 30 — R@1 0.7729, +0.0174 over shipped.**

---

## THE VERDICT: the floor is not cleared, and nothing is promoted

The registered promotion floor is **+0.02** over the shipped fit R@1 of 0.7555. The best cell
delivers **+0.0174**. **It does not clear, so by the registration nothing ships and the held-out
split was not touched.**

The floor was M0c Session A's, reused verbatim rather than invented here, precisely so it could not
be chosen to fit. **It is not moved.** The argument for reading it generously is recorded below and
is a decision for the human, not for this session.

**The direct precedent for holding the line:** M0c Session A's slate arm measured **+0.0087 on fit
and −0.0044 on held-out**. A fit gain of this magnitude has already flipped sign once in this
project, one session ago, on this corpus.

---

## The finding: capacity is refuted across a 17× parameter range

| | R@1 @ d10 |
|---|---|
| L-2 **fine-tuned**, 16M | **0.7555** |
| L-12, 33M | 0.6201 |
| L-2 un-tuned, 16M | 0.5983 |
| bge-reranker-base, **278M** | 0.5895 |
| mxbai-rerank-base-v1, 184M | 0.5677 |
| jina-v1-turbo, 38M | 0.5284 |
| jina-v2-base, **278M** | 0.4803 |

**Three 184–278M-parameter cross-encoders lose to a fine-tuned 16M model by 17 to 27 points.**
Every one of them was fetched, digest-pinned and gated in Session I and then never scored; the
reason they were never scored was a CPU latency figure, and the reason that figure was decisive was
a deployment assumption that does not hold.

Session I's L-2→L-6 null (+0.0131, p = 0.7011) recorded its own limit — *"says nothing about bge,
jina or mxbai"*. **It now says it.** The capacity hypothesis is closed across the full admitted
range, on the target hardware.

### But the fit split flatters the fine-tunes, and the honest number is smaller

`session_j_finetune.py` records `"trained_on": "fit split only"`. **The ft models saw these queries
in training and the un-tuned models did not**, so the 17–27 point gap above is measured on
contaminated ground and overstates domain adaptation by roughly 2×. ADR-018's held-out figure for
the same contrast is **+0.0699**.

**The ranking survives, the magnitude does not.** Fine-tuning still beats a 17× parameter increase
decisively at +0.0699 held-out against a capacity effect that is *negative*. Any quotation of the
17-point figure without this paragraph is wrong.

**The depth comparisons are clean**, because both arms are the same model and contamination applies
equally: depth 10 → 30 is +0.0131 (L-2-ft) and +0.0262 (L-6-ft).

---

## The prediction, scored

| registered | outcome |
|---|---|
| **P1** best fit R@1 lands **0.78–0.85** | **REFUTED.** Best is 0.7729 — below the band. Too optimistic |
| **P2** nothing reaches 0.95, none reaches 0.90 | **HELD.** Ceiling is 0.7729 |
| **P3** depth contributes more than capacity | **HELD, strongly.** Depth +0.0131/+0.0262 within a model; capacity −0.0088 at fixed depth 10 (L-2-ft → L-6-ft) and negative across every un-tuned pair |
| **P4** best config inside 300 ms; bge d30 ≈ 245 ms | **HELD on the gate, REFUTED on the estimate.** bge d30 measured **116.4 ms** — my FLOP arithmetic was 2.1× pessimistic. Registered as an estimate, not a measurement, which is why it can be scored at all |

---

## The reframe, and it is the session's real content

**I said the latency budget was the binding constraint. It is not, and this sweep is what shows it.**

| | |
|---|---|
| budget | 300 ms P95 |
| best configuration | **37.1 ms** |
| most expensive cell measured | **203.7 ms** — still inside |

**Every one of the thirty cells fits the GPU budget.** The constraint that had been hiding behind
CPU latency turns out not to be latency at all: given 8× more compute than the shipped path uses,
quality moves by +0.0174 and stops. **There is budget here that cannot be usefully spent.**

That corroborates M0c Session A from an independent direction. It put four *architectures* on the
same separation — including a global cross-encoder with no information bottleneck — and moved top-1
on 2 of 229. This session put nine *pretrained scorers* on it, spanning 16M to 278M and four
architectures, and moved it by less than the promotion floor. **Two independent lines now say the
cross-encoder reranking approach is saturated on this corpus.**

### What that leaves

`R@1 = input_recall × conditional_accuracy`, and the factorisation is now fully mapped:

* **input recall is solved at depth 30** — 0.9825, the whole pruned pool, at 37 ms. The 22-case
  "gold never reaches the reranker" bucket is closable at will.
* **conditional accuracy is the wall.** Best measured 0.8200 (and it *falls* with depth: more
  candidates are more distractors). R@1 0.95 at the 0.9825 ceiling requires **0.967**.

Nothing in the admitted model set is within 15 points of that.

---

## The one mechanism this session did not test, named rather than left implicit

**An LLM reranker.** Declined by the human before the sweep and therefore not measured. It is
recorded as **untested, not refuted** — and the evidence for it is stronger after this sweep than
before it, because the sweep closed the alternative. It is now the only untested mechanism with a
plausible path to the conditional accuracy the target needs.

**The other named lever remains supersession**, worth +0.1666 on knowledge-update R@1_current by
M0c Session A's oracle, and blocked on HP2 entity identity rather than on ranking.

---

## Instrument discipline

**The control reproduces the published fit R@1 exactly: 0.7555 = 0.7555**, with input recall 0.9214
matching Session I and conditional accuracy 0.8200 against Session K's 0.8199. The sweep refuses to
run otherwise, for the reason `publish_precision_coverage.py` carries the same refusal: a
reconstruction of a five-level ranking key has at least four ways to be subtly wrong and every one
of them yields a plausible number.

**R@1_current reads 0.6987 against M0c Session A's published 0.6900 — a 2-case difference, and it
is an instrument difference, not a reproduction.** This sweep classifies the current-value turn by
verbatim containment of the gold answer; M0c Session A used a richer rule with 11 flagged
fallbacks. **R@1_current deltas are comparable WITHIN this table and must not be differenced
against M0c Session A's published figure.**

**Two gates were re-measured per graph rather than inherited, and one moved:**

| | CPU (Session K) | CUDA (here) |
|---|---|---|
| GPU→GPU determinism | — | **PASSES**, 3 identical values |
| batch invariance, shipped graph | **0.000000** | **0.000324, NOT identical** |

The batch-invariance change is consistent with ADR-029, whose amended gate is GPU→GPU byte-identity
plus cross-provider *ranking* equivalence, not cross-provider logit identity. **Ranking equivalence
re-confirmed here:** re-scoring the shipped graph through the GPU batched path returns R@1 0.7555,
identical to the shipped CPU number. Had the gate been inherited from the CPU measurement, the
0.000324 would never have been seen.

**A stale handoff corrected.** Session L's RESULT.md §6 says *"GPU is closed on correctness"*. Its
own ADR-029 reverses that and explains why: the original spike compared each CUDA repeat against the
**CPU** reference rather than against the other repeats, reporting cross-provider disagreement as
within-provider nondeterminism. GPU→GPU determinism was never broken. The ADR is adopted and the
RESULT.md line is stale.

---

## What this session did not touch

Named, because the closure pattern this milestone is correcting is exactly the silent carry:

* the ANN index and int8 hot vector array
* the live-only hot index
* group commit on journal append
* consolidation as a run
* the query-type router
* **cues 3, 4 and 5** — entity-graph and causal unattempted; **temporal refuted on this corpus**
  (Session G arm 4: 1/59 temporal-reasoning questions carry a parseable window; held-out −0.0087)
* `effective_trust` — still inert, still the human's reserved decision
* the two existing cues — untuned, per the standing instruction

---

## The argument for reading the floor generously, recorded rather than acted on

Stated because CLAUDE.md requires it be argued explicitly and not quietly applied.

**For:** +0.0174 is the largest quality movement measured since ADR-018. Its two arms are the same
model, so contamination cancels. It is Tier A — a digest re-pin in `rerank.rs` and nothing else. It
costs 30 ms of a 263 ms surplus. And the depth half of it raises input recall *monotonically*, which
is structurally safer than the slate-rule change that flipped sign.

**Against:** it is below a floor that was set a session in advance for this exact purpose, and the
one directly comparable fit gain in this project's history went from +0.0087 to −0.0044 across the
split.

**Not decided here.** One held-out read would settle it and costs one number; spending it is the
human's call.
