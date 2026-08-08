"""R3 -- where the 0.9039 ceiling comes from, and what it would take to move it.

Every arm in this session is bounded by input recall: if the gold turn is not in the depth-10
slate handed to the reranker, no reranker recovers it. `R@1 = input_recall x conditional_accuracy`
factors exactly, and it is 0.9039 x 0.7440 today. The reranking arms attack the second factor. This
script measures the first, which nothing in M0b ever did directly.

It reads the shipped binary's own candidate dump -- all ~490 candidates per query with their
lexical, dense and gate scores and their pruning verdict -- and asks what recall a differently
constructed slate would have at the same depth, and at greater depths.

It also computes SESSION-LEVEL recall, which is the metric comparable retrieval systems usually
publish. Turn-level R@1 and session-level R@5 are different questions by orders of magnitude on
this corpus, and quoting one against the other is the category error this project keeps a list of.

Nothing here is a proposal. Several of the orderings measured are on the closed list (fusion,
ADR-010/011) and are computed as DIAGNOSTIC CEILINGS only -- to say how much is upstream, not to
suggest re-opening them. Where a row is closed it is labelled closed.

Prints numbers. Applies nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

OUT = REPO / "runs" / "session-m0c" / "reach-r3-slate.json"
RUN = REPO / "runs" / "session-k"
SPLIT_PATH = REPO / "tools" / "split.json"

DEPTH_SHIPPED = 10


def iter_ndjson(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_turn_map(run_jsonl: Path) -> dict[str, str]:
    """memory_id -> turn_id, from the section 4.6 ingest responses. This is the same mapping
    `Attributor` builds; it is rebuilt here rather than imported because the Attributor also loads
    the 277 MB corpus, and this script only needs the identifier join."""
    m = {}
    with run_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            if '"written"' not in line:
                continue
            body = json.loads(line).get("body", {})
            for w in body.get("written", []) or []:
                for mid in w.get("memory_ids", []) or []:
                    m[mid] = w["turn_id"]
    return m


def load_pool(split: str, gold_map: dict[str, frozenset]) -> dict[str, dict]:
    d = RUN / split
    turn_of = build_turn_map(d / "run.jsonl")
    per: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    unmapped = 0
    for row in iter_ndjson(d / "scored-candidates.ndjson"):
        q = row["query_id"]
        tid = turn_of.get(row["memory_id"])
        if tid is None:
            unmapped += 1
            continue
        p = per[q]
        p["turn_id"].append(tid)
        p["gold"].append(tid in gold_map.get(q, frozenset()))
        p["lex"].append(row["lexical_bm25"])
        p["den"].append(row["dense_cosine"])
        p["score"].append(row["score"])
        p["margin"].append(row["margin"])
        p["survived"].append(bool(row.get("survived_pruning")))
        p["rerank"].append(np.nan if row.get("rerank_score") is None
                           else float(row["rerank_score"]))
        p["session"].append(row["session_key"])
    if unmapped:
        print(f"  WARNING: {unmapped} dump rows had no memory_id -> turn_id mapping")
    return {q: {k: np.asarray(v) for k, v in p.items()} for q, p in per.items()}


def rrf(*rank_arrays, k: int = 60) -> np.ndarray:
    return sum(1.0 / (k + 1 + r) for r in rank_arrays)


def ranks_desc(x: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(-x, kind="stable"), kind="stable")


def recall_at(order: np.ndarray, gold: np.ndarray, depth: int) -> bool:
    return bool(gold[order[:depth]].any())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--splits", nargs="+", default=["heldout"])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    from marlowe_eval.datasets import longmemeval

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()
    cases = {c.query_id: c for c in corpus.cases}

    report: dict = {"_what": "where the input-recall ceiling comes from and what would move it",
                    "_nothing_here_is_a_proposal": "several orderings are on the closed list and "
                                                   "are computed as diagnostic ceilings only"}

    for sp in args.splits:
        print("=" * 92)
        print(f"R3 -- SLATE CONSTRUCTION, {sp} split")
        print("=" * 92)
        pool = load_pool(sp, gold_map)
        eligible = [q for q in pool
                    if q in cases and not cases[q].is_abstention and pool[q]["gold"].any()]
        eligible.sort()
        n = len(eligible)
        print(f"eligible queries {n} (non-abstention, >=1 gold in the retrieved pool)")
        print(f"pool size per query: median {np.median([len(pool[q]['gold']) for q in eligible]):.0f}"
              f"   survivors: median "
              f"{np.median([pool[q]['survived'].sum() for q in eligible]):.0f}")
        print()

        # ---- the shipped slate, and what recall it achieves -------------------------------
        orders = {}
        for q in eligible:
            p = pool[q]
            # the shipped slate is the gate order restricted to survivors -- the same five-level
            # key analyze_cue_overlap.shipped_order uses, with rerank absent above depth 10
            gate = np.lexsort((-p["margin"], -p["score"], ~p["survived"]))
            orders[q] = {
                "gate (SHIPPED slate order)": gate,
                "dense alone": np.lexsort((-p["den"], ~p["survived"])),
                "lexical alone": np.lexsort((-p["lex"], ~p["survived"])),
                "RRF lexical+dense [CLOSED: ADR-010/011]":
                    np.lexsort((-rrf(ranks_desc(p["lex"]), ranks_desc(p["den"])), ~p["survived"])),
            }

        rows = []
        print(f"{'slate ordering':<42} {'R@10':>8} {'R@15':>8} {'R@20':>8} {'R@48':>8}")
        print("-" * 92)
        for label in next(iter(orders.values())):
            vals = {}
            for depth in (10, 15, 20, 48):
                hits = sum(recall_at(orders[q][label], pool[q]["gold"], depth) for q in eligible)
                vals[depth] = hits / n
            rows.append({"ordering": label, **{f"recall_at_{d}": round(v, 4)
                                               for d, v in vals.items()}})
            print(f"{label:<42} {vals[10]:>8.4f} {vals[15]:>8.4f} {vals[20]:>8.4f} "
                  f"{vals[48]:>8.4f}")

        # ---- unions: the cheapest way to raise recall at bounded depth ---------------------
        print()
        print(f"{'UNION slates (depth = size of the union)':<42} {'recall':>8} {'med size':>9}")
        print("-" * 92)
        unions = []
        for a, b, take in (("gate (SHIPPED slate order)", "dense alone", 10),
                           ("gate (SHIPPED slate order)", "dense alone", 8),
                           ("gate (SHIPPED slate order)", "lexical alone", 10)):
            hits, sizes = 0, []
            for q in eligible:
                s = set(orders[q][a][:take].tolist()) | set(orders[q][b][:take].tolist())
                sizes.append(len(s))
                hits += bool(pool[q]["gold"][list(s)].any())
            lbl = f"{a.split()[0]} top{take} UNION {b.split()[0]} top{take}"
            unions.append({"union": lbl, "recall": round(hits / n, 4),
                           "median_size": float(np.median(sizes))})
            print(f"{lbl:<42} {hits/n:>8.4f} {np.median(sizes):>9.0f}")

        # ---- the ceilings ------------------------------------------------------------------
        surv = sum(bool(pool[q]["gold"][pool[q]["survived"]].any()) for q in eligible) / n
        allp = 1.0  # eligible is defined as >=1 gold in the pool
        print()
        print(f"  recall over ALL SURVIVORS (median 48):        {surv:.4f}   <- pruning's ceiling")
        print(f"  recall over the WHOLE RETRIEVED POOL (~490):  {allp:.4f}   <- by construction of "
              f"the eligible set")

        # ---- session-level recall, the metric other systems publish ------------------------
        print()
        print("-" * 92)
        print("SESSION-LEVEL RECALL -- the metric comparable systems usually report")
        print("-" * 92)
        print("  A session scores as retrieved if any of its turns is retrieved. Session score is")
        print("  the MAX over its turns, which is the aggregation ADR-013 measured. This is NOT")
        print("  turn-level R@1 and the two are not interchangeable.")
        sess_rows = []
        for label in ("gate (SHIPPED slate order)", "dense alone", "lexical alone"):
            vals = {}
            for depth in (1, 3, 5, 10):
                hits = 0
                for q in eligible:
                    p, o = pool[q], orders[q][label]
                    seen, top = [], []
                    for i in o:
                        s = p["session"][i]
                        if s not in seen:
                            seen.append(s)
                            top.append(s)
                        if len(top) >= depth:
                            break
                    goldsess = set(p["session"][p["gold"]].tolist())
                    hits += bool(goldsess & set(top))
                vals[depth] = hits / n
            sess_rows.append({"ordering": label,
                              **{f"session_recall_at_{d}": round(v, 4) for d, v in vals.items()}})
            print(f"  {label:<40} S@1 {vals[1]:.4f}  S@3 {vals[3]:.4f}  "
                  f"S@5 {vals[5]:.4f}  S@10 {vals[10]:.4f}")

        report[sp] = {"n_eligible": n, "turn_level": rows, "unions": unions,
                      "recall_over_survivors": round(surv, 4),
                      "session_level": sess_rows}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
