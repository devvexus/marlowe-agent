"""Split each candidate into sentences, score the pieces, aggregate. Does it find a buried answer?

    python tools/sentence_maxp.py --top 5

**Measurement only. No training, no shipping. This is a scoring change over the existing graph.**

## The idea

Our worked failure `9a707b82` has a gold turn reading:

    "I'm excited to try making croissants again, and I think I'll also make some banana bread for
     the dinner party. I recently made a batch with walnuts... BY THE WAY, I JUST BAKED A CHOCOLATE
     CAKE for my friend's birthday party... Anyways, do you have any tips for banana bread?"

The answer is ONE clause in a turn dominated by croissants and banana bread. A whole-turn score
averages the answer away. Scoring each sentence and taking the best should surface it.

That is **MaxP** (Dai & Callan) and it is standard practice for long documents.

## THE REASON IT MIGHT BACKFIRE, stated before the run

Max-pooling rewards whichever candidate owns the single best-matching sentence — and our failures
are won by turns that ECHO THE QUESTION'S PHRASING. In `505af2f5` the question is *"I was thinking
of trying a new coffee creamer recipe. Any recommendations?"* and rank 1 is *"I'm thinking of trying
some new coffee flavors, do you have any recommendations for spring-themed coffee drinks?"* — a
near-perfect frame match. Isolated as its own sentence, that scores even higher.

So max-pooling may amplify exactly the failure it is meant to fix. Both directions are plausible,
which is why this is measured rather than argued.

**And one piece of our own evidence already cuts against the premise:** the "gold is buried in a
'by the way' aside" pattern was tested against the 173 correct cases and reads **39% of failures vs
47% of successes** — it is a property of the corpus, not of the failures. Burial being common does
not mean burial is what loses.

## Scored the only way that means anything

Flips GAINED against flips LOST on the head-probe population, where rank 1 is already gold **110
times against 26**. A rule must be right on more than 81% of the pairs it touches or it loses
ground. Correlations and mean-score improvements are not reported, because they look encouraging
and do not survive to the decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "sentence-maxp.json"
MAX_SEQ = 256
# Conversational text; a plain terminator split is adequate and has no tunable in it.
_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_WORDS = 3  # a fragment shorter than this is glued to its neighbour rather than scored alone


def sentences(text: str) -> list[str]:
    raw = [s.strip() for s in _SPLIT.split(text or "") if s.strip()]
    out: list[str] = []
    for s in raw:
        if out and len(s.split()) < MIN_WORDS:
            out[-1] = out[-1] + " " + s
        else:
            out.append(s)
    return out or ([text] if text else [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ms-marco-MiniLM-L-2-v2-ft-session-j")
    ap.add_argument("--provider", default="CPUExecutionProvider")
    ap.add_argument("--top", type=int, default=5)
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
    print(f"control: fit R@1 {r1}  ({len(pools)} queries)  top-{args.top}  {args.provider}")

    ce = R.load(args.model, provider=args.provider)
    rows, lat, nsent = {}, [], []
    for i, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        texts = texts_all.get(qid, {})
        idxs = [int(j) for j in orders[qid][: args.top]]
        rec = []
        t0 = time.perf_counter()
        for j in idxs:
            whole = texts.get(pool.candidates[j].turn_id) or ""
            ss = sentences(whole)
            nsent.append(len(ss))
            piece = [ce.score(pool.question, s, MAX_SEQ) for s in ss] if ss else []
            rec.append(
                {
                    "is_gold": bool(pool.gold[j]),
                    "whole": pool.candidates[j].rerank_score,
                    "n_sentences": len(ss),
                    "max": max(piece) if piece else -1e9,
                    "mean": float(np.mean(piece)) if piece else -1e9,
                    "sum": float(np.sum(piece)) if piece else -1e9,
                }
            )
        lat.append((time.perf_counter() - t0) * 1000.0)
        rows[qid] = rec
        if i % 40 == 0:
            print(f"  {i}/{len(pools)}  {np.median(lat):.0f} ms/query  {np.mean(nsent):.1f} sent/turn")

    n = len(rows)

    def evaluate(key) -> dict:
        gained = lost = 0
        correct = 0
        for rec in rows.values():
            base_gold = rec[0]["is_gold"]
            j = int(np.argmax([key(c) for c in rec]))
            new_gold = rec[j]["is_gold"]
            correct += int(new_gold)
            if new_gold and not base_gold:
                gained += 1
            elif base_gold and not new_gold:
                lost += 1
        return {"flips_gained": gained, "flips_lost": lost, "net": gained - lost,
                "r1": round(correct / n, 4), "delta": round(correct / n - r1, 4)}

    arms = {
        "whole (control, reproduces shipped)": evaluate(lambda c: c["whole"] if c["whole"] is not None else -1e9),
        "sentence MAX": evaluate(lambda c: c["max"]),
        "sentence MEAN": evaluate(lambda c: c["mean"]),
        "sentence SUM": evaluate(lambda c: c["sum"]),
    }
    for a in (0.25, 0.5, 1.0):
        arms[f"whole + {a}*max"] = evaluate(
            lambda c, a=a: (c["whole"] if c["whole"] is not None else -1e9) + a * c["max"]
        )

    print(f"\n{'arm':<38}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}{'delta':>9}")
    for k, v in arms.items():
        print(f"{k:<38}{v['flips_gained']:>6}{v['flips_lost']:>6}{v['net']:>6}"
              f"{v['r1']:>9.4f}{v['delta']:>+9.4f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_what": "sentence-level MaxP over the top-k, fit split",
                "_measurement_only": True,
                "model": args.model, "top": args.top, "provider": args.provider,
                "control_fit_r1": r1,
                "sentences_per_turn": {"mean": float(np.mean(nsent)), "median": float(np.median(nsent))},
                "ms_per_query": round(float(np.median(lat)), 1),
                "arms": arms,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nmean {np.mean(nsent):.1f} sentences/turn, {np.median(lat):.0f} ms/query on {args.provider}")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
