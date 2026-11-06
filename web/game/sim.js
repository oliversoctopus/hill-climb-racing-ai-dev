// Simulation core: world/terrain/car construction, the per-tick step, death
// checks, and the small vehicle-geometry helpers the rest of the app shares.
import {
  S, SCALE, SPAWN_X, FRAME_RATE, SIM_DT, MAX_SESSION_TERRAINS, FLYOFF_GRACE_TICKS,
} from "./state.js";
import {
  Car, Ground, Box2D, Vec2, b2World, b2StaticBody, perlinSeed,
  getSpawningY, setSpawningY,
} from "./bridge.js";
import { modeDef, spawnColor } from "./modes.js";
import { isBelowKillLine } from "./geom.js";
import { T, tuneTick, tuneGroundPre, tuneGroundPost, terrainTuned, syncGroundDims,
         tuneOnBuild } from "./tune.js";
import { humanAction, humanActionWASD, humanActionAny } from "./input.js";
import { recordTick, applyFlyCheats, bpSetZeroG,
         bpSyncExitButton } from "./cheats.js";
import { mapKeyOf, mapRecord, mapRecordAll, globalRecord, commitRun, cheatsActive, physicsModified, refreshRecordsStrip,
         recordMapLabel } from "./records.js";
import { hrAction, hrAfterTick, hrFinish } from "./humanruns.js";

// ---- Score metric --------------------------------------------------------
// Project score: (max forward px − spawn) / 10, floored, >= 0. Matches eval.py
// and Code Bullet's Player.js. `scorePx` takes a raw x in px; `scoreOf` a player.
export function scorePx(px) { return Math.max(0, Math.floor((px - SPAWN_X) / 10)); }
export function scoreOf(p) { return scorePx(p.maxDistPx); }
// A finished run's score split three ways: up to the finish line (what the finish time
// measures), the natural fly-off (until FLYOFF_GRACE after leaving the terrain), and anything
// after that (only cheats get there — a clean car is dead by then). Null if unfinished.
// Floored differences, so the parts always sum to the score.
export function scoreParts(p) {
  if (!p.beatTick) return null;
  const total = scoreOf(p), toFinish = Math.min(total, scorePx(p.finishLinePx));
  const graceEnd = p.graceEndPx != null ? scorePx(p.graceEndPx) : total;
  // Airborne time off the edge, until death or the end of the window (0 = never left the lip).
  const endTick = Math.min(p.deadTick || S.tickCount, p.leftLipTick + FLYOFF_GRACE_TICKS);
  const flyoffSec = p.leftLipTick ? Math.max(0, endTick - p.leftLipTick) / FRAME_RATE : 0;
  return { toFinish, flyoff: graceEnd - toFinish, after: total - graceEnd, flyoffSec };
}
// Signed current-position distance (score units), NOT clamped at 0 — so driving or
// teleporting behind the spawn line reads negative. Only the live Distance readout uses
// this; the canonical Score (scoreOf) stays floored at 0.
export function distancePx(px) { return Math.floor((px - SPAWN_X) / 10); }
// Current-position score: like scoreOf but from the car's CURRENT x, not its high-water
// mark (p.maxDistPx) — so it drops (and can go negative) when the car rolls back behind
// spawn. Falls back to the stored max when there's no live car.
export function curScoreOf(p) {
  if (p && p.car && p.car.chassisBody) return distancePx(p.car.chassisBody.GetPosition().x * SCALE);
  return scoreOf(p);
}

