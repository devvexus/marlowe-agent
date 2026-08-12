"""H-B: ATTRIBUTION CONCENTRATION by LEAVE-ONE-SENTENCE-OUT ABLATION.

    python tools/ablation_attribution.py

**Measurement only. Nothing ships, nothing is trained, no held-out read is spent.**

## The mechanism

For each member of a head pair (rank 1, rank 2 under the shipped key):

    S_full            = ce(question, whole turn)                     <- must reproduce rerank_score
    S_-i              = ce(question, whole turn MINUS sentence i)
    drop_i            = S_full - S_-i
    concentration     = max_i(drop_i) / sum_i |drop_i|               <- parameter-free, in [-1, 1]

**Flip the pair when rank 2's concentration exceeds rank 1's. tau = 0. No knob.**

Undefined when the turn has fewer than 2 sentences or when sum_i |drop_i| == 0. An undefined pair
is NEVER flipped and the count is reported.

## Why this is not sentence MaxP (11 gained / 15 lost, dead)

MaxP scores each sentence **in isolation**, which is why it surfaced the distractor's
question-echoing span at full strength -- a question-echoing sentence alone is a maximally
query-matching object. Ablation never scores a span alone: it measures **how much the turn's own
score depends on that span in context**. §4's unifying fact predicts gold's score rests on one
clause (concentrated) while the distractor is uniformly on-topic (diffuse). That is a different
quantity from "which span scores best in isolation".

## REGISTERED PREDICTION, written before the run

  * +3 to +7 net cases at tau = 0 on fit.
  * It FAILS the above-0.084 test -- <= 0 net above the band. Same family as context decay
    (fit +0.0305 -> held-out -0.0087) measured by ablation instead of by windowing; every member
    of that family has fired only inside the near-tie band.
  * The unnormalised secondary (raw max drop, rank2 - rank1) will be WORSE than the ratio, because
    raw drop scales with sentence count and length is dead.

## Reuse, not re-implementation

  * the cross-encoder loader          `session_i_rerankers.load` (digest-pinned, ORT_ENABLE_BASIC,
                                       1 thread, batch 1, provider asserted after construction)
  * the sentence splitter             `sentence_maxp.sentences`
  * the head pairs and the R@1 gate   `head_probe.build`
  * the flip-scoring harness          `head_probe.{score_feature,evaluate,print_curve}` -- the
                                       feature is registered by MUTATING `head_probe.FEATURES` at
                                       runtime; that file is not modified.

## The reproduction check, before any drop is believed

`S_full` computed through this path must reproduce the `rerank_score` already recorded in
`head-probe.json` for the same candidate. If it does not, this is a different scorer and the run
refuses. A drop is a difference of two scores, so a systematic offset would cancel and the check
would still be the only thing standing between "measuring the shipped model" and "measuring
something else".
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import head_probe as HP  # noqa: E402
import session_i_rerankers as R  # noqa: E402
from sentence_maxp import sentences  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "ablation-attribution.json"
NEAR_TIE = 0.084
MAX_SEQ = 256
REPRO_TOL = 1e-3  # the recorded logit comes from the Rust f32 stage; this is a cross-runtime check

POSITIVE, NEGATIVE, AMBIGUOUS = HP.POSITIVE, HP.NEGATIVE, HP.AMBIGUOUS


# -- the feature ---------------------------------------------------------------------------------


def ablate(ce, question: str, text: str) -> dict:
    """Leave-one-sentence-out attribution profile for one candidate."""
    s_full = ce.score(question, text, MAX_SEQ)
    ss = sentences(text)
    rec = {"n_sentences": len(ss), "s_full": s_full, "drops": None,
           "concentration": None, "max_drop": None, "sum_abs_drop": None, "forwards": 1}
    if len(ss) < 2:
        return rec
    drops = []
    for i in range(len(ss)):
        held = " ".join(ss[:i] + ss[i + 1:])
        drops.append(s_full - ce.score(question, held, MAX_SEQ))
    rec["forwards"] += len(ss)
    denom = float(np.sum(np.abs(drops)))
    rec["drops"] = [round(float(d), 6) for d in drops]
    rec["max_drop"] = float(np.max(drops))
    rec["sum_abs_drop"] = denom
    rec["concentration"] = (float(np.max(drops)) / denom) if denom > 0 else None
    return rec


def f_concentration(p):
    """PRIMARY. rank 2's attribution is MORE concentrated than rank 1's -> flip."""
    a, b = p["_abl_r1"]["concentration"], p["_abl_r2"]["concentration"]
    return None if (a is None or b is None) else (b - a)


def f_max_drop(p):
    """SECONDARY, unnormalised. rank 2's single largest drop exceeds rank 1's -> flip."""
    a, b = p["_abl_r1"]["max_drop"], p["_abl_r2"]["max_drop"]
    return None if (a is None or b is None) else (b - a)


# -- the tau = 0 read, computed directly and cross-checked against the harness curve --------------


def table(pairs, fn, strict: bool, tau: float = 0.0) -> dict:
    """FLIPS GAINED / LOST at a fixed tau, with the above-0.084 breakdown, computed here.

    `strict` selects `value > tau` (the hypothesis as registered: "rank 2's concentration EXCEEDS
    rank 1's") versus `value >= tau` (what `head_probe.score_feature`'s curve rows mean). Both are
    reported because a float tie at exactly 0 would otherwise be silently assigned.
    """
    g = l = a = und = 0
    ag = al = aa = 0          # above the 0.084 band
    bg = bl = ba = 0          # inside the band
    nogap = 0
    for p in pairs:
        v = fn(p)
        if v is None:
            und += 1
            continue
        if not ((v > tau) if strict else (v >= tau)):
            continue
        lab = p["label"]
        g += lab == POSITIVE
        l += lab == NEGATIVE
        a += lab == AMBIGUOUS
        gap = p["rerank_gap"]
        if gap is None:
            nogap += 1
            continue
        if gap > NEAR_TIE:
            ag += lab == POSITIVE
            al += lab == NEGATIVE
            aa += lab == AMBIGUOUS
        else:
            bg += lab == POSITIVE
            bl += lab == NEGATIVE
            ba += lab == AMBIGUOUS
    n = len(pairs)
    return {
        "tau": tau, "comparison": ">" if strict else ">=",
        "n_flipped": g + l + a, "flips_gained": g, "flips_lost": l, "flips_ambiguous": a,
        "net_cases": g - l, "net_r1_delta": round((g - l) / n, 4), "n_undefined": und,
        "above_band": {"gained": ag, "lost": al, "ambiguous": aa, "net": ag - al},
        "inside_band": {"gained": bg, "lost": bl, "ambiguous": ba, "net": bg - bl},
        "flipped_with_no_gap": nogap,
    }


def blind_swap_reference(pairs) -> dict:
    """What a rule that fires on EVERYTHING scores, split by the band. The thing to beat."""
    out = {}
    for name, keep in (("all", lambda gp: True),
                       ("inside_band", lambda gp: gp is not None and gp <= NEAR_TIE),
                       ("above_band", lambda gp: gp is not None and gp > NEAR_TIE)):
        g = sum(1 for p in pairs if keep(p["rerank_gap"]) and p["label"] == POSITIVE)
        l = sum(1 for p in pairs if keep(p["rerank_gap"]) and p["label"] == NEGATIVE)
        out[name] = {"gained": g, "lost": l, "net": g - l}
    return out


def class_read(pairs) -> dict:
    """The control.json read: gold's concentration vs that of the distractor that sits beside it.

    POSITIVE pairs ARE the fit failures at the head (gold at rank 2, a distractor at rank 1).
    NEGATIVE pairs ARE the solved cases whose runner-up is not itself gold -- `control.json`'s
    `strict_successes_competitor_not_gold`, the population `head_probe.cross_check` gates on. If
    gold looks the same next to its competitor in both, the feature is a property of the corpus and
    not of the failures, which is how nine of ten predecessors died.
    """
    out = {}
    for label, gold_key, dist_key in ((POSITIVE, "_abl_r2", "_abl_r1"),
                                      (NEGATIVE, "_abl_r1", "_abl_r2")):
        for field in ("concentration", "max_drop"):
            gv = [p[gold_key][field] for p in pairs
                  if p["label"] == label and p[gold_key][field] is not None
                  and p[dist_key][field] is not None]
            dv = [p[dist_key][field] for p in pairs
                  if p["label"] == label and p[gold_key][field] is not None
                  and p[dist_key][field] is not None]
            out[f"{label}.{field}"] = {
                "n": len(gv),
                "gold_mean": round(float(np.mean(gv)), 4) if gv else None,
                "gold_median": round(float(np.median(gv)), 4) if gv else None,
                "distractor_mean": round(float(np.mean(dv)), 4) if dv else None,
                "distractor_median": round(float(np.median(dv)), 4) if dv else None,
                "mean_gold_minus_distractor": round(float(np.mean(gv) - np.mean(dv)), 4) if gv else None,
                "gold_higher_frac": round(float(np.mean([x > y for x, y in zip(gv, dv)])), 4) if gv else None,
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="ms-marco-MiniLM-L-2-v2-ft-session-j")
    ap.add_argument("--provider", default="CPUExecutionProvider")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    # -- THE GATE: head_probe.build() refuses unless fit R@1 reconstructs to 0.7555 --------------
    pools, pairs, r1 = HP.build()
    n = len(pairs)
    print(f"pairs: {n}   POSITIVE {sum(p['label']==POSITIVE for p in pairs)}  "
          f"NEGATIVE {sum(p['label']==NEGATIVE for p in pairs)}  "
          f"AMBIGUOUS {sum(p['label']==AMBIGUOUS for p in pairs)}")

    ce = R.load(args.model, provider=args.provider)
    smoke = R.smoke_test(ce)
    print(f"model: {ce.name}  digest {ce.digest[:16]}...  provider {args.provider}  "
          f"smoke {smoke['relevant']:+.4f} vs {smoke['irrelevant']:+.4f} pass={smoke['pass']}")
    if not smoke["pass"]:
        raise SystemExit("REFUSING: the loaded model does not discriminate in the right direction.")

    # -- the ablation sweep ----------------------------------------------------------------------
    t0 = time.perf_counter()
    forwards = 0
    repro = []
    for k, p in enumerate(pairs, 1):
        q = p["question"]
        for member, slot in (("rank1", "_abl_r1"), ("rank2", "_abl_r2")):
            rec = ablate(ce, q, p[member]["text"])
            forwards += rec["forwards"]
            p[slot] = rec
            if p[member]["reranked"] and p[member]["rerank_score"] is not None:
                repro.append({
                    "query_id": p["query_id"], "member": member,
                    "recorded": p[member]["rerank_score"], "recomputed": rec["s_full"],
                    "abs_diff": abs(rec["s_full"] - p[member]["rerank_score"]),
                })
        if k % 40 == 0:
            el = time.perf_counter() - t0
            print(f"  {k}/{n} pairs  {forwards} forwards  {el:.0f}s  "
                  f"{1000*el/max(forwards,1):.1f} ms/forward")
    elapsed = time.perf_counter() - t0

    # -- THE REPRODUCTION CHECK ------------------------------------------------------------------
    diffs = np.array([r["abs_diff"] for r in repro])
    worst = max(repro, key=lambda r: r["abs_diff"]) if repro else None
    print("\n" + "=" * 92)
    print("REPRODUCTION CHECK -- does this path reproduce head-probe.json's recorded rerank_score?")
    print("=" * 92)
    print(f"  candidates compared      {len(repro)} of {2*n}")
    print(f"  max  |recomputed - recorded|   {diffs.max():.3e}")
    print(f"  mean |recomputed - recorded|   {diffs.mean():.3e}")
    print(f"  median                         {np.median(diffs):.3e}")
    print(f"  worst case  {worst['query_id']} {worst['member']}: "
          f"recorded {worst['recorded']:.6f}  recomputed {worst['recomputed']:.6f}")
    if diffs.max() > REPRO_TOL:
        raise SystemExit(
            f"REFUSING. max |recomputed - recorded| is {diffs.max():.6f} > {REPRO_TOL}. This path "
            "is not the shipped scorer, so every drop measured here is about a different model."
        )
    print(f"  PASS (tolerance {REPRO_TOL})")

    # -- register the features on head_probe's harness without modifying that file ---------------
    HP.FEATURES["ablation_concentration"] = (
        "PRIMARY: max_i(drop_i)/sum_i|drop_i|, rank2 minus rank1. Higher = flip.", f_concentration)
    HP.FEATURES["ablation_max_drop_raw"] = (
        "SECONDARY, unnormalised: max_i(drop_i), rank2 minus rank1. Higher = flip.", f_max_drop)

    undef_c = sum(1 for p in pairs if f_concentration(p) is None)
    lt2 = sum(1 for p in pairs for s in ("_abl_r1", "_abl_r2") if p[s]["n_sentences"] < 2)
    zero = sum(1 for p in pairs for s in ("_abl_r1", "_abl_r2")
               if p[s]["n_sentences"] >= 2 and not p[s]["sum_abs_drop"])
    nsent = [p[s]["n_sentences"] for p in pairs for s in ("_abl_r1", "_abl_r2")]
    print(f"\nsentences/turn mean {np.mean(nsent):.2f} median {np.median(nsent):.0f} "
          f"max {max(nsent)}   forwards {forwards}   {elapsed:.0f}s")
    print(f"UNDEFINED pairs (never flipped): {undef_c}/{n}   "
          f"[members with <2 sentences: {lt2}/{2*n}; members with sum|drop| == 0: {zero}]")

    ref = blind_swap_reference(pairs)
    print(f"\nblind-swap reference   all {ref['all']['net']:+d}   "
          f"inside band {ref['inside_band']['net']:+d} "
          f"({ref['inside_band']['gained']}g/{ref['inside_band']['lost']}l)   "
          f"above band {ref['above_band']['net']:+d} "
          f"({ref['above_band']['gained']}g/{ref['above_band']['lost']}l)")

    results = {}
    for name, fn in (("ablation_concentration", f_concentration),
                     ("ablation_max_drop_raw", f_max_drop)):
        print("\n" + "=" * 92)
        print(f"{name} -- {HP.FEATURES[name][0]}")
        print("=" * 92)
        res = HP.evaluate(pairs, name, fn, n)

        prim = table(pairs, fn, strict=True)
        prim_ge = table(pairs, fn, strict=False)
        inv = table(pairs, lambda p, fn=fn: (None if fn(p) is None else -fn(p)), strict=True)

        for lab, t in (("tau=0, flip when value >  0  (PRIMARY, as registered)", prim),
                       ("tau=0, flip when value >= 0", prim_ge),
                       ("tau=0, SIGN-INVERTED control (flip when rank1 > rank2)", inv)):
            print(f"\n  {lab}")
            print(f"    flips {t['n_flipped']:>3d}   GAINED {t['flips_gained']:>3d}   "
                  f"LOST {t['flips_lost']:>3d}   amb {t['flips_ambiguous']:>3d}   "
                  f"NET {t['net_cases']:+d}   dR@1 {t['net_r1_delta']:+.4f}")
            ab, ib = t["above_band"], t["inside_band"]
            print(f"    ABOVE 0.084   gained {ab['gained']}  lost {ab['lost']}  "
                  f"amb {ab['ambiguous']}  net {ab['net']:+d}")
            print(f"    inside band   gained {ib['gained']}  lost {ib['lost']}  "
                  f"amb {ib['ambiguous']}  net {ib['net']:+d}")

        print("\n  full curve (threshold selected on fit -- a design signal, never a result):")
        HP.print_curve(name, res["forward"])
        b = res["forward"]["best"]
        ibst = res["negative_control_sign_inverted"]["best"]
        m = res["negative_control_at_matched_budget"]
        print(f"    BEST     net {b['net_cases']:+d} ({b['flips_gained']}g/{b['flips_lost']}l) at "
              f"tau {b['tau']:.4f}, {b['n_flipped']} flips, dR@1 {b['net_r1_delta']:+.4f}")
        print(f"    CONTROL  sign-inverted BEST net {ibst['net_cases']:+d} at "
              f"{ibst['n_flipped']} flips; at the SAME {b['n_flipped']}-flip budget "
              f"net {m['net_cases']:+d}")
        print(f"    separation from control {b['net_cases'] - ibst['net_cases']:+d}")

        # the above-band breakdown at the fit-selected best tau too, since that is the arm most
        # likely to be quoted
        best_tab = table(pairs, fn, strict=False, tau=b["tau"])
        print(f"    at BEST tau, ABOVE 0.084: gained {best_tab['above_band']['gained']}  "
              f"lost {best_tab['above_band']['lost']}  net {best_tab['above_band']['net']:+d}")

        results[name] = {
            "tau0_strict": prim, "tau0_inclusive": prim_ge, "tau0_sign_inverted": inv,
            "harness": res, "at_best_tau": best_tab,
        }

    # -- the control.json read -------------------------------------------------------------------
    cr = class_read(pairs)
    ctrl = json.loads((REPO / "runs" / "session-m0c-m" / "control.json").read_text(encoding="utf-8"))
    print("\n" + "=" * 92)
    print("CONTROL READ -- gold vs the distractor beside it, on FAILURES and on SOLVED cases")
    print("=" * 92)
    print(f"  control.json: {ctrl['summary'].get('strict_successes_competitor_not_gold')} solved "
          f"cases whose runner-up is not itself gold == the NEGATIVE population "
          f"({sum(p['label']==NEGATIVE for p in pairs)})")
    print(f"  {'population / field':<34}{'n':>4}{'GOLD mean':>11}{'DISTR mean':>12}"
          f"{'diff':>9}{'gold>dist':>11}")
    for k, v in cr.items():
        pop = "FAILURES (gold@2)" if k.startswith(POSITIVE) else "SOLVED (gold@1)"
        print(f"  {pop + ' ' + k.split('.')[1]:<34}{v['n']:>4}{v['gold_mean']:>11.4f}"
              f"{v['distractor_mean']:>12.4f}{v['mean_gold_minus_distractor']:>+9.4f}"
              f"{v['gold_higher_frac']:>11.4f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "H-B attribution concentration by leave-one-sentence-out ablation, fit split",
        "_measurement_only": True,
        "_registered_prediction": {
            "net_cases_at_tau0_fit": "+3 to +7",
            "above_0084": "<= 0 net -- predicted to FAIL the decisive test",
            "secondary_unnormalised": "WORSE than the ratio (raw drop scales with sentence count)",
        },
        "gate": {"published_fit_r1": HP.CONTROL_R1, "reconstructed_fit_r1": r1},
        "model": ce.name, "digest": ce.digest, "provider": args.provider, "max_seq": MAX_SEQ,
        "reproduction_check": {
            "n": len(repro), "max_abs_diff": float(diffs.max()),
            "mean_abs_diff": float(diffs.mean()), "median_abs_diff": float(np.median(diffs)),
            "tolerance": REPRO_TOL, "worst": worst,
        },
        "sentences_per_turn": {"mean": float(np.mean(nsent)), "median": float(np.median(nsent)),
                               "max": int(max(nsent))},
        "forwards": forwards, "seconds": round(elapsed, 1),
        "undefined_pairs": undef_c, "members_lt2_sentences": lt2, "members_zero_denominator": zero,
        "blind_swap_reference": ref,
        "results": results,
        "control_read": cr,
        "per_pair": [
            {"query_id": p["query_id"], "label": p["label"], "rerank_gap": p["rerank_gap"],
             "conc_r1": p["_abl_r1"]["concentration"], "conc_r2": p["_abl_r2"]["concentration"],
             "max_drop_r1": p["_abl_r1"]["max_drop"], "max_drop_r2": p["_abl_r2"]["max_drop"],
             "n_sent_r1": p["_abl_r1"]["n_sentences"], "n_sent_r2": p["_abl_r2"]["n_sentences"],
             "s_full_r1": p["_abl_r1"]["s_full"], "s_full_r2": p["_abl_r2"]["s_full"]}
            for p in pairs
        ],
    }, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
