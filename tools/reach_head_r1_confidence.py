"""R1 -- reachability for candidate A: a confidence signal fit against RELEVANCE.

The declared operating point selects the top 10% of queries by the rank1-minus-rank2 rerank
margin. That margin is a property of the model's OUTPUT DISTRIBUTION. ADR-017's binding rule says
a correction term must be fitted against RELEVANCE, not against the score, because the two differ
by more than an order of magnitude on this corpus. The gate needs a predictor of CORRECTNESS.
This script asks whether one exists, before anything is built.

Three checks, in the order the protocol requires:

  ADR-010 reach  -- can the shape move precision@10%? Enumerate what CAN and CANNOT move.
  ADR-013 read   -- can the READ vary? Count how many queries change membership in the selected
                    set, in BOTH directions, on the fit split.
  ADR-014 power  -- the contrast is a SELECTOR swap, not a ranking change, so exact McNemar does
                    not apply. State the analogous floor for the test that does (Fisher's exact
                    on the swap set) and confirm the arms disagree that often on the exact
                    contrast the test consumes.

Every feature here is computable at query time from the shipped slate. `category` is measured and
then EXCLUDED from anything shippable -- LongMemEval's question_type is a label, not a runtime
signal, and a selector that reads it would be scoring with the answer sheet.

Prints numbers. Applies nothing. Fit split only, except where a held-out column is explicitly
labelled as the previously-published Session K read.
"""

from __future__ import annotations

import argparse
import json
import math
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import beta, fisher_exact

REPO = Path(__file__).resolve().parents[1]
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
OUT = REPO / "runs" / "session-m0c" / "reach-r1-confidence.json"

OPERATING_COVERAGE = 0.10
# ADR-013's numeric form, inherited from runs/session-i/PREREGISTRATION.json.
MIN_DISCORDANT_FOR_A_REPORTED_DELTA = 10


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - a / 2.0, k + 1, n - k))
    return (lo, hi)


def session_of(turn_id: str) -> str:
    """turn_id is f"{session_id}-{turn_index}"; session ids themselves contain hyphens, so split
    from the right exactly once."""
    return turn_id.rsplit("-", 1)[0]


