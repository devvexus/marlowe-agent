"""Read a retrieval stage profile and print the breakdown. No verdict, no band.

    python tools/profile_retrieval.py --run runs/session-l/profiled-cold

Reads `<run>/heldout/retrieval-profile.ndjson` — one row per section 4.2 call, written by
`marlowe --eval-adapter --profile-retrieval` — and reports P50/P90/P95/P99/max per stage.

## What this refuses to do

**It refuses to report shares that do not add up.** Per-stage P95s are taken over different
queries, so they do NOT sum to the total P95 and presenting them as a percentage breakdown would
be arithmetic nobody performed. Three separate things are reported instead:

  * the per-stage distribution, in milliseconds, which is what a stage costs;
  * the decomposition of the ONE query at the P95 of total latency, which is a real breakdown of
    a real request and is what "share of P95" can honestly mean;
  * the mean share across queries, which is what a stage costs on average.

**It refuses to report a breakdown that does not reconcile.** `residual_us` is the part of the
span that no stage claimed. If it is more than `MAX_RESIDUAL_SHARE` of the span, the table is
printed with a REFUSED verdict: a breakdown with a hole in it can hide exactly the cost it was
built to find, and a plausible-looking ranking of stages would still be produced.

**It refuses to call a run cold when it was warm.** `embed_was_cached` is read per row. A warm
cache removes the query's forward pass from the timed span, so a profile whose rows are mostly
cache hits is a warm profile whatever the directory was called.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Stage order is the pipeline's, and it is restated here only as a display order -- the names come
# from the rows themselves, so a stage added in Rust and forgotten here is reported as UNKNOWN
# rather than silently dropped from the table.
STAGE_ORDER = [
    "candidates",
    "scope",
    "lexical",
    "dense",
    "features",
    "gate",
    "prune",
    "rerank",
    "assemble",
]

# Above this, the breakdown is not trustworthy enough to read stage against stage.
MAX_RESIDUAL_SHARE = 0.05


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank, the same convention the harness's cost block uses."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(q * len(ordered)), len(ordered) - 1)
    return ordered[index]


def distribution(values: list[float]) -> dict:
    return {
        "p50": round(st.median(values), 3) if values else 0.0,
        "p90": round(percentile(values, 0.90), 3),
        "p95": round(percentile(values, 0.95), 3),
        "p99": round(percentile(values, 0.99), 3),
        "max": round(max(values), 3) if values else 0.0,
        "mean": round(st.fmean(values), 3) if values else 0.0,
    }


def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"{path} is empty. The run wrote no profile rows.")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True, help="a run directory holding heldout/")
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--label",
        required=True,
        help="what configuration produced this profile, e.g. 'cold, baseline' or 'cold, batched "
        "rerank'. REQUIRED and echoed into the artifact: two profiles of two configurations are "
        "the whole point of taking one, and an unlabelled table is a number without its system.",
    )
    args = ap.parse_args()

    run_dir: Path = args.run.resolve()
    path = run_dir / args.split / "retrieval-profile.ndjson"
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Re-run the scoring driver with --profile-retrieval."
        )
    rows = load(path)

    # **Queries that retrieved nothing are kept in the population, not filtered out.** A query
    # whose store had no candidates costs ~0 ms and is a real request; dropping it would raise
    # every percentile with nothing recording that the population moved. They are counted
    # separately so the reader can see how many there are.
    trivial = sum(1 for r in rows if r["scoped"] == 0)
    cached = sum(1 for r in rows if r["embed_was_cached"])

    total_ms = [r["total_us"] / 1000 for r in rows]
    embed_ms = [r["embed_us"] / 1000 for r in rows]
    span_ms = [r["span_us"] / 1000 for r in rows]
    residual_ms = [r["residual_us"] / 1000 for r in rows]

    # The reconciliation, and it is checked before anything is read stage against stage.
    span_total = sum(r["span_us"] for r in rows)
    residual_total = sum(r["residual_us"] for r in rows)
    residual_share = residual_total / span_total if span_total else 0.0
    # The other half of the same check: the stages live inside `span`, and `span` plus the query
    # embedding must account for the handler's own total. What is left is serialization and the
    # gate-feature dump -- named, so it cannot be silently attributed to a stage.
    unattributed = [
        (r["total_us"] - r["span_us"] - r["embed_us"]) / 1000 for r in rows
    ]

    stage_names = [k[:-3] for k in rows[0] if k.endswith("_us") and k[:-3] in STAGE_ORDER]
    unknown = sorted(
        {k[:-3] for r in rows for k in r if k.endswith("_us")}
        - set(STAGE_ORDER)
        - {"total", "embed", "span", "residual"}
    )

    stages = {name: [r[f"{name}_us"] / 1000 for r in rows] for name in STAGE_ORDER if name in stage_names}

    # The one honest "share of P95": decompose the single query that sits at the P95 of total.
    p95_total = percentile(total_ms, 0.95)
    at_p95 = min(rows, key=lambda r: abs(r["total_us"] / 1000 - p95_total))
    p95_row = {
        "query_id": at_p95["query_id"],
        "total_ms": round(at_p95["total_us"] / 1000, 3),
        "embed_ms": round(at_p95["embed_us"] / 1000, 3),
        "considered": at_p95["considered"],
        "scoped": at_p95["scoped"],
        "reranked": at_p95["reranked"],
        "stages_ms": {n: round(at_p95[f"{n}_us"] / 1000, 3) for n in stages},
        "residual_ms": round(at_p95["residual_us"] / 1000, 3),
        "unattributed_ms": round(
            (at_p95["total_us"] - at_p95["span_us"] - at_p95["embed_us"]) / 1000, 3
        ),
    }
    denominator = at_p95["total_us"] or 1
    p95_row["share_of_total"] = {
        **{n: round(at_p95[f"{n}_us"] / denominator, 4) for n in stages},
        "embed": round(at_p95["embed_us"] / denominator, 4),
        "residual": round(at_p95["residual_us"] / denominator, 4),
        "unattributed": round(p95_row["unattributed_ms"] * 1000 / denominator, 4),
    }

    mean_share = {
        n: round(st.fmean([r[f"{n}_us"] / (r["total_us"] or 1) for r in rows]), 4)
        for n in stages
    }
    mean_share["embed"] = round(
        st.fmean([r["embed_us"] / (r["total_us"] or 1) for r in rows]), 4
    )

    report = {
        "label": args.label,
        "run": str(run_dir),
        "split": args.split,
        "queries": len(rows),
        "queries_with_no_candidates_in_scope": trivial,
        "queries_served_from_the_embedding_cache": cached,
        "cache_state": (
            "COLD" if cached == 0 else ("WARM" if cached == len(rows) else "MIXED")
        ),
        "cache_state_note": (
            "a warm cache removes the query's forward pass from the timed span. A MIXED profile "
            "is two populations and its percentiles belong to neither."
        ),
        "reconciliation": {
            "residual_share_of_span": round(residual_share, 6),
            "max_residual_share": MAX_RESIDUAL_SHARE,
            "verdict": "OK" if residual_share <= MAX_RESIDUAL_SHARE else "REFUSED",
            "residual_ms": distribution(residual_ms),
            "unattributed_ms": distribution(unattributed),
            "unattributed_is": (
                "total - span - embed: response serialization and the gate-feature dump, both "
                "inside `cost.latency_ms` and outside every stage. Named rather than folded into "
                "a stage."
            ),
            "unknown_stage_columns": unknown,
        },
        "total_ms": distribution(total_ms),
        "embed_ms": distribution(embed_ms),
        "span_ms": distribution(span_ms),
        "stages_ms": {n: distribution(v) for n, v in stages.items()},
        "at_the_p95_query": p95_row,
        "mean_share_of_total": mean_share,
        "pool_sizes": {
            "considered": distribution([float(r["considered"]) for r in rows]),
            "scoped": distribution([float(r["scoped"]) for r in rows]),
            "reranked": distribution([float(r["reranked"]) for r in rows]),
        },
        "why_stage_p95s_do_not_sum": (
            "each stage's P95 is taken over a different query. The only breakdown that sums is "
            "`at_the_p95_query`, which decomposes one real request."
        ),
    }

    out = args.out or (run_dir / "retrieval-profile.json")
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"{args.label}  --  {len(rows)} queries, cache {report['cache_state']}")
    print(f"reconciliation: residual {residual_share:.4%} of span -> "
          f"{report['reconciliation']['verdict']}")
    if unknown:
        print(f"  UNKNOWN stage columns present and NOT displayed: {unknown}")
    print()
    print(f"{'stage':<12}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}   share of the P95 query")
    print("-" * 74)
    for name in ["embed"] + list(stages):
        d = distribution(embed_ms) if name == "embed" else distribution(stages[name])
        share = p95_row["share_of_total"].get(name, 0.0)
        print(f"{name:<12}{d['p50']:>9.3f}{d['p95']:>9.3f}{d['p99']:>9.3f}{d['max']:>9.3f}"
              f"   {share:>7.2%}")
    print("-" * 74)
    for name, values in (("residual", residual_ms), ("unattributed", unattributed)):
        d = distribution(values)
        share = p95_row["share_of_total"].get(name, 0.0)
        print(f"{name:<12}{d['p50']:>9.3f}{d['p95']:>9.3f}{d['p99']:>9.3f}{d['max']:>9.3f}"
              f"   {share:>7.2%}")
    d = distribution(total_ms)
    print(f"{'TOTAL':<12}{d['p50']:>9.3f}{d['p95']:>9.3f}{d['p99']:>9.3f}{d['max']:>9.3f}")
    print()
    print(f"pools: considered p50 {report['pool_sizes']['considered']['p50']:.0f}, "
          f"scoped p50 {report['pool_sizes']['scoped']['p50']:.0f}, "
          f"reranked p50 {report['pool_sizes']['reranked']['p50']:.0f}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
