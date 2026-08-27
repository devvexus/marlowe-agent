"""The counterfactual, measured rather than argued: identical content, but the
per-turn changing block moved to AFTER the conversation history instead of being
concatenated onto the end of the system message."""
import ttft, sys
C = ttft.CORPUS
STABLE = C[:12000]; MEMBODY = C[50000:53000]
UT = lambda j: C[60000 + j*900 : 60000 + j*900 + 800]
AT = lambda j: C[80000 + j*900 : 80000 + j*900 + 800]
TURNS = 10

def run_arm(cell):
    out = []
    for i in range(TURNS):
        mk = ttft.unique_marker()
        msgs = [{"role": "system", "content": STABLE}]        # byte-identical, forever
        for j in range(i):
            msgs.append({"role": "user", "content": UT(j)})
            msgs.append({"role": "assistant", "content": AT(j)})
        # the changing block, AFTER history, immediately before the live turn
        msgs.append({"role": "user", "content": mk + MEMBODY})
        msgs.append({"role": "user", "content": UT(i)})
        r = ttft.one(cell, i, "", "", 32768, num_predict=8, messages=msgs)
        out.append(r)
        print("  turn %2d  ptok=%5d  ttft=%7.1f  load=%6.1f  peval=%7.1f" % (
            i, r['prompt_eval_count'], r['ttft_ms'], r['load_ms'], r['prompt_eval_ms'])); sys.stdout.flush()
    return out

ttft.control("G2-pre")
print("ARM C -- changing block moved AFTER history; system prefix byte-identical")
run_arm("G2_mem_after_history")
ttft.control("G2-post")
