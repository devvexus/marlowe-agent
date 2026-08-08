"""Session J, Part 1 — arm 7, explicit length normalization of the rerank score.

**No training, no new model, no change to the slate.** A normalization term applied to the rerank
logit before the argsort, measured on the models Session I already pinned.

Promoted from deferred to the named next lever by ADR-015: the shipped `MAX_SEQ_LEN = 256` cap is
an *accidental* length normalizer. It truncates gold in 7.86% of fit cases, and raising it to 512
costs **-0.0917 R@1** because the cap was suppressing a length preference rather than causing one —
the rank-1 distractor on failures goes from 50.0% assistant-authored at 157 median word pieces to
74.3% at 487. Normalizing explicitly is the way to stop the sequence length being load-bearing.

## Score once, normalize many

Every arm here is a pure function of `(logit, wordpieces, role)` per slate candidate, so the
cross-encoder runs **once per (model, precision, sequence length, split)** and every arm, every
strength, and every contrast is post-processing over that cache. The whole grid costs five forward
passes. The cache is written to disk and reused, so re-running a sweep re-scores nothing.

## The arms

  * **7a control** — the raw logit. Ordering identical to the shipped stage.
  * **7b subtractive** — `s - lambda * f_hat(log wordpieces)`.
  * **7c divisive** — `sigmoid(s) / wordpieces^alpha`. Defined on the **probability scale**
    deliberately: a cross-encoder logit is signed, and dividing a signed score by a positive length
    factor pushes negatives the wrong way, which would be a different transform for the half of the
    slate that scores below zero rather than a length correction.
  * **7d role only** — `s - beta * 1[assistant]`.
  * **7e both** — 7b and 7d together, which is the decomposition that says whether speaker role
    adds anything beyond length. 87.7% of gold is user-authored and the two are correlated but not
    identical, so this is the only arm that can separate them.

## What is fitted, and what is swept

`f_hat` and `beta` are estimated **without reference to R@1** — `f_hat` is the binned conditional
mean of the logit on log word pieces over all fit-split slate candidates, and `beta` is the
difference in mean logit between assistant-authored and user-authored candidates. Only the
**strength** is swept against the metric, over the five-point grid the pre-registration fixes.

That split is the point. Estimating the length effect from the scores themselves keeps the
correction from being reverse-engineered out of the ranking it is judged on; the one scalar that
does see the metric has five possible values and its whole curve is reported, so the selection is
visible rather than absorbed into a single best number.

## Precision

**f32 for every cell that varies sequence length** (ADR-015): padding alone flips top-1 in 15% of
cases on the shipped int8 graph, and all eight f32 graphs are invariant to 0.000000. The int8
shipped configuration is carried as a control at `[1, 256]` only, where its shape binding holds.

    python tools/session_j_arm7.py --split fit --models ms-marco-MiniLM-L-2-v2 --seq 256 512
    python tools/session_j_arm7.py --split fit --models ms-marco-MiniLM-L-6-v2 --seq 256 512
    python tools/session_j_arm7.py --split fit --models ms-marco-MiniLM-L-2-v2-int8 --seq 256
"""

from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import time

import numpy as np

from reach_pools import REPO, Pool, turn_texts
from reach_rerank_fit import PREREG_PATH as SESSION_H_PREREG, top1_is_gold
from session_h_pools import fidelity_gate, load_split_pools
from session_i_rerankers import SHIPPED_INT8, ModelRefused, load as load_pinned
import session_j_models


def load(name: str):
    """Session I's pinned models, falling back to models this session trained and pinned.

    The fallback is a SEPARATE manifest, not an entry added to Session I's. Editing Session I's
    manifest so a Session J file passes its own digest check would make that manifest a record of
    nothing. Both loaders enforce the same rules; see `session_j_models`.
    """
    try:
        return load_pinned(name)
    except ModelRefused:
        return session_j_models.load_finetuned(name)
from session_i_seqlen import (
    MIN_DISCORDANT_FOR_ALPHA,
    mcnemar_exact,
    shipped_slate,
    turn_roles,
)