// ---- Vehicle geometry helpers -------------------------------------------
// Every dynamic body that makes up the vehicle, guarded so a partially-built or
// frozen car doesn't throw. (Car.bodies() is the un-guarded fast path used where
// the car is known-complete; this defensive version backs the readout cheats.)
export function _vehicleBodies(car) {
  const bodies = [];
  if (!car) return bodies;
  if (car.chassisBody) bodies.push(car.chassisBody);
  if (car.wheels) for (let wi = 0; wi < car.wheels.length; wi++) {
    const w = car.wheels[wi]; if (!w) continue;
    if (w.body) bodies.push(w.body);
    if (w.rimBody) bodies.push(w.rimBody);
  }
  if (car.person) {
    if (car.person.torso && car.person.torso.body) bodies.push(car.person.torso.body);
    if (car.person.head && car.person.head.body) bodies.push(car.person.head.body);
  }
  return bodies;
}
// Whole-vehicle center of mass in world meters (mass-weighted mean of every body's
// own CoM). A fixed point in the vehicle frame, so unlike the chassis origin it does
// NOT orbit/wobble as the car spins — the right anchor for the readouts.
export function _vehicleCoM(car) {
  const bodies = _vehicleBodies(car);
  let mx = 0;
  let my = 0;
  let mtot = 0;
  for (let i = 0; i < bodies.length; i++) {
    const m = bodies[i].GetMass(); if (!(m > 0)) continue;
    const c = bodies[i].GetWorldCenter();
    mx += m * c.x; my += m * c.y; mtot += m;
  }
  if (mtot <= 0) { const p = car.chassisBody.GetPosition(); return { x: p.x, y: p.y }; }
  return { x: mx / mtot, y: my / mtot };
}
// Snapshot a car's draw pose (meters) + whole-vehicle CoM for the ghost replay.
export function capturePose(car) {
  function wp(b) { const q = b.GetPosition(); return { x: q.x, y: q.y, angle: b.GetAngle() }; }
  return { chassis: wp(car.chassisBody),
           wheels: [wp(car.wheels[0].body), wp(car.wheels[1].body)],
           torso: wp(car.person.torso.body), head: wp(car.person.head.body),
           com: _vehicleCoM(car),   // whole-vehicle CoM so replay readouts don't wobble
           dead: !!car.player.kindaDead };
}

// ---- Contact listener ----------------------------------------------------
export function makeContactListener(w) {
  const L = new Box2D.Dynamics.b2ContactListener;
  L.BeginContact = contact => {
    const udA = contact.GetFixtureA().GetBody().GetUserData();
    const udB = contact.GetFixtureB().GetBody().GetUserData();
    if (!udA || !udB) return;

    function killViaHead(headBody) {
      if (S.bpInvincible || !T.headKills) return;   // cheat / playground rule: head hits don't kill
      if (headBody.GetJointList() == null) return;
      const c = headBody.GetJointList().other.GetJointList().other.GetUserData();
      if (!c) return;
      try { w.DestroyJoint(c.distJoint); } catch(e) {}
      try { w.DestroyJoint(c.person.distJoint); } catch(e) {}
      try { w.DestroyJoint(c.revJoint); } catch(e) {}
      try { w.DestroyJoint(c.person.headJoint); } catch(e) {}
      if (c.player) c.player.kindaDead = true;
    }
    if (udA.id == "head" && udB.id == "ground") killViaHead(contact.GetFixtureA().GetBody());
    if (udB.id == "head" && udA.id == "ground") killViaHead(contact.GetFixtureB().GetBody());
    if (udA.id == "wheel" && udB.id == "ground") udA.onGround = true;
    if (udB.id == "wheel" && udA.id == "ground") udB.onGround = true;
  };
  L.EndContact = contact => {
    const udA = contact.GetFixtureA().GetBody().GetUserData();
    const udB = contact.GetFixtureB().GetBody().GetUserData();
    if (!udA || !udB) return;
    if (udA.id == "wheel" && udB.id == "ground") udA.onGround = false;
    if (udB.id == "wheel" && udA.id == "ground") udB.onGround = false;
  };
  // Friction heat per tire for fx dust: tangent impulse x contact slip, averaged over
  // the step, since one step's friction can spin a skidding tire up to rolling speed.
  L.PreSolve = contact => {
    const s = _tireSlip(contact);
    if (s) contact._slipPre = s.v;
  };
  L.PostSolve = (contact, impulse) => {
    const s = _tireSlip(contact);
    if (!s) return;
    let j = 0;
    for (let i = 0; i < contact.GetManifold().m_pointCount; i++) j += Math.abs(impulse.tangentImpulses[i]);
    const pre = contact._slipPre ?? s.v;
    s.wheel.fxHeat = (s.wheel.fxHeat || 0) + j * (Math.abs(pre) + Math.abs(s.v)) / 2;
    s.wheel.fxHeatDir = (s.wheel.fxHeatDir || 0) + j * pre;   // sign = way the dirt flies
  };
  w.SetContactListener(L);
  return L;
}

