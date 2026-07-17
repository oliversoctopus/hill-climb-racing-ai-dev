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

### 7. Comment density
- Inline comments explain **why**, in 1–2 lines — not the history of how we got
  here. Relocate long experiment narrative / rationale to `PROJECT_STATUS.md` and
  link to it. Keep enough that intent is clear; cut the storytelling.

### 8. Dead / experimental code
- **Truly dead** (never executed on any live path): **delete** — git history
  (root is versioned as of Tier 0) preserves it.
- **Retired whole approaches**: move to `archive/` (never delete `archive/` without
  an explicit go-ahead). (`legacy_pybox2d/` was such an archive, deleted 2026-07-07
  once it was the only consumer of pybox2d + the dead physics constants.)
- **Still-wired experiments that default OFF** (e.g. nudge, spawn-jitter): keep in
  place behind a clear `# EXPERIMENTAL (off by default)` banner + the enabling flag.
- When an experiment's scaffolding is **entangled with a live function** and can't
  be cleanly moved, **quarantine it in place** with a banner rather than risk a
  deep excision.

### 9. Parity markers
- Where a value is **single-sourced** (obs constants via `policy_meta.json`),
  **delete** stale "must match X" prose — it's now false.
- Where two implementations are **genuinely hand-mirrored** (`env.py._build_obs` ↔
  `ai_policy.js._buildObs` formulas), **enforce with a test**
  (`python/tests/test_obs_parity.py`) and add a short banner pointing at it.
- `cb_reference/` is a frozen diff-baseline; we deliberately diverged from it twice —
  the torso↔chassis joint limit (behavioral) and the 2026-07-17 syntax modernization
  (cosmetic) — so a raw diff against it is now noisy. It is NOT a sync target.

### 11. Logging / debug output
- **No stray `console.log` / `print`** in shipped code paths. Gate any debug output
  behind an explicit flag (boolean / env var), default off.

### 12. Domain landmark constants (score / ceiling numbers)
- **Completion = reaching the last solid vertex** (the launch lip / true end):
  `COMPLETE_PX = GROUND_DISTANCE − GROUND_SMOOTHNESS` (19,185px, score ~1883),
  **single-sourced in `constants.py`** and imported everywhere (browser uses
  `distance − smoothness`). Fixed 2026-07-07: the old soft lines `−950`→1790 and
  `−350`→1850 under-counted the track and are retired. **Pre-fix completion %s are NOT
  comparable** to post-fix ones (the new line is stricter).
- **Docs**: one "Score landmarks & ceilings" glossary (PROJECT_STATUS.md, linked from
  CLAUDE.md) pins each number to meaning/model/metric — completion ~1883, fly-off
  ~1900–1962, mean ceilings ~1350 base_a / ~1410 pinned, Best-of-X completion (per model,
  measured against the OLD line). Never use them interchangeably.

### 3. Sign / coordinate helpers (decided Tier 4 = A)
- World space is **y-DOWN** (larger y = lower on screen), which makes
  clearance/altitude sign errors easy to introduce. The sign conventions live in
  **named helpers** in one place (`web/game/geom.js`): `altitudeAbove(groundY, pointY)`
  (positive = above ground) and `isBelowKillLine(yPx)` (fell off the world). Touched
  code uses these instead of bare subtractions.

### 10. JS naming style (decided Tier 4 = A)
- **Codify the existing style; don't churn** as part of a *structural* change — keep
  modernization to its own isolated, separately-verified commit so any regression is
  unambiguously cosmetic, not structural. **Done 2026-07-07:** `web/game/` modernized
  (AST-based `lebab`: `var`→`const`/`let`, arrow callbacks where `this`-safe, template
  literals) AFTER the Tier 4 split shipped. **Done 2026-07-17:** the physics classes
  `web/{Car,Wheel,Person,Ground}.js` modernized the same way (`var`→`const`/`let` inside
  methods + a few no-op bare `this.field;` statements removed, `;;` cleaned, `&&`-guard →
  `?.` in `Car.destroy`). Then a **cleanup sweep** for what the earlier
  passes missed: `web/ai_policy.js` (never lebab'd before — `var`→`const`/`let` + template
  literals; outer IIFE and `this`-free methods arrowed); the reused sibling-loop
  `var i`/`var pi`/`var vect` lebab conservatively left in `Car`/`Ground`/`render`/`sim`
  (safe — each loop gets its own block-scoped binding, none captured in a closure); and a
  broader lebab transform set (`obj-shorthand`, `obj-method`, remaining `template`) the
  first `web/game/` pass didn't run — e.g. `{ actions: actions }`→`{ actions }`,
  `{ GetPosition: function(){…} }`→`{ GetPosition(){…} }`. `node --check` passes on all 16
  non-vendored files; remaining `var`s are all vendored (`libraries/`) or in comments.
  **Left intentionally:** loose equality (`==`/`!=`) — it's valid, consistent, and some
  cases (`x != null`) are the null-AND-undefined idiom that would change behavior if
  tightened; not worth churning parity code for zero functional gain. Verified each round:
  full parity suite (obs bit-exact, `max|py-js|=0`), `game/` import-link harness, and
  deterministic eval unchanged at 1495.
- **Two hard constraints that survive modernization** (do NOT "modernize" past these):
  1. The p5/Box2D **compat-shim block in `web/index.html` must keep its top-level
     declarations as `var`/`function`** — a top-level `var`/`function` in a classic script
     becomes a `window` property (which the physics classes and the `window.HCR` bridge
     read); top-level `let`/`const`/`class` do **not** attach to `window`. So that block is
     off-limits to `var`→`const` churn.
  2. The physics class files must stay **classic scripts** (no `import`/`export`): they're
     `eval`'d into V8 for training (`js_backend.py`), which has no module loader and no
     `window`, and loaded by `legacy_neat/` via plain `<script>`. Their *internals* are
     free to use modern syntax — V8 8.9 (PyMiniRacer's bundle) supports everything through
     ES2020 — which is why the 2026-07-17 pass was safe.

### 13. Line endings (decided = A)
- **`.gitattributes` normalizes all text to LF** in the repo AND on checkout
  (`* text=auto eol=lf`), in both the root and `web/` repos; binary assets excluded.
  The working tree is already LF; this pins it so `core.autocrlf=true` can't flip files
  to CRLF. Silences the "LF will be replaced by CRLF" warnings.

---

## Deferred

- *(none — all conventions decided as of the 2026-07-07 refactor)*
