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

## §2. THE SHAPE IS DECIDED, AND IT WAS DECIDED BY SIZING RATHER THAN BY SCHEDULING

**AMENDED 2026-08-30 by the human, and the amendment overturns this section's original argument.**
It reasoned from a 9B secretary plus a 9B worker, concluded that two copies of a 9B do not fit on a
16 GB card, and therefore that the tier ladder had to *swap* models — at a measured **10,484.9 ms**
per cold load, which would make a "fast" tier slower than the tier it was avoiding.

**That premise is now wrong.** The models are chosen small **specifically so that they can all run in
parallel**, and the arithmetic says they do:

| Role | Ollama default | Size | Verified present |
|---|---|---|---|
| **Secretary** | `marlowe-dawn:9b-super` | 5.9 GB | yes |
| **Agent** | `marlowe-mini:4b-super` | 2.8 GB | yes |
| **Extractor** | `marlowe-mini:2b` | 1.3 GB | yes |
| **(a fourth role — UNNAMED)** | — | — | **see below** |

**10.0 GB of the card's 16**, co-resident, leaving headroom for the KV cache, the embedder and the
reranker — all three of which also want VRAM, and ADR-044 resolves the embedder's provider against
**free VRAM at load**, so the headroom is not spare, it is allocated. All three models were confirmed
present via `ollama list` on 2026-08-30.

So there is no ladder and no swapping. **The design is co-residency, and what remains is a routing
question, not a scheduling one.**

> ### MEASURED 2026-08-30, M3 Session C — CO-RESIDENCY HOLDS AND THE HEADROOM DOES NOT
>
> **The paragraph above is arithmetic, and §2a's own rule is that `/api/ps` is the measurement.**
> It was run before designing the queue, as §2a requires. Full record:
> [`runs/m3-c/capacity-finding.md`](../../runs/m3-c/capacity-finding.md); raw output
> `runs/m3-c/capacity.txt`. **Its conclusion survives and its numbers do not**, so it is amended in
> place rather than rewritten.
>
> **What holds.** All three roles stayed resident simultaneously — `OLLAMA_MAX_LOADED_MODELS` is
> unset and resolved to **≥ 3** here, so §2's item 2 hazard (*"the second model evicts the first and
> the design silently degrades into the swap-per-turn the original §2 warned about"*) did **not**
> occur on this machine. Cold load plus one token: **4,354 / 3,212 / 5,442 ms**, so the 10,484.9 ms
> figure the original §2 reasoned from is not what these models cost.
>
> **What does not.** *"10.0 GB of the card's 16, leaving headroom"* omits the desktop. The card was
> **never** 16 GB free: `nvidia-smi` read **5,086 MiB already held** — Opera GX, Discord, Steam,
> Wallpaper Engine, the NVIDIA overlay, `explorer.exe` — before a model loaded. After all three
> roles: **14,993 MiB used, 1,053 MiB free.** One gigabyte, not six.
>
> That is the number ADR-044 reads. The embedder resolves its provider against **free VRAM at load**,
> and CLAUDE.md already records what that produces — *"not an error, a slower run with a
> correct-looking log line."* The reranker wants VRAM on the same terms. **And the fourth role's
> name is the human's; its space is now measured, and there is none.**
>
> **Three corrections an admission decision has to carry:**
>
> 1. **`ollama list` sizes are blob sizes.** `size_vram` sums to **10,849,836,070 B = 10.85 GB**
>    against the table's 10.0 — 8.5% larger, because it includes the KV cache and compute buffers.
>    The table above sizes the roles from the wrong column; **`size_vram` is the one to admit
>    against.**
> 2. **Neither figure reconciles, so a plan computed once is already stale.** 5,086 + 10,347 MiB
>    expected against **14,993 observed**, 440 MiB apart, with per-model deltas wrong in both
>    directions (`dawn:9b` took 6,670 MiB of real card against 5,562 reported; `mini:2b` took 411
>    against 1,665). The desktop moves by hundreds of MiB *while the probe runs*. **Admission must
>    re-measure at admit time and carry a margin** — and Ollama's failure mode when a model does not
>    fit is the CPU split §2a forbids by name.
> 3. **Concurrency was NOT measured.** `OLLAMA_NUM_PARALLEL=1` is read from the declaration; no two
>    requests were issued at once. §3 item 7's consequence stands on a declaration, not a run, and
>    it stays that way until two overlapping requests are timed.
>
> None of this reaches STATE.md's **THREE CONSTANTS ENCODE A 16 GB CARD**. This is one machine, one
> day, one desktop workload — a measurement scoped to the system it was taken on. A different
> desktop baseline is a different answer, and *all consumer hardware* is untouched by it.

