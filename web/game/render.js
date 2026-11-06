// Vanilla-canvas renderer (no p5): scenery, cars, HUD, smooth-follow camera, the
// unified cheat-readout HUD, split-screen for Human-vs-Human, and the DOM stats
// line. Mirrors python/renderer.py but supports multiple players with per-player
// colors. The physics classes' own p5 show() methods are used only by legacy_neat/.
import {
  S, SCALE, SPAWN_X, CANVAS_WIDTH, CANVAS_HEIGHT, FRAME_RATE, SIM_DT,
  AI_COLOR, AI2_COLOR, HUMAN_COLOR, HUMAN_L_COLOR, HUMAN_R_COLOR, LEGENDARY_FLYOFF,
} from "./state.js";
import { drawDevWorld, drawDevHUD } from "./dev.js";
import { scoreOf, scorePx, scoreParts, curScoreOf, _vehicleBodies, _vehicleCoM } from "./sim.js";
import { modeDef, stageWidth } from "./modes.js";
import { altitudeAboveKillLine } from "./geom.js";
import { drawBackground, fillDirt, drawFinishFlag, drawBestFlag, finishPx } from "./scenery.js";
import { drawPlayerPanel, drawProgressBar, drawTag, drawReadout, drawEndCard, PANEL_W } from "./hud.js";
import { emitDust, stepFx, shake, shakeOffset, burstConfetti, drawDust, drawConfetti, clearFx } from "./fx.js";
import { runSeconds, fmtTime, mapRecord, globalRecord, mapRecordAll, globalRecordAll, showCheatRecords
} from "./records.js";

// ---- Fixed-timestep render smoothing -------------------------------------
// Physics steps at a fixed 30 Hz; render() runs every rAF, drawing each body at
// lerp(prev tick, curr tick, alpha). The accumulator is primed one tick ahead
// (sim.buildWithGround), so each tick computes at the START of the wall-clock
// window that displays it: in-between frames are true interpolation between real
// states (no extrapolation artifacts) with no added display latency. Ghost replays
// interpolate the same way. Angles are Box2D's continuous radians — no wrap needed.
function _renderAlpha() {
  return Math.max(0, Math.min(1, S.accumSec / SIM_DT));
}
function _lerpPose(a, b, t) {
  return { x: a.x + (b.x - a.x) * t,
           y: a.y + (b.y - a.y) * t,
           angle: a.angle + (b.angle - a.angle) * t };
}
// Lerp a whole car pose (chassis/head/torso/wheels; ghost poses also carry a CoM the
// readout cheats anchor on). Tolerates a missing part in `a` by holding `b`'s value.
function _lerpCarPose(a, b, t) {
  const out = {
    chassis: _lerpPose(a.chassis || b.chassis, b.chassis, t),
    head:    _lerpPose(a.head    || b.head,    b.head,    t),
    torso:   _lerpPose(a.torso   || b.torso,   b.torso,   t),
    wheels:  [],
  };
  for (let i = 0; i < b.wheels.length; i++) {
    out.wheels.push(_lerpPose(a.wheels[i] || b.wheels[i], b.wheels[i], t));
  }
  if (a.com && b.com) {
    out.com = { x: a.com.x + (b.com.x - a.com.x) * t, y: a.com.y + (b.com.y - a.com.y) * t };
  } else if (b.com) out.com = b.com;
  return out;
}
// The pose to draw player p at this frame — or null to fall back to live bodies
// (snapshots not seeded yet).
function _playerDrawPose(p, alpha) {
  const a = p.rposePrev, b = p.rposeCurr;
  if (!b) return null;
  if (!a || a === b || alpha >= 1) return b;
  return _lerpCarPose(a, b, alpha);
}

// Draws a body's sprite at its world position, rotated by its angle. The sprite-rect
// (sx, sy, sw, sh) is in body-LOCAL pixel space (relative to the body's center,
// before rotation) — matches the p5 image(spr, sx, sy, sw, sh) inside push/rotate.
function _drawSprite(ctx, img, body, sx, sy, sw, sh) {
  const p = body.GetPosition();
  const a = body.GetAngle();
  ctx.save();
  ctx.translate(p.x * SCALE - S.cameraPanX, p.y * SCALE - S.cameraPanY);
  ctx.rotate(a);
  ctx.drawImage(img, sx, sy, sw, sh);
  ctx.restore();
}

// Draws a rotated solid rectangle (torso) — same as p5's push/translate/rotate/
// rectMode(CENTER)/rect(0,0,w,h) sequence.
function _drawRotRect(ctx, body, w, h, fill, stroke) {
  const p = body.GetPosition();
  const a = body.GetAngle();
  ctx.save();
  ctx.translate(p.x * SCALE - S.cameraPanX, p.y * SCALE - S.cameraPanY);
  ctx.rotate(a);
  ctx.fillStyle = fill;
  ctx.fillRect(-w/2, -h/2, w, h);
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1;
    ctx.strokeRect(-w/2, -h/2, w, h);
  }
  ctx.restore();
}