// Tangential velocity (m/s, +x-ish = rightward) of a tire's contact patch over the
// ground, or null if the contact isn't tire-on-ground. Read-only: never touches physics.
const _wm = new Box2D.Collision.b2WorldManifold();
function _tireSlip(contact) {
  const bA = contact.GetFixtureA().GetBody(), bB = contact.GetFixtureB().GetBody();
  const udA = bA.GetUserData(), udB = bB.GetUserData();
  if (!udA || !udB) return null;
  let tire, sgn;
  if (udA.id == "wheel" && udB.id == "ground" && bA === udA.body) { tire = bA; sgn = 1; }
  else if (udB.id == "wheel" && udA.id == "ground" && bB === udB.body) { tire = bB; sgn = -1; }
  else return null;
  contact.GetWorldManifold(_wm);
  const nx = _wm.m_normal.x * sgn, ny = _wm.m_normal.y * sgn;   // tire centre -> ground
  const R = tire.GetUserData().radius / SCALE, om = tire.GetAngularVelocity();
  const v = tire.GetLinearVelocity();
  const px = v.x - om * R * ny, py = v.y + om * R * nx;   // v + omega x (R n)
  let tx = -ny, ty = nx;
  if (tx < 0) { tx = -tx; ty = -ty; }                      // orient tangent rightward
  return { wheel: tire.GetUserData(), v: px * tx + py * ty };
}

// ---- Players -------------------------------------------------------------
export function makePlayer(agent, color, xOffsetPx, yOffsetPx) {
  // xOffsetPx / yOffsetPx perturb spawn position in pixel units. Used by Best of X
  // to exploit Box2D's chaotic divergence: sub-pixel offsets are visually
  // imperceptible but amplify over seconds into very different trajectories, so X
  // attempts of a deterministic policy produce X different runs without stochastic
  // action sampling.
  const dx = xOffsetPx || 0;
  const dy = yOffsetPx || 0;
  const dummyPlayer = { shirtColorR: color.shirtR, shirtColorG: color.shirtG, shirtColorB: color.shirtB,
                      dead: false, kindaDead: false };
  const car = new Car(SPAWN_X + dx, getSpawningY() + dy, S.world, dummyPlayer);
  if (agent) agent.reset();   // clear any per-episode AI state
  return {
    car,
    agent,             // null = human; otherwise an Agent (see ai_policy.js)
    isAI: agent !== null,
    color,
    maxDistPx: car.chassisBody.GetPosition().x * SCALE,
    dead: false,
    // No-progress timeout state (AI only). Counter ticks up each step and resets
    // each time the car crosses a 50-px milestone. Matches python/env.py:244 — the
    // agent was trained against this gate. Humans aren't timed out.
    stuckCount: 0,
    // Tick at which this car first passed the finish (0 = hasn't beaten the game).
    // Human-vs-Human uses it to award the win to whoever beat the game first.
    beatTick: 0,
  };
}

// Freeze a car in place: make every body static so it holds its final pose instead
// of continuing to fall. Used ONLY when a car falls off the edge of the world —
// otherwise the camera chases it into the void and the screen fills with the
// (infinitely-tall) brown dirt polygon. The world itself can't stop (an opponent may
// still be racing in vs/hvh), so we stop just the fallen car.
export function freezeCar(car) {
  const bs = car.bodies();
  for (let i = 0; i < bs.length; i++) {
    try { bs[i].SetType(b2StaticBody); } catch (e) {}
  }
}

