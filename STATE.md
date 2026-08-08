# State

**Updated:** 2026-08-08 — **M1 is CLOSED (`ed25914`). Current milestone: M2**, branch `m2-loop`.
Session A shipped the spine (loop, tools, permissions, runs, assembler); **Session B shipped path
scoping whole** — traversal suite and handle discipline together, ADR-027, **verified on Windows AND
Linux**. **414 cargo tests on Windows, 62 on Linux, `eval/` untouched at 72.** Next is Session C.

**M0b is COMPLETE and SHIPPED.** The Session J fine-tune is on the scored path; held-out R@1
**0.5764 → 0.6725**. K1 is amended and pinned. The precision/coverage curve is published and an
operating point is declared.

**M0c Session A (branch `retrieval-m0c`) ran head separability to a conclusion and shipped nothing.
R@1 stays 0.6725.** Both named candidates are measured and closed; K1's 10%-coverage interval is
retired as arithmetically unreachable. See "M0c Session A" below and `runs/session-m0c/RESULT.md`
before proposing any retrieval work.

> ### R@1 COUNTS THE SUPERSEDED FACT AS A HIT. Every R@1 in this project is inflated.
> LongMemEval marks **both** the stale and the current turn `has_answer`, so returning the outdated
> value scores as correct. Held-out **0.6725 → 0.6288** counting only the current value; on
> **knowledge-update 0.7222 → 0.4444**, where **10 of 26 apparent hits (38.5%) are the stale fact**
> (fit: 15 of 26, 57.7%). **Report `R@1_current` beside R@1 from now on.**
> `docs/design/HARM-WEIGHTED-PRECISION.md`.

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

**0. A CAPABILITY REPORT IS NOT AN EMISSION REPORT.** This is the standing lesson, and it was the
**eleventh** instance of the pattern this file has recorded — the first where *the harness disabled
the very thing it was verifying*. **The twelfth is in Standing checks below, and it is the first the
family caught prospectively**: `Deserialize` routed around a validating constructor, closed before
it existed rather than found after it shipped.

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

## Next action — M2 Session C2: the Ollama adapter

