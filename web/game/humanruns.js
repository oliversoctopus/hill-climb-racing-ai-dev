// Human-run recorder (dev mode only): each human run's per-tick car state and action, kept
// in IndexedDB so they survive reloads, downloaded from the Dev section as imitation data.
// The raw state plus the stored terrain rebuild any obs encoding. Replaying the actions
// instead drifts: python/js_backend.py rounds differently (PROJECT_STATUS *Human-run recorder*).
import { S, SCALE, SPAWN_X, FRAME_RATE } from "./state.js";
import { getSpawningY } from "./bridge.js";
import { bpSetStatus } from "./cheats.js";

const MIN_ABANDONED_TICKS = 3 * FRAME_RATE;   // an R/T this soon after spawn isn't a run
const IDLE_NOTE_TICKS = 10 * FRAME_RATE;      // the list flags a run ending in this much idling

// Three stores: "runs" holds small summaries (what the list reads), "ticks" the per-tick
// data under the same key, "maps" each terrain once.
const $ = id => document.getElementById(id);
const _req = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
let _dbp = null;
function _db() {
  if (!_dbp) {
    const r = indexedDB.open("hcr_human_runs", 2);
    r.onupgradeneeded = () => {
      const db = r.result;
      for (const n of Array.from(db.objectStoreNames)) db.deleteObjectStore(n);   // v1 held test runs only
      db.createObjectStore("runs", { autoIncrement: true });
      db.createObjectStore("ticks");
      db.createObjectStore("maps");
    };
    _dbp = _req(r);
  }
  return _dbp;
}
async function _tx(mode) {
  const t = (await _db()).transaction(["runs", "ticks", "maps"], mode);
  return { runs: t.objectStore("runs"), ticks: t.objectStore("ticks"), maps: t.objectStore("maps"),
           done: new Promise((res, rej) => { t.oncomplete = res; t.onerror = () => rej(t.error); }) };
}

// ---- Recording (called from sim.js) --------------------------------------------
// The state a human player sees this tick and the action they drive. Starts the recording
// at tick 0; a tick out of sequence (quick-load rewinds) or a frame-step spoils it.
export function hrAction(p, action) {
  if (!p.hr) {
    if (!S.devMode || S.tickCount !== 0 || S.replayActions !== null) { p.hr = { off: true }; return; }
    p.hr = { actions: "", state: [], grounded: "", spoiled: false, simSpeedMin: S.simSpeed, simSpeedMax: S.simSpeed,
             reversed: false };
  }
  const r = p.hr;
  if (r.off || r.done) return;
  if (S.paused || S.tickCount !== r.actions.length) r.spoiled = true;
  const c = p.car, b = c.chassisBody, q = b.GetPosition(), v = b.GetLinearVelocity();
  r.state.push(q.x, q.y, b.GetAngle(), b.GetAngularVelocity(), v.x, v.y);
  r.grounded += (c.wheels[0].onGround === true ? 1 : 0) + (c.wheels[1].onGround === true ? 2 : 0);
  r.actions += action;
  r.simSpeedMin = Math.min(r.simSpeedMin, S.simSpeed);
  r.simSpeedMax = Math.max(r.simSpeedMax, S.simSpeed);
  r.reversed = r.reversed || S.bpReverse;
}
export function hrAfterTick(p) { if (p.dead) hrFinish(p, "died"); }

// Ends a run ("died", or "abandoned" by a rebuild) and stores it unless it's unusable.
export function hrFinish(p, end) {
  const r = p.hr;
  if (!r || r.off || r.done) return;
  r.done = true;
  if (S.runModified || r.spoiled || !/[01]/.test(r.actions)) return;
  if (end === "abandoned" && r.actions.length < MIN_ABANDONED_TICKS) return;
  const g = S.ground;
  const run = {
    map: S.mapKey, map_name: S.currentTerrainName || "", mode: S.mode, control: p.control || "any",
    end, ticks: r.actions.length, idle_tail_ticks: r.actions.length - r.actions.search(/2*$/),
    score: Math.max(0, Math.floor((p.maxDistPx - SPAWN_X) / 10)),
    beat_tick: p.beatTick || null, sim_speed_min: r.simSpeedMin, sim_speed_max: r.simSpeedMax, reversed_controls: r.reversed,
    saved_at: new Date().toISOString(),
  };
  const ticks = { actions: r.actions, state_f64: _f64ToB64(r.state), grounded: r.grounded };
  const map = { key: S.mapKey, spawning_y: getSpawningY(), distance: g.distance, smoothness: g.smoothness,
                vertices_m: g.vectors.map(v => [v.x, v.y]) };
  _save(run, ticks, map).catch(e => bpSetStatus(`Human run not saved: ${e.message}`));
}
function _f64ToB64(arr) {
  const u8 = new Uint8Array(new Float64Array(arr).buffer);
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}
async function _save(run, ticks, map) {
  const t = await _tx("readwrite");
  const add = t.runs.add(run);
  add.onsuccess = () => t.ticks.put(ticks, add.result);
  t.maps.put(map, map.key);
  await t.done;
  _refresh();
}