// Render order mirrors Car.show() in Car.js: person, wheels, then chassis sprite on
// top (drawn LAST so it covers the wheel-attach points). `pose` (optional) is an
// interpolated snapshot from _playerDrawPose — when given, every body is drawn at its
// lerped pose via _mockBody instead of its live Box2D pose; dims/colors still come
// from the live car.
function _drawCar(ctx, car, color, isAI, pose) {
  const assets = S.assets;
  // Torso (rotated solid rect, shirt color)
  const torso = car.person.torso;
  const shirtColor = `rgb(${car.player.shirtColorR},${car.player.shirtColorG},${car.player.shirtColorB})`;
  _drawRotRect(ctx, pose ? _mockBody(pose.torso) : torso.body, torso.width, torso.height, shirtColor, "#000");

  // Head sprite. AI cars wear Code Bullet's computer head (isCB branch in Person.js:
  // CB uses x=-r-7, person x=-r-8; both y=-r-15, w=h=r*3).
  const head = car.person.head;
  const hr = head.radius;
  const headBody = pose ? _mockBody(pose.head) : head.body;
  if (isAI && assets.cbhead) {
    _drawSprite(ctx, assets.cbhead, headBody, -hr - 7, -hr - 15, hr * 3, hr * 3);
  } else {
    _drawSprite(ctx, assets.head, headBody, -hr - 8, -hr - 15, hr * 3, hr * 3);
  }

  // Wheel sprites (Wheel.js: x=-r, y=-r, w=h=2*r)
  for (let i = 0; i < car.wheels.length; i++) {
    const w = car.wheels[i];
    const wBody = (pose && pose.wheels[i]) ? _mockBody(pose.wheels[i]) : w.body;
    _drawSprite(ctx, assets.wheel, wBody, -w.radius, -w.radius, w.radius * 2, w.radius * 2);
  }

  // Chassis sprite (Car.js: x=-cw/2-7, y=-ch-20, w=cw+23, h=ch*2+10)
  const cw = car.chassisWidth, ch = car.chassisHeight;
  _drawSprite(ctx, assets.car, pose ? _mockBody(pose.chassis) : car.chassisBody,
              -cw/2 - 7, -ch - 20, cw + 23, ch * 2 + 10);
}

// Draw the car from a recorded pose (meters) instead of live Box2D bodies, by
// mocking the GetPosition/GetAngle the sprite helpers read. dims (px) come from the
// export so sizes are exact. Mirrors _drawCar's order: torso, head, wheels, chassis.
function _mockBody(o) {
  return { GetPosition() { return { x: o.x, y: o.y }; },
           GetAngle() { return o.angle || 0; } };
}
function _drawCarFromPose(ctx, pose, color, d) {
  const assets = S.assets;
  // Ghost replays are always the AI beating the track, so it wears the CB head.
  const shirt = `rgb(${color.shirtR},${color.shirtG},${color.shirtB})`;
  _drawRotRect(ctx, _mockBody(pose.torso), d.torso_w, d.torso_h, shirt, "#000");
  const hr = d.head_r;
  if (assets.cbhead) {
    _drawSprite(ctx, assets.cbhead, _mockBody(pose.head), -hr - 7, -hr - 15, hr * 3, hr * 3);
  } else {
    _drawSprite(ctx, assets.head, _mockBody(pose.head), -hr - 8, -hr - 15, hr * 3, hr * 3);
  }
  for (let i = 0; i < pose.wheels.length; i++) {
    const wr = d.wheel_r;
    _drawSprite(ctx, assets.wheel, _mockBody(pose.wheels[i]), -wr, -wr, wr * 2, wr * 2);
  }
  const cw = d.chassis_w, ch = d.chassis_h;
  _drawSprite(ctx, assets.car, _mockBody(pose.chassis), -cw/2 - 7, -ch - 20, cw + 23, ch * 2 + 10);
}

// Smooth-follow camera update for ONE viewport. Mutates cam.panX/panY so the focus
// car sits at screen-x `anchorX` and stays inside a vertical screen band. Shared by
// single-view render and each half of the split screen.
function _followCamera(cam, focusX, focusYworld, anchorX) {
  const CAM_TRIGGER_MARGIN = 80;   // px from the left edge; once the focus reaches this
                                 // (reversing / flying backwards) the camera catches it
  let target = focusX - anchorX; // normal offset: the focus sits anchorX px from the left
  if (!S.bpZeroG) {
    // Normal play floors the scroll at 0 so the pre-start area stays hidden and the
    // focus is free to drift left across the screen. Once it reaches the trigger
    // margin, catch it and smoothly pan back to the FULL anchorX margin — latched
    // (panX < 0) until it returns to spawn.
    const flooredTarget = Math.max(0, target);
    const triggered = (cam.panX < 0) || (focusX - cam.panX < CAM_TRIGGER_MARGIN);
    target = triggered ? target : flooredTarget;
  }
  // Feed-forward the target's own per-frame velocity so the camera doesn't TRAIL a fast
  // car. A plain lerp (`pan += (target-pan)*k`) lags a moving target by an offset
  // proportional to its SPEED — so at high speed the car drifts off its anchor and either
  // leaves the screen or trips the snap below in visible chunks. Adding (1-k)*(target-
  // lastTarget) cancels that: the steady-state lag is zero, so the car holds its anchor at
  // ANY constant speed and only slides (then eases back) while it's accelerating. k=0.25 =>
  // 0.75 feed-forward.
  if (Math.abs(target - cam.panX) > 400) cam.panX = target;   // snap on big jumps (teleport/respawn)
  else cam.panX += (target - cam.panX) * 0.25 + (target - cam.lastTargetX) * 0.75;
  cam.lastTargetX = target;
  // Vertical follow: keep the focus car inside a screen band. Stays ~0 in normal play,
  // only kicking in when it flies high or falls low. Target from the NEUTRAL-camera
  // world y (not the panned screen position) so the return is smooth and symmetric. Same
  // velocity feed-forward as the horizontal (k=0.2 => 0.8) — this is the axis that had no
  // snap safety net, so without it a fast climb/fall trailed off-screen entirely.
  const topM = 120, botM = CANVAS_HEIGHT - 80;
  let targetY = 0;
  if (focusYworld < topM) targetY = focusYworld - topM;
  else if (focusYworld > botM) targetY = focusYworld - botM;
  cam.panY += (targetY - cam.panY) * 0.2 + (targetY - cam.lastTargetY) * 0.8;
  cam.lastTargetY = targetY;
}

// Surface y at screen x, linearly interpolated along pts (searching from index k).
function _surfY(pts, k, x) {
  let j = k;
  while (j > 0 && pts[j][0] > x) j--;
  while (j < pts.length - 2 && pts[j + 1][0] < x) j++;
  const a = pts[j], b = pts[j + 1];
  return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]);
}

// One grass tuft at anchor (x, y), sheared so its base spans the surface under it.
function _drawTuft(ctx, spr, pts, k, x, y) {
  const hw = spr.width / 2;
  const m = (_surfY(pts, k, x + hw) - _surfY(pts, k, x - hw)) / spr.width;
  ctx.save();
  ctx.transform(1, m, 0, 1, x, y);
  ctx.drawImage(spr, -hw, -spr.height / 2 - 15);
  ctx.restore();
}