**ADR-028 (the human's decision): Marlowe runs against a LOCAL OLLAMA ENDPOINT first.** Hosted
providers register later. This dissolves the K6 tension rather than trading against it — an env
var, a first-run prompt and a bundled key all put *something* in front of the first run, and K6
measures whether that something is there, not whether it is small.

**Build the provider adapter; do NOT build the credential broker.** Ollama needs the first and none
of the second. Three requirements from ADR-028: degrade honestly when Ollama is absent (invariant 4
— a declared value on the run, surfaced in the status band, naming the remedy); record the
capability difference, tool-call reliability especially, so a debugging session can tell a harness
bug from a 7B model; and keep ADR-008's routing as a table over local models whose shape survives
hosted models arriving. `CapabilityProfile::model_route` already names a task role, never a model.

**Still owed from C1: the four executors** (`read`, `edit`, `find`, `bash`). The scope work they
need is done — see below. `bash`'s `cwd` needs its own assertion: `CreateProcess` takes a cwd
*string*, not a handle, so Windows relies on the walk's pinning a **second** time. That argument
must earn a test rather than inherit the walk's.

### M2 Session C1 — 2026-08-08. The platform gate and the write path.

**421 cargo tests on Windows, 65 on Linux under `MARLOWE_TRAVERSAL_STRICT=1`.**

- **`WorkspaceScope::new()` refuses at construction on an unverified platform.**
  `VERIFIED_PLATFORMS = ["windows", "linux"]` — what has been *executed*, not what compiles.
  **macOS is deliberately absent**: case-insensitive and NFD-normalizing, which is exactly where
  `glob`'s matching and `request`'s NFC handling would diverge.
- **`ParamType::WritePath`, declared per parameter.** `edit`'s `path` may create; `bash`'s `cwd` and
  `read`/`find`'s `path` must exist. Deriving access from consequence level would make two
  different requirements take their behaviour from the same number.
- **`Access` threaded through the walk.** It applies to the **final component only** — every
  directory on the way is opened read-only and refused if it is a reparse point, whatever the
  caller intends at the end. Creation happens *inside the already-verified parent*, which is why it
  is safe: the parent is still held open (pinned on Windows, an `openat` descriptor on POSIX).
- **A create positive control**, because a scope that only opened existing files would pass every
  other test in the suite and make `edit` impossible. It also asserts the negatives: a refused
  create must not create, and a create through a junction must not land outside.

### Superseded — M2 Session C's original framing

**Scope: `ROADMAP.md` §M2.** Sessions A and B are done. C builds the executors behind
`driver::ToolHost` (and they must take the handle from `Adjudication::handles`, **never re-open a
path** — that is the one way to reopen the race ADR-027 closed), `SKILL.md` loading with progressive
disclosure, `find_skill` semantic discovery, MCP as tool transport, and a provider client honouring
`CallLimits::max_output_tokens` as a hard cap.

**Before writing an executor, read ADR-027's last section.** The wall is the handle walk; an
executor that calls `File::open(scoped.resolved())` has undone it, and no test in the traversal
suite would notice, because the suite tests the checker and the race would be in the caller.

### M2 Session B — 2026-08-08. Path scoping, whole. ADR-027.

**412 cargo tests (from 375), `eval/` untouched at 72.** `WorkspaceScope` replaces the refusal;
`Unavailable` is retained for profiles that must provably not touch the filesystem.

**Three parts, and only the third contains anything:** `request` refuses ambiguous spellings before
any syscall, `glob` matches the declaration, `walk` opens without ever letting a string be resolved
twice. POSIX: `openat` + `O_NOFOLLOW` per component. Windows: every directory pinned open with a
share mode **excluding `FILE_SHARE_DELETE`** (so the prefix cannot be renamed out from under the
walk), plus `FILE_FLAG_OPEN_REPARSE_POINT` with refusal on `FILE_ATTRIBUTE_REPARSE_POINT`, plus
root identity verified before and after.

**The TOCTOU test races, and proves it races.** `tests/toctou.rs` carries a deliberately vulnerable
`naive_check_then_open` and **asserts that it escapes** — returning out-of-scope content under the
same interleaving. That is the half that makes the other half mean anything. The interleaving is
deterministic via a `WalkObserver` called at the exact vulnerable instant (`()` in production), not
a thread racing and hoping. On Windows the test also asserts the swap failed *as a sharing
violation*, so a swap that failed because `mklink` was missing cannot leave it green.

**BOTH GAPS ARE CLOSED, and the closing condition is now a standing requirement.**

They were real and blocking: the symlink class could not run on Windows (os error 1314, privilege
not held), and the POSIX walk had never been executed — ADR-002's inversion landing on the security
boundary.

**Closed 2026-08-08 on WSL2 (Kali, ext4 `/tmp`, native symlinks), `MARLOWE_TRAVERSAL_STRICT=1`, all
62 tests green and the coverage manifest reporting `RAN` for all eleven classes including symlink
escape.** The POSIX `openat`/`O_NOFOLLOW` walk executed for the first time there, and
`the_naive_implementation_escapes_which_is_what_makes_this_a_race` passed on Linux too — so the race
window is demonstrably real on Linux and `O_NOFOLLOW` demonstrably closes it.

**The standing requirement, because a one-time run is not a guarantee:** the suite runs on **both**
platforms with `MARLOWE_TRAVERSAL_STRICT=1` before path scoping is called verified after any change
to `scope/`. Windows alone leaves the symlink class unrunnable; Linux alone never executes the
pinning. `.wsl-probe.sh` is deliberately **not** kept — a script nobody reads is not a procedure;
the command is two lines in ADR-027.

**A guard whose subject moved is no guard.** Splitting `scope.rs` into `scope/` made the brief §13
hook name a file that no longer existed — path scoping was silently unguarded and nothing said so.
The entry is now a directory prefix, the hook grew `--self-check`, and
`marlowe-permission/tests/boundary_hook.rs` fails the build on a stale entry. Verified by a negative
control: renaming a guarded file makes it fail by name.

**Positive controls are in the suite deliberately.** Session A's refuse-everything scope would pass
every negative assertion in a traversal suite. Legitimate deep reads and lookalike filenames
(`console.log`, `a..b.txt`) must open, or the suite measures presence rather than correctness.

**After C, in order:** D — wire M0b's memory in, including K1 condition 3's abstention path, which
is a condition of the criterion M0b was judged against and is **load-bearing**. E — the TUI against
the real loop, first-run onboarding (ADR-002 makes it a requirement, not a nicety), K6 measured in a
clean container, and M1's one open acceptance row (accent on a light background).

### M2 Session A — 2026-08-08. The spine: loop, tools, permissions, runs.

**Three new crates, one-way layering: `marlowe-tools` → `marlowe-permission` → `marlowe-loop`.**
375 cargo tests (from 273), `eval/` untouched at 72, conformance unchanged
(`REJECTED, 0 findings, fail_no_time_dependence` — the baseline since Session B, see Known issues).

**The three things M2 had to get right so M3 extends rather than replaces:**

1. **Every spawn declares a `CapabilityProfile`**, and `reads_untrusted && !exposed_tools.is_empty()`
   is a load-time error — private fields, one constructor, and `Deserialize` routed through it so a
   profile from a file cannot bypass what a profile from code cannot. **Two refusals beyond the
   pinned one** (ADR-022): a quarantined reader may not write memory and may not hold egress, because
   the empty tool set closes neither — the loop's own `MemoryWrite` step is not a tool.
2. **Every spawn declares a `Budget` and an `OrphanPolicy`.** `OrphanPolicy` is recorded in the
   `RunSpawned` payload and unused, which is what makes M3 an extension. All six budget dimensions
   fire, each tested individually.
3. **Children return `CondensedResult` and nothing else.** The child's `SessionState` is dropped when
   the recursive call returns; there is no accessor that hands a parent a child's history.

**A subagent is the one loop re-entered** (ADR-022). `tests/hp10_budgets.rs` fails the build if a
second driving loop appears in the crate.

**The decision most likely to be argued with is ADR-023, and it should be read before Session C.**
Taint is computed by the harness from the context window — `ModelStep::ToolCall` has no taint field
at all — so a model-composed Target carries the **worst trust class in view**. The consequence looks
like a bug the first time it fires: **once a run has read untrusted content, every model-composed
Target in that run is blocked.** That is §8.2's trifecta break arriving as a property rather than a
second mechanism, and it means orchestrator-worker is *required* for any run that reads the web and
then acts, not an optimization for hard questions.

**Two defects found by tests, both fixed, both recorded because their failure modes were invisible
from their own tests:**

- **The assembler dropped any block larger than its source cap.** A single long turn vanished. Found
  by a 70%-trigger test reading `fill_pct = 0.0024`. Fixed by ADR-025: only *recoverable* sources are
  trimmable — history is not, so history pressure raises fill until compaction handles it with the
  durable appends in front. Omissions are now marked in the view, never silent.
- **Two spin paths.** Compaction compared successive iterations rather than its own result, and
  tool-result masking re-ran when it had nothing left to mask. Both presented as a hang, which is the
  worst shape: `MAX_STEPS` caught them as a budget pause, which reads like a model problem.

**`--reranking`-class hazard avoided, worth naming:** `ExposedSet`, `CapabilityManifest` and
`CapabilityProfile` all route `Deserialize` through their validating constructor. A field-wise
deserialize would have left every in-code test green while the only path that reads outside input
skipped the check.

**Known gap in the brief §13 hook, measured not assumed.** The permission layer's files are guarded;
`engine.rs` — the loop's *call* into it — is not, because guarding it would make every loop change
ask. What stands behind the call site is a test that drives a real blocked call through the loop.
See CLAUDE.md's enforcement table.

**Deferred from M1 and still deferred:** app-level text selection in the conversation pane, and the
launcher on macOS/Linux (§B17). Both are Session E or later; neither blocks anything.

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

### M0c Session A — head separability, MEASURED AND CLOSED. `runs/session-m0c/RESULT.md`.

**R@1 is 0.6725 and this session did not move it. Nothing shipped; there is no Rust diff.** Both
named candidates were built, four learned architectures were cross-validated, and a seventh
mechanism was found mid-session and taken to a held-out read. All null or negative.

**1. K1's interval reading is ARITHMETICALLY UNREACHABLE at the declared operating point.** A
**perfect** selector — 23 of 23 — has a Clopper-Pearson lower bound of **0.8518** at 10% coverage on
n = 229. Clearing 0.95 by interval needs **n_c ≥ 72 with zero errors, or ≥ 110 with one**. This is
not a retrieval statement; it retires a target the way ADR-016 retired the 0.3739 ceiling.
**Do not register a band on it.** `tools/reach_head_r0_attainability.py`.

**2. Candidate A — a relevance-fitted confidence signal — is NEGATIVE.** No query-time feature beats
the rerank margin at the head, and the three with *better overall AUC are worse there*. Overall
discrimination and head discrimination are different quantities on this corpus.

**3. Candidate B — set-wise / listwise scoring — is a NULL across four architectures.** Out-of-fold,
5-fold CV by conversation: S1 set-wise head **+0.0044**, L1 listwise fine-tune **−0.0131** (null
*with power*, discordant 13, p = 0.5811), LS1 **+0.0000**, S2 global cross-encoder with token-level
cross-talk **+0.0000** (top-1 changed on 2 of 229). **The binding resource is labelled data** — 229
fit queries, 38 recoverable failures, on a reranker Session J already fine-tuned on them.

**4. Slate construction gained +0.0087 on fit and lost −0.0044 on held-out.** Input recall rose
+0.0175 and conditional accuracy fell −0.0189 to meet it. The Session J addendum pattern exactly.

**5. THE FAILURE MODE IS NOW CHARACTERISED, and it is not what STATE.md said.** Same-session
gold-to-rank-1 turn gaps are **−10, −8, −6, −4, −2 — all even, therefore SAME ROLE**. The failure is
**discriminating between two USER turns in one conversation several exchanges apart**. Rank 1 on
failures is assistant-authored on only **5.3% (fit) / 7.5% (held-out)** of cases — the Session J
fine-tune already removed the user/assistant confusion. **The "47.1% assistant-authored" figure
below is stale and turn-pair chunking's rationale goes with it** (measured ceiling: +0.0087 fit,
+0.0131 held-out).

