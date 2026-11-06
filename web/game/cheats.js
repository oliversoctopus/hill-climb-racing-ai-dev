// Bug probe + test-time cheats: per-tick state recorder, live physics-knob tuning,
// Zero-G, Float, and the Flight/Rocket flight cheats. All passive/opt-in — nothing
// here runs unless a checkbox/key turns it on, so AI runs and default driving are
// unaffected. (See HOW_TO_PLAY §7 for the bug-probe panel.)
import {
  S, SCALE, SPAWN_X, FRAME_RATE, BP_MAX_LEN,
  FLIGHT_ROT_RATE, FLIGHT_ROT_DAMP,
  ROCKET_ROT_RATE, ROCKET_ROT_DAMP, ROCKET_LIN_DAMP,
} from "./state.js";
import { Vec2, getSpawningY,
         DIRT_MASK, DIRT_CATEGORY, GRASS_MASK, GRASS_CATEGORY } from "./bridge.js";
import { KILL_LINE_M } from "./geom.js";
import { _vehicleCoM, snapRenderPoses } from "./sim.js";
import { humanAction, flyInput } from "./input.js";
import { T } from "./tune.js";

function _bpHumanPlayer() {
  if (!S.players) return null;
  for (let i = 0; i < S.players.length; i++) if (!S.players[i].isAI) return S.players[i];
  return null;
}
// Every live car on screen (AI and human alike). The physics-knob cheats apply to
// ALL of these so they affect the AI in every mode, incl. AI-only — same as Zero-G
// (global gravity) and Float already do.
function _bpAllCars() {
  const out = [];
  if (S.players) {
    for (let i = 0; i < S.players.length; i++) if (S.players[i].car) out.push(S.players[i].car);
  }
  return out;
}
export function bpSetStatus(s) {
  const e = document.getElementById("bp_status"); if (e) e.textContent = s;
  showToast(s);
}
// Transient message over the canvas, so cheat feedback is visible with the drawer shut.
let _toastTimer = 0;
export function showToast(s) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = s;
  t.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
}

export function recordTick() {
  const p = _bpHumanPlayer();
  if (!p || !p.car || p.dead) return;
  const c = p.car, cb = c.chassisBody;
  const pos = cb.GetPosition(), v = cb.GetLinearVelocity();
  const idt = FRAME_RATE;   // inv_dt for GetReactionTorque
  function jt(j) { try { return j ? j.GetReactionTorque(idt) : 0; } catch (e) { return 0; } }
  const w0 = c.wheels[0], w1 = c.wheels[1];
  const rec = {
    tick: S.tickCount, act: humanAction(),
    keyL: !!S.humanKeys.left, keyR: !!S.humanKeys.right, zeroG: S.bpZeroG, inv: S.bpInvincible,
    x: pos.x, y: pos.y, vx: v.x, vy: v.y,
    angle: cb.GetAngle(), angVel: cb.GetAngularVelocity(),
    motor0: !!(w0.joint && w0.joint.m_enableMotor),
    motor1: !!(w1.joint && w1.joint.m_enableMotor),
    wheelW0: w0.body.GetAngularVelocity(), wheelW1: w1.body.GetAngularVelocity(),
    on0: (w0.onGround === true), on1: (w1.onGround === true),
    rev0: jt(w0.joint), rev1: jt(w1.joint),       // motor-joint angular reaction (~0 when off)
    pris0: jt(w0.prisJoint), pris1: jt(w1.prisJoint)  // suspension torque into chassis
  };
  S.bpRecord.push(rec);
  if (S.bpRecord.length > BP_MAX_LEN) S.bpRecord.shift();
  const live = document.getElementById("bp_live");
  if (live) live.textContent = `angVel ${rec.angVel.toFixed(3)} rad/s  angle ${rec.angle.toFixed(2)}${S.bpZeroG ? "  [ZERO-G]" : ""}`;
}

// ---- Flight & Rocket cheats ---------------------------------------------
// Two mutually-exclusive flight cheats sharing the WASD/arrow directional input.
// Rocket (J) is thrust-based (acceleration + drag); Flight (G) is constant-velocity
// hover control. Both rotate the same way. Applied per tick from runOneStep.

