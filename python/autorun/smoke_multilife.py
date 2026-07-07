"""Smoke test for MultiLifeEnv: obs shape, terrain persistence across lives,
death-marker population. Cheap; safe to run under load."""
import os, sys, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from multilife_env import MultiLifeEnv  # noqa: E402


def terrain_hash(env):
    v = np.asarray(env._ground.vectors, dtype=np.float64).tobytes()
    return hashlib.md5(v).hexdigest()[:8]


def run_life(env, max_steps=60):
    obs, _ = env.reset()
    th = terrain_hash(env)
    m_at_reset = obs[-2:].copy()  # marker dims
    done = False
    info = {}
    steps = 0
    while not done and steps < max_steps:
        obs, r, term, trunc, info = env.step(0)  # always forward
        done = term or trunc
        steps += 1
    return th, m_at_reset, info.get("score", 0), env._life_in_trial, len(env._death_positions)


def main():
    LIVES = 3
    env = MultiLifeEnv(lives_per_terrain=LIVES, n_markers=2, seed=123,
                       randomize_terrain=True, max_episode_steps=40)
    print("obs space:", env.observation_space.shape, "(expect base 12 + 2 = 14)")
    assert env.observation_space.shape[0] == 14, "obs dim wrong"

    print(f"\n{'life#':>5s} {'trial_life':>10s} {'terrain':>9s} {'markers@reset':>22s} "
          f"{'#deaths_known':>13s} {'score':>6s}")
    hashes = []
    for i in range(8):  # 8 lives -> trials of 3,3,2 ; expect terrain change at life 4,7
        th, m, sc, tl, nd = run_life(env)
        hashes.append(th)
        print(f"{i+1:>5d} {tl:>10d} {th:>9s} {str(np.round(m,3)):>22s} {nd:>13d} {sc:>6d}")

    # Checks
    same_123 = hashes[0] == hashes[1] == hashes[2]
    change_4 = hashes[3] != hashes[2]
    same_456 = hashes[3] == hashes[4] == hashes[5]
    change_7 = hashes[6] != hashes[5]
    print("\nterrain same across lives 1-3:", same_123)
    print("terrain changes at life 4    :", change_4)
    print("terrain same across lives 4-6:", same_456)
    print("terrain changes at life 7    :", change_7)
    assert same_123 and change_4 and same_456 and change_7, "terrain grouping FAILED"
    print("\nSMOKE PASS")


if __name__ == "__main__":
    main()
