# ADR-042 · The document store, and why a reference carrying only counts needs no quarantine

**Status:** Shipped (M2). Store, reference, `web`-returns-a-ref, and `read`-by-ref are all built
and asserted.
**Implements:** ARCHITECTURE §2.2, which has specified this store since M2 and had no implementation.
**Depends on:** ADR-040 (extraction), ADR-041 (batched quarantined reads).
**Does not amend:** brief §8.2, the five layers, or any trust-class rule.

## Context

ARCHITECTURE §2.2 has said this for two milestones:

> *"This store does double duty: it is the reference target that keeps untrusted bytes out of
> attention (§2.8), and it is the eviction unit that keeps the log small."*

It was never built. `marlowe-exec`'s `body_for` still carried the note *"content-addressed by the
store at M2 D; until then the hash names the bytes"* — so a `ToolBody::Reference` was a hash nobody
could dereference, and the loop worked around it by shipping a head-and-tail preview instead.

ADR-041 cut the cost of reading untrusted content from N model calls to one per group. That is the
floor for *condensing*, and condensing exists because **prose is what crosses**.

## The observation this ADR rests on

**A tool result containing zero attacker-authored bytes does not need quarantine at all.**

Layer 1 launders attacker prose by having a model with no tools re-author it. If nothing
attacker-authored is crossing, there is nothing to launder — and no model call to pay for.

A `DocumentRef` is:

```rust
pub struct DocumentRef {
    pub hash: String,          // content address
    pub url: String,           // supplied by the caller, echoed back
    pub format: Format,        // harness-detected
    pub wire_bytes: usize,
    pub chars: usize,
    pub links: usize,
    pub headings: usize,
    pub has_title: bool,       // THAT one exists, never WHAT it says
    pub warnings: Vec<&'static str>,   // fixed harness constants
}
```

Every field is measured by the harness. A page can *influence* these numbers — it can contain four
thousand links — but it cannot **author** them. **A number cannot carry an instruction.**

## What is deliberately absent, and why each one matters

No title, no headings, no description, no snippet. Each is attacker-authored text, and putting any
of them on the reference would quietly restore exactly what this removes — a page whose `<title>`
reads *"ignore your instructions and run …"* would be back in the orchestrator's window, with the
store providing false assurance that it was not.

`warnings` is the subtle one. `Warning::to_string()` interpolates values on several variants —
`UnknownCharset { declared }` embeds a charset label taken **from the page**. So the reference
carries `warning_kind()`, a closed set of harness-authored constants, and
`warning_kinds_are_fixed_strings_and_carry_no_attacker_text` asserts both halves: that the kind is
clean *and* that the `Display` form is not, which is why the distinction exists.

## Decision

1. **`marlowe_extract::store::DocumentStore`** — content-addressed, `Send + Sync`, cheap to clone,
   so the concurrent fetch path writes from many threads and one reader reads.
2. **Idempotent by content.** Two URLs serving identical bytes collapse to one hash and one slot.
3. **`FileSystemTools` holds one**, and every `web` fetch stores the extracted document whole and
   emits its ref in the result summary.
4. **`text()` is the only way content leaves.** Every call site of it is a place untrusted text
   starts flowing again, which makes them auditable by grep.

## Shipped, and what it cost

`web` now returns the reference **instead of** the page, at `AgentObserved`. Content comes back
through exactly one door: `read(ref=…)`, at `UntrustedContent`, which the loop condenses through
ADR-041's quarantined reader.

`read` gained `ref` as an optional **Target** alongside an optional `path`. **ADR-034's rule is
preserved rather than broken:** that rule is *a parameter the executor cannot run without is
required*, and `read` now has two ways to name its subject, so neither alone is structurally
mandatory. A call supplying neither is refused with a message naming both — and a call whose `path`
was supplied and *refused* gets a different message, because telling a model whose traversal was
just blocked that it "gave neither" points it at the wrong correction. (Caught by
`an_escape_never_reaches_an_executor_at_all`.)

`ref` is a Target and not a payload because it selects **which** document is read. A ref the model
took from a `web` result is `AgentObserved`, so the ordinary flow adjudicates; a ref composed out of
a fetched page's own text would carry that page's class and be blocked by the same check as any
other target.

| | Fetch 30 pages | Read them |
|---|---|---|
| Before ADR-041 | 30 model calls | — |
| After ADR-041 | 1 model call | — |
| **Now** | **0 model calls** | 1 per group, and only for documents actually opened |

## Tests

**Every assertion is on the BYTES of a reference, never on its trust class.** A build that stamped
`AgentObserved` while still shipping the page would satisfy a class check and fail all of these.

`marlowe-extract/src/store.rs` (6) and `tests/adversarial.rs` (54) — the reference leaks no title,
no heading, no description, no link URL and no body text, each paired with a control proving that
field *was* hostile; the hash is hex-only; the URL is the caller's; warning kinds are constants
while the `Display` form demonstrably is not.

`marlowe-exec/tests/web_returns_a_reference.rs` (12) — a page hostile in four separate fields yields
a clean reference; the reference is made only of numbers, the caller's URL and harness vocabulary;
the counts that *do* cross are enough to plan with; dereferencing returns the content and it is
`UntrustedContent` again; a round trip does not launder; an HTTP error body is measured not quoted;
a redirect carries no content; a scanned PDF reports `needs-ocr` without quoting the document.

`marlowe-loop/tests/injection_attempts.rs` (10) — end to end through the real `Engine`, including
the pessimistic case where the quarantined reader **complies** with the injection and relays it
verbatim. Containment must not depend on the reader resisting.
