"""Session G — offline reconstruction of the held-out candidate pools, plus the fidelity gate.

Session F's scoring run dumped every scored candidate to
`runs/session-f/heldout/scored-candidates.ndjson`. This module rebuilds the per-query pools from
that dump and re-attaches the one thing the harness discards: **which internal LongMemEval session
each candidate turn came from**, and that session's observation date.

The harness flattens a case's ~50 haystack sessions into one `SessionHistory` whose `session_id`
is the question id (see `datasets/longmemeval.py`), so session structure survives only inside
`turn_id`. Rather than parse it back out of a string, the mapping is rebuilt from the raw corpus,
which is authoritative. Parsing `f"{sid}-{t_idx}"` in reverse happens to be unambiguous here --
no released session id contains a hyphen, checked -- but that is a property of the data today and
not of the format.

Nothing here re-ranks or re-scores. It reproduces Session F exactly, and refuses to hand out pools
if it cannot.

**Registered gate.** `runs/session-g/PREREGISTRATION.json -> reconstruction_fidelity_gate`. If the
rebuilt pools do not reproduce Session F's published held-out top-1 rates to four decimal places,
every downstream arm reports NOT MEASURED. An arm delta computed against a wrong baseline is worse
than no number, because it looks like one.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.datasets import timeparse  # noqa: E402
from marlowe_eval.metrics.records import Attributor  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
PREREG_PATH = REPO / "runs" / "session-g" / "PREREGISTRATION.json"
DEFAULT_RUN = REPO / "runs" / "session-f" / "heldout"


@dataclass(frozen=True)
class Candidate:
    """One scored candidate, with its session provenance re-attached."""

    lexical_bm25: float
    dense_cosine: float
    score: float
    margin: float
    passes: bool
    is_gold: bool
    turn_id: str | None
    sid: str | None
    """The internal LongMemEval haystack session id. None if unattributable."""
    session_index: int | None
    session_at_ms: int | None
    """The session's observation date -- `haystack_dates`, the first of arm 4's three dates."""
    turn_index: int | None
    occurred_at_ms: int | None


@dataclass(frozen=True)
class Pool:
    """One query's full candidate pool, in the dump's own row order.

    Row order matters and is preserved deliberately: the gate's final tiebreak is entry-id
    ascending, and `analyze_cue_overlap.py` gets that for free from a *stable* argsort over the
    dump's order. A reconstruction that sorted or grouped the rows would reproduce the same scores
    and a different top-1.
    """

    query_id: str
    question: str
    category: str
    ask_at_ms: int
    candidates: tuple[Candidate, ...]

    def array(self, field: str) -> np.ndarray:
        return np.array([getattr(c, field) for c in self.candidates])

    @property
    def gold(self) -> np.ndarray:
        return np.array([c.is_gold for c in self.candidates])


def iter_ndjson(path: Path):
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def order_of(scores: np.ndarray) -> np.ndarray:
    """Descending rank order for a single score.

    Stable, so ties keep the dump's own row order -- the gate's final tiebreak. Identical to
    `analyze_cue_overlap.order_of`; duplicated rather than imported because that file is a script
    with a `main()`, and importing it would run argument parsing.
    """
    return np.argsort(-scores, kind="stable")


def hit(order: np.ndarray, gold: np.ndarray, k: int) -> bool:
    """Does the top-k intersect gold? Same meaning as every session since C."""
    return bool(set(order[:k].tolist()) & set(np.flatnonzero(gold).tolist()))


def _session_provenance(corpus_path: Path) -> dict[str, dict[str, tuple]]:
    """query_id -> turn_id -> (sid, session_index, session_at_ms, turn_index, occurred_at_ms).

    Rebuilt from the RAW corpus rather than from the harness `Corpus`, because the adapter
    flattens haystack sessions and the internal boundary does not survive into `SessionHistory`.
    The turn_id construction mirrors `longmemeval.py` exactly -- if that changes, this must too,
    and the fidelity gate is what would catch it.
    """
    raw = json.loads(io.open(corpus_path, encoding="utf-8").read())
    out: dict[str, dict[str, tuple]] = {}
    for inst in raw:
        qid = str(inst["question_id"])
        per_turn: dict[str, tuple] = {}
        for s_idx, (sid, session, date) in enumerate(
            zip(inst["haystack_session_ids"], inst["haystack_sessions"], inst["haystack_dates"])
        ):
            session_at = timeparse.parse(date, dataset="longmemeval", where=f"{qid}[{s_idx}]")
            for t_idx, _turn in enumerate(session):
                per_turn[f"{sid}-{t_idx}"] = (
                    sid,
                    s_idx,
                    session_at,
                    t_idx,
                    session_at + t_idx * 1000,
                )
        out[qid] = per_turn
    return out


def load_pools(run_dir: Path = DEFAULT_RUN) -> tuple[dict[str, Pool], dict]:
    """Rebuild every held-out pool. Returns (pools, provenance_stats)."""
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    corpus_path = REPO / split["corpus_path"]
    corpus = longmemeval.load(corpus_path)
    gold_map = corpus.gold_map()
    cases = {c.query_id: c for c in corpus.cases}
    provenance = _session_provenance(corpus_path)

    attributor = Attributor()
    for frame in iter_ndjson(run_dir / "run.jsonl"):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))

    rows: dict[str, list[Candidate]] = {}
    unattributable = 0
    no_provenance = 0
    for row in iter_ndjson(run_dir / "scored-candidates.ndjson"):
        # Refused by name, never defaulted -- a pre-v4 dump carries no `margin`, and falling back
        # to `score` alone would silently compare a different ordering. Same refusal, same reason,
        # as `analyze_cue_overlap.py`.
        for required in ("calibrated_precision", "score", "margin", "passes", "lexical_bm25", "dense_cosine"):
            if required not in row:
                raise SystemExit(
                    f"{run_dir / 'scored-candidates.ndjson'} has no {required!r}. This is a "
                    "pre-v4 dump, or a --fit-mode run. The pools cannot be reconstructed from it."
                )
        qid = row["query_id"]
        attribution, turn_id = attributor.attribute(row["memory_id"], gold_map.get(qid, frozenset()))
        if turn_id is None:
            unattributable += 1
        prov = provenance.get(qid, {}).get(turn_id) if turn_id else None
        if turn_id is not None and prov is None:
            no_provenance += 1
        rows.setdefault(qid, []).append(
            Candidate(
                lexical_bm25=row["lexical_bm25"],
                dense_cosine=row["dense_cosine"],
                score=row["score"],
                margin=row["margin"],
                passes=bool(row["passes"]),
                is_gold=(attribution == "gold"),
                turn_id=turn_id,
                sid=prov[0] if prov else None,
                session_index=prov[1] if prov else None,
                session_at_ms=prov[2] if prov else None,
                turn_index=prov[3] if prov else None,
                occurred_at_ms=prov[4] if prov else None,
            )
        )

    pools: dict[str, Pool] = {}
    for qid, cands in rows.items():
        case = cases.get(qid)
        if case is None or case.is_abstention:
            continue
        if not any(c.is_gold for c in cands):
            # Same exclusion as every session since C: a case with no surviving gold contributes
            # no signal to a top-k intersection. STATE.md is emphatic that this is a MISS in the
            # re-based table, not an exclusion -- but the rate this module reproduces is the raw
            # one, so the exclusion is the behaviour being matched.
            continue
        pools[qid] = Pool(
            query_id=qid,
            question=case.question,
            category=case.category,
            ask_at_ms=case.ask_at_ms,
            candidates=tuple(cands),
        )

    stats = {
        "pools": len(pools),
        "candidates": sum(len(p.candidates) for p in pools.values()),
        "unattributable_rows": unattributable,
        "attributed_but_no_session_provenance": no_provenance,
        "sessions_seen": len({(p.query_id, c.sid) for p in pools.values() for c in p.candidates if c.sid}),
    }
    return pools, stats


def turn_texts() -> dict[str, dict[str, str]]:
    """query_id -> turn_id -> text. The pools carry scores, not text.

    Arms 2, 3 and the cross-encoder all need the text a candidate was scored from, and the dump
    stores only `memory_id`. Rebuilt from the raw corpus for the same reason the session
    provenance is.
    """
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    out: dict[str, dict[str, str]] = {}
    for inst in raw:
        per: dict[str, str] = {}
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                per[f"{sid}-{t_idx}"] = str(turn.get("content", ""))
        out[str(inst["question_id"])] = per
    return out


def gold_answers() -> dict[str, str | None]:
    """query_id -> the released gold answer. Used ONLY for arm 3's oracle ceiling."""
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    corpus = longmemeval.load(REPO / split["corpus_path"])
    return {c.query_id: c.gold_answer for c in corpus.cases}


