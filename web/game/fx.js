// Cosmetic effects: wheel dust + dirt clods (world space), screen shake, and confetti
// (screen space). Advanced from render(), not the physics step, so they never touch the physics.
import { S, SCALE, CANVAS_HEIGHT } from "./state.js";

const puffs = [];     // soft dust haze
const clods = [];     // small ballistic dirt/grass bits
const confetti = [];
let shakeT = 0, shakeMag = 0;
const MAX_PUFFS = 260, MAX_CLODS = 140;
const PUFF_FRESH = "150,110,70", PUFF_OLD = "200,184,158";   // colour drifts toward pale haze
const CLOD_COLORS = ["#5a3a1e", "#6b4526", "#4a2f18", "#7a5230"];
const GRASS_FLECK = "#3f8f2a";
const LAYER_ALPHA = 0.7;

// Pre-baked lumpy, soft-edged puff sprites (a few overlapping radial blobs), one set
// per tone so a puff can cross-fade fresh -> old. Same shape index in both sets.
const SPRITE_PX = 64, N_SHAPES = 4;
function _bakePuff(rgb, blobs) {
  const c = document.createElement("canvas");
  c.width = c.height = SPRITE_PX;
  const g = c.getContext("2d"), h = SPRITE_PX / 2;
  for (const b of blobs) {
    const bx = h + b.x * h, by = h + b.y * h;
    const gr = g.createRadialGradient(bx, by, 0, bx, by, b.r * h);
    gr.addColorStop(0, `rgba(${rgb},0.9)`);
    gr.addColorStop(0.5, `rgba(${rgb},0.45)`);
    gr.addColorStop(1, `rgba(${rgb},0)`);
    g.fillStyle = gr;
    g.fillRect(0, 0, SPRITE_PX, SPRITE_PX);
  }
  return c;
}
const _shapes = Array.from({ length: N_SHAPES }, () => {
  const blobs = [{ x: 0, y: 0, r: 0.6 }];
  const k = 3 + Math.floor(Math.random() * 3);
  for (let i = 0; i < k; i++) {
    const a = Math.random() * Math.PI * 2, d = 0.25 + Math.random() * 0.2;
    blobs.push({ x: Math.cos(a) * d, y: Math.sin(a) * d, r: 0.3 + Math.random() * 0.2 });
  }
  return blobs;
});
const _freshSprites = _shapes.map(b => _bakePuff(PUFF_FRESH, b));
const _oldSprites = _shapes.map(b => _bakePuff(PUFF_OLD, b));

// Offscreen layer the puffs are flattened into, then composited once, so overlaps
// merge into one cloud instead of stacking into darker lens shapes.
let _layer = null, _lctx = null;
function _layerFor(cv) {
  if (!_layer) { _layer = document.createElement("canvas"); _lctx = _layer.getContext("2d"); }
  if (_layer.width !== cv.width || _layer.height !== cv.height) { _layer.width = cv.width; _layer.height = cv.height; }
  return _lctx;
}

// Emit dust + clods per wheel, scaled by the friction heat (J) sim.js's contact listener
// accumulated since the last frame. Spinning out or a skidding landing runs ~1-4 kW.
const PUFFS_PER_J = 0.015, CLODS_PER_J = 0.03, KICK_FULL_W = 3000;
export function emitDust(p, dt) {
  const car = p.car;
  if (!car) return;
  // Capped so heat banked while rendering was skipped (search, ghost replay) can't burst.
  const hMax = 2 * KICK_FULL_W * Math.max(dt, 1 / 30);
  const heat = car.wheels.map(w => { const h = Math.min(w.fxHeat || 0, hMax), d = w.fxHeatDir || 0; w.fxHeat = w.fxHeatDir = 0; return [h, d]; });
  if (p.dead) return;
  const v = car.chassisBody.GetLinearVelocity();
  car.wheels.forEach((w, i) => {
    const [h, hd] = heat[i];
    if (h <= 0) return;
    const dir = Math.sign(hd);                   // dirt leaves with the contact patch
    const kick = 1 + Math.min(h / Math.max(dt, 1e-3), KICK_FULL_W) / KICK_FULL_W * 0.8;   // harder skid throws clods farther
    const c = w.body.GetPosition();
    const cx = c.x * SCALE, cy = c.y * SCALE + w.radius * 0.8;
    let n = h * PUFFS_PER_J;
    while (n > 0 && puffs.length < MAX_PUFFS) {
      if (n < 1 && Math.random() > n) break;
      n -= 1;
      const r0 = 3 + Math.random() * 3;
      puffs.push({
        x: cx + (Math.random() - 0.5) * 10, y: cy - Math.random() * 4,
        vx: dir * (20 + Math.random() * 50) + v.x * SCALE * 0.15,
        vy: -(15 + Math.random() * 35),
        r0, r1: r0 + 14 + Math.random() * 16, r: r0,
        rot: Math.random() * Math.PI * 2, vr: (Math.random() - 0.5) * 1.5,
        s: Math.floor(Math.random() * N_SHAPES), life: 0, max: 0.7 + Math.random() * 0.6,
      });
    }
    n = h * CLODS_PER_J;
    while (n > 0 && clods.length < MAX_CLODS) {
      if (n < 1 && Math.random() > n) break;
      n -= 1;
      clods.push({
        x: cx + (Math.random() - 0.5) * 8, y: cy - 2,
        vx: dir * (60 + Math.random() * 120) * kick + v.x * SCALE * 0.3,
        vy: -(60 + Math.random() * 130) * kick,
        sz: 1.8 + Math.random() * 2.2, rot: Math.random() * Math.PI * 2, vr: (Math.random() - 0.5) * 20,
        c: Math.random() < 0.2 ? GRASS_FLECK : CLOD_COLORS[Math.floor(Math.random() * CLOD_COLORS.length)],
        life: 0, max: 0.5 + Math.random() * 0.4,
      });
    }
  });
}

