"""The CORRECT-case control: the other side of `failure_forensics.py`.

`tools/failure_forensics.py` emits rich features for the 56 fit-split FAILURES and nothing else.
Every threshold anyone derives from it is therefore ONE-SIDED. A rule that fires on 40% of failures
may fire on 38% of successes, in which case it is noise -- and as written we cannot tell.

This is the mirror. For the 173 CORRECT fit cases it emits the same feature set, so any hypothesis
can be stated as a predicate and tested as failures-vs-successes with a Fisher exact p.

    python tools/correct_case_control.py            # emit  -> runs/session-m0c-m/control.json
    python tools/correct_case_control.py compare    # print the two-sided table, write nothing

**The contrast, and why it is the analogue.** In a failure the interesting pair is *winner vs gold*:
the thing that beat gold, against gold. In a correct case rank 1 IS gold, so the analogous pair is
**rank 1 (gold) vs rank 2 (the runner-up that did not beat it)**. Both are emitted under one schema:
`gold` and `competitor`. Every derived field -- `same_session`, `turn_gap`, `same_role`,
`length_ratio`, `rerank_gap`, `cross_session` -- is computed identically on both sides, by the same
code path, so a difference between the two populations cannot be an artifact of two implementations.

**Where a correct case is NOT a clean analogue, stated rather than hidden.** When a case has several
gold turns, rank 2 may itself be gold, so the "competitor" is not a distractor at all. That subset is
flagged (`competitor_is_gold`) and every comparison is reported TWICE: over all 173, and over the
strict subset where the competitor is not gold. Failures need no such restriction -- their rank-1 is
non-gold by definition.

**Reuse, not re-implementation.** The five-level shipped ranking key comes from
`sweep_reranker_frontier.shipped_order`; the pools from `reach_pools.load_pools`; the per-candidate
feature dump and the role table from `failure_forensics.describe` / `.turn_roles`. The one thing that
is restated here is the *cue-only* order (the pre-rerank rank), because in `failure_forensics.py` it
is an inline expression inside `main()` and that file is a committed record which is not refactored.
**That duplication is gated:** the 56 failure records built here are checked field-by-field against
`runs/session-m0c-m/failures.json`, including `gold_rank_pre_rerank`. If the restated key drifts, the
script refuses.

**Gates, all three, before anything is written.**
  1. the reconstruction reproduces the published fit R@1 of 0.7555 exactly
  2. 173 correct + 56 failures == 229 queries
  3. the 56 failure records agree with `failures.json` on every shared field
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import numpy as np  # noqa: E402
from scipy.stats import fisher_exact  # noqa: E402

from tokenizers import Tokenizer  # noqa: E402

from failure_forensics import SLATE_DEPTH, describe, turn_roles  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
OUT_PATH = OUT_DIR / "control.json"
FAILURES_PATH = OUT_DIR / "failures.json"

# Function words are stripped before any "content word" test. Kept deliberately short and generic:
# a stoplist tuned by looking at which failures it rescues is the thing this whole module exists to
# prevent.
STOP = frozenset(
    """
    a an the and or but if then than that this these those there here of in on at to for from by
    with without about into over under again further once is are was were be been being am do does
    did doing have has had having i me my myself we our ours you your yours he him his she her it
    its they them their what which who whom when where why how all any both each few more most
    other some such no nor not only own same so too very can will just should now would could may
    might must shall im ive id ill dont doesnt didnt cant wont hes shes theyre youre were thats
    as up down out off s t d ll m o re ve y
    """.split()
)

WORD = re.compile(r"[a-z0-9]+")

# The SHIPPED tokenizer and the SHIPPED sequence length. Truncation is the subject of plan §3a, and
# a whitespace-word proxy for "over the 256 wordpiece budget" is a measurement of word counts read
# as a property of the tokenizer. Both are emitted -- `gold_truncated_wordpiece` is the real thing,
# `gold_truncated_words_gt_190` is the proxy -- so the two can be seen to agree or not.
MAX_SEQ = 256
TOKENIZER_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
_TOK = Tokenizer.from_file(str(TOKENIZER_DIR / "tokenizer.json"))
_TOK.no_truncation()
_TOK.no_padding()


def pair_wordpieces(question: str, text: str) -> int:
    """`[CLS] q [SEP] t [SEP]` length, untruncated, via the tokenizer's own pair template.

    `> MAX_SEQ` means the shipped scorer never saw the tail of this turn.
    """
    return len(_TOK.encode(question or "", text or "").ids)


def content_words(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, function words and 1-2 character tokens dropped."""
    return {w for w in WORD.findall((text or "").lower()) if len(w) > 2 and w not in STOP}


