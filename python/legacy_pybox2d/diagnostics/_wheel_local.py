"""How much is each wheel moving *relative to the chassis* (suspension travel)?
World-frame motion has been a poor proxy for what's visible: a wheel can sit
still in world coords while the chassis moves around it. Compute the wheel
position in chassis-local coords each tick and look at how that varies.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from compare import load
import matplotlib.pyplot as plt

js = load("trace_js.json")
py = load("trace_py.json")
n = min(len(js), len(py))


def wheel_local(trace, wheel_prefix):
    """For each tick, transform wheel_world into chassis-local frame."""
    out_x, out_y = [], []
    for r in trace[:n]:
        cx, cy, ca = r["cx"], r["cy"], r["cangle"]
        wx, wy = r[wheel_prefix + "x"], r[wheel_prefix + "y"]
        # rotate (wx-cx, wy-cy) by -ca to get chassis-local
        dx, dy = wx - cx, wy - cy
        cosa, sina = math.cos(-ca), math.sin(-ca)
        lx = dx * cosa - dy * sina
        ly = dx * sina + dy * cosa
        out_x.append(lx)
        out_y.append(ly)
    return out_x, out_y


js_w0x, js_w0y = wheel_local(js, "w0")
js_w1x, js_w1y = wheel_local(js, "w1")
py_w0x, py_w0y = wheel_local(py, "w0")
py_w1x, py_w1y = wheel_local(py, "w1")


def path(seq, start=30):
    return sum(abs(seq[t + 1] - seq[t]) for t in range(start, n - 1))


def std(seq, start=30):
    vals = seq[start:n]
    m = sum(vals) / len(vals)
    return (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5


print(f"{'quantity':<32} {'JS path':>9} {'Py path':>9} {'JS stdev':>9} {'Py stdev':>9}")
print("-" * 70)
for label, jseq, pseq in [
    ("back-wheel local x (fore/aft)",  js_w0x, py_w0x),
    ("back-wheel local y (up/down)",   js_w0y, py_w0y),
    ("front-wheel local x (fore/aft)", js_w1x, py_w1x),
    ("front-wheel local y (up/down)",  js_w1y, py_w1y),
]:
    print(f"{label:<32} {path(jseq):>9.2f} {path(pseq):>9.2f} {std(jseq):>9.3f} {std(pseq):>9.3f}")

# Plot
fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
ticks = [r["tick"] for r in js[:n]]
for ax, label, jseq, pseq in zip(
    axes.flat,
    ["back-wheel local x", "back-wheel local y", "front-wheel local x", "front-wheel local y"],
    [js_w0x, js_w0y, js_w1x, js_w1y],
    [py_w0x, py_w0y, py_w1x, py_w1y],
):
    ax.plot(ticks, jseq, label="JS", color="#28a", linewidth=1.5)
    ax.plot(ticks, pseq, label="Py", color="#2a2", linewidth=1.5, linestyle="--")
    ax.set_title(label + " — wheel position in chassis-local frame (m)")
    ax.grid(alpha=0.3); ax.legend(loc="best", fontsize=8)
    ax.axvline(30, color="gray", linestyle=":", alpha=0.5)
axes[-1, 0].set_xlabel("tick"); axes[-1, 1].set_xlabel("tick")
plt.suptitle("Wheel motion *relative to chassis* — this is what the user actually sees")
plt.tight_layout()
out = os.path.join(ROOT, "wheel_local.png")
plt.savefig(out, dpi=110)
print(f"\nsaved {out}")
