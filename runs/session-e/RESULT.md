# M0b Session E — per-query features

**The session fails its pre-registered floor, by one case in 230. It also confirms its hypothesis
decisively and moves the ceiling further than any previous session.** Both are true, both are
reported, and neither is allowed to soften the other.

Pre-registered in `runs/session-e/PREREGISTRATION.json`, committed at `6148c5e` **before any fit
existed**. Every band and condition below was fixed while the number it judges could not be known.

---

## The hypothesis, and it is confirmed

Lexical alone puts gold at rank 1 in 54.8% of held-out queries. The calibration's best block was
31.0% gold. The claim was that this gap is a **measurement defect**: the isotonic curve pools
~119,340 candidates across all fit queries and asks what fraction of a *raw-score* band is gold,
which requires BM25 and cosine to be comparable **across** queries. They are not —
`lexical::BM25_SATURATION` is deliberately absolute rather than min-max, because min-max forces
every query's best candidate to 1.0 and destroys abstention. So the top block should fill with
candidates from high-scoring **queries** rather than high-scoring **matches**.

### The primary diagnostic — CONCENTRATION CONFIRMED

Measured on the fit split **before any curve was fit**, and it is not marginal:

| ranked by | distinct queries in the top block | of | z vs the no-query-effect null |
|---|---|---|---|
| `lexical_bm25` (pooled) | **133** | 242 | **−16.4** |
| `dense_cosine` (pooled) | 138 | 242 | −15.3 |

The null is **derived, not chosen**: if the top block were a uniform random sample of candidates
the expected coverage is the occupancy result `m·(1−(1−1/m)ⁿ)` = **206.86 ± 4.50** queries. The
pooled block covers 133.

**Concentration alone does not prove the concentration is harmful** — one could argue that queries
with high BM25 genuinely have better matches, so filling the block from them is correct. What
refutes that is the conjunction: those same high-scoring queries yield a block that is only 31%
gold, while taking each query's *own* rank-1 yields 56%. The concentration is spurious, not
informative.

### The direct payoff — Number 3, swept on margin instead of the raw score

Same cue, same scores, same held-out split. Only the question changed:

| swept feature | precision | coverage |
|---|---|---|
| `lexical_bm25` (pooled) | 0.418182 | 0.260684 |
| **`lexical_margin`** (query-local) | **0.579487** | **0.482906** |
| `dense_cosine` (pooled) | 0.298387 | 0.282051 |
| **`dense_margin`** (query-local) | **0.564815** | 0.260684 |

Lexical improves on **both terms at once** — precision +0.161 and coverage nearly doubled. This is
the clearest single statement of the session's finding.

**The raw sweeps are bit-identical to Sessions C and D**, and the unchanged-cue check confirms
lexical / dense / oracle are identical at every k. The held-out population did not move; the
feature did.

---

## The floor — FAIL

**Condition:** top-1 gold-hit rate on the held-out split ≥ **0.5478**, read by
`analyze_cue_overlap.py` over the same 230 answerable-with-gold cases, `hit()` and the
case-selection filter unmodified. Inherited unchanged from Session D.

| top-k | lexical | dense | **v4 gate** | v3 max-fusion | RRF | either-oracle |
|---|---|---|---|---|---|---|
| **1** | **0.548** | 0.444 | **0.543** | 0.478 | 0.496 | 0.652 |
| 5 | 0.787 | 0.830 | 0.817 | 0.822 | 0.844 | 0.887 |
| 10 | 0.835 | 0.917 | 0.878 | 0.896 | 0.913 | 0.948 |

**0.5435 against a required 0.5478 — FAIL.** The gap is 0.0043, which on 230 cases is **exactly one
case**. The session fails outright, as pre-registered: no partial credit, no re-tuning.

**It is a large improvement and it still fails.** Session D scored 0.4783 against the same floor; v4
recovers 0.065 of that and lands at parity-minus-one-case with always-lexical. Recording both facts
because quoting either alone misleads.

### What the failure now means, and it is a different failure

Session D's floor failure was a **calibration** failure — a step function had no resolution at the
top and the tiebreak decided top-1. That is fixed and cannot recur: no calibrated value appears in
the v4 ranking key at all, so the ordering is continuous by construction.

