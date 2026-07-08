# CLAUDE.md — Hill Climb Racing AI

Orientation for working in this repo. For the detailed experiment log / handoff,
see **`PROJECT_STATUS.md`**; this file is the durable "how it works + how to
work in it" summary.

## What this is

A Hill Climb Racing AI: a PPO policy that drives a 2-wheeled car over
procedurally-generated hilly terrain, maximizing forward distance. It trains in
Python (Stable-Baselines3) and deploys to the browser via ONNX.

**The physics is the unmodified JS game** (`Box2d.js` + `Wheel.js` + `Person.js`
+ `Car.js`, Code Bullet's old game) run inside a V8 engine via PyMiniRacer — for
both training and deployment. We did this because `pybox2d 2.3.10`'s solver
allowed 30–100 mm of wheel drift the original `Box2d.js` (Box2D 2.0/2.1) doesn't;
running the real JS physics gives exact browser parity (and lifted the score
ceiling 836 → ~1300). **Do not restore pybox2d** — the archived port
(`legacy_pybox2d/`) was deleted 2026-07-07; git history has it if ever needed.

## Architecture / data flow

```
Training:  python/train.py (PPO, SubprocVecEnv ×8, VecFrameStack ×4)
  → python/env.py (gym.Env)
    → python/js_backend.py (PyMiniRacer / V8): loads libraries/Box2d.js + Wheel/Person/Car.js
    → python/ground.py generates terrain via python/p5_noise.py (p5.js noise port)
      → hands vertex list to JS via build_world(); JS steps Box2D, returns obs JSON
    → PPO reads obs, picks discrete action

Browser:   web/index.html → web/libraries/ort.min.js + web/ai_policy.onnx
           + web/ai_policy.js + the SAME Wheel/Person/Car/Ground/Box2d.js physics
           (the deployable static site lives entirely in web/ — its own git repo,
            deployed to Vercel. The physics JS is SINGLE-SOURCED here: js_backend.py
            reads web/Wheel.js etc. directly, so there is no root copy to drift.)
```

## Environment / running things

- **Python interpreter:** `python/.venv/Scripts/python.exe` (Python 3.13).
  All deps (SB3, gymnasium, py_mini_racer, onnx/onnxruntime, pygame, tb) are
  ONLY in this venv — the system `python` will `ModuleNotFound`. Windows.

```powershell
# Train (defaults ARE the champion recipe: per-wheel + reward shaping +
# LR/entropy decay, normal terrain; ~65 min):
python\.venv\Scripts\python.exe python\train.py --timesteps 8000000 --seed 1 --name my_run

# Scan for collapse, then 200-ep confirm the FINAL (see gotcha 3):
python\.venv\Scripts\python.exe python\diagnostics\rc_scan.py my_run --min-step 4000000 --episodes 60
python\.venv\Scripts\python.exe python\diagnostics\rc_scan.py x --confirm python\checkpoints\my_run_final.zip --episodes 200 --seed 42

# Batch eval / paired A/B:
python\.venv\Scripts\python.exe python\eval.py <ckpt.zip> --batch --episodes 200 --random-terrain --deterministic

# Export to browser ONNX (no path arg = straight to web/ai_policy.onnx; then
# hard-refresh the served page):
python\.venv\Scripts\python.exe python\export_onnx.py <ckpt.zip>

# Browser (ORT can't load over file://) — serve the web/ folder:
python\.venv\Scripts\python.exe -m http.server 8765 --directory web   # open http://localhost:8765/

# Tests (correctness, not the diagnostics/ probes) — see python/tests/README.md:
python\.venv\Scripts\python.exe python\tests\test_vectorized_ground.py   # terrain parity
python\.venv\Scripts\python.exe python\tests\test_saverestore.py         # save/restore fidelity
```

## Model / observation / reward

- **Obs:** 12-dim per-wheel (the default): chassis angle, rear-grounded,
  front-grounded, ang-vel, vx, vy, + 6 ground-clearance samples ahead (75 px
  apart; count configurable via `--lookahead-n` / `HCR_LOOKAHEAD_N` — 13 = the
  30 m human screen view, tested WORSE than 6). `VecFrameStack(4)` → **48-dim**
  policy input. Net: MLP 256×256 (pi & vf).
- **Action:** `Discrete(3)` — 0=forward, 1=reverse, 2=off. Motor is **on/off
  only** (no throttle scaling — this is why SAC's continuous action was wasted).
- **Reward:** forward progress `max(0, Δx_m)` + shaping (default on):
  `+0.01/tick` survival and `-50` on death.
- **Score** (the eval metric) = `(max_dist_px − spawn_x)/10`, **uncapped**.
  Three end-of-track landmarks (often conflated — see memory
  `true-score-ceiling-flyoff`): `COMPLETE_PX` soft line = **1790** (what
  best_of_k / jitter_probe / eval call "completion", ~935px short of the end);
  `END_PX` = **1850** (the old "~1850 cap"); the **last solid vertex ≈ 19,185px
  = score 1883** (the launch lip). **Beating the game = reach the lip and fly off
  into the void** (you die when chassis `y*30 > 720`); the projectile arc adds
  ~30–80px, so a real completion scores **~1900–1962** (measured;
  `diagnostics/measure_track_end.py`). The env never declares victory — episodes
  end only on death/truncation. `GROUND_DISTANCE=19200px`, `SCALE=30px/m`.
- Rearward samples exist but are off (`env.py GROUND_REAR_N=0`; tested, no
  benefit); `ai_policy.js PPO_REAR_N` must match the deployed model.

## Terrain / difficulty knob

- `ground.randomize(difficulty=f)`, `f∈[0,1]`: `f=0` is **normal** (steepness
  ramps 130→250 across the track — the real game distribution, byte-identical to
  the old code). `f>0` raises the steepness FLOOR (`130+120f`) with the ceiling
  pinned at 250 (reverse curriculum). **Eval always uses f=0.**
- `is_too_steep()` rejects ~97% of raw maps and the generator **rerolls until it
  passes** (matching the real game, `sketch.js:234`, ~33 rerolls avg) — the gate
  is the *defining filter* of the real game's terrain distribution, not an
  impassability measure. Fixed 2026-06-06 (the old 10-reroll cap leaked
  too-steep maps ~73% of the time); a 1000-reroll safety cap remains for high
  `difficulty`. Originals for diffing: `cb_reference/`.

## Conventions & gotchas (read before changing things)

**Coding conventions live in `CONVENTIONS.md`** (units, angles, Python↔JS
constant sync, magic numbers, …) — read that before editing code. The gotchas
below are project-specific traps.

1. **Use the venv python** (`python/.venv/Scripts/python.exe`).
2. **Per-wheel obs + reward shaping are default-on everywhere** (env, train,
   eval) since the 2026-06-06 CLI cleanup. Env-var overrides:
   `HCR_PER_WHEEL=0` / `HCR_REWARD_SHAPING=0` (legacy 11-dim checkpoints),
   `HCR_DIFFICULTY` (pin f), `HCR_DIFFICULTY_MAX`, `HCR_LOOKAHEAD_N`
   (default 6; 13 for `vision13_a_*`). Old run commands map as:
   `--per-wheel --reward-shaping --reverse-curriculum --rc-fmax-cap 0.0`
   ≡ today's no-flag default; the retired curriculum + SAC trainers live in
   `python/archive/` — **NEVER delete `python/archive/` unless the user
   explicitly says so.**
3. **Default to the `_final` checkpoint; the scan is a collapse detector, not
   a picker.** The decay schedule keeps final ≈ plateau; the argmax of ~41
   noisy 60-ep scan means is mostly luck (inflated ~+100). Snapshot-pick ONLY
   if the scan shows final >150 below the plateau. Cite only 200-ep confirms;
   cross-model claims need the paired A/B on identical tracks (different eval
   protocols generate different track sets even at the same seed!). Full
   protocol: PROJECT_STATUS "Model selection & eval protocol".
4. **Don't modify the physics** (torque, motor on/off, friction) — it breaks
   browser parity, and the locked physics is intentional. **The physics JS is
   single-sourced in `web/`** (`web/{Car,Wheel,Person,Ground}.js` +
   `web/libraries/Box2d.js`): both the deployed site AND the training path use it
   (`js_backend.py` reads `web/…` directly — 2026-07-07 dedup; there is no root
   copy anymore, so an edit can't land in only one place). Edit there.
   **Exception (2026-07-07):** the driver's **torso↔chassis** revolute joint now
   carries an ASYMMETRIC angular limit (`web/Car.js`): `lowerAngle=−70.6°`,
   `upperAngle=+104.5°`. This stops a strong impact from flipping the driver into
   the stable "hanging 180° below the car" pose (a distance joint fixes only
   distance, not side; that flip → head-ground death you can't recover). The limit
   MUST sit inside the upright basin of attraction or the ragdoll just rests
   against the wall in the flip basin (what the first-cut ±90° did). The basin is
   asymmetric because rest is tilted ~−19.7° (anchor offset forward): measured
   flip edges are jointAngle −71.6° (torso tipping forward) / +105.5° (tipping
   back); we take a **1° margin inside each**. The head↔torso (neck) joint has NO
   limit — it doesn't exhibit the flip in practice. (See PROJECT_STATUS for the
   basin measurement.) So the physics is
   **no longer byte-identical to Code Bullet's original** (`cb_reference/` lacks
   the limits). Impact on the AI is nil in practice — the driver is near-massless
   and the limit only engages on rocket-mode-level impacts the policy never
   produces (200-ep seed-42 parity confirm unchanged; see PROJECT_STATUS).
5. **ONNX export:** `export_onnx.py` uses `dynamo=False`, opset 11 — required for
   ONNX Runtime Web 1.18. Don't use the dynamo exporter or threaded WASM.
6. **`web/ai_policy.js`** constants `PPO_PER_WHEEL` / `PPO_REAR_N` /
   `PPO_LOOKAHEAD_N` must match the deployed `web/ai_policy.onnx` (currently
   per-wheel, rear=0, lookahead=6 → 48 stacked).
7. **Reboot before long sessions** — known machine-level memory leak, ~100 MB/h
   (unfixable, do NOT investigate); long runs can hit `WinError 1450`.
8. **Checkpoints regrow fast** (~81 per run). Keep only `_final` + any cited
   snapshot. **Prune ONLY with the user's explicit go-ahead** — report keepers
   vs prunable and wait; when approved: verify keepers, dry-run, delete.
9. **Before long/expensive training runs, restate the exact config (steps,
   flags, seeds, direction) and get sign-off** — a wrong-direction curriculum run
   was wasted once. (See the user-memory `confirm-intent-before-training`.)
10. **Same-seed envs do NOT see the same terrain across runs/instances.**
   `make_ground`'s reroll loop and the grass picks consume the *global*
   `random` stream, so track identity depends on stream position, not the env
   seed (this silently invalidated the old cross-policy consensus analysis).
   To compare policies/attempts on identical tracks, pin them the
   `diagnostics/jitter_probe.py` way: `random.seed(k)` immediately before
   `make_ground(None)`, then inject the Ground via an `env._make_ground` patch.
   **Corollary (2026-06-08): `eval.py --ab` is therefore effectively UNPAIRED at
   f=0** — env_a/env_b reroll off the global stream to different terrain despite
   the same `--seed` (tell: `sd_diff ≈ √2×single-policy-sd ≈ 600`). Its mean test
   is still valid (unpaired), but for TRUE pairing use the pinned-track inject
   method (`python/autorun/best_of_k.py`, `fs8_ab.py`, `multilife_eval.py`).
11. **In THIS repo, "commit" means "commit AND push".** The user is the sole
   editor and this is low-stakes, so when they say commit, push to the remote in
   the same step (don't wait for a separate "push"). Applies only to this project.
   (Only `web/` is a git repo → Vercel; the root is untracked.)

## Current state (2026-06-06)

- **Save-scum backtracking BEATS THE GAME on 30/30 tracks (2026-06-18)** — the one
  test-time lever that broke the chaos ceiling. Go-Explore-style: on death, restore
  a physics snapshot a little back, perturb the action stream, retry; rewind deeper
  if the same wall persists; commit each cleared section; stitch. Reaching the true
  finish (lip + fly-off, score ~1900–1962) it beats **96.7% (29/30) vs Best-of-30
  66.7%** on identical pinned tracks (strictly dominant, +9 tracks, 0 losses); the
  lone holdout fell to a bigger budget → **100% with patience** (no structural hard
  core; the limit is budget/chaos, not skill). It FACTORIZES the per-section survival
  product Best-of-X can't. NOTE: this is a CONSTRUCTED stitched replay, not a better
  policy / legit single-shot number (BC-robustification would likely wash, cf. SIL).
  Harness `python/autorun/backtrack_search.py` (the offline pose-stream export
  `python/autorun/export_replay.py` still exists but the browser no longer ships
  pre-exported replays — the deleted `replays/` folder). `web/index.html` now runs
  the search **live in-browser** via one button: **▶ Watch the AI beat the game
  (or get close)** runs the Go-Explore search on the *current* terrain, then
  ghost-replays the result (flies off the end if it can, else shows the best run
  found). (This replaced the older pinned-track picker + `replays/` ghost-replay /
  "Load & drive".) Memories `backtracking-save-scum-search`,
  `true-score-ceiling-flyoff`.
- **Deployed (2026-06-15):** `python/checkpoints/seed2_resume_11611776_steps.zip`
  → `web/ai_policy.onnx` (same obs/arch as base_a: per-wheel, lookahead 6, rear 0,
  48-dim; drop-in, `web/ai_policy.js` unchanged). A snapshot from the seed2 hold-low
  resume; held-out 500-track paired **+68 vs base_a (1490 vs 1422, p=0.0065)**;
  200-ep seed-42 confirm **1486.4** (vs base_a 1367.5 same protocol — but a
  different track set, so cite the paired +68, not the +119).
  **CAVEAT — this is a snapshot-pick (against gotcha #3):** its neighbors and the
  run's own endpoint WASH vs base_a (12M +23 ns, resume_final +20 ns, 11.2M −51),
  so the +68 may be a lucky local peak of the ±100 per-checkpoint eval wander, not
  a better *model*. Deployed at the user's explicit instruction.
  **Paired re-test 2026-06-16:** deployed vs base_a
  on identical pinned tracks = **+52.6 mean (n.s., p≈0.13)**, completion TIED; a
  +4M reset-high re-anneal from this lineage fell back to base_a's mean (−70 vs
  deployed, p≈0.035). So the snapshot is a real-ish ~+60 mean-DISTANCE peak the
  lineage can't re-reach, but completion is flat ~22-24% across base_a/deployed/
  reanneal — the peak doesn't buy completions. **Revert:** re-export the prior
  champion `python/checkpoints/base_a_8000000_steps.zip` (1367.5, 200-ep seed-42)
  with `export_onnx.py` (the old `.onnx.bak` backups were deleted in the web/
  reorg; older 1312 champion is `ppo_p5_combo_a_6400000`). Terrain gen
  numpy-vectorized (bitwise-identical; parity
  `tests/test_vectorized_ground.py`).
- **The ~1350 ceiling is CHAOS, not missing skill** (`jitter_probe.py`):
  0% early deaths; ±1px spawn jitter spreads the stop point by a median
  ~10,000 px on the same track; 8 jittered attempts complete 67.5% of tracks
  (vs 20% single-attempt, oracle mean ~1799 vs ~1850–1900 track-length cap).
  The limit is per-section survival *probability* in the steep back third.
- **What helped:** per-wheel obs (+~60); LR 3e-4→1e-4 + entropy 0.01→0.003
  decay (+155, anti-degradation — keeps the final at peak).
- **What didn't (all tested; numbers in PROJECT_STATUS):** reverse curriculum,
  easy→normal curriculum + bottleneck-spawn, rear vision, extended forward
  vision (13-sample/30 m: −127 vs matched control), retraining on the corrected
  terrain distribution (wash), deeper/wider nets, no frame-stack, longer
  episodes, 16M steps (pre-decay AND with stretched decay — reaches the SAME eval
  ceiling as the 8M champion, +16±84 paired, completion down; the rising train
  curve is cross-run-uninformative — WITHIN a run eval DOES track training
  reward, r≈0.6–0.9, see PROJECT_STATUS "Train-vs-eval curves"), compressed-decay
  runs <8M (4M −143, 2M −199 paired) and a constant-low resume (`--resume-hold-low`,
  +4M: wash) — **~8M is a saturation knee**: less compute undershoots even with
  matched decay, more saturates (compute-vs-decay study 2026-06-15),
  SAC, γ=0.999 (significantly worse), self-imitation v1
  (BC on lucky stochastic rollouts: wash, demo set self-contradictory),
  cross-seed distillation (chaos artifact), risk-averse death penalty
  (−300/−500 + 4000-tick episodes: −136/−164 paired, completion 24.5%→14/11.5%,
  pace unchanged — on/off motor can't trade speed for survival),
  **multi-life death-markers** (markers-only; lives=6 AND lives=3: lose to free
  Best-of-X — adaptivity competes with chaos-reroll diversity; lives=3 helps
  single-shot only), **RecurrentPPO/LSTM** (full 8M: −447 paired, decisive),
  **frame-stack-8** (−112 paired: more temporal context hurts; 4 is the sweet
  spot), **seed-search** (seeds 2/3 wash: champion is seed-robust), **stochastic
  Best-of-X** (caps ~67% vs deterministic 70%). [autonomous run 2026-06-08;
  details in python/autorun/RUNLOG.md]
  **2026-06-16:** test-time **MPC/search** on the
  frozen policy (the open "planning" lever — chaos defeats foresight at every
  horizon; H=90 hurts 50%→17%), **targeted perturbation** at the death spot (wash
  vs blind jitter), **robustness training** (`--spawn-jitter 1.0`: −148 paired
  single-shot, p≈0.0004), and a **champion+robust ensemble** (no help at matched
  budget; shared ~17% hard core).
  **2026-06-19:** **in-episode "exploration nudge"** (`--nudge-prob`/`--nudge-mag`,
  default-off, parity-safe) — occasional small recoverable chassis velocity kick
  DURING training, grounded-gated, with the death penalty suppressed for ~1s after
  (the "fair" version) so the policy must learn to continue from being knocked off
  its line. Full 8M run at p0.01/mag0.5: **−93.5 paired vs base_a (t=−2.18,
  p≈0.03), completion 21.5%→17.5%** — modestly HURT, same direction as spawn-jitter
  (the in-episode analog). Mechanism: on/off motor can't trade against a
  perturbation, and chaos means perturbed states never recur so there's no
  learnable recovery — perturbation-during-training just dilutes the specialized
  single-shot trajectory. Two independent perturbation-training negatives now;
  a positive config is unlikely (see memory `perturbation-training-hurts`).
- **Best-of-X is the deployed lever; the DEPLOYED model's ceiling is ~82.5%, not
  70%** (the old "70% plateau / flat to K=16" was *base_a*). On 120 pinned tracks
  (`best_of_k.py`, deployed `seed2_resume`): K=8→66.7, K=10→70.0, K=15→79.2,
  K=20→81.7, **K=30→82.5%** — it keeps gaining past K=10. `web/index.html` now does
  **early-stop on completion + default X=15** (raising X is free on solved maps).
  Adaptive allocation reaches 82.5% at avg-10 attempts (`adaptive_bestofx.py`;
  +12.5pp over uniform-10 = oracle) — the campaign lever.
- **Live levers** (the human's 90%-in-5-adaptive gap, now vs the corrected ~82.5%
  Best-of-X ceiling): (1) a TRUE multi-life episode with reward/credit ACROSS
  lives — the ONLY untested policy lever (markers-only saturates; given the
  2026-06-16 negatives, expectations low); (2) ~~planning/search/MPC~~ TESTED
  NEGATIVE 2026-06-16 (chaos defeats foresight); (3) browser adaptive-X — SHIPPED
  (early-stop + X=15); cross-track adaptive allocation analyzed
  (`adaptive_bestofx.py`). The ~17% hard core is shared across policies (a
  structural on/off-motor limit). Physics off-limits. Reusable infra:
  `python/autorun/` (best_of_k, adaptive_bestofx, targeted_perturb, ensemble,
  robust_ab), `planner.py`, `diagnostics/jitter_probe.py`, `tests/test_saverestore.py`.

## Repo map (essentials)

```
web/                                         # the deployable static site (its own git
  index.html                                 #   repo → Vercel). index.html = the old
  ai_policy.js, ai_policy.onnx               #   ai_play.html (PPO in V8; incl. a Bug-
  Car/Wheel/Person/Ground.js, Pics/          #   probe debug panel, see HOW_TO_PLAY §7).
  libraries/{Box2d,ort.min}.js + *.wasm      #   *** SINGLE SOURCE of the physics JS ***
  vercel.json, README.md, HOW_TO_PLAY.md     #   (Box2d/Car/Wheel/Person/Ground) — the
                                             #   training path reads these too. + ORT runtime + deploy docs.
HOW_TO_PLAY.md                               # serve + play/race-the-AI instructions (+ Bug-probe panel)
cb_reference/                                # pristine Code Bullet originals (for diffing; NOT loaded)
legacy_neat/                                 # legacy NEAT-era game (kept, unused by AI):
                                             #   index.html + sketch.js + Genome/Neat/Population/
                                             #   Species/Node/Player/Connection*/World.js. index.html
                                             #   loads the physics from ../web/ and p5 from ../libraries/
analysis_artifacts/                          # one-off diagnostic outputs (trace/bugrun JSON, reward &
                                             #   train-vs-eval PNGs, measure*.html, debug_images/) — not
                                             #   load-bearing; safe to delete
libraries/                                   # p5.{js,dom,sound}.js ONLY (legacy_neat game); the physics
                                             #   Box2d.js now lives solely in web/libraries/
PROJECT_STATUS.md                            # detailed handoff + experiment log
python/
  train.py        # PPO entrypoint; champion recipe is the default (see --help:
                  #   --lookahead-n --gamma --max-steps --lr-final --ent-final ...)
  env.py          # HillClimbEnv (gym); obs build; per-episode difficulty sampling
  js_backend.py   # JSPhysics: PyMiniRacer/V8 wrapper around the JS classes
  ground.py       # terrain gen (numpy-vectorized; difficulty knob, is_too_steep gate)
  p5_noise.py     # exact p5.js noise() port + bitwise-identical noise_array()
  eval.py         # batch / watch / paired-A/B eval
  export_onnx.py  # PPO .zip -> web/ai_policy.onnx (default; dynamo=False, opset 11)
  harvest.py, finetune_sil.py, demos/   # SIL infra (v1 tested: no benefit)
  constants.py    # SCALE, sizes, spawn, GROUND_* (physics params live in JS, not here)
  play.py, renderer.py   # manual driving + pygame renderer
  tests/          # real correctness tests: test_vectorized_ground.py (terrain
                  #   parity), test_saverestore.py (save/restore fidelity) + README
  diagnostics/    # rc_scan.py (scan/confirm), deathmap.py, jitter_probe.py,
                  #   torque_probe.py (localize what torques the chassis),
                  #   analyze_bugrun.py (read the browser Bug-probe JSON exports)
  checkpoints/, tb/, logs/   # logs/ = training run stdout logs (nudge_a*, robust1px_a, _crash, ...)
  archive/        # retired trainers (reverse curriculum, SAC) — NEVER delete
                  #   unless the user explicitly says so (see archive/README.md)
```
(The `legacy_pybox2d/` pre-JS-physics port was deleted 2026-07-07 — it was the sole
remaining consumer of pybox2d and the dead physics-tuning constants. In git history.)
