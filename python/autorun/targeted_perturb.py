"""A2: targeted-perturbation Best-of-X vs blind +-1px-jitter Best-of-X (paired).

Blind Best-of-X diversifies attempts only by a +-1px spawn nudge, which the chaos
amplifies into different whole-track trajectories. But when a track has a
specific wall (the deathmap shows the deployed model stalls in the steep back
third), it may be better to spend retries doing something DIFFERENT *right at the
wall* -- a poor-man's, model-free cousin of the MPC planner, and the kind of
"targeted noise beats uniform noise" the robustness literature reports.

This harness runs, on the SAME pinned tracks (paired), two arms at matched K:
  blind    : attempt 0 canonical, attempts 1.. = +-1px spawn jitter (== best_of_k).
  targeted : attempt 0 canonical; each retry replays the policy but, for a short
             window ending just before the deepest death seen so far, FORCES an
             off-policy action (coast / brake / full-gas) -- plus +-1px jitter so
             repeats still diversify.

Reports completion% vs K for both arms, and the paired per-track win/loss.

Run: python autorun/targeted_perturb.py [n_tracks=40] [k=12] [--ckpt PATH]
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

DEFAULT_CKPT = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")
from constants import COMPLETE_PX  # completion = last vertex (score ~1883); single source

# Perturbation menu: (forced_action, pre_px before the wall, width_ticks).
# action 0=forward(gas), 1=reverse(brake/back), 2=off(coast).
VARIANTS = [
    (2, 120, 10),   # coast into the wall
    (0, 120, 12),   # full gas earlier
    (1, 90, 8),     # tap brake just before
    (2, 220, 14),   # coast from further back (carry less speed over a crest)
    (0, 60, 10),    # late gas
    (1, 160, 12),   # back off then re-commit
]


def run(venv, model, plan):
    """One deterministic attempt. If plan is given, force plan['action'] for
    plan['width'] ticks once max_distance_px first reaches the wall window."""
    obs = venv.reset()
    done, info = False, {}
    fired, rem = False, 0
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        act = int(a[0])
        if plan is not None:
            md = info.get("max_distance_px", 0.0)
            if not fired and md >= plan["trigger_x"] - plan["pre"]:
                fired, rem = True, plan["width"]
            if rem > 0:
                act, rem = plan["action"], rem - 1
        obs, r, d, i = venv.step([act])
        done, info = bool(d[0]), i[0]
    return float(info.get("max_distance_px", 0.0))


def make_venv():
    return VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)


def main():
    argv = sys.argv[1:]
    ckpt = DEFAULT_CKPT
    if "--ckpt" in argv:
        i = argv.index("--ckpt"); ckpt = argv[i + 1]; del argv[i:i + 2]
    n_tracks = int(argv[0]) if len(argv) > 0 else 40
    K = int(argv[1]) if len(argv) > 1 else 12

    print(f"[targeted_perturb] {os.path.basename(ckpt)}  {n_tracks} tracks, K={K}", flush=True)
    model = PPO.load(ckpt, device="auto")

    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    blind = np.zeros((n_tracks, K))
    targ = np.zeros((n_tracks, K))
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            venv = make_venv(); venv.reset()
            raw = venv.venv.envs[0].unwrapped
            sy = raw._ground.spawning_y
            jr = random.Random(55_000 + t)

            # --- blind arm: canonical + K-1 jittered ---
            raw._js.set_spawn(float(SPAWN_X), float(sy))
            blind[t, 0] = run(venv, model, None)
            for k in range(1, K):
                dx, dy = (jr.random() - 0.5) * 2.0, (jr.random() - 0.5) * 2.0
                raw._js.set_spawn(SPAWN_X + dx, sy + dy)
                blind[t, k] = run(venv, model, None)

            # --- targeted arm: canonical, then variants aimed at deepest death ---
            raw._js.set_spawn(float(SPAWN_X), float(sy))
            targ[t, 0] = run(venv, model, None)
            best_death = targ[t, 0]
            for k in range(1, K):
                act, pre, width = VARIANTS[(k - 1) % len(VARIANTS)]
                plan = {"trigger_x": best_death, "action": act, "pre": pre, "width": width}
                dx, dy = (jr.random() - 0.5) * 2.0, (jr.random() - 0.5) * 2.0
                raw._js.set_spawn(SPAWN_X + dx, sy + dy)
                targ[t, k] = run(venv, model, plan)
                if targ[t, k] < COMPLETE_PX:           # advance the target if we got deeper
                    best_death = max(best_death, targ[t, k])
            venv.close()
            print(f"  [{t+1}/{n_tracks}] done", flush=True)
    finally:
        E._make_ground = orig

    comp = lambda m, k: 100.0 * (m[:, :k] >= COMPLETE_PX).any(axis=1).mean()
    print(f"\n  {'K':>3s}  {'blind%':>7s}  {'targeted%':>9s}  {'delta':>6s}")
    for k in range(1, K + 1):
        b, tg = comp(blind, k), comp(targ, k)
        print(f"  {k:>3d}  {b:>6.1f}%  {tg:>8.1f}%  {tg-b:>+5.1f}")

    # paired at full K: which arm solved which track
    bsolved = (blind >= COMPLETE_PX).any(axis=1)
    tsolved = (targ >= COMPLETE_PX).any(axis=1)
    only_t = int((tsolved & ~bsolved).sum())
    only_b = int((bsolved & ~tsolved).sum())
    print(f"\n  paired @K={K}: targeted-only solves={only_t}, blind-only solves={only_b}, "
          f"both={int((bsolved & tsolved).sum())}, neither={int((~bsolved & ~tsolved).sum())}")
    out = os.path.join(HERE, "targeted_perturb_results.npz")
    np.savez(out, blind=blind, targ=targ, complete_px=COMPLETE_PX)
    print(f"  raw -> {out}")


if __name__ == "__main__":
    main()
