"""Find the peak-scoring span in a candidate, expand around it, and measure how fast the score DECAYS.

    python tools/context_decay.py --top 3

**Measurement only. No training, nothing ships.**

## The hypothesis, and why it is not max-pooling

Max-pooling asks "what is the best single piece of this candidate?" and throws away everything
else. It has been measured three times and the same mechanism kills it every time: isolating the
peak also isolates the DISTRACTOR's peak, and a question-echoing sentence in isolation is a
maximally query-matching object. Retrieval-level proposition indexing -0.0786 input recall; top-5
MaxP net -4; top-3 MaxP net +1.

**This uses the SHAPE of the score profile instead of its maximum.**

    a distractor matches because ONE span echoes the question's wording.
    nothing around that span is about the query, so widening the window
    dilutes the score FAST.

    a gold turn matches because it CONTAINS the answer, embedded in
    context that is also about the subject, so widening the window
    holds the score UP.

So the feature is not the peak, it is **peak minus expanded** -- how quickly relevance falls off
when you stop cherry-picking. A sharp cliff means a narrow lexical coincidence. A plateau means
sustained topical support.

Concretely, for each candidate: split into propositions, find the peak-scoring one, then score
nested windows centred on it -- [p], [p-1..p+1], [p-2..p+2], the whole turn -- and read the profile.

## The bar, unchanged

Rank 1 is already gold **110 times against 26** in the head population, so any rule must be right
on more than 81% of the pairs it touches. And the test that every one of twenty mechanisms has
failed: **does it fire CORRECTLY above a 0.084 cross-encoder gap?** Helping only inside the
near-tie band is a coin flip with extra steps -- a blind swap there scores +5.
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

OUT = REPO / "runs" / "session-m0c-m" / "context-decay.json"
OUT_HO = REPO / "runs" / "session-m0c-m" / "context-decay-heldout.json"
NEAR_TIE = 0.084
MAX_SEQ = 256
_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_WORDS = 4


def propositions(text: str) -> list[str]:
    raw = [s.strip() for s in _SPLIT.split(text or "") if s.strip()]
    out: list[str] = []
    for s in raw:
        if out and len(s.split()) < MIN_WORDS:
            out[-1] += " " + s
        else:
            out.append(s)
    return out or ([text] if text else [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ms-marco-MiniLM-L-2-v2-ft-session-j")
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--heldout", action="store_true", help="SPEND A HELD-OUT READ")
    ap.add_argument("--out", default=str(OUT))
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
    print(f"control: {'HELD-OUT' if args.heldout else 'fit'} R@1 {r1}  ({len(pools)} queries)  top-{args.top}")

    ce = R.load(args.model, provider=args.provider)
    rows, lat = {}, []
    for n, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        t = texts_all.get(qid, {})
        idxs = [int(i) for i in orders[qid][: args.top]]
        rec = []
        t0 = time.perf_counter()
        for i in idxs:
            text = t.get(pool.candidates[i].turn_id) or ""
            props = propositions(text)
            k = len(props)
            piece = [ce.score(pool.question, p, MAX_SEQ) for p in props]
            pk = int(np.argmax(piece))
            # Nested windows centred on the peak proposition.
            def win(rad: int) -> float:
                lo, hi = max(0, pk - rad), min(k, pk + rad + 1)
                return ce.score(pool.question, " ".join(props[lo:hi]), MAX_SEQ)
            w0 = piece[pk]
            w1 = win(1) if k > 1 else w0
            w2 = win(2) if k > 2 else w1
            whole = pool.candidates[i].rerank_score
            rec.append({
                "is_gold": bool(pool.gold[i]),
                "whole": whole,
                "n_props": k,
                "peak": w0, "w1": w1, "w2": w2,
                # DECAY: how far the score falls when the window widens. Large = narrow
                # coincidence. Small/negative = the surrounding context supports the match.
                "decay_1": w0 - w1,
                "decay_full": w0 - (whole if whole is not None else w0),
            })
        lat.append((time.perf_counter() - t0) * 1000.0)
        rows[qid] = rec
        if n % 40 == 0:
            print(f"  {n}/{len(pools)}  {np.median(lat):.0f} ms/query")

    N = len(rows)

    # ---- is the decay actually different for gold? the reach check before any rule ------------
    g_d1 = [c["decay_1"] for r in rows.values() for c in r if c["is_gold"]]
    n_d1 = [c["decay_1"] for r in rows.values() for c in r if not c["is_gold"]]
    g_df = [c["decay_full"] for r in rows.values() for c in r if c["is_gold"]]
    n_df = [c["decay_full"] for r in rows.values() for c in r if not c["is_gold"]]
    print(f"\ndecay to window+-1     GOLD median {np.median(g_d1):+.4f} (n={len(g_d1)})   "
          f"NON-GOLD {np.median(n_d1):+.4f} (n={len(n_d1)})")
    print(f"decay to the full turn GOLD median {np.median(g_df):+.4f}   "
          f"NON-GOLD {np.median(n_df):+.4f}")
    print("  (hypothesis predicts GOLD decays LESS -- a smaller number)")

    def ev(key, label):
        g = l = corr = 0
        og = ol = on = 0
        for rec in rows.values():
            j = int(np.argmax([key(c) for c in rec]))
            corr += int(rec[j]["is_gold"])
            w = [(c["whole"] if c["whole"] is not None else -1e9) for c in rec]
            gap = w[0] - w[1] if len(w) > 1 else None
            outside = gap is not None and gap > NEAR_TIE
            if j != 0:
                if rec[j]["is_gold"] and not rec[0]["is_gold"]:
                    g += 1; og += int(outside)
                elif rec[0]["is_gold"] and not rec[j]["is_gold"]:
                    l += 1; ol += int(outside)
                elif outside:
                    on += 1
        return {"rule": label, "gained": g, "lost": l, "net": g - l,
                "r1": round(corr / N, 4), "above": {"g": og, "l": ol, "n": on}}

    def whole(c):
        return c["whole"] if c["whole"] is not None else -1e9

    arms = [ev(whole, "control (shipped)")]
    for lam in (0.25, 0.5, 1.0, 2.0):
        arms.append(ev(lambda c, l=lam: whole(c) + l * c["decay_1"], f"ce + {lam}*decay(+-1)"))
    for lam in (0.25, 0.5, 1.0):
        arms.append(ev(lambda c, l=lam: whole(c) + l * c["decay_full"], f"ce + {lam}*decay(full)"))
    # the direction the hypothesis PREDICTED, retained as the sign control: gold was predicted to
    # decay LESS and in fact decays 10x MORE, so this arm must lose. A feature that "helps" in both
    # directions is measuring nothing.
    arms.append(ev(lambda c: whole(c) - 0.5 * c["decay_1"], "SIGN CONTROL: ce - 0.5*decay"))
    arms.append(ev(lambda c: c["w1"], "score of the peak window +-1"))
    arms.append(ev(lambda c: c["w2"], "score of the peak window +-2"))

    print(f"\n{'rule':<30}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}   >0.084 g/l/n")
    for a in arms:
        o = a["above"]
        print(f"{a['rule']:<30}{a['gained']:>6}{a['lost']:>6}{a['net']:>6}{a['r1']:>9.4f}"
              f"   {o['g']}/{o['l']}/{o['n']}")

    dest = Path(args.out) if args.out != str(OUT) else (OUT_HO if args.heldout else OUT)
    dest.write_text(json.dumps({
        "_what": "peak-window score decay as a tie-break over the shipped top-k, fit split",
        "_measurement_only": True,
        "_hypothesis": ("a distractor matches on one echoing span and DECAYS fast when the window "
                        "widens; a gold answer sits in supporting context and holds up"),
        "control_fit_r1": r1, "top": args.top, "model": args.model,
        "decay_by_class": {
            "decay_pm1": {"gold_median": float(np.median(g_d1)), "nongold_median": float(np.median(n_d1))},
            "decay_full": {"gold_median": float(np.median(g_df)), "nongold_median": float(np.median(n_df))},
        },
        "arms": arms, "ms_per_query": round(float(np.median(lat)), 1), "rows": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\n{np.median(lat):.0f} ms/query")
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
