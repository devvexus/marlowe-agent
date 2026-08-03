# Marlowe — Roadmap

Every milestone is **independently shippable and independently useful**. A harness that only
works when complete is a harness that never works.

**Scope rule:** one milestone at a time. Scope is whatever this file marks current. If a task
pulls you outside it, note it in `STATE.md` and stop.

**Current milestone: M0a.**

---

## Kill criteria

Per brief §0.7 — what measurement, if it came back bad, says this design is wrong.

| # | Measurement | Verdict if it fails |
|---|---|---|
| **K1** | Injection precision <0.95 at ≤7,000 tokens and ≤300 ms P95, with the gate frozen | **Project-level.** Marlowe is a well-built harness with nothing distinguishing it. Reconsider rather than continue (§5.7). **The answer is not "add learning"** — see HP1. |
| **K2** | LongMemEval-S <90% or abstention <85% | Memory design is wrong, not undertuned. Revisit cue set and query routing before anything downstream. |
| **K3** | Non-zero ASR on unsigned memory writes | Invariant 2 is not structurally enforced. Stop and fix the write path; nothing else matters. |
| **K4** | First frame >150 ms or any flicker at 80×24 | The terminal thesis (§B0: differentiation is subtraction, craft is the product) is not achievable in the chosen stack. Revisit ADR-001. |
| **K5** | Runs do not resume from checkpoint across host reboot | Invariant 6 fails; the durable-run control plane — the stated competitive opening — is not real. |
| **K6** | Time from install to first useful output >5 min, or any config required | §4's zero-config constraint failed; the product is for developers only, which is not the product. |

---

## M0a — The eval harness, alone

**Ships:** a benchmark harness that can score *any* memory implementation behind the pinned
interface, and a published methodology.

**Built in a separate session, with no memory implementation in the repo.** The scorer is
written without knowledge of the retriever. Same reason the spike gates were pre-committed:
**the measurement cannot be authored by the thing being measured.**

### Scope

- Benchmark adapters: **LongMemEval-S** (500 q, per-category reporting: single-session,
  multi-session, temporal, knowledge-update, preference, abstention), the **abstention subset**,
  **LoCoMo** (1,540 q), and reporting paths for **LongMemEval-M**, **LongMemEval-V2**, and
  **BEAM-1M/10M**.
- **Injection-precision judge protocol** and its calibration against human labels.
- **Structurally enforced cost accounting** — the harness rejects a `RetrievalResponse` with no
  `cost` block as a protocol error. §5.7's "report the pair" is a schema requirement, not a
  reporting convention.
- **Poisoning suite**: MINJA-, MemoryGraft-, and laundering-style attacks; AgentDojo-style
  reporting of **both** ASR and utility retention.
- **Staleness half-life** measurement.
- A reference stub implementing the interface, so the harness is testable before M0b exists.

### The human label set — your deliverable, not the agent's

The judge protocol and harness are the agent's. **The human-judged relevance labels are the
human's.**

| Property | Requirement |
|---|---|
| Target size | ≥400 judged injections, ≥50 per LongMemEval category |
| Sampling rule | Stratified by category and by gate score decile, so the calibration curve has support across its range — not just the confident head |
| Blinding | The judge sees query + injected memory, never the score or whether it was injected |
| Refresh | Re-drawn whenever the cue set or router changes materially |

**Injection precision may not be validated against agent-generated relevance labels.** Doing so
reintroduces exactly the circularity the M0a/M0b split exists to prevent: the system would be
scored by a judge derived from the thing being scored. The offline LLM judge (HP1, tier 2) is
permitted **only** for gate training signal and for tracking between human label refreshes, and
its agreement rate against the human set must be published alongside any number it produces.

### Contracts it must satisfy

`CONTRACTS.md` §4 in full — **all three interfaces**, not just retrieval:

| § | Interface | Without it, M0a cannot build |
|---|---|---|
| 4.6 | **Ingest** | LongMemEval/LoCoMo history loading; the poisoning suite |
| 4.7 | **Answer** | Any accuracy or abstention score |
| 4.1–4.4 | **Retrieve** | Injection precision, tokens, latency |
| 4.5 | **Clock** | Staleness half-life, and reproducibility of anything decay-dependent |

