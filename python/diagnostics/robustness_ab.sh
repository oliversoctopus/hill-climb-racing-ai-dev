#!/usr/bin/env bash
# Robustness test: does the reverse curriculum help on HARD terrain (f>0)?
# Paired A/B on the UNBIASED final (8M) checkpoints, both seeds, at f=0.5 & 0.75.
# RC trained on hard terrain; if it's more robust this is where it should show.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
export HCR_PER_WHEEL=1
F () { grep -vE "Warning|warn|oneDNN|absl|InitializeLog|TF_ENABLE|pkg_resources|^\[eval\] algo|loading|continuous|~[0-9]+s left"; }

for f in 0.5 0.75; do
  export HCR_DIFFICULTY=$f
  for seed_pair in "rc_a_8000000 base_a_8000000 seed1" "rc_b_8000000 base_b_8000000 seed2"; do
    set -- $seed_pair
    echo "===== f=$f  $3:  A=$1  vs  B=$2  (200 terrains seed 42) ====="
    $PY eval.py "checkpoints/$1_steps.zip" --ab "checkpoints/$2_steps.zip" \
       --episodes 200 --random-terrain --deterministic --ab-deterministic --seed 42 2>&1 \
       | F | grep -E "mean score|paired diff \(|mean =|95% CI|t\(199|per-terrain"
    echo
  done
done
echo "ROBUSTNESS_DONE"
