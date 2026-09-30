# CONVENTIONS.md — Hill Climb Racing AI

Coding conventions for this repo. They apply to new and touched code: when you touch a file, bring the touched code up to them, and leave untouched code alone. Code cites these rules by number, so keep the numbers stable.

## 1. Spatial units — meters internal

- Meters are the single internal unit for positions, velocities and lengths. Convert to pixels only at render and UI boundaries.
- Variables holding pixels (UI, score, legacy paths) carry a `_px` suffix. Meter variables may carry `_m` when the unit isn't obvious from context.
- `SCALE = 30 px/m` is the only conversion factor.
- Untouched legacy pixel paths (e.g. the score / `_max_dist_px` machinery in `env.py`) are grandfathered; convert them and add `_px` when a change touches them.

## 2. Angles — radians internal

- Store and compute angles in radians. Suffix `_deg` and convert only for display.

## 3. Sign / coordinate helpers

- World space is y-down (larger y = lower on screen), which makes clearance and altitude sign errors easy. The sign conventions live in named helpers in `web/game/geom.js`: `altitudeAbove(groundY, pointY)` (positive = above ground) and `isBelowKillLine(yPx)` (fell off the world). Touched code uses these instead of bare subtractions.

## 4. Python ↔ JS constant sync — generated JSON is the single source

- Obs encoding and policy topology constants are defined once, in `python/obs_spec.py`.
- `export_onnx.py` emits `web/policy_meta.json` from `obs_spec` alongside the ONNX model.
- `web/ai_policy.js` loads its values from `policy_meta.json` at init and keeps no authoritative copy.
- A fail-closed validation layer guards a bad or missing JSON, and any failure throws at init instead of running on defaults:
  - structural: all required keys present, correct types;
  - semantic: `input_width == n_obs * n_stack`, values in sane ranges;
  - model: a dummy inference of the declared width against the loaded ONNX session.

## 5. Config & env-var overrides

- The `HCR_*` env-var overrides let `SubprocVecEnv` workers inherit config without pickling it across the process boundary. Keep them.
- The env config surface is defined once, as the `EnvConfig` dataclass in `env.py`: each field's env-var name, default, cast and clamp in one table.
- Precedence: the env var wins over the constructor kwarg; the subprocess mechanism depends on it. Whenever an env var changes a field away from what the caller passed (or the default), log one concise line at construction; stay silent when they agree.

## 6. Magic numbers

- No bare magic number in logic for normalization, cross-referenced or derived values. Give it a named constant with a one-line derivation comment in the nearest spec module.
- Purely local one-off literals may stay inline if commented.

## 7. Comments

- A comment explains a non-obvious why (a constraint, a reason, a trap) in 1–2 lines. A file header says what the module is in a few lines.
- No history of how the code got here, no dates, no experiment results or measured figures, and no restating what the code does. Those go in git or `PROJECT_STATUS.md`; if a decision needs defending, one line names the section.

## 8. Dead / experimental code

- Dead code (never executed on any live path) is deleted; git history preserves it.
- Retired whole approaches move to `archive/`. Never delete `archive/` without an explicit go-ahead.
- Still-wired experiments that default off (e.g. nudge, spawn-jitter) stay in place behind a `# EXPERIMENTAL (off by default)` banner and their enabling flag.
- When an experiment's scaffolding is entangled with a live function and can't be cleanly moved, quarantine it in place with a banner instead of risking a deep excision.

## 9. Parity markers

- Where a value is single-sourced (obs constants via `policy_meta.json`), delete "must match X" prose; it is false.
- Where two implementations are hand-mirrored (`env.py` `_build_obs` ↔ `ai_policy.js` `_buildObs`), enforce it with a test (`python/tests/test_obs_parity.py`) and add a short banner pointing at it.
- `cb_reference/` is a frozen diff baseline, not a sync target. The live physics diverges from it (the torso↔chassis joint limit and syntax modernization), so a raw diff is noisy.

## 10. JS style

- Codify the existing style; don't churn. Modernization goes in its own separately verified commit, never mixed with a structural change, so any regression is unambiguously cosmetic.
- Leave loose equality (`==`/`!=`) alone: `x != null` is the null-and-undefined idiom, and tightening it changes behavior.
- Two hard constraints:
  1. The p5/Box2D compat-shim block in `web/index.html` keeps its top-level declarations as `var`/`function`. In a classic script those become `window` properties, which the physics classes and the `window.HCR` bridge read; top-level `let`/`const`/`class` do not.
  2. The physics class files stay classic scripts (no `import`/`export`). They are `eval`'d into V8 for training (`js_backend.py`), which has no module loader and no `window`, and loaded by `legacy_neat/` via plain `<script>`. Their internals may use modern syntax up to ES2020 (PyMiniRacer bundles V8 8.9).

## 11. Logging / debug output

- No stray `console.log` / `print` in shipped code paths. Gate debug output behind an explicit flag (boolean or env var), default off.

## 12. Domain landmark constants (score / ceiling numbers)

- Completion is reaching the last solid vertex (the launch lip): `COMPLETE_PX = GROUND_DISTANCE − GROUND_SMOOTHNESS`, single-sourced in `constants.py` and imported everywhere (browser: `distance − smoothness`).
- Completion rates recorded against the retired soft lines (score 1790 and 1850) are not comparable to ones measured against `COMPLETE_PX`.
- The landmark and ceiling numbers are defined once, in the PROJECT_STATUS *Score landmarks & ceilings* glossary, each pinned to its meaning, model and metric. Never use them interchangeably.

## 13. Line endings

- `.gitattributes` normalizes all text to LF in the repo and on checkout (`* text=auto eol=lf`), in both the root and `web/` repos; binary assets are excluded. This keeps `core.autocrlf=true` from flipping files to CRLF.

## 14. Markdown

- Markdown is one line per paragraph, list item or blockquote; editors and renderers wrap it. Python stays hard-wrapped. `python/unwrap_md.py` checks, and `--write` converts.
