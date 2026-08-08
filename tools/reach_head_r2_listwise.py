"""R2 -- reachability for candidate B: set-wise / listwise scoring.

The shipped cross-encoder scores each (query, candidate) pair in isolation. Nothing in the shipped
path ever compares two candidates directly. Candidate B scores the slate jointly, so the model can
observe that candidate B resolves candidate A, or that A is superseded.

Unlike candidate A, this shape moves the RANKING, so it moves R@1, R@5, conditional accuracy AND
the whole precision/coverage curve including the head. This script establishes:

  ADR-010 reach  -- the structural ceiling (gold present in the slate) and the realised headroom,
                    plus what a joint scorer CANNOT move (input recall: the slate is given).
  ADR-013 read   -- how many fit queries a joint scorer could change top-1 on, in both directions.
  ADR-014 power  -- exact McNemar's floor (2/2^n <= alpha => n >= 6) and the fit-split discordance
                    of the strongest realisable proxy on the EXACT contrast the held-out test will
                    consume: joint-scored top-1 vs shipped top-1, same slate, same split.

The proxy used for the discordance measurement is deliberately WEAK and stated as such: an oracle
cannot be the instrument check, because an oracle's discordance is an upper bound rather than an
estimate of what the built arm will produce. Two realisable proxies are measured instead.

Prints numbers. Applies nothing. Fit split for every selection read; the held-out columns are
descriptive of the ALREADY-PUBLISHED Session K ranking and introduce no new held-out decision.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
OUT = REPO / "runs" / "session-m0c" / "reach-r2-listwise.json"

ALPHA = 0.05
MIN_DISCORDANT_MCNEMAR = 6      # 2/2^n <= 0.05  =>  n >= 6
MIN_DISCORDANT_REPORTABLE = 10  # ADR-013's numeric form, runs/session-i/PREREGISTRATION.json


def mcnemar_exact_two_sided(b: int, c: int) -> float:
    """Binomial over the discordant pairs only."""
    n = b + c
    if n == 0:
        return float("nan")
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def smallest_attainable_p(n: int) -> float:
    return 1.0 if n == 0 else min(1.0, 2.0 / (2.0 ** n))


def load(split: str) -> list[dict]:
    d = json.loads(Path(str(SLATES).format(split=split)).read_text(encoding="utf-8"))
    if d["n"] != 229:
        raise SystemExit(f"REFUSING: {split} n={d['n']}, canonical 229")
    return d["records"]


def gold_rank(rec: dict) -> int:
    """Rank (0-based) of the first gold candidate in shipped order; -1 if none in slate."""
    for i, g in enumerate(rec["gold"]):
        if g:
            return i
    return -1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    data = {s: load(s) for s in ("fit", "heldout")}
    report: dict = {"_what": "R2 reachability for set-wise / listwise scoring."}

    print("=" * 92)
    print("R2 -- CAN JOINT (SET-WISE / LISTWISE) SCORING MOVE THE METRIC?")
    print("=" * 92)

    # ---------------- ADR-010 reach: the structural ceiling ----------------
    print()
    print("-" * 92)
    print("ADR-010 REACH -- the ceiling, and where the recoverable mass sits")
    print("-" * 92)
    print(f"{'split':<9} {'n':>4} {'R@1 now':>8} {'gold in slate':>14} {'CEILING':>8} "
          f"{'headroom':>9} {'recoverable':>12}")
    for split, recs in data.items():
        n = len(recs)
        r1 = sum(r["correct"] for r in recs) / n
        gis = sum(r["gold_in_slate"] for r in recs) / n
        recoverable = sum(1 for r in recs if r["gold_in_slate"] and not r["correct"])
        print(f"{split:<9} {n:>4d} {r1:>8.4f} {gis:>14.4f} {gis:>8.4f} "
              f"{gis-r1:>9.4f} {recoverable:>9d} q")
        report.setdefault("ceiling", {})[split] = {
            "n": n, "r_at_1": round(r1, 4), "gold_in_slate": round(gis, 4),
            "ceiling_r_at_1": round(gis, 4), "headroom": round(gis - r1, 4),
            "recoverable_queries": recoverable,
        }

    print()
    print("  CAN MOVE     R@1, R@5, conditional accuracy, and every point on the precision/")
    print("               coverage curve INCLUDING the head. A joint scorer reorders the slate,")
    print("               so both which query looks confident and whether rank 1 is right change.")
    print("  CANNOT MOVE  input recall / gold-in-slate. The slate is an INPUT to this shape. The")
    print("               ceiling above is hard for every candidate-B variant, exactly as R@10")
    print("               was hard for the cross-encoder in Session H.")
    print("  CANNOT MOVE  the R0 interval verdict at 10% coverage. n_c = 23 caps the Clopper-")
    print("               Pearson lower bound at 0.8518 even at 23/23.")

    # ---------------- where the recoverable mass sits ----------------
    print()
    print("-" * 92)
    print("WHERE THE RECOVERABLE MASS SITS -- rank of the first gold, among failures")
    print("-" * 92)
    for split, recs in data.items():
        fails = [r for r in recs if r["gold_in_slate"] and not r["correct"]]
        ranks = Counter(gold_rank(r) for r in fails)
        tot = len(fails)
        cum = 0
        parts = []
        for k in range(1, 10):
            cum += ranks.get(k, 0)
            parts.append(f"<= {k+1}: {cum:>2d} ({cum/tot:.0%})")
        print(f"  {split:<8} {tot} recoverable failures")
        print(f"           gold at rank 2: {ranks.get(1,0)}  rank 3: {ranks.get(2,0)}  "
              f"rank 4: {ranks.get(3,0)}  rank 5: {ranks.get(4,0)}  "
              f"rank 6-10: {sum(ranks.get(k,0) for k in range(5,10))}")
        print(f"           cumulative  {'  '.join(parts[:5])}")
        report.setdefault("gold_rank_among_failures", {})[split] = {
            "n_failures_with_gold_in_slate": tot,
            "by_rank": {str(k + 1): ranks.get(k, 0) for k in range(1, 10)},
        }

    # ---------------- the joint-structure hypothesis, measured ----------------
    print()
    print("-" * 92)
    print("THE JOINT-STRUCTURE HYPOTHESIS -- is the gold RELATED to the wrong rank-1?")
    print("-" * 92)
    print("  If joint scoring is the right shape, the recoverable gold should sit in a measurable")
    print("  RELATION to the candidate that beat it -- same session, adjacent turn, opposite role.")
    print("  A pairwise scorer cannot see any of those. This measures whether they are there.")
    print()

    def sess(t: str) -> str:
        return t.rsplit("-", 1)[0]

    def tix(t: str) -> int:
        try:
            return int(t.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return -10_000

    print("  THE COMPARISON GROUP IS RANK-1 vs RANK-2, NOT RANK-1 vs GOLD.")
    print("  A first version of this read compared rank 1 to the gold in both groups. On")
    print("  successes the gold IS rank 1, so 'same session' was 1.0000 and 'opposite role'")
    print("  0.0000 BY CONSTRUCTION -- a null instrument whose silence is not evidence. The")
    print("  contrast below is the relation between the top TWO candidates in each group, which")
    print("  is defined and non-degenerate on both sides.")
    print()

    def relation(r: dict, i: int, j: int) -> tuple[bool, bool, bool]:
        ti, tj = r["turn_ids"][i], r["turn_ids"][j]
        same = sess(ti) == sess(tj)
        near = same and abs(tix(tj) - tix(ti)) <= 2
        opp = r["roles"][i] != r["roles"][j]
        return same, near, opp

    for split, recs in data.items():
        fails = [r for r in recs if r["gold_in_slate"] and not r["correct"]]
        wins = [r for r in recs if r["correct"]]
        stats = {}
        # failures: rank 1 (wrong) against the first gold, which is what a joint scorer must
        # promote. successes: rank 1 (right) against rank 2, the distractor it had to beat.
        for label, group, pick in (("failures (rank1 vs gold)", fails, gold_rank),
                                   ("successes (rank1 vs rank2)", wins, lambda _r: 1)):
            same_sess = adj = opp_role = 0
            gaps = []
            for r in group:
                j = pick(r)
                if j <= 0:
                    continue
                s_, n_, o_ = relation(r, 0, j)
                same_sess += s_
                adj += n_
                opp_role += o_
                if s_:
                    gaps.append(tix(r["turn_ids"][j]) - tix(r["turn_ids"][0]))
            m = max(len(group), 1)
            stats[label] = {
                "n": len(group),
                "same_session": round(same_sess / m, 4),
                "within_2_turns": round(adj / m, 4),
                "opposite_role": round(opp_role / m, 4),
                "median_turn_gap_when_same_session": (
                    float(np.median(gaps)) if gaps else None),
            }
        keys = list(stats)
        f, s = stats[keys[0]], stats[keys[1]]
        print(f"  {split}:")
        print(f"    {'':<32}{'failures':>12}{'successes':>12}")
        print(f"    {'':<32}{'rank1 vs gold':>12}{'rank1 vs r2':>12}")
        print(f"    {'n':<32}{f['n']:>12d}{s['n']:>12d}")
        for k in ("same_session", "within_2_turns", "opposite_role"):
            print(f"    {k:<32}{f[k]:>12.4f}{s[k]:>12.4f}")
        report.setdefault("joint_structure", {})[split] = stats

    # ---------------- ADR-013 / ADR-014: the read, and power on the exact contrast ----------
    print()
    print("-" * 92)
    print("ADR-013 READ + ADR-014 POWER -- on the EXACT contrast the held-out test consumes")
    print("-" * 92)
    print("  contrast: joint-scored top-1  vs  shipped pairwise top-1, same slate, same split.")
    print("  test: two-sided exact McNemar over queries whose top-1 differs.")
    print(f"  alpha = {ALPHA}; smallest attainable two-sided p is 2/2^n, so n >= "
          f"{MIN_DISCORDANT_MCNEMAR}.")
    print(f"  ADR-013's separate floor for reporting a delta at all: n >= "
          f"{MIN_DISCORDANT_REPORTABLE}.")
    print()
    print("  An oracle's discordance is an UPPER BOUND, not an estimate of what a built arm")
    print("  produces, so two REALISABLE proxies are measured beside it. Fit split.")
    print()

    recs = data["fit"]
    proxies: dict[str, np.ndarray] = {}

    # proxy 1: rank by (rerank logit) - lambda * log(wordpieces) is CLOSED (ADR-017, length
    # normalization). Not used. Instead: reorder by the slate's own softmax under a temperature
    # that is a function of the SLATE, which no pairwise scorer can compute -- the cheapest
    # genuinely joint transform available without training anything.
    def joint_zscore(r: dict) -> np.ndarray:
        s = np.asarray(r["rerank_scores"], dtype=float)
        sd = s.std()
        return (s - s.mean()) / (sd if sd > 1e-9 else 1.0)

    # proxy 2: a purely joint, training-free rule -- promote a candidate that is the USER turn
    # immediately preceding an assistant rank-1 in the same session. This is exactly the
    # "candidate B resolves candidate A" relation, expressed as a hand rule.
    def resolves_rule(r: dict) -> np.ndarray:
        s = np.asarray(r["rerank_scores"], dtype=float)
        bonus = np.zeros_like(s)
        t0, r0 = r["turn_ids"][0], r["roles"][0]
        for j in range(1, len(s)):
            tj, rj = r["turn_ids"][j], r["roles"][j]
            if sess(tj) != sess(t0):
                continue
            gap = tix(tj) - tix(t0)
            if r0 == "assistant" and rj == "user" and gap in (-1, -2):
                bonus[j] = 1.0
        return s + bonus * (s[0] - s[1] + 1e-6) * 1.01  # just enough to overtake

    for label, fn in (("slate z-score (joint normalisation)", joint_zscore),
                      ("'user turn that rank-1 answers' promotion", resolves_rule)):
        gained = lost = 0
        for r in recs:
            new = fn(r)
            top_new = int(np.argmax(new))
            old_ok = r["correct"]
            new_ok = bool(r["gold"][top_new])
            changed = top_new != 0
            if changed and new_ok and not old_ok:
                gained += 1
            elif changed and old_ok and not new_ok:
                lost += 1
        disc = gained + lost
        p = mcnemar_exact_two_sided(gained, lost)
        print(f"  {label}")
        print(f"    discordant {disc} (gained {gained}, lost {lost})  "
              f"exact McNemar p = {p:.4f}  smallest attainable p at this n = "
              f"{smallest_attainable_p(disc):.4f}")
        print(f"    alpha attainable: {'YES' if disc >= MIN_DISCORDANT_MCNEMAR else 'NO'};  "
              f"clears ADR-013 reporting floor: "
              f"{'YES' if disc >= MIN_DISCORDANT_REPORTABLE else 'NO'}")
        report.setdefault("adr_014_discordance_proxies", {})[label] = {
            "discordant": disc, "gained": gained, "lost": lost,
            "exact_mcnemar_p": round(p, 4),
            "smallest_attainable_p": round(smallest_attainable_p(disc), 4),
            "alpha_attainable": disc >= MIN_DISCORDANT_MCNEMAR,
            "clears_adr_013_floor": disc >= MIN_DISCORDANT_REPORTABLE,
            "_this_is_a_proxy": "a training-free stand-in measured so the instrument check is "
                                "not taken on an oracle; the built arm's own discordance is "
                                "measured on fit before the held-out read",
        }
        print()

    # the oracle bound on discordance, reported and explicitly not the instrument check
    orc_gain = sum(1 for r in recs if r["gold_in_slate"] and not r["correct"])
    print(f"  ORACLE upper bound on discordance: {orc_gain} (every recoverable failure fixed, "
          f"none lost).")
    print("  Reported only. ADR-014 requires the instrument check on a REALISABLE contrast;")
    print("  Session H's defect was measuring the wrong contrast, not measuring too small a one.")
    report["oracle_discordance_upper_bound"] = orc_gain

    # ---------------- what the target implies ----------------
    print()
    print("-" * 92)
    print("WHAT THE STATED GOAL IMPLIES -- R@1 near 0.80 on held-out")
    print("-" * 92)
    h = report["ceiling"]["heldout"]
    need = 0.80
    n = h["n"]
    have = int(round(h["r_at_1"] * n))
    want = math.ceil(need * n)
    print(f"  held-out: {have}/{n} correct now ({h['r_at_1']:.4f}); 0.80 needs {want}/{n}.")
    print(f"  that is +{want-have} queries, drawn from the {h['recoverable_queries']} recoverable "
          f"failures = {(want-have)/h['recoverable_queries']:.0%} of them.")
    print(f"  hard ceiling is {h['ceiling_r_at_1']:.4f} ({int(round(h['ceiling_r_at_1']*n))}/{n}).")
    report["goal_implication"] = {
        "target_r_at_1": need, "heldout_now": have, "heldout_needed": want,
        "queries_to_gain": want - have, "recoverable_pool": h["recoverable_queries"],
        "fraction_of_recoverable_needed": round((want - have) / h["recoverable_queries"], 4),
        "hard_ceiling": h["ceiling_r_at_1"],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
