"""Multi-scenario auto-tuner.

Reads trace_js_multi.json (produced by measure_multi.html) which contains
3 JS reference traces:
    cruise_flat — friction × motor balance (steady-state forward velocity)
    climb_ramp  — motor torque, slip behavior on inclines
    bump_coast  — suspension freq/damp behavior

For each candidate parameter set, runs all 3 scenarios in Python with the
overridden physics and scores them. Each scenario's score is normalized
by its JS-baseline magnitude so they contribute roughly equally regardless
of trace length or quantity scale.

Multi-start: 8 diverse warm starts to avoid local minima.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from constants import SCALE, MOTOR_SPEED
from car import Car
from measure import build_world_with_terrain, record, step


# ---------------------------------------------------------------------------
# JS reference loading
# ---------------------------------------------------------------------------
def load_js_multi(path: str) -> Dict[str, Dict]:
    with open(path) as f:
        data = json.load(f)
    return {s["name"]: s for s in data["scenarios"]}


# ---------------------------------------------------------------------------
# Per-parameter-set scenario runner. Like measure.py's run_trace, but takes
# the scenario metadata from the JS reference so terrain etc. match exactly.
# ---------------------------------------------------------------------------
# Anti-flip throttle controller — must match measure_multi.html /
# measure_multi.py line-for-line.
#   release when:  chassis_angle < ANGLE_PANIC  OR  chassis_omega < OMEGA_PANIC
#   resume  when:  chassis_angle > ANGLE_RESUME AND chassis_omega > -0.5
ANGLE_PANIC  = -0.4    # rad, ~-23°
ANGLE_RESUME = -0.15   # rad, ~-9°
OMEGA_PANIC  = -2.0    # rad/s


def _normalize_angle(a: float) -> float:
    while a > math.pi:  a -= 2 * math.pi
    while a < -math.pi: a += 2 * math.pi
    return a


def _apply_motor_forward(car: Car, motor_rear: float, motor_front: float, was_off: bool) -> None:
    """Equivalent of car.motor_on(forward=True) but reading torques from args
    instead of constants. Skips the rotation-torque kick on re-engagement
    (subtle but matches JS — torque only applied on first engage)."""
    car.wheels[0].set_motor(-MOTOR_SPEED, motor_rear)
    car.wheels[1].set_motor(-MOTOR_SPEED, motor_front)
    if was_off:
        # JS only applies the chassis rotation torque on the *initial* motorOn(true)
        # call, not on each re-engagement. Mirror that.
        pass


def run_scenario_with_params(scenario: Dict,
                             motor_rear: float, motor_front: float,
                             wheel_friction: float, susp_freq: float, susp_damp: float,
                             chassis_ang_damp: float, chassis_lin_damp: float,
                             wheel_ang_damp_extra: float) -> List[Dict]:
    """Run one scenario in Python with the given overridden physics. Uses the
    anti-flip throttle controller (hysteresis on chassis angle) to emulate a
    real player, so traces have useful information past the wheelie-flip
    point instead of flatlining."""
    world, _ = build_world_with_terrain(scenario["terrain"])
    car = Car(scenario["spawn_x"], scenario["spawn_y"], world)

    # Override physics parameters on the live Box2D objects.
    car.chassis_body.angularDamping = chassis_ang_damp
    car.chassis_body.linearDamping = chassis_lin_damp
    for wheel in car.wheels:
        for fixture in wheel.body.fixtures:
            fixture.friction = wheel_friction
        wheel.body.angularDamping = 1.8 + wheel_ang_damp_extra
        wheel.wheel_joint.springFrequencyHz = susp_freq
        wheel.wheel_joint.springDampingRatio = susp_damp

    trace = [record(car, 0)]
    for i in range(1, scenario["settle_ticks"] + 1):
        step(world)
        trace.append(record(car, i))

    # Initial motor engagement (matches JS Car.motorOn: -MOTOR_SPEED + the
    # one-time -rotation_torque kick to start a wheelie).
    car.wheels[0].set_motor(-MOTOR_SPEED, motor_rear)
    car.wheels[1].set_motor(-MOTOR_SPEED, motor_front)
    car.chassis_body.ApplyTorque(-2.0, True)
    throttle_on = True

    for i in range(1, scenario["throttle_ticks"] + 1):
        a = _normalize_angle(car.chassis_body.angle)
        omega = car.chassis_body.angularVelocity
        if throttle_on and (a < ANGLE_PANIC or omega < OMEGA_PANIC):
            for w in car.wheels:
                w.disable_motor()
            throttle_on = False
        elif (not throttle_on) and a > ANGLE_RESUME and omega > -0.5:
            car.wheels[0].set_motor(-MOTOR_SPEED, motor_rear)
            car.wheels[1].set_motor(-MOTOR_SPEED, motor_front)
            throttle_on = True
        step(world)
        rec = record(car, scenario["settle_ticks"] + i)
        rec["throttle"] = 1 if throttle_on else 0
        trace.append(rec)

    return trace


# ---------------------------------------------------------------------------
# Per-scenario score — same shape as tune.py but with weights chosen per
# scenario to emphasize the physics aspect that scenario was designed to
# expose.
# ---------------------------------------------------------------------------
def _path_length(trace: List[Dict], key: str, n: int) -> float:
    return sum(abs(trace[t + 1][key] - trace[t][key]) for t in range(n - 1))


def _wheel_local_y(trace: List[Dict], wheel_prefix: str) -> List[float]:
    out = []
    for r in trace:
        ca = r["cangle"]
        dx = r[wheel_prefix + "x"] - r["cx"]
        dy = r[wheel_prefix + "y"] - r["cy"]
        out.append(dx * math.sin(-ca) + dy * math.cos(-ca))
    return out


def _local_path_length(trace: List[Dict], wheel_prefix: str, n: int) -> float:
    seq = _wheel_local_y(trace, wheel_prefix)[:n]
    return sum(abs(seq[t + 1] - seq[t]) for t in range(n - 1))


# Per-scenario weight presets. Each scenario emphasizes what it isolates.
SCENARIO_WEIGHTS = {
    "cruise_flat": {
        # Cruise is mostly about cx and cvx — the steady-state forward
        # velocity is what reveals friction × motor balance.
        "position": {"cx": 3.0, "cy": 1.0, "cangle": 5.0,
                     "cvx": 30.0, "cvy": 3.0, "comega": 3.0,
                     "w0x": 1.0, "w0y": 1.0, "w1x": 1.0, "w1y": 1.0,
                     "hx": 1.0, "hy": 1.0, "tx": 1.0, "ty": 1.0,
                     "w0a": 0.2, "w1a": 0.2},
        "path": {"cy": 1.0, "cangle": 3.0},
        "local_path": {"w0_local_y": 1.0, "w1_local_y": 1.0},
    },
    "climb_ramp": {
        # Climbing — chassis x progression and tilt are the dominant signals.
        # Slip behavior shows up as cvx mismatch.
        "position": {"cx": 5.0, "cy": 3.0, "cangle": 30.0,
                     "cvx": 20.0, "cvy": 10.0, "comega": 5.0,
                     "w0x": 2.0, "w0y": 3.0, "w1x": 2.0, "w1y": 3.0,
                     "hx": 1.0, "hy": 3.0, "tx": 1.0, "ty": 3.0,
                     "w0a": 0.5, "w1a": 0.5},
        "path": {"cy": 2.0, "cangle": 15.0},
        "local_path": {"w0_local_y": 2.0, "w1_local_y": 5.0},
    },
    "bump_coast": {
        # Bump impact — suspension behavior is everything.
        # Position-RMS doesn't catch ringing, so path-length dominates.
        "position": {"cx": 1.0, "cy": 10.0, "cangle": 50.0,
                     "cvx": 5.0, "cvy": 30.0, "comega": 15.0,
                     "w0x": 1.0, "w0y": 8.0, "w1x": 1.0, "w1y": 8.0,
                     "hx": 1.0, "hy": 3.0, "tx": 1.0, "ty": 3.0,
                     "w0a": 0.5, "w1a": 0.5},
        "path": {"cy": 5.0, "cangle": 30.0, "w0y": 5.0, "w1y": 5.0},
        "local_path": {"w0_local_y": 10.0, "w1_local_y": 25.0},
    },
}


def scenario_score(py_trace: List[Dict], js_trace: List[Dict], weights: Dict) -> float:
    n = min(len(py_trace), len(js_trace))
    s = 0.0
    for k, w in weights["position"].items():
        sq = sum((py_trace[t][k] - js_trace[t][k]) ** 2 for t in range(n))
        s += w * math.sqrt(sq / n)
    for k, w in weights["path"].items():
        s += w * abs(_path_length(py_trace, k, n) - _path_length(js_trace, k, n))
    for label, w in weights["local_path"].items():
        prefix = "w0" if label.startswith("w0") else "w1"
        s += w * abs(_local_path_length(py_trace, prefix, n)
                     - _local_path_length(js_trace, prefix, n))
    return s


# ---------------------------------------------------------------------------
# Multi-scenario score: sum of per-scenario scores. Each scenario is
# pre-normalized by its JS-baseline score so they contribute roughly
# equally regardless of trace length / quantity scale.
# ---------------------------------------------------------------------------
def total_score(params: tuple, js_scenarios: Dict[str, Dict],
                normalize: Dict[str, float] | None = None) -> Tuple[float, Dict[str, float]]:
    per_scenario = {}
    total = 0.0
    for name, js_s in js_scenarios.items():
        try:
            py_trace = run_scenario_with_params(js_s, *params)
        except Exception as e:
            return 1e9, {name: 1e9 for name in js_scenarios}
        s = scenario_score(py_trace, js_s["trace"], SCENARIO_WEIGHTS[name])
        per_scenario[name] = s
        if normalize and name in normalize:
            total += s / normalize[name]
        else:
            total += s
    return total, per_scenario


# ---------------------------------------------------------------------------
# Optimization wrapper
# ---------------------------------------------------------------------------
PARAM_NAMES = ["motor_rear", "motor_front", "wheel_friction",
               "susp_freq", "susp_damp", "chassis_ang_damp",
               "chassis_lin_damp", "wheel_ang_damp_extra"]
JS_BASELINE = [700.0, 350.0, 1.5,  70.0, 25.0, 0.1, 0.001, 0.001]
LOWER       = [50.0,  25.0,  0.05, 5.0,  0.5,  0.01, 0.001, 0.001]
UPPER       = [1500., 750.,  3.0,  200., 100., 5.0,  3.0,   5.0]


def to_normalized(physical):
    lo = np.array(LOWER); hi = np.array(UPPER)
    return np.log(np.array(physical) / lo) / np.log(hi / lo)


def from_normalized(x_normalized):
    lo = np.array(LOWER); hi = np.array(UPPER)
    return lo * (hi / lo) ** np.clip(x_normalized, 0.0, 1.0)


# Diverse warm starts. Each picks a different region of parameter space so
# Nelder-Mead's local search has a chance of finding a global-ish optimum.
WARM_STARTS = [
    ("JS exact + tiny cap",          [700,  350,  1.0,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("JS exact, JS friction (1.5)",  [700,  350,  1.5,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("low friction / high motor",    [1000, 500,  0.5,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("high friction / low motor",    [500,  250,  2.0,  70.0, 25.0, 0.10, 0.05, 0.10]),
    ("soft suspension",              [700,  350,  1.0,  30.0,  8.0, 0.10, 0.05, 0.10]),
    ("stiff suspension",             [700,  350,  1.0, 120.0, 50.0, 0.10, 0.05, 0.10]),
    ("high damping",                 [800,  400,  0.75, 50.0, 15.0, 0.50, 0.30, 1.00]),
    ("balanced mid",                 [800,  400,  1.2,  60.0, 20.0, 0.20, 0.15, 0.30]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--maxiter", type=int, default=300)
    parser.add_argument("--starts", type=int, default=len(WARM_STARTS),
                        help="how many warm starts to run (default: all)")
    args = parser.parse_args()

    js_path = os.path.join(ROOT, "trace_js_multi.json")
    if not os.path.exists(js_path):
        sys.exit(f"missing {js_path} — open measure_multi.html in a browser and download it first")
    js_scenarios = load_js_multi(js_path)
    print(f"loaded {len(js_scenarios)} JS scenarios from {js_path}")
    for name, s in js_scenarios.items():
        print(f"  {name:<14} {len(s['trace'])} ticks")

    # Baseline per-scenario score with JS-exact params — used to normalize.
    print("\n[normalizing] computing JS-baseline score per scenario...")
    _, normalize = total_score(JS_BASELINE, js_scenarios)
    for name, s in normalize.items():
        print(f"  {name:<14} baseline = {s:.2f}")
    print(f"  total = {sum(normalize.values()):.2f}")

    def objective(x_norm: np.ndarray) -> float:
        params = from_normalized(x_norm)
        total, _ = total_score(tuple(params), js_scenarios, normalize=normalize)
        return total

    # Show normalized JS-baseline as the reference
    print(f"\nJS baseline normalized total: {len(normalize):.2f}  (= 1.0 per scenario × {len(normalize)} scenarios)")

    # Run all starts
    results = []
    for label, warm in WARM_STARTS[: args.starts]:
        x0 = to_normalized(warm)
        t0 = time.time()
        iters = [0]
        def cb(xk):
            iters[0] += 1
        res = minimize(objective, x0, method="Nelder-Mead", callback=cb,
                       options={"maxiter": args.maxiter, "xatol": 0.005, "fatol": 0.01, "adaptive": True})
        physical = from_normalized(res.x)
        total, per = total_score(tuple(physical), js_scenarios, normalize=normalize)
        elapsed = time.time() - t0
        print(f"\n[{label}]  iters={iters[0]}  time={elapsed:.1f}s  total={total:.3f}")
        print("  per-scenario: " + "  ".join(f"{n}={s:.3f}" for n, s in per.items()))
        print("  params: " + "  ".join(f"{n}={v:.2f}" for n, v in zip(PARAM_NAMES, physical)))
        results.append((total, label, physical, per))

    results.sort(key=lambda r: r[0])
    print("\n" + "=" * 78)
    print("RANKED RESULTS  (lower is better; 1.0 per scenario = matches JS baseline exactly)")
    print("=" * 78)
    for i, (total, label, _, per) in enumerate(results):
        per_str = "  ".join(f"{n}={s:.2f}" for n, s in per.items())
        print(f"  #{i+1:<2} total={total:>7.3f}  ({per_str})  {label}")

    best_total, best_label, best_params, best_per = results[0]
    print(f"\nBest start: '{best_label}', total normalized score = {best_total:.3f}")
    print("Per-scenario breakdown (1.0 = same as JS-exact baseline):")
    for name, s in best_per.items():
        ratio = s / normalize[name]
        print(f"  {name:<14} {s:>7.2f}  (= {ratio:.3f}x baseline)")
    print("\nBest parameters:")
    for n, v, js in zip(PARAM_NAMES, best_params, JS_BASELINE):
        print(f"  {n:<22} {v:>9.3f}   (JS={js}, ratio={v/js:.2f}x)")

    out_path = os.path.join(ROOT, "tuned_params.json")
    with open(out_path, "w") as f:
        json.dump({n: float(v) for n, v in zip(PARAM_NAMES, best_params)}, f, indent=2)
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