// Rocket: forward/back apply thrust along facing; a light linear drag caps the speed.
function _rocketCar(c, input) {
  try { c.motorOff(); } catch (e) {}   // it's a rocket now, not a driven car
  const cb = c.chassisBody;
  const sign = input.fwd ? 1 : (input.back ? -1 : 0);
  const spin = (input.rotL === input.rotR) ? 0 : (input.rotR ? 1 : -1);
  const dir = cb.GetWorldVector(new Vec2(1, 0));  // facing = chassis local +x
  const bodies = c.bodies();
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i]; if (!b) continue;
    const m = b.GetMass(); if (!(m > 0)) continue;   // static/frozen bodies: skip
    if (sign !== 0)
      b.ApplyForce(new Vec2(sign * S.rocketAccel * m * dir.x,
                            sign * S.rocketAccel * m * dir.y), b.GetWorldCenter());
    const v = b.GetLinearVelocity();   // light drag → terminal speed, no runaway
    b.SetLinearVelocity(new Vec2(v.x * ROCKET_LIN_DAMP, v.y * ROCKET_LIN_DAMP));
  }
  if (spin !== 0) { cb.SetAngularVelocity(spin * ROCKET_ROT_RATE); cb.SetAwake(true); }
  else { cb.SetAngularVelocity(cb.GetAngularVelocity() * ROCKET_ROT_DAMP); }
}

// Flight: constant-velocity hover. The car moves at exactly flightSpeed along its
// facing while forward/back is held, and is pinned to zero velocity the instant
// neither is held. We drive the whole assembly as a rigid body (linear V + ω×r about
// the CoM) and pre-cancel the gravity Box2D adds this step, so the commanded velocity
// holds exactly — no fall, no drift.
function _flyVelCar(c, input) {
  try { c.motorOff(); } catch (e) {}
  const cb = c.chassisBody;
  const sign = input.fwd ? 1 : (input.back ? -1 : 0);
  const spin = (input.rotL === input.rotR) ? 0 : (input.rotR ? 1 : -1);
  const omega = (spin !== 0) ? spin * FLIGHT_ROT_RATE
                           : cb.GetAngularVelocity() * FLIGHT_ROT_DAMP;
  const dir = cb.GetWorldVector(new Vec2(1, 0));
  const vx = sign * S.flightSpeed * dir.x, vy = sign * S.flightSpeed * dir.y;
  const g = S.world.GetGravity(), gx = g.x / FRAME_RATE, gy = g.y / FRAME_RATE;
  const com = _vehicleCoM(c), bodies = c.bodies();
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i]; if (!b) continue;
    const p = b.GetWorldCenter();
    const rx = p.x - com.x, ry = p.y - com.y;   // rigid-body velocity field about the CoM
    b.SetLinearVelocity(new Vec2(vx - omega * ry - gx, vy + omega * rx - gy));
    b.SetAngularVelocity(omega); b.SetAwake(true);
  }
}

// OR-merge two control sets (single-player: either hand flies the lone car).
function _mergeFly(a, b) {
  return { fwd: a.fwd || b.fwd, back: a.back || b.back,
           rotL: a.rotL || b.rotL, rotR: a.rotR || b.rotR };
}
// Apply a per-car fly function to every player's car, routing input per control set:
// Human-vs-Human gives each player their OWN keys; other modes merge both and apply
// to all cars (incl. the AI's).
function _applyFlyCheat(flyFn) {
  if (!S.players || !S.players.length) return;
  const merged = (S.mode === "hvh") ? null : _mergeFly(S.flyKeysWASD, S.flyKeysArrows);
  for (let pi = 0; pi < S.players.length; pi++) {
    const p = S.players[pi]; if (!p.car) continue;
    const input = merged || (p.control === "arrows" ? S.flyKeysArrows : S.flyKeysWASD);
    flyFn(p.car, flyInput(input));   // Reverse-controls cheat mirrors it, if on
  }
}
export function applyFlyCheats() {
  if (S.bpFlight)      _applyFlyCheat(_flyVelCar);
  else if (S.bpRocket) _applyFlyCheat(_rocketCar);
}

