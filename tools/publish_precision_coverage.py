"""Publish the precision/coverage curve and the declared operating point — Session K, Part 3.

The amended K1 (2026-08-08, `ROADMAP.md` → "K1 — amended 2026-08-08", argued in ADR-019) makes the
curve **part of the product**, not a run output:

> 1. The curve ships with the product. Precision at every coverage level from 100% down to 10%,
>    each point with its binomial interval, measured on a held-out split the gate's parameters have
>    never seen.
> 2. The operating point is chosen on the curve and declared, not assumed.

So this writes to two stable locations rather than only into `runs/`:

  * `crates/marlowe-memory/artifacts/precision-coverage-heldout-v1.json` — beside the frozen gate
  * `docs/design/PRECISION-COVERAGE.md` — the human-readable published curve

## It reads the BINARY's dump, not an offline reconstruction

Session J's curve was computed from an offline Python reconstruction of the slate. This one is
computed from `scored-candidates.ndjson`, which the shipped binary wrote while producing the
published R@1 — so the curve and the headline number come from the same pass through the same
graph.

## The reader and the ranking are IMPORTED from `analyze_cue_overlap.py`, not restated

That tool is where this project's binary-side R@1 has been read since Session C, and its
`shipped_order` reproduces `retrieve.rs::select_for_injection`'s five levels: `survived_pruning`
desc, `rerank_score` desc (**NaN last** — `Option`'s own ordering puts `None` first, which is the
opposite, so both sides write it out by hand), `score` desc, `margin` desc, id asc.

**This was written the other way first and it was wrong, which is why the import is not optional.**
The first draft joined gold with `score_longmemeval.read_scored` and re-implemented the ordering
locally. `read_scored` **drops `survived_pruning` and `rerank_score`** — so `rerank_score` came back
`None` for every row, the ranker fell through to the gate order, and the curve was built on a
ranking that was not the shipped one. It did not crash and the numbers looked plausible: R@1 read
0.5411 where the binary reads 0.6725. **Tenth instance of the two-sides-silently-disagree pattern**,
caught only because the second-implementation check demanded an exact match against the canonical
tool. The eligibility rule is imported for the same reason: `analyze_cue_overlap` scores queries
that are non-abstention **and** have at least one gold row in the pool, which is the n=229 the
published numbers are on; the first draft's own rule gave n=245 and n=231.

## The nonconformity score

The **rank-1 minus rank-2 gap on the key actually in force**, which for the shipped configuration is
the raw cross-encoder logit. **A query whose rank 1 or rank 2 carries no rerank score is REFUSED,
not silently handled** — the two would be separated by a different quantity than the one tau is
calibrated on, and a margin computed across that boundary is not comparable to one computed within
it.

## The guarantee and the measurement are two different quantities

Kept in separate fields and printed on separate lines, per ADR-019 §2 and the Session J
pre-registration. The conformal bound covers `P(inject | wrong)` — marginal, distribution-free,
finite-sample. **K1 asks for `P(correct | injected)`**, a selective risk the marginal bound does not
cover. Both are reported. Neither is described as the other.

## Global tau only

No category clears the registered `n >= 40` floor on its wrong-query calibration set. The per-group
n is printed beside the rule so the refusal is visible rather than implied.

    python tools/score_longmemeval.py --out runs/session-k --fit-only --reranking <DIR>
    python tools/publish_precision_coverage.py --run runs/session-k --reranking-label <NAME>
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import beta

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from analyze_cue_overlap import columns, read_dump, shipped_order  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
ARTIFACT_OUT = REPO / "crates" / "marlowe-memory" / "artifacts" / "precision-coverage-heldout-v1.json"
DOC_OUT = REPO / "docs" / "design" / "PRECISION-COVERAGE.md"

ALPHAS = [0.05, 0.10, 0.20, 0.30]
MIN_GROUP_N = 40      # registered in Session J: below this the (1-a)(1+1/n) quantile is the maximum
THRESHOLD = 0.95      # NOT lowered by the amendment. See ADR-019.


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Exact binomial interval. On every point, because n is small exactly where it matters."""
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return lo, hi


