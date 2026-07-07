#!/usr/bin/env bash
# Decay-isolation 200-ep confirms (seed 42, f=0). Compare nodecay finals to the
# base (decay) finals already measured: base_a@8M=1350.7, base_b@8M=1328.1.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
export HCR_PER_WHEEL=1
F () { grep -vE "Warning|warn|oneDNN|absl|InitializeLog|TF_ENABLE|pkg_resources"; }

# Coarse scan nodecay_b first (find its best), then confirm finals.
echo "===== nodecay_b coarse scan (60 ep, seed 12345) ====="
$PY diagnostics/rc_scan.py nodecay_b --min-step 1600000 --max-step 8000000 --every 2 \
   --episodes 60 --seed 12345 2>&1 | F | tail -6

echo
echo "===== 200-ep confirms (seed 42, f=0) ====="
for c in nodecay_a_8000000 nodecay_b_8000000; do
  $PY diagnostics/rc_scan.py x --confirm "checkpoints/${c}_steps.zip" --episodes 200 --seed 42 2>&1 | F
done
echo "CONFIRM_NODECAY_DONE"
