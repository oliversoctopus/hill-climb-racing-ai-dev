"""Sweep suspension freq AND damp together — search for the configuration that
puts the front wheel into a calm equilibrium relative to the chassis."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from tune import run_trace, score
from compare import load

js = load("trace_js.json")
n = len(js)


def front_local_y_path(trace, start=30):
    s = 0.0; prev = None
    for r in trace[start:n]:
        ca = r["cangle"]
        dx = r["w1x"] - r["cx"]; dy = r["w1y"] - r["cy"]
        cosa = math.cos(-ca); sina = math.sin(-ca)
        ly = dx * sina + dy * cosa
        if prev is not None: s += abs(ly - prev)
        prev = ly
    return s


def back_local_y_path(trace, start=30):
    s = 0.0; prev = None
    for r in trace[start:n]:
        ca = r["cangle"]
        dx = r["w0x"] - r["cx"]; dy = r["w0y"] - r["cy"]
        cosa = math.cos(-ca); sina = math.sin(-ca)
        ly = dx * sina + dy * cosa
        if prev is not None: s += abs(ly - prev)
        prev = ly
    return s


js_back_local  = back_local_y_path(js)
js_front_local = front_local_y_path(js)
print(f"JS target:  back-local-y={js_back_local:.2f}   front-local-y={js_front_local:.2f}\n")

# baseline: tuned values
print(f"{'freq':>5} {'damp':>5}  {'back-local-y':>13}  {'front-local-y':>14}  {'score':>7}")
print("-" * 56)
for freq in [10, 25, 50, 76, 100]:
    for damp in [1, 5, 25, 39, 80]:
        t = run_trace(834, 419, 0.75, freq, damp, 0.50, 0.37, 0.99)
        b = back_local_y_path(t)
        f = front_local_y_path(t)
        s = score(t, js)
        print(f"{freq:>5} {damp:>5}  {b:>13.2f}  {f:>14.2f}  {s:>7.1f}")