def per_query(per: dict, cases: dict) -> list[dict]:
    """One row per query: the rank-1/rank-2 margin on the key in force, and whether rank 1 is gold.

    **The eligibility rule is `analyze_cue_overlap`'s, not a new one:** non-abstention, and at
    least one gold row in the pool. That is the n=229 population every published R@1 in this
    project is computed on, and a curve on a different population would not be comparable to the
    R@1 printed beside it.
    """
    out, refused = [], []
    for qid, rows in per.items():
        case = cases.get(qid)
        if case is None or case.is_abstention:
            continue
        c = columns(rows)
        if c["gold"].sum() == 0:
            continue
        if len(rows) < 2:
            refused.append((qid, f"only {len(rows)} candidate(s); no rank-2 to take a margin from"))
            continue
        order = shipped_order(c["score"], c["margin"], c["survived"], c["rerank"])
        i1, i2 = int(order[0]), int(order[1])
        if np.isnan(c["rerank"][i1]) or np.isnan(c["rerank"][i2]):
            # REFUSED rather than handled. See the module docstring.
            refused.append((qid, "rank 1 or rank 2 carries no rerank score; the margin would "
                                 "cross a key boundary and is not comparable to the calibration"))
            continue
        out.append({
            "query_id": qid,
            "category": case.category,
            "margin": float(c["rerank"][i1] - c["rerank"][i2]),
            "correct": bool(c["gold"][i1]),
        })
    if refused:
        print(f"  REFUSED {len(refused)} quer(y|ies) — margin not defined on the key in force:")
        for qid, why in refused[:5]:
            print(f"    {qid}: {why}")
        if len(refused) > 5:
            print(f"    ... and {len(refused) - 5} more")
    return out


def conformal_tau(fit_rows: list[dict], alpha: float) -> dict:
    """Risk control and coverage control, kept apart and labelled for what each one is."""
    wrong = np.array([r["margin"] for r in fit_rows if not r["correct"]])
    allm = np.array([r["margin"] for r in fit_rows])

    def q(x: np.ndarray, a: float) -> float:
        n = len(x)
        if n == 0:
            return float("inf")
        return float(np.quantile(x, min(1.0, (1 - a) * (1 + 1 / n)), method="higher"))

    return {
        "alpha": alpha,
        "risk_control": {
            "tau": q(wrong, alpha),
            "calibrated_on": "fit queries whose rank 1 is NOT gold",
            "n_calibration": int(len(wrong)),
            "guarantee": (
                f"for an exchangeable new query whose rank 1 is not gold, P(margin >= tau) <= "
                f"{alpha}. A bound on the FALSE-INJECTION RATE AMONG WRONG QUERIES. "
                f"Distribution-free, finite-sample, marginal over the calibration draw."
            ),
            "what_it_is_not": (
                "this is NOT precision. K1 asks for P(correct | injected), a selective risk the "
                "marginal bound does not cover."
            ),
        },
        "coverage_control": {
            "tau": q(allm, alpha),
            "calibrated_on": "ALL fit queries",
            "n_calibration": int(len(allm)),
            "_what_it_controls": (
                "coverage, not risk. The (1-alpha)(1+1/n) quantile over every query selects "
                "roughly the top alpha fraction by margin."
            ),
        },
    }


def curve(rows: list[dict], coverages: list[float]) -> list[dict]:
    margins = np.array([r["margin"] for r in rows])
    correct = np.array([r["correct"] for r in rows])
    n = len(rows)
    out = []
    for target in coverages:
        k = max(1, int(round(target * n)))
        cut = np.sort(margins)[::-1][k - 1]
        sel = margins >= cut
        n_sel, n_hit = int(sel.sum()), int(correct[sel].sum())
        lo, hi = clopper_pearson(n_hit, n_sel)
        out.append({
            "target_coverage": target,
            "actual_coverage": round(n_sel / n, 4),
            "margin_threshold": round(float(cut), 6),
            "injected": n_sel,
            "correct": n_hit,
            "precision": round(n_hit / n_sel, 4),
            "ci95_low": round(lo, 4),
            "ci95_high": round(hi, 4),
            "clears_threshold_point_estimate": bool(n_hit / n_sel >= THRESHOLD),
            "clears_threshold_interval": bool(lo >= THRESHOLD),
        })
    return out


