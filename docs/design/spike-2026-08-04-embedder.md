# Spike — ONNX inference engine for the dense cue

**Date:** 2026-08-04 · **Milestone:** M0b Session C · **Decides:** ADR-004's unnamed runtime

ADR-004 says "local ONNX small model, 384 dimensions" and **names no inference engine**. That
gap matters more here than it looks: `marlowe-eval repro` hashes the injected set byte for byte,
so anything that can change an embedding can change a published number.

The concern was stated before measuring, and it is Session B's own argument against SQLite FTS5
transplanted one layer down:

> FTS5's `bm25()` ranking is a property of the *bundled SQLite version*, so a dependency bump
> could change a published number with nothing in this repo changing.

## Method

**The gates were written down first**, in `runs/session-c/PREREGISTRATION.json` under
`engine_gate`, before either engine was built:

| Gate | Condition | Why that number |
|---|---|---|
| throughput | ≥ 25 texts/s per core, single-threaded, at `MAX_SEQ_LEN` | ~494k turn-embeddings across the session's three real-corpus passes; at 25/s/core with 8 workers that is ~41 min for a full fit-and-score cycle. A cue whose re-fit cannot run twice in a session cannot be iterated on. |
| latency | retrieval P95 ≤ 120 ms | 40% of §5.7's 300 ms budget, leaving 180 ms for cues 3–5, fusion and ADR-003's hot index. Two of five cues may not take more than 40%. |
| op coverage | loads the pinned `model.onnx` and reproduces the committed reference embeddings | Failing to load is a fail regardless of speed. |
| determinism | byte-identical across two calls, two process spawns, and worker counts 1 / 2 / 8 | This is what `repro` depends on. |

**Decision rule, also pre-committed:** tract if it clears all four; otherwise ort with threads
pinned to 1, sequential execution, a pinned graph-optimization level, and the ORT version plus
model digest carried into the gate artifact as load-time checks.

**Measured on** the real corpus: 1,000 turns drawn by deterministic stride from LongMemEval-S
(cleaned), so the length distribution is the corpus's own — median 96 word pieces, 75th
percentile 380. A synthetic short string would have measured the wrong thing entirely. Queries
are the corpus's own 100 shortest-sorted questions. Machine: 16 logical cores, Windows 11, MSVC.

**Parallelism is at the text level, never inside the model.** Each forward pass runs
single-threaded on one worker; results are reassembled by input index. That makes worker-count
invariance structural rather than hoped-for — and the spike measured it anyway.

**tract was given symbolic sequence length, not padding to 256.** Chosen *before* measuring, to
be fair to it: padding every text to `MAX_SEQ_LEN` would roughly triple its work, since the
median turn is 96 word pieces against a 256 limit. Judging an engine on a configuration chosen
to disadvantage it would not be a measurement.

## Result

| engine | loads | load ms | max abs diff vs reference | min cosine | texts/s/core | query P50 | query P95 | identical across calls | across spawns | across 1/2/8 workers |
|---|---|---|---|---|---|---|---|---|---|---|
| **tract 0.23.4** | yes | 163 | 3.42e-7 | 0.99999994 | **21.8** | 6.4 ms | 10.5 ms | yes | yes | yes |
| **ort 2.0.0-rc.10** | yes | 248 | 2.68e-7 | 1.00000000 | **45.7** | 4.3 ms | 6.9 ms | yes | yes | yes |

Digests, for the record — identical within an engine across every spawn and worker count, and
different between engines, which is the expected shape:

```
tract  38f1b2b28ce25699    ort  26dba779b1da8175
```

**Both engines are fully deterministic. Throughput is the only thing that separates them.**

- **tract fails the throughput gate: 21.8 texts/s/core against a pre-committed 25.** It misses
  by 13%. It passes every other gate, and its reference agreement (3.42e-7) is comfortably
  inside the tolerance floor established by the ONNX export itself (2.35e-7 between
  sentence-transformers and onnxruntime on the same file).
- **ort passes every gate**, at 2.1× tract's throughput.

## Decision: ort, by the pre-committed rule

tract failed a gate, so the rule selects ort. **The gate was not revisited after seeing 21.8.**
Re-tuning a tract configuration to squeak past a threshold it had already missed would be
optimizing against the gate, which is the thing pre-committing it exists to prevent.

Configuration, per the rule: `intra_op_num_threads = 1`, `inter_op_num_threads = 1`,
`GraphOptimizationLevel::Level1` pinned explicitly rather than left at the version's default.

### The version-dependence worry turned out to be smaller than stated, and here is why

The pre-registration accepted ort as a fallback on the grounds that *"ORT's numerics are a
property of a version that can be pinned into the artifact and checked at load"* — weaker than
determinism-by-construction, but recordable. Inspecting what actually ships strengthens that:

| Link | How it is pinned |
|---|---|
| `ort` crate | `=2.0.0-rc.10` — exact, not a caret range |
| `ort-sys` | checksum in `Cargo.lock`, which this repo tracks |
| **ONNX Runtime binary** | `ort-sys`'s `dist.txt` pins **ONNX Runtime 1.22.0** with a **SHA256 per target** (`540D19B3…FE190D` for `x86_64-pc-windows-msvc`) |
| linkage | **statically linked** into the binary — no loose `onnxruntime.dll` beside the executable to be swapped |

So the chain from `Cargo.lock` to the machine code that computes an embedding is digest-pinned
end to end. That is a genuinely different situation from FTS5, where the ranking function's
behaviour rode on whatever SQLite the build happened to bundle, with nothing recording it.

### What is being given up, stated plainly

1. **ort has no stable release.** `2.0.0-rc.13` is the newest; there has never been a `2.0.0`.
   Pinned with `=` so a new rc cannot arrive silently, but a pre-1.0 dependency on the measured
   path is a real cost.
2. **Determinism is measured, not structural.** tract has no thread pool and no runtime kernel
   dispatch; ort has both, and what makes it safe here is that threads are pinned to 1 and the
   invariance was *measured*. A future change that let the thread count vary would break the
   property silently. The mitigation is the standing test, not the configuration.
3. **Cross-hardware bit-identity is not claimed by either engine**, and no tolerance window is
   introduced to paper over it. ORT's CPU dispatch selects kernels by CPU feature set, so a
   different machine may differ in the last bits. The claim this repo makes is same-binary,
   same-machine — which is what `repro` tests.
4. **A 46 MB binary.** ONNX Runtime statically linked is most of it.

### When to revisit — recorded now, so it is not re-derived later

tract remains viable and missed by 13%. Revisit if any of these becomes true:

- an embedding cache lands, making ingest throughput largely irrelevant and leaving only the
  6–10 ms query path, where tract already passes comfortably;
- ort's pre-1.0 status becomes a problem (a yanked rc, an unfixed soundness bug);
- the deployment target changes to one where a 46 MB static link or a CDN build-time download is
  unacceptable — note ADR-003's VPS target.

The spike crate `crates/marlowe-embed-spike` is **deleted** once ADR-004 is amended; re-running
this comparison means restoring it from this commit. Its numbers are here so that is rarely
necessary.

## Byproduct worth carrying forward

The ONNX export in `models/` is faithful to the published model: **max abs diff 2.35e-7, min
cosine 0.99999994** against `sentence-transformers` on the same 40 texts. That number is the
floor for any Rust-vs-reference tolerance — a tolerance tighter than the gap between two
faithful implementations of the same graph would fail an implementation for being correct.
