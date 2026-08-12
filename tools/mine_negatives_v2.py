"""M0c Session M, Phase 2 PREPARATION — negatives the Session J miner structurally cannot reach.

    python tools/mine_negatives_v2.py

## The hole, verified in code rather than inferred

`tools/session_j_mine_negatives.py:94` reads

    if sid not in gold_sessions:
        continue

so every one of the 6,898 shipped fine-tuning pairs draws its negative from **inside the gold
turn's own session**. Four classes, all answering *"which turn inside the right conversation"*.
Meanwhile 14 of the 30 real in-slate failures put their rank-1 in a session containing **no gold at
all**, and the model's failure rate on queries it trained on (22.6%) equals its rate on queries held
apart (25.5%) — it underfits, so the lever is *which* negatives, not *how many*.

This file adds three classes and **modifies nothing**. `session_j_mine_negatives.py` is the record
of what produced the shipped graph; its `content_words`/`STOP` are imported here rather than
re-written, so `entity_overlap` and `question_echo` are ranked by the same tokenizer and a
per-class ablation compares classes rather than tokenizers.

| class | drawn from | ranked by |
|---|---|---|
| `deployed_top_k` | the SHIPPED model's own top-10 for the query, gold turns removed | the shipped five-level key itself |
| `cross_session` | sessions containing NO gold turn | content-word overlap with the QUESTION |
| `question_echo` | anywhere in the haystack | content-word overlap with the QUESTION |

`question_echo` exists because nothing currently maximises overlap with the **question** —
`entity_overlap` maximises overlap with the **gold turn**, which is a different quantity. The
distinction was control-tested at 41% of failures against 16% of successes.

## Four things that are enforced rather than assumed

**1. The reconstruction control, before any negative is mined.** `deployed_top_k` is only the
deployed competitor set if the ranking reproduces the deployed ranking. The shipped key is
re-derived from `runs/session-k/fit/` via `sweep_reranker_frontier.shipped_order` and must read fit
R@1 **0.7555** exactly, or this script refuses to write. It is the same refusal, for the same
reason, that `sweep_reranker_frontier.py` and `publish_precision_coverage.py` carry: a five-level
key has at least four ways to be subtly wrong and every one of them yields a plausible number.

**2. The held-out haystack rule, which now BINDS where it did not before.** Session J excluded one
fit query, because negatives came only from gold sessions and gold-session collision with the
held-out haystacks is nearly zero. Two of these three classes draw from *non-gold* sessions, and
**2,182 sessions appear in both haystacks** — so the registration's rule ("no training pair may
come from a session present in ANY held-out haystack") stops being a formality and starts removing
real candidates. It is enforced per candidate turn and the drops are counted per class.

**3. The fold structure is Session J's, reproduced and then CHECKED against its output.** The
train/val boundary is drawn over the same union-find on (query, gold session) as Session J, seeded
from the same query set — every non-excluded fit query, including those that produce no pair. The
manifest reports agreement with `runs/session-j/training-pairs.jsonl` query by query. Reproducing
the logic is not evidence that it reproduced; comparing to the artifact is.

**4. The false-negative filter, because a mined "negative" that states the answer is a label error
that actively teaches the wrong thing.** ~9 of the current rank-1 winners genuinely state the
answer, so this bites hardest on exactly the class most likely to help. Matching is
whitespace-normalised, case-insensitive, with alphanumeric lookarounds rather than `\\b` so that
`10%` and `3:1` match as written. **106 of the 500 released answers are under four characters and
mostly bare numerals**, where containment is a weak reading of "this turn states the answer" — so
the manifest reports the short-answer share of every drop count rather than folding it in silently.

Determinism: every ordering is total and explicit, every set is `sorted()` before it reaches
output, and nothing reads a clock. Two runs are byte-identical; `--verify-determinism` re-runs the
mine in-process and compares.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_j_mine_negatives as J  # noqa: E402  — tokenizer + STOP list, imported not copied
import sweep_reranker_frontier as SW  # noqa: E402  — the shipped five-level ranking key
from reach_pools import load_pools  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
FIT_POOLS = REPO / "runs" / "session-k" / "fit"
SESSION_J_PAIRS = REPO / "runs" / "session-j" / "training-pairs.jsonl"
OUT_DIR = REPO / "runs" / "session-m0c-m"
STATS_PATH = OUT_DIR / "negatives-v2-stats.json"
PAIRS_NAME = "training-pairs-v2.jsonl"

# The published fit R@1 of the shipped configuration. `deployed_top_k` is meaningless unless the
# reconstruction reproduces it; see sweep_reranker_frontier.py's identical control.
CONTROL_FIT_R1 = 0.7555

# ---- the caps, each with its reason ----------------------------------------------------------

DEPLOYED_TOP_K_DEPTH = 10
"""The shipped slate depth. Not a tuning knob: these are exactly the turns the deployed model puts
in front of the answer at inference, so the depth is the deployment's, not this script's."""

CROSS_SESSION_CAP = 4
"""Per (gold turn, class), matching Session J's `PER_CLASS_CAP = 4`. The reason is Session J's:
a per-class ablation compares classes only if the classes are comparable in volume, so this class
is sized to sit beside `entity_overlap` (1,876) rather than to be as large as the corpus allows.
The mining rule could emit ~45 non-gold sessions per query; that would make the ablation a
measurement of volume."""

CROSS_SESSION_MAX_PER_SESSION = 1
"""At most one turn per distractor session. The four highest-overlap turns of a single distractor
session are near-duplicates of one another — same topic, usually adjacent — so they teach one
distinction four times. One turn from each of the four highest-overlap distractor sessions teaches
four. The failure this class targets is 14 rank-1s in 14 different wrong sessions, and the manifest
reports `distinct_sessions_drawn_from` so the choice is observable rather than asserted."""

QUESTION_ECHO_CAP = 4
"""Same reason as CROSS_SESSION_CAP: sized against Session J's four."""

