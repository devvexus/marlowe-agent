# ADR-044 — The embedder defaults to `auto`: GPU where one constructs and fits, CPU otherwise, and the resolved provider is ANNOUNCED

**Status:** ADOPTED 2026-08-17, on the human's authority as a design decision. **Shipped in this
commit** — `crates/marlowe/src/main.rs` no longer defaults `--embedder-provider` to `cpu`.
**Depends on:** ADR-013 (GPU deferred for the retrieval path, pending this), ADR-015 (a different
execution provider is a different scorer), ADR-029 (the same wall, on the cross-encoder, and the
amendment that cleared it)
**Evidence:** `runs/session-e-cuda/` — `PREDICTION.md` (committed at `9db08b9`, **before** the
scoring run was launched), `top1-cpu-vs-cuda.json`, `fit-cuda/` (with `BINARY.json` and
`ENVIRONMENT.json`), `bench-idle.txt`, `bench-coexist.txt`, `footprint-{cpu,cuda}.txt`,
`coexist-plan-{1,2,3}model*.txt`. Commit `a619645`.

---

## 1. The decision

> **The embedder's default execution provider is `auto`. `auto` opens CUDA sessions when a CUDA
> session constructs *and* device memory holds one with a whole spare session left over; otherwise
> it runs on CPU at the full requested width. `auto` NEVER fails a run over a busy card. The
> resolved provider — not the request — is announced at startup, and it is in the embedding cache's
> identity.**

Three arms, and each exists for a different reader:

| `--embedder-provider` | behaviour | who it is for |
|---|---|---|
| **`auto`** *(the default)* | GPU where it constructs and fits, CPU otherwise, never an error | the product |
| `cpu` | CPU, whatever the machine has | every number this project published before 2026-08-17 |
| `cuda` | CUDA, and **a hard error if it cannot be had** | measurement, and only measurement |

**`cuda` is deliberately not the default and it is not a tidier spelling of `auto`.** It is the
refusal arm. A measurement cell that silently ran on CPU under a CUDA label is Session G verbatim,
and the only defence against it is a load that fails loudly. Shipping that to a user means a binary
that refuses to launch on a machine whose card is full — ADR-029's *MEASUREMENT-CORRECT and
PRODUCT-WRONG* distinction, applied to the arm this project would most plausibly have picked by
mistake.

**And `auto` is not a hedge.** A shared card is the normal condition here: `llama-server` holds
~11.5 GB of 16.4 GB on this machine, and the loader's width derives from what is free *at that
instant* rather than from a constant. Measured, live, by walking models onto the card:

| free VRAM at load | resolved |
|---|---|
| idle card | CUDA, **8 of 8** sessions |
| 6,267 MB (one model resident) | CUDA, **6 of 8** — *"1509 MB usable would not hold another session plus a spare (793 MB each)"* |
| 1,645 MB (two models) | CUDA, **1 of 8** |
| 1,366 MB (three models) | CUDA, **1 of 8** |

Falling to a narrower GPU embedder is a throughput outcome. Failing the run would be a correctness
outcome imposed for a throughput reason, which is the trade `auto` refuses to make.

---

## 2. Why the reference-fixture failure does not block this, stated precisely

**It is a real failure and it is not being waived.** `embedding-reference.json` is
sentence-transformers / HuggingFace output, and it is the authority on the question *does this build
agree with HuggingFace?* Measured on the shipped graph, one worker, `MAX_SEQ_LEN` 1024:

| provider | median abs diff | max abs diff | `MAX_ABS_DIFF` | min cosine |
|---|---|---|---|---|
| CPU | **1.043e-7** | 1.043e-7 | 1e-4 | — |
| **CUDA** | **3.072e-5** | **1.063e-4** | 1e-4 | **0.99999970** |

CUDA is roughly **500x further from the reference than CPU across the whole distribution**, and its
max is over the tolerance. `the_embedder_reproduces_the_reference_on_cuda_too` records that as a
result, not as a fixture problem.

