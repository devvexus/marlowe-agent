#!/usr/bin/env bash
# M3 Session A — steering a run that is already going, from another terminal.
#
# The daemon serves the MAIN port one connection at a time, so this is only meaningful because
# the steer goes to the control plane: on the main port it would not be read until the turn it
# was meant to change had already ended.
set -u
cd "$(dirname "$0")/../../.." || exit 1
M=target/release/marlowe.exe
DEMO="$(cygpath -w /tmp/m3demo)"
P="$DEMO/profile"; W="$DEMO/ws"; PORT=11455; OUT=runs/session-a-m3/live

say() { printf '\n=== %s ===\n' "$*"; }

say "1. a turn starts, and it is told to keep going"
( "$M" --ask "Read f1.md. Then read f2.md. Then f3.md, f4.md, f5.md and f6.md, one at a time, one file per step. Do not answer until you have read all six." \
      --workspace "$W" --profile-root "$P" --daemon-port $PORT > "$OUT/steer-turn.txt" 2>&1
  echo "ASK EXITED $?" >> "$OUT/steer-turn.txt" ) &

RUNID=""
for _ in $(seq 1 200); do
  ROW=$("$M" --runs --profile-root "$P" --daemon-port $PORT 2>/dev/null | grep ' running ')
  if [ -n "$ROW" ]; then RUNID=$(echo "$ROW" | awk '{print $2}'); echo "$ROW"; break; fi
  sleep 0.05
done
[ -z "$RUNID" ] && { echo "FAILED: no live run"; exit 1; }

say "2. wait for the first completed step, so the run is genuinely mid-flight"
python "$OUT/watch_journal.py" "$P/journal.db" "$RUNID" 1 60 || exit 1

say "3. /steer, from this process, while the turn holds the main port"
"$M" --steer "$RUNID" --guidance "STOP READING FILES. Answer right now with exactly the word PINEAPPLE and nothing else." \
     --profile-root "$P" --daemon-port $PORT 2>&1 | tee "$OUT/steer-sent.txt"

say "4. the run's own answer"
wait
cat "$OUT/steer-turn.txt"

say "5. the journal records the delivery"
python - "$P/journal.db" "$RUNID" <<'PY'
import json, sqlite3, sys
conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
rows = conn.execute("SELECT kind,payload FROM journal WHERE run_id=? ORDER BY seq", (sys.argv[2],)).fetchall()
for kind, payload in rows:
    if kind == "steer_received":
        print("steer_received:", json.loads(payload))
print("checkpoints:", sum(1 for k, _ in rows if k == "checkpointed"))
PY
