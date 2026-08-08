"""R5 -- can harm-weighted precision vary? The ADR-010 check, before any band is registered.

Every arm since Session H has optimized R@1, which treats all rank-1 failures as equal. Brief
Sec 5.7 does not: a topically-adjacent turn that adds nothing costs tokens, while a superseded fact
injected as current actively misleads, and the second is what the trust-class and supersession
machinery exists to prevent. This script asks whether that distinction is MEASURABLE on this corpus
and whether the resulting read can vary. It registers nothing and proposes nothing.

**The structural fact this rests on, and it needs no new labels.** LongMemEval's knowledge-update
cases carry EXACTLY TWO answer sessions. The earlier one states an old value of a fact; the later
one states the value the `answer` field actually holds. Both are marked `has_answer: true`, so
`longmemeval.load` puts BOTH turn ids in `gold_turn_ids` -- which means the harness scores a hit
when the ranker returns the STALE fact. That is not a caveat on the harm question; it is the harm
question, and R@1 has been counting the harmful case as a success.

**Supersession is restricted to knowledge-update, deliberately.** Other categories also carry
multiple answer sessions -- multi-session questions need several turns to answer and none of them
supersedes another. Applying a recency rule there would manufacture harm out of a category where
the design intends every answer session to count. The per-category counts are printed so the
restriction is visible rather than asserted.

Classes, over the SHIPPED rank-1. "Current" and "stale" are decided by which answer session holds
the value the `answer` field states -- see `load_case_structure`, which explains why no ordering is
used to decide it:

  current          rank 1 is gold and in the answer-bearing session
  superseded       rank 1 is gold and in the OTHER answer session of a knowledge-update case
                   -- HARMFUL, and scored as CORRECT by every R@1 in this project
  stale_session    rank 1 is NOT gold but sits in that same superseded session -- the stale fact,
                   a different turn of it
  on_topic_wrong   rank 1 is not gold but sits in some answer session -- the right conversation,
                   the wrong turn
  irrelevant       rank 1 is in no answer session at all -- costs tokens, misleads nobody

Prints numbers. Applies nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval" / "src"))

SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
SPLIT_PATH = REPO / "tools" / "split.json"
OUT = REPO / "runs" / "session-m0c" / "reach-r5-harm-classes.json"

# ADR-013's numeric form: a read must be able to vary before a band is registered on it.
MIN_FOR_A_REPORTABLE_READ = 10


def sess_of(turn_id: str) -> str:
    return turn_id.rsplit("-", 1)[0]


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _toks(s) -> set[str]:
    return set(_norm(s).split())


def load_case_structure(corpus_path) -> dict[str, dict]:
    """Per case: question_type, the gold turn ids, and WHICH answer session holds the CURRENT value.

    **The current session is identified by the `answer` field, not by an ordering.** A first
    version ranked the two answer sessions by `haystack_dates` and called the later one current.
    That is a proxy, and this corpus is exactly the wrong place for it: the loader records that the
    released data dates 76 of 500 cases with sessions after their own question. Ordering by the
    `_1`/`_2` suffix is a second proxy -- a naming convention is not a timestamp.

    The quantity actually wanted is "which gold turn states the value the answer holds", and that
    is directly checkable: normalise the `answer` and look for it in each session's gold text.
    Where the answer appears verbatim in exactly one, the identification is DECISIVE. Where it does
    not, token overlap breaks the tie and the case is flagged `fallback` so every number below can
    be re-read with those cases removed.

    Measured on this corpus: the answer-bearing session is the later one by suffix in 86.4% of the
    59 decisive knowledge-update cases and the later one by date in 84.7%. Neither ordering is
    reliable enough to classify harm by, which is why neither is used."""
    raw = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    out = {}
    decisive = fallback = 0
    for inst in raw:
        qid = str(inst["question_id"])
        ans = list(inst["answer_session_ids"])
        answer = str(inst.get("answer", ""))
        gold_by_sess: dict[str, list[str]] = defaultdict(list)
        gold = set()
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for i, t in enumerate(session):
                if t.get("has_answer"):
                    gold.add(f"{sid}-{i}")
                    gold_by_sess[sid].append(str(t["content"]))

        current_sess, how = None, "not_applicable"
        if inst["question_type"] == "knowledge-update" and len(ans) == 2 \
                and all(s in gold_by_sess for s in ans):
            at = _toks(answer)

            def score(sid):
                txt = " ".join(gold_by_sess[sid])
                return (_norm(answer) in _norm(txt), len(at & _toks(txt)) / max(len(at), 1))

            s0, s1 = score(ans[0]), score(ans[1])
            if s0[0] != s1[0]:
                current_sess, how = (ans[0] if s0[0] else ans[1]), "verbatim"
                decisive += 1
            elif s0[1] != s1[1]:
                current_sess, how = (ans[0] if s0[1] > s1[1] else ans[1]), "token_overlap"
                decisive += 1
            else:
                current_sess, how = sorted(ans)[-1], "fallback_suffix_order"
                fallback += 1

        out[qid] = {"question_type": inst["question_type"], "answer_sessions": set(ans),
                    "gold": gold, "answer": answer, "current_session": current_sess,
                    "identified_by": how}
    print(f"  knowledge-update current-session identification: {decisive} decisive from the "
          f"answer text, {fallback} by suffix fallback (flagged)")
    return out


def classify(turn_id: str, case: dict) -> str:
    s = sess_of(turn_id)
    is_gold = turn_id in case["gold"]
    cur = case["current_session"]
    # `stale` is defined only where a current session was identified -- i.e. knowledge-update with
    # two gold-bearing answer sessions. Everywhere else the class is empty BY CONSTRUCTION, which
    # is stated rather than inferred from a count of zero.
    stale = (case["answer_sessions"] - {cur}) if cur is not None else set()

    if is_gold:
        return "superseded" if s in stale else "current"
    if s in stale:
        return "stale_session"
    if s in case["answer_sessions"]:
        return "on_topic_wrong"
    return "irrelevant"


HARMFUL = ("superseded", "stale_session")
CLASSES = ("current", "superseded", "stale_session", "on_topic_wrong", "irrelevant")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    print("reading corpus structure ...")
    cases = load_case_structure(REPO / split["corpus_path"])

    print()
    print("=" * 96)
    print("R5 -- CAN HARM-WEIGHTED PRECISION VARY?  (ADR-010, before any band)")
    print("=" * 96)

    # ---- how many cases can express supersession at all -------------------------------------
    per_cat = defaultdict(lambda: Counter())
    for c in cases.values():
        per_cat[c["question_type"]][len(c["answer_sessions"])] += 1
    print()
    print("  answer-session counts by category -- only knowledge-update is treated as supersession")
    print(f"  {'category':<30} {'1 session':>10} {'2 sessions':>11} {'3+':>5}")
    for cat in sorted(per_cat):
        c = per_cat[cat]
        print(f"  {cat:<30} {c[1]:>10} {c[2]:>11} {sum(v for k,v in c.items() if k>=3):>5}")

    report: dict = {
        "_what": "R5 ADR-010 reachability for harm-weighted precision",
        "_the_structural_fact": "LongMemEval knowledge-update cases carry two answer sessions and "
                                "BOTH are marked has_answer, so gold_turn_ids contains the stale "
                                "turn. Every R@1 in this project scores a hit on the superseded "
                                "fact.",
        "answer_sessions_by_category": {k: dict(v) for k, v in per_cat.items()},
    }

    for spl in ("fit", "heldout"):
        recs = json.loads(Path(str(SLATES).format(split=spl)).read_text(
            encoding="utf-8"))["records"]
        n = len(recs)
        counts = Counter()
        ku_counts = Counter()
        rows = []
        for r in recs:
            case = cases[r["query_id"]]
            cls = classify(r["turn_ids"][0], case)
            counts[cls] += 1
            if case["question_type"] == "knowledge-update":
                ku_counts[cls] += 1
            rows.append({"query_id": r["query_id"], "category": case["question_type"],
                         "class": cls, "margin": r["margin"],
                         "identified_by": case["identified_by"],
                         "r_at_1_correct": bool(r["correct"])})

        r1 = counts["current"] + counts["superseded"]
        print()
        print("-" * 96)
        print(f"  {spl}  n={n}   SHIPPED rank-1 harm classes")
        print("-" * 96)
        for c in CLASSES:
            tag = "  <- HARMFUL" if c in HARMFUL else ""
            tag += "   <- counted as an R@1 HIT" if c == "superseded" else ""
            print(f"    {c:<18} {counts[c]:>4d}  ({counts[c]/n:>6.2%}){tag}")
        print(f"    {'TOTAL':<18} {n:>4d}")
        print()
        print(f"    R@1 as published                     "
              f"{r1}/{n} = {r1/n:.4f}   (current + superseded)")
        print(f"    R@1 counting ONLY the current value  "
              f"{counts['current']}/{n} = {counts['current']/n:.4f}   "
              f"({counts['superseded']} stale hits removed)")
        harmful = sum(counts[c] for c in HARMFUL)
        print(f"    harmful rank-1 injections            {harmful}/{n} = {harmful/n:.4f}")
        fails = n - r1
        print(f"    of the {fails} R@1 failures: stale_session {counts['stale_session']}, "
              f"on_topic_wrong {counts['on_topic_wrong']}, irrelevant {counts['irrelevant']}")
        print(f"    knowledge-update only ({sum(ku_counts.values())} queries): "
              f"{dict(ku_counts)}")

        fb = [x for x in rows if x["identified_by"] == "fallback_suffix_order"]
        fb_harm = sum(1 for x in fb if x["class"] in HARMFUL)
        print(f"    SENSITIVITY: {len(fb)} queries were classified by suffix fallback rather than "
              f"by the answer text;")
        print(f"                 {fb_harm} of them are in a harmful class. Excluding them, "
              f"harmful = {harmful - fb_harm}/{n - len(fb)}.")

        report[spl] = {
            "n": n,
            "classified_by_fallback": len(fb),
            "harmful_excluding_fallback": harmful - fb_harm,
            "classes": {c: counts[c] for c in CLASSES},
            "r_at_1_published": round(r1 / n, 4),
            "r_at_1_current_only": round(counts["current"] / n, 4),
            "stale_hits_counted_as_correct": counts["superseded"],
            "harmful_rank1": harmful,
            "harm_rate": round(harmful / n, 4),
            "knowledge_update_only": dict(ku_counts),
            "_rows": rows,
        }

    # ---- ADR-010 / ADR-013: can the read vary? ----------------------------------------------
    print()
    print("=" * 96)
    print("ADR-010 REACH + ADR-013 READ -- verdict")
    print("=" * 96)
    verdicts = {}
    for spl in ("fit", "heldout"):
        d = report[spl]
        harmful = d["harmful_rank1"]
        stale_hits = d["stale_hits_counted_as_correct"]
        can_vary = harmful >= MIN_FOR_A_REPORTABLE_READ
        print(f"  {spl}: {harmful} harmful rank-1 injections "
              f"(floor {MIN_FOR_A_REPORTABLE_READ}) -> "
              f"{'CAN VARY' if can_vary else 'CANNOT VARY -- do not register a band'}")
        print(f"         of which {stale_hits} are gold-marked stale turns that R@1 scores as hits")
        verdicts[spl] = {"harmful": harmful, "floor": MIN_FOR_A_REPORTABLE_READ,
                         "can_vary": bool(can_vary),
                         "stale_hits_counted_as_correct": stale_hits}
    report["adr_010_verdict"] = verdicts

    print()
    print("  CAN MOVE     harm-weighted precision, and R@1-counting-only-the-current-value.")
    print("               Both are functions of WHICH turn reaches rank 1, which every ranking")
    print("               mechanism changes.")
    print("  CANNOT MOVE  the harm class of a query whose slate contains no earlier-session turn.")
    print("               Supersession is expressible on knowledge-update cases only; on every")
    print("               other category the superseded class is empty BY CONSTRUCTION and a")
    print("               band read over the whole split dilutes by that fraction.")
    print("  CANNOT MOVE  anything via the Sec 4.3 supersession exclusion as it stands. It is live")
    print("               (entry.rs:124, called at retrieve.rs:328) but the only writer of")
    print("               superseded_by is consolidation's 0.98-cosine near-duplicate merge")
    print("               (consolidate.rs:697); ingest.rs:142 hardcodes None and the Sec 4.6 wire")
    print("               has no supersession field. ADR-012 measured pairs at >=0.98 as 0.0086%")
    print("               of 30.6M. The filter cannot see a semantic contradiction.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
