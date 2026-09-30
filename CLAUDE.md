# CLAUDE.md — Hill Climb Racing AI

Rules and pointers for working in this repo. `PROJECT_STATUS.md` holds results, the experiment log and the reasoning behind these rules; `CONVENTIONS.md` holds the coding conventions.

## What this is

A PPO policy drives a 2-wheeled car over procedurally generated hills, maximizing forward distance. It trains in Python (Stable-Baselines3) and runs in the browser via ONNX.

The physics is Code Bullet's JS game (`Box2d.js`, `Wheel.js`, `Person.js`, `Car.js`) run inside V8 via PyMiniRacer, for training and deployment alike, so both run the same physics. They are not bit-identical: rounding differences make a browser run diverge in Python within seconds (PROJECT_STATUS *Human-run recorder*). Do not restore pybox2d: its solver drifts where `Box2d.js` does not (PROJECT_STATUS *Physics history*).

## Architecture

```
Training:  python/train.py (PPO, SubprocVecEnv ×8, VecFrameStack ×4)
  → python/env.py (gym.Env)
    → python/js_backend.py (V8): loads web/libraries/Box2d.js + web/{Wheel,Person,Car}.js
    → python/ground.py terrain via python/p5_noise.py (p5.js noise port)
      → vertex list handed to JS via build_world(); JS steps Box2D, returns obs JSON

Browser:   web/index.html → web/libraries/ort.min.js + web/ai_policy.onnx
           + web/ai_policy.js + the same physics JS
```

`web/` is the deployable static site and its own git repo (GitHub → Vercel). The physics JS lives only in `web/`; `js_backend.py` reads it from there.

## Running things

All dependencies are in `python/.venv` (Python 3.13, Windows); the system `python` lacks them.

```powershell
# Train (defaults are the champion recipe; ~65 min):
python\.venv\Scripts\python.exe python\train.py --timesteps 8000000 --seed 1 --name my_run

# Collapse scan, then a 200-ep confirm of the final:
python\.venv\Scripts\python.exe python\diagnostics\rc_scan.py my_run --min-step 4000000 --episodes 60
python\.venv\Scripts\python.exe python\diagnostics\rc_scan.py x --confirm python\checkpoints\my_run_final.zip --episodes 200 --seed 42

# Batch eval:
python\.venv\Scripts\python.exe python\eval.py <ckpt.zip> --batch --episodes 200 --random-terrain --deterministic

# Export to web/ai_policy.onnx (then hard-refresh the page):
python\.venv\Scripts\python.exe python\export_onnx.py <ckpt.zip>

# Browser (ORT can't load over file://):
python\.venv\Scripts\python.exe -m http.server 8765 --directory web   # http://localhost:8765/

# Every test and doc check; run before finishing any change (python/tests/README.md):
python\.venv\Scripts\python.exe python\tests\run.py
```

## Model, observation, reward

- **Obs:** 12-dim per wheel: chassis angle, rear-grounded, front-grounded, angular velocity, vx, vy, and 6 ground-clearance samples ahead, 75 px apart (`--lookahead-n` / `HCR_LOOKAHEAD_N`). `VecFrameStack(4)` makes a 48-dim input. MLP 256×256 for pi and vf.
- **Action:** `Discrete(3)`: forward, reverse, off. The motor is on/off only.
- **Reward:** `max(0, Δx_m)` per tick, plus shaping (on by default): +0.01 per tick survived, −50 on death.
- **Score** (the eval metric) = `(max_dist_px − spawn_x)/10`, uncapped. **Completion** is reaching the last solid vertex, `COMPLETE_PX` in `constants.py` (browser: `distance − smoothness`). Beating the game is reaching that lip and flying off into the void. Episodes end only on death or truncation. The landmark scores are in PROJECT_STATUS *Score landmarks & ceilings*; never use them interchangeably.
- Rear samples exist but are off (`obs_spec.REAR_N = 0`).

## Terrain

- `ground.randomize(difficulty=f)`, `f ∈ [0, 1]`. `f = 0` is the real game's distribution; `f > 0` raises the steepness floor. **Eval always uses `f = 0`.**
- `is_too_steep()` rejects most raw maps and the generator rerolls until one passes, as the real game does (`sketch.js` in `cb_reference/`). The gate defines the distribution; it does not measure passability.

## Rules and gotchas

