"""Show a query's gold turn and its in-session neighbours (the vocabulary-bridge check)."""
import io
import json
import sys

q = sys.argv[1]
needle = sys.argv[2] if len(sys.argv) > 2 else None
split = json.load(open(r"tools/split.json", encoding="utf-8"))
raw = json.loads(io.open(split["corpus_path"], encoding="utf-8").read())
inst = {i["question_id"]: i for i in raw}[q]
print("Q:", inst["question"][:110])
print("A:", repr(str(inst["answer"])[:90]))
for sid, sess in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
    for i, t in enumerate(sess):
        if needle and needle.lower() not in t["content"].lower():
            continue
        print(f"\n== HIT [{sid} t{i}] role={t['role']} ({len(t['content'].split())} words):")
        print("  ", repr(t["content"][:220]))
        for j in range(max(0, i - 1), min(len(sess), i + 2)):
            tag = ">>" if j == i else "  "
            print(f"  {tag} ctx[{j}] {sess[j]['role']}: {sess[j]['content'][:130]!r}")
