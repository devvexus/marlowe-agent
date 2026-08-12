"""Two ways to strip the shared signal from the top-k, measured against the same bar as everything else.

    python tools/denoise_rerank.py

**Measurement only. No training, nothing ships.**

Sixteen post-hoc mechanisms have now been measured on the rank-1/rank-2 decision. Every one either
died or was confined to cross-encoder gaps below **0.084** -- the band where the shipped model's top
two scores are effectively identical and any nudge reshuffles them. A blind swap there scores +5,
which beats the span reader and sentence MaxP, and neither of those ever made a correct call
outside it.

So the bar is not the net. **Does the rule fire CORRECTLY above 0.084?**

## ARM 1 -- centroid subtraction

The candidates in a slate are near-duplicates in topic: they were selected for sharing the query's
subject. So the dominant direction in their embedding space is the thing they all have in common,
which is by definition the least discriminating direction available.

Subtract the slate centroid from each candidate vector, then compare the residual to the query.

**Why this is not the ADR-011 trap.** `z` already centres the *scores*, and per-query score
normalisation is a strictly increasing transform within a query -- an identity on R@1, which is a
within-query ordering read. Session I reclassified an entire arm for exactly that reason.
**Centring the VECTORS is different: it changes the geometry, not the scale, so it can reorder.**
That distinction is the whole reason this is worth running and score-normalisation was not.

The prior is low -- dense alone is the weakest cue at 0.4454 and dense fusion flipped 0 at every
weight -- but the mechanism argument cuts the other way: raw cosine may be weak *because* it is
dominated by the shared component this removes.

## ARM 2 -- the reader's null head as an explicit penalty

A SQuAD-v2 span reader emits `start_logits` and `end_logits` and nothing else; "unanswerable" is
encoded as the span collapsing onto position 0. So

    null_score = start[0] + end[0]

is a trained estimate of **"this passage contains no answer"**.

The reach check used `best_span - null` and found it helps only inside the near-tie band. **The null
term has never been used on its own as a penalty against the cross-encoder's score.** That is a
different combination: not "which passage answers best" but "penalise the ones that look
answer-free".

The argument for a dedicated anti-model: the distractor class is larger and more homogeneous than
the gold class -- one gold per query against nine distractors, sharing a characteristic form -- so
"what does a distractor look like" may be an easier function than "what does the answer look like".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import readers  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "denoise-rerank.json"
NEAR_TIE = 0.084
TOP = 5


_EMB: dict = {}


def embed_all(texts: list[str], model_dir: Path) -> np.ndarray:
    """jina-v2-small, the shipped dense cue's own embedder, L2-normalised.

    Uses `model-w-mean-pooling.onnx`, which emits `[batch, 512]` directly -- the pooling is inside
    the graph, so this cannot disagree with the shipped path about how pooling is done. The
    directory ships `vocab.txt` rather than a `tokenizer.json`, matching `cue/dense/tokenizer.rs`'s
    WordPiece loader, so the tokenizer is built from that.
    """
    import onnxruntime as ort
    from tokenizers import BertWordPieceTokenizer

    if "s" not in _EMB:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        so.intra_op_num_threads = 1
        _EMB["s"] = ort.InferenceSession(str(model_dir / "model-w-mean-pooling.onnx"), so,
                                         providers=["CPUExecutionProvider"])
        tok = BertWordPieceTokenizer(str(model_dir / "vocab.txt"), lowercase=True)
        tok.enable_truncation(max_length=512)
        tok.enable_padding(length=512)
        _EMB["t"] = tok
    sess, tok = _EMB["s"], _EMB["t"]

    encs = [tok.encode(t or "") for t in texts]
    feed = {
        "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
        "token_type_ids": np.array([e.type_ids for e in encs], dtype=np.int64),
    }
    v = np.asarray(sess.run(None, feed)[0])
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reader", default="roberta-base-squad2")
    ap.add_argument("--embedder", default="jina-embeddings-v2-small-en")
    ap.add_argument("--top", type=int, default=TOP)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, _ = load_pools(FIT_POOLS)
    texts_all = turn_texts()
    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}")
    print(f"control: fit R@1 {r1}  ({len(pools)} queries)  top-{args.top}\n")

    rd = readers.load(args.reader, provider=args.provider)
    if not readers.smoke_test(rd)["pass"]:
        raise SystemExit(f"REFUSING: {args.reader} fails the smoke test")
    emb_dir = REPO / "models" / args.embedder

    rows = {}
    for n, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        t = texts_all.get(qid, {})
        idxs = [int(i) for i in orders[qid][: args.top]]
        docs = [t.get(pool.candidates[i].turn_id) or "" for i in idxs]
        vecs = embed_all([pool.question] + docs, emb_dir)
        qv, cv = vecs[0], vecs[1:]
        centroid = cv.mean(axis=0)
        resid = cv - centroid
        resid = resid / (np.linalg.norm(resid, axis=1, keepdims=True) + 1e-9)
        nulls = [rd.score(pool.question, d)["null"] if d else 0.0 for d in docs]
        rows[qid] = {
            "gold": [bool(pool.gold[i]) for i in idxs],
            "ce": [pool.candidates[i].rerank_score for i in idxs],
            "cos_raw": [float(qv @ v) for v in cv],
            "cos_centered": [float(qv @ v) for v in resid],
            "null": [float(x) for x in nulls],
        }
        if n % 40 == 0:
            print(f"  {n}/{len(pools)}")

    N = len(rows)

    def evaluate(key, label):
        gain = lost = corr = 0
        og = ol = on = 0
        for d in rows.values():
            base = 0
            j = int(np.argmax([key(d, i) for i in range(len(d["gold"]))]))
            corr += int(d["gold"][j])
            gap = (d["ce"][0] - d["ce"][1]) if None not in d["ce"][:2] else None
            outside = gap is not None and gap > NEAR_TIE
            if j != base:
                if d["gold"][j] and not d["gold"][base]:
                    gain += 1; og += int(outside)
                elif d["gold"][base] and not d["gold"][j]:
                    lost += 1; ol += int(outside)
                elif outside:
                    on += 1
        return {"rule": label, "gained": gain, "lost": lost, "net": gain - lost,
                "r1": round(corr / N, 4), "above_near_tie": {"g": og, "l": ol, "n": on}}

    def ce(d, i):
        return d["ce"][i] if d["ce"][i] is not None else -1e9

    arms = [evaluate(ce, "control (shipped)")]
    arms.append(evaluate(lambda d, i: d["cos_raw"][i], "dense cosine, raw"))
    arms.append(evaluate(lambda d, i: d["cos_centered"][i], "ARM1 dense cosine, CENTRED"))
    for lam in (0.5, 1.0, 2.0, 5.0):
        arms.append(evaluate(lambda d, i, l=lam: ce(d, i) + l * d["cos_centered"][i],
                             f"ARM1 ce + {lam}*centred"))
    for lam in (0.05, 0.1, 0.25, 0.5):
        arms.append(evaluate(lambda d, i, l=lam: ce(d, i) - l * d["null"][i],
                             f"ARM2 ce - {lam}*null"))

    print(f"\n{'rule':<34}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}   >0.084 g/l/n")
    for a in arms:
        o = a["above_near_tie"]
        print(f"{a['rule']:<34}{a['gained']:>6}{a['lost']:>6}{a['net']:>6}{a['r1']:>9.4f}"
              f"   {o['g']}/{o['l']}/{o['n']}")

    Path(args.out).write_text(json.dumps({
        "_what": "centroid subtraction and reader-null penalty over the top-k, fit split",
        "_measurement_only": True,
        "_decisive_test": "does any rule fire CORRECTLY above the 0.084 near-tie band?",
        "control_fit_r1": r1, "top": args.top, "reader": args.reader,
        "arms": arms, "rows": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {Path(args.out).relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
