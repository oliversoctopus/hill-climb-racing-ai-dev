// Entry point: loads assets + the AI agent, runs the wall-clock loop, and wires
// every DOM control. This is the only module that touches the page's buttons/inputs
// and the requestAnimationFrame loop; the concern modules it imports do the work.
import {
  S, CANVAS_HEIGHT, SIM_DT, SCALE,
  FLIGHT_SPEED_MIN, FLIGHT_SPEED_MAX, FLIGHT_SPEED_STEP, FLIGHT_SPEED_STEP_HI, FLIGHT_SPEED_STEP_BREAK,
  ROCKET_ACCEL_MIN, ROCKET_ACCEL_MAX, ROCKET_ACCEL_STEP, LEGENDARY_FLYOFF,
} from "./state.js";
import { AiPolicy, setGrassSprites, getSpawningY } from "./bridge.js";
import { modeLabel, stageWidth } from "./modes.js";
import { buildSimulation, buildWithGround, currentGroundSource, runOneStep,
         refreshSessionTerrainsMenu, updateCurrentTerrainBox } from "./sim.js";
import { loadSavedTerrains, addSavedTerrain, removeSavedTerrain, renameSavedTerrain,
         findSavedByName, findSavedByGeometry } from "./saved_terrains.js";
import { render, updateStats } from "./render.js";
import { refreshRecordsStrip, listRecordMaps, recordMapSource, recordMapLabel, deleteRecordMap,
         fmtTime, showCheatRecords, setShowCheatRecords, initRecords, setPinned, isPinned } from "./records.js";
import { runBestOfX, watchSelectedRun, _bestofxPanelVisible, runBacktrack } from "./search.js";
import {
  bpSetStatus, bpSetZeroG, bpFloatCar, bpUnderworld, bpStop, bpToggleExit,
  bpTeleport, bpTeleportCurrent, bpFlag, bpDownload, showToast,
} from "./cheats.js";
import { focusGame, _handleGameKey, _handleActionKey, _handleModeKey } from "./input.js";
import { buildTunePanel, setTune, resetTune, TUNE_PRESETS } from "./tune.js";
import { initDevMode, devAfterInit } from "./dev.js";
import { initHumanRuns } from "./humanruns.js";

export function setStatus(s) { document.getElementById("status").textContent = s; }

// ---- Assets --------------------------------------------------------------
// Mirrors sketch.js preload() — the same files the original browser game used.
function _loadImg(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => { resolve(img); };
    img.onerror = () => { reject(new Error(`failed to load ${src}`)); };
    img.src = src;
  });
}
async function loadAssets() {
  const paths = {
    sky:    "Pics/sky.png",
    car:    "Pics/car.png",
    wheel:  "Pics/wheel2.png",
    head:   "Pics/headLarge.png",   // person head (human cars)
    cbhead: "Pics/CBHead3.png",     // Code Bullet's computer-ish head (AI cars)
    g0:    "Pics/grass.png",
    g1:    "Pics/grass2.png",
    g2:    "Pics/grass3.png",
    g3:    "Pics/grass4.png",
    g4:    "Pics/grass5.png",
  };
  const keys = Object.keys(paths);
  const imgs = await Promise.all(keys.map(k => _loadImg(paths[k])));
  for (let i = 0; i < keys.length; i++) S.assets[keys[i]] = imgs[i];
  S.assets.grass = [S.assets.g0, S.assets.g1, S.assets.g2, S.assets.g3, S.assets.g4];
  // Replace the stub grassSprites polyfill with the real loaded array so
  // Ground.randomizeGround()'s grassPositions stay valid for rendering.
  setGrassSprites(S.assets.grass);
}

function _setupHiDPI() {
  // Fit the stage to the window (as big as fits without pushing the toolbar off-screen),
  // with the backing store at device resolution so it stays crisp at any size. The
  // drawing code always works in logical 1280×720 units (2560 wide for split screen);
  // the context transform maps those onto however many real pixels we have.
  const canvas = document.getElementById("stage");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = stageWidth(), h = CANVAS_HEIGHT;
  const fs = !!document.fullscreenElement;   // fullscreen: the stage gets the whole screen
  const availW = fs ? window.innerWidth : document.documentElement.clientWidth - 32;
  const availH = fs ? window.innerHeight : Math.max(360, window.innerHeight - 190);
  const cssW = Math.floor(Math.min(availW, availH * w / h));
  const cssH = Math.round(cssW * h / w);
  canvas.width  = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.style.width  = `${cssW}px`;
  canvas.style.height = `${cssH}px`;
  const k = canvas.width / w;
  ctx.setTransform(k, 0, 0, k, 0, 0);
  ctx.imageSmoothingQuality = "high";
  if (!fs) document.documentElement.style.setProperty("--stage-w", `${Math.max(cssW, 960)}px`);
}
window.addEventListener("resize", () => _setupHiDPI());
// Exported so the backtrack search can shrink the 2×-wide split canvas back to 1×.
export { _setupHiDPI };

