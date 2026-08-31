# The PI session — prove the team works in its box

Read `STATE.md`'s top entry, then `docs/design/PI-SESSION-PLAN.md`, then `ADR-070` and `ADR-071` in
full. Then `CLAUDE.md` — its failure ledger runs to nineteen, and **two of this session's own
corrections were instances of it.**

Baseline, verified 2026-08-31 at `2b5e02b`:

| | |
|---|---|
| HEAD | `2b5e02b`, tree clean, **49 commits ahead of the remote — Matthew pushes, never you** |
| Suite | **1,263 passed, 0 failed, 7 ignored, 122 `test result` lines**, ten crates, per-crate only (`runs/m3-c/final/suite-all.txt`) |
| Highest ADR | **071** |
| Layer 3 | still unreachable, **and that is correct** — `grep -rn "ingest_external(" --include=*.rs crates/*/src/` minus definitions returns zero |
| `Channel::Agent` | classified, **no production producer** |
| Accepted, unbuilt | **ADR-070** (one sandbox per team, wrapping `bash`) and **ADR-071** (inside a team they just talk) |

## What this session is

Matthew: *"The goal is to prove that agents work in their sandbox. We should be able to deploy a PI
team directly after that session and observe it. It won't have cross-agent communication or meetings
yet, but it will have a PI who deploys agents manually — still lets us test the system."*

**The deliverable is a thing he watches, not a suite that goes green.** A PI takes a real task,
provisions a box, spawns helpers into it, they work, and it is observable through `/watch`.

## STEP 0 IS A SPIKE AND IT GATES EVERYTHING — Matthew must be present

**Does Git Bash run inside an AppContainer at all?** MSYS2 uses named shared objects and `fork()`
emulation; AppContainer redirects the object namespace to
`\Sessions\N\AppContainerNamedObjects\<SID>`. **Nobody has verified this.** ADR-070 §4.3 names it as
the largest risk in the design and says explicitly that it is a spike, not an argument.

Three outcomes, all acceptable: it works; it does not and the fallback is a native shell or a
separate unprivileged account; or neither is clean and the session becomes "sandbox mechanism" while
the demo waits. **Finding that in hour one is the point.**

> **If the spike fails, ADR-071's premise is gone** — it says so itself, §7 item 4. Team-internal
> free prose is contingent on the box existing. **It must not survive its own precondition.**

## Then, in order

1. **The box.** `crates/marlowe-sandbox`: an AppContainer token with a **NULL capability array**
   (not a zero count — instance #17 read in the correct direction: the withholding is structural
   because there is no array), an ACL view of one directory, stdout/stderr piped back.
   `marlowe_exec::spawn_shell` (`crates/marlowe-exec/src/lib.rs:2523`) is the **one** call site.
2. **The team workspace.** A directory per top-agent, ACL'd to that team's package SID, destroyed
   with the team. A `git worktree` is what goes **inside** it.
3. **The kickoff artifact.** `agents/pi/kickoff-v1.md` and one per role beneath it, on
   `persona/vN.md`'s pattern — versioned, loaded not interpolated, stable tier.
4. **The demo.** A real task, watched.

## Two facts verified on this machine — do not re-derive, do not contradict

```
C:\Users\matth        ← NO "ALL APPLICATION PACKAGES" ACE at all
C:\Program Files\Git  ← ALL APPLICATION PACKAGES:(I)(RX) and (I)(OI)(CI)(IO)(GR,GE)
```

**Windows denies an AppContainer the user's profile and lets it run Git Bash, by its own default
ACLs, before a line is written.** `CreateAppContainerProfile` needs no elevation.

## THE ACCEPTANCE TEST, AND IT IS THE WHOLE POINT

Run **with the harness's own path scoping deliberately disabled**. With scoping on, every probe
passes whether or not the box exists — instance #15 aimed at the single claim the design rests on.

| probe from inside the box | a leak looks like |
|---|---|
| read `C:\Windows\System32\drivers\etc\hosts` | it succeeds |
| list `C:\Users\matth` | entries come back |
| write a canary the harness created seconds earlier in its own scratch | the canary changes |
| `curl https://example.com` | a response |
| connect `127.0.0.1:11434` | Ollama answers |