**6. A METRIC MISMATCH, resolved.** Systems publishing "96.6% on LongMemEval" report **session-level
R@5**. Marlowe measures **0.9738 session R@5 shipped, 0.9869 on its dense cue alone** — it is not
behind on that metric, it reports a far harder one (turn-level R@1 out of ~490 candidates). Never
quote one against the other.

**7. HARM-WEIGHTED PRECISION, measured for the first time. `docs/design/HARM-WEIGHTED-PRECISION.md`.**
§5.7 is about harm, not accuracy, and R@1 treats every failure as equal. Partitioning rank-1 into
harm classes — no new labels, LongMemEval's knowledge-update annotation carries it:

  - **Of the injections that are not the current value, 13 of 85 (15.3%) are HARMFUL and 72 (84.7%)
    are merely useless.** §5.7's premise is *weaker* than assumed on the failure side. Five in six
    wrong injections cost tokens rather than corrupt reasoning.
  - **But R@1 counts the stale fact as a hit** — see the box at the top of this file.
  - **At the declared operating point the two precisions are IDENTICAL**: published 0.9130, current
    0.9130, harm 0 of 23, on both splits. `PRECISION-COVERAGE.md` needs no correction at 10%
    coverage and a −0.0437 correction at 100%.
  - **Harm is zero at the head FOR THE WRONG REASON, and this is the part not to re-derive wrong.**
    Not "abstention suppresses harm" — that is a proxy conclusion. Knowledge-update queries are
    simply low-confidence (median margin **0.2782 vs 0.4020**) and make up **0.0% of the held-out
    top-10% slice against a 15.7% base rate**. *Within* knowledge-update the margin's relation to
    harm **flips sign between splits** (top-half harm 0.444 held-out vs 0.389 fit). The protection is
    a **category-exclusion side effect and it is fragile** — raising coverage, or improving
    confidence on knowledge-update, removes it with nothing reporting a change.
  - **§4.3's supersession exclusion is LIVE AND BLIND.** `entry.rs:124` is correct and called at
    `retrieve.rs:328` — not a wiring defect. But the only writer of `superseded_by` is
    consolidation's **≥0.98-cosine** near-duplicate merge (`consolidate.rs:697`); `ingest.rs:142`
    hardcodes `None`, §4.6's wire has no supersession field and forbids extras, and `store.rs:133`
    defers the contradiction detector. ADR-012 measured ≥0.98 pairs at **0.0086%** of 30.6M.
    **A missing component, not a tuning opportunity — and it is the component §5.7 assumes exists.**

