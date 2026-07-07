"""Confirm fast_reset produces bit-deterministic trajectories."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from env import HillClimbEnv

# Deeper, more varied action pattern to stress more code paths
ACTIONS = []
for cycle in range(10):
    ACTIONS += [0] * 30 + [1] * 5 + [2] * 5 + [0] * 10

def run(env):
    obs, _ = env.reset(seed=42)
    obs_traj = [obs]
    for a in ACTIONS:
        obs, r, term, trunc, info = env.step(a)
        obs_traj.append(obs)
        if term:
            obs, _ = env.reset(seed=42)
            obs_traj.append(obs)
    return obs_traj

env = HillClimbEnv(max_episode_steps=10000, seed=42)
A = run(env)
B = run(env)
C = run(env)

max_diff_AB = max(float(np.max(np.abs(a-b))) for a, b in zip(A, B))
max_diff_BC = max(float(np.max(np.abs(b-c))) for b, c in zip(B, C))
print(f"trajectories: {len(A)} obs each ({len(ACTIONS)} actions)")
print(f"max diff A vs B (build vs fast): {max_diff_AB:.3e}")
print(f"max diff B vs C (fast vs fast):  {max_diff_BC:.3e}")
print("PASS" if max(max_diff_AB, max_diff_BC) == 0.0 else "FAIL")

# Now also run gymnasium's check_env
from gymnasium.utils.env_checker import check_env
env2 = HillClimbEnv(max_episode_steps=200, seed=42)
print("\n[check_env]...")
check_env(env2, skip_render_check=True)
print("[check_env] PASS")
env.close()
env2.close()
