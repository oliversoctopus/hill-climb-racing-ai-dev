"""Plot JS reference, JS-exact Python, and tuned Python all overlaid."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib.pyplot as plt
from tune import run_trace, JS_BASELINE
from compare import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

js = load("trace_js.json")
py_baseline = run_trace(*JS_BASELINE)
# tuned values from optimizer (8 params, with damping)
py_tuned = run_trace(827.78, 414.40, 0.77, 76.99, 32.26, 0.512, 0.393, 1.022)

n = min(len(js), len(py_baseline), len(py_tuned))
ticks = [r["tick"] for r in js[:n]]

fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True)
panels = [
    ("cx",     "chassis x (px)"),
    ("cy",     "chassis y (px)"),
    ("cangle", "chassis angle (rad)"),
    ("cvx",    "chassis vx (m/s)"),
    ("cvy",    "chassis vy (m/s)"),
    ("comega", "chassis omega (rad/s)"),
]
for ax, (key, label) in zip(axes.flat, panels):
    ax.plot(ticks, [r[key] for r in js[:n]],          label="JS reference", color="#28a", linewidth=2)
    ax.plot(ticks, [r[key] for r in py_baseline[:n]], label="Py (JS-exact params)", color="#e62", linewidth=1.2, linestyle=":")
    ax.plot(ticks, [r[key] for r in py_tuned[:n]],    label="Py (auto-tuned)", color="#2a2", linewidth=1.5, linestyle="--")
    ax.set_title(label)
    ax.axvline(30, color="gray", linestyle=":", alpha=0.5)
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8)
axes[-1, 0].set_xlabel("tick"); axes[-1, 1].set_xlabel("tick")
plt.suptitle("JS reference vs Python (JS params) vs Python (auto-tuned)", fontsize=11)
plt.tight_layout()
out = os.path.join(ROOT, "trace_tuned.png")
plt.savefig(out, dpi=110)
print(f"saved {out}")
