# ADR-048 — The persona may use Markdown, because the interface now renders it

Date: 2026-08-22 · Status: **Accepted** · Supersedes the no-markdown rule in `persona/v2.md`

## Context

`persona/v2.md` said, in its `<voice>` section:

> Your output is read in a terminal. The interface carries the structure, so your prose carries
> none.
>
> Never use markdown — no asterisks, no headers, no bold, no bullet symbols.

and in `<self_check>`: *"Is there markdown in this? Strip it."*

**That rule was deliberate and it was not a leftover from voice.** `04-addendum-persona.md` was
amended on 2026-08-10 precisely to say so: the adopted prompt derived the rule from *"You are a
voice-first system … spoken aloud through TTS"*, and the amendment records that **"the rule is
right and the reason was wrong for this system"** — Marlowe is terminal-native, there is no TTS
path, and a persona claiming to be spoken aloud would have been a false claim about the product.
The rule was kept on a **terminal** justification: *the interface carries the structure*.

## What changed

ADR-047 made that justification false. The conversation pane now renders Markdown — headings,
lists, tables, fenced code, emphasis — and renders LaTeX maths into Unicode. The interface carries
*some* of the structure and now expects the prose to carry the rest.

**And a direct contradiction had already shipped.** `IDENTITY_FACTS` in `marlowe-daemon` was given
a sentence telling the model *"The terminal renders your replies as Markdown"* while the persona in
the same system prompt said *"Never use markdown … Strip it."* Two instructions, opposite, in one
request. That was introduced with ADR-047's disclosure sentence and went unnoticed for two commits.

## Decision

**Formatting is earned, never decorative.** Prose stays the default and the register does not
change: the structure belongs in the sentences. Markdown is permitted where the content is
genuinely shaped that way — a table for rows and columns, a fence for code, a list for a list — and
refused where it is ornament: a heading over three sentences, bold on a merely-important phrase, a
bullet per sentence. Those make a short answer look like a report, which is the failure the
original rule was protecting against and which is still the failure.

**Maths is the one place formatting is not decoration.** `$inline$` and `$$display$$` are typeset,
and notation the renderer cannot represent exactly is shown as raw source rather than approximated
— so the persona says to prefer notation that survives.

## What this does NOT decide

**The classic CLI (`--classic`) does not render Markdown**, and the persona has no surface selector
— `04-addendum-persona.md` notes that absence in its own amendment. So a reply written for the TUI
is read as source on the linear surface.

That is tolerable and it is not free: `**bold**` and `$\alpha$` are legible as source, and `Y`
copies source Markdown anyway, so the interchange format was already Markdown. **What makes it
tolerable is the "earned, not decorative" rule** — a reply that only uses structure the content
actually has degrades to readable plain text, while one full of ornamental headings does not. A
surface selector remains the correct long-term answer and is still not built.

## Consequence for the §13 boundary

`persona/vN.md` is a brief §13 protected path and this edit is exactly the kind that boundary
exists to require a decision for. **The hook's matcher is correct** — piped a persona edit, it
returns `ask` with the right reason. **No approval prompt surfaced during the actual edit**, so in
this session's permission mode the boundary did not gate the change.

That is the gap `CLAUDE.md` names and predicts: *"A pipe test proves the matcher recognises a
string. It does not prove the hook fires when the agent edits the file."* The persona row should be
read as **matcher-verified, not gate-verified**, and this ADR is the entry the boundary asks for
in place of the prompt that did not appear.
