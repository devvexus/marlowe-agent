# M0b Session I — three findings, no sweep

**Scope narrowed twice during the session, both times deliberately and both times recorded before
the next measurement ran.** The full arm sweep was not run. Three findings are the deliverable, and
each one changes what a later session does.

**Headline: the obvious fix to a real defect is a −0.0917 regression, and the reason is mechanical.**

| | |
|---|---|
| **1. Truncation is an accidental length normalizer** | The shipped seq-256 cap truncates gold in 7.86% of fit cases. Raising it to 512 costs **−0.0917 R@1** (p=0.0002, α attainable). **Do not ship.** |
| **2. int8 is shape-sensitive** | Padding alone flips top-1 in **15%** of cases on the shipped quantized graph. f32 is invariant to 0.000000. Sequence length is not a free parameter on int8. |
| **3. CUDA is unblocked** | Nothing was missing. `os.add_dll_directory(torch/lib)` before importing onnxruntime. This unblocks fine-tuning, now the strongest remaining lever. |

Pre-registration: `PREREGISTRATION.json`, written after Phase 0/1 and before any sweep number.

---

## 1. The truncation defect: real, and the obvious fix is wrong

### The defect stands

Query + gold turn fits in seq 256 in **211/229 = 0.9214** of fit cases. Gold p95 is 270 word pieces
and its maximum is 681, against a document budget of ~237 after the query and 3 special tokens.
**R@1 0.5764 was measured on a configuration that scores 7.86% of gold turns on a fragment.**

**The two 0.9214 readings are independent — checked, not assumed.** Gold-in-top-10-slate and
gold-fits-in-256 are *different* sets of 211: 194 overlap, 17 exclusive to each, 1 in neither.
P(A∧B) = 0.8472 against an independence prediction of 0.8490. The joint figure is the one that
matters: **only 0.8472 of cases have gold both in the slate and untruncated.**

### The fix fails, with power

`ms-marco-MiniLM-L-2-v2` **f32**, depth 10, window 0, fit split. Everything but sequence length is
identical — same digest, same pruning, same gate key, same slate.

| | R@1 | input recall | conditional accuracy |
|---|---|---|---|
| seq 256 | 0.5983 | 0.9214 | 0.6493 |
| seq 512 | 0.5066 | 0.9214 | 0.5498 |
| **Δ** | **−0.0917** | 0.0000 *(pinned — slate membership does not depend on seq)* | **−0.0995** |

Discordant **31** (5 gained, 26 lost), exact McNemar **p = 0.0002**. **α was attainable at this n**
— the smallest possible p here is 0.0000, well under 0.05. Unlike Session H's, this significance
statement carries information.

### The mechanism, which is the actual finding

Registered before the measurement: hypothesis (a) the model genuinely prefers long passages, or
(b) truncation manufactures the score by cutting a distractor to its most query-like opening.

**(a) holds, and more strongly than either framing anticipated. Truncation at 256 was *suppressing*
the length bias, not manufacturing it.**

| rank-1 on failures | seq 256 | seq 512 |
|---|---|---|
| assistant-authored | 50.0% | **74.3%** |
| median word pieces | 157 | **487** |
| p75 / p95 | 424 / 632 | 611 / 771 |
| failures | 92 | 113 |

Gold is 87.7% user-authored at a median of 70 word pieces; the assistant base rate is 12.3%. Give
the model more of a long assistant turn and it prefers that turn *more*.

> **The 256 cap is doing two opposing jobs.** It costs the 7.86% of gold turns that do not fit, and
> it earns more than that back by capping how much score a long distractor can accumulate.
> **Removing the cap removes the normalization.**

**Consequence for a later session: raising sequence length must not be attempted again on its own.**
It is only viable alongside explicit length normalization of the rerank score — which is **arm 7,
structural features, now promoted from deferred to the named next lever for R@1.**

### The one capacity read that landed, and it is a null with power

`ms-marco-MiniLM-L-6-v2` f32 completed after the scope narrowed. Precision held constant, so this is
capacity alone — 2 layers against 6, same architecture, same training set, same tokenizer.

| fit, depth 10, window 0 | R@1 | conditional accuracy | ms/pair |
|---|---|---|---|
| L-2 f32 @256 | 0.5983 | 0.6493 | 18.2 |
| **L-6 f32 @256** | **0.6114** | **0.6635** | 52.1 |
| L-2 int8 @256 *(shipped)* | 0.6201 | 0.6730 | 8.9 |

**L-6 vs L-2, paired: +0.0131 R@1, discordant 27 (15 gained, 12 lost), exact p = 0.7011.** α was
attainable at this n (smallest possible p = 0.0000). **This is a null result with the power to have
detected an effect** — not an underpowered one. Tripling reranker depth is indistinguishable from
noise against a target that needs +0.20.

