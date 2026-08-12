"""WHY does the cross-encoder leave gold out of the top 3? A taxonomy of the surviving losses.

    PYTHONIOENCODING=utf-8 python tools/cond3_taxonomy.py

## Why this is now the only question that matters

Held-out, R@3 = 0.9825 (pruning) x 0.9956 (slate@30) x **0.9107 (cond@3)**. Pruning loses 4 and
removing it is measured harmful; the slate loses 1. **cond@3 loses 20 and is the entire wall.**
R@3 = 0.95 needs cond@3 = 0.9711.

Every prior attempt treated the reranker as a black box to be swapped, fused or re-thresholded.
27 mechanisms, one significant result. This asks the question those skipped: **when gold is sitting
in the ten candidates the model was handed and it still does not put it in the top three, what
KIND of case is it?**

The point is to stop optimising an average. If the 20 are one thing, that is a training target. If
they are five things, chasing the average is why nothing has moved.

## What is dumped, per losing case

  * category, gold's rank under the fusion, and how far it missed
  * the fused logit gap between gold and the candidate holding rank 3 -- a near-miss and a rout
    are different problems
  * gold's role and length, and the same for the three that beat it
  * whether gold is an ASSISTANT turn (the model was trained on user-question/passage pairs)
  * whether gold is TRUNCATED at 256 wordpieces (the answer clause may never be seen)
  * question-word echo: does the winner repeat the question's content words that gold lacks?
  * whether gold and the winner are near-duplicates (both state the same fact)
  * full text of gold and of the three that beat it, so the cases can be READ

**Reading the cases is the point.** Every finding in this session that survived came from reading;
every one that came from a statistic died on held-out.

## Split

**FIT is primary** -- it is the development split and reading it costs nothing. The held-out losses
are counted too, because the held-out read is already spent and re-reading its per-case structure
consumes nothing further; but no configuration is chosen on it.

## Gates

1. Shipped graph, depth 10, reproduces fit R@1 **0.7555** exactly.
2. The depth-10 cue slate equals the candidate set the binary actually reranked, 229/229.
3. The reconstructed cascade reproduces `cascade-squeeze.json`'s fit cond@3 of **0.9511** for the
   six-way fusion. Without that, the losses being dumped are a different set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from cascade_squeeze import L6J, MAX_SEQ, NARROW, RRF_K, SHIPPED, SLATE, W1, register_w1  # noqa
from correct_case_control import content_words, cue_only_order  # noqa: E402
from failure_forensics import turn_roles  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "cond3-taxonomy.json"
MD = REPO / "runs" / "session-m0c-m" / "cond3-taxonomy.md"
FIT_COND3 = 0.9511


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", type=Path, default=FIT_POOLS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--md", type=Path, default=MD)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, _ = load_pools(args.pools)
    texts, roles = turn_texts(), turn_roles()
    n = len(pools)
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    questions = {c.query_id: c.question for c in corpus.cases}
    answers = {c.query_id: c.gold_answer for c in corpus.cases}
    is_fit = args.pools == FIT_POOLS

    ship = {q: shipped_order(p) for q, p in pools.items()}
    r1 = round(sum(int(p.gold[int(ship[q][0])]) for q, p in pools.items()) / n, 4)
    if is_fit and abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING (GATE 1). fit R@1 {r1}; published {CONTROL_R1}.")
    cue = {q: [int(v) for v in cue_only_order(p)] for q, p in pools.items()}
    exact = sum(set(cue[q][:10]) == {i for i, c in enumerate(p.candidates)
                                     if c.rerank_score is not None} for q, p in pools.items())
    if exact != n:
        raise SystemExit(f"REFUSING (GATE 2). slate mismatch on {n - exact}.")
    print(f"GATE 1  R@1 {r1}   GATE 2  slate {exact}/{n}   GATE 3  registered {list(register_w1())}")

    slate = {q: cue[q][:SLATE] for q in pools}
    ce = R.load(SHIPPED, provider=args.provider)
    narrow = {}
    for q, p in pools.items():
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate[q]]
        s = ce.score_batch(p.question, docs, MAX_SEQ)
        narrow[q] = [i for _, i in sorted(zip(s, slate[q]), key=lambda t: (-t[0], t[1]))][:NARROW]

    models = [SHIPPED, L6J] + W1
    ranks_by_model = {}
    for nm in models:
        c = R.load(nm, provider=args.provider)
        o = {}
        for q, p in pools.items():
            docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in narrow[q]]
            s = c.score_batch(p.question, docs, MAX_SEQ)
            o[q] = {i: r for r, i in enumerate(
                sorted(narrow[q], key=lambda i: (-dict(zip(narrow[q], s))[i], i)))}
        ranks_by_model[nm] = o

    fused = {}
    for q in pools:
        sc = {i: sum(1.0 / (RRF_K + ranks_by_model[nm][q][i] + 1) for nm in models)
              for i in narrow[q]}
        fused[q] = sorted(narrow[q], key=lambda i: (-sc[i], i))

    in_slate = [q for q in pools if any(pools[q].gold[i] for i in slate[q])]
    hit3 = [q for q in in_slate if any(pools[q].gold[int(v)] for v in fused[q][:3])]
    cond3 = len(hit3) / len(in_slate)
    print(f"        cond@3 {cond3:.4f} over {len(in_slate)} in-slate "
          f"({'fit target 0.9511' if is_fit else 'held-out'})")
    if is_fit and abs(cond3 - FIT_COND3) > 0.006:
        raise SystemExit(f"REFUSING (GATE 3). cond@3 {cond3:.4f} vs cascade-squeeze's {FIT_COND3}.")

    lost = [q for q in in_slate if q not in hit3]
    print(f"        LOST at cond@3: {len(lost)}\n")

    def wp(t):
        return len(re.findall(r"\w+|[^\w\s]", t or ""))

    recs = []
    for q in sorted(lost):
        p = pools[q]
        gi = [i for i in narrow[q] if p.gold[i]]
        gpos = min(fused[q].index(i) for i in gi) if gi else None
        gtext = texts.get(q, {}).get(p.candidates[gi[0]].turn_id) or "" if gi else ""
        qw = content_words(questions.get(q) or "")
        gw = content_words(gtext)
        top3 = []
        for r, v in enumerate(fused[q][:3], 1):
            t = texts.get(q, {}).get(p.candidates[int(v)].turn_id) or ""
            tw = content_words(t)
            top3.append({
                "rank": r, "role": roles.get(q, {}).get(p.candidates[int(v)].turn_id, "?"),
                "words": len(t.split()), "wordpieces": wp(t),
                "echo_over_gold": len((qw & tw) - gw),
                "jaccard_with_gold": round(len(gw & tw) / max(1, len(gw | tw)), 3),
                "text": t,
            })
        recs.append({
            "query_id": q, "category": p.category,
            "gold_rank_fused": gpos + 1 if gpos is not None else None,
            "gold_role": roles.get(q, {}).get(p.candidates[gi[0]].turn_id, "?") if gi else "?",
            "gold_words": len(gtext.split()), "gold_wordpieces": wp(gtext),
            "gold_truncated_at_256": wp(gtext) > 256,
            "gold_is_assistant": (roles.get(q, {}).get(p.candidates[gi[0]].turn_id) == "assistant")
                                 if gi else False,
            "gold_echo_of_question": len(qw & gw),
            "n_models_placing_gold_top3": sum(
                1 for nm in models if gi and min(ranks_by_model[nm][q][i] for i in gi) < 3),
            "question": questions.get(q), "gold_answer": answers.get(q), "gold_text": gtext,
            "top3": top3,
        })

    print(f"{'query':16s} {'category':26s} {'gRank':>5} {'gRole':>9} {'gWP':>5} "
          f"{'trunc':>6} {'echo':>5} {'#models@3':>9}")
    for r in recs:
        print(f"{r['query_id']:16s} {r['category']:26s} {str(r['gold_rank_fused']):>5} "
              f"{r['gold_role']:>9} {r['gold_wordpieces']:>5} "
              f"{'YES' if r['gold_truncated_at_256'] else '-':>6} "
              f"{r['gold_echo_of_question']:>5} {r['n_models_placing_gold_top3']:>9}")

    print("\nAGGREGATES over the lost set")
    print(f"  category      {dict(Counter(r['category'] for r in recs))}")
    print(f"  gold role     {dict(Counter(r['gold_role'] for r in recs))}")
    print(f"  gold rank     {dict(Counter(r['gold_rank_fused'] for r in recs))}")
    print(f"  truncated     {sum(r['gold_truncated_at_256'] for r in recs)}/{len(recs)}")
    print(f"  no model got it top-3: "
          f"{sum(1 for r in recs if r['n_models_placing_gold_top3'] == 0)}/{len(recs)}")
    base_role = Counter()
    for q in in_slate:
        gi = [i for i in narrow[q] if pools[q].gold[i]]
        if gi:
            base_role[roles.get(q, {}).get(pools[q].candidates[gi[0]].turn_id, "?")] += 1
    print(f"  BASE RATE gold role over all in-slate: {dict(base_role)}")
    base_cat = Counter(pools[q].category for q in in_slate)
    print("  category enrichment (lost share / base share):")
    for c, k in sorted(Counter(r["category"] for r in recs).items(),
                       key=lambda t: -t[1] / base_cat[t[0]]):
        print(f"    {c:28s} {k}/{base_cat[c]} = {k / base_cat[c]:.3f}  "
              f"({k / base_cat[c] / (len(recs) / len(in_slate)):.2f}x)")

    lines = [f"# cond@3 losses — {len(recs)} cases ({'fit' if is_fit else 'held-out'})", ""]
    for r in recs:
        lines += [f"## {r['query_id']} · {r['category']} · gold at fused rank "
                  f"{r['gold_rank_fused']} · {r['n_models_placing_gold_top3']}/6 models had it top-3",
                  f"**Q:** {r['question']}", f"**A:** {r['gold_answer']}",
                  f"**GOLD** [{r['gold_role']}, {r['gold_wordpieces']} wp]: {r['gold_text'][:700]}", ""]
        for t in r["top3"]:
            lines.append(f"**{t['rank']}.** [{t['role']}, {t['wordpieces']} wp, "
                         f"echo+{t['echo_over_gold']}, jac {t['jaccard_with_gold']}] {t['text'][:500]}")
        lines.append("")
    args.md.write_text("\n".join(lines), encoding="utf-8")
    args.out.write_text(json.dumps(
        {"_split": "fit" if is_fit else "heldout", "cond3": round(cond3, 4),
         "in_slate": len(in_slate), "lost": len(recs), "records": recs},
        indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.name} and {args.md.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
