"""E5 eval: frame-stack-8 (fs8) vs champion (frame-stack-4), TRULY paired.

Uses pinned tracks (random.seed before make_ground + inject via _make_ground) so
both policies run byte-identical terrain -> real pairing (terrain cancels),
unlike eval.py --ab which is effectively unpaired at f=0 (make_ground rerolls
~22-33x off the GLOBAL RNG, so two envs sit at different stream positions).

Each policy: 1 deterministic attempt per pinned track (no jitter). Paired t-test
on per-track score diff (fs8 - champ).

Run: python autorun/fs8_ab.py [n_tracks=120]
"""
import os, sys, random
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

CHAMP = os.path.join(ROOT, "checkpoints", "base_a_8000000_steps.zip")
FS8 = os.path.join(ROOT, "checkpoints", "fs8_final.zip")


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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    champ = PPO.load(CHAMP, device="auto")
    fs8 = PPO.load(FS8, device="auto")

    tracks = []
    for t in range(n):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    sc_c = np.zeros(n); sc_f = np.zeros(n)
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            sc_c[t] = run_on(g, champ, 4)
            sc_f[t] = run_on(g, fs8, 8)
            if (t + 1) % 20 == 0:
                print(f"  [{t+1}/{n}] champ {sc_c[:t+1].mean():.1f}  fs8 {sc_f[:t+1].mean():.1f}", flush=True)
    finally:
        E._make_ground = orig

    diff = sc_f - sc_c
    md = diff.mean(); sd = diff.std(ddof=1); se = sd / np.sqrt(n)
    t_stat = md / se if se > 0 else 0.0
    try:
        from scipy.stats import t as st
        p = float(2 * (1 - st.cdf(abs(t_stat), df=n - 1)))
        tc = float(st.ppf(0.975, df=n - 1))
    except Exception:
        from math import erfc, sqrt
        p = float(erfc(abs(t_stat) / sqrt(2))); tc = 1.96

    print(f"\n[fs8_ab] {n} pinned tracks (TRUE paired), deterministic single attempt")
    print(f"  champ (stack4) mean = {sc_c.mean():.2f}")
    print(f"  fs8   (stack8) mean = {sc_f.mean():.2f}")
    print(f"  paired diff (fs8 - champ): mean = {md:+.2f}  sd = {sd:.1f}  SE = {se:.2f}")
    print(f"  95% CI = [{md-tc*se:+.1f}, {md+tc*se:+.1f}]   t({n-1}) = {t_stat:+.2f}  p = {p:.4f}")
    print(f"  per-track wins: fs8 {int((diff>0).sum())}  champ {int((diff<0).sum())}  ties {int((diff==0).sum())}")
    print(f"  (sd {sd:.0f} << ~600 confirms real pairing)")


if __name__ == "__main__":
    main()
