# The PI model — Marlowe is the connection to the geniuses

**Stated by the human 2026-08-31, during M3 Session C. This page is the requirement, not the
design.** It captures what was asked for while the wording is fresh, so the brainstorms that follow
are judged against it rather than against a paraphrase.

| | |
|---|---|
| **Status** | requirement captured; design in progress. **BUILT AND GREEN:** §3's tool reversal (`6e01c37`). **PROPOSED, NOT BUILT:** §3.2's sandbox (ADR-070) |
| **Overturns** | M3-DESIGN §1.2 (*"masters hold no working tools, structurally"*) — already reversed in code |
| **Amends** | M3-DESIGN §1.1, §3.1, §3.2 and §4 — see §5 below; none of those amendments is written yet |
| **Feeds** | `AGENT-DIRECTORY.md` (the ladder), `REDTEAM-SESSION.md` (pass 2's surface changes), `ADR-070` (§3.2's mechanism — **PROPOSED**) |

**The status row read *"requirement captured; design in progress, nothing built beyond §1's tool
reversal"* until 2026-08-31, and is amended rather than replaced because two things on this page now
have two different statuses and it must never let them read as one.** The tool reversal is in code
and the suite is green. The sandbox is an ADR awaiting the human — no crate, no call site, no spike
run. Every sentence below that touches either one says which it is.


> **ADR-070 WAS ACCEPTED BY THE HUMAN ON 2026-08-31, AFTER THIS PAGE WAS WRITTEN.**
> Every *"proposed"* below that names it should be read as **accepted and still unbuilt** —
> acceptance authorised the work and settled the mechanism argument; it built nothing. The
> spike that gates the implementation (does Git Bash survive an AppContainer?) has not run,
> and ADR-070's own status line says acceptance does not change that. **No document may cite
> it as evidence that agents are contained until those probes have.**

---

## §1. THE ORDERING, AND IT IS THE MOST IMPORTANT LINE ON THIS PAGE

> *"Security is a primary concern but research and knowledge comes first."*
>
> *"Security is in there to protect us from prompt injection, but it absolutely may not get to a
> point where speed/accuracy/knowledge is hurt."*

**Read that literally.** Security is a constraint, not the objective, and it must not be the binding
constraint. A design that is safe and slow has failed this brief. Where a protection would cost
speed, accuracy or knowledge, the protection is re-designed — not the goal.

**What that does NOT license.** The threat is prompt injection, and the one property that does not
bend is in §4. Everything else is negotiable.

---

## §2. The interaction, in the human's own shape

```
User -> Marlowe (Secretary)
   "This is what I'm doing, can you get it done for me?"

Marlowe
   "Yes sir, of course. Let me ask some questions to get it hammered out
    before I deploy the team."
   -> scope questions: what the user wants, and what they want to RECEIVE
   -> deploys the PI (Agent-High) with the capabilities needed to achieve it

Then, in parallel:
   * the user keeps talking to Marlowe, with NO impact on the PI
   * or the user talks to the PI DIRECTLY  (it is a top-agent, so it is reachable)
   * or Marlowe carries a message to it, or asks it for a response
```

**Four things in that sketch are new and none of them is built.**

1. **The intake interview.** Marlowe does not relay a request; he *interrogates* it until the scope
   and the deliverable are pinned. M3-DESIGN has no such phase — a spawn today is a `run` tool call
   with a `task` string. **What the user wants to RECEIVE is part of the scope**, which is the
   `OutputContract` decided with the human rather than guessed by a model.
2. **Marlowe fits the capabilities to the job at spawn.** Not a fixed per-role profile: the tool set,
   the budget and the team shape are derived from the answers to §2's questions. §1.3's *"worker tool
   sets are per type"* is a weaker statement than this.
