"""Every near miss, with its full top-30, for pattern-hunting.

    python tools/dump_near_misses.py

Writes `runs/session-m0c-m/near-misses.json` and a readable `near-misses.md`.

## What a "near miss" is here

A query where the gold turn is present in the ranking but NOT at rank 1. These are the recoverable
failures -- 53 of 75 on held-out, and **32 of them have gold sitting at rank 2**. The other 22 are
ABSENT (gold outside the depth-10 slate) and are a different problem, so they are marked rather
than mixed in.

## Read this before hunting for patterns in it

Twenty-one mechanisms have already been measured against this population. The ones that FAILED are
listed in the artifact so the same ground is not re-covered, and — more usefully — so a new idea can
be checked against the reason each failed rather than its bare verdict.

**The single most important constraint:** rank 1 is already gold **110 times against 26** in the
head population, so any rule that reorders must be right on **more than 81%** of the pairs it
touches or it loses ground. That is why "this pattern appears in 40% of failures" is not evidence —
it has to appear in failures *and not* in successes, which is why the correct-case control
(`control.json`, the 173 solved cases) exists and killed 9 of 10 hypotheses.

**And the second:** a rule that only fires where the cross-encoder gap is below **0.084** is
indistinguishable from a coin flip, because a blind swap in that band scores +5 — more than the
span reader, sentence MaxP, or the ensemble achieved. Every candidate carries its gap so this can
be checked immediately.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from failure_forensics import turn_roles  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "near-misses.json"
MD = REPO / "runs" / "session-m0c-m" / "near-misses.md"
DEPTH = 30

ALREADY_TRIED = {
    "_read_this_first": (
        "21 mechanisms measured against this exact population. Each entry is WHY it failed, not "
        "just that it did -- a new idea should be checked against the reason."
    ),
    "question_echo (winner carries question words gold lacks)": (
        "REAL as a diagnostic -- 41% of failures vs 16% of successes, control-tested, p=0.0014. "
        "DEAD as a tie-break: at tau>=1 it flips 121 pairs for 10 gained / 73 lost, net -63, "
        "because BOTH rank-1 and rank-2 usually echo the question."
    ),
    "IDF non-query mass": "0 net at every threshold; the sign-inverted control is ALSO negative, so it is not separating this population at all.",
    "length / ln(words) / winner_longer": "0.554 of failures vs 0.520 of successes, p=0.758. Dead.",
    "gold truncated at 256 tokens": "0.107 vs 0.109 on strict successes. Exactly no signal. Confined 100% to single-session-assistant, where two-sided p=0.062.",
    "same_role, same_session": "0.929 vs 0.919 and REVERSES on strict successes. Corpus properties, not failure properties.",
    "recency / temporal proximity": "~0 net. knowledge-update (2/10) and temporal (9/12) cancel exactly.",
    "dense-cosine fusion at rank 2": "0 flips at EVERY weight.",
    "numeric answer-type filter": "2 of 56.",
    "neighbour similarity (gold as outlier)": "REFUTED and backwards -- gold is MORE similar to its neighbours (0.1851 vs 0.1533). The slate is drawn from pruned sessions so gold is INSIDE the cluster.",
    "centroid subtraction (remove the shared component)": "raw dense -43, centred dense -47. Removing what candidates share made it WORSE; the shared direction carries signal.",
    "sentence MaxP": "pure max 11 gained / 15 lost -- it surfaces the buried answer AND the imposter, and the imposter wins more. Fusion +4/-0 but ALL gains below 0.084 and 6 fires above it with 0 correct.",
    "proposition-level INDEXING": "input recall -0.0786 at depth 10. 4202 units from 487 turns means 4202 chances for a distractor to own one lucky proposition.",
    "context decay around the peak": "hypothesis was BACKWARDS -- gold decays 10x MORE (0.1337 vs 0.0133), because the gold answer is a narrow span in a multi-topic turn while distractors are uniformly on-topic. Inverted sign: fit +0.0305, HELD-OUT -0.0087.",
    "three SQuAD-v2 span readers": "real signal (inverted controls -44 vs -163) but WEAKER than the cross-encoder, and redundant: +6/-0 on the shipped ranking became 1 gained / 4 lost against a better one.",
    "ensemble vote of 5 cross-encoders": "best net +2; above 0.084 it loses 5 gained / 8 lost. When voters disagree with the incumbent and it is confident, the incumbent is usually right.",
    "nine pretrained cross-encoders, 16M-278M": "the 278M models LOSE to a fine-tuned 16M by 17-27 points. Capacity refuted across a 17x range.",
    "rerank depth 10 -> 30": "input recall +0.0743, conditional accuracy -0.0520, net +0.0044, p=1.000 on held-out. Third reproduction of that trade.",
    "retrain with new negatives (arm B)": "fit 0.8253 (p=0.0004!) -> held-out 0.6812. deployed_top_k negatives are query-specific, so it memorised turns.",
    "BCE instead of MarginMSE": "-0.0524 at fixed negatives. The objective change HURTS.",
    "joint pairwise encoder (duoBERT)": "the only thing to fire correctly above the band on fit (15/6) -- on held-out that became 20/20, an exact coin flip. Symmetry control failed on both splits.",
    "small LLM picking from the top 3": "0.5B is degenerate (never picks option 1); 4B nets -1 at n=40. Latency is NOT the blocker -- model-only cost is 22-147 ms against a 285 ms headroom.",
    "score recalibration": "IMPOSSIBLE, not merely ineffective: R@1 is a within-query ordering read and any monotone transform is an identity on it.",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=DEPTH)
    args = ap.parse_args()

    pools, _ = load_pools(FIT_POOLS)
    texts_all, roles_all = turn_texts(), turn_roles()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    cases = {c.query_id: c for c in corpus.cases}

    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}")
    print(f"control: fit R@1 {r1}  ({len(pools)} queries)")

    records = []
    for qid, pool in sorted(pools.items()):
        order = [int(i) for i in orders[qid]]
        if pool.gold[order[0]]:
            continue
        texts, roles = texts_all.get(qid, {}), roles_all.get(qid, {})
        case = cases[qid]
        gold_rank = next((j + 1 for j, i in enumerate(order) if pool.gold[i]), None)
        s = [pool.candidates[i].rerank_score for i in order[:2]]
        top = []
        for j, i in enumerate(order[: args.depth]):
            c = pool.candidates[i]
            top.append({
                "rank": j + 1, "is_gold": bool(pool.gold[i]),
                "role": roles.get(c.turn_id), "turn_id": c.turn_id,
                "session_id": c.sid, "turn_index": c.turn_index,
                "rerank_score": c.rerank_score, "cue_z": round(c.score, 4),
                "cue_margin": round(c.margin, 4),
                "bm25": round(c.lexical_bm25, 4), "cosine": round(c.dense_cosine, 4),
                "survived_pruning": c.survived_pruning,
                "text": texts.get(c.turn_id) or "",
            })
        records.append({
            "query_id": qid, "category": pool.category,
            "question": case.question, "gold_answer": case.gold_answer,
            "question_date": getattr(case, "ask_at_ms", None),
            "gold_rank": gold_rank,
            "gold_in_top_30": gold_rank is not None and gold_rank <= args.depth,
            "class": ("RANK-2 NEAR MISS" if gold_rank == 2
                      else "RANK-3" if gold_rank == 3
                      else "IN-SLATE" if gold_rank and gold_rank <= 10
                      else "ABSENT (different problem -- gold outside the depth-10 slate)"),
            "ce_gap_rank1_rank2": (round(s[0] - s[1], 4) if None not in s else None),
            "_gap_note": ("below 0.084 means the two scores are effectively identical and a blind "
                          "swap there already scores +5 -- a rule that only fires here is a coin flip"),
            "n_gold_turns": int(sum(pool.gold)),
            "top": top,
        })

    by_class: dict[str, int] = {}
    for r in records:
        by_class[r["class"]] = by_class.get(r["class"], 0) + 1

    OUT.write_text(json.dumps({
        "_what": f"every fit-split failure with its full top-{args.depth}, for pattern-hunting",
        "_split": "fit", "_config": "shipped (L-2-ft @ depth 10)",
        "control_fit_r1": r1, "queries": len(pools), "failures": len(records),
        "by_class": by_class,
        "THE_BAR": {
            "head_population": "rank 1 is gold 110 times vs 26 -- a reordering rule must be right on >81% of pairs it touches",
            "correct_case_control": "runs/session-m0c-m/control.json holds the same features for the 173 SOLVED cases. A pattern that does not separate failures from successes is not a finding; that control killed 9 of 10 hypotheses",
            "near_tie_band": "a rule firing only below a 0.084 gap is a coin flip -- blind swapping there scores +5",
        },
        "ALREADY_TRIED_AND_WHY_IT_FAILED": ALREADY_TRIED,
        "records": records,
    }, indent=2) + "\n", encoding="utf-8")

    lines = [f"# Fit-split failures with full top-{args.depth}", "",
             f"{len(pools)} queries, R@1 {r1}, **{len(records)} failures**.", ""]
    for k, v in sorted(by_class.items()):
        lines.append(f"- {k}: **{v}**")
    lines += ["", "**Before hunting:** rank 1 is already gold 110 times against 26, so a rule must "
              "be right on >81% of what it touches. `control.json` has the same features for the "
              "173 SOLVED cases — a pattern must separate the two. A rule that fires only below a "
              "0.084 gap is a coin flip (blind swap there = +5). 21 mechanisms already failed; see "
              "`ALREADY_TRIED_AND_WHY_IT_FAILED` in the JSON.", ""]
    for r in sorted(records, key=lambda x: (x["gold_rank"] or 999)):
        lines += [f"## {r['query_id']} · {r['category']} · {r['class']} · gold rank "
                  f"{r['gold_rank']} · gap {r['ce_gap_rank1_rank2']}", "",
                  f"**Q:** {r['question']}", "", f"**A:** {r['gold_answer']}", ""]
        for c in r["top"][:6]:
            tag = "  ⬅ **GOLD**" if c["is_gold"] else ""
            lines.append(f"**{c['rank']}.** [{c['role']}, logit {c['rerank_score']}, "
                         f"bm25 {c['bm25']}, cos {c['cosine']}]{tag}")
            for ln in textwrap.wrap(c["text"][:400], 100):
                lines.append(f"    {ln}")
            lines.append("")
        if r["gold_rank"] and r["gold_rank"] > 6:
            g = next(c for c in r["top"] if c["is_gold"]) if r["gold_in_top_30"] else None
            if g:
                lines.append(f"**GOLD at rank {g['rank']}** [{g['role']}, logit {g['rerank_score']}]")
                for ln in textwrap.wrap(g["text"][:400], 100):
                    lines.append(f"    {ln}")
                lines.append("")
    MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{len(records)} failures: " + ", ".join(f"{k} {v}" for k, v in sorted(by_class.items())))
    print(f"wrote {OUT.relative_to(REPO)}  ({OUT.stat().st_size // 1024} KB)")
    print(f"wrote {MD.relative_to(REPO)}  ({MD.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
