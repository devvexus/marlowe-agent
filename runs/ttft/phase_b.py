import ttft, sys
USER = ttft.CONTROL_USER
SIZES = [0, 3900, 15500, 23200, 46400]   # ~0, 1k, 4k, 6k, 12k tokens
ttft.control("B-pre")
for ch in SIZES:
    out = []
    for i in range(5):
        m = ttft.unique_marker()
        if ch == 0:
            out.append(ttft.one("B_syslen_%d" % ch, i, "", m + " " + USER, 32768, num_predict=16))
        else:
            out.append(ttft.one("B_syslen_%d" % ch, i, ttft.system_of(ch, marker=(100, m)),
                                USER, 32768, num_predict=16))
    print(ttft.summarize(out, "B_syslen %6d chars" % ch)); sys.stdout.flush()
ttft.control("B-post")
