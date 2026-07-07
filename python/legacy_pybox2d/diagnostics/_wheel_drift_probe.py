"""Track how much the wheel translates off its expected (chassis-local) anchor.

Drives the car forward over a hilly track, prints the wheel's chassis-local-x
offset over time. Expected: ~0 (the prismatic should clamp it). If it drifts,
the prismatic constraint is failing under load.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from env import _build_world
from constants import SCALE, CHASSIS_WIDTH, WHEEL_SIZE, CANVAS_HEIGHT
from world import step_world

world, listener, ground, car = _build_world(42)

# What the wheels' chassis-local x SHOULD be (Car.py setup)
cw, ws = CHASSIS_WIDTH, WHEEL_SIZE
expected_w0_local_x = (-cw / 2 + ws * 1.2) / SCALE   # back wheel
expected_w1_local_x = ( cw / 2 - ws * 1.2) / SCALE   # front wheel

car.motor_on(forward=True)

max_drift = [0.0, 0.0]
max_drift_t = [0, 0]
drift_log = []

for t in range(900):  # 30 seconds at 30 FPS
    step_world(world, listener)
    car.update(CANVAS_HEIGHT)
    for i, w in enumerate(car.wheels):
        # Wheel position in chassis local frame
        lp = car.chassis_body.GetLocalPoint(w.body.position)
        expected_x = expected_w0_local_x if i == 0 else expected_w1_local_x
        drift_x = lp.x - expected_x
        if abs(drift_x) > abs(max_drift[i]):
            max_drift[i] = drift_x
            max_drift_t[i] = t
    if t % 30 == 0:
        lp0 = car.chassis_body.GetLocalPoint(car.wheels[0].body.position)
        lp1 = car.chassis_body.GetLocalPoint(car.wheels[1].body.position)
        drift_log.append((t, lp0.x - expected_w0_local_x, lp0.y, lp1.x - expected_w1_local_x, lp1.y))

print("expected back-wheel local x:  {:.3f} m".format(expected_w0_local_x))
print("expected front-wheel local x: {:.3f} m".format(expected_w1_local_x))
print()
print(" t    | w0 dx       w0 ly      w1 dx       w1 ly")
for entry in drift_log:
    print(" {:4d} | {:+8.4f}m  {:+6.3f}m  {:+8.4f}m  {:+6.3f}m".format(*entry))
print()
print(f"MAX BACK  wheel drift along chassis-x:  {max_drift[0]:+.4f}m at t={max_drift_t[0]}")
print(f"MAX FRONT wheel drift along chassis-x:  {max_drift[1]:+.4f}m at t={max_drift_t[1]}")
print(f"chassis is {cw/SCALE:.2f}m wide for reference; >0.1m drift = visibly broken")
