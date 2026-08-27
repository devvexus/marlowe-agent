# ADR-060 `llamacpp` provider — adversarial verification

Verifier: independent of the implementer and of the probe. 2026-08-27.
Binary under test: `target/release/marlowe.exe`, built 13:25 from this working tree.
Machine: RTX 4080 SUPER (16,376 MiB), `qwen3.5:9b`, Windows 11.

> **The tree moved under this verification.** `crates/marlowe-provider/src/ollama_store.rs` gained a
> `crate::hybrid` that *spawns* `llama-server` while I was measuring. Everything below tests the
> "v1 connects, the user launches" version I built at 13:25. **Finding 1 gets worse, not better,
> under a spawner** — see it.

---

## VERDICT: **DO NOT SHIP AS-IS.**

Not because the feature does not work — **it works, and the headline claim reproduces at product
level**. Because the one command the product hands the user in order to make it work produces a
server running on **CPU at 10.6 tok/s**, and every check in the feature reports `Ready` when it does.

Fix Finding 1 and the recommendation flips to ship.

---

## The reading that matters: TTFT **through the product**

Not `probe.py`. Not a unit test. The **running daemon**, both arms, back to back, on a machine with
0 `cargo`, 0 `rustc`, and exactly one GPU-verified `llama-server`.

| arm | TTFT median (n=7 warm) | range | spread | generation | turn total |
|---|---|---|---|---|---|
| **ollama** — 11434, Ollama's own service | **382.4 ms** | 335.1–398.3 | 16% | 415.1 ch/s | 716 ms |
| **llamacpp** — GPU-verified server, private port | **71.0 ms** | 62.7–100.6 | 46% | 423.4 ch/s | 419 ms |

**5.4x on TTFT. Throughput equal (+2%, inside the spread).** ADR-060 predicted 5.3x from an HTTP
instrument; the product delivers 5.4x. A proxy that held up when taken at the real level — the rarer
direction, and worth recording as such.

A replicate of the ollama arm taken 20 minutes earlier, different profile, different daemon
process: **426.5 ms** (n=7, 405–457). Two independent readings, 382 and 427 ms.

### RECONCILIATION REQUIRED: a second product measurement says 3.1x, not 5.4x

Commit `ab9b3d7` (14:01:54) reports **151.5 ms llamacpp / 472.5 ms ollama = 3.1x**, taken through
the daemon's own `--dev` stderr, and instructs readers not to quote my 71/382 pair. **Both numbers
should not circulate. Here is what differs, stated without deciding it in my own favour.**

**Where that measurement is stronger than mine:** it verified the prompt from *both daemons'
outbound dumps on every measured call* — 17,381 chars of system and 12 tools, identical on both arms
— so its ratio is demonstrably not a prompt-size artefact. **I did not measure my prompt size**, and
that is the single most likely explanation for the gap. If my daemons sent a shorter prefix, my
absolute numbers are low and its are the ones to quote.

**Where mine is stronger:** n=**7** warm reps per arm against its 3-minus-1 = **2**; and I checked
machine load immediately before and after each cell (0 `cargo`, 0 `rustc` both times).

**One thing that needs checking before its number is canonised:** its measurement window overlaps
mine. I was running `cargo check --workspace --jobs 4` on a 45-second poll from **13:58 to 14:02**,
waiting for the tree to compile — and that commit lands at **14:01:54**. That is CLAUDE.md hazard
form 6, and I caused it. It would inflate both of its arms.

**Instrument placement argues against a simple explanation.** Its clock is *inside* the daemon
(`--dev` stderr); mine is a client across the socket and therefore contains strictly more — daemon
event plumbing, framing, loopback. **Mine should read HIGHER than its, and reads lower on both
arms.** So the difference is in conditions, not in where the clock sits, and it is not yet explained.

**Recommendation: re-measure once, on a quiet machine, with the prompt size dumped, n>=7 per arm,
and one instrument.** Until then quote neither as canonical. What both agree on, and what the
decision actually rests on, is the **direction and rough size**: llama.cpp is several times faster
to first token through the product, and its generation throughput is not worse.

### What the instrument is, and the one thing it is not

