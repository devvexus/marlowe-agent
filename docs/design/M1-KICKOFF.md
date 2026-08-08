# M1 kickoff — the terminal shell against a stub agent

**Written 2026-08-08, at the close of M0b. Nothing in M1 has been implemented.** This file is the
scope handoff: what M1 is, what it carries, what it must not do, and what to read before touching
anything.

---

## The one sentence

**Ships the TUI and the classic CLI, driven by a scripted stub. Carries K4.**

Craft is proven *before* there is a real agent behind it, because craft retrofitted onto a working
agent never happens. M1 has no model call in it.

---

## Read before writing any code

| Path | Why, for M1 specifically |
|---|---|
| `docs/requirements/03-addendum-terminal.md` | **The interface requirements. Binding.** Read it fully — this is the milestone it was written for. |
| `docs/requirements/04-addendum-persona.md` | Anything producing user-visible prose carries the persona, including a *stub's* output. |
| `docs/design/ARCHITECTURE.md` | Component boundaries. |
| `docs/design/CONTRACTS.md` | **Before any code crossing a boundary.** `TurnEvent` lives here. |
| `STATE.md` | Always, at session start. |

**§B1 is binding and an earlier draft got it wrong:** memory is invisible in the interface. The user
experiences it through the agent knowing things — never through panels, scores, or citations.
Retrieval instrumentation exists only under `--dev`.

---

## Scope

Header line, conversation, input line — nothing else by default. One-line tool calls with typed
summaries, expand on demand, failures auto-expanding, live lines animating in place, consecutive
same-verb collapse. Three ambient values (context %, spend, elapsed) with context pressure as
**colour, not a bar**. `⌘K`/`Ctrl-K` palette. Slash autocomplete. Multiline default, Esc interrupt,
type-while-thinking. `!cmd`. `/undo N`. Local session recap with no LLM call. Modal approval overlay
— the only bordered element.

## Acceptance — §B9, all of it

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

**K4:** first frame >150 ms or any flicker at 80×24 → the terminal thesis is not achievable in this
stack, and ADR-001 is revisited. That is a real kill criterion, not a performance goal.

**The last row is symmetric and its direction has inverted.** ADR-002 (revised) puts development on
native Windows, so **Linux is now the surface at risk of being verified only in CI**. Both must be
run on a real terminal emulator. A TUI verified on one platform is not verified.

## Non-goals

No real agent. No memory wiring. No network. **No memory UI, ever** (§B1) — the `TurnEvent` enum has
no injection variant and must not gain one.

---

## What M0b hands over, and what it does not

**Hands over:** a memory subsystem that scores against M0a, a shipped reranker at held-out R@1
**0.6725**, a published precision/coverage curve (`PRECISION-COVERAGE.md`) and a declared operating
point. M1 consumes **none** of it. That is deliberate — M1 is the vehicle, and it is built against a
stub precisely so the interface is not shaped by whatever the memory system happens to do today.

**Does not hand over:** an abstention path. The amended K1's condition 3 requires that below the
operating point the system abstains and the agent recovers through the explicit `recall` tool
(§5.5). **That is M2 work and it is now load-bearing** — it is a condition of the criterion M0b was
judged against, not a nice-to-have. Do not let it drift.

## The two M0b directions that are carried, not closed

Neither is an M1 dependency. Both are named so they are not rediscovered.

1. **Head separability.** Session J's highest-weighted finding: +0.0699 R@1 bought **nothing** at the
   operating point. Something must make the top decile separable and the rerank margin is not it.
   Unexplored candidates: a confidence signal fit against **relevance** rather than against score
   (ADR-017's rule), and set-wise/listwise scoring that observes candidates jointly.
2. **The human label set.** ≥400 judged injections, ≥50 per category, judged blind, stratified by
   score decile. **True injection precision has never been computed** — every figure to date is a
   gold-turn proxy. Drawable now that a conformal operating point exists to sample from.

---

## Standing rules that do not pause for a new milestone

- **Every numeric target becomes an executable test.** A target that is not a command printing a
  number does not exist. §B9's table is eleven such commands, not eleven aspirations.
- **`eval/` is the scoreboard and is not modified to accommodate an implementation.**
- **Prefer a load-time error to a sensible default.** Five bugs in this project so far. A TUI has
  more places to hide one than a retrieval path does: terminal capability probes, colour depth,
  locale, and resize handling all have a plausible fallback that makes a mismatch unobservable.
- **Contracts in `CONTRACTS.md` are pinned.** If one is wrong, stop and raise it.
