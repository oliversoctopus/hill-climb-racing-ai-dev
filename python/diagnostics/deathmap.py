"""Characterize the score ceiling: for a checkpoint, run N episodes at f=0 and
report WHERE/why episodes end -- completion rate, early-death rate, the death-x
distribution across the track, and the terrain steepness at the death point.

If most non-completions die deep in the track where steepness is high, the
ceiling is terrain/physics-limited (impassable bottlenecks), not a driving-skill
or optimization limit.
"""
import os, sys
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from stable_baselines3 import PPO  # noqa
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack  # noqa
from env import HillClimbEnv  # noqa
from constants import GROUND_DISTANCE, SPAWN_X, COMPLETE_PX  # noqa

def main():
    ckpt = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    max_steps = 5000
    model = PPO.load(ckpt, device="auto")
    env = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
        max_episode_steps=max_steps, seed=seed, randomize_terrain=True, per_wheel_obs=True)]), 4)

    scores, deaths_px, steps_arr, truncated = [], [], [], []
    for _ in range(n):
        obs = env.reset(); done = False; info = {}; st = 0
        while not done:
            a, _ = model.predict(obs, deterministic=True)
            obs, r, d, i = env.step(a); done = bool(d[0]); info = i[0]; st += 1
        scores.append(info.get("score", 0))
        deaths_px.append(info.get("max_distance_px", 0))
        steps_arr.append(st)
        truncated.append(st >= max_steps)
    env.close()

    scores = np.array(scores); deaths_px = np.array(deaths_px)
    steps_arr = np.array(steps_arr); truncated = np.array(truncated)
    completed = deaths_px >= COMPLETE_PX      # reached the last vertex (true end)
    early = scores < 100
    # steepness ramp at the stopping point: map(x, 0, DIST, 130, 250)
    steep_at = 130.0 + (250.0 - 130.0) * np.clip(deaths_px / GROUND_DISTANCE, 0, 1)

    print(f"[deathmap] {os.path.basename(ckpt)}  n={n} seed={seed}  track={GROUND_DISTANCE}px (completion score ~{int((COMPLETE_PX-SPAWN_X)/10)})")
    print(f"  mean score={scores.mean():.1f}  median={int(np.median(scores))}  max={int(scores.max())}")
    print(f"  COMPLETED track (reached last vertex):  {100*completed.mean():.1f}%")
    print(f"  early death (<100):                    {100*early.mean():.1f}%")
    print(f"  timed out (hit {max_steps} steps, survived): {100*truncated.mean():.1f}%")
    print(f"  of NON-completions: mean stop at {deaths_px[~completed].mean():.0f}px "
          f"({100*deaths_px[~completed].mean()/GROUND_DISTANCE:.0f}% of track), "
          f"mean steepness there={steep_at[~completed].mean():.0f} (ramp 130->250)")
    print("  stop-position distribution (fraction of track):")
    edges = np.linspace(0, GROUND_DISTANCE, 11)
    hist, _ = np.histogram(deaths_px, bins=edges)
    for k in range(10):
        bar = "#" * int(round(40 * hist[k] / max(1, hist.max())))
        print(f"    {10*k:>3d}-{10*(k+1):>3d}%  n={hist[k]:>3d}  {bar}")

if __name__ == "__main__":
    main()
