# M0b Session G — the query side, measured

**Pre-registration committed at `db114e8`, before any pool was reconstructed.** Every band, gate and
verdict below was fixed in that file first. Nothing shipped: no gate refit, no artifact minted, the
binary untouched.

---

## The finding: the problem is not the one four sessions have been attacking

Session-level pruning at N=3 keeps **10.3%** of the candidate pool at **98.25%** gold retention. The
registered failure decomposition splits that residual:

| | cases | |
|---|---|---|
| **solved** — gold is top-1 under at least one cue | **148** | |
| **right session, wrong rank** — gold's session survived, gold is not top-1 | **77** | ← the problem |
| **wrong session** — gold's session did not survive the cut | **4** | |

**19.2 to 1.** Selecting which of ~48 sessions holds the answer is close to solved by max-aggregated
cue scores alone. What remains is ranking **inside a correct ~47-turn session**.

Sessions D, E and F attacked arbitration over a ~487-turn pool. That is a different problem, and it
is the one with the 0.6435 either-cue oracle cap on it. Ranking 47 topically coherent turns is not
obviously subject to the same bound — but Session G did not measure it, and the question is
**registered forward, unmeasured**, in `REGISTERED-QUESTION-in-session-rerank.json`.

A better session scorer is worth approximately nothing. Four cases.

---

## The pre-registration lesson: a read that could not vary

**Arm 1's registered primary read was vacuous, and the registration did not catch it.**

`oracle@1` came back **+0.0000 at every N, in both pruning modes**. That is not a null result. Under
max aggregation a session's score *is* its best turn's score, so the globally top-scoring turn always
lies in the top-scoring session, and keeping the top N≥1 sessions cannot displace it. Measured rather
than argued: **458/458 case-cue pairs, zero violations** (`arm1-pruning.json → structural_check`).

The pre-registration did the ADR-010 reach check correctly — it verified that **the shape can move
the metric**, and pruning genuinely can, by removing a distractor ranked above gold. What it did not
check is that **the specific read, under the specific aggregation rule, can vary at all.** Those are
different questions and only the first was asked.

> **The generalized lesson, for every future registration: verify that the READ can vary, not only
> that the SHAPE can move the metric.** A reach check on the mechanism does not transfer to a reach
> check on the measurement.

This sits beside ADR-011's record of Session D: a registered quantity that cannot move produces a
clean, confident, meaningless number, and nothing downstream looks wrong.

**Second miss, disclosed:** the registration fixed N and every read but **not the session-scoring
rule**, found while implementing after the file was committed. Handled by declaring three variants
before running any of them and reporting all. Because the rule was unregistered, **the
best-performing variant is not quotable as the arm's result** — the primary is the parameter-free
one declared first.

| variant | pool | gold retention | oracle@1 | Δ |
|---|---|---|---|---|
| **max / union (PRIMARY)** N=1 | 0.0329 | 0.9214 | 0.6463 | +0.0000 *(vacuous)* |
| **max / union (PRIMARY)** N=3 | 0.1027 | 0.9825 | 0.6463 | +0.0000 *(vacuous)* |
| **max / union (PRIMARY)** N=5 | 0.1790 | 0.9869 | 0.6463 | +0.0000 *(vacuous)* |
| max / per-cue N=3 | 0.0710 | 0.9825 | 0.6463 | +0.0000 *(vacuous)* |
| mean-top3 / union N=1 | 0.0312 | 0.8996 | 0.5764 | −0.0699 |
| mean-top3 / union N=3 | 0.1005 | 0.9825 | 0.6463 | +0.0000 |

Only aggregations that *can* displace the argmax move the number, and the one tested moved it
**down**.

---

## Arm 3 refutes its own premise

The brief specified: *"Embed a plausible answer rather than the question. Answers resemble the turns
being searched; questions do not."*

No LLM was available, so the **ceiling** was measured instead — embed the *released gold answer*. If
the true answer does not beat the question, no generated approximation can, because the generator's
best case is to reproduce it. This is a stronger reachability statement than any one generator's
output, and it uses gold labels, so it is an upper bound and **never a shippable number**.

| variant | oracle@1 | Δ | gained | lost | McNemar p | verdict |
|---|---|---|---|---|---|---|
| baseline | 0.6463 | — | — | — | — | — |
| **oracle answer alone** (as specified) | 0.4236 | **−0.2227** | 33 | 84 | 0.0000 | **HARMFUL** |
| oracle question **+** answer | 0.7380 | +0.0917 | 27 | 6 | 0.0003 | *upper bound, not shippable* |
| **template rewrite, no LLM** (realizable) | 0.6681 | +0.0218 | 9 | 4 | 0.2668 | **INCONCLUSIVE** |