def group_ns(fit_rows: list[dict], held_rows: list[dict]) -> dict:
    by_fit: dict[str, list[dict]] = defaultdict(list)
    for r in fit_rows:
        by_fit[r["category"]].append(r)
    by_held: dict[str, int] = defaultdict(int)
    for r in held_rows:
        by_held[r["category"]] += 1
    out = {}
    for cat, rows in sorted(by_fit.items()):
        wrong = sum(1 for r in rows if not r["correct"])
        out[cat] = {
            "fit_n": len(rows),
            "fit_n_wrong": wrong,
            "heldout_n": by_held.get(cat, 0),
            "eligible_for_group_conditional_tau": wrong >= MIN_GROUP_N,
        }
    return out


def flatness(held_curve: list[dict]) -> dict:
    """The amended criterion's NEW kill condition, evaluated rather than described.

    'The project is reconsidered if the curve is flat -- precision at 10% coverage not materially
    above precision at 100% coverage.' 'Materially' is made concrete here as: the point estimate at
    10% must exceed the point estimate at 100%, AND the interval at 10% must exclude the 100%
    point estimate. The second half is what stops a noise-sized gap on n=23 from reading as a pass.
    """
    at100 = min(held_curve, key=lambda p: abs(p["actual_coverage"] - 1.00))
    at10 = min(held_curve, key=lambda p: abs(p["actual_coverage"] - 0.10))
    higher = at10["precision"] > at100["precision"]
    excludes = at10["ci95_low"] > at100["precision"]
    return {
        "precision_at_100_coverage": at100["precision"],
        "precision_at_10_coverage": at10["precision"],
        "delta": round(at10["precision"] - at100["precision"], 4),
        "ci95_low_at_10": at10["ci95_low"],
        "n_at_10": at10["injected"],
        "point_estimate_higher": higher,
        "interval_at_10_excludes_100_point": excludes,
        "curve_is_flat_KILL": not (higher and excludes),
        "_rule": (
            "flat = NOT (precision@10 > precision@100 AND ci95_low@10 > precision@100). The "
            "interval half is what stops a noise-sized gap on ~23 queries from reading as a pass."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, help="run directory holding heldout/ and fit/")
    ap.add_argument("--reranking-label", required=True,
                    help="the configuration this curve was measured with. Carried into the "
                         "artifact and the doc: a curve without its configuration is unreadable.")
    ap.add_argument("--operating-point", type=float, default=0.10,
                    help="target coverage to DECLARE, on this curve. Default 0.10.")
    args = ap.parse_args()

    run_dir = (REPO / args.run) if not Path(args.run).is_absolute() else Path(args.run)
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()
    cases = {c.query_id: c for c in corpus.cases}

    loaded = {}
    for name in ("fit", "heldout"):
        d = run_dir / name
        # `run.jsonl` is what `write_artifacts` names the transcript. Named here rather than
        # guessed: the Attributor is rebuilt from its ingest responses, and a missing file would
        # produce an empty attribution map -- every query would read as "not gold" and the curve
        # would be a flat zero that looks like a measurement.
        for p in (d / "scored-candidates.ndjson", d / "run.jsonl"):
            if not p.exists():
                raise SystemExit(
                    f"{p} is missing. Produce it first:\n"
                    f"  python tools/score_longmemeval.py --out {args.run} "
                    f"{'--fit-only ' if name == 'fit' else ''}--reranking <DIR>\n"
                    "The tau calibration and the curve must come through the SAME pipeline; "
                    "there is deliberately no fallback to an offline reconstruction."
                )
        print(f"reading {name} ...")
        loaded[name] = per_query(read_dump(d, gold_map), cases)

    fit_rows, held_rows = loaded["fit"], loaded["heldout"]
    r1_fit = float(np.mean([r["correct"] for r in fit_rows]))
    r1_held = float(np.mean([r["correct"] for r in held_rows]))
    print()
    print(f"R@1  fit {r1_fit:.4f} (n={len(fit_rows)})   held-out {r1_held:.4f} (n={len(held_rows)})")

    # ---- the second-implementation check, ENFORCED rather than remembered -------------------
    #
    # This curve is only meaningful if its rank-1 is the binary's rank-1. `analyze_cue_overlap.py`
    # is where this project's binary-side R@1 has been read since Session C, so its number is the
    # authority and this tool must reproduce it EXACTLY -- as Session H's 0.5764 = 0.5764 and
    # Session J's control did. The first draft of this file disagreed at 0.5411 vs 0.6725 and
    # printed a perfectly plausible curve anyway; an exact assertion is what catches that.
    overlap_path = run_dir / "cue-overlap.json"
    if not overlap_path.exists():
        raise SystemExit(
            f"{overlap_path} is missing. Run `python tools/analyze_cue_overlap.py --run "
            f"{args.run}/heldout` first. It is not optional: it is the authority this curve's "
            "rank-1 is checked against, and without it the check silently does not happen."
        )
    canonical = json.loads(io.open(overlap_path, encoding="utf-8").read())
    canonical_r1 = canonical["gold_in_top_k"]["1"].get("shipped")
    if canonical_r1 is None:
        raise SystemExit(
            f"{overlap_path} carries no `shipped` top-1 -- it was built from a dump with no "
            "rerank columns. The curve cannot be checked against it."
        )
    if round(r1_held, 4) != round(canonical_r1, 4):
        raise SystemExit(
            f"SECOND-IMPLEMENTATION CHECK FAILED. This tool reads held-out R@1 "
            f"{r1_held:.4f}; analyze_cue_overlap.py reads {canonical_r1:.4f}. These are two "
            "readings of the same ranking and they must agree exactly. Do NOT publish a curve "
            "until they do -- a curve whose rank-1 is not the binary's rank-1 is a measurement "
            "of a ranking that does not exist."
        )
    print(f"second-implementation check: {r1_held:.4f} == {canonical_r1:.4f}  PASS "
          f"(vs analyze_cue_overlap.py)")

    coverages = [round(x, 2) for x in np.arange(1.0, 0.09, -0.05)]
    held_curve = curve(held_rows, coverages)

    print()
    print("PRECISION / COVERAGE, HELD-OUT, shipped graph")
    print(f"  {'coverage':>9} {'n':>5} {'precision':>10} {'95% CI':>20} {'>=0.95?':>9}")
    for pt in held_curve:
        mark = "INTERVAL" if pt["clears_threshold_interval"] else (
            "point" if pt["clears_threshold_point_estimate"] else "no")
        print(f"  {pt['actual_coverage']:>9.4f} {pt['injected']:>5} {pt['precision']:>10.4f} "
              f"  [{pt['ci95_low']:.4f}, {pt['ci95_high']:.4f}] {mark:>9}")

    taus = {}
    print()
    print("THE GUARANTEE AND THE MEASUREMENT, kept apart:")
    for alpha in ALPHAS:
        t = conformal_tau(fit_rows, alpha)
        tau = t["risk_control"]["tau"]
        sel = np.array([r["margin"] >= tau for r in held_rows])
        hit = np.array([r["correct"] for r in held_rows])[sel]
        n_sel = int(sel.sum())
        lo, hi = clopper_pearson(int(hit.sum()), n_sel)
        n_wrong = sum(1 for r in held_rows if not r["correct"])
        n_wrong_injected = sum(1 for r in held_rows if r["margin"] >= tau and not r["correct"])
        t["measured_on_heldout"] = {
            "coverage": round(n_sel / len(held_rows), 4),
            "injected": n_sel,
            "precision": round(float(hit.mean()), 4) if n_sel else None,
            "ci95": [round(lo, 4), round(hi, 4)],
            "false_injection_rate_among_wrong_queries": (
                round(n_wrong_injected / n_wrong, 4) if n_wrong else None),
            "_the_guarantee_bounds_the_last_line_ONLY": True,
        }
        taus[str(alpha)] = t
        m = t["measured_on_heldout"]
        print(f"  alpha {alpha:<5} tau {tau:>9.4f}  GUARANTEE: P(inject | wrong) <= {alpha}")
        print(f"                            MEASURED:  P(inject | wrong) = "
              f"{m['false_injection_rate_among_wrong_queries']}")
        print(f"                            MEASURED:  precision {m['precision']} "
              f"[{m['ci95'][0]:.4f}, {m['ci95'][1]:.4f}] at coverage {m['coverage']:.4f} "
              f"(n={m['injected']})")

    op = min(held_curve, key=lambda p: abs(p["actual_coverage"] - args.operating_point))
    flat = flatness(held_curve)
    any_interval = [p for p in held_curve if p["clears_threshold_interval"]]

    print()
    print(f"DECLARED OPERATING POINT: coverage {op['actual_coverage']:.4f}  "
          f"precision {op['precision']:.4f}  CI [{op['ci95_low']:.4f}, {op['ci95_high']:.4f}]  "
          f"(n={op['injected']}, margin >= {op['margin_threshold']:.4f})")
    print(f"K1 (original form): {'SATISFIED' if any_interval else 'NOT reached at any coverage'}"
          f" — no level clears {THRESHOLD} by interval" if not any_interval else "")
    print(f"K1 (amended, flatness kill): precision@10 {flat['precision_at_10_coverage']:.4f} vs "
          f"@100 {flat['precision_at_100_coverage']:.4f}, delta {flat['delta']:+.4f}, "
          f"ci_low@10 {flat['ci95_low_at_10']:.4f}  ->  "
          f"{'CURVE IS FLAT — KILL CONDITION MET' if flat['curve_is_flat_KILL'] else 'not flat; kill condition NOT met'}")

    groups = group_ns(fit_rows, held_rows)
    print()
    print(f"GROUP-CONDITIONAL TAU: refused. Registered floor is n >= {MIN_GROUP_N} wrong queries.")
    for cat, g in groups.items():
        print(f"  {cat:32s} fit n={g['fit_n']:>3}  wrong={g['fit_n_wrong']:>3}  "
              f"heldout n={g['heldout_n']:>3}  eligible={g['eligible_for_group_conditional_tau']}")

    artifact = {
        "_what": "The published precision/coverage curve. Required to ship with the product by the "
                 "amended K1 (2026-08-08); see ROADMAP.md and ADR-019.",
        "_measured_by": "tools/publish_precision_coverage.py, from the SHIPPED BINARY's own dump",
        "version": 1,
        "split": "heldout",
        "split_digest": split["digest"],
        "configuration": args.reranking_label,
        "n_queries": len(held_rows),
        "r_at_1": {"heldout": round(r1_held, 4), "fit": round(r1_fit, 4)},
        "threshold": THRESHOLD,
        "_threshold_note": "NOT lowered by the amendment. The criterion's shape changed; its "
                           "number did not. See ADR-019.",
        "precision_coverage_heldout": held_curve,
        "declared_operating_point": op,
        "flatness_kill_condition": flat,
        "conformal": {
            "_the_guarantee_is_not_the_precision": (
                "The conformal bound covers P(inject | wrong) -- marginal, distribution-free, "
                "finite-sample. K1 asks for P(correct | injected), a selective risk it does not "
                "cover. Both are reported here in separate fields and must never be conflated."
            ),
            "nonconformity": "rank-1 minus rank-2 gap on the shipped ranking key (the raw "
                             "cross-encoder logit)",
            "by_alpha": taus,
        },
        "group_conditional": {
            "used": False,
            "rule": f"group-conditional tau only where the wrong-query calibration set has "
                    f"n >= {MIN_GROUP_N}. GLOBAL TAU ONLY: no category clears it.",
            "per_group_n": groups,
        },
    }
    ARTIFACT_OUT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_OUT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    (run_dir / "precision-coverage.json").write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print()
    print(f"WROTE {ARTIFACT_OUT.relative_to(REPO)}")
    print(f"WROTE {(run_dir / 'precision-coverage.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
