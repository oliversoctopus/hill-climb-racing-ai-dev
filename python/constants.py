"""Live geometry / environment constants for the JS-backed env.

These are the Python-side constants the training / eval path consumes (obs,
terrain generation, spawn, camera). They match the JS game 1:1.

The actual PHYSICS parameters (body densities/frictions, motor torques, joint
freqs, damping, gravity, solver iterations, collision categories) are NOT here —
they live in the JS source (web/*.js + js_backend.py's polyfills), which both the
browser and training read directly. js_backend.py is the single source for those.
(The old pybox2d-tuned copies + the pybox2d port were removed 2026-07-07.)

Convention: (x, y) with y growing downward, gravity (0, +10) — matches the JS game.
Units: pixels for terrain/geometry; SCALE px per Box2D meter. See CONVENTIONS.md #1.
"""

SCALE = 30.0  # pixels per Box2D meter

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
FRAME_RATE = 30

# ---- Car DIMENSIONS (Car.js geometry; used by obs + the backtrack ghost render) ----
CHASSIS_WIDTH = 125
CHASSIS_HEIGHT = 40

# ---- Ground / terrain generation (Ground.js) ----
GROUND_SMOOTHNESS = 15               # px between vertices
GROUND_GRASS_THICKNESS = 5           # px; grass edges offset upward by this/SCALE
GROUND_DISTANCE = 15 * CANVAS_WIDTH  # 19200 px
GROUND_DIFFICULTY = 50

# "Completion" = reaching the last SOLID terrain vertex (the launch lip) — the true
# end of the track (score ~1883). Single source for every completion check.
# NOTE: earlier code used softer lines (GROUND_DISTANCE-950 → score 1790, or -350 →
# 1850) that UNDER-counted the track; those are retired (fixed 2026-07-07). Completion
# %s measured against the old lines are NOT comparable to this (stricter) definition.
LAST_VERTEX_PX = GROUND_DISTANCE - GROUND_SMOOTHNESS   # 19185 px
COMPLETE_PX = LAST_VERTEX_PX

# ---- Spawn (sketch.js Player.addToWorld: new Car(350, spawningY, ...)) ----
SPAWN_X = 350
SPAWN_Y_BACK_FROM_GROUND = 100       # spawningY = vectors[10].y - 100 (set at gen time)
SPAWN_VECTOR_INDEX = 10
