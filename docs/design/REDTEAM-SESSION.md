# The red-team session — what it measures, and when its zeros mean anything

**Scheduled 2026-08-29 with the human.** Referenced as a dependency by **seven sites across six
documents** and owned by none: `M3-DESIGN.md`'s header, its §8 and its §10 item 7; `ROADMAP.md`'s M3
block; `SCOPED-MEMORY.md`'s acceptance table and its arm S5; `01-brief.md` §8.3; `DECISIONS.md`'s
§8.2-amendment entry, which is where this number became first-order; and `CONTRACTS.md` §9's
`Reversible` rationale, which rests on one named class from the list. **Two of those are settled
decisions resting on a measurement nobody had scheduled**, which is §1's finding stated as a count.

**And nothing linked here until 2026-08-29.** The filename appeared in the repository exactly once —
as this file's own path — so a reader starting at `STATE.md` or `ROADMAP.md`'s milestone table never
arrived. `ROADMAP.md` now points here from its M3 design list, its Session C row and its red-team
paragraph; `CLAUDE.md`'s five-layer section points here too, which is where a reader is already asking
what evidence exists that the layers work.

| | |
|---|---|
| **Status** | scheduled, not started |
| **First attempt** | **end of M3 Session C** — injection only |
| **Second attempt** | **post-M3, after Session D** — the full class list |
| **Depends on** | C for the typed upward channels (the A8 control); D for a memory write path (the laundering classes) |
| **Pass 1 blocked by nothing** | it runs on what C ships |
| **Pass 2 is NOT unblocked by D alone** | it also needs ADR-062 §4's origin decision — the human's — and four abstention gates shown open. See §4 |

---

## §1. Why this is not a defence-in-depth check

`01-brief.md` §8.3 is explicit, and it is the sentence that sets this session's weight:

> Measured resistance on an AgentDojo-style prompt-injection suite, reported as attack success rate
> *and* utility retention — a defense that blocks everything by breaking the agent is not a defense.
> **Since the §8.2 amendment this is a first-order result, not a defence-in-depth check**: with no
> kernel backstop on the ordinary path, it is the primary evidence that containment works.

So this is the primary evidence, and it sat unscheduled across seven cross-references. That is the
first finding, and it is recorded here rather than fixed silently.

**`01-brief.md` is deliberately not amended to point back here.** A requirements doc states what must
be true; scheduling who runs it and when is a design act, and CLAUDE.md's map says requirements are
not loaded by default. The reachability obligation is discharged in `ROADMAP.md` — the M3 design list,
Session C's row and the red-team paragraph — and in CLAUDE.md's five-layer section, which are what a
session reads before touching this milestone.

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

**The taint half is NOT reachable, and its zeros are vacuous.** `marlowe_memory::ingest` has no
**correct** production caller — ADR-062. M3 Session B established *why that cannot simply be fixed*:
§2.1 forbids tainting the permanent run, §7 withholds `MemoryWrite` from workers until Session D, so
**no run in the current architecture may correctly hold an untrusted belief.** A red-teamer attacking
this surface returns **0 successes out of N**, and that reading is character-for-character identical
to *"the defence works"*.

> **Do not check this with `grep -rn "\bingest("`.** That command returns two hits since `673bcd2`
> added `DaemonMemory::ingest_external`, which calls `ingest` and has no caller of its own — so the
> retired check goes **loud and affirmative** and a reader concludes the daemon ingests. CLAUDE.md's
> instance #18. The discriminating command is one level down:
> `grep -rn "ingest_external(" --include=*.rs crates/*/src/` minus the definition, and **zero
> non-definition hits means the latch is still unreachable.**

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

**Note against the standing habit on this machine: live turns here normally run `marlowe-red:9b`.**
That is the **control** arm. Running pass 1 on it alone measures an unsafeguarded model and reports it
as the product — the reverse of the error §2 warns about, and just as invisible in the number. Both
fit the 16 GB card (6.6 GB and 5.8 GB), so both arms run, and **the report names which model produced
each cell.**

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
caller and the taint half becomes real.

> **Two things must be true before pass 2's taint half measures anything, and neither is Session D
> shipping.** ADR-062 §7 says *"Session D **at the earliest**"*: wiring also needs §4's **origin
> decision**, which is a pinned-contract change and the human's. And when a caller does exist, **four
> gates stand between an ingested belief and an observable refusal, and every one of them produces
> "no composed target was refused"** — the six-hour maturation window (`silent_until`,
> `MATURATION_WINDOW_MS`); `Abstention::NoReranker`, so a daemon started without `--reranking`
> auto-injects nothing, ever; `Abstention::NoRunnerUp`, so a profile holding exactly one planted
> belief can never inject at all; and rank-1 and rank-2 both inside `RERANK_BUDGET = 10` with a margin
> ≥ 1.165071. **Only the first is exercised by anything in the workspace.** A pass-2 setup that plants
> one belief in a fresh profile and attacks it is **guaranteed a zero by construction**. The setup goes
> on the report beside the number, and each gate is shown open before the number counts.

