"""Inspect one query's slate rows: logits, narrowing membership, gold flags."""
import json
import io
import sys

q = sys.argv[1]
path = sys.argv[2]
rows = [json.loads(l) for l in io.open(path, encoding="utf-8") if f'"query_id":"{q}"' in l]
slate = [r for r in rows if r.get("rerank_score") is not None]
print("rows", len(rows), "slate", len(slate))
srt = sorted(slate, key=lambda r: (-r["rerank_score"], r["memory_id"]))
for i, r in enumerate(srt[:14], 1):
    print(f"{i:>2} {r['memory_id'][:16]:16} logit {r['rerank_score']:9.4f}  fusion {r.get('fusion_rank')}")
