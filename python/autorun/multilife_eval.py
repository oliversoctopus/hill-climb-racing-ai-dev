"""E3 eval: does adaptive multi-life (death markers) beat the champion's
i.i.d. chaos-reroll best-of-K, on identical pinned tracks?

Three conditions per pinned track, K attempts each:
  champ      : champion base_a, attempt 0 canonical + K-1 spawn-jittered (the
               deployed Best-of-X trick; pure chaos rerolls, NO memory).
  ml_nojit   : multi-life policy, K lives, SAME spawn every life. The ONLY thing
               that changes across lives is the death-marker obs -> if life 2's
               distance differs from life 1, the markers changed behaviour. This
               is the core scientific test (needs no jitter).
  ml_jit     : multi-life policy, K adaptive lives WITH spawn jitter on retries
               (the deployable mode: chaos rerolls + memory combined).

Reports completion% and oracle (best-of-K) mean score vs K for each, plus the
"markers changed behaviour" rate for ml_nojit.

Usage: python autorun/multilife_eval.py <ml_policy.zip> [--markers 2]
       [--lives 8] [--tracks 60]
"""
import argparse, os, sys, random
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
import env as E  # noqa: E402
from env import HillClimbEnv  # noqa: E402
from multilife_env import MultiLifeEnv  # noqa: E402
from ground import make_ground  # noqa: E402
from constants import GROUND_DISTANCE, SPAWN_X  # noqa: E402

from constants import COMPLETE_PX  # completion = last vertex (score ~1883); single source
CHAMP = os.path.join(ROOT, "checkpoints", "base_a_8000000_steps.zip")


def run_ep(venv, model):
    obs = venv.reset()
    done = False; info = {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a); done = bool(d[0]); info = i[0]
    return float(info.get("max_distance_px", 0.0))


def champ_attempts(g, model, K, tseed):
    E._make_ground = lambda s, difficulty=0.0, _g=g: _g
    venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)
    venv.reset(); raw = venv.venv.envs[0].unwrapped; sy = raw._ground.spawning_y
    out = np.zeros(K)
    raw._js.set_spawn(float(SPAWN_X), float(sy)); out[0] = run_ep(venv, model)
    jr = random.Random(55_000 + tseed)
    for k in range(1, K):
        dx = (jr.random() - 0.5) * 2.0; dy = (jr.random() - 0.5) * 2.0
        raw._js.set_spawn(SPAWN_X + dx, sy + dy); out[k] = run_ep(venv, model)
    venv.close(); return out


def ml_attempts(g, model, K, markers, jitter, tseed):
    E._make_ground = lambda s, difficulty=0.0, _g=g: _g
    venv = VecFrameStack(DummyVecEnv([lambda: MultiLifeEnv(
        lives_per_terrain=K, n_markers=markers, max_episode_steps=5000,
        randomize_terrain=False, per_wheel_obs=True)]), 4)
    raw = venv.venv.envs[0].unwrapped
    out = np.zeros(K)
    jr = random.Random(77_000 + tseed)
    for k in range(K):
        if jitter and k >= 1 and raw._ground is not None:
            sy = raw._ground.spawning_y
            dx = (jr.random() - 0.5) * 2.0; dy = (jr.random() - 0.5) * 2.0
            raw._js.set_spawn(SPAWN_X + dx, sy + dy)
        out[k] = run_ep(venv, model)  # MultiLifeEnv.reset handles grouping+markers
    venv.close(); return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ml_policy")
    ap.add_argument("--markers", type=int, default=2)
    ap.add_argument("--lives", type=int, default=8)
    ap.add_argument("--tracks", type=int, default=60)
    args = ap.parse_args()
    K = args.lives

    champ = PPO.load(CHAMP, device="auto")
    ml = PPO.load(args.ml_policy, device="auto")

    tracks = []
    for t in range(args.tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    d_champ = np.zeros((args.tracks, K))
    d_mlnj = np.zeros((args.tracks, K))
    d_mlj = np.zeros((args.tracks, K))
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            d_champ[t] = champ_attempts(g, champ, K, t)
            d_mlnj[t] = ml_attempts(g, ml, K, args.markers, False, t)
            d_mlj[t] = ml_attempts(g, ml, K, args.markers, True, t)
            print(f"  [{t+1}/{args.tracks}] done", flush=True)
    finally:
        E._make_ground = orig

    sc = lambda d: np.maximum(0.0, (d - SPAWN_X) / 10.0)
    comp = lambda d: d >= COMPLETE_PX

    def curve(name, d):
        print(f"\n[{name}] completion% / oracle mean score, vs K:")
        print(f"{'K':>3s} {'compl%':>7s} {'oracle':>7s}")
        for k in range(1, K + 1):
            pre = d[:, :k]
            print(f"{k:>3d} {100*comp(pre).any(axis=1).mean():>6.1f}% "
                  f"{sc(pre.max(axis=1)).mean():>7.1f}")

    curve("champ (chaos rerolls)", d_champ)
    curve("ml_nojit (markers only)", d_mlnj)
    curve("ml_jit (markers + jitter)", d_mlj)

    # Core scientific test: did markers change behaviour without jitter?
    changed = (np.abs(d_mlnj[:, 1] - d_mlnj[:, 0]) > 1.0).mean()
    print(f"\n[markers-changed-behaviour] ml_nojit life2 != life1 on "
          f"{100*changed:.1f}% of tracks (0% => markers ignored)")
    print(f"[final completion@K={K}] champ {100*comp(d_champ).any(1).mean():.1f}%  "
          f"ml_nojit {100*comp(d_mlnj).any(1).mean():.1f}%  "
          f"ml_jit {100*comp(d_mlj).any(1).mean():.1f}%")

    out = os.path.join(HERE, "multilife_eval_results.npz")
    np.savez(out, d_champ=d_champ, d_mlnj=d_mlnj, d_mlj=d_mlj)
    print(f"\n  raw -> {out}")


if __name__ == "__main__":
    main()
