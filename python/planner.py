"""B2: receding-horizon MPC overlay on the frozen policy (the "foresight" lever).

The deployed policy is reactive: it commits to a per-tick argmax and cannot look
through the bifurcations that the chaos finding shows decide survival in the
steep back third. Here we add a planner on TOP of the frozen policy using the
exact JS simulator as the world model.

Design (informed by tests/test_saverestore.py):
  - The REAL trajectory runs on a clean env (committed actions only) so the
    executed/replayable path stays exact.
  - A SCRATCH HillClimbEnv on the same terrain, with its JS backend in planning
    mode (a lethal head-ground contact only FLAGS death, joints survive -> the
    in-place restore stays valid across branches), rolls candidate futures with
    the POLICY IN THE LOOP: a candidate = "take action a now, then follow the
    frozen policy for H ticks". This respects the policy's reactivity (naive
    fixed-action rollouts underperform the policy -- measured).
  - We engage only in the back third, plan every `cadence` ticks, and OVERRIDE
    only when the policy's own rollout is predicted to DIE within H while an
    alternative first action survives. The override is held for the cadence,
    then the policy resumes. Re-planning on the TRUE state corrects the Box2D
    warm-start model error continuously.

Run (feasibility probe, policy-only vs policy+MPC on pinned tracks):
  python planner.py [n_tracks=15] [--ckpt PATH] [--horizon 20] [--cadence 6]
"""
import os, sys, random
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stable_baselines3 import PPO                                   # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa: E402
import env as E                                                     # noqa: E402
from env import (HillClimbEnv, GROUND_LOOKAHEAD_SKIP, GROUND_REAR_N,  # noqa: E402
                 GROUND_REAR_SKIP)
from js_backend import JSPhysics                                    # noqa: E402
from ground import make_ground                                     # noqa: E402
from constants import GROUND_DISTANCE, SPAWN_X, SCALE              # noqa: E402

DEFAULT_CKPT = os.path.join(HERE, "checkpoints", "seed2_resume_11611776_steps.zip")
END_PX = GROUND_DISTANCE - 350.0
COMPLETE_PX = END_PX - 600.0
ENGAGE_FROM = 0.45 * GROUND_DISTANCE      # only plan in the steep back of the track


class MpcPlanner:
    def __init__(self, ground, model, lookahead_n=6, horizon=20, cadence=6):
        self.model = model
        self.H, self.cadence = horizon, cadence
        self.nobs = 6 + lookahead_n + GROUND_REAR_N
        # scratch env: gives _build_obs + coyote; its JS backend is planning-mode.
        self.se = HillClimbEnv(per_wheel_obs=True, lookahead_n=lookahead_n,
                               randomize_terrain=False)
        self.se._js = JSPhysics()
        self.se._js.build_world(ground.vectors, float(SPAWN_X), float(ground.spawning_y))
        self.se._js.set_planning(True)
        self.sim_steps = 0
        self.plans = 0

    def _frames(self, stacked):
        flat = np.asarray(stacked, dtype=np.float32).reshape(-1)
        return [flat[i * self.nobs:(i + 1) * self.nobs].copy() for i in range(4)]

    def _act(self, frames):
        st = np.concatenate(frames).reshape(1, -1)
        return int(self.model.predict(st, deterministic=True)[0][0])

    def _roll(self, snap, first_action, frames0, coyote):
        """Restore to snap, take first_action, then follow the policy H-1 ticks.
        Returns (max_x_px, died)."""
        se = self.se
        se._js.restore_state(snap)
        se.last_grounded_rear, se.last_grounded_front = coyote
        frames = [f.copy() for f in frames0]
        maxx, died = 0.0, False
        for t in range(self.H):
            act = first_action if t == 0 else self._act(frames)
            state = se._js.step_and_state(act, se.lookahead_n, GROUND_LOOKAHEAD_SKIP,
                                          GROUND_REAR_N, GROUND_REAR_SKIP)
            self.sim_steps += 1
            base = se._build_obs(state)
            frames = frames[1:] + [base]
            maxx = state["max_x"] * SCALE
            if state["dead"]:
                died = True; break
        return maxx, died

    def choose(self, real_js, policy_action, stacked_obs, coyote):
        """Return (action, overrode). Only overrides if the policy is predicted to
        die within H and an alternative first action does strictly better."""
        self.plans += 1
        snap = real_js.save_state()
        frames0 = self._frames(stacked_obs)
        pol_maxx, pol_died = self._roll(snap, policy_action, frames0, coyote)
        if not pol_died:
            return policy_action, False            # policy survives -> trust it
        best_fa, best_maxx, best_died = policy_action, pol_maxx, True
        for fa in (0, 2, 1):                        # gas / coast / brake
            if fa == policy_action:
                continue
            mx, dd = self._roll(snap, fa, frames0, coyote)
            better = (best_died and not dd) or (dd == best_died and mx > best_maxx)
            if better:
                best_fa, best_maxx, best_died = fa, mx, dd
        return best_fa, (best_fa != policy_action)


