# M0c Session A — head separability, and then the metric itself

**R@1 is 0.6725 on held-out. It was 0.6725 before this session and nothing shipped.** Both named
candidates were built and measured, four learned architectures were cross-validated, a seventh
mechanism was found mid-session and taken to a held-out read, and every one of them is a null or a
loss. The session's output is measurement, not a model.

**Then the question changed, and Part 6 is the largest finding here.** R@1 treats every failure as
equal; §5.7 does not. Measuring the difference showed that **R@1 counts the superseded fact as a
hit** — the metric three sessions have optimized is inflated by **+0.0437** overall and by **28
points on knowledge-update**, the category §5.7 was written about. Read Part 6 first.

| | |
|---|---|
| **0. R@1 HAS BEEN COUNTING THE HARMFUL CASE AS A SUCCESS** | LongMemEval marks *both* the stale and the current turn `has_answer`. Held-out R@1 0.6725 → **0.6288** counting only the current value; on knowledge-update 0.7222 → **0.4444**, with **10 of 26 apparent hits being the stale fact**. See Part 6 and `docs/design/HARM-WEIGHTED-PRECISION.md`. |
| **1. K1's interval reading is arithmetically unreachable at the declared operating point** | A **perfect** selector — 23 of 23 — has a Clopper-Pearson lower bound of **0.8518** at 10% coverage on n=229. No mechanism clears 0.95 there, ever. This retires a target, in the same way ADR-016 retired the 0.3739 ceiling. |
| **2. Candidate A — a relevance-fitted confidence signal — is NEGATIVE** | No query-time feature beats the rerank margin at the head, and the features with *better overall AUC are worse at the head*. |
| **3. Candidate B — set-wise / listwise scoring — is a NULL across four architectures** | +0.0044, −0.0131, +0.0000, +0.0000 out-of-fold. From a 384-d pooled bottleneck to full token-level cross-attention. |
| **4. Slate construction gained +0.0087 on fit and lost −0.0044 on held-out** | The Session J addendum pattern, repeated exactly. |
| **5. The comparison that mattered was a metric mismatch** | Marlowe measures **0.9738 session-level R@5**. Systems publishing "96.6%" on LongMemEval are reporting that quantity, not turn-level R@1. |
| **6. The real failure mode is now characterised** | Two **user** turns in the same session, several exchanges apart. Not user-vs-assistant, which the Session J fine-tune already fixed. |

---

## Part 0 — R0, and why it is first

`tools/reach_head_r0_attainability.py`. Pure arithmetic, no model, no corpus.

K1's reading rule is pinned in `runs/session-j/PREREGISTRATION.json`: *"'Reaches 0.95' means the
INTERVAL, not the point estimate."* At coverage `c` the injected set has `n_c = round(c·n)`
members, and the best any mechanism can do is `k = n_c`. The Clopper-Pearson lower bound at `k = n`
is `0.025^(1/n)` — **a function of `n_c` alone.**

| coverage | n_c | best possible precision | **CI95 low at perfection** | clears 0.95? |
|---|---|---|---|---|
| **0.10** | **23** | 1.0000 | **0.8518** | **no** |
| 0.15 | 34 | 1.0000 | 0.8972 | no |
| 0.25 | 57 | 1.0000 | 0.9373 | no |
| 0.35 | 80 | 1.0000 | 0.9549 | yes |

**Clearing the threshold by interval needs n_c ≥ 72 with zero errors, or n_c ≥ 110 with one.**
The shipped head errs on 2 of 23.

**This is not a statement about retrieval.** It says the criterion's interval reading and its
10%-coverage reading cannot both be satisfied on a 229-query split. A session aiming at the
interval must move the point estimate and report the interval honestly, or raise n. Both are
stated; neither was quietly chosen. **No band was registered on a quantity the split cannot
express** — registering one would have been ADR-010's error committed against the criterion
instead of against a shape.

---

## Part 1 — Candidate A is negative, and the way it fails is the finding

`tools/reach_head_r1_confidence.py`, fit split, 18 query-time features, ADR-017 compliant (the
target is the binary gold-hit label; nothing is fitted against the rerank score).

