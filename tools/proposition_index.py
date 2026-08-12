"""Does indexing PROPOSITIONS instead of TURNS get gold into the slate more often?

    python tools/proposition_index.py

**Reach check. ADR-010. Twenty minutes, nothing built, nothing shipped.**

## The one thing M0c Session M never changed

Twenty post-hoc tie-breaks, nine pretrained scorers, an ensemble, a retrain, a joint pairwise
encoder, three span readers and an LLM picker all took the candidate set the pipeline produced and
argued about its ORDER. **None of them changed what a candidate IS.**

A candidate is one turn's raw text -- whatever the user happened to type in one message. The gold
turn in `9a707b82` reads:

    "I'm excited to try making CROISSANTS again, and I think I'll also make some BANANA BREAD for
     the dinner party. I recently made a batch with WALNUTS... BY THE WAY, I JUST BAKED A CHOCOLATE
     CAKE for my friend's birthday party... Anyways, do you have any tips for BANANA BREAD?"

BM25 and the dense cue score that whole blob, so the answer's signal is divided by three unrelated
topics. The distractor that beats it -- *"I'm thinking of trying some new coffee flavors, do you
have any recommendations?"* -- is one coherent thought scoring at full strength.

**And there is a sharper version of the same point.** BM25 ranks by query-term overlap; our
distractors are DEFINED by query-term overlap without the answer (question-echo: 41% of failures
against 16% of successes, control-tested). So the retrieval stage actively selects our hardest
distractors into the slate, and nothing downstream can undo a slate chosen on the property that
characterises wrong answers.

## Why this is NOT the sentence-MaxP experiment already measured

`tools/sentence_maxp.py` re-scored the **top-5 turns** at the **rerank** stage: the slate was still
drawn by turn-level cues, so a buried sentence never competed for ENTRY. It measured 11 gained /
15 lost as a reranking rule.

This changes the retrieval unit itself. The quantity that matters is therefore **input recall at
depth 10** -- does gold get INTO the slate -- not the reranking outcome.

**18 of 56 fit failures are ABSENT**: gold never enters the slate at all. Every mechanism this
session worked on the 38 in-slate ones. The only thing that touched ABSENT was depth, and depth
failed on held-out because it added distractors in proportion (+0.0743 input recall, -0.0520
conditional accuracy, net +0.0044, p=1.000). Proposition indexing brings a diluted gold IN without
raising the candidate count.

## THE CONTROL, and the comparison is meaningless without it

My BM25 is not the shipped Rust BM25. Comparing my proposition-level score against the shipped
turn-level number would conflate "propositions vs turns" with "my implementation vs theirs".

So **the same implementation is run both ways** -- turn-level and proposition-level -- and the
difference between THOSE is the reading. The shipped number is reported beside them as context
only.

Per-query IDF over that query's own units, matching `lexical::score_all`, which builds its document
frequency map over the ~487 candidates of the query being scored.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "proposition-index.json"
K1, B = 1.2, 0.75
MIN_WORDS = 4          # a fragment shorter than this is glued to its neighbour, never scored alone
_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    "a an the of to in on at is are was were be been being it its this that these those and or but "
    "if then as by from for with i my me we our you your do did does have has had will would can "
    "could should not no yes so just really very about there here".split()
)


def toks(t: str) -> list[str]:
    return [w for w in _WORD.findall((t or "").lower()) if w not in STOP]


def propositions(text: str) -> list[str]:
    raw = [s.strip() for s in _SPLIT.split(text or "") if s.strip()]
    out: list[str] = []
    for s in raw:
        if out and len(s.split()) < MIN_WORDS:
            out[-1] += " " + s
        else:
            out.append(s)
    return out or ([text] if text else [])


def bm25_scores(query: str, units: list[list[str]]) -> np.ndarray:
    """Okapi BM25 over one query's unit population. IDF is per-query, as the shipped cue's is."""
    n = len(units)
    if n == 0:
        return np.zeros(0)
    df: Counter[str] = Counter()
    for u in units:
        df.update(set(u))
    avgdl = sum(len(u) for u in units) / n
    q = [w for w in dict.fromkeys(toks(query))]
    idf = {w: math.log(1.0 + (n - df.get(w, 0) + 0.5) / (df.get(w, 0) + 0.5)) for w in q}
    out = np.zeros(n)
    for i, u in enumerate(units):
        if not u:
            continue
        tf = Counter(u)
        dl = len(u)
        s = 0.0
        for w in q:
            f = tf.get(w, 0)
            if f:
                s += idf[w] * (f * (K1 + 1)) / (f + K1 * (1 - B + B * dl / avgdl))
        out[i] = s
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", type=int, nargs="+", default=[5, 10, 20, 30])
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, _ = load_pools(FIT_POOLS)
    texts_all = turn_texts()
    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}")
    print(f"control: fit R@1 {r1}  ({len(pools)} queries)\n")

    N = len(pools)
    rec = {k: {"shipped": 0, "turn": 0, "prop": 0} for k in args.depths}
    gold_rank = {"turn": [], "prop": []}
    nprop = []

    for n, (qid, pool) in enumerate(sorted(pools.items()), 1):
        t = texts_all.get(qid, {})
        texts = [t.get(c.turn_id) or "" for c in pool.candidates]
        gold = np.array(pool.gold)

        # -- the shipped cue order, as drawn (survivors first, then score/margin/id) --------------
        keys = [(0 if c.survived_pruning else 1, -c.score, -c.margin, c.memory_id or "")
                for c in pool.candidates]
        ship = sorted(range(len(texts)), key=lambda i: keys[i])

        # -- ARM 1: my BM25 at TURN level (the control for my implementation) ---------------------
        turn_units = [toks(x) for x in texts]
        s_turn = bm25_scores(pool.question, turn_units)
        o_turn = sorted(range(len(texts)), key=lambda i: (-s_turn[i], pool.candidates[i].memory_id or ""))

        # -- ARM 2: my BM25 at PROPOSITION level, turn score = best proposition -------------------
        owner, prop_units = [], []
        for i, x in enumerate(texts):
            for p in propositions(x):
                owner.append(i); prop_units.append(toks(p))
        nprop.append(len(prop_units))
        s_prop_units = bm25_scores(pool.question, prop_units)
        s_prop = np.zeros(len(texts))
        for u, sc in zip(owner, s_prop_units):
            if sc > s_prop[u]:
                s_prop[u] = sc
        o_prop = sorted(range(len(texts)), key=lambda i: (-s_prop[i], pool.candidates[i].memory_id or ""))

        for k in args.depths:
            rec[k]["shipped"] += int(any(gold[i] for i in ship[:k]))
            rec[k]["turn"] += int(any(gold[i] for i in o_turn[:k]))
            rec[k]["prop"] += int(any(gold[i] for i in o_prop[:k]))
        for nm, o in (("turn", o_turn), ("prop", o_prop)):
            gold_rank[nm].append(next((j + 1 for j, i in enumerate(o) if gold[i]), None))
        if n % 60 == 0:
            print(f"  {n}/{N}  {np.mean(nprop):.0f} propositions/query")

    print(f"\nmean {np.mean(nprop):.0f} propositions per query "
          f"(from ~{np.mean([len(p.candidates) for p in pools.values()]):.0f} turns)\n")
    print(f"{'depth':>7}{'shipped':>10}{'my BM25 turn':>15}{'my BM25 prop':>15}{'prop - turn':>14}")
    table = []
    for k in args.depths:
        sh, tu, pr = rec[k]["shipped"] / N, rec[k]["turn"] / N, rec[k]["prop"] / N
        print(f"{k:>7}{sh:>10.4f}{tu:>15.4f}{pr:>15.4f}{pr - tu:>+14.4f}")
        table.append({"depth": k, "shipped": round(sh, 4), "my_turn": round(tu, 4),
                      "my_prop": round(pr, 4), "prop_minus_turn": round(pr - tu, 4)})

    med = {nm: float(np.median([r for r in v if r])) for nm, v in gold_rank.items()}
    print(f"\nmedian rank of gold:  turn {med['turn']:.0f}   prop {med['prop']:.0f}")

    Path(args.out).write_text(json.dumps({
        "_what": "proposition-level vs turn-level BM25 indexing, fit split",
        "_measurement_only": True,
        "_the_reading": ("prop_minus_turn is the isolated effect of the UNIT, because both columns "
                         "use the same BM25 implementation. the shipped column is context only."),
        "control_fit_r1": r1, "n": N,
        "mean_propositions_per_query": float(np.mean(nprop)),
        "input_recall": table,
        "median_gold_rank": med,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {Path(args.out).relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
