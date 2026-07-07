"""Port of Car.js — chassis polygon (3 fixtures), two wheels, a rider, and joints.

The chassis polygon comes from Car.js as 3 separate convex fixtures:
  1. Main hull (5 verts, low slope at front).
  2. Spike on the roof — looks like a small antenna in the sprite.
  3. Front bumper, a tiny rectangle off the right side with lower friction.

Joints:
  - person revolute (torso ↔ chassis at chassis center)
  - person distance (torso top ↔ chassis right, freq=5, damp=0.1, length *= 1.1)

motor_on(forward) drives both wheels' motors. The front wheel has 700 N·m
max torque, the rear 350 — this asymmetry is what gives the car its
characteristic wheelie behavior in JS.
"""

from __future__ import annotations

from Box2D import (
    b2World,
    b2PolygonShape,
    b2FixtureDef,
    b2Filter,
    b2Vec2,
    b2BodyDef,
    b2_dynamicBody,
    b2RevoluteJointDef,
    b2DistanceJointDef,
)

from constants import (
    SCALE,
    CHASSIS_WIDTH,
    CHASSIS_HEIGHT,
    WHEEL_SIZE,
    CHASSIS_DENSITY,
    CHASSIS_FRICTION,
    CHASSIS_RESTITUTION,
    CHASSIS_BUMPER_FRICTION,
    CHASSIS_BUMPER_RESTITUTION,
    CHASSIS_ANGULAR_DAMPING,
    CHASSIS_LINEAR_DAMPING,
    CHASSIS_CATEGORY,
    CHASSIS_MASK,
    MOTOR_SPEED,
    MOTOR_TORQUE_REAR,
    MOTOR_TORQUE_FRONT,
    ROTATION_TORQUE,
    PERSON_CHASSIS_DIST_JOINT_FREQ,
    PERSON_CHASSIS_DIST_JOINT_DAMP,
    PERSON_CHASSIS_LENGTH_MULTIPLIER,
    PERSON_HEIGHT,
)
from wheel import Wheel
from person import Person


