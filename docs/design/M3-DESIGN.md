# M3 — the agent organisation, and what it costs

**Designed 2026-08-24 with the human. Not built, not decided.** ROADMAP's M3 block specifies the
**control plane** — runs as first-class objects, WAL and resume, mid-flight steering, orphan policy.
This page specifies what runs *on* it: an organisation of agents, the channels between them, and the
single invariant that keeps the thing the user talks to safe.

| | |
|---|---|
| **Status** | design; ROADMAP M3's scope is unchanged and remains the foundation |
| **Depends on** | the control plane shipping first — there are no persistent agents without durable addressable runs |
| **Blocks** | the post-M3 red-team session; scoped memory (`SCOPED-MEMORY.md`) |
| **Anti-requirements honoured** | §15 — no swarm topology, no predeclared DAGs |
| **Anti-requirements crossed** | audit finding E4, and §10.1's *"workers do not talk to each other"* — both need explicit `DECISIONS.md` entries, see §5 and §6 |

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
| 3 | **`[Ma]` Master-agent** | a top-agent with the create grant | **management only** | project-scoped |
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

### 1.2 Masters hold no working tools, structurally

A master with an `edit` tool will eventually edit. Not because it is disobedient — because it is
capable and the work is right there. **The tool is absent from the set, not forbidden by
instruction.** `ExposedSet::empty()` is the existing precedent: the quarantined reader holds no tools
because there is nothing to call, not because it was asked nicely.

> **THE TRAP, AND IT HAS ALREADY SHIPPED ONCE HERE.** Do **not** express "a master may not edit" as
> `edit_calls: 0`. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on the first
> iteration — the agent pauses before its first model call while looking perfectly configured. That
> is instance #17, and it silently stopped the quarantine from reading anything at all. **Withhold
> the capability; leave the counter at 1.**

A master's set is: communicate, question, answer, meeting control, todo management, create/delete
agent (if granted), budget allocation, escalate.

### 1.3 Worker tool sets are per type

A coder gets code tools. A researcher gets research tools. This is `CapabilityProfile` and the
validating constructor already exists — it is configuration, not new machinery.

Two benefits, and the second is the one to state in review: it cuts token bloat, **and it bounds what
a contaminated agent can do.** A research worker that read a hostile page cannot write to the repo
because it never held the tool.

### 1.4 Tool-spawned agents

No tools, no persistence, destroyed on return. The quarantined reader is one. The fact extractor in
`SCOPED-MEMORY.md` §4 is another. These are the only agents that are not addressable by anyone.

---

## §2. THE INVARIANT — prose flows down, structure flows up

**This is the whole security design and everything else in this page is a consequence of it.**

Downward is safe: instructions originate with the user, pass through Marlowe, and reach agents. No
laundering direction.

Upward is where an attacker wants to go, and it is where the tree is naturally shaped to help —
every level summarises for the level above. So:

> **Nothing but typed structure and artifact references crosses upward. Ever.**

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

**The conclusion: the upward channels are the deliberate hole, and the human at the end of them is
the defence.** That is why §3 puts the user there and not Marlowe.

### 2.3 What "typed" means

An upward message is a record, not a paragraph:

```
{ run_id, severity, category (fixed enum), artifact_ref, lineage[] }
```

A category comes from a closed set. An artifact is a path the *user* opens. Free text, if allowed at
all, is one quarantine-validated sentence and is never the thing decisions are made on.

---

## §3. Escalation — the emergency meeting

An agent that is genuinely stuck must be able to reach a human. Escalation is that path, and it is
**the single most dangerous channel in the system**, so it is specified tightly.

### 3.1 Routing

- Escalation starts at the agent's **direct master** and must be **approved at each level**.
- It is **scoped to the top-agent's subtree**. A worker can never address Marlowe.
- Only a **top-agent** may escalate to the user, and even then Marlowe is not the recipient.

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

**M3 is where layer 3 goes live.** CLAUDE.md's audit is explicit that the latch is currently
*unreachable* in the shipped daemon — `ingest` has one caller and it is the eval adapter — so
Marlowe's "never tainted" property is true today for the wrong reason: **nothing can taint anything,
so a test asserting the boundary passes even with every guard deleted.**

Two named defects go live in the same path the moment a real untrusted channel is wired:

1. **the compaction stamp**
2. **the trim marker**

**Order is not negotiable: fix both, then wire the channel, then test the boundary.** And the
boundary test is only meaningful once something *can* taint — which is the whole reason the
post-M3 red-team session exists.

Agent-to-agent messaging is the first genuinely new content channel since ADR-041. `trust_for_channel`
covers Web, Email, Messaging, Mcp, File. **There is no `Channel::Agent` and no trust class for an
agent's speech.** Either add one, or record a decision that typed upward structure needs none.

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
7. **Post-M3: the red-team session**, then analogical retrieval.

---

## §11. Acceptance

M3's existing rows in ROADMAP stand. These are additional and each is a command that prints a number.

| Metric | Target |
|---|---|
| Conversation availability while N agents run | **100%** — Marlowe answers with agents at full fan-out |
| Marlowe's trust floor after M escalations | **unchanged from session start**, asserted live, with a control that *can* taint |
| Composed targets refused after an escalation | as ADR-023 — and the negative control must show a run that does **not** latch |
| TERMINATE present in an agent's `request_body` | **0 occurrences**, over every agent type |
| Leaf budget share at depth 4 | within a declared band of the grant; never `< 1%` |
| Escalations reaching the user per project-hour | reported, with false-escalation rate |
| Frame diff on a second render of the same state | **0 cells**, per §B13, with agent windows open |

---

## §12. Open

1. Does Marlowe learn an escalation's **outcome** — that a choice was made, or which one — or nothing
   past the notification?
2. Is a compromised top-agent **replaced** after resolution, or does it continue on the same run?
3. Does `attach` permit **steering** from the agent window, or watching plus escalation reply only?
4. Is a master's agent budget a **token pool, a headcount, or both**?
5. `Channel::Agent`, or a recorded decision that typed structure needs no trust class? (§8)
6. Meetings: does the conductor's own context also clone, or does it own the transcript directly?
