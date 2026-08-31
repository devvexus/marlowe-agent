# ANGLE: THE MECHANISM — what actually enforces the box on Windows 11, what it costs, and what it cannot do.

The box only has to contain ONE thing, and that reframes the whole problem. `web`, the model call, the journal, and `read`/`write`/`edit`/`glob`/`grep` all execute **in the daemon process** (`FileSystemTools` dispatch, `C:\Users\matth\Projects\Marlowe_Harness\crates\marlowe-exec\src\lib.rs:1999-2001`), walled by `PathScope`. Only `bash` leaves the process — `spawn_shell` at `lib.rs:2523` builds `Command::new(git_bash).arg("-c")` and `run_bounded` at `lib.rs:2584` pipes it. So the question is not "how do I sandbox Marlowe", it is "how do I spawn one child process with no network and a filesystem view of one directory, while the parent still reaches in". That asymmetry is free: the daemon keeps its own token, so the harness reaches into the team folder while the box cannot reach out.

**The winner on Windows 11 is AppContainer, and three of its properties are verified on this machine rather than assumed.** (1) `C:\Program Files\Git` and `C:\Windows\System32` both carry inherited `APPLICATION PACKAGE AUTHORITY\ALL APPLICATION PACKAGES:(RX)` and `(OI)(CI)(IO)(GR,GE)` ACEs (`icacls`, run above) — so an AppContainer child can execute Git Bash and load system DLLs. (2) `C:\Users\matth` carries **no** ALL APPLICATION PACKAGES ACE at all — only SYSTEM, Administrators, `NEUTRINO\matth`, and one capability SID with `(S,X)`. The user's profile is denied to any AppContainer by default, with no code written. (3) `%LOCALAPPDATA%\Packages` exists and `CreateAppContainerProfile` needs no elevation (this shell is not elevated).

Network denial in an AppContainer is not a filter and not an ACL — it is WFP at the ALE connect layers, conditioned on the package SID. A token created with `SECURITY_CAPABILITIES { AppContainerSid, Capabilities: NULL, CapabilityCount: 0 }` holds neither `internetClient` (S-1-15-3-1) nor `privateNetworkClientServer` (S-1-15-3-3), and the kernel drops the connect. **Loopback is additionally blocked for AppContainers by default** — the thing the ROADMAP names as "exactly where an attacker aims" is closed by the same mechanism, not despite it. `CheckNetIsolation LoopbackExempt` is the documented escape hatch and it requires admin, so the exemption cannot be granted by the agent. This is containment in §8.1's exact sense: there is no spelling of `curl` that acquires a capability the token does not hold.

**Three things are unverified and I will not assert them.** (a) Whether MSYS2's runtime — named shared objects, `fork()` emulation — survives AppContainer's redirected object namespace (`\Sessions\N\AppContainerNamedObjects\<SID>`). This is the single largest risk in the design and it is a one-hour spike, not an argument. (b) Whether two processes in the *same* AppContainer can reach each other over loopback (matters for "run a dev server and curl it" inside the box). (c) The exact `windows-sys` feature/module path for `CreateAppContainerProfile` (`Win32_Security_Isolation`, believed correct, check against the pinned version).

**And the finding that changes the sequencing: `bash`'s `Irreversible` escalation IS the current sandbox for the shell path.** ADR-049 §4 measured `curl` returning HTTP 200 from a shell child, and no `EgressPolicy` is consulted there because the adjudicator iterates `Url`-typed parameters and `bash` declares none. The only thing standing between the model and the network on that path today is that every call stops and asks a human. So "securities lifted inside the sandbox" and "the sandbox exists" are **one change, not two** — lifting the escalation first does not trade a little security for speed, it removes the only control that path has.

This revisits ADR-002 **narrowly and says so**: it restores a kernel backstop for `bash` alone, on a path that never had one. It does not put the secretary back in a box, and every word of ADR-002's accepted cost — "a permission-layer bug has no kernel backstop" — remains true for `read`, `write`, `edit`, `glob`, `grep` and `web`, which still run on the daemon's own token.

## AppContainer per team, wrapping `bash` only

**What:** A new crate `crates/marlowe-sandbox` owns one function: spawn a child under an AppContainer token with zero capability SIDs, an ACL-granted view of exactly one directory, and stdout/stderr pipes back to the daemon. `spawn_shell` calls it instead of `Command::spawn` when the run carries a team workspace. Nothing else moves into the box.

**Mechanism:** `DeriveAppContainerSidFromAppContainerName(L"marlowe-team-<id>")` gives a deterministic SID from a name — so the team folder's ACL can be written before the process ever exists, and is reproducible across daemon restarts. `CreateAppContainerProfile` (idempotent; returns `HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)`) creates `%LOCALAPPDATA%\Packages\marlowe-team-<id>\`, once per team, no elevation. Then `InitializeProcThreadAttributeList` + `UpdateProcThreadAttribute(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, &SECURITY_CAPABILITIES{ AppContainerSid: sid, Capabilities: NULL, CapabilityCount: 0 })` + `CreateProcessW(..., EXTENDED_STARTUPINFO_PRESENT, &si_ex)`. Network denial is WFP keyed on the package SID at the ALE_AUTH_CONNECT layers — kernel, not parse. **Instance #17 read in reverse**: `CapabilityCount: 0` here means "no capabilities were granted", the correct reading, and it is only correct because `Capabilities` is NULL — the withholding is structural (there is no array), exactly like `ExposedSet::empty()`, not a numeric limit that something compares against.

**Helps research:** This is the mechanism that lets `bash` stop being `Irreversible`. A research team that can `mkdir -p adr/ADR-001 && git init && python analyze.py` without a modal per call is the difference between a workflow and a demo. The human's ordering — research first — is satisfied by removing the prompt, and removing the prompt is only defensible once the kernel holds the line the prompt was holding.

**Cost:** **Latency**: `CreateProcessW` with an extended STARTUPINFOEX is not materially slower than a plain one (~1-3 ms for process creation); Git Bash's own MSYS2 DLL init dominates at tens of ms. Expected overhead low single-digit ms on a ~50 ms floor — **must be measured, not assumed**. Profile creation is once per team, tens of ms. **Disk**: a few hundred KB of empty structure per team under `%LOCALAPPDATA%\Packages`. **Dependency**: `windows-sys` enters the workspace for the first time (grep confirms zero `windows-sys`/`winapi` in any Cargo.toml today) with features `Win32_Security_Isolation`, `Win32_Security_Authorization`, `Win32_System_Threading`, `Win32_System_JobObjects`, `Win32_System_Pipes`. **Unsafe**: `marlowe-exec` is `#![deny(unsafe_code)]` with one named exception (`pre_exec`); the FFI must live in the new crate, which is the right boundary anyway. **Platform**: Windows-only. `WorkspaceScope::new()` already refuses on an unverified platform (`crates/marlowe-permission/src/scope/mod.rs:232`) — the sandbox should use the same shape, so a Linux build gets a load-time refusal naming the missing namespace backend rather than a silent unsandboxed shell.

**Read by:** `marlowe_exec::spawn_shell` (`crates/marlowe-exec/src/lib.rs:2523`) is the one reader of the sandbox handle. The capability count is read by the Windows kernel's WFP filter engine, not by Marlowe — which is the point: there is no field in Marlowe that could go unread.

## The team workspace root is DERIVED by the harness, never named by a model

**What:** `FileSystemTools`'s `workspace: PathBuf` (`crates/marlowe-exec/src/lib.rs:306`, set by `new` at `:347`) is already a per-host field, and `WorkspaceScope` is stateless — it takes `workspace: &Path` per `open` call. So the wall is already parameterized by root. What is NOT parameterized is which host a child gets.

**Mechanism:** **The blocker is `Ports`.** `pub tools: &'a mut dyn ToolHost` (`crates/marlowe-loop/src/engine.rs:244`), and `Engine::spawn` hands children `tools: ports.tools` verbatim at `engine.rs:2457`, `:3174` and `:3505`. One tool host, one root, for the entire run tree. Per-team roots therefore need `Ports` to carry a **factory** — `trait ToolHostFactory { fn for_workspace(&self, root: &Path) -> Box<dyn ToolHost>; }` — with the root computed by the harness from the run's team identity, exactly as `AgentLevel::child_of` computes a level from a disposition the model merely names. A `workspace` field on `SpawnRequest` would be a **target** in layer 3's sense and must be refused by `composes_spawn_targets` alongside `tools`, `budget_tokens`, `role` and `kind`.

**Helps research:** The human's own example — "the research team creates a folder in their sandbox for each of their ADRs" — requires the folder to persist across turns. That is the whole value: an empty workspace holding only the team's own work beats a cluttered desktop.

**Cost:** **This is the largest structural change in the proposal and it should be priced honestly.** `build_tool_host` (`crates/marlowe-daemon/src/daemon.rs:706`, called at `:2497`) becomes a factory closure; `DaemonToolHost`'s concrete three-layer type (`McpTools<SkillTools<RecallTools<FileSystemTools<WorkspaceScope>>>>`, `daemon.rs:702-704`) becomes a boxed trait object, which loses the static dispatch and must not lose `execute_batch` forwarding — `daemon.rs:720-728` warns in a long comment that a wrapper failing to forward `execute_batch` silently serializes the concurrent fetch path, and `tests/composition_root.rs::a_batch_reaches_the_innermost_host_through_both_wrappers` is the assertion that catches it. Adding a fourth link (the factory) is exactly the event that comment names.

**Read by:** The derived root is read by `PathScope::open` via `FileSystemTools`'s `self.workspace`, and by `spawn_shell`'s `dir` argument (`lib.rs:1559`). A refusal of a model-supplied `workspace` would be read by `Engine::spawn`'s `composes_spawn_targets` check at `engine.rs:2812`.

## Team identity is SESSION-scoped, and that lands on an already-open human question

**What:** The team folder must survive across user messages, and it cannot be keyed on a `RunId`, because `Daemon::ask_streaming_with` builds a fresh `Run::root` per user message.

**Mechanism:** The same run-versus-session boundary that ADR-032 §3.1 leaves loose for egress grants (`ROADMAP.md` open question 4: "a grant lasts one `Run` ... the human is re-asked about an already-approved host on his next turn") and that `SECURITY-AUDIT.md` §8 raises about ADR-023's trust-floor latch ("the latch belongs on the session, not the Run"). A team workspace is a **third** consumer of that same missing scope, and it is the first one where the run-scoped answer is obviously wrong rather than merely inconvenient — a team whose folder evaporates every turn cannot do the thing the human described.

**Helps research:** Naming this as one question with three consumers is worth more than three separate deferrals. It is a pinned-contract decision and it is the human's; surfacing it now stops the sandbox design from silently inventing a fourth scope.

**Cost:** No code. It is a decision that blocks the durable half of the feature; the ephemeral half (a box that exists for one turn) ships without it.

**Read by:** Nothing yet — that is the finding. `ROADMAP.md` lines 69-86 and `SECURITY-AUDIT.md` §8 are where it currently lives, split.

## Job Object with KILL_ON_JOB_CLOSE, shipped in the same change

