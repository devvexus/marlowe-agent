# State

**Updated:** 2026-08-03 — M0b **Session B** built; the first LongMemEval number exists; HP1 amended
**Current milestone:** M0b — Sessions A and B **complete**. Next is the second cue.

## Next action

**Add the dense cue (ADR-004's local ONNX embedder), then re-fit.** This is what Session B's
numbers point at, and the reasoning is short:

- The frozen gate's isotonic curve **tops out at 0.309 predicted precision**. The operating
  point is 0.95. **There is no score region where one lexical cue can clear K1**, so the gate
  abstains on every query — see *The first number* below.
- Held-out precision at the curve's top block is **0.334 at 0.453 coverage**, which is the
  pre-registered "functioning, cue set incomplete" band. The cue works; four of five are missing.
- Latency has enormous headroom: **P95 24 ms against a 300 ms budget**. A dense cue plus an ANN
  index fits inside it comfortably.

**Do not lower the threshold, and do not re-tune the calibration resolution.** HP1 freezes the
operating point, ROADMAP M10 is the only milestone permitted to move one, and the roadmap says
in as many words that adaptivity is not the remedy for a missed K1. The blocks-per-curve choice
(256, equal-count) was fixed on a stated principle *before* the fit precisely so it could not
become a back-door threshold knob — finer top-end buckets would raise the reachable maximum.

**Do not adjust the maturation window.** Unchanged from Session A, and now under a second kind
of pressure — see *Open gaps*.

**Re-fit deliberately when the cue set changes.** `cue_agreement` is pinned to zero *by
declaration*, not by variance, and that pin is a statement about a one-cue system. It stops
being free the moment the second cue lands.

**Two things to do the moment the gate starts injecting again, in this order:**

1. **Run `conformance` before reading any quality number.** That is the run in which §4.3
   maturation becomes verifiable through the contract again, and it closes the open gap below.
   A silent failure there would mean the defence was lost during the cue work with nothing
   observing it.
2. **Record the calibration generalization pair** — fit-split prediction vs. held-out
   measurement. See *Standing checks*. It is invisible in every other number.

**Amended this session:** `DECISIONS.md` **HP1** gains *The fit/report split* — HP1 said the
weights are fit on benchmark gold evidence and never said what they are then reported against,
which is train-on-test read literally. The amendment pins a pre-registered, category-stratified
split and the rule that the held-out figure is the headline. It also records the two ways a
coefficient can be meaningless, because the first fit produced one of each.

## The first number

**Everything below was pre-registered in `runs/session-b/PREREGISTRATION.json` before the gate
was fit.** Bands, budget conditions, the degenerate-pass guard, and the poisoning vacuity
prediction were all written first; none was edited after a number existed. Full write-up in
`runs/session-b/RESULT.md`.

| | Pre-registered | Measured |
|---|---|---|
| **Number 1** — operating point at frozen 0.95 | *no band, by design* | **gate abstained on all 249 held-out cases.** 0 injections, coverage 0.000 |
| **Number 2** — cue capability | 0.20–0.50 → "functioning, cue set incomplete" | **0.334** at cut 0.309, coverage 0.453 |
| Retrieval P95 ≤ 300 ms | void the numbers if missed | **pass, 24 ms** |
| Injections on abstention cases ≤ 0.20 | | pass, 0.000 — **vacuously** |
| Degenerate-pass guard (coverage < 0.05) | | **triggered** |

**Number 1 in one line: the calibration's maximum predicted precision is 0.309 and the frozen
threshold is 0.95, so nothing can clear it.** That is a result about an incomplete cue set, not
a defect, and it is the outcome the pre-registration named as anticipated.

**`evidence_precision` reads 0.0 on both splits and the value is vacuous** — an empty
denominator. It means *nothing was injected*, not *the injections were wrong*. `summary.json`
carries that on the value itself, next to the contamination label on the all-500 figure.

**A calibration check worth keeping.** The fit predicted 0.309 for its top block on the fit
split; that block measured **0.334 on the held-out split**. The curve generalizes and is
slightly conservative — which is the thing the split exists to be able to say at all.

**The token-budget half of the budget condition is vacuous this run** (max 0 tokens, because
nothing was injected). Only the latency half carries information.

## Built

**M0b Session B** — the lexical cue and the frozen gate. **88 tests passing**
(`cargo test --workspace`), up from 49. `eval/` **unchanged, zero lines** — verified by
`git status -- eval/` and by its suite still printing 72.

- **`cue/lexical.rs`** — BM25, pure Rust. **Not SQLite FTS5, and this is a deviation from what
  this file previously suggested.** FTS5 was never a pinned decision; `DECISIONS.md` does not
  name it and the 2026-08-01 spike used it from Python. Three reasons against it here: `bm25()`
  ranking is a property of the *bundled SQLite version* and `repro` hashes the injected set byte
  for byte, so a dependency bump could move a published number with nothing in the repo
  changing; a second physical index must be kept in sync with §4.3's live-only partition and a
  drift there is unobservable; and an explicit tokenizer is testable where FTS5's is not.
- **Absolute, not min-max, score normalization** (`saturate`, `s/(s+10)`). Min-max is the
  obvious choice and would have destroyed the gate: it forces the best candidate of *every*
  query to 1.0, including queries where nothing matches, so a gate reading it could never
  abstain. Asserted by test.
- **`gate/features.rs`** — deliberately **artifact-free**, which is what lets `--fit-mode`
  produce the fit data without a gate existing yet. No bootstrap placeholder anywhere.
- **`gate/mod.rs`** — frozen weights + isotonic curve, threshold in calibrated-precision units.
  **Nine distinct load-time refusals and no default gate**: unfitted artifact, reordered feature
  names, wrong weight count, a pinned weight that is not zero, a pin naming an unknown feature,
  a non-monotone curve, an unsorted curve, an empty curve, a moved threshold. Verified live —
  the binary refuses the placeholder and names the command that regenerates it.
- **`--dump-gate-features` / `--fit-mode`** — a diagnostic side channel that never changes the
  wire. Under a gate it also carries this build's own `score` and `calibrated_precision` for
  every scored candidate, which is what the curve is read from when the gate abstains and the
  wire therefore carries nothing. The alternative — re-applying the weights in Python — would
  have put a second implementation of the gate's arithmetic beside the real one with nothing
  comparing them.
- **`no_candidate_above_threshold`** is now truthful for the first time; Session A correctly
  refused to use it because no threshold existed.
- **`tools/`** — `preregister_split.py`, `fit_gate.py`, `score_longmemeval.py`. They import
  `marlowe_eval` as a library and change nothing in it. The harness deliberately exposes no
  real-corpus path; adding `--corpus-path` would be the implementation reshaping the
  scoreboard's interface for its own convenience, and if that flag is right it is an M0a change
  argued separately.

**M0b Session A** — Rust workspace, `crates/`. **49 tests passing** (`cargo test --workspace`).
Toolchain: MSVC 14.44 + Windows SDK 10.0.22621, rustc 1.97.1 `stable-x86_64-pc-windows-msvc`.

- **`marlowe-contract`** — §4 as serde types. Closed enums with **no `Other` variant**, so an
  unknown `channel` fails to deserialize and becomes a §4.0.4 class A `malformed_body` rather
  than a default. `ContractVersion` is a zero-sized type that can only serialize to the
  constant — a `String` field with `#[serde(default)]` looked equivalent and was not, because
  `default` applies only to *de*serialization and these responses are serialize-only.
- **`marlowe-journal`** — §1. Append is the only write path; `AppendRequest` carries no `seq`,
  `ts` or `signature`, and `JournalEvent`'s signature field has no public constructor. Hash
  chain (§1 as amended). `replay` requires an `OperatorCapability` (invariant 8).
- **`marlowe-memory`** — §§2–3. Trust derived from channel through a **total match with no
  catch-all arm**; `check_actor` returns `Option<RejectionReason>` and so *cannot* elevate.
  Belief store is a **versioned derivation** over the log — the ADR-009 mechanism, and it is
  the only constructor that reads history, so it runs on every open rather than on a rare
  migration.
- **`marlowe`** — `--eval-adapter --profile-root <DIR>`, NDJSON over stdio. `--profile-root` is
  required with no default, and `Profile::init` refuses a non-empty directory.
- **The latency fence** (`elapsed.rs`) — the one legitimate real-clock read, isolated so the
  guard can name it. `ElapsedMs` has one accessor, `as_cost_ms`.
- **Three determinism guards** — `HashMap`/`HashSet` banned outright; `Instant`/`SystemTime`/
  `UNIX_EPOCH` banned outside the fence; ids not built from time values.

**Measured against the M0a harness, not asserted** (target
`exec://target/release/marlowe.exe --eval-adapter --profile-root {profile_root}`):

| Check | Result |
|---|---|
| `conformance` — all three interfaces | **CONFORMS**, 0 findings |
| Clock probe | **pass** — translation-invariant *and* time-dependent |
| **K3: unsigned-write ASR** | **0.000** — 4/4 `visibly_rejected`, 0 injected |
| **Laundering trust assertions** | **16 checked, 0 failed**, and **non-vacuous** — the planted memory reached the injected set, so its derived trust was genuinely read |
| `repro --runs 2` | two identical sha256 |
| Protocol errors, full run | 0 |
| Retrieval tokens | mean 31.75, max 51, 0 over the 7,000 budget |

`eval/` — the M0a harness. Python, separate artifact per ADR-001, depends on `CONTRACTS.md`
§4 and nothing else (enforced by a test). **72 tests passing** — unchanged across this
session's two-file transport addition, verified before and after.

- **`adapter/subprocess_ndjson.py` + the `exec://` target** — written this session, completing
  the one M0a component deliberately deferred until §4.0 was pinned. Eleven deliberately
  broken targets, eleven correct rejections, including the class A / class B split. The CRLF
  check is the one that only works because the pipes are binary: text mode would have
  rewritten `\r\n` to `\n` and the check would have passed while testing nothing.
- `contract/errors.py` gained the §4.0.4 kinds as real enum members. An earlier draft carried
  the true kind in a side attribute while the typed field held an approximation — two fields
  that must agree with only one checked, which is the pattern this project keeps paying for.

- **`contract/`** — §4 as executable schema. `cost` required on all three interfaces; hedged
  abstention, injected tombstones, both directions of §4.2's abstention exclusivity and
  §4.7's symmetry are `ProtocolError`s. JSON Schema export for third parties.
- **Reference stub + 11 conformance fixtures** — one deliberately broken target per rule the
  harness claims to enforce. The stub reads the answer key; its selection function takes
  `(query_id, rng)` and never the query text, so it cannot become a retriever. Asserted by
  test. Its origin→trust table is total over the closed channel set with **no default**.
- **Suites** — benchmark, conformance, clock probe, staleness sweep, poisoning (MINJA,
  MemoryGraft, laundering, delayed-trigger, unsigned-write).
- **Metrics** — three separately-named precisions (no field called `injection_precision`),
  accuracy + abstention, cost, staleness. `Scored` cannot be built without a `CostSummary`;
  `PoisoningResult` cannot be built without utility retention.
- **Judge + labels** — blinded stratified sampler (score, position and injected-flag leaks all
  closed, with decoys); verdict cache; agreement/κ. `AnthropicJudge` refuses to construct
  without a two-part opt-in **and** a human label set; `JudgedPrecision` refuses without an
  `Agreement`.
- **`METHODOLOGY.md`** — including §12, what the harness cannot tell you.

**Proved by measurement, not assertion** (all reproducible from `eval/README.md`):

| Check | Result |
|---|---|
| Instrument recovers its own input | precision knob 0.5/0.7/0.9 → measured 0.456/0.687/0.899 |
| Staleness probe recovers a planted half-life | stub 7.0 d → measured 7.3 d |
| Missing `cost` rejected on all three interfaces | 3 findings, exit 1 |
| Clock probe discriminates | `oracle` passes; `broken.clock_reader` fails `no_time_dependence` |
| Laundering suite discriminates | `oracle` 0 failures; `broken.trust_launderer` 9/16, naming `web → user_asserted` |
| Bit-identical reproduction at fixed seed + clock | two runs, identical sha256 |
| LongMemEval-S adapter against the real release | 500 q / 246,750 turns / 30 abstention, no findings |

## Previously built

Design only — see git history for the 2026-08-01 session.

- `docs/design/ARCHITECTURE.md` — core abstraction, component boundaries, agent loop in
  pseudocode, invariant-enforcement table (7 from the brief + 2 pinned this session),
  simplicity-budget audit, process model.
- `docs/design/CONTRACTS.md` — pinned schemas. Journal, memory envelope + payloads, trust
  propagation, the M0a↔M0b retrieval interface, runs, sessions, skill/tool manifests,
  permission, trust ledger, people/commitments, connections, loop-boundary types, surfaces.
- `docs/design/DECISIONS.md` — all 16 hard problems answered (choice / rejected / cost, with the
  unsolved ones named as unsolved and given a resolving experiment) + 8 infrastructure ADRs.
- `docs/design/ROADMAP.md` — M0a…M10, kill criteria K1–K6, per-milestone acceptance drawn from
  the requirements' numeric targets.
- `docs/design/spike-2026-08-01.md` — storage spike record. Backs ADR-003.

**Proved by measurement, not argument** (spike, 1 pinned vCPU, concurrent durable writes):
single journal passes both pre-committed gates; retrieval P95 16.2 ms with a live-only hot index
vs. 94.9 ms without; append 633/s; index rebuild 11.7 s reproducing **exact per-entry fidelity,
0 mismatches**.

## In progress

Nothing half-done. Session B's scope is closed and both pre-registered numbers are measured.

**Expected and honest, not failures** — a later session must not read these as regressions:

| Number | Why |
|---|---|
| LongMemEval accuracy **0%** | No generator is wired, and none was in scope. Every answer is an honest abstention (`degraded_path`), 0 fabrications. **K2 is not in reach and is not claimed.** |
| `evidence_precision` **0.0 on both splits** | Vacuous — an empty denominator, because the gate injected nothing. It does **not** mean the injections were wrong. Carried on the value itself in `summary.json` |
| Gate abstains on 100% of queries | Number 1. The calibration tops out at 0.309 predicted precision against a frozen 0.95 |
| MINJA / MemoryGraft / delayed-trigger ASR **0.000** | **Vacuous** — see the second known issue. Not a security result |
| Utility retention **0.0** | A ratio over answer accuracy, and the denominator is 0 |
| Staleness half-life **not measured** | Supersession *machinery* exists; the contradiction *detector* is retrieval quality and waits. Reported as unmeasured rather than extrapolated |
| Only the latency half of the budget condition is informative | Token max is 0 because nothing was injected. P95 24 ms is a real measurement — the cue really did rank ~493 candidates per query |

## Open gaps — each with a named closing condition

Not "known issues to live with". Each of these is currently *uncovered*, and each has a
condition that closes it. A session that satisfies the condition must re-run the check and move
the entry out of this section.

### §4.3 maturation has no contract-level coverage

**Closing condition: the gate begins injecting.** Nothing else closes it — not a code change,
not a new unit test.

**Status.** The clock probe **fails** (`fail_no_time_dependence`) and conformance reports
**REJECTED with 0 section 4 findings**. Session A passed both.

**The cause is Number 1, not a clock bug.** Maturation was observable in Session A because the
injected set grew as entries matured. With the gate abstaining on every query the injected set
is empty at every clock value, so there is no time dependence for the probe to find. The probe
is **correct to fail** — this file already recorded that an implementation with no observable
time-dependence fails correctly, because §4.3 maturation is a requirement.

**What is actually uncovered.** Maturation is still enforced in `entry.rs` and still exercised
by Rust unit tests, but **its effect is invisible through the section 4 contract**. That is this
project's own unobservable-mismatch pattern applied to a *defence* rather than a bug: the
mechanism could be removed entirely and every contract-level check would stay exactly as green
as it is now. This is the strongest argument in the Session B data for completing the cue set
rather than lowering the threshold.

**It was not fixed by weakening the gate, and must not be.** When the gate starts injecting,
re-run `conformance` first — before reading any quality number — because that is the run in
which the maturation defence becomes verifiable again, and a silent failure there would mean the
defence was lost at some point during the cue work with nothing observing it.

## Standing checks — re-run these on every cue addition

- **Calibration generalization: fit-split prediction vs. held-out measurement.** Session B:
  the isotonic curve's top block predicted **0.309** on the fit split and measured **0.334** on
  the held-out split — generalizing, and slightly conservative.

  **Re-run at every cue addition and every re-fit, and record both numbers.** A curve that
  predicts well in-sample and badly out-of-sample is a memorized calibration, and the failure is
  invisible in every other number the harness produces: precision, coverage, ASR and latency all
  look identical whether the curve generalizes or not. The only place it shows is this
  comparison, so it only exists if someone looks. A later fit whose held-out measurement falls
  materially *below* its fit-split prediction is a signal about the **calibration**, not about
  the cue — investigate the fit before adding anything else.

  The comparison is the top block's predicted precision (`max` of `isotonic_breakpoints` in the
  artifact) against `number_2_cue_capability.value` in `runs/<session>/summary.json`.