What remains is an **arbitration** failure. The shape still has to choose *which cue speaks for a
candidate*, and choosing by calibrated margin picks wrong slightly more often than never choosing
at all (i.e. always-lexical). Every cue scores a memory in isolation and the gate compares those
isolated opinions; that is the bound.

**This is the finding the next session inherits:** per-query normalization fixes the question the
calibration asks. It does not fix cue selection at rank 1, and no fusion over per-cue scores can,
because the top-1 oracle over both cues is 0.652 and that is the ceiling on perfect arbitration.

---

## The ceiling — CONFIRMED band, and it is the largest movement yet

**0.371245**, against Session D's 0.309013.

| | Session B | Session C | Session D | **Session E** |
|---|---|---|---|---|
| max calibrated precision | 0.309013 | 0.317597 | 0.309013 | **0.371245** |
| what changed | 1 cue | +dense cue | +max fusion | **+per-query features** |
| delta | — | +0.0086 | −0.0086 | **+0.0622** |

**Seven times the movement a whole new cue produced.** Per cue: `lexical_margin` 0.371245,
`dense_margin` 0.336910.

**The band fired unambiguously.** The registered boundaries were CONFIRMED at ≥ 0.33703 and UNMOVED
below 0.354021 — and 0.371245 clears **both**, so only the confirming band fires and the overlap
region was never entered. It also lands 0.011 under the registered upper-bound prediction of
0.382038, consistent with the optimistic bias recorded before the fit.

### The band was demoted before the fit, and the reason matters

**The band-separation check FIRED.** Confirmed ≥ 0.33703 overlaps unmoved < 0.354021, because the
predicted movement (0.309 → 0.382) is smaller than two binomial standard errors on a 466-row block.
A band whose confirming and falsifying regions overlap cannot return a clean verdict.

**δ was not narrowed to force separation.** δ was derived from the block size; shrinking it after
seeing non-separation would be tuning the instrument to guarantee an answer. The band was left
exactly as derived, demoted to a secondary read, and the well-powered `block_concentration`
diagnostic was added as the primary — a test of the same hypothesis that is not resolution-limited.

**This is ADR-010's lesson applied to its mirror image.** Session D registered a band on a quantity
its shape could not move. The symmetric failure is a band whose two verdicts overlap. Both are
unreadable, and both are catchable *before* the fit.

### Two arithmetic corrections, found before the fit rather than after

1. **The gold-bearing fraction.** The top block fills with rank-1s from **all** cases, but only 229
   of 251 fit cases have gold in scope; the other 22 contribute a row to every rank slice and a hit
   to none. The first model conflated the two and inflated the prediction. Each rank slice is now
   scaled by the gold-bearing fraction.
2. **The block is not a random sample.** Only one candidate per query can have a positive margin, so
   the rest of the block is the *least-negative* margins — rank-2s from queries where s₁ ≈ s₂, i.e.
   the queries with no decisive leader, whose rank-2 gold rate is probably below average. The
   prediction was therefore registered as an **upper bound**, not a point estimate.

Both corrections avoid repeating Session D's inverted selectivity comparison. Part of the
54.8% / 31% gap **was never a bug** — a 466-row block and a 251-row rank-1 set are different
populations, and this quantifies how much of the gap that accounts for.

---

## A structural cap, registered before the fit and asserted by test

**`margin` is positive for at most one candidate per cue per query.** An isotonic curve is
non-decreasing, so it cannot give high precision to a negative margin and low precision to a
positive one. Therefore **at most 2 candidates per query can ever clear the threshold**, and usually
exactly one.

Consequences, all registered in advance:
- coverage is capped by the top-1 hit rate;
- `m` (mean injections per firing case) is bounded by 2 and will usually be ~1, which is what makes
  the power floor unreachable on a 249-case split;
- **it is not a defect to fix by widening the feature.** §5.5 is precision-first and recovers recall
  through the explicit search tool. It is the cost of asking a decisiveness question, accepted
  knowingly.

---

## The coverage floor — UNDERPOWERED, exactly as predicted

**Registered explicitly: partial coverage at high precision is a PASS.** §5.5 is precision-first
(*"recall recovered by making the agent's explicit memory search tool excellent"*) and K1's wording
carries no coverage term. A gate firing on 30% of queries at ≥0.95 precision meets K1's stated
requirement and is not a partial success.