| feature | AUC | precision@10% | swaps vs margin |
|---|---|---|---|
| **margin (incumbent)** | 0.6677 | **0.9130** (21/23) | — |
| margin_1_3 | **0.7137** | 0.8696 (20/23) | 9 |
| softmax_p1 | 0.7134 | 0.8696 (20/23) | 8 |
| top1_score | 0.7008 | 0.8696 (20/23) | 14 |
| slate_entropy (neg) | 0.6360 | 0.9130 (21/23) | 12 |

**Nothing beats the margin at the head, and the three features with better AUC are all worse
there.** Overall discrimination and head discrimination are different quantities on this corpus.
That is head separability stated precisely rather than assumed, and it is why "fit a better
confidence signal" was the wrong shape.

**A test-selection note.** The selector contrast is not a McNemar contrast — the two arms inject
*different* queries, so there are no paired per-query outcomes. The applicable test is Fisher's
exact on the 2×2 of (arm-only vs margin-only) × (correct vs wrong), whose smallest attainable
two-sided p is `2/C(2m,m)`, giving **m ≥ 4** for α = 0.05. Recorded because reaching for McNemar
here would have produced a confident number from the wrong test.

---

## Part 2 — Candidate B: reachable on paper, null in fact

### The reach check was positive, and that is why it was worth building

`tools/reach_head_r2_listwise.py`, held-out: **53 recoverable failures** (gold in the slate, rank 1
wrong). **60% have gold at rank 2**, 77% at rank ≤ 3. The logit gap between the wrong rank 1 and
the gold:

| gap ≤ | queries | R@1 if all flipped |
|---|---|---|
| 0.25 | 15 (28%) | +0.0655 |
| 0.50 | 31 (58%) | +0.1354 |
| **1.00** | **46 (87%)** | **+0.2009** |

Median gap **0.435 logits**. These are near-ties, not confident errors. ADR-010 satisfied on
measurement.

### Then all four architectures landed on the shipped number

Nested 5-fold CV **by conversation** over the fit split — out-of-fold predictions for all 229
queries, so no query is ever scored by a model that saw it.

| arm | what it sees | out-of-fold R@1 | delta | discordant | α attainable? |
|---|---|---|---|---|---|
| **S1** set-wise head | frozen 384-d pooled vector per candidate | 0.7598 | +0.0044 | 1 | no |
| **L1** listwise fine-tune | pairs, independently, listwise objective | 0.7424 | **−0.0131** | 13 | **yes**, p = 0.5811 |
| **LS1** encoder + head jointly | both | 0.7555 | +0.0000 | 4 | no |
| **S2** global cross-encoder | `[CLS] Q [SEP] T₁…T₄`, token-level cross-talk, seq 512 | 0.7555 | +0.0000 | 0 | no |

**L1 is a null with power** and slightly negative. S2 — the arm with no information bottleneck at
all — changed top-1 on 2 of 229 queries.

**The diagnosis is the data, not the architecture.** The fit split has 229 queries of which **38
are recoverable failures**, on a reranker Session J already fine-tuned on those same queries. Four
architectures spanning the full range of joint-observation capacity is not four coincidences.

### Two instrument corrections made along the way, both recorded

1. **The single 46-case validation slice was not a usable instrument.** It read S1 at 0.8261 and L1
   at 0.8043 — 38 against 37 queries. ADR-012's rule is that a band narrower than the instrument's
   resolution cannot be read, and one case in 46 is that. Replacing it with 5-fold CV moved S1's
   apparent gain from **+0.0435 to +0.0044**. The first number was noise and would have been
   reported as a result.
2. **A joint-structure read was a null instrument by construction.** It compared rank 1 to the gold
   in both the failure and success groups — but on successes the gold *is* rank 1, so "same
   session" was 1.0000 and "opposite role" 0.0000 mechanically. Changed to rank1-vs-rank2 on the
   success side before any number was believed. Corrected, the enrichment is 1.3× on held-out, not
   the dramatic effect the broken version implied.

### Two properties built in rather than hoped for

- **Every arm emits `shipped_logit + delta` with a zero-initialised head**, so an untrained arm
  reproduces the shipped ranking *exactly* (0.7555, asserted in code). Every reported movement is
  trained movement, not a randomly initialised scorer shuffling near-ties.
- **S1's permutation equivariance measured 0.000002**, not argued from the absence of positional
  encoding.

---

## Part 3 — the slate arm: +0.0087 on fit, −0.0044 on held-out

