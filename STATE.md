# State

**Updated:** 2026-08-04 — M0b **Session E** built; the hypothesis is **confirmed**, the ceiling moved
further than in any prior session, and the shape **still failed its pre-registered floor by one case**
**Current milestone:** M0b — Sessions A–E **complete**. Next is the **cross-encoder**, not cue 3.

## Next action

**Consolidation. The cross-encoder was spiked this session and is RULED OUT at M0b on latency.**

**Do not re-attempt the cross-encoder without a fresh pre-registration.** Its bar was registered
before it ran; both configurations missed and the registered response is "not adopted at M0b, no
third attempt". Full record in `docs/design/spike-2026-08-04-cross-encoder.md`:

| seq | threads | stage P95 | projected total | speedup got / needed |
|---|---|---|---|---|
| 512 | 16 | 1054 ms | 1088 ms | 2.45× / **9.71×** |
| **256** | **16** | **331 ms** | **365 ms** | 3.33× / **4.14×** |

The closest configuration misses 300 ms by 65 ms — and 16 threads is a workstation, not ADR-003's
1-vCPU target (single-thread: **1136 ms**), the total is an optimistic *sum* of two spans rather than
an end-to-end measurement, and 37.8% of pairs were truncated at seq 256. **Determinism passed
perfectly** (batch 1 vs 20, threads, two processes — all `0.000e+00`), so a future attempt keeps
batching and multi-threading.

**It is ruled out on COST, not on quality — its quality was never measured.** Nothing says a
cross-encoder would not work; only that this one cannot run inside §5.7's budget on this hardware.

**So consolidation is the lever.** ~493 raw turns per case with near-duplicates competing against
gold is the candidate-pool problem, and it is the one named cause of the 54.8% / 31% gap that
Session E did **not** close. Session E closed the calibration cause and measured the arbitration
cause; the pool itself is untouched.