The floor is on **attributed injections**, not coverage, because the injection count is what decides
whether a precision number is *readable* and it is exactly computable before the fit:

> `N_min` = 139 — the smallest N whose **Wilson** 95% lower bound at p̂ = 0.95 exceeds 0.90.
> (0.900164 at 139; 0.899932 at 138.) Wilson, never Wald: at p near 1 the normal approximation
> extends above 1.0 and its coverage collapses, which is exactly the regime a 0.95 claim is read in.

**Measured: 0 attributed injections → UNDERPOWERED.** The gate abstains on all 249 held-out cases
because its calibration tops out at 0.371245 against a frozen 0.95. This was the predicted outcome
and is written down as such in the pre-registration; it is a statement about the **instrument**, not
about the gate, and the response is to report it rather than to lower the floor.

**Label-set feasibility — companion, no verdict.** K1's headline needs ≥400 judged injections with
≥50 per category, and the smallest answerable category has 30 cases, so at m = 1 it requires
coverage 1.67 — unmeetable by construction. Registering it as pass/fail would have been the ADR-010
error. Measured: not drawable at this operating point.

---

## The other numbers

| | Session C | Session D | **Session E** |
|---|---|---|---|
| **Number 1** @ frozen 0.95 | abstained on all 249 | abstained on all 249 | **abstained on all 249** |
| **Number 2** cue capability | 0.371 @ cov 0.504 | 0.334 @ cov 0.453 | **0.355 @ cut 0.35, cov 0.650** |
| **Number 2b** matched coverage | — | NOT matched | **NOT matched — delta suppressed** |
| **Number 3** lexical raw | 0.418 @ 0.261 | 0.418 @ 0.261 | **0.418 @ 0.261** (unchanged) |
| **Number 3** dense raw | 0.298 @ 0.282 | 0.298 @ 0.282 | **0.298 @ 0.282** (unchanged) |
| **Number 3** lexical margin | — | — | **0.579 @ 0.483** |
| **Number 3** dense margin | — | — | **0.565 @ 0.261** |
| retrieval P95 | 36 ms cold | NOT MEASURED | **34 ms cold**, 40-case subset |
| degenerate-pass guard | triggered | triggered | **triggered** |

**Number 2 is not comparable across sessions this time, and the file now says so automatically.**
Its rule reads at the most selective cut reaching 0.25 coverage; the v4 curve's nearest such cut
sits at coverage **0.650** against Session C's 0.504. Number 2b exists to compare at matched
coverage and it **could not match either** — so its delta is now **suppressed rather than reported
with a caveat**. Session D hit the same problem and caught it by hand in prose; a check that
depends on someone remembering to do it is a check that stops happening, so
`score_longmemeval.number_two_b` now computes `matched` and refuses to emit a delta when it is
false.

**Calibration generalization — three pairs, none fired.** The rule is held-out below the fit-split
prediction by more than 0.05 absolute.

| pair | predicted (fit) | measured (held-out) | delta |
|---|---|---|---|
| `lexical_margin` | 0.371245 | 0.579487 | **+0.2082** |
| `dense_margin` | 0.336910 | 0.564815 | **+0.2279** |
| overall vs Number 2 | 0.371245 | 0.354839 | −0.0164 |

The per-cue pairs are **like-for-like for the first time**: the curves are fit on margin, so the
held-out measurement they are compared against is now the *margin* sweep. Reading them against the
raw sweep would have compared a margin-fit curve to a raw-score measurement — a mismatch that would
have looked entirely reasonable in the output.

**The oracle read is reported as a diagnostic and carries NO band this session**, because per-query
features cannot move the oracle: within a query, z and margin are monotone transforms of the raw
score, so each cue's rank-1 candidate is unchanged and the oracle is exactly "either cue's rank-1 is
gold". Registering a band on it would have repeated Session D's error verbatim. For the record:
top-1 closes **+30.5%** of the gap on the v2-gate denominator and **−4.1%** on the best-single
denominator.

---

## Conditions

