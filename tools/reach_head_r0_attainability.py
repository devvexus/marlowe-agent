"""R0 -- the attainability arithmetic, before any mechanism is proposed.

ADR-010 asks whether a shape can move the metric it will be judged on. This script asks the
question one level further up, and it is the question that must be answered first: **can the
READ reach the band AT ALL, on this split, for ANY mechanism?**

K1's reading rule is pinned in `runs/session-j/PREREGISTRATION.json`:

    "'Reaches 0.95' means the INTERVAL, not the point estimate."

At coverage c on a held-out split of n queries, the injected set has n_c = round(c * n) members.
The most favourable outcome any mechanism can produce is k = n_c (every injected query correct).
The Clopper-Pearson lower bound at k = n is `alpha_2 ** (1/n)` with `alpha_2 = 0.025`, which is a
function of n_c ALONE -- it does not depend on the retrieval system, the reranker, the confidence
signal, or anything else a session could build.

So the ceiling on the criterion at each coverage is arithmetic, and it is knowable before any
code is written. This prints it.

Prints numbers. Applies nothing. Writes one JSON artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scipy.stats import beta

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "runs" / "session-m0c" / "reach-r0-attainability.json"

THRESHOLD = 0.95
CONF = 0.95


def clopper_pearson(k: int, n: int, conf: float = CONF) -> tuple[float, float]:
    """Exact binomial interval. Identical arithmetic to publish_precision_coverage.clopper_pearson,
    restated here rather than imported because this script must run before anything is built."""
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - a / 2.0, k + 1, n - k))
    return (lo, hi)


def min_n_for_threshold(errors: int, threshold: float = THRESHOLD) -> int:
    """Smallest n whose Clopper-Pearson lower bound at k = n - errors clears `threshold`."""
    n = max(errors + 1, 1)
    while n < 100_000:
        lo, _ = clopper_pearson(n - errors, n)
        if lo >= threshold:
            return n
        n += 1
    return -1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-heldout", type=int, default=229,
                    help="the eligible held-out population; 229 is canonical since Session C")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    n = args.n_heldout

    print("=" * 78)
    print("R0 -- CAN THE READ REACH THE BAND, FOR ANY MECHANISM?")
    print("=" * 78)
    print(f"held-out population n = {n};  threshold = {THRESHOLD};  "
          f"'reaches' = Clopper-Pearson 95% LOWER BOUND >= threshold")
    print()

    coverages = [round(x, 2) for x in [1.0 - 0.05 * i for i in range(19)]]
    rows = []
    print(f"{'coverage':>9} {'n_c':>5} {'perfect':>9} {'ci_low':>8} {'clears?':>8} "
          f"{'one_err':>8} {'ci_low':>8} {'clears?':>8}")
    print("-" * 78)
    for c in coverages:
        n_c = max(1, round(c * n))
        lo_perfect, _ = clopper_pearson(n_c, n_c)
        lo_one, _ = clopper_pearson(n_c - 1, n_c) if n_c >= 2 else (float("nan"), float("nan"))
        row = {
            "coverage": c,
            "n_c": n_c,
            "best_possible_precision": 1.0,
            "ci95_low_if_perfect": round(lo_perfect, 4),
            "clears_threshold_if_perfect": bool(lo_perfect >= THRESHOLD),
            "precision_with_one_error": round((n_c - 1) / n_c, 4) if n_c >= 2 else None,
            "ci95_low_with_one_error": round(lo_one, 4) if n_c >= 2 else None,
            "clears_threshold_with_one_error": bool(lo_one >= THRESHOLD) if n_c >= 2 else False,
        }
        rows.append(row)
        print(f"{c:>9.2f} {n_c:>5d} {1.0:>9.4f} {lo_perfect:>8.4f} "
              f"{'YES' if row['clears_threshold_if_perfect'] else 'no':>8} "
              f"{(n_c-1)/n_c:>8.4f} {lo_one:>8.4f} "
              f"{'YES' if row['clears_threshold_with_one_error'] else 'no':>8}")

    print()
    print("-" * 78)
    print("THE MINIMUM INJECTED-SET SIZE AT WHICH THE INTERVAL CAN CLEAR 0.95")
    print("-" * 78)
    mins = {}
    for errors in range(0, 5):
        m = min_n_for_threshold(errors)
        mins[errors] = m
        print(f"  with {errors} error(s): n >= {m:>4d}  "
              f"(= {m / n * 100:6.2f}% coverage of a {n}-query split)")

    perfect_min = mins[0]
    clearing = [r for r in rows if r["clears_threshold_if_perfect"]]
    first_clearing = min(clearing, key=lambda r: r["coverage"]) if clearing else None

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    lo_23, _ = clopper_pearson(23, 23)
    print(f"At the DECLARED OPERATING POINT (10% coverage, n_c = 23):")
    print(f"  a PERFECT selector -- 23 of 23 correct -- has CI95 lower bound {lo_23:.4f}.")
    print(f"  {lo_23:.4f} < {THRESHOLD}.")
    print()
    print("  => K1's interval reading is UNATTAINABLE at 10% coverage on a 229-query held-out")
    print("     split, for ANY mechanism, including a perfect one. This is arithmetic, not a")
    print("     statement about retrieval.")
    print()
    if first_clearing is None:
        print("  => No coverage level on this grid can clear the interval even at perfection.")
    else:
        print(f"  => The lowest coverage on this grid where a PERFECT selector clears is "
              f"{first_clearing['coverage']:.2f} "
              f"(n_c = {first_clearing['n_c']}, ci_low {first_clearing['ci95_low_if_perfect']:.4f}).")
    print(f"  => A perfect selector needs n_c >= {perfect_min} injections; with a single error, "
          f"n_c >= {mins[1]}.")
    print()
    print("  This does not say the work is pointless. It says the criterion's INTERVAL reading and")
    print("  its 10%-coverage reading cannot both be satisfied on n = 229, so a session aiming at")
    print("  the interval must move the POINT ESTIMATE and report the interval honestly, or")
    print("  raise n. Both are stated; neither is quietly chosen.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "_what": "R0 attainability arithmetic: the ceiling K1's interval reading imposes, "
                 "independent of any mechanism.",
        "_why": "ADR-010 asks whether a shape can move the metric. This asks whether the metric "
                "can reach the band at all on this split. It is prior to every candidate.",
        "n_heldout": n,
        "threshold": THRESHOLD,
        "reading_rule": "'Reaches 0.95' means the Clopper-Pearson 95% lower bound, not the point "
                        "estimate. Pinned in runs/session-j/PREREGISTRATION.json.",
        "curve_ceiling": rows,
        "min_injected_set_size_to_clear_threshold": {str(k): v for k, v in mins.items()},
        "verdict_at_declared_operating_point": {
            "coverage": 0.10,
            "n_c": 23,
            "precision_if_perfect": 1.0,
            "ci95_low_if_perfect": round(lo_23, 4),
            "clears_threshold": bool(lo_23 >= THRESHOLD),
            "reading": "UNATTAINABLE for any mechanism at n_c = 23. Arithmetic, not quality.",
        },
    }
    args.out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print()
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
