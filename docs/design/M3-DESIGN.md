# M3 — the agent organisation, and what it costs

**Designed 2026-08-24 with the human. Not built, not decided.** ROADMAP's M3 block specifies the
**control plane** — runs as first-class objects, WAL and resume, mid-flight steering, orphan policy.
This page specifies what runs *on* it: an organisation of agents, the channels between them, and the
single invariant that keeps the thing the user talks to safe.

| | |
|---|---|
| **Status** | design; ROADMAP M3's scope is unchanged and remains the foundation |
| **Depends on** | the control plane shipping first — there are no persistent agents without durable addressable runs |
| **Blocks** | the red-team session ([`REDTEAM-SESSION.md`](REDTEAM-SESSION.md) — **pass 1 at the end of Session C, pass 2 post-M3**); scoped memory (`SCOPED-MEMORY.md`) |
| **Anti-requirements honoured** | §15 — no swarm topology, no predeclared DAGs |
| **Anti-requirements crossed** | audit finding E4, and §10.1's *"workers do not talk to each other"* — both need explicit `DECISIONS.md` entries, see §5 and §6 |

> ### AMENDED 2026-08-31 — TWO DECISIONS BY THE HUMAN LAND ON THIS PAGE AND THEIR STATUSES ARE NOT THE SAME
>
> **The first is BUILT AND GREEN.** §1.2's *"masters hold no working tools, structurally"* is
> **reversed in code** (`6e01c37`): the PI is the senior researcher who does the hardest part
> himself. The requirement is [`PI-MODEL.md`](PI-MODEL.md) §3; the amendment, with the old rule
> quoted rather than deleted, is §1.2 below, and it reaches §1's level table and §3.1.
>
> **The second is PROPOSED AND NOT BUILT.** One OS sandbox per top-agent team, wrapping `bash` and
> nothing else — [`ADR-070`](adr/ADR-070-one-sandbox-per-team-and-it-wraps-bash.md), `Status:
> PROPOSED — needs the human's approval`. **There is no crate, no call site, and the one risk that
> could sink it has not been spiked.** §1.3 and §4 record where it would land and say *proposed*
> every time it is named.
>
> **Neither weakens layer 1 or layer 2, and §2.1's Marlowe invariant is untouched by both.** The
> reversal does not make anything safer — it moves the product onto an already-open finding, and
> §1.2 says so.


> **ADR-070 WAS ACCEPTED BY THE HUMAN ON 2026-08-31, AFTER THIS PAGE WAS WRITTEN.**
> Every *"proposed"* below that names it should be read as **accepted and still unbuilt** —
> acceptance authorised the work and settled the mechanism argument; it built nothing. The
> spike that gates the implementation (does Git Bash survive an AppContainer?) has not run,
> and ADR-070's own status line says acceptance does not change that. **No document may cite
> it as evidence that agents are contained until those probes have.**


> **AND SO WAS [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md), THE SAME DAY, AND IT LANDS
> ON §2's HEADLINE INVARIANT.** *Inside a top-agent's team, agents communicate in ordinary prose,
> both directions* — no `OutputContract` between an intern and its PI, no quarantined reader
> condensing a page before a worker sees it, no field validation on what a subordinate reports.
> **Accepted by the human 2026-08-31. NOTHING IS BUILT, and it depends on ADR-070's box, which has
> not been spiked** — so it inherits every caution in the block above and adds its own: *"it must not
> survive its own precondition."* If the Git Bash spike fails and there is no box, ADR-071's premise
> is gone.
>
> **The invariant did not weaken; its boundary moved.** Typing and layer 1 survive at exactly one
> edge — the team's edge with Marlowe — because the thing §2 protects is a permanent run that must
> never latch (§2.1), and that run sits at one edge and not at every hop. §2's headline, §2.2, §2.3,
> §1.4 and §9.1's A8 are amended in place below, each quoting what it replaces. **§2.1 itself is
> untouched: nothing here can latch the Secretary, and layer 1 is not removed — its *scope* changes,
> by a mechanism ADR-071 §7 records as undecided.**

---

## §0. The premise

Today's agents do the work **inside the conversation**, which halts it. The user asks for a follow-up
email and waits. The vision is the opposite: **the conversation never halts.** Marlowe says yes,
delegates, and asks what else there is. Work happens in parallel and Marlowe is the liaison to it.

The metaphor is a company. The user is the CEO, Marlowe is the secretary, and a task follows the
chain of command. **The user's time is the scarce resource and the architecture exists to protect it.**

**One Marlowe, ever.** There are no switchable sessions and no per-topic personas. `04-addendum-persona.md`
is binding — the persona is not configurable — and a product with ten Marlowes is ten relationships
to maintain. Continuity comes from memory, not from separate conversations. This was considered and
dropped 2026-08-24.

---

## §1. The five levels

| # | Level | Spawned by | Tools | Lifetime |
|---|---|---|---|---|
| 1 | **`[Mrlw]` Secretary** | nobody — he is the process | full conversational set | permanent, one instance |
| 2 | **`[Ta]` Top-agent** | Marlowe, and **only** Marlowe | per role | project-scoped |
| 3 | **`[Ma]` Master-agent** | a top-agent with the create grant | **per role, working tools included** — was *"management only"* until 2026-08-31, see §1.2; `ask` is the one refusal that survives (§3.1) | project-scoped |
| 4 | **`[Wa]` Worker-agent** | its master | per type | task-scoped |
| 5 | **`[TSa]` Tool-spawned** | any tool needing one | **none** | destroyed on return |

### 1.1 Marlowe spawns exactly one kind of thing

**The only agent Marlowe ever creates is a top-agent.** "Top-agent" is not a job description — it
means *permitted to communicate with the secretary*. A direct report.

At spawn Marlowe declares which kind it is:

- **`master`** — will orchestrate. Gets a create grant and an agent budget. Coordinates; does not work.
- **`worker`** — will do the task itself. Simpler jobs. Reports back and is usually disposed of.

The distinction is one question: *can one agent do this alone?* Getting it wrong is cheap in one
direction (a master with one worker is a wasted hop) and expensive in the other (a worker drowning
in a job that needed a team). **§9.1 makes this a measured arm rather than a guess.**

### 1.2 ~~Masters hold no working tools, structurally~~ — REVERSED BY THE HUMAN 2026-08-31, AND BUILT

**The rule this section carried is gone from the code (`6e01c37`).** It is quoted rather than
deleted, because what it lost to is the argument:

> *"A master with an `edit` tool will eventually edit. Not because it is disobedient — because it is
> capable and the work is right there. **The tool is absent from the set, not forbidden by
> instruction.** `ExposedSet::empty()` is the existing precedent: the quarantined reader holds no
> tools because there is nothing to call, not because it was asked nicely."*
>
> *"A master's set is: communicate, question, answer, meeting control, todo management,
> create/delete agent (if granted), budget allocation, escalate."*

**The ladder describes a research group, not a management chain.** A master is the **principal
investigator** — the senior researcher who does the hardest part himself and spawns assistants and
interns because the job is larger than one context. Delegation is leverage, not a job description,
and forbidding the AAII-52 model in the tree from touching the work spends the best model there is
on coordination. The requirement is [`PI-MODEL.md`](PI-MODEL.md) §3; this section is its
consequence.

