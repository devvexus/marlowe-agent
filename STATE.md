# State

**Updated:** 2026-08-08 — **M0b is COMPLETE and SHIPPED.** The Session J fine-tune is on the scored
path; held-out R@1 **0.5764 → 0.6725**. K1 is amended and pinned. The precision/coverage curve is
published and an operating point is declared. **Current milestone: M1.**

## The shipped configuration

`--reranking models/ms-marco-MiniLM-L-2-v2-ft-session-j` — **f32**, seq 256, batch 1, depth 10,
sha256 `9c222dac…`. ADR-018 (the measurement), **ADR-020** (the shipping decision).
`runs/session-k/RESULT.md`.

| held-out, n=229, from the BINARY | Session H | **shipped** |
|---|---|---|
| **R@1** | 0.5764 | **0.6725** |
| R@5 | 0.8428 | **0.8865** |
| R@10 | 0.9039 | 0.9039 |
| **input recall** | 0.9039 | **0.9039** |
| **conditional accuracy** | 0.6377 | **0.7440** |
| retrieval P95 warm, full split | 149 ms | **211 ms** |
| retrieval P95 **cache-cold**, 40-case subset | — | **238 ms** |
| tokens over budget | 0 | **0** |

**`R@1 = input_recall × conditional_accuracy` factors exactly and input recall did not move by one
case.** A cross-encoder changes the order within the slate, not what is in it. The whole gain is
conditional accuracy, **+0.1063**. Lexical (0.5415), dense (0.4454), `fitted_gate` (0.5371) and the
either-cue oracle (0.6463) are **bit-identical** to Session H — that is the control.

**Two deltas, and they answer different questions.** **+0.0699** is fine-tuned vs **un-tuned f32** —
the contrast that isolates domain adaptation, with the test behind it (discordant 38, `p = 0.0139`).
**+0.0961** is what a user gets, because what was replaced was **int8**. Never quote +0.0961 as the
fine-tuning effect.

**Budget margin is now thin: 238/300 cold leaves 62 ms.** K1's precision numbers are *defined* at
these budgets — a violation makes them void, not caveated.

## READ THIS FIRST — three things that must not be re-derived wrong

**0. A CAPABILITY REPORT IS NOT AN EMISSION REPORT.** This is the standing lesson, and it is the
**eleventh** instance of the pattern this file has recorded — the first where *the harness disabled
the very thing it was verifying*.

M1's frame rendered entirely achromatic in Windows Terminal for four rounds of screenshots while the
startup record printed `tier=truecolor`. Nothing was wrong with the detection: the terminal really
was truecolor. `NO_COLOR=1` was set in the environment of the shell that launched it, crossterm
honours `NO_COLOR` **at the formatter level** — `SetForegroundColor(..)` emits `ESC[m`, an empty SGR
which is a full reset — and every cell was therefore painted in the terminal's default foreground.
The layout, the styles, the region contract and the colour tier were all correct simultaneously.

**The probe was answering the wrong question.** It measured what the terminal *can carry* and
reported it where the reader would understand *what will be emitted*. Those two are different
quantities and nothing in the system compared them, so they disagreed in silence — the same shape as
the `--reranking` default, the `--embedder-model` default, and the eight before them.

The fix is `Theme::emission_report()`, which states what will actually be emitted and names the
override; it has a regression test. **The fix is not to stop honouring `NO_COLOR`** — that is a
legitimate user preference, and overriding it silently would be the identical sin inverted.

Generalised, for the next time: **when a component reports a capability, ask what it would print if
the capability were present but suppressed downstream.** If the answer is "the same thing", the
report is decorative. Diagnosing this cost four rounds and was only closed by writing three probes
that emitted known bytes and measuring the resulting pixels — *the screenshot was right and the
record was wrong* the entire time.

## READ THIS FIRST — two things that must not be re-derived wrong

**1. The 0.3739 ceiling never measured retrieval quality.** ADR-016. **A perfect retrieval system
scores 0.8483 on the shipped gate** against a 0.95 threshold: `fit_isotonic`'s smallest expressible
block is 435 rows spanning **100% of queries**, and the gate has no vocabulary for confident
subsets. Nine sessions read the gap as closable by better retrieval. It never was. **This
invalidates no retrieval measurement** — R@1, R@5, R@10, conditional accuracy, the oracle and every
closed mechanism were measured against gold turns with the gate uninvolved. `THRESHOLD = 0.95` is
untouched.

