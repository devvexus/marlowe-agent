"""Session I, P1 + P2 — the truncation defect fix, and arm 0 at minimum breadth.

**P1 is a defect fix, not an arm.** `rerank.rs` pins `MAX_SEQ_LEN = 256`. On the fit split the
query plus the gold turn fits in 256 in only 211/229 = 0.9214 of cases, so the shipped binary
scores 7.86% of gold turns on a fragment and **R@1 0.5764 was measured on that configuration**.
Raising the sequence length to 512 changes nothing else: same model, same digest, same pruning,
same gate key, same depth, no context.

**P2 is the question that fix answers.** Phase 0.2 found the rank-1 distractor on failures is 47.1%
assistant-authored against a 12.3% base rate, and 131 word pieces at the median against gold's 70 --
with p75 406 and p95 654, both far beyond the 256 cap. Two hypotheses, registered before this ran:

  (a) the reranker genuinely prefers long passages -- a known MS MARCO artifact;
  (b) truncation MANUFACTURES the score, by cutting a long distractor down to its most query-like
      opening.

They are distinguished by the rank-1 distractor's length and authorship distribution at BOTH
sequence lengths. If long assistant turns stop dominating failures at 512, (b) holds and the defect
fix is itself the finding. If the distribution is unchanged, (a) holds, the bias belongs to the
model rather than to the configuration, and the honest report is that the fix did not explain the
failures.

**The contrast is paired and its power is measured, not assumed** (ADR-014). Exact McNemar is a
binomial over the discordant pairs only, so the smallest attainable two-sided p is `2/2^n` -- 0.0625
at n=5 and 0.03125 at n=6. The discordant count is reported beside every p-value, and if it is below
6 the p-value is declared unattainable in advance rather than quoted as evidence of absence.

    python tools/session_i_seqlen.py --split fit
    python tools/session_i_seqlen.py --split heldout
    python tools/session_i_seqlen.py --split fit --models ms-marco-MiniLM-L-6-v2 --seq 512
"""

from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import time
from collections import Counter

import numpy as np

from reach_pools import REPO, SPLIT_PATH, Pool, turn_texts
from reach_rerank_fit import PREREG_PATH as SESSION_H_PREREG, gate_order, top1_is_gold
from reach_session_h_pruning import derived_keys, prune_mask
from session_h_pools import fidelity_gate, load_split_pools
from session_i_rerankers import SHIPPED_INT8, load

BUDGET = 10
MIN_DISCORDANT_FOR_ALPHA = 6      # 2/2^6 = 0.03125, the first n at which p<0.05 is attainable


def turn_roles() -> dict[str, dict[str, str]]:
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    return {
        str(inst["question_id"]): {
            f"{sid}-{t}": str(turn.get("role", "?"))
            for sid, sess in zip(inst["haystack_session_ids"], inst["haystack_sessions"])
            for t, turn in enumerate(sess)
        }
        for inst in raw
    }


def shipped_slate(pool: Pool, gap_ms: int, prune_n: int) -> np.ndarray:
    """Unchanged from Phase 0.1. Slate membership does not depend on the sequence length."""
    keys = derived_keys(pool, gap_ms)
    pruned = np.flatnonzero(prune_mask(pool, keys, prune_n))
    return pruned[gate_order(pool, pruned)[:BUDGET]]


def mcnemar_exact(b: int, c: int) -> tuple[float, float]:
    """Two-sided exact McNemar, and the smallest p this many discordant pairs could ever produce."""
    n = b + c
    if n == 0:
        return 1.0, 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail), min(1.0, 2 / (2 ** n))


