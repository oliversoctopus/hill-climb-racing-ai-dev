"""Train-reward (from TB) vs deterministic eval (from eval_curve npz) for the
16M run base16_a. Single panel, twin y-axes; vertical line at 8M (where the
deployed champion stopped) so you can see whether 8M->16M bought any eval."""
import os, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUN = "base16_a"

# Training reward from TensorBoard.
tbdir = sorted(glob.glob(os.path.join(ROOT, "tb", f"{RUN}_*")))[0]
acc = EventAccumulator(tbdir, size_guidance={"scalars": 0}); acc.Reload()
ev = acc.Scalars("rollout/ep_rew_mean")
ts = np.array([e.step for e in ev]) / 1e6
tr = np.array([e.value for e in ev])

# Deterministic eval curve.
d = np.load(os.path.join(HERE, f"eval_curve_{RUN}.npz"))
cs = d["steps"] / 1e6
ce = d["scores"].mean(axis=1)
se = d["scores"].std(axis=1) / np.sqrt(d["scores"].shape[1])

fig, ax = plt.subplots(figsize=(8, 5))
l1 = ax.plot(cs, ce, 'o-', color='C0', label='deterministic eval (score)')[0]
ax.fill_between(cs, ce - se, ce + se, color='C0', alpha=0.15)
ax.axhline(1411, color='C2', ls='--', lw=1, label='8M champion eval (1411)')
ax.set_ylabel('deterministic eval score', color='C0'); ax.tick_params(axis='y', labelcolor='C0')
ax.set_ylim(900, 1550); ax.set_xlabel('training steps (millions)')
ax.axvline(8.0, color='gray', ls=':', lw=1); ax.text(8.1, 930, '8M (champion stop)', color='gray', fontsize=8)

ax2 = ax.twinx()
l2 = ax2.plot(ts, tr, '-', color='C3', alpha=0.6, label='training reward (stochastic)')[0]
ax2.set_ylabel('training ep_rew_mean', color='C3'); ax2.tick_params(axis='y', labelcolor='C3')

ax.legend(handles=[l1, l2, ax.lines[1]], loc='lower right', fontsize=8)
ax.set_title('base16_a (16M): training reward climbs to 16M; deterministic eval flat after ~6-8M')
fig.tight_layout()
out = os.path.join(ROOT, "..", "train_vs_eval_base16.png"); out = os.path.abspath(out)
fig.savefig(out, dpi=110)
# Also print the aligned table + correlation.
trm = np.array([tr[int(np.argmin(np.abs(ts - s)))] for s in cs])
print(f"{'step(M)':>8}{'train':>8}{'eval':>8}")
for s, t, e in zip(cs, trm, ce):
    print(f"{s:>8.1f}{t:>8.0f}{e:>8.0f}")
print(f"Pearson r (all): {np.corrcoef(trm, ce)[0,1]:+.2f}")
h = cs >= 8.0
print(f"Pearson r (>=8M, {int(h.sum())} pts): {np.corrcoef(trm[h], ce[h])[0,1]:+.2f}")
print(f"eval 8M->16M: {ce[h][0]:.0f} -> {ce[-1]:.0f}")
print(f"saved -> {out}")
