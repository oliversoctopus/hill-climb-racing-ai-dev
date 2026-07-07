"""Headless probe: load the smoke checkpoint, predict 50 actions, then close.
Verifies that the eval pipeline (model.load + env + predict) is wired up
without needing a window. Use eval.py for the actual interactive eval."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stable_baselines3 import PPO
from env import HillClimbEnv

model = PPO.load(os.path.join(HERE, "checkpoints", "smoke_final.zip"))
env = HillClimbEnv(max_episode_steps=200, seed=7)
obs, _ = env.reset(seed=7)
for i in range(50):
    a, _ = model.predict(obs, deterministic=True)
    obs, r, term, trunc, info = env.step(int(a))
    if term or trunc:
        print(f"  ep ended at step {i+1}: score={info['score']}")
        obs, _ = env.reset(seed=7+i)
print("OK")
env.close()
