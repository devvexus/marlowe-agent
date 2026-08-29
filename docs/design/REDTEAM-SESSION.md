# The red-team session — what it measures, and when its zeros mean anything

**Scheduled 2026-08-29 with the human.** Referenced as a dependency by five documents and owned by
none until now: `M3-DESIGN.md`'s header and §8, `M3-DESIGN.md` §10 item 7, `ROADMAP.md`'s M3 block,
`SCOPED-MEMORY.md`'s acceptance table, and `01-brief.md` §8.3.

| | |
|---|---|
| **Status** | scheduled, not started |
| **First attempt** | **end of M3 Session C** — injection only |
| **Second attempt** | **post-M3, after Session D** — the full class list |
| **Depends on** | C for the typed upward channels (the A8 control); D for a memory write path (the laundering classes) |
| **Blocked by nothing** | both passes are runnable at their scheduled points |

---

## §1. Why this is not a defence-in-depth check

`01-brief.md` §8.3 is explicit, and it is the sentence that sets this session's weight:

> Measured resistance on an AgentDojo-style prompt-injection suite, reported as attack success rate
> *and* utility retention — a defense that blocks everything by breaking the agent is not a defense.
> **Since the §8.2 amendment this is a first-order result, not a defence-in-depth check**: with no
> kernel backstop on the ordinary path, it is the primary evidence that containment works.

So this is the primary evidence, and it sat unscheduled across five documents' worth of
cross-reference. That is the first finding, and it is recorded here rather than fixed silently.

---

## §2. THE THING THAT WOULD OTHERWISE PRODUCE A FALSE PASS

**The session splits into two halves with opposite readiness, and they must never be reported as one
number.**

**The injection half is reachable today.** `M3-DESIGN.md` §2.2 concedes in writing that the
quarantined reader's summary *"comes back attacker-shaped anyway"*. M3 Session B established where
it lands: `crates/marlowe-loop/src/engine.rs:2182` pushes the condensed note at
`TrustClass::AgentInferred`, which is **above** `blocks_composed_targets`'s threshold. So the
attacker's goal is precise and the surface is live: get text through the reader's `OutputContract`,
and it sits in the parent's window at a class that blocks nothing.

**The taint half is NOT reachable, and its zeros are vacuous.** `marlowe_memory::ingest` has one
production caller and it is the `--eval-adapter`. M3 Session B established *why that cannot simply be
fixed*: §2.1 forbids tainting the permanent run, §7 withholds `MemoryWrite` from workers until
Session D, so **no run in the current architecture may correctly hold an untrusted belief.** A
red-teamer attacking this surface returns **0 successes out of N**, and that reading is
character-for-character identical to *"the defence works"*.

> **A red-team report that does not separate these two halves is the vacuity family aimed at the
> primary evidence that containment works.** CLAUDE.md's standing question — *what would this
> measurement read if the thing I care about were broken?* — answers "the same" for every taint-class
> zero taken before Session D. Those cells are **discarded, not celebrated.**

---

## §3. The two positive controls, one per axis

A clean sheet is two hypotheses — *containment is structural* and *the attack set is too weak* — and
neither pass can separate them without a control that is **expected to fail**.

### 3.1 Channel axis — arm A8, already designed

`M3-DESIGN.md` §9.1 arm **A8**: upward channel shape, three arms — fully typed / typed + one
validated sentence / **free text (control, expected to fail)** — measured on injection-propagation
rate. Its note is this session's justification for running at end of C rather than post-M3:

> **A8's third arm is the vacuity control for the entire §2 invariant.** If free-text upward performs
> identically on the red-team set, the typing is decorative and the finding is worth more than the
> feature.

**Sessions D and E are built on the assumption that typed upward containment works.** End of C is the
last cheap moment to discover that it does not.

### 3.2 Model axis — `marlowe-red:9b`, and it is a control rather than a bonus round

