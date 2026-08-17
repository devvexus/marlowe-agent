# Marlowe — Roadmap

Every milestone is **independently shippable and independently useful**. A harness that only
works when complete is a harness that never works.

**Scope rule:** one milestone at a time. Scope is whatever this file marks current. If a task
pulls you outside it, note it in `STATE.md` and stop.

**Current milestone: M2.** M0a, M0b and M1 are complete. M1 closed 2026-08-08 at `ed25914`; see §M2
below for scope, and [`PRECISION-COVERAGE.md`](PRECISION-COVERAGE.md) for what M0b published.

---

## Kill criteria

Per brief §0.7 — what measurement, if it came back bad, says this design is wrong.

| # | Measurement | Verdict if it fails |
|---|---|---|
| **K1** | **AMENDED 2026-08-08 — see below.** A flat precision/coverage curve: precision at 10% coverage not materially above precision at 100% coverage | **Project-level.** A confidence signal carrying no information is the failure K1 was written to catch. Reconsider rather than continue (§5.7). **The answer is not "add learning"** — see HP1. |
| **K2** | LongMemEval-S <90% or abstention <85% | Memory design is wrong, not undertuned. Revisit cue set and query routing before anything downstream. |
| **K3** | Non-zero ASR on unsigned memory writes | Invariant 2 is not structurally enforced. Stop and fix the write path; nothing else matters. |
| **K4** | **RESTATED 2026-08-08 — see below.** First frame >150 ms, or any repaint flicker across 120×30 → 240×60 | The terminal thesis (§B0: density with discipline, craft is the product) is not achievable in the chosen stack. Revisit ADR-001. |
| **K5** | Runs do not resume from checkpoint across host reboot | Invariant 6 fails; the durable-run control plane — the stated competitive opening — is not real. |
| **K6** | **RESTATED 2026-08-12 — see below.** Binary on disk and model pulled: cold launch to first useful output >5 min, or any config required | §4's zero-config constraint failed; the product is for developers only, which is not the product. |

### K6 — restated 2026-08-12

> **Original:** *"Time from install to first useful output >5 min, or any config required."*
>
> **Restated:** *"With the binary on disk and the model already pulled — cold launch to first useful
> output >5 min, or any config required."*

**What changed and why.** The original silently included the model download. `qwen3.5:9b` is
**6.59 GB**; at 100 Mbps that is roughly nine minutes on its own, so K6 as written could not be met
on any connection a normal user has, at any level of engineering effort. A kill criterion that
cannot be passed is not a kill criterion — it is a row everyone learns to step over, which is worse
than not having it, because the stepping-over generalises to the rows that *are* achievable.

**This is a restatement, not a relaxation, and the distinction matters.** The clause measures what
the product controls: process launch, profile creation, journal open and verification, belief-store
derivation, and the first model call. A bandwidth-bound one-time download is not a property of the
harness and never was — including it made K6 a measurement of the user's ISP wearing a product
label.

**What the removed term becomes instead: a disclosure requirement, not a silent omission.** M2's
acceptance already requires first-run onboarding to state plainly what Marlowe reaches. The pull
time joins that list. A user meeting Marlowe on a new machine still waits ~9 minutes for the model,
and the product must **say so before they start waiting** rather than appear hung. Dropping the term
from K6 without adding it to the disclosure would be the failure this project logs as an adjacent
measurement — a number that is correct about a different system.

**Measured 2026-08-12, against the restated clause:**

| | |
|---|---|
| Marlowe's own cold start (launch → accepting connections, fresh profile) | **70 ms** |
| Marlowe's share of an end-to-end ask | **68–198 ms** |
| End to end, cold, model pulled and resident | **1.2–1.5 s** |
| Budget | 300,000 ms |

**Passes by more than two orders of magnitude on the harness's own contribution.** Everything above
Marlowe's share is model inference: `qwen3.5:9b` is a reasoning model whose thinking block swings an
order of magnitude run to run, and an earlier 11.3 s reading was 11,071 ms of self-reported model
time around 198 ms of harness. **If K6 ever fails it will not be the harness**, which is worth
stating because it redirects the next investigation.

