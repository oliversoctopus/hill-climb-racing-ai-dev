"""E6: can STOCHASTIC action sampling break the deterministic best-of-K ceiling?

E1 showed the champion's deterministic-argmax + ±1px spawn-jitter best-of-K
plateaus at ~70% completion (K>=10): ~30% of tracks where EVERY jittered attempt
dies the same way (chaos rerolls converge). Stochastic sampling perturbs the
action choices themselves (much larger than ±1px), which might cover trajectory
space the argmax never explores -> clearing sections argmax always fails.

If stochastic wins, it's a deployable change (ai_policy.js act() is argmax-only;
add sampling to its Best-of-X loop). Three conditions on identical pinned tracks:
  det_jit   : deterministic + ±1px jitter        (= E1 baseline / current deploy)
  stoch_jit : stochastic sampling + ±1px jitter
  stoch_nojit: stochastic sampling, same spawn    (diversity from sampling only)

Run: python autorun/best_of_k_stoch.py [n_tracks=60] [k_max=16]
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
from constants import GROUND_DISTANCE, SPAWN_X  # noqa: E402

END_PX = GROUND_DISTANCE - 350.0
COMPLETE_PX = END_PX - 600.0
CKPT = os.path.join(ROOT, "checkpoints", "base_a_8000000_steps.zip")


def run_episode(venv, model, deterministic):
    obs = venv.reset(); done = False; info = {}
    while not done:
        a, _ = model.predict(obs, deterministic=deterministic)
        obs, r, d, i = venv.step(a); done = bool(d[0]); info = i[0]
    return float(info.get("max_distance_px", 0.0))


def attempts(g, model, K, tseed, deterministic, jitter):
    E._make_ground = lambda s, difficulty=0.0, _g=g: _g
    venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)
    venv.reset(); raw = venv.venv.envs[0].unwrapped; sy = raw._ground.spawning_y
    out = np.zeros(K)
    jr = random.Random(55_000 + tseed)
    for k in range(K):
        if jitter and k >= 1:
            dx = (jr.random() - 0.5) * 2.0; dy = (jr.random() - 0.5) * 2.0
            raw._js.set_spawn(SPAWN_X + dx, sy + dy)
        else:
            raw._js.set_spawn(float(SPAWN_X), float(sy))
        out[k] = run_episode(venv, model, deterministic)
    venv.close(); return out


def main():
    n_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    k_max = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    model = PPO.load(CKPT, device="auto")

    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    dj = np.zeros((n_tracks, k_max)); sj = np.zeros((n_tracks, k_max)); sn = np.zeros((n_tracks, k_max))
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            dj[t] = attempts(g, model, k_max, t, True, True)
            sj[t] = attempts(g, model, k_max, t, False, True)
            sn[t] = attempts(g, model, k_max, t, False, False)
            print(f"  [{t+1}/{n_tracks}] done", flush=True)
    finally:
        E._make_ground = orig

    sc = lambda d: np.maximum(0.0, (d - SPAWN_X) / 10.0)
    comp = lambda d: d >= COMPLETE_PX

    def curve(name, d):
        print(f"\n[{name}] completion% / oracle mean score, vs K:")
        for k in (1, 2, 3, 5, 8, 10, 12, 16):
            if k > k_max: break
            pre = d[:, :k]
            print(f"  K={k:>2d}  {100*comp(pre).any(axis=1).mean():>5.1f}%  {sc(pre.max(axis=1)).mean():>7.1f}")

    curve("det_jit (E1 baseline / current deploy)", dj)
    curve("stoch_jit", sj)
    curve("stoch_nojit", sn)
    out = os.path.join(HERE, "best_of_k_stoch_results.npz")
    np.savez(out, det_jit=dj, stoch_jit=sj, stoch_nojit=sn)
    print(f"\n  raw -> {out}")


if __name__ == "__main__":
    main()
