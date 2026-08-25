# ADR-055 — A run's own prose streams to its window; the quarantined reader's still does not

**Status:** ACCEPTED. Written **before** the first output line was rendered, which is the only order
in which this entry means anything — an entry written afterwards is a rationalisation of a shipped
byte.
**Binding on:** audit finding E4; `M3-DESIGN.md` §6.7 and §3.6; Addendum B §B2, §B6, §B13.
**Depends on:** ADR-047 (the display pipeline), ADR-041 (what a condensed read actually returns),
`marlowe_contract::text` (the display predicate).
**Amends:** the blanket reading of E4 recorded in `STATE.md` (2026-08-24, "M3 DESIGN DIRECTION").
**Does not amend:** `QuarantinedSink`. Nothing below relaxes it.

---

## 1. What E4 says, and the sentence that is about to be crossed

E4, as filed:

> **The quarantined child shares the parent's `TurnSink`, streaming unvalidated reader output to the
> terminal — HIGH.**
> *Fix:* suppress `TextDelta`/`ReasoningDelta`/`SpeechRetracted` when `reads_untrusted`; **move the
> character check to the sink boundary.**

**Only the first half of that fix was built.** `QuarantinedSink` suppresses the three prose events.
The second clause — *move the character check to the sink boundary* — was never done, and nothing in
the suite noticed, because after the suppression there was no path left that anyone was looking at.

The generalised form the project has been quoting is wider than the finding:

> *"Prose composed inside a window holding attacker-controlled pages must not stream to a terminal."*

**A run window streams a run's output. That sentence, read as written, forbids it.** So it is crossed
here, deliberately, once, in writing.

## 2. The distinction the blanket reading loses

There are two different things called "a window showing an agent", and E4 covers exactly one of them.

| | whose prose | does its window hold attacker pages | position |
|---|---|---|---|
| **A quarantined reader** | the child's | **yes, raw, by construction** | **unchanged — suppressed** |
| **An ordinary run** | the run's own | no raw page ever reaches it (ADR-039/041) | **streams, sanitised** |

An ordinary run's window holds **condensed results** — validated, capped, per-field, positionally
labelled. ADR-041 concedes in writing that those are *attacker-influenced prose*: a **fidelity** risk.
It does not concede that a raw page is in there, because layer 1 is what stops that, and layer 1 is
untouched by this entry.

**And the parent's prose already reaches a terminal today.** `nothing_the_quarantined_reader_says_reaches_the_surface`
has always carried the negative control that says so:

```rust
assert!(h.sink_text.contains(PARENT_SAYS),
        "the parent's own answer must still reach the surface");
```

A run window is therefore **not a new channel**. It is the existing channel — the one every reply the
user has ever read came down — rendered in a second window instead of the first. Refusing it in a
window while permitting it in the main pane would be a position about *window management*, not about
containment.

## 3. What the middle position said, and why it is kept for the reader and dropped for the run

`STATE.md` recorded a middle position:

> the window shows the agent's **activity** — running, elapsed, sources, tokens, the validated fields
> it returned — without its **prose**.

**That remains this project's position for the quarantined reader, and nothing here changes it.** The
argument against showing a reader's prose survives the sanitiser and is quoted here rather than
paraphrased, because it is the load-bearing half:

> the objection that survives the sanitiser is **attribution**, not characters — attacker-derived
> prose rendered in Marlowe's own reasoning voice, aimed at the human rather than the machine. Brief
> §8.1 is *"filtering does not work. Containment works."*

For an **ordinary run** that objection does not apply in the same form, because the prose is the
run's own answer to the user, arriving in the voice it has always arrived in, in the region the
product exists to show. The user is not being handed a page's words in Marlowe's voice; they are
being handed Marlowe's words about a page, which is what a condensed read is *for*.

## 4. The condition, and it is E4's own unbuilt half

Streaming is permitted **on the condition that the character check is at the display boundary** —
the clause E4 asked for and did not get.

Every byte that reaches a cell in a run window passes `chrome::prepare_model_text`, which is
`marlowe_contract::text::sanitize_prose` followed by `chrome::mark_reserved`. That is:

1. **The display predicate.** C0, DEL, C1, U+2028/2029, the BiDi overrides, the zero-width block, and
   the tag block U+E0000–U+E007F — the one family ratatui passes through, and the documented channel
   for smuggling an instruction past a human reader.