**THE HUMAN LABEL SET is now the highest-value open item** — ≥400 judged injections, ≥50 per
category, judged blind, stratified by score decile. **True injection precision has never been
computed**; every figure is a gold-turn proxy, including the harm classes above. It is drawable and
it is the human's deliverable.

### M0c Session B — supersession is BLOCKED, not dead. ADR-028. `runs/session-m0c/RESULT.md` Part 7.

**Nothing was built. The verdict is about scope.** Three measurements, on fit, before any code:

- **R6, the ceiling.** A perfect oracle is worth **+0.1666 knowledge-update R@1 current-value-only**
  (0.3056 → 0.4722), **+0.0262 overall** (0.6900 → 0.7162), and cuts harmful injections **17 → 5**.
  **Worth building whenever it becomes reachable.**
- **R6, the power finding.** A perfect oracle produces exactly **6 discordant** — the bare minimum
  for α = 0.05 — reaching p = 0.0312 *only* because all six fall one way. **No realisable detector
  can produce a significant result on this split.** α is declared UNATTAINABLE IN ADVANCE; the delta
  carries any future verdict alone. The oracle's one-directional read is structural and must not be
  inherited by a real arm's instrument check.
- **R7, similarity CLOSED.** True pairs at ~0.83 cosine sit inside a distractor distribution reaching
  0.95. **Best precision anywhere: 0.0745** — twelve live memories permanently removed per correct
  catch, against a cost model registered before measuring. **ADR-012's 0.98 bar catches 0 of 33**,
  which is the quantitative reason the current merge is blind.