**Substituting the answer for the question costs 22 points with a perfect generator.** The premise is
refuted. What helps is the answer *augmenting* the question — query augmentation, not answer
substitution — and that reading is available only at an upper bound that requires already knowing the
answer.

The realizable range for the technique is bracketed **[+0.0218 not significant, +0.0917
unattainable]**.

---

## Arm 2 is harmful, and the mechanism was predicted in advance

| configuration | oracle@1 | Δ | gained | lost | p | verdict |
|---|---|---|---|---|---|---|
| PRF + entity, k=5 m=10 w=1 (PRIMARY) | 0.4105 | **−0.2358** | 11 | 65 | 0.0000 | **HARMFUL** |
| PRF + entity, k=3 m=5 w=2 | 0.5284 | −0.1179 | 13 | 40 | 0.0003 | **HARMFUL** |

The registered prediction named the mechanism before the number existed: *"PRF's feedback is drawn
from the first pass, and the first pass is worst on exactly the ~36% of cases where neither cue has
gold at rank 1 — so feedback is drawn from distractors precisely where help is needed."* Confirmed,
and larger than predicted.

Morphological expansion was **not implemented**, per the standing instruction.

---

## Arm 4: the corpus, not the extractor

Registered read order put **coverage first**, precisely so a null could not be blamed on the wrong
thing.

| | |
|---|---|
| turns with an extracted referenced date | 6,506 / 111,546 (**5.83%**) |
| questions with a parseable **window** | 12 / 229 (**5.24%**) |
| …of which **temporal-reasoning** | **1 / 59 (1.69%)** |

LongMemEval's temporal questions are **interval arithmetic over two named events** — *"how many weeks
ago did I…"*, *"how many days passed between…"*. They name events, not windows. A retrieval-side hard
constraint needs a window to bite on, and on this corpus one exists for a single temporal question in
59.

Primary read (extraction-covered subset) is **n=12** — reported and unusable; its Wilson half-width
alone exceeds every promotion band. Full held-out: **−0.0087**, inside the NOT REACHED band. One pool
emptied, one case lost gold it had at rank 1.

**Mastra's three-date structure transfers to the answer stage, not to retrieval.** That is where
their 95.5% is earned: computing an offset once evidence is in hand.

---

## Combined, and the additivity read

**Arm 1 pruning at N=3 + arm 3 template rewrite: oracle@1 0.6507, Δ+0.0044.**

Sub-additive, as registered. The rewrite alone nets **+5** cases; the combination nets **+1** —
pruning slightly degrades the rewrite's gain rather than compounding it.

| arm | recovered | broken | net |
|---|---|---|---|
| arm 1 pruning N=3 | 0 | 0 | 0 |
| arm 2 PRF+entity (primary) | 11 | 65 | −54 |
| arm 3 oracle answer *(upper bound)* | 33 | 84 | −51 |
| arm 3 oracle question+answer *(upper bound)* | 27 | 6 | +21 |
| arm 3 template rewrite | 9 | 4 | **+5** |
| arm 4 temporal | 0 | 2 | −2 |
| **combined (prune + rewrite)** | 10 | 9 | **+1** |

**A caveat on the subsumption table, stated rather than quoted around:** the registered rule declares
"A subsumes B" when B recovers ≤2 cases that A does not. Arm 1 recovers **zero** cases, so every
pairwise verdict involving it fires trivially. Those rows are in `additivity.json` and none of them
means anything. The rule needs a non-empty-recovery precondition; that is a defect in the rule I
registered, not a finding.

No full cross-product was computed: combining a harmful arm with a neutral one measures nothing.

---

## The cross-encoder: the cheap one is fast enough and not deterministic

Registered configurations only — two models, ten candidates, seq 256, no sweep. Bar: stage P95 ≤
**240 ms** at 1 thread (§5.7's 300 ms, minus Session F's measured 33 ms base, minus a 27 ms
integration reserve, because the spike's own method note records that a projected total is a sum of
separately measured spans and is optimistic by construction).

| model | 1 thread P95 | 16 thread P95 | truncation | latency bar | batch determinism | thread determinism |
|---|---|---|---|---|---|---|
| L-6 int8 | 273.47 ms | 121.18 ms | 0.4050 | ✗ | **FAIL** (0.050) | PASS |
| **L-2 int8** | **92.41 ms** | 45.36 ms | 0.4050 | **✓** | **FAIL** (0.037) | PASS |

*Reference: the spike's ruled-out configuration was fp32 L-6, 20 candidates, seq 256 — 331 ms stage,
365 ms projected.*