// Draw sky + ground + grass for the current global cameraPanX/cameraPanY into a
// viewport `viewWidth` px wide (local coords; caller sets up clip/translate).
function _drawScenery(ctx, viewWidth, timeSec) {
  const assets = S.assets;
  const ground = S.ground;
  drawBackground(ctx, viewWidth);

  // Ground (dirt fill + grass line). Walk only the visible vertex slice. Track vertex
  // INDICES so we can place grass sprites at the same indices.
  const v = ground.vectors;
  const xLeft = S.cameraPanX - 50;
  const xRight = S.cameraPanX + viewWidth + 50;
  const topPts = [];
  const topIdx = [];
  for (let i = 0; i < v.length - 2; i++) {
    const vx = v[i].x * SCALE, vy = v[i].y * SCALE;
    if (vx < xLeft) continue;
    if (vx > xRight) break;
    topPts.push([vx - S.cameraPanX, vy - S.cameraPanY]);
    topIdx.push(i);
  }

  // Grass sprites (Ground.js show()). Each vertex has 2 grass slots: grassPositions[2i]
  // at vertex i, grassPositions[2i+1] halfway to vertex i+1. -1 = no sprite. Centered on
  // its anchor with a -15 px y-offset. Drawn BEFORE the ground so the grass band hides
  // the tufts' pale bases, and vertically sheared so each base follows the local slope
  // (blades stay upright) — otherwise slopes bury one side in dirt.
  if (ground.grassPositions && assets.grass && topIdx.length > 1) {
    const gp = ground.grassPositions;
    for (let k = 0; k < topIdx.length - 1; k++) {
      const i = topIdx[k];
      const sIdx = gp[2 * i];
      if (sIdx !== undefined && sIdx >= 0 && sIdx < assets.grass.length)
        _drawTuft(ctx, assets.grass[sIdx], topPts, k, topPts[k][0], topPts[k][1]);
      const sIdx2 = gp[2 * i + 1];
      if (sIdx2 !== undefined && sIdx2 >= 0 && sIdx2 < assets.grass.length)
        _drawTuft(ctx, assets.grass[sIdx2], topPts, k,
                  (topPts[k][0] + topPts[k+1][0]) / 2, (topPts[k][1] + topPts[k+1][1]) / 2);
    }
  }

  if (topPts.length >= 2) {
    const bottom = CANVAS_HEIGHT + 60;   // overdraw for screen shake
    ctx.beginPath();
    ctx.moveTo(topPts[0][0], topPts[0][1]);
    for (let i = 1; i < topPts.length; i++) ctx.lineTo(topPts[i][0], topPts[i][1]);
    ctx.lineTo(topPts[topPts.length-1][0], bottom);
    ctx.lineTo(topPts[0][0], bottom);
    ctx.closePath();
    fillDirt(ctx, viewWidth);
    // Main green grass band. Width + color match Code Bullet's Ground.show():
    // stroke(0,120,0) = #007800, strokeWeight(grassThickness*2) = 10 (centered).
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#007800"; ctx.lineWidth = 10;
    ctx.beginPath();
    ctx.moveTo(topPts[0][0], topPts[0][1]);
    for (let i = 1; i < topPts.length; i++) ctx.lineTo(topPts[i][0], topPts[i][1]);
    ctx.stroke();
    // Four thin (weight-3) detail lines, matching Code Bullet's Ground.show(): two
    // olive lines below the terrain line and two bright-green highlights above it.
    const detail = [
      ["#423c00", 9],   // stroke(66,60,0)  dark olive
      ["#2c5a00", 6],   // stroke(44,90,0)  olive-green
      ["#008c00", -5],  // stroke(0,140,0)  bright green
      ["#008200", -3],  // stroke(0,130,0)  green
    ];
    ctx.lineWidth = 3;
    for (let d = 0; d < detail.length; d++) {
      ctx.strokeStyle = detail[d][0];
      const off = detail[d][1];
      ctx.beginPath();
      ctx.moveTo(topPts[0][0], topPts[0][1] + off);
      for (let i = 1; i < topPts.length; i++) ctx.lineTo(topPts[i][0], topPts[i][1] + off);
      ctx.stroke();
    }
  }

  drawFinishFlag(ctx, viewWidth, timeSec);
  if (_humanMode() && S.recStart) drawBestFlag(ctx, viewWidth, S.recStart.map.bestScore);
}

// ---- HUD helpers -----------------------------------------------------------
function _humanMode() { return modeDef(S.mode).spawn.some(d => d.agent === "human"); }
function _progressFrac(px) {
  const span = finishPx() - SPAWN_X;
  return span > 0 ? Math.max(0, Math.min(1, (px - SPAWN_X) / span)) : 0;
}
// "Map best 1502 · ⏱ 1:58.20" / "… · no finish yet" / "No record …".
function _bestLine(r, label) {
  if (!r.bestScore) return `No record on this map yet`;
  return `${label} ${r.bestScore}  ·  ${r.bestTime != null ? `⏱ ${fmtTime(r.bestTime)}` : "no finish yet"}`;
}
function _recValue(r) {
  if (!r.bestScore) return "—";
  return `${r.bestScore}  ·  ${r.bestTime != null ? fmtTime(r.bestTime) : "no finish"}`;
}
// Incl.-cheats track value as coloured segments: a part a cheated run set is red + ⚠.
const CHEAT_RED = "#ff6b6b";
function _recValueAll(a) {
  if (!a.score) return "—";
  const part = (txt, cheated) => [cheated ? `⚠${txt}` : txt, cheated ? CHEAT_RED : "#fff"];
  return [part(String(a.score), a.scoreCheated), ["  ·  ", "#fff"],
          a.time != null ? part(fmtTime(a.time), a.timeCheated) : ["no finish", "#fff"]];
}
// Panel contents for one live player.
function _panelFor(p, label, color) {
  const lines = [];
  if (!p.isAI && S.recStart) {
    lines.push(_bestLine(S.recStart.map, "Map best"));
  }
  if (S.bpDistance) lines.push(`Distance now  ${curScoreOf(p)}`);
  return { label, color: color.outline, score: scoreOf(p), time: fmtTime(runSeconds(p)), lines,
           dead: p.dead && !p.beatTick, finished: !!p.beatTick };
}
function _taintTag(ctx, x, y) {
  if (S.runTainted) drawTag(ctx, x, y, "⚠ CHEATS / SLOW-MO USED · CHEAT RECORDS ONLY", "rgba(190,50,50,0.9)");
}
function _progressFor(ctx, cx, players) {
  const markers = players.map(p => ({ frac: _progressFrac(p.maxDistPx), color: p.color.outline }));
  const best = (_humanMode() && S.recStart && S.recStart.map.bestScore)
    ? _progressFrac(S.recStart.map.bestScore * 10 + SPAWN_X) : null;
  drawProgressBar(ctx, cx, 30, 360, markers, best);
}