`runs/llamacpp/product_ttft.py` opens the daemon's own socket, writes the profile's `daemon.token`
then the ask frame — exactly the framing `Client::send_streaming_approving` uses
(`client.rs:135-140`) — and stops the clock on the first `reasoning`/`text` delta. Auth, context
assembly, injected memory, the driver, the request body, the SSE fold and the daemon's event
plumbing are all inside the measurement.

**The one unshipped part is the reader loop, and it cannot be avoided:** `marlowe --ask` collects
every event into a `Vec` and prints nothing until the turn ends (`agent.rs:294-303`). **The shipped
CLI physically cannot report a first-token time.** That is itself worth knowing.

Controls: fresh session per rep (a shared session accumulates history and drifted 962 to 3,985 ms —
a confound, removed, not a result); byte-identical prompt so the prefix is warm; rep 1 reported and
excluded; machine load checked before and after each cell.

---

## FINDING 1 — SHIP BLOCKER. The product's own launch command yields a CPU server.

`ResolvedModel::launch_plan` emits **one** environment variable, `GGML_BACKEND_PATH`. ADR-060's
probe recorded **two**. Same binary, same blob, same argv, back to back, nothing else running:

| launch | VRAM delta | `no usable GPU` in log | predicted_per_second |
|---|---|---|---|
| **A** — `GGML_BACKEND_PATH` only (**what the product prints, and what `hybrid` will spawn**) | took none | 1 | **10.6 tok/s** |
| **B** — `GGML_BACKEND_PATH` + `PATH` including the lib and `cuda_v12` dirs | **+5,523 MiB** | 0 | **107.4 tok/s** |

**10.1x.** A's log line, verbatim, with an **empty** reason after the colon:

```
E load_backend: failed to load C:\...\ollama\cuda_v12\ggml-cuda.dll:
```

`GGML_BACKEND_PATH` tells ggml *which file* to load. It does not tell the **Windows loader** where
that file's own imports — `cudart`, `cublas`, in the same Ollama lib dirs — are to be found. The
directory must also be on the search path.

The comment above `launch_command` is emphatic and correct about the half it names — *"must name
the DLL, not its directory"* — and silent about the half that decides the outcome.

Evidence: `runs/llamacpp/product/DLL-CONTROL.md`, `dll-A-envonly.log`, `dll-B-withpath.log`.

---

## FINDING 2 — the checks that would read the same if the feature were broken

The question asked of every check the implementer added. These are the ones that fail it.

### 2a. `Availability::Ready` cannot see GPU offload. Measured, not argued.

On the CPU server: `/health` 200, `/props` complete, `chat_template_caps.supports_tools` true,
`Availability::probe` returns **`Ready`**, the switch is **accepted**, `--status` prints *"serving …
template reports tool support"* — and **TTFT measured 218 ms against Ollama's 426**, i.e. the
headline metric read as a **2x win** while the turn was **5x worse**.

Every hit for `GGML_BACKEND_PATH`, `ngl` and `offload` in `llamacpp.rs` and `ollama_store.rs` is
inside the **launch-hint string**. `probe` reads `/health`, `/props` and `/v1/models`; none
distinguishes GPU from CPU. **Nothing in the driver reads offload state.**

> **BEING FIXED AS THIS WAS WRITTEN.** At 13:52 `Availability::probe` gained a fourth parameter,
> `OffloadPolicy` (`llamacpp.rs:542`); `daemon.rs` had not yet caught up, which is what broke suite
> attempt 4. Everything measured above is the **13:25 binary**, where the gap was real and open.
> Two conditions for the new parameter to be a guard rather than a declaration:
>
> 1. **It must not be satisfied by liveness.** `/health`, `/props` and `/v1/models` read identically
>    at 10.6 and 107.4 tok/s — measured, not supposed. The reading has to be a token rate, a VRAM
>    delta, or the launch log.
> 2. **Finding 1 must be fixed first, or the guard lands on a broken launch.** If `hybrid` spawns
>    from `LaunchPlan` as it stands, `OffloadPolicy` will correctly report that the server Marlowe
>    itself just started is on CPU — a working guard whose only job is to condemn its own launcher.