**L-2-int8 clears the latency bar with 147 ms to spare, and cannot be used.** Batch invariance fails
for both int8 models with max logit differences of **0.050** and **0.037** — not float noise, and
easily enough to reorder a ranking. The spike's fp32 L-6 passed this check *exactly* (0.000e+00).
Quantization changes the reduction order inside the graph.

**This is why re-verification was registered rather than inherited.** A stage whose score depends on
batch composition breaks `repro --runs 2`, which is a standing check. Inheriting the spike's
determinism pass would have shipped it.

### No GPU number is reported, and that is a correction

`get_available_providers()` lists `CUDAExecutionProvider`, so the first run produced CUDA figures of
272.67 ms and 97.11 ms — within 1% of the 1-thread CPU numbers. The provider **fails to load** on
missing cuBLAS/cuDNN and ORT falls back to CPU **without raising**. Those were CPU numbers wearing a
GPU label: this project's unobservable-mismatch pattern, in the provider binding. The script now
checks `get_providers()` on the constructed session and refuses to report rather than trust.

### Verdict, as registered

**NOT ADOPTED.** Adoption required three things and two failed:

| condition | result |
|---|---|
| latency at 1 thread ≤ 240 ms | **MET** by L-2-int8 |
| determinism re-verified | **FAILED**, both models |
| arm 1 shortlist equivalence | **FAILED**, every N and every ranker |

The shortlist-equivalence condition — `R@10 pruned ≥ R@20 unpruned − 0.01` — failed at oracle 0.9563
against a required 0.9769. **The re-open is not justified by this session**, independent of the
latency result. That verdict is not reinterpreted in light of L-2 passing.

---

## The registered prediction, scored

> *"No single arm moves the either-cue top-1 oracle by ≥ 0.05 with McNemar p < 0.05. Arm 1 delivers
> its value as pool reduction and shortlist equivalence rather than as oracle movement. The combined
> oracle is sub-additive."*

| clause | outcome |
|---|---|
| no realizable arm reaches +0.05 significant | **HELD** — best realizable is +0.0218 at p=0.2668 |
| …with one exception | the gold-label upper bound reached +0.0917 at p=0.0003. It is not a realizable arm; an upper bound exceeding the bar is what an upper bound is for |
| arm 1's value is pool reduction, not oracle | **HELD**, but for a reason the prediction did not give — the read was vacuous, not merely small |
| arm 1 shortlist equivalence | **FAILED**, which the prediction assumed would hold |
| combined is sub-additive | **HELD** — +0.0044 combined vs +0.0218 alone |
| arm 2 small or negative | **HELD**, strongly negative |
| arm 3 largest query-side arm, under 0.05 | **HELD** |
| arm 4 coverage-bound, full set down | **HELD** — −0.0087 |

---

## Gates and standing checks

Every number above sits behind gates that ran first.

| gate | result |
|---|---|
| pool reconstruction vs Session F published top-1 | lexical 0.5415 / dense 0.4454 / oracle 0.6463 — **exact to 4dp** |
| Python query embedder vs Rust's cached vectors | max abs component diff **7.45e-08** over 249 questions × 512 dims |
| Python BM25 vs stored `lexical_bm25` | Spearman **1.000000**, top-1 identical **100%** |
| document-vector lookup vs stored `dense_cosine` | max abs **1.79e-07** |

The second-implementation surface was kept minimal deliberately: Session F's 377 MB embedding cache
holds Rust's own vector for every question and turn, so **document vectors were never recomputed** and
only the query path is Python. That also made the registered gate strictly stronger than required —
it compares vectors elementwise rather than the downstream scalar the registration asked for.

| standing check | result |
|---|---|
| `cargo test --workspace` | **175 passed**, unchanged |
| `cd eval && pytest` | **72 passed**, unchanged, `eval/` zero lines touched |
| `repro --runs 2`, **no cache** | **IDENTICAL** |
| `conformance` | REJECTED, 0 findings, `fail_no_time_dependence` — the expected baseline |
| unchanged-cue check | registered as **will not fire**; no implementation change shipped |

---

## What this session did not do

**QA accuracy was dropped by explicit decision**, not omitted: no LLM credentials are configured and
no crate carries an HTTP client. It rolls to Session H. When it is built it belongs in `tools/` as an
offline measurement over retrieval output — [ROADMAP.md](../../docs/design/ROADMAP.md) M0b is
exercised through the eval harness only, and an answer stage on the measured path would be milestone
drift.

Every number here is **held-out** and is therefore **headroom, not validation**. Anything promoted
from this session must have its band re-derived on the fit split before it is built. Quoting a
Session G figure in Session H as evidence that a shipped mechanism generalizes would be the same
measurement on the same cases.
