"""Generalized TRUE-paired A/B on pinned tracks (terrain cancels), with per-model
frame-stack. Deterministic single attempt per track. Paired t-test on score diff.

Run: python autorun/paired_ab.py <ckpt_a> <ckpt_b> [--na 4] [--nb 4] [--tracks 120]
  diff is (A - B).
"""
import argparse, os, sys, random
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


def run_on(g, model, n_stack):
    E._make_ground = lambda s, difficulty=0.0, _g=g: _g
    venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), n_stack)
    obs = venv.reset(); done = False; info = {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a); done = bool(d[0]); info = i[0]
    venv.close()
    return int(info.get("score", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt_a"); ap.add_argument("ckpt_b")
    ap.add_argument("--na", type=int, default=4); ap.add_argument("--nb", type=int, default=4)
    ap.add_argument("--tracks", type=int, default=120)
    args = ap.parse_args()

    A = PPO.load(args.ckpt_a, device="auto"); B = PPO.load(args.ckpt_b, device="auto")
    tracks = []
    for t in range(args.tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    sa = np.zeros(args.tracks); sb = np.zeros(args.tracks)
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            sa[t] = run_on(g, A, args.na)
            sb[t] = run_on(g, B, args.nb)
            if (t + 1) % 30 == 0:
                print(f"  [{t+1}/{args.tracks}] A {sa[:t+1].mean():.0f}  B {sb[:t+1].mean():.0f}", flush=True)
    finally:
        E._make_ground = orig

    diff = sa - sb; n = args.tracks
    md = diff.mean(); sd = diff.std(ddof=1); se = sd / np.sqrt(n)
    t_stat = md / se if se > 0 else 0.0
    try:
        from scipy.stats import t as st
        p = float(2 * (1 - st.cdf(abs(t_stat), df=n - 1))); tc = float(st.ppf(0.975, df=n - 1))
    except Exception:
        from math import erfc, sqrt
        p = float(erfc(abs(t_stat) / sqrt(2))); tc = 1.96
    print(f"\n[paired_ab] {n} pinned tracks")
    print(f"  A={os.path.basename(args.ckpt_a)} (stack{args.na}) mean={sa.mean():.2f}")
    print(f"  B={os.path.basename(args.ckpt_b)} (stack{args.nb}) mean={sb.mean():.2f}")
    print(f"  paired diff (A-B): mean={md:+.2f} sd={sd:.1f} SE={se:.2f} "
          f"95%CI=[{md-tc*se:+.1f},{md+tc*se:+.1f}] t={t_stat:+.2f} p={p:.4f}")
    print(f"  per-track wins: A {int((diff>0).sum())}  B {int((diff<0).sum())}  ties {int((diff==0).sum())}")


if __name__ == "__main__":
    main()
