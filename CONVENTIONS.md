# CONVENTIONS.md — Hill Climb Racing AI

Durable coding conventions, decided during the 2026-07-07 understandability
refactor. **These apply to NEW and TOUCHED code** — they are not a mandate to
rewrite untouched legacy. When you touch a file, bring the touched code up to
these. Referenced from CLAUDE.md.

---

## Decided

### 1. Spatial units — meters internal
- **Meters are the single internal unit** for positions, velocities, lengths.
  Convert to pixels ONLY at render / UI boundaries.
- Variables holding **pixels** (UI, score, legacy paths) MUST carry a `_px`
  suffix. Meter variables may carry `_m` when the unit isn't obvious from
  immediate context.
- `SCALE = 30 px/m` is the only conversion factor.
- Legacy pixel paths not yet touched (e.g. the score / `_max_dist_px` machinery
  in `env.py`) are grandfathered; convert them only when a change touches them,
  and suffix `_px` at that point.

### 2. Angles — radians internal
- Store and compute angles in **radians**. Suffix `_deg` and convert only for
  display / human-facing output.

### 4. Python ↔ JS constant sync — generated JSON is the single source
- Obs encoding + policy topology constants are defined ONCE in
  `python/obs_spec.py`.
- `export_onnx.py` emits `web/policy_meta.json` from `obs_spec` alongside the
  ONNX model.
- `web/ai_policy.js` **loads its running values from `policy_meta.json`** at
  init — it does not keep its own authoritative copy.
- A **fail-closed validation layer** guards a bad/missing JSON:
  - structural: all required keys present, correct types;
  - semantic: `input_width == n_obs * n_stack`, values in sane ranges;
  - model check: a dummy inference of the declared width against the loaded
    ONNX session.
  - Any failure **throws loudly at init** (does not silently run on defaults).

### 6. Magic numbers
- **No bare magic number in logic** for normalization / cross-referenced /
  derived values — give it a named constant with a one-line derivation comment,
  in the nearest spec module.
- Purely local one-off literals may stay inline if commented.

### 5. Config & env-var overrides
- The `HCR_*` env-var overrides exist so `SubprocVecEnv` worker processes inherit
  config without pickling it through the process boundary. Keep them.
- Define the env config surface **once as a dataclass** (`EnvConfig` in `env.py`)
  — each field's env-var name, default, cast, and clamp live in one table, not in
  per-field `try/except` blocks.
- **Precedence: env-var WINS** over the constructor kwarg (this is what makes the
  subprocess mechanism work). To keep that from being a silent foot-gun, an
  override is **logged** at construction: whenever an env var changes a field away
  from the value the caller passed (or the default), print one concise line. No
  log when the env var matches what the value would have been anyway.

---

## Deferred (decide when we reach the relevant tier — Claude will re-surface these)

- **#3** sign/coordinate helper conventions (y-down, clearance/altitude)
- **#7** comment density (trim inline "why"; relocate experiment history to PROJECT_STATUS)
- **#8** dead / experimental code handling (delete vs archive vs banner+flag)
- **#9** parity markers for hand-mirrored code
- **#10** JS naming style (touched code only)
- **#11** logging / debug output gating
- **#12** domain landmark constants (the conflated score numbers)
- **#13** `.gitattributes` line-ending normalization
