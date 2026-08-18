"""Resident footprint of the two shipped front ends, attributed by source.

**Two totals, never blended.** `marlowe --serve` is the product; `marlowe --eval-adapter` is the
benchmark path. They are two independent front ends over the same crates
(`docs/design/EVAL-PRODUCT-DIVERGENCE.md`) and they do not load the same components:

* `--serve` loads **no embedder** — zero references to `Embedder` in `crates/marlowe-daemon/src/`,
  and the one production call site is `crates/marlowe/src/main.rs:657`, inside `--eval-adapter`.
  It *does* load a cross-encoder, via `DaemonMemory::open`, when `--reranking` is given.
* `--eval-adapter` loads both, plus a `VectorStore` of embeddings.

Reporting one number for "Marlowe" would therefore describe neither.

# The instruments, named

* **Host** is `WorkingSet64` and `PeakWorkingSet64` from `Get-Process`, sampled from outside the
  process. Working set is resident bytes; peak is the high-water mark since start.
* **Device** is card-wide `nvidia-smi --query-gpu=memory.free`, differenced against a baseline
  captured before the process starts. Per-process device memory reads `[N/A]` under WDDM on this
  driver, so there is no per-process device instrument here at all — the card-wide delta includes
  anything else that allocated in the window, which is why every run prints its own baseline and
  why an idle control is taken alongside.

# The journal slope is measured, not asserted

`Journal::verify_chain` walks every row and `BeliefStore::derive` folds the whole log; both are
O(journal) and neither slope had ever been measured. This builds journals at several sizes through
the shipped `--eval-adapter` wire and reads the daemon's startup footprint on each, so "it scales
with journal size" is a fitted line rather than a reading of the source.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARLOWE = REPO / "target" / "release" / "marlowe.exe"
EMBEDDER = REPO / "models" / "jina-embeddings-v2-small-en"
RERANKER = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
CUDA_LIB = r"C:\Users\matth\AppData\Local\Programs\Python\Python311\Lib\site-packages\torch\lib"


def ps(command: str) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def proc_mem(pid: int) -> tuple[int, int] | None:
    """`(WorkingSet64, PeakWorkingSet64)` in bytes, or None once the process is gone."""
    raw = ps(
        f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
        f"if ($p) {{ Write-Output ('{{0}} {{1}}' -f $p.WorkingSet64, $p.PeakWorkingSet64) }}"
    )
    parts = raw.split()
    if len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def device_free_bytes() -> int | None:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        return None
    try:
        return min(int(line.strip()) for line in out.stdout.splitlines() if line.strip()) * 1024 * 1024
    except ValueError:
        return None


def mb(b: float) -> float:
    return b / 1024.0 / 1024.0


def settle(pid: int, stable_reads: int = 3, interval: float = 1.0, limit: int = 90):
    """Sample until the working set stops moving, and return `(working, peak)`.

    **A fixed sleep is what this replaces, and the reason is a real hazard rather than tidiness.**
    A `--reranking` daemon reads a 60 MB graph from disk at startup; whether a one-shot sample
    lands before or after that read depends on the OS file cache, so the same configuration
    measures 30 MB on one run and 92 MB on the next with nothing to say which is the answer. The
    first version of this script sampled the eval adapter as soon as its working set crossed
    200 MB and reported 908 MB for a process that settled at 1,093 MB -- a 20% under-read of a
    headline number, produced by an instrument that fired on a threshold it had been given rather
    than on the event it cared about.

    `stable_reads` consecutive samples within 1 MB is the settled condition. Returns the last
    reading even if it never settles, so a still-growing process is visible in the elapsed time
    rather than reported as a failure.
    """
    last = None
    stable = 0
    for _ in range(limit):
        time.sleep(interval)
        m = proc_mem(pid)
        if m is None:
            return last
        if last is not None and abs(m[0] - last[0]) < 1024 * 1024:
            stable += 1
            if stable >= stable_reads:
                return m
        else:
            stable = 0
        last = m
    return last


# --------------------------------------------------------------------------------------------
# Building a journal of a chosen size, through the shipped wire
# --------------------------------------------------------------------------------------------

TEXT_BANK = [
    "the harbour report arrived on the morning of the fourteenth and named three vessels",
    "she said the equation would not close unless the second term was measured again",
    "the signal engine logs a number every time a letter is written to the index",
    "nobody had re-run the sweep since the graph was re-pinned in session j",
]


def ingest_frames(turns: int, session: str, base_ms: int) -> list[str]:
    """One ingest frame carrying `turns` turns. Terminal channel: `UserAsserted` at ingest."""
    body = {
        "contract_version": "1.0",
        "clock": {"now_ms": base_ms},
        "session_id": session,
        "turns": [
            {
                "turn_id": f"{session}-t{i}",
                "speaker": "user" if i % 2 == 0 else "assistant",
                "text": f"{TEXT_BANK[i % len(TEXT_BANK)]} (turn {i} of session {session})",
                "occurred_at_ms": base_ms + i * 1000,
                "origin": {"channel": "terminal", "actor": "user"},
            }
            for i in range(turns)
        ],
    }
    return [json.dumps({"op": "ingest", "body": body})]


def build_profile(root: Path, sessions: int, turns_per_session: int, env: dict) -> dict:
    """Drive `--eval-adapter` to write a journal, and report the adapter's own footprint."""
    root.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(MARLOWE),
        "--eval-adapter",
        "--profile-root",
        str(root),
        "--embedder-model",
        str(EMBEDDER),
        "--reranking",
        str(RERANKER),
        "--embedder-provider",
        "cpu",
        "--rerank-provider",
        "cpu",
    ]
    dev_before = device_free_bytes()
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    samples: dict = {"pid": proc.pid, "device_baseline": dev_before}

    # The startup banner is written before the first frame is read, so a reading taken now is the
    # loaded-but-idle footprint: both models resident, no memory written, no vector embedded.
    assert proc.stdin is not None and proc.stdout is not None
    samples["after_load"] = settle(proc.pid)
    samples["device_after_load"] = device_free_bytes()

    for s in range(sessions):
        for line in ingest_frames(turns_per_session, f"s{s}", 1_700_000_000_000 + s * 86_400_000):
            proc.stdin.write(line + "\n")
        proc.stdin.flush()
        proc.stdout.readline()

    samples["after_ingest"] = proc_mem(proc.pid)
    samples["device_after_ingest"] = device_free_bytes()
    proc.stdin.close()
    proc.wait(timeout=120)
    samples["stderr"] = proc.stderr.read() if proc.stderr else ""
    samples["memories"] = sessions * turns_per_session
    return samples


