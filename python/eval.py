"""Run a trained PPO policy with the pygame renderer (default) OR a headless
batch eval that prints summary statistics over many episodes.

Usage:
    # Watch mode (default) — opens a pygame window:
    python eval.py checkpoints/ppo_hcr_final.zip
    python eval.py checkpoints/ppo_hcr_final.zip --random-terrain --episodes 5

    # Batch mode — no rendering, many episodes, summary stats:
    python eval.py checkpoints/ppo_hcr_final.zip --batch --episodes 200 --random-terrain --deterministic

    # A/B mode — paired comparison on identical terrains, paired t-test:
    python eval.py model_a.zip --ab model_b.zip --episodes 200 --random-terrain --deterministic --ab-deterministic
    python eval.py model.zip --ab model.zip --deterministic --episodes 200 --random-terrain
                       # ^ same model, A=deterministic, B=stochastic

Notes:
    --random-terrain: generate fresh terrain each episode (deterministic
                      from --seed; same seed reproduces the same series).
                      Without this, all episodes share one terrain.
    --batch:          headless; uses the env's faster reset path; ideal for
                      reliable averaged performance over many trials.

Controls during watch mode:
    R         reset (next episode)
    ESC / Q   quit
    +/-       speed up / slow down sim (1..8x)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from env import HillClimbEnv  # noqa: E402


def _is_recurrent(model_path: str) -> bool:
    """Peek inside the SB3 .zip: RecurrentPPO checkpoints use an Lstm policy."""
    import json
    import zipfile
    with zipfile.ZipFile(model_path, "r") as zf:
        with zf.open("data") as f:
            data = json.loads(f.read().decode("utf-8"))
    pc = str(data.get("policy_class", ""))
    return "Lstm" in pc or "Recurrent" in pc


def _load_model(model_path: str):
    """Load PPO or RecurrentPPO based on the checkpoint's policy class."""
    if _is_recurrent(model_path):
        from sb3_contrib import RecurrentPPO
        return RecurrentPPO.load(model_path), True
    from stable_baselines3 import PPO
    return PPO.load(model_path), False


def _build_env(*, randomize_terrain, seed, max_steps, render_mode, recurrent=False):
    """Wrap a HillClimbEnv to match training-time obs: VecFrameStack(4) for
    plain PPO, single-frame for RecurrentPPO (the LSTM replaces the stack)."""
    from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack
    env_single = HillClimbEnv(
        max_episode_steps=max_steps,
        render_mode=render_mode,
        seed=seed,
        randomize_terrain=randomize_terrain,
    )
    env = DummyVecEnv([lambda: env_single])
    if not recurrent:
        env = VecFrameStack(env, n_stack=4)
    return env, env_single


def run_watch(args, model):
    """Interactive single-window eval. Renders, supports keyboard controls."""
    import pygame
    from constants import FRAME_RATE  # noqa

    env, env_single = _build_env(
        randomize_terrain=args.random_terrain,
        seed=args.seed,
        max_steps=args.max_steps,
        render_mode="human",
        recurrent=args._recurrent,
    )
    clock = pygame.time.Clock()
    sim_speed = 1
    running = True
    episode = 0

    while running and episode < args.episodes:
        obs = env.reset()  # randomize_terrain=True rebuilds deterministically
        env_single.render(sim_speed=sim_speed)  # pre-init pygame video
        ep_reward = 0.0
        ep_steps = 0
        t0 = time.time()
        done = False
        last_info = {"score": 0, "max_distance_px": 0}
        state = None
        episode_start = np.ones((1,), dtype=bool)

        while not done and running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    elif ev.key == pygame.K_r:
                        done = True
                    elif ev.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                        sim_speed = min(sim_speed + 1, 8)
                    elif ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                        sim_speed = max(sim_speed - 1, 1)

            for _ in range(sim_speed):
                action, state = model.predict(obs, state=state, episode_start=episode_start,
                                              deterministic=args.deterministic)
                obs, rewards, dones, infos = env.step(action)
                episode_start = dones
                ep_reward += float(rewards[0])
                ep_steps += 1
                last_info = infos[0]
                if dones[0]:
                    done = True
                    break

            env_single.render(sim_speed=sim_speed)
            clock.tick(FRAME_RATE)

        dt = time.time() - t0
        print(f"  ep{episode}: reward={ep_reward:+.2f}  steps={ep_steps}  "
              f"score={last_info.get('score', 0)}  "
              f"max_dist={last_info.get('max_distance_px', 0):.0f}px  wall={dt:.1f}s")
        episode += 1

    env.close()


