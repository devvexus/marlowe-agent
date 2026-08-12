"""H-D: how much of the head is actually DECIDABLE? The honest ceiling.

    python tools/head_decidability.py
    -> runs/session-m0c-m/head-decidability.json

`head-probe.json` reports a maximum reachable of **+26 cases** -- the POSITIVE head pairs, where
rank 2 is gold and rank 1 is not, so a flip fixes the case. That number is the ceiling every
subsequent mechanism has been scored against. **This module asks whether it is real.**

Reading `near-misses.md`, case after case has a rank-1 turn that ALSO STATES THE GOLD ANSWER:

    22d2cb42  "Where did I get my guitar serviced?"  -> "The music shop on Main St."
              rank 1: "...I remember the music shop on Main St where I got my guitar serviced..."

A pair like that is not a decision a text feature could get right. Both members answer the
question; which one carries the corpus's `has_answer` flag is a labelling accident. Crediting a
reordering rule for flipping it is crediting it for a coin toss it happened to win.

## The three measurements

**(i)  Answer containment at rank 1 on the 26 POSITIVE pairs.** Machine count, using
      `answer_containment`'s matcher -- imported, not reimplemented -- plus a full text dump of all
      26 so the machine count can be hand-checked. Both counts are reported. A matcher is a
      measurement instrument and 26 cases is cheap to read.

**(ii) THE CONTROL, and it is the whole point.** The same matcher on the NON-GOLD member of the
      SOLVED head pairs: the **rank-2 turn of the 110 NEGATIVE pairs**. Structurally identical --
      in a POSITIVE pair the non-gold member is rank 1, in a NEGATIVE pair it is rank 2 -- so this
      is apples to apples. If a runner-up in a solved case contains the answer at a similar rate,
      containment is a **corpus property, not a failure property**, and (i) means nothing. The 93
      AMBIGUOUS pairs are run too, both members, split by both-gold vs neither-gold.

**(iii) Near-duplicate structure at the head.** rank1 <-> rank2 content-word Jaccard
      (`correct_case_control.content_words`) and dense cosine under the shipped embedder
      (`reach_embed`: the Rust cache's own vectors where present, `JinaEmbedder` otherwise).
      Distribution split by label. Question: **are POSITIVE pairs systematically more
      near-duplicate than NEGATIVE ones** -- i.e. is the head decision often between two
      restatements of one fact, where no text feature could prefer either?

## The corrected ceiling

    POSITIVE pairs whose rank-1 turn does NOT contain the answer
      = the cases a reordering rule could actually be CREDITED for,

split above and below the 0.084 cross-encoder gap band (`|rerank_gap|`), because below it the two
logits are effectively identical and blind swapping already scores +5.

**No LLM anywhere.** String matching and the shipped embedder only.

## Gates

1. `head_probe.build()` reproduces fit R@1 = 0.7555 exactly or refuses -- and its own negative
   control (the cue-only order) is run and must refuse.
2. The rank-1 containment computed here must agree, case for case, with the committed
   `answer-containment.json`. That file was written by a different code path; a disagreement means
   this module has a second, quietly different matcher, which is the thing it exists not to have.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from answer_containment import (  # noqa: E402
    contains_loose,
    contains_strict,
    content_tokens,
    normalise,
)
from correct_case_control import content_words  # noqa: E402
from head_probe import (  # noqa: E402
    AMBIGUOUS,
    NEGATIVE,
    OUT_DIR,
    POSITIVE,
    build,
    self_check,
)

BAND = 0.084  # RESEARCH/brief §3.4: below this the two cross-encoder logits are effectively equal.

# -- THE HAND COUNT -------------------------------------------------------------------------------
#
# A matcher is an instrument, and 26 cases is cheap to read. Every POSITIVE pair was read in full
# from `head-decidability-positive-dump.md` and adjudicated by eye. This table is the record of that
# reading; it is NEVER used to compute the machine numbers, only compared against them.
#
#   contains  -- does the RANK-1 turn (the non-gold winner) STATE the gold answer?
#   arbitrary -- is the gold LABEL arbitrary on this pair? True when rank 1 and rank 2 restate the
#                same underlying fact, or when the case is multi-hop and rank 1 is at least as
#                sufficient as the flagged gold turn. A flip here changes R@1 without the injected
#                turn becoming any more able to answer the question, so no rule deserves credit for
#                getting it "right".
HAND = {
    # query_id:        (contains, arbitrary, note)
    "58bf7951":        (False, False, "rank1 mentions attending a play, never names it"),
    "0100672e":        (False, True,  "two-hop: rank1 has $60 total, gold has '5 mugs'. Each is one "
                                      "half; neither states $12"),
    "gpt4_45189cb4":   (False, False, "rank1 is about autocross; unrelated"),
    "caf9ead2":        (False, False, "rank1 says '20 minutes away', not the 5-hour move"),
    "6222b6eb":        (True,  False, "rank1: '6S ... It is implemented in the SIAC_GEE tool'. "
                                      "Verbatim. The gold turn states it too"),
    "58ef2f1c":        (False, False, "rank1 has 'back in February' only; gold has \"Valentine's "
                                      "Day\", which is the answer given world knowledge"),
    "5c40ec5b":        (True,  False, "rank1: \"we've met up twice before\""),
    "60036106":        (False, True,  "rank1 and gold state the SAME fact -- 'reached around 2,000 "
                                      "people'. Neither states 12,000"),
    "22d2cb42":        (True,  False, "rank1: 'the music shop on Main St where I got my guitar "
                                      "serviced'"),
    "a89d7624":        (False, False, "rank1 is about packing for California; unrelated"),
    "e3fc4d6e":        (True,  False, "rank1 is the pasted article and contains 'Dr. Arati "
                                      "Prabhakar' verbatim; gold is the assistant's entity list"),
    "c6853660":        (True,  False, "MACHINE MISS. rank1: 'I have increased the limit to two "
                                      "cups'. The answer string carries 'one cup' as well, which "
                                      "rank1 lacks, so LOOSE fails on a token the answer to the "
                                      "question does not need"),
    "gpt4_2f584639":   (False, True,  "MACHINE FALSE POSITIVE. {album, mom, photo} are all present "
                                      "but the question is which gift came FIRST, and rank1 does "
                                      "not establish an order. Ordering needs both turns"),
    "89527b6b":        (False, False, "rank1 is the user's authoring prompt; no colour anywhere"),
    "46a3abf7":        (False, True,  "rank1 names TWO tanks (5-gal + 20-gal), gold names one. "
                                      "rank1 is strictly more sufficient toward '3'"),
    "77eafa52":        (False, True,  "rank1 and gold both state 'quoted me $2,500'. Same fact; "
                                      "neither states $300"),
    "gpt4_5dcc0aab":   (True,  False, "rank1 and gold are near-paraphrases and BOTH say 'cleaned my "
                                      "white Adidas sneakers last month'"),
    "b46e15ed":        (False, False, "rank1 is the 'Ride to Cure Cancer' ride; not the consecutive "
                                      "pair"),
    "b29f3365":        (False, True,  "rank1 and gold both state 'new amp two weeks ago'. Same "
                                      "fact; 'four weeks' needs the lesson-start turn"),
    "b86304ba":        (False, False, "rank1 is the vinyl record, not the sunset painting"),
    "3ba21379":        (False, True,  "rank1 and gold BOTH say 'Ford Mustang Shelby GT350R'. The "
                                      "answer is 'Ford F-150 pickup truck' and NEITHER contains it "
                                      "-- the flagged gold turn does not answer its own question"),
    "ba61f0b9":        (False, False, "rank1 is the user asking the question; gold gives 'team of "
                                      "10, half women' (=5) against an answer of 6, so the gold is "
                                      "itself weak, but rank1 is clearly weaker"),
    "07741c44":        (False, False, "rank1 is the cobbler drop-off; 'under my bed' is only in "
                                      "gold"),
    "157a136e":        (False, True,  "rank1 and gold both state grandma's 75th birthday. Same "
                                      "fact; '43' needs the user's own age"),
    "a1eacc2a":        (False, False, "rank1 is the workshop turn; gold has 'completed 7 short "
                                      "stories'. A clean, decidable pair"),
    "gpt4_468eb063":   (False, False, "rank1 is about Sophia at a networking event, not Emma"),
}
OUT_PATH = OUT_DIR / "head-decidability.json"
CONTAINMENT_PATH = OUT_DIR / "answer-containment.json"
DUMP_PATH = OUT_DIR / "head-decidability-positive-dump.md"


# -- the matcher, applied. `contains` is the ONLY containment decision in this file. ---------------


def contains(answer: str, text: str) -> dict:
    """`answer_containment`'s rule, verbatim, applied to an arbitrary (answer, turn) pair.

    Every function called here is imported from `answer_containment`. Nothing is re-derived: if the
    rule is wrong it is wrong identically in both files, which is the only kind of agreement worth
    having between two call sites.
    """
    ans_tokens = normalise(answer)
    ans_content = content_tokens(ans_tokens)
    tt = normalise(text)
    strict = contains_strict(ans_tokens, tt)
    loose = strict or contains_loose(ans_content, set(tt))
    return {
        "strict": bool(strict),
        "loose": bool(loose),
        "n_answer_content_tokens": len(ans_content),
        "answer_content_tokens": sorted(ans_content),
        "scorable": bool(ans_content),
        "min2": len(ans_content) >= 2,
    }


def tally(rows: list[dict], key: str) -> dict:
    """Rates over the rows that are scorable at all. `min2` is the sensitivity band."""
    scorable = [r for r in rows if r[key]["scorable"]]
    min2 = [r for r in scorable if r[key]["min2"]]
    n, m = len(scorable), len(min2)
    return {
        "n_pairs": len(rows),
        "n_scorable": n,
        "n_unscorable_zero_content_answer": len(rows) - n,
        "strict": sum(r[key]["strict"] for r in scorable),
        "loose": sum(r[key]["loose"] for r in scorable),
        "strict_rate": round(sum(r[key]["strict"] for r in scorable) / n, 4) if n else None,
        "loose_rate": round(sum(r[key]["loose"] for r in scorable) / n, 4) if n else None,
        "n_min2": m,
        "loose_min2": sum(r[key]["loose"] for r in min2),
        "loose_min2_rate": round(sum(r[key]["loose"] for r in min2) / m, 4) if m else None,
        "strict_min2": sum(r[key]["strict"] for r in min2),
        "strict_min2_rate": round(sum(r[key]["strict"] for r in min2) / m, 4) if m else None,
    }


# -- gate 2: agree with the committed containment record -------------------------------------------


def cross_check_rank1(rows: list[dict]) -> dict:
    if not CONTAINMENT_PATH.exists():
        raise SystemExit(
            f"REFUSING. {CONTAINMENT_PATH} does not exist. Run tools/answer_containment.py first -- "
            "without it the matcher here is unchecked against the committed record."
        )
        # unreachable, kept explicit
    committed = {
        r["query_id"]: r
        for r in json.loads(CONTAINMENT_PATH.read_text(encoding="utf-8"))["records"]
    }
    checked = disagree = missing = 0
    bad = []
    for r in rows:
        c = committed.get(r["query_id"])
        if c is None:
            missing += 1
            continue
        checked += 1
        if (
            c["rank1_contains_strict"] != r["rank1"]["strict"]
            or c["rank1_contains_loose"] != r["rank1"]["loose"]
        ):
            disagree += 1
            bad.append(r["query_id"])
    if disagree:
        raise SystemExit(
            "REFUSING. rank-1 containment here disagrees with answer-containment.json on "
            f"{disagree} queries ({bad[:10]}). Two matchers, not one."
        )
    return {"checked": checked, "disagreements": 0, "not_in_committed_record": missing}


# -- (iii) near-duplicate structure ----------------------------------------------------------------


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Vectors:
    """The shipped embedder. Rust's own cached vector where the text is in the cache, else Python.

    Both come from `reach_embed`; neither is reimplemented here. The cache is preferred because it
    is literally the vector the product used, so a cache hit removes the second implementation from
    the measurement entirely. `n_from_cache` / `n_computed` are reported so the mix is visible.
    """

    def __init__(self):
        from reach_embed import JinaEmbedder, RustEmbeddingCache

        try:
            self.cache = RustEmbeddingCache()
        except SystemExit as exc:  # a missing/multiple cache is not fatal; the embedder covers it
            print(f"  cache unavailable ({exc}); every vector will be computed")
            self.cache = None
        self.embedder = JinaEmbedder()
        self.n_from_cache = 0
        self.n_computed = 0
        self._memo: dict[str, np.ndarray] = {}

    def get(self, text: str) -> np.ndarray:
        v = self._memo.get(text)
        if v is not None:
            return v
        v = self.cache.get(text) if self.cache is not None else None
        if v is None:
            v = self.embedder.embed(text)
            self.n_computed += 1
        else:
            self.n_from_cache += 1
        self._memo[text] = np.asarray(v, dtype=np.float32)
        return self._memo[text]

    def cosine(self, a: str, b: str) -> float:
        va, vb = self.get(a), self.get(b)
        na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))


def dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    s = sorted(values)

    def q(p):
        return round(s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))], 4)

    return {
        "n": len(s),
        "mean": round(statistics.fmean(s), 4),
        "median": q(0.5),
        "p10": q(0.10),
        "p25": q(0.25),
        "p75": q(0.75),
        "p90": q(0.90),
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
    }


def frac_above(values: list[float], t: float) -> dict:
    if not values:
        return {"n": 0, "count": 0, "rate": None}
    c = sum(1 for v in values if v >= t)
    return {"n": len(values), "count": c, "rate": round(c / len(values), 4)}


# -- main ------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    print("=" * 96)
    print("GATE 1 -- reconstruct the shipped fit ranking, or refuse")
    print("=" * 96)
    pools, pairs, r1 = build()

    ctl = self_check(pools)
    print(f"gate negative control: cue-only order reconstructs fit R@1 {ctl['cue_only_r1']}; "
          f"gate refused: {ctl['refused']}")
    if not ctl["refused"]:
        raise SystemExit("REFUSING. The gate accepted a ranking that is not the shipped one.")
    print(f"  {ctl['message']}")

    counts = Counter(p["label"] for p in pairs)
    n = len(pairs)
    print(f"\npopulation: {n} pairs -- POSITIVE {counts[POSITIVE]}, NEGATIVE {counts[NEGATIVE]}, "
          f"AMBIGUOUS {counts[AMBIGUOUS]}")

    # -- per-pair containment, both members --------------------------------------------------------
    rows = []
    for p in pairs:
        ans = p["gold_answer"] or ""
        rows.append(
            {
                "query_id": p["query_id"],
                "label": p["label"],
                "category": p["category"],
                "question": p["question"],
                "gold_answer": p["gold_answer"],
                "rerank_gap": p["rerank_gap"],
                "abs_rerank_gap": abs(p["rerank_gap"]) if p["rerank_gap"] is not None else None,
                "n_gold_turns": p["n_gold_turns"],
                "rank1_is_gold": p["rank1_is_gold"],
                "rank2_is_gold": p["rank2_is_gold"],
                "rank1": contains(ans, p["rank1"]["text"]),
                "rank2": contains(ans, p["rank2"]["text"]),
                "rank1_text": p["rank1"]["text"],
                "rank2_text": p["rank2"]["text"],
            }
        )

    print("\n" + "=" * 96)
    print("GATE 2 -- rank-1 containment must agree with the committed answer-containment.json")
    print("=" * 96)
    xc = cross_check_rank1(rows)
    print(f"  checked {xc['checked']} queries, disagreements {xc['disagreements']}, "
          f"not in committed record {xc['not_in_committed_record']}")

    pos = [r for r in rows if r["label"] == POSITIVE]
    neg = [r for r in rows if r["label"] == NEGATIVE]
    amb = [r for r in rows if r["label"] == AMBIGUOUS]
    amb_both = [r for r in amb if r["rank1_is_gold"] and r["rank2_is_gold"]]
    amb_neither = [r for r in amb if not r["rank1_is_gold"] and not r["rank2_is_gold"]]

    # -- (i) ---------------------------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("(i) ANSWER CONTAINMENT AT RANK 1, ON THE POSITIVE PAIRS -- the non-gold winner")
    print("=" * 96)
    t_pos = tally(pos, "rank1")
    print(f"  POSITIVE pairs                        {t_pos['n_pairs']}")
    print(f"  scorable (answer has content tokens)  {t_pos['n_scorable']}")
    print(f"  rank-1 contains answer STRICT         {t_pos['strict']}  "
          f"({t_pos['strict_rate']})")
    print(f"  rank-1 contains answer LOOSE          {t_pos['loose']}  ({t_pos['loose_rate']})")
    print(f"  rank-1 contains LOOSE, answers >=2ct  {t_pos['loose_min2']} of {t_pos['n_min2']}  "
          f"({t_pos['loose_min2_rate']})")
    print("\n  query ids where rank 1 CONTAINS the answer (loose):")
    for r in pos:
        if r["rank1"]["scorable"] and r["rank1"]["loose"]:
            print(f"    {r['query_id']:16s} strict={str(r['rank1']['strict']):5s} "
                  f"gap={r['abs_rerank_gap']:.4f}  {r['gold_answer'][:60]!r}")
    print("\n  query ids where rank 1 does NOT contain the answer:")
    for r in pos:
        if not (r["rank1"]["scorable"] and r["rank1"]["loose"]):
            print(f"    {r['query_id']:16s} gap={r['abs_rerank_gap']:.4f}  "
                  f"{r['gold_answer'][:60]!r}")

    # -- (ii) THE CONTROL --------------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("(ii) THE CONTROL -- the SAME matcher on the non-gold member of a SOLVED head pair")
    print("=" * 96)
    t_neg = tally(neg, "rank2")
    t_amb1, t_amb2 = tally(amb, "rank1"), tally(amb, "rank2")
    t_ab1, t_ab2 = tally(amb_both, "rank1"), tally(amb_both, "rank2")
    t_an1, t_an2 = tally(amb_neither, "rank1"), tally(amb_neither, "rank2")

    hdr = (f"  {'population':44s} {'n':>4} {'scor':>5} {'strict':>7} {'s-rate':>7} "
           f"{'loose':>6} {'l-rate':>7} {'l>=2ct':>7} {'rate':>7}")

    def row(label, t):
        print(f"  {label:44s} {t['n_pairs']:>4d} {t['n_scorable']:>5d} {t['strict']:>7d} "
              f"{(t['strict_rate'] if t['strict_rate'] is not None else float('nan')):>7.4f} "
              f"{t['loose']:>6d} "
              f"{(t['loose_rate'] if t['loose_rate'] is not None else float('nan')):>7.4f} "
              f"{t['loose_min2']:>7d} "
              f"{(t['loose_min2_rate'] if t['loose_min2_rate'] is not None else float('nan')):>7.4f}")

    print(hdr)
    row("POSITIVE rank1  (non-gold winner) <- (i)", t_pos)
    row("NEGATIVE rank2  (non-gold runner-up) CTRL", t_neg)
    row("AMBIGUOUS rank1", t_amb1)
    row("AMBIGUOUS rank2", t_amb2)
    row("  AMBIGUOUS both-gold rank1", t_ab1)
    row("  AMBIGUOUS both-gold rank2", t_ab2)
    row("  AMBIGUOUS neither-gold rank1", t_an1)
    row("  AMBIGUOUS neither-gold rank2", t_an2)

    # A single-line verdict on whether (i) survives its control.
    a, b = t_pos["loose_rate"], t_neg["loose_rate"]
    a2, b2 = t_pos["loose_min2_rate"], t_neg["loose_min2_rate"]
    print(f"\n  LOOSE:     POSITIVE-rank1 {a}   vs   NEGATIVE-rank2 {b}   "
          f"ratio {round(a / b, 3) if b else None}")
    print(f"  LOOSE>=2ct: POSITIVE-rank1 {a2}   vs   NEGATIVE-rank2 {b2}   "
          f"ratio {round(a2 / b2, 3) if b2 else None}")

    # -- (iii) near-duplicate structure ------------------------------------------------------------
    print("\n" + "=" * 96)
    print("(iii) NEAR-DUPLICATE STRUCTURE AT THE HEAD -- rank1 <-> rank2")
    print("=" * 96)
    print("  loading the shipped embedder ...")
    vecs = Vectors()
    for r in rows:
        w1, w2 = content_words(r["rank1_text"]), content_words(r["rank2_text"])
        r["jaccard"] = round(jaccard(w1, w2), 4)
        r["cosine"] = round(vecs.cosine(r["rank1_text"], r["rank2_text"]), 4)
    print(f"  vectors: {vecs.n_from_cache} from the Rust cache, {vecs.n_computed} computed "
          f"in Python (shipped graph, mean-pooled, L2-normalised)")

    groups = {
        "POSITIVE": pos,
        "NEGATIVE": neg,
        "AMBIGUOUS": amb,
        "AMBIGUOUS_both_gold": amb_both,
        "AMBIGUOUS_neither_gold": amb_neither,
    }
    struct = {}
    print(f"\n  {'group':24s} {'n':>4} | {'JACCARD':>8} {'med':>7} {'p75':>7} {'p90':>7} "
          f"{'>=.5':>6} | {'COSINE':>8} {'med':>7} {'p75':>7} {'p90':>7} {'>=.9':>6}")
    for name, g in groups.items():
        js = [r["jaccard"] for r in g]
        cs = [r["cosine"] for r in g]
        dj, dc = dist(js), dist(cs)
        struct[name] = {
            "n": len(g),
            "jaccard": dj,
            "cosine": dc,
            "jaccard_ge_0.3": frac_above(js, 0.3),
            "jaccard_ge_0.5": frac_above(js, 0.5),
            "cosine_ge_0.85": frac_above(cs, 0.85),
            "cosine_ge_0.90": frac_above(cs, 0.90),
            "cosine_ge_0.95": frac_above(cs, 0.95),
        }
        print(f"  {name:24s} {len(g):>4d} | {dj['mean']:>8.4f} {dj['median']:>7.4f} "
              f"{dj['p75']:>7.4f} {dj['p90']:>7.4f} "
              f"{struct[name]['jaccard_ge_0.5']['rate']:>6.3f} | "
              f"{dc['mean']:>8.4f} {dc['median']:>7.4f} {dc['p75']:>7.4f} {dc['p90']:>7.4f} "
              f"{struct[name]['cosine_ge_0.90']['rate']:>6.3f}")

    # -- the corrected ceiling ---------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("THE CORRECTED CEILING")
    print("=" * 96)

    def band_split(rs):
        above = [r for r in rs if r["abs_rerank_gap"] is not None and r["abs_rerank_gap"] > BAND]
        below = [r for r in rs if r["abs_rerank_gap"] is not None and r["abs_rerank_gap"] <= BAND]
        undef = [r for r in rs if r["abs_rerank_gap"] is None]
        return above, below, undef

    creditable = [r for r in pos if not (r["rank1"]["scorable"] and r["rank1"]["loose"])]
    creditable_strict = [r for r in pos if not (r["rank1"]["scorable"] and r["rank1"]["strict"])]
    a_all, b_all, u_all = band_split(pos)
    a_cr, b_cr, u_cr = band_split(creditable)
    a_cs, b_cs, u_cs = band_split(creditable_strict)

    def line(label, rs, a, b, u):
        print(f"  {label:52s} {len(rs):>4d}   above band {len(a):>3d}   below {len(b):>3d}   "
              f"undef {len(u):>3d}   dR@1 {len(rs)/n:>+7.4f} / above {len(a)/n:>+7.4f}")

    line("claimed ceiling: all POSITIVE pairs", pos, a_all, b_all, u_all)
    line("corrected (rank1 does NOT contain, LOOSE)", creditable, a_cr, b_cr, u_cr)
    line("corrected (rank1 does NOT contain, STRICT)", creditable_strict, a_cs, b_cs, u_cs)
    print(f"\n  band = |rerank_gap| > {BAND}; denominator for dR@1 is {n} fit queries")
    print("\n  the creditable POSITIVE pairs, ABOVE the band (LOOSE rule):")
    for r in sorted(a_cr, key=lambda r: -r["abs_rerank_gap"]):
        print(f"    {r['query_id']:16s} gap={r['abs_rerank_gap']:.4f} J={r['jaccard']:.3f} "
              f"cos={r['cosine']:.3f}  {r['gold_answer'][:52]!r}")

    # -- MACHINE COUNT vs HAND COUNT ---------------------------------------------------------------
    print("\n" + "=" * 96)
    print("MACHINE COUNT vs HAND COUNT -- all 26 POSITIVE pairs read in full")
    print("=" * 96)
    missing = sorted({r["query_id"] for r in pos} - set(HAND))
    extra = sorted(set(HAND) - {r["query_id"] for r in pos})
    if missing or extra:
        raise SystemExit(
            f"REFUSING. The hand table does not cover the POSITIVE set: missing {missing}, "
            f"extra {extra}. A hand count over a population that has moved is not a check."
        )
    machine_yes = {r["query_id"] for r in pos if r["rank1"]["loose"]}
    hand_yes = {q for q, (c, _a, _n) in HAND.items() if c}
    arbitrary = {q for q, (_c, a, _n) in HAND.items() if a}
    print(f"  machine LOOSE  {len(machine_yes):>2d} of 26   {sorted(machine_yes)}")
    print(f"  machine STRICT {t_pos['strict']:>2d} of 26")
    print(f"  HAND           {len(hand_yes):>2d} of 26   {sorted(hand_yes)}")
    print(f"  machine says yes, hand says no: {sorted(machine_yes - hand_yes)}")
    print(f"  hand says yes, machine says no: {sorted(hand_yes - machine_yes)}")
    for q in sorted((machine_yes - hand_yes) | (hand_yes - machine_yes)):
        print(f"    {q:16s} {HAND[q][2]}")

    gap_of = {r["query_id"]: r["abs_rerank_gap"] for r in pos}
    hand_creditable = {r["query_id"] for r in pos} - hand_yes
    hand_decidable = hand_creditable - arbitrary
    above = lambda s: {q for q in s if gap_of[q] is not None and gap_of[q] > BAND}  # noqa: E731
    print(f"\n  ARBITRARY-GOLD pairs (rank1 and rank2 restate one fact, or rank1 is no less "
          f"sufficient): {len(arbitrary)}")
    for q in sorted(arbitrary, key=lambda q: -gap_of[q]):
        print(f"    {q:16s} gap={gap_of[q]:.4f}  {HAND[q][2]}")
    print(f"\n  {'hand-creditable (rank1 does NOT state the answer)':52s} {len(hand_creditable):>4d}"
          f"   above band {len(above(hand_creditable)):>3d}   dR@1 {len(hand_creditable)/n:+.4f} / "
          f"above {len(above(hand_creditable))/n:+.4f}")
    print(f"  {'hand-DECIDABLE (also not an arbitrary gold label)':52s} {len(hand_decidable):>4d}"
          f"   above band {len(above(hand_decidable)):>3d}   dR@1 {len(hand_decidable)/n:+.4f} / "
          f"above {len(above(hand_decidable))/n:+.4f}")
    print(f"\n  the hand-DECIDABLE pairs above the band -- the honest headroom:")
    for q in sorted(above(hand_decidable), key=lambda q: -gap_of[q]):
        print(f"    {q:16s} gap={gap_of[q]:.4f}  {HAND[q][2]}")

    hand_block = {
        "_what": "every POSITIVE pair read in full and adjudicated by eye. NEVER used to compute "
                 "the machine numbers -- only compared against them.",
        "machine_loose": sorted(machine_yes),
        "machine_loose_count": len(machine_yes),
        "machine_strict_count": t_pos["strict"],
        "hand_contains": sorted(hand_yes),
        "hand_contains_count": len(hand_yes),
        "machine_yes_hand_no": sorted(machine_yes - hand_yes),
        "hand_yes_machine_no": sorted(hand_yes - machine_yes),
        "arbitrary_gold": sorted(arbitrary),
        "arbitrary_gold_count": len(arbitrary),
        "hand_creditable": {
            "cases": len(hand_creditable),
            "above_band": len(above(hand_creditable)),
            "r1_delta": round(len(hand_creditable) / n, 4),
            "r1_delta_above_band": round(len(above(hand_creditable)) / n, 4),
            "query_ids": sorted(hand_creditable),
        },
        "hand_decidable": {
            "_what": "creditable AND not an arbitrary gold label. The honest ceiling.",
            "cases": len(hand_decidable),
            "above_band": len(above(hand_decidable)),
            "r1_delta": round(len(hand_decidable) / n, 4),
            "r1_delta_above_band": round(len(above(hand_decidable)) / n, 4),
            "query_ids": sorted(hand_decidable),
            "query_ids_above_band": sorted(above(hand_decidable), key=lambda q: -gap_of[q]),
        },
        "notes": {q: {"contains": c, "arbitrary": a, "note": note}
                  for q, (c, a, note) in HAND.items()},
    }

    # -- the hand-verification dump ----------------------------------------------------------------
    lines = [
        "# H-D: all 26 POSITIVE head pairs, full text, for hand verification",
        "",
        "The machine count in `head-decidability.json` is the LOOSE/STRICT rule from",
        "`tools/answer_containment.py`. This file is what it is checked against: every POSITIVE",
        "pair, question, gold answer, rank-1 text (the non-gold winner) and rank-2 text (the gold).",
        "Hand verdict: does the RANK-1 turn state the gold answer?",
        "",
    ]
    for r in sorted(pos, key=lambda r: -(r["abs_rerank_gap"] or 0)):
        lines += [
            f"## {r['query_id']}   [{r['category']}]   |gap| {r['abs_rerank_gap']:.4f}   "
            f"J {r['jaccard']:.3f}   cos {r['cosine']:.3f}",
            "",
            f"* **Q** {r['question']}",
            f"* **A** {r['gold_answer']}",
            f"* machine: strict={r['rank1']['strict']}  loose={r['rank1']['loose']}  "
            f"answer content tokens {r['rank1']['answer_content_tokens']}",
            "",
            "**RANK 1 (not flagged gold):**",
            "",
            "> " + (r["rank1_text"] or "").replace("\n", "\n> "),
            "",
            "**RANK 2 (flagged gold):**",
            "",
            "> " + (r["rank2_text"] or "").replace("\n", "\n> "),
            "",
        ]
    DUMP_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {DUMP_PATH.relative_to(REPO)}  (hand-verification dump, all 26 POSITIVE pairs)")

    artifact = {
        "_what": "H-D: is the +26 POSITIVE-pair ceiling real? Answer containment at the head, its "
                 "control on solved cases, and rank1<->rank2 near-duplicate structure.",
        "_split": "fit",
        "_config": "ms-marco-MiniLM-L-2-v2-ft-session-j, depth 10 (shipped)",
        "_no_llm": "String/lexical matching and jina-embeddings-v2-small-en only. No generative "
                   "model is used anywhere in this measurement.",
        "_rule": "containment is answer_containment's rule, imported: strict = normalised answer as "
                 "a contiguous whole-token run; loose = strict OR all answer content tokens present "
                 "order-free; min2 = restricted to answers with >= 2 content tokens.",
        "gate": {
            "reconstructed_fit_r1": r1,
            "negative_control": ctl,
            "cross_check_rank1_against_answer_containment_json": xc,
        },
        "population": {k: len(v) for k, v in groups.items()} | {"pairs": n},
        "i_containment_positive_rank1": t_pos,
        "ii_control": {
            "NEGATIVE_rank2": t_neg,
            "AMBIGUOUS_rank1": t_amb1,
            "AMBIGUOUS_rank2": t_amb2,
            "AMBIGUOUS_both_gold_rank1": t_ab1,
            "AMBIGUOUS_both_gold_rank2": t_ab2,
            "AMBIGUOUS_neither_gold_rank1": t_an1,
            "AMBIGUOUS_neither_gold_rank2": t_an2,
            "_why": "In a POSITIVE pair the non-gold member is rank 1; in a NEGATIVE pair it is "
                    "rank 2. Comparing those two is apples to apples. If they match, containment "
                    "is a corpus property and finding (i) is void.",
        },
        "iii_near_duplicate_structure": struct,
        "machine_count_vs_hand_count": hand_block,
        "corrected_ceiling": {
            "band": BAND,
            "denominator_queries": n,
            "claimed": {
                "cases": len(pos),
                "above_band": len(a_all),
                "below_band": len(b_all),
                "r1_delta": round(len(pos) / n, 4),
                "r1_delta_above_band": round(len(a_all) / n, 4),
            },
            "corrected_loose": {
                "cases": len(creditable),
                "above_band": len(a_cr),
                "below_band": len(b_cr),
                "r1_delta": round(len(creditable) / n, 4),
                "r1_delta_above_band": round(len(a_cr) / n, 4),
                "query_ids": [r["query_id"] for r in creditable],
                "query_ids_above_band": [r["query_id"] for r in a_cr],
            },
            "corrected_strict": {
                "cases": len(creditable_strict),
                "above_band": len(a_cs),
                "below_band": len(b_cs),
                "r1_delta": round(len(creditable_strict) / n, 4),
                "r1_delta_above_band": round(len(a_cs) / n, 4),
                "query_ids": [r["query_id"] for r in creditable_strict],
            },
        },
        "positive_pairs": [
            {k: v for k, v in r.items() if k not in ("rank1_text", "rank2_text")}
            | {"rank1_text": r["rank1_text"], "rank2_text": r["rank2_text"]}
            for r in pos
        ],
        "rows": [{k: v for k, v in r.items() if k not in ("rank1_text", "rank2_text")}
                 for r in rows],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
