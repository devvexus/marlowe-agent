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
    # ── landed in M2 Session A ────────────────────────────────────────────────────────────
    "crates/marlowe-permission/src/adjudicate.rs": (
        "the permission and approval layer (brief §13). ADR-002 removed the kernel backstop, "
        "so this is the wall rather than the first of two: the (action, target) split, the "
        "path-scope routing and the tier decision all live here"
    ),
    "crates/marlowe-permission/src/taint.rs": (
        "the permission layer's fail-closed provenance lookup (brief §13). An untracked "
        "argument reads as UntrustedContent; a default the other way inverts the security "
        "property while looking like tidy code"
    ),
    "crates/marlowe-permission/src/egress.rs": (
        "egress allowlisting (brief §13, path scoping and egress rules). Deny-by-default per "
        "run, and one of the three mechanisms that lets Inert reads skip the target check"
    ),
    "crates/marlowe-loop/src/profile.rs": (
        "the capability profile's load-time invariants (brief §13, the permission layer). "
        "`reads_untrusted && !exposed_tools.is_empty()` is §8.2's structural trifecta break"
    ),
    # -- landed in M2 Session C3 (ADR-052) --------------------------------------------------
    "crates/marlowe-daemon/src/mcp.rs": (
        "where an MCP tool result acquires its trust class (brief 13, memory provenance and "
        "trust-class propagation). ADR-052 condition 1: the SERVER is trusted because the user "
        "installed it, the OUTPUT is UntrustedContent unconditionally. This is layer 1's entry "
        "point for MCP -- `condense_batch` triggers on the trust class, not the tool name, so "
        "changing this one field is how MCP results would stop being quarantined at all, with "
        "nothing else in the tree looking different"
    ),
    "crates/marlowe-tools/src/pin.rs": (
        "the description pin (brief 13, the permission and approval layer). ADR-052 section 4: "
        "ADR-052's whole argument is that the user inspected what they installed, and this is "
        "what keeps that a TRUE statement rather than a historical one when a live-fetched tool "
        "list changes under an approved name"
    ),
    "crates/marlowe-loop/src/steer.rs": (
        "the one door a steer comes through (ADR-054). A steer is the ONLY channel that writes "
        "new strings into `UserAsserted` in a run whose floor has already latched, so whoever can "
        "widen this can hand a poisoned run a target it would otherwise refuse. The cap and the "
        "sanitiser here are the whole of that check"
    ),
    # -- landed in M3 Session B3 (M3-D3) ----------------------------------------------------
    "crates/marlowe-daemon/src/memory.rs": (
        "where a belief that arrived from OUTSIDE acquires its trust class (brief 13, memory "
        "provenance and trust-class propagation). `DaemonMemory::ingest_external` is the only "
        "non-circular taint source in the product: `remember` writes at "
        "`min(AgentInferred, run_floor)` and can never produce the FIRST untrusted belief, so "
        "everything layer 3 latches on has to enter here. The class is derived from "
        "`content.channel` by `trust_for_channel` and RETURNED, never supplied -- a caller that "
        "could name the class would be the security boundary. This file also derives the belief "
        "id from the channel's pinned wire spelling, so a change here moves identities as well "
        "as classes. It has no caller today (ADR-062); guarding it before it gains one is the "
        "point -- instance #14 is what a guard added after the fact costs"
    ),
    "crates/marlowe-loop/src/driver.rs": (
        "THE LOOP'S WHOLE PORT SURFACE, and the brief 13 subject inside it is `MemoryHost` and "
        "`ExternalContent` specifically -- memory provenance and trust-class propagation, pinned "
        "at CONTRACTS.md 12.1. THE FILE IS WIDER THAN THE BOUNDARY: it also declares `ModelStep`, "
        "`ToolHost`, `ToolBody`, `ClockSource`, `TurnSink`, `ApprovalGate` and a dozen more, and "
        "most edits to it will be ordinary loop work rather than a boundary crossing. That is "
        "said here on purpose. A banner that fires on everything says nothing at the moment it "
        "matters (instance #15), so READ WHICH TYPE IS BEING CHANGED before approving: if it is "
        "not the memory port, this prompt is noise and the honest answer is yes. The memory port "
        "is the part that cannot be defended anywhere else -- `MemoryHost::remember` takes the "
        "run's "
        "latched floor as a REQUIRED parameter and `ingest_external` takes an origin and returns "
        "the derived class: both are ADR-038's whole content, and both are enforced by the "
        "SIGNATURE rather than by any check inside an implementation. Dropping `run_floor`, or "
        "letting `ExternalContent` carry a `TrustClass` instead of a `Channel`, would open the "
        "laundering path in a way no implementation test could see -- every host would still "
        "pass its own tests"
    ),
    "crates/marlowe-loop/src/provenance.rs": (
        "argument provenance (brief §13, the permission layer). ADR-023: the harness computes "
        "taint from the context window, and a model that could label its own arguments "
        "trusted would be the security boundary"
    ),
}

