"""Session H, Phase 1 — the sessionizer, and arm 1 re-derived on the FIT split.

Two jobs, in one script because they are one computation with the partition swapped.

**Job 1: is timestamp contiguity a usable proxy for session structure?** The binary has no
internal session boundary and section 4.6 does not carry one. Rather than parse the harness's
private `turn_id` encoding, sessions are DERIVED: sort a scope's candidates by `occurred_at_ms`
and start a new session at any gap over `session_gap_ms`. This measures how that partition
compares to the true `sid` partition, against a band registered in
`runs/session-h/PREREGISTRATION.json` BEFORE this script was written.

**Job 2: re-derive arm 1 on the fit split.** Every Session G number is held-out and is therefore
headroom rather than validation. Nothing gets built on a held-out band.

Both run on the fit split only. Neither reads held-out.

**The registered structural check is repeated here, not inherited.** Session G proved the
max-aggregation identity on the TRUE partition: under max aggregation a session's score is its
best turn's score, so pruning to top-N>=1 cannot displace a cue's top-1. That proof never uses any
property of the partition, so it should hold for derived sessions too -- but the tiebreak key
changes with the partition, and the identity holds only modulo exact ties at the maximum. So it is
measured again rather than assumed.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from reach_pools import REPO, Pool, hit, order_of
from session_h_pools import gated_fit_pools

PREREG_PATH = REPO / "runs" / "session-h" / "PREREGISTRATION.json"
OUT_PATH = REPO / "runs" / "session-h" / "sessionizer-and-arm1-fit.json"
CUES = ("lexical_bm25", "dense_cosine")
N_VALUES = (1, 3, 5)


# --------------------------------------------------------------------------------------------
# The partitions.
# --------------------------------------------------------------------------------------------

def true_keys(pool: Pool) -> list[str]:
    """The LongMemEval haystack session each turn came from. The thing being approximated."""
    return [c.sid for c in pool.candidates]


def derived_keys(pool: Pool, gap_ms: int) -> list[str]:
    """Sessions derived from `occurred_at_ms` contiguity.

    **This function is the specification the Rust implementation must reproduce**, so it is
    written the way the Rust will be: sort by (occurred_at_ms, turn_id), walk once, open a new
    session whenever the gap to the previous turn exceeds the threshold.

    The secondary sort key matters for determinism but not for the result: two turns at the same
    millisecond have a gap of 0, which never exceeds the threshold, so they land in the same
    session regardless of which comes first.
    """
    order = sorted(
        range(len(pool.candidates)),
        key=lambda i: (pool.candidates[i].occurred_at_ms, pool.candidates[i].turn_id or ""),
    )
    keys: list[str | None] = [None] * len(pool.candidates)
    group = 0
    prev: int | None = None
    for i in order:
        at = pool.candidates[i].occurred_at_ms
        if prev is not None and at - prev > gap_ms:
            group += 1
        keys[i] = f"d-{group}"
        prev = at
    return keys  # type: ignore[return-value]


# --------------------------------------------------------------------------------------------
# Pruning, parameterised by the partition.
# --------------------------------------------------------------------------------------------

def _session_scores(pool: Pool, keys: list[str], cue: str) -> dict[str, float]:
    """The FROZEN rule: session score = max over its turns of that cue's score."""
    by: dict[str, float] = {}
    for cand, key in zip(pool.candidates, keys):
        v = getattr(cand, cue)
        if key not in by or v > by[key]:
            by[key] = v
    return by


