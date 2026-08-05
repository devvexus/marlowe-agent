# M0b Session F — consolidation, measured

**The prediction was registered before the fit and it is confirmed. Consolidation does not raise
the oracle on this benchmark; it lowers it slightly.** The either-cue top-1 oracle goes
**0.6522 → 0.6435** like-for-like, −0.0087, two cases in 230. Every other ranker is flat or
marginally down.

That is the answer to the question the session existed to ask, and the reason is structural
rather than a tuning miss. It is stated with both halves attached, because a bare null invites two
opposite misreadings and both are wrong.

---

## 1. The headline table — R@k, before and after

`runs/session-e/cue-overlap.json` → `runs/session-f/cue-overlap.json`, held-out split.

**Two denominators, and the difference is a finding rather than bookkeeping.** Session E scored
230 answerable-with-gold cases; Session F scores **229**. One case lost its only gold turn to a
merge, so it has no gold candidate left and the analyzer drops it. **That is a miss, not an
exclusion.** The table below re-bases every "after" figure onto the 230-case denominator, counting
the dropped case as a failure; the raw 229-case figures are in `cue-overlap.json` and read ~0.004
higher throughout.

| ranker | R@1 | R@5 | R@10 |
|---|---|---|---|
| lexical | 0.5478 → **0.5391** (−0.0087) | 0.7870 → **0.7870** (−0.0000) | 0.8348 → **0.8305** (−0.0043) |
| dense | 0.4435 → **0.4435** (−0.0000) | 0.8304 → **0.8305** (+0.0001) | 0.9174 → **0.9130** (−0.0044) |
| **fused gate** | 0.5435 → **0.5348** (−0.0087) | 0.8174 → **0.8130** (−0.0044) | 0.8783 → **0.8826** (+0.0043) |
| RRF (reference) | 0.4957 → **0.4913** (−0.0044) | 0.8435 → **0.8391** (−0.0044) | 0.9130 → **0.9087** (−0.0043) |
| **either-cue oracle** | **0.6522 → 0.6435** (−0.0087) | 0.8870 → **0.8869** (−0.0001) | 0.9478 → **0.9435** (−0.0043) |

Every movement is one to two cases in 230. The Wilson half-width at p≈0.65 over 230 cases is
**0.062**; the largest movement in the table is 0.0087. **Nothing here is separable from noise,
which is why the oracle carried no band.**

**The comparable reading, for the K1 conversation.** Published LongMemEval numbers in the 90s are
recall@k or QA accuracy, not injection precision. On recall@5 this system is at **0.813** (fused
gate), **0.831** (dense alone), **0.839** (RRF), against an either-cue ceiling of **0.887**. At
recall@10 the gate is **0.883** and the oracle **0.944**. Those are the numbers that compare; the
0.95 injection-precision bar is a different quantity and is not on this trajectory.

## 2. The pre-registered numbers

`runs/session-f/PREREGISTRATION.json`, committed at `3de5625` before the fit existed.

| | Session E | **Session F** | verdict |
|---|---|---|---|
| **Number 1** — pool reduction (held-out) | — | **1.186%** | **PREMISE REFUTED** (band: `< 0.03`) |
| **Number 2** — oracle after consolidation | 0.6522 | **0.6435** | no band, by registration |
| **Number 3** — floor, re-based | 0.5435 vs 0.5478 | **0.5371 vs 0.5415** | **FAIL** |
| Ceiling (max calibrated precision) | 0.371245 | **0.373913** | — |
| Number 2 cue capability | 0.355 @ cov 0.650 | **0.3612 @ cov 0.645** | — |
| Number 3 lexical / dense raw | 0.418 / 0.298 | **0.4343 / 0.3067** | moved — expected, see §4 |
| Number 3 lexical / dense margin | 0.579 / 0.565 | **0.6149 / 0.5728** | — |
| retrieval P95 (≤300 ms) | 34 ms cold | **19 ms warm** | passes |
| consolidation cost per ingest | — | **123 ms P95** | 0.41% of the 30 s deadline |
| abstention injections ≤0.20 | 0.000, vacuous | **0.000, vacuous** | — |
| degenerate-pass guard | triggered | **triggered** | — |

### Number 1 is the only well-powered number, and it refutes the session's own premise

`STATE.md` carried the claim that the pool is *"~493 raw conversational turns per query where
near-duplicates compete with gold."* Measured over **30,587,870 pairwise similarities** on the fit
split and 119,563 held-out candidates:

- **1.186%** of the held-out pool is removed at the registered threshold.
- **0.0086%** of all pairs reach cosine 0.98; **0.37%** reach 0.90.
- Mean pool per query **485.9 → 480.2**.

The ~493-turn pool is ~493 **distinct** turns. There is very little for a near-duplicate rule to
remove because there is very little duplication present.

### The floor fails, and it fails against a harder bar than any previous session's

Re-based before the fit: the floor is the best single cue **measured in the same run**, not a
frozen historical number. Consolidation changes the cues, so an inherited floor could have been
cleared on a cue improvement the fusion did not earn.

