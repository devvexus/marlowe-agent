# M0b Session C — the dense cue

**Everything below was pre-registered in `PREREGISTRATION.json` and `PREREGISTRATION-model.json`
before the fit ran.** Bands, void conditions, the engine gate, the model condition and the
poisoning prediction were all written first.

## The numbers

| | Session B | Session C |
|---|---|---|
| cues | lexical | lexical + **dense** |
| gate | `frozen-v1`, 4 features | `frozen-v2`, 5 features |
| fit rows / positives | 119,340 / 452 | 119,340 / 452 |
| fitted weights | lexical 12.53 | lexical 4.54, **dense 26.47** |
| **max calibrated precision** | 0.309 | **0.3176** |
| **Number 1** @ frozen 0.95 | abstained everywhere | **abstained everywhere** |
| **Number 2** cue capability | 0.334 @ cut 0.309, cov 0.453 | **0.371 @ cut 0.3176, cov 0.504** |
| verdict against pre-registered bands | functioning, cue set incomplete | **"dense adds nothing measurable"** |
| retrieval P95 | 24 ms | **36 ms** (cold) / 24 ms (warm cache) |

**Number 2 = 0.371 falls in `0.29 ≤ p < 0.39`.** It sits just below Session B's Wilson upper
bound of 0.3804, so the improvement is real in direction and not distinguishable from sampling
noise by the test written before the fit.

**A limitation of the read rule, recorded and NOT used to reinterpret the band.** Number 2 reads
the most selective cut whose coverage still reaches 0.25 — the floor is fixed, the realised
coverage is not. Both moved: 0.334 @ 0.453 → 0.371 @ 0.504. The verdict is correct and it
understates that the cue found more gold *and* was more precise about it. A matched-coverage
comparison is a different statistic and must be pre-registered before a future fit, not
substituted now. Full text in `PREREGISTRATION-model.json`.

**Calibration generalization pair** (standing check): fit-split top block predicted **0.3176**,
held-out measured **0.371** — above prediction, same conservative direction as Session B's
0.309 → 0.334. The pre-registered failure rule (held-out more than 0.05 *below* prediction) did
not fire.

## Number 3, and the question it was built to answer

Per-cue, swept alone at Number 2's read rule:

| cue alone | precision | coverage | gold / distractor |
|---|---|---|---|
| lexical BM25 | **0.418** | 0.261 | 69 / 96 |
| dense cosine | **0.298** | 0.282 | 74 / 174 |

The pre-registered reading fired: *"dense is weaker than lexical alone → the embedder is
suspect; check pooling and normalization against the committed reference vectors first, then the
truncation rate."* **Both named checks were run and both are clean**: pooling agrees with the
maintainer's own pooled graph to 1.08e-7, the embedder reproduces the reference within the
stated tolerance, and truncation is 0.002% of turns at `MAX_SEQ_LEN` 8192. The suspicion was
raised by the pre-registration and is discharged by the evidence the pre-registration named.

### Redundant or complementary? **Complementary, decisively.**

`cue-overlap.json`, held-out, n=230 answerable cases:

- **Per-case rank correlation between the cues: Spearman ρ mean 0.233, median 0.234.** They rank
  candidates almost independently.
- **They find different gold turns:**

| ranker | top-1 | top-5 | top-10 |
|---|---|---|---|
| lexical | 0.548 | 0.787 | 0.835 |
| dense | 0.444 | 0.830 | 0.917 |
| **fitted gate** | **0.496** | **0.848** | **0.926** |
| rank fusion (RRF) | 0.496 | 0.844 | 0.913 |
| **oracle — either cue** | **0.652** | **0.887** | **0.948** |

At top-1, lexical alone finds gold that dense misses in **20.9%** of cases and dense finds gold
lexical misses in **10.4%**. The union reaches 0.652 against 0.548 for the better single cue.

### The finding that matters: they are complementary and the **fusion** loses it

**At top-1 the fitted gate (0.496) is *worse than lexical alone* (0.548)** — `fusion vs best
single −0.052`, and a 0.157 gap to the oracle union. Rank-fusion scores identically, so this is
not an artifact of the cues' incomparable score scales. At top-5 and top-10 the gate does beat
both singles, but only just, and still leaves 0.039 / 0.022 on the table.

The operating point lives in the top-1-ish regime — the calibration's top block is where
predicted precision is highest and candidates are fewest. **That is exactly the regime where the
fusion is worse than its better input.** It explains the headline result directly: a materially
better cue was added, the cues turned out to be near-independent, and the calibration ceiling
moved 0.309 → 0.3176, because the combiner discards the complementarity precisely where the
threshold reads.