// Live-play HUD for the single-screen modes: your panel top-left, the AI's top-right
// when racing it; the progress bar top-center.
function _drawSingleScoreHUD(ctx) {
  let ai = null, hum = null, aiB = null;
  for (let i = 0; i < S.players.length; i++) {
    const p = S.players[i];
    if (p.aiB) aiB = p; else if (p.isAI) ai = p; else hum = p;
  }
  if (aiB) {   // dev AI vs AI: main AI top-left, AI B top-right
    _progressFor(ctx, CANVAS_WIDTH / 2, ai ? [ai, aiB] : [aiB]);
    if (ai) drawPlayerPanel(ctx, 16, 14, _panelFor(ai, "Main AI", AI_COLOR));
    drawPlayerPanel(ctx, CANVAS_WIDTH - 16 - PANEL_W, 14, _panelFor(aiB, "AI B", AI2_COLOR));
    return;
  }
  const order = [];
  if (hum) order.push(hum);
  if (ai) order.push(ai);
  _progressFor(ctx, CANVAS_WIDTH / 2, order);
  let bottom = 0;
  if (hum) bottom = drawPlayerPanel(ctx, 16, 14, _panelFor(hum, "You", HUMAN_COLOR));
  if (ai) {
    const b = drawPlayerPanel(ctx, hum ? CANVAS_WIDTH - 16 - PANEL_W : 16, 14, _panelFor(ai, "AI", AI_COLOR));
    if (!hum) bottom = b;
  }
  if (hum) _taintTag(ctx, 16, bottom + 8);
}

// ---- Readout cheats (altimeter, speed) ----------------------------------
// Altimeter (info readout): the chassis's ABSOLUTE elevation above the fixed kill-line
// level, in meters (y-down; see geom.altitudeAboveKillLine) — a constant reference, not
// the clearance over the hill directly below, so it reads true height along the track.
function _altitudeMeters(car) {
  if (!car) return 0;
  const p = car.chassisBody.GetPosition();
  return altitudeAboveKillLine(p.y);
}
// Speed meter (cheat): the WHOLE-VEHICLE center-of-mass velocity in m/s (mass-weighted
// mean of every body's CoM velocity). The chassis CoM orbits the vehicle CoM while the
// car spins, so a chassis-only reading wobbles; the combined CoM velocity is the true
// translational speed. x>0 is forward/right; world y is DOWN, so vertical is -vy.
function _speedComponents(car) {
  if (!car) return { h: 0, v: 0, total: 0 };
  const bodies = _vehicleBodies(car);
  let mx = 0, my = 0, mtot = 0;
  for (let i = 0; i < bodies.length; i++) {
    const m = bodies[i].GetMass(); if (!(m > 0)) continue;   // static/frozen bodies have mass 0
    const bv = bodies[i].GetLinearVelocity();
    mx += m * bv.x; my += m * bv.y; mtot += m;
  }
  if (mtot <= 0) {   // dead/frozen car — fall back to the chassis body
    const cv = car.chassisBody.GetLinearVelocity();
    return { h: cv.x, v: -cv.y, total: Math.sqrt(cv.x * cv.x + cv.y * cv.y) };
  }
  const vx = mx / mtot, vy = my / mtot;
  return { h: vx, v: -vy, total: Math.sqrt(vx * vx + vy * vy) };
}

// Ghost-replay data sources for the readout cheats. A ghost is a recorded pose stream
// (no live bodies), so both readouts anchor on the recorded WHOLE-VEHICLE CoM (pose.com),
// NOT the chassis origin, so they don't wobble. Altitude = elevation above the fixed
// kill-line level; speed = finite-difference of the CoM across neighbouring frames.
// Older poses fall back to chassis.
function _ghostRef(pose) { return (pose && pose.com) ? pose.com : (pose ? pose.chassis : null); }
function _ghostAltitudeMeters(pose) {
  const r = _ghostRef(pose);
  if (!r) return 0;
  return altitudeAboveKillLine(r.y);
}
function _ghostSpeedComponents(idx) {
  if (!S.ghostPoses || S.ghostPoses.length < 2) return { h: 0, v: 0, total: 0 };
  const i  = Math.max(0, Math.min(idx, S.ghostPoses.length - 1));
  const i0 = Math.max(0, i - 1), i1 = Math.min(S.ghostPoses.length - 1, i + 1);
  if (i1 === i0) return { h: 0, v: 0, total: 0 };
  const a = _ghostRef(S.ghostPoses[i0]), b = _ghostRef(S.ghostPoses[i1]);
  if (!a || !b) return { h: 0, v: 0, total: 0 };
  const dt = (i1 - i0) / FRAME_RATE;
  const vx = (b.x - a.x) / dt, vy = (b.y - a.y) / dt;
  return { h: vx, v: -vy, total: Math.sqrt(vx * vx + vy * vy) };
}