**TTFT is the wrong guard for this.** First token is dominated by prompt eval on a cached prefix,
which CPU does acceptably. Generation is where CPU collapses, and TTFT cannot see generation. Any
guard must read tokens/second, the launch log, or a VRAM delta.

### 2b. The launch-command test asserts the declaration, not the effect.

`ollama_store_resolution.rs:237` — `assert!(cmd.contains("GGML_BACKEND_PATH"))`. **Green on a command
that produces a 10.6 tok/s CPU server.** Identical in form to the `inline_threshold_bytes == 0` case
CLAUDE.md records: a property asserted where it is *declared* rather than where it is *enforced*.
The whole class is closed by one live check — launch it, read `predicted_per_second`.

### 2c. `--status` masks the launch command exactly when it is needed. Observed live.

`daemon.rs:1050` is `stale_against_source().or_else(|| availability.remedy())`. With **nothing
listening**, `--status` printed only *"this daemon's binary is 20 min older than the source"*. The
launch command — the entire product of `ollama_store`, and the thing that makes "v1 does not
supervise" survivable — **never appeared.** In a working tree the staleness arm is almost always
live, so the remedy is suppressed for precisely the audience that needs it.

### 2d. `switching_to_llamacpp_with_nothing_listening_is_refused_with_the_launch_command`

Its assertion is a five-way disjunction and **never asserts a launch command is present**. A refusal
carrying no remedy at all passes as long as the string `llama-server` appears. The name claims more
than the body checks.

### 2e. `LLAMACPP_DEFAULT_PORT` collides with *other llama-servers*, and Windows permits it.