VAL_FRACTION = 0.2
"""Session J's, reproduced exactly. Changing it would move the validation boundary and make the
Phase 2 validation number incomparable to the Session J baseline it is measured against."""

SHORT_ANSWER_CHARS = 4
"""Answers below this length are almost all bare numerals, where containment is a weak reading of
"this turn states the answer". Not used to skip the filter — used to report what share of every
drop count comes from them, so the filter's noise floor is visible."""

MIN_ANSWER_TOKENS_FOR_SUBSET = 2
"""Token-subset containment is used only for answers with at least this many content tokens, and
the threshold is measured rather than chosen.

Exact substring containment alone reads **4** rank-1 label artifacts; PLAN-R1 cites **9 of 56**,
and the difference is real — five rank-1 turns state the answer in their own words
(`'The music shop on Main St.'` against *"...the music shop on main st where i go..."*). An exact
matcher misses every one, so it would let five turns that answer the question into `deployed_top_k`
labelled as things to reject. Token-subset containment recovers exactly those five and reproduces
the published 9.

It is gated at two tokens because a control says a one-token version is mostly noise. Fired over
every fit turn, gold against non-gold:

    answer content tokens | fires on gold | fires on non-gold | lift
    1                     | 21.9%         | 8.0%  (3,405 turns) |   2.7x
    2                     | 28.3%         | 1.0%              |  27.1x
    3                     | 34.3%         | 0.4%              |  79.0x
    4                     | 34.5%         | 0.2%              | 179.9x
    5+                    |  3.8%         | 0.03%             | 138.6x

At one token the filter is finding the word, not the answer, and would delete thousands of
legitimate negatives. At two it is finding the answer. Exact substring still applies at every
length, so a one-token answer is not unprotected — it is protected by the matcher that does not
have an 8% base rate."""

CLASSES = ("deployed_top_k", "cross_session", "question_echo")


