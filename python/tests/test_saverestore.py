"""B1 verification: does JSPhysics.save_state()/restore_state() reproduce the
trajectory from a realistic, LIVE driving state? Quantifies the divergence
between a continuous policy rollout and a run restored from a snapshot taken
mid-climb, for three restore paths:

  in-place : restore into the SAME (still-alive) car -- isolates Box2D contact
             warm-start drift only. (Invalid if the car died in the horizon:
             head-ground contact destroys joints irreversibly.)
  reset    : reset_car() then restore -- the planner's death-safe path (rebuilds
             joints, then teleports each body; baked anchors re-satisfy them).
  fresh    : a brand-new V8 context built on the same terrain, then restore --
             worst case (no shared solver history at all).

We drive the deployed policy WARMUP steps to reach a live in-hills state, snap,
then play a fixed recorded action sequence both continuously and from each
restore. Small max-divergence => restore is a faithful model for search. (The
planner's EXECUTED path is always continuous, so even moderate drift here only
affects candidate *scoring*, not the final replay.)

Run: python tests/test_saverestore.py
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
from js_backend import JSPhysics                                    # noqa: E402
from ground import make_ground                                     # noqa: E402
from constants import SPAWN_X                                       # noqa: E402

CKPT = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")
WARMUP = 250          # policy steps to reach a live mid-climb state
HORIZON = 120         # steps to compare after the snapshot


def chassis(js):
    s = js.state()
    return np.array([s["x"], s["y"], s["angle"]]), bool(s["dead"])


def main():
    random.seed(987_010)
    ground = make_ground(None, difficulty=0.0)
    E._make_ground = lambda seed, difficulty=0.0, _g=ground: _g

    model = PPO.load(CKPT, device="auto")
    venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)
    obs = venv.reset()
    js = venv.venv.envs[0].unwrapped._js

    # Warm up with the policy to a live, climbing state.
    for _ in range(WARMUP):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a)
        if d[0]:
            sys.exit(f"car died during warmup (step<{WARMUP}); lower WARMUP")
    snap = js.save_state()
    s0, _ = chassis(js)

    # identity check: save -> restore (no step) must be exact.
    js.restore_state(snap)
    id_err = np.abs(chassis(js)[0] - s0).max()

    # Continuous baseline: record the policy's actions + positions for HORIZON.
    acts, cont = [], []
    died_at = None
    for t in range(HORIZON):
        a, _ = model.predict(obs, deterministic=True)
        acts.append(int(a[0]))
        obs, r, d, i = venv.step(a)
        pos, dead = chassis(js)
        cont.append(pos)
        if d[0]:
            died_at = t
            break
    cont = np.array(acts and cont)

    def replay(js_, actions):
        out = []
        for a in actions:
            js_.step(a)
            out.append(chassis(js_)[0])
        return np.array(out)

    results = {}
    # in-place AFTER divergence (the real planner case): js is at the continuous
    # endpoint now; restore back to snap and replay. Only valid if still alive
    # (a death in the horizon would have destroyed joints irreversibly).
    if died_at is None:
        js.restore_state(snap)
        results["in-place"] = replay(js, acts)
    # reset path (always valid, even if the horizon died)
    js.reset_car(); js.restore_state(snap)
    results["reset"] = replay(js, acts)
    # fresh context, same terrain
    fresh = JSPhysics(); fresh.build_world(ground.vectors, float(SPAWN_X), float(ground.spawning_y))
    fresh.restore_state(snap)
    results["fresh"] = replay(fresh, acts)

    def report(name, tr):
        m = min(len(tr), len(cont))
        d = np.linalg.norm(tr[:m, :2] - cont[:m, :2], axis=1)
        print(f"  {name:>8s}: max|dpos|={d.max()*30:7.3f}px  "
              f"final|dpos|={d[-1]*30:7.3f}px  "
              f"max|dangle|={np.abs(tr[:m,2]-cont[:m,2]).max():.4f}rad")

    print(f"[test_saverestore] warmup={WARMUP} horizon={len(cont)} (policy), 1 pinned track")
    print(f"  identity (save->restore->no step): |d|={id_err*30:.2e}px  (should be ~0)")
    print(f"  snapshot chassis x={s0[0]*30:.0f}px -> continuous endpoint x={cont[-1,0]*30:.0f}px"
          + (f"  (DIED at +{died_at})" if died_at is not None else "  (alive)"))
    for name in ("in-place", "reset", "fresh"):
        if name in results:
            report(name, results[name])

    # planning-mode death-safety: with _planning on, a branch that DIES must not
    # destroy joints, so a later in-place restore + benign replay still matches a
    # clean (no-death) replay from the same fresh context.
    f2 = JSPhysics(); f2.build_world(ground.vectors, float(SPAWN_X), float(ground.spawning_y))
    f2.restore_state(snap); f2.set_planning(True)
    bdead = False
    for _ in range(400):                       # spam reverse to flip & die
        f2.step(1)
        if f2.state()["dead"]:
            bdead = True; break
    f2.restore_state(snap)                      # restore after the death
    safe = replay(f2, acts)
    m = min(len(safe), len(results["fresh"]))
    corrupt = np.linalg.norm(safe[:m, :2] - results["fresh"][:m, :2], axis=1).max() * 30
    # If joints had been destroyed the car would fly apart -> divergence in the
    # thousands of px. A diff in the warm-start range (tens of px) means intact.
    verdict = "INTACT (warm-start range)" if corrupt < 600 else "CORRUPTED (joints destroyed!)"
    print(f"  planning death-safety: dying-branch died={bdead}, "
          f"replay-after-death vs clean-fresh diff={corrupt:.1f}px -> {verdict}")

    print("\n  divergence = Box2D contact warm-start drift (impulse cache not "
          "snapshotted). For short-horizon MPC scoring this is the model error; "
          "the committed/replayed path is continuous so it stays exact.")


if __name__ == "__main__":
    main()
