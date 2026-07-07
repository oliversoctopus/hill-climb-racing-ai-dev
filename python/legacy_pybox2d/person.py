"""Port of Person.js — Head (circle) + Torso (box) connected by revolute + distance joints.

Both bodies live in PERSON_CATEGORY and only collide with grass; the chassis
and wheels can pass through the rider freely. The head-vs-ground contact is
how the JS game decides the car is dead, so the head's userData id "head" is
load-bearing for the contact listener in world.py.
"""

from __future__ import annotations

from Box2D import (
    b2World,
    b2PolygonShape,
    b2CircleShape,
    b2FixtureDef,
    b2Filter,
    b2Vec2,
    b2RevoluteJointDef,
    b2DistanceJointDef,
)

from constants import (
    SCALE,
    PERSON_WIDTH,
    PERSON_HEIGHT,
    HEAD_DENSITY,
    HEAD_FRICTION,
    HEAD_RESTITUTION,
    TORSO_DENSITY,
    TORSO_FRICTION,
    TORSO_RESTITUTION,
    PERSON_CATEGORY,
    PERSON_MASK,
)


class Head:
    def __init__(self, x_px: float, y_px: float, radius_px: float, world: b2World):
        self.world = world
        self.radius_px = radius_px
        self.body = world.CreateDynamicBody(position=(x_px / SCALE, y_px / SCALE), angle=0.0)
        self.body.userData = {"id": "head", "owner": self}
        self.body.CreateFixture(
            b2FixtureDef(
                shape=b2CircleShape(radius=radius_px / SCALE),
                density=HEAD_DENSITY,
                friction=HEAD_FRICTION,
                restitution=HEAD_RESTITUTION,
                filter=b2Filter(categoryBits=PERSON_CATEGORY, maskBits=PERSON_MASK),
            )
        )


class Torso:
    def __init__(self, x_px: float, y_px: float, height_px: float, width_px: float, world: b2World):
        self.world = world
        self.width_px = width_px
        self.height_px = height_px
        self.body = world.CreateDynamicBody(position=(x_px / SCALE, y_px / SCALE), angle=0.0)
        self.body.userData = {"id": "torso", "owner": self}
        self.body.CreateFixture(
            b2FixtureDef(
                shape=b2PolygonShape(box=(width_px / 2 / SCALE, height_px / 2 / SCALE)),
                density=TORSO_DENSITY,
                friction=TORSO_FRICTION,
                restitution=TORSO_RESTITUTION,
                filter=b2Filter(categoryBits=PERSON_CATEGORY, maskBits=PERSON_MASK),
            )
        )


class Person:
    """x, y are the car/joint anchor in pixel space. Torso sits centered at
    (x, y - personHeight/2); head sits at (x, y - personHeight - personWidth)."""

    def __init__(self, x_px: float, y_px: float, world: b2World,
                 width_px: float = PERSON_WIDTH, height_px: float = PERSON_HEIGHT):
        self.world = world
        self.width_px = width_px
        self.height_px = height_px

        self.torso = Torso(x_px, y_px - height_px / 2.0, height_px, width_px, world)
        self.head = Head(x_px, y_px - height_px - width_px, width_px, world)

        # Revolute at the neck (x, y - height) — matches JS exactly. The
        # head-torso constraint was never the issue: the visible "head
        # flipping below the chassis" was actually the whole person body
        # (head + torso as a rigid-ish unit) swinging 180° around the
        # *chassis* anchor. That's handled in car.py with limits on the
        # torso-chassis revolute.
        neck = b2Vec2(x_px / SCALE, (y_px - height_px) / SCALE)
        self.head_joint = world.CreateJoint(
            b2RevoluteJointDef(
                bodyA=self.head.body,
                bodyB=self.torso.body,
                localAnchorA=self.head.body.GetLocalPoint(neck),
                localAnchorB=self.torso.body.GetLocalPoint(neck),
            )
        )

        # distance joint between head-top and torso-base (just keeps geometry stable)
        anchor_torso = b2Vec2(x_px / SCALE, y_px / SCALE)
        anchor_head = b2Vec2(x_px / SCALE, (y_px - height_px - width_px) / SCALE)
        self.dist_joint = world.CreateJoint(
            b2DistanceJointDef(
                bodyA=self.head.body,
                bodyB=self.torso.body,
                anchorA=anchor_head,
                anchorB=anchor_torso,
            )
        )
