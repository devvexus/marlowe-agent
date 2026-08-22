# ADR-046 — The GPU cascade ships: depth 30, narrowed by the shipped graph, fused with a second opinion

Date: 2026-08-22 · Status: **Accepted** · Owner: M0c Session N

## Context

`RerankPlan::{Shipped, Cascade}`, `CASCADE_SLATE = 30`, `CASCADE_NARROW = 10`, `RRF_K = 60`,
`FUSION_GRAPHS` and `ScoredCandidate::fusion_rank` have existed since M0c Session M2 — with **no
call site**. The configuration they describe was pre-registered
(`runs/session-m0c-m/PREREGISTRATION-CASCADE-HELDOUT.json`) and measured held-out:
**R@1 0.6987 / R@3 0.8865** against the shipped path's 0.6725 / 0.8515 (R@3 +0.0350, McNemar
10 gained / 2 lost, p = 0.0386). It could not run on CPU at the shipped pins (p50 1134 ms against
§5.7's 300 ms), which is why the scaffolding sat behind an explicit "NOT WIRED" warning rather
than being quietly enabled.

Four blockers were named in the code. This ADR records how each closed:

1. *Single `MODEL_SHA256` pin.* Already solved: `FUSION_GRAPHS` digest-pins every member and
   `CrossEncoder::load_fusion_member` refuses any name outside it. No caller-supplied digest
   exists; there is no second way to load either graph.
2. *`Rerank` held one encoder.* `Rerank::Cascade { encoder, fuse, batched }` now carries both.
3. *`MAX_BATCH = 10` vs a 30-wide slate.* Chunking: batched scoring never exceeds the measured
   envelope; provider equivalence was then MEASURED (G3 below), not assumed.
4. *Missing L-6 fixture.* Generated from HuggingFace (`cross-encoder-reference-ft-session-j-L6.json`)
   and enforced by a Rust test through `load_fusion_member`, plus per-graph batch-invariance —
   never inherited from the shipped graph.

## Decision

1. **Wire the cascade.** `RerankPlan::select(cuda_constructed)` gains its call site: Cascade runs
   iff the primary cross-encoder **resolved** to CUDA (construction-proven via
   `error_on_failure()`, never an availability list) **and** the fusion member loaded. Everything
   else keeps the shipped depth-10 shape, bit-identically.
2. **`auto` is the default and keys on the RESOLVED provider**, because the cascade is GPU-only by
   measurement. `--rerank-plan shipped|cascade` are the explicit measurement arms. An explicit
   cascade without `--reranking <DIR>` refuses at parse; a plan/encoder mismatch refuses at start
   in BOTH directions (Cascade without both graphs; Shipped holding an unread fusion graph).
3. **Announce and stamp.** The plan prints its own startup line (`rerank plan …`) and lands on
   every `retrieval-profile.ndjson` row as `rerank_plan`. The dump gains `fusion_rank` (`null`
   when absent) so a driver can reproduce the fused order from the binary's own bytes.
4. **The fusion is ranks, not scores.** RRF over the two rankings of the narrowed ten, ties by
   candidate index ascending — replicating the offline tool exactly, where adjacent swaps are
   EXACT ties and the tie-break decides real cases. Unit tests pin the arithmetic and both
   tie-breaks.

## Verification (all taken this session, on the wired binary)

| check | result |
|---|---|
| fit + held-out controls, pinned CPU | 0.7555 / 0.6725 EXACT — the shipped path is untouched |
| cascade on fit vs offline artifact | 180/229 and 213/229 EXACT |
| **G3: CUDA vs CPU case counts, cascade** | **zero movement** (chunked batches are decision-equivalent) |
| held-out reproduction | 160/229, 203/229 EXACT, replicated across independent spawns |
| latency | end-to-end P95 **29.4 ms** on CUDA (budget 300); one first-query warm-up spike ~600 ms, disclosed |
| suite | see `runs/session-m0c-n/suite.txt` |

## Consequences

* GPU deployments inject from a strictly better measured configuration; CPU-pinned published
  numbers do not move. `repro` across differing card states can now differ by PLAN — the same
  caveat `auto` providers already carry, and pinned-CPU targets remain the reproducible setting.
* **Debt, recorded not silently absorbed:** the operating point's margin stays in shipped-graph
  logit units while the head order is now a fusion; its distribution under fusion differs, of the
  same class as the `ADMIT_TOP_K = 3` debt already recorded in `retrieve.rs`.
* Held-out narrowing retention measures **0.9777 (5 cases)**, materially worse than fit's 0.9956 —
  the narrowing step is the newest weak link and is explicitly fair game for the next registered
  probe.
* Supersedes nothing; implements what `RerankPlan`'s own doc always described. The warning
  "NOT WIRED — nothing reads this" is now false and has been removed by the wiring itself.
