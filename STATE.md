# State

**Updated:** 2026-08-05 — M0b **Session F** built. Consolidation is implemented, journaled and
measured, the pre-registered prediction is **confirmed**, and **the named-lever list is now empty**.
**Current milestone:** M0b — Sessions A–F **complete**.

## Next action

**Not a lever. The next conversation is about K1's definition, and that is a human decision.**

Registered in `runs/session-f/PREREGISTRATION.json` **before the result existed**, so it cannot
read as a reaction to a disappointing number: after this session the cross-encoder is out on
latency and consolidation is measured, and **there is no further named mechanism that raises the
either-cue oracle within M0b's budget.**

The question to put to a human is not "what next" but **"is 0.95 injection precision the right bar
for a two-cue content-similarity system whose top-1 oracle caps at 0.65?"** See "Open questions".

**Do not re-attempt consolidation without a fresh pre-registration.** It is built and it works;
the finding is that this corpus has almost nothing to merge. Three future directions are *named
and none was tried*, each needing its own registration: (1) contradiction resolution and fidelity
demotion, the §5.3 parts deliberately deferred here; (2) in-place episode→fact distillation — same
id, same turn, rewritten text, which is the only distillation shape that stays attributable; (3) a
structurally different cue (entity-graph or temporal), which is the only thing left that can
exceed a content-similarity oracle.

**Do not read the null as "consolidation is unnecessary."** Both halves are registered and neither
may be quoted alone — see ADR-012.

**Still standing from Session E, unchanged:** do not scope cues 3–5 on the old reasoning; do not
lower the threshold; do not re-tune the calibration resolution; do not re-attempt the cross-encoder
without a fresh pre-registration.

## The numbers

Full write-up in `runs/session-f/RESULT.md`. Pre-registration committed at `3de5625`, before the
fit existed.

| | Session D | Session E | **Session F** |
|---|---|---|---|
| **Either-cue oracle** top-1 | 0.6522 | 0.6522 | **0.6435** (like-for-like, −0.0087) |
| **Ceiling** (max calibrated precision) | 0.309013 | 0.371245 | **0.3739** |
| **Floor** top-1 | 0.4783 ❌ | 0.5435 vs 0.5478 ❌ | **0.5371 vs 0.5415** ❌ **FAIL, re-based** |
| **Number 1** — pool reduction | — | — | **1.186%** → **PREMISE REFUTED** |
| Number 2 cue capability | 0.334 @ 0.453 | 0.355 @ 0.650 | **0.3612 @ 0.645** |
| Number 3 lexical / dense raw | 0.418 / 0.298 | 0.418 / 0.298 | **0.4343 / 0.3067** |
| Number 3 lexical / dense margin | — | 0.579 / 0.565 | **0.6149 / 0.5728** |
| retrieval P95 (≤300 ms) | NOT MEASURED | 34 ms cold | **33 ms cold**, 19 ms warm |
| consolidation cost per ingest | — | — | **123 ms P95** (0.41% of the 30 s deadline) |

**The R@k table is the deliverable this session, above the ceiling** — it is the input to the K1
decision. Held-out, re-based onto Session E's 230-case denominator:

| ranker | R@1 | R@5 | R@10 |
|---|---|---|---|
| lexical | 0.5478 → **0.5391** | 0.7870 → **0.7870** | 0.8348 → **0.8305** |
| dense | 0.4435 → **0.4435** | 0.8304 → **0.8305** | 0.9174 → **0.9130** |
| **fused gate** | 0.5435 → **0.5348** | 0.8174 → **0.8130** | 0.8783 → **0.8826** |
| RRF (reference) | 0.4957 → **0.4913** | 0.8435 → **0.8391** | 0.9130 → **0.9087** |
| **either-cue oracle** | **0.6522 → 0.6435** | 0.8870 → **0.8869** | 0.9478 → **0.9435** |

**Every movement is one to two cases in 230, against a Wilson half-width of 0.062.** Nothing here
is separable from noise, which is exactly why the oracle carried no band.

**The denominator moved 230 → 229 and that is a finding, not bookkeeping.** One case lost its only
gold turn to a merge, so the analyzer drops it; that is a **miss**, not an exclusion. The table
above counts it as a failure. Raw 229-case figures in `cue-overlap.json` read ~0.004 higher
throughout — **do not quote those against Session E.**

