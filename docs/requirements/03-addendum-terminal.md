# Marlowe Addendum B: The Terminal

**Companion to:** Marlowe — Requirements for a Memory-First Agent Harness (v1.0)
**Status:** Requirements specification.

---

## B0. Position

Marlowe is terminal-native. The CLI is not a debug surface for a product that really lives in a
web app; it is the product. Voice, messaging, and mobile are projections of the same session and
the same commands.

**The design target:** an engineer opens it and thinks *someone who uses terminals every day
built this*. Not flashy. Not a dashboard. The opposite — it should feel like the most restrained,
fastest, least cluttered agent CLI they have used, and the restraint should read as confidence
rather than as missing features.

The benchmark is Hermes Agent's TUI, which is the most complete in the category. Match its
capability. **Beat it on craft.** Hermes is feature-dense and shows it — boxed panels, a wide
multi-field status bar, a startup banner listing model, backend, working directory, every tool
and every installed skill. Every one of those is defensible in isolation. Together they are a
wall of chrome between the user and the conversation.

Marlowe's differentiation is subtraction.

---

## B1. Memory Is Not a UI Element

**This is a correction to an earlier draft and it is binding.**

Memory is the most important system in the harness (v1.0 §5). It gets **no special treatment in
the interface.** The user experiences memory the way you experience it in a good colleague:
they just know things.

Correct:

> This looks like the client version drift you hit in March — the pinned version got
> dropped when the Dockerfile was rebuilt.

Wrong, in every variant:

- A persistent panel showing retrieved memories and confidence scores
- A status-bar field for injection count or precision
- Inline citations on recalled facts
- Any default-visible indication that retrieval occurred

An agent that narrates its own recall is not demonstrating good memory. It is demonstrating that
it does not trust the user to notice. Memory that works is invisible; **the response is the
interface.**

**Corrections stay conversational.** "No, I moved off Postgres in April" is how a user fixes a
belief. It must work as plain speech and take effect immediately (v1.0 §5.3 reconsolidation).
Slash commands for memory exist as a power-user affordance — `/mem search`, `/mem forget`,
`/mem pin` — but they are not the primary path and they are not advertised in the interface.

### The one carve-out: `--dev`

Building a memory system whose failure modes are invisible is not possible. Under `marlowe --dev`
(or `/dev` in-session), a diagnostic pane becomes available showing what was injected, what was
rejected, retrieval scores, and full provenance — plus `/why` for retroactive inspection of any
turn.

**Off by default. Never shown to a user who did not ask. Not part of the product surface.**
It is instrumentation for building M0, and it exists because §5.7's 0.95 precision target is
unreachable without it.

---

## B2. The Screen

One header line. The conversation. One input line. Nothing else, ever, by default.

```
  marlowe  opus-5  ~/projects/ingest                             ⌘K
  ──────────────────────────────────────────────────────────────────

    why is the ingest job timing out again

  This looks like the client version drift you hit in March — the
  pinned version got dropped when the Dockerfile was rebuilt.

    ⋯ read   Dockerfile                                   48 lines
    ⋯ bash   git log --oneline -- Dockerfile              6 commits

  Confirmed. Commit 4a2f1c dropped the pin three weeks ago. Want me
  to restore it and open a PR?

  ──────────────────────────────────────────────────────────────────
  ›                                              12%  $0.18  22m
```

### Rules

**No boxes.** Structure comes from indentation, whitespace, and at most one hairline rule.
Box-drawing characters around panels are the single largest source of visual noise in terminal
UIs and Marlowe uses them nowhere in the default view. Overlays may have one border. That is all.

**One accent color.** Everything else is the terminal's own foreground at three weights: dim,
normal, bright. The accent marks exactly one thing — where the user's attention should go right
now. A palette of five semantic colors is a dashboard; a palette of one is a tool. Respect the
terminal's background and theme; never hardcode a background fill.

