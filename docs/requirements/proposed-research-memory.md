# Research memory — a required capability

**Status: REQUIRED by the human, 2026-08-11. Not designed, not built, not scheduled.** Recorded
here because it was asserted as a must-have during M2 Session D and would otherwise live only in a
transcript. Held in `requirements/` rather than `design/adr/` for the same reason
`proposed-K1-amendment.md` was: it is a statement of what the product must do, not yet an argued
decision about how.

---

## The requirement, in the human's words

> Research memory is a must have.
>
> I have him research deep physics niche area. I later ask him a niche physics question from
> there → he utilizes the memories he gained from that research he did (solo) to give a better
> answer.

**The acceptance scenario, stated so it can become a test:**

1. Marlowe runs a deep-research task on a niche physics area, **solo** — no human in the loop for
   the duration.
2. Time passes. A separate session, a separate run.
3. The human asks a niche question from that area.
4. The answer is **materially better than it would have been without the research**, and the
   improvement comes from memory rather than from re-fetching.

Step 4 is the one that needs an instrument. "Better" is not measurable as stated; a paired
comparison against the same question asked of a store without the research is.

**Why this is not a nice-to-have:** it is the eleven-week-callback property (brief §5) applied to
knowledge the agent acquired on its own initiative. Memory is the spine of this project, and a
memory system that can only remember what a human said to it is remembering half of what happened.

---

## It works under the design currently argued for, and here is the trace

The design in question is **declared injection of untrusted-origin memory** — a run states at
construction whether untrusted-origin memories may be auto-injected, per §5's *declared at spawn,
never inferred*. No new `TrustClass` variant. See "What it must not be" below.

| Step | What happens | Trust |
|---|---|---|
| Research run fetches pages | `web` → `UntrustedContent` per `trust_for_channel(Channel::Web)` | floor drops, composed targets blocked for that run |
| Research run writes memories | claim write at `min(AgentInferred, run_floor)` = `UntrustedContent`, source identity attached | correct: origin is a page |
| 6h maturation elapses | §4.3 exclusion (3) releases them into auto-injection candidacy | unchanged |
| Human asks the physics question | retrieval injects rank 1 if the rerank margin clears the declared cut point | `ContextView::trust_floor()` drops to `UntrustedContent` |
| Marlowe answers | reads memory, speaks | **fine — answering needs no composed target** |

**The cost lands exactly where it does not hurt.** Injecting an untrusted-origin memory makes the
run read-only for *model-composed* targets, because `trust_floor()` is `min` over all blocks
including `SourceKind::InjectedMemory` (`context.rs:377`) and the latch is monotonic. Answering a
question needs no tool call at all, so the scenario above pays nothing.

**And the mixed case degrades gracefully rather than failing.** `Provenance::taint_for`
(`provenance.rs:94`) looks each argument up in the attributed set before falling back to the floor,
and `attribute_user_message` attributes every whitespace token the user literally typed as
`UserAsserted`. So in a run that has injected research memory, Marlowe can still act on **targets
the human named** and cannot act on targets it invented from what it read. That is precisely the
right line, and it falls out of ADR-023 rather than needing new machinery.

---

## What it must not be

**Not a new `TrustClass` variant.** `TrustClass` is an ordinal (`UntrustedContent = 0` …
`UserAsserted = 3`) and propagation is `min` over a lineage. A "Gathered" class has no correct
position: above `UntrustedContent` grants research content more authority than the page it came
from, which is §14.6 laundering with the derivation step built in; at the same level it is an
annotation, not a class. §3.3 binds trust to **origin**, and the origin of research content is a web
page. `trust_for_channel` is already total over `Channel` with no default arm, and `Web` already
answers this question.

**Not a summary that escapes the floor.** A condensed return from a research subagent is still
derived from untrusted text, so `min` propagation keeps it at `UntrustedContent`. HP6's finding is
that content signals do not survive derivation, and a worker that "cleans" a page is the laundering
path with an extra hop.

**Not a floor that lifts when the memory leaves the view.** M2 C2f established the latch is
monotonic per run precisely because the assembler dropping a block to stay inside budget was
silently handing privileges back.

**Never store the payload of content flagged as an injection attempt.** The retention record —
source identity, time, reason — is the useful part; the text is the attack, and keeping it in a
retrievable store is the plant step of a delayed-trigger attack performed on the attacker's behalf.
`Fidelity::Tombstone` already exists and is already excluded from injection; that is the shape.

---

## The distinction the human found, which is real and unbuilt

One scalar is answering two questions: *may this text influence what the system does?* and *may this
text be recalled and shown to the model as information?* Today they are the same field. The second
is what research memory needs and the first is what must stay closed.

The resolution is **not** a second trust axis but **attribution**: the stored unit is not "a fact",
it is *"this source asserts X"*, injected with the source named. That is the question that survives
a uniformly-tainted population — *who asserted it*, per ADR-036 §5 and the CLAUDE.md ledger entry on
saturation — and ADR-036's corroboration-over-independent-roots is already the mechanism that makes a
set of individually-untrusted claims usable without trusting any one of them.

The human's **Kept / Discarded** distinction is a *retention* decision, not a trust decision. It
belongs beside `Fidelity`, not beside `TrustClass`.

