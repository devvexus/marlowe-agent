import ttft, statistics, sys, time

SYS_CHARS = 15000          # the real system message measured 12,556-17,353 chars
USER = "In one sentence, what is the core abstraction described above?"
NCTX = 32768
NP = 16
mk = lambda i: "[[MK%04d]]" % i          # fixed width, so length never changes

BASE = ttft.system_of(SYS_CHARS, marker=(100, mk(0)))
END_POS = SYS_CHARS - 200

def control(tag):
    """Unchanging control: a fresh-prefix request of fixed shape. Sensitive to
    machine contention because it pays full prompt eval every time."""
    out = []
    for i in range(3):
        out.append(ttft.one("CONTROL@" + tag, i,
                            ttft.system_of(SYS_CHARS, marker=(100, mk(9000 + i))),
                            USER, NCTX, num_predict=NP))
    print(ttft.summarize(out, "CONTROL@" + tag)); sys.stdout.flush()
    return out

def run(cell, systems):
    out = []
    for i, s in enumerate(systems):
        out.append(ttft.one(cell, i, s, USER, NCTX, num_predict=NP))
    print(ttft.summarize(out, cell)); sys.stdout.flush()
    return out

# warm the model so no cell pays load_duration
ttft.one("warm", 0, BASE, USER, NCTX, num_predict=NP, record=False)

control("A-pre")
run("A2_identical",   [BASE] * 6)
run("A4_end_mutated", [ttft.system_of(SYS_CHARS, marker=(100, mk(0)))[:END_POS]
                       + mk(100 + i)
                       + ttft.system_of(SYS_CHARS, marker=(100, mk(0)))[END_POS + 10:]
                       for i in range(5)])
run("A2b_identical_again", [BASE] * 3)
run("A3_start_mutated", [ttft.system_of(SYS_CHARS, marker=(100, mk(200 + i)))
                         for i in range(5)])
control("A-post")
