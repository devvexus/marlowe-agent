"""How often does the rank-1 turn STATE the gold answer without being flagged as gold?

    python tools/answer_containment.py
    -> runs/session-m0c-m/answer-containment.json

**This is a DIAGNOSTIC and it is reported BESIDE R@1. It does not replace R@1, it does not redefine
it, and nothing in `eval/` is touched.** `eval/` is the scoreboard; a metric loosened after seeing
which cases it would rescue is precisely what the working agreement forbids. What this measures is a
property of the CORPUS LABELS, not of the retriever: the denominator R@1 is scored against contains
cases where the turn at rank 1 answers the question and the corpus does not say so. Knowing how many
tells you what fraction of the remaining headroom is reachable at all.

Known example, and it is why this exists. Query `07741c45`, *"Where do I currently keep my old
sneakers?"*, answer *"in a shoe rack in my closet"*. Rank 1 is
`"...I need to organize my closet this weekend, and I'm looking forward to storing my old sneakers in
a shoe rack..."` -- unflagged, and scored as a miss. The flagged gold turn states the SUPERSEDED
value (*"keeping them under my bed"*).

## The containment rule, stated in full

Both texts are normalised the same way: lowercased, every character outside `[a-z0-9]` replaced by a
space, whitespace collapsed. Then:

  * **STRICT** -- the normalised answer occurs as a contiguous run of whole tokens in the normalised
    turn. Word-boundary safe, so `"rack"` does not match `"racket"`.
  * **LOOSE** -- STRICT, **or** every *content* token of the answer occurs somewhere in the turn's
    token set, order-free. Content tokens are alphanumeric tokens of length > 2 that are not
    function words, plus every purely numeric token regardless of length (`"3"`, `"2019"` carry the
    answer in this corpus and must not be dropped).

**Both are reported, always, and so is a third.** LOOSE with a one-content-token answer is close to
free -- `"yes"`, `"blue"`, `"Paris"` will match half a haystack -- so `loose_min2`, restricted to
answers carrying at least two content tokens, is reported as the sensitivity band. A single headline
number here would be a number whose value is set by the rule that produced it, which is the thing
this repo keeps catching.

Answers that reduce to zero content tokens are **excluded and counted**, not scored as hits.

## The second number: near-verbatim duplicates of a flagged gold turn

A separate corpus property, and separately reported. For every flagged gold turn, is there another
turn -- NOT flagged -- that is a near-verbatim duplicate of it? Reported at three thresholds
(content-token Jaccard 1.0 / 0.9 / 0.8) and at two scopes, because the corpus has two meanings of
"same session":

  * `haystack_session` -- the same LongMemEval session id, the corpus's own unit
  * `case` -- anywhere in the same question's haystack, which is what the harness sees, since
    `datasets/longmemeval.py` flattens all ~50 sessions into one `SessionHistory`

**A duplicate is not the same thing as an unflagged turn that answers the question**, and 07741c45 is
the case that shows it: its unflagged competitor is not a duplicate of the gold turn at any
threshold. So `unflagged_containing` is reported too -- turns elsewhere in the case that satisfy the
loose containment rule but are not flagged. That is the property 07741c45 actually exemplifies.

**Gate:** the reconstruction reproduces the published fit R@1 of 0.7555 exactly, or nothing is
written. Same refusal, same reason, as `tools/failure_forensics.py`.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
OUT_PATH = OUT_DIR / "answer-containment.json"

JACCARD_THRESHOLDS = (1.0, 0.9, 0.8)

STOP = frozenset(
    """
    a an the and or but if then than that this these those there here of in on at to for from by
    with without about into over under again further once is are was were be been being am do does
    did doing have has had having i me my myself we our ours you your yours he him his she her it
    its they them their what which who whom when where why how all any both each few more most
    other some such no nor not only own same so too very can will just should now would could may
    might must shall im ive id ill dont doesnt didnt cant wont hes shes theyre youre thats
    as up down out off s t d ll m o re ve y
    """.split()
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> list[str]:
    """Lowercase, punctuation to space, split. The single normalisation both rules run on."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).split()


