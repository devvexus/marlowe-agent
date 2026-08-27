#!/usr/bin/env python3
"""
CANONICAL PRODUCT TTFT.  One process, one clock, both placements.

WHY THIS EXISTS
---------------
Two product-level TTFT numbers disagreed and neither author could explain the
direction of the gap:

    A  client across the daemon socket   71.0 ms (llama.cpp)  382.4 ms (ollama)  n=7
    B  daemon's own --dev stderr        151.5 ms              472.5 ms           n=2

A's clock *contains* B's -- it starts before the socket connect and stops on the
first delta that has crossed the socket -- so A should read HIGHER.  It read
lower on both arms.  Comparing two numbers taken in two different processes on
two different days cannot settle that, because every candidate explanation
(prompt size, session reuse, --dev overhead, pipe latency, a background build)
lives in the difference between the two RUNS, not in the difference between the
two CLOCKS.

So this instrument takes BOTH placements ON THE SAME REP, from ONE python
process, off ONE time.perf_counter().  The A-vs-B gap stops being a cross-run
comparison and becomes a within-rep subtraction:

    t_connect ......... socket opened, token written              (A starts)
    t_ask_sent ........ the ask op written
    t_end_request ..... daemon printed `[dev] ===== END REQUEST`  (B starts)
                        -- everything before this is daemon-side: auth, context
                           assembly, memory retrieval, request construction, and
                           the cost of the --dev dump itself
    t_frame_content ... daemon printed the first frame carrying bytes (B stops)
    t_first_delta ..... first non-empty reasoning/text delta on the socket (A stops)

    pre_request  = t_end_request     - t_ask_sent
    dev_ttft     = t_frame_content   - t_end_request      <-- CANONICAL
    delivery     = t_first_delta     - t_frame_content
    socket_ttft  = t_first_delta     - t_connect

`delivery` is signed on purpose.  It is the ONLY reading that measures how far
the stderr pipe lags the socket; a negative value means the daemon's stderr line
reached this process AFTER the event it describes had already crossed the socket,
which would mean dev_ttft's stop edge is late.  Asserting a pipe-read clock is
tight without measuring it is exactly the proxy this project keeps shipping.

THE STOP EDGE IS DEFINED ONCE, FOR BOTH CLOCKS
----------------------------------------------
A stopped on the first delta with non-empty content.  The dev frame dump prints
a line for EVERY frame including the role-only opener, so `frame 1` is not the
same event.  Both dev_ttft (content) and dev_ttft_anyframe are recorded, and the
canonical one is the content-bearing edge, because that is the one A used and a
clock comparison that changed the stop event would be measuring the definition.

THE PROMPT IS DUMPED ON EVERY MEASURED CALL
-------------------------------------------
System-message character count, message count and the tool list are parsed out
of the dev dump PER CALL, from the `--- conversation (N messages) ---` table --
which both arms print in the same format, unlike the ollama-only
`system messages:` line.  If the two arms do not send the same bytes the ratio is
a prompt-size artefact and not a runtime result; that is the single thing whose
absence caused the disagreement this run exists to retire.

WHAT WAS KEPT FROM A'S INSTRUMENT (product_ttft.py)
---------------------------------------------------
  * The wire framing: token line first, then the ask op (without the token the
    daemon closes in 0.3 ms and that reads as a very fast turn).
  * A FRESH SESSION PER REP with a byte-identical message.  A shared session
    grows the prefix every rep and "warm" stops meaning anything.
  * Throughput carried beside TTFT, because a CPU-bound server wins on TTFT and
    loses 5x on the turn.
WHAT CHANGED: the dev-stderr clock above, the per-call prompt dump, the
bracketing readings, and tokens/sec taken from the frame stream rather than
chars/sec (chars/sec is still reported so A's rows stay comparable).
"""
import argparse
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "target" / "release" / "marlowe.exe"


# ---------------------------------------------------------------- bracketing
def bracket(tag):
    """0 cargo / 0 rustc and the VRAM reading, RECORDED not remembered.

    A cell bracketed on one side only is not bracketed: a build that starts
    halfway through inflates every remaining rep and leaves the `before`
    reading looking perfectly clean.
    """
    try:
        tl = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=60).stdout
    except Exception as e:  # noqa: BLE001
        tl = "tasklist failed: %s" % e
    counts = {}
    for name in ("cargo.exe", "rustc.exe", "llama-server.exe", "marlowe.exe", "ollama.exe"):
        counts[name] = sum(1 for ln in tl.splitlines() if ln.lower().startswith(name.lower()))
    try:
        o = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=60).stdout.strip()
        used, free = [int(x.strip()) for x in o.split(",")]
        vram = {"used_mib": used, "free_mib": free}
    except Exception as e:  # noqa: BLE001
        vram = {"error": str(e)}
    return {"tag": tag, "at": time.strftime("%H:%M:%S"), "procs": counts, "vram": vram}