export function bpSetZeroG(on) {
  if (on) {
    // Capture the REAL gravity only when first entering zero-G — otherwise a second
    // enable would read the already-zeroed gravity. Store a copy, not the world's
    // internal vector.
    if (!S.bpZeroG) {
      const g = S.world.GetGravity();
      S.bpSavedGravity = new Vec2(g.x, g.y);
    }
    S.world.SetGravity(new Vec2(0, 0));
    S.bpZeroG = true;
    bpSetStatus("Zero-G ON — gravity off (everything keeps its velocity). Press F to float the car(s) up.");
  } else {
    // Fall back to normal gravity if the saved value is missing or (defensively) zero.
    let gv = S.bpSavedGravity;
    if (!gv) gv = new Vec2(T.gravityX, T.gravityY);
    S.world.SetGravity(gv);
    S.bpZeroG = false;
    bpSetStatus("Zero-G OFF — gravity restored.");
  }
}
function _bpFloatOneCar(c) {
  // Translate the WHOLE car up ~300px, PRESERVING both linear AND angular velocity so
  // it keeps doing exactly what it was doing. With no gravity (press Zero-G first) and
  // no ground, a spin that grows/persists is a pure joint/solver artifact.
  const dyM = 300 / SCALE;
  const bodies = c.bodies();
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i]; if (!b) continue;
    const bp = b.GetPosition();
    b.SetPositionAndAngle(new Vec2(bp.x, bp.y - dyM), b.GetAngle());
    b.SetAwake(true);   // velocity (linear + angular) preserved
  }
}
export function bpFloatCar() {
  S.runTainted = S.runModified = true;   // one-shot cheat → cheat records only
  // Float every car on screen — AI and human alike (both players in Human-vs-Human).
  let n = 0;
  if (S.players) {
    for (let i = 0; i < S.players.length; i++) {
      const p = S.players[i];
      if (p.car) { _bpFloatOneCar(p.car); n++; }
    }
  }
  if (n === 0) { bpSetStatus("No car to float — start a run first."); return; }
  snapRenderPoses();   // discontinuous move — don't let the interpolator smear the jump
  bpSetStatus(`Floated ${n > 1 ? `${n} cars` : "car"} up (velocity preserved, camera follows). Enable Zero-G to watch a pure joint/solver spin.`);
}
// "Underworld" cheat: teleport every car straight down to a fixed low altitude (1.5 m
// above the fall-off line), PRESERVING both linear and angular velocity so it keeps doing
// exactly what it was doing. "Altitude" here is the absolute elevation above the kill line
// the Altimeter reads (geom.altitudeAboveKillLine), so we shift the whole assembly so its
// chassis sits at that altitude — right on the brink of the void.
const UNDERWORLD_ALTITUDE_M = 1.5;
function _bpUnderworldOneCar(c) {
  // y-down world: altitude = KILL_LINE_M − y, so the target altitude maps to this y, and
  // dyM (>0 = downward) is how far to slide the whole car to put its chassis there.
  const targetY = KILL_LINE_M - UNDERWORLD_ALTITUDE_M;
  const dyM = targetY - c.chassisBody.GetPosition().y;
  const bodies = c.bodies();
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i]; if (!b) continue;
    const bp = b.GetPosition();
    b.SetPositionAndAngle(new Vec2(bp.x, bp.y + dyM), b.GetAngle());
    b.SetAwake(true);   // velocity (linear + angular) preserved
  }
}
export function bpUnderworld() {
  S.runTainted = S.runModified = true;   // one-shot cheat → cheat records only
  // Send every car on screen down to the underworld — AI and human alike.
  let n = 0;
  if (S.players) {
    for (let i = 0; i < S.players.length; i++) {
      const p = S.players[i];
      if (p.car) { _bpUnderworldOneCar(p.car); n++; }
    }
  }
  if (n === 0) { bpSetStatus("No car to send under — start a run first."); return; }
  snapRenderPoses();   // discontinuous move — don't let the interpolator smear the jump
  bpSetStatus(`Underworld — dropped ${n > 1 ? `${n} cars` : "car"} to altitude ${UNDERWORLD_ALTITUDE_M} m above the fall-off line (velocity preserved). Turn on Invincible to survive down here.`);
}