**What licenses the flip is not that the gap is small. It is that the gap moves no decision, and
that was measured rather than argued.** The fit split, 242 sessions, CPU arm against CUDA arm, same
binary configuration but for the provider:

| | CPU | CUDA |
|---|---|---|
| session-level top-1 | **0.9008** (218/242) | **0.9008** (218/242) |
| identical top-1 pick | — | **242 / 242** |
| gained / lost / net | — | **0 / 0 / 0** |
| McNemar exact, two-sided | — | **p = 1.0** |
| top-10 slate, identical order | — | 239 / 242 (3 reordered, all at ranks 4–10, none at rank 1) |

**And the control is the half that makes that mean anything**, because two runs that were secretly
the same run also report perfect agreement:

| | value |
|---|---|
| candidate rows per dump | 117,890 (identical count) |
| rows whose `dense_cosine` changed | **117,702 of 117,888 shared — 99.84%** |
| rows whose fused `score` changed | 18,583 |
| max abs Δ `dense_cosine` | 8.810e-5 |

`PREDICTION.md` fixed the floor before the run: *"if fewer than 90% of rows move, the run did not
use CUDA and every number in it is vacuous."* 99.84% moved. **Every input to the decision moved and
no decision moved.** `tools/compare_top1.py` is controlled in both directions — run against itself
it prints `VACUOUS -- the inputs did not move`, and run on the unrelated 8192-vs-1024 pair it
reproduces that comparison's numbers to the row.

**The general form, and it is the reason this ADR exists rather than a widened constant:
`MAX_ABS_DIFF` is a proxy. The decision is the property.** A component tolerance is an instrument
for detecting that something moved; it cannot say whether what moved mattered. When the two
disagree, the answer is to measure the property — not to move the instrument until it agrees. This
is ADR-029's amendment, taken a second time, on a second scorer, with the same shape of evidence.

**The three reordered slates are reported rather than rounded away.** ADR-029 measured 0 of 229 for
the cross-encoder; the embedder is noisier at 3 of 242. The perturbation reaches the slate at depth
10 in 1.2% of queries and reaches no winner. A claim of "nothing moved" would have been false.

---

## 3. What this does NOT license

Five things, each of which someone will otherwise read this ADR as granting.

1. **`MAX_ABS_DIFF` is unchanged at 1e-4 and still guards the shipped CPU path.** Nothing here
   widens a tolerance. `CUDA_MAX_ABS_DIFF = 1e-3` in `embedding_reference.rs` remains what its
   comment says it is — **a tripwire around a measurement, not a tolerance**: one order of magnitude
   above the 1.063e-4 observed on 2026-08-17, so that *drift* fails while today's known gap does
   not. Nobody has derived a real CUDA tolerance from the gap between two faithful implementations,
   and rounding up the first number ever measured would be fitting the threshold to the observation.

2. **`embedding-reference.json` is NOT regenerated.** It is HuggingFace's output and it is the
   authority in that direction. Regenerating it on CUDA would delete the only instrument that can
   detect the gap this ADR is reasoning about.

3. **A CUDA number is not comparable to a CPU number — ADR-015 is untouched.** Every published
   figure stays labelled with the provider that produced it. `report.json` records the target string
   verbatim, `retrieval-profile` rows carry the provider, and `tools/score_longmemeval.py` now
   **requires** `--embedder-provider` rather than inheriting a binary default that has just changed
   underneath it: a scoring run that omitted the flag before this commit measured CPU, and after it
   would measure whatever the card had free.

4. **Vectors cannot cross providers.** `EmbedProvider::name()` is in `CacheIdentity`, so a
   CPU-computed vector and a CUDA-computed vector can never share a cache key. Switching providers
   re-embeds; it does not serve one provider's vectors under the other's label. That string is an
   identity, not a display label.

5. **Determinism, batch invariance and padding invariance are NOT inherited across this boundary.**
   ADR-013's standing rule — re-measured per graph, never carried — applies per *provider* for the
   same reason. What has been measured on CUDA is ranking equivalence on the fit split. Anything
   else claimed of the CUDA path needs its own command.

