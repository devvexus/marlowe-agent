# M0c Session M — Research: breaking the conditional-accuracy wall

Scope: methods only. No production code was written. All claims carry a source; where the
literature does not address our case that is said explicitly rather than glossed.

**The question this document is answering.** R@1 = input_recall × conditional_accuracy.
Input recall is 0.9825 at rerank depth 30 and is not the problem. Conditional accuracy tops out
at 0.8200. 46% of failures are one rank-1-vs-rank-2 decision, median logit gap 0.298. The
characteristic failure is **a turn that restates the question's topic beating a turn that
contains the answer**, and the wrong winner carries ≥2 question content-words the gold lacks in
41% of failures vs 16% of successes.

---

## 0. The three reframes that organise everything below

These are not methods. They are readings of the existing evidence that change which methods are
worth trying, and each one is independently sourced.

### 0.1 This is an Answer Sentence Selection problem, and the shipped model was never trained on one

The incumbent is a `ms-marco-MiniLM-L-*` cross-encoder. MS MARCO's relevance label is *topical
relevance of a web passage to a web query*, and its negatives are drawn corpus-wide from a
first-stage retriever. The label does not contain the distinction "restates the topic" vs
"contains the answer", because in a corpus-wide pool that distinction almost never has to be
made — the competing passages are about other things.

