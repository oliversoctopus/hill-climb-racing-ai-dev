// Physics playground: every tweakable knob in the Debug panel, defined once in TUNE_SPEC
// (the panel UI is generated from it). Browser-only — the shared physics classes are
// untouched; live knobs are pushed onto existing bodies/joints, size knobs go through
// the construction wrappers in index.html's shim, terrain knobs through map generation.
// At the defaults nothing here touches the simulation (every hook is gated on modified).
import { S, SCALE, CANVAS_HEIGHT, STUCK_TIMEOUT_TICKS } from "./state.js";
import { Vec2, setSpawningY } from "./bridge.js";

// Shared with the index.html shim (which reads the size knobs while a car is built).
export const T = window.HCR_TUNE;

const off0 = v => (v === 0 ? "off" : null);
// apply: "live" (default) | "restart" (next car build) | "newmap" (next generated map).
// log: slider moves logarithmically (for knobs spanning orders of magnitude).
export const TUNE_SPEC = [
  { id: "world", title: "🌍 World", items: [
    { key: "gravityY", label: "Gravity ↓", def: 10, min: -20, max: 50, step: 0.1, unit: "m/s²" },
    { key: "gravityX", label: "Gravity →", def: 0, min: -20, max: 20, step: 0.1, unit: "m/s²" },
  ]},
  { id: "body", title: "🚙 Car body", items: [
    { key: "chassisDensity", label: "Density", def: 1, min: 0.05, max: 20, log: true },
    { key: "chassisFriction", label: "Friction", def: 0.5, min: 0, max: 3, step: 0.01 },
    { key: "chassisBounce", label: "Bounciness", def: 0.01, min: 0, max: 1.5, step: 0.01 },
    { key: "bumperFriction", label: "Bumper friction", def: 0.1, min: 0, max: 3, step: 0.01 },
    { key: "bumperBounce", label: "Bumper bounciness", def: 0.1, min: 0, max: 1.5, step: 0.01 },
    { key: "chassisAngDamp", label: "Spin damping", def: 0.1, min: 0, max: 10, step: 0.05 },
    { key: "airDrag", label: "Air drag", def: 0, min: 0, max: 5, step: 0.05 },
    { key: "airControl", label: "Air-control torque", def: 2, min: 0, max: 60, step: 0.5 },
  ]},
  { id: "wheels", title: "🛞 Wheels", items: [
    { key: "tireFriction", label: "Tire grip", def: 1.5, min: 0, max: 5, step: 0.05 },
    { key: "tireBounce", label: "Tire bounciness", def: 0.1, min: 0, max: 1.5, step: 0.01 },
    { key: "tireDensity", label: "Tire density", def: 1, min: 0.05, max: 20, log: true },
    { key: "wheelAngDamp", label: "Spin damping", def: 1.8, min: 0, max: 10, step: 0.1 },
    { key: "rimDensity", label: "Hub density", def: 0.05, min: 0.005, max: 10, log: true },
    { key: "rimFriction", label: "Hub friction", def: 0.99, min: 0, max: 5, step: 0.01 },
    { key: "rimBounce", label: "Hub bounciness", def: 0.2, min: 0, max: 1.5, step: 0.01 },
  ]},
  { id: "motor", title: "⚙ Motor", items: [
    { key: "motorSpeed", label: "Top speed ×", def: 1, min: 0, max: 5, step: 0.05 },
    { key: "rearTorque", label: "Rear torque", def: 700, min: 0, max: 10000, step: 10, unit: "N·m" },
    { key: "frontTorque", label: "Front torque", def: 350, min: 0, max: 10000, step: 10, unit: "N·m" },
  ]},
  { id: "susp", title: "🔩 Suspension", items: [
    { key: "suspFreq", label: "Stiffness", def: 70, min: 0.5, max: 200, log: true, unit: "Hz" },
    { key: "suspDamp", label: "Damping", def: 25, min: 0, max: 50, step: 0.5 },
    { key: "suspLength", label: "Ride height ×", def: 1, min: 0.2, max: 3, step: 0.05 },
    { key: "suspTravel", label: "Travel limit", def: 0, min: 0, max: 2, step: 0.05, unit: "m", fmt: off0 },
  ]},
  { id: "driver", title: "🧍 Driver", items: [
    { key: "headDensity", label: "Head density", def: 0.001, min: 0.0001, max: 5, log: true },
    { key: "torsoDensity", label: "Torso density", def: 0.002, min: 0.0001, max: 5, log: true },
    { key: "driverFriction", label: "Friction", def: 0.01, min: 0, max: 3, step: 0.01 },
    { key: "driverBounce", label: "Bounciness", def: 0.01, min: 0, max: 1.5, step: 0.01 },
    { key: "seatFreq", label: "Seat spring", def: 5, min: 0.2, max: 30, log: true, unit: "Hz" },
    { key: "seatDamp", label: "Seat damping", def: 0.1, min: 0, max: 5, step: 0.05 },
    { key: "seatLimits", label: "Seat tilt limits (no under-car flip)", def: true, bool: true },
    { key: "neckLimit", label: "Neck bend limit", def: 180, min: 0, max: 180, step: 1, unit: "°",
      fmt: v => (v >= 180 ? "off" : null) },
    { key: "neckStiff", label: "Neck spring", def: 0, min: 0, max: 5, step: 0.1, unit: "Hz", fmt: off0 },
  ]},
  { id: "sizes", title: "📏 Sizes & shapes", apply: "restart", items: [
    { key: "chassisLen", label: "Car length ×", def: 1, min: 0.4, max: 3, step: 0.05 },
    { key: "chassisHt", label: "Car height ×", def: 1, min: 0.4, max: 3, step: 0.05 },
    { key: "wheelSize", label: "Wheel size ×", def: 1, min: 0.3, max: 3.5, step: 0.05 },
    { key: "wheelbase", label: "Wheelbase ×", def: 1, min: 0.3, max: 2, step: 0.05 },
    { key: "driverSize", label: "Driver size ×", def: 1, min: 0.3, max: 3, step: 0.05 },
  ]},
  { id: "rules", title: "⚖ Rules", items: [
    { key: "headKills", label: "Head hitting the ground kills", def: true, bool: true },
    { key: "killLineM", label: "Fall-off line depth", def: 24, min: 24, max: 300, step: 1, unit: "m" },
    { key: "aiStuckTicks", label: "AI stuck timeout", def: STUCK_TIMEOUT_TICKS, min: 90, max: 3600, step: 15,
      fmt: v => `${(v / 30).toFixed(1)} s` },
  ]},
  { id: "terrain", title: "⛰ Terrain", items: [
    { key: "hilliness", label: "Hilliness ×", def: 1, min: 0, max: 3, step: 0.05, apply: "newmap" },
    { key: "mapLength", label: "Map length ×", def: 1, min: 0.1, max: 5, step: 0.05, apply: "newmap" },
    { key: "pointSpacing", label: "Point spacing", def: 15, min: 5, max: 150, step: 1, unit: "px", apply: "newmap" },
    { key: "groundFriction", label: "Ground friction", def: 0.99, min: 0, max: 3, step: 0.01 },
    { key: "groundBounce", label: "Ground bounciness", def: 0.1, min: 0, max: 2, step: 0.01 },
  ]},
];

