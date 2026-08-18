# ADR-045 — The reranker defaults to `auto`

**Status:** ACCEPTED. `--rerank-provider` defaults to `auto`.
**Mirrors:** ADR-044 (the embedder, same construction — read that first)
**Depends on:** ADR-015 (a different execution provider is a different scorer), ADR-029

## 1. The decision

`--rerank-provider` defaults to **`auto`**: CUDA when a session constructs and device memory allows,
CPU otherwise. Not `cuda`. The refusing arm is measurement-correct and product-wrong — a research
run must not die because the card is busy.

This closes a disagreement that stood for months: **ADR-029 put the rerank on CUDA and the default
was `cpu`.** The document and the code said different things and nothing reconciled them.

## 2. The governing principle, in the human's words

> *"Everything GPU if it has space for it, CPU otherwise."*

Stated verbatim because an earlier draft of this work paraphrased it as *"leave it on CPU where it is
already inside its latency budget"* — and that is **wrong**. The reranker runs at 182 ms p50 against
a 300 ms budget, so a budget-gated rule would have left it on CPU forever. Being fast enough is not
a reason to decline free speed. **Space is the gate; the budget is reporting.**

## 3. Why ADR-029's numbers do not license this and a fresh measurement was required

Every rejection figure in this project's history was a 1-thread CPU number read against a GPU
target, and STATE.md records that error being made in *both* directions. ADR-029's numbers are
evidence about ADR-029's configuration. Three gates were measured here instead, and **all three had
to pass or the default would not have moved.**

### Gate 2 — the reference fixture on CUDA. PASSES.

`cross_encoder_reference` verifies on CUDA, worst observed delta **~0.00104** logits. **The fixture
was not regenerated** — it is derived from the published pipeline as the authority, and rewriting it
to match our implementation would make the implementation trivially correct.

### Gate 3 — batch invariance on CUDA. PASSES.

Sizes 1..10 on the shipped f32 graph: `max |batched − single|` = **0.000349** (worst at batch 9),
**zero order changes**. ADR-015's rule is that invariance is re-measured per graph *and per
configuration* and never inherited, so the CPU reading licensed nothing here.

The check carries its own control — `the_batch_invariance_check_can_actually_see_a_reordering` —
because a reorder detector that cannot detect a reorder reports zero either way.

### Gate 1 — does CUDA change which memory ranks first. PASSES.

**Zero top-1 changes**, over 120 queries and **1,200 pairs**, against a completed dump.

| | |
|---|---|
| pairs scored on both providers | **1,200** |
| max abs delta, logits | **0.001260757** |
| queries with any reorder deeper in the list | **2** |
| **queries whose top-1 changed** | **0** |

The verdict rule was fixed before the run: *zero top-1 changes → flip; any change → do not.*

**Why this was not a scoring run.** The obvious method is to score the fit split twice. That is two
full passes, and an earlier attempt at exactly that was killed and left a **0-byte**
`scored-candidates.ndjson` — worse than no attempt, because a zero-byte file in a results directory
reads like a result. The reranker is a **pure function of `(query, document) → logit`**, so scoring
real pairs directly on both providers answers the same question in minutes. See
`examples/rerank_gate1.rs`.

**The two reorders are the expected shape, not a warning.** A 0.0013-logit deviation can only flip
pairs separated by less than that. STATE.md's near-tie signature records that post-hoc mechanisms on
this corpus gain cases almost entirely inside gaps below **0.084** — two orders of magnitude wider.
So deep near-ties move and the head does not, which is what the numbers show.

## 4. The near-miss, recorded because it is the more useful half

**The first run of `rerank_gate1` printed a clean `PASS — 0 flips, max |delta| 0.000000000`.** It was
vacuous. It requested batches of 12, `score_batch` **correctly refused every one** — invariance on
this graph is measured only to 10, and extrapolating past measured sizes is the inherited-measurement
error this project has paid for four times — and the delta was therefore computed over **zero
comparisons**. The empty `worst:` field was the only tell.

Both controls in place at the time passed: the arms *were* different providers, and the flip detector
*did* work. **Neither could see that nothing had been scored.** A third control now asserts pairs
were actually compared and exits `VACUOUS` if not.

The general form, for the next measurement: *a control proves the instrument can detect a difference;
it does not prove the instrument was ever pointed at anything.*

## 5. What this does not license

- **`MAX_BATCH` stays 10.** Gate 3 measured 1..10; a larger batch is refused rather than run, and
  that refusal is what caught §4.
- **The reference fixture is not regenerated** and its tolerance is not widened.
- **A CUDA number is not comparable to a CPU number** (ADR-015). Every published figure keeps naming
  the provider that produced it.
- **`auto` resolves against free VRAM at load**, so two runs on one machine can pick different
  providers. That is why the resolved provider is announced rather than the requested one, and why
  explicit `cuda` — fail loudly — still exists for measurement.
- **CUDA needs `MARLOWE_CUDA_LIB_DIR`.** No CUDA Toolkit is required; torch's bundled runtime
  suffices. Unset, `auto` silently and correctly resolves to CPU.

## 6. Device cost, and why memory was never the blocker

**341 MB** at `MAX_BATCH`, warmed. Against a card holding a 9B at ~6.6 GB, the reranker is noise.
The open question this ADR does **not** answer is the reserve: `auto` reads free memory at load and
takes what is there, which on a shared card can squat on memory belonging to the language model.
That is recorded in STATE.md as the tier list and is deferred, not solved.