// One-place end-of-step bookkeeping shared by the live RAF loop and the Best of X
// headless loop. Updates max-distance + stuck counter, applies the head/fell-off
// death checks and the AI no-progress timeout. Returns true iff the player just died.
export function _checkPlayerEndOfStep(p) {
  if (p.dead) return false;
  const pos = p.car.chassisBody.GetPosition();
  const xpx = pos.x * SCALE;
  const ypx = pos.y * SCALE;
  p.stuckCount += 1;
  if (xpx > p.maxDistPx) {
    p.maxDistPx = xpx;
    // Reset on each 50-px milestone — same trigger as training (int(max_dist_px) %
    // 50 == 0). Math.floor matches Python's int() for positive values.
    if (Math.floor(p.maxDistPx) % 50 === 0) p.stuckCount = 0;
  }
  // Record the first step this car reaches the finish = the last solid terrain vertex
  // (distance - smoothness; the launch lip) — the same line as "completion" and what
  // the backtrack search calls "beating the game". Human-vs-Human awards the win to
  // whoever crosses FIRST (smallest beatTick).
  if (!p.beatTick && S.ground && p.maxDistPx >= S.ground.distance - S.ground.smoothness) {
    p.beatTick = S.tickCount;
    p.finishLinePx = S.ground.distance - S.ground.smoothness;
  }
  // Natural fly-off window: starts when the car leaves the terrain (passes the cliff edge
  // just past the finish line — a car can sit on the lip for a while first), lasts
  // FLYOFF_GRACE; distance after it is "after fly-off" (see scoreParts).
  if (p.beatTick && !p.leftLipTick && S.ground && p.maxDistPx > S.ground.distance) p.leftLipTick = S.tickCount;
  if (p.leftLipTick && p.graceEndPx == null && S.tickCount - p.leftLipTick >= FLYOFF_GRACE_TICKS) p.graceEndPx = p.maxDistPx;
  const fellOffWorld = !S.bpInvincible && isBelowKillLine(ypx);   // fell below the screen into the void
  if (!S.bpInvincible && (p.car.player.kindaDead || isBelowKillLine(ypx))) p.dead = true;
  if (p.isAI && !S.bpInvincible && p.stuckCount > T.aiStuckTicks) p.dead = true;
  if (p.dead) p.deadTick = S.tickCount;   // freezes the run timer
  // Freeze ONLY on a fall-off-the-world death: head-hit ragdolls stay on-screen and
  // are fine to keep tumbling, but a car that dropped off the edge would fall forever
  // and the camera would fill the screen with brown dirt. Inert in the backtrack
  // search/replay (btRoll returns on death and rebuilds; jsReplaySegments doesn't call this).
  if (p.dead && fellOffWorld) freezeCar(p.car);
  return p.dead;
}

// ---- Terrain generation --------------------------------------------------
// Generate a playable map: roll noise + randomize, rerolling until isTooSteep()
// accepts it — matching the real game (sketch.js:234), which loops UNBOUNDED. The
// gate rejects ~97% of raw maps (~33 rerolls avg), so it defines the game's terrain
// distribution. The 1000-cap is only a hang guard (P(hit) ~ 0.97^1000 ~ 1e-13).
// Returns the Ground (no world bodies built yet) and the global spawningY that
// randomizeGround() set. Pulling this out of buildWithGround lets Best of X generate
// ONE map and clone it into X separate worlds.
export function rollAcceptableGround() {
  const tmp = new b2World(new Vec2(0, 10), false);
  perlinSeed(Math.floor(Math.random() * 0x7FFFFFFF));
  let g = new Ground(tmp);
  tuneGroundPre(g);
  g.randomizeGround();
  let rerolls = 0;
  const cap = terrainTuned() ? 200 : 1000;   // odd spacings can fail the gate a lot
  while (g.isTooSteep() && rerolls < cap) {
    perlinSeed(Math.floor(Math.random() * 0x7FFFFFFF));
    g = new Ground(tmp);
    tuneGroundPre(g);
    g.randomizeGround();
    rerolls += 1;
  }
  tuneGroundPost(g);   // physics playground: hilliness + spawn height
  return { ground: g, spawningY: getSpawningY() };
}

// Build the players the current mode wants (see modes.MODES). Best of X passes a
// sub-pixel spawn jitter, applied to the (single) AI player.
function spawnPlayers(spawnDx, spawnDy) {
  const defs = modeDef(S.mode).spawn;
  const out = [];
  for (let i = 0; i < defs.length; i++) {
    const d = defs[i];
    if (d.agent === "ai2" && !S.aiAgent2) continue;   // AI B not loaded (dev mode off)
    const agent = (d.agent === "ai") ? S.aiAgent : (d.agent === "ai2") ? S.aiAgent2 : null;
    const dx = (d.agent === "ai") ? (spawnDx || 0) : 0;
    const dy = (d.agent === "ai") ? (spawnDy || 0) : 0;
    const p = makePlayer(agent, spawnColor(d), dx, dy);
    if (d.control) p.control = d.control;
    if (d.agent === "ai2") p.aiB = true;
    out.push(p);
  }
  return out;
}

