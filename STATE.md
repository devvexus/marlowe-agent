# State

**Updated:** 2026-08-06 — M0b Session H complete. **Code shipped.** The retrieval path prunes and
reranks; R@1 moved **0.5348 → 0.5764**, the first ranker in this project to beat its best single cue.
**Current milestone:** M0b — Sessions A–H complete.

## Next action

**Decide between two named levers, or take the K1 conversation. Session H answered its question and
the answer narrows the field.**

> **The gain is the cross-encoder. It is not the in-session framing.** The reranker gains +0.0393
> over the fitted gate **whether or not the pool was pruned first**. Q1 and Q2 differ on **3 and 1
> cases out of 229**. Session pruning is **closed as a quality mechanism**; it survives only as a
> cost mechanism.

### The lever with a mechanism attached

**Refit the frozen gate on pruned-pool margin distributions.** The only thing that can move the
ceiling and close §4.3's gap. Margins inside a ~50-turn pool are larger than inside a ~487-turn one,
so a curve fit on the pruned distribution would assign materially higher calibrated precision —
which is exactly why reading the *current* curve on a pruned pool would be a silent mismatch, and
why Session H did not. **Needs its own pre-registration, a new gate artifact version and a fresh
fit.** It is a gate refit, not a ranking change, and must not be smuggled into a ranking session.

### The lever that is a contract change

**§4.6 carries no internal session structure.** The harness flattens ~48 haystack sessions into one
history whose `session_id` is the question id, so Session H had to *derive* sessions from
`occurred_at_ms` contiguity. **An M0a change with its own registration** — argued on its merits, not
absorbed as a permanent workaround. Lower value now that pruning is closed as a quality mechanism.

### Second deliverable, still rolled forward: QA accuracy

Needs an API key and a small HTTP client in `tools/`. A credential, not a design question. Build it
in `tools/` as an **offline measurement over retrieval output**. **Registered in advance: a strong
QA number does not satisfy K1 and a weak one does not refute the design.** Report it with its answer
model named — Mastra moved 84.23 → 94.87 on model alone.

**Still standing:** do not scope cues 3–5; do not lower the threshold; do not re-tune the
calibration resolution; do not re-attempt consolidation without a fresh pre-registration; do not
attack arbitration over the full pool again; arms 2, 3 and 4 are closed. **New: do not build a
better session scorer, and do not re-attempt session pruning as a quality mechanism.**

## Session H — the numbers

Full write-up in `runs/session-h/RESULT.md`. Pre-registration at `ab80870`, before the sessionizer
was measured. **ADR-014.**

| | before | after |
|---|---|---|
| R@1 | 0.5348 | **0.5764** |
| R@5 | 0.8130 | **0.8428** |
| R@10 | 0.8826 | **0.9039** |
| oracle R@1 | 0.6435 | 0.6463 — **pinned, not a measurement** |
| ceiling | 0.3739 | 0.3739 — **pinned, not a measurement** |
| retrieval P95 | 33 ms cold subset | **149 ms** warm, full split, passes 300 ms |

Shipped ranker **0.5764** against best single cue **0.5415**: +0.0349. Sessions D, E and F each
shipped a fusion that did not clear that. **At top-10 the shipped ranker is BELOW dense alone**
(0.9039 vs 0.9170) — it is a top-1 mechanism reordering ten candidates.

**The registered question FAILS both sub-questions.** Q1 +0.0131, Q2 +0.0044, against a registered
+0.05. Floor met in both (0.5764 > 0.5415).

### The number that matters for K1

**The reranker is NOT capped by the either-cue oracle and lands below it anyway.** Presence ceiling
**0.9825** against the 0.6435 cap — measured on the fit split before building, per ADR-010. It is
free to reach ~0.98 and reads 0.5764 against a held-out oracle of 0.6463.

> **The bound is a property of the task, not of the combiner.** Sessions D and E were capped *by
> their shape*. This one is not, and performs in the same neighbourhood regardless.

### ADR-014's binding lesson — verify the CONTRAST can vary

**The registered α was unreachable.** Exact McNemar is a binomial over discordant pairs; the
smallest attainable p is `2/2^n` — 0.25 at n=3, 1.0 at n=1. Q1 had 3 discordant pairs, Q2 had 1.
`p < 0.05` was **not attainable at any outcome**. The significance half of both verdicts is
uninformative by construction and **must not be quoted as evidence of absence**. The delta half is
sound and carries the conclusion. Full record in `runs/session-h/POWER-DEFECT.md`.

The ADR-013 instrument check **passed** and measured the wrong contrast — reranked-vs-the-ranking-
it-replaces, where the test consumes reranked-pruned-vs-reranked-unpruned.

> **Binding: a pre-registration using a paired test MUST state the minimum discordant count at which
> its α is attainable, and its instrument check MUST confirm the arms disagree that often, on the
> exact contrast rather than a proxy.**

### The sessionizer failed its registered guard and the session proceeded deliberately