3. **A direct user↔PI channel, and it is a first-class feature rather than an implication.**
   Stated by the human 2026-08-31: **"any top-level agent is talkable by Marlowe and the user. It's
   part of their run window."**

   M3-DESIGN §6.5 already allows chat with a top-agent through a window, and §3.1 lets a top-agent
   reach the *user*. **Neither describes the user opening the conversation**, and the difference is
   not cosmetic:

   * §3's channel is an **escalation** — the agent is stuck, it is scoped to a subtree, it is
     approved at each level, and Marlowe is deliberately not the recipient. It is rare and it is
     the agent's to initiate.
   * This channel is an **ordinary conversation**, initiated by whoever wants it, at any time, with
     no escalation semantics and nothing to approve.

   Two consequences to design against. **It is talkable by Marlowe *too***, which §3.2 does not
   anticipate — that section is emphatic that Marlowe sees *"a notification and nothing else"* about
   an escalation, and a routine chat channel is a different object that must not become a way to
   read one. **And it lives in the run window** (M3-DESIGN §6, already built), so the substrate
   exists: a window attaches to a run, `Intent::Steer` is already a write into a running run, and
   `/watch` already opens one. What is missing is a reply path and the framing that this is a
   conversation rather than a steer.

   **The §4 invariant constrains one direction only.** The user or Marlowe talking *to* a top-agent
   is prose flowing **down**, which §2 declares safe. What comes **back** is the direction that has
   always needed typing, and a chat reply is exactly the free-text upward channel §2.3 exists to
   prevent — so this is where A8's unanswered question stops being academic.
4. **The conversation never blocks the work, in both directions.** Talking to Marlowe must not
   perturb the PI, and the PI must not wait on Marlowe. This is M3's founding premise
   (*"the conversation never halts"*) applied to a specific pair.

---

## §3. What the PI may do

> *"The PI has a small research team they can use to explore options. Maybe they have an idea but
> need a rigorous mathematical proof for it? They deploy an agent for it. Maybe their job is
> massive? A full website repo? He can make teams."*

- **Spawn specialists on demand**, mid-task, in response to something it discovered. A proof
  obligation is a reason to spawn that did not exist when the task was scoped.
- **Form teams, not just workers** — a level-3 assistant that has its own interns. The ladder already
  permits `PI -> Master -> Worker`; what is new is that the PI decides when a *team* rather than a
  *worker* is the right shape, at runtime.
- **Do the hardest part itself.** Settled 2026-08-31 and already in code: the `Master` arm of
  `CapabilityProfile::new` no longer refuses working tools, and `MANAGEMENT_TOOLS` /
  `ProfileError::MasterHoldsWorkingTool` went with the rule.

**The reversal's reasoning, kept here because it is the argument the design rests on.** §1.2 held
that *"a master with an `edit` tool will eventually edit… because it is capable and the work is right
there."* But `SpawnRequest.task` is an `ArgumentRole::Payload` and `composes_spawn_targets` never
checks it — so a toolless master still wrote the task for a worker that held `edit`. **The rule
displaced the actor one hop without adding a check.** Removing it does not open that path; it stops
routing around it.

**One refusal survived, and it nearly died by accident — which is the part of this reversal worth
remembering.** `MANAGEMENT_TOOLS` was doing two jobs under one whitelist: it withheld working tools
*and* it withheld `ask`. Deleting the constant for the first would have silently dropped the second,
and nothing about the deletion would have looked wrong. `ask` is now refused **by name**
(`ProfileError::OnlyATopAgentMayAsk`) because only a top-agent reaches the user, so the refusal is
stated rather than inherited from a list. Built and green at `6e01c37`; `MANAGEMENT_TOOLS` and
`ProfileError::MasterHoldsWorkingTool` are deleted.

### 3.0 THE KICKOFF — a role briefing, because 52 AAII does not mean it can infer what it is

> *"An ideal model for research can't infer it. It'll need an md given, called 'kickoff' — a quick
> introduction of what it is (You are the Principal Investigator) and what it can do. Use agents
> when needed. The models are 52 AAII, but giving them a small kickoff goes a long way."*

