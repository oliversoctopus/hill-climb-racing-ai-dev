// Personal records (human runs only): best score and fastest finish per map (keyed by a
// geometry hash) and across all maps, derived from the per-map entries. Cheated or slow-mo
// runs count only toward a second "incl. cheats" track (m.all), shown behind a checkbox.
// Every map a run sets something on or attempts gets an entry, plus its terrain in
// IndexedDB (the small blob stays in localStorage, read synchronously). Only notable maps
// (m.keep, rules in records_rules.js) and pinned ones are listed, kept for good and given
// a sequential `id`; the rest expire KEEP_DAYS after their last attempt unless Saved or
// loaded. Clean and cheat notability are separate, and cheat-only maps hide with the cheat
// records. Labels are resolved at display time: the Saved name, else "Record map <id>".
import { S, SCALE, FRAME_RATE } from "./state.js";
import { getSpawningY, Vec2 } from "./bridge.js";
import { loadSavedTerrains } from "./saved_terrains.js";
import { ATTEMPT_SEC, ATTEMPT_SCORE, NEAR_FINISH, KEEP_DAYS, CHEAT_ATTEMPTS, ladder, finishNotable,
         fastCutoff, classifyLegacy } from "./records_rules.js";

const DAY_MS = 24 * 3600 * 1000;

const KEY = "hcr_records_v1";
const LEGACY_MAPS_KEY = "hcr_record_maps_v1";   // terrains in localStorage, from before IndexedDB

function _load() {
  try {
    const d = JSON.parse(localStorage.getItem(KEY) || "null");
    if (d && d.version === 1 && d.maps) {
      if (d.nextId == null) {   // blob from before ids: number maps in stored order
        let id = 1;
        for (const k of Object.keys(d.maps)) { d.maps[k].id = id++; delete d.maps[k].name; }
        d.nextId = id;
      }
      delete d.global;           // now derived (see _global)
      const now = Date.now();
      for (const m of Object.values(d.maps)) {
        if (!m.all) m.all = _cleanAll(m);   // pre-cheat-track blob
        if (!m.att) m.att = _noAttempts();
        if (!m.keep) m.keep = { clean: null, cheat: null };
        if (m.last == null) m.last = now;   // written by an older tab: its clock starts now
      }
      if (!d.finishPool) d.finishPool = {};
      return d;
    }
  } catch (e) { /* corrupt or storage blocked → start fresh */ }
  return { version: 1, schema: 2, nextId: 1, maps: {}, finishPool: {} };
}
// The incl.-cheats track, seeded from a map's clean bests.
function _cleanAll(m) {
  return { score: m.bestScore, scoreCheated: false, scoreParts: m.bestScoreParts || null,
           time: m.bestTime, timeCheated: false };
}
// Attempt counters (records_rules.js says what counts). Slow-mo-only runs are cheated
// attempts, and also tracked on their own (slow, slowMax) since their physics is stock.
function _noAttempts() { return { clean: 0, max: 0, n1700: 0, cheat: 0, slow: 0, slowMax: 0 }; }
function _newEntry() {
  return { id: null, bestScore: 0, bestTime: null, all: _cleanAll({ bestScore: 0, bestTime: null }),
           att: _noAttempts(), keep: { clean: null, cheat: null }, pinned: false, last: Date.now() };
}
function _clean(m) { return m.bestScore > 0 || m.bestTime != null; }
function _cheatOnly(m) { return !_clean(m) && (m.all.score > 0 || m.all.time != null); }
function _promote(d, m) { if (m.id == null) m.id = d.nextId++; }
// Listed in the Records menu without "Show all". A pinned map holding only cheated
// records is hidden with the cheat records, like any other cheat-only map.
function _listed(m, showCheats) {
  return !!(m.keep.clean || (m.pinned && !_cheatOnly(m)) || (showCheats && (m.keep.cheat || m.pinned)));
}
function _exempt(key, m, saved) {
  return !!(m.keep.clean || m.keep.cheat || m.pinned || saved[key] || key === S.mapKey);
}
function _save(d) {
  try { localStorage.setItem(KEY, JSON.stringify(d)); return true; }
  catch (e) { _warn("Records not saved: browser storage is full or blocked."); return false; }
}
// A failed write must be visible: a silently dropped record looks like "no record on this map".
function _warn(msg) {
  console.warn(`[records] ${msg}`);
  const el = document.getElementById("status");
  if (el) el.textContent = msg;
}

