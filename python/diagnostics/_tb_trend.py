"""One-off: dump rollout/ep_rew_mean trends from tb logs to verify whether
training reward was still rising at the end of each run."""
import os
import sys

import numpy as np
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

HERE = os.path.dirname(os.path.abspath(__file__))
TB = os.path.join(os.path.dirname(HERE), "tb")

runs = sys.argv[1:] or sorted(os.listdir(TB))
print(f"{'run':<22s} {'@4M':>7s} {'@6M':>7s} {'@7M':>7s} {'@8M':>7s} {'last1M slope':>13s}")
for run in runs:
    path = os.path.join(TB, run)
    if not os.path.isdir(path):
        continue
    acc = EventAccumulator(path, size_guidance={"scalars": 0})
    acc.Reload()
    if "rollout/ep_rew_mean" not in acc.Tags().get("scalars", []):
        print(f"{run:<22s}  (no ep_rew_mean)")
        continue
    ev = acc.Scalars("rollout/ep_rew_mean")
    steps = np.array([e.step for e in ev], dtype=np.float64)
    vals = np.array([e.value for e in ev], dtype=np.float64)

    def at(target, win=300_000):
        m = np.abs(steps - target) <= win
        return f"{vals[m].mean():7.1f}" if m.any() else "      -"

    # Linear slope over the final 1M steps, per 1M steps.
    end = steps.max()
    m = steps >= end - 1_000_000
    slope = np.polyfit(steps[m], vals[m], 1)[0] * 1e6 if m.sum() > 2 else float("nan")
    print(f"{run:<22s} {at(4e6)} {at(6e6)} {at(7e6)} {at(8e6)} {slope:+10.1f}/1M")