**2. R@1 and the operating point are different questions, and this is now measured twice.**
+0.0961 R@1 bought **nothing** at the operating point — the head got slightly *worse* while the body
got clearly better. See below.

## K1 — amended 2026-08-08, and the curve is published

Pinned in `ROADMAP.md` → "K1 — amended 2026-08-08" and brief **§5.7.1**. Argument: **ADR-019**.
Proposal of record kept and marked ADOPTED at `docs/requirements/proposed-K1-amendment.md`.

**The threshold is NOT moved.** The criterion's *shape* changed from a single point to a published
curve, and a **new** kill condition was added: **a flat curve — precision at 10% coverage not
materially above precision at 100% — is project-level.** Condition 3 is **binding**: a configuration
that injects at low precision to raise coverage fails outright.

### `docs/design/PRECISION-COVERAGE.md` — the published curve

> **DECLARED OPERATING POINT: coverage 10.0%, precision 0.9130 (21/23), CI [0.7196, 0.9893],
> margin ≥ 1.1651.** State this, with its interval, wherever the capability is described.

**K1 original: still not reached.** No coverage level clears 0.95 with its interval lower bound above
the threshold. Shipping a materially better model did not change that answer.

**K1 amended, flatness kill: NOT met.** precision@10 `0.9130` vs precision@100 `0.6725`, delta
**+0.2405**, ci_low@10 `0.7196` > `0.6725`. The confidence signal carries real information.

**The prediction was published before the measurement and it held:**

| at 10% coverage | superseded int8 | **shipped fine-tune** |
|---|---|---|
| precision | 0.9565 (22/23) | **0.9130** (21/23) |
| at 100% coverage | 0.5764 | **0.6725** |

One case of 23 flipped at the head, against +22 of 229 across the split. Statistically
indistinguishable at the head, clearly better in the body.

**Guarantee ≠ precision, always reported apart.** Conformal at α = 0.05: τ = 1.4639, measured
`P(inject | wrong)` = **0.0133** against the **0.05** bound, precision 0.9333 (14/15) at 6.55%
coverage. The bound covers the false-injection rate among wrong queries; K1 asks for
`P(correct | injected)`, a selective risk it does not cover. **Global τ only** — largest wrong-query
calibration set is 12 against a floor of 40.

## Next action — M1

**Scope and kickoff: `ROADMAP.md` §M1** (`M1-KICKOFF.md` is deleted — it was v1 scope). Ships a
**scripted stub**. **Carries K4.** Read `03-addendum-terminal.md` fully before any interface work,
and `04-addendum-persona.md` before any user-visible prose — **including the stub's**.

**§B1 is binding: zero memory-related elements in the default view.** The `TurnEvent` enum has no
injection variant and must not gain one. M1 consumes none of M0b, deliberately — the interface must
not be shaped by what memory happens to do today.

### M1 progress — 2026-08-08

**Built and verified live in Windows Terminal** (not `TestBackend`): the frame, keyboard navigation,
conversation and §B6 tool lines, status band and seven states, inspector, approvals overlay, classic
CLI, width refusal, `doctor`. 87 tests green across `marlowe-surface`, `marlowe-stub`, `marlowe`;
`eval/` untouched at 72.

**Amendments to Addendum B made this session, all at the human's direction:**

- **§B10 — the mouse is captured.** Reverses the earlier "keyboard-first, so leave selection to the
  terminal" reasoning: drag-selecting the frame is the single thing that made a running application
  read as a printout. Keyboard remains complete; teardown is in the panic hook too.
- **§B10 — the first-keystroke rule.** The default focus is a region where letters are hotkeys,
  **never a text input**. Stated as a rule because the failure is invisible to any test that presses
  `Esc` first — "reachable after one extra key that no border mentions" still passes.
