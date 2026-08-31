# The PI session — plan, for approval

**Written 2026-08-31 at the human's request, for the session immediately after M3 Session C.**
Nothing here is started.

## The goal, in the human's words

> *"The goal is to prove that agents work in their sandbox. We should be able to deploy a PI team
> directly after that session and observe it. It won't have cross-agent communication or meetings
> yet, but it will have a PI who deploys agents manually — still lets us test the system."*

**So the deliverable is a thing you watch, not a suite that goes green.** A PI takes a real task,
provisions a box, spawns helpers into it, they work, and you see it happen.


> **ADR-070 WAS ACCEPTED BY THE HUMAN ON 2026-08-31, AFTER THIS PAGE WAS WRITTEN.**
> Every *"proposed"* below that names it should be read as **accepted and still unbuilt** —
> acceptance authorised the work and settled the mechanism argument; it built nothing. The
> spike that gates the implementation (does Git Bash survive an AppContainer?) has not run,
> and ADR-070's own status line says acceptance does not change that. **No document may cite
> it as evidence that agents are contained until those probes have.**

---

## What is already built, so the plan does not re-build it

| | |
|---|---|
| Five agent levels, constructor-validated | `a017ee0` |
| `role` and `disposition` on `SpawnRequest`, both ADR-023 Targets | `a017ee0` |
| A master may hold working tools — the PI reversal | `6e01c37` |
| `Engine::spawn` — a parent really does spawn and run a child | shipped |
| A window per run: `/watch`, `/runs`, `/steer` | M3 Session F |
| Model-driver seam — a real daemon turn with a scripted model | `b44c9f4` |

## What is missing, and only the first three block the demo

1. **The sandbox** — ADR-070, proposed, unbuilt. The point of the session.
2. **A per-team workspace** — somewhere for the team to write. Without it there is nothing to watch.
3. **The kickoff artifact** — and this one is easy to underrate. **A model not told it has a team
   does not spawn one.** Without a kickoff the demo shows a very good model doing everything alone,
   which is the opposite of the thing being demonstrated.
4. *(not blocking)* the intake interview, the user↔PI chat channel, no-token-budget-on-local.

---

## The order, with a gate at each step

### Step 0 — THE SPIKE, and it decides whether the rest happens

**Does Git Bash run inside an AppContainer at all?** MSYS2 uses named shared objects and `fork()`
emulation, and AppContainer redirects the object namespace to
`\Sessions\N\AppContainerNamedObjects\<SID>`. **Nobody has verified this and ADR-070 says so.**

A few hours. Three outcomes, all acceptable:

* **It works** → proceed.
* **It does not** → fall back to `cmd`/PowerShell inside the box, or to a separate unprivileged
  account. Both are worse ergonomically; neither is fatal.
* **Neither works cleanly** → the session becomes "sandbox mechanism" and the demo waits. **Better
  to find that in step 0 than in step 3.**

> **This step needs you present.** It is the first time a containment boundary is exercised on your
> machine. Everything after it can run unattended.

### Step 1 — the box

`crates/marlowe-sandbox`, one function: spawn a child under an AppContainer token with a null
capability array and an ACL view of one directory. `marlowe_exec::spawn_shell` calls it when the run
carries a team workspace.

**The acceptance test is the whole point and it runs with the harness's own path scoping deliberately
disabled** — otherwise it passes whether or not the box exists:

| probe from inside | leak looks like |
|---|---|
| read `C:\Windows\System32\drivers\etc\hosts` | it succeeds |
| list `C:\Users\matth` | entries come back |
| write a canary the harness made seconds earlier in its own scratch | the canary changes |
| `curl https://example.com` | a response |
| connect `127.0.0.1:11434` | Ollama answers |

Plus the **positive control**: the same shell doing ordinary work — `mkdir`, `git init`, writing a
file in its own workspace. Without it the escape probes pass on a shell that never started.

**No destructive command, anywhere, for any reason.** A read that succeeds is exactly as conclusive
as a delete that succeeds.

### Step 2 — the team workspace

A directory per top-agent, created at spawn, ACL'd to that team's package SID, destroyed with the
team. Marlowe chooses what goes in — nothing, or a `git worktree` of the repo when the job is about
the repo. The worktree is **provisioning inside the box**, never a substitute for it.

### Step 3 — the kickoff

`agents/pi/kickoff-v1.md` and one per role beneath it. Artifact on `persona/vN.md`'s pattern:
versioned, loaded not interpolated, in the stable tier. *You are the principal investigator. You have
assistants and interns. Delegating is expected. Findings carry their sources.*

### Step 4 — the demo

A real task — *"research X and write it up"* — run end to end and watched through `/watch`.

---

## What the demo will and will not show

**Will:** a PI that reads, plans, spawns helpers, and writes files into a box it cannot leave; a
team workspace that ends up with real artifacts in it; and the escape probes failing.

**Will not, and these must be said before the demo rather than explained after it:**

* **The team runs sequentially, not in parallel.** `Engine::spawn` calls `self.run(...)`
  synchronously, and `OLLAMA_NUM_PARALLEL=1` serialises every model anyway. It will look like a
  queue, because it is one. That is not the sandbox failing.
* **No cross-agent communication and no meetings** — the human's own scope.
* **Model swaps cost ~11.4 s each** and `marlowe-dusk:27b-super` does not co-reside with anything on
  this card. **Run the demo with the PI at `marlowe-dawn:9b-super`** — the human's own testing
  configuration — or it measures eviction latency rather than teamwork.
* **No benchmark number.** Proving the harness beats a solo model is a later, separate measurement
  with its own controls.

## Risks, ranked

1. **MSYS2 under AppContainer.** Step 0 exists because of it.
2. **The PI does not delegate.** Mitigated by the kickoff; if it still refuses, that is a finding
   about the kickoff and worth having.
3. **The box breaks the harness.** The daemon must still reach into the team folder while the box
   cannot reach out — verified by the positive control, not assumed.
4. **The demo is boring** because everything serialises. Named above so it is not read as a defect.

## What needs you

* **Approve ADR-070** — the sandbox is `PROPOSED` and step 1 is gated on it.
* **Be present for step 0.** Two hours, once.
* Everything else can run unattended, and touches no §13-guarded file.