---

## 4. The Session L caveat, restated because it survives this decision intact

**A constructed CUDA session does not mean every node ran on the GPU.** ADR-029 measured **13.6% of
nodes still executing on CPU** — 55,680 of 408,320, all shape and index ops, no matmuls — under a
successfully *registered* CUDA session, and `ort` 2.0.0-rc.10 exposes no node placement at all.

So `EmbedProvider::Cuda` on a loaded `Embedder` licenses exactly one claim: *a CUDA session
constructed and registration was not permitted to fall back silently.* It does not license "this ran
on the GPU". `get_providers()` naming CUDA as **registered** is not a measurement of where nodes
**ran**, and that census was taken once, in Python, on the *rerank* graph, at ORT 1.24.2 — this build
links 1.22. **It has never been taken on the embedder graph at all.** ADR-029's standing obligation
to re-run `tools/session_l_gpu_recovery.py` after any change to the graph, model or ORT version is
inherited here and is still open.

---

## 5. The open risk, named rather than mitigated away

**`auto` resolves against free VRAM at load, so two runs of the same binary on the same machine can
select different providers** — and, on the GPU arm, different widths — depending on what else
started or stopped on the card in between. That is not a bug in `auto`; it is what `auto` means.

Three consequences, and the first two are the reason the design is shaped this way:

- **The provider is REPORTED**, at startup, from the resolved plan rather than from the request:
  `marlowe: embedder asked for auto, running on CUDAExecutionProvider with 8 of 8 worker session(s)`.
  ADR-029's rule — *an unannounced fallback is indistinguishable from the failure mode it
  resembles* — with the request printed beside the resolution so a CPU line is legible as a fallback
  rather than as a configuration.
- **The provider is in the cache key**, so the irreproducibility is confined to *which* scorer ran.
  It cannot become two providers' vectors mixed inside one namespace.
- **`cuda` still exists, and it is the arm every measurement uses.** A reproducible comparison needs
  a provider that cannot drift, which is precisely the arm that errors rather than falling back.
  `--embedder-provider auto` is **not** reproducible across machine states and must never label a
  published number.

**One further defect is inherited and open, from `STATE.md`:** `auto_sessions` swallows the warm-up
failure of its first session, so where the warm-up fails the per-session cost estimate collapses to
the computed floor — roughly 4x too small on a full card — and the loader can open more sessions
than measurement would allow. It is bounded by the one-spare-session rule re-reading the device on
every decision, and by construction failures being caught, which is why the 1,645 MB and 1,366 MB
cases above stopped at one session rather than thrashing. Measured, not fixed, and stated here
because `auto` is now the path that reaches it.

**And a live first-session CPU fallback on this machine remains unmeasured.** The card could not be
squeezed below the first-session threshold with Ollama resident, because Ollama evicts its own
models first. The branch is covered by `Probe::Fixed(0)` in
`embedder_provider.rs::a_zero_vram_budget_falls_back_to_cpu_instead_of_failing_the_run`, which
asserts the run survives with the full requested width on CPU and that the *memory* branch — not the
construction branch — is the one reported. That is a driven test, not a live observation, and the
distinction is recorded rather than blurred.

---

## 6. What it buys, so the trade is on the page

Throughput, `runs/session-e-cuda/bench-idle.txt` and `bench-coexist.txt`, cache OFF on every row,
32 texts per cell:

| tokens | CPU 1 worker | CPU 8 workers | CUDA 1 worker | CUDA 8 workers |
|---|---|---|---|---|
| 102 | 28.90 ms | 4.94 ms | **2.24 ms** | 2.93 ms |
| 502 | 157.42 ms | 29.22 ms | **2.93 ms** | 3.05 ms |
| 1024 | 386.36 ms | 86.93 ms | **4.66 ms** | 4.59 ms |

**~83x against single-worker CPU at `MAX_SEQ_LEN`, ~19x against the 8-worker CPU configuration the
product actually shipped.** With `llama-server` co-resident the CUDA column moves to 2.15–6.77 ms
and the CPU column to 5.15–384.20; the ratio narrows but does not invert.

