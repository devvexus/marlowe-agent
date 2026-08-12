# M0c Session M, Phase 2 — the negatives moved it, the objective hurt

**The one remaining untested lever, run.** Two changes — different negatives, different loss —
ablated into four arms so they are separable, plus a by-class ablation on both v2 arms. Ten graphs
trained, all ten export-verified, all ten scored through `tools/sweep_reranker_frontier.py`.

**Nothing shipped.** No artifact minted, `crates/` untouched, no held-out read taken, no git write.
Session J's files were read and not modified; the models are pinned in this session's own
`runs/session-m0c-m/retrain-manifest.json`.

---

## 1. THE INSTRUMENT: arm A reproduces the shipped graph, and not just its R@1

Arm A is Session J's recipe re-run by `tools/finetune_v2.py` — same base checkpoint, same pairs,
same loss, same `delta`, same hyperparameters, same seed, same conversation-level fold.

| | Session J recorded | arm A measured |
|---|---|---|
| target margin `delta` | 2.926574 | **2.926574** |
| epoch 1 train loss / fit-val R@1 | 4.5541 / 0.7234 | **4.5541 / 0.7234** |
| epoch 2 | 1.8213 / 0.7447 | **1.8213 / 0.7447** |
| epoch 3 | 1.3610 / 0.7447 | **1.3610 / 0.7447** |
| best epoch | 2 | **2** |
| base fit-val R@1 | 0.6809 | **0.6809** |

Scored through the harness, in the same process as the shipped graph:

```
CONTROL  shipped key, depth 10: R@1 0.7555  (published 0.7555)  R@1_current 0.6987
control reproduces the published fit R@1 exactly. proceeding.

ms-marco-MiniLM-L-2-v2-ft-session-j    d10  R@1 0.7555  cur 0.6987  ir 0.9214  ca 0.8200
ms-marco-MiniLM-L-2-v2-ft-m-A          d10  R@1 0.7555  cur 0.6987  ir 0.9214  ca 0.8200
```

**And the stronger check: 0 discordant queries out of 229.** Arm A and the shipped graph do not
merely agree on an aggregate — they make the *same top-1 decision on every fit query*. An R@1 that
matches by coincidence is a real possibility at this granularity; a per-query identity is not.

**Arm A reproduced. Every other arm's number is therefore about the right system.**

### The base-checkpoint confound was avoided, not declared

The brief anticipated starting from `models/ms-marco-MiniLM-L-2-v2-ft-session-j/pytorch-reference/`,
which is *already* fine-tuned — the confound M0c Session A's L1 arm was criticised for, and one that
would have made arm A structurally incapable of reproducing 0.7555, because a second round of
training on top of Session J's is not the recipe that produced the shipped graph.

**It was not needed.** The un-tuned `cross-encoder/ms-marco-MiniLM-L-2-v2` PyTorch checkpoint is in
the local HF cache, so every arm starts from it. The comparability check confirms it is the same
starting point Session J used, on the same numbers Session J recorded:

| | Session J | here |
|---|---|---|
| Xenova ONNX baseline R@1 | 0.5983 | **0.5983** |
| this PyTorch checkpoint R@1 | 0.5983 | **0.5983** |
| Pearson | 1.0 | **1.000000** |
| max abs logit difference | 5e-05 | **0.000050** |

`--base ft` exists in the trainer and was not used; which checkpoint ran is recorded in every
artifact it writes. **Seed: 7**, matching Session J. Hyperparameters: 3 epochs, lr 2e-5, batch 32,
max_len 256, AdamW, best epoch by fit-val R@1.

---

## 2. THE FOUR-ARM TABLE

Fit split, n = 229, depth 10, CUDA batched, RTX 4080 SUPER, seq 256, scored by
`sweep_reranker_frontier.py` — the shipped-key control reproducing 0.7555 on every run.