// "Stop" cheat: momentarily kill all motion — zero every body's linear AND angular
// velocity on every car, so it freezes in place for an instant before gravity/driving
// take over again. One-shot (not a hold). Applies to all cars, like Float/Underworld.
function _bpStopOneCar(c) {
  const bodies = c.bodies();
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i]; if (!b) continue;
    b.SetLinearVelocity(new Vec2(0, 0));
    b.SetAngularVelocity(0);
    b.SetAwake(true);
  }
}
export function bpStop() {
  S.runTainted = S.runModified = true;   // one-shot cheat → cheat records only
  let n = 0;
  if (S.players) {
    for (let i = 0; i < S.players.length; i++) {
      const p = S.players[i];
      if (p.car) { _bpStopOneCar(p.car); n++; }
    }
  }
  if (n === 0) { bpSetStatus("No car to stop — start a run first."); return; }
  bpSetStatus(`Stopped ${n > 1 ? `${n} cars` : "car"} — all velocity zeroed (momentary).`);
}

// "Open Exit" cheat: knock down the invisible RIGHT WALL that seals the "underworld"
// (the space between the terrain and the invisible bottom floor). That wall is an
// incidental collision edge — the ground's vertex list closes its render fill with two
// bottom corners (Ground.js:64-65), and setBodies() turns EVERY consecutive pair into a
// Box2D edge (Ground.js:109-116), so surf_last→bottomRight became a near-vertical wall at
// the far right (and its grass-layer twin, offset up by grassThickness). The left side is
// already open (the chain never closes back to surf_0), so removing the right wall lets
// you drive straight out the right end. The button CYCLES: if the wall is up it comes
// down; if it's already down, the same two edges are re-added via Ground.addEdge —
// exactly how setBodies() built them — sealing the exit again. Runtime-only + opt-in: it
// mutates just THIS live world's ground body, never the shared generation path, so
// training/parity are untouched. A rebuild (Restart / Regenerate / load / mode switch)
// restores the wall (sim.buildWithGround calls bpSyncExitButton to re-label the button).
function _edgeMatches(fix, ax, ay, bx, by, eps) {
  const s = fix.GetShape();
  if (!s || s.m_vertexCount !== 2) return false;
  const v0 = s.m_vertices[0], v1 = s.m_vertices[1];
  const near = (v, x, y) => Math.abs(v.x - x) <= eps && Math.abs(v.y - y) <= eps;
  return (near(v0, ax, ay) && near(v1, bx, by)) || (near(v0, bx, by) && near(v1, ax, ay));
}
// Keep the button's label honest: "Open Exit" while the wall is up, "Close Exit" once
// it's down. Rebuilds restore the wall, so buildWithGround calls this with open=false.
export function bpSyncExitButton(open) {
  const el = document.querySelector("#bp_openexit .btn-label");   // keeps the <kbd>E</kbd> marker
  if (el) el.textContent = open ? "Close Exit" : "Open Exit";
}
export function bpToggleExit() {
  S.runTainted = S.runModified = true;   // one-shot cheat → cheat records only
  const g = S.ground;
  if (!g || !g.vectors || g.vectors.length < 3 || !g.dirtBody) { bpSetStatus("No terrain — start a run first."); return; }
  const V = g.vectors, n = V.length;
  const a = V[n - 3], b = V[n - 2];            // surf_last, bottomRight — the wall's endpoints (dirt)
  const gt = (g.grassThickness || 5) / SCALE;  // grass edges sit this much higher (Ground.js:114)
  const eps = 1e-4;
  // Match the dirt wall (offset 0) and the grass wall (offset gt) on their bodies.
  const targets = [{ body: g.dirtBody, off: 0 }, { body: g.grassBody, off: gt }];
  let removed = 0;
  for (let ti = 0; ti < targets.length; ti++) {
    const body = targets[ti].body, off = targets[ti].off;
    if (!body) continue;
    const toKill = [];   // collect first — don't destroy mid-iteration
    for (let f = body.GetFixtureList(); f; f = f.m_next) {
      if (_edgeMatches(f, a.x, a.y - off, b.x, b.y - off, eps)) toKill.push(f);
    }
    for (let k = 0; k < toKill.length; k++) { body.DestroyFixture(toKill[k]); removed++; }
  }
  if (removed > 0) {
    bpSyncExitButton(true);
    bpSetStatus("Underworld exit opened — the right wall is down. Drive off the right end to leave (press E again to close it; Restart/Regenerate also restores it).");
    return;
  }
  // Wall not found → the exit is open: put it back. Re-add the dirt edge and its
  // grass twin exactly as Ground.setBodies() built them (same fixture/filter data).
  g.addEdge(a, b, DIRT_MASK, DIRT_CATEGORY, false);
  g.addEdge(new Vec2(a.x, a.y - gt), new Vec2(b.x, b.y - gt), GRASS_MASK, GRASS_CATEGORY, true);
  bpSyncExitButton(false);
  bpSetStatus("Underworld exit closed — the right wall is back up (press E again to reopen).");
}

