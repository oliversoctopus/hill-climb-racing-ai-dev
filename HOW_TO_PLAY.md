# How to Play — Browser Game (you vs. the AI)

The whole site lives in the **`web/`** folder (its own git repo, deployed to
Vercel). Everything runs in `web/index.html`: the AI (PPO via ONNX), human
keyboard driving, and a head-to-head race mode. The only setup needed is a local
web server — ONNX Runtime Web **cannot load the model over `file://`**, so
double-clicking the HTML file will not work.

## 1. Start the server

From the repo root (`C:\Users\olive\Projects\Hill-Climb-Racing-AI`), serve the
`web/` folder:

```powershell
python\.venv\Scripts\python.exe -m http.server 8765 --directory web
```

Leave that window open. (Any static file server works; this is just the
easiest one already installed. On the deployed Vercel site, just open the URL.)

## 2. Open the page

Go to **http://localhost:8765/** in your browser (or the deployed URL).

Wait for the status line to change from "Loading model + physics..." to
**"Ready — ..."**. The sim starts immediately in *AI only* mode.

## 3. Pick a mode

Use the **Mode** dropdown under the canvas:

| Mode | What it does |
|---|---|
| **AI only** | Watch the deployed model (`ai_policy.onnx`) drive. |
| **Human only** | You drive. No AI car. |
| **Human vs AI** | Both cars spawn on the same terrain and race. You are the **orange** car, the AI is **blue**. |
| **Human vs Human (split)** | Two humans race on the **same** terrain. The canvas widens to **two full screens side-by-side** (best on a large monitor). **Left screen** = **P1**, **orange** car, **WASD**. **Right screen** = **P2**, **green** car, **arrow keys**. Each screen follows its own car and shows both scores — yours top-left, your opponent's top-right — so you can spot who's ahead. When both cars are dead the **higher score wins**. |
| **Best of X (AI)** | Runs the AI X times on one shared map (with tiny spawn jitter so attempts diverge), then lets you replay any attempt ranked best→worst. |

Switching modes rebuilds the world with fresh terrain.

## 4. Controls (human driving)

- **→ (Right arrow)** — motor forward
- **← (Left arrow)** — motor reverse
- **Nothing held** — motor off (coast)

In **Human vs Human (split)** mode the left car uses **WASD** instead: **D** (or
**W**) = forward, **A** (or **S**) = reverse. The right car keeps the arrow keys.

That's the entire action space — it's on/off only, exactly what the AI has.
No brakes, no throttle scaling.

Other buttons:

- **↺ Restart (same terrain)** — puts the car(s) back at the start of the
  *current* map, no new terrain. This is what you click after the "DEAD — click
  Reset" overlay if you want another go at the same hills.
- **🎲 Regenerate terrain** — throws away the current map and generates a
  brand-new random one, respawning everyone.
- **Pause / Resume** — freezes the sim.
- **Speed (1x–8x)** — simulation speed multiplier (handy for watching the AI;
  for racing, stay on 1x).
- **Terrains** — a dropdown of every map generated this session; pick one to
  re-load it (Restart re-drives it, Regenerate makes a fresh one).
- **⌨ Keybinds** — pops up the keyboard-shortcut cheat sheet.
- **▶ Watch the AI beat the game (or get close)** — runs the Go-Explore
  save-scum backtracking search on the *current* terrain, then replays the run
  as a ghost: it flies off the end if it can, otherwise it shows the best run it
  found. "Replaying run…" appears next to the button while the replay plays.

Keyboard shortcuts (also on the **⌨ Keybinds** button): **I** invincible,
**Z** Zero-G (toggle), **F** float the car(s) up, **H** altimeter, **V** speed
meter, **R** Restart (same terrain), **T** Regenerate terrain, **P** Pause/Resume,
**Esc** close the cheat sheet.

## 5. Racing the AI (Human vs AI mode)

- Both cars run on the **same terrain** and the same physics, in the same
  world (they don't collide with each other — wheels/chassis only interact
  with the ground).
- Terrain is generated exactly like the real Code Bullet game (same noise, same
  steepness filter — fixed 2026-06-06), so the hills should feel identical to
  thebigcb.com.
- The HUD shows each player's max distance and **score** (= distance px ÷ 10).
  The AI's deployed model averages ~**1370** (median ~1420) on this terrain;
  the track caps out around ~**1850–1900**.
