# ADR-047 — Markdown and inline LaTeX in the conversation pane

**Status:** ACCEPTED and **BUILT**. `crates/marlowe-surface/src/{markdown,latex,chrome}.rs`.
**Binding on:** Addendum B §B2 (colour and the region contract), §B6 (the conversation), §B10 (`Y`),
§B13 (the acceptance rows), §B12/K4 (flicker and first frame).
**Depends on:** ADR-030 (the notice vocabulary — why harness prose is *not* markdown),
`marlowe_contract::text` (the display predicate).
**Corrects:** `marlowe-surface/tests/display_sanitiser.rs`'s recorded trade. See §7.

---

## 1. What changed and why it is not cosmetic

Model replies have always been markdown. The conversation pane drew them as flat text, so a reply
built out of a heading, a numbered list, a fenced block and a table arrived as one paragraph with
punctuation in it. §B12's third craft target is *nothing is ever ambiguous*; a wall of undifferentiated
prose is exactly ambiguous, and it is the single most-read region on the screen.

So the pane now renders markdown, and makes inline maths legible where a character grid can.

**The decision that shaped everything else is that §B2's colour budget forbids syntax highlighting**,
and that turned out to be a constraint worth having rather than one to work around.

---

## 2. The colour budget, and what markdown gets instead

§B2: *one accent plus three state colours plus three foreground weights*, and — in as many words —
**state colours encode state only, never category.** §B13 asserts the row and
`b13_rendering.rs::every_colour_emitted_is_one_of_the_declared_values` checks every emitted
foreground against `Theme::declared_colours()`.

Green-for-strings and blue-for-keywords are therefore out, and not merely on a technicality: amber
means *needs attention*, red means *failure*, green means *healthy*. A green string literal would
make the screen say something false about state, in the region the user reads first.

What is used instead is text **attributes**, which cost the budget nothing, plus the accent, which
§B2's own table assigns to *structure*:

