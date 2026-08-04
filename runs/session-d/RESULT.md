# M0b Session D — the fusion

**The session fails its pre-registered floor. No number here is reported as an improvement.**

Pre-registered in `runs/session-d/PREREGISTRATION.json`, committed at `0290a5d` before any fit
existed. Both conditions were fixed while the numbers they judge could not be known.

---

## The finding: calibration and rank preservation are in tension

This is the session's real output, and it is not "max-fusion was the wrong shape."

**Isotonic calibration maps a continuous score to a step function. `max` over step functions has
no resolution at the top — exactly where the operating point reads.**

Measured, not narrated (`tools/analyze_fusion_failure.py`, `runs/session-d/fusion-failure.json`):

| | |
|---|---|
| `lexical_bm25` curve | 230 blocks; **everything above 0.68293 collapses to 0.309013** |
| `dense_cosine` curve | 95 blocks; **everything above 0.832636 collapses to 0.287554** |
| Cases with a tie at the fused maximum | **60.4%** (mean tie 2.72 candidates, p90 6, max 19) |
| Lexical's own head reordered by the tiebreak | **23.0%** of cases |
| ...promoting a higher-dense candidate | 24.8% |
| Gold inside the unorderable band, not picked | **20.9%** of cases |

Lexical alone orders its head by continuous BM25. Max-fusion flattens that head to one value and
hands the decision to the tiebreak — and the pre-registered tiebreak,
`min_calibrated_precision`, is *the other cue's opinion*, so inside a lexical-dominated tie it
defers to dense, the weaker cue at top-1 (0.444 against 0.548).

**Calibration was introduced to make two cues comparable. It does that by destroying the ordering
inside each cue.** Putting cues in common units and preserving within-cue rank are in direct
tension, and any future fusion shape has to answer it.

### The constraint this places on the cascade

The cascade is the pre-registered next shape. **It must not reintroduce this tension**, and the
way to avoid it is structural rather than a matter of care:

> Dense filters by **calibrated precision**; lexical reranks by **raw BM25**. Ordering at the top
> then comes from a continuous score, so the step function never decides a rank.

A cascade that reranked by *calibrated* lexical precision would reproduce Session D exactly. This
constraint is recorded here so the next session inherits it rather than rediscovering it, and it
is to be written into the pre-registration at the same time as `N`.

### The same coarseness appears in two more places

Not three separate problems — one property of the instrument, surfacing three times:

1. **Top-1 ties** (above).
2. **The ceiling is structurally capped** — see below.
3. **Number 2b could not be read at matched coverage.** The registered read point was Session C's
   realised coverage of 0.504274; the nearest cut the v3 curve offers is coverage **0.606838**.
   The comparison is therefore *not* like-for-like and its delta is not a quality signal. Reported
   as such rather than quoted.

---

## The floor — FAIL

**Condition:** any fusion must score at or above its best single input at the operating point;
under 0.5478 at top-1 the session fails outright, no partial credit.

| top-k | lexical | dense | **v3 max-fusion** | v2 linear gate | RRF | either-oracle |
|---|---|---|---|---|---|---|
| **1** | **0.548** | 0.444 | **0.478** | 0.496 | 0.496 | 0.652 |
| 5 | 0.787 | 0.830 | 0.822 | 0.848 | 0.844 | 0.887 |
| 10 | 0.835 | 0.917 | 0.896 | 0.926 | 0.913 | 0.948 |

**0.4783 against a required 0.5478.** Worse than its best single input at every k, and worse than
the v2 linear gate it replaced at every k.

The registered finding, in its own words: *calibrated precision is not a valid cross-cue
arbitration signal at the top of the ranking* — a finding about calibration, not about
linear-vs-max, and not a statement that the parameters need adjusting.

**The oracle read** (fraction of the pre-committed +0.157 gap closed; both denominators, because
quoting only the larger fraction would be denominator-shopping):

| top-k | primary (÷0.1565, from the v2 gate) | secondary (÷0.1044, from best single) |
|---|---|---|
| 1 | **−11.1%** | −66.6% |
| 5 | −66.5% | −15.3% |
| 10 | −140.3% | −71.5% |

**The comparison is valid.** The cue set did not change this session, and the unchanged-cue check
confirms lexical, dense and the oracle are identical to Session C to four decimals. The held-out
population did not move; the fusion did.

---

## The ceiling — the band fired, and the read is confounded

**0.3090**, against Session C's 0.3176 and Session B's 0.309013.

| | Session B | Session C | **Session D** |
|---|---|---|---|
| max calibrated precision | 0.309013 | 0.317597 | **0.309013** |
| what changed | 1 cue | +dense cue | +fusion shape |

The pre-registered band `< 0.35` fired. **Its registered words:**

> *"Two independent structural fixes — a whole new cue in Session C, then the combiner in Session
> D — each moved the ceiling by under 0.05. STOP ADDING CUES AND ESCALATE TO THE HUMAN. The
> binding constraint is the information available to content-similarity retrieval, not the
> combiner and not the cue count. K1 at 0.95 is not on this trajectory."*

**That reading does not hold, and the escalation is not taken.** The band assumed two independent
structural fixes each failing to move the ceiling. What actually happened is one fix that moved it
(+0.0086, Session C) and one shape that **could not move it by construction**:

> Under max-fusion, `max calibrated precision = max_c (cue c's own top block)`. The fusion enters
> the ranking and cannot enter the ceiling at all. v2's joint logistic *could* — and did, reaching
> 0.3176 above both cues' solo ceilings of 0.3090 and 0.2876, because blending produced a joint
> score whose top block was marginally purer than either cue's own.

So this is **one trajectory data point, not two**, and the escalation the band calls for is not
licensed by it. Recorded as: band fired, registered words on the record, read confounded by a
structural cap identified during the session.

**Two predictions this session got wrong, stated plainly:**

1. **Ceiling ≥ 0.42 — falsified.** The band was anchored on the claim that a per-cue curve's top
   block is "far more selective than 0.261 coverage." It is the opposite: the top block holds
   ~466 rows (256 quantile buckets over 119,340), while Number 3's read point holds 165
   attributed candidates. The selectivity comparison was inverted.
2. **The shape was argued on ranking, and its structural cap on the ceiling was missed.** That
   cap is a real cost of the choice and was not in the plan.

### The pre-registration lesson

**A band on a quantity the tested shape cannot structurally move is not a valid read.** Before
registering a band, check that the shape being tested can move the metric it will be judged on.
Both of the above follow from not doing that check — the ceiling band was well-derived, carefully
anchored, and measuring something max-fusion had no mechanism to affect.

This belongs beside the existing discipline, not as a replacement for it: the floor *was* a valid
read, it *was* falsifiable, and it is what makes this session's negative result usable.

---

## The other numbers

| | Session C | **Session D** |
|---|---|---|
| **Number 1** @ frozen 0.95 | abstained on all 249 | **abstained on all 249** |
| **Number 2** cue capability | 0.371 @ cut 0.3176, cov 0.504 | **0.334 @ cut 0.309, cov 0.453** |
| **Number 2b** matched coverage | — | **0.3157 @ cov 0.607 — NOT matched, see above** |
| **Number 3** lexical alone | 0.418 @ 0.261 | **0.418 @ 0.261** (unchanged) |
| **Number 3** dense alone | 0.298 @ 0.282 | **0.298 @ 0.282** (unchanged) |
| retrieval P95 | 36 ms cold | **NOT MEASURED** (cold) / 26 ms warm |
| abstention injections ≤ 0.20 | 0.000, vacuous | 0.000, **vacuous** |
| degenerate-pass guard | triggered | **triggered** |

Number 2 returns to **exactly** Session B's 0.334123, because the v3 read point is lexical's own
top block — which is Session B's curve. Session B fit a logistic on lexical alone, a monotone
transform, and isotonic regression over the same quantile buckets is invariant to it. An
independent confirmation that the new fitter does what it claims.

**Calibration generalization — three pairs, none fired.** The rule is held-out below the fit-split
prediction by more than 0.05 absolute.

| pair | predicted (fit) | measured (held-out) | delta |
|---|---|---|---|
| overall (max over cues) vs Number 2 | 0.309013 | 0.334123 | **+0.0251** |
| `lexical_bm25` vs Number 3 | 0.309013 | 0.418182 | **+0.1092** |
| `dense_cosine` vs Number 3 | 0.287554 | 0.298387 | **+0.0108** |

All conservative, same direction as Sessions B and C. **Computed by the scorer this session**
rather than worked out by hand in prose — a check that only exists when someone remembers to do
the arithmetic is a check that stops happening.

---

## Conditions

| Condition | Result |
|---|---|
| Determinism — `repro --runs 2` | **NOT MEASURED** |
| Budget: P95 ≤ 300 ms, no case > 7,000 tokens | **pass** — **NOT MEASURED** cold; 26 ms warm, 0 cases over |
| False evidence on abstention cases ≤ 0.20 | pass, 0.000 — **vacuously**, nothing injected |
| Degenerate-pass guard (coverage < 0.05) | **triggered** — coverage 0.000 at the operating point |
| `eval/` unchanged | **pass** — 72 tests, `git status -- eval/` clean |

**Ordered gate 1 ran before any quality number**, and came back exactly as pre-registered:
conformance **REJECTED with 0 section-4 findings**, clock probe `fail_no_time_dependence`. Both are
consequences of the empty injected set. The registered regression condition — conformance failing
for a reason *other* than the empty injected set, or the clock probe failing a different check —
did not occur.

Every vacuity predicted in the pre-registration held: poisoning ASRs 0.000 and vacuous, laundering
assertion vacuous, `evidence_precision` 0.0 with an empty denominator, §4.3 maturation still
uncovered at contract level. **None is a Session D regression.**

---

## What shipped

**146 tests passing** (`cargo test --workspace`), up from 125. `eval/` unchanged, zero lines, still
printing 72.

- **`gate/mod.rs` — `frozen-v3`.** Per-cue isotonic curves, `max` fusion, no weight vector and no
  logistic. The refusal set **grew from 11 to 17** and none was removed: added `VersionDisagrees`,
  `FusionDisagrees`, `CueFeaturesDisagree`, `CueCurveMissing`, `CueCurveExtra`,
  `NonCueFeatureNotInert`, `InertFeatureIsACue`, `InertFeatureUnknown`,
  `CurveDuplicateBreakpoint`, `CurvePrecisionOutOfRange`; `PinnedWeightNotZero` was **replaced**
  by coverage enforcement rather than dropped, because with no weight vector the property to
  enforce is that no feature leaves the gate silently.
- **`FusionDisagrees` is the load-bearing one.** The feature *names* are identical across v2 and
  v3, so `FeatureNamesDisagree` cannot see a v2 calibration applied under v3 semantics. Verified
  live in both directions: a v2 artifact is refused on unknown `weights`, and the binary refuses
  the unfitted placeholder naming the command that regenerates it.
- **`CurveDuplicateBreakpoint`** — identified in the plan *before* the fit. Both cue scores have a
  large atom at exactly 0, so quantile bucketing produces blocks sharing a `score_upper`;
  `partition_point` cannot resolve which owns that score, and a `<`-based sortedness check does
  not fire. Fixed at both ends: the fitter pools buckets sharing a bound before PAVA, and the
  load-time refusal catches a fitter regression.