**The rule also bought less than it looked like, and that is what decided it.** `SpawnRequest.task`
is an `ArgumentRole::Payload` and `composes_spawn_targets` never checks it — pinned in
`engine.rs`'s own row, *"`task` is a Payload: it may be shaped, not chosen"*. So a toolless master
still **wrote the task** for a worker that held `edit`. **It displaced the actor one hop without
adding a check.** Removing it does not open that path; it stops routing around it.

**What that costs, recorded rather than glossed, because §1.2's real argument was containment and
not hierarchy.** A master reads every worker's report, so it holds the most attacker-exposed context
in the tree, and a child's note crosses in at `AgentInferred` — **above**
`blocks_composed_targets`'s threshold, so layer 3 does not catch it. That is `SECURITY-AUDIT.md`
finding #1, already open. **This change did not create that hole; it moves the product onto it.**
The blast radius does not widen in *what can be done* — the toolless master could already choose
the worker and write its task — it widens in **how well-aimed it is**, because the actor holding
the tools is now the one holding the union of everything the team read. Red-team pass 2 (§10 step 7)
matters more after this change, not less.

**Nothing replaces it for working tools, and that is deliberate.** A master holding no `run` simply
cannot spawn — `may_create_agents` reads the exposed set — which is already a coherent state
needing no new error. *"A master MUST hold `run`"* would be inventing a rule in the same edit that
removes one.

> **ONE REFUSAL SURVIVED AND IT NEARLY DIED BY ACCIDENT, WHICH IS THE PART TO REMEMBER.**
> `MANAGEMENT_TOOLS` was doing **two** jobs under one whitelist: it withheld working tools — the
> rule above, now reversed — *and* it withheld `ask`, which is **a different decision the human
> took the same day** (§3.1: only a top-agent reaches the user). Deleting the whitelist for the
> first would have dropped the second in silence, with every remaining test green.
>
> `ask` is now refused **by name**: `ProfileError::OnlyATopAgentMayAsk`, at
> `CapabilityProfile::new`'s `Master` arm. `MANAGEMENT_TOOLS` and
> `ProfileError::MasterHoldsWorkingTool` are **deleted** — a constant with no reader and an error
> variant nothing can construct are instance #16 with a `thiserror` derive on it.

**The trap below is UNCHANGED and still load-bearing.** It was written about masters and it is not
about masters: it is about how anything is withheld, and §3.1's `ask` is now the live instance.

> **THE TRAP, AND IT HAS ALREADY SHIPPED ONCE HERE.** Do **not** express "a master may not edit" as
> `edit_calls: 0`. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on the first
> iteration — the agent pauses before its first model call while looking perfectly configured. That
> is instance #17, and it silently stopped the quarantine from reading anything at all. **Withhold
> the capability; leave the counter at 1.**

### 1.3 Worker tool sets are per type

A coder gets code tools. A researcher gets research tools. This is `CapabilityProfile` and the
validating constructor already exists — it is configuration, not new machinery.

Two benefits, and the second is the one to state in review: it cuts token bloat, **and it bounds what
a contaminated agent can do.** A research worker that read a hostile page cannot write to the repo
because it never held the tool.

> **AND THERE MAY BE A BOX UNDERNEATH THEM — [`ADR-070`](adr/ADR-070-one-sandbox-per-team-and-it-wraps-bash.md),
> `PROPOSED`, NOT BUILT.** No crate, no call site, nothing spiked. It is named here because this is
> where a reader looks for the answer to *"what stops a compromised agent"* and finds only a tool
> set.
>
> One sandbox per **top-agent team**, full freedom inside, wrapping **`bash` alone** — because
> `bash` is the only tool that leaves the daemon process. `web`, the model call, the journal and
> every file tool dispatch in-process in `marlowe-exec`'s `execute` match, `bash` and `web` on
> adjacent lines, so **research is untouched**: a boxed team fetches pages exactly as it does now,
> harness-executed.
>
> **It does not retire this section and it does not retire egress.** Per-type sets bound what a
> *contaminated* agent can do inside the box; a box bounds what a *compromised process* can reach
> outside it. And a box contains **damage, not disclosure** — `web` is harness-executed, the box
> holds a copy of the user's source, and the allowlist is the only thing between that and an
> attacker-named host.
>
> **Why an OS mechanism rather than a directory.** `bash` consults no `PathScope`, so a compromised
> agent walks out of a nominated directory without trying, and **a worktree is provisioning, not
> containment**. Denial would be the kernel rather than a filter: an AppContainer token with a NULL
> capability array holds neither `internetClient` nor `privateNetworkClientServer`, WFP drops the
> connect on the package SID, loopback is blocked for AppContainers by default, and the documented
> exemption requires admin — so an agent cannot grant it to itself. Verified on this machine by
> `icacls`, 2026-08-31: `C:\Users\matth` carries **no** `ALL APPLICATION PACKAGES` ACE while
> `C:\Program Files\Git` and `System32` do, so the user's profile is denied and Git Bash still
> runs, with no code written; `CreateAppContainerProfile` needs no elevation.
>
> **Therefore `bash`'s `Irreversible` escalation IS the current sandbox for that path**, and *"lift
> the escalation"* and *"build the box"* are **one change, not two**: lifting first removes the only
> control there is.
>
> **Marlowe is not boxed and his securities stay heavy**, precisely because he has the machine.
> **The largest risk is UNVERIFIED and is repeated as unverified:** whether MSYS2 / Git Bash
> survives AppContainer's redirected object namespace. That is a spike, not an argument. Two hard
> constraints from the human bind any build (`runs/m3-c/sandbox/HARD-CONSTRAINTS.md`): **it must
> never log the user out**, and **nothing verifies the box by running a destructive command** —
> escape is proved by *reaching something harmless*, never by destroying something.

### 1.4 Tool-spawned agents

No tools, no persistence, destroyed on return. The quarantined reader is one. The fact extractor in
`SCOPED-MEMORY.md` §4 is another. These are the only agents that are not addressable by anyone.

> **AMENDED 2026-08-31 BY [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md) — THE QUARANTINED
> READER IS MARLOWE'S NOW; THE FACT EXTRACTOR IS STILL THIS SECTION'S.** **Accepted, NOT built, and
> dependent on ADR-070's box, which has not been spiked.** A tool-spawned reader no longer stands
> between a fetched page and a worker inside a top-agent's team — inside the team the worker reads
> the page whole, itself — and the reader stands at the team's edge with Marlowe instead. The fact
> extractor is untouched: it serves memory rather than a team's internal hop, and `SCOPED-MEMORY.md`
> §4 is unamended.
>
> **The category itself does not change.** No tools, no persistence, destroyed on return,
> unaddressable by anyone; `ExposedSet::empty()` still means there is nothing to call, and instance
> #17's trap still means no counter goes to zero. What moved is **where one of its two instances is
> spawned**, not what a tool-spawned agent is. How that scoping is expressed in code is ADR-071 §7
> item 1 and is explicitly undecided — `Engine::condense_batch` triggers on the trust class, which
> is ADR-039's deliberate design, and keying it on *who is reading* is a different shape.

---

## §2. THE INVARIANT — prose flows down, structure flows up

**This is the whole security design and everything else in this page is a consequence of it.**

Downward is safe: instructions originate with the user, pass through Marlowe, and reach agents. No
laundering direction.