- **§B10 — copy is first-class.** `Shift`-drag (verified working under capture: 121 chars out of a
  live session), `y` for the focused turn, `Y` for the transcript as markdown. **Payloads are built
  from the model, never the screen** — the measured native selection returns
  `+3 −0 ││ ┌Spend───…`, three regions' cells from one row.
- **§B17 — the launcher.** `marlowe --launch` writes an additive Windows Terminal profile, scheme
  and theme, then opens the window. A desktop shortcut (`Marlowe.lnk`) runs it.

**Three bugs found by using it that no test caught, all now fixed:**

1. **Scroll never moved.** `move_within` computed `u16::MAX - 1` and the renderer clamped it back to
   the bottom, so the first notch moved nothing and so did the next 65,533. **Every unit test
   passed**, because they asserted `scroll` *changed*, not that the view *moved*. The renderer now
   hands its clamp back to the app.
2. **The third foreground weight was double-dimmed.** The palette carried the mockup's exact
   `#4a4460` **and** `Modifier::DIM` on top, "for terminals that honour it" — which had the
   reasoning backwards: an explicit fg colour is universal and SGR 2 is the unreliable half, so the
   modifier could only double-apply where it worked. Windows Terminal honours it, and the dimmest
   tier became unreadable. **The weights now carry no modifier**, so the mockup is the reference on
   every terminal.
3. **`NO_COLOR`.** See item 0 at the top of this file.

**Two Windows Terminal limits, measured rather than assumed** — do not re-attempt without new
evidence: `themes.window.frame` is accepted and **silently ignored** (focused title bar stayed at
the Windows accent colour `#946B33`); and the tab strip's `+` cannot be hidden while Windows
Terminal draws the title bar, while giving the title bar back to Windows removes `+` but repaints it
in the accent colour. The `×` *is* removable (`tab.showCloseButton: never`). Focus mode was tried
and rejected — it takes drag and close with it, and `WS_CAPTION` is already set, so no window-style
trick restores them.

**HOVER WORKS. A CLAIM THAT IT DID NOT WAS WRONG, AND THE WAY IT WAS WRONG IS THE LESSON.**

An earlier version of this section recorded, as a measured fact, that mouse motion events were never
delivered and that every hover state was dead code. **That was false.** The human confirmed hover
working by using it.

What the measurement actually showed: a synthetic pointer sweep via `SetCursorPos` produced
`mouse=2`. The harness had failed `SetForegroundWindow` three times immediately beforehand
("target window refused focus"), and terminals report mouse motion only to a **focused** window.
So the number measured the harness's inability to activate the window, not the application's
ability to receive motion.

**This is the same error as the `NO_COLOR` bug in item 0, committed while writing up the `NO_COLOR`
bug.** A probe answered a question adjacent to the one being asked, and its answer was read as a
product failure. The specific trap for anything driving a GUI from outside: **synthetic input into an
unfocused window is not evidence about the application.** Assert focus, or do not report the result.

No code change was kept. `ESC[?1003h` was briefly added and has been reverted — crossterm's
`EnableMouseCapture` already enables all-motion tracking, which is why hover worked all along.

**Deferred to M2, with a real blocker rather than a shrug: app-level text selection in the
conversation pane.** Mouse-down anchors, drag extends, the span renders in inverse video, release
copies. It needs cell-to-character mapping that respects wrapped lines and **never crosses a region
boundary** — which is exactly what terminal selection cannot do, and the measured proof is in §B10:
a `Shift`-drag across one row of the running build returned `+3 -0 || ,-Spend---`, three regions'
cells from a single screen row. It is blocked on Marlowe owning the renderer for that pane, it is
about a week, and `helix`/`zellij` are the reference implementations. M1 ships `Shift`-drag plus
`y`/`Y`, which covers the need without pretending to be the same capability.

**Two Windows Terminal limits, as measured facts with their numbers.** These are the evidence for
whether a native window is ever worth a milestone, so they are recorded as data, not impressions:

1. **`themes.window.frame` is accepted and silently ignored** (WT 1.24.11911.0). Set to `#0F0E14`,
   the focused title bar still measured **`#946B33`** — the Windows accent colour. A settings key
   that does nothing and reports nothing.
