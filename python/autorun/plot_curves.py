"""Overlay deterministic eval vs stochastic training reward across training,
for seed2 (champion recipe) and fs8 (frame-stack-8). Two panels, twin y-axes;
a vertical line at 4M marks the learning -> plateau regime split."""
import re, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))


def train_series(run):
    txt = open(os.path.join(HERE, 'logs', f'{run}_train.log')).read()
    rews = [float(x) for x in re.findall(r"ep_rew_mean\s*\|\s*([0-9.eE+-]+)", txt)]
    steps = [int(x) for x in re.findall(r"total_timesteps\s*\|\s*([0-9]+)", txt)]
    n = min(len(rews), len(steps))
    return np.array(steps[:n]), np.array(rews[:n])


def curve(run):
    d = np.load(os.path.join(HERE, f'eval_curve_{run}.npz'))
    return d['steps'], d['scores'].mean(axis=1), d['scores'].std(axis=1) / np.sqrt(d['scores'].shape[1])


fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharex=True)
for ax, run, title in zip(axes, ['seed2', 'fs8'],
                          ['seed2 (champion recipe, stack-4)', 'fs8 (frame-stack-8)']):
    ts, tr = train_series(run)
    cs, ce, se = curve(run)
    x = cs / 1e6

    # Left axis: deterministic eval (with SE band).
    l1 = ax.plot(x, ce, 'o-', color='C0', label='deterministic eval (score)')[0]
    ax.fill_between(x, ce - se, ce + se, color='C0', alpha=0.15)
    ax.set_ylabel('deterministic eval score', color='C0')
    ax.tick_params(axis='y', labelcolor='C0')
    ax.set_ylim(900, 1500)
    ax.set_xlabel('training steps (millions)')
    ax.set_title(title)
    ax.axvline(4.0, color='gray', ls=':', lw=1)
    ax.text(4.05, 920, 'learning | plateau', color='gray', fontsize=8)

    # Right axis: stochastic training reward.
    ax2 = ax.twinx()
    l2 = ax2.plot(ts / 1e6, tr, '-', color='C3', alpha=0.7,
                  label='training reward (stochastic)')[0]
    ax2.set_ylabel('training ep_rew_mean', color='C3')
    ax2.tick_params(axis='y', labelcolor='C3')
    ax2.set_ylim(250, 470)
    ax.legend(handles=[l1, l2], loc='lower right', fontsize=8)

fig.suptitle('Training reward keeps rising; deterministic eval plateaus after ~4M '
             '(de-noising, not learning)', fontsize=11)
fig.tight_layout()
out = os.path.join(os.path.dirname(HERE), '..', 'train_vs_eval_curves.png')
out = os.path.abspath(out)
fig.savefig(out, dpi=110)
print(f"saved -> {out}")
