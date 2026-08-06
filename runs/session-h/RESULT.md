# M0b Session H — session pruning and in-session reranking, shipped and measured

**The first session since C to change the scored retrieval path.** Pre-registration committed at
`ab80870`, before the sessionizer was measured and before any held-out number existed.

**The headline: the reranker works and pruning does not.** R@1 moves **0.5348 → 0.5764**. The
registered question, which asked whether *pruning* makes reranking better, **FAILS both
sub-questions**. Those are the same session's results and both are reported.

---

## 1. The headline table

`runs/session-h/cue-overlap.json`, held-out, n=229, produced by the **binary** rather than a
reconstruction.

| | before (Session F) | after | Δ |
|---|---|---|---|
| **R@1** | 0.5348 | **0.5764** | **+0.0416** |
| **R@5** | 0.8130 | **0.8428** | +0.0298 |
| **R@10** | 0.8826 | **0.9039** | +0.0213 |
| **oracle R@1** | 0.6435 | **0.6463** | *structurally pinned — see §4* |
| **ceiling** (max calibrated precision) | 0.3739 | **0.3739** | *structurally pinned — see §4* |
| **retrieval P95** | 33 ms cold | **149 ms** warm, full split | passes 300 ms |

Per-ranker, same run:

| ranker | R@1 | R@5 | R@10 |
|---|---|---|---|
| lexical | 0.5415 | 0.7904 | 0.8341 |
| dense | 0.4454 | 0.8341 | 0.9170 |
| fitted gate (Session F's ranker) | 0.5371 | 0.8166 | 0.8865 |
| RRF (reference) | 0.4930 | 0.8428 | 0.9128 |
| **shipped** (prune → rerank → gate key) | **0.5764** | **0.8428** | **0.9039** |
| either-cue oracle | 0.6463 | 0.8908 | 0.9476 |

**The shipped ranker beats the best single cue for the first time in this project**: +0.0349 at
top-1 against lexical's 0.5415. Sessions D, E and F each shipped a fusion that did not.

**An independent cross-check, and it is exact.** The binary's shipped R@1 is **0.5764**; the offline
reconstruction computing the same quantity for the registered question got **0.5764**. Two
implementations, one number. That is the standing "second implementation must reproduce the first"
check discharged on the session's headline figure.

**At top-10 the shipped ranker is BELOW dense alone** — 0.9039 against 0.9170, −0.0131. The stage
is a *top-1* mechanism: it reorders ten candidates and cannot help beyond them. Stated because a
table showing only R@1 would hide it.

---

## 2. The registered question FAILS, and one of its two criteria was broken

`runs/session-g/REGISTERED-QUESTION-in-session-rerank.json`, registered before any result existed.

| | treatment | control | delta | discordant | McNemar p | floor |
|---|---|---|---|---|---|---|
| **Q1** rerank all pruned vs all unpruned | 0.5764 | 0.5633 | **+0.0131** | 3–0 | 0.25 | met |
| **Q2** rerank top-10 pruned vs top-10 unpruned | 0.5764 | 0.5721 | **+0.0044** | 1–0 | 1.00 | met |

Bars: `delta >= +0.05`, `p < 0.05`, `reranked top-1 > 0.5415`. **Both FAIL.**

**The registered α was unreachable, and that is my registration's defect.** Full record in
`POWER-DEFECT.md`. Exact McNemar is a binomial over the *discordant pairs only*, so the smallest
attainable p is `2/2^n` — 0.25 at n=3, 1.0 at n=1. Q1 had 3 discordant pairs and Q2 had 1, so
`p < 0.05` was **not attainable at any outcome**. The significance half of each verdict is
uninformative by construction and **must not be quoted as evidence of absence.**

**The delta half is untouched and is sound.** +0.0131 and +0.0044 against a +0.05 bar are an order
of magnitude short, and no amount of power turns +0.0044 into +0.05.

**The floor passed and is a separate registered condition.** 0.5764 > 0.5415.

### The finding is in the counts, not the test

Q1 and Q2 differ on **3 and 1 cases out of 229**. Feeding the reranker a 10.3%-of-pool shortlist
instead of the entire ~487-turn pool **changes its top-1 almost never**. The reranker's output is
essentially invariant to whether pruning ran. That comes from the counts rather than from the broken
test, and it is the durable result.

### Which means the session's own premise is answered, and answered no

ADR-013 reframed the problem as *ranking inside a correct ~47-turn session*, on the strength of a
19:1 failure decomposition. Session H built that and measured it. **The reranker gains +0.0393 over
the fitted gate whether or not the pool was pruned first.** The gain is the *cross-encoder*, not the
*in-session framing*. The 19:1 decomposition was a true description of where the errors are and a
false lead about what would fix them — knowing gold is in the surviving session does not help a
reranker that was already going to consider it.

---

## 3. ADR-010 confirmed by measurement: not capped, and still near the cap

Registered to be confirmed rather than assumed, on the fit split, before building:

- **presence ceiling of the pruned pool: 0.9825** against the either-cue oracle's 0.6435. The
  reranker is structurally free to reach ~0.98 and is **not** capped the way Sessions D and E were.
- It lands at **0.5764**, against a held-out either-cue oracle of **0.6463**.

**This is the session's most consequential number for K1.** Four sessions attacked arbitration and
were bounded by the either-cue oracle *because of their shape*. This mechanism is not bounded by it
— proven, not argued — and finishes **below it anyway**. The bound is therefore a property of the
**task**, not of the combiner. A better arbitration shape is not the missing piece, because this
one was not an arbitration and did not clear the bar either.

---

## 4. Two rows are structurally pinned, registered in advance as pinned

Both were registered before measurement in `PREREGISTRATION.json → structurally_pinned_rows`, and
both correct a claim the session brief made.

**The ceiling cannot move.** Pruning runs *after* `features::extract_all`, so every candidate's
`calibrated_precision` is bit-identical to Session F's and the max over a subset can only fall.
0.3739 is an identity here, not a measurement.

**Single-cue and either-cue top-1 cannot move.** Session G's max-aggregation identity is
**partition-independent** — its proof never uses any property of the partition — so it holds for
derived sessions exactly as for true ones. Re-measured rather than inherited: **458/458 case-cue
pairs, zero violations, on both partitions.**

**The unchanged-cue check is a NULL INSTRUMENT here and did not fire.** It reads exactly the three
quantities that identity pins. `STATE.md` had registered it as expected-to-fire because the pool
changes; that was wrong, and instructively so — *"the pool changed"* does not imply *"a read over
the pool changed"*. **Its silence is not evidence the pruned pool is sound.**

**§4.3's gap does NOT close.** The gate still injects nothing: max calibrated precision 0.3739
against a 0.95 threshold. `conformance` was run first, as required, and is REJECTED with 0 section-4
findings and `fail_no_time_dependence` — exactly as pre-registered.

---

## 5. The sessionizer failed its registered guard and the session proceeded deliberately

Full argument in `BAND-FAILURE-ARGUMENT.md`, written before the reranker was built.

| read | derived | true | band | |
|---|---|---|---|---|
| primary — gold retention @N=3 | 0.9825 | 0.9825 | \|Δ\| ≤ 0.02 | **PASS**, Δ +0.0000 |
| guard — surviving pool fraction | 0.1550 | 0.1003 | ≤ 1.5× | **FAIL**, 1.546× |

**The band is not edited. It failed and stays failed.** The argument for proceeding is *not* that
the miss was small: the guard is a proxy for gold damage, and the quantity it proxies for was
measured directly and is exactly zero — completeness 1.0000, zero true sessions split, zero gold
sessions split. The sessionizer merges and never splits, and splitting is the only mechanism by
which pruning can lose the answer. Direction-of-bias is recorded as secondary support, not the
reason.

**§4.6 carries no session structure, and that is the real defect.** Every derived sessionizer is an
approximation of something the contract could carry. Recorded as an **M0a change with its own
registration**, not this session's scope, so it is argued on its merits rather than becoming a
permanent workaround.

---

## 6. Seventh instance of the two-sides-silently-disagree pattern

**Session G re-costed the cross-encoder at ORT's default graph optimization (`ENABLE_ALL`); the Rust
stage builds at `Level1`.** Same digest-pinned graph, same token ids, **logits 0.0699 apart** —
nearly twice the 0.037 batch-invariance failure that blocked adoption in Session G. Caught by the
reference fixture, not by reasoning. Every Python tool now pins `ORT_ENABLE_BASIC`, and the fit
measurement was killed and restarted because it had been running at the wrong level.

The reference test caught a second real defect: **HuggingFace's `longest_first` pops from the FIRST
sequence on ties**, where the first draft popped from the second. Every fixture case passed except
`long query AND long document`, which exists for exactly this.

**Batch invariance re-verified at Level1 rather than inherited across the fusion change: 0.0958**,
worse than at `ENABLE_ALL`. That reinforces the batch=1 design. `repro --runs 2` without a cache is
**byte-identical with the reranker live**, which is the end-to-end confirmation.

---

## 7. Latency: both configurations, because they answer different questions

| configuration | stage P95 | bar | |
|---|---|---|---|
| **shipped** — top-10 of the pruned pool | **102.6 ms** | 300 ms | **passes** |
| Q1 — all ~50 of the pruned pool | **1938.7 ms** | none by registration | 6.5× over budget |
| full retrieval P95, whole held-out split | **149 ms** | 300 ms | **passes** |

Session G's 92.41 ms was a *stage* P95 over 10 pairs as **one batched forward**. At batch 1 it is
10 sequential forwards, measured here at ~10 ms each. The figure survives; the reason it survives is
that the model is small enough for batching to buy nothing.

**What in-session reranking is worth and what fits are different numbers.** Q1's configuration is
what the quality question needed and it does not fit in 300 ms. Since Q1's quality gain over Q2 is
+0.0000 — both read 0.5764 — the budget is not what is limiting quality here.

---

## 8. What shipped

- `retrieve.rs`: `session_keys` (contiguity at a frozen 30-min gap), `surviving_sessions`
  (max-aggregated union of per-cue top-3), pruning after feature extraction, two new ranking levels
  above the existing three, which are untouched.
- `rerank.rs`: L-2-int8 through `ort`, both digests pinned at load, **batch 1 structurally** — one
  pair per call, asserted leading dimension, no slice entry point. Provider required to register via
  `error_on_failure()` rather than checked afterwards.
- `occurred_at_ms` on `MemoryWrittenPayload` and `MemoryEntry`, required and never defaulted,
  `DERIVATION_VERSION` 1 → 2. Maturation still reads the ingest clock and never this field.
- `--reranking`, required, explicit value (`off` or a directory) — deliberately not a bare boolean.
- Hand-rolled BERT pair encoder + `cross_encoder_reference.rs` against HF tokenizers and real ONNX
  logits.

**188 tests passing** (from 175). `eval/` untouched, **72 passing**.

---

## 9. Standing checks

| check | result |
|---|---|
| `repro --runs 2`, no cache | **PASS**, byte-identical, reranker live |
| `conformance` first | REJECTED, 0 findings — as pre-registered |
| reconstruction fidelity gate | **PASS** — 0.5415 / 0.4454 / 0.6463 exactly |
| second implementation reproduces the first | **PASS** — binary 0.5764 = offline 0.5764 |
| unchanged-cue check | did not fire — **null instrument here**, see §4 |
| `cargo test --workspace` | 188 |
| `cd eval && pytest` | 72, unchanged |
