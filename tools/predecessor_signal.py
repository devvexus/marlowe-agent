"""Does the turn BEFORE a candidate say anything about whether that candidate holds the answer?

    python tools/predecessor_signal.py --top 3

**Reach check first, rule second. Measurement only.**

## The idea, and why it is not the turn-pair arm

A conversational turn is a RESPONSE. "By the way, I just baked a chocolate cake" did not manifest
from nothing -- something prompted it. If an answer-bearing turn is systematically preceded by
something different from what precedes a distractor, the predecessor is a free feature we have
never read.

M0c Session A's turn-pair arm (R4) asked a DIFFERENT question: *is the gold the other half of
rank-1's own exchange?* It measured 2-3 cases and a +0.0087 ceiling, and it is not this. This asks
whether **each candidate's own predecessor discriminates that candidate.**

Two predecessors are read, because conversation alternates:

  * **prev-1** -- the immediately preceding turn (the other speaker: what prompted this)
  * **prev-2** -- the same speaker's previous turn (what this person was already saying)

## THE CONSTRAINT THIS SESSION EARNED, applied here from the start

Four mechanisms cleared their bar on fit and died on held-out: depth (+0.0174 -> +0.0044), the
retrain (+0.0698 -> +0.0087), the joint pairwise encoder (+0.0655 -> +0.0044), and context decay
(+0.0305 -> **-0.0087**).

**Decay was never trained.** Only its lambda was chosen on fit -- one hyperparameter from ten cells
-- and even that did not transfer. **At n=229, threshold selection overfits.** So:

1. The **reach check comes first**: does the predecessor's score separate gold from non-gold at
   all? If not, nothing downstream can matter and this ends in twenty minutes.
2. Any rule is scored **parameter-free** -- fixed weight 1.0, or a pure tie-break -- because a rule
   with a knob is already suspect here. The lambda sweep is printed for shape only and is
   explicitly NOT the result.

## The bar, unchanged

Rank 1 is gold **110 times against 26**, so a reordering rule must be right on >81% of what it
touches. And the test twenty-one mechanisms have failed: **does it fire correctly above a 0.084
cross-encoder gap?**
"""

from __future__ import annotations

import argparse
import json
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

