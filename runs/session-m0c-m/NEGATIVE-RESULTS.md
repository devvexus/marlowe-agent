# Twenty-three ways not to improve turn-level R@1 on LongMemEval-S

**A catalogue of negative results with mechanisms, from M0c Session M.**
Every number here is measured. Every method was run to completion on the same frozen split with the
same instrument gate. Nothing shipped.

---

## Abstract

We attempted to improve turn-level Recall@1 on LongMemEval-S beyond a baseline of **0.6725**
(held-out, n=229) using twenty-three distinct mechanisms spanning feature engineering, model
substitution, architecture change, retraining, and generative selection. **All twenty-three failed.**
Four cleared a pre-registered promotion floor on the fit split and were falsified by a held-out
read; nineteen failed on fit or on a control.

Three results are worth reporting beyond the individual nulls:

1. **A structural property of the corpus explains most failures.** Gold turns are multi-topic with a
   narrow answer span; distractors are single-topic and coherent. Any mechanism rewarding sustained
   topical support favours the distractor; any mechanism isolating a peak surfaces the distractor's
   query-echoing span as readily as the gold's answer.
2. **Threshold selection overfits at n=229, not merely training.** One mechanism that was never
   trained — only a single hyperparameter chosen from ten candidate values on the fit split — moved
   +0.0305 on fit and **−0.0087** on held-out.
3. **The post-hoc reranking class has a measurable ceiling of +5 cases**, achieved by blind coin-flip
   swapping in a narrow score band. No feature, ensemble, or auxiliary model exceeded it.

---

## 1. System under test

**Corpus.** LongMemEval-S, 500 questions, ~48 haystack sessions and ~490 candidate turns per
question. Split once, deterministically, stratified by question category: **251 fit / 249 held-out**,
digest-pinned, never redrawn.

**Pipeline.**

```
~490 turns
  → §4.3 exclusions (tombstone, superseded, unmatured) + session scope
  → BM25 (lexical cue)  +  cosine over jina-embeddings-v2-small (dense cue)
  → frozen isotonic gate: per-cue margin calibration, winning cue's z orders
  → session pruning: derive sessions by 30-min gap, keep union of each cue's top-3
  → top-10 slate by (survived_pruning, cue z, cue margin, id)
  → cross-encoder: ms-marco-MiniLM-L-2-v2, fine-tuned, f32, 2 layers, hidden 384, seq 256
  → rank 1
```

**Deployment constraint.** Auto-injection admits `vec![order[0]]` — **exactly one memory**. R@1 is
therefore the product metric, not a research proxy. R@5 does not reach the user.

**Baseline.**

| | fit | held-out |
|---|---|---|
| R@1 | 0.7555 | **0.6725** |
| R@2 | 0.8690 | 0.8122 |
| R@3 | 0.8996 | 0.8515 |
| R@5 | 0.9170 | 0.8865 |
| R@10 | — | 0.9039 |
| session-level S@1 / S@5 | — | 0.8472 / 0.9738 |

The ~0.083 fit/held-out gap is **case mix, not overfitting** (established in an earlier session and
reproduced on every configuration, including models trained on neither split).

---

## 2. Where the losses are

Gold retention per stage, held-out, over the **234 answerable** cases (249 minus 15 abstention):

| stage | gold survives | stage retention | lost here |
|---|---|---|---|
| answerable cases | 234 | — | — |
| ingest + exclusions + scope | 229 | 0.9786 | 5 |
| session pruning | 225 | 0.9825 | 4 |
| slate draw (top-10) | 207 | 0.9200 | 18 |
| **cross-encoder picks rank 1** | **154** | **0.7440** | **53** |

Retentions multiply exactly: `0.9786 × 0.9825 × 0.9200 × 0.7440 = 0.6581 = 154/234`.

**One stage loses 53; the other three combined lose 27.** Perfecting the cross-encoder alone yields
R@1 = 0.8846; perfecting any other single stage yields +0.012 to +0.057.

### 2.1 The failure is one binary decision

Of the 53 in-slate losses, **32 have gold at rank 2**. Labelling every query's (rank-1, rank-2) pair:

| label | n | |
|---|---|---|
| POSITIVE | 26 | rank 2 is gold — a swap **fixes** |
| NEGATIVE | 110 | rank 1 is gold — a swap **breaks** |
| AMBIGUOUS | 93 | both or neither — a swap is a no-op |

**Ceiling on any rank-1/rank-2 tie-break: +26 cases = +0.1135 R@1. Floor: −0.4803.** Rank 1 is
already correct 110 times against 26, so **a reordering rule must be right on >81% of the pairs it
touches** merely to break even. 41% of head decisions cannot move R@1 in either direction.

### 2.2 The near-tie band

Rank-1/rank-2 cross-encoder logit gaps on failures: **minimum 0.0004, median 0.348**. Below a gap of
**0.084** the model is *anti-correlated* with correctness — 6 of 7 decisive flips go the wrong way
(Fisher p = 0.000178). **Blind swapping in that band scores +5 net.** This is the ceiling that every
post-hoc mechanism was measured against, and none exceeded it.

### 2.3 Failures are diffuse, not categorical

Enrichment of the 30 *real* in-slate failures over base rate (13.1%):

| category | fails / queries | rate | enrichment |
|---|---|---|---|
| **single-session-preference** | 8 / 15 | 0.533 | **4.07×** |
| single-session-user | 5 / 32 | 0.156 | 1.19× |
| knowledge-update | 5 / 36 | 0.139 | 1.06× |
| single-session-assistant | 3 / 28 | 0.107 | 0.82× |
| multi-session | 5 / 61 | 0.082 | 0.63× |
| **temporal-reasoning** | 4 / 57 | 0.070 | **0.54×** |

Outside preference, **every category sits between 0.54× and 1.19×**. No question-type-shaped fix
captures the bulk. Notably temporal-reasoning is the cross-encoder's *best* category — deictic
questions fail at the **slate** stage (33% of ABSENT cases carry a deictic) rather than at ranking.

### 2.4 Label artifacts contaminate the denominator in both directions

- **9 of 56 fit failures put a turn *stating the gold answer* at rank 1** but unflagged in the
  corpus. Verified by answer-string containment; 6 under a strict rule, 9 under a loose one.
- Conversely, the published R@1 uses **229** as its denominator, silently excluding the 5 answerable
  cases where gold never reached the scored set. On a 234 basis, R@1 is **0.6581**.
- Duplication is *not* a general corpus property: probing 447 flagged golds against every unflagged
  turn in their case gives **0 at Jaccard ≥ 0.9, 2 at ≥ 0.8**.

**The effective ceiling is therefore ~0.96, not 1.00**, and any promotion threshold is being read
against a denominator uncertain by a couple of points in both directions.

---

## 3. Methodology

**Pre-registration.** Bands, predictions and kill conditions were committed to git **before** any
number existed (`4373111`). Promotion floor: **+0.02 over fit R@1**, reused verbatim from a prior
session so it could not be chosen to fit the result.

**Instrument gate.** Every tool refuses to emit unless it reproduces the published fit R@1 of
**0.7555 exactly**. A reconstruction of a five-level ranking key has at least four ways to be subtly
wrong, and each yields a plausible number. Negative controls were built for the gate itself: the
cue-only ordering (0.5633) must be *refused*.

**Scoring discipline.** All results are reported as **flips gained vs flips lost**, never as
correlation, AUC, or mean-score improvement. Justification: three features with *better AUC* than
the incumbent were all *worse at the head*. Overall discrimination and head discrimination are
different quantities on this corpus.

**The correct-case control.** The 173 solved cases were emitted with identical features so every
hypothesis is testable as failures-vs-successes. **This control killed 9 of 10 hypotheses**, several
of which had strong one-sided statistics.

**The above-band test.** Every mechanism was scored separately on pairs where the cross-encoder gap
exceeds 0.084, because a rule confined to the near-tie band is indistinguishable from a coin flip.

**Sign controls.** Each feature was also evaluated with its sign inverted. A feature that helps in
both directions is measuring nothing.

