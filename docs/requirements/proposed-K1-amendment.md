# Proposed Amendment — K1

> ## STATUS: **ADOPTED 2026-08-08**, M0b Session K. Option (a), with (c)'s two directions carried forward as named work rather than as preconditions.
>
> **This file is kept as the proposal of record. It is no longer the live criterion.** Do not read
> or cite it as the pinned text — it is what was put to the human, and the decision is recorded here
> so that later sessions can see what was argued and what was chosen, not only the outcome.
>
> | | where it now lives |
> |---|---|
> | **Part A** — the criterion | `docs/design/ROADMAP.md` → "K1 — amended 2026-08-08" **(pinned)** |
> | | `docs/requirements/01-brief.md` §5.7.1 **(pinned)** |
> | **Part B** — the argument | `docs/design/DECISIONS.md` → **ADR-019** |
> | **Part C** — the non-goals | ADR-019, "What this ADR deliberately does NOT do" |
> | **Part D** — the decision | resolved: **(a)** with (c)'s directions retained |
> | the curve and operating point | `docs/design/PRECISION-COVERAGE.md` |

**Written:** 2026-08-06, after M0b Session J.
**Applies to:** `ROADMAP.md` kill criteria, and brief §5.7 where K1's numbers originate.

Part A is the text to paste. Part B is the argument, kept out of the pinned text. Part C is what
this amendment deliberately does not do.

---

# Part A — the proposed text

> ## K1 — amended 2026-08-06
>
> **Original:** injection precision <0.95 at ≤7,000 tokens and ≤300 ms P95, with the gate frozen →
> project-level; reconsider rather than continue.
>
> **Measured, Session J, held-out, n=229:** no coverage level reaches 0.95 injection precision with
> its confidence interval above the threshold. The best point estimate is **0.9565 (22/23) at 10.0%
> coverage, Clopper-Pearson [0.7805, 0.9989]**. This was the registered prediction, written before
> the read.
>
> **Amended criterion.** Marlowe's memory subsystem is judged on a published precision/coverage
> curve rather than on a single threshold, with three conditions:
>
> 1. **The curve ships with the product.** Precision at every coverage level from 100% down to 10%,
>    each point with its binomial interval, measured on a held-out split the gate's parameters have
>    never seen.
> 2. **The operating point is chosen on the curve and declared**, not assumed. Whatever coverage is
>    selected, the injection precision at that point and its interval are stated wherever the
>    capability is described.
> 3. **The abstention path is real.** Below the operating point the system abstains and the agent
>    recovers through the explicit `recall` tool (§5.5). A configuration that injects at low
>    precision to raise coverage fails this criterion outright.
>
> **The kill condition is retained and restated.** The project is reconsidered if the curve is flat
> — that is, if precision at 10% coverage is not materially above precision at 100% coverage. A
> system whose confidence carries no information is the case K1 was written to catch, and it remains
> a project-level finding.
>
> **Constraints unchanged:** ≤7,000 tokens and ≤300 ms P95 still bind, and the shipped fine-tuned
> configuration measures 214 ms/query inside that budget.

---

# Part B — why

## B1 · The instrument could not have passed

**ADR-016, measured not derived: a perfect retrieval system scores 0.8483 on the shipped gate
against a 0.95 threshold.**

Three steps, each measured on the fit split:

1. Every pooling operation in `fit_isotonic` makes a block larger, never smaller. The smallest
   expressible block is 435 rows — 1.90 candidates per query.
2. `{cue}_margin` is positive for exactly one candidate per query, so the top block is forced to be
   "one row from every query, then the least-negative rank-2s." Measured: the top block spans
   **229 of 229 queries** for both cues. **The gate has no vocabulary for confident subsets.**
3. 89 of 229 fit queries have exactly one gold row, so their rank-2 slot is necessarily a
   distractor. A perfect cue gets 229 rank-1 rows plus at most 140 rank-2 rows: 369/435 = 0.8483.

Sessions B through H each read the 0.3739 ceiling as evidence retrieval was not improving. It was
reporting a structural property of the calibration shape and would have read approximately the same
with a flawless retriever. **The honest K1 number was first produced in Session J, from a conformal
reading at query resolution — the only resolution that can express a subset.**

This does not invalidate any retrieval measurement. R@1, R@5, R@10, conditional accuracy, the oracle,
every closed mechanism and every failure decomposition were measured against gold turns with the
gate uninvolved. It invalidates the *interpretation* of one number.

