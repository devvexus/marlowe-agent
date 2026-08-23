"""Audit the QA number: decompose failures into RETRIEVAL vs GENERATION vs JUDGE.

Joins qa-rows.json (answers, judgments) with the dump (was gold inside the injected top-3?)
and classifies every failure:

  GOLD-NOT-INJECTED   retrieval miss -- the pick stage never handed the answerer the evidence
  NEI                 answerer claimed NOT_ENOUGH_INFORMATION even though gold WAS injected
                      -> generator/harness failure, not memory failure
  WRONG-VALUE         gold injected, model answered, judge said wrong -> real error or judge strictness
  JUDGE-UNPARSEABLE   excluded

    python tools/qa_audit.py --rows runs/session-m0c-n/qa-rows.json \
        --dump runs/session-m0c-n/qa-holding-run/heldout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from reach_pools import load_pools  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--dump", type=Path, required=True)
    args = ap.parse_args()

    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    pools, _ = load_pools(args.dump)

    def gold_in_injected(q: str, n_mem: int) -> bool | None:
        p = pools.get(q)
        if p is None:
            return None
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        g = [bool(c.is_gold) for c in p.candidates]
        return any(g[i] for i in cur[:max(n_mem, 0)])

    buckets = {"gold-not-injected": [], "NEI": [], "wrong-value": [],
               "correct": [], "judge-unparseable": []}
    for r in rows:
        q = r["query_id"]
        gi = gold_in_injected(q, r["n_memories"])
        ans = r["answer"] or ""
        nei = "not_enough_information" in ans.lower().replace(" ", "") or \
            "NOT_ENOUGH_INFORMATION" in ans
        if r["correct"] is None:
            buckets["judge-unparseable"].append(r)
        elif r["correct"]:
            buckets["correct"].append(r)
        elif gi is False:
            buckets["gold-not-injected"].append(r)
        elif nei:
            buckets["NEI"].append(r)
        else:
            buckets["wrong-value"].append(r)

    total = len(rows)
    print(f"graded rows: {total}")
    for name, rs in buckets.items():
        print(f"  {name:18} {len(rs):4d}  ({len(rs)/total:.1%})")

    # THE number the user wants: conversion WHEN gold was injected
    gi_rows = [r for r in rows if (gold_in_injected(r["query_id"], r["n_memories"])) is True]
    gi_correct = sum(1 for r in gi_rows if r["correct"])
    print(f"\n*** accuracy GIVEN gold was among injected memories: "
          f"{gi_correct}/{len(gi_rows)} = {gi_correct / max(len(gi_rows),1):.4f} ***")
    no_gi = [r for r in rows if gold_in_injected(r["query_id"], r["n_memories"]) is False]
    nc = sum(1 for r in no_gi if r["correct"])
    print(f"    accuracy when gold NOT injected: {nc}/{len(no_gi)} = "
          f"{nc / max(len(no_gi),1):.4f}")

    # failure samples for eyeballing
    for name in ("NEI", "wrong-value"):
        print(f"\n-- {name} samples --")
        for r in buckets[name][:6]:
            print(f"  [{r['category']}] {r['query_id']}: {r['answer'][:110]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