`01-brief.md` §8.3's full class list then applies:

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

## §5. Sandbox — it must still BE layer 4, and the reason is `bash`, not `web`

The human's requirement is zero chance of harm to the machine, closely guarded.

**Corrected 2026-08-29, and the correction is recorded rather than quietly applied.** This section
opened *"layer 4 — egress allowlisting — is approved and NOT shipped … the deny-by-default outbound
path does not [exist], pending the approval surface."* **That overstates the gap, and it was inherited
rather than checked.** Deny-by-default outbound exists and is live: `CapabilityProfile::interactive()`
holds `EgressPolicy::AllowApproved { granted: [] }`, an ungranted host produces
`Outcome::NeedsApproval` rather than a refusal, and the daemon's `SocketApprovals` puts the prompt on
the open connection with the full URL in `blast_radius.scope`. The product's own signed journal reads
**37 `web` decisions since the 2026-08-10 flip, every one `needs_approval` — zero allowed, zero
blocked — with 29 granted and 8 declined by a client answering**, which `DenyUnattended` cannot
produce. The approval surface this section called pending shipped at M2 C2f on 2026-08-10.

What ADR-032 describes and has **not** shipped is the **session-held grant**: `EgressPolicy::grant()`
has no production call site and `CapabilityProfile` exposes no `&mut` route to it, so every fetch is a
fresh human decision. That is *stronger* than the ADR, not weaker.

**So the `web` path is not the hole. `bash` is.** The adjudicator's egress section iterates parameters
typed `Url`; **`bash` declares none, so no `EgressPolicy` is consulted on that path at all** —
ADR-049 §4, measured: `curl` to arxiv.org returns HTTP 200 from `cmd /C`. What stands there instead is
`bash`'s `Irreversible` escalation, which asks about a **command** and never about a **destination**.
A red-teamer's shortest path to arbitrary egress is the shell, and it does not touch layer 4 on the
way.

**The sandbox requirement is unchanged. The reason is now specific:**

* **`bash` reaches the network with nothing allowlisting the destination**, so network egress control
  must sit at the **sandbox boundary, not in-process**. The in-process allowlist covers exactly one
  tool, and it is not the tool a red-teamer would reach for.
* **ADR-032 is `Status: PROPOSED — needs the human's approval`** and names
  `marlowe-loop/src/profile.rs` and `marlowe-permission/src/adjudicate.rs` as the §13-guarded files it
  touches. Both were edited. **An unaccepted §13 decision is not a defence to bet a machine on**,
  however well the code behind it reads.
* **No prompt has been observed on the current binary.** The 37 rows above are from builds up to
  2026-08-27. A code read plus a two-day-old journal row is weaker than a run, and this project has a
  named family for treating one as the other. The live re-check is one `web` call in the TUI and a look
  at the last `permission_decided` row.
* Layer 5 — the trust ledger — is M6 and does not exist.

**Every report before M6 states the layer tally on its front page, and it is no longer "three live,
two absent".** As of 2026-08-29:

| Layer | State at pass 1 |
|---|---|
| 1 — quarantine | **live**, and routed (ADR-039, ADR-041) |
| 2 — trust class propagation | **live** |
| 3 — the `(action, target)` latch | **shipped and UNREACHABLE in the daemon** (ADR-062). A pass-1 result about it measures a state the product cannot enter |
| 4 — egress | **live on the `web` path, absent on the `bash` path**, with no grant persistence and an unaccepted ADR |
| 5 — trust ledger | **not built — M6** |

A partial number read as a whole-system result is this project's most-logged failure. **Layer 3's row
is the one most likely to produce it here**: a clean injection pass at the end of Session C says
nothing about the latch, because nothing in the shipped daemon can reach it. Pass 2 may count layer 3
only once Session D has shipped a caller **and** ADR-062 §4's origin decision has been taken.

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

It does not claim the two passes are sufficient. **Two of five layers are unambiguously live at pass 1
— see §5's table, and note that the earlier wording here said three.** The full five-layer system
cannot be red-teamed until M6.

It does not claim the class list is complete — §8.3's five are the classes the brief names, and a
completeness pass over them is part of the session rather than a precondition for it.

And it does not claim that a clean pass 1 means the design is sound. It means the design is sound
**or** the attack set is weak, and §3's two controls are the only things that tell those apart.