**So "content-similarity cues stack poorly" is true of the outcome and false as an explanation.**
They stack poorly *despite* being complementary. The bottleneck is demonstrably the combiner,
not cue similarity.

### What this implies for scoping cue 3 — evidence, not a decision

The pre-committed rule was: *if redundant, build exactly one structurally different cue and
measure the ceiling immediately.* **The premise is refuted**, so that branch does not apply as
written. The measured bottleneck is the fusion, and a third cue added to a combiner that already
degrades its best input at top-1 would most likely reproduce this result.

The headroom a structural cue would target is still real and still unreached — **34.8% of cases
have no gold in either cue's top-1**, and 5.2% have none in either top-10. Nothing here says
entity-graph or temporal cues are unnecessary. It says they are not the *next* thing to measure.

Cheapest next experiment, one session: a fusion that cannot score below its best input (max over
per-cue calibrated precisions, or a combination fit on rank features rather than raw scores),
measured against the same Number 2 read rule and the same frozen threshold.

**Two conditions are pre-committed for that session now**, while the number they judge cannot be
known — they are in `STATE.md`'s *Next action* and must be copied verbatim into its
pre-registration:

1. **Floor condition, hard, not a band.** Any fusion must score at or above its best single input
   at the operating point. Today's gate scores 0.496 at top-1 against lexical's 0.548 and fails
   this floor. If the new fusion still lands under **0.548**, it fails outright and the finding is
   that *linear-score fusion is the wrong shape* — not that the parameters need tuning.
2. **The oracle bound is the read.** Ceiling **+0.157** at top-1. Report the **fraction of that
   gap closed**, not the absolute number: +0.05 means very different things at 30% and at 90% of
   the reachable headroom.

## Conditions

| Condition | Result |
|---|---|
| Determinism (VOID if failed) | **pass** — golden vectors bit-identical across calls, spawns, worker counts 1/3/8; cache hit ≡ miss bit-for-bit |
| Budget: P95 ≤ 300 ms, no case > 7,000 tokens | **pass** — 36 ms cold, 0 cases over |
| False evidence on abstention cases ≤ 0.20 | pass, 0.000 — **vacuously**, nothing injected |
| Degenerate-pass guard (coverage < 0.05) | **triggered** — coverage 0.000 at the operating point |
| Model condition: two cycles ≤ 90 min | **pass** — cycle 1 ≈ 80 min, cycle 2 **12.3 min** cache-served |

**The embedding cache works and is load-bearing as registered.** 190,025 vectors, second full
cycle 740 s against ~80 minutes cold. ADR-004's model choice was conditional on this and the
condition is met.

**Poisoning prediction: not falsified, and still vacuous.** The gate injects nothing, so ASRs
remain 0.000 for the same reason as Session B. Session A's 1.000 stays the reference. This is
not a security result.

**§4.3 maturation did not close.** Conformance: REJECTED, 0 section-4 findings, clock probe
`fail_no_time_dependence` — identical in shape to Session B. The pre-registered stop condition
was *gate injects AND conformance fails*; the gate does not inject, so nothing was lost during
the cue work. The gap's closing condition is unchanged.

## Corrections this session made to its own beliefs

1. **The truncation premise was wrong.** 38.64% of word pieces never reached the embedder at 256
   tokens, and both operator and agent reasoned that Number 2 would substantially measure
   truncation. Within a fixed model, turns truncated at 46% / 34% / 0% give recall@1 of
   0.314 / 0.345 / 0.309 — flat, not monotone. Caught by measurement before the fit.
2. **jina's win was model quality, not window length.** Because the above is flat, the
   8192-token context is not what bought the +31% relative recall@1 over MiniLM.
3. **Chunk-and-pool was measured and rejected**, losing on both axes (recall@1 0.309 vs 0.345, at
   23.9 texts/s/core against a 25 gate) by the exact mechanism predicted in advance.
4. **A stale pin rationale was replaced, not inherited.** Session B pinned `cue_agreement` on
   collinearity; with two cues that argument is false. The pin stands on a freshly stated reason.
5. **The driver reported a verdict against the wrong bands.** `number_two()` had Session B's
   thresholds hardcoded and labelled 0.371 with a Session B band name. The value was right and
   the label was wrong. Fixed structurally: bands are now parsed from the pre-registration, so
   the two cannot disagree again.
6. **Three invented sha256 digests were caught by a load-time refusal** — and one of the three
   was correct by coincidence, which is the argument for load-time refusals in one sentence:
   there is no way to tell a right guess from a wrong one without checking.