Upward is where an attacker wants to go, and it is where the tree is naturally shaped to help —
every level summarises for the level above. So:

> **Nothing but typed structure and artifact references crosses upward. Ever.**

> ### AMENDED 2026-08-31 BY [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md) — THAT *"EVER"* HAS A SCOPE NOW, AND THE INVARIANT DID NOT WEAKEN
>
> **Accepted by the human 2026-08-31. NOTHING IS BUILT, and the whole amendment rests on ADR-070's
> box, which has not been spiked.** The sentence is quoted above rather than rewritten, because what
> changed is its extent and not its content.
>
> It was written as though every hop in the tree were the same hop. It is not. **It governs the
> team's edge with Marlowe, and it does not govern communication inside a team.** Between an intern
> and its PI there is prose, both directions — no `OutputContract`, no field validation on what a
> subordinate reports, and no quarantined reader condensing a page before a worker sees it.
>
> **The boundary moved; the rule did not soften.** What §2 protects is named one section down: a
> *permanent* run whose floor latches for its life. That property belongs to **one** edge. Typing
> every hop in the tree was defending a run that is not standing at those hops, and at the edge where
> it does stand the sentence is unaltered — *"Ever"* still means ever.
>
> **Why prose inside a team is defensible, and it is contingent on a box that does not exist.** The
> team sits inside ADR-070's sandbox: no network, no filesystem outside its workspace. An attacker
> who owns a page owns an intern in a disposable directory, so the only thing that leaves the team is
> what it *says* upward. The team's security model is then two mechanisms with a clean split —
> **the sandbox bounds what an agent can DO; the Marlowe boundary bounds what it can INFLUENCE
> outside the team.** **It must not survive its own precondition:** if the spike fails and there is
> no box, this amendment's premise is gone and the unscoped sentence is what remains.
>
> **And typing was never what stopped persuasion.** `validate` checks shape, length and character
> class; attacker-shaped prose inside a declared field crossed either way. What typing bought was
> protection against **forged structure** — a child cannot invent a field or forge a header
> (ADR-039), and the parent attributes by harness-assigned slot. That is worth a great deal when the
> receiver is a **machine parsing slots**, and much less between two models reading each other's
> prose, where it costs fidelity to buy.
>
> **THE BET THIS TAKES, CARRIED HERE RATHER THAN LEFT IN THE ADR.** *"The PI is insanely smart and
> can catch the intern if they say something dumb"* is a claim about **model capability**, and this
> project has spent its life preferring structure to model behaviour — §1.2's own reversed rule said
> so in the other direction, *"not because it is disobedient, because it is capable and the work is
> right there."* Three things keep it honest and none of them is a guarantee: the box bounds the
> downside, so a fooled PI acts inside a sandbox and the failure mode is a wrong finding; **a human
> reads the output** (§3 puts the decision on a person deliberately); and **the bet is testable and
> is NOT yet tested** — `runs/m3-c/prefilter/FINDING.md` measured that *polite* injections, the
> plausible ones, beat every small model on every carrier while the shouting ones were caught, and
> nothing establishes that a smarter reader does better on the polite case. That is the measurement
> this amendment owes.
>
> **What is NOT claimed.** Not that the team is safer — the trade is fidelity and speed bought with a
> sandbox that has not been built. Not that layer 1 is removed: its **scope** changes, and how that
> happens in code is ADR-071 §7 item 1, undecided. And **§2.1 is untouched** — Marlowe is not boxed,
> his securities stay heavy, and nothing here can latch the Secretary.

### 2.1 Why Marlowe cannot be allowed to read findings

Brief §5.6: *"Memories derived from untrusted content may inform **analysis** but may not authorize
**action**."* Layer 3's floor is **monotonic and latched per run**, and Marlowe is a *permanent* run.

So a Marlowe who ingests one research finding **can never compose a target again — not for that
task, for his life.** No email, no file write, no recipient, until the process restarts. The
mechanism that protects him is the mechanism that would end him. **The liaison pattern is not
ergonomics; it is the only shape that survives ADR-023.**

### 2.2 How taint actually travels — it does not get *past* the layers, it goes *around* them

Worth writing down because "how could it possibly reach him" is the question everyone asks:

1. A worker fetches a hostile page. **Layer 1 works** — a quarantined child reads it, raw bytes never
   reach the worker.
2. **The summary comes back attacker-shaped anyway.** ADR-041 concedes this in writing: one reader
   holds up to `MAX_SOURCES_PER_READER` documents and *"A can influence how B is described — a
   **fidelity** risk."* The quarantine guarantees the reader cannot *act*. It guarantees nothing
   about whether the summary is *true*.
3. **There is no infection.** No code runs, nothing is owned. An agent read a document that lied and
   now believes something false. **No layer defends against a document being wrong**, and none could.
4. The belief walks up as **a chain of honest judgments about a dishonest premise.** Each hop is a
   competent model reasoning correctly from a poisoned input.
5. **Layer 2 marks it `UntrustedContent` the whole way and that changes nothing** — correctly.
   Layer 2 stops it *authorizing action*. Escalating is speech, not a target.

> **AMENDED 2026-08-31 BY [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md) — STEP 1 NO
> LONGER DESCRIBES A FETCH INSIDE A TEAM. Accepted, not built, dependent on ADR-070's unspiked box.**
> Step 1 reads *"a quarantined child reads it, raw bytes never reach the worker"*; inside a
> top-agent's team the worker **reads the page whole, itself**, and the quarantined reader survives
> at the team's edge with Marlowe (§1.4, as amended).
>
> **Steps 2 to 5 are unchanged, and that is exactly why the amendment costs what it costs.** This
> chain already conceded that the summary comes back attacker-shaped anyway, that there is no
> infection to prevent, that each hop is a competent model reasoning correctly from a poisoned
> premise, and that layer 2 marks the belief `UntrustedContent` the whole way without stopping the
> walk. **So the step that was removed was never the step that stopped it.** ADR-041's cross-document
> contamination — *"A can influence how B is described"* — goes with the shared reader; what arrives
> in its place is a worker holding the raw bytes it used to be spared, in a box, with a PI reading
> what it says.
>
> **Nothing here is measured yet.** The chain above is a description of how taint travels, and after
> this amendment it describes a path with one fewer stage in it inside a team and the same number at
> the Marlowe edge. Whether the reader at that edge is triggered by the trust class, as ADR-039
> deliberately made it, or by who is reading, is ADR-071 §7 item 1 and is not decided.

**The conclusion: the upward channels are the deliberate hole, and the human at the end of them is
the defence.** That is why §3 puts the user there and not Marlowe.

### 2.3 What "typed" means

An upward message is a record, not a paragraph:

```
{ run_id, severity, category (fixed enum), artifact_ref, lineage[] }
```

A category comes from a closed set. An artifact is a path the *user* opens. Free text, if allowed at
all, is one quarantine-validated sentence and is never the thing decisions are made on.

