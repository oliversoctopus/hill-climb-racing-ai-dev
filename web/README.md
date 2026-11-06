# Hill Climb Racing AI — Web

A browser build of a Hill Climb Racing AI: a PPO policy (exported to ONNX) that drives a 2-wheeled car over procedurally-generated hills, maximizing forward distance. You can watch it drive, race it yourself, or watch its Go-Explore "save-scum" search try to beat the game.

Everything runs client-side — the real JS game physics (`Box2d.js` + `Car.js` + `Wheel.js` + `Person.js` + `Ground.js`) plus the PPO policy running in-browser via [ONNX Runtime Web](https://onnxruntime.ai/). No backend.

**Live site:** _(add your Vercel URL here)_

## Play / develop locally

ONNX Runtime Web can't load the model over `file://`, so serve the folder over HTTP:

```bash
# from this folder
python -m http.server 8765
# then open http://localhost:8765/
```

See **[HOW_TO_PLAY.md](HOW_TO_PLAY.md)** for modes, controls, and the "watch the AI beat the game" feature.

## Deployment (Vercel)

Static site — no build step.

- **Framework Preset:** Other
- **Build Command:** _(none)_
- **Output Directory:** `.`
- **Root Directory:** this folder (`web`) if the repo has it nested

`vercel.json` sets the `application/wasm` Content-Type so ONNX Runtime's wasm loads correctly.

## Files

| Path | Role |
|---|---|
| `index.html` | The entire app (rendering, modes, AI/human driving, backtrack search) |
| `ai_policy.js` | PPO-in-JS inference wrapper around the ONNX model |
| `ai_policy.onnx` | Deployed policy weights |
| `Car.js` `Wheel.js` `Person.js` `Ground.js` | Unmodified JS game physics |
| `libraries/Box2d.js` | Box2D physics engine |
| `libraries/ort.min.js` + `*.wasm` | ONNX Runtime Web |
| `Pics/` | Sprites (car, wheels, heads, grass, sky) |

> The Python training pipeline (Stable-Baselines3 PPO, terrain generation, eval, ONNX export) lives in a separate project and is intentionally **not** part of this deployment repo. This repo is the production website only.
