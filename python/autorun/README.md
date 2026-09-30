# python/autorun

Lab notebook of one-off experiment/eval scripts (the autonomous-run campaign; see `RUNLOG.md`). NOT load-bearing library code; the durable correctness tests live in `python/tests/`. Result artifacts (`*.npz` / `*.log` / `*.csv`) are gitignored.

Run with the venv python, e.g.:

```powershell
python\.venv\Scripts\python.exe python\autorun\best_of_k.py 60 16
```

**Env construction:** `eval._build_env(randomize_terrain=…, seed=…, max_steps=…, render_mode=None, n_stack=None)` is the canonical stacked-env builder (returns `(vec_env, env_single)`; `n_stack=None` uses the champion's 4). NEW eval scripts should import it instead of re-implementing the `VecFrameStack(DummyVecEnv([HillClimbEnv(…)]), 4)` idiom. The scripts below predate it and inline the idiom, kept as-is to preserve their exact recorded behavior.

## Best-of-X / deployment levers
- **best_of_k.py** — Best-of-K completion/score curve for the deployed champion (±1px spawn jitter, pinned tracks); saves the attempt matrix.
- **adaptive_bestofx.py** — adaptive Best-of-X allocation scored OFFLINE on best_of_k's recorded attempt matrix (uniform vs stop-on-solve vs adaptive vs oracle). <br>*(Pruned 2026-07-07: tested-negative Best-of-X variants: `best_of_k_stoch` (stochastic sampling capped lower), `targeted_perturb` (wash vs blind jitter), `ensemble_bestofx` (no help). Conclusions in PROJECT_STATUS; scripts in git history.)*

## Search / replay
- **backtrack_search.py** — Go-Explore "save-scum" backtracking search on the frozen policy: rewind + perturb + stitch to factorize per-section survival.
- **export_replay.py** — re-run the backtracking search to export stitched beat-the-game runs (+ hard play-only tracks) as browser replay JSON.

## Paired A/B eval (pinned tracks)
- **paired_ab.py** — generalized TRUE-paired A/B of two checkpoints on pinned tracks, per-model frame-stack, paired t-test.
- **robust_ab.py** — paired single-shot A/B of two checkpoints + each model's completion rate.
- **fs8_ab.py** — frame-stack-8 vs champion (frame-stack-4), truly paired.
- **eval_multi.py** — eval a champion + several checkpoints on the SAME pinned tracks; per-ckpt mean + paired diff (spiky-point sanity check).

## Multi-life
- **multilife_env.py** — MultiLifeEnv: K lives per terrain + previous-death obs markers (adaptive-retry lever).
- **train_multilife.py** — PPO trainer on MultiLifeEnv, mirroring the champion recipe.
- **smoke_multilife.py** — cheap smoke test: obs shape, terrain persistence across lives, marker population.
- **multilife_eval.py** — does adaptive multi-life (markers) beat the champion's i.i.d. best-of-K on identical tracks?

## Eval curves / plotting
- **eval_curve.py** — deterministic eval curve across a run's checkpoints on PINNED tracks (low-noise, comparable across checkpoints).
- **_curve_table.py** — print train-reward vs det-eval table + Pearson r for seed2 / fs8.
- **plot_curves.py** — overlay det eval vs train reward for seed2 + fs8 (two panels, twin y-axes). <br>*(Pruned 2026-07-07: one-off study figures whose conclusions are in PROJECT_STATUS: `plot_curve_base16` (8M→16M), `combined_plot` (compute-vs-decay). In git history.)*

## Weight averaging
- **swa.py** — Stochastic Weight Averaging of late `seed2_resume` checkpoints → basin centroid.

## Redundant / overlapping clusters
Groups that do similar things (the tested-negative / one-off members were pruned 2026-07-07; see the section notes above; these remain):
- **Paired-A/B family (4):** `paired_ab` (the generalized one), `robust_ab`, `fs8_ab`, `eval_multi`: same pinned-track inject + paired-diff scaffold; `fs8_ab`/`robust_ab` are specializations of `paired_ab`, `eval_multi` extends it to N checkpoints. (Kept — still occasionally useful.)
- **Plotting (2):** `plot_curves` + its text-only twin `_curve_table` — read `eval_curve_*.npz` + train logs/TB and render the eval-vs-train story.
