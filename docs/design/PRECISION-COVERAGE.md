# The precision/coverage curve, and the declared operating point

**Required to ship with the product by the amended K1** (`ROADMAP.md` → "K1 — amended 2026-08-08",
argued in ADR-019). This is not a run output; it is part of what Marlowe publishes about itself.

| | |
|---|---|
| **Configuration** | `ms-marco-MiniLM-L-2-v2-ft-session-j`, f32, seq 256, depth 10 (ADR-018, ADR-020) |
| **Split** | held-out, n = 229, `split.json` digest `3a685798…` |
| **Measured by** | `tools/publish_precision_coverage.py`, from the **shipped binary's own dump** |
| **Machine-readable** | `crates/marlowe-memory/artifacts/precision-coverage-heldout-v1.json` |
| **Regenerate** | `python tools/publish_precision_coverage.py --run runs/session-k --reranking-label <NAME>` |

---

## The curve

Every coverage level from 100% down to 10%, each point with its exact (Clopper-Pearson) 95%
interval. Coverage is selected by thresholding the **rank-1 minus rank-2 rerank margin** — the
ranking key actually in force.

| coverage | n | **precision** | 95% CI | ≥ 0.95? |
|---|---|---|---|---|
| 100.0% | 229 | 0.6725 | [0.6076, 0.7329] | no |
| 95.2% | 218 | 0.6743 | [0.6077, 0.7361] | no |
| 90.0% | 206 | 0.6942 | [0.6264, 0.7563] | no |
| 85.2% | 195 | 0.7026 | [0.6331, 0.7658] | no |
| 79.9% | 183 | 0.7213 | [0.6504, 0.7849] | no |
| 75.1% | 172 | 0.7384 | [0.6660, 0.8023] | no |
| 69.9% | 160 | 0.7312 | [0.6555, 0.7982] | no |
| 65.1% | 149 | 0.7248 | [0.6457, 0.7947] | no |
| 59.8% | 137 | 0.7080 | [0.6243, 0.7825] | no |
| 55.0% | 126 | 0.6984 | [0.6103, 0.7769] | no |
| 49.8% | 114 | 0.7281 | [0.6367, 0.8072] | no |
| 45.0% | 103 | 0.7379 | [0.6420, 0.8196] | no |
| 40.2% | 92 | 0.7717 | [0.6725, 0.8528] | no |
| 34.9% | 80 | 0.8125 | [0.7097, 0.8911] | no |
| 30.1% | 69 | 0.8116 | [0.6994, 0.8957] | no |
| 24.9% | 57 | 0.8246 | [0.7009, 0.9125] | no |
| 20.1% | 46 | 0.8696 | [0.7374, 0.9506] | no |
| 14.9% | 34 | 0.8824 | [0.7255, 0.9670] | no |
| **10.0%** | **23** | **0.9130** | **[0.7196, 0.9893]** | no |

> ### No coverage level reaches 0.95 precision with its interval lower bound above the threshold.
> **That is the K1 answer, and it is unchanged by shipping a better model.**

---

## The declared operating point

> ## Coverage **10.0%** · precision **0.9130** (21 of 23) · 95% CI **[0.7196, 0.9893]**
> Margin threshold **≥ 1.1651**. Below it, the system **abstains**.

**This is the number that must be stated wherever the capability is described**, per condition 2 of
the amended criterion. Not the 0.6725 headline R@1, and not a rounded 0.91 without its interval —
**n is 23, and the interval is what an honest reading of 23 cases looks like.**

A second point is available and is reported rather than hidden. The conformal construction at
α = 0.05 selects a smaller, more confident set: **precision 0.9333 (14 of 15) at 6.55% coverage, CI
[0.6805, 0.9983]**, τ = 1.4639. It buys ~2 points of precision for ~3.5 points of coverage on 8
fewer queries, and its interval is wider. **10% is declared because the criterion reads there and
because n = 23 is the less fragile of the two**, not because it is better on every axis.

---

## The prediction, and then the measurement

**Published in that order deliberately.** Before this curve was computed, the expectation on record
was that the shipped fine-tuned graph would read *worse at the head* than the int8 configuration it
replaces, because Session J measured fine-tuning as helping the body of the ranking and stopping at
the top decile.

| at 10% coverage | superseded int8 (Session J) | **shipped fine-tune (Session K)** |
|---|---|---|
| precision | **0.9565** (22/23) | **0.9130** (21/23) |
| 95% CI | [0.7805, 0.9989] | [0.7196, 0.9893] |
| at 100% coverage | 0.5764 | **0.6725** |

