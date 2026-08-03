"""A minimal conforming CONTRACTS.md section 4 target, for proving the wire.

**This is a transport fixture. It is not a memory system and must never be described as
one.** It exists so `exec://` can be shown to work before M0b exists, and so a transport
defect is distinguishable from an implementation defect afterwards.

It lives outside `eval/` on purpose. `eval/` is the scoreboard; a fixture that exercises the
harness's own transport is not part of it, and keeping it here holds the eval/ diff for the
subprocess transport to exactly two files.

What it does:

  ingest    writes one memory per turn, derives effective trust from `origin.channel`
            through a table that is total over the closed set with no default
  retrieve  always abstains, `no_candidates`
  answer    always abstains, with the abstaining retrieval embedded

**Expected to FAIL the clock probe**, with `fail_no_time_dependence`. That is correct and is
not a transport bug: the probe asks whether output moves across a year of synthetic time, and
a fixture with no maturation and no stored state cannot move. Section 4.3 is explicit that an
implementation with no observable time dependence deserves to fail, so the fixture is not
given a fake one to make a number look better.

    python tools/echo_target.py --profile-root <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

CONTRACT_VERSION = "1.0"

# CONTRACTS.md section 3.3 / section 4.6. Total over the closed channel set, with NO default
# arm. An unrecognized channel raises, and the caller turns that into a section 4.0.4 class A
# `malformed_body` -- it is never mapped to a trust class.
#
# This is the rule section 4.6 states in as many words: "an unrecognized value is a load-time
# error on both sides. It is never mapped to a default." A catch-all here would let the
# laundering suite pass while measuring nothing, and if the default were trusted it would
# hide the failure while actively causing it.
TRUST_BY_CHANNEL = {
    "terminal": "user_asserted",
    "voice": "user_asserted",
    "messaging": "untrusted_content",
    "email": "untrusted_content",
    "web": "untrusted_content",
    "mcp": "untrusted_content",
    "tool_output": "agent_observed",
    "file": "untrusted_content",
}


class MalformedBody(Exception):
    """Section 4.0.4 class A: the request was bad."""


def derive_trust(channel: str) -> str:
    try:
        return TRUST_BY_CHANNEL[channel]
    except KeyError:
        raise MalformedBody(
            f"channel {channel!r} is outside the closed set in section 4.6; it is a "
            "load-time error and is never mapped to a default"
        ) from None


def handle_ingest(body: dict) -> dict:
    written = []
    for index, turn in enumerate(body.get("turns", [])):
        origin = turn.get("origin") or {}
        trust = derive_trust(origin.get("channel", ""))
        written.append(
            {
                "turn_id": turn["turn_id"],
                # Ids are derived from the session and turn, never from a timestamp: the
                # clock probe shifts every supplied time by ten years and compares ids.
                "memory_ids": [f"m-{body['session_id']}-{index}"],
                "effective_trust": trust,
            }
        )
    return {
        "contract_version": CONTRACT_VERSION,
        "session_id": body["session_id"],
        "written": written,
        "rejected": [],
        "cost": {"ingest_tokens": 0, "latency_ms": {"total": 0}},
    }


def abstaining_retrieval(query_id: str) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "query_id": query_id,
        "abstained": True,
        "abstention_reason": "no_candidates",
        "injected": [],
        "considered": 0,
        "gate": {"version": "echo-fixture-no-gate", "threshold": 0.0, "adaptive": False},
        "cost": {"retrieval_tokens": 0, "latency_ms": {"total": 0}},
    }


def handle_retrieve(body: dict) -> dict:
    return abstaining_retrieval(body["query_id"])


def handle_answer(body: dict) -> dict:
    query_id = body["query_id"]
    return {
        "contract_version": CONTRACT_VERSION,
        "query_id": query_id,
        # answered:false requires abstained:true, and an abstention requires an empty
        # grounded_in. Section 4.7 makes both of those protocol errors if violated.
        "answered": False,
        "answer": None,
        "abstained": True,
        "abstention_reason": "no_candidates",
        "grounded_in": [],
        "retrieval": abstaining_retrieval(query_id),
        "cost": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "retrieval_tokens": 0,
            "latency_ms": {"total": 0},
        },
    }


HANDLERS = {"ingest": handle_ingest, "retrieve": handle_retrieve, "answer": handle_answer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Required, and required to be empty: a target that silently reuses a populated root
    # lets state leak between the harness's spawns, and the clock probe alone spawns four.
    parser.add_argument("--profile-root", required=True)
    args = parser.parse_args(argv)

    root = args.profile_root
    os.makedirs(root, exist_ok=True)
    if os.listdir(root):
        print(f"profile root {root!r} is not empty; refusing to reuse state", file=sys.stderr)
        return 2

    # Section 4.0.2: binary/raw stdio. Text mode would translate the LF terminator on
    # Windows into CRLF, which section 4.0.2 makes a protocol error -- the fixture would
    # then fail the harness's own check for reasons that have nothing to do with the target.
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for raw in stdin:
        line = raw.rstrip(b"\n")
        if not line:
            continue
        frame = json.loads(line.decode("utf-8"))
        op = frame.get("op")
        try:
            if op not in HANDLERS:
                out = {"op": op, "error": {"kind": "unknown_op", "detail": str(op)}}
            else:
                out = {"op": op, "body": HANDLERS[op](frame["body"])}
        except MalformedBody as exc:
            out = {"op": op, "error": {"kind": "malformed_body", "detail": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - class B is a result, not a crash
            # Section 4.0.4 class B: the implementation failed on a well-formed request.
            # Reported as a result so the harness scores the unit and continues, rather
            # than dying and making a recoverable bug look like a crash.
            out = {"op": op, "error": {"kind": "internal_error", "detail": repr(exc)}}

        stdout.write(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        stdout.write(b"\n")
        # Section 4.0.2: flush after each response frame. A response sitting in a buffer is
        # indistinguishable from a hang.
        stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