// Additive: each preset only sets its own knobs, so they stack (Moon + Ice rink).
export const TUNE_PRESETS = [
  { name: "🌙 Moon", vals: { gravityY: 1.62 } },
  { name: "🧊 Ice rink", vals: { tireFriction: 0.03, rimFriction: 0.03, groundFriction: 0.02, chassisFriction: 0.02 } },
  { name: "🤸 Trampoline", vals: { groundBounce: 1.0, tireBounce: 0.9, chassisBounce: 0.8 } },
  { name: "🚚 Monster truck", vals: { wheelSize: 2, wheelbase: 1.4, chassisLen: 1.3, suspLength: 1.4, rearTorque: 5000, frontTorque: 5000, motorSpeed: 1.2 } },
  { name: "🎈 Bobblehead", vals: { headDensity: 0.02, driverSize: 1.3, neckStiff: 1.2, seatFreq: 1.5, seatDamp: 0.05 } },
];

const ITEMS = {};
for (const sec of TUNE_SPEC) for (const it of sec.items) {
  it.apply = it.apply || sec.apply || "live";
  it.sec = sec;
  ITEMS[it.key] = it;
  if (!(it.key in T)) T[it.key] = it.def;
}
const _isDef = it => (it.bool ? T[it.key] === it.def : Math.abs(T[it.key] - it.def) < 1e-9);
const _mod = apply => Object.values(ITEMS).some(it => (!apply || it.apply === apply) && !_isDef(it));
export function tuneModified() { return _mod(null); }

