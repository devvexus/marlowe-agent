import ttft, http.client, json, time, statistics, sys
PORT=8080
def call(system, user, n_predict=16, conn=None):
    body={"model":"m","messages":([{"role":"system","content":system}] if system else [])+
          [{"role":"user","content":user}],"stream":True,"max_tokens":n_predict,
          "stream_options":{"include_usage":True},"timings_per_token":True}
    p=json.dumps(body).encode()
    own = conn is None
    t_pre=time.perf_counter()
    c=conn or http.client.HTTPConnection("127.0.0.1",PORT,timeout=300)
    if own: c.connect()
    t_conn=time.perf_counter(); t0=time.perf_counter()
    c.request("POST","/v1/chat/completions",p,{"Content-Type":"application/json"})
    r=c.getresponse(); ttft_=None; tim={}
    while True:
        l=r.readline()
        if not l: break
        l=l.strip()
        if not l.startswith(b"data:"): continue
        d=l[5:].strip()
        if d==b"[DONE]": break
        try: f=json.loads(d)
        except Exception: continue
        if f.get("timings"): tim=f["timings"]
        for ch in f.get("choices",[]):
            dl=ch.get("delta") or {}
            if ttft_ is None and (dl.get("content") or dl.get("reasoning_content")):
                ttft_=time.perf_counter()-t0
    if own: c.close()
    return {"ttft_ms":(ttft_*1000) if ttft_ else None,"connect_ms":(t_conn-t_pre)*1000,
            "pp_ms":tim.get("prompt_ms"),"pp_n":tim.get("prompt_n"),"pred_ms":tim.get("predicted_ms")}

def cell(label, systems, user, n=None):
    out=[call(s,user) for s in systems]
    v=[r["ttft_ms"] for r in out if r["ttft_ms"]]
    pp=[r["pp_ms"] for r in out if r["pp_ms"]]
    print("%-40s n=%2d ttft med=%8.1f min=%8.1f max=%8.1f | prompt_ms med=%8.1f n_tok=%s"%(
        label,len(v),statistics.median(v),min(v),max(v),
        statistics.median(pp) if pp else float('nan'), out[-1]["pp_n"])); sys.stdout.flush()
    return out

U=ttft.CONTROL_USER
call("", "warmup", 4)                                            # warm
BASE=ttft.system_of(15000, marker=(100,"[[LLBASE001]]"))
cell("LL tiny prompt (no system)", [""]*8, "Reply with one word.")
cell("LL 15000-char system, COLD prefix", [ttft.system_of(15000,marker=(100,ttft.unique_marker())) for _ in range(6)], U)
cell("LL 15000-char system, IDENTICAL repeat", [BASE]*6, U)
