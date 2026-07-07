import re, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))

def train_series(run):
    txt = open(os.path.join(HERE, 'logs', f'{run}_train.log')).read()
    rews = [float(x) for x in re.findall(r"ep_rew_mean\s*\|\s*([0-9.eE+-]+)", txt)]
    steps = [int(x) for x in re.findall(r"total_timesteps\s*\|\s*([0-9]+)", txt)]
    n = min(len(rews), len(steps))
    return np.array(steps[:n]), np.array(rews[:n])

def curve(run):
    d = np.load(os.path.join(HERE, f'eval_curve_{run}.npz'))
    return d['steps'], d['scores'].mean(axis=1)

for run in ['seed2', 'fs8']:
    ts, tr = train_series(run)
    cs, ce = curve(run)
    trm = np.array([tr[int(np.argmin(np.abs(ts - s)))] for s in cs])
    print(f"\n=== {run} ===")
    print(f"{'step':>9} {'train_rew':>9} {'det_eval':>8}")
    for s, t, e in zip(cs, trm, ce):
        print(f"{s:>9} {t:>9.0f} {e:>8.0f}")
    r_all = float(np.corrcoef(trm, ce)[0, 1])
    print(f"  Pearson r (all 10 pts): {r_all:+.2f}")
    h = cs >= 4_000_000
    print(f"  Pearson r (>=4M, {int(h.sum())} pts): "
          f"{float(np.corrcoef(trm[h], ce[h])[0, 1]):+.2f}")
    print(f"  train_rew {trm[0]:.0f}->{trm[-1]:.0f} (+{trm[-1]-trm[0]:.0f}); "
          f"det_eval {ce[0]:.0f}->{ce[-1]:.0f} (+{ce[-1]-ce[0]:.0f})")
    print(f"  back-half (>=4M) det_eval: mean {ce[h].mean():.0f}, "
          f"range {ce[h].min():.0f}-{ce[h].max():.0f}")