**Three future cross-encoder options are NAMED and NONE was tried** (spike record, §"What a future
attempt would have to pre-register first"): a quantized/shallower encoder, N < 20, or a *conditional*
stage that reranks only when the gate is uncertain. **Do not try them until one passes and report the
winner** — each is a separate pre-registered experiment with its own bar, or none of them is.

**Do not scope cues 3–5, in either direction.** Registered in all three ceiling bands *before* the
fit, so no result reopens it: 34.8% of held-out cases have gold at rank 1 from **neither** content
cue, and that population is unreachable by any content-similarity cue.

**Do not lower the threshold, and do not re-tune the calibration resolution.** Unchanged, now under a
fourth session's worth of pressure. `CALIBRATION_BLOCKS = 256` is additionally an *input* to Session
E's ceiling band, so moving it would move the number the band predicted.

## The numbers

**Pre-registered in `runs/session-e/PREREGISTRATION.json`, committed at `6148c5e` before any fit
existed.** Full write-up in `runs/session-e/RESULT.md`; the mechanism is in the pre-registration's
`block_concentration`.

| | Session C | Session D | **Session E** |
|---|---|---|---|
| **Ceiling** (max calibrated precision) | 0.317597 | 0.309013 | **0.371245** ✅ CONFIRMED band |
| **Floor** top-1 (need ≥ 0.5478) | 0.4957 | 0.4783 | **0.5435** ❌ **FAIL by one case in 230** |
| **Number 1** @ frozen 0.95 | abstained on all 249 | abstained on all 249 | **abstained on all 249** |
| **Number 2** cue capability | 0.371 @ cov 0.504 | 0.334 @ cov 0.453 | **0.355 @ cov 0.650** |
| **Number 2b** matched coverage | — | NOT matched | **NOT matched, delta SUPPRESSED** |
| **Number 3** lexical / dense raw | 0.418 / 0.298 | 0.418 / 0.298 | **0.418 / 0.298** (unchanged) |
| **Number 3** lexical / dense **margin** | — | — | **0.579 / 0.565** |
| retrieval P95 (≤300 ms) | 36 ms cold | NOT MEASURED | **34 ms cold** (40-case subset — see Known issues) |
| abstention injections ≤0.20 | 0.000, vacuous | 0.000, vacuous | 0.000, **vacuous** |
| degenerate-pass guard | triggered | triggered | **triggered** |

**The hypothesis, and it is confirmed decisively.** The pooled calibration asked whether a
candidate's *absolute* score predicts gold, which requires BM25 and cosine to be comparable **across**
queries. Measured before any fit: the pooled top block covers **133 of 242 queries** against an
occupancy null of **206.9 ± 4.5** — **z = −16.4** (dense 138, z = −15.3).

**The clearest single number is Number 3 swept on margin rather than the raw score.** Same cue, same
scores, query-local question: lexical goes **0.418 @ 0.261 coverage → 0.579 @ 0.483**. Both terms
improved and coverage nearly doubled.

**The floor failed and the session fails, as pre-registered.** 0.5435 vs 0.5478 — one case in 230,
and a 0.065 recovery on Session D. Both facts are recorded because quoting either alone misleads.
`floor_verdict: "fail"` is stamped in the artifact and the interlock is armed.

**Ceiling trajectory, stated honestly:** 0.309 → 0.3176 → 0.309 → **0.371**. Largest movement yet
(+0.0622, against +0.0086 for a whole new cue) and **it does not extrapolate to 0.95**. The top-1
oracle over both cues is 0.652, so even perfect arbitration cannot reach K1's operating point. K1 at
0.95 is not on this trajectory with two content-similarity cues.

**Calibration generalization — three pairs, none fired**, and **like-for-like for the first time**:
the curves are fit on margin, so they are compared against the *margin* sweep. `lexical_margin`
0.3712 → 0.5795 (+0.208), `dense_margin` 0.3369 → 0.5648 (+0.228), overall 0.3712 → 0.3548 (−0.016).

**The oracle carries NO band this session, by design.** Per-query features **cannot** move it — within
a query z and margin are monotone transforms of the raw score, so each cue's rank-1 is unchanged and
the oracle is exactly "either cue's rank-1 is gold". Registering a band on it would have repeated
Session D's error. Reported as a diagnostic only: top-1 closes +30.5% on the v2-gate denominator and
−4.1% on the best-single one.

## Built

**M0b Session E** — per-query features, `frozen-v4`. **162 tests passing**, up from 146. `eval/`
**unchanged, zero lines**, still printing 72.

- **`gate/features.rs` — extraction is set-level.** `extract_all(entries, raw, dense)` replaces the
  per-candidate `extract`, because rank, margin and z do not exist for a candidate in isolation.
  **No single-candidate entry point exists**: one would return zeros for every per-query feature and
  a caller reaching for it would get a silently unrankable candidate.
- **A third feature role, with its own refusals.** `CUE_FEATURES` (calibrated) / `RANK_FEATURES`
  (order the ranking, never calibrated) / `inert_features` (neither, with a stated reason). Calling a
  feature that decides the ordering "inert" would be a false claim on the record, so
  `RankFeaturesDisagree` and `InertFeatureIsARankFeature` exist and the coverage check spans all
  three. **The refusal set grew; nothing was removed.**
- **The ranking key contains no calibrated value at all** — `(winning cue's z DESC, its margin DESC,
  id ASC)`. ADR-010 is discharged **structurally**: a step function cannot decide a rank here.
- **`CueSpec`** groups each cue's raw/margin/z names so an index cannot drift between parallel arrays.
- **Margin is computed on RAW BM25, before saturation** — identified before the fit. `s/(s+10)`
  compresses the top, so margins on the saturated value would make *low*-score leads look *larger*
  than high-score ones, inverting the property margin is chosen for.
- **σ = 0 is defined, not defaulted** (z = 0.0), matching `dense_for`'s absent-evidence rule.
- **`min_calibrated_precision` deleted rather than left unused** — from `Verdict`, the key and the
  dump. ADR-010 measured it deferring to the weaker cue inside a lexical-dominated tie.
- **The fitter's 1.0 top-anchor removed**, and the removal is the point: it marked the end of a
  `[0,1]` feature's range and margin is unbounded. It was *harmless in effect*, which is exactly why
  an inherited rule whose reason had stopped being true would have survived.
- **`tools/preregister_session_e.py`** — derives the ceiling band from measured rank-k rates and block
  arithmetic, computes the occupancy null and the concentration diagnostic, and derives `N_min` by
  Wilson search rather than a rounded closed form.
- **`score_longmemeval.py`** — Number 3 gains the margin sweeps (so generalization stays
  like-for-like); the power floor and label-set companion; **`number_two_b` now computes `matched` and
  SUPPRESSES the delta when false**, rather than emitting a non-comparable number with a caveat.
- **ADR-011** records the finding, the arbitration constraint it leaves, the structural cap, and the
  new pre-registration lesson.

**Earlier sessions:** A (workspace, contracts, journal, memory, determinism guards) · B (lexical cue,
frozen gate, absolute normalization) · C (dense cue, jina-v2-small, embedding cache) · D (max fusion,
**failed floor**, ADR-010). See git history and `runs/session-*/RESULT.md`.

## Standing checks — re-run these on every cue or feature change

- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue. A curve that
  predicts well in-sample and badly out-of-sample is a memorized calibration, and it is **invisible in
  every other number**. Rule: held-out below the fit-split prediction by >0.05 absolute.
  **Read it against the sweep of the feature the curve was FIT ON** — Session E fits on margin, so the
  margin sweep is the comparison; using the raw sweep would compare a margin-fit curve to a raw-score
  measurement and look entirely reasonable.
- **The unchanged-cue check.** `lexical` / `dense` / `oracle` at every k must be identical across
  sessions that did not change the cue set. Session E: identical to Session C. A move means the
  held-out **population** changed and every cross-session comparison is invalid.
- **The embedding cache's byte-identity test** — a hit and a miss must produce byte-identical vectors.
  Re-run whenever the model, tokenizer, embedder version or `MAX_SEQ_LEN` changes, not only when the
  cache code changes.
- **`cargo test --workspace`, and `cd eval && python -m pytest` printing 72 unchanged.** A changed eval
  count means the scoreboard was modified.
- **`repro --runs 2`, WITHOUT an embedding cache.** Two cold runs also cover the embedder across
  process spawns. Session E adds a real new surface — per-query features are a **reduction** over the
  candidate set and float summation is order-dependent — pinned to candidate-slice index order (the
  belief store's own `BTreeMap` iteration) and asserted by test.

## Open gaps — each with a named closing condition

### §4.3 maturation has no contract-level coverage

**Closing condition: the gate begins injecting.** Nothing else closes it. Status unchanged: clock
probe **fails** `no_time_dependence`, conformance **REJECTED with 0 section-4 findings**. Both are
consequences of the empty injected set, and the probe is **correct** to fail. Maturation is still
enforced in `entry.rs` and exercised by unit tests, but its effect is **invisible through the
contract** — the mechanism could be removed and every contract-level check would stay as green as it
is now. **When the gate starts injecting, re-run `conformance` FIRST**, before any quality number.

### The exported ONNX weights are not independently validated against the published model

**Closing condition: a maintained load path for `jinaai/jina-embeddings-v2-small-en` that does not go
through `transformers.onnx`, or an alternative authority for the same weights.**

`tests/embedding_reference.rs` checks the Rust embedder against a fixture generated by **Python
onnxruntime on the same pinned `model.onnx`**. That validates everything around the graph —
tokenization, masking, pooling, normalization — in a second language. It does **not** validate that
the export matches the published PyTorch model, and `transformers.onnx` was removed in transformers
5.x so the authority is gone rather than skipped. The maintainer's own pooled graph agrees to
**1.08e-7**, which is a better instrument on the highest-risk component but shares the same export:
two graphs from one export prove consistency, not fidelity. **Do not close this by regenerating the
fixture from Rust** — that makes reference and implementation the same artifact.

**The cross-encoder must not acquire a second instance of this gap** — prefer a maintainer-published
ONNX export, and if none exists, record the gap for that model too rather than papering over it.

## Known issues

- **Retrieval P95 is 34 ms COLD, measured on a 40-case SUBSET, and the subset is forced.** A fully
  cache-cold run **cannot complete**: on a cold cache the implementation must embed a whole session's
  turns inside one §4.6 ingest call, and some LongMemEval sessions exceed the harness's §4.0.7
  **30-second** deadline — which aborts the run before it scores anything (`deadline_exceeded` on
  ingest, after ~129 of 249 sessions). **This is an INGEST-THROUGHPUT property, not a retrieval-latency
  one, and it is new.** It also clarifies Session C's "36 ms cold": that was *query*-cold with a
  corpus-warm cache, and the cold/warm delta is one query forward pass.

  `--max-cases` exists for the subset read and **refuses to combine with a quality number**, because
  scoring a subset would be choosing the population after seeing the split. **Do not "fix" the cold
  read by excluding the embedding from the timed span** — it is a real per-query cost.

- **Every poisoning ASR is 0.000 and VACUOUS. Do not quote it as a security result.** A gate that
  injects nothing has a trivially zero attack success rate; `utility_retention` 0.0 beside each one is
  the AgentDojo pairing saying exactly that. The laundering trust assertion is vacuous too — predicted
  in writing beforehand, precisely so a green suite could not later be read as evidence. **K3 is the
  exception and is still meaningful: unsigned-write ASR 0.000, 4/4 visibly rejected**, measured at the
  write path before any gate exists.

- **The maturation window is 6h and is under tuning pressure. Do not adjust it to make a suite go
  green.** `MATURATION_WINDOW_MS` in `crates/marlowe-memory/src/entry.rs`. It reads the **ingest
  clock**, never the turn's `occurred_at_ms` — a backdated plant must not arrive pre-matured.

- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token). A real
  tokenizer now exists in the dense cue and would lower it; unwired here deliberately, because erring
  high can only make a budget look worse, never hide a miss.

- **`considered` costs a full-store scan per query** — O(store), 246,750 entries on the full corpus.
  ADR-003's physical live-only hot index is what removes it. Do not redefine `considered` to the
  scoped count; that field is a real measurement the report depends on.

- **Retrieval is scoped to the request's `session_id`** — a scope filter, not a relevance judgment.
  It forecloses no LongMemEval category: `datasets/longmemeval.py` merges all of a question's haystack
  sessions into one synthetic per-question session, ~493 turns, and picking gold out of them is the
  actual retrieval problem.

- **`--suite poisoning` writes an empty `run.jsonl`** — the poisoning suite builds its own clients and
  their exchanges are never captured. Harmless for scoring; verify poisoning behaviour against the
  binary directly or run the benchmark suite alongside. A harness observation, **not** something to fix
  in `eval/`.

- **`timing_tainted` is not wired into `report.json`.** The transport raises on a deadline breach and
  `runner.py` records it per-suite, but there is no run-level flag. Carrying it needs a `runner.py`
  change, outside the approved diff. **This is now load-bearing** — the cold-run failure above is
  exactly the case it describes.

- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run the **`cleaned`**
  variant; **variants differ by ~0.5–2 pp, so comparison against a published number is invalid unless
  that number states its variant.** Ours always states `cleaned`.

- **LongMemEval-S penalises correct clock handling on 76 of 500 cases** — questions dated before their
  own history, 43 with gold evidence postdating the question. A property of the corpus, reproduced
  faithfully. The harness reports accuracy over the 424 clean cases beside the 500-case headline.

- **The bit-identical claim excludes timing, by a declared one-key allowlist** (`latency_ms`). No
  tolerance windows anywhere else. Widening that allowlist belongs in an ADR.

- **The headline metric has never been produced.** No human label set exists, so every run reports
  `injection_precision_human: null`. Session E adds the **label-set feasibility companion**: at the
  current operating point K1's label set is **not drawable**, because the smallest answerable category
  has 30 cases and ≥50 per category needs coverage above 1.0 at one injection per case.

- **The permission layer has no kernel backstop (ADR-002, revised).** Declared paths, the
  `(action, target)` split, trust propagation and egress allowlisting are the only wall on the ordinary
  path, so the permission layer carries materially more weight than designed. M2 gains an adversarial
  path-traversal suite plus a TOCTOU requirement (handles, not re-resolved strings).

- **M1's §B9 suite must run on both native Windows Terminal and a Linux terminal emulator.**
  Development is on Windows, so Linux is the surface at risk of CI-only verification.

## Open questions for the human

1. **The M0a human label set is your deliverable, not the agent's.** ≥400 judged injections, ≥50 per
   LongMemEval category, judge blinded to score. Injection precision may not be validated against
   agent-generated relevance labels — that reintroduces the circularity the M0a/M0b split prevents.
   **Session E adds a concrete blocker to plan around:** at this operating point the label set is not
   drawable at all, so the headline stays uncomputable until coverage rises.
2. **HP14 has an experiment attached, not an answer** — deliberately. Needs a consenting cohort at M6.
3. **The trajectory is worth a human read, and it is not an escalation.** Four sessions of structural
   work have moved the ceiling 0.309 → 0.371 against a frozen 0.95, and the two-cue top-1 oracle caps
   perfect arbitration at 0.652. K1 at 0.95 is **not** on this trajectory with content-similarity cues
   alone.

   **The cross-encoder was the named lever that could exceed that oracle, and it is now ruled out at
   M0b on latency** — 365 ms projected against a 300 ms budget in its most generous configuration,
   on hardware more generous than the deployment target. That leaves **consolidation** as the last
   named lever before the cue set itself, and consolidation attacks the candidate pool rather than
   the ceiling directly.

   Raising this as information, not as a request to stop, and **no pre-registered band called for
   escalation this session** — Session D's band did, and its read was recorded as confounded. But a
   human should know that the option space named in Session E's own pre-registration is now one
   item shorter, and that it shortened on a measured budget rather than on a judgement call.

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
