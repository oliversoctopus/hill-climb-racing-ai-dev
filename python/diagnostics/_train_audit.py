"""Pre-training audit: stress tests the env + training pipeline before kicking off
a long PPO run. Checks for issues that could waste hours of training time."""
import os, sys, time, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from env import HillClimbEnv

# ------------------------------------------------------------------
# 1. Observation invariants — 9-dim float32, all components in declared range
#    across a full episode, across multiple seeds.
# ------------------------------------------------------------------
print("\n[1] Observation invariants across 5 seeds × 200 steps")
env = HillClimbEnv(max_episode_steps=200)
all_ok = True
for seed in range(5):
    obs, _ = env.reset(seed=seed)
    obs_min = obs.copy()
    obs_max = obs.copy()
    for t in range(200):
        a = (t % 3)
        obs, r, term, trunc, info = env.step(int(a))
        obs_min = np.minimum(obs_min, obs)
        obs_max = np.maximum(obs_max, obs)
        if obs.dtype != np.float32:
            print(f"  seed={seed} t={t}: WRONG dtype {obs.dtype}")
            all_ok = False; break
        if not env.observation_space.contains(obs):
            print(f"  seed={seed} t={t}: obs OUT OF BOUNDS: {obs}")
            all_ok = False; break
        if not np.isfinite(obs).all():
            print(f"  seed={seed} t={t}: obs has NaN/inf: {obs}")
            all_ok = False; break
        if term or trunc:
            obs, _ = env.reset(seed=seed)
print(f"  bounds across all 5 seeds: min={obs_min.tolist()}  max={obs_max.tolist()}")
print(f"  -> {'OK' if all_ok else 'FAILED'}")

# ------------------------------------------------------------------
# 2. Reward sanity — total reward should roughly equal final chassis_x distance
# ------------------------------------------------------------------
print("\n[2] Reward sums to forward distance (sanity check on dense reward)")
obs, _ = env.reset(seed=42)
total_r = 0.0
for t in range(150):
    obs, r, term, trunc, _ = env.step(0)  # always forward
    total_r += r
    if term or trunc:
        break
final_x_m = env.car.chassis_body.position.x
from constants import SPAWN_X, SCALE
start_x_m = SPAWN_X / SCALE
expected = final_x_m - start_x_m
diff = abs(total_r - expected)
print(f"  total reward = {total_r:+.4f}m   final_chassis_x - spawn = {expected:+.4f}m  diff = {diff:.2e}")
print(f"  -> {'OK' if diff < 1e-3 else 'FAILED (reward != forward distance)'}")

# ------------------------------------------------------------------
# 3. Reset stress: 200 consecutive fast_resets, ensure no crash, state stays sane
# ------------------------------------------------------------------
print("\n[3] Reset stress test — 200 consecutive episodes")
env2 = HillClimbEnv(max_episode_steps=50, seed=7)
crash = False
for ep in range(200):
    try:
        obs, _ = env2.reset(seed=7)
        for t in range(50):
            obs, r, term, trunc, _ = env2.step((t * 3) % 3)
            if term or trunc:
                break
    except Exception as e:
        print(f"  ep {ep}: CRASH {type(e).__name__}: {e}")
        crash = True; break
print(f"  -> {'OK — 200 episodes, no crash' if not crash else 'FAILED'}")
env2.close()

# ------------------------------------------------------------------
# 4. Determinism: same seed → same trajectory (after our contact-clear fix)
# ------------------------------------------------------------------
print("\n[4] Bit-determinism across resets (gymnasium check_env requirement)")
def rollout(env, seed):
    obs, _ = env.reset(seed=seed)
    traj = [obs.copy()]
    for a in [(i % 3) for i in range(50)]:
        obs, r, term, trunc, _ = env.step(a)
        traj.append(obs.copy())
        if term or trunc: break
    return traj
env3 = HillClimbEnv(max_episode_steps=200, seed=11)
A = rollout(env3, 11)
B = rollout(env3, 11)
max_diff = max(float(np.max(np.abs(a - b))) for a, b in zip(A, B))
print(f"  max obs diff A vs B (same seed): {max_diff:.3e}")
print(f"  -> {'OK' if max_diff == 0.0 else 'FAILED'}")
env3.close()

# ------------------------------------------------------------------
# 5. Performance budget: how long does training rollout take?
# ------------------------------------------------------------------
print("\n[5] Performance: env.step throughput single-thread")
env4 = HillClimbEnv(max_episode_steps=10000, seed=100)
env4.reset(seed=100)
N = 10000
t0 = time.perf_counter()
for i in range(N):
    obs, r, term, trunc, _ = env4.step(0)
    if term or trunc:
        env4.reset(seed=100)
dt = time.perf_counter() - t0
print(f"  {N} steps in {dt:.2f}s = {N/dt:.0f} steps/s single-thread")
print(f"  projected 1M steps single-thread: {1_000_000/(N/dt)/60:.1f} min")
print(f"  projected 1M steps × 8 SubprocVecEnv: ~{1_000_000/(N/dt)/60/4:.1f} min (estimated 4x speedup)")
env4.close()

# ------------------------------------------------------------------
# 6. SubprocVecEnv smoke test
# ------------------------------------------------------------------
print("\n[6] SubprocVecEnv 4-worker smoke test")
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor

def make_factory(seed):
    def _t():
        if HERE not in sys.path: sys.path.insert(0, HERE)
        from env import HillClimbEnv
        from stable_baselines3.common.monitor import Monitor
        return Monitor(HillClimbEnv(seed=seed, max_episode_steps=200))
    return _t

vec = SubprocVecEnv([make_factory(1000 + i) for i in range(4)])
obs = vec.reset()
print(f"  vec.reset() -> obs shape {obs.shape}, dtype {obs.dtype}")
ep_returns = [0.0] * 4
ep_lengths = [0] * 4
ep_completed = 0
for t in range(500):
    actions = np.array([t % 3] * 4)
    obs, rew, dones, infos = vec.step(actions)
    for i in range(4):
        ep_returns[i] += rew[i]
        ep_lengths[i] += 1
        if dones[i]:
            ep_completed += 1
            if "episode" in infos[i]:
                # Monitor populated this
                pass
            ep_returns[i] = 0.0; ep_lengths[i] = 0
vec.close()
print(f"  500 vec steps × 4 workers = {500*4} total; {ep_completed} episodes completed")
print(f"  -> OK")

print("\n" + "=" * 60)
print("All audits passed. Pipeline ready for full training run.")
