# ADR-041 · One quarantined reader per group, not per page — and three budget limits that were bugs in effect

**Status:** Accepted, shipped (M2, tools/parallelism session)
**Amends:** ADR-039 (the routing, not the containment), `Budget`'s slicing, and the quarantined read's `OutputContract`.
**Does not amend:** brief §8.2, the five layers, trust-class propagation, adjudication, egress policy. The containment is unchanged.

## Context

ADR-039 routed every untrusted tool result through a quarantined child. It condensed **one page per
child**, which was the right first shape and the wrong steady-state cost.

Once `web` could fetch concurrently (ADR-040), the arithmetic stopped working. Thirty fetches
returned in ~300 ms and then cost:

- **30 child runs**, each a full model round trip, executed **serially**;
- **30 of the run's 8 subagent slots** — so the run paused at eight and never saw the rest;
- a token slice that **decayed geometrically**, because `BudgetShare::Small` takes ⅛ of
  *remaining*: read 1 got ⅛ of the budget, read 8 held about **0.3% of the original**.

The third of those is the one that matters most, because it is silent. A reader too poor to
summarise does not error — it returns something worse, and a degraded description of an
attacker-controlled page is precisely the output nobody can audit.

## Decision

### 1. A group of untrusted results is read by ONE child

`Engine::condense_batch` collects a tool group's untrusted results and reads them in a single
quarantined child. **Nothing about the isolation was ever per-page, so nothing about the isolation
changed:**

| Property | Before | After |
|---|---|---|
| Reader's tool set | `ExposedSet::empty()` (load-time error otherwise) | unchanged |
| Reader's egress | `EgressPolicy::DenyAll` | unchanged |
| Output validation | `OutputContract::validate`, capped, C0 refused | unchanged |
| Rendering | headers at column 0, values indented | unchanged |
| Failure | fails closed, page is never the fallback | unchanged |
| **Cost for N pages** | **N spawns, N model calls, N subagents** | **1 spawn, 1 model call, 1 subagent** |

### 2. The contract gained one field per source

Was a single `findings` capped at 2,000 characters. Now `about` (600) plus `source_1..source_N`
at 1,500 each. A fixed 2,000 was already tight for one research paper and would have been
meaningless split across several.

**Source labels are assigned by the harness, positionally, and never derived from content, from the
URL, or from anything the child model wrote.** A document that could name its own slot could claim
to be another, and the parent attributes findings by slot.

### 3. Contamination is bounded, not unlimited

`MAX_SOURCES_PER_READER = 6`. A group larger than that is split across readers.

### 4. Condensed documents are cached by content hash

Keyed on the **content**, not the URL, so two URLs serving identical bytes collapse to one read.
Research corpora repeat constantly. A cache hit costs **zero** model calls.

Caching the *condensed* form rather than the page is deliberate: the stored value has already
passed `OutputContract::validate`, so a hit cannot reintroduce anything the contract would have
refused. The key is the content itself, so a hit is only obtainable by already possessing the
identical bytes — there is no probing oracle.

### 5. `Budget::slice_for_quarantined_read`

A share of the **original** budget (¼), clamped by what remains — not a geometric slice of the
remainder. And **depth is not consumed**, because a reader holding an empty tool set structurally
cannot spawn. Previously `slice_for` refused at `depth == 0`, so a run four levels deep could fetch
a page and then never read it, receiving *"no budget remained to condense it"* when the real cause
was distance from the root.

## The trade, stated rather than buried

One context now holds several attacker-controlled documents, so document A's text can influence how
the reader describes document B. **This is a fidelity risk, not an escalation one.** The reader has
no tools and no egress; the worst available outcome is a wrong summary, which was already reachable
for a document's own summary. The trifecta is broken in exactly the same place.

`MAX_SOURCES_PER_READER` bounds it: one hostile page can affect at most six descriptions, not a
whole corpus.

## Two bugs found while building this, both of the standing family

**1. A zero budget dimension means "already exhausted", not "may not use."** The reader was given
`tool_calls: 0` and `subagents: 0` to express *it has no tools*. `Budget::exhausted` compares
`spent >= budget`, so `0 >= 0` fired on the first iteration: the reader paused before its first
model call, returned nothing, and every page came back *"could not be condensed"* — a quarantine
that had silently stopped reading anything at all. The capability is withheld structurally
(`ExposedSet::empty()`, `depth: 0`) and the counters are 1.

**2. Interpolating a field value re-opened ADR-039's forgery hole.** A draft of `condense_batch`
pulled the field's raw value out of the map and formatted it into the note directly. `render` is
what keeps a header at column 0 and **indents every line a value contributes**; interpolating the
value put the check and the thing it protects back on opposite sides of a format string — the exact
shape of the original bug. Caught by `egress_grant.rs` asserting on the rendered form.
`a_value_cannot_forge_a_source_header` now asserts it directly.

## Tests

`crates/marlowe-loop/tests/quarantine_batch.rs`, seven, all asserting on the parent's actual window
or on counted model calls rather than on a constant:

- four fetches are read by **exactly one** child;
- page bytes are absent from the parent, **with a negative control** that some view did contain them;
- each source appears under its own harness-assigned label;
- a group above the cap splits across readers, but still uses far fewer than one per source;
- five byte-identical documents are read **once** and still yield five results;
- a value containing `source_2:` is indented and cannot read back as a header;
- with no budget for a reader, the page is **not** the fallback.

## Consequence for existing tests

Three scripted-driver tests encoded the **old cost model** — one child reply per fetch. They now
encode the new one, with the reason stated inline. The properties they assert (egress asks per
fetch; the parent's floor stays clean; batch ordering) are untouched; only the number of scripted
child replies changed. `ScriptedTools` returns byte-identical bodies, so most of their condensations
are now cache hits.

## What this does NOT solve

The interactive path still condenses, so a research pass through the agent still pays one model call
per group of fetches. Removing that entirely is Phase 4 of the plan this ADR is step 1–3 of: extracted
documents go to a content-addressed store, the agent receives references plus harness-computed
metadata containing **zero attacker bytes**, and one quarantined synthesis pass reads the store at the
end. That is strictly *more* contained than this — the agent would never read attacker-authored prose
at all — and it wants `ADR-037-deep-research-shape.md` read first and its own ADR.
