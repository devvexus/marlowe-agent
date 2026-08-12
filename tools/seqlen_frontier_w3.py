"""M0c Session M, W3 — does lifting the 256 sequence cap move fit R@1?

The shipped cross-encoder scores at `max_seq = 256`. That number is inherited from the int8 era:
ADR-015 bound the quantized graph to `[1, 256]` in EVERY dimension because re-padding bit-identical
ids moved int8 logits by a median 0.0109 and flipped top-1 in 15% of cases. Session K moved the
shipped path to f32, which removed quantization from the scored path — so the *reason* for the cap
has expired, while the cap has not.

**ADR-015 is re-opened on each graph and closed here before any R@1 cell is read.** A sequence
length change makes a graph a different scorer until padding invariance, batch invariance and
determinism are re-measured ON THAT GRAPH at THAT length. "f32 graphs were invariant" is a class
claim and is never inherited.

REGISTERED PREDICTION (written before this ran, recorded verbatim in the output artifact):
  * padding invariance is 0.000000 on both f32 graphs at every length;
  * fit R@1 moves by -0.01 to +0.02 at 512 -- small, because ~11% of golds truncate but the
    competitors truncate at a similar rate;
  * if it moves, it moves UP, because a truncated gold loses its answer clause while a truncated
    distractor loses only more of the same topic. A flat number refutes that premise and must be
    reported as refuting it;
  * latency roughly doubles 256 -> 512 and is irrelevant against a 300 ms budget.

Nothing here is reimplemented. The ranking key (`shipped_order`), the re-ranked order
(`reordered`), the current-gold classifier and the scorer are imported from
`sweep_reranker_frontier`; the loader, determinism and batch-invariance probes from
`session_i_rerankers`; the 256->512 padding probe from `session_j_verify_export`, which this file's
length-parameterized probe is CROSS-CHECKED against at 512 rather than replacing.

    python tools/seqlen_frontier_w3.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import turn_texts  # noqa: E402
from session_j_verify_export import padding_invariance as SESSION_J_PADDING  # noqa: E402
from sweep_reranker_frontier import (  # noqa: E402
    CONTROL_R1,
    CONTROL_R1_CURRENT,
    FIT_POOLS,
    MAX_SEQ as SHIPPED_MAX_SEQ,
    OUT_DIR,
    current_gold_ids,
    evaluate,
    reordered,
    shipped_order,
)
from reach_pools import load_pools  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

PREDICTION = {
    "padding_invariance": "0.000000 on both f32 graphs at EVERY candidate length",
    "fit_r_at_1_delta_at_512": "-0.01 to +0.02",
    "sign_if_it_moves": "UP -- a truncated gold loses its answer clause, a truncated distractor "
                        "loses only more of the same topic. Flat refutes the premise, and that "
                        "must be said.",
    "latency": "roughly doubles 256->512; irrelevant at 14.7 ms P95 against a 300 ms budget",
}

MODELS = ["ms-marco-MiniLM-L-2-v2-ft-session-j", "ms-marco-MiniLM-L-6-v2-ft-session-j"]
LENGTHS = [256, 320, 384, 512]
DEPTHS = [10, 20]


# ---------------------------------------------------------------------------------------------
# ADR-015's three checks, parameterized by length. Each is measured PER GRAPH at EVERY length.
# ---------------------------------------------------------------------------------------------

def padding_invariance_at(ce, pairs: list[tuple[str, str]], lengths: list[int]) -> dict:
    """ADR-015. Bit-identical token ids, re-padded to each candidate length: only SHAPE differs.

    The pairs are REAL (question, turn) pairs from the fit split whose natural wordpiece length
    fits inside the smallest candidate length, so no cap truncates them and the ids are identical
    across every cell. A pair that truncated differently at two lengths would be a content change
    measured as a shape change.
    """
    tok = ce.tokenizer
    out: dict[str, dict] = {}
    natural = []
    for q, d in pairs:
        tok.no_truncation()
        tok.no_padding()
        enc = tok.encode(q, d)
        natural.append((list(enc.ids), list(enc.attention_mask), list(enc.type_ids)))

    def run(ids, mask, types):
        feed = {"input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.array([mask], dtype=np.int64)}
        if "token_type_ids" in ce.input_names:
            feed["token_type_ids"] = np.array([types], dtype=np.int64)
        o = np.asarray(ce.session.run(None, feed)[0]).reshape(-1)
        return float(o[0]) if ce.output_dim == 1 else float(o[1] - o[0])

    ref = [run(i, m, t) for i, m, t in natural]
    for L in lengths:
        deltas = []
        for (ids, mask, types), r in zip(natural, ref):
            k = len(ids)
            assert k <= L, f"pair of {k} wordpieces does not fit in {L}; content would change"
            v = run(ids + [0] * (L - k), mask + [0] * (L - k), types + [0] * (L - k))
            deltas.append(abs(v - r))
        d = np.array(deltas)
        out[str(L)] = {
            "pairs": len(deltas),
            "max_abs_delta": float(d.max()),
            "median_abs_delta": float(np.median(d)),
            "nonzero": int((d > 0).sum()),
            "invariant": bool(d.max() == 0.0),
        }
    return out


def batch_invariance_at(ce, query: str, docs: list[str], L: int) -> dict:
    """R.batch_invariance's measurement, at an arbitrary length. Same construction, same reduce."""
    encs = [ce.encode(query, d, L) for d in docs]
    feed = {
        "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
    }
    if "token_type_ids" in ce.input_names:
        feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)

    def reduce(arr):
        arr = np.asarray(arr)
        return arr.reshape(-1) if ce.output_dim == 1 else arr[:, 1] - arr[:, 0]

    batched = reduce(ce.session.run(None, feed)[0])
    singles = np.array([
        reduce(ce.session.run(None, {k: v[i:i + 1] for k, v in feed.items()})[0])[0]
        for i in range(len(docs))
    ])
    return {"max_abs_diff": float(np.abs(batched - singles).max()),
            "identical": bool(np.array_equal(batched, singles)), "pairs": len(docs)}