**Still unmeasured, and named so it is not read as covered:** every run behind those numbers used a
**fresh or nearly-empty journal**. `Journal::open` runs `verify_chain`, which walks from sequence 1
and re-derives every signature, and `BeliefStore::derive` folds the whole log — both **O(journal
size)**. 70 ms against zero events says nothing about the slope, and a bad slope stays invisible for
months before arriving as *"why does it take eight seconds to start now."* K6 as restated is exactly
the measurement that would catch it, on a generated journal of realistic size.

### K1 — amended 2026-08-08

**Adopted from `docs/requirements/proposed-K1-amendment.md` Part A. The argument is ADR-019.**

> **Original:** injection precision <0.95 at ≤7,000 tokens and ≤300 ms P95, with the gate frozen →
> project-level; reconsider rather than continue.
>
> **Measured, Session J, held-out, n=229:** no coverage level reaches 0.95 injection precision with
> its confidence interval above the threshold. The best point estimate is **0.9565 (22/23) at 10.0%
> coverage, Clopper-Pearson [0.7805, 0.9989]**. This was the registered prediction, written before
> the read.
>
> **Amended criterion.** Marlowe's memory subsystem is judged on a published precision/coverage
> curve rather than on a single threshold, with three conditions:
>
> 1. **The curve ships with the product.** Precision at every coverage level from 100% down to 10%,
>    each point with its binomial interval, measured on a held-out split the gate's parameters have
>    never seen.
> 2. **The operating point is chosen on the curve and declared**, not assumed. Whatever coverage is
>    selected, the injection precision at that point and its interval are stated wherever the
>    capability is described.
> 3. **The abstention path is real.** Below the operating point the system abstains and the agent
>    recovers through the explicit `recall` tool (§5.5). A configuration that injects at low
>    precision to raise coverage fails this criterion outright.
>
> **The kill condition is retained and restated.** The project is reconsidered if the curve is flat
> — that is, if precision at 10% coverage is not materially above precision at 100% coverage. A
> system whose confidence carries no information is the case K1 was written to catch, and it remains
> a project-level finding.
>
> **Constraints unchanged:** ≤7,000 tokens and ≤300 ms P95 still bind, and the shipped fine-tuned
> configuration measures 214 ms/query inside that budget.

**Three things about this amendment that must not erode.**

**1. The threshold is NOT moved.** `0.95` is not lowered and no number in the original criterion is
relaxed. What changes is the criterion's *shape* — from a single point to a published curve — and a
**new** kill condition is added that did not exist before. An amendment that only widened a target
would be worthless; this one adds a way to fail that the original did not have.

**2. Condition 3 is binding, not advisory.** A configuration that injects at low precision in order
to report higher coverage **fails this criterion outright**. Coverage is not a quantity to be
maximized against precision; the curve exists so that trade is visible rather than silent.

**3. The 0.3739 ceiling never measured retrieval quality — and this invalidates no retrieval
measurement.** Per ADR-016, measured before any band was registered: **a perfect retrieval system
scores 0.8483 on the shipped gate against a 0.95 threshold**, because `fit_isotonic`'s smallest
expressible block spans 100% of queries and the gate has no vocabulary for confident subsets.
Sessions B–H each read the 0.3739 ceiling as evidence retrieval was not improving; it was reporting
a structural property of the calibration shape and would have read approximately the same with a
flawless retriever.

> **What this does NOT invalidate: any retrieval measurement.** R@1, R@5, R@10, conditional
> accuracy, the oracle, every closed mechanism and every failure decomposition were measured
> **against gold turns with the gate uninvolved**. What was invalidated is the *interpretation of
> one number*, not the measurements themselves.

**The published curve and the declared operating point live at
[`docs/design/PRECISION-COVERAGE.md`](PRECISION-COVERAGE.md)**, with the machine-readable artifact
at `crates/marlowe-memory/artifacts/precision-coverage-heldout-v1.json`.

### K4 — restated 2026-08-08, at the start of M1

**Both of the original statement's premises were withdrawn by Addendum B v2, and neither withdrawal
was reflected here.** The original read:

