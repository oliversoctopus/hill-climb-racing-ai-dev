"""Ensemble Best-of-X: do two policies' failures complement each other?

The chaos caps a SINGLE policy's Best-of-X completion (~82.5% for the deployed
champion at K=30; ~17.5% of tracks never complete in 30 tries). If a
differently-trained policy (e.g. the spawn-jitter robustness model) solves some
of that hard core, then interleaving the two policies' attempts could push the
UNION above either alone. (Cross-SEED ensembles tested WORSE historically; a
differently-TRAINED policy is the open question.)

On the same pinned tracks we run K attempts of each model (canonical + jittered),
then compute Best-of-K completion for champ-only, robust-only, and MIXED
(alternating champ/robust, K attempts total). Mixed > max(single) => complementary.

Run: python autorun/ensemble_bestofx.py <ckpt_b.zip> [--ckpt-a <champ.zip>] [n_tracks=60] [k=16]
"""
import os, sys, random
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


def attempts(venv, raw, model, K, jseed):
    """K attempts: 0 canonical, 1.. jittered +-1px (same protocol as best_of_k)."""
    sy = raw._ground.spawning_y
    out = np.zeros(K)
    raw._js.set_spawn(float(SPAWN_X), float(sy))
    out[0] = run_episode(venv, model)
    jr = random.Random(jseed)
    for k in range(1, K):
        dx, dy = (jr.random() - 0.5) * 2.0, (jr.random() - 0.5) * 2.0
        raw._js.set_spawn(SPAWN_X + dx, sy + dy)
        out[k] = run_episode(venv, model)
    return out


def main():
    argv = sys.argv[1:]
    ckpt_a = DEFAULT_A
    if "--ckpt-a" in argv:
        i = argv.index("--ckpt-a"); ckpt_a = argv[i + 1]; del argv[i:i + 2]
    if not argv:
        sys.exit("usage: ensemble_bestofx.py <ckpt_b.zip> [--ckpt-a a.zip] [n_tracks] [k]")
    ckpt_b = argv[0]
    n_tracks = int(argv[1]) if len(argv) > 1 else 60
    K = int(argv[2]) if len(argv) > 2 else 16

    print(f"[ensemble] A={os.path.basename(ckpt_a)} B={os.path.basename(ckpt_b)}  "
          f"{n_tracks} tracks, K={K}", flush=True)
    A = PPO.load(ckpt_a, device="auto"); B = PPO.load(ckpt_b, device="auto")

    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    da = np.zeros((n_tracks, K)); db = np.zeros((n_tracks, K))
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
                max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)
            venv.reset(); raw = venv.venv.envs[0].unwrapped
            da[t] = attempts(venv, raw, A, K, 55_000 + t)
            db[t] = attempts(venv, raw, B, K, 77_000 + t)
            venv.close()
            print(f"  [{t+1}/{n_tracks}] done", flush=True)
    finally:
        E._make_ground = orig

    comp = lambda m: (m >= COMPLETE_PX)
    print(f"\n  {'K':>3s}  {'champ%':>7s}  {'robust%':>8s}  {'mixed%':>7s}  {'mix-best':>8s}")
    for k in range(1, K + 1):
        ca = 100.0 * comp(da[:, :k]).any(axis=1).mean()
        cb = 100.0 * comp(db[:, :k]).any(axis=1).mean()
        na = (k + 1) // 2; nb = k // 2            # interleave champ,robust,champ,...
        mixed = comp(da[:, :na]).any(axis=1) | comp(db[:, :nb]).any(axis=1)
        cm = 100.0 * mixed.mean()
        print(f"  {k:>3d}  {ca:>6.1f}%  {cb:>7.1f}%  {cm:>6.1f}%  {cm-max(ca,cb):>+7.1f}")

    # union at full K (best case for the ensemble) vs each alone
    ua = comp(da).any(axis=1); ub = comp(db).any(axis=1)
    print(f"\n  @K={K}: champ-only solves={int((ua&~ub).sum())}, "
          f"robust-only solves={int((ub&~ua).sum())}, both={int((ua&ub).sum())}, "
          f"neither={int((~ua&~ub).sum())}")
    print(f"  full union (champ OR robust, {K} each) = {100.0*(ua|ub).mean():.1f}%  "
          f"(champ alone {100.0*ua.mean():.1f}%, robust alone {100.0*ub.mean():.1f}%)")
    np.savez(os.path.join(HERE, "ensemble_results.npz"), da=da, db=db, complete_px=COMPLETE_PX)


if __name__ == "__main__":
    main()
