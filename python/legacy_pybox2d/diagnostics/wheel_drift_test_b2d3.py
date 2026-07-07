"""Mirror of wheel_drift_test.py but using pyb2d3 (Box2D 3.0).

Tests whether Box2D 3.0's rewritten joint solver fixes the perpendicular
drift bug we found in pybox2d 2.3.10.

Same scene as the pybox2d test:
  - chassis 4m x 1m at (0, 15)
  - wheel radius 0.5m at (1, 16)
  - ground edge at y=20
  - gravity (0, 10)
  - 300 ticks at 1/30 s
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import pyb2d3 as b2

WHEEL_CAT = 0x1
CHASSIS_CAT = 0x2
GROUND_CAT = 0x4

CHASSIS_INIT = (0.0, 15.0)
WHEEL_INIT = (1.0, 16.0)
GROUND_Y = 20.0


def _filter(cat: int, mask: int):
    f = b2.Filter()
    f.category_bits = cat
    f.mask_bits = mask
    return f


def _shape_def(density: float, friction: float, restitution: float, cat: int, mask: int):
    sd = b2.ShapeDef()
    sd.density = density
    sd.material.friction = friction
    sd.material.restitution = restitution
    sd.filter = _filter(cat, mask)
    return sd


def _make_world() -> "b2.World":
    world = b2.World(gravity=(0.0, 10.0))

    # Ground: static body with a 200m wide box at the ground line.
    gnd = world.create_static_body(position=(0.0, GROUND_Y + 0.5))
    gdef = _shape_def(1.0, 0.99, 0.1, GROUND_CAT, WHEEL_CAT | CHASSIS_CAT)
    gnd.create_polygon_shape(gdef, b2.box(100.0, 0.5))
    return world


def _make_chassis(world: "b2.World"):
    chassis = world.create_dynamic_body(
        position=CHASSIS_INIT,
        linear_damping=0.05,
        angular_damping=0.11,
    )
    sdef = _shape_def(1.0, 0.5, 0.01, CHASSIS_CAT, GROUND_CAT)
    chassis.create_polygon_shape(sdef, b2.box(2.0, 0.5))
    return chassis


def _make_wheel_body(world: "b2.World"):
    wheel = world.create_dynamic_body(
        position=WHEEL_INIT,
        angular_damping=1.8,
    )
    sdef = _shape_def(1.0, 1.0, 0.1, WHEEL_CAT, GROUND_CAT)
    wheel.create_circle_shape(sdef, b2.circle(center=(0.0, 0.0), radius=0.5))
    return wheel


def build_wheel_joint_rig(world, chassis, *, hertz: float, damping_ratio: float):
    wheel = _make_wheel_body(world)
    # Local anchor on chassis: wheel pos in chassis-local frame = (1, 1).
    # Local anchor on wheel: its own center (0, 0).
    world.create_wheel_joint(
        body_a=chassis,
        body_b=wheel,
        local_anchor_a=(1.0, 1.0),
        local_anchor_b=(0.0, 0.0),
        local_axis_a=(0.0, 1.0),
        enable_spring=True,
        hertz=hertz,
        damping_ratio=damping_ratio,
    )
    return wheel


def run_drop_test(rig_builder, *, ticks: int = 300, substep_count: int = 4,
                  angular_kick: float = 0.0, initial_chassis_angvel: float = 0.0):
    world = _make_world()
    chassis = _make_chassis(world)
    wheel = rig_builder(world, chassis)

    if initial_chassis_angvel:
        chassis.angular_velocity = initial_chassis_angvel

    max_drift = 0.0
    drift_tick = -1
    contact_tick = -1
    kicked = False
    final_drift = 0.0

    for t in range(ticks):
        world.step(1.0 / 30.0, substep_count)

        # Did wheel touch ground? Use the body-events API if available, or
        # cheap heuristic: wheel y position vs ground.
        # Simple check: wheel y > GROUND_Y - 0.5 (its lower edge touches at y=GROUND_Y - r = 19.5)
        wheel_y = wheel.position[1]
        in_contact = wheel_y >= GROUND_Y - 0.51
        if in_contact and contact_tick < 0:
            contact_tick = t
        if in_contact and not kicked and angular_kick != 0.0 and contact_tick == t:
            chassis.apply_torque(angular_kick, True)
            kicked = True

        # Wheel position in chassis-local frame.
        # Box2D 3.0: compute manually since I don't see a get_local_point shortcut.
        cp = chassis.position
        ca = chassis.angle
        wp = wheel.position
        import math
        c, s = math.cos(ca), math.sin(ca)
        dx_world = wp[0] - cp[0]
        dy_world = wp[1] - cp[1]
        local_x =  c * dx_world + s * dy_world
        # local_y = -s * dx_world + c * dy_world  # (unused; this is the suspension axis)
        x_drift = abs(local_x - 1.0)  # anchored at chassis-local x=1.0
        final_drift = x_drift
        if x_drift > max_drift:
            max_drift = x_drift
            drift_tick = t

    return dict(
        max_drift_m=max_drift,
        drift_tick=drift_tick,
        contact_tick=contact_tick,
        final_drift_m=final_drift,
    )


def fmt(d):
    return (f"max={d['max_drift_m']*1000:6.1f}mm  "
            f"@tick={d['drift_tick']:3d}  "
            f"contact@={d['contact_tick']:3d}  "
            f"final={d['final_drift_m']*1000:6.1f}mm")


def main():
    print("pyb2d3 (Box2D 3.0) wheel drift diagnostic")
    print("=" * 80)
    print(f"chassis at {CHASSIS_INIT}, wheel at {WHEEL_INIT}, ground at y={GROUND_Y}")
    print("wheel chassis-local x should be 1.0 forever; any deviation = drift")
    print()

    cases = [
        ("WheelJoint hertz=6 damp=0.8",
         lambda w, c: build_wheel_joint_rig(w, c, hertz=6.0, damping_ratio=0.8)),
        ("WheelJoint hertz=70 damp=25",
         lambda w, c: build_wheel_joint_rig(w, c, hertz=70.0, damping_ratio=25.0)),
        ("WheelJoint hertz=30 damp=1.0",
         lambda w, c: build_wheel_joint_rig(w, c, hertz=30.0, damping_ratio=1.0)),
    ]

    print("[Test 1] simple drop (gravity only)")
    print("-" * 80)
    for label, builder in cases:
        r = run_drop_test(builder)
        print(f"  {label:<36s}  {fmt(r)}")

    print()
    print("[Test 2] drop + 500 N.m torque kick on landing")
    print("-" * 80)
    for label, builder in cases:
        r = run_drop_test(builder, angular_kick=500.0)
        print(f"  {label:<36s}  {fmt(r)}")

    print()
    print("[Test 3] drop with chassis spinning at 3 rad/s")
    print("-" * 80)
    for label, builder in cases:
        r = run_drop_test(builder, initial_chassis_angvel=3.0)
        print(f"  {label:<36s}  {fmt(r)}")

    print()
    print("[Test 4] substep_count sweep on hertz=6/damp=0.8 (test 2 conditions)")
    print("-" * 80)
    for substeps in [1, 2, 4, 8, 16]:
        r = run_drop_test(
            lambda w, c: build_wheel_joint_rig(w, c, hertz=6.0, damping_ratio=0.8),
            substep_count=substeps, angular_kick=500.0,
        )
        print(f"  substeps={substeps:<3d}                         {fmt(r)}")


if __name__ == "__main__":
    main()
