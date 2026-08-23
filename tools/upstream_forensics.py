"""Upstream forensics: where do the ingest+scope (5) and pruning (4) losses actually go?

For each held-out query, compare the corpus's gold turn set against what reached the dump:
  ABSENT-SESSION  no candidate carries that gold turn AND its whole session is absent -> scope/
                  ingestion never admitted it
  ABSENT-TURN     the gold turn's session HAS other candidates present, but the flagged turn
                  itself is missing -> a turn-level exclusion (maturation/tombstone) or
                  attribution gap ate exactly the answering turn
  PRUNED          present in candidates but survived_pruning=false -> pruning dropped it

    python tools/upstream_forensics.py --run runs/session-m0c-n/cascade-heldout-cuda-v2/heldout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools, turn_texts  # noqa: E402
from marlowe_eval.datasets import longmemeval  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    args = ap.parse_args()

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()

    pools, _ = load_pools(args.run)
    texts = turn_texts()

    counts = {"ABSENT-SESSION": [], "ABSENT-TURN": [], "PRUNED": []}
    for q, p in sorted(pools.items()):
        gold_turns = gold_map.get(q, frozenset())
        if not gold_turns:
            continue
        by_turn = {}
        sess_of = {}
        for i, c in enumerate(p.candidates):
            if c.turn_id:
                by_turn[c.turn_id] = i
                if c.sid is not None:
                    sess_of[c.sid] = True
        for gt in sorted(gold_turns):
            if gt in by_turn:
                i = by_turn[gt]
                if not p.candidates[i].survived_pruning:
                    counts["PRUNED"].append((q, gt))
            else:
                # which session does this gold turn belong to? sid is the prefix before last '-N'
                sid = gt.rsplit("-", 1)[0] if "-" in gt else None
                if sid and sid not in sess_of:
                    counts["ABSENT-SESSION"].append((q, gt))
                else:
                    counts["ABSENT-TURN"].append((q, gt))

    for kind, rows in counts.items():
        print(f"{kind}: {len(rows)}")
        for q, gt in rows[:12]:
            t = texts.get(q, {}).get(gt) or ""
            print(f"   {q} {gt} ({len(t.split())}w): {t[:110]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