// Build a fresh world with the players a given mode wants. If `sourceGround` is
// non-null, clones its vectors/grass instead of generating new terrain — used both
// for Best of X attempts and for replaying a recorded run. spawnDx/spawnDy perturb
// the AI spawn in pixels (Best of X only).
export function buildWithGround(sourceGround, sourceSpawningY, spawnDx, spawnDy) {
  S.worldGen += 1;  // invalidates any in-flight runOneStep awaiting from the old world
  // An abandoned human run (Restart/Regenerate mid-drive) still counts toward records.
  for (const p of S.players) if (!p.isAI && !p.dead) { commitRun(p, scoreOf(p), scoreParts(p), true); hrFinish(p, "abandoned"); }
  S.bpZeroG = false;  // fresh world has normal gravity; clear any stale float state
  S.world = new b2World(new Vec2(0, 10), false);
  S.listener = makeContactListener(S.world);
  if (sourceGround) {
    setSpawningY(sourceSpawningY);
    S.ground = new Ground(S.world);
    S.ground.cloneFrom(sourceGround);
    syncGroundDims(S.ground, sourceGround);
    S.ground.setBodies(S.world);
  } else {
    const roll = rollAcceptableGround();
    setSpawningY(roll.spawningY);
    S.ground = new Ground(S.world);
    S.ground.cloneFrom(roll.ground);
    syncGroundDims(S.ground, roll.ground);
    S.ground.setBodies(S.world);
    recordSessionTerrain();   // remember this fresh map for the Terrains dropdown
  }

  // Records: identify the map and snapshot the bests to beat for this run.
  S.mapKey = mapKeyOf(S.ground);
  S.runTainted = S.runModified = false;
  S.recStart = { map: mapRecord(S.mapKey), global: { ...globalRecord() }, all: { ...mapRecordAll(S.mapKey) } };
  refreshRecordsStrip();

  S.players = spawnPlayers(spawnDx, spawnDy);
  snapRenderPoses();   // seed the render-interpolation snapshots at the spawn pose

  S.tickCount = 0;
  S.cameraPanX = 0;
  S.cameraPanY = 0;
  // Reset pan AND the feed-forward's remembered target so a rebuild doesn't see a huge
  // phantom first-frame velocity (see render._followCamera).
  S.cam0.panX = S.cam0.panY = S.cam0.lastTargetX = S.cam0.lastTargetY = 0;
  S.camL.panX = S.camL.panY = S.camL.lastTargetX = S.camL.lastTargetY = 0;
  S.camR.panX = S.camR.panY = S.camR.lastTargetX = S.camR.lastTargetY = 0;
  // One tick of credit: each tick computes at the START of the window that displays
  // it, so render's interpolation adds no display latency (see render.js).
  S.accumSec = SIM_DT;
  S.lastWallMs = 0;
  tuneOnBuild();   // physics playground: the new car now matches the size knobs
  bpSyncExitButton(false);   // the fresh ground has its right wall back
  // Keep Zero-G in sync with its checkbox across rebuilds. The fresh world has normal
  // gravity (bpZeroG reset to false), so if the user left Zero-G ticked, re-apply it.
  // bpSetZeroG recaptures the fresh world's real gravity on entry, so bpSavedGravity
  // stays correct.
  const _zg = document.getElementById("bp_zerog");
  if (_zg && _zg.checked) bpSetZeroG(true);
}

export function buildSimulation() {
  // Default path used by Reset / mode switch. Generates a fresh map — UNLESS a track
  // has been loaded, in which case we rebuild that exact pinned track. (Reset clears
  // loadedTrack first, so only a Mode switch keeps the pinned track.) Any normal
  // (re)build exits ghost-replay mode.
  S.replayActions = null;
  S.ghostPoses = null; S.ghostDone = false;
  if (S.loadedTrack) {
    // Record maps carry an exact meters+grass source; everything else is px vertices.
    const src = S.loadedTrack.source || makeSourceFromTrack(S.loadedTrack);
    buildWithGround(src, S.loadedTrack.spawning_y, 0, 0);
  } else {
    buildWithGround(null, 0);
  }
}