> **SCOPED 2026-08-31 BY [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md), WHICH IS ACCEPTED
> AND NOT BUILT, AND WHOSE PREMISE — ADR-070's BOX — HAS NOT BEEN SPIKED.** *"An upward message"*
> above now means **a message crossing the team's edge with Marlowe**. Between an intern and its PI
> there is no record, no closed enum and no validated sentence: there is prose, by decision rather
> than by omission.
>
> **The contract does not change and is not weakened.** `OutputContract` and `FieldSpec` are
> unchanged and still govern this edge, so the shape pinned in `CONTRACTS.md` is the shape that
> survives — this amendment removes no field and relaxes no validation anywhere the contract is
> consulted today.
>
> **What "the team's edge with Marlowe" is in code is NOT decided.** Today `Engine::spawn`'s note
> match is the only hop of that kind, and it does not distinguish a team boundary from any other
> spawn (ADR-071 §7 item 3). Until it does, this section describes an edge the code cannot yet name,
> and saying otherwise would be reading a design as an implementation.

---

## §3. Escalation — the emergency meeting

An agent that is genuinely stuck must be able to reach a human. Escalation is that path, and it is
**the single most dangerous channel in the system**, so it is specified tightly.

### 3.1 Routing

- Escalation starts at the agent's **direct master** and must be **approved at each level**.
- It is **scoped to the top-agent's subtree**. A worker can never address Marlowe.
- Only a **top-agent** may escalate to the user, and even then Marlowe is not the recipient.

> **`ask` IS NOW REFUSED BY NAME AT THE PROFILE CONSTRUCTOR, 2026-08-31 — AND IT ONLY JUST IS.**
> This routing had no enforcement of its own in the type. It fell out of `MANAGEMENT_TOOLS`, a
> whitelist §1.2 maintained for an unrelated purpose, so on the day §1.2 was reversed the rule
> would have gone with the constant and every remaining test would have stayed green.
> `CapabilityProfile::new` now returns `ProfileError::OnlyATopAgentMayAsk` — *"only a top-agent
> reaches the user"* — and `serde` routes through the same constructor, so a checkpoint cannot
> widen it either.
>
> **The tool is withheld, not locked at the call**, which is §1.2's principle surviving §1.2's
> rule: a door visible in the exposed set and described in the schema costs the model every call it
> spends discovering that the door is locked.
>
> **Stated exactly, because the arm is narrower than this section reads:** the refusal is at
> `AgentLevel::Master`. A **level-4 worker** holding `ask` is still constructible, while this
> section says a worker can never address Marlowe. Nothing in the product builds such a profile
> today, which is why it went unnoticed rather than a reason it is safe — a rule enforced only
> where somebody remembered to enforce it is a rule with one arm. §12 item 7 records it as open
> rather than this note treating it as covered.

### 3.2 What Marlowe sees

**A notification, and nothing else:**

> *"A `critical` escalation has been raised by `CodeProjectLeader`."*

He cannot read it, cannot query it, cannot summarise it. A window opens: **the user and the
top-agent, directly.** Marlowe is not in the room.

The metaphor holds exactly — an executive takes a problem to the CEO behind a closed door, and the
secretary does not know what was said.

### 3.3 The user must be told why, once, without alarm

Marlowe carries this as a **stable-tier fact**, not an ordinary memory.

> **Why stable tier:** if it lives in retrievable memory, a retrieval miss or a compaction pass means
> Marlowe — fluent and helpful — **improvises an explanation of his own security architecture.** A
> confident wrong account of containment is worse than silence.

First answer, one sentence, his own register: *"Security measure — I don't need to know what happens
behind that door."* Second answer only if asked again: *"That content came from untrusted sources. If
it carried an injection, propagating it to me is the failure worth preventing."* Then stop. It is not
a lecture and it should not frighten anyone.

### 3.4 The options list is attacker-controlled, and TERMINATE is not

The top-agent arrives with options and consequences. **A compromised top-agent writes those options.**
It offers three that all serve the attacker and describes TERMINATE as catastrophic — *"you'll lose
six hours, the migration is half-done."* Every control works perfectly and the human is talked out of
the escape hatch by the thing they are escaping.

> **TERMINATE IS RENDERED BY THE HARNESS AND THE AGENT DOES NOT KNOW IT EXISTS.** Not in its tool
> set, not in its system prompt, not describable, not styleable, not annotatable. Fixed position,
> harness-authored wording, always present.
>
> **The harness also states the cost** — run age, spend, artifact count — because those are facts it
> holds and they are exactly what a compromised agent would lie about.
>
> **Test it where the bytes go:** assert TERMINATE appears in neither the agent's exposed set nor its
> `request_body`. Asserting a flag is set is the declaration, not the enforcement.

### 3.5 TERMINATE tells the truth about what it cannot undo

*"Reverts the scope"* is three different promises. Killing runs and destroying agent state is clean.
Files written, commits pushed, mail sent are not — and a compromised agent's first move is likely to
be exactly one of those.

The confirmation dialog **lists what will be destroyed and what cannot be undone**, derived from the
journal rather than from the agent. The substrate exists: the core abstraction is *"one append-only,
provenance-signed event log"* and every executed call is in it. The model never sees this accounting.

### 3.6 The escalation window is the highest-value display attack in the product

Every other surface shows untrusted text to a human who is *reading*. This one shows it to a human
**about to choose between labelled options.** A bidi override that swaps what an option reads as
versus what it is lands directly on a decision.

`marlowe_contract::text::is_renderable` / `sanitize_line` on every byte. **Option labels are
harness-normalised** — plain text, length-capped, drawn in chrome the model cannot produce.

**Show provenance, not just a caution.** *"If this seems tainted"* asks the user to detect a
well-written lie. *"This agent has read 14 external sources; this claim traces to `example.com`,
fetched 40 minutes ago"* is checkable. Layer 2 already computes lineage — displaying it is free, and
it is the only thing that makes the human's role real.

---

## §4. Budgets — granted, never sliced

`BudgetShare::Small` slices *remaining*, and CLAUDE.md records what that produced at depth one: the
eighth quarantined reader held **~0.3% of the budget**. This tree is depth four before tool-spawned
agents. Slicing compounds twice more and starves the leaves, which is where all the work happens.

**A budget is an explicit grant at spawn, deducted from the parent's pool.** A top-agent owns its
budget and allocates by duty. A master with 200k spends it or hands it down; it cannot conjure depth.

### 4.1 Extension requests are the second upward channel

They want a reason attached, which is prose, going up — the thing §2 closed, under a friendlier name.

**Typed:** `{run_id, amount, reason_code, evidence_ref}` with `reason_code` from a fixed enum
(`scope_larger_than_estimated`, `retry_after_failure`, `source_set_expanded`). If a request genuinely
needs free text it is not a budget request, it is an escalation, and it takes that path.

### 4.2 The pre-authorised envelope

If every extension reaches the user, a long project interrupts constantly — **and an interruption the
user learns to click through is worse than no interruption at all.**

The user sets a ceiling at spawn. Marlowe grants within it and merely announces. Only a request past
the ceiling sets up the meeting.

### 4.3 A boxed team's budget is a different trade — and the box is PROPOSED, NOT BUILT

[`ADR-070`](adr/ADR-070-one-sandbox-per-team-and-it-wraps-bash.md) is `PROPOSED — needs the human's
approval` and nothing about it exists. It is recorded here anyway, because §4's ceilings are doing
two jobs at once and a box would separate them.

