"""Tournament-style comparison of trained checkpoints on identical terrains.

Each checkpoint auto-detects its algo (PPO/SAC) and obs shape from the
saved .zip, then gets wrapped in the matching env (current 11-dim baseline,
or one of the legacy variants in compat_envs.py). All models run on the
SAME terrain seed sequence — i.e., every model plays the same N terrains —
so we can do paired t-tests pairwise between any two models.

Per-terrain pairing cancels the dominant variance term (terrain difficulty),
giving the test much more power than independent batches would.

Usage:
    python diagnostics/compare_models.py \\
        checkpoints/ppo_hcr_final.zip \\
        checkpoints/ppo_fixed_final.zip \\
        checkpoints/ppo_stack_final.zip \\
        checkpoints/ppo_obs17_final.zip \\
        checkpoints/ppo_obs20_final.zip \\
        checkpoints/sac_first_final.zip \\
        --episodes 100 --random-terrain --deterministic
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from env import HillClimbEnv  # noqa: E402
from compat_envs import (  # noqa: E402
    HillClimbEnv11DimDelta,
    HillClimbEnv17Dim,
    HillClimbEnv20Dim,
)


def _detect_algo(model_path: str) -> str:
    with zipfile.ZipFile(model_path, "r") as zf:
        with zf.open("data") as f:
            data = json.loads(f.read().decode("utf-8"))
    policy_class = str(data.get("policy_class", ""))
    return "sac" if ("SAC" in policy_class or "sac" in policy_class) else "ppo"


def build_loadout(path: str, *, seed: int, randomize: bool, max_steps: int):
    """Load a model + build the matching env. Returns (vec_env, model, label)."""
    from stable_baselines3 import PPO, SAC
    from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack

    algo = _detect_algo(path)
    ModelCls = SAC if algo == "sac" else PPO
    model = ModelCls.load(path)

    stacked_dim = int(model.observation_space.shape[0])
    continuous = (algo == "sac")

    # Map stacked-obs dim -> (single-frame dim, n_stack, env class).
    # Note: the 11-dim historical checkpoints (ppo_hcr / ppo_fixed / ppo_stack)
    # used JS-style delta-from-first ground encoding, not the current env.py's
    # absolute clearance. Use HillClimbEnv11DimDelta so they see the obs
    # distribution they were trained against.
    if stacked_dim == 11:
        single_dim, n_stack, EnvCls = 11, 1, HillClimbEnv11DimDelta
    elif stacked_dim == 44:
        single_dim, n_stack, EnvCls = 11, 4, HillClimbEnv11DimDelta
    elif stacked_dim == 68:
        single_dim, n_stack, EnvCls = 17, 4, HillClimbEnv17Dim
    elif stacked_dim == 80:
        single_dim, n_stack, EnvCls = 20, 4, HillClimbEnv20Dim
    else:
        raise ValueError(
            f"Unknown obs shape ({stacked_dim},) for {path}. "
            f"Add a mapping in build_loadout() if this is a new variant."
        )

    env_kwargs = dict(
        seed=seed,
        max_episode_steps=max_steps,
        randomize_terrain=randomize,
        render_mode=None,
    )
    # continuous_action only exists on HillClimbEnv; subclasses inherit it.
    env_kwargs["continuous_action"] = continuous

    inner = EnvCls(**env_kwargs)
    vec = DummyVecEnv([lambda: inner])
    if n_stack > 1:
        vec = VecFrameStack(vec, n_stack=n_stack)

    label = (f"{os.path.basename(path):<26s}  algo={algo:3s}  "
             f"single={single_dim:<2d}  stack={n_stack}")
    return vec, model, label


def _play_episode(env, model, deterministic: bool):
    obs = env.reset()
    ep_r = 0.0
    last = {"score": 0}
    done = False
    while not done:
        action, _ = model.predict(obs, deterministic=deterministic)
        obs, r, dones, infos = env.step(action)
        ep_r += float(r[0])
        last = infos[0]
        if dones[0]:
            done = True
    return ep_r, int(last.get("score", 0))


def _paired_t(diff: np.ndarray):
    n = len(diff)
    mean_d = float(diff.mean())
    sd_d = float(diff.std(ddof=1)) if n > 1 else 0.0
    se = sd_d / np.sqrt(n) if n > 1 else 0.0
    t_stat = mean_d / se if se > 0 else 0.0
    try:
        from scipy.stats import t as student_t
        p = float(2.0 * (1.0 - student_t.cdf(abs(t_stat), df=n - 1)))
        t_crit = float(student_t.ppf(0.975, df=n - 1))
    except Exception:
        from math import erfc, sqrt
        p = float(erfc(abs(t_stat) / sqrt(2.0)))
        t_crit = 1.96
    return mean_d, sd_d, se, t_stat, p, t_crit


def main():
    p = argparse.ArgumentParser()
    p.add_argument("models", nargs="+", help="One or more SB3 checkpoint paths.")
    p.add_argument("--episodes", type=int, default=100,
                   help="Number of terrains each model plays.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--deterministic", action="store_true",
                   help="Greedy action selection for every model.")
    p.add_argument("--random-terrain", action="store_true",
                   help="Fresh terrain per episode. All envs use the same seed "
                        "sequence so per-terrain comparisons are paired.")
    p.add_argument("--csv", default=None,
                   help="Write the full models × episodes matrix to this CSV.")
    args = p.parse_args()

    print(f"[compare] loading {len(args.models)} checkpoints "
          f"(seed={args.seed}, det={args.deterministic}, random_terrain={args.random_terrain})")
    loadouts = []
    for path in args.models:
        try:
            env, model, label = build_loadout(
                path, seed=args.seed, randomize=args.random_terrain,
                max_steps=args.max_steps,
            )
        except Exception as e:
            print(f"  SKIP {path}: {e}")
            continue
        loadouts.append((env, model, label, path))
        print(f"  loaded: {label}")

    if len(loadouts) < 2:
        print("[compare] need at least 2 loadable checkpoints for a comparison.")
        return

    n_models = len(loadouts)
    n_eps = args.episodes
    scores = np.zeros((n_models, n_eps), dtype=np.int64)
    rewards = np.zeros((n_models, n_eps), dtype=np.float64)

    print(f"\n[compare] {n_models} models × {n_eps} episodes "
          f"= {n_models * n_eps} runs total")
    t0 = time.time()
    for ep in range(n_eps):
        for m_idx, (env, model, _, _) in enumerate(loadouts):
            r, s = _play_episode(env, model, args.deterministic)
            rewards[m_idx, ep] = r
            scores[m_idx, ep] = s
        done_eps = ep + 1
        if done_eps % max(1, n_eps // 20) == 0 or done_eps == n_eps:
            elapsed = time.time() - t0
            eta = (n_eps - done_eps) * elapsed / done_eps
            best_so_far = scores[:, :done_eps].mean(axis=1).max()
            print(f"  [{done_eps}/{n_eps}]  "
                  f"best mean score so far: {best_so_far:.1f}  "
                  f"({elapsed:.1f}s, ~{eta:.0f}s left)")

    for env, _, _, _ in loadouts:
        env.close()

    # ---------------------------------------------------------------
    # Per-model summary, ranked by mean score.
    # ---------------------------------------------------------------
    means = scores.mean(axis=1)
    medians = np.median(scores, axis=1)
    stds = scores.std(axis=1)
    maxes = scores.max(axis=1)
    order = np.argsort(-means)  # descending

    print()
    print(f"[compare] Per-model summary (sorted by mean score, {n_eps} terrains):")
    print(f"  rank  {'model':<42s}  mean      std      median    max")
    for rank, i in enumerate(order):
        label = loadouts[i][2]
        print(f"  {rank+1:>4d}  {label:<42s}  "
              f"{means[i]:8.1f}  {stds[i]:7.1f}  {medians[i]:6.0f}  {maxes[i]:5d}")

    # ---------------------------------------------------------------
    # Pairwise paired t-tests on the per-terrain score differences.
    # ---------------------------------------------------------------
    print()
    print(f"[compare] Pairwise paired t-tests on score (A - B). "
          f"'*' = p<0.05, '**' = p<0.01:")
    print(f"  {'A':<26s}  {'B':<26s}  diff        95% CI            t        p")
    pairs = []
    for i in range(n_models):
        for j in range(i + 1, n_models):
            diff = (scores[i] - scores[j]).astype(np.float64)
            mean_d, sd_d, se, t_stat, p_val, t_crit = _paired_t(diff)
            ci_lo = mean_d - t_crit * se
            ci_hi = mean_d + t_crit * se
            la = os.path.basename(loadouts[i][3])
            lb = os.path.basename(loadouts[j][3])
            sig = " **" if p_val < 0.01 else (" * " if p_val < 0.05 else "   ")
            pairs.append((la, lb, mean_d, ci_lo, ci_hi, t_stat, p_val, sig))

    # Sort by abs(mean_d) descending so the biggest effects show first.
    for la, lb, mean_d, ci_lo, ci_hi, t_stat, p_val, sig in sorted(
        pairs, key=lambda r: -abs(r[2])
    ):
        print(f"  {la:<26s}  {lb:<26s}  {mean_d:+8.1f}  "
              f"[{ci_lo:+7.1f}, {ci_hi:+7.1f}]  {t_stat:+6.2f}  {p_val:.4f}{sig}")

    # ---------------------------------------------------------------
    # Optional CSV dump (models × episodes matrix, long form).
    # ---------------------------------------------------------------
    if args.csv:
        with open(args.csv, "w") as f:
            f.write("model,episode,score,reward\n")
            for i, (_, _, _, path) in enumerate(loadouts):
                name = os.path.basename(path)
                for ep in range(n_eps):
                    f.write(f"{name},{ep},{scores[i,ep]},{rewards[i,ep]:.4f}\n")
        print(f"\n[compare] full log -> {args.csv}")


if __name__ == "__main__":
    main()
