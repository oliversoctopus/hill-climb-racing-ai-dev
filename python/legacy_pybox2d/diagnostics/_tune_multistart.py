"""Multi-start tuner — runs scipy.optimize.minimize from several different
warm starts and reports the best. Nelder-Mead is a local optimizer in 8 dims;
without multiple starts we can't tell if we landed in a global minimum.
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import numpy as np
from scipy.optimize import minimize
from tune import (PARAM_NAMES, JS_BASELINE, LOWER, UPPER, objective,
                  to_normalized, from_normalized, run_trace, score)

# Load target trace
with open(os.path.join(ROOT, "trace_js.json")) as f:
    data = json.load(f)
target = data["trace"] if isinstance(data, dict) else data

# Diverse warm starts spanning the realistic parameter space.
# Format: [motor_rear, motor_front, wheel_friction, susp_freq, susp_damp,
#          chassis_ang_damp, chassis_lin_damp, wheel_ang_damp_extra]
STARTS = [
    ("JS baseline + small cap",      [700,  350,  1.0,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("low friction / high motor",    [1000, 500,  0.5,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("high friction / low motor",    [500,  250,  2.0,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("soft suspension",              [700,  350,  1.0,  30.0,  8.0, 0.10, 0.05, 0.10]),
    ("stiff suspension",             [700,  350,  1.0, 120.0, 50.0, 0.10, 0.05, 0.10]),
    ("high damping (old-tune-ish)",  [800,  400,  0.75, 50.0, 15.0, 0.50, 0.30, 1.00]),
    ("low damping",                  [700,  350,  1.0,  70.0, 25.0, 0.02, 0.005, 0.01]),
    ("balanced mid",                 [800,  400,  1.2,  60.0, 20.0, 0.20, 0.15, 0.30]),
]


def run_one(label, warm):
    x0 = to_normalized(warm)
    t0 = time.time()
    last_score = [None]
    iters = [0]
    def cb(xk):
        iters[0] += 1
        last_score[0] = objective(xk, target)
    res = minimize(objective, x0, args=(target,), method="Nelder-Mead", callback=cb,
                   options={"maxiter": 350, "xatol": 0.005, "fatol": 0.5, "adaptive": True})
    physical = from_normalized(res.x)
    print(f"\n[{label}]  iters={iters[0]}  time={time.time()-t0:.1f}s  score={res.fun:.2f}")
    print("  " + "  ".join(f"{n}={v:.2f}" for n, v in zip(PARAM_NAMES, physical)))
    return res.fun, physical


# JS baseline score for reference
js_score = score(run_trace(*JS_BASELINE), target)
print(f"JS baseline score (no optimization):  {js_score:.2f}\n")

results = []
for label, warm in STARTS:
    s, p = run_one(label, warm)
    results.append((s, label, p))

results.sort(key=lambda r: r[0])
print("\n" + "=" * 78)
print("RANKED RESULTS")
print("=" * 78)
print(f"{'rank':>4} {'score':>9}  start")
for i, (s, label, _) in enumerate(results):
    print(f"  #{i+1:<2} {s:>9.2f}  {label}")

print("\nBest params:")
best_score, best_label, best_params = results[0]
for n, v, js in zip(PARAM_NAMES, best_params, JS_BASELINE):
    print(f"  {n:<22} {v:>9.3f}  (JS={js}, ratio={v/js:.2f}x)")
print(f"\nbest from start: '{best_label}', score={best_score:.2f}")

# Save best
with open(os.path.join(ROOT, "tuned_params.json"), "w") as f:
    json.dump({n: float(v) for n, v in zip(PARAM_NAMES, best_params)}, f, indent=2)
print("saved tuned_params.json")

# Save best trace for the comparison plot
best_trace = run_trace(*best_params)
with open(os.path.join(ROOT, "trace_tuned.json"), "w") as f:
    json.dump(best_trace, f)
print("saved trace_tuned.json")