// ---- Wall-clock loop -----------------------------------------------------
// Physics dt is fixed at 1/30 simulated seconds per step (Box2D wants a fixed
// timestep). We accumulate real wall time and run however many steps that
// corresponds to. simSpeed multiplies the accumulator so "2x" = 2 simulated seconds
// per real second.
const STALL_SEC = 0.1;
let _lastDt = 1 / 60;
async function loop() {
  const now = performance.now();
  if (S.lastWallMs === 0) S.lastWallMs = now;
  // A longer gap is a stall (an extension script, a background tab): resume where the
  // screen froze instead of catching up, so no physics runs that the player never saw.
  const gap = (now - S.lastWallMs) / 1000;
  S.lastWallMs = now;
  if (gap <= STALL_SEC) _lastDt = gap;
  const realDt = gap <= STALL_SEC ? gap : _lastDt;

  let didStep = false;
  if (!S.paused && S.aiAgent && !S.bestofxBusy) {
    S.accumSec += realDt * S.simSpeed;
    while (S.accumSec >= SIM_DT) {
      S.inStep = true;
      const allDead = await runOneStep();
      S.inStep = false;
      S.accumSec -= SIM_DT;
      didStep = true;
      if (allDead) { S.accumSec = 0; break; }
    }
  }

  // Render EVERY rAF: physics stays at 30 Hz sim-time, render() smooths the frames
  // in between (see render.js). Skip while the Best-of-X / backtrack search owns the
  // world — its headless loop bypasses the pose snapshots.
  if (!S.bestofxBusy) render();
  syncModeTabs();
  if (didStep || S.paused) updateStats();   // the DOM stats only change on a step
  requestAnimationFrame(loop);
}

async function init() {
  _setupHiDPI();
  setStatus("Loading sprites...");
  try {
    await loadAssets();
  } catch (e) {
    setStatus(`ERROR loading assets: ${e.message}`);
    throw e;
  }

  // Pick the AI agent here. Swap to a different class (or args) to deploy a different
  // model — no other file changes. See ai_policy.js for the Agent contract.
  setStatus("Loading AI agent...");
  S.aiAgent = new AiPolicy.PpoOnnxAgent("ai_policy.onnx");
  try {
    await S.aiAgent.init();
  } catch (e) {
    setStatus(`ERROR loading agent: ${e.message}`);
    throw e;
  }

  devAfterInit();   // dev mode: loads AI B in the background if already unlocked

  setStatus("Building simulation...");
  buildSimulation();
  setStatus(`Ready — ${modeLabel()}`);
  requestAnimationFrame(loop);
}

// ---- DOM wiring ----------------------------------------------------------
// Mode tabs: a face for the hidden #mode <select>, which stays the source of truth
// (Alt+1…5 and the search code drive it). Synced every frame — cheap, and it catches
// every path that changes or disables the select.
const _modeTabs = Array.from(document.querySelectorAll("#mode_tabs button"));
_modeTabs.forEach(b => {
  b.onclick = () => {
    const sel = document.getElementById("mode");
    if (sel.disabled || sel.value === b.dataset.mode) return;
    sel.value = b.dataset.mode;
    sel.dispatchEvent(new Event("change"));
  };
});
let _tabState = "";
function syncModeTabs() {
  const sel = document.getElementById("mode");
  const st = `${sel.value}|${sel.disabled}`;
  if (st === _tabState) return;
  _tabState = st;
  for (const b of _modeTabs) { b.classList.toggle("active", b.dataset.mode === sel.value); b.disabled = sel.disabled; }
}
document.getElementById("mode").addEventListener("change", syncModeTabs);
syncModeTabs();

// Tools drawer (readouts, cheats, debug).
export function setDrawer(open) { document.getElementById("drawer").classList.toggle("open", open); }
document.getElementById("drawer_btn").onclick = () => {
  setDrawer(!document.getElementById("drawer").classList.contains("open"));
};
document.getElementById("drawer_close").onclick = () => { setDrawer(false); };

