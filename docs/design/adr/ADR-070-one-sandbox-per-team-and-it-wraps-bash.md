# ADR-070 · One sandbox per team, and it wraps `bash` — nothing else has to move

**Status:** **Accepted 2026-08-31 by Matthew.** **DESIGN ONLY — NOTHING HERE IS BUILT**, and
acceptance does not change that: §4.3's three unverified facts stand, and **§7's spike gates the
implementation** rather than following it.

Three facts below were verified on this machine by `icacls` and are marked as such; three more are
**explicitly unverified** and are named rather than asserted. **The largest of those — whether Git
Bash survives an AppContainer — is the first step of the next session and is a spike, not an
implementation** (`PI-SESSION-PLAN.md` step 0). If it fails, §4.3 names the fallbacks and this
acceptance covers them too: what was accepted is *one OS-enforced box per team wrapping `bash`*, not
AppContainer specifically.

> **What acceptance changes and what it does not.** It authorises the work and settles the argument
> — a per-team box is the mechanism, `bash` is what it wraps, and lifting `bash`'s escalation happens
> **in the same change** that builds the box (§3). It does not make the box exist, and no document
> may cite this ADR as evidence that agents are contained until §7's probes have run.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | **ADR-002 narrowly** — it restores a kernel backstop for `bash` alone, on a path that never had one. ADR-026's `Irreversible` ceiling for `bash` becomes conditional rather than absolute. M3-DESIGN §1.3 and §4 |
| **Depends on** | ADR-024 (path scoping), ADR-026 (the consequence ceiling), ADR-027 (containment is the handle walk), ADR-032 / ADR-049 (egress), `PI-MODEL.md` |
| **Contract change** | **None yet.** A team workspace is a field on the run's tool host, not on a pinned type. If `SpawnRequest` must carry it, that is a §13-guarded change and is escalated separately |
| **Code change** | Specified, not written. A new crate `marlowe-sandbox`, one call site in `marlowe-exec` |

---

## 1 · The requirement, in the human's words

> *"Marlowe → full access to computer, hence why its securities are heavy. Marlowe-deployed agent
> teams → full access to their own sandbox, securities lifted so they can go wild on their research
> for maximum workflow. An empty workspace with only items pertaining to their job is much easier
> than a cluttered user desktop."*

> *"Assume the worst. The agent gets compromised and turns completely evil. A git worktree can be
> left. A sandbox cannot."*

And the ordering that governs every trade in this document:

> *"Security is a primary concern but research and knowledge comes first."*

## 2 · The finding that makes this small: only ONE thing leaves the process

`web`, the model call, the journal, and `read`/`write`/`edit`/`glob`/`grep` **all execute inside the
daemon process** — `FileSystemTools`' dispatch at `crates/marlowe-exec/src/lib.rs:1999-2001` shows
`bash` and `web` side by side, and every file tool is walled by `PathScope`.

**Only `bash` leaves.** `spawn_shell` (`lib.rs:2523`) builds `Command::new(git_bash).arg("-c")`.

So the question is not *"how do I sandbox an agent"*. It is *"how do I spawn one child process with
no network and a filesystem view of one directory, while the parent still reaches in."*

**That asymmetry is free.** The daemon keeps its own token, so the harness reaches into the team
folder while the box cannot reach out. Research is untouched: `web` is harness-executed today and
stays that way, so a boxed team fetches pages exactly as it does now.

## 3 · Why path scoping cannot do this, and why the worktree idea fails

`WorkspaceScope` / `PathScope::open` gate the *file tools* — checks inside the harness's process, on
arguments the harness parsed. **`bash` consults none of them.** The shell inherits the daemon's
filesystem access entire; `..`, an absolute path, a symlink or a Python one-liner walks straight out
of any directory the harness nominated.