OUT_DIR = REPO / "runs" / "session-j"

# Fixed by runs/session-j/PREREGISTRATION.json. Not a tuning knob: read from the file rather than
# restated, so a grid edited here without editing the registration cannot go unnoticed.
PREREG_PATH = OUT_DIR / "PREREGISTRATION.json"

LENGTH_BINS = 20        # equal-count bins for the conditional mean. ~115 candidates per bin at
                        # 2290 slate rows, which is enough for a stable mean and coarse enough
                        # that f_hat cannot chase individual candidates.


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


# ------------------------------------------------------------------------------------------------
# Phase A -- score once per (model, precision, seq, split), and cache it.
# ------------------------------------------------------------------------------------------------


def cache_path(split: str, model: str, seq: int) -> "object":
    precision = "int8" if model.endswith("-int8") else "f32"
    stem = model.replace("ms-marco-MiniLM-", "").replace("-int8", "")
    # Every varied parameter is in the name. Session I's seqlen tool keyed on split alone and
    # silently overwrote a prior run's results with a different model's.
    return OUT_DIR / f"rerank-scores-{split}-{stem}-{precision}-seq{seq}.json"


def score_slates(ce, pools: dict[str, Pool], texts, roles, seq: int, gap_ms: int,
                 prune_n: int, label: str) -> dict:
    """One forward pass per slate candidate. Everything an arm needs, and nothing else."""
    rows: dict[str, dict] = {}
    lat: list[float] = []
    for n_done, pool in enumerate(pools.values(), 1):
        per_turn = texts.get(pool.query_id, {})
        per_role = roles.get(pool.query_id, {})
        slate = shipped_slate(pool, gap_ms, prune_n)
        scores, lengths, speakers, golds, turn_ids = [], [], [], [], []
        for i in slate:
            tid = pool.candidates[int(i)].turn_id or ""
            text = per_turn.get(tid, "")
            t0 = time.perf_counter()
            scores.append(ce.score(pool.question, text, seq))
            lat.append((time.perf_counter() - t0) * 1000.0)
            # The TRUE, untruncated word-piece count. The normalization must read the candidate's
            # real length, not the capped length it happened to be scored at -- the whole defect
            # is that the cap is silently doing this job.
            lengths.append(ce.wordpieces(text))
            speakers.append(per_role.get(tid, "?"))
            golds.append(bool(pool.gold[int(i)]))
            turn_ids.append(tid)
        rows[pool.query_id] = {
            "category": pool.category,
            "slate": [int(i) for i in slate],
            "scores": scores,
            "wordpieces": lengths,
            "roles": speakers,
            "gold": golds,
            "turn_ids": turn_ids,
            "gold_in_slate": bool(pool.gold[slate].any()),
        }
        if n_done % 100 == 0:
            print(f"    {label} seq {seq}: {n_done}/{len(pools)}")
    lat.sort()
    return {
        "rows": rows,
        "ms_per_pair": {
            "median": round(statistics.median(lat), 3),
            "p95": round(lat[max(0, int(round(0.95 * len(lat))) - 1)], 3),
            "pairs": len(lat),
        },
    }


# ------------------------------------------------------------------------------------------------
# Phase B -- the arms, as post-processing over the cache.
# ------------------------------------------------------------------------------------------------


