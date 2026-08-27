import ttft, sys, statistics, collections
C=ttft.CORPUS; STABLE=C[:12000]; MEMBODY=C[50000:53000]
UT=lambda j:C[60000+j*900:60000+j*900+800]; AT=lambda j:C[80000+j*900:80000+j*900+800]
TURNS=10
def arm(cell, placement):
    out=[]
    for i in range(TURNS):
        mk=ttft.unique_marker()
        msgs=[{"role":"system","content":STABLE+"\n\n"+mk+MEMBODY if placement=="in_system" else STABLE}]
        for j in range(i):
            msgs+=[{"role":"user","content":UT(j)},{"role":"assistant","content":AT(j)}]
        if placement!="in_system": msgs.append({"role":"user","content":mk+MEMBODY})
        msgs.append({"role":"user","content":UT(i)})
        out.append(ttft.one(cell,i,"","",32768,num_predict=8,messages=msgs))
    return out
ttft.one("rewarm",0,"","hi",32768,num_predict=2,record=False)   # reload the model into Ollama
ttft.control("I-pre")
runs=collections.defaultdict(list)
for r in range(3):
    for cell,pl in (("G_mem_changes","in_system"),("G2_mem_after_history","after")):
        for k,x in enumerate(arm(cell,pl)): runs[(cell,k)].append(x)
    print("  rep %d"%r); sys.stdout.flush()
print("\n turn | ptok  |  B: memory IN system   |  C: memory AFTER history")
print("      |       |   ttft     peval       |   ttft     peval")
for i in range(TURNS):
    b=runs[("G_mem_changes",i)]; c=runs[("G2_mem_after_history",i)]
    md=lambda v,k: statistics.median([x[k] for x in v])
    print(" %4d | %5d | %7.1f  %7.1f      | %7.1f  %7.1f"%(
        i, md(b,'prompt_eval_count'), md(b,'ttft_ms'), md(b,'prompt_eval_ms'),
        md(c,'ttft_ms'), md(c,'prompt_eval_ms')))
ttft.control("I-post")