**RULE 1's premise gets its first real test and does not survive it.** The decomposition said
capacity leads because 49.4% of failures sit at ranks 2–3; the one capacity step measured moves
almost nothing. **This does not close arm 2** — L-2→L-6 is a modest step inside one architecture and
says nothing about bge, jina or mxbai — but it substantially downgrades the capacity hypothesis, and
a later session should weight arm 7 above arm 2 accordingly.

**The sequence-length penalty is capacity-dependent, and that is a real interaction:**

| seq 512 vs 256 | ΔR@1 | discordant | exact p |
|---|---|---|---|
| **L-2** f32 | **−0.0917** | 31 | **0.0002** |
| **L-6** f32 | −0.0088 | 8 | 0.7266 |

L-2 collapses when given long documents; L-6 barely moves. The rank-1 distractor at seq 512 is 74.3%
assistant-authored at 487 median word pieces under L-2, but only 54.9% at 160 under L-6. **The length
bias is substantially a weak-model artifact.** It does not rescue raising the sequence length — L-6
still does not gain from it — but it means length normalization and capacity are not independent
levers, and arm 7 should be measured across at least two capacities.

*(A caution on the int8 row: it reads 0.0218 above L-2 f32, i.e. quantization appearing to help. That
is 5 cases and was not paired-tested. It is noise until someone measures it, not a finding.)*

---

## 2. int8 is shape-sensitive, and the first read of §1 was void

The first pass ran the contrast on the shipped **int8** graph and produced the same −0.0917. The
sanity check then failed: **50 out of 50 identical, untruncated pairs scored differently at
max_len 256 versus 512.** With a correct attention mask, padding should be inert.

Isolated properly — the *exact token ids* from the 256 encoding, stripped of padding and re-padded
to 512, so content, order and everything else is bit-identical and only the tensor shape differs:

| padding-only, 600 pairs | median \|Δlogit\| | p95 | max | **cases where padding alone flips top-1** |
|---|---|---|---|---|
| L-2 **int8** | 0.010904 | 0.046044 | 0.417379 | **9/60 = 15%** |
| L-2 **f32** | 0.000000 | 0.000000 | 0.000000 | **0/60** |

**`[1, 256]` is load-bearing on the shipped quantized graph, exactly as batch=1 is.** Both are
quantization artifacts, not architectural properties — this is the same family as Session H's 0.0958
batch-invariance failure, arriving in a second dimension.

**The int8 and f32 reads both landing on −0.0917 is coincidence and must not be read as
corroboration.** Both lost a net 21 of 229 cases; the underlying discordance differs (27 vs 31).
The f32 figure is the one that stands, because it is the only one where sequence length is the sole
variable.

**Standing check, new:** *any sweep that varies sequence length runs f32, or its cells are different
scorers.* Eighth instance of the two-sides-silently-disagree pattern.

---

## 3. CUDA: unblocked, and nothing was missing

Session G's CUDA figure landed within 1% of the CPU number because the provider was *listed* and
never *loaded*, and ORT fell back silently.

**Diagnosis.** No CUDA Toolkit is installed and none is needed. Driver 610.74 / CUDA UMD 13.3, RTX
4080 SUPER. `torch 2.5.1+cu121` already bundles precisely what ORT 1.24 requires, in
`site-packages/torch/lib`: `cublas64_12.dll`, `cublasLt64_12.dll`, `cudnn64_9.dll`,
`cudart64_12.dll`. They were simply not on ORT's DLL search path.

**The fix, exactly, so a fresh environment reproduces it:**

```python
import os
os.add_dll_directory(os.path.join(os.path.dirname(__import__("torch").__file__), "lib"))
import onnxruntime as ort            # AFTER add_dll_directory, never before
sess = ort.InferenceSession(model, opts, providers=["CUDAExecutionProvider"])
assert "CUDAExecutionProvider" in sess.get_providers()   # asserted, never assumed
```

Verified: `ACTIVE PROVIDERS: ['CUDAExecutionProvider', 'CPUExecutionProvider']`, forward pass
returns a finite logit.

**Two conditions on any use of it, neither yet discharged:**

- **The environment has a package conflict to clean up first:** `onnxruntime` 1.23.2 **and**
  `onnxruntime-gpu` 1.24.2 are both installed into the same package directory. 1.24.2 currently
  wins. Uninstall the CPU package.
- **The determinism boundary is not crossed in this session.** GPU is for offline fit-split
  selection only; a published held-out number is taken on CPU, single-threaded. GPU-vs-CPU ranking
  agreement must be verified before any GPU cell is trusted. **GPU is not adopted for shipped
  inference** — that needs its own ADR covering determinism and the VPS target.

**This unblocks fine-tuning a cross-encoder on the fit split**, which was blocked on CUDA and is now
the strongest remaining lever.

---

## 4. What else was measured, and what was banked rather than spent

### Phase 0.1 — the fit/held-out gap is case mix. Issue closed.

Both halves scored through one function, one process, one dump:

| check | target | measured | |
|---|---|---|---|
| held-out reproduces the **binary** | 0.5764 | 0.5764 | **+0.0000** |
| fit reproduces **Session H's offline tool** | 0.6201 | 0.6201 | **+0.0000** |

| split | n | R@1 | input recall | conditional accuracy |
|---|---|---|---|---|
| fit | 229 | 0.6201 | 0.9214 | 0.6730 |
| held-out | 229 | 0.5764 | 0.9039 | 0.6377 |
| Δ | | +0.0437 | +0.0175 | **+0.0353** |

**81% of the gap is discrimination, not slate quality.** Held-out input recall was *derived* before
being measured — reranking permutes a slate and never changes its membership, so the shipped R@10
**is** the top-10 input recall — and the measurement confirmed 0.9039 exactly.

### Phase 0.2 — the failure decomposition (fit, n=229, 87 failures)

| gold lands at | count | of failures |
|---|---|---|
| rank 1 — solved | 142 | — |
| rank 2 | 29 | 33.3% |
| rank 3 | 14 | 16.1% |
| rank 4–5 | 22 | 25.3% |
| rank 6–10 | 4 | 4.6% |
| **absent from slate** | 18 | **20.7%** |

**Input recall by depth, computed with no reranker at all** — from the gate key's rank of gold:

| depth | 10 | 20 | 30 | 50 | 100 | pruned pool |
|---|---|---|---|---|---|---|
| input recall | 0.9214 | 0.9738 | **0.9825** | 0.9825 | 0.9825 | 0.9825 |
| conditional accuracy needed for R@1 0.80 | 0.8682 | 0.8215 | 0.8142 | — | — | — |

**Depth saturates at 30, and depth 30 *is* the whole pruned pool.** Session H's "reranking ~50 scores
the same as 10" was reranking ~30 effective candidates with a model too weak to exploit them: depth
handed L-2 **+0.0611** of input recall and L-2 returned **−0.0374** of conditional accuracy, netting
+0.0044. That is a capacity failure, not depth being closed.

**The rank-1 distractor shares gold's true session only 58.0% of the time** (derived session 59.4%),
at cosine 0.850 to gold. Any brief framing this as same-session discrimination is wrong by 42%.

### Phase 1 — banked, so a later session starts at Phase 2

- **Acquisition:** 12 candidates probed, 10 clear the bar, **8 fetched and pinned by repository
  revision AND sha256**. `bge-reranker-v2-m3` and `mxbai-rerank-base-v2` publish no maintainer ONNX
  export — **refused, not substituted**, and named so they are not silently re-added.
- **Model gate:** all 9 admitted (8 f32 + the shipped int8 control) on digest, provider-asserted,
  pair-encoding, discrimination and determinism. Cost measured: 8.9 ms/pair (shipped) to 462
  ms/pair (mxbai-base). **bge-base and jina-v2 are ~7.6 s/query at depth 20 and cannot ship against
  ADR-003's 1-vCPU target regardless of quality** — if either wins on quality, the cascade becomes
  the shipping question rather than an optional arm.
- **Truncation reachability grid:** an **uncapped ±1 window is 733 word pieces at the median** and is
  unreachable at every sequence length these models support. With a per-neighbour cap of 32–64 at
  seq 512, survival is 0.982–0.987 and arm 1 becomes reachable. **Cells below 0.98 are not swept** —
  run uncapped at 256, arm 1 would have read "context does not help" while measuring truncation.

### Registered and not run

**Arm 6 (per-query normalization) was reclassified rather than deferred: it CANNOT move R@1.** It is
a strictly increasing transform within a query, and R@1 is a within-query ordering read — an
identity, the same defect as ADR-011 and ADR-013. It is real machinery for the precision-at-coverage
curve, where the decision is cross-query. No band was registered on it.

**Deferred as UNMEASURED — not closed, not refuted, not run:** arm 1 (context), the depth grid,
cascade, ensemble, structural features.

---

## 5. Standing checks

| check | result |
|---|---|
| reconstruction licensing gate | **PASS** — lexical / dense / either-cue reproduce Session F exactly |
| second implementation reproduces the first | **PASS** — offline 0.5764 = binary 0.5764, and 0.6201 = 0.6201 |
| ONNX graph optimization level pinned both sides | **PASS** — `ORT_ENABLE_BASIC` throughout |
| provider asserted after construction | **PASS** — on all 9 models, and on the CUDA path |
| every adopted model pinned by revision AND sha256 | **PASS** — 8 models |
| `eval/` untouched | **PASS** — unchanged |
| `rerank.rs` unchanged | **PASS** — the fix was measured and rejected; nothing shipped |

**Two defects in my own tooling, found and fixed rather than shipped:** the truncation grid's first
run compared token counts that included `[CLS]`/`[SEP]` against counts that did not, and read
0.0000 survival at window 0 — impossible, since the document *is* the gold turn there. And
`session_i_seqlen.py` originally named its output by split alone, so a second invocation with a
different model silently overwrote the first's results; it now names by model as well.
