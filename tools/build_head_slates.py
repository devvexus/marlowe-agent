"""Build the offline slate dataset the head-separability reachability checks read.

One record per query: the question, the ten reranked candidates in the SHIPPED order, their
texts, roles, word-piece lengths, shipped rerank logits and gold flags. Everything the two named
candidates -- a relevance-fitted confidence signal, and set-wise/listwise scoring -- need, without
re-running the binary.

**The slate is not re-derived here.** It is read from Session J's per-graph score dump, the same
file whose offline reconstruction reproduced the binary's held-out R@1 exactly (0.6725 = 0.6725,
Session K's second-implementation check). This script re-asserts that equality on load and refuses
to write if it fails -- a dataset that silently describes a different ranking is the defect that
cost Session K a full wrong curve.

Applies nothing. Writes runs/session-m0c/slates-{split}.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SPLIT_PATH = REPO / "tools" / "split.json"
SCORES = REPO / "runs" / "session-j" / "rerank-scores-{split}-L-2-v2-ft-session-j-f32-seq256.json"
OUT = REPO / "runs" / "session-m0c" / "slates-{split}.json"

# The canonical numbers this dataset must reproduce, from runs/session-k/RESULT.md and
# runs/session-j/arm7-*.json cell 7a_control. Hard-coded so a drifting input is caught here.
CANONICAL_R_AT_1 = {"fit": 0.7555, "heldout": 0.6725}
CANONICAL_N = 229
PINNED_DIGEST = "9c222dac4315cfd2f33f2e865bb651a7a16bf532c11e55b7fb1a43bb041880c0"


def shipped_slate_order(scores: np.ndarray) -> np.ndarray:
    """Descending rerank logit, stable. Within a fully-reranked depth-10 slate this is exactly
    `analyze_cue_overlap.shipped_order` restricted to the reranked prefix: `survived` is true for
    all ten, no `rerank` is NaN, so the `score`/`margin` levels below never arbitrate."""
    return np.argsort(-scores, kind="stable")


def load_corpus_text(corpus_path: Path, wanted: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    """turn_id -> text, and query_id -> question. `turn_id` is `f"{session_id}-{turn_index}"`,
    exactly as eval/src/marlowe_eval/datasets/longmemeval.py:134 builds it. That construction is
    mirrored rather than imported because importing the loader parses all 500 cases into Turn
    objects, which is minutes and gigabytes for a mapping this script uses twice."""
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    questions: dict[str, str] = {}
    conflicts = 0
    for inst in raw:
        questions[str(inst["question_id"])] = str(inst["question"])
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                tid = f"{sid}-{t_idx}"
                if tid not in wanted:
                    continue
                content = str(turn["content"])
                if tid in texts and texts[tid] != content:
                    conflicts += 1
                texts[tid] = content
    if conflicts:
        raise SystemExit(
            f"REFUSING: {conflicts} turn_ids carry different text in different cases. The "
            f"turn_id -> text mapping is not a function on this corpus and every downstream "
            f"join would be silently ambiguous."
        )
    return texts, questions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--splits", nargs="+", default=["fit", "heldout"])
    args = ap.parse_args()

    split_meta = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus_path = REPO / split_meta["corpus_path"]
    if not corpus_path.exists():
        raise SystemExit(f"REFUSING: corpus absent at {corpus_path}. data/ is gitignored; run fetch.")

    loaded = {}
    wanted: set[str] = set()
    for split in args.splits:
        p = Path(str(SCORES).format(split=split))
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["digest"] != PINNED_DIGEST:
            raise SystemExit(
                f"REFUSING: {p.name} carries digest {d['digest'][:8]}..., pinned is "
                f"{PINNED_DIGEST[:8]}.... This is a different graph."
            )
        if d["split"] != split or d["seq_len"] != 256 or d["precision"] != "f32":
            raise SystemExit(f"REFUSING: {p.name} is not the shipped configuration.")
        loaded[split] = d
        for r in d["rows"].values():
            wanted.update(r["turn_ids"])

    print(f"joining text for {len(wanted)} distinct turn_ids from {corpus_path.name} "
          f"({corpus_path.stat().st_size / 1e6:.0f} MB) ...")
    texts, questions = load_corpus_text(corpus_path, wanted)
    missing = wanted - set(texts)
    if missing:
        raise SystemExit(f"REFUSING: {len(missing)} slate turn_ids absent from the corpus, "
                         f"e.g. {sorted(missing)[:5]}")
    print(f"  resolved {len(texts)} turn texts, {len(questions)} questions")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    for split, d in loaded.items():
        records = []
        hits = 0
        for qid, r in d["rows"].items():
            scores = np.asarray(r["scores"], dtype=float)
            order = shipped_slate_order(scores)
            gold = np.asarray(r["gold"], dtype=bool)
            hits += bool(gold[order[0]])
            records.append({
                "query_id": qid,
                "category": r["category"],
                "question": questions[qid],
                "gold_in_slate": bool(r["gold_in_slate"]),
                # every parallel array below is stored in SHIPPED ORDER, rank 0 first
                "turn_ids": [r["turn_ids"][i] for i in order],
                "texts": [texts[r["turn_ids"][i]] for i in order],
                "roles": [r["roles"][i] for i in order],
                "wordpieces": [int(r["wordpieces"][i]) for i in order],
                "rerank_scores": [float(scores[i]) for i in order],
                "gold": [bool(gold[i]) for i in order],
                "correct": bool(gold[order[0]]),
                "margin": float(scores[order[0]] - scores[order[1]]),
            })
        r_at_1 = hits / len(records)
        want = CANONICAL_R_AT_1[split]
        if len(records) != CANONICAL_N or round(r_at_1, 4) != want:
            raise SystemExit(
                f"REFUSING to write {split}: reconstructed R@1 {r_at_1:.4f} on n={len(records)}, "
                f"canonical is {want} on n={CANONICAL_N}. The slate this dataset describes is not "
                f"the shipped ranking."
            )
        out = Path(str(OUT).format(split=split))
        out.write_text(json.dumps({
            "_what": "shipped depth-10 slates in shipped order, with gold, for offline head work",
            "_reproduces": f"R@1 {r_at_1:.4f} on n={len(records)}, checked on write",
            "split": split,
            "digest": PINNED_DIGEST,
            "configuration": "ms-marco-MiniLM-L-2-v2-ft-session-j (f32, seq 256, depth 10)",
            "n": len(records),
            "r_at_1": round(r_at_1, 4),
            "records": records,
        }, indent=1) + "\n", encoding="utf-8")
        print(f"  {split}: n={len(records)} R@1={r_at_1:.4f} (canonical {want}) -> "
              f"{out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
