// Background art drawn behind the terrain: gradient sky + sun, parallax clouds and
// hills, a textured dirt fill, and the finish / personal-best flags. Purely cosmetic
// — nothing here reads back into the physics or the AI's observations.
import { S, SCALE, SPAWN_X, CANVAS_HEIGHT } from "./state.js";

const PAD = 40;   // overdraw so screen shake never exposes the canvas edge

// ---- Cached sprites -------------------------------------------------------
let _clouds = null, _dirt = null;

// Deterministic PRNG so the scenery is identical every load.
function _rng(seed) {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6D2B79F5) >>> 0;
    let r = Math.imul(t ^ (t >>> 15), t | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function _makeClouds() {
  const rnd = _rng(7), out = [];
  for (let k = 0; k < 5; k++) {
    const w = 180 + rnd() * 140, h = 70 + rnd() * 30;
    const c = document.createElement("canvas");
    c.width = w; c.height = h * 1.7;          // headroom: puffs rise above the base
    const g = c.getContext("2d");
    g.translate(0, h * 0.7);
    const puffs = [];
    for (let i = 0; i < 7; i++) {
      const r = h * (0.28 + rnd() * 0.18);
      puffs.push([r + rnd() * (w - 2 * r), h - r - rnd() * h * 0.25, r]);
    }
    // soft blue underside, then the white body offset up
    g.fillStyle = "rgba(190,215,240,0.9)";
    for (const [x, y, r] of puffs) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill(); }
    g.fillStyle = "#fff";
    for (const [x, y, r] of puffs) { g.beginPath(); g.arc(x, y - r * 0.18, r * 0.92, 0, Math.PI * 2); g.fill(); }
    out.push(c);
  }
  return out;
}

function _makeDirt() {
  const N = 256, c = document.createElement("canvas");
  c.width = c.height = N;
  const g = c.getContext("2d"), rnd = _rng(42);
  g.fillStyle = "#6a3913"; g.fillRect(0, 0, N, N);
  for (let i = 0; i < 900; i++) {           // speckle
    g.fillStyle = rnd() < 0.5 ? "rgba(40,18,4,0.35)" : "rgba(150,90,40,0.25)";
    g.fillRect(rnd() * N, rnd() * N, 2 + rnd() * 2, 2 + rnd() * 2);
  }
  return c;
}

// ---- Sky + parallax -------------------------------------------------------
function _hillY(x, seed) {
  return Math.sin(x * 0.0021 + seed) * 0.5 + Math.sin(x * 0.0047 + seed * 2.3) * 0.3
       + Math.sin(x * 0.0111 + seed * 0.7) * 0.2;
}

function _drawHills(ctx, viewWidth, factor, baseY, amp, seed, fill, trees) {
  const off = S.cameraPanX * factor, offY = -S.cameraPanY * factor;
  const step = 16;
  ctx.fillStyle = fill;
  ctx.beginPath();
  ctx.moveTo(-PAD, CANVAS_HEIGHT + PAD);
  for (let sx = -PAD; sx <= viewWidth + PAD + step; sx += step) {
    ctx.lineTo(sx, baseY + offY - amp * _hillY(sx + off, seed));
  }
  ctx.lineTo(viewWidth + PAD + step, CANVAS_HEIGHT + PAD);
  ctx.closePath();
  ctx.fill();
  if (!trees) return;
  // Trees at fixed world-parallax positions along the ridge.
  const spacing = 140;
  const first = Math.floor((off - PAD) / spacing);
  for (let k = first; k * spacing - off < viewWidth + PAD; k++) {
    const h = Math.abs(Math.sin(k * 12.9898) * 43758.5453) % 1;   // hash → [0,1)
    if (h < 0.45) continue;
    const wx = k * spacing + h * 90, sx = wx - off;
    const gy = baseY + offY - amp * _hillY(wx, seed) + 4;
    const r = 10 + h * 10;
    ctx.fillStyle = "#4b3a24";
    ctx.fillRect(sx - 2, gy - r * 0.9, 4, r * 0.9);
    ctx.fillStyle = trees;
    ctx.beginPath(); ctx.arc(sx, gy - r * 1.3, r, 0, Math.PI * 2); ctx.fill();
  }
}

