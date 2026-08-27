import ttft, sys, statistics, collections
C = ttft.CORPUS
STABLE = C[:12000]; MEMBODY = C[50000:53000]
UT = lambda j: C[60000 + j*900 : 60000 + j*900 + 800]
AT = lambda j: C[80000 + j*900 : 80000 + j*900 + 800]
TURNS = 10

def arm(cell, placement):
    out=[]
    for i in range(TURNS):
        mk = ttft.unique_marker()
        if placement == "in_system":
            msgs=[{"role":"system","content":STABLE+"\n\n"+mk+MEMBODY}]
        else:
            msgs=[{"role":"system","content":STABLE}]
        for j in range(i):
            msgs.append({"role":"user","content":UT(j)}); msgs.append({"role":"assistant","content":AT(j)})
        if placement != "in_system":
            msgs.append({"role":"user","content":mk+MEMBODY})
        msgs.append({"role":"user","content":UT(i)})
        out.append(ttft.one(cell,i,"","",32768,num_predict=8,messages=msgs))
    return out

ttft.control("H-pre")
runs=collections.defaultdict(list)
for r in range(2):
    for cell,pl in (("G_mem_changes","in_system"),("G2_mem_after_history","after")):
        for k,x in enumerate(arm(cell,pl)): runs[(cell,k)].append(x)
    print("  rep %d done"%r); sys.stdout.flush()

print("\nturn | ptok  | B(in system) ttft peval | C(after history) ttft peval")
for i in range(TURNS):
    b=runs[("G_mem_changes",i)]; c=runs[("G2_mem_after_history",i)]
    md=lambda v,k: statistics.median([x[k] for x in v])
    print(" %3d | %5d | %8.1f %8.1f      | %8.1f %8.1f" % (
        i, md(b,'prompt_eval_count'), md(b,'ttft_ms'), md(b,'prompt_eval_ms'),
        md(c,'ttft_ms'), md(c,'prompt_eval_ms')))
ttft.control("H-mid")

# think on/off, at the product's shape, cold prefix
for th in (True, False):
    out=[ttft.one("H_think_%s"%th,i,ttft.system_of(15000,marker=(100,ttft.unique_marker())),
                  ttft.CONTROL_USER,32768,think=th,num_predict=16) for i in range(5)]
    print(ttft.summarize(out,"think=%s"%th),
          " first_kind=",collections.Counter(r['first_kind'] for r in out)); sys.stdout.flush()

# num_predict, at the product's shape
for np_ in (16, 512, 8192):
    out=[ttft.one("H_npredict_%d"%np_,i,ttft.system_of(15000,marker=(100,ttft.unique_marker())),
                  ttft.CONTROL_USER,32768,num_predict=np_) for i in range(5)]
    print(ttft.summarize(out,"num_predict=%d"%np_)); sys.stdout.flush()
ttft.control("H-post")
