"""Snapshot-scan a run's checkpoints at NORMAL difficulty (f=0).

Final checkpoint != best (training reward is confounded by the difficulty
schedule). So eval every checkpoint in a step range on the SAME terrain set
(fixed seed) and rank by mean score. All evals are per-wheel, deterministic,
random-terrain, f=0 (the real game / eval distribution).

Usage:
    python diagnostics/rc_scan.py <run_name> [--min-step N] [--max-step N]
        [--every K] [--episodes 100] [--seed 12345]
    # then confirm the winner at 200 eps seed 42:
    python diagnostics/rc_scan.py <run_name> --confirm <ckpt.zip> --episodes 200 --seed 42
"""

import argparse
import glob
import os
import re
import sys
import time

import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"   # reverse-curriculum models are per-wheel
# Leave HCR_DIFFICULTY unset -> env f_max defaults to 0 -> f=0 (normal) eval.

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
from env import HillClimbEnv  # noqa: E402
from eval import _is_recurrent  # noqa: E402  (LSTM-checkpoint detection)

CKPT_DIR = os.path.join(ROOT, "checkpoints")


def eval_ckpt(ckpt, n_eps, seed, max_steps=5000):
    recurrent = _is_recurrent(ckpt)
    if recurrent:
        from sb3_contrib import RecurrentPPO
        model = RecurrentPPO.load(ckpt, device="auto")
    else:
        model = PPO.load(ckpt, device="auto")

    def mk():
        return HillClimbEnv(max_episode_steps=max_steps, seed=seed,
                            randomize_terrain=True, per_wheel_obs=True)

    env = DummyVecEnv([mk])
    if not recurrent:   # LSTM models train on single-frame obs (no stack)
        env = VecFrameStack(env, n_stack=4)
    scores = np.zeros(n_eps, dtype=np.int64)
    for ep in range(n_eps):
        obs = env.reset()
        done = False
        info = {}
        state = None
        episode_start = np.ones((1,), dtype=bool)
        while not done:
            a, state = model.predict(obs, state=state, episode_start=episode_start,
                                     deterministic=True)
            obs, r, d, i = env.step(a)
            episode_start = d
            done = bool(d[0]); info = i[0]
        scores[ep] = info.get("score", 0)
    env.close()
    return scores


def step_of(path):
    m = re.search(r"_(\d+)_steps\.zip$", path)
    return int(m.group(1)) if m else -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--min-step", type=int, default=4_000_000)
    ap.add_argument("--max-step", type=int, default=10**12)
    ap.add_argument("--every", type=int, default=1, help="Take every Kth checkpoint.")
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--confirm", default=None, help="Eval one specific ckpt path and stop.")
    args = ap.parse_args()

    if args.confirm:
        t0 = time.time()
        s = eval_ckpt(args.confirm, args.episodes, args.seed)
        q = np.quantile(s, [0.10, 0.25, 0.50, 0.75, 0.90])
        dead = 100 * (s < 100).mean()
        print(f"[confirm] {os.path.basename(args.confirm)}  "
              f"{args.episodes} eps  seed={args.seed}  ({time.time()-t0:.0f}s)")
        print(f"  mean={s.mean():.1f}  std={s.std():.1f}  "
              f"q10/25/50/75/90={int(q[0])}/{int(q[1])}/{int(q[2])}/{int(q[3])}/{int(q[4])}  "
              f"min={int(s.min())}  max={int(s.max())}  early-death<100={dead:.1f}%")
        return

    paths = sorted(glob.glob(os.path.join(CKPT_DIR, f"{args.run}_*_steps.zip")), key=step_of)
    paths = [p for p in paths if args.min_step <= step_of(p) <= args.max_step]
    paths = paths[::args.every]
    if not paths:
        print(f"no checkpoints matched {args.run} in [{args.min_step}, {args.max_step}]")
        return

    print(f"[scan] {args.run}: {len(paths)} ckpts, {args.episodes} eps each, "
          f"seed={args.seed}, f=0 (normal)")
    print(f"{'step':>10s}  {'mean':>7s}  {'median':>7s}  {'q10':>5s}  {'dead%':>6s}")
    print("-" * 44)
    best = (None, -1.0)
    for p in paths:
        s = eval_ckpt(p, args.episodes, args.seed)
        mean = s.mean()
        med = int(np.median(s))
        q10 = int(np.quantile(s, 0.1))
        dead = 100 * (s < 100).mean()
        flag = ""
        if mean > best[1]:
            best = (p, mean); flag = "  <-- best so far"
        print(f"{step_of(p):>10d}  {mean:>7.1f}  {med:>7d}  {q10:>5d}  {dead:>5.1f}%{flag}")
    print("-" * 44)
    print(f"[scan] best: {os.path.basename(best[0])}  mean={best[1]:.1f}")


if __name__ == "__main__":
    main()