2. **The chrome reservation.** Box drawing and block elements, so a run's output cannot draw a border
   and cannot forge a §B6 tool line inside a window whose whole premise is that borders delineate
   regions the harness drew.

**The marker names the codepoint rather than swallowing it** (`<U+202E>`), because a silently dropped
glyph and a clean string are indistinguishable to the person who has to decide whether the line in
front of them came from the harness.

**Asserted on the rendered `Buffer`, not on the function that built it.** The check is worth nothing
if it is asserted where it is declared — that is family #16, and it is the failure this project has
logged most often. `window_sanitiser.rs` renders a frame and searches the output region's cells.

## 5. The test is MOVED, not deleted, and here is where each half went

`nothing_the_quarantined_reader_says_reaches_the_surface` **stays exactly where it is, unchanged, in
`marlowe-loop/tests/quarantine_batch.rs`.** It asserts the quarantine's suppression, which this entry
does not touch. Deleting it would be deleting layer 1's only test.

What moves is **E4's second clause** — the character check at the boundary where bytes reach a
screen. It had no test anywhere, because it had no implementation anywhere. It now has both, in
`marlowe-surface/tests/window_sanitiser.rs`, which names E4 in its header so the lineage is greppable
from either end.

| E4 clause | before | after |
|---|---|---|
| suppress the reader's prose | `QuarantinedSink` + `quarantine_batch.rs` | **unchanged** |
| character check at the sink boundary | **not built, not tested** | `window::draw` + `window_sanitiser.rs` |

**The audit table is updated in the same commit**, so `SECURITY-AUDIT.md`'s E4 row does not keep
claiming a one-line fix for a two-clause finding.

## 6. §3's escalation window is covered by this entry, and carries three further conditions

`M3-DESIGN.md` §3.6 calls the escalation window *"the highest-value display attack in the product"*,
and it is a harder case than a run window: the human is not reading, they are **choosing between
labelled options**. Sanitisation is necessary and is nowhere near sufficient. So the same permission
is granted with three additions, recorded here because §6.7 asked for one entry covering both:

1. **Option labels are harness-normalised** — plain text, length-capped, drawn in chrome the model
   cannot produce (§4 above is what makes "cannot produce" true rather than hoped for).
2. **TERMINATE is harness-rendered and the agent does not know it exists** — not in its exposed set,
   not in its `request_body`. §3.4. Asserted where the bytes go, not on a flag.
3. **Provenance is shown, not a caution.** *"This agent has read 14 external sources; this claim
   traces to `example.com`, fetched 40 minutes ago"* is checkable; *"if this seems tainted"* asks the
   user to detect a well-written lie.

None of the three is built in this session — the escalation window is §3's, and §10's step 5. They
are stated here because the permission is granted here, and a permission granted without its
conditions written down is how the conditions get discovered later by an auditor.

## 7. What this entry does NOT permit

Stated as a list, because the next person to read it will be looking for the edge.

* **It does not permit a quarantined reader's window.** §2's first row is unchanged. If that is
  wanted, it needs its own entry and it must argue past §3's attribution objection, which this one
  does not.
* **It does not permit raw tool results in a window.** What streams is `TurnEvent::TextDelta` and
  `ReasoningDelta` — model prose. A fetched page reaches a window only after `condense_batch`, the
  same as it reaches the main pane.
* **It does not permit a window to render prose that skipped the pipeline.** There is one draw path
  and it calls `prepare_model_text`. A second one would be two definitions of what may be displayed,
  which is the shape §4's whole argument depends on not existing.
* **It does not weaken ADR-023.** A window is a surface. Nothing rendered in one is an authority to
  compose a target, and the steer field is adjudicated as `/steer` is — see ADR-054.

## 8. Cost accepted

**A run window can be made to show ugly text.** A page that induces a summary full of reserved glyphs
renders as `<U+2500>` sequences. That is the intended behaviour and the same trade `chrome.rs`
already records: the alternative is quietly rewriting the model's characters into ASCII look-alikes,
which is a mangle the reader cannot detect.

**Attacker-influenced prose reaches a human's eyes.** It always did. What this entry buys is that it
arrives bounded, sanitised, unable to forge the chrome around it, and unable to authorise anything —
and what it costs is that "no prose in a window" is no longer a sentence anyone can quote as the
project's position, because it never described the product accurately anyway.