| Condition | Result |
|---|---|
| Determinism — `repro --runs 2` | **PASS**, two identical sha256, on **both** v3 and v4 |
| Budget: P95 ≤ 300 ms, no case > 7,000 tokens | **pass** — **34 ms COLD** (40-case subset), 22 ms warm (full split), 0 cases over |
| False evidence on abstention cases ≤ 0.20 | pass, 0.000 — **vacuously**, nothing injected |
| Degenerate-pass guard (coverage < 0.05) | **triggered** — coverage 0.000 at the operating point |
| `eval/` unchanged | **pass** — 72 tests, `git status -- eval/` clean |
| `cargo test --workspace` | **162 passing**, up from 146 |

**Ordered gate 1 ran before any quality number.** Conformance **REJECTED with 0 section-4 findings**,
clock probe `fail_no_time_dependence` — both consequences of the empty injected set, exactly as
pre-registered. The registered regression condition (conformance failing for a *different* reason,
or the clock probe failing a *different* check) did not occur.

**Determinism deserves a specific note.** Session D changed the gate's arithmetic and the ranking key
without re-verifying reproduction, and a four-level key with 60.4% tie rates is where a
nondeterministic sort would hide. It reproduces bit-identically — the `total_cmp` chain plus a unique
`id` final tiebreak makes the comparator a total order. Session E adds a genuinely new determinism
surface (per-query features are a **reduction** over the candidate set, and floating-point summation
is order-dependent); the reduction order is pinned to candidate-slice index order, the slice order is
the belief store's own `BTreeMap` iteration, and it is asserted by test. Both `repro` runs were made
**without an embedding cache**, so they also cover the embedder across process spawns.

Every vacuity predicted in the pre-registration held: poisoning ASRs 0.000 and vacuous, laundering
assertion vacuous, `evidence_precision` 0.0 with an empty denominator, §4.3 maturation still
uncovered at contract level. **None is a Session E regression.**

---

## What shipped

**162 tests passing**, up from 146. `eval/` **unchanged, zero lines**, still printing 72.

- **`gate/features.rs` — extraction is set-level.** `extract(entry, raw, dense)` is replaced by
  `extract_all(entries, raw, dense)`, because rank, margin and z do not exist for a candidate in
  isolation. There is deliberately **no single-candidate entry point**: one would have to return
  zeros for every per-query feature, and a caller reaching for it would get a silently unrankable
  candidate.
- **A third feature role.** `CUE_FEATURES` (calibrated) / `RANK_FEATURES` (order the ranking, never
  calibrated) / `inert_features` (neither, with a stated reason). v3 had two roles, and calling a
  feature that decides the ordering "inert" would be a false claim on the record — so
  `InertFeatureIsARankFeature` and `RankFeaturesDisagree` exist and the coverage check now spans all
  three. **The refusal set grew and nothing was removed.**
- **`CueSpec`** groups each cue's raw / margin / z names so an index cannot drift between parallel
  arrays, asserted against `FEATURE_NAMES` by test.
- **The margin is computed on RAW BM25, before saturation.** Identified before the fit:
  `saturate(s) = s/(s+10)` compresses the top of the range, so at s=30→0.750 and s=40→0.800 the
  margin is 0.050 while at s=0→0.000 and s=1→0.091 it is 0.091. Computing margin on the saturated
  value would make **low**-score margins look **larger** than high-score ones, inverting the very
  property margin is chosen for. Ranks are unaffected either way, because saturation is monotone.
- **σ = 0 is defined, not defaulted** — the common all-zero-BM25 query gives z = 0.0, matching
  `dense_for`'s existing rule that absent evidence is worth 0.0 and never a skip.
- **The 1.0 top-anchor was removed from the fitter**, and the removal is the point: it marked the end
  of a `[0,1]` feature's range, and margin is unbounded above and negative for every non-leader. It
  was *harmless in effect* — the lookup clamps either way — which is exactly why it would have
  survived as an inherited rule whose stated reason had quietly stopped being true.
- **`min_calibrated_precision` deleted rather than left unused**, from the `Verdict`, the ranking key
  and the dump. ADR-010 measured it deferring to the weaker cue inside a lexical-dominated tie.
- **`dump.rs`** carries `score`, `margin`, `calibrated_precision`, `winning_cue`, so
  `analyze_cue_overlap.py` reproduces the gate's own ordering instead of re-implementing it.
