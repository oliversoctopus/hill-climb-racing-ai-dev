# Hill Climb Racing AI — handoff document

Detailed handoff + experiment log. For day-to-day orientation see `CLAUDE.md`; for coding conventions see `CONVENTIONS.md`.

**How to read this file:** everything below the glossary is a *reverse-chronological experiment log* (newest first). For a plain-English overview jump to **TL;DR** (below the log); for what the score numbers mean, the **Score landmarks & ceilings** glossary is next.

## Score landmarks & ceilings (glossary)

The docs use several distances/scores that are easy to conflate. This is the canonical key (CONVENTIONS *Domain landmark constants*). Score = `(max_dist_px − SPAWN_X)/10`, uncapped; `GROUND_DISTANCE`=19200px.

**Completion** = reaching the **last solid terrain vertex** (the launch lip / true end). Single-sourced as `COMPLETE_PX = GROUND_DISTANCE − GROUND_SMOOTHNESS` in `constants.py` (and `storedGround.distance − smoothness` in the browser). Every completion check uses it.

| landmark | px | ≈ score | meaning |
|---|---|---|---|
| **`COMPLETE_PX`** (completion) | **19,185** (`GROUND_DISTANCE − GROUND_SMOOTHNESS`) | **~1883** | **the true end — reaching the last solid vertex (the launch lip).** This is "completion." |
| real fly-off | — | **~1900–1962** | beating the game = reach the lip and fly off into the void (a bit past completion; measured) |
| ~~soft line~~ (RETIRED) | 18,250 (`−950`) | ~~1790~~ | the OLD "completion" (best_of_k/eval/jitter_probe) — ~935 px short; **wrong**, fixed 2026-07-07 |
| ~~`END_PX`~~ (RETIRED) | 18,850 (`−350`) | ~~1850~~ | the old "~1850 cap" — also short of the true end |

**Mean-score ceilings** (different eval protocols, NOT interchangeable): **~1350** = base_a on the 200-ep seed-42 protocol; **~1410** = on the 120 pinned-track set (the gap is protocol, not a better model).

**Best-of-X completion ceilings** (per MODEL): **70%** = base_a; **82.5%** = the deployed seed2_resume model (K=30). ⚠️ These were measured against the **OLD** soft line (score 1790); under the corrected last-vertex definition (~1883) they will be **lower** and need re-measuring. Do NOT compare old %s to numbers produced after 2026-07-07.

---

## 2026-11-06 — Project moved to one repo with a deploy remote

The root repo now tracks `web/` through `git subtree`, with `web/`'s 79 commits imported, so one clone has everything. Vercel still deploys from the existing `web/` repo. `git subtree split --prefix=web` reproduced that repo's head hash exactly, so subtree pushes are fast-forwards. A commit that touches no `web/` file produces nothing to push.

The history was rewritten before publishing. The 2026-09-30 DevTools trace is gone because a trace of a personal Chrome profile records other tabs and installed extensions, and its findings are in that entry. The same entry's description of the machines tried was reworded.

License: Code Bullet's Hill-Climb-Racing-AI repo has no license. GitHub reports none, and its 41 files include no license file, its README is only a title, and its game code has no license text. The repo's MIT license therefore excludes that material (`NOTICE.md`).

## 2026-10-25 — Record maps: storage quota, notability and expiry

Report: after 332 record maps the game said "no record on this map" on every new map. Cause: every map with any score became a record map and stored its terrain in localStorage (about 14 KB each). localStorage held 5,242,837 of Chrome's 5,242,880 characters, and `_save` swallowed the quota error, so new records were silently dropped.

Fix (`web/game/records.js`, rules in `web/game/records_rules.js`):

- Terrains moved to IndexedDB (`hcr_records` → `terrains`); the small records blob stays in localStorage. Failed writes now show in the status line. The first load after the change backs up both old localStorage blobs to `hcr_records` → `backup` under `v1`.
- Attempts are counted per map. A clean attempt lasts at least 3 s and scores at least 100; a cheated attempt lasts at least 3 s. Slow-mo-only runs are cheated attempts and are also counted on their own.
- A map is kept for good (listed, given an id) when it is notable: a clean finish in the fastest quarter of all clean finish times, or a finish plus three runs of 1700+; for an unfinished map, 3 attempts with a best of 1500+, 4 with 1000+, 6 with 700+, or 10 at any score; holding an all-maps best; 3 cheated attempts, or the slow-mo ladder, or the incl.-cheats all-maps best (cheat notability, hidden with cheat records); or a 📌 pin. Notability is sticky. The finish-time pool keeps every map's clean best even after the map expires.
- Other maps are unlisted ("Show all" reveals them) and expire 7 days after their last attempt, unless Saved or loaded.
- Existing maps were judged once by `classifyLegacy`: the rules above with real clean attempt counts from the human-run recorder where it had runs (224 of 332 maps; it skips physics-cheat runs, so its counts can only undercount), a 1600+ best keeping unfinished maps without recorded runs, no fallback for slow finishes, and a running max over ids standing in for "an all-maps best when it was set". Dry run on the live data: 92 kept, 240 unlisted (142 of them slow finishes), which start their 7-day clock on the first load after deploy.
- The 49 newest maps (16 of them kept) had no stored terrain, because they were set after the quota filled. Their terrains were recovered once, by hand in the browser, from the human-run recorder's `maps` store: all 49 were there and every one hashed to its record's key. The recorder doesn't keep grass, so their grass layout was regenerated with `Ground.randomizeGround()`'s rule (cosmetic only).

## 2026-09-30 — Browser stutters come from Chrome extensions

Report: during human play the page freezes for 0.1–0.25 s every minute or so, on every machine and Chrome profile tried. **In an Incognito window (no extensions) the freezes went away** over 3 min of play. No code change.

A DevTools Performance trace of the live site (107 s of human play, personal profile; not kept) located each freeze:

| time | on screen | cause |
|---|---|---|
| 103.2–103.4 s | ~14 dropped frames, ~220–250 ms | BlockSite extension (`eiimnmioipafcokbfikbljfdeojpcgbh`) injecting `content.js` into the page twice: 123 ms + 115 ms on the main thread, in an isolated world |
| 89.6 s | ~107 ms | restart (R/T): 64 ms key handler + 42 ms first frame; harmless, a new map takes longer to react to |
| 67.1–67.3 s | 2 late frames (34, 36 ms) | memory-reducing major GC (19 ms) then 5 ms CppGC (Blink heap) sweep tasks |

Mitigation in `web/game/main.js`: a frame gap over 100 ms counts as a stall, and the loop resumes from where the screen froze instead of catching up. Before, it ran up to 100 ms of physics in one frame after a freeze (a visible lurch, and physics the player never saw); a side-by-side test with a faked 200 ms main-thread block felt much better without catch-up. Run times count ticks, so records are unaffected.

Rejected: running the game in a Web Worker on an `OffscreenCanvas`. A test page confirmed the worker keeps drawing smoothly through a 200 ms main-thread block, but keyboard events only reach the main thread, so input pressed during the block arrives up to 200 ms late while the car keeps moving. In a side-by-side throttle-balancing test the user preferred the pause: more visible, but it never acts on stale input.

What triggers BlockSite's re-injection is unknown. The page changes no title, URL or favicon; 0.2 s before it the browser flushed the back/forward cache for every tab, so the trigger is probably browser-wide.