---

## Gate: do not design this until the poisoning numbers are real

Research memory is, structurally, **the delayed-trigger attack performed on purpose** — write
everything read now, retrieve it later. MINJA, MemoryGraft and delayed-trigger have all reported ASR
**0.000**, and STATE.md records all three as **vacuous**, because the gate injects nothing.

M2 Session D's D2 turns injection on and makes them non-vacuous for the first time. **Those numbers
are the prior for what a deliberate firehose of untrusted content would do**, and they should gate
this design rather than follow it. A capability that multiplies the ingested-untrusted-content
volume by two orders of magnitude should not be designed against ASRs that were measured on a system
that injected nothing.

---

## THE PATH IS `recall`, NOT AUTO-INJECTION — and this was nearly designed around the wrong one

**Added 2026-08-11 after the requirement was first written.** The scenario above was being reasoned
about as an auto-injection problem for several exchanges. It is not, and the distinction decides
what has to be built.

| Path | Gate | What it is for |
|---|---|---|
| **Auto-injection** | K1's declared operating point — **10% coverage**. Nine queries in ten inject **nothing** | the unprompted callback: *"you mentioned eleven weeks ago…"* |
| **Explicit `recall`** | **no precision gate.** Sees tombstones and unmatured entries (CONTRACTS §3.6) | the model deliberately searching what it knows |

The human's scenario — *researched physics, later asked a physics question, uses what was found* — is
**`recall`**. Marlowe recognises he has worked in the area and searches his own memory. Brief §5.5
says exactly this: *"recall recovered by making the agent's explicit memory search tool excellent."*

**The distinction is principled rather than a loophole.** K1's threshold governs content arriving
**unrequested**, which the model reads as its own knowledge. A search the model chose to run, and
whose results it can evaluate, is a different act. Security is unchanged either way — recall results
land as `UntrustedContent` and drop the run floor exactly as injected memories do — so nothing is
smuggled past a guard.

**Consequence for scheduling: the capability is closer than the M3 framing suggests.** `recall` has
no executor; that is M2 Session D's D3, not M3. What M3 owns is *filling the store by researching
solo*, and its blocker is unattended egress rather than anything about memory.

## The second axis exists in the schema and is dead

`MemoryEntry.confidence` is written as the literal `1.0` at **nine** construction sites
(`ingest.rs:138`, `consolidate.rs:772`, `store.rs:120`, `entry.rs:151`, and five more) and **read
nowhere**. It is not among `features::FEATURE_NAMES`' eleven. It has never influenced a ranking, a
gate verdict or an injection.

This matters because it is the field the requirement actually needs. Trust class answers *where did
this come from* and must never move. Confidence answers *how much reason is there to believe it* and
is exactly what research memory needs to accumulate. **The two-axis design does not require a schema
change — it requires writing to a field that already exists.**

Candidate signals, and their status stated honestly:

| Signal | Status |
|---|---|
| Corroboration over independent roots | **Designed, not built.** ADR-036, M3 |
| The human confirming a claim | **No mechanism.** Nothing turns "yes, that's right" into a stored signal |
| **Verified use** — the claim was used and the outcome checked out | **INVENTED IN CONVERSATION by the agent, 2026-08-11.** No ADR, no decision, no roadmap slot. It was described as "the strongest signal" before anyone had agreed it was a signal at all. Recorded here so it is not later mistaken for a design |

**Why confidence is also the security answer.** The adversarial hole in the declared operating point
is that it thresholds the **rerank margin** — a score an attacker who controls text can optimise
directly. Corroboration count and verified use are terms an attacker **cannot** manufacture: planting
three independent roots is a different order of difficulty, and a use that actually worked cannot be
faked into the harness's own observation. **Confidence is the term the attacker cannot forge, and the
gate currently reads only the term they can.**

## Open questions

1. **Volume.** Research writes far more than conversation does. Capacity is fine — Session L
   measured the candidate scan at 3.83 ms / 1.78% of P95 at 113k entries — but K1's precision is a
   base-rate property, and the declared operating point was measured at n=229 on a population where
   a correct memory existed in the pool. A large tainted corpus changes that base rate in the
   direction nobody has measured.
2. **Which run declares it.** A research run declaring "inject untrusted-origin memory" is one
   thing; the *later question-answering* run is the one that actually needs the declaration, and it
   is an ordinary interactive run. Whether that is a per-run flag, a per-query mode, or a property
   of the retrieval call is undecided.
3. **Solo operation.** "Research he did solo" means an unattended run, and `DenyUnattended` returns
   false, so `web` cannot be approved with nobody there. Unattended research needs an egress
   decision that does not exist — ADR-032 §3.1 grants hosts one at a time, by a human, session-scoped
   and never persisted. That is a direct conflict with the requirement and needs resolving.
4. **The measurement for step 4.** A paired comparison — same question, same model, store with and
   without the research — is the only honest instrument, and it needs a question set nobody has
   built.

## Owner

**M3.** ADR-035, ADR-036 and ADR-037 are the designed research stack and durable runs are its
precondition. This document is the requirement those ADRs must satisfy; it is not itself a design.
