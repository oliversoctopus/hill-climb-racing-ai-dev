#!/usr/bin/env bash
# 200-ep confirms (seed 42) on seed-2's top candidates + paired A/B.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
export HCR_PER_WHEEL=1
F () { grep -vE "Warning|warn|oneDNN|absl|InitializeLog|TF_ENABLE|pkg_resources|^\[eval\] algo|loading|continuous"; }

echo "===== 200-ep confirms (seed 42, f=0) ====="
for c in rc_b_7800000 rc_b_8000000 base_b_7800000 base_b_8000000; do
  $PY diagnostics/rc_scan.py x --confirm "checkpoints/${c}_steps.zip" --episodes 200 --seed 42 2>&1 | F
done

echo
echo "===== Paired A/B: rc_b_7800000 (A) vs base_b_7800000 (B), 200 terrains seed 42 ====="
$PY eval.py checkpoints/rc_b_7800000_steps.zip \
   --ab checkpoints/base_b_7800000_steps.zip \
   --episodes 200 --random-terrain --deterministic --ab-deterministic --seed 42 2>&1 | F

echo "CONFIRM_SEED2_DONE"
