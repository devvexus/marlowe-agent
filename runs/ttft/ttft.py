#!/usr/bin/env python3
"""TTFT instrument for Ollama /api/chat.

Metric: wall-clock from the moment the request bytes are written to the socket
to the first frame carrying a NON-EMPTY `thinking` or `content` delta.
Also records Ollama's own final-frame accounting so prompt eval is separable
from generation.

Writes NDJSON to runs/ttft/raw.ndjson. Edits nothing.
"""
import http.client, json, os, subprocess, sys, time, statistics, argparse

HOST, PORT = "127.0.0.1", 11434
MODEL = "qwen3.5:9b"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw.ndjson")

# ---------------------------------------------------------------- filler text
def _corpus():
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    parts = []
    for p in ("CLAUDE.md", "STATE.md", "docs/design/ARCHITECTURE.md", "docs/design/DECISIONS.md"):
        f = os.path.join(root, p)
        if os.path.exists(f):
            parts.append(open(f, encoding="utf-8", errors="replace").read())
    body = "\n\n".join(parts)
    while len(body) < 120000:
        body += body
    return body

CORPUS = _corpus()

_CTR = os.path.join(os.path.dirname(OUT), ".marker_counter")
def unique_marker():
    """A 12-char marker never used before in this repo. The Phase-A control used
    repeated markers and read as a cache HIT at the end of the run, which looked
    exactly like the machine getting faster. Uniqueness is what makes it a control."""
    n = int(open(_CTR).read().strip() or 0) if os.path.exists(_CTR) else 0
    n += 1
    open(_CTR, "w").write(str(n))
    return "[[MK%06d]]" % n

CONTROL_CHARS = 15000
CONTROL_USER = "In one sentence, what is the core abstraction described above?"

def control(tag, reps=3):
    """The unchanging control cell: fixed shape, always a fresh prefix, so it pays
    full prompt eval every time and moves if the machine does."""
    out = [one("CONTROL@" + tag, i,
               system_of(CONTROL_CHARS, marker=(100, unique_marker())),
               CONTROL_USER, 32768, num_predict=16) for i in range(reps)]
    print(summarize(out, "CONTROL@" + tag)); sys.stdout.flush()
    return out

def system_of(chars, marker=None):
    """A system prompt of `chars` characters. `marker` (fixed width) is spliced in
    at a given position so a prefix can be perturbed without changing length."""
    s = CORPUS[:chars]
    if marker is not None:
        pos, txt = marker
        assert len(txt) + pos <= len(s), (pos, len(txt), len(s))
        s = s[:pos] + txt + s[pos + len(txt):]
    return s

# ---------------------------------------------------------------- machine state
def machine():
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15).stdout.strip()
        util, mem = [x.strip() for x in g.split(",")]
    except Exception:
        util, mem = None, None
    busy = False
    try:
        tl = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=20).stdout.lower()
        busy = ("cargo.exe" in tl) or ("rustc.exe" in tl) or ("link.exe" in tl)
    except Exception:
        pass
    return {"gpu_util": util, "gpu_mem_mib": mem, "build_running": busy}

