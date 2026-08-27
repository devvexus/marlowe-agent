"""Production shape: system = [stable prefix][injected memory], then N conversation turns.
Injected memory is retrieved per turn, so in arm B it changes every turn -- and because it
sits at the END of the system message, everything after it (the WHOLE conversation) is
invalidated too. Arm A holds it byte-identical."""
import ttft, sys, statistics
C = ttft.CORPUS
STABLE = C[:12000]                       # view.stable + view.context
MEMBODY = C[50000:53000]                 # ~3000 chars of injected memory
UT = lambda j: C[60000 + j*900 : 60000 + j*900 + 800]
AT = lambda j: C[80000 + j*900 : 80000 + j*900 + 800]
TURNS = 10

def sysmsg(marker):
    return STABLE + "\n\n" + marker + MEMBODY

def run_arm(cell, changing):
    fixed = ttft.unique_marker()
    out = []
    for i in range(TURNS):
        mk = ttft.unique_marker() if changing else fixed
        msgs = [{"role": "system", "content": sysmsg(mk)}]
        for j in range(i):
            msgs.append({"role": "user", "content": UT(j)})
            msgs.append({"role": "assistant", "content": AT(j)})
        msgs.append({"role": "user", "content": UT(i)})
        r = ttft.one(cell, i, "", "", 32768, num_predict=8, messages=msgs)
        out.append(r)
        print("  turn %2d  ptok=%5d  ttft=%7.1f  load=%6.1f  peval=%7.1f" % (
            i, r['prompt_eval_count'], r['ttft_ms'], r['load_ms'], r['prompt_eval_ms']))
        sys.stdout.flush()
    return out

ttft.control("G-pre")
print("ARM A -- injected memory BYTE-IDENTICAL every turn")
a = run_arm("G_mem_stable", False)
print("ARM B -- injected memory CHANGES every turn (what ships today)")
b = run_arm("G_mem_changes", True)
ttft.control("G-post")
print()
print("turn | ptok  | A ttft  A peval | B ttft  B peval | B-A ttft")
for i in range(TURNS):
    print(" %3d | %5d | %7.1f %7.1f | %7.1f %7.1f | %+8.1f" % (
        i, b[i]['prompt_eval_count'], a[i]['ttft_ms'], a[i]['prompt_eval_ms'],
        b[i]['ttft_ms'], b[i]['prompt_eval_ms'], b[i]['ttft_ms']-a[i]['ttft_ms']))
