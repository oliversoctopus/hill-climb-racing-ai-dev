// Persistence for user-named terrains in the browser's localStorage. Pure storage —
// no DOM, no sim; just the JSON blob under one versioned key. The menu UI (render,
// prompt, confirm) lives in main.js.
//
// Blob shape: { version: 1, terrains: [{ name, vertices, spawning_y }] }, with vertices
// in PIXELS ([[x, y], ...]) — the same loadedTrack format the session terrains use, so a
// saved map re-loads through the normal pinned-track path (sim.makeSourceFromTrack).
// It's keyed to the page origin, so saved maps survive close/reopen and redeploys, but
// only on the same browser + domain (see HOW_TO_PLAY). The `version` field lets a future
// format change detect and skip stale blobs instead of choking on them.
const KEY = "hcr_saved_terrains_v1";

export function loadSavedTerrains() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const data = JSON.parse(raw);
    if (data && data.version === 1 && Array.isArray(data.terrains)) return data.terrains;
  } catch (e) { /* corrupt JSON or storage unavailable → treat as empty */ }
  return [];
}

// Write the whole list back. Returns true on success, false if storage rejected it
// (quota exceeded, or disabled e.g. private mode) so callers can surface a message.
function _write(terrains) {
  try { localStorage.setItem(KEY, JSON.stringify({ version: 1, terrains })); return true; }
  catch (e) { return false; }
}

// Append one terrain. Returns the updated array on success, or null if the write failed.
export function addSavedTerrain(terrain) {
  const all = loadSavedTerrains();
  all.push(terrain);
  return _write(all) ? all : null;
}

// Remove the terrain at `index`. Returns the updated array (unchanged if out of range).
export function removeSavedTerrain(index) {
  const all = loadSavedTerrains();
  if (index < 0 || index >= all.length) return all;
  all.splice(index, 1);
  _write(all);
  return all;
}

// Rename the terrain at `index`. Returns the updated array, or null on write failure.
// Caller is responsible for uniqueness checks (findSavedByName) before calling.
export function renameSavedTerrain(index, newName) {
  const all = loadSavedTerrains();
  if (index < 0 || index >= all.length) return all;
  all[index].name = newName;
  return _write(all) ? all : null;
}

// ---- Duplicate detection -------------------------------------------------
// Names are unique case-SENSITIVELY (so "Map" and "map" are distinct), after trimming
// surrounding whitespace. Returns the index of an existing terrain with the same name,
// or -1. `exceptIndex` is skipped so a rename doesn't clash with the terrain being renamed.
function _norm(name) { return (name || "").trim(); }
export function findSavedByName(name, exceptIndex) {
  const key = _norm(name);
  const all = loadSavedTerrains();
  for (let i = 0; i < all.length; i++) {
    if (i === exceptIndex) continue;
    if (_norm(all[i].name) === key) return i;
  }
  return -1;
}

// A save→load→save round trip (÷SCALE, ×SCALE) changes px vertices by float rounding,
// so compare with a tolerance far below the whole-pixel spacing between maps.
const GEO_EPS = 1e-6;
function _closeEq(a, b) { return Math.abs(a - b) <= GEO_EPS; }
function _sameGeometry(a, b) {
  if (!a || !b || !_closeEq(a.spawning_y, b.spawning_y)) return false;
  const av = a.vertices, bv = b.vertices;
  if (!Array.isArray(av) || !Array.isArray(bv) || av.length !== bv.length) return false;
  for (let i = 0; i < av.length; i++) {
    if (!_closeEq(av[i][0], bv[i][0]) || !_closeEq(av[i][1], bv[i][1])) return false;
  }
  return true;
}
// Index of a saved terrain with the same geometry as `terrain`, or -1.
export function findSavedByGeometry(terrain, exceptIndex) {
  const all = loadSavedTerrains();
  for (let i = 0; i < all.length; i++) {
    if (i === exceptIndex) continue;
    if (_sameGeometry(all[i], terrain)) return i;
  }
  return -1;
}