What the earlier in-page loggers showed, and why they missed it: per frame, each flagged hitch looked like one late frame (44–47 ms) and nothing worse. They time frames up to the hand-off to the browser and cannot see extension scripts or compositor drops, so they undercounted. Also ruled out in-page: saved data and dev mode (60 fps for 3 min with the user's data), live vs local code (identical apart from line endings), and resolution (2087×1173 and 1043×587 both gave ~2 late frames per minute).

Open, optional: the CppGC sweeps are partly fed by canvas objects the render code creates every frame (sky and sun gradients, dirt pattern, `DOMMatrix`, depth gradient) and by per-tick DOM text writes. Caching them would shrink the small GC hitches; it does not touch the extension freezes.

Method notes: a DevTools Performance trace is the tool here; per-frame `PipelineReporter` states give dropped frames, and `EvaluateScript` with `contextType: isolated` marks extension scripts. Chrome stops rAF in an occluded window, LoAF only reports frames ≥ 50 ms, and `await import('/game/state.js')` in the console returns the live `S`.

## 2026-09-29 — Human-run recorder; browser and `js_backend.py` are not bit-identical

`web/game/humanruns.js` (dev mode) records each clean human run: per tick, the chassis state (x, y, angle, angular velocity, vx, vy) and wheel contacts before the action, plus the action and the exact terrain. Physics-changing cheats, quick-load and frame-step drop a run; slow-mo does not. Verified: obs rebuilt with `env._build_obs` from a 5000-tick recording equal the deployed agent's in-browser obs on every tick (max diff 0).

Replaying the recorded actions through `js_backend.py` does not reproduce the run. Two sources, measured on the same 5000-tick recording (max abs diff over x, y, angle and velocities, SI units):

| tick | `js_backend.py` as is | ground edges in browser order |
|---|---|---|
| 1–10 | 0 | 0 |
| 11 | 1.8e-15 | 1.8e-15 |
| 30 | 0.79 | 1.7e-13 |
| 300 | 78 | 1.1 |
| 600 | 190 | 61 |

- Edge order: `Ground.setBodies` creates every dirt edge, then every grass edge; `js_backend._buildGroundBodies` interleaves them per segment. Fixture order changes contact order, and the solver rounds differently.
- A second difference, source not found, appears at tick 11 under both orders and grows chaotically.

Both are rounding-level; the physics is the same, so policy performance should not move. What is lost is exact reproduction of a browser run in Python beyond a few seconds, so imitation data must come from the recorded state, not from a replay.

## 2026-09-29 — Browser-only Physics playground

`web/game/tune.js` (Tools drawer) exposes ~45 knobs: gravity, densities, friction, motor, suspension, driver, sizes, rules, terrain. Size knobs work via construction wrappers in `index.html`'s shim (Car accessors + `Wheel`/`Person`/`Car` subclass rebinding); the physics files are untouched and training never loads the shim. Every hook is gated on "knob modified", so at stock the browser sim is bit-identical to before (verified: terrain
+ 900-tick drive, 3 seeds). Trap found on the way: `Box2d.js` polyfills `Object.defineProperty` with get/set only; it ignores `value`.

## 2026-07-17 — Physics classes syntax-modernized

CONVENTIONS.md was written during the 2026-07-07 understandability refactor (Tiers 0–4), which split `web/game/` into ES modules and then modernized it with AST-based `lebab` (`var`→`const`/`let`, `this`-safe arrows, template literals) in a separate commit. On 2026-07-17 the physics classes `web/{Car,Wheel,Person,Ground}.js` got the same pass (plus no-op `this.field;` statements removed, `;;` cleaned, `Car.destroy` `&&`-guard → `?.`). A cleanup sweep followed: `ai_policy.js` (never lebab'd before), the sibling-loop `var`s lebab had left (safe: none captured in a closure), and the `obj-shorthand` / `obj-method` / remaining `template` transforms. `node --check` passes on all 16 non-vendored files. Loose equality (`==`/`!=`) left as is: `x != null` is the null-and-undefined idiom. Verified each round: obs bit-exact (`max|py-js|=0`), `game/` import harness, deterministic eval unchanged (1495). `cb_reference/` now diverges cosmetically as well as behaviorally (the joint limit below).

## 2026-07-07 — Driver ragdoll joint limits (browser-play fix, AI wash)

Fixed the long-standing "head flips 180° below the car on a very strong impact and dies unrecoverably" bug. Root cause: the driver's revolute joints had **no angular limits** (verified: the game never calls `EnableLimit`/`SetLimits`; the upright pose was held only by soft distance-joint springs). A distance joint constrains only the *distance* between anchors, not which side, so "driver above" and "driver hanging 180° below" are two stable equilibria of the same spring system; a hard enough impact (rocket mode) kicks it over the barrier into the lower well, where the head then drags on the ground → `killViaHead` death, and no restoring torque exists to climb back out (invincible mode only skips the death, doesn't right the ragdoll).

Fix (final): an **asymmetric** angular limit on the **torso↔chassis** revolute joint only (`web/Car.js`): `lowerAngle=−70.6°`, `upperAngle=+104.5°`. The head↔torso (neck) joint is left UNLIMITED; it doesn't exhibit the flip in practice. Physics is therefore **no longer byte-identical to `cb_reference/`** (Code Bullet's original).

How the angles were calculated (separatrix measurement):
- Mapped the driver's basin of attraction by pinning the chassis static + airborne (pure gravity+spring regime, no ground/head contact), disabling the limit, and releasing the ragdoll from rest rotated to a sweep of angles about the chassis pivot (`diagnostics`-style probe; scripts in scratch).
- The upright well sits at **rel ≈ −19.7°** (torso-minus-chassis angle; the distance-joint anchor is offset toward the front, so rest hangs tilted forward).
- The basin is **asymmetric**: bisected flip edges are **rel = +71.6° (torso tipping FORWARD, head toward +x)** and **rel = −105.5° (tipping BACK)**. Past either, the ragdoll falls into the 180° head-down well (rel ≈ +164°). (Measured from rest it's ~+91°/−86°, nearly symmetric; the lopsidedness comes from the −19.7° rest offset.)
- The limit is on `jointAngle = −rel` (`rel ∈ [−upperAngle, −lowerAngle]`), so the forward edge maps to `lowerAngle = −71.6°` and the back edge to `upperAngle = +105.5°`.
- **Chosen margin: 1° inside each edge** → `lowerAngle = −70.6°`, `upperAngle = +104.5°`.
- A limit MUST sit inside the basin, else the ragdoll rests against the wall in the flip basin, which was the first-cut symmetric ±90° bug (place-at-wall check: L=72° sticks, L=71° reverts). The abandoned symmetric ±70° was correct on the forward side but needlessly choked ~35° of legitimate backward lean.
- Confirmed with the file-baked asymmetric values: shoving the ragdoll 140° past the wall reverts to upright rest (−19.6°) in BOTH directions.
- (Note: on FLAT ground with a resting dynamic chassis even ±90° reverts under kicks; the flip only manifests in violent/airborne whole-car dynamics, which is why the hard basin-inside limit is the right guarantee.)
- Corroboration (2026-07-07): a closed-form rigid-body statics model (torso pendulum + soft distance-spring `k=m(2πf)²`=0.987 N/m + rigidly-slaved head, from raw `Car.js` geometry: torso CoM 15px / spring anchors A=20px,B=(62.5,−20)px, L0=68.75px / head 45px from the pivot; m_torso=1.0e−3, m_head=7.85e−4 kg, g=10) reproduces the measured edges to ~1°. Full model vs solver: rest −18.98° vs −19.68°; forward edge +71.01° vs +71.65°; back edge −104.46° vs −105.63°; asymmetry (fwd−back displacement from rest) +4.50° vs +5.37°. Decomposing that ~5° asymmetry: +1.94° from the spring-anchor offset alone (torso-only model), +2.56° more from the head's lever arm (45px, ~3× the torso CoM's), <1° genuine solver residual (≈ the ±0.5° run-to-run probe noise). So the asymmetry is real physics, not a solver artifact, and the 1° margin sits against a physically-understood edge.

