"""R7 -- is the supersession pair FINDABLE? The other half of the reachability check.

R6 measured the ceiling: a perfect oracle is worth +0.0262 overall R@1, +0.1666 on
knowledge-update, and cuts harmful injections by 71%. That is what a detector would be reaching
for. This asks whether any detector can reach it, and it is the question that decides the session.

**The asymmetry that governs the threshold** (registered here, before any threshold is chosen): a
FALSE supersession removes a live memory from injection permanently; a MISSED supersession leaves a
stale one injectable. Those costs are not symmetric and the threshold is not chosen against F1.
Merges are reversible via the `supersedes` edge (HP5, ADR-012) so a false supersession is not
catastrophic -- but it is silent, and a silent permanent removal is worse than a visible stale
injection. The threshold is therefore chosen against the FALSE-POSITIVE direction.

What is measured, per knowledge-update case, over the case's whole retrieved pool:

  1. the cosine between the TRUE pair -- the stale gold turn and the current gold turn;
  2. the cosine between the stale gold turn and every OTHER turn in the pool -- the population a
     threshold has to reject;
  3. the RANK of the true partner among all pool turns by cosine from the stale turn;
  4. the separation: what precision a global cosine threshold achieves at each recall level, and
     what threshold ADR-012's 0.98 duplicate bar would have caught.

A supersession threshold is NOT a duplicate threshold. ADR-012 measured >=0.98 at 0.0086% of 30.6M
pairs, which is why the current merge is blind. If the true pairs sit inside the bulk of the
distractor distribution, no threshold exists and the answer is a contradiction detector that reads
VALUES, not similarity -- or nothing.

Embeddings come from the shipped embedder, `jina-embeddings-v2-small-en`, mean-pooled -- the same
vectors the dense cue scores with. A different embedder would measure a different system.

Fit split only. Prints numbers. Applies nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_harm_r5_classes import load_case_structure  # noqa: E402
from reach_head_r3_slate import load_pool  # noqa: E402

EMBED_DIR = REPO / "models" / "jina-embeddings-v2-small-en"
SPLIT_PATH = REPO / "tools" / "split.json"
OUT = REPO / "runs" / "session-m0c" / "reach-r7-separability-{split}.json"
MAX_LEN = 512
ADR012_DUPLICATE_THRESHOLD = 0.98


_CACHE = REPO / "runs" / "session-m0c" / "r7-turn-embeddings.npz"


def embed_all(by_id: dict[str, str], batch: int = 128) -> dict[str, np.ndarray]:
    """Mean-pooled jina embeddings for every distinct turn, ONCE, L2-normalised.

    A first version embedded each case's pool separately. Pools overlap heavily -- 34 fit
    knowledge-update cases share 16,093 distinct turns between them -- so it re-embedded the same
    text many times and did not finish. Deduplicating by turn id is the whole fix.

    `ORT_ENABLE_BASIC` is pinned on both sides per CLAUDE.md: `ort` builds at Level1 and Python's
    default fuses differently. An offline measurement taken at a different level measures a
    different embedder. Padding is per batch rather than to a fixed 512 -- mean pooling is taken
    over the attention mask, so padded positions contribute nothing and the two agree to float
    noise; the fixed length would only slow it down."""
    import onnxruntime as ort
    from tokenizers import Tokenizer

    graph = EMBED_DIR / "model-w-mean-pooling.onnx"
    if not graph.exists():
        raise SystemExit(f"REFUSING: {graph} absent. There is deliberately no fallback to the "
                         f"un-pooled graph -- pooling it differently here would measure a "
                         f"different embedder from the one the dense cue uses.")

    ids = sorted(by_id)
    if _CACHE.exists():
        z = np.load(_CACHE, allow_pickle=True)
        if list(z["ids"]) == ids:
            print(f"  reusing cached embeddings for {len(ids)} turns")
            return {t: v for t, v in zip(z["ids"], z["emb"])}
        print("  cache present but for a different turn set; re-embedding")

    tok = Tokenizer.from_file(str(EMBED_DIR / "tokenizer.json")) \
        if (EMBED_DIR / "tokenizer.json").exists() else None
    if tok is None:
        from transformers import AutoTokenizer
        hf = AutoTokenizer.from_pretrained(str(EMBED_DIR))

        def enc_fn(ts):
            e = hf(ts, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="np")
            return {k: v.astype(np.int64) for k, v in e.items()}
    else:
        tok.enable_truncation(max_length=MAX_LEN)
        tok.enable_padding()          # to the batch max, not to MAX_LEN

        def enc_fn(ts):
            e = tok.encode_batch(ts)
            return {"input_ids": np.array([x.ids for x in e], dtype=np.int64),
                    "attention_mask": np.array([x.attention_mask for x in e], dtype=np.int64),
                    "token_type_ids": np.array([x.type_ids for x in e], dtype=np.int64)}

    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    avail = ort.get_available_providers()
    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                 if "CUDAExecutionProvider" in avail else ["CPUExecutionProvider"])
    sess = ort.InferenceSession(str(graph), opts, providers=providers)
    print(f"  embedding {len(ids)} distinct turns on {sess.get_providers()[0]} ...")
    names = {i.name for i in sess.get_inputs()}

    # sort by length so each batch pads to a similar width
    order = sorted(range(len(ids)), key=lambda i: len(by_id[ids[i]]))
    out = np.zeros((len(ids), 0), dtype=np.float32)
    buf: list[tuple[int, np.ndarray]] = []
    for s in range(0, len(order), batch):
        chunk = order[s:s + batch]
        feed = {k: v for k, v in enc_fn([by_id[ids[i]] for i in chunk]).items() if k in names}
        v = sess.run(None, feed)[0]
        if v.ndim == 3:
            m = feed["attention_mask"][:, :, None].astype(np.float32)
            v = (v * m).sum(1) / np.maximum(m.sum(1), 1e-9)
        v = v.astype(np.float32)
        if out.shape[1] == 0:
            out = np.zeros((len(ids), v.shape[1]), dtype=np.float32)
        out[chunk] = v
        if (s // batch) % 20 == 0:
            print(f"    {min(s + batch, len(order))}/{len(order)}", flush=True)
    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(_CACHE, ids=np.array(ids), emb=out)
    return {t: v for t, v in zip(ids, out)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="fit", choices=["fit", "heldout"])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    from marlowe_eval.datasets import longmemeval

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus_path = REPO / split["corpus_path"]
    cases = load_case_structure(corpus_path)
    corpus = longmemeval.load(corpus_path)
    gold_map = corpus.gold_map()
    harness = {c.query_id: c for c in corpus.cases}

    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    for inst in raw:
        for sid, sess in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for i, t in enumerate(sess):
                texts[f"{sid}-{i}"] = str(t["content"])

    pool = load_pool(args.split, gold_map)
    ku = sorted(q for q in pool if q in harness and not harness[q].is_abstention
                and cases[q]["question_type"] == "knowledge-update"
                and cases[q]["current_session"] is not None)
    print(f"\nsplit={args.split}  knowledge-update cases with an identified current session: "
          f"{len(ku)}")

    # gather every turn that any usable case needs, then embed the union ONCE
    usable = []
    needed: dict[str, str] = {}
    for q in ku:
        cur = cases[q]["current_session"]
        stale_sess = cases[q]["answer_sessions"] - {cur}
        pool_tids = [t for t in pool[q]["turn_id"].tolist() if t in texts]
        pool_set = set(pool_tids)
        stale_gold = [t for t in cases[q]["gold"]
                      if t.rsplit("-", 1)[0] in stale_sess and t in pool_set]
        cur_gold = [t for t in cases[q]["gold"] if t.rsplit("-", 1)[0] == cur]
        if not stale_gold or not cur_gold or len(pool_tids) < 10:
            continue
        usable.append((q, stale_gold[0], cur_gold, pool_tids))
        for t in set(pool_tids) | set(cur_gold) | {stale_gold[0]}:
            needed[t] = texts[t]
    print(f"  usable knowledge-update cases: {len(usable)}")
    vecs = embed_all(needed)

    true_cos, rank_of_partner, pool_sizes = [], [], []
    all_distractor_cos = []
    per_case = []
    for q, s_tid, cur_gold, pool_tids in usable:
        uniq = list(dict.fromkeys(pool_tids + cur_gold + [s_tid]))
        emb = np.stack([vecs[t] for t in uniq])
        idx = {t: i for i, t in enumerate(uniq)}
        sims = emb @ vecs[s_tid]

        best_partner = max(float(sims[idx[t]]) for t in cur_gold if t in idx)
        others = np.array([sims[idx[t]] for t in uniq
                           if t != s_tid and t not in set(cur_gold)], dtype=float)
        rank = int((others > best_partner).sum()) + 1

        true_cos.append(best_partner)
        rank_of_partner.append(rank)
        pool_sizes.append(len(others) + 1)
        all_distractor_cos.append(others)
        per_case.append({"query_id": q, "stale_turn": s_tid,
                         "cos_to_current_gold": round(best_partner, 4),
                         "rank_of_true_partner": rank, "pool": len(others) + 1})

    tc = np.asarray(true_cos)
    dc = np.concatenate(all_distractor_cos)
    print(f"  usable cases: {len(tc)}   distractor pairs measured: {len(dc):,}")

    print()
    print("=" * 96)
    print("R7 -- IS THE SUPERSESSION PAIR FINDABLE?")
    print("=" * 96)
    print(f"  cosine(stale gold, current gold)  -- the TRUE pair, n={len(tc)}")
    for qq in (0.05, 0.25, 0.5, 0.75, 0.95):
        print(f"     p{int(qq*100):>2}  {np.quantile(tc, qq):.4f}")
    print(f"  cosine(stale gold, every other pool turn) -- the population to REJECT, n={len(dc):,}")
    for qq in (0.5, 0.9, 0.99, 0.999, 1.0):
        print(f"     p{qq*100:>5.1f}  {np.quantile(dc, qq):.4f}")

    print()
    print(f"  RANK of the true partner among all pool turns, by cosine from the stale turn:")
    r = np.asarray(rank_of_partner)
    print(f"     rank 1: {int((r == 1).sum())}/{len(r)}   top-5: {int((r <= 5).sum())}/{len(r)}   "
          f"top-20: {int((r <= 20).sum())}/{len(r)}   median rank {np.median(r):.0f} "
          f"of a median pool of {np.median(pool_sizes):.0f}")

    print()
    print("-" * 96)
    print("WHAT A GLOBAL COSINE THRESHOLD BUYS -- precision against the false-positive direction")
    print("-" * 96)
    print(f"{'threshold':>10} {'recall':>18} {'false positives':>17} {'precision':>10}")
    rows = []
    for th in (0.99, ADR012_DUPLICATE_THRESHOLD, 0.95, 0.92, 0.90, 0.88, 0.85, 0.80, 0.75, 0.70):
        tp = int((tc >= th).sum())
        fp = int((dc >= th).sum())
        prec = tp / (tp + fp) if (tp + fp) else float("nan")
        tag = "   <- ADR-012's duplicate bar" if th == ADR012_DUPLICATE_THRESHOLD else ""
        print(f"{th:>10.2f} {tp:>4d}/{len(tc):<4d} ({tp/len(tc):>5.1%}) {fp:>17,d} "
              f"{prec:>10.4f}{tag}")
        rows.append({"threshold": th, "true_positives": tp, "recall": round(tp / len(tc), 4),
                     "false_positives": fp, "precision": round(prec, 6) if tp + fp else None})

    print()
    print("-" * 96)
    print("READING")
    print("-" * 96)
    overlap = float((dc >= np.quantile(tc, 0.25)).mean())
    print(f"  {overlap:.2%} of distractor pairs sit at or above the 25th percentile of the true "
          f"pairs.")
    best = max((x for x in rows if x["precision"] is not None), key=lambda x: x["precision"])
    print(f"  best global-cosine precision anywhere on the grid: {best['precision']:.4f} at "
          f"threshold {best['threshold']} (recall {best['recall']:.1%})")
    print()
    if best["precision"] < 0.5:
        print("  => A GLOBAL COSINE THRESHOLD CANNOT DO THIS. The true pairs are not separable")
        print("     from the pool by similarity alone, and every threshold that catches them")
        print("     catches far more live memories. Under the registered asymmetry -- a false")
        print("     supersession removes a live memory permanently -- this is not a threshold to")
        print("     tune, it is a signal that is absent.")
    else:
        print("  => a global cosine threshold has usable precision; a band can be derived.")

    out = args.out or Path(str(OUT).format(split=args.split))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "is the supersession pair findable by similarity? R6 gave the ceiling; this gives "
                 "the approach.",
        "_cost_model_registered_before_any_threshold": {
            "false_supersession": "removes a live memory from injection permanently and silently. "
                                  "Reversible via the supersedes edge (HP5, ADR-012) but not "
                                  "self-announcing.",
            "missed_supersession": "leaves a stale memory injectable; visible as a wrong answer.",
            "rule": "the threshold is chosen against the FALSE-POSITIVE direction, not against F1",
        },
        "split": args.split, "embedder": "jina-embeddings-v2-small-en, mean-pooled, "
                                         "ORT_ENABLE_BASIC",
        "n_cases": len(tc), "n_distractor_pairs": int(len(dc)),
        "true_pair_cosine": {f"p{int(q*100)}": round(float(np.quantile(tc, q)), 4)
                             for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
        "distractor_cosine": {f"p{q*100:g}": round(float(np.quantile(dc, q)), 4)
                              for q in (0.5, 0.9, 0.99, 0.999, 1.0)},
        "rank_of_true_partner": {"rank_1": int((r == 1).sum()), "top_5": int((r <= 5).sum()),
                                 "top_20": int((r <= 20).sum()),
                                 "median": float(np.median(r)),
                                 "median_pool": float(np.median(pool_sizes))},
        "threshold_grid": rows,
        "best_precision": best,
        "per_case": per_case,
    }, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
