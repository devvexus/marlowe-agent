# Session H — the registered significance test had no power, and that is my registration's defect

**Written immediately on reading the held-out result, before `RESULT.md`.** The verdict is not
being softened: both Q1 and Q2 **FAIL** their registered conditions and they stay failed. What this
file records is that **one of the two failure criteria was uninformative by construction**, and the
reader needs to know which, because "failed the delta" and "failed the significance test" carry
completely different weight here.

## What was measured

| | treatment | control | delta | discordant | McNemar p | floor |
|---|---|---|---|---|---|---|
| **Q1** rerank all pruned vs all unpruned | 0.5764 | 0.5633 | **+0.0131** | 3–0 | 0.25 | met |
| **Q2** rerank top-10 pruned vs top-10 unpruned | 0.5764 | 0.5721 | **+0.0044** | 1–0 | 1.00 | met |

Registered bars: `delta >= +0.05`, `p < 0.05`, and `reranked top-1 > 0.5415`. **Both FAIL.**

## The defect

Two-sided exact McNemar is a binomial test on the **discordant pairs only**. With `n` discordant
pairs all falling one way, the smallest achievable p is `2 / 2^n`:

| discordant n | best achievable p | α = 0.05 |
|---|---|---|
| 1 | 1.0000 | unreachable |
| 2 | 0.5000 | unreachable |
| 3 | 0.2500 | unreachable |
| 4 | 0.1250 | unreachable |
| 5 | 0.0625 | unreachable |
| **6** | **0.0312** | **reachable** |

**Q1 had 3 discordant pairs and Q2 had 1.** So `p < 0.05` was **not attainable at any outcome** —
not merely unattained. Had every discordant pair fallen for the treatment, Q1's p would still have
been 0.25. The significance criterion could not have been passed and could not have been failed
informatively; it returned a number that looks like evidence and is not.

## Why my instrument check did not catch it — and this is the point

`PREREGISTRATION.json → instrument_checks.adr_013_can_the_registered_read_vary` required
**≥ 10 discordant cases in both directions**, measured on the fit split. It **passed**, comfortably:
62 discordant, 38 gains, 24 losses.

But it measured the wrong contrast. It compared **reranked top-1 against the pruned-pool gate
top-1** — the ranking the reranker *replaces*. The registered question compares **reranked-pruned
against reranked-unpruned** — two arms that share the same reranker and differ only in which pool
fed it. Those two contrasts have nothing to do with each other's variance, and the second is the one
the McNemar test actually runs on.

> **ADR-013 said: check that the READ can vary, not only that the SHAPE can move the metric.**
> **Session H adds: check that the CONTRAST can vary — the specific difference the registered test
> consumes — not merely that the read can.**

This is the third member of the same family, and it arrived one level further down each time:

1. **ADR-011 / Session D** — the *mechanism* could not move the metric.
2. **ADR-013 / Session G arm 1** — the *read* could not vary (the max-aggregation identity).
3. **Session H, here** — the *read* varies fine; the **contrast between the two arms** does not,
   so the *test statistic* was pinned.

A registration that verifies its read can move has still not verified that its **comparison** can.
The general form: for any paired test, the pre-registration must state the minimum discordant count
its α is attainable at, and the instrument check must confirm the arms actually disagree that often
— on the exact contrast, not on a proxy for it.

## What the result still supports, stated carefully

**The delta criterion is untouched by this and is the informative half.** Q1's point estimate is
+0.0131 and Q2's is +0.0044, against a registered +0.05. Those are point estimates, not tests, and
they are an order of magnitude below the bar. No amount of additional power turns +0.0044 into
+0.05. **The conclusion "session pruning does not deliver the registered improvement" rests on the
deltas and is sound.**

**What is NOT supported** is any claim of the form "pruning was shown not to help, p = 0.25". The
p-values here are artefacts of a test with no power and must not be quoted as evidence of absence.

**The absolute floor passed, and it is a real pass.** Reranked top-1 is **0.5764** against the
registered floor of **0.5415**, the best single cue on the same split. Session D shipped a fusion
worse than its best input, which is why that floor exists; this reranker clears it. That is a
separate registered condition from Q1 and Q2 and it is met.

**The tiny discordance is itself the finding.** Q1 and Q2 differ on 3 and 1 cases out of 229. That
is not noise obscuring an effect — it is the direct observation that **feeding the reranker a
10.3%-of-pool shortlist versus the whole pool changes what it picks almost never.** The reranker's
top-1 is essentially invariant to whether pruning ran. That is a stronger and more interesting
statement than the p-values, it comes from the counts rather than from the test, and it is what
should be carried forward.
