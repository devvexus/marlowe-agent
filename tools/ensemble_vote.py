"""Do independent cross-encoders vote the top-2 better than the incumbent decides it alone?

    python tools/ensemble_vote.py

**Measurement only. No training, nothing ships.**

## Why this is not another perturbation

Twelve tie-breaks have now been measured on the rank-1/rank-2 decision. Every one either died
outright or produced +4 to +6 confined to cross-encoder gaps below 0.084 -- the band where the
shipped model's two scores are effectively identical and ANY nudge reshuffles them. A blind swap in
that band scores +5, which is more than the span reader or sentence MaxP achieved, and neither of
those ever made a correct call outside it.

The common defect: **they all perturb the SAME score.** A monotone or near-monotone tweak of one
model's output can only redistribute that model's own ties.

**A second model has different errors.** It can be confident and right exactly where the incumbent
is confident and wrong -- which is the one property none of the twelve possessed, and the only way
to reach the 21 failures whose gaps sit above the near-tie band.

Session I fetched, digest-pinned and gated nine models across four architectures and recorded
ensembling as "deferred as UNMEASURED -- not closed, not refuted, not run".

## Voting, not averaging, and the reason matters

The frontier sweep measured these models' standalone fit R@1 from 0.4803 to 0.7729. Averaging their
logits would let a model that is 27 points worse drag the incumbent, and the scales are not
comparable across architectures anyway (bge and jina are XLM-RoBERTa, the MiniLMs are BERT).

So each model casts **one vote on the pair** -- "is A better than B" -- which is calibration-free
and scale-free. The incumbent's own preference is one vote among them.

## THE TEST THAT DECIDES IT

Not the net. **Does it fire correctly ABOVE the 0.084 band?** Every prior mechanism scored 0 there.
A rule that only ever helps inside the coin-flip band is a coin flip with extra steps, however good
its headline looks.
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

OUT = REPO / "runs" / "session-m0c-m" / "ensemble-vote.json"
NEAR_TIE = 0.084
MAX_SEQ = 256

# The incumbent first; it is the decision being challenged, not a peer.
INCUMBENT = "ms-marco-MiniLM-L-2-v2-ft-session-j"
# Voters, spanning capacity AND architecture. Standalone fit R@1 from the frontier sweep in
# brackets -- carried so a weak voter is a known weak voter rather than a surprise.
VOTERS = [
    "ms-marco-MiniLM-L-6-v2-ft-session-j",   # 0.7467
    "ms-marco-MiniLM-L-12-v2",               # 0.6201
    "ms-marco-MiniLM-L-4-v2",                # 0.6157
    "ms-marco-MiniLM-L-6-v2",                # 0.6114
    "bge-reranker-base",                     # 0.5895  -- XLM-R, different family
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="CUDAExecutionProvider")
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

    # The pairs to adjudicate: every query's shipped top-2.
    pairs = {}
    for qid, pool in pools.items():
        o = [int(i) for i in orders[qid][:2]]
        t = texts_all.get(qid, {})
        s = [pool.candidates[i].rerank_score for i in o]
        pairs[qid] = {
            "q": pool.question,
            "a": t.get(pool.candidates[o[0]].turn_id) or "",
            "b": t.get(pool.candidates[o[1]].turn_id) or "",
            "gold_a": bool(pool.gold[o[0]]),
            "gold_b": bool(pool.gold[o[1]]),
            "ce_gap": (s[0] - s[1]) if None not in s else None,
            "votes": {},
        }

    for name in VOTERS:
        try:
            ce = R.load(name, provider=args.provider)
        except Exception as e:  # noqa: BLE001
            print(f"{name:<38} REFUSED: {type(e).__name__}: {str(e)[:80]}")
            continue
        t0 = time.perf_counter()
        for d in pairs.values():
            sa = ce.score(d["q"], d["a"], MAX_SEQ) if d["a"] else -1e9
            sb = ce.score(d["q"], d["b"], MAX_SEQ) if d["b"] else -1e9
            d["votes"][name] = "a" if sa >= sb else "b"
        agree = np.mean([d["votes"][name] == "a" for d in pairs.values()])
        print(f"{name:<38} agrees with incumbent on {agree:.3f}   "
              f"{(time.perf_counter()-t0)/len(pairs)*1000:.0f} ms/pair-set")

    voters = [v for v in VOTERS if all(v in d["votes"] for d in pairs.values())]
    print(f"\n{len(voters)} voters usable\n")

    def evaluate(rule, label) -> dict:
        gained = lost = 0
        out_gain = out_loss = out_noop = 0
        for d in pairs.values():
            if not rule(d):
                continue
            if d["gold_b"] and not d["gold_a"]:
                gained += 1
                if d["ce_gap"] is not None and d["ce_gap"] > NEAR_TIE:
                    out_gain += 1
            elif d["gold_a"] and not d["gold_b"]:
                lost += 1
                if d["ce_gap"] is not None and d["ce_gap"] > NEAR_TIE:
                    out_loss += 1
            elif d["ce_gap"] is not None and d["ce_gap"] > NEAR_TIE:
                out_noop += 1
        return {
            "rule": label, "flips_gained": gained, "flips_lost": lost,
            "net": gained - lost, "r1": round(r1 + (gained - lost) / len(pairs), 4),
            "above_near_tie": {"gained": out_gain, "lost": out_loss, "noop": out_noop},
        }

    arms = []
    for k in range(1, len(voters) + 1):
        arms.append(evaluate(
            lambda d, k=k: sum(1 for v in voters if d["votes"][v] == "b") >= k,
            f"swap if >= {k} of {len(voters)} voters prefer rank-2",
        ))
    # unanimity, and unanimity restricted to the near-tie band
    arms.append(evaluate(
        lambda d: all(d["votes"][v] == "b" for v in voters),
        "swap if ALL voters prefer rank-2",
    ))
    arms.append(evaluate(
        lambda d: all(d["votes"][v] == "b" for v in voters)
        and d["ce_gap"] is not None and d["ce_gap"] <= NEAR_TIE,
        "unanimous AND inside the near-tie band",
    ))

    print(f"{'rule':<48}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}   >0.084 g/l/n")
    for a in arms:
        o = a["above_near_tie"]
        print(f"{a['rule']:<48}{a['flips_gained']:>6}{a['flips_lost']:>6}{a['net']:>6}"
              f"{a['r1']:>9.4f}   {o['gained']}/{o['lost']}/{o['noop']}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "independent cross-encoders voting the shipped top-2, fit split",
        "_measurement_only": True,
        "_decisive_test": (
            "does any rule fire CORRECTLY above the 0.084 near-tie band? every prior mechanism "
            "scored 0 there, which is what makes them coin flips with extra steps."
        ),
        "control_fit_r1": r1, "incumbent": INCUMBENT, "voters": voters,
        "near_tie_threshold": NEAR_TIE, "arms": arms,
        "pairs": {k: {kk: vv for kk, vv in v.items() if kk not in ("a", "b", "q")}
                  for k, v in pairs.items()},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
