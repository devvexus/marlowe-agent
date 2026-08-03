# State

**Updated:** 2026-08-03 — M0b **Session A** built; §1 amended; ADR-009 recorded
**Current milestone:** M0b — Session A **complete**. Next is Session B.

## Next action

**Start M0b Session B: the lexical cue and the frozen gate.** Session A deliberately stopped
short of any retrieval quality, so that the structural invariants were verified before there
was a benchmark number to argue about. That worked — see *Built* — and the number is now the
next thing to produce.

Session B's scope, in order:

1. **A lexical cue** (SQLite FTS5 is available; a `.claude/settings.local.json` probe confirms
   it compiles in). Retrieval currently returns *all matured entries for the session*, ordered
   by recency, with no relevance judgment at all.
2. **The frozen gate** with a **real isotonic calibration fit as a build-time artifact** on
   LongMemEval gold evidence (HP1). Until that exists the gate stamp says `ungated-v0`,
   `threshold: 0.0`, and every `score` / `calibrated_precision` is `0.0`. **Do not put a
   plausible version string next to those zeros** — a stamp reading `frozen-v1` would make an
   ungated run look like a gate that ran and found nothing interesting, which is a much
   better-looking claim than the true one.
3. Then the first LongMemEval number, with its cost, per §5.7.

**Do not start Session B by adjusting the maturation window.** See the first known issue.

**Amended this session:** `CONTRACTS.md` **§1** now specifies the journal as a hash chain
(`prev_signature` in the signed tuple). No major bump — no journal had ever been written
outside the test suite that landed in the same change; the reasoning is recorded in §1 itself,
following the §4.0 precedent. **ADR-009** answers open question 3: no structural-signature
field, on forgetting-leak grounds primarily and schema cost secondarily.

## Built

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

Nothing half-done. Session A's scope is closed and its four acceptance criteria are measured.

**Expected and honest, not failures** — these are what a substrate with no gate and no
generator produces, and a later session must not read them as regressions:

| Number | Why |
|---|---|
| LongMemEval accuracy **0%**, 6 abstained-when-answerable | No generator is wired. Every answer is an honest abstention (`degraded_path`), 0 fabrications, 2 correct refusals |
| MINJA / MemoryGraft / delayed-trigger ASR **1.000** | There is no gate. Suppressing these is Session B's job, and the ASR is what makes the laundering assertion non-vacuous today |
| Utility retention **0.0** | It is a ratio over answer accuracy, and the denominator is 0 |
| Staleness half-life **not measured** | Supersession *machinery* exists; the contradiction *detector* is retrieval quality and waits. Reported as unmeasured rather than extrapolated, which is correct |
| `evidence_precision` 0.4375 | Not the K1 headline and must never be reported as it. K1 needs the human label set, which is still the human's deliverable |

## Known issues

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
  reported number to **fall**.

- **Retrieval is scoped to the request's `session_id`.** That is a scope filter, not a
  relevance judgment — it is the honest minimum for a system with no cues. It also means
  LongMemEval's multi-session category cannot be answered correctly by construction until the
  cues arrive. Do not mistake the resulting category breakdown for a quality signal.

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