### The requirement, as given

- **Four model roles exist.** Each is **user-configurable in a small window**.
- **Either provider works per role** — Ollama or OpenRouter.
- **The spawner names the model**: when the harness emits a `run` it says which role it wants, and
  the corresponding model serves it.

### THREE THINGS THAT MUST BE SETTLED BEFORE ANY OF THIS IS BUILT

**1. The fourth role has no name.** Four were specified; three were given defaults. The missing one
is not guessed here, because a role invented by an implementer becomes a default nobody chose. **Ask.**

**2. `OLLAMA_MAX_LOADED_MODELS` IS UNSET ON THIS MACHINE, and it is the knob co-residency depends
on.** Verified 2026-08-30 at User scope: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
`OLLAMA_NUM_PARALLEL=1`, and **`OLLAMA_MAX_LOADED_MODELS` empty**. These are different knobs and
conflating them is how the plan fails quietly:

- `OLLAMA_NUM_PARALLEL` bounds **concurrent requests against one model**. It is 1, deliberately —
  STATE.md records that it protects the prefix cache and **serialises parallel subagents**, an
  accepted cost. It says nothing about how many *distinct* models stay resident.
- `OLLAMA_MAX_LOADED_MODELS` bounds **how many distinct models stay loaded**. Unset means Ollama's
  default, which **must be read from the running server rather than assumed** — and if it resolves
  below the number of roles, the second model evicts the first and the design silently degrades into
  exactly the swap-per-turn the original §2 warned about, at ~10 s per switch.

**Measure it before building on it:** `GET /api/ps` after loading all four says what is actually
resident. That is the check; the env var is the declaration.

**3. `NUM_PARALLEL=1` still serialises the agents.** Four co-resident models do not give four
concurrent turns if each model admits one request at a time. Whether that matters depends on whether
the roles are used simultaneously — a secretary waiting on an extractor is fine; three workers
running together is not. **This is a real trade against the prefix-cache protection, and it is the
human's.**

### What the original §2 got right and keeps

The **eviction path already exists** — `/api/ps` plus `POST /api/generate {keep_alive: 0}`, with the
engine printing what it evicted. It was written for the hybrid engine and it is the same mechanism a
directory needs to report and manage residency.

And STATE.md's open item **`THREE CONSTANTS ENCODE A 16 GB CARD`** still applies with more force, not
less: this configuration fits *this* card. Its three rules are inherited — the offload check is a
**degree**, not a boolean; the KV allocation is derived from measured free VRAM and the choice is
**stated to the user**; and eviction is the **normal path**, not a warning.

---

## §2a. ADMISSION CONTROL — added 2026-08-30, and it is Session C's problem, not Session G's

**The requirement, in substance:**

- **Agents are kept warm.** A loaded model stays loaded.
- **We load as many as we can onto the GPU, and we NEVER CPU-split.** A model is fully resident or
  it does not run.
- **If a new agent cannot fit, it waits for one of the same type to finish.** A per-role queue.
- *"We have 3 workers loaded, but are out of memory; a 4th agent is spawned and waits for an open
  worker."*

This is **admission control on spawn**. It decides whether a run may start, which makes it part of
the spawn path Session C ships — the window that configures the roles is still G, but a spawn that
can be *refused for capacity* changes the lifecycle, and the lifecycle is pinned.

### The good news: the state already exists and is already pinned

`RunStatus::Queued` is in CONTRACTS §5's enum and has producers at `run.rs:647` and `:670`, rendered
by `roster.rs:214`. **No contract change is needed to express waiting.**