- **Use the venv python.**
- **Per-wheel obs and reward shaping are on by default** in env, train and eval. Env-var overrides: `HCR_PER_WHEEL=0` and `HCR_REWARD_SHAPING=0` for legacy 11-dim checkpoints, `HCR_DIFFICULTY`, `HCR_DIFFICULTY_MAX`, `HCR_LOOKAHEAD_N`. **Never delete `python/archive/`** unless the user says so.
- **Default to the `_final` checkpoint.** The scan detects collapse; it does not pick a model, because the argmax of noisy 60-ep means is inflated. Snapshot-pick only if the final sits more than 150 below the plateau. Cite only 200-ep confirms. Cross-model claims need a paired A/B on identical tracks (PROJECT_STATUS *Model selection & eval protocol*).
- **Don't modify the physics** (torque, motor, friction); it breaks browser parity. Edit physics JS only in `web/`. The physics files must stay classic scripts, since V8 has no module loader or `window`; `web/game/` reaches them through the `window.HCR` bridge. Known divergences from `cb_reference/`: an asymmetric torso↔chassis joint limit in `web/Car.js` (the limits must sit inside the upright basin; PROJECT_STATUS *Driver ragdoll joint limits*) and cosmetic syntax modernization. The Physics playground (`web/game/tune.js`) is browser-only and gated on "knob modified", so a stock browser sim stays bit-identical; training never loads it. `Box2d.js` polyfills `Object.defineProperty` with get/set only and ignores `value`.
- **ONNX export** uses `dynamo=False`, opset 11, for ONNX Runtime Web 1.18. No dynamo exporter, no threaded WASM.
- **Obs encoding is single-sourced** in `python/obs_spec.py`. `export_onnx.py` writes `web/policy_meta.json`, which `web/ai_policy.js` loads and validates fail-closed. `test_obs_parity.py` checks `ai_policy.js` `_buildObs` against `env.py` `_build_obs`.
- **Checkpoints regrow fast.** Keep `_final` and any cited snapshot. Prune only with the user's go-ahead: report keepers and prunable, wait, then verify keepers, dry-run, delete.
- **Before a long training run, restate the exact config** (steps, flags, seeds, direction) and get sign-off.
- **Same-seed envs do not see the same terrain.** `make_ground`'s reroll loop consumes the global `random` stream, so track identity depends on stream position. `eval.py --ab` is therefore unpaired at `f = 0`. To pair, pin tracks with `random.seed(k)` right before `make_ground(None)` and inject the Ground through an `env._make_ground` patch, as `diagnostics/jitter_probe.py` and `autorun/best_of_k.py` do.
- **Two repos. "Commit" means commit and push.** `web/` pushes to GitHub → Vercel. The root is local-only and tracks `python/` and docs; it ignores `web/`, checkpoints, tb, logs and result artifacts (`*.npz`, `backtrack_runs/`). Ignored results are not recoverable from git, so don't overwrite them. A change spanning both is one commit in each.
- **Check PROJECT_STATUS *TL;DR* before proposing an experiment.** Most ideas have been tested negative.

## Current state

- **Deployed:** `python/checkpoints/seed2_resume_11611776_steps.zip` → `web/ai_policy.onnx`. It is a snapshot-pick, deployed at the user's instruction. To revert, re-export `python/checkpoints/base_a_8000000_steps.zip`.
- **Browser:** Best-of-X with early stop (default X = 15), and **▶ Watch the AI beat this map**, which runs the save-scum backtracking search (`python/autorun/backtrack_search.py`) live on the current terrain and replays the result.
- **Human runs:** with dev mode unlocked, every human run is recorded to IndexedDB (per tick: raw chassis state, wheel contacts, action; plus the terrain) and downloaded with **💾 Save runs**; the Dev section lists them for deleting one by one. Runs that change the physics (any cheat but slow-mo and reverse controls, the playground, quick-load, frame-step) are dropped, as are abandons under 3 s. Build obs from the recorded state with `env._build_obs`; replaying the actions through `js_backend.py` drifts.
- Results, the tested-negative list and open levers: PROJECT_STATUS *TL;DR*.

## Repo map

```
web/                   deployable site (own repo). index.html = markup + p5/Box2D compat
  game/*.js            shim + window.HCR bridge + game/main.js (ES modules: sim, render,
                       search, records, tune = playground, dev = password-gated dev mode,
                       humanruns = dev-mode recorder of your own runs)
  Car/Wheel/Person/Ground.js, libraries/Box2d.js   the only copy of the physics
  ai_policy.js, ai_policy.onnx, policy_meta.json
python/
  train.py, env.py, js_backend.py, ground.py, p5_noise.py, obs_spec.py, constants.py
  eval.py, export_onnx.py, play.py, renderer.py
  tests/               correctness tests (terrain parity, save/restore, obs parity)
  diagnostics/         rc_scan, deathmap, jitter_probe, torque_probe, analyze_bugrun, ...
  autorun/             best_of_k, adaptive_bestofx, robust_ab, backtrack_search, ...
  archive/             retired trainers (never delete)
  checkpoints/, tb/, logs/
cb_reference/          Code Bullet originals, for diffing only
legacy_neat/           the old NEAT game; loads physics from ../web/, p5 from ../libraries/
analysis_artifacts/    one-off diagnostic outputs; not load-bearing
PROJECT_STATUS.md      results, experiment log, reasoning
CONVENTIONS.md         coding conventions
HOW_TO_PLAY.md         serving and playing the browser game
```