// One registry for every centre-screen "readout" cheat so EVERY render path (single
// screen, split-screen, ghost replay) draws them identically. Each render path builds
// a "cheat target" (a live car OR a replay frame) and calls drawCheatHUD once.
function cheatTargetFromCar(car) {
  return { altitude() { return _altitudeMeters(car); },
           speed() { return _speedComponents(car); } };
}
function cheatTargetFromGhost(pose, idx) {
  return { altitude() { return _ghostAltitudeMeters(pose); },
           speed() { return _ghostSpeedComponents(idx); } };
}
// Registry entries render top-to-bottom in this order. `on` reads the toggle flag;
// `line` turns a target into the display string; `color`/`size` style the text.
// To add a readout cheat: add its flag to state.S, a checkbox/key, a target accessor,
// and ONE entry here — it then appears in all modes automatically.
const CHEAT_HUD = [
  { color: "#9fd4ff",
    on() { return S.bpAltimeter; },
    line(t) { return `⛰ Altitude ${t.altitude().toFixed(1)} m`; } },
  { color: "#ffd27f", size: 20,
    on() { return S.bpSpeed; },
    line(t) { const s = t.speed();
      return `🚗 H ${s.h.toFixed(1)}  V ${s.v.toFixed(1)}  Tot ${s.total.toFixed(1)} m/s`; } },
  { color: "#9df0ff", size: 20,
    on() { return S.bpFlight; },
    line() { return `✈ Flight speed ${S.flightSpeed} m/s  (scroll to adjust)`; } },
  { color: "#ff9d6e", size: 20,
    on() { return S.bpRocket; },
    line() { return `🚀 Rocket thrust ${S.rocketAccel} m/s²  (scroll to adjust)`; } },
  { color: "#ffa0e0", size: 20,   // silent input change — say so on screen (K)
    on() { return S.bpReverse; },
    line() { return "🔄 Reversed controls"; } },
];
// Draw every enabled readout for `target`, stacked from topY down. Returns the y after
// the last line so callers can keep laying out below it if needed.
function drawCheatHUD(ctx, target, centerX, topY) {
  if (!target) return topY;
  let y = topY;
  for (let i = 0; i < CHEAT_HUD.length; i++) {
    const c = CHEAT_HUD[i];
    if (!c.on()) continue;
    drawReadout(ctx, c.line(target), centerX, y, c.color, c.size);
    y += 30;
  }
  return y;
}


// ---- Effects bookkeeping -----------------------------------------------------
let _fxLastMs = 0, _fxGen = -1;
let _endCard = null;          // cached end-card spec for the current all-dead state
let _allDeadAt = 0;           // wall ms when every player was first seen dead
let _ghostFinish = null;      // { poses, idx } — first ghost frame past the finish

function _endFade(since, now) { return since ? Math.max(0, Math.min(1, (now - since - 500) / 350)) : 0; }

// Death → shake; first finish → confetti. Stamps wall times the end cards fade from.
function _detectEvents(now) {
  const hasHuman = S.players.some(p => !p.isAI);
  for (const p of S.players) {
    if (p.dead && !p._fxDeadAt) {
      p._fxDeadAt = now;
      if (!p.beatTick && (!p.isAI || !hasHuman)) shake(9, 0.35);
    }
    if (p.beatTick && !p._fxBeatAt) { p._fxBeatAt = now; burstConfetti(stageWidth()); }
  }
  if (S.ghostPoses && S.ghostBeaten) {
    if (!_ghostFinish || _ghostFinish.poses !== S.ghostPoses) {
      const fx = finishPx() / SCALE;
      let idx = S.ghostPoses.findIndex(q => q.chassis.x >= fx);
      _ghostFinish = { poses: S.ghostPoses, idx, fired: false };
    }
    if (!_ghostFinish.fired && _ghostFinish.idx >= 0 && S.ghostIdx >= _ghostFinish.idx) {
      _ghostFinish.fired = true; burstConfetti(stageWidth());
    }
  }
}

function _ghostSeconds() {
  const fin = (_ghostFinish && _ghostFinish.poses === S.ghostPoses && _ghostFinish.idx >= 0) ? _ghostFinish.idx : Infinity;
  return Math.max(0, Math.min(S.ghostIdx, fin)) / FRAME_RATE;
}

const HINT = [["R", "Restart"], ["T", "New map"]];

let _recCache = null;   // record rows, read once per end card (not every frame)
function _recRows() {
  if (_recCache) return _recCache;
  const m = mapRecord(S.mapKey), g = globalRecord();
  _recCache = [["Best on this map  (score · finish)", _recValue(m)],
               ["Best on any map  (score · finish)", _recValue(g)]];
  if (showCheatRecords()) {
    const ga = globalRecordAll();
    _recCache.push(["Incl. cheats · this map", _recValueAll(mapRecordAll(S.mapKey))],
                   ["Incl. cheats · any map", _recValueAll({ score: ga.score, scoreCheated: ga.scoreCheated,
                                                             time: ga.time, timeCheated: ga.timeCheated })]);
  }
  return _recCache;
}
// Cheat-track badges (red), shown only with "Show cheat records" on.
const CHEAT_BADGE = t => ({ text: t, bg: CHEAT_RED, fg: "#3a0000" });
function _cheatBadge(r, glob, map, hadPrev) {
  if (!r.cheated || !showCheatRecords()) return null;
  if (glob) return CHEAT_BADGE("CHEAT RECORD");
  if (map && hadPrev) return CHEAT_BADGE("CHEAT MAP BEST");
  return null;
}
function _scoreBadge(p) {
  const r = p.newRec || {};
  if (r.globalScore) return "NEW RECORD";
  if (r.mapScore && S.recStart && S.recStart.map.bestScore > 0) return "MAP BEST";
  return _cheatBadge(r, r.allGlobalScore, r.allMapScore, S.recStart && S.recStart.all.score > 0);
}
function _timeBadge(p) {
  const r = p.newRec || {};
  if (r.globalTime) return "NEW RECORD";
  if (r.mapTime && S.recStart && S.recStart.map.bestTime != null) return "MAP BEST";
  return _cheatBadge(r, r.allGlobalTime, r.allMapTime, S.recStart && S.recStart.all.time != null);
}
// Score breakdown row for a finished run that kept going past the natural fly-off
// (cheats only; last part red) or had a legendary clean fly-off (gold ✦).
const GOLD = "#ffd27f";
function _partsRows(p) {
  const pt = p && scoreParts(p);
  if (!pt) return [];
  const legend = !S.runTainted && pt.flyoff >= LEGENDARY_FLYOFF;
  if (!pt.after && !legend) return [];
  const fly = `${pt.flyoff} (${pt.flyoffSec.toFixed(1)}s)`;
  return [[legend ? "✦ Legendary fly-off · split" : "Split: to finish · fly-off · after",
           [[`${pt.toFinish}  ·  `, "#c9d4e2"], [legend ? `✦${fly}` : fly, legend ? GOLD : "#c9d4e2"],
            ["  ·  ", "#c9d4e2"], pt.after ? [`↗${pt.after}`, CHEAT_RED] : ["0", "#c9d4e2"]]]];
}
function _runLine(p) { return `${scoreOf(p)}  ·  ${p.beatTick ? fmtTime(runSeconds(p)) : "DNF"}`; }
// A run that made this map notable. Kept only through cheats: it lists with the cheat records.
function _keptRows(p) {
  const r = p.newRec;
  if (!r || !r.kept) return [];
  return [[r.keptCheatOnly ? "Map kept in cheat records" : "Map kept in Records", r.kept]];
}