OUT = REPO / "runs" / "session-m0c-m" / "predecessor-signal.json"
NEAR_TIE = 0.084
MAX_SEQ = 256


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ms-marco-MiniLM-L-2-v2-ft-session-j")
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--heldout", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    pool_dir = (REPO / "runs" / "session-k" / "heldout") if args.heldout else FIT_POOLS
    expect = 0.6725 if args.heldout else CONTROL_R1
    pools, _ = load_pools(pool_dir)
    texts_all = turn_texts()
    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - expect) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed R@1 {r1} != published {expect}")
    print(f"control: {'HELD-OUT' if args.heldout else 'fit'} R@1 {r1}  ({len(pools)} queries)")

    ce = R.load(args.model, provider=args.provider)
    rows, lat, missing = {}, [], 0
    for n, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        t = texts_all.get(qid, {})
        idxs = [int(i) for i in orders[qid][: args.top]]
        rec = []
        t0 = time.perf_counter()
        for i in idxs:
            c = pool.candidates[i]
            # turn_id is "{session_id}-{turn_index}", so the predecessors are addressable directly.
            p1 = p2 = None
            if c.sid is not None and c.turn_index is not None:
                if c.turn_index >= 1:
                    p1 = t.get(f"{c.sid}-{c.turn_index - 1}")
                if c.turn_index >= 2:
                    p2 = t.get(f"{c.sid}-{c.turn_index - 2}")
            if p1 is None:
                missing += 1
            s1 = ce.score(pool.question, p1, MAX_SEQ) if p1 else None
            s2 = ce.score(pool.question, p2, MAX_SEQ) if p2 else None
            rec.append({
                "is_gold": bool(pool.gold[i]),
                "whole": c.rerank_score,
                "prev1": s1, "prev2": s2,
                "has_prev1": p1 is not None, "turn_index": c.turn_index,
            })
        lat.append((time.perf_counter() - t0) * 1000.0)
        rows[qid] = rec
        if n % 50 == 0:
            print(f"  {n}/{len(pools)}  {np.median(lat):.0f} ms/query")

    N = len(rows)

    # ---- REACH CHECK: does the predecessor separate gold from non-gold at all? ----------------
    print(f"\nREACH CHECK -- predecessor score by class ({missing} candidates had no predecessor)")
    print(f"{'':22}{'GOLD median':>14}{'NON-GOLD':>12}{'delta':>9}{'n gold':>8}")
    reach = {}
    for nm in ("prev1", "prev2"):
        g = [c[nm] for r in rows.values() for c in r if c["is_gold"] and c[nm] is not None]
        b = [c[nm] for r in rows.values() for c in r if not c["is_gold"] and c[nm] is not None]
        d = float(np.median(g) - np.median(b)) if g and b else 0.0
        reach[nm] = {"gold_median": float(np.median(g)) if g else None,
                     "nongold_median": float(np.median(b)) if b else None,
                     "delta": round(d, 4), "n_gold": len(g), "n_nongold": len(b)}
        print(f"{nm:<22}{np.median(g):>14.4f}{np.median(b):>12.4f}{d:>+9.4f}{len(g):>8}")
    # the same contrast RELATIVE to the candidate's own score -- a predecessor that is high
    # because the whole session is on-topic is not a signal about this candidate
    for nm in ("prev1", "prev2"):
        g = [c[nm] - c["whole"] for r in rows.values() for c in r
             if c["is_gold"] and c[nm] is not None and c["whole"] is not None]
        b = [c[nm] - c["whole"] for r in rows.values() for c in r
             if not c["is_gold"] and c[nm] is not None and c["whole"] is not None]
        d = float(np.median(g) - np.median(b))
        reach[f"{nm}_minus_own"] = {"gold_median": float(np.median(g)),
                                    "nongold_median": float(np.median(b)), "delta": round(d, 4)}
        print(f"{nm + ' - own score':<22}{np.median(g):>14.4f}{np.median(b):>12.4f}{d:>+9.4f}")

    def whole(c):
        return c["whole"] if c["whole"] is not None else -1e9

    def ev(key, label):
        g = l = corr = 0
        og = ol = on = 0
        for rec in rows.values():
            j = int(np.argmax([key(c) for c in rec]))
            corr += int(rec[j]["is_gold"])
            w = [whole(c) for c in rec]
            gap = w[0] - w[1] if len(w) > 1 else None
            out = gap is not None and gap > NEAR_TIE
            if j != 0:
                if rec[j]["is_gold"] and not rec[0]["is_gold"]:
                    g += 1; og += int(out)
                elif rec[0]["is_gold"] and not rec[j]["is_gold"]:
                    l += 1; ol += int(out)
                elif out:
                    on += 1
        return {"rule": label, "gained": g, "lost": l, "net": g - l,
                "r1": round(corr / N, 4), "above": {"g": og, "l": ol, "n": on}}

    def pv(c, nm):
        return c[nm] if c[nm] is not None else -1e9

    arms = [ev(whole, "control (shipped)")]
    # PARAMETER-FREE, which is the only form worth believing after four threshold collapses.
    arms.append(ev(lambda c: whole(c) + pv(c, "prev1"), "ce + prev1        (weight 1, no knob)"))
    arms.append(ev(lambda c: whole(c) + pv(c, "prev2"), "ce + prev2        (weight 1, no knob)"))
    arms.append(ev(lambda c: whole(c) + 0.5 * (pv(c, "prev1") + pv(c, "prev2")),
                   "ce + mean(prev1,prev2)"))
    arms.append(ev(lambda c: pv(c, "prev1"), "prev1 alone"))
    # shape only -- NOT the result, and the sweep is printed so a knob cannot be read as a finding
    for lam in (0.25, 0.5):
        arms.append(ev(lambda c, l=lam: whole(c) + l * pv(c, "prev1"), f"[shape only] ce + {lam}*prev1"))

    print(f"\n{'rule':<38}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}   >0.084 g/l/n")
    for a in arms:
        o = a["above"]
        print(f"{a['rule']:<38}{a['gained']:>6}{a['lost']:>6}{a['net']:>6}{a['r1']:>9.4f}"
              f"   {o['g']}/{o['l']}/{o['n']}")

    dest = Path(args.out) if args.out else (
        OUT.with_name("predecessor-signal-heldout.json") if args.heldout else OUT)
    dest.write_text(json.dumps({
        "_what": "does a candidate's PRECEDING turn discriminate whether it holds the answer",
        "_measurement_only": True,
        "_split": "heldout" if args.heldout else "fit",
        "_note": ("rules are scored PARAMETER-FREE at weight 1.0. lambda-swept cells are printed "
                  "for shape and are explicitly not the result: four mechanisms this session died "
                  "because their operating point was selected on fit, including one that was never "
                  "trained at all."),
        "control_r1": r1, "top": args.top, "candidates_without_predecessor": missing,
        "reach_check": reach, "arms": arms,
        "ms_per_query": round(float(np.median(lat)), 1), "rows": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\n{np.median(lat):.0f} ms/query")
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