**Required ≥ 0.5415 (this run's lexical), measured 0.5371.** It also fails against the superseded
0.5478 basis. `floor_verdict: "fail"` is stamped into `gate-frozen-v5.json` and the load interlock
is armed: the artifact becomes unloadable the moment its calibration would reach the threshold.

This is the third consecutive session where the fused gate loses to its own best input at top-1.
That is now a stable property of the two-cue arbitration, not an accident of one shape.

## 3. What the mechanism actually is, and two things measurement changed about it

**The merge is a supersession edge and mints no new belief.** A near-duplicate cluster elects one
of its **existing** members; the rest get `Superseded`, and §4.3's exclusion (2) — which already
existed and was already tested — removes them from the candidate set. This is what **HP5**
specifies (*"merges are supersedes edges and are therefore undoable"*), and the attribution
property falls out of it rather than being arranged for the benchmark: every retrievable memory
keeps the id ingest returned for exactly one turn, so M0a's `Attributor` stays exact and `eval/`
is untouched.

Two design decisions were changed *by* measurement, before the pre-registration was written:

**Single-link clustering is wrong here, and the failure is spectacular.** jina's similarity over
chat turns is anisotropic — **40.8%** of all 30.6M fit-split pairs reach 0.70 — so a transitive
linkage chains. At threshold 0.70 single link removed **99.8%** of the pool and built a
**616-member** "near-duplicate" cluster: the entire session declared one memory. Complete link
ships; single is swept anyway and both tables are in the pre-registration, so the rejection stays
measured rather than becoming folklore.

**The survivor is the LATEST member, not the earliest.** Supersession means a newer belief
displaces an older one, and LongMemEval's **knowledge-update** category is built on exactly that:
the gold turn is the latest statement of a fact whose earlier statements are distractors.
Electing the earliest would have systematically suppressed gold across the one category whose
whole difficulty is recency, and it would have presented as an unexplained retrieval regression.

### The registered attribution risk, and what it cost

Registered in advance: *if consolidation merges a gold turn into a belief with other turns,
attribution may break.* The supersession design removes the id-level version of that hazard
entirely. What remains is a real retrieval failure, and it is reported rather than corrected:

**One held-out case lost its only gold turn to a merge** (2 cases on the fit split at this
threshold). Under a per-turn evidence key that is a genuine miss, not an attribution artifact —
"fixing" it would be the implementation authoring its own measurement. It is the reason the
denominator moved 230 → 229 and the reason §1 re-bases.

## 4. Standing checks

**The unchanged-cue check fired, and it was pre-registered to.** `lexical` 0.5478 → 0.5415,
`dense` 0.4435 → 0.4454, `either_oracle` 0.6522 → 0.6463 (229-case basis). This session changes
the candidate set on purpose, so the check is doing its job. Registered under
`expected_check_failures` before the fit precisely so that a real invariant would not be quietly
reinterpreted on the day it first went off. Number 3's raw pair moved for the same reason.

**Calibration generalization: three pairs, none fired.** Read like-for-like against the margin
sweep, both cues generalize conservatively.

**`repro --runs 2`, without an embedding cache: IDENTICAL.** Consolidation adds a real new
determinism surface — single-link and complete-link agglomeration are both order-sensitive unless
the union rule is — and it is pinned: union into the numerically smaller index, candidate edges
sorted by `(−similarity, i, j)`, clusters emitted by representative id.

**Conformance: REJECTED with 0 section-4 findings, clock probe `fail_no_time_dependence`.**
Unchanged, and still the correct result for a gate that injects nothing.

**`cargo test --workspace` 175 (from 162). `cd eval && python -m pytest` 72, unchanged.**

## 5. A driver bug worth recording, because it is this project's pattern

The first Session F scoring pass reported the **v4** ceiling and the v4 calibration predictions
beside **v5** held-out measurements. Every measured number was correct — those come off the wire —
but `score_longmemeval.py` reads the artifact from disk *by path* while the binary embeds its own
copy with `include_str!`, and the path was not updated with the version bump. Nothing failed and
nothing looked wrong.

Fixed, and closed structurally: the driver now compares the artifact's declared version against
the §4.2 gate stamp the run actually put on the wire, and refuses on disagreement. **This is the
fifth instance of the pattern CLAUDE.md warns about** — two sides silently disagreeing while every
test stays green — and the first one to occur in a `tools/` driver rather than in the
implementation.

**The version bump also went stale in two hand-written test fixtures**, which is the same pattern
in a third place. `gate::tests::fitted_json` and `retrieve::tests::test_gate` both carried
`"version": "frozen-v4"` as a literal; after the bump, 38 tests failed with a version-disagreement
error that had nothing to do with what any of them were testing. Worse was
`a_wrong_version_is_refused`, whose `.replace("frozen-v4", "frozen-v3")` would have found nothing
and left the fixture valid — **a refusal test that silently stops testing its refusal**. Both
fixtures now interpolate `GATE_VERSION`, so the next bump cannot repeat it.

## 6. What this does and does not license

**It does not generalize to real user history.** On real history the same thing genuinely does get
said repeatedly across months, and the duplicate density would be higher. This is evidence about
*this benchmark's candidate pool*. It is **not** evidence that §5.3 consolidation is unnecessary in
production, and the mechanism now exists, is journaled, is reversible, and costs 123 ms per session
close.

**It does close the named-lever list**, which was registered before the result existed. The
cross-encoder is out on latency; consolidation is measured. There is no further named mechanism
that raises the either-cue oracle within M0b's budget. The next conversation is about K1's
definition — what 0.95 injection precision means, and whether it is the right bar for a two-cue
content-similarity system whose oracle caps at 0.65 — and not about the next lever.