Pool inflation **1.546×** against ≤1.5×. `runs/session-h/BAND-FAILURE-ARGUMENT.md`, written before
the reranker was built. **The band is not edited.** The argument is *not* that the miss was small:
the guard is a proxy for gold damage, and the quantity it proxies for was measured directly and is
exactly zero — gold retention Δ +0.0000, completeness 1.0000, zero gold sessions split. **Do not
inherit "proceeded past a failed band because it was close" — that is not what happened.**

**ADR-014 corollary:** a guard whose primary read directly measures the guard's own concern is
redundant and must be registered as **subordinate** to that read, not as an independent stop.

## Built

**M0b Session H** — first change to the scored retrieval path since C. **188 tests passing** (from
175), `eval/` unchanged at **72**.

`retrieve.rs`: `session_keys`, `surviving_sessions`, pruning after `features::extract_all`, two new
ranking levels above the untouched three. `rerank.rs`: L-2-int8 via `ort`, digests pinned at load,
**batch 1 structurally**, provider required to register via `error_on_failure()`. `occurred_at_ms`
on the payload and entry, `DERIVATION_VERSION` 1 → 2. `--reranking` required with an explicit value.
New in `tools/`: `session_h_pools.py`, `preregister_session_h.py`, `reach_session_h_pruning.py`,
`reach_rerank_fit.py`, `answer_registered_question.py`, `make_cross_encoder_fixtures.py`.

**Earlier sessions:** A (workspace, contracts, journal, memory) · B (lexical cue, frozen gate) ·
C (dense cue) · D (max fusion, **failed floor**, ADR-010) · E (per-query features, **failed floor**,
ADR-011) · F (consolidation, **null**, ADR-012) · G (query side measured, ADR-013).

## Standing checks — re-run on every cue, feature or pool change

- **Offline reachability work must pass a reconstruction fidelity gate first.**
- **A second implementation of a scored-path component must reproduce the first.** Session H:
  binary 0.5764 = offline reconstruction 0.5764, exactly.
- **Pin the ONNX graph optimization level on both sides.** `ort` uses `Level1`; Python defaults to
  `ORT_ENABLE_ALL`, and they fuse the int8 graph differently — **logits 0.0699 apart on identical
  token ids**, nearly twice the batch-invariance failure that blocked adoption in Session G.
- **The artifact the driver reads must be the artifact the run scored with.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue.
- **The unchanged-cue check.** **It is a NULL INSTRUMENT for a pruning change** — it reads exactly
  the three quantities the partition-independent max-aggregation identity pins. Its silence is not
  evidence.
- **`repro --runs 2`, WITHOUT a cache.** Run it *early*. Also catches a batch-invariance regression.
- **The embedding cache's byte-identity test.**
- **`cargo test --workspace` (188) and `cd eval && python -m pytest` (72).**

## Open gaps — each with a named closing condition

### §4.3 maturation has no contract-level coverage
**Closing condition: the gate begins injecting.** It still does not: max calibrated precision
**0.3739** against a 0.95 threshold, and Session H's pruning cannot change that by construction.
Conformance run first, REJECTED with 0 findings — as pre-registered. **The gate refit is the only
named path to closing this.**

### The exported ONNX weights are not independently validated against the published model
**Closing condition: a maintained load path for `jina-embeddings-v2-small-en` outside
`transformers.onnx`, or an alternative authority.** Unchanged. The cross-encoder is a
maintainer-published Xenova export pinned by sha256.

## Known issues

- **Do not quote Session H's McNemar p-values.** The test had no power; see the binding lesson above.
- **Session pruning is closed as a QUALITY mechanism.** It remains a cost mechanism.
- **The additivity read's subsumption rule is defective as registered.** Fix before reusing.
- **Consolidation's retrieval effect is untested at realistic duplicate density.**
- **Trust propagation through a derived belief is STILL unexercised.**
- **The 230 → 229 denominator change must not be ignored in any cross-session comparison.**
- **Every poisoning ASR is 0.000 and VACUOUS.** K3 is the exception and still meaningful.
- **The maturation window is 6h and under tuning pressure. Do not adjust it to make a suite green.**
- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token).
- **`considered` costs a full-store scan per query.** ADR-003's live-only hot index removes it.
- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run **`cleaned`**.
- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.**
- **The headline metric has never been produced.** No human label set exists.
- **The permission layer has no kernel backstop (ADR-002, revised).**
- **M1's §B9 suite must run on both native Windows Terminal and a Linux terminal emulator.**

## Open questions for the human

1. **The K1 conversation, and Session H sharpened it into a specific claim.**
   Four sessions attacked arbitration and were capped by the 0.6435 either-cue oracle *because of
   their shape*. Session H shipped a mechanism that is **provably not capped** — presence ceiling
   0.9825 — and it reads **0.5764** against an oracle of 0.6463. **The bound looks like a property
   of the task, not of the combiner.** If that is right, more arbitration work is not the answer and
   the remaining named levers are the gate refit and the answer stage.

   Comparable numbers: **R@1 0.576, R@5 0.843, R@10 0.904** against oracles of 0.646 / 0.891 / 0.948.
   Injection precision is still 0.3739 against a frozen 0.95. QA accuracy still unmeasured.

2. **The M0a human label set is your deliverable.** ≥400 judged injections, ≥50 per category, judge
   blinded. **Still not drawable at this operating point.**

3. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
