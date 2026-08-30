# The capacity model, measured — and `AGENT-DIRECTORY.md` §2's headroom does not exist

**Measured 2026-08-30, M3 Session C, before designing the admission queue.** AGENT-DIRECTORY §2a is
explicit that this had to come first: *"`GET /api/ps` is the measurement; the env vars are only
declarations. Measure before designing the queue, or the queue will be built against the wrong
bottleneck."*

Raw output: [`capacity.txt`](capacity.txt). Probe: [`capacity_probe.sh`](capacity_probe.sh).

## What was asked, and what the answer is

*"3 workers loaded, out of memory"* had two readings with different bottlenecks and different knobs.
**This machine is in the second reading, and the first one cannot arise at `NUM_PARALLEL=1`.**

| Reading | Bottleneck | Knob | Measured |
|---|---|---|---|
| three workers of the **same** role | KV cache | `OLLAMA_NUM_PARALLEL` | **=1**, so a role admits one request at a time and a second same-role worker does not get a slot — it queues inside Ollama, invisibly |
| three workers of **different** roles | weights | `OLLAMA_MAX_LOADED_MODELS` | **unset, and it resolved to ≥ 3** — all three roles stayed resident simultaneously |

So the co-residency premise holds. **The headroom claim does not.**

## The numbers

RTX 4080 SUPER, **16,376 MiB** total, Ollama 0.32.5.

| Stage | `memory.used` | `memory.free` | Resident models (`/api/ps`) |
|---|---|---|---|
| baseline | **5,086 MiB** | 10,960 MiB | none |
| + `marlowe-dawn:9b-super` | 11,756 | 4,290 | 1 |
| + `marlowe-mini:4b-super` | 14,582 | 1,464 | 2 |
| + `marlowe-mini:2b` | **14,993** | **1,053** | **3** |

Cold load + one token: **4,354 / 3,212 / 5,442 ms**. Every model reported `context_length: 32768`.
Declared environment: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
`OLLAMA_KEEP_ALIVE` **unset**, `OLLAMA_MAX_LOADED_MODELS` **unset** — read at both User and Machine
scope.

## Finding 1 — the 5,086 MiB baseline is the desktop, and the design's arithmetic omits it

AGENT-DIRECTORY §2: *"**10.0 GB of the card's 16**, co-resident, leaving headroom for the KV cache,
the embedder and the reranker."*

The card was **never** 16 GB free. `nvidia-smi --query-compute-apps` names the holders: Opera GX,
Discord, Steam's `steamwebhelper`, Wallpaper Engine, the NVIDIA overlay, `explorer.exe`,
`msedgewebview2`, ASUS Armoury and Alienware FX. **That is a machine someone works on, not a leak** —
it is the ordinary state, and it is 5.0 GB before Marlowe asks for anything.

**Measured headroom after the three roles: 1,053 MiB.** Not six gigabytes; one.

That matters because **ADR-044 resolves the embedder's provider against free VRAM at load**, and this
document already records what that produces: *"an unset variable is not an error — it is a slower run
with a correct-looking log line."* With 1.0 GiB free the embedder falls to CPU and says so in a line
that reads exactly like success. The reranker wants VRAM on the same terms.

**The fourth role has nowhere to go.** Its name is the human's (three of four were given defaults);
its *space* is now measured, and there is not any.

## Finding 2 — `ollama list` sizes are blob sizes, and `size_vram` is 8.5% larger

| Model | `ollama list` | `size_vram` (bytes) | `size_vram` (MiB) |
|---|---|---|---|
| `marlowe-dawn:9b-super` | 5.9 GB | 5,832,064,368 | 5,561.9 |
| `marlowe-mini:4b-super` | 2.8 GB | 3,271,515,176 | 3,120.0 |
| `marlowe-mini:2b` | 1.3 GB | 1,746,256,526 | 1,665.4 |
| **total** | **10.0 GB** | **10,849,836,070** | **10,347.3 MiB = 10.85 GB** |

§2's table sizes the roles from `ollama list`. **`size_vram` is the figure an admission decision has
to use**, and it is the larger one. Planning against the `ollama list` column overcommits by 850 MB —
which, against 1,053 MiB of real headroom, is most of it.

## Finding 3 — neither number reconciles, so a plan computed once is already stale

Baseline 5,086 + `size_vram` 10,347 = **15,433 MiB expected**; **14,993 MiB observed**. 440 MiB apart.
Per-model deltas disagree in both directions: `dawn:9b` took **6,670 MiB** of real card against
5,562 MiB reported, and `mini:2b` took **411 MiB** against 1,665 MiB reported.

Two causes, and both point the same way: `size_vram` excludes the CUDA context and compute buffers,
and **the desktop's own usage moves by hundreds of MiB while the probe runs** — a browser tab, a
Discord call, a game launcher.

**Consequence for the queue: free VRAM is not a quantity that can be computed at startup and
subtracted from.** Admission must re-measure at admit time and carry a margin, and the margin has to
be big enough to absorb a desktop that is not asking permission. A queue that plans once will admit a
model that then does not fit, and Ollama's failure mode there is a CPU split — which
`AGENT-DIRECTORY.md` §2a forbids by name.

## Finding 4 — `NUM_PARALLEL=1` means the roster can tell the truth about intent and lie about execution

Four co-resident models still serialise: each admits one request at a time. AGENT-DIRECTORY §3 item 7
states the consequence — *"a directory showing eight running agents on a machine that runs them one at
a time is telling the truth about intent and a lie about execution."*

**This is the same shape as the `RunStatus::Queued` question, one level down.** *Waiting for a model
slot* and *running* must not render as one word either, and the queue is the thing that knows the
difference. Whether to raise `NUM_PARALLEL` is a direct trade against the prefix-cache protection it
was set for — a TTFT decision the human already took once — and is **not** taken here.

## What this does NOT establish

- **Nothing about concurrency was measured.** No two requests were issued at once. That
  `NUM_PARALLEL=1` serialises is read from the declaration, not from a run — the honest status is
  *declared, not measured*, and it stays that way until two overlapping requests are timed.
- **Nothing about eviction.** `OLLAMA_KEEP_ALIVE` is unset, so the three models expired ~5 minutes
  after the probe. Whether re-warming under memory pressure evicts cleanly or CPU-splits is unmeasured.
- **This is one machine on one day, with one desktop workload.** Per CLAUDE.md's standing rule, it is
  a measurement scoped to the system it was taken on. A different desktop baseline is a different
  answer, and the generalisation to *all consumer hardware* — STATE.md's open item **THREE CONSTANTS
  ENCODE A 16 GB CARD** — is untouched by it.