2. **The tab strip's `+` cannot be hidden while Windows Terminal draws the title bar.** The two
   reachable states were both built and measured: `showTabsInTitlebar: true` gives a title bar at
   **`#0F0E14`**, identical to the terminal background and seamless, but keeps `+` and the chevron;
   `false` removes the whole strip but hands the bar to Windows, which paints it **`#946B33`**. The
   `x` *is* removable (`tab.showCloseButton: never`). Focus mode was tried and rejected: it removes
   drag and close, and `WS_CAPTION`/`WS_SYSMENU` are **already set** (style `0x14CF0000`), so no
   window-style trick restores them — WT draws over the caption itself.

**The 9-line interaction checklist PASSED**, driven by hand by the human in one live Windows
Terminal session, 2026-08-08: every region hotkey, all five dropdowns opened and selected from, the
full Tab cycle and back, conversation scrolling, all seven status states, the approval overlay,
`Ctrl-C` handled by the app, a forced panic, and quit. `RESULT.md` records it attributed to the
human rather than as an unattributed "verified".

**ONE ROW LEFT BEFORE M1 IS ACCEPTED:** accent legibility on a **light** terminal background. §B13
asks for the eye, on each; it has a contrast number (3.26:1, which clears AA for large text and UI
components but not AA body) and has never been looked at. Open it once on a light background and
either accept it or move the accent.

### The two M0b directions, carried as named work rather than preconditions

**1. HEAD SEPARABILITY — the highest-weighted finding of Sessions J and K.** Fine-tuning dominates
the curve from 100% down to ~25% coverage and **stops helping at the head, which is exactly where
the criterion reads.** Something must make the top decile separable and **the rerank margin is not
it**. Two named candidates, both unexplored:

  - **A distinct confidence signal fit against RELEVANCE rather than against score** (ADR-017's
    rule). The margin is what conformal thresholds today and its head is where fine-tuning stopped
    helping. Candidates: agreement between cues, gold-length prior, session-level evidence.
  - **Set-wise or listwise scoring** that observes candidates jointly rather than independently. The
    cross-encoder scores each pair in isolation; nothing in the shipped path ever compares two
    candidates directly.

**2. THE HUMAN LABEL SET — ≥400 judged injections, ≥50 per category, judged blind, stratified by
score decile.** **True injection precision — the quantity K1 names — has never been computed**;
every figure to date is a gold-turn proxy. **It is now drawable**, because a conformal operating
point exists to sample from. It was not before.

**Also still open:** turn-pair chunking (untested, cheapest structural idea, addresses fragment
boundaries directly); the gate-design constraint (ADR-016's closing section — either the resolution
rule or the margin feature's one-positive-per-query property must change, and **re-tuning the
resolution stays forbidden**); QA accuracy (needs an API credential, not a design decision).

**Do not re-attempt:** consolidation, PRF, entity expansion, HyDE, session pruning as a quality
mechanism, length normalization, or raising sequence length.

## Standing checks — re-run on every cue, feature, pool or MODEL change

- **A second implementation of a scored-path component must reproduce the first, EXACTLY.** Session
  H: 0.5764 = 0.5764. Session K: **0.6725 = 0.6725**.
- **`analyze_cue_overlap.py` is the authority for binary-side R@1.** Its ranking functions and dump
  reader are module-level so a second tool imports them instead of restating them.
  `publish_precision_coverage.py` **refuses to write** unless its R@1 matches.
  **`score_longmemeval.read_scored` drops `survived_pruning` and `rerank_score`** — anything ranking
  from it silently falls through to the gate order. This cost a full wrong curve in Session K.
- **Determinism, batch and padding invariance are re-measured PER GRAPH and never inherited.**
- **Pin the ONNX graph optimization level on both sides.** `ort` uses `Level1`; Python defaults to
  `ORT_ENABLE_ALL` and fuses differently — 0.0699 logits apart on identical token ids.
- **`repro --runs 2`, WITHOUT a cache.** Run it *early*.
- **`conformance` BEFORE any quality number.**
- **The artifact the driver reads must be the artifact the run scored with.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue.
- **The unchanged-cue check is a NULL INSTRUMENT for a pruning change.** Its silence is not evidence.
- **`cargo test --workspace` (190) and `cd eval && python -m pytest` (72).**

