# Spike — cross-encoder rerank, 2026-08-04

**Result: FAIL on latency, at both pre-registered configurations. The reranker is NOT ADOPTED at
M0b.** Determinism passed perfectly and is worth keeping on the record for whoever revisits this.

The bar was **registered before the spike ran** — `runs/session-e/PREREGISTRATION.json` →
`cross_encoder_spike` — and the spike script reads it from that file rather than restating it, so a
moved bar would show up as a diff. Raw numbers in `runs/session-e/cross-encoder-spike.json`.

## Why it was tried

Session E's floor failure is an **arbitration** failure. Every cue scores a memory in isolation and
the gate compares isolated opinions, which bounds top-1 at the either-cue oracle of **0.652**. A
cross-encoder reads query and candidate **together in one pass**, so its top-1 ceiling is the recall
of the pool it reranks rather than the oracle — the only named shape that could exceed the bound
Session E was judged against.

## What was measured

`Xenova/ms-marco-MiniLM-L-6-v2`, a **maintainer-published ONNX export**, pinned by sha256:

| file | sha256 | bytes |
|---|---|---|
| `model.onnx` | `c623d0bcb99f4622beb413eaef00cfbe5db20df9f1dd982da4b4f26022881870` | 90,992,115 |
| `tokenizer.json` | `d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66` | 711,396 |

Chosen deliberately over exporting one ourselves: STATE.md carries an open gap that our jina export
is not independently validated against the published model, because `transformers.onnx` was removed
in transformers 5.x. Exporting a second model here would have acquired a **second instance of that
gap**.

Pairs are **real LongMemEval text** — 40 held-out queries × 20 turns from their own sessions —
because sequence length is the whole question.

### Determinism — PASS, all three, exactly

| check | result | max abs diff |
|---|---|---|
| batch 1 vs batch 20 | **PASS** | `0.000e+00` |
| 1 thread vs 4 threads | **PASS** | `0.000e+00` |
| two separate processes | **PASS** | `0.000e+00` |

Batch-size invariance was the one expected to fail — batching changes reduction order inside the
graph — and it did not. Worth recording: a future attempt does not need to give up batching, and
**multi-threading is licensed for this graph**.

### Latency — FAIL, with room to spare in the wrong direction

Budget is §5.7's **total cold retrieval P95 ≤ 300 ms**, with Session E's measured 34 ms cold
(reranker absent) as the base the stage adds to.

| seq len | threads | stage P95 | projected total | speedup vs 1 thread | speedup **needed** | passes |
|---|---|---|---|---|---|---|
| 512 | 1 | 2583 ms | 2617 ms | — | — | ✗ |
| 512 | 16 | 1054 ms | 1088 ms | 2.45× | **9.71×** | ✗ |
| 256 | 1 | 1102 ms | 1136 ms | — | — | ✗ |
| **256** | **16** | **331 ms** | **365 ms** | 3.33× | **4.14×** | **✗** |

Truncation: **19.0%** of pairs at 512, **37.8%** at 256.

**The closest configuration misses by 65 ms, and the honest reading is worse than that**, for three
reasons stated together because any one alone would be misleading:

1. **16 threads is a workstation, not the deployment target.** ADR-003 sizes against a 1-vCPU VPS.
   The single-thread figure — **1136 ms at seq 256** — is the one closer to deployment.
2. **The total is a SUM of two separately measured spans**, not an end-to-end measurement. It omits
   whatever the integration itself costs, so it is optimistic by construction and is labelled as an
   estimate everywhere it appears.
3. **37.8% truncation at 256** means more than a third of pairs did not fit, so that configuration is
   already scoring on partial evidence before any quality number is taken.

## The verdict, as registered

> *"If L-6 at `max_seq_len` 512 misses the latency bar, the single pre-registered fallback is
> `max_seq_len` 256 with the truncation rate measured and reported. If that also misses, **the
> reranker is not adopted at M0b** — no third attempt, because a ladder chosen after seeing the
> number is tuning."*

Both configurations missed. **Not adopted at M0b.**

### One correction to the spike's own method

The first run pinned threads to 1, inheriting `embedder.rs`'s convention. **That was never a
registered constraint** — the registered latency condition says nothing about thread count, and the
registered *determinism* check had just licensed multi-threading for this graph. Reporting a FAIL
against a constraint the spike itself introduced would have been reporting a failure the
pre-registration did not require, so the assumption was removed and the multi-thread number
measured.

It was measured **once, at the machine's core count** — not swept upward until something passed.
That distinction is the whole difference between removing an unregistered assumption and extending
the fallback ladder, and the ladder was not extended.

## What a future attempt would have to pre-register first

Named here so they are not chosen with this failure in view, and **none of them was tried**:

- **A smaller or quantized encoder** — int8, or L-2/L-4 instead of L-6. The needed speedup at seq
  256 is 4.14× single-thread-equivalent, which is roughly the right order for int8 plus a shallower
  model, so this is the one with a plausible path.
- **Rerank fewer than 20.** Linear in N, and N was itself a registered choice.
- **A conditional stage** — rerank only when the gate is uncertain. This changes the latency profile
  from per-query to per-uncertain-query and is the only option that does not trade quality for
  speed. It also introduces a firing predicate, which is the objection that has already pinned
  `cue_agreement_2cue` twice; it would need that predicate pre-registered.

**What must not happen** is trying these until one passes and reporting the winner. Each is a
separate pre-registered experiment with its own bar, or none of them is.

## Consequence for the roadmap

The named lever order in Session E's pre-registration was **cross-encoder, then consolidation**. The
cross-encoder is now ruled out at M0b **on cost, not on quality** — its quality was never measured,
and that distinction matters: nothing here says a cross-encoder would not have worked, only that
this one cannot run inside §5.7's budget on this hardware.

So **consolidation is the next lever**: ~493 raw turns per case with near-duplicates competing
against gold is the candidate-pool problem, and it is the one remaining named cause of the
54.8% / 31% gap that Session E did not close. Cues 3–5 remain deferred, unchanged and for the
unchanged reason.
