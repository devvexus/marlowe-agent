"""QA TESTER -- the official LongMemEval metric, finally measured.

The pipeline answers each question using ONLY the memories our system actually injected on the
wire, then a judge model grades the answer against the corpus gold. This is the benchmark's own
criterion (answer accuracy under an LLM judge), which every R@k number in this project has been a
proxy for.

Model: OpenRouter `stealth/ox-alpha` for BOTH answering and judging (temperature 0).
Responses are cached to disk keyed by prompt hash, so re-runs never re-bill.

    python tools/qa_tester.py --run runs/session-m0c-n/qa-holding-run/heldout \
        [--limit 5] [--concurrency 4]

Requires OPENROUTER_API_KEY in the environment.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools  # noqa: E402
from marlowe_eval.datasets import longmemeval  # noqa: E402

API_BASE = "https://openrouter.ai/api/v1"
MODEL = "stealth/ox-alpha"

ANSWER_SYSTEM = (
    "You answer questions about the user's life using ONLY the provided memories from past "
    "conversations. If the memories contain the needed information, give a short, direct "
    "answer. If they do not contain it, reply exactly: NOT_ENOUGH_INFORMATION. Do not guess."
)

JUDGE_SYSTEM = (
    "You are a strict grader. Compare the model's answer against the ground-truth answer for "
    "the question. They are correct if they convey the same key fact(s); wording, units and "
    "extra detail do not matter. Respond with ONLY this JSON: {\"correct\": true|false}"
)


def iter_ndjson(path: Path):
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def chat(api_key: str, messages: list[dict], cache: dict, cache_key: str,
         max_tokens: int = 300) -> str:
    if cache_key in cache:
        return cache[cache_key]
    # ox-alpha is a REASONING model: hidden reasoning tokens count against max_tokens, so a
    # small cap returns content=None with finish_reason="length". Budget generously and
    # double once if we still get length-truncated silence.
    attempt_tokens = max_tokens
    last_err = None
    for attempt in range(5):
        body = json.dumps({
            "model": MODEL,
            "messages": messages,
            "temperature": 0,
            "max_tokens": attempt_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            text = msg.get("content")
            if text is None and data["choices"][0].get("finish_reason") == "length":
                attempt_tokens *= 4
                continue
            if text is None:
                text = ""
            cache[cache_key] = text
            return text
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise SystemExit(f"OpenRouter call failed after retries: {last_err}")


def parse_judge(raw: str | None) -> bool | None:
    if not raw:
        return None
    s = raw.strip()
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1:
        try:
            return bool(json.loads(s[i:j + 1]).get("correct"))
        except Exception:
            pass
    low = s.lower()
    if '"correct": true' in low or low.startswith("true"):
        return True
    if '"correct": false' in low or low.startswith("false"):
        return False
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None, help="smoke-test on N queries")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--cache", type=Path,
                    default=REPO / "runs" / "session-m0c-n" / "qa-cache.json")
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set.")

    # â”€â”€ wire records: what did we ACTUALLY inject? â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    injections: dict[str, list[str]] = {}
    for frame in iter_ndjson(args.run / "run.jsonl"):
        if frame.get("op") != "answer":
            continue
        body = frame.get("body") or {}
        retr = body.get("retrieval") or {}
        qid = retr.get("query_id") or body.get("query_id")
        contents = [i.get("content") or "" for i in retr.get("injected", [])]
        if qid:
            injections[qid] = [c for c in contents if c]

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    cases = {c.query_id: c for c in corpus.cases}

    qids = [q for q in sorted(injections) if q in cases and not cases[q].is_abstention]
    if args.limit:
        qids = qids[:args.limit]
    print(f"queries with wire records: {len(injections)}; testing {len(qids)} "
          f"(model {MODEL})")

    cache: dict = {}
    if args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))

    def one(qid: str) -> dict:
        case = cases[qid]
        mems = injections.get(qid, [])
        mem_block = "\n".join(f"- {m}" for m in mems) if mems else "(none)"
        user = f"MEMORIES:\n{mem_block}\n\nQUESTION: {case.question}\nAnswer:"
        ans_raw = chat(api_key,
                       [{"role": "system", "content": ANSWER_SYSTEM},
                        {"role": "user", "content": user}],
                       cache, "ans:" + hashlib.sha256(user.encode()).hexdigest(),
                       max_tokens=2500)
        judge_user = (f"Question: {case.question}\nGround-truth answer: {case.gold_answer}\n"
                      f"Model answer: {ans_raw}")
        verdict = chat(api_key,
                       [{"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": judge_user}],
                       cache, "jud:" + hashlib.sha256(judge_user.encode()).hexdigest(),
                       max_tokens=1200)
        correct = parse_judge(verdict)
        return {"query_id": qid, "category": case.category, "n_memories": len(mems),
                "answer": ans_raw[:200], "correct": correct,
                "judge_raw": verdict[:80]}

    rows = []
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(one, q) for q in qids]
        done = 0
        for fut in cf.as_completed(futures):
            rows.append(fut.result())
            done += 1
            if done % 25 == 0 or done == len(qids):
                print(f"  {done}/{len(qids)}")

    args.cache.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    n = len(rows)
    judged = [r for r in rows if r["correct"] is not None]
    correct = sum(1 for r in judged if r["correct"])
    empty = sum(1 for r in rows if r["n_memories"] == 0)
    print("\n==================== QA RESULT ====================")
    print(f"questions graded          : {len(judged)}/{n} (unparseable judgments excluded)")
    print(f"answer accuracy           : {correct}/{len(judged)} = "
          f"{correct / max(len(judged), 1):.4f}")
    print(f"queries with NO injection : {empty}")
    cats: dict[str, list[dict]] = {}
    for r in judged:
        cats.setdefault(r["category"], []).append(r)
    for cat, rs in sorted(cats.items()):
        c = sum(1 for r in rs if r["correct"])
        print(f"  {cat:28} {c}/{len(rs)} = {c/len(rs):.4f}")
    args.cache.with_name("qa-rows.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
