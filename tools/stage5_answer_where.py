"""Among stage-5 failures: does the corpus ANSWER STRING appear inside any fused top-3 turn?"""
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

hit_unflagged = miss = 0
for q, p in sorted(pools.items()):
    cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                 key=lambda i: p.candidates[i].fusion_rank)
    g = [bool(c.is_gold) for c in p.candidates]
    golds_in_narrow = [i for i in cur if g[i]]
    if not golds_in_narrow:
        continue
    if min(cur.index(i) + 1 for i in golds_in_narrow) <= 3:
        continue
    ans = str(inst.get(q, {}).get("answer", "")).lower().strip()
    ans_tokens = [t for t in "".join(ch if ch.isalnum() else " " for ch in ans).split() if len(t) > 2]
    found = None
    for r in (1, 2, 3):
        t = p.candidates[cur[r - 1]]
        w = (TEXTS.get(q, {}).get(t.turn_id) or "").lower()
        if g[cur[r - 1]]:
            continue  # flagged would have counted already
        overlap = sum(1 for tok in set(ans_tokens) if tok in w) if ans_tokens else 0
        if ans_tokens and overlap >= max(1, int(0.6 * len(set(ans_tokens)))):
            found = (r, round(overlap / len(set(ans_tokens)), 2))
            break
    if found:
        hit_unflagged += 1
        print(f"{q}: answer-content present at fused rank {found[0]} "
              f"(token overlap {found[1]:.0%}) on an UNFLAGGED turn")
    else:
        miss += 1
print(f"\nanswer-content sitting in our top-3 on unflagged turns: {hit_unflagged}/16")
print(f"true misses (no answer content anywhere in top-3): {miss}/16")
