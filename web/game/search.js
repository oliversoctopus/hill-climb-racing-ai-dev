// Test-time search over the frozen policy: Best of X (X jittered attempts on one
// map, replay the best) and the in-browser Go-Explore "save-scum" backtracking
// search (drive; on death rewind to a snapshot, perturb, retry; rewind deeper if a
// wall persists; commit cleared sections; stitch). Plus the ghost replay that plays
// back a recorded pose stream. Mirrors python/autorun/{best_of_k,backtrack_search}.py.
import { S, SCALE, SPAWN_X, FRAME_RATE, AI_COLOR } from "./state.js";
import {
  Car, Ground, Vec2, b2World, getSpawningY, setSpawningY,
} from "./bridge.js";
import {
  makeContactListener, makePlayer, buildWithGround, buildSimulation,
  makeSourceFromTrack, rollAcceptableGround, applyAction, _checkPlayerEndOfStep,
  capturePose, scorePx,
} from "./sim.js";
import { modeLabel } from "./modes.js";
import { syncGroundDims, tuneTick } from "./tune.js";
import { setStatus, _setupHiDPI } from "./main.js";

// ---- Best of X -----------------------------------------------------------
function _bestofxRank(i, n) {
  if (i === 0)     return "1st (best)";
  if (i === 1)     return "2nd";
  if (i === 2)     return "3rd";
  if (i === n - 1) return `${i + 1}th (worst)`;
  return `${i + 1}th`;
}