- **The floor interlock — `FailedFloorWouldInject`.** The artifact now carries `floor_verdict`
  (`pass` | `fail` | `unmeasured`) with `floor_required` / `floor_measured` / `floor_read_from`,
  and **a gate whose floor verdict is `fail` cannot load if its calibration would reach the frozen
  threshold.**

  This is the answer to "why does a shape that failed its floor stay embedded?". It stays because
  it injects nothing — and **that argument expires precisely when the next session succeeds**,
  since the cascade's whole goal is to make the gate inject. Leaving the swap to a session
  remembering to do it is the failure mode this project keeps paying for. So it is an interlock:
  a failed floor and a calibration that would inject cannot coexist in a loadable artifact.

  Verified live in both directions — v3 loads at ceiling 0.3090; the same artifact with its top
  block raised to 0.96 is refused, naming
  `analyze_cue_overlap.py --record-verdict` as the way out. Checked on `fail` only, not
  `unmeasured`: the floor is read from a scoring run's feature dump, which needs this gate to load
  in order to produce it, so refusing `unmeasured` would deadlock. `fit_gate.py` writes
  `unmeasured`; `analyze_cue_overlap.py --record-verdict` stamps the measured verdict.
- **`retrieve.rs`** — the pre-registered four-level ranking key.
- **`dump.rs`** — `min_calibrated_precision`, so the driver reproduces the gate's own ordering
  instead of re-implementing the fusion in Python.
- **`tools/`** — `preregister_session_d.py`, `analyze_fusion_failure.py`; `fit_gate.py` rewritten
  per-cue with `fit_logistic` **deleted rather than left unused**; `analyze_cue_overlap.py` gains
  `--run`/`--out`, the gap fractions, the floor verdict and the unchanged-cue check;
  `score_longmemeval.py` gains Number 2b, the computed generalization pairs and
  `--embedding-cache` / `--heldout-only` for the cold read.

### A false rationale found and corrected

`gate/mod.rs` justified the logistic's existence by claiming the harness stratifies its human-label
sample by gate-**score** decile. **It does not.** Both stratification call sites pass
`calibrated_precision`: `eval/src/marlowe_eval/metrics/precision.py:96` and
`eval/src/marlowe_eval/labels/sampler.py:73`. `sampler.py:80` carries `score` onto `SampleDraw` and
nothing reads it. The harness's *parameter* is named `score` (`precision.py:67`) — the name matched
the wire field, so the dependency was inferred rather than checked.

The comment is **corrected, not deleted**, naming both verified call sites so the next reader
re-checks in one step. This is the project's unobservable-mismatch pattern applied to a
*rationale*: the claim could have been removed entirely and every test would have stayed green,
because nothing ever depended on it.

`CONTRACTS.md` §4 was checked before building and does **not** constrain `score` semantically, so
redefining it as a within-curve percentile raises no contract question. Dropping `weights` from the
artifact is likewise not a contract change — §4.4's `Gate` struct is the internal design type; the
wire stamp is `GateStamp {version, threshold, adaptive}` on both sides and carries no weights.

---

## Two numbers this session did not measure

**Retrieval P95 (cold) and `repro --runs 2` are NOT MEASURED.** The session ended before the
cache-cold read finished, and neither was worth holding it open for: the gate abstains on 100% of
queries, so the cold read prices a path that injects nothing, and the warm figure (26 ms) already
clears the 300 ms budget by an order of magnitude with 0 cases over the token budget.

Reported as **not measured** rather than substituted with Session C's 36 ms or with the warm
number wearing a cold label. The cue set and embedder are unchanged from Session C, so its 36 ms
remains the best available reference — but it is a reference, not this session's measurement, and
the next session that produces an injecting gate must measure both properly.

---

## What the next session does

**Not escalation, and not cue 3.** The cascade, pre-registered first:

1. Register `N` from dense's held-out recall curve **before any reranker exists**.
2. **Register the rank-preservation constraint explicitly**: dense filters by calibrated
   precision, lexical reranks by **raw BM25**. The ordering that decides top-1 must come from a
   continuous score.
3. Register a ceiling band **only if the cascade can structurally move the ceiling** — check
   first. A cascade's reachable precision is its reranker's calibration over the filtered set,
   which is *not* obviously capped the way max-fusion's was, but that must be established rather
   than assumed.
4. The floor is unchanged and still ≥ 0.5478 at top-1.

The cascade's top-1 ceiling is dense's R@N (0.917 at N=10) rather than the top-1 oracle 0.652 —
it is the only named shape that can exceed the bound this session was judged against. That is why
it was ranked second rather than discarded, and it is now the only candidate left.
