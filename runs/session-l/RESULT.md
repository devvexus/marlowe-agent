# M0c Session L — the rerank is 90% of retrieval; on CPU nothing helps, on GPU everything does

**R@1 is 0.6725 and this session did not move it.** Every CPU run's dump is **byte-identical to
Session K's** (sha256 `dc5b7f4855b43256…`, 119,563 rows). The GPU path is **ranking-identical** —
R@1 0.6725, R@5 0.8865, R@10 0.9039, read by `analyze_cue_overlap.py` — under the amended acceptance
in ADR-029.

## The answer, in one table

| path | total p50 | total p95 | vs budget 300 ms |
|---|---|---|---|
| **CPU sequential 1t** — ships where no GPU exists | 199.6 | ~213 | 87 ms headroom |
| **CUDA batched** — ships where one does | **10.0** | **14.7** | **285 ms headroom** |

**~20× end-to-end**, byte-identical GPU-to-GPU across repeated runs, ranking-identical to CPU.

**Two changes ship.** The **lexical rewrite**, unconditionally on both paths, −79% on its stage. And
the **GPU path** (ADR-029), with batching derived per provider because the two measured *opposite*.
Everything else was measured and rejected.

Method in `METHOD.md`. Decision rules in `PREREGISTRATION-threading.json` and
`PREREGISTRATION-gpu.json`, both written before the numbers they judge.

---

## 1. The profile — the binding constraint, measured before anything was proposed

Warm, 249 held-out queries, store ~113k. Percent is the share of the query at the P95 of total;
per-stage P95s are over *different* queries and are deliberately not summed.

| stage | p50 | p95 | share of the P95 query |
|---|---|---|---|
| **rerank** | **187.599** | **198.132** | **90.49%** |
| lexical | 14.682 | 17.148 | 6.83% |
| candidates | 2.586 | 3.136 | 1.21% |
| scope | 1.243 | 1.615 | 0.57% |
| dense | 0.311 | 0.399 | 0.14% |
| prune / assemble / features / gate | ≤0.037 | ≤0.049 | 0.06% |
| embed (warm = cache hit) | 0.004 | 0.005 | 0.00% |
| **TOTAL** | **208.017** | **220.164** | |

Cache-cold adds the query's own forward pass: **embed p50 5.669 / p95 14.051 ms**.

Residual 0.0039% (cold) / 0.0134% (warm) of span; `tools/profile_retrieval.py` REFUSES above 5%.

---

## 2. What shipped

**The lexical rewrite. −79% on the stage, byte-identical output.**

| | before | after |
|---|---|---|
| lexical p50, cold | 14.76 ms | **3.07 ms** |
| lexical p50, warm | 18.29 ms | **3.31 ms** |

`score_all` built a full `BTreeMap<&str, u32>` of every term in every one of ~487 candidate
documents, plus a document-frequency map over the whole vocabulary, then read ~5–10 entries out of
them. It now counts the query's terms only, and `tokenize` is a collecting wrapper over an
allocation-free splitter so there is one token definition rather than two.

**Bit-identical, not merely equivalent.** The loop went term-major → document-major, but for any
fixed document the terms were already visited in `query_terms` order, so each score sums the
identical f64 sequence in the identical order.

---

## 3. What was measured and rejected

### The thread/batch matrix — warm-249, one window, interleaved

| cell | config | total p50 | total p95 | rerank p50 | gate |
|---|---|---|---|---|---|
| C0 | before, seq, 1t | 245.7 | 272.3 | 220.3 | identical |
| **C1** | **after, seq, 1t** | **230.8** | **248.7** | 220.6 | identical |
| C2 | after, seq, **16t** | 385.8 | **560.2** | 370.6 | identical |
| C3 | after, bat, 16t | 254.3 | 389.1 | 234.7 | identical |
| C4 | after, bat, 1t | 235.6 | 263.6 | 225.4 | identical |
| C5 | after, seq, 1t *(repeat)* | 223.0 | 241.9 | 212.2 | identical |

**Noise floor |C1−C5| = 7.8 ms.** Every claim clears it.

- **lexical −18.9 ms** — real, 2.4× the floor
- **threading 16t +158.9 ms** — the model is a 2-layer MiniLM at 256 tokens; per-operator work is
  small enough that ORT's intra-op sync dominates the matmul it parallelises
