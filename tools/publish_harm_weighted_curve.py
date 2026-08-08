"""Harm-weighted precision beside R@1, at the operating point and across the coverage curve.

Brief Sec 5.7's argument is about HARM, not accuracy: a wrong injected memory corrupts reasoning,
which is why the design is precision-first with abstention. R@1 and the published
precision/coverage curve treat every rank-1 failure as equal. They are not equal. A topically
adjacent turn that adds nothing costs tokens; a superseded fact injected as current is the failure
the trust-class and supersession machinery exists to prevent.

This reports both, on the same axis, so a configuration that trades a merely-useless injection for
a harmful one is visible. Under R@1 that trade is invisible; under Sec 5.7 it is a regression.

Three quantities per coverage level, each with an exact Clopper-Pearson interval:

  precision_published   rank 1 is any gold turn. This is the number in PRECISION-COVERAGE.md.
  precision_current     rank 1 states the value the `answer` field holds. Strictly smaller,
                        because the published number counts superseded gold as a hit.
  harm_rate             rank 1 is a superseded fact presented as current.

The coverage key is the rank1-minus-rank2 rerank margin, identical to
`publish_precision_coverage.curve`, so the rows line up with the published curve point for point.

**The question this exists to answer is whether harm concentrates at the HEAD.** If the harm rate
falls with coverage, abstention already suppresses it and Sec 5.7's machinery is doing its job
through a different route. If it RISES at the head, the system is most confident exactly where it
is most harmful, and that is a defect of a different order from a low R@1.

Reads the shipped configuration only. Fits nothing, selects nothing, proposes nothing.
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

from reach_harm_r5_classes import CLASSES, HARMFUL, classify, load_case_structure  # noqa: E402

SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
SPLIT_PATH = REPO / "tools" / "split.json"
OUT = REPO / "runs" / "session-m0c" / "harm-weighted-curve.json"
DOC = REPO / "docs" / "design" / "HARM-WEIGHTED-PRECISION.md"

# from docs/design/PRECISION-COVERAGE.md -- the rows this curve must line up with
PUBLISHED = {1.00: 0.6725, 0.10: 0.9130}
PUBLISHED_MARGIN_AT_10 = 1.1651


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - a / 2.0, k + 1, n - k))
    return (lo, hi)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="heldout", choices=["fit", "heldout"])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--write-doc", action="store_true")
    args = ap.parse_args()

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    cases = load_case_structure(REPO / split["corpus_path"])
    recs = json.loads(Path(str(SLATES).format(split=args.split)).read_text(
        encoding="utf-8"))["records"]
    n = len(recs)

    cls = np.array([classify(r["turn_ids"][0], cases[r["query_id"]]) for r in recs])
    margin = np.array([r["margin"] for r in recs], dtype=float)
    published_ok = np.isin(cls, ["current", "superseded"])
    current_ok = cls == "current"
    harmful = np.isin(cls, list(HARMFUL))

    # the control: the published-gold read must reproduce PRECISION-COVERAGE.md exactly
    r1 = published_ok.mean()
    want = PUBLISHED[1.00] if args.split == "heldout" else 0.7555
    if round(float(r1), 4) != want:
        raise SystemExit(f"REFUSING: published-gold R@1 reads {r1:.4f}, canonical is {want}. "
                         f"The class partition does not reproduce the shipped ranking.")
    print(f"  CONTROL: published-gold R@1 {r1:.4f} == canonical {want}  PASS")

    coverages = [round(x, 2) for x in np.arange(1.0, 0.09, -0.05)]
    rows = []
    print()
    print("=" * 104)
    print(f"HARM-WEIGHTED PRECISION / COVERAGE -- {args.split}, n={n}, shipped configuration")
    print("=" * 104)
    print(f"{'cov':>6} {'n_c':>5} | {'published':>9} {'95% CI':>18} | {'current':>8} "
          f"{'95% CI':>18} | {'harm':>6} {'harmful':>8}")
    print("-" * 104)
    for c in coverages:
        k = max(1, round(c * n))
        cut = float(np.sort(margin)[::-1][k - 1])
        sel = margin >= cut
        m = int(sel.sum())
        kp, kc, kh = int(published_ok[sel].sum()), int(current_ok[sel].sum()), int(harmful[sel].sum())
        plo, phi = clopper_pearson(kp, m)
        clo, chi = clopper_pearson(kc, m)
        hlo, hhi = clopper_pearson(kh, m)
        rows.append({"target_coverage": c, "actual_coverage": round(m / n, 4),
                     "margin_threshold": round(cut, 6), "injected": m,
                     "precision_published": round(kp / m, 4),
                     "ci95_published": [round(plo, 4), round(phi, 4)],
                     "precision_current": round(kc / m, 4),
                     "ci95_current": [round(clo, 4), round(chi, 4)],
                     "harm_count": kh, "harm_rate": round(kh / m, 4),
                     "ci95_harm": [round(hlo, 4), round(hhi, 4)],
                     "inflation_published_minus_current": round((kp - kc) / m, 4)})
        print(f"{m/n:>6.1%} {m:>5} | {kp/m:>9.4f} [{plo:>7.4f},{phi:>7.4f}] | {kc/m:>8.4f} "
              f"[{clo:>7.4f},{chi:>7.4f}] | {kh/m:>6.4f} {kh:>4d}/{m:<4d}")

    at100 = rows[0]
    at10 = min(rows, key=lambda r: abs(r["actual_coverage"] - 0.10))

    print()
    print("-" * 104)
    print("DOES HARM CONCENTRATE AT THE HEAD?")
    print("-" * 104)
    print(f"  harm rate at 100% coverage : {at100['harm_rate']:.4f} "
          f"({at100['harm_count']}/{at100['injected']})")
    print(f"  harm rate at  10% coverage : {at10['harm_rate']:.4f} "
          f"({at10['harm_count']}/{at10['injected']})  CI {at10['ci95_harm']}")
    direction = ("RISES at the head -- the system is most confident where it is most harmful"
                 if at10["harm_rate"] > at100["harm_rate"] else
                 "FALLS at the head -- abstention already suppresses the harmful class"
                 if at10["harm_rate"] < at100["harm_rate"] else
                 "is FLAT -- the confidence signal carries no information about harm")
    print(f"  => harm {direction}")

    print()
    print("-" * 104)
    print("THE OPERATING POINT, RESTATED UNDER SEC 5.7")
    print("-" * 104)
    print(f"  published   precision {at10['precision_published']:.4f} "
          f"CI {at10['ci95_published']}   <- docs/design/PRECISION-COVERAGE.md")
    print(f"  current     precision {at10['precision_current']:.4f} "
          f"CI {at10['ci95_current']}   <- counting only the value the answer holds")
    print(f"  inflation   {at10['inflation_published_minus_current']:+.4f}")

    # the partition of everything that is NOT the current value -- the user's actual question
    not_current = ~current_ok
    print()
    print("-" * 104)
    print("OF THE INJECTIONS THAT ARE NOT THE CURRENT VALUE, HOW MANY ARE HARMFUL?")
    print("-" * 104)
    tot = int(not_current.sum())
    for cl in CLASSES:
        if cl == "current":
            continue
        k = int((cls == cl).sum())
        tag = "  HARMFUL" if cl in HARMFUL else "  merely useless"
        print(f"    {cl:<16} {k:>4d}  ({k/tot:>6.1%} of the {tot} non-current){tag}")
    kh_all = int(harmful.sum())
    print(f"    {'-> harmful':<16} {kh_all:>4d}  ({kh_all/tot:>6.1%})")
    print(f"    {'-> useless':<16} {tot-kh_all:>4d}  ({(tot-kh_all)/tot:>6.1%})")

    # knowledge-update on its own, where the class is expressible at all
    ku = np.array([cases[r["query_id"]]["question_type"] == "knowledge-update" for r in recs])
    kn = int(ku.sum())
    print()
    print(f"  ON KNOWLEDGE-UPDATE ALONE (n={kn}), where supersession is expressible:")
    print(f"    published R@1  {published_ok[ku].mean():.4f} "
          f"({int(published_ok[ku].sum())}/{kn})")
    print(f"    current   R@1  {current_ok[ku].mean():.4f} ({int(current_ok[ku].sum())}/{kn})")
    print(f"    harm rate      {harmful[ku].mean():.4f} ({int(harmful[ku].sum())}/{kn})")
    stale_hits = int(((cls == "superseded") & ku).sum())
    hits = int(published_ok[ku].sum())
    print(f"    ** {stale_hits} of the {hits} apparent hits ({stale_hits/max(hits,1):.1%}) are the "
          f"STALE value scored as correct **")

    artifact = {
        "_what": "harm-weighted precision beside the published precision/coverage curve",
        "_why": "brief Sec 5.7 is about harm, not accuracy; R@1 treats all failures as equal",
        "_the_classifier": "the CURRENT gold turn is the one whose text states the `answer`. No "
                           "date or suffix ordering is used -- see reach_harm_r5_classes."
                           "load_case_structure for why.",
        "split": args.split, "n": n, "configuration": "ms-marco-MiniLM-L-2-v2-ft-session-j "
                                                      "(f32, seq 256, depth 10)",
        "control_reproduces_published_r_at_1": True,
        "rank1_classes": {c: int((cls == c).sum()) for c in CLASSES},
        "r_at_1_published": round(float(published_ok.mean()), 4),
        "r_at_1_current_only": round(float(current_ok.mean()), 4),
        "harm_rate_overall": round(float(harmful.mean()), 4),
        "curve": rows,
        "at_100_coverage": at100, "at_10_coverage": at10,
        "harm_concentration": {"at_100": at100["harm_rate"], "at_10": at10["harm_rate"],
                               "reading": direction},
        "non_current_partition": {c: int((cls == c).sum()) for c in CLASSES if c != "current"},
        "knowledge_update": {
            "n": kn,
            "r_at_1_published": round(float(published_ok[ku].mean()), 4),
            "r_at_1_current_only": round(float(current_ok[ku].mean()), 4),
            "harm_rate": round(float(harmful[ku].mean()), 4),
            "stale_hits_among_apparent_hits": f"{stale_hits}/{hits}",
        },
        "the_machinery": {
            "sec_4_3_exclusion_exists": True,
            "where": "entry.rs:124 is_injection_candidate -> superseded_by.is_none(); called at "
                     "retrieve.rs:328",
            "can_it_fire_on_this_corpus": "only via consolidation's 0.98-cosine near-duplicate "
                                          "merge (consolidate.rs:697). ingest.rs:142 hardcodes "
                                          "None and the Sec 4.6 wire has no supersession field, so "
                                          "a caller cannot assert it.",
            "verdict": "the exclusion is LIVE and BLIND. Not a wiring defect -- a missing "
                       "contradiction detector, which store.rs:133 defers explicitly. ADR-012 "
                       "measured pairs at >=0.98 cosine as 0.0086% of 30.6M.",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
