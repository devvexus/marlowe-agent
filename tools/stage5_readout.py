"""Print every stage-5 failure: question, type, gold turn, and what beat it. For reading."""
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

for q, p in sorted(pools.items()):
    cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                 key=lambda i: p.candidates[i].fusion_rank)
    g = [bool(c.is_gold) for c in p.candidates]
    golds_in_narrow = [i for i in cur if g[i]]
    if not golds_in_narrow:
        continue
    fused_rank = min(cur.index(i) + 1 for i in golds_in_narrow)
    if fused_rank <= 3:
        continue
    x = inst.get(q, {})
    print("=" * 100)
    print(f"[{q}] type={x.get('question_type')}  gold@fused-rank {fused_rank}")
    print(f"Q: {x.get('question','')[:160]}")
    gi = golds_in_narrow[0]
    gtext = TEXTS.get(q, {}).get(p.candidates[gi].turn_id) or ""
    print(f"GOLD({len(gtext.split())}w): {gtext[:230]!r}")
    for r in (1, 2, 3):
        t = p.candidates[cur[r - 1]]
        w = TEXTS.get(q, {}).get(t.turn_id) or ""
        print(f"  #{r} ({len(w.split())}w): {w[:170]!r}")