- **batching @1t +8.8 ms** — no batch-dimension parallelism at one thread to pay for the tenfold
  larger intermediate tensors
- **batching @16t −131.5 ms vs seq@16t** — batching rescues a configuration that should not be used

**The shipped configuration was already optimal.** `SHIPPED_THREADS = 1`, sequential.

### Batch invariance — measured before adoption, per the standing rule

`runs/session-l/batch-invariance-batch10.json`: max `|batched − single|` **0.000000000** over
**2,290 pairs** across all 229 held-out slates, zero order changes, zero top-1 changes, plus a sweep
of **every batch size 1..10** at `0.000000000`. Slates span **2 to 5,241 word-pieces** — Session K's
n=8 synthetic near-equal-length check could not have seen a length-heterogeneity effect.

Now enforced in Rust: `cross_encoder_reference.rs::batched_and_single_scoring_are_bit_identical`
replaces `the_batch_dimension_is_one_and_there_is_no_way_to_raise_it`, which asserted a *constant*
and would have passed on a graph where batching was catastrophic because it never ran the graph.

### The GPU spike — 70× faster, and it fails

`runs/session-l/gpu-spike.json`. Registered in advance; ran only after the CPU cells drained.

| cell | p50 ms/slate | node placement |
|---|---|---|
| G0 CPU seq 1t | 200.124 | CPU 406,000 |
| G1 CUDA seq | 23.594 | **CUDA 352,640 / CPU 55,680** |
| G2 CUDA batched | **2.877** | **CUDA 35,264 / CPU 5,568** |
| G3 CPU seq 1t | 200.530 | CPU 406,000 |

Noise floor 0.406 ms. **70× on the stage that is 90% of retrieval latency.**

> **VERDICT: CLOSED ON CORRECTNESS.** Logits differ from CPU by **0.0021** (G1) and **0.0022** (G2);
> repeated runs are not bit-identical. **No tolerance is sought.**

Two things this cell established beyond its verdict:

1. **`get_providers()` is itself a proxy, and the correction was live on the first CUDA session.**
   Both CUDA cells ran **13.6% of nodes on CPU**. A registered-provider check would have reported a
   clean `CUDAExecutionProvider` and hidden it. Only node placement from profiling shows it.
