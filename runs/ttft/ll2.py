import ttft, statistics, sys
from llama_direct import call, cell
U=ttft.CONTROL_USER
BASE=ttft.system_of(15000, marker=(100,"[[LLBASE002]]"))
call("", "warm", 4)
cell("LL tiny prompt (no system)",        [""]*15, "Reply with one word.")
cell("LL 15k system COLD prefix",         [ttft.system_of(15000,marker=(100,ttft.unique_marker())) for _ in range(10)], U)
call(BASE,U,4)   # prime
cell("LL 15k system IDENTICAL repeat",    [BASE]*15, U)
# prompt-eval rate curve on llama.cpp, for the ceiling question
for ch in (3900, 23200, 46400):
    cell("LL syslen %6d cold"%ch, [ttft.system_of(ch,marker=(100,ttft.unique_marker())) for _ in range(5)], U)