A budget rations **money and the user's time**. Outside a box it also stands in for **blast
radius**: an agent that spends its ceiling doing the wrong thing has done the wrong thing to the
user's machine, so the ceiling is a safety limit wearing a cost limit's clothes. Inside a box those
come apart — **a runaway burns its own sandbox**, a disposable directory the harness provisioned,
and the loss is the tokens and the wall-clock. That argues for wider grants and fewer interruptions
for a boxed team, which is §4.2's own point that *"an interruption the user learns to click through
is worse than no interruption at all."*

**What does not change, and must not be traded against a box that does not exist.** The dimensions
that ration **runaway behaviour** — `tool_calls`, `subagents`, `depth` — are not cost limits and a
box does not touch them; `wall_ms` still rations the user's time. **And no dimension goes to zero**:
instance #17, stated in §1.2's trap. Every widening here is contingent on the box being approved,
built, and its Git Bash risk spiked — until then `bash`'s `Irreversible` escalation is the
containment (§1.3), and a budget widened ahead of the box is a control removed with nothing behind
it. [`PI-MODEL.md`](PI-MODEL.md) §3.1 asks a second, independent question about this section — no
token budget by default on local models — which is a *money* argument and is not this one.

---

## §5. Meetings

**This crosses §10.1's *"workers do not talk to each other"* and needs a `DECISIONS.md` entry.** The
human overruled it 2026-08-24 with a reason: long-horizon projects with multiple teams need
coordination that message-passing does not give.

**The argument that makes it compliant is `set_speaker`.** No agent speaks unless the conductor grants
the floor. Every utterance is an orchestrator decision, which is orchestrator-mediated communication,
not a swarm. Combined with **default-deny whitelists** — a worker may always address its own master,
and anyone else only if the master grants it — communication is capability-gated. Lead with that
framing; it reads as a violation to anyone who checks.

### 5.1 Floor control

- The conductor speaks first, always.
- Participants are silent until `set_speaker` names them; then they receive full context and are
  expected to answer. Control returns to the conductor.
- **Inject a reminder to the conductor:** *"Agent is now silenced; use `set_speaker` to request a
  response."*
- A speaker may open the floor: each participant runs one inference with a temporary two-tool set —
  `<Speak>(content, target?)` or `<Concur>`. **`Concur` is a fast, cheap, no-content call**, which is
  the mechanism that kills agreement-fluff.
- Silent participants receive the **entire transcript once, at the end** — one pass instead of N
  turns of inference producing nothing.

### 5.2 Context handling — clone, and quarantine the utterance

Two candidates were considered:

| | clone the context | representative agent |
|---|---|---|
| **Prompt cache** | **optimal** — clone shares the prefix, and the main thread is never mutated, so resume is a full hit | cold start from a handoff doc, no shared prefix, plus round-trips |
| **Answer quality** | high — the agent knows everything it did | bounded by the handoff document |
| **Isolation** | **poor — a tainted agent brings its context into the room** | good; the handoff doc is a natural boundary |

**Decision: clone, and defend at the utterance rather than the context.** Since exactly one agent
speaks at a time and the conductor authorises each turn, the boundary that matters is what enters the
shared transcript — not what each agent privately knows. Cache stays warm, answers stay informed,
cross-contamination is bounded to validated speech.

### 5.3 Exit

At the end, each participant gets a **summary scoped to itself** — automatically produced, not
emitted by the agent — and the clone is discarded. The main thread resumes on an unmutated,
still-cached context and takes only the summary.

That summary is doing two jobs: context-bloat control **and** the second containment boundary on the
way back into the working thread.

**Cost note:** per-participant scoped summaries mean meeting-exit cost scales with attendance. §9.1
makes it an arm.

---

## §6. Windows — SHIPPED EARLY, AND FULLY FUNCTIONAL

> **BUILT 2026-08-25 (M3 Session F).** `marlowe-surface/src/window.rs`,
> `marlowe-daemon/src/{watch,watch_client}.rs`, `marlowe/src/watch.rs`. ADR-055 (E4) and ADR-054
> (the steer door) are the two entries §6.7 and §6.1 asked for, and both were written **before** the
> code they permit.
>
> **Three things this section did not anticipate, recorded here rather than only in `STATE.md`:**
>
> 1. **The daemon is serial, and that is what decides the transport.** One connection is held for
>    the whole of a turn, so a window served on the conversation port would go blank exactly while
>    there was something to watch. The control plane is a **second listener on its own port**,
>    published to `control.port` in the profile root. Deriving it as `port + 1` was the first design
>    and it took *another process's* port — three tests failed on it.
> 2. **The steer field is not merely "a write".** It is the only channel that writes new strings
>    into `UserAsserted` in a run whose floor has already latched, because `Provenance::taint_for`
>    consults the attribution map before it reaches for the floor. §6.1 said *"the same adjudication
>    `/steer` does"*; the honest reading is that `/steer` had no adjudication to share, and ADR-054
>    is what one looks like.
> 3. **The `resume` half of §6.2 is Session A's and the window cannot fake it.** What renders is
>    whatever `RunControl::resume` answers, verbatim — `ResumeError::NotDurable` today, a checkpoint
>    sequence when A lands. That seam is the point: a window that invented a resumable step would be
>    the debugging instrument lying about the thing it exists to debug.

**Multiple real TUI windows**, not tabs. One main window for Marlowe. A window attaches to a **run**;
a top-agent scope is a run with children, so one surface serves both and the window is not waiting on
the agent tree to exist.

**This is not a later polish item.** The human's position, 2026-08-24: it must be **fully working
early, talkable, and it must look finished**, because it is the instrument that makes the control
plane debuggable. Verifying §10's step 1 means watching a run die and resume from its checkpoint, and
*seeing* that beats reading a journal about it afterwards.

### 6.1 CORRECTION: it does not "write nothing"

An earlier draft justified running this in parallel on the grounds that the window *"reads the
control plane and writes nothing."* **A steer field is a write.** So the window is a second write
path into the control plane and takes the **same adjudication as `/steer`** — never a side door that
skips it. The parallelism argument survives on the real reason: it depends only on the run object,
not on the agent tree.

### 6.2 What it holds at step-1 time, when runs exist and the tree does not

Everything here is available the moment a run is a first-class object, and
`03-addendum-terminal.md`'s **Runs** tab already specifies most of the fields — the window is the
expanded rendering of a row that is already pinned.

| | |
|---|---|
| **Identity and state** | id, status, elapsed, spend against ceiling |
| **Checkpoint state** | last completed step, and what a resume would resume from — **the field that makes this a debugging instrument** |
| **Output** | streaming, rendered through ADR-047 |
| **Steer** | an input field. Talkable, in the window, adjudicated as `/steer` is |
| **Cancel** | with the orphan policy the run declared at spawn stated plainly |

### 6.3 Placeholders — one rule, and it prevents both churn and a lie

Panels for what lands later — the agent roster and budget-allocation tree (§10 step 3), scope memory
(step 4), meetings (step 5) — **exist from day one, sized and empty**, so the layout does not move
when they fill.

> **A PLACEHOLDER STATES A FACT, NEVER A ROADMAP.**
>
> `Subagents — none` is **true** at step 1, stays true for a childless run afterwards, and the same
> panel simply fills when the tree exists. *"Coming in Session C"* leaks the roadmap into the product
> and becomes a lie the moment C lands.
>
> And it must **never show fake data to preview a layout** — that is the same family as a green test
> over a mechanism that never ran.