Two `llama-server.exe` were simultaneously `LISTENING` on `127.0.0.1:11437` (PIDs 126896 and 132712,
five minutes apart, byte-identical command lines — both agents used ADR-060's). Windows did not
refuse the second bind. **`Availability::probe` cannot tell which server it reached**, and neither
can `--status`. The port was moved off 11435 because it collided with the daemon; it now collides
with itself. This voided a full measurement cell before I noticed.

### Checks that ARE real — asked the same question, and they answer it

- **`refuses_tools()`** — non-vacuous, verified against a live `--no-jinja` server: `/props` reports
  `supports_tools: false` there, and the switch is refused. It is read at `daemon.rs:1326`, not just
  declared.
- **`the_replayed_call_carries_a_type_here_and_does_not_on_the_ollama_path`** and its `arguments`
  sibling are **differential** — they assert the llamacpp body against the ollama body, so a builder
  that stamped `type` on everything fails them. That is the right shape.
- **`capability_for` returns `unmeasured` always**, and `fit_for_default()` is false for it, so
  llamacpp can never be promoted to default by that mechanism.
- **`Tier1Runtime` is a required field**, so every call site had to state its runtime rather than
  inherit "Ollama" by omission. That is what made Finding 3 provable.

---

## FINDING 3 — the VRAM hazard is FIXED, verified in the exact hazard state

Reproduced the state ADR-060 §3 names, then read the product:

```
llama-server holding the card          GPU free: 2,124 MiB
ollama ps                              EMPTY
ollama list                            qwen3.5:9b   6.6 GB
--status                               rerank  CUDAExecutionProvider · batched · asked auto
```

The old code asked `ollama ps` (absent, so "not resident") and `ollama list` (present, 6.6 GB) and
would have reserved **6.6 GB against 2.1 GB free**, resolving the reranker to CPU with a reason
false in every clause. It now reserves **0** and stays on **CUDA**.

The fix also closes a **shipped** defect the ADR did not name: `Daemon::open` passed
`ForTier1(&config.model)` unconditionally, including on the OpenRouter path, where nothing on this
machine runs the model at all.

---

## FINDING 4 — the tool round trip works end to end. This is the check nothing else had run.

Through the running daemon, on the GPU server, one turn:

```
(1, 'read', 'CLAUDE.md', 'running', '0 ms')
(1, 'read', 'CLAUDE.md', 'ok', '411 lines · 32903 B')
DEGRADED: []   ERRORS: []
REPLY: 'The exact text of the first line is:  # Marlowe'
```

This clears the probe's two hardest blockers **at the seam**, which no unit test can reach:

- **`arguments` arrives as a fragmented JSON string** — reassembled by `index`, parsed, correct
  target. Had it failed, the call would have arrived well-formed with *no arguments* and been
  refused by the permission layer for "no declared target": a model that never erred, reported as
  one that did.
- **`"type": "function"` on the replayed assistant call** — iteration 2 returned **no HTTP 500**.
  Without it every tool-using turn dies on its second model call.

---

## Ollama is still the default, and nothing switched on its own

- `PROVIDERS = ["ollama", "openrouter", "llamacpp"]` — one definition; the picker and
  `set_provider` validate against the same list.
- `resolve_provider`: `None | Some("ollama") => Ollama`. Reaching llamacpp needs `--provider
  llamacpp` typed.
- `zero_config_is_unchanged.rs` is **unmodified** by this work.
- Live: a daemon started with no `--provider` reports `provider ollama`.
- Minor: `MARLOWE_LLAMA_SERVER` is a new env var in `ollama_store.rs`. It overrides the *binary
  path* only and cannot move the provider, so the "no environment variable reaches this file" claim
  in `llamacpp.rs` is true of `llamacpp.rs` and not of the pair.

## Standing rules

`HashMap`/`HashSet` under `crates/`: none in the new code — the fold uses a `BTreeMap` **because**
its order decides batch order, and says so. No `Instant::now`/`SystemTime::now`. `eval/` untouched.
`no_tls_in_the_default_path.rs` green. The `sse.rs` relocation is a faithful move:
`openai_messages` reproduces OpenRouter's previous body byte for byte.

**One un-measured change rode along on a shipped path:** OpenRouter's `tool_schema` now shares
`openai_tool_schema`, which honours each parameter's own `description` where OpenRouter's copy sent
`"text"`. A real improvement, and a **prompt change to a hosted provider**, unmeasured, folded into
an opt-in feature.

## Not established

- `ContextTooSmall` never fired live.
- `stream_options.include_usage` on the **streamed** path (the non-streamed response does carry
  `usage`).
- `chat_template_kwargs.enable_thinking` — sent, never shown to be read by this GGUF's template.
- `-np > 1`; a mid-turn `llama-server` crash; `set_model` mid-turn.

## Two tooling traps this run hit, both worth recording

1. **The background-task harness reported "exit code 0" while `cargo` exited 101 — twice.** The
   wrapper's exit status was the subshell's, not cargo's. Tallying the file is what caught it.
2. **A compile error in ONE test target aborts the whole workspace build, and `--no-fail-fast` does
   not cover it.** CLAUDE.md's rule is written for a *test failure*, where each binary cargo reached
   still prints `test result: ok` and the file looks complete — caught by counting binaries against
   an expected total. A **build** failure is different: the file contains **zero** `test result`
   lines, and "zero" reads like "nothing ran yet" rather than "the run is over and it failed". Two
   failure modes, two detectors.

---

## 10 · The control on §1, because a latency table without one is not evidence

The two arms were not merely "the same question". Read out of each daemon's own outbound dump:

* **Every measured call on both arms carried a 17,381-character system message.** Byte count
  identical, arm to arm, call to call.
* **Every measured call on both arms offered the same 12 tools** — `read, write, edit, glob, grep,
  bash, web, recall, use, ask, remember, run`. The tool schema is ~43% of the prefix by ADR-060's
  own token count, so an arm that omitted it would have won by default.
* **The windows agree.** The Ollama arm sends `num_ctx=32768 num_predict=8192`; the llamacpp arm
  sends neither, by design, and its server was launched `-c 32768`. `Availability::ContextTooSmall`
  is what enforces that, and it did not fire.

So the 151.5 ms against 472.5 ms is not a prompt-size difference.

**The one outlier explains itself and supports the ADR.** The Ollama arm's fifth model call read
**1,929.3 ms** — four times its own warm figure — and it is the only call on either arm whose
system message was a different size: **17,529 characters**, 148 bytes longer, because injected
memory changed. A prefix that changes at the *front* re-evaluates everything behind it. That is
ADR-060 §1's cold-prefix cell arriving unbidden in a product run, and it is the strongest argument
in this file for the prefix-stability work being independent of, and additive to, the runtime
choice.

---

## 11 · Method — how to reproduce the 151 / 472 pair without having been here

The instrument is `scratchpad/product_ttft_daemon.py`. It is a *driver*, not a client: it speaks to
no model and opens no socket to any server. Everything it reads is written by the daemon.

1. **Build.** `cargo build --release --jobs 4` with `MARLOWE_CUDA_LIB_DIR` set. Record the binary's
   mtime; every reading below must come from that binary and no other. (`--status` will tell you if
   the binary is older than the source, and on a shared checkout it usually will be — see §5.1.)
2. **One llama-server, and prove it is on the GPU before timing anything.** Launch it, then check
   two independent readings: the launch log must not contain `no usable GPU found`, **and**
   `nvidia-smi` free memory must drop by the weights (~6.3 GB for `qwen3.5:9b` Q4_K_M at `-c 32768`
   on this machine). Neither alone is sufficient — see §12.
3. **A fresh profile root per arm**, and a distinct daemon port per arm. A shared profile carries a
   session, and a carried session means arm B starts with arm A's history in the prefix.
4. **Start the daemon with `--dev`** and pipe its **stderr** through a line timestamper. This is the
   whole trick: `--dev` prints `[dev] ===== END REQUEST =====` immediately before the request goes
   out and `[dev] frame N …` on each streamed delta, from two sinks in `daemon.rs` that **both
   providers share**. TTFT is the difference between the first frame carrying bytes and that marker.
   Nothing about it is provider-specific, which is what makes the two arms comparable at all.
5. **Drive it with the real client** — `marlowe.exe --ask "<q>" --daemon-port P --profile-root R
   --workspace W` — four times with the same question, and **discard rep 1**. Rep 1 pays the cold
   prefix, and on Ollama it also pays the model load: 10,485 ms against 472 ms warm.
6. **Read the control before reading the result.** From each arm's dump, confirm the system message
   is the same byte count and the tool set is the same on every measured call (§10). If they are
   not, the arms are not comparable and the table is fiction.
7. **Check the machine.** No `cargo` running during any cell, from the process list, before each
   arm — not from memory of having said so.

**Two confounds this design removes, and one it does not.** Removed: a shared profile (fresh root
per arm) and a shared port (distinct ports). Not removed: **conversation history accumulates within
an arm**, because `--ask` against one daemon is one session. Over four reps that is small and it is
symmetric between arms — the measured warm figures do not trend within either arm (151.5 / 159.2 /
131.2 and 472.5 / 478.6 / 465.9). It would **not** stay small over dozens of turns, so a longer run
needs a fresh daemon per rep or it is measuring history growth.

**The one drift that did appear is itself the finding.** The Ollama arm's fifth model call read
1,929.3 ms — four times its own warm figure — and it is the only call on either arm whose system
message changed size, 17,381 → 17,529 characters, because injected memory changed. **A 148-byte
change at the front of the prefix cost ~1.45 seconds.** That is ADR-060 §1's cold-prefix cell
occurring spontaneously in an ordinary product run, and it says the prefix-stability work is
additive to the runtime choice rather than an alternative to it: llama.cpp makes the floor lower,
and prefix churn is what lifts you off the floor.

---

## 12 · Two harness properties this session discovered the hard way

**`TaskStop` kills the job wrapper and the `cargo` child survives it.** I stopped a background job
that was running a build-then-test chain; the wrapper died, `cargo` did not, and it went on to
start a second `cargo test --workspace` while another was already running. That is the pairing
CLAUDE.md names as the likeliest 0x139 trigger on this box, and it is also what corrupted
`runs/llamacpp/suite.txt` at 13:32 — two processes with independent file offsets writing one
`>`-redirected path, producing markers out of chronological order and one truncated `test result`
line. **Stopping a task is not stopping the build.** Verify from the process list, and give any
long-running redirect its own filename rather than a shared one.

**`no usable GPU found` is corroboration, not a contract.** I used its absence as a GPU check and
its presence as a CPU check, and both readings happened to be right — but across the launches in
this session the string appeared in one failing case and not in another. A log line is a property
of a build's verbosity. The reading that decides is `timings.predicted_per_second` (17 against 178
on this machine, with nothing between), with the `nvidia-smi` delta as an independent second
positive. Use the log line only to write a better *cause* string.

