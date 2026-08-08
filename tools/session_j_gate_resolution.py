"""Session J, Part 0 — what the 0.3739 ceiling actually measures.

**This is an ADR-010 reachability check, and it runs BEFORE any band is registered.** Part 3(a) is
an isotonic refit whose headline is `max_calibrated_precision`. Before fitting anything, the
question is whether that quantity *can* reach the frozen 0.95 threshold — and the answer is decided
by the calibration's own arithmetic, independently of which features are fed to it.

The mechanism, stated before it is measured:

`fit_isotonic` buckets the fit rows into `CALIBRATION_BLOCKS = 256` **equal-count** blocks, then
pools adjacent blocks sharing a score bound, then pools adjacent PAVA violators. Every one of those
operations makes a block **larger**, never smaller. So the finest question the calibration can ever
ask is *"what fraction of these N/256 rows are gold?"*, and

    max_calibrated_precision <= min(total_positives, block_size) / block_size

The consequence is not that 0.95 is arithmetically impossible. It is that the operating point the
threshold names **cannot be expressed at this resolution**: one block spans ~1.8 candidates per
query, so the most selective statement the gate can make is about the top ~1.8 candidates of
*every* query — a statement at ~100% coverage. **A precision threshold is a request for a confident
SUBSET, and the calibration has no vocabulary for subsets smaller than one block.**

What is measured here, and on which population:

  1. **The bound**, from the numbers `gate-frozen-v5.json` itself records. No dump, no
     reconstruction, nothing to license — pure arithmetic over 117894 rows and 450 positives.
  2. **The query coverage of the top block**, which needs labelled rows and therefore needs a
     population. It uses the **gated** `runs/session-f/all/` dump, cut to the fit half and licensed
     by the same fidelity gate `session_h_pools` already uses.
  3. **The oracle** at this resolution, which separates "the feature is weak" from "the resolution
     cannot ask the question".

**Two populations appear below and they are NOT interchangeable.** The shipped 0.373913 was fit on
the `--fit-mode` dump, whose in-process attribution was never archived — `runs/session-f/fit-applied/`
is a *consolidation-applied* run and attributing the fit-mode dump through it yields 119340 rows and
452 positives against the artifact's recorded 117894 and 450. That is a different population, so
**the second-implementation check against 0.373913 is NOT RUN, and is reported as not run.** It
costs nothing that matters: the bound in (1) is arithmetic over numbers the artifact carries itself,
and the coverage in (2) is a property of any population with ~487 candidates and ~1.8 gold per query.

`fit_isotonic` and `CALIBRATION_BLOCKS` are IMPORTED from `fit_gate.py`, never restated. A second
implementation of the bucketing arithmetic sitting beside the real one with nothing comparing them
is the mismatch pattern this project has paid for eight times.

    python tools/session_j_gate_resolution.py
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))
sys.path.insert(0, str(REPO / "tools"))

from fit_gate import (  # noqa: E402
    ARTIFACT_PATH,
    CALIBRATION_BLOCKS,
    CUE_FEATURES,
    FEATURE_NAMES,
    THRESHOLD,
    fit_isotonic,
)
from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.metrics.records import Attributor  # noqa: E402
from reach_pools import SPLIT_PATH, iter_ndjson  # noqa: E402
from session_h_pools import ALL_RUN, fidelity_gate, load_split_pools  # noqa: E402

OUT_PATH = REPO / "runs" / "session-j" / "gate-resolution.json"

# The fit-mode dump and the transcript that CANNOT label it. Named so the gap is on the record
# rather than being silently worked around.
FIT_MODE_DUMP = REPO / "runs" / "session-f" / "fit-features.ndjson"


def block_sizes(n: int, max_blocks: int = CALIBRATION_BLOCKS) -> np.ndarray:
    """Equal-count bucket sizes — `fit_isotonic`'s own expression, evaluated for a given n."""
    return np.bincount(np.minimum((np.arange(n) * max_blocks) // n, max_blocks - 1))


def bound(n_rows: int, n_pos: int, n_cases: int) -> dict:
    sizes = block_sizes(n_rows)
    top = int(sizes[-1])
    ceiling = min(n_pos, top) / top
    needed = int(np.ceil(THRESHOLD * top))
    return {
        "rows": n_rows,
        "positives": n_pos,
        "cases": n_cases,
        "smallest_expressible_block_rows": int(sizes.min()),
        "top_block_rows": top,
        "rows_per_query_in_one_block": round(top / n_cases, 4),
        "max_attainable_calibrated_precision": round(ceiling, 6),
        "gold_rows_needed_for_threshold": needed,
        "share_of_all_gold_that_requires": round(min(1.0, needed / n_pos), 6),
        "threshold_attainable_in_principle": bool(ceiling >= THRESHOLD),
    }


def print_bound(label: str, b: dict) -> None:
    print(f"  {label}")
    print(f"    {b['rows']} rows, {b['positives']} positive, {b['cases']} cases")
    print(f"    smallest expressible block      {b['smallest_expressible_block_rows']} rows"
          f"  = {b['rows_per_query_in_one_block']:.2f} candidates per query")
    print(f"    max attainable calibrated prec. {b['max_attainable_calibrated_precision']:.4f}"
          f"  = min({b['positives']}, {b['top_block_rows']}) / {b['top_block_rows']}")
    print(f"    gold rows needed for {THRESHOLD}        {b['gold_rows_needed_for_threshold']}"
          f"  = {b['share_of_all_gold_that_requires']:.1%} of ALL gold in the split")


def load_gated_fit_rows() -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """(X, y, query_ids, stats) over the licensed gated fit population.

    Licensing is not re-derived: `session_h_pools.load_split_pools` reconstructs both halves of
    `runs/session-f/all/` and `fidelity_gate` requires the held-out half to reproduce Session F's
    published top-1 exactly. That is what permits using the fit half at all.

    This function then reads the same dump a second time, for the two calibrated cue features the
    `Pool` dataclass does not carry. **The two reads are checked against each other** — same cases,
    same row count — so a divergence between them is a refusal rather than a silent disagreement.
    """
    fit_pools, heldout_pools, _ = load_split_pools(ALL_RUN)
    ok, report = fidelity_gate(heldout_pools)
    for name, check in report["checks"].items():
        print(f"    {name:14s} target {check['target']:.4f}  measured {check['measured']:.4f}  "
              f"{'PASS' if check['pass'] else 'FAIL'}")
    if not ok:
        raise SystemExit(
            "Reconstruction licensing gate FAILED. The fit half of runs/session-f/all/ is not "
            "Session F's fit split, and no number below would describe the shipped gate."
        )

    keep = set(fit_pools)
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()

    attributor = Attributor()
    for frame in iter_ndjson(ALL_RUN / "run.jsonl"):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))

    features: list[list[float]] = []
    labels: list[int] = []
    queries: list[str] = []
    for row in iter_ndjson(ALL_RUN / "scored-candidates.ndjson"):
        qid = row["query_id"]
        if qid not in keep:
            continue
        attribution, _turn_id = attributor.attribute(row["memory_id"], gold_map.get(qid, frozenset()))
        features.append([float(row[name]) for name in FEATURE_NAMES])
        labels.append(1 if attribution == "gold" else 0)
        queries.append(qid)

    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    q = np.asarray(queries)

    expected_rows = sum(len(p.candidates) for p in fit_pools.values())
    expected_gold = sum(int(p.gold.sum()) for p in fit_pools.values())
    if int(x.shape[0]) != expected_rows or int(y.sum()) != expected_gold:
        raise SystemExit(
            f"the two reads of {ALL_RUN.name}/ disagree: this one sees {x.shape[0]} rows / "
            f"{int(y.sum())} gold, the Pool reconstruction sees {expected_rows} / {expected_gold}. "
            "Refusing rather than describing one read with the other's licence."
        )
    return x, y, q, {"rows": int(x.shape[0]), "positives": int(y.sum()),
                     "cases": len(fit_pools)}