**This is the difference between a capable model and a capable *researcher*, and it is not a prompt
tweak.** A `task` string says what to do. It does not say *what you are*, *who works for you*, *what
they are good at*, or *that delegating is expected rather than a failure to cope*. A model that has
not been told it has a team does not spawn one — and the whole thesis of this harness is that the
team is where the gain is.

**It is an ARTIFACT, on `persona/vN.md`'s pattern, and for the same reasons.** Versioned, one file,
loaded rather than interpolated, and living in the **stable tier**. §3.3's argument transfers
exactly: a role that lives in retrievable memory is a role a retrieval miss lets the model
improvise, and a PI inventing its own job description is worse than one that was never briefed.

**It is NOT the persona.** `04-addendum-persona.md` is binding, non-configurable, and Marlowe's —
it governs user-visible prose. A kickoff is a *role briefing* for an agent the user does not read
directly. Two different artifacts, two different lifetimes, and conflating them would put the
persona's stability requirements on a file that should change as the team's capabilities do.

**One per role, not one in total.** The assistant's kickoff and the intern's are different documents
saying different things — *"you extract and report; you do not editorialise; the PI needs what the
source says, not what you think of it"* is the intern's whole job description and it is not the PI's.

**It flows DOWN, so §2 declares it safe** and it costs the security model nothing. The kickoff is
harness-authored prose reaching an agent; nothing about it crosses upward.

**And it is what makes the output read like research.** The human's benchmark framing —

> *"If you put `marlowe-dusk:27b-super` into this harness and asked it a benchmark question that
> required deep research, and compared it to the same model without the harness, the scores should
> be extremely different — and the answers should read like research findings rather than simple
> A/B/C/D."*

— is a statement about **register and evidence**, not just accuracy. A model told *"answer the
question"* returns an answer. A model told *"you are a principal investigator; findings carry their
sources; you have assistants for breadth and interns for triage"* returns something with a shape.
That shape is half the kickoff and half the `OutputContract`, and neither is inferable from a task
string.

**The measurement that would prove it**, and it is the one benchmark row that matters here: the same
model, the same question, harness against no harness, scored on the benchmark's own metric **and**
on whether the answer carries checkable citations. Anything less is comparing a model to itself.

### 3.1 No token budget by default, on local models

> *"Also a mode, default mode, no token budget limit for local models by default."*

**Local inference costs electricity, not money, so a token cap is rationing a resource that is not
scarce.** The default for a local provider is unmetered tokens.

**But "no token limit" must not become "no limit", and the type already warns why.**
`Budget::interactive`'s own comment: *"Every field is a real number rather than `u64::MAX`: an
unbounded dimension is a dimension whose cap never fires, and the point of the type is that all six
fire."* Two distinct jobs are being conflated in one struct:

| Dimension | What it rations | On a local model |
|---|---|---|
| `tokens`, `micros_usd` | **money** | not scarce — should not bind |
| `wall_ms` | **the user's time** | still scarce; still binds |
| `tool_calls`, `subagents`, `depth` | **runaway behaviour** | still binds, and is the real safety net |

So the shape to build is *not* `tokens: u64::MAX`. **Derive the token cap from the wall-clock budget
at the model's measured throughput** — 44 tok/s for `marlowe-dusk:27b-super` — so every dimension
stays a real number that can fire, and the token cap simply stops being the one that does. Thirty
minutes at 44 tok/s is ~79,000 tokens; the user experiences no token limit, and `Budget::exhausted`
keeps working exactly as designed.

**Instance #17 applies at every site:** a dimension of `0` reads as *already exhausted*, never as
*unlimited*. Whatever is built here, no counter goes to zero.

### 3.2 The workspace — a sandbox, and it is the *"securities lifted"* half of §1

> *"Marlowe → full access to computer, hence why its securities are heavy. Marlowe-deployed agent
> teams → full access to their own sandbox, securities lifted so they can go wild on their research
> for maximum workflow. An empty workspace with only items pertaining to their job is much easier
> than a cluttered user desktop."*

