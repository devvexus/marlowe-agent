"""Prune-reach diagnostic: for each pruning-lost QUERY, where did the gold session rank?

Uses the dump's own cue scores to rank derived sessions exactly as retrieve.rs does
(max-aggregated score per session per cue, sessions sorted desc), then reports:
  - the gold session's best rank across the two cues
  - whether keep-N = 4, 5, 6 would admit it
  - pool inflation for ALL queries at each N (sessions admitted)

DIAGNOSTIC ONLY -- selects nothing, registers nothing.

    python tools/prune_reach.py --run runs/session-m0c-n/cascade-heldout-cuda-v2/heldout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from reach_pools import load_pools  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    n = len(pools)

    # Per query: session -> max score (the "lexical-ish" aggregate uses `score`; dense uses
    # dense_cosine). retrieve.rs ranks sessions per cue by MAX score within session.
    lost_queries = []
    recovered_at = {4: 0, 5: 0, 6: 0}
    infl = {4: [], 5: [], 6: []}
    for q, p in pools.items():
        sess_score: dict[tuple, float] = {}
        sess_dense: dict[tuple, float] = {}
        gold_sess: dict[tuple, bool] = {}
        for c in p.candidates:
            key = (c.sid, c.session_key)
            if key not in sess_score or c.score > sess_score[key]:
                sess_score[key] = c.score
            if key not in sess_dense or (c.dense_cosine or 0) > sess_dense[key]:
                sess_dense[key] = c.dense_cosine or 0.0
            gold_sess[key] = gold_sess.get(key, False) or bool(
                c.is_gold and c.turn_id and False  # placeholder; gold-per-session set below
            )
        # gold membership per session: a session is gold-bearing if ANY candidate in it is gold
        # AND that candidate survived_pruning is irrelevant here (we ask about the raw pool)
        gold_by_session = set()
        for c in p.candidates:
            if c.is_gold and c.sid is not None:
                gold_by_session.add((c.sid, c.session_key))
        # NOTE: candidates already exclude pruned-away? No -- reach_pools keeps them with
        # survived_pruning=False, so non-survivors' sessions appear too.

        def rank_of(key, table):
            order = sorted(table, key=lambda k: (-table[k], k))
            return order.index(key) + 1 if key in order else None

        # which queries lost ALL their gold at pruning?
        surviving_gold_sessions = {
            (c.sid, c.session_key) for c in p.candidates
            if c.is_gold and c.survived_pruning and c.sid is not None
        }
        all_gold_sessions = {(c.sid, c.session_key) for c in p.candidates
                             if c.is_gold and c.sid is not None}
        if all_gold_sessions and not surviving_gold_sessions:
            lost_queries.append(q)
            best_rank = min(
                r for r in (
                    min(rank_of(k, sess_score) or 10**6, rank_of(k, sess_dense) or 10**6)
                    for k in all_gold_sessions
                )
            )
            tag = next((f"N{nn}" for nn in (3, 4, 5, 6) if best_rank <= nn), "N>6")
            print(f"LOST {q}: gold session best-rank {best_rank} ({tag})")
            for nn in (4, 5, 6):
                if best_rank <= nn:
                    recovered_at[nn] += 1

        # pool inflation at each N (union over both cues), counting sessions
        for nn in (4, 5, 6):
            keep = set()
            for table in (sess_score, sess_dense):
                order = sorted(table, key=lambda k: (-table[k], k))
                keep.update(order[:nn])
            infl[nn].append(len(keep))

    base3 = []
    for q, p in pools.items():
        sess_score = {}
        sess_dense = {}
        for c in p.candidates:
            key = (c.sid, c.session_key)
            sess_score[key] = max(sess_score.get(key, -1e9), c.score)
            sess_dense[key] = max(sess_dense.get(key, -1e9), c.dense_cosine or 0.0)
        keep = set()
        for table in (sess_score, sess_dense):
            keep.update(sorted(table, key=lambda k: (-table[k], k))[:3])
        base3.append(len(keep))
    import statistics as st
    print(f"\nqueries losing ALL gold to pruning: {len(lost_queries)}")
    print(f"recovered at N=4: {recovered_at[4]}  N=5: {recovered_at[5]}  N=6: {recovered_at[6]}")
    print(f"mean sessions kept: N=3 {st.median(base3):.0f} | "
          f"N=4 {st.median(infl[4]):.0f} | N=5 {st.median(infl[5]):.0f} | "
          f"N=6 {st.median(infl[6]):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
