# State

**Updated:** 2026-08-02 — M0a built; §4.0 pinned
**Current milestone:** M0a — **complete.** Next is M0b.

## Next action

**Start M0b, on native Windows.** ADR-002 was revised 2026-08-02: no WSL2 move. Marlowe runs on
the user's real filesystem by default — it is a secretary, and a secretary that cannot reach
your files is useless — so there is no sandbox default to erode, and the argument that forced
WSL2 no longer applies.

One piece of M0a is deliberately unwritten: `adapter/subprocess_ndjson.py` and the `exec://`
target. §4.0 is pinned, so it is buildable now, but there is no M0b process to spawn yet —
write it as the first thing M0b needs, against §4.0.3's frame shape (~half a session).

**Pinned this session:** `CONTRACTS.md` §4.0 (transport), plus a §4.2 clarification, closed-set
`channel`/`speaker` vocabularies in §4.6, §4.7 abstention symmetry, and the clock normalized to
`clock: { now_ms }` on all three interfaces. Decision record:
`docs/design/pinned-4.0-transport-record.md`. **No major version bump was taken** — the change
is breaking to the wire, but nothing had ever consumed the contract. Overrule by editing the
version constant and adding a `DECISIONS.md` entry; the harness follows.

## Built

`eval/` — the M0a harness. Python, separate artifact per ADR-001, depends on `CONTRACTS.md`
§4 and nothing else (enforced by a test). **62 tests passing.**

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

68 tests passing.

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

Nothing half-done. One component deliberately unwritten: the subprocess transport
(`exec://`). §4.0 is pinned so it is buildable, but there is no M0b process to spawn.

## Known issues

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

0. **Contract version after the §4.0 pin — flagged, not asked.** Normalizing the retrieval
   clock is breaking to the wire, and the versioning rule answers a breaking change with a
   major bump plus a `DECISIONS.md` entry. **No bump was taken**, because no implementation
   has ever consumed the contract — a major version signals a migration, and there is nobody
   to signal. If you would rather this were `(2, 0)`, say so; it is a one-line change plus an
   ADR, and the harness follows.

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

*Resolved 2026-08-02:* `CONTRACTS.md` §4.0 pinned, with all five open cases decided — see
`docs/design/pinned-4.0-transport-record.md`. And **ADR-002 revised**: real filesystem by
default, sandbox scoped to the quarantined reader, development stays native Windows, no WSL2
move. The one open item it leaves is the brief §8.2 conflict above.

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