# ---- helpers ----------------------------------------------------------------------------------


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class AnswerMatcher:
    """Does a turn state the gold answer? Two matchers, because one of them is not enough.

    `exact` — whitespace-normalised, case-insensitive substring with alphanumeric lookarounds
    rather than `\\b`. `\\b` is a word-CHARACTER boundary, so it anchors wrongly on answers that
    begin or end with punctuation (`10%`, `3:1`).

    `subset` — every content token of the answer present in the turn, used only above
    `MIN_ANSWER_TOKENS_FOR_SUBSET`. This is the matcher that catches a turn stating the answer in
    its own word order, which is the common case and which exact matching misses entirely. See that
    constant for the control that sets the threshold.

    Which matcher fired is recorded, not merged, so the strict and the loose count stay separable.
    """

    __slots__ = ("exact", "tokens")

    def __init__(self, answer: str) -> None:
        a = norm(answer)
        self.exact = re.compile(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])") if a else None
        toks = {w for w in re.findall(r"[a-z0-9']+", a) if w not in J.STOP}
        self.tokens = toks if len(toks) >= MIN_ANSWER_TOKENS_FOR_SUBSET else None

    def match(self, turn: dict) -> str | None:
        """`"exact"`, `"token_subset"`, or None."""
        if self.exact is not None and self.exact.search(turn["norm"]):
            return "exact"
        if self.tokens is not None and self.tokens <= turn["all_tokens"]:
            return "token_subset"
        return None

    def __bool__(self) -> bool:
        return self.exact is not None or self.tokens is not None


def overlap_key(question_terms: frozenset[str], turn: dict) -> tuple:
    """Rank key for the two question-overlap classes. Total, so the order is reproducible.

    1. content-word intersection with the QUESTION, descending — the same raw-count signal
       `entity_overlap` uses, computed against a different text.
    2. shorter text first. Without this the class collapses into `long_assistant`: a 1,500-word
       assistant turn hits every question term by accident, and that negative already exists in
       Session J's mix. The tiebreak keeps this class about echo rather than length.
    3. turn_id ascending — determinism, never a signal.
    """
    return (-len(question_terms & turn["terms"]), len(turn["text"]), turn["turn_id"])


def build_index(raw: list) -> dict[str, dict[str, dict]]:
    """query_id -> turn_id -> turn record. turn_id mirrors reach_pools/longmemeval exactly."""
    index: dict[str, dict[str, dict]] = {}
    for inst in raw:
        qid = str(inst["question_id"])
        per: dict[str, dict] = {}
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                text = str(turn.get("content", ""))
                normed = norm(text)
                per[f"{sid}-{t_idx}"] = {
                    "turn_id": f"{sid}-{t_idx}",
                    "sid": sid,
                    "idx": t_idx,
                    "role": str(turn.get("role", "?")),
                    "text": text,
                    "norm": normed,
                    "terms": frozenset(J.content_words(text)),
                    # every token, stopwords included -- the answer side is what gets filtered
                    "all_tokens": frozenset(re.findall(r"[a-z0-9']+", normed)),
                    "gold": bool(turn.get("has_answer")),
                }
        index[qid] = per
    return index


def fold_assignment(query_to_sessions: dict[str, list[str]]) -> tuple[set[str], set[str], int]:
    """Session J's train/val split, by CONVERSATION. Reproduced, not imported — J's copy lives
    inside its `main()`. Verified against J's artifact in the manifest rather than trusted."""
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

    ordered = sorted(groups.values(), key=lambda g: min(g))
    total = sum(len(g) for g in ordered)
    val: set[str] = set()
    for group in ordered:
        if len(val) >= VAL_FRACTION * total:
            break
        val |= group
    train = {q for g in ordered for q in g} - val
    return train, val, len(ordered)


# ---- the mine ---------------------------------------------------------------------------------


