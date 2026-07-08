"""Direction C eval: paired single-shot A/B of two checkpoints on identical
pinned tracks, plus each model's completion rate.

Tracks are pinned the jitter_probe way (seed the global RNG right before
make_ground, inject the Ground via env._make_ground) so BOTH models drive the
exact same terrain from the exact same canonical spawn -- a TRUE paired test
(unlike eval.py --ab at f=0, which rerolls to different terrain; see CLAUDE.md
gotcha #10). Reports the paired mean difference with a t-stat.

Run: python autorun/robust_ab.py <ckpt_b.zip> [--ckpt-a <champion.zip>] [n_tracks=200]
  default ckpt_a = the deployed champion (seed2_resume_11611776_steps.zip).
"""
import os, sys, random, math
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from stable_baselines3 import PPO                                   # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
import env as E                                                     # noqa: E402
from env import HillClimbEnv                                        # noqa: E402
from ground import make_ground                                     # noqa: E402
from constants import GROUND_DISTANCE, SPAWN_X                      # noqa: E402

DEFAULT_A = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")
from constants import COMPLETE_PX  # completion = last vertex (score ~1883); single source


def run_episode(venv, model):
    obs = venv.reset(); done, info = False, {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a); done, info = bool(d[0]), i[0]
    return float(info.get("max_distance_px", 0.0))


def main():
    argv = sys.argv[1:]
    ckpt_a = DEFAULT_A
    if "--ckpt-a" in argv:
        i = argv.index("--ckpt-a"); ckpt_a = argv[i + 1]; del argv[i:i + 2]
    if not argv:
        sys.exit("usage: robust_ab.py <ckpt_b.zip> [--ckpt-a <a.zip>] [n_tracks]")
    ckpt_b = argv[0]
    n_tracks = int(argv[1]) if len(argv) > 1 else 200

    print(f"[robust_ab] A={os.path.basename(ckpt_a)}  B={os.path.basename(ckpt_b)}  "
          f"{n_tracks} pinned tracks, single-shot deterministic f=0", flush=True)
    A = PPO.load(ckpt_a, device="auto")
    B = PPO.load(ckpt_b, device="auto")

    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    sa = np.zeros(n_tracks); sb = np.zeros(n_tracks)
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            for model, out in ((A, sa), (B, sb)):
                venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
                    max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)
                venv.reset()
                raw = venv.venv.envs[0].unwrapped
                raw._js.set_spawn(float(SPAWN_X), float(raw._ground.spawning_y))
                out[t] = run_episode(venv, model)
                venv.close()
            if (t + 1) % 20 == 0:
                print(f"  [{t+1}/{n_tracks}]", flush=True)
    finally:
        E._make_ground = orig

    sc = lambda d: np.maximum(0.0, (d - SPAWN_X) / 10.0)
    ca = sc(sa); cb = sc(sb)
    diff = cb - ca
    sd = diff.std(ddof=1); se = sd / math.sqrt(n_tracks)
    tstat = diff.mean() / se if se > 0 else float("nan")
    comp_a = 100.0 * (sa >= COMPLETE_PX).mean()
    comp_b = 100.0 * (sb >= COMPLETE_PX).mean()

    print(f"\n[robust_ab] single-shot, {n_tracks} pinned tracks (paired)")
    print(f"  A mean score = {ca.mean():.1f}   completion = {comp_a:.1f}%")
    print(f"  B mean score = {cb.mean():.1f}   completion = {comp_b:.1f}%")
    print(f"  paired diff (B - A): mean = {diff.mean():+.1f}  sd = {sd:.1f}  "
          f"SE = {se:.1f}  t({n_tracks-1}) = {tstat:+.2f}")
    print(f"  B-better tracks = {int((diff>0).sum())}, A-better = {int((diff<0).sum())}, "
          f"tie = {int((diff==0).sum())}")
    print(f"\n  next: Best-of-K curve for B vs the champion's (run "
          f"`best_of_k.py 120 30 --ckpt {os.path.basename(ckpt_b)}` and compare to "
          f"best_of_k_seed2_resume_11611776_steps.npz).")
    np.savez(os.path.join(HERE, "robust_ab_results.npz"), sa=sa, sb=sb,
             complete_px=COMPLETE_PX)


if __name__ == "__main__":
    main()