def measure(ce, pools, texts, roles, seq_len, gap_ms, prune_n, label):
    rows, lat = [], []
    for n_done, pool in enumerate(pools.values(), 1):
        per_turn, per_role = texts.get(pool.query_id, {}), roles.get(pool.query_id, {})
        slate = shipped_slate(pool, gap_ms, prune_n)
        scores = []
        for i in slate:
            tid = pool.candidates[int(i)].turn_id or ""
            t0 = time.perf_counter()
            scores.append(ce.score(pool.question, per_turn.get(tid, ""), seq_len))
            lat.append((time.perf_counter() - t0) * 1000.0)
        order = np.argsort(-np.array(scores), kind="stable")
        ranked = slate[order]
        top1 = int(ranked[0])
        t1_tid = pool.candidates[top1].turn_id or ""
        rows.append({
            "query_id": pool.query_id,
            "category": pool.category,
            "gold_in_slate": bool(pool.gold[slate].any()),
            "top1_is_gold": top1_is_gold(pool, slate, order),
            "rank1_role": per_role.get(t1_tid, "?"),
            "rank1_wordpieces": ce.wordpieces(per_turn.get(t1_tid, "")),
        })
        if n_done % 100 == 0:
            print(f"    {label} seq {seq_len}: {n_done}/{len(pools)}")

    n = len(rows)
    hits = sum(r["top1_is_gold"] for r in rows)
    present = sum(r["gold_in_slate"] for r in rows)
    lat.sort()
    fails = [r for r in rows if not r["top1_is_gold"]]
    q = lambda v, p: float(np.percentile(v, p)) if v else float("nan")  # noqa: E731
    wl = [r["rank1_wordpieces"] for r in fails]
    role = Counter(r["rank1_role"] for r in fails)
    return {
        "seq_len": seq_len, "cases": n,
        "r_at_1": round(hits / n, 4),
        "input_recall": round(present / n, 4),
        "conditional_accuracy": round(hits / present, 4) if present else None,
        "ms_per_pair": {"median": round(statistics.median(lat), 3),
                        "p95": round(lat[max(0, int(round(0.95 * len(lat))) - 1)], 3)},
        "rank1_on_failures": {
            "n": len(fails),
            "assistant_share": round(role.get("assistant", 0) / len(fails), 4) if fails else None,
            "wordpieces": {"median": q(wl, 50), "p75": q(wl, 75), "p95": q(wl, 95)},
        },
        "_per_case": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["fit", "heldout"], default="fit")
    ap.add_argument("--models", nargs="+", default=[SHIPPED_INT8])
    ap.add_argument("--seq", nargs="+", type=int, default=[256, 512])
    args = ap.parse_args()

    prereg = json.loads(io.open(SESSION_H_PREREG, encoding="utf-8").read())
    gap_ms = prereg["frozen_parameters"]["session_gap_ms"]["value"]
    prune_n = prereg["frozen_parameters"]["prune_N"]["value"]

    fit, heldout, _ = load_split_pools()
    ok, gate = fidelity_gate(heldout)
    if not ok:
        print("Reconstruction licensing gate FAILED.")
        return 1
    pools = fit if args.split == "fit" else heldout
    print(f"Licensing gate PASSED. {args.split} split: {len(pools)} pools.\n")

    texts, roles = turn_texts(), turn_roles()
    results: dict[str, dict] = {}

    for name in args.models:
        ce = load(name)
        print(f"{name}  ({ce.arch}, ~{ce.params_m}M, max_seq {ce.max_seq_supported}, "
              f"digest {ce.digest[:16]}...)")
        for seq in args.seq:
            if seq > ce.max_seq_supported:
                print(f"  seq {seq} exceeds this model's positional limit; SKIPPED")
                continue
            r = measure(ce, pools, texts, roles, seq, gap_ms, prune_n, name)
            results[f"{name}@{seq}"] = r
            print(f"  seq {seq:>4}  R@1 {r['r_at_1']:.4f}  input recall {r['input_recall']:.4f}  "
                  f"cond.acc {r['conditional_accuracy']:.4f}  "
                  f"{r['ms_per_pair']['median']:.1f} ms/pair")
        print()

    # ---- the registered contrast, paired, with its power stated -----------------------------
    contrasts = {}
    keys = list(results)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            ra = {r["query_id"]: r["top1_is_gold"] for r in results[a]["_per_case"]}
            rb = {r["query_id"]: r["top1_is_gold"] for r in results[b]["_per_case"]}
            shared = sorted(set(ra) & set(rb))
            b_wins = sum(1 for q in shared if rb[q] and not ra[q])
            a_wins = sum(1 for q in shared if ra[q] and not rb[q])
            n_disc = a_wins + b_wins
            p, p_min = mcnemar_exact(a_wins, b_wins)
            attainable = n_disc >= MIN_DISCORDANT_FOR_ALPHA
            contrasts[f"{b} vs {a}"] = {
                "delta_r_at_1": round(results[b]["r_at_1"] - results[a]["r_at_1"], 4),
                "delta_conditional_accuracy": round(
                    results[b]["conditional_accuracy"] - results[a]["conditional_accuracy"], 4),
                "gained": b_wins, "lost": a_wins, "discordant": n_disc,
                "mcnemar_exact_p": round(p, 4),
                "smallest_attainable_p_at_this_n": round(p_min, 4),
                "alpha_005_attainable": bool(attainable),
                "_adr_013_read_varies": bool(n_disc > 0 and a_wins > 0 and b_wins > 0),
            }

    print("=" * 78)
    print("REGISTERED CONTRASTS -- paired, with power stated (ADR-014)")
    print("=" * 78)
    for name, c in contrasts.items():
        print(f"  {name}")
        print(f"    delta R@1 {c['delta_r_at_1']:+.4f}   "
              f"delta conditional accuracy {c['delta_conditional_accuracy']:+.4f}")
        print(f"    discordant {c['discordant']} (gained {c['gained']}, lost {c['lost']})   "
              f"exact p {c['mcnemar_exact_p']:.4f}")
        if not c["alpha_005_attainable"]:
            print(f"    ALPHA 0.05 UNATTAINABLE at n={c['discordant']}: the smallest possible p "
                  f"here is {c['smallest_attainable_p_at_this_n']:.4f}.")
            print(f"    The p-value is NOT evidence of absence. The delta carries the verdict.")
        else:
            print(f"    alpha 0.05 attainable (smallest possible p at this n: "
                  f"{c['smallest_attainable_p_at_this_n']:.4f})")

    print("\n" + "=" * 78)
    print("P2 -- WHAT SITS AT RANK 1 ON FAILURES, at each sequence length")
    print("=" * 78)
    print(f"  {'configuration':>34} {'fails':>6} {'assistant':>10} {'wp med':>7} {'wp p75':>7} {'wp p95':>7}")
    for k, r in results.items():
        p = r["rank1_on_failures"]
        print(f"  {k:>34} {p['n']:>6} {p['assistant_share']:>10.1%} "
              f"{p['wordpieces']['median']:>7.0f} {p['wordpieces']['p75']:>7.0f} "
              f"{p['wordpieces']['p95']:>7.0f}")
    print("\n  Registered before this ran: if long assistant turns stop dominating failures at 512,")
    print("  hypothesis (b) holds -- truncation was manufacturing the score. If the distribution is")
    print("  unchanged, hypothesis (a) holds and the bias belongs to the model, not the config.")

    # Named by MODEL as well as split. An earlier version wrote one file per split, so a second
    # invocation with a different model silently overwrote the first one's results -- the artifact
    # kept the filename and lost the numbers.
    tag = "-".join(m.replace("ms-marco-MiniLM-", "").replace("-v2", "") for m in args.models)
    out = REPO / "runs" / "session-i" / f"seqlen-{args.split}-{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "Session I P1 (truncation defect fix) and P2 (arm 0, minimum breadth).",
        "split": args.split,
        "slate": {"prune_N": prune_n, "session_gap_ms": gap_ms, "budget": BUDGET, "window": "none"},
        "adr_014_floor": {"alpha": 0.05, "min_discordant_n": MIN_DISCORDANT_FOR_ALPHA,
                          "_why": "exact McNemar's smallest two-sided p is 2/2^n"},
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "_per_case"}
                    for k, v in results.items()},
        "contrasts": contrasts,
        "_per_case": {k: v["_per_case"] for k, v in results.items()},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
