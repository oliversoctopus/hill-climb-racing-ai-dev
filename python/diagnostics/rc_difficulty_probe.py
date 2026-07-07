"""Probe the reverse-curriculum difficulty landscape with the EXISTING champion.

The champion (ppo_p5_combo_a) is 12-dim per-wheel, no rear vision — exactly the
obs the reverse-curriculum models use (GROUND_REAR_N=0). So we can run it on the
new env at fixed difficulties f to learn:
  - f=0 should reproduce the champion's ~1312 (validates f=0 == normal),
  - how scores degrade as f rises (is the frontier reachable, or an instant wall?).

This is the real pre-flight: pick rc-fmax-cap where the frontier is HARD but not
a dead-on-spawn wall (a difficulty with no progress teaches nothing useful).

Usage:
    HCR_PER_WHEEL is forced on here. Pass the champion ckpt and episodes/seed.
    python diagnostics/rc_difficulty_probe.py <ckpt> [episodes] [seed]
"""

import os
import sys
import time

import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
from env import HillClimbEnv  # noqa: E402


def eval_at_f(model, f, n_eps, seed, max_steps=5000):
    os.environ["HCR_DIFFICULTY"] = str(f)

    def mk():
        return HillClimbEnv(max_episode_steps=max_steps, seed=seed,
                            randomize_terrain=True, per_wheel_obs=True)

    env = DummyVecEnv([mk])
    env = VecFrameStack(env, n_stack=4)
    scores = np.zeros(n_eps, dtype=np.int64)
    for ep in range(n_eps):
        obs = env.reset()
        done = False
        info = {}
        while not done:
            a, _ = model.predict(obs, deterministic=True)
            obs, r, d, i = env.step(a)
            done = bool(d[0]); info = i[0]
        scores[ep] = info.get("score", 0)
    env.close()
    return scores


def main():
    ckpt = sys.argv[1]
    n_eps = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    model = PPO.load(ckpt, device="auto")
    print(f"[probe] champion={os.path.basename(ckpt)}  episodes={n_eps}  seed={seed}")
    print(f"{'f':>5s}  {'mean':>7s}  {'median':>7s}  {'q10':>5s}  {'q90':>5s}  "
          f"{'min':>5s}  {'max':>5s}  {'dead<100%':>9s}")
    print("-" * 64)
    for f in [0.0, 0.25, 0.5, 0.75, 1.0]:
        t0 = time.time()
        s = eval_at_f(model, f, n_eps, seed)
        q10, q90 = np.quantile(s, [0.1, 0.9])
        dead = 100 * (s < 100).mean()
        print(f"{f:>5.2f}  {s.mean():>7.1f}  {int(np.median(s)):>7d}  "
              f"{int(q10):>5d}  {int(q90):>5d}  {int(s.min()):>5d}  {int(s.max()):>5d}  "
              f"{dead:>8.1f}%  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
