# Brief: find an exploitable pattern in the retrieval failures

You are hunting for a signal that improves **turn-level R@1** on LongMemEval. Twenty-three
mechanisms have already been measured against this exact data and every one failed. **Your job is
to find something they missed, or to establish convincingly that there is nothing left.**

Both outcomes are valuable. A confident, well-controlled "nothing here" is worth more than a
plausible-looking finding that dies on held-out — which has happened four times.

---

## 1. THE SYSTEM, in one paragraph

For each question, ~490 conversation turns are candidates. Two cues score them (BM25 and dense
cosine over jina-v2-small), a frozen isotonic gate fuses them, session pruning cuts the pool, and
the **top 10 by the fused key** go to a fine-tuned 2-layer MiniLM cross-encoder which picks rank 1.
The product injects **only rank 1** (`vec![order[0]]`), so R@1 is the product metric, not a proxy.

**Held-out R@1 = 0.6725. Fit R@1 = 0.7555.** The ~0.083 gap is case mix, not overfitting (Session I
closed that question).

### Where the losses are (held-out, 234 answerable)

| stage | gold survives | retention | lost |
|---|---|---|---|
| answerable | 234 | — | — |
| ingest + exclusions + scope | 229 | 0.9786 | 5 |
| session pruning | 225 | 0.9825 | 4 |
| slate draw (top-10) | 207 | 0.9200 | 18 |
| **cross-encoder picks rank 1** | **154** | **0.7440** | **53** |

**The cross-encoder loses 53; every other stage combined loses 27.** And R@2 = 0.8122, so
**32 of those 53 have gold sitting at rank 2**. +0.1397 is one binary decision.

---

## 2. YOUR DATA

All paths relative to `c:\Users\matth\Projects\Marlowe_Harness`.

| file | what |
|---|---|
| `runs/session-m0c-m/near-misses.json` | **2.6 MB. Every fit failure × full top-30**: role, session, turn index, rerank logit, BM25, cosine, cue z, cue margin, pruning survival, full text. Plus `ALREADY_TRIED_AND_WHY_IT_FAILED` |
| `runs/session-m0c-m/near-misses.md` | the same, readable, 146 KB |
| `runs/session-m0c-m/control.json` | **703 KB. THE 173 SOLVED CASES**, same features. This is the file that killed 9 of 10 hypotheses. Use it on everything |
| `runs/session-m0c-m/head-probe.json` | 229 labelled rank-1/rank-2 pairs: **26 POSITIVE** (flip fixes), **110 NEGATIVE** (flip breaks), 93 AMBIGUOUS |
| `runs/session-m0c-m/failures.json` | the original forensics, 56 records with derived contrast fields |
| `runs/session-m0c-m/*.json` | every experiment's raw per-query output |
| `data/longmemeval_s_cleaned.json` | the raw corpus (UTF-8 — open with `io.open(..., encoding='utf-8')`) |

**Reuse the existing tooling; do not reimplement it.** `tools/reach_pools.py` (`load_pools`,
`turn_texts`), `tools/sweep_reranker_frontier.py` (`shipped_order`), `tools/head_probe.py` (a
feature-scoring harness that reports flips gained vs lost across a threshold sweep, with a
sign-inverted control). A second implementation of the ranking key is the failure mode this project
keeps a ledger of.

**Every script must gate on reproducing fit R@1 = 0.7555 exactly before emitting anything.** Copy
the pattern from `tools/failure_forensics.py`. A reconstruction that does not reproduce it is
describing a ranking the product does not produce.

---

## 3. THE BAR — read this twice, it is where every predecessor died

**1. Rank 1 is already gold 110 times against 26.** Any reordering rule must be right on **more
than 81%** of the pairs it touches or it loses ground. This is brutal and it is the whole game.

**2. Score FLIPS GAINED vs FLIPS LOST. Never a correlation, an AUC, or a mean difference.** Three
features with *better AUC* than the incumbent were all *worse at the head*. Overall discrimination
and head discrimination are different quantities on this corpus.

**3. Test against `control.json`.** A pattern present in 40% of failures is worthless if it is
present in 38% of successes. **This killed 9 of 10 hypotheses**, including several that looked
compelling.

**4. THE DECISIVE TEST: does it fire correctly where the cross-encoder gap is ABOVE 0.084?** Below
that the two scores are effectively identical and *blind swapping scores +5* — more than the span
reader, sentence MaxP or the ensemble achieved. **A rule that only helps inside that band is a coin
flip with extra steps.** Every record carries its gap. Twenty-one mechanisms scored 0 or negative
above it.

**5. NO TUNABLE KNOBS.** Four mechanisms cleared their bar on fit and died on held-out — including
**context decay, which was never trained**; only its λ was chosen on fit, one hyperparameter from
ten cells, and it still went **+0.0305 → −0.0087**. At n=229, *threshold selection overfits*.
Prefer parameter-free rules. If a parameter is unavoidable, fix it by an argument stated **before**
you look at the result.

**6. Run the sign-inverted control.** A feature that "helps" in both directions is measuring
nothing. This is how the predecessor-turn idea was killed.

---

## 4. THE UNIFYING FACT — most failures are one thing

> **Gold turns are multi-topic with a narrow answer. Distractors are single-topic and coherent.**

The canonical gold turn: *"I'm excited to try making **croissants** again, and I'll make some
**banana bread**... I made a batch with **walnuts**... **By the way, I just baked a chocolate cake
for my friend's birthday**... any tips for **banana bread**?"* — the answer is one clause in four
topics.