// Values the current car / map were built with — a differing knob is "pending".
const _built = { restart: {}, newmap: {} };
function _snapshot(apply) { for (const it of Object.values(ITEMS)) if (it.apply === apply) _built[apply][it.key] = T[it.key]; }
_snapshot("restart"); _snapshot("newmap");
const _pending = it => it.apply !== "live" && _built[it.apply][it.key] !== T[it.key];

// ---- Applying ------------------------------------------------------------
function _fixtures(b) { const a = []; for (let f = b.GetFixtureList(); f; f = f.m_next) a.push(f); return a; }
function _setFix(b, dens, fric, bounce) {
  for (const f of _fixtures(b)) { f.SetDensity(dens); f.SetFriction(fric); f.SetRestitution(bounce); }
  b.ResetMassData();
}

// Push every live knob onto one car's bodies and joints.
export function tuneCar(c) {
  try {
    const cb = c.chassisBody;
    // Fixture list is newest-first: [bumper, roll bar, main body] (Car.js build order).
    _fixtures(cb).forEach((f, i) => {
      f.SetDensity(T.chassisDensity);
      f.SetFriction(i === 0 ? T.bumperFriction : T.chassisFriction);
      f.SetRestitution(i === 0 ? T.bumperBounce : T.chassisBounce);
    });
    cb.ResetMassData();
    cb.SetAngularDamping(T.chassisAngDamp);
    c.rotationTorque = T.airControl;
    for (const w of c.wheels) {
      _setFix(w.body, T.tireDensity, T.tireFriction, T.tireBounce);
      w.body.SetAngularDamping(T.wheelAngDamp);
      _setFix(w.rimBody, T.rimDensity, T.rimFriction, T.rimBounce);
      if (w._baseLen === undefined) w._baseLen = w.distJoint.GetLength();
      w.distJoint.SetLength(w._baseLen * T.suspLength);
      w.distJoint.SetFrequency(T.suspFreq);
      w.distJoint.SetDampingRatio(T.suspDamp);
      w.prisJoint.EnableLimit(T.suspTravel > 0);
      if (T.suspTravel > 0) w.prisJoint.SetLimits(-T.suspTravel, T.suspTravel);
    }
    const P = c.person;
    _setFix(P.head.body, T.headDensity, T.driverFriction, T.driverBounce);
    _setFix(P.torso.body, T.torsoDensity, T.driverFriction, T.driverBounce);
    c.distJoint.SetFrequency(T.seatFreq);
    c.distJoint.SetDampingRatio(T.seatDamp);
    c.revJoint.EnableLimit(T.seatLimits);
    const a = T.neckLimit * Math.PI / 180;
    P.headJoint.EnableLimit(T.neckLimit < 180);
    P.headJoint.SetLimits(-a, a);
    for (const b of c.bodies()) { b.SetLinearDamping(T.airDrag); b.SetAwake(true); }
  } catch (e) { /* a head-hit death may have destroyed some joints */ }
}

