"""Python mirror of measure_multi.html — runs the same 3 scenarios in Python.

Reads trace_js_multi.json for terrain + scenario metadata. Writes
trace_py_multi.json with the corresponding Python traces. Use this for
spot-checking single-config behavior across scenarios; the tuner
(tune_multi.py) runs the scenarios in-process without writing files.
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import List, Dict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from car import Car
from measure import build_world_with_terrain, record, step


# Anti-flip throttle controller — emulates a real player. Hysteresis on
# angle + angular-velocity guard. Must match measure_multi.html and
# tune_multi.py line-for-line.
#   release when:  chassis_angle < ANGLE_PANIC  OR  chassis_omega < OMEGA_PANIC
#   resume  when:  chassis_angle > ANGLE_RESUME AND chassis_omega > -0.5
ANGLE_PANIC  = -0.4    # rad, ~-23°
ANGLE_RESUME = -0.15   # rad, ~-9°
OMEGA_PANIC  = -2.0    # rad/s


def _normalize_angle(a: float) -> float:
    while a > math.pi:  a -= 2 * math.pi
    while a < -math.pi: a += 2 * math.pi
    return a


# ---------------------------------------------------------------------------
# Terrain generators — must match measure_multi.html line-for-line so the
# Python traces simulate identical geometry.
# ---------------------------------------------------------------------------
def terrain_flat() -> List[List[float]]:
    return [[x, 600.0] for x in range(0, 4001, 100)]


def terrain_ramp() -> List[List[float]]:
    verts = []
    for x in range(0, 4001, 50):
        if x < 500:
            y = 600.0
        else:
            y = 600.0 - 0.344 * (x - 500)
        verts.append([float(x), y])
    return verts


def terrain_bump() -> List[List[float]]:
    verts = []
    for x in range(0, 4001, 25):
        d = x - 1500
        y = 600.0 - 40.0 * math.exp(-(d * d) / (2 * 80 * 80))
        verts.append([float(x), y])
    return verts


# Spawn x / y mirrors the JS html for each scenario.
SCENARIOS = {
    "cruise_flat": dict(terrain=terrain_flat, spawn_x=350, spawn_y=500,
                        settle_ticks=30, throttle_ticks=240),
    "climb_ramp":  dict(terrain=terrain_ramp, spawn_x=350, spawn_y=500,
                        settle_ticks=30, throttle_ticks=240),
    "bump_coast":  dict(terrain=terrain_bump, spawn_x=350, spawn_y=500,
                        settle_ticks=30, throttle_ticks=200),
}


def run_scenario(name: str, verts: List[List[float]], spawn_x: int, spawn_y: int,
                 settle_ticks: int, throttle_ticks: int) -> Dict:
    """Build a world for this scenario, settle, then drive forward with the
    anti-flip throttle controller (releases throttle when about to wheelie
    over, resumes when chassis recovers)."""
    world, _ = build_world_with_terrain(verts)
    car = Car(spawn_x, spawn_y, world)
    trace = [record(car, 0)]
    for i in range(1, settle_ticks + 1):
        step(world)
        trace.append(record(car, i))

    car.motor_on(forward=True)
    throttle_on = True
    motor_releases = 0
    for i in range(1, throttle_ticks + 1):
        a = _normalize_angle(car.chassis_body.angle)
        omega = car.chassis_body.angularVelocity
        if throttle_on and (a < ANGLE_PANIC or omega < OMEGA_PANIC):
            car.motor_off()
            throttle_on = False
            motor_releases += 1
        elif (not throttle_on) and a > ANGLE_RESUME and omega > -0.5:
            car.motor_on(forward=True)
            throttle_on = True
        step(world)
        rec = record(car, settle_ticks + i)
        rec["throttle"] = 1 if throttle_on else 0
        trace.append(rec)
    return {
        "name": name,
        "terrain": verts,
        "spawn_x": spawn_x, "spawn_y": spawn_y,
        "settle_ticks": settle_ticks, "throttle_ticks": throttle_ticks,
        "angle_panic": ANGLE_PANIC, "angle_resume": ANGLE_RESUME,
        "motor_releases": motor_releases,
        "trace": trace,
    }


def main() -> None:
    out = {"scenarios": []}
    for name, cfg in SCENARIOS.items():
        verts = cfg["terrain"]()
        s = run_scenario(name, verts, cfg["spawn_x"], cfg["spawn_y"],
                         cfg["settle_ticks"], cfg["throttle_ticks"])
        last = s["trace"][-1]
        print(f"{name:<14} {len(s['trace']):4d} ticks  final cx={last['cx']:.0f}px  cy={last['cy']:.0f}px  motor_releases={s['motor_releases']}")
        out["scenarios"].append(s)

    out_path = os.path.join(ROOT, "trace_py_multi.json")
    with open(out_path, "w") as f:
        json.dump(out, f)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
