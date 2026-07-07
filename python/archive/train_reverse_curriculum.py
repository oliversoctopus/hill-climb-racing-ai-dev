"""PPO training entrypoint.

Defaults to 1M timesteps across 8 parallel envs (SubprocVecEnv). Logs to
TensorBoard at python/tb/ and checkpoints every 100k steps to
python/checkpoints/.

Usage:
    python train.py                          # 1M steps, 8 envs (default)
    python train.py --timesteps 100000       # short run
    python train.py --n-envs 4 --timesteps 50000
    python train.py --resume checkpoints/ppo_hcr_500000_steps.zip

Each parallel env gets its own seed so terrain differs across workers —
that's the only diversity in training, because within an env we use
fast_reset() (same terrain across episodes).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Defer SB3 import until after argparse so --help is fast.


def make_env_factory(seed: int, randomize_terrain: bool = True,
                     per_wheel_obs: bool = False, reward_shaping: bool = False,
                     difficulty_max: float = 0.0, max_episode_steps: int = 2000,
                     lookahead_n: int = 6):
    """Returns a thunk that builds one HillClimbEnv with the given seed."""
    def _thunk():
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from env import HillClimbEnv
        from stable_baselines3.common.monitor import Monitor
        env = HillClimbEnv(
            seed=seed,
            max_episode_steps=max_episode_steps,
            randomize_terrain=randomize_terrain,
            per_wheel_obs=per_wheel_obs,
            reward_shaping=reward_shaping,
            difficulty_max=difficulty_max,
            lookahead_n=lookahead_n,
        )
        return Monitor(env)
    return _thunk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=1_000_000)
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--checkpoint-dir", default=os.path.join(HERE, "checkpoints"))
    parser.add_argument("--tb-dir", default=os.path.join(HERE, "tb"))
    parser.add_argument("--save-every", type=int, default=100_000)
    parser.add_argument("--resume", default=None, help="Path to a .zip checkpoint to continue training from")
    parser.add_argument("--name", default="ppo_hcr", help="Run name (used in checkpoint filenames + tb subdir)")
    parser.add_argument("--seed", type=int, default=0,
                        help="Master seed: seeds PPO (network init + action sampling) AND offsets the "
                             "per-worker terrain seeds. Pairs an A/B: same --seed, differ only in "
                             "--rc-fmax-cap, isolates the curriculum effect from init/terrain luck.")
    parser.add_argument("--vec", choices=("subproc", "dummy"), default="subproc",
                        help="VecEnv backend. 'dummy' runs envs in-process (slower but easier to debug).")
    parser.add_argument("--no-randomize-terrain", dest="randomize_terrain",
                        action="store_false", default=True,
                        help="Disable per-episode terrain randomization (each env gets one fixed track).")
    parser.add_argument("--per-wheel", action="store_true",
                        help="Use 12-dim obs with separate rear/front grounded bits.")
    parser.add_argument("--reward-shaping", action="store_true",
                        help="Add +0.01/tick survival bonus and -50 death penalty.")
    parser.add_argument("--lookahead-n", type=int, default=6,
                        help="Forward ground-clearance samples, 75px apart (default 6 = 375px/"
                             "12.5m — the champion's view; 13 = 900px/30m, the full human "
                             "screen view). Changes obs dim: eval with HCR_LOOKAHEAD_N=<N>.")
    parser.add_argument("--gamma", type=float, default=0.995,
                        help="PPO discount factor (default 0.995). Raise (e.g. 0.999) for a longer "
                             "effective credit-assignment horizon.")
    parser.add_argument("--max-steps", type=int, default=2000,
                        help="Per-episode step cap during training (default 2000). Raise (e.g. 3000) "
                             "so deep runs aren't truncated before the track end (~1920 steps).")
    parser.add_argument("--net-arch", default="256x256",
                        help="MLP arch as 'WxW' or 'WxWxW'. Default '256x256'.")
    # ---- Reverse curriculum (normal -> harder) ----
    # Per episode each worker draws difficulty f ~ U(0, f_max(t)). f=0 is normal
    # (the eval distribution); higher f raises the steepness floor (see
    # ground.randomize). Only f_max grows over training (the range EXPANDS), so
    # coverage of normal..frontier stays uniform — over-sampling the hard later
    # terrain that survivorship under-samples in from-the-start training.
    parser.add_argument("--reverse-curriculum", action="store_true",
                        help="Expand per-episode difficulty range f~U(0,f_max) over the run "
                             "(normal -> harder). Also enables the LR/entropy decay schedule.")
    parser.add_argument("--rc-fmax-cap", type=float, default=1.0,
                        help="Final f_max (ceiling of the difficulty range). 1.0 = whole track at "
                             "steepness 250. Set 0.0 for a matched NORMAL-ONLY baseline. Default 1.0.")
    parser.add_argument("--rc-warmup-frac", type=float, default=0.2,
                        help="Fraction of training with f_max=0 (pure-normal warmup) before expanding. "
                             "Default 0.2.")
    parser.add_argument("--rc-ramp-frac", type=float, default=0.5,
                        help="Fraction of training over which f_max ramps 0 -> rc-fmax-cap AFTER the "
                             "warmup; the remainder holds at the cap. Default 0.5.")
    # ---- Anti-degradation: decay LR and entropy over the run (applied whenever
    # --reverse-curriculum is set, so both arms of the A/B share it) ----
    parser.add_argument("--lr-final", type=float, default=1e-4,
                        help="Learning rate at end of training (linear decay from 3e-4). Default 1e-4.")
    parser.add_argument("--ent-final", type=float, default=0.003,
                        help="ent_coef at end of training (linear decay from 0.01). Lower entropy late "
                             "stabilizes the competent policy. Default 0.003.")
    args = parser.parse_args()

    os.makedirs(args.checkpoint_dir, exist_ok=True)
    os.makedirs(args.tb_dir, exist_ok=True)

    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecFrameStack
    from stable_baselines3.common.callbacks import CheckpointCallback, CallbackList, BaseCallback

    class ReverseCurriculumCallback(BaseCallback):
        """Drives the reverse-curriculum schedules each rollout (cheap: once per
        ~n_steps, not per step):
          - f_max(t): warmup at 0 (pure normal), then ramp 0->fmax_cap, then hold.
            Each worker draws per-episode f ~ U(0, f_max) from this ceiling.
          - learning_rate: linear 3e-4 -> lr_final;
          - ent_coef: linear ent_start -> ent_end (lower entropy late stabilizes
            the competent policy).
        The LR/entropy decays counter the back-third score collapse seen in
        ppo_p5_curriculum_a (1167 @ 5.5M -> 808 @ 8M)."""

        def __init__(self, total_timesteps, fmax_cap, warmup_frac, ramp_frac,
                     ent_start, ent_end):
            super().__init__()
            self.total = max(1, int(total_timesteps))
            self.fmax_cap = max(0.0, min(1.0, float(fmax_cap)))
            self.warmup_frac = max(0.0, float(warmup_frac))
            self.ramp_frac = max(1e-6, float(ramp_frac))
            self.ent_start = float(ent_start)
            self.ent_end = float(ent_end)

        def _progress(self):
            return min(1.0, self.num_timesteps / self.total)

        def _f_max(self):
            prog = self._progress()
            if prog < self.warmup_frac:
                return 0.0
            ramp_prog = (prog - self.warmup_frac) / self.ramp_frac
            return self.fmax_cap * max(0.0, min(1.0, ramp_prog))

        def _on_rollout_start(self):
            prog = self._progress()
            fmax = self._f_max()
            self.training_env.env_method("set_difficulty_max", fmax)
            self.logger.record("curriculum/f_max", fmax)

            # Linear decays across the full run.
            ent = self.ent_start + (self.ent_end - self.ent_start) * prog
            self.model.ent_coef = ent
            self.logger.record("curriculum/ent_coef", ent)

        def _on_step(self):
            return True

    # f_max the workers start at (before the callback's first rollout tick). At
    # warmup this is 0 (pure normal). Baseline (rc-fmax-cap 0) stays 0 throughout.
    initial_fmax = 0.0

    # Worker terrain seeds offset by the master seed so different --seed values
    # give different terrain too (and a given --seed reproduces the same set).
    worker_seed_base = 1000 + args.seed * 100
    env_factories = [make_env_factory(seed=worker_seed_base + i,
                                       randomize_terrain=args.randomize_terrain,
                                       per_wheel_obs=args.per_wheel,
                                       reward_shaping=args.reward_shaping,
                                       difficulty_max=initial_fmax,
                                       max_episode_steps=args.max_steps,
                                       lookahead_n=args.lookahead_n)
                     for i in range(args.n_envs)]
    VecCls = SubprocVecEnv if args.vec == "subproc" else DummyVecEnv
    envs = VecCls(env_factories)
    # Frame stack: each observation becomes [obs(t-3), obs(t-2), obs(t-1), obs(t)]
    # concatenated to a 44-dim vector (11 × 4). Lets the policy see velocity
    # trends, angle oscillation, on-ground transitions etc. — temporal context
    # that a single-frame obs can't capture. Incompatible with non-stacked
    # checkpoints; required fresh retrain after introducing.
    envs = VecFrameStack(envs, n_stack=4)

    checkpoint_cb = CheckpointCallback(
        save_freq=max(1, args.save_every // args.n_envs),
        save_path=args.checkpoint_dir,
        name_prefix=args.name,
    )
    if args.reverse_curriculum:
        callbacks = CallbackList([
            checkpoint_cb,
            ReverseCurriculumCallback(args.timesteps, args.rc_fmax_cap,
                                      args.rc_warmup_frac, args.rc_ramp_frac,
                                      ent_start=0.01, ent_end=args.ent_final),
        ])
    else:
        callbacks = checkpoint_cb

    # Learning-rate schedule. SB3 calls this with progress_remaining (1.0 at
    # start -> 0.0 at end). With --reverse-curriculum, decay 3e-4 -> args.lr_final
    # linearly (both A/B arms share it); otherwise keep the constant 3e-4.
    _lr_init = 3e-4
    if args.reverse_curriculum:
        _lr_final = args.lr_final
        lr_schedule = lambda pr: _lr_final + (_lr_init - _lr_final) * pr
    else:
        lr_schedule = _lr_init

    if args.resume:
        print(f"[train] resuming from {args.resume}")
        model = PPO.load(args.resume, env=envs, tensorboard_log=args.tb_dir)
        # PPO.load restores hyperparameters from the checkpoint, ignoring
        # anything we'd pass in the PPO() constructor below. Override the
        # ones we want to actually change on resume.
        model.ent_coef = 0.01      # see PPO() construction below for rationale
        model.learning_rate = 3e-4
        model.clip_range = lambda _progress: 0.2  # PPO expects a callable
        print(f"[train] overriding ent_coef={model.ent_coef}, lr={model.learning_rate}")
    else:
        # SB3 defaults proven on continuous-control tasks; the plan in
        # PROJECT_STATUS.md prescribes these explicitly.
        # net_arch={pi: [256, 256], vf: [256, 256]} gives a ~16x larger
        # network than SB3's MlpPolicy default of [64, 64]. The default ~10k
        # parameters were the actual bottleneck: terrain randomization
        # SHOULD push reward higher, but the prior result was slightly
        # worse — sign that the policy didn't have enough capacity to learn
        # general driving (back-up-and-retry, wheelie management, recovery)
        # in addition to the new terrain diversity. Going to 256x256 gives
        # the network room to actually represent these behaviors.
        arch_layers = [int(x) for x in args.net_arch.split("x")]
        policy_kwargs = dict(net_arch=dict(pi=arch_layers, vf=arch_layers))
        model = PPO(
            "MlpPolicy",
            envs,
            policy_kwargs=policy_kwargs,
            learning_rate=lr_schedule,
            n_steps=2048,
            batch_size=256,
            n_epochs=10,
            gamma=args.gamma,
            gae_lambda=0.95,
            clip_range=0.2,
            seed=args.seed,
            ent_coef=0.01,      # back to default. ent_coef=0.03 worked early
                                # (found a late-training breakout to ~290 rew),
                                # but once the policy is competent the entropy
                                # bonus stops adding value and starts hurting —
                                # keeps the policy noisier than it needs to be,
                                # which lowers deterministic eval performance.
                                # Standard practice: high entropy → low entropy
                                # as training matures.
            vf_coef=0.5,
            tensorboard_log=args.tb_dir,
            verbose=1,
        )

    print(f"[train] {args.n_envs} envs ({args.vec}), {args.timesteps} timesteps, "
          f"randomize_terrain={args.randomize_terrain}")
    if args.reverse_curriculum:
        print(f"[train] reverse-curriculum: f~U(0,f_max); f_max 0 (warmup {args.rc_warmup_frac:.0%}) "
              f"-> {args.rc_fmax_cap:g} (ramp {args.rc_ramp_frac:.0%}), then hold")
        if args.rc_fmax_cap <= 0.0:
            print(f"[train]   (rc-fmax-cap=0 -> NORMAL-ONLY baseline arm)")
        print(f"[train] anti-degradation: lr 3e-4 -> {args.lr_final:g}, "
              f"ent_coef 0.01 -> {args.ent_final:g} (linear over run)")
    print(f"[train] checkpoints -> {args.checkpoint_dir}")
    print(f"[train] tensorboard -> {args.tb_dir}   (tensorboard --logdir {args.tb_dir})")
    t0 = time.time()
    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=callbacks,
            tb_log_name=args.name,
            reset_num_timesteps=(args.resume is None),
            progress_bar=False,
        )
    finally:
        envs.close()

    final_path = os.path.join(args.checkpoint_dir, f"{args.name}_final.zip")
    model.save(final_path)
    dt = time.time() - t0
    print(f"[train] done in {dt:.1f}s; final model -> {final_path}")


if __name__ == "__main__":
    main()
