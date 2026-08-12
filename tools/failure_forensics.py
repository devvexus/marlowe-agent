"""Where does the gold actually sit when we miss R@1, and what beat it?

Every session so far has COUNTED failures. None has characterised them. This dumps one record per
missed case, rich enough that a reader -- human or model -- can look for what the winners have in
common that the gold does not.

    python tools/failure_forensics.py
    -> runs/session-m0c-m/failures.json      the full records
    -> runs/session-m0c-m/failures.md        the same thing, readable

**Fit split only.** Held-out is the validation set for whatever this suggests; characterising
failures on it would burn the split that has to judge the fix.

**The shipped configuration**, reconstructed from `runs/session-k/fit`. `rerank_score` is already in
that dump, so this reproduces the shipped ranking exactly with no model call -- and the ordering is
gated on reproducing the published fit R@1 of 0.7555 before a single record is written.

## The three failure classes, separated because they need different fixes

  * **ABSENT**   -- gold is not in the reranker's slate at all. An input-recall failure. Depth fixes
                    it: input recall is 0.9214 at depth 10 and 0.9825 at depth 30.
  * **DEMOTED**  -- the reranker SAW gold and pushed it down relative to where the cue order had it.
                    The reranker actively made this case worse.
  * **MISRANKED** -- gold was in the slate and the reranker left it below rank 1 without demoting it.

Lumping these together is how "the reranker is the problem" and "the slate is the problem" become
indistinguishable, and they have opposite fixes.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import numpy as np  # noqa: E402

from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
SLATE_DEPTH = 10  # the shipped budget, RERANK_BUDGET in retrieve.rs


def turn_roles() -> dict[str, dict[str, str]]:
    """query_id -> turn_id -> role. Built exactly as `reach_pools.turn_texts` builds text.

    Role is not on `Candidate` and is not in the dump; M0c Session A found 89.4% of held-out gold is
    user-authored, so it is the first structural axis to check and it has to come from the corpus.
    """
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    raw = json.loads((REPO / split["corpus_path"]).read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for inst in raw:
        per: dict[str, str] = {}
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                per[f"{sid}-{t_idx}"] = str(turn.get("role", ""))
        out[str(inst["question_id"])] = per
    return out


def describe(pool, index, texts, roles, pre_rank, final_rank):
    """One candidate, with everything a pattern could plausibly live in."""
    c = pool.candidates[index]
    text = texts.get(c.turn_id) or ""
    return {
        "turn_id": c.turn_id,
        "role": roles.get(c.turn_id) or None,
        "words": len(text.split()),
        "chars": len(text),
        "session_id": c.sid,
        "session_index": c.session_index,
        "turn_index": c.turn_index,
        "occurred_at_ms": c.occurred_at_ms,
        "rank_pre_rerank": pre_rank,
        "rank_final": final_rank,
        "reranked": c.rerank_score is not None,
        "rerank_score": c.rerank_score,
        "lexical_bm25": round(c.lexical_bm25, 4),
        "dense_cosine": round(c.dense_cosine, 4),
        "cue_z": round(c.score, 4),
        "cue_margin": round(c.margin, 4),
        "survived_pruning": c.survived_pruning,
        "text": text,
    }


def main() -> int:
    pools, stats = load_pools(FIT_POOLS)
    texts_all, roles_all = turn_texts(), turn_roles()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    answers = {c.query_id: c.gold_answer for c in corpus.cases}
    questions = {c.query_id: c.question for c in corpus.cases}

    # -- the gate: reproduce the shipped ranking before writing anything ------------------------
    final_orders, pre_orders = {}, {}
    hits = 0
    for qid, pool in pools.items():
        final_orders[qid] = shipped_order(pool)
        # The cue-only order: the same key with level 2 (rerank) removed, i.e. what the ranking
        # would have been had the cross-encoder never run. This is what DEMOTED is measured against.
        keys = [
            (0 if c.survived_pruning else 1, -c.score, -c.margin, c.memory_id or "")
            for c in pool.candidates
        ]
        pre_orders[qid] = np.array(
            sorted(range(len(pool.candidates)), key=lambda i: keys[i]), dtype=np.int64
        )
        hits += int(pool.gold[final_orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING. Reconstructed fit R@1 is {r1}; published is {CONTROL_R1}. The forensics "
            "would be describing a ranking the product does not produce."
        )
    print(f"control: fit R@1 {r1} == published {CONTROL_R1}. {len(pools)} queries.")

    records = []
    for qid, pool in pools.items():
        order, pre = final_orders[qid], pre_orders[qid]
        gold_idx = [i for i, g in enumerate(pool.gold) if g]
        top = int(order[0])
        if pool.gold[top]:
            continue  # solved

        texts, roles = texts_all.get(qid, {}), roles_all.get(qid, {})
        rank_of_final = {int(v): r + 1 for r, v in enumerate(order)}
        rank_of_pre = {int(v): r + 1 for r, v in enumerate(pre)}
        slate = {int(v) for v in pre[:SLATE_DEPTH]}

        # The best-placed gold turn: the one that decides R@1 for this case.
        best_gold = min(gold_idx, key=lambda i: rank_of_final[i])
        g = describe(pool, best_gold, texts, roles, rank_of_pre[best_gold], rank_of_final[best_gold])
        w = describe(pool, top, texts, roles, rank_of_pre[top], rank_of_final[top])

        in_slate = best_gold in slate
        if not in_slate:
            failure_class = "ABSENT"
        elif rank_of_final[best_gold] > rank_of_pre[best_gold]:
            failure_class = "DEMOTED"
        else:
            failure_class = "MISRANKED"

        same_session = (w["session_id"] is not None) and (w["session_id"] == g["session_id"])
        records.append(
            {
                "query_id": qid,
                "category": pool.category,
                "question": questions.get(qid),
                "gold_answer": answers.get(qid),
                "failure_class": failure_class,
                "gold_rank_final": g["rank_final"],
                "gold_rank_pre_rerank": g["rank_pre_rerank"],
                "gold_in_slate": in_slate,
                "n_gold_turns": len(gold_idx),
                "all_gold_ranks_final": sorted(rank_of_final[i] for i in gold_idx),
                "n_candidates": len(pool.candidates),
                # -- the contrast, which is what a pattern would live in ------------------------
                "same_session": same_session,
                "turn_gap": (
                    g["turn_index"] - w["turn_index"]
                    if same_session and g["turn_index"] is not None and w["turn_index"] is not None
                    else None
                ),
                "same_role": w["role"] == g["role"],
                "winner_is_longer": w["words"] > g["words"],
                "length_ratio_winner_over_gold": (
                    round(w["words"] / g["words"], 3) if g["words"] else None
                ),
                "rerank_gap": (
                    round(w["rerank_score"] - g["rerank_score"], 4)
                    if w["reranked"] and g["reranked"]
                    else None
                ),
                "winner": w,
                "gold": g,
                "top5": [
                    {
                        "rank": r + 1,
                        "is_gold": bool(pool.gold[int(i)]),
                        "role": roles.get(pool.candidates[int(i)].turn_id),
                        "words": len((texts.get(pool.candidates[int(i)].turn_id) or "").split()),
                        "rerank_score": pool.candidates[int(i)].rerank_score,
                        "text": (texts.get(pool.candidates[int(i)].turn_id) or "")[:400],
                    }
                    for r, i in enumerate(order[:5])
                ],
            }
        )

    # -- aggregates ----------------------------------------------------------------------------
    n = len(pools)
    cls = Counter(r["failure_class"] for r in records)
    ranks = Counter(min(r["gold_rank_final"], 99) for r in records)
    summary = {
        "queries": n,
        "R@1": r1,
        "failures": len(records),
        "failure_class": dict(cls),
        "gold_rank_final_histogram": {
            str(k): v for k, v in sorted(ranks.items())
        },
        "gold_at_rank_2": sum(1 for r in records if r["gold_rank_final"] == 2),
        "gold_in_top_5": sum(1 for r in records if r["gold_rank_final"] <= 5),
        "same_session_as_winner": sum(1 for r in records if r["same_session"]),
        "same_role_as_winner": sum(1 for r in records if r["same_role"]),
        "winner_longer_than_gold": sum(1 for r in records if r["winner_is_longer"]),
        "by_category": {
            c: {
                "failures": sum(1 for r in records if r["category"] == c),
                "of_queries": sum(1 for p in pools.values() if p.category == c),
            }
            for c in sorted({p.category for p in pools.values()})
        },
        "median_rerank_gap": round(
            float(np.median([r["rerank_gap"] for r in records if r["rerank_gap"] is not None])), 4
        ),
        "median_length_ratio": round(
            float(
                np.median(
                    [
                        r["length_ratio_winner_over_gold"]
                        for r in records
                        if r["length_ratio_winner_over_gold"] is not None
                    ]
                )
            ),
            3,
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "failures.json").write_text(
        json.dumps(
            {
                "_what": "fit-split R@1 failures under the SHIPPED configuration, characterised",
                "_split": "fit",
                "_config": "ms-marco-MiniLM-L-2-v2-ft-session-j, depth 10 (shipped)",
                "summary": summary,
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Fit-split R@1 failures, characterised",
        "",
        f"Shipped config. {n} queries, R@1 {r1}, **{len(records)} failures**.",
        "",
        "| | |",
        "|---|---|",
    ]
    for k, v in summary["failure_class"].items():
        lines.append(f"| class {k} | {v} |")
    lines += [
        f"| gold at rank 2 | {summary['gold_at_rank_2']} |",
        f"| gold in top 5 | {summary['gold_in_top_5']} |",
        f"| winner shares gold's session | {summary['same_session_as_winner']} |",
        f"| winner shares gold's role | {summary['same_role_as_winner']} |",
        f"| winner longer than gold | {summary['winner_longer_than_gold']} |",
        f"| median length ratio winner/gold | {summary['median_length_ratio']} |",
        f"| median rerank logit gap | {summary['median_rerank_gap']} |",
        "",
    ]
    for r in sorted(records, key=lambda x: (x["failure_class"], x["gold_rank_final"])):
        lines += [
            f"## {r['query_id']} · {r['category']} · {r['failure_class']} · gold at rank "
            f"{r['gold_rank_final']} (pre-rerank {r['gold_rank_pre_rerank']})",
            "",
            f"**Q:** {r['question']}",
            "",
            f"**A:** {r['gold_answer']}",
            "",
            f"- same session {r['same_session']} · turn gap {r['turn_gap']} · same role "
            f"{r['same_role']} · length ratio {r['length_ratio_winner_over_gold']} · rerank gap "
            f"{r['rerank_gap']}",
            "",
            f"**RANK 1 ({r['winner']['role']}, {r['winner']['words']}w, logit "
            f"{r['winner']['rerank_score']}):** {r['winner']['text'][:700]}",
            "",
            f"**GOLD ({r['gold']['role']}, {r['gold']['words']}w, logit "
            f"{r['gold']['rerank_score']}):** {r['gold']['text'][:700]}",
            "",
        ]
    (OUT_DIR / "failures.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nwrote {(OUT_DIR / 'failures.json').relative_to(REPO)}")
    print(f"wrote {(OUT_DIR / 'failures.md').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
