"""Are the lexical and dense cues redundant or complementary?

Number 3 reports what each cue can do alone. It cannot say whether they find the *same* gold
turns, and that distinction decides what the next session builds:

  redundant     -> content-similarity cues stack poorly because they see the same thing. Build
                   ONE structurally different cue (entity-graph or temporal, scoring on
                   relations rather than content) and measure the ceiling immediately.
  complementary -> the information is present and the FUSION is losing it. A third cue would
                   likely repeat the result; fix the combiner first.

Three measurements, driver-side, on the held-out split only:

  1. per-case Spearman rank correlation between the two cue scores
  2. which cue's top-k contains a gold turn, and the union over both
  3. the FITTED GATE's own top-k against those bounds -- the number that says whether the
     fusion captures what the cues jointly know

    python tools/analyze_cue_overlap.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.metrics.records import Attributor  # noqa: E402

RUN = REPO / "runs" / "session-c" / "heldout"
OUT = REPO / "runs" / "session-c" / "cue-overlap.json"


def iter_ndjson(path: Path):
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    d = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / d) if d else 0.0


def rrf(a: np.ndarray, b: np.ndarray, k: int = 60) -> np.ndarray:
    """Reciprocal rank fusion — a fusion that uses only RANKS, so the cues' incomparable score
    scales cannot let one dominate. Included as a cheap reference point for the fitted gate."""
    ra = np.argsort(np.argsort(-a, kind="stable"))
    rb = np.argsort(np.argsort(-b, kind="stable"))
    return 1.0 / (k + 1 + ra) + 1.0 / (k + 1 + rb)


def main() -> int:
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()

    attributor = Attributor()
    for frame in iter_ndjson(RUN / "run.jsonl"):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))

    per = defaultdict(list)
    for row in iter_ndjson(RUN / "scored-candidates.ndjson"):
        attribution, _ = attributor.attribute(
            row["memory_id"], gold_map.get(row["query_id"], frozenset())
        )
        per[row["query_id"]].append(
            (row["lexical_bm25"], row["dense_cosine"], row["score"], attribution == "gold")
        )

    cases = {c.query_id: c for c in corpus.cases}
    queries = [q for q in per if q in cases and not cases[q].is_abstention]

    def hit(scores: np.ndarray, gold: np.ndarray, k: int) -> bool:
        return bool(set(np.argsort(-scores, kind="stable")[:k].tolist()) & set(np.flatnonzero(gold).tolist()))

    rhos: list[float] = []
    ks = (1, 5, 10)
    tally = {k: defaultdict(int) for k in ks}
    n = 0
    for query in queries:
        lex = np.array([r[0] for r in per[query]])
        den = np.array([r[1] for r in per[query]])
        gate = np.array([r[2] for r in per[query]])
        gold = np.array([r[3] for r in per[query]])
        if gold.sum() == 0:
            continue
        n += 1
        rhos.append(spearman(lex, den))
        fused = rrf(lex, den)
        for k in ks:
            L, D = hit(lex, gold, k), hit(den, gold, k)
            tally[k]["lexical"] += L
            tally[k]["dense"] += D
            tally[k]["both"] += L and D
            tally[k]["either"] += L or D
            tally[k]["neither"] += not L and not D
            tally[k]["fitted_gate"] += hit(gate, gold, k)
            tally[k]["rank_fusion_rrf"] += hit(fused, gold, k)

    rho = np.array(rhos)
    by_k = {}
    for k in ks:
        t = tally[k]
        best_single = max(t["lexical"], t["dense"])
        by_k[str(k)] = {
            "lexical": round(t["lexical"] / n, 4),
            "dense": round(t["dense"] / n, 4),
            "both": round(t["both"] / n, 4),
            "lexical_only": round((t["lexical"] - t["both"]) / n, 4),
            "dense_only": round((t["dense"] - t["both"]) / n, 4),
            "either_oracle": round(t["either"] / n, 4),
            "neither": round(t["neither"] / n, 4),
            "fitted_gate": round(t["fitted_gate"] / n, 4),
            "rank_fusion_rrf": round(t["rank_fusion_rrf"] / n, 4),
            "oracle_gain_over_best_single": round((t["either"] - best_single) / n, 4),
            "fusion_gap_to_oracle": round((t["either"] - t["fitted_gate"]) / n, 4),
            "fusion_vs_best_single": round((t["fitted_gate"] - best_single) / n, 4),
        }

    result = {
        "_what": "Do the two cues find the SAME gold turns? Held-out split, driver-side.",
        "_why": (
            "Number 3 says what each cue does alone. It cannot say whether a third cue or a "
            "better combiner is the higher-leverage next step, and this can."
        ),
        "cases": n,
        "rank_correlation": {
            "mean": round(float(rho.mean()), 4),
            "median": round(float(np.median(rho)), 4),
            "p10": round(float(np.percentile(rho, 10)), 4),
            "p90": round(float(np.percentile(rho, 90)), 4),
            "reading": (
                "Low correlation means the cues rank candidates differently, which is the "
                "precondition for them being complementary rather than redundant."
            ),
        },
        "gold_in_top_k": by_k,
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"held-out answerable cases: {n}")
    print(f"Spearman rho: mean {rho.mean():.3f}  median {np.median(rho):.3f}")
    print()
    print(f"{'ranker':22s} " + " ".join(f"{'top-'+str(k):>8}" for k in ks))
    for name in ["lexical", "dense", "fitted_gate", "rank_fusion_rrf", "either_oracle"]:
        print(f"{name:22s} " + " ".join(f"{by_k[str(k)][name]:>8.3f}" for k in ks))
    print()
    for k in ks:
        b = by_k[str(k)]
        print(
            f"top-{k:<2} lexical-only {b['lexical_only']:.3f}  dense-only {b['dense_only']:.3f}  "
            f"neither {b['neither']:.3f}  |  fusion vs best single {b['fusion_vs_best_single']:+.3f}  "
            f"gap to oracle {b['fusion_gap_to_oracle']:+.3f}"
        )
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