**Whitespace is the luxury signal.** A blank line above and below each turn. Two-space left
margin on everything. Terminal UIs that breathe feel expensive because almost none of them do.

**No startup banner.** The header line is the banner. Model, working directory, and nothing else.
Tool and skill inventories live behind `/status`, which nobody needs at session start and everybody
is shown by every competitor.

**The conversation is the hero.** Every pixel of chrome must justify itself against the cost of
taking space from the transcript.

---

## B3. Tool Calls — The Biggest Win

The single largest difference between a clean agent CLI and a noisy one is what happens when the
agent uses a tool. Most stream raw output into the transcript. Within ten turns the conversation
is unreadable.

**Every tool call renders as one line:** verb, target, and a result summary.

```
    ⋯ read   src/memory/store.py                        142 lines
    ⋯ bash   pytest tests/memory                    12 passed · 1.4s
    ⋯ edit   src/memory/retrieval.py                       +23 −7
    ⋯ web    "longmemeval abstention"                    6 results
    ⋯ bash   pytest tests/voice                     2 failed · 0.9s
```

- **Expand on demand.** Cursor to a line, press enter (or `Tab`) for full output in place.
- **Failures auto-expand.** A non-zero exit or an error shows its output immediately —
  the one case where the user always wants detail.
- **Live lines animate in place.** A running command updates its own line with elapsed time.
  It does not scroll output into the transcript and then clear it.
- **Consecutive same-verb calls collapse.** Six reads become `⋯ read 6 files` with expansion.
- **Result summaries are typed, not generic.** `142 lines`, `+23 −7`, `12 passed · 1.4s` — each
  tool declares how its result summarizes. `done` is not acceptable.

Long-running background work never scrolls the foreground. It appears as a single line that
updates, and the prompt stays live throughout.

---

## B4. Ambient State

Hermes puts model, token count, a fill bar, percentage, cost, and elapsed time in a persistent
bar. Six fields, always. Marlowe shows three, dim, right-aligned on the input line: **context
percentage, spend, elapsed.**

- **Context pressure is a color, not a bar.** The percentage is dim until 60%, amber at 60%,
  accent at the 70% compaction trigger (v1.0 §6). No progress bar — the number and its color
  carry it.
- **Compaction announces itself in one line** and does not interrupt: `─ compacted · 47 turns → summary ─`.
- **Degradation is stated, never silent** (v1.0 invariant 4). Fallback to a secondary provider or
  a reduced retrieval path shows on the input line in amber. One word. `degraded`. `/status` for why.
- **Full numbers live in `/status`.** Model, provider, tools loaded, skills installed, tokens by
  source, cost breakdown, active runs. One screen, on demand, never persistent.

---

## B5. Interaction

- **`⌘K` / `Ctrl-K` opens one fuzzy palette** over everything: sessions, models, skills, commands,
  recent files. Editor-grade — type-ahead, instant filtering, arrow-and-enter. This replaces
  four separate pickers with one keystroke and is the highest-leverage interaction in the design.
- **Slash commands autocomplete inline**, with descriptions, filtered as you type.
- **Multiline by default.** Shift-enter for a newline, enter to send. Paste of multiple lines
  never fires a premature send.
- **Esc interrupts.** Partial output is kept. Interrupt during a tool call follows v1.0 §9 —
  idempotent reads complete, mutations cancel.
- **Type while it thinks.** Input is never blocked. Queued messages send when the turn completes.
- **`!cmd`** runs a shell command in the agent's working directory, through the same approval path.
  A latency shortcut, not a security bypass. Non-zero exits shown.
- **`/undo N`** soft-deletes the last N turns, identically across CLI, TUI, and messaging.
- **Installed skills become slash commands automatically.**
- **User-defined commands that skip the model** entirely — the cheapest latency win available.

---

## B6. Approvals

The one place chrome is warranted, because this is where the security model meets the user
(v1.0 §8) and where most agent terminals degrade into reflexive clicking.

- **Modal overlay, visually distinct, impossible to answer by accident.** This is the only
  element permitted a border.