// End card for the single-screen modes, built once when everyone is dead.
function _buildEndCard() {
  let ai = null, hum = null, aiB = null;
  for (const p of S.players) { if (p.aiB) aiB = p; else if (p.isAI) ai = p; else hum = p; }
  const WIN = "#7dffa6", LOSE = "#ff8a80";
  const card = { rows: [], hint: HINT };
  const taintNote = "Cheats were on — counts only toward cheat records";
  if (aiB && ai) {   // dev AI vs AI
    let aWins = null;
    if (ai.beatTick || aiB.beatTick) aWins = ai.beatTick && (!aiB.beatTick || ai.beatTick <= aiB.beatTick);
    else if (scoreOf(ai) !== scoreOf(aiB)) aWins = scoreOf(ai) > scoreOf(aiB);
    card.title = aWins === null ? "TIE!" : aWins ? "MAIN AI WINS" : "AI B WINS";
    card.color = GOLD;
    card.subtitle = (ai.beatTick || aiB.beatTick) ? "First to the finish wins" : "Nobody finished — farthest run wins";
    card.rows.push(["Main AI  (score · time)", _runLine(ai)], ..._partsRows(ai));
    card.rows.push(["AI B  (score · time)", _runLine(aiB)], ..._partsRows(aiB));
  } else if (S.mode === "vs" && hum && ai) {
    let humanWins;
    if (hum.beatTick || ai.beatTick) {
      humanWins = hum.beatTick && (!ai.beatTick || hum.beatTick <= ai.beatTick);
      card.subtitle = humanWins ? "You reached the finish first" : "The AI reached the finish first";
    } else {
      const hs = scoreOf(hum), as = scoreOf(ai);
      humanWins = hs > as;
      if (hs === as) { card.title = "TIE!"; card.color = GOLD; }
      card.subtitle = humanWins ? "You went farther" : "The AI went farther";
    }
    if (!card.title) { card.title = humanWins ? "YOU WIN!" : "AI WINS"; card.color = humanWins ? WIN : LOSE; }
    if (S.runTainted) card.subtitle = taintNote;
    card.rows.push(["You  (score · time)", _runLine(hum), _scoreBadge(hum) || _timeBadge(hum)], ..._partsRows(hum));
    card.rows.push(["AI  (score · time)", _runLine(ai)], ..._partsRows(ai));
    card.rows.push(..._keptRows(hum));
    card.rows.push(..._recRows());
  } else if (hum) {
    card.title = hum.beatTick ? "YOU BEAT THE GAME!" : "CRASHED!";
    card.color = hum.beatTick ? WIN : LOSE;
    card.subtitle = S.runTainted ? taintNote : (S.currentTerrainName || "");
    card.rows.push(["Score", String(scoreOf(hum)), _scoreBadge(hum)], ..._partsRows(hum));
    if (hum.beatTick) card.rows.push(["Finish time", fmtTime(runSeconds(hum)), _timeBadge(hum)]);
    card.rows.push(..._keptRows(hum));
    card.rows.push(..._recRows());
  } else if (ai) {
    card.title = ai.beatTick ? "AI BEAT THE GAME!" : "AI CRASHED";
    card.color = ai.beatTick ? WIN : LOSE;
    card.rows.push(["Score", String(scoreOf(ai))], ..._partsRows(ai));
    card.rows.push(["Time", ai.beatTick ? fmtTime(runSeconds(ai)) : `${fmtTime(runSeconds(ai))} (crashed)`]);
  }
  return card;
}

export function render() {
  const cv = document.getElementById("stage");
  const ctx = cv.getContext("2d");
  const alpha = _renderAlpha();   // fraction of a tick between the last two physics states
  const now = performance.now();
  const dt = _fxLastMs ? Math.min(0.1, (now - _fxLastMs) / 1000) : 0;
  _fxLastMs = now;
  if (S.worldGen !== _fxGen) { _fxGen = S.worldGen; clearFx(); _endCard = null; _allDeadAt = 0; _recCache = null; }
  if (!S.paused) {
    const simDt = dt * S.simSpeed;   // dirt lives in sim time so slow-mo slows it too
    stepFx(dt, simDt);
    if (!S.ghostPoses) for (const p of S.players) emitDust(p, simDt);
  }
  _detectEvents(now);
  _toggleWant = null;

  // Human-vs-Human: two live cars on the same terrain, side-by-side split screen.
  if (modeDef(S.mode).split && !S.ghostPoses && S.players.length >= 2) renderSplit(ctx, alpha, now);
  else _renderSingle(ctx, alpha, now);
  drawConfetti(ctx);
  _syncEndToggle();
}