This is the only contract M0a may depend on; depending on anything else means the split is not
real. If the harness finds it needs a fourth interface, the fix belongs in `CONTRACTS.md`, not in
the harness.

### Acceptance

- Scores the reference stub end to end and produces the full report.
- **Rejects a response missing `cost`** — on all three interfaces.
- **Rejects `answered: false` with a populated `answer`.** The honest "no" and a hedged answer
  are distinct outcomes; a harness that blurs them will score a confabulation as an abstention.
- **Drives the implementation entirely through a synthetic clock**, and a run at a fixed seed and
  clock reproduces bit-identically. If it does not, something is reading a system clock and
  staleness half-life is not measurable.
- **Asserts derived trust rather than declared trust**: a claim ingested with `channel: "web"`
  reports `untrusted_content` no matter how many derivations it passes through.
- Judge agreement against the human label set is published.
- Methodology is reproducible by a third party from the repo alone.

### Non-goals

No retrieval implementation. No storage. No gate. No embedding model. If M0a contains a
retriever, it has failed.

---

## M0b — The memory prototype

**Ships:** memory that scores against M0a. **Carries K1, K2, K3.**

### Scope

- Journal, content store, belief store per `CONTRACTS.md` §§1–3.
- **Live-only hot index** (ADR-003 — requirement, not optimization), cold index for tombstones.
- **ANN index + int8-quantized hot vector array.** An M0b requirement, not a later
  optimization: Tier C shows brute force crossing 120 ms at ~600k live and float32 exceeding a
  1 GB VPS at ~390k. **An exact search path is retained permanently as validation ground truth**
  — it is not scaffolding to delete once ANN works.
- **Group commit on journal append.** Scoped here rather than left as a note: the measured 633/s
  is workstation NVMe, and VPS shared storage at 20× slower lands ~44/s — *below* the 50/s gate.
  A design requirement that only holds on the developer's hardware is not a design requirement.
- Five cues + query-type router + fusion + **frozen gate**.
- Consolidation as a run: supersession, contradiction resolution, fidelity demotion, trend
  extractors (HP3), silent-entry maturation.
- Worst-case trust propagation; `remember` as an adjudicated request.
- All three supervision tiers **logged, feeding back into nothing**.
- `--dev` diagnostics: what was injected, what was rejected, scores, provenance, `/why`.

### Acceptance

| Metric | Target |
|---|---|
| LongMemEval-S overall / abstention subset | ≥90% / ≥85% |
| LoCoMo | ≥85% |
| **Injection precision (human-judged)** | **≥0.95** |
| Tokens per query | ≤7,000 |
| P95 retrieval latency | ≤300 ms |
| Unsigned-write ASR | 0% |
| Index rebuild reproduces exact per-entry fidelity | exact match |
| **ANN recall@50 vs. brute-force ground truth, at each Tier-C size point** | **≥0.99** |
| **int8 recall@50 vs. unquantized exact search** | **≥0.99** |
| **Sustained durable append under emulated VPS storage (fsync ≥20 ms)** | **≥50/s** |
| LongMemEval-M / V2 / BEAM | reported honestly |
| Staleness half-life | measured and reported |

Three of these are non-obvious and are here deliberately:

- **ANN is accepted on recall, not latency.** The 120 ms storage budget was derived under exact
  search. An approximate index that is fast and silently drops true neighbours passes latency and
  fails K1 — and presents as a retrieval-quality problem, sending investigation to the cues, the
  router, and the gate, none of which are at fault.
- **Recall is a standing test, not a tuning step.** It degrades as the index grows and as
  parameters drift, so it runs at every size point on every change to index, embedder, or
  quantization.
- **The append test emulates VPS storage rather than quoting the workstation number.** 633/s on
  NVMe proves nothing about the deployment target; ~44/s at 20×-slower fsync is the figure that
  has to clear the gate, and group commit is what clears it.