// ---- Teleport cheat -----------------------------------------------------
// Teleport to an arbitrary spot given in the two units the HUD already shows: X is the
// project SCORE (distance), Y is ALTITUDE in metres above the fall-off line (the
// Altimeter reading). They're different units on purpose — both are recognizable from
// the readouts. Inverse of the two metrics: score px = score*10 + SPAWN_X (see
// sim.scorePx), altitude→y = KILL_LINE_M − altitude (see geom.altitudeAboveKillLine).

// Reference car for the panel's prefill: the human's car if there is one, else the
// first live car (so AI-only mode prefills from the AI).
function _bpRefCar() {
  const h = _bpHumanPlayer();
  if (h && h.car) return h.car;
  if (S.players) for (let i = 0; i < S.players.length; i++) if (S.players[i].car) return S.players[i].car;
  return null;
}
// The reference car's CURRENT position expressed in teleport units, for prefilling the
// panel — null if there's no car yet.
export function bpTeleportCurrent() {
  const c = _bpRefCar();
  if (!c) return null;
  const p = c.chassisBody.GetPosition();
  return { score: Math.max(0, Math.floor((p.x * SCALE - SPAWN_X) / 10)),
           altitude: KILL_LINE_M - p.y };
}
function _bpTeleportOneCar(c, targetXm, targetYm) {
  // Shift the WHOLE assembly so the chassis lands at the target, preserving linear +
  // angular velocity (same body-shift approach as Float/Underworld).
  const p = c.chassisBody.GetPosition();
  const dx = targetXm - p.x, dy = targetYm - p.y;
  const bodies = c.bodies();
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i]; if (!b) continue;
    const bp = b.GetPosition();
    b.SetPositionAndAngle(new Vec2(bp.x + dx, bp.y + dy), b.GetAngle());
    b.SetAwake(true);
  }
}
export function bpTeleport(score, altitudeM) {
  S.runTainted = S.runModified = true;
  const targetXm = (score * 10 + SPAWN_X) / SCALE;   // score → chassis x (meters)
  const targetYm = KILL_LINE_M - altitudeM;          // altitude → chassis y (meters, y-down)
  let n = 0;
  if (S.players) {
    for (let i = 0; i < S.players.length; i++) {
      const p = S.players[i];
      if (p.car) { _bpTeleportOneCar(p.car, targetXm, targetYm); n++; }
    }
  }
  if (n === 0) { bpSetStatus("No car to teleport — start a run first."); return; }
  snapRenderPoses();   // discontinuous move — don't let the interpolator smear the jump
  bpSetStatus(`Teleported ${n > 1 ? `${n} cars` : "car"} to score ${Math.round(score)}, altitude ${altitudeM} m (velocity preserved).`);
}
export function bpFlag() {
  S.bpFlags.push({ tick: S.tickCount, idx: S.bpRecord.length });
  bpSetStatus(`Flagged at tick ${S.tickCount} (flag #${S.bpFlags.length}). Keep playing, then Download.`);
}
export function bpDownload() {
  const gv = (S.ground && S.ground.vectors)
    ? S.ground.vectors.map(v => [v.x, v.y]) : [];
  const data = {
    meta: {
      units: "position/velocity in meters & m/s, angle rad, ang_vel rad/s, torque N*m; ground in meters",
      frame_rate: FRAME_RATE, scale: SCALE, spawn_x: SPAWN_X,
      spawning_y: getSpawningY(),
      mode: S.mode,
      phys: { ...T },   // every physics-playground knob (game/tune.js)
      n_ticks: S.bpRecord.length, flags: S.bpFlags
    },
    ground: gv, ticks: S.bpRecord
  };
  const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `hcr_bugrun_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
  bpSetStatus(`Downloaded ${S.bpRecord.length} ticks, ${S.bpFlags.length} flag(s).`);
}
