"""Parse tensorboard event files for each run, report peak ep_rew_mean
and the step it occurred at. Used to target intermediate checkpoint evals."""

import os
import sys
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TB_DIR = os.path.join(ROOT, "tb")


RUNS_OF_INTEREST = [
    "ppo_js_8m_1",
    "ppo_js_8m_exp1_perwheel_1",
    "ppo_js_8m_exp2_reward_1",
    "ppo_js_8m_exp3_long_1",
    "ppo_js_8m_exp4_deeper_1",
    "ppo_js_8m_exp5_nostack_1",
    "ppo_js_16m_0",
    "ppo_js_baseline2_1",
    "ppo_js_8m_combo_1",
]


def main():
    print(f"{'Run':<35s}  {'peak rew':>10s}  {'at step':>12s}  {'final rew':>10s}  {'final step':>12s}")
    print("-" * 90)
    for run in RUNS_OF_INTEREST:
        path = os.path.join(TB_DIR, run)
        if not os.path.isdir(path):
            print(f"{run:<35s}  (not found)")
            continue
        ea = EventAccumulator(path, size_guidance={'scalars': 0})
        ea.Reload()
        if "rollout/ep_rew_mean" not in ea.Tags()["scalars"]:
            print(f"{run:<35s}  (no rollout/ep_rew_mean)")
            continue
        events = ea.Scalars("rollout/ep_rew_mean")
        peak = max(events, key=lambda e: e.value)
        final = events[-1]
        print(f"{run:<35s}  {peak.value:>10.1f}  {peak.step:>12d}  "
              f"{final.value:>10.1f}  {final.step:>12d}")


if __name__ == "__main__":
    main()
