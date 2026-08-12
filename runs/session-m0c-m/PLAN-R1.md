# Plan — the largest available R@1 gains, excluding LLM rerankers

**Written 2026-08-11 at the close of M0c Session M, from measured evidence only.** Every number
below is either measured this session, measured in a prior session and cited with its scope, or an
estimate explicitly marked as one.

**Target: fit 0.7555 → ~0.81, held-out 0.6725 → ~0.72.** The honest ceiling of this plan is
**low-to-mid 0.80s on fit**. It does not reach 0.90, and §6 says why.

---

## 0. The evidence this plan rests on

| fact | value | source |
|---|---|---|
| fit / held-out R@1 | 0.7555 / 0.6725 | Session K, reproduced exactly this session |
| failures decompose | **38 in-slate + 18 ABSENT** | `failures.json` |
| label artifacts | **9 of 56** | answer-containment, computed |
| depth 30 admits | 14 of 18 ABSENT; 4 unreachable at any depth | Session I, reconfirmed |
| **depth-30 conversion** | **4 of 14 = 29%** | **measured this session** |
| train/val failure rate | **22.6% vs 25.5% — no gap** | computed against `training-pairs.jsonl` |
| cross-session negatives in training | **0 of 6,898** | `session_j_mine_negatives.py:94` |
| rank-2 near-ties | 26; 7 within 0.10 logits | `failures.json` |
| cue-rescue ceiling | ~10 of 56 | quantitative review |

**The two facts that shape everything:**

1. **The model underfits.** 44 of 56 failures are queries it trained on, and its failure rate on
   trained queries equals its rate on held-apart ones. More data of the same kind cannot help — and
   M0c Session A's L1 listwise fine-tune already measured **−0.0131, a null with power**.
2. **The 29% conversion rate is the discount on every estimate below.** Making a gold *reachable* is
   not making it *chosen*. Depth 30 made 14 golds reachable and won 4.

---

## Phase 0 — instrument first. ~2 hours. No R@1 change.

Nothing in Phases 1–3 is safely readable without this, and it is the cheapest work in the plan.

**0a. Emit the failure features for the 173 CORRECT cases.**
Every threshold discovered this session is one-sided: measured only on failures. A rule that fires on
40% of failures and 38% of successes is noise, and currently we cannot tell. The content review
already built this control informally and it **killed most of its own hypotheses** — including
near-duplicate-winner, intention-vs-fact (27% vs 27%, exactly zero signal) and
aggregation-is-harder (backwards). Promote it into `tools/`.

**0b. Answer-containment diagnostic, reported BESIDE R@1, never replacing it.**
9 of 56 "failures" put a turn stating the gold answer at rank 1. **The fit ceiling is ~0.96, not
1.00.** Without this, every promotion decision is measured against a denominator containing cases
nothing can fix. Pre-register it as a diagnostic — `eval/` is the scoreboard and is not modified,
and a metric loosened after seeing which cases it would rescue is exactly what the working
agreement forbids.

**Gate:** both land in `tools/`, both run in CI-time, no artifact minted.

---

## Phase 1 — ship what is already measured. +0.0174 fit.

**`ms-marco-MiniLM-L-6-v2-ft-session-j` at rerank depth 30.**

Measured this session: fit **0.7555 → 0.7729**, at **37.1 ms of a 300 ms GPU budget**. Tier A — it is
BERT WordPiece on the same 30522 vocab, so shipping is a digest re-pin in `rerank.rs` and a depth
constant, with no new tokenizer.

**Required before it ships, none inheritable:**

