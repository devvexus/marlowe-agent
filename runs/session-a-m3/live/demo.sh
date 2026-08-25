#!/usr/bin/env bash
# M3 Session A — a run survives a daemon restart, demonstrated live.
#
# The kill is a `taskkill /F`, not `--shutdown`: the point is a daemon that did not get to
# write a terminal status, which is what a crash, a reboot or a provider failover leaves.
set -u
cd "$(dirname "$0")/../../.." || exit 1
M=target/release/marlowe.exe
DEMO="$(cygpath -w /tmp/m3demo)"
P="$DEMO/profile"
W="$DEMO/ws"
PORT=11455
OUT=runs/session-a-m3/live

say() { printf '\n=== %s ===\n' "$*"; }

say "1. a turn starts"
( "$M" --ask "Read f1.md and tell me what it says. Then read f2.md and tell me what THAT says. Then read f3.md. Answer only after all three, one file per step." \
      --workspace "$W" --profile-root "$P" --daemon-port $PORT > "$OUT/turn3.txt" 2>&1
  echo "ASK EXITED $?" >> "$OUT/turn3.txt" ) &
ASK_PID=$!

say "2. /runs, from another process, while the turn is live"
RUNID=""
for _ in $(seq 1 200); do
  ROW=$("$M" --runs --profile-root "$P" --daemon-port $PORT 2>/dev/null | grep ' running ')
  if [ -n "$ROW" ]; then RUNID=$(echo "$ROW" | awk '{print $2}'); echo "$ROW"; break; fi
  sleep 0.1
done
[ -z "$RUNID" ] && { echo "FAILED: no live run appeared"; exit 1; }

say "3. wait for the first completed step, then kill -9 the daemon"
# The PID is resolved BEFORE the wait, so the kill is one syscall after the checkpoint lands.
# Resolving it after cost ~200 ms of `netstat`, which against a 9B model that finishes a two-step
# turn in under five seconds was enough for the run to complete first -- and a "control" that
# proves the run finished proves the opposite of what it is for.
PID=$(netstat -ano 2>/dev/null | grep "127.0.0.1:$PORT " | grep LISTENING | awk '{print $NF}' | head -1)
STEP=$(python "$OUT/watch_journal.py" "$DEMO/profile/journal.db" "$RUNID" 1 60)
echo "checkpoint step $STEP is durable; killing now"
echo "killing daemon pid $PID"
taskkill //F //PID "$PID" > "$OUT/kill.txt" 2>&1
cat "$OUT/kill.txt"
wait $ASK_PID 2>/dev/null

say "4. THE CONTROL: the turn did not finish"
cat "$OUT/turn3.txt"

say "5. the daemon is gone"
"$M" --runs --profile-root "$P" --daemon-port $PORT 2>&1 | head -3

say "6. a NEW daemon, same profile"
( "$M" --serve --workspace "$W" --profile-root "$P" --daemon-port $PORT --model marlowe-red:9b \
      > "$OUT/daemon2.log" 2>&1 ) &
for _ in $(seq 1 200); do
  "$M" --status --profile-root "$P" --daemon-port $PORT >/dev/null 2>&1 && break
  sleep 0.1
done
grep -i 'interrupted' "$OUT/daemon2.log"

say "7. /runs finds the interrupted run, and /watch says what a resume would resume from"
"$M" --runs --profile-root "$P" --daemon-port $PORT 2>&1 | tee "$OUT/runs-after-restart.txt"
"$M" --watch "$RUNID" --profile-root "$P" --daemon-port $PORT 2>&1 | tee "$OUT/watch-after-restart.txt"

say "8. resume"
"$M" --resume "$RUNID" --profile-root "$P" --daemon-port $PORT 2>&1 | tee "$OUT/resumed.txt"

say "done"
