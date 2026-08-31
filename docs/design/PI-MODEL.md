# The PI model — Marlowe is the connection to the geniuses

**Stated by the human 2026-08-31, during M3 Session C. This page is the requirement, not the
design.** It captures what was asked for while the wording is fresh, so the brainstorms that follow
are judged against it rather than against a paraphrase.

| | |
|---|---|
| **Status** | requirement captured; design in progress, nothing built beyond §1's tool reversal |
| **Overturns** | M3-DESIGN §1.2 (*"masters hold no working tools, structurally"*) — already reversed in code |
| **Amends** | M3-DESIGN §1.1, §3.1, §3.2 and §4 — see §5 below; none of those amendments is written yet |
| **Feeds** | `AGENT-DIRECTORY.md` (the ladder), `REDTEAM-SESSION.md` (pass 2's surface changes) |

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

## §6. What this page deliberately does not decide

The mechanisms. Two brainstorms are running against this requirement — one on capability without
hindrance (lifecycle, per-value provenance, reversibility, raw model performance, and what threatens
§4), one on the research team (topology, citation verification, effort scaling). **Their proposals
are judged against §1's ordering and §4's invariant**, and nothing here commits to any of them.
