"""Full-text adjudication view for the 4 suspected label-artifact cases."""
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from reach_pools import load_pools, turn_texts  # noqa: E402

run = Path(sys.argv[1])
pools, _ = load_pools(run)
TEXTS = turn_texts()
split = json.load(open(REPO / "tools" / "split.json", encoding="utf-8"))
raw = json.loads(open(REPO / split["corpus_path"], encoding="utf-8").read())
inst = {i["question_id"]: i for i in raw}

for q in ["dc439ea3", "65240037", "7e00a6cb", "gpt4_4929293b"]:
    p = pools[q]
    x = inst[q]
    cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                 key=lambda i: p.candidates[i].fusion_rank)
    g = [bool(c.is_gold) for c in p.candidates]
    golds_in_narrow = [i for i in cur if g[i]]
    fused_gold_rank = min(cur.index(i) + 1 for i in golds_in_narrow)
    print("=" * 100)
    print(f"[{q}] {x['question_type']}")
    print("Q:", x["question"][:200])
    print("CORPUS ANSWER:", repr(str(x["answer"])[:200]))
    print(f"(labeled-gold fused rank: {fused_gold_rank})")
    for r in (1, 2, 3):
        t = p.candidates[cur[r - 1]]
        w = TEXTS.get(q, {}).get(t.turn_id) or ""
        flag = "GOLD-LABELED" if g[cur[r - 1]] else "unflagged"
        print(f"\n--- rank {r} [{flag}] ({len(w.split())}w):")
        print("   ", w[:600].replace("\n", " ⏎ "))
    print()
