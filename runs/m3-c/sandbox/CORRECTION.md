# A worktree can be left. A sandbox cannot. — the correction that decides the mechanism

**Stated by the human 2026-08-31, correcting me mid-design.** Recorded because I had conflated two
things in the sentence *"a git worktree gives you a repo copy for pennies"*, and the conflation is
the one that would quietly produce a sandbox that contains nothing.

## The claim

> *"Assume the worst. The agent gets compromised and turns completely evil. A git worktree can be
> left. A sandbox cannot."*

Correct, and the reason is specific rather than general.

## Why path scoping cannot hold a compromised agent

`WorkspaceScope` / `PathScope::open` (`crates/marlowe-permission/src/scope/`) gate the file tools —
`read`, `write`, `edit`, `glob`, `grep`. Those checks run **inside the harness's own process**, on
arguments the harness parsed.

**`bash` does not go through any of them.** `FileSystemTools::bash` spawns a shell, and that shell
inherits the harness process's filesystem access entire. `cd ..`, an absolute path, a symlink, a
Python one-liner that opens a file by a computed name — none of it consults `WorkspaceScope`, because
`WorkspaceScope` is not in the room. The scope is a property of the *harness's* file tools, not of
the *machine*.

So a compromised agent holding `bash` walks out of a worktree without needing a trick.

**This is why `bash` is `ConsequenceLevel::Irreversible` and escalates on every call.** The approval
prompt *is* the containment for `bash`; there is nothing else. ADR-026 was not caution, it was the
only non-losing move available — and its own reasoning says why the obvious alternative fails:
refining the consequence per-command means parsing the command, which is the Cursor CVE.

## The consequence for the design

> **Remove the escalation without a sandbox and nothing is left. Add the sandbox and the escalation
> becomes unnecessary.**

Therefore:

* **The boundary must be OS-enforced** — a restricted token, a namespace, a separate account — and
  not a directory convention. If the mechanism reduces to *"we point the workspace at a different
  folder"*, **nothing has been built**, and the day someone lifts the `bash` escalation on the
  strength of it is the day it matters.
* **A worktree is PROVISIONING, not containment.** It is a cheap way to put a repo copy *inside* the
  box. It is not an alternative to the box, and any design that treats it as one has substituted
  organisation for enforcement.
* **The acceptance test writes itself, and it is the only one that matters.** Run a `bash` command
  inside a team's sandbox that tries to read and then write a file outside it — an absolute path
  into the user's home, and a `..` traversal — and assert both fail **at the OS**, with the harness's
  path scoping deliberately disabled for that run. With scoping on, the test passes whether or not
  the sandbox exists, which is instance #15 aimed at the one claim the whole design rests on.

## What this does not change

The rest of the model stands: full freedom inside the box, the box holds only what the job needs,
egress stays harness-side because it is disclosure rather than damage, and `marlowe-secretary` keeps
full access precisely because his securities are heavy.
