"""Physics / geometry constants. TWO groups (see the banner further down):

  * LIVE — consumed by the JS-backed env / ground / obs path: SCALE, canvas &
    frame rate, spawn, chassis + wheel DIMENSIONS, GROUND_*, collision categories.
    These match the JS source 1:1.
  * LEGACY pybox2d tuning — body densities/frictions/damping, motor torques and
    joint freqs. Empirically tuned for the RETIRED pybox2d port; NOT used by the
    live path (the JS physics reads its own values from web/*.js). They
    deliberately DIVERGE from JS (see the per-line 'JS:' notes) and are kept only
    for legacy_pybox2d. See CONVENTIONS.md #8.

Convention: (x, y) with y growing downward, gravity (0, +10) (matches the JS game).
"""

import math

SCALE = 30.0  # pixels per Box2D meter (sketch.js)

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
FRAME_RATE = 30
PHYSICS_DT = 1.0 / 30.0
VEL_ITERS = 10
POS_ITERS = 10

# JS does one Step(1/30, 10, 10) per game-tick — we match that exactly.
# An earlier version substepped 2× internally to make the wheel suspension
# (freq=70) reach its requested stiffness in Box2D 2.3's solver, but that
# also doubled how often ground friction iterates per tick, which added
# grip and changed the bouncing/acceleration feel. Match JS-exact instead;
# residual softness vs JS is pure Box2D 2.0 → 2.3 version drift.
PHYSICS_SUBSTEPS = 1

GRAVITY = (0.0, 10.0)  # sketch.js: new Vec2(0, 10)

# ---- Collision categories / masks (sketch.js) ----
WHEEL_CATEGORY = 0x0001
CHASSIS_CATEGORY = 0x0002
GRASS_CATEGORY = 0x0004
DIRT_CATEGORY = 0x0008
PERSON_CATEGORY = 0x0010

WHEEL_MASK = GRASS_CATEGORY
CHASSIS_MASK = DIRT_CATEGORY
GRASS_MASK = WHEEL_CATEGORY | PERSON_CATEGORY
DIRT_MASK = CHASSIS_CATEGORY
PERSON_MASK = GRASS_CATEGORY

# ----------------------------------------------------------------------
# LEGACY pybox2d tuning (NOT used by the live JS-backed path)
# ----------------------------------------------------------------------
# The body densities/frictions/damping, motor torques and joint freqs below were
# tuned empirically for the RETIRED pybox2d port (scipy.optimize matching a JS
# reference trace; see legacy_pybox2d/tune.py). The LIVE path runs the real JS
# physics (js_backend.py loads web/*.js), which reads its own values — so these
# tuned numbers are DEAD for training/eval and deliberately diverge from JS (see
# each 'JS:' note). Only legacy_pybox2d consumes them. CONVENTIONS.md #8.
#
# EXCEPTION — the plain DIMENSIONS in this block are still LIVE: CHASSIS_WIDTH,
# CHASSIS_HEIGHT (obs + backtrack render), WHEEL_SIZE, PERSON_WIDTH, PERSON_HEIGHT.

# ---- Chassis (Car.js) ----
CHASSIS_WIDTH = 125
CHASSIS_HEIGHT = 40
WHEEL_SIZE = 17  # radius (px)
CHASSIS_DENSITY = 1.0
CHASSIS_FRICTION = 0.5
CHASSIS_RESTITUTION = 0.01
CHASSIS_ANGULAR_DAMPING = 0.11   # JS: 0.1   (multi-scenario+controller optimum ≈ JS)
CHASSIS_LINEAR_DAMPING = 0.05    # JS: 0     (multi-scenario+controller optimum)
CHASSIS_BUMPER_FRICTION = 0.1    # the 3rd fixture (bumper) is 0.1 / 0.1
CHASSIS_BUMPER_RESTITUTION = 0.1
ROTATION_TORQUE = 2.0

# ---- Motor (Car.js) ----
MOTOR_SPEED = 13.0 * math.pi     # rad/s
MOTOR_TORQUE_REAR = 1023.0       # JS: 700.0  (multi-scenario+controller optimum)
MOTOR_TORQUE_FRONT = 530.0       # JS: 350.0  (multi-scenario+controller optimum)