> First frame >150 ms or any flicker at **80×24** → the terminal thesis (§B0: **differentiation is
> subtraction**, craft is the product) is not achievable in the chosen stack. Revisit ADR-001.

§B11 v2 withdraws the 80×24 requirement outright — the TUI requires **≥120 columns and ≥30 rows**
and renders an honest refusal below that, because a narrow variant was designed and rejected. §B0 v2
withdraws *subtraction* as the thesis and replaces it with **density with discipline**. §B13 sets the
flicker verification surface at **120×30 through 240×60**.

**A kill criterion measured at a width the design refuses to render is not a criterion.** It could
only ever return "fail", and it would be measuring the refusal line.

> **K4, restated.** First frame >150 ms, or any repaint flicker across the supported range 120×30 →
> 240×60. **Verdict if it fails:** the terminal thesis (§B0 v2: density with discipline, craft is the
> product) is not achievable in the chosen stack. Revisit ADR-001.

**Nothing is relaxed.** The 150 ms budget is untouched, and the flicker surface is *larger* than the
one it replaces — 120×30 → 240×60 spans a wider range of reflow geometries than a single 80×24 grid
did, and §B2's border-not-fill focus rule exists precisely to survive it. M1 carries K4.

---

## M0a — The eval harness, alone ✅ COMPLETE

**72 tests, `eval/`, never modified to accommodate an implementation.** The one deliverable still
outstanding is **the human label set**, which is the human's and not the agent's — see below. It is
now *drawable* for the first time, because M0b produced a conformal operating point to sample from.


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

## M0b — The memory prototype ✅ COMPLETE 2026-08-08

**Shipped:** held-out R@1 **0.6725**, R@5 0.8865, R@10 0.9039, conditional accuracy 0.7440,
retrieval P95 **211 ms** warm / **238 ms** cache-cold against a 300 ms budget, 0 cases over the
7,000-token budget. Reranker `ms-marco-MiniLM-L-2-v2-ft-session-j` (f32), ADR-020.
Curve and declared operating point: [`PRECISION-COVERAGE.md`](PRECISION-COVERAGE.md).
Sessions A–K; `runs/session-*/RESULT.md`.

**Carried forward as named work, not preconditions:** head separability, and the human label set.
See `STATE.md` and §M1 below.

> ### CORRECTED 2026-08-11 — this closure named two carried items and silently carried at least five
>
> Read against the Scope section below, **M0b shipped roughly 40% of its named mechanism**:
>
> | Scoped | Built? |
> |---|---|
> | **Five cues** | **Two** — lexical and dense. Entity-graph, temporal and causal never attempted |
> | Query-type router | **No** |
> | Fusion, frozen gate | Yes |
> | **ANN index + int8 hot vector array** — *"an M0b requirement, not a later optimization"* | **No** |
> | **Live-only hot index** — *"requirement, not optimization"* | **No** |
> | **Group commit on append** — *"scoped here rather than left as a note"* | **No** — the phrase appears once, in a comment about what durability would need |
> | Consolidation **as a run**; contradiction resolution; trend extractors (HP3) | **A function, not a run.** No caller outside the eval adapter; it cannot spawn |
>
> **Three of those lines carry a phrase written to pre-empt deferral, and were deferred anyway.**
>
> **This does not invalidate 0.6725.** The number is real, measured from the shipped binary, and
> labelled scrupulously everywhere it appears. What it is not is a measurement of the *designed*
> system — and it has been treated as "retrieval quality" in every downstream decision since,
> including K1's amendment and the declared operating point.
>
> Sessions D–L all worked the two cues that exist; the largest quality win was +0.0699 from
> fine-tuning the reranker, and M0c Session A closed the remaining named candidates with R@1
> unmoved. **The third cue has never been attempted.** Brief and constraints at the top of
> `STATE.md`.


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

## M1 — The terminal shell against a stub agent ✅ COMPLETE 2026-08-08

**Shipped** at `ed25914`: the frame, keyboard navigation, §B6 tool lines, the status band and its
seven states, the inspector, the approvals overlay, the classic CLI, width refusal, `doctor`, and
the §B17 Windows launcher. The 9-line interaction checklist was driven by hand in a live Windows
Terminal session and passed. Three bugs were found by *using* it that no test caught — scroll,
double-dimming, and `NO_COLOR` — and all three are recorded in `STATE.md` with their lesson.