Cost, `footprint-cuda.txt`: **1,057 MB host peak / 802 MB device for one warmed session at
`MAX_SEQ_LEN`**, growing roughly +550 MB device per additional session. No OOM with `llama-server`
resident at any width the budget permitted.

**Cost accepted:** two numeric paths where one ships and one is measured — the same configuration
ADR-029 accepted, now on the second scorer. The mitigation is that both are measured, the difference
is published, and the provider is on every artifact. Not that the difference is small.

---

## 7. The tests that hold this, and what each would read if it were broken

`cargo test -p marlowe --bin marlowe -- embedder_provider_flag` — **7 tests.** Every mutation below
was RUN, not reasoned about.

| property | test | mutation, and what it read |
|---|---|---|
| the CLI default is `auto` | `embedder_provider_flag::the_default_is_auto` | `Auto` → `Cpu`: **2 FAILED**, *"the embedder default is `auto` (ADR-044)"* |
| `cpu` and `cuda` still reach the loader | `…::the_explicit_arms_still_reach_the_loader` | a default that swallowed the flag → fails |
| an unknown value is refused, not defaulted | `…::an_unknown_value_is_refused_rather_than_defaulted` | a permissive fallthrough → fails |
| the announcement names **both** request and resolution | `…::the_announcement_names_what_was_asked_and_what_was_obtained`, `…::an_explicit_cpu_run_is_distinguishable_from_a_fallback_to_cpu` | drop the request half: **2 FAILED**, *"the REQUEST must be on the line"* |
| the announcement discriminates between providers | `…::an_auto_run_that_got_cuda_reads_differently_from_one_that_got_cpu` | the control: it stays green under the mutation above, which is why it is not the same test |
| `Embedder::load` is still the fixed-CPU constructor | `embedding_reference.rs::the_embedder_reproduces_the_reference_within_a_measured_tolerance` asserts `provider() == Cpu` | `load` → `Auto`: **1 FAILED** on this machine, *"the row labelled `cpu` is measuring something else"*. On a CPU-only box `Auto` resolves to CPU and this passes — stated rather than implied |
| a full card is a fallback, never a failure | `embedder_provider.rs::a_zero_vram_budget_falls_back_to_cpu_instead_of_failing_the_run` | make exhaustion an error → fails |
| the scorer cannot publish an unlabelled provider | `python tools/score_longmemeval.py` without `--embedder-provider` exits 2 | restore the pass-through default → the refusal disappears |

**The unit tests assert what the source formats. They are the weaker claim.** The stronger one is
the running binary's own startup line, read from `target/release/marlowe.exe` after checking its
mtime against the source change — `cargo run --example` builds a different binary and has already
mislabelled one run in this project. Taken on `target/release/marlowe.exe`, built 22:00:23 against
sources last touched 21:57:27, **with no `--embedder-provider` flag on the command line at all**:

```
marlowe: embedder asked for auto, running on CUDAExecutionProvider with 8 of 8 worker session(s)
         -- CUDA, all 8 requested sessions opened
```

**And the control, because one line that says CUDA is not evidence that anything chose it.** Same
binary, same command, `MARLOWE_CUDA_LIB_DIR` unset:

```
marlowe: embedder asked for auto, running on CPUExecutionProvider with 8 of 8 worker session(s)
         -- a CUDA session did not construct: ... "cublasLt64_12.dll" ... (Error 126)
```

**A third reading is what the announcement change is FOR.** `--embedder-provider cpu`, same machine,
CUDA available, reads *"asked for cpu, running on CPUExecutionProvider — CPU was asked for
explicitly"*. Two of these three runs end on CPU, and before this commit they printed the same
words. One is a configuration and one is a fallback; a reader can now tell which.

Artifacts: `runs/session-e-cuda-adr044/live-default.txt`, `live-control-unset.txt`,
`live-control-explicit-cpu.txt`.