**Confirmed. The head got worse while full coverage got better.** One case of 23 flipped at the
operating point, against +22 cases of 229 across the split as a whole. The two configurations are
statistically indistinguishable at the head — 21 versus 22 of 23, with overlapping intervals — and
that is precisely the point: **+0.0961 R@1 bought nothing where the criterion reads.**

This is the clearest statement available of ADR-019 §3 and it is more useful than either number
alone. **A metric and an operating point are different questions.** Nine sessions of retrieval work
moved the metric; the operating point did not follow. The named lever is no longer "raise R@1" but
**"what makes the top decile separable"** — and the rerank margin is not it.

---

## The kill condition, evaluated

The amended criterion adds a **new** way to fail that the original did not have: *the project is
reconsidered if the curve is flat.*

| | |
|---|---|
| precision @ 100% coverage | 0.6725 |
| precision @ 10% coverage | 0.9130 |
| **delta** | **+0.2405** |
| CI lower bound @ 10% | 0.7196 |
| rule | flat ⟺ NOT (precision@10 > precision@100 **and** ci_low@10 > precision@100) |
| **verdict** | **NOT flat. Kill condition NOT met.** |

The interval half of the rule is what stops a noise-sized gap on 23 queries from reading as a pass.
Here 0.7196 > 0.6725 with room, so **the confidence signal carries real information** — the failure
K1 was written to catch is not present.

---

## The guarantee and the measurement are two different quantities

**They are never conflated, in the artifact or here.** The conformal construction calibrates τ on
the margins of *fit*-split queries whose rank 1 is not gold, at the `(1−α)(1+1/n)` quantile.

| α | τ | **GUARANTEE** `P(inject \| wrong) ≤` | **MEASURED** `P(inject \| wrong)` | **MEASURED** precision | coverage | n |
|---|---|---|---|---|---|---|
| 0.05 | 1.4639 | 0.05 | **0.0133** | 0.9333 [0.6805, 0.9983] | 6.55% | 15 |
| 0.10 | 0.9569 | 0.10 | 0.0667 | 0.8611 [0.7050, 0.9533] | 15.72% | 36 |
| 0.20 | 0.5846 | 0.20 | 0.2000 | 0.8148 [0.7130, 0.8925] | 35.37% | 81 |
| 0.30 | 0.4680 | 0.30 | 0.3467 | 0.7400 [0.6427, 0.8226] | 43.67% | 100 |

**The guarantee bounds the false-injection rate among wrong queries** — marginal, distribution-free,
finite-sample. **It is not precision.** K1 asks for `P(correct | injected)`, a *selective* risk the
marginal bound does not cover: it depends on the base rate of correctness and on how coverage falls,
neither of which the conformal construction pins.

> Reporting the 0.05 bound as though it were a 95% precision guarantee would be the same category
> error the 0.3739 ceiling was read with for nine sessions. Both columns are published; neither is
> described as the other.

---

## Global τ only — no category clears the floor

Group-conditional thresholds are **refused**, per the registered `n ≥ 40` floor on the wrong-query
calibration set. The per-group n is published beside the rule so the refusal is visible rather than
implied:

| category | fit n | fit n **wrong** | held-out n | eligible? |
|---|---|---|---|---|
| knowledge-update | 36 | 10 | 36 | no |
| multi-session | 61 | 12 | 60 | no |
| single-session-assistant | 28 | 6 | 27 | no |
| single-session-preference | 15 | 10 | 15 | no |
| single-session-user | 32 | 6 | 32 | no |
| temporal-reasoning | 57 | 12 | 59 | no |

The largest wrong-query calibration set is 12. A finite-sample conformal bound degrades as `1/n` per
group, and per-category reads are already known to be unstable across the split — which is a finding
*against* group-conditional conformal, not a caveat on it.

---

## What this curve is NOT

**It is not the headline metric, and the distinction is not pedantic.** §5.7's injection precision is
*the fraction of auto-injected memories a human judge rates relevant*. Every figure on this page is a
**gold-turn proxy**: rank 1 is scored correct when it is one of LongMemEval's annotated gold turns.

**True injection precision has never been computed.** The ≥400-judgment blind label set remains the
only path to it. It is now *drawable* — a conformal operating point exists to sample from, which it
did not before — and until it is drawn, every number here should be read as a proxy that is
published because it is honest about being one.

**The gate does not currently inject at all.** Not because retrieval is too weak: per ADR-016 the
isotonic gate's smallest expressible operating point spans 100% of queries, and **a perfect
retrieval system scores 0.8483 on it** against a 0.95 threshold. This curve is measured at query
resolution (1/229), which is the only resolution that can express a confident subset. **Wiring this
operating point into an injection path is M2 work**, together with the abstention path condition 3
requires.
