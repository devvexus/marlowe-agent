"""Split the NEI failures by whether gold was actually injected."""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from reach_pools import load_pools  # noqa: E402

rows = json.loads((REPO / "runs/session-m0c-n/qa-rows.json").read_text(encoding="utf-8"))
pools, _ = load_pools(Path(REPO / "runs/session-m0c-n/qa-holding-run/heldout"))


def gi(q, n):
    p = pools.get(q)
    if p is None:
        return None
    cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                 key=lambda i: p.candidates[i].fusion_rank)
    g = [bool(c.is_gold) for c in p.candidates]
    return any(g[i] for i in cur[:max(n, 0)])


nei = [r for r in rows
       if r["answer"] and "not_enough_information" in r["answer"].lower().replace(" ", "")]
c: Counter = Counter()
for r in nei:
    g = gi(r["query_id"], r["n_memories"])
    c["gold-WAS-injected" if g else ("gold-absent" if g is False else "unknown")] += 1
    c[f"cat {r['category']}"] += 1
print("NEI total:", len(nei))
for k, v in sorted(c.items()):
    print(f"  {k:34} {v}")
