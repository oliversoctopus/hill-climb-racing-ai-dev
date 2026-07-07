#!/usr/bin/env bash
# Sequential reverse-curriculum A/B: rc vs normal-only baseline, 2 paired seeds.
# Pair 1 (rc_a, base_a) runs first so a full A/B exists even if cut short.
set -u
cd "$(dirname "$0")/.."   # -> python/
PY=.venv/Scripts/python.exe
COMMON="--timesteps 8000000 --n-envs 8 --vec subproc --per-wheel --reward-shaping \
        --reverse-curriculum --rc-warmup-frac 0.2 --rc-ramp-frac 0.5"
STATUS=diagnostics/rc_ab_status.txt
echo "RC A/B run started $(date)" > "$STATUS"

run () {
  local name="$1"; shift
  echo ">>> [$(date +%H:%M:%S)] START $name" | tee -a "$STATUS"
  $PY train.py $COMMON "$@" --name "$name" > "diagnostics/${name}.log" 2>&1
  local rc=$?
  echo "<<< [$(date +%H:%M:%S)] END   $name exit=$rc" | tee -a "$STATUS"
}

run rc_a   --rc-fmax-cap 1.0 --seed 1
run base_a --rc-fmax-cap 0.0 --seed 1
run rc_b   --rc-fmax-cap 1.0 --seed 2
run base_b --rc-fmax-cap 0.0 --seed 2

echo "ALL DONE $(date)" | tee -a "$STATUS"
