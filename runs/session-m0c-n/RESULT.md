# M0c Session N — the cascade ships. R@1 0.6725 → 0.6987, R@3 0.8515 → 0.8865, held-out, verified exact.

**Pre-registration committed before implementation** (`PREREGISTRATION.json` in this directory).
Every gate it registered was taken on the wired binary and every one passed **exactly**. Nothing
was tuned: slate 30, narrow 10, RRF k=60, admit 3 — all inherited from
`runs/session-m0c-m/PREREGISTRATION-CASCADE-HELDOUT.json`, which this session implements rather
than revisits.

## The one-line verdict

`RerankPlan` had no call site since it was written; the best measured configuration in the
project sat behind a "NOT WIRED" warning. It is now wired, announced, stamped, dumped,
provider-equivalence-proven, and reproduced held-out **twice** from independent process spawns.

## Gates, all PASS

| gate | registered | observed |
|---|---|---|
| G1 control, fit | R@1 0.7555 / R@3 0.8996 exact | **173/229, 206/229** |
| G1 control, held-out | R@1 0.6725 / R@3 0.8515 exact | **154/229, 195/229** |
| G2 cascade, fit | 180 / 213 of 229 exact | **180/229 = 0.7860, 213/229 = 0.9301** |
| G3 provider equivalence (fit) | zero case movement CUDA vs CPU | **zero** |
| G4 L-6 fixture + per-graph batch invariance | HF-generated, Rust ≤1e-3, bit-identical batching | **PASS** |
| held-out reproduction | 160 / 203 of 229 exact | **160/229 = 0.6987, 203/229 = 0.8865** |
| held-out reproduction, independent spawn | agreement | **identical case-for-case** |
| latency, CUDA end-to-end | P95 ≤ 300 ms | **29.4 ms** (rerank stage p50 16.1 ms for all 40 pairs) |

The latency table's max cell (~600 ms) is ONE first-query CUDA warm-up spike on a cold session;
p95/p99 exclude nothing and still clear the budget by 10×.

## What shipped

* `Rerank::Cascade` in `retrieve.rs`, with `draw_slate` / chunked `score_slate` (never exceeding
  `MAX_BATCH`) / `cascade_fusion_order` as a pure, unit-tested function whose tie-breaks
  replicate the offline tool bit-for-bit — including the EXACT ties adjacent swaps produce under
  two-way RRF.
* `--rerank-plan auto|shipped|cascade`; `auto` selects Cascade iff the reranker RESOLVED CUDA and
  the fusion member loaded. Startup refuses both mismatch directions. Plan announced at startup
  and on every profile row (`rerank_plan`).
* Dump carries `fusion_rank` (`null` when absent), so drivers reconstruct the fused order from
  the binary's own bytes — no second Python implementation of the ranking.
* Fixture `cross-encoder-reference-ft-session-j-L6.json` (HuggingFace authority) + two Rust tests:
  logit agreement through `load_fusion_member`, and per-graph batch invariance on the fuse graph.
* Tools: `tools/cascade_verify.py` (the gate checker), `--rerank-plan` pass-through in
  `tools/score_longmemeval.py` (recorded verbatim in report.json via the target string),
  `fusion_rank` carried in `tools/reach_pools.py`.

## Suite

`cargo test --workspace --jobs 4 --no-fail-fast`: **950 passed, 0 failed**, 85 `test result`
lines tallied from `suite.txt`. Master was 944; **+6 is exactly the six new tests** (three fusion
arithmetic, two L-6 reference/invariance, one single-candidate passthrough).

## New finding surfaced by the wiring itself

On held-out, gold surviving the narrowing step measures **219/224 = 0.9777** — five cases lost at
30→10 — where the FIT split had shown 0.9956 (one case). The offline artifacts never reported
held-out post-narrowing separately; the wired dump does. **Narrowing is the newest weak link**
and had been hidden by a favourable fit number — the exact pattern this project keeps a ledger
for. A wider or smarter narrow is a registered-probe target, not a knob to turn.

## Per-stage conditional accuracy after this change (held-out)

| stage | survives | conditional |
|---|---|---|
| ingest + scope | 229/234 | 97.86% |
| session pruning | 225/229 | 98.25% |
| slate draw @30 | 224/225 | **99.56%** (was 92.0% @ depth 10) |
| narrowing 30→10 | 219/224 | **97.77%** ← newly exposed |
| pick top-3 | 203/219 | 92.69% |
| pick rank-1 | 160/219 | 73.06% |

## What this session did not do

