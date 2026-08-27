# Canonical product TTFT — one instrument, one clock, and what the other two were measuring

**2026-08-27, 14:15:36 → 14:20:24, this machine (RTX 4080 SUPER, 16 GB), `qwen3.5:9b`, one GGUF
blob (`sha256-dec52a44…`) served two ways.** Six cells, n = 12 per cell, rep 1 discarded,
**n = 11 warm**. Every cell bracketed `0 cargo / 0 rustc` **before and after**, recorded in the
cell's own JSON by the instrument rather than remembered. Nothing was built. Nothing outside
`runs/llamacpp/` was written. No commit.

Binary under measurement — stated because `product_ttft_daemon.py` vanishing is exactly why this
line exists:

```
target/release/marlowe.exe
  mtime  2026-08-27 13:31:54.443068100 -0500
  sha256 65acfa2d5f254541a439d1e898f4c0fd73d366cb3517310e4c4de65af2849359
```

---

## 1 · The canonical pair

**The clock is the daemon's own `--dev` stderr**, as briefed: from the daemon printing
`===== END REQUEST =====` to it printing the first frame carrying bytes.

| arm | **TTFT median** | min | max | spread | n warm | tok/s | turn total |
|---|---|---|---|---|---|---|---|
| **llama.cpp (GPU, hand-launched)** | **65.3 ms** | 62.7 | 81.2 | 18.6 | 11 | **73.6** | 501.3 ms |
| **Ollama** | **313.4 ms** | 296.3 | 394.4 | 98.1 | 11 | **68.3** | 778.3 ms |
| **ratio** | **4.80x** | | | | | 1.08x | 1.55x |

**Quote 65 / 313 and 4.8x.** Not 71/382 (5.4x), not 151/472 (3.1x), and not ADR-060's 52/275.

**Both axes move the same way**, which is the reading that matters: llama.cpp is 4.8x faster to
first token **and** faster on the whole turn (501 ms vs 778 ms) and marginally faster generating
(73.6 vs 68.3 tok/s). The failure this project has recorded — a 2x TTFT *win* concealing a 5x
turn-time *regression* on a CPU server — is not present. It could not have been ruled out from
TTFT alone, which is why it is in the table.

### The control cell

The same fixed prompt, re-measured after the other phase, so stability is demonstrated rather
than claimed:

| cell | first pass | control repeat | apart |
|---|---|---|---|
| llama.cpp, `--dev` on | 65.3 ms | **65.9 ms** | 0.6 ms |
| Ollama, `--dev` on | 313.4 ms | **305.9 ms** | 7.5 ms |

Both repeats land inside the first pass's own min/max. The machine did not move under the
measurement.

---

## 2 · The prompt, on every measured call, both arms

This is the single reading whose absence caused the disagreement, so it is dumped per call and not
sampled.

| reading | llama.cpp | Ollama |
|---|---|---|
| system message | **17,381 chars** | **17,381 chars** |
| distinct values seen across 11 warm reps | **{17381}** | **{17381}** |
| messages in the body | 2 | 2 |
| tools offered | **12** | **12** |
| model calls per turn | 1 | 1 |

Tool list, byte-identical on both arms, all six cells:

```
read, write, edit, glob, grep, bash, web, recall, use, ask, remember, run
```

**The two arms send the same prompt. The 4.8x is not a prompt-size artefact.** This confirms B's
claim on this point — B verified it too, and B was right.

It also means the system-prompt drift B found (17,381 → 17,529 mid-run, costing ~1.45 s) **did not
occur once in 72 measured calls here.** The difference is method: a fresh profile root per cell and
a fresh session per rep. That is not a refutation of B's finding — it is the condition under which
B's finding does not fire, which makes the finding sharper, not weaker.

Daemon configuration was matched to what both prior runs announced, not left to default:

```
marlowe: memory retrieval live · models/ms-marco-MiniLM-L-2-v2-ft-session-j
```

