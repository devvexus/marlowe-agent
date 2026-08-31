# Two hard constraints on the sandbox, and on anyone testing it

**Stated by the human 2026-08-31. These bind the design AND the verification.** They are separate
from the requirement itself, and both are about not damaging the machine while building the thing
that exists to protect it.

## 1. It must never log the user out, or disturb their session

The mechanism runs **inside the user's existing session**. It does not create or switch Windows
sessions, and it does not touch anything the interactive desktop depends on.

**Ruled out on this ground alone**, whatever their other merits:

* Anything invoking `logoff`, `shutdown`, or session manipulation.
* A **Job Object** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` whose handle scope could include the
  harness or any parent — closing it takes the whole tree down, and getting that scope wrong is a
  one-line mistake that kills the daemon and everything above it.
* Killing or restarting `explorer.exe`, `winlogon`, `csrss`, or anything in the session's critical
  path.
* Changing the interactive user's own token, group membership, or profile.

**Acceptable on this ground:** a restricted/AppContainer token applied to a *child* process only; a
separate unprivileged local account used solely as a process identity; a WSL2 or container instance.
Each still has to be judged on whether it actually prevents escape — this constraint only removes
candidates, it does not select one.

## 2. NOTHING VERIFIES THE SANDBOX BY RUNNING A DESTRUCTIVE COMMAND

> *"Make sure it never tries to 'let me test if a dangerous command works — deletes the system —
> oops, looks like it worked'."*

**This applies to the product, to every test, and to every agent working on this repository.** It is
the most dangerous moment in the whole feature: the natural way to prove containment is to do
something terrible and observe that nothing happened, and if the box is not yet working, the
observation is that everything happened.

**The rule: prove escape by REACHING something harmless you should not be able to reach — never by
DESTROYING something you should not be able to destroy.**

Escape is demonstrated by any one of these, and none of them damages anything:

| Probe | What a leak looks like | What it costs if the box is broken |
|---|---|---|
| **Read** a file outside the box that certainly exists — `C:\Windows\System32\drivers\etc\hosts` | the read succeeds | nothing; it is a read |
| **Write** to a **canary path the harness created for this purpose** in its own temp directory | the canary file changes | one file the harness owns and expects to lose |
| **List** the user's home directory | entries come back | nothing |
| **Connect** to a known host, or to `127.0.0.1:11434` | the connection opens | nothing |
| **Spawn** a process outside the restriction | it starts | nothing; it is `cmd /C exit` |

A read that succeeds is exactly as conclusive as a delete that succeeds, and it leaves the machine
intact. **There is no information in the destructive version that the read does not already carry.**

### Forbidden in any test, example, fixture or agent instruction

`rm -rf` outside a temp path, `del /s`, `format`, `diskpart`, `rd /s` on anything not created by the
test itself, writes to `C:\Windows` or `C:\Program Files`, registry writes outside `HKCU\Software\<test key>`,
anything touching `.ssh`, credential stores, or the user's documents — **and any command whose
justification is "to see whether it is blocked."**

### And the canary is the harness's, not the user's

If a probe writes, it writes to a path **the harness created seconds earlier for that probe**, in
its own scratch directory, and deletes afterwards. A probe that writes to a pre-existing user file
to see whether it can is destroying data to learn something a fresh canary would have told it.

## Why this is written down rather than assumed

CLAUDE.md's ledger is nineteen instances of a measurement answering a question adjacent to the one
being asked. **A destructive verification is the opposite failure and it has no ledger entry,
because a project only gets to make it once.**