**One acceptance row was still open at close: accent legibility on a light background** (§B13 asks
for the eye, on each). It carries a contrast number of 3.26:1, which clears AA for large text and UI
components but not AA body text. It is carried into M2 Session E, which is the next session that
touches the interface.

**Ships:** the TUI and classic CLI, driven by a scripted stub. **Carries K4.**

Craft is proven *before* there is a real agent behind it, because craft that is retrofitted
onto a working agent never happens. M1 has no model call in it.

**This section was rewritten 2026-08-08 against Addendum B v2, and it absorbed `M1-KICKOFF.md`,
which is deleted.** The kickoff was written at the close of M0b against Addendum B **v1** and every
scope line in it was withdrawn within the day: it specified "header line, conversation, input line —
nothing else by default", "≤2 lines of chrome", "zero box-drawn panels", "usable over SSH at 80×24",
and "modal approval overlay — the only bordered element". v2 reverses all five. Two documents
describing one milestone is how the next session reads the withdrawn one; there is now one.

### Read before writing any code

| Path | Why, for M1 specifically |
|---|---|
| [`03-addendum-terminal.md`](../requirements/03-addendum-terminal.md) | **The interface requirements, v2. Binding.** Read it fully — this is the milestone it was written for, and **v2 reverses v1**. |
| [`marlowe-tui-mockup.html`](marlowe-tui-mockup.html) | The clickable mockup of that spec. **Where prose and mockup disagree, prose wins**; where prose is silent, the mockup is the intent. |
| [`04-addendum-persona.md`](../requirements/04-addendum-persona.md) | Anything producing user-visible prose carries the persona — **including a stub's scripted output**. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Component boundaries. §2.14: surfaces hold no policy and no state the daemon lacks. |
| [`CONTRACTS.md`](CONTRACTS.md) | **Before any code crossing a boundary.** `TurnEvent` §13. |
| `STATE.md` | Always, at session start. |

**§B1 is binding: zero memory-related regions in the default surface.** The user experiences memory
through the agent knowing things, never through panels, scores, or citations. A `recall` *tool line*
is permitted — it is a tool line like any other. A *region whose subject is the memory system* is
not. Retrieval instrumentation is a seventh inspector tab under `--dev` only, and that is M2.

### The rule the design rests on — §B2

> A border delineates an interactive region. Every bordered region carries a label on its top border
> and a hotkey on its bottom border. **A region with no hotkey has no border.**

**Focus is border colour and label colour, never a background fill.** A fill collides with the
user's theme, costs a full-cell repaint on every focus change (which fights K4), and reads as a web
page rendered in a terminal.

**Reading §B3 precisely, because getting it wrong ships decorative borders.** Six regions, of which
only four are bordered *as regions*: the five control-strip fields, the status band, the
conversation, and the message field. The titlebar, the footer and **the inspector itself** have no
hotkey and therefore no border — the inspector's borders live on its *items* (§B7), each of which
carries a label and a key. The mockup shows several bordered inspector items without a key; that is
the mockup being loose, and prose wins.

### Scope — what M1 ships

1. **The frame.** Six regions per §B3, conversation never below 55% of the horizontal split, every
   label, hotkey, pager and tab bar pinned **outside** its region's scroll area. Chrome that scrolls
   is a bug and it is the bug this design is most likely to ship with.
2. **Keyboard navigation, built before any content.** Region hotkeys jump focus, `Tab`/`Shift-Tab`
   cycle in reading order, arrows move within, `Enter` acts, `Esc` backs out one level. Mouse is a
   bonus; mouse-first retrofitted with keys produces a bad TUI.
3. **The conversation pane and §B6 tool lines.** One line per call, typed summaries, failures
   auto-expanding, live lines animating in place, consecutive same-verb collapse, a visible
   scrollbar, and the pinned pager carrying turn count, compaction count and lineage depth.
4. **The status band and its seven states** (§B5). Motion means Marlowe is working; stillness means
   the ball is in the user's court, which is why `waiting` **freezes** the indicator. Glyph form is
   **ADR-021** — a braille amplitude meter, decided and recorded before implementation.