// Best score / fastest finish over all maps, with the key of the map holding each.
function _global(d) {
  const g = { bestScore: 0, bestScoreKey: "", bestTime: null, bestTimeKey: "" };
  for (const [k, m] of Object.entries(d.maps)) {
    if (m.bestScore > g.bestScore) { g.bestScore = m.bestScore; g.bestScoreKey = k; }
    if (m.bestTime != null && (g.bestTime == null || m.bestTime < g.bestTime)) { g.bestTime = m.bestTime; g.bestTimeKey = k; }
  }
  return g;
}
// Same over the incl.-cheats track (+ whether each winning value was a cheated run).
function _globalAll(d) {
  const g = { score: 0, scoreKey: "", scoreCheated: false, time: null, timeKey: "", timeCheated: false };
  for (const [k, m] of Object.entries(d.maps)) {
    const a = m.all;
    if (a.score > g.score) { g.score = a.score; g.scoreKey = k; g.scoreCheated = a.scoreCheated; }
    if (a.time != null && (g.time == null || a.time < g.time)) { g.time = a.time; g.timeKey = k; g.timeCheated = a.timeCheated; }
  }
  return g;
}

// ---- "Show cheat records" setting (shared by the Records menu and the end card) ----
const SHOW_KEY = "hcr_show_cheat_records";
let _show = null;
export function showCheatRecords() {
  if (_show === null) { try { _show = localStorage.getItem(SHOW_KEY) === "1"; } catch (e) { _show = false; } }
  return _show;
}
export function setShowCheatRecords(on) {
  _show = !!on;
  try { localStorage.setItem(SHOW_KEY, _show ? "1" : "0"); } catch (e) {}
  refreshRecordsStrip();   // labels of cheat-only maps appear/disappear
  document.dispatchEvent(new Event("hcr-cheat-records-toggled"));
}

// ---- Map identity ------------------------------------------------------------
// FNV-1a over the px vertices rounded to 0.1 px (absorbs the px↔m save/load round trip).
function _hashVerts(pxVerts, spawningY) {
  let h = 0x811c9dc5;
  const mix = n => { h ^= n & 0xffff; h = Math.imul(h, 0x01000193); h ^= n >>> 16; h = Math.imul(h, 0x01000193); };
  for (const [x, y] of pxVerts) { mix(Math.round(x * 10)); mix(Math.round(y * 10)); }
  mix(Math.round(spawningY * 10));
  return (h >>> 0).toString(36);
}
export function mapKeyOf(ground) {
  return _hashVerts(ground.vectors.map(v => [v.x * SCALE, v.y * SCALE]), getSpawningY());
}

// ---- Stored terrains -----------------------------------------------------------
// Vertices are kept exactly (meters, as Float64 → base64, ~14 KB/map) with the grass
// layout, so a re-loaded record map is bit-identical to the one the record was set on.
// A freshly generated map's x's are exactly k*smoothness/SCALE (+ the 2 closing verts),
// so they're only stored when they don't match that (e.g. a px-round-tripped map).
function _f64ToB64(arr) {
  const u8 = new Uint8Array(new Float64Array(arr).buffer);
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}
function _b64ToF64(b64) {
  const s = atob(b64), u8 = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) u8[i] = s.charCodeAt(i);
  return Array.from(new Float64Array(u8.buffer));
}
// IndexedDB "hcr_records": "terrains" (map key → stored terrain) and "backup" (the
// localStorage blobs as they were before the move, kept in case the migration misbehaved).
const _req = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
let _dbp = null;
function _db() {
  if (!_dbp) {
    const r = indexedDB.open("hcr_records", 1);
    r.onupgradeneeded = () => { r.result.createObjectStore("terrains"); r.result.createObjectStore("backup"); };
    _dbp = _req(r);
  }
  return _dbp;
}
async function _tx(store, mode, fn) {
  const t = (await _db()).transaction(store, mode);
  const out = fn(t.objectStore(store));
  await new Promise((res, rej) => { t.oncomplete = res; t.onerror = t.onabort = () => rej(t.error); });
  return out;
}
const _storedKeys = new Set();   // keys with a terrain in IndexedDB, filled by initRecords()

function _legacyMaps() {
  try { return JSON.parse(localStorage.getItem(LEGACY_MAPS_KEY) || "{}") || {}; } catch (e) { return {}; }
}
function _regularXs(g, n) {
  const xs = [];
  for (let k = 0; k < n - 2; k++) xs.push((k * g.smoothness) / SCALE);
  xs.push(g.distance / SCALE, 0 / SCALE);
  return xs;
}
function _storeCurrentMap(key) {
  if (_storedKeys.has(key)) return;
  const g = S.ground, n = g.vectors.length;
  const reg = _regularXs(g, n);
  const regular = g.vectors.every((v, i) => v.x === reg[i]);
  const t = {
    n, smoothness: g.smoothness, distance: g.distance,
    xs: regular ? null : _f64ToB64(g.vectors.map(v => v.x)),
    ys: _f64ToB64(g.vectors.map(v => v.y)),
    grass: g.grassPositions.map(x => (x < 0 ? "." : String(x))).join(""),   // sprite idx 0-4, "." = none
    spawning_y: getSpawningY(),
    tuned: !!g.tuned,   // a physics-playground map: runs on it stay "cheated" when re-loaded
  };
  _storedKeys.add(key);
  _tx("terrains", "readwrite", s => s.put(t, key)).catch(e => {
    _storedKeys.delete(key);   // the record still counts; the map just can't be re-loaded
    _warn(`This map's terrain wasn't stored (${e && e.message}), so it can't be re-loaded from Records.`);
  });
}
// A Ground.cloneFrom() source for a record map, or null if its terrain wasn't stored.
export async function recordMapSource(key) {
  let t = null;
  try { t = await _tx("terrains", "readonly", s => s.get(key)).then(r => r.result); } catch (e) {}
  if (!t) t = _legacyMaps()[key];   // not migrated yet (IndexedDB unavailable)
  if (!t) return null;
  try {
    const ys = _b64ToF64(t.ys);
    const xs = t.xs ? _b64ToF64(t.xs) : _regularXs(t, t.n);
    const grass = Array.from(t.grass, c => (c === "." ? -1 : Number(c)));
    return { vectors: xs.map((x, i) => new Vec2(x, ys[i])), grassPositions: grass,
             spawning_y: t.spawning_y, tuned: !!t.tuned };
  } catch (e) { return null; }
}
function _dropTerrains(keys) {
  for (const k of keys) _storedKeys.delete(k);
  _tx("terrains", "readwrite", s => { for (const k of keys) s.delete(k); }).catch(() => {});
}
export function deleteRecordMap(key) {
  const d = _load();
  delete d.maps[key];
  _save(d);
  _dropTerrains([key]);
  refreshRecordsStrip();
}