**Held-out discipline.** The held-out split is a consumable. Four reads were spent, each on one
configuration, each recorded with the argument for spending it.

---

## 4. Results by class

### 4.1 Feature-based tie-breaks (all null)

Scored on the head population with a full threshold sweep. Best operating point per feature:

| feature | gained | lost | net | ΔR@1 |
|---|---|---|---|---|
| rerank-gap closeness (blind swap) | 6 | 1 | **+5** | +0.0218 |
| cue z | 2 | 0 | +2 | +0.0087 |
| pre-rerank rank | 2 | 0 | +2 | +0.0087 |
| cue margin | 1 | 0 | +1 | +0.0044 |
| question echo | 0 | 0 | 0 | 0 |
| IDF non-query mass | 0 | 0 | **0** | 0 |
| ln(words) ratio | 0 | 1 | −1 | −0.0044 |

**The best feature is a blind coin flip.** `rerank-gap closeness` is a degenerate always-swap rule
with 7 decisive flips, not a discriminator.

Two-sided tests against the 173 solved cases (Bonferroni-corrected over the 10-predicate family):

| predicate | failures | strict successes | ratio | p |
|---|---|---|---|---|
| **question echo** | 0.375 | 0.109 | **3.44** | **0.0014** ✓ |
| cross-session competitor | 0.482 | 0.345 | 1.40 | 0.955 ✗ |
| length ratio > 1.5 | 0.268 | 0.127 | 2.10 | 0.309 ✗ |
| gold ≤ 35 words | 0.250 | 0.127 | 1.96 | 0.517 ✗ |
| **gold truncated at 256 tok** | 0.107 | 0.109 | **0.98** | 1.000 ✗ |
| winner longer | 0.554 | 0.446 | 1.24 | 1.000 ✗ |
| same role | 0.929 | 0.873 | 1.06 | 1.000 ✗ |

**`question_echo` is the only survivor as a diagnostic — and it reverses as a tie-break.** At τ≥1 it
flips 121 pairs for 10 gained / 73 lost, **net −63**, because *both* rank-1 and rank-2 usually echo
the question. This is the sharpest instance of the head-vs-aggregate divergence: the 41%-vs-16%
statistic is real and useless.

**Also refuted:** global recency prior (~0 net; knowledge-update at 2/10 and temporal at 9/12 cancel
exactly), dense-cosine fusion at rank 2 (**0 flips at every weight α**), numeric answer-type filter
(2 of 56).

**Impossible, not merely ineffective:** per-query score recalibration. R@1 is a within-query ordering
read and any monotone transform is an identity on it. Motivated by the observation that **0 of 229
selected candidates score above the model's own relevance boundary** (median logit −6.99) — a real
observation that governs *coverage*, not R@1.

### 4.2 Model substitution (refuted across a 17× parameter range)

Nine digest-pinned cross-encoders, four architectures, fit split, depth 10, CUDA:

| model | params | R@1 | ms/query |
|---|---|---|---|
| **L-2 fine-tuned** *(incumbent)* | 16M | **0.7555** | 7.0 |
| L-6 fine-tuned | 23M | 0.7467 | 10.4 |
| L-12 | 33M | 0.6201 | 16.4 |
| L-2 un-tuned | 16M | 0.5983 | 6.8 |
| **bge-reranker-base** | **278M** | 0.5895 | 31.7 |
| mxbai-rerank-base | 184M | 0.5677 | 55.8 |
| jina-v1-turbo | 38M | 0.5284 | 10.3 |
| **jina-v2-base** | **278M** | **0.4803** | 33.7 |

**Three models of 184–278M parameters lose to a fine-tuned 16M model by 17–27 points.** Capacity is
refuted across the full admitted range. Domain adaptation dominates: fine-tuning is worth **+0.0699
held-out** on the same architecture.

**Latency is not the constraint.** All thirty cells fit a 300 ms budget on GPU; the best uses 37 ms.
Every prior rejection of a model in this project was made on a **1-thread CPU** number for a **GPU**
deployment target.

### 4.3 Depth (held-out null, and a reproducible trade)

