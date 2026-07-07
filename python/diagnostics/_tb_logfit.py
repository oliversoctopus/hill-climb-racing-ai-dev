"""One-off: is ep_rew_mean still rising per a log law, or has it flattened?

Fits v = a + b*ln(t) on steps in [0.5M, 6M], then tests the fit OUT OF SAMPLE
on 6M-8M (does the curve keep following the log trajectory?). Also reports the
log-law projected gain for 8M -> 16M (= b*ln(2)).
"""
import os
import sys

import numpy as np
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

HERE = os.path.dirname(os.path.abspath(__file__))
TB = os.path.join(os.path.dirname(HERE), "tb")

print(f"{'run':<14s} {'b':>6s} {'R2':>5s}  {'pred 6-8M':>9s} {'act 6-8M':>9s} "
      f"{'resid sd':>8s}  {'proj +8->16M':>12s}")
for run in sys.argv[1:]:
    acc = EventAccumulator(os.path.join(TB, run), size_guidance={"scalars": 0})
    acc.Reload()
    ev = acc.Scalars("rollout/ep_rew_mean")
    t = np.array([e.step for e in ev], dtype=np.float64)
    v = np.array([e.value for e in ev], dtype=np.float64)

    fit_m = (t >= 0.5e6) & (t <= 6e6)
    test_m = t > 6e6
    b, a = np.polyfit(np.log(t[fit_m]), v[fit_m], 1)
    pred = a + b * np.log(t)
    ss_res = np.sum((v[fit_m] - pred[fit_m]) ** 2)
    ss_tot = np.sum((v[fit_m] - v[fit_m].mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    resid_sd = np.std(v[fit_m] - pred[fit_m])
    print(f"{run:<14s} {b:>6.1f} {r2:>5.2f}  {pred[test_m].mean():>9.1f} "
          f"{v[test_m].mean():>9.1f} {resid_sd:>8.1f}  {b * np.log(2):>+12.1f}")
