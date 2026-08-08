# M0b Session J — the ceiling never measured quality, normalization is a null, fine-tuning ships

**Three deliverables, all run. Nothing shipped — measurement was the deliverable, per Session I's
precedent.** `rerank.rs` and `eval/` are unchanged.

| | |
|---|---|
| **1. The 0.3739 ceiling was never a quality signal** | A **perfect** retrieval system scores **0.8483** on the shipped gate against a 0.95 threshold. Nine sessions read the gap as closable by better retrieval. It never was. **ADR-016.** |
| **2. Length normalization is a NULL on held-out, with power** | Fit gains of +0.0349 to +0.1048 do **not** reproduce. Registered floor fails on L-2; the post-hoc form fails its floor on every cell. Not covariate shift — gold length distributions are identical across splits. **ADR-017 + amendment.** |
| **3. Fine-tuning is the lever, and it ships** | L-2 f32 held-out **0.6026 → 0.6725, +0.0699**, discordant 38, exact **p = 0.0139**, α attainable. **214 ms/query, inside the 300 ms budget.** First significant held-out change to the scored path in the project. **ADR-018.** |
| **4. K1, answered for the first time** | **No coverage level reaches 0.95 precision** with its interval above the threshold. Best point estimate **0.9565 (22/23) at 10.0% coverage**, CI **[0.7805, 0.9989]**. |

Pre-registration `PREREGISTRATION.json`, written before anything was fit. Post-hoc addendum
`ADDENDUM-post-hoc-length-form.json`, written before any held-out read.

---

## Part 0 — the ADR-010 check that came back negative

`gate-resolution.json`, licensed by the standing fidelity gate (lexical 0.5415, dense 0.4454,
either-cue 0.6463, all exact).

**`max_calibrated_precision ≥ 0.95` is unreachable at `CALIBRATION_BLOCKS = 256` for any feature,
including a perfect one.** Three measured steps:

1. **Resolution.** Every pooling operation in `fit_isotonic` enlarges a block. The smallest
   expressible operating point is **435 rows = 1.90 candidates per query**.
2. **Forced composition.** `{cue}_margin` is positive for exactly one candidate per query, so the
   top block must be one row from every query plus the least-negative rank-2s. **Measured: 229 of
   229 queries, 100% coverage, exactly 229 rank-1 rows, for both cues.** A precision threshold asks
   for a confident *subset*; the gate has no vocabulary for subsets.
3. **The oracle.** 89 of 229 fit queries have exactly one gold row, so their rank-2 slot is
   necessarily a distractor. A perfect cue gets 229 + min(206, 140) = **369 / 435 = 0.8483**.

At full coverage the value is a diluted single-cue R@1: lexical 0.3885 (129 gold among 229 rank-1
rows, 40 among the other 206), dense 0.3540. **That is the whole of 0.3739.**

**Not run, and reported as not run:** the second-implementation check against the published
0.373913. The shipped ceiling was fit on the `--fit-mode` dump whose in-process attribution was
never archived; attributing it through the consolidation-applied transcript gives 119340 rows /
452 positives against the artifact's 117894 / 450. The refusal fired and the licensed gated
population was used instead.

---

## Part 1 — arm 7, and it does not survive held-out

### Fit looked good

| fit, R@1 | control | 7c registered | Δ | 7f post-hoc |
|---|---|---|---|---|
| L-2 f32 @256 | 0.5983 | 0.6332 | +0.0349 | 0.6769 |
| L-2 f32 @512 | 0.5066 | 0.6114 | +0.1048 | 0.6419 |
| L-6 f32 @256 | 0.6114 | 0.6638 | +0.0524 | 0.6856 |
| L-6 f32 @512 | 0.6026 | 0.6638 | +0.0612 | 0.6856 |
| L-2 int8 @256 *(shipped)* | 0.6201 | 0.6463 | +0.0262 | 0.6681 |

### Held-out says no

| held-out, seq 256 | control | 7c@0.5 | Δ | discordant | exact p | 7f@2.0 | Δ |
|---|---|---|---|---|---|---|---|
| L-2 int8 *(shipped)* | 0.5764 | 0.5764 | +0.0000 | 24 | 1.0000 | 0.5895 | +0.0131 |
| L-2 f32 | 0.6026 | 0.5939 | **−0.0087** | 30 | 0.8555 | 0.5983 | −0.0043 |
| L-6 f32 | 0.6201 | 0.6419 | +0.0218 | 43 | 0.5424 | 0.6201 | +0.0000 |

**α attainable on every contrast (discordant 24–43). None approaches significance.** The registered
floor of +0.01 fails on L-2 f32; L-6's +0.0218 is at the top of its band but at p = 0.5424.

