"""Give a small LLM the query and the top-k turns; it names the one that answers. Measured.

    python tools/llm_pick.py --model qwen2.5:0.5b-instruct --top 3

**Measurement only. Nothing ships, no Rust, no training.**

## Why this is the last thing to try, and why it is structurally different

Twenty post-hoc mechanisms, nine pretrained cross-encoders, an ensemble, a retrain and a joint
pairwise encoder have all been measured on the rank-1/rank-2 decision. Every one either died, or
was confined to cross-encoder gaps below 0.084, or -- for the three that were TRAINED on the fit
split -- posted a large fit gain that collapsed on held-out:

    depth 30                 +0.0174 fit -> +0.0044 held-out    4x
    retrain arm B            +0.0698 fit -> +0.0087 held-out    8x
    joint pairwise encoder   +0.0655 fit -> +0.0044 held-out   15x

**An off-the-shelf LLM is not trained on our fit split.** It has never seen the corpus, the
rankings, or the negatives. So unlike arm B and duoBERT, its fit number cannot be inflated by
memorisation -- which after three collapses is the property that matters most.

And it can read all k candidates in one context and reason over them, which is the capability
nothing else had: the shipped cross-encoder is pointwise and cannot represent "B answers and A
merely restates".

## The controls

* **`--shuffle`** -- present the candidates in a permuted order. A model that just says "1" scores
  0.7555 by echoing the incumbent, because rank 1 is already gold 81% of the time. **If the
  shuffled and unshuffled results differ materially, the model is reading position, not content.**
* **the pick distribution** is reported. A degenerate model that always answers "1" is visible
  immediately rather than showing up as a suspiciously flat result.
* **unparseable output is a NO-OP**, keeping rank 1 -- never a silent drop, never a random pick.
* the **above-0.084 breakdown**, because that is the bar every other mechanism failed: helping only
  inside the near-tie band is a coin flip with extra steps.

Greedy decode at temperature 0 with a fixed seed: a ranking that cannot be reproduced is not a
ranking this project can ship.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OLLAMA = "http://localhost:11434/api/chat"
OUT = REPO / "runs" / "session-m0c-m" / "llm-pick.json"
NEAR_TIE = 0.084

SYSTEM = (
    "You are given a question about a person's past conversations, and several numbered memories. "
    "Exactly one memory contains the answer. The others are about a similar topic but do NOT "
    "contain the answer. Reply with the number of the memory that contains the answer. "
    "Reply with the number ONLY - no words, no punctuation, no explanation."
)


def ask(model: str, question: str, docs: list[str], timeout: int = 120) -> tuple[str, float]:
    blocks = "\n\n".join(f"{i + 1}. {d}" for i, d in enumerate(docs))
    user = f"Question: {question}\n\nMemories:\n{blocks}\n\nWhich number contains the answer?"
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "top_p": 1.0, "seed": 7, "num_predict": 8},
    }
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        out = json.loads(fh.read())
    return out["message"]["content"].strip(), (time.perf_counter() - t0) * 1000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:0.5b-instruct")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--shuffle", action="store_true", help="permute candidate order (position control)")
    ap.add_argument("--heldout", action="store_true", help="SPEND A HELD-OUT READ")
    ap.add_argument("--limit", type=int, default=0)
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
    split = "HELD-OUT" if args.heldout else "fit"
    print(f"control: {split} R@1 {r1}  ({len(pools)} queries)  model={args.model}  top-{args.top}"
          f"{'  SHUFFLED' if args.shuffle else ''}")

    qids = sorted(pools)
    if args.limit:
        qids = qids[: args.limit]

    rng = np.random.default_rng(7)
    rows, lat, picks, unparsed = {}, [], Counter(), 0
    for n, qid in enumerate(qids, 1):
        pool = pools[qid]
        t = texts_all.get(qid, {})
        idxs = [int(i) for i in orders[qid][: args.top]]
        docs = [t.get(pool.candidates[i].turn_id) or "" for i in idxs]
        perm = list(range(len(idxs)))
        if args.shuffle:
            rng.shuffle(perm)
        shown = [docs[p] for p in perm]
        try:
            raw, ms = ask(args.model, pool.question, shown)
        except Exception as e:  # noqa: BLE001
            print(f"  {qid}: {type(e).__name__}: {str(e)[:70]}")
            continue
        lat.append(ms)
        m = re.search(r"\d+", raw)
        # Unparseable or out of range -> NO-OP, keep rank 1. Never a silent drop or a random pick.
        if m and 1 <= int(m.group()) <= len(shown):
            chosen = perm[int(m.group()) - 1]
        else:
            chosen = 0
            unparsed += 1
        picks[chosen] += 1
        rows[qid] = {
            "gold": [bool(pool.gold[i]) for i in idxs],
            "ce": [pool.candidates[i].rerank_score for i in idxs],
            "pick": chosen, "raw": raw[:24],
        }
        if n % 40 == 0:
            print(f"  {n}/{len(qids)}  {np.median(lat):.0f} ms/query  picks={dict(picks)}")

    N = len(rows)
    gain = lost = corr = 0
    og = ol = on = 0
    for d in rows.values():
        j = d["pick"]
        corr += int(d["gold"][j])
        gap = (d["ce"][0] - d["ce"][1]) if None not in d["ce"][:2] else None
        outside = gap is not None and gap > NEAR_TIE
        if j != 0:
            if d["gold"][j] and not d["gold"][0]:
                gain += 1; og += int(outside)
            elif d["gold"][0] and not d["gold"][j]:
                lost += 1; ol += int(outside)
            elif outside:
                on += 1

    res = {
        "_what": f"small-LLM top-{args.top} selection, {split} split",
        "_measurement_only": True,
        "model": args.model, "split": split, "top": args.top, "shuffled": args.shuffle,
        "decode": {"temperature": 0.0, "seed": 7, "num_predict": 8},
        "control_r1": r1, "n": N,
        "picked_rank_1_fraction": round(picks[0] / N, 4),
        "pick_distribution": {str(k + 1): v for k, v in sorted(picks.items())},
        "unparseable": unparsed,
        "flips_gained": gain, "flips_lost": lost, "net": gain - lost,
        "new_r1": round(corr / N, 4), "delta": round(corr / N - r1, 4),
        "above_near_tie": {"gained": og, "lost": ol, "noop": on},
        "ms_per_query": round(float(np.median(lat)), 1),
        "rows": rows,
    }
    dest = Path(args.out) if args.out else (
        OUT.with_name(f"llm-pick-{args.model.replace(':', '-')}"
                      f"{'-shuffled' if args.shuffle else ''}"
                      f"{'-heldout' if args.heldout else ''}.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'':16}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}{'delta':>9}   >0.084 g/l/n")
    print(f"{args.model[:16]:<16}{gain:>6}{lost:>6}{gain - lost:>6}{res['new_r1']:>9.4f}"
          f"{res['delta']:>+9.4f}   {og}/{ol}/{on}")
    print(f"\npicked rank 1 on {res['picked_rank_1_fraction']:.3f} of queries "
          f"(a model that always says 1 scores {r1})")
    print(f"pick distribution {res['pick_distribution']}   unparseable {unparsed}")
    print(f"{res['ms_per_query']} ms/query")
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
