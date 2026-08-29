# The Agent Directory — a brief for a brainstorming session, not a design

**Requested 2026-08-29 by the human. Scheduled at the END of M3, and the first step is a
brainstorming session, not an implementation session.**

| | |
|---|---|
| **Status** | requested; nothing designed, nothing built |
| **Scheduled** | end of M3, after Sessions C, D and E |
| **First step** | a brainstorming session with the human — this page is its input, not its output |
| **Depends on** | Session C (the agent tree exists), Session F's window substrate (shipped) |
| **Collides with** | STATE.md's open item *"THREE CONSTANTS ENCODE A 16 GB CARD"* — same problem, one level down |

---

## §1. What was asked for

Verbatim in substance, so the brainstorm starts from the request rather than from a paraphrase:

> Add another thing to M3. **The Agent Directory** — see all running agents, available agents etc.
>
> When deploying non-cloud agents, the harness seriously needs to consider the cost of each locally
> hosted agent — look at what space it has for VRAM cache of each etc.
>
> This window lets the user select **"secretary model"**, **Agent-Model-High** (agents with highest
> capabilities / load-bearing), **Agent-Model-Medium** (default), **Agent-Model-Low** (quickest
> agents, meant for fast tasks).
>
> When the harness emits a `run` they will also — **new parameter** — emit a **level**,
> High/Medium/Low, which will load the corresponding agent up.

Two features, and they are separable: a **directory** (what exists, what is running) and a **level
ladder** (which model a run gets, and what that costs in VRAM). The brainstorm should decide whether
they ship together or whether the directory is useful before the ladder exists.

---

## §2. THE CONSTRAINT THAT DECIDES THE SHAPE, AND IT IS ALREADY MEASURED

**On this machine, the ladder is not a residency problem — it is a scheduling problem, and the
arithmetic says so before anyone designs anything.**

| Measured, and where | Value |
|---|---|
| The card | **16 GB** |
| A warm 9B Ollama runner | **6.7 GB** (STATE.md, hybrid session) |
| **Two copies of a 9B on 16 GB** | **DO NOT FIT.** A warm runner alone was enough to push `llama-server` silently onto the CPU |
| Ollama **cold** load, measured through the daemon | **10,484.9 ms** |
| Ollama **warm** per-request scheduler | **219–228 ms**, paid per request |
| `OLLAMA_NUM_PARALLEL=1` | set at User scope; protects the prefix cache and **serialises parallel subagents** — the accepted cost |
| CUDA primary context | ~238 MB per process, leaked once and never returned |
| Embedder + reranker | also want VRAM; ADR-044 resolves `auto` against **free VRAM at load** |

**So the obvious reading of the request is the one that fails.** If the secretary is a 9B (6.6 GB)
and Medium is a 9B (6.6 GB), that is 13.2 GB before the embedder, the reranker, the CUDA context and
the KV cache — and a **switch** between levels costs a cold load, measured at **ten and a half
seconds**. A "Low" tier *"meant for fast tasks"* that costs 10 s to switch into is slower than the
Medium model it was avoiding. **The tier ladder can invert its own purpose, and the number that
proves it is already on the page.**

That is not an argument against the feature. It is the first thing the brainstorm has to solve, and
it has a measured answer available rather than a guess.

### Models present on this machine, for the arithmetic

`qwen3.5:0.8b` 1.0 GB · `qwen3-vl:2b` 1.9 GB · `qwen3.5:2b` 2.7 GB · `qwen3.5:4b` 3.4 GB ·
**`marlowe-red:9b` 5.8 GB** · **`qwen3.5:9b` 6.6 GB** · `marlowe-dawn:9b` 6.6 GB ·
`marlowe-dusk:27b-small` 10 GB · `qwen3.6:27b` 17 GB · `marlowe-dusk:27b` 18 GB ·
`qwen3.6:35b-a3b` 23 GB · **cloud: `marlowe-noir:397b`, `qwen3.5:397b-cloud`**

Cloud entries matter: **High may be the tier that does not live on the card at all**, which removes
the VRAM problem and introduces an egress and trust one instead.

---

## §3. Questions the brainstorm must settle

