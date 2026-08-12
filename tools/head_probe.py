"""The head minimal-pair probe set: RESEARCH.md §1, built as an instrument and nothing else.

`tools/reach_head_r1_confidence.py` measured 18 query-time features and found that the three with
BETTER AUC than the incumbent margin were all WORSE at the head:

    margin      AUC 0.6677   precision@10% 0.9130   <- incumbent
    margin_1_3  AUC 0.7137   precision@10% 0.8696
    softmax_p1  AUC 0.7134   precision@10% 0.8696
    top1_score  AUC 0.7008   precision@10% 0.8696

Overall discrimination and head discrimination are different quantities on this corpus. So a
tie-break feature fitted on AUC is fitted on a proxy that moves independently of the property being
bought, which is the failure family this project keeps a ledger of. **This module is the non-proxy
instrument: every feature is fit on the rank-1-vs-rank-2 distribution and scored on FLIPS.**

    python tools/head_probe.py
    -> runs/session-m0c-m/head-probe.json

**Fit split only.** Held-out is the split that has to judge whatever this suggests; a feature that
scores well HERE has been selected on fit, at a threshold chosen on fit, and still needs a held-out
read before it means anything.

## The population and the three labels

One pair per fit query -- (rank 1, rank 2) under the SHIPPED five-level ranking key. 229 pairs.

  * **POSITIVE**  rank 2 is gold and rank 1 is not. A flip FIXES the case: +1 R@1.
  * **NEGATIVE**  rank 1 is gold and rank 2 is not. A flip BREAKS the case: -1 R@1.
  * **AMBIGUOUS** both gold, or neither. A flip changes R@1 by 0 -- but it is still emitted and
    still counted, because a feature that fires overwhelmingly on the ambiguous set is telling you
    it is not measuring the decision.

FLIPS GAINED and FLIPS LOST are the two numbers. Net R@1 delta is (gained - lost) / 229. Nothing
else in this file is a headline.

## Reuse, not re-implementation

The ranking key is `sweep_reranker_frontier.shipped_order`; the pools are
`reach_pools.load_pools`; the per-candidate dump is `failure_forensics.describe` and its role table;
the cue-only order and the content-word tokenizer are `correct_case_control`'s. A second
implementation of the ranking key has at least four ways to be subtly wrong and every one of them
yields a plausible number, which is why the gate below exists and why nothing is restated here.

## The gate, and its negative control

The reconstruction must reproduce the published fit R@1 of **0.7555** exactly or the module refuses
before writing anything. `--self-check` proves the gate can refuse: it re-runs the gate against the
CUE-ONLY order (the same key with the cross-encoder level removed), which is a real ranking this
system produces and which does NOT score 0.7555. A gate that has never refused is a gate nobody has
tested.

A second gate cross-checks the labelling against two files this module cannot write:
`failures.json`'s `gold_at_rank_2` must equal the POSITIVE count, and `control.json`'s
`strict_successes_competitor_not_gold` must equal the NEGATIVE count. Both are the same population
arrived at by a different code path.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from correct_case_control import content_words, cue_only_order  # noqa: E402
from failure_forensics import SLATE_DEPTH, describe, turn_roles  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
OUT_PATH = OUT_DIR / "head-probe.json"
FAILURES_PATH = OUT_DIR / "failures.json"
CONTROL_PATH = OUT_DIR / "control.json"

POSITIVE, NEGATIVE, AMBIGUOUS = "POSITIVE", "NEGATIVE", "AMBIGUOUS"

# The flip budgets the printed curve is condensed to. The JSON carries every distinct threshold.
PRINT_BUDGETS = (1, 3, 5, 10, 15, 20, 30, 50, 75, 100, 150, 229)


# -- the gate ------------------------------------------------------------------------------------


def gate(r1: float, what: str) -> None:
    """Reproduce the published fit R@1 or refuse. Copied in shape from `failure_forensics.main`."""
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING ({what}). Reconstructed fit R@1 is {r1}; published is {CONTROL_R1}. The "
            "probe set would be describing head decisions the product does not make."
        )


def cross_check(counts) -> dict:
    """Gate 2. The label counts must agree with two files this module cannot write.

    `failures.json`'s `gold_at_rank_2` IS the POSITIVE set by definition -- a fit failure whose gold
    sits at rank 2. `control.json`'s `strict_successes_competitor_not_gold` IS the NEGATIVE set --
    a correct case whose rank-2 runner-up is not itself gold. If either disagrees, the labelling
    here is a second, quietly different definition of the same population.
    """
    for path in (FAILURES_PATH, CONTROL_PATH):
        if not path.exists():
            raise SystemExit(
                f"REFUSING. {path} does not exist. Run tools/failure_forensics.py and "
                "tools/correct_case_control.py first -- without them the labelling is unchecked."
            )
    fail = json.loads(FAILURES_PATH.read_text(encoding="utf-8"))["summary"]
    ctrl = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))["summary"]
    checks = {
        "POSITIVE == failures.json gold_at_rank_2": (counts[POSITIVE], fail["gold_at_rank_2"]),
        "NEGATIVE == control.json strict_successes_competitor_not_gold": (
            counts[NEGATIVE],
            ctrl["strict_successes_competitor_not_gold"],
        ),
        "POSITIVE + NEGATIVE + AMBIGUOUS == queries": (
            counts[POSITIVE] + counts[NEGATIVE] + counts[AMBIGUOUS],
            fail["queries"],
        ),
    }
    bad = [f"{k}: here {a} vs there {b}" for k, (a, b) in checks.items() if a != b]
    if bad:
        raise SystemExit("REFUSING. Label counts disagree with the committed records:\n  "
                         + "\n  ".join(bad))
    return {k: {"here": a, "there": b} for k, (a, b) in checks.items()}


# -- IDF, built over the fit candidate turns only --------------------------------------------------


def build_idf(pools, texts_all) -> tuple[dict[str, float], float, int]:
    """Document frequency over every fit-split candidate turn. One turn = one document.

    Fit only, deliberately: the held-out split is not read here, not even for a word count.
    """
    df: Counter = Counter()
    n_docs = 0
    for qid, pool in pools.items():
        texts = texts_all.get(qid, {})
        for c in pool.candidates:
            text = texts.get(c.turn_id)
            if text is None:
                continue
            n_docs += 1
            for w in content_words(text):
                df[w] += 1
    idf = {w: math.log((n_docs + 1) / (d + 1)) + 1.0 for w, d in df.items()}
    return idf, math.log(n_docs + 1) + 1.0, n_docs


def non_query_mass(text: str, question: str, idf: dict[str, float], default: float) -> dict:
    """RESEARCH.md §10: the IDF-weighted mass of the candidate NOT licensed by the question.

    A question-echo turn is nearly fully predictable from the question, so its unlicensed fraction
    is low. An answer-bearing turn necessarily carries information the question did not supply.

    This is NOT the refuted length penalty: `norm` is a FRACTION, invariant to how long the turn is.
    """
    toks = content_words(text)
    qw = content_words(question or "")
    total = sum(idf.get(w, default) for w in toks)
    unlicensed = sum(idf.get(w, default) for w in toks if w not in qw)
    return {
        "non_query_mass_idf": round(unlicensed, 4),
        "total_mass_idf": round(total, 4),
        "non_query_mass_norm": round(unlicensed / total, 4) if total else None,
        "n_content_words": len(toks),
        "q_overlap": len(qw & toks),
    }


# -- the pairs -------------------------------------------------------------------------------------


def build_pairs(pools, texts_all, roles_all, questions, answers, idf, default_idf) -> list[dict]:
    """One record per query: the (rank 1, rank 2) pair, both members fully described."""
    pairs = []
    for qid, pool in pools.items():
        order, pre = shipped_order(pool), cue_only_order(pool)
        if len(order) < 2:
            raise SystemExit(f"REFUSING. {qid} has {len(order)} candidates; a head pair needs 2.")
        texts, roles = texts_all.get(qid, {}), roles_all.get(qid, {})
        rank_final = {int(v): r + 1 for r, v in enumerate(order)}
        rank_pre = {int(v): r + 1 for r, v in enumerate(pre)}
        slate = {int(v) for v in pre[:SLATE_DEPTH]}

        i1, i2 = int(order[0]), int(order[1])
        a = describe(pool, i1, texts, roles, rank_pre[i1], rank_final[i1])
        b = describe(pool, i2, texts, roles, rank_pre[i2], rank_final[i2])
        gold1, gold2 = bool(pool.gold[i1]), bool(pool.gold[i2])

        if gold2 and not gold1:
            label = POSITIVE
        elif gold1 and not gold2:
            label = NEGATIVE
        else:
            label = AMBIGUOUS

        question = questions.get(qid) or ""
        for member in (a, b):
            member.update(non_query_mass(member["text"], question, idf, default_idf))
            member["in_slate"] = (i1 if member is a else i2) in slate

        q_words = content_words(question)
        t1, t2 = content_words(a["text"]), content_words(b["text"])
        gold_idx = [i for i, g in enumerate(pool.gold) if g]
        same_session = (a["session_id"] is not None) and (a["session_id"] == b["session_id"])

        pairs.append(
            {
                "query_id": qid,
                "category": pool.category,
                "question": question,
                "gold_answer": answers.get(qid),
                "label": label,
                "rank1_is_gold": gold1,
                "rank2_is_gold": gold2,
                "n_gold_turns": len(gold_idx),
                "n_candidates": len(pool.candidates),
                "all_gold_ranks_final": sorted(rank_final[i] for i in gold_idx),
                # -- the derived contrast, rank1 relative to rank2 ------------------------------
                "rerank_gap": (
                    round(a["rerank_score"] - b["rerank_score"], 6)
                    if a["reranked"] and b["reranked"]
                    else None
                ),
                "length_ratio_r1_over_r2": (
                    round(a["words"] / b["words"], 4) if b["words"] else None
                ),
                "ln_words_ratio": (
                    round(math.log(max(a["words"], 1)) - math.log(max(b["words"], 1)), 4)
                ),
                "same_session": same_session,
                "turn_gap": (
                    a["turn_index"] - b["turn_index"]
                    if same_session and a["turn_index"] is not None and b["turn_index"] is not None
                    else None
                ),
                "same_role": a["role"] == b["role"],
                "cue_margin_gap": round(a["cue_margin"] - b["cue_margin"], 6),
                "cue_z_gap": round(a["cue_z"] - b["cue_z"], 6),
                "pre_rerank_rank_gap": a["rank_pre_rerank"] - b["rank_pre_rerank"],
                # question-overlap counts, both directions and the exclusive ("echo") form
                "q_content_words": len(q_words),
                "q_overlap_r1": len(q_words & t1),
                "q_overlap_r2": len(q_words & t2),
                "q_echo_r1_not_r2": len((q_words & t1) - t2),
                "q_echo_r2_not_r1": len((q_words & t2) - t1),
                "non_query_mass_norm_gap": (
                    round(a["non_query_mass_norm"] - b["non_query_mass_norm"], 6)
                    if a["non_query_mass_norm"] is not None and b["non_query_mass_norm"] is not None
                    else None
                ),
                "rank1": a,
                "rank2": b,
            }
        )
    return pairs


# -- the seeded features ---------------------------------------------------------------------------
#
# EVERY feature is oriented so that HIGHER MEANS FLIP -- promote rank 2 over rank 1. The orientation
# is the hypothesis, and the negative control below is what stops an orientation from being free.
# `None` means undefined on this pair; an undefined pair is never flipped and is counted separately.


def f_rerank_gap(p):
    """Small logit gap -> flip. The incumbent margin, read as a tie-break instead of a selector."""
    g = p["rerank_gap"]
    return None if g is None else -g


def f_ln_words_ratio(p):
    """rank 1 much longer than rank 2 -> flip. `winner_longer_than_gold` fires in 31 of 56."""
    return p["ln_words_ratio"]


def f_cue_margin(p):
    """rank 2 had the stronger cue margin -> flip."""
    return -p["cue_margin_gap"]


def f_cue_z(p):
    """rank 2 had the stronger winning-cue z -> flip."""
    return -p["cue_z_gap"]


def f_pre_rerank_rank(p):
    """The cross-encoder promoted rank 1 over a candidate the cues preferred -> flip it back."""
    return float(p["pre_rerank_rank_gap"])


def f_question_echo(p):
    """rank 1 carries question content-words rank 2 lacks -> it is echoing the question -> flip.

    The feature form of the measured statistic: >=2 such words in 41% of failures vs 16% of solved.
    """
    return float(p["q_echo_r1_not_r2"] - p["q_echo_r2_not_r1"])


def f_non_query_mass(p):
    """RESEARCH.md §10. rank 2 carries more IDF mass the question did not supply -> flip."""
    g = p["non_query_mass_norm_gap"]
    return None if g is None else -g


FEATURES = {
    "rerank_gap_closeness": ("-(logit1 - logit2): a small head gap flips", f_rerank_gap),
    "ln_words_ratio": ("ln(words1) - ln(words2): rank 1 being longer flips", f_ln_words_ratio),
    "cue_margin": ("cue_margin2 - cue_margin1", f_cue_margin),
    "cue_z": ("cue_z2 - cue_z1", f_cue_z),
    "pre_rerank_rank": ("pre-rerank rank of rank1 minus that of rank2", f_pre_rerank_rank),
    "question_echo": (
        "(question content-words in rank1 absent from rank2) minus the reverse",
        f_question_echo,
    ),
    "non_query_mass": (
        "RESEARCH.md sec.10: normalised IDF mass unlicensed by the question, rank2 minus rank1",
        f_non_query_mass,
    ),
}


# -- the harness -----------------------------------------------------------------------------------


def score_feature(pairs, fn, n_queries: int) -> dict:
    """FLIPS GAINED and FLIPS LOST as a function of the decision threshold.

    `fn(pair)` is flipped when `fn(pair) >= tau`. The curve walks every distinct value of the
    feature, so the operating point is visible rather than assumed. `best` is the tau maximising net
    -- and it is SELECTED ON FIT, which is why `_caveat` travels with it in the artifact.
    """
    vals = []
    undefined = 0
    for p in pairs:
        v = fn(p)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            undefined += 1
            continue
        vals.append((float(v), p["label"]))

    vals.sort(key=lambda t: -t[0])
    rows, gained = [], 0
    lost = ambiguous = 0
    i = 0
    while i < len(vals):
        tau = vals[i][0]
        j = i
        while j < len(vals) and vals[j][0] == tau:  # take the whole tie block: `>= tau`
            lab = vals[j][1]
            gained += lab == POSITIVE
            lost += lab == NEGATIVE
            ambiguous += lab == AMBIGUOUS
            j += 1
        rows.append(
            {
                "tau": round(tau, 6),
                "n_flipped": j,
                "flips_gained": gained,
                "flips_lost": lost,
                "flips_ambiguous": ambiguous,
                "net_cases": gained - lost,
                "net_r1_delta": round((gained - lost) / n_queries, 4),
            }
        )
        i = j

    # Fewest flips wins a tie: a rule that touches less of the system for the same net is the one
    # to prefer, and it is also the one less likely to be an artifact of the fit split.
    best = max(rows, key=lambda r: (r["net_cases"], -r["n_flipped"])) if rows else None
    return {
        "n_defined": len(vals),
        "n_undefined": undefined,
        "curve": rows,
        "best": best,
        "flip_everything": rows[-1] if rows else None,
    }


def print_curve(name: str, res: dict, budgets=PRINT_BUDGETS) -> None:
    rows = res["curve"]
    if not rows:
        print(f"  {name}: no defined values")
        return
    picked, seen = [], set()
    for b in budgets:
        r = min(rows, key=lambda r: (abs(r["n_flipped"] - b), r["n_flipped"]))
        if r["n_flipped"] not in seen:
            seen.add(r["n_flipped"])
            picked.append(r)
    print(f"  {'tau':>12} {'flips':>6} {'GAINED':>7} {'LOST':>5} {'amb':>5} {'net':>5} {'dR@1':>8}")
    for r in picked:
        print(
            f"  {r['tau']:>12.4f} {r['n_flipped']:>6d} {r['flips_gained']:>7d} "
            f"{r['flips_lost']:>5d} {r['flips_ambiguous']:>5d} {r['net_cases']:>5d} "
            f"{r['net_r1_delta']:>+8.4f}"
        )


def evaluate(pairs, name: str, fn, n_queries: int) -> dict:
    """The feature, its sign-inverted negative control, and the verdict that compares them.

    A feature whose inverted twin scores as well is measuring nothing -- the threshold search alone
    can manufacture a positive net from noise, in either direction, and that is exactly what the
    control is for.
    """
    fwd = score_feature(pairs, fn, n_queries)
    inv = score_feature(pairs, lambda p: (None if fn(p) is None else -fn(p)), n_queries)

    # Matched-budget read: at the forward feature's own operating point, what does the inverted
    # feature score using the SAME number of flips? A best-vs-best comparison lets the control win
    # on flip count alone.
    matched = None
    if fwd["best"] is not None and inv["curve"]:
        k = fwd["best"]["n_flipped"]
        matched = min(inv["curve"], key=lambda r: (abs(r["n_flipped"] - k), r["n_flipped"]))

    fb = fwd["best"]["net_cases"] if fwd["best"] else 0
    ib = inv["best"]["net_cases"] if inv["best"] else 0
    return {
        "feature": name,
        "description": FEATURES[name][0],
        "forward": fwd,
        "negative_control_sign_inverted": inv,
        "negative_control_at_matched_budget": matched,
        "verdict": {
            "beats_zero_net": bool(fb > 0),
            "best_net_cases": fb,
            "best_net_r1_delta": fwd["best"]["net_r1_delta"] if fwd["best"] else 0.0,
            "inverted_best_net_cases": ib,
            "separation_from_control": fb - ib,
            "_caveat": "best tau is chosen on fit, on the same 229 pairs the feature is scored on. "
                       "A positive net here is a design signal, NEVER a result. It needs a "
                       "held-out read at a FIXED tau before it is evidence of anything.",
        },
    }


# -- assembly ---------------------------------------------------------------------------------------


def build():
    pools, _stats = load_pools(FIT_POOLS)
    texts_all, roles_all = turn_texts(), turn_roles()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    answers = {c.query_id: c.gold_answer for c in corpus.cases}
    questions = {c.query_id: c.question for c in corpus.cases}

    hits = sum(int(pool.gold[shipped_order(pool)[0]]) for pool in pools.values())
    r1 = round(hits / len(pools), 4)
    gate(r1, "shipped order")
    print(f"gate: fit R@1 {r1} == published {CONTROL_R1}  ({len(pools)} queries)")

    idf, default_idf, n_docs = build_idf(pools, texts_all)
    print(f"idf:  {len(idf)} content words over {n_docs} fit candidate turns (fit split only)")

    pairs = build_pairs(pools, texts_all, roles_all, questions, answers, idf, default_idf)
    return pools, pairs, r1


def self_check(pools) -> dict:
    """The gate's NEGATIVE CONTROL: it must refuse a ranking that is not the shipped one.

    The cue-only order is the shipped key with level 2 (the cross-encoder) removed -- a ranking this
    system genuinely produces, not a synthetic perturbation. If the gate accepts it, the gate is not
    reading what it claims to read.
    """
    hits = sum(int(pool.gold[cue_only_order(pool)[0]]) for pool in pools.values())
    r1 = round(hits / len(pools), 4)
    try:
        gate(r1, "cue-only order (negative control)")
    except SystemExit as exc:
        return {"refused": True, "cue_only_r1": r1, "message": str(exc)}
    return {"refused": False, "cue_only_r1": r1, "message": None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--self-check", action="store_true",
                    help="run the gate's negative control and exit without writing")
    args = ap.parse_args()

    pools, pairs, r1 = build()
    n = len(pairs)

    control = self_check(pools)
    print("\n" + "=" * 92)
    print("GATE NEGATIVE CONTROL -- can the gate refuse?")
    print("=" * 92)
    print(f"  cue-only order (level 2 removed) reconstructs fit R@1 {control['cue_only_r1']}")
    print(f"  gate refused: {control['refused']}")
    if control["message"]:
        print(f"    {control['message']}")
    if not control["refused"]:
        raise SystemExit(
            "REFUSING. The gate accepted the cue-only order, so it does not discriminate the "
            "shipped ranking and it is not evidence about anything."
        )
    if args.self_check:
        return 0

    counts = Counter(p["label"] for p in pairs)
    checks = cross_check(counts)
    print("\ngate 2: label counts agree with failures.json and control.json")
    for k, v in checks.items():
        print(f"  {k:62s} {v['here']} == {v['there']}")
    by_cat = {
        c: Counter(p["label"] for p in pairs if p["category"] == c)
        for c in sorted({p["category"] for p in pairs})
    }

    print("\n" + "=" * 92)
    print("THE POPULATION -- one (rank 1, rank 2) pair per fit query, shipped ranking")
    print("=" * 92)
    print(f"  pairs                                    {n}")
    print(f"  POSITIVE  (rank2 gold, rank1 not)  FLIP FIXES     {counts[POSITIVE]}")
    print(f"  NEGATIVE  (rank1 gold, rank2 not)  FLIP BREAKS    {counts[NEGATIVE]}")
    print(f"  AMBIGUOUS (both gold, or neither)  FLIP IS A NOOP {counts[AMBIGUOUS]}")
    print(f"\n  maximum reachable by ANY rank-1/rank-2 tie-break: "
          f"+{counts[POSITIVE]} cases = +{counts[POSITIVE] / n:.4f} R@1")
    print(f"  worst reachable:                                  "
          f"-{counts[NEGATIVE]} cases = -{counts[NEGATIVE] / n:.4f} R@1")
    print(f"\n  {'category':30s} {'POS':>5} {'NEG':>5} {'AMB':>5}")
    for c, cc in by_cat.items():
        print(f"  {c:30s} {cc[POSITIVE]:>5d} {cc[NEGATIVE]:>5d} {cc[AMBIGUOUS]:>5d}")

    print("\n" + "=" * 92)
    print("SEEDED FEATURES -- fit on the head pair distribution, scored on FLIPS")
    print("=" * 92)
    results = []
    for name, (_desc, fn) in FEATURES.items():
        res = evaluate(pairs, name, fn, n)
        results.append(res)
        print(f"\n-- {name}: {FEATURES[name][0]}")
        print(f"   defined on {res['forward']['n_defined']}/{n} pairs "
              f"({res['forward']['n_undefined']} undefined)")
        print_curve(name, res["forward"])
        b, ib = res["forward"]["best"], res["negative_control_sign_inverted"]["best"]
        m = res["negative_control_at_matched_budget"]
        print(f"   BEST      net {b['net_cases']:+d} cases ({b['flips_gained']} gained, "
              f"{b['flips_lost']} lost) at tau {b['tau']:.4f}, {b['n_flipped']} flips, "
              f"dR@1 {b['net_r1_delta']:+.4f}")
        print(f"   CONTROL   sign inverted: best net {ib['net_cases']:+d} at {ib['n_flipped']} "
              f"flips; at the SAME {b['n_flipped']}-flip budget net {m['net_cases']:+d}")
        print(f"   VERDICT   {'BEATS ZERO NET' if b['net_cases'] > 0 else 'does not beat zero net'}"
              f"  (separation from control {b['net_cases'] - ib['net_cases']:+d})")

    print("\n" + "=" * 92)
    print("SUMMARY -- best net cases per feature, fit split, threshold selected on fit")
    print("=" * 92)
    print(f"  {'feature':24s} {'gained':>7} {'lost':>5} {'net':>5} {'dR@1':>8} {'inv net':>8}")
    for res in sorted(results, key=lambda r: -r["verdict"]["best_net_cases"]):
        b = res["forward"]["best"]
        print(f"  {res['feature']:24s} {b['flips_gained']:>7d} {b['flips_lost']:>5d} "
              f"{b['net_cases']:>5d} {b['net_r1_delta']:>+8.4f} "
              f"{res['verdict']['inverted_best_net_cases']:>+8d}")
    winners = [r["feature"] for r in results if r["verdict"]["beats_zero_net"]]
    print(f"\n  beat zero net on fit: {winners if winners else 'NONE'}")
    print("  Every one of those is a fit-selected threshold on the same 229 pairs. It is a design "
          "signal and not a result until a held-out read at a fixed tau says otherwise.")

    artifact = {
        "_what": "the head minimal-pair probe set -- RESEARCH.md §1. One (rank 1, rank 2) pair per "
                 "fit query under the shipped ranking, labelled by what a flip would do to R@1, "
                 "plus the seeded features' flip tables.",
        "_split": "fit",
        "_config": "ms-marco-MiniLM-L-2-v2-ft-session-j, depth 10 (shipped)",
        "_instrument_only": "Nothing here ships. No artifact is minted, no gate refit, no held-out "
                            "read spent.",
        "_methodology": "RESEARCH.md §1: a tie-break feature is fit on the rank-1-vs-rank-2 "
                        "distribution and scored on FLIPS, never fit globally on AUC. Three "
                        "features with better AUC than the incumbent margin were all worse at the "
                        "head (reach-r1-confidence.json), which is what makes AUC a proxy here.",
        "gate": {
            "published_fit_r1": CONTROL_R1,
            "reconstructed_fit_r1": r1,
            "negative_control": {
                "what": "the cue-only order -- the shipped five-level key with the cross-encoder "
                        "level removed. A real ranking this system produces.",
                **control,
            },
            "cross_check_against_committed_records": checks,
        },
        "population": {
            "pairs": n,
            "POSITIVE": counts[POSITIVE],
            "NEGATIVE": counts[NEGATIVE],
            "AMBIGUOUS": counts[AMBIGUOUS],
            "max_reachable_cases": counts[POSITIVE],
            "max_reachable_r1_delta": round(counts[POSITIVE] / n, 4),
            "worst_reachable_cases": -counts[NEGATIVE],
            "by_category": {c: dict(cc) for c, cc in by_cat.items()},
            "_labels": {
                "POSITIVE": "rank 2 is gold and rank 1 is not -- a flip FIXES the case",
                "NEGATIVE": "rank 1 is gold and rank 2 is not -- a flip BREAKS the case",
                "AMBIGUOUS": "both gold or neither -- a flip changes R@1 by 0",
            },
        },
        "features": results,
        "pairs": pairs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