The distractor that beat it: *"I'm thinking of trying some new coffee flavors, do you have any
recommendations?"* — one coherent thought, scoring at full strength.

**This predicts the shape of most failures:**

- anything rewarding *sustained topical support* (decay, neighbour similarity, centroid subtraction,
  predecessor/successor turns) → **favours the distractor**
- anything *isolating a peak* (sentence MaxP, proposition indexing) → **surfaces the distractor's
  question-echoing span as readily as the gold's answer**

**The dilution that looks like the disease is also the immune system.** If your hypothesis falls on
either side of this, predict its sign from the fact before you measure — and if it fails, check
whether the *inverted* sign works, because that has already happened once (context decay).

**One more structural fact:** the cross-encoder is fed `entry.text` and **nothing else** — not role,
date, session, turn index, surrounding turns, or its own cue scores. All of those exist in the data.

---

## 5. WHAT IS ALREADY DEAD, AND WHY

The reasons matter more than the verdicts — check a new idea against the *reason*.
Full catalogue in `near-misses.json → ALREADY_TRIED_AND_WHY_IT_FAILED`. Summary:

**Killed by the correct-case control:** question echo *(real diagnostic at 41% vs 16%, dead as a
tie-break because BOTH rank-1 and rank-2 usually echo)*, length/ln(words), role, same-session,
truncation, IDF non-query mass *(0 net, and its inverse is also negative)*.

**Killed by measurement:** recency (~0), dense-cosine fusion at rank 2 (**0 flips at every weight**),
numeric answer-type filter (2/56), neighbour similarity (*gold is MORE similar to its neighbours*),
centroid subtraction (*removing the shared component made it worse*), sentence MaxP, proposition
indexing (input recall **−0.0786**), all four neighbour turns (both signs, −22 to −70),
score recalibration (**mathematically impossible** — R@1 is a within-query ordering read, so any
monotone transform is an identity).

**Killed on held-out after clearing the fit bar:** depth 30 (+0.0174 → +0.0044), retrain with new
negatives (**+0.0698, p=0.0004 → +0.0087**), joint pairwise duoBERT encoder (+0.0655 → +0.0044),
context decay (+0.0305 → −0.0087).

**Killed as models:** nine pretrained cross-encoders 16M–278M (*the 278M models lose to a fine-tuned
16M by 17–27 points*), three SQuAD-v2 span readers (*real signal, weaker than the incumbent,
redundant against a better one*), a 5-model ensemble (*best +2; above the band it loses 5 vs 8*),
small LLM pickers (*0.5B degenerate, 4B net −1*).

**NOT a constraint, despite intuition:** latency. The GPU path runs at **14.7 ms P95 against a
300 ms budget**, and even a 4B LLM's model-only cost is 147 ms. If your idea is expensive, that is
fine.

---

## 6. HOW TO WORK

**Phase 1 — read and hypothesise.** Read `near-misses.md` end to end. Read actual failure text; do
not only compute statistics. The best finding of the session came from reading three cases closely.
Generate as many concrete, mechanical hypotheses as you can.

**Phase 2 — filter cheaply.** For each hypothesis, before building anything, ask:
(a) can it move R@1 *in principle*, or is it a monotone transform / an identity?
(b) does the unifying fact in §4 predict its sign?
(c) is it already dead for a stated reason in §5?
(d) does it need a tunable knob?

**Phase 3 — SPAWN AGENTS TO TEST, IN PARALLEL.** Do not test serially. For each surviving
hypothesis, spawn a subagent with:

- the hypothesis stated mechanically
- a **prediction registered before the run** — effect size and direction
- the bar from §3 verbatim
- an instruction to report **flips gained / flips lost / net / above-0.084 breakdown**, plus the
  sign-inverted control
- the data paths and the "reuse, don't reimplement" rule
- the instrument gate (reproduce fit R@1 0.7555 exactly, or refuse)

Give each agent **one** hypothesis. Run several concurrently. Require raw pasted output, not
summaries.

**Phase 4 — verify before believing.** Anything that survives on fit gets checked against
`control.json` and the above-band test by *you*, not by the agent that found it. Then say plainly
whether it deserves a held-out read. **Held-out is a consumable and four reads are already spent.**

---

## 7. REPORT

Write to `runs/session-m0c-m/AGENT-FINDINGS.md`:

1. **Hypotheses generated**, and which you filtered out in Phase 2 with the reason.
2. **Every hypothesis tested**, with its registered prediction, its flip table, its above-band
   breakdown, and its sign control. Include the failures — a well-controlled null is a result.
3. **Anything that survives**, with an explicit statement of what would falsify it and whether it
   has a tunable parameter.
4. **Your honest verdict on whether anything is left.** If the answer is "the space is exhausted",
   say so directly. Do not manufacture a recommendation.

---

## 8. CONSTRAINTS

- **NEVER run `git add`, `git commit`, or any git write.** A parallel session shares this checkout.
- **`eval/` is NEVER modified.** It is the scoreboard.
- **Do NOT spend a held-out read.** Fit split only (`runs/session-k/fit`). Held-out
  (`runs/session-k/heldout`) is off limits without explicit permission.
- Do not modify existing tools. Create new files under `tools/`; write artifacts under
  `runs/session-m0c-m/`.
- Do not run `cargo`.
- Scratch files in the system temp dir.
- **Run everything and paste real output.** An arm you did not run is NOT-MEASURED, never a result.