// Startup: move terrains out of localStorage (backing up both blobs first), then index
// what's stored. An older tab may still write the legacy key, so this runs on every load.
export async function initRecords() {
  try {
    const raw = localStorage.getItem(LEGACY_MAPS_KEY);
    if (raw) {
      const have = await _tx("backup", "readonly", s => s.get("v1")).then(r => r.result);
      if (!have) await _tx("backup", "readwrite", s => s.put({ records: localStorage.getItem(KEY), maps: raw,
                                                              at: new Date().toISOString() }, "v1"));
      const legacy = JSON.parse(raw) || {};
      await _tx("terrains", "readwrite", s => { for (const [k, t] of Object.entries(legacy)) s.put(t, k); });
      localStorage.removeItem(LEGACY_MAPS_KEY);
    }
    const keys = await _tx("terrains", "readonly", s => s.getAllKeys()).then(r => r.result);
    for (const k of keys) _storedKeys.add(k);
  } catch (e) {
    for (const k of Object.keys(_legacyMaps())) _storedKeys.add(k);
    _warn(`Record maps' terrains couldn't move to IndexedDB (${e && e.message}).`);
  }
  if (_load().schema !== 2) await _migrateLegacy();
  _expire();
  refreshRecordsStrip();
}
// Entries from before attempts were counted get their notability from classifyLegacy();
// the rest start a fresh KEEP_DAYS clock and lose their id.
async function _migrateLegacy() {
  const runs = await _humanRunSummaries();
  const d = _load(), now = Date.now();
  const cls = classifyLegacy(Object.entries(d.maps).map(([key, m]) => ({ key, ...m })), runs, FRAME_RATE);
  for (const [k, m] of Object.entries(d.maps)) {
    const c = cls[k];
    m.att = c.att; m.keep = { clean: c.clean, cheat: c.cheat }; m.pinned = false; m.last = now;
    if (!c.clean && !c.cheat) m.id = null;
    if (m.bestTime != null) d.finishPool[k] = m.bestTime;
  }
  d.schema = 2;
  _save(d);
}
// The human-run recorder's run summaries (dev mode), or [] if it never recorded.
async function _humanRunSummaries() {
  try {
    if (indexedDB.databases && !(await indexedDB.databases()).some(x => x.name === "hcr_human_runs")) return [];
    const db = await _req(indexedDB.open("hcr_human_runs"));
    if (!db.objectStoreNames.contains("runs")) { db.close(); return []; }
    const runs = await _req(db.transaction("runs", "readonly").objectStore("runs").getAll());
    db.close();
    return runs;
  } catch (e) { return []; }
}
// Drop unlisted maps whose last attempt is over KEEP_DAYS old. Only on schema-2 data,
// whose notability has been worked out (older entries would all look expendable).
function _expire() {
  const d = _load();
  if (d.schema !== 2) return;
  const saved = _savedNames(), cut = Date.now() - KEEP_DAYS * DAY_MS, gone = [];
  for (const [k, m] of Object.entries(d.maps)) {
    if (!_exempt(k, m, saved) && m.last < cut) { delete d.maps[k]; gone.push(k); }
  }
  if (!gone.length) return;
  _save(d);
  _dropTerrains(gone);
}

// ---- Labels --------------------------------------------------------------------
function _savedNames() {
  const out = {};
  for (const t of loadSavedTerrains()) {
    try { out[_hashVerts(t.vertices, t.spawning_y)] = t.name; } catch (e) {}
  }
  return out;
}
function _label(d, key, saved) {
  const m = key && d.maps[key];
  if (!m) return "";
  // A map holding only cheated records stays anonymous while those are hidden.
  if (_cheatOnly(m) && !showCheatRecords()) return "";
  return saved[key] || (m.id != null ? `Record map ${m.id}` : "");
}
export function recordMapLabel(key) { return _label(_load(), key, _savedNames()); }

// Every map with an entry for the Records menu, oldest id first, unlisted (no id) last.
// `listed` = shown without "Show all"; `expiresIn` = days left, null when kept for good.
export function listRecordMaps() {
  const d = _load(), saved = _savedNames(), g = _global(d), ga = _globalAll(d), now = Date.now();
  const show = showCheatRecords();
  return Object.entries(d.maps)
    .map(([key, m]) => ({ key, id: m.id, label: _label(d, key, saved), bestScore: m.bestScore,
                          bestScoreParts: m.bestScoreParts || null,
                          bestTime: m.bestTime, loadable: _storedKeys.has(key),
                          clean: _clean(m), cheatOnly: _cheatOnly(m), all: m.all, att: m.att, keep: m.keep,
                          pinned: !!m.pinned,
                          saved: !!saved[key], listed: _listed(m, show),
                          expiresIn: _exempt(key, m, saved) ? null
                                     : Math.max(0, Math.ceil((m.last + KEEP_DAYS * DAY_MS - now) / DAY_MS)),
                          globalScore: key === g.bestScoreKey, globalTime: key === g.bestTimeKey,
                          globalAllScore: key === ga.scoreKey, globalAllTime: key === ga.timeKey }))
    .sort((a, b) => (a.id ?? Infinity) - (b.id ?? Infinity));
}

// Pin = keep for good and list, without a Saved name. Pinning the loaded map creates its
// entry if no run has yet. Unpinning returns it to the normal rules, clock included.
export function setPinned(key, on) {
  const d = _load();
  let m = d.maps[key];
  if (!m) {
    if (!on || key !== S.mapKey) return;
    m = d.maps[key] = _newEntry();
    _storeCurrentMap(key);
  }
  m.pinned = !!on;
  if (on) _promote(d, m);
  _save(d);
  refreshRecordsStrip();
}
export function isPinned(key) { const m = _load().maps[key]; return !!(m && m.pinned); }