// Top controls
document.getElementById("reset_pos").onclick = () => {
  // "Restart (same terrain)" — put the car(s) back at the start of THIS map. No new
  // terrain: rebuild from a clone of the current ground. Exits ghost mode.
  S.replayActions = null;
  S.ghostPoses = null; S.ghostDone = false;
  setStatus("Restarting on the same terrain...");
  buildWithGround(currentGroundSource(), getSpawningY(), 0, 0);
  setStatus(`Ready — ${modeLabel()}`);
};
document.getElementById("reset").onclick = () => {
  // "Regenerate terrain" — throw away this map and generate a brand-new random one.
  if (S.mode === "bestofx") {
    S.bestofxRuns = [];
    document.getElementById("bestofx_results").style.display = "none";
    document.getElementById("bestofx_status").textContent = "";
  }
  // Clear any pinned track so a prior backtrack solve / loaded track isn't replayed
  // instead (the pin survives a Mode switch, but Regenerate always makes new).
  S.loadedTrack = null;
  setStatus("Building new terrain...");
  buildSimulation();
  setStatus(`Ready — ${modeLabel()}`);
};
// ---- Terrains + Saved Terrains menus ----
// Load a terrain object ({vertices px, spawning_y, name}) from either menu. Pinning it
// via loadedTrack means Restart re-drives it and a Mode switch keeps it (Regenerate
// clears it). Same path the old Terrains dropdown used.
function loadTerrainObject(t) {
  if (S.mode === "bestofx") {   // clear stale Best-of-X runs like Regenerate does
    S.bestofxRuns = [];
    document.getElementById("bestofx_results").style.display = "none";
    document.getElementById("bestofx_status").textContent = "";
  }
  S.loadedTrack = t.source ? { source: t.source, spawning_y: t.spawning_y, name: t.name }
                           : { vertices: t.vertices, spawning_y: t.spawning_y, name: t.name };
  S.currentTerrainName = t.name;
  S.currentTerrainUnsaved = false;   // it exists (just loaded from a menu)
  setStatus(`Loaded ${t.name} — ${modeLabel()}`);
  buildSimulation();
  updateCurrentTerrainBox();
  closeTerrainMenus();
  focusGame();
}
function closeTerrainMenus() {
  document.getElementById("terrains_panel").style.display = "none";
  document.getElementById("saved_panel").style.display = "none";
  document.getElementById("records_panel").style.display = "none";
}
// Records menu: all-maps bests, then every listed map with Load, Pin and Delete; "Show all"
// adds the unlisted ones. With "Show cheat records" on, sort by the incl.-cheats track.
const _sv = r => (showCheatRecords() ? r.all.score : r.bestScore);
const _tv = r => (showCheatRecords() ? r.all.time : r.bestTime);
const _byId = (a, b) => (a.id ?? Infinity) - (b.id ?? Infinity) || (_sv(b) - _sv(a));   // unlisted (no id) last
const REC_SORTS = {
  id:    _byId,
  score: (a, b) => (_sv(b) - _sv(a)) || _byId(a, b),
  // fastest finish first; unfinished maps last, among themselves by best score
  time:  (a, b) => ((_tv(a) == null) - (_tv(b) == null)) ||
                   (_tv(a) != null ? _tv(a) - _tv(b) : 0) ||
                   (_sv(b) - _sv(a)) || _byId(a, b),
};
let _recSort = "id", _recShowAll = false;
try { const v = localStorage.getItem("hcr_records_sort"); if (REC_SORTS[v]) _recSort = v; } catch (e) {}
try { _recShowAll = localStorage.getItem("hcr_records_show_all") === "1"; } catch (e) {}
function _recNote(r) {
  if (r.expiresIn != null) return r.expiresIn === 0 ? "expires today" : `expires in ${r.expiresIn} day${r.expiresIn === 1 ? "" : "s"}`;
  if (r.pinned) return "pinned";
  if (r.keep.clean || r.keep.cheat) return `kept: ${r.keep.clean || r.keep.cheat}`;
  return r.saved ? "kept: saved" : "kept while loaded";
}
function _recTile(val, sub, isTime) {
  const t = document.createElement("div");
  t.className = "rec" + (isTime ? " time" : "");
  const v = document.createElement("div"); v.className = "rec-val"; v.textContent = val;
  const s2 = document.createElement("div"); s2.className = "rec-sub"; s2.textContent = sub; s2.title = sub;
  t.append(v, s2);
  return t;
}
function renderRecordsMenu() {
  const list = document.getElementById("records_list");
  const summary = document.getElementById("records_summary");
  for (const b of document.querySelectorAll("#records_sort button")) b.classList.toggle("active", b.dataset.sort === _recSort);
  const show = showCheatRecords();
  document.getElementById("records_show_cheats").checked = show;
  document.getElementById("records_show_all").checked = _recShowAll;
  const all = listRecordMaps();
  const visible = show ? all : all.filter(r => !r.cheatOnly);   // a map can hold only cheated records
  const maps = visible.filter(r => r.listed || _recShowAll);
  list.innerHTML = ""; summary.innerHTML = "";
  if (!visible.length) {
    list.innerHTML = '<div class="menu-empty">No records yet. Drive a map (no cheats) and your best score and fastest finish land here.</div>';
    return;
  }
  const topScore = visible.find(r => r.globalScore), topTime = visible.find(r => r.globalTime);
  summary.append(
    _recTile(topScore ? topScore.bestScore : "—", `best score · any map${topScore ? ` (${topScore.label})` : ""}`),
    _recTile(topTime ? fmtTime(topTime.bestTime) : "—", `best time · any map${topTime ? ` (${topTime.label})` : " — no finishes yet"}`, true));
  if (show) {
    // The incl.-cheats bests; red + ⚠ when a cheated run holds them.
    const aS = visible.find(r => r.globalAllScore), aT = visible.find(r => r.globalAllTime);
    const tS = _recTile(aS ? (aS.all.scoreCheated ? "⚠" : "") + aS.all.score : "—",
                        `best score · incl. cheats${aS ? ` (${aS.label})` : ""}`);
    const tT = _recTile(aT ? (aT.all.timeCheated ? "⚠" : "") + fmtTime(aT.all.time) : "—",
                        `best time · incl. cheats${aT ? ` (${aT.label})` : " — no finishes yet"}`, true);
    tS.classList.toggle("cheat", !!(aS && aS.all.scoreCheated));
    tT.classList.toggle("cheat", !!(aT && aT.all.timeCheated));
    summary.append(tS, tT);
  }

  const head = document.createElement("div");
  head.className = "terrain-row rec-row rec-head";
  const cols = [["#", "id"], ["Map", null], ["Best score", "score"], ["Best time", "time"], ["", null]];
  for (const [txt, key] of cols) {
    const c = document.createElement("span");
    const arrow = key === _recSort ? (key === "score" ? " ▼" : key === "time" ? " ▲" : "") : "";
    c.textContent = txt + arrow;
    if (key && key === _recSort) c.className = "sorted";
    head.appendChild(c);
  }
  list.appendChild(head);
  if (!maps.length) {
    list.insertAdjacentHTML("beforeend", '<div class="menu-empty">No maps kept yet. A map is kept once you finish it ' +
      'fast, keep retrying it, or pin it; tick <b>Show all</b> to see the rest.</div>');
  }

  for (const r of maps.slice().sort(REC_SORTS[_recSort])) {
    const row = document.createElement("div");
    row.className = "terrain-row rec-row" + (r.listed ? "" : " unlisted");
    const id = document.createElement("span");
    id.className = "rec-id"; id.textContent = r.id != null ? `#${r.id}` : "—";
    const nm = document.createElement("span");
    nm.className = "terrain-name";
    nm.textContent = (r.label || "Unlisted map") + (r.key === S.mapKey ? "  (current)" : "");
    const note = document.createElement("small");
    note.className = "rec-note" + (r.expiresIn != null ? " expiring" : "");
    note.textContent = _recNote(r);
    nm.title = `${nm.textContent} · ${note.textContent}`;
    nm.appendChild(note);
    const stat = (cls, text, top, tip) => {
      const e = document.createElement("span");
      e.className = cls;
      if (top) { const t = document.createElement("span"); t.className = "trophy"; t.textContent = "🏆"; e.appendChild(t); }
      e.appendChild(document.createTextNode(text));
      e.title = tip;
      return e;
    };
    const sc = stat("rec-stat", String(r.bestScore || "—"), r.globalScore,
                    r.globalScore ? "best score on any map" : "best score on this map");
    const legend = r.bestScoreParts && r.bestScoreParts.flyoff >= LEGENDARY_FLYOFF;   // clean track only
    if (legend) {
      const g = document.createElement("span");
      g.className = "rec-legend"; g.textContent = " ✦";
      g.title = `Legendary fly-off: ${r.bestScoreParts.flyoff} points past the finish`;
      sc.appendChild(g);
    }
    const tm = stat("rec-stat time", fmtTime(r.bestTime), r.globalTime,
                    r.globalTime ? "fastest finish on any map" : (r.bestTime == null ? "not finished yet" : "fastest finish on this map"));
    if (show) {
      // A cheated run holds this map's incl.-cheats best: show it under the clean one.
      const cheatLine = (cell, text, top, tip) => {
        const c = document.createElement("span");
        c.className = "rec-cheat"; c.textContent = `⚠ ${text}${top ? " 🏆" : ""}`; c.title = tip;
        cell.appendChild(c);
      };
      if (r.all.scoreCheated) cheatLine(sc, String(r.all.score) + (r.all.scoreParts && r.all.scoreParts.after ? " ↗" : ""),
        r.globalAllScore, `best score incl. cheats${r.globalAllScore ? " on any map" : ""} — set by a cheated run`);
      if (r.all.timeCheated) cheatLine(tm, fmtTime(r.all.time), r.globalAllTime,
        `fastest finish incl. cheats${r.globalAllTime ? " on any map" : ""} — set by a cheated run`);
    }
    const acts = document.createElement("span");
    acts.className = "rec-actions";
    const load = document.createElement("button");
    load.textContent = "Load";
    load.dataset.recLoad = r.key;
    if (!r.loadable) { load.disabled = true; load.title = "This map's terrain wasn't stored (older record, or storage was full)"; }
    const pin = document.createElement("button");
    pin.textContent = "📌"; pin.className = "rec-pin-btn" + (r.pinned ? " on" : "");
    pin.dataset.recPin = r.key;
    pin.title = r.pinned ? "Pinned: kept for good. Click to unpin." : "Pin: keep this map for good, without saving it";
    const del = document.createElement("button");
    del.textContent = "Delete"; del.className = "danger";
    del.dataset.recDel = r.key;
    acts.append(load, pin, del);
    row.append(id, nm, sc, tm, acts);
    list.appendChild(row);

    // Score breakdown (finished runs only): ▸ toggle on the score, three parts when open.
    const parts = [];
    if (r.bestScoreParts) parts.push(["Clean best", r.bestScore, r.bestScoreParts, false]);
    if (show && r.all.scoreCheated && r.all.scoreParts) parts.push(["Incl. cheats", r.all.score, r.all.scoreParts, true]);
    if (!parts.length) continue;
    const open = _recExpanded.has(r.key);
    const tog = document.createElement("span");
    tog.className = "rec-expand"; tog.textContent = open ? "▾" : "▸";
    tog.dataset.recExpand = r.key;
    tog.title = "Score breakdown: to the finish · fly-off · after the fly-off";
    sc.prepend(tog);
    if (!open) continue;
    const box = document.createElement("div");
    box.className = "rec-parts";
    for (const [lbl, total, pt, cheated] of parts) {
      const line = document.createElement("div");
      if (cheated) line.className = "cheat";
      line.innerHTML = `<b></b> <span class="p-fin"></span> to finish · <span class="p-fly"></span> fly-off · ` +
                       `<span class="p-aft"></span> after fly-off`;
      line.querySelector("b").textContent = `${lbl} ${cheated ? "⚠" : ""}${total} =`;
      line.querySelector(".p-fin").textContent = pt.toFinish;
      // flyoffSec is missing on breakdowns recorded before it existed.
      line.querySelector(".p-fly").textContent = pt.flyoff + (pt.flyoffSec != null ? ` (${pt.flyoffSec.toFixed(1)} s)` : "");
      const aft = line.querySelector(".p-aft");
      aft.textContent = pt.after ? `↗${pt.after}` : "0";
      aft.classList.toggle("hot", pt.after > 0);
      if (!cheated && pt.flyoff >= LEGENDARY_FLYOFF) {
        line.querySelector(".p-fly").classList.add("legend");
        line.insertAdjacentHTML("beforeend", ' · <span class="legend">✦ legendary fly-off</span>');
      }
      box.appendChild(line);
    }
    list.appendChild(box);
  }
}
const _recExpanded = new Set();   // map keys whose score breakdown is open (this session)
document.getElementById("records_sort").onclick = (e) => {
  const k = e.target && e.target.dataset && e.target.dataset.sort;
  if (!k || !REC_SORTS[k]) return;
  _recSort = k;
  try { localStorage.setItem("hcr_records_sort", k); } catch (err) {}
  renderRecordsMenu();
};
function openRecordsMenu() {
  renderRecordsMenu();
  document.getElementById("records_panel").style.display = "block";
}
document.addEventListener("hcr-records-changed", updateCurrentTerrainBox);
// "Show cheat records": one setting, two checkboxes (Records menu + end card).
document.getElementById("records_show_cheats").onchange = (e) => setShowCheatRecords(e.target.checked);
document.getElementById("records_show_all").onchange = (e) => {
  _recShowAll = e.target.checked;
  try { localStorage.setItem("hcr_records_show_all", _recShowAll ? "1" : "0"); } catch (err) {}
  renderRecordsMenu();
};
document.getElementById("rec_pin").onclick = () => {
  if (S.mapKey) setPinned(S.mapKey, !isPinned(S.mapKey));
  if (document.getElementById("records_panel").style.display === "block") renderRecordsMenu();
  focusGame();
};
document.querySelector("#endcard_cheats input").onchange = (e) => { setShowCheatRecords(e.target.checked); focusGame(); };
document.addEventListener("hcr-cheat-records-toggled", () => {
  if (document.getElementById("records_panel").style.display === "block") renderRecordsMenu();
});
document.getElementById("records_btn").onclick = openRecordsMenu;
document.getElementById("records_title_btn").onclick = openRecordsMenu;
document.getElementById("records_close").onclick = () => { document.getElementById("records_panel").style.display = "none"; focusGame(); };
document.getElementById("records_list").onclick = (e) => {
  const el = e.target;
  if (!el || !el.dataset) return;
  if (el.dataset.recExpand !== undefined) {
    const k = el.dataset.recExpand;
    if (_recExpanded.has(k)) _recExpanded.delete(k); else _recExpanded.add(k);
    renderRecordsMenu();
  } else if (el.dataset.recLoad !== undefined) {
    const key = el.dataset.recLoad;
    recordMapSource(key).then(src => {
      if (!src) { setStatus("That map's terrain wasn't stored, so it can't be loaded."); return; }
      loadTerrainObject({ source: src, spawning_y: src.spawning_y, name: recordMapLabel(key) || "Unlisted map" });
    });
  } else if (el.dataset.recPin !== undefined) {
    setPinned(el.dataset.recPin, !isPinned(el.dataset.recPin));
    renderRecordsMenu();
  } else if (el.dataset.recDel !== undefined) {
    const label = recordMapLabel(el.dataset.recDel) || "this unlisted map";
    if (!window.confirm(`Delete your records on “${label}”? This can't be undone.`)) return;
    deleteRecordMap(el.dataset.recDel);
    renderRecordsMenu();
  }
};
// Render the Saved Terrains list from localStorage: one row per map with Load + Delete.
function renderSavedTerrainsMenu() {
  const list = document.getElementById("saved_list");
  const saved = loadSavedTerrains();
  list.innerHTML = "";
  if (!saved.length) {
    list.innerHTML = '<div class="menu-empty">No saved terrains yet. Find a map you like, then “Save Current Terrain”.</div>';
    return;
  }
  for (let i = 0; i < saved.length; i++) {
    const row = document.createElement("div");
    row.className = "terrain-row";
    const nm = document.createElement("span");
    nm.className = "terrain-name";
    nm.textContent = saved[i].name;
    const load = document.createElement("button");
    load.textContent = "Load";
    load.dataset.savedLoad = String(i);
    const ren = document.createElement("button");
    ren.textContent = "Rename";
    ren.dataset.savedRename = String(i);
    const del = document.createElement("button");
    del.textContent = "Delete";
    del.className = "danger";
    del.dataset.savedDel = String(i);
    row.appendChild(nm);
    row.appendChild(load);
    row.appendChild(ren);
    row.appendChild(del);
    list.appendChild(row);
  }
}
// Open buttons refresh their list first so it's always current.
document.getElementById("terrains_btn").onclick = () => {
  refreshSessionTerrainsMenu();
  document.getElementById("terrains_panel").style.display = "block";
};
document.getElementById("saved_btn").onclick = () => {
  renderSavedTerrainsMenu();
  document.getElementById("saved_panel").style.display = "block";
};
document.getElementById("terrains_close").onclick = () => { document.getElementById("terrains_panel").style.display = "none"; focusGame(); };
document.getElementById("saved_close").onclick    = () => { document.getElementById("saved_panel").style.display = "none"; focusGame(); };
// Delegated clicks on the session list: load by terrain id.
document.getElementById("terrains_list").onclick = (e) => {
  const el = e.target;
  if (!el || !el.dataset || el.dataset.sessionLoad === undefined) return;
  const id = parseInt(el.dataset.sessionLoad, 10);
  for (let i = 0; i < S.sessionTerrains.length; i++) {
    if (S.sessionTerrains[i].id === id) { loadTerrainObject(S.sessionTerrains[i]); return; }
  }
};
// Delegated clicks on the saved list: Load, or Delete-with-confirm (re-read from storage
// so the index is always against the current list).
document.getElementById("saved_list").onclick = (e) => {
  const el = e.target;
  if (!el || !el.dataset) return;
  if (el.dataset.savedLoad !== undefined) {
    const saved = loadSavedTerrains();
    const i = parseInt(el.dataset.savedLoad, 10);
    if (i >= 0 && i < saved.length) loadTerrainObject(saved[i]);
  } else if (el.dataset.savedRename !== undefined) {
    const saved = loadSavedTerrains();
    const i = parseInt(el.dataset.savedRename, 10);
    if (i < 0 || i >= saved.length) return;
    const oldName = saved[i].name;
    const newName = (window.prompt(`Rename “${oldName}” to:`, oldName) || "").trim();
    if (!newName || newName === oldName) return;   // cancelled, blank, or unchanged
    if (findSavedByName(newName, i) !== -1) {
      window.alert(`You already have a saved terrain named “${newName}”. Please choose a different name.`);
      return;
    }
    renameSavedTerrain(i, newName);
    refreshRecordsStrip();   // record labels use the live Saved name
    // If the renamed map is the one we're currently driving, rename the current box too.
    if (S.currentTerrainName === oldName) { S.currentTerrainName = newName; updateCurrentTerrainBox(); }
    renderSavedTerrainsMenu();
    setStatus(`Renamed “${oldName}” to “${newName}”.`);
  } else if (el.dataset.savedDel !== undefined) {
    const saved = loadSavedTerrains();
    const i = parseInt(el.dataset.savedDel, 10);
    if (i >= 0 && i < saved.length && window.confirm(`Delete saved terrain “${saved[i].name}”?`)) {
      const deletedName = saved[i].name;
      removeSavedTerrain(i);
      refreshRecordsStrip();
      // If we're currently driving the map we just deleted, keep it loaded but mark the
      // box "(unsaved)". The name stays so a re-save prefills it.
      if (S.currentTerrainName === deletedName) { S.currentTerrainUnsaved = true; updateCurrentTerrainBox(); }
      renderSavedTerrainsMenu();
    }
  }
};
// Save the CURRENT terrain to localStorage under a user-supplied name.
document.getElementById("save_current_btn").onclick = () => {
  if (!S.ground || !S.ground.vectors) { setStatus("No terrain to save yet."); return; }
  const terrain = {
    name: "",
    vertices: S.ground.vectors.map(v => [v.x * SCALE, v.y * SCALE]),   // px, loadedTrack format
    spawning_y: getSpawningY(),
  };
  // Block saving the same map twice — name which existing saved terrain it duplicates.
  const dupGeo = findSavedByGeometry(terrain);
  if (dupGeo !== -1) {
    const existing = loadSavedTerrains()[dupGeo];
    setStatus(`Already saved as “${existing.name}”.`);
    window.alert(`This terrain is identical to your saved terrain “${existing.name}”, so it wasn't saved again.`);
    return;
  }
  const name = (window.prompt("Name this terrain:", S.currentTerrainName || "") || "").trim();
  if (!name) return;   // cancelled or blank
  // Names must be unique (case-sensitive).
  if (findSavedByName(name) !== -1) {
    setStatus(`A saved terrain named “${name}” already exists.`);
    window.alert(`You already have a saved terrain named “${name}”. Please choose a different name.`);
    return;
  }
  terrain.name = name;
  if (!addSavedTerrain(terrain)) { setStatus("Couldn't save — browser storage is full or disabled."); return; }
  refreshRecordsStrip();
  S.currentTerrainName = name;
  S.currentTerrainUnsaved = false;
  updateCurrentTerrainBox();
  renderSavedTerrainsMenu();
  setStatus(`Saved terrain “${name}”.`);
};
// Fullscreen the game screen (canvas + toast). _setupHiDPI re-fits it on the change.
document.getElementById("fullscreen_btn").onclick = () => {
  if (document.fullscreenElement) { document.exitFullscreen(); return; }
  const frame = document.getElementById("stage_frame");
  if (frame.requestFullscreen) frame.requestFullscreen().catch(() => setStatus("Fullscreen isn't available here."));
};
document.addEventListener("fullscreenchange", () => {
  const fs = !!document.fullscreenElement;
  document.getElementById("fullscreen_btn").textContent = fs ? "⛶ Exit fullscreen" : "⛶ Fullscreen";
  _setupHiDPI();
  if (fs) showToast("Fullscreen — press Esc to exit");
  focusGame();
});
document.getElementById("pause").onclick = function() {
  S.paused = !S.paused;
  if (!S.paused) S.lastWallMs = 0;   // avoid huge dt burst on resume
  this.textContent = S.paused ? "Resume" : "Pause";
};
document.getElementById("speed").onchange = function() {
  S.simSpeed = parseFloat(this.value);   // fractional (0.25x/0.5x) as well as integer speeds
};
document.getElementById("mode").onchange = function() {
  S.mode = this.value;
  _bestofxPanelVisible(S.mode === "bestofx");
  _setupHiDPI();   // resize the canvas (hvh = 2× wide split screen; others = 1×)
  setStatus(`Building ${S.mode} mode...`);
  buildSimulation();
  setStatus(`Ready — ${modeLabel()}`);
  // Move keyboard focus OFF the dropdown so driving keys go to the game instead of
  // scrolling the <select>.
  this.blur();
  focusGame();
};

