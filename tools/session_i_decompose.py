"""Session I, Phase 0.2 — decompose the rank-1 failures, on the FIT split, before building.

Session G's 19:1 decomposition reframed a whole line of work in an afternoon. This is the same move
applied to the live problem: gold is in the reranker's slate 92.14% of the time on fit and reaches
rank 1 only 62.01% of the time, and the entire remaining problem lives in that gap.

**Fit only, deliberately.** This decomposition CHOOSES WHICH ARMS GET BUILT. That is a design
decision, and a design decision taken on held-out spends held-out power before a single band is
registered. The held-out half is read once, at the end, on one configuration.

**The arm-selection rule is written down here, above the numbers, and is evaluated mechanically
below.** Registering a rule after seeing the data it selects on is how a sweep becomes a story.

    RULE 1  mass concentrated at ranks 2-3      -> capacity leads (arm 2), depth second
    RULE 2  mass flat across ranks 2-10         -> context leads (arm 1); flat means the model has
                                                   no useful signal, not that it is narrowly beaten
    RULE 3  mass at "gold absent from the slate"-> depth leads (arm 3), and it is mandatory
    RULE 4  rank-1 distractors systematically longer or assistant-authored
                                                -> structural features (arm 7) is promoted, with a
                                                   length-control read attached
    RULE 5  failures concentrate in a category  -> reported as the next session's mandate whatever
                                                   else happens

**Input recall as a function of depth is computed WITHOUT the reranker**, from the gate key's rank
of gold inside the pruned pool. Reranking permutes a slate and never changes its membership, so
depth-d input recall is exactly "is gold within the first d by the gate key". That makes the ceiling
of every depth in arm 3 readable in seconds, before any model is downloaded.

**The cosine-to-gold read is a DIAGNOSTIC and is not a scored path.** It uses `reach_embed`'s
JinaEmbedder, which does not pin the ONNX graph optimization level -- correctly, for its own
purpose. No number in this session's frontier depends on it, and it is labelled in the output.

    python tools/session_i_decompose.py
"""

from __future__ import annotations

import io
import json
from collections import Counter, defaultdict

import numpy as np

from reach_pools import REPO, SPLIT_PATH, Pool, order_of, turn_texts
from reach_rerank_fit import (
    PREREG_PATH as SESSION_H_PREREG,
    build_session,
    gate_order,
    load_tokenizer,
    score_pair,
)
from reach_session_h_pruning import derived_keys, prune_mask
from session_h_pools import gated_fit_pools

OUT_PATH = REPO / "runs" / "session-i" / "failure-decomposition.json"
BUDGET = 10
DEPTHS = (10, 20, 30, 50, 100)


def turn_roles() -> dict[str, dict[str, str]]:
    """query_id -> turn_id -> 'user' | 'assistant'.

    Local rather than added to `reach_pools`, so Session H's tooling and its registered
    reconstruction gate are not perturbed while Session I is deriving bands from them.
    """
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    out: dict[str, dict[str, str]] = {}
    for inst in raw:
        per: dict[str, str] = {}
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                per[f"{sid}-{t_idx}"] = str(turn.get("role", "?"))
        out[str(inst["question_id"])] = per
    return out


def rank_bucket(rank: int | None) -> str:
    """Where gold landed. `None` means it was never in the slate to be ranked."""
    if rank is None:
        return "absent_from_slate"
    if rank == 1:
        return "1_solved"
    if rank in (2, 3):
        return f"{rank}"
    if rank <= 5:
        return "4-5"
    return "6-10"