export function mapRecord(key) {
  const m = _load().maps[key];
  return { bestScore: m ? m.bestScore : 0, bestTime: m ? m.bestTime : null };
}
export function globalRecord() { return _global(_load()); }
export function mapRecordAll(key) {
  const m = _load().maps[key];
  return m ? m.all : { score: 0, scoreCheated: false, time: null, timeCheated: false };
}
export function globalRecordAll() { return _globalAll(_load()); }

// ---- Runs ----------------------------------------------------------------------
// Seconds a player has been driving: frozen at the finish, or at death.
export function runSeconds(p) {
  const t = p.beatTick || p.deadTick || S.tickCount;
  return t / FRAME_RATE;
}
export function fmtTime(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60), s = sec - m * 60;
  return `${m}:${s < 10 ? "0" : ""}${s.toFixed(2)}`;
}

// Anything that makes a run easier than a straight drive.
export function cheatsActive() { return S.simSpeed < 1 || physicsModified(); }
// The subset that changes the physics itself (slow-mo only changes the player's reaction time).
export function physicsModified() {
  return S.bpInvincible || S.bpZeroG || S.bpFlight || S.bpRocket || S.bpPhysModified
      || !!(S.ground && S.ground.tuned);   // a playground-generated map (flat/short/...)
}

// "clean", "cheat" or null (an abandon). Runs that only used slow-mo are cheated runs;
// S.runModified tells them apart from physics cheats.
function _attemptKind(p, score, cheated) {
  if ((p.deadTick || S.tickCount) < ATTEMPT_SEC * FRAME_RATE) return null;
  if (cheated) return "cheat";
  return score >= ATTEMPT_SCORE ? "clean" : null;
}