| markdown | rendered as | why |
|---|---|---|
| heading | accent; **bold** at levels 1–2 | accent is structure. Bold gives three ranks — bold accent, accent, prose — without a second colour |
| strong | `BOLD` | |
| emphasis | `ITALIC` | |
| strikethrough | `CROSSED_OUT` | |
| inline code, code block | foreground **weight 1** (the terminal's own), indented two columns | see below |
| block quote | text at weight 2, with a `▏` rule at weight 3 | §B2: *"dimming is load-bearing"* |
| list bullet `•`, ordered marker | accent | structure |
| link text | `UNDERLINED`; the target in weight 2, **always shown** | see §5 |
| horizontal rule | a full-width run of `·` at weight 3 | **not** `─`. See §4 |
| table | aligned columns, bold header, **no rules at all** | see §4 |

**Code takes weight 1 — the terminal's own foreground — and that is the choice worth defending.**
Marlowe's prose is `theme.speech()`, a violet tint. The terminal's own foreground sits clearly apart
from it, spends nothing from the budget, and is what a reader already associates with verbatim
output. *Dimming* code was the obvious alternative and is backwards: code is the part of a reply
people most want to read.

Measured on a rendered buffer at five sizes: **six distinct foregrounds across a markdown-rich
frame, every one of them in `declared_colours()`**
(`markdown_render.rs::markdown_emits_no_colour_outside_the_declared_palette`).

### 2.1 `Modifier::REVERSED` is a background fill, and the existing §B13 row cannot see it

§B13 has a zero-background-fills row, and `b13_rendering.rs` walks every cell asserting
`cell.bg == Color::Reset`.

**Reverse video would pass that walk and paint a solid slab.** It is a modifier, not a `bg`, so the
assertion reading the `bg` field reports `Reset` for a cell the terminal fills. It is also the most
common way terminal markdown renderers draw a code fence.

This is the project's own failure family — a property asserted where it is *declared* rather than
where it is *seen* — so a code fence here gets an indent and a weight instead, and
`markdown_render.rs::not_one_cell_carries_a_background_or_reverse_video` asserts both halves. The
mutation `md_reversed` (make `Ctx::code()` reverse video) fails it and the unit test beside it.

---

## 3. The model authors this text, so rendering it is a new attack surface

Flat text could already *say* `  ⋯ read  /etc/shadow  48 lines`. What it could not do was choose
weight, colour or block structure. Interpreting markup hands the model all three, and this project
has shipped that failure twice: `CondensedResult::render` joining fields as `"{k}: {v}"` so a value
containing `"\nanswer: …"` forged a field header, and a tool `target` containing a newline forging a
second §B6 tool line. Both were closed **structurally**, at the render site.

**The mitigation is the same shape: the model does not get to speak the harness's vocabulary.**

`crates/marlowe-surface/src/chrome.rs` holds every glyph the harness draws as chrome, in one place.
`render.rs` reads it **as the source of the glyphs it draws**, and the reservation reads it as the
set it refuses — so a future chrome glyph that is not declared there is not drawn either, because
there is nowhere else to get one from. That is the construction
`marlowe_permission::blocks_composed_targets` uses to keep the §B6 trust banner and the
adjudicator's enforcement site from drifting apart.

| reserved | what the harness draws with it |
|---|---|
| `⋯` U+22EF | §B6's tool line marker |
| `▸` `▾` | disclosure — the reasoning block, the control-strip pickers, inspector actions |
| `↵` U+21B5 | "Enter acts here" |
| `▏` U+258F | the block-quote rule this crate draws |
| `│` `█` | the scrollbar track and thumb |
| **U+2500–U+257F** | box drawing — every §B2 border, the compaction rule |
| **U+2580–U+259F** | block elements |

The last two are **ranges, not the glyphs currently in use**. Blocking `─` alone leaves `━`, `═`,
`┏` and sixty others, each of which draws a box just as convincingly, and **§B2's premise is that a
border delineates an interactive region** — the whole design rests on it. If a reply can draw a
border, every border on the screen becomes a claim the user can no longer check.

A refused glyph is **marked, not dropped**: `<U+22EF>`, following
`marlowe_contract::text::sanitize`'s house style. A silently dropped glyph and a clean line are the
same line to the person deciding whether the harness wrote it. As in that module, **the marker is
not provenance** — a reply can contain the literal text `<U+22EF>` — and that asymmetry is the safe
direction.

### 3.1 What this costs, named rather than absorbed

A reply drawing a directory tree with `├──` renders `<U+251C><U+2500><U+2500>`. That is ugly, and it
is the intended behaviour: the alternative is quietly rewriting the model's characters into ASCII
look-alikes, which is a mangle the reader cannot detect. **Markdown tables are the common case and
are unaffected**, because §4 lays them out with no rules at all — the frequent thing never needs the
refused vocabulary.

### 3.2 Asserted on the drawn buffer, with a control on each side

`tests/markdown_forgery.rs`, every assertion on a `ratatui::Buffer`:

* a forged §B6 tool line, tried four ways — bare, inside a fence, inside `**`, inside a quote
* a forged §B9 approval region drawn in box characters
* a forged `─ compacted · 47 turns → summary ─`, and the markdown `---` that a renderer reaching
  for `─` would draw
* a forged `▸ thought for 4210 characters   ↵`
* **the other half**: every glyph in `chrome::MARKERS` must actually appear in a drawn frame, or the
  reservation is guarding a glyph nobody uses. That is the fourteenth-instance shape — *a guard is a
  claim, and a claim needs something checking its subject is still there* — applied to a glyph
  rather than to a file path.
* the **scope** control: harness notices are *not* put through the reservation, and a test fires if
  somebody later routes them through it for symmetry.

Each forgery test also asserts that the surrounding text landed and that the `<U+…>` marker is
visible, so "the glyph is absent" is a statement about the glyph rather than about an empty pane.

### 3.3 Two things the layout closes without needing a rule

* **Model prose reaches no cell outside the conversation region**, asserted by diffing a frame with
  a short reply against one with a two-screen reply. The status band, the approval overlay and the
  message field carry the harness's claims about what is happening, and they are unreachable.
* **`Entry::User` is still rendered flat.** The user typed it; showing their `**` back to them as
  bold would be rewriting their own words, and it keeps the interpreted surface to model-authored
  text alone.

---

## 4. Two constructs that had to be drawn differently from the obvious way

**Horizontal rules are `·`, not `─`.** The compaction marker is `─ compacted · 47 turns → summary ─`
in accent, and a model-requested rule in the same glyph is one `·` away from forging it. `─` is
reserved anyway, so this is both the glyph and the reason it is not the other one.

**Tables are columns with no rules.** A table drawn with `┌─┬─┐` is a border the model asked for,
inside the conversation, with a label position at its top left — the exact shape of a §B2 region. A
bold header and aligned columns carry the same information and borrow none of it. Cells wrap inside
their own column; the widest column is shrunk first, because proportional scaling rounds every
column into being slightly wrong while narrow columns survive intact. **When it cannot fit even at
the minimum, the source is shown instead of a squashed grid** — §B11's *a broken grid is worse than
an honest refusal*, one scale down.

**Code is hard-wrapped, never re-flowed.** Word-wrapping a code line moves tokens across lines and
changes what the reader believes the program says.

---

## 5. Links always show their target

A link is the one markdown construct that lets an author make text `X` point somewhere the reader
cannot see. In a terminal there is nothing to click, so hiding the target buys nothing and costs the
reader the only fact that matters about it. `[the docs](http://evil.example)` renders as
`the docs (http://evil.example)`, the target in weight 2, always.

---

## 6. Inline LaTeX: where the line is, and why it is drawn there

**You cannot render LaTeX in a character grid.** There is no vinculum, no radical that spans, no
stacked limits, no matrix. What a terminal can do is Greek, sub- and superscripts, the common
operators and relations, and simple fractions — which covers most of the maths in a conversational
reply.

`latex.rs` answers one question per expression: **can the whole of it be represented?** If yes it
returns the Unicode; if any single token cannot, it returns `None` and the caller prints the source,
delimiters included, styled as verbatim text.

**All-or-nothing is the whole design.** `\int_0^\infty e^{-x}dx` with the `\infty` quietly dropped is
`∫₀ e⁻ˣdx` — a *different integral* that looks entirely plausible. A wrong formula that looks right
is worse than a raw one that looks raw, because the reader of the raw one knows to go and check.
This is §B11's instinct in a new place.

Rendered: `\alpha \times \beta^2` → `α × β²`; `E = mc^2` → `E = mc²`; `\frac{1}{2}` → `½`;
`\frac{a+b}{c}` → `(a+b)/c`; `\sqrt{x+1}` → `√(x+1)`; `\mathbb{R}^n` → `ℝⁿ`; `O(n \log n)` →
`O(n log n)`.

Refused, each deliberately rather than unfinished:

| construct | why |
|---|---|
| `\hat`, `\bar`, `\vec`, `\tilde`, `\dot` | combining marks occupy zero columns, so the wrap arithmetic and the eye would disagree |
| `\begin{…}`, `&`, `\\` | matrices and alignments are two-dimensional; there is no honest one-line form |
| `\sqrt[3]{x}` | an index on the radical has no inline form. `\sqrt{x}` has one and is accepted |
| any `\command` not in the table | an unknown command is an unknown meaning. Silence is not translation |
| `^q`, `_b` | Unicode has no such glyph. Refusing is the only alternative to inventing one |

Three details worth recording:

1. **Spacing is set, not copied.** Anything unambiguously binary — relations, arrows, `× ÷ ± ∓ ⊕ ⊗ ∘`
   — gets one space either side, because `α × β²` is scannable and `α×β²` is not. `+` and `-` are
   excluded: they are also unary, and `- x` reads as a subtraction with a missing left operand.
   *This was found by looking at the rendered pane, not by reasoning about the parser.*
2. **The whitespace that terminates a command name is syntax and is consumed** (`\alpha x` → `αx`),
   except after an operator name, where LaTeX itself sets a thin space (`\log n` → `log n`).
3. **`$` is the dollar sign more often than it is a delimiter**, and this is the module's one
   heuristic. *"it costs $5 and $10"* contains a well-formed `$…$` span whose content is `5 and `,
   and translating it yields `5and` — a silent, confident corruption of ordinary prose. Four rules
   guard it, each earning its place against a real sentence: no leading or trailing space in the
   content; no letter run of three or more outside a command; at least one maths signal, or a single
   letter; no newline and a bounded length. The cost is that a lone `$5$` stays as source, which is
   the right direction — a reader seeing `$5$` has lost nothing.

### 6.1 Two safety properties, enforced on the output rather than asserted about the table

**Every emitted codepoint passes `marlowe_contract::text::is_renderable`, and none is a chrome
glyph.** The second matters more than it looks: `chrome::prepare_model_text` runs over the raw reply
*before* parsing, so anything the maths renderer produces afterwards has already passed the chrome
reservation. A table entry mapping some command to `─` would be a hole straight through §2's premise,
opened by a maths table nobody would think to audit for borders.

Both are checked on the **result of every call**, not only in a test over the table — the table is
one way to reach the output and a future `\command` handler would be another. `\cdots` is `···`
rather than U+22EF for exactly this reason, and `render("a─b")` returns `None`.

---

## 7. `display_sanitiser.rs`'s recorded trade is now spent, and this ADR is the reason

That file records that the TUI deliberately does **not** sanitise, that ratatui discarding control
characters on their way into a `Buffer` is the enforcing layer, and that the file is *a
characterisation test of a dependency, not a guard*. It names the two things that would change the
trade. **Markdown is both.**

* *"The marker substitution would change wrapping and column arithmetic that §B13's flicker rows
  measure to the cell."* True while wrapping happened on the raw string. `render_prose` substitutes
  **before** parsing and wrapping, so the arithmetic sees the final text — that objection is answered
  by the order of operations rather than argued away.
* ratatui's filtering is still true and still the enforcing layer for `ESC`. It says **nothing**
  about U+2028, the BiDi overrides, or the zero-width block, and each of those defeats a defence
  markdown rendering newly depends on: U+2028 is a line break `str::lines()` does not see, so the
  block parser splits differently from the eye; U+202E reverses the displayed order of a line, so an
  indent — the entire forgery defence — becomes a property the model can move; a zero-width character
  occupies no column while carrying bytes, so wrapped width and displayed width diverge.

So `chrome::prepare_model_text` runs `marlowe_contract::text::sanitize_prose` first: **one predicate,
shared with the contract-value check**, rather than a second idea of what a safe character is.
`display_sanitiser.rs` remains a characterisation test of ratatui and is still correct about what it
covers.

---

## 8. Purity, and what it cost

**There is no cache and no memoisation keyed on anything.** K4 makes zero repaint flicker a kill
criterion and `b13_rendering.rs` proves it by rendering frame N and frame N+1 and diffing the buffers
cell by cell — which works only because rendering is a pure function of `(state, now_ms)`. The
scrollbar depends on the same purity: `render::transcript_lines` is the only thing that knows how
many wrapped lines a transcript produced, and it hands that number back to `App::scroll_max`. A
cached count and a freshly wrapped one would be two answers to one question.

`Ctx` holds one `Cell<usize>` (§8.2). It is constructed inside `render_prose`, so the function is
still pure in its arguments; `markdown_render.rs::a_second_render_of_the_same_state_changes_not_one_cell`
asserts it at all five sizes, and `the_scroll_extent_agrees_with_what_markdown_actually_drew` asserts
the scrollbar is sized from the count that was drawn.

### 8.1 The measured cost

`tests/markdown_cost.rs`, release, this machine, with the flat path measured **in the same process on
the same bytes** as the control:

| case | flat (before) | markdown | ceiling |
|---|---|---|---|
| 32 KB — a typical session's first frame | — | **3.4 ms** | 8 ms |
| 400 KB at 66 columns — a full context window | 3.4 ms | **29 ms** | 50 ms |
| 400 KB at 136 columns | 3.2 ms | **25 ms** | 50 ms |
| 140 KB of adversarial punctuation | — | **24 ms** | 50 ms |

**ADR-047 costs roughly 8× the flat renderer.** Two things bought most of it back and are worth
keeping: adjacent same-style text coalesces into one `Span` per run rather than one per word (a
`String` allocation per word, per frame, for the whole transcript), and a paragraph containing none
of `* _ \` [ < $ ~ \` skips the inline machinery entirely.

**The ceilings are profile-aware, and each is labelled with what it can establish.** K4 is a property
of the release binary; a debug build measures 7–8× slower on the identical input. Asserting the
release ceiling in a debug run would fail on a correct build. So the release ceilings are evidence
about K4, and the debug ceilings (60 ms / 500 ms) are evidence about the *algorithm* — they exist so
the workspace suite, which runs in debug, still fails if §8.2's quadratic comes back.

### 8.2 A scan budget, because a model can choose its punctuation

**Found by the cost test, not by reading the parser.** Inline markdown scans forward for a closing
delimiter, and an opener with no closer scans to the end of the block. That is cheap in prose and
quadratic in a reply that is nothing but openers: 140 KB of `[[[[…`, backtick runs and `***nested `
took **144 ms in one frame** — past K4's entire first-frame budget — from nothing but the model's
choice of characters.

One budget, shared by every scanning construct, charged per character examined, sized at 16× the
reply's length plus a floor. When it runs out **the rest of the reply renders as literal text**,
which is what the pane did before ADR-047 — the degraded state is the previous product rather than a
broken one. Ordinary markdown spends roughly its own length and never approaches it.

Two further bounds in the same family: an unclosed backtick run is skipped **whole** rather than
retried one character in (retrying re-counts the run, which is the quadratic in miniature), and block
nesting stops at six levels, because `> `×10 000 is one line of text and ten thousand levels of
recursion — a stack overflow rather than a slow frame.

With the budget: 24 ms release, and the mutation `md_budget` restores 1 415 ms in debug against a
500 ms ceiling.

### 8.3 The architectural finding this leaves open

`transcript_lines` lays out the **entire** transcript on every frame, because the scrollbar needs the
true line count. That was 3.4 ms and is now 29 ms at the pessimistic end, and it is paid per frame
rather than per turn — so a very long session tightens the ceiling on animation. The daemon's
projection appends without bound (`project.rs`: *"the transcript grows"*), so the pessimistic end is
reachable.

**The fix is windowed layout with a cached total, and it is a change to `transcript_lines`'
contract** — scroll behaviour, the scrollbar and the pager all read that number. It is recorded in
`STATE.md` rather than done here.

---

## 9. `Y` still copies source markdown

§B10: *"`Y` copies the whole transcript as markdown."* Markdown was already the interchange format,
and rendering it must not change what comes out. `clipboard::transcript_markdown` builds from
`Entry` and never from the screen, so this is structural — but it is asserted rather than assumed,
with the two halves as controls for each other: **the pane showing no `**` proves the renderer ran,
and the clipboard showing `**` proves it did not reach the copy.** Either assertion alone passes on a
build where the feature does nothing. The mutation `md_copy_source` fails it.

---

## 10. What was rejected

* **Syntax highlighting.** §2. Not a near miss — it would make the screen lie about state.
* **A background or reverse-video code fence.** §2.1.
* **A markdown crate.** `pulldown-cmark` would be a correct parser and the wrong dependency here:
  the whole security argument is about controlling exactly which glyphs and which structures can
  reach the grid, and a general parser's output would have to be filtered afterwards — the filtering
  posture this project rejects on principle. The subset is ~700 lines and every construct in it is a
  decision recorded above.
* **Rendering `Entry::User` as markdown.** §3.3.
* **Rendering harness notices as markdown.** They are a closed vocabulary (ADR-030) rendered from
  typed data; there is no markup in them, so interpreting it buys nothing and risks an `_` in a flag
  name becoming emphasis in the one text the harness itself authored. They also skip the chrome
  reservation, because the harness is allowed to draw chrome and the model is not.
* **Best-effort LaTeX.** §6.
* **Combining-mark accents.** §6 — zero-width glyphs break the column arithmetic the flicker rows
  measure to the cell.

---

## 11. How this was verified

* **Ten mutations, one at a time, each caught by a named test.** `scratchpad/mutate2.py` entries
  `md_render`, `md_chrome`, `md_ranges`, `md_rule`, `md_reversed`, `md_budget`, `md_latex_partial`,
  `md_latex_output`, `md_currency`, `md_copy_source`. `mutate2.py` refuses to run unless its pattern
  matches exactly once, so a mutation that silently failed to apply cannot report a clean bill of
  health.
* **Every acceptance assertion reads a drawn `ratatui::Buffer`**, not an intermediate `Vec<Span>`.
* **The pane was looked at**, at 120×30 and 160×45 — `snapshot.rs::a_markdown_reply_can_be_read`.
  Two of the decisions above (binary-operator spacing, full-width rules) came from that and from
  nothing else.

### 11.1 Verified in the RUNNING binary, not only in a headless buffer

CLAUDE.md logs an instance of a green test asserting on a request body built **inside the test
process** while the deployed daemon served a binary from before the change. A `TestBackend` is the
same shape of evidence, so the frame was also taken from `target/release/marlowe.exe` itself.

`marlowe --tui --scripted --timing-probe` renders one real frame and exits, and the emitted escape
stream can be captured. To get markdown into it, one reply was **temporarily** added to the stub's
opening transcript, the release binary rebuilt, the frame captured, and the stub reverted. In the
captured stream, at 120×30, `TERM=xterm-256color`:

| observed in the running process | |
|---|---|
| `ESC[38;5;…` and `ESC[1m` present | real 256-colour and bold SGR are emitted, not merely styled |
| `Margin is α × β²; the tail $\int_0^\infty e^{-x}dx$ is left as written.` | §6, both halves, on one line |
| `written. See the note (https://example.invalid/j).` | §5 — the target is on screen |
| `·································` | §4 — the rule is `·`, not `─` |
| `And a forged line: <U+22EF> bash rm -rf ./build   exit 0` | §3 — the forgery refused, and **marked visibly** |
| `  ⋯ run       deep-research      spawned` | …**on the same screen** as a real §B6 tool line carrying the real `⋯`. That is the discrimination, live |
| `Running. About twenty minutes and roughly $3 — I'll ping you.` | §6's currency guard, on a scripted reply nobody wrote for this test |
| `time_to_first_frame_ms  1` | K4's 150 ms, from the shipped binary, with the parser in the path |

**What this did NOT establish.** No interactive session: this environment has no PTY, so scrolling,
resizing a live window, and `y`/`Y` under a real terminal were not exercised. **Italic was not in
that viewport** — `ESC[3m` does not appear in the captured stream, because `*eleven percent*` was
above the fold. It is asserted on the grid by `markdown_render.rs`, but whether a given terminal
*font* renders italic at all is a property no test in this repository can see. §B13's by-eye row
covers the accent; nothing covers emphasis, and on a font without an italic face emphasis and body
will look identical. **Look at a markdown reply in a real terminal before treating that as closed.**

---

## 12. Known limits

* **Column arithmetic counts characters, not display columns.** That is the existing behaviour of
  `render::wrap` and of every chrome line in the crate; the maths substitutions stay inside BMP
  symbols that are single-width in the pinned font (§B17 pins Cascadia Code). A wide glyph would put
  the wrap and the screen out of agreement — which is one more reason the maths table is a curated
  list rather than a general transliteration.
* **Reference-style links** (`[text][ref]`) and **setext headings** are not implemented and render
  literally.
* **Indented (four-space) code blocks** are not implemented; fenced blocks are. An indented block
  renders as a paragraph.
* **A hard line break** needs two trailing spaces or a trailing backslash; a lone newline joins, per
  CommonMark. `Y` still yields the source, so nothing is lost by the join.
* §8.3.