5. **The inspector: Runs and Schedule live.** Runs carries the Steer field, a focusable text input
   *inside* a pane and the hardest interaction in the inspector. Schedule is where §B7's actual
   argument for a TUI lives — the region carries the data, the transcript carries the judgment.
6. **Approvals** (§B9). Dims the entire frame, doubled border in its risk tier's colour, centred.
   The only element permitted to dim the rest of the screen — and **dimming is a foreground rewrite,
   never a fill**, so the zero-fill acceptance row proves it.
7. **The classic CLI** (§B11). Command parity, not layout parity. Both surfaces dispatch from **one
   command registry**, so parity is a property of the design rather than a checklist that rots.
8. **Width handling.** `CSI 8 ; rows ; cols t` resize request on start; below 120×30 an honest
   refusal naming current and required size and offering the classic CLI. **Never a degraded grid.**

### Deferred to M2, with reasons

- **The `Ctrl-K` palette.** It indexes sessions, skills, models and memory search, none of which
  exist. Built against a stub index it measures nothing. **Slash-command autocomplete does ship** —
  it lives in the message field and is cheap.
- **Sessions, Skills, Trust and Status panes.** Present in the tab bar and reachable, each rendering
  one bordered region with a label, a key, and a line naming what will live there and in which
  milestone. Honest and present, not a fake pane — the tab bar must not lie.
- **`--dev`'s seventh tab.** Nothing to inspect without memory wiring.
- **Mouse.** §B10 — every path by key first.

### Acceptance — §B13 in full

Every row is a command that prints a number, per the standing rule.

| Metric | Target |
|---|---|
| Time to first frame | < 150 ms |
| Time to interactive | < 300 ms |
| Dropped keystrokes during streaming | Zero |
| Repaint flicker during stream or resize | **Zero, verified 120×30 through 240×60** |
| Tool call default footprint | 1 line |
| **Every bordered region has a label and a hotkey** | **100%, asserted by test** |
| **Regions reachable by keyboard alone** | 100% |
| Background fills used to signal focus | Zero |
| Chrome inside a scroll area | Zero |
| Distinct colours | ≤ 1 accent + 3 state + 3 foreground weights |
| Memory-related regions in the default surface | Zero |
| **Accent legible on both dark and light terminal backgrounds** | **Verified by eye on each** |
| Below-minimum width behaviour | Honest refusal, never a degraded grid |
| Classic CLI command parity | 100% of commands, sessions, data |
| **§B13 suite run on native Windows Terminal AND a Linux emulator** | **Pass on both** |

**Three rows are most likely to be skipped and all three are load-bearing.** The label-and-hotkey
row is asserted by test, not by inspection — the region contract is a type that cannot be
constructed without both. The cross-platform row inverts with ADR-002 (revised): development is on
native Windows, so **Linux is the surface at risk of CI-only verification**, and a TUI verified on
one platform is not verified. The accent row cannot be a test on its own — violet is the accent most
likely to fail it, and a value that works only on dark works on one machine.

**K4 is carried here.** First frame >150 ms, or any flicker across 120×30 → 240×60, revisits
ADR-001. See "K4 — restated" above.

### Non-goals

No real agent. No memory wiring. No network. **No memory UI, ever** (§B1) — the `TurnEvent` enum
has no injection variant and must not gain one.

M1 consumes **none** of M0b. That is deliberate: the interface must not be shaped by whatever the
memory system happens to do today.

### What M0b hands over, and what it does not

**Hands over:** a memory subsystem scoring against M0a at held-out R@1 **0.6725**, a published
precision/coverage curve and a declared operating point.

**Does not hand over: an abstention path.** The amended K1's condition 3 requires that below the
operating point the system abstains and the agent recovers through the explicit `recall` tool
(§5.5). **That is M2 work and it is load-bearing** — a condition of the criterion M0b was judged
against, not a nice-to-have. Do not let it drift.

### The two M0b directions carried, not closed

Neither is an M1 dependency. Both are named so they are not rediscovered.