- **States blast radius, not the command.** Not `Run: rm -rf ./build?` but
  `Delete 1,204 files in ./build · not recoverable`.
- **Risk-tiered** per v1.0 §8.2 — silent for reversible reads, batched for routine writes,
  blocking for irreversible ones.
- **Novelty gating is explained in one line** when it fires: `unusual · first write outside workspace`.
- **`/trust`** opens the trust ledger (Addendum A §A8): action classes, tier, agreement rate,
  trend. Promote and demote in place. This is §A9's dashboard in its native form for this user.
- **Rubber-stamping is measured.** Track approval latency and approve-without-expand rate per
  class. When a user is clicking through, say so and propose either promoting the class or
  tightening it (v1.0 §14.8).

---

## B7. Sessions

- **Resume shows a tight local recap** — turns, tools used, files touched, last exchange —
  computed locally, no LLM call. Four lines, not a screen.
- **Compaction lineage is navigable** (v1.0 §6). `/lineage` walks the chain to read
  pre-compaction records.
- **`/runs`** lists active background work: status, budget consumed, elapsed. `/steer <run>`
  injects guidance into a running child without killing it (v1.0 §10.1). `/watch` attaches.
- **Two front-ends, one runtime.** A classic readline CLI that works over SSH and in minimal
  environments, and the TUI. Same agent, same sessions, same commands, same data. Explicit flags
  beat config. **No TUI-only features** — diverging them means maintaining two products.

---

## B8. Craft — Where "Engineer's Dream" Actually Comes From

Not from features. From four things users feel and cannot name:

1. **Nothing ever makes them wait.** First frame under 150 ms. Input accepted under 300 ms.
   Keystrokes never dropped, including mid-stream. The banner paints before initialization
   finishes.
2. **Nothing ever flickers.** Correct differential rendering. Resize reflows cleanly at any
   width down to 80×24. Streaming does not repaint the screen.
3. **Nothing is ever ambiguous.** Every state is legible at a glance. A user never wonders
   whether it is working, waiting, or stuck.
4. **Nothing is decorative.** Every moving element reports real state. No spinners where
   content could be. No mascots. No animation that is not information.

Get these four right and the interface will be described as beautiful by people who cannot point
to a single beautiful thing in it.

---

## B9. Acceptance Criteria

| Metric | Target |
|---|---|
| Time to first frame | < 150 ms |
| Time to interactive | < 300 ms |
| Dropped keystrokes during streaming | Zero |
| Repaint flicker during stream or resize | Zero, verified at 80×24 through 200×60 |
| Tool call default footprint | 1 line |
| Persistent chrome | ≤ 2 lines total (header + input) |
| Distinct colors in default view | ≤ 1 accent + 3 foreground weights |
| Box-drawn panels in default view | Zero |
| Memory-related elements in default view | Zero |
| Classic CLI parity with TUI | 100% of commands, sessions, data |
| Usable over SSH at 80×24 | Yes |

---

## B10. Anti-Requirements

- **No web UI in v1.** Terminal and messaging gateway are the surfaces.
- **No memory visualization outside `--dev`.** §B1.
- **No startup inventory.** Tools and skills belong in `/status`.
- **No multi-field status bar.** Three values, dim, on the input line.
- **No boxes outside modal overlays.**
- **No decorative anything.** No mascots, no pets, no ASCII art beyond the header word.
- **No TUI-only features.**

---

## B11. Sources

Hermes Agent CLI and TUI documentation (Nous Research) — classic REPL and TUI front-ends, status
bar composition, collapsible banner sections, modal overlays, non-blocking input, shell mode and
its approval semantics, `/undo`, local session recap, automatic slash commands from skills, TTY
fallback. Marlowe matches this capability surface and diverges on visual density by intent.

---

*Supersedes the first draft of Addendum B, which specified a persistent memory panel and a
memory field in the status bar. Both are removed. Memory is experienced through the response.*