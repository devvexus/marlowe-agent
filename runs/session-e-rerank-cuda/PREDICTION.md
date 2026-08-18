# PREDICTION — the reranker on CUDA, registered before the runs that judge it

**Written 2026-08-17, and committed before the scoring runs were launched.** Same discipline as
`runs/session-e-cuda/PREDICTION.md` (committed at `9db08b9`), for the same reason: a threshold
chosen after seeing a number is not a threshold.

The question is whether `--rerank-provider` should default to `auto` — GPU where a CUDA session
constructs and device memory allows, CPU otherwise — mirroring ADR-044's flip of
`--embedder-provider`. Today it defaults to `cpu`, which contradicts ADR-029's own headline
sentence (*"where a CUDA device is available the rerank runs on it"*).

---

## The governing principle, stated first because it decides what counts as evidence

The human's principle for this whole class of decision:

> *"Everything should be default GPU and as low memory as possible, but we leave it on CPU for
> cases where it's already fast."*

**So the deciding number is NOT the speedup.** It is (a) whether the component is already inside
its budget, and (b) what moving it costs in memory. A 50× speedup on a stage that already fits is
not an argument; a stage that eats its whole budget is, even at 3×.

**And ADR-029's old numbers are not admissible as the justification.** Every rejection figure in
this project's history was a 1-thread CPU number read against a GPU target, and `STATE.md` records
that error being made in BOTH directions — Session K's *"batching buys nothing here"* was correct
and was retired on a profile; Session L's threading result was a +158.9 ms regression that a
citation would have hidden. The measurements below are taken on this machine, this week, on this
binary.

---

## What is predicted

### 1. Ranking A/B on the fit split — 242 queries

Two arms of `tools/score_longmemeval.py --fit-only`, identical but for `--rerank-provider`, with
`--embedder-provider cpu` **pinned on both** so the embedder cannot move underneath the comparison.

| | prediction |
|---|---|
| identical top-1 pick | **242 / 242** |
| gained / lost / net | **0 / 0 / 0** |
| McNemar exact two-sided | **p = 1.0** |
| top-10 slate, identical order | ≥ 239 / 242 |

**Basis, and it is a prior rather than an inheritance.** ADR-029 measured 0 of 229 held-out slates
reordered on the int8 graph at ORT 1.24.2 in a different build. That is a *different system* — the
shipped graph is now the Session J f32 fine-tune and this build links ORT 1.22 — so it is the
reason to expect agreement, not the evidence for it.

### 2. THE CONTROL, and it is mandatory — the run is thrown away without it

> **If fewer than 90% of the rows that carry a `rerank_score` change it, the CUDA arm did not run
> on CUDA and every number in this comparison is vacuous.**

The fit split produces **117,890** candidate rows, of which exactly **2,420** carry a
`rerank_score` — 10 per query, the survivors of pruning. The other 115,470 are `null` and are
untouched by this treatment, so a control computed over all rows would read ~2% and mean nothing.
**The control is over the 2,420 reranked rows only.**

**A second control runs in the opposite direction:** `dense_cosine` must change on **0** rows,
because the embedder is pinned to `cpu` on both arms. A non-zero reading there means something
other than the reranker moved and the comparison is confounded.

`tools/compare_top1.py`'s existing `control_reading` keys on `dense_cosine`, which is the right
field for an *embedder* comparison and the wrong one here — it would print `VACUOUS` on a perfectly
valid reranker A/B. The control field is therefore being made an explicit required argument rather
than a default, for the same reason `--reranking` and `--embedder-provider` are required: a default
control field lets a comparison be judged by an instrument pointed at a different component.

### 3. The reference fixture on CUDA — `cross-encoder-reference-ft-session-j.json`

