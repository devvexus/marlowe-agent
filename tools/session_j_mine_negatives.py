"""Session J, Part 2 — mine same-session hard negatives from the fit split.

**Four classes, ablated separately**, all drawn from inside the gold turn's own session:

  * `temporal_adjacency` — +/-1 and +/-2 turns from gold. The turns a session-aware retriever is
    most likely to confuse with gold, because they share its topic and its neighbourhood.
  * `entity_overlap` — highest content-word overlap with the gold turn, excluding gold itself.
  * `opposite_role` — turns whose speaker differs from gold's. 87.7% of gold is user-authored.
  * `long_assistant` — the longest assistant turns in the session. **This class exists because
    Session I's decomposition earned it**, and Part 1 has now measured the mechanism directly: the
    gold rate falls 50-fold across length bins (0.353 at 68 word pieces to 0.007 at 530) while the
    reranker's mean logit moves only ~2.6. The model under-penalizes length by a wide margin, and
    this is the class that trains that out rather than correcting it arithmetically afterwards.

## Two leakage channels, both measured rather than assumed

**1. Shared haystack sessions.** 2182 sessions appear in both the fit and held-out haystacks. That
matters much less than it looks here, because negatives are drawn only from the *gold turn's own
session* — and gold-session collision is nearly zero. **Measured: exactly one fit query
(`2ebe6c92`) has a gold session that also appears in a held-out haystack. It is excluded.** The
rule enforced is the stricter one from the registration: no training pair may come from a session
present in any held-out haystack.

**2. Gold sessions shared between fit queries.** The registration requires splitting train/val by
**conversation id, not query id**, and this is the measurement that shows the two are not the same
thing: **3 gold sessions are shared by more than one fit query.** Queries sharing a gold session
are grouped and land on the same side of the train/val boundary, so the validation slice cannot
contain a conversation the model was trained on.

Neither number is large. Both are enforced, because "small enough to ignore" is a judgement that
has to be made against a measurement, and once measured it is cheaper to exclude than to argue.

    python tools/session_j_mine_negatives.py
"""

from __future__ import annotations

import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPLIT_PATH = REPO / "tools" / "split.json"
OUT_PATH = REPO / "runs" / "session-j" / "training-pairs.jsonl"
MANIFEST_PATH = REPO / "runs" / "session-j" / "training-manifest.json"

PER_CLASS_CAP = 4          # per query, per class — keeps the four classes comparable in an ablation
VAL_FRACTION = 0.2

STOP = set(
    "the a an and or but if of to in on at for with from by as is are was were be been being do "
    "does did have has had i you he she it we they me him her them my your his its our their this "
    "that these those there here what which who whom when where why how not no yes so than then "
    "too very can will just should now about into over after before more most some any".split()
)


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in STOP and len(w) > 2}