- **`cargo test --workspace`, and `cd eval && python -m pytest` printing 72 unchanged.** A
  changed eval count means the scoreboard was modified.

## Known issues

- **Every poisoning ASR is now 0.000, and the number is VACUOUS. Do not quote it as a security
  result.** MINJA, MemoryGraft and delayed-trigger all fell from 1.000 to 0.000 — because a gate
  that injects nothing has an attack success rate of zero trivially. `utility_retention` is 0.0
  beside each one, which is the AgentDojo pairing saying exactly that. Session A's 1.000 and
  Session B's 0.000 are both artifacts of the injection rate, not measurements of discrimination.

  **The laundering trust assertion is now vacuous too — 16 checked, 0 failed, nothing observed.**
  This was *predicted in writing before the run* (`PREREGISTRATION.json`), precisely so that a
  green suite with no record of what was expected could not later be read as evidence. Session A
  is the run where that assertion was non-vacuous, and it stays the reference.

  **K3 is the exception and is still meaningful: unsigned-write ASR 0.000, 4/4 visibly
  rejected.** It is measured at the write path, before any gate exists, so its value does not
  depend on whether anything is injected.

- **The maturation window is 6h, and it is under tuning pressure. Do not adjust it to make a
  suite go green.** `MATURATION_WINDOW_MS` in `crates/marlowe-memory/src/entry.rs`.

  *Why 6h:* brief §5.3 requires "corroboration or elapsed stability" and pins no number. Six
  hours sits inside a working day, so a fact the user states in the morning is usable that
  afternoon, while a single-exposure plant must survive half a day during which contradiction
  can supersede it. Chosen on those grounds alone.

  *The pressure, named:* `poisoning._observed_trust` in the harness returns `None` when the
  planted memory was never injected, and the suite **scores that as a pass**. The laundering
  assertion is therefore only informative if the attack memory is matured by the trigger query
  — which the suite fires at plant + 1 day. **6h was not chosen to sit under that trigger**,
  and a future session must not "fix" a vacuous laundering result by moving the window. The
  correct response to a vacuous assertion is to report it as vacuous. The eval adapter does.

  Two related facts a later session will need: maturation reads the **ingest clock**, never
  the turn's `occurred_at_ms` — using the turn's own time would let a backdated plant arrive
  pre-matured, handing over the defence in the payload. And with no gate yet, the laundering
  assertion is at its *most* informative, because the attack memory is actually injected and
  its derived trust is actually read; a good gate suppresses the injection and turns the
  assertion back into a silent pass. Verifying trust propagation before there is a gate is the
  only time it is cheap to verify properly.

