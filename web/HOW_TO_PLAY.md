# How to Play — Browser Game (you vs. the AI)

Everything runs in `index.html`: the AI (PPO via ONNX), human keyboard driving, and a head-to-head race mode. The only setup needed is a local web server, because ONNX Runtime Web **cannot load the model over `file://`**, so double-clicking the HTML file will not work.

On the deployed site, open the URL and skip to step 3.

## 1. Start the server (local only)

From this folder:

```bash
python -m http.server 8765
```

Leave that window open. (Any static file server works.)

## 2. Open the page

Go to **http://localhost:8765/** in your browser (or the deployed URL).

Wait for the status line to change from "Loading model + physics..." to **"Ready — ..."**. The sim starts immediately in *AI drives* mode.

## 3. Pick a mode

Use the **mode tabs** in the top bar (or **Alt+1…5**):

| Mode | What it does |
|---|---|
| **AI drives** | Watch the deployed model (`ai_policy.onnx`) drive. |
| **You drive** | You drive. No AI car. |
| **You vs AI** | Both cars spawn on the same terrain and race. You are the **orange** car, the AI is **blue**. |
| **2 players** | Two humans race on the **same** terrain, split screen. **Left screen** = **P1**, **orange** car, **WASD**. **Right screen** = **P2**, **green** car, **arrow keys**. Each screen follows its own car and shows both panels — yours top-left, your opponent's top-right. When both cars are dead, whoever reached the finish first wins; if nobody did, the farther run wins. |
| **Best of X** | Runs the AI X times on one shared map (with tiny spawn jitter so attempts diverge), then lets you replay any attempt ranked best→worst. |

Switching modes rebuilds the world with fresh terrain.

## 4. Controls (human driving)

- **→ (Right arrow)** or **↑ (Up arrow)** — motor forward
- **← (Left arrow)** or **↓ (Down arrow)** — motor reverse
- **Nothing held** — motor off (coast)

In **Human vs Human (split)** mode the left car uses **WASD** instead: **D** (or **W**) = forward, **A** (or **S**) = reverse. The right car keeps the arrow keys. Both sets drive on either axis, so the two are exact mirrors of each other.

That's the entire action space: on/off only, exactly what the AI has. No brakes, no throttle scaling.

### The HUD

