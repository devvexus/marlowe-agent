"""Train the cross-encoder for TOP-3 MEMBERSHIP, not for rank 1.

    PYTHONIOENCODING=utf-8 python tools/finetune_top3.py --arm T3 --k 3

## The argument, in one paragraph

The product now injects three memories (`ADMIT_TOP_K = 3`, `retrieve.rs`), so **R@3 is the product
metric**. Every graph this project has ever trained was optimised for rank 1: Session J's loss is
hard-label MarginMSE, `mse_loss(s_pos - s_neg, delta)`, which pushes gold above **every** negative
by a fixed margin. That spends capacity separating rank 1 from rank 2 — a distinction the product
no longer makes — while the boundary that actually costs cases is between rank 3 and rank 4.

The measured loss profile says exactly that. `tools/cond3_taxonomy.py`, fit, 11 cases lost at
`cond@3`: gold lands at **rank 4 in five of them** and rank 5-6 in four more. Only two are routs.
**This is a near-miss population one position outside the cut.**

## The loss

For each query, score the positive and ALL of its mined negatives. Let `s_k` be the **k-th highest
negative** (k = 3). Then

    L = relu(delta - (s_pos - s_k))

Gold above the 3rd-highest negative means at most two negatives outrank it, so **gold is in the top
3 — and the loss is exactly zero regardless of which of the three it is.** That is the objective
stated literally: get it in the top 3, do not care about the ordering inside.

`delta` is Session J's own target margin, recomputed from the base model's margins by the same rule,
so this arm differs from arm A in the *shape* of the objective and in nothing else.

**Why this is not the dead "BCE instead of MarginMSE" arm** (-0.0524 at fixed negatives). That
changed the loss FAMILY — pointwise classification instead of pairwise margin — and kept the rank-1
target. This keeps the pairwise margin and moves the TARGET from "above every negative" to "above
the k-th". Same family, different boundary.

## MODEL SELECTION MOVES TOO, and this is the part most likely to be got wrong

`finetune_v2.py` picks the best epoch by fit-val **R@1**. Selecting a top-3 objective's checkpoint
on a rank-1 metric would optimise one thing and choose on another — the proxy failure this project
keeps a ledger of. Selection here is by fit-val **R@k**. Both are printed every epoch so the
divergence is visible rather than assumed.

## What is reused

`finetune_v2`'s loaders, exporter, ONNX verification, delta rule, fold handling and score cache are
imported, not restated. **The only things this file changes are the loss and the selection metric.**
`finetune_v2.py` is not modified.

## Registered before any number exists

  * fit-val R@3 rises; fit-val R@1 **falls or is flat**. If R@1 also rises the loss is probably not
    doing what it says and I should check before believing R@3.
  * fit `cond@3` 0.9511 -> **0.955-0.975**. Below 0.9511 refutes the arm outright.
  * The near-miss structure predicts most of the gain comes from cases currently at rank 4.
  * Held-out is NOT read by this file, and no configuration is chosen on held-out.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import finetune_v2 as F  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"


def r_at_k_from_scores(cache: dict, by_query: dict[str, np.ndarray], k: int) -> float:
    """R@k over the cached slates. `r_at_1_from_scores` with the cut moved, nothing else."""
    hits = 0
    for qid, row in cache["rows"].items():
        order = np.argsort(-by_query[qid], kind="stable")
        hits += any(bool(row["gold"][int(i)]) for i in order[:k])
    return hits / len(cache["rows"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", default="T3")
    ap.add_argument("--k", type=int, default=3, help="the rank boundary the loss targets")
    ap.add_argument("--pairs", default="sessionj", choices=sorted(F.PAIR_FILES))
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--queries-per-batch", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--loss", choices=["hinge", "marginmse"], default="hinge",
                    help="hinge penalises only undershoot; marginmse drives the gap TO delta and is "
                         "Session J's family")
    ap.add_argument("--delta", type=float, default=None,
                    help="override the delta rule. Exists only to reproduce the first, broken run "
                         "(2.926574, the rank-1 margin). Never use it to tune.")
    ap.add_argument("--max-negatives", type=int, default=24,
                    help="cap per query so one long slate cannot dominate a step; the k-th highest "
                         "is taken over the cap, and the cap is declared, not tuned")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    F.set_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}   arm {args.arm}   k = {args.k}")
    if device != "cuda":
        print("  WARNING: training on CPU. Every published timing in this project is a "
              "1-thread CPU number for a GPU target; this will be slow.")

    cache = json.loads(F.CACHE.read_text(encoding="utf-8"))
    questions = F.load_questions()
    from reach_pools import turn_texts
    texts_by_query = turn_texts()

    source = F.HF_REPO
    tok = AutoTokenizer.from_pretrained(source)
    model = AutoModelForSequenceClassification.from_pretrained(source).to(device)

    # ---- delta AT THE BOUNDARY THE LOSS TARGETS -------------------------------------------------
    #
    # **The first version of this file got this wrong and the failure is instructive.** It inherited
    # Session J's `delta = 2.926574`, which is the median RANK-1 margin. The hinge then demanded
    # gold beat the 3rd-highest negative by 2.93 logits — a margin big enough that clearing it puts
    # gold at rank 1 anyway. The "don't care which of the top 3" property was barely exercised, R@1
    # rose against the registered prediction, and the graph came out strictly weaker than the
    # shipped one (fit R@1 0.7293 vs 0.7555, cond@3 0.9244 vs 0.9511).
    #
    # Session J's rule is *"the median margin over fit cases this base already gets right"*. Applied
    # at k = 1 that is gold-minus-runner-up. **Applied at k it is gold minus the k-th highest
    # NON-GOLD, over the cases the base already places inside the top k.** Same rule, same base,
    # evaluated at the boundary the objective actually uses. It is one number computed by a fixed
    # rule, not a swept hyperparameter — `--delta` exists only to reproduce the broken run.
    margins = []
    for qid, row in cache["rows"].items():
        s = np.asarray(row["scores"], dtype=float)
        gold = np.asarray(row["gold"], dtype=bool)
        if not gold.any():
            continue
        order = np.argsort(-s, kind="stable")
        if not any(gold[int(i)] for i in order[:args.k]):
            continue  # the base does not already get this one right at k; it sets no target
        neg = np.sort(s[~gold])[::-1]
        if len(neg) < args.k:
            continue
        margins.append(float(s[gold].max() - neg[args.k - 1]))
    delta = float(np.median(margins)) if args.delta is None else args.delta
    src = "OVERRIDDEN" if args.delta is not None else f"median over {len(margins)} fit cases"
    print(f"target margin delta = {delta:.6f}  ({src}; gold minus the k={args.k}-th highest "
          f"non-gold, over cases the base already places inside the top {args.k})")
    # **The machinery check, and it caught a real divergence rather than a bug.**
    #
    # Session J's delta is `s[order[0]] - s[order[1]]` -- gold minus the RUNNER-UP, whether or not
    # that runner-up is itself gold. This file's rule skips other golds and measures gold minus the
    # highest NON-gold. On multi-gold queries those differ: Session J measures the gap between two
    # golds (small), this measures the gap to the first real negative (larger). At k=1 the two give
    # 2.926574 and 3.568838.
    #
    # **The divergence is deliberate and this file's rule is the right one for a MEMBERSHIP
    # objective**: pushing gold_1 above gold_2 is work the metric does not ask for and gradient
    # spent against itself. But the check must validate the LOOP, so it recomputes Session J's own
    # formula on the same cache and requires that to reproduce -- which isolates "is the cache and
    # the loop right" from "is the rule different".
    sj = []
    for qid, row in cache["rows"].items():
        s_ = np.asarray(row["scores"], dtype=float)
        o_ = np.argsort(-s_, kind="stable")
        if row["gold"][int(o_[0])]:
            sj.append(float(s_[int(o_[0])] - s_[int(o_[1])]))
    sj_delta = float(np.median(sj))
    if abs(sj_delta - F.SESSION_J_DELTA) > 1e-5:
        raise SystemExit(
            f"REFUSING. Session J's own formula on this cache gives {sj_delta:.6f}, not "
            f"{F.SESSION_J_DELTA}. The cache or the loop is wrong, so no delta here is trustworthy."
        )
    print(f"  machinery check: Session J's formula reproduces {F.SESSION_J_DELTA} exactly "
          f"({sj_delta:.6f}); this file's k={args.k} rule gives {delta:.6f} — the difference is "
          f"the deliberate exclusion of other gold turns from the negative set")

    # ---- group the pairwise file BY QUERY: the top-k boundary needs a slate, not a pair ---------
    rows = [json.loads(l) for l in io.open(F.PAIR_FILES[args.pairs], encoding="utf-8") if l.strip()]
    grouped: dict[str, dict] = {}
    for r in rows:
        if r["fold"] != "train":
            continue
        g = grouped.setdefault(r["query_id"], {"question": r["question"],
                                               "positive": r["positive"], "negatives": []})
        g["negatives"].append(r["negative"])
    groups = [g for g in grouped.values() if len(g["negatives"]) >= args.k]
    dropped = len(grouped) - len(groups)
    print(f"train queries: {len(groups)}  (dropped {dropped} with fewer than k={args.k} negatives)")
    print(f"negatives per query: min {min(len(g['negatives']) for g in groups)}  "
          f"median {int(np.median([len(g['negatives']) for g in groups]))}  "
          f"max {max(len(g['negatives']) for g in groups)}  cap {args.max_negatives}")

    val_queries = sorted({r["query_id"] for r in rows if r["fold"] == "val"})
    val_in_cache = [q for q in val_queries if q in cache["rows"]]
    if len(val_queries) != F.SESSION_J_VAL_QUERIES:
        raise SystemExit(f"val fold is {len(val_queries)}, Session J's is "
                         f"{F.SESSION_J_VAL_QUERIES}. Not the same validation set.")
    val_cache = {"rows": {q: cache["rows"][q] for q in val_in_cache}}
    val_pairs, val_idx = [], []
    for qid in val_in_cache:
        per = texts_by_query.get(qid, {})
        for j, tid in enumerate(cache["rows"][qid]["turn_ids"]):
            val_pairs.append((questions[qid], per.get(tid, "")))
            val_idx.append((qid, j))

    def val_scores():
        s = F.score_with_torch(model, tok, val_pairs, device)
        bq = {q: np.zeros(len(r["scores"])) for q, r in val_cache["rows"].items()}
        for (qid, j), v in zip(val_idx, s):
            bq[qid][j] = v
        return bq

    bq = val_scores()
    base1, basek = F.r_at_1_from_scores(val_cache, bq), r_at_k_from_scores(val_cache, bq, args.k)
    print(f"  base model, fit-val R@1 {base1:.4f}   fit-val R@{args.k} {basek:.4f}\n")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    rng = np.random.default_rng(args.seed)
    history = [{"epoch": 0, "val_r_at_1": round(base1, 4),
                f"val_r_at_{args.k}": round(basek, 4), "train_loss": None}]
    best = {"epoch": 0, "metric": basek, "state": None}

    for epoch in range(1, args.epochs + 1):
        model.train()
        order = rng.permutation(len(groups))
        losses, zero_loss = [], 0
        for start in range(0, len(order), args.queries_per_batch):
            chunk = [groups[i] for i in order[start:start + args.queries_per_batch]]
            batch_loss = 0.0
            for g in chunk:
                negs = g["negatives"]
                if len(negs) > args.max_negatives:
                    negs = [negs[i] for i in rng.choice(len(negs), args.max_negatives, replace=False)]
                enc = tok([g["question"]] * (1 + len(negs)), [g["positive"], *negs],
                          padding="max_length", truncation=True, max_length=F.MAX_LEN,
                          return_tensors="pt").to(device)
                s = model(**enc).logits.reshape(-1)
                s_pos, s_neg = s[0], s[1:]
                # The k-th HIGHEST negative. Gold above it => at most k-1 negatives outrank gold
                # => gold is inside the top k, and the loss is zero whatever its position there.
                kth = torch.topk(s_neg, args.k).values[-1]
                gap = s_pos - kth
                if args.loss == "hinge":
                    batch_loss = batch_loss + torch.relu(delta - gap)
                else:
                    # **MarginMSE at the k-th boundary.** The k=1 control proved the deficit was the
                    # LOSS FAMILY, not k: hinge@k=1 reads fit d10 R@1 0.7118 against MarginMSE@k=1's
                    # 0.7555, while hinge@k=3 reads 0.7249 — so moving k 1->3 is worth +0.0131
                    # inside the hinge family and the family itself costs more than k buys. This
                    # keeps Session J's family and moves ONLY the boundary, which is the arm the
                    # evidence actually points at.
                    batch_loss = batch_loss + torch.nn.functional.mse_loss(
                        gap.reshape(1), torch.full((1,), delta, device=gap.device))
            batch_loss = batch_loss / len(chunk)
            opt.zero_grad()
            batch_loss.backward()
            opt.step()
            v = float(batch_loss.item())
            losses.append(v)
            zero_loss += v == 0.0
        bq = val_scores()
        v1, vk = F.r_at_1_from_scores(val_cache, bq), r_at_k_from_scores(val_cache, bq, args.k)
        history.append({"epoch": epoch, "val_r_at_1": round(v1, 4),
                        f"val_r_at_{args.k}": round(vk, 4),
                        "train_loss": round(float(np.mean(losses)), 4),
                        "steps_at_zero_loss": zero_loss})
        print(f"  epoch {epoch}: loss {np.mean(losses):.4f}  "
              f"({zero_loss}/{len(losses)} steps already satisfied)  "
              f"fit-val R@1 {v1:.4f} ({v1 - base1:+.4f})   "
              f"R@{args.k} {vk:.4f} ({vk - basek:+.4f})")
        # SELECTION IS ON R@k, because that is what the loss optimises.
        if vk > best["metric"]:
            best = {"epoch": epoch, "metric": vk,
                    "state": {k_: t.detach().cpu().clone() for k_, t in model.state_dict().items()}}

    print(f"\nbest epoch {best['epoch']}  fit-val R@{args.k} {best['metric']:.4f} "
          f"(selected on R@{args.k}, not R@1)")
    if best["state"] is not None:
        model.load_state_dict(best["state"])

    name = f"ms-marco-MiniLM-L-2-v2-ft-{args.arm.lower()}"
    out = REPO / "models" / name
    out.mkdir(parents=True, exist_ok=True)
    # Both mirror `finetune_v2`'s export exactly. The `.to("cpu")` is not cosmetic -- the tracer
    # builds its dummy input on CPU, so exporting a CUDA model raises a device mismatch. And the
    # tokenizer is written by `backend_tokenizer.save`, NOT `save_pretrained`: `rerank.rs` pins
    # `tokenizer.json` against TOKENIZER_SHA256, and the two writers do not produce the same bytes.
    model = model.to("cpu")
    F.export_onnx(model, out / "model.onnx")
    tok.backend_tokenizer.save(str(out / "tokenizer.json"))
    model.save_pretrained(str(out / "pytorch-reference"))
    digest = F.sha256_file(out / "model.onnx")
    rec = {"_what": f"top-{args.k} membership objective, arm {args.arm}",
           "name": name, "k": args.k, "loss": f"relu(delta - (s_pos - s_neg_k)), k={args.k}",
           "selection_metric": f"fit-val R@{args.k}", "delta": delta,
           "base_checkpoint": str(source), "digest": digest,
           "hyperparameters": {"epochs": args.epochs, "lr": args.lr, "seed": args.seed,
                               "queries_per_batch": args.queries_per_batch,
                               "max_negatives": args.max_negatives, "max_len": F.MAX_LEN},
           "train_queries": len(groups), "history": history,
           "best_epoch": best["epoch"]}
    p = OUT_DIR / f"top3-train-{args.arm}.json"
    p.write_text(json.dumps(rec, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"exported {out.relative_to(REPO)}  sha256 {digest[:16]}…")
    print(f"wrote {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