- **`retrieval_tokens` is a pessimistic estimate, not a token count.** No tokenizer exists yet
  (ADR-004's model is unwired), so `retrieve.rs` uses 3 chars/token — deliberately *over*-
  estimating, because erring high can only make a budget look worse, never hide a miss against
  §5.7's ≤7,000. Replace it with a real tokenizer when the embedder lands, and expect the
  reported number to **fall**. Untested against a real load so far: the gate injected nothing,
  so the estimator has never had to price a non-empty set on the real corpus.

- **`considered` costs a full-store scan per query.** `injection_candidates` walks every entry
  in the belief store (246,750 on the full corpus) before session scoping, because `considered`
  is defined as the true size of the set passing §4.3's exclusions across the whole store.
  Measured P95 is 24 ms so it is nowhere near the budget, but it is O(store) per query and
  ADR-003's physical live-only hot index — an M0b requirement, not yet built — is what removes
  it. Do not "optimize" it by redefining `considered` to the scoped count; that field is a real
  measurement the report depends on.

- **Retrieval is scoped to the request's `session_id`** — a scope filter, not a relevance
  judgment. The cue is what judges relevance inside it.

  **Session scoping does not foreclose any LongMemEval category, including multi-session.**
  `datasets/longmemeval.py` merges *all* of a question's haystack sessions into one synthetic
  per-question session (`case_session = qid`), so every candidate for a question is already in
  scope. That is about **493 turns per case**, and picking the handful of gold turns out of them
  is the actual retrieval problem — the same problem in every category.

  *(Corrected 2026-08-03. The Session A version of this entry claimed the opposite and was
  wrong; the claim above is the one to use.)*

- **`--suite poisoning` writes an empty `run.jsonl`.** `runner.py` extends the transcript only
  inside the benchmark block; the poisoning suite builds its own clients and their exchanges
  are never captured. Harmless for scoring, but it cost this session a wrong verification —
  a check that read `run.jsonl` after a poisoning-only run found zero attack memories and
  looked like a real failure. Verify poisoning behaviour against the binary directly, or run
  the benchmark suite alongside. **A harness observation, not something to fix in `eval/`.**

- **`timing_tainted` is still not wired into `report.json`.** §4.0.7 says a harness-imposed
  deadline marks the run timing-tainted with a hash that is not comparable, and `canonical.py`
  already describes the flag. The transport raises a `TransportError` on deadline breach, which
  `runner.py` records per-suite and continues from — but there is no run-level flag. Carrying
  it needs a `runner.py` change, which was outside the approved diff.

- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** `verify-corpus`
  passed against the real release — 500 questions, 500 sessions, 246,750 turns, 30 abstention,
  all seven categories, no dangling gold ids — and its digest is now pinned in
  `datasets/fetch.py`. We run the **`cleaned`** variant: the maintainer's own published
  replacement (`xiaowu0162/longmemeval` is deprecated in its favour), which removes noisy
  history sessions that interfered with answer correctness. **Variants differ by ~0.5–2 pp, so
  comparison against a published number is invalid unless that number states its variant —
  many do not. Ours always states `cleaned`.** The LoCoMo adapter is still written from the
  published schema alone, and its fixtures cannot catch a misreading — same hand wrote both.
- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.** Questions dated before
  their own history (up to 0.99 d), **43 with gold evidence postdating the question**;
  concentrated in temporal-reasoning (54), knowledge-update (15), abstention (7). A property of
  the corpus, reproduced faithfully and not corrected. **A system honouring §4.5 is penalised
  relative to one ignoring the clock**, so the headline understates correct behaviour. Reported
  as a `verify-corpus` statistic, and the harness reports accuracy over the 424 clean cases
  beside the 500-case headline as a clock-handling diagnostic. See METHODOLOGY.md §11 before
  comparing this number to a vendor's.
- **The bit-identical claim excludes timing, by a declared one-key allowlist** (`latency_ms`).
  Latency is self-reported by the implementation and varies by nature; it is recorded, scored,
  and not hashed. No tolerance windows anywhere else — any other off-allowlist variance is a
  failure. Widening that allowlist weakens the acceptance criterion and belongs in an ADR.
- **The reference stub's latencies are synthetic**, so a stub run's P95 measures nothing. It
  has no clock to time itself with, and inventing a wall-clock reading is what §4.5 forbids.
- **The headline metric has never been produced.** No human label set exists, so every run so
  far reports `injection_precision_human: null` with a note saying K1 was not measured.
- **The clock probe cannot prove absence.** It catches an implementation whose behaviour moves
  with a system clock; it cannot prove one never reads it. An implementation with no
  observable time-dependence fails — correctly, since §4.3 maturation is a requirement.
- **The permission layer has no kernel backstop (ADR-002, revised 2026-08-02).** Marlowe runs
  on the real filesystem by default; kernel sandboxing is retained only for the quarantined
  reader (`reads_untrusted: true`, empty tool set). Declared paths, the `(action, target)`
  split, trust propagation and egress allowlisting are now the only wall on the ordinary path,
  **so the permission layer carries materially more weight than it was designed to carry.**
  Consequences: §8.3's AgentDojo ASR becomes a first-order number rather than a
  defence-in-depth check, and **path scoping becomes a security boundary** — M2 gains an
  adversarial path-traversal suite plus a TOCTOU requirement (operate on handles, not
  re-resolved strings).
- **Brief §8.2 was amended to match (2026-08-02), not left as a deviation.** §8.1's premise is
  untouched — trifecta real, filtering fails, containment answers — and only the location of
  containment changed. The divergence from the original differentiator and its cost are stated
  in the requirement itself, so a future reader meets them where they meet the claim.
- **M1's §B9 suite must run on both native Windows Terminal and a Linux terminal emulator.**
  The requirement is unchanged but its direction inverted: development is now on Windows, so
  Linux is the surface at risk of being verified only in CI.
- The spike's aged shape is statistical, not a real workload. The tombstone curve gives the
  forgetting policy a budget; it does not predict where a real user lands on it.
- Retrieval *quality* is entirely unmeasured. The spike settled cost only.

Two former entries here are now M0b scope with acceptance tests, not notes: **group commit**
(tested at ≥50/s under emulated VPS fsync, not the 633/s workstation figure) and **ANN + int8**
(accepted on recall@50 ≥0.99 against brute-force ground truth, not on latency).

## Open questions for the human

1. **The M0a human label set is your deliverable, not the agent's.** ≥400 judged injections,
   ≥50 per LongMemEval category, stratified by gate-score decile, judge blinded to score.
   Injection precision may not be validated against agent-generated relevance labels — that
   reintroduces the circularity the M0a/M0b split exists to prevent. M0b cannot report its
   headline metric without this.
2. **HP14 has an experiment attached, not an answer** — deliberately, and confirmed. The
   falsification condition and its replacement (hard periodic re-consent on tier ≥4) are now
   pinned in the ADR. Needs a consenting cohort at M6.
*Resolved 2026-08-01:* the §A10/§B10 web-UI tension. B10 stands — terminal-native is the
deliberate position, and A10's channel list was written against cloud-only competitors.

*Resolved 2026-08-03:* **`MemoryEntry` does not carry a structural-signature field.** See
`DECISIONS.md` **ADR-009**, which states the reasons in the order they should be reused.

**The primary reason is correctness, not schema cost.** A signature computed at write time and
stored on the envelope does not demote when the entry's fidelity does, so it keeps matching at full
strength on a Gist — accessibility restored through a side channel, which is §5.4's worst-failure
clause. Under §3.4 it is worse: a plaintext signature outside the encrypted record survives
crypto-shredding, which is an invariant 5 hole. Making it demote and shred correctly is a second
lifecycle nobody has specified or costed.

**The cost model this question was framed on was wrong in all three parts. Corrected here so a
later session does not reuse the prices as precedent:**

| This file previously said | Actually |
|---|---|
| A contract **major** version bump | §3 crosses no process line — §4 is the only contract that does — and an **optional** field is additive, which this project's own precedents call **minor** (`CONTRACTS.md` §1.1, §3.2) |
| A **journal migration** | The belief store is a materialized view; no journal event payload changes, so §1's forever-decodable rule is never engaged |
| Re-deriving **across full history** | Invariant 9 permits derivation only over live entries at current fidelity. Deriving over the forgotten tail is **forbidden**, not merely expensive — it is the same leak described above |

Real late-adoption price: a minor bump plus one rebuild, which ADR-003 already commits to and
measured at 11.7 s. **What preserves the option is not a column** — it is that the belief-store
rebuild is a *versioned derivation* over the event stream (`derivation_version` in the profile),
which is a testable property where a nullable field with no producer and no consumer is not.

Cost accepted: signatures derived at M9 will be weaker than write-time ones, because pre-demotion
content is legitimately less accessible by then. Weaker analogical matching is the right trade
against a forgetting leak, but it is a loss, not a free choice.

*Resolved 2026-08-02:* `CONTRACTS.md` §4.0 pinned, with all five open cases decided — see
`docs/design/pinned-4.0-transport-record.md`. **ADR-002 revised**: real filesystem by default,
sandbox scoped to the quarantined reader, development stays native Windows, no WSL2 move; brief
§8.2 amended to match rather than left as a deviation.

*Resolved 2026-08-02:* **`CONTRACT_VERSION` stays `(1, 0)`** after the §4.0 pin. The retrieval
clock normalization is breaking to the wire, and the rule answers a breaking change with a major
bump — but a major version exists to signal a migration to implementers, and there are none. M0b
does not exist; the only reader was the M0a harness, updated in the same commit. Recorded as
settled rather than left in the queue, because an open item gets re-raised by every fresh
session until someone closes it, and the answer will not have changed.

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session
and competes with real work for context.

- **Built:** one line per completed unit, with the test that proves it.
- **In progress:** what is half-done and where you left off — specific enough to resume without
  re-reading the diff.
- **Known issues:** what is wrong and unfixed, including what you caused.
- **Open questions:** decisions you could not make alone. This is the human's queue.

Not a changelog. Git has that. This file answers one question: *what should the next session
do first?*