// Gravity + ground surface for a world.
export function tuneWorld(world) {
  const g = new Vec2(T.gravityX, T.gravityY);
  if (S.bpZeroG && world === S.world) S.bpSavedGravity = g; else world.SetGravity(g);
  for (let b = world.GetBodyList(); b; b = b.GetNext()) {
    const ud = b.GetUserData();
    if (ud && ud.id === "ground") for (const f of _fixtures(b)) { f.SetFriction(T.groundFriction); f.SetRestitution(T.groundBounce); }
  }
}

// A freshly built car with bigger wheels / body / longer suspension would spawn with its
// wheels in the ground and get launched: pre-extend the wheels to the new spring length,
// then lift the whole car so it keeps a stock car's ground clearance.
const STOCK_CHASSIS_H = 40, STOCK_WHEEL_R = 17;   // Car.js
function _fitNewCar(c) {
  let ext = 0;
  for (const w of c.wheels) {
    if (w._baseLen === undefined) w._baseLen = w.distJoint.GetLength();
    ext = w._baseLen * (T.suspLength - 1);   // m, along the (still vertical) suspension axis
    if (ext > 0) for (const b of [w.body, w.rimBody]) { const p = b.GetPosition(); b.SetPosition(new Vec2(p.x, p.y + ext)); }
  }
  // Wheel bottoms sit chassisHeight/2 + 1.25·r below the chassis centre (Car.js).
  const lift = (c.chassisHeight - STOCK_CHASSIS_H) / 2 + (c.wheelSize - STOCK_WHEEL_R) * 1.25 + Math.max(0, ext) * SCALE;
  if (lift > 0) for (const b of c.bodies()) { const p = b.GetPosition(); b.SetPosition(new Vec2(p.x, p.y - lift / SCALE)); }
}

// Called by the shim's Car wrapper for EVERY car built (live play, Best of X, search).
window.HCR_onCar = c => {
  if (_mod("restart") || T.suspLength !== 1) _fitNewCar(c);
  if (_mod("live")) { tuneCar(c); tuneWorld(c.world); }
};

// After a knob change: retune every car on screen + the live world.
export function applyTuneLive() {
  S.bpPhysModified = tuneModified();
  if (!S.world) return;
  for (const p of S.players || []) if (p.car) tuneCar(p.car);
  tuneWorld(S.world);
}

// Per-tick forces (run after the actions, before world.Step): motor overrides — motorOn()
// resets torque/speed every tick — and the optional neck spring.
export function tuneTick() {
  const motor = T.motorSpeed !== 1 || T.rearTorque !== 700 || T.frontTorque !== 350;
  if (!motor && !T.neckStiff) return;
  for (const p of S.players || []) {
    const c = p.car; if (!c) continue;
    if (motor) c.wheels.forEach((w, i) => {
      const j = w.joint;
      if (!j || !j.m_enableMotor) return;
      j.SetMaxMotorTorque(i === 0 ? T.rearTorque : T.frontTorque);   // wheels[0] = rear
      j.SetMotorSpeed(j.GetMotorSpeed() * T.motorSpeed);
    });
    if (T.neckStiff && !c.player.kindaDead) {
      // Damped rotational spring pulling the head back upright relative to the torso.
      const h = c.person.head.body, t = c.person.torso.body;
      const Ih = h.GetInertia(), It = t.GetInertia(), I = Ih * It / (Ih + It);
      const w0 = 2 * Math.PI * T.neckStiff;
      const rel = h.GetAngle() - t.GetAngle(), relW = h.GetAngularVelocity() - t.GetAngularVelocity();
      const tau = -I * (w0 * w0 * rel + 1.4 * w0 * relW);
      h.ApplyTorque(tau); t.ApplyTorque(-tau);
    }
  }
}

