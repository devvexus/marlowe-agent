"""Adjudicate dc439ea3 properly: does 'Hoop Dance' appear in the fused top-3 or only deeper?"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from reach_pools import load_pools, turn_texts  # noqa: E402

pools, _ = load_pools(Path(REPO / "runs/session-m0c-n/cascade-heldout-cuda-v2/heldout"))
T = turn_texts()
p = pools["dc439ea3"]
cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
             key=lambda i: p.candidates[i].fusion_rank)

for r in (1, 2, 3):
    t = p.candidates[cur[r - 1]]
    w = T.get("dc439ea3", {}).get(t.turn_id) or ""
    print(f"rank {r}: 'hoop' present: {'hoop' in w.lower()}   ({len(w.split())} words)")

golds_in_slate = [i for i in cur if p.candidates[i].is_gold]
for gi in golds_in_slate[:3]:
    w = T.get("dc439ea3", {}).get(p.candidates[gi].turn_id) or ""
    fr = p.candidates[gi].fusion_rank + 1 if p.candidates[gi].fusion_rank is not None else -1
    print(f"gold@fused{fr}: 'hoop' present: {'hoop' in w.lower()}  ({len(w.split())}w)")
    print("   ", w[:200].replace("\n", " | "))

# where does Hoop Dance actually live in this session?
hits = [(tid, txt) for tid, txt in T.get("dc439ea3", {}).items() if "hoop" in txt.lower()]
print(f"\nturns in the whole case containing 'hoop': {len(hits)}")
for tid, txt in hits[:2]:
    print("   ", repr(txt[:180].replace("\n", " | ")))