def mine(classes: tuple[str, ...]) -> tuple[list[dict], dict]:
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    fit_ids, heldout_ids = set(split["fit"]), set(split["heldout"])

    heldout_haystack: set[str] = set()
    for inst in raw:
        if str(inst["question_id"]) in heldout_ids:
            heldout_haystack |= set(inst["haystack_session_ids"])

    index = build_index(raw)

    # ---- the control. Nothing is mined from a ranking that is not the deployed ranking. --------
    pools, pool_stats = load_pools(FIT_POOLS)
    r1 = sum(int(bool(p.gold[SW.shipped_order(p)[0]])) for p in pools.values())
    measured = round(r1 / len(pools), 4)
    if abs(measured - CONTROL_FIT_R1) >= 1e-9:
        raise SystemExit(
            f"REFUSING TO MINE. The shipped-key reconstruction over {FIT_POOLS} reads fit R@1 "
            f"{measured}; the published value is {CONTROL_FIT_R1}. `deployed_top_k` would then be "
            "the top-10 of a different ranker, mined and shipped under the deployed label."
        )
    deployed_order = {qid: [int(i) for i in SW.shipped_order(p)[:DEPLOYED_TOP_K_DEPTH]]
                      for qid, p in pools.items()}

    pairs: list[dict] = []
    excluded_by_haystack_rule: list[str] = []
    no_usable_gold: list[str] = []
    no_pool: list[str] = []
    query_to_sessions: dict[str, list[str]] = {}
    class_counts: Counter = Counter()
    answer_drops: Counter = Counter()
    answer_drops_short: Counter = Counter()
    answer_drops_by_matcher: Counter = Counter()
    answer_drop_turns: dict[str, set[tuple[str, str]]] = {c: set() for c in CLASSES}
    leak_drops: Counter = Counter()
    gold_turn_skips: Counter = Counter()
    class_queries: dict[str, set[str]] = {c: set() for c in CLASSES}
    class_sessions: dict[str, set[tuple[str, str]]] = {c: set() for c in CLASSES}
    same_session_negatives: Counter = Counter()
    answer_lengths: list[int] = []
    pat_by_qid: dict[str, re.Pattern | None] = {}

    for inst in raw:
        qid = str(inst["question_id"])
        if qid not in fit_ids:
            continue
        question = str(inst["question"])
        answer = str(inst.get("answer") or "")
        gold_sessions = set(inst.get("answer_session_ids") or [])

        if gold_sessions & heldout_haystack:
            excluded_by_haystack_rule.append(qid)
            continue

        per_turn = index[qid]
        golds = sorted(
            (t for t in per_turn.values() if t["gold"]),
            key=lambda t: (t["sid"], t["idx"]),
        )
        owned = sorted({t["sid"] for t in golds})
        query_to_sessions[qid] = owned
        if not golds:
            no_usable_gold.append(qid)
            continue

        pat = AnswerMatcher(answer)
        pat_by_qid[qid] = pat
        short_answer = len(norm(answer)) < SHORT_ANSWER_CHARS
        answer_lengths.append(len(norm(answer)))
        question_terms = frozenset(J.content_words(question))

        # ---- the three candidate pools, ranked once per query ---------------------------------
        walks: dict[str, list[dict]] = {}

        if "deployed_top_k" in classes:
            pool = pools.get(qid)
            if pool is None:
                no_pool.append(qid)
            else:
                walk = []
                for i in deployed_order[qid]:
                    tid = pool.candidates[i].turn_id
                    rec = per_turn.get(tid) if tid else None
                    if rec is not None:
                        walk.append(rec)
                walks["deployed_top_k"] = walk

        if "cross_session" in classes:
            walks["cross_session"] = sorted(
                (t for t in per_turn.values() if t["sid"] not in gold_sessions and t["text"].strip()),
                key=lambda t: overlap_key(question_terms, t),
            )

        if "question_echo" in classes:
            walks["question_echo"] = sorted(
                (t for t in per_turn.values() if t["text"].strip()),
                key=lambda t: overlap_key(question_terms, t),
            )

        caps = {
            "deployed_top_k": DEPLOYED_TOP_K_DEPTH,
            "cross_session": CROSS_SESSION_CAP,
            "question_echo": QUESTION_ECHO_CAP,
        }
        per_session_caps = {
            "deployed_top_k": None,
            "cross_session": CROSS_SESSION_MAX_PER_SESSION,
            "question_echo": None,
        }

        for gold in golds:
            for cls in CLASSES:
                walk = walks.get(cls)
                if walk is None:
                    continue
                taken = 0
                by_session: Counter = Counter()
                for cand in walk:
                    if taken >= caps[cls]:
                        break
                    if cand["gold"]:
                        gold_turn_skips[cls] += 1
                        continue
                    how = pat.match(cand)
                    if how is not None:
                        answer_drops[cls] += 1
                        answer_drops_by_matcher[(cls, how)] += 1
                        answer_drop_turns[cls].add((qid, cand["turn_id"]))
                        if short_answer:
                            answer_drops_short[cls] += 1
                        continue
                    if cand["sid"] in heldout_haystack:
                        leak_drops[cls] += 1
                        continue
                    lim = per_session_caps[cls]
                    if lim is not None and by_session[cand["sid"]] >= lim:
                        continue
                    by_session[cand["sid"]] += 1
                    taken += 1
                    same = cand["sid"] == gold["sid"]
                    pairs.append({
                        "query_id": qid,
                        "conversation_id": gold["sid"],
                        "question": question,
                        "positive": gold["text"],
                        "positive_role": gold["role"],
                        "negative": cand["text"],
                        "negative_role": cand["role"],
                        "negative_class": cls,
                        "turn_gap": (cand["idx"] - gold["idx"]) if same else None,
                    })
                    class_counts[cls] += 1
                    class_queries[cls].add(qid)
                    class_sessions[cls].add((qid, cand["sid"]))
                    same_session_negatives[cls] += int(same)

    # ---- what the rank-1 competitor actually is, per failing fit query ------------------------
    #
    # `deployed_top_k` exists to train against the turn that currently BEATS gold, so the number
    # that says whether the class does its job is not its pair count -- it is how many rank-1
    # competitors reached the training set, and how many were label artifacts the filter removed.
    rank1 = {"failing_queries": 0, "rank1_became_a_negative": 0,
             "rank1_dropped_answer_filter": 0, "rank1_dropped_leak_filter": 0}
    rank1_artifacts: list[dict] = []
    for qid in sorted(pat_by_qid):
        pool = pools.get(qid)
        if pool is None:
            continue
        top = pool.candidates[deployed_order[qid][0]]
        if top.is_gold:
            continue
        rank1["failing_queries"] += 1
        rec = index[qid].get(top.turn_id or "")
        if rec is None:
            continue
        how = pat_by_qid[qid].match(rec)
        if how is not None:
            rank1["rank1_dropped_answer_filter"] += 1
            rank1_artifacts.append({"query_id": qid, "turn_id": rec["turn_id"], "matcher": how})
        elif rec["sid"] in heldout_haystack:
            rank1["rank1_dropped_leak_filter"] += 1
        else:
            rank1["rank1_became_a_negative"] += 1

    train_queries, val_queries, n_groups = fold_assignment(query_to_sessions)
    for pair in pairs:
        pair["fold"] = "val" if pair["query_id"] in val_queries else "train"

    # ---- fold agreement with Session J's artifact -------------------------------------------
    j_fold: dict[str, str] = {}
    if SESSION_J_PAIRS.exists():
        for line in io.open(SESSION_J_PAIRS, encoding="utf-8"):
            if line.strip():
                row = json.loads(line)
                j_fold[row["query_id"]] = row["fold"]
    shared = sorted(set(j_fold) & (train_queries | val_queries))
    agree = sum(
        1 for q in shared
        if j_fold[q] == ("val" if q in val_queries else "train")
    )

    j_counts: Counter = Counter()
    for line in (io.open(SESSION_J_PAIRS, encoding="utf-8") if SESSION_J_PAIRS.exists() else []):
        if line.strip():
            j_counts[json.loads(line)["negative_class"]] += 1

    fold_counts: Counter = Counter()
    for pair in pairs:
        fold_counts[(pair["negative_class"], pair["fold"])] += 1

    stats = {
        "_what": (
            "M0c Session M Phase 2 prep — three negative classes Session J's same-session miner "
            "cannot reach. Mined only; nothing trained, nothing shipped."
        ),
        "sources": {
            "split": "tools/split.json",
            "corpus": split["corpus_path"],
            "deployed_ranking": "runs/session-k/fit/ via sweep_reranker_frontier.shipped_order",
            "session_j_baseline": "runs/session-j/training-pairs.jsonl",
        },
        "control": {
            "_why": (
                "deployed_top_k is the deployed competitor set only if the reconstruction is the "
                "deployed ranking. The script refuses to write if this does not match."
            ),
            "fit_r_at_1_reconstructed": measured,
            "fit_r_at_1_published": CONTROL_FIT_R1,
            "pass": True,
            "pools": pool_stats,
        },
        "constants": {
            "DEPLOYED_TOP_K_DEPTH": DEPLOYED_TOP_K_DEPTH,
            "CROSS_SESSION_CAP": CROSS_SESSION_CAP,
            "CROSS_SESSION_MAX_PER_SESSION": CROSS_SESSION_MAX_PER_SESSION,
            "QUESTION_ECHO_CAP": QUESTION_ECHO_CAP,
            "VAL_FRACTION": VAL_FRACTION,
            "SHORT_ANSWER_CHARS": SHORT_ANSWER_CHARS,
            "classes_mined": list(classes),
        },
        "queries": {
            "fit_total": len(fit_ids),
            "excluded_by_heldout_haystack_rule": sorted(excluded_by_haystack_rule),
            "excluded_count": len(excluded_by_haystack_rule),
            "no_usable_gold_turn": sorted(no_usable_gold),
            "no_reconstructed_pool": sorted(no_pool),
            "_no_pool_note": (
                "load_pools drops abstention cases and cases whose gold turn produced no surviving "
                "candidate. deployed_top_k is undefined for those; the other two classes still "
                "cover them, so the classes do not span identical query sets."
            ),
            "with_pairs": len(sorted({p["query_id"] for p in pairs})),
        },
        "per_class": {
            c: {
                "pairs": class_counts[c],
                "queries_covered": len(class_queries[c]),
                "distinct_sessions_drawn_from": len(class_sessions[c]),
                "negatives_from_the_gold_turn_own_session": same_session_negatives[c],
                "train_pairs": fold_counts[(c, "train")],
                "val_pairs": fold_counts[(c, "val")],
            }
            for c in CLASSES if c in classes
        },
        "false_negative_filter": {
            "_what": (
                "a mined negative that states the gold answer is a label error that actively "
                "teaches the wrong thing. Counted at the point of selection: these are candidates "
                "that WOULD have entered the training set."
            ),
            "rule": (
                "exact: whitespace-normalised, case-insensitive containment with alphanumeric "
                f"lookarounds. token_subset: every answer content token present, for answers with "
                f">= {MIN_ANSWER_TOKENS_FOR_SUBSET} content tokens. See MIN_ANSWER_TOKENS_FOR_SUBSET "
                "for the gold-vs-non-gold control that sets that threshold."
            ),
            "dropped_per_class": {c: answer_drops[c] for c in CLASSES if c in classes},
            "dropped_per_class_by_matcher": {
                c: {m: answer_drops_by_matcher[(c, m)] for m in ("exact", "token_subset")}
                for c in CLASSES if c in classes
            },
            "dropped_distinct_turns_per_class": {
                c: len(answer_drop_turns[c]) for c in CLASSES if c in classes
            },
            "_two_units": (
                "dropped_per_class counts PAIRS prevented — the unit that matters for label noise "
                "in the training set, and it is amplified by the ~1.9 gold turns a query has. "
                "dropped_distinct_turns_per_class counts the underlying turns."
            ),
            "dropped_per_class_from_answers_under_4_chars": {
                c: answer_drops_short[c] for c in CLASSES if c in classes
            },
            "_short_answer_caveat": (
                f"{sum(1 for n in answer_lengths if n < SHORT_ANSWER_CHARS)} of "
                f"{len(answer_lengths)} mined fit answers are under {SHORT_ANSWER_CHARS} "
                "characters and mostly bare numerals, where containment is a weak reading of "
                "'this turn states the answer'. Reported separately rather than folded in."
            ),
            "gold_turns_skipped_per_class": {c: gold_turn_skips[c] for c in CLASSES if c in classes},
        },
        "heldout_haystack_leak_filter": {
            "_what": (
                "Session J's registered rule — no training pair may come from a session present in "
                "ANY held-out haystack. It excluded ONE query there because negatives never left "
                "the gold session. Two of these three classes leave it, so the rule now removes "
                "real candidates and the count is the measurement of that."
            ),
            "sessions_in_both_haystacks": 2182,
            "dropped_per_class": {c: leak_drops[c] for c in CLASSES if c in classes},
        },
        "fold_structure": {
            "_what": "Session J's union-find over (query, gold session). Split by CONVERSATION.",
            "conversation_groups": n_groups,
            "train_queries": len(train_queries),
            "val_queries": len(val_queries),
            "agreement_with_session_j": {
                "_why": (
                    "reproducing the logic is not evidence that it reproduced. Every query present "
                    "in both files must land on the same side, or the Phase 2 validation number is "
                    "not comparable to Session J's."
                ),
                "shared_queries": len(shared),
                "same_fold": agree,
                "pass": bool(shared) and agree == len(shared),
            },
        },
        "rank1_competitor": {
            "_what": (
                "the number that says whether deployed_top_k does its job. Fit queries whose rank-1 "
                "is not gold, and what happened to that rank-1 turn."
            ),
            **rank1,
            "rank1_label_artifacts": rank1_artifacts,
            "_artifact_note": (
                "these are cases where the turn that 'beat' gold states the gold answer, so the "
                "loss is a measurement artifact rather than a ranking error. Training against them "
                "as negatives would teach the model to reject a correct answer."
            ),
        },
        "class_balance_against_session_j": {
            "_why": (
                "so the mix is a deliberate choice rather than an accident of the mining rule."
            ),
            "session_j": dict(sorted(j_counts.items())),
            "session_j_total": sum(j_counts.values()),
            "v2": {c: class_counts[c] for c in CLASSES if c in classes},
            "v2_total": len(pairs),
            "combined_total": sum(j_counts.values()) + len(pairs),
        },
        "examples": [],
    }

    # A handful of triples, deterministically chosen: the first pair of each class on the
    # lexicographically first query that class covers.
    for c in CLASSES:
        if c not in classes:
            continue
        for pair in sorted(pairs, key=lambda p: (p["query_id"], p["negative_class"])):
            if pair["negative_class"] == c:
                stats["examples"].append({
                    "negative_class": c,
                    "query_id": pair["query_id"],
                    "fold": pair["fold"],
                    "question": pair["question"],
                    "positive": pair["positive"][:300],
                    "negative": pair["negative"][:300],
                    "negative_role": pair["negative_role"],
                    "turn_gap": pair["turn_gap"],
                    "same_session_as_gold": pair["turn_gap"] is not None,
                })
                break

    return pairs, stats