- You **die** when your driver's head touches the ground or you fall off the
  bottom of the screen. The AI additionally dies if it makes no progress for
  ~17 seconds (matching its training); you are never timed out.
- The camera follows **you** while you're alive; when you die it switches to
  the AI so you can watch whether it beats your distance. When everyone is
  dead, click **↺ Restart (same terrain)** to race the same hills again, or
  **🎲 Regenerate terrain** for a fresh map.

Tip: the AI's whole skill is rhythm — pulsing the motor on/off to keep the
nose level on landings and to crawl up steep faces without flipping. Tapping
**←** mid-air pitches the nose up; tapping **→** pitches it down.

## 6. Best of X (optional)

Select *Best of X (AI)*, set the number of attempts, click **Run**. The AI
plays X attempts headless (no rendering) on one fixed map, then the results
dropdown lets you **Watch** any attempt, ranked from best to worst. **🎲
Regenerate terrain** re-rolls the shared map and clears old runs.

## 7. Bug probe (debug panel)

Below the main controls is a **✨ Cheats** row and a **🐞 Bug probe** panel. The
**cheats** — Invincible, Zero-G + Float, Altimeter, Speed, and the physics/motor
knobs — apply to **every car on screen, the AI included, in all modes** (even
AI-only). The **recorder / Flag / Download** tools still log the **human** car, so
for *recording* use **Mode: Human only**. Nothing here persists or touches the
source physics — it's all runtime, so AI/browser parity and the deployed model
are unaffected (no retrain implied).

- **Recorder (always on):** every tick the human car's full state is logged
  (chassis pose + angular velocity, per-wheel motor/spin/on-ground, the motor-joint
  and suspension reaction torques, keys/action, and the flags below). The live
  `angVel … angle …` readout shows the current chassis spin.
- **Invincible:** skips every death path — head-touches-ground (which also splits
  the car), falling off the bottom, **and the AI's no-progress timeout** — so no
  car ends its run while you experiment.
- **Zero-G + Float:** turns gravity off and lifts the car(s) into open air,
  **preserving linear and angular velocity** (so a developing spin keeps
  going). With no gravity and no ground, any spin that grows is a pure
  joint/solver artifact. The camera follows the car vertically as it drifts.
  Pressing **Zero-G** again restores gravity.
- **Altimeter (H) / Speed meter (V):** on-screen readouts for the focused car —
  height above the ground (m) and speed as **H**orizontal / **V**ertical / **Tot**al
  (m/s; vertical is positive upward). Speed is the car's whole-vehicle
  center-of-mass velocity, so spinning or flipping doesn't inflate it. They sit
  top-center; when both are on, altitude is on top and speed just below. In
  Human-vs-Human split mode each screen shows its own player's meters.
- **⚑ Flag reproduced:** marks the current tick so the moment is easy to find.
- **Download recording:** exports `hcr_bugrun_*.json` (ticks + flags + terrain +
  the active physics knobs). Analyse it with
  `python\.venv\Scripts\python.exe python\diagnostics\analyze_bugrun.py <file>`.
- **Physics knobs (live, runtime-only):** chassis/wheel angular damping,
  suspension spring freq/damp, **motor speed×**, **motor torque×**, and wheel
  friction. **Apply** pushes the values; **Reset** restores stock. Two presets:
  **🔥 Unmask** (strip damping → exposes a suspension-resonance instability) and
  **🌀 Motor-spin** (motor speed ×2 → the chassis winds into a sustained
  counter-spin while driving — motor *speed*, not torque/friction, is that lever).

## Troubleshooting

| Symptom | Fix |
|---|---|
| "ERROR loading agent" / model never loads | You opened the file directly (`file://`) or the server isn't running. Use http://localhost:8765/ (or the deployed URL). |
| Page loads but sprites missing | Server started from the wrong directory — point it at `web/` (`--directory web`) so `Pics/`, `libraries/`, and `ai_policy.onnx` resolve. |
| Just deployed a new model but behavior unchanged | Hard-refresh (**Ctrl+Shift+R**) — the browser caches `ai_policy.onnx` and `ai_policy.js`. |
| Port 8765 already in use | Pick another port (`-m http.server 8766`) and adjust the URL. |
| Arrow keys scroll the page instead of driving | Click the page/canvas once so it has keyboard focus. |