### Non-goals

No agent loop, no tools, no TUI. M0b is exercised through the eval harness only.

---

## M1 — The terminal shell against a stub agent

**Ships:** the TUI and classic CLI, driven by a scripted stub. **Carries K4.**

Craft is proven *before* there is a real agent behind it, because craft that is retrofitted
onto a working agent never happens.

### Scope

Header line, conversation, input line — nothing else by default. One-line tool calls with typed
summaries, expand on demand, failures auto-expanding, live lines animating in place,
consecutive same-verb collapse. Three ambient values (context %, spend, elapsed) with context
pressure as colour, not a bar. `⌘K`/`Ctrl-K` palette. Slash autocomplete. Multiline default,
Esc interrupt, type-while-thinking. `!cmd`. `/undo N`. Local session recap with no LLM call.
Modal approval overlay — the only bordered element.

### Acceptance (§B9, all of it)

| Metric | Target |
|---|---|
| Time to first frame | <150 ms |
| Time to interactive | <300 ms |
| Dropped keystrokes during streaming | Zero |
| Repaint flicker during stream or resize | Zero, verified 80×24 → 200×60 |
| Tool call default footprint | 1 line |
| Persistent chrome | ≤2 lines |
| Distinct colours in default view | ≤1 accent + 3 foreground weights |
| Box-drawn panels in default view | Zero |
| **Memory-related elements in default view** | **Zero** |
| Classic CLI parity with TUI | 100% of commands, sessions, data |
| Usable over SSH at 80×24 | Yes |
| **Full §B9 suite re-run against native Windows Terminal** | **Pass** |

The last row is symmetric and unchanged, but its direction has inverted: ADR-002 (revised) puts
development on native Windows, so **Linux is now the surface at risk of being verified only in
CI**. Both must be run on a real terminal emulator — a TUI verified on one platform is not
verified.

### Non-goals

No real agent. No memory wiring. No network. **No memory UI, ever** (§B1) — the `TurnEvent` enum
has no injection variant and must not gain one.

---

## M2 — The one loop, tools, skills, permissions

**Ships:** a genuinely useful terminal coding agent. **Carries K6.**

### Scope

The loop from `ARCHITECTURE.md` §3. Eleven model-visible tools. `SKILL.md` loading with
progressive disclosure and `find_skill` semantic discovery. MCP transport. Registration ≠
exposure. Capability manifests with **load-time default-deny** on consequence. The
`(action, target)` argument-provenance check. Risk-tiered approvals. **Real filesystem by
default, sandbox scoped to the quarantined reader** (ADR-002, revised). Egress deny-by-default.
Spend caps. Context assembler: per-source budgets, tool-result clearing, 70% compaction with
lineage and cache invalidation, structural governance re-assertion.

M0b's memory is wired in here — this is the first milestone where the eleven-week callback can
happen.

### Acceptance

- Install → first useful output **<5 min, zero config**, in a clean container.
- **First-run onboarding states plainly what Marlowe can reach** — which directories, which
  hosts, what it asks before doing versus does silently. ADR-002 (revised) makes this a
  requirement, not a nicety: a zero-config first run must not become a zero-disclosure one.
