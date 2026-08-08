"""THE TRIPWIRE -- knowledge-update share of the top decile, and harm rate within it.

`HARM-WEIGHTED-PRECISION.md` records that harm is zero at the declared operating point **for the
wrong reason**: the head contains 0.0% knowledge-update queries on held-out against a 15.7% base
rate, because knowledge-update queries are simply low-confidence (median margin 0.2782 against
0.4020). That is a category-exclusion side effect, not a harm-aware mechanism, and it disappears
silently if coverage rises or if confidence on knowledge-update improves.

R6 demonstrated exactly what "improving" looks like: a perfect supersession oracle takes the
knowledge-update share of the fit top decile from **4.3% to 13.0%**. Success at making
knowledge-update more confident is the thing that removes the accidental protection. **So the
metric has to be live before anything moves it**, which is why this ships ahead of any detector.

Two standing metrics, reported on every run, both with intervals:

  ku_share_top_decile    what fraction of the injected set is knowledge-update. Against the 15.7%
                         base rate. Rising is not bad in itself -- it is the signal that the harm
                         number below can no longer be inherited and must be re-read.
  harm_top_decile        harmful injections among the injected set, with a Clopper-Pearson 95%
                         interval. **0 of 23 has an upper bound of 0.1482.** Three configurations
                         agreeing on zero is three configurations agreeing on a number that cannot
                         distinguish zero from one in seven. The interval is printed every time and
                         a bare zero is never reported alone.

TRIP conditions, registered here rather than chosen later:

  TRIP  any harmful injection in the top decile, against a recorded baseline of zero. Under K1
        condition 3 a configuration that injects at low precision fails outright, and a superseded
        fact injected as current is the failure §5.7 names. From a baseline of 0, one is a
        regression.
  WARN  ku_share_top_decile at or above the 15.7% base rate. The accidental protection is gone;
        the harm figure must be re-measured on the new configuration, not carried over.

Exit code 1 on TRIP so a pipeline notices. WARN is exit 0 -- it is a change of regime, not a defect.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import beta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from reach_harm_r5_classes import HARMFUL, classify, load_case_structure  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
BASELINE = REPO / "crates" / "marlowe-memory" / "artifacts" / "head-composition-baseline-v1.json"

OPERATING_COVERAGE = 0.10
KU_BASE_RATE = 0.157          # 78 knowledge-update of 500 cases
BASELINE_HARM_TOP_DECILE = 0  # HARM-WEIGHTED-PRECISION.md, both splits


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - a / 2.0, k + 1, n - k))
    return (lo, hi)


def measure(split: str, coverage: float, slates_path: Path | None = None) -> dict:
    cases = load_case_structure(json.loads(SPLIT_PATH.read_text(encoding="utf-8"))["corpus_path"]
                                if not (REPO / json.loads(
                                    SPLIT_PATH.read_text(encoding="utf-8"))["corpus_path"]).exists()
                                else REPO / json.loads(
                                    SPLIT_PATH.read_text(encoding="utf-8"))["corpus_path"])
    p = slates_path or Path(str(SLATES).format(split=split))
    recs = json.loads(p.read_text(encoding="utf-8"))["records"]
    n = len(recs)

    margin = np.array([r["margin"] for r in recs], dtype=float)
    cls = np.array([classify(r["turn_ids"][0], cases[r["query_id"]]) for r in recs])
    ku = np.array([cases[r["query_id"]]["question_type"] == "knowledge-update" for r in recs])
    harmful = np.isin(cls, list(HARMFUL))

    k = max(1, round(coverage * n))
    cut = float(np.sort(margin)[::-1][k - 1])
    sel = margin >= cut
    m = int(sel.sum())

    kh = int(harmful[sel].sum())
    kku = int(ku[sel].sum())
    hlo, hhi = clopper_pearson(kh, m)
    slo, shi = clopper_pearson(kku, m)
    return {
        "split": split, "n": n, "coverage": round(m / n, 4), "n_c": m,
        "margin_threshold": round(cut, 6),
        "ku_count_top_decile": kku, "ku_share_top_decile": round(kku / m, 4),
        "ci95_ku_share": [round(slo, 4), round(shi, 4)],
        "ku_base_rate": KU_BASE_RATE,
        "harm_count_top_decile": kh, "harm_rate_top_decile": round(kh / m, 4),
        "ci95_harm_top_decile": [round(hlo, 4), round(hhi, 4)],
        "harm_count_overall": int(harmful.sum()),
        "harm_rate_overall": round(float(harmful.mean()), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--splits", nargs="+", default=["fit", "heldout"])
    ap.add_argument("--coverage", type=float, default=OPERATING_COVERAGE)
    ap.add_argument("--slates", type=Path, default=None,
                    help="explicit slates file, for measuring a NEW configuration")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record these figures as the baseline future runs are compared against")
    args = ap.parse_args()

    print("=" * 92)
    print("TRIPWIRE -- head composition and harm at the operating point")
    print("=" * 92)
    print(f"  the accidental protection this watches: knowledge-update is {KU_BASE_RATE:.1%} of "
          f"cases but ~0% of the head, because it is low-confidence, not because harm is detected")
    print()

    results, tripped, warned = {}, [], []
    for s in args.splits:
        r = measure(s, args.coverage, args.slates)
        results[s] = r
        print(f"  {s}: n_c={r['n_c']} at {r['coverage']:.1%} coverage")
        print(f"     knowledge-update share : {r['ku_share_top_decile']:.4f} "
              f"[{r['ci95_ku_share'][0]:.4f}, {r['ci95_ku_share'][1]:.4f}]  "
              f"({r['ku_count_top_decile']}/{r['n_c']})  base rate {KU_BASE_RATE:.1%}")
        print(f"     HARM at the op. point  : {r['harm_count_top_decile']}/{r['n_c']} = "
              f"{r['harm_rate_top_decile']:.4f}  "
              f"CI [{r['ci95_harm_top_decile'][0]:.4f}, {r['ci95_harm_top_decile'][1]:.4f}]"
              f"   <- NEVER quote the point estimate alone")
        print(f"     harm overall           : {r['harm_count_overall']}/{r['n']} = "
              f"{r['harm_rate_overall']:.4f}")
        if r["harm_count_top_decile"] > BASELINE_HARM_TOP_DECILE:
            tripped.append(s)
        if r["ku_share_top_decile"] >= KU_BASE_RATE:
            warned.append(s)
        print()

    print("-" * 92)
    for s in warned:
        print(f"  WARN  {s}: knowledge-update share {results[s]['ku_share_top_decile']:.1%} has "
              f"reached the {KU_BASE_RATE:.1%} base rate.")
        print("        The category-exclusion protection is gone. The harm figure must be "
              "RE-MEASURED on this")
        print("        configuration, not inherited from HARM-WEIGHTED-PRECISION.md.")
    for s in tripped:
        print(f"  TRIP  {s}: {results[s]['harm_count_top_decile']} harmful injection(s) at the "
              f"operating point, against a baseline of {BASELINE_HARM_TOP_DECILE}.")
        print("        A superseded fact injected as current is the failure §5.7 names, and K1")
        print("        condition 3 is binding.")
    if not tripped and not warned:
        print("  OK    no trip, no warning. Both figures are reported with their intervals above;")
        print("        a harm count of 0 at n_c=23 still has an upper bound near 0.148.")

    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({
            "_what": "standing head-composition tripwire baseline",
            "_why": "harm is zero at the operating point because the head contains almost no "
                    "knowledge-update queries, not because harm is detected. A perfect "
                    "supersession oracle moves the fit share 4.3% -> 13.0%, so success at "
                    "knowledge-update removes the protection. This records the pre-change state.",
            "version": 1,
            "configuration": "ms-marco-MiniLM-L-2-v2-ft-session-j (f32, seq 256, depth 10)",
            "operating_coverage": args.coverage,
            "ku_base_rate": KU_BASE_RATE,
            "trip_conditions": {
                "TRIP": "harm_count_top_decile > 0",
                "WARN": f"ku_share_top_decile >= {KU_BASE_RATE}",
            },
            "_interval_rule": "0 of 23 has a Clopper-Pearson upper bound of 0.1482. The point "
                              "estimate is never reported without its interval.",
            "baseline": results,
        }, indent=2, default=float) + "\n", encoding="utf-8")
        print(f"\n  wrote baseline {BASELINE}")

    return 1 if tripped else 0


if __name__ == "__main__":
    raise SystemExit(main())