- **The floor interlock carried forward and is now armed.** `floor_verdict: "fail"` is stamped into
  the artifact with `floor_required` 0.5478 and `floor_measured` 0.5435. The gate loads today only
  because it injects nothing; it becomes unloadable the instant its calibration reaches the frozen
  threshold.
- **`tools/preregister_session_e.py`** — derives the ceiling band from measured rank-k rates and
  block arithmetic, computes the occupancy null and the concentration diagnostic, and derives
  `N_min` by Wilson search rather than a rounded closed form.

---

## Two measurement findings, neither of which is a quality number

**1. A cache-cold run cannot complete, and the reason is the harness's deadline.** On a cold cache
the implementation must embed a whole session's turns inside one §4.6 ingest call, and some
LongMemEval sessions exceed the §4.0.7 **30-second** floor — which aborts the run before it scores
anything (`deadline_exceeded` on ingest, after ~129 of 249 sessions). This is an **ingest-throughput**
property, not a retrieval-latency one, and it is new information: no previous session recorded it.

The read was therefore taken over a **40-case subset with a fresh cache: P95 34.0 ms** against the
300 ms budget, consistent with Session C's 36 ms reference. Retrieval P95 is a *per-query* property
— every query still ranks the same ~493 candidates — so the subset measures the same quantity with a
smaller n. The full-split **warm** figure is 22 ms, and it is the one that would have been
misleading: a cache hit removes the query's forward pass from the timed span.

It also clarifies what Session C's "36 ms cold" was — *query*-cold with a corpus-warm cache; the
cold/warm delta is one query forward pass. `--max-cases` was added to `score_longmemeval.py` for the
subset read, and it **refuses to combine with a quality number**, because scoring a subset would be
choosing the population after seeing the split.

**2. `CLAUDE.md`'s documented target was stale** and cost a wasted run: `--embedder-model` has been
required with no default since Session C, and a target without it fails as `implementation_crashed`
on every interface — which reads like a protocol bug and is not one. Corrected, with the reason.

---

## What the next session does

**The cross-encoder, and the floor failure makes it better motivated than the plan assumed.**

The residual is now an **arbitration** failure: every cue scores a memory in isolation and the gate
compares isolated opinions, which bounds top-1 at the either-cue oracle of 0.652. A cross-encoder
reads query and candidate **together in one pass**, so its top-1 ceiling is the *recall of the
candidate pool it reranks* rather than the oracle — it is the only named shape that can exceed the
bound this session was judged against.

**Its pass conditions are already pre-registered** (`cross_encoder_spike` in
`PREREGISTRATION.json`), before any measurement:

- **Latency:** total **cold** retrieval P95 ≤ 300 ms with the reranker inside the timed span, over
  the top 20. §5.7's real requirement, never an invented sub-budget. The stage's own P95 reported
  beside it.
- **Determinism:** bit-identical logit across two process spawns, two ONNX worker-thread counts, and
  **batch 1 vs batch 20**. The last is the one that catches things — batching changes reduction
  order. If it fails, batching is not used and latency is re-read without it.
- **Digest:** model and tokenizer vocab sha256 pinned, verified at **download and load**.
- **Reference:** Rust vs Python onnxruntime on the same pinned graph over pair-encoding hazards, and
  **prefer a maintainer-published ONNX export** so STATE.md's open validation gap does not acquire a
  second instance.
- **One fallback, decided in advance:** if L-6 at `max_seq_len` 512 misses the bar, the single
  registered fallback is `max_seq_len` 256 with the truncation rate reported. If that also misses,
  the reranker is **not adopted at M0b**. No third attempt.

**Do not scope cues 3–5, in either direction.** Registered in all three ceiling bands before the
fit, so a result of any shape leaves it unchanged: 34.8% of held-out cases have gold at rank 1 from
**neither** content cue, and that population is unreachable by any content-similarity cue, third or
otherwise. The named levers are the cross-encoder, then consolidation.

**And state the trajectory honestly.** The ceiling has gone 0.309 → 0.3176 → 0.309 → **0.371** across
four sessions. That is real movement, it is the largest so far, and **it does not extrapolate to
0.95**. The top-1 oracle over both cues is 0.652, so even perfect arbitration between these two cues
cannot reach K1's operating point. K1 at 0.95 is not on this trajectory with two content-similarity
cues — which is what the standing read already said, and this session does not change it.