## B2 · The measured answer is a real negative, not an instrument artifact

The conformal arm is not subject to §B1's defect. It operates at query resolution (1/229), sets τ at
the `(1−α)(1+1/n)` quantile of the rank-1 minus rank-2 rerank margin, and produces a genuine coverage
curve. It still does not reach 0.95 with a bounded interval.

The guarantee and the measurement are reported as separate quantities throughout, because they are:
conformal at α=0.05 gives measured P(inject | wrong) = 0.0133 against the 0.05 marginal bound, and
that marginal guarantee does **not** cover precision conditional on having injected, which is the
selective-risk quantity K1 asks about.

## B3 · More retrieval quality is not the lever

**Session J's highest-weighted finding: +0.0699 R@1 from fine-tuning bought nothing at the operating
point.** Fine-tuning dominates the precision/coverage curve from 100% down to roughly 25% coverage
and stops helping at the head — which is exactly where K1 reads.

So the amendment is not "the target was too hard and we tried our best." It is that nine sessions of
work established, with measurements, that the binding constraint is **separability at the head of the
ranking**, and that the rerank margin is not the signal that provides it. That is a specific
unsolved problem, not a shortfall.

## B4 · The field context

No published system reports injection precision at all. Headline LongMemEval results in the 90s are
QA accuracy or Recall@k. The closest independent work on admission thresholds tops out near 0.58.
Every system reaching 90%+ spends materially more than 300 ms, or performs no retrieval and keeps
the log in context.

**K1 set a bar the field does not measure, at a budget the field does not meet.** That was a
deliberate and defensible choice. It is also why there is no prior art to borrow from, and why the
answer had to be measured rather than looked up.

## B5 · What the amended criterion preserves

The original K1 exists to prevent one specific failure: a memory system that injects confidently and
wrongly, corrupting reasoning while appearing to work. **The amended criterion prevents the same
failure by a different route** — the curve makes the precision at any chosen coverage a published
number rather than an assumption, and condition 3 forbids buying coverage with precision.

The flatness kill condition retains the original's teeth. A system whose confidence signal carries
no information still fails, and that failure is still project-level.

---

# Part C — what this amendment does not do

**It does not lower a threshold to match a result.** The frozen-gate discipline has held for ten
sessions specifically to prevent that, and this amendment would be worthless if it were that move
wearing a longer argument. The threshold is not moved; the *criterion shape* changes from a single
point to a published curve, and a new kill condition is added.

**It does not claim K1 was wrong.** K1 was a reasonable bar written before anyone knew what was
reachable. The measurement is what changed.

**It does not close the two remaining directions**, and both are recorded rather than abandoned:

1. **A separability mechanism at the head.** §B3 names the problem precisely: something must make
   the top decile separable, and the rerank margin does not. Unexplored candidates include a
   distinct confidence signal fit against gold rather than against score (ADR-017's rule), and
   set-wise or listwise scoring that observes candidates jointly rather than independently.
2. **The human label set.** ≥400 judged injections, ≥50 per category, judged blind, stratified by
   score decile. **True injection precision — the quantity K1 actually names — has never been
   computed.** Every figure to date is a gold-turn proxy. The label set becomes drawable now that a
   conformal operating point exists to sample from, and it is the only path to the real number.

**It does not authorize skipping the abstention path.** §5.5 is precision-first with recall recovered
through the explicit `recall` tool. If the operating point is 10% coverage, the other 90% must
abstain and the agent must be able to search explicitly. That is M2 work and it is now load-bearing.

---

# Part D — the decision requested

Three options, stated plainly:

**(a) Adopt this amendment.** Publish the curve, declare an operating point, proceed to M1. The
memory subsystem is judged on what it demonstrably does rather than on a threshold measured through
an instrument that could not have passed.

**(b) Hold K1 as written and stop.** Defensible. The bar was set deliberately and it was not met.

**(c) Hold K1 and continue on the two remaining directions** — head separability and the label set —
before deciding. Costs one to three sessions and produces the true injection-precision number for the
first time.

**Recommendation: (a), with (c)'s two directions carried forward as named work rather than as
preconditions.** The measured curve is a better description of the system than a threshold it misses
by an interval, the remaining directions are real but unbounded in time, and Marlowe has been an
engine with no vehicle for ten sessions. M1 and M2 make it usable; the label set becomes cheaper to
produce once there is a running system to produce it from.