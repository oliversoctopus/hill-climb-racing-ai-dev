# python/diagnostics

Lab notebook of one-off probes (chaos/ceiling investigations, physics forensics, pre-flight checks). NOT load-bearing library code; the durable correctness tests live in `python/tests/`. Result artifacts (`*.npz` / `*.log` / `*.csv`) are gitignored.

Files prefixed `_` (e.g. `_tb_trend.py`) are helper/internal probes. **`rc_scan.py` is the collapse-detector / final-confirm tool referenced in CLAUDE.md** (scan a run for degradation, then 200-ep confirm the final).

Run with the venv python, e.g.:

```powershell
python\.venv\Scripts\python.exe python\diagnostics\jitter_probe.py 60 8
```

## Score ceiling / chaos / terrain
- **jitter_probe.py** — chaos vs skill: does the same policy die in different places under ±1px spawn jitter; single- vs cross-policy oracle (pinned tracks).
- **deathmap.py** — where/why episodes end: completion rate, death-x distribution, terrain steepness at death.
- **measure_track_end.py** — pin the TRUE end-of-track fly-off score (run to natural death, no early-stop).

## Checkpoint selection
- **rc_scan.py** — snapshot-scan a run's checkpoints at f=0, rank by mean; `--confirm` for the 200-ep final check (the collapse detector; actively used per CLAUDE.md). <br>*(Pruned 2026-07-07: one-time reverse-curriculum pre-flight tuning: `rc_probe` (is_too_steep rejection rate), `rc_difficulty_probe` (score-vs-difficulty). The curriculum was retired; scripts in git history.)*

## Physics forensics (spontaneous-rotation investigation)
- **torque_probe.py** — localize the spontaneous CCW chassis rotation; A/Bs stock vs stability-corrected suspension via patched Wheel.js in V8.
- **analyze_bugrun.py** — read the browser Bug-probe JSON export; report the spontaneous-rotation signature (motor-off / wheels-off-ground / zero-G). <br>*(Pruned 2026-07-07: `v8_physics_probe`, the superseded original "is V8 fast enough" prototype. In git history.)*

## Pre-flight smoke / audit
- **_env_smoke.py** — quick smoke test for the JS-backed HillClimbEnv (reset/step timing, obs).
- **_eval_smoke.py** — headless: load the smoke checkpoint, predict ~50 actions, verify the eval pipeline is wired up.
- **_train_audit.py** — pre-training audit: stress-test env + pipeline (obs invariants across seeds) before a long PPO run.

## TensorBoard analysis
- **_find_peaks.py** — parse TB event files, report peak `ep_rew_mean` + the step it occurred at.
- **_tb_trend.py** — dump `ep_rew_mean` trends (@4/6/7/8M + last-1M slope) to check whether reward was still rising at run end.
- **_tb_logfit.py** — fit `v = a + b·ln(t)`, test out-of-sample on 6–8M, project the log-law 8M→16M gain.

## Redundant / overlapping clusters
Groups that do similar things (the one-off / superseded members were pruned 2026-07-07; see the section notes above; these remain):
- **TensorBoard analysis (3):** `_find_peaks`, `_tb_trend`, `_tb_logfit` — all `EventAccumulator`-read `rollout/ep_rew_mean`; differ only in the summary (peak / trend / log-fit). (Kept — tiny; could later fold into one script with subcommands.)
- **Smoke/audit (3):** `_env_smoke`, `_eval_smoke`, `_train_audit` — overlapping "does the env/eval/train pipeline stand up" checks (now largely superseded by `python/tests/`, but cheap to keep).