// Build a Ground.cloneFrom() source from a Python-exported pinned track. Vertices
// arrive in PIXELS (incl. the 2 closing verts); Ground stores meters, so divide by
// SCALE. grassPositions are cosmetic (2 per vertex) — -1 = no sprite.
export function makeSourceFromTrack(track) {
  const verts = [];
  for (let i = 0; i < track.vertices.length; i++) {
    verts.push(new Vec2(track.vertices[i][0] / SCALE, track.vertices[i][1] / SCALE));
  }
  const grass = [];
  for (let i = 0; i < verts.length; i++) { grass.push(-1); grass.push(-1); }
  return { vectors: verts, grassPositions: grass };
}

// Build a source (cloned vectors + grass) from the CURRENT live terrain, so we can
// rebuild the world on the SAME map (Restart) without generating a new one.
export function currentGroundSource() {
  return { vectors: S.ground.vectors.map(v => new Vec2(v.x, v.y)),
           grassPositions: S.ground.grassPositions.slice(), tuned: S.ground.tuned };
}

// ---- Session terrains ----------------------------------------------------
// Remember every fresh map generated this session so the user can re-load one from
// the Terrains dropdown. Stored as loadedTrack-compatible objects (vertices in px)
// so re-loading reuses the normal pinned-track path. Capped so a long session can't
// grow huge.
export function recordSessionTerrain() {
  if (!S.ground || !S.ground.vectors) return;
  S.terrainCounter += 1;
  const name = `Terrain ${S.terrainCounter}`;
  S.sessionTerrains.push({
    id: S.terrainCounter,
    name,
    vertices: S.ground.vectors.map(v => [v.x * SCALE, v.y * SCALE]),
    spawning_y: getSpawningY(),
  });
  if (S.sessionTerrains.length > MAX_SESSION_TERRAINS) S.sessionTerrains.shift();
  S.currentTerrainName = name;   // a freshly generated map becomes the current one
  S.currentTerrainUnsaved = false;
  refreshSessionTerrainsMenu();
}
// Render the session-terrain list into the Terrains menu (newest first). Rows carry the
// terrain id in a data attribute; main.js delegates the click-to-load. Also refreshes the
// current-terrain box so both stay in sync from one call.
export function refreshSessionTerrainsMenu() {
  const list = document.getElementById("terrains_list");
  if (list) {
    list.innerHTML = "";
    if (!S.sessionTerrains.length) {
      list.innerHTML = '<div class="menu-empty">No terrains generated yet this session.</div>';
    } else {
      for (let i = S.sessionTerrains.length - 1; i >= 0; i--) {   // newest first
        const t = S.sessionTerrains[i];
        const row = document.createElement("div");
        row.className = "terrain-row";
        const nm = document.createElement("span");
        nm.className = "terrain-name";
        nm.textContent = t.name + (t.name === S.currentTerrainName ? "  (current)" : "");
        const load = document.createElement("button");
        load.textContent = "Load";
        load.dataset.sessionLoad = String(t.id);
        row.appendChild(nm);
        row.appendChild(load);
        list.appendChild(row);
      }
    }
  }
  updateCurrentTerrainBox();
}
// Reflect S.currentTerrainName in the little "current terrain" box under the controls.
export function updateCurrentTerrainBox() {
  const box = document.getElementById("current_terrain_box");
  if (!box) return;
  // "(unsaved)" flags a map whose saved copy was deleted — it's still loaded, just no
  // longer stored. Only shown when there's actually a name to qualify.
  const suffix = (S.currentTerrainUnsaved && S.currentTerrainName) ? " (unsaved)" : "";
  // A map holding a record also shows its record label ("Terrain 7 · Record map 5"),
  // unless that's already its name (loaded from Records or Saved).
  const rec = S.mapKey ? recordMapLabel(S.mapKey) : "";
  const recSfx = (rec && rec !== S.currentTerrainName) ? ` · ${rec}` : "";
  box.textContent = `${S.currentTerrainName || "—"}${suffix}${recSfx}`;
  box.parentElement.title = box.textContent;
}

// ---- Actions + the per-tick step ----------------------------------------
export function applyAction(car, action) {
  if (action === 0) car.motorOn(true);
  else if (action === 1) car.motorOn(false);
  else car.motorOff();
}