| | before | after |
|---|---|---|
| input recall | 0.9039 | **0.9782** |
| conditional accuracy | 0.7440 | **0.6920** |
| **R@1** | 0.6725 | **0.6769** |

**+0.0044, McNemar 20 gained / 19 lost, p = 1.000.**

This is the **third independent reproduction** of the same trade — depth buys input recall and the
reranker returns it as conditional accuracy:

| | recall gained | conditional accuracy lost |
|---|---|---|
| depth on L-2 (earlier session) | +0.0611 | −0.0374 |
| slate-union rule (earlier session) | +0.0175 | −0.0189 |
| **depth 30 on L-6-ft (here)** | **+0.0743** | **−0.0520** |

**R@1 cannot be bought with recall on this corpus.** Every additional candidate is an additional
distractor at essentially the same rate.

### 4.4 Auxiliary discriminative models (real signal, redundant)

**Three SQuAD-v2 span readers** (mobilebert 25M, tinyroberta 82M, roberta-base 125M). Head: best
passage span minus null span, masked to candidate tokens. All passed discrimination against a
*topical, answer-free* distractor, with exact padding invariance.

| arm | gained | lost | net | R@1 |
|---|---|---|---|---|
| reader re-orders the slate | 17 | 59 | −42 | 0.5721 |
| reader decides top-2 | 14 | 23 | −9 | 0.7162 |
| **gated to gap < 0.084** | **6** | **0** | **+6** | **0.7817** |
| *inverted control* | 0 | 168 | −168 | 0.0218 |

The inverted controls (−42 vs −168) prove the signal is real and correctly signed — **the reader is
simply weaker than the incumbent.** The gated arm cleared the promotion floor at p = 0.031 **and
replicated across all three models**.

**It did not survive a change of base ranker.** Against L-6-ft at depth 30 the same reader at the
same τ reads **1 gained / 4 lost**. The two mechanisms were fixing the same cases; the reader was
substituting for a better reranker, and against one there is nothing left for it to do. The
threshold also failed to transfer — τ = 0.084 was in L-2-ft's logit units on L-2-ft's gap
distribution.

**Ensemble of five cross-encoders** voting on the top-2: best net **+2**; above the near-tie band it
loses **5 gained against 8**. Voters agree with the incumbent 72–81% of the time, and when they
disagree while it is confident, the incumbent is usually right.

### 4.5 Unit and granularity changes (refuted, twice, by the same mechanism)

**Sentence-level MaxP at rerank time**, top-5: pure max **11 gained / 15 lost (−4)**; mean −23; sum
−93. Fusion `whole + 0.5·max` reads +4/−0 — but **all four gains lie below a 0.084 gap, and it fires
6 times above the band with 0 correct.** Banding to top-3 or top-2 gives an identical +4: every gain
is a rank-2→rank-1 promotion, so narrowing removes candidates that never won.

**Proposition-level indexing at retrieval time** — the only change to *what a candidate is*:

| depth | shipped | same BM25, turn-level | same BM25, proposition-level | Δ |
|---|---|---|---|---|
| 5 | 0.8341 | 0.8079 | 0.7205 | **−0.0873** |
| 10 | 0.9214 | 0.8777 | 0.7991 | **−0.0786** |
| 30 | 0.9825 | 0.9563 | 0.9083 | −0.0480 |

Worse at every depth, with the same implementation run both ways as the control. **4,202 propositions
from ~487 turns means 4,202 chances for a distractor to own one lucky unit**, and max-pooling is
maximally exposed to that.

**Both experiments have one mechanism: splitting helps the buried answer and helps the imposter
more.** The dilution that looks like the disease is also the immune system.

### 4.6 Structural / relational features (all refuted)

**Neighbour similarity** (candidate-to-candidate, no query): gold's mean affinity to its neighbours
is **0.1851 against non-gold's 0.1533** — gold is the *consensus*, not the outlier, contradicting the
intuition. On the decisive population it is a coin flip (POSITIVE 0.500, NEGATIVE 0.536); as a swap
rule, net **−4**. Mechanism: session pruning draws the slate from topically coherent sessions, so the
top candidates are gold's own session-mates and gold sits inside the cluster.

