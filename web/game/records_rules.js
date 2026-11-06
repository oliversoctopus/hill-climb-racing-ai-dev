// Which runs count as attempts on a map, and which maps are notable enough to keep for
// good (the rest expire KEEP_DAYS after their last attempt). Pure (no imports), so the
// same rules can be evaluated against a copy of the stored data.

export const ATTEMPT_SEC = 3;        // a shorter run is an abandon, not an attempt
export const ATTEMPT_SCORE = 100;    // a clean run scoring less is an abandon too
export const NEAR_FINISH = 1700;     // an "almost finished" clean run
export const KEEP_DAYS = 7;
export const CHEAT_ATTEMPTS = 3;     // cheated attempts that make a map notable

// An unfinished map: enough attempts at a high enough best.
export function ladder(n, max) {
  return (n >= 3 && max >= 1500) || (n >= 4 && max >= 1000) || (n >= 6 && max >= 700) || n >= 10;
}
// A finished map: a fastest-quarter time, or repeated near-finishes.
export function finishNotable(n1700) { return n1700 >= 3; }
// The slowest time still in the fastest quarter of `times` (null if empty).
export function fastCutoff(times) {
  if (!times.length) return null;
  const s = times.slice().sort((a, b) => a - b);
  return s[Math.ceil(s.length * 0.25) - 1];
}

// An unfinished map with no recorded runs is assumed tried once; this best still keeps it.
export const LEGACY_KEEP_SCORE = 1600;
// One-time judgement of maps from before attempts were counted, with real clean attempt
// counts from the human-run recorder where it has runs. Returns key → { clean, cheat, att }.
export function classifyLegacy(maps, runs, frameRate) {
  const hr = {};
  for (const u of runs) {
    const h = hr[u.map] || (hr[u.map] = { n: 0, max: 0, n1700: 0 });
    if (u.ticks < ATTEMPT_SEC * frameRate || u.score < ATTEMPT_SCORE || u.sim_speed_min < 1) continue;
    h.n += 1; h.max = Math.max(h.max, u.score);
    if (u.score >= NEAR_FINISH) h.n1700 += 1;
  }
  const byId = maps.slice().sort((a, b) => a.id - b.id);
  const cut = fastCutoff(byId.filter(m => m.bestTime != null).map(m => m.bestTime));
  // Bests at the time each map appeared (ids are in first-record order), plus today's holders.
  let runClean = 0, runAll = 0;
  const top = { s: null, t: null, as: null, at: null };
  for (const m of byId) {
    if (m.bestScore > 0 && (!top.s || m.bestScore > top.s.bestScore)) top.s = m;
    if (m.bestTime != null && (!top.t || m.bestTime < top.t.bestTime)) top.t = m;
    if (m.all.score > 0 && (!top.as || m.all.score > top.as.all.score)) top.as = m;
    if (m.all.time != null && (!top.at || m.all.time < top.at.all.time)) top.at = m;
  }
  const out = {};
  for (const m of byId) {
    const clean = m.bestScore > 0 || m.bestTime != null, fin = m.bestTime != null, h = hr[m.key];
    const cleanWalk = m.bestScore > runClean, allWalk = m.all.score > runAll;
    runClean = Math.max(runClean, m.bestScore); runAll = Math.max(runAll, m.all.score);
    let c = null, x = null;
    if (m === top.s || m === top.t) c = "all-maps best";
    else if (fin && m.bestTime <= cut) c = "fastest-quarter finish";
    else if (clean && cleanWalk) c = "all-maps best when set";
    else if (fin && h && finishNotable(h.n1700)) c = `finished, ${h.n1700} runs of ${NEAR_FINISH}+`;
    else if (!fin && h && ladder(h.n, h.max)) c = `${h.n} attempts, best ${h.max}`;
    else if (!fin && !h && m.bestScore >= LEGACY_KEEP_SCORE) c = `best ${m.bestScore}, before attempts were counted`;
    if ((m === top.as && m.all.scoreCheated) || (m === top.at && m.all.timeCheated)) x = "all-maps best incl. cheats";
    else if (!clean && allWalk) x = "all-maps best incl. cheats when set";
    const att = h ? { clean: h.n, max: h.max, n1700: h.n1700 }
                  : { clean: m.bestScore >= ATTEMPT_SCORE ? 1 : 0, max: m.bestScore, n1700: m.bestScore >= NEAR_FINISH ? 1 : 0 };
    out[m.key] = { clean: c, cheat: x, att: { ...att, cheat: clean ? 0 : 1, slow: 0, slowMax: 0 } };
  }
  return out;
}
