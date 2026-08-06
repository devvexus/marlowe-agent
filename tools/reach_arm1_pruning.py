"""Session G, arm 1 — session-level pruning. Score sessions, keep top N, rank turns only within.

The haystack's internal session structure is in the data and currently discarded: retrieval is
scoped by `session_id`, but that is the *question's* synthetic session, and the ~48 real
LongMemEval sessions inside each haystack are never used as a unit. This arm uses them.

**Registered reads** (`PREREGISTRATION.json -> arm_1_registered_reads`), reported together and
none alone: surviving pool size, gold retention, and the either-cue top-1 oracle. Pruning raises
top-1 only by removing a distractor above gold, and lowers it by removing gold; an oracle gain
bought by dropping gold is a loss, and the oracle alone cannot show that.

**Also registered**: the failure decomposition. "Pruning did not help" has two causes with two
different fixes -- the wrong session was selected, or the right session was selected and gold
ranked poorly inside it. The first needs a better session scorer; the second needs a reranker, and
is exactly the case the cross-encoder addresses.

---

## An unregistered degree of freedom, disclosed

The pre-registration fixed N = {1, 3, 5} and every read, but it did **not** fix the session
*scoring* rule, and there is more than one defensible choice. That gap is mine and it was found
while implementing, after the registration was committed.

It is handled by declaring the variants below **before running any of them** and reporting all
results including the unflattering ones. The consequence is stated rather than worked around:

> **Because the aggregation rule was not pre-registered, the best-performing variant cannot be
> quoted as this arm's result.** The PRIMARY is the first rule declared -- the simplest one, chosen
> for having no free parameter -- and the others are sensitivity analysis. Promoting whichever
> variant scored highest would be choosing the rule after seeing the number, which is the thing the
> registration exists to prevent.

PRIMARY: session score under a cue = **max** over its turns of that cue's score; a session survives
if it is in the **top-N by lexical OR top-N by dense** (union, so at most 2N sessions survive).
Max-aggregation is standard best-passage scoring and has no parameter to tune. The union is
cue-symmetric and is what would actually ship: one pruned pool, both cues ranking inside it.

SENSITIVITY A: per-cue independent pruning -- each cue prunes by its own session scores and ranks
in its own pruned pool. Cue-symmetric but does not correspond to a single shippable pool.

SENSITIVITY B: session score = mean of the top-3 turn scores, union pruning otherwise identical.
Has a parameter, which is why it is not primary.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from reach_pools import REPO, Pool, hit, load_pools, order_of

OUT_PATH = REPO / "runs" / "session-g" / "arm1-pruning.json"
N_VALUES = (1, 3, 5)
CUES = ("lexical_bm25", "dense_cosine")


def _session_scores(pool: Pool, cue: str, agg: str) -> dict[str, float]:
    """sid -> aggregated score for one cue."""
    by_session: dict[str, list[float]] = defaultdict(list)
    for cand in pool.candidates:
        if cand.sid is not None:
            by_session[cand.sid].append(getattr(cand, cue))
    if agg == "max":
        return {sid: max(vals) for sid, vals in by_session.items()}
    if agg == "mean_top3":
        return {sid: float(np.mean(sorted(vals, reverse=True)[:3])) for sid, vals in by_session.items()}
    raise ValueError(agg)


def _top_n_sessions(scores: dict[str, float], n: int) -> list[str]:
    """Top N sids. Ties broken by sid ascending, so the choice is deterministic."""
    return [sid for sid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def _mask(pool: Pool, keep: set[str]) -> np.ndarray:
    return np.array([c.sid in keep for c in pool.candidates])


def _rates(pool: Pool, mask: np.ndarray, ks=(1, 5, 10, 20)) -> dict:
    """Top-k hit for each cue over the masked pool, plus the either-cue oracle.

    Masking is done by index selection rather than by score suppression. Suppressing a score would
    leave the row in the ranking with a very negative value, which changes nothing at k=1 and
    quietly changes R@20.
    """
    idx = np.flatnonzero(mask)
    out: dict = {}
    if idx.size == 0:
        return {f"{name}@{k}": False for name in ("lexical", "dense", "oracle") for k in ks}
    gold = pool.gold[idx]
    orders = {name: order_of(pool.array(cue)[idx]) for name, cue in zip(("lexical", "dense"), CUES)}
    for k in ks:
        L = hit(orders["lexical"], gold, k)
        D = hit(orders["dense"], gold, k)
        out[f"lexical@{k}"] = L
        out[f"dense@{k}"] = D
        out[f"oracle@{k}"] = L or D
    return out


def _decompose(pool: Pool, keep: set[str], mask: np.ndarray) -> str:
    """The registered failure decomposition, per case."""
    gold_sessions = {c.sid for c in pool.candidates if c.is_gold and c.sid is not None}
    if not (gold_sessions & keep):
        return "wrong_session"
    r = _rates(pool, mask, ks=(1,))
    if r["oracle@1"]:
        return "solved"
    return "right_session_wrong_rank"


def run_variant(pools: dict[str, Pool], agg: str, mode: str, n: int) -> dict:
    """One (aggregation, pruning mode, N) cell."""
    tally = defaultdict(int)
    decomp = defaultdict(int)
    kept_frac: list[float] = []
    gold_retained = 0
    per_case: dict[str, bool] = {}

    for pool in pools.values():
        total = len(pool.candidates)
        scores = {cue: _session_scores(pool, cue, agg) for cue in CUES}

        if mode == "union":
            keep = set()
            for cue in CUES:
                keep |= set(_top_n_sessions(scores[cue], n))
            mask = _mask(pool, keep)
            kept_frac.append(int(mask.sum()) / total)
            if pool.gold[mask].any():
                gold_retained += 1
            r = _rates(pool, mask)
            decomp[_decompose(pool, keep, mask)] += 1
        elif mode == "per_cue":
            # Each cue prunes by its own session scores. Reported as sensitivity: it is not one
            # shippable pool, and its "pool size" is the mean of two different pools.
            r = {}
            sizes = []
            any_gold = False
            for name, cue in zip(("lexical", "dense"), CUES):
                keep = set(_top_n_sessions(scores[cue], n))
                mask = _mask(pool, keep)
                sizes.append(int(mask.sum()) / total)
                any_gold = any_gold or bool(pool.gold[mask].any())
                idx = np.flatnonzero(mask)
                if idx.size == 0:
                    for k in (1, 5, 10, 20):
                        r[f"{name}@{k}"] = False
                    continue
                o = order_of(pool.array(cue)[idx])
                g = pool.gold[idx]
                for k in (1, 5, 10, 20):
                    r[f"{name}@{k}"] = hit(o, g, k)
            for k in (1, 5, 10, 20):
                r[f"oracle@{k}"] = r[f"lexical@{k}"] or r[f"dense@{k}"]
            kept_frac.append(float(np.mean(sizes)))
            gold_retained += any_gold
            decomp["not_decomposed_for_this_mode"] += 1
        else:
            raise ValueError(mode)

        for key, val in r.items():
            tally[key] += val
        per_case[pool.query_id] = bool(r["oracle@1"])

    n_cases = len(pools)
    return {
        "aggregation": agg,
        "mode": mode,
        "N": n,
        "cases": n_cases,
        "surviving_pool_fraction_mean": round(float(np.mean(kept_frac)), 6),
        "gold_retention": round(gold_retained / n_cases, 4),
        "rates": {k: round(v / n_cases, 4) for k, v in sorted(tally.items())},
        "failure_decomposition": {k: v for k, v in sorted(decomp.items())},
        "_per_case_oracle_at_1": per_case,
    }


def structural_check(pools: dict[str, Pool]) -> dict:
    """Is max-aggregation pruning a NO-OP at k=1 by construction?

    Written after seeing oracle@1 come back +0.0000 at every N in both modes. An exact zero
    repeated six times is a structural signature, not a measurement, and the suspicion is an
    identity: under max aggregation a session's score IS its best turn's score, so the
    globally top-scoring turn always belongs to the top-scoring session. If that holds, keeping
    the top N>=1 sessions can never displace the top-1 turn, and the arm's registered primary
    read is VACUOUS rather than null.

    Asserting that analytically would be cheap. This measures it, per the working agreement that
    a claim which is not a command printing a number does not exist.
    """
    violations = 0
    checked = 0
    for pool in pools.values():
        for cue in CUES:
            scores = _session_scores(pool, cue, "max")
            top_session = _top_n_sessions(scores, 1)[0]
            top_turn_idx = int(order_of(pool.array(cue))[0])
            checked += 1
            if pool.candidates[top_turn_idx].sid != top_session:
                violations += 1
    return {
        "_claim": (
            "Under max aggregation the top-1 turn under a cue always lies in that cue's top-1 "
            "session, so pruning to top-N>=1 cannot change the cue's top-1."
        ),
        "checked_case_cue_pairs": checked,
        "violations": violations,
        "identity_holds": violations == 0,
        "_consequence_if_it_holds": (
            "Arm 1's registered oracle@1 read is VACUOUS under max aggregation -- the measurement "
            "was structurally incapable of moving, so +0.0000 is not evidence that pruning does "
            "not help at top-1. It is evidence that this aggregation cannot be asked."
        ),
        "_why_ties_do_not_break_it": (
            "Both the session ranking and the turn ranking break ties deterministically, and a tie "
            "at the maximum still places the winning turn inside a session whose max equals the "
            "global max. Any such session is tied for first, so at N>=1 a tie could in principle "
            "select a different one -- which is why this is measured and not assumed."
        ),
    }


def main() -> int:
    pools, stats = load_pools()

    # The unpruned baseline, computed in the SAME run from the SAME pools -- the registered
    # shortlist-equivalence condition compares R@10 pruned against R@20 unpruned, and both sides
    # are measured here rather than one being looked up.
    full = defaultdict(int)
    base_per_case: dict[str, bool] = {}
    for pool in pools.values():
        r = _rates(pool, np.ones(len(pool.candidates), dtype=bool))
        for k, v in r.items():
            full[k] += v
        base_per_case[pool.query_id] = bool(r["oracle@1"])
    n_cases = len(pools)
    baseline = {k: round(v / n_cases, 4) for k, v in sorted(full.items())}

    results = []
    for agg, mode in (("max", "union"), ("max", "per_cue"), ("mean_top3", "union")):
        for n in N_VALUES:
            results.append(run_variant(pools, agg, mode, n))

    primary = [r for r in results if r["aggregation"] == "max" and r["mode"] == "union"]

    report = {
        "_what": "Session G arm 1 -- session-level pruning, measured on held-out pools.",
        "_disclosure": (
            "The session aggregation rule was NOT pre-registered. Variants were declared before "
            "running and all are reported; the PRIMARY is max/union, the first and "
            "parameter-free rule. The best-scoring variant may not be quoted as the arm's result."
        ),
        "reconstruction": stats,
        "structural_check": structural_check(pools),
        "unpruned_baseline": baseline,
        "primary_variant": "max aggregation, union of per-cue top-N",
        "results": results,
        "shortlist_equivalence": {
            "_rule": "R@10 pruned at N >= R@20 unpruned - 0.01, per ranker",
            "r_at_20_unpruned": {
                name: baseline[f"{name}@20"] for name in ("lexical", "dense", "oracle")
            },
            "evaluated": [
                {
                    "N": r["N"],
                    **{
                        name: {
                            "r_at_10_pruned": r["rates"][f"{name}@10"],
                            "passes": r["rates"][f"{name}@10"] >= baseline[f"{name}@20"] - 0.01,
                        }
                        for name in ("lexical", "dense", "oracle")
                    },
                }
                for r in primary
            ],
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Arm 1 -- session-level pruning. {n_cases} held-out cases, "
          f"{stats['sessions_seen'] / n_cases:.1f} sessions per case.\n")
    print("Unpruned baseline:")
    print(f"  oracle@1 {baseline['oracle@1']:.4f}   oracle@10 {baseline['oracle@10']:.4f}   "
          f"oracle@20 {baseline['oracle@20']:.4f}")
    print(f"  lexical@1 {baseline['lexical@1']:.4f}  dense@1 {baseline['dense@1']:.4f}  "
          f"lexical@20 {baseline['lexical@20']:.4f}  dense@20 {baseline['dense@20']:.4f}\n")

    print("PRIMARY -- max aggregation, union of per-cue top-N:")
    print(f"  {'N':>2}  {'pool':>7}  {'goldret':>7}  {'oracle@1':>8}  {'delta':>7}  "
          f"{'oracle@10':>9}  {'wrong_sess':>10}  {'wrong_rank':>10}  {'solved':>6}")
    for r in primary:
        d = r["failure_decomposition"]
        print(f"  {r['N']:>2}  {r['surviving_pool_fraction_mean']:>7.4f}  "
              f"{r['gold_retention']:>7.4f}  {r['rates']['oracle@1']:>8.4f}  "
              f"{r['rates']['oracle@1'] - baseline['oracle@1']:>+7.4f}  "
              f"{r['rates']['oracle@10']:>9.4f}  {d.get('wrong_session', 0):>10}  "
              f"{d.get('right_session_wrong_rank', 0):>10}  {d.get('solved', 0):>6}")

    print("\nSENSITIVITY (declared before running; not promotable):")
    for r in results:
        if r["aggregation"] == "max" and r["mode"] == "union":
            continue
        print(f"  {r['aggregation']:>9} / {r['mode']:<8} N={r['N']}  pool "
              f"{r['surviving_pool_fraction_mean']:.4f}  goldret {r['gold_retention']:.4f}  "
              f"oracle@1 {r['rates']['oracle@1']:.4f} "
              f"({r['rates']['oracle@1'] - baseline['oracle@1']:+.4f})")

    print("\nShortlist equivalence -- R@10 pruned vs R@20 unpruned - 0.01:")
    for row in report["shortlist_equivalence"]["evaluated"]:
        marks = "  ".join(
            f"{name} {row[name]['r_at_10_pruned']:.4f} "
            f"{'PASS' if row[name]['passes'] else 'FAIL'}"
            for name in ("lexical", "dense", "oracle")
        )
        print(f"  N={row['N']}  {marks}")

    sc = report["structural_check"]
    print(f"\nStructural check -- {sc['checked_case_cue_pairs']} case/cue pairs, "
          f"{sc['violations']} violations.")
    if sc["identity_holds"]:
        print("  IDENTITY HOLDS. Max aggregation cannot move top-1: the top-scoring turn defines")
        print("  the top-scoring session. Arm 1's oracle@1 read is VACUOUS, not null -- +0.0000 is")
        print("  the measurement being structurally unable to move, not pruning failing to help.")
    else:
        print("  Identity does NOT hold; oracle@1 under max aggregation is a real measurement.")

    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