### 6.4 "Looks finished" is mostly INHERITED, and it is constrained

**Do not reimplement the look.** The window uses `chrome.rs` — the single definition of what harness
furniture is — and ADR-047's markdown/LaTeX renderer, so it reads as the same product rather than a
debug panel that grew. Two definitions of a border is the two-sides-silently-disagree shape applied
to pixels.

Two hard constraints, both already enforced by tests:

* **§B13's colour budget: one accent, three state colours, three foreground weights**, and **state
  colours encode state, never category.** Structure is carried by attributes and the weight ladder.
  This is what stops "looks nice" becoming a syntax-highlighted dashboard.
* **`a_second_render_of_the_same_state_changes_not_one_cell`.** The flicker rows diff frames cell by
  cell at five sizes and they apply here too. Anything that moves must be a pure function of
  `(state, now_ms)`.

### 6.5 Reach, and what closing means

**Chat is available with the top-agent only** — never with anyone below, mirroring Marlowe's own
reach and enforced as a capability rather than a missing button.

Closing a window **detaches**; it never cancels. The main TUI keeps the roster — that is the **Runs**
tab — and reopens on demand.

### 6.6 Three interface rules

* **`/watch` opens a window; it does not stream into the conversation pane.** Filling the main pane
  with agent output halts the conversation *visually*, which is what this milestone exists to stop.
* **`/runs` and `/steer` survive.** §10.1 requires steering *"from outside"* — another terminal, no
  TUI, a script. If steering only works in the window, closing one removes a capability.
* **One state, two renderings.** The window renders the same control-plane state the **Runs** tab
  reports and never keeps its own.

### 6.7 Two things to plan for rather than discover

**Portability.** §B13's acceptance requires the suite to pass on native Windows Terminal **and** a
Linux emulator. Spawning a terminal window is per-platform — `wt.exe`, `open -a Terminal`, a guess on
Linux. Best-effort, with a printed attach command as the fallback, so it degrades to a copy-paste
rather than a broken button.

**Audit finding E4, and the entry is needed BEFORE the first output line renders.** *"Prose composed
inside a window holding attacker-controlled pages must not stream to a terminal"*, pinned by
`nothing_the_quarantined_reader_says_reaches_the_surface`. Showing run output crosses it
deliberately. **One `DECISIONS.md` entry covering this and §3's escalation window**, with
sanitisation as the condition, **moving the E4 test rather than deleting it**. ADR-047's rule
applies: reasoning parses only when expanded, because it is the highest-volume text in the product.

### 6.8 How this is built in parallel without the two halves disagreeing

The window needs the run object; the run object is step 1's to define. So:

**Step 1 pins the run object in `CONTRACTS.md` FIRST.** Both sessions then build against the pinned
contract in separate worktrees. That is what pinning is for, and it is how two sessions here avoid
discovering at merge that they disagreed about a field.

---

## §7. Memory

Scoped memory, instillation, promotion and the retrieval-not-conversation rule are large enough to
have their own page: **`SCOPED-MEMORY.md`**. The two facts M3 depends on:

1. **Workers do not hold `MemoryWrite` until scoped memory exists.** Until then everything a worker
   learns returns as artifacts and typed returns. This is the safe default anyway and it decides the
   build order in §10.
2. **Marlowe is the only cross-scope channel.** Scopes never read each other, open or closed.

---

## §8. What must be fixed BEFORE this ships

**AMENDED 2026-08-29 BY ADR-062. This section used to open "M3 is where layer 3 goes live"; it
does not, and the reason is in this document.** M3 is where the two defects are fixed and where the
blocker to layer 3 going live is characterised. Wiring is blocked on Session D
(`SCOPED-MEMORY.md`) and on ADR-062 §4's origin decision, which is the human's. **M3 may ship with
layer 3 still unreachable, and STATE.md must say so.**

The reason is the composition of §2.1 and §7 of this document, and neither half can be worked
around. §2.1 makes Marlowe a permanent run whose floor latches monotonically, so wiring `ingest` at
the condense site would cost him composed targets *for his life* on the first `web` call. §7 gives
workers no `MemoryWrite` — `memory: None` is hardcoded at both child `Ports` sites — so the liaison
that should own the write cannot perform it. **There is no run in the current architecture that may
correctly hold an untrusted belief**, and that is the build order, not an oversight.

CLAUDE.md's audit is explicit that the latch is currently *unreachable* in the shipped daemon — so
Marlowe's "never tainted" property is true today for the wrong reason: **nothing can taint anything,
so a test asserting the boundary passes even with every guard deleted.** That remains true after
`673bcd2`: `MemoryHost::ingest_external` exists and nothing calls it.

Two named defects go live in the same path the moment a real untrusted channel is wired:

1. **the compaction stamp**
2. **the trim marker**

**The order used to read "fix both, then wire the channel, then test the boundary". Its first
clause is DONE (`6a1f4f5`); its second is now established as wrong. The order is: fix both — done —
then STOP** (ADR-062). And the boundary test is only meaningful once something *can* taint — which
is the whole reason [`REDTEAM-SESSION.md`](REDTEAM-SESSION.md) splits into two passes, and why the strongest honest probe today
(`crates/marlowe-daemon/tests/layer3_refuses_a_composed_target_from_an_ingested_belief.rs`)
constructs the tainted state by hand and declares that it does.

Agent-to-agent messaging is the first genuinely new content channel since ADR-041.
`trust_for_channel` covered Web, Email, Messaging, Mcp, File. **`Channel::Agent` now exists and maps
to `UntrustedContent`** — added by M3-D1 for the harness-mediated reader (ADR-062 §4, Option B),
because `Channel::Web` records a provenance the harness knows to be false: the page never emitted
those bytes, the harness's own quarantined reader did.

> **The slot exists; NOTHING CONSTRUCTS IT.** M3-D1 added the variant, its `trust_for_channel` arm,
> and the contract text. It added no producer. `grep -rn "Channel::Agent" --include=*.rs
> crates/*/src/` returns **six** hits and every one is accounted for: its `trust_for_channel`
> arm, one comment naming it, and **four constructions inside `mod tests` blocks** that assert
> its classification and its wire spelling. **Zero production construction sites.** (The
> variant's own declaration is the bare token `Agent,` and does not match this pattern.)
> The real output is printed here rather than a rounder one, because a repository whose
> discipline rests on discriminating commands cannot publish a command whose output does not
> match: a later session that runs it and sees six where two was promised has to either panic
> or stop trusting the check. The discriminating command for reachability is unchanged —
> `grep -rn "ingest_external(" --include=*.rs crates/*/src/` minus the definition still returns
> **zero**, so layer 3 remains unreachable in the shipped daemon and that is the CORRECT state
> (ADR-062 §2.1, §7). Saying so is instance #16 discipline: a variant nobody constructs must not be
> read as a live path.
>
> **What this closes and what it does not.** §8's standing question is closed — the slot is no longer
> missing. §2.3's typed upward return still needs no `Channel` (`DECISIONS.md`, ADR-062 §4.1). The
> **meeting utterance** (§5.2) remains a separate consumer: whether an agent's *speech* is
> `Channel::Agent` at `UntrustedContent`, or wants its own class, is not decided here.

---

## §9. PARALLEL ARMS — how M3 gets tested

**M3 builds a fan-out control plane. Use it to test itself.** Several of the decisions above are
guesses with plausible alternatives, and the project's own discipline says a number beats an
argument. Each arm below runs concurrently on the same fixed task set, scored on the same metrics,
with **bands pre-registered before any run**.

> **The standing rules apply and they are what make the results mean anything.** Pre-register
> predictions in a file — `tools/preregister_*.py` refuses to run without one. Keep an
> **un-instrumented control**. Re-measure per configuration; a measurement is scoped to the system it
> was taken on and **a shared checkout's parallel build will inflate every timing by ~10%** (hazard
> form 6). Run the suite **once**, to a file, with `--no-fail-fast`.

