#!/usr/bin/env python3
"""PreToolUse hook: guard the brief §13 do-not-touch boundary.

CLAUDE.md lists six components the agent may not modify. Until 2026-08-03 that list claimed
to be "enforced by PreToolUse hooks" and was not — no hooks existed at all. This is the hook.

**What it does and does not do.** It does not deny outright; it forces an explicit human
decision by returning `permissionDecision: "ask"` with a reason naming the rule. The boundary
is against the agent changing safety machinery on its own initiative, not against the project
ever evolving it. A human who reads the reason and approves has made the decision the
boundary exists to require.

**Why paths and not concepts.** A matcher needs something concrete. Five of the six CLAUDE.md
entries name components that do not exist yet (no permission layer, no path scoping, no audit
logging, no trust ledger, no persona artifact). As each lands, add its path here — the entry
is the enforcement, and a component with no entry is unguarded regardless of what the list
says.

Building a listed component in its assigned milestone is not "touching" it. M0b Session A
wrote `trust.rs` for the first time; that was the milestone's scope. The guard exists for what
comes after.
"""

from __future__ import annotations

import json
import sys

# Suffix-matched against the forward-slash-normalized absolute path. Suffixes rather than
# absolute paths so the guard survives the repo being cloned elsewhere.
PROTECTED = {
    "crates/marlowe-memory/src/trust.rs": (
        "memory provenance and trust-class propagation (brief §13). This is what defeats "
        "memory laundering: worst-case propagation over the full lineage, and the rule that "
        "origin.actor may reject a write but never elevate its trust. HP6 and K3 both rest "
        "on it"
    ),
    "crates/marlowe-journal/src/signature.rs": (
        "the write-time integrity binding and the hash chain (brief §13, audit logging). "
        "Invariant 7 rests on it, and CONTRACTS.md §1 pins the signed tuple"
    ),
    "crates/marlowe-journal/src/journal.rs": (
        "the only write path (brief §13, audit logging). There is no unsigned variant, which "
        "is how the 0% unsigned-write ASR target (K3) is structural rather than filtered"
    ),
}

# Directory prefixes, matched anywhere in the normalized path.
PROTECTED_DIRS = {
    "/persona/": (
        "the persona artifact (brief §13). It lives in the stable tier, is versioned, and is "
        "not configurable — see 04-addendum-persona.md"
    ),
}


def reason_for(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    for suffix, why in PROTECTED.items():
        if normalized.endswith(suffix):
            return why
    for fragment, why in PROTECTED_DIRS.items():
        if fragment in normalized:
            return why
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # A hook that cannot parse its input must not block work. It has no basis for a
        # decision, so it says nothing and the normal permission flow applies.
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not path:
        return 0

    why = reason_for(str(path))
    if why is None:
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": (
                        f"BRIEF §13 BOUNDARY — {path} is {why}.\n\n"
                        "CLAUDE.md lists this among the components the agent may not modify. "
                        "Approve only if you have decided this change is intended; a change "
                        "here should come with a DECISIONS.md entry saying why."
                    ),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
