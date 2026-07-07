"""PPO training on the 17-dim obs (matches sac_first's obs shape).

Used to settle the algorithm-vs-budget question: SAC trained for 38 min
wall-clock and scored 986. The original ppo_obs17 trained for ~9 min and
scored 814. To know whether SAC's lead is the algorithm or the wall-clock
budget, train PPO on the same obs for the same wall-clock and compare.

Default 8M steps ≈ 37 min on this machine (~3.6 k steps/sec at 8 envs),
matching SAC's wall-clock budget.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


def make_env_factory(seed: int, randomize_terrain: bool = True):
    """Subprocess-safe env thunk for HillClimbEnv17Dim."""
    def _thunk():
        # Re-establish sys.path inside the subprocess so the compat module loads.
        for q in (ROOT, HERE):
            if q not in sys.path:
                sys.path.insert(0, q)
        from compat_envs import HillClimbEnv17Dim
        from stable_baselines3.common.monitor import Monitor
        env = HillClimbEnv17Dim(
            seed=seed,
            max_episode_steps=2000,
            randomize_terrain=randomize_terrain,
        )
        return Monitor(env)
    return _thunk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=8_000_000)
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--name", default="ppo_obs17_long")
    parser.add_argument("--checkpoint-dir", default=os.path.join(ROOT, "checkpoints"))
    parser.add_argument("--tb-dir", default=os.path.join(ROOT, "tb"))
    parser.add_argument("--save-every", type=int, default=500_000)
    parser.add_argument("--vec", choices=("subproc", "dummy"), default="subproc")
    args = parser.parse_args()

    os.makedirs(args.checkpoint_dir, exist_ok=True)
    os.makedirs(args.tb_dir, exist_ok=True)

    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecFrameStack
    from stable_baselines3.common.callbacks import CheckpointCallback

    env_factories = [make_env_factory(seed=3000 + i) for i in range(args.n_envs)]
    VecCls = SubprocVecEnv if args.vec == "subproc" else DummyVecEnv
    envs = VecCls(env_factories)
    envs = VecFrameStack(envs, n_stack=4)

    checkpoint_cb = CheckpointCallback(
        save_freq=max(1, args.save_every // args.n_envs),
        save_path=args.checkpoint_dir,
        name_prefix=args.name,
    )

    # Same hyperparameters as the original ppo_obs17 / current train.py.
    # Changing them would confound the algorithm-vs-budget comparison.
    policy_kwargs = dict(net_arch=dict(pi=[256, 256], vf=[256, 256]))
    model = PPO(
        "MlpPolicy",
        envs,
        policy_kwargs=policy_kwargs,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=256,
        n_epochs=10,
        gamma=0.995,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        vf_coef=0.5,
        tensorboard_log=args.tb_dir,
        verbose=1,
    )

    print(f"[train_obs17] {args.n_envs} envs ({args.vec}), {args.timesteps} timesteps")
    print(f"[train_obs17] checkpoints -> {args.checkpoint_dir}")
    print(f"[train_obs17] tensorboard -> {args.tb_dir}")
    t0 = time.time()
    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=checkpoint_cb,
            tb_log_name=args.name,
            progress_bar=False,
        )
    finally:
        envs.close()

    final_path = os.path.join(args.checkpoint_dir, f"{args.name}_final.zip")
    model.save(final_path)
    dt = time.time() - t0
    print(f"[train_obs17] done in {dt:.1f}s; final model -> {final_path}")


if __name__ == "__main__":
    main()
