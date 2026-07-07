"""Sweep wheel body linear damping — does it tame the front-wheel local-y oscillation?"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from Box2D import (
    b2World, b2Vec2, b2BodyDef, b2_staticBody, b2FixtureDef, b2Filter, b2EdgeShape,
)
from constants import (SCALE, DIRT_CATEGORY, DIRT_MASK, GRASS_CATEGORY, GRASS_MASK,
                       GRAVITY, PHYSICS_DT, VEL_ITERS, POS_ITERS, MOTOR_SPEED)
from car import Car
from world import HillClimbContactListener
from measure import build_world_with_terrain, load_terrain_from_js_trace, SPAWN_X_PX, SPAWN_Y_PX, SETTLE_TICKS, THROTTLE_TICKS
from compare import load


def run_with_wheel_lin_damp(wheel_lin_damp):
    terrain = load_terrain_from_js_trace(os.path.join(ROOT, "trace_js.json"))
    world, listener = build_world_with_terrain(terrain)
    car = Car(SPAWN_X_PX, SPAWN_Y_PX, world)
    for wheel in car.wheels:
        wheel.body.linearDamping = wheel_lin_damp
    trace = []
    def rec(t):
        cb = car.chassis_body
        return {"tick": t, "cx": cb.position.x*SCALE, "cy": cb.position.y*SCALE, "cangle": cb.angle,
                "w0x": car.wheels[0].body.position.x*SCALE, "w0y": car.wheels[0].body.position.y*SCALE,
                "w1x": car.wheels[1].body.position.x*SCALE, "w1y": car.wheels[1].body.position.y*SCALE}
    trace.append(rec(0))
    for i in range(1, SETTLE_TICKS + 1):
        world.Step(PHYSICS_DT, VEL_ITERS, POS_ITERS); world.ClearForces()
        trace.append(rec(i))
    car.wheels[0].set_motor(-MOTOR_SPEED, 834)
    car.wheels[1].set_motor(-MOTOR_SPEED, 419)
    car.chassis_body.ApplyTorque(-2.0, True)
    for i in range(1, THROTTLE_TICKS + 1):
        world.Step(PHYSICS_DT, VEL_ITERS, POS_ITERS); world.ClearForces()
        trace.append(rec(SETTLE_TICKS + i))
    return trace


def front_local_y_path(trace, start=30):
    s = 0.0
    prev = None
    for r in trace[start:]:
        # Transform front wheel into chassis-local frame
        ca = r["cangle"]
        dx = r["w1x"] - r["cx"]; dy = r["w1y"] - r["cy"]
        cosa = math.cos(-ca); sina = math.sin(-ca)
        ly = dx * sina + dy * cosa
        if prev is not None:
            s += abs(ly - prev)
        prev = ly
    return s


def back_local_y_path(trace, start=30):
    s = 0.0; prev = None
    for r in trace[start:]:
        ca = r["cangle"]
        dx = r["w0x"] - r["cx"]; dy = r["w0y"] - r["cy"]
        cosa = math.cos(-ca); sina = math.sin(-ca)
        ly = dx * sina + dy * cosa
        if prev is not None:
            s += abs(ly - prev)
        prev = ly
    return s


js = load("trace_js.json")
print(f"target (JS):  back-local-y path = {back_local_y_path(js):.2f}   front-local-y path = {front_local_y_path(js):.2f}")
print()
print(f"{'wheel_lin_damp':>14}  {'back-local-y':>13}  {'front-local-y':>14}  {'final cx':>9}")
for wd in [0.0, 0.1, 0.3, 0.5, 1.0, 2.0, 4.0, 8.0]:
    t = run_with_wheel_lin_damp(wd)
    print(f"{wd:>14.2f}  {back_local_y_path(t):>13.2f}  {front_local_y_path(t):>14.2f}  {t[-1]['cx']:>9.1f}")
