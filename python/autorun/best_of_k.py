"""E1: Best-of-K deployment curve for the deployed champion.

The chaos finding (jitter_probe) says the real headroom on this game is NOT a
better single-shot policy but retrying with microscopic spawn jitter (the
ai_play.html "Best of X" trick). This quantifies exactly how completion rate and
mean score scale with K, so the browser deployment can be tuned with numbers.

Per pinned track: attempt 0 = canonical (no jitter), attempts 1..K_MAX-1 =
+-1px uniform spawn jitter (identical to ai_play.html). Best-of-K = the max over
the first K attempts. Tracks pinned by seeding the global RNG right before
make_ground and injecting the Ground (env._make_ground patch) so every attempt
runs byte-identical terrain.

Run: python autorun/best_of_k.py [n_tracks=60] [k_max=16] [--ckpt PATH]

--ckpt defaults to the deployed champion (seed2_resume_11611776_steps.zip). The
raw per-track x K attempt matrix is saved to best_of_k_<ckpt-stem>.npz so runs on
different checkpoints don't clobber each other (adaptive_bestofx.py reads it).
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
# The deployed champion (same obs/arch as base_a: per-wheel, lookahead 6, rear 0).
DEFAULT_CKPT = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")


def run_episode(venv, model):
    obs = venv.reset()
    done = False
    info = {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a)
        done = bool(d[0]); info = i[0]
    return float(info.get("max_distance_px", 0.0))


def main():
    argv = sys.argv[1:]
    ckpt = DEFAULT_CKPT
    if "--ckpt" in argv:
        i = argv.index("--ckpt")
        ckpt = argv[i + 1]
        del argv[i:i + 2]
    n_tracks = int(argv[0]) if len(argv) > 0 else 60
    k_max = int(argv[1]) if len(argv) > 1 else 16

    print(f"[best_of_k] checkpoint: {os.path.basename(ckpt)}", flush=True)
    model = PPO.load(ckpt, device="auto")

    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    dist = np.zeros((n_tracks, k_max))  # attempt 0 canonical, 1..K-1 jittered
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
                max_episode_steps=5000, randomize_terrain=False,
                per_wheel_obs=True)]), 4)
            venv.reset()
            raw = venv.venv.envs[0].unwrapped
            sy = raw._ground.spawning_y

            raw._js.set_spawn(float(SPAWN_X), float(sy))
            dist[t, 0] = run_episode(venv, model)
            jrng = random.Random(55_000 + t)
            for k in range(1, k_max):
                dx = (jrng.random() - 0.5) * 2.0
                dy = (jrng.random() - 0.5) * 2.0
                raw._js.set_spawn(SPAWN_X + dx, sy + dy)
                dist[t, k] = run_episode(venv, model)
            venv.close()
            print(f"  [{t+1}/{n_tracks}] done", flush=True)
    finally:
        E._make_ground = orig

    sc = lambda d: np.maximum(0.0, (d - SPAWN_X) / 10.0)
    comp = lambda d: d >= COMPLETE_PX

    print(f"\n[best_of_k] {n_tracks} pinned tracks, {os.path.basename(ckpt)}, K up to {k_max}")
    print(f"{'K':>3s}  {'completion%':>11s}  {'mean score':>10s}  {'median':>7s}  {'q10':>6s}")
    print("-" * 48)
    for k in range(1, k_max + 1):
        prefix = dist[:, :k]
        best = prefix.max(axis=1)           # best-of-K distance per track
        comp_rate = 100.0 * comp(prefix).any(axis=1).mean()
        s = sc(best)
        print(f"{k:>3d}  {comp_rate:>10.1f}%  {s.mean():>10.1f}  "
              f"{np.median(s):>7.0f}  {np.quantile(s,0.1):>6.0f}")

    stem = os.path.splitext(os.path.basename(ckpt))[0]
    out = os.path.join(HERE, f"best_of_k_{stem}.npz")
    np.savez(out, dist=dist, n_tracks=n_tracks, k_max=k_max,
             complete_px=COMPLETE_PX, spawn_x=SPAWN_X, ckpt=stem)
    print(f"\n  raw distances -> {out}")


if __name__ == "__main__":
    main()