def _top_n(scores: dict[str, float], n: int) -> list[str]:
    """Top N keys. Ties broken by key ascending, so the choice is deterministic."""
    return [k for k, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def prune_mask(pool: Pool, keys: list[str], n: int) -> np.ndarray:
    """The FROZEN rule: keep the union of each cue's top-N sessions."""
    keep: set[str] = set()
    for cue in CUES:
        keep |= set(_top_n(_session_scores(pool, keys, cue), n))
    return np.array([k in keep for k in keys])


def pruning_reads(pools: dict[str, Pool], keyfn, n: int) -> dict:
    """Surviving pool fraction, gold retention, and the failure decomposition."""
    fracs: list[float] = []
    gold_kept = 0
    decomp: dict[str, int] = defaultdict(int)
    rates: dict[str, int] = defaultdict(int)

    for pool in pools.values():
        keys = keyfn(pool)
        mask = prune_mask(pool, keys, n)
        fracs.append(int(mask.sum()) / len(pool.candidates))

        idx = np.flatnonzero(mask)
        gold = pool.gold[idx]
        kept = bool(gold.any())
        gold_kept += kept

        orders = {name: order_of(pool.array(cue)[idx]) for name, cue in zip(("lexical", "dense"), CUES)}
        oracle_at_1 = False
        for k in (1, 5, 10, 20):
            L = hit(orders["lexical"], gold, k)
            D = hit(orders["dense"], gold, k)
            rates[f"lexical@{k}"] += L
            rates[f"dense@{k}"] += D
            rates[f"oracle@{k}"] += L or D
            if k == 1:
                oracle_at_1 = L or D

        # The registered decomposition. `wrong_session` is checked first and is exclusive: if
        # pruning dropped every gold turn, the ranking inside the survivors is not the failure.
        if not kept:
            decomp["wrong_session"] += 1
        elif oracle_at_1:
            decomp["solved"] += 1
        else:
            decomp["right_session_wrong_rank"] += 1

    n_cases = len(pools)
    return {
        "N": n,
        "cases": n_cases,
        "surviving_pool_fraction_mean": round(float(np.mean(fracs)), 6),
        "gold_retention": round(gold_kept / n_cases, 4),
        "rates": {k: round(v / n_cases, 4) for k, v in sorted(rates.items())},
        "failure_decomposition": dict(sorted(decomp.items())),
    }


# --------------------------------------------------------------------------------------------
# Partition agreement, reported as diagnostics beside the bands.
# --------------------------------------------------------------------------------------------

def agreement(pools: dict[str, Pool], gap_ms: int) -> dict:
    """How the derived partition differs from the true one, in the terms that matter.

    Homogeneity and completeness are reported separately and NOT combined into a symmetric
    score, because the two error directions have different consequences. A derived session that
    MERGES two true sessions is wasteful -- the pool is bigger than intended and gold is still
    in it. A true session SPLIT across derived sessions is dangerous -- pruning can keep one
    fragment and discard the one holding gold.
    """
    pure_derived = total_derived = 0
    whole_true = total_true = 0
    split_true = 0
    cases_with_a_split = 0
    derived_counts: list[int] = []
    true_counts: list[int] = []
    gold_session_split_cases = 0

    for pool in pools.values():
        tk, dk = true_keys(pool), derived_keys(pool, gap_ms)

        d_to_t: dict[str, set[str]] = defaultdict(set)
        t_to_d: dict[str, set[str]] = defaultdict(set)
        for t, d in zip(tk, dk):
            d_to_t[d].add(t)
            t_to_d[t].add(d)

        total_derived += len(d_to_t)
        pure_derived += sum(1 for ts in d_to_t.values() if len(ts) == 1)
        total_true += len(t_to_d)
        whole_true += sum(1 for ds in t_to_d.values() if len(ds) == 1)

        splits = [t for t, ds in t_to_d.items() if len(ds) > 1]
        split_true += len(splits)
        cases_with_a_split += bool(splits)

        gold_sessions = {c.sid for c in pool.candidates if c.is_gold}
        if gold_sessions & set(splits):
            gold_session_split_cases += 1

        derived_counts.append(len(d_to_t))
        true_counts.append(len(t_to_d))

    n = len(pools)
    return {
        "homogeneity_pure_derived_sessions": round(pure_derived / total_derived, 4),
        "completeness_whole_true_sessions": round(whole_true / total_true, 4),
        "true_sessions_split": split_true,
        "cases_with_any_split_true_session": cases_with_a_split,
        "cases_where_a_GOLD_session_is_split": gold_session_split_cases,
        "_why_that_last_one_matters": (
            "A split gold session is the only way the sessionizer can lose the answer: pruning "
            "keeps one fragment and the gold turn is in the other."
        ),
        "mean_derived_sessions_per_case": round(float(np.mean(derived_counts)), 2),
        "mean_true_sessions_per_case": round(float(np.mean(true_counts)), 2),
        "cases": n,
    }


def identity_check(pools: dict[str, Pool], keyfn, label: str) -> dict:
    """Does max-aggregation pruning leave each cue's top-1 untouched, on THIS partition?

    Registered as a prediction, so it is measured rather than inherited from Session G. The proof
    is partition-independent but holds only modulo exact ties at the maximum, and the tiebreak key
    changes with the partition.
    """
    violations = 0
    checked = 0
    for pool in pools.values():
        keys = keyfn(pool)
        for cue in CUES:
            top_key = _top_n(_session_scores(pool, keys, cue), 1)[0]
            top_turn = int(order_of(pool.array(cue))[0])
            checked += 1
            if keys[top_turn] != top_key:
                violations += 1
    return {
        "partition": label,
        "checked_case_cue_pairs": checked,
        "violations": violations,
        "identity_holds": violations == 0,
    }


def main() -> int:
    prereg = json.loads(io.open(PREREG_PATH, encoding="utf-8").read())
    frozen = prereg["frozen_parameters"]
    band = prereg["sessionizer_band"]
    gap_ms = frozen["session_gap_ms"]["value"]
    n_primary = frozen["prune_N"]["value"]
    tol = 0.02
    inflation_max = 1.5

    pools = gated_fit_pools()
    print(f"Fit split: {len(pools)} pools, "
          f"{sum(len(p.candidates) for p in pools.values())} candidates.")
    print(f"Session gap {gap_ms} ms (30 min), frozen. Prune N={n_primary}, frozen.\n")

    agr = agreement(pools, gap_ms)
    print("Partition agreement -- derived (timestamp contiguity) vs true (haystack sid):")
    print(f"  homogeneity  (derived sessions drawn from one true session)  "
          f"{agr['homogeneity_pure_derived_sessions']:.4f}")
    print(f"  completeness (true sessions inside one derived session)      "
          f"{agr['completeness_whole_true_sessions']:.4f}")
    print(f"  true sessions split across derived sessions                  {agr['true_sessions_split']}")
    print(f"  cases where a GOLD session is split                          "
          f"{agr['cases_where_a_GOLD_session_is_split']}")
    print(f"  mean sessions per case: derived {agr['mean_derived_sessions_per_case']}  "
          f"true {agr['mean_true_sessions_per_case']}\n")

    true_reads = {n: pruning_reads(pools, true_keys, n) for n in N_VALUES}
    derived_reads = {n: pruning_reads(pools, lambda p: derived_keys(p, gap_ms), n) for n in N_VALUES}

    print(f"Arm 1 re-derived on the FIT split -- frozen rule (max aggregation, union of per-cue top-N):")
    print(f"  {'partition':>9}  {'N':>2}  {'pool':>7}  {'goldret':>7}  {'oracle@1':>8}  "
          f"{'wrong_sess':>10}  {'wrong_rank':>10}  {'solved':>6}")
    for label, reads in (("true", true_reads), ("derived", derived_reads)):
        for n in N_VALUES:
            r = reads[n]
            d = r["failure_decomposition"]
            print(f"  {label:>9}  {n:>2}  {r['surviving_pool_fraction_mean']:>7.4f}  "
                  f"{r['gold_retention']:>7.4f}  {r['rates']['oracle@1']:>8.4f}  "
                  f"{d.get('wrong_session', 0):>10}  {d.get('right_session_wrong_rank', 0):>10}  "
                  f"{d.get('solved', 0):>6}")
    print()

    t, dv = true_reads[n_primary], derived_reads[n_primary]
    retention_delta = dv["gold_retention"] - t["gold_retention"]
    inflation = dv["surviving_pool_fraction_mean"] / t["surviving_pool_fraction_mean"]
    primary_pass = abs(retention_delta) <= tol
    guard_pass = inflation <= inflation_max
    usable = primary_pass and guard_pass

    print(f"REGISTERED BANDS at N={n_primary}, read against the fit split:")
    print(f"  primary  gold retention derived {dv['gold_retention']:.4f} vs true "
          f"{t['gold_retention']:.4f}  delta {retention_delta:+.4f}  "
          f"band |delta| <= {tol}   {'PASS' if primary_pass else 'FAIL'}")
    print(f"  guard    pool fraction derived {dv['surviving_pool_fraction_mean']:.4f} vs true "
          f"{t['surviving_pool_fraction_mean']:.4f}  inflation {inflation:.3f}x  "
          f"band <= {inflation_max}x   {'PASS' if guard_pass else 'FAIL'}")
    print()

    ids = [
        identity_check(pools, true_keys, "true"),
        identity_check(pools, lambda p: derived_keys(p, gap_ms), "derived"),
    ]
    print("Registered structural prediction -- max-aggregation identity, measured not inherited:")
    for i in ids:
        print(f"  {i['partition']:>8}: {i['checked_case_cue_pairs']} case-cue pairs, "
              f"{i['violations']} violations, "
              f"{'IDENTITY HOLDS' if i['identity_holds'] else 'IDENTITY BROKEN'}")
    print()

    report = {
        "_what": (
            "Session H Phase 1 -- the sessionizer measured against its registered band, and arm 1 "
            "re-derived on the FIT split. Held-out is not read."
        ),
        "split": "fit",
        "cases": len(pools),
        "frozen": {"session_gap_ms": gap_ms, "prune_N": n_primary,
                   "rule": frozen["session_scoring_rule"]["value"]},
        "partition_agreement": agr,
        "arm1_true_partition": true_reads,
        "arm1_derived_partition": derived_reads,
        "registered_bands": {
            "primary_gold_retention": {
                "derived": dv["gold_retention"], "true": t["gold_retention"],
                "delta": round(retention_delta, 4), "band": tol, "pass": primary_pass,
            },
            "guard_pool_fraction": {
                "derived": dv["surviving_pool_fraction_mean"],
                "true": t["surviving_pool_fraction_mean"],
                "inflation": round(inflation, 4), "band": inflation_max, "pass": guard_pass,
            },
            "sessionizer_usable": usable,
            "_on_failure": band["UNUSABLE_IF"]["then"],
        },
        "max_aggregation_identity": ids,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not usable:
        print("SESSIONIZER UNUSABLE against its registered band. STOPPING, per the registration.")
        print("No fallback to parsing turn_id, and the gap threshold is not swept to rescue it.")
        print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
        return 1

    print("SESSIONIZER USABLE. Timestamp contiguity carries the session structure this needs.")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