def cue_only_order(pool) -> np.ndarray:
    """The ranking with level 2 (the cross-encoder) removed -- i.e. `rank_pre_rerank`.

    RESTATED from the inline expression in `failure_forensics.main()`. That file is a committed
    record and is not edited, so this is the one duplicated key in the module. `check_against_
    failures()` is what stops the duplication from becoming a second, quietly different definition.
    """
    keys = [
        (0 if c.survived_pruning else 1, -c.score, -c.margin, c.memory_id or "")
        for c in pool.candidates
    ]
    return np.array(sorted(range(len(pool.candidates)), key=lambda i: keys[i]), dtype=np.int64)


def build_record(qid, pool, texts, roles, question, answer, order, pre):
    """One case, correct or failed, in a single schema.

    `gold` is the best-placed gold turn (in a correct case, that is rank 1). `competitor` is the
    turn it is being contrasted against: the rank-1 winner in a failure, the rank-2 runner-up in a
    correct case. Both go through `failure_forensics.describe`.
    """
    rank_final = {int(v): r + 1 for r, v in enumerate(order)}
    rank_pre = {int(v): r + 1 for r, v in enumerate(pre)}
    slate = {int(v) for v in pre[:SLATE_DEPTH]}

    gold_idx = [i for i, g in enumerate(pool.gold) if g]
    top = int(order[0])
    correct = bool(pool.gold[top])

    best_gold = min(gold_idx, key=lambda i: rank_final[i])
    g = describe(pool, best_gold, texts, roles, rank_pre[best_gold], rank_final[best_gold])

    if correct:
        # The runner-up. `None` only if the pool holds a single candidate.
        comp_idx = int(order[1]) if len(order) > 1 else None
    else:
        comp_idx = top

    w = (
        describe(pool, comp_idx, texts, roles, rank_pre[comp_idx], rank_final[comp_idx])
        if comp_idx is not None
        else None
    )

    gold_sids = {pool.candidates[i].sid for i in gold_idx}
    rec = {
        "query_id": qid,
        "category": pool.category,
        "question": question,
        "gold_answer": answer,
        "outcome": "correct" if correct else "failure",
        "n_gold_turns": len(gold_idx),
        "n_candidates": len(pool.candidates),
        "gold_rank_final": g["rank_final"],
        "gold_rank_pre_rerank": g["rank_pre_rerank"],
        "gold_in_slate": best_gold in slate,
        "all_gold_ranks_final": sorted(rank_final[i] for i in gold_idx),
        "has_competitor": w is not None,
        "competitor_is_gold": bool(pool.gold[comp_idx]) if comp_idx is not None else None,
        "gold_pair_wordpieces": pair_wordpieces(question, g["text"]),
        "competitor_pair_wordpieces": pair_wordpieces(question, w["text"]) if w else None,
        "gold": g,
        "competitor": w,
    }

    if w is None:
        rec.update(
            {
                "same_session": None,
                "turn_gap": None,
                "same_role": None,
                "winner_is_longer": None,
                "length_ratio_winner_over_gold": None,
                "rerank_gap": None,
                "cross_session": None,
                "question_echo_words": None,
            }
        )
        return rec

    same_session = (w["session_id"] is not None) and (w["session_id"] == g["session_id"])
    q_words = content_words(question or "")
    echo = (q_words & content_words(w["text"])) - content_words(g["text"])
    rec.update(
        {
            "same_session": same_session,
            "turn_gap": (
                g["turn_index"] - w["turn_index"]
                if same_session and g["turn_index"] is not None and w["turn_index"] is not None
                else None
            ),
            "same_role": w["role"] == g["role"],
            "winner_is_longer": w["words"] > g["words"],
            "length_ratio_winner_over_gold": (
                round(w["words"] / g["words"], 3) if g["words"] else None
            ),
            "rerank_gap": (
                round(w["rerank_score"] - g["rerank_score"], 4)
                if w["reranked"] and g["reranked"]
                else None
            ),
            # "in a session containing no gold at all" -- the Phase 2 `cross_session` hypothesis.
            "cross_session": w["session_id"] not in gold_sids,
            "question_echo_words": sorted(echo),
        }
    )
    return rec