function _bestofxPopulateSelect() {
  const sel = document.getElementById("bestofx_select");
  sel.innerHTML = "";
  for (let i = 0; i < S.bestofxRuns.length; i++) {
    const r = S.bestofxRuns[i];
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${_bestofxRank(i, S.bestofxRuns.length)} — score ${r.score} (attempt #${r.attempt})`;
    sel.appendChild(opt);
  }
  document.getElementById("bestofx_results").style.display = "inline";
}

export async function runBestOfX() {
  let X = parseInt(document.getElementById("bestofx_n").value);
  if (!(X > 0)) X = 10;
  if (X > 200) X = 200;

  // UI: hide previous results, show abort, disable inputs that would race the headless
  // loop (mode change / reset would rebuild the world out from under us).
  document.getElementById("bestofx_results").style.display = "none";
  document.getElementById("bestofx_run").disabled = true;
  document.getElementById("bestofx_n").disabled = true;
  document.getElementById("mode").disabled = true;
  document.getElementById("reset").disabled = true;
  document.getElementById("bestofx_abort").style.display = "inline";
  S.bestofxAbort = false;
  S.bestofxRuns = [];

  // One canonical map for all X attempts.
  setStatus(`Best of ${X} — rolling map...`);
  const roll = rollAcceptableGround();
  S.storedGround = roll.ground;
  S.storedSpawningY = roll.spawningY;

  // A track counts as "complete" when an attempt reaches the LAST solid terrain vertex
  // (the launch lip / true end = distance - smoothness; score ~1883) — the same line as
  // beating the game. Once solved, further attempts are wasted, so stop early.
  const completePx = S.storedGround.distance - S.storedGround.smoothness;
  let solvedOn = 0;

  // No stochastic sampling — the agent stays argmax-greedy. Each attempt gets a tiny
  // sub-pixel spawn jitter; Box2D's chaotic dynamics amplify it into different runs.
  S.bestofxBusy = true;

  try {
    for (let i = 0; i < X; i++) {
      if (S.bestofxAbort) break;
      setStatus(`Best of ${X} — attempt ${i + 1}/${X}...`);
      document.getElementById("bestofx_status").textContent =
        `running ${i + 1}/${X}`;

      // ±1 px in each axis (≈ ±0.033 m). Below the eye-test threshold, above what Box2D
      // needs to diverge. Stored per-run so the same attempt replays deterministically.
      const dx = (Math.random() - 0.5) * 2.0;
      const dy = (Math.random() - 0.5) * 2.0;
      S.replayActions = null;
      buildWithGround(S.storedGround, S.storedSpawningY, dx, dy);
      const p = S.players[0];
      const actions = [];
      // Tight headless loop — no rendering. await yields the event loop each tick (ORT
      // Web's session.run is async); we also force a setTimeout yield every 200 ticks.
      while (!p.dead) {
        const act = await S.aiAgent.act({ car: p.car, ground: S.ground, scale: SCALE });
        actions.push(act);
        applyAction(p.car, act);
        tuneTick();
        S.world.Step(1.0 / FRAME_RATE, 10, 10);
        S.world.ClearForces();
        S.tickCount += 1;
        _checkPlayerEndOfStep(p);
        if (actions.length % 200 === 0) {
          await new Promise(r => { setTimeout(r, 0); });
          if (S.bestofxAbort) break;
        }
      }
      if (!p.dead) continue;   // aborted mid-run — skip the partial recording
      const distPx = Math.max(0, Math.round(p.maxDistPx - SPAWN_X));
      S.bestofxRuns.push({
        attempt: i + 1,
        distance: distPx,
        score: Math.floor(distPx / 10),
        actions,
        spawnDx: dx,
        spawnDy: dy,
      });
      if (p.maxDistPx >= completePx) { solvedOn = i + 1; break; }  // solved -> stop early
    }
  } finally {
    S.bestofxBusy = false;
    S.lastWallMs = 0;  // avoid a huge accumulator burst when RAF resumes
    document.getElementById("bestofx_run").disabled = false;
    document.getElementById("bestofx_n").disabled = false;
    document.getElementById("mode").disabled = false;
    document.getElementById("reset").disabled = false;
    document.getElementById("bestofx_abort").style.display = "none";
  }

  if (S.bestofxRuns.length === 0) {
    document.getElementById("bestofx_status").textContent = "aborted";
    setStatus("Best of X aborted.");
    return;
  }

  S.bestofxRuns.sort((a, b) => b.distance - a.distance);
  _bestofxPopulateSelect();

  const n = S.bestofxRuns.length;
  const best = S.bestofxRuns[0].score;
  const worst = S.bestofxRuns[n - 1].score;
  document.getElementById("bestofx_status").textContent =
    `done — ${n} runs (best ${best}, worst ${worst})${solvedOn ? ` — solved on attempt ${solvedOn}, stopped early` : ""}`;
  setStatus(`Best of ${n} complete — pick a run and click Watch`);

  // Show the best run by default so the user sees something immediately.
  watchSelectedRun();
}

export function watchSelectedRun() {
  const sel = document.getElementById("bestofx_select");
  let idx = parseInt(sel.value);
  if (!(idx >= 0 && idx < S.bestofxRuns.length)) idx = 0;
  const run = S.bestofxRuns[idx];
  // Fresh world + cloned canonical ground + same spawn jitter as the recording. Box2D
  // is deterministic, so identical spawn + identical action sequence reproduces the
  // recorded trajectory frame-accurate.
  buildWithGround(S.storedGround, S.storedSpawningY, run.spawnDx, run.spawnDy);
  S.replayActions = run.actions;
  S.replayIdx = 0;
  document.getElementById("bestofx_status").textContent =
    `watching ${_bestofxRank(idx, S.bestofxRuns.length)} — score ${run.score} (attempt #${run.attempt})`;
}

export function _bestofxPanelVisible(show) {
  document.getElementById("bestofx_panel").style.display = show ? "block" : "none";
  if (!show) {
    // Leaving Best of X mode — clear replay so the next mode runs live.
    S.replayActions = null;
    document.getElementById("bestofx_results").style.display = "none";
    document.getElementById("bestofx_status").textContent = "";
  }
}

// ---- Ghost replay --------------------------------------------------------
// Play back a recorded per-tick pose stream (no live physics) so the user can watch a
// stitched save-scum run over its terrain.
export function watchGhost(track) {
  if (!track.poses) { setStatus("no run to replay"); return; }
  S.loadedTrack = track;
  buildWithGround(makeSourceFromTrack(track), track.spawning_y, 0, 0);  // build the terrain
  S.players = [];                     // no live car — the ghost is the show
  S.ghostPoses = track.poses;
  S.ghostDims  = track.dims || { chassis_w:125, chassis_h:40, wheel_r:17, torso_w:15, torso_h:30, head_r:15 };
  S.ghostScore = track.beat_score || 0;
  S.ghostBeaten = (track.beaten !== false);   // exported replays are genuine beats; best-run ghosts pass beaten:false
  S.ghostIdx = -1; S.ghostDone = false;
  S.paused = false; S.lastWallMs = 0; S.accumSec = 0;
  document.getElementById("pause").textContent = "Pause";
  setStatus(`${(S.ghostBeaten ? "▶ Watching the AI beat " : "▶ Watching the AI's best run on ") +
          (track.name || "this terrain")} (${S.ghostPoses.length} frames)`);
}

// ---- Save-scum backtracking search --------------------------------------
// Restore = rebuild the car (fresh bodies, baked joints) + teleport to the saved
// pose/velocity (re-satisfies the joints and clears the impulse cache the SAME way
// every time) — the Python "reset" path, so the ghost replay reproduces the run exactly.
function saveCarState(car) {
  const bs = car.bodies(), arr = [];
  for (let i = 0; i < bs.length; i++) {
    const b = bs[i], p = b.GetPosition(), v = b.GetLinearVelocity();
    arr.push([p.x, p.y, b.GetAngle(), v.x, v.y, b.GetAngularVelocity()]);
  }
  return { bodies: arr, og0: car.wheels[0].onGround === true,
           og1: car.wheels[1].onGround === true, motorState: car.motorState };
}
// Rebuild the search car fresh (destroy old joints+bodies, new Car at spawn) — the
// constructor re-bakes joint anchors at spawn, so teleporting each body to the saved
// pose re-satisfies every joint. Mirrors js_backend resetCar().
function rebuildSearchCar(p) {
  p.car.destroy(S.world);
  const dummy = { shirtColorR: AI_COLOR.shirtR, shirtColorG: AI_COLOR.shirtG,
                shirtColorB: AI_COLOR.shirtB, dead: false, kindaDead: false };
  p.car = new Car(SPAWN_X, getSpawningY(), S.world, dummy);
}
function restoreCarState(p, snap) {
  rebuildSearchCar(p);                   // fresh car (impulse cache cleared consistently)
  const bs = p.car.bodies();
  for (let i = 0; i < bs.length; i++) {
    const r = snap.bodies[i], b = bs[i];
    b.SetPositionAndAngle(new Vec2(r[0], r[1]), r[2]);
    b.SetLinearVelocity(new Vec2(r[3], r[4]));
    b.SetAngularVelocity(r[5]); b.SetAwake(true);
  }
  p.car.wheels[0].onGround = snap.og0;
  p.car.wheels[1].onGround = snap.og1;
  if (snap.motorState !== undefined) p.car.motorState = snap.motorState;
  p.car.player.kindaDead = false;
}
// Build a dedicated search world (clone of the given terrain) with ONE AI car.
function buildSearchWorld(srcGround, sY) {
  S.worldGen += 1;
  S.world = new b2World(new Vec2(0, 10), false);
  S.listener = makeContactListener(S.world);
  setSpawningY(sY);
  S.ground = new Ground(S.world);
  S.ground.cloneFrom(srcGround);
  syncGroundDims(S.ground, srcGround);
  S.ground.setBodies(S.world);
  const p = makePlayer(S.aiAgent, AI_COLOR);
  S.players = [p];
  S.tickCount = 0; S.cameraPanX = 0; S.cameraPanY = 0;
  return p;
}
// One forward rollout from the search car's CURRENT state (burst actions first, then
// the AI policy). Records actions + periodic snapshots; yields to the UI.
async function btRoll(p, startAidx, burst, opts) {
  const actions = [];
  const snaps = [];
  let maxX = p.maxDistPx;
  let beaten = false;
  let t = 0;
  while (true) {
    if (t % opts.snapEvery === 0) {
      snaps.push({ aidx: startAidx + actions.length, car: saveCarState(p.car),
                   agent: S.aiAgent.snapshotState(), maxDistPx: p.maxDistPx,
                   stuckCount: p.stuckCount });
    }
    const act = (t < burst.length) ? burst[t]
            : await S.aiAgent.act({ car: p.car, ground: S.ground, scale: SCALE });
    applyAction(p.car, act);
    tuneTick();
    S.world.Step(1.0 / FRAME_RATE, 10, 10);
    S.world.ClearForces();
    S.tickCount += 1; actions.push(act); t += 1; opts.ticks.n += 1;
    _checkPlayerEndOfStep(p);
    maxX = p.maxDistPx;
    if (maxX >= opts.beatPx) beaten = true;
    if (p.dead)                  return { actions, snaps, maxX, status: beaten ? "complete" : "dead",   n: t };
    if (t >= opts.branchMaxTicks) return { actions, snaps, maxX, status: beaten ? "complete" : "trunc",  n: t };
    if (opts.ticks.n >= opts.budget) return { actions, snaps, maxX, status: beaten ? "complete" : "budget", n: t };
    if (t % 256 === 0) {
      await new Promise(r => { setTimeout(r, 0); });
      if (S.backtrackAbort) return { actions, snaps, maxX, status: "abort", n: t };
      document.getElementById("backtrack_status").textContent =
        `searching… tries ${opts.prog.tries}, deepest rewind ${opts.prog.maxDepth}, reached score ${scorePx(maxX)} (tick ${opts.ticks.n}/${opts.budget})`;
    }
  }
}
function commitSegments(segments, seam, bActions) {
  const start = seam.aidx;
  let base = 0;
  const out = [];
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i], L = seg.actions.length;
    if (start >= base + L) { out.push(seg); base += L; }
    else { if (start - base > 0) out.push({ start: seg.start, actions: seg.actions.slice(0, start - base) }); break; }
  }
  out.push({ start: seam, actions: bActions.slice() });
  return out;
}
function restoreSearch(p, snap) {
  restoreCarState(p, snap.car);
  S.aiAgent.restoreState(snap.agent);
  p.maxDistPx = snap.maxDistPx; p.stuckCount = snap.stuckCount; p.dead = false;
}
async function jsBacktrackSolve(p, opts) {
  opts.ticks = { n: 0 }; opts.prog = { tries: 1, maxDepth: 0 };
  const r = await btRoll(p, 0, [], opts);
  let segments = [{ start: r.snaps[0], actions: r.actions }];
  let tries = 1, backtracks = 0, bottlenecks = 0, maxDepth = 0;
  // Track the FURTHEST run ever seen (even attempts that died without clearing a wall),
  // not just the committed bottleneck — so a non-beaten search still shows its deepest
  // attempt as the "best run", not the last committed section.
  let bestMaxX = r.maxX, bestSegments = segments;
  function out(o) { o.tries = tries; o.backtracks = backtracks; o.bottlenecks = bottlenecks;
                    o.maxDepth = maxDepth; o.ticks = opts.ticks.n; return o; }
  if (r.status === "abort")    return out({ solved: false, reason: "abort", maxX: r.maxX, segments: null });
  if (r.status === "complete") return out({ solved: true, reason: "single-shot", maxX: r.maxX, segments });
  let committed = r.actions, csnaps = r.snaps, bottleneck = r.maxX, depth = opts.initDepth;
  while (opts.ticks.n < opts.budget) {
    if (S.backtrackAbort)      return out({ solved: false, reason: "abort", maxX: bottleneck, segments: null });
    if (depth > csnaps.length) return out({ solved: false, reason: "exhausted", maxX: bestMaxX, segments: bestSegments });
    const seam = csnaps[csnaps.length - depth];
    if (depth > maxDepth) maxDepth = depth;
    opts.prog.maxDepth = maxDepth;
    let cleared = false;
    for (let a = 0; a < opts.attempts; a++) {
      if (opts.ticks.n >= opts.budget || S.backtrackAbort) break;
      restoreSearch(p, seam);
      const bl = opts.burstMin + Math.floor(Math.random() * (opts.burstMax - opts.burstMin + 1));
      const burst = [];
      for (let k = 0; k < bl; k++) burst.push(Math.floor(Math.random() * 3));
      const b = await btRoll(p, seam.aidx, burst, opts);
      tries += 1; opts.prog.tries = tries;
      if (b.status === "abort") return out({ solved: false, reason: "abort", maxX: bottleneck, segments: null });
      // Remember this attempt if it's the deepest yet (stitch it onto the run so far).
      if (b.maxX > bestMaxX) { bestMaxX = b.maxX; bestSegments = commitSegments(segments, seam, b.actions); }
      if (b.status === "complete") {
        segments = commitSegments(segments, seam, b.actions);
        bottlenecks += 1;
        return out({ solved: true, reason: "backtrack", maxX: b.maxX, segments });
      }
      if (b.maxX >= bottleneck + opts.margin) {     // cleared this wall, died later
        committed = committed.slice(0, seam.aidx).concat(b.actions);
        csnaps = csnaps.filter(s => s.aidx < seam.aidx).concat(b.snaps);
        segments = commitSegments(segments, seam, b.actions);
        bottleneck = b.maxX; bottlenecks += 1; depth = opts.initDepth; cleared = true;
        break;
      }
    }
    if (!cleared) { depth += 1; backtracks += 1; }   // iterative deepening
  }
  return out({ solved: false, reason: "budget", maxX: bestMaxX, segments: bestSegments });
}
// Replay the committed segments (rebuild+teleport at each seam, play recorded actions)
// capturing a per-tick pose stream — exact reproduction of the run.
function jsReplaySegments(p, segments) {
  const poses = [];
  let dims = null;
  for (let si = 0; si < segments.length; si++) {
    const seg = segments[si];
    restoreCarState(p, seg.start.car);
    for (let ai = 0; ai < seg.actions.length; ai++) {
      applyAction(p.car, seg.actions[ai]);
      tuneTick();
      S.world.Step(1.0 / FRAME_RATE, 10, 10); S.world.ClearForces();
      if (!dims) dims = { chassis_w: p.car.chassisWidth, chassis_h: p.car.chassisHeight,
                          wheel_r: p.car.wheels[0].radius, torso_w: p.car.person.torso.width,
                          torso_h: p.car.person.torso.height, head_r: p.car.person.head.radius };
      poses.push(capturePose(p.car));
    }
  }
  return { poses, dims };
}
function _btUI(running) {
  document.getElementById("backtrack_run").disabled = running;
  document.getElementById("backtrack_abort").style.display = running ? "inline" : "none";
  document.getElementById("mode").disabled = running;
  document.getElementById("reset").disabled = running;
  document.getElementById("reset_pos").disabled = running;
  document.getElementById("bestofx_run").disabled = running;
}
export async function runBacktrack() {
  if (!S.aiAgent) return;
  // Backtrack search drives a single AI car; running it from Human-vs-Human's two-car
  // split-screen world causes camera/render bugs. Force AI-only first, reusing the
  // CURRENT terrain so we still search the exact map that was on screen.
  if (S.mode === "hvh") {
    const keepGround = { vectors: S.ground.vectors.map(v => new Vec2(v.x, v.y)),
                       grassPositions: S.ground.grassPositions.slice() };
    S.mode = "ai";
    const modeSel = document.getElementById("mode");
    if (modeSel) modeSel.value = "ai";
    _bestofxPanelVisible(false);
    _setupHiDPI();                              // shrink the 2×-wide split canvas back to 1×
    buildWithGround(keepGround, getSpawningY(), 0, 0);
  }
  // Snapshot the CURRENT terrain (clone vectors; keep a px copy for loadedTrack reuse).
  const srcGround = { vectors: S.ground.vectors.map(v => new Vec2(v.x, v.y)),
                    grassPositions: S.ground.grassPositions.slice() };
  const sY = getSpawningY();
  const pxVerts = S.ground.vectors.map(v => [v.x * SCALE, v.y * SCALE]);
  const budget = parseInt(document.getElementById("backtrack_budget").value) || 120000;

  S.backtrackAbort = false; S.bestofxBusy = true; _btUI(true);
  S.ghostPoses = null; S.ghostDone = false;
  document.getElementById("backtrack_replaying").style.display = "none";
  setStatus("Backtracking on this terrain — searching for a run that beats the game…");
  document.getElementById("backtrack_status").textContent = "starting…";

  const p = buildSearchWorld(srcGround, sY);
  const opts = { snapEvery: 20, attempts: 8, margin: 400, budget, branchMaxTicks: 5000,
               burstMin: 2, burstMax: 8, initDepth: 2, beatPx: S.ground.distance - S.ground.smoothness };
  let res;
  try { res = await jsBacktrackSolve(p, opts); }
  catch (e) {
    res = { solved: false, reason: `error: ${e.message}`, tries: 0, backtracks: 0,
            bottlenecks: 0, maxDepth: 0, maxX: 0, segments: null };
  }
  _btUI(false); S.bestofxBusy = false; S.lastWallMs = 0;

  const depthSec = (res.maxDepth * opts.snapEvery / FRAME_RATE).toFixed(1);
  if (res.solved && res.segments) {
    const rep = jsReplaySegments(p, res.segments);      // sync, atomic w.r.t. the RAF loop
    const score = scorePx(res.maxX);
    S.loadedTrack = { vertices: pxVerts, spawning_y: sY, poses: rep.poses, dims: rep.dims,
                      beat_score: score, name: "this random terrain (beaten)" };
    document.getElementById("backtrack_status").textContent =
      `✓ BEAT in ${res.tries} tries, ${res.backtracks} backtracks (deepest rewind ${res.maxDepth} snaps ≈ ${depthSec}s; ${res.bottlenecks} bottleneck${res.bottlenecks === 1 ? "" : "s"}) — score ${score} in ${res.ticks} ticks. Replaying…`;
    watchGhost(S.loadedTrack);
  } else if (res.segments) {
    // Didn't beat the game, but the search made real progress — replay the AI's BEST
    // (deepest committed) stitched run as a ghost instead of just resetting.
    const rep2 = jsReplaySegments(p, res.segments);
    const reached = scorePx(res.maxX);
    S.loadedTrack = { vertices: pxVerts, spawning_y: sY, poses: rep2.poses, dims: rep2.dims,
                      beat_score: reached, beaten: false,
                      name: "this random terrain (AI best run — not beaten)" };
    document.getElementById("backtrack_status").textContent =
      `did NOT beat (${res.reason}) after ${res.tries} tries, ${res.backtracks} backtracks; best reached score ${reached}${res.reason === "budget" ? " — raise the tick budget and retry" : ""} — replaying the AI's best run…`;
    watchGhost(S.loadedTrack);
  } else {
    // No replayable run (user aborted, or an error) — keep the terrain loaded to retry.
    S.loadedTrack = { vertices: pxVerts, spawning_y: sY, name: "this random terrain" };
    buildSimulation();
    const reached3 = scorePx(res.maxX);
    document.getElementById("backtrack_status").textContent =
      `${res.reason === "abort" ? "aborted" : `did NOT beat (${res.reason})`} after ${res.tries} tries, ${res.backtracks} backtracks; deepest reached score ${reached3}${res.reason === "budget" ? " — raise the tick budget and retry" : ""}`;
    setStatus(`Ready — ${modeLabel()}`);
  }
}