Physics JS de-duplicated the same day (see below), so the limits live in exactly one place; at the time of this fix they had to be mirrored across root + web/.

AI-parity check: 200-ep seed-42 confirm of the deployed model (`seed2_resume_11611776_steps`) with the limit enabled = **mean 1493.1** (std 386.1, 0% early death, max 1936) vs the documented 1486.4 baseline → **+6.7, ~0.25 SEM = wash** (and the +6.7 is within run-to-run oneDNN inference FP jitter anyway). As expected: the driver is near-massless and the limit only engages on rocket-mode-level impacts the policy never generates. Deployed model NOT re-exported or retrained (no need). (This parity run was on the first ±90° cut; the argument carries over unchanged to the final asymmetric limit, which only adjusts a joint the policy never drives to its stops, so it was not re-run.)

Deploy status: shipped. The final asymmetric limit (−70.6°/+104.5°) + neck-limit removal is committed + pushed to `web/` (`main` 7a956e1 → Vercel); the earlier ±90° cut was d665a41.

## 2026-07-07 — Physics JS single-sourced in web/ (dedup)

The physics JS (`Box2d.js`, `Car.js`, `Wheel.js`, `Person.js`, `Ground.js`) used to exist as byte-identical copies in BOTH the repo root (read by `js_backend.py` for training + by the legacy game) and `web/` (the deployed Vercel site). Two live copies = a silent-desync trap (the joint-limit fix above had to be mirrored across 4 files). Deduped to a single source:

- `web/` is now the sole home. `js_backend.py:_read` was repointed to `web/…` (added `_WEB = ROOT/web`; the 4 load lines are unchanged). It's the only physics reader; everything else (env/eval/export/autorun) goes through it.
- `legacy_neat/index.html` now loads physics from `../web/` (p5 still from `../libraries/`); the archived `analysis_artifacts/measure*.html` likewise.
- Root `Car/Wheel/Person/Ground.js` + `libraries/Box2d.js` **deleted** (were byte-identical; verified before removal). Root `libraries/` now holds only p5.
- `cb_reference/` untouched — still the pristine diff baseline.