The task that *does* contain it is **Answer Sentence Selection (AS2)**. Its canonical dataset,
ASNQ, is constructed by labelling a sentence positive iff it is in the long answer **and**
contains the short answer, and negative if it is *in the same long answer paragraph but does not
contain the short answer*
([ASNQ](https://huggingface.co/datasets/AmazonScience/asnq),
[TANDA §3](https://arxiv.org/abs/1911.04118)). That is a literal, word-for-word description of
our failure mode, built deliberately as the hard class of an entire subfield.

**Consequence.** "The model underfits" is true but under-specified. It underfits a distinction
that neither its pretraining transfer set (MS MARCO) nor its in-domain set (6,898 pairs, 0 of
which leave the gold session) ever asked it to make. That is consistent with every refutation on
the list: capacity does not help because capacity is not the binding constraint; more data of the
same kind does not help because the same kind does not contain the distinction; four
architectures reproduce the number because they were all fed the same label.

### 0.2 Standard hard-negative *denoising* would delete exactly the examples we need — do not import it by default

RocketQA filters mined negatives with a cross-encoder and keeps only those it is confident are
irrelevant ([RocketQA](https://arxiv.org/abs/2010.08191)). NV-Retriever's best rule, TopK-PercPos,
discards any mined negative scoring above **95% of the positive's score**
([NV-Retriever](https://arxiv.org/abs/2407.15831)). SimANS samples negatives *ranked near* the
positive but explicitly avoids the very hardest, on the grounds that they are probably
mislabelled positives ([SimANS](https://arxiv.org/abs/2210.11773)).

Every one of those rules exists to solve the **false negative** problem: in MS MARCO and NQ, a
high-scoring unlabelled passage is very often *actually relevant*, and training on it as a
negative causes collapse
([negative sampling survey](https://arxiv.org/pdf/2603.18005)).

**Our setting inverts the premise.** LongMemEval annotates the answer-bearing turns, and
answer-bearingness is a *checkable string property*, not a human relevance judgement. A turn in
the gold session that scores above the gold and does not contain the answer is not a suspected
false negative — it is the single most valuable training example we could possibly construct.
A 95%-of-positive threshold deletes it.

**So: mine hard negatives aggressively, and use answer-string presence — not a score threshold —
as the ground truth for negativity.** This is the one place where the mainstream recipe is
actively wrong for us, and importing it uncritically would look like a null result rather than a
mistake.

### 0.3 The scaling laws say pointwise training is on the axis we have already refuted

*Scaling Laws for Cross-Encoder Reranking* (2026,
[arXiv](https://arxiv.org/html/2603.04816)) fits power laws separately per objective and reports
the **data exponent**:

| objective | data exponent e | reading |
|---|---|---|
| pointwise | −0.13 to −0.20 | gains come almost entirely from *capacity* |
| pairwise | −0.43 to −0.50 | gains come from *training exposure* |
| listwise | −0.43 to −0.50 | same |

The `ms-marco-MiniLM` family is trained pointwise (binary cross-entropy per pair). If we are
training pointwise, we are on the curve whose only lever is model size — and we have measured
that lever dead across a 17× range. **Changing objective changes which axis we are on.** The
same paper reports a 68M model matching or exceeding a 400M model at equal compute under
*pairwise* and pointwise objectives (though not listwise), which is a second, independent reason
not to expect capacity to be the answer.

**This also reframes the failed listwise fine-tune (−0.0131, null with power).** A listwise loss
only has more information than a pointwise one *if the group it is computed over is the group the
model sees at inference*. That is the entire content of LCE (§2 below). If the group was assembled
from a random or corpus-wide negative pool, it is trivially separable, the listwise gradient
collapses to the pointwise one, and the null is the expected result rather than a refutation of
listwise training. **Before writing listwise off, check what the group was.**

---

## 1. Do this first: build the instrument, not the fix

**Method.** A diagnostic probe set of *minimal pairs*: (question, question-echo turn,
answer-bearing turn) triples drawn from the 56 fit failures plus synthesised ones, scored as
"does the model rank the answer-bearing member above the echo member". Report pairwise accuracy
on this set as a standing number.

**Source.** ABNIRML ([TACL 2022](https://aclanthology.org/2022.tacl-1.13/)) is the methodology:
diagnostic probes built as controlled perturbations, testing one property at a time, rather than
aggregate effectiveness metrics. The axiomatic-diagnostics line
([Towards Axiomatic Explanations for Neural Ranking Models](https://dl.acm.org/doi/10.1145/3471158.3472256))
is the same idea grounded in retrieval axioms.

**Why it fits us specifically.** The project has already measured that *three features with
better AUC than the incumbent were all worse at the head*. That is the strongest possible
evidence that the aggregate metric is a proxy that moves independently of the property. A probe
set that is *only* head decisions is the non-proxy measurement, and it costs one afternoon.

**Cost.** Low. **Risk.** Low — the risk is that it is skipped because it is not a fix.

**Note on methodology, which follows from our own measurement.** Any tie-break feature or
calibrator must be **fit on the rank-1-vs-rank-2 pair distribution and scored on flips**, never
fit on the global candidate pool and scored on AUC. The three-features result says the two
objectives disagree here. This is a free correction that costs nothing and probably explains a
previous null.

---

## STRONG CANDIDATES

Ranked by expected value per unit of implementation cost, with the reasoning made explicit.

---

## 2. LCE — group-wise training with negatives from the deployed pipeline at the deployed depth

**What it is.** Localized Contrastive Estimation. Train the cross-encoder with a softmax
cross-entropy over a *group* of one positive and n−1 negatives, where the negatives are sampled
**from the top-k of the exact first-stage retriever the reranker will sit behind, at the exact
depth it will see**. Gao, Dai & Callan, *Rethink Training of BERT Rerankers in Multi-Stage
Retrieval Pipeline*, ECIR 2021 ([arXiv:2101.08751](https://arxiv.org/abs/2101.08751); reference
implementation [luyug/Reranker](https://github.com/luyug/Reranker)). Reproduced and extended in
*Squeezing Water from a Stone* (Pradeep et al., ECIR 2022,
[PDF](https://cs.uwaterloo.ca/~jimmylin/publications/Pradeep_etal_ECIR2022.pdf)).

**Why it plausibly fits our failure mode.** Our first stage is *not* generic: two cues → frozen
isotonic gate → session pruning → top 10. That pipeline hands the reranker a candidate set that
is far more homogeneous than a BM25 top-1000 — mostly turns from one or two sessions, mostly
on-topic. The reranker was trained on 6,898 pairs of which **0 leave the gold session**, so its
training distribution is *narrower in one dimension and wider in another* than what it is asked to
score. LCE's central empirical claim is precisely that this mismatch costs effectiveness, and that
matching the sampling depth to the deployment depth recovers it.

**Concretely, what to do.**
- Group size = the deployed rerank depth (10), or a subsample of it. Group size is the paper's key
  hyperparameter and is swept as a heat map; it interacts with the first-stage depth.
- Negatives = run the *actual deployed pipeline* (gate + pruning included) over the training
  queries and take its top-k minus the gold. Do not use a bare BM25 or bare-dense pool: that is a
  different distribution, and it is very likely what the failed listwise experiment used.
- Loss = softmax CE over the group. This is simultaneously the fix for §0.3 (moves us onto the
  steep-data-exponent axis) and the fix for the negative distribution.

**Expected magnitude.** LCE reports significant MRR@10 gains over pointwise CE on MS MARCO. The
number will not transfer. What should transfer is the *direction*, because the mechanism it fixes
(train/inference candidate-distribution mismatch) is one we can independently confirm we have.

**Cost.** Moderate. Requires the training harness to call the deployed pipeline to build groups,
and a group-wise batch collator. No new graph, no new inference-time cost.

**Risk.** Low. Worst case it reproduces the listwise null — but this time with the group
construction verified, which converts a null into information.

---

## 3. TANDA — an AS2 transfer stage before the in-domain adapt

**What it is.** Transfer-and-Adapt: fine-tune the pretrained encoder on a large, high-quality
*general* task first (ASNQ), producing a stable intermediate model, then adapt on the small, noisy
target set. Garg, Vu & Moschitti, AAAI 2020
([arXiv:1911.04118](https://arxiv.org/abs/1911.04118); code
[amazon-science/wqa_tanda](https://github.com/amazon-science/wqa_tanda)).

**Why it plausibly fits our failure mode.** See §0.1. ASNQ's negatives are the same-paragraph
non-answer-bearing sentences — structurally identical to our question-echo turns. 57k questions,
23M candidates; subsampling to a few hundred thousand pairs is standard. TANDA's specific claim is
that the transfer step produces a model that is *robust to noise in the adapt step and needs far
less target data* — which matches a target set of 6,898 pairs exactly.

**Expected magnitude.** TANDA sets MAP 92.0 (WikiQA) / 94.3 (TREC-QA), roughly +10 MAP over
single-stage fine-tuning on those benchmarks. **That number does not transfer**: WikiQA and
TREC-QA are Wikipedia declarative prose with factoid questions, and our candidates are
first-person conversational turns with a personal-history question. The domain gap is genuine and
should be stated in any writeup. What transfers is the *label semantics*, which is the thing we
are missing.

**Cost.** Moderate — one extra fine-tuning stage on a public dataset, no architecture change, and
the result is still a 16M model that meets the latency budget.

**Risk.** Medium. Two specific ones: (a) the domain gap may make the transfer stage a wash or
mildly harmful, which the §1 probe set will detect cheaply; (b) ASNQ positives are single
sentences, ours are whole turns that may exceed the 256-token budget — mismatched granularity in
the transfer stage is a real hazard.

**Adjacent and cheap:** *Context-Aware Transformer Pre-Training for AS2*
([arXiv:2305.15358](https://arxiv.org/abs/2305.15358)) and *Modeling Context in AS2 on a Latency
Budget* ([EACL 2021](https://arxiv.org/abs/2101.12093)) both report that encoding the candidate's
*neighbours* — (preceding, candidate, following) with distinct segment ids — improves AS2, by 6–11%
over non-contextual SOTA in the multi-way-attention variant. In a conversation this is unusually
well-motivated: the answer to "what did I say my budget was" may sit in the assistant's *reply* to
the user's turn, and pronoun/ellipsis resolution across turns is the normal case, not the edge
case. **This is a cheap input-format change with a directly applicable rationale.**

---

## 4. Counterfactual question-echo negatives: construct them, don't only mine them

**What it is.** Build the hardest possible negative by taking the **gold turn and deleting or
replacing the answer span**, leaving every other token intact. The result is maximally
topically-matched, maximally lexically-overlapping with the question, and definitively
non-answer-bearing. This is minimal-pair counterfactual augmentation, the same family as
Retrieval-Guided Counterfactual generation (RGF,
[arXiv:2110.07596](https://arxiv.org/abs/2110.07596)) and *Learning to Rank Question Answer Pairs
with Bilateral Contrastive Data Augmentation*
([arXiv:2106.11096](https://arxiv.org/abs/2106.11096)).

**Why it plausibly fits our failure mode — better than mining does.** Mining gives you negatives
that are *usually* topical-not-answer-bearing, mixed with noise. Construction gives you a set
where **every non-answer feature is held constant by design**, so the only gradient available is
the one we want. The model cannot solve the pair with topic, with BM25, with length, or with
question-word overlap, because those are all identical between the two members. This directly
attacks the measured statistic: the wrong winner's extra question content-words become useless as
a discriminator when the two members share them.

It also sidesteps §0.2 entirely: a constructed negative cannot be a false negative.

**The known failure of this method, and the mitigation.** Counterfactual augmentation is
notorious for teaching the *edit artefact* instead of the concept — the model learns "text with a
deletion scar is negative" or "shorter is negative". **Mitigation: apply the same edit operation
to produce a positive.** Delete a non-answer span of comparable length from the gold turn and keep
it labelled positive. Now the edit is uninformative and only the answer's presence is. This is the
single most important implementation detail and skipping it will produce a green training curve
and no gain — the exact proxy failure this project already tracks fifteen instances of.

**Expected magnitude.** Unknown; no direct literature on turn-level personal memory. The
mechanism is sound and the augmentation is unbounded in supply.

**Cost.** Low. Answer spans are available from the benchmark annotation. Generating N variants per
gold turn is a data-prep script.

**Risk.** Medium — see the artefact problem above. Also: over-weighting constructed pairs may push
the model toward a degenerate "answer-string detector" that fails when the answer is paraphrased.
Cap the constructed fraction and keep mined negatives in the mix.

---

## 5. Iterative self-mined negatives (ANCE-style), tuned for our refresh economics

**What it is.** Maintain negatives sampled from the *current* model's own top-k, refreshed
periodically during training, rather than from a fixed pool.
[ANCE, ICLR 2021](https://arxiv.org/abs/2007.00808).

**Refresh schedule — the concrete answer to the question asked.** ANCE refreshes the ANN index
asynchronously; the paper's operating point is roughly **every 10k batches** with a 1:1
trainer/inferencer GPU split. Reported behaviour: **5k is more stable, 20k fluctuates under high
learning rate**, and skewing the split toward the trainer makes the index visibly stale and
degrades results. Staleness is the failure mode to watch.

**How this changes for us — and it changes a lot.** ANCE's refresh cost is dominated by
re-encoding a multi-million-document corpus. Ours is ~487 candidates per query over a few thousand
training queries, and the "index" is just the deployed pipeline. **Refreshing is cheap enough to do
every epoch, or even every few hundred steps.** The staleness/cost tradeoff that dictates ANCE's
schedule essentially does not bind here. Refresh often; the failure mode ANCE warns about is the
one we can most easily avoid.

**Cross-session negatives.** Currently 0 of 6,898 pairs leave the gold session. This is the
narrowest possible negative distribution, and ANCE's entire premise is that negatives must come
from the full candidate space the model will actually rank over. **But**: our session-pruning
stage means the deployed top-10 is *partly* cross-session and *mostly* within-session. So the
right target is not "corpus-wide" (ANCE's answer) but "whatever the deployed pipeline actually
produces" (LCE's answer, §2). These two prescriptions differ and LCE's is the one that matches our
architecture. **Sample cross-session negatives in the proportion the deployed pipeline produces
them, not uniformly.**

**Denoising — deviate from standard practice, per §0.2.** Use answer-string presence as the
negativity label. If a soft filter is wanted anyway, SimANS's *ambiguous* sampling
([arXiv:2210.11773](https://arxiv.org/abs/2210.11773)) — weight negatives ranked *near* the
positive most heavily — is the right shape, because it up-weights the head region without
discarding it, whereas NV-Retriever's hard 95% threshold discards precisely it.

**Expected magnitude.** ANCE-style refreshing is worth several MRR points in dense retrieval. For
a *reranker* over a short, homogeneous candidate list the gain is less well characterised in the
literature — reranker-side iterative mining is mostly folded into LCE. Treat §2 as the primary and
this as the schedule detail on top of it.

**Cost.** Moderate. **Risk.** Medium — the classic ANCE risk is training collapse from too-hard
negatives. Our answer-string ground truth removes the usual cause (false negatives) but not the
other one: if constructed + mined hard negatives dominate, the loss surface gets very sharp.
Ramp the hardness across training rather than starting at maximum.

---

## 6. duoBERT-style pairwise adjudication of the top-2, gated on the score gap

**What it is.** After pointwise reranking, a second model scores *triples* (q, dᵢ, dⱼ) —
both candidates in one sequence — estimating P(dᵢ ≻ dⱼ). Nogueira, Yang, Cho & Lin, *Multi-Stage
Document Ranking with BERT* ([arXiv:1910.14424](https://arxiv.org/abs/1910.14424); code
[castorini/duobert](https://github.com/castorini/duobert)). Aggregation over the pairwise matrix
was tested as SUM / BINARY / MAX / MIN, with **SUM best**.

**Why it plausibly fits our failure mode — this is the most literal match on the list.** 46% of
failures are a single rank-1-vs-rank-2 decision. A pointwise scorer must decide "does this turn
answer the question" for each candidate *in isolation*, and must then hope two independently
computed scalars order correctly across a median gap of 0.298. A duo model computes a
**comparative** feature directly: with both turns in the same attention window it can represent
"this one names a value of the type asked for and that one merely repeats the topic" — a relation
that has no pointwise encoding at all.

**Gate it on the gap.** Do not run duo on all 10. We already know the failures concentrate at
small gaps. Invoke duo only when the top-2 gap < τ, with τ calibrated on the fit split. At k=2
symmetric that is 2 extra forward passes on a small fraction of queries — close to free.

**Cost.** Moderate-to-high, and the cost is *not* the compute. Two problems specific to this repo:

- **Token budget.** Two full turns plus the question will not fit in 256 tokens. This needs a 384
  or 512 graph, or aggressive truncation of the pair members.
- **A new graph re-opens the invariance measurements.** Per the project's own standing rule,
  batch and padding invariance are re-measured *per graph* and never inherited, and ADR-015's
  `[1, 256]` shape binding is a property of the graph, not the architecture. A duo graph with a
  different sequence length must have its invariance measured from scratch, not argued.

**Risk.** Medium-high. duoBERT is no longer actively developed and its gains on MS MARCO were
modest relative to monoBERT. But its gains were measured over a *thousand*-candidate list where
most pairs are easy; ours would be measured over the 2 candidates where the pointwise model is
demonstrably at chance. **Those are different quantities and ours is the more favourable one.**

---

## 7. Distillation from a *fine-tuned* larger teacher, with a margin-preserving objective

**What it is.** Two things at once, and the question posed — "does distillation work when the
teacher is worse zero-shot?" — has a clean answer.

**(a) Zero-shot ordering does not predict fine-tuned ordering.** The nine-model sweep measured
*zero-shot or lightly-tuned* effectiveness. A 109M cross-encoder fine-tuned with ListNet beats a
4B model by 2.6 nDCG@3 and 13.3 Spearman at 37× fewer parameters
([systematic study, 2026](https://arxiv.org/html/2608.09650)); the scaling-laws paper finds a 68M
model matching a 400M model at equal compute under pairwise objectives
([arXiv](https://arxiv.org/html/2603.04816)). So "the 278M models lose to a fine-tuned 16M model"
is evidence that *those 278M models as configured* lose — **it is not evidence that a fine-tuned
278M model loses.** Running that fine-tune is a cheap, decisive experiment and it answers the
question directly. Per this project's own rule about measurements scoped to the system they were
taken on: the 17× capacity refutation was measured on un-fine-tuned graphs, and carrying it to
fine-tuned graphs requires re-measuring, not citing.

**(b) The distillation objective matters, and one of them preserves exactly the quantity we are
losing.** Margin-MSE (Hofstätter et al.,
[arXiv:2010.02666](https://arxiv.org/abs/2010.02666)) regresses the student onto the teacher's
**margin between a positive and a negative**, not onto absolute scores. Our worst failures have
margins of 0.0099. A hard 0/1 label throws that information away entirely; margin-MSE transmits
it. Recent reproductions place margin-MSE in the consistently top tier across backbones
([Reproducing and Comparing Distillation Techniques for Cross-Encoders,
2026](https://arxiv.org/html/2603.03010)), while listwise KL-divergence distillation over a
candidate group is reported to beat margin-based losses in the dense-retrieval setting
([arXiv:2505.19274](https://arxiv.org/abs/2505.19274)). Rank-DistiLLM
([arXiv:2405.07920](https://arxiv.org/pdf/2405.07920)) is the reference for distilling ranking
behaviour into cross-encoders specifically.

**Why it plausibly fits our failure mode.** A 2-layer model has to learn the answer-bearing
distinction from a binary label. A teacher's soft margin is a much denser signal per example, and
the standard reason distillation helps small students is that it supplies exactly the gradient
information the small model cannot extract from hard labels alone
([MiniLM](https://arxiv.org/abs/2002.10957)). Given that we have *no train/val gap* — i.e. we are
signal-limited, not sample-limited — a denser per-example signal is the theoretically right lever.

**Cost.** Moderate. One teacher fine-tune, one scoring pass, one student retrain. No inference-time
cost at all — this is the cheapest option to *deploy*.

**Risk.** Low-medium. The whole thing is contingent on step (a): if the fine-tuned 278M teacher
does not beat the 16M student, there is nothing to distil. **Run (a) first as a gate.**

---

## 8. An answerability head, trained jointly — not an answer-type filter

**What it is.** Multi-task the cross-encoder: the existing relevance head plus a second head
predicting "does this turn contain a span that answers this question". At inference, combine.
The architectural precedent is **PReGAN** ([arXiv:2207.01762](https://arxiv.org/abs/2207.01762)),
which uses *two* discriminators — one on topical relevance and one on **answerability** — with the
explicitly stated diagnosis that "beyond topical relevance, passage ranking for open-domain
factoid QA also requires a passage to contain an answer".

**Why it plausibly fits our failure mode.** That sentence is our bug report. The measured
"numeric answer-type filter" failed at 2/56 — but it was deployed as a **hard filter over a hand-
specified answer type**. A learned soft head is a different object: it is trained on all answer
types, it outputs a graded score that can break a 0.0099 tie, and it does not need the answer type
to be enumerable.

**Expected magnitude.** PReGAN reports gains on open-domain QA passage ranking; the numbers are on
Wikipedia/NQ-style corpora and will not transfer. The value here is that it is a *second signal
computed by the same forward pass*, so its cost is one extra linear layer.

**Cost.** Low. **Risk.** Medium — multi-task training can degrade the primary head, and the
auxiliary label ("contains an answering span") is only cleanly available where the benchmark gives
us the answer string. Weight the auxiliary loss low and ablate.

**Note on training labels.** The counterfactual construction in §4 gives this head perfect,
abundant supervision for free: gold turn = answerable, answer-span-deleted turn = not answerable,
everything else held fixed. §4 and §8 compose unusually well.

---

## 9. LambdaRank weighting, because ΔMRR for a 1↔2 swap is the largest weight in the objective

**What it is.** Weight each pairwise gradient by the change in the target metric that swapping
that pair would cause. LambdaLoss ([Wang et al., CIKM 2018](https://dl.acm.org/doi/10.1145/3269206.3271784))
is the framework that gives this a proper probabilistic footing.

**Why it plausibly fits our failure mode, precisely.** Our metric is R@1 — reciprocal rank
truncated at 1. The Δ-metric for swapping positions 1 and 2 is the **maximum possible** value;
Δ for swapping 7 and 8 is zero. A plain pairwise loss weights those equally. LambdaRank weighting
makes the objective top-heavy *by construction*, which is the exact mismatch between "overall AUC"
and "head discrimination" that this project has already measured three times over.

This is the principled version of "fit the tie-break on head decisions only" from §1, and it is
worth stating that they are the same idea applied at two different levels: **weight the loss by
what the metric actually cares about.**

**Reported comparison, honestly.** Head-to-head across BEIR-style datasets, RankNet averaged
nDCG@10 56.7, LambdaRank 55.4, ListNet 55.9 — i.e. **LambdaRank did not win on nDCG@10**. But
nDCG@10 is precisely the aggregate metric we have measured to be a poor proxy for our head
behaviour. The argument for LambdaRank here is metric-alignment, not a borrowed benchmark result,
and it should be stated that way rather than dressed up.

**Cost.** Low — it is a reweighting of an existing loss. **Risk.** Low. Combine with §2; the group
structure LCE provides is what LambdaRank needs to compute Δ.

---

## 10. An IDF-weighted "non-query mass" feature, fit on head pairs only

**What it is.** A single scalar feature: the IDF-weighted mass of content in the candidate that is
**not licensed by the question**. A question-echo turn is nearly fully predictable from the
question; an answer-bearing turn necessarily contains information the question does not contain.

**Why it plausibly fits our failure mode.** This is the feature form of the statistic already
measured: the wrong winner carries ≥2 question content-words the gold lacks, 41% vs 16%. That is
a 2.6× separation on a quantity we can compute in microseconds. The winner has ≥ gold's BM25 in
43/56 — i.e. **BM25 is anti-correlated with correctness at the head**, which is a strong, unusual,
and directly exploitable signal.

**Why it is not the already-refuted length penalty.** The measured global length penalty was
net-harmful. This is a different quantity: not "how long" but "how much of the length is
IDF-weighted content the question did not supply". Length correlates with it weakly and in a way
that is confounded by turn type. Worth separating explicitly in the writeup so the two results are
not conflated later.

**Two variants worth testing:**
- Lexical: Σ IDF over candidate content tokens absent from the question, normalised.
- Dense: the residual norm of the candidate embedding after projecting out the question direction.
  Cheap (both vectors already computed), and it captures paraphrase where the lexical version does
  not.

**Cost.** Very low — a day, including the ablation. **Risk.** Low, *provided* it is fit on the
rank-1-vs-rank-2 pair distribution and evaluated on flips (§1). Fit on the global pool and scored
on AUC, it will look promising and then fail at the head, which is exactly what happened to the
last three features.

---

# WORTH KNOWING ABOUT

Real methods, but with weaker fit, weaker evidence for our metric, or a constraint conflict.

## 11. Set-Encoder — inter-passage attention, permutation-invariant

Passages are encoded as separate sequences; each carries an `[INT]` token, and tokens in one
sequence attend to the *other* sequences' `[INT]` tokens only. Positional encodings restart per
sequence, so the model is permutation-invariant by construction — no position bias, unlike
concatenated listwise rerankers. ([arXiv:2404.06912](https://arxiv.org/abs/2404.06912))

**Attractive**: gives candidates a view of each other (like duo, §6) at a fraction of duo's cost,
and is orders of magnitude cheaper than concatenation-based listwise scoring.

**Honest read of the evidence**: at 330M, Set-Encoder is only *comparable* to a pointwise
monoELECTRA on plain relevance (~0.73–0.79 nDCG@10 on TREC DL 19/20); it wins clearly only on
**novelty/duplicate-aware** ranking (0.821 vs 0.785 α-nDCG@10). And **the paper does not evaluate
early precision at all** — no nDCG@1, no P@1. So the published evidence does not speak to our
metric. The architecture is the right shape for our problem; the evidence that it helps our
quantity does not exist. If duo (§6) is blocked on token budget, this is the fallback.

## 12. Reader-guided reranking (RIDER) — strong results, but it needs a reader

Rerank candidates by lexical overlap with a reader's *top predicted answers*. No training at all.
Reports **10–20 absolute points of top-1 retrieval accuracy** and 1–4 EM, and beats trained
transformer rerankers ([arXiv:2101.00294](https://arxiv.org/abs/2101.00294)).

Those are the largest top-1 gains in anything surveyed here, and the mechanism is exactly ours: an
answer prediction is by definition answer-bearing evidence, so it discriminates answer-containing
from topic-matching turns directly.

**The constraint.** As published it requires a reader, and a generative reader is excluded. **The
boundary worth naming rather than assuming:** an *extractive* span reader — a small SQuAD-style
span classifier that outputs (start, end) offsets into the candidate — is a discriminative model,
not a generative one. Whether that falls inside or outside the exclusion is a decision for the
user, not for this document. If it is inside, it is arguably the highest-expected-value item on
the whole list and §8 becomes its cheap approximation.

Related and same constraint: **RMM** (*In Prospect and Retrospect: Reflective Memory Management*,
[ACL 2025](https://aclanthology.org/2025.acl-long.413/)) does online RL on the retriever using the
reader's binary citation feedback (+1 useful / −1 not), reporting **>10% accuracy improvement on
LongMemEval** and Recall@5 up to 69.8%.

## 13. Fact-augmented key expansion — the LongMemEval paper's own strongest lever, and it is generative

The benchmark authors' own optimisation: concatenate extracted user facts with the raw value at
indexing time. Reported **+9.4% recall@k and +5.4% final accuracy averaged across models**
([arXiv:2410.10813](https://arxiv.org/abs/2410.10813)).

Two reasons it is filed here rather than above. (a) It is an **indexing-time generative** step,
which is at minimum adjacent to the exclusion. (b) It targets **recall**, and our recall is 0.9825
— we would be buying the thing we already have. Also worth knowing: a controlled ablation argues
the opposite direction, that verbatim chunks beat extracted artifacts for long conversations
([arXiv:2601.00821](https://arxiv.org/pdf/2601.00821)).

**One number from that paper is directly useful to us regardless**: with flat indexing, *round*
(turn) granularity scores **lower** than session granularity — Recall@10 0.692 vs 0.783, NDCG@10
0.512 vs 0.638. We rank turns. That is the benchmark authors measuring that turn-level ranking is
the harder problem, which is corroborating context for why conditional accuracy is our wall.

## 14. Sliding-window / MaxP vs PARADE for over-budget turns

Already planned. The literature: MaxP is score aggregation (max over windows); PARADE aggregates
passage *representations* and beats MaxP notably on collections "where relevance signals can be
spread throughout the document" — Robust04, GOV2
([arXiv:2008.09093](https://arxiv.org/abs/2008.09093)).

**Honest transfer assessment: PARADE's advantage probably does not apply to us.** In a
conversational turn the answer is a *concentrated* span, not a signal spread over a long document.
That is the exact condition under which MaxP is competitive and PARADE's extra machinery earns
nothing. **Implement MaxP; do not build PARADE without first measuring that relevance is
distributed.** This is cheap and the reasoning should be recorded, because "we used the better
method from the paper" is how a measurement gets carried across a boundary it does not survive.

## 15. Adaptive rerank depth — a latency lever here, not a quality lever

*Optimal Re-Ranking Depth* (SIGIR 2026, [DOI](https://doi.org/10.1145/3805712.3809953)): many
queries have a well-defined optimal depth; **oracle depth selection gives >7% effectiveness and 5×
less reranking on MS MARCO DEV**, but **standard QPP methods are ineffective at predicting it** —
only an LLM-assessed first-stage-quality predictor worked. AcuRank
([arXiv:2505.18512](https://arxiv.org/pdf/2505.18512)) does uncertainty-aware adaptive computation
for listwise reranking.

**For us:** input recall is 0.9825 at depth 30, so depth is not where R@1 is being lost, and
adaptive depth cannot buy conditional accuracy in the obvious way. There is one non-obvious way it
could: **a shallower list contains fewer question-echo distractors**, so if the gold is at rank 1
of a 5-candidate list it cannot be beaten by the 8th. A depth sweep against *conditional accuracy*
(not recall) is a cheap experiment that would settle it. And the effective predictor in the paper
is LLM-based, which is excluded.

## 16. Rank fusion / RRF at the head — consistent with the null already measured

RRF sums 1/(rank + k), k≈60. It is explicitly a *calibration-free* method — it discards score
magnitudes. Our failures are decided by score margins of 0.0099–0.298, i.e. by exactly the
information RRF throws away. The already-measured result (dense-cosine fusion at rank 2: **0 flips
at every weight**) is what this predicts. Recording the mechanism is useful so the null is not
re-litigated: **fusion buys recall, not head precision, and we do not need recall.**

## 17. RocketQAv2 — joint retriever/reranker training with dynamic listwise distillation

([arXiv:2110.07367](https://arxiv.org/pdf/2110.07367)) Trains retriever and reranker jointly, with
the reranker's distribution supervising the retriever and hybrid data augmentation. Filed here
because our first stage is a *frozen isotonic gate* — a published, build-time artifact that
`fit_gate.py` refuses to regenerate casually. Joint training would touch it. Worth knowing that
the joint formulation exists and reports gains; not worth destabilising a frozen gate for.

---

# What the literature does not cover, stated plainly

1. **No paper surveyed here measures P@1 / R@1 on turn-level personal conversational memory.**
   Everything reported is nDCG@10 / MRR@10 on MS MARCO, BEIR or TREC DL. Our metric is R@1 and
   our corpus is first-person dialogue. Every magnitude quoted above should be treated as a
   direction, not a forecast.

2. **The head-vs-aggregate divergence we measured is not well studied.** Three features with
   better AUC being worse at the head is a real, reproducible phenomenon in our system, and the
   ranking literature almost universally reports aggregate metrics. This is why §1 (build the
   probe set) is ranked above every method: we are operating without the instrument that would
   make any of the methods below it evaluable.

3. **Hard-negative denoising literature assumes false negatives dominate. Ours don't** (§0.2).
   Every default in RocketQA / NV-Retriever / SimANS is tuned for a premise we do not share. This
   is the highest-risk place to copy a recipe.

4. **The 17× capacity refutation was measured on models that were not in-domain fine-tuned.** Per
   the project's own standing rule about measurements scoped to the system they were taken on,
   extending it to fine-tuned graphs needs a measurement, not a citation. §7(a) is that
   measurement and it is one training run.

---

# Suggested sequence

| # | Item | Cost | Why here |
|---|---|---|---|
| 1 | §1 probe set of head minimal-pairs | hours | Nothing below is evaluable without it |
| 2 | §10 IDF non-query-mass feature, fit on head pairs | 1 day | Directly exploits a statistic already measured; cheapest possible signal |
| 3 | §2 LCE groups from the deployed pipeline + §9 LambdaRank weighting | days | Fixes the negative distribution and the objective axis at once; also explains the listwise null |
| 4 | §4 counterfactual echo negatives (with the edit-control positives) + §8 answerability head | days | Compose; give the model the distinction it was never taught, with no false-negative risk |
| 5 | §7(a) fine-tune a 278M teacher — pure gate | 1 run | Answers "do big models win when fine-tuned" and unblocks §7(b) |
| 6 | §3 ASNQ transfer stage | week | Highest ceiling, highest domain-gap risk; do after the cheap wins are banked |
| 7 | §6 duo adjudication gated on the score gap | week+ | Most literal match to the failure, but needs a new graph and fresh invariance measurements |

**One process note, in this project's own idiom.** Several items above are trim-, group- or
edit-dependent: §2's gain depends on the group actually coming from the deployed pipeline, §4's
depends on the edit-control positives actually existing, §5's on the refresh actually happening.
Each needs a control that fails when the named thing did not occur — a group assembled from a
random pool, a run with the edit control removed, a run with refresh disabled. Otherwise the
result reads identically whether or not the mechanism fired.

---

## Sources

- [ANCE — Approximate Nearest Neighbor Negative Contrastive Learning, ICLR 2021](https://arxiv.org/abs/2007.00808)
- [RocketQA, NAACL 2021](https://arxiv.org/abs/2010.08191) · [RocketQAv2](https://arxiv.org/pdf/2110.07367)
- [NV-Retriever: effective hard-negative mining](https://arxiv.org/abs/2407.15831)
- [SimANS: Simple Ambiguous Negatives Sampling](https://arxiv.org/abs/2210.11773)
- [Negative Sampling Techniques in Information Retrieval: A Survey](https://arxiv.org/pdf/2603.18005)
- [TANDA: Transfer and Adapt, AAAI 2020](https://arxiv.org/abs/1911.04118) · [code](https://github.com/amazon-science/wqa_tanda) · [ASNQ dataset](https://huggingface.co/datasets/AmazonScience/asnq)
- [Context-Aware Transformer Pre-Training for AS2](https://arxiv.org/abs/2305.15358) · [Modeling Context in AS2 on a Latency Budget, EACL 2021](https://arxiv.org/abs/2101.12093)
- [PReGAN: Answer Oriented Passage Ranking with Weakly Supervised GAN](https://arxiv.org/abs/2207.01762)
- [RIDER: Reader-Guided Passage Reranking](https://arxiv.org/abs/2101.00294)
- [LCE — Rethink Training of BERT Rerankers, ECIR 2021](https://arxiv.org/abs/2101.08751) · [code](https://github.com/luyug/Reranker)
- [Squeezing Water from a Stone, ECIR 2022](https://cs.uwaterloo.ca/~jimmylin/publications/Pradeep_etal_ECIR2022.pdf)
- [Multi-Stage Document Ranking with BERT (monoBERT/duoBERT)](https://arxiv.org/abs/1910.14424) · [code](https://github.com/castorini/duobert)
- [Margin-MSE — Cross-Architecture Knowledge Distillation](https://arxiv.org/abs/2010.02666)
- [Reproducing and Comparing Distillation Techniques for Cross-Encoders (2026)](https://arxiv.org/html/2603.03010)
- [Cross-Encoder Listwise Distillation vs Contrastive Learning](https://arxiv.org/abs/2505.19274)
- [Rank-DistiLLM](https://arxiv.org/pdf/2405.07920)
- [Scaling Laws for Cross-Encoder Reranking (2026)](https://arxiv.org/html/2603.04816)
- [Listwise Cross-Encoder Fine-Tuning vs Agentic Instruction Tuning (2026)](https://arxiv.org/html/2608.09650)
- [Set-Encoder: Permutation-Invariant Inter-Passage Attention](https://arxiv.org/abs/2404.06912)
- [PARADE: Passage Representation Aggregation](https://arxiv.org/abs/2008.09093)
- [Optimal Re-Ranking Depth, SIGIR 2026](https://doi.org/10.1145/3805712.3809953) · [AcuRank](https://arxiv.org/pdf/2505.18512)
- [ABNIRML, TACL 2022](https://aclanthology.org/2022.tacl-1.13/) · [Towards Axiomatic Explanations for Neural Ranking Models](https://dl.acm.org/doi/10.1145/3471158.3472256)
- [LambdaLoss Framework, CIKM 2018](https://dl.acm.org/doi/10.1145/3269206.3271784)
- [Retrieval-guided Counterfactual Generation for QA](https://arxiv.org/abs/2110.07596) · [Bilateral Contrastive DA for QA ranking](https://arxiv.org/abs/2106.11096)
- [LongMemEval, ICLR 2025](https://arxiv.org/abs/2410.10813)
- [RMM — In Prospect and Retrospect, ACL 2025](https://aclanthology.org/2025.acl-long.413/)
- [Verbatim Chunks Beat Extracted Artifacts](https://arxiv.org/pdf/2601.00821)
- [MiniLM](https://arxiv.org/abs/2002.10957)
