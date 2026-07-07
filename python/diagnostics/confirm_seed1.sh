#!/usr/bin/env bash
# 200-ep confirms (seed 42, independent of the seed-12345 scan) on seed-1's top
# candidates, plus a paired A/B on identical terrains. HCR_PER_WHEEL forced on.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
export HCR_PER_WHEEL=1
F () { grep -vE "Warning|warn|oneDNN|absl|InitializeLog|TF_ENABLE|pkg_resources"; }

echo "===== 200-ep confirms (seed 42, f=0) ====="
for c in rc_a_4400000 rc_a_8000000 base_a_8000000 base_a_6800000; do
  $PY diagnostics/rc_scan.py x --confirm "checkpoints/${c}_steps.zip" --episodes 200 --seed 42 2>&1 | F
done

echo
echo "===== Paired A/B: rc_a_4400000 (A) vs base_a_8000000 (B), 200 terrains seed 42 ====="
$PY eval.py checkpoints/rc_a_4400000_steps.zip \
   --ab checkpoints/base_a_8000000_steps.zip \
   --episodes 200 --random-terrain --deterministic --ab-deterministic --seed 42 2>&1 | F

echo "CONFIRM_SEED1_DONE"
