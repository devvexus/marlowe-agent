"""Why did max-over-per-cue-calibrated-precision lose at top-1?

Session D's floor failed: 0.4783 against a required 0.5478, and worse than the v2 linear gate's
0.4957 at every k. This script measures the mechanism rather than leaving it as a story.

**This is a diagnostic, not a search.** It does not re-fit, does not re-rank against gold, and
proposes no new operating point. Every number below is a descriptive statistic about the
artifact that already shipped and the run that already happened. The pre-registered response to
a failed floor is to report the finding; explaining it is part of reporting it.

The hypothesis it tests, stated before looking:

  Isotonic calibration maps a continuous score to a STEP FUNCTION. `max` over two step functions
  is constant across a wide band at the top, so the ranking has no resolution exactly where
  top-1 reads. Lexical alone orders its head by continuous BM25; max-fusion collapses that head
  to one value and hands the decision to the tiebreak.

    python tools/analyze_fusion_failure.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.metrics.records import Attributor  # noqa: E402

DEFAULT_RUN = REPO / "runs" / "session-d" / "heldout"
ARTIFACT = REPO / "crates" / "marlowe-memory" / "artifacts" / "gate-frozen-v3.json"


def iter_ndjson(path: Path):
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    run_dir = args.run.resolve()
    out_path = (args.out.resolve() if args.out else run_dir.parent / "fusion-failure.json")

    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    curves = artifact["cue_curves"]

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()

    attributor = Attributor()
    for frame in iter_ndjson(run_dir / "run.jsonl"):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))

    per = defaultdict(list)
    for row in iter_ndjson(run_dir / "scored-candidates.ndjson"):
        attribution, _ = attributor.attribute(
            row["memory_id"], gold_map.get(row["query_id"], frozenset())
        )
        per[row["query_id"]].append(
            (
                row["lexical_bm25"],
                row["dense_cosine"],
                row["calibrated_precision"],
                row["min_calibrated_precision"],
                attribution == "gold",
            )
        )

    cases = {c.query_id: c for c in corpus.cases}
    queries = [q for q in per if q in cases and not cases[q].is_abstention]

    tie_sizes: list[int] = []
    winner_is_dense_side = 0
    lexical_head_destroyed = 0
    gold_in_tie_but_not_first = 0
    n = 0

    for query in queries:
        lex = np.array([r[0] for r in per[query]])
        den = np.array([r[1] for r in per[query]])
        cal = np.array([r[2] for r in per[query]])
        min_cal = np.array([r[3] for r in per[query]])
        gold = np.array([r[4] for r in per[query]])
        if gold.sum() == 0:
            continue
        n += 1

        top_cal = cal.max()
        tied = np.flatnonzero(cal == top_cal)
        tie_sizes.append(len(tied))

        # Within the tie, the gate's second key is min_calibrated_precision -- which is the
        # OTHER cue's opinion. Measure how often that reorders the head away from lexical's own
        # best candidate.
        lex_best = int(np.argmax(lex))
        order = np.lexsort((-min_cal[tied], ))
        gate_first = int(tied[order[0]])
        if len(tied) > 1 and gate_first != lex_best and lex_best in tied.tolist():
            lexical_head_destroyed += 1
        # Did the winning cue's own score even decide? If the tie is large, the max carries no
        # ordering information at all.
        if len(tied) > 1 and den[gate_first] > den[lex_best]:
            winner_is_dense_side += 1
        # Gold present inside the tied band but not selected first.
        if len(tied) > 1 and gold[tied].any() and not gold[gate_first]:
            gold_in_tie_but_not_first += 1

    sizes = np.array(tie_sizes)
    result = {
        "_what": "why max-over-per-cue-calibrated-precision lost at top-1",
        "_this_is_a_diagnostic_not_a_search": (
            "No re-fit, no re-rank against gold, no proposed operating point. Descriptive "
            "statistics about the artifact that shipped and the run that happened."
        ),
        "cases": n,
        "curve_resolution": {
            cue: {
                "blocks": len(curves[cue]),
                "top_block_precision": curves[cue][-1][1],
                "top_block_lower_bound": curves[cue][-2][0] if len(curves[cue]) > 1 else None,
                "_reading": (
                    "every candidate whose score exceeds the lower bound receives the SAME "
                    "calibrated precision, so the fusion cannot order them"
                ),
            }
            for cue in artifact["cue_features"]
        },
        "ties_at_the_fused_maximum": {
            "mean": round(float(sizes.mean()), 2),
            "median": int(np.median(sizes)),
            "p90": int(np.percentile(sizes, 90)),
            "max": int(sizes.max()),
            "fraction_of_cases_with_a_tie": round(float((sizes > 1).mean()), 4),
            "_reading": (
                "the number of candidates sharing the top fused calibrated precision. Every one "
                "of these is decided by the TIEBREAK, not by the fusion."
            ),
        },
        "lexical_head_destroyed": {
            "cases": lexical_head_destroyed,
            "fraction": round(lexical_head_destroyed / n, 4),
            "_reading": (
                "cases where lexical's own best candidate was inside the tied band but the "
                "tiebreak promoted a different candidate above it. This is the mechanism: "
                "lexical alone orders its head by continuous BM25; max-fusion flattens that "
                "head to one value and lets the second key reorder it."
            ),
        },
        "tiebreak_favoured_the_weaker_cue": {
            "cases": winner_is_dense_side,
            "fraction": round(winner_is_dense_side / n, 4),
            "_reading": (
                "of those, how often the promoted candidate had a HIGHER dense cosine than "
                "lexical's own best. min_calibrated_precision is the other cue's opinion, so "
                "inside a lexical-dominated tie it hands the decision to dense -- the weaker "
                "cue at top-1 (0.444 vs 0.548)."
            ),
        },
        "gold_inside_the_tie_but_not_ranked_first": {
            "cases": gold_in_tie_but_not_first,
            "fraction": round(gold_in_tie_but_not_first / n, 4),
            "_reading": (
                "the loss made visible: the gold turn was inside the band the fusion could not "
                "order, and the tiebreak did not pick it."
            ),
        },
    }
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"cases: {n}")
    print()
    for cue, block in result["curve_resolution"].items():
        print(
            f"{cue:16s} {block['blocks']:4d} blocks; everything above "
            f"{block['top_block_lower_bound']} collapses to {block['top_block_precision']}"
        )
    print()
    t = result["ties_at_the_fused_maximum"]
    print(f"candidates tied at the fused maximum: mean {t['mean']}, median {t['median']}, "
          f"p90 {t['p90']}, max {t['max']}")
    print(f"cases with a tie at the top: {t['fraction_of_cases_with_a_tie']:.1%}")
    print()
    print(f"lexical's head reordered by the tiebreak: "
          f"{result['lexical_head_destroyed']['fraction']:.1%} of cases")
    print(f"  ... promoting a higher-dense candidate: "
          f"{result['tiebreak_favoured_the_weaker_cue']['fraction']:.1%}")
    print(f"gold inside the unorderable band, not picked: "
          f"{result['gold_inside_the_tie_but_not_ranked_first']['fraction']:.1%}")
    print(f"\nwrote {out_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