# Directory prefixes, matched anywhere in the normalized path.
#
# Path scoping is a DIRECTORY entry rather than a file list, and that is a lesson rather than a
# style choice. It was `crates/marlowe-permission/src/scope.rs` until M2 Session B split it into
# `scope/{mod,request,glob,walk}.rs`, at which point the entry named a file that no longer
# existed and the whole component was silently unguarded. Nothing reported it. A directory entry
# survives a split; `--self-check` below catches the case where nothing survives.
PROTECTED_DIRS = {
    "/persona/": (
        "the persona artifact (brief §13). It lives in the stable tier, is versioned, and is "
        "not configurable — see 04-addendum-persona.md"
    ),
    "/marlowe-permission/src/scope/": (
        "path scoping (brief §13). ADR-024: the traversal suite and the handle discipline ship "
        "together or neither ships; ADR-027: containment is the handle walk, and `ScopedPath` "
        "has no constructor from a string"
    ),
}


def reason_for(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    for suffix, why in PROTECTED.items():
        if normalized.endswith(suffix):
            return why
    # A leading "/" is prepended before the directory check so a REPO-RELATIVE path matches too.
    #
    # `PROTECTED_DIRS` keys are written as `/persona/` — bounded on both sides so `personal/` and
    # `my-persona-notes/` do not match. Without this line, `persona/v1.md` (relative) was SILENT
    # while `C:\...\persona1.md` (absolute) fired, because only the second contains a slash
    # before the fragment. The `crates/...` entries in PROTECTED are `endswith` suffixes and never
    # had the asymmetry; only the directory fragments did.
    rooted = normalized if normalized.startswith("/") else "/" + normalized
    for fragment, why in PROTECTED_DIRS.items():
        if fragment in rooted:
            return why
    return None


# Tokens that make a shell command a WRITE rather than a read.
#
# **Why this list exists instead of matching every command that names a guarded file.** The hook
# returns `ask`, and M3-DESIGN §4.2 names the cost of over-asking directly: *"an interruption the
# user learns to click through is worse than no interruption at all."* Guarded files are grepped
# and `sed -n`'d constantly during ordinary work — prompting on every read would train exactly
# that reflex, and a boundary nobody reads is a boundary that does not exist.
WRITE_TOKENS = (
    ">", ">>", "|tee", "| tee", "tee ", "sed -i", "perl -i", "python", "python3", "ruby ",
    "node ", "cp ", "mv ", "rm ", "install ", "truncate", "dd ", "patch ", "git apply",
    "git checkout", "git restore", "git reset",
)


def reason_for_command(command: str) -> tuple[str, str] | None:
    """A §13 path named inside a shell command that also looks like a write.

    # The gap this closes, and it was found twice independently in one session

    `.claude/settings.json` matched `Edit|Write|NotebookEdit`. **The Bash tool was not in it**, and
    `main` read only `file_path`/`notebook_path` — so every guarded-file change made through a
    heredoc, `sed -i` or a Python one-liner produced **no prompt and no record**, while
    `--self-check`, `boundary_hook.rs` and CLAUDE.md's table all still reported the path as
    protected. Those three check *paths*; none of them checks *reachability*.

    That is instance #14's family aimed one level out. There, a guard's SUBJECT moved and the guard
    went quiet. Here the subject is correct and the guard's **trigger surface** is incomplete — and
    the tool an agent naturally reaches for to do a mechanical multi-site edit is precisely the one
    that bypassed it.

    # THIS IS A FILTER, AND FILTERS LOSE. Say so rather than let it be read as containment.

    `$(echo dri)ver.rs`, a path built from a variable, a `python` script that computes the name —
    each defeats this trivially. `01-brief.md` §8.1 rules filters out **by name** for untrusted
    content: *"Filtering does not work. Containment works."*

    **It is still the right mechanism HERE, and the reason is the threat model rather than the
    technique.** §13 exists against *the agent changing safety machinery on its own initiative* —
    an honest agent doing mechanical work, not an adversary evading a check. There is no attacker
    on this path choosing the spelling of the filename. Against that, a filter that catches the
    ordinary case is worth having; against egress, where an attacker does choose, it would not be.
    **A later reader must not promote this into a containment boundary**, which is why the
    distinction is written here and not left to be inferred.

    Returns `(matched_path_fragment, why)` or `None`.
    """
    lowered = command.lower()
    if not any(tok in lowered for tok in WRITE_TOKENS):
        return None
    # Both separators: the repo is developed on Windows and edited through Git Bash, so the same
    # guarded file is written `crates/…/trust.rs` and `crates\…\trust.rs` in the same session.
    normalised = command.replace("\\", "/")
    for suffix, why in PROTECTED.items():
        if suffix in normalised:
            return suffix, why
    for fragment, why in PROTECTED_DIRS.items():
        if fragment in normalised:
            return fragment, why
    # **A bare relative path is still a path.** `PROTECTED_DIRS` keys are bounded on both sides —
    # `/persona/` — so that `personal/` cannot match, and `reason_for` inherits that. It means
    # `git checkout -- persona/v1.md` misses while `./persona/v1.md` hits, which is a distinction
    # no author of a shell command is thinking about. Each whitespace-separated token is retested
    # with a synthetic leading `/`, which restores the catch **without loosening the bound**:
    # `/personal/` still does not contain `/persona/`. Measured both ways in
    # `runs/m3-c/hook/bash-matcher.txt`.
    for token in normalised.split():
        candidate = "/" + token.lstrip("./")
        for fragment, why in PROTECTED_DIRS.items():
            if fragment in candidate:
                return fragment, why
    return None


def list_protected() -> int:
    """Print every guarded entry, one per line, sorted. Read by `boundary_hook.rs`.

    **This exists because `--self-check` cannot see itself shrink.** It iterates `PROTECTED`, so
    an entry that has been DELETED is trivially satisfied: the row is gone, nothing names a
    missing file, the check exits 0 and both tests in `boundary_hook.rs` stay green while the
    component is silently unguarded. That is instance #14 one step earlier — #14 is a guard whose
    SUBJECT moved, this is a guard that was REMOVED — and it was measured, not argued: deleting
    the `crates/marlowe-loop/src/driver.rs` row turned nothing red.

    A self-referential list cannot detect its own deletions, so the expectation has to live
    outside it. `boundary_hook.rs` pins the set and compares against this output.

    **The module doc of that test says two copies of a list is how they disagree, and that is
    still true — it is now the mechanism rather than the objection.** A drift between the two
    copies fails the build and asks a human, which is exactly the decision the §13 boundary
    exists to require. What must never happen is a row leaving with nothing to say so.
    """
    for entry in sorted(list(PROTECTED) + list(PROTECTED_DIRS)):
        print(entry)
    return 0


def self_check(repo_root: str) -> int:
    """Verify every guarded entry still names something that exists.

    A guard whose subject moved is not a weaker guard — it is no guard, and it reports nothing.
    That happened once already: `scope.rs` became `scope/mod.rs` in M2 Session B and path scoping
    was unguarded until a pipe test noticed. This turns that from silence into a failing build;
    `marlowe-permission/tests/boundary_hook.rs` runs it.
    """
    import os

    missing = []
    for suffix in PROTECTED:
        if not os.path.exists(os.path.join(repo_root, suffix)):
            missing.append(suffix)
    # A directory entry is matched anywhere in a path, not rooted at the repo, so it is resolved
    # by searching rather than by joining.
    #
    # **`/persona/` used to be exempt here and no longer is.** The exemption's stated basis was
    # that the entry is "pre-emptive by design" — guarding a directory before it existed. That
    # stopped being true: `persona/v1.md` and `persona/v2.md` exist and `daemon.rs` does
    # `include_str!("../../../persona/v2.md")`. So it was the ONE guarded row whose subject could
    # move with zero signal — rename the directory and the hook matches nothing, `--self-check`
    # returns 0, and `boundary_hook.rs` stays green. That is instance #14 reproduced on the single
    # row where the fix had deliberately not been applied.
    #
    # An exemption whose justification has expired is worse than no exemption, because it reads as
    # a considered decision. If a genuinely pre-emptive entry is added later, gate it on the
    # directory NOT existing rather than on a hardcoded name.
    wanted = set(PROTECTED_DIRS)
    if wanted:
        skip = {"target", ".git", "data", "models", "runs", "node_modules", "__pycache__"}
        found = set()
        for dirpath, dirnames, _ in os.walk(repo_root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            normalized = dirpath.replace("\\", "/") + "/"
            for fragment in wanted:
                if fragment in normalized:
                    found.add(fragment)
        missing.extend(sorted(wanted - found))

    for m in missing:
        print(f"UNGUARDED: {m} is listed as protected and does not exist", file=sys.stderr)
    return 1 if missing else 0


def main() -> int:
    # **Gated on the flag, not on the arity, and that is the whole point.**
    #
    # This was `len(sys.argv) >= 3 and sys.argv[1] == "--self-check"`. Invoked as `--self-check`
    # with the path argument missing, it fell through to the stdin branch, failed to parse JSON,
    # and **returned 0** — so a mistyped self-check reads as "every guarded path exists". A guard
    # whose failure mode is a silent pass is the thing this file exists to prevent, committed in
    # the file that prevents it.
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-check":
        if len(sys.argv) < 3:
            print("--self-check needs a repo root", file=sys.stderr)
            return 2
        return self_check(sys.argv[2])

    # Gated on the flag for the same reason as above: a mistyped enumeration must not fall
    # through to the stdin branch and return 0, which would read as "the set is empty".
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-protected":
        return list_protected()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # A hook that cannot parse its input must not block work. It has no basis for a
        # decision, so it says nothing and the normal permission flow applies.
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""

    if path:
        why = reason_for(str(path))
        if why is None:
            return 0
    else:
        # **The Bash road.** `Edit`/`Write` carry a path; a shell command carries a command, and
        # for the whole of M3 this branch did not exist — so a heredoc into a guarded file was
        # unprompted and unrecorded. See `reason_for_command`, including what it deliberately
        # cannot see.
        command = tool_input.get("command") or ""
        if not command:
            return 0
        hit = reason_for_command(str(command))
        if hit is None:
            return 0
        path, why = hit

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