# ---------------------------------------------------------------- one request
def one(cell, rep, system, user, num_ctx, think=True, num_predict=16,
        conn=None, keep_alive=None, extra=None, record=True,
        nodelay=True, single_write=False, messages=None, abort_after_first=False):
    body = {
        "model": MODEL,
        "messages": messages if messages is not None else
                    (([{"role": "system", "content": system}] if system else [])
                     + [{"role": "user", "content": user}]),
        "stream": True,
        "think": think,
        "options": {"num_predict": num_predict, "num_ctx": num_ctx},
    }
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    if extra:
        body["options"].update(extra)
    payload = json.dumps(body).encode()

    # Hazard form 6: never take a timing reading while a build holds the machine.
    # Wait it out and record how long, rather than abort or (worse) measure anyway.
    st = machine()
    waited = 0.0
    while st["build_running"]:
        if waited == 0.0:
            print("  [waiting: build running before %s rep %s]" % (cell, rep)); sys.stdout.flush()
        time.sleep(20); waited += 20
        st = machine()
        if waited > 1800:
            raise RuntimeError("build still running after 30 min; refusing to measure")
    if waited:
        time.sleep(20); waited += 20      # settle after a build exits
        print("  [resumed after %.0fs]" % waited); sys.stdout.flush()
    own_conn = conn is None
    t_pre = time.perf_counter()
    c = conn or http.client.HTTPConnection(HOST, PORT, timeout=300)
    if own_conn:
        c.connect()
    import socket as _s
    try:
        c.sock.setsockopt(_s.IPPROTO_TCP, _s.TCP_NODELAY, 1 if nodelay else 0)
    except OSError:
        pass
    t_conn = time.perf_counter()

    t0 = time.perf_counter()
    c.putrequest("POST", "/api/chat", skip_accept_encoding=True)
    c.putheader("Content-Type", "application/json")
    c.putheader("Content-Length", str(len(payload)))
    if own_conn:
        c.putheader("Connection", "close")
    if single_write:
        c.endheaders(payload)          # one write: head + body together
    else:
        c.endheaders()                 # the shipped Rust shape: two writes
        c.send(payload)

    resp = c.getresponse()
    t_hdr = time.perf_counter()
    ttft = None
    first_frame = None
    first_kind = None
    frames = 0
    final = {}
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        frames += 1
        if first_frame is None:
            first_frame = time.perf_counter() - t0
        try:
            f = json.loads(line)
        except Exception:
            continue
        m = f.get("message") or {}
        if ttft is None:
            for k in ("thinking", "reasoning", "reasoning_content", "content"):
                if m.get(k):
                    ttft = time.perf_counter() - t0
                    first_kind = k
                    break
            if ttft is None and m.get("tool_calls"):
                ttft = time.perf_counter() - t0
                first_kind = "tool_calls"
        if abort_after_first and ttft is not None:
            break
        if f.get("done"):
            final = f
    t_end = time.perf_counter()
    if own_conn:
        c.close()

    ns = lambda k: (final.get(k) / 1e6) if final.get(k) is not None else None
    rec = {
        "cell": cell, "rep": rep, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sys_chars": len(system), "num_ctx": num_ctx, "think": think,
        "num_predict": num_predict, "reuse_conn": not own_conn,
        "keep_alive": keep_alive,
        "connect_ms": round((t_conn - t_pre) * 1000, 3),
        "hdr_ms": round((t_hdr - t0) * 1000, 3),
        "first_frame_ms": round(first_frame * 1000, 2) if first_frame is not None else None,
        "ttft_ms": round(ttft * 1000, 2) if ttft is not None else None,
        "nodelay": nodelay, "single_write": single_write,
        "first_kind": first_kind,
        "total_ms": round((t_end - t0) * 1000, 2),
        "frames": frames,
        "load_ms": round(ns("load_duration"), 2) if ns("load_duration") else ns("load_duration"),
        "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_ms": round(ns("prompt_eval_duration"), 2) if ns("prompt_eval_duration") else ns("prompt_eval_duration"),
        "eval_count": final.get("eval_count"),
        "eval_ms": round(ns("eval_duration"), 2) if ns("eval_duration") else ns("eval_duration"),
        "total_duration_ms": round(ns("total_duration"), 2) if ns("total_duration") else ns("total_duration"),
        "done_reason": final.get("done_reason"),
        **{f"pre_{k}": v for k, v in st.items()},
        **{f"post_{k}": v for k, v in machine().items()},
    }
    rec["waited_s"] = waited
    if rec["post_build_running"]:
        rec["SUSPECT"] = "build appeared during cell"
    if record:
        with open(OUT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    return rec

def summarize(recs, label):
    v = [r["ttft_ms"] for r in recs if r["ttft_ms"] is not None]
    if not v:
        return f"{label:38s} NO TOKENS"
    pe = [r["prompt_eval_ms"] for r in recs if r["prompt_eval_ms"]]
    pc = [r["prompt_eval_count"] for r in recs if r["prompt_eval_count"]]
    return (f"{label:38s} n={len(v):2d} ttft med={statistics.median(v):8.1f} "
            f"min={min(v):8.1f} max={max(v):8.1f} "
            f"| peval med={statistics.median(pe) if pe else float('nan'):8.1f}ms "
            f"tok={statistics.median(pc) if pc else float('nan'):7.0f}")
