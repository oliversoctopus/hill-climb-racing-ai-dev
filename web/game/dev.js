// Dev mode: password-gated developer tools — AI-vision + Box2D debug overlays, frame
// step + quick-save/load, loading other models (and the AI-vs-AI mode), map JSON
// import/export for the Python harness, plus the spin presets and bug probe.
// The gate is a curtain, not security: the check runs client-side and all of this code
// ships to everyone. It only keeps clutter away from players.
import { S, SCALE, SPAWN_X, SIM_DT, CANVAS_HEIGHT } from "./state.js";
import { Car, Box2D, Vec2, AiPolicy, getSpawningY } from "./bridge.js";
import { runOneStep, snapRenderPoses, freezeCar } from "./sim.js";
import { bpSetStatus, showToast } from "./cheats.js";

// sha256(DEV_SALT + password). Change the password: recompute this and commit.
const DEV_SALT = "hcr-dev-v1:";
const DEV_HASH = "8b76f433375a6a83dba1e50afba0d39947817f6b567ec7824a98ee7f6e661ed3";
const DEV_KEY = "hcr_dev_unlocked";

const $ = id => document.getElementById(id);
let _hooks = { loadTerrain: null, setStatus: () => {} };
let _deployedA = null, _deployedB = null;   // the page's own ai_policy.onnx agents

async function _sha256Hex(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, "0")).join("");
}

// ---- Gate ------------------------------------------------------------------
function _applyDevClass() { document.body.classList.toggle("dev", S.devMode); }

async function _ensureAgentB() {
  if (S.aiAgent2 || !S.aiAgent) return;
  const b = new AiPolicy.PpoOnnxAgent("ai_policy.onnx");
  await b.init();
  _deployedB = S.aiAgent2 = b;
  _syncModelLabels();
}

async function _unlock(pw) {
  if (!window.crypto || !crypto.subtle) { $("dev_err").textContent = "Needs https:// or localhost (no WebCrypto here)."; return; }
  if (await _sha256Hex(DEV_SALT + pw) !== DEV_HASH) { $("dev_err").textContent = "Wrong password."; return; }
  S.devMode = true;
  try { localStorage.setItem(DEV_KEY, "1"); } catch (e) {}
  _applyDevClass();
  $("dev_panel").style.display = "none";
  $("dev_pw").value = "";
  showToast("🔧 Dev mode unlocked — see the Tools drawer");
  _ensureAgentB().catch(e => bpSetStatus(`AI B failed to load: ${e.message}`));
}

function _lock() {
  S.devMode = false;
  try { localStorage.removeItem(DEV_KEY); } catch (e) {}
  S.devVision = S.devB2D = false;
  $("dev_vision").checked = $("dev_b2d").checked = false;
  _slot = null;
  const sel = $("mode");
  if (S.aiAgent !== _deployedA && _deployedA) { S.aiAgent = _deployedA; _syncModelLabels(); if (sel.value !== "aivai") _restart(); }
  if (sel.value === "aivai" && !sel.disabled) { sel.value = "ai"; sel.dispatchEvent(new Event("change")); }
  _applyDevClass();
  showToast("Dev mode locked");
}

// Called from main.js once the main agent is loaded.
export async function devAfterInit() {
  _deployedA = S.aiAgent;
  if (S.devMode) await _ensureAgentB().catch(e => bpSetStatus(`AI B failed to load: ${e.message}`));
}

// ---- Frame step + quick-save/load -----------------------------------------
function _pause() { if (!S.paused) $("pause").click(); }

async function devStep() {
  if (S.bestofxBusy || S.inStep) return;
  _pause();
  S.inStep = true;
  try { await runOneStep(); } finally { S.inStep = false; }
  S.accumSec = SIM_DT * 0.9999;   // render the new tick's pose (alpha ≈ 1), not a lerp
}

// One quick-save slot: every car's bodies + the per-run bookkeeping + agent obs history.
const P_KEYS = ["maxDistPx", "stuckCount", "dead", "deadTick", "beatTick", "finishLinePx",
                "leftLipTick", "graceEndPx", "_fxDeadAt", "_fxBeatAt"];
let _slot = null;