def baseline_top1(pools: dict[str, Pool]) -> dict[str, float]:
    """Session F's three headline top-1 rates, recomputed from the rebuilt pools."""
    n = len(pools)
    tally = {"lexical": 0, "dense": 0, "either_oracle": 0}
    for pool in pools.values():
        gold = pool.gold
        lex = hit(order_of(pool.array("lexical_bm25")), gold, 1)
        den = hit(order_of(pool.array("dense_cosine")), gold, 1)
        tally["lexical"] += lex
        tally["dense"] += den
        tally["either_oracle"] += lex or den
    return {k: round(v / n, 4) for k, v in tally.items()}


def fidelity_gate(pools: dict[str, Pool]) -> tuple[bool, dict]:
    """The registered gate. Reproduce Session F or refuse to hand out pools."""
    prereg = json.loads(io.open(PREREG_PATH, encoding="utf-8").read())
    targets = prereg["reconstruction_fidelity_gate"]["targets_read_from_session_f_artifact"]
    measured = baseline_top1(pools)
    checks = {}
    ok = True
    for key in ("lexical_top1", "dense_top1", "either_oracle_top1"):
        name = {"lexical_top1": "lexical", "dense_top1": "dense", "either_oracle_top1": "either_oracle"}[key]
        passed = abs(measured[name] - targets[key]) < 1e-9
        checks[name] = {"target": targets[key], "measured": measured[name], "pass": passed}
        ok = ok and passed
    return ok, {"cases": len(pools), "checks": checks}


def main() -> int:
    pools, stats = load_pools()
    ok, report = fidelity_gate(pools)

    print("Reconstructed held-out pools from runs/session-f/heldout/")
    for k, v in stats.items():
        print(f"  {k:42s} {v}")
    print()
    print(f"Reconstruction fidelity gate over {report['cases']} cases:")
    for name, c in report["checks"].items():
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  {name:14s} target {c['target']:.4f}  measured {c['measured']:.4f}  {mark}")
    print()
    if not ok:
        print("GATE FAILED. Every downstream arm reports NOT MEASURED.")
        return 1
    print("GATE PASSED. The reconstruction reproduces Session F exactly; arms may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
