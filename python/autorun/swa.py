"""Stochastic Weight Averaging (SWA) of late-training checkpoints.

The deployed snapshot is a ~+60 mean-score 'spike' its lineage can't re-reach by
training (the top of late-PPO's random walk through a near-flat solution basin).
SWA is the standard fix for "the optimizer wanders but no single checkpoint is
reliably best": average the late checkpoints' WEIGHTS -> the basin centroid, which
is reproducible and usually >= any single checkpoint with lower variance.

Averages the last N seed2_resume_*_steps.zip checkpoints (consecutive 100k-step,
low-LR -> same basin, so weight averaging is valid; they bracket the 11.6M spike).
Saves swa_seed2_a.zip. Eval with: robust_ab.py swa_seed2_a.zip 300

Run: python autorun/swa.py [N=10]
"""
import os, sys, glob, re

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import torch                                       # noqa: E402
from stable_baselines3 import PPO                  # noqa: E402

CKDIR = os.path.join(ROOT, "checkpoints")


def step_of(p):
    m = re.search(r"_(\d+)_steps", os.path.basename(p))
    return int(m.group(1)) if m else -1


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    paths = sorted(glob.glob(os.path.join(CKDIR, "seed2_resume_*_steps.zip")), key=step_of)
    if len(paths) < 2:
        sys.exit("need >=2 seed2_resume checkpoints to average")
    sel = paths[-N:]
    print(f"[swa] averaging {len(sel)} checkpoints "
          f"{step_of(sel[0])}..{step_of(sel[-1])}", flush=True)

    models = [PPO.load(p, device="cpu") for p in sel]
    ref = models[0].policy.state_dict()
    avg = {}
    for k in ref:
        if ref[k].is_floating_point():
            acc = torch.zeros_like(ref[k], dtype=torch.float64)
            for m in models:
                acc += m.policy.state_dict()[k].double()
            avg[k] = (acc / len(models)).to(ref[k].dtype)
        else:
            avg[k] = ref[k].clone()      # non-float buffers: keep the reference
    models[0].policy.load_state_dict(avg)

    out = os.path.join(CKDIR, "swa_seed2_a.zip")
    models[0].save(out)
    print(f"[swa] saved -> {out}")


if __name__ == "__main__":
    main()