* No change to ADMIT_TOP_K, the frozen gate, MAX_SEQ_LEN, eval/, or any crate outside
  marlowe-memory plus the minimal call-site edits in crates/marlowe named in the ADR.
* No sweep of narrow width, slate depth, k, or membership. The six-way fusion stays unshipped
  (its own held-out read was +0.0044 — already spent, already recorded).
* Held-out reads spent: **one configuration, twice** (the pre-registered reproduction plus the
  accidental-but-valuable second spawn), plus the CPU control. No other held-out access.
* Not merged to master — the worktree branch `m0c-cues` awaits the human's call.

## Next (registered probes, in priority order)

1. **Narrowing**: recover some of the 5 held-out cases the 30→10 cut drops (now measurable per dump).
2. **The combiner gap**: union-oracle cond@3 0.9778 vs best combiner 0.9467 on fit.
3. Focused-second-pass head discrimination (delta between differently-conditioned scores).
4. Session-prune scorer (~4 cases) and the ingest+scope losses (~5) as ceiling repair.

---

## Addendum — Probe 1 (narrowing): closed null, no held-out read earned

PREREGISTRATION-NARROWING.json, instrument gate 229/229, evaluation 
arrow-probe.json.
Union narrow recovered its predicted fit case (post-narrow 225/229) for **zero** R@3 movement
(0 gained / 0 lost) at +50% fuse rows; RRF-narrow dropped BELOW its own registered post-narrow
floor (223 < 224) and is dead by its own rule. Neither arm reached the earn-a-read bar (fit
R@3 >= 214), so the held-out split was not touched.

**The redirect:** the cut was never the constraint. Held-out loses 16 cases at the fuse pick
(cond@3 92.7%) against 5 at the cut. Probe 2 (the combiner gap: union-oracle cond@3 0.9778 vs
best combiner 0.9467 on fit) is where the measurable headroom lives.

Also landed here: the rerank_score write-back defect and its fix -- see the section above the
suite table in git history; the mutation-sensitive test is
etrieve.rs::under_the_cascade_rerank_score_stays_the_SHIPPED_graphs_logit.

---

## Addendum — Probe 2 (the combiner): closed. The oracle gap is a fit-side mirage.

PREREGISTRATION-COMBINER(-HELDOUT).json; instrument gates 229/229 on both splits;
evaluations 
arrow-probe.json, combiner-probe{-heldout}.json.

Fit: six-vote killed by its own band (R@3 212, gained 1 / lost 2); **six-zsum earned the read**
(fit R@1 185 / R@3 215, +5/+2, parameter-free). Held-out, one read spent: **155 / 204**
(0.6769 / 0.8908) against the pair's 160 / 203 -- inside every predicted band, falsification not
met, and the PREWRITTEN ship rule (R@3 >= 205 AND R@1 >= 159) failed on both halves. Not adopted.

**The finding:** six-zsum lands case-for-case on the six-way RRF's already-recorded numbers
(155/204 = 0.6769/0.8908). Rank-based and magnitude-based combination of the same six opinions
read identically held-out -- the ensemble contributes exactly +1 R@3 for -5 R@1 no matter how it
is combined, so the union-oracle's fit-side headroom was shared error wearing complementary
clothes. Fifth instance of the fit-to-held-out collapse family, now characterised at the level
of the COMBINER rather than any single arm.

---

## Addendum -- Probe 3 (the pick): the reader works. Adoption blocked by a prewritten bar, by ONE case.

PREREGISTRATION-PICK{,-HELDOUT-AMENDMENT,-HALFWEIGHT}.json; instrument gates 229/229 on every
run; evaluations pick-probe{,-heldout,-halfweight-*}.json.

| configuration | fit R@1/R@3 | held-out R@1/R@3 |
|---|---|---|
| shipped pair-cascade | 180 / 213 | 160 / 203 |
| reader @ w=1.0 | 176 / 219 (+7/-1) | 156 / 206 (+3/-0) |
| **reader @ w=0.5** | 179 / 216 (+4/-1) | **163 / 205 (+11/-8 / +2/-0)** |

Full weight: R@3 +3 clean held-out, R@1 -4 -- ship rule failed (R@3 < 208). Half weight,
registered end-to-end before any w=0.5 number: fit gate cleared inside both bands; held-out read
**strictly better on both metrics** (+3 R@1, +2 R@3, zero R@3 losses) -- and the R@1 band was
violated UPWARD (163 > 162; the trade model was wrong in the favourable direction). The
prewritten ship rule demanded R@3 >= 206; the read is 205. **Not adopted; the rule governs until
the human says otherwise.** The rule's design flaw is disclosed: it required R@3 alone to carry
an adoption whose actual shape was both-metrics improvement.