**The post-hoc form fails its +0.02 floor on every cell — and it was the strongest on fit.** Exactly
what post-hoc selection predicts, and why the addendum pinned its prediction in advance.

**It is not covariate shift.** Gold length is identical across splits: median 70 word pieces, p75
84, p95 239 vs 224; assistant-authored gold 8.4% vs 7.0%. The fit gain was 8 net cases of 229 at
p = 0.1516 — already not significant — and it does not reproduce.

### The estimator finding, which does survive

The registered `f_hat = E[score | length]` came out with slope **−0.5091** and *added* score to long
candidates; 7b/7d/7e failed at every strength. The diagnosis generalizes:

| length bin (median wp) | 32 | 51 | 68 | 88 | 186 | 368 | 530 | 656 |
|---|---|---|---|---|---|---|---|---|
| mean logit | −6.94 | −6.90 | −6.02 | −5.87 | −6.73 | −7.07 | −8.03 | −8.62 |
| **gold rate** | 0.115 | 0.248 | **0.353** | 0.329 | 0.063 | 0.039 | **0.007** | **0.007** |

**The mean logit moves 2.6 and is not monotone; the gold rate falls 50-fold.** `E[s|len]` measures
the model's length response when what needs correcting is that response *relative to relevance's*.
**Ninth instance of the family** — ADR-011 mechanism, ADR-013 read, ADR-014 contrast, here estimator.

### The truncation closure is withdrawn

| normalized 7c@0.5, 512 vs 256 | fit Δ | held-out Δ | discordant |
|---|---|---|---|
| L-6 f32 | 0.0000 | −0.0087 | 2 |
| L-2 f32 | −0.0437 | −0.0611 | 16 (p = 0.0005) |

L-6 stays numerically inside the −0.01 bar on both splits, but on **2 discordant cases**, and the
precondition — that normalization works — is itself a held-out null. **`MAX_SEQ_LEN` stays 256 and
the 7.86% gold truncation stays a known, priced defect.**

---

## Part 2 — fine-tuning, and it is the result

| held-out, seq 256, depth 10 | R@1 | Δ vs own base | discordant | exact p | ms/pair | ms/query |
|---|---|---|---|---|---|---|
| L-2 int8 *(shipped today)* | 0.5764 | — | — | — | 8.9 | 89 |
| L-2 f32 | 0.6026 | — | — | — | 20.1 | 201 |
| **L-2 f32 FINE-TUNED** | **0.6725** | **+0.0699** | 38 (27/11) | **0.0139** | 21.4 | **214** |
| L-6 f32 | 0.6201 | — | — | — | 57.0 | 570 |
| L-6 f32 fine-tuned | 0.6681 | +0.0480 | 43 (27/16) | 0.1263 | 74.1 | 741 |

Registered band: floor +0.02, predicted [+0.02, +0.08], derived from this project's own evidence and
explicitly not inherited from the research report. **+0.0699 lands inside it.**

**This is not the capacity null in disguise.** Tripling depth bought +0.0131 at p = 0.7011.
Domain-adapting the *smaller* model bought +0.0699 at p = 0.0139, and the fine-tuned 16M-parameter
L-2 beats the un-tuned 22M L-6 by +0.0524. **The gap was never capacity.**

**It ships.** L-6 fine-tuned is better on fit and worse on every other axis — 741 ms/query against a
300 ms budget. L-2 fine-tuned is 214 ms/query *and* the better held-out model.

**Discipline:** trained on fit only; mined and split **by conversation id** (3 gold sessions are
shared between fit queries, so the two differ); 2182 shared haystack sessions measured, exactly 1
fit query collides and was dropped; checkpoint chosen on a fit-carved validation slice; the
hard-label MarginMSE substitution registered as a deviation with its reason **before** training.

**Export gap bounded, not closed.** Comparability before training: Pearson **1.000000**, max |Δlogit|
**0.000014**, identical R@1 — so the delta is measured against the existing baseline. All five
post-export checks pass on both models: batch invariance **0.000000**, padding invariance
**0.000000**, torch-vs-ORT **0.000003** / **0.000001**. Training reproduces bit-identically.
**Self-validated only — this session is the publisher, and a second instance of the gap now exists.**

---

## Part 3 — the K1 number

### Arm (a): reports the bound and stops

Per ADR-016 the oracle is 0.8483 < 0.95, so no refit can clear the threshold whatever features it
is given. None was fitted. `THRESHOLD = 0.95` untouched.

### Arm (b): conformal, guarantee and measurement kept apart

