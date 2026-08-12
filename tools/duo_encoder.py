"""A JOINT PAIRWISE reranker: one forward pass over TWO candidates, output "which is better".

    python tools/duo_encoder.py --train --eval

**The last untested mechanism in the ranking space, and the only one that can REPRESENT a
comparison rather than proxy it.**

## Why this is different from everything M0c Session M measured

The shipped cross-encoder is **pointwise**:

    [CLS] q [SEP] A [SEP]  -> 4.21          two independent forwards; a sort compares them
    [CLS] q [SEP] B [SEP]  -> 4.19          A's score does not know B exists

Attention runs *within a row*, so even a batched `[10, 256]` forward gives no cross-candidate
information -- batching is a compute optimisation, not joint reasoning. The model therefore has no
internal place to put the thought *"A restates the question, B contains the answer"*, which is
exactly the failure: 32 of 53 held-out in-slate losses are gold at rank 2, median gap 0.348,
minimum 0.0004.

Nineteen post-hoc mechanisms tried to recover that comparison from outside the model -- features,
readers, sentence MaxP, neighbour structure, ensembles. Every one either died or was confined to
cross-encoder gaps below **0.084**, the band where the two scores are effectively identical and any
nudge reshuffles them. A blind coin flip in that band scores +5, which beats all of them.

**This model sees both candidates at once:**

    [CLS] q [SEP] A [SEP] B [SEP]  ->  P(A beats B)

Attention crosses the second [SEP]. The comparison is a computation, not a subtraction.

## THE CONTROL THAT DECIDES WHETHER IT LEARNED ANYTHING

Rank 1 is gold **110 times against 26** in the head population. **A pairwise model can score 81% by
learning "always say A" and nothing else.** So:

1. Every training pair is presented BOTH WAYS -- `(A,B)->1` and `(B,A)->0`.
2. **Symmetry is measured at eval**: feed each pair both orderings and require
   `P(A>B) + P(B>A) ~ 1`. A model that fails this has learned POSITION, not preference, and its
   headline number is meaningless.

Reported before any accuracy number, because the accuracy number is uninterpretable without it.

## Negatives: pattern-based only, and that is a decision arm B forced

`runs/session-m0c-m/training-pairs-v2.jsonl` carries three classes. Arm B trained on all three and
scored **fit 0.8253 / held-out 0.6812** -- a 8x collapse, with the fit/held-out gap widening from
0.083 to 0.144. Its ablation showed `deployed_top_k` was the dominant class, and it is
**query-specific by construction**: it is literally "the turns that beat gold on THESE queries", so
a model can memorise the turns instead of the pattern.

`cross_session` and `question_echo` describe a SHAPE. Default is pattern-only; `--all-classes` runs
the other arm so the choice is measured rather than asserted.

## Sequence length

Measured on the fit split: query + 2 candidates is 156 word pieces at the median, 268 at p90.
**89.1% fit in 256, 93.4% in 384.** Default 384; truncation is longest-first.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

PAIRS = REPO / "runs" / "session-m0c-m" / "training-pairs-v2.jsonl"
OUT_DIR = REPO / "models"
RESULT = REPO / "runs" / "session-m0c-m" / "duo-encoder.json"
RESULT_HO = REPO / "runs" / "session-m0c-m" / "duo-encoder-heldout.json"
BASE = "cross-encoder/ms-marco-MiniLM-L-6-v2"
NEAR_TIE = 0.084
PATTERN_CLASSES = ("cross_session", "question_echo")
SEED = 7


def set_seed(s: int) -> None:
    import torch

    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


def encode_triple(tok, question: str, a: str, b: str, max_len: int):
    """[CLS] q [SEP] A [SEP] B [SEP], segment 0 = q+A, segment 1 = B.

    BERT has two segment embeddings, so the boundary that gets a dedicated embedding is the one
    that matters: which text is candidate B. duoBERT uses the same assignment.

    Truncation is longest-first over the two CANDIDATES only -- the question is never cut, because
    it is 16 word pieces at the median and losing it would remove the thing being compared against.
    """
    q = tok.encode(question, add_special_tokens=False)
    ta = tok.encode(a, add_special_tokens=False)
    tb = tok.encode(b, add_special_tokens=False)
    room = max_len - 4 - len(q)
    while len(ta) + len(tb) > room and (ta or tb):
        if len(ta) >= len(tb):
            ta.pop()
        else:
            tb.pop()
    ids = [tok.cls_token_id] + q + [tok.sep_token_id] + ta + [tok.sep_token_id] + tb + [tok.sep_token_id]
    n0 = 1 + len(q) + 1 + len(ta) + 1          # [CLS] q [SEP] A [SEP]  -> segment 0
    types = [0] * n0 + [1] * (len(ids) - n0)
    mask = [1] * len(ids)
    pad = max_len - len(ids)
    return ids + [tok.pad_token_id] * pad, types + [0] * pad, mask + [0] * pad


def load_pairs(all_classes: bool) -> list[dict]:
    rows = []
    for line in PAIRS.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if all_classes or r["negative_class"] in PATTERN_CLASSES:
            rows.append(r)
    return rows


def train(args) -> Path:
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    set_seed(SEED)
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=1)
    model.cuda().train()

    rows = load_pairs(args.all_classes)
    train_rows = [r for r in rows if r["fold"] == "train"]
    val_rows = [r for r in rows if r["fold"] == "val"]
    print(f"pairs: {len(rows)}  train {len(train_rows)}  val {len(val_rows)}  "
          f"classes={'ALL' if args.all_classes else 'pattern-only'}")

    # BOTH ORDERINGS. Without this the model learns "always say A" and scores 81% knowing nothing.
    X, T, M, Y = [], [], [], []
    for r in train_rows:
        for a, b, y in ((r["positive"], r["negative"], 1.0), (r["negative"], r["positive"], 0.0)):
            i, t, m = encode_triple(tok, r["question"], a, b, args.max_len)
            X.append(i); T.append(t); M.append(m); Y.append(y)
    ds = TensorDataset(*[torch.tensor(v) for v in (X, T, M)], torch.tensor(Y, dtype=torch.float))
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, drop_last=True,
                    generator=torch.Generator().manual_seed(SEED))
    print(f"training examples (both orderings): {len(ds)}")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    lossf = torch.nn.BCEWithLogitsLoss()
    for ep in range(args.epochs):
        tot = 0.0
        for ids, types, mask, y in dl:
            opt.zero_grad()
            out = model(input_ids=ids.cuda(), token_type_ids=types.cuda(),
                        attention_mask=mask.cuda()).logits.squeeze(-1)
            loss = lossf(out, y.cuda())
            loss.backward(); opt.step()
            tot += float(loss)
        print(f"  epoch {ep + 1}: loss {tot / len(dl):.4f}")

    name = f"duo-L6-{'all' if args.all_classes else 'pattern'}"
    out = OUT_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out); tok.save_pretrained(out)
    print(f"saved {out}")
    return out


def evaluate(model_dir: Path, args) -> dict:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from reach_pools import load_pools, turn_texts
    from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order

    # Held-out is a consumable: one configuration, spent deliberately. The gate below
    # asserts the reconstruction reproduces the PUBLISHED number for whichever split is
    # read, so a wrong split silently scored would refuse rather than produce a plausible
    # figure about the wrong population.
    POOLS = (REPO / "runs" / "session-k" / "heldout") if args.heldout else FIT_POOLS
    EXPECT = 0.6725 if args.heldout else CONTROL_R1

    tok = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir)).cuda().eval()

    pools, _ = load_pools(POOLS)
    texts_all = turn_texts()
    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - EXPECT) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed R@1 {r1} != published {EXPECT}")
    print(f"control: {'HELD-OUT' if args.heldout else 'fit'} R@1 {r1}  ({len(pools)} queries)")

    @torch.no_grad()
    def prob(q: str, a: str, b: str) -> float:
        i, t, m = encode_triple(tok, q, a, b, args.max_len)
        o = model(input_ids=torch.tensor([i]).cuda(), token_type_ids=torch.tensor([t]).cuda(),
                  attention_mask=torch.tensor([m]).cuda()).logits.squeeze()
        return float(torch.sigmoid(o))

    rows, sym, lat = {}, [], []
    for n, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        txt = texts_all.get(qid, {})
        idxs = [int(i) for i in orders[qid][: args.top]]
        docs = [txt.get(pool.candidates[i].turn_id) or "" for i in idxs]
        k = len(idxs)
        t0 = time.perf_counter()
        wins = [0.0] * k
        wins_raw = [0.0] * k
        pab = {}
        for x in range(k):
            for y in range(x + 1, k):
                p = prob(pool.question, docs[x], docs[y])
                q2 = prob(pool.question, docs[y], docs[x])
                sym.append(p + q2)
                # **SYMMETRISED, and this is the fix the control forced.** Scoring one ordering
                # only leaves the model's position bias in the result: the first run measured
                # P(A>B)+P(B>A) = 1.1299 +/- 0.4794, a bias toward "A" plus real order-dependent
                # instability. Averaging the two directions cancels the bias by construction and
                # halves the variance of the instability. `wins_raw` keeps the one-directional
                # score so the two can be compared rather than the old number simply vanishing.
                p_sym = 0.5 * (p + (1.0 - q2))
                pab[(x, y)] = {"p_ab": p, "p_ba": q2, "p_sym": p_sym}
                wins[x] += p_sym; wins[y] += (1.0 - p_sym)
                wins_raw[x] += p; wins_raw[y] += (1.0 - p)
        lat.append((time.perf_counter() - t0) * 1000.0)
        rows[qid] = {
            "gold": [bool(pool.gold[i]) for i in idxs],
            "ce": [pool.candidates[i].rerank_score for i in idxs],
            "wins": wins,
            "wins_raw": wins_raw,
            "p_1v2": pab.get((0, 1)),
        }
        if n % 40 == 0:
            print(f"  {n}/{len(pools)}  {np.median(lat):.0f} ms/query  sym {np.mean(sym):.3f}")

    N = len(rows)
    symmetry = {"mean_p_ab_plus_p_ba": float(np.mean(sym)),
                "sd": float(np.std(sym)),
                "_pass": bool(abs(np.mean(sym) - 1.0) < 0.10),
                "_why": ("a pairwise model can score 81% by learning 'always say A'. if this is "
                         "not ~1.0 the model learned POSITION, not preference, and every accuracy "
                         "number below is meaningless")}
    print(f"\nSYMMETRY  P(A>B)+P(B>A) = {symmetry['mean_p_ab_plus_p_ba']:.4f} "
          f"+/- {symmetry['sd']:.4f}   {'PASS' if symmetry['_pass'] else 'FAIL'}")

    def score(key, label):
        g = l = corr = 0
        og = ol = on = 0
        for d in rows.values():
            j = int(np.argmax([key(d, i) for i in range(len(d["gold"]))]))
            corr += int(d["gold"][j])
            gap = (d["ce"][0] - d["ce"][1]) if None not in d["ce"][:2] else None
            outside = gap is not None and gap > NEAR_TIE
            if j != 0:
                if d["gold"][j] and not d["gold"][0]:
                    g += 1; og += int(outside)
                elif d["gold"][0] and not d["gold"][j]:
                    l += 1; ol += int(outside)
                elif outside:
                    on += 1
        return {"rule": label, "gained": g, "lost": l, "net": g - l,
                "r1": round(corr / N, 4), "delta": round(corr / N - r1, 4),
                "above_near_tie": {"g": og, "l": ol, "n": on}}

    arms = [
        score(lambda d, i: (d["ce"][i] if d["ce"][i] is not None else -1e9), "control (shipped)"),
        score(lambda d, i: d["wins"][i], "duo tournament (SYMMETRISED)"),
        score(lambda d, i: d["wins_raw"][i], "duo tournament (one-directional)"),
    ]
    for lam in (0.25, 0.5, 1.0, 2.0):
        arms.append(score(lambda d, i, l=lam: (d["ce"][i] if d["ce"][i] is not None else -1e9)
                          + l * d["wins"][i], f"ce + {lam}*duo"))

    print(f"\n{'rule':<30}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}   >0.084 g/l/n")
    for a in arms:
        o = a["above_near_tie"]
        print(f"{a['rule']:<30}{a['gained']:>6}{a['lost']:>6}{a['net']:>6}{a['r1']:>9.4f}"
              f"   {o['g']}/{o['l']}/{o['n']}")

    res = {"_what": "joint pairwise (duoBERT-style) reranker over the shipped top-k, fit split",
           "_measurement_only": True, "model": str(model_dir.name), "base": BASE,
           "max_len": args.max_len, "top": args.top, "seed": SEED,
           "classes": "all" if args.all_classes else "pattern-only",
           "control_fit_r1": r1, "symmetry": symmetry, "arms": arms,
           "ms_per_query": round(float(np.median(lat)), 1), "rows": rows}
    dest = RESULT_HO if args.heldout else RESULT
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(f"\n{np.median(lat):.0f} ms/query for {args.top} candidates "
          f"({args.top * (args.top - 1) // 2} pairs x2 for the symmetry probe)")
    print(f"wrote {dest.relative_to(REPO)}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--all-classes", action="store_true",
                    help="include deployed_top_k; default is pattern-only (see the docstring)")
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-len", type=int, default=384)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--heldout", action="store_true", help="SPEND A HELD-OUT READ")
    args = ap.parse_args()

    d = Path(args.model_dir) if args.model_dir else None
    if args.train:
        d = train(args)
    if args.eval:
        if d is None:
            raise SystemExit("--eval needs --train or --model-dir")
        evaluate(d, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
