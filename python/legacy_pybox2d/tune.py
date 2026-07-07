"""Auto-tune Python physics parameters to match the JS reference trace.

Loads ``trace_js.json`` (produced by measure.html) as the target. Runs
``measure.py``'s scenario in-process with overrideable parameters, scores
the divergence, and uses Nelder-Mead to minimize.

Parameters tuned:
  1. motor_torque_rear   (JS default 700)
  2. motor_torque_front  (JS default 350)
  3. wheel_friction      (JS default 1.5 — but Box2D 2.0 caps closer to 1.0)
  4. susp_freq           (wheel suspension distance-joint frequencyHz, JS=70)
  5. susp_damp           (wheel suspension distance-joint dampingRatio, JS=25)
  6. chassis_ang_damp    (JS default 0.1)

Other parameters (densities, restitution, joint anchors, chassis polygon,
gravity, ground friction) match JS exactly and aren't touched here.

Usage:
    python tune.py                    # run optimizer, write tuned_params.json + tune_diff.png
    python tune.py --eval 700 350 1.5 70 25 0.1   # just evaluate one parameter set
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import List, Dict, Tuple

import numpy as np
from scipy.optimize import minimize

from Box2D import (
    b2World, b2Vec2, b2BodyDef, b2_staticBody, b2FixtureDef, b2Filter, b2EdgeShape,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from constants import (
    SCALE, DIRT_CATEGORY, DIRT_MASK, GRASS_CATEGORY, GRASS_MASK,
    GRAVITY, PHYSICS_DT, VEL_ITERS, POS_ITERS, MOTOR_SPEED,
)
from car import Car
from world import HillClimbContactListener
from measure import (
    SPAWN_X_PX, SPAWN_Y_PX, SETTLE_TICKS, THROTTLE_TICKS,
    build_world_with_terrain, load_terrain_from_js_trace,
)

# Terrain loaded once at module import (re-loaded by main() if needed)
_TERRAIN = None


def get_terrain():
    global _TERRAIN
    if _TERRAIN is None:
        js_path = os.path.join(ROOT, "trace_js.json")
        _TERRAIN = load_terrain_from_js_trace(js_path)
    return _TERRAIN


def record(car, tick):
    cb = car.chassis_body
    cv = cb.linearVelocity
    return {
        "tick": tick,
        "cx": cb.position.x * SCALE, "cy": cb.position.y * SCALE,
        "cangle": cb.angle, "cvx": cv.x, "cvy": cv.y, "comega": cb.angularVelocity,
        "w0x": car.wheels[0].body.position.x * SCALE,
        "w0y": car.wheels[0].body.position.y * SCALE,
        "w0a": car.wheels[0].body.angle,
        "w1x": car.wheels[1].body.position.x * SCALE,
        "w1y": car.wheels[1].body.position.y * SCALE,
        "w1a": car.wheels[1].body.angle,
        "hx":  car.person.head.body.position.x * SCALE,
        "hy":  car.person.head.body.position.y * SCALE,
        "tx":  car.person.torso.body.position.x * SCALE,
        "ty":  car.person.torso.body.position.y * SCALE,
    }


def run_trace(motor_rear: float, motor_front: float,
              wheel_friction: float, susp_freq: float, susp_damp: float,
              chassis_ang_damp: float, chassis_lin_damp: float = 0.0,
              wheel_ang_damp_extra: float = 0.0) -> List[Dict]:
    """Build a fresh car with the given physics parameters, run the trace."""
    world, listener = build_world_with_terrain(get_terrain())
    car = Car(SPAWN_X_PX, SPAWN_Y_PX, world)

    # Apply parameter overrides directly on the Box2D objects.
    car.chassis_body.angularDamping = chassis_ang_damp
    car.chassis_body.linearDamping = chassis_lin_damp
    for wheel in car.wheels:
        # Friction is set on the fixture, not the body
        for fixture in wheel.body.fixtures:
            fixture.friction = wheel_friction
        wheel.body.angularDamping = 1.8 + wheel_ang_damp_extra
        # Suspension (b2WheelJoint) spring params are mutable post-construction
        wheel.wheel_joint.springFrequencyHz = susp_freq
        wheel.wheel_joint.springDampingRatio = susp_damp

    trace = [record(car, 0)]
    for i in range(1, SETTLE_TICKS + 1):
        world.Step(PHYSICS_DT, VEL_ITERS, POS_ITERS)
        world.ClearForces()
        trace.append(record(car, i))

    # Engage motor with the tuned torques (bypass Car.motor_on which reads
    # constants.MOTOR_TORQUE_*; call the wheels directly).
    car.wheels[0].set_motor(-MOTOR_SPEED, motor_rear)
    car.wheels[1].set_motor(-MOTOR_SPEED, motor_front)
    # JS Car.motorOn also applies -rotation_torque on engaging forward.
    car.chassis_body.ApplyTorque(-2.0, True)

    for i in range(1, THROTTLE_TICKS + 1):
        world.Step(PHYSICS_DT, VEL_ITERS, POS_ITERS)
        world.ClearForces()
        trace.append(record(car, SETTLE_TICKS + i))

    return trace


# ----------------------------------------------------------------------
# Divergence score
# ----------------------------------------------------------------------
# Position RMS — catches mean-position divergence
WEIGHTS = {
    "cx": 1.0, "cy": 5.0, "cangle": 50.0,
    "cvx": 5.0, "cvy": 10.0, "comega": 5.0,
    "hx": 1.0, "hy": 5.0, "tx": 1.0, "ty": 5.0,
    "w0x": 1.0, "w0y": 5.0, "w0a": 0.5,
    "w1x": 1.0, "w1y": 5.0, "w1a": 0.5,
}

# Path-length penalty — catches oscillation-amplitude divergence
# (sum of |x(t+1) - x(t)|, then absolute diff between trace and target).
# Position-RMS misses this: Python can have right-mean-position but bounce
# 30% more around it. The user could *see* this even though RMS was tiny.
PATH_WEIGHTS = {
    "cy": 3.0,
    "cangle": 20.0,
    "w0y": 3.0,
    "w1y": 3.0,
}

# Chassis-local-frame path length penalty — catches wheel-relative-to-chassis
# oscillation. This is what the user *sees* — a wheel bobbing inside the
# suspension while the chassis sits steady. World-frame paths miss it.
LOCAL_PATH_WEIGHTS = {
    "w0_local_y": 5.0,
    "w1_local_y": 15.0,   # front wheel oscillation diverges the most — penalize heaviest
}


def _path_length(trace, key, n):
    return sum(abs(trace[t + 1][key] - trace[t][key]) for t in range(n - 1))


def _wheel_local_y(trace, wheel_prefix):
    """List of wheel y in chassis-local frame, per tick."""
    out = []
    for r in trace:
        ca = r["cangle"]
        dx = r[wheel_prefix + "x"] - r["cx"]
        dy = r[wheel_prefix + "y"] - r["cy"]
        cosa = math.cos(-ca); sina = math.sin(-ca)
        out.append(dx * sina + dy * cosa)
    return out


def _local_path_length(trace, wheel_prefix, n):
    seq = _wheel_local_y(trace, wheel_prefix)[:n]
    return sum(abs(seq[t + 1] - seq[t]) for t in range(n - 1))


def score(trace: List[Dict], target: List[Dict]) -> float:
    n = min(len(trace), len(target))
    s = 0.0
    for k, w in WEIGHTS.items():
        sq = sum((trace[t][k] - target[t][k]) ** 2 for t in range(n))
        s += w * math.sqrt(sq / n)
    for k, w in PATH_WEIGHTS.items():
        s += w * abs(_path_length(trace, k, n) - _path_length(target, k, n))
    for label, w in LOCAL_PATH_WEIGHTS.items():
        wheel_prefix = "w0" if label.startswith("w0") else "w1"
        s += w * abs(_local_path_length(trace, wheel_prefix, n)
                     - _local_path_length(target, wheel_prefix, n))
    return s


# ----------------------------------------------------------------------
# Optimization
# ----------------------------------------------------------------------
PARAM_NAMES = ["motor_rear", "motor_front", "wheel_friction",
               "susp_freq", "susp_damp", "chassis_ang_damp",
               "chassis_lin_damp", "wheel_ang_damp_extra"]
JS_BASELINE  = [700.0, 350.0, 1.5,  70.0, 25.0, 0.1, 0.001, 0.001]
# Start the optimizer from a guess that already has some damping — Nelder-Mead
# never wanders far from its start in 8 dims, so giving it a useful prior matters.
# After the b2WheelJoint refactor JS values score 1652 (vs the old rim-joint
# baseline's 4106); the old tuned warm-start now actively hurts. Restart from
# JS values with a small wheel-friction cap (Box2D 2.3 honors friction > 1
# whereas Box2D.js effectively capped at ~1.0).
WARM_START   = [700.0, 350.0, 1.0,  70.0, 25.0, 0.1,  0.05,  0.1]
LOWER        = [50.0,  25.0,  0.05, 5.0,  0.5,  0.01, 0.001, 0.001]
UPPER        = [1500., 750.,  3.0,  200., 100., 5.0,  3.0,   5.0]


def objective(x_normalized: np.ndarray, target: List[Dict]) -> float:
    """Map normalized [0,1] params -> physical values, run trace, return score.

    We optimize in log-space-normalized coordinates so Nelder-Mead's simplex
    moves don't favor large-magnitude parameters.
    """
    lo = np.array(LOWER); hi = np.array(UPPER)
    physical = lo * (hi / lo) ** np.clip(x_normalized, 0.0, 1.0)  # geometric interpolation
    try:
        trace = run_trace(*physical)
        return score(trace, target)
    except Exception as e:
        print(f"  [trace error: {type(e).__name__} {e}]")
        return 1e9


def to_normalized(physical):
    lo = np.array(LOWER); hi = np.array(UPPER)
    return np.log(np.array(physical) / lo) / np.log(hi / lo)


def from_normalized(x_normalized):
    lo = np.array(LOWER); hi = np.array(UPPER)
    return lo * (hi / lo) ** np.clip(x_normalized, 0.0, 1.0)


# ----------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--eval", type=float, nargs=len(PARAM_NAMES), default=None,
                   help="just evaluate one parameter set, don't optimize")
    p.add_argument("--maxiter", type=int, default=400)
    args = p.parse_args()

    target_path = os.path.join(ROOT, "trace_js.json")
    if not os.path.exists(target_path):
        sys.exit(f"missing {target_path} — run measure.html first")
    with open(target_path) as f:
        data = json.load(f)
    # New format: {"terrain": [...], "trace": [...]}. Old format: bare trace list.
    target = data["trace"] if isinstance(data, dict) else data
    print(f"target: {len(target)} ticks from {target_path}")

    if args.eval is not None:
        trace = run_trace(*args.eval)
        s = score(trace, target)
        for name, val in zip(PARAM_NAMES, args.eval):
            print(f"  {name}: {val}")
        print(f"  score: {s:.2f}")
        return

    # Baseline (JS-exact values)
    baseline_trace = run_trace(*JS_BASELINE)
    baseline_score = score(baseline_trace, target)
    print(f"baseline score (JS values): {baseline_score:.2f}")

    # Optimize from a warm start (Nelder-Mead is local)
    x0 = to_normalized(WARM_START)
    iters = [0]
    history = []

    def cb(xk):
        iters[0] += 1
        physical = from_normalized(xk)
        s = objective(xk, target)
        history.append((iters[0], s, physical.tolist()))
        if iters[0] % 5 == 0 or iters[0] <= 5:
            print(f"  iter {iters[0]:3d}  score={s:7.1f}  " +
                  "  ".join(f"{n}={v:.2f}" for n, v in zip(PARAM_NAMES, physical)))

    print(f"optimizing... (max {args.maxiter} iterations)")
    result = minimize(
        objective, x0, args=(target,),
        method="Nelder-Mead",
        callback=cb,
        options={"maxiter": args.maxiter, "xatol": 0.005, "fatol": 0.5, "adaptive": True},
    )

    best = from_normalized(result.x)
    best_score = result.fun
    print()
    print(f"final score: {best_score:.2f}   (improvement: {baseline_score - best_score:.1f}, " +
          f"{(1 - best_score / baseline_score) * 100:.1f}%)")
    print("tuned parameters:")
    for name, val, js in zip(PARAM_NAMES, best, JS_BASELINE):
        ratio = val / js
        print(f"  {name:<18} {val:>9.3f}   (JS={js}, ratio={ratio:.2f}x)")

    # Save
    out_path = os.path.join(ROOT, "tuned_params.json")
    with open(out_path, "w") as f:
        json.dump({n: float(v) for n, v in zip(PARAM_NAMES, best)}, f, indent=2)
    print(f"saved {out_path}")

    # Save best trace for inspection
    best_trace = run_trace(*best)
    with open(os.path.join(ROOT, "trace_tuned.json"), "w") as f:
        json.dump(best_trace, f)


if __name__ == "__main__":
    main()