**A worktree is provisioning, not containment.** It is a cheap way to put a repo copy *inside* a box.
It is not a box. `runs/m3-c/sandbox/CORRECTION.md` records this; it is the human's correction of an
earlier draft of this design and it is the reason the mechanism has to be OS-enforced.

**Therefore `bash`'s `Irreversible` escalation IS the current sandbox for the shell path**, and
ADR-026 was the only non-losing move available rather than caution — its own text says why the
alternative fails: refining consequence per command means parsing the command, which is the Cursor
CVE. ADR-049 §4 measured the gap it was holding: `curl` returns HTTP 200 from `cmd /C`, and **no
`EgressPolicy` is consulted on that path at all**, because the adjudicator iterates `Url`-typed
parameters and `bash` declares none.

> **So "lift the escalation" and "build the sandbox" are ONE change, not two.** Lifting first does
> not trade a little security for speed — it removes the only control that path has. This is the
> sequencing constraint and it is the most important sentence in this ADR.

## 4 · The decision: an AppContainer per team, wrapping `bash` only

A new crate `crates/marlowe-sandbox` owns one function: spawn a child under an **AppContainer token
with zero capability SIDs**, granted an ACL view of exactly one directory, with stdout/stderr piped
back. `spawn_shell` calls it instead of `Command::spawn` when the run carries a team workspace.
**Nothing else moves.**

### 4.1 Verified on this machine — `icacls`, run 2026-08-31

```
C:\Users\matth        NT AUTHORITY\SYSTEM:(OI)(CI)(F)
                      BUILTIN\Administrators:(OI)(CI)(F)
                      NEUTRINO\matth:(OI)(CI)(F)
                      S-1-15-3-65536-…-230526575:(S,X)
                      ← NO "ALL APPLICATION PACKAGES" ACE

C:\Program Files\Git  APPLICATION PACKAGE AUTHORITY\ALL APPLICATION PACKAGES:(I)(RX)
                      APPLICATION PACKAGE AUTHORITY\ALL APPLICATION PACKAGES:(I)(OI)(CI)(IO)(GR,GE)
```

**The user's profile is denied to any AppContainer by Windows' own default ACLs, with no code
written — and Git Bash is executable by one.** That is the containment and the usability, both for
free. `C:\Windows\System32` carries the same package ACEs, so system DLLs load.

`CreateAppContainerProfile` requires **no elevation** (verified: the probing shell was not elevated).

### 4.2 Network denial is the kernel, not a filter

A token built with `SECURITY_CAPABILITIES { AppContainerSid, Capabilities: NULL, CapabilityCount: 0 }`
holds neither `internetClient` (S-1-15-3-1) nor `privateNetworkClientServer` (S-1-15-3-3). Windows
Filtering Platform drops the connect at the ALE authorise-connect layers, keyed on the package SID.

**There is no spelling of `curl` that acquires a capability the token does not hold.** That is
containment in `01-brief.md` §8.1's exact sense, and it is why this is not the filter §8.1 rules out.

**Loopback is blocked for AppContainers by default**, which closes the hole ROADMAP names as *"exactly
where an attacker aims once anything on loopback can proxy outward"* — and the documented exemption,
`CheckNetIsolation LoopbackExempt`, **requires admin**, so an agent cannot grant it to itself.

**Instance #17, read in the correct direction.** `CapabilityCount: 0` here means *"no capabilities
were granted"* and is correct **only because `Capabilities` is NULL** — the withholding is
structural, there is no array, exactly as `ExposedSet::empty()` withholds tools. It is not a counter
something compares against.

### 4.3 THREE THINGS ARE UNVERIFIED AND ARE NOT ASSERTED

1. **Whether MSYS2 / Git Bash survives AppContainer's redirected object namespace**
   (`\Sessions\N\AppContainerNamedObjects\<SID>`). Git Bash uses named shared objects and `fork()`
   emulation. **This is the largest risk in the design and it is a one-hour spike, not an argument.**
   If it fails, the fallback is a native shell (`cmd`/PowerShell) in the box, or a separate
   unprivileged account instead of an AppContainer.