// Fold a human run into the records; idempotent, so it's called on finish, death and abandon.
// `ended` (death or abandon) counts the attempt, once per run. Flags for the end card go on p.newRec.
export function commitRun(p, score, parts, ended = false) {
  if (!p || p.isAI || !S.mapKey) return;
  const cheated = S.runTainted;
  const time = p.beatTick ? p.beatTick / FRAME_RATE : null;
  const d = _load();
  const g = _global(d), ga = _globalAll(d);
  const prev = d.maps[S.mapKey] || _newEntry();
  const betterScore = !cheated && score > prev.bestScore;
  const betterTime = !cheated && time != null && (prev.bestTime == null || time < prev.bestTime);
  const allScore = score > prev.all.score;
  const allTime = time != null && (prev.all.time == null || time < prev.all.time);
  let attempt = null;
  if (ended && !p.attemptCounted) { p.attemptCounted = true; attempt = _attemptKind(p, score, cheated); }
  const finishedNow = !cheated && time != null && !p.finishSeen;
  if (finishedNow) p.finishSeen = true;
  if (!betterScore && !betterTime && !allScore && !allTime && !attempt && !finishedNow) return;
  if (!d.maps[S.mapKey]) {
    d.maps[S.mapKey] = prev;
    _storeCurrentMap(S.mapKey);
  }
  const m = d.maps[S.mapKey];
  m.last = Date.now();
  const a = m.att;
  if (attempt === "clean") {
    a.clean += 1; a.max = Math.max(a.max, score);
    if (score >= NEAR_FINISH) a.n1700 += 1;
  } else if (attempt === "cheat") {
    a.cheat += 1;
    if (!S.runModified && score >= ATTEMPT_SCORE) { a.slow += 1; a.slowMax = Math.max(a.slowMax, score); }
  }
  const nr = p.newRec || (p.newRec = {});
  nr.cheated = cheated;
  if (betterScore) { m.bestScore = score; m.bestScoreParts = parts || null; nr.mapScore = true; }
  if (betterTime) { m.bestTime = time; nr.mapTime = true; }
  if (betterScore && score > g.bestScore) nr.globalScore = true;
  if (betterTime && (g.bestTime == null || time < g.bestTime)) nr.globalTime = true;
  if (allScore) { m.all.score = score; m.all.scoreCheated = cheated; m.all.scoreParts = parts || null; nr.allMapScore = true; }
  if (allTime) { m.all.time = time; m.all.timeCheated = cheated; nr.allMapTime = true; }
  if (allScore && score > ga.score) nr.allGlobalScore = true;
  if (allTime && (ga.time == null || time < ga.time)) nr.allGlobalTime = true;
  // The finish-time pool keeps every map's clean best, even after the map expires, so
  // pruning slow maps doesn't tighten the fastest-quarter cutoff.
  if (finishedNow) d.finishPool[S.mapKey] = m.bestTime;
  const wasKept = !!(m.keep.clean || m.keep.cheat);
  const why = _keepReasons(d, m, nr, finishedNow);
  if (!m.keep.clean && why.clean) m.keep.clean = why.clean;
  if (!m.keep.cheat && why.cheat) m.keep.cheat = why.cheat;
  if (!wasKept && (m.keep.clean || m.keep.cheat)) {
    _promote(d, m);
    nr.kept = m.keep.clean || m.keep.cheat;
    nr.keptCheatOnly = !m.keep.clean;
  }
  _save(d);
  refreshRecordsStrip();
}
// Why this run makes the map notable, per track (null = it doesn't). Sticky: commitRun
// only ever sets a reason, so a map stays kept after the finish cutoff tightens.
function _keepReasons(d, m, nr, finishedNow) {
  const a = m.att, r = { clean: null, cheat: null };
  if (nr.globalScore || nr.globalTime) r.clean = "all-maps best";
  else if (m.bestTime != null) {
    if (finishedNow && m.bestTime <= fastCutoff(Object.values(d.finishPool))) r.clean = "fastest-quarter finish";
    else if (finishNotable(a.n1700)) r.clean = `finished, ${a.n1700} runs of ${NEAR_FINISH}+`;
  } else if (ladder(a.clean, a.max)) r.clean = `${a.clean} attempts, best ${a.max}`;
  if (nr.cheated && (nr.allGlobalScore || nr.allGlobalTime)) r.cheat = "all-maps best incl. cheats";
  else if (a.cheat >= CHEAT_ATTEMPTS) r.cheat = `${a.cheat} cheated attempts`;
  else if (ladder(a.slow, a.slowMax)) r.cheat = `${a.slow} slow-mo attempts, best ${a.slowMax}`;
  return r;
}

// The four tiles under the toolbar. Re-run after the Saved list changes so labels follow
// saves, renames and deletes.
export function refreshRecordsStrip() {
  const d = _load();
  const saved = _savedNames();
  const mr = (S.mapKey && d.maps[S.mapKey]) || { bestScore: 0, bestTime: null };
  const g = _global(d);
  const set = (id, v, sub) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelector(".rec-val").textContent = v;
    const s = el.querySelector(".rec-sub");
    if (s) { s.textContent = sub; s.title = sub; }
  };
  const here = _label(d, S.mapKey, saved);
  const hereSfx = here ? ` (${here})` : "";
  set("rec_map_score", mr.bestScore || "—", `best score · this map${hereSfx}`);
  set("rec_map_time",  fmtTime(mr.bestTime), `fastest finish · this map${hereSfx}`);
  const sl = _label(d, g.bestScoreKey, saved), tl = _label(d, g.bestTimeKey, saved);
  set("rec_all_score", g.bestScore || "—", `best score · all maps${sl ? ` (${sl})` : ""}`);
  set("rec_all_time",  fmtTime(g.bestTime), `fastest finish · all maps${tl ? ` (${tl})` : ""}`);
  const pin = document.getElementById("rec_pin");
  if (pin) {
    const on = !!(S.mapKey && d.maps[S.mapKey] && d.maps[S.mapKey].pinned);
    pin.classList.toggle("on", on);
    pin.disabled = !S.mapKey;
    pin.title = on ? "Pinned: kept in Records for good. Click to unpin."
                   : "Pin this map: keep it in Records for good, without saving it";
  }
  // Labels may have changed (new record map, save/rename/delete) — main.js refreshes the
  // Map chip on this (an event, since sim.js already imports this module).
  document.dispatchEvent(new Event("hcr-records-changed"));
}