| arm | negatives | loss | pairs | R@1 | vs shipped | R@1_current | R@5 | cond. acc |
|---|---|---|---|---|---|---|---|---|
| *shipped* | — | — | — | 0.7555 | — | 0.6987 | 0.9170 | 0.8200 |
| **A** (control) | Session J | MarginMSE | 5,612 | **0.7555** | **+0.0000** | 0.6987 | 0.9170 | 0.8200 |
| **B** | **v2** | MarginMSE | 5,563 | **0.8253** | **+0.0698** | **0.7729** | 0.9170 | **0.8957** |
| **C** | Session J | **BCE** | 5,612 | **0.7031** | **−0.0524** | 0.6419 | 0.9127 | 0.7631 |
| **D** | **v2** | **BCE** | 5,563 | **0.7293** | **−0.0262** | 0.6681 | 0.9170 | 0.7915 |

**The two changes separate cleanly, and they point opposite ways.**

* **Negatives, at fixed loss:** A → B is **+0.0698**; C → D is **+0.0262**. Both positive.
* **Objective, at fixed negatives:** A → C is **−0.0524**; B → D is **−0.0960**. Both negative.

**Only one of the two proposed changes helps. BCE is not a null — it is a loss, in both negative
conditions, and it is the larger effect where the better negatives are.** The hypothesis that
MarginMSE's zero-gradient-past-`delta` was the binding constraint is **refuted**: replacing it with
an objective that keeps pushing made the ranking worse, and the arm that keeps MarginMSE and only
changes what it is pushing *against* is the one that moves.

**A and B are volume-matched** — 5,612 against 5,563 pairs, a 0.9% difference — so A → B is a
comparison of *which* negatives, not *how many*. That is the exact claim PLAN-R1 §0 makes about
this model underfitting, and it now has a number.

**Input recall is unchanged at 0.9214 across every arm.** The whole movement is conditional
accuracy, 0.8200 → 0.8957. Session M's RESULT.md called conditional accuracy "the wall" and put the
best measured value at 0.8200. **The wall moved.**

### Statistical test — McNemar exact, paired against the shipped graph

| arm | scope | won | lost | discordant | exact p |
|---|---|---|---|---|---|
| A | all 229 | 0 | 0 | **0** | 1.0000 |
| **B** | all 229 | **18** | **2** | 20 | **0.0004** |
| C | all 229 | 8 | 20 | 28 | **0.0357** |
| D | all 229 | 11 | 17 | 28 | 0.3449 |
| **B** | held-apart 47 | **3** | **0** | 3 | 0.2500 |
| C | held-apart 47 | 2 | 2 | 4 | 1.0000 |
| D | held-apart 47 | 4 | 3 | 7 | 1.0000 |

Arm C is **significantly worse** at p = 0.0357. Arm D is a null trending worse.

---

## 3. THE CONTAMINATION CONTROL, AND IT IS THE NUMBER TO READ SECOND

`deployed_top_k` is the shipped model's own top-10 **for that query**, so a query in the training
fold has had its exact competitor turns presented as negatives beside its own gold. A model that
memorised "turn X is not the answer to question Q" would raise fit R@1 without learning anything,
**and the sweep's single 229-query number reads identically either way.**

`tools/finetune_v2.py --fold-report` splits it. It reuses `sweep_reranker_frontier`'s
`shipped_order`, `reordered`, `evaluate` and `current_gold_ids` rather than re-implementing them,
and its `all` column reproduces each arm's sweep number exactly — which is how the reuse is known
to be faithful rather than merely intended.

| arm | all 229 | trained-on 182 | **held-apart 47** |
|---|---|---|---|
| shipped baseline order | 0.7555 | 0.7582 | 0.7447 |
| ms-marco-MiniLM-L-2-v2-ft-session-j | 0.7555 | 0.7582 | 0.7447 |
| A | 0.7555 | 0.7582 | 0.7447 |
| **B** | **0.8253** | **0.8297** | **0.8085** |
| C | 0.7031 | 0.6923 | 0.7447 |
| D | 0.7293 | 0.7198 | 0.7660 |
| B-no-deployed | 0.7511 | 0.7473 | 0.7660 |
| B-no-cross | 0.7642 | 0.7637 | 0.7660 |
| B-no-echo | 0.7860 | 0.7912 | 0.7660 |
| D-no-deployed | 0.7336 | 0.7253 | 0.7660 |
| D-no-cross | 0.7118 | 0.6978 | 0.7660 |
| D-no-echo | 0.7249 | 0.7143 | 0.7660 |