**A compile error in a shared checkout is a snapshot with a timestamp, and mine have both.** For the
record: `ollama_store.rs:334`'s unterminated character literal was real in the tree my `cargo check`
read at **13:48:39**; by **14:0x** the same line read `a.contains('\')` and I recorded that in §9.
The `marlowe-daemon` E0061 failures I saw at **13:57** are `Availability::probe` gaining its
required `OffloadPolicy` argument ahead of the daemon call sites — which is the §3 fix landing
correctly, a `Ready` that cannot be constructed without an offload reading, and not a defect. None
of these is attributed to this feature and none was fixed by me.

---

## 13 · A correction to this project's own standing test advice

CLAUDE.md says, twice and emphatically, that a run whose purpose is a **count** needs
`--no-fail-fast`, because `cargo test` stops at the first failing binary and every binary it reached
still printed `test result: ok`, so the file reads complete. That is right and it is not enough.

**`--no-fail-fast` governs test FAILURES. It does nothing about a BUILD failure.** Four of my five
attempts died at compilation, `--no-fail-fast` present every time, and the resulting file contains
**zero** `test result` lines. Zero is the dangerous number, because zero reads like *"nothing has
run yet"* rather than *"the run is over and it failed."* A tail shows warnings; an exit code can be
0 if a wrapper swallowed it; and a `FAILED` grep finds nothing, because nothing ran.