function _saveCar(car) {
  const bodies = car.bodies().map(b => {
    const p = b.GetPosition(), v = b.GetLinearVelocity();
    return [p.x, p.y, b.GetAngle(), v.x, v.y, b.GetAngularVelocity()];
  });
  return { bodies, og0: car.wheels[0].onGround === true, og1: car.wheels[1].onGround === true,
           motorState: car.motorState, kindaDead: !!car.player.kindaDead,
           frozen: car.chassisBody.GetType() !== Box2D.Dynamics.b2Body.b2_dynamicBody };
}
// Same restore as the backtrack search: a fresh Car (joints re-baked, impulse cache
// cleared), then teleport each body to its saved pose/velocity. Every load replays the
// same future bit-exactly, but not the ORIGINAL run's (Box2D's warm-start caches are lost).
function _restoreCar(p, s) {
  const pl = p.car.player;
  p.car.destroy(S.world);
  pl.kindaDead = s.kindaDead;
  p.car = new Car(SPAWN_X, getSpawningY(), S.world, pl);
  const bs = p.car.bodies();
  for (let i = 0; i < bs.length; i++) {
    const r = s.bodies[i];
    bs[i].SetPositionAndAngle(new Vec2(r[0], r[1]), r[2]);
    bs[i].SetLinearVelocity(new Vec2(r[3], r[4]));
    bs[i].SetAngularVelocity(r[5]); bs[i].SetAwake(true);
  }
  p.car.wheels[0].onGround = s.og0;
  p.car.wheels[1].onGround = s.og1;
  if (s.motorState !== undefined) p.car.motorState = s.motorState;
  if (s.frozen) freezeCar(p.car);
}

function devQuickSave() {
  if (S.bestofxBusy || !S.world) return;
  _slot = {
    gen: S.worldGen, tick: S.tickCount, replayIdx: S.replayIdx, ghostIdx: S.ghostIdx,
    players: S.ghostPoses ? null : S.players.map(p => ({
      car: _saveCar(p.car),
      agent: p.agent && p.agent.snapshotState ? p.agent.snapshotState() : null,
      keys: Object.fromEntries(P_KEYS.map(k => [k, p[k]])),
    })),
  };
  showToast(`💾 Quick-saved at tick ${S.tickCount}`);
}

function devQuickLoad() {
  if (S.bestofxBusy) return;
  if (!_slot || _slot.gen !== S.worldGen || (_slot.players && _slot.players.length !== S.players.length)) {
    showToast("No quick-save for this run (Q saves)"); return;
  }
  S.worldGen += 1;   // an in-flight step against the old cars bails (see runOneStep)
  _slot.gen = S.worldGen;
  S.tickCount = _slot.tick; S.replayIdx = _slot.replayIdx; S.ghostIdx = _slot.ghostIdx;
  if (S.ghostPoses) { S.ghostDone = false; showToast(`⤺ Loaded tick ${S.tickCount}`); return; }
  S.players.forEach((p, i) => {
    const s = _slot.players[i];
    _restoreCar(p, s.car);
    if (s.agent) p.agent.restoreState(s.agent);
    for (const k of P_KEYS) p[k] = s.keys[k];
  });
  S.runTainted = S.runModified = true;   // save-scumming isn't a clean run
  snapRenderPoses();
  showToast(`⤺ Loaded tick ${S.tickCount} (run now counts as cheated)`);
}

// ---- Models ---------------------------------------------------------------
function _syncModelLabels() {
  const lbl = a => (!a ? "—" : (a === _deployedA || a === _deployedB) ? "deployed" : a.devLabel);
  $("dev_model_a").textContent = lbl(S.aiAgent);
  $("dev_model_b").textContent = lbl(S.aiAgent2);
}
function _restart() { $("reset_pos").click(); }   // same map, re-spawn with the current agents

let _loadTarget = "a";
async function _loadModel(files) {
  if (S.bestofxBusy) { bpSetStatus("Wait for the search to finish."); return; }
  const onnx = files.find(f => /\.onnx$/i.test(f.name));
  const js = files.find(f => /\.json$/i.test(f.name));
  if (!onnx) { bpSetStatus("Pick an .onnx file (select its policy_meta.json with it)."); return; }
  try {
    bpSetStatus(`Loading ${onnx.name}…`);
    const meta = js ? JSON.parse(await js.text()) : await (await fetch("policy_meta.json")).json();
    const ag = new AiPolicy.PpoOnnxAgent(onnx.name);
    await ag.initFromBytes(new Uint8Array(await onnx.arrayBuffer()), meta);
    ag.devLabel = onnx.name + (js ? "" : " (deployed meta)");
    if (_loadTarget === "a") S.aiAgent = ag; else S.aiAgent2 = ag;
    _syncModelLabels();
    _restart();
    bpSetStatus(`Loaded ${ag.devLabel} as ${_loadTarget === "a" ? "the main AI" : "AI B"}.` +
                (_loadTarget === "b" && S.mode !== "aivai" ? " Switch to the AI vs AI tab to race it." : ""));
  } catch (e) {
    bpSetStatus(`Model load failed: ${e.message}`);
  }
}

