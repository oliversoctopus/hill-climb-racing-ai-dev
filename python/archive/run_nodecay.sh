#!/usr/bin/env bash
# Isolate the LR/entropy decay schedule. base_a/base_b = combo + decay + normal
# terrain. These nodecay_a/nodecay_b = combo + NO decay (constant lr 3e-4, ent
# 0.01) + normal terrain, at the SAME seeds. Only difference = the decay schedule.
# (No --reverse-curriculum -> f_max stays 0 = normal, and no LR/ent decay.)
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
COMMON="--timesteps 8000000 --n-envs 8 --vec subproc --per-wheel --reward-shaping"
STATUS=diagnostics/nodecay_status.txt
echo "nodecay isolation started $(date)" > "$STATUS"

run () {
  local name="$1"; shift
  echo ">>> [$(date +%H:%M:%S)] START $name" | tee -a "$STATUS"
  $PY train.py $COMMON "$@" --name "$name" > "diagnostics/${name}.log" 2>&1
  echo "<<< [$(date +%H:%M:%S)] END   $name exit=$?" | tee -a "$STATUS"
}

run nodecay_a --seed 1
run nodecay_b --seed 2
echo "NODECAY ALL DONE $(date)" | tee -a "$STATUS"
