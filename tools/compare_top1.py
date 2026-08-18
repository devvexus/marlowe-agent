"""Does a change to the retrieval stack move a DECISION?

**The question this answers is ADR-029's, not a tolerance's.** A numerical difference between two
providers, two graphs or two sequence caps is interesting only if it changes what the system picks.
ADR-029 met a byte-identity wall on the cross-encoder, declined to widen the gate, and amended the
requirement to *ranking equivalence* after measuring it -- 0 of 229 slates reordered. This is that
measurement, factored out so the next one does not get re-implemented by hand.

Reads two `scored-candidates.ndjson` dumps produced by `score_longmemeval.py`, groups by
`query_id`, ranks each query's candidates by `(rerank_score, score)`, takes the top 1, and
attributes it to a session against the corpus's `answer_session_ids`.

# The control is not optional and it is the point

A comparison of two runs that were secretly the same run reports **perfect agreement**, which is
also what a genuine null result looks like. The two are indistinguishable from the headline alone.
So this always prints how many candidate rows actually changed their `dense_cosine` and their
`score`: if the inputs did not move, the output saying "nothing moved" is vacuous and the run has
to be thrown away rather than believed. That failure has already happened in this project -- a
scoring pass that measured `MAX_SEQ_LEN` 8192 while its directory was named 1024.

# What it deliberately does not do

It does not open `summary.json` and it does not recompute R@1. Session-level top-1 from the dump is
a *paired* measurement on two runs taken minutes apart through one code path, which is what makes
it evidence about the change; a published headline from another day is a different system and
comparing against it is the carried-measurement error `CLAUDE.md` logs four instances of.

    python tools/compare_top1.py --baseline runs/a/fit --treatment runs/b/fit \\
        --label-baseline "CPU" --label-treatment "CUDA" --out runs/b/top1-comparison.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.metrics.records import Attributor  # noqa: E402

CORPUS = REPO / "data" / "longmemeval_s_cleaned.json"


def iter_ndjson(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def answer_sessions() -> dict[str, frozenset[str]]:
    """query_id -> the session ids that contain the answer, from the released corpus.

    Read from the raw release rather than from `Corpus`, because the harness's model carries
    `gold_turn_ids` and deliberately does not carry `answer_session_ids` -- session-level top-1 is
    a coarser reading than the harness's own and belongs to the caller, not to the scoreboard.
    """
    raw = json.loads(CORPUS.read_text(encoding="utf-8"))
    return {c["question_id"]: frozenset(c["answer_session_ids"]) for c in raw}


def session_of_turn(turn_id: str) -> str:
    """`<haystack_session_id>-<turn_index>` -> `<haystack_session_id>`.

    The adapter builds turn ids as `f"{sid}-{t_idx}"` (`longmemeval.py`), and haystack session ids
    themselves contain hyphens (`sharegpt_yywfIrx_0`), so only the LAST segment may be stripped.
    """
    return turn_id.rsplit("-", 1)[0]


def attributor_for(run_dir: Path) -> Attributor:
    """Built from the run's own transcript, exactly as `score_longmemeval.py` builds it.

    The memory_id -> turn_id mapping comes from the section 4.6 ingest response, never from
    parsing an id: an id's shape is the implementation's business and consolidation can produce
    one that no ingest ever returned.
    """
    a = Attributor()
    transcript = run_dir / "run.jsonl"
    for frame in iter_ndjson(transcript):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                a.record(written["turn_id"], list(written["memory_ids"]))
    return a


def rank_key(row: dict) -> tuple:
    """`(rerank_score, score)`, descending, with a deterministic final tie-break.

    Reranked candidates outrank unreranked ones: a `None` `rerank_score` means the candidate never
    reached the cross-encoder. `memory_id` breaks exact ties so the comparator itself cannot
    manufacture a difference out of dict ordering -- the count of queries decided by that
    tie-break is reported, because a comparison resting on it would be reporting its own sort.
    """
    rr = row.get("rerank_score")
    return (1 if rr is not None else 0, rr if rr is not None else 0.0, row["score"], row["memory_id"])


def top1(dump: Path) -> tuple[dict[str, dict], int]:
    """query_id -> the winning row, plus how many queries were decided by the id tie-break."""
    by_query: dict[str, list[dict]] = defaultdict(list)
    for row in iter_ndjson(dump):
        by_query[row["query_id"]].append(row)

    winners: dict[str, dict] = {}
    tie_decided = 0
    for qid, rows in by_query.items():
        rows.sort(key=rank_key, reverse=True)
        winners[qid] = rows[0]
        if len(rows) > 1 and rank_key(rows[0])[:3] == rank_key(rows[1])[:3]:
            tie_decided += 1
    return winners, tie_decided


def slate_agreement(base_dump: Path, treat_dump: Path, depth: int = 10) -> dict:
    """How many queries have a byte-identical top-`depth` ORDER.

    **ADR-029's actual gate, and it is stronger than the top-1 verdict.** That ADR replaced
    cross-provider byte-identity with *ranking equivalence, top-10 order vs CPU* and reported 0 of
    229 slates reordered. Top-1 alone can be identical while everything under it churns, which
    would say the perturbation is reaching decisions and happening not to reach the winning one
    yet. Reported beside the verdict, never instead of it.
    """
    def slates(dump: Path) -> dict[str, list[str]]:
        by_query: dict[str, list[dict]] = defaultdict(list)
        for row in iter_ndjson(dump):
            by_query[row["query_id"]].append(row)
        out = {}
        for qid, rows in by_query.items():
            rows.sort(key=rank_key, reverse=True)
            out[qid] = [r["memory_id"] for r in rows[:depth]]
        return out

    b, t = slates(base_dump), slates(treat_dump)
    shared = sorted(b.keys() & t.keys())
    identical_order = sum(1 for q in shared if b[q] == t[q])
    identical_set = sum(1 for q in shared if set(b[q]) == set(t[q]))
    return {
        "depth": depth,
        "queries": len(shared),
        "identical_order": identical_order,
        "reordered": len(shared) - identical_order,
        "identical_membership": identical_set,
        "different_membership": len(shared) - identical_set,
    }


def mcnemar_exact_two_sided(b: int, c: int) -> float:
    """Exact two-sided McNemar over the discordant pairs.

    The binomial test with p = 0.5 on `b` successes out of `n = b + c`, doubled. Exact rather than
    chi-square with continuity correction, because the discordant count here is expected to be
    single digits and the asymptotic test is not valid there. `n = 0` is `1.0`: no discordant pairs
    is no evidence of a difference, which is a different statement from evidence of no difference.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5**n)
    return min(1.0, 2.0 * tail)