- **Path-traversal suite passes AND access is handle-based. One requirement, not two.**
  The suite covers symlinks and Windows junctions, `..` sequences, UNC and `\\?\` forms, 8.3
  short names, case-insensitivity collisions, Win32 name munging, alternate data streams, and
  Unicode normalization, with canonicalization before the check and never after. The handle
  discipline is `openat`/`O_NOFOLLOW` on POSIX and explicit reparse semantics plus
  final-handle identity verification on Windows.

  **They ship together or neither ships.** Canonicalize-then-open leaves a check-then-use
  race: a symlink planted between the check and the open means the check was correct and the
  open still landed outside scope. A traversal suite passing against a check-then-open
  implementation therefore certifies a boundary that does not exist — which is worse than no
  suite, because it is believed. Splitting these into separate acceptance items is how that
  happens, so they are one item. See ADR-002 and brief §8.2 (amended): with no kernel
  backstop, a path check defeated by string manipulation is the whole protection gone.
- SWE-bench Verified and Terminal-Bench 2.0: competitive on the same model.
- τ-bench / BFCL: competitive on the same model.
- Compaction preserves governance constraints across the boundary — tested explicitly.
- Compaction invalidates cache — tested explicitly.
- Startup fails on an unannotated tool manifest.
- Budget tests from HP10 pass in CI.

### Non-goals

No durable runs surviving parent death (M3). No triggers. No voice. No connections.

---

## M3 — The durable run control plane

**Ships:** the competitive opening (§10.1 — the thing Hermes lacks). **Carries K5.**

### Scope

Runs as first-class objects with independent lifecycle. Children outliving parents; orphan
policy declared at spawn. WAL + checkpoint resume. Mid-flight steering without restart.
Orchestrator-worker isolation with condensed structured returns. Ad-hoc spawning, no
predeclared graph. `/runs`, `/steer`, `/watch`.

Deep research rides on this: effort scaling, explicit subagent contracts, a **separate**
verification pass for citations, real file artifacts, progressive delivery.

### Acceptance

| Metric | Target |
|---|---|
| Runs surviving restart, provider failover, host reboot | 100% resume from last checkpoint |
| DeepResearch Bench RACE | ≥ expert-reference parity |
| DeepResearch Bench FACT citation accuracy | ≥95% |
| GAIA / BrowseComp | competitive on the same model |
| Every quality number | reported with tokens and wall-clock |

### Non-goals

No swarm topology. No predeclared DAGs. Both are anti-requirements (§15).

---

## M4 — Triggers and unattended runs

**Ships:** work that happens when nobody is watching.

Schedule (cron and natural language), event, condition, manual — all gated by the same
permission machinery, all using the same loop, same memory, same skills. Tiered autonomy
declared per trigger. Loud failure with diagnosis and proposed fix. Per-automation cost
ceilings. Idempotency and dedup. One-command audit and revocation.

**Acceptance:** a failed unattended run notifies with a diagnosis; a runaway loop hits its
ceiling and pauses rather than spending; every scheduled thing is listable and killable in one
command; **no separate automation code path exists** (if automation needs its own loop, the
architecture is wrong).

**Non-goals:** no undeclared/proactive noticing — that is M5.

---

## M5 — Connections, people, commitments

**Ships:** the secretary layer's substrate.

Connection broker (both implementations, HP16), high-level intent tools over low-level API
wrappers, progressive connection driven by need, bundles. People model built from observed
interaction. Commitment extraction with the three-band confidence gate (HP15). The open-loop
list. Noticing: deterministic classes on, judgment classes in shadow (HP11).

### Acceptance

| Metric | Target |
|---|---|
| Install → first connected app | <90 s |
| Taps to connect a bundle | ≤3 |
| **Credential exposure to model context** | **Zero, structurally enforced and tested** |
| Model-visible tools with 20 apps connected | ≤12 |
| Broken-connection self-heal without user action | >80% |
| Cross-channel entity resolution accuracy | ≥95% |
| Commitment extraction recall | ≥90% |
| Commitment false-closure rate | <2% |
| Noticing precision (deterministic classes) | ≥0.80 |
| Unprompted interruptions per day | ≤5, user-adjustable |

**Non-goals:** no autonomous sending. Everything stays at tier ≤2 until M6.

---

## M6 — The trust ledger and dashboard

**Ships:** the mechanism that makes autonomy reachable.

The six-tier ladder per action class. Shadow mode as default entry. Evidence-based promotion
**proposed to the user, never self-granted**. Reversibility-weighted thresholds with hard
ceilings. Immediate silent demotion. Verification sampling, drift detection, novelty gating.
The three dashboard views. Rubber-stamping measurement (§B6). `/trust`.

### Acceptance

| Metric | Target |
|---|---|
| Classes at tier ≥3 after 30 days | ≥5 |
| Promotion proposals accepted | ≥70% |
| Post-promotion correction rate | <5% per class |
| Time from correction to demotion | immediate, same session |
| **Self-granted promotions** | **Zero, structurally impossible** |
| Confidence calibration error | <10% |
| Non-technical users who can change a tier unaided | ≥90% |
| Users who believe the time-saved number | ≥80% (survey) |
| Drafts sent unedited (tier ≥3 classes) | ≥85% |
| Voice-match blind test | ≥70% indistinguishable |
| Escalations resolvable in one tap | ≥80% |
| **Day-30 users with ≥1 class at tier ≥4** | **≥60%** |

The last row is the real one (§A12). Everything above it is a leading indicator of whether
people actually let the system work.

Also the HP14 experiment: injected-error catch rate, sampled cohort vs. control.

---

## M7 — Voice

Cascade with streaming overlap; S2S pluggable. Three-layer turn-taking with semantic turn
detection. Backchannel discrimination. Mid-tool interrupt policy in code, not config.

| Metric | Target | Ceiling |
|---|---|---|
| Voice-to-voice P50 | ≤800 ms | 1.5 s |
| Voice-to-voice P95 | ≤1.5 s | 3.0 s |
| Barge-in | ≤150 ms | 200 ms |
| Turn gap | 200–450 ms | — |

**Non-goals:** no separate voice loop. Voice is a surface, not a mode.

---

## M8 — Reach

Every channel a full interaction surface. One session identity across all. The assistant
addressable — its own address and handles. Zero-install path. Async by default. Presence
awareness. Multi-party etiquette per HP13.

**Resolved requirements tension — confirmed, not inferred.** §A10 lists web and native mobile
among the channels; §B10 says *no web UI in v1*. **B10 wins: v1 surfaces are terminal, messaging
gateway (SMS/iMessage/WhatsApp/Telegram/Slack/Discord/email), and voice. Web and native mobile
are deferred to v2.** The zero-install path is satisfied by SMS, not by a web app.

The reason matters more than the ruling: §A10's channel list was written against **cloud-only
competitors**, where a web UI is the only surface there is. Terminal-native is the deliberate
position (§B0), not a starting point to grow out of — so inheriting a competitor-shaped channel
list would import their architecture through the back door.

**Acceptance:** capability parity across channels — 100% of medium-supported actions; a session
started by voice, continued by text, finished in a terminal, with no restatement.

---

## M9 — Bounded self-improvement

Skill induction from a **pool** of diverse trajectories analysed in parallel, not sequential
distillation. Environment knowledge accumulation. Two-split acceptance with automatic rollback.
Versioned, reversible, reviewable diffs.

**Hard boundary, enforced by the architecture rather than by policy:** the agent may never
modify the permission system, sandbox configuration, audit logging, memory provenance, or the
trust ledger's promotion logic. Since the model cannot append to the journal at all, and tier
grants are appendable only by the permission component, this is structural.

**Acceptance:** a self-proposed change that regresses the held-out split is rolled back
automatically; every self-modification is a reviewable diff.

---

## M10 — Gate adaptivity

The only milestone that may set `Gate.adaptive = true`.

**Entry condition:** M0b's frozen baseline is published and stable.
**Ship condition:** the adaptive gate **beats the frozen baseline** on the M0a suite, at equal
or lower token cost and latency. If it does not beat it, it does not ship — the frozen gate
remains.

The supervision asymmetry from HP1 holds regardless: utilization is a weak negative only;
positives come only from the offline judge and explicit corrections.

**Non-goal:** adaptivity as a fix for a missed K1. If M0b missed 0.95 frozen, this milestone is
not the remedy — that would be treating a retrieval problem as a tuning problem.

---

## Sequencing rationale

M0a before M0b because the measurement cannot be authored by the thing measured. M0b before
everything because it carries the project kill criterion and the brief is explicit that it
ships first. M1 before M2 because craft is never retrofitted. M2 before M3 because a useful
agent that cannot survive a reboot beats a durable agent that does nothing. M5 before M6 because
value must precede autonomy (§A11) — the user receives something useful before being asked to
grant anything meaningful.