def fit_length_effect(all_scores: np.ndarray, all_lengths: np.ndarray) -> dict:
    """The conditional mean of the logit on log word pieces. **Never sees R@1.**

    Equal-count bins, then linear interpolation between bin centres, flat outside the range. The
    OLS slope is carried alongside as a diagnostic -- if the conditional mean is close to linear,
    the two agree and the estimate is not an artifact of the binning.
    """
    logl = np.log(np.maximum(all_lengths, 1))
    order = np.argsort(logl, kind="stable")
    binned = np.minimum((np.arange(len(order)) * LENGTH_BINS) // len(order), LENGTH_BINS - 1)
    centres, means = [], []
    for b in range(LENGTH_BINS):
        mask = binned == b
        if not mask.any():
            continue
        idx = order[mask]
        centres.append(float(np.mean(logl[idx])))
        means.append(float(np.mean(all_scores[idx])))
    slope, intercept = np.polyfit(logl, all_scores, 1)
    return {
        "centres": centres,
        "means": means,
        "ols_slope_per_log_wordpiece": float(slope),
        "ols_intercept": float(intercept),
        "spearman_score_vs_length": float(
            np.corrcoef(np.argsort(np.argsort(logl)), np.argsort(np.argsort(all_scores)))[0, 1]
        ),
    }


def f_hat(effect: dict, lengths: np.ndarray) -> np.ndarray:
    return np.interp(np.log(np.maximum(lengths, 1)), effect["centres"], effect["means"])


def fit_role_effect(all_scores: np.ndarray, all_roles: np.ndarray) -> dict:
    """beta = mean logit on assistant-authored candidates minus mean on user-authored. No R@1."""
    a = all_scores[all_roles == "assistant"]
    u = all_scores[all_roles == "user"]
    return {
        "assistant_mean": float(a.mean()) if a.size else 0.0,
        "user_mean": float(u.mean()) if u.size else 0.0,
        "beta": float(a.mean() - u.mean()) if a.size and u.size else 0.0,
        "assistant_share_of_slate": float((all_roles == "assistant").mean()),
    }


def normalized(arm: str, strength: float, s: np.ndarray, length: np.ndarray, role: np.ndarray,
               effect: dict, role_effect: dict) -> np.ndarray:
    if arm == "7a_control":
        return s
    if arm == "7b_subtractive":
        return s - strength * f_hat(effect, length)
    if arm == "7c_divisive":
        return sigmoid(s) / np.power(np.maximum(length, 1), strength)
    if arm == "7d_role_only":
        return s - strength * role_effect["beta"] * (role == "assistant")
    if arm == "7e_both":
        return (s - strength * f_hat(effect, length)
                - strength * role_effect["beta"] * (role == "assistant"))
    if arm == "7f_signed_log_POSTHOC":
        return s - strength * np.log(np.maximum(length, 1))
    raise ValueError(arm)


# The five REGISTERED arms. The registered contrast is selected from these and only these.
ARMS = ["7a_control", "7b_subtractive", "7c_divisive", "7d_role_only", "7e_both"]

# **POST-HOC. Not registered, and deliberately held outside `ARMS`.** `runs/session-j/
# ADDENDUM-post-hoc-length-form.json` records how it was arrived at and pins its held-out
# prediction. It is 7b's functional form with a positive CONSTANT slope in place of the fitted
# conditional mean, whose slope came out negative and therefore corrected in the wrong direction.
#
# It is reported beside the registered arms and never inside the registered contrast: letting a
# form discovered on the fit split compete for a pre-registered band is precisely what the band
# exists to prevent.
POSTHOC_ARMS = ["7f_signed_log_POSTHOC"]
POSTHOC_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]