**Why the null, in one line:** LongMemEval-S haystacks are assembled from *distinct real sessions*,
so distractors are topically related rather than textually duplicated. 0.0086% of 30.6M pairs reach
cosine 0.98. The "~493 turns with near-duplicates" this file used to claim is **~493 distinct
turns**.

## Built

**M0b Session F** — consolidation, `frozen-v5` + `consolidation-frozen-v1`. **175 tests passing**,
up from 162. `eval/` **unchanged, zero lines**, still printing 72.

- **`consolidate.rs` — the merge is a supersession edge and mints no new belief.** A cluster elects
  an existing member; the rest get `Superseded` and leave §4.3's candidate set via exclusion (2),
  which already existed. This is what **HP5** specifies, and attribution survives as a consequence:
  every retrievable memory keeps the id ingest returned for exactly one turn.
- **`plan` is pure; `apply` writes.** A dry-run report carries no threshold and `apply` refuses it,
  so the pass the frozen threshold is derived from is *structurally* incapable of applying anything.
- **Complete linkage, measured — single link chains catastrophically.** 40.8% of all 30.6M pairs
  reach cosine 0.70, so at that threshold single link removed **99.8%** of the pool and built a
  **616-member** cluster. Both linkages are swept and both tables are in the pre-registration.
- **The survivor is the LATEST member.** Electing the earliest would suppress gold across the whole
  knowledge-update category, whose difficulty *is* recency.
- **`min_cosine` is over all pairs INSIDE a cluster, not the joining edges** — every joining edge
  is above threshold by construction, so the first version could never have shown transitivity.
- **No on/off flag.** `Policy::load` refuses an unregistered artifact, so a build either merges at
  a registered threshold or does not start. A default-off switch is the permissive default that
  lets a run measure the unconsolidated system under a consolidated label.
- **`tools/dump_consolidation.py`** (dry-run sweep and `--applied` cost read) and
  **`tools/preregister_session_f.py`** (gold-blind threshold choice; carries Session E's read
  rules forward by copy rather than restating them).
- **ADR-012** records the finding, both halves of the non-generalization, and the two decisions
  measurement changed.

**Earlier sessions:** A (workspace, contracts, journal, memory) · B (lexical cue, frozen gate) ·
C (dense cue, jina-v2-small) · D (max fusion, **failed floor**, ADR-010) · E (per-query features,
**failed floor**, ADR-011). See git history and `runs/session-*/RESULT.md`.

## Standing checks — re-run these on every cue, feature or pool change

- **The artifact the driver reads must be the artifact the run scored with.** New, and it exists
  because it broke: Session F's first scoring pass reported v4's ceiling and v4's calibration
  predictions beside v5's held-out measurements. Every measured number was right; only the
  artifact-derived metadata was a version behind, and nothing looked wrong.
  `score_longmemeval.py` now compares the artifact's version against the §4.2 gate stamp on the
  wire and refuses on disagreement. **Fifth instance of the two-sides-disagree pattern, and the
  first in a `tools/` driver.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue, read
  against the sweep of the feature the curve was **fit on** (margin, not raw).
- **The unchanged-cue check.** `lexical` / `dense` / `oracle` must be identical across sessions
  that did not change the cue set **or the candidate pool**. Session F changes the pool, so it
  fired and was pre-registered to. A move that the pool reduction cannot account for is still
  alarming.
- **`repro --runs 2`, WITHOUT an embedding cache.** Session F adds a real new surface —
  agglomerative clustering is order-sensitive unless the union rule is. Pinned: union into the
  numerically smaller index, candidate edges sorted `(−similarity, i, j)`, clusters emitted by
  representative id.
- **The embedding cache's byte-identity test** — a hit and a miss must produce byte-identical
  vectors.
- **`cargo test --workspace` and `cd eval && python -m pytest` printing 72 unchanged.**

## Open gaps — each with a named closing condition

### §4.3 maturation has no contract-level coverage

**Closing condition: the gate begins injecting.** Status unchanged: clock probe **fails**
`no_time_dependence`, conformance **REJECTED with 0 section-4 findings**. Both are consequences of
the empty injected set and the probe is **correct** to fail. **When the gate starts injecting,
re-run `conformance` FIRST**, before any quality number.

### The exported ONNX weights are not independently validated against the published model

