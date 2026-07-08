"""Chaos vs skill: does the SAME policy fail in different places under
microscopic spawn jitter (the browser Best-of-X trick), and how does a
single-policy jitter-oracle compare to a cross-policy oracle?

Fixes the track-identity flaw in impassable_test.py part B: make_ground's
reroll loop and the grass picks consume the GLOBAL random stream, so two
sequential env runs with the same env seed see DIFFERENT terrain. Here every
track is pinned by seeding the global RNG immediately before generation and
injecting the resulting Ground into the env (env._make_ground patch), so all
policies/attempts run on byte-identical terrain.

Per track:
  - base_a: 1 unjittered attempt + K attempts with sub-pixel spawn jitter
    (+-1 px uniform, exactly like ai_play.html Best of X)
  - combo_a, rc_a: 1 unjittered attempt each (corrected consensus)

Run:  python\\.venv\\Scripts\\python.exe python\\diagnostics\\jitter_probe.py [n_tracks] [n_jitter]
"""
import os, sys, random
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
import env as E  # noqa: E402
from env import HillClimbEnv  # noqa: E402
from ground import make_ground  # noqa: E402
from constants import GROUND_DISTANCE, SPAWN_X  # noqa: E402

from constants import COMPLETE_PX  # completion = last vertex (score ~1883); single source

CKPTS = {
    "base_a": os.path.join(ROOT, "checkpoints", "base_a_8000000_steps.zip"),
    "combo_a": os.path.join(ROOT, "checkpoints", "ppo_p5_combo_a_6400000_steps.zip"),
    "rc_a": os.path.join(ROOT, "checkpoints", "rc_a_8000000_steps.zip"),
}


def run_episode(venv, model):
    obs = venv.reset()
    done = False
    info = {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a)
        done = bool(d[0])
        info = i[0]
    return float(info.get("max_distance_px", 0.0))


def main():
    n_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    n_jitter = int(sys.argv[2]) if len(sys.argv) > 2 else 7

    models = {name: PPO.load(p, device="auto") for name, p in CKPTS.items()}

    # Pin tracks: global-RNG seed right before generation makes make_ground
    # (rerolls + grass draws included) fully deterministic.
    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    base_solo = np.zeros(n_tracks)                  # unjittered base_a
    base_jit = np.zeros((n_tracks, n_jitter))       # jittered base_a
    others = {"combo_a": np.zeros(n_tracks), "rc_a": np.zeros(n_tracks)}

    orig_make_ground = E._make_ground
    try:
        for t, g in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
                max_episode_steps=5000, randomize_terrain=False,
                per_wheel_obs=True)]), 4)
            venv.reset()  # builds the world with the injected ground
            raw = venv.venv.envs[0].unwrapped
            sy = raw._ground.spawning_y

            # base_a unjittered (the canonical deterministic run)
            raw._js.set_spawn(float(SPAWN_X), float(sy))
            base_solo[t] = run_episode(venv, models["base_a"])

            # base_a jittered: +-1 px per axis, like ai_play.html Best of X
            jrng = random.Random(55_000 + t)
            for k in range(n_jitter):
                dx = (jrng.random() - 0.5) * 2.0
                dy = (jrng.random() - 0.5) * 2.0
                raw._js.set_spawn(SPAWN_X + dx, sy + dy)
                base_jit[t, k] = run_episode(venv, models["base_a"])

            # other policies, unjittered, SAME track (corrected consensus)
            raw._js.set_spawn(float(SPAWN_X), float(sy))
            for name in others:
                others[name][t] = run_episode(venv, models[name])

            venv.close()
            done_eps = (t + 1) * (1 + n_jitter + len(others))
            print(f"  [{t+1}/{n_tracks}] track done ({done_eps} episodes total)", flush=True)
    finally:
        E._make_ground = orig_make_ground

    comp = lambda d: d >= COMPLETE_PX
    all_base = np.concatenate([base_solo[:, None], base_jit], axis=1)  # (n, 1+K)

    print()
    print(f"[jitter_probe] {n_tracks} pinned tracks, base_a x (1 + {n_jitter} jittered), "
          f"+ combo_a/rc_a x1")
    print()
    print("--- Q1: does the SAME policy fail in different places under +-1px jitter? ---")
    nc = ~comp(all_base).any(axis=1)  # tracks base_a never completes
    spread = all_base.max(axis=1) - all_base.min(axis=1)
    print(f"  stop-position spread across base_a's {1+n_jitter} attempts (per track):")
    print(f"    median {np.median(spread):.0f}px  mean {spread.mean():.0f}px  "
          f"min {spread.min():.0f}  max {spread.max():.0f}")
    print(f"    tracks with spread < 800px (attempts agree where it fails): "
          f"{100*(spread < 800).mean():.0f}%")
    print()
    print("--- Q2: single-policy jitter-oracle vs cross-policy oracle ---")
    print(f"  base_a single attempt completes:            {100*comp(base_solo).mean():5.1f}%")
    print(f"  base_a jitter-oracle ({1+n_jitter} attempts):          "
          f"{100*comp(all_base).any(axis=1).mean():5.1f}%")
    cross = np.vstack([base_solo, others['combo_a'], others['rc_a']])
    print(f"  combo_a single:                              {100*comp(others['combo_a']).mean():5.1f}%")
    print(f"  rc_a single:                                 {100*comp(others['rc_a']).mean():5.1f}%")
    print(f"  3-policy oracle (1 attempt each, SAME track):{100*comp(cross).any(axis=0).mean():5.1f}%")
    n_complete = comp(cross).sum(axis=0)
    print(f"  tracks all 3 complete: {100*(n_complete == 3).mean():.1f}%   "
          f"some: {100*((n_complete > 0) & (n_complete < 3)).mean():.1f}%   "
          f"none: {100*(n_complete == 0).mean():.1f}%")
    print()
    print("--- Q3: mean-score view ---")
    sc = lambda d: np.maximum(0, (d - SPAWN_X) / 10.0)
    print(f"  base_a single-attempt mean score:   {sc(base_solo).mean():7.1f}")
    print(f"  base_a jitter-oracle mean score:    {sc(all_base.max(axis=1)).mean():7.1f}")
    print(f"  3-policy oracle mean score:         {sc(cross.max(axis=0)).mean():7.1f}")

    out = os.path.join(HERE, "jitter_probe_results.npz")
    np.savez(out, base_solo=base_solo, base_jit=base_jit,
             combo_a=others["combo_a"], rc_a=others["rc_a"])
    print(f"\n  raw distances saved to {out}")


if __name__ == "__main__":
    main()