Found by R3 *after* the four registered arms failed, so it carries
`PREREGISTRATION-AMENDMENT-1.json` with its own floor and prediction written before the read.

**R3's finding was real:** the shipped depth-10 slate is not the best way to choose which ten
candidates the cross-encoder sees. Held-out R@10 is 0.9039 for the gate order against **0.9258 for
the dense cue alone** — the admission rule loses recall against one of its own inputs.

**But the direction flipped between splits**, which is exactly why selection was made on fit:
dense-ordered is *worse* than gate on fit (0.9083 vs 0.9214) and better on held-out. The union
family was consistent on both, and the pre-written tie-break ("ties within 0.005 broken by lowest
added latency") selected `gate8 ∪ dense8` at depth 10, zero added cost.

| | fit | held-out |
|---|---|---|
| control `gate top10` | 0.7555 ✓ reproduces | 0.6725 ✓ reproduces |
| **`gate8 ∪ dense8`** | **0.7642 (+0.0087)** | **0.6681 (−0.0044)** |
| input recall | 0.9214 → 0.9345 | 0.9039 → **0.9214** |
| conditional accuracy | 0.8199 → 0.8178 | 0.7440 → **0.7251** |

**The mechanism worked and the metric did not.** Input recall rose by +0.0175 on held-out and
conditional accuracy fell by −0.0189 to meet it. The registered directional prediction — *added
candidates are also added distractors* — held, and came in slightly worse than its band.

No rule in the sweep exceeded 0.6725 on held-out. **The best available outcome was "no change".**

---

## Part 4 — the comparison that prompted this, resolved

A published system reporting **96.6%** on LongMemEval was raised as a target. It reports
**session-level Recall@5** — is the gold *session* among the top 5 *sessions*. Marlowe reports
**turn-level Recall@1** — is the single top-ranked *turn* gold, out of ~490 candidates.

Measured on Marlowe, held-out, same corpus:

| ordering | S@1 | S@3 | **S@5** | S@10 |
|---|---|---|---|---|
| gate (shipped slate) | 0.8472 | 0.9214 | **0.9738** | 0.9913 |
| dense alone | 0.8690 | 0.9738 | **0.9869** | 0.9913 |

**Marlowe is at 0.9738 shipped and 0.9869 on its dense cue alone, against a published 96.6% raw /
98.4% tuned.** We are not behind on that metric; we report a much harder one. Quoting one against
the other is the category error this project keeps a list of, and this is the eleventh entry's
shape: *a number that answers a question adjacent to the one being asked.*

---

## Part 5 — turn-pair chunking, and a stale rationale in STATE.md

`tools/reach_head_r4_turnpair.py`. STATE.md carries turn-pair chunking as "the cheapest structural
idea", justified by "87.7% of gold is user-authored; the distractors that beat it are 47.1%
assistant-authored".

**The first half holds — 89.4% of held-out gold is user-authored. The second half is stale.**

| | fit | held-out |
|---|---|---|
| gold is the other half of rank-1's own exchange | 2 of 38 | 3 of 53 |
| R@1 ceiling if exactly those are fixed | +0.0087 | +0.0131 |
| **rank 1 on failures is assistant-authored** | **2/38 (5.3%)** | **4/53 (7.5%)** |

The Session J fine-tune already fixed the user/assistant confusion, so the failure pairing targets
has largely gone. And the same-session gold-to-rank-1 turn gaps are **−10, −8, −6, −4, −2** — all
even, therefore **same role**.

> **The real failure is discriminating between two USER turns in the same conversation, several
> exchanges apart, both topically on target.** Pairing does not touch it. Neither does anything
> that keys on role or adjacency.

---

## What this session did not do

- **It shipped nothing.** Nothing cleared the pre-registered +0.02 floor, so by the registration
  nothing ships. `crates/marlowe-memory` is unchanged; there is no Rust diff.
- **It did not lower a floor to match a result.** The +0.02 floor stands and the arms are reported
  as failing it.
- **It did not touch `eval/`** (72 passing, no diff), the frozen gate, `THRESHOLD = 0.95`,
  `MAX_SEQ_LEN`, or anything owned by the parallel M2 session.

## A disclosure

`tools/reach_head_r3_slate.py` was run on the **held-out** split before it was run on fit. It
measures recall properties of the already-published configuration and fits no parameter, but it
was seen. The selection was made entirely on fit by a pre-written tie-break, and the fit and
held-out reads *disagree in direction* on the strongest single rule — which is itself the evidence
that selecting on the held-out read would have been selecting on noise. Residual risk is non-zero
and is recorded rather than absorbed.

## Standing checks

| check | result |
|---|---|
| offline reconstruction reproduces the binary | **PASS, EXACT** — fit 0.7555, held-out 0.6725 |
| torch reference vs shipped ONNX logits | **PASS** — max 1.0e-5, **top-1 229/229** |
| control reproduces the published R@1 in every sweep | **PASS**, enforced in code (the tool refuses to write) |
| S1 permutation equivariance | **PASS** — 0.000002 |
| untrained arms reproduce the shipped ranking exactly | **PASS**, asserted in code |
| `cd eval && pytest` | **72 passing**, `eval/` has no diff |
| `cargo test -p marlowe-memory` | **10 passing**, no Rust changed |

**A defect this session caught before it did damage.** The first encode pass used
`PreTrainedTokenizerFast` over the shipped `tokenizer.json` instead of the raw
`tokenizers.Tokenizer` the scored path uses. Same file, same vocabulary — **logits up to 3.56
apart**, and entirely plausible-looking. Every set-wise head would have been trained against a
scorer that does not exist. It was caught only because the encoder asserts against the cached ONNX
logits before writing. Twelfth instance of two-sides-silently-disagree.

---

## What a later session inherits

1. **Do not spend a session on the 10%-coverage interval.** R0 closes it arithmetically.
2. **Do not spend a session re-scoring the depth-10 slate.** Four architectures, one honest
   instrument, all null. The binding resource is labelled data: 38 informative fit failures.
3. **The failure mode is same-role, same-session, multi-exchange separation.** Any mechanism keying
   on role, adjacency, or length is aimed at a failure the Session J fine-tune already removed.
4. **Input recall is the ceiling and it is loose.** Held-out gate top-10 is 0.9039 against dense
   alone at 0.9258 and all-survivors at 0.9825. Raising it did not help *with this reranker*,
   because conditional accuracy fell to meet it — but the ceiling is where the remaining 0.2314
   lives, and no reranking work can reach past it.
5. **Batch invariance was measured at 0.000000 on the shipped f32 graph in Session K.** Batching
   the depth-10 rerank is available and would buy latency headroom, which is the only currency that
   buys depth. Untested.

---

# Part 6 — R@1 was the wrong number, and here is how wrong

**Added after the sections above, at the human's direction.** The observation: §5.7's argument is
about *harm*, not accuracy, and every arm since Session H has optimized R@1, which treats all
failures as equal. The criticism lands, and measuring it changes what this session concludes.

Full record: `docs/design/HARM-WEIGHTED-PRECISION.md`. Artifacts:
`runs/session-m0c/reach-r5-harm-classes.json`, `harm-weighted-curve.json`,
`harm-weighted-curve-fit.json`.

## 6.1 The structural fact, and it needs no new labels

LongMemEval's knowledge-update cases carry **exactly two answer sessions** (78 of 78). One states an
old value; the other states the value `answer` holds. **Both are marked `has_answer: true`**, and
`longmemeval.py:144` puts every such turn into `gold_turn_ids`.

> **Retrieving the stale fact scores as an R@1 hit.** The harmful case has been counted as a success
> in every R@1 this project has published, including this session's.

**ADR-010 reachability: PASS.** 13 harmful rank-1 injections on held-out, 17 on fit, against a floor
of 10. Of those, 10 (held-out) and 15 (fit) are gold-marked stale turns R@1 scores as correct.

## 6.2 The classifier does not use an ordering, and that was a correction mid-flight

A first version ranked the two answer sessions by `haystack_dates` and called the later one current.
Its own diagnostic killed it: date order agreed with the `_N` suffix on only **166 of 250**
two-answer-session cases, and this corpus dates 76 of 500 cases *after* their own question. Both
orderings are proxies. The quantity wanted is *which gold turn states the value the answer holds*,
which is directly checkable. Measured: the answer-bearing session is the later one by suffix in
**86.4%** and by date in **84.7%** of the 59 decisive knowledge-update cases. Neither is used.
11 cases fall back to suffix order and are flagged; held-out harmful goes 13 → 12 without them.

## 6.3 The answer to the question as asked

**Of the injections that are not the current value:**

| | held-out | fit |
|---|---|---|
| **harmful** (superseded + stale_session) | **13 of 85 — 15.3%** | 17 of 71 — 23.9% |
| merely useless (on_topic_wrong + irrelevant) | 72 of 85 — 84.7% | 54 of 71 — 76.1% |

**Roughly five in six wrong injections cost tokens rather than corrupt reasoning. §5.7's premise is
weaker than assumed on the failure side**, and that is a real finding about the design.

## 6.4 But R@1 is inflated, and worst exactly where §5.7 reads

| | held-out | fit |
|---|---|---|
| R@1 as published | 0.6725 | 0.7555 |
| **R@1 counting only the current value** | **0.6288** | **0.6900** |
| inflation | **+0.0437** | +0.0655 |

**Knowledge-update alone (n = 36 per split):**

| | held-out | fit |
|---|---|---|
| R@1 as published | 0.7222 | 0.7222 |
| **R@1 current only** | **0.4444** | **0.3056** |
| **stale hits among apparent hits** | **10 of 26 (38.5%)** | **15 of 26 (57.7%)** |

**At the declared operating point the two precisions are identical** — published 0.9130, current
0.9130, harm 0 of 23, on both splits. `PRECISION-COVERAGE.md` needs no correction at 10% coverage
and a −0.0437 correction at 100%.

## 6.5 Harm is zero at the head for the wrong reason

The naive reading is "abstention suppresses harm". **That is a proxy conclusion and it is wrong.**

| | fit | held-out |
|---|---|---|
| median margin, knowledge-update vs all | 0.3548 vs 0.4254 | **0.2782 vs 0.4020** |
| knowledge-update share of the top-10% slice | 4.3% (1/23) | **0.0% (0/23)** |
| base rate | 15.7% | 15.7% |
| **within** knowledge-update, harm top-half vs bottom-half by margin | 0.389 vs 0.556 | **0.444 vs 0.278** |

**The head is harm-free because it contains almost no knowledge-update queries**, not because the
confidence signal discriminates harm — and *within* knowledge-update the margin's relationship to
harm **flips sign between splits**. The protection is a category-exclusion side effect and it is
fragile: anything raising coverage, or improving confidence on knowledge-update, removes it silently.
`0.0000` on n = 23 has a Clopper-Pearson upper bound of **0.1482** and is not evidence of zero.

## 6.6 Does the machinery already fix it? No — live and blind

**The §4.3 exclusion exists and is correct.** `entry.rs:124` — `superseded_by.is_none()` is exclusion
(2) of `is_injection_candidate`, called at `retrieve.rs:328`, unit-tested per exclusion. **Not a
wiring defect.**

**The trigger is missing.** The only writer of `superseded_by` is consolidation's near-duplicate
merge at `consolidate.rs:697`, thresholded at **cosine ≥ 0.98**. `ingest.rs:142` hardcodes `None`;
§4.6's `IngestRequest` has no supersession field and forbids extras, so **a caller cannot assert it**;
`store.rs:133` defers the contradiction detector explicitly. ADR-012 already measured pairs at
≥ 0.98 as **0.0086%** of 30,587,870 and recorded why — LongMemEval distractors are "topically related
rather than textually duplicated".

> Neither "supersession is not detected" nor "the exclusion is not firing" is quite right. The filter
> fires correctly on every edge it is given — ~1.19% of the pool — and nothing gives it the edges
> that matter. **A missing component, not a tuning opportunity, and it is the component §5.7's
> argument assumes exists.**

## 6.7 What changes as a result

1. **`R@1_current` should be reported beside R@1 from now on.** A configuration that trades a
   merely-useless injection for a superseded one is a regression under §5.7 and invisible under R@1.
   This session's own slate arm was evaluated only on R@1 and that was insufficient.
2. **The three sessions of R@1 optimization were measuring a number inflated by 4.4 points**, and by
   28 points on knowledge-update. None of the conclusions reverse — the arms were null against the
   inflated number and are null against the corrected one — but the baseline was never what it said.
3. **The named next lever is a contradiction detector**, not a ranking mechanism. It is the one
   thing that would let a live, correct, already-wired exclusion do the job §5.7 assumes it does.