class Car:
    def __init__(self, x_px: float, y_px: float, world: b2World):
        self.world = world
        self.dead = False
        self.starting_x = x_px
        self.max_distance = 0.0
        self.change_count = 0  # ticks since last new max distance
        self.motor_state = 0  # -1 reverse, 0 off, +1 forward

        self.chassis_width = CHASSIS_WIDTH
        self.chassis_height = CHASSIS_HEIGHT
        self.wheel_size = WHEEL_SIZE

        # ---- chassis body ----
        # Build via an explicit b2BodyDef rather than CreateDynamicBody kwargs.
        # The kwarg form intermittently produced a body at world origin (0, 0)
        # — a user screenshot caught the chassis at (0, 0) while wheels/person
        # sat at the correct spawn. Setting position on the body def explicitly
        # is reliable.
        spawn = b2Vec2(x_px / SCALE, y_px / SCALE)
        bd = b2BodyDef()
        bd.type = b2_dynamicBody
        bd.position = spawn
        bd.angle = 0.0
        # bullet=True on the chassis enabled CCD and triggered a native
        # segfault during death (joints destroyed, leftover high angular
        # velocity → TOI computation iterated on a corrupt constraint
        # graph). Bullet is only needed on the head, which is what triggers
        # the death rule.
        bd.angularDamping = CHASSIS_ANGULAR_DAMPING
        bd.linearDamping = CHASSIS_LINEAR_DAMPING
        self.chassis_body = world.CreateBody(bd)
        self.chassis_body.userData = {"id": "car", "owner": self}
        # Defensive sanity check — if pybox2d still produces a body at origin,
        # raise so the failure is loud instead of corrupting the play state.
        assert (
            abs(self.chassis_body.position.x - spawn.x) < 0.01
            and abs(self.chassis_body.position.y - spawn.y) < 0.01
        ), f"chassis body created at {self.chassis_body.position}, expected {spawn}"

        cw = self.chassis_width
        ch = self.chassis_height

        # Fixture 1 — main hull (5 verts, Car.js vectors)
        self._add_polygon_fixture(
            [
                (-cw / 2, -ch / 2),
                (cw / 4 + 5, -ch / 2),
                (cw / 2, -ch / 2 + 5),
                (cw / 2, ch / 2),
                (-cw / 2, ch / 2),
            ],
            density=CHASSIS_DENSITY,
            friction=CHASSIS_FRICTION,
            restitution=CHASSIS_RESTITUTION,
        )

        # Fixture 2 — spike on top (Car.js vectors2)
        self._add_polygon_fixture(
            [
                (cw / 4, -ch / 2),
                (cw / 4 - 15, -ch / 2 - 20),
                (cw / 4 - 5, -ch / 2 - 20),
                (cw / 4 + 10, -ch / 2),
            ],
            density=CHASSIS_DENSITY,
            friction=CHASSIS_FRICTION,
            restitution=CHASSIS_RESTITUTION,
        )

        # Fixture 3 — front bumper (Car.js vectors3, lower friction 0.1)
        self._add_polygon_fixture(
            [
                (cw / 2, -ch / 2 + 5),
                (cw / 2 + 5, -ch / 2 + 8),
                (cw / 2 + 5, ch / 2 - 5),
                (cw / 2, ch / 2),
            ],
            density=CHASSIS_DENSITY,
            friction=CHASSIS_BUMPER_FRICTION,
            restitution=CHASSIS_BUMPER_RESTITUTION,
        )

        # ---- wheels ----
        wy = y_px + ch / 2 + WHEEL_SIZE / 4
        self.wheels = [
            Wheel(x_px - cw / 2 + WHEEL_SIZE * 1.2, wy, WHEEL_SIZE, self.chassis_body, world),
            Wheel(x_px + cw / 2 - WHEEL_SIZE * 1.2, wy, WHEEL_SIZE, self.chassis_body, world),
        ]

        # ---- rider ----
        self.person = Person(x_px, y_px, world)

        # Person ↔ chassis revolute at the chassis center. JS has no limits,
        # but in Box2D 2.3 the soft chassis-person dist_joint (freq=5) isn't
        # strong enough to prevent the rider unit from swinging 180° around
        # this anchor under hard impacts — the dist_joint actually has a
        # second equilibrium at 180° because of how its anchors are
        # positioned, and the soft spring + gravity can stabilize the rider
        # below the chassis (which kills the car via head-ground contact).
        # ±90° limits allow normal wheelies/landings but block full inversion.
        joint_pos = b2Vec2(x_px / SCALE, y_px / SCALE)
        self.rev_joint = world.CreateJoint(
            b2RevoluteJointDef(
                bodyA=self.person.torso.body,
                bodyB=self.chassis_body,
                localAnchorA=self.person.torso.body.GetLocalPoint(joint_pos),
                localAnchorB=self.chassis_body.GetLocalPoint(joint_pos),
                enableLimit=True,
                lowerAngle=-1.571,  # -90°
                upperAngle= 1.571,  # +90°
            )
        )

        # Person ↔ chassis distance joint (suspends torso from a point above the chassis right edge)
        anchor_person = b2Vec2(x_px / SCALE, (y_px - PERSON_HEIGHT * 2.0 / 3.0) / SCALE)
        anchor_car = b2Vec2((x_px + cw / 2) / SCALE, (y_px - ch / 2) / SCALE)
        dj_def = b2DistanceJointDef(
            bodyA=self.person.torso.body,
            bodyB=self.chassis_body,
            anchorA=anchor_person,
            anchorB=anchor_car,
            frequencyHz=PERSON_CHASSIS_DIST_JOINT_FREQ,
            dampingRatio=PERSON_CHASSIS_DIST_JOINT_DAMP,
        )
        dj_def.length *= PERSON_CHASSIS_LENGTH_MULTIPLIER
        self.dist_joint = world.CreateJoint(dj_def)

    # ----------------------------------------------------------------
    def _add_polygon_fixture(self, vertices_px, *, density, friction, restitution):
        verts = [(vx / SCALE, vy / SCALE) for vx, vy in vertices_px]
        self.chassis_body.CreateFixture(
            b2FixtureDef(
                shape=b2PolygonShape(vertices=verts),
                density=density,
                friction=friction,
                restitution=restitution,
                filter=b2Filter(categoryBits=CHASSIS_CATEGORY, maskBits=CHASSIS_MASK),
            )
        )

    # ----------------------------------------------------------------
    def motor_on(self, forward: bool) -> None:
        # In Car.js: forward → wheel motors at -motor_speed (Box2D's revolute motor
        # spins toward positive angle, but the wheels are attached to the rim and the
        # whole thing is mirrored). We replicate the JS sign convention verbatim.
        sign = -1.0 if forward else 1.0
        # wheels[0] is the BACK wheel (drive) — gets the higher torque, like JS
        self.wheels[0].set_motor(sign * MOTOR_SPEED, MOTOR_TORQUE_REAR)
        self.wheels[1].set_motor(sign * MOTOR_SPEED, MOTOR_TORQUE_FRONT)

        old_state = self.motor_state
        self.motor_state = 1 if forward else -1

        if forward:
            self.chassis_body.ApplyTorque(-ROTATION_TORQUE, True)

        # Car.js: extra torque kick when reversing direction (oldState + new == 0).
        # JS literal: applyTorque(motorState * -1)  →  ApplyTorque((motorState*-1) * rotationTorque)
        if old_state + self.motor_state == 0 and old_state == 1:
            self.chassis_body.ApplyTorque(self.motor_state * -1 * ROTATION_TORQUE, True)

    def motor_off(self) -> None:
        if self.motor_state == 1:
            self.chassis_body.ApplyTorque(ROTATION_TORQUE * self.motor_state, True)
        self.motor_state = 0
        for w in self.wheels:
            w.disable_motor()

    # ----------------------------------------------------------------
    def motor_on_continuous(self, throttle: float) -> None:
        """Continuous-action analogue of motor_on / motor_off.

        throttle in [-1, +1]. Sign picks direction (positive=forward, like
        Discrete action 0); magnitude scales the max motor torque. A
        deadband of |throttle| < 0.1 is treated as "off" so SAC can express
        intentional coasting without having to land exactly on 0.

        Mirrors motor_on()'s chassis-torque kick + direction-reversal kick
        so transient behavior matches the discrete version.
        """
        if abs(throttle) < 0.1:
            self.motor_off()
            return

        forward = throttle > 0
        scale = min(1.0, abs(throttle))
        sign = -1.0 if forward else 1.0
        self.wheels[0].set_motor(sign * MOTOR_SPEED, MOTOR_TORQUE_REAR * scale)
        self.wheels[1].set_motor(sign * MOTOR_SPEED, MOTOR_TORQUE_FRONT * scale)

        old_state = self.motor_state
        self.motor_state = 1 if forward else -1

        if forward:
            self.chassis_body.ApplyTorque(-ROTATION_TORQUE * scale, True)

        if old_state + self.motor_state == 0 and old_state == 1:
            self.chassis_body.ApplyTorque(self.motor_state * -1 * ROTATION_TORQUE, True)

    # ----------------------------------------------------------------
    def update(self, canvas_height_px: float) -> None:
        x_px = self.chassis_body.position.x * SCALE
        y_px = self.chassis_body.position.y * SCALE
        self.change_count += 1

        if x_px > self.max_distance:
            self.max_distance = x_px
            if int(self.max_distance) % 50 == 0:
                self.change_count = 0
        elif self.change_count > 500 and not self.dead:
            # No-progress timeout — JS Car.js used 250 (~8s), but that's
            # too strict for trickier inclines where backing up + retry
            # genuinely takes ~10s. 500 (~16.7s at 30 FPS) gives room for
            # retry attempts while still killing the truly-stuck.
            self.dead = True

        # Falling off the bottom of the canvas kills the car
        if not self.dead and y_px > canvas_height_px:
            self.dead = True

    def destroy(self) -> None:
        """Tear down all joints + bodies safely.

        Order matters with pybox2d 2.3:
          1) Explicitly destroy every joint we own — relying on Box2D's
             auto-joint-destruction when a body is destroyed has segfaulted
             in practice (chassis has 4 wheel-suspension joints + many
             active ground contacts; the combined unwind crashed).
          2) Zero each body's velocity so any pending CCD / TOI computation
             can't try to integrate a freed body.
          3) Destroy bodies leaf-first (head, torso, rim bodies, wheel
             bodies, chassis last). The chassis touches the most contacts
             and has the most fixtures, so we want it destroyed when
             nothing else still references it.
        """
        # --- joints first ---
        joint_attrs = [
            (self, "dist_joint"),
            (self, "rev_joint"),
            (self.person, "dist_joint"),
            (self.person, "head_joint"),
        ]
        for wheel in self.wheels:
            joint_attrs.append((wheel, "wheel_joint"))
        for owner, attr in joint_attrs:
            j = getattr(owner, attr, None)
            if j is not None:
                try:
                    self.world.DestroyJoint(j)
                except Exception:
                    pass
                setattr(owner, attr, None)

        # --- zero velocities so no body is mid-integration when freed ---
        bodies = [
            self.person.head.body,
            self.person.torso.body,
            self.wheels[0].body,
            self.wheels[1].body,
            self.chassis_body,
        ]
        for body in bodies:
            try:
                body.linearVelocity = (0.0, 0.0)
                body.angularVelocity = 0.0
            except Exception:
                pass

        # --- bodies last, leaf-first (chassis is the most-connected, destroy it last) ---
        for body in bodies:
            try:
                self.world.DestroyBody(body)
            except Exception:
                pass