// ---- Terrain hooks (rollAcceptableGround) -----------------------------------
export const terrainTuned = () => _mod("newmap");
// Before randomizeGround(): length + vertex spacing. Length stays a whole number of
// spacings so the last solid vertex is exactly distance − smoothness (the finish).
export function tuneGroundPre(g) {
  if (!terrainTuned()) return;
  const sp = T.pointSpacing;
  g.smoothness = sp;
  g.distance = Math.max(sp * 60, Math.round(g.distance * T.mapLength / sp) * sp);
}
// After the steepness gate: hilliness (heights scaled about the spawn-area height,
// kept above the kill line) + a spawn height matching the new spacing.
export function tuneGroundPost(g) {
  _snapshot("newmap");
  if (!terrainTuned()) return;
  g.tuned = true;
  const vs = g.vectors, n = vs.length - 2, x0 = 150 / SCALE;   // Ground spawns from x=150px
  let i = 0; while (i < n - 2 && vs[i + 1].x <= x0) i++;
  const pivot = vs[i].y + (vs[i + 1].y - vs[i].y) * (x0 - vs[i].x) / (vs[i + 1].x - vs[i].x);
  if (T.hilliness !== 1) {
    const floorY = (CANVAS_HEIGHT - 30) / SCALE;
    for (let k = 0; k < n; k++) vs[k].y = Math.min(floorY, pivot + (vs[k].y - pivot) * T.hilliness);
  }
  setSpawningY(pivot * SCALE - 100);
}
// A cloned Ground only copies vertices; recover its length/spacing from them.
export function syncGroundDims(g, src) {
  const vs = g.vectors, n = vs.length;
  if (n < 4) return;
  const r = v => Math.round(v * 1e6) / 1e6;
  const dist = r(vs[n - 2].x * SCALE), sp = r((vs[1].x - vs[0].x) * SCALE);
  if (Math.abs(dist - g.distance) > 1e-6) g.distance = dist;
  if (Math.abs(sp - g.smoothness) > 1e-6) g.smoothness = sp;
  g.tuned = !!(src && src.tuned) || g.distance !== 19200 || g.smoothness !== 15;
}
// Called on every world build: the car now matches the size knobs.
export function tuneOnBuild() {
  _snapshot("restart");
  refreshTunePanel();
  if (_reminded && !Object.values(ITEMS).some(_pending)) { _reminded = false; _status("Rebuilt with the new settings."); }
}

// ---- Panel UI ---------------------------------------------------------------
let _status = () => {};
let _reminded = false;   // a "restart / new map to apply" reminder is on screen
const _dec = it => (it.step ? Math.max(0, -Math.floor(Math.log10(it.step) + 1e-9)) : 3);
function _fmt(it, v) {
  const f = it.fmt && it.fmt(v);
  if (f) return f;
  return it.log ? String(+v.toPrecision(3)) : v.toFixed(_dec(it));
}
const _toSlider = (it, v) => (it.log ? 1000 * Math.log(v / it.min) / Math.log(it.max / it.min) : v);
const _fromSlider = (it, p) => (it.log ? +(it.min * Math.pow(it.max / it.min, p / 1000)).toPrecision(3) : p);

export function setTune(vals) {
  const pend = { restart: false, newmap: false };
  for (const k in vals) {
    const it = ITEMS[k]; if (!it) continue;
    T[k] = it.bool ? !!vals[k] : Math.min(it.max, Math.max(it.min, +vals[k]));
    if (_pending(it)) pend[it.apply] = true;
  }
  applyTuneLive();
  refreshTunePanel();
  const msgs = [];
  if (pend.restart) msgs.push("press Restart (R) to rebuild the car with the new size");
  if (pend.newmap) msgs.push("generate a New map (T) to see the terrain change");
  _reminded = msgs.length > 0;
  if (msgs.length) _status("To see it: " + msgs.join("; ") + ".");
  else _status(tuneModified() ? "Physics playground: changes applied live (this run counts toward cheat records only)."
                              : "Physics back to stock.");
}
export function resetTune(secId) {
  const vals = {};
  for (const it of Object.values(ITEMS)) if (!secId || it.sec.id === secId) vals[it.key] = it.def;
  setTune(vals);
}