def main() -> int:
    prereg = json.loads(io.open(SESSION_H_PREREG, encoding="utf-8").read())
    gap_ms = prereg["frozen_parameters"]["session_gap_ms"]["value"]
    prune_n = prereg["frozen_parameters"]["prune_N"]["value"]

    pools = gated_fit_pools()
    texts, roles = turn_texts(), turn_roles()
    sess, digest = build_session()
    tok = load_tokenizer()

    # A SECOND tokenizer, with neither truncation nor padding, purely to count word pieces. The
    # scoring tokenizer pads every input to 256, so its length is a constant and useless here.
    from tokenizers import Tokenizer
    counter = Tokenizer.from_file(str(REPO / "models" / "ms-marco-MiniLM-L-2-v2-int8" / "tokenizer.json"))

    def wordpieces(text: str) -> int:
        return len(counter.encode(text).ids)

    # DIAGNOSTIC ONLY. `JinaEmbedder` does not pin the graph optimization level -- correct for its
    # own purpose, and unacceptable for a scored path. Nothing in this session's frontier reads
    # this number; it exists to answer "is the winning distractor a near-paraphrase of gold, or a
    # different topic the reranker liked anyway?"
    from reach_embed import JinaEmbedder
    embedder = JinaEmbedder()
    _emb_cache: dict[str, np.ndarray] = {}

    def cosine(a: str, b: str) -> float | None:
        if not a or not b:
            return None
        for t in (a, b):
            if t not in _emb_cache:
                _emb_cache[t] = embedder.embed(t)
        return float(np.dot(_emb_cache[a], _emb_cache[b]))

    print(f"Fit split: {len(pools)} pools. Reranker L-2-int8 {digest[:16]}..., "
          f"batch 1, seq 256, ORT_ENABLE_BASIC.\n")

    rows = []
    depth_recall = Counter()
    for n_done, pool in enumerate(pools.values(), 1):
        per_turn, per_role = texts.get(pool.query_id, {}), roles.get(pool.query_id, {})
        keys = derived_keys(pool, gap_ms)
        pruned_idx = np.flatnonzero(prune_mask(pool, keys, prune_n))
        by_gate = pruned_idx[gate_order(pool, pruned_idx)]           # pruned pool, gate key order
        slate = by_gate[:BUDGET]

        gold_pos = np.flatnonzero(pool.gold[by_gate])                # gate-key ranks of gold, 0-based
        gate_rank_of_gold = int(gold_pos[0]) + 1 if gold_pos.size else None
        for d in DEPTHS:
            depth_recall[d] += bool(gate_rank_of_gold is not None and gate_rank_of_gold <= d)
        depth_recall["pruned_pool"] += bool(gate_rank_of_gold is not None)
        depth_recall["full_pool"] += bool(pool.gold.any())

        scores = np.array([
            score_pair(sess, tok, pool.question, per_turn.get(pool.candidates[int(i)].turn_id or "", ""))[0]
            for i in slate
        ])
        order = np.argsort(-scores, kind="stable")
        ranked = slate[order]                                        # slate in reranked order

        gold_in_ranked = np.flatnonzero(pool.gold[ranked])
        gold_rank = int(gold_in_ranked[0]) + 1 if gold_in_ranked.size else None
        top1 = int(ranked[0])
        gold_i = int(ranked[gold_in_ranked[0]]) if gold_in_ranked.size else None

        # Where the winner sits under each first-stage cue, over the WHOLE pool -- so a distractor
        # that no cue liked but the cross-encoder promoted is distinguishable from one both cues
        # already had at the top.
        lex_order = order_of(pool.array("lexical_bm25"))
        den_order = order_of(pool.array("dense_cosine"))
        rank_in = lambda o, i: int(np.flatnonzero(o == i)[0]) + 1  # noqa: E731

        t1_tid = pool.candidates[top1].turn_id or ""
        g_tid = pool.candidates[gold_i].turn_id if gold_i is not None else None
        row = {
            "query_id": pool.query_id,
            "category": pool.category,
            "solved": gold_rank == 1,
            "gold_rank_in_slate": gold_rank,
            "bucket": rank_bucket(gold_rank),
            "gate_rank_of_gold_in_pruned_pool": gate_rank_of_gold,
            "pruned_pool_size": int(by_gate.size),
            "cosine_rank1_to_gold": (
                None if g_tid is None
                else cosine(per_turn.get(t1_tid, ""), per_turn.get(g_tid, ""))
            ),
            "rank1": {
                "turn_id": t1_tid,
                "role": per_role.get(t1_tid, "?"),
                "wordpieces": wordpieces(per_turn.get(t1_tid, "")),
                "same_true_session_as_gold": (
                    None if g_tid is None
                    else pool.candidates[top1].sid == pool.candidates[gold_i].sid
                ),
                "same_derived_session_as_gold": (
                    None if gold_i is None else keys[top1] == keys[gold_i]
                ),
                "lexical_rank": rank_in(lex_order, top1),
                "dense_rank": rank_in(den_order, top1),
                "rerank_score": float(scores[order[0]]),
            },
            "gold": None if gold_i is None else {
                "turn_id": g_tid,
                "role": per_role.get(g_tid or "", "?"),
                "wordpieces": wordpieces(per_turn.get(g_tid or "", "")),
                "lexical_rank": rank_in(lex_order, gold_i),
                "dense_rank": rank_in(den_order, gold_i),
                "rerank_score": float(scores[order[int(gold_in_ranked[0])]]),
            },
        }
        row["rerank_margin_top1_minus_top2"] = float(scores[order[0]] - scores[order[1]]) \
            if len(order) > 1 else None
        rows.append(row)
        if n_done % 50 == 0:
            print(f"  {n_done}/{len(pools)} cases")

    n = len(rows)
    failures = [r for r in rows if not r["solved"]]

    # ---- 1. where does gold actually land -------------------------------------------------
    buckets = Counter(r["bucket"] for r in rows)
    order_of_buckets = ["1_solved", "2", "3", "4-5", "6-10", "absent_from_slate"]
    print("\n" + "=" * 78)
    print("1. WHERE GOLD LANDS in the reranked top-10 (fit, n=%d)" % n)
    print("=" * 78)
    for b in order_of_buckets:
        c = buckets.get(b, 0)
        share_all = c / n
        share_fail = c / len(failures) if b != "1_solved" else float("nan")
        bar = "#" * int(round(share_all * 60))
        tail = f"  {share_fail:>6.1%} of failures" if b != "1_solved" else ""
        print(f"  {b:>18}  {c:>4}  {share_all:>6.1%}{tail}  {bar}")

    # ---- 2. input recall as a function of depth, no reranker needed ------------------------
    print("\n" + "=" * 78)
    print("2. INPUT RECALL BY DEPTH -- the ceiling on R@1 at each depth (fit)")
    print("=" * 78)
    depth_table = {}
    for d in DEPTHS:
        ir = depth_recall[d] / n
        depth_table[str(d)] = {
            "input_recall": round(ir, 4),
            "conditional_accuracy_required_for_r1_080": round(0.80 / ir, 4) if ir else None,
            "attainable": bool(ir >= 0.80),
        }
        req = 0.80 / ir
        print(f"  depth {d:>4}   input recall {ir:.4f}   "
              f"conditional accuracy needed for R@1 0.80: {req:.4f}"
              f"{'' if req <= 1.0 else '   UNATTAINABLE AT THIS DEPTH'}")
    for name in ("pruned_pool", "full_pool"):
        ir = depth_recall[name] / n
        depth_table[name] = {"input_recall": round(ir, 4)}
        print(f"  {name:>9}   input recall {ir:.4f}")

    # ---- 3. what sits at rank 1 instead ---------------------------------------------------
    print("\n" + "=" * 78)
    print("3. WHAT SITS AT RANK 1 on the %d failures" % len(failures))
    print("=" * 78)

    def share(rs, pred):
        vals = [pred(r) for r in rs]
        vals = [v for v in vals if v is not None]
        return (sum(vals) / len(vals), len(vals)) if vals else (float("nan"), 0)

    solved = [r for r in rows if r["solved"]]
    role_fail = Counter(r["rank1"]["role"] for r in failures)
    role_ok = Counter(r["rank1"]["role"] for r in solved)
    print(f"  rank-1 author        failures: " +
          "  ".join(f"{k} {v/len(failures):.1%}" for k, v in sorted(role_fail.items())))
    print(f"                       solved:   " +
          "  ".join(f"{k} {v/len(solved):.1%}" for k, v in sorted(role_ok.items())))
    gold_role = Counter(r["gold"]["role"] for r in rows if r["gold"])
    print(f"  gold author overall  " +
          "  ".join(f"{k} {v/sum(gold_role.values()):.1%}" for k, v in sorted(gold_role.items())))

    fl = [r["rank1"]["wordpieces"] for r in failures]
    sl = [r["rank1"]["wordpieces"] for r in solved]
    gl = [r["gold"]["wordpieces"] for r in rows if r["gold"]]
    q = lambda v, p: float(np.percentile(v, p)) if v else float("nan")  # noqa: E731
    print(f"\n  wordpieces           {'median':>8} {'p75':>8} {'p95':>8}  (seq cap is 256)")
    for name, v in (("rank-1 on failures", fl), ("rank-1 on solved", sl), ("gold turns", gl)):
        print(f"    {name:<19} {q(v,50):>8.0f} {q(v,75):>8.0f} {q(v,95):>8.0f}")

    same_true, n_true = share(failures, lambda r: r["rank1"]["same_true_session_as_gold"])
    same_der, n_der = share(failures, lambda r: r["rank1"]["same_derived_session_as_gold"])
    print(f"\n  rank-1 shares gold's TRUE session      {same_true:.1%}  (n={n_true})")
    print(f"  rank-1 shares gold's DERIVED session   {same_der:.1%}  (n={n_der})")

    lex1 = [r["rank1"]["lexical_rank"] for r in failures]
    den1 = [r["rank1"]["dense_rank"] for r in failures]
    lexg = [r["gold"]["lexical_rank"] for r in failures if r["gold"]]
    deng = [r["gold"]["dense_rank"] for r in failures if r["gold"]]
    cf = [r["cosine_rank1_to_gold"] for r in failures if r["cosine_rank1_to_gold"] is not None]
    cs = [r["cosine_rank1_to_gold"] for r in solved if r["cosine_rank1_to_gold"] is not None]
    print(f"\n  cosine(rank-1, gold)   {'median':>8} {'p25':>8} {'p75':>8}   [DIAGNOSTIC -- "
          f"unpinned graph opt level, no frontier number reads it]")
    print(f"    on failures          {q(cf,50):>8.3f} {q(cf,25):>8.3f} {q(cf,75):>8.3f}")
    print(f"    on solved (=1.000 by construction, gold IS rank 1)  n={len(cs)}")

    print(f"\n  first-stage rank of the winner vs gold, on failures ({'median':>6}):")
    print(f"    rank-1  lexical {q(lex1,50):>6.0f}   dense {q(den1,50):>6.0f}")
    print(f"    gold    lexical {q(lexg,50):>6.0f}   dense {q(deng,50):>6.0f}")

    # ---- 4. categories --------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("4. FAILURES BY CATEGORY (fit)")
    print("=" * 78)
    cats: dict[str, list] = defaultdict(list)
    for r in rows:
        cats[r["category"]].append(r)
    cat_table = {}
    print(f"  {'category':>28} {'n':>4} {'R@1':>7} {'in-slate':>9} {'cond.acc':>9} {'absent':>7}")
    for cat, rs in sorted(cats.items(), key=lambda kv: -len(kv[1])):
        n_c = len(rs)
        present = sum(1 for r in rs if r["gold_rank_in_slate"] is not None)
        hits = sum(1 for r in rs if r["solved"])
        ca = hits / present if present else None
        cat_table[cat] = {
            "cases": n_c, "r_at_1": round(hits / n_c, 4),
            "input_recall": round(present / n_c, 4),
            "conditional_accuracy": round(ca, 4) if ca is not None else None,
            "absent_from_slate": n_c - present,
        }
        print(f"  {cat:>28} {n_c:>4} {hits/n_c:>7.4f} {present/n_c:>9.4f} "
              f"{(ca if ca is not None else float('nan')):>9.4f} {n_c-present:>7}")

    # ---- 5. the registered rule, evaluated mechanically ------------------------------------
    fail_n = len(failures)
    at_23 = (buckets.get("2", 0) + buckets.get("3", 0)) / fail_n
    at_absent = buckets.get("absent_from_slate", 0) / fail_n
    tail = [buckets.get(b, 0) / fail_n for b in ("2", "3", "4-5", "6-10")]
    flat = (max(tail) - min(tail)) < 0.15
    longer = q(fl, 50) > q(gl, 50) * 1.25
    assistant_heavy = role_fail.get("assistant", 0) / fail_n > \
        (gold_role.get("assistant", 0) / max(sum(gold_role.values()), 1)) + 0.15

    verdicts = {
        "RULE_1_capacity_leads_mass_at_rank_2_3": {"share_of_failures": round(at_23, 4),
                                                   "fires_if": "> 0.40", "fires": at_23 > 0.40},
        "RULE_2_context_leads_flat_2_to_10": {"spread": round(max(tail) - min(tail), 4),
                                              "fires_if": "spread < 0.15", "fires": bool(flat)},
        "RULE_3_depth_leads_mass_absent": {"share_of_failures": round(at_absent, 4),
                                           "fires_if": "> 0.20", "fires": at_absent > 0.20},
        "RULE_4_structural_features_promoted": {
            "rank1_median_wordpieces": q(fl, 50), "gold_median_wordpieces": q(gl, 50),
            "longer_by_25pct": bool(longer), "assistant_heavy_by_15pts": bool(assistant_heavy),
            "fires": bool(longer or assistant_heavy)},
    }
    print("\n" + "=" * 78)
    print("5. ARM-SELECTION RULE, evaluated (registered above the numbers, in this file's docstring)")
    print("=" * 78)
    for k, v in verdicts.items():
        print(f"  {'FIRES    ' if v['fires'] else 'silent   '} {k}")
        print(f"            {json.dumps({kk: vv for kk, vv in v.items() if kk != 'fires'})}")

    report = {
        "_what": "Session I Phase 0.2 -- rank-1 failure decomposition, FIT split, before building.",
        "split": "fit",
        "cases": n,
        "failures": fail_n,
        "reranker": {"model": "L-2-int8", "sha256": digest, "batch": 1, "max_seq_len": 256,
                     "threads": 1, "graph_optimization_level": "ORT_ENABLE_BASIC"},
        "slate": {"prune_N": prune_n, "session_gap_ms": gap_ms, "budget": BUDGET},
        "where_gold_lands": {b: buckets.get(b, 0) for b in order_of_buckets},
        "input_recall_by_depth": depth_table,
        "_input_recall_by_depth_note": (
            "Computed from the gate key's rank of gold inside the pruned pool, with NO reranker. "
            "Reranking permutes a slate and never changes its membership, so depth-d input recall "
            "is exactly 'gold within the first d by the gate key'. This is the ceiling on R@1 at "
            "each depth in arm 3, readable before any model is downloaded."
        ),
        "rank1_profile": {
            "role_on_failures": dict(role_fail), "role_on_solved": dict(role_ok),
            "gold_role_overall": dict(gold_role),
            "wordpieces": {
                "rank1_on_failures": {"median": q(fl, 50), "p75": q(fl, 75), "p95": q(fl, 95)},
                "rank1_on_solved": {"median": q(sl, 50), "p75": q(sl, 75), "p95": q(sl, 95)},
                "gold": {"median": q(gl, 50), "p75": q(gl, 75), "p95": q(gl, 95)},
            },
            "shares_gold_true_session": round(same_true, 4),
            "shares_gold_derived_session": round(same_der, 4),
            "first_stage_rank_medians_on_failures": {
                "rank1_lexical": q(lex1, 50), "rank1_dense": q(den1, 50),
                "gold_lexical": q(lexg, 50), "gold_dense": q(deng, 50),
            },
        },
        "by_category": cat_table,
        "arm_selection_rule": verdicts,
        "cosine_rank1_to_gold_on_failures": {
            "_diagnostic_only": (
                "reach_embed.JinaEmbedder does not pin the ONNX graph optimization level. Correct "
                "for its own purpose, unacceptable for a scored path. No frontier number reads it."
            ),
            "median": q(cf, 50), "p25": q(cf, 25), "p75": q(cf, 75), "n": len(cf),
        },
        "_per_case": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
