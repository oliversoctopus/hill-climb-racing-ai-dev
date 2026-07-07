"""PPO training entrypoint.

Defaults are the champion recipe: per-wheel obs, reward shaping, and the
LR/entropy decay schedule are always on. Logs to TensorBoard at python/tb/
and checkpoints every 100k steps to python/checkpoints/.

Usage:
    python train.py --timesteps 8000000 --seed 1 --name my_run   # champion recipe
    python train.py --timesteps 100000                           # short smoke run
    python train.py --resume checkpoints/ppo_hcr_500000_steps.zip

Each parallel env gets its own seed so terrain differs across workers —
that's the only diversity in training, because within an env we use
fast_reset() (same terrain across episodes).

History: older runs used opt-in flags (--per-wheel --reward-shaping
--reverse-curriculum --rc-fmax-cap 0.0) — that combination IS today's
default. The reverse-curriculum machinery (tested: no benefit) lives in
archive/train_reverse_curriculum.py.
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
                     max_episode_steps: int = 2000, lookahead_n: int = 6,
                     death_penalty: float = 50.0, spawn_jitter: float = 0.0,
                     nudge_prob: float = 0.0, nudge_mag: float = 0.5):
    """Returns a thunk that builds one HillClimbEnv with the given seed.

    Per-wheel obs and reward shaping are the env's defaults (HCR_PER_WHEEL=0 /
    HCR_REWARD_SHAPING=0 env vars opt out for legacy checkpoints).
    """
    def _thunk():
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from env import HillClimbEnv
        from stable_baselines3.common.monitor import Monitor
        env = HillClimbEnv(
            seed=seed,
            max_episode_steps=max_episode_steps,
            randomize_terrain=randomize_terrain,
            lookahead_n=lookahead_n,
            death_penalty=death_penalty,
            spawn_jitter=spawn_jitter,
            nudge_prob=nudge_prob,
            nudge_mag=nudge_mag,
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
    parser.add_argument("--resume-hold-low", action="store_true",
                        help="On resume, HOLD LR/ent at the annealed-low values (--lr-final/"
                             "--ent-final) instead of resetting to 3e-4/0.01. Tests whether "
                             "extra compute past convergence at constant-low helps (Q1 probe). "
                             "Default off preserves the documented reset-high resume behavior.")
    parser.add_argument("--resume-reset-schedule", action="store_true",
                        help="On resume, run a FRESH LR/entropy decay CYCLE: reset the timestep "
                             "clock (reset_num_timesteps=True) so LR re-anneals 3e-4->--lr-final "
                             "and ent 0.01->--ent-final over --timesteps. Network weights are "
                             "kept; only the schedule clock resets. Without this, a plain resume "
                             "keeps the clock at the loaded step count, so the schedules stay "
                             "near their annealed-low end (~= hold-low). Mutually exclusive with "
                             "--resume-hold-low.")
    parser.add_argument("--name", default="ppo_hcr", help="Run name (used in checkpoint filenames + tb subdir)")
    parser.add_argument("--seed", type=int, default=0,
                        help="Master seed: seeds PPO (network init + action sampling) AND offsets the "
                             "per-worker terrain seeds. For an A/B, train both arms with the same "
                             "--seed so init/terrain luck cancels.")
    parser.add_argument("--vec", choices=("subproc", "dummy"), default="subproc",
                        help="VecEnv backend. 'dummy' runs envs in-process (slower but easier to debug).")
    parser.add_argument("--no-randomize-terrain", dest="randomize_terrain",
                        action="store_false", default=True,
                        help="Disable per-episode terrain randomization (each env gets one fixed track).")
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
    parser.add_argument("--recurrent", action="store_true",
                        help="Use sb3-contrib RecurrentPPO (MlpLstmPolicy, contrib-default LSTM: "
                             "256 hidden, separate critic LSTM) on SINGLE-FRAME obs — no "
                             "VecFrameStack; the LSTM replaces the 4-frame stack. Eval needs the "
                             "recurrent-aware eval.py/rc_scan.py (hidden-state threading).")
    parser.add_argument("--death-penalty", type=float, default=50.0,
                        help="Reward subtracted on death/stuck (default 50 — the champion value). "
                             "Larger values train risk-averse 'finish the level' driving at some "
                             "cost in mean pace; pair with --max-steps 4000 so slow play can "
                             "still reach the track end.")
    parser.add_argument("--spawn-jitter", type=float, default=0.0,
                        help="Robustness training: perturb the spawn by +-N px (uniform) each "
                             "episode so the policy must learn wide-basin trajectories that "
                             "survive the same micro-perturbation the eval/Best-of-X jitter "
                             "applies. Default 0 (off) is byte-identical to the champion recipe. "
                             "Try 1.0 to match the +-1px eval jitter.")
    parser.add_argument("--nudge-prob", type=float, default=0.0,
                        help="Exploration nudge: per-tick probability of an in-episode "
                             "physics 'nudge' (a small recoverable velocity/angular kick to "
                             "the chassis) while grounded. Broadens the training state "
                             "distribution so the policy learns to recover/continue from "
                             "being knocked off its trajectory; modeled as env dynamics noise "
                             "(PPO stays on-policy). The death penalty is suppressed for ~1s "
                             "after each nudge so a nudge-caused death isn't charged to the "
                             "policy. Default 0 (off) = byte-identical to the champion recipe. "
                             "Try ~0.01 (about 1 nudge / 100 grounded ticks).")
    parser.add_argument("--nudge-mag", type=float, default=0.5,
                        help="Peak |angular-velocity| nudge in rad/s (chassis ang_vel obs is "
                             "normalized by 4); the linear vx/vy kick scales with it. Only "
                             "used when --nudge-prob > 0. Default 0.5 (small, recoverable).")
    # ---- Anti-degradation decay (always on): LR and entropy decay linearly
    # over the run. This was the real lift behind the old --reverse-curriculum
    # flag (+155 vs no decay); the curriculum itself tested as no benefit and
    # was retired to archive/train_reverse_curriculum.py.
    parser.add_argument("--lr-final", type=float, default=1e-4,
                        help="Learning rate at end of training (linear decay from 3e-4). Default 1e-4.")
    parser.add_argument("--ent-final", type=float, default=0.003,
                        help="ent_coef at end of training (linear decay from 0.01). Lower entropy late "
                             "stabilizes the competent policy. Default 0.003.")
    args = parser.parse_args()

    if args.resume_hold_low and args.resume_reset_schedule:
        parser.error("--resume-hold-low and --resume-reset-schedule are mutually exclusive")

    os.makedirs(args.checkpoint_dir, exist_ok=True)
    os.makedirs(args.tb_dir, exist_ok=True)

    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecFrameStack
    from stable_baselines3.common.callbacks import CheckpointCallback, CallbackList, BaseCallback
    if args.recurrent:
        from sb3_contrib import RecurrentPPO

    class EntropyDecayCallback(BaseCallback):
        """Linearly decays ent_coef over the run (once per rollout, cheap).
        Counters the late-training score collapse seen before decay was
        introduced (e.g. ppo_p5_curriculum_a: 1167 @ 5.5M -> 808 @ 8M)."""

        def __init__(self, total_timesteps, ent_start, ent_end):
            super().__init__()
            self.total = max(1, int(total_timesteps))
            self.ent_start = float(ent_start)
            self.ent_end = float(ent_end)

        def _on_rollout_start(self):
            prog = min(1.0, self.num_timesteps / self.total)
            ent = self.ent_start + (self.ent_end - self.ent_start) * prog
            self.model.ent_coef = ent
            self.logger.record("train/ent_coef_scheduled", ent)

        def _on_step(self):
            return True

    # Worker terrain seeds offset by the master seed so different --seed values
    # give different terrain too (and a given --seed reproduces the same set).
    worker_seed_base = 1000 + args.seed * 100
    env_factories = [make_env_factory(seed=worker_seed_base + i,
                                       randomize_terrain=args.randomize_terrain,
                                       max_episode_steps=args.max_steps,
                                       lookahead_n=args.lookahead_n,
                                       death_penalty=args.death_penalty,
                                       spawn_jitter=args.spawn_jitter,
                                       nudge_prob=args.nudge_prob,
                                       nudge_mag=args.nudge_mag)
                     for i in range(args.n_envs)]
    VecCls = SubprocVecEnv if args.vec == "subproc" else DummyVecEnv
    envs = VecCls(env_factories)
    # Frame stack: each observation becomes [obs(t-3), obs(t-2), obs(t-1), obs(t)]
    # concatenated (12-dim per-wheel obs × 4 = 48). Lets the policy see velocity
    # trends, angle oscillation, on-ground transitions etc. — temporal context
    # that a single-frame obs can't capture. Incompatible with non-stacked
    # checkpoints; required fresh retrain after introducing.
    # --recurrent: NO stack — the LSTM carries temporal context instead (and far
    # more of it); single-frame 12-dim obs.
    if not args.recurrent:
        # n_stack defaults to the champion's 4; HCR_N_STACK overrides (eval must
        # match). Used to probe explicit temporal context (e.g. 8).
        _n_stack = int(os.environ.get("HCR_N_STACK", "4"))
        envs = VecFrameStack(envs, n_stack=_n_stack)

    callbacks = CallbackList([
        CheckpointCallback(
            save_freq=max(1, args.save_every // args.n_envs),
            save_path=args.checkpoint_dir,
            name_prefix=args.name,
        ),
        EntropyDecayCallback(args.timesteps, ent_start=0.01, ent_end=args.ent_final),
    ])

    # Learning-rate schedule: linear 3e-4 -> args.lr_final. SB3 calls this with
    # progress_remaining (1.0 at start -> 0.0 at end).
    _lr_init = 3e-4
    _lr_final = args.lr_final
    lr_schedule = lambda pr: _lr_final + (_lr_init - _lr_final) * pr

    AlgoCls = RecurrentPPO if args.recurrent else PPO
    policy_name = "MlpLstmPolicy" if args.recurrent else "MlpPolicy"

    if args.resume:
        print(f"[train] resuming from {args.resume}")
        model = AlgoCls.load(args.resume, env=envs, tensorboard_log=args.tb_dir)
        # PPO.load restores hyperparameters from the checkpoint, ignoring
        # anything we'd pass in the PPO() constructor below. Override the
        # ones we want to actually change on resume.
        if args.resume_hold_low:
            # Q1 probe: keep the already-annealed schedule LOW and CONSTANT (no
            # re-anneal). The EntropyDecayCallback also holds ent_end here because
            # num_timesteps >= args.timesteps -> progress clamps to 1.0.
            from stable_baselines3.common.utils import constant_fn
            model.ent_coef = args.ent_final          # e.g. 0.003
            model.learning_rate = args.lr_final       # e.g. 1e-4
            model.lr_schedule = constant_fn(args.lr_final)  # force constant LR
            model.clip_range = lambda _progress: 0.2
            print(f"[train] resume HOLD-LOW: ent_coef={model.ent_coef}, lr={args.lr_final} (constant)")
        else:
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
        model = AlgoCls(
            policy_name,
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
            ent_coef=0.01,      # decayed to --ent-final by EntropyDecayCallback.
                                # High entropy early aids exploration; once the
                                # policy is competent the bonus stops adding
                                # value and starts hurting — keeps the policy
                                # noisier than it needs to be, which lowers
                                # deterministic eval performance.
            vf_coef=0.5,
            tensorboard_log=args.tb_dir,
            verbose=1,
        )

    print(f"[train] {args.n_envs} envs ({args.vec}), {args.timesteps} timesteps, "
          f"randomize_terrain={args.randomize_terrain}, "
          f"death_penalty={args.death_penalty:g}, max_steps={args.max_steps}, "
          f"spawn_jitter={args.spawn_jitter:g}px, "
          f"nudge=p{args.nudge_prob:g}/mag{args.nudge_mag:g}, "
          f"algo={'RecurrentPPO (no frame stack)' if args.recurrent else 'PPO (stack 4)'}")
    print(f"[train] decay: lr 3e-4 -> {args.lr_final:g}, "
          f"ent_coef 0.01 -> {args.ent_final:g} (linear over run)")
    print(f"[train] checkpoints -> {args.checkpoint_dir}")
    print(f"[train] tensorboard -> {args.tb_dir}   (tensorboard --logdir {args.tb_dir})")
    t0 = time.time()
    try:
        # Fresh schedule cycle on resume (--resume-reset-schedule) re-anneals
        # LR/ent from high by resetting the timestep clock; weights are kept.
        reset_num = (args.resume is None) or args.resume_reset_schedule
        model.learn(
            total_timesteps=args.timesteps,
            callback=callbacks,
            tb_log_name=args.name,
            reset_num_timesteps=reset_num,
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
