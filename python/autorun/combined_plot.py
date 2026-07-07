"""Final combined figure for the compute-vs-decay + resume study.
Left: saturation curve (final 120-track paired eval vs compute) — the Q2 answer.
Right: eval-vs-step trajectories (incl. the seed2->resume hold-low continuation).
Reads eval_curve_*.npz (trajectories) and parses ab_*.log (A/B means)."""
import os, re, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def ab_means(logname):
    """Return (A_mean, B_mean) from a paired_ab log."""
    txt = open(os.path.join(HERE, "logs", logname)).read()
    a = float(re.search(r"A=.*?mean=([0-9.]+)", txt).group(1))
    b = float(re.search(r"B=.*?mean=([0-9.]+)", txt).group(1))
    return a, b


def curve(run):
    d = np.load(os.path.join(HERE, f"eval_curve_{run}.npz"))
    return d["steps"] / 1e6, d["scores"].mean(axis=1)


# --- A/B means (120 pinned tracks, vs champion B=1409) ---
dec2m_m = ab_means("ab_dec2m.log")[0]
dec4m_m = ab_means("ab_dec4m.log")[0]
base16_m, champ_m = ab_means("ab_base16.log")        # B = champion (8M)
resume_m = ab_means("ab_resume_vs_champ.log")[0]
seed2_8m = ab_means("ab_resume_vs_seed2.log")[1]     # B = seed2_final (8M)

fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5.5))

# ---- Left: saturation curve ----
xs = [2, 4, 8, 16]
ys = [dec2m_m, dec4m_m, champ_m, base16_m]
axL.plot(xs, ys, 'o-', color='C0', lw=2, label='normal decay (decay matched to run length)')
for x, y in zip(xs, ys):
    axL.annotate(f"{y:.0f}", (x, y), textcoords="offset points", xytext=(0, 8), ha='center', fontsize=9)
axL.plot([12], [resume_m], 'X', color='C3', ms=13,
         label=f'seed2 +4M resume @ const-low LR/ent ({resume_m:.0f})')
axL.annotate(f"{resume_m:.0f}", (12, resume_m), textcoords="offset points", xytext=(0, -16), ha='center',
             fontsize=9, color='C3')
axL.axhline(champ_m, color='gray', ls='--', lw=1, label=f'8M champion ceiling ({champ_m:.0f})')
axL.set_xlabel('training compute (M steps)'); axL.set_ylabel('deterministic eval (120 pinned tracks)')
axL.set_title('Eval vs compute: saturates at ~8M\n(shorter compressed-decay falls short; >8M & resume add nothing)')
axL.set_ylim(1150, 1480); axL.legend(fontsize=8, loc='lower right')

# ---- Right: eval-vs-step trajectories ----
for run, lab, col in [('dec2m', 'dec2m (2M)', 'C2'), ('dec4m', 'dec4m (4M)', 'C1'),
                      ('seed2', 'seed2 (8M)', 'C0'), ('base16_a', 'base16 (16M)', 'C4')]:
    s, e = curve(run)
    axR.plot(s, e, 'o-', ms=3, color=col, label=lab, alpha=0.85)
# seed2 -> resume continuation (8M..12M), constant-low.
sr, er = curve('seed2_resume')
axR.plot(sr, er, 's-', ms=3, color='C3', label='seed2 resume 8→12M (const-low)')
axR.axhline(champ_m, color='gray', ls='--', lw=1)
axR.set_xlabel('training steps (M)'); axR.set_ylabel('deterministic eval (40 pinned tracks)')
axR.set_title('Eval-vs-step trajectories (each run\'s decay compressed into its length)')
axR.set_ylim(600, 1600); axR.legend(fontsize=8, loc='lower right')

fig.suptitle('Compute vs decay: ~8M is the knee; decay-compression and post-hoc resume both fail to beat it',
             fontsize=12)
fig.tight_layout()
out = os.path.abspath(os.path.join(ROOT, "..", "compute_vs_decay.png"))
fig.savefig(out, dpi=110)
print("means: dec2m %.0f dec4m %.0f champ8M %.0f seed2_8M %.0f base16_16M %.0f resume12M %.0f"
      % (dec2m_m, dec4m_m, champ_m, seed2_8m, base16_m, resume_m))
print(f"saved -> {out}")