**Prediction: CUDA does NOT reproduce the CPU reference within `LOGIT_TOLERANCE = 1e-3` with
certainty, and a failure is a RESULT rather than a nuisance.** ADR-029 measured the cross-provider
logit delta at median **0.000237**, p95 **0.000824**, max **0.002182** over 2,290 held-out pairs —
so the max is already over 1e-3 on a population 280× larger than this 8-case fixture. Whether these
particular 8 cases land under the line is close to a coin toss.

**Registered in advance, so the outcome cannot be reasoned into afterwards:**

- The fixture is **NOT regenerated**. It is HuggingFace/ONNX-Runtime-Python output on a pinned
  graph and it is the authority on *does this build agree with the reference?*
- `LOGIT_TOLERANCE` is **NOT widened**. It guards the shipped CPU path.
- A CUDA case over the line is recorded as a measured gap. **The decision is settled by §1's
  ranking A/B, not by this tolerance** — ADR-044's rule, taken a second time: a component tolerance
  is an instrument for detecting that something moved, and cannot say whether what moved mattered.

### 4. Batch invariance on CUDA — UNMEASURED, and this is the one that can block the flip

`MAX_BATCH = 10`. `runs/session-l/batch-invariance-batch10.json` swept 1..10 at max |delta|
**0.000000000** — **on CPU**. ADR-015's standing rule is that invariance is re-measured **per graph
and per configuration** and never inherited, and a different execution provider is a different
scorer. **A GPU has never been measured here at all.**

**Prediction: CUDA is NOT bit-identical across batch sizes.** cuBLAS selects a GEMM kernel by
problem shape, so a batch of 1 and a batch of 10 can take different tilings and therefore different
reduction orders. Expected magnitude ≲ 1e-3 logits, of the same order as the cross-provider delta.

**The decision rule, fixed now:**

| reading | verdict |
|---|---|
| any **order change** or **top-1 change** within a slate across batch sizes 1..10 | **DO NOT FLIP.** Report it. |
| numerical delta only, zero order changes, zero top-1 changes | flip, and publish the delta rather than claiming `0.000000000` |
| bit-identical | flip, and say the CPU reading reproduced |

**And it is not permitted to claim CPU's `0.000000000` for the GPU path under any outcome.**

### 5. `MAX_SEQ_LEN` / shape binding

ADR-015's `[1, 256]` shape-binding hazard was a **quantization** property, and the shipped graph
has been f32 since Session K — Session K re-measured padding invariance at **0.000000** on f32.
**Prediction: no shape-binding effect on CUDA either.** Verified rather than inherited: the batch
sweep varies the batch dimension on the shipped f32 graph directly.

### 6. The component table — what the memory figures are expected to be

| component | expected device peak | basis |
|---|---|---|
| embedder, one CUDA session at `MAX_SEQ_LEN` 1024 | ~800 MB | measured 802 MB, `runs/session-e-cuda/footprint-cuda.txt` |
| **reranker, one CUDA session at `MAX_SEQ_LEN` 256, `MAX_BATCH` 10** | **under 400 MB, and most of it ORT's arena rather than the graph** | the graph is ~17 MB f32; activations at `[10, 256]` on a 2-layer 384-wide MiniLM are single-digit MB |

**The reranker is predicted to be the CHEAP one**, which is the half of the human's principle that
decides it. If the reranker's device cost lands anywhere near the embedder's 802 MB, that is a
finding and it weakens the case for the flip on a shared card.

### 7. The budget question, which is the actual decision

Session L measured the shipped CPU path at **rerank p50 187.6 ms**, **total retrieval p50 208.0 /
p95 220.2 ms** against §5.7's **300 ms P95** cap.

**So the CPU reranker is already INSIDE its own budget** — and that is exactly the case the human's
principle says to leave alone. The counter-argument, and it has to be made explicitly rather than
assumed:

- the rerank is **90.49%** of the retrieval P95 — it is not a stage among stages, it is the budget;
- §5.7's 300 ms exists so retrieval fits inside brief §9's **800 ms voice-to-voice**, where 220 ms
  is **27.5%** of the whole conversational budget before a token is generated;
