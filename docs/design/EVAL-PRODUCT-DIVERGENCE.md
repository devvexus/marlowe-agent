# The benchmark measures a system the product is not

**Established 2026-08-17. Every claim below was verified by grep at the time of writing, and the
command is given so you can re-verify rather than trust this file.**

Three components have been found where the **eval path** and the **shipped daemon** have come apart.
Each was found separately, chasing something else. Three is a pattern rather than a coincidence, and
naming it is the point of this document.

## What this does NOT say

It does **not** say the measurements are wrong. R@1 0.6725, the precision/coverage curve, the
embedder's throughput, the GPU work — all correct, all reproducible, all about the eval adapter.

It says: **a quality or security claim must name which path it describes**, because the two are no
longer the same system, and the numbers have been carrying the product's name.

## The three

### 1. `ingest` has exactly one caller, and it is the eval adapter

```
grep -rn "\bingest(" crates/ --include=*.rs | grep -v "fn ingest" | grep -v "/tests/"
```

One hit: `crates/marlowe/src/adapter.rs:304`, inside `--eval-adapter`.

```
grep -rc "Channel::" crates/marlowe-daemon/src/*.rs
```

Zero. The daemon never names a channel, so it never ingests.

### 2. Layer 3's trust latch cannot fire in the shipped daemon

A consequence of (1) rather than a separate defect. After ADR-041, no tool result can taint a parent;
the only remaining source of `UntrustedContent` in a run's own window is **injected memory**. A
belief is `UntrustedContent` only from `ingest` — or from `remember_claim` with an already-bottomed
floor, which is circular. With `ingest` unreachable from the daemon, the latch has no live trigger.

**Not broken — unreachable.** CLAUDE.md carried the claim *"layer 3 is still reachable and
non-vacuous"* and it was corrected in place: true of the test surface and of the eval adapter, false
of the product.

### 3. The daemon loads no embedder at all

```
grep -rn "Embedder" crates/marlowe-daemon/src/
```

Zero references. The one production call site is `crates/marlowe/src/main.rs:657`, inside
`--eval-adapter`.

**So every embedder number this project has published describes the benchmark path.** That includes
the 8.6 GB ALiBi finding, the 23× reduction from `MAX_SEQ_LEN`, ADR-044's GPU flip, and the ~50×
CUDA speedup. All real; none of them describes what `marlowe --serve` does, because it does not
embed.

It also explains the daemon's 70 ms cold start: there is no model to load.

## The counter-example, which bounds the claim — added 2026-08-18

**The reranker is NOT divergent, and saying so matters as much as the three above.** The daemon
constructs a `CrossEncoder` (`crates/marlowe-daemon/src/memory.rs:93`, loaded at `:120`), and on a
running daemon it resolves to **CUDA** under ADR-045's `auto`. So this is not "the memory stack is
eval-only". It is three specific components, and a reader who generalises past them will be wrong.

**What the product's retrieval actually is, in the code's own words** (`memory.rs:94-98`):

> *"**Empty, and that is a stated limitation rather than an oversight.** The dense cue scores 0.0 for
> every candidate without vectors, so retrieval here is **lexical + rerank**. Embedding at write time
> is the next increment; `dense_for` already treats a missing vector as 0.0 — the honest value —
> rather than skipping the candidate, so the degradation is uniform and visible rather than a
> silently shrinking candidate set."*

That is the divergence stated precisely and **already declared at the site**, by whoever wrote it,
before anyone went looking. The daemon runs **lexical + rerank**; the benchmark runs **lexical +
dense + rerank**. Every retrieval number this project has published — R@1 0.6725 included — was
measured with a dense cue the product does not have.

**So the correction to §3 is not that the daemon lacks an embedder — it is what that costs.** The
missing embedder is not an absent optimisation; it is an absent *cue*, and the published quality
figures describe a two-cue system where the product has one plus a reranker. The degradation is
uniform rather than a shrinking candidate set, which is the right design, and it is still a
different system.

## Why this shape keeps happening

The eval adapter and the daemon are **two independent front ends over the same crates**, and only one
of them is measured. `marlowe_eval` drives the adapter; nothing drives the daemon except a human
using it. So a capability can be built, tested, benchmarked and documented while the product never
reaches it — and every instrument in the project reports success, because every instrument points at
the adapter.

This is the project's standing failure family at the level of the architecture: *a measurement that
answers a question adjacent to the one being asked, and the adjacent answer looks authoritative.*

## The check that catches the next one

For any component carrying a published number, one command:

```
grep -rn "<ComponentType>" crates/marlowe-daemon/src/
```

**If it returns nothing, the number is about the eval path.** Say so wherever the number is quoted.

Generalised: *for every capability with a measurement attached, ask whether `marlowe-daemon` reaches
it.* Thirty seconds, and it is the whole check.

## What is not proposed here

**Fixing the divergence is milestone work and is deliberately not proposed.** Wiring `ingest` into
the product has a stated prerequisite — the compaction stamp (E5) and the trim marker (F1) must be
fixed **first**, or layer 3 goes live together with two known defects in the same path. Wiring the
daemon to the embedder is a retrieval decision, not a plumbing one.

This document names the pattern. Acting on it needs a milestone and an owner.
