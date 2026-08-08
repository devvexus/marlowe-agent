# M1 Session A — the frame, the keyboard, the conversation, the status band, two inspector tabs

**2026-08-08.** The TUI and the classic CLI against a scripted stub. **Carries K4.**

Scope: `ROADMAP.md` §M1. Requirements: `03-addendum-terminal.md` **v2**. Glyph decision: **ADR-021**.

---

## §B13, every row

Each row is a command that prints a number. `cargo test -p marlowe-surface -p marlowe-stub`
— **70 tests, 70 passing, on both platforms.**

> **M1 IS NOT ACCEPTED. THIS RECORD WAS OVERSTATED AND IS NOW MARKED.**
>
> Every row below carries **how** it was verified. **A headless pass on a row about keystrokes,
> flicker, colour or terminal state is not a pass** — those are properties of what reaches a
> terminal, and `TestBackend` asserts what reaches a buffer. This session found three bugs that a
> fully green suite could not see (scroll that never moved, double-dimmed text, `NO_COLOR`), which
> is the evidence for the distinction rather than a theory about it.
>
> **Outstanding before M1 closes:** the 9-line interaction checklist driven end to end in one
> session, and the light-background legibility row, which has never been checked by eye.

| Metric | Target | Windows | Linux | Verified | Where |
|---|---|---|---|---|---|
| Time to first frame | < 150 ms | **1 ms** | **0 ms** | **live** (real TTY, raw mode + alt screen; one frame then exit) | `marlowe --tui --timing-probe` |
| Time to interactive | < 300 ms | **1 ms** | **0 ms** | **live**, same caveat | same |
| Dropped keystrokes during streaming | Zero | **0 of 54** | **0 of 54** | **headless** — keys injected into `App`, never through a terminal | `no_keystroke_is_dropped_while_the_stub_is_streaming` |
| Repaint flicker, 120×30 → 240×60 | Zero | **see below** | **see below** | **headless** — buffer diff, not observed on screen | `b13_rendering` |
| Tool call default footprint | 1 line | **1 × 6 calls** | same | **headless** | `a_settled_tool_call_occupies_exactly_one_line` |
| **Every bordered region has a label and a hotkey** | 100%, by test | **68/68** | same | **headless** (structural — the right instrument for this row) | `b13_region_contract` |
| **Regions reachable by keyboard alone** | 100% | **68/68** | same | **headless**; live only for `i`, the tab digits and `Tab` | `every_region_is_reachable_from_the_default_focus` |
| Background fills to signal focus | Zero | **0 of 612,000 cells** | same | **headless** | `not_one_cell_in_any_screen_carries_a_background` |
| Chrome inside a scroll area | Zero | **0 across 5 sizes** | same | **headless** | `no_label_hotkey_pager_or_tab_bar_falls_inside_a_scroll_area` |
| Distinct colours | ≤ 1+3+3 | **6 in use, 9 declared** | same | **headless AND live** — 58,226 chromatic pixels sampled off the running window, `#9B7EDE` dominant | `every_colour_emitted_is_one_of_the_declared_values` |
| Memory-related regions | Zero | **0 of 68** | same | **headless** (structural) | `b13_memory_surface` |
| **Accent legible on dark AND light** | eye, on each | 5.88:1 dark / 3.26:1 light | same | **dark: live** (pixel-sampled). **light: NOT VERIFIED — never opened on a light background** | contrast computed, eye check outstanding |
| Below-minimum width | honest refusal | **4 sizes, 0 box glyphs** | same | **headless** | `below_the_minimum_it_refuses_and_draws_no_grid` |
| Classic CLI command parity | 100% | **18/18** | same | **headless** | `every_command_in_the_registry_is_reachable_in_both_surfaces` |
| **Suite on Windows Terminal AND Linux** | pass on both | **70/70** | **70/70** | **suite headless on both**; a live frame was confirmed on Windows Terminal and on xterm under WSLg | qualified below |

**Verified live this session, beyond the table** (real window, real input, measured): chrome theme
`#0F0E14` matching the terminal background; `Y` copy landing 1,425 characters of clean markdown on
the system clipboard; `Shift`-drag reaching native selection under mouse capture (121 chars);
inspector tab selection by mouse; slash autocomplete with arrow selection; one-click dropdown
switching; hover (confirmed by the human); the key-collision guard refusing to start.

**A measurement retracted, recorded so it is not re-derived:** a claim that mouse motion events were
never delivered was **false**. It came from a synthetic pointer sweep against a window that had just
refused foreground activation, and terminals report motion only to a focused window. Synthetic input
into an unfocused window is not evidence about the application.

