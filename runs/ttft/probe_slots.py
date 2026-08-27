import ttft, sys
SYS=15000; USER="In one sentence, what is the core abstraction described above?"
mk=lambda i:"[[MK%04d]]"%i
S=lambda i: ttft.system_of(SYS, marker=(100, mk(i)))

# 1. Truly fresh markers, never used before -> should be COLD if control is honest
fresh=[ttft.one("CTL_fresh",i,S(7000+i),USER,32768,num_predict=16) for i in range(3)]
print(ttft.summarize(fresh,"CTL_fresh (never-used markers)")); sys.stdout.flush()

# 2. Slot depth: distinct P1..P6, then revisit P1..P6 in order.
for i in range(6):
    ttft.one("slot_fill",i,S(7100+i),USER,32768,num_predict=16)
print("--- revisit, oldest first; peval low = that prompt still cached ---")
for i in range(6):
    r=ttft.one("slot_revisit",i,S(7100+i),USER,32768,num_predict=16)
    print("  revisit P%d  ttft=%8.1f  peval=%8.1f  tok=%s"%(i,r["ttft_ms"],r["prompt_eval_ms"] or -1,r["prompt_eval_count"]))
    sys.stdout.flush()