Constraint that dictated the direction: Vercel serves `web/` as a self-contained site, so the one physical copy MUST live there and the training path reads from it (can't invert). Verified: env resets + steps 600 ticks loading physics from web/, no JS error. NOT solved by this: the `ground.py` (Python port) ↔ `Ground.js` parity, a separate axis, since training builds terrain in Python, not from the JS file. Root is not a git repo, so this dedup also pulls the training-path physics into version control (web/) for the first time.

## 2026-06-18 — Save-scum backtracking BEATS THE GAME (the lever that broke the ceiling)

User idea ("cheat"): on death, don't restart from spawn: restore a physics snapshot a little way back, add a small random action burst, let the policy continue; retry a few times; if the same bottleneck keeps killing, rewind FURTHER; commit each cleared section; stitch the pieces into one continuous run. This is **Go-Explore's exploration phase** ("first return to a state, then explore"), and it's the right tool because the game is deterministic-but-chaotic (the jitter_probe regime). It FACTORIZES the per-section survival product that caps Best-of-X: Best-of-X needs one run to survive every hard section at once (∏ of small probs); backtracking clears each section independently (∏ of near-ones).

**Harness:** `python/autorun/backtrack_search.py`. Reuses `js.save_state()` + death-safe `reset_car()`+`restore_state()` (`tests/test_saverestore.py`). Resume is exact: snapshots physics AND the resumable policy state (manual `VecFrameStack(4)` + env coyote/stuck/progress counters). One persistent V8 world → committed run is one continuous sim, restores only at the few commit seams. Tracks pinned like best_of_k (seed 987000+t). `--baseline-k` runs paired Best-of-K; `--target-px` default = the lip.

**End-of-track, pinned down** (`diagnostics/measure_track_end.py`): solid terrain ends at the last vertex ≈ **19,185px = score 1883** (np.arange excludes the 19200 endpoint; the last 2 verts are closing verts). You don't die at the lip; you **fly off into the void**, projectile arc adds ~30–80px until `y*30>720` kills you, so a real completion scores **~1900–1962** (seed 987004→1922, 987013→1962, 987005→1912). The repo's `COMPLETE_PX` (1790) is a SOFT line ~935px short; all prior "completion" stats used it, leaving the run-up + launch finale untested (it has real new bottlenecks ~18,300/18,750px).

**Results (deployed champion, 30 pinned tracks, paired Best-of-30 same terrain):**
- Soft line (1790): backtracking **96.7%** (29/30; 9 single-shot, 20 backtrack, 1 budget-capped, 0 rewound-to-spawn) vs Best-of-30 **76.7%**. Strictly dominant (+6 tracks, 0 losses). Cost ~1.8× ticks (42.8k vs 24.1k/track).
- BEAT the game (lip + fly-off): backtracking **96.7%** (29/30) vs Best-of-30 **66.7%**. The gap WIDENS to +30pp because the finale drops Best-of-30 76.7→66.7 while backtracking holds 96.7 by rewinding deeper (max depth 76 vs 37). Achieved scores 1885–1962. Cost ~2× ticks (65.6k vs 31.9k/track).
- The lone holdout (track 12 / seed 987011) was budget-capped; a re-run at budget 2M + attempts-per-depth 16 BEAT it (1927, depth 92, 2039 attempts, 977k ticks) → **30/30 = 100% with patience. No true on/off-motor hard core in this sample**: the limit is budget/chaos, not skill.

**CAVEAT:** this is a CONSTRUCTED stitched replay, not a better policy or a legit single-shot/Best-of-X number. Go-Explore "robustification" (BC the trajectories into a policy) would likely wash, as SIL/BC already did.

**Artifacts / browser:** `python/autorun/export_replay.py` re-runs the (deterministic) search per track and can replay it to an EXACT per-tick pose stream (vertices px + spawn
+ poses + body dims). **NOTE (web/ reorg):** the browser no longer ships pre-exported replays: the old pinned-track picker (**▶ Watch AI beat it** ghost-replay + **Load & drive**) and the `replays/` folder it read were removed. `web/index.html` now runs the Go-Explore search **live in-browser** on the *current* terrain via one button, **▶ Watch the AI beat this map**, then ghost-replays the result.

## 2026-06-08 autonomous session (6 experiments, all negative/wash)
Log: `python/autorun/RUNLOG.md`. **No deployable improvement found; champion + Best-of-X stays.** Results:
- **Best-of-K curve** (champion, pinned tracks): K=8→65%, K=10→**70% hard plateau** (flat to K=16); mean 1476→1820. web/index.html already ships Best-of-X (det argmax + ±1px jitter, default X=15) → **X=10 is already near-optimal**.
- **Seed search** (seeds 2,3): wash (+23 p.56 / −32 p.46) → champion seed-robust.
- **Multi-life death-markers** (markers-only; lives=6 & lives=3): lose to free Best-of-X (K=8: 53–55% vs 65%); markers cut the trajectory diversity Best-of-X needs. lives=3 helps single-shot (26.7 vs 20%) but not under Best-of-X.
- **RecurrentPPO/LSTM** (full 8M): −447 paired, p<1e-4, decisively worse.
- **Frame-stack-8**: −112 paired, p=.02 — more temporal context hurts (4 is best).
- **Stochastic Best-of-X**: ~67% vs deterministic 70%; it can't break the ceiling.
- **Methodology**: confirmed `eval.py --ab` is ~unpaired at f=0 (both envs reroll off the global `random` stream); pinned-track inject is the true-paired method.
- **Train-vs-eval curves** (follow-up): within-run, deterministic eval DOES track `ep_rew_mean` (r +0.59/+0.72/+0.90 for seed2/fs8/base16); the dissociation is cross-run/at-ceiling only. Full detail in the "16M / train-vs-eval" section below; plots `train_vs_eval_curves.png`, `train_vs_eval_base16.png`.
- Remaining untested high-upside idea: a TRUE multi-life episode (credit across lives), vs the saturating markers-only design tested here.


## TL;DR

A Hill Climb Racing AI: PPO drives a 2-wheel car over procedural terrain, maximizing forward distance. Started as a Python port of Code Bullet's old NEAT-based JS game; we ended up running the **unmodified JS physics** inside V8 (PyMiniRacer) for both training and browser deployment, because `pybox2d 2.3.10`'s solver allowed 30–100 mm of wheel drift the original `Box2d.js 2.0/2.1` doesn't (see "Physics history"). Terrain is a bitwise-exact Python port of p5.js `noise()`, so the training distribution matches the actual game.

**Deployed (2026-06-15): `seed2_resume_11611776_steps.zip`** → `web/ai_policy.onnx` (same obs/arch as base_a, drop-in). A snapshot from the seed2 hold-low resume; held-out 500-track paired **+68 vs base_a (1490 vs 1422, p=0.0065)**; 200-ep seed-42 confirm **1486.4** (median 1554, 0% early deaths; base_a was 1367.5 same protocol, but different tracks → cite the paired +68, not +119). Deployed at the user's explicit request. **CAVEAT (snapshot-pick, against the default-to-`_final` rule):** the run's endpoint and neighbors WASH vs base_a (resume_final +20 ns, 12M +23 ns, 11.2M −51), so the +68 is likely a lucky peak of the ±100 per-checkpoint eval wander, not a better model. **Revert:** re-export `base_a_8000000_steps.zip` over `web/ai_policy.onnx` with `export_onnx.py`. See "Deploying a snapshot-pick" below.

**Prior champion: `base_a_8000000_steps.zip`** (12-dim per-wheel obs + reward shaping + LR/entropy decay, 8M PPO steps, normal terrain): **mean 1367.5** (200-ep det, seed 42; std 428, median 1422, 90th pct 1900, 0% early deaths); 1350.7 pre-fix. (The `.onnx.bak` deploy backups were deleted in the web/ reorg; re-export from the `.zip` checkpoints to revert. Older 1312 champion is `ppo_p5_combo_a_6400000`.)

**The ~1350 ceiling is CHAOS, not missing skill** (jitter probe, 2026-06-06): the policy is near-optimal at general driving (0% early deaths); on any given track, ±1px spawn jitter spreads its stop point by a median **10,275 px**, and 8 jittered attempts complete **67.5%** of tracks (vs 20% single-attempt; oracle mean 1798.7 against a ~1885 track-length cap). The limit is per-section survival *probability* in the steep back third. Every config tried lands in 1180–1432; see the experiment log.

**Test-time levers.** Best-of-X is the deployed single-policy lever: ~82.5% completion at K=30 on the deployed model (old soft line). Save-scum backtracking beats the game on 30/30 pinned tracks, but it is a constructed stitched replay, not a better policy; it runs live in the browser (**▶ Watch the AI beat this map**).

**Tested negative** (details in the log): reverse and easy→normal curricula, bottleneck-spawn, rear vision, 13-sample forward vision, retraining on the corrected terrain, deeper/wider nets, no frame-stack, frame-stack-8, longer episodes, 16M steps, compressed decay <8M, constant-low resume, SAC, γ=0.999, self-imitation, cross-seed distillation, risk-averse death penalty, multi-life death markers, RecurrentPPO/LSTM, seed search, stochastic Best-of-X, test-time MPC, targeted perturbation, spawn-jitter and in-episode-nudge robustness training, champion+robust ensemble. ~8M steps is a saturation knee.

**Remaining untested policy lever:** a true multi-life episode with credit across lives (markers-only saturates; expectations low). The ~17% Best-of-X hard core is shared across policies. Physics is off-limits.

## How it works

```
Training:
  python/env.py (gym.Env)
    → python/js_backend.py (PyMiniRacer / V8)
      → loads libraries/Box2d.js + Wheel.js + Person.js + Car.js
      → ground.py generates terrain via p5_noise.py, hands vertex list to JS
      → JS steps Box2D, returns obs JSON; PPO picks Discrete(3) action

Browser:
  web/index.html → web/libraries/ort.min.js (single-threaded SIMD WASM)
    + web/ai_policy.onnx + web/ai_policy.js (obs construction)
    + the SAME JS physics files (copied into web/)
```

## Repo layout

```
Hill-Climb-Racing-AI/          # (canonical map: CLAUDE.md "Repo map (essentials)")
├── web/                       # deployable static site (subtree-pushed → Vercel);
│                              #   *** SINGLE SOURCE of the physics JS *** — js_backend.py
│                              #   reads web/{Car,Wheel,Person,Ground}.js directly (no root copy)
│   ├── index.html, ai_policy.js, ai_policy.onnx, policy_meta.json
│   ├── Car/Wheel/Person/Ground.js, Pics/, libraries/{Box2d,ort.min}.js + *.wasm
│   └── vercel.json, README.md, HOW_TO_PLAY.md
├── CLAUDE.md / PROJECT_STATUS.md / CONVENTIONS.md / README.md / HOW_TO_PLAY.md
├── cb_reference/              # pristine Code Bullet originals (for diffing; not loaded)
├── legacy_neat/               # NEAT-era JS game; loads physics from ../web/, p5 from ../libraries/
├── libraries/                 # p5.{js,dom,sound}.js ONLY (for legacy_neat)
├── analysis_artifacts/        # one-off diagnostic outputs (measure*.html, trace*.json, …)
├── Pics/                      # sprites for the legacy game (web/ has its own copy)
└── python/
    ├── .venv/                 # Python 3.13 + SB3, gymnasium, py_mini_racer, onnx(runtime), pygame, tb
    ├── constants.py           # SCALE, sizes, spawn, GROUND_* (physics params live in JS)
    ├── ground.py              # terrain gen (numpy-vectorized; difficulty knob; is_too_steep gate;
    │                          #   scalar refs _randomize_scalar/_is_too_steep_scalar kept for tests)
    ├── p5_noise.py            # exact p5.js noise() port + bitwise-identical noise_array()
    ├── js_backend.py          # JSPhysics: V8 wrapper around the JS classes
    ├── env.py                 # HillClimbEnv; kwargs per_wheel_obs, reward_shaping, lookahead_n
    ├── train.py               # PPO entrypoint; champion recipe IS the defaults (see --help)
    ├── eval.py                # batch / watch / paired-A/B eval (PPO only)
    ├── play.py / renderer.py  # manual driving + pygame renderer
    ├── export_onnx.py         # PPO .zip → web/ai_policy.onnx (default; dynamo=False, opset 11)
    ├── harvest.py             # SIL demo harvester (reusable)
    ├── finetune_sil.py        # weighted-BC + KL-anchor fine-tuner (SIL v1: no benefit)
    ├── demos/base_a_h1.npz    # 2,552 segments / 1.21M demo steps (reusable)
    ├── checkpoints/ tb/
    ├── diagnostics/           # rc_scan.py (snapshot scan/confirm), deathmap.py,
    │                          # jitter_probe.py (chaos / pinned-track probe),
    │                          # test_vectorized_ground.py (bitwise parity),
    │                          # p5_sweep_results.json + old run logs
    └── archive/               # retired trainers (reverse-curriculum train.py, SAC)
                               # + their launch scripts (see archive/README.md).
                               # NEVER delete unless the user explicitly says so.
    (legacy_pybox2d/ pre-JS-physics port deleted 2026-07-07 — see git history)
```

## Model selection & eval protocol (adopted 2026-06-06)

Per-track score std is ~430 and chaos decorrelates everything, so eval noise dominates most differences. Rules:

1. **Default to the `_final` checkpoint.** Since the LR/entropy decay landed, final ≈ plateau in every run; that was its purpose.
2. **The scan (`rc_scan.py`, 60 ep × all ckpts ≥4M) is a COLLAPSE DETECTOR, not a picker.** Within a scan all checkpoints share the same tracks, so it reliably shows the run's shape, but the argmax of 41 means with SE≈55 is mostly luck and inflates ~+100 (measured: scan→confirm regressions of −97 and −121). Only if final sits >150 below the plateau (pre-decay collapses were 150–350) is snapshot-picking justified.
3. **Cite only 200-ep confirms** (`rc_scan.py x --confirm <zip> --episodes 200 --seed 42`), never scan means.
4. **Cross-model claims need the paired A/B on identical tracks** (`eval.py A --ab B --deterministic --ab-deterministic --random-terrain`). Different protocols generate DIFFERENT track sets even at the same seed: a 200-track set shifts means by ±60 of pure track luck (this manufactured an illusory +65 for base_nd_a; the paired test showed +18.9, p=0.65). Even paired, the per-track diff sd is ~586 (chaos), so SE≈41 at n=200; resolving a true +20 would need ~3,600 episodes.

## Reproduce / deploy the champion config

```powershell
# Defaults ARE the champion recipe (per-wheel obs, reward shaping, LR/entropy
# decay, normal terrain). ~65 min:
python\.venv\Scripts\python.exe python\train.py --timesteps 8000000 --seed 1 --name my_run

# Collapse check, then confirm the FINAL (see protocol above):
python\.venv\Scripts\python.exe python\diagnostics\rc_scan.py my_run --min-step 4000000 --episodes 60
python\.venv\Scripts\python.exe python\diagnostics\rc_scan.py x --confirm python\checkpoints\my_run_final.zip --episodes 200 --seed 42

# Export + deploy (no path arg = straight to web/ai_policy.onnx; hard-refresh the page):
python\.venv\Scripts\python.exe python\export_onnx.py <ckpt.zip>
```

CLI cleanup 2026-06-06: old experiment-log commands map as `--per-wheel --reward-shaping --reverse-curriculum --rc-fmax-cap 0.0` ≡ today's no-flag default; the curriculum/SAC trainers moved to `python/archive/`. Per-wheel + shaping are also the env defaults now (`HCR_PER_WHEEL=0` / `HCR_REWARD_SHAPING=0` to eval legacy 11-dim checkpoints). If the obs layout changes vs the deployed model, update `web/ai_policy.js` (`PPO_PER_WHEEL`, `PPO_REAR_N`, `PPO_LOOKAHEAD_N`).

## Experiment log (chronological; all evals 200-ep det seed 42 at f=0 unless noted)

### May 2026 sweep (7 runs × 8M, pre-decay)

| Config | Seeds | Mean | Individual |
|---|---|---|---|
| baseline (no flags) | 3 | 1179.3 ± 39.8 | 1135, 1192, 1211 |
| reward shaping alone | 2 | 1156.3 | 1124, 1189 |
| per-wheel + reward ("combo") | 2 | 1237.8 | **1312**, 1163 |

The 1312 seed (combo_a @6.4M peak) became the long-time champion: tighter variance (std 365 vs 430–510) and higher q10 (863 vs 405–601).

### Ruled out (multi-seed or >2σ single-seed regressions)

- ❌ Deeper net [256,256,256] — instability (approx_kl 0.038, clip_fraction 0.24), −200+.
- ❌ No frame stack; longer episodes (max_steps 5000); 16M steps (regresses to the mean instead of building on the lucky peak); reward shaping alone.
- ❌ SAC — slower, matched at best; `Car.motorOn` is sign-only so the continuous action is wasted.
- ❌ Easy→normal curriculum + bottleneck spawning: run a (curr 0.15→1.0, bottleneck 0.6) peaked 1167 @5.5M then COLLAPSED to 808 @8M (early deaths 0.5%→27.5%); run b with decaying bottleneck-prob + LR/entropy decay fixed the collapse (final-is-best, 1221, 0% early deaths) but still under the champion. Curriculum infra later removed from train.py.
- ❌ Rear vision (3 samples behind): no benefit; `GROUND_REAR_N=0` now, JS code path kept (guarded on rear_n>0).
- ❌ γ=0.999 + max-steps 3000 long-horizon probe (`hzn_a`, 2026-06-05): confirm 1252.9; paired vs base_a **−90.8, CI [−168,−13], p=0.022 — significantly WORSE** (return-variance inflation). Tail failures are not a discount-horizon problem.

### Reverse curriculum + the decay discovery (2026-06-05)

Mechanism: difficulty `f` raises the steepness FLOOR (130+120f, ceiling pinned 250); f=0 byte-identical to normal; per episode f~U(0,f_max(t)), f_max ramps over training. (CLI retired 2026-06-06 → `archive/train_reverse_curriculum.py`.) Paired A/B, 2 seeds × {rc, normal-only baseline}, shared net-init/terrain seeds:

- Finals: RC 1327.1/1311.5 vs baseline 1350.7/1328.1. All 6 paired tests (f=0, 0.5, 0.75) non-significant; RC doesn't win even on the hard terrain it trained on. **Reverse curriculum: NO benefit**: the task generalizes upward from normal terrain.
- **Unexpected +155 win: the LR 3e-4→1e-4 + entropy 0.01→0.003 decay** (shared by both arms). Isolated with no-decay controls at the same seeds: finals 1339.4 (decay) vs 1184.6 (no decay), both seeds consistent. It's ANTI-DEGRADATION, not a higher ceiling: peaks are ~1340–1380 either way; decay keeps the FINAL at peak (the old 1312 "champion" was exactly a lucky no-decay peak; nodecay's best snapshot was 1336.8). This resolved the peak-vs-final problem and led to deploying `base_a_8000000` (final).