Each car gets a panel in the top corner: its **score**, a **⏱ run timer** (game time, so it's fair at any sim speed; it freezes at the finish or when you crash), and for your car the best on this map. The bar at top-center shows how far along the track each car is, a gold tick at your best on this map, and the checkered finish. On the track itself, a **checkered FINISH flag** marks the launch lip (reaching it = beating the map) and a gold **BEST** pennant marks where your best run on this map ended. When the run is over, a card sums it up (score, finish time, **NEW RECORD** / **MAP BEST** badges) with **R** / **T** hints.

### Records

The **Your records** strip under the toolbar shows your **best score** and **fastest finish time** on the current map and across all maps. They're kept in this browser's local storage (same browser + domain only). A map is recognised by its shape, so a map re-loaded from History or Saved keeps its records. Each map that holds a record gets a permanent number in the order records were first set on maps, and the tiles label it with its **Saved** name if you've saved it (following renames and deletes), otherwise as **Record map N**, so the numbers skip past saved maps ("Record map 1", "Hilly", "Record map 3").

Every record map's terrain is stored too, so you can go back and beat it: **🏆 Records** in the toolbar (or click **Your records**) shows your all-maps **best score** and **best time** on top, then lists every record map: number, name, best score, best time (fastest finish), a 🏆 next to the all-maps bests. **Sort by** switches between **Order set** (the numbering), **Best score** (farthest first) and **Best time** (fastest first; maps you haven't finished go last); it remembers your choice. Each row has **Load** (rebuilds the exact same map, grass and all) and **Delete** (drops that map's records; asks first). Each stored map takes ~16 KB of browser storage. Only human runs count, and a run doesn't count if you used a cheat (Invincible, Zero-G, Flight, Rocket, Float, Underworld, Stop, Exit, Teleport, any physics-playground knob, or a map generated with changed terrain knobs) or slow-mo below 1×; the HUD shows a red **cheat records only** tag when that happens. Reverse controls is a handicap, so it still counts.

Cheated runs still land on a second, **incl. cheats** record track (the best of *all* runs; a clean run that beats it updates it too, but a cheated run never touches the clean records). Tick **Show cheat records** in the Records menu or under the end-of-run card to see it: the extra rows/tiles appear next to the clean ones, and any value a cheated run set is shown in **red with ⚠** (new ones get a red **CHEAT RECORD** badge). Maps holding only cheated records are hidden while the box is unticked.

Score (farthest distance) and finish time (the moment you cross the line) are separate records, so one run can hold both. For a finished run the score splits into **to the finish** (what the time measures), **fly-off** (until 5 s after the car leaves the end of the terrain; a real launch off the lip is over by then) and **after fly-off** (only reachable with cheats like Rocket/Flight). Click **▸** next to a record score in the Records menu to see the split (with how long the fly-off lasted); a **↗** marks scores with distance after the fly-off, and the end card shows the split automatically for such runs. A clean run with a fly-off of **90+ points** (≈ a score of 1973 on a normal map) earns a gold **✦ legendary fly-off** marker on the end card and next to the record.

### Toolbar

- **↺ Restart** — puts the car(s) back at the start of the *current* map, no new terrain.
- **🎲 New map** — throws away the current map and generates a brand-new random one, respawning everyone.
- **Pause / Resume** — freezes the sim.
- **⛶ Fullscreen** — fills the screen with only the game (HUD included); **Esc** exits. Keys work as usual; switch modes with **Alt+1…5**.
- **Speed (0.25x–8x)** — simulation speed multiplier (handy for watching the AI; for racing, stay on 1x). **Shift+Scroll** anywhere on the page steps it too (scroll up = faster). Every speed renders at your display's full frame rate; the renderer fills in frames between physics ticks, while the physics itself always steps at the game's exact 30 Hz (slow-mo is smooth, not a slideshow).
- **🗺 History** — opens a menu of every map generated this session (newest first); click **Load** to re-drive one. Cleared when you close the page.
- **💾 Saved** — opens a menu of maps you've saved in this browser. **＋ Save current map** prompts for a name and stores the current map to the browser's local storage (survives closing/reopening and redeploys, but only in the same browser + domain). Names must be unique, and saving a map that's identical to one you already have is blocked (it tells you which saved terrain it matches). Each saved map has **Load**, **Rename**, and **Delete** (Delete asks once to confirm). The **Map** chip in the toolbar always shows which map you're on; renaming the current map updates it, and deleting the saved copy of the map you're on marks it **(unsaved)** (it stays loaded; re-saving suggests the same name).
- **▶ Watch the AI beat this map** — runs the Go-Explore save-scum backtracking search on the *current* terrain, then replays the run as a ghost: it flies off the end if it can, otherwise it shows the best run it found. "● Replaying run" appears under the toolbar while the replay plays. The **⚙** next to it holds the search's tick budget.
- **⌨ Keys** (top bar) — pops up the keyboard-shortcut cheat sheet.
- **🛠 Tools** (top bar) — slides out the drawer with the readouts, cheats, status messages and debug panel (see §7). Every item also has a key, so the drawer can stay closed; cheat messages pop up briefly over the canvas.

Keyboard shortcuts (also on the **⌨ Keys** button): **I** invincible, **Z** Zero-G (toggle), **F** float the car(s) up, **U** Underworld (drop the car(s) to altitude 1.5 m, just above the fall-off line), **X** stop (zero all velocity), **H** altimeter, **V** velocity, **C** distance (current-position score), **K** reverse controls, **R** Restart (same map), **T** New map, **P** Pause/Resume, **Alt+1…5** switch mode (1 AI drives · 2 You drive · 3 You vs AI · 4 2 players · 5 Best of X), **Esc** close the cheat sheet / Tools drawer.

## 5. Racing the AI (Human vs AI mode)

- Both cars run on the **same terrain** and the same physics, in the same world (they don't collide with each other; wheels/chassis only interact with the ground).
- Terrain is generated exactly like the real Code Bullet game (same noise, same steepness filter), so the hills should feel identical to thebigcb.com.
- The HUD shows each player's **score** (= max distance px ÷ 10) and run time. The AI's deployed model averages ~**1370** (median ~1420) on this terrain; the track caps out around ~**1850–1900**.
- You **die** when your driver's head touches the ground or you fall off the bottom of the screen. The AI additionally dies if it makes no progress for ~17 seconds (matching its training); you are never timed out.
- The camera follows **you** while you're alive; when you die it switches to the AI so you can watch whether it beats your distance. When everyone is dead, press **R** (↺ Restart) to race the same hills again, or **T** (🎲 New map) for a fresh map.

Tip: the AI's whole skill is rhythm: pulsing the motor on/off to keep the nose level on landings and to crawl up steep faces without flipping. Tapping **←** mid-air pitches the nose up; tapping **→** pitches it down.

## 6. Best of X (optional)

Select *Best of X*, set the number of attempts, click **Run**. The AI plays X attempts headless (no rendering) on one fixed map, then the results dropdown lets you **Watch** any attempt, ranked from best to worst. **🎲 New map** re-rolls the shared map and clears old runs.

## 7. Tools drawer: readouts, cheats, physics playground

The **🛠 Tools** drawer holds **Readouts** (Altimeter, Velocity, Current distance; read-only, not cheats), **Cheats**, **Messages**, the collapsed **🧪 Physics playground**, and (unlocked) the **🔧 Dev mode** tools (§8). The **info readouts and cheats** (Altimeter, Velocity, Distance, Invincible, Zero-G + Float, Underworld, and the physics/motor knobs) apply to **every car on screen, the AI included, in all modes** (even AI-only). The dev-mode bug probe logs the **human** car, so for *recording* use **You drive** mode. Nothing here persists or touches the source physics; it's all runtime, so AI/browser parity and the deployed model are unaffected (no retrain implied).

- **Recorder (always on):** every tick the human car's full state is logged (chassis pose + angular velocity, per-wheel motor/spin/on-ground, the motor-joint and suspension reaction torques, keys/action, and the flags below). The live `angVel … angle …` readout shows the current chassis spin.
- **Invincible:** skips every death path — head-touches-ground (which also splits the car), falling off the bottom, **and the AI's no-progress timeout**, so no car ends its run while you experiment.
- **Zero-G + Float:** turns gravity off and lifts the car(s) into open air, **preserving linear and angular velocity** (so a developing spin keeps going). With no gravity and no ground, any spin that grows is a pure joint/solver artifact. The camera follows the car vertically as it drifts. Pressing **Zero-G** again restores gravity.
- **Underworld (U):** the opposite of Float: teleports the car(s) straight down to **altitude 1.5 m** (the Altimeter's reading: elevation above the fall-off line at the bottom of the screen), preserving linear and angular velocity. That's right on the brink of the void, so turn on **Invincible** first if you don't want to fall off.
- **Stop (X):** momentarily zeroes all velocity (horizontal, vertical, and rotational) on every car, freezing it in place for an instant before gravity and driving take over again. Handy for lining up a jump or killing a bad spin.
- **Open/Close Exit (E):** there's an invisible "underworld" between the terrain and a floor below the screen; you can slip into it from the open left edge, but a wall seals the right end. This knocks that right wall down (on the current map only) so you can drive out the right side; pressing it again puts the wall back up; the button cycles open ↔ closed (its label tracks the state). A rebuild (Restart, New map, loading a map, or switching mode) also puts the wall back.
- **Reverse controls (K):** mirrors every movement key: **←**/**→**, **↑**/**↓**, **A**/**D** and **S**/**W** swap while driving, and in **Flight**/**Rocket** mode forward↔back and the two rotate keys swap too. It applies to both control sets, so in Human-vs-Human both players get it; the AI drives itself and is unaffected. A pink **🔄 Reversed controls** line sits with the other on-screen readouts while it's on. Safe to toggle mid-drive; the swap happens when the keys are read, so a held key never sticks.
- **Teleport:** opens a small window to teleport the car(s) to any position. **X is the score** (distance) and **Y is altitude in metres** above the fall-off line: two different units, but both are the numbers you already see in the HUD (score + Altimeter). The fields prefill from the car's current spot; velocity is preserved. No keybind.
- **Altimeter (H) / Velocity (V):** on-screen readouts for the focused car: altitude above the fall-off line (a fixed level at the bottom of the screen, in m, so it reads true elevation along the track rather than clearance over the hill directly below) and velocity as **H**orizontal / **V**ertical / **Tot**al (m/s; vertical is positive upward). Velocity is the car's whole-vehicle center-of-mass velocity, so spinning or flipping doesn't inflate it. They sit top-center; when both are on, altitude is on top and speed just below. In Human-vs-Human split mode each screen shows its own player's meters.
- **Current distance (C):** your **current-position** score, shown as an extra line in the player's panel. The score is your best (high-water mark); this is where you are *now*, so it drops if you roll backward.
- **🧪 Physics playground** (the collapsible panel at the bottom of the Tools drawer): every tweakable physics value, in collapsible sections: World (gravity down/sideways), Car body, Wheels, Motor (top speed ×, separate **rear** and **front** torque, so 0 on one gives front/rear-wheel drive), Suspension (stiffness, damping, ride height, travel limit), Driver (head/torso density, seat spring, seat tilt limits, neck limit + spring), **Sizes & shapes**, Rules (head-hit death, fall-off depth, AI stuck timeout) and Terrain. Each number is a slider plus a box for exact values; double-click a knob's name to reset it. Most knobs apply **live** to every car, the AI included (it was trained on stock physics, so expect chaos). **Sizes & shapes** apply on **Restart (R)** and terrain hilliness/length/spacing on a **New map (T)**; the section shows "↺ restart to apply" / "🎲 new map to apply" and a message reminds you. Presets (Moon, Ice rink, Trampoline, Monster truck, Bobblehead) stack; **Reset all** restores stock. Values reset on page reload.
## 8. Dev mode (password)

The small **🔒 Dev** button at the bottom of the Tools drawer (or opening the page with `?dev`) asks for the dev password. Once unlocked, the browser remembers it (localStorage) until you press **Lock**. The password only hides these tools: it's checked client-side and the code ships to everyone. Unlocking adds a **🔧 Dev mode** section to the drawer and an **AI vs AI** mode tab:

- **AI vision:** the policy's 6 look-ahead probes drawn on the terrain (label = probe:clearance in m, colour red→green = near→far, dashed = clipped to the obs range), a green ring on each wheel the policy currently sees as grounded (coyote time included), and a panel with the FWD/REV/OFF softmax probabilities plus the newest raw obs values.
- **Box2D debug draw:** every fixture (green dynamic, orange static, blue sensor), joints (cyan), contact points + normals (red), centre of mass + velocity (yellow), and a panel with body/joint/contact counts and the torso joint angle against its −70.6°/+104.5° limits.
- **Time:** **.** pauses and steps one physics tick (hold to repeat). **Q** quick-saves the whole sim and **L** loads it back. A load marks the run as cheated. Every load replays the same future exactly, but not quite the original run, because Box2D's warm-start caches aren't saved.
- **Models:** **Load main AI… / Load AI B…** take an `.onnx` plus its `policy_meta.json` (select both; without the meta, the deployed one is used). The main AI drives every mode, Best of X and the search too. **AI vs AI** races main vs B on one map. **Both → deployed** reverts.
- **Map JSON:** Copy / Download / Paste / Open the current map (vertices in px + spawn + grass). Import also accepts Python's `Ground.save_json` output and bug-probe recordings. In Python, `python autorun/backtrack_search.py --map-json hcr_map_X.json` searches that exact map (`Ground.load_json` reads the format).
- **Spin-investigation presets:** **🔥 Unmask** (strip damping + stiff, under-damped suspension → exposes a suspension-resonance instability) and **🌀 Motor-spin** (motor speed ×2 → the chassis winds into a sustained counter-spin while driving — motor *speed*, not torque/friction, is that lever).
- **Bug probe:** **⚑ Flag unusual** marks the current tick so the moment is easy to find, and **Download recording** exports `hcr_bugrun_*.json` (ticks + flags + terrain + every playground knob) for offline analysis. The recorder itself is always on.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "ERROR loading agent" / model never loads | You opened the file directly (`file://`) or the server isn't running. Use http://localhost:8765/ (or the deployed URL). |
| Page loads but sprites missing | Server started from the wrong directory — it must be this folder so `Pics/`, `libraries/`, and `ai_policy.onnx` resolve. |
| Just deployed a new model but behavior unchanged | Hard-refresh (**Ctrl+Shift+R**) — the browser caches `ai_policy.onnx` and `ai_policy.js`. |
| Port 8765 already in use | Pick another port (`-m http.server 8766`) and adjust the URL. |
| Arrow keys scroll the page instead of driving | Click the page/canvas once so it has keyboard focus. |