| α | τ | **GUARANTEE** P(inject \| wrong) ≤ | **MEASURED** P(inject \| wrong) | **MEASURED** precision | coverage | n |
|---|---|---|---|---|---|---|
| 0.05 | 1.4639 | 0.05 | **0.0133** | 0.9333 [0.6805, 0.9983] | 6.6% | 15 |
| 0.10 | 0.9569 | 0.10 | 0.0667 | 0.8611 [0.7050, 0.9533] | 15.7% | 36 |
| 0.20 | 0.5846 | 0.20 | 0.2000 | 0.8148 [0.7130, 0.8925] | 35.4% | 81 |

*(fine-tuned L-2, held-out)*. The guarantee bounds the **false-injection rate among wrong queries**
— marginal, distribution-free, finite-sample. **It is not precision.** K1 asks for
P(correct | injected), a selective risk the marginal bound does not cover. Both are reported; neither
is described as the other.

**Global τ only.** No category clears the registered n ≥ 40 floor — the largest wrong-query
calibration set is 22 (`multi-session`). Per-group n reported beside the rule, as registered.

### The precision/coverage curve — the deliverable

| coverage | shipped (n) | precision [95% CI] | fine-tuned L-2 (n) | precision [95% CI] |
|---|---|---|---|---|
| 100% | 229 | 0.5764 [0.510, 0.641] | 229 | **0.6725** [0.608, 0.733] |
| 75% | 172 | 0.6337 [0.557, 0.706] | 172 | **0.7384** [0.666, 0.802] |
| 50% | 114 | 0.7105 [0.618, 0.792] | 114 | 0.7281 [0.637, 0.807] |
| 35% | 80 | 0.7875 [0.682, 0.871] | 80 | 0.8125 [0.710, 0.891] |
| 25% | 57 | 0.8421 [0.721, 0.925] | 57 | 0.8246 [0.701, 0.913] |
| 20% | 46 | 0.8696 [0.737, 0.951] | 46 | 0.8696 [0.737, 0.951] |
| 15% | 34 | 0.8824 [0.726, 0.967] | 34 | 0.8824 [0.726, 0.967] |
| **10%** | 23 | **0.9565** [0.781, 0.999] | 23 | 0.9130 [0.720, 0.989] |

> ## **No coverage level reaches 0.95 precision with its interval lower bound above the threshold.**
> **This is the K1 answer.**

The best point estimate is **0.9565 — 22 of 23 — at 10.0% coverage on the shipped configuration**,
one error away from the bar on 23 queries, with a lower interval bound of **0.7805**. The registered
prediction was that no coverage level would clear it by interval. **Confirmed.**

**A real observation that is not noise-shaped:** fine-tuning dominates the curve from 100% down to
about 25% coverage and then stops helping. It improves the *body* of the ranking, not its
*confident head*. The head is where K1 reads, so **+0.0699 R@1 bought nothing at the operating
point** — a concrete instance of the thing this project keeps rediscovering, that a metric and an
operating point are different questions.

---

## Standing checks

| check | result |
|---|---|
| `cargo test --workspace` | **188 passing, 0 failed** |
| `cd eval && pytest` | **72** |
| `repro --runs 2`, cold, no cache | **byte-identical** |
| second implementation reproduces the first | **PASS** — held-out control reads **0.5764**, Session H's published number, through a code path that did not exist then |
| ONNX graph optimization level pinned both sides | **PASS** — `ORT_ENABLE_BASIC` throughout |
| provider asserted after construction | **PASS** |
| every model pinned by sha256 | **PASS** — including both fine-tuned graphs, in a **separate** Session J manifest so Session I's is not edited |
| any cell varying sequence length runs f32 | **PASS** — int8 refused at seq ≠ 256 by the tool |
| `eval/` untouched | **PASS** |
| `rerank.rs` untouched | **PASS** — nothing shipped |

---

## What a later session inherits

1. **Never quote 0.3739 against 0.95 as a quality gap.** ADR-016. The gate-design constraint —
   either the resolution rule or the margin feature's one-positive-per-query property must change —
   is recorded beside the K1 conversation.
2. **Fit a normalization term against relevance, not against the score.** ADR-017 §1 survives its
   own amendment.
3. **The fine-tuned L-2 is measured and not shipped.** Shipping needs a pinned digest, a
   `--reranking` path, a conformance run, and a decision on f32-at-214-ms versus int8-at-89 —
   including whether to quantize, which re-opens ADR-015's shape-binding on an unmeasured graph.
4. **R@1 and the operating point are different questions.** +0.0699 R@1 moved the curve everywhere
   except where K1 reads it.
