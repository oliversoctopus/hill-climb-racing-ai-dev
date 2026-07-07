"""Overnight multi-seed sweep on p5-noise terrain.

For each config × seed:
  1. Train 8M PPO (~60 min) — captures full TB curve + per-100k checkpoints
  2. Scan TB events for the highest ep_rew_mean step
  3. Eval that peak checkpoint at 200 episodes (deterministic)
  4. Record mean / std / quantiles → JSON

If a run crashes the script keeps going (other seeds still useful).
Final report at the end has per-config aggregates so we can see real signal
vs the noise we've been fighting.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                   # .../python
PROJECT_ROOT = os.path.dirname(ROOT)           # .../Hill-Climb-Racing-AI
PY = os.path.join(PROJECT_ROOT, "python", ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable  # fallback if running from outside the venv path

TB_DIR = os.path.join(ROOT, "tb")
CKPT_DIR = os.path.join(ROOT, "checkpoints")
RESULTS_PATH = os.path.join(HERE, "p5_sweep_results.json")
LOG_DIR = os.path.join(HERE, "p5_sweep_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# All runs go through this exact recipe (only --name + extra flags vary).
TRAIN_BASE = ["--timesteps", "8000000", "--n-envs", "8", "--vec", "subproc"]
EVAL_EPISODES = 200

SWEEP = [
    # 3 baselines = noise estimate for the default config on p5 terrain
    {"name": "ppo_p5_baseline_a",  "flags": [],                                "per_wheel": False},
    {"name": "ppo_p5_baseline_b",  "flags": [],                                "per_wheel": False},
    {"name": "ppo_p5_baseline_c",  "flags": [],                                "per_wheel": False},
    # 2 reward shaping seeds
    {"name": "ppo_p5_reward_a",    "flags": ["--reward-shaping"],              "per_wheel": False},
    {"name": "ppo_p5_reward_b",    "flags": ["--reward-shaping"],              "per_wheel": False},
    # 2 combo (per-wheel + reward) seeds
    {"name": "ppo_p5_combo_a",     "flags": ["--per-wheel", "--reward-shaping"], "per_wheel": True},
    {"name": "ppo_p5_combo_b",     "flags": ["--per-wheel", "--reward-shaping"], "per_wheel": True},
]


def find_peak_step(run_name: str):
    """Return (step, ep_rew_mean) for the run's TB log peak. None on failure."""
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    candidates = [os.path.join(TB_DIR, run_name + "_1"),
                  os.path.join(TB_DIR, run_name + "_0"),
                  os.path.join(TB_DIR, run_name)]
    path = next((p for p in candidates if os.path.isdir(p)), None)
    if path is None:
        return None
    ea = EventAccumulator(path, size_guidance={"scalars": 0})
    ea.Reload()
    if "rollout/ep_rew_mean" not in ea.Tags()["scalars"]:
        return None
    events = ea.Scalars("rollout/ep_rew_mean")
    if not events:
        return None
    peak = max(events, key=lambda e: e.value)
    return peak.step, peak.value


def nearest_checkpoint(run_name: str, target_step: int) -> str:
    """Pick the 100k-stride checkpoint nearest to target_step."""
    import glob
    pattern = os.path.join(CKPT_DIR, f"{run_name}_*_steps.zip")
    files = []
    for f in glob.glob(pattern):
        base = os.path.basename(f)
        # filename: <name>_<step>_steps.zip
        try:
            step = int(base.replace(run_name + "_", "").replace("_steps.zip", ""))
            files.append((step, f))
        except ValueError:
            continue
    if not files:
        return None
    # Closest by absolute distance to target
    files.sort(key=lambda kv: abs(kv[0] - target_step))
    return files[0][1]