def turn_index_of(turn_id: str) -> int:
    try:
        return int(turn_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return -1


def features(rec: dict) -> dict[str, float]:
    """Query-level features, all computable from the shipped depth-10 slate at query time."""
    s = np.asarray(rec["rerank_scores"], dtype=float)   # already in shipped (descending) order
    wp = np.asarray(rec["wordpieces"], dtype=float)
    roles = rec["roles"]
    tids = rec["turn_ids"]
    p = np.exp(s - s.max())
    p = p / p.sum()

    sess = [session_of(t) for t in tids]
    idxs = [turn_index_of(t) for t in tids]

    return {
        # --- the incumbent, and its immediate neighbours in the same family ---
        "margin": float(s[0] - s[1]),
        "top1_score": float(s[0]),                       # ABSOLUTE confidence; currently unused
        "margin_1_3": float(s[0] - s[2]),
        "margin_1_mean_rest": float(s[0] - s[1:].mean()),
        "softmax_p1": float(p[0]),
        "slate_entropy": float(-(p * np.log(p + 1e-12)).sum()),
        "slate_std": float(s.std()),
        "score_range": float(s[0] - s[-1]),
        # --- the relevance-side priors STATE.md names but the margin cannot see ---
        "top1_log_wordpieces": float(math.log(max(wp[0], 1.0))),
        "top1_is_assistant": 1.0 if roles[0] == "assistant" else 0.0,
        "assistant_share": float(np.mean([r == "assistant" for r in roles])),
        "slate_median_log_wp": float(np.median(np.log(np.maximum(wp, 1.0)))),
        # --- joint structure: what the slate says about itself ---
        "n_sessions_in_slate": float(len(set(sess))),
        "top1_session_share": float(sum(x == sess[0] for x in sess)),
        "rank12_same_session": 1.0 if sess[0] == sess[1] else 0.0,
        "rank12_turn_gap": float(abs(idxs[0] - idxs[1])) if sess[0] == sess[1] else 99.0,
        "rank12_opposite_role": 1.0 if roles[0] != roles[1] else 0.0,
        # --- the query side ---
        "question_words": float(len(rec["question"].split())),
    }


def load(split: str) -> tuple[list[dict], np.ndarray, dict[str, np.ndarray], list[str]]:
    d = json.loads(Path(str(SLATES).format(split=split)).read_text(encoding="utf-8"))
    if d["n"] != 229:
        raise SystemExit(f"REFUSING: {split} has n={d['n']}, canonical is 229")
    recs = d["records"]
    y = np.asarray([r["correct"] for r in recs], dtype=bool)
    feats = [features(r) for r in recs]
    names = list(feats[0])
    X = {k: np.asarray([f[k] for f in feats], dtype=float) for k in names}
    return recs, y, X, names


def precision_at_coverage(key: np.ndarray, y: np.ndarray, coverage: float) -> dict:
    """Exactly publish_precision_coverage.curve's rule: k = max(1, round(c*n)); cut is the k-th
    largest key; select key >= cut, so ties can push actual coverage above target."""
    n = len(key)
    k = max(1, round(coverage * n))
    cut = float(np.sort(key)[::-1][k - 1])
    sel = key >= cut
    inj = int(sel.sum())
    cor = int(y[sel].sum())
    lo, hi = clopper_pearson(cor, inj)
    return {"actual_coverage": round(inj / n, 4), "cut": cut, "injected": inj, "correct": cor,
            "precision": round(cor / inj, 4), "ci95_low": round(lo, 4), "ci95_high": round(hi, 4),
            "selected": sel}


def auc(key: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUC, ties averaged."""
    order = np.argsort(key, kind="stable")
    ranks = np.empty(len(key), dtype=float)
    ranks[order] = np.arange(1, len(key) + 1, dtype=float)
    # average ranks over ties
    uniq, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    sums = np.zeros(len(uniq))
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    npos, nneg = int(y.sum()), int((~y).sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    return float((ranks[y].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--coverage", type=float, default=OPERATING_COVERAGE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    recs_f, y_f, X_f, names = load("fit")
    n = len(y_f)

    print("=" * 92)
    print("R1 -- CAN A RELEVANCE-FITTED CONFIDENCE SIGNAL MOVE PRECISION AT THE HEAD?")
    print("=" * 92)
    print(f"fit split, n={n}, base rate correct = {y_f.mean():.4f} ({int(y_f.sum())}/{n})")
    print(f"coverage under test = {args.coverage:.0%}  ->  n_c = {max(1, round(args.coverage*n))}")
    print()

    # ---------------- ADR-010: reach ----------------
    print("-" * 92)
    print("ADR-010 REACH -- what CAN and CANNOT move")
    print("-" * 92)
    n_c = max(1, round(args.coverage * n))
    oracle_correct = min(n_c, int(y_f.sum()))
    base = precision_at_coverage(X_f["margin"], y_f, args.coverage)
    can = {
        "precision at the operating point": (
            f"YES. The selector chooses WHICH {n_c} of {n} queries are injected; correctness of "
            f"each is fixed by the ranker. {int(y_f.sum())} queries are correct, so any count from "
            f"0 to {oracle_correct} of {n_c} is structurally reachable. Incumbent (margin): "
            f"{base['correct']}/{base['injected']}."),
    }
    cannot = {
        "R@1 at full coverage": (
            "NO, STRUCTURALLY. A selector reorders nothing inside a slate. R@1 is fixed at 0.7555 "
            "(fit) / 0.6725 (held-out) for every candidate-A variant. Registering an R@1 band on "
            "this shape would repeat Session D's error verbatim."),
        "input recall / R@5 / R@10": (
            "NO, STRUCTURALLY. Same reason -- the slate and its contents are untouched."),
        "the R0 interval verdict at 10% coverage": (
            "NO. Clopper-Pearson at n_c=23 tops out at a 0.8518 lower bound even at 23/23. "
            "No selector clears 0.95 by interval here; see reach-r0-attainability.json."),
    }
    for k, v in can.items():
        print(f"  CAN MOVE     {k}\n               {v}")
    for k, v in cannot.items():
        print(f"  CANNOT MOVE  {k}\n               {v}")
    print()

    # ---------------- single-feature screen ----------------
    print("-" * 92)
    print(f"SINGLE-FEATURE SCREEN on FIT -- can anything beat the margin at {args.coverage:.0%}?")
    print("-" * 92)
    print(f"{'feature':<26} {'AUC':>7} {'prec@c':>8} {'k/n_c':>9} {'ci_low':>8} {'swap':>6}")
    print("-" * 92)
    base_sel = base["selected"]
    screen = {}
    for name in names:
        for sign, tag in ((1.0, ""), (-1.0, " (neg)")):
            key = sign * X_f[name]
            a = auc(key, y_f)
            r = precision_at_coverage(key, y_f, args.coverage)
            swap = int((r["selected"] & ~base_sel).sum())
            screen[name + tag] = {"auc": round(a, 4), **{k: v for k, v in r.items()
                                                         if k != "selected"},
                                  "swap_vs_margin": swap}
            if sign > 0 or a > 0.5:
                print(f"{name+tag:<26} {a:>7.4f} {r['precision']:>8.4f} "
                      f"{r['correct']:>4d}/{r['injected']:<4d} {r['ci95_low']:>8.4f} {swap:>6d}")
    print()

    # ---------------- ADR-013: can the read vary ----------------
    print("-" * 92)
    print("ADR-013 READ -- can the selected SET vary, in both directions?")
    print("-" * 92)
    print(f"floor: >= {MIN_DISCORDANT_FOR_A_REPORTED_DELTA} queries change membership before any "
          f"delta is reportable")
    varied = []
    for label, rec in screen.items():
        if rec["swap_vs_margin"] >= MIN_DISCORDANT_FOR_A_REPORTED_DELTA:
            varied.append((label, rec["swap_vs_margin"], rec["precision"]))
    varied.sort(key=lambda t: -t[2])
    for label, sw, pr in varied[:12]:
        print(f"  {label:<28} swaps {sw:>3d}  prec@c {pr:.4f}")
    if not varied:
        print("  NONE. Every single feature selects essentially the margin's own set.")
    print()

    # ---------------- ADR-014: power on the exact contrast ----------------
    print("-" * 92)
    print("ADR-014 POWER -- the contrast this test consumes, and the floor for alpha = 0.05")
    print("-" * 92)
    print("  The contrast is a SELECTOR SWAP at matched coverage, not a ranking change, so exact")
    print("  McNemar does not apply -- there are no paired per-query outcomes, because the two")
    print("  arms inject DIFFERENT queries. The test that does apply is Fisher's exact on the")
    print("  2x2 of (arm-A-only vs arm-B-only) x (correct vs wrong) over the swap set.")
    print()
    print("  Smallest attainable two-sided Fisher p with m swaps each way is 2 / C(2m, m):")
    floor_m = None
    for m in range(1, 10):
        p_min = 2.0 / math.comb(2 * m, m)
        reachable = p_min <= 0.05
        if reachable and floor_m is None:
            floor_m = m
        print(f"    m = {m}:  2/C({2*m},{m}) = {p_min:.4f}   "
              f"{'REACHABLE' if reachable else 'unreachable at alpha=0.05'}")
    print(f"\n  => MINIMUM SWAP COUNT AT WHICH alpha = 0.05 IS ATTAINABLE: m >= {floor_m}")
    print(f"     (against ADR-013's separate floor of {MIN_DISCORDANT_FOR_A_REPORTED_DELTA} for "
          f"reporting a delta at all, which is the binding one here)")
    print()

    # the strongest single alternative, tested on the exact contrast
    best = max((v for k, v in screen.items() if v["swap_vs_margin"] >= floor_m),
               key=lambda v: v["precision"], default=None)
    best_label = next((k for k, v in screen.items() if v is best), None)
    if best is not None:
        print(f"  strongest single-feature alternative meeting the swap floor: {best_label}")
        print(f"    prec@c {best['precision']:.4f} ({best['correct']}/{best['injected']}) vs "
              f"margin {base['precision']:.4f} ({base['correct']}/{base['injected']}), "
              f"swaps {best['swap_vs_margin']}")

    # ---------------- the oracle bound on selection, stated but NOT registered ----------------
    print()
    print("-" * 92)
    print("ORACLE ON SELECTION -- reported, and explicitly NOT a band (ADR-010)")
    print("-" * 92)
    print(f"  A perfect selector reaches {oracle_correct}/{n_c} = {oracle_correct/n_c:.4f} on fit.")
    print("  This is the ceiling on candidate A and it is NOT registerable as a band: Session D")
    print("  registered a ceiling its shape could not move and ADR-010 exists because of it.")

    artifact = {
        "_what": "R1 reachability for a relevance-fitted confidence signal, fit split only.",
        "split": "fit",
        "n": n,
        "coverage_under_test": args.coverage,
        "n_c": n_c,
        "base_rate_correct": round(float(y_f.mean()), 4),
        "incumbent_margin_selector": {k: v for k, v in base.items() if k != "selected"},
        "adr_010_reach": {"can_move": can, "cannot_move": cannot,
                          "oracle_on_selection": {"correct": oracle_correct, "n_c": n_c,
                                                  "precision": round(oracle_correct / n_c, 4),
                                                  "_not_a_band": "ADR-010: a ceiling the shape "
                                                                 "cannot move is not a valid read; "
                                                                 "reported only."}},
        "single_feature_screen": screen,
        "adr_013_read_can_vary": {
            "floor": MIN_DISCORDANT_FOR_A_REPORTED_DELTA,
            "features_clearing_the_floor": [{"feature": l, "swaps": s, "precision": p}
                                            for l, s, p in varied],
        },
        "adr_014_power": {
            "alpha": 0.05,
            "test": "Fisher's exact, two-sided, on the 2x2 of (arm-A-only vs arm-B-only) x "
                    "(correct vs wrong) over the swap set at matched coverage",
            "why_not_mcnemar": "the arms inject different queries, so there are no paired "
                               "per-query outcomes for McNemar to consume",
            "min_swaps_for_alpha": floor_m,
            "formula": "smallest attainable two-sided p is 2 / C(2m, m)",
            "contrast_the_test_consumes": "new selector vs rank1-minus-rank2 rerank margin, at "
                                          "matched coverage, same ranking, same slate, fit split",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
