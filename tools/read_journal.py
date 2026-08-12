#!/usr/bin/env python
"""Read the signed journal directly, instead of asking Marlowe what it remembers.

**Why this exists, and why it is committed rather than living in a scratchpad.**

Asking the running agent what it remembers returns a *capability report*: the model's
description of a mechanism, not a measurement of that mechanism's output. The same family as
`get_providers()` reporting which providers were *registered* rather than where the nodes
*ran*. The journal is the only place that records what was actually written, with the trust
class the harness derived at write time — so it is the only instrument that can answer
"what did this run put in memory, and at what class" without the answer routing through the
thing under test.

M2 Session D built this, left it in a scratchpad, and it was gone by Session E. This is the
second build. It is in `tools/` so there is not a third.

**It opens the database read-only and verifies nothing.** Signature-chain verification is
`Journal::open`'s job and duplicating it here would be a second implementation of the check
-- the exact shape this project warns about. If you need the chain verified, start the daemon
and read its refusal. This tool answers "what is in the log", which is a different question,
and it deliberately still answers it on a log whose chain is broken.

Usage
-----
    python tools/read_journal.py                          # default profile, memory events
    python tools/read_journal.py --profile-root <DIR>     # a scratch profile
    python tools/read_journal.py --kinds all              # every event kind
    python tools/read_journal.py --kinds permission_decision
    python tools/read_journal.py --since-seq 400 --json
    python tools/read_journal.py --list-kinds             # what is actually in this log

`--kinds memory` (the default) is the Session D question: every `memory_written` and
`memory_write_rejected` with its trust class. `--kinds security` adds the adjudicator's
decisions, which is what a blast-radius measurement reads.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

JOURNAL_DB = "journal.db"

# Named groups, so a caller asks for a question rather than remembering wire spellings.
#
# **These are the spellings `--list-kinds` reports on a real log, not the `EventKind` variant
# names.** The first draft of this file guessed them from the Rust enum and got three wrong:
# the kind is `permission_decided`, not `permission_decision`, and the tool pair is
# `tool_requested`/`tool_completed`, not `tool_called`. Every one of those would have queried
# an empty set and printed "0 events" -- a confident, clean, entirely wrong answer, which is
# why `--list-kinds` exists and why an empty result prints the log's total below.
GROUPS: dict[str, tuple[str, ...]] = {
    "memory": ("memory_written", "memory_write_rejected", "memory_injected"),
    "security": (
        "memory_written",
        "memory_write_rejected",
        "permission_decided",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "egress_blocked",
        "trust_floor_latched",
        "tool_requested",
        "tool_failed",
        "run_spawned",
    ),
    "all": (),
}

# Payload keys worth pulling to the front of a line, in priority order. A payload is
# free-form JSON the journal does not interpret, so this is presentation only -- anything
# not listed here still appears in the trailing dump under --verbose or --json.
HIGHLIGHT = (
    "trust",
    "trust_class",
    "class",
    "floor",
    "blocks_composed_targets",
    "outcome",
    "reason",
    "tool",
    "verb",
    "scope",
    "text",
    "id",
    "why",
)


def default_profile_root() -> Path:
    """Mirror `marlowe::agent::default_profile_root`.

    Restated rather than imported because this is Python reading a Rust program's data
    directory. If the Rust side moves, this prints a path that does not exist -- which is a
    visible failure, unlike a silently different default.
    """
    for var in ("LOCALAPPDATA", "XDG_DATA_HOME", "HOME"):
        base = os.environ.get(var)
        if base:
            return Path(base) / "marlowe" / "default-profile"
    import tempfile

    return Path(tempfile.gettempdir()) / "marlowe" / "default-profile"


def open_readonly(db: Path) -> sqlite3.Connection:
    """Read-only, and it must fail rather than create.

    `sqlite3.connect` on a missing path creates an empty database and every query then
    returns nothing -- a clean, confident, entirely wrong answer of "no memories were
    written". The URI form with mode=ro refuses instead, which is the load-time-error
    preference applied to an instrument.
    """
    if not db.exists():
        raise SystemExit(f"no journal at {db}\n(is --profile-root right? the daemon creates it on first start)")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def render_payload(payload: str, verbose: bool) -> str:
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return payload if verbose else payload[:120]
    if not isinstance(obj, dict):
        return json.dumps(obj)

    parts = []
    seen = set()
    for key in HIGHLIGHT:
        if key in obj:
            parts.append(f"{key}={_short(obj[key], verbose)}")
            seen.add(key)
    if verbose:
        for key in sorted(obj):
            if key not in seen:
                parts.append(f"{key}={_short(obj[key], True)}")
    elif len(obj) > len(seen):
        parts.append(f"(+{len(obj) - len(seen)} more)")
    return "  ".join(parts) if parts else "{}"


def _short(value: object, verbose: bool) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    limit = 400 if verbose else 90
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile-root", type=Path, default=None, help="defaults to the daemon's own profile")
    p.add_argument(
        "--kinds",
        default="memory",
        help="a group (memory, security, all) or a comma-separated list of exact event kinds",
    )
    p.add_argument("--since-seq", type=int, default=0)
    p.add_argument("--limit", type=int, default=0, help="0 means no limit")
    p.add_argument("--run", default=None, help="only this run id")
    p.add_argument("--session", default=None, help="only this session id")
    p.add_argument("--json", action="store_true", help="one JSON object per line, payload intact")
    p.add_argument("--verbose", action="store_true", help="every payload key, longer values")
    p.add_argument("--list-kinds", action="store_true", help="count each kind present, then exit")
    args = p.parse_args()

    root = args.profile_root or default_profile_root()
    conn = open_readonly(root / JOURNAL_DB)

    if args.list_kinds:
        rows = conn.execute(
            "SELECT kind, COUNT(*), MIN(seq), MAX(seq) FROM journal GROUP BY kind ORDER BY COUNT(*) DESC"
        ).fetchall()
        print(f"{'kind':<28} {'count':>7}  {'first':>7}  {'last':>7}")
        for kind, n, lo, hi in rows:
            print(f"{kind:<28} {n:>7}  {lo:>7}  {hi:>7}")
        return 0

    group = GROUPS.get(args.kinds)
    kinds = group if group is not None else tuple(k.strip() for k in args.kinds.split(",") if k.strip())

    sql = "SELECT seq, ts, session_id, run_id, actor, kind, payload FROM journal WHERE seq > ?"
    params: list[object] = [args.since_seq]
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        params.extend(kinds)
    if args.run:
        sql += " AND run_id = ?"
        params.append(args.run)
    if args.session:
        sql += " AND session_id = ?"
        params.append(args.session)
    sql += " ORDER BY seq"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    rows = conn.execute(sql, params).fetchall()

    if args.json:
        for seq, ts, session, run, actor, kind, payload in rows:
            try:
                parsed = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                parsed = payload
            print(
                json.dumps(
                    {
                        "seq": seq,
                        "ts": ts,
                        "session": session,
                        "run": run,
                        "actor": actor,
                        "kind": kind,
                        "payload": parsed,
                    }
                )
            )
        return 0

    print(f"# {root / JOURNAL_DB}")
    print(f"# {len(rows)} event(s), kinds={args.kinds}")
    if not rows:
        # An empty result is the answer that most needs distinguishing from a broken query,
        # because "nothing was written" and "nothing matched" read identically.
        total = conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
        print(f"# the log holds {total} event(s) in total -- try --list-kinds")
        return 0

    print(f"{'seq':>6}  {'kind':<24} {'actor':<22} {'run':<12} payload")
    for seq, _ts, _session, run, actor, kind, payload in rows:
        run_s = (run or "-")[:12]
        print(f"{seq:>6}  {kind:<24} {(actor or '-'):<22} {run_s:<12} {render_payload(payload, args.verbose)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