def _play_episode(env, model, deterministic: bool):
    """Run one episode to termination. Returns (reward, score, steps).

    Threads LSTM hidden state + episode_start through predict() — required for
    RecurrentPPO, harmless for plain PPO (which returns state=None).
    """
    obs = env.reset()
    ep_reward = 0.0
    ep_steps = 0
    last_info = {"score": 0}
    done = False
    state = None
    episode_start = np.ones((1,), dtype=bool)
    while not done:
        action, state = model.predict(obs, state=state, episode_start=episode_start,
                                      deterministic=deterministic)
        obs, r, dones, infos = env.step(action)
        episode_start = dones
        ep_reward += float(r[0])
        ep_steps += 1
        last_info = infos[0]
        if dones[0]:
            done = True
    return ep_reward, int(last_info.get("score", 0)), ep_steps


def run_batch(args, model):
    """Headless many-episode eval. Prints summary stats. No rendering."""
    env, _ = _build_env(
        randomize_terrain=args.random_terrain,
        seed=args.seed,
        max_steps=args.max_steps,
        render_mode=None,
        recurrent=args._recurrent,
    )

    print(f"[eval/batch] {args.episodes} episodes  "
          f"random_terrain={args.random_terrain}  deterministic={args.deterministic}")

    rewards = np.zeros(args.episodes, dtype=np.float64)
    scores = np.zeros(args.episodes, dtype=np.int64)
    steps = np.zeros(args.episodes, dtype=np.int64)
    t0 = time.time()

    for ep in range(args.episodes):
        ep_reward, score, ep_steps = _play_episode(env, model, args.deterministic)
        rewards[ep] = ep_reward
        scores[ep] = score
        steps[ep] = ep_steps

        # Periodic progress so the user can see something is happening on long runs.
        if (ep + 1) % max(1, args.episodes // 20) == 0 or ep == args.episodes - 1:
            done_n = ep + 1
            elapsed = time.time() - t0
            eps_per_s = done_n / max(elapsed, 1e-6)
            eta = (args.episodes - done_n) / max(eps_per_s, 1e-6)
            print(f"  [{done_n}/{args.episodes}]  "
                  f"running mean score={scores[:done_n].mean():.1f}  "
                  f"mean reward={rewards[:done_n].mean():+.2f}  "
                  f"({elapsed:.1f}s, ~{eta:.0f}s left)")

    env.close()

    qs = np.quantile(scores, [0.10, 0.25, 0.50, 0.75, 0.90])
    qr = np.quantile(rewards, [0.10, 0.25, 0.50, 0.75, 0.90])
    early_deaths = int((scores < 100).sum())

    print()
    print(f"[eval/batch] Summary over {args.episodes} episodes "
          f"(wall {time.time() - t0:.1f}s):")
    print(f"  reward:  mean={rewards.mean():+.2f}  std={rewards.std():.2f}  "
          f"min={rewards.min():+.2f}  max={rewards.max():+.2f}")
    print(f"           quantiles (10/25/50/75/90): "
          f"{qr[0]:+.1f}  {qr[1]:+.1f}  {qr[2]:+.1f}  {qr[3]:+.1f}  {qr[4]:+.1f}")
    print(f"  score:   mean={scores.mean():.1f}   std={scores.std():.1f}   "
          f"min={scores.min()}   max={scores.max()}")
    print(f"           quantiles (10/25/50/75/90): "
          f"{qs[0]:.0f}  {qs[1]:.0f}  {qs[2]:.0f}  {qs[3]:.0f}  {qs[4]:.0f}")
    print(f"  steps:   mean={steps.mean():.1f}  min={steps.min()}  max={steps.max()}")
    print(f"  early deaths (score<100): {early_deaths}/{args.episodes} "
          f"({100*early_deaths/args.episodes:.1f}%)")

    if args.csv:
        with open(args.csv, "w") as f:
            f.write("episode,reward,score,steps\n")
            for i in range(args.episodes):
                f.write(f"{i},{rewards[i]:.4f},{scores[i]},{steps[i]}\n")
        print(f"[eval/batch] per-episode log -> {args.csv}")


def run_ab(args, model_a, model_b, label_a: str, label_b: str):
    """Paired comparison on identical terrains. Reports paired t-test.

    Both envs are built with the same seed and randomize_terrain flag, so
    they produce the exact same terrain sequence. That makes the per-episode
    score difference (A - B) the right unit of analysis — terrain difficulty
    cancels out, and the test has way more power than two unpaired batches.
    """
    env_a, _ = _build_env(
        randomize_terrain=args.random_terrain,
        seed=args.seed, max_steps=args.max_steps, render_mode=None,
        recurrent=args._recurrent,
    )
    env_b, _ = _build_env(
        randomize_terrain=args.random_terrain,
        seed=args.seed, max_steps=args.max_steps, render_mode=None,
        recurrent=args._recurrent_b,
    )

    print(f"[eval/ab]  A={label_a}  det_A={args.deterministic}")
    print(f"[eval/ab]  B={label_b}  det_B={args.ab_deterministic}")
    print(f"[eval/ab]  {args.episodes} terrains  random_terrain={args.random_terrain}")

    scores_a = np.zeros(args.episodes, dtype=np.int64)
    scores_b = np.zeros(args.episodes, dtype=np.int64)
    rewards_a = np.zeros(args.episodes, dtype=np.float64)
    rewards_b = np.zeros(args.episodes, dtype=np.float64)
    t0 = time.time()

    for ep in range(args.episodes):
        rewards_a[ep], scores_a[ep], _ = _play_episode(env_a, model_a, args.deterministic)
        rewards_b[ep], scores_b[ep], _ = _play_episode(env_b, model_b, args.ab_deterministic)
        if (ep + 1) % max(1, args.episodes // 20) == 0 or ep == args.episodes - 1:
            done_n = ep + 1
            elapsed = time.time() - t0
            eta = (args.episodes - done_n) * elapsed / done_n
            diff_so_far = (scores_a[:done_n] - scores_b[:done_n]).mean()
            print(f"  [{done_n}/{args.episodes}]  "
                  f"mean A={scores_a[:done_n].mean():.1f}  "
                  f"mean B={scores_b[:done_n].mean():.1f}  "
                  f"paired diff={diff_so_far:+.1f}  "
                  f"({elapsed:.1f}s, ~{eta:.0f}s left)")

    env_a.close()
    env_b.close()

    diff = (scores_a - scores_b).astype(np.float64)
    n = args.episodes
    mean_diff = diff.mean()
    sd_diff = diff.std(ddof=1) if n > 1 else 0.0
    se = sd_diff / np.sqrt(n) if n > 1 else 0.0
    t_stat = mean_diff / se if se > 0 else 0.0

    # Two-sided p-value from Student's t with n-1 dof. Fall back to the
    # normal approximation if scipy isn't installed (it's a dep via SB3
    # in practice, but be defensive).
    try:
        from scipy.stats import t as student_t
        p = float(2.0 * (1.0 - student_t.cdf(abs(t_stat), df=n - 1)))
    except Exception:
        from math import erfc, sqrt
        p = float(erfc(abs(t_stat) / sqrt(2.0)))

    # 95% CI on the paired mean diff using t-critical.
    try:
        from scipy.stats import t as student_t
        t_crit = float(student_t.ppf(0.975, df=n - 1))
    except Exception:
        t_crit = 1.96
    ci_lo = mean_diff - t_crit * se
    ci_hi = mean_diff + t_crit * se

    print()
    print(f"[eval/ab] Paired comparison ({n} terrains, wall {time.time() - t0:.1f}s):")
    print(f"  A={label_a}")
    print(f"     mean score = {scores_a.mean():8.2f}   mean reward = {rewards_a.mean():+8.2f}")
    print(f"  B={label_b}")
    print(f"     mean score = {scores_b.mean():8.2f}   mean reward = {rewards_b.mean():+8.2f}")
    print(f"  paired diff (A - B):")
    print(f"     mean = {mean_diff:+.3f}   sd = {sd_diff:.3f}   SE = {se:.3f}")
    print(f"     95% CI = [{ci_lo:+.2f}, {ci_hi:+.2f}]")
    print(f"     t({n-1}) = {t_stat:+.3f}   p = {p:.4f}   "
          f"({'SIGNIFICANT' if p < 0.05 else 'not significant'} at alpha=0.05)")

    wins_a = int((scores_a > scores_b).sum())
    wins_b = int((scores_a < scores_b).sum())
    ties = int((scores_a == scores_b).sum())
    print(f"  per-terrain: A wins {wins_a}  B wins {wins_b}  ties {ties}")

    if args.csv:
        with open(args.csv, "w") as f:
            f.write("episode,score_a,score_b,reward_a,reward_b,diff_score\n")
            for i in range(n):
                f.write(f"{i},{scores_a[i]},{scores_b[i]},"
                        f"{rewards_a[i]:.4f},{rewards_b[i]:.4f},"
                        f"{scores_a[i] - scores_b[i]}\n")
        print(f"[eval/ab] per-terrain log -> {args.csv}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", help="Path to a saved SB3 PPO .zip checkpoint")
    parser.add_argument("--episodes", type=int, default=10,
                        help="Number of episodes. Watch default 10; batch default 10 (set higher for reliable stats).")
    parser.add_argument("--seed", type=int, default=42,
                        help="Base seed. With --random-terrain, this determines the deterministic terrain sequence.")
    parser.add_argument("--max-steps", type=int, default=5000)
    parser.add_argument("--deterministic", action="store_true",
                        help="Use greedy action selection (no exploration noise).")
    parser.add_argument("--batch", action="store_true",
                        help="Headless many-episode eval with summary stats. Don't render.")
    parser.add_argument("--random-terrain", action="store_true",
                        help="Generate fresh terrain each episode (deterministic from --seed).")
    parser.add_argument("--csv", default=None,
                        help="In --batch/--ab mode, write per-episode results to this CSV.")
    parser.add_argument("--ab", default=None, metavar="MODEL_B",
                        help="Paired comparison: run this second checkpoint on the same terrains "
                             "as the first and print a paired t-test on per-terrain score diffs.")
    parser.add_argument("--ab-deterministic", action="store_true",
                        help="In --ab mode, B uses deterministic actions. A's mode is set by --deterministic.")
    args = parser.parse_args()

    if args.ab:
        mode = "ab"
    elif args.batch:
        mode = "batch"
    else:
        mode = "watch"
    print(f"[eval] mode={mode}")

    print(f"[eval] loading {args.model}")
    model, args._recurrent = _load_model(args.model)
    if args._recurrent:
        print("[eval] recurrent (LSTM) checkpoint — single-frame obs, no frame stack")

    if args.ab:
        print(f"[eval] loading B={args.ab}")
        model_b, args._recurrent_b = _load_model(args.ab)
        if args._recurrent_b:
            print("[eval] B is recurrent (LSTM) — single-frame obs, no frame stack")
        label_a = os.path.basename(args.model) + (" (det)" if args.deterministic else " (stoch)")
        label_b = os.path.basename(args.ab) + (" (det)" if args.ab_deterministic else " (stoch)")
        run_ab(args, model, model_b, label_a, label_b)
    elif args.batch:
        run_batch(args, model)
    else:
        run_watch(args, model)


if __name__ == "__main__":
    main()