### The question that must be answered before any of it is built

**`RunStatus::Queued` currently means *constructed, not yet started* — a transient measured in
microseconds. Capacity-waiting is the same word for a state that may last minutes**, and the human
watching the roster is the one who pays for the conflation: a run that is *about to start* and a run
that is *blocked behind three busy workers* would render identically, with no way to tell whether
anything is wrong.

This is the same shape as ADR-032 §2's finding — *"`DenyAll` and an allowlist that happens to be
empty currently behave identically and must stop being the same thing."* Decide whether capacity
waiting is `Queued`, or a distinct state, or `Queued` carrying a reason. **A reason field is the
cheapest honest option and it is what the roster needs to say anything useful.**

### THE CAPACITY MODEL IS NOT KNOWN, AND THE EXAMPLE IS AMBIGUOUS

*"3 workers loaded, out of memory"* has two readings and they have **different bottlenecks and
different fixes**:

| Reading | What is loaded | What runs out | The knob |
|---|---|---|---|
| Three workers of the **same role** | **one** copy of `marlowe-mini:4b-super`'s weights | **KV cache** — one per concurrent slot | `OLLAMA_NUM_PARALLEL` |
| Three workers of **different roles** | three sets of weights | **weights** | `OLLAMA_MAX_LOADED_MODELS` |

Under Ollama, same-role workers share weights; what multiplies per concurrent request is the KV
cache, and `NUM_PARALLEL` also **divides the context window** across slots. So in the first reading
the ceiling is not 16 GB of weights at all — it is KV growth, and raising the worker count *shrinks
every worker's context*. In the second, weights are the ceiling and `NUM_PARALLEL=1` still serialises
each role to one request at a time, so "3 workers" would not be concurrent regardless.

**Neither is asserted here, because neither has been measured on this machine.** `GET /api/ps` after
loading the roles reports what is actually resident and at what size; that is the measurement, and
the env vars are only declarations. **Measure before designing the queue, or the queue will be built
against the wrong bottleneck.**

### Two standing decisions this requirement reopens, and neither may be reversed silently

**1. "Kept warm" versus the `OLLAMA_KEEP_ALIVE` reversal.** STATE.md records that `KEEP_ALIVE` was
set and then **deliberately reverted** to Ollama's 5-minute default, because *"pinning 6.7 GB forever
is the wrong trade for a trivial saving."* **That decision was made about one 9B model.** With four
roles sized to co-reside at 10.0 GB the trade is a different one, and "agents are kept warm" is a
request to revisit it — but it is a revisit, not an oversight, and it needs saying so.

**2. "Never CPU-split" versus the offload-degree rule.** STATE.md's open item
`THREE CONSTANTS ENCODE A 16 GB CARD` says the offload check *"must be a DEGREE, not a boolean:
42/48 layers on GPU is healthy, not a failure."* That was written about the **llama.cpp hybrid**,
which is shelved — so the two are probably not in conflict. **Probably is not a decision.** State
explicitly that the agent pool is all-or-nothing per model while the hybrid's rule, if it ever
returns, is about something else.

---

## §3. Questions the brainstorm must settle

Ordered by how much of the design each one decides.

1. **~~Are levels resident or swapped?~~ SETTLED 2026-08-30: resident.** The models are sized to
   co-reside — 10.0 GB of 16 — so this is a routing question, not a scheduling one. What survives
   of it is narrower and is §2's item 2: **`OLLAMA_MAX_LOADED_MODELS` is unset**, so residency is
   currently whatever Ollama's default resolves to, and if that is below the role count the design
   degrades into swapping without saying so. Read `/api/ps`; do not read the env var.
2. **~~Does a "fast" tier stay fast?~~ Replaced by a sharper question: does anything run
   CONCURRENTLY?** Co-residency removes the load cost and does **not** remove `NUM_PARALLEL=1`, which
   admits one request per model at a time. So four loaded models still serialise if the roles are
   used together. Decide whether concurrency is actually wanted — and if it is, that is a direct
   trade against the prefix-cache protection `NUM_PARALLEL=1` was set for, which is a TTFT decision
   the human already made once.
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