| Model | Role | Notes |
|---|---|---|
| `qwen3.5:9b` | **primary** | 9.7B, Q4_K_M, 262k context, tools + thinking. A safeguarded model: the ordinary product case |
| `marlowe-red:9b` | **positive control** | trained without safeguards, highly susceptible to prompt injection |

**Run `marlowe-red` whether or not `qwen3.5` comes back clean.** Both clean is *still* two
hypotheses. What separates them is `marlowe-red` against **A8's free-text arm** — an
injection-susceptible model down an unprotected channel. If that does not propagate, the attack set
is too weak and every zero above it is uninterpretable. If it propagates and typed structure does
not, the typing is load-bearing and the zeros are real.

That is what would make the claim *"the security of this system does not depend on the model"*
evidence rather than a hope.

---

## §4. Scope of each pass

### Pass 1 — end of M3 Session C. Injection only.

- A8's three arms × `qwen3.5:9b`, then × `marlowe-red:9b`.
- Attack surface: the condensed summary re-entering a parent at `AgentInferred`, and the typed
  upward channels C ships.
- **Excluded:** every class that needs a memory write path. Their absence is stated on the report,
  not left as a blank.
- Reported as ASR **and utility retention**, per §8.3.

**Available earlier, if an early signal is wanted:** a narrow layer-1 A/B needing no tree — run the
injection set with the quarantined reader on, then off (raw page straight into context). Its control
is free, and it establishes that layer 1 does real work on the injection axis. It is a day, not a
session, and it is not the first attempt.

### Pass 2 — post-M3, after Session D.

Session D gives workers `MemoryWrite`, which is when `ingest` gains its first correct production
caller and the taint half becomes real. `01-brief.md` §8.3's full class list then applies:

1. memory laundering through LLM-mediated derivation
2. delayed-trigger poisoning
3. tool-description poisoning
4. skill supply-chain compromise
5. sandbox-boundary redefinition via agent output

plus §8.3's **0% attack success rate against unsigned memory writes**.

> **A correction to two documents, recorded rather than edited in place.** `ROADMAP.md`'s *"Then, and
> not inside M3: the red-team session — the boundary cannot be tested until something can taint"* is
> right about the reason and imprecise about the date: *something can taint* arrives at **Session D,
> inside M3**, not at the milestone edge. `SCOPED-MEMORY.md`'s *"poisoning ASR ... measured post-M3"*
> inherits the same imprecision. The ordering is unchanged; only the boundary moves.

---

## §5. Sandbox — it must BE layer 4, not sit behind it

The human's requirement is zero chance of harm to the machine, closely guarded.

**Layer 4 — egress allowlisting — is approved and NOT shipped.** ADR-031 and ADR-032 exist; the
deny-by-default outbound path does not, pending the approval surface. Layer 5 — the trust ledger —
is M6.

So a red-team session runs with **one of the five layers simply absent**, and the sandbox has to
supply it: **network egress control at the sandbox boundary, not in-process.** An in-process
allowlist is the thing being tested, and it is not there.

**Every report before M6 states "three layers live, two absent" on its front page.** Otherwise a
partial number reads as a whole-system result — which is this project's most-logged failure, applied
to its most important measurement.

---

## §6. What is NOT an arm

`M3-DESIGN.md` §9.2, unchanged and repeated here because a red-team session is exactly where someone
would be tempted to A/B them:

> Anything where a wrong answer is a security hole rather than a quality loss. **TERMINATE's
> structural invisibility, layer 1 routing, and the empty tool set are not A/B tested.** They are
> asserted.

They are not arms. They **are** targets: a red-teamer should attempt to violate each, and a
successful violation is a defect report rather than a data point.

---

## §7. What this document deliberately does not claim

It does not claim the two passes are sufficient. Three of five layers are live at pass 1 and pass 2;
the full five-layer system cannot be red-teamed until M6.

It does not claim the class list is complete — §8.3's five are the classes the brief names, and a
completeness pass over them is part of the session rather than a precondition for it.

And it does not claim that a clean pass 1 means the design is sound. It means the design is sound
**or** the attack set is weak, and §3's two controls are the only things that tell those apart.