# -- the predicates ------------------------------------------------------------------------------
#
# Each returns True, False, or None for "undefined on this record". `None` is excluded from BOTH
# denominators and the surviving n is reported, so a predicate that is silently undefined on half
# the successes cannot masquerade as a rate over 173.


def _p_question_echo(r):
    e = r["question_echo_words"]
    return None if e is None else len(e) >= 2


def _p_winner_longer(r):
    return r["winner_is_longer"]


def _p_length_ratio(r):
    v = r["length_ratio_winner_over_gold"]
    return None if v is None else v > 1.5


def _p_cross_session(r):
    return r["cross_session"]


def _p_gold_short(r):
    return r["gold"]["words"] <= 35


def _p_gold_truncated_proxy(r):
    # ~190 whitespace words as a stand-in for "over the 256 wordpiece budget". A PROXY, kept only so
    # it can be seen next to the real measurement below.
    return r["gold"]["words"] > 190


def _p_gold_truncated(r):
    # The real thing: the (question, gold) pair exceeds the shipped 256-wordpiece sequence, so the
    # scorer never saw the tail of the gold turn. This is plan §3a's premise.
    return r["gold_pair_wordpieces"] > MAX_SEQ


def _p_competitor_truncated(r):
    # §3a's own stated control: max-over-windows also lets a long DISTRACTOR accumulate, so the
    # competitor's truncation rate has to be read beside the gold's.
    v = r["competitor_pair_wordpieces"]
    return None if v is None else v > MAX_SEQ


def _p_same_session(r):
    return r["same_session"]


def _p_same_role(r):
    return r["same_role"]


PREDICATES = {
    "question_echo": (
        ">=2 question content-words in the competitor and ABSENT from gold",
        _p_question_echo,
    ),
    "winner_longer": ("competitor has more words than gold", _p_winner_longer),
    "length_ratio_gt_1_5": ("competitor/gold word ratio > 1.5", _p_length_ratio),
    "cross_session": ("competitor sits in a haystack session containing no gold", _p_cross_session),
    "gold_words_le_35": ("the gold turn is <= 35 words", _p_gold_short),
    "gold_truncated_words_gt_190": ("PROXY: the gold turn is > 190 whitespace words", _p_gold_truncated_proxy),
    "gold_truncated": (
        "REAL: (question, gold) exceeds 256 wordpieces, so the scorer never saw gold's tail",
        _p_gold_truncated,
    ),
    "competitor_truncated": (
        "the §3a control: (question, competitor) exceeds 256 wordpieces",
        _p_competitor_truncated,
    ),
    "same_session": ("competitor shares gold's haystack session", _p_same_session),
    "same_role": ("competitor shares gold's role", _p_same_role),
}


def rate(records, fn):
    yes = no = 0
    for r in records:
        v = fn(r)
        if v is None:
            continue
        yes += bool(v)
        no += not bool(v)
    return yes, no


def compare(failures, successes, name):
    """Failure rate vs success rate, with counts and a two-sided Fisher exact p."""
    _, fn = PREDICATES[name]
    fy, fnn = rate(failures, fn)
    sy, snn = rate(successes, fn)
    table = [[fy, fnn], [sy, snn]]
    odds, p = fisher_exact(table, alternative="two-sided")
    f_rate = fy / (fy + fnn) if (fy + fnn) else None
    s_rate = sy / (sy + snn) if (sy + snn) else None
    return {
        "predicate": name,
        "description": PREDICATES[name][0],
        "failures": {"yes": fy, "n": fy + fnn, "rate": round(f_rate, 4) if f_rate is not None else None},
        "successes": {"yes": sy, "n": sy + snn, "rate": round(s_rate, 4) if s_rate is not None else None},
        "ratio": (
            round(f_rate / s_rate, 3) if f_rate is not None and s_rate else None
        ),
        "odds_ratio": None if not np.isfinite(odds) else round(float(odds), 3),
        "fisher_p": round(float(p), 6),
        # These predicates are a family tested together on one split. The unadjusted p is what a
        # single pre-registered hypothesis would earn; this is what the family earns.
        "fisher_p_bonferroni": round(min(1.0, float(p) * len(PREDICATES)), 6),
    }