The 47 held-apart queries are fit queries whose **conversations** never entered any arm's training
set — Session J's union-find fold, verified 242/242 against Session J's own artifact by
`mine_negatives_v2.py`, and verified here to be the same 47 queries in both pair files.

**Arm B gains +0.0715 on the trained-on half and +0.0638 on the half it never saw.** The gap between
those is +0.0077; the shipped graph's own trained-vs-held-apart gap is +0.0135. **The memorisation
premium is smaller than the baseline's own fold noise, so the gain is not memorisation of specific
competitor turns.**

**Three caveats on the held-apart number, stated rather than buried:**

1. **n = 47, and 3 flips is p = 0.25.** It is directionally consistent (3 won, 0 lost) and it is not
   significant on its own. The all-229 result is what is significant; the held-apart result is what
   says the all-229 result is not an artifact.
2. **The held-apart 47 IS the model-selection set** — best epoch is chosen by fit-val R@1 over
   exactly those queries, so it is not an independent test. It happens not to bind for arm B, whose
   best epoch is **3, the final one**: a procedure with no checkpoint selection at all would have
   chosen the same weights. It does bind for C (epoch 1) and D (epoch 1).
3. **The three negative classes were designed after looking at fit failures.** Even a fold-clean fit
   number is a design signal. **Held-out carries the verdict and has not been spent.**

---

## 4. BY-CLASS ABLATION — run on BOTH v2 arms, because the winner is B, not D

The brief asked for the by-class ablation on arm D. D is below the control, so ablating it measures
degrees of harm; the ablation was run on **B as well**, since that is the arm with something to
decompose. Both are reported.

| arm | classes | pairs | R@1 | vs its own full arm |
|---|---|---|---|---|
| **B** | all three | 5,563 | **0.8253** | — |
| B-no-deployed | cross_session + question_echo | 3,088 | 0.7511 | **−0.0742** |
| B-no-cross | deployed_top_k + question_echo | 4,019 | 0.7642 | **−0.0611** |
| B-no-echo | deployed_top_k + cross_session | 4,019 | 0.7860 | **−0.0393** |
| **D** | all three | 5,563 | 0.7293 | — |
| D-no-deployed | cross_session + question_echo | 3,088 | 0.7336 | +0.0043 |
| D-no-cross | deployed_top_k + question_echo | 4,019 | 0.7118 | −0.0175 |
| D-no-echo | deployed_top_k + cross_session | 4,019 | 0.7249 | −0.0044 |

**All three classes contribute to arm B, and none of the three is sufficient alone** — every
two-class arm lands between the shipped 0.7555 and B's 0.8253, and B-no-deployed lands *below* the
shipped baseline. The effect is in the combination.

**The volume confound, and the one comparison that is free of it.** Dropping a class also drops
pairs, so `−0.0742` for `deployed_top_k` mixes class with volume: that arm has 3,088 pairs against
the others' 4,019. **B-no-cross and B-no-echo have identical volume (4,019),** so those two are
directly comparable to each other, and they say **`cross_session` contributes more than
`question_echo`** (0.7642 vs 0.7860 — removing cross_session costs 0.0218 more). The
`deployed_top_k` figure is the largest drop and is also the least clean; single-class arms would
settle it and were **NOT MEASURED**.

---

## 5. WHERE THE WINS LAND, and it confirms the hypothesis mechanistically

Arm B against the shipped graph, per category:

| category | n | shipped R@1 | arm B R@1 | delta | flips (won / lost) |
|---|---|---|---|---|---|
| **single-session-preference** | 15 | 0.3333 | **0.7333** | **+0.4000** | **6 / 0** |
| single-session-assistant | 28 | 0.7857 | 0.8571 | +0.0714 | 2 / 0 |
| multi-session | 61 | 0.8033 | 0.8689 | +0.0656 | 4 / 0 |
| knowledge-update | 36 | 0.7222 | 0.7778 | +0.0556 | 2 / 0 |
| temporal-reasoning | 57 | 0.7895 | 0.8246 | +0.0351 | 3 / 1 |
| single-session-user | 32 | 0.8125 | 0.8125 | +0.0000 | 1 / 1 |

**The gain is broad — every category is flat or up, 18 wins against 2 losses — and it is
concentrated exactly where the hypothesis said it would be.** PLAN-R1 §3c identified
`single-session-preference` as failing 10 of 15 (p = 0.0004), *"the only category where the winner
beats gold on discourse frame while losing on content"*, and proposed a dedicated **preference
routing** fix worth an estimated +2 cases. **Arm B recovers 6 of those 10 with no routing, no new
feature and no code outside the trainer.** Preference queries are pure speech acts with no entity
anchor, which is the purest form of "talks about the topic" beating "contains the answer" — and it
is the category that moves most.

**This is not a trained-fold artifact either:** two of arm B's three held-apart wins are
`single-session-preference` (`09d032c9`, `195a1a1b`), the third `multi-session` (`157a136e`).

**PLAN-R1 §3c should be re-costed before it is built.** Its ~+2 cases now overlap 6 already taken.

---

## 6. THE BANDS, SCORED

| registered | outcome |
|---|---|
| **Prediction: +5 to +8 cases, fit ~0.777–0.790** | **REFUTED — on the low side.** Arm B is +16 net cases (18 won, 2 lost) at fit **0.8253**. The first band today that was too *pessimistic* |
| **Promotion floor: +0.02 over fit 0.7555** | **CLEARED by arm B at +0.0698 — 3.5× the floor.** Not cleared by A (+0.0000), C (−0.0524) or D (−0.0262) |
| **Report R@1_current beside R@1 always** | Done. Shipped 0.6987 → arm B **0.7729**, +0.0742, moving with R@1 rather than against it |

**By the registration, arm B has earned held-out read #2. It was not taken** — the brief forbids
spending one, and the decision is the human's. Read the floor as it was written: this is the first
configuration in M0c to clear it.

**The counter-precedent stands and should be quoted with the number above.** M0c Session A's slate
arm went **+0.0087 fit → −0.0044 held-out**, and ADR-018's fit-to-held-out shrinkage on this exact
contrast was roughly 2×. A 2× shrink on +0.0698 is still +0.035, which clears the floor; a sign flip
is not excluded by anything measured here.

---

## 7. EXPORT VERIFICATION — five checks, ten graphs, all pass

A silently wrong export produces plausible numbers, so no arm was scored before this passed.
`tools/finetune_v2.py --verify` runs `session_j_verify_export.py`'s check functions — imported, not
restated — against a graph loaded through `session_i_rerankers.load` with its digest pin,
`ORT_ENABLE_BASIC`, one thread and the provider asserted after construction.

| check | A | B | C | D | B-no-* ×3 | D-no-* ×3 |
|---|---|---|---|---|---|---|
| 1. discriminates | PASS | PASS | PASS | PASS | PASS | PASS |
| 2. determinism (3 runs, 1 value) | PASS | PASS | PASS | PASS | PASS | PASS |
| 3. batch invariance, CPU | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| 4. padding invariance | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| **5. torch vs ORT** | **2e-06** | **2e-06** | **3e-06** | **3e-06** | ≤3e-06 | ≤4e-06 |

Check 5 is the only one that speaks to the **export** rather than to the exported graph's behaviour,
and it is the one the brief singles out. Artifacts:
`runs/session-m0c-m/export-verification-<model>.json`.

**Batch invariance on CUDA is NOT identical — arm B reads 0.00044155**, against the shipped graph's
0.00032425 measured in the same way this session. This is the ADR-029 position, not a regression:
the amended gate is GPU→GPU byte-identity plus cross-provider *ranking* equivalence, and GPU→GPU
determinism passes (3 identical values). **Re-measured per graph, never inherited.**

