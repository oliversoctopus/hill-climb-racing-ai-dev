"""Port of Wheel.js, refactored to use b2WheelJoint.

The original JS source uses two bodies per wheel (a rolling body + a non-
colliding "rim") wired with three joints (revolute as motor, prismatic as
suspension axis, distance as spring). That was the standard Box2D
suspension recipe in the early-2010s. b2WheelJoint, added later, bundles
exactly that — axis + spring + motor — into one purpose-built joint.

We switched away from the JS three-joint design because in Box2D 2.3 the
prismatic constraint between rim and chassis couldn't hold the wheel
on-axis under hard impacts: the rim's density (0.05) vs chassis's density
(1.0) created a 20:1 mass ratio that the constraint solver couldn't
enforce — measured drift of >1 m horizontally on spawn impact. Raising
the rim density fixed the drift but killed traction (wheelspin without
forward motion). Neither end of the rim-density knob worked; the joint
architecture itself was the problem.

b2WheelJoint sidesteps this entirely by linking the rolling body directly
to the chassis. One body and one joint per wheel; the constraint solver
has nothing tricky to handle.

Mapping JS parameter → Box2D 2.3 attribute:
    frequencyHz   -> springFrequencyHz
    dampingRatio  -> springDampingRatio
    motorSpeed/maxMotorTorque/motorEnabled: same as the old revolute joint API
"""

from __future__ import annotations

from Box2D import (
    b2World,
    b2Body,
    b2CircleShape,
    b2FixtureDef,
    b2Filter,
    b2Vec2,
    b2WheelJointDef,
)

from constants import (
    SCALE,
    WHEEL_BODY_DENSITY,
    WHEEL_BODY_FRICTION,
    WHEEL_BODY_RESTITUTION,
    WHEEL_BODY_ANGULAR_DAMPING,
    WHEEL_DIST_JOINT_FREQ,
    WHEEL_DIST_JOINT_DAMP,
    WHEEL_CATEGORY,
    WHEEL_MASK,
)


class Wheel:
    def __init__(self, x_px: float, y_px: float, radius_px: float, chassis: b2Body, world: b2World):
        self.world = world
        self.radius_px = radius_px
        self.on_ground = False

        r_m = radius_px / SCALE
        pos = (x_px / SCALE, y_px / SCALE)

        # --- rolling body (the only body per wheel — no more rim) ---
        self.body = world.CreateDynamicBody(position=pos, angle=0.0)
        self.body.userData = {"id": "wheel", "owner": self}
        self.body.CreateFixture(
            b2FixtureDef(
                shape=b2CircleShape(radius=r_m),
                density=WHEEL_BODY_DENSITY,
                friction=WHEEL_BODY_FRICTION,
                restitution=WHEEL_BODY_RESTITUTION,
                filter=b2Filter(categoryBits=WHEEL_CATEGORY, maskBits=WHEEL_MASK),
            )
        )
        self.body.angularDamping = WHEEL_BODY_ANGULAR_DAMPING

        if chassis is not None:
            # b2WheelJoint: chassis <-> wheel, with suspension axis along
            # chassis-local +y (downward in our y-down convention). The
            # wheel rests at its spawn world-position and can translate
            # along that axis as the spring compresses/extends.
            jd = b2WheelJointDef(
                bodyA=chassis,
                bodyB=self.body,
                anchor=b2Vec2(*pos),
                axis=b2Vec2(0.0, 1.0),
                frequencyHz=WHEEL_DIST_JOINT_FREQ,
                dampingRatio=WHEEL_DIST_JOINT_DAMP,
            )
            self.wheel_joint = world.CreateJoint(jd)
        else:
            self.wheel_joint = None

    # ----------------------------------------------------------------
    def set_motor(self, speed: float, max_torque: float) -> None:
        # The old revolute-joint design had a sign quirk: it was wired with
        # bodyA = rolling, bodyB = rim, and car.py compensates by negating
        # MOTOR_SPEED for "forward". b2WheelJoint here uses bodyA = chassis,
        # bodyB = wheel, which flips the convention. To keep car.py's
        # call-site unchanged, negate the speed here so a "forward" call
        # from car.py still drives the car forward.
        if self.wheel_joint is None:
            return
        self.wheel_joint.motorEnabled = True
        self.wheel_joint.motorSpeed = -speed
        self.wheel_joint.maxMotorTorque = max_torque

    def disable_motor(self) -> None:
        if self.wheel_joint is not None:
            self.wheel_joint.motorEnabled = False
