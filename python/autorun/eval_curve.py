"""Deterministic eval CURVE across a run's checkpoints, on PINNED tracks.

Unlike rc_scan.py (hardcoded n_stack=4; random-terrain points land on different
tracks each checkpoint due to the global-RNG reroll issue), this evaluates every
sampled checkpoint on the SAME pinned track set (inject via _make_ground) at the
correct frame-stack -> a low-noise, comparable-across-checkpoints curve. Lets you
see whether deterministic eval rises with the (linearly-rising) training reward.

Run: python autorun/eval_curve.py <run> --n-stack 4|8 [--tracks 40] [--every 8]
"""
import os, sys, glob, re, random, argparse
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
import env as E  # noqa: E402
from env import HillClimbEnv  # noqa: E402
from ground import make_ground  # noqa: E402
from constants import SPAWN_X  # noqa: E402

CKPT_DIR = os.path.join(ROOT, "checkpoints")


def step_of(p):
    m = re.search(r"_(\d+)_steps\.zip$", p)
    return int(m.group(1)) if m else -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--n-stack", type=int, default=4)
    ap.add_argument("--tracks", type=int, default=40)
    ap.add_argument("--every", type=int, default=8, help="take every Kth checkpoint")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(CKPT_DIR, f"{args.run}_*_steps.zip")), key=step_of)
    paths = paths[args.every - 1::args.every]  # ~80/every points, ending at final
    if not paths:
        print(f"no checkpoints for {args.run}"); return
    steps = [step_of(p) for p in paths]
    models = [PPO.load(p, device="auto") for p in paths]
    print(f"[curve] {args.run}: {len(paths)} ckpts (steps {steps[0]}..{steps[-1]}), "
          f"{args.tracks} pinned tracks, n_stack={args.n_stack}", flush=True)

    tracks = []
    for t in range(args.tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    scores = np.zeros((len(paths), args.tracks))
    orig = E._make_ground
    try:
        for ti, g in enumerate(tracks):
            E._make_ground = lambda s, difficulty=0.0, _g=g: _g
            venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
                max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), args.n_stack)
            for mi, model in enumerate(models):
                obs = venv.reset(); done = False; info = {}
                while not done:
                    a, _ = model.predict(obs, deterministic=True)
                    obs, r, d, i = venv.step(a); done = bool(d[0]); info = i[0]
                scores[mi, ti] = int(info.get("score", 0))
            venv.close()
            print(f"  track {ti+1}/{args.tracks} done", flush=True)
    finally:
        E._make_ground = orig

    print(f"\n[curve] {args.run} deterministic eval vs training step "
          f"({args.tracks} pinned tracks):")
    print(f"{'step':>10s} {'mean':>8s} {'median':>7s}")
    for mi, st in enumerate(steps):
        print(f"{st:>10d} {scores[mi].mean():>8.1f} {np.median(scores[mi]):>7.0f}")
    out = os.path.join(HERE, f"eval_curve_{args.run}.npz")
    np.savez(out, steps=np.array(steps), scores=scores)
    print(f"\n  raw -> {out}")


if __name__ == "__main__":
    main()