// Best of X
document.getElementById("bestofx_run").onclick   = () => { runBestOfX(); };
document.getElementById("bestofx_abort").onclick = () => { S.bestofxAbort = true; };
document.getElementById("bestofx_watch").onclick = () => { watchSelectedRun(); };

// Backtrack search
document.getElementById("backtrack_run").onclick = () => { runBacktrack(); };
document.getElementById("backtrack_abort").onclick = () => { S.backtrackAbort = true; };

// Cheats / bug probe
document.getElementById("bp_invince").onchange = function() {
  S.bpInvincible = this.checked;
  bpSetStatus(S.bpInvincible ? "Invincible ON — head-hit / fall-off / AI no-progress timeout won't kill any car."
                             : "Invincible OFF.");
};
document.getElementById("bp_zerog").onchange   = function() { bpSetZeroG(this.checked); };
document.getElementById("bp_altimeter").onchange = function() {
  S.bpAltimeter = this.checked;
  bpSetStatus(S.bpAltimeter ? "Altimeter ON — altitude above the fall-off line (a fixed level) shown on screen."
                            : "Altimeter OFF.");
};
document.getElementById("bp_speed").onchange = function() {
  S.bpSpeed = this.checked;
  bpSetStatus(S.bpSpeed ? "Speed meter ON — chassis velocity (m/s) shown on screen."
                        : "Speed meter OFF.");
};
document.getElementById("bp_distance").onchange = function() {
  S.bpDistance = this.checked;
  bpSetStatus(S.bpDistance ? "Distance ON — your CURRENT-position score shown under the score (drops if you roll back)."
                           : "Distance OFF.");
};
document.getElementById("bp_flight").onchange = function() {
  S.bpFlight = this.checked;
  if (S.bpFlight && S.bpRocket) {   // mutually exclusive — they share the same keys
    S.bpRocket = false; document.getElementById("bp_rocket").checked = false;
  }
  bpSetStatus(S.bpFlight
    ? `Flight mode ON — WASD/arrows fly at a constant speed (↑/W forward, ↓/S backward, ←/A & →/D rotate); release forward/back to stop dead in the air. Speed ${S.flightSpeed} m/s; scroll wheel to adjust (0–300). Tip: Invincible survives crashes.`
    : "Flight mode OFF.");
};
document.getElementById("bp_rocket").onchange = function() {
  S.bpRocket = this.checked;
  if (S.bpRocket && S.bpFlight) {   // mutually exclusive
    S.bpFlight = false; document.getElementById("bp_flight").checked = false;
  }
  bpSetStatus(S.bpRocket
    ? `Rocket mode ON — WASD/arrows thrust the car like a rocket (↑/W & ↓/S thrust, ←/A & →/D rotate). Thrust ${S.rocketAccel} m/s²; scroll wheel to adjust. Tip: turn on Invincible to survive crashes.`
    : "Rocket mode OFF.");
};
document.getElementById("bp_reverse").onchange = function() {
  S.bpReverse = this.checked;
  bpSetStatus(S.bpReverse
    ? "Reverse controls ON — every movement key is mirrored: left↔right while driving, and forward↔back / the two rotate keys in Flight and Rocket mode. Applies to both control sets (both players in Human-vs-Human); the AI drives itself, so it's unaffected."
    : "Reverse controls OFF.");
};
// Scroll wheel over the canvas adjusts whichever fly cheat is active: Flight speed
// (0–300) or Rocket thrust. passive:false so we can preventDefault the page scroll.
// (Shift+scroll is the SIM-speed control below — let it bubble up to that handler.)
document.getElementById("stage").addEventListener("wheel", e => {
  if (e.shiftKey) return;
  if (S.bpFlight) {
    e.preventDefault();
    const up = e.deltaY < 0;
    // Increments of FLIGHT_SPEED_STEP up to the break, FLIGHT_SPEED_STEP_HI past it.
    // Going up uses the band you're entering; going down the band you're leaving, so the
    // grid stays clean (…95, 100, 110, 120…) around the break.
    const step = up ? (S.flightSpeed >= FLIGHT_SPEED_STEP_BREAK ? FLIGHT_SPEED_STEP_HI : FLIGHT_SPEED_STEP)
                    : (S.flightSpeed >  FLIGHT_SPEED_STEP_BREAK ? FLIGHT_SPEED_STEP_HI : FLIGHT_SPEED_STEP);
    S.flightSpeed = Math.max(FLIGHT_SPEED_MIN, Math.min(FLIGHT_SPEED_MAX, S.flightSpeed + (up ? step : -step)));
    bpSetStatus(`Flight speed ${S.flightSpeed} m/s  (scroll up = faster, down = slower; ${FLIGHT_SPEED_MIN}–${FLIGHT_SPEED_MAX})`);
  } else if (S.bpRocket) {
    e.preventDefault();
    const d2 = (e.deltaY < 0 ? 1 : -1) * ROCKET_ACCEL_STEP;
    S.rocketAccel = Math.max(ROCKET_ACCEL_MIN, Math.min(ROCKET_ACCEL_MAX, S.rocketAccel + d2));
    bpSetStatus(`Rocket thrust ${S.rocketAccel} m/s²  (scroll up = faster, down = slower; ${ROCKET_ACCEL_MIN}–${ROCKET_ACCEL_MAX})`);
  }
}, { passive: false });
// Shift+Scroll (anywhere on the page) steps the SIM speed through the Speed
// dropdown's options (0.25x…8x), scroll up = faster. Drives the <select> (set +
// dispatch change) so the one onchange path owns S.simSpeed. Shift, not Alt: a
// wheel event isn't a key, so releasing Alt after Alt+Scroll focuses the browser
// menu (and Chrome ignores preventDefault on that). With Shift held, browsers
// report the wheel delta in deltaX.
window.addEventListener("wheel", e => {
  if (!e.shiftKey) return;
  e.preventDefault();
  focusGame();   // keep driving keys on the game, wherever the pointer was
  const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX;
  const sel = document.getElementById("speed");
  const idx = sel.selectedIndex + (delta < 0 ? 1 : -1);
  if (idx >= 0 && idx < sel.options.length && idx !== sel.selectedIndex) {
    sel.selectedIndex = idx;
    sel.dispatchEvent(new Event("change"));   // runs speed.onchange → S.simSpeed
  }
  setStatus(`Sim speed ${sel.options[sel.selectedIndex].textContent}  (Shift+scroll up = faster, down = slower)`);
}, { passive: false });
document.getElementById("bp_float").onclick    = bpFloatCar;
document.getElementById("bp_underworld").onclick = bpUnderworld;
document.getElementById("bp_stop").onclick = bpStop;
document.getElementById("bp_openexit").onclick = bpToggleExit;
// Teleport: open the panel, prefilling X/Y from the current car so it's a sane start.
document.getElementById("bp_teleport").onclick = () => {
  const cur = bpTeleportCurrent();
  if (cur) {
    document.getElementById("teleport_x").value = String(cur.score);
    document.getElementById("teleport_y").value = cur.altitude.toFixed(1);
  }
  document.getElementById("teleport_panel").style.display = "block";
};
document.getElementById("teleport_go").onclick = () => {
  const x = parseFloat(document.getElementById("teleport_x").value);
  const y = parseFloat(document.getElementById("teleport_y").value);
  if (isNaN(x) || isNaN(y)) { bpSetStatus("Teleport: enter a numeric score (X) and altitude (Y)."); return; }
  bpTeleport(x, y);
  document.getElementById("teleport_panel").style.display = "none";
  focusGame();
};
document.getElementById("teleport_close").onclick = () => {
  document.getElementById("teleport_panel").style.display = "none";
  focusGame();
};
document.getElementById("bp_flag").onclick     = bpFlag;
document.getElementById("bp_download").onclick = bpDownload;
// Physics playground: knob sections generated from tune.TUNE_SPEC.
buildTunePanel(document.getElementById("tune_root"), bpSetStatus);
const _presetBox = document.getElementById("tune_presets");
for (const pr of TUNE_PRESETS) {
  const btn = document.createElement("button");
  btn.textContent = pr.name;
  btn.onclick = () => setTune(pr.vals);
  _presetBox.appendChild(btn);
}
document.getElementById("tune_resetall").onclick = () => resetTune();
// Spin-investigation presets (debug only). Unmask: no angular damping + a very stiff,
// under-damped suspension — resonance-driven, so DRIVE over bumps to provoke it.
document.getElementById("bp_unmask").onclick = () =>
  setTune({ chassisAngDamp: 0, wheelAngDamp: 0, suspFreq: 200, suspDamp: 0.3 });
