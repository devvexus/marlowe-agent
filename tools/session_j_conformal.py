"""Session J, Part 3 — the precision/coverage curve, and the first number this project has
produced against K1.

Two arms, reported side by side.

## (a) Isotonic refit — reports the ADR-016 bound and STOPS

Part 0 measured, before anything was fit, that `max_calibrated_precision >= 0.95` is **unreachable
at `CALIBRATION_BLOCKS = 256` for any feature, including a perfect one**: the oracle is **0.8483**.
The top block is 435 rows spanning 100% of queries, so the only operating point the gate can
express is full coverage. Fitting a refit anyway would produce a number whose entire content is
that bound. `runs/session-j/gate-resolution.json`.

## (b) Conformal risk control — the K1 answer

Nonconformity is the margin between rank 1 and rank 2 **on the ranking key actually in force**. For
the shipped configuration that is the raw cross-encoder logit gap, exactly as registered; for a
normalized configuration it is the gap on the normalized key, because that is what decides the
ranking whose precision is being controlled.

### The guarantee and the measurement are two different quantities

This is the distinction the pre-registration binds hardest on, so the code keeps them in separate
fields and the report prints them on separate lines.

**The guarantee.** Calibrate `tau` on the fit-split margins of queries whose rank 1 is **not** gold,
at the `(1-alpha)(1+1/n0)` quantile. By exchangeability, for a new query whose rank 1 is not gold,
`P(margin >= tau) <= alpha`. That is a bound on the **false-injection rate among wrong queries** —
distribution-free, finite-sample, and marginal over the calibration draw.

**It is NOT precision.** K1 asks for precision *conditional on having injected*, which is a
selective risk the marginal bound does not cover. `P(correct | injected)` depends on the base rate
of correctness and on how coverage falls, neither of which the conformal construction pins.

Both are reported. Neither is described as the other.

The plain quantile over *all* fit queries — the form named in STATE.md — is also computed and
labelled for what it is: **coverage control**, not risk control. Taking the `(1-alpha)(1+1/n)`
quantile over every query selects roughly the top `alpha` fraction by margin, so it sets coverage
and says nothing about precision.

## The deliverable

The curve: precision at every coverage level down to 10%, on held-out, **with a Clopper-Pearson 95%
interval on every point**. At 10% coverage n is about 23, where an observed 0.95 carries a lower
bound near 0.77 — so "reaches 0.95" means the interval, not the point estimate.

Section 5.5 is precision-first with recall recovered through the explicit recall tool, and **K1
carries no coverage term**, so >= 0.95 precision at any coverage satisfies it as written.

    python tools/session_j_conformal.py --configs shipped best-registered
"""

from __future__ import annotations

import argparse
import io
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import beta

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "runs" / "session-j"
GATE_RESOLUTION = OUT_DIR / "gate-resolution.json"

