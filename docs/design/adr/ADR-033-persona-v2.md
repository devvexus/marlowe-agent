# ADR-033 — The persona artifact moves to v2, adopted from a working prompt and translated against the real harness

**Status:** ACCEPTED (M2 C2f, 2026-08-10) — the human's direction; `persona/` is brief §13
**Extends:** Addendum C (amended at §C0, §C1, §C5, §C7, §C10), ADR-030
**Artifact:** `persona/v2.md`. Rationale and the full translation table: `persona/README.md`

## 1. Decision

`persona/v1.md` — pinned verbatim from Addendum C §C10 — is superseded by `persona/v2.md`, a prompt
from a prior harness that performs measurably better with this model class. `daemon.rs`'s
`include_str!` and `persona_emission.rs` both move to v2. v1 is retained for the diff.

**It was translated, not copied**, and the translation is the substance of this decision.

## 2. The rule the translation applied

**A prompt that promises a capability the harness does not have is the same defect as a tool
description that does.** M2 C2e paid for this once: `bash`'s description claimed a *"persistent
shell session"* against a fresh `cmd /C` per call, and asked to demonstrate its tools the model
produced a **fabricated shell transcript** echoing our own false description back. A persona is
model-visible prose in the stable tier of every request; it is the highest-leverage place to author
that defect and the least likely place to notice it.

So: `<vision>` (screen and webcam tools — none exist, and it instructed the model to *"never say I
can't see"*), `<redteam_routing>`, `<git>`, the search half of `<knowledge_and_search>`, and most of
`<memory_and_continuity>` were **cut**, not softened.

**The most dangerous one was not a cut.** `<tool_use>`'s first non-negotiable rule was *"Emit
multiple independent tool calls in a single response."* `parse_step` does `calls.first()` and
discards the rest **silently**. A missing tool returns an error the model can read; a dropped call
simply never happens. v2 states one call per turn, which is what the loop does — and reverts when
the loop does otherwise, in the same commit, never before it.

## 3. Where v2 supersedes Addendum C's prose, and where it does not

**Supersedes.** §C4's required behaviours and §C1's "Is not" list are dispositions stated in
paragraphs. v2 states them as an explicit `<words_to_avoid>` list and a pre-response `<self_check>`.
A probe can grep for `great question`; it cannot grep for *not sycophantic*. §C10 is amended to
record that the artifact is now the source and the document defers to it.

**Does not.** §C7's acceptance criteria are the scoreboard and are not deferred to, in the same way
`eval/` is never modified to accommodate an implementation.

## 4. The open item, stated as the risk it is

**v2 has not been measured on this system.** No sycophancy score, no blind-discrimination score, no
drop-condition run exists — for v2 *or* for v1, because §C7's probe set has never been built.

The justification for adopting v2 is that it performed well in a prior harness. **That is a prior
about a different system, and this project has a standing rule about carrying a measurement across
a boundary without re-taking it.** The rule cuts here. Adoption is the human's call and is recorded
as such; what is not claimed is that v2 is better *as measured*.

§C7 is amended to say the suite does not exist, because an acceptance table with no runs behind it
reads exactly like one that is being met.

## 5. Consequences

- **~3,544 tokens against v1's ~409 — 11.5% of the effective window**, permanently, in every
  request. The stable tier is not trimmable, so it displaces everything else and §6's compaction
  trigger arrives earlier. §C0's *"roughly twenty lines … negligible"* is amended.
- **§C2's five drop conditions are still prompt text, not a permission gate.** v2 states them more
  fully than v1, which could be mistaken for enforcement. It is not. M6.
- **The operator is not named in the artifact.** `IDENTITY_FACTS` is kept separate from `PERSONA`
  precisely so the artifact stays deployment-independent; a person's name falls under the same
  argument as a workspace path.
- **OPEN: §C1 derives the register from Chandler's Marlowe, the adopted prompt from Christopher
  Marlowe.** Restraint versus transgression — different dispositions that overlap only partly. v2
  names neither (§C8 forbids backstory) and states the agreed behaviour directly. If the poet is
  intended, §C1 is what needs rewriting.