def feature_movement(base: Path, treat: Path) -> dict:
    """**The control.** How many candidate rows actually changed, joined on (query_id, memory_id).

    Reported for `dense_cosine` (the embedder's own output) and for `score` (the fused value the
    ranking reads). A change to the embedder that moves neither did not run.
    """
    base_rows = {(r["query_id"], r["memory_id"]): r for r in iter_ndjson(base)}
    treat_rows = {(r["query_id"], r["memory_id"]): r for r in iter_ndjson(treat)}
    shared = base_rows.keys() & treat_rows.keys()

    moved_cos = moved_score = 0
    max_cos_delta = 0.0
    max_score_delta = 0.0
    for key in shared:
        b, t = base_rows[key], treat_rows[key]
        dc = abs(b["dense_cosine"] - t["dense_cosine"])
        ds = abs(b["score"] - t["score"])
        if dc != 0.0:
            moved_cos += 1
        if ds != 0.0:
            moved_score += 1
        max_cos_delta = max(max_cos_delta, dc)
        max_score_delta = max(max_score_delta, ds)

    return {
        "rows_baseline": len(base_rows),
        "rows_treatment": len(treat_rows),
        "rows_shared": len(shared),
        "rows_only_in_baseline": len(base_rows) - len(shared),
        "rows_only_in_treatment": len(treat_rows) - len(shared),
        "rows_with_changed_dense_cosine": moved_cos,
        "rows_with_changed_score": moved_score,
        "fraction_dense_cosine_moved": (moved_cos / len(shared)) if shared else 0.0,
        "max_abs_dense_cosine_delta": max_cos_delta,
        "max_abs_score_delta": max_score_delta,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", required=True, help="run dir holding scored-candidates.ndjson + run.jsonl")
    ap.add_argument("--treatment", required=True)
    ap.add_argument("--label-baseline", default="baseline")
    ap.add_argument("--label-treatment", default="treatment")
    ap.add_argument("--out", default=None, help="write the full result as JSON here")
    args = ap.parse_args()

    base_dir, treat_dir = Path(args.baseline), Path(args.treatment)
    gold = answer_sessions()

    base_win, base_ties = top1(base_dir / "scored-candidates.ndjson")
    treat_win, treat_ties = top1(treat_dir / "scored-candidates.ndjson")
    base_attr, treat_attr = attributor_for(base_dir), attributor_for(treat_dir)

    shared_q = sorted(base_win.keys() & treat_win.keys())

    def pick(win: dict, attr: Attributor, qid: str) -> tuple[str, str | None, bool | None]:
        row = win[qid]
        turn = attr.turn_of(row["memory_id"])
        if turn is None:
            # Consolidation can produce an id no ingest returned. Unattributable is a real answer
            # and is counted on its own line rather than scored as wrong.
            return row["memory_id"], None, None
        sess = session_of_turn(turn)
        return row["memory_id"], sess, sess in gold.get(qid, frozenset())

    identical = gained = lost = 0
    unattributable = 0
    base_correct = treat_correct = 0
    moved: list[dict] = []
    for qid in shared_q:
        bm, bs, bc = pick(base_win, base_attr, qid)
        tm, ts, tc = pick(treat_win, treat_attr, qid)
        if bc is None or tc is None:
            unattributable += 1
            continue
        if bm == tm:
            identical += 1
        base_correct += int(bc)
        treat_correct += int(tc)
        if bc and not tc:
            lost += 1
            moved.append({"query_id": qid, "direction": "lost", "from": bm, "to": tm,
                          "from_session": bs, "to_session": ts})
        elif tc and not bc:
            gained += 1
            moved.append({"query_id": qid, "direction": "gained", "from": bm, "to": tm,
                          "from_session": bs, "to_session": ts})
        elif bm != tm:
            moved.append({"query_id": qid, "direction": "same-verdict-different-pick",
                          "from": bm, "to": tm, "from_session": bs, "to_session": ts})

    n = len(shared_q) - unattributable
    control = feature_movement(base_dir / "scored-candidates.ndjson",
                               treat_dir / "scored-candidates.ndjson")
    slates = slate_agreement(base_dir / "scored-candidates.ndjson",
                             treat_dir / "scored-candidates.ndjson")
    p = mcnemar_exact_two_sided(lost, gained)

    result = {
        "baseline": {"label": args.label_baseline, "dir": str(base_dir),
                     "session_top1": base_correct, "of": n,
                     "rate": base_correct / n if n else 0.0,
                     "queries_decided_by_id_tiebreak": base_ties},
        "treatment": {"label": args.label_treatment, "dir": str(treat_dir),
                      "session_top1": treat_correct, "of": n,
                      "rate": treat_correct / n if n else 0.0,
                      "queries_decided_by_id_tiebreak": treat_ties},
        "identical_top1_pick": identical,
        "queries_compared": n,
        "unattributable_top1": unattributable,
        "gained": gained,
        "lost": lost,
        "net": gained - lost,
        "mcnemar_exact_two_sided_p": p,
        "moved": moved,
        "slate_top10": slates,
        "CONTROL": control,
        "control_reading": (
            "VACUOUS -- the inputs did not move, so 'no decision moved' is not a result"
            if control["rows_with_changed_dense_cosine"] == 0
            else f"{control['rows_with_changed_dense_cosine']} of {control['rows_shared']} shared "
                 f"rows changed dense_cosine and {control['rows_with_changed_score']} changed "
                 "score, so the comparison had something to discriminate"
        ),
    }

    print(json.dumps({k: v for k, v in result.items() if k != "moved"}, indent=2))
    if moved:
        print(f"\n{len(moved)} query/queries changed pick:")
        for m in moved:
            print(f"  {m['query_id']}: {m['direction']} {m['from_session']} -> {m['to_session']}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