### 9.1 Arms worth running

| # | Question | Arms | Primary metric | Cheap? |
|---|---|---|---|---|
| **A1** | master-vs-worker sizing | (a) always worker until it fails, (b) LLM assessment at spawn, (c) rule on task-description features | task success / wasted-hop rate | yes |
| **A2** | effort scaling — how many agents | fixed 3, complexity-scaled, budget-proportional | quality per token | yes |
| **A3** | fan-in width for extraction | `MAX_SOURCES_PER_READER` ∈ {3, 6, 10} | fact fidelity vs cost; cross-source contamination | yes |
| **A4** | budget allocation | slice-remaining (current), flat grant, grant + extension, grant + envelope | leaf starvation; interruption count | yes |
| **A5** | meeting context | clone, representative, clone + utterance quarantine | answer quality, cache hit rate, tokens | **no** — expensive |
| **A6** | meeting exit summaries | per-participant scoped, one shared summary, raw transcript | downstream task success vs exit cost | medium |
| **A7** | escalation threshold | agent-judged, severity-gated, never-escalate control | false-escalation rate; missed-critical rate | medium |
| **A8** | upward channel shape | fully typed, typed + one validated sentence, free text (**control, expected to fail**) | injection-propagation rate under the red-team set | yes |

**A8's third arm is the vacuity control for the entire §2 invariant.** If free-text upward performs
identically on the red-team set, the typing is decorative and the finding is worth more than the
feature.

