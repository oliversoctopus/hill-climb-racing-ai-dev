"""Quick smoke test for the JS-backed HillClimbEnv."""
import os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from env import HillClimbEnv


def main():
    env = HillClimbEnv(seed=42, randomize_terrain=False, max_episode_steps=2000)

    t0 = time.time()
    obs, info = env.reset()
    print(f"first reset: {(time.time()-t0)*1000:.0f}ms  obs.shape={obs.shape}")
    print(f"  obs[:5] = {np.round(obs[:5], 3)}")
    print(f"  obs[5:] = {np.round(obs[5:], 3)}")

    # Episode 1: forward-only
    t0 = time.time()
    total_reward = 0.0
    ep_steps = 0
    last_info = info
    done = False
    while not done:
        obs, r, term, trunc, info = env.step(0)
        total_reward += r
        ep_steps += 1
        last_info = info
        done = term or trunc
    dt = time.time() - t0
    print(f"ep1 forward-only: steps={ep_steps}  reward={total_reward:+.1f}  "
          f"score={last_info['score']}  wall={dt:.2f}s -> {ep_steps/dt:.0f} steps/sec")

    # Episode 2: respawn on same terrain
    t0 = time.time()
    obs, info = env.reset()
    print(f"second reset: {(time.time()-t0)*1000:.0f}ms")
    total_reward = 0.0
    for _ in range(30): env.step(2)
    for _ in range(100):
        obs, r, term, trunc, info = env.step(0)
        total_reward += r
        if term or trunc: break
    print(f"after 30 settle + 100 forward: reward={total_reward:+.1f}  info={info}")

    # Episode 3: randomize_terrain test
    env2 = HillClimbEnv(seed=42, randomize_terrain=True, max_episode_steps=500)
    obs1, _ = env2.reset()
    obs2, _ = env2.reset()
    diff = float(np.abs(obs1[5:] - obs2[5:]).max())
    print(f"randomize_terrain: max obs diff between episodes = {diff:.3f}")


if __name__ == "__main__":
    main()