- GPU→GPU byte-identity across repeated runs (ADR-029's amended gate)
- cross-provider **ranking** equivalence vs the CPU path
- **batch and padding invariance re-measured on THIS graph.** L-2-ft reads 0.000000 on CPU and
  **0.000324 on CUDA**; L-6-ft is a different graph and inherits neither number
- node placement re-verified with `tools/session_l_gpu_recovery.py` — ADR-029's explicit interim
  obligation after any model change
- `repro --runs 2` byte-identical, omitting `--embedding-cache`
- CPU-fallback latency reported as information — 1 vCPU is the capability floor and L-6 at depth 30
  costs ~1.1 s there, which is a **capability statement, not a budget breach**

**Held-out read #1 here.** This is the first configuration that has earned one.
**Kill:** held-out delta ≤ 0 → do not ship, and record it. M0c A's slate arm went +0.0087 fit →
−0.0044 held-out; that outcome is live.

---

## Phase 2 — the negative-mining retrain. THE largest single lever. +5 to +7 cases.

The one hole verified in code rather than inferred from failures.

All 6,898 fine-tuning pairs draw negatives from **inside the gold session** — four heuristic classes,
all answering *"which turn inside the right conversation."* Meanwhile **14 of the 30 real in-slate
failures have their rank-1 in a session containing no gold at all.** The model was trained to solve a
different problem than the one it fails.

**Three new negative classes, ablated by class exactly as Session J ablates its four:**

| class | definition | targets |
|---|---|---|
| **`deployed_top_k`** | the current model's own rank 1–10 per query, excluding gold | the rank-2 cluster **directly** — the competitor *is* the negative |
| **`cross_session`** | question-overlap-ranked turns from non-answer sessions, capped per query | 14 cases; preference 8/10, temporal 8/12 |
| **`question_echo`** | maximise overlap with the **question**, filtered to exclude answer tokens | control-tested: **41% of failures vs 16% of solved, 2.6×** |

`deployed_top_k` is standard iterative hard-negative mining and is the piece most likely to move
rank-2 conversion, because it trains against the exact turns that currently win.

**Expected: +5 to +7 in-slate (21 reachable × 25–35%), plus ~+2 from better conversion of the
depth-30 admissions. Fit ~0.79–0.81.**

**Risks, stated before the run:**
- Teaching cross-session rejection may cost the same-session discrimination the current fine-tune
  bought (**+0.0699 held-out, ADR-018**). The per-class ablation is what detects it.
- Mining negatives from fit failures and scoring on fit is **circular**. Fit is a design signal only;
  held-out carries the verdict.
- Retraining moves the whole graph — re-run every Phase 1 gate on the new graph.

**Kill:** fit gain < +0.02 over the Phase 1 baseline → do not take a held-out read, ship nothing.
**Held-out read #2** only if it clears.

---

## Phase 3 — three independent, targeted fixes. +3 to +5 cases.

Run only after Phase 2, because Phase 2 overlaps all three and would otherwise double-count.

**3a. Long-turn windowing for `single-session-assistant`.** ~+2 cases.
**64.3% of that category's gold turns exceed the 256-token budget, against ~0% everywhere else.** All
golds truncated → 6 fail / 12 succeed; some gold fits → **0 fail / 10 succeed** (p = 0.049). Score
overlapping 256-token windows and max-pool.
**This is NOT what ADR-015 refused** — that measured *raising the cap* to 512 (−0.0917) and ADR-017
measured *length normalisation* (null). Windowing at a fixed 256 has never been tested.
**Control:** max-over-windows also lets a long *distractor* accumulate. Measure the winner-truncation
rate alongside, or the fix is unfalsifiable.

**3b. Adaptive slate depth.** Buys Phase 1's win without paying 3× rerank on every query.
`cue_z < 3.0` identifies **17 of 18** ABSENT cases. Expand 10 → 30 only when the cue stage is weak.
Same quality, most of the latency back. Do this *after* fixed depth 30 is validated, so the two
changes are separable.

**3c. Preference routing.** ~+2 cases, capped at 10 by category size.
`single-session-preference` fails **10/15 (p = 0.0004)** and is the only category where the winner
beats gold on discourse *frame* (+0.092) while **losing on content** (−0.006), 8/10 cases. Preference
queries are pure speech acts with no entity anchor. Strip the request frame and score on a
content-word projection.
**Negative control, and it is available:** all 5 correct preference cases have zero competing
sessions and must not regress.

---

## Phase 4 — the pruning wall. NEEDS A DECISION BEFORE ANY CODE.

Four failures (`eac54add` @326, `6e984302` @165, `d6233ab6` @103, `92a0aa75` @69) have
`survived_pruning = False` and enter the slate at **no depth**. The quantitative review also found the
pruner is not a clean `cue_z` threshold — pruned golds sit at 1.94 / 2.39 / 0.64 / −0.06 while a
*surviving* gold sits at **0.621**. That inconsistency deserves an audit on its own terms.

**This is cue and fusion work, which the session brief explicitly fenced off.** It is listed so the
4 cases are not silently written off. It needs its own decision and its own pre-registration.

---

## 5. The projected trajectory

| after | fit R@1 | held-out (est.) | basis |
|---|---|---|---|
| today | 0.7555 | 0.6725 | measured |
| Phase 1 | **0.7729** | ~0.685 | **measured on fit** |
| Phase 2 | 0.790 – 0.803 | ~0.705 | estimate, 25–35% conversion |
| Phase 3 | **0.810 – 0.821** | **~0.72** | estimate |
| *artifact-corrected view of the same system* | 0.854 – 0.863 | — | measurement, not capability |

**Sober case: held-out ~0.70.** This project's record is that fit gains shrink or reverse across the
split, and the reranker trains on fit, so Phase 2's fit number is inflated by construction.

**Held-out budget: three reads, planned in advance** — after Phase 1, after Phase 2, after Phase 3.
Iterating against held-out turns it into a second training set and it stops being evidence.

---

## 6. What this plan cannot reach, and why

| | cases | why |
|---|---|---|
| rank-2 near-ties | 26 (7 within 0.10 logits) | worth **+0.114 at oracle** — every feature we compute scores 26–63% on this decision, i.e. a coin flip. Phase 2's `deployed_top_k` attacks it directly and is the only thing that might |
| aggregation, n_gold ≥ 3 | 11 | no single turn answers "how many". Architectural — session-level or multi-turn evidence units. An M0a/scoreboard conversation |
| pruned-unreachable | 4 | Phase 4, fenced |
| no pattern found | 9 | control-tested against the 173; nothing separates them |

**Ceiling without an LLM reranker: low-to-mid 0.80s on fit, ~0.72–0.75 held-out.**

Three independent lines now say the cross-encoder class is saturated: four architectures (M0c A),
nine pretrained scorers from 16M to 278M (Session M), and the absence of a train/val gap. **If Phase
2 also returns null, that is the fourth, and the remaining answer is the mechanism this plan
excludes.**

---

## 7. Measured dead ends — do not re-spend sessions here

| | result |
|---|---|
| global recency prior | **~0** — knowledge-update (2/10) and temporal (9/12) cancel exactly |
| dense-cosine fusion at rank 2 | **0 flips at every α tested** |
| numeric answer-type filter | **2 of 56** |
| global hand-set length penalty | **net-harmful** — flips top-1 in 13/37 at a 54% hit rate |
| cue re-weighting generally | capped at **~10 of 56**; in 46 of 56 the cues agreed with the mistake |
| bigger pretrained cross-encoders | **refuted to 278M**, Session M, on the GPU target |
| more training data of the same kind | **refuted** — no train/val gap; L1 listwise fine-tune −0.0131, null with power |
| temporal cue | **refuted on this corpus** — Session G arm 4, 1/59 firing on its own category |
