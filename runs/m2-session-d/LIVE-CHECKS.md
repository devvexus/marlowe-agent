# M2 Session D — the two built-but-unverified things, checked live

2026-08-11. Binary built this session from `f85e2e0` + nothing. Scratch port **11477** throughout, so
no daemon on the default 11435 was touched. Human at the keyboard; the agent cannot click an X.

**The instrument is the listener and the socket, not `--status`.** `agent::status()` constructs
`Client::new("cli")`, pinned to `DEFAULT_DAEMON_PORT`, and `--status` takes no `--daemon-port` — the
same gap C2f closed for `--ask`, still open here. Worse: with nothing on 11435 it calls
`Daemon::open` and reports on a daemon it just constructed, which reads identically to a report
about a running one.

## Results

| # | Check | Result |
|---|---|---|
| A | X-close while **idle** stops the daemon | **PASS** — no listener after |
| B | X-close **mid-turn** leaves the daemon running | **PASS** — listener survived |
| B2 | The conversation is there on the way back in | **PASS**, after the failure below was diagnosed |
| C | `bash` through the approval window on a real turn | **PASS** — prompt shown, human approved, command executed |

The console control handler fires on `CTRL_CLOSE_EVENT`, and `TURN_IN_FLIGHT` mirrors
`session.is_busy()` correctly in **both** directions. Neither disagreed, so the busy mirror is right
and C2e's mid-turn conversation loss has not been reintroduced.

## C is closed, and it was the last one

**`bash` reached the approval window on a real turn, the human approved, and the command ran.**
Until now both halves were tested against each other over a socket (`approval_round_trip.rs`) with
no model in the loop, and STATE.md's standing note was *"treat the end-to-end path as unverified
until an approval is observed on a real turn."* It has been.

An approved `web` fetch crossed the same modal earlier in the session, so the surface now has two
independent live confirmations rather than one — different tool, different consequence tier
(`Inert` + egress vs `Irreversible`), same gate.

**Every live item this session opened with is now closed.**

## B2 failed on the first attempt, and the cause was not what it looked like

**Reported as:** reopening after the mid-turn close showed no conversation, accepted no keystrokes,
and sat on *"connecting"*. The listener was still up.

**It looked like conversation loss. It was not.** A direct socket probe found the daemon answering,
`live_runs: 0`, and `{"op":"replay","session":"tui"}` returning the entire transcript — the question,
the reasoning, and the answers. Nothing had been lost at any point.

**What actually happened.** The turn was still executing. The prompt used for B made the model emit
**48,064 characters** against the output contract's 4,000, get nudged, and start again — a turn
lasting minutes. The daemon is serial and cannot accept a second connection while executing one.
And `LiveSession::finish_connect` performs **three blocking socket round-trips** — `status`, `Runs`,
`Replay` — on the UI thread with **no timeout**, before any interactive frame is drawn. So a busy
daemon renders as a dead window.

Confirmed by retrying once the daemon went idle: it connected promptly and replayed the conversation.

### The defect, stated as a finding

**A daemon that is present and busy is indistinguishable from one that is dead, and the surface
accepts no input while it decides.** `live.rs::an_absent_daemon_degrades_visibly_rather_than_refusing_to_start`
covers the daemon being **absent** — connect is refused, immediately, and the band says so. Nobody
covered the daemon being **present and busy**, where connect *succeeds* and the reply never comes.
The test's own name records which case was considered.

**STATE.md describes the symptom wrongly and should be corrected.** It says a client reopening
mid-turn *"shows the conversation up to the last completed turn and then waits."* It shows
**nothing** and accepts nothing, because the handshake blocks before there is anything to show. The
limitation was recorded with the wrong consequence attached, which is why this read as a new bug and
cost a round trip.

**Proposed fix, not built — Session E territory.** A read timeout on the handshake, and a
`connecting` state the surface can paint and quit out of, so *waiting on a busy daemon* is a visible
state rather than a hang. The three round-trips should also not all be prerequisites of the first
interactive frame: `status` is, `Runs` and `Replay` are not.

### A measurement instrument that could not answer the question

`d` — a listening-socket count — cannot distinguish **busy** from **wedged**: the port stays bound
either way. It was the right instrument for A and B, and the wrong one for B2, and it read
"LISTENING" in both the working and the broken case. Replaced for B2 by a probe that sends
`{"op":"status"}` and waits for a reply, which is the difference between *the port is open* and *the
daemon is answering*. Same family as the rest of the ledger: the cheap reading was authoritative and
about an adjacent question.

## Also observed

- **`rerank_provider: "not-wired"`** — the daemon loads no cross-encoder today. D2's artifact-to-graph
  binding therefore has a real absence to refuse against rather than a fallback to slip into.
- **The staleness banner fired correctly**, reporting the daemon's binary as 58 minutes older than
  the source — the source had moved because `record.rs` was edited after the build. The banner is
  doing its job. **Any live check after D1 lands must `--shutdown --daemon-port 11477` and relaunch**,
  or it measures the old binary.
- **The model blew the output contract by 12×** (48,064 against 4,000) and recovered only after a
  nudge. Noted, not chased; it is not this session's scope.