**Stated by the human 2026-08-31. It is a requirement about the environment rather than about the
agent**, and it was missing from this page entirely until now. The asymmetry is the whole of it:
Marlowe holds the machine, so his securities stay heavy *because* of what he can reach; a team holds
only its own box, so the protections that exist to keep the machine safe have nothing left to protect
inside one and can be lifted there. Those are one sentence read from two ends, and neither half
survives alone — lifting the securities without the box is not a trade, it is a subtraction.

**The last clause is a research argument, not a security one, and §1 is why it belongs here.** An
empty workspace holding only the job's own material is a better place to work than a user's desktop:
fewer wrong files to open, no ambiguity about what is in scope, nothing to be careful around. The box
is claimed to make the work *better*, and a box that only made it safer would be the kind of
protection §1 says to re-design rather than accept.

**And the correction, which is the human's and which an earlier draft of the mechanism got wrong:**

> *"Assume the worst. The agent gets compromised and turns completely evil. A git worktree can be
> left. A sandbox cannot."*

**A worktree is provisioning, not containment.** It is a cheap way to put a repo copy *inside* a box;
it is not a box. `bash` consults no `PathScope` — the file tools are walled inside the harness
process and the shell is not — so `..`, an absolute path, a symlink or a Python one-liner leaves a
nominated directory without trying. What the requirement asks for is something a compromised agent
cannot walk out of, and only the OS can say that.

**Which fixes the sequencing, and it is the part of this requirement most easily read backwards:
`bash`'s `Irreversible` escalation IS the current sandbox for the shell path.** So *"lift the
securities"* and *"build the box"* are **one change, not two**. Lifting first does not buy a little
speed for a little security; it removes the only control that path has.

**THE MECHANISM IS PROPOSED AND NOTHING IS BUILT.**
`docs/design/adr/ADR-070-one-sandbox-per-team-and-it-wraps-bash.md` is `Status: PROPOSED — needs the
human's approval` and is marked `DESIGN ONLY, NO CODE`: no crate, no call site, no spike. This page
records the requirement it answers, not a decision that it is the answer. What is worth carrying up
from it is only what changes how large the requirement turns out to be:

* **Only `bash` leaves the daemon process.** `web`, the model call, the journal and every file tool
  run in-process — `crates/marlowe-exec/src/lib.rs:1999-2001` dispatches `bash` and `web` side by
  side. **So the box would wrap `bash` alone, and research is untouched:** `web` is harness-executed
  today and stays that way, so a boxed team fetches pages exactly as it does now.
* **AppContainer, with three facts verified on this machine by `icacls`.** `C:\Users\matth` carries
  **no** `ALL APPLICATION PACKAGES` ACE, so the user's profile is denied to an AppContainer by
  Windows' own defaults with no code written; `C:\Program Files\Git` and `System32` do carry it, so
  Git Bash and the system DLLs load; `CreateAppContainerProfile` needs no elevation.
* **Network denial would be the kernel, not a filter.** A token built with a NULL capability array
  holds neither `internetClient` nor `privateNetworkClientServer`, and Windows Filtering Platform
  drops the connect on the package SID. **Loopback is blocked for AppContainers by default** — the
  hole ROADMAP names as *"exactly where an attacker aims"* — and the documented exemption requires
  admin, so an agent cannot grant it to itself.
* **Egress is NOT retired by any of this.** The box contains **damage**, not **disclosure**: `web` is
  harness-executed and the box does not constrain it, the box holds a copy of the user's source, and
  the allowlist is the only thing between that and an attacker-named host.
* **Marlowe is not boxed**, and his securities stay heavy precisely because he has the machine. §4's
  invariant is untouched by the proposal.
* **UNVERIFIED, and it is repeated as unverified wherever this is discussed:** whether MSYS2 / Git
  Bash survives AppContainer's redirected object namespace. That is the largest risk in the design,
  and it is a spike rather than an argument — no amount of reasoning on this page settles it.
