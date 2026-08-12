# ADR-039 · Untrusted tool results are condensed by a quarantined child before they reach the run that holds tools

**Status:** Accepted, shipped, live-verified (M2 Session E)
**Supersedes nothing. Amends:** the practical reading of ADR-023's latch, and `OutputContract`'s shape.

## Context

Brief §8.2 has two sentences. The first — *the component that reads untrusted content has
`reads_untrusted: true` and an empty tool set* — has been a load-time error since M2 Session A:
`reads_untrusted && !exposed_tools.is_empty()` refuses to construct.

The second — ***"the component with tool access receives sanitized structured input, never raw
untrusted text"*** — was **violated in the shipped product** from the moment `web` landed in C2f.
`FileSystemTools::web` returned page bytes at `UntrustedContent` and the loop pushed them straight
into the context of a run holding `bash`, `edit`, `find` and `web`. Reader and doer were collapsed,
which §8.2 names as the configuration that makes a deployment exploitable.

Two things followed from it, and only the first was noticed:

1. **Layer 3 was doing layer 1's job.** ADR-023's latch dropped the run's floor to
   `UntrustedContent`, so every model-composed Target was refused for the rest of the run. Reported
   by the human as *"after fetching web data all his tools get turned off. seems dumb."* The read was
   right; the cause was the missing control, not a misbehaving guard.
2. **A declared mitigation was inert.** `web`'s manifest carries `inline_threshold_bytes: 0` with the
   comment *"Never inlined. §8.2: raw untrusted bytes do not reach attention."* **Nothing reads that
   field.** `marlowe-exec`'s `body_for` decides inline-vs-reference against a global
   `MAX_INLINE_BYTES = 8_192`. Its only reader is a test asserting the field equals 0 — the
   declaration, not the behaviour — which passed on a build where every page under 8 KB reached
   attention verbatim.

## The gate, and why it was nearly a refusal

The crossing this ADR relies on already existed: `Engine::spawn` pushes a child's result into the
parent at `TrustClass::AgentInferred`. That is **the one place in the system where content crosses
from untrusted to trusted by declaration rather than by lineage**, and `OutputContract::validate` is
the only thing standing in it.

`validate` checked three things: no unknown field names, no missing field names, and an aggregate
`String::len` cap. **It constrained no value.** A child talked into emitting an attacker's text filled
the declared field with it and passed.

Worse: the `push` sits **outside** the outcome match, so **all five branches crossed at
`AgentInferred`** while `validate` governed one. `Escalated { question }` interpolated a child's
model-authored string — composed after it read the page — verbatim into the parent.

**Routing `web` through a child before fixing that would have shipped the exception before the thing
that justifies it**, and would have been worse than the honest hole: an unsound crossing exercised on
every fetch instead of never.

## Decision

Build the return path first, then the routing.

1. **`OutputContract` takes typed fields.** `FieldSpec { name, ty, max_chars }` with
   `FieldType::{Text, Line}`. `validate` now checks names, **then values**, then the aggregate:
   per-field character caps, and a refusal of every C0 control except `\n`/`\t`, plus `DEL` and C1.
   That last is not tidiness — `ESC` is `U+001B`, and refusing C0 is what stops a fetched page
   writing terminal escape sequences through a child and onto a screen. Nothing else on the path
   would catch it.
   **No `ContractViolation` variant interpolates a value.** A violation is written into the parent's
   context, so a message quoting the offending text would be the laundering path the validation
   exists to close.
2. **Only a validated result carries content across.** Escalated/Failed/Cancelled/Paused render fixed
   harness-authored strings; the detail goes to the journal, which is not model-reachable
   (invariant 8). Debuggability keeps what it needs; the parent's window gets nothing it cannot
   account for.
3. **`CondensedResult::render` is unforgeable.** It was `"{k}: {v}"` joined by newlines, and the
   parent only ever sees the flattened string — so a value containing `"\nanswer: …"` produced a line
   indistinguishable from a real field header. Field *names* were whitelisted; the rendered form was
   not, putting the check and the thing it protects on opposite sides of a format string. **A field
   header is now the only thing at column 0, and every line a value contributes is indented.**
4. **`Engine::condense_untrusted`.** The harness fetches — egress adjudicated, host approved by a
   human, unchanged. A child with `CapabilityProfile::quarantined_reader()` (empty tool set,
   `DenyAll` egress, budget sliced `Small` from the parent) receives the bytes as an
   `UntrustedContent` block in its own window and returns one capped `Text` field. The parent
   receives the rendered result; **its floor does not move.**

### Two properties of the trigger, both load-bearing

**It is keyed on the trust class, not the tool name.** The condition is
`marlowe_permission::blocks_composed_targets(outcome.trust)` — the same function the adjudicator
enforces on. The class that costs a run its composed targets is exactly the class that must be
condensed before it is read, and a future tool returning untrusted content is covered without anyone
remembering to extend a list.

**There is no carve-out for failed calls.** The first draft exempted them, reasoning that a failure
body is a harness-authored error string at `AgentObserved` on every path that constructs one. True
today, and an assumption about every executor that will ever exist. The cost of dropping the
exemption is a wasted child on a failed fetch; the benefit is that no branch remains for a future
executor to fall through.

**Every failure path fails closed.** Out of budget, contract violation, or a dead child each push a
harness note naming what happened — and never the page.

## Consequences

- **§8.2's second sentence holds.** Verified live, on the running binary: the child's window carries
  the raw `<!doctype html>` and offers **zero tools**; the parent's carries a 203-character summary
  and all nine. The raw HTML appears once in the whole outbound dump.
- **Composed targets survive a fetch.** The ergonomics complaint is closed **by layer 1, not by
  relaxing layer 3.** `blocks_composed_targets` is untouched; a run that reaches `UntrustedContent`
  still loses composed targets. What changed is that fetching no longer takes a run there.
- **No tool result can taint a parent any more.** The only remaining source of `UntrustedContent` in a
  run's own window is **injected memory**, which `daemon.rs` pushes at `retrieved.floor`. Layer 3
  remains reachable and non-vacuous — but its subject changed, and four loop tests had to move to that
  taint source. One went **green and vacuous** in the process, when its four trust classes collapsed
  onto a single floor; it was caught by asking what the table would read if it were measuring nothing.
- **The quarantined child's floor drop must not be announced.** The child shares the parent's sink, so
  the first build printed *"read untrusted · composed targets blocked for this run"* on every fetch —
  naming a child with no tools to block, while the parent it named was unrestricted. **C2f's defect,
  re-opened by the component built to fix it.** `reads_untrusted` profiles are exempt from the
  announcement; the journal still records the latch, and only the screen is gated.
- **A user cannot obtain a raw page.** "Show me this page's HTML" returns a summary. A real functional
  loss, accepted, and unmeasured.
- **The channel is bounded, not zero.** A summary of a page is attacker-influenced prose however it is
  typed. What the constraints buy is that it is **capped, sanitized, and structurally unable to forge
  the record it arrives in** — and §5.6 governs the rest: it may inform **analysis**, and layer 3
  still refuses to let it choose a **target**.

## Not done

- **`inline_threshold_bytes` is still read by nothing**, and `web_is_inert_and_never_inlines` still
  asserts the declaration. Layer 1 makes it moot for `web`; the dead field and its green test are
  unclaimed work.
- **`FieldType::Line` has no production caller**, because the completion path files a child's entire
  reply into every declared field, so a single-line field could never validate. It is kept for an
  emitter that names its own fields, and the reason is recorded at the one production contract.
