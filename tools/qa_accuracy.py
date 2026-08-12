"""QA accuracy — the M0b acceptance criterion that has never been measured.

    python tools/qa_accuracy.py --model marlowe-red:9b --arms none gold k1 k5 k10

`ROADMAP.md` M0b Acceptance: **LongMemEval-S overall / abstention subset >= 90% / >= 85%**. That row
has never had a number against it. Two blockers stacked, and both are now gone:

  1. **No generator.** `crates/marlowe/src/adapter.rs:649` — *"Session A has no generator wired, so
     every answer is an honest abstention"* — hardcodes `answered: false`. Session G recorded QA
     accuracy as dropped because *"no LLM credentials are configured and no crate carries an HTTP
     client"*. M2 shipped `marlowe-provider`, and `crates/marlowe/Cargo.toml` already depends on it.
  2. **Nothing was ever injected.** Every Session K answer frame reads
     `abstention_reason: no_candidate_above_threshold` under gate `frozen-v5` at threshold 0.95 —
     and ADR-016 measured that a *perfect* retrieval system scores 0.8483 against that threshold, so
     the gate could never admit anything. ADR-019 replaced it with the declared operating point.

So `answer_accuracy 0.0` on the record is not a measurement of answering. It is two absences.

## This measures offline, and does not touch the shipped path

Same pattern as the reranker frontier: reconstruct the shipped ranking from
`runs/session-k/fit/scored-candidates.ndjson`, take the top-k turns, and ask a local model. No Rust
change, nothing shipped. Wiring the generator into `handle_answer` is the follow-up, and it should
be done once this says what the number is.

## THE TWO CONTROLS, and the measurement is uninterpretable without them

A bare QA number cannot distinguish "retrieval failed" from "the model cannot answer".

  * **`gold`** — feed the *gold* turns. This is the CEILING: generator capability given perfect
    retrieval. If QA@gold is 0.70, then no retrieval improvement can push QA past 0.70, and R@1 work
    is not the binding constraint.
  * **`none`** — feed NO memories. This is the FLOOR: what the model answers from its own parameters
    plus the question. LongMemEval questions are about a fictional user's history, so this should be
    near zero — and if it is NOT, then some of QA@k is the model guessing, not remembering, and
    every k-arm must be read against it.

Reporting QA@k without both is the shape this project keeps a list of: a number that would read the
same if the thing it claims to measure were broken.

## Grading

`ContainmentGrader` from `marlowe_eval.metrics.accuracy`, IMPORTED not reimplemented. It is
deterministic and seed-free, and it declares `comparable_to_published = False` — LongMemEval's
published protocol grades with an LLM judge, so **these numbers are a regression signal and are not
comparable to published LongMemEval results.** That is the grader's own statement, carried here.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.metrics.accuracy import ContainmentGrader  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "qa-accuracy.json"
OLLAMA = "http://localhost:11434/api/chat"

SYSTEM = (
    "You answer questions about a user's own conversation history using ONLY the memories provided. "
    "Answer in as few words as possible - a name, a number, a date, a short phrase. "
    "Do not explain. Do not repeat the question. "
    "If the memories do not contain the answer, reply exactly: I don't know."
)


def ask(model: str, question: str, memories: list[str], timeout: int = 120) -> tuple[str, float]:
    """One turn. Greedy, fixed seed -- a QA number from a sampled decode is not reproducible."""
    if memories:
        blocks = "\n\n".join(f"[memory {i + 1}] {m}" for i, m in enumerate(memories))
        user = f"Memories:\n{blocks}\n\nQuestion: {question}\nAnswer:"
    else:
        user = f"Question: {question}\nAnswer:"
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        # Greedy and seeded. Reported in the artifact so a rerun is comparable.
        "options": {"temperature": 0.0, "top_p": 1.0, "seed": 7, "num_predict": 64},
    }
    req = urllib.request.Request(
        OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        out = json.loads(fh.read())
    return out["message"]["content"].strip(), (time.perf_counter() - t0) * 1000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="marlowe-red:9b")
    ap.add_argument(
        "--arms", nargs="+", default=["none", "gold", "k1", "k5", "k10"],
        help="none=no memories (FLOOR), gold=the gold turns (CEILING), kN=shipped top-N",
    )
    ap.add_argument("--limit", type=int, default=0, help="0 = all queries")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts_all = turn_texts()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    cases = {c.query_id: c for c in corpus.cases}

    # The instrument gate, same as every other tool this session.
    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}.")
    print(f"control: fit R@1 {r1}. {len(pools)} queries. model={args.model}")

    grader = ContainmentGrader()
    qids = sorted(pools)
    if args.limit:
        qids = qids[: args.limit]

    results = {}
    for arm in args.arms:
        correct = abstain = 0
        per_cat: dict[str, list[int]] = {}
        rows, lat = [], []
        for qid in qids:
            pool, case = pools[qid], cases[qid]
            texts = texts_all.get(qid, {})
            if arm == "none":
                mems = []
            elif arm == "gold":
                mems = [
                    texts.get(pool.candidates[i].turn_id) or ""
                    for i, g in enumerate(pool.gold) if g
                ][:10]
            else:
                k = int(arm[1:])
                mems = [
                    texts.get(pool.candidates[int(i)].turn_id) or "" for i in orders[qid][:k]
                ]
            mems = [m for m in mems if m]
            try:
                answer, ms = ask(args.model, case.question, mems)
            except Exception as e:  # noqa: BLE001
                print(f"  {qid}: request failed: {type(e).__name__}: {str(e)[:100]}")
                continue
            lat.append(ms)
            said_no = answer.lower().startswith("i don't know") or answer.lower().startswith("i dont know")
            ok = (not said_no) and grader.grade(case.question, case.gold_answer or "", answer)
            correct += int(ok)
            abstain += int(said_no)
            per_cat.setdefault(case.category, [0, 0])
            per_cat[case.category][0] += 1
            per_cat[case.category][1] += int(ok)
            rows.append(
                {"query_id": qid, "category": case.category, "memories": len(mems),
                 "gold": case.gold_answer, "answer": answer, "correct": ok, "abstained": said_no}
            )
        n = len(rows)
        results[arm] = {
            "n": n,
            "qa_accuracy": round(correct / n, 4) if n else 0.0,
            "abstention_rate": round(abstain / n, 4) if n else 0.0,
            "median_latency_ms": round(sorted(lat)[len(lat) // 2], 1) if lat else None,
            "per_category": {
                k: {"n": v[0], "qa_accuracy": round(v[1] / v[0], 4)} for k, v in sorted(per_cat.items())
            },
            "rows": rows,
        }
        print(f"  arm {arm:<5} n={n:<4} QA={results[arm]['qa_accuracy']:.4f}  "
              f"abstain={results[arm]['abstention_rate']:.4f}  "
              f"{results[arm]['median_latency_ms']} ms")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_what": "QA accuracy, fit split, offline. The M0b acceptance row that was never measured.",
                "_split": "fit",
                "_model": args.model,
                "_decode": {"temperature": 0.0, "top_p": 1.0, "seed": 7, "num_predict": 64},
                "_grader": {
                    "name": grader.name,
                    "comparable_to_published": grader.comparable_to_published,
                    "_note": (
                        "LongMemEval's published protocol grades with an LLM judge. This grader is "
                        "deterministic containment and is a REGRESSION SIGNAL, not a benchmark "
                        "result. Do not compare it to published LongMemEval numbers."
                    ),
                },
                "_controls": {
                    "none": "FLOOR - no memories. Non-zero here means the model is guessing.",
                    "gold": "CEILING - the gold turns. Caps what any retrieval improvement can buy.",
                },
                "control_fit_r1": r1,
                "pools": stats,
                "arms": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        shown = out.resolve().relative_to(REPO)
    except ValueError:
        shown = out
    print(f"\nwrote {shown}")

    if "gold" in results and "k10" in results:
        g, k = results["gold"]["qa_accuracy"], results["k10"]["qa_accuracy"]
        print(f"\nretrieval headroom: QA@k10 {k:.4f} against the QA@gold ceiling {g:.4f} "
              f"-> {g - k:+.4f} available to retrieval work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