def evaluate(cache: dict, pools: dict[str, Pool], arm: str, strength: float,
             effect: dict, role_effect: dict) -> dict:
    per_case = []
    for qid, row in cache["rows"].items():
        pool = pools[qid]
        slate = np.array(row["slate"], dtype=int)
        s = np.array(row["scores"], dtype=float)
        length = np.array(row["wordpieces"], dtype=float)
        role = np.array(row["roles"])
        key = normalized(arm, strength, s, length, role, effect, role_effect)
        order = np.argsort(-key, kind="stable")
        top = int(order[0])
        per_case.append({
            "query_id": qid,
            "category": row["category"],
            "gold_in_slate": row["gold_in_slate"],
            "top1_is_gold": top1_is_gold(pool, slate, order),
            "top1_turn_id": row["turn_ids"][top],
            "rank1_role": row["roles"][top],
            "rank1_wordpieces": row["wordpieces"][top],
        })
    n = len(per_case)
    hits = sum(r["top1_is_gold"] for r in per_case)
    present = sum(r["gold_in_slate"] for r in per_case)
    fails = [r for r in per_case if not r["top1_is_gold"]]
    wl = [r["rank1_wordpieces"] for r in fails]
    return {
        "arm": arm,
        "strength": strength,
        "cases": n,
        "r_at_1": round(hits / n, 4),
        "input_recall": round(present / n, 4),
        "conditional_accuracy": round(hits / present, 4) if present else None,
        "rank1_on_failures": {
            "n": len(fails),
            "assistant_share": round(
                sum(1 for r in fails if r["rank1_role"] == "assistant") / len(fails), 4)
            if fails else None,
            "wordpieces_median": float(np.median(wl)) if wl else None,
        },
        "_per_case": per_case,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["fit", "heldout"], default="fit")
    ap.add_argument("--models", nargs="+", default=["ms-marco-MiniLM-L-2-v2"])
    ap.add_argument("--seq", nargs="+", type=int, default=[256])
    args = ap.parse_args()

    prereg = json.loads(io.open(PREREG_PATH, encoding="utf-8").read())
    grid = prereg["part_1_length_normalization"]["lambda_grid"]
    print(f"strength grid, from the pre-registration: {grid}")

    h_prereg = json.loads(io.open(SESSION_H_PREREG, encoding="utf-8").read())
    gap_ms = h_prereg["frozen_parameters"]["session_gap_ms"]["value"]
    prune_n = h_prereg["frozen_parameters"]["prune_N"]["value"]

    fit, heldout, _ = load_split_pools()
    ok, _gate = fidelity_gate(heldout)
    if not ok:
        print("Reconstruction licensing gate FAILED.")
        return 1
    pools = fit if args.split == "fit" else heldout
    print(f"Licensing gate PASSED. {args.split} split: {len(pools)} pools.\n")

    texts, roles = turn_texts(), turn_roles()

    for model in args.models:
        precision = "int8" if model.endswith("-int8") else "f32"
        for seq in args.seq:
            if precision == "int8" and seq != 256:
                # ADR-015: padding alone flips top-1 in 15% of cases on this graph. A cell that
                # varies sequence length on int8 measures two different scorers.
                print(f"REFUSED: {model} at seq {seq}. int8 is shape-bound; f32 only when the "
                      "sequence length varies (ADR-015).")
                return 1

            path = cache_path(args.split, model, seq)
            if path.exists():
                cache = json.loads(io.open(path, encoding="utf-8").read())
                print(f"{model} @{seq} ({precision}): cache HIT, {path.name}")
            else:
                ce = load(model)
                print(f"{model} @{seq} ({precision}, {ce.arch}, ~{ce.params_m}M, "
                      f"digest {ce.digest[:16]}...)")
                if seq > ce.max_seq_supported:
                    print(f"  seq {seq} exceeds this model's positional limit; SKIPPED")
                    continue
                cache = score_slates(ce, pools, texts, roles, seq, gap_ms, prune_n, model)
                cache["model"] = model
                cache["precision"] = precision
                cache["seq_len"] = seq
                cache["split"] = args.split
                cache["digest"] = ce.digest
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
                print(f"  scored {cache['ms_per_pair']['pairs']} pairs at "
                      f"{cache['ms_per_pair']['median']:.1f} ms/pair -> {path.name}")

            sweep(cache, pools, grid, args.split, model, precision, seq)
    return 0