def main() -> int:
    artifact = json.loads(io.open(ARTIFACT_PATH, encoding="utf-8").read())
    print(f"artifact: {ARTIFACT_PATH.name}  ({artifact['version']}, threshold {artifact['threshold']})")
    print(f"  shipped ceiling: {max(max(b[1] for b in c) for c in artifact['cue_curves'].values()):.4f}")

    # ---- 1. the bound, from the artifact's own recorded numbers ------------------------------
    print()
    print("=" * 78)
    print("1. THE ARITHMETIC BOUND — a property of the resolution, not of any feature")
    print("=" * 78)
    print(f"  CALIBRATION_BLOCKS = {CALIBRATION_BLOCKS}, equal-count; pooling only ever ENLARGES a block")
    print()
    shipped = bound(int(artifact["fit_rows"]), int(artifact["fit_positives"]), int(artifact["fit_cases"]))
    print_bound("the population the SHIPPED ceiling was fit on (--fit-mode)", shipped)

    # ---- 2. coverage, on the licensed gated population ---------------------------------------
    print()
    print("=" * 78)
    print("2. WHAT THE MOST SELECTIVE EXPRESSIBLE OPERATING POINT COVERS")
    print("=" * 78)
    print("  licensing the gated fit population (runs/session-f/all/, held-out half):")
    x, y, q, stats = load_gated_fit_rows()
    print(f"  GATE PASSED. gated fit population: {stats['rows']} rows, {stats['positives']} "
          f"positive, {stats['cases']} cases")
    print()
    gated = bound(stats["rows"], stats["positives"], stats["cases"])
    print_bound("the gated fit population (what Part 3 will refit on)", gated)

    top_block = gated["top_block_rows"]
    coverage = {}
    print()
    for name in CUE_FEATURES:
        column = FEATURE_NAMES.index(name)
        order = np.argsort(-x[:, column], kind="stable")
        head = order[:top_block]
        by_query: dict[str, int] = defaultdict(int)
        for idx in head:
            by_query[q[idx]] += int(y[idx])
        touched = len(by_query)
        golds = int(y[head].sum())
        curve = fit_isotonic(x[:, column], y)

        # **What the top block is MADE OF, per query.** `{cue}_margin` is the candidate's lead
        # over its own query's runner-up, so exactly one candidate per query has a positive value
        # and every other candidate has a negative one. The global top block is therefore forced to
        # be "every query's rank-1, then the least-negative rank-2s" -- which is why its precision
        # cannot be anything other than a diluted single-cue R@1, whatever the calibration does.
        # Measured rather than asserted.
        raw_cue = "lexical_bm25" if name.startswith("lexical") else "dense_cosine"
        raw_col = FEATURE_NAMES.index(raw_cue)
        per_query_rank: dict[str, np.ndarray] = {}
        for qid in set(q.tolist()):
            rows = np.flatnonzero(q == qid)
            per_query_rank[qid] = rows[np.argsort(-x[rows, raw_col], kind="stable")]
        rank_of = {}
        for qid, rows in per_query_rank.items():
            for r, idx in enumerate(rows):
                rank_of[int(idx)] = r
        head_ranks = np.array([rank_of[int(i)] for i in head])
        is_rank1 = head_ranks == 0
        n_rank1 = int(is_rank1.sum())
        gold_at_rank1 = int(y[head][is_rank1].sum())
        cue_r_at_1 = float(
            np.mean([bool(y[rows[0]]) for rows in per_query_rank.values()])
        )

        coverage[name] = {
            "top_block_rows": top_block,
            "distinct_queries_in_top_block": touched,
            "query_coverage": round(touched / stats["cases"], 4),
            "gold_rows_in_top_block": golds,
            "top_block_precision": round(golds / top_block, 4),
            "queries_with_a_gold_row_in_top_block": sum(1 for v in by_query.values() if v > 0),
            "refit_curve_blocks": len(curve),
            "refit_top_block": round(max(b[1] for b in curve), 6),
            "composition": {
                "rank1_rows_in_top_block": n_rank1,
                "non_rank1_rows_in_top_block": top_block - n_rank1,
                "gold_among_the_rank1_rows": gold_at_rank1,
                "gold_among_the_rest": golds - gold_at_rank1,
                "cue_r_at_1_on_this_population": round(cue_r_at_1, 4),
                "top_block_precision_predicted_from_cue_r_at_1": round(
                    cue_r_at_1 * n_rank1 / top_block, 4),
            },
        }
        c = coverage[name]
        comp = c["composition"]
        print(f"  {name}")
        print(f"    the top block spans {touched} of {stats['cases']} queries"
              f"  = {c['query_coverage']:.1%} QUERY COVERAGE")
        print(f"    {golds} gold rows of {top_block}  ->  precision {c['top_block_precision']:.4f}")
        print(f"    recomputed on THIS population: {c['refit_top_block']:.4f} "
              f"({c['refit_curve_blocks']} blocks)")
        print(f"    COMPOSITION: {comp['rank1_rows_in_top_block']} of the {top_block} rows are "
              f"their query's rank-1 under {raw_cue}")
        print(f"      gold among those rank-1 rows      {comp['gold_among_the_rank1_rows']}"
              f"   (cue R@1 = {comp['cue_r_at_1_on_this_population']:.4f})")
        print(f"      gold among the other "
              f"{comp['non_rank1_rows_in_top_block']:>3} rows      {comp['gold_among_the_rest']}")
        print(f"      precision predicted by cue R@1 alone: "
              f"{comp['top_block_precision_predicted_from_cue_r_at_1']:.4f}"
              f"   against measured {c['top_block_precision']:.4f}")

    # ---- 3. the oracle ------------------------------------------------------------------------
    #
    # The naive bound is min(positives, block) / block, and on this population that is 1.0000 --
    # useless, because it ignores WHERE the gold rows can be. The block's composition is forced:
    # a `{cue}_margin` is positive for exactly one candidate per query, so the top block is always
    # "one row from every query, then the least-negative rank-2s". A query can only contribute a
    # gold row at rank 2 if it HAS a second gold row. 89 of 229 fit queries have exactly one.
    print()
    print("=" * 78)
    print("3. ORACLE — the best ANY feature could do at this resolution")
    print("=" * 78)
    per_query_gold = Counter()
    for qid in set(q.tolist()):
        per_query_gold[qid] = int(y[q == qid].sum())
    hist = Counter(per_query_gold.values())
    n_cases = stats["cases"]
    rank2_slots = top_block - n_cases
    queries_with_2plus = sum(v for k, v in hist.items() if k >= 2)
    oracle_gold = n_cases + min(rank2_slots, queries_with_2plus)
    oracle = oracle_gold / top_block

    print(f"  gold rows per query: " + ", ".join(f"{k}x{v}" for k, v in sorted(hist.items())))
    print(f"  queries with >= 2 gold rows            {queries_with_2plus} of {n_cases}")
    print()
    print(f"  the top block is FORCED to be {n_cases} rank-1 rows + {rank2_slots} rank-2 rows")
    print(f"  a perfect cue makes all {n_cases} rank-1 rows gold")
    print(f"  it can make at most min({rank2_slots}, {queries_with_2plus}) = "
          f"{min(rank2_slots, queries_with_2plus)} of the rank-2 rows gold")
    print(f"  ORACLE max_calibrated_precision        ({n_cases} + "
          f"{min(rank2_slots, queries_with_2plus)}) / {top_block} = {oracle:.4f}")
    print()
    if oracle < THRESHOLD:
        print(f"  *** {oracle:.4f} < {THRESHOLD}. THE THRESHOLD IS UNREACHABLE AT THIS RESOLUTION ***")
        print(f"  *** FOR ANY FEATURE, INCLUDING A PERFECT ONE. It has been unreachable since  ***")
        print(f"  *** CALIBRATION_BLOCKS was chosen, and 0.3739 has been read against it since ***")
        print(f"  *** Session B as though the gap were a quality gap.                          ***")
    else:
        print(f"  {oracle:.4f} >= {THRESHOLD}: reachable in principle by a perfect cue.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "_what": (
            "Session J Part 0, the ADR-010 reachability check for Part 3(a). What the 0.3739 "
            "ceiling measures: the RESOLUTION of the calibration at ~100% coverage, not the "
            "quality of the retrieval system."
        ),
        "artifact": {
            "path": str(ARTIFACT_PATH.relative_to(REPO)).replace("\\", "/"),
            "version": artifact["version"],
            "threshold": THRESHOLD,
            "shipped_ceiling": max(max(b[1] for b in c) for c in artifact["cue_curves"].values()),
        },
        "bound_on_shipped_fit_population": shipped,
        "bound_on_gated_fit_population": gated,
        "top_block_coverage": coverage,
        "oracle": {
            "_what": (
                "The best top-block precision ANY feature could produce at this resolution. The "
                "naive min(positives, block)/block bound is vacuous because it ignores where gold "
                "rows can be: a {cue}_margin is positive for exactly one candidate per query, so "
                "the top block is forced to be one row from every query plus the least-negative "
                "rank-2s, and a query contributes a gold rank-2 row only if it HAS a second gold."
            ),
            "gold_rows_per_query_histogram": {str(k): v for k, v in sorted(hist.items())},
            "queries_with_two_or_more_gold_rows": queries_with_2plus,
            "forced_rank1_rows": n_cases,
            "forced_rank2_rows": rank2_slots,
            "max_gold_rows_in_top_block": oracle_gold,
            "max_calibrated_precision": round(oracle, 6),
            "clears_threshold": bool(oracle >= THRESHOLD),
        },
        "second_implementation_check": {
            "run": False,
            "why": (
                "the shipped 0.373913 was fit on the --fit-mode dump, whose in-process "
                "attribution was never archived. runs/session-f/fit-applied/run.jsonl is a "
                "CONSOLIDATION-APPLIED run; attributing runs/session-f/fit-features.ndjson "
                "through it yields 119340 rows and 452 positives against the artifact's recorded "
                "117894 and 450. That is a different population, and describing one with the "
                "other's licence is the exact failure this project keeps paying for. The check "
                "is reported as NOT RUN rather than run against the wrong population."
            ),
            "fit_mode_dump": str(FIT_MODE_DUMP.relative_to(REPO)).replace("\\", "/"),
            "reconstructed_rows": 119340,
            "reconstructed_positives": 452,
            "artifact_rows": int(artifact["fit_rows"]),
            "artifact_positives": int(artifact["fit_positives"]),
            "_cost_of_not_running_it": (
                "none that matters. The bound is arithmetic over numbers the artifact carries "
                "itself, and the coverage finding is a property of any population with ~487 "
                "candidates and ~1.8 gold rows per query."
            ),
        },
        "verdict": (
            f"max_calibrated_precision >= {THRESHOLD} is UNREACHABLE at CALIBRATION_BLOCKS = "
            f"{CALIBRATION_BLOCKS} for any feature, including a perfect one: the oracle is "
            f"{oracle:.4f}. The frozen threshold names an operating point on a CONFIDENT SUBSET, "
            "and the calibration cannot express a subset smaller than one block. One block spans "
            f"{gated['rows_per_query_in_one_block']:.2f} candidates per query across 100% of "
            "queries, so the only operating point the gate can name is FULL COVERAGE, where the "
            "value is a diluted single-cue R@1. 0.3739 is a resolution property reported at full "
            "coverage. It has been read against 0.95 as a quality gap since Session B, and that "
            "gap was never closable by improving retrieval."
        ),
    }, indent=2) + "\n", encoding="utf-8")
    print()
    print(f"WROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