// ---- Map JSON -------------------------------------------------------------
// Vertices in px (the Python Ground's units); python/ground.py load_json reads it.
function _mapJSON() {
  const g = S.ground;
  return JSON.stringify({
    format: "hcr-map-v1", name: S.currentTerrainName || "map", spawning_y: getSpawningY(),
    distance: g.distance, tuned: !!g.tuned,
    vertices: g.vectors.map(v => [v.x * SCALE, v.y * SCALE]), grass: g.grassPositions.slice(),
  });
}
// Accepts our export, Python's save_json ({vectors:[{x,y}]} px) or a bug-probe
// recording ({meta, ground:[[x,y]] meters}).
function _importMap(text) {
  let d;
  try { d = JSON.parse(text); } catch (e) { bpSetStatus("Not valid JSON."); return; }
  let m;
  if (Array.isArray(d.vertices)) m = d.vertices.map(v => [v[0] / SCALE, v[1] / SCALE]);
  else if (Array.isArray(d.vectors)) m = d.vectors.map(v => Array.isArray(v) ? [v[0] / SCALE, v[1] / SCALE] : [v.x / SCALE, v.y / SCALE]);
  else if (d.meta && Array.isArray(d.ground)) m = d.ground.map(v => [v[0], v[1]]);
  if (!m || m.length < 12 || !m.every(v => Number.isFinite(v[0]) && Number.isFinite(v[1]))) {
    bpSetStatus("No usable terrain in that JSON (expected vertices / vectors / a bug-probe ground)."); return;
  }
  const grass = (Array.isArray(d.grass) && d.grass.length === 2 * m.length) ? d.grass.slice() : m.flatMap(() => [-1, -1]);
  const sy = Number.isFinite(d.spawning_y) ? d.spawning_y
           : Number.isFinite(d.meta && d.meta.spawning_y) ? d.meta.spawning_y : m[10][1] * SCALE - 100;
  const source = { vectors: m.map(v => new Vec2(v[0], v[1])), grassPositions: grass, tuned: !!d.tuned };
  _hooks.loadTerrain({ source, spawning_y: sy, name: d.name || "Imported map" });
  bpSetStatus(`Imported “${d.name || "Imported map"}” (${m.length} vertices).`);
}
function _download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---- Overlays ---------------------------------------------------------------
const _sx = xm => xm * SCALE - S.cameraPanX;
const _sy = ym => ym * SCALE - S.cameraPanY;

// The look-ahead vertices exactly as Ground.getPositions picks them (padded with the
// last one past the end of the track).
function _probeVerts(m, x) {
  const vs = S.ground.vectors;
  let i0 = vs.findIndex(v => v.x >= x);
  if (i0 < 0) i0 = vs.length - 1;
  const out = [];
  let last = i0;
  for (let k = 0; k < m.lookahead_n; k++) {
    const j = i0 + k * m.lookahead_skip;
    if (j < vs.length) last = j;
    out.push(vs[last]);
  }
  return out;
}