// ---- Render-pose snapshots (fixed-timestep render smoothing) -------------
// Per-tick pose snapshots (capturePose format) that render() extrapolates between
// frames. Purely cosmetic — never fed back into Box2D/obs, so parity is untouched.
// Roll forward one tick: prev <- curr, curr <- live. Dead cars are captured too —
// their ragdoll keeps moving under physics and is still drawn.
function _recordRenderPoses() {
  for (let pi = 0; pi < S.players.length; pi++) {
    const p = S.players[pi];
    if (!p.car) continue;
    const cap = capturePose(p.car);
    p.rposePrev = p.rposeCurr || cap;
    p.rposeCurr = cap;
  }
}
// Snap prev = curr = live so the next frames render the CURRENT pose with no sweep.
// Call after any discontinuous move — spawn/rebuild, the teleporting cheats
// (Float/Underworld/Teleport), and the final death frame — or the interpolator
// would draw a one-frame smear across the jump.
export function snapRenderPoses() {
  for (let pi = 0; pi < S.players.length; pi++) {
    const p = S.players[pi];
    if (!p.car) continue;
    p.rposeCurr = capturePose(p.car);
    p.rposePrev = p.rposeCurr;
  }
}

export async function runOneStep() {
  // Ghost replay: advance the recorded pose stream one frame; NO physics step.
  // simSpeed/pause still apply (driven by the loop's accumulator). Returns true
  // (==all done) at the last frame so the loop stops and holds the final frame.
  if (S.ghostPoses !== null) {
    S.ghostIdx += 1;
    if (S.ghostIdx >= S.ghostPoses.length - 1) { S.ghostIdx = S.ghostPoses.length - 1; S.ghostDone = true; return true; }
    return false;
  }
  // One physics tick + one action poll per living player + Box2D step.
  if (S.players.length === 0) return false;
  // Capture the generation at entry. If buildWithGround runs during an await below,
  // the post-await check returns early so we don't apply a stale action against a
  // freshly-built world (see S.worldGen).
  const gen = S.worldGen;

  for (let pi = 0; pi < S.players.length; pi++) {
    const p = S.players[pi];
    if (p.dead) continue;
    let action;
    if (S.replayActions !== null && p.agent) {
      // Replay mode: read pre-recorded action. Past the end -> motor off (the car was
      // already dying when recording stopped).
      action = (S.replayIdx < S.replayActions.length) ? S.replayActions[S.replayIdx] : 2;
    } else if (p.agent) {
      // Hand the agent a minimal sim context — it decides what obs to build. Adding a
      // new agent type with different obs needs only requires extending this object.
      action = await p.agent.act({
        car: p.car,
        ground: S.ground,
        scale: SCALE,
      });
      if (gen !== S.worldGen) return true;  // world replaced mid-await; abort
    } else {
      // Human: route the correct control set. hvh tags players with .control
      // (left=WASD, right=arrows); every other mode's lone human accepts EITHER.
      action = (p.control === "wasd")   ? humanActionWASD()
             : (p.control === "arrows") ? humanAction()
             :                            humanActionAny();
      hrAction(p, action);
    }
    applyAction(p.car, action);
  }
  if (S.replayActions !== null) S.replayIdx += 1;
  tuneTick();               // physics playground: motor overrides + neck spring before the step
  applyFlyCheats();         // cheat: WASD/arrow Flight (constant vel) or Rocket (thrust)

  S.world.Step(1.0 / FRAME_RATE, 10, 10);
  S.world.ClearForces();
  S.tickCount += 1;
  recordTick();   // bug probe: log human-car state this tick (no-op if no human)

  if (cheatsActive()) S.runTainted = true;
  if (physicsModified()) S.runModified = true;
  let allDead = true;
  for (let pi = 0; pi < S.players.length; pi++) {
    const p = S.players[pi];
    if (p.dead) continue;
    const hadBeat = p.beatTick;
    _checkPlayerEndOfStep(p);
    if (!p.isAI && (p.dead || (p.beatTick && !hadBeat))) commitRun(p, scoreOf(p), scoreParts(p), p.dead);
    if (!p.isAI) hrAfterTick(p);
    if (!p.dead) allDead = false;
  }
  _recordRenderPoses();   // dead cars too — the world keeps stepping their ragdolls
  return allDead;
}