const _rows = {};
export function buildTunePanel(root, statusFn) {
  _status = statusFn;
  for (const sec of TUNE_SPEC) {
    const d = document.createElement("details");
    d.className = "tune-sec";
    d.innerHTML = `<summary><span>${sec.title}</span><span class="tune-badge"></span></summary>`;
    sec.badge = d.querySelector(".tune-badge");
    for (const it of sec.items) {
      const row = document.createElement("div");
      if (it.bool) {
        row.innerHTML = `<label class="toggle"><input type="checkbox"><span class="sw"></span><span class="tl"></span></label>`;
        row.querySelector(".tl").textContent = it.label;
        const cb = row.querySelector("input");
        cb.onchange = () => setTune({ [it.key]: cb.checked });
        _rows[it.key] = { row, cb };
      } else {
        row.className = "tune-row";
        row.innerHTML = `<span class="tl"></span><input type="range"><input type="text" inputmode="decimal">`;
        row.querySelector(".tl").textContent = it.label + (it.unit ? ` (${it.unit})` : "");
        row.querySelector(".tl").title = `Default ${_fmt(it, it.def)} — double-click to reset`;
        row.querySelector(".tl").ondblclick = () => setTune({ [it.key]: it.def });
        const sl = row.querySelector("input[type=range]"), nb = row.querySelector("input[type=text]");
        sl.min = it.log ? 0 : it.min; sl.max = it.log ? 1000 : it.max; sl.step = it.log ? 1 : it.step;
        sl.oninput = () => { nb.value = _fmt(it, _fromSlider(it, +sl.value)); };
        sl.onchange = () => setTune({ [it.key]: _fromSlider(it, +sl.value) });
        nb.onchange = () => {
          const v = parseFloat(nb.value);
          if (isNaN(v)) { nb.value = _fmt(it, T[it.key]); return; }
          setTune({ [it.key]: v });
        };
        nb.onkeydown = e => { if (e.key === "Enter") nb.blur(); e.stopPropagation(); };
        _rows[it.key] = { row, sl, nb };
      }
      d.appendChild(row);
    }
    const note = document.createElement("div");
    note.className = "tune-foot";
    if (sec.apply === "restart") note.textContent = "Takes effect on Restart (R).";
    if (sec.id === "terrain") note.textContent = "Hilliness, length and spacing take effect on a New map (T).";
    const rb = document.createElement("button");
    rb.className = "ghost"; rb.textContent = "Reset section";
    rb.onclick = () => resetTune(sec.id);
    note.appendChild(rb);
    d.appendChild(note);
    root.appendChild(d);
  }
  refreshTunePanel();
}

export function refreshTunePanel() {
  for (const it of Object.values(ITEMS)) {
    const r = _rows[it.key]; if (!r) continue;
    r.row.classList.toggle("mod", !_isDef(it));
    r.row.classList.toggle("pending", _pending(it));
    if (r.cb) r.cb.checked = T[it.key];
    else {
      r.sl.value = _toSlider(it, T[it.key]);
      if (document.activeElement !== r.nb) r.nb.value = _fmt(it, T[it.key]);
    }
  }
  for (const sec of TUNE_SPEC) {
    if (!sec.badge) continue;
    const n = sec.items.filter(it => !_isDef(it)).length;
    const pend = sec.items.find(_pending);
    sec.badge.textContent = pend ? (pend.apply === "restart" ? "↺ restart to apply" : "🎲 new map to apply")
                          : (n ? `${n} changed` : "");
    sec.badge.classList.toggle("warn", !!pend);
  }
}