ALPHAS = [0.05, 0.10, 0.20, 0.30]
MIN_GROUP_N = 40          # registered: below this the (1-a)(1+1/n) quantile is just the maximum
THRESHOLD = 0.95


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Exact binomial interval. Reported on every point because n is small where it matters."""
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return lo, hi


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def ranking_key(arm: str, strength: float, s: np.ndarray, length: np.ndarray) -> np.ndarray:
    if arm == "7a_control":
        return s
    if arm == "7c_divisive":
        return sigmoid(s) / np.power(np.maximum(length, 1), strength)
    if arm == "7f_signed_log_POSTHOC":
        return s - strength * np.log(np.maximum(length, 1))
    raise ValueError(arm)


def per_query(cache: dict, arm: str, strength: float) -> list[dict]:
    """One row per query: the margin on the key in force, and whether rank 1 is gold."""
    rows = []
    for qid, row in cache["rows"].items():
        s = np.array(row["scores"], float)
        length = np.array(row["wordpieces"], float)
        key = ranking_key(arm, strength, s, length)
        order = np.argsort(-key, kind="stable")
        margin = float(key[order[0]] - key[order[1]]) if len(order) > 1 else float("inf")
        rows.append({
            "query_id": qid,
            "category": row["category"],
            "margin": margin,
            "correct": bool(row["gold"][int(order[0])]),
        })
    return rows


def conformal_tau(fit_rows: list[dict], alpha: float) -> dict:
    """Both constructions, kept apart and labelled.

    RISK: quantile over the margins of fit queries whose rank 1 is WRONG. Bounds the rate at which
    a wrong query is injected. COVERAGE: quantile over ALL fit queries — the form named in
    STATE.md, which selects roughly the top alpha fraction by margin and controls coverage.
    """
    wrong = np.array([r["margin"] for r in fit_rows if not r["correct"]])
    allm = np.array([r["margin"] for r in fit_rows])

    def conformal_quantile(x: np.ndarray, a: float) -> float:
        n = len(x)
        if n == 0:
            return float("inf")
        level = min(1.0, (1 - a) * (1 + 1 / n))
        return float(np.quantile(x, level, method="higher"))

    return {
        "alpha": alpha,
        "risk_control": {
            "tau": conformal_quantile(wrong, alpha),
            "calibrated_on": "fit queries whose rank 1 is NOT gold",
            "n_calibration": int(len(wrong)),
            "guarantee": (
                f"for an exchangeable new query whose rank 1 is not gold, "
                f"P(margin >= tau) <= {alpha}. A bound on the FALSE-INJECTION RATE AMONG WRONG "
                f"QUERIES. Distribution-free, finite-sample, marginal over the calibration draw."
            ),
            "what_it_is_not": (
                "this is NOT precision. K1 asks for P(correct | injected), a selective risk the "
                "marginal bound does not cover."
            ),
        },
        "coverage_control": {
            "tau": conformal_quantile(allm, alpha),
            "calibrated_on": "ALL fit queries",
            "n_calibration": int(len(allm)),
            "_what_it_controls": (
                "coverage, not risk. The (1-alpha)(1+1/n) quantile over every query selects "
                "roughly the top alpha fraction by margin."
            ),
        },
    }


def curve(rows: list[dict], coverages: list[float]) -> list[dict]:
    """Precision at each target coverage, with an exact interval on every point."""
    margins = np.array([r["margin"] for r in rows])
    correct = np.array([r["correct"] for r in rows])
    n = len(rows)
    out = []
    for target in coverages:
        k = max(1, int(round(target * n)))
        cut = np.sort(margins)[::-1][k - 1]
        sel = margins >= cut
        n_sel = int(sel.sum())
        n_hit = int(correct[sel].sum())
        lo, hi = clopper_pearson(n_hit, n_sel)
        out.append({
            "target_coverage": target,
            "actual_coverage": round(n_sel / n, 4),
            "threshold": round(float(cut), 6),
            "injected": n_sel,
            "correct": n_hit,
            "precision": round(n_hit / n_sel, 4),
            "ci95_low": round(lo, 4),
            "ci95_high": round(hi, 4),
            "clears_threshold_point_estimate": bool(n_hit / n_sel >= THRESHOLD),
            "clears_threshold_interval": bool(lo >= THRESHOLD),
        })
    return out


def group_conditional(fit_rows: list[dict], held_rows: list[dict], alpha: float) -> dict:
    by_fit: dict[str, list[dict]] = defaultdict(list)
    for r in fit_rows:
        by_fit[r["category"]].append(r)
    by_held: dict[str, list[dict]] = defaultdict(list)
    for r in held_rows:
        by_held[r["category"]].append(r)

    out = {}
    for cat, rows in sorted(by_fit.items()):
        wrong = [r["margin"] for r in rows if not r["correct"]]
        eligible = len(wrong) >= MIN_GROUP_N
        entry = {
            "fit_n": len(rows),
            "fit_n_wrong": len(wrong),
            "heldout_n": len(by_held.get(cat, [])),
            "eligible": eligible,
            "_rule": f"group-conditional tau only where the wrong-query calibration set has "
                     f"n >= {MIN_GROUP_N}; below that the quantile is simply the maximum",
        }
        if eligible:
            n0 = len(wrong)
            level = min(1.0, (1 - alpha) * (1 + 1 / n0))
            entry["tau"] = float(np.quantile(np.array(wrong), level, method="higher"))
        out[cat] = entry
    return out


def load_cache(split: str, model: str, seq: int) -> dict:
    precision = "int8" if model.endswith("-int8") else "f32"
    stem = model.replace("ms-marco-MiniLM-", "").replace("-int8", "")
    path = OUT_DIR / f"rerank-scores-{split}-{stem}-{precision}-seq{seq}.json"
    if not path.exists():
        raise SystemExit(f"{path.name} is missing. Run session_j_arm7.py --split {split} on this "
                         "model first.")
    return json.loads(io.open(path, encoding="utf-8").read())


CONFIGS = {
    # name: (model, seq, arm, strength)
    "shipped": ("ms-marco-MiniLM-L-2-v2-int8", 256, "7a_control", 0.0),
    "L2-f32-raw": ("ms-marco-MiniLM-L-2-v2", 256, "7a_control", 0.0),
    "L2-f32-7c": ("ms-marco-MiniLM-L-2-v2", 256, "7c_divisive", 0.5),
    "L6-f32-raw": ("ms-marco-MiniLM-L-6-v2", 256, "7a_control", 0.0),
    "L6-f32-7c": ("ms-marco-MiniLM-L-6-v2", 256, "7c_divisive", 0.5),
    "L6-f32-7f-posthoc": ("ms-marco-MiniLM-L-6-v2", 256, "7f_signed_log_POSTHOC", 2.0),
    "ft-L6-raw": ("ms-marco-MiniLM-L-6-v2-ft-session-j", 256, "7a_control", 0.0),
    "ft-L6-7c": ("ms-marco-MiniLM-L-6-v2-ft-session-j", 256, "7c_divisive", 0.5),
    "ft-L2-raw": ("ms-marco-MiniLM-L-2-v2-ft-session-j", 256, "7a_control", 0.0),
    "ft-L2-7c": ("ms-marco-MiniLM-L-2-v2-ft-session-j", 256, "7c_divisive", 0.5),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=["shipped"])
    args = ap.parse_args()

    res = json.loads(io.open(GATE_RESOLUTION, encoding="utf-8").read())
    print("=" * 78)
    print("ARM (a) — ISOTONIC REFIT: reports the ADR-016 bound and STOPS")
    print("=" * 78)
    print(f"  shipped ceiling                  {res['artifact']['shipped_ceiling']:.4f}")
    print(f"  smallest expressible block       {res['bound_on_gated_fit_population']['top_block_rows']} rows"
          f"  = {res['bound_on_gated_fit_population']['rows_per_query_in_one_block']:.2f} per query")
    print(f"  query coverage of that block     100% (229 of 229, both cues)")
    print(f"  ORACLE at this resolution        {res['oracle']['max_calibrated_precision']:.4f}"
          f"   < {THRESHOLD}")
    print(f"  -> a PERFECT retrieval system fails this gate. No refit can clear the threshold,")
    print(f"     so none is fitted. See ADR-016.")

    coverages = [round(x, 2) for x in np.arange(1.0, 0.09, -0.05)]
    report = {"_what": "Session J Part 3 — precision/coverage on held-out, both arms.",
              "arm_a_isotonic_refit": {
                  "run": False,
                  "reason": "ADR-016: the oracle at CALIBRATION_BLOCKS = 256 is "
                            f"{res['oracle']['max_calibrated_precision']}, below the {THRESHOLD} "
                            "threshold, so no refit can clear it whatever features it is given",
                  "bound": res["bound_on_gated_fit_population"],
                  "oracle": res["oracle"],
                  "top_block_coverage": res["top_block_coverage"],
              },
              "arm_b_conformal": {}}

    for name in args.configs:
        model, seq, arm, strength = CONFIGS[name]
        fit_rows = per_query(load_cache("fit", model, seq), arm, strength)
        held_rows = per_query(load_cache("heldout", model, seq), arm, strength)

        print()
        print("=" * 78)
        print(f"ARM (b) — CONFORMAL · {name}  ({model}, seq {seq}, {arm}@{strength})")
        print("=" * 78)
        base_fit = float(np.mean([r["correct"] for r in fit_rows]))
        base_held = float(np.mean([r["correct"] for r in held_rows]))
        print(f"  R@1  fit {base_fit:.4f} (n={len(fit_rows)})   "
              f"held-out {base_held:.4f} (n={len(held_rows)})")

        taus = {}
        print()
        print("  THE GUARANTEE AND THE MEASUREMENT, kept apart:")
        for alpha in ALPHAS:
            t = conformal_tau(fit_rows, alpha)
            tau = t["risk_control"]["tau"]
            sel = np.array([r["margin"] >= tau for r in held_rows])
            hit = np.array([r["correct"] for r in held_rows])[sel]
            n_sel = int(sel.sum())
            lo, hi = clopper_pearson(int(hit.sum()), n_sel)
            wrong_injected = [r for r in held_rows if r["margin"] >= tau and not r["correct"]]
            n_wrong_held = sum(1 for r in held_rows if not r["correct"])
            t["measured_on_heldout"] = {
                "coverage": round(n_sel / len(held_rows), 4),
                "injected": n_sel,
                "precision": round(float(hit.mean()), 4) if n_sel else None,
                "ci95": [round(lo, 4), round(hi, 4)],
                "false_injection_rate_among_wrong_queries": round(
                    len(wrong_injected) / n_wrong_held, 4) if n_wrong_held else None,
                "_the_guarantee_bounds_the_last_line_only": True,
            }
            taus[str(alpha)] = t
            m = t["measured_on_heldout"]
            print(f"    alpha {alpha:<5}  tau {tau:>9.4f}   GUARANTEE: P(inject | wrong) <= {alpha}")
            print(f"                             MEASURED:  P(inject | wrong) = "
                  f"{m['false_injection_rate_among_wrong_queries']}")
            print(f"                             MEASURED:  precision {m['precision']} "
                  f"[{m['ci95'][0]:.4f}, {m['ci95'][1]:.4f}] at coverage {m['coverage']:.4f}"
                  f"  (n={m['injected']})")

        held_curve = curve(held_rows, coverages)
        print()
        print("  PRECISION / COVERAGE, HELD-OUT — the deliverable")
        print(f"  {'coverage':>9} {'n':>5} {'precision':>10} {'95% CI':>18} {'>=0.95?':>9}")
        for pt in held_curve:
            mark = "INTERVAL" if pt["clears_threshold_interval"] else (
                "point" if pt["clears_threshold_point_estimate"] else "no")
            print(f"  {pt['actual_coverage']:>9.4f} {pt['injected']:>5} {pt['precision']:>10.4f} "
                  f"  [{pt['ci95_low']:.4f}, {pt['ci95_high']:.4f}] {mark:>9}")

        any_point = [p for p in held_curve if p["clears_threshold_point_estimate"]]
        any_interval = [p for p in held_curve if p["clears_threshold_interval"]]
        print()
        if any_interval:
            best = max(any_interval, key=lambda p: p["actual_coverage"])
            print(f"  K1 SATISFIED at coverage {best['actual_coverage']:.4f}, "
                  f"threshold {best['threshold']:.4f} — interval lower bound "
                  f"{best['ci95_low']:.4f} >= {THRESHOLD}")
        elif any_point:
            best = max(any_point, key=lambda p: p["actual_coverage"])
            print(f"  point estimate reaches {THRESHOLD} at coverage {best['actual_coverage']:.4f} "
                  f"({best['correct']}/{best['injected']}), but its interval lower bound is "
                  f"{best['ci95_low']:.4f}. NOT sufficient.")
        else:
            top = max(held_curve, key=lambda p: p["precision"])
            print(f"  NO coverage level reaches {THRESHOLD}. Best precision {top['precision']:.4f} "
                  f"at coverage {top['actual_coverage']:.4f} (n={top['injected']}).")
            print(f"  **THIS IS THE K1 ANSWER.**")

        report["arm_b_conformal"][name] = {
            "model": model, "seq": seq, "arm": arm, "strength": strength,
            "r_at_1": {"fit": round(base_fit, 4), "heldout": round(base_held, 4),
                       "fit_n": len(fit_rows), "heldout_n": len(held_rows)},
            "conformal_tau": taus,
            "precision_coverage_heldout": held_curve,
            "group_conditional": group_conditional(fit_rows, held_rows, 0.05),
            "k1_verdict": {
                "any_coverage_clears_point_estimate": bool(any_point),
                "any_coverage_clears_interval": bool(any_interval),
            },
        }

    out = OUT_DIR / f"conformal-{'-'.join(args.configs)}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