## Known issues

- **The export gap is now on the SHIPPED path.** The graph is **self-validated only** — this project
  is the publisher, so there is no external authority. Digest pinning, torch-vs-ORT at 1e-6,
  per-graph determinism/batch/padding invariance, and a second pair-encoder implementation
  reproducing HuggingFace exactly are what stand behind it. **They bound the gap; they do not close
  it.** Say so wherever the number is quoted.
- **Do not re-quantize the shipped graph without re-measuring `[1, 256]`.** ADR-015's shape-binding
  is a property of int8 graphs; **padding alone flipped top-1 in 15% of int8 cases** while f32 was
  invariant to 0.000000. The fine-tuned graph has never been measured quantized.
- **`MAX_SEQ_LEN` stays 256; the 7.86% gold truncation is a PRICED defect.** Raising it cost
  −0.0917 R@1 (`p = 0.0002`, α attainable) because the cap doubles as a length normalizer.
  ADR-017's closure was **withdrawn** on held-out. Only viable with a normalization term fitted
  against **relevance**, not against the score — and the registered `E[score|length]` estimator had
  slope −0.5091 and *added* score to long candidates.
- **At top-10 the shipped ranker is BELOW dense alone** (0.9039 vs 0.9170). It is a top-1 mechanism
  reordering ten candidates; do not read its R@10 as a capability.
- **The gate still injects nothing, and ADR-016 is why** — not retrieval quality. Conformance is
  REJECTED with 0 findings and `fail_no_time_dependence`, the unchanged baseline since Session B.
  **§4.3 maturation still has no contract-level coverage.** Wiring the declared operating point into
  an injection path, with condition 3's abstention path, is **M2 work and now load-bearing**.
- **Per-category reads are unstable across the split — a finding AGAINST group-conditional
  conformal, not a caveat on it.** Largest wrong-query calibration set is 12 against a floor of 40.
- **Do not quote Session H's McNemar p-values.** The test had no power; ADR-014.
- **Session pruning is closed as a QUALITY mechanism.** It remains a cost mechanism.
- **Turn-pair chunking is untested** and is a candidate for any session touching ingest. 87.7% of
  gold is user-authored; the distractors that beat it are 47.1% assistant-authored and 1.9× longer.
- **The failure mode is only 58% same-session.** Any brief describing it as same-session
  discrimination is wrong by that margin.
- **The additivity read's subsumption rule is defective as registered.** Fix before reusing.
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
- **M1's §B13 suite must run on both native Windows Terminal and a Linux terminal emulator.**

## Open questions for the human

1. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.
2. **QA accuracy needs an API credential.** A key and a small HTTP client in `tools/`. Offline
   measurement over retrieval output only; an answer stage on the measured path is milestone drift.
3. **The human label set is your deliverable and it is now drawable.** See above.

## Built

**M0b Session K** — the reranker ships. `rerank.rs` re-pinned to the fine-tuned f32 graph with a
named refusal for the superseded int8 directory; `cross_encoder_reference.rs` table-driven over both
vocabularies (**190 tests**, from 188); `analyze_cue_overlap.py` ranking lifted to module scope
(verified byte-identical); new `tools/publish_precision_coverage.py`; **three stale defaults
deleted** — `score_longmemeval.py --reranking` (defaulted to the *old* graph),
`session_j_verify_export.py --out-dir` (silently overwrote Session J's record), and
`make_cross_encoder_fixtures.py`'s hard-coded model. New: `docs/design/PRECISION-COVERAGE.md`,
`docs/design/M1-KICKOFF.md`, ADR-019, ADR-020, brief §5.7.1.

**Earlier:** A (workspace, contracts, journal, memory) · B (lexical cue, frozen gate) · C (dense
cue) · D (max fusion, **failed floor**, ADR-010) · E (per-query features, **failed floor**,
ADR-011) · F (consolidation, **null**, ADR-012) · G (query side measured, ADR-013) · H (cross-encoder
rerank ships, ADR-014) · I (sequence cap is a length normalizer, ADR-015) · J (ceiling never measured
quality / normalization null / fine-tuning is the lever — ADR-016, 017, 018).

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