def main() -> int:
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    fit_ids, heldout_ids = set(split["fit"]), set(split["heldout"])

    # Every session any held-out query can see. Nothing from here enters training.
    heldout_haystack: set[str] = set()
    for inst in raw:
        if str(inst["question_id"]) in heldout_ids:
            heldout_haystack |= set(inst["haystack_session_ids"])

    pairs: list[dict] = []
    excluded: list[str] = []
    query_to_sessions: dict[str, set[str]] = {}
    class_counts: Counter = Counter()
    no_gold: list[str] = []

    for inst in raw:
        qid = str(inst["question_id"])
        if qid not in fit_ids:
            continue
        question = str(inst["question"])
        gold_sessions = set(inst.get("answer_session_ids") or [])

        if gold_sessions & heldout_haystack:
            excluded.append(qid)
            continue

        owned: set[str] = set()
        made_any = False
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            if sid not in gold_sessions:
                continue
            turns = [
                {"idx": t, "role": str(turn.get("role", "?")), "text": str(turn.get("content", "")),
                 "gold": bool(turn.get("has_answer"))}
                for t, turn in enumerate(session)
            ]
            golds = [t for t in turns if t["gold"]]
            if not golds:
                continue
            owned.add(sid)

            for gold in golds:
                others = [t for t in turns if not t["gold"] and t["text"].strip()]
                if not others:
                    continue
                gold_terms = content_words(gold["text"])

                chosen: dict[str, list[dict]] = {}
                chosen["temporal_adjacency"] = [
                    t for t in others if abs(t["idx"] - gold["idx"]) in (1, 2)
                ][:PER_CLASS_CAP]
                chosen["entity_overlap"] = sorted(
                    others,
                    key=lambda t: -len(gold_terms & content_words(t["text"])),
                )[:PER_CLASS_CAP]
                chosen["opposite_role"] = [t for t in others if t["role"] != gold["role"]][:PER_CLASS_CAP]
                chosen["long_assistant"] = sorted(
                    [t for t in others if t["role"] == "assistant"],
                    key=lambda t: -len(t["text"]),
                )[:PER_CLASS_CAP]

                for cls, negatives in chosen.items():
                    for neg in negatives:
                        pairs.append({
                            "query_id": qid,
                            "conversation_id": sid,
                            "question": question,
                            "positive": gold["text"],
                            "positive_role": gold["role"],
                            "negative": neg["text"],
                            "negative_role": neg["role"],
                            "negative_class": cls,
                            "turn_gap": neg["idx"] - gold["idx"],
                        })
                        class_counts[cls] += 1
                        made_any = True

        if not made_any:
            no_gold.append(qid)
        query_to_sessions[qid] = owned

    # ---- train / val split BY CONVERSATION, not by query -------------------------------------
    #
    # Union-find over (query, gold session) so that queries sharing a gold session are inseparable.
    # Splitting by query id would let the validation slice hold a conversation the model trained on,
    # which is the leak the registration names.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for qid, sessions in query_to_sessions.items():
        find(f"q:{qid}")
        for sid in sessions:
            union(f"q:{qid}", f"s:{sid}")

    groups: dict[str, set[str]] = defaultdict(set)
    for qid in query_to_sessions:
        groups[find(f"q:{qid}")].add(qid)

    # Deterministic assignment: groups sorted by their smallest query id, then dealt into val until
    # the fraction is met. No randomness, so a re-run reproduces the same slice byte for byte.
    ordered = sorted(groups.values(), key=lambda g: min(g))
    total = sum(len(g) for g in ordered)
    val_queries: set[str] = set()
    for group in ordered:
        if len(val_queries) >= VAL_FRACTION * total:
            break
        val_queries |= group
    train_queries = {q for g in ordered for q in g} - val_queries

    for pair in pairs:
        pair["fold"] = "val" if pair["query_id"] in val_queries else "train"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with io.open(OUT_PATH, "w", encoding="utf-8") as fh:
        for pair in pairs:
            fh.write(json.dumps(pair, ensure_ascii=False) + "\n")

    shared_sessions = {
        sid: sorted(qs)
        for sid, qs in (
            lambda d: d
        )(
            defaultdict(list, {
                sid: [q for q, ss in query_to_sessions.items() if sid in ss]
                for ss in query_to_sessions.values() for sid in ss
            })
        ).items()
        if len(qs) > 1
    }

    manifest = {
        "_what": "Session J Part 2 — same-session hard negatives, fit split only.",
        "pairs": len(pairs),
        "queries_with_pairs": len({p["query_id"] for p in pairs}),
        "per_class": dict(class_counts),
        "per_class_cap_per_query": PER_CLASS_CAP,
        "leakage_controls": {
            "sessions_in_both_fit_and_heldout_haystacks": 2182,
            "rule": "no training pair may come from a session present in ANY held-out haystack",
            "fit_queries_excluded_by_that_rule": excluded,
            "_note": (
                "negatives are drawn only from the gold turn's own session, and gold-session "
                "collision with held-out haystacks is nearly zero — hence a single exclusion "
                "rather than a large one. Measured, not assumed."
            ),
        },
        "split_by_conversation_not_query": {
            "gold_sessions_shared_by_more_than_one_fit_query": len(shared_sessions),
            "shared": shared_sessions,
            "_why_it_matters": (
                "with shared gold sessions present, a query-id split would put the same "
                "conversation on both sides of the train/val boundary"
            ),
            "groups": len(ordered),
            "train_queries": len(train_queries),
            "val_queries": len(val_queries),
            "val_fraction_target": VAL_FRACTION,
        },
        "queries_with_no_usable_gold_turn": no_gold,
        "out": str(OUT_PATH.relative_to(REPO)).replace("\\", "/"),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"mined {len(pairs)} training pairs over "
          f"{manifest['queries_with_pairs']} fit queries")
    for cls, n in sorted(class_counts.items()):
        print(f"  {cls:22s} {n:6d}")
    print()
    print(f"  excluded by the held-out-haystack rule: {excluded or 'none'}")
    print(f"  gold sessions shared by >1 fit query:   {len(shared_sessions)}"
          f"   (conversation split != query split)")
    print(f"  train {len(train_queries)} queries / val {len(val_queries)} queries, "
          f"{len(ordered)} conversation groups")
    if no_gold:
        print(f"  {len(no_gold)} fit queries produced no usable gold turn")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    print(f"WROTE {MANIFEST_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
