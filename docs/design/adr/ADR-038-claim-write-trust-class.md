# ADR-038 · A model-authored claim is written at `min(AgentInferred, run_floor)`

**Status: ACCEPTED** by the human, 2026-08-11, during M2 Session D. §13 territory — the write path
computes a trust class, so this decision precedes the code rather than documenting it afterwards.

---

## Context

`remember` is a `ModelStep::MemoryWrite`, routed to `MemoryHost::remember`. Wiring it in M2 Session D
turned up something the STATE entry did not say: **there is no single-claim write path in
`marlowe-memory` at all.** `ingest()` writes a session's *turns*; nothing writes a model-supplied
*claim*. CONTRACTS §3.5 pins `remember(run, claim) -> Result<WriteReceipt, Rejected>` and it has
never existed. `memory: None` in the daemon was concealing an absent implementation, not merely an
unwired one.

Building it requires answering one question that has no defensible default:

**What trust class does a model-authored claim carry?**

`trust_for_channel` is total over `Channel` with no default arm, and a model is not a channel —
correctly, since §3.3 binds trust to *origin* and the model is not an origin. So the table cannot
answer it and something new must.

## The candidates

| Candidate | Verdict |
|---|---|
| `AgentObserved` (2) | **Wrong by §3.3's own words.** That tier is *"the HARNESS computed it: exit codes, hashes, line counts."* The model writing prose is not that |
| `AgentInferred` (1) | *"the model concluded it."* Reads correct in isolation and is **the dangerous one** — see below |
| `min(AgentInferred, run_floor)` | **Chosen** |
| Reject the write when the floor is at `UntrustedContent` | Rejected: loses information the run legitimately produced, and a refusal the model cannot act on is worse than a correctly-classed write |

## Decision

```
own_trust = min(AgentInferred, run's latched trust floor)
effective = effective_trust(own_trust, parents)      // §3.3 unchanged
```

The latched floor is `Provenance`'s, the same value `taint_for` already computes as
`view.trust_floor().min(latched)`. **No new quantity is introduced and `trust.rs` is not modified** —
`effective_trust` and `trust_for_channel` are called, not changed.

## Why

**Bare `AgentInferred` is a laundering path, and it is reachable today.** A run that fetches a page
and then calls `remember` would write attacker-shaped text at `AgentInferred` — one full class above
`UntrustedContent` — with the page's origin nowhere in the record. That memory then competes for
rank 1 at injection on equal terms with everything else, and arrives in a later run reading as
Marlowe's own conclusion.

`profile.rs`'s `reads_untrusted && may_write_memory` guard does **not** cover this. That guard closes
the *quarantined reader* writing memory. An ordinary `interactive()` run reads untrusted content and
may write memory — both true, by design, and the combination is the whole point of an agent that
reads and remembers.

**The floor is already computed and then discarded on the write side.** ADR-023 latches it
monotonically per run because C2f found the assembler dropping a block to stay inside budget was
silently handing privileges back. Writing a memory is composing a *durable* target out of run
content — the most consequential composition the system performs, since it outlives the run. A write
path that ignores the floor is the one place the latch is calculated and thrown away.

**It degrades correctly under saturation.** In a uniformly tainted run every claim lands at
`UntrustedContent`, which is *true* rather than merely conservative. That is the property the
CLAUDE.md ledger entry on uniformly-tainted populations asks for: when the floor stops
discriminating, it should stop *claiming* to discriminate.

**`ingest.rs:76-85` predicted this moment.** Its comment explains that the empty-lineage
`effective_trust` call is made rather than short-circuited because *"the propagation rule is the
thing under test, and a path that only runs once consolidation exists is a path that is broken when
consolidation arrives."* The reasoning was right and it named the wrong arrival. Parents were never
the problem. **`own_trust` is**, and this is the first write path where the model chooses the text.

## Consequences

- A `remember` in a run that has read a web page writes at `UntrustedContent`. That is intended.
- A `remember` in a clean run writes at `AgentInferred`, one below `AgentObserved`, so a model claim
  never reaches the tier reserved for what the harness itself computed.
- Trust is **never** promoted afterwards. A belief's class is fixed at write time and `min`
  propagation only lowers it. What may accumulate is *confidence* — a separate, currently dead field
  (`MemoryEntry.confidence`, written `1.0` at nine sites and read nowhere). See
  `docs/requirements/proposed-research-memory.md`.
- The claim write path must record the floor it used, so a later reader can tell
  *"AgentInferred because the run was clean"* from *"AgentInferred because nobody checked"*.

## What this does not decide

**Whether an untrusted-origin memory should be auto-injectable at all**, and under what declaration.
That is the research-memory requirement and it is open. This ADR governs the class a claim is
*written* at, not what retrieval later does with it.