// "Show cheat records" checkbox: a DOM overlay just under the canvas-drawn end card
// (only on cards that list human records). Card rect is in logical canvas units.
let _toggleWant = null;
function _syncEndToggle() {
  const el = document.getElementById("endcard_cheats");
  if (!el) return;
  if (!_toggleWant) { if (el.style.display !== "none") el.style.display = "none"; return; }
  const cv = document.getElementById("stage");
  const k = cv.clientWidth / _toggleWant.lw;
  const t = _toggleWant;
  el.style.display = "flex";
  el.style.left = `${cv.offsetLeft + (t.x + t.w / 2) * k}px`;
  el.style.top = `${cv.offsetTop + (t.y + t.h + 12) * k}px`;
  el.style.opacity = String(t.a);
  const cb = el.querySelector("input");
  if (cb.checked !== showCheatRecords()) cb.checked = showCheatRecords();
}
// Toggling (here or in the Records menu) rebuilds the cached card text.
document.addEventListener("hcr-cheat-records-toggled", () => { _endCard = null; _recCache = null; });

function _renderSingle(ctx, alpha, now) {
  // Camera target: prefer the LIVING human so they can always see themselves; once the
  // human dies, hand off to the AI. Falls back to whatever's alive (or any player).
  let focus = null;
  for (let pi = 0; pi < S.players.length; pi++) {
    if (!S.players[pi].isAI && !S.players[pi].dead) { focus = S.players[pi]; break; }
  }
  if (focus === null) {
    for (let pi = 0; pi < S.players.length; pi++) {
      if (S.players[pi].isAI && !S.players[pi].dead) { focus = S.players[pi]; break; }
    }
  }
  if (focus === null && S.players.length > 0) focus = S.players[0];
  // Ghost pose: interpolate toward the KNOWN next recorded frame (a recording has no
  // latency to hide); holds the final frame once done.
  let ghostPose = null;
  if (S.ghostPoses && S.ghostPoses.length) {
    const gi = Math.max(0, Math.min(S.ghostIdx, S.ghostPoses.length - 1));
    const giNext = Math.min(gi + 1, S.ghostPoses.length - 1);
    ghostPose = (giNext === gi || S.ghostDone)
      ? S.ghostPoses[gi]
      : _lerpCarPose(S.ghostPoses[gi], S.ghostPoses[giNext], alpha);
  }
  const focusPose = focus ? _playerDrawPose(focus, alpha) : null;
  const focusCar = focusPose ? focusPose.chassis
                 : (focus ? focus.car.chassisBody.GetPosition() : null);
  let focusX = focusCar ? focusCar.x * SCALE : SPAWN_X;
  if (ghostPose) focusX = ghostPose.chassis.x * SCALE;
  let focusYworld = focusCar ? focusCar.y * SCALE : 0;
  if (ghostPose) focusYworld = ghostPose.chassis.y * SCALE;
  _followCamera(S.cam0, focusX, focusYworld, SPAWN_X);
  S.cameraPanX = S.cam0.panX; S.cameraPanY = S.cam0.panY;   // publish to the globals the helpers read

  const [ox, oy] = shakeOffset();
  ctx.save();
  ctx.translate(ox, oy);
  _drawScenery(ctx, CANVAS_WIDTH, now / 1000);
  drawDust(ctx);
  if (ghostPose) {
    _drawCarFromPose(ctx, ghostPose, AI_COLOR, S.ghostDims);
  } else {
    for (let pi = 0; pi < S.players.length; pi++) {
      _drawCar(ctx, S.players[pi].car, S.players[pi].color, S.players[pi].isAI,
               _playerDrawPose(S.players[pi], alpha));
    }
    drawDevWorld(ctx, CANVAS_WIDTH);
  }
  ctx.restore();

  if (ghostPose) {
    const gx = ghostPose.chassis.x * SCALE;
    const finished = _ghostFinish && _ghostFinish.idx >= 0 && S.ghostIdx >= _ghostFinish.idx;
    drawProgressBar(ctx, CANVAS_WIDTH / 2, 30, 360, [{ frac: _progressFrac(gx), color: AI_COLOR.outline }], null);
    drawPlayerPanel(ctx, 16, 14, { label: "AI · replay", color: AI_COLOR.outline, score: scorePx(gx),
                                   time: fmtTime(_ghostSeconds()), lines: [], finished });
    drawCheatHUD(ctx, cheatTargetFromGhost(ghostPose, S.ghostIdx), CANVAS_WIDTH / 2, 74);
    if (S.ghostDone) {
      ctx.fillStyle = "rgba(6,10,20,0.35)";
      ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      drawEndCard(ctx, CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2 + 20, {
        title: S.ghostBeaten ? "AI BEAT THE GAME!" : "AI'S BEST RUN",
        color: S.ghostBeaten ? "#7dffa6" : "#ffd27f",
        subtitle: S.ghostBeaten ? "Found by rewind-and-retry search" : "Search budget ran out before the finish",
        rows: [["Score", String(Math.round(S.ghostScore))],
               ["Time", S.ghostBeaten ? fmtTime(_ghostSeconds()) : "DNF"]],
        hint: HINT,
      });
    }
    return;
  }

  _drawSingleScoreHUD(ctx);
  if (focus && focus.car) drawCheatHUD(ctx, cheatTargetFromCar(focus.car), CANVAS_WIDTH / 2, 74);
  drawDevHUD(ctx, CANVAS_WIDTH, S.players);

  const allDead = S.players.length > 0 && S.players.every(p => p.dead);
  if (!allDead) { _allDeadAt = 0; _endCard = null; _recCache = null; return; }
  if (!_allDeadAt) _allDeadAt = now;
  const a = _endFade(_allDeadAt, now);
  if (a <= 0) return;
  if (!_endCard) _endCard = _buildEndCard();
  ctx.fillStyle = `rgba(6,10,20,${(0.4 * a).toFixed(3)})`;
  ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
  const rect = drawEndCard(ctx, CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2 + 20, { ..._endCard, alpha: a });
  if (S.players.some(p => !p.isAI)) _toggleWant = { ...rect, a, lw: CANVAS_WIDTH };
}