Ordered by how much of the design each one decides.

1. **Are levels RESIDENT or SWAPPED?** Resident means the VRAM budget must hold every tier that can
   be live at once, which the arithmetic above says it cannot at 9B. Swapped means a cold load per
   switch. A third option — **Low and Medium resident, High in cloud** — fits 16 GB and changes what
   High means.
2. **Does a "fast" tier stay fast?** If Low is reached by eviction, its first token is 10 s behind
   Medium's. Either Low is permanently resident (and small), or "quickest" is false.
3. **What does the level attach to, and does it inherit?** A `run` parameter, per M3-DESIGN §1's
   five levels. Does a child inherit its parent's level, or does the spawning agent choose? A master
   that can set its children's level is choosing spend and capability.
4. **WHO chooses the level — and can untrusted content influence it?** This is a security question
   and it is not obviously covered by the existing layers. A downgrade (force everything to Low to
   make the system dumber before an attack) and an upgrade (force High to exhaust budget) are both
   attacker-useful. **Is the level a *target* under ADR-023, or a payload?** Layer 3 governs
   *which tool, which recipient, which path, which amount* — a model tier is the same kind of thing
   and is not in that list. **Answer this explicitly rather than by omission.**
5. **What is an "available agent"?** An installed Ollama model, a configured role (coder,
   researcher), or a `CapabilityProfile`? §1.3's worker tool sets are per type, so a directory row is
   plausibly a *type*, not a model.
6. **What does the directory show for RUNNING agents that the Runs tab does not?** `03-addendum-terminal.md`
   pins tab `1` as the roster — status, elapsed, spend against ceiling, subagent depth, steer field —
   and M3-DESIGN §6.5 says *"one state, two renderings"*. **A directory that keeps its own view of
   what is running is the two-sides-silently-disagree shape this project has logged repeatedly.**
   Decide whether this is a third rendering of the control plane or a genuinely different object.
7. **How does it interact with `OLLAMA_NUM_PARALLEL=1`?** Subagents are serialised today. A
   directory showing eight running agents on a machine that runs them one at a time is telling the
   truth about intent and a lie about execution.
8. **Does the secretary's model ever change?** Marlowe is one permanent run and the persona is not
   configurable (`04-addendum-persona.md`, binding). Changing his model mid-life changes his voice,
   and §C4's anti-sycophancy probe set is a standing regression test **whose score a model swap is
   blocking on**. So "select secretary model" is not a dropdown; it is a versioned decision with a
   probe run attached.

---

## §4. What already exists, so the brainstorm does not redesign it

- **`vram.rs`** has a probe and a reserve mechanism, used by the embedder and the hybrid engine.
- **Eviction via documented endpoints** — `/api/ps` and `/api/generate {keep_alive: 0}` — with the
  engine printing what it evicted. Written for the hybrid; it is the same mechanism a tier switch
  needs.
- **STATE.md's open item, `THREE CONSTANTS ENCODE A 16 GB CARD`**, already contains half of this
  feature's VRAM job and should be read as part of the brainstorm rather than solved twice. It
  already asks for **`/model` to say what fits** — *"qwen3.5:9b — fits, 32k. 27b — 4.2 GB short."* —
  which is the directory's VRAM column in a different surface. It also establishes three rules this
  page inherits: **the offload check is a DEGREE, not a boolean**; **the KV allocation is derived
  from measured free VRAM and the choice is stated to the user**; and **eviction is the normal path,
  not a warning.**
- **Session F's window substrate** ships already, so this is a new window rather than new window
  machinery.

---

## §5. What this page deliberately does not decide

Everything in §3. This is the brainstorm's input.

It also does not decide whether the two halves ship together. A directory of what is running and
available is useful on its own and is mostly a rendering of state the control plane already holds;
the level ladder is a scheduling and VRAM problem with a measured hazard in it. **They are one
request and possibly two sessions.**

And it does not assume the 16 GB card. That number is this machine, and STATE.md's open item names
the generalisation as unsolved: the target is *all consumer hardware*, and a design that fits 16 GB
by arithmetic rather than by measurement is the same mistake one card size down.