### Terrain distribution fix + vectorization (2026-06-06)

Re-diffed against the live Code Bullet code (`cb_reference/`): `randomizeGround()`/noise/physics byte-identical, BUT the real game rerolls **unbounded** until `isTooSteep()` passes (sketch.js:234) while our port capped at 10 rerolls then accepted. The gate rejects ~97% of raw maps (~33 rerolls avg), so it *defines* the game's distribution; under the 10-cap ~73% of our maps were ones the real game never shows (worst-window climb mean 6.0 m / max 9.3 m vs the gate's 5.0 m cap). Fixed in `ground.py make_ground` and `web/index.html rollAcceptableGround` (1000-reroll safety cap; only relevant at high f; at f=1.0 pass rate 0.2%, ~2 s/map, ~13% of calls exhaust the cap).

- **Champion re-eval on the new distribution: 1367.5 vs 1350.7, unchanged** (z≈0.4). The gate sits far below the car's capability (~16× over-conservative), so the policy already climbed most 5–9 m windows. The fix matters for human-play fidelity, not AI score (confirmed by the base_nd_a retrain below).
- Reroll cost (reset 119→308 ms) erased by **numpy-vectorizing the generator** (`p5_noise.py noise_array`, `ground.py randomize`/ `is_too_steep`): **bitwise-identical** (asserted over 30 seeds × 4 difficulties by `tests/test_vectorized_ground.py`; a 20-ep eval reproduced per-episode scores exactly). Single roll 7.2→1.0 ms, make_ground f=0 164→39 ms (f=1.0 2019→170 ms), env reset 308→**83 ms**, faster than pre-fix.