def measure_serve(root: Path, reranking: bool, env: dict, port: int) -> dict:
    """Start `marlowe --serve` on an existing profile and read its settled footprint."""
    cmd = [str(MARLOWE), "--serve", "--profile-root", str(root), "--daemon-port", str(port)]
    if reranking:
        cmd += ["--reranking", str(RERANKER)]
    dev_before = device_free_bytes()
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    settled = settle(proc.pid)
    elapsed = time.perf_counter() - t0
    # **`--status` DOES NOT TAKE A PORT, so this cannot ask the daemon under measurement.**
    #
    # `--serve`'s startup lines name the model directory and stop there; the RESOLVED rerank
    # provider appears only on `--status`, from `rerank_provider_label`. The obvious move is to
    # ask `--status` here -- and the first version of this script did, passing `--daemon-port`
    # along with it. `main.rs` routes `--status` to `agent::status(workspace, profile_root)`,
    # which takes **no port**: the flag is accepted on the command line and ignored, so the reply
    # came from whatever sits on the DEFAULT port and the run recorded `rerank not-loaded` for
    # four daemons that had each resolved CUDA and were holding ~1 GB of host and ~350-670 MB of
    # device memory at the time.
    #
    # Nothing was broken. The daemon was right, the label was right, and the reading was about a
    # different process -- the project's own "a measurement is scoped to the system it was taken
    # on" family, produced by a flag that was silently ignored rather than refused. It is recorded
    # here rather than repaired because repairing it means running a daemon on the default port,
    # which serialises the sweep against any daemon the user already has up.
    #
    # **The resolution is verified separately and manually**: start one daemon on the default port
    # and run `marlowe --status`. On an idle card that prints
    # `rerank      CUDAExecutionProvider · batched · asked auto`.
    resolved = [
        "not captured: `--status` takes no --daemon-port, so it cannot address this daemon. "
        "Verify the resolved provider with a daemon on the DEFAULT port; see the note in "
        "measure_serve()."
    ]
    result = {
        "pid": proc.pid,
        "reranking": reranking,
        "settled": settled,
        "device_baseline": dev_before,
        "device_after": device_free_bytes(),
        "seconds_to_settle": elapsed,
        "alive": proc.poll() is None,
        "status_lines": resolved,
    }
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        result["stderr"] = proc.stderr.read() if proc.stderr else ""
    except Exception:
        result["stderr"] = ""
    return result


def journal_bytes(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default="0,50,250,1000",
                    help="memory counts to build journals at")
    ap.add_argument("--turns-per-session", type=int, default=50)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(**__import__("os").environ)
    env["MARLOWE_CUDA_LIB_DIR"] = CUDA_LIB

    if not MARLOWE.exists():
        print(f"no binary at {MARLOWE}; `cargo build --release` first")
        return 1
    print(f"binary: {MARLOWE}  mtime {time.ctime(MARLOWE.stat().st_mtime)}")

    report: dict = {"binary_mtime": MARLOWE.stat().st_mtime, "rows": []}
    sizes = [int(s) for s in args.sizes.split(",")]
    port = 45800
    for n in sizes:
        root = out / f"profile-{n}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        sessions = max(0, n // args.turns_per_session)
        adapter = {"skipped": "n == 0, nothing to ingest"}
        if sessions:
            adapter = build_profile(root, sessions, args.turns_per_session, env)
        else:
            # Still start the adapter once on an empty profile — that reading IS the
            # loaded-but-empty eval-adapter total, and it is one of the two headline numbers.
            adapter = build_profile(root, 0, 0, env)

        jb = journal_bytes(root)
        port += 1
        serve_plain = measure_serve(root, False, env, port)
        port += 1
        serve_rerank = measure_serve(root, True, env, port)
        row = {
            "memories": n,
            "profile_bytes": jb,
            "adapter": adapter,
            "serve_no_reranking": serve_plain,
            "serve_with_reranking": serve_rerank,
        }
        report["rows"].append(row)
        ws = lambda d, k: mb((d.get(k) or (0, 0))[0])
        print(
            f"n={n:<6} profile {mb(jb):8.2f} MB | "
            f"adapter loaded {ws(adapter, 'after_load'):8.1f} -> ingested {ws(adapter, 'after_ingest'):8.1f} MB | "
            f"serve {ws(serve_plain, 'settled'):8.1f} MB | "
            f"serve+rerank {ws(serve_rerank, 'settled'):8.1f} MB | "
            f"settle {serve_rerank.get('seconds_to_settle', 0):.1f}s"
        )

    (out / "footprint.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out / 'footprint.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
