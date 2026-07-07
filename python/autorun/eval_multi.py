"""Eval a champion + several checkpoints on the SAME pinned tracks (champion run
once), report each mean + paired diff vs champion. For checking whether a
spiky curve point (e.g. seed2_resume 11.6M=1582 on 40 tracks) holds up.

Run: python autorun/eval_multi.py --champ <champ.zip> --tracks 200 <ckpt1> <ckpt2> ...
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


def run_on(g, model, n_stack=4):
    E._make_ground = lambda s, difficulty=0.0, _g=g: _g
    venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), n_stack)
    obs = venv.reset(); done = False; info = {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a); done = bool(d[0]); info = i[0]
    venv.close()
    return int(info.get("score", 0))


def pval(diff):
    n = len(diff); md = diff.mean(); sd = diff.std(ddof=1); se = sd / np.sqrt(n)
    t = md / se if se > 0 else 0.0
    try:
        from scipy.stats import t as st
        return md, se, float(2 * (1 - st.cdf(abs(t), df=n - 1)))
    except Exception:
        from math import erfc, sqrt
        return md, se, float(erfc(abs(t) / sqrt(2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--champ", required=True)
    ap.add_argument("--tracks", type=int, default=200)
    ap.add_argument("--seed-base", type=int, default=987_000,
                    help="pinned-track seed base; use a DIFFERENT base for a "
                         "held-out set (avoids winner's-curse on selected ckpts)")
    ap.add_argument("ckpts", nargs="+")
    args = ap.parse_args()

    champ = PPO.load(args.champ, device="auto")
    models = [(os.path.basename(c), PPO.load(c, device="auto")) for c in args.ckpts]
    tracks = []
    for t in range(args.tracks):
        random.seed(args.seed_base + t)
        tracks.append(make_ground(None, difficulty=0.0))

    champ_s = np.zeros(args.tracks)
    other_s = {name: np.zeros(args.tracks) for name, _ in models}
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            champ_s[t] = run_on(g, champ)
            for name, m in models:
                other_s[name][t] = run_on(g, m)
            if (t + 1) % 40 == 0:
                print(f"  [{t+1}/{args.tracks}]", flush=True)
    finally:
        E._make_ground = orig

    print(f"\n[eval_multi] {args.tracks} pinned tracks")
    print(f"  champ ({os.path.basename(args.champ)}): mean = {champ_s.mean():.2f}")
    for name, _ in models:
        s = other_s[name]
        md, se, p = pval(s - champ_s)
        print(f"  {name}: mean = {s.mean():.2f}  diff vs champ = {md:+.1f} (SE {se:.1f}, p={p:.4f})  "
              f"wins {int((s>champ_s).sum())}/{int((s<champ_s).sum())}")


if __name__ == "__main__":
    main()
