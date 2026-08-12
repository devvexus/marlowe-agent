"""H-C: SLATE-UNIQUE IDF MASS -- the mass a candidate carries that NO OTHER SLATE MEMBER carries.

    python tools/slate_unique_mass.py
    -> runs/session-m0c-m/slate-unique-mass.json

## The hypothesis, stated mechanically

The unifying fact: gold turns are multi-topic with a narrow answer; distractors are single-topic and
coherent -- AND THE DISTRACTORS ARRIVE IN CLUSTERS (near-misses `22d2cb42`: ranks 1,3,4,5 all "music
shop on Main St"; `3ba21379`: ranks 1,2,3,4 all Mustang GT350R). So the gold's extra topics and its
narrow answer clause are, by construction, content no other slate member carries.

For each candidate in the depth-10 slate, over the content-word TYPE set:

    unique(c)      = tokens(c) \\ union of tokens(d) for d in the comparison set
    unique_mass(c) = sum of idf[w] for w in unique(c)
    frac(c)        = unique_mass(c) / total_mass(c)

The feature, oriented HIGHER MEANS FLIP, is `frac(rank2) - frac(rank1)`. **tau = 0, parameter-free.**

  * PRIMARY   comparison set = the other 9 slate members, head pair INCLUDED in each other's.
  * SECONDARY the two head members EXCLUDED from each other's comparison set, so they cannot cancel.

The FRACTION is primary because it is length-invariant; `length / ln(words)` is already dead
(0.554 vs 0.520, p=0.758). The unnormalised sum is reported beside it.

## Why this is not the dead `non_query_mass` feature

`non_query_mass` measures mass unlicensed by the QUESTION (0 net, negative inverse). This measures
mass unlicensed by the SLATE -- a different denominator and a different mechanism. Whether that
distinction survives contact with the data is exactly what the reported correlation answers.

## REGISTERED PREDICTION, written before the first run

  * +2 to +6 net cases at tau = 0 on fit.
  * FAILS the above-0.084 test: 0 or negative net above the band.
  * Correlation with `non_query_mass_norm_gap` HIGH (>0.5) -- and if it is, this is the dead
    feature in new clothes and that is to be said plainly.

## Reuse, not re-implementation

Everything structural is imported: `head_probe.build` (which carries the fit R@1 = 0.7555 gate),
`head_probe.evaluate/score_feature/print_curve` (the flip harness and its sign-inverted control),
`head_probe.build_idf`, `correct_case_control.content_words` and `.cue_only_order`,
`sweep_reranker_frontier.shipped_order`, `failure_forensics.SLATE_DEPTH`, `reach_pools.turn_texts`.
`head_probe.FEATURES` is mutated at runtime; `tools/head_probe.py` is not edited.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import numpy as np  # noqa: E402
from scipy.stats import mannwhitneyu, pearsonr, spearmanr  # noqa: E402

import head_probe as HP  # noqa: E402
from correct_case_control import content_words, cue_only_order  # noqa: E402
from failure_forensics import SLATE_DEPTH  # noqa: E402
from reach_pools import turn_texts  # noqa: E402
from sweep_reranker_frontier import shipped_order  # noqa: E402

OUT_PATH = REPO / "runs" / "session-m0c-m" / "slate-unique-mass.json"

BAND = 0.084  # THE DECISIVE TEST: above this the two head scores are not effectively identical
POSITIVE, NEGATIVE, AMBIGUOUS = HP.POSITIVE, HP.NEGATIVE, HP.AMBIGUOUS

# The four registered feature names. All oriented HIGHER MEANS FLIP (promote rank 2).
PRIMARY = "slate_unique_frac_primary"
SECONDARY = "slate_unique_frac_secondary"
PRIMARY_RAW = "slate_unique_mass_primary_unnormalised"
SECONDARY_RAW = "slate_unique_mass_secondary_unnormalised"


# -- the statistic ---------------------------------------------------------------------------------


def slate_unique_fields(pool, texts, idf, default_idf, slate_idx, i1, i2) -> dict:
    """`unique_mass`, `total_mass` and their ratio for the head pair, under both comparison sets."""
    toks = {i: content_words(texts.get(pool.candidates[i].turn_id) or "") for i in slate_idx}

    def mass(words) -> float:
        return float(sum(idf.get(w, default_idf) for w in words))

    def unique_against(i, comparison) -> set:
        others: set = set()
        for j in comparison:
            if j != i:
                others |= toks[j]
        return toks[i] - others

    out = {}
    for label, i in (("r1", i1), ("r2", i2)):
        total = mass(toks[i])
        # PRIMARY: every other slate member, the head partner included.
        u_pri = mass(unique_against(i, [j for j in slate_idx if j != i]))
        # SECONDARY: the head partner excluded, so the two heads cannot cancel each other.
        u_sec = mass(unique_against(i, [j for j in slate_idx if j not in (i1, i2)]))
        out[f"{label}_total_mass"] = round(total, 4)
        out[f"{label}_unique_mass_primary"] = round(u_pri, 4)
        out[f"{label}_unique_mass_secondary"] = round(u_sec, 4)
        out[f"{label}_unique_frac_primary"] = round(u_pri / total, 6) if total else None
        out[f"{label}_unique_frac_secondary"] = round(u_sec / total, 6) if total else None
        out[f"{label}_n_content_words"] = len(toks[i])
    out["slate_size"] = len(slate_idx)

    def gap(a, b):
        return None if (a is None or b is None) else round(b - a, 6)

    out["slate_unique_frac_primary_gap"] = gap(
        out["r1_unique_frac_primary"], out["r2_unique_frac_primary"]
    )
    out["slate_unique_frac_secondary_gap"] = gap(
        out["r1_unique_frac_secondary"], out["r2_unique_frac_secondary"]
    )
    out["slate_unique_mass_primary_gap"] = gap(
        out["r1_unique_mass_primary"], out["r2_unique_mass_primary"]
    )
    out["slate_unique_mass_secondary_gap"] = gap(
        out["r1_unique_mass_secondary"], out["r2_unique_mass_secondary"]
    )
    return out


def f_primary(p):
    return p["slate_unique_frac_primary_gap"]


def f_secondary(p):
    return p["slate_unique_frac_secondary_gap"]


def f_primary_raw(p):
    return p["slate_unique_mass_primary_gap"]


def f_secondary_raw(p):
    return p["slate_unique_mass_secondary_gap"]


# -- the tau = 0 operating point, computed here rather than read off the curve ---------------------
#
# `score_feature`'s curve only carries taus that are ATTAINED feature values, and `>= tau` includes
# the tie block. The hypothesis says "when rank 2's fraction EXCEEDS rank 1's", which is strict, so
# both readings are computed and both are printed. A tie flipped is a coin flip dressed as a rule.


def operating_point(pairs, fn, n_queries, strict: bool, subset=None) -> dict:
    rows = pairs if subset is None else subset
    gained = lost = amb = undefined = 0
    for p in rows:
        v = fn(p)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            undefined += 1
            continue
        fires = (v > 0.0) if strict else (v >= 0.0)
        if not fires:
            continue
        lab = p["label"]
        gained += lab == POSITIVE
        lost += lab == NEGATIVE
        amb += lab == AMBIGUOUS
    return {
        "rule": ("f > 0 (strict, 'exceeds')" if strict else "f >= 0 (ties flipped too)"),
        "n_pairs_considered": len(rows),
        "n_undefined": undefined,
        "n_flipped": gained + lost + amb,
        "flips_gained": gained,
        "flips_lost": lost,
        "flips_ambiguous": amb,
        "net_cases": gained - lost,
        "net_r1_delta": round((gained - lost) / n_queries, 4),
        "precision_on_decisive": (
            round(gained / (gained + lost), 4) if (gained + lost) else None
        ),
    }


def label_counts(rows) -> dict:
    return {
        POSITIVE: sum(1 for p in rows if p["label"] == POSITIVE),
        NEGATIVE: sum(1 for p in rows if p["label"] == NEGATIVE),
        AMBIGUOUS: sum(1 for p in rows if p["label"] == AMBIGUOUS),
    }


def print_op(tag: str, op: dict, avail: dict) -> None:
    print(
        f"  {tag:34s} flips {op['n_flipped']:>4d}  GAINED {op['flips_gained']:>3d}  "
        f"LOST {op['flips_lost']:>3d}  amb {op['flips_ambiguous']:>3d}  "
        f"net {op['net_cases']:>+4d}  dR@1 {op['net_r1_delta']:>+7.4f}  "
        f"prec {op['precision_on_decisive'] if op['precision_on_decisive'] is not None else '-'}"
        f"   [available POS {avail[POSITIVE]} NEG {avail[NEGATIVE]}]"
    )


def separation(pairs, fn, name: str) -> dict:
    """Does the statistic separate the POSITIVE pairs from the NEGATIVE pairs AT ALL?

    This is the `control.json` read in its head-pair form: the 110 NEGATIVE pairs ARE the solved
    cases whose rank-2 runner-up is not gold (gate 2 of `head_probe` checks that identity against
    `control.json`'s `strict_successes_competitor_not_gold`). A statistic present in 40% of the
    failures and 38% of the successes is noise, and this is where that shows.
    """
    by = {POSITIVE: [], NEGATIVE: [], AMBIGUOUS: []}
    for p in pairs:
        v = fn(p)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        by[p["label"]].append(float(v))
    pos, neg = np.array(by[POSITIVE]), np.array(by[NEGATIVE])
    u, pval = mannwhitneyu(pos, neg, alternative="two-sided") if len(pos) and len(neg) else (None, None)
    out = {"feature": name}
    for lab, arr in (("POSITIVE", pos), ("NEGATIVE", neg), ("AMBIGUOUS", np.array(by[AMBIGUOUS]))):
        out[lab] = {
            "n": int(len(arr)),
            "mean": round(float(arr.mean()), 6) if len(arr) else None,
            "median": round(float(np.median(arr)), 6) if len(arr) else None,
            "sd": round(float(arr.std(ddof=1)), 6) if len(arr) > 1 else None,
            "frac_gt_0": round(float((arr > 0).mean()), 4) if len(arr) else None,
        }
    out["mannwhitney_u"] = None if u is None else float(u)
    out["mannwhitney_p"] = None if pval is None else round(float(pval), 6)
    if len(pos) and len(neg):
        # Rank-biserial / AUC of POSITIVE over NEGATIVE. Reported because it is the quantity a
        # correlation-minded reader would reach for -- and it is NOT the headline. Flips are.
        out["auc_pos_over_neg"] = round(float(u) / (len(pos) * len(neg)), 4)
        pooled = math.sqrt(((len(pos) - 1) * pos.var(ddof=1) + (len(neg) - 1) * neg.var(ddof=1))
                           / max(len(pos) + len(neg) - 2, 1))
        out["cohens_d"] = round(float((pos.mean() - neg.mean()) / pooled), 4) if pooled else None
    return out


def main() -> int:
    # -- the gate. `head_probe.build` refuses unless the reconstruction reads fit R@1 0.7555 -------
    pools, pairs, r1 = HP.build()
    n = len(pairs)

    texts_all = turn_texts()
    idf, default_idf, n_docs = HP.build_idf(pools, texts_all)

    # -- attach the statistic, and check the slate is the slate -----------------------------------
    slate_mismatch = []
    for p in pairs:
        qid = p["query_id"]
        pool = pools[qid]
        texts = texts_all.get(qid, {})
        order, pre = shipped_order(pool), cue_only_order(pool)
        i1, i2 = int(order[0]), int(order[1])
        slate_idx = [int(v) for v in pre[:SLATE_DEPTH]]
        # The slate the cross-encoder ACTUALLY scored is the set with a rerank logit. If the
        # cue-only top-10 is not that set, this feature is being computed over a slate the product
        # never formed -- so it is checked rather than assumed.
        actually_reranked = {i for i, c in enumerate(pool.candidates) if c.rerank_score is not None}
        if set(slate_idx) != actually_reranked:
            slate_mismatch.append(
                {
                    "query_id": qid,
                    "cue_top10": sorted(slate_idx),
                    "reranked": sorted(actually_reranked),
                }
            )
        if i1 not in slate_idx or i2 not in slate_idx:
            raise SystemExit(f"REFUSING. {qid}: head pair is not inside its own slate.")
        p.update(slate_unique_fields(pool, texts, idf, default_idf, slate_idx, i1, i2))

    print(f"slate: depth {SLATE_DEPTH}, cue-only top-10 == the actually-reranked set on "
          f"{n - len(slate_mismatch)}/{n} queries")
    if slate_mismatch:
        raise SystemExit(
            "REFUSING. The cue-only top-10 is not the set the cross-encoder scored on "
            f"{len(slate_mismatch)} queries, e.g. {slate_mismatch[0]}. The slate this feature is "
            "computed over would not be the slate the product formed."
        )
    sizes = sorted({p["slate_size"] for p in pairs})
    print(f"       slate sizes present: {sizes}")

    counts = label_counts(pairs)
    print(f"\npopulation: {n} pairs -- POSITIVE {counts[POSITIVE]} (flip fixes), "
          f"NEGATIVE {counts[NEGATIVE]} (flip breaks), AMBIGUOUS {counts[AMBIGUOUS]}")
    print(f"            a reordering rule must be right on > "
          f"{counts[NEGATIVE] / (counts[POSITIVE] + counts[NEGATIVE]):.1%} of the decisive pairs "
          "it touches or it loses ground")

    # -- register with the head-probe harness WITHOUT editing it ----------------------------------
    HP.FEATURES[PRIMARY] = (
        "PRIMARY: (slate-unique IDF mass / total IDF mass), rank2 minus rank1; "
        "comparison set = the other 9 slate members, head pair included",
        f_primary,
    )
    HP.FEATURES[SECONDARY] = (
        "SECONDARY: same fraction, head pair EXCLUDED from each other's comparison set",
        f_secondary,
    )
    HP.FEATURES[PRIMARY_RAW] = (
        "PRIMARY, UNNORMALISED: slate-unique IDF mass in nats, rank2 minus rank1",
        f_primary_raw,
    )
    HP.FEATURES[SECONDARY_RAW] = (
        "SECONDARY, UNNORMALISED: head pair excluded, unique IDF mass, rank2 minus rank1",
        f_secondary_raw,
    )

    above = [p for p in pairs if p["rerank_gap"] is not None and abs(p["rerank_gap"]) > BAND]
    below = [p for p in pairs if p["rerank_gap"] is not None and abs(p["rerank_gap"]) <= BAND]
    no_gap = [p for p in pairs if p["rerank_gap"] is None]
    print(f"\nband split at |rerank_gap| > {BAND}: above {len(above)}, below {len(below)}, "
          f"no gap {len(no_gap)}")
    print(f"  above the band: {label_counts(above)}")
    print(f"  below the band: {label_counts(below)}")

    results = {}
    for name, fn in (
        (PRIMARY, f_primary),
        (SECONDARY, f_secondary),
        (PRIMARY_RAW, f_primary_raw),
        (SECONDARY_RAW, f_secondary_raw),
    ):
        print("\n" + "=" * 100)
        print(f"{name} -- {HP.FEATURES[name][0]}")
        print("=" * 100)
        res = HP.evaluate(pairs, name, fn, n)

        print("\n  full threshold curve (tau selected on fit is a DESIGN SIGNAL, never a result):")
        HP.print_curve(name, res["forward"])

        print("\n  THE PARAMETER-FREE OPERATING POINT, tau = 0:")
        ops = {}
        for strict in (True, False):
            key = "strict_gt_0" if strict else "ge_0"
            ops[key] = operating_point(pairs, fn, n, strict)
            print_op(f"tau=0 {'strict >0' if strict else '>=0     '} ALL", ops[key], counts)

        print("\n  THE DECISIVE TEST -- above |rerank_gap| > 0.084, where the scores are NOT "
              "effectively identical:")
        for strict in (True, False):
            key = ("strict_gt_0" if strict else "ge_0")
            ops["above_" + key] = operating_point(pairs, fn, n, strict, subset=above)
            ops["below_" + key] = operating_point(pairs, fn, n, strict, subset=below)
            print_op(f"tau=0 {'strict >0' if strict else '>=0     '} ABOVE band",
                     ops["above_" + key], label_counts(above))
            print_op(f"tau=0 {'strict >0' if strict else '>=0     '} below band",
                     ops["below_" + key], label_counts(below))

        print("\n  SIGN-INVERTED NEGATIVE CONTROL:")
        inv_fn = (lambda f: (lambda p: (None if f(p) is None else -f(p))))(fn)
        for strict in (True, False):
            key = "inverted_strict_gt_0" if strict else "inverted_ge_0"
            ops[key] = operating_point(pairs, inv_fn, n, strict)
            print_op(f"INVERTED tau=0 {'strict' if strict else '>=0   '} ALL", ops[key], counts)
        ops["inverted_above_strict_gt_0"] = operating_point(pairs, inv_fn, n, True, subset=above)
        print_op("INVERTED tau=0 strict ABOVE band", ops["inverted_above_strict_gt_0"],
                 label_counts(above))
        b = res["forward"]["best"]
        ib = res["negative_control_sign_inverted"]["best"]
        m = res["negative_control_at_matched_budget"]
        print(f"    fit-selected BEST      net {b['net_cases']:+d} ({b['flips_gained']} gained, "
              f"{b['flips_lost']} lost) at tau {b['tau']:.4f}, {b['n_flipped']} flips")
        print(f"    INVERTED best          net {ib['net_cases']:+d} at {ib['n_flipped']} flips")
        print(f"    INVERTED at the SAME {b['n_flipped']}-flip budget: net {m['net_cases']:+d} "
              f"({m['flips_gained']} gained, {m['flips_lost']} lost)")
        print(f"    separation from control {b['net_cases'] - ib['net_cases']:+d}")

        print("\n  DOES IT SEPARATE THE 26 POSITIVE FROM THE 110 NEGATIVE AT ALL?")
        sep = separation(pairs, fn, name)
        for lab in ("POSITIVE", "NEGATIVE", "AMBIGUOUS"):
            s = sep[lab]
            print(f"    {lab:10s} n {s['n']:>3d}  mean {s['mean']:>+10.5f}  median "
                  f"{s['median']:>+10.5f}  sd {s['sd']}  frac>0 {s['frac_gt_0']}")
        print(f"    Mann-Whitney U p {sep['mannwhitney_p']}  AUC(pos>neg) {sep.get('auc_pos_over_neg')}"
              f"  Cohen's d {sep.get('cohens_d')}")

        results[name] = {
            "description": HP.FEATURES[name][0],
            "tau0": ops,
            "harness": res,
            "separation": sep,
        }

    # -- is this the dead feature in new clothes? --------------------------------------------------
    print("\n" + "=" * 100)
    print("CORRELATION WITH THE DEAD `non_query_mass` FEATURE (both oriented higher = flip)")
    print("=" * 100)
    corrs = {}
    dead = HP.FEATURES["non_query_mass"][1]
    for name, fn in (
        (PRIMARY, f_primary),
        (SECONDARY, f_secondary),
        (PRIMARY_RAW, f_primary_raw),
        (SECONDARY_RAW, f_secondary_raw),
    ):
        xs, ys = [], []
        for p in pairs:
            a, b_ = fn(p), dead(p)
            if a is None or b_ is None:
                continue
            xs.append(float(a))
            ys.append(float(b_))
        r, rp = pearsonr(xs, ys)
        rho, sp = spearmanr(xs, ys)
        corrs[name] = {
            "n": len(xs),
            "pearson_r": round(float(r), 4),
            "pearson_p": round(float(rp), 8),
            "spearman_rho": round(float(rho), 4),
            "spearman_p": round(float(sp), 8),
        }
        print(f"  {name:38s} n {len(xs):>3d}  pearson r {r:>+7.4f} (p {rp:.2e})  "
              f"spearman rho {rho:>+7.4f} (p {sp:.2e})")
    print("\n  The registered prediction was r > 0.5. If it holds, this is the dead "
          "IDF-non-query-mass\n  feature in new clothes and that is the finding.")

    # -- what the shipped system already does at tau=0, for scale ----------------------------------
    print("\n" + "=" * 100)
    print("SCALE: what blind swapping scores, for comparison")
    print("=" * 100)
    blind_all = {"gained": counts[POSITIVE], "lost": counts[NEGATIVE],
                 "net": counts[POSITIVE] - counts[NEGATIVE]}
    ab = label_counts(above)
    bl = label_counts(below)
    print(f"  blind swap, ALL pairs        gained {blind_all['gained']}  lost {blind_all['lost']}  "
          f"net {blind_all['net']:+d}")
    print(f"  blind swap, BELOW the band   gained {bl[POSITIVE]}  lost {bl[NEGATIVE]}  "
          f"net {bl[POSITIVE] - bl[NEGATIVE]:+d}")
    print(f"  blind swap, ABOVE the band   gained {ab[POSITIVE]}  lost {ab[NEGATIVE]}  "
          f"net {ab[POSITIVE] - ab[NEGATIVE]:+d}")

    artifact = {
        "_what": "H-C slate-unique IDF mass: the IDF mass a head candidate carries that NO OTHER "
                 "depth-10 slate member carries, as a fraction of its total mass, scored on FLIPS.",
        "_split": "fit",
        "_config": "ms-marco-MiniLM-L-2-v2-ft-session-j, depth 10 (shipped)",
        "_instrument_only": "Nothing ships. No artifact minted, no gate refit, no held-out read.",
        "_registered_prediction": {
            "net_cases_at_tau_0_on_fit": "+2 to +6",
            "above_0_084": "0 or negative net",
            "correlation_with_non_query_mass_norm_gap": "> 0.5; if so this is the dead feature "
                                                        "in new clothes",
        },
        "gate": {"published_fit_r1": HP.CONTROL_R1, "reconstructed_fit_r1": r1,
                 "queries": len(pools)},
        "idf": {"content_words": len(idf), "fit_candidate_turns": n_docs, "split": "fit only"},
        "slate": {"depth": SLATE_DEPTH, "cue_top10_equals_reranked_set_on": n - len(slate_mismatch),
                  "of": n, "sizes_present": sizes},
        "population": {"pairs": n, **{k: v for k, v in counts.items()},
                       "above_band": label_counts(above), "below_band": label_counts(below),
                       "band": BAND},
        "blind_swap_reference": {"all": blind_all,
                                 "above_band": {"gained": ab[POSITIVE], "lost": ab[NEGATIVE],
                                                "net": ab[POSITIVE] - ab[NEGATIVE]},
                                 "below_band": {"gained": bl[POSITIVE], "lost": bl[NEGATIVE],
                                                "net": bl[POSITIVE] - bl[NEGATIVE]}},
        "features": results,
        "correlation_with_dead_non_query_mass": corrs,
        "pairs": [
            {
                k: p[k]
                for k in (
                    "query_id", "category", "label", "rerank_gap", "non_query_mass_norm_gap",
                    "slate_size", "r1_total_mass", "r2_total_mass",
                    "r1_unique_mass_primary", "r2_unique_mass_primary",
                    "r1_unique_frac_primary", "r2_unique_frac_primary",
                    "r1_unique_mass_secondary", "r2_unique_mass_secondary",
                    "r1_unique_frac_secondary", "r2_unique_frac_secondary",
                    "slate_unique_frac_primary_gap", "slate_unique_frac_secondary_gap",
                    "slate_unique_mass_primary_gap", "slate_unique_mass_secondary_gap",
                )
            }
            for p in pairs
        ],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