**Centroid subtraction** (remove the shared component from the embeddings, compare residuals): raw
dense −43, **centred dense −47**. Removing what candidates share made it *worse* — the shared
direction carries signal.

**Context decay** around the peak-scoring span. Hypothesis: a distractor matches on one echoing span
so widening the window kills the score, while gold sits in supporting context and holds up.
**Measured backwards** — gold decays **10× more** (0.1337 vs 0.0133), because the gold answer is a
narrow span inside a multi-topic turn while the distractor is uniformly on-topic. Inverted, the
feature looked strong: **fit +0.0305, 8 gained / 1 lost, p = 0.039**, clearing the floor and firing
3/1 above the near-tie band. **Held-out: −0.0087.** The gold/non-gold separation shrinks from 3.2× to
1.8× across the split.

**Neighbour turns** — all four adjacent positions, both signs:

| | + (weight 1) | − (sign control) |
|---|---|---|
| prev-1 | −69 | −63 |
| prev-2 (same speaker) | −70 | −68 |
| **next-1 (the reply)** | **−24** | −28 |
| next-2 | −32 | −22 |

**Both signs lose everywhere: no usable signal.** One real detail — `next-1` is the *only* neighbour
where gold scores higher than non-gold (**+0.1495**), the predicted direction for "an assistant reply
restates what the user just said." At ~1% of the score scale it is two orders of magnitude too small
to act on. Exhaustive: the corpus has two roles only (no system turns) and sessions strictly
alternate, verified **32,324/32,324**.

### 4.7 Retraining (the largest fit gain, and the largest collapse)

Four arms, ablating negatives against objective, fit split, all from an **un-tuned** base checkpoint:

| arm | negatives | loss | fit R@1 | vs shipped | McNemar |
|---|---|---|---|---|---|
| A *(control)* | original | MarginMSE | 0.7555 | +0.0000 | 0/0 — reproduces exactly, 0 discordant |
| **B** | **new** | MarginMSE | **0.8253** | **+0.0698** | **18/2, p = 0.0004** |
| C | original | BCE | 0.7031 | −0.0524 | 8/20, p = 0.036 |
| D | new | BCE | 0.7293 | −0.0262 | 11/17, p = 0.34 |

**The negatives moved it; the objective hurt it.** The motivating hypothesis for BCE — that
hard-label MarginMSE caps separation because the loss reaches zero once the gap hits a fixed target
— is **refuted**.

The negatives addressed a gap verified in source: the original miner never leaves the gold turn's
session (`if sid not in gold_sessions: continue`), so **0 of 6,898 training pairs teach the model to
reject a wrong conversation**, while 14 of 30 real failures place rank 1 in exactly that. All three
new classes contribute; removing `deployed_top_k` costs the most (0.8253 → 0.7511, *below* shipped).

**Held-out: 0.6812, +0.0087, McNemar 10/8, p = 0.815.**

| | fit | held-out | gap |
|---|---|---|---|
| shipped | 0.7555 | 0.6725 | 0.083 |
| **arm B** | 0.8253 | 0.6812 | **0.144** |

