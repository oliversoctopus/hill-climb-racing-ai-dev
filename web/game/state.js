// Shared mutable game state + tuning constants for the browser app.
//
// Why one `S` object instead of module-level `let`s: nearly every concern
// (sim, render, cheats, search, input) both READS and WRITES this state, and ES
// module imports are read-only to the importer. Routing it all through one
// imported object lets any module mutate `S.world = ...` etc. without a setter
// per field. Everything here started life as a top-level `var` in the old
// index.html monolith; it is now `export const` (the object binding is const,
// its fields mutate freely).

// --- Physics/geometry constants (single-sourced in the index.html compat shim,
// which the physics classes read as globals; we re-export them so modules can
// import explicitly rather than reach for bare globals). ---
export const SCALE = window.SCALE;                 // px per meter (30)
export const SPAWN_X = window.SPAWN_X;             // canonical spawn x, px (350)
export const CANVAS_WIDTH = window.CANVAS_WIDTH;   // one screen, px (1280)
export const CANVAS_HEIGHT = window.CANVAS_HEIGHT; // px (720); also the fall-off kill line

// Physics step rate. Box2D wants a fixed timestep; the loop paces to it.
export const FRAME_RATE = 30;
export const SIM_DT = 1.0 / FRAME_RATE;

// AI no-progress timeout — matches python/env.py:244 (the agent trained against it).
export const STUCK_TIMEOUT_TICKS = 500;

// Natural fly-off window, from leaving the terrain edge: distance gained within it is the
// "fly-off" part of a score, anything later is "after fly-off" (cheats only). Measured
// 2026-09-29: deployed AI fly-offs 0.8–2.0 s (median 1.6, n=15); analytic worst case over
// 400 maps (highest lip, motor top speed launched up the steepest final ramp) 4.7 s.
export const FLYOFF_GRACE_SEC = 5;
export const FLYOFF_GRACE_TICKS = FLYOFF_GRACE_SEC * FRAME_RATE;
// Gold "legendary fly-off" marker (clean runs only): fly-off distance, in score points.
// 90 ≈ a score of ~1973 on a normal map — the best human launch in ~500 focused tries.
export const LEGENDARY_FLYOFF = 90;

// --- Player colors ---
export const AI_COLOR    = { outline: "#5cf", torso: "#3c5ac8", shirtR: 80,  shirtG: 120, shirtB: 200 };
export const HUMAN_COLOR = { outline: "#fc5", torso: "#c8783c", shirtR: 200, shirtG: 120, shirtB: 60  };
// Human-vs-Human: left car (WASD) orange, right car (arrows) green — kept visually
// distinct so each player can spot both cars on the shared terrain.
export const HUMAN_L_COLOR = HUMAN_COLOR;
export const HUMAN_R_COLOR = { outline: "#6f6", torso: "#2f8f2f", shirtR: 90, shirtG: 190, shirtB: 90 };
// Dev mode's second AI ("AI B" in AI vs AI).
export const AI2_COLOR = { outline: "#e8f", torso: "#9a3cc8", shirtR: 170, shirtG: 80, shirtB: 200 };

// --- Cheat / bug-probe tuning ---
export const BP_MAX_LEN = 12000;   // ring-buffer cap (~6.7 min at 30 fps)
export const FLIGHT_SPEED_MIN = 0, FLIGHT_SPEED_MAX = 300;
// Scroll increments: FLIGHT_SPEED_STEP up to FLIGHT_SPEED_STEP_BREAK, then _HI beyond it.
export const FLIGHT_SPEED_STEP = 5, FLIGHT_SPEED_STEP_HI = 10, FLIGHT_SPEED_STEP_BREAK = 100;
export const FLIGHT_ROT_RATE = 2.0;   // spin rate (rad/s) while rotate held
export const FLIGHT_ROT_DAMP = 0.90;  // per-tick angular damping when NOT rotating
export const ROCKET_ACCEL_MIN = 5, ROCKET_ACCEL_MAX = 120, ROCKET_ACCEL_STEP = 5;
export const ROCKET_ROT_RATE = 2.0;
export const ROCKET_ROT_DAMP = 0.90;
export const ROCKET_LIN_DAMP = 0.99;  // per-tick linear drag so thrust settles at a terminal speed

export const MAX_SESSION_TERRAINS = 30;