// Draw ONE split-screen half (a full standard-width screen): its own camera following
// `ownP`, the shared world (both cars drawn), and this player's HUD.
function _drawViewport(ctx, cam, offsetX, viewWidth, ownP, oppP, ownName, oppName, ownColor, oppColor, alpha, now, bothDead) {
  const ownPose = _playerDrawPose(ownP, alpha);
  const fc = ownPose ? ownPose.chassis : ownP.car.chassisBody.GetPosition();
  _followCamera(cam, fc.x * SCALE, fc.y * SCALE, SPAWN_X);
  S.cameraPanX = cam.panX; S.cameraPanY = cam.panY;   // publish to globals for the draw helpers

  ctx.save();
  ctx.beginPath(); ctx.rect(offsetX, 0, viewWidth, CANVAS_HEIGHT); ctx.clip();
  ctx.translate(offsetX, 0);

  const [ox, oy] = shakeOffset();
  ctx.save();
  ctx.translate(ox, oy);
  _drawScenery(ctx, viewWidth, now / 1000);
  drawDust(ctx);
  for (let pi = 0; pi < S.players.length; pi++)
    _drawCar(ctx, S.players[pi].car, S.players[pi].color, S.players[pi].isAI,
             _playerDrawPose(S.players[pi], alpha));
  drawDevWorld(ctx, viewWidth);
  ctx.restore();

  _progressFor(ctx, viewWidth / 2, [ownP, oppP]);
  drawDevHUD(ctx, viewWidth, [ownP]);
  const bottom = drawPlayerPanel(ctx, 16, 14, _panelFor(ownP, ownName, ownColor));
  drawPlayerPanel(ctx, viewWidth - 16 - PANEL_W, 14, { ..._panelFor(oppP, oppName, oppColor), lines: [] });
  _taintTag(ctx, 16, bottom + 8);
  drawCheatHUD(ctx, cheatTargetFromCar(ownP.car), viewWidth / 2, 74);

  // A player who crossed the finish (beatTick) shows FINISHED — even after they fly off
  // into the void and die, that's still a win, so beatTick wins over dead.
  if (!bothDead) {
    const a = _endFade(ownP.beatTick ? ownP._fxBeatAt : ownP._fxDeadAt, now);
    if (a > 0) {
      ctx.fillStyle = `rgba(6,10,20,${(0.35 * a).toFixed(3)})`;
      ctx.fillRect(0, 0, viewWidth, CANVAS_HEIGHT);
      drawEndCard(ctx, viewWidth / 2, CANVAS_HEIGHT / 2 + 20, {
        title: ownP.beatTick ? "FINISHED!" : "CRASHED!", color: ownP.beatTick ? "#7dffa6" : "#ff8a80",
        subtitle: "Waiting for the other player…", width: 420, alpha: a,
        rows: [["Score", String(scoreOf(ownP))], ["Time", ownP.beatTick ? fmtTime(runSeconds(ownP)) : "DNF"]],
      });
    }
  }
  ctx.restore();
}

function renderSplit(ctx, alpha, now) {
  const W = CANVAS_WIDTH;   // each half is one full standard-width screen
  const pL = S.players[0], pR = S.players[1];
  const bothDead = pL.dead && pR.dead;
  // Left screen shows P1 (own, top-left) vs P2 (opp, top-right); right screen mirrors it.
  _drawViewport(ctx, S.camL, 0, W, pL, pR, "P1 · WASD",   "P2 · Arrows", HUMAN_L_COLOR, HUMAN_R_COLOR, alpha, now, bothDead);
  _drawViewport(ctx, S.camR, W, W, pR, pL, "P2 · Arrows", "P1 · WASD",   HUMAN_R_COLOR, HUMAN_L_COLOR, alpha, now, bothDead);

  // Divider between the two screens.
  ctx.save();
  ctx.fillStyle = "#0b1020";
  ctx.fillRect(W - 3, 0, 6, CANVAS_HEIGHT);
  ctx.restore();

  // Only reveal the conclusion once BOTH players are DEAD (fell off, hit their head, or
  // flew off the end after beating the game). The winner is whoever crossed the finish
  // first; if neither did, the higher score wins.
  if (!bothDead) { _recCache = null; return; }
  const a = _endFade(Math.max(pL._fxDeadAt || 0, pR._fxDeadAt || 0), now);
  if (a <= 0) return;
  let title, sub;
  if (pL.beatTick || pR.beatTick) {
    let lWins;
    if (pL.beatTick && pR.beatTick) {
      lWins = (pL.beatTick !== pR.beatTick) ? (pL.beatTick < pR.beatTick) : (pL.maxDistPx >= pR.maxDistPx);
    } else lWins = !!pL.beatTick;
    title = lWins ? "◀ P1 WINS" : "P2 WINS ▶";
    sub = (pL.beatTick && pR.beatTick) ? "Both finished — first to the flag wins" : "Reached the finish — opponent didn't";
  } else {
    const ls = scoreOf(pL), rs = scoreOf(pR);
    title = (ls === rs) ? "TIE!" : (ls > rs ? "◀ P1 WINS" : "P2 WINS ▶");
    sub = "Nobody finished — farthest run wins";
  }
  const stageW = stageWidth();
  ctx.fillStyle = `rgba(6,10,20,${(0.4 * a).toFixed(3)})`;
  ctx.fillRect(0, 0, stageW, CANVAS_HEIGHT);
  const rect = drawEndCard(ctx, stageW / 2, CANVAS_HEIGHT / 2 + 20, {
    title, color: "#ffd27f", subtitle: S.runTainted ? "Cheats were on — cheat records only" : sub,
    width: 600, alpha: a,
    rows: [["P1 · WASD  (score · time)", _runLine(pL), _scoreBadge(pL) || _timeBadge(pL)], ..._partsRows(pL),
           ["P2 · Arrows  (score · time)", _runLine(pR), _scoreBadge(pR) || _timeBadge(pR)], ..._partsRows(pR),
           ..._recRows()],
    hint: [["R", "Rematch"], ["T", "New map"]],
  });
  _toggleWant = { ...rect, a, lw: stageW };
}

// DOM bits that change per step: the "Replaying run…" chip while a ghost plays.
export function updateStats() {
  const repEl = document.getElementById("backtrack_replaying");
  if (repEl) repEl.style.display = (S.ghostPoses && !S.ghostDone) ? "inline-flex" : "none";
}