function _drawVision(ctx, p) {
  const ag = p.agent, m = ag && ag.meta;
  if (!m || p.dead || !p.car.chassisBody) return;
  const pos = p.car.chassisBody.GetPosition();
  const bottom = pos.y + m.chassis_height_px / SCALE;
  const probes = _probeVerts(m, pos.x);
  ctx.save();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgba(255,255,255,0.5)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(_sx(pos.x), _sy(bottom)); ctx.lineTo(_sx(probes[probes.length - 1].x), _sy(bottom)); ctx.stroke();
  probes.forEach((v, k) => {
    const raw = v.y - bottom;   // metres below the chassis bottom (y-down)
    const cc = Math.max(m.clearance_min_m, Math.min(m.clearance_max_m, raw));
    const t = (cc - m.clearance_min_m) / (m.clearance_max_m - m.clearance_min_m);
    const col = `hsl(${Math.round(t * 120)},90%,60%)`;
    ctx.strokeStyle = col; ctx.fillStyle = col;
    ctx.setLineDash(cc !== raw ? [3, 3] : []);   // dashed = clipped to the obs range
    ctx.beginPath(); ctx.moveTo(_sx(v.x), _sy(bottom)); ctx.lineTo(_sx(v.x), _sy(bottom + cc)); ctx.stroke();
    ctx.beginPath(); ctx.arc(_sx(v.x), _sy(bottom + cc), 4, 0, Math.PI * 2); ctx.fill();
    ctx.font = "bold 11px ui-monospace, monospace"; ctx.textAlign = "center";
    ctx.fillText(`${k}:${cc.toFixed(1)}`, _sx(v.x), _sy(bottom) - 6);
  });
  // Wheel-contact obs flags (with coyote time): green ring = the policy sees "grounded".
  const flags = [ag._lastGroundedRear < m.coyote_frames, ag._lastGroundedFront < m.coyote_frames];
  ctx.setLineDash([]);
  p.car.wheels.forEach((w, i) => {
    const wp = w.body.GetPosition();
    ctx.strokeStyle = flags[i] ? "#5f5" : "rgba(200,200,200,0.6)";
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(_sx(wp.x), _sy(wp.y), w.radius + 5, 0, Math.PI * 2); ctx.stroke();
  });
  ctx.restore();
}