* **Two hard constraints from the human**, recorded at `runs/m3-c/sandbox/HARD-CONSTRAINTS.md`: it
  must **never log the user out**, and **nothing verifies the box by running a destructive command**
  — escape is proved by *reaching something harmless you should not be able to reach*, never by
  destroying something.

---

## §4. THE ONE PROPERTY THAT DOES NOT BEND

> *"As long as marlowe-secretary stays unlatched he's ok."*

**Marlowe's trust floor must never latch.** He is the one permanent run, and M3-DESIGN §2.1 is why:
ADR-023's floor is monotonic per run, so a Marlowe who ingests one finding *"can never compose a
target again — not for that task, for his life."*

**And the reframe that makes the rest of this page affordable: the PI is a RUN, not a person.** It is
task-scoped and disposable. A latched PI is not a dead PI — it can hand off to a fresh one. Every
expensive protection in the current design exists because Marlowe is permanent, and **none of that
reasoning transfers to a run that can be restarted.** That is where the headroom is.

---

## §5. What this obliges, and none of it is done

* **M3-DESIGN §1.2** — reversed in code; the section still reads the old way and must be amended in
  place with the old wording quoted.
* **M3-DESIGN §1.1** — *"the only agent Marlowe ever creates is a top-agent"* survives, but
  *"master … coordinates; does not work"* does not.
* **M3-DESIGN §3.1/§3.2** — the escalation path stays, and a **user-initiated** channel to a
  top-agent is a different thing that §3 does not describe. Marlowe seeing *"a notification and
  nothing else"* must be checked against what a user↔PI channel implies.
* **M3-DESIGN §4** — the budget model, per §3.1 above.
* **`SECURITY-AUDIT.md` finding #1** matters more after this change, not less: a child's report
  crosses into the parent at `AgentInferred`, above `blocks_composed_targets`'s threshold, and the PI
  now holds working tools while holding the union of everything its team found. **The blast radius
  does not widen in what can be done; it widens in how well-aimed it is.**
* **Red-team pass 2's surface changes** — the PI is now an acting agent with cross-worker synthesis.
* **§3.1's budget model gets cheaper inside a box, and that is the clearest thing the sandbox buys
  the rest of this page.** *"No token budget on local"* is affordable because tokens are electricity;
  what it still has to pay for is **runaway behaviour**, which is why `tool_calls`, `subagents` and
  `depth` are named above as the real safety net. A runaway inside a team's own box burns its own box
  — a disposable directory belonging to a disposable run — rather than the user's machine, so those
  counters go back to rationing the user's time instead of standing in for containment. **Today they
  are still standing in for it**, because the box is proposed and not built, and a counter carrying a
  job it was not designed for is not a thing to relax on the strength of an unaccepted ADR.
* **§1's ordering reaches its *"securities lifted"* half only through §3.2.** The lift is affordable
  *because* something else is holding. If ADR-070 is not accepted, the securities on the `bash` path
  stay exactly where ADR-026 put them, and §3.2's sequencing sentence is why: there is no version of
  this requirement in which the lift happens on its own.
* **M3-DESIGN §1.3 and §4, ADR-002 narrowly, and ADR-026's `Irreversible` ceiling for `bash`** — all
  of them move if the sandbox is accepted, and none of them has moved. That is ADR-070's own amends
  row, repeated here so this page's obligations are not read as smaller than they are.

## §6. What this page deliberately does not decide

The mechanisms. Two brainstorms are running against this requirement — one on capability without
hindrance (lifecycle, per-value provenance, reversibility, raw model performance, and what threatens
§4), one on the research team (topology, citation verification, effort scaling). **Their proposals
are judged against §1's ordering and §4's invariant**, and nothing here commits to any of them.

**§3.2's mechanism is in the same position, and is named rather than adopted.** The sandbox
*requirement* is the human's and is captured above; the AppContainer that answers it is ADR-070's and
is **PROPOSED**. A later reader looking on this page for the decision will not find one, and that is
correct — what is here is what was asked for.