Omitting `--reranking` makes `--serve` announce `memory retrieval WRITE-ONLY`, which is a
different system on the pre-request path. Measuring that would have been measuring something
neither A nor B did.

---

## 3 · A versus B — the explanation

### The instrument that settles it

A and B could not be reconciled because **every candidate explanation lives in the difference
between the two runs, not the two clocks.** So this instrument takes **both clock placements on the
same rep**, in one Python process, off one `perf_counter`. The gap becomes a subtraction:

```
socket_ttft  =  connect+auth  +  pre_request  +  dev_ttft  +  delivery
```

| segment | what it spans | llama.cpp | Ollama |
|---|---|---|---|
| connect + auth | socket open, token line written | 16.6 ms | 12.9 ms |
| pre_request | ask received → `END REQUEST` (auth, assembly, retrieval, the dump itself) | 4.9 ms | 11.1 ms |
| **dev_ttft** | **→ first content frame — B's placement, canonical** | **65.3 ms** | **313.4 ms** |
| delivery | → first delta on the socket — measures stderr-pipe lag | **0.1 ms** | **0.1 ms** |
| **socket_ttft** | **A's placement** | **88.0 ms** | **340.9 ms** |

### Finding 1 — the direction is confirmed, and B's ordering is structurally impossible

**44 out of 44 paired warm reps: `socket_ttft > dev_ttft`. Never once the other way.**

| cell | n | min delta | median | max |
|---|---|---|---|---|
| llama.cpp | 11 | **+5.2 ms** | +21.8 | +32.0 |
| Ollama | 11 | **+11.1 ms** | +24.8 | +36.1 |

The outer clock is larger by 5–36 ms, every time, exactly as the containment argument says it must
be. **So B reporting the inner clock HIGHER than A's outer clock cannot be a property of the
system.** It is a difference between the two runs.

`delivery = 0.1 ms` also kills the one hypothesis that would have made the dev clock untrustworthy:
the stderr pipe does not lag the socket. The dev-stderr placement is sound, and it is the right
canonical clock.

### Finding 2 — three candidate causes, measured and eliminated

| hypothesis | test | verdict |
|---|---|---|
| **prompt size** (the leading hypothesis; A never measured its prompt) | dumped per call, both arms | **ELIMINATED** — 17,381 chars / 12 tools / 2 messages, identical, 72/72 calls |
| **`--dev` perturbs what it measures** — the dump prints the whole system prompt line by line to a pipe on the critical path | ran every arm with `--dev` on and off | **ELIMINATED** — costs **10.9 ms** on Ollama (340.9 → 330.0 socket) and **−0.2 ms** on llama.cpp (88.0 → 87.8). Real, tiny, and the wrong sign to explain B |
| **clock placement** | 44 paired reps | **ELIMINATED, and it points the other way** — worth −17 to −28 ms, not +86 to +159 |

### Finding 3 — A is approximately reproduced; B is the outlier

| | llama.cpp | Ollama | vs this run |
|---|---|---|---|
| A, socket clock | 71.0 | 382.4 | **this run's socket: 88.0 / 340.9** — both within ~20% |
| B, dev clock | 151.5 | 472.5 | **this run's dev: 65.3 / 313.4** — B is **+86.2 ms (+132%)** and **+159.1 ms (+51%)** |

**A's conditions were sound; A was simply on the outer clock.** B is the number that does not
reproduce.

### Finding 4 — what I can and cannot attribute in B, stated plainly

**What is established:** B's excess is not clock placement (wrong sign), not prompt size (identical),
and not `--dev` (≤11 ms). Its own author found the contamination — a 16-core
`cargo check --workspace --jobs 4` on a 45-second poll from 13:58 to 14:02, with B's window closing
at 14:01:54, so B ran **entirely inside a build**.

**What is not established:** whether contamination accounts for the full +51% / +132%. Hazard form 6
is recorded in `CLAUDE.md` at **~10%** inflation for timed queries. B's excess is five to thirteen
times that. Two further conditions in B are visible in its own commit message and each would push
the same way:

- **n = 2 after discarding rep 1.** My data shows spontaneous Ollama stalls in an otherwise clean
  window — one warm rep at **2,292.9 ms** against a 296–394 ms band, and one turn taking two model
  calls and 3,943 ms. At n = 2 a single such event *is* the median. My own reps 2–3 also still sit
  5–13% above steady state, so with three reps the "warm" pair is not fully warm either.
- **A prefix that changed size mid-run**, 17,381 → 17,529, which B itself measured at ~1.45 s.

**I cannot decompose B's residual further, and the reason is a finding in its own right:
B's instrument and its raw rows do not exist.** `ab9b3d7` ("Product TTFT is 3.1x") committed
**`STATE.md` only, 83 insertions**. `runs/llamacpp/product_ttft_daemon.py` is not on `master`, not in
either worktree, not anywhere in the checkout. The dev-stderr clock here was rebuilt from
`daemon.rs` rather than reused, because there was nothing to reuse. **A measurement whose instrument
was never written down cannot be audited, only re-taken** — which is what this run is.

**So: the direction is fully explained and the magnitude is not.** Attributing all of B's excess to
the build would be a tidy answer I did not measure.

---

## 4 · GPU verification — mine, not the product's

**Read this before quoting anything above as evidence about the hybrid engine.**

`target/release/marlowe.exe` is from **13:31:54** and predates the entire hybrid effort. The
implementer has run `cargo check` only, which emits no executable. This binary therefore contains
**no `hybrid.rs`**: no adoption, no blob-identity match, no tool-support probe, no offload check, no
`PATH` prefix on the spawn, and no `ollama/llama.cpp` fallback. `--provider llamacpp` here is the
**third-provider** design, which connects to an endpoint and refuses.

The honest description of the arm is: **the third-provider binary, hand-launched with both
environment variables, connected to.** *Not* adopted. **None of the adoption path, the offload check,
the `PATH` fix or the fallback has ever executed**, and nothing in this document is evidence that any
of them work.

The daemon's own announcement is the positive evidence for that, not an inference:

```
marlowe: model provider LLAMACPP · http://127.0.0.1:11492 · ADR-060, opt-in; Ollama remains the default
```

Adoption would have printed `marlowe: engine llama.cpp · … · started in N ms · <offload>`. It is
absent from all three llama.cpp cells.

**Consequently the product could not tell me whether it was on the GPU, and the verification below
is my own.** Launch line, mine, matching the *old* `launch_plan` plus the `PATH` the product did not
yet emit:

```bash
LIB="$LOCALAPPDATA/Programs/Ollama/lib/ollama"
GGML_BACKEND_PATH="$LIB/cuda_v12/ggml-cuda.dll" \
PATH="$LIB:$LIB/cuda_v12:$PATH" \
"$LIB/llama-server.exe" -m <blob> -c 32768 -ngl 99 -np 1 \
    --jinja --reasoning-format deepseek --host 127.0.0.1 --port 11492
```

Three independent readings, because one would have been a proxy:

| reading | value | CPU would read |
|---|---|---|
| VRAM delta across the spawn | **+6,381 MiB** (3,334 → 9,715) | ~0 |
| GPU utilisation during a 500-token generation | **96–97%**, six consecutive samples | ~0% |
| `timings.predicted_per_second` | **77.2 tok/s** | 10.6 (DLL-CONTROL.md) |

### The 107 tok/s marker did not reproduce, and it is the same binary

The brief's threshold was *"~107 on this card, ~10 means CPU."* I measure **77.2 tok/s at
`-c 32768`**. Suspecting the context size, I re-launched at **`-c 8192` — the exact argv
`DLL-CONTROL.md` used — and got 85.7 tok/s**, still 21.7 short of 107.4. `llama-server.exe` is
unchanged on disk (mtime 2026-07-27 18:45:20), so this is not a build difference.