# ---------------------------------------------------------------- dev stderr
FRAME_THINK = re.compile(r"^\[dev\] frame\s+(\d+)\s+THINK\s+(\d+) bytes")
FRAME_TEXT = re.compile(r"^\[dev\] frame\s+(\d+)\s+(\d+) bytes")
CONV_ROW = re.compile(r"^\[dev\] \[\s*(\d+)\]\s+(\S+)\s+(\d+) chars")
CONV_HDR = re.compile(r"^\[dev\] --- conversation \((\d+) messages\) ---")
SYS_LINE = re.compile(r"^\[dev\] --- system\[(\d+)\] \((\d+) chars\) ---")
TOOLS = re.compile(r"^\[dev\] tools offered: (.*)$")
REQ_START = re.compile(r"^\[dev\] ===== OUTBOUND REQUEST")
REQ_END = re.compile(r"^\[dev\] ===== END REQUEST =====")


class Daemon:
    """marlowe --serve, with its stderr timestamped as it arrives.

    Timestamps are read-times in THIS process off the same perf_counter the
    socket clock uses, so the two placements are directly subtractable.  The
    cost of that choice is pipe latency, which `delivery` measures rather than
    assumes.
    """

    def __init__(self, argv, env, logpath):
        self.lines = []  # (t_perf, text)
        self.lock = threading.Lock()
        self.log = open(logpath, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            argv, env=env, cwd=str(REPO),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self.t = threading.Thread(target=self._pump, daemon=True)
        self.t.start()

    def _pump(self):
        for raw in self.proc.stderr:
            t = time.perf_counter()
            line = raw.rstrip("\r\n")
            with self.lock:
                self.lines.append((t, line))
            self.log.write("%.6f %s\n" % (t, line))
        try:
            self.log.flush()
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self):
        with self.lock:
            return list(self.lines)

    def wait_for(self, needle, timeout):
        end = time.time() + timeout
        while time.time() < end:
            for _, ln in self.snapshot():
                if needle in ln:
                    return True
            if self.proc.poll() is not None:
                return False
            time.sleep(0.05)
        return False

    def stop(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.log.flush()
            self.log.close()
        except Exception:  # noqa: BLE001
            pass


def parse_calls(lines, t_lo, t_hi):
    """Every model call the daemon made inside one rep's window.

    A turn is not always one model call -- the loop may call again after a tool
    or a `done`.  TTFT is the FIRST call; the count of calls is reported too,
    because two arms making a different number of calls have different turn
    totals for a structural reason and not a speed one.
    """
    win = [(t, l) for (t, l) in lines if t_lo <= t <= t_hi]
    calls, cur = [], None
    for t, l in win:
        if REQ_START.match(l):
            if cur:
                calls.append(cur)
            cur = {"t_req_start": t, "t_end_request": None, "system_chars": None,
                   "system_chars_sysline": None, "messages": None, "tools": None,
                   "roles": [], "frames": [], "t_first_any_frame": None,
                   "t_first_content_frame": None}
            continue
        if cur is None:
            continue
        m = CONV_HDR.match(l)
        if m:
            cur["messages"] = int(m.group(1))
            continue
        m = CONV_ROW.match(l)
        if m:
            role, nchars = m.group(2), int(m.group(3))
            cur["roles"].append([role, nchars])
            if role == "system" and cur["system_chars"] is None:
                cur["system_chars"] = nchars
            continue
        m = SYS_LINE.match(l)
        if m:
            if cur["system_chars_sysline"] is None:
                cur["system_chars_sysline"] = int(m.group(2))
            continue
        m = TOOLS.match(l)
        if m:
            cur["tools"] = m.group(1).strip()
            continue
        if REQ_END.match(l):
            cur["t_end_request"] = t
            continue
        m = FRAME_THINK.match(l)
        if m:
            n, b = int(m.group(1)), int(m.group(2))
            if cur["t_first_any_frame"] is None:
                cur["t_first_any_frame"] = t
            if b > 0 and cur["t_first_content_frame"] is None:
                cur["t_first_content_frame"] = t
            cur["frames"].append((t, n, b, "think"))
            continue
        m = FRAME_TEXT.match(l)
        if m:
            n, b = int(m.group(1)), int(m.group(2))
            if cur["t_first_any_frame"] is None:
                cur["t_first_any_frame"] = t
            if b > 0 and cur["t_first_content_frame"] is None:
                cur["t_first_content_frame"] = t
            cur["frames"].append((t, n, b, "text"))
            continue
    if cur:
        calls.append(cur)
    return calls


# ---------------------------------------------------------------- the socket
def ask(port, message, profile_root, session, timeout=300.0):
    token = ""
    try:
        token = (Path(profile_root) / "daemon.token").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    t_connect = time.perf_counter()
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.settimeout(timeout)
    s.sendall((token + "\n").encode())
    t_ask_sent = time.perf_counter()
    s.sendall((json.dumps({"op": "ask", "session": session, "message": message}) + "\n").encode())
    f = s.makefile("r", encoding="utf-8")
    t_first_delta = None
    kind = None
    text = []
    reasoning = []
    err = None
    degraded = []
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        ev = e.get("event")
        if ev in ("reasoning", "text") and e.get("delta"):
            if t_first_delta is None:
                t_first_delta = time.perf_counter()
                kind = ev
            (text if ev == "text" else reasoning).append(e["delta"])
        elif ev == "degraded":
            degraded.append("%s: %s" % (e.get("what"), e.get("remedy")))
        elif ev == "error":
            err = e.get("detail")
            break
        elif ev == "done":
            break
    t_done = time.perf_counter()
    try:
        s.close()
    except Exception:  # noqa: BLE001
        pass
    return dict(t_connect=t_connect, t_ask_sent=t_ask_sent, t_first_delta=t_first_delta,
                t_done=t_done, kind=kind, text="".join(text),
                reasoning_chars=len("".join(reasoning)), err=err, degraded=degraded)


MSG = "Reply with exactly the word READY and nothing else."


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--provider", required=True)  # ollama | llamacpp
    p.add_argument("--daemon-port", type=int, required=True)
    p.add_argument("--llamacpp-port", type=int, default=0)
    p.add_argument("--reps", type=int, default=8)
    p.add_argument("--out", required=True)
    p.add_argument("--dev", default="on")  # on | off
    a = p.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    before = bracket("before")
    if before["procs"]["cargo.exe"] or before["procs"]["rustc.exe"]:
        print(json.dumps({"REFUSED": "cargo/rustc running before the cell", "bracket": before}))
        sys.exit(2)

    # A fresh profile root per cell, via the flag `--serve` already takes.  The
    # first draft moved LOCALAPPDATA instead; that is also where llama-server.exe
    # is looked for, so it would have silently cost the llamacpp arm its engine
    # and fallen back to Ollama while every label still read "llamacpp".  The
    # flag has no such coupling.  Deleting the user's real default-profile would
    # also have worked and is not a trade worth making unasked.
    profile_root = out / ("profile-%s" % a.label)
    if profile_root.exists():
        shutil.rmtree(profile_root, ignore_errors=True)
    profile_root.mkdir(parents=True)

    env = dict(os.environ)

    argv = [str(BIN), "--serve", "--daemon-port", str(a.daemon_port),
            "--workspace", str(REPO), "--profile-root", str(profile_root),
            # NOT a default.  Without it the daemon announces `memory retrieval
            # WRITE-ONLY`, which is a DIFFERENT SYSTEM: no rerank, no retrieval
            # on the pre-request path, and potentially different injected memory
            # in the system prompt.  Both prior runs' daemons announced
            # `memory retrieval live · models/ms-marco-MiniLM-L-2-v2-ft-session-j`,
            # so measuring without it would measure something neither A nor B did.
            "--reranking", str(REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"),
            "--provider", "ollama" if a.provider == "ollama" else "llamacpp"]
    if a.provider != "ollama":
        argv += ["--llamacpp-port", str(a.llamacpp_port)]
    if a.dev == "on":
        argv += ["--dev"]

    t_spawn = time.perf_counter()
    d = Daemon(argv, env, out / ("daemon-%s.stderr.log" % a.label))
    if not d.wait_for("daemon listening on", timeout=300):
        d.stop()
        print(json.dumps({"FAILED": "daemon never listened", "label": a.label}))
        sys.exit(3)
    startup_ms = (time.perf_counter() - t_spawn) * 1e3

    # The announced provider line, so "which engine answered" is read out of the
    # running process rather than inferred from the flag that was passed.
    announced = [ln for _, ln in d.snapshot() if ln.startswith("marlowe:")]

    rows = []
    for i in range(a.reps):
        t_lo = time.perf_counter()
        r = ask(a.daemon_port, MSG, profile_root, "ttft-%d-%s" % (i, uuid.uuid4().hex[:8]))
        time.sleep(0.35)  # let the tail of the stderr drain before slicing the window
        t_hi = time.perf_counter()
        calls = parse_calls(d.snapshot(), t_lo, t_hi)
        first = calls[0] if calls else None
        row = {"rep": i + 1, "n_model_calls": len(calls)}
        row["socket_ttft_ms"] = (None if r["t_first_delta"] is None
                                 else (r["t_first_delta"] - r["t_connect"]) * 1e3)
        row["turn_total_ms"] = (r["t_done"] - r["t_connect"]) * 1e3
        row["first_delta_kind"] = r["kind"]
        row["reply"] = r["text"][:24]
        row["reasoning_chars"] = r["reasoning_chars"]
        row["err"] = r["err"]
        row["degraded"] = r["degraded"]
        if first and first["t_end_request"] and first["t_first_content_frame"]:
            row["dev_ttft_ms"] = (first["t_first_content_frame"] - first["t_end_request"]) * 1e3
            row["dev_ttft_anyframe_ms"] = (first["t_first_any_frame"] - first["t_end_request"]) * 1e3
            row["pre_request_ms"] = (first["t_end_request"] - r["t_ask_sent"]) * 1e3
            row["delivery_ms"] = (None if r["t_first_delta"] is None
                                  else (r["t_first_delta"] - first["t_first_content_frame"]) * 1e3)
            fr = first["frames"]
            row["frames_first_call"] = len(set(n for _, n, _, _ in fr))
            if len(fr) > 2:
                span = fr[-1][0] - first["t_first_content_frame"]
                row["gen_tok_per_s"] = ((row["frames_first_call"] - 1) / span) if span > 1e-9 else None
            row["system_chars"] = first["system_chars"]
            row["system_chars_sysline"] = first["system_chars_sysline"]
            row["messages"] = first["messages"]
            row["tools"] = first["tools"]
            row["roles"] = first["roles"]
        else:
            row["dev_ttft_ms"] = None
            row["note"] = "no parsed dev request/frame pair in this rep window"
        gen_span = row["turn_total_ms"] - (row["socket_ttft_ms"] or 0)
        row["gen_chars_per_s"] = (((r["reasoning_chars"] + len(r["text"])) / gen_span * 1e3)
                                  if gen_span > 0 else None)
        rows.append(row)
        print("  %s rep %d/%d: dev=%s socket=%s pre=%s deliv=%s sys=%s tools=%d calls=%d "
              "total=%s tok/s=%s reply=%r err=%s" % (
                  a.label, row["rep"], a.reps,
                  None if row["dev_ttft_ms"] is None else round(row["dev_ttft_ms"], 1),
                  None if row["socket_ttft_ms"] is None else round(row["socket_ttft_ms"], 1),
                  round(row.get("pre_request_ms") or 0, 1),
                  round(row.get("delivery_ms") or 0, 1),
                  row.get("system_chars"),
                  len((row.get("tools") or "").split(", ")) if row.get("tools") else 0,
                  row["n_model_calls"], round(row["turn_total_ms"], 1),
                  None if row.get("gen_tok_per_s") is None else round(row["gen_tok_per_s"], 1),
                  row["reply"], row["err"]), flush=True)

    after = bracket("after")
    d.stop()

    def med(key):
        vals = [r[key] for r in rows[1:] if r.get(key) is not None]
        if not vals:
            return None
        return {"n": len(vals), "median": round(statistics.median(vals), 1),
                "min": round(min(vals), 1), "max": round(max(vals), 1),
                "spread": round(max(vals) - min(vals), 1),
                "all": [round(v, 1) for v in vals]}

    result = {
        "label": a.label, "provider": a.provider, "dev": a.dev,
        "daemon_port": a.daemon_port, "llamacpp_port": a.llamacpp_port,
        "reps": a.reps, "rep1_discarded": True,
        "daemon_startup_ms": round(startup_ms, 1),
        "announced": announced,
        "bracket_before": before, "bracket_after": after,
        "dev_ttft_ms": med("dev_ttft_ms"),
        "dev_ttft_anyframe_ms": med("dev_ttft_anyframe_ms"),
        "socket_ttft_ms": med("socket_ttft_ms"),
        "pre_request_ms": med("pre_request_ms"),
        "delivery_ms": med("delivery_ms"),
        "turn_total_ms": med("turn_total_ms"),
        "gen_tok_per_s": med("gen_tok_per_s"),
        "gen_chars_per_s": med("gen_chars_per_s"),
        "rep1": dict((k, rows[0].get(k)) for k in ("dev_ttft_ms", "socket_ttft_ms", "turn_total_ms")),
        "system_chars_seen": sorted(set(r.get("system_chars") for r in rows if r.get("system_chars"))),
        "tools_seen": sorted(set(r.get("tools") for r in rows if r.get("tools"))),
        "messages_seen": sorted(set(r.get("messages") for r in rows if r.get("messages"))),
        "model_calls_seen": sorted(set(r["n_model_calls"] for r in rows)),
        "errors": [r["err"] for r in rows if r["err"]],
        "degraded": [x for r in rows for x in r["degraded"]],
        "rows": rows,
    }
    (out / ("%s.json" % a.label)).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(dict((k, v) for k, v in result.items() if k != "rows"), indent=2))


if __name__ == "__main__":
    main()