**So the tally needs two checks, not one:**

* **Count the `test result` lines against the expected number of binaries** (~127–133 for this
  workspace). Fewer means a partial run — the fail-fast case CLAUDE.md already describes.
* **Check that the count is not ZERO, and read the file's `error` lines when it is.** Zero means the
  build failed and no test executed at all. This is a different failure with the same-looking file,
  and it is the one that bit this session four times.

And the corollary that cost the most time here: **grep the file for `error[E`/`could not compile`
before believing any tally**, because a workspace that does not build produces a file that is
neither green nor red — it is empty of evidence, and empty is what "green" looks like from a
distance.

---

## 14 · What is certified, and what is not

**Certified — from runs I own, on `target/release/marlowe.exe` built 13:31:54:**

* `cargo build --release --jobs 4` exit **0**, with `MARLOWE_CUDA_LIB_DIR` set.
* The product-level TTFT pair, **151.5 ms (llamacpp, GPU) against 472.5 ms (ollama)**, warm, median
  of three, measured inside the running daemon, with the like-for-like control in §10 and the method
  in §11.
* Generation rate, same instrument: 166–179 frames/s on both GPU arms, **17.2** on the CPU
  fail-open arm.
* The DLL control: the product's printed launch command allocates **0 bytes** of VRAM and logs
  `no usable GPU found`; the same command plus `PATH` allocates 6.3 GB and does not (§2).
* Iteration 2 of a real tool-using turn against a live `llama-server`: three outbound requests, the
  `tool_calls` replay on requests 2 and 3, both 200, correct answer (§6.2).
* The VRAM re-base: `rerank CUDAExecutionProvider` on a llamacpp daemon with a GPU-resident server
  (§6.4).
* Ollama is still the default and still discloses its own 12/12 (§6.1).

**NOT certified: the workspace suite tally.** Five attempts, four aborted at compilation on three
different sessions' in-flight edits, and the one file that completed was written by two processes at
once and is unusable as evidence (§7). The tree is, at the time of writing, **deliberately** not
compiling: `Availability::probe` has taken a required `OffloadPolicy` argument and `Availability::Ready`
a required `offload` field, ahead of the four `daemon.rs` call sites — which is §3's fix landing as a
load-time error, exactly the right shape, in two halves. Owners notified; no code fixed by me. **The
tally is owed and it is not this feature's to give.**

---

## The workspace suite — and why no tally is attached to this document

**Four attempts. None produced a countable run, and not one of the reasons was the llama.cpp work.**