// ---- Dev-section list and buttons ------------------------------------------------
async function _summaries(t) {
  const [runs, ids] = await Promise.all([_req(t.runs.getAll()), _req(t.runs.getAllKeys())]);
  return runs.map((r, i) => ({ ...r, id: ids[i] }));
}
const _mmss = ticks => { const s = Math.round(ticks / FRAME_RATE); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

async function _refresh() {
  const count = $("hr_count"), list = $("hr_list");
  if (!count) return;
  let runs;
  try { runs = await _summaries(await _tx("readonly")); }
  catch (e) { count.textContent = `Storage unavailable: ${e.message}`; return; }
  const ticks = runs.reduce((s, r) => s + r.ticks, 0);
  count.textContent = `${runs.length} run${runs.length === 1 ? "" : "s"} stored (${_mmss(ticks)})`;
  list.replaceChildren(...runs.reverse().map(r => {   // newest first
    const row = document.createElement("div");
    row.className = "hr-row";
    const txt = document.createElement("span");
    const when = new Date(r.saved_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const idle = r.idle_tail_ticks >= IDLE_NOTE_TICKS ? ` · idle ${_mmss(r.idle_tail_ticks)} at end` : "";
    txt.textContent = `${when} · ${r.map_name || r.map}\n${_mmss(r.ticks)} · score ${r.score} · ${r.end}${idle}`;
    txt.title = txt.textContent;
    if (idle) txt.className = "hr-idle";
    const del = document.createElement("button");
    del.textContent = "✕";
    del.title = "Delete this run";
    del.onclick = () => _delete(r.id).catch(e => bpSetStatus(`Delete failed: ${e.message}`));
    row.append(txt, del);
    return row;
  }));
}
// Removes one run, and its map once no other run uses it.
async function _delete(id) {
  const t = await _tx("readwrite");
  const run = await _req(t.runs.get(id));
  t.runs.delete(id);
  t.ticks.delete(id);
  if (run && !(await _summaries(t)).some(r => r.id !== id && r.map === run.map)) t.maps.delete(run.map);
  await t.done;
  _refresh();
}
async function _download() {
  const t = await _tx("readonly");
  const runs = await _summaries(t);
  if (!runs.length) { bpSetStatus("No human runs recorded yet."); return; }
  const full = await Promise.all(runs.map(async r => ({ ...r, ...(await _req(t.ticks.get(r.id))) })));
  const keys = new Set(runs.map(r => r.map));
  const maps = (await _req(t.maps.getAll())).filter(m => keys.has(m.key));
  const data = { format: "hcr-human-runs-v1", frame_rate: FRAME_RATE, scale: SCALE, spawn_x: SPAWN_X,
                 actions: "0 forward, 1 reverse, 2 off; one char per tick",
                 state_f64: "base64 little-endian float64, 6 per tick: chassis x m, y m, angle rad, "
                          + "ang vel rad/s, vx m/s, vy m/s; the state the action was chosen in",
                 grounded: "one digit per tick: bit 0 rear wheel, bit 1 front wheel on the ground",
                 maps: Object.fromEntries(maps.map(m => [m.key, m])), runs: full };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: "application/json" }));
  a.download = `hcr_human_runs_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
  bpSetStatus(`Downloaded ${runs.length} human runs.`);
}
let _clearArmed = 0;
async function _clear() {
  const btn = $("hr_clear");
  if (!_clearArmed) {
    btn.textContent = "Click again to clear all";
    _clearArmed = setTimeout(() => { _clearArmed = 0; btn.textContent = "Clear all"; }, 3000);
    return;
  }
  clearTimeout(_clearArmed); _clearArmed = 0; btn.textContent = "Clear all";
  const t = await _tx("readwrite");
  t.runs.clear(); t.ticks.clear(); t.maps.clear();
  await t.done;
  _refresh();
  bpSetStatus("Cleared the stored human runs.");
}

export function initHumanRuns() {
  $("hr_download").onclick = () => _download().catch(e => bpSetStatus(`Download failed: ${e.message}`));
  $("hr_clear").onclick = () => _clear().catch(e => bpSetStatus(`Clear failed: ${e.message}`));
  _refresh();
}