def compare_by_category(failures, successes, name):
    cats = sorted({r["category"] for r in failures} | {r["category"] for r in successes})
    return {
        c: compare(
            [r for r in failures if r["category"] == c],
            [r for r in successes if r["category"] == c],
            name,
        )
        for c in cats
    }


def check_against_failures(failure_records):
    """Gate 3. The 56 failure records built here must agree with the committed `failures.json`.

    This is what makes the restated `cue_only_order` safe: `gold_rank_pre_rerank` is derived from it
    and is checked here against a file this module cannot write.
    """
    if not FAILURES_PATH.exists():
        raise SystemExit(
            f"REFUSING. {FAILURES_PATH} does not exist. Run tools/failure_forensics.py first -- "
            "without it the restated pre-rerank key is unchecked."
        )
    published = {r["query_id"]: r for r in json.loads(FAILURES_PATH.read_text(encoding="utf-8"))["records"]}
    mine = {r["query_id"]: r for r in failure_records}
    if set(published) != set(mine):
        raise SystemExit(
            f"REFUSING. failure set differs from failures.json: "
            f"only-here {sorted(set(mine) - set(published))}, only-there {sorted(set(published) - set(mine))}"
        )
    shared = [
        "category", "n_gold_turns", "n_candidates", "gold_rank_final", "gold_rank_pre_rerank",
        "gold_in_slate", "all_gold_ranks_final", "same_session", "turn_gap", "same_role",
        "winner_is_longer", "length_ratio_winner_over_gold", "rerank_gap",
    ]
    bad = []
    for qid, pub in published.items():
        got = mine[qid]
        for k in shared:
            if got[k] != pub[k]:
                bad.append(f"{qid}.{k}: here {got[k]!r} vs failures.json {pub[k]!r}")
        # `winner` there is `competitor` here, and must be the same turn.
        if got["competitor"]["turn_id"] != pub["winner"]["turn_id"]:
            bad.append(f"{qid}.winner: {got['competitor']['turn_id']} vs {pub['winner']['turn_id']}")
        if got["gold"]["turn_id"] != pub["gold"]["turn_id"]:
            bad.append(f"{qid}.gold: {got['gold']['turn_id']} vs {pub['gold']['turn_id']}")
    if bad:
        raise SystemExit("REFUSING. Disagreement with failures.json:\n  " + "\n  ".join(bad[:20]))
    return len(shared)


def build():
    pools, _stats = load_pools(FIT_POOLS)
    texts_all, roles_all = turn_texts(), turn_roles()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    answers = {c.query_id: c.gold_answer for c in corpus.cases}
    questions = {c.query_id: c.question for c in corpus.cases}

    # -- gate 1: reproduce the shipped ranking -------------------------------------------------
    orders, pres, hits = {}, {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        pres[qid] = cue_only_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING. Reconstructed fit R@1 is {r1}; published is {CONTROL_R1}. The control "
            "would be describing a ranking the product does not produce."
        )
    print(f"gate 1: fit R@1 {r1} == published {CONTROL_R1}  ({len(pools)} queries)")

    records = [
        build_record(
            qid, pool, texts_all.get(qid, {}), roles_all.get(qid, {}),
            questions.get(qid), answers.get(qid), orders[qid], pres[qid],
        )
        for qid, pool in pools.items()
    ]
    successes = [r for r in records if r["outcome"] == "correct"]
    failures = [r for r in records if r["outcome"] == "failure"]

    # -- gate 2: 173 + 56 == 229 ----------------------------------------------------------------
    assert len(successes) + len(failures) == len(pools) == 229, (
        len(successes), len(failures), len(pools)
    )
    if (len(successes), len(failures)) != (173, 56):
        raise SystemExit(
            f"REFUSING. Expected 173 correct / 56 failures, got {len(successes)} / {len(failures)}."
        )
    print(f"gate 2: {len(successes)} correct + {len(failures)} failures == {len(pools)}")

    # -- gate 3: agreement with the committed failures.json --------------------------------------
    nshared = check_against_failures(failures)
    print(f"gate 3: all {len(failures)} failure records agree with failures.json on {nshared} fields")

    return pools, records, successes, failures, r1