Mechanism, for the record: the reader scores answerability ("does this turn contain an
extractable answer-value"), not relevance. It rescues buried multi-topic gold (the corpus's
signature failure) at set level; at full weight its answer-shaped false positives overrule
correct consensus winners at rank 1; at half weight they mostly do not, and held-out the head
GAINS. Delta-fusion (sharpened-query second pass) killed on fit: +3/-4 R@3, -13 R@1.

---

## Addendum -- Stage-5 forensics: the remaining failures are COMPUTED answers, not buried ones

tools/pick_forensics.py over the held-out cascade dump. The 16 fuse-pick failures decompose:

* **~7 aggregation/computation/sequence answers** (counts across sessions, day-delta arithmetic,
  chess notation, note sequences): the answer string does not appear in ANY candidate turn --
  verified against corpus answers ("2", "14 days", "28. Kg3", "C D E F G A B A G F E D C").
  Structurally invisible to span readers and relevance rankers alike; reachable only by a
  generation/reasoning step. **CLOSED while LLM reranking is disallowed -- and that closure is
  the finding:** R@3 0.95 on this benchmark is a reasoning problem, not a ranking problem.
* **~3 long turns** (166/216/582 words vs seq-256 scoring window): truncation-limited; windowed
  reading is the registered next probe.
* **~6 genuine near-peers**: small turns, gold ranked 4-10 by both graphs and often the reader
  too; the half-weight reader harvests part of this (+3 R@1/+2 R@3 measured).

Ceiling statement, measured: with the reader adopted and upstream repaired, this architecture
family tops out near R@3 0.92; the path beyond runs through the banned mechanism class.

---

## Addendum -- Probe 4 (neighbour expansion): closed. Fourth and final form of the neighbour idea.

PREREGISTRATION-EXPANSION.json; gate 229/229. Expansion of <=16-word candidates with their own
session neighbours (prev+turn+next) at scoring time: fit R@3 unchanged vs reader-alone (216 both)
at -3 R@1. The forensic case that motivated it (six-word '28. Kg3 would be my move.') does not
convert even expanded -- notation fragments compete on fluency, not vocabulary, once context is
attached. Neighbour information has now been tested as feature (both signs), predecessor,
tie-break, and input expansion: all four null or harmful. The idea family is closed with
measurements behind every form.

---

## Addendum -- The stage-5 pattern, read case-by-case (16/16 read, answer-string verified)

* **A. 4/16 label artifacts**: the answer string sits in our fused top-3 on UNFLAGGED turns
  (dc439ea3 at rank 1 with 100 percent token overlap). Answer-containment R@3 is already
  ~207/229 = 0.9040 -- the metric undercounts us by at least four cases in this band alone.
* **B. 6/16 computed/synthesized answers** (temporal arithmetic across turns, cross-session
  counts, suggestions-from-preferences): the flagged gold states the precondition; the answer
  must be generated. Closed without generation -- now proven per-case, not asserted.
* **C. 5/16 same-session near-peers** (whole session on-topic; gold carries the value): the
  reader's home population -- 75499fd8's reader score is +11 while it holds half a vote.
* **D. 1/16 truncation** (582-word turn, seq-256 window): windowed reading is the registered fix.

Pattern in one line: we rank PRECONDITIONS against CONCLUSIONS -- and a quarter of the misses
are already answered, uncredited.

---

## CORRECTION (same day) -- the 4 label-artifact cases were hand-adjudicated; 2 survive

Full-text adjudication, not string overlap: dc439ea3 CONFIRMED (the labeled-gold turn contains no
'hooop'/'Hoop' at all -- it cannot answer; 'Hoop Dance' lives in the unflagged turn we ranked
#3) and 65240037 CONFIRMED ('in a 1:10 ratio' verbatim at rank 1, unflagged). The other two
(7e00a6cb, gpt4_4929293b) were FALSE POSITIVES of the >=60-percent token-overlap proxy --
generic-noun matches ('budget hostels', 'cousin') that a reader would reject immediately.

Corrected figures: verified label artifacts 2/16, not 4/16; containment-adjusted held-out R@3
~205/229 ~= 0.895, not 0.904. The earlier 0.904 figure is withdrawn.

Standing rule adopted for this session's artifacts: no containment claim ships without
full-text adjudication of every case it counts. String overlap nominates; reading verifies.