**The generalisation gap widened by 1.7×** — overfitting, measured rather than asserted. Cause:
`deployed_top_k` negatives are *query-specific by construction* ("the turns that beat gold on **these**
queries"), so the model memorised turns rather than the pattern.

An unprompted within-fit contamination control (conversation-level holdout) read **+0.0638 on 47
queries** and predicted nothing — that is 3 cases at p = 0.25.

### 4.8 Architecture: joint pairwise encoding (the only above-band success on fit)

A duoBERT-style model reading **both candidates in one forward pass**: `[CLS] q [SEP] A [SEP] B [SEP]`,
seq 384, base L-6, trained on pattern-based negatives with **both orderings** presented.

Motivation: the incumbent is pointwise and emits one scalar per candidate. Attention runs within a
row, so even a batched `[10,256]` forward carries no cross-candidate information. The model has no
internal representation for *"B answers and A restates"*.

Token budget measured: query + 2 candidates is 156 word pieces at the median; **89.1% fit in 256,
93.4% in 384.**

| arm | gained | lost | net | fit R@1 | above 0.084 |
|---|---|---|---|---|---|
| duo tournament (symmetrised) | 24 | 12 | +12 | 0.8079 | 17 / 12 |
| ce + 0.25×duo | 9 | 0 | +9 | 0.7948 | **5 / 0** |
| **ce + 2.0×duo** | 21 | 6 | **+15** | **0.8210** | **15 / 6** |

**This was the first and only mechanism to make correct calls above the near-tie band at scale.**

**Held-out:** the tournament reads **23 gained / 22 lost**, and above the band **20 / 20 — an exact
coin flip**. Best cell +0.0044.

A registered symmetry control failed on both splits: `P(A>B) + P(B>A) = 1.13 ± 0.48`, indicating
order-dependent instability. This was declared in advance to render the accuracy numbers
uninterpretable, and the held-out result is consistent with it.

### 4.9 Generative selection (out of scope, then tested)

Small LLMs given the query and top-3, asked to name the answer-bearing turn, greedy at temperature 0.

- **qwen2.5:0.5b-instruct** — R@1 0.2750, and **it never once selected option 1** across 40 queries
  where option 1 is correct ~75% of the time. Degenerate; caught immediately by reporting the pick
  distribution.
- **qwen3.5:4b** — non-degenerate (picks 24/6/10), but **net −1** at n=40.

**A latency measurement error worth recording.** Wall-clock read 2,222 ms/query, apparently 7.4× over
budget. A control with a **one-token prompt took the same 2,300 ms**: the cost was Ollama's constant
per-request overhead, not the model. Actual model cost is **22 ms (0.5B) to 147 ms (4B)** — all
within a 300 ms budget. The first reading measured the harness and would have been reported as a
property of the approach.

---

## 5. Cross-cutting findings

### 5.1 A structural property of the corpus explains most failures

> **Gold turns are multi-topic with a narrow answer. Distractors are single-topic and coherent.**

Canonical example. Question: *"I mentioned cooking something for my friend a couple of days ago.
What was it?"* Answer: *a chocolate cake*.

Gold turn: *"I'm excited to try making **croissants** again, and I'll also make some **banana
bread**… I made a batch with **walnuts**… **By the way, I just baked a chocolate cake for my friend's
birthday party**… any tips for **banana bread**?"*

Rank-1 winner: *"I'm thinking of getting into **cooking**…"* — echoing the question's own word, one
coherent thought.

**This predicts the sign of most mechanisms tested:**

| mechanism family | prediction | observed |
|---|---|---|
| rewards sustained topical support | favours distractor | decay ✓, neighbour affinity ✓, centroid ✓, predecessor ✓ |
| isolates a peak | surfaces distractor's echo too | MaxP ✓, proposition indexing ✓ |

**The dilution that appears to be the disease is also the immune system.**

### 5.2 The near-tie signature

Mechanisms that perturb a pointwise score gain 4–6 with ~0 losses **entirely inside gaps below
0.084**, and none fires correctly outside it. Three unrelated mechanisms — a span-extraction model, a
sentence splitter, and a coin flip — converge on the same handful of cases: the six fixes shared
between the reader and MaxP have gaps of 0.0099–0.0838, **all below the threshold**.

**A post-hoc result measured on one base ranker is not a result until a second base ranker
reproduces it.** Demonstrated: the reader's +6/−0 became 1/−4.

### 5.3 Threshold selection overfits at n=229

| mechanism | trained on fit? | fit | held-out |
|---|---|---|---|
| depth 30 | no | +0.0174 | +0.0044 |
| retrain arm B | **yes** | +0.0698 | +0.0087 |
| joint pairwise encoder | **yes** | +0.0655 | +0.0044 |
| **context decay** | **NO** | **+0.0305** | **−0.0087** |

**Context decay was never trained.** Only its λ was selected on fit — one hyperparameter from ten
candidate values — and it still reversed sign. **A rule with a tunable knob is suspect on this
corpus regardless of whether a model was fitted.**

Corollary: **a held-apart subset of the same split is not a held-out split.** Arm B's within-fit,
conversation-level control predicted +0.0638 and delivered +0.0087; the corpus, the mining procedure
and the model generating the negatives were all shared.

### 5.4 Aggregate statistics do not survive to the head

Three features with better AUC than the incumbent were all worse at the head. `question_echo` is
3.44× enriched in failures and **reverses** as a tie-break. Neighbour affinity separates gold from
non-gold by +0.0318 overall and is a coin flip on the decisive pairs.

**Any feature must be fit on the rank-1-vs-rank-2 distribution and scored on flips**, never on a
global metric.

### 5.5 The metric is not what the field reports

Three published LongMemEval systems report **session-level Recall@5**: 96.6% and 95.2%, both
LLM-free, neither with a held-out split. The system here reads **0.9738 shipped / 0.9869 on its dense
cue alone** on that metric. Both source documents state explicitly that this is not the benchmark's
official metric, which is QA accuracy under an LLM judge.

**No system in that comparison set, including this one, reports the official metric.** Session-level
recall is near-saturated — a naive baseline reaches 96.6% — and turn-level R@1 out of ~490 candidates
is a substantially harder question. The benchmark's own authors measure turn granularity below
session granularity by ~9 points at R@10.

---

## 6. Threats to validity

1. **Single corpus.** Every finding is scoped to LongMemEval-S. The unifying property in §5.1 is a
   property of *this* corpus's construction (haystacks assembled from distinct real sessions) and may
   not hold on real user history, where the same thing genuinely does get said repeatedly.
2. **Synthetic timestamps.** Turns within a session are one second apart (`session_at + index×1000`),
   so any temporal mechanism is evaluated on a degenerate distribution.
3. **Label noise, both directions.** ~9 of 56 failures are unflagged answer-bearing turns; the
   published denominator excludes 5 unrecoverable cases. Effective ceiling ~0.96.
4. **n = 229 per split.** Wilson half-width at p = 0.67 is ±0.058, so unpaired reads of R@1 cannot
   resolve effects smaller than ~13 cases. All primary tests are paired (McNemar exact) for this
   reason.
5. **Fine-tune contamination.** The shipped reranker trained on the fit split, so all fit-split
   comparisons involving it are optimistic. Held-out figures are the only capability claims.
6. **One generator, one judge.** QA accuracy figures are pilot-only (n=20, a local 9B model, lexical
   grading) and are not comparable to published results.

---

## 7. What remains untested

Everything still open is **outside the ranking stage**:

1. **QA accuracy** — the benchmark's official metric and this milestone's acceptance criterion, never
   measured. The recorded `answer_accuracy 0.0` is two absences stacked: no generator is wired, and
   the historical gate admitted nothing. A pilot (n=20) reads **none 0.00 / gold 0.65 / k5 0.55 /
   k10 0.50 / k1 0.25**. The clean 0.00 floor is the only part solid at that sample size, and it
   establishes that the model guesses nothing without memories.
2. **The admission rule.** The product injects **one** memory. The pilot reads **k1 0.25 against k5
   0.55** — a larger effect than any ranking work attempted here, obtainable by a one-line change,
   and traded against token budget, injection precision, and stale-fact harm.
3. **Supersession detection.** An oracle marking stale knowledge-update beliefs superseded is worth
   **+0.1666 on knowledge-update R@1_current** and a **71% cut in harmful injections**. The exclusion
   that would consume it is live, correct and unit-tested; it receives no edges because the only
   writer is a near-duplicate merge firing on 0.0086% of pairs. Blocked on entity identity.

**Within ranking, the honest conclusion is that the space is closed.** The ceiling on post-hoc
mechanisms is +5 cases, set by a coin flip; capacity is refuted across 17×; better negatives, a
better objective, and a joint-encoding architecture each produced a large fit gain and a held-out
null. The binding constraint is labelled data — approximately **38 informative fit failures** — and
no architectural change observed here substitutes for it.