### Flicker, as a cell count rather than an opinion

Render frame N, render frame N+1, diff the buffers.

| event | cells changed | interior cells of the focused region | interior cells of every other region |
|---|---|---|---|
| focus change, 120×30 | 218 | 6 (`opus-5` brightening) | **0** |
| focus change, 240×60 | 458 | 6 | **0** |
| streaming text delta | conversation + status band only | — | **0 outside those two** |
| `waiting`, 3.5 s | **0** | — | — |

The 218–458 cells are border and title styles — one style swap per region, which is exactly what
§B2's *"focus is a border and a title, never a fill"* buys. A fill would have repainted every
interior cell of both regions involved; the measurement is **0**.

**`waiting` changed 0 cells over 3.5 seconds.** ADR-021's freeze is structural: the stub stops
sampling, the meter holds its last frame, and nothing in the widget branches on the state.

---

## Three qualifications, stated rather than absorbed

### 1. The Linux row is **partially** met, and the gap is named

**What was verified:** the full 70-test suite on Linux (Kali on WSL2, rustc 1.97.1,
`x86_64-unknown-linux-gnu`) — **70/70**, identical to Windows. That covers the Linux *build* and
the Linux *runtime path*: crossterm's unix backend, termios raw mode, the SIGWINCH resize path,
unix TTY handling, and every headless rendering assertion.

**What was NOT verified:** a Linux terminal *emulator*. WSL2's console is Windows Terminal — the
Linux userspace is real, the emulator is not. gnome-terminal, konsole and alacritty on a Linux
desktop remain unrun.

**This matters most for the braille row.** Glyph rendering is a property of the emulator and its
font, and it is the one thing ADR-021 deliberately has no fallback for. The Windows Terminal check
passed by eye (`marlowe --doctor`); the Linux-desktop check has not been done.

§B13's row is *"pass on both"*, and this is one pass and one partial. **It is not claimed as met.**

### 2. The accent's light-background number is the weakest measurement here

| background | contrast | WCAG |
|---|---|---|
| dark `#0F0E14` | **5.88:1** | clears AA for body text (4.5) |
| white `#FFFFFF` | **3.26:1** | clears AA for **large text and UI components** (3.0); **below** AA body (4.5) |

The accent carries labels and hotkeys, which are **small** text. On a light terminal `#9B7EDE` is
legible rather than comfortable, and it clears its threshold by 0.26.

**No change was made.** §B2 pins the accent, and `MARLOWE_ACCENT` exists for exactly this. The
number is recorded so the eye check argues with a measurement, and so a future change to
`ACCENT_RGB` has to move a number in a test rather than pass quietly. `marlowe --doctor` prints
both rows, **measuring the resolved accent rather than the default** — reporting an override on one
line and the default's contrast on the next would have been this project's signature defect.

### 3. M1's amplitude source is a scripted envelope, not a microphone

ADR-021, repeated here because this is where it would rot. The *widget* invents nothing and renders
what its source reports, so §B12's "reports real state" is **structurally satisfied**. The reading
is still synthetic. M2 replaces the source; the widget does not change.

---

## What shipped, and what did not

**Shipped:** the frame (six regions, conversation at 58% of the split, all chrome pinned outside
scroll areas); keyboard navigation built before any content; the conversation pane with §B6's
one-line tool calls, same-verb collapse, auto-expanding failures, live lines and the pinned pager;
the status band with all seven states and ADR-021's braille meter; **Runs and Schedule** live;
**approvals**; the classic CLI over one command registry; the width refusal, the `CSI 8` resize
request, and `marlowe doctor`.

**Deferred to M2, and reachable-but-honest in the meantime:** Sessions, Skills, Trust and Status
each render one bordered region saying what will live there and in which milestone. The `Ctrl-K`
palette indexes sessions, skills and models — none of which exist — so it says so rather than
searching a stub index. Mouse. `--dev`'s seventh tab.

## Two things a later session must not undo

- **`marlowe-surface` depends on `marlowe-stub`, never the reverse.** That is what makes
  ARCHITECTURE.md §2.14 — *a surface holds no state the daemon lacks* — a property of the
  dependency graph rather than a discipline. A surface that cannot produce a session value cannot
  invent one.
- **Every render is a pure function of `(state, now_ms)`.** The stub owns the clock
  (`frame_clock.rs`, the second and last fence in `determinism_guard.rs`). A stray `Instant::now()`
  inside a widget would make every flicker row above unmeasurable, and the guard names the file.
