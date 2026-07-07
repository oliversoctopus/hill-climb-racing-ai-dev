"""Python physics trace, paired with measure.html.

Runs the same scenario: flat ground at y=600, car spawns at (350, 500),
30-tick settle, then 120 ticks of full-forward throttle. Writes
``trace_py.json`` next to ``trace_js.json``. Use ``compare.py`` to diff them.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Dict

from Box2D import (
    b2World,
    b2Vec2,
    b2BodyDef,
    b2_staticBody,
    b2FixtureDef,
    b2Filter,
    b2EdgeShape,
)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from constants import (
    SCALE,
    DIRT_CATEGORY,
    DIRT_MASK,
    GRASS_CATEGORY,
    GRASS_MASK,
    GRAVITY,
    PHYSICS_DT,
    VEL_ITERS,
    POS_ITERS,
)
from car import Car
from world import HillClimbContactListener


SPAWN_X_PX = 350
SPAWN_Y_PX = 500
SETTLE_TICKS = 30
THROTTLE_TICKS = 120


def build_world_with_terrain(verts: list) -> tuple[b2World, HillClimbContactListener]:
    """Build a world whose ground is the list of (x_px, y_px) vertices.
    Mirrors Ground.js setBodies: one edge per dirt segment + one grass segment 5px above."""
    world = b2World(gravity=b2Vec2(*GRAVITY), doSleep=True)
    listener = HillClimbContactListener()
    world.contactListener = listener

    bd = b2BodyDef()
    bd.type = b2_staticBody
    body = world.CreateBody(bd)
    body.userData = {"id": "ground", "owner": None}

    def add_layer(y_offset: float, mask: int, category: int) -> None:
        for i in range(1, len(verts)):
            a = verts[i - 1]; b = verts[i]
            fd = b2FixtureDef(
                shape=b2EdgeShape(vertices=[
                    b2Vec2(a[0] / SCALE, (a[1] + y_offset) / SCALE),
                    b2Vec2(b[0] / SCALE, (b[1] + y_offset) / SCALE),
                ]),
                friction=0.99,
                restitution=0.1,
                filter=b2Filter(categoryBits=category, maskBits=mask),
            )
            body.CreateFixture(fd)

    add_layer(0,  DIRT_MASK,  DIRT_CATEGORY)
    add_layer(-5, GRASS_MASK, GRASS_CATEGORY)
    return world, listener


def load_terrain_from_js_trace(path: str) -> list:
    """Read the terrain vertices that measure.html embedded in trace_js.json."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "terrain" in data:
        return data["terrain"]
    raise RuntimeError(f"{path} doesn't contain terrain vertices — re-export from measure.html")


def record(car: Car, tick: int) -> Dict:
    cb = car.chassis_body
    cv = cb.linearVelocity
    return {
        "tick": tick,
        "cx": cb.position.x * SCALE,
        "cy": cb.position.y * SCALE,
        "cangle": cb.angle,
        "cvx": cv.x,
        "cvy": cv.y,
        "comega": cb.angularVelocity,
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


def step(world: b2World) -> None:
    """JS-style single Step per game tick — bypass step_world() to avoid the
    substep wrapper. We want a fair JS-vs-Python comparison."""
    world.Step(PHYSICS_DT, VEL_ITERS, POS_ITERS)
    world.ClearForces()


def main() -> None:
    js_trace_path = os.path.join(os.path.dirname(HERE), "trace_js.json")
    terrain = load_terrain_from_js_trace(js_trace_path)
    world, listener = build_world_with_terrain(terrain)
    car = Car(SPAWN_X_PX, SPAWN_Y_PX, world)

    trace: List[Dict] = [record(car, 0)]

    for i in range(1, SETTLE_TICKS + 1):
        step(world)
        trace.append(record(car, i))

    car.motor_on(forward=True)
    for i in range(1, THROTTLE_TICKS + 1):
        step(world)
        trace.append(record(car, SETTLE_TICKS + i))

    out_path = os.path.join(os.path.dirname(HERE), "trace_py.json")
    with open(out_path, "w") as f:
        json.dump(trace, f)
    print(f"wrote {out_path}  ({len(trace)} ticks)")
    # Quick summary
    end = trace[-1]
    print(f"final chassis: ({end['cx']:.1f}, {end['cy']:.1f})  v=({end['cvx']:.2f}, {end['cvy']:.2f}) m/s  angle={end['cangle']:.3f}")


if __name__ == "__main__":
    main()
