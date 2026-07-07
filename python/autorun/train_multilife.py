"""E3 trainer: PPO on MultiLifeEnv (K lives/terrain + previous-death markers).

Mirrors the champion recipe in python/train.py exactly (256x256, gamma 0.995,
LR 3e-4->1e-4 + ent 0.01->0.003 linear decay, frame-stack 4, 8 SubprocVecEnv)
so the ONLY difference vs the champion is the multi-life env + marker obs. That
keeps any score delta attributable to the lever, not to incidental hyperparams.

Usage:
    python autorun/train_multilife.py --timesteps 8000000 --seed 7 \
        --name ml6 --lives 6 --markers 2
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


def make_env_factory(seed, lives, markers, max_episode_steps=2000,
                     lookahead_n=6, death_penalty=50.0):
    def _thunk():
        for p in (ROOT, HERE):
            if p not in sys.path:
                sys.path.insert(0, p)
        from multilife_env import MultiLifeEnv
        from stable_baselines3.common.monitor import Monitor
        env = MultiLifeEnv(
            lives_per_terrain=lives,
            n_markers=markers,
            seed=seed,
            max_episode_steps=max_episode_steps,
            randomize_terrain=True,   # toggled internally per trial
            lookahead_n=lookahead_n,
            death_penalty=death_penalty,
        )
        return Monitor(env)
    return _thunk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=8_000_000)
    ap.add_argument("--n-envs", type=int, default=8)
    ap.add_argument("--name", default="ml")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--lives", type=int, default=6)
    ap.add_argument("--markers", type=int, default=2)
    ap.add_argument("--lookahead-n", type=int, default=6)
    ap.add_argument("--death-penalty", type=float, default=50.0)
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--lr-final", type=float, default=1e-4)
    ap.add_argument("--ent-final", type=float, default=0.003)
    args = ap.parse_args()

    ckpt_dir = os.path.join(ROOT, "checkpoints")
    tb_dir = os.path.join(ROOT, "tb")
    os.makedirs(ckpt_dir, exist_ok=True)

    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecFrameStack
    from stable_baselines3.common.callbacks import CheckpointCallback, CallbackList, BaseCallback

    class EntropyDecayCallback(BaseCallback):
        def __init__(self, total, ent_start, ent_end):
            super().__init__()
            self.total = max(1, int(total)); self.s = float(ent_start); self.e = float(ent_end)

        def _on_rollout_start(self):
            prog = min(1.0, self.num_timesteps / self.total)
            self.model.ent_coef = self.s + (self.e - self.s) * prog
            self.logger.record("train/ent_coef_scheduled", self.model.ent_coef)

        def _on_step(self):
            return True

    worker_seed_base = 1000 + args.seed * 100
    factories = [make_env_factory(worker_seed_base + i, args.lives, args.markers,
                                  args.max_steps, args.lookahead_n, args.death_penalty)
                 for i in range(args.n_envs)]
    envs = VecFrameStack(SubprocVecEnv(factories), n_stack=4)

    _lr_i, _lr_f = 3e-4, args.lr_final
    lr_schedule = lambda pr: _lr_f + (_lr_i - _lr_f) * pr

    model = PPO(
        "MlpPolicy", envs,
        policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])),
        learning_rate=lr_schedule, n_steps=2048, batch_size=256, n_epochs=10,
        gamma=0.995, gae_lambda=0.95, clip_range=0.2, seed=args.seed,
        ent_coef=0.01, vf_coef=0.5, tensorboard_log=tb_dir, verbose=1,
    )

    callbacks = CallbackList([
        CheckpointCallback(save_freq=max(1, 100_000 // args.n_envs),
                           save_path=ckpt_dir, name_prefix=args.name),
        EntropyDecayCallback(args.timesteps, 0.01, args.ent_final),
    ])

    print(f"[train_ml] {args.n_envs} envs, {args.timesteps} steps, lives={args.lives}, "
          f"markers={args.markers}, obs_dim={envs.observation_space.shape}")
    t0 = time.time()
    try:
        model.learn(total_timesteps=args.timesteps, callback=callbacks,
                    tb_log_name=args.name, progress_bar=False)
    finally:
        envs.close()
    final_path = os.path.join(ckpt_dir, f"{args.name}_final.zip")
    model.save(final_path)
    print(f"[train_ml] done in {time.time()-t0:.1f}s -> {final_path}")


if __name__ == "__main__":
    main()