1. **Head separability.** Fine-tuning dominates the curve from 100% down to ~25% coverage and stops
   helping at the head, which is exactly where the criterion reads. **The rerank margin is not the
   signal.** Unexplored: a confidence signal fit against **relevance** rather than against score
   (ADR-017's rule), and set-wise/listwise scoring that observes candidates jointly.
2. **The human label set.** ≥400 judged injections, ≥50 per category, judged blind, stratified by
   score decile. **True injection precision has never been computed** — every figure to date is a
   gold-turn proxy. Drawable now that a conformal operating point exists to sample from.

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

### Session order — a dependency order, not a preference

> **CORRECTED IN PLACE 2026-08-17.** This table marked **C2a as "next"** when C2a through D had
> shipped, and **C2d, C2e and C2f were not in it at all** — they existed only in `STATE.md`. A stale
> table is how a session rebuilds something that already works, so every row below now carries the
> commit that shipped it. Three sessions ran that this table never scheduled; they are listed rather
> than folded into a lettered row, because a session that happened is not evidence that a planned
> session did.

| Session | Ships | Status |
|---|---|---|
| **A** | The spine: the one loop, eleven tool manifests, registration ≠ exposure, the permission layer, `(action, target)`, egress, runs + budgets + ephemeral spawn, the context assembler | ✅ 2026-08-08 |
| **B** | **Path scoping — the traversal suite and handle discipline, together** (ADR-024, ADR-027) | ✅ 2026-08-08, Windows **and** Linux |
| **C1** | The platform gate; `ParamType::WritePath` and the walk's write/create path | ✅ 2026-08-08 `42ae9d3`, `e8e6dd0` |
| **C2a** | The four executors — `read`, `edit`, `find`, `bash` — on adjudicated handles | ✅ 2026-08-08 `d1b6d76` |
| **C2b** | The **Ollama provider adapter** (ADR-028). Adapter only; **no credential broker** | ✅ 2026-08-08 `c048dec`, `84ed6e3` |
| **C2c** | **ARCHITECTURE §6 wiring — the daemon/client split made real.** `Engine` constructed, `marlowe --tui` driving it instead of M1's scripted stub | ✅ 2026-08-09 `69ead72` |
| **C2d** | The view models promoted out of `marlowe-stub`; `marlowe --tui` on the real `Engine` (ADR-030) | ✅ 2026-08-09 `5fbd513`, `9f51476` |
| **C2e** | The loop honest about what it sends and what it shows: streaming, roles, think-block handling, persona *emission* | ✅ 2026-08-09 `2be2179`, `1813740` |
| **C2f** | `web` exposed; the latch met real untrusted content; TUI approvals, `--shutdown`, `--daemon-port` | ✅ 2026-08-10 `6f8a3aa` |
| **D** | M0b's memory wired in, including **K1 condition 3's abstention path** | ✅ 2026-08-11 `850b512`, `a5a028b`, `ddf168b` |
| **C3** | `SKILL.md` + progressive disclosure + `find_skill`, MCP transport | **NOT STARTED.** Deferred past D, which this table's own rule permits. The *vocabulary* exists from Session A — `Transport::{Skill, Mcp}`, third-party descriptions carried as `UntrustedContent` — but nothing loads a `SKILL.md`, no `find_skill` exists, and no MCP transport speaks to a server |
| — | **Layer 1 routing (ADR-039)** — `Engine::condense_batch`, the quarantined reader wired to the trust class | ✅ 2026-08-12, **unscheduled** |
| — | **Tools and parallelism (ADR-040, ADR-041, ADR-042)** — `marlowe-extract`, `marlowe-net` rebuilt, concurrent fetch, batched quarantined reads, the document store | ✅ 2026-08-12 `1d3a428`, **unscheduled** |
| — | **The security audit** — 108 findings from 8 read-only agents, 20+ fixed, each pinned by a test that fails on revert | ✅ 2026-08-12 `813ae2f`…`5142420`, **unscheduled** |
| **E** | The TUI against the real loop, first-run onboarding, K6 in a clean container, M1's open accent row | **current** |

**Session B is verified on both platforms, and that is a standing requirement rather than a
one-time closure.** The symlink class cannot run on Windows without elevation and the POSIX walk
never executes there; the Windows pinning never executes on Linux. The halves do not overlap, so a
single-platform green is a half-measured wall. Both were run at the close of Session B —
`MARLOWE_TRAVERSAL_STRICT=1` passes on Linux with 11/11 classes `RAN`. ADR-027 carries the command.

**§6's wiring is a named item because it was not one, and that is how it nearly became a K6
surprise.** `marlowe --tui` drives M1's scripted stub; nothing constructs an `Engine`; the
client/daemon split does not exist. It is the last thing between the parts and the whole, and it
carries **invariant 6** (a run survives its starter) and **M1's 150 ms first-frame budget**, so it
is not plumbing to rush. Left implicit between sessions, its absence would surface at K6 as
"install → first useful output failed" and read as a model problem.

**C3 defers before C2 does.** A Marlowe that can be talked to with no skills library beats a skills
library that cannot be talked to.

**Session A's deliberate absences are refusals, not gaps.** Every one is a named error rather than a
permissive default: a `Path` argument is blocked because scoping does not exist, `remember` reports
that memory is not wired, and `RunControl::resume` refuses by name because runs are not durable
until M3. A build in which those quietly succeeded would be the failure this project has logged
eleven times.

**Two items deferred from M1, deliberately and with the reason recorded.**

**App-level text selection in the conversation pane.** Mouse-down anchors, drag extends, the span
renders in inverse video, release copies. Cell-to-character mapping that respects wrapped lines and
**never crosses a region boundary** — which is exactly what terminal selection cannot do, and the
measured proof is in §B10: a `Shift`-drag across one line of the running M1 build returned
`+3 −0 ││ ┌Spend───…`, three regions' worth of cells from one screen row. `helix` and `zellij` are
the reference implementations. **It is about a week of work and it is not the frame**, which is
what M1 exists to prove; M1 ships `Shift`-drag plus `y`/`Y` copy, which covers the need without
pretending to be the same thing.

**The launcher on macOS and Linux** (§B17). Windows ships in M1 because Windows Terminal exposes
all three of what §B17 needs — `--focus`, a named profile, and additive settings. The equivalents
exist elsewhere (iTerm2 dynamic profiles, GNOME Terminal via dconf, kitty and alacritty config
fragments) but each is a separate implementation that has to be **verified on the platform** rather
than reasoned about from another one. Until then `marlowe --launch` reports the degraded path and
runs in the current terminal.

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

#### Acceptance status, measured 2026-08-17 — **four rows are UNMET and two of those are UNSCHEDULED**

**Why this block exists.** The session table above was corrected in the same pass, and correcting a
session table without auditing the acceptance list is exactly how **M0b shipped 40% of its named
mechanism and closed without saying so** — the failure `STATE.md` documents at length. Committing it
a second time, in the same repository, having read the entry, would be worse than the first. Each row
below carries the command or the path that decided it, not a recollection.

| Acceptance row | Status | Evidence |
|---|---|---|
| Install → first useful output <5 min, zero config, clean container | **UNMET — unmeasured** | Session E item 3, running now |
| First-run onboarding states what Marlowe can reach | **UNMET** | Session E item 4 |
| Path-traversal suite passes **and** access is handle-based | **MET** | Session B, both platforms, `MARLOWE_TRAVERSAL_STRICT=1`, 11/11 classes `RAN`; ADR-027 |
| **SWE-bench Verified and Terminal-Bench 2.0: competitive** | **UNMET AND UNSCHEDULED** | No occurrence of either name anywhere in the repository — no harness, no adapter, no run, no result |
| **τ-bench / BFCL: competitive** | **UNMET AND UNSCHEDULED** | As above. Neither name appears in any `.rs`, `.py`, `.toml`, `.json` or `.yaml` outside `target/` |
| Compaction preserves governance across the boundary — *tested explicitly* | **MET** | `marlowe-loop/tests/compaction.rs:70` and `:173`. Driven through `Engine::run` with a summarizer that preserves nothing, asserted on the assembled view **and** on the view the driver was handed, with an explicit vacuity guard (`state.compactions >= 1`) |
| Compaction invalidates cache — *tested explicitly* | **MET** | `compaction.rs:222`. Asserts the epoch moves **and** that the stale entry is gone rather than merely unreachable |
| Startup fails on an unannotated tool manifest | **MET, structurally — and stronger than the row asks** | `ToolRegistration.manifest` is `CapabilityManifest`, not `Option`, so an unannotated registration is unrepresentable (`registry.rs:108-121`). A missing **role** is a load error (`manifest.rs:434`); a missing **consequence** loads as the *maximum* (`manifest.rs:413`) — fail-closed by default rather than by refusal, which is deliberate and is not what this row's wording describes |
| **Budget tests from HP10 pass in CI** | **UNMET — there is no CI** | `marlowe-loop/tests/hp10_budgets.rs` exists and passes locally. `.github/` does not exist, and no CI configuration of any kind is in the repository. The row is blocked on CI existing, not on the tests |

**Three things this audit turned up that are not scope calls and are recorded here so they are not
rediscovered.**

**1. Whether the four benchmark rows block M2's closure or are deferred is a scope decision, and it
is deliberately not made here.** They are flagged, dated and left open. What is *not* open is whether
they have been done: they have not, and nothing in the repository suggests any of them was ever
started.

**2. "Pass in CI" is unachievable for every row in this project, not just this one, because there is
no CI.** M1's acceptance carries *"§B13 suite run on native Windows Terminal **and** a Linux
emulator — pass on both"*, and Session B's note says both-platform verification is *"a standing
requirement rather than a one-time closure"*. With no CI, every standing check in this project stands
only as long as a human remembers to run it by hand — which is the same failure mode as a guarded
path that moved, one level up. Both were last run by hand.

**3. `LoadError::MissingManifest` has no constructor anywhere in the workspace.** Its doc comment
says *"The system does not start"*, describing a runtime refusal that cannot execute, because the
property is enforced by the type instead. The variant is vestigial rather than broken — the guarantee
is real and is stronger than the variant claims — but it is instance #16's shape in miniature: a
declared control with no reader. Left in place, named here.

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

## M5.5 — Project knowledge

**Ships:** documents and reference material as memory, scoped to a project.

Not a new subsystem — §5's memory pointed at documents instead of conversations. Ingest is
`remember()` with a document source; persistence and retrieval are unchanged. The only new
mechanism is **scoping**: a project's knowledge surfaces inside that project and stays quiet
outside it, as a filter on the candidate set.

The value is that a research or engineering project stops being re-explained every session.
Papers, specs, decisions, and prior results accumulate and surface when relevant.

**What this is not.** Injection is a *knowledge* channel, not a *capability* channel. Where the
model can reason but lacks a specific fact, convention, or worked technique, injected memory
closes that gap. Where the model cannot do the reasoning, injecting examples produces confident
mimicry, which scores worse than abstention. Nothing here substitutes for fine-tuning, and the
distinction must be stated wherever the capability is described — the failure mode looks like
success in testing.

**Acceptance:** cross-project leakage zero — a project's knowledge never surfaces outside its
scope; injection precision on document-sourced memory measured separately from conversational
memory and held to the same ≥0.95; ingest of a 500-page corpus stays inside the §5.7 token and
latency budgets at query time.

**Non-goals.** No bulk context loading at session start — that is what §6 argues against, and
the ≤7,000-token budget forecloses it. The right three surface; the other four hundred do not.
No analogical or structural retrieval — see M9.
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

**Candidate direction: research memory.** Analogical retrieval — matching on structure rather
than surface, "this looks like a relation I remember." All five cues match on surface features,
so two problems with the same shape and different vocabulary are invisible to every one of them.
This is a known-hard problem and the honest technical content of the idea. Gated on M0b: if
basic retrieval misses K1, a sixth cue is irrelevant; if it clears comfortably, the M0b data
shows what the cue set actually misses, which is a better basis than reasoning about it now.
The capability-vs-knowledge distinction in M5.5 applies with more force here — a derived
technique entering procedural memory needs a **verifiable** outcome (proof holds, tests pass,
numbers reconcile), never utilization, or a wrong technique compounds each time it is reused.
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
