"""Diagnostic: measure wheel horizontal drift across joint configurations.

The wheel suspension is supposed to constrain the wheel to move ONLY along
the chassis-local suspension axis. Any motion perpendicular to that axis
is a constraint violation ("horizontal drift" in the user's words).

Test setup:
  - chassis (4m x 1m box) floating above ground
  - one wheel (radius 0.5m) attached via joint(s)
  - ground edge below
  - drop the rig from height, optionally apply an angular kick on impact
  - log wheel position in chassis-local frame every tick
  - report max perpendicular (x) drift over 300 ticks

If b2WheelJoint drifts but the 3-joint design doesn't, the architecture
is the bug. If both drift, it's a solver iteration / numerical issue.
If neither drifts in this test but gameplay does, the bug needs a
different reproduction.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from Box2D import (  # noqa: E402
    b2World, b2Vec2,
    b2PolygonShape, b2CircleShape, b2EdgeShape,
    b2FixtureDef, b2BodyDef, b2_dynamicBody,
    b2WheelJointDef, b2RevoluteJointDef, b2PrismaticJointDef, b2DistanceJointDef,
    b2Filter,
)


WHEEL_CAT = 0x1
CHASSIS_CAT = 0x2
GROUND_CAT = 0x4

CHASSIS_INIT_POS = b2Vec2(0.0, 15.0)
WHEEL_INIT_POS = b2Vec2(1.0, 16.0)         # 1 m forward, 1 m below chassis center
GROUND_Y = 20.0


def _make_world() -> tuple[b2World, object]:
    world = b2World(gravity=(0, 10), doSleep=False)
    ground = world.CreateStaticBody(position=(0, 0))
    ground.CreateFixture(
        b2FixtureDef(
            shape=b2EdgeShape(vertices=[b2Vec2(-100, GROUND_Y), b2Vec2(100, GROUND_Y)]),
            friction=0.99,
            filter=b2Filter(categoryBits=GROUND_CAT, maskBits=WHEEL_CAT | CHASSIS_CAT),
        )
    )
    return world, ground


def _make_chassis(world: b2World) -> object:
    bd = b2BodyDef()
    bd.type = b2_dynamicBody
    bd.position = CHASSIS_INIT_POS
    bd.linearDamping = 0.05
    bd.angularDamping = 0.11
    chassis = world.CreateBody(bd)
    chassis.CreateFixture(
        b2FixtureDef(
            shape=b2PolygonShape(box=(2.0, 0.5)),
            density=1.0,
            friction=0.5,
            restitution=0.01,
            filter=b2Filter(categoryBits=CHASSIS_CAT, maskBits=GROUND_CAT),
        )
    )
    return chassis


def _make_wheel_body(world: b2World, *, density: float = 1.0, group: int = 0) -> object:
    bd = b2BodyDef()
    bd.type = b2_dynamicBody
    bd.position = WHEEL_INIT_POS
    body = world.CreateBody(bd)
    body.CreateFixture(
        b2FixtureDef(
            shape=b2CircleShape(radius=0.5),
            density=density,
            friction=1.0,
            restitution=0.1,
            filter=b2Filter(categoryBits=WHEEL_CAT, maskBits=GROUND_CAT, groupIndex=group),
        )
    )
    body.angularDamping = 1.8
    return body


def build_wheel_joint_rig(world: b2World, chassis, *, freq: float, damp: float) -> object:
    """Single body + b2WheelJoint (current architecture)."""
    wheel = _make_wheel_body(world)
    jd = b2WheelJointDef(
        bodyA=chassis,
        bodyB=wheel,
        anchor=WHEEL_INIT_POS,
        axis=b2Vec2(0.0, 1.0),
        frequencyHz=freq,
        dampingRatio=damp,
    )
    world.CreateJoint(jd)
    return wheel


def build_3joint_rig(world: b2World, chassis, *, rim_density: float,
                     freq: float = 70.0, damp: float = 25.0) -> object:
    """JS-faithful 3-joint: rolling body + rim body + revolute + prismatic + distance."""
    # Rolling body (collides with ground via WHEEL_CAT).
    rolling = _make_wheel_body(world, density=1.0, group=0)
    # Rim body — doesn't collide with anything (negative groupIndex shared).
    rim_bd = b2BodyDef()
    rim_bd.type = b2_dynamicBody
    rim_bd.position = WHEEL_INIT_POS
    rim = world.CreateBody(rim_bd)
    rim.CreateFixture(
        b2FixtureDef(
            shape=b2CircleShape(radius=0.5),
            density=rim_density,
            friction=0.99,
            restitution=0.2,
            filter=b2Filter(groupIndex=-1),
        )
    )

    rev = b2RevoluteJointDef()
    rev.Initialize(rolling, rim, WHEEL_INIT_POS)
    world.CreateJoint(rev)

    pris = b2PrismaticJointDef()
    pris.Initialize(rim, chassis, WHEEL_INIT_POS, b2Vec2(0.0, -1.0))
    world.CreateJoint(pris)

    dj = b2DistanceJointDef()
    anchor_wheel = WHEEL_INIT_POS
    anchor_car = b2Vec2(WHEEL_INIT_POS.x, WHEEL_INIT_POS.y - 1.5)  # 3r above
    dj.Initialize(rim, chassis, anchor_wheel, anchor_car)
    dj.frequencyHz = freq
    dj.dampingRatio = damp
    world.CreateJoint(dj)

    return rolling


def run_drop_test(rig_builder, *, vel_iters: int = 10, pos_iters: int = 10,
                  ticks: int = 300, angular_kick: float = 0.0,
                  initial_chassis_angvel: float = 0.0) -> dict:
    """Drop rig, return drift stats.

    angular_kick: extra angular impulse applied to chassis the first tick
                  after wheel contacts ground (simulates motor torque during landing).
    initial_chassis_angvel: spin the chassis from t=0 (simulates car already in motion).
    """
    world, _ = _make_world()
    chassis = _make_chassis(world)
    wheel = rig_builder(world, chassis)
    chassis.angularVelocity = initial_chassis_angvel

    max_drift = 0.0
    drift_tick = -1
    contact_tick = -1
    kicked = False
    drift_series = []

    for tick in range(ticks):
        world.Step(1.0 / 30.0, vel_iters, pos_iters)

        # Once wheel touches ground, optionally apply angular kick.
        wheel_contacts = bool(wheel.contacts)
        if wheel_contacts and contact_tick < 0:
            contact_tick = tick
        if (wheel_contacts and not kicked and angular_kick != 0.0 and contact_tick == tick):
            chassis.ApplyTorque(angular_kick, True)
            kicked = True

        # Wheel position in chassis-local frame. The wheel was anchored at
        # local (1, 1) so its local x should remain at 1 (constraint enforces
        # no motion perpendicular to the chassis-local y axis). Any deviation
        # from 1 is drift.
        local_wheel = chassis.GetLocalPoint(wheel.worldCenter)
        x_drift = abs(local_wheel.x - WHEEL_INIT_POS.x)
        drift_series.append(x_drift)
        if x_drift > max_drift:
            max_drift = x_drift
            drift_tick = tick

    return dict(
        max_drift_m=max_drift,
        drift_tick=drift_tick,
        contact_tick=contact_tick,
        final_drift_m=drift_series[-1],
    )


def fmt(d: dict) -> str:
    return (f"max_drift={d['max_drift_m']*1000:6.1f}mm  "
            f"@tick={d['drift_tick']:3d}  "
            f"contact@={d['contact_tick']:3d}  "
            f"final={d['final_drift_m']*1000:6.1f}mm")


def main():
    print("Wheel drift diagnostic")
    print("=" * 80)
    print(f"chassis at {tuple(CHASSIS_INIT_POS)}, wheel at {tuple(WHEEL_INIT_POS)}, "
          f"ground at y={GROUND_Y}")
    print(f"wheel chassis-local x should be {WHEEL_INIT_POS.x:.1f} forever; any deviation = drift")
    print()

    # ----- Test 1: simple drop, no kick -----
    print("[Test 1] simple drop (gravity only, no rotation, no motor)")
    print("-" * 80)
    cases = [
        ("b2WheelJoint  freq=6   damp=0.8 (current)",
         lambda w, c: build_wheel_joint_rig(w, c, freq=6.0, damp=0.8)),
        ("b2WheelJoint  freq=70  damp=25  (JS-style params)",
         lambda w, c: build_wheel_joint_rig(w, c, freq=70.0, damp=25.0)),
        ("3-joint  rim_density=0.05 (JS)",
         lambda w, c: build_3joint_rig(w, c, rim_density=0.05)),
        ("3-joint  rim_density=0.2",
         lambda w, c: build_3joint_rig(w, c, rim_density=0.2)),
        ("3-joint  rim_density=0.5",
         lambda w, c: build_3joint_rig(w, c, rim_density=0.5)),
        ("3-joint  rim_density=1.0",
         lambda w, c: build_3joint_rig(w, c, rim_density=1.0)),
    ]
    for label, builder in cases:
        r = run_drop_test(builder)
        print(f"  {label:<48s}  {fmt(r)}")

    # ----- Test 2: drop + angular kick on landing -----
    print()
    print("[Test 2] drop + 500 N·m torque kick on landing (simulates motor)")
    print("-" * 80)
    for label, builder in cases:
        r = run_drop_test(builder, angular_kick=500.0)
        print(f"  {label:<48s}  {fmt(r)}")

    # ----- Test 3: chassis already spinning when dropped -----
    print()
    print("[Test 3] drop with chassis spinning at 3 rad/s (simulates flip recovery)")
    print("-" * 80)
    for label, builder in cases:
        r = run_drop_test(builder, initial_chassis_angvel=3.0)
        print(f"  {label:<48s}  {fmt(r)}")

    # ----- Test 4: solver iteration sweep on current b2WheelJoint -----
    print()
    print("[Test 4] solver iteration sweep on current b2WheelJoint (test 2 conditions)")
    print("-" * 80)
    for vi, pi in [(10, 10), (20, 20), (40, 40), (80, 80)]:
        r = run_drop_test(
            lambda w, c: build_wheel_joint_rig(w, c, freq=6.0, damp=0.8),
            angular_kick=500.0, vel_iters=vi, pos_iters=pi,
        )
        label = f"vel={vi:<3d} pos={pi:<3d}"
        print(f"  {label:<48s}  {fmt(r)}")


if __name__ == "__main__":
    main()