// Motor-spin: double the motor's target speed — floor it to provoke the sustained CCW spin.
document.getElementById("bp_motorspin").onclick = () => setTune({ motorSpeed: 2 });
initDevMode({ loadTerrain: loadTerrainObject });
initHumanRuns();
initRecords();

// Keybinds cheat-sheet overlay.
document.getElementById("keybinds_btn").onclick = () => {
  const pnl = document.getElementById("keybinds_panel");
  pnl.style.display = (pnl.style.display === "none") ? "block" : "none";
};
document.getElementById("keybinds_close").onclick = () => {
  document.getElementById("keybinds_panel").style.display = "none";
  focusGame();
};

// Keyboard + focus
window.addEventListener("keydown", e => { if (_handleModeKey(e)) return; _handleGameKey(e, true); _handleActionKey(e); });
window.addEventListener("keyup",   e => { _handleGameKey(e, false); });
document.getElementById("stage").addEventListener("mousedown", focusGame);

// Interacting with a button/checkbox/dropdown leaves keyboard focus ON that control:
// a focused button keeps a black ring, and a focused checkbox or <select> swallows
// every driving key (_handleGameKey ignores keys while a form field is focused — and a
// focused <select> would change its own value on arrow keys), so you can't drive. Two
// delegated listeners hand focus straight back to the game so every current AND future
// control is covered (superseding the per-handler blur() the mode/terrain menus already
// do). Number/text inputs are deliberately left alone so you can still type in them.
//  - buttons on `click` (a button has no `change` event)
//  - checkboxes and <select>s on `change`, NOT click: blurring a <select> mid-click
//    would slam the dropdown shut before you could pick an option.
document.addEventListener("click", e => {
  const t = e.target;
  if (t && t.tagName === "BUTTON") { t.blur(); focusGame(); }
});
document.addEventListener("change", e => {
  const t = e.target;
  if (t && (t.tagName === "SELECT" || (t.tagName === "INPUT" && t.type === "checkbox"))) {
    t.blur();
    focusGame();
  }
});

window.addEventListener("load", () => { init(); focusGame(); });