def serialize(pairs: list[dict]) -> str:
    return "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classes", nargs="+", default=list(CLASSES), choices=list(CLASSES),
                    help="each class is independently toggleable and separately tagged")
    ap.add_argument("--max-inline-mb", type=float, default=20.0,
                    help="above this the pairs file goes to the system temp dir, not runs/")
    ap.add_argument("--merge-session-j", action="store_true",
                    help="also write Session J's 6,898 pairs + these, for a 7-class training file")
    ap.add_argument("--verify-determinism", action="store_true",
                    help="mine twice in-process and compare bytes")
    args = ap.parse_args()

    classes = tuple(c for c in CLASSES if c in set(args.classes))
    pairs, stats = mine(classes)
    body = serialize(pairs)

    if args.verify_determinism:
        again, _ = mine(classes)
        same = serialize(again) == body
        print(f"in-process determinism: {'IDENTICAL' if same else 'DIFFERENT'}")
        if not same:
            return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nbytes = len(body.encode("utf-8"))
    if nbytes > args.max_inline_mb * 1024 * 1024:
        out = Path(tempfile.gettempdir()) / PAIRS_NAME
        where = "SYSTEM TEMP (over the inline size limit)"
    else:
        out = OUT_DIR / PAIRS_NAME
        where = "runs/session-m0c-m"
    out.write_text(body, encoding="utf-8", newline="\n")

    stats["output"] = {
        "pairs_file": str(out).replace("\\", "/"),
        "location": where,
        "bytes": nbytes,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "pairs": len(pairs),
    }

    if args.merge_session_j:
        merged = io.open(SESSION_J_PAIRS, encoding="utf-8").read() + body
        mbytes = len(merged.encode("utf-8"))
        mroot = Path(tempfile.gettempdir()) if mbytes > args.max_inline_mb * 1024 * 1024 else OUT_DIR
        mpath = mroot / "training-pairs-7class.jsonl"
        mpath.write_text(merged, encoding="utf-8", newline="\n")
        stats["output"]["merged_7class_file"] = str(mpath).replace("\\", "/")
        stats["output"]["merged_7class_bytes"] = mbytes

    STATS_PATH.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    # ---- report ---------------------------------------------------------------------------
    print(f"CONTROL  shipped-key fit R@1 {stats['control']['fit_r_at_1_reconstructed']} "
          f"(published {CONTROL_FIT_R1})  PASS")
    print(f"\nmined {len(pairs)} pairs over {stats['queries']['with_pairs']} fit queries\n")
    print(f"  {'class':<18} {'pairs':>7} {'queries':>8} {'ans-drop':>9} {'leak-drop':>10} "
          f"{'same-sess':>10}")
    for c in classes:
        p = stats["per_class"][c]
        print(f"  {c:<18} {p['pairs']:>7} {p['queries_covered']:>8} "
              f"{stats['false_negative_filter']['dropped_per_class'][c]:>9} "
              f"{stats['heldout_haystack_leak_filter']['dropped_per_class'][c]:>10} "
              f"{p['negatives_from_the_gold_turn_own_session']:>10}")
    print()
    rk = stats["rank1_competitor"]
    print(f"  rank-1 competitor: {rk['failing_queries']} failing fit queries -> "
          f"{rk['rank1_became_a_negative']} rank-1s entered as negatives, "
          f"{rk['rank1_dropped_answer_filter']} dropped as label artifacts, "
          f"{rk['rank1_dropped_leak_filter']} dropped by the leak rule")
    print()
    j = stats["class_balance_against_session_j"]
    print(f"  Session J: {j['session_j_total']} pairs in 4 classes  "
          f"({', '.join(f'{k} {v}' for k, v in j['session_j'].items())})")
    print(f"  v2:        {j['v2_total']} pairs in {len(classes)} classes   "
          f"combined {j['combined_total']}")
    print()
    q = stats["queries"]
    print(f"  excluded by the held-out-haystack rule: {q['excluded_by_heldout_haystack_rule'] or 'none'} "
          f"({q['excluded_count']} of {q['fit_total']} fit queries)")
    print(f"  no usable gold turn:                   {len(q['no_usable_gold_turn'])}")
    print(f"  no reconstructed pool (deployed_top_k only): {len(q['no_reconstructed_pool'])}")
    f = stats["fold_structure"]
    a = f["agreement_with_session_j"]
    print(f"  folds: train {f['train_queries']} / val {f['val_queries']} over "
          f"{f['conversation_groups']} conversation groups")
    print(f"  fold agreement with Session J: {a['same_fold']}/{a['shared_queries']} "
          f"{'PASS' if a['pass'] else 'FAIL'}")
    print(f"\nWROTE {out}  ({nbytes / 1024 / 1024:.1f} MB, {where})")
    print(f"WROTE {STATS_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
