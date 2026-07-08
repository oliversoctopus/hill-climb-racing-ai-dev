# Hill Climb Racing AI

A PPO agent that drives a 2-wheeled car over procedurally-generated hilly terrain,
maximizing forward distance. It trains in Python (Stable-Baselines3) and deploys to the
browser via ONNX. **The physics is the unmodified Code Bullet JS game** (`Box2d.js` +
`Wheel/Person/Car/Ground.js`) run inside V8 (PyMiniRacer) for *both* training and the
browser, so the two match exactly.

Live site: deployed from `web/` to Vercel.

## Where to look

| File | What |
|---|---|
| **`CLAUDE.md`** | Durable "how it works / how to work in this repo" — **start here.** |
| **`CONVENTIONS.md`** | Coding conventions (units, angles, Python↔JS sync, config, …). Read before editing code. |
| **`PROJECT_STATUS.md`** | Detailed handoff + reverse-chronological experiment log + score-landmark glossary. |
| `web/HOW_TO_PLAY.md` | How to serve and play / race the AI in the browser. |

## Quickstart

All Python runs use the venv interpreter `python/.venv/Scripts/python.exe` (Windows,
Python 3.13). Defaults in `train.py` **are** the champion recipe.

```powershell
# Train (~65 min):
python\.venv\Scripts\python.exe python\train.py --timesteps 8000000 --seed 1 --name my_run

# Evaluate (headless batch):
python\.venv\Scripts\python.exe python\eval.py <ckpt.zip> --batch --episodes 200 --random-terrain --deterministic

# Export a checkpoint to the browser (writes web/ai_policy.onnx + web/policy_meta.json):
python\.venv\Scripts\python.exe python\export_onnx.py <ckpt.zip>

# Serve the browser build (ORT can't load over file://), then open http://localhost:8765/
python\.venv\Scripts\python.exe -m http.server 8765 --directory web

# Tests:
python\.venv\Scripts\python.exe python\tests\test_vectorized_ground.py
python\.venv\Scripts\python.exe python\tests\test_obs_parity.py
python\.venv\Scripts\python.exe python\tests\test_saverestore.py
```

## Repo structure (two git repos)

- **`web/`** is its own git repo → pushed to GitHub → deployed by Vercel. It is the
  **single source of the physics JS** (`Car/Wheel/Person/Ground.js` + `libraries/Box2d.js`);
  the Python training path reads those files directly.
- The **repo root** is a separate, **local-only** git repo tracking `python/` + the docs.
  (`web/` is gitignored by the root repo so the two don't interfere.)

See CLAUDE.md "Repo map (essentials)" for the full layout.
