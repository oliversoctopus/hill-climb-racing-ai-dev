"""Pin the TRUE end-of-track score: run the deployed policy with NO early-stop
until natural death, on tracks the policy completes single-shot, and watch the
fly-off (chassis x keeps climbing as y falls past the 720px canvas into the void).

"Beating the game" = max_x reaches the end of the terrain (last vertex ~19185px),
which requires launching off the final edge. This measures exactly how far max_x
(and thus score) gets.

Run: python diagnostics/measure_track_end.py
"""
import os, sys, random
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "autorun"))
from stable_baselines3 import PPO                                   # noqa: E402
import env as E                                                     # noqa: E402
from env import HillClimbEnv                                        # noqa: E402
from ground import make_ground                                     # noqa: E402
from constants import SPAWN_X, SCALE, CANVAS_HEIGHT, GROUND_DISTANCE  # noqa: E402
from backtrack_search import init_stack, push_stack                 # noqa: E402

CKPT = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")
SCORE = lambda px: (px - SPAWN_X) / 10.0


def main():
    model = PPO.load(CKPT, device="auto")
    # tracks that completed single-shot in the n30 study (reach ~1790 unaided)
    for t in [4, 5, 6, 10]:
        random.seed(987_000 + t)
        g = make_ground(None, difficulty=0.0)
        last_vx = g.vectors[-1][0]                 # x of final terrain vertex (px)
        E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
        env = HillClimbEnv(max_episode_steps=8000, randomize_terrain=False,
                           per_wheel_obs=True)
        obs, _ = env.reset()
        fb = init_stack(obs)
        traj = []                                  # (chassis_x_px, chassis_y_px)
        done = False; info = {}
        while not done:
            a, _ = model.predict(fb.reshape(1, -1), deterministic=True)
            obs, _r, term, trunc, info = env.step(int(a[0]))
            push_stack(fb, obs)
            st = env._js.state(env.lookahead_n, 5, 0, 5)
            traj.append((st["x"] * SCALE, st["y"] * SCALE))
            done = term or trunc
        traj = np.array(traj)
        maxd = info["max_distance_px"]
        peak_i = int(np.argmax(traj[:, 0]))
        print(f"\n=== track seed {987_000+t} ===")
        print(f"  last terrain vertex x = {last_vx:.0f}px   (GROUND_DISTANCE={GROUND_DISTANCE})")
        print(f"  max chassis x = {maxd:.1f}px  ->  SCORE = {SCORE(maxd):.1f}")
        print(f"  died at tick {len(traj)} ({'term' if term else 'trunc'}); "
              f"peak-x at tick {peak_i} (chassis y there = {traj[peak_i,1]:.0f}px, "
              f"canvas bottom = {CANVAS_HEIGHT})")
        # show the tail: x still rising while y drops past 720 = flying into the void
        print(f"  tail (x_px, y_px) last 16 ticks:")
        for x, y in traj[-16:]:
            flag = "  <-- below canvas (void)" if y > CANVAS_HEIGHT else ""
            print(f"      x={x:8.1f}  y={y:7.1f}{flag}")
        env.close()


if __name__ == "__main__":
    main()