- **R8, value conflict CLOSED ON SCALING.** **0.4444 anchored** on the true stale turn; **0.0026
  unanchored** as a real detector runs — 4 true against ~1,539 false across 3.9M pairs, a **154×
  collapse**. The anchored number was the mechanism's precision *conditional on entity resolution
  already existing*. **The rule verifies supersession given a candidate; it does not find one.**

> **VERDICT (2): signal present, extraction missing.** Not undetectable — blocked on a component.

**OPEN GAP, with a named closing condition. DO NOT MARK SUPERSESSION CLOSED.** Detection requires
**entity resolution over the candidate pool**, which narrows 3.9M pairs to a handful before any value
comparison runs. **HP2 specifies it — `SameAs` beliefs with confidence and provenance, produced by
consolidation — and it has never been built.** `Payload::Entity` and `Payload::Edge` exist in §3.2;
nothing fills them. **Closing condition: that component exists**, and then a value comparison over
(entity, relation) triples clears **precision ≥ 0.5 measured UNANCHORED** — parity under the
registered asymmetry — at a recall moving the ceiling by more than one case. **Entity resolution is
HP2 and is NOT scoped here**; it needs its own registration and its own reachability check. Note it
would be the first live exercise of trust propagation through a derived belief.

> ### §5.7 CONSEQUENCE — the finding of this whole line of work
> **With supersession unreachable, harm being zero at the operating point is the ONLY protection
> that exists, and it is ACCIDENTAL.** The head contains **0.0% knowledge-update queries against a
> 15.7% base rate** because that category is low-confidence (median margin 0.2782 vs 0.4020), not
> because harm is detected. **The tripwire is now LOAD-BEARING, not diagnostic.**
>
> **Two ways it disappears, both things a future session might do deliberately:** coverage rising,
> or knowledge-update confidence improving. R6 measured the second — a perfect oracle takes the fit
> knowledge-update share of the top decile from **4.3% to 13.0%**. Neither announces itself.
>
> **`tools/tripwire_head_composition.py`**, baselined at
> `crates/marlowe-memory/artifacts/head-composition-baseline-v1.json`. TRIPs on any harmful
> injection at the operating point against a baseline of zero; WARNs when the knowledge-update share
> reaches the base rate, at which point the harm figure must be RE-MEASURED, not inherited.
> **`0 of 23` is reported with its interval every time — upper bound 0.1482.**

**THE CORRECTED BASELINE MUST APPEAR BESIDE EVERY PUBLISHED R@1.** Held-out **0.6288** current-value-
only against **0.6725** published; knowledge-update **0.4444** against **0.7222**. A session quoting
the published figure without knowing it counts stale hits as successes is working from a false
premise.

**§4.3's exclusion is untouched and is NOT the defect.** It is correct, wired and unit-tested. It has
no edges because nothing produces them.

**Also still open:** the gate-design constraint (ADR-016's closing section — either the resolution
rule or the margin feature's one-positive-per-query property must change; **re-tuning the resolution
stays forbidden**); QA accuracy (needs an API credential); **batching the depth-10 rerank** —
batch invariance measured **0.000000** on the shipped f32 graph in Session K, so it is available and
untested, and latency is the only currency that buys depth.

