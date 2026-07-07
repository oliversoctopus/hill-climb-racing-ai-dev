"""Box2D world wrapper + contact listener (mirrors sketch.js listener.BeginContact / EndContact).

Two key behaviors:
  * head ↔ ground contact: destroy the four joints that hold the car together
    (chassis-person distance, person-internal distance, person-chassis revolute,
    head-torso revolute). The car splits into floppy pieces — this is the
    "death" trigger in the JS game.
  * wheel ↔ ground contact: toggle `wheel.on_ground`. Used as a vision input
    so the AI knows when it's airborne.

The JS contact listener checks `id == "head"` / `id == "ground"` etc. on the
fixture user data. We mirror that with our own `{"id": "head"|"wheel"|"ground"|...}`
user-data dicts attached to each body.
"""

from __future__ import annotations

from Box2D import b2World, b2ContactListener, b2Vec2

from constants import GRAVITY, PHYSICS_DT, VEL_ITERS, POS_ITERS, PHYSICS_SUBSTEPS


def _id_of(body) -> str:
    ud = body.userData
    if isinstance(ud, dict):
        return ud.get("id", "")
    return ""


def _owner_of(body):
    ud = body.userData
    if isinstance(ud, dict):
        return ud.get("owner")
    return None


class HillClimbContactListener(b2ContactListener):
    """Listener installed on the b2World."""

    def __init__(self):
        super().__init__()
        self._pending_joint_destroys = []
        self._pending_kills = []  # list of cars that just died this step
        self._killed_ids: set[int] = set()  # cars we've already destructed; never touch again

    # ----------------------------------------------------------------
    def BeginContact(self, contact):
        body_a = contact.fixtureA.body
        body_b = contact.fixtureB.body
        id_a = _id_of(body_a)
        id_b = _id_of(body_b)

        # ---- head ↔ ground: kill ----
        head_body = None
        if id_a == "head" and id_b == "ground":
            head_body = body_a
        elif id_b == "head" and id_a == "ground":
            head_body = body_b
        if head_body is not None:
            head_owner = _owner_of(head_body)  # Head instance
            if head_owner is None:
                return
            # Walk: head -> head_joint.other = torso; torso -> rev_joint.other = chassis (Car)
            jl = head_body.joints
            if not jl:
                return
            torso_body = jl[0].other
            tjl = torso_body.joints
            car = None
            for je in tjl:
                other = je.other
                ou = _owner_of(other)
                if ou is not None and getattr(ou, "wheels", None) is not None:
                    car = ou
                    break
            if car is None:
                return
            if id(car) in self._killed_ids:
                return  # already queued/destroyed; never touch again
            self._killed_ids.add(id(car))
            self._pending_joint_destroys.append(car)

        # ---- wheel ↔ ground: on_ground = True ----
        wheel_body = None
        if id_a == "wheel" and id_b == "ground":
            wheel_body = body_a
        elif id_b == "wheel" and id_a == "ground":
            wheel_body = body_b
        if wheel_body is not None:
            wheel = _owner_of(wheel_body)
            if wheel is not None:
                wheel.on_ground = True

    def EndContact(self, contact):
        body_a = contact.fixtureA.body
        body_b = contact.fixtureB.body
        id_a = _id_of(body_a)
        id_b = _id_of(body_b)

        wheel_body = None
        if id_a == "wheel" and id_b == "ground":
            wheel_body = body_a
        elif id_b == "wheel" and id_a == "ground":
            wheel_body = body_b
        if wheel_body is not None:
            wheel = _owner_of(wheel_body)
            if wheel is not None:
                wheel.on_ground = False

    # ----------------------------------------------------------------
    def drain_pending(self, world: b2World):
        """Run after world.Step(): destroy queued joints + mark cars dead.

        Each joint is destroyed at most once. After we destroy a joint we
        null its attribute, so future drains can't re-pass a stale pointer
        to DestroyJoint (which segfaults in pybox2d).
        """
        for car in self._pending_joint_destroys:
            for attr in ("dist_joint", "rev_joint"):
                j = getattr(car, attr, None)
                if j is not None:
                    try:
                        world.DestroyJoint(j)
                    except Exception:
                        pass
                    setattr(car, attr, None)
            for attr in ("dist_joint", "head_joint"):
                j = getattr(car.person, attr, None)
                if j is not None:
                    try:
                        world.DestroyJoint(j)
                    except Exception:
                        pass
                    setattr(car.person, attr, None)
            car.dead = True
            self._pending_kills.append(car)
        self._pending_joint_destroys.clear()


def make_world() -> tuple[b2World, HillClimbContactListener]:
    world = b2World(gravity=b2Vec2(*GRAVITY), doSleep=True)
    listener = HillClimbContactListener()
    world.contactListener = listener
    return world, listener


def step_world(world: b2World, listener: HillClimbContactListener) -> None:
    """One game-tick: PHYSICS_SUBSTEPS Box2D steps at dt/N, then a single
    drain_pending at the end.

    Joints are NOT destroyed inside the substep loop — destroying mid-tick
    leaves the rest of the substeps simulating a car with a half-broken
    constraint graph, which crashes pybox2d. Drain once when the tick is done."""
    sub_dt = PHYSICS_DT / PHYSICS_SUBSTEPS
    for _ in range(PHYSICS_SUBSTEPS):
        world.Step(sub_dt, VEL_ITERS, POS_ITERS)
        world.ClearForces()
    listener.drain_pending(world)
