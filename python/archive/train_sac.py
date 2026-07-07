"""SAC training entrypoint.

Mirrors train.py but with SAC + continuous-throttle action. The motivation
for SAC over PPO is documented in PROJECT_STATUS.md ("Phase 2.5 — SAC
implementation guide"): the 290-330 PPO reward ceiling looks structural,
and continuous action + off-policy replay are the two biggest changes
left to try.

Defaults to 1M timesteps across 4 parallel envs. SAC trains slower per
env-step than PPO (target nets + actor + 2 critics every step) so fewer
envs are usually optimal; cost is dominated by gradient updates, not
rollout collection.

Usage:
    python train_sac.py                          # 1M steps, 4 envs (default)
    python train_sac.py --timesteps 100000       # short smoke-test
    python train_sac.py --n-envs 2 --timesteps 50000
    python train_sac.py --resume checkpoints/sac_hcr_500000_steps.zip
"""

from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def make_env_factory(seed: int, randomize_terrain: bool = True):
    """Thunk that builds one continuous-action HillClimbEnv with the given seed."""
    def _thunk():
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from env import HillClimbEnv
        from stable_baselines3.common.monitor import Monitor
        env = HillClimbEnv(
            seed=seed,
            max_episode_steps=2000,
            randomize_terrain=randomize_terrain,
            continuous_action=True,
        )
        return Monitor(env)
    return _thunk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=1_000_000)
    # SAC: fewer envs is usually optimal. Each step triggers a gradient
    # update on actor + 2 critics + target soft-update — env stepping
    # is no longer the bottleneck the way it is for PPO.
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--checkpoint-dir", default=os.path.join(HERE, "checkpoints"))
    parser.add_argument("--tb-dir", default=os.path.join(HERE, "tb"))
    parser.add_argument("--save-every", type=int, default=100_000)
    parser.add_argument("--resume", default=None,
                        help="Path to a .zip checkpoint to continue training from")
    parser.add_argument("--name", default="sac_hcr",
                        help="Run name (used in checkpoint filenames + tb subdir)")
    parser.add_argument("--vec", choices=("subproc", "dummy"), default="subproc",
                        help="VecEnv backend. 'dummy' runs envs in-process (slower but easier to debug).")
    parser.add_argument("--no-randomize-terrain", dest="randomize_terrain",
                        action="store_false", default=True,
                        help="Disable per-episode terrain randomization.")
    parser.add_argument("--buffer-size", type=int, default=1_000_000,
                        help="Replay buffer capacity (1M default = ~500MB).")
    parser.add_argument("--learning-starts", type=int, default=10_000,
                        help="Random-action steps before training begins.")
    args = parser.parse_args()

    os.makedirs(args.checkpoint_dir, exist_ok=True)
    os.makedirs(args.tb_dir, exist_ok=True)

    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecFrameStack
    from stable_baselines3.common.callbacks import CheckpointCallback

    env_factories = [make_env_factory(seed=2000 + i,
                                      randomize_terrain=args.randomize_terrain)
                     for i in range(args.n_envs)]
    VecCls = SubprocVecEnv if args.vec == "subproc" else DummyVecEnv
    envs = VecCls(env_factories)
    # Same frame-stack as PPO: 17-dim obs × 4 frames = 68-dim input.
    # SAC handles stacked obs identically to PPO — the policy/critic just
    # see a larger flat vector.
    envs = VecFrameStack(envs, n_stack=4)

    checkpoint_cb = CheckpointCallback(
        save_freq=max(1, args.save_every // args.n_envs),
        save_path=args.checkpoint_dir,
        name_prefix=args.name,
    )

    if args.resume:
        print(f"[train_sac] resuming from {args.resume}")
        model = SAC.load(args.resume, env=envs, tensorboard_log=args.tb_dir)
    else:
        # net_arch=[256, 256] matches what worked for PPO. SAC's default
        # is also [256, 256] so this is the safe baseline.
        policy_kwargs = dict(net_arch=[256, 256])
        model = SAC(
            "MlpPolicy",
            envs,
            policy_kwargs=policy_kwargs,
            learning_rate=3e-4,
            buffer_size=args.buffer_size,
            learning_starts=args.learning_starts,
            batch_size=256,
            tau=0.005,         # target-net soft update
            gamma=0.995,       # same long horizon that worked for PPO
            train_freq=1,      # gradient step every env step (per env)
            gradient_steps=1,
            ent_coef="auto",   # automatic temperature tuning
            tensorboard_log=args.tb_dir,
            verbose=1,
        )

    print(f"[train_sac] {args.n_envs} envs ({args.vec}), {args.timesteps} timesteps, "
          f"randomize_terrain={args.randomize_terrain}, buffer={args.buffer_size}")
    print(f"[train_sac] checkpoints -> {args.checkpoint_dir}")
    print(f"[train_sac] tensorboard -> {args.tb_dir}   (tensorboard --logdir {args.tb_dir})")
    t0 = time.time()
    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=checkpoint_cb,
            tb_log_name=args.name,
            reset_num_timesteps=(args.resume is None),
            progress_bar=False,
        )
    finally:
        envs.close()

    final_path = os.path.join(args.checkpoint_dir, f"{args.name}_final.zip")
    model.save(final_path)
    dt = time.time() - t0
    print(f"[train_sac] done in {dt:.1f}s; final model -> {final_path}")


if __name__ == "__main__":
    main()