def make_venv():
    return VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=5000, randomize_terrain=False, per_wheel_obs=True)]), 4)


def run_policy(venv, model):
    obs = venv.reset(); done, info = False, {}
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, d, i = venv.step(a); done, info = bool(d[0]), i[0]
    return float(info.get("max_distance_px", 0.0))


def run_mpc(venv, model, planner):
    obs = venv.reset(); done, info = False, {}
    raw = venv.venv.envs[0].unwrapped
    hold_a, hold_left, plan_timer, overrides = 2, 0, 0, 0
    while not done:
        a_pol = int(model.predict(obs, deterministic=True)[0][0])
        a = a_pol
        x_px = info.get("max_distance_px", 0.0)
        if x_px >= ENGAGE_FROM:
            if hold_left > 0:
                a, hold_left = hold_a, hold_left - 1
            elif plan_timer <= 0:
                coyote = (raw.last_grounded_rear, raw.last_grounded_front)
                a_choice, overrode = planner.choose(raw._js, a_pol, obs, coyote)
                plan_timer = planner.cadence
                if overrode:
                    a, hold_a, hold_left = a_choice, a_choice, planner.cadence - 1
                    overrides += 1
            plan_timer -= 1
        obs, r, d, i = venv.step([a]); done, info = bool(d[0]), i[0]
    return float(info.get("max_distance_px", 0.0)), overrides


def main():
    argv = sys.argv[1:]
    ckpt = DEFAULT_CKPT
    horizon, cadence = 20, 6
    for flag, cast in (("--ckpt", str), ("--horizon", int), ("--cadence", int)):
        if flag in argv:
            i = argv.index(flag); v = cast(argv[i + 1])
            if flag == "--ckpt": ckpt = v
            elif flag == "--horizon": horizon = v
            else: cadence = v
            del argv[i:i + 2]
    n_tracks = int(argv[0]) if len(argv) > 0 else 15

    print(f"[planner] {os.path.basename(ckpt)}  {n_tracks} tracks  "
          f"H={horizon} cadence={cadence} engage>={ENGAGE_FROM:.0f}px", flush=True)
    model = PPO.load(ckpt, device="auto")

    tracks = []
    for t in range(n_tracks):
        random.seed(987_000 + t)
        tracks.append(make_ground(None, difficulty=0.0))

    pol = np.zeros(n_tracks); mpc = np.zeros(n_tracks)
    ov = np.zeros(n_tracks, dtype=int); steps = np.zeros(n_tracks, dtype=np.int64)
    orig = E._make_ground
    try:
        for t, g in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            venv = make_venv(); venv.reset()
            raw = venv.venv.envs[0].unwrapped
            raw._js.set_spawn(float(SPAWN_X), float(raw._ground.spawning_y))
            pol[t] = run_policy(venv, model)
            planner = MpcPlanner(g, model, horizon=horizon, cadence=cadence)
            mpc[t], ov[t] = run_mpc(venv, model, planner)
            steps[t] = planner.sim_steps
            venv.close()
            sc = lambda d: max(0.0, (d - SPAWN_X) / 10.0)
            print(f"  [{t+1}/{n_tracks}] policy={sc(pol[t]):.0f} mpc={sc(mpc[t]):.0f} "
                  f"overrides={ov[t]} planSteps={steps[t]}", flush=True)
    finally:
        E._make_ground = orig

    comp = lambda m: 100.0 * (m >= COMPLETE_PX).mean()
    sc = lambda d: np.maximum(0.0, (d - SPAWN_X) / 10.0)
    pc, pp = (mpc >= COMPLETE_PX), (pol >= COMPLETE_PX)
    print(f"\n[planner] single-attempt on {n_tracks} pinned tracks")
    print(f"  policy : completion={comp(pol):.1f}%  mean score={sc(pol).mean():.1f}")
    print(f"  +MPC   : completion={comp(mpc):.1f}%  mean score={sc(mpc).mean():.1f}")
    print(f"  paired : MPC-only solves={int((pc&~pp).sum())}, policy-only solves="
          f"{int((pp&~pc).sum())}, both={int((pc&pp).sum())}, neither={int((~pc&~pp).sum())}")
    print(f"  mean planner sim-steps/attempt = {steps.mean():.0f} "
          f"(~{1+steps.mean()/2000:.1f} blind Best-of-X tries cost the same)")
    out = os.path.join(HERE, "autorun", "planner_results.npz")
    np.savez(out, pol=pol, mpc=mpc, overrides=ov, sim_steps=steps, complete_px=COMPLETE_PX)
    print(f"  raw -> {out}")


if __name__ == "__main__":
    main()