function _drawB2D(ctx, viewW) {
  const b2Body = Box2D.Dynamics.b2Body, b2Shape = Box2D.Collision.Shapes.b2Shape;
  const x0 = (S.cameraPanX - 60) / SCALE, x1 = (S.cameraPanX + viewW + 60) / SCALE;
  ctx.save();
  ctx.lineWidth = 1.5;
  for (let b = S.world.GetBodyList(); b; b = b.GetNext()) {
    const pos = b.GetPosition(), a = b.GetAngle(), c = Math.cos(a), s = Math.sin(a);
    const dyn = b.GetType() === b2Body.b2_dynamicBody;
    const W = v => [pos.x + c * v.x - s * v.y, pos.y + s * v.x + c * v.y];
    for (let f = b.GetFixtureList(); f; f = f.GetNext()) {
      const sh = f.GetShape();
      ctx.strokeStyle = f.IsSensor() ? "#6cf" : !dyn ? "#fa5" : b.IsAwake() ? "#7f7" : "#8a8";
      if (sh.GetType() === b2Shape.e_circleShape) {
        const [cx, cy] = W(sh.GetLocalPosition()), r = sh.GetRadius();
        ctx.beginPath(); ctx.arc(_sx(cx), _sy(cy), r * SCALE, 0, Math.PI * 2);
        ctx.moveTo(_sx(cx), _sy(cy)); ctx.lineTo(_sx(cx + c * r), _sy(cy + s * r)); ctx.stroke();
      } else if (sh.GetType() === b2Shape.e_polygonShape) {
        const vs = sh.GetVertices(), n = sh.GetVertexCount();
        const pts = [];
        for (let i = 0; i < n; i++) pts.push(W(vs[i]));
        if (!dyn && (pts.every(q => q[0] < x0) || pts.every(q => q[0] > x1))) continue;   // off-screen ground
        ctx.beginPath(); ctx.moveTo(_sx(pts[0][0]), _sy(pts[0][1]));
        for (let i = 1; i < n; i++) ctx.lineTo(_sx(pts[i][0]), _sy(pts[i][1]));
        if (n > 2) ctx.closePath();
        ctx.stroke();
      }
    }
    if (dyn) {   // centre of mass + velocity (length = 0.2 s of travel)
      const wc = b.GetWorldCenter(), v = b.GetLinearVelocity();
      ctx.fillStyle = "#fff";
      ctx.fillRect(_sx(wc.x) - 2, _sy(wc.y) - 2, 4, 4);
      ctx.strokeStyle = "#ff0";
      ctx.beginPath(); ctx.moveTo(_sx(wc.x), _sy(wc.y)); ctx.lineTo(_sx(wc.x + v.x * 0.2), _sy(wc.y + v.y * 0.2)); ctx.stroke();
    }
  }
  ctx.strokeStyle = "#0ff"; ctx.fillStyle = "#0ff";
  for (let j = S.world.GetJointList(); j; j = j.GetNext()) {
    const A = j.GetAnchorA(), B = j.GetAnchorB();
    ctx.beginPath(); ctx.moveTo(_sx(A.x), _sy(A.y)); ctx.lineTo(_sx(B.x), _sy(B.y)); ctx.stroke();
    ctx.beginPath(); ctx.arc(_sx(A.x), _sy(A.y), 3, 0, Math.PI * 2); ctx.arc(_sx(B.x), _sy(B.y), 3, 0, Math.PI * 2); ctx.fill();
  }
  const wm = new Box2D.Collision.b2WorldManifold();
  ctx.strokeStyle = "#f44"; ctx.fillStyle = "#f44";
  for (let k = S.world.GetContactList(); k; k = k.GetNext()) {
    const n = k.IsTouching() ? k.GetManifold().m_pointCount : 0;
    if (!n) continue;
    k.GetWorldManifold(wm);
    for (let i = 0; i < n; i++) {
      const q = wm.m_points[i];
      ctx.beginPath(); ctx.arc(_sx(q.x), _sy(q.y), 4, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.moveTo(_sx(q.x), _sy(q.y));
      ctx.lineTo(_sx(q.x + wm.m_normal.x * 0.6), _sy(q.y + wm.m_normal.y * 0.6)); ctx.stroke();
    }
  }
  ctx.restore();
}

// World-space overlays; called by render.js inside the camera/shake transform.
export function drawDevWorld(ctx, viewW) {
  if (!S.devMode || S.ghostPoses || !S.world) return;
  if (S.devB2D) _drawB2D(ctx, viewW);
  if (S.devVision) for (const p of S.players) if (p.isAI) _drawVision(ctx, p);
}

function _box(ctx, x, y, w, h) {
  ctx.fillStyle = "rgba(8,12,24,0.78)";
  ctx.beginPath(); ctx.roundRect(x, y, w, h, 10); ctx.fill();
}
const ACT_NAMES = ["FWD", "REV", "OFF"];
// Screen-space panels: per-AI action probabilities + obs (bottom-left), Box2D stats
// and the torso-joint angle vs its limits (bottom-right).
export function drawDevHUD(ctx, viewW, players) {
  if (!S.devMode || S.ghostPoses || !S.world) return;
  ctx.save();
  ctx.font = "bold 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  if (S.devVision) {
    let y = CANVAS_HEIGHT - 16;
    for (const p of players) {
      if (!p.isAI || !p.agent || !p.agent.meta) continue;
      const ag = p.agent, L = ag.lastLogits;
      const h = 96;
      y -= h;
      _box(ctx, 16, y, 250, h - 8);
      ctx.fillStyle = p.color.outline;
      const name = p.aiB ? "AI B" : "AI";
      ctx.fillText(`${name}${S.replayActions ? " · replay (no inference)" : ""}`, 26, y + 13);
      if (L && !S.replayActions) {
        const mx = Math.max(L[0], L[1], L[2]);
        const e = [0, 1, 2].map(i => Math.exp(L[i] - mx)), sum = e[0] + e[1] + e[2];
        const best = e.indexOf(Math.max(...e));
        for (let i = 0; i < 3; i++) {
          const pr = e[i] / sum, by = y + 30 + i * 15;
          ctx.fillStyle = i === best ? "#fff" : "#9aa7bd";
          ctx.fillText(ACT_NAMES[i], 26, by);
          ctx.fillStyle = "rgba(255,255,255,0.12)"; ctx.fillRect(62, by - 5, 130, 10);
          ctx.fillStyle = i === best ? p.color.outline : "#5d6b85"; ctx.fillRect(62, by - 5, 130 * pr, 10);
          ctx.fillStyle = i === best ? "#fff" : "#9aa7bd";
          ctx.fillText(`${(pr * 100).toFixed(1)}%`, 198, by);
        }
      }
      const fs = ag._frameStack, o = fs && fs.length ? fs[fs.length - 1] : null;
      if (o && ag.meta.per_wheel) {
        ctx.fillStyle = "#9aa7bd";
        ctx.fillText(`ang ${o[0].toFixed(2)} gR${o[1]} gF${o[2]} ω ${o[3].toFixed(2)} vx ${o[4].toFixed(2)} vy ${o[5].toFixed(2)}`, 26, y + 76);
      }
    }
  }
  if (S.devB2D) {
    let nb = 0, nc = 0, nj = 0;
    for (let b = S.world.GetBodyList(); b; b = b.GetNext()) nb++;
    for (let k = S.world.GetContactList(); k; k = k.GetNext()) if (k.IsTouching()) nc++;
    for (let j = S.world.GetJointList(); j; j = j.GetNext()) nj++;
    const lines = [`tick ${S.tickCount} · bodies ${nb} · joints ${nj} · touching ${nc}`];
    for (const p of players) {
      if (!p.car || !p.car.revJoint) continue;
      const lbl = p.aiB ? "AI B" : p.isAI ? "AI" : "you";
      lines.push(p.car.player.kindaDead ? `${lbl}: torso joint detached (dead)`
        : `${lbl}: torso joint ${(p.car.revJoint.GetJointAngle() * 180 / Math.PI).toFixed(1)}° [−70.6, +104.5]`);
    }
    const w = 330, h = 12 + lines.length * 17;
    _box(ctx, viewW - 16 - w, CANVAS_HEIGHT - 16 - h, w, h);
    ctx.fillStyle = "#cfe";
    lines.forEach((s, i) => ctx.fillText(s, viewW - 6 - w, CANVAS_HEIGHT - 16 - h + 14 + i * 17));
  }
  ctx.restore();
}