**Repeat control on the scored number:** re-running arm B's sweep in a fresh process returns
**R@1 0.8253, cur 0.7729, ir 0.9214, ca 0.8957** — identical (`retrain-B-repeat.json`).

**The unvalidated-export gap is bounded, not closed.** These are models this session trained; there
is no external authority. Same statement Session J carries.

---

## 8. WHAT WAS NOT MEASURED

Named, because "not run" is not a result:

* **Held-out, for every arm.** Deliberately not spent.
* **Single-class arms** (each v2 class alone). The `deployed_top_k` ablation stays volume-confounded
  without them.
* **Depths 20 and 30** on any arm. Every number here is depth 10. Session M measured depth 10 → 30 as
  +0.0131 on the shipped graph; whether that stacks on arm B is unknown.
* **L-6 on the v2 negatives.** Session M's best pre-retrain cell was L-6-ft at depth 30 (0.7729);
  arm B beats it at depth 10 with an L-2, but the combination is untested.
* **More than 3 epochs.** Arm B's fit-val was **still climbing at epoch 3** (0.7234 → 0.7447 →
  0.8085) and its best epoch is the last one, so the schedule is a bound rather than an optimum.
* **Session J's 4 classes + v2's 3 together** (`--merge-session-j` builds the 13,785-pair file).
* **Any Rust change.** Arm B is Tier A — BERT WordPiece on the same 30522 vocab — so shipping would
  be a digest re-pin in `rerank.rs`, but nothing in `crates/` was touched and no gate from PLAN-R1
  Phase 1 (GPU→GPU byte-identity across runs, cross-provider ranking equivalence, node placement via
  `session_l_gpu_recovery.py`, `repro --runs 2`) was run on this graph.

**Latency is not a claim here.** The p50 figures in the cells (6.2–9.4 ms) were taken in a shared
checkout with a parallel session live, which is hazard form 6 in CLAUDE.md. They are recorded and
should not be differenced.

---

## 9. FILES

| path | what |
|---|---|
| `tools/finetune_v2.py` | the trainer, `--verify`, and `--fold-report` |
| `tools/session_i_rerankers.py` | **10 entries added to `FINETUNES`**, digest-pinned. Nothing else changed |
| `models/ms-marco-MiniLM-L-2-v2-ft-m-{A,B,C,D,B-no-*,D-no-*}/` | the graphs, tokenizers and PyTorch references |
| `runs/session-m0c-m/retrain-manifest.json` | this session's pins; Session J's manifest not written to |
| `runs/session-m0c-m/retrain-<arm>.json` | the sweep cell per arm (10 + `retrain-B-repeat.json`) |
| `runs/session-m0c-m/retrain-train-<arm>.json` | per-arm training record: base, comparability, loss, history |
| `runs/session-m0c-m/retrain-fold-breakdown.json` | trained-on / held-apart split, plus per-query hits |
| `runs/session-m0c-m/export-verification-<model>.json` | the five checks per graph |
| `runs/session-m0c-m/train-arms.log` | full training output for arms B through D-no-echo |

---

## 10. THE ONE-LINE ANSWER

**Yes — the reranker can learn to prefer the turn that contains the answer over the turn that talks
about the topic, and the thing that teaches it is the negatives, not the objective.** Fit R@1
0.7555 → **0.8253** (p = 0.0004, 18 won / 2 lost), conditional accuracy 0.8200 → **0.8957**, driven
hardest by `single-session-preference` at **0.3333 → 0.7333**, holding at +0.0638 on 47 queries
whose conversations were never trained on, from a model that is **the same 16M parameters at the
same 6 ms**. The BCE arm of the same experiment is **worse than the control**, significantly so on
Session J's negatives.

**Three independent lines had said the cross-encoder class was saturated on this corpus — four
architectures, nine pretrained scorers, and the absence of a train/val gap.** All three were
measurements of **capacity**. None of them varied **what the model was asked to separate**. The
saturation was real and it was in the wrong dimension.
