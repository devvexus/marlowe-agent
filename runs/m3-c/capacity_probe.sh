#!/usr/bin/env bash
# M3 Session C — the capacity model, MEASURED. AGENT-DIRECTORY §2a: "/api/ps is the
# measurement; the env vars are only declarations."
#
# Two readings of "3 workers loaded, out of memory" have different bottlenecks:
#   same role      -> one set of weights, KV cache multiplies  (OLLAMA_NUM_PARALLEL)
#   different role -> weights multiply                          (OLLAMA_MAX_LOADED_MODELS)
# This probe answers which one this machine is actually in.
set -u
H=http://127.0.0.1:11434
ps() { curl -s --max-time 10 "$H/api/ps"; }
warm() { curl -s --max-time 300 "$H/api/generate" -d "{\"model\":\"$1\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" > /dev/null; }

echo "=== declared env (User scope) ==="
powershell.exe -NoProfile -Command '
 foreach ($n in "OLLAMA_MAX_LOADED_MODELS","OLLAMA_NUM_PARALLEL","OLLAMA_KEEP_ALIVE","OLLAMA_FLASH_ATTENTION","OLLAMA_KV_CACHE_TYPE","OLLAMA_GPU_OVERHEAD") {
   $v = [Environment]::GetEnvironmentVariable($n,"User"); if ($null -eq $v) { $v = "<unset>" }
   $m = [Environment]::GetEnvironmentVariable($n,"Machine"); if ($null -eq $m) { $m = "<unset>" }
   "{0,-28} user={1,-10} machine={2}" -f $n,$v,$m }' 2>&1

echo
echo "=== ollama version ==="; curl -s --max-time 5 "$H/api/version"
echo; echo "=== baseline /api/ps (expect empty) ==="; ps

echo; echo "=== VRAM before ==="
nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv 2>&1 | head -3

for m in marlowe-dawn:9b-super marlowe-mini:4b-super marlowe-mini:2b; do
  echo; echo "=== warming $m ==="
  t0=$(date +%s%3N); warm "$m"; t1=$(date +%s%3N)
  echo "load+gen wall_ms=$((t1-t0))"
  echo "--- /api/ps after $m ---"; ps
  echo; echo "--- VRAM after $m ---"
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader 2>&1 | head -2
done

echo; echo "=== FINAL /api/ps — how many DISTINCT models stayed resident ==="; ps
echo; echo "=== FINAL VRAM ==="
nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv 2>&1 | head -3