// ---- Wiring ---------------------------------------------------------------
function _isField(t) { return t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA"); }

export function initDevMode(hooks) {
  _hooks = { ..._hooks, ...hooks };
  try { S.devMode = localStorage.getItem(DEV_KEY) === "1"; } catch (e) {}
  _applyDevClass();

  const openGate = () => { $("dev_err").textContent = ""; $("dev_panel").style.display = "block"; $("dev_pw").focus(); };
  $("dev_unlock_btn").onclick = openGate;
  $("dev_close").onclick = () => { $("dev_panel").style.display = "none"; };
  $("dev_form").onsubmit = e => { e.preventDefault(); _unlock($("dev_pw").value); };
  $("dev_lock").onclick = _lock;
  if (!S.devMode && new URLSearchParams(location.search).has("dev")) openGate();

  $("dev_vision").onchange = e => { S.devVision = e.target.checked; };
  $("dev_b2d").onchange = e => { S.devB2D = e.target.checked; };
  $("dev_step").onclick = devStep;
  $("dev_qsave").onclick = devQuickSave;
  $("dev_qload").onclick = devQuickLoad;

  const pickModel = t => { _loadTarget = t; $("dev_model_file").value = ""; $("dev_model_file").click(); };
  $("dev_load_a").onclick = () => pickModel("a");
  $("dev_load_b").onclick = () => pickModel("b");
  $("dev_model_file").onchange = e => _loadModel(Array.from(e.target.files));
  $("dev_models_reset").onclick = () => {
    if (S.bestofxBusy || !_deployedA) return;
    S.aiAgent = _deployedA; if (_deployedB) S.aiAgent2 = _deployedB;
    _syncModelLabels(); _restart();
    bpSetStatus("Both AIs back on the deployed model.");
  };

  $("dev_map_copy").onclick = async () => {
    try { await navigator.clipboard.writeText(_mapJSON()); bpSetStatus("Map JSON copied to the clipboard."); }
    catch (e) { bpSetStatus(`Clipboard blocked (${e.message}) — use Download.`); }
  };
  $("dev_map_dl").onclick = () => {
    const nm = (S.currentTerrainName || "map").replace(/[^\w-]+/g, "_");
    _download(`hcr_map_${nm}.json`, _mapJSON());
  };
  $("dev_map_paste").onclick = async () => {
    let t = null;
    try { t = await navigator.clipboard.readText(); } catch (e) { t = window.prompt("Paste map JSON:"); }
    if (t) _importMap(t);
  };
  $("dev_map_open").onclick = () => { $("dev_map_file").value = ""; $("dev_map_file").click(); };
  $("dev_map_file").onchange = async e => { const f = e.target.files[0]; if (f) _importMap(await f.text()); };

  window.addEventListener("keydown", e => {
    if (!S.devMode || e.ctrlKey || e.metaKey || e.altKey || _isField(e.target)) return;
    const k = e.key.toLowerCase();
    if (k === ".") { e.preventDefault(); devStep(); }
    else if (k === "q" && !e.repeat) { e.preventDefault(); devQuickSave(); }
    else if (k === "l" && !e.repeat) { e.preventDefault(); devQuickLoad(); }
  });
}
