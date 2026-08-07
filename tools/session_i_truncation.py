"""Session I, Phase 1.2 — the truncation reachability grid. ADR-010 applied to arm 1.

**The trap this exists to avoid.** The shipped stage pins `MAX_SEQ_LEN = 256`
(`crates/marlowe-memory/src/rerank.rs`). Phase 0.2 measured the median gold turn at 70 word pieces
and the rank-1 distractor on failures at 131 median / 406 p75 / 654 p95. A +/-2 context window is
five turns. Run at 256, HuggingFace `longest_first` truncation pops from the longer sequence -- the
document -- **from the end**, so a `+k` suffix is discarded first and on a long window the gold turn
itself is cut. Arm 1 would then read "context does not help" for a reason that has nothing to do
with context.

ADR-010's rule is that an arm must be shown able to move the metric before a band is registered on
it. For arm 1 that means: **at this window and this sequence length, does the gold turn survive
tokenization at all?** A cell below the threshold is UNREACHABLE and is not swept.

**Context is built the way the BINARY could build it, not the way the corpus makes convenient.**
Neighbours are taken by `occurred_at_ms` order over the case's turns, clamped at a 30-minute gap --
the same rule `reach_session_h_pruning.derived_keys` uses, and the only structure the store carries
(`MemoryEntry.occurred_at_ms`, one entry per turn). Using the raw corpus's `(sid, turn_index)`
adjacency would be easier and would be a *different* neighbourhood than the shipped path can
reconstruct: the eighth instance of two sides silently disagreeing, discovered after shipping.

No inference runs here. This is token counting, and it is cheap.

    python tools/session_i_truncation.py
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np

from reach_pools import REPO, SPLIT_PATH, turn_texts
from session_h_pools import gated_fit_pools
from session_i_rerankers import MODELS_DIR, manifest

OUT_PATH = REPO / "runs" / "session-i" / "truncation-grid.json"

SESSION_GAP_MS = 1_800_000          # 30 minutes, frozen in Session H
WINDOWS = {"0": (0, 0), "-1/+1": (1, 1), "-2/+2": (2, 2), "-3/+3": (3, 3),
           "-2/+1": (2, 1), "-1/+2": (1, 2)}
SEQ_LENS = (256, 384, 512, 1024)
REACHABLE_AT = 0.98                 # a cell below this cannot be attributed to the mechanism
JOIN = "\n"

# Per-NEIGHBOUR word-piece cap. The gold turn is never capped; only its context is.
#
# This axis is not decoration. The first run of this grid measured a +/-1 window at a median of
# ~715 word pieces, because gold is 87.7% user-authored (Phase 0.2) and a user turn's neighbours
# are long assistant turns. An uncapped window does not fit ANY sequence length these models
# support, so without this axis arm 1 has no reachable cell at all and could not be swept.
# Capping the context and never the candidate is also the rule that stays implementable in Rust.
CAPS: tuple[int | None, ...] = (None, 32, 64, 128)


def case_turns() -> dict[str, list[tuple[str, int, str]]]:
    """query_id -> [(turn_id, occurred_at_ms, text)], in occurred_at_ms order.

    Every turn of the case, not just the scored candidates: the binary's store holds one entry per
    ingested turn (`ingest.rs` writes 1:1), so a neighbour that never became a candidate is still
    reachable there and must be reachable here.
    """
    from marlowe_eval.datasets import timeparse

    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    out: dict[str, list[tuple[str, int, str]]] = {}
    for inst in raw:
        qid = str(inst["question_id"])
        rows = []
        for s_idx, (sid, session, date) in enumerate(zip(
                inst["haystack_session_ids"], inst["haystack_sessions"], inst["haystack_dates"])):
            at = timeparse.parse(date, dataset="longmemeval", where=f"{qid}[{s_idx}]")
            for t_idx, turn in enumerate(session):
                rows.append((f"{sid}-{t_idx}", at + t_idx * 1000, str(turn.get("content", ""))))
        rows.sort(key=lambda r: (r[1], r[0]))
        out[qid] = rows
    return out


def window_for(rows, i: int, before: int, after: int) -> tuple[list[str], int]:
    """The context window around row `i`, clamped at a >30-minute gap. Returns (texts, gold_pos).

    Clamping is what makes this the binary's neighbourhood rather than the corpus's: the store has
    no session field, so contiguity in `occurred_at_ms` is the only boundary available to it.
    """
    lo = i
    for _ in range(before):
        if lo == 0 or rows[lo][1] - rows[lo - 1][1] > SESSION_GAP_MS:
            break
        lo -= 1
    hi = i
    for _ in range(after):
        if hi == len(rows) - 1 or rows[hi + 1][1] - rows[hi][1] > SESSION_GAP_MS:
            break
        hi += 1
    return [r[2] for r in rows[lo:hi + 1]], i - lo


def main() -> int:
    pools = gated_fit_pools()
    texts = turn_texts()
    turns = case_turns()
    index = {q: {t[0]: k for k, t in enumerate(rows)} for q, rows in turns.items()}

    # One tokenizer per DISTINCT tokenizer file. The four MiniLM models share one digest, so the
    # grid is computed five times rather than nine.
    from tokenizers import Tokenizer
    by_digest: dict[str, tuple[str, object, list[str]]] = {}
    max_seq: dict[str, int] = {}
    for m in manifest()["models"]:
        d = m["digests"]["tokenizer.json"]
        if d not in by_digest:
            tok = Tokenizer.from_file(str(MODELS_DIR / m["name"] / "tokenizer.json"))
            by_digest[d] = (m["name"], tok, [])
        by_digest[d][2].append(m["name"])
        # The MINIMUM across models sharing a tokenizer: a cell is only sweepable for a model that
        # can actually run that sequence length, and the four MiniLM depths all cap at 512.
        max_seq[d] = min(max_seq.get(d, 10 ** 9), m["max_seq"])

    print(f"Fit split: {len(pools)} pools. {len(by_digest)} distinct tokenizers across "
          f"{sum(len(v[2]) for v in by_digest.values())} models.\n")

    grid: dict[str, dict] = {}
    prefix_violations = 0

    for digest, (rep, tok, shared) in by_digest.items():
        family_max_seq = max_seq[digest]
        tok.no_truncation()
        tok.no_padding()
        per_model: dict[str, dict] = {}

        def capped(text: str, cap: int | None) -> str:
            """The first `cap` word pieces of `text`, as text.

            Cut at the token's own character offset rather than by decoding and re-encoding: a
            decode/encode round trip is not the identity, and the boundary would move by a token
            or two in a way that is invisible in the output.
            """
            if cap is None:
                return text
            enc = tok.encode(text, add_special_tokens=False)
            if len(enc.ids) <= cap:
                return text
            return text[: enc.offsets[cap - 1][1]]

        for wname, (before, after) in WINDOWS.items():
            per_cap: dict[str, dict] = {}
            for cap in CAPS:
                doc_lens, cases = [], []
                for pool in pools.values():
                    gold_ids = [c.turn_id for c in pool.candidates if c.is_gold and c.turn_id]
                    if not gold_ids:
                        continue
                    rows = turns[pool.query_id]
                    i = index[pool.query_id].get(gold_ids[0])
                    if i is None:
                        continue
                    win, gpos = window_for(rows, i, before, after)
                    # The candidate is never capped; only its context is.
                    win = [t if k == gpos else capped(t, cap) for k, t in enumerate(win)]
                    doc_full = JOIN.join(win)
                    doc_upto = JOIN.join(win[:gpos + 1])

                    # add_special_tokens=False on BOTH sides. `kept` below counts only tokens
                    # carrying sequence_id 1 -- the document's own content -- so a `need` that
                    # included [CLS] and [SEP] would be inflated by 2-3 and the comparison would be
                    # between different units. That defect read 0.0000 survival at window 0, where
                    # the document IS the gold turn and survival is 1.0 by construction.
                    full_ids = tok.encode(doc_full, add_special_tokens=False).ids
                    upto_ids = tok.encode(doc_upto, add_special_tokens=False).ids
                    # The prefix property is CHECKED, not assumed: a joined prefix tokenizes as a
                    # prefix of the whole only if the join point is a hard token boundary. It is,
                    # for WordPiece and for SentencePiece on a newline -- but "it is" is how this
                    # project acquires bugs.
                    if full_ids[: len(upto_ids)] != upto_ids:
                        prefix_violations += 1
                    doc_lens.append(len(full_ids))
                    cases.append((pool.question, doc_full, len(upto_ids)))

                entry = {
                    "doc_wordpieces": {
                        "median": float(np.median(doc_lens)),
                        "p75": float(np.percentile(doc_lens, 75)),
                        "p95": float(np.percentile(doc_lens, 95)),
                        "max": int(max(doc_lens)),
                    },
                    "by_seq_len": {},
                }
                for L in SEQ_LENS:
                    tok.enable_truncation(max_length=L)
                    survived = 0
                    for question, doc_full, need in cases:
                        enc = tok.encode(question, doc_full)
                        kept = sum(1 for s in enc.sequence_ids if s == 1)
                        survived += kept >= need
                    tok.no_truncation()
                    rate = survived / len(cases)
                    # A sequence length above the model's own positional limit is not a cell that
                    # scores worse -- it is a cell that cannot be run. Reporting its survival as
                    # "reachable" would register a band on a configuration no model can execute.
                    applicable = L <= family_max_seq
                    entry["by_seq_len"][str(L)] = {
                        "gold_survives_intact": round(rate, 4),
                        "applicable": applicable,
                        "reachable": bool(applicable and rate >= REACHABLE_AT),
                    }
                per_cap["uncapped" if cap is None else str(cap)] = entry
            per_model[wname] = per_cap

        grid[rep] = {"tokenizer_sha256": digest, "shared_by": shared,
                     "max_seq_supported": family_max_seq, "windows": per_model}

    print("GOLD SURVIVES TOKENIZATION INTACT  (fraction of fit cases)")
    print("A cell below %.2f is UNREACHABLE: arm 1 could not move the metric there, and any\n"
          "reading from it would measure truncation rather than context.\n" % REACHABLE_AT)
    caps = ["uncapped" if c is None else str(c) for c in CAPS]
    for rep, g in grid.items():
        print(f"  {rep}   (shared by {len(g['shared_by'])} model(s), max_seq {g['max_seq_supported']})")
        print(f"    {'window':>7} {'cap':>8} {'doc med':>8} {'doc p95':>8} " +
              "".join(f"{'seq ' + str(L):>11}" for L in SEQ_LENS))
        for wname in WINDOWS:
            for cap in caps:
                e = g["windows"][wname][cap]
                row = (f"    {wname:>7} {cap:>8} {e['doc_wordpieces']['median']:>8.0f} "
                       f"{e['doc_wordpieces']['p95']:>8.0f} ")
                for L in SEQ_LENS:
                    c = e["by_seq_len"][str(L)]
                    mark = '  ' if c['reachable'] else (' X' if c['applicable'] else ' -')
                    row += f"{c['gold_survives_intact']:>9.4f}{mark}"
                print(row)
        print()

    reachable = {
        rep: sorted(
            (w, cap, L)
            for w in WINDOWS for cap in caps for L in SEQ_LENS
            if g["windows"][w][cap]["by_seq_len"][str(L)]["reachable"]
        )
        for rep, g in grid.items()
    }
    print("SWEEPABLE CELLS for arm 1 (window, neighbour cap, seq len), per tokenizer family:")
    for rep, cells in reachable.items():
        if not cells:
            print(f"  {rep:>36}  NONE -- arm 1 has no reachable cell and is NOT SWEPT")
            continue
        print(f"  {rep:>36}  {len(cells)} cells")
        for w, cap, L in cells:
            if w == "0":
                continue  # window 0 is the control, reachable by construction
            print(f"  {'':>36}    window {w:>6}  cap {cap:>8}  seq {L}")

    if prefix_violations:
        print(f"\nWARNING: {prefix_violations} cases where the joined prefix did not tokenize as a "
              "prefix of the whole. The survival figures for those are approximate.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "_what": "Session I Phase 1.2 -- truncation reachability. ADR-010 applied to arm 1.",
        "split": "fit",
        "cases": len(pools),
        "context_rule": (
            "neighbours by occurred_at_ms order over ALL of the case's turns, clamped at a "
            "30-minute gap -- the rule the binary can reconstruct from MemoryEntry.occurred_at_ms, "
            "NOT the corpus's (sid, turn_index) adjacency."
        ),
        "reachable_threshold": REACHABLE_AT,
        "prefix_property_violations": prefix_violations,
        "grid": grid,
        "sweepable_cells": reachable,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