### Ceiling re-characterization: it's chaos (2026-06-06)

Deathmap (n=200, new distribution): base_a completes 18.0%, 0% early deaths/timeouts, non-completions stop at 67–90% of track (steepness ~210).

**⚠ The old cross-policy consensus analysis was BROKEN**: `impassable_test.py` part B (and the pre-fix "27.5% some-complete / ~5% impassable / 4,686 px spread" numbers) compared policies on NON-identical tracks: `make_ground`'s reroll loop and grass picks consume the **global** `random` stream, so same-seed envs see different terrain. Do not cite those %s. (Qualitative "failures are diverse, not shared walls" survived.)

Corrected experiment (`diagnostics/jitter_probe.py`: pin tracks via `random.seed(k)` before `make_ground(None)` + `env._make_ground` injection; 40 tracks; raw data `jitter_probe_results.npz`):
- ±1px spawn jitter (the web/index.html Best-of-X trick) spreads base_a's stop position by a **median 10,275 px** on the same track; only 2% of tracks have all 8 attempts agreeing within 800 px.
- Single attempt completes 20%; **8-attempt jitter-oracle completes 67.5%**, beating a 3-policy oracle (40%); cross-seed "complementary skills" was an attempt-count artifact (rc_a's apparent 25% completion edge fell to 12.5% on pinned tracks). Jitter-oracle mean 1798.7 (cap ~1885).
- Implication: the ceiling = per-section survival probability (robustness). Cross-seed distillation is dead; near-maximal play already exists inside the policy at low per-attempt probability.

### Self-imitation v1 (2026-06-06) — NO improvement

Pipeline: `harvest.py` (per pinned track: det baseline + K stochastic attempts with ±1px jitter; keep attempts beating baseline by >500 px; extract divergence segments around the baseline death zone; 1,000 tracks × 8 → **2,552 segments / 1.21M steps → `demos/base_a_h1.npz`**, ~80 min; 19.6% of steps sample off-argmax at T=1.0) + `finetune_sil.py` (weighted BC + KL anchor to the frozen champion, policy net only). Findings:
1. Per-step critic advantage max(0, rtg−V) is the WRONG weight: V(s) is a distribution-average; even winning attempts sit below it in steep sections → 99.3% of steps got zero weight. Use the segment-level counterfactual (d_att − d_det, same track) instead.
2. Even then BC barely moves the policy: fork-adoption plateaus at 3–4.6% across kl_coef ∈ {1.0, 0.3, 0.1} × 10 epochs; the demo set is self-contradictory (80% of steps are the champion's own argmax, outvoting the forks ~4:1 at overlapping states).

Paired A/B (sil_kl01_ep10 vs champion): **−49.5, CI [−134,+35], p=0.25** → wash leaning negative. Scripts + npz kept as infrastructure. Untested v2 ideas: death-zone-proximal fork weighting (pure compute_weights change), contrastive winner-vs-loser harvesting: likely wash too if the wins are unidentifiable chaos.

### Human benchmark (2026-06-06)

The user completes 20–40% of maps first-try, ~90% within 5 tries. The AI: 18–20% first-try (parity through a 48-float keyhole) but only 67.5% in 8: its retries are i.i.d. samples of a frozen policy; a human's are ADAPTIVE (remember the death spot, change approach). Measured deficits: between-attempt adaptation, perception, planning horizon, not reflexes. This produced the candidate list in the TL;DR (multi-life death-marker training, RecurrentPPO).

### Extended forward vision + new-distribution retrain (2026-06-06) — both negative

"Human-length vision": the camera pins the car at x=350 of 1280, so a human sees 930 px (31 m) ahead; the AI saw 375 px (12.5 m). Infra: `env.py` `lookahead_n` arg + `HCR_LOOKAHEAD_N` override (default 6, old models unaffected), `train.py --lookahead-n`. Trained 13 samples × 75 px = 900 px / 30 m (obs 19 → 76 stacked), champion recipe otherwise, PLUS a matched 6-sample control on the new distribution (`base_nd_a`):

- `vision13_a` best (7.2M; scan 1426.9): confirm **1305.4**
- `base_nd_a` best (6.8M; scan 1529.9): confirm **1432.4**
- **Vision: −127 vs matched control — clearly worse.** Consistent with chaos (failures aren't missed foresight); +28 stacked input dims likely made optimization harder on the same budget.
- **Distribution retrain: wash.** Paired A/B base_nd_a_6800000 vs champion: **+18.9, CI [−63,+101], p=0.65** (wins 107–93); the confirm-protocol +65 was track-set luck. **Champion/ONNX unchanged.**
- Both scan→confirm regressions (~−100) motivated the model-selection protocol above. Kept ckpts: both `_final`s + the two cited snapshots.

### Risk-averse death penalty (2026-06-07) — clearly negative

Hypothesis: the −50 death penalty (≈5 s of driving) makes the optimal policy risk-neutral on distance; raising it should buy first-try completion. Arms `risk300_a`/`risk500_a`: champion recipe + `--death-penalty 300/500 --max-steps 4000` (flag added to train.py/env.py, default 50 unchanged; `HCR_DEATH_PENALTY` override).

| (paired, identical tracks, n=200) | champion | risk300 | risk500 |
|---|---|---|---|
| mean score | 1412.9 | 1277.3 (−135.6, p=0.0045) | 1248.5 (−164.4, p=0.0001) |
| completion (≥1800) | 24.5% | 14.0% | 11.5% |

Finals confirm 1226.6 / 1239.3; scans show no collapse (finals ≈ plateau), just a lower, noisier plateau. **Worse on BOTH metrics, monotonically in the penalty, and pace was unchanged** (score/step 0.63 for all three): the arms never learned to drive slower, they got worse. Reading: with an on/off motor and momentum-hungry climbs, pace is terrain-set, not policy-set: a "careful" mode doesn't exist in the action space, so the bigger penalty only inflated reward variance and degraded optimization (same failure family as γ=0.999). Confirms the jitter-probe picture: deaths are chaos rolls, not recklessness. Reward-tuning toward completion is a dead lever.

### RecurrentPPO probe (2026-06-07) — ABORTED, inconclusive

Infra built and kept: `train.py --recurrent` (sb3-contrib RecurrentPPO, MlpLstmPolicy, single-frame obs, no stack), recurrent-aware `eval.py`/ `rc_scan.py` (LSTM auto-detect + hidden-state threading). Run `recurrent_a` killed at ~1.3M/8M: ~238 fps on CPU (~9 h/run, 8.6× PPO) and the early curve tracked the PPO runs. NOT a verdict on the lever: 1.3M is too early to judge an LSTM; the cost/benefit just didn't clear. Revisit needs GPU torch or the shared/128 LSTM config.

### 16M with stretched decay (2026-06-07) — train/eval dissociation, wash

The user observed all runs' `ep_rew_mean` still rising at 8M; verified: it follows a log law (R² 0.6–0.8; a 0.5–6M fit predicts the held-out 6–8M segment; projected +24–41 train reward for 8M→16M; tooling: `diagnostics/_tb_trend.py`, `_tb_logfit.py`). May's 16M failure predates the decay, so `base16_a` = champion recipe, 16M, decay stretched over 16M (the schedule is tied to --timesteps; NEVER --resume a finished run to extend; it resets LR/ent and undoes the decay). Result: train reward 437 (log law held, +60 over 8M runs) but paired A/B vs champion on identical tracks **+15.9, CI [−68,+99], p=0.71; completion 20.5% vs 24.5%**: the gain did NOT transfer. (The 1434.5-vs-1367.5 confirm gap is the usual cross-protocol track-set illusion.) The wash is **cross-run, not within-run** (see the eval-curve follow-up below): with stretched decay base16 keeps converging (its eval rises to ~16M) but only to the SAME ceiling the 8M champion already hit, so 2× compute is a dead lever for *beating* it. (nodecay is the sharper cross-run case: train reward rose while its eval FELL ~150.) Only the f=0 paired A/B settles it.

### Train-vs-eval curves (2026-06-08 follow-up) — within-run they DO correlate
Deterministic eval CURVES across checkpoints (pinned-track, low-noise; `autorun/eval_curve.py`) vs the stochastic `ep_rew_mean`:
- seed2 (champ recipe, 8M): Pearson r=+0.59; eval 1103→1433 over the run.
- fs8 (frame-stack-8, 8M): r=+0.72; eval 1003→1302 (worse policy throughout: trains to *higher* reward than champion yet evals ~130 lower).
- base16_a (16M): **r=+0.90 (r=+0.82 even for ≥8M)**; eval 1235(8M)→1377(16M), noisy peak 1526@14.4M.

**Correction to the "rising `ep_rew_mean` ≠ rising eval" shorthand:** WITHIN a run deterministic eval tracks training reward, often strongly; both are driven by the policy converging (base16's stretched decay keeps it converging, hence eval rising, to ~16M). The real dissociation is narrower: (1) **cross-run ranking**: training reward can't rank competent policies (fs8 trains higher, evals lower than champion); (2) **at the ceiling**: a longer/stretched run reaches the SAME eval ceiling as the shorter champion (base16 16M ≈ champion 8M, +16 p=0.71), so "still rising at 16M" ≠ "beats the 8M model". Within-run curves and snapshot peaks (base16's 1526@14.4M is a single noisy 40-track point) must not be snapshot-picked; only the f=0 paired A/B decides cross-run. Plots: `train_vs_eval_curves.png`, `train_vs_eval_base16.png`; infra: `eval_curve.py`, `plot_curves.py` in `python/autorun/` (the one-off `plot_curve_base16.py` was pruned 2026-07-07).

### Compute vs decay (2026-06-15) — ~8M is a saturation knee, ceiling is robust
Tested whether the eval ceiling is set by the decay schedule completing or by raw compute. All eval on the SAME 120 pinned tracks (paired vs champion):
- **Q2 compressed-decay** (decay auto-tied to `--timesteps`): 2M **1211** (−199, p=.0006), 4M **1267** (−143, p=.009), 8M champion **1409**, 16M **1421** (+12, wash). => SATURATION curve: eval climbs to ~8M then plateaus. Compute matters UP TO ~8M (decay-compression can't substitute for it); beyond 8M wasted. dec4m trained to *higher* reward (394) than champion (376) yet evaled 143 lower: compressed anneal inflates the train curve on an undertrained policy.
- **Q1 resume hold-low** (new `train.py --resume-hold-low`: holds LR/ent at 1e-4/0.003 constant instead of the default reset-to-3e-4/0.01): resumed seed2 +4M -> vs seed2(8M) **−11 p=.82**, vs champion **+5 p=.93**, a wash; train reward even drifted 437→418. Churns at the ceiling, can't exceed it.
- **Takeaway:** the ~1410 ceiling is reached at ~8M and is robust from every direction (less compute undershoots, more saturates, const-low resume can't push past): a policy-class × chaos ceiling, not a schedule artifact. Champion 8M is the right compute. Figure: `compute_vs_decay.png`; infra: `autorun/paired_ab.py` (the one-off `combined_plot.py` was pruned 2026-07-07).

### Deploying a snapshot-pick: seed2_resume 11.6M (2026-06-15)
The seed2 hold-low resume's eval CURVE had a 40-track spike at 11.6M (1582). Investigation of whether that's real:
- 1582 was a 40-track high; on 200 tracks it regressed to 1462 (+53 vs champ, ns).
- Held-out 500-track (seed-base 555000, NOT the selection set): 11.6M **+68.3, p=0.0065** vs base_a, i.e. real & replicated for THAT snapshot.
- BUT the natural endpoint `resume_final` = +20 (ns) and `12M` = +23 (ns), and the adjacent `11.2M` = −51. Adjacent checkpoints swing −51→+68 in 0.4M steps = the ±100 per-checkpoint deterministic-eval wander (chaos-amplified; training reward is flat throughout, so the policy isn't actually changing much). 11.6M is a LONE peak, not a sustained plateau.
- Fair run-vs-run (endpoint vs endpoint) = wash. The +68 exploits run A's wander via snapshot-picking while base_a (intermediates pruned) gets no such pick.
- The recommended decisive test (dense late-checkpoint sweep on a fresh set: lone-spike vs plateau) was NOT run; the user chose to deploy 11.6M directly. **Deployed at user request despite the snapshot-pick caveat.** Revert = re-export `base_a_8000000_steps.zip` over `web/ai_policy.onnx` via `export_onnx.py` (the old `.onnx.bak` backups were deleted in the web/ reorg). Recommended follow-up if revisiting: the dense-sweep test, and/or re-confirm 11.6M on a 3rd held-out set; if it's a lone spike, revert to base_a. Tangent settled here too: the resume "dip" some curves show is NOT a bug: LR/ent constant (TB), Adam momentum restored, training reward flat; seed2 UNINTERRUPTED dips the same (4.8M 1310, 7.2M 1329 on 120 trk). It's the same eval wander.

### Snapshot re-test, test-time search, robustness (2026-06-16) — all negative
- **Deployed snapshot re-test:** seed2_resume 11.6M vs base_a on identical pinned tracks = **+52.6 mean (n.s., p≈0.13)**, completion TIED (~22–24% across base_a / deployed / re-anneal). A +4M reset-high re-anneal from this lineage fell back to base_a's mean (−70 vs deployed, p≈0.035). The snapshot is a real-ish ~+60 mean-distance peak the lineage can't re-reach, and it buys no completions.
- **Best-of-X on the deployed model** (120 pinned tracks, `best_of_k.py`): K=8→66.7, K=10→70.0, K=15→79.2, K=20→81.7, **K=30→82.5%**. It keeps gaining past K=10 (the old "70% plateau, flat to K=16" was base_a). Browser now early-stops on completion with default X=15. Adaptive allocation (`adaptive_bestofx.py`) reaches 82.5% at avg-10 attempts (+12.5pp over uniform-10 = oracle). All against the OLD soft line (see glossary).
- **Test-time MPC/search** on the frozen policy: chaos defeats foresight at every horizon; H=90 hurts 50%→17%. Planner retired to `archive/planner.py`.
- **Targeted perturbation** at the death spot: wash vs blind jitter.
- **Robustness training** (`--spawn-jitter 1.0`): −148 paired single-shot, p≈0.0004.
- **Champion+robust ensemble:** no help at matched budget; a shared ~17% hard core.

### In-episode exploration nudge (2026-06-19) — negative
Idea: bring the test-time save-scum perturbation INTO training: occasionally give the policy a small random "nudge" mid-episode so it learns to be robust to error and to escape spots where it gets stuck. Built as default-off, parity-safe infra:
- `js_backend.nudge(dvx,dvy,dav)` adds a small chassis velocity + angular-velocity kick via the SAME `SetLinearVelocity`/`SetAngularVelocity` path `restore_state` uses → solver/joints/torque untouched, browser parity holds. Verified: parity byte-identical with `nudge_prob=0`; the kick perturbs velocities as specified.
- `env.step()`: with prob `nudge_prob`/tick, **only while grounded** (recoverable) and **outside an existing grace window** (no compounding), step then nudge. It's modeled as env DYNAMICS NOISE (agent observes the post-nudge state and reacts → PPO stays on-policy, NOT an action override). The −50 death penalty is suppressed for `NUDGE_GRACE_TICKS=30` (~1s) after each nudge so a nudge-into-a-wall death isn't charged to the policy (the "fair"/exploration version; raw-DR would charge it). `train.py --nudge-prob/--nudge-mag` plumbed like `--spawn-jitter`.
- Run: fresh 8M, seed 1, champion recipe + `--nudge-prob 0.01 --nudge-mag 0.5` (`nudge_a`). No collapse (rc_scan: `_final` 1344.3 @ seed12345, 0% deaths, ≈ plateau; argmax 7.3M=1466.8 is the usual noisy-60ep inflation, NOT snapshot-picked).
- **Result — modestly HURTS.** Paired single-shot vs base_a on 200 identical pinned tracks (`robust_ab.py`): base_a **1410.2 / 21.5%** vs nudge_a **1316.6 / 17.5%**, diff **−93.5 (sd 605.9, SE 42.8, t(199)=−2.18, p≈0.03)**, nudge-better on 94 of 200. Standalone 200-ep seed-42 confirm: nudge_a **1314.9** (vs base_a 1367.5 same protocol, different track set → cite the paired −93.5). Completion FELL, the opposite of the hypothesis.
- Mechanism (as pre-registered): the on/off motor can't trade against a perturbation ("can't trade speed for survival"), and chaos means perturbed states never recur, so there's no stable recovery to learn, and perturbation-during-training dilutes the specialized single-shot trajectory. Same direction as `--spawn-jitter 1.0` (−148): two independent perturbation-training negatives now. A smaller/rarer nudge might wash to neutral but a positive config is unlikely; no sweep run (each point is a 65-min run). Infra kept in-tree (default-off, parity-safe, reusable).

## Physics history (why JS Box2D in V8)

- Original game: `Box2d.js` (Emscripten port of Box2D 2.0/2.1). Our pybox2d (2.3.10) port needed weeks of tuning yet capped at score ~836 (PPO) / 986 (SAC), with visible horizontal wheel drift during impacts.
- Measured: JS allows **1–4 mm** drift, pybox2d **30–100 mm** (`wheel_drift_measure.html` vs `diagnostics/wheel_drift_test.py`). It's the solver algorithm (relaxed 2.1→2.3 for speed), not parameters.
- Failed fixes: writing `b2_linearSlop`/`b2_baumgarte` from Python (SWIG silently ignores writes); pyb2d3 / Box2D 3.0 (−45% drift but still 7× JS, full API rewrite).
- ✅ Run the unmodified JS via PyMiniRacer/V8: exact physics, ~1700 steps/s single-env (~12k aggregate × 8 SubprocVecEnv). Ceiling moved 836 → 1312. The physics was the bottleneck.

## Key gotchas

1. **pybox2d's `b2_linearSlop`/`b2_baumgarte` ignore Python writes** (SWIG read-only rebindings), so tuning them does nothing.
2. **PyTorch ONNX export defaults to the dynamo exporter**, which emits ops ORT Web 1.18 can't run (`Lt[m] is not a function`). Always `dynamo=False` (see `export_onnx.py`).
3. **Threaded WASM ORT needs `crossOriginIsolated`**, which `http.server` doesn't set. Single-threaded SIMD only (`ort.env.wasm.numThreads=1`).
4. **`Car.js` `this.shapes` stores vertices in METER space** — don't divide by SCALE again in renderers.
5. **`Ground.getPositions()` returns METERS** in the browser; `js_backend.py` overrides it to return pixels for `env.py`. Both correct; easy to mix up.
6. **Final checkpoint ≠ best — but default to final anyway**: see "Model selection & eval protocol". Scan to detect collapse; don't snapshot-hunt.
7. **`web/ai_policy.js` constants (`PPO_PER_WHEEL`, `PPO_REAR_N`, `PPO_LOOKAHEAD_N`) must match the deployed onnx's obs layout.**
8. **Same-seed envs do NOT see the same terrain** (global-RNG consumption by rerolls/grass). Pin tracks the `jitter_probe.py` way (seed the global RNG right before `make_ground(None)`, inject via `env._make_ground`).

## Things NOT to do

- ❌ `dynamo=True` in torch.onnx.export (won't load in ORT Web 1.18).
- ❌ Threaded WASM ORT (needs CORS headers we don't set).
- ❌ Restore pybox2d — the drift returns. (The archived `legacy_pybox2d/` port was deleted 2026-07-07; git history has it.)
- ❌ Add throttle scaling to `Car.js` — the original motor is on/off only and fidelity is intentional (this is why SAC's continuous action was wasted).
- ❌ Prune checkpoints (or other artifacts) without the user's explicit go-ahead; report keepers vs prunable and wait.
- ❌ Delete `python/archive/` (retired curriculum/SAC trainers), only with the user's explicit instruction.

## Running things

```powershell
# Train current best config: see "Reproduce" above.

# Batch eval / paired A/B:
python\.venv\Scripts\python.exe python\eval.py <ckpt.zip> --batch --episodes 200 --random-terrain --deterministic
python\.venv\Scripts\python.exe python\eval.py <A.zip> --ab <B.zip> --episodes 200 --random-terrain --deterministic --ab-deterministic

# Browser (ORT can't load over file://) — serve the web/ folder:
python\.venv\Scripts\python.exe -m http.server 8765 --directory web   # → http://localhost:8765/

# TensorBoard (avoid alongside long training runs — see Known issues):
python\.venv\Scripts\tensorboard.exe --logdir python\tb
```

## Known issues / caveats

- `play.py` works but its pygame renderer is minimal vs the browser.
- Checkpoints: pruned 2026-06-05 (3.8 GB → 46 MB) and again 2026-06-06. Training saves ~81/run, so it regrows fast. **Prune only with explicit user approval** (verify keepers → dry-run → delete).
- The ~100 MB/h kernel memory leak that caused `WinError 1450` on long runs was HP Omen Gaming Hub. Removing it fixed both.
