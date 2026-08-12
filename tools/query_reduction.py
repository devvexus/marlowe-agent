"""H-A — QUERY REDUCTION AT THE CROSS-ENCODER. Change the QUESTION side of the pair.

    python tools/query_reduction.py

**Measurement only. Fit split only. Nothing ships, no held-out read spent.**

## The hypothesis

The cross-encoder sees `[CLS] question [SEP] turn [SEP]`. Twenty-three mechanisms have changed the
TURN side (max-pooling, propositions, neighbours, decay) or the model. Nobody has changed the
QUESTION side. ADR-013 measured query EXPANSION (PRF, entity discovery, HyDE) at the cue/embedding
stage, before the cross-encoder existed. Query REDUCTION at the rerank stage is untested.

Many LongMemEval questions carry a meta-preamble that *quotes or points at a turn which is not the
answer*:

    89527b6b: "I'm going back to our previous conversation about the children's book on dinosaurs.
               Can you remind me what color was the scaly body of the Plesiosaur in the image?"

Rank 1 is the user's turn ASKING for a children's book about dinosaurs -- a near-verbatim match for
the preamble. The gold is the assistant's book text. The preamble is a pointer to the wrong turn and
it dominates the match.

## Two views, both FIXED BEFORE ANY NUMBER EXISTS

  * **V1 `q_last`** (parameter-free): the final sentence of the question only. Identity when the
    question is one sentence.
  * **V2 `preamble_drop`**: drop leading sentences containing any of a PRE-DECLARED, FIXED phrase
    list (below). Never drop the final sentence. Identity when nothing matches.

The V2 list is written here once and is NOT tuned. It is not fitted to the failures; it is the
generic English set of "I am referring back to something" openers.

## Three fusions, all declared, all reported

    reduced-only  S_red
    max           max(S_full, S_red)
    mean          (S_full + S_red) / 2

## REGISTERED PREDICTION (written before the run)

  * V2 reduced-only: +3 to +8 net cases on fit, concentrated in single-session-assistant/user.
  * V1 reduced-only: ~0 or negative -- "I'm planning a trip to Denver soon. Any suggestions on what
    to do there?" loses the topic word.
  * mean beats max for both views (max has the sentence-MaxP failure mode).
  * Direction above the 0.084 band: positive, because this re-scores the whole slate rather than
    breaking a near-tie.

## The bar

Rank 1 is already gold **110 against 26**. FLIPS GAINED vs FLIPS LOST, never a correlation. The
decisive read is the ABOVE-0.084 band, classified by the ORIGINAL SHIPPED gap. And the negative
control is the DROPPED PREAMBLE ALONE as the query: if that also improves R@1, the mechanism is not
what it claims and the result is noise.

## The gate

The shipped key must reproduce fit R@1 = 0.7555 exactly, and the head-pair labels must reproduce
head-probe.json's 26/110/93, before anything is emitted.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sentence_maxp import sentences  # noqa: E402  -- the ONE sentence splitter, reused
from sweep_reranker_frontier import (  # noqa: E402
    CONTROL_R1,
    FIT_POOLS,
    reordered,
    shipped_order,
)

OUT = REPO / "runs" / "session-m0c-m" / "query-reduction.json"
HEAD_PROBE = REPO / "runs" / "session-m0c-m" / "head-probe.json"

MAX_SEQ = 256      # ADR-015: a sequence-length change is a different scorer
SLATE_DEPTH = 10   # the shipped depth
NEAR_TIE = 0.084   # below this the two head scores are effectively identical

POSITIVE, NEGATIVE, AMBIGUOUS = "POSITIVE", "NEGATIVE", "AMBIGUOUS"

# ---------------------------------------------------------------------------------------------
# V2's phrase list. FIXED. Declared before any measurement, never tuned against a result.
# ---------------------------------------------------------------------------------------------
PREAMBLE_PATTERNS = (
    "previous conversation",
    "earlier conversation",
    "going back to",
    "get back to",
    "follow up on",
    "following up on",
    "you mentioned",
    "you said",
    "you told me",
    "as we discussed",
    "i wanted to confirm",
    "i was going through",
    "i remember we",
    "i remember you",
)


def view_v1(question: str) -> tuple[str, str]:
    """`q_last`: the final sentence. Returns (reduced, dropped_preamble)."""
    ss = sentences(question)
    if len(ss) < 2:
        return question, ""
    return ss[-1], " ".join(ss[:-1])


def view_v2(question: str) -> tuple[str, str]:
    """`preamble_drop`: drop leading pattern-matching sentences. Never drop the final one."""
    ss = sentences(question)
    i = 0
    while i < len(ss) - 1 and any(p in ss[i].lower() for p in PREAMBLE_PATTERNS):
        i += 1
    if i == 0:
        return question, ""
    return " ".join(ss[i:]), " ".join(ss[:i])


VIEWS = {"V1_q_last": view_v1, "V2_preamble_drop": view_v2}


# ---------------------------------------------------------------------------------------------


class Scorer:
    """The cross-encoder with a (query, doc) memo. Batch 1, seq 256, CPU, 1 thread -- as shipped."""

    def __init__(self, ce):
        self.ce = ce
        self.memo: dict[tuple[str, str], float] = {}
        self.calls = 0

    def score(self, query: str, doc: str) -> float:
        key = (query, doc)
        v = self.memo.get(key)
        if v is None:
            v = self.ce.score(query, doc, MAX_SEQ)
            self.memo[key] = v
            self.calls += 1
        return v


def tally(pools, order_by_qid) -> dict:
    """R@1 and the per-category breakdown. A tally, not a second ranking key."""
    n = len(pools)
    hits = 0
    per_cat: dict[str, list[int]] = {}
    per_query: dict[str, bool] = {}
    for qid, pool in pools.items():
        hit = bool(pool.gold[order_by_qid[qid][0]])
        per_query[qid] = hit
        hits += int(hit)
        per_cat.setdefault(pool.category, [0, 0])
        per_cat[pool.category][0] += 1
        per_cat[pool.category][1] += int(hit)
    return {
        "n": n,
        "R@1": round(hits / n, 4),
        "hits": hits,
        "per_category": {k: {"n": v[0], "hits": v[1], "R@1": round(v[1] / v[0], 4)}
                         for k, v in sorted(per_cat.items())},
        "_per_query": per_query,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ms-marco-MiniLM-L-2-v2-ft-session-j")
    ap.add_argument("--provider", default="CPUExecutionProvider")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts_all = turn_texts()

    orders = {qid: shipped_order(p) for qid, p in pools.items()}
    hits = sum(int(pools[q].gold[o[0]]) for q, o in orders.items())
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING. Reconstructed fit R@1 {r1} != published {CONTROL_R1}. This pipeline is not "
            "computing what the binary computes."
        )
    print(f"GATE 1  shipped key, fit R@1 {r1} == published {CONTROL_R1}   "
          f"({len(pools)} queries, {stats['candidates']:,} candidates)")

    # -- head-pair labels, and gate 2 against head-probe.json ---------------------------------
    labels, gaps = {}, {}
    for qid, pool in pools.items():
        i1, i2 = int(orders[qid][0]), int(orders[qid][1])
        g1, g2 = bool(pool.gold[i1]), bool(pool.gold[i2])
        labels[qid] = POSITIVE if (g2 and not g1) else NEGATIVE if (g1 and not g2) else AMBIGUOUS
        s1, s2 = pool.candidates[i1].rerank_score, pool.candidates[i2].rerank_score
        gaps[qid] = None if (s1 is None or s2 is None) else abs(s1 - s2)
    counts = Counter(labels.values())

    hp = json.loads(HEAD_PROBE.read_text(encoding="utf-8"))["population"]
    mismatch = [f"{k}: here {counts[k]} vs head-probe.json {hp[k]}"
                for k in (POSITIVE, NEGATIVE, AMBIGUOUS) if counts[k] != hp[k]]
    if mismatch:
        raise SystemExit("REFUSING. Head-pair labels disagree with head-probe.json:\n  "
                         + "\n  ".join(mismatch))
    print(f"GATE 2  head-pair labels == head-probe.json: "
          f"POSITIVE {counts[POSITIVE]}  NEGATIVE {counts[NEGATIVE]}  AMBIGUOUS {counts[AMBIGUOUS]}")
    above = sum(1 for g in gaps.values() if g is not None and g > NEAR_TIE)
    print(f"        original shipped head gap > {NEAR_TIE}: {above}/{len(pools)} queries "
          f"({sum(1 for q, g in gaps.items() if g is not None and g > NEAR_TIE and labels[q] == POSITIVE)} POS, "
          f"{sum(1 for q, g in gaps.items() if g is not None and g > NEAR_TIE and labels[q] == NEGATIVE)} NEG)")

    # -- the slates ----------------------------------------------------------------------------
    slates, docs_by_qid, unreranked = {}, {}, 0
    for qid, pool in pools.items():
        slate = [int(i) for i in orders[qid][:SLATE_DEPTH]]
        if any(pool.candidates[i].rerank_score is None for i in slate):
            unreranked += 1
        slates[qid] = slate
        docs_by_qid[qid] = [texts_all.get(qid, {}).get(pool.candidates[i].turn_id) or ""
                            for i in slate]
    print(f"        slates: depth {SLATE_DEPTH}, {unreranked} queries have an unreranked member")

    # -- the views, before any model runs ------------------------------------------------------
    views: dict[str, dict[str, tuple[str, str]]] = {}
    print()
    for vname, fn in VIEWS.items():
        v = {qid: fn(pools[qid].question) for qid in pools}
        views[vname] = v
        fired = [q for q, (red, _) in v.items() if red != pools[q].question]
        with_preamble = [q for q, (_, pre) in v.items() if pre.strip()]
        print(f"VIEW {vname:20s} changed the question on {len(fired)}/{len(pools)} queries; "
              f"non-empty preamble on {len(with_preamble)}")
        # THE BASE RATE ON THE TOUCHED POPULATION. Bar #1: a rule must be right on more than 81%
        # of the pairs it touches. Here the relevant number is how many of the queries it touches
        # were ALREADY CORRECT -- those are the ones it can only break.
        already = [q for q in fired if bool(pools[q].gold[orders[q][0]])]
        print(f"     {'':20s}   of those, ALREADY CORRECT at baseline: {len(already)}/{len(fired)} "
              f"({len(fired) - len(already)} are baseline failures it could fix)")
        by_cat = Counter(pools[q].category for q in fired)
        for c, k in sorted(by_cat.items()):
            print(f"     {'':20s}   {c:32s} {k}")

    ce = R.load(args.model, provider=args.provider)
    print(f"\nmodel {ce.name}  digest {ce.digest[:16]}...  {args.provider}  batch 1  seq {MAX_SEQ}")
    smoke = R.smoke_test(ce)
    det = R.determinism(ce)
    print(f"smoke: relevant {smoke['relevant']:.4f} > irrelevant {smoke['irrelevant']:.4f} "
          f"pass={smoke['pass']}   determinism pass={det['pass']}")
    if not smoke["pass"] or not det["pass"]:
        raise SystemExit("REFUSING. The loader's own gates did not pass.")
    sc = Scorer(ce)

    # -- S_full: the full question, re-scored in THIS process ----------------------------------
    t0 = time.perf_counter()
    s_full = {}
    for i, qid in enumerate(sorted(pools), 1):
        q = pools[qid].question
        s_full[qid] = [sc.score(q, d) for d in docs_by_qid[qid]]
        if i % 60 == 0:
            print(f"  S_full {i}/{len(pools)}  {sc.calls} forwards  "
                  f"{time.perf_counter() - t0:.0f}s")
    py_full_order = {qid: reordered(pools[qid], slates[qid], s_full[qid]) for qid in pools}
    py_full = tally(pools, py_full_order)
    print(f"\nPYTHON-FULL CONTROL  re-scoring the FULL question in this process reproduces "
          f"R@1 {py_full['R@1']}  (shipped dump {r1}, delta {py_full['R@1'] - r1:+.4f})")
    print("  This is the baseline every fusion delta below is measured against, so the Rust/Python")
    print("  scorer difference cannot be mistaken for an arm's effect.")

    # -- the arms ------------------------------------------------------------------------------
    def fuse(full, red, how):
        if how == "reduced-only":
            return list(red)
        if how == "max":
            return [max(a, b) for a, b in zip(full, red)]
        return [(a + b) / 2.0 for a, b in zip(full, red)]

    def run_arm(label: str, qtext, changed: set[str]) -> list[dict]:
        red = {}
        for qid in pools:
            q = qtext(qid)
            red[qid] = [sc.score(q, d) for d in docs_by_qid[qid]] if q is not None \
                else list(s_full[qid])
        out = []
        for how in ("reduced-only", "max", "mean"):
            fused = {qid: fuse(s_full[qid], red[qid], how) for qid in pools}
            order = {qid: reordered(pools[qid], slates[qid], fused[qid]) for qid in pools}
            t = tally(pools, order)

            # -- head-pair flip table (against the SHIPPED head pair) ----------------------
            pos_to_idx = {qid: {c: k for k, c in enumerate(slates[qid])} for qid in pools}
            g = l = amb = 0
            g_above = l_above = amb_above = 0
            n_flipped = 0
            flip_detail = []
            for qid in pools:
                i1, i2 = int(orders[qid][0]), int(orders[qid][1])
                pm = pos_to_idx[qid]
                if i1 not in pm or i2 not in pm:
                    continue
                f1, f2 = fused[qid][pm[i1]], fused[qid][pm[i2]]
                if f2 <= f1:
                    continue
                n_flipped += 1
                lab = labels[qid]
                g += lab == POSITIVE
                l += lab == NEGATIVE
                amb += lab == AMBIGUOUS
                if gaps[qid] is not None and gaps[qid] > NEAR_TIE:
                    g_above += lab == POSITIVE
                    l_above += lab == NEGATIVE
                    amb_above += lab == AMBIGUOUS
                flip_detail.append({"query_id": qid, "label": lab, "orig_gap": gaps[qid],
                                    "category": pools[qid].category})

            # -- full-slate case-level gains and losses, split by the ORIGINAL head gap ------
            base_hits = py_full["_per_query"]
            fs_gain = [q for q in pools if t["_per_query"][q] and not base_hits[q]]
            fs_loss = [q for q in pools if base_hits[q] and not t["_per_query"][q]]
            fs_gain_above = [q for q in fs_gain if gaps[q] is not None and gaps[q] > NEAR_TIE]
            fs_loss_above = [q for q in fs_loss if gaps[q] is not None and gaps[q] > NEAR_TIE]

            rec = {
                "arm": label,
                "fusion": how,
                "n_queries_view_changed": len(changed),
                "head_pair": {
                    "flips_total": n_flipped,
                    "flips_gained": g,
                    "flips_lost": l,
                    "flips_ambiguous": amb,
                    "net_cases": g - l,
                    "net_r1_delta": round((g - l) / len(pools), 4),
                    "above_0.084": {"gained": g_above, "lost": l_above,
                                    "ambiguous": amb_above, "net": g_above - l_above},
                    "flips": flip_detail,
                },
                "full_slate": {
                    "R@1": t["R@1"],
                    "delta_vs_python_full": round(t["R@1"] - py_full["R@1"], 4),
                    "delta_vs_shipped": round(t["R@1"] - r1, 4),
                    "cases_gained": len(fs_gain),
                    "cases_lost": len(fs_loss),
                    "net_cases": len(fs_gain) - len(fs_loss),
                    "above_0.084": {"gained": len(fs_gain_above), "lost": len(fs_loss_above),
                                    "net": len(fs_gain_above) - len(fs_loss_above)},
                    "gained_ids": fs_gain,
                    "lost_ids": fs_loss,
                    "per_category": t["per_category"],
                },
            }
            out.append(rec)
            hp_ = rec["head_pair"]
            fs_ = rec["full_slate"]
            print(f"  {label:34s} {how:<13s} "
                  f"head g/l {hp_['flips_gained']:>2}/{hp_['flips_lost']:<3} net {hp_['net_cases']:>+3}  "
                  f"| slate R@1 {fs_['R@1']:.4f} d {fs_['delta_vs_python_full']:>+7.4f} "
                  f"g/l {fs_['cases_gained']:>2}/{fs_['cases_lost']:<3} net {fs_['net_cases']:>+3}  "
                  f"| >0.084 g/l {fs_['above_0.084']['gained']:>2}/{fs_['above_0.084']['lost']:<3} "
                  f"net {fs_['above_0.084']['net']:>+3}")
        return out

    results = []
    print("\n" + "=" * 118)
    print("THE ARMS -- full-slate re-rank at depth 10, deltas against the PYTHON-FULL control")
    print("=" * 118)
    for vname in VIEWS:
        v = views[vname]
        changed = {q for q in pools if v[q][0] != pools[q].question}
        results += run_arm(vname, lambda qid, v=v: v[qid][0], changed)

    print("\n" + "=" * 118)
    print("NEGATIVE CONTROL -- the DROPPED PREAMBLE ALONE as the query. If this also improves,")
    print("the mechanism is not what it claims and the result is noise.")
    print("=" * 118)
    for vname in VIEWS:
        v = views[vname]
        changed = {q for q in pools if v[q][1].strip()}

        def preamble_q(qid, v=v):
            pre = v[qid][1].strip()
            return pre if pre else None   # no preamble -> unchanged, exactly as the view is

        results += run_arm(f"NEGCTL preamble-only {vname}", preamble_q, changed)

    # -- THE MECHANISM DIAGNOSTIC ------------------------------------------------------------
    #
    # The arms above say WHETHER reduction helps. This says WHY. The hypothesis is that the
    # preamble lifts the DISTRACTOR more than the gold ("a pointer to the wrong turn"). The
    # preamble's contribution to a candidate's score is exactly (S_full - S_red), and it is
    # already computed for every slate member. So split it by gold/non-gold and read the sign.
    #
    # The hypothesis requires the per-query differential to be NEGATIVE.
    print("\n" + "=" * 118)
    print("MECHANISM DIAGNOSTIC -- the preamble's contribution (S_full - S_red), gold vs non-gold")
    print("=" * 118)
    diagnostics = {}
    for vname in VIEWS:
        v = views[vname]
        fired = [q for q in sorted(pools) if v[q][0] != pools[q].question]
        gold_d, dist_d, per_q = [], [], []
        for qid in fired:
            q = v[qid][0]
            gs, ds = [], []
            for k, i in enumerate(slates[qid]):
                delta = s_full[qid][k] - sc.score(q, docs_by_qid[qid][k])
                (gs if pools[qid].gold[i] else ds).append(delta)
            gold_d += gs
            dist_d += ds
            if gs and ds:
                per_q.append(float(np.mean(gs) - np.mean(ds)))
        g, d_ = np.array(gold_d), np.array(dist_d)
        pq = np.array(per_q)
        diagnostics[vname] = {
            "fired": len(fired),
            "gold": {"n": len(g), "mean": round(float(g.mean()), 4),
                     "median": round(float(np.median(g)), 4)},
            "non_gold": {"n": len(d_), "mean": round(float(d_.mean()), 4),
                         "median": round(float(np.median(d_)), 4)},
            "per_query_gold_minus_distractor": {
                "n": len(pq), "mean": round(float(pq.mean()), 4),
                "median": round(float(np.median(pq)), 4),
                "favour_gold": int((pq > 0).sum()), "favour_distractor": int((pq < 0).sum()),
            },
            "_hypothesis_requires": "NEGATIVE -- the preamble must help distractors more than gold",
        }
        print(f"  {vname:20s} fired {len(fired):>3}   "
              f"GOLD n={len(g):<4} mean {g.mean():+.4f} median {np.median(g):+.4f}   "
              f"NON-GOLD n={len(d_):<4} mean {d_.mean():+.4f} median {np.median(d_):+.4f}")
        print(f"  {'':20s} per-query (gold - distractor): mean {pq.mean():+.4f} "
              f"median {np.median(pq):+.4f}; {int((pq > 0).sum())} queries favour GOLD, "
              f"{int((pq < 0).sum())} favour distractors")
        print(f"  {'':20s} the hypothesis requires this to be NEGATIVE.")

    print(f"\n{sc.calls} cross-encoder forwards, {time.perf_counter() - t0:.0f}s wall")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "H-A query reduction at the cross-encoder. Fit split. Measurement only.",
        "_registered_prediction": {
            "V2_reduced_only": "+3 to +8 net cases on fit, concentrated in "
                               "single-session-assistant and single-session-user",
            "V1_reduced_only": "~0 or negative (loses the topic word on 2-sentence questions)",
            "mean_vs_max": "mean beats max for both views",
            "above_band": "positive -- a whole-slate re-score, not a near-tie tie-break",
        },
        "model": args.model, "provider": args.provider, "max_seq": MAX_SEQ,
        "slate_depth": SLATE_DEPTH, "near_tie": NEAR_TIE,
        "v2_patterns": list(PREAMBLE_PATTERNS),
        "gate": {"shipped_fit_r1": r1, "published": CONTROL_R1,
                 "head_labels": dict(counts),
                 "python_full_control_r1": py_full["R@1"],
                 "python_full_per_category": py_full["per_category"]},
        "views": {vn: {q: {"reduced": views[vn][q][0], "preamble": views[vn][q][1],
                           "question": pools[q].question, "category": pools[q].category}
                       for q in sorted(pools) if views[vn][q][0] != pools[q].question}
                  for vn in VIEWS},
        "arms": results,
        "mechanism_diagnostic": diagnostics,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
