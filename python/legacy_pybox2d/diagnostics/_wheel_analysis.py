"""Look at wheel y and wheel angular position over time — does Python bounce more?"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from compare import load
import matplotlib.pyplot as plt

js = load("trace_js.json")
py = load("trace_py.json")
n = min(len(js), len(py))

# Frame-to-frame oscillation magnitude — sum of |y(t+1) - y(t)| over throttle phase
def path_length(trace, key, start, end):
    return sum(abs(trace[t+1][key] - trace[t][key]) for t in range(start, end))

print("frame-to-frame motion during throttle phase (ticks 30-150):")
for key, label in [("w0y", "back-wheel y"), ("w1y", "front-wheel y"),
                   ("cy",  "chassis   y"),  ("cangle", "chassis angle (×100)")]:
    j = path_length(js, key, 30, n - 1)
    p = path_length(py, key, 30, n - 1)
    if "angle" in label: j *= 100; p *= 100
    print(f"  {label:<25} JS={j:7.1f}  Py={p:7.1f}  Py/JS={p/j if j > 0 else float('nan'):.2f}x")

# Effective grip: 1 - (wheel_rotation_distance) vs (actual translation)
def slip(trace, key_rot, key_x, wheel_radius=17/30):
    rot = trace[-1][key_rot] - trace[30][key_rot]
    dx = (trace[-1][key_x] - trace[30][key_x]) / 30  # m
    expected = rot * wheel_radius
    return 1 - dx / expected if expected != 0 else 0

print("\nslip ratio (wheel rotation expected vs actual translation):")
print(f"  JS back wheel:  {slip(js, 'w0a', 'w0x')*100:.1f}%")
print(f"  Py back wheel:  {slip(py, 'w0a', 'w0x')*100:.1f}%")
print(f"  JS front wheel: {slip(js, 'w1a', 'w1x')*100:.1f}%")
print(f"  Py front wheel: {slip(py, 'w1a', 'w1x')*100:.1f}%")

# Plot the wheel y over time
fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
ticks = [r["tick"] for r in js[:n]]
for ax, key, label in zip(axes.flat, ["w0y", "w1y", "w0a", "w1a"],
                          ["back-wheel y (px)", "front-wheel y (px)",
                           "back-wheel rotation (rad, cumulative)", "front-wheel rotation (rad, cumulative)"]):
    ax.plot(ticks, [r[key] for r in js[:n]], label="JS", color="#28a", linewidth=1.5)
    ax.plot(ticks, [r[key] for r in py[:n]], label="Py", color="#2a2", linewidth=1.5, linestyle="--")
    ax.set_title(label); ax.grid(alpha=0.3); ax.legend(loc="best", fontsize=8)
    ax.axvline(30, color="gray", linestyle=":", alpha=0.5)
axes[-1, 0].set_xlabel("tick"); axes[-1, 1].set_xlabel("tick")
plt.suptitle("Wheel detail: JS vs current tuned Python (hilly terrain)")
plt.tight_layout()
out = os.path.join(ROOT, "wheel_diff.png")
plt.savefig(out, dpi=110)
print(f"\nsaved {out}")