export function drawBackground(ctx, viewWidth) {
  if (!_clouds) { _clouds = _makeClouds(); _dirt = _makeDirt(); }
  const g = ctx.createLinearGradient(0, 0, 0, CANVAS_HEIGHT);
  g.addColorStop(0, "#3f8fdc");
  g.addColorStop(0.6, "#8cc4ee");
  g.addColorStop(1, "#d8eefa");
  ctx.fillStyle = g;
  ctx.fillRect(-PAD, -PAD, viewWidth + 2 * PAD, CANVAS_HEIGHT + 2 * PAD);

  // Sun (fixed in the sky, drifts only with vertical pan)
  const sx = viewWidth - 190, sy = 120 - S.cameraPanY * 0.03;
  const sun = ctx.createRadialGradient(sx, sy, 10, sx, sy, 120);
  sun.addColorStop(0, "rgba(255,250,220,1)");
  sun.addColorStop(0.3, "rgba(255,240,180,0.55)");
  sun.addColorStop(1, "rgba(255,240,180,0)");
  ctx.fillStyle = sun;
  ctx.fillRect(sx - 120, sy - 120, 240, 240);

  // Clouds, repeating every WRAP px of parallax space.
  const WRAP = 2400, cf = 0.08;
  const cOff = S.cameraPanX * cf;
  for (let i = 0; i < 9; i++) {
    const img = _clouds[i % _clouds.length];
    const base = i * 267 + (i * 97) % 130;
    let x = ((base - cOff) % WRAP + WRAP) % WRAP - 300;
    const y = 40 + ((i * 53) % 170) - S.cameraPanY * cf;
    if (x > viewWidth + 50) continue;
    ctx.globalAlpha = 0.85;
    ctx.drawImage(img, x, y);
    ctx.globalAlpha = 1;
  }

  _drawHills(ctx, viewWidth, 0.12, 430, 90, 1.3, "#a9cbd6", null);
  _drawHills(ctx, viewWidth, 0.3, 500, 80, 4.1, "#7fb38a", "#5d9a66");
}

// Integer hash of a pebble cell → 4 values in [0,1). Pebbles are placed per world
// cell (not baked into the repeating dirt tile) so they never visibly repeat. Seeded
// by the map key: each map gets its own pebbles, the same every time it's loaded.
let _seedKey = null, _seed = 0;
function _mapSeed() {
  if (S.mapKey !== _seedKey) {
    _seedKey = S.mapKey;
    _seed = 0x9e3779b9;
    for (let i = 0; i < _seedKey.length; i++) _seed = Math.imul(_seed ^ _seedKey.charCodeAt(i), 0x01000193);
  }
  return _seed;
}
function _cellRand(cx, cy, seed) {
  let h = Math.imul(cx, 0x27d4eb2d) ^ Math.imul(cy, 0x165667b1) ^ seed;
  const out = [];
  for (let i = 0; i < 4; i++) {
    h = Math.imul(h ^ (h >>> 15), 0x2c1b3c6d); h ^= h + Math.imul(h ^ (h >>> 7), 0x297a2d39);
    out.push(((h ^ (h >>> 14)) >>> 0) / 4294967296);
  }
  return out;
}

const PEBBLE_CELL = 72;
function _drawPebbles(ctx, viewWidth) {
  const x0 = Math.floor((S.cameraPanX - PAD - 12) / PEBBLE_CELL);
  const x1 = Math.floor((S.cameraPanX + viewWidth + PAD + 12) / PEBBLE_CELL);
  const y0 = Math.floor((S.cameraPanY - PAD - 12) / PEBBLE_CELL);
  const y1 = Math.floor((S.cameraPanY + CANVAS_HEIGHT + 60 + 12) / PEBBLE_CELL);
  const peb = [];
  const seed = _mapSeed();
  for (let cx = x0; cx <= x1; cx++) for (let cy = y0; cy <= y1; cy++) {
    const [a, b, c, d] = _cellRand(cx, cy, seed);
    if (d < 0.3) continue;
    const rx = 3 + c * 8, ry = rx * (0.55 + d * 0.3);
    peb.push([(cx + a) * PEBBLE_CELL - S.cameraPanX, (cy + b) * PEBBLE_CELL - S.cameraPanY, rx, ry]);
  }
  // One path per layer (shadow, body, highlight) keeps it to 3 fills per frame.
  const layer = (color, dx, dy, sx, sy, ox, oy) => {
    ctx.fillStyle = color; ctx.beginPath();
    for (const [x, y, rx, ry] of peb) {
      const px = x + dx + rx * ox, py = y + dy + ry * oy;
      ctx.moveTo(px + rx * sx, py);
      ctx.ellipse(px, py, rx * sx, ry * sy, 0, 0, Math.PI * 2);
    }
    ctx.fill();
  };
  layer("#4a2609", 1, 2, 1, 1, 0, 0);
  layer("#8d5a2b", 0, 0, 1, 1, 0, 0);
  layer("rgba(255,220,170,0.25)", 0, 0, 0.4, 0.3, -0.3, -0.35);
}