# ---- Wheel rolling body (Wheel.js createBody) ----
WHEEL_BODY_DENSITY = 1.0
WHEEL_BODY_FRICTION = 0.52       # JS: 1.5    — Box2D 2.0 effectively capped friction near ~1.0; multi-scenario+controller optimum
WHEEL_BODY_RESTITUTION = 0.1
WHEEL_BODY_ANGULAR_DAMPING = 1.90  # JS: 1.8   (1.8 + 0.10 extra, close to JS now that controller scenarios capture real dynamics)

# ---- Wheel rim body (Wheel.js constructor body 2) ----
WHEEL_RIM_DENSITY = 0.2          # JS: 0.05  — JS's 20x-lighter rim caused a bad mass ratio at
                                 # the prismatic joint so the solver couldn't hold the wheel
                                 # on-axis during hard impacts (back wheel slipped >1m along
                                 # chassis-x at spawn). Raising rim density tightens the
                                 # constraint; rim=1.0 fully fixed drift but the chassis
                                 # couldn't move (wheelspin without traction). 0.2 is the
                                 # measured sweet spot: best forward travel of any density
                                 # tested and ~half the drift of the JS value.
WHEEL_RIM_FRICTION = 0.99
WHEEL_RIM_RESTITUTION = 0.2

# Wheel suspension (b2WheelJoint spring): the original two-body-three-joint design
# was structurally unstable in Box2D 2.3 due to a 20:1 mass ratio between the rim
# (density 0.05) and chassis (density 1.0) — measured >1m horizontal wheel drift
# under spawn impact. Switched to b2WheelJoint, which connects the rolling wheel
# directly to the chassis with a purpose-built suspension joint (axis + spring +
# motor in one) and has no mass-ratio failure mode. After that refactor the JS
# freq/damp values converge to within a few percent of JS in the auto-tuner.
WHEEL_DIST_JOINT_FREQ = 6.0      # JS: 70.0  — tuner picked 59 to match JS trajectories, but
                                 # that put the spring at ~2 oscillations per tick which the
                                 # solver couldn't enforce cleanly (wheels drifted horizontally).
                                 # 6 Hz is the standard b2WheelJoint car-suspension band: the
                                 # wheel now visibly compresses + rebounds, and the constraint
                                 # solver has no trouble keeping it on its axis.
WHEEL_DIST_JOINT_DAMP = 0.8      # JS: 25.0  — JS value was dampingRatio=25 (26× past critical),
                                 # which made the suspension behave like a rigid rod in honey:
                                 # no spring action, no bounce. 0.8 is slightly under critical
                                 # damping — standard car-suspension feel.

# ---- Person (Person.js) ----
PERSON_WIDTH = 15
PERSON_HEIGHT = 30
HEAD_DENSITY = 0.001
HEAD_FRICTION = 0.01
HEAD_RESTITUTION = 0.01
TORSO_DENSITY = 0.002
TORSO_FRICTION = 0.01
TORSO_RESTITUTION = 0.01

# Person-chassis joint (Car.js)
PERSON_CHASSIS_DIST_JOINT_FREQ = 5.0
PERSON_CHASSIS_DIST_JOINT_DAMP = 0.1
PERSON_CHASSIS_LENGTH_MULTIPLIER = 1.1

# ---- Ground (Ground.js) ----
GROUND_FRICTION = 0.99
GROUND_RESTITUTION = 0.1
GROUND_SMOOTHNESS = 15  # px between vectors
GROUND_GRASS_THICKNESS = 5  # px; grass edges offset upward by this/SCALE
GROUND_DISTANCE = 15 * CANVAS_WIDTH  # 19200 px
GROUND_DIFFICULTY = 50

# Spawn x (sketch.js Player.addToWorld: new Car(350, spawningY, ...))
SPAWN_X = 350
# spawningY = vectors[10].y - 100  (set during ground generation)
SPAWN_Y_BACK_FROM_GROUND = 100
SPAWN_VECTOR_INDEX = 10