def sweep(cache: dict, pools: dict[str, Pool], grid: list[float], split: str,
          model: str, precision: str, seq: int) -> None:
    all_scores = np.array([s for r in cache["rows"].values() for s in r["scores"]])
    all_lengths = np.array([w for r in cache["rows"].values() for w in r["wordpieces"]])
    all_roles = np.array([x for r in cache["rows"].values() for x in r["roles"]])

    effect = fit_length_effect(all_scores, all_lengths)
    role_effect = fit_role_effect(all_scores, all_roles)

    print(f"\n  the length effect, estimated WITHOUT reference to R@1:")
    print(f"    OLS slope {effect['ols_slope_per_log_wordpiece']:+.4f} logits per log word piece"
          f"   (Spearman score vs length {effect['spearman_score_vs_length']:+.4f})")
    print(f"    role beta {role_effect['beta']:+.4f} logits"
          f"   (assistant {role_effect['assistant_mean']:+.3f} vs user {role_effect['user_mean']:+.3f},"
          f" {role_effect['assistant_share_of_slate']:.1%} of the slate)")

    control = evaluate(cache, pools, "7a_control", 0.0, effect, role_effect)
    results = {"7a_control@0.0": control}
    print(f"\n  {'arm':>16} {'strength':>9} {'R@1':>8} {'cond.acc':>9} {'delta':>8} "
          f"{'changed':>8} {'assist%':>8} {'wp med':>7}")
    print(f"  {'7a_control':>16} {'--':>9} {control['r_at_1']:>8.4f} "
          f"{control['conditional_accuracy']:>9.4f} {'--':>8} {'--':>8} "
          f"{control['rank1_on_failures']['assistant_share']:>8.1%} "
          f"{control['rank1_on_failures']['wordpieces_median']:>7.0f}")

    ctrl_top = {r["query_id"]: r["top1_turn_id"] for r in control["_per_case"]}
    for arm in ARMS[1:]:
        for strength in grid:
            if strength == 0.0:
                continue          # identical to the control by construction
            res = evaluate(cache, pools, arm, strength, effect, role_effect)
            changed = sum(1 for r in res["_per_case"] if ctrl_top[r["query_id"]] != r["top1_turn_id"])
            res["adr_010_top1_changed_vs_control"] = changed
            results[f"{arm}@{strength}"] = res
            print(f"  {arm:>16} {strength:>9.2f} {res['r_at_1']:>8.4f} "
                  f"{res['conditional_accuracy']:>9.4f} "
                  f"{res['r_at_1'] - control['r_at_1']:>+8.4f} {changed:>8} "
                  f"{res['rank1_on_failures']['assistant_share']:>8.1%} "
                  f"{res['rank1_on_failures']['wordpieces_median']:>7.0f}")

    # ---- the post-hoc form, reported beside the registered arms and NEVER inside the contrast --
    addendum = json.loads(io.open(OUT_DIR / "ADDENDUM-post-hoc-length-form.json",
                                  encoding="utf-8").read())
    pinned_c = addendum["what_is_fixed_here"]["c"]
    posthoc: dict[str, dict] = {}
    print(f"\n  POST-HOC form (not registered; addendum pins c = {pinned_c}) — s - c*log(wordpieces)")
    print(f"  {'c':>16} {'':>9} {'R@1':>8} {'cond.acc':>9} {'delta':>8} "
          f"{'changed':>8} {'assist%':>8} {'wp med':>7}")
    for arm in POSTHOC_ARMS:
        for strength in POSTHOC_GRID:
            res = evaluate(cache, pools, arm, strength, effect, role_effect)
            changed = sum(1 for r in res["_per_case"] if ctrl_top[r["query_id"]] != r["top1_turn_id"])
            res["adr_010_top1_changed_vs_control"] = changed
            res["is_pinned_value"] = bool(strength == pinned_c)
            posthoc[f"{arm}@{strength}"] = res
            mark = "  <- PINNED" if strength == pinned_c else ""
            print(f"  {strength:>16.2f} {'':>9} {res['r_at_1']:>8.4f} "
                  f"{res['conditional_accuracy']:>9.4f} "
                  f"{res['r_at_1'] - control['r_at_1']:>+8.4f} {changed:>8} "
                  f"{res['rank1_on_failures']['assistant_share']:>8.1%} "
                  f"{res['rank1_on_failures']['wordpieces_median']:>7.0f}{mark}")

    # ---- the registered contrast: best REGISTERED arm vs control, paired, power stated ---------
    best_key = max((k for k in results if not k.startswith("7a")),
                   key=lambda k: results[k]["r_at_1"])
    best = results[best_key]
    ca = {r["query_id"]: r["top1_is_gold"] for r in control["_per_case"]}
    cb = {r["query_id"]: r["top1_is_gold"] for r in best["_per_case"]}
    shared = sorted(set(ca) & set(cb))
    gained = sum(1 for q in shared if cb[q] and not ca[q])
    lost = sum(1 for q in shared if ca[q] and not cb[q])
    n_disc = gained + lost
    p, p_min = mcnemar_exact(lost, gained)
    reach_ok = best.get("adr_010_top1_changed_vs_control", 0) >= MIN_DISCORDANT_FOR_ALPHA

    contrast = {
        "best_arm": best_key,
        "delta_r_at_1": round(best["r_at_1"] - control["r_at_1"], 4),
        "delta_conditional_accuracy": round(
            best["conditional_accuracy"] - control["conditional_accuracy"], 4),
        "gained": gained, "lost": lost, "discordant": n_disc,
        "mcnemar_exact_p": round(p, 4),
        "smallest_attainable_p_at_this_n": round(p_min, 4),
        "alpha_005_attainable": bool(n_disc >= MIN_DISCORDANT_FOR_ALPHA),
        "adr_010_top1_changed": best.get("adr_010_top1_changed_vs_control", 0),
        "adr_010_reach_pass": bool(reach_ok),
        "_selection_note": (
            f"the best arm is selected over {len(results) - 1} (arm, strength) cells on this same "
            "split, so this delta is optimistically biased. The full grid is printed above and "
            "stored below so the selection is visible; the honest read is held-out, taken once."
        ),
    }

    print(f"\n  REGISTERED CONTRAST — best arm vs 7a control, paired (ADR-014)")
    print(f"    {best_key}   delta R@1 {contrast['delta_r_at_1']:+.4f}   "
          f"delta cond.acc {contrast['delta_conditional_accuracy']:+.4f}")
    print(f"    discordant {n_disc} (gained {gained}, lost {lost})   exact p {p:.4f}")
    if not contrast["alpha_005_attainable"]:
        print(f"    ALPHA 0.05 UNATTAINABLE at n={n_disc}: smallest possible p here is {p_min:.4f}.")
        print(f"    The p-value is NOT evidence of absence. The delta carries the verdict.")
    if not reach_ok:
        print(f"    ADR-010 REACH FAILED: top-1 changed on only "
              f"{contrast['adr_010_top1_changed']} queries (floor {MIN_DISCORDANT_FOR_ALPHA}).")

    stem = model.replace("ms-marco-MiniLM-", "").replace("-int8", "")
    out = OUT_DIR / f"arm7-{split}-{stem}-{precision}-seq{seq}.json"
    out.write_text(json.dumps({
        "_what": "Session J Part 1, arm 7 — explicit length normalization of the rerank score.",
        "split": split, "model": model, "precision": precision, "seq_len": seq,
        "digest": cache.get("digest"),
        "ms_per_pair": cache["ms_per_pair"],
        "strength_grid": grid,
        "length_effect": effect,
        "role_effect": role_effect,
        "adr_014_floor": {"alpha": 0.05, "min_discordant_n": MIN_DISCORDANT_FOR_ALPHA},
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "_per_case"}
                    for k, v in results.items()},
        "registered_contrast": contrast,
        "posthoc_form": {
            "_what": "s - c*log(wordpieces). NOT REGISTERED; see ADDENDUM-post-hoc-length-form.json.",
            "_excluded_from": "the registered contrast above, deliberately",
            "pinned_c": pinned_c,
            "results": {k: {kk: vv for kk, vv in v.items() if kk != "_per_case"}
                        for k, v in posthoc.items()},
        },
        "_per_case": {k: v["_per_case"] for k, v in {**results, **posthoc}.items()},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"  WROTE {out.name}\n")


if __name__ == "__main__":
    raise SystemExit(main())