// Dirt fill for the terrain polygon (already built as the current path by the caller).
export function fillDirt(ctx, viewWidth) {
  const pat = ctx.createPattern(_dirt, "repeat");
  pat.setTransform(new DOMMatrix().translate(-S.cameraPanX, -S.cameraPanY));
  ctx.fillStyle = pat;
  ctx.fill();
  ctx.save();
  ctx.clip();
  _drawPebbles(ctx, viewWidth);
  // Darken with depth.
  const g = ctx.createLinearGradient(0, 300 - S.cameraPanY, 0, CANVAS_HEIGHT + 200 - S.cameraPanY);
  g.addColorStop(0, "rgba(20,8,0,0)");
  g.addColorStop(1, "rgba(20,8,0,0.55)");
  ctx.fillStyle = g;
  ctx.fillRect(-PAD, -PAD, viewWidth + 2 * PAD, CANVAS_HEIGHT + 60 + 2 * PAD);
  ctx.restore();
}

// ---- Flags ----------------------------------------------------------------
// Terrain surface y (px, world) at world x (px), by binary search over the top vertices.
export function groundYAtPx(xpx) {
  const v = S.ground && S.ground.vectors;
  if (!v || v.length < 3) return 0;
  const xm = xpx / SCALE;
  let lo = 0, hi = v.length - 3;
  if (xm <= v[0].x) return v[0].y * SCALE;
  if (xm >= v[hi].x) return v[hi].y * SCALE;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (v[mid].x <= xm) lo = mid; else hi = mid; }
  const t = (xm - v[lo].x) / (v[hi].x - v[lo].x || 1);
  return (v[lo].y + (v[hi].y - v[lo].y) * t) * SCALE;
}

export function finishPx() { return S.ground ? S.ground.distance - S.ground.smoothness : 0; }

export function drawFinishFlag(ctx, viewWidth, timeSec) {
  if (!S.ground) return;
  const wx = finishPx();
  const x = wx - S.cameraPanX;
  if (x < -80 || x > viewWidth + 80) return;
  const y = groundYAtPx(wx) - S.cameraPanY;
  const poleH = 110;
  ctx.fillStyle = "#eee"; ctx.fillRect(x - 2, y - poleH, 4, poleH);
  ctx.fillStyle = "#333"; ctx.beginPath(); ctx.arc(x, y - poleH, 4, 0, Math.PI * 2); ctx.fill();
  // Checkered flag with a gentle wave.
  const cols = 6, rows = 4, cw = 9, chh = 9;
  for (let c = 0; c < cols; c++) {
    const wave = Math.sin(timeSec * 5 + c * 0.9) * 3 * (c / cols);
    for (let r = 0; r < rows; r++) {
      ctx.fillStyle = (r + c) % 2 ? "#111" : "#fff";
      ctx.fillRect(x + 2 + c * cw, y - poleH + 2 + r * chh + wave, cw + 0.5, chh + 0.5);
    }
  }
  ctx.save();
  ctx.font = `20px ${DISPLAY_FONT}`;
  ctx.textAlign = "center";
  ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,0.6)"; ctx.lineJoin = "round";
  ctx.strokeText("FINISH", x, y - poleH - 12);
  ctx.fillStyle = "#fff"; ctx.fillText("FINISH", x, y - poleH - 12);
  ctx.restore();
}

// Gold pennant where your best run on this map ended.
export function drawBestFlag(ctx, viewWidth, score) {
  if (!score || !S.ground) return;
  const wx = score * 10 + SPAWN_X;
  const x = wx - S.cameraPanX;
  if (x < -60 || x > viewWidth + 60 || wx >= finishPx()) return;
  const y = groundYAtPx(wx) - S.cameraPanY;
  ctx.save();
  ctx.font = `13px ${DISPLAY_FONT}`;
  // Swallowtail pennant sized to the text, so the label always fits inside it.
  const w = ctx.measureText("BEST").width + 12, notch = 6, top = y - 64, h = 20;
  ctx.fillStyle = "rgba(255,255,255,0.85)"; ctx.fillRect(x - 1.5, top, 3, 64);
  ctx.fillStyle = "#ffc933";
  ctx.beginPath();
  ctx.moveTo(x + 1.5, top); ctx.lineTo(x + 1.5 + w + notch, top);
  ctx.lineTo(x + 1.5 + w, top + h / 2); ctx.lineTo(x + 1.5 + w + notch, top + h);
  ctx.lineTo(x + 1.5, top + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#5a3d00"; ctx.textBaseline = "middle"; ctx.fillText("BEST", x + 7, top + h / 2 + 1);
  ctx.restore();
}

export const DISPLAY_FONT = `"Lilita One", "Arial Black", sans-serif`;
export const UI_FONT = `"Nunito", "Segoe UI", system-ui, sans-serif`;