def eval_checkpoint(ckpt_path: str, per_wheel: bool) -> dict | None:
    """Run 200-episode eval (deterministic) and parse mean score from output."""
    env = {**os.environ}
    if per_wheel:
        env["HCR_PER_WHEEL"] = "1"
    log_path = os.path.join(LOG_DIR, os.path.basename(ckpt_path) + ".evallog")
    cmd = [PY, os.path.join(ROOT, "eval.py"), ckpt_path,
           "--batch", "--episodes", str(EVAL_EPISODES),
           "--random-terrain", "--deterministic"]
    with open(log_path, "w", encoding="utf-8") as f:
        p = subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        return None
    # Parse final summary lines from the log
    with open(log_path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    import re
    m = re.search(r"score:\s+mean=([-\d.]+)\s+std=([-\d.]+)\s+min=(\d+)\s+max=(\d+)", text)
    if not m:
        return {"raw_tail": text[-1000:]}
    q = re.search(r"quantiles \(10/25/50/75/90\):\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", text)
    return {
        "mean":  float(m.group(1)),
        "std":   float(m.group(2)),
        "min":   int(m.group(3)),
        "max":   int(m.group(4)),
        "q10":   int(q.group(1)) if q else None,
        "q25":   int(q.group(2)) if q else None,
        "q50":   int(q.group(3)) if q else None,
        "q75":   int(q.group(4)) if q else None,
        "q90":   int(q.group(5)) if q else None,
    }


def load_results():
    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_results(results):
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def main():
    results = load_results()
    t_start = time.time()

    for i, run in enumerate(SWEEP):
        name = run["name"]
        if name in results and results[name].get("completed"):
            print(f"[sweep] skip {name} — already in results.json")
            continue

        print(f"\n========== [{i+1}/{len(SWEEP)}] {name} ==========")
        print(f"   flags: {run['flags']}")
        train_log = os.path.join(LOG_DIR, name + "_train.log")
        train_cmd = [PY, os.path.join(ROOT, "train.py")] + TRAIN_BASE + \
                    ["--name", name] + run["flags"]

        t0 = time.time()
        with open(train_log, "w", encoding="utf-8") as f:
            p = subprocess.run(train_cmd, stdout=f, stderr=subprocess.STDOUT)
        train_secs = time.time() - t0
        print(f"   training done in {train_secs:.0f}s  (exit {p.returncode})")
        if p.returncode != 0:
            results[name] = {"error": "training failed", "exit": p.returncode,
                             "train_secs": train_secs}
            save_results(results)
            continue

        peak = find_peak_step(name)
        if peak is None:
            print(f"   ERROR: no TB peak for {name}")
            results[name] = {"error": "no TB peak", "train_secs": train_secs}
            save_results(results)
            continue
        peak_step, peak_rew = peak
        print(f"   TB peak ep_rew_mean = {peak_rew:.1f} at step {peak_step}")

        ckpt = nearest_checkpoint(name, peak_step)
        if ckpt is None:
            print(f"   ERROR: no checkpoint near step {peak_step}")
            results[name] = {"error": "no near checkpoint",
                             "peak_step": peak_step, "peak_rew": peak_rew,
                             "train_secs": train_secs}
            save_results(results)
            continue
        print(f"   evaling {os.path.basename(ckpt)}")
        t0 = time.time()
        eval_res = eval_checkpoint(ckpt, per_wheel=run.get("per_wheel", False))
        eval_secs = time.time() - t0
        print(f"   eval done in {eval_secs:.0f}s  -> {eval_res}")

        results[name] = {
            "completed": True,
            "flags": run["flags"],
            "per_wheel": run.get("per_wheel", False),
            "train_secs": train_secs,
            "peak_step": peak_step,
            "peak_rew": peak_rew,
            "ckpt": os.path.basename(ckpt),
            "eval": eval_res,
            "eval_secs": eval_secs,
        }
        save_results(results)

    print("\n\n================ FINAL REPORT ================")
    print(f"Total wall time: {(time.time()-t_start)/60:.1f} min\n")
    # Group by config (drop trailing _a/_b/_c)
    from collections import defaultdict
    groups = defaultdict(list)
    for name, r in results.items():
        if not r.get("completed"):
            continue
        config = "_".join(name.split("_")[:-1])
        groups[config].append(r["eval"]["mean"])
    print(f"{'config':<32s}  {'n':>3s}  {'mean':>7s}  {'std':>6s}  {'individual scores':<40s}")
    print("-" * 100)
    import statistics
    for config in sorted(groups.keys()):
        scores = groups[config]
        m = statistics.mean(scores)
        s = statistics.stdev(scores) if len(scores) > 1 else 0.0
        ss = "  ".join(f"{v:.0f}" for v in scores)
        print(f"{config:<32s}  {len(scores):>3d}  {m:>7.1f}  {s:>6.1f}  {ss}")


if __name__ == "__main__":
    main()
