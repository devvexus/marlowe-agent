"""Session H — fit-split pools, and the gate that has to pass before they may be used.

Every Session G number is held-out, and STATE.md is emphatic about the consequence: those figures
are **headroom, not validation**. Anything promoted from them has to have its band re-derived on the
**fit** split before it is built, or Session H measures the same cases twice and calls the second
reading a confirmation of the first.

So this module hands out **fit-split** pools. Session F never dumped scored candidates for the fit
split on its own (`runs/session-f/fit-applied/` has `run.jsonl` and no
`scored-candidates.ndjson`), but `runs/session-f/all/` scored all 500 cases with the same gate, and
the fit half can be cut out of it.

**That substitution is exactly the kind of thing that has to be checked rather than assumed.**
`all/` is a different run directory than `heldout/`; if it scored differently for any reason -- a
different gate artifact, a different consolidation setting, a different corpus -- then its "fit
half" is a pool from some other experiment, and every band derived from it would be wrong in a way
that still prints a number. So the gate below cuts the **held-out** half out of the *same* `all/`
dump and requires it to reproduce Session F's published held-out top-1 rates exactly. If `all/`
reproduces the held-out baseline, it is the same scoring, and its fit half can be trusted for the
same reason.

Same rule, same targets and same 4-decimal equality as Session G's
`reconstruction_fidelity_gate`; read from that file rather than restated here, so there is one copy
of the numbers.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from reach_pools import (
    PREREG_PATH,
    REPO,
    SPLIT_PATH,
    Pool,
    baseline_top1,
    load_pools,
)

ALL_RUN = REPO / "runs" / "session-f" / "all"
OUT_PATH = REPO / "runs" / "session-h" / "fit-pools-gate.json"


def split_ids() -> tuple[frozenset[str], frozenset[str]]:
    """(fit, heldout) query ids, from the split pre-registered in Session B and never re-run."""
    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    return frozenset(split["fit"]), frozenset(split["heldout"])


def load_split_pools(run_dir: Path = ALL_RUN) -> tuple[dict[str, Pool], dict[str, Pool], dict]:
    """Reconstruct from one dump and cut it in two. Returns (fit, heldout, stats)."""
    pools, stats = load_pools(run_dir)
    fit_ids, heldout_ids = split_ids()

    fit = {q: p for q, p in pools.items() if q in fit_ids}
    heldout = {q: p for q, p in pools.items() if q in heldout_ids}

    unsplit = set(pools) - fit_ids - heldout_ids
    if unsplit:
        # Not a warning. A pool whose case is in neither half of a pre-registered split means the
        # dump and the split disagree about what the corpus is, and no downstream band is readable.
        raise SystemExit(
            f"{len(unsplit)} reconstructed pools are in neither half of the split "
            f"(e.g. {sorted(unsplit)[:3]}). The dump and tools/split.json disagree."
        )

    stats = dict(stats)
    stats["fit_pools"] = len(fit)
    stats["heldout_pools"] = len(heldout)
    return fit, heldout, stats


def fidelity_gate(heldout: dict[str, Pool]) -> tuple[bool, dict]:
    """The held-out half of `all/` must reproduce Session F's published held-out top-1.

    This is the check that licenses using the FIT half of the same dump. It is deliberately run on
    the half whose answer is already published: the fit half has no published baseline to check
    against, so the only way to earn confidence in it is to show the dump reproduces the half that
    does.
    """
    prereg = json.loads(io.open(PREREG_PATH, encoding="utf-8").read())
    targets = prereg["reconstruction_fidelity_gate"]["targets_read_from_session_f_artifact"]
    measured = baseline_top1(heldout)
    names = {
        "lexical_top1": "lexical",
        "dense_top1": "dense",
        "either_oracle_top1": "either_oracle",
    }
    checks = {}
    ok = True
    for key, name in names.items():
        passed = abs(measured[name] - targets[key]) < 1e-9
        checks[name] = {"target": targets[key], "measured": measured[name], "pass": passed}
        ok = ok and passed
    return ok, {
        "_what": (
            "The held-out half cut out of runs/session-f/all/ must reproduce Session F's published "
            "held-out top-1 exactly. Passing is what licenses using the FIT half of the same dump."
        ),
        "source_run": str(ALL_RUN.relative_to(REPO)).replace("\\", "/"),
        "rule": prereg["reconstruction_fidelity_gate"]["rule"],
        "heldout_cases_reconstructed": len(heldout),
        "checks": checks,
        "pass": ok,
    }


def gated_fit_pools() -> dict[str, Pool]:
    """The one entry point downstream scripts should use. Refuses if the gate fails."""
    fit, heldout, _ = load_split_pools()
    ok, report = fidelity_gate(heldout)
    if not ok:
        raise SystemExit(
            "Fit-split reconstruction gate FAILED -- runs/session-f/all/ does not reproduce the "
            "published held-out baseline, so its fit half is not Session F's fit split. "
            f"{json.dumps(report['checks'], indent=2)}"
        )
    return fit


def main() -> int:
    fit, heldout, stats = load_split_pools()
    ok, report = fidelity_gate(heldout)

    print(f"Reconstructed both splits from {report['source_run']}/")
    for k, v in stats.items():
        print(f"  {k:42s} {v}")
    print()
    print(f"Fit-split licensing gate over {report['heldout_cases_reconstructed']} held-out cases:")
    for name, c in report["checks"].items():
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  {name:14s} target {c['target']:.4f}  measured {c['measured']:.4f}  {mark}")
    print()

    fit_baseline = baseline_top1(fit)
    report["fit_split_baseline_top1"] = fit_baseline
    report["fit_cases_reconstructed"] = len(fit)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not ok:
        print("GATE FAILED. The fit half of this dump is not Session F's fit split, and no")
        print("fit-split band may be derived from it.")
        return 1

    print("GATE PASSED. The fit half of the same dump is Session F's fit split.\n")
    print(f"Fit-split baseline top-1 over {len(fit)} cases -- NEW, never published before:")
    for name in ("lexical", "dense", "either_oracle"):
        print(f"  {name:14s} {fit_baseline[name]:.4f}")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
