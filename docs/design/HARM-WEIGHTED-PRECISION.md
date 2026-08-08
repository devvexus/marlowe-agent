# Harm-weighted precision — what R@1 has been hiding

**§5.7's argument is about harm, not accuracy.** A wrong injected memory corrupts reasoning; that is
why the design is precision-first with abstention, and why the trust-class and supersession
machinery exists. Every arm since Session H has optimized **R@1**, which treats a topically
adjacent turn and a superseded fact as the same failure. They are not the same failure.

This page separates them. It needs no new labels.

| | |
|---|---|
| **Measured by** | `tools/publish_harm_weighted_curve.py`, over `tools/reach_harm_r5_classes.py`'s partition |
| **Configuration** | `ms-marco-MiniLM-L-2-v2-ft-session-j`, f32, seq 256, depth 10 — the shipped path, unmodified |
| **Split** | held-out and fit, n = 229 each, `split.json` digest `3a685798…` |
| **Control** | the published-gold read reproduces `PRECISION-COVERAGE.md`'s R@1 **exactly** (0.6725 / 0.7555); the tool refuses to write otherwise |
| **Machine-readable** | `runs/session-m0c/harm-weighted-curve.json` |

---

## The structural fact this rests on

LongMemEval's knowledge-update cases carry **exactly two answer sessions** — 78 of 78. One states an
old value of a fact; the other states the value the `answer` field holds. **Both are marked
`has_answer: true`**, and `longmemeval.py:144` puts every such turn into `gold_turn_ids`.

```
answer = "25 minutes and 50 seconds (or 25:50)"
  [answer_a25d4a91_1-4]  has_answer=true  "...set a personal best ... of 27:12"       <- SUPERSEDED
  [answer_a25d4a91_2-0]  has_answer=true  "...beat my personal best time of 25:50"    <- CURRENT
```

> **Retrieving the stale fact scores as an R@1 hit.** The harmful case has been counted as a success
> in every R@1 this project has published.

**The classifier does not use an ordering.** A first version ranked the two answer sessions by
`haystack_dates` and called the later one current. That is a proxy, and this is the wrong corpus for
it — the loader records that the release dates 76 of 500 cases with sessions *after* their own
question. The `_1`/`_2` suffix is a second proxy; a naming convention is not a timestamp. The
quantity actually wanted is *which gold turn states the value the answer holds*, and that is
directly checkable. Measured: the answer-bearing session is the later one **by suffix in 86.4%** and
**by date in 84.7%** of the 59 decisive knowledge-update cases. Neither is reliable enough to
classify harm by, so neither is used. 59 cases resolve from the answer text, 11 fall back to suffix
order and are **flagged**; every number below survives their removal (held-out harmful 13 → 12).

**Supersession is scoped to knowledge-update deliberately.** multi-session and temporal-reasoning
also carry 2–3 answer sessions, but there none supersedes another — the question needs several turns
to answer. Applying a recency rule there would manufacture harm out of a category where every answer
session is meant to count.

### The five classes, over the shipped rank-1

| class | meaning | harmful? |
|---|---|---|
| `current` | gold, in the answer-bearing session | no |
| `superseded` | gold, in the *other* answer session of a knowledge-update case | **yes — and scored as an R@1 hit** |
| `stale_session` | not gold, but in that same superseded session | **yes** |
| `on_topic_wrong` | not gold, in some answer session — right conversation, wrong turn | no, merely useless |
| `irrelevant` | in no answer session at all — costs tokens, misleads nobody | no, merely useless |

---

## The answer: most failures are useless, but R@1 is inflated

**Held-out, n = 229, shipped configuration:**

| class | count | share |
|---|---|---|
| current | 144 | 62.88% |
| **superseded** | **10** | **4.37%** |
| **stale_session** | **3** | **1.31%** |
| on_topic_wrong | 46 | 20.09% |
| irrelevant | 26 | 11.35% |

| | held-out | fit |
|---|---|---|
| **R@1 as published** | **0.6725** | **0.7555** |
| **R@1 counting only the current value** | **0.6288** | **0.6900** |
| **inflation** | **+0.0437** | **+0.0655** |
| harm rate | 0.0568 (13/229) | 0.0742 (17/229) |

**Of the injections that are not the current value — the question as asked:**

| | held-out | fit |
|---|---|---|
| harmful | **13 of 85 (15.3%)** | 17 of 71 (23.9%) |
| merely useless | 72 of 85 (84.7%) | 54 of 71 (76.1%) |

> **§5.7's premise is weaker than assumed on the failure side.** Roughly five in six wrong
> injections cost tokens rather than corrupt reasoning. That is a real finding about the design: the
> harm argument is carried by a minority of failures.

---

## But the inflation is concentrated exactly where §5.7 reads

**Knowledge-update alone**, the category supersession is expressible on:

| | held-out (n=36) | fit (n=36) |
|---|---|---|
| R@1 as published | 0.7222 (26/36) | 0.7222 (26/36) |
| **R@1 counting only the current value** | **0.4444 (16/36)** | **0.3056 (11/36)** |
| harm rate | 0.3611 | 0.4722 |
| **stale hits among apparent hits** | **10 of 26 (38.5%)** | **15 of 26 (57.7%)** |

> **On the category §5.7 was written about, between 38% and 58% of what R@1 counts as a success is
> the outdated fact.** Category R@1 is inflated by 28 points on held-out and 42 on fit.

---

## The coverage curve, harm-weighted

Held-out. Coverage selected by the rank1-minus-rank2 rerank margin — identical to
`publish_precision_coverage.curve`, so rows line up with the published curve point for point. Every
figure carries an exact Clopper-Pearson 95% interval.