// --- The single mutable state object ---
export const S = {
  // core simulation
  world: null,
  ground: null,
  listener: null,
  players: [],            // array of player records (see sim.makePlayer)
  tickCount: 0,
  paused: false,
  simSpeed: 1,            // set via the Speed dropdown or Shift+Scroll
  aiAgent: null,          // Agent instance from ai_policy.js (PpoOnnxAgent by default)
  aiAgent2: null,         // dev mode: "AI B" (its own instance — agents hold per-episode state)
  mode: "ai",             // key into modes.MODES

  // Best of X + replay
  storedGround: null,     // canonical map cloned into each attempt's fresh world
  storedSpawningY: 0,
  bestofxRuns: [],        // [{ attempt, distance, score, actions:[int], spawnDx, spawnDy }]
  bestofxAbort: false,
  replayActions: null,    // non-null => feed recorded actions instead of the model
  replayIdx: 0,
  bestofxBusy: false,     // guards the RAF loop while a headless loop owns the world
  worldGen: 0,            // bumped on every world rebuild; in-flight steps bail if it changed

  // Loaded track + ghost replay
  loadedTrack: null,
  ghostPoses: null,       // non-null => ghost replay mode (per-tick poses, meters)
  ghostIdx: -1,
  ghostDims: null,
  ghostScore: 0,
  ghostDone: false,
  ghostBeaten: true,      // false => a "best run" that did NOT beat the game
  backtrackAbort: false,

  // Camera (published into cameraPanX/Y right before each viewport draws)
  cameraPanX: 0,
  cameraPanY: 0,
  // panX/panY = current pan; lastTargetX/Y = previous frame's target, for the camera's
  // velocity feed-forward (see render._followCamera).
  cam0: { panX: 0, panY: 0, lastTargetX: 0, lastTargetY: 0 },   // single-view modes
  camL: { panX: 0, panY: 0, lastTargetX: 0, lastTargetY: 0 },   // Human-vs-Human left half
  camR: { panX: 0, panY: 0, lastTargetX: 0, lastTargetY: 0 },   // Human-vs-Human right half

  // Human input (held by keyboard listeners). Two control sets so two humans can
  // race on one keyboard. Semantics match the AI action space (right=forward).
  humanKeys:     { left: false, right: false },  // arrows -> right screen / lone human
  humanKeysWASD: { left: false, right: false },  // A/D (or S/W) -> left screen
  flyKeysWASD:   { fwd: false, back: false, rotL: false, rotR: false },
  flyKeysArrows: { fwd: false, back: false, rotL: false, rotR: false },

  // Bug probe / cheats
  bpRecord: [],           // ring buffer of per-tick human-car snapshots
  bpFlags: [],            // user-set markers {tick, idx}
  bpZeroG: false,
  bpSavedGravity: null,
  bpInvincible: false,    // skip head-ground / fell-off / no-progress death
  bpAltimeter: false,     // live height-above-ground readout
  bpSpeed: false,         // live speed readout
  bpDistance: false,      // live current-position score readout, under the player score (C)
  bpFlight: false,        // constant-velocity hover cheat (G)
  bpRocket: false,        // thrust cheat (J)
  bpReverse: false,       // reversed movement controls cheat (K)
  flightSpeed: 20,        // m/s, scroll-adjustable
  rocketAccel: 20,        // m/s^2, scroll-adjustable

  // Dev mode (see dev.js)
  devMode: false,         // unlocked with the password
  devVision: false,       // AI-vision overlay
  devB2D: false,          // Box2D debug draw
  inStep: false,          // a runOneStep is in flight (dev frame-step must not overlap it)

  // Loop timing
  accumSec: 0,
  lastWallMs: 0,

  // Session terrains (re-loadable from the Terrains menu)
  sessionTerrains: [],
  terrainCounter: 0,
  currentTerrainName: "",   // name shown in the "current terrain" box (Terrain N, or a loaded name)
  currentTerrainUnsaved: false,   // true => current map's saved copy was deleted; box shows "(unsaved)"

  // Records (see records.js)
  mapKey: "",               // geometry hash of the current map
  runTainted: false,        // a cheat / slow-mo was used this run → don't record it
  runModified: false,       // a physics-changing cheat was used this run (slow-mo excluded)
  recStart: null,           // { map, global } records as they stood when the run began
  bpPhysModified: false,    // debug physics/motor knobs are off their defaults

  // Image assets (loaded once at init)
  assets: {},
};