**Closing condition: a maintained load path for `jinaai/jina-embeddings-v2-small-en` that does not
go through `transformers.onnx`, or an alternative authority for the same weights.** Unchanged from
Session E — `tests/embedding_reference.rs` validates everything *around* the graph in a second
language, but two graphs from one export prove consistency, not fidelity. **Do not close this by
regenerating the fixture from Rust.**

## Known issues

- **Consolidation is measured on a corpus that has almost nothing to merge, so its retrieval effect
  is untested at realistic duplicate density.** 1.186% pool reduction is not a stress test of the
  merge logic. The clustering, the survivor rule and the reversibility are exercised by unit and
  integration tests; the *quality* consequence of merging is not, and cannot be here.

- **Trust propagation through a derived belief is STILL unexercised, and consolidation arriving did
  not change that.** `ingest.rs` records that `effective_trust` is called with an empty parent list
  so the propagation path would not be "broken when consolidation arrives". Consolidation has now
  arrived and **mints no new belief**, so the path remains untested end to end. It will first be
  exercised by whatever does create a derived belief — contradiction resolution, or in-place
  distillation. Worst-case propagation itself is unit-tested in `trust.rs`.

- **The 230 → 229 denominator change must not be ignored in any cross-session comparison.** A case
  whose only gold turn is suppressed leaves the analyzer's population entirely. Always re-base onto
  the earlier denominator before quoting a delta.

- **Retrieval P95 is 33 ms COLD on a 40-case SUBSET, and the subset is forced.** A fully cache-cold
  full-split run cannot complete: the implementation must embed a whole session's turns inside one
  §4.6 ingest call and some sessions exceed the §4.0.7 30-second deadline. `--max-cases` refuses to
  combine with a quality number. **Consolidation adds 123 ms P95 to that call** — 0.41% of the
  deadline, so it is not what pushes a session over, but it is now on the wrong side of the budget
  and should be watched if ingest work grows.

- **Every poisoning ASR is 0.000 and VACUOUS. Do not quote it as a security result.** A gate that
  injects nothing has a trivially zero attack success rate. **K3 is the exception and is still
  meaningful: unsigned-write ASR 0.000, 4/4 visibly rejected.**

- **The maturation window is 6h and is under tuning pressure. Do not adjust it to make a suite go
  green.** It reads the **ingest clock**, never `occurred_at_ms`.

- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token).

- **`considered` costs a full-store scan per query.** ADR-003's physical live-only hot index is what
  removes it.

- **Retrieval is scoped to the request's `session_id`** — a scope filter, not a relevance judgment.

- **`--suite poisoning` writes an empty `run.jsonl`**; **`timing_tainted` is not wired into
  `report.json`**. Both are harness observations, **not** things to fix in `eval/`.

- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run the **`cleaned`**
  variant; comparison against a published number is invalid unless that number states its variant.

- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.** Reproduced faithfully; the
  harness reports accuracy over the 424 clean cases beside the 500-case headline.

- **The headline metric has never been produced.** No human label set exists, so every run reports
  `injection_precision_human: null`, and at this operating point the label set is **not drawable**.

- **The permission layer has no kernel backstop (ADR-002, revised).**

- **M1's §B9 suite must run on both native Windows Terminal and a Linux terminal emulator.**

## Open questions for the human

1. **The K1 conversation, and it is now the only one.** Four structural fixes have moved the ceiling
   0.309 → 0.374 against a frozen 0.95, and the two-cue top-1 oracle is 0.65 — so even perfect
   arbitration cannot reach the operating point. The named-lever list is empty, and that was
   registered before this session's result existed.

   The comparable numbers, because published LongMemEval results in the 90s are recall@k or QA
   accuracy rather than injection precision: **R@5 0.813 fused / 0.831 dense / 0.839 RRF against an
   0.887 oracle; R@10 0.883 against 0.944.** Those are competitive-shaped. The 0.95
   injection-precision bar is a different quantity.

   The decision is whether K1 means what it was written to mean, or whether it needs restating for
   a system whose retrieval is this good and whose *arbitration* is what caps it. **Raising this as
   the agenda item, not proposing an answer.**

2. **The M0a human label set is your deliverable, not the agent's.** ≥400 judged injections, ≥50 per
   category, judge blinded. **Still not drawable at this operating point.**

3. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