| coverage | n_c | precision **published** | 95% CI | precision **current** | 95% CI | **harm rate** |
|---|---|---|---|---|---|---|
| 100.0% | 229 | 0.6725 | [0.6076, 0.7329] | **0.6288** | [0.5627, 0.6915] | 0.0568 |
| 90.0% | 206 | 0.6942 | [0.6264, 0.7563] | 0.6456 | [0.5762, 0.7108] | 0.0631 |
| 75.1% | 172 | 0.7384 | [0.6660, 0.8023] | 0.6860 | [0.6110, 0.7545] | 0.0640 |
| 59.8% | 137 | 0.7080 | [0.6243, 0.7825] | 0.6715 | [0.5862, 0.7493] | 0.0511 |
| 45.0% | 103 | 0.7379 | [0.6420, 0.8196] | 0.6990 | [0.6008, 0.7855] | 0.0485 |
| 34.9% | 80 | 0.8125 | [0.7097, 0.8911] | 0.7625 | [0.6542, 0.8505] | 0.0500 |
| 30.1% | 69 | 0.8116 | [0.6994, 0.8957] | 0.7971 | [0.6831, 0.8844] | 0.0145 |
| 20.1% | 46 | 0.8696 | [0.7374, 0.9506] | 0.8478 | [0.7113, 0.9366] | 0.0217 |
| 14.8% | 34 | 0.8824 | [0.7255, 0.9670] | 0.8824 | [0.7255, 0.9670] | **0.0000** |
| **10.0%** | **23** | **0.9130** | [0.7196, 0.9893] | **0.9130** | [0.7196, 0.9893] | **0.0000** |

### At the declared operating point, the two precisions are identical

**Published 0.9130, current-only 0.9130, inflation +0.0000, harm 0 of 23.** The declared operating
point injects no stale facts, on either split. `PRECISION-COVERAGE.md`'s number needs no correction
**at 10% coverage**. It needs a −0.0437 correction at full coverage.

---

## Why harm is zero at the head — and it is not what it looks like

The naive reading is "abstention suppresses the harmful class". **That reading is a proxy and it is
wrong.** Measured:

| | fit | held-out |
|---|---|---|
| median margin, all queries | 0.4254 | 0.4020 |
| median margin, knowledge-update | **0.3548** | **0.2782** |
| knowledge-update share of the top-10% slice | **4.3%** (1 of 23) | **0.0%** (0 of 23) |
| base rate of knowledge-update | 15.7% | 15.7% |
| **within knowledge-update**, harm rate top-half by margin | 0.389 | **0.444** |
| **within knowledge-update**, harm rate bottom-half by margin | 0.556 | **0.278** |

> **The head is harm-free because it contains almost no knowledge-update queries at all**, not
> because the confidence signal discriminates harm. And **within** knowledge-update the margin
> carries no reliable information about harm — the direction *flips between splits* (falls on fit,
> rises on held-out).

This matters for what may be concluded:

- The protection is a **category-exclusion side effect**, not a harm-aware mechanism. Knowledge-update
  queries are simply low-confidence, and the margin threshold drops them.
- **It is therefore fragile.** Anything that raises coverage, or that makes knowledge-update queries
  more confident — including a successful retrieval improvement on that category — removes the
  protection without any component reporting a change.
- `0.0000` on n = 23 has a Clopper-Pearson upper bound of **0.1482**. It is not evidence of zero.

---

## Does the existing machinery already fix this? No, and the reason is precise

**The §4.3 exclusion exists, is correct, and is live.** `crates/marlowe-memory/src/entry.rs:124`:

```rust
pub fn is_injection_candidate(&self, now_ms: i64) -> bool {
    self.fidelity > Fidelity::Tombstone      // (1) tombstones
        && self.superseded_by.is_none()      // (2) superseded entries
        && self.is_matured(now_ms)           // (3) unmatured entries
}
```

Called at `retrieve.rs:328`, unit-tested per exclusion at `entry.rs:188`. **This is not a wiring
defect.**

**The gap is the trigger.** The only thing in the workspace that ever sets `superseded_by` is
consolidation's near-duplicate merge at `consolidate.rs:697`, thresholded at **cosine ≥ 0.98**.
`ingest.rs:142` hardcodes `superseded_by: None` on every write, and §4.6's `IngestRequest` has no
supersession field and forbids extras — **a caller cannot assert it.** `store.rs:133` states plainly
that the contradiction detector is deferred.

And ADR-012 already measured why that threshold cannot help here: LongMemEval distractors are
*"topically related rather than textually duplicated"*; pairs at ≥ 0.98 are **0.0086%** of
30,587,870. A knowledge-update pair — "my best is 27:12" versus "my best is 25:50" — is a semantic
contradiction of moderate similarity, nowhere near 0.98.

> **The exclusion is live and blind.** It fires on ~1.19% of the pool, on the wrong thing. Neither
> "supersession is not detected" nor "the exclusion is not firing" is quite right: the filter fires
> correctly on every edge it is given, and nothing gives it the edges that matter.

**This is a missing component, not a tuning opportunity** — and it is the component §5.7's argument
assumes exists.

---

## What this page does not claim

- **It is still a gold-turn proxy.** §5.7's injection precision is what a *human judge* rates
  relevant. The harm classes are derived from LongMemEval's own annotation, which is better than
  R@1 but is not a human judgment of harm. The ≥400-judgment blind label set remains the only path
  to the headline metric.
- **`harmful` is not calibrated against a cost.** It counts injections of a superseded fact. It does
  not weigh them against the token cost of a useless one, because no such exchange rate has been
  argued.
- **n is small where it matters.** 36 knowledge-update queries per split; 23 at the operating point.
  Every interval is published for that reason.