def comparisons(failures, successes):
    strict = [r for r in successes if r["competitor_is_gold"] is False]
    return {
        "all_successes": [compare(failures, successes, n) for n in PREDICATES],
        "strict_successes_competitor_not_gold": [compare(failures, strict, n) for n in PREDICATES],
        "by_category_all_successes": {
            n: compare_by_category(failures, successes, n) for n in PREDICATES
        },
        "_strict_n": len(strict),
    }


def _row(c, label_width=28, key="predicate"):
    f, s = c["failures"], c["successes"]
    fr = f"{f['yes']}/{f['n']} = {f['rate']:.3f}" if f["rate"] is not None else f"0/{f['n']} = -"
    sr = f"{s['yes']}/{s['n']} = {s['rate']:.3f}" if s["rate"] is not None else f"0/{s['n']} = -"
    ratio = f"{c['ratio']:.2f}" if c["ratio"] is not None else "-"
    return (
        f"{c[key]:{label_width}s} {fr:>16s} {sr:>16s} {ratio:>7s} "
        f"{c['fisher_p']:>10.5f} {c['fisher_p_bonferroni']:>10.5f}"
    )


def print_table(cmp_block, label, n_fail, n_succ):
    print(f"\n== {label}  (failures n={n_fail}, successes n={n_succ}) ==")
    print(
        f"{'predicate':28s} {'failures':>16s} {'successes':>16s} {'ratio':>7s} "
        f"{'fisher p':>10s} {'bonf p':>10s}"
    )
    for c in cmp_block:
        print(_row(c))


def print_by_category(block, name):
    print(f"\n== per category: {name} -- {PREDICATES[name][0]} ==")
    print(
        f"{'category':28s} {'failures':>16s} {'successes':>16s} {'ratio':>7s} "
        f"{'fisher p':>10s} {'bonf p':>10s}"
    )
    for cat, c in block.items():
        c = dict(c, category=cat)
        print(_row(c, key="category"))


def main(argv) -> int:
    mode = argv[1] if len(argv) > 1 else "emit"
    if mode not in ("emit", "compare"):
        raise SystemExit("usage: correct_case_control.py [emit|compare [predicate ...]]")
    wanted = argv[2:]
    for w in wanted:
        if w not in PREDICATES:
            raise SystemExit(f"unknown predicate {w!r}; known: {', '.join(PREDICATES)}")

    pools, records, successes, failures, r1 = build()
    cmps = comparisons(failures, successes)

    print_table(cmps["all_successes"], "ALL successes (rank-2 competitor, gold or not)",
                len(failures), len(successes))
    print_table(cmps["strict_successes_competitor_not_gold"],
                "STRICT successes (rank-2 is NOT gold)", len(failures), cmps["_strict_n"])

    for w in wanted:
        print_by_category(cmps["by_category_all_successes"][w], w)

    if mode == "compare":
        print("\n(compare mode: nothing written)")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "_what": "fit-split CORRECT-case control -- the mirror of failures.json, so every "
                         "hypothesis can be tested failures-vs-successes",
                "_split": "fit",
                "_config": "ms-marco-MiniLM-L-2-v2-ft-session-j, depth 10 (shipped)",
                "_contrast": "gold vs competitor; competitor = rank-1 winner in a failure, "
                             "rank-2 runner-up in a correct case",
                "summary": {
                    "queries": len(pools),
                    "R@1": r1,
                    "correct": len(successes),
                    "failures": len(failures),
                    "strict_successes_competitor_not_gold": cmps["_strict_n"],
                    "by_category": {
                        c: {
                            "correct": sum(1 for r in successes if r["category"] == c),
                            "failures": sum(1 for r in failures if r["category"] == c),
                        }
                        for c in sorted({p.category for p in pools.values()})
                    },
                },
                "comparisons": {
                    k: v for k, v in cmps.items() if not k.startswith("_")
                },
                "predicates": {k: v[0] for k, v in PREDICATES.items()},
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
