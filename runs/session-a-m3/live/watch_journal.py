"""Wait until a run has N completed checkpoints in the journal, then print its step.

The demo's first version polled `marlowe --watch`, which spawns a process per check -- roughly
200 ms of latency against a 9B model that finishes a two-step turn in under five seconds. The
kill kept landing after the run had already completed, so the "control" that was supposed to prove
the run died proved the opposite.

Reading the journal directly is ~10 ms, which is well inside the window. It is also the honest
instrument: the journal is what a resume reads, so waiting on it is waiting on exactly the state
the next phase depends on.
"""
import json
import sqlite3
import sys
import time

db, run, want, deadline_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
end = time.time() + deadline_s
while time.time() < end:
    try:
        # `mode=ro` so this never takes a write lock on a journal a daemon is appending to.
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.2)
        rows = conn.execute(
            "SELECT payload FROM journal WHERE kind='checkpointed' ORDER BY seq ASC"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        time.sleep(0.01)
        continue
    steps = []
    for (payload,) in rows:
        try:
            p = json.loads(payload)
        except ValueError:
            continue
        if p.get("run") == run:
            steps.append(p.get("step"))
    if len(steps) >= want:
        print(max(steps))
        sys.exit(0)
    time.sleep(0.01)
print("TIMEOUT", file=sys.stderr)
sys.exit(1)
