"""Self-imitation demo harvester (phase 1 of the lucky-rollout pipeline).

Per pinned track:
  1. one DETERMINISTIC baseline attempt -> d_det (where the argmax controller
     gets to). Tracks the baseline already completes are skipped — nothing to
     learn there.
  2. K STOCHASTIC attempts (policy-distribution sampling, optional temperature,
     plus +-1px spawn jitter for state diversity). Attempts that beat the
     baseline by --keep-margin px are "lucky rollouts".
  3. From each kept attempt, extract the DIVERGENCE SEGMENT: the step window
     where the car approaches and passes the baseline's death zone
     (d_det - pre .. d_det + post). Most of a lucky episode agrees with argmax
     anyway; the informative decisions are concentrated at the fork.

Why stochastic sampling is required: BC on deterministic rollouts is vacuous —
every (s, a) pair already satisfies a = argmax(s). Only sampled off-argmax
actions that led to better outcomes carry learning signal. The summary reports
the off-argmax ("fork") rate; if it is tiny (the entropy-decayed policy is
peaked), re-run with --temperature > 1.

Output (.npz): per-step arrays  obs (N,48) float32, actions (N,) int8,
rtg (N,) float32 (gamma-discounted return-to-go over the FULL episode),
is_fork (N,) bool;  per-segment tables  seg_start/seg_end (indices into the
step arrays), seg_track, seg_attempt, seg_d_det, seg_d_att;  and a json
config string. Advantage weights are computed at fine-tune time as
max(0, rtg - V(s)) using the (frozen) champion critic.

Run:
  python\\.venv\\Scripts\\python.exe python\\harvest.py ^
      python\\checkpoints\\base_a_8000000_steps.zip ^
      --tracks 1000 --attempts 8 --workers 8 --out python\\demos\\base_a_h1.npz
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys

import numpy as np

os.environ.setdefault("HCR_PER_WHEEL", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from constants import GROUND_DISTANCE, SPAWN_X  # noqa: E402

END_PX = GROUND_DISTANCE - 350.0
COMPLETE_PX = END_PX - 600.0

_W: dict = {}  # per-worker state (model, cfg) — populated by _init_worker


def _init_worker(ckpt: str, cfg: dict) -> None:
    os.environ["HCR_PER_WHEEL"] = "1"
    import torch as th
    th.set_num_threads(1)  # 8 workers x default threads oversubscribes the CPU
    from stable_baselines3 import PPO
    _W["model"] = PPO.load(ckpt, device="cpu")
    _W["cfg"] = cfg


def _sample_action(model, obs: np.ndarray, temperature: float):
    """Sample from the policy distribution (optionally temperature-scaled).
    Returns (action, is_fork) where is_fork = sampled action != argmax."""
    import torch as th
    obs_th, _ = model.policy.obs_to_tensor(obs)
    with th.no_grad():
        dist = model.policy.get_distribution(obs_th)
        logits = dist.distribution.logits
        argmax = int(logits.argmax(dim=-1).item())
        if temperature != 1.0:
            logits = logits / temperature
        action = int(th.distributions.Categorical(logits=logits).sample().item())
    return action, action != argmax


def _run_episode(venv, model, *, stochastic: bool, temperature: float, record: bool):
    """Run one episode. If record, returns (max_dist, traj dict); else (max_dist, None)."""
    obs = venv.reset()
    obs_l, act_l, rew_l, dist_l, fork_l = [], [], [], [], []
    done = False
    info: dict = {}
    while not done:
        if stochastic:
            a, fork = _sample_action(model, obs, temperature)
            act = np.array([a])
        else:
            act, _ = model.predict(obs, deterministic=True)
            fork = False
        if record:
            obs_l.append(obs[0].astype(np.float32))
            act_l.append(int(act[0]))
            fork_l.append(fork)
        obs, r, d, i = venv.step(act)
        done = bool(d[0])
        info = i[0]
        if record:
            rew_l.append(float(r[0]))
            dist_l.append(float(info.get("max_distance_px", 0.0)))
    max_dist = float(info.get("max_distance_px", 0.0))
    if not record:
        return max_dist, None
    return max_dist, {
        "obs": np.asarray(obs_l, dtype=np.float32),
        "actions": np.asarray(act_l, dtype=np.int8),
        "rewards": np.asarray(rew_l, dtype=np.float32),
        "max_dist_px": np.asarray(dist_l, dtype=np.float32),
        "is_fork": np.asarray(fork_l, dtype=bool),
    }


def _rtg(rewards: np.ndarray, gamma: float) -> np.ndarray:
    out = np.zeros_like(rewards)
    acc = 0.0
    for i in range(len(rewards) - 1, -1, -1):
        acc = rewards[i] + gamma * acc
        out[i] = acc
    return out


def harvest_track(t: int) -> dict:
    """Worker: returns segments + stats for one pinned track."""
    cfg = _W["cfg"]
    model = _W["model"]
    import torch as th
    from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack
    import env as E
    from env import HillClimbEnv
    from ground import make_ground

    # Pin the track (global-RNG seed right before generation — same scheme as
    # diagnostics/jitter_probe.py; do NOT trust env seeds for track identity).
    random.seed(cfg["seed_base"] + t)
    th.manual_seed(cfg["seed_base"] + t)
    g = make_ground(None, difficulty=0.0)

    orig = E._make_ground
    E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
    try:
        venv = VecFrameStack(DummyVecEnv([lambda: HillClimbEnv(
            max_episode_steps=5000, randomize_terrain=False,
            per_wheel_obs=True, reward_shaping=True)]), 4)
        venv.reset()
        raw = venv.venv.envs[0].unwrapped
        sy = float(raw._ground.spawning_y)

        # 1) deterministic baseline
        raw._js.set_spawn(float(SPAWN_X), sy)
        d_det, _ = _run_episode(venv, model, stochastic=False,
                                temperature=1.0, record=False)
        stats = {"track": t, "d_det": d_det, "det_complete": d_det >= COMPLETE_PX,
                 "attempts": 0, "kept": 0, "fork_steps": 0, "total_steps": 0}
        segments = []
        if stats["det_complete"]:
            return {"stats": stats, "segments": segments}

        # 2) stochastic attempts
        jrng = random.Random(cfg["seed_base"] * 31 + t)
        for k in range(cfg["attempts"]):
            dx = (jrng.random() - 0.5) * 2.0
            dy = (jrng.random() - 0.5) * 2.0
            raw._js.set_spawn(SPAWN_X + dx, sy + dy)
            d_att, traj = _run_episode(venv, model, stochastic=True,
                                       temperature=cfg["temperature"], record=True)
            stats["attempts"] += 1
            stats["fork_steps"] += int(traj["is_fork"].sum())
            stats["total_steps"] += len(traj["actions"])
            if d_att < d_det + cfg["keep_margin"]:
                continue

            # 3) divergence segment around the baseline's death zone
            md = traj["max_dist_px"]
            start_idx = int(np.argmax(md >= d_det - cfg["pre_px"]))
            past = md >= d_det + cfg["post_px"]
            end_idx = int(np.argmax(past)) if past.any() else len(md)
            if end_idx <= start_idx:
                continue
            rtg = _rtg(traj["rewards"], cfg["gamma"])
            segments.append({
                "track": t, "attempt": k, "d_det": d_det, "d_att": d_att,
                "obs": traj["obs"][start_idx:end_idx],
                "actions": traj["actions"][start_idx:end_idx],
                "rtg": rtg[start_idx:end_idx].astype(np.float32),
                "is_fork": traj["is_fork"][start_idx:end_idx],
            })
            stats["kept"] += 1
        venv.close()
        return {"stats": stats, "segments": segments}
    finally:
        E._make_ground = orig


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("checkpoint")
    p.add_argument("--tracks", type=int, default=200)
    p.add_argument("--attempts", type=int, default=8)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--temperature", type=float, default=1.0,
                   help="sampling temperature (>1 = more off-argmax forks)")
    p.add_argument("--keep-margin", type=float, default=500.0,
                   help="attempt must beat the deterministic baseline by this many px")
    p.add_argument("--pre-px", type=float, default=1000.0,
                   help="segment starts this many px before the baseline death point")
    p.add_argument("--post-px", type=float, default=1500.0,
                   help="segment ends once the car is this many px past it")
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--seed-base", type=int, default=2_000_000)
    p.add_argument("--out", default=os.path.join(HERE, "demos", "harvest.npz"))
    args = p.parse_args()

    cfg = {"attempts": args.attempts, "temperature": args.temperature,
           "keep_margin": args.keep_margin, "pre_px": args.pre_px,
           "post_px": args.post_px, "gamma": args.gamma,
           "seed_base": args.seed_base, "tracks": args.tracks,
           "checkpoint": args.checkpoint}

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    all_segments, all_stats = [], []
    with mp.Pool(args.workers, initializer=_init_worker,
                 initargs=(args.checkpoint, cfg)) as pool:
        for n_done, res in enumerate(
                pool.imap_unordered(harvest_track, range(args.tracks)), 1):
            all_stats.append(res["stats"])
            all_segments.extend(res["segments"])
            if n_done % 10 == 0 or n_done == args.tracks:
                kept = sum(s["kept"] for s in all_stats)
                print(f"  [{n_done}/{args.tracks}] tracks done — "
                      f"{kept} segments so far", flush=True)

    # ---- summary ----
    n_complete = sum(s["det_complete"] for s in all_stats)
    n_att = sum(s["attempts"] for s in all_stats)
    n_kept = sum(s["kept"] for s in all_stats)
    fork = sum(s["fork_steps"] for s in all_stats)
    steps = sum(s["total_steps"] for s in all_stats)
    print(f"\n[harvest] {args.tracks} tracks | det-complete (skipped): "
          f"{n_complete} ({100*n_complete/max(1,args.tracks):.0f}%)")
    print(f"  stochastic attempts: {n_att}  kept (beat baseline by "
          f">{args.keep_margin:.0f}px): {n_kept} ({100*n_kept/max(1,n_att):.1f}%)")
    print(f"  off-argmax fork rate: {100*fork/max(1,steps):.2f}% of steps "
          f"(temperature {args.temperature}) — if <~1%, consider --temperature 1.5+")

    if not all_segments:
        print("  no segments harvested — nothing to save.")
        return

    obs = np.concatenate([s["obs"] for s in all_segments])
    actions = np.concatenate([s["actions"] for s in all_segments])
    rtg = np.concatenate([s["rtg"] for s in all_segments])
    is_fork = np.concatenate([s["is_fork"] for s in all_segments])
    lens = np.array([len(s["actions"]) for s in all_segments])
    seg_end = np.cumsum(lens)
    seg_start = seg_end - lens
    np.savez_compressed(
        args.out,
        obs=obs, actions=actions, rtg=rtg, is_fork=is_fork,
        seg_start=seg_start.astype(np.int64), seg_end=seg_end.astype(np.int64),
        seg_track=np.array([s["track"] for s in all_segments], dtype=np.int32),
        seg_attempt=np.array([s["attempt"] for s in all_segments], dtype=np.int32),
        seg_d_det=np.array([s["d_det"] for s in all_segments], dtype=np.float32),
        seg_d_att=np.array([s["d_att"] for s in all_segments], dtype=np.float32),
        config=json.dumps(cfg),
    )
    print(f"  saved {len(all_segments)} segments / {len(actions)} steps "
          f"({obs.nbytes/1e6:.0f} MB obs) -> {args.out}")
    print(f"  segment fork-step share: {100*is_fork.mean():.2f}%  "
          f"mean rtg: {rtg.mean():.1f}")


if __name__ == "__main__":
    main()