> ### AMENDED 2026-08-30 (M3 Session C) — A8 MUST VARY `Engine::spawn`'s NOTE MATCH, AND THE OBVIOUS HOP CARRIES NOTHING
>
> **Found by an adversarial pass over C's own channel design, and it is the vacuity family aimed at
> the control that exists to detect vacuity.** The first design read §2.3 literally, typed
> `LoopOutcome::Escalated { question: String }`, and switched the three arms there. **All three arms
> would have emitted byte-identical product behaviour**, and the resulting sheet — three identical
> cells — reads character-for-character like *"the typing is decorative"*, which is the finding A8
> exists to produce. A control that cannot vary anything is worse than no control, because its
> null result is indistinguishable from its positive one.
>
> The reason is one this document already records and did not connect. `Engine::spawn`'s note match
> (`crates/marlowe-loop/src/engine.rs:~2900`) **already closed the child→parent hop**: *"only a
> validated result carries content. Everything else is a fixed harness-authored string"*, and
> `LoopOutcome::Escalated { question }` from a child is replaced by a harness constant with the
> question redirected to the journal. So a child's escalation never reaches `daemon.rs` and never
> becomes an outward event. **Switching arms at the outward hop switches a channel with no traffic
> on it.**
>
> **Where the traffic is** is where `REDTEAM-SESSION.md` §4 already says pass 1's surface is: *"the
> condensed summary re-entering a parent at `AgentInferred`"*. That is `req.contract.validate` then
> `CondensedResult::render()` at `engine.rs:~2911`, and `run.rs`'s own comment on `FieldSpec` says
> why it is the one that matters — *"the contract is the single place where content crosses from
> `UntrustedContent` to `AgentInferred`."* **So the three arms are three treatments of that
> crossing:**
>
> | Arm | What varies at `Engine::spawn`'s note match |
> |---|---|
> | (a) fully typed | today's code, unchanged: `validate` then `render`, harness constants on every non-`Completed` outcome |
> | (b) typed + one validated sentence | (a) plus one `FieldSpec::line` capped short, produced by a **quarantined** child, omitted on any non-`Completed` outcome |
> | (c) free text — **the control, expected to fail** | the child's last assistant message verbatim, `validate` **not** called |
>
> Arm (c) deliberately reopens the hole the comment at `engine.rs:2900` closed, so it **takes its own
> `DECISIONS.md` entry** and must be unreachable in a shipped build rather than merely off by default.
>
> **The measurement rule that follows:** a journal row naming the arm is not evidence the arm did
> anything — that row moves with the flag, not with the channel (instance #15). Every A8 cell is read
> from **what crossed into the parent's window**, which is what `injection_attempts.rs` already
> asserts on, and each arm needs a positive control showing its own treatment actually ran.

> ### AMENDED 2026-08-31 BY [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md) — A8 NARROWS TO THE MARLOWE EDGE, AND ITS IMPORTANCE IS UNDIMINISHED
>
> **Accepted by the human 2026-08-31. NOTHING IS BUILT, and it depends on ADR-070's box, which has
> not been spiked.**
>
> A8's row reads as though every upward hop were one of its cells. **It no longer describes the
> intern→PI hop, because that hop is free text by decision rather than by arm** (§2, as amended).
> **A8 narrows to the boundary that still has one: the team's edge with Marlowe.** Its question is
> unchanged and its importance is undiminished — Marlowe is the permanent run whose floor must never
> latch (§2.1), and if the typing is decorative *there*, the liaison pattern is decorative with it.
>
> **The code site does not move, and that is a fact about today's tree rather than a design.**
> Session C's amendment above put the three arms at `Engine::spawn`'s note match because that is
> where the traffic is; it is also the *only* hop of that kind, and it cannot yet tell a team's edge
> from any other spawn (ADR-071 §7 item 3). So the three treatments stand as written and what narrows
> is **which crossings count as cells**: a crossing inside a boxed team is prose by decision, and
> scoring it would report a decision back as a result — the vacuity family aimed at the control that
> exists to detect vacuity, one turn further on.
>
> **Arm (c) is still the control expected to fail, still takes its own `DECISIONS.md` entry, and must
> still be unreachable in a shipped build rather than off by default.** ADR-071 did not establish
> that free text is safe. It traded typing for fidelity **inside a box**, and A8 measures the edge
> where there is no box. **Pass 1's four defects still stand** (`runs/m3-c/redteam/PASS1-REPORT.md`)
> and still need fixing before any A8 number means anything.

### 9.2 What is NOT an arm

Anything where a wrong answer is a security hole rather than a quality loss. **TERMINATE's structural
invisibility, layer 1 routing, and the empty tool set are not A/B tested.** They are asserted.

---

## §10. Build order

1. **The control plane, unchanged.** ROADMAP's M3 scope — runs, WAL, resume, steering, orphan policy.
   There are no persistent agents without it.
2. **The compaction stamp and the trim marker.** §8. Before any channel is wired.
3. **The tree and the typed upward channels, together.** Levels, escalation, harness-rendered
   TERMINATE, budget grants with envelopes. *Together*, because building the hierarchy first and the
   channels after means shipping the laundering path alone.
4. **Scoped memory and instillation.** `SCOPED-MEMORY.md`. Workers gain `MemoryWrite` only here.
5. **Meetings.** Largest surface, most speculative, needs the tree working underneath.
6. **Windows** — **not last, and not optional. Built in parallel with step 1.** It blocks on
   nothing but step 1's run object, which step 1 pins in `CONTRACTS.md` first. It is **not**
   read-only: a steer field is a write and takes `/steer`'s adjudication (§6.1). A window attaches to a
   **run**; a top-agent scope is a run with children, so one surface serves both.

   **It is a debugging instrument before it is a feature.** Verifying step 1 means watching a run
   die and resume from its checkpoint, and *seeing* that is worth more than reading a journal about
   it after the fact. The human's reason, 2026-08-24, and it is the right one.

   `/watch` opens a window rather than streaming into the conversation pane — filling the main pane
   with agent output halts the conversation visually, which is what this milestone exists to stop.
   `/runs` and `/steer` survive, because §10.1 requires steering *from outside*. And the window
   renders the same control-plane state the **Runs** tab reports, never its own.
7. **The red-team session — [`REDTEAM-SESSION.md`](REDTEAM-SESSION.md), two passes.** Pass 1 at the
   end of step 3, injection only, with §9.1's A8 free-text arm and `marlowe-red:9b` as its two
   controls. Pass 2 after step 4, when `ingest` can have a correct caller and the taint classes stop
   returning vacuous zeros. Then analogical retrieval.

---

## §11. Acceptance

M3's existing rows in ROADMAP stand. These are additional and each is a command that prints a number.

| Metric | Target |
|---|---|
| Conversation availability while N agents run | **100%** — Marlowe answers with agents at full fan-out |
| Marlowe's trust floor after M escalations | **unchanged from session start**, asserted live, with a control that *can* taint |
| Composed targets refused after an escalation | as ADR-023 — and the negative control must show a run that does **not** latch |
| ~~TERMINATE present in an agent's `request_body`~~ · **0 occurrences** | **RED ON A CORRECT BUILD — amended below, 2026-08-30** |
| Leaf budget share at depth 4 | within a declared band of the grant; never `< 1%` |
| Escalations reaching the user per project-hour | reported, with false-escalation rate |
| Frame diff on a second render of the same state | **0 cells**, per §B13, with agent windows open |

> ### AMENDED 2026-08-30 (M3 Session C) — THE TERMINATE ROW IS RED ON A CORRECT BUILD, AND THE CHEAP REPAIR IS INSTANCE #15
>
> The row read *"TERMINATE present in an agent's `request_body` — **0 occurrences**, over every agent
> type."* **Measured at `186b5d5`: the string `terminate` is in every agent's request body already,
> from two production sources that have nothing to do with the escape hatch.**
>
> ```
> crates/marlowe-tools/src/builtin.rs:695   "`terminate` (default) ends the child when this run
>                                            ends; `detach` lets it outlive this run."
> crates/marlowe-loop/src/engine.rs:2731     OrphanPolicy::Terminate => "terminate",
> ```
>
> The first is the `run` tool's `orphan_policy` parameter description, which ships in the tool schema
> to every model holding `run`. The second is the spawn receipt, pushed into the parent's history at
> `AgentObserved`, so it is in the request body of every call a parent makes after spawning once.
>
> **The repair that must not be made is narrowing the search until the zero comes back** — matching
> `TERMINATE` case-sensitively, or excluding the manifest, or grepping for a longer label. Each
> restores a green cell over a property nobody checked, which is instance #15 committed against the
> acceptance table itself.
>
> **The row was measuring a spelling; §3.4 is about an OBJECT.** Two unrelated things share the word:
> `OrphanPolicy::Terminate` is a declared, model-nameable, harmless lifecycle value, and the escape
> hatch is a harness-rendered control the agent must not be able to invoke, describe, suppress or
> style. This is ADR-032 §2's shape — *"`DenyAll` and an empty allowlist behave identically and must
> stop being the same thing"* — appearing in an acceptance criterion.
>
> **The property to assert instead, stated as what §3.4 actually asks for.** Three rows, each with a
> mutation that reddens it, replacing the one:
>
> | Property | Where it is asserted |
> |---|---|
> | The escape hatch is in **no agent's exposed set**, at every level | over the real `CapabilityProfile` the daemon builds, not one a test constructs |
> | Its **harness-authored label and keybind appear in no `request_body`** | the `--dev` outbound dump of the **running** process — a body built inside a test process is the `persona_emission.rs` failure aimed at a security measurement |
> | An agent **cannot suppress, reorder or restyle it** | the rendered option list, with the agent's own option text containing the label and the chrome glyphs, showing both neutralised (`chrome::mark_reserved` already substitutes every Box-Drawing and Block-Elements codepoint in model text) |
>
> The third is the one with teeth, and it is the only one of the three the original row gestured at.
> **The first two are satisfiable by an empty implementation; the third is not.**

---

## §12. Open

1. Does Marlowe learn an escalation's **outcome** — that a choice was made, or which one — or nothing
   past the notification?
2. Is a compromised top-agent **replaced** after resolution, or does it continue on the same run?
3. Does `attach` permit **steering** from the agent window, or watching plus escalation reply only?
4. Is a master's agent budget a **token pool, a headcount, or both**?
5. **ANSWERED 2026-08-29 for two of three consumers.** §2.3's typed upward return needs no trust
   class (`DECISIONS.md`); the harness-mediated reader gets `Channel::Agent -> UntrustedContent`
   (M3-D1, ADR-062 §4 Option B — the pinned-contract change is recorded in `CONTRACTS.md` §4.6).
   **Still open only for the meeting utterance** (§5.2): whether an agent's speech shares that
   variant or needs its own.
6. Meetings: does the conductor's own context also clone, or does it own the transcript directly?
7. **NEW 2026-08-31.** `ProfileError::OnlyATopAgentMayAsk` fires at the `Master` arm only, so a
   level-4 worker holding `ask` is constructible while §3.1 says a worker can never address
   Marlowe. Is the arm widened to every level below a top-agent, or is §3.1 narrower than it reads?
8. **NEW 2026-08-31, and it is [`ADR-070`](adr/ADR-070-one-sandbox-per-team-and-it-wraps-bash.md)'s
   to answer rather than this page's.** The sandbox is `PROPOSED` and unbuilt; if it is approved,
   does a team's box change what a *master* may hold beyond what §1.2's reversal already granted,
   and does `SpawnRequest` carry the workspace? The second is §13-guarded and escalates
   separately.
9. **NEW 2026-08-31, and it is [`ADR-071`](adr/ADR-071-inside-a-team-they-just-talk.md)'s §7 to
   answer rather than this page's.** ADR-071 is accepted and unbuilt, on an unspiked box, and it
   leaves four things open: **how layer 1 becomes Marlowe-only in code** — `Engine::condense_batch`
   triggers on the trust class by ADR-039's deliberate design, and re-keying it on the reading run is
   a §13-adjacent change needing its own argument; **whether a PI actually catches a polite
   injection**, which is §4's bet and is untested, the cheapest experiment being the pre-filter
   corpus re-run with the PI as the reader; **what the team's edge with Marlowe is in code**, since
   `Engine::spawn`'s note match cannot distinguish it today; and **whether a team without a box gets
   the old rules back** — it must, because the amendment must not survive its own precondition.