def content_tokens(tokens: list[str]) -> set[str]:
    """Length > 2 and not a function word -- plus every purely numeric token, whatever its length."""
    return {t for t in tokens if t.isdigit() or (len(t) > 2 and t not in STOP)}


def contains_strict(answer_tokens: list[str], turn_tokens: list[str]) -> bool:
    """The answer as a contiguous run of whole tokens in the turn."""
    n = len(answer_tokens)
    if n == 0 or n > len(turn_tokens):
        return False
    for i in range(len(turn_tokens) - n + 1):
        if turn_tokens[i : i + n] == answer_tokens:
            return True
    return False


def contains_loose(answer_content: set[str], turn_tokens_set: set[str]) -> bool:
    """Every content token of the answer present somewhere in the turn, order-free."""
    return bool(answer_content) and answer_content <= turn_tokens_set


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main() -> int:
    pools, _stats = load_pools(FIT_POOLS)
    texts_all = turn_texts()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    cases = {c.query_id: c for c in corpus.cases}
    gold_map = corpus.gold_map()

    # -- the gate --------------------------------------------------------------------------------
    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING. Reconstructed fit R@1 is {r1}; published is {CONTROL_R1}. A containment "
            "figure read off a different ranking would describe a product that does not exist."
        )
    print(f"gate: fit R@1 {r1} == published {CONTROL_R1}  ({len(pools)} queries)")

    # -- 1. containment at rank 1 ------------------------------------------------------------------
    records, skipped = [], []
    for qid, pool in pools.items():
        case = cases[qid]
        ans_tokens = normalise(case.gold_answer)
        ans_content = content_tokens(ans_tokens)
        top = int(orders[qid][0])
        top_c = pool.candidates[top]
        text = texts_all.get(qid, {}).get(top_c.turn_id) or ""
        tt = normalise(text)
        tt_set = set(tt)

        if not ans_content:
            skipped.append({"query_id": qid, "gold_answer": case.gold_answer})
            continue

        strict = contains_strict(ans_tokens, tt)
        loose = strict or contains_loose(ans_content, tt_set)
        records.append(
            {
                "query_id": qid,
                "category": pool.category,
                "question": case.question,
                "gold_answer": case.gold_answer,
                "answer_content_tokens": sorted(ans_content),
                "rank1_turn_id": top_c.turn_id,
                "rank1_is_flagged_gold": bool(pool.gold[top]),
                "rank1_contains_strict": strict,
                "rank1_contains_loose": loose,
                "rank1_text": text,
            }
        )

    def tally(rows):
        n = len(rows)
        if n == 0:
            return {"n": 0}
        flagged = sum(r["rank1_is_flagged_gold"] for r in rows)
        min2 = [r for r in rows if len(r["answer_content_tokens"]) >= 2]
        return {
            "n": n,
            # R@1 restricted to the same rows, so containment and R@1 share a denominator and can
            # be read on one line. NOT the published R@1 -- that is over all 229 including the
            # zero-content-answer cases, and is printed separately.
            "R@1_on_these_rows": round(flagged / n, 4),
            "contains_strict": round(sum(r["rank1_contains_strict"] for r in rows) / n, 4),
            "contains_loose": round(sum(r["rank1_contains_loose"] for r in rows) / n, 4),
            "contains_loose_min2": (
                round(sum(r["rank1_contains_loose"] for r in min2) / len(min2), 4) if min2 else None
            ),
            "n_min2": len(min2),
            # The label-artifact bucket: rank 1 answers the question and the corpus does not agree.
            "unflagged_but_contains_strict": sum(
                1 for r in rows if not r["rank1_is_flagged_gold"] and r["rank1_contains_strict"]
            ),
            "unflagged_but_contains_loose": sum(
                1 for r in rows if not r["rank1_is_flagged_gold"] and r["rank1_contains_loose"]
            ),
            # The diagnostic ceiling: flagged-gold OR contains. Explicitly NOT R@1.
            "diagnostic_hit_or_contains_strict": round(
                sum(1 for r in rows if r["rank1_is_flagged_gold"] or r["rank1_contains_strict"]) / n,
                4,
            ),
            "diagnostic_hit_or_contains_loose": round(
                sum(1 for r in rows if r["rank1_is_flagged_gold"] or r["rank1_contains_loose"]) / n,
                4,
            ),
        }

    overall = tally(records)
    by_category = {
        c: tally([r for r in records if r["category"] == c])
        for c in sorted({r["category"] for r in records})
    }

    # -- 2. near-verbatim duplicates of a flagged gold turn ----------------------------------------
    #
    # Only flagged gold turns are probed, against every other turn in the case. Two scopes, three
    # thresholds, all reported.
    # The unit of this count is a FLAGGED GOLD TURN, not a case: the question is how many gold
    # labels have an unflagged twin, and a case with three gold turns contributes three chances.
    dup_counts = {
        scope: {str(t): 0 for t in JACCARD_THRESHOLDS} for scope in ("haystack_session", "case")
    }
    dup_hist = Counter()
    dup_examples = []
    unflagged_containing_cases = 0
    unflagged_containing_cases_min2 = 0
    n_min2_cases = 0
    unflagged_containing_examples = []
    probed_gold_turns = 0

    for qid, pool in pools.items():
        case = cases[qid]
        turns = texts_all.get(qid, {})
        flagged = set(gold_map.get(qid, frozenset()))
        if not turns:
            continue
        tok = {tid: content_tokens(normalise(t)) for tid, t in turns.items()}
        # `sid-t_idx`; no released session id contains a hyphen (checked in reach_pools).
        sid_of = {tid: tid.rsplit("-", 1)[0] for tid in turns}

        for gid in sorted(flagged):
            if gid not in tok:
                continue
            probed_gold_turns += 1
            best = {"haystack_session": 0.0, "case": 0.0}
            best_rec = None
            for tid, tset in tok.items():
                if tid == gid or tid in flagged:
                    continue
                j = jaccard(tok[gid], tset)
                scope = "haystack_session" if sid_of[tid] == sid_of[gid] else "case"
                if j > best[scope]:
                    best[scope] = j
                if j > (best_rec["jaccard"] if best_rec else 0.0):
                    best_rec = {
                        "query_id": qid,
                        "gold_turn_id": gid,
                        "duplicate_turn_id": tid,
                        "scope": scope,
                        "jaccard": round(j, 4),
                    }
            # `case` scope is the union: the harness flattens all haystack sessions into one
            # history, so a twin in a sibling session is a twin as far as retrieval is concerned.
            anywhere = max(best["haystack_session"], best["case"])
            for t in JACCARD_THRESHOLDS:
                if best["haystack_session"] >= t:
                    dup_counts["haystack_session"][str(t)] += 1
                if anywhere >= t:
                    dup_counts["case"][str(t)] += 1
            dup_hist[f"{int(anywhere * 10) / 10:.1f}"] += 1
            if best_rec and best_rec["jaccard"] >= 0.8:
                dup_examples.append(best_rec)

        # -- the property 07741c45 actually exemplifies ------------------------------------------
        ans_tokens = normalise(case.gold_answer)
        ans_content = content_tokens(ans_tokens)
        if ans_content:
            found = []
            for tid, text in turns.items():
                if tid in flagged:
                    continue
                tt = normalise(text)
                if contains_strict(ans_tokens, tt) or contains_loose(ans_content, set(tt)):
                    found.append(tid)
            if len(ans_content) >= 2:
                n_min2_cases += 1
                unflagged_containing_cases_min2 += bool(found)
            if found:
                unflagged_containing_cases += 1
                unflagged_containing_examples.append(
                    {"query_id": qid, "n_unflagged_containing": len(found), "turn_ids": found[:5]}
                )

    dup_examples.sort(key=lambda r: -r["jaccard"])

    # 07741c45, named in the plan, carried explicitly so its reading is on the record.
    known = next((r for r in records if r["query_id"] == "07741c45"), None)
    known_dup = next((r for r in dup_examples if r["query_id"] == "07741c45"), None)

    summary = {
        "published_fit_R@1_over_all_229": r1,
        "queries": len(pools),
        "scored": len(records),
        "skipped_zero_content_answer": len(skipped),
        "overall": overall,
        "by_category": by_category,
        "flagged_gold_turns_probed": probed_gold_turns,
        "gold_turns_with_unflagged_near_duplicate": dup_counts,
        "best_unflagged_jaccard_histogram": dict(sorted(dup_hist.items())),
        "cases_with_an_unflagged_turn_containing_the_answer": {
            "cases": unflagged_containing_cases,
            "of": len(pools),
            "rate": round(unflagged_containing_cases / len(pools), 4),
            "min2_cases": unflagged_containing_cases_min2,
            "of_min2": n_min2_cases,
            "rate_min2": (
                round(unflagged_containing_cases_min2 / n_min2_cases, 4) if n_min2_cases else None
            ),
        },
        "known_example_07741c45": {
            "rank1_contains_strict": known["rank1_contains_strict"] if known else None,
            "rank1_contains_loose": known["rank1_contains_loose"] if known else None,
            "rank1_is_flagged_gold": known["rank1_is_flagged_gold"] if known else None,
            "best_near_duplicate_jaccard_ge_0.8": known_dup,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "_what": "answer containment at rank 1, fit split -- a DIAGNOSTIC reported beside "
                         "R@1, never replacing it. eval/ is untouched.",
                "_split": "fit",
                "_config": "ms-marco-MiniLM-L-2-v2-ft-session-j, depth 10 (shipped)",
                "_rule": "strict = normalised answer as a contiguous whole-token run; loose = "
                         "strict OR all answer content tokens present order-free; loose_min2 = "
                         "loose restricted to answers with >= 2 content tokens",
                "summary": summary,
                "skipped": skipped,
                "near_duplicate_examples": dup_examples[:40],
                "unflagged_containing_examples": unflagged_containing_examples[:40],
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # -- report ------------------------------------------------------------------------------------
    print()
    print(f"scored {len(records)} of {len(pools)} (skipped {len(skipped)} zero-content answers)")
    print()
    print(f"{'':28s} {'R@1':>8s} {'strict':>8s} {'loose':>8s} {'loose>=2':>9s} "
          f"{'unflag-s':>9s} {'unflag-l':>9s} {'diag-l':>8s}")
    def row(label, t):
        print(f"{label:28s} {t['R@1_on_these_rows']:>8.4f} {t['contains_strict']:>8.4f} "
              f"{t['contains_loose']:>8.4f} "
              f"{(t['contains_loose_min2'] if t['contains_loose_min2'] is not None else float('nan')):>9.4f} "
              f"{t['unflagged_but_contains_strict']:>9d} {t['unflagged_but_contains_loose']:>9d} "
              f"{t['diagnostic_hit_or_contains_loose']:>8.4f}")
    row("ALL", overall)
    for c, t in by_category.items():
        row(f"  {c}", t)
    print()
    print(f"answers with < 2 content tokens: {overall['n'] - overall['n_min2']} of {overall['n']}")
    print()
    print(f"flagged gold turns probed for a near-verbatim unflagged duplicate: {probed_gold_turns}")
    for scope, counts in dup_counts.items():
        print(f"  scope {scope:18s} " + "  ".join(f"J>={k}: {v}" for k, v in counts.items()))
    print("  best-unflagged-Jaccard histogram (bucket floor -> gold turns): "
          + json.dumps(dict(sorted(dup_hist.items()))))
    print()
    print(f"cases with SOME unflagged turn containing the answer (loose): "
          f"{unflagged_containing_cases} of {len(pools)} "
          f"({unflagged_containing_cases / len(pools):.1%});  restricted to >=2-content-token "
          f"answers: {unflagged_containing_cases_min2} of {n_min2_cases} "
          f"({unflagged_containing_cases_min2 / n_min2_cases:.1%})")
    print()
    print("known example 07741c45: " + json.dumps(summary["known_example_07741c45"]))
    print()
    print("BY CATEGORY, answers with < 2 content tokens: " + json.dumps(
        {c: t["n"] - t["n_min2"] for c, t in by_category.items()}
    ))
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    print("\nThis is a DIAGNOSTIC. R@1 on the fit split remains "
          f"{r1}. Nothing here changes it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
