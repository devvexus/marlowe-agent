import ttft, http.client, sys
U = ttft.CONTROL_USER
S = lambda: ttft.system_of(15000, marker=(100, ttft.unique_marker()))
def rep(cell, n=6, **kw):
    out=[ttft.one(cell,i,"", "Reply with one word.",32768,num_predict=4,**kw) for i in range(n)]
    print(ttft.summarize(out,cell))
    import statistics
    print("      load med=%.1f  first_frame med=%.1f  connect med=%.2f" % (
        statistics.median([r['load_ms'] for r in out]),
        statistics.median([r['first_frame_ms'] for r in out]),
        statistics.median([r['connect_ms'] for r in out]))); sys.stdout.flush()
    return out

ttft.control("C-pre")
rep("C1_fresh_conn_nodelay_2writes")                       # the shipped Rust shape, but NODELAY on
rep("C2_fresh_conn_NAGLE_2writes", nodelay=False)          # the shipped Rust shape exactly
rep("C3_fresh_conn_single_write", single_write=True)
# keep-alive: one connection, many requests
c = http.client.HTTPConnection("127.0.0.1", 11434, timeout=300); c.connect()
out=[ttft.one("C4_keepalive_reused",i,"", "Reply with one word.",32768,num_predict=4,conn=c) for i in range(6)]
c.close()
print(ttft.summarize(out,"C4_keepalive_reused"))
import statistics
print("      load med=%.1f" % statistics.median([r['load_ms'] for r in out])); sys.stdout.flush()
ttft.control("C-post")