**Plus the positive control**: the same shell doing ordinary work — `mkdir`, `git init`, writing in
its own workspace. Without it the escape probes pass on a shell that never started.

## Do NOT

- **Never verify containment with a destructive command.** *"Let me test if a dangerous command
  works — deletes the system — oops, looks like it worked."* **Escape is proved by REACHING
  something harmless, never by DESTROYING something.** A read that succeeds is exactly as conclusive
  and leaves the machine intact. `runs/m3-c/sandbox/HARD-CONSTRAINTS.md` is binding.
- **Never log Matthew out.** No session switching, nothing touching `explorer`/`winlogon`, and no Job
  Object whose `KILL_ON_JOB_CLOSE` scope could include the daemon or a parent.
- **Never `cargo test --workspace`** — it has bugchecked this machine. Per-crate, once, to a file,
  `grep -c FAILED` **first** in any chain. Finish with `-p marlowe` for the determinism guard no
  other `-p` reaches.
- **Do not wire `ingest`** (ADR-062) or add a `Channel::Agent` producer.
- **Do not lift `bash`'s escalation before the box works.** ADR-070 §3: that escalation **IS** the
  current containment on that path, so lifting and building are **one change**. Lifting first removes
  the only wall.
- **Do not retire egress.** The box contains **damage**, not **disclosure**: `web` is
  harness-executed and the box holds a copy of the repo.
- `HashMap`/`HashSet` banned under `crates/`. Never `git add -A`. No `Co-Authored-By`.

## Traps, and two are this session's own corrections

- **A8 IS RETIRED.** It moved to M3-DESIGN §9.2 — asserted, not A/B tested. Do not resurrect it as an
  arm, and do not design a rate where the answer is pass/fail. What remains worth attacking is two
  assertions: can anything cross into Marlowe untyped, and can anything leave the box.
- **The Marlowe boundary IS identifiable.** `run.profile.level() == AgentLevel::Secretary` at
  `Engine::spawn`, on a public getter that already ships. A previous note called this a blocker; it
  was made from an assumption about the code rather than from reading it.
- **A worktree is provisioning, not containment.** `bash` consults no `PathScope`, so a compromised
  agent leaves a nominated directory without trying.
- **#15** — assert where it enforces. **#16** — name the function that reads every field, or drop it.
  **#17** — no capability withheld by a counter of zero.
- **Line numbers drift constantly.** `composes_spawn_targets` had its wrong four times in one day.
  Verify every citation in this brief before repeating it.

## The demo will not impress, and say so before it runs

- **The team is sequential.** `Engine::spawn` calls `self.run(...)` synchronously and
  `OLLAMA_NUM_PARALLEL=1` serialises every model. It will look like a queue because it is one.
- **Run the PI at `marlowe-dawn:9b-super`**, not the 27b — which co-resides with nothing on this card
  and costs **11,410 ms** per swap. Otherwise the demo measures eviction latency.
- **No benchmark number.** Harness-versus-solo is a separate measurement with its own controls.

## Owed by Matthew

1. **Presence for step 0.** Two hours, once.
2. **The `ask` guard's Worker arm** — one line in `profile.rs` (§13-guarded): the refusal sits on the
   `Master` arm only, so a level-4 Worker holding `ask` is still constructible.
3. Standing: the latch scope **before Session D starts**; ADR-062 §4's origin decision;
   `ROADMAP` *Waiting* item 1 is stale (ADR-032 was accepted 2026-08-29).

## Hazards

`marlowe-permission/src/`, `marlowe-memory/src/trust.rs`,
`marlowe-loop/src/{profile,provenance,driver,steer}.rs` and `marlowe-daemon/src/{mcp,memory}.rs` are
§13-guarded — **and the hook now matches `Bash` as well as `Edit`**, so a heredoc into one prompts.
Set `MARLOWE_CUDA_LIB_DIR` or the embedder silently runs on CPU with a correct-looking log line.
`git checkout --` on uncommitted work discards it, so commit before mutation-testing.