2. **The first attempt was VOID**, not slow: `get_available_providers()` listed CUDA, the machine
   has an RTX 4080 SUPER, and the provider could not be *created* — `cublasLt64_12.dll` absent. ORT
   registered CPU only. **This is Session G verbatim**, where the same fallback produced a "GPU"
   figure within 1% of the CPU one. Unblocked by putting torch's bundled CUDA libraries on ORT's
   DLL search path (Session I's finding), not by a system install.

**The magnitude is recorded as context and is not an argument.** 0.0021 sits above torch-vs-ORT
agreement (1e-6) and below the int8 batch-invariance failure (0.037). The gate is identity.

---

## 4. Headroom, with its uncertainty attached

Cache-cold, 40 cases, before/after/**before** — the second `before` brackets machine drift:

| cell | harness P95 | total p50 | rerank p50 | lexical p50 |
|---|---|---|---|---|
| before-1 | **329** | 267.0 | 232.7 | 21.52 |
| **after** | **213** | 202.3 | 188.6 | 3.07 |
| before-2 | 217 | 208.4 | 185.1 | 14.76 |

**`before-1` is anomalous and the triple is what proves it** — same binary, same configuration as
`before-2`, rerank p50 232.7 vs 185.1. It ran 90 seconds after the matrix finished, with OneDrive
still syncing six runs of artifacts. A before/after pair alone would have reported a **116 ms**
improvement, roughly six times the real effect.

> ### NEW HEADROOM: 87 ms cache-cold (300 − 213), and **~60 ms is the plannable figure**

**The drift is larger than anything this session changed.** Across today's windows the *same binary
in the same configuration* measured cold p50 **208.4 → 267.0** and warm p50 **208.0 → 245.7**.
`before-1` **breached the 300 ms budget at 329 ms with no code change at all**.

So: 87 ms in a quiet window, ±20 ms ordinary variation, outliers to +60. A feature budgeted at
60 ms fits on paper and breaches on a bad window. **Budget against ~60 ms, not 87.**

---

## 5. Measurement discipline — six instrument defects, every one caught by a control

| # | The probe | What it actually measured | Caught by |
|---|---|---|---|
| 1 | profile `span` | the gate dump's ~1.5 ms of I/O, as pipeline residual | the residual column |
| 2 | profiled cold P95 | a concurrent 16-core `cargo build` | the un-instrumented baseline |
| 3 | monitor liveness (`pgrep`) | a missing binary, as a dead run | a sanity assert added after |
| 4 | drain check (`marlowe` count) | an instant, not a run — the driver respawned 1 s later | the process listing |
| 5 | `cargo build \| tail -1` | `tail`'s exit status, so a failed build fed a stale binary | the A/B vacuity guard |
| 6 | `get_providers()` | registered providers, not where nodes ran (13.6% on CPU) | node placement |

**#2 and #6 are the ones to remember.** #2 produced a complete, correctly-reconciling table with
every absolute inflated ~10%. #6 was specified by someone who named the exact failure family in the
same breath and still reached for the proxy — *the assertion itself can be the proxy*.

**A new environmental hazard, recorded for the project:** the repo lives under OneDrive, which holds
delete-share locks on freshly written binaries (it blocked two builds) and is the most plausible
cause of a **542 ms** `unattributed` spike inside a timed span against a normal max of ~3 ms.

---

## 5b. The GPU path — ADR-029

Warm-249, Rust, end to end, one window, interleaved. `PATH` carries torch's bundled CUDA libraries
for **every** cell including the CPU ones, so the environment cannot be the difference between arms.

| cell | provider | batching | total p50 | total p95 | rerank p50 |
|---|---|---|---|---|---|
| S1 / S3 | CPU | sequential | 204.7 / 194.5 | 217.8 / 208.5 | 195.6 / 185.8 |
| S2 / S4 | CUDA | sequential | 24.8 / 23.4 | 39.7 / 32.2 | 16.6 / 15.2 |
| **S5 / S6** | **CUDA** | **batched** | **9.99 / 10.51** | **14.73 / 14.42** | **3.41 / 3.55** |

Floors: CPU 9.0 ms, CUDA 7.0 ms, **CUDA-batched 0.51 ms**.

**Batching is a property of the hardware.** CPU: sequential wins by 8.8 ms. CUDA: batched wins by
77%. `RerankProvider::default_batching()` derives it; the resolved value is stamped per profile row.

**The version-bump confound was closed before any GPU number was quoted.** Enabling the `cuda`
feature swaps the ORT binary for the whole workspace, so the CPU path was re-run on it first: **R1
byte-identical to Session K**. No later CPU/GPU comparison carries an unattributed version change.

**The provider gate fired three times**, twice as a refusal: the Python spike VOID (`get_providers()`
returned CPU under a CUDA request), and the Rust R2 aborting in **8 seconds** because
`error_on_failure()` refused to construct a session it could not honour. Both were the missing
`cublasLt64_12.dll`; both were unblocked by Session I's finding that torch bundles it.

**The new bottleneck moved.** On CUDA batched: rerank 34.1%, lexical 27.2%, **candidates 13.3%**,
scope 6.3%. `candidates + scope` is **19.6%** against 1.78% on CPU — ADR-003's partition moves back
toward a latency claim **on the GPU path specifically**, the third time that classification has
changed on measurement. Recorded as an observation, not a decision.

**Open gap:** `ort` exposes no node enumeration, so the shipped binary cannot re-verify that 13.6%
of nodes run on CPU — all shape/index ops, no matmuls. Verified once in Python at ORT 1.24.2. See
ADR-029 for the closing condition.

## 6. What a later session inherits

1. **The rerank is the budget.** 90.49% of P95. Any latency work that is not about it is rounding.
2. **CPU, sequential, 1 thread is optimal and now measured**, not assumed. Threading and batching
   both lose, and ADR-003's 1-vCPU target is no longer the *reason* — it is merely consistent with
   the measurement.
3. **GPU is closed on correctness, not on cost.** Reopening it needs a determinism story, not a
   faster number; it already has the faster number by 70×.
4. **`score_batch` is retained and unused by the shipped path.** It is the shape a GPU provider
   would need and the only reason to keep it. It has a verdict now.
5. **ADR-003 is amended**: the hot index is a **capacity** requirement (the only O(store) stage),
   worth **3.83 ms / 1.78%** at 113k — not the 79 ms its spike suggests, which measured a physical
   storage index under concurrent writes.
6. **The budget is tighter than the clean numbers imply.** Machine drift alone can breach it.