**Do not re-attempt:** consolidation, PRF, entity expansion, HyDE, session pruning as a quality
mechanism, length normalization, raising sequence length, **re-scoring the depth-10 slate by any
learned mechanism**, or **the 10%-coverage interval**.

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
- **`cargo test --workspace` (412) and `cd eval && python -m pytest` (72).**
- **A traversal suite must contain an implementation it DEFEATS.** `tests/toctou.rs` asserts that
  `naive_check_then_open` escapes under the same interleaving. Without that half, a green suite is
  equally consistent with a test that never landed in the race window.
- **A guarded path that moved is unguarded, and says nothing.** `protect-boundaries.py --self-check`
  fails on a stale entry and `tests/boundary_hook.rs` runs it. Re-run after any file move under a
  guarded component.
- **A validating constructor must be the ONLY way in, `serde` included.** `ExposedSet`,
  `CapabilityManifest` and `CapabilityProfile` route `Deserialize` through theirs. A field-wise
  deserialize leaves every in-code test green while the one path that reads outside input skips the
  check — the same shape as a stale default, arriving through a different door. **This is the
  TWELFTH instance of the family in item 0, and the FIRST caught by design rather than by failure**
  — the other eleven were found after they shipped; this one was closed before it could exist,
  because the family's question was asked of the serde path specifically.

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
- **Turn-pair chunking is now MEASURED and small.** Ceiling +0.0087 fit / +0.0131 held-out. Its
  stated rationale is stale: 89.4% of gold is still user-authored, but rank 1 on failures is
  assistant-authored on only 5.3–7.5% of cases, not 47.1%. See M0c above.
- **A TOKENIZER WRAPPER IS NOT THE TOKENIZER.** `PreTrainedTokenizerFast` over the shipped
  `tokenizer.json` produced logits up to **3.56** from the raw `tokenizers.Tokenizer` the scored
  path uses — same file, same vocabulary, entirely plausible output. Twelfth instance of
  two-sides-silently-disagree. Anything scoring offline must use `tokenizers.Tokenizer` configured
  as `spike_cross_encoder.encode` configures it, and must assert against cached logits before
  writing.
- **A single 20% validation slice is not an instrument at this n.** It read one arm at +0.0435 that
  5-fold CV read at +0.0044 — 38 versus 37 of 46 queries. ADR-012. Use out-of-fold predictions over
  all 229.
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
- **Path scoping must be re-verified on BOTH platforms after any change to `scope/`.** Windows
  cannot run the symlink class without elevation; Linux never exercises the Windows pinning. A
  single-platform green is a half-measured wall. Both were run at the close of Session B.
- **`read`, `edit`, `find` and `bash` still have no executors** (Session C). Path scoping now
  admits a declared path, so a green traversal suite is evidence about the *checker*, not about
  filesystem tools that do not exist yet.
- **HP10's zero-config row is PARTIAL.** The library half is tested; **K6 — install → first useful
  output under five minutes in a clean container — is not measured** and lands in Session E. It is a
  milestone kill criterion, so do not let the passing library test be read as the criterion.
- **`TurnEvent` exists twice** — canonically in `marlowe-loop`, and M1's view-model copy in
  `marlowe-stub`. Session E deletes the stub's copy and points `marlowe-surface` at the real one.
  The two `BlastRadius` shapes (CONTRACTS §9's, and the stub's rendered form) reconcile there.
- **The M2 report line said "a spawn with an empty tool set and reads_untrusted fails at load
  time".** It is the **non-empty** set that fails, per CONTRACTS §5; the empty set is the valid
  quarantined reader. Both cases are tested so the two cannot be confused.

## Open questions for the human

1. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.
2. **QA accuracy needs an API credential.** A key and a small HTTP client in `tools/`. Offline
   measurement over retrieval output only; an answer stage on the measured path is milestone drift.
3. **The human label set is your deliverable and it is now drawable.** See above.

## Built

**M2 Session A** — the spine. Three crates: `marlowe-tools` (manifests with load-time default-deny,
`ExposedSet` capped in its constructor, the eleven builtins, tool descriptions carrying a trust
class), `marlowe-permission` (`TaintSet` failing closed, the `(action, target)` check, egress with a
deliberately strict URL parser, a path scope that refuses everything, the adjudicator),
`marlowe-loop` (the one loop, `Budget`, `Run`, `CapabilityProfile`, the context assembler,
provenance, ephemeral spawn, `TurnEvent`). **375 tests, from 273.** ADR-022 through ADR-026. Six
paths added to the brief §13 hook and pipe-tested.

**M1 Sessions A–B** — the TUI and classic CLI against the scripted stub, closed at `ed25914`. K4
carried and met. ADR-021.

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