| # | started | outcome | cause |
|---|---|---|---|
| 1 | 13:22:35 | build exit 101 | `target/release/marlowe.exe` locked by two `marlowe.exe` from 02:51 |
| 2 | 13:24:56 | **contaminated** | a second agent wrote into the same `suite.txt`; my own marker lines missing, line 279 torn, a `target/verify-llamacpp` path I never set, one rustc dead of `STATUS_DLL_INIT_FAILED` |
| 3 | 13:54:59 | build exit 101, **zero** `test result` lines | `ollama_store.rs:334` mid-write: `a.contains('\')`. **Already fixed at 13:55** — re-verified before reporting |
| 4 | 13:58:14 | build exit 101, **zero** `test result` lines | `Availability::probe` gained a 4th parameter `OffloadPolicy` (`llamacpp.rs` 13:52) and `daemon.rs` (13:15) had not caught up |
| 5 | 14:02:16 | `cargo check` still red | same refactor, converging: `marlowe-provider` now compiles, `marlowe-daemon` has **three** un-updated `Availability::probe` call sites (`daemon.rs:1073, 1351, 1568`) |

**NO SUITE TALLY IS CLAIMED BY THIS DOCUMENT.** The tree was being actively refactored by the
hybrid agent throughout — `hybrid.rs`, `llamacpp.rs` and `ollama_store.rs` all changed between
13:52 and 14:02 — and the last clean state I could have counted was the 13:25 binary, before that
work began. **The suite must be run after the `OffloadPolicy` refactor lands.** Anything counted
mid-refactor is a number about a tree nobody will ship.

Attempt 2's readable numbers were **135 binaries, 1,603 passed, 0 failed** — and they are **not
evidence**, because at least two runs' output is interleaved in that file. They are preserved as
`suite-CONTAMINATED-two-writers.txt`. **The danger is that they look right**: against an expected
~1,520+/0 they read as a clean pass.

A bounded waiter is polling `cargo check --workspace` and will run the suite **once** into
`suite-verify.txt` on the first clean check. **A tally taken of a half-refactored tree would be
exactly the plausible-looking number this project keeps being caught by, so none is claimed here.**

### Two tooling traps, both hit live, both worth recording

**1. The background-task harness reported "exit code 0" while `cargo` exited 101 — twice.** The
wrapper's status was the subshell's, not cargo's. Tallying the file is what caught it. Two
independent instruments were wrong in the same direction and the file was right.

**2. A compile error in ONE test target aborts the whole workspace build, and `--no-fail-fast` does
not cover it.** CLAUDE.md's rule is written for a *test failure*, where every binary cargo reached
still prints `test result: ok` and the file looks complete — detected by counting binaries against
an expected total. A **build** failure is a different mode: the file holds **zero** `test result`
lines, and "zero" reads like *"nothing has run yet"* rather than *"the run is over and it failed"*.
**Two failure modes, two detectors.** Attempt 1 also showed the first form of it: `--no-fail-fast`
printed *"build failed, waiting for other jobs to finish"* and then exited, having run nothing.

### Observing another session mid-write

Attempts 3 and 4 are CLAUDE.md hazard forms 4 and 5: **a real error, accurately observed, about a
state that had already stopped existing.** Attempt 3's syntax error was gone within a minute. Both
were reported with the time of observation and neither was fixed by me — only the author knows the
intent, and the reflex to fix is the wrong one.

---

## Confirmations against the task's own questions

| asked | answer | how |
|---|---|---|
| TTFT through the product, both providers | **71.0 ms llamacpp / 382.4 ms ollama**, 5.4x, throughput equal | running daemon, its own socket protocol, both arms back to back |
| Does the embedder/reranker still resolve to CUDA with llamacpp active? | **Yes** — `CUDAExecutionProvider` | reproduced the hazard state: `ollama ps` empty, `ollama list` 6.6 GB, 2,124 MiB free |
| Is Ollama still the default? | **Yes** | no `--provider` flag, no env vars → `provider ollama` with Ollama's own 12/12 disclosure |
| Did anything switch on its own? | **No** | `PROVIDERS` unchanged in order; `zero_config_is_unchanged.rs` untouched |
| Checks that would read the same if broken | **five named**, one of them measured at 10.1x | Finding 2 |