2. **Whether two processes inside the same AppContainer can reach each other over loopback** —
   which decides whether *"run a dev server and curl it"* works inside the box.
3. **The exact `windows-sys` module path** for `CreateAppContainerProfile`
   (`Win32_Security_Isolation` believed correct; check against the pinned version).

## 5 · What it retires, and the one thing it must not

| Control | After the box |
|---|---|
| `bash`'s `Irreversible` escalation | **Retired inside a box.** The prompt was standing in for the kernel; the kernel is now there. Outside a box — Marlowe — it stands unchanged |
| Path scoping for `bash` | **Superseded by the OS.** It remains for the in-process file tools, where it is still the only wall |
| `blocks_composed_targets` on a boxed team's file targets | **Weakened in consequence, not removed.** A composed path inside a disposable box is not the `.git/hooks/pre-commit` chain SECURITY-AUDIT #1 describes |
| **Egress on `web`** | **NOT retired.** The box contains **damage**, not **disclosure**: `web` is harness-executed and the box does not constrain it at all. The team's box holds a copy of the user's source, and the allowlist is the only thing between that and an attacker-named host |
| Layer 1's quarantined reader | **Unchanged.** It stops raw bytes reaching a tool-holding context — a different job from stopping a process escaping |

**Marlowe is not boxed and his securities stay heavy.** He has full access to the machine, which is
exactly why. §2.1's invariant is untouched: nothing here can latch the Secretary.

## 6 · Two hard constraints, from the human, binding on the build

Recorded in full at `runs/m3-c/sandbox/HARD-CONSTRAINTS.md`.

1. **It must never log the user out.** The mechanism runs inside the existing session. This rules out
   session switching, anything touching `explorer`/`winlogon`, and any Job Object whose
   `KILL_ON_JOB_CLOSE` scope could include the daemon or a parent.
2. **NOTHING verifies the sandbox by running a destructive command.** *"Let me test if a dangerous
   command works — deletes the system — oops, looks like it worked."* **Escape is proved by reaching
   something harmless you should not be able to reach, never by destroying something.**

## 7 · Acceptance — and the control that separates a box from a renamed folder

**The only test that matters**, and it must be run with the harness's own path scoping
**deliberately disabled for that run**:

| Probe from inside the box | A leak looks like | Cost if it leaks |
|---|---|---|
| read `C:\Windows\System32\drivers\etc\hosts` | the read succeeds | nothing |
| list `C:\Users\matth` | entries come back | nothing |
| write a canary the harness created seconds earlier in its own scratch | the canary changes | one file the harness expects to lose |
| `curl https://example.com` | a response | nothing |
| connect `127.0.0.1:11434` | Ollama answers | nothing |

**With path scoping left ON, every one of these passes whether or not the sandbox exists** — a green
check over the single claim the design rests on, which is instance #15 aimed at the load-bearing
wall.

Plus a **positive control**: the same shell, in the same box, successfully doing ordinary work —
`mkdir`, `git init`, writing a file in its own workspace. A box that contains everything by breaking
the shell is not a box, and without this row the escape probes pass on a shell that never started.

## 8 · What this does NOT decide

* **The provisioning question** — what goes into a team's box at spawn, and who chooses. `PI-MODEL.md`
  §2 says Marlowe decides during the intake interview; the mechanism is indifferent.
* **Whether `SpawnRequest` carries the workspace.** §13-guarded, escalated separately.
* **The Linux backend.** `WorkspaceScope::new()` already refuses on an unverified platform; the
  sandbox should use the same shape, so a non-Windows build gets a **load-time refusal naming the
  missing backend** rather than a silently unsandboxed shell.
* **Whether `bash`'s manifest consequence changes, or only its adjudication.** ADR-026's ceiling is
  a declared property of the tool; making it conditional on the run's box is a change to what a
  declaration means, and that deserves its own argument.
