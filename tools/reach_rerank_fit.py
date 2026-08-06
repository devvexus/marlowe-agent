"""Session H, Phase 1 — the cross-encoder run offline on the FIT split.

Two registered instrument checks, plus the fit-split answer to the registered question. All on
fit; held-out is not touched. Running the instrument checks on the fit split costs no held-out
power, which is the point of doing them here.

**ADR-010 — is the reranker capped at the either-cue oracle?** Sessions D and E both shipped a
fusion into that cap. A fusion that only ARBITRATES between two cues cannot beat the either-cue
oracle, because it can only pick a candidate one of them already ranked first. A cross-encoder
computes a new score over (query, turn) text and can promote a candidate neither cue ranked first,
so its ceiling should be *gold is in the slate handed to it*. Registered to be confirmed, not
assumed.

**ADR-013 — can the registered read vary?** Arm 1's registered read returned +0.0000 at every N
because it was an identity. The registration verified the shape could move the metric and never
verified the read could move. So: count the cases where reranking changes top-1, and require
movement in BOTH directions.

**The reranker configuration is pinned and matches what will ship**, because an instrument check
run in a configuration the binary does not use is a check on a different instrument:

  * **batch 1**, fixed shape `[1, 256]`, padded. Fixed shape is the same graph shape Session G's
    re-costing measured, so the 92.41 ms figure stays the thing being checked. Batch 1 is
    structural -- int8 batch invariance failed at 0.037 logits, and a batch of one removes the
    failure mode rather than tolerating it.
  * 1 thread, `CPUExecutionProvider`, asserted against the constructed session rather than
    requested and trusted.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import time
from pathlib import Path

import numpy as np

from reach_pools import REPO, Pool, turn_texts
from reach_session_h_pruning import derived_keys, prune_mask
from session_h_pools import gated_fit_pools

PREREG_PATH = REPO / "runs" / "session-h" / "PREREGISTRATION.json"
RECOST_PATH = REPO / "runs" / "session-g" / "cross-encoder-recost.json"
MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-int8"
OUT_PATH = REPO / "runs" / "session-h" / "rerank-fit.json"

MAX_SEQ_LEN = 256
BATCH = 1
THREADS = 1
PROVIDER = "CPUExecutionProvider"
EITHER_CUE_ORACLE = 0.6435
MIN_DISCORDANT = 10


class ProviderFellBack(RuntimeError):
    """The requested execution provider did not load and ORT silently used another one."""


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_session():
    """Load the pinned graph, and verify the digest and the provider rather than trusting them."""
    import onnxruntime as ort

    model = MODEL_DIR / "model_int8.onnx"
    expected = json.loads(io.open(RECOST_PATH, encoding="utf-8").read())
    expected = expected["results"]["L-2-int8"]["digests"]["model_int8.onnx"]
    found = sha256_file(model)
    if found != expected:
        raise SystemExit(
            f"{model} hashes to {found}, the pinned digest is {expected}. This is a different "
            "graph than the one Session G re-costed, and a different graph produces different "
            "scores while still looking like a reranker."
        )

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = THREADS
    opts.inter_op_num_threads = THREADS
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # PINNED to match the Rust stage, which builds at Level1. ORT's DEFAULT is ORT_ENABLE_ALL, and
    # it fuses this int8 graph differently: identical token ids, a logit 0.0699 apart. That is
    # nearly twice the 0.037 batch-invariance failure that blocked adoption in Session G, and
    # Session G's own re-costing ran at the default. An offline measurement taken at a different
    # optimization level than the shipped stage is a measurement of a different scorer.
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    sess = ort.InferenceSession(str(model), opts, providers=[PROVIDER])

    # ADR-013: a provider that is LISTED is not a provider that LOADS.
    active = sess.get_providers()
    if PROVIDER not in active:
        raise ProviderFellBack(f"requested {PROVIDER}, ORT is running {active}")
    return sess, found


def load_tokenizer():
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_SEQ_LEN)
    tok.enable_padding(length=MAX_SEQ_LEN)
    return tok


def score_pair(sess, tok, query: str, doc: str) -> tuple[float, bool]:
    """One (query, doc) pair. Batch is 1 and there is no parameter to raise it."""
    enc = tok.encode(query, doc)
    ids = np.array([enc.ids], dtype=np.int64)
    mask = np.array([enc.attention_mask], dtype=np.int64)
    types = np.array([enc.type_ids], dtype=np.int64)
    assert ids.shape[0] == BATCH == 1, "batch is fixed at 1, structurally"

    feed = {"input_ids": ids, "attention_mask": mask}
    names = {i.name for i in sess.get_inputs()}
    if "token_type_ids" in names:
        feed["token_type_ids"] = types
    # Fed BY NAME. token_type_ids carries the query/candidate boundary, and binding positionally
    # would transpose it on any graph that orders its inputs differently -- the model would still
    # return a plausible score.
    out = sess.run(None, feed)[0]
    return float(np.asarray(out).reshape(-1)[0]), False


def batch_invariance(sess, tok, n: int = 8) -> dict:
    """Does a pair's score depend on which other pairs share its batch, at THIS fusion level?"""
    docs = [f"I moved off Postgres in April, attempt number {i}." for i in range(n)]
    query = "which database did I migrate away from"
    encs = [tok.encode(query, d) for d in docs]
    ids = np.array([e.ids for e in encs], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
    types = np.array([e.type_ids for e in encs], dtype=np.int64)
    feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": types}
    batched = np.asarray(sess.run(None, feed)[0]).reshape(-1)
    singles = np.array([
        np.asarray(sess.run(None, {k: v[i:i + 1] for k, v in feed.items()})[0]).reshape(-1)[0]
        for i in range(n)
    ])
    diff = float(np.abs(batched - singles).max())
    return {"max_abs_diff": diff, "pass": bool(np.array_equal(batched, singles)), "pairs": n}


def gate_order(pool: Pool, idx: np.ndarray) -> np.ndarray:
    """The shipped ranking key restricted to `idx`: (score desc, margin desc, dump order).

    Returns positions into `idx`. Identical in meaning to analyze_cue_overlap.gate_order; the
    dump's own row order is the final tiebreak and np.lexsort is stable.
    """
    score = pool.array("score")[idx]
    margin = pool.array("margin")[idx]
    return np.lexsort((-margin, -score))


def top1_is_gold(pool: Pool, idx: np.ndarray, order: np.ndarray) -> bool:
    if idx.size == 0:
        return False
    return bool(pool.gold[idx][order[0]])


def hit_at(pool: Pool, idx: np.ndarray, order: np.ndarray, k: int) -> bool:
    if idx.size == 0:
        return False
    return bool(pool.gold[idx][order[:k]].any())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--include-unpruned-all",
        action="store_true",
        help="also rerank the FULL ~487-candidate pool (Q1's control arm). ~110k forward passes.",
    )
    args = ap.parse_args()

    prereg = json.loads(io.open(PREREG_PATH, encoding="utf-8").read())
    n_primary = prereg["frozen_parameters"]["prune_N"]["value"]
    gap_ms = prereg["frozen_parameters"]["session_gap_ms"]["value"]
    budget = 10

    pools = gated_fit_pools()
    texts = turn_texts()
    sess, digest = build_session()
    tok = load_tokenizer()

    # Determinism RE-VERIFIED at this optimization level, not inherited. ADR-013's rule is per
    # graph, and Level1 is a different fusion than the ENABLE_ALL Session G measured at. The
    # shipped path never batches, so a batch failure here would not affect it -- it is measured so
    # that the claim "batch 1 removes the failure mode" rests on a number at the shipped config.
    det = batch_invariance(sess, tok)
    print(f"Batch invariance at Level1: max |batch1 - batchN| = {det['max_abs_diff']:.6f} "
          f"({'PASS' if det['pass'] else 'FAIL -- and batch=1 is why it does not matter'})")

    print(f"Fit split: {len(pools)} pools. Reranker L-2-int8 {digest[:16]}...")
    print(f"batch {BATCH}, seq {MAX_SEQ_LEN}, {THREADS} thread, {PROVIDER} (asserted).\n")

    rows = []
    latencies: list[float] = []
    missing_text = 0

    for n_done, pool in enumerate(pools.values(), 1):
        per_turn = texts.get(pool.query_id, {})
        keys = derived_keys(pool, gap_ms)
        mask = prune_mask(pool, keys, n_primary)
        pruned_idx = np.flatnonzero(mask)
        all_idx = np.arange(len(pool.candidates))

        # The slates. Q2's budget is drawn by the SHIPPED ranking key from each pool.
        pruned_order = gate_order(pool, pruned_idx)
        unpruned_order = gate_order(pool, all_idx)
        q2_treat_idx = pruned_idx[pruned_order[:budget]]
        q2_ctrl_idx = all_idx[unpruned_order[:budget]]

        need = set(pruned_idx.tolist()) | set(q2_ctrl_idx.tolist())
        if args.include_unpruned_all:
            need = set(all_idx.tolist())

        scores: dict[int, float] = {}
        for i in sorted(need):
            tid = pool.candidates[i].turn_id
            doc = per_turn.get(tid or "", "")
            if not doc:
                missing_text += 1
            start = time.perf_counter()
            s, _ = score_pair(sess, tok, pool.question, doc)
            latencies.append((time.perf_counter() - start) * 1000.0)
            scores[i] = s

        def rerank(idx: np.ndarray) -> np.ndarray:
            """Descending by cross-encoder score. Stable, so ties keep the incoming order."""
            vals = np.array([scores[int(i)] for i in idx])
            return np.argsort(-vals, kind="stable")

        row = {
            "query_id": pool.query_id,
            "baseline_gate_top1": top1_is_gold(pool, all_idx, unpruned_order),
            "pruned_gate_top1": top1_is_gold(pool, pruned_idx, pruned_order),
            "gold_in_pruned_pool": bool(pool.gold[pruned_idx].any()) if pruned_idx.size else False,
            "gold_in_q2_treat_slate": bool(pool.gold[q2_treat_idx].any()),
            "gold_in_q2_ctrl_slate": bool(pool.gold[q2_ctrl_idx].any()),
            "q1_treat_top1": top1_is_gold(pool, pruned_idx, rerank(pruned_idx)),
            "q2_treat_top1": top1_is_gold(pool, q2_treat_idx, rerank(q2_treat_idx)),
            "q2_ctrl_top1": top1_is_gold(pool, q2_ctrl_idx, rerank(q2_ctrl_idx)),
        }
        if args.include_unpruned_all:
            row["q1_ctrl_top1"] = top1_is_gold(pool, all_idx, rerank(all_idx))
        rows.append(row)

        if n_done % 25 == 0:
            print(f"  {n_done}/{len(pools)} cases, {len(latencies)} pairs scored")

    n = len(rows)
    rate = lambda k: round(sum(r[k] for r in rows) / n, 4)  # noqa: E731

    # ---- ADR-010: presence ceilings -------------------------------------------------------
    ceiling_pruned = rate("gold_in_pruned_pool")
    adr010_pass = ceiling_pruned > EITHER_CUE_ORACLE

    # ---- ADR-013: can the read vary? ------------------------------------------------------
    gained = sum(1 for r in rows if r["q1_treat_top1"] and not r["pruned_gate_top1"])
    lost = sum(1 for r in rows if not r["q1_treat_top1"] and r["pruned_gate_top1"])
    discordant = gained + lost
    adr013_pass = discordant >= MIN_DISCORDANT and gained > 0 and lost > 0

    latencies.sort()
    p95 = latencies[max(0, int(round(0.95 * len(latencies))) - 1)]

    report = {
        "_what": "Session H Phase 1 -- the cross-encoder measured offline on the FIT split.",
        "split": "fit",
        "cases": n,
        "reranker": {
            "model": "L-2-int8", "sha256": digest, "batch": BATCH,
            "max_seq_len": MAX_SEQ_LEN, "threads": THREADS, "provider": PROVIDER,
            "_shape": "fixed [1, 256], padded -- the same graph shape Session G re-costed",
        },
        "batch_invariance_at_level1": det,
        "pairs_scored": len(latencies),
        "candidates_with_no_text": missing_text,
        "per_pair_latency_ms": {
            "p95": round(p95, 3),
            "median": round(statistics.median(latencies), 3),
            "mean": round(statistics.fmean(latencies), 3),
        },
        "adr_010_reach_check": {
            "_question": "is the reranker capped at the either-cue oracle?",
            "presence_ceiling_pruned_pool": ceiling_pruned,
            "either_cue_oracle": EITHER_CUE_ORACLE,
            "passes_if": f"> {EITHER_CUE_ORACLE} strictly",
            "pass": adr010_pass,
            "presence_ceiling_q2_treatment_slate": rate("gold_in_q2_treat_slate"),
            "presence_ceiling_q2_control_slate": rate("gold_in_q2_ctrl_slate"),
        },
        "adr_013_can_the_read_vary": {
            "_question": "can reranked top-1 differ from the ranking it replaces?",
            "comparator": "pruned-pool gate top-1",
            "cases_reranking_GAINS_gold": gained,
            "cases_reranking_LOSES_gold": lost,
            "discordant_cases": discordant,
            "passes_if": f"discordant >= {MIN_DISCORDANT} AND both directions observed",
            "pass": adr013_pass,
        },
        "fit_split_readings": {
            "_not_the_registered_answer": (
                "The registered question is answered on HELD-OUT. These are fit-split readings, "
                "taken to de-risk the build and to give the instrument checks something to read."
            ),
            "baseline_gate_top1_unpruned": rate("baseline_gate_top1"),
            "gate_top1_pruned": rate("pruned_gate_top1"),
            "q1_treatment_rerank_all_pruned": rate("q1_treat_top1"),
            "q2_treatment_rerank_top10_pruned": rate("q2_treat_top1"),
            "q2_control_rerank_top10_unpruned": rate("q2_ctrl_top1"),
            "fit_split_floor_best_single_cue": 0.5633,
        },
        "_per_case": rows,
    }
    if args.include_unpruned_all:
        report["fit_split_readings"]["q1_control_rerank_all_unpruned"] = rate("q1_ctrl_top1")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(latencies)} pairs scored. per-pair P95 {p95:.2f} ms, "
          f"median {statistics.median(latencies):.2f} ms.")
    if missing_text:
        print(f"WARNING: {missing_text} candidates had no text and were scored against an empty doc.")

    print(f"\nADR-010 -- is the reranker capped at the either-cue oracle?")
    print(f"  presence ceiling of the pruned pool   {ceiling_pruned:.4f}")
    print(f"  either-cue oracle                     {EITHER_CUE_ORACLE:.4f}")
    print(f"  {'PASS -- not capped' if adr010_pass else 'FAIL -- capped, the premise is refuted'}")
    print(f"  Q2 treatment slate ceiling            {rate('gold_in_q2_treat_slate'):.4f}")
    print(f"  Q2 control   slate ceiling            {rate('gold_in_q2_ctrl_slate'):.4f}")

    print(f"\nADR-013 -- can the registered read vary?")
    print(f"  reranking GAINS gold in               {gained} cases")
    print(f"  reranking LOSES gold in               {lost} cases")
    print(f"  discordant                            {discordant} (need >= {MIN_DISCORDANT}, both directions)")
    print(f"  {'PASS -- the read varies' if adr013_pass else 'FAIL -- the read is pinned; Q1/Q2 report NOT MEASURED'}")

    print(f"\nFit-split readings (NOT the registered answer, which is held-out):")
    fr = report["fit_split_readings"]
    print(f"  gate top-1, unpruned                  {fr['baseline_gate_top1_unpruned']:.4f}")
    print(f"  gate top-1, pruned                    {fr['gate_top1_pruned']:.4f}")
    print(f"  Q1 treatment -- rerank all pruned     {fr['q1_treatment_rerank_all_pruned']:.4f}")
    if args.include_unpruned_all:
        print(f"  Q1 control   -- rerank all unpruned   {fr['q1_control_rerank_all_unpruned']:.4f}")
    print(f"  Q2 treatment -- rerank top10 pruned   {fr['q2_treatment_rerank_top10_pruned']:.4f}")
    print(f"  Q2 control   -- rerank top10 unpruned {fr['q2_control_rerank_top10_unpruned']:.4f}")
    print(f"  floor (best single cue, fit split)    {fr['fit_split_floor_best_single_cue']:.4f}")

    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0 if (adr010_pass and adr013_pass) else 1


if __name__ == "__main__":
    raise SystemExit(main())