**What:** Assign the sandboxed shell to a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` memory/process caps.

**Mechanism:** `run_bounded`'s own doc comment (`crates/marlowe-exec/src/lib.rs:2574-2583`) already names this gap precisely: "`child.kill()` kills the shell, not what the shell started ... on Windows there is no Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, which would need a `windows-sys` dependency this crate does not have. So `bash(\"sh -c 'sleep 999 &'\")` leaves the grandchild running." That dependency arrives with the AppContainer work, so the objection dissolves. `CreateJobObjectW` + `SetInformationJobObject` + `AssignProcessToJobObject` before `ResumeThread` (spawn suspended with `CREATE_SUSPENDED`, assign, then resume — otherwise a fast grandchild escapes the window).

**Helps research:** A grandchild that survives the 120 s timeout is a leak today; **inside a sandbox it is a process in the box with nobody watching it**, which is worse. And the memory cap is what stops one team's runaway build from bugchecking the machine — CLAUDE.md records a real `0x139` on this box under memory exhaustion.

**Cost:** ~60 lines in the new crate. One extra kernel object per shell call (negligible). `CREATE_SUSPENDED` + `ResumeThread` adds one syscall pair. No disk.

**Read by:** The kernel reads the job limits. Marlowe reads the job handle only to close it, in `run_bounded`'s drop path — closing it is what fires the kill.

## The ACL grant goes through the HANDLE, and is a load-time error

**What:** Granting the team's AppContainer SID full control of its own directory is done with `SetSecurityInfo` on the already-open `ScopedPath` handle, at team-folder creation, and verified there — not discovered on the first `bash` call.

**Mechanism:** `SetSecurityInfo(scoped.handle(), SE_KERNEL_OBJECT/SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, ...)` takes a HANDLE, which composes exactly with `ScopedPath::handle()` (`crates/marlowe-permission/src/scope/mod.rs:60`) and does not reintroduce the string re-resolution the crate header forbids. Shelling out to `icacls` would work and is tempting, but it is a string-based path operation crossing the wall — and it would be the only one. **The failure mode this closes**: if the ACL is missing, `CreateProcessW` fails with `ERROR_ACCESS_DENIED` and the model sees "bash failed" with no explanation, which reads as a broken tool rather than an unprovisioned box. Same reasoning as `WorkspaceScope::new` refusing at construction rather than at first use (`scope/mod.rs:227-231`).

**Helps research:** A team that cannot write its own folder is a team that burns its budget discovering that. The receipt-shaped answer — refuse at creation, name the reason — is the pattern `Engine::spawn_refused` already uses everywhere.

**Cost:** One extra ACE per team folder. Verified at creation with a re-read of the DACL, which is one syscall. No per-call cost.

**Read by:** The kernel's access check reads the ACE. Marlowe reads it back once, at creation, in the verification — and that read-back is the difference between a declared control and instance #16.

## `run_bounded` is refactored to be spawn-agnostic

**What:** `pub fn run_bounded(mut cmd: std::process::Command, limits: ShellLimits)` (`lib.rs:2584`) takes a `Command`, which cannot express a proc-thread attribute list. It must take something already spawned.

**Mechanism:** `std::os::windows::process::CommandExt` exposes only `creation_flags`, `raw_arg` and `async_pipes` — there is **no** hook for `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`. So `Command` cannot be kept for the sandboxed path. Change the signature to accept a small trait yielding (a wait/kill/exit-code handle, an out reader, an err reader). `child.try_wait()` becomes `WaitForSingleObject(h, 0) == WAIT_OBJECT_0`; `child.kill()` becomes `TerminateProcess`; `child.wait()` becomes `GetExitCodeProcess`. The pipes come from `CreatePipe` + `SetHandleInformation(HANDLE_FLAG_INHERIT)` on the child ends, wrapped as `File` via `FromRawHandle`, and passed in `STARTUPINFOEX.StartupInfo.hStd*` with `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` restricting inheritance to exactly those three. **Do not use `WaitForSingleObject`'s timeout argument** — that is a wall-clock read on a §4-reachable path, which `crates/marlowe/tests/determinism_guard.rs` refuses and has already caught once in this very function (`lib.rs:1561-1566`). Keep the `POLL_MS` sleep-counting loop verbatim.

**Helps research:** Everything `run_bounded` guarantees — the output cap that killed a `0x139` risk, the timeout, the reader grace, the "the command did not finish" body text — must survive into the box, or the box trades containment for the hang the audit removed.

**Cost:** A ~150-line refactor of the most safety-relevant function in `marlowe-exec`, plus the existing `shell_bounds.rs` test (which the header at `lib.rs:2407-2411` records as having drifted once already because it built its own copy of the shell command). The `ShellLimits::production()` injection seam exists precisely so this stays testable with a sub-second child.

**Read by:** `FileSystemTools::bash` (`lib.rs:1567`) is the only caller. `stopped` and `flooded` are read at `lib.rs:1579-1600` and turned into body text and metrics — those readers are what make the caps non-vacuous today and must keep reading the same fields.

## `bash`'s consequence level becomes a property of the PROFILE, not of the tool

**What:** `bash` is `ConsequenceLevel::Irreversible` in `crates/marlowe-tools/src/builtin.rs` and its comment (line 16) is right and must be preserved: refining it per-command means parsing the command, which is the Cursor CVE. The sandbox is what makes a **third** answer exist, and the ADR must say so rather than implying ADR-026 was careless.

**Mechanism:** The declared level stays `Irreversible` — it is "the ceiling a tool can reach", and the tool's registration should not lie about that. What changes is the *blast radius the adjudicator is reasoning about*: a run whose profile carries a sandboxed workspace has a shell that reaches nothing but that directory and no network at all, so `Irreversible` is no longer the right ceiling **for that profile**. Express it where profiles are already validated — `CapabilityProfile::new` (`crates/marlowe-loop/src/profile.rs:277`), the same constructor that already refuses `reads_untrusted` + tools, `reads_untrusted` + egress, `Master` + `ask`, and `ToolSpawned` + tools. No wildcard arm; a new variant is a compile error there by construction (`profile.rs:311`). **This is not a filter**: no command text is inspected. The level is decided by which box the run is in, before any argument exists.

**Helps research:** This is the entire user-visible payoff. Without it, the team still stops and asks on every shell call and nothing about the workflow improved.

**Cost:** It is a §13-guarded edit (`profile.rs` is in `PROTECTED`), so it arrives with a `DECISIONS.md` entry and an observed permission prompt. It also needs a mutation test in both directions: deleting the sandbox condition must make an unsandboxed run stop asking (red), and deleting the escalation must make a sandboxed run's `bash` reach the network (red, via the network probe below).

**Read by:** `marlowe_permission::adjudicate` reads the consequence level. The sandbox flag on the profile would be read by whatever `adjudicate` consults — and **if no function reads it, it is instance #16 and the whole feature is decorative.** Name the reader in the ADR or do not add the field.

## Docker per team, declared as the fallback and never the default

**What:** If the Git Bash spike fails, `docker run -d --network=none --name marlowe-team-<id> -v <ws>:/ws debian:slim sleep infinity`, then `docker exec` per `bash` call.

**Mechanism:** Docker Desktop 28.3.3 is installed on this machine and the `docker-desktop` WSL2 distro exists (currently Stopped). `--network=none` gives a container with only a loopback interface and no route out — genuinely airtight, kernel-enforced by a Linux network namespace, and the loopback inside is the container's own, so a dev server started in the box IS reachable from the box, which is the one thing AppContainer may not give (unverified item (b)).

**Helps research:** Real bash, real Linux, real `apt`. A research team gets a complete userland with no MSYS2 questions at all.

**Cost:** **Docker Desktop becomes an install-time dependency of the shell working**, which is the same K6 objection `DaemonConfig::reranking`'s doc comment records against requiring the cross-encoder to talk at all (`crates/marlowe-daemon/src/daemon.rs:229-238`) — and Docker Desktop is 2 GB and a VM, not 60 MB. Latency: `docker exec` warm is ~80-150 ms per call versus ~50 ms today; a container start is ~300-800 ms, once per team. Disk: ~80 MB image shared, plus a thin writable layer per team. **And the real design cost: the box is on the other side of a filesystem boundary `PathScope` does not own.** The bind mount re-resolves paths in the Linux kernel, so the handle discipline the walk exists to enforce (`scope/mod.rs` header, brief §8.3) simply does not extend into the container. That is not fatal — the container can see nothing but the mount — but it must be stated rather than assumed to carry over.

**Read by:** Nothing in Marlowe reads a container's network mode; the Linux kernel does. Marlowe would read `docker inspect`'s `NetworkMode` once at team creation as the load-time verification, which is the only way this is evidence rather than a claim.

**measurement:** **Every one of these needs its control, because a probe that reads the same when the box is broken is instance #15.** Run each pair in one session, print both numbers.

**1. The box denies the internet.**
`bash("curl -s -o /dev/null -w '%{http_code}' --max-time 5 https://arxiv.org; echo rc=$?")`
- Sandboxed: expect a connect failure and a non-zero `rc`. Expect **not** `200`.
- **Control (mandatory)**: the identical call on the unsandboxed path must print `200`. ADR-049 §4 already published that `200` from `cmd /C` to arxiv.org, so this control has a recorded prior value — if it does not reproduce, you have measured that arxiv is down or `curl` is missing, not that the box works.

**2. The box denies loopback — the one the ROADMAP names.**
`bash("curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:11434/api/tags; echo rc=$?")` (Ollama).
- Sandboxed: expect failure. Unsandboxed control: expect `200` whenever the daemon is up.

**3. `web` still works — the sandbox did not break layer 4 by breaking the network for everything.**
One `web` fetch through the approval modal in the same turn, from the same run. Expect a `DocumentRef` with a non-zero char count. Control: the same host **declined** at the modal must produce `NeedsApproval` → blocked. This is the assertion that the daemon-side network is untouched; without it, "no network in the box" is indistinguishable from "no network anywhere".

**4. Full freedom inside — the human's actual requirement.**
`bash("mkdir -p adr/ADR-001 && echo x > adr/ADR-001/notes.md && ls -R adr | wc -l")` → prints a line count, **with no approval prompt**. Control: the same shell writing to `/c/Users/matth/Desktop/x` must fail with a permission error. Two numbers, one run.

**5. The team cannot see the machine.**
`bash("ls /c/Users/matth 2>&1 | head -1; cat /c/Users/matth/.ssh/id_rsa 2>&1 | head -1")` → permission denied on both. Control: unsandboxed, the first lists the directory. (The ACL evidence above predicts this: `C:\Users\matth` carries no ALL APPLICATION PACKAGES ACE.)

**6. The number the human's ordering makes decisive — latency.**
50 iterations of `bash("true")`, sandboxed and unsandboxed, print both medians and the delta in ms. **Take them in separate sessions, not interleaved**, and take them when nothing else is building: CLAUDE.md's parallel-sessions form 6 is a 16-core `cargo build` inflating a timed measurement ~10% and producing a complete, plausible, wrong table. If the delta exceeds ~10 ms the design has to say so, because "it absolutely may not get to a point where speed is hurt" is the governing constraint.

**7. Disk per team.**
`du -sh` of `%LOCALAPPDATA%\Packages\marlowe-team-<id>` plus the team folder, printed at creation.

**8. The mutation tests, which are what make 1 and 2 evidence rather than description.**
Delete the `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` call → probe 1 must go from failure to `200` (red). Grant `internetClient` (S-1-15-3-1) in the capability array → probe 1 must return `200` and probe 2 must still fail (which also confirms loopback and internet are separately governed). Neither of these is a unit test; both are live probes, for the reason `docs/design/REDTEAM-SESSION.md` and the layer-3 note in CLAUDE.md both give.

**residual_risk:** **1. The exfiltration channel this design CREATES, and it is the one to argue about.** The box has no network — but the team writes files the parent later `read`s. Content the team's own model authored is `AgentObserved`, not `UntrustedContent`, so ADR-023's latch does not fire on it. A worker fetches a poisoned page (harness-side, via `web`), reads it inside the box, "summarizes a finding", writes it to `adr/ADR-007/notes.md`, and the parent reads that file and acts on it — with an approved host, on the parent's own network, with a clean trust floor. **The workspace becomes a laundering surface, and it launders through the tool the sandbox is supposed to make safe.** Layer 2's worst-case-over-lineage rule is exactly what should stop this, and it cannot, because the lineage is broken by a filesystem round trip that no `derivation` vector records. This is the same shape as `ingest` hardcoding `derivation: Vec::new()` (ROADMAP open question 2). Do not ship the sandbox claiming it reduces injection risk; on this axis it increases it.

**2. The sandbox is a box around `bash`, not around Marlowe.** `read`, `write`, `edit`, `glob`, `grep` and `web` all run on the daemon's own token, unsandboxed, and reach the user's entire filesystem. ADR-002's accepted cost — "a permission-layer bug has no kernel backstop ... it is now the only wall on the ordinary path" — is **unchanged for six of the seven tools**. A traversal defect in `scope/walk.rs` is exactly as severe after this change as before it. Anyone reading "Marlowe now has a sandbox" will get this wrong; the ADR must lead with it.

**3. Unbounded disk inside the box.** A Job Object caps memory and process count; there is no disk quota without FSRM, which needs admin. A team can fill the volume. Nothing here stops that, and nothing proposed does.

**4. Three unverified claims, restated so they are not quietly promoted to facts.** (a) Whether Git Bash/MSYS2 runs at all under an AppContainer — its named-object and `fork()` emulation against a redirected `\Sessions\N\AppContainerNamedObjects\<SID>` namespace is genuinely unknown to me. If it fails, the fallbacks are busybox-w32 (a ~700 KB static shell, but the ADR-026-neighbour argument that "the tool is named bash and the model writes bash" cuts against it) or Docker. (b) Whether two processes in the *same* AppContainer can reach each other over loopback — if not, "run a dev server and curl it" is broken inside the box, and Docker is the only option that gives it. (c) The `windows-sys` module path for `CreateAppContainerProfile`. All three are answered by one probe.

**5. Loopback exemption is a real escape hatch, and it is admin-gated — which is the reason it is acceptable.** `CheckNetIsolation.exe LoopbackExempt -a -p=<SID>` re-opens loopback for a package, permanently and machine-wide. The agent cannot run it unelevated. But a *user* who runs it once to debug something has silently disabled probe 2 forever, and **probe 2 would still print a failure only until someone did that** — so the probe must be re-run, not cited, exactly as CLAUDE.md's measurement-scoping rule requires.

**6. Sequencing risk, stated as an instruction.** `bash`'s `Irreversible` escalation is the ONLY egress control on the shell path today (ADR-049 §4: no `EgressPolicy` is consulted, because the adjudicator iterates `Url`-typed parameters and `bash` declares none; measured `curl` → HTTP 200). If the escalation is lifted before the box is verified by probes 1 and 2, the product goes from "a human sees every shell command" to "nothing sees any of them" in one commit. **The two changes ship together or not at all.**

**7. Windows-only.** The whole mechanism is `#[cfg(windows)]`. `WorkspaceScope::new` already refuses on an unverified platform and the sandbox must adopt the same load-time refusal, or a Linux build silently runs an unsandboxed shell under a profile that says it is sandboxed — a permissive default making a mismatch unobservable, which is the family CLAUDE.md names four bugs from.

**cheapest_first_step:** **One standalone Rust probe, ~120 lines, written in the scratchpad — outside the workspace, touching no Marlowe crate, needing no ADR and no §13 approval.** It creates an AppContainer profile named `marlowe-probe`, derives its SID, grants that SID full control of one scratch directory via `SetSecurityInfo`, and launches `C:\Program Files\Git\bin\bash.exe -c '<script>'` in it with `SECURITY_CAPABILITIES { Capabilities: NULL, CapabilityCount: 0 }`, capturing stdout through a `CreatePipe` pair.

The script is one line and it answers everything at once:
```
echo shell=$BASH_VERSION;
curl -s -o /dev/null -w 'net=%{http_code}\n' --max-time 5 https://arxiv.org || echo net=FAIL;
curl -s -o /dev/null -w 'loop=%{http_code}\n' --max-time 5 http://127.0.0.1:11434/api/tags || echo loop=FAIL;
ls /c/Users/matth >/dev/null 2>&1 && echo home=READABLE || echo home=DENIED;
touch ./probe.txt && echo ws=WRITABLE || echo ws=DENIED
```

Five lines of output settle the design:
- `shell=5.x` → **Git Bash runs under AppContainer**, the largest unknown, closed. Empty or a crash → the whole AppContainer branch is dead and Docker is the answer, discovered in an hour instead of after the `run_bounded` refactor.
- `net=FAIL` and `loop=FAIL` → containment works, including the loopback case the ROADMAP flags.
- `home=DENIED` → the ACL evidence gathered above (`C:\Users\matth` has no ALL APPLICATION PACKAGES ACE) holds in practice, not just on paper.
- `ws=WRITABLE` → the grant-through-handle mechanism works and the team can do its job.

**Then run the exact same script through today's unsandboxed `spawn_shell` and print both columns side by side.** Without that control the sandboxed column is unreadable — `net=FAIL` reads identically whether the box works or `curl` is not on the PATH, and that is instance #15 in one command. ADR-049 §4's published `200` is the prior value the control must reproduce.

Nothing in `crates/` changes. If the probe comes back clean, the design is real and the sequencing (probe → `marlowe-sandbox` crate → `run_bounded` refactor → the `ToolHostFactory` change → the profile-level escalation change, last) is worth an ADR. If it comes back dirty, an hour was spent and the Docker branch is priced honestly instead of being the thing discovered when the Windows branch fails halfway.

### Rejected

- **Windows Sandbox (`WindowsSandbox.exe`)** — Not even installed on this machine — `Test-Path C:\Windows\System32\WindowsSandbox.exe` returns False, so it is an optional-feature install (and enabling it needs admin). Beyond that it is disqualified on three independent axes for a per-team box: it is a full Hyper-V VM costing ~1-2 GB of RAM and seconds to start; it has historically supported only one running instance, so "one per team" is not expressible; and it is **stateless by design** — the container is destroyed on close, which deletes exactly the ADR folders the human's own example says the team must accumulate. It is the right tool for opening one untrusted installer, and the wrong tool for a durable team workspace.
- **A restricted token (`CreateRestrictedToken`, deny-only SIDs, SAFER)** — **It does not deny network, and that is the whole requirement.** Restricted tokens gate access to securable objects — files, registry keys, named objects — via deny-only SIDs and a restricting-SID intersection. Sockets are not ACL'd against a token in a way that stops an outbound TCP connect, and there is no WFP condition keyed on "has restricting SIDs". It would confine the filesystem (duplicating what `PathScope` and an ACL already do) while leaving `curl` working, which is the exact half-measure ADR-049 §4 already measured. AppContainer is the variant of this idea that ships with the network filter attached; there is no reason to take the one without it.
- **Job Objects as the sandbox** — A Job Object is a resource and lifetime container, not a security boundary: it caps CPU, memory, process count and UI access, and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` guarantees cleanup. **It has no network limit of any kind.** Rejected as the box — and adopted anyway, as a separate idea above, because it closes the grandchild leak `run_bounded`'s own doc comment names at `crates/marlowe-exec/src/lib.rs:2574-2583`. Two mechanisms for two different questions, stated separately so neither is mistaken for the other.
- **A separate unprivileged local user plus a Windows Firewall outbound block rule scoped to that user** — Four costs, any one of which is disqualifying. (1) **Creating a local user requires admin**, and this shell is not elevated — so the harness cannot provision a team on its own, which kills "cheap enough to create per team". (2) Running as that user needs `CreateProcessWithLogonW` and therefore **a credential at rest**, which is a worse security object than the thing being defended. (3) **Firewall rules require admin and are machine-global state that outlives the harness** — a rule the agent cannot create, a user can disable, and nothing in the product would notice. The default outbound policy is Allow, so this is an added block rule, not a tightened default. (4) `-LocalUser` on an *outbound* rule is documented but I have **not verified** it filters as claimed on this build; I will not assert it. Meanwhile the filesystem half still needs the same ACL work AppContainer needs, so it buys nothing on that axis either. The one thing it has over AppContainer is that it needs no unsafe FFI — not enough.
- **WSL2 with `unshare -n`** — The distro exists on this machine (`kali-linux`, WSL2, Stopped), so it is genuinely available — and it is still wrong here. `unshare -n` needs root inside the distro, which is the user's distro, not a harness-owned one; provisioning a second distro costs GBs of VHDX per team, which fails "cheap per team". The killing cost is the filesystem: the team's workspace lives on the Windows side, so the shell reaches it over `/mnt/c` (drvfs) or the harness reaches into `\\wsl$`, and drvfs per-file overhead is tens of milliseconds — a `grep -r` over a real tree is brutal, and "speed/accuracy/knowledge must not be hurt" is the governing constraint. **And the structural objection: the handle discipline the whole `scope/walk.rs` design exists to enforce does not cross into the Linux kernel.** `bash`'s cwd would be resolved by a filesystem Marlowe's wall cannot see, which is a boundary change disguised as a deployment choice.
- **A persistent sandboxed shell per team, with commands fed over a pipe** — Very attractive on latency — it amortizes the ~50 ms Git Bash startup to zero — and it destroys everything `run_bounded` guarantees. The 120 s timeout would kill the *shell*, so a timed-out command loses the team's entire shell state anyway, which is the only thing persistence bought. Framing one command's output needs a sentinel (`echo __MARLOWE_DONE__`), and the exit code needs `echo $?` — **so the harness would be parsing a stream the model can write into.** A model that emits `echo __MARLOWE_DONE__; echo 0` forges a successful completion. That is a parser standing between the harness and the truth about whether a command succeeded, which is §8.1's shape in a new place. Rejected, and worth recording as rejected because the latency argument will be made again.
- **A helper launcher process (`marlowe.exe --sandbox-exec`)** — Adds a process, a hop, and an IPC surface, and buys AppContainer nothing — `CreateProcessW` with an attribute list works fine from inside the daemon. It IS the right shape for the separate-local-user option (which needs `CreateProcessWithLogonW` and a credential), so it is rejected together with that option rather than on its own.
- **Refining `bash`'s consequence level by inspecting the command** — Not proposed and explicitly not revisited. `crates/marlowe-tools/src/builtin.rs:16` is right: refining per-command means parsing the command, which is the Cursor CVE — an allowlist that auto-approved the commands the attacker needed. Brief §8.1: filtering does not work. The sandbox is what makes a third answer exist, and the ADR should say that ADR-026 was **correct on the options it had**, not that it was careless. The level moves because the blast radius moved, and no command text is ever read.

---

# ANGLE: What sandboxing agent teams actually retires, what it does not, and what the security model pays — mechanism by mechanism, against the code at HEAD.

The claim "a sandbox retires most in-process security for teams" is TRUE for exactly one mechanism and FALSE for the other four, and the reason is a single structural fact: **`web` is executed by the harness, in the daemon process, not by the agent** (`crates/marlowe-exec/src/lib.rs:1717`, `marlowe_net::fetch` called from `FileSystemTools::web`). A box around a team is a directory. `web` is a socket in an unsandboxed process. They are not on the same side of any wall. So the box contains DAMAGE and contains no DISCLOSURE at all, and the human's requested lift of ADR-032 is the one item that must be refused.

Rulings, each verified by reading the file:

1. **`bash`'s `Irreversible` — YES, it can drop, and this is the whole win.** Not by changing the level and not by parsing the command. `builtin.rs:16` is right that the declared level is the ceiling a tool can REACH; what a shell can reach is a property of the (tool, container) pair, not of the tool. A second registration — sandboxed `bash` at `Reversible` — selected by the harness from the run's container, is a different manifest read at the same line (`adjudicate.rs:422`), no new field. Cost if the box leaks: `required_tier(Reversible) = Act` (`adjudicate.rs:245`), the daemon runs at `Act`, so a leak is silent arbitrary code execution with no human in the loop. That is why the container must be a kernel object and not `current_dir(dir)`, which is all `spawn_shell` does today (`marlowe-exec/src/lib.rs:2532`).
2. **ADR-032's per-host approval — DO NOT LIFT.** See above. Additionally it is already once-per-host-per-turn via `grant_egress_host`, so a 30-source arXiv pass costs ONE prompt, not thirty. What actually hurts research speed is that the grant dies at the turn boundary (`Run::root` per user message, `daemon.rs:2609`) — the fix that serves his ordering is widening the grant's scope (ADR-068's open question) and pre-seeding a team's allowlist, not deleting the check.
3. **`blocks_composed_targets` — not retired, ALREADY INERT, and for an unrelated reason.** `origin <= UntrustedContent` (`adjudicate.rs:50-52`); every child return and every quarantined-reader note crosses at `AgentInferred` (`engine.rs:2247`, `engine.rs:~3409`). SECURITY-AUDIT #1. An ADR that credits the sandbox for this would record an accident of ADR-041/042 as a deliberate trade.
4. **Layer 1 — a different job, keep it.** The box bounds where a decision's consequence lands; quarantine bounds who gets to make the decision. It is also nearly free already: ADR-042 made `web` cost zero model calls, and only `read(ref=…)` pays (one call per group of 6, `MAX_SOURCES_PER_READER`, `engine.rs:67`).
5. **Path scoping — NOT redundant, and the framing is backwards.** `bash` is not path-scoped at all today: step 3 opens handles only for `Path`/`WritePath` params (`adjudicate.rs:331-339`), `bash` declares `cwd` and a `command` that is a Target, and `spawn_shell` runs an arbitrary command line. `cat ~/.ssh/id_rsa` is unguarded. A sandbox is not redundant with path scoping — it is the FIRST thing that ever bounds the shell.

And the finding that outranks all five: **per-team workspaces are not expressible today.** `Engine` holds one `workspace: PathBuf` (`engine.rs:433`), the adjudication reads `workspace: &self.workspace` (`engine.rs:1835`), and `Engine::spawn` hands the child `tools: ports.tools` (`engine.rs:3174`) — the same `FileSystemTools` built once per turn from `self.config.workspace` (`daemon.rs:2497`). Children share the parent's root by construction. This is plumbing before it is containment.

## Sandboxed `bash` is a SECOND MANIFEST, not a lowered level

**What:** Register a second `bash` capability manifest whose declared `ConsequenceLevel` is `Reversible`, selected by the harness when the run holds a container handle. The interactive `bash` stays `Irreversible`, unchanged, forever.

**Mechanism:** `marlowe-tools/src/builtin.rs:16` states the rule that makes this legitimate: the declared level is the CEILING A TOOL CAN REACH. Reach is a property of the (tool, container) pair. A shell whose every reachable object is a disposable directory has a genuinely lower ceiling — that is a fact about the container, not an opinion about the command, so it is not the Cursor CVE. The harness picks the manifest from the run's container; no model names it and no command string is parsed.

**Helps research:** This is the entire workflow unblock. `adjudicate.rs:422` returns `NeedsApproval` for `Irreversible` BEFORE the tier comparison, so today every single shell call in a research worker stops and asks — and a child that stops gets `PauseReason::AwaitingApproval`, which the parent's window renders as `[child stopped] it needed an approval, and a child run has nobody to ask` (`engine.rs:~3238`). A research team that cannot run one shell command without a human is not a research team.

**Cost:** Latency: zero — same adjudication path, same line. Disk: zero. The real cost is the leak case: at `Reversible`, `required_tier(Reversible) = Act` (`adjudicate.rs:245`) and the daemon runs at `Act`, so `Outcome::Allowed` with NO prompt. A leaked box converts directly to silent arbitrary code execution as the user. The container must therefore be a kernel object (AppContainer token / Job Object on Windows), not `current_dir` — which is literally all `spawn_shell` does now (`marlowe-exec/src/lib.rs:2532`).

**Read by:** `adjudicate::adjudicate`, line 422 — `if manifest.consequence() == ConsequenceLevel::Irreversible`. No new field, no new branch, one existing reader. The load-time form: the sandboxed manifest is only constructible from a run holding a container handle, so a `Reversible` shell outside a box cannot be built rather than being refused at call time.

## The egress approval STAYS, and the lift is a PRE-SEEDED team allowlist

**What:** Refuse the human's request to lift ADR-032 for sandboxed teams. Instead, let a team be created with `EgressPolicy::AllowApproved { granted: [...] }` already populated — arxiv.org, crossref.org, docs.rs, whatever the team's job is — approved ONCE by the human at team creation.

**Mechanism:** `EgressPolicy::permits` (`marlowe-permission/src/egress.rs:218`) is `self.grants(host) && declared.iter().any(...)`. Pre-seeding `granted` makes every fetch to a research host silent; a host the ATTACKER chose is still ungranted and still hits `adjudicate.rs:374`'s `NeedsApproval`. Deny-by-default is preserved; the prompt burden goes to zero on the hosts the work needs.

**Helps research:** It gives him what he asked for — no prompts during research — without giving up the only live control on the exfiltration leg. And the honest accounting: the current cost is already ONE prompt per host per turn, not per fetch, because `grant_egress_host` is wired (ADR-032 §3.1). Thirty arXiv sources cost one prompt today. The thing that actually costs him prompts is the turn boundary resetting the grant (`Run::root` per user message, `daemon.rs:2609`) — that is ADR-068's open scope question and it is the right lever.

**Cost:** Latency: zero. Disk: a host list per team, bytes. Cost of NOT doing this — of lifting the check outright — is total: `web` runs in the daemon (`marlowe-exec/src/lib.rs:1717`), so no container the team runs in touches it, AND the composed-URL block that would otherwise stop `read(ref)`-derived exfiltration is inert (see the latch entry). Lift the approval and there is nothing at all between an attacker-shaped summary naming a URL and an outbound GET carrying the user's source.

**Read by:** `EgressPolicy::permits` (`egress.rs:218`), called from `adjudicate.rs:369`. `CapabilityProfile::grant_egress_host` is the only mutable route (`marlowe-loop/src/profile.rs`), and the child inherits it: `Engine::spawn` passes `run.profile.egress().clone()` (`engine.rs:~2888`), so a team-level seed reaches every worker without a second mechanism.

## Record the latch as INERT, not as lifted

**What:** The ADR must state that ADR-023's latch does not fire on the path attacker prose takes, that this is true TODAY and independent of sandboxing, and that repairing it later is expected to make it bite `web`'s `url` and `run`'s `exposed_tools` — which is the correct outcome and must not be 'fixed' by re-lifting it.

**Mechanism:** `blocks_composed_targets(origin) = origin <= TrustClass::UntrustedContent` (`adjudicate.rs:50-52`). Every quarantined-reader note is pushed at `TrustClass::AgentInferred` (`engine.rs:2247`) and every child return crosses at `AgentInferred` (`engine.rs:~3409`, `Block::new(SourceKind::ChildResults, note, TrustClass::AgentInferred)`). `AgentInferred > UntrustedContent`. SECURITY-AUDIT #1, verified by reading both sites.

**Helps research:** It prevents the worst possible outcome of this decision: a future session reading 'teams are sandboxed, so composed targets are allowed' and deleting the guard, at which point repairing finding #1 becomes a regression instead of a fix. It also identifies the two targets whose protection genuinely survives a sandbox — a URL and a child's capability set, both of which LEAVE the box — versus the two it does not — a path and a shell command, both of which stay in it.

**Cost:** Zero code. One `DECISIONS.md` entry, which SECURITY-AUDIT #1 already demands in those words: 'This needs a `DECISIONS.md` entry, not a patch.'

**Read by:** Nothing reads a decision record — that is the point, and it is why this entry is a recording rather than a control. The enforcement sites are `adjudicate.rs:309` (tool targets) and `engine.rs:2812` `composes_spawn_targets` (spawn targets); both stay, both stay currently silent.

## Keep layer 1; buy latency by RAISING the group size, not by deleting the reader

**What:** The quarantined reader stays inside the box. If a sandboxed team needs more throughput, raise `MAX_SOURCES_PER_READER` for that team — and record that this is a fidelity trade, measured, not a containment trade.

**Mechanism:** `condense_chunk` builds a child on `CapabilityProfile::quarantined_reader()` — `ExposedSet::empty()`, `EgressPolicy::DenyAll`, `AgentLevel::ToolSpawned` (`profile.rs:389`) — and returns a length- and character-class-validated `CondensedResult`. A box bounds where a decision's CONSEQUENCE lands. Quarantine bounds WHO GETS TO MAKE the decision. A boxed worker's model still reads the page and still decides; the box does not stop it obeying, it only limits what obeying costs.

**Helps research:** ADR-042 already removed most of the cost the human would be trying to escape: `web` returns a `DocumentRef` at `AgentObserved` and costs ZERO model calls; only `read(ref=…)` pays (`marlowe-exec/src/lib.rs:1628` — 'a research pass that fetches thirty pages and reads three of them pays for three'). Plus a BLAKE3 content cache (`content_key`, `engine.rs:96`) makes repeated sources free. Deleting the layer buys much less than it looks like it buys.

**Cost:** One model call per group of `MAX_SOURCES_PER_READER = 6` (`engine.rs:67`), serialised against the parent's own generation because `OLLAMA_NUM_PARALLEL=1` (AGENT-DIRECTORY.md:213) — 30 read sources = 5 serialised reader calls. Raising the group size trades that for fidelity: ADR-041 bounds it at 6 precisely because 'A can influence how B is described'. That is a quality number and must be measured on the eval, not asserted.

**Read by:** `Engine::condense_batch`, `engine.rs:2231` — `for chunk in pending.chunks(MAX_SOURCES_PER_READER)`. The trigger is `blocks_composed_targets(outcome.trust)` at `engine.rs:2151`, keyed on the trust class rather than the tool name, so it already covers any future untrusted-returning tool.

## Path scoping stays, and gains a per-run root — ONE definition, read by both sides

**What:** Move the workspace root from `Engine` to `Run`, and make `FileSystemTools` take it from the same place the adjudicator does. Do not touch `scope/` (it is §13-guarded and already correct).

**Mechanism:** `WorkspaceScope` is STATELESS — its only field is `_gated: ()` (`scope/mod.rs:219-224`) — and the root arrives per call: `self.scope.open(manifest.paths(), req.workspace, value, access)` (`adjudicate.rs:343`). So per-team roots are already the shape scoping takes; you change an argument, not a mechanism. Re-implementing scoping per box would be pure waste.

**Helps research:** This is the actual blocker on the human's design and nobody has named it. Today: `Engine` holds one `workspace: PathBuf` (`engine.rs:433`, set at `:595`/`:603`), the adjudication reads `workspace: &self.workspace` (`engine.rs:1835`), and `Engine::spawn` hands the child `tools: ports.tools` (`engine.rs:3174`) — the same `FileSystemTools` built once per turn from `self.config.workspace` (`daemon.rs:2497`). **A child physically cannot have its own workspace root.** 'The research team creates a folder in its sandbox for each ADR' is not expressible at HEAD.

**Cost:** Real engineering, in `engine.rs` and `daemon.rs` (§13-adjacent but not §13-guarded). The hazard to name up front: there are TWO definitions of the workspace root today — `Engine::workspace` (used for adjudication) and `FileSystemTools::workspace` (used at `marlowe-exec/src/lib.rs:1559` as `bash`'s default cwd, and at `:1100/:1114/:1371/:1392/:1394` for `glob`/`grep` relativisation). They agree only because both read `config.workspace`. Give a run its own root and change only one of them, and the adjudicator scopes team A while the shell starts in team B — a mismatch with no failing test. Make it one field, read by both.

**Read by:** `Adjudicator::adjudicate` step 3, `adjudicate.rs:343`; and `FileSystemTools::bash`, `marlowe-exec/src/lib.rs:1559` (`unwrap_or_else(|| self.workspace.clone())`). Those two are the readers, and today they are two fields.

## LOOPBACK IS THE HOLE, and the daemon's own port is the worst instance

**What:** Before any 'allow loopback so Ollama and dev servers work' rule is written: the daemon has no authentication, and `SocketApprovals` answers on the connection that asked. A boxed shell with loopback access can drive the UNSANDBOXED daemon and approve its own requests.

**Mechanism:** SECURITY-AUDIT #4, verified as a standing finding: any local process connects to the fixed port and drives `read`/`edit`/`bash`/`web`/`remember`, and the attacker is also the approval authority. ROADMAP §3 already flags loopback as 'exactly where an attacker aims once anything on loopback can proxy outward' — and the highest-value proxy on that loopback is Marlowe itself, running as the user, outside the box.

**Helps research:** Naming it now is what stops the sandbox from being decorative. A container that permits loopback while the daemon is unauthenticated is not a container: the escape is one `curl` to a fixed port, and it lands with FULL interactive capability including `bash` at `Irreversible` that answers its own prompt.

**Cost:** Either the container denies loopback (and the team loses dev servers, and Ollama must be reached through a mechanism the harness owns rather than by the agent curling it), or the daemon gets authentication first. There is no third option that is honest. Deciding this is cheap; discovering it after shipping is not.

**Read by:** Nothing reads it today — that is the finding. Whatever is chosen, the reader must be the container's own network policy (an AppContainer token's capability set), not a string check in Rust, because a string check is a filter and `$(echo c)url` beats it (brief §8.1).

## Pre-commit: a sandboxed team never holds a secretary tool, expressed as a LEVEL rule

**What:** Write into the ADR that no team profile may ever hold a send-as-user, email, calendar or payment tool, and enforce it in `CapabilityProfile::new`'s level match rather than by tool-list convention.

**Mechanism:** `CapabilityProfile::new` already has a total, wildcard-free match on `AgentLevel` (`profile.rs:311-373`) whose comment says a sixth variant is a compile error rather than a silent default. It already refuses `run` to a `Master` holding working tools and refuses `ask` to a `Master`. A rule that `TopAgent`/`Master`/`Worker` may not hold a secretary tool goes in the same match, with the same construction-time failure.

**Helps research:** It costs research nothing — no research team wants to send mail — and it closes the question before the surface exists. Today the answer to 'can a team reach `marlowe-secretary`' is NO for a schedule reason, not a defence reason: no email or calendar tool is registered (the builtin set is the eleven at `builtin.rs:37`), and the only secretary-shaped channel is `EscalationDesk::secretary_notice` (`marlowe-daemon/src/escalation.rs:193`), which returns a `Notice` and is the desk's record, not the agent's. That is an absence, and absences get filled.

**Cost:** Zero latency, zero disk, a few lines in a §13-guarded file — which means it arrives with a `DECISIONS.md` entry and a human's approval, as it should.

**Read by:** `CapabilityProfile::new`, the `AgentLevel::TopAgent { .. } | AgentLevel::Worker` and `AgentLevel::Master` arms (`profile.rs:361-373`). Construction-time failure, not a call-time refusal — so an unbuildable profile, not a blocked call.

**measurement:** **The number that proves the box, and the control that makes it evidence.**

Egress from a boxed shell — the one claim the whole design rests on:

```
# inside a sandboxed team run
bash("curl -s -o /dev/null -w '%{http_code}' https://example.com")   # must print 000
```

The control is the identical call from an UNSANDBOXED interactive run, which must print `200` — that is ADR-049 §4's already-measured result (`curl` to arxiv.org returns HTTP 200) and it is the reading that must change. Without the control, `000` reads identically whether the container works, `curl` is missing, or the network is down: instance #15 exactly.

Second control, non-optional given the loopback decision:

```
bash("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:<daemon_port>/")
```

Whatever loopback policy is chosen, this must print the number that policy predicts. If loopback is allowed and this prints anything but a refusal, the sandbox is decorative — see SECURITY-AUDIT #4.

Workspace separation:

```
# two teams, A and B
bash("ls ..")   # in team A, must not list team B's directory
```

The control is the SAME call on today's build, which must list it — because `Engine::spawn` hands the child `ports.tools` (`engine.rs:3174`) and there is one `FileSystemTools` per turn. A test asserting only that team A sees its own files is green on a shared workspace and proves nothing.

Prompt burden, which is the number that should decide the ADR's emphasis and costs nothing to take now:

```
sqlite3 "$PROFILE_ROOT/journal.db" \
  "select json_extract(payload,'$.tool'), json_extract(payload,'$.outcome'), count(*)
   from journal where kind='permission_decided' group by 1,2 order by 3 desc;"
```

If `bash`/`needs_approval` dominates, the sandbox's payoff is the `Irreversible` drop and the egress question is a distraction. If `web`/`needs_approval` dominates, the turn-boundary grant reset (ADR-068) is the lever, not the check itself.

And the standing latch check, which must keep returning nothing until Session D:

```
grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"
```

**residual_risk:** **An attacker who owns a page and gets a team to act on it still reaches all of this.**

1. **Exfiltration through `web` — completely uncontained by the box.** `web` runs in the daemon (`marlowe-exec/src/lib.rs:1717`). The only live control is the per-host approval at `adjudicate.rs:374`, and the composed-URL block that should back it up is inert (`AgentInferred` > `UntrustedContent`). If the human lifts egress for teams, the exfiltration leg has zero controls.

2. **Exfiltration through `bash` — uncontained unless the container is a kernel NETWORK boundary.** ADR-049 §4 is measured, not argued. And the loopback carve-out needed for Ollama and dev servers is the escape: the daemon is on loopback, unauthenticated, and `SocketApprovals` answers on the asking connection (SECURITY-AUDIT #4). A boxed shell that can reach 127.0.0.1 can drive the unsandboxed daemon with full interactive capability and approve its own `bash` prompt. **A sandbox that allows loopback while the daemon has no auth is not a sandbox** — this is the single worst interaction in the plan.

3. **The user reads a poisoned artifact and acts on it.** M3-DESIGN §2.3 makes an artifact 'a path the USER opens'. The box contains the file; it does not contain the human. A research team writes `sandbox/adr-017/finding.md` saying the release checklist requires appending a line to `.git/hooks/pre-commit`; the user does it. §2.2 point 3 is explicit — no layer defends against a document being wrong, and none could. **This is the deliberate hole and the ADR must say it is deliberate**, because a sandbox makes it MORE likely: an agent free to 'go wild' produces more artifacts, and volume is what erodes the human's reading.

4. **The team's report shaping the user's next decision** — the same channel one hop earlier, and the one that scales. §2.2 point 4: a chain of honest judgments about a dishonest premise, each hop a competent model reasoning correctly from a poisoned input. The typed crossing narrows it (fixed-enum category, `artifact_ref`, `lineage`), but A8 arm (b)'s validated headline is still one attacker-influenced sentence, and the human weights a team's conclusion heavily by design.

5. **Grandchildren outlive the box.** `run_bounded`'s own doc comment: no Job Object on Windows, no process group on Unix — `bash("sh -c 'sleep 999 &'")` leaves a process running after the tool returns. If the box is per-team-per-turn, the grandchild outlives it and is then an unsandboxed process the harness has forgotten about.

6. **The harness itself is never sandboxed.** The process parsing attacker bytes is the daemon: three reachable panics in the extractor from one `é`, a panic message that carries ~256 characters of the document into the orchestrator at `AgentObserved` (SECURITY-AUDIT #2, CRITICAL, still open), an xlsx that demands ~200 GB and ABORTS past `catch_unwind`. Sandboxing the agent does not sandbox the parser, and the parser is where the attacker's bytes actually land.

7. **`bash` inherits the full environment** (SECURITY-AUDIT A14 — no `env_clear()`, no allowlist). Nothing to steal today because the provider is local Ollama. The day one API key is env-carried, every boxed shell reads it and — since the box does not constrain `web`, and may not constrain the shell's own network — sends it.

8. **`marlowe-secretary` cannot be reached, because it does not exist.** No email or calendar tool is registered; the builtin set is the eleven at `builtin.rs:37`. The only secretary-shaped channel is `EscalationDesk::secretary_notice` (`escalation.rs:193`), which returns a `Notice` and nothing else. **That is an absence, not a defence** — and absences get filled. Pre-commit the level rule now.

9. **Marlowe stays unlatched — but by inheritance, not by anything here.** M3-DESIGN §2.1's non-negotiable holds today because `ingest_external` has no caller (ADR-062, still verifiable by the grep) and because the child return crosses at `AgentInferred`. Sandboxing changes neither, and this ADR must not be read as having secured it. On the day Session D gives `ingest` its first correct caller, layer 3 goes live together with the compaction stamp and the trim marker, and it goes live in a world where teams have been told they are free.

**cheapest_first_step:** Two read-only commands, about five minutes, and they reorder the entire ADR before a line is written.

```
sed -n '433p;1835p;3174p' crates/marlowe-loop/src/engine.rs
sed -n '2497p' crates/marlowe-daemon/src/daemon.rs
```

They show `Engine` holding one `workspace: PathBuf`, the adjudication reading `workspace: &self.workspace`, `Engine::spawn` handing the child `tools: ports.tools`, and one `FileSystemTools` built per turn from `self.config.workspace`. Together: **a child cannot have its own workspace root at HEAD.** The human's design — 'the research team creates a folder in its sandbox for each ADR' — is not expressible, and the first commit is plumbing (move `workspace` from `Engine` to `Run`, ONE field read by both `adjudicate.rs:343` and `marlowe-exec/src/lib.rs:1559`), not containment.

Then, before any design work, take the number that decides the emphasis:

```
sqlite3 "$PROFILE_ROOT/journal.db" \
  "select json_extract(payload,'$.tool'), json_extract(payload,'$.outcome'), count(*)
   from journal where kind='permission_decided' group by 1,2 order by 3 desc;"
```

If `bash`/`needs_approval` dominates — which it should, since `adjudicate.rs:422` escalates every single shell call before the tier comparison — then the sandbox's whole payoff is the `Irreversible` drop, the egress lift the human asked for buys almost nothing, and refusing it costs him almost nothing. That is the version of this argument he will accept.

### Rejected

- **Refine `bash`'s consequence level per command — parse it, allowlist the safe ones.** — `builtin.rs:16` names it: that is the Cursor CVE exactly, an allowlist that auto-approved the commands the attacker needed. Brief §8.1: 'Filtering does not work. Containment works.' `$(echo c)url`, a Python one-liner, or a script written in an earlier turn beats any parse. The sandbox is what makes a THIRD answer exist — the level drops because reach shrank, not because a string was inspected.
- **Lift the per-host egress approval for sandboxed teams, as the human asked.** — The sandbox contains damage and contains no disclosure. `web` is executed by `FileSystemTools::web` -> `marlowe_net::fetch` in the daemon (`marlowe-exec/src/lib.rs:1717`); the agent never opens a socket, so no container it runs in constrains the fetch at all. The team's box holds a copy of the user's source. And the backstop that would otherwise catch a composed URL is inert — the reader's note crosses at `AgentInferred`, above `blocks_composed_targets`' threshold. Lifting the approval leaves literally nothing on the exfiltration leg. The lift he actually wants — zero prompts during research — is bought by pre-seeding the team's `granted` list.
- **Delete layer 1's quarantined reader inside the box, to recover the serialised model calls.** — It answers a different question. The box bounds what obeying an injected instruction COSTS; quarantine bounds whether the acting model reads the instruction at all. It is also cheaper than it looks: ADR-042 made `web` cost zero model calls and only `read(ref=…)` pays, and the BLAKE3 content cache makes repeats free. The available latency lever is raising `MAX_SOURCES_PER_READER`, which is a measured fidelity trade, not a containment one.
- **Re-implement path confinement inside the container and drop `PathScope`.** — Waste, and it loses something the container does not give. `WorkspaceScope` is stateless (`_gated: ()`, `scope/mod.rs:219`) and takes the root per call (`req.workspace`, `adjudicate.rs:343`), so per-team roots are already its natural shape. A container gives a boundary; it does not give the handle discipline that closes check-then-use (`scope/mod.rs` header, brief §8.3). Also §13-guarded — read only.
- **Give each team its own daemon, using the existing `--workspace` flag.** — ADR-002 is one daemon per profile, and the reason is measured, not stylistic: the journal is a hash chain that cannot tolerate a second writer — a second daemon on one profile produced `UNIQUE constraint failed: journal.seq` on every append (`marlowe-journal/src/profile.rs:51-60`). It would also multiply loaded model weights on a 16 GB card. The change belongs in the loop, moving `workspace` from `Engine` to `Run`.
- **Allow loopback unconditionally so Ollama and dev servers keep working.** — The daemon is on loopback, has no authentication, and `SocketApprovals` answers on the connection that asked (SECURITY-AUDIT #4). A boxed shell with loopback reaches an unsandboxed process running as the user, holding `bash` at `Irreversible`, and approves its own request. That is not a leak in the sandbox; it is the sandbox having no far side.
- **Express 'this team has no network' as a zero in the budget or capability struct.** — Instance #17. `Budget::exhausted` compares `spent >= budget`, so `0 >= 0` fires on iteration one — the quarantined reader paused before its first model call and returned 'the content could not be condensed' for every page. Capabilities are withheld structurally: `ExposedSet::empty()` means there is no tool, an AppContainer token without `internetClient` means there is no socket. Never a counter.
- **Prove the sandbox with a test asserting team A cannot see team B's files.** — Green on today's build with one shared `FileSystemTools` if the assertion is only 'A sees its own files', and green whatever happens if `ls ..` merely errors for an unrelated reason. Instance #15: the reading must differ when the mechanism is broken, which means the control is the same call on the pre-change build, and it must list team B.
- **Credit the sandbox with keeping Marlowe unlatched (M3-DESIGN §2.1).** — He is unlatched today because nothing can taint anything: `ingest_external` has no caller (ADR-062), and the reader-note crossing is at `AgentInferred`. Sandboxing changes neither. Writing 'the sandbox protects Marlowe' invites the next session to drop ADR-062's guard on the strength of it.

---

# ANGLE: Provisioning and lifecycle: what is in a team's box, who decides, when it dies, and how work gets out of it.

**The fact everything hangs on, verified rather than assumed: there is exactly one workspace root in the process, it is `DaemonConfig::workspace`, and it reaches the tools by two independent paths that are set from that one field at two different sites.** `Engine.workspace` (`crates/marlowe-loop/src/engine.rs:433`, set at `crates/marlowe-daemon/src/daemon.rs:2090`) has **exactly one reader** — `engine.rs:1835`, `Request::workspace`, which is what `PathScope::open` resolves the manifest's `./**` against. `FileSystemTools.workspace` (`crates/marlowe-exec/src/lib.rs:314`, set at `daemon.rs:2498` through `build_tool_host`) has **six** — `lib.rs:1100, 1114, 1371, 1392, 1394` (the `glob`/`grep` walks) and `1559` (`bash`'s cwd fallback). And `Engine::spawn` hands the child `tools: ports.tools` verbatim (`engine.rs:~3170`), so **every run in the tree — Marlowe, PI, master, worker — shares one tool host rooted at the user's real directory.**

That is why the human's request is currently impossible, and also why it is cheap: the box is a *value*, both consumers already take it as a parameter, and nobody has to invent a mechanism. Somebody has to decide which run supplies it and add the one reader that decides.

**Second verified fact, and it changes what the word "workspace" is allowed to mean: path scoping does not confine `bash`.** `spawn_shell` on Windows is `cmd.arg(command).current_dir(dir)` (`lib.rs:2531-2533`). The `cwd` handle is held open — which pins the directory against rename, and that is all it does. The shell then does `cd ..`, absolute paths, `curl`. Path scoping is real and strong for `read`/`write`/`edit`/`glob`/`grep` and is a *starting directory* for `bash`. A design that says "the team gets its own workspace" without saying which strength applies to which tool is instance #16 at the architecture level.

**Third: nothing a team owns survives a turn except the filesystem.** `build_tool_host` is called inside `turn` (`daemon.rs:2498`), so the `DocumentStore` (`Arc<Mutex<BTreeMap>>`, `crates/marlowe-extract/src/store.rs:111`) is rebuilt every turn and every `web` ref dies with it — while `read_ref`'s own error text tells the model refs "last for this session" (`lib.rs:1635`), which is a fourth party disagreeing about a lifetime. `Run::root` is rebuilt per user message. `Checkpoint` (`crates/marlowe-loop/src/durable.rs:87`, `deny_unknown_fields`, `CHECKPOINT_VERSION = 1`) carries profile, budget, floor and window — **and no workspace.** So the box is not a convenience layered on durable state; it *is* the team's durable state, and a resume that cannot name it lands in the user's home directory with nothing observing the mismatch.

**Fourth, and it is the finding I would defend hardest: a shared box is a free-text upward channel with no type, no cap and no validator, and it looks like a filesystem.** A workspace `read` returns `TrustClass::AgentObserved` (`lib.rs:1041` and its neighbours; only `read_ref` at `1674` is `UntrustedContent`), and `blocks_composed_targets` is `origin <= UntrustedContent` (`crates/marlowe-permission/src/adjudicate.rs:50-52`) — so a file a worker wrote and a parent read composes targets freely, never touches `req.contract.validate`, never touches `CondensedResult::render`, and never crosses `Engine::spawn`'s note match at `engine.rs:~2911`. ADR-063 switches A8's three arms at that line. **A shared box would run an unmeasured, untyped, unbounded channel alongside the one A8 is measuring** — the vacuity family aimed at the control that exists to detect vacuity, which M3-DESIGN §9.1 already caught once.

So the answer to the question the brief asks — *does a file sidestep the upward-channel problem or relocate it?* — is: **it depends entirely on who opens it, and §2.3's word "user" was already load-bearing.** A file the user opens has no model in the loop, so there is no instruction-following surface; what remains is a display attack, which is §3.6's territory and is bounded because the human is reading rather than choosing between harness-labelled options. That genuinely sidesteps it. A file a *parent agent* reads is prose crossing upward with the type system switched off. The design below keeps those two cases physically apart, using machinery that already exists rather than a new check.

## The box lives on CapabilityProfile as a private field, and never on SpawnRequest

**What:** A `Workspace` value (an enum: `UserRoot` | `Box(PathBuf)`) becomes a private field on `CapabilityProfile`, set only through `CapabilityProfile::new`, which refuses `level != AgentLevel::Secretary && workspace == UserRoot` as a load-time error (`ProfileError::AgentInUserWorkspace`). The model never names it. No field is added to `SpawnRequest`.

**Mechanism:** CLAUDE.md's own argument for why the granted egress set lives on the profile rather than the `Run` transfers exactly: `CapabilityProfile::new` is the place an invariant relating two fields can be enforced, and putting the value beside the policy on the `Run` bypasses the constructor while every quarantine test stays green. Here the invariant is `level ⟹ workspace`, and both operands are already profile fields (`level` is private and constructor-validated, `profile.rs:266-272`). `CapabilityProfile`'s `Deserialize` already routes through `new`, so a **checkpoint** claiming an agent in the user's root is refused at decode rather than restored — which is the resume story solved for free. Keeping it off `SpawnRequest` follows ADR-057 §5's precedent verbatim: `share` and `reads_untrusted` are 'withheld structurally, so a model cannot reach them by naming them'. A workspace root is *which path* — the most Target-shaped value in the system — so a model composing one under a latched floor is precisely what layer 3 exists to refuse. `composes_spawn_targets` would otherwise need a new arm, and `crates/marlowe-loop/src/driver.rs` where `SpawnRequest` lives is **§13-guarded** (PROTECTED as 'the memory and approval ports'). This design touches it not at all, and that is deliberate.

**Helps research:** Marlowe decides the box during PI-MODEL §2's intake interview, where the human is present and the answers are pinned. That is the one place in the system with enough context to say 'this team needs crates/ and docs/ and nothing else' — a spawning model guessing at runtime would either over-provision (context bloat) or under-provision (a team that cannot see its subject).

**Cost:** One new private field, one new `ProfileError` arm, and a **`CHECKPOINT_VERSION` bump to 2** — a new field on a serialized struct is exactly what ADR-053 says the version exists for, because a missing field taking a serde default here means 'the daemon's workspace', which is the permissive value pointing at the user's home directory. `PauseReason`'s note that a new *variant* needs no bump does not cover a new *field*. Latency: zero. Disk: zero.

**Read by:** `CapabilityProfile::new` (the two-field invariant), its `Deserialize` (decode-time refusal), and `Engine`'s `adjudicate` call at `engine.rs:1835`, which reads `run.profile.workspace()` in place of today's `self.workspace`. `Engine.workspace` — the field with exactly one reader — is then deleted rather than left as a second definition.

## Three provisioning modes, and `Graft` is a sparse `git worktree`

**What:** A closed enum decided at intake: `Scratch` (a fresh empty directory under `profile_root/boxes/<run>`), `Graft { paths }` (a `git worktree` of the user's repo, sparse-checked-out to the declared paths, on a branch named for the run), `Mirror { paths }` (a hardlink farm or junction for non-repo directories). `Scratch` is not the default — the default is whatever the intake interview settled, and a team spawned with no answer is refused rather than given an empty box.

**Mechanism:** `git worktree` is already this project's answer to the parallel-sessions hazard (CLAUDE.md's seven-form table; `.claude/worktrees/` exists), so the team box and a human's parallel session share one primitive and one set of documented failure modes. It shares `.git` rather than copying it, which on this repo is the difference between 11.5 MB and 7.2 GB. And it makes 'getting work out' free: a worktree is a branch, so `git log`/`git diff` against `team/<run>` is the delivery mechanism, already installed, already understood, with the user's own tooling.

**Helps research:** This is the §1-ordering argument and it is measurable, not rhetorical. `workspace_map` (`daemon.rs:3416`) injects the box's shape into the context tier with `MAP_MAX_ENTRIES = 200` and `MAP_MAX_DEPTH = 2`. Measured on this repo today: the full root produces **200 entries, truncated = true, 4,771 chars (~1,200 tokens)** and appends the notice 'there are more files than this'. `crates/` alone produces **73 entries, no truncation, 1,539 chars (~384 tokens)**; `crates + docs` is ~104 entries and still does not truncate. So a curated box is the only configuration in which the model is *not* told its own map of its own workspace is incomplete. Curation buys knowledge here; it does not trade against it.

**Cost:** Disk, measured on this checkout: tracked bytes total **133,342,199** (1,634 files), of which `runs/` is the bulk; `crates + docs + tools + eval` is **11,511,000 bytes**. A sparse `Graft` of the source of truth is ~11.5 MB per team. `.git` is 7.2 GB and is **not** copied. Latency: one `git worktree add --no-checkout` plus a sparse-checkout set, sub-second on a warm repo, paid once at spawn, off the daemon thread per CLAUDE.md's heavy-work rule. `Mirror` with hardlinks is ~0 bytes and is the mode to use for read-only reference material.

**Read by:** The provisioner, called once from the spawn path before `CapabilityProfile::new`; `workspace_map` at `daemon.rs:3416`, which walks the box and is where the entry-count number is read; and `WALK_SKIP` (`crates/marlowe-exec/src/lib.rs:195`), which does **not** skip `runs/` — so a `Graft` that includes `runs/` burns the 200-entry budget on run artifacts and must be declared narrowly on purpose.

## Boxes are flat siblings, never nested — and this is a correction to the obvious answer

**What:** `profile_root/boxes/<sayable-run-id>/` for every agent at every level. A worker's box is a sibling of its master's, not a subdirectory. Nested teams get nested *runs* and flat *boxes*.

**Mechanism:** The obvious design is `box(child) = box(parent)/child`, so fan-in is free and the parent just reads its subdirectories. **That design is broken and it breaks the §2 invariant.** Every filesystem tool declares the single glob `WORKSPACE = "./**"` (`crates/marlowe-tools/src/builtin.rs:61`), resolved against the run's own root — so with prefix nesting the parent's declared glob *already admits* every child's box, and the parent reads the child's raw prose at `AgentObserved` with `validate` never called. `PathGlob` is a bare newtype over `String` (`crates/marlowe-tools/src/manifest.rs:185-194`) with no negation concept, so an exclusion glob is not expressible and building one means editing `crates/marlowe-permission/src/scope/glob.rs`, which is in **`PROTECTED_DIRS`**. Flat siblings need no new check at all: `scope::request::validate` already refuses `..`, rooted forms, ADS, device names and munged names *before any syscall* (`scope/mod.rs`, step 1), so a run physically cannot spell a path to a sibling box. **The containment is the machinery that is already there, not a new rule.** Second, independent reason for the same layout: `OrphanPolicy::Detach` sets `parent: None` and the child resumes (`durable.rs:375-378`) — under nesting, a detached child's box would live inside a dead parent's directory. Two unrelated arguments landing on one layout is worth more than either alone.

**Helps research:** It costs the free fan-in, and that cost is paid back by the promotion path below, which is the place a check can actually live. A PI that could silently absorb everything its workers wrote would have no boundary at all between 'my finding' and 'what a worker read on a hostile page' — which is SECURITY-AUDIT finding #1, made worse by the 2026-08-31 reversal that gave masters working tools.

**Cost:** Windows path length. `profile_root/boxes/<id>/` with `crate::run::sayable` short names keeps the box path under ~80 characters, which matters because `scope/walk.rs` opens component-by-component and MAX_PATH lands on the deepest file in the deepest box first. Flat siblings are what keep this bounded — depth-4 nesting plus a `Graft` of `crates/marlowe-permission/src/scope/` would eat the budget. Disk: N boxes instead of one tree, same total bytes.

**Read by:** `scope::request::validate` and `scope::glob::admits` (both already running on every path, no change), and the provisioner that chooses the directory name. Nothing new reads anything.

## The tool host takes the root per batch, and `FileSystemTools.workspace` is deleted

**What:** `ToolHost::execute_batch` gains a root argument supplied by the calling run; `FileSystemTools.workspace` — six readers at `lib.rs:1100, 1114, 1371, 1392, 1394, 1559` — becomes that argument. One value, passed from one place, read by both the scoping site and the execution sites.

**Mechanism:** Today the scoping root and the execution root are two fields set from one config value at two sites (`daemon.rs:2090` and `:2498`). That is the two-sides-silently-disagree shape sitting latent: change one and every test that checks the other stays green. Per-batch makes the box a property of *the run making the call*, which is what it is, and it is the only way a child can differ from its parent given that `Engine::spawn` shares `ports.tools`. The alternative — `Engine::spawn` constructing a child tool host — would make `marlowe-loop` depend on `marlowe-exec`, a dependency the crate graph deliberately does not have.

**Helps research:** It is what makes the whole design real rather than declarative. Without it a boxed profile is a field with one reader (the adjudicator) while `glob`, `grep` and `bash`'s cwd still walk the user's directory — a control that reads correct in the profile and does nothing at the executor, which is instance #16 with the blast radius pointing at the user's home.

**Cost:** Touches the whole wrapper chain — `McpTools`, `SkillTools`, `RecallTools`, `FileSystemTools` — every link of which must forward the new argument. The trap is already documented at `daemon.rs:706-740` and already tested: `tests/composition_root.rs::a_batch_reaches_the_innermost_host_through_both_wrappers` fails if a link forgets. Mechanical, a few hundred lines, no latency.

**Read by:** `FileSystemTools::glob`/`grep` walks (`lib.rs:1100, 1114, 1371, 1392, 1394`) and `FileSystemTools::bash`'s cwd fallback (`lib.rs:1559`). And the deletion is the point: after this, `grep -n "self.workspace" crates/marlowe-exec/src/lib.rs` returns nothing, which is the check that the second definition is gone rather than shadowed.

## Getting work out: two readers, two rules, and only one of them needs a mechanism

**What:** **The user reads any box directly** — the artifact reference the team returns is an absolute path the TUI can open, and no promotion, copy or validation is involved. **A parent agent reads nothing of a child's box**; what crosses is the `OutputContract`-validated result plus an artifact *reference* — path, byte count, content hash, and nothing else. To get the bytes, the parent calls a harness tool `promote(<child-run>, <relative-path>)` which copies the file into the parent's own box, where `read` can then reach it.

**Mechanism:** This is §2.3's sentence taken literally — 'an artifact is a path the **user** opens' — with the emphasis finally load-bearing. The user is not a model: bytes reach a human eye through an editor, there is no instruction-following surface, and the residual risk is a display attack (bidi, homoglyphs) which is §3.6's problem and is bounded because the human is reading rather than choosing between harness-labelled options. A parent *is* a model, so the same bytes are prose crossing upward and need the same treatment as every other upward hop. `promote`'s first argument is *which file* — a Target — so it goes through `adjudicate` exactly like `edit`'s path, and a latched parent cannot compose it. The bulk stays where it was written; only what was explicitly asked for moves.

**Helps research:** It answers the human's actual example — 'the research team creates a folder in their sandbox for each one of their ADRs' — without the file becoming a laundering path. The team writes freely, at any volume, with no cap and no schema, because the intended reader is a person. The PI still gets what it needs, one named file at a time, through a door that has a check on it. Nothing about the team's own throughput is slowed: the cost lands on the parent's *reading*, which is where the exposure is.

**Cost:** One new builtin tool (`promote`) with a `Target` path parameter and a `Reversible` or `Irreversible` consequence level — and note ADR-058's precedent that a distinct action gets its own tool rather than a flag on an existing one. The **honest open question, flagged rather than resolved**: whether promoted bytes arrive at `AgentObserved` (today's `read`) or must be quarantined. That is ADR-062 §4's question — what channel a belief derived from another agent's output is recorded under — with `Channel::Agent` already existing and having **zero production construction sites**. It is a pinned-contract question and it is the human's. Disk: a copy per promoted file, kilobytes.

**Read by:** `adjudicate`'s Target check on `promote`'s path parameter; `PathScope::open` twice, once in each box, which is the only way the copy can be made without a re-resolved string; and the TUI's artifact-reference renderer, which needs the path for the user's own open.

## Lifecycle: `OrphanPolicy` already decides the box's fate, and `Terminate` seals rather than deletes

**What:** The three existing variants each get a box consequence. `Terminate` → run `Cancelled`, box **sealed** (made read-only, retained). `Detach` → `parent: None`, box **survives, still writable**, now the root of its own tree. `Adopt { by }` → box does not move; only the run graph does. The box outlives the turn by construction — it is a directory — and dies only when a human deletes it.

**Mechanism:** `settle_orphan` (`durable.rs:361-385`) already writes a new checkpoint per variant and already returns a distinguishable `OrphanOutcome`; the box treatment hangs off the same match with no new enum and no new `EventKind`. Sealing rather than deleting is forced by M3-DESIGN §3.5: TERMINATE must state what it cannot undo, 'derived from the journal rather than from the agent'. A box that vanished with the run would make the honest confirmation dialog impossible to write — it would have to say 'and forty files you have not read'. So termination stops the run and freezes the deliverable; **destruction is a separate, user-initiated act**, surfaced in the Runs tab beside the run it belonged to.

**Helps research:** It is the only durable thing a team has. Every other artefact of a turn is destroyed at turn end — `DocumentStore` is rebuilt inside `turn` (`daemon.rs:2498`) so `web` refs die, and `Run::root` is rebuilt per user message. A research team that fetched thirty sources across four turns has, today, exactly one place to put what it learned that will still be there next turn, and this is it.

**Cost:** Retention is a policy that needs a number and the number must be a command: `marlowe --boxes --stale` lists boxes with no live run, no unread artifact, older than N days, and prints the count and the total bytes. **It lists; it never deletes.** A timer that deletes is a timer that eventually eats a deliverable. Disk grows monotonically until a human acts, and that is the correct failure mode for a directory whose contents are the product.

**Read by:** `settle_orphan` (`durable.rs:361`) and `settle_children` (`engine.rs:2667`) for the fate; `Checkpoint.profile.workspace()` for a resume, which is what makes a resumed run land in its own box rather than the daemon's; and the Runs tab, which is where a human sees the box and can destroy it.

## The environment is part of the box, and today it is not confined at all

**What:** `spawn_shell` gets an explicit allowlisted environment for boxed runs, on the pattern `eval/`'s §4.0.9 `minimal_env()` already uses for the harness's own spawns.

**Mechanism:** Verified: `grep -n "env_clear\|\.env(\|env_remove" crates/marlowe-exec/src/lib.rs` returns **nothing**. The shell child inherits the daemon's entire environment — `PATH`, `MARLOWE_CUDA_LIB_DIR`, and any provider credential the daemon was started with, `OPENROUTER_API_KEY` being the obvious one given `marlowe-openrouter` exists. A box that confines the filesystem and hands over the daemon's environment has relocated the blast radius, not shrunk it: exfiltration needs a secret and a socket, and `bash` already has the socket (ADR-049 §4, measured — `curl` returns HTTP 200).

**Helps research:** It costs the team nothing. A research team needs `PATH` and a temp directory; it does not need the secretary's model credentials. And the project already has the pattern and the reason written down — `minimal_env()` is a fixed allowlist, which is why `tools/score_longmemeval.py` has to translate `MARLOWE_CUDA_LIB_DIR` onto `PATH` by hand rather than leaking the whole environment.

**Cost:** A few lines in `spawn_shell` plus a decision about what is on the list. The real cost is that a team doing legitimate tool work may need something the list omits, and the failure will be a confusing tool error rather than a refusal — so the list must be declared per box at provisioning time and named in the refusal, `ScopeError::Unopenable`'s remedy-naming style.

**Read by:** `spawn_shell` (`crates/marlowe-exec/src/lib.rs:2523` windows, `:2538` unix) — the one function that builds the `Command`, so there is one site and it cannot drift.

## The AppContainer is a second act on the same directory, and it does not ship first

**What:** Defer the kernel token. Ship the box with filesystem containment from the existing scope machinery plus provisioning; record the AppContainer as a separately-argued follow-on with its precondition written down.

**Mechanism:** ADR-002's revision rejected general sandboxing for two reasons, and **neither survives contact with a team box** — which is why this is an *extension along an axis the ADR already carved*, not an overturning. (1) 'A secretary that cannot reach your files is useless': the team is not the secretary, never wanted the user's files, and its contents were chosen by Marlowe at intake rather than requested by the agent. (2) 'A default that must be overridden daily is not a default': erosion needs an inconvenienced human, and there is no human inside the box. ADR-002 already retains a sandbox backend for exactly one profile — the quarantined reader, 'a small, isolated component with no interactive path'. **A team box is a second profile with the same three properties**, so the carve-out sentence is the precedent rather than the obstacle. The reason to defer anyway: an AppContainer's only *new* protection over the box is network, and the network story does not close. A token without `internetClient` cannot reach **loopback either** — Windows blocks AppContainer loopback and lifting it is a per-package `CheckNetIsolation LoopbackExempt` registry change. So the naive answer breaks Ollama and breaks 'run a dev server and curl it', and the exemption that fixes it is precisely where an attacker aims once anything on loopback can proxy outward. That is ADR-049 §4 re-opened by another route, not closed.

**Helps research:** Deferring is the §1-ordering answer. The filesystem win is available now from machinery that exists and costs nothing at runtime; the network win requires an argument nobody has finished and a mechanism that plausibly breaks a legitimate workflow. Shipping the cheap half immediately is strictly better than blocking the box on the hard half.

**Cost:** If it is ever built, provisioning and the token are **one act**: an AppContainer process cannot read its own box unless the box's ACL grants the package capability SID (`icacls <box> /grant *<sid>:(OI)(CI)F` at creation). That is why it belongs in this angle at all — it is a property of how the directory is made, not a flag flipped later. Cost of deferring, stated plainly: `bash` in a box still reaches the network, so a boxed team can still exfiltrate anything in its box.

**Read by:** Nothing, today — and that is the point. **Do not add a `sandboxed: bool` to `CapabilityProfile` in anticipation.** A declared control with no reader is instance #16, and `web`'s `inline_threshold_bytes: 0` is the version of that mistake that already shipped here with a green test asserting the declaration.

**measurement:** **The number with teeth, and its control.** Two runs, one boxed and one not, reading the same path outside the box:

```
cargo test -p marlowe-loop --test box_containment -- --nocapture
# a_boxed_run_cannot_read_outside_its_box ......... Undeclared   (the property)
# marlowes_own_run_can_read_the_same_path ......... Ok           (THE CONTROL)
```

The control is not optional and it is the specific thing this project has been burned by. Without it the suite reads identically when the file simply does not exist — which is the exact confusion `ScopeError::Unopenable`'s message was rewritten for on 2026-08-25, after an agent read 'cannot find the file' as a permission denial and wrote a handoff document about MSVC path resolution. If both rows refuse, the test is measuring absence, not containment.

**The number that proves the upward channel was not relocated, with a mutation that must redden it:**

```
cargo test -p marlowe-loop --test box_containment -- a_parent_cannot_read_a_childs_box
# MUTATION: change the provisioner to box(child) = box(parent)/<child>, re-run.
# It MUST go green. If it stays red under nesting, the test is asserting something else.
```

This is the one I would refuse to ship without, because the flat-sibling layout is the whole enforcement and a test that passes under both layouts is not testing the layout.

**The knowledge number — §1's ordering made executable, and it already runs today:**

```
python -c "<breadth-first walk, MAP_MAX_ENTRIES=200, MAP_MAX_DEPTH=2, WALK_SKIP>"
# user root : 200 entries, truncated=True,  4771 chars (~1192 tokens)   <- measured, today
# crates/   :  73 entries, truncated=False, 1539 chars (~ 384 tokens)   <- measured, today
```

Target: **a provisioned box never truncates** — entry count < 200 and the 'there are more files than this' notice absent. **State its polarity honestly: this one goes quiet rather than red.** If provisioning silently fell back to `config.workspace`, this cell would read 200/truncated — a quality signal a reader might shrug at — while the containment test above would *fail outright*. Test one is the evidence; test three is the improvement.

**Disk, measured on this checkout rather than estimated:**

```
git ls-files -z | xargs -0 du -cb | tail -1              # 133,342,199  full tracked
git ls-files -z -- crates docs tools eval | xargs -0 du -cb | tail -1   # 11,511,000  a Graft
du -sh .git                                              # 7.2G — NOT copied by a worktree
```

**And the composition-root check, because the per-batch root is the change most likely to be half-wired:**

```
cargo test -p marlowe-daemon --test composition_root
# a_batch_reaches_the_innermost_host_through_both_wrappers
```

That test already exists and already fails when a wrapper link forgets to forward. Extending it to assert the *root* arrived at `FileSystemTools`, not merely that a batch did, is the difference between 'the call reached the executor' and 'the executor used the box'.

**residual_risk:** **A boxed team still reaches the network.** `bash` is executed by the harness (`lib.rs:2000`), `spawn_shell` runs a real shell, and no `EgressPolicy` is consulted on that path — ADR-049 §4, measured with `curl` returning 200. The box confines the *filesystem*. Everything in the box can leave it over a socket, and the box is where the team's research lives. If the team was fed a poisoned source, the exfiltration channel is open and this design does not close it. ROADMAP #3 is deferred by the human pending triage and no milestone owns it.

**The box does not make anything safe to read.** ADR-041 already concedes the fidelity risk — one quarantined reader holds up to six documents and 'A can influence how B is described'. A team that read a hostile page writes an honest file about a dishonest premise, and the file is *correct* in every checkable way. §2.2's chain of honest judgments about a poisoned input runs through a filesystem exactly as it ran through a summary. No layer defends against a document being wrong, and none could.

**`promote` is a hole with a door on it, and the door is only as good as an unanswered question.** Whether promoted bytes arrive at `AgentObserved` (today's `read`) or must be quarantined is ADR-062 §4's origin question — the same one blocking Session D's correct `ingest` caller, with `Channel::Agent` existing and having zero production construction sites. Ship `promote` at `AgentObserved` and a parent absorbs child prose above `blocks_composed_targets`' threshold, which is SECURITY-AUDIT finding #1 with a new front door — made worse, not better, by the 2026-08-31 reversal that gave masters working tools.

**A `Graft` is a live handle on the user's real repository.** A worktree shares `.git`. A team with `bash` in a grafted box can `git checkout`, `git reset`, rewrite refs, or push. The sparse checkout bounds what it *sees*; it does not bound what `git` can *do* to the object store both checkouts share. Either the box is `Mirror`/`Scratch` for anything with `bash`, or `Graft` needs its own answer, and I do not have one that is not a filter.

**The environment gap is live today and this design only names it.** Until `spawn_shell` clears the environment, every credential the daemon was started with is one `echo $VAR` away inside every box.

**And the honest structural one: three of these ideas are only as strong as the layout.** Flat siblings do all the work of keeping a parent out of a child's box, and the layout is a *provisioner's choice*, not a load-time invariant — nothing in `CapabilityProfile::new` can tell a sibling path from a nested one without a string check, and a string check on a harness-constructed path is fine but a string check is what it is. Someone who 'tidies up' the provisioner into nesting for convenience turns the whole upward channel back on, and every containment test except the one mutation test above stays green.

**cheapest_first_step:** **Run the discriminating grep that prices the whole design, before writing a line.** Five minutes, read-only, and it settles the one thing the cost estimate rests on — that the box has exactly two consumers and no third I missed:

```
grep -n "self\.workspace" crates/marlowe-loop/src/engine.rs        # expect: 1  (line 1835)
grep -n "self\.workspace" crates/marlowe-exec/src/lib.rs           # expect: 6  (1100,1114,1371,1392,1394,1559)
grep -rn "config\.workspace" crates/marlowe-daemon/src/            # expect: the two setters + status/display rows
grep -rn "tools: ports\.tools" crates/marlowe-loop/src/engine.rs   # expect: the child shares the parent's host
```

Those are the numbers I measured; a session that gets different ones has a different codebase and should stop and re-derive rather than build against this page. **State the expected output rather than the command alone** — instance #18 is a prescribed check that went loud and affirmative after the call graph moved under it, and it was committed against CLAUDE.md itself.

Then, still before any provisioning code, write the **failing** test that the whole design is judged by, and watch it fail for the right reason:

```
crates/marlowe-loop/tests/box_containment.rs
  a_boxed_run_cannot_read_outside_its_box       -> today: PASSES WRONGLY (there are no boxes,
                                                    so construct it with a hand-built profile and
                                                    watch it read the user's root successfully)
  marlowes_own_run_can_read_the_same_path       -> the control
  a_parent_cannot_read_a_childs_box             -> the mutation target
```

The first assertion failing on today's build *is the finding*: it demonstrates, in a command that prints a result, that every agent in the tree is currently rooted in the user's directory. That is worth more to the human deciding this than any amount of the argument above, and it costs an afternoon.

### Rejected

- **A `workspace` field on `SpawnRequest`, filled by the spawning model through `run`** — It is *which path* — the most Target-shaped value in the system. `composes_spawn_targets` would need a new arm, and `crates/marlowe-loop/src/driver.rs` is §13-guarded (PROTECTED as 'the memory and approval ports'). ADR-057 §5's precedent is the right shape and this design follows it exactly: `share` and `reads_untrusted` are withheld structurally 'so a model cannot reach them by naming them'. Marlowe decides the box at intake, where the human is.
- **Nesting a child's box under its parent's, so fan-in is free** — My own first answer, and it is wrong. Every filesystem tool declares the single glob `./**` (`builtin.rs:61`) resolved against the run's own root, so prefix nesting means the parent's declaration already admits the child's box — the parent reads the child's raw prose at `AgentObserved`, `validate` never runs, and `Engine::spawn`'s note match at `engine.rs:~2911` is bypassed entirely. `PathGlob` is a bare `String` newtype (`manifest.rs:185`) with no negation, so an exclusion glob is not expressible without editing `scope/glob.rs`, which is in `PROTECTED_DIRS`. Flat siblings need no new check: `scope::request::validate` already refuses `..` before any syscall.
- **Copying the repository into each box** — 133 MB per team, measured — and worse, it **diverges**. The team researches a snapshot while the user edits the original and neither knows. A worktree is one object with two checkouts and `git status` says which is which; a copy is two objects and a guess.
- **Destroying the box when the run terminates** — The deliverable is in there. M3-DESIGN §3.5 requires TERMINATE to state what it cannot undo, derived from the journal — a box that vanished with the run makes the honest dialog unwritable ('and forty files you have not read'). Seal, retain, and let a human delete.
- **Parsing or scanning what a team writes to decide whether it may cross upward** — A filter, and brief §8.1 rules it out by name: 'Filtering does not work. Containment works.' It loses to an adversary choosing the spelling. Containment here is the promotion door plus the flat layout — the parent cannot name the sibling path at all, which is not a judgement about content.
- **A per-box `EgressPolicy` as the answer to `bash` reaching the network** — `adjudicate`'s egress section iterates parameters typed `Url`; `bash` declares none, so **no `EgressPolicy` is consulted on that path at all** (ADR-049 §4, measured — `curl` returns HTTP 200). A policy field the shell path never reads is instance #16 wearing a security label, and it would be *worse* than the current honest gap because it would read as coverage. Either the shell loses network capability at the process boundary or `bash` is recorded as outside layer 4 by decision. Both are the human's.
- **Shipping the AppContainer token with the first cut of the box** — Its only new protection over the box is network, and the network story does not close: a token without `internetClient` cannot reach loopback either, so it breaks Ollama and breaks the legitimate dev-server-plus-curl workflow, and the `CheckNetIsolation LoopbackExempt` fix is exactly where an attacker aims once anything on loopback proxies outward. Blocking the box on an unfinished argument violates §1's ordering when the filesystem half is available today for free.
- **A `sandboxed: bool` on `CapabilityProfile` now, wired later** — Instance #16, and this codebase already shipped that exact mistake: `web`'s `inline_threshold_bytes: 0` carries the comment 'Never inlined. §8.2: raw untrusted bytes do not reach attention', **no code reads it**, and `web_is_inert_and_never_inlines` asserts the field's value rather than a byte's fate. Every field in this design names the function that reads it or it does not go in.
- **Making the box a value on `Run` rather than on `CapabilityProfile`** — Same reason CLAUDE.md gives for the egress granted-set: `CapabilityProfile::new` is where an invariant relating two fields is enforceable, and both operands (`level`, `workspace`) are already profile fields. On the `Run` the `level ⟹ workspace` check is bypassed rather than enforced — the profile would still read `Secretary`-shaped while the run touched a box, or worse the reverse — and the profile's `Deserialize`-routes-through-`new` property, which is what refuses a bad **checkpoint** at decode, would not apply.

---

# CRITIQUE (usable-with-fixes)

**Fatal:** Not fatal, but one item comes close and it is the axis the design was warned about. **The container the whole argument rests on cannot be built at the seam it names, and no sandbox mechanism exists anywhere in this workspace.** `grep -rni sandbox --include=*.rs crates/*/src/` returns six hits and every one is a doc comment — `profile.rs:388` ("The one profile ADR-002 keeps a kernel sandbox for"), `onboarding.rs:9`, `builtin.rs:14`. There is no backend, no trait, no dependency. `spawn_shell` (`crates/marlowe-exec/src/lib.rs:2523/2538`) ends in `run_bounded(cmd: std::process::Command, limits)`, and an AppContainer must be applied at `CreateProcessW` via `STARTUPINFOEX` + `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` — it cannot be applied to an already-created process the way a Job Object can. `std::os::windows::process::CommandExt` exposes `creation_flags` and `raw_arg` on stable; `raw_attribute` is nightly-only (verify against the pinned toolchain — one command), and `std::process::Child` cannot be constructed from a raw handle, so the pipe-capping, deadline and kill machinery that A1 and A2 were fixed into has to be rewritten against raw handles. The design prices idea #1 as "Latency: zero. Disk: zero." That is the cost of the *manifest*; the cost of the *container* is a new `cfg(windows)` `windows-sys` dependency in a crate whose own doc comment at `run_bounded` says it deliberately does not have one, plus a reimplementation of the function two shipped security fixes live in. Everything else in the document is repairable; this is the item that decides whether the ADR is a design or a wish.

- **Sandboxed `bash` is a SECOND MANIFEST, not a lowered level** — The selection mechanism does not exist and would need a new field on a §13-guarded type. "Selected by the harness from the run's container" requires `CapabilityProfile` to carry a container handle; it has exactly seven fields (`exposed_tools`, `egress`, `interrupt`, `model_route`, `level`, `may_write_memory`, `reads_untrusted`, `profile.rs:379-387`) and none is a path or a handle. The design claims "no new field, one existing reader" while requiring one.
  - fix: Drop the container handle entirely — the enforcement already exists. `engine.rs:2842-2853` is `// A narrowing, never a widening.`: a child's requested tools must be a subset of the parent's exposed set. So register the boxed shell as a **second ToolId** and make the level rule a load-time error in `CapabilityProfile::new`'s existing wildcard-free `match level` (`profile.rs:314-375`): `ToolId("bash")` at any level below `Secretary` is a `ProfileError`, and the boxed id at `Secretary` is a `ProfileError` too. The reader is the match that is already there — the one the comment calls "the #19-safe shape, where the check's coverage is not a list somebody maintains." A team top-agent that never holds `bash` cannot pass it down, because narrowing is enforced two hundred lines above the profile construction.
- **Sandboxed `bash` is a SECOND MANIFEST, not a lowered level** — The model-facing text is wrong for the second manifest and the design never mentions it. `SHELL_DESCRIPTION` (`builtin.rs:154`) is what the model reads, and it asserts two things that become false in a box: *"EVERY call to this one STOPS AND ASKS THEM for approval, so a wrong guess costs them a prompt"* and *"It reaches the network normally."* The design calls the second manifest "a different manifest read at the same line" — but `registration()` carries a description, a token budget (`2_048`), declared paths (`&[WORKSPACE]`) and declared hosts (`&[]`), and it names none of them. `builtin.rs:421-425` records a live failure caused by exactly this: two readings of one word in one request body, which is *stronger evidence than any appeal to a model's priors*.
  - fix: Write a second `SHELL_DESCRIPTION` for the boxed shell that states the truth: no prompt, workspace-only reach, and whatever the network answer turns out to be. And keep the two descriptions in one `const` pair with a test that neither contains the other's promise — the same discipline that fixed the `grep`/`find` collision.
- **LOOPBACK IS THE HOLE, and the daemon's own port is the worst instance** — The premise is false at HEAD, and it is stated as a live standing finding. SECURITY-AUDIT #4 ("The daemon has no authentication") is in the **Fixed** table at `SECURITY-AUDIT.md:26`: *"a per-profile token, offered as a connection preamble, checked before dispatch"*, `marlowe-daemon` `socket_auth::*` (5 cases), and the audit notes the fix was verified by **removing the check** and watching an unauthenticated `{"op":"shutdown"}` get dispatched. `crates/marlowe-daemon/src/auth.rs` exists; enforcement is at `daemon.rs:3250` and `control_plane.rs:660`. So "the escape is one `curl` to a fixed port, and it lands with FULL interactive capability" is not true — it lands on `unauthenticated:`.
  - fix: Restate it as the requirement it actually is, which is sharper. `auth.rs`'s own header says the token defends *other users*, not *a process running as you* — "that threat is out of scope and no token changes it." A sandbox changes that: a boxed process is no longer running as you in the relevant sense, and the token becomes load-bearing in a way its author disclaimed. The buildable consequence: **the box must not have read access to the profile root**, because `daemon.token` is a file, and an AppContainer's filesystem access is decided by whether an ACE for the package SID exists. That is a checkable ACL fact (`icacls %LOCALAPPDATA%\marlowe` must show no `S-1-15-2-*` and no package SID), not an argument. Do keep the self-approval half — `SocketApprovals` answering on the asking connection is explicitly *not* closed (audit B2).
- **LOOPBACK IS THE HOLE, and the daemon's own port is the worst instance** — The loopback polarity is backwards for the mechanism the design chose, and this inverts the trade. For an AppContainer, loopback is **blocked by default and is not a capability** — `internetClient` (S-1-15-3-1), `internetClientServer` (S-1-15-3-2) and `privateNetworkClientServer` (S-1-15-3-3) govern remote addresses; 127.0.0.1 is separately blocked, and the only exemption is `CheckNetIsolation.exe LoopbackExempt -a -p=<SID>`, which requires administrator and is **per-package, all-or-nothing — there is no per-port form**. So "either the container denies loopback (and the team loses dev servers) or the daemon gets authentication first" presents a choice that does not exist, and misses the free win.
  - fix: State it the other way round: under AppContainer you get loopback denial without asking, and you cannot buy back one port even if you want to. That is precisely what makes granting `internetClient` safe — the box reaches arxiv.org and cannot reach the daemon, `ollama` on 11434, or any other local service. Name the cost honestly on the same line: a dev server started inside the box is unreachable from the user's browser, and Ollama must be reached through the harness (which is already true — the agent never opens the model socket).
- **(document-wide) residual risk 6 — "the harness itself is never sandboxed"** — It cites fixed findings as open. "Three reachable panics in the extractor from one `é`, a panic message that carries ~256 characters of the document into the orchestrator at `AgentObserved` (SECURITY-AUDIT #2, CRITICAL, still open)" — G1 and G2–G4 are rows one and two of the **Fixed** table, each naming the test that fails on revert (`multibyte::no_error_detail_ever_quotes_the_document`, `multibyte::*` 5 cases). A residual-risk list that inflates itself is the same failure as a green-and-vacuous test pointed the other way: it stops being evidence about what is actually exposed.
  - fix: Keep the point, shrink it to what survives: the xlsx that demands ~200 GB and **aborts past `catch_unwind`** (audit finding 7) is not in the Fixed table and is the honest instance — an availability hole in the process that parses attacker bytes, which no agent sandbox touches because the parser runs daemon-side beside `web`.
- **Path scoping stays, and gains a per-run root — ONE definition, read by both sides** — The finding is right and understated on the easy half, and the hard half is misdescribed. Easy half: at `engine.rs:1833-1837` the request is built with `workspace: &self.workspace` on a line where `run` is already in scope two arguments away (`exposed: run.profile.exposed_tools()`, `egress: run.profile.egress()`) — a one-token change once `Run` carries a root. Hard half: the design says `FileSystemTools::workspace` is "`bash`'s default cwd, and glob/grep relativisation". It is six readers (`self.workspace` at `marlowe-exec/src/lib.rs:1100, 1114, 1371, 1392, 1394, 1559`), and **1394 is a second `scope.open` — an enforcement site, not a relativisation**: `self.scope.open(declared, &self.workspace, &relative, Access::Read)`. Give a run its own root and change only the adjudicator, and `grep` enforces confinement against a different root than step 3 did, with no failing test — the design's own named hazard, one notch worse than it stated.
  - fix: Say which field dies. `FileSystemTools` must hold no workspace at all: add `workspace: PathBuf` to `marlowe_permission::Adjudication` (which today is only `decision` + `handles`, `adjudicate.rs:176-180`), set from `req.workspace` by the adjudicator, and delete the executor's field so all six sites read the one value that was actually enforced against. `Adjudication` already reaches every executor via `BatchItem` (`driver.rs:563-567`). Both files are §13-guarded (`adjudicate.rs` and `driver.rs`), so price it as a §13 change arriving with a `DECISIONS.md` entry rather than as "real engineering in `engine.rs` and `daemon.rs`."
- **(document-wide) cost realism** — Nothing in the document prices the thing the human said must never be paid. A team with no network capability cannot `pip install`, `cargo fetch`, `npm i` or `git clone` — and the human's ordering is *"It absolutely may not get to a point where speed/accuracy/knowledge is hurt."* The design discusses egress for `web` at length and never asks whether the boxed shell can build anything. It also gives no number for disk per team, none for AppContainer profile creation or workspace ACL cost, and none for added spawn latency.
  - fix: Answer it: grant the box `internetClient` and say plainly that the box therefore does **not** contain egress from the shell, only from the filesystem and the object namespace. A per-package network allowlist would need WFP filters keyed on `FWPM_CONDITION_ALE_PACKAGE_ID`, and adding WFP filters requires administrator — correct mechanism, wrong privilege level for a user-installed product, and that belongs in `rejected` with the reason. Then the containment claim is exactly "blast radius is a disposable directory, not the user's machine", which is what the human asked for, rather than a network boundary that is not there.
- **(document-wide) platform verification** — The single highest-risk unknown is not flagged as unknown. `spawn_shell` on Windows runs **Git Bash (MSYS2)** and its doc comment states there is **no fallback to `cmd`** — *"if Git Bash is absent the call fails and says what to install."* MSYS2's fork emulation uses named objects and shared sections; an AppContainer gets its own object namespace (`\Sessions\N\AppContainerNamedObjects\<SID>`) and no filesystem access without an ACE. Whether MSYS2 runs at all under an AppContainer is unproven here and I could not verify it read-only. The design asserts "AppContainer token / Job Object on Windows" with no hedge. Note also that `builtin.rs:165` still says `spawn_shell` runs `cmd /C`, which the current `spawn_shell` contradicts — stale comment, worth a line.
  - fix: Make it the first spike and gate the ADR on it: create a profile with `CreateAppContainerProfile`, ACL a scratch dir for the package SID, launch `C:\Program Files\Git\bin\bash.exe -c 'echo ok; ls'` in it, and report. If MSYS2 will not run boxed, the entire mechanism has no shell and the fallback (a boxed `cmd`, or WSL2, or nothing) is a different ADR.
- **Measurement — workspace separation via `bash("ls ..")`** — It is not a standing check. Its stated control is "the SAME call on today's build, which must list it" — that control stops being runnable the moment the change ships, so it is a one-time observation, not a regression test. And `ls ..` is ambiguous on the layout the project already uses: `.claude/worktrees/` means a team's parent directory legitimately contains sibling worktrees, so listing it proves nothing either way.
  - fix: Probe identity, not listing. Inside the box, `whoami /groups` must show the AppContainer package SID and a mandatory label of Low; outside it must not. That reading differs whenever the box is not enforcing, it stays runnable forever, and it does not depend on directory layout. Pair it with a negative: `bash("cat \"$LOCALAPPDATA/marlowe/daemon.token\"")` must fail with access denied — that is the escape from the auth correction above, tested at the one file that matters.
- **Record the latch as INERT, not as lifted / ADR-002 framing** — The design treats ADR-002 as a decision this work has to revisit and argue against. It does not: ADR-002's revised execution model already carries the carve-out verbatim — *"**Sandboxing is retained, scoped to one profile.** ... It is a small, isolated component with no interactive path, so a container backend covers it on Windows without the override-erosion problem that killed the general case."* The reason sandbox-by-default was rejected is named and it is **override erosion on the interactive path**, which is a property teams do not have.
  - fix: Frame this as ADR-002's own discriminator applied to a second component, not as a reversal. A team has no interactive path — a child that needs an approval simply stops (`engine.rs:3238`, *"a child run has nobody to ask"*), so there is no override for a daily convenience to erode. That is the argument the human will accept, it costs no fight, and it makes the ADR additive to ADR-002 rather than a challenge to it.

## Strengthened

## What a team sandbox actually buys, what it cannot buy, and the three things that have to be built first

### The one fact that decides everything

**`web` is executed by the harness, in the daemon process.** `marlowe-exec/src/lib.rs:2000` dispatches `"web" => self.web(...)`; `web` at `:1701` calls `marlowe_net::fetch` at `:1717`. The agent never opens that socket. A box around a team is a filesystem and an object namespace; `web` is a socket in an unsandboxed process on the other side of it.

So: **the box contains damage. It does not contain disclosure.** Every ruling below follows from that one sentence, and the human's requested lift of the per-host egress approval is the one item to refuse.

### This is ADR-002's own carve-out, not a reversal of it

ADR-002's revised execution model rejected sandbox-by-default for a named reason — *override erosion on the interactive path* — and then kept sandboxing anyway: *"**Sandboxing is retained, scoped to one profile.** … a small, isolated component with no interactive path, so a container backend covers it on Windows without the override-erosion problem that killed the general case."*

A team has no interactive path. A child that needs an approval does not prompt; it stops — `engine.rs:3238`, *"[child stopped] it needed an approval, and a child run has nobody to ask."* There is no override for a daily convenience to erode, because there is no override. This ADR extends ADR-002's existing discriminator to a second component. It does not argue with it.

### The five mechanisms, ruled

**1 · `bash`'s `Irreversible` — this is the whole win, and it is why teams do not work today.** `adjudicate.rs:422` escalates every `Irreversible` call before the tier comparison, so every shell call in a worker hits `PauseReason::AwaitingApproval` and the run dies. Not fixed by parsing the command (`builtin.rs:16` is right; that is the Cursor CVE) and not by editing `bash`'s level. Fixed by a **second ToolId** whose reach is genuinely smaller — a fact about the container, not an opinion about a string.

**2 · Egress approval — keep it, and pre-seed instead.** `EgressPolicy::permits` (`egress.rs`) is consulted at `adjudicate.rs:369`; a team created with `AllowApproved { granted: [arxiv.org, crossref.org, docs.rs, …] }` fetches silently and an attacker-chosen host still asks. `engine.rs:2888` passes `run.profile.egress().clone()` to every child, so one seed covers the tree. The honest accounting: the grant is already once-per-host-per-**turn** via `grant_egress_host`, so thirty arXiv sources cost one prompt today. What costs prompts is the turn boundary rebuilding `Run::root` — widen *that*, not the check.

**3 · The `(action, target)` latch — record it as inert; do not credit the box for it.** `blocks_composed_targets(origin) = origin <= UntrustedContent` (`adjudicate.rs:50-52`); the reader's note enters the parent at `TrustClass::AgentInferred` (`engine.rs:2246`). SECURITY-AUDIT finding #1, open. Writing "teams are boxed, so composed targets are fine" makes repairing #1 a regression instead of a fix.

**4 · Layer 1 stays.** The box bounds what obeying an injected instruction *costs*; quarantine bounds whether the acting model reads it. Already cheap: ADR-042 made `web` zero model calls, only `read(ref=…)` pays, one call per `MAX_SOURCES_PER_READER = 6` (`engine.rs:67, 2231`), BLAKE3 cache on repeats.

**5 · Path scoping stays and needs nothing.** `WorkspaceScope`'s only field is `_gated: ()` (`scope/mod.rs:219-224`); the root arrives per call as `req.workspace` (`adjudicate.rs:343`). Per-team roots are already its natural shape.

---

### The three things to build, in order

#### Step 0 (blocking spike, read-only until it passes) — will MSYS2 run in an AppContainer?

`spawn_shell` on Windows runs **Git Bash**, and its doc comment states there is no fallback to `cmd`. AppContainer gives a process its own object namespace and no filesystem access without an ACE for the package SID; MSYS2's fork emulation depends on named objects and on reading its own install tree. **I could not verify this and neither could the design under review. Everything below is conditional on it.**

```
# create profile (no admin), ACL a scratch dir, launch
CreateAppContainerProfile("marlowe.team.spike", ...)   -> package SID
icacls <scratch> /grant *<packageSID>:(OI)(CI)F
CreateProcessW STARTUPINFOEX + PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES
  "C:\Program Files\Git\bin\bash.exe" -c "echo ok; ls; whoami /groups"
```

If `bash` does not start, the mechanism has no shell and the fallback is a different ADR.

#### Step 1 — plumbing: ONE workspace root, read by everything that enforces

Today there are two roots and they agree only by accident.

- Adjudication: `workspace: &self.workspace` at `engine.rs:1835`, on a line where `run` is already in scope two arguments away (`exposed: run.profile.exposed_tools()`).
- Execution: `FileSystemTools::workspace`, **six** readers at `marlowe-exec/src/lib.rs:1100, 1114, 1371, 1392, 1394, 1559` — and `1394` is a second `scope.open`, an *enforcement* site, not a relativisation.

Change only the first and `grep` confines against a different root than step 3 did, with no failing test.

**Fix, stated so one field dies:** add `workspace: PathBuf` to `marlowe_permission::Adjudication` (today just `decision` + `handles`, `adjudicate.rs:176-180`), set by the adjudicator from `req.workspace`; **delete `FileSystemTools::workspace`**. `Adjudication` already reaches every executor through `BatchItem` (`driver.rs:563-567`). Both files are §13-guarded, so this arrives with a `DECISIONS.md` entry and a prompt — appropriate for a change that moves where confinement is defined.

Then `Run` carries the root, `Engine::spawn` gives the child its own, and *"a folder in the sandbox for each ADR"* becomes expressible. It is **not** expressible at HEAD: `M3-DESIGN.md` contains the word "workspace" zero times.

#### Step 2 — the boxed shell as a second ToolId, refused structurally at the wrong level

No container handle on `CapabilityProfile` — the type has seven fields and none is a handle, and it is §13-guarded. The enforcement already exists:

- `engine.rs:2842-2853`, `// A narrowing, never a widening.` — a child's tools must be a subset of the parent's.
- `CapabilityProfile::new`'s `match level` (`profile.rs:314-375`), total and wildcard-free by design.

So: register `bash_boxed` at `Reversible`, and add to that match — **`ToolId("bash")` below `Secretary` is a `ProfileError`; the boxed id at `Secretary` is a `ProfileError`.** Load-time, reader already present, no new field, and no descendant can widen back to the unboxed shell because narrowing is checked two hundred lines earlier.

**It needs its own description.** `SHELL_DESCRIPTION` (`builtin.rs:154`) tells the model *"EVERY call to this one STOPS AND ASKS THEM for approval"* and *"It reaches the network normally"* — both wrong for a boxed shell at `Reversible`. `builtin.rs:421-425` records a live failure from exactly this: two readings of one word in one request body. A test that neither description contains the other's promise.

**And the container must be a kernel object.** `required_tier(Reversible) = Act` (`adjudicate.rs:245`) and the daemon runs at `Act` (`daemon.rs:2091`), so a boxed call is `Allowed` with **no prompt**. A leaked box is silent arbitrary code execution as the user. `current_dir` is not a box.

**Cost, priced properly.** `run_bounded` takes a `std::process::Command` and calls `.spawn()`. `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` must be set at `CreateProcessW`; `CommandExt::raw_attribute` is nightly (verify against the pinned toolchain — one command), and `std::process::Child` cannot be built from a raw handle. So: a `cfg(windows)` `windows-sys` dependency in `marlowe-exec` — which `run_bounded`'s own comment says the crate deliberately lacks — and a rewrite of the pipe-capping/deadline/kill path that A1 and A2 were fixed into. That is the real bill, and it is not zero.

**One thing falls out free.** Pass `PROC_THREAD_ATTRIBUTE_JOB_LIST` in the same `STARTUPINFOEX` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, and `bash("sh -c 'sleep 999 &'")` no longer leaves a grandchild — the leak `run_bounded`'s doc comment names and declines to claim. Same call, same commit.

**Platform refusal, load-time, using the idiom already in the tree.** `WorkspaceScope::new()` refuses on any platform whose suite has never run (`scope/mod.rs:158-163, 232-239`). `TeamBox::new()` does the same: a team on macOS **refuses to start** rather than silently running unboxed. Load-time error over permissive default, in the project's own shape.

---

### Network: give the box the internet, and say plainly what that costs

This is where the human's ordering decides it. A team that cannot `pip install`, `cargo fetch` or `git clone` is not a research team, and *"it absolutely may not get to a point where speed/accuracy/knowledge is hurt."*

Windows AppContainer facts, and the polarity is the opposite of what you would guess:

- Remote network is granted by **capability SIDs**: `internetClient` (S-1-15-3-1), `internetClientServer` (S-1-15-3-2), `privateNetworkClientServer` (S-1-15-3-3).
- **Loopback is blocked independently and is not a capability.** The only exemption is `CheckNetIsolation.exe LoopbackExempt -a -p=<SID>` — **administrator, per-package, all-or-nothing. There is no per-port form.**

So grant `internetClient` and nothing else. The box reaches arxiv.org, PyPI and crates.io; it **cannot** reach 127.0.0.1 — not the daemon, not Ollama, not anything local — and you could not carve out a single port even if you wanted to. Research is unhindered and the worst escape closes for free.

**Say the rest honestly rather than claiming a boundary that is not there:** with `internetClient` granted, the box does **not** contain egress from the shell. ADR-049 §4's `curl` still returns 200. What the box contains is the filesystem and the object namespace — which is exactly *"blast radius is a disposable directory rather than the user's machine"*, and is what was asked for.

**Costs, named:** a dev server inside the box is unreachable from the user's browser; if that matters, the harness proxies it, and that is a separate decision.

### The daemon-token correction, because the design under review had it wrong

SECURITY-AUDIT #4 — *"the daemon has no authentication"* — is **fixed** (`SECURITY-AUDIT.md:26`; `crates/marlowe-daemon/src/auth.rs`; enforced at `daemon.rs:3250` and `control_plane.rs:660`; verified by removing the check and watching an unauthenticated `shutdown` get dispatched). Do not write an ADR on the premise that one `curl` to a fixed port gets full interactive capability.

The sharper point survives and is buildable. `auth.rs`'s header disclaims *"malware running as you… that threat is out of scope."* A sandbox changes that — a boxed process stops being "you" in the sense that matters — so the token becomes load-bearing in a way its author explicitly did not claim. The requirement: **the profile root gets no ACE for the package SID**, and `daemon.token` is therefore unreadable from inside. Two independent walls (no loopback, no token), which is what makes the measurement below discriminating. What is **not** closed: `SocketApprovals` answers on the connection that asked (audit B2) — a token proves which user, not that a human saw the prompt.

### Measurement — every claim a command, every command with a control

**Is the box a box at all** (identity, not a directory listing — it stays runnable forever and does not depend on layout):
```
bash_boxed("whoami /groups")      # must show the AppContainer package SID + Mandatory Label\Low
bash      ("whoami /groups")      # control, interactive run: must show neither
```

**The escape that matters** — two readings, and both must fail:
```
bash_boxed("cat \"$LOCALAPPDATA/marlowe/daemon.token\"")                       # must be denied
bash_boxed("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:<port>/")  # must print 000
bash_boxed("curl -s -o /dev/null -w '%{http_code}' https://example.com")       # must print 200
```
The third line is the control for the second: with `internetClient` granted, `000` on loopback beside `200` on the internet means the container is enforcing. `000` on both would read identically if `curl` were missing — which is instance #15, and is why both are taken.

**The grandchild, closed in the same commit:**
```
bash_boxed("sh -c 'sleep 999 &'") ; then assert no descendant of the job survives
```

**Workspace separation, once step 1 lands:** a test that team A's `write` to a path resolving into team B's root is `Blocked{UndeclaredPath}` — asserted on the adjudication, which is the thing that moved. Mutation control: revert `Adjudication::workspace` to the engine's field and the test must go red.

**The number that decides the ADR's emphasis, takeable today:**
```
sqlite3 "$PROFILE_ROOT/journal.db" \
  "select json_extract(payload,'$.tool'), json_extract(payload,'$.outcome'), count(*)
   from journal where kind='permission_decided' group by 1,2 order by 3 desc;"
```
If `bash`/`needs_approval` dominates — it should, since `adjudicate.rs:422` escalates before the tier comparison — the payoff is the `Irreversible` drop, the egress lift buys almost nothing, and refusing it costs the human almost nothing.

**And the standing latch check, unchanged:**
```
grep -rn "ingest_external(" --include=*.rs crates/*/src/ | grep -v "fn ingest_external"
```

### Rejected

- **Parse the command and allowlist safe ones.** `builtin.rs:16` names it: the Cursor CVE. `$(echo c)url` beats any parse. The box makes a third answer exist — the level drops because reach shrank, not because a string was inspected.
- **Lift the per-host egress approval.** `web` runs in the daemon; no container the team runs in constrains it, and the composed-URL backstop is inert. Lifting it leaves nothing on the exfiltration leg. The lift he actually wants is the pre-seeded `granted` list.
- **A per-package network allowlist via WFP** (`FWPM_CONDITION_ALE_PACKAGE_ID`). Correct mechanism, wrong privilege level: adding WFP filters requires administrator. Revisit if Marlowe ever ships a service.
- **A loopback exemption so dev servers work.** `CheckNetIsolation LoopbackExempt` is admin-only and per-package — it would hand the box the daemon's port and Ollama's along with the dev server. All-or-nothing, and "all" includes the thing running as the user with `bash` at `Irreversible`.
- **A container handle field on `CapabilityProfile`.** New field on a §13-guarded type when `engine.rs:2842`'s narrowing plus a level rule in an existing total match does the job at load time.
- **A per-team daemon via `--workspace`.** ADR-002: one daemon per profile; the journal is a hash chain and a second writer produces `UNIQUE constraint failed: journal.seq`. Also multiplies model weights on a 16 GB card.
- **WSL2 or Windows Sandbox as the box.** Both move the *filesystem* out of the daemon's reach, and `read`/`write`/`glob`/`grep` are all executed daemon-side with real Win32 handles through `PathScope`. Opening those over `\\wsl.localhost` is a network redirector: no `FILE_SHARE_DELETE` pinning, different reparse semantics, and ADR-002's amended check-then-use rule silently weakened. AppContainer is right *because* it boxes the process and leaves the workspace ordinary NTFS the daemon can still open.
- **`"no network" as `network: 0`** — instance #17. Withheld structurally: no capability SID means no socket.
- **`bash("ls ..")` as the separation test.** Its control cannot be run after the change ships, and `.claude/worktrees/` makes a populated parent directory legitimate.
- **Crediting the box with keeping Marlowe unlatched.** He is unlatched because `ingest_external` has no caller and the child's note crosses at `AgentInferred`. The box changes neither, and writing otherwise invites the next session to drop ADR-062's guard.

### Residual risk, after all of it

1. **Exfiltration through `web`** — uncontained by any box, held only by the per-host approval, with the composed-URL backstop inert.
2. **Exfiltration through the boxed shell** — uncontained by design once `internetClient` is granted. Stated, not hidden.
3. **The user reads a poisoned artifact and acts on it.** The box contains the file, not the human — and a team told to "go wild" produces more artifacts, which is what erodes reading. M3-DESIGN §2.2 point 3; deliberate.
4. **The report shaping the human's next decision** — the same channel one hop earlier, and the one that scales.
5. **The harness is never boxed.** The process parsing attacker bytes is the daemon. The extractor panics are fixed (G1–G4, with tests); the xlsx that demands ~200 GB and **aborts past `catch_unwind`** is not.
6. **`bash` inherits the full environment** (A14, open). Nothing to steal while the provider is local Ollama; the day one API key is env-carried, every boxed shell reads it and — since the box does not constrain egress — sends it. Add `env_clear()` plus an allowlist in the same commit as the boxed shell; it is cheap now and expensive later.
7. **No secretary tool may ever reach a team.** Today the answer is *no* for a schedule reason — no email or calendar tool is registered — which is an absence, and absences get filled. Put the rule in the same `match level` as the `bash` rule, as a construction-time failure.

---

# CRITIQUE (usable-with-fixes)

**Fatal:** 

- **The ACL grant goes through the HANDLE, and is a load-time error** — UNBUILDABLE AS WRITTEN. `SetSecurityInfo(handle, ..., DACL_SECURITY_INFORMATION, ...)` requires WRITE_DAC on the handle. `ScopedPath`'s handle is opened by `open_component` (`crates/marlowe-permission/src/scope/walk.rs:107-122`) with `OpenOptions::new().read(true)` plus `write(true)` for the RW arms and nothing else — no WRITE_DAC, no READ_CONTROL beyond what GENERIC_READ implies. The call fails ERROR_ACCESS_DENIED. Adding WRITE_DAC means editing `scope/walk.rs`, which is §13-guarded, and the FFI cannot live in that crate at all: `crates/marlowe-permission/src/lib.rs:28` is `#![forbid(unsafe_code)]`, which no `#[allow]` can override.
  - fix: Do not touch the handle. Set the DACL at CREATION, in the new sandbox crate, with `CreateDirectoryW` and a `SECURITY_ATTRIBUTES` carrying an explicit DACL that grants the derived AppContainer SID full control — before `PathScope` ever walks the directory. Verify once, at creation, with a `GetNamedSecurityInfo` read-back (that read-back is what keeps it out of instance #16). No §13 file is edited, no handle needs a right it does not have, and the load-time-refusal property the idea wanted is preserved exactly.
- **Team identity is SESSION-scoped, and that lands on an already-open human question** — FACTUALLY WRONG AND ALREADY ANSWERED. `docs/design/adr/ADR-068-the-latch-belongs-on-the-session-and-that-was-answered-in-august.md` exists, is **Accepted, M3 Session C, 2026-08-31**, and its §9.4 is titled *"The egress grant's scope, answered SEPARATELY — and `SECURITY-AUDIT.md` §8's own coupling is wrong"*. It amends exactly the coupling this idea proposes as its finding: *"They are opposites... Widening the latch can only ever REMOVE privilege... Widening the grant ADDS privilege for longer... One 'yes, session-scoped' ruling would quietly do both, and it should not."* The idea's headline — "one question with three consumers" — is the conflation an accepted ADR spent a section dismantling one day ago.
  - fix: Delete the framing. Team-workspace lifetime is a FOURTH and independent question, and it is the easiest of the four: a directory that survives a turn confers no privilege on anyone — it is neither a latch (which only subtracts) nor a grant (which adds reach). Say that explicitly, cite ADR-068 §9.4 as the reason it is separable, and answer it on its own without touching ADR-068's deferral or ADR-032 §3.1.
- **The team workspace root is DERIVED by the harness, never named by a model** — NAMES THE WRONG BLOCKER AND MISSES THE LOAD-BEARING ONE. The idea says `Ports.tools` is the blocker. But the wall the adjudicator enforces reads `Request.workspace` — `pub workspace: &'a Path` on `Request` in `crates/marlowe-permission/src/adjudicate.rs` — supplied from `Engine`'s own `workspace: PathBuf` field (`crates/marlowe-loop/src/engine.rs:433`, set once in `Engine::new` at `:595`/`:603`, read at `:1835` where the `Request` is built). And `Engine::spawn` does NOT build a child Engine: it constructs `child_ports` and calls `self.run(...)` (`engine.rs:2451-2466`), so there is exactly ONE `Engine.workspace` for the entire run tree, alongside exactly one `FileSystemTools.workspace` (`lib.rs`, used at `:1100`, `:1114`, `:1371`, `:1394`, `:1559`). A change that swaps the tool host and not the Engine's workspace gives `bash` one root and the permission layer another, silently — the permissive-default family CLAUDE.md logs four bugs from.
  - fix: Treat the root as one value with two readers, and assert it. Whatever mechanism supplies the team root must supply both `Engine.workspace` and `FileSystemTools.workspace`, with a construction-time equality check that refuses when they differ. Then prefer a routing wrapper to a `ToolHostFactory`: one `TeamRoutingTools` owning a map of `team_id -> DaemonToolHost` keeps every inner chain statically composed, needs no boxing per spawn, and leaves `Engine::spawn`'s three `tools: ports.tools` sites (`engine.rs:2457`, `:3174`, `:3505`) untouched. It still adds a fourth link, so it still owes `execute_batch` forwarding and `tests/composition_root.rs::a_batch_reaches_the_innermost_host_through_both_wrappers` — the trap `daemon.rs:707-727` warns about by name.
- **`run_bounded` is refactored to be spawn-agnostic** — THE ~150-LINE REFACTOR OF THE MOST SAFETY-RELEVANT FUNCTION IN `marlowe-exec` MAY BE ENTIRELY UNNECESSARY, AND THE DESIGN DID NOT CHECK. It asserts `std::os::windows::process::CommandExt` "exposes only `creation_flags`, `raw_arg` and `async_pipes` — there is no hook for `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`." `CommandExt::raw_attribute` exists precisely to attach arbitrary `PROC_THREAD_ATTRIBUTE_*` values to a `Command`. Whether it is stable on this toolchain — verified `rustc 1.97.1 (8bab26f4f 2026-07-14)` — is the single highest-leverage unknown in the whole proposal, and the design states the negative as fact without running the check.
  - fix: Check before designing around it. `rustup component add rust-src`, then `grep -n "raw_attribute" -B4 -A4 "$USERPROFILE/.rustup/toolchains/stable-x86_64-pc-windows-msvc/lib/rustlib/src/rust/library/std/src/os/windows/process.rs"` (the component is not currently installed here — I checked). If it is stable, `run_bounded`, `Child`, `try_wait`, `kill`, `drain_capped`, `READER_GRACE_MS` and the `POLL_MS` sleep-counting loop all survive VERBATIM, the `shell_bounds.rs` drift risk never arises, and the sandbox is one `raw_attribute` call plus the profile setup.
- **A helper launcher process (`marlowe.exe --sandbox-exec`) [rejected]** — REJECTED FOR THE WRONG REASON, AND IT IS THE RIGHT FALLBACK. The stated reason is that it "buys AppContainer nothing — `CreateProcessW` with an attribute list works fine from inside the daemon." True and beside the point: what it buys is `run_bounded` unchanged, which is worth far more than one extra 1-3 ms spawn on a ~50 ms Git Bash floor. The design simultaneously prices the alternative at ~150 lines of refactor on the function that carries the output cap, the timeout, the reader grace and the "the command did not finish" body text (`lib.rs:1567-1600` reads `stopped` and `flooded`), and then rejects the option that avoids it.
  - fix: If `raw_attribute` is unstable, ship the launcher: `marlowe.exe --sandbox-launch <profile-name> <cwd> -- <command>`, running on the daemon's own token, inheriting the three pipe handles the daemon already creates. It creates the Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, spawns the AppContainer child with `CREATE_SUSPENDED`, assigns, resumes, waits, and exits with the child's code. Killing the launcher closes the job handle, which kills the sandboxed child — so `child.kill()` at `lib.rs:2631` and `:2643` keeps meaning what it means today, and the grandchild leak that `lib.rs:2574-2583` documents closes as a side effect rather than as a second mechanism. The launcher's own rejection stands only for the separate-local-user option, which needs a credential at rest.
- **AppContainer per team, wrapping `bash` only** — `Capabilities: NULL, CapabilityCount: 0` FAILS THE HUMAN'S STATED ORDERING, AND THIS IS THE DESIGN'S BIGGEST PRODUCT ERROR. A zero-capability AppContainer cannot reach a package index: no `git clone`, no `pip install`, no `cargo fetch`, no `npm i`, no `apt`. The governing constraint is *"research and knowledge comes first. It absolutely may not get to a point where speed/accuracy/knowledge is hurt"* — and a research team that cannot fetch a dependency is crippled by the box, not freed by it. The design treats total network denial as settled good and worries only about loopback (residual risk 4b), never asking whether the human wants the internet inside the box.
  - fix: The capability array is the dial, and it is the product decision this ADR exists to take. Grant `internetClient` (S-1-15-3-1) per team, from the team's profile, and leave the array empty for anything that must not reach out. Loopback is blocked for AppContainers independently of granted capabilities — the documented escape hatch is `CheckNetIsolation LoopbackExempt`, which is admin-gated and unreachable by the agent (`CheckNetIsolation.exe` is present on this machine; `WindowsSandbox.exe` is not) — so a team with `internetClient` gets the open internet with a folder-shaped blast radius while the attack the ROADMAP names at line 63, proxying outward through Ollama on loopback, stays closed. THIS IS UNVERIFIED and must be probe-verified, not asserted: the design's own mutation probe already separates the two axes ("grant `internetClient` → probe 1 returns 200 and probe 2 must still fail"); it simply did not draw the product conclusion from a probe it had already written.
- **The measurement section** — THE PROBES CARRY THEIR OWN INSTANCE #15. `net=FAIL`, `loop=FAIL` and `home=DENIED` are exactly what a child that never started prints. `shell=$BASH_VERSION` is in the script but is never stated as a gate on the other four lines. Worse, `curl` failing reads identically whether the token lacks the capability or `curl` is missing from this MSYS2 install — and the `spawn_shell` control does not discriminate that, because it is a different PATH.
  - fix: Make the TOKEN the subject, not `curl`'s exit code. Inside the box, `whoami /groups` must print the package SID and `Mandatory Label\Low Mandatory Level`, and `whoami /all` must NOT list `S-1-15-3-1`. That reads differently when the attribute silently failed to apply, which no `curl` result does. Then declare every other line void unless both `shell=` and the SID line appeared, and add `command -v curl` to the script so a missing binary is distinguishable from a denied connect.
- **The cheapest first step (the standalone probe)** — THE SCRATCH DIRECTORY'S ANCESTRY IS LOAD-BEARING AND UNSPECIFIED, SO `ws=WRITABLE` MAY ANSWER AN ADJACENT QUESTION. I re-ran the ACL evidence and it reproduces, with one detail the design read past: `C:\Users\matth` carries no ALL APPLICATION PACKAGES ACE, but it DOES carry `S-1-15-3-65536-599108337-2355189375-1353122160-3480128286-3345335107-485756383-4087318168-230526575:(S,X)` — a capability SID granting Synchronize and Traverse to holders of one capability a zero-capability container does not hold. Whether the child can reach a granted leaf under that path therefore depends on whether an AppContainer token carries SeChangeNotifyPrivilege (bypass traverse checking). I did not verify that, and the design does not mention it. A probe run against a scratch directory with different ancestor ACLs measures a path a real team workspace will not have.
  - fix: Run the probe against a directory under `C:\Users\matth\...` — the session scratchpad qualifies — and add `whoami /priv` to the script. If SeChangeNotifyPrivilege is absent or disabled, every ancestor of a team workspace needs traverse for the package SID, which means team roots cannot live under the user profile and the disk and provisioning story changes. Better to learn that in the same hour as the MSYS2 answer.
- **Residual risk 1 (the laundering surface)** — UNDERSTATES A HOLE THAT ALREADY EXISTS, WHICH MAKES THE NET EFFECT ON LAYER 2 WRONG. It says the sandbox CREATES a laundering surface via files. `FileSystemTools::bash` returns `trust: TrustClass::AgentObserved` unconditionally (`crates/marlowe-exec/src/lib.rs:1602-1604`, commented *"the harness observed the exit code; it did not author the output"*). So `bash("curl evil.com")` already launders attacker bytes straight into the parent's window at `AgentObserved`, today, with no file and no sandbox involved — ADR-049 §4's measured HTTP 200 is that hole, not merely an egress gap.
  - fix: State it correctly: the box CLOSES the direct laundering channel by removing the network (or narrows it, under the `internetClient` dial), and OPENS a file-mediated one. Net effect on layer 2 is a wash, not a regression, and the thing that would actually close both is revisiting `bash`'s output trust class — a separate and larger question this ADR should name and decline rather than inherit.
- **`bash`'s consequence level becomes a property of the PROFILE** — MISPRICED: AN EIGHTH `CapabilityProfile` FIELD IS A PINNED-CONTRACT MOVE, NOT JUST A §13 EDIT. `CapabilityProfile` holds exactly seven private fields (`exposed_tools`, `egress`, `interrupt`, `model_route`, `level`, `may_write_memory`, `reads_untrusted`), and ADR-064 pinned it in `CONTRACTS.md` §5 **by membership**, recording that such changes are "escalated, not taken". The design prices this as "a §13-guarded edit, so it arrives with a `DECISIONS.md` entry and an observed permission prompt" and never mentions the contract.
  - fix: Check whether the field is needed at all before proposing it. `AgentLevel` already distinguishes a team head — `AgentLevel::TopAgent { manages: bool }` (`profile.rs:104`), private, constructor-validated, and already read by `CapabilityProfile::new` and by `AgentLevel::child_of`. If the box is keyed on the level, there is no eighth field, no contract move, and no instance-#16 exposure, because the reader already exists and is already tested. If a separate field is genuinely required, price it as a contract escalation with ADR-064's precedent, and name `adjudicate`'s reader line before adding it.
- **The summary's framing of ADR-002** — MISREADS ADR-002 IN A WAY THAT MAKES THE ASK HARDER THAN IT IS. The design says it "revisits ADR-002 narrowly" by restoring a kernel backstop on a path that never had one. ADR-002's revised Execution model (`docs/design/DECISIONS.md:548`, revision dated 2026-08-02) says something more useful: *"Sandboxing is retained, scoped to one profile"* — the quarantined reader, `reads_untrusted: true` with an empty `exposed_tools`, "keeps a sandbox backend", and *"a container backend covers it on Windows without the override-erosion problem that killed the general case."* That backend has never been built.
  - fix: Lead with the carve-out that already exists. The same `marlowe-sandbox` crate serves the quarantined reader ADR-002 already authorised AND the shell team, which turns the acceptance question from "reopen ADR-002's removal of the kernel backstop" into "extend an already-accepted, already-scoped carve-out to a second profile, and build the backend that was promised in August." That is a materially cheaper ask, and it is true.
- **AppContainer per team (environment)** — ENVIRONMENT INHERITANCE IS UNADDRESSED, AND IT BECOMES AN EXFILTRATION PRIMITIVE UNDER THE FIX ABOVE. `run_bounded` sets `cmd.stdin(Stdio::null())` and pipes both output streams (`lib.rs:2596`) and never calls `env_clear`. The sandboxed child therefore inherits the daemon's entire environment — `MARLOWE_CUDA_LIB_DIR` and, more to the point, whatever provider credentials ADR-046's OpenRouter path and the local-runtime path read. A box with no network makes that harmless; a box holding `internetClient` plus the parent's API keys is an exfiltration primitive that neither the ACL nor the WFP filter touches, because the traffic is the box's own and perfectly legitimate.
  - fix: Explicit allowlist env for the sandboxed child — `PATH`, `HOME`, `TEMP`, `TMP` and nothing else — the same shape as the eval harness's `minimal_env()`, which CLAUDE.md already describes as a fixed allowlist. Make it a load-time property of the sandbox spawn, not a flag, so it cannot be forgotten.
- **Cost: disk** — THE DISK NUMBER MEASURES THE WRONG OBJECT. "A few hundred KB of empty structure per team under `%LOCALAPPDATA%\Packages`" is right about the AppContainer profile and irrelevant to the cost. The team workspace is where a research team puts a `git clone`, a venv and a model download, and that is gigabytes. Residual risk 3 notes there is no quota without FSRM (admin) and stops there, leaving "a team can fill the volume" as an accepted risk with no instrument.
  - fix: No quota, but a number, per the working agreement's rule that every numeric target becomes a command that prints one. Walk the team root at each turn boundary and surface the byte count as a `Metric::Count`, so "the volume is filling" is observable in the product before it is fatal. That is cheap (the walk is already bounded by `WALK_FILE_CAP`) and it is the difference between an accepted risk and an unobservable one.
- **Three things are unverified and I will not assert them** — THE LIST IS TWO SHORT, AND THE TWO MISSING ONES ARE ASSERTED AS FACT IN THE SUMMARY. (a) *"Loopback is additionally blocked for AppContainers by default"* is stated flatly and is the load-bearing claim under the ROADMAP's named attack; whether it holds independently of granted capabilities is not established. (b) An AppContainer token carrying bypass-traverse-checking is assumed silently by the whole "grant the leaf, ignore the ancestors" ACL plan. Both read as verified because they sit in a paragraph that opens by announcing what is unverified.
  - fix: Add both to the unverified list, and add both to the probe: `whoami /priv` for the privilege, and the loopback curl re-run with `internetClient` granted for the independence. Until the probe runs, mark them UNVERIFIED in the ADR text itself, not in a trailing caveat — the design's own discipline about what a claim's confidence looks like on the page applies to this page.

## Strengthened

# The mechanism: what enforces the team box on Windows 11, what it costs, and what it cannot do

## 1 · The box contains one child process, and that decides everything

Six of the seven working tools never leave the daemon. `FileSystemTools::dispatch` (`crates/marlowe-exec/src/lib.rs:1993-2002`) routes `read`, `write`, `edit`, `glob`, `grep` and `web` to in-process executors that operate on handles the adjudicator opened. `bash` is the only one that spawns: `spawn_shell` at `lib.rs:2523` builds `Command::new(git_bash).arg("-c")` and hands it to `run_bounded` at `:2584`.

So the question is not "how do I sandbox Marlowe". It is: **spawn one child with a filesystem view of one directory and a network capability the team's profile chose, while the daemon reaches in freely.** That asymmetry is free — the daemon keeps its own token — and it is why the harness keeps working: `web`, the model call, the journal and every file tool are on the daemon's side of the wall, untouched.

## 2 · ADR-002 already authorised a sandbox backend, and it was never built

The framing is not "reopen ADR-002". `DECISIONS.md:548`, Execution model revised 2026-08-02, says: *"Sandboxing is retained, scoped to one profile"* — the quarantined reader keeps a sandbox backend, and *"a container backend covers it on Windows without the override-erosion problem that killed the general case."* **No such backend exists.**

One `crates/marlowe-sandbox` serves both: the quarantined reader ADR-002 already carved out, and the team shell. The ask is to extend an accepted carve-out to a second profile and build the thing promised in August — not to revisit the removal of the kernel backstop on the ordinary path, which stays removed for all six in-process tools and whose accepted cost is unchanged.

## 3 · The mechanism, and the capability array is the product decision

`DeriveAppContainerSidFromAppContainerName(L"marlowe-team-<id>")` gives a deterministic SID from a name, so the team folder's DACL can be written before the process exists and survives daemon restarts. `CreateAppContainerProfile` is idempotent, needs no elevation, and costs a few hundred KB under `%LOCALAPPDATA%\Packages`. Then `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` with `SECURITY_CAPABILITIES { AppContainerSid, Capabilities, CapabilityCount }`.

**`Capabilities` is a dial, not a zero.** The submitted design hardcodes `NULL, 0` and calls total network denial containment. It is containment, and it fails the governing constraint: a zero-capability container cannot `git clone`, `pip install`, `cargo fetch` or reach any package index. *"Research and knowledge comes first"* is not satisfied by a research team that cannot fetch a dependency.

| Team profile | Capability array | What the team gets | What is closed |
|---|---|---|---|
| research, default | `[S-1-15-3-1]` (`internetClient`) | the open internet, `git`, `pip`, `cargo` — no prompt, no allowlist | the user's filesystem; **loopback** |
| quarantined reader (ADR-002's carve-out) | empty | nothing outbound | everything |

Loopback is blocked for AppContainers irrespective of granted capabilities; the documented exemption is `CheckNetIsolation LoopbackExempt`, admin-gated and unreachable by the agent (`CheckNetIsolation.exe` is present on this machine, `WindowsSandbox.exe` is not). **That is the operating point this product wants**: the ROADMAP's named attack at line 63 — proxying outward through Ollama on loopback — stays closed while the team goes wild on the internet inside a folder-shaped blast radius. **UNVERIFIED**, and probe 2b below is what settles it.

This is containment, not filtering: no command text is inspected, ever. There is no spelling of `curl` that acquires a capability the token does not hold, and no spelling that reaches `C:\Users\matth`.

**Environment is allowlisted, not inherited.** `run_bounded` nulls stdin and pipes both output streams and never calls `env_clear` (`lib.rs:2596`). A box holding `internetClient` and the daemon's provider credentials is an exfiltration primitive no ACL or WFP filter touches, because the traffic is its own and legitimate. `PATH`, `HOME`, `TEMP`, `TMP`, nothing else — the shape of the eval harness's `minimal_env()`, enforced at the spawn, not behind a flag.

## 4 · The ACL goes on at creation, not through a handle

`SetSecurityInfo` on `ScopedPath::handle()` **cannot work**. `open_component` (`scope/walk.rs:107-122`) opens with `read(true)` plus `write(true)` and no `WRITE_DAC`; the call returns ERROR_ACCESS_DENIED. Adding the right means editing a §13-guarded file in a `#![forbid(unsafe_code)]` crate (`marlowe-permission/src/lib.rs:28`), where the FFI cannot live regardless.

Instead: `CreateDirectoryW` with a `SECURITY_ATTRIBUTES` carrying an explicit DACL granting the derived SID full control, in the sandbox crate, at team creation, before `PathScope` ever walks it. Verify with a `GetNamedSecurityInfo` read-back in the same function — that read-back is the difference between a control and instance #16 — and refuse at creation with a named error, so a team never discovers an unprovisioned box by burning budget on a `bash` that says only "failed".

**One ancestry question is open and I did not verify it.** `C:\Users\matth` carries no ALL APPLICATION PACKAGES ACE — only `S-1-15-3-65536-599108337-…:(S,X)`, a capability SID granting Synchronize+Traverse to holders of a capability a zero-capability container lacks. Whether the child reaches a granted leaf beneath it depends on the token carrying SeChangeNotifyPrivilege (bypass traverse checking), which the probe answers with `whoami /priv`. If it does not, team roots cannot live under the profile and the provisioning story changes.

## 5 · Two roots move together, or the wall disagrees with itself

The submitted design names `Ports.tools` as the blocker for per-team roots. **The blocker that matters is the other one.** The adjudicator — the actual wall — reads `Request.workspace` (`pub workspace: &'a Path` on `Request`, `adjudicate.rs`), supplied from `Engine`'s own `workspace: PathBuf` (`engine.rs:433`, set once in `Engine::new` at `:595`/`:603`, read at `:1835`). And `Engine::spawn` builds no child engine — it constructs `child_ports` and calls `self.run(...)` (`engine.rs:2451-2466`). **One `Engine.workspace` for the entire run tree, and one `FileSystemTools.workspace` beside it.**

Swap the tool host alone and `bash` runs in the team folder while the permission layer walls to the daemon's — a mismatch nothing observes. So:

- The team root is one value with two readers, supplied together, with a construction-time equality refusal when they differ.
- Prefer a **routing wrapper** to a `ToolHostFactory`: one `TeamRoutingTools` owning `team_id -> DaemonToolHost` keeps every inner chain statically composed, needs no boxing per spawn, and leaves the three `tools: ports.tools` sites (`engine.rs:2457`, `:3174`, `:3505`) untouched. It is still a fourth link, so it still owes `execute_batch` forwarding and `tests/composition_root.rs::a_batch_reaches_the_innermost_host_through_both_wrappers` — the trap `daemon.rs:707-727` warns about by name.
- A model-supplied `workspace` on `SpawnRequest` is a **target** in layer 3's sense and joins `composes_spawn_targets` (`engine.rs:3740`) beside `exposed_tools`, `budget_tokens`, `orphan_policy` and `role`.
- **No eighth `CapabilityProfile` field until it is shown to be needed.** ADR-064 pinned that type in `CONTRACTS.md` §5 *by membership*; an eighth field is a contract escalation, not a §13 edit. `AgentLevel::TopAgent { manages: bool }` (`profile.rs:104`) already marks a team head, is already private and constructor-validated, and is already read by `CapabilityProfile::new` and `child_of`. Key the box on the level and there is no new field, no contract move, and no unread control.

## 6 · Check `raw_attribute` before refactoring anything

The claim that `CommandExt` has no hook for a proc-thread attribute is **unchecked**. `CommandExt::raw_attribute` exists for exactly this. Toolchain here is `rustc 1.97.1 (8bab26f4f 2026-07-14)`; `rust-src` is not installed. One command decides:

```
rustup component add rust-src
grep -n "raw_attribute" -B4 -A4 "$USERPROFILE/.rustup/toolchains/stable-x86_64-pc-windows-msvc/lib/rustlib/src/rust/library/std/src/os/windows/process.rs"
```

- **Stable** → `run_bounded`, `Child`, `try_wait`, `kill`, `drain_capped`, `READER_GRACE_MS` and the `POLL_MS` loop survive verbatim. The sandbox is one call plus profile setup. No refactor of the function carrying the output cap, the timeout and the "the command did not finish" body text.
- **Unstable** → ship the **launcher**, and do not refactor. `marlowe.exe --sandbox-launch <profile> <cwd> -- <cmd>` runs on the daemon's token, inherits the three pipes the daemon already made, creates the Job Object with `KILL_ON_JOB_CLOSE`, spawns the AppContainer child `CREATE_SUSPENDED`, assigns, resumes, waits, exits with the child's code. `child.kill()` at `lib.rs:2631`/`:2643` keeps meaning what it means today, and the grandchild leak documented at `lib.rs:2574-2583` closes as a side effect. Cost: one extra `CreateProcessW` (~1-3 ms) on a ~50 ms Git Bash floor, against ~150 lines of surgery on the most safety-relevant function in `marlowe-exec`. The launcher is the right shape here even though it is the wrong shape for the separate-local-user option, which needs a credential at rest.

## 7 · Team lifetime is a fourth question, and it is the easy one

The submitted design calls the team folder's lifetime a third consumer of one open scope question. **That is the coupling `ADR-068` §9.4 — Accepted 2026-08-31 — exists to dismantle**: widening the trust-floor latch only ever *removes* privilege; widening an egress grant *adds* reach for longer; *"one 'yes, session-scoped' ruling would quietly do both, and it should not."*

A durable team directory is neither. It confers no privilege on anyone — it is a place, not a permission — so it can be answered on its own without touching ADR-068's deferral or ADR-032 §3.1. Note only that `Daemon::ask_streaming_with` builds a fresh `Run::root` per user message (`daemon.rs:2609`), so the key is the team, not the `RunId`, and the ephemeral half (a box for one turn) ships either way.

## 8 · Measurement — every probe with the control that makes it evidence

Take these in one session, nothing else building (parallel-sessions form 6: a 16-core build inflated a timed table ~10% and it looked complete).

**0 · The token, first, and everything else is void without it.** Inside the box: `whoami /groups` prints the package SID and `Mandatory Label\Low Mandatory Level`; `whoami /all` does **not** list `S-1-15-3-1` in the empty-array configuration; `echo shell=$BASH_VERSION` prints `5.x`; `command -v curl` prints a path. This is the #15-proof check — a `curl` failure reads identically when the attribute never applied, when the child never started, and when `curl` is absent. A token listing does not.

**1 · Internet.** `curl -s -o /dev/null -w '%{http_code}' --max-time 5 https://arxiv.org; echo rc=$?`. Empty array → connect failure. `internetClient` granted → `200`. Unsandboxed control → `200`, reproducing ADR-049 §4's published prior; if it does not reproduce, you measured the network, not the box.

**2 · Loopback.** Same against `http://127.0.0.1:11434/api/tags` (Ollama). Sandboxed → failure. Unsandboxed control → `200` whenever the daemon is up.

**2b · Independence — the one that licenses §3's operating point.** Re-run probe 2 *with* `internetClient` granted. Probe 1 must read `200` and probe 2 must **still** fail. If loopback opens with `internetClient`, the whole capability dial collapses back to the zero array and the research cost is real.

**3 · The harness is untouched.** One `web` fetch through the approval modal, same turn, same run → a `DocumentRef` with non-zero chars. Control: the same host declined → `NeedsApproval` → blocked. Without this, "no network in the box" is indistinguishable from "no network anywhere".

**4 · Freedom inside.** `mkdir -p adr/ADR-001 && echo x > adr/ADR-001/notes.md && ls -R adr | wc -l` → a line count, **with no approval prompt**. Control, same run: writing to `/c/Users/matth/Desktop/x` fails. Two numbers.

**5 · The machine is invisible.** `ls /c/Users/matth` and `cat /c/Users/matth/.ssh/id_rsa` → denied on both. Control: unsandboxed, the first lists. Run the probe's scratch root **under `C:\Users\matth`** so ancestor ACLs match a real team folder, and print `whoami /priv` in the same breath.

**6 · Latency — decisive, because speed is the governing constraint.** 50× `bash("true")`, sandboxed and unsandboxed, separate sessions, print both medians and the delta. Over ~10 ms and the design must say so out loud.

**7 · Disk, as a standing metric not a one-off.** Walk the team root at each turn boundary and surface the byte count as a `Metric::Count`. There is no quota without FSRM (admin), so the answer is not a limit — it is a number, printed, before the volume fills.

**8 · Mutations, which are what make 1 and 2 evidence.** Delete the `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` call → probe 0 loses the package SID and probe 1 goes to `200`. Delete the DACL grant → probe 4 goes red at `mkdir`. Delete the profile-level consequence change → probe 4 stops and asks. All live probes, none unit tests.

## 9 · Rejected

**Windows Sandbox** — absent on this machine (optional feature, admin to enable), a full Hyper-V VM at ~1-2 GB and seconds to start, historically one instance, and **stateless by design**: it deletes exactly the ADR folders the human's example accumulates.

**Restricted tokens / SAFER** — gate securable objects, not sockets. No WFP condition keys on "has restricting SIDs". It confines the filesystem, duplicating `PathScope` plus an ACL, and leaves `curl` working — the half-measure ADR-049 §4 already measured. AppContainer is this idea with the network filter attached.

**Job Objects as the box** — lifetime and resource container, no network limit of any kind. Rejected as the box, adopted as a separate mechanism for the grandchild leak.

**A separate local user + firewall rule** — user creation and firewall rules both need admin (this shell is not elevated), `CreateProcessWithLogonW` needs a credential at rest, the rule is machine-global state outliving the harness, and `-LocalUser` on an outbound rule is **unverified**. The filesystem half still needs the same ACL work.

**WSL2 `unshare -n`** — needs root in the *user's* distro; a harness-owned distro is GBs of VHDX per team. The killer is `/mnt/c` drvfs overhead in the tens of ms per file, which is `grep -r` over a real tree, against a constraint that says speed may not be hurt. And the handle discipline `scope/walk.rs` exists to enforce does not cross into the Linux kernel.

**A persistent piped shell per team** — amortizes Git Bash startup to zero and destroys `run_bounded`. A timeout kills the shell, losing the state persistence bought; framing a command needs a sentinel and an `echo $?`, so the harness parses a stream the model writes into, and `echo __MARLOWE_DONE__; echo 0` forges a success. §8.1's shape in a new place. Recorded because the latency argument will be made again.

**Refining `bash`'s level by inspecting the command** — not proposed, not revisited. `builtin.rs:16` is right and ADR-026 was correct on the options it had. The level moves because the blast radius moved; no command text is ever read.

**Docker, as declared fallback only** — verified present (28.3.3, `docker-desktop` WSL2 distro). `--network=none` is airtight and its loopback is the container's own, so a dev server inside is reachable inside — the one thing AppContainer may not give. But Docker Desktop becomes an install-time dependency of the shell working at all (2 GB and a VM, the K6 objection `daemon.rs:229-238` records against requiring the cross-encoder), `docker exec` is ~80-150 ms warm against ~50 ms today, and the bind mount re-resolves paths in the Linux kernel where `PathScope`'s handle discipline does not reach.

## 10 · Residual risk

**1 · The laundering channel, stated correctly.** `FileSystemTools::bash` returns `TrustClass::AgentObserved` unconditionally (`lib.rs:1602-1604`). So `bash("curl evil.com")` launders attacker bytes into the parent's window at `AgentObserved` **today**, with no sandbox and no file — that is what ADR-049 §4's HTTP 200 actually costs. The box *closes* that direct channel (or narrows it under the capability dial) and *opens* a file-mediated one: the team writes `adr/ADR-007/notes.md`, the parent `read`s it, and the lineage break is a filesystem round trip no `derivation` vector records. **Net effect on layer 2 is a wash, not a reduction.** Do not ship this claiming it lowers injection risk. What would close both is revisiting `bash`'s output trust class, which is a larger question this ADR names and declines.

**2 · The box is around `bash`, not around Marlowe.** Six of seven tools run on the daemon's token and reach the whole filesystem. ADR-002's accepted cost is unchanged for them; a traversal defect in `scope/walk.rs` is exactly as severe after this as before. Anyone reading "Marlowe now has a sandbox" will get this wrong, so the ADR leads with it.

**3 · Unbounded disk.** No quota without admin. Probe 7 makes it observable, not bounded.

**4 · Five unverified claims, none promoted.** (a) Git Bash/MSYS2 under AppContainer's redirected `\Sessions\N\AppContainerNamedObjects\<SID>` namespace — the largest unknown; fallbacks are busybox-w32 or Docker. (b) Same-container loopback between two of the team's own processes. (c) The `windows-sys` module path for `CreateAppContainerProfile`. (d) **Loopback denial being independent of granted capabilities** — §3's operating point rests on it. (e) **The token carrying bypass-traverse-checking** — §4's ACL plan rests on it. One probe answers all five.

**5 · `LoopbackExempt` is a real, admin-gated escape hatch.** The agent cannot run it. A *user* who runs it once to debug something silently disables probe 2 forever, and probe 2 would print failure only until they did. Re-run it; never cite it.

**6 · Sequencing, as an instruction.** `bash`'s `Irreversible` escalation is the only egress control on that path today. Lift it before probes 0, 1 and 2 pass and the product goes from "a human sees every shell command" to "nothing sees any of them" in one commit. **The two ship together or not at all.**

**7 · Windows-only.** All of it is `#[cfg(windows)]`, with `WorkspaceScope::new`'s load-time refusal shape (`scope/mod.rs:227-240`) copied exactly — a named `PlatformUnverified`-style error, never a silent unsandboxed shell under a profile claiming to be sandboxed.

## 11 · First step, and it costs an hour

One standalone Rust binary in the scratchpad — outside the workspace, no crate touched, no ADR, no §13 approval. It creates profile `marlowe-probe`, derives the SID, creates a scratch directory **under `C:\Users\matth`** with a DACL granting that SID, and launches `C:\Program Files\Git\bin\bash.exe -c '<script>'` under `SECURITY_CAPABILITIES`, capturing stdout through `CreatePipe`. Run it three times: empty capability array, `internetClient` granted, and unsandboxed control.

```
whoami /groups | grep -i "appcontainer\|Mandatory Label";
whoami /priv | grep -i changenotify;
echo shell=$BASH_VERSION; command -v curl;
curl -s -o /dev/null -w 'net=%{http_code}\n' --max-time 5 https://arxiv.org || echo net=FAIL;
curl -s -o /dev/null -w 'loop=%{http_code}\n' --max-time 5 http://127.0.0.1:11434/api/tags || echo loop=FAIL;
ls /c/Users/matth >/dev/null 2>&1 && echo home=READABLE || echo home=DENIED;
touch ./probe.txt && echo ws=WRITABLE || echo ws=DENIED
```

Three columns settle the design. `shell=5.x` plus the package SID closes the largest unknown and validates every other line; without both, the run is INVALID, not contained. `net=FAIL` in column 1 and `net=200` in column 2 with `loop=FAIL` in **both** licenses §3's operating point. `home=DENIED` confirms the ACL evidence holds in practice. `ws=WRITABLE` plus the `changenotify` line confirms the grant and the traverse assumption together.

Clean → the sequencing is: probe → `raw_attribute` check → `marlowe-sandbox` (AppContainer + Job Object + creation-time DACL) → the root-derivation change with its two-reader equality assertion → the profile-level escalation change, **last, with probes 0/1/2 green**. Dirty → an hour spent, and Docker is priced honestly instead of discovered halfway through a `run_bounded` refactor that should never have started.

---

# CRITIQUE (usable-with-fixes)

**Fatal:** Idea #4 — "ToolHost::execute_batch gains a root argument" — edits `crates/marlowe-loop/src/driver.rs`, which is entry line 99 of `PROTECTED` in `.claude/hooks/protect-boundaries.py` ("the memory and approval ports"). Idea #1's mechanism paragraph boasts, about that exact file: "This design touches it not at all, and that is deliberate." The design contradicts itself on its own central §13 claim, because it never checked which crate `ToolHost` (driver.rs:570) and `BatchItem` (driver.rs:563) live in. That mis-prices the load-bearing change: "mechanical, a few hundred lines, no latency" is in fact a security-machinery edit that trips the hook and, per its own docstring, "should arrive with a `DECISIONS.md` entry". Worse, the design never noticed cheaper driver.rs-free routes exist — `Ports` is in `engine.rs:241` (unguarded), and `glob`/`grep` already take their base from `handle_for(a, "path")` out of `Adjudication.handles`, so five of `self.workspace`'s six readers retire with no trait change at all. A session building this as written hits a §13 prompt on the central edit and finds the surgical route only afterwards.

- **The tool host takes the root per batch, and `FileSystemTools.workspace` is deleted** — `ToolHost` (`crates/marlowe-loop/src/driver.rs:570`) and `BatchItem` (`driver.rs:563`) are both in the §13-guarded `driver.rs` (PROTECTED line 99). Changing `execute_batch`'s signature is a guarded edit. Every alternative the design weighed also crosses a wall: `Adjudication` is in `crates/marlowe-permission/src/adjudicate.rs:176`, also PROTECTED. The design asserts the opposite as a virtue.
  - fix: Route the root through `Ports` (`engine.rs:241`, UNGUARDED) as a separate port — `roots: &dyn RunRoot`, trait in a new `marlowe-loop/src/workspace.rs` — and retire `FileSystemTools.workspace`'s readers rather than re-plumbing them. Five of six are avoidable today: `lib.rs:1100`, `1114`, `1371`, `1392` are `strip_prefix(&self.workspace)` purely for relativization, and the already-adjudicated `ScopedPath` carries `relative()` (used by `read` at `lib.rs:1040`); `lib.rs:1559` is `bash`'s cwd *fallback*, removable by requiring `cwd` for boxed runs. Only `lib.rs:1394`'s `self.scope.open(declared, &self.workspace, &relative, Access::Read)` in `grep`'s per-file re-open genuinely needs a root — one value reaching one call site, not a trait signature.
- **Three provisioning modes, and `Graft` is a sparse `git worktree` (the knowledge argument)** — Instance #15, inside the design's own §1-ordering justification. The 200-entries-truncated / 73-entries measurement is taken on `workspace_map` (`daemon.rs:3416`), whose ONLY caller is `daemon.rs:2662`, inside `Daemon::turn`, pushing a `SourceKind::ProjectFiles` block into the *secretary's* `SessionMemory`. `Engine::spawn` builds `child_state = SessionState::new(child_run.session, state.identity.clone())` (`engine.rs:2393`, `3067`, `3474`) and pushes only the brief and governance. A spawned team receives no workspace map at all, today, at any size. The number reads identically whether provisioning works, fails, or was never built — it is measured on a path no boxed team reaches.
  - fix: State the real finding: the map is secretary-only, so provisioning must ALSO seed the child's state with `workspace_map(box_root)` at the three `child_state.push` sites, and the entry-count target becomes a property of that new block. Until that line exists the 73-vs-200 number is not evidence about a team's knowledge. Note also `WALK_SKIP` (`marlowe-exec/src/lib.rs:195`) is `[".git","target","node_modules",".venv","__pycache__","dist"]` and `workspace_map` additionally drops every dotfile except `.claude` — so a `Graft` containing `.github/` or `.cargo/` is readable by `read` and invisible in the map.
- **Measurement — disk, measured on this checkout rather than estimated** — The prescribed command is broken and its headline number is wrong by ~1.9x. `git ls-files -z | xargs -0 du -cb | tail -1` emits one `total` line PER xargs batch; on this checkout xargs splits into 3 batches, so `tail -1` reports the last chunk only. Measured: that command yields 133,098,253 (the design reports 133,342,199, same method, drifted); the true sum is 247,256,212 over 1,635 files. The `Graft` figure survives by luck — `crates docs tools eval` is 623 files, fits one batch, true total 11,510,844 against the claimed 11,511,000. A command printing a plausible number while summing a third of its input is precisely the family this project counts.
  - fix: `git ls-files -z | xargs -0 du -b | awk '{s+=$1} END{print s}'`. The corrected copy-rejection is stronger, not weaker: a full copy is 247 MB per team, not 133 MB. `du -sh .git` = 7.2G is right and remains the decisive worktree number.
- **The box lives on CapabilityProfile as a private field** — Three problems. (1) `CapabilityProfile::new` (`profile.rs:276`) takes seven positional arguments; adding an eighth edits `profile.rs`, which is PROTECTED — so this idea is *also* a §13 edit, unacknowledged. (2) The proposed invariant `level != AgentLevel::Secretary && workspace == UserRoot` is a negated equality over a five-variant enum, and `profile.rs:311-318` refuses wildcard arms by name: "**No wildcard arm.** A sixth `AgentLevel` variant is a compile error here rather than a level that quietly inherits whichever neighbour `_` happened to cover -- the #19-safe shape". A `!=` is a wildcard wearing a different hat. (3) The Deserialize-refuses-a-bad-checkpoint story requires an absolute `PathBuf` inside `Checkpoint` (`durable.rs:87`), which makes a signed checkpoint machine-bound and writes the user's home directory into the record.
  - fix: Write it as an exhaustive `match level`, one arm per variant, matching `profile.rs:314`'s existing style. Serialize a profile-root-relative box **id** (`boxes/<id>`), not an absolute path, and resolve against `config.profile_root` at restore. Bump `CHECKPOINT_VERSION` 1→2 — `durable.rs:75-79` says the version exists exactly because "every default this struct could take is a security property reset to its permissive value". And say plainly this is a `profile.rs` edit under §13 with a `DECISIONS.md` entry, rather than presenting the design as boundary-free.
- **The consumer count in the summary and in `cheapest_first_step`** — "It reaches the tools by two independent paths" and the expected grep output "the two setters + status/display rows" undercount. `self.config.workspace` has FOUR functional consumers, verified: `daemon.rs:2090` (`Engine::new` → `Request::workspace` at `engine.rs:1835`), `:2498` (`build_tool_host` → `FileSystemTools::new(scope, workspace.to_path_buf())`), `:2628` (the `workspace_rule` governance string "The workspace is {}. Every path you name is relative to it."), `:2662` (`workspace_map`). Plus `:1057`, a boot-time `build_tool_host`. Re-rooting the first two only ships a team told the user's directory is its workspace while every path resolves inside a box.
  - fix: Correct the expected output to four functional sites, one boot check, three display rows, and make all four part of provisioning. `:2628` is the sharper trap: `assert_governance` is documented at `:2623` as asserted once per conversation because "re-asserting per turn would grow the stable tier by two blocks a turn" — so a session whose box changes mid-conversation keeps a stale absolute path in the **stable tier**, structurally un-updatable. Either the box is fixed for the life of a session, or that block needs a replace-in-place path that does not exist.
- **The AppContainer is a second act on the same directory** — Platform claims asserted from memory; several conflated, and the largest blockers missing. (a) AppContainer loopback is blocked regardless of capabilities — `internetClient` governs outbound internet, `privateNetworkClientServer` the local subnet; neither ever grants loopback. The design reaches the right conclusion from the wrong mechanism, and `CheckNetIsolation LoopbackExempt` is a documented development aid, not a shipping configuration. (b) `std::process::Command` CANNOT create an AppContainer process — it needs `CreateProcessAsUserW` + `UpdateProcThreadAttribute` with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`, plus `CreateAppContainerProfile`. Verified: `grep -rn "windows-sys\|winapi" --include=Cargo.toml` returns NOTHING in this workspace, and `lib.rs:2576` already records declining that dependency for Job Objects. (c) The Windows shell is **Git Bash, not cmd** — `shell_command()` (`lib.rs:2415-2426`) resolves `git_bash()`, runs `bash -c`, sets `CREATE_NO_WINDOW`, and errors with an install-Git-for-Windows message. AppContainer-ing msys2 bash means ACLing the whole Git tree for the package SID and betting on msys2 fork emulation under a restricted token; the one-line `icacls <box> /grant` covers the box and not the interpreter.
  - fix: Keep the deferral — it is the right call — but re-argue it from those three verified blockers rather than from loopback alone, and state loopback correctly. Add why WFP does not rescue it: user-mode `FwpmFilterAdd` with `FWPM_CONDITION_ALE_APP_ID` keys on the image path, and a boxed team's shell and Marlowe's own shell are the same `bash.exe`; the only condition that separates them is `FWPM_CONDITION_ALE_PACKAGE_ID`, an AppContainer SID — so the two routes converge and WFP additionally needs admin. Worth noting too that ADR-002's cited carve-out ("the quarantined reader keeps a sandbox backend") is itself unbuilt: no sandbox backend exists in `crates/`.
- **Lifecycle: `Terminate` seals rather than deletes** — "Sealed (made read-only)" has no mechanism and the process story is missing. A directory's `FILE_ATTRIBUTE_READONLY` does not make its children read-only on Windows; the only real seal is a deny-write ACE, which the daemon (same user token) can remove, and which surfaces to the model as an opaque `ERROR_ACCESS_DENIED` from `std::fs` rather than a `ScopeError` with a remedy. Separately, `run_bounded`'s own comment (`lib.rs:2570-2578`) states `child.kill()` kills the shell and not what the shell started — no process group, no Job Object — so a terminated run can leave a `bash`-spawned grandchild still writing into the box just sealed. And `settle_orphan` (`durable.rs:361`) is pure, returns an amended `Checkpoint`, and touches no filesystem, so box treatment cannot hang off "the same match".
  - fix: Put the seal in `settle_orphan`'s CALLERS and factor it into one function — the doc at `durable.rs:358` says there are two writers (the loop via `Recorder`, the daemon via `CheckpointStore`) and "a decision with two implementations is a decision that drifts". Define the seal as a deny-write ACE that is advisory against the agent, not against the daemon. State the grandchild as an accepted residual by name. Give `marlowe --boxes --stale` a second column for boxes with a live descendant process, so the gap is visible rather than implied.
- **Boxes are flat siblings, never nested** — The argument is sound and the evidence checks out (`WORKSPACE = "./**"` at `builtin.rs:61`; `PathGlob` is `#[serde(transparent)] pub struct PathGlob(String)` at `manifest.rs:185` with no negation; `scope/glob.rs` is in `PROTECTED_DIRS`). But the design's own residual_risk concedes the fatal shape and ships anyway: the layout is a provisioner's convention, nothing in `CapabilityProfile::new` distinguishes a sibling from a nested path, and the only detector of a regression is a mutation a human runs by hand. That is #19-shaped — the guard's correctness is a fact about a function nobody re-checks.
  - fix: Make it a load-time invariant, not a convention: a box path is `profile_root/boxes/<id>` with exactly one component after `boxes/`, refused by name as `BoxError::NestedBox` in the constructor that mints a box. A provisioner "tidied up" into nesting then fails to construct rather than silently reopening the upward channel, and the hand-run mutation becomes a backstop instead of the whole enforcement.
- **Getting work out: `promote`** — `promote(<child-run>, <relative-path>)` needs two handles in two different roots, and nothing in the permission layer has that shape: `Adjudication.handles` is `BTreeMap<String, ScopedPath>` keyed by parameter name (`adjudicate.rs:179`), opened against a single `Request::workspace: &'a Path` (`adjudicate.rs:169`). The design's own read_by admits it — "`PathScope::open` twice, once in each box" — which is a change to `adjudicate.rs` and `scope/`, both PROTECTED, priced as "one new builtin tool".
  - fix: Invert the direction: make it a child-side push, `deliver(<relative-path>)`, adjudicated in the child's own single root against its own `Request::workspace`; the harness copies into the parent's box. One handle, one root, no `adjudicate` change — and it runs in the same direction as `Engine::spawn`'s return hop, where ADR-063's A8 arm already sits (`engine.rs:~2911`). The trust-class question (`AgentObserved` per `lib.rs:1041` vs quarantined; `Channel::Agent` with zero production construction sites) is correctly flagged as the human's and is unchanged by the inversion.
- **The environment is part of the box** — The gap is real and correctly measured (`grep -n "env_clear\|\.env(\|env_remove" crates/marlowe-exec/src/lib.rs` returns nothing — confirmed), but the allowlist has a Windows trap the design does not name, and `eval/`'s `minimal_env()` does not transfer. The interpreter is msys2 bash (`shell_command()`, `lib.rs:2415`), which needs `PATH` to find its own coreutils; and dropping `SystemRoot`/`SYSTEMROOT` breaks Winsock initialization, so DNS and every socket fail with errors resembling nothing about a missing variable. `MARLOWE_BASH` is read on the parent side to locate bash at all.
  - fix: Name the floor concretely for this platform — `SystemRoot`, `SYSTEMROOT`, `windir`, `PATH`, `TEMP`, `TMP`, `USERPROFILE`, `HOME`, `COMSPEC`, `PATHEXT`, `NUMBER_OF_PROCESSORS` — with a prefix denylist on top (`*_API_KEY`, `*_TOKEN`, `OPENROUTER_*`, `ANTHROPIC_*`, `AWS_*`, `MARLOWE_CUDA_LIB_DIR`). Declare it per box at provisioning and echo the withheld names in the refusal, `ScopeError::Unopenable` style. The measurement is one command that prints a number: `bash("env | grep -ci 'key\\|token'")` inside a box must print 0.

## Strengthened

# Provisioning and lifecycle for team boxes

## 1. The finding that prices everything, verified

There is one workspace root in the process. `DaemonConfig::workspace` reaches four *functional* consumers, all in `crates/marlowe-daemon/src/daemon.rs`:

| Site | What it feeds | Effect if not re-rooted |
|---|---|---|
| `:2090` | `Engine::new` → `Request::workspace` (`engine.rs:1835`) | the adjudicator opens every handle in the user's tree |
| `:2498` | `build_tool_host` → `FileSystemTools::new(scope, workspace)` | `glob`/`grep` walk the user's tree; `bash` starts there |
| `:2628` | the `workspace_rule` governance string, **stable tier** | the model is told the wrong absolute path, permanently |
| `:2662` | `workspace_map` → `SourceKind::ProjectFiles` block | the model is handed a listing of the user's files |

Plus `:1057`, a boot-time `build_tool_host` for `verify_every_exposed_tool_is_runnable`, and display rows at `:1200`, `:1300`, `:1385`.

`Engine::spawn` forwards `tools: ports.tools` verbatim (`engine.rs:3174`), so **every run in the tree — Marlowe, top-agent, master, worker — shares one tool host rooted at the user's real directory.** That is the whole gap, and it is cheap to close because the box is a *value*: `FileSystemTools::new(scope, workspace.to_path_buf())` already takes it as a parameter.

**Two of those four are not what a naive count finds.** `:2628` writes into the **stable tier** via `assert_governance`, documented at `:2623` as asserted once per conversation because re-asserting would grow the tier every turn — structurally un-updatable mid-session. `:2662` calls `workspace_map`, whose only caller it is, inside `Daemon::turn`, on the *secretary's* `SessionMemory`. `Engine::spawn` builds `child_state = SessionState::new(...)` at `engine.rs:2393`, `3067`, `3474` and pushes only the brief and governance: **a spawned team receives no workspace map at all, today.**

## 2. What confinement each tool actually gets

| Tool | Root source today | Strength in a box |
|---|---|---|
| `read`/`write`/`edit` | `Adjudication.handles` (`adjudicate.rs:179`), opened against `Request::workspace` | **Hard.** `scope::request::validate` refuses `..`, rooted forms, ADS, device names before any syscall |
| `glob`/`grep` | base from `handle_for(a,"path")`; `self.workspace` for relativization and re-open | **Hard**, once the two roots agree |
| `bash` | `handle_for(a,"cwd")`, else `self.workspace` (`lib.rs:1559`) | **A starting directory only.** Windows: `cmd.arg(command).current_dir(dir)` (`lib.rs:2531`); the shell then does `cd ..`, absolute paths, `curl` |
| `web` | harness-side, egress-adjudicated | unchanged; the box does not touch it |

The Unix arm is genuinely stronger — `pre_exec` + `fchdir` on the verified descriptor (`lib.rs:2551-2562`), no string crossing — and the source's own comment calls the Windows gap unclosable without a new dependency. **Say so in the ADR. A box claiming to confine `bash` on Windows is instance #15 at the architecture level.**

## 3. The plumbing, and it is smaller than it looks

Do **not** change `ToolHost::execute_batch`. `ToolHost` (`driver.rs:570`) and `BatchItem` (`driver.rs:563`) are in the §13-guarded `driver.rs`, PROTECTED line 99. `Ports` is in `engine.rs:241` and is **not** guarded.

Five of `FileSystemTools.workspace`'s six readers retire without any signature change:

- `lib.rs:1100`, `1114`, `1371`, `1392` — `strip_prefix(&self.workspace)` purely for relativization. The adjudicated `ScopedPath` already carries `relative()` (used by `read` at `lib.rs:1040`). Relativize against the handle.
- `lib.rs:1559` — `bash`'s cwd *fallback*. Make `cwd` required for boxed runs; a boxed shell with no declared cwd is a refusal, not a default. (#17: this fallback is a permissive default pointing at the user's home.)

One genuinely needs a root: `lib.rs:1394`, `self.scope.open(declared, &self.workspace, &relative, Access::Read)` in `grep`'s per-file re-open. Give `FileSystemTools` its root through a `roots: &dyn RunRoot` port added to `Ports` in `engine.rs`, trait defined in a new unguarded `marlowe-loop/src/workspace.rs`.

**The disagreement to design against, because it is silent.** If the adjudicator's root and the executor's root differ, `strip_prefix` at `lib.rs:1392` fails, the loop `continue`s, and **`grep` returns zero hits with no error.** Absence and containment read identically. The port exists so there is one value, not two.

## 4. The box on the profile, as a portable id

A private `Workspace` field on `CapabilityProfile`, set only through `CapabilityProfile::new` (`profile.rs:276`) — the same argument CLAUDE.md gives for the granted egress set, and both operands (`level`, `workspace`) are already profile fields. Never on `SpawnRequest`: a root is the most Target-shaped value in the system, and `driver.rs` is guarded.

Two corrections to the obvious version:

- **Exhaustive `match level`, one arm per variant.** `profile.rs:311-318` refuses wildcard arms by name — "a sixth `AgentLevel` variant is a compile error here rather than a level that quietly inherits whichever neighbour `_` happened to cover". A `!= Secretary` is a wildcard wearing a different hat.
- **Serialize a box id, not a `PathBuf`.** `Checkpoint` (`durable.rs:87`) is signed and must stay portable; an absolute path binds it to one machine and writes the user's home directory into the record. Store `boxes/<id>` relative to `profile_root`, resolve at restore. `CHECKPOINT_VERSION` 1 → 2, because a missing field defaulting to "the daemon's workspace" is exactly the permissive reset `durable.rs:75-79` says the version exists to stop.

**Be honest: `profile.rs` is PROTECTED. This is a §13 edit and it arrives with a `DECISIONS.md` entry.** The hook returns `ask`, not `deny`; a human who reads the reason and approves has made the decision the boundary exists to require.

## 5. Three modes; the flat layout as a load-time invariant

`Scratch` (empty dir), `Graft` (sparse `git worktree`, branch `team/<run>`), `Mirror` (hardlinks/junctions, read-only reference material). No default — a team spawned without an intake answer is refused, not given an empty box.

Disk, measured correctly (`git ls-files -z | xargs -0 du -cb | tail -1` reports only the last of **3** xargs batches on this checkout):

```
full tracked            247,256,212 bytes  (1,635 files)
crates+docs+tools+eval   11,510,844 bytes  (623 files)   <- a Graft
.git                            7.2 GB                    <- shared, never copied
```

A copy is 247 MB per team and it **diverges** — the team researches a snapshot while the user edits the original. A worktree is 11.5 MB and is one object with two checkouts, so `git log`/`git diff` against `team/<run>` is the delivery mechanism, already installed.

**Flat siblings, `profile_root/boxes/<id>/`, enforced not conventioned.** Nesting would put a child's box inside the parent's declared `WORKSPACE = "./**"` (`builtin.rs:61`), so the parent reads the child's raw prose at `AgentObserved` with `validate` never called and `Engine::spawn`'s A8 arm bypassed — and no exclusion is expressible, because `PathGlob` is `#[serde(transparent)] pub struct PathGlob(String)` (`manifest.rs:185`) with no negation and `scope/glob.rs` is in `PROTECTED_DIRS`. Make it a constructor invariant: a box path has exactly one component after `boxes/`, refused as `BoxError::NestedBox`. A provisioner "tidied up" into nesting then fails to construct instead of silently reopening the upward channel. Second, independent argument for the same layout: `OrphanPolicy::Detach` sets `parent: None` (`durable.rs:375`) and the child resumes — under nesting its box would live inside a dead parent's directory.

Windows path length is why this also stays shallow: `scope/walk.rs` opens component-by-component, so MAX_PATH lands on the deepest file in the deepest box first.

## 6. Getting work out: the child pushes, the parent never pulls

**The user reads any box directly.** §2.3's "an artifact is a path the *user* opens", with the emphasis load-bearing: a human at an editor has no instruction-following surface; the residual is a display attack, §3.6's territory.

**A parent reads nothing of a child's box.** What crosses is the `OutputContract`-validated result plus an artifact reference. To move bytes, the **child** calls `deliver(<relative-path>)` and the harness copies into the parent's box.

A push, not the obvious pull, for a mechanical reason: `Adjudication.handles` is keyed by parameter name and every handle opens against one `Request::workspace: &'a Path` (`adjudicate.rs:169`). A parent-side `promote(<child-run>, <path>)` needs two handles in two roots — a change to `adjudicate.rs` and `scope/`, both PROTECTED. A child-side `deliver` is one handle in one root and needs neither. It also runs in the same direction as `Engine::spawn`'s return hop, where ADR-063's A8 arm already sits (`engine.rs:~2911`).

**Open, and the human's:** whether delivered bytes land at `AgentObserved` (today's `read`, `lib.rs:1041`) or quarantined. That is ADR-062 §4's origin question, with `Channel::Agent` existing and having zero production construction sites. Ship at `AgentObserved` and a parent absorbs child prose above `blocks_composed_targets`' threshold (`adjudicate.rs:50-52`) — SECURITY-AUDIT finding #1 with a front door, made worse by the 2026-08-31 reversal that gave masters working tools.

## 7. Lifecycle

`settle_orphan` (`durable.rs:361`) is pure, returns an amended `Checkpoint`, and touches no filesystem — box treatment lives in its **callers**, and `durable.rs:358` says there are two (the loop via `Recorder`, the daemon via `CheckpointStore`), so factor the seal into one function or it is a decision with two implementations.

- `Terminate` → run `Cancelled`, box sealed: a deny-write ACE, **advisory against the agent, not against the daemon**.
- `Detach` → box survives writable, root of its own tree.
- `Adopt` → box does not move; only the run graph does.

Sealing rather than deleting is forced by M3-DESIGN §3.5: TERMINATE must state what it cannot undo, and a box that vanished with the run makes that dialog unwritable ("and forty files you have not read"). Destruction is a separate, user-initiated act.

**Two gaps stated rather than implied.** `run_bounded`'s own comment (`lib.rs:2570-2578`) records that `child.kill()` kills the shell, not what the shell started — no process group, no Job Object — so a terminated run can leave a grandchild writing into the box just sealed. And a deny-write ACE surfaces to the model as an opaque `ERROR_ACCESS_DENIED` from `std::fs`, not a `ScopeError` with a remedy.

Retention lists, never deletes: `marlowe --boxes --stale` prints count, total bytes, and a column for boxes with a live descendant process. A timer that deletes is a timer that eventually eats a deliverable.

## 8. The environment

`grep -n "env_clear\|\.env(\|env_remove" crates/marlowe-exec/src/lib.rs` returns **nothing**. Every credential the daemon holds is one `echo $VAR` away inside every box, and `bash` already has a socket (ADR-049 §4, `curl` returns 200).

Allowlist at `spawn_shell` — one site, `lib.rs:2523`/`:2538`. **The Windows floor is not obvious and getting it wrong looks like a network bug:** the interpreter is msys2 Git Bash (`shell_command()`, `lib.rs:2415-2426`), which needs `PATH` for its own coreutils, and dropping `SystemRoot`/`SYSTEMROOT` breaks Winsock initialization so DNS fails with an error resembling nothing. Floor: `SystemRoot`, `SYSTEMROOT`, `windir`, `PATH`, `TEMP`, `TMP`, `USERPROFILE`, `HOME`, `COMSPEC`, `PATHEXT`, `NUMBER_OF_PROCESSORS`. Prefix denylist on top: `*_API_KEY`, `*_TOKEN`, `OPENROUTER_*`, `ANTHROPIC_*`, `AWS_*`, `MARLOWE_CUDA_LIB_DIR`. Declared per box, and the refusal names what was withheld.

## 9. AppContainer: deferred, and now for the verified reasons

Not the loopback point alone. Three blockers, checked:

1. **`std::process::Command` cannot create an AppContainer process.** It needs `CreateProcessAsUserW` + `UpdateProcThreadAttribute` with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`, and `CreateAppContainerProfile`. `grep -rn "windows-sys\|winapi" --include=Cargo.toml` returns **nothing** in this workspace, and `lib.rs:2576` already records declining that dependency for Job Objects.
2. **The interpreter is Git Bash.** ACLing the box is the easy half; the package SID also needs read+execute across the whole Git for Windows tree, and msys2's fork emulation under a restricted token is a bet nobody here has measured.
3. **Loopback, stated correctly.** AppContainer loopback is blocked *irrespective of capabilities* — `internetClient` governs outbound internet, `privateNetworkClientServer` the local subnet; neither ever grants loopback. `CheckNetIsolation LoopbackExempt` is a documented development aid, not a shipping configuration. So the naive token breaks Ollama and breaks dev-server-plus-curl, and the exemption is precisely where an attacker aims once anything on loopback can proxy outward.

**WFP does not rescue it.** User-mode `FwpmFilterAdd` with `FWPM_CONDITION_ALE_APP_ID` keys on the image path, and a boxed team's shell and Marlowe's own shell are the same `bash.exe`. The only condition that separates them is `FWPM_CONDITION_ALE_PACKAGE_ID` — an AppContainer SID — so the routes converge, and WFP additionally requires admin.

Note also that ADR-002's carve-out cited as precedent ("the quarantined reader keeps a sandbox backend", DECISIONS.md:584-590) is itself **unbuilt** — no sandbox backend exists in `crates/`. The precedent is a decision, not a mechanism to reuse.

**Do not add `sandboxed: bool` in anticipation.** Instance #16, and this codebase already shipped that exact mistake: `web`'s `inline_threshold_bytes: 0`, with a green test asserting the declaration.

## 10. Numbers, each a command

```
cargo test -p marlowe-loop --test box_containment -- --nocapture
#   a_boxed_run_cannot_read_outside_its_box   -> Undeclared   (the property)
#   marlowes_own_run_can_read_the_same_path   -> Ok           (THE CONTROL)
```
Without the control both rows refuse when the file merely does not exist — the confusion `ScopeError::Unopenable`'s message was rewritten for on 2026-08-25 — and the suite is measuring absence, not containment.

```
cargo test -p marlowe-loop --test box_containment -- a_parent_cannot_read_a_childs_box
# MUTATION: provisioner -> box(parent)/<child>. It MUST go green. If it stays red, it tests something else.
```

```
cargo test -p marlowe-loop --test box_containment -- a_boxed_grep_finds_its_own_files
# The silent-empty control. Point the adjudicator's root and the executor's root at different
# boxes: grep returns 0 hits and NO error. This is what makes that state fail loudly.
```

```
cargo test -p marlowe-daemon --test composition_root
# extend a_batch_reaches_the_innermost_host_through_both_wrappers to assert the ROOT arrived,
# not merely that a batch did.
```

Knowledge — **and it is not a number until the child gets a map at all.** The 200-vs-73 `workspace_map` reading is taken on `Daemon::turn`'s secretary block; `child_state` is a fresh `SessionState`. Seed `workspace_map(box_root)` at the three `child_state.push` sites, then:
```
cargo test -p marlowe-loop --test box_containment -- a_teams_map_is_never_truncated
# entries < MAP_MAX_ENTRIES(200) and the "listing stopped at" notice absent
```
Polarity stated honestly: this one goes quiet rather than red if provisioning falls back to `config.workspace`; the containment test is the evidence, this is the improvement. `WALK_SKIP` is `[".git","target","node_modules",".venv","__pycache__","dist"]` and `workspace_map` additionally drops every dotfile but `.claude`, so a `Graft` containing `.github/` is readable and invisible.

Disk, with the corrected command:
```
git ls-files -z | xargs -0 du -b | awk '{s+=$1} END{print s}'                    # 247,256,212
git ls-files -z -- crates docs tools eval | xargs -0 du -b | awk '{s+=$1} END{print s}'  # 11,510,844
du -sh .git                                                                       # 7.2G, not copied
```

Environment:
```
bash("env | grep -ci 'key\|token'")   # must print 0 inside a box
```

## 11. Residual risk

- **A boxed team still reaches the network.** No `EgressPolicy` is consulted on the `bash` path at all — `adjudicate` iterates `Url`-typed parameters and `bash` declares none. Everything in the box can leave over a socket, and the box is where the research lives. Not closed here; no milestone owns it.
- **A `Graft` shares `.git`.** Sparse checkout bounds what a team *sees*, not what `git` can *do* to the shared object store. Until that has an answer that is not a filter, anything holding `bash` gets `Scratch` or `Mirror`.
- **The box does not make anything safe to read.** ADR-041 already concedes A-influences-B inside a reader. A team fed a poisoned source writes an honest file about a dishonest premise, correct in every checkable way.
- **`bash` on Windows leaves the box by `cd ..`.** Filesystem confinement is hard for `read`/`write`/`edit`/`glob`/`grep` and is a starting directory for the shell. That asymmetry is the product until the token question is answered, and it should be written into the ADR rather than discovered.

## 12. Cheapest first step

Run the corrected greps and expect these exact numbers before writing a line: `self.workspace` in `engine.rs` → **1** (1835); in `marlowe-exec/src/lib.rs` → **6** (1100, 1114, 1371, 1392, 1394, 1559); `config.workspace` in `marlowe-daemon/src/` → **8**, of which four are functional (2090, 2498, 2628, 2662), one is a boot check (1057), three are display; `tools: ports.tools` in `engine.rs` → **3** (2457, 3174, 3505). Different numbers mean a different codebase — stop and re-derive.

Then confirm the two facts that reshape the design: `grep -rn "pub trait ToolHost\|pub struct BatchItem" crates/` → both in the §13-guarded `driver.rs`, and `grep -n "workspace_map" crates/marlowe-daemon/src/daemon.rs` → exactly one caller, inside `Daemon::turn`, so **no child ever sees a map**.

Then write the failing test and watch it fail for the right reason: `a_boxed_run_cannot_read_outside_its_box` passes wrongly today, because there are no boxes. Demonstrating in one command that every agent in the tree is currently rooted in the user's directory is worth more to the human than the rest of this page.

---

