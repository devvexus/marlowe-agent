# The capacity sensor — a brief for a future session, not a design

**Requested 2026-08-31 by the human, after admission control was declined on a measured finding.**
This page is a session's *input*. It deliberately does not pick a winner.

| | |
|---|---|
| **Status** | requested; nothing designed, nothing built |
| **Blocks** | [`ADR-067`](adr/ADR-067-admission-control-on-spawn-and-what-queued-means.md) — admission control on spawn, which cannot be built until this is answered |
| **Caused by** | `/api/ps`'s `size_vram` measured wrong by 7.6× on the largest model, and `size == size_vram` making the CPU-split test inert |
| **Related** | [`AGENT-DIRECTORY.md`](AGENT-DIRECTORY.md) §2a; `STATE.md`'s open item *THREE CONSTANTS ENCODE A 16 GB CARD* |

---

## §1. The finding that made this necessary

Measured 2026-08-31 on a 16,376 MiB card, `marlowe-dusk:27b-super`, three polls two seconds apart:

```
/api/ps   size 1,631 MiB   size_vram 1,631 MiB      <- stable, and wrong
nvidia-smi  8,856 MiB used  ->  15,415 MiB used     <- ~6.5 GB actually taken
/api/generate  load_duration 11,410 ms              <- it really did load
```

**Two consequences, and they are independent defects.**

1. **`size_vram` under-reported by 7.6×.** An admission controller asking *"how big is this model"* gets an answer 6 GB too small and admits something that does not fit.
2. **`size == size_vram`, so the standard CPU-split test reads GPU-ONLY** — on the one model where a split is most likely. §2a's *"we NEVER CPU-split"* cannot be enforced by comparing those two fields.

**ADR-067 keys its refusal branch and its no-split guarantee on exactly those two fields.** That is why it was not built: it would have shipped a guard that reads *"fits"* whatever happens, which is this project's most-logged shape.

---

## §2. THE STRUCTURAL INSIGHT — there are TWO questions and ADR-067 conflated them

This is the most useful thing on the page and it should survive even if every option below is rejected.

| | Question | When | What a wrong answer costs |
|---|---|---|---|
| **Predictive** | *Will this model fit if I load it?* | **before** the load | admit → OOM, or a CPU split, or an eviction nobody chose |
| **Verificatory** | *Did it fit, fully, on the GPU?* | **after** the load | the roster lies about what is running |

**They are different questions and they probably need different sensors.** A predictive sensor must work on a model that is **not resident** — which is precisely what `/api/ps` cannot do, because it lists only resident models. A verificatory sensor may use anything, including behaviour.

Conflating them is the likeliest root cause of ADR-067's shape: it reached for one field to answer both, and that field can answer neither.

---

## §3. Options to explore. None is endorsed.

### A. Read the blob and manifest on disk
`~/.ollama/models/manifests/.../<tag>` lists layers and byte sizes; the blobs are under `blobs/sha256-*`.

- **For:** exact, static, needs no server, and **available before the model is loaded** — the only family that can answer the predictive question directly.
- **Against:** weights ≠ VRAM. KV cache, compute buffers and the CUDA context sit on top, and that overhead is what the 7.6× gap is made of. It also cannot see a split.
- **Ask:** is `weights + measured_overhead_factor` good enough, and is that factor stable per architecture?

### B. `nvidia-smi` free-memory delta around a load
What produced the finding above.

- **For:** measures the real thing.
- **Against:** **only works after loading**, so it cannot gate admission; and the desktop moves under you — a 440 MiB drift was measured *mid-probe*.

### C. Per-process attribution (`--query-compute-apps`, or NVML directly)
Attribute VRAM to the Ollama process and ignore desktop noise.

- **For:** removes the drift in B.
- **Against:** **measured on this machine, `used_gpu_memory` returned `[N/A]` and `[Insufficient Permissions]`** for every process. Check whether NVML gives it with different privileges before building on it.

### D. Parse the GGUF header and compute analytically
Block count, embedding length, head counts, quantization, context length → weights + KV by formula. `/api/show`'s `model_info` exposes much of the same without opening the file.

- **For:** predictive, and the **only option that can answer "what context length fits"** rather than a yes/no.
- **Against:** it is reimplementing llama.cpp's memory estimator, and it will drift from what Ollama actually does. A formula that disagrees with the loader is a second definition of the fact.

### E. Ollama's own debug log (`OLLAMA_DEBUG=1`)
The server prints its **own** estimate and the offload decision — *"offloading N repeating layers to GPU"*.

- **For:** this is the ground truth *for the decision Ollama is about to make*, including the split, from the component that makes it. Strongest candidate for the verificatory question.
- **Against:** log parsing, and an unstable format across versions. Would need a pinned-version check that fails loudly rather than silently mis-parsing.

### F. Measure once per model, then remember
Load it, measure the real delta, evict, **cache the number against the blob digest.**

- **For:** empirical and exact; the digest makes the cache correct by construction. Probably the strongest *practical* answer.
- **Against:** costs one real load per model (11.4 s measured for the 27b) — fine once, unacceptable per spawn. Needs a cold-start story and an invalidation rule when the card's free memory changes.

### G. Detect a split behaviourally, not declaratively
A CPU-split model is dramatically slower. Measure tok/s on a tiny generation against a per-model baseline.

- **For:** **asserts the property rather than a proxy**, which is this project's own rule; and it works when `size_vram` lies.
- **Against:** needs a baseline per model per machine, and it is slow to evaluate.

### H. Two sensors that must agree, else refuse
Do not trust one number. Require agreement between an independent pair — say A and B, or F and G — and treat disagreement as **unknown**, failing closed.

- **For:** directly answers the failure that caused this page. Disagreement is a *signal*, and a sensor that cannot be cross-checked is one that will be believed when wrong.
- **Against:** more moving parts, and a real cost when the two legitimately differ.

---

## §4. What the session must not do

- **Do not build a guard on a field nobody has verified.** That is the mistake being repaired. Whatever is chosen arrives with a measurement showing it is right on `marlowe-dusk:27b-super` specifically — the model where the current sensor fails.
- **Do not read an env var and call it a measurement.** §2a: *"`/api/ps` is the measurement; the env vars are only declarations."* That rule stands; it is the *sensor* that was wrong, not the principle.
- **Do not assume the 16 GB card.** Co-residency assumes larger cards or smaller models. The sensor must be right on both.
- **Do not conflate the two questions in §2.** If one sensor genuinely answers both, say so and show it.

## §5. The acceptance bar

A command that prints a number, per this project's standing rule. At minimum:

1. **Predict** the footprint of a model that is **not resident**, and be right within a stated band when it is loaded.
2. **Detect a CPU split** on a model that actually splits — which means **deliberately causing one**, on a card too full, and showing the sensor says so. A no-split guarantee that has never seen a split is a guarantee nobody has tested.
3. **Survive the desktop moving** by hundreds of MiB mid-decision.
4. **Fail closed and say which sensor disagreed**, rather than returning a number nobody can audit.
