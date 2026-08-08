"""R4 -- reachability for turn-pair chunking, the last structural idea and the one STATE.md
names as the cheapest untested.

Conditional accuracy is the binding factor. R@1 = input_recall x conditional_accuracy, the slate
work moves the first and R3/m0c_slate_rules showed the second falls to meet it. Every reranking arm
tried this session is a null. So the remaining question is whether the UNIT OF INDEXING is wrong.

The hypothesis, from STATE.md: 87.7% of gold is user-authored, and the distractors that beat it are
47.1% assistant-authored and 1.9x longer. A user question and the assistant reply that answers it
are one exchange but two indexed turns, so the reranker is asked to choose between two halves of
the same thing. If the pair were one unit, that particular failure could not occur -- and the pair
also carries the answer text alongside the question text, which is what a query actually matches.

This measures the CEILING that reframing offers, before any ingest change is contemplated:

  1. How many recoverable failures have their gold ADJACENT to the wrong rank 1? Those are fixed
     for free by pairing, because the two candidates merge into one.
  2. How many golds are adjacent to ANOTHER gold? Those merge harmlessly.
  3. How many golds would be merged into a unit whose OTHER half is a strong distractor elsewhere
     in the slate -- the failure mode pairing INTRODUCES, which must be counted or the ceiling is
     an advertisement rather than a measurement.

It does not measure what pairing does to retrieval, which changes the candidate pool, the BM25
statistics and the dense embeddings all at once. That would need a full re-run. This says whether
that re-run is worth a session.

Prints numbers. Applies nothing. Reports fit and held-out side by side; the held-out column is
descriptive of the already-published ranking and fits nothing.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
OUT = REPO / "runs" / "session-m0c" / "reach-r4-turnpair.json"


def sess(t: str) -> str:
    return t.rsplit("-", 1)[0]


def tix(t: str) -> int:
    try:
        return int(t.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return -10_000


def pair_id(tid: str) -> str:
    """The chunk a turn falls into under (user, assistant) pairing. LongMemEval haystacks
    alternate user/assistant from index 0, so turns 2k and 2k+1 form exchange k. Derived from the
    index rather than from the role, because the role is what the pairing is meant to stop the
    ranker keying on."""
    return f"{sess(tid)}#{tix(tid) // 2}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    report = {"_what": "ceiling offered by turn-pair chunking, measured on the existing slates",
              "_what_it_is_not": "a measurement of what pairing does to retrieval; that changes "
                                 "the pool, the BM25 statistics and the embeddings at once and "
                                 "needs a full re-run"}

    print("=" * 92)
    print("R4 -- TURN-PAIR CHUNKING: what does merging (user, assistant) into one unit buy?")
    print("=" * 92)

    for split in ("fit", "heldout"):
        recs = json.loads(Path(str(SLATES).format(split=split)).read_text(
            encoding="utf-8"))["records"]
        n = len(recs)
        fails = [r for r in recs if r["gold_in_slate"] and not r["correct"]]

        # 1. failures where the gold is the OTHER HALF of rank 1's own exchange
        same_pair = 0
        adjacent_gaps = Counter()
        for r in fails:
            gi = r["gold"].index(True)
            t0, tg = r["turn_ids"][0], r["turn_ids"][gi]
            if pair_id(t0) == pair_id(tg):
                same_pair += 1
            if sess(t0) == sess(tg):
                adjacent_gaps[tix(tg) - tix(t0)] += 1

        # 2. what pairing costs: a gold merged with a half that is ALSO in the slate and scores
        #    higher than the gold does. Under pairing the merged unit inherits one score, so this
        #    is not automatically a loss -- but it is where the risk lives, so it is counted.
        merged_with_slate_member = 0
        for r in recs:
            if not r["gold_in_slate"]:
                continue
            gi = r["gold"].index(True)
            pg = pair_id(r["turn_ids"][gi])
            for j, t in enumerate(r["turn_ids"]):
                if j != gi and pair_id(t) == pg:
                    merged_with_slate_member += 1
                    break

        # 3. slate compression: how many of the ten candidates collapse
        compression = [len({pair_id(t) for t in r["turn_ids"]}) for r in recs]

        # 4. the role story STATE.md records, re-measured here
        gold_user = sum(1 for r in recs if r["gold_in_slate"]
                        and r["roles"][r["gold"].index(True)] == "user")
        gold_n = sum(1 for r in recs if r["gold_in_slate"])
        fail_top1_asst = sum(1 for r in fails if r["roles"][0] == "assistant")

        r1 = sum(r["correct"] for r in recs) / n
        ceiling = (sum(r["correct"] for r in recs) + same_pair) / n

        print()
        print(f"  {split}  (n={n}, recoverable failures {len(fails)})")
        print(f"    gold is the OTHER HALF of rank 1's own exchange   {same_pair:>3d} "
              f"({same_pair/max(len(fails),1):.0%} of failures)")
        print(f"    -> R@1 if exactly those are fixed and nothing breaks  "
              f"{r1:.4f} -> {ceiling:.4f}  ({ceiling-r1:+.4f})")
        print(f"    same-session gold-to-rank1 turn gaps: "
              f"{dict(sorted(adjacent_gaps.items())[:8])}")
        print(f"    gold shares a pair with another slate member       "
              f"{merged_with_slate_member:>3d} of {gold_n}  <- where pairing's risk lives")
        print(f"    slate compresses from 10 units to a median of      "
              f"{np.median(compression):>3.0f}")
        print(f"    gold is user-authored {gold_user}/{gold_n} ({gold_user/gold_n:.1%});  "
              f"rank 1 on failures is assistant-authored {fail_top1_asst}/{len(fails)} "
              f"({fail_top1_asst/max(len(fails),1):.1%})")

        report[split] = {
            "n": n, "recoverable_failures": len(fails),
            "gold_is_other_half_of_rank1_pair": same_pair,
            "r_at_1_now": round(r1, 4),
            "r_at_1_ceiling_if_those_fixed": round(ceiling, 4),
            "delta": round(ceiling - r1, 4),
            "same_session_gaps": {str(k): v for k, v in sorted(adjacent_gaps.items())},
            "gold_shares_pair_with_another_slate_member": merged_with_slate_member,
            "gold_in_slate_n": gold_n,
            "median_units_after_pairing": float(np.median(compression)),
            "gold_user_authored": f"{gold_user}/{gold_n}",
            "rank1_assistant_authored_on_failures": f"{fail_top1_asst}/{len(fails)}",
        }

    print()
    print("-" * 92)
    print("READING")
    print("-" * 92)
    f, h = report["fit"], report["heldout"]
    print(f"  The free win -- gold merging with the very candidate that beat it -- is "
          f"{f['gold_is_other_half_of_rank1_pair']} queries on fit and "
          f"{h['gold_is_other_half_of_rank1_pair']} on held-out,")
    print(f"  worth {f['delta']:+.4f} and {h['delta']:+.4f} R@1 respectively. That is the part of "
          f"the idea that is")
    print("  arithmetic rather than hope. Everything beyond it depends on pairing changing what")
    print("  retrieval finds, which this script cannot see and a full re-run would have to show.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