def determinism_at(ce, query: str, doc: str, L: int, repeats: int = 3) -> dict:
    vals = [ce.score(query, doc, L) for _ in range(repeats)]
    return {"values": vals, "identical": bool(len(set(vals)) == 1)}


# ---------------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--lengths", nargs="+", type=int, default=LENGTHS)
    ap.add_argument("--depths", nargs="+", type=int, default=DEPTHS)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT_DIR / "seqlen-frontier-w3.json"))
    args = ap.parse_args()

    assert SHIPPED_MAX_SEQ == 256, "the control length is the shipped one; it is not a choice here"
    assert args.lengths[0] == 256, "256 is the control cell and is scored first"

    pools, stats = load_pools(FIT_POOLS)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = current_gold_ids(corpus)
    texts = turn_texts()

    # ---- the gate, before anything else is read ------------------------------------------
    baseline_order = {qid: shipped_order(p) for qid, p in pools.items()}
    control = evaluate(pools, baseline_order, gold_current)
    print(f"\nGATE  shipped key, depth 10: R@1 {control['R@1']}  (published {CONTROL_R1})   "
          f"R@1_current {control['R@1_current']}  (published {CONTROL_R1_CURRENT})")
    if abs(control["R@1"] - CONTROL_R1) >= 1e-9:
        raise SystemExit(
            f"REFUSING. Reconstruction reads R@1 {control['R@1']}, published fit is {CONTROL_R1}."
        )
    print("GATE PASSED -- the reconstruction reproduces the published fit R@1 exactly.\n")

    # ---- truncation rates, per length, gold vs competitor ---------------------------------
    # `competitor` is the highest-ranked NON-gold candidate in the depth-10 slate under the shipped
    # pre-rerank key -- the same object control.json names, and the thing a longer cap would also
    # feed more of. Measured with each graph's own tokenizer; the two share a WordPiece vocab but
    # that is asserted by the numbers agreeing, not assumed.
    results: dict[str, dict] = {}
    per_case_out: dict[str, dict] = {}

    for name in args.models:
        ce = R.load(name, provider=args.provider)
        print(f"{name}  ({ce.arch}, ~{ce.params_m}M, positional limit {ce.max_seq_supported}, "
              f"digest {ce.digest[:16]}...)  provider {ce.session.get_providers()[0]}")
        for L in args.lengths:
            if L > ce.max_seq_supported:
                raise SystemExit(f"{name}: {L} exceeds the positional limit {ce.max_seq_supported}")

        # ---- ADR-015, re-opened and closed on THIS graph ---------------------------------
        smoke = R.smoke_test(ce)
        if not smoke["pass"]:
            raise SystemExit(f"{name}: discrimination smoke test failed; refused")

        # Real fit pairs that fit inside the SMALLEST candidate length, so ids are bit-identical.
        probe_pairs = []
        for qid, pool in pools.items():
            base = baseline_order[qid]
            for i in base[:3]:
                doc = texts.get(qid, {}).get(pool.candidates[int(i)].turn_id) or ""
                if not doc:
                    continue
                tok = ce.tokenizer
                tok.no_truncation()
                tok.no_padding()
                if len(tok.encode(pool.question, doc).ids) <= min(args.lengths):
                    probe_pairs.append((pool.question, doc))
            if len(probe_pairs) >= 60:
                break
        probe_pairs = probe_pairs[:60]

        pad = padding_invariance_at(ce, probe_pairs, args.lengths)
        session_j_cross = SESSION_J_PADDING(ce)   # the existing 256->512 probe, unmodified
        batch = {str(L): batch_invariance_at(
            ce, R.QUERY, [f"I moved off Postgres in April, attempt number {i}." for i in range(8)], L
        ) for L in args.lengths}
        det = {str(L): determinism_at(ce, R.QUERY, R.RELEVANT, L) for L in args.lengths}

        print(f"  ADR-015 on {name}:")
        for L in args.lengths:
            print(f"    seq {L:>4}  padding max|d| {pad[str(L)]['max_abs_delta']:.6f}"
                  f"   batch max|d| {batch[str(L)]['max_abs_diff']:.6f}"
                  f"   determinism {'IDENTICAL' if det[str(L)]['identical'] else 'VARIES'}")
        print(f"    cross-check, session_j_verify_export.padding_invariance (256->512): "
              f"max {session_j_cross['max_abs_delta']:.6f} over {session_j_cross['pairs']} pairs")
        all_invariant = all(pad[str(L)]["invariant"] for L in args.lengths)
        if not all_invariant:
            print("    *** PADDING INVARIANCE IS NOT 0.000000. Every cell below on this graph is "
                  "a DIFFERENT SCORER, not a comparable one. ***")

        # ---- truncation rates over the real slates ----------------------------------------
        tok = ce.tokenizer
        gold_lens, comp_lens = [], []
        case_gold_len: dict[str, int] = {}
        for qid, pool in pools.items():
            base = baseline_order[qid]
            slate = [int(i) for i in base[:max(args.depths)]]
            tok.no_truncation()
            tok.no_padding()
            best_g, best_c = None, None
            for rank, i in enumerate(slate[:10]):
                c = pool.candidates[i]
                doc = texts.get(qid, {}).get(c.turn_id) or ""
                n = len(tok.encode(pool.question, doc).ids)
                if c.is_gold and best_g is None:
                    best_g = n
                if (not c.is_gold) and best_c is None:
                    best_c = n
            if best_g is not None:
                gold_lens.append(best_g)
                case_gold_len[qid] = best_g
            if best_c is not None:
                comp_lens.append(best_c)
        gl, cl = np.array(gold_lens), np.array(comp_lens)
        trunc = {str(L): {"gold": round(float((gl > L).mean()), 4),
                          "competitor": round(float((cl > L).mean()), 4),
                          "gold_n": int(gl.size), "competitor_n": int(cl.size)}
                 for L in args.lengths}
        print(f"  truncation rate (top-gold / top-competitor in the depth-10 slate):")
        for L in args.lengths:
            print(f"    seq {L:>4}  gold {trunc[str(L)]['gold']:.4f}   "
                  f"competitor {trunc[str(L)]['competitor']:.4f}")

        # ---- the cells -------------------------------------------------------------------
        for depth in args.depths:
            for L in args.lengths:
                order_by_qid, ms, recall = {}, [], 0
                outcomes = {}
                for qid, pool in pools.items():
                    base = baseline_order[qid]
                    slate = [int(i) for i in base[:depth]]
                    docs = [texts.get(qid, {}).get(pool.candidates[i].turn_id) or "" for i in slate]
                    t0 = time.perf_counter()
                    logits = ce.score_batch(pool.question, docs, L)
                    ms.append((time.perf_counter() - t0) * 1000.0)
                    o = reordered(pool, slate, logits)
                    order_by_qid[qid] = o
                    recall += int(any(pool.gold[i] for i in slate))
                    outcomes[qid] = bool(pool.gold[o[0]])
                got = evaluate(pools, order_by_qid, gold_current)
                ir = recall / len(pools)
                key = f"{name}@d{depth}@{L}"
                results[key] = {
                    "model": name, "depth": depth, "max_seq": L,
                    "R@1": got["R@1"], "R@1_current": got["R@1_current"], "R@5": got["R@5"],
                    "input_recall": round(ir, 4),
                    "conditional_accuracy": round(got["R@1"] / ir, 4) if ir else 0.0,
                    "rerank_ms_p50": round(float(np.percentile(ms, 50)), 2),
                    "rerank_ms_p95": round(float(np.percentile(ms, 95)), 2),
                    "per_category": got["per_category"],
                }
                per_case_out[key] = outcomes
                print(f"  d{depth:<3} seq {L:>4}  R@1 {got['R@1']:.4f}  cur "
                      f"{got['R@1_current']:.4f}  ir {ir:.4f}  "
                      f"ca {results[key]['conditional_accuracy']:.4f}  "
                      f"{results[key]['rerank_ms_p50']:6.2f} ms p50")

        results[f"_gates::{name}"] = {
            "smoke": smoke, "padding_invariance": pad, "batch_invariance": batch,
            "determinism": det, "truncation_rate": trunc,
            "session_j_padding_cross_check_256_to_512": session_j_cross,
            "all_lengths_padding_invariant": all_invariant,
        }
        results[f"_gold_pair_wordpieces::{name}"] = case_gold_len
        print()

    # ---- the mechanism's own signature ---------------------------------------------------
    print("=" * 90)
    print("TRUNCATED-GOLD SUBGROUP -- cases whose top gold pair exceeds 256, outcome 256 vs 512")
    print("=" * 90)
    subgroups = {}
    for name in args.models:
        lens = results[f"_gold_pair_wordpieces::{name}"]
        trunc_ids = {q for q, n in lens.items() if n > 256}
        for depth in args.depths:
            a = per_case_out[f"{name}@d{depth}@256"]
            b = per_case_out[f"{name}@d{depth}@512"]
            shared = sorted(set(a) & set(b))
            inside = [q for q in shared if q in trunc_ids]
            outside = [q for q in shared if q not in trunc_ids]

            def tab(ids):
                g = sum(1 for q in ids if b[q] and not a[q])
                l = sum(1 for q in ids if a[q] and not b[q])
                return {"n": len(ids), "gained": g, "lost": l, "net": g - l}

            row = {"truncated_gold": tab(inside), "untruncated_gold": tab(outside),
                   "all": tab(shared), "n_truncated_gold_cases": len(trunc_ids)}
            subgroups[f"{name}@d{depth}"] = row
            print(f"  {name} d{depth}  (gold truncated at 256 in {len(trunc_ids)}/{len(shared)} "
                  f"cases)")
            for k in ("truncated_gold", "untruncated_gold", "all"):
                t = row[k]
                print(f"    {k:<18} n {t['n']:>4}  gained {t['gained']:>3}  lost {t['lost']:>3}  "
                      f"net {t['net']:+d}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "M0c Session M W3 -- sequence cap 256 vs 320/384/512, FIT split, both fine-tunes.",
        "_registered_prediction": PREDICTION,
        "_adr_015": "re-opened per graph; padding/batch/determinism measured at EVERY length below",
        "provider": args.provider,
        "gate": {"R@1": control["R@1"], "published": CONTROL_R1,
                 "R@1_current": control["R@1_current"], "published_current": CONTROL_R1_CURRENT},
        "pools": stats,
        "cells": {k: v for k, v in results.items() if not k.startswith("_")},
        "gates": {k: v for k, v in results.items() if k.startswith("_gates::")},
        "truncated_gold_subgroup": subgroups,
        "_per_case": per_case_out,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