- ADR-029 already decided this, on that argument, and the shipped default has silently disagreed
  with its own ADR since.

**Predicted verdict: FLIP** — on the grounds that the component is inside §5.7 but consumes 90% of
it and 27% of §9, and that the memory price is small. **If the measured device cost is large, the
principle says leave it on CPU and the prediction is wrong.**

---

## What would make this whole exercise vacuous, listed so it can be checked

1. The CUDA arm silently running on CPU. Caught by the ≥90% `rerank_score` movement floor.
2. The embedder moving between arms. Caught by the `dense_cosine` = 0 rows control.
3. A stale `marlowe.exe`. `BINARY.json` records sha256 and mtime; checked against source mtimes
   before each run. `cargo run --example` does not rebuild `marlowe.exe`.
4. A latency figure taken with the embedding cache on, so the second provider reads the first's
   vectors. Every latency cell in the component table runs cache OFF and prints that it did.
5. A concurrent `cargo build` stealing cores from a timed cell — CLAUDE.md's parallel-checkout
   hazard #6. Nothing is built while anything is measured, and the build log timestamps are
   recorded so the two windows can be checked not to overlap.

---

# AMENDMENT — the governing principle was RESTATED BY THE HUMAN, before any run was launched

**Appended 2026-08-17, after the section above was committed at `bd33367` and before the first
scoring run started.** Nothing above is edited: a pre-registration that gets quietly rewritten is
not a pre-registration. What follows supersedes §"The governing principle" and §7.

## The principle, verbatim, in the human's own words

> **"If reranking has a low memory footprint and is meaningfully faster on GPU then it should be on
> GPU. The idea is -> everything GPU if it has space for it, CPU otherwise."**

The paraphrase this file was registered against — *"we leave it on CPU for cases where it's already
fast"*, read as *being inside budget is a reason to stay on CPU* — **was wrong.** The rule is
**SPACE**, not budget:

1. Is it **meaningfully faster** on GPU?
2. Does it **fit** in device memory alongside everything else on the card?

Both yes → **GPU by default, CPU as the fallback when the card is full.** *"Fast enough on CPU"*
does not beat *"faster on GPU and it fits."* **CPU is the fallback, not the preference.**

This is the same shape that made `auto` right for the embedder in ADR-044: take the GPU when there
is room, degrade when there is not, and never fail a run over a busy card.

## What this changes in the predictions above

| § | before | after |
|---|---|---|
| 7 | the CPU rerank being inside §5.7's 300 ms was an argument *against* flipping, to be rebutted | **not a gate at all.** The budget column is reporting, not the decision |
| 6 | device cost was one input among several | **THE constraint.** A component that is faster on GPU but starves the model server or forces the embedder down to one session **has not earned the move** |

**The coexistence question is now the load-bearing one and is predicted explicitly.** The card is
16,376 MiB and `llama-server` holds ~11.5 GB of it. The embedder needs ~802 MB per session. So the
reranker must fit in what is left *after both*.

> **Prediction: the reranker's device footprint is under 400 MB at `MAX_BATCH` and it fits
> alongside the embedder AND Ollama simultaneously.** If it does not — if it is large enough to cut
> the embedder's width or to push `llama-server` off the card — **do not flip**, and say so.

## What does NOT change, and none of it is relaxed

The three gates still decide whether the flip is permitted at all, and any one of them failing
means **do not flip**:

1. the ranking A/B, with the ≥90% `rerank_score` movement control;
2. the cross-encoder reference fixture, re-verified on CUDA and **never regenerated**;
3. batch invariance **measured on CUDA**, never inherited from CPU.

**Predicted verdict is unchanged — FLIP — but the reason is now different**, and the difference
matters for the next session: not *"90% of a budget is too much"* but *"it is meaningfully faster,
it is small, and it fits."*