**77–86 is unambiguously the GPU** — eight times the CPU figure, at 96% GPU utilisation, with the
whole model resident. But **107.4 should not be used as a pass/fail threshold until someone
re-measures it**, because a run reading 85 is not a CPU server and a threshold that says otherwise
will condemn a healthy one. The likeliest cause is the ~3.1 GB of desktop GPU load on this box
(Opera, Discord, Spotify, VS Code, Steam, Wallpaper Engine) competing for cycles. **This is the
project's own rule about a measurement being scoped to the system it was taken on** — the number
arrived with a citation instead of a command, and running the command moved it.

---

## 5 · Full cell table

`dev` = canonical. All medians, n = 11 warm.

| cell | provider | `--dev` | dev TTFT | socket TTFT | pre_req | delivery | tok/s | turn | cargo/rustc before → after |
|---|---|---|---|---|---|---|---|---|---|
| OLLAMA-dev-on | ollama | on | **313.4** | 340.9 | 11.1 | 0.1 | 68.3 | 778.3 | 0/0 → 0/0 |
| OLLAMA-dev-off | ollama | off | — | 330.0 | — | — | — | 859.6 | 0/0 → 0/0 |
| LLAMACPP-dev-on | llamacpp | on | **65.3** | 88.0 | 4.9 | 0.1 | 73.6 | 501.3 | 0/0 → 0/0 |
| LLAMACPP-dev-off | llamacpp | off | — | 87.8 | — | — | — | 481.7 | 0/0 → 0/0 |
| LLAMACPP-CTRL | llamacpp | on | 65.9 | 80.2 | 4.8 | 0.1 | 73.2 | 539.0 | 0/0 → 0/0 |
| OLLAMA-CTRL | ollama | on | 305.9 | 328.0 | 11.4 | 0.1 | 68.9 | 913.6 | 0/0 → 0/0 |

VRAM at each bracket is in the per-cell JSON. Machine returned to **0 cargo, 0 rustc, 0
llama-server, `ollama ps` empty, 12,953 MiB free** at 14:22:48.

Discarded rep 1, for the record — it is the cold-prefix cell occurring on schedule rather than
being provoked: llama.cpp **2,193.5 ms**, Ollama **393.7 ms** and **5,428.2 ms** (the latter
including the Ollama model load).

---

## 6 · Artifacts

| path | what |
|---|---|
| `runs/llamacpp/ttft_canonical.py` | the instrument — both clock placements, per-call prompt dump, self-bracketing (it **refuses to start** if cargo/rustc is non-zero) |
| `runs/llamacpp/canonical/*.json` | per-cell rows, medians, brackets, the daemon's announcements |
| `runs/llamacpp/canonical/daemon-*.stderr.log` | every daemon's full `--dev` stderr, each line prefixed with its `perf_counter` read time |
| `runs/llamacpp/canonical/llama-server-11492.log` | the server under measurement (`-c 32768`) |
| `runs/llamacpp/canonical/llama-server-11493-c8192.log` | the `-c 8192` throughput control |

### Method notes worth keeping

- **A fresh profile root came from `--serve --profile-root`, not from deleting
  `$LOCALAPPDATA/marlowe/default-profile`.** My first draft moved `LOCALAPPDATA` instead — which is
  also where `llama-server.exe` is looked for, so it would have silently cost the llama.cpp arm its
  engine while every label still read `llamacpp`. Caught before it ran, by asking what the cell
  would report if the engine had quietly changed.
- **`delivery` is signed on purpose.** A pipe-read clock asserted to be tight without being measured
  is the same shape as every other proxy in `CLAUDE.md`. It measured 0.1 ms, so the claim is now a
  reading.
- **The stop edge is pinned to the content-bearing frame on both clocks.** The dev dump prints a line
  for every frame including the role-only opener; stopping on `frame 1` would have compared two
  different events and called the difference a clock.