export function shake(mag, dur) { shakeMag = Math.max(shakeMag, mag); shakeT = Math.max(shakeT, dur); }
export function shakeOffset() {
  if (shakeT <= 0) return [0, 0];
  const m = shakeMag * Math.min(1, shakeT * 4);
  return [(Math.random() - 0.5) * 2 * m, (Math.random() - 0.5) * 2 * m];
}

const CONF_COLORS = ["#ff5a5a", "#ffc933", "#5cd65c", "#4fb3ff", "#c77dff", "#ff8fd1"];
export function burstConfetti(width) {
  for (let i = 0; i < 180; i++) {
    confetti.push({
      x: Math.random() * width, y: -20 - Math.random() * 200,
      vx: (Math.random() - 0.5) * 120, vy: 60 + Math.random() * 160,
      rot: Math.random() * 6.28, vr: (Math.random() - 0.5) * 10,
      w: 6 + Math.random() * 6, h: 3 + Math.random() * 4,
      c: CONF_COLORS[i % CONF_COLORS.length], life: 0, max: 3.5 + Math.random() * 1.5,
    });
  }
}

// dt is wall-clock (shake, confetti); simDt is dt × sim speed (dust, clods).
export function stepFx(dt, simDt = dt) {
  shakeT = Math.max(0, shakeT - dt);
  if (shakeT === 0) shakeMag = 0;
  stepDirt(simDt);
  for (let i = confetti.length - 1; i >= 0; i--) {
    const c = confetti[i];
    c.life += dt;
    if (c.life >= c.max || c.y > CANVAS_HEIGHT + 30) { confetti.splice(i, 1); continue; }
    c.x += (c.vx + Math.sin(c.life * 3 + c.rot) * 40) * dt;
    c.y += c.vy * dt; c.rot += c.vr * dt;
  }
}

function stepDirt(dt) {
  const drag = Math.exp(-2.5 * dt);
  for (let i = puffs.length - 1; i >= 0; i--) {
    const d = puffs[i];
    d.life += dt;
    if (d.life >= d.max) { puffs.splice(i, 1); continue; }
    d.x += d.vx * dt; d.y += d.vy * dt;
    d.vx *= drag; d.vy = d.vy * drag - 12 * dt;    // heavy drag + slight buoyancy
    d.rot += d.vr * dt;
    const t = d.life / d.max;
    d.r = d.r0 + (d.r1 - d.r0) * (1 - (1 - t) ** 3);   // ease-out growth
  }
  for (let i = clods.length - 1; i >= 0; i--) {
    const c = clods[i];
    c.life += dt;
    if (c.life >= c.max) { clods.splice(i, 1); continue; }
    c.x += c.vx * dt; c.y += c.vy * dt;
    c.vy += 600 * dt; c.rot += c.vr * dt;
  }
}

export function clearFx() { puffs.length = 0; clods.length = 0; confetti.length = 0; shakeT = 0; }

export function drawDust(ctx) {
  if (puffs.length) {
    const L = _layerFor(ctx.canvas);
    L.setTransform(1, 0, 0, 1, 0, 0);
    L.clearRect(0, 0, _layer.width, _layer.height);
    const base = ctx.getTransform();             // inherit DPR scale / shake / split offset
    for (const d of puffs) {
      const t = d.life / d.max;
      const a = t < 0.12 ? t / 0.12 : Math.pow((1 - t) / 0.88, 1.5);   // quick in, long fade
      const mix = t * t;
      L.setTransform(base);
      L.translate(d.x - S.cameraPanX, d.y - S.cameraPanY);
      L.rotate(d.rot);
      const sz = d.r * 2;
      L.globalAlpha = a * (1 - mix);
      L.drawImage(_freshSprites[d.s], -d.r, -d.r, sz, sz);
      L.globalAlpha = a * mix;
      L.drawImage(_oldSprites[d.s], -d.r, -d.r, sz, sz);
    }
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = LAYER_ALPHA;
    ctx.drawImage(_layer, 0, 0);
    ctx.restore();
  }
  for (const c of clods) {
    ctx.save();
    ctx.globalAlpha = Math.min(1, (1 - c.life / c.max) * 3);
    ctx.translate(c.x - S.cameraPanX, c.y - S.cameraPanY);
    ctx.rotate(c.rot);
    ctx.fillStyle = c.c;
    ctx.beginPath();                              // irregular quad, not a square
    ctx.moveTo(-c.sz, -c.sz * 0.6); ctx.lineTo(c.sz * 0.8, -c.sz);
    ctx.lineTo(c.sz, c.sz * 0.7); ctx.lineTo(-c.sz * 0.7, c.sz);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }
}

export function drawConfetti(ctx) {
  for (const c of confetti) {
    ctx.save();
    ctx.globalAlpha = Math.min(1, (c.max - c.life) * 2);
    ctx.translate(c.x, c.y); ctx.rotate(c.rot);
    ctx.fillStyle = c.c;
    ctx.fillRect(-c.w / 2, -c.h / 2, c.w, c.h * Math.abs(Math.cos(c.life * 6 + c.rot)));
    ctx.restore();
  }
}
