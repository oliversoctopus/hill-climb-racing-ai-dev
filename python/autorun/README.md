# python/autorun

Lab notebook of one-off experiment/eval scripts (the autonomous-run campaign;
see `RUNLOG.md`). NOT load-bearing library code — the durable correctness tests
live in `python/tests/`. Result artifacts (`*.npz` / `*.log` / `*.csv`) are
gitignored.

Run with the venv python, e.g.:

```powershell
python\.venv\Scripts\python.exe python\autorun\best_of_k.py 60 16
```

**Env construction:** `eval._build_env(randomize_terrain=…, seed=…, max_steps=…,
render_mode=None, n_stack=None)` is the canonical stacked-env builder (returns
`(vec_env, env_single)`; `n_stack=None` uses the champion's 4). NEW eval scripts
should import it instead of re-implementing the
`VecFrameStack(DummyVecEnv([HillClimbEnv(…)]), 4)` idiom. The scripts below predate
it and inline the idiom — kept as-is to preserve their exact recorded behavior.

## Best-of-X / deployment levers
- **best_of_k.py** — Best-of-K completion/score curve for the deployed champion (±1px spawn jitter, pinned tracks); saves the attempt matrix.
- **best_of_k_stoch.py** — can stochastic action sampling beat the deterministic Best-of-K ceiling?
- **adaptive_bestofx.py** — adaptive Best-of-X allocation scored OFFLINE on best_of_k's recorded attempt matrix (uniform vs stop-on-solve vs adaptive vs oracle).
- **targeted_perturb.py** — targeted-perturbation Best-of-X (off-policy burst at the wall) vs blind ±1px jitter, paired.
- **ensemble_bestofx.py** — do two differently-trained policies' Best-of-X failures complement (mixed union > single)?

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
- **plot_curves.py** — overlay det eval vs train reward for seed2 + fs8 (two panels, twin y-axes).
- **plot_curve_base16.py** — train reward vs det eval for the 16M run base16_a (did 8M→16M buy any eval?).
- **combined_plot.py** — combined figure for the compute-vs-decay + resume study (saturation curve + eval trajectories).

## Weight averaging
- **swa.py** — Stochastic Weight Averaging of late `seed2_resume` checkpoints → basin centroid.

## Redundant / overlapping clusters
Groups that do similar things (flagged for later pruning — NOT a deletion recommendation):
- **Best-of-X variants (5):** `best_of_k`, `best_of_k_stoch`, `adaptive_bestofx`, `targeted_perturb`, `ensemble_bestofx` — all build a pinned-track attempt matrix and compute Best-of-K completion; they differ only in what diversifies attempts.
- **Paired-A/B family (4):** `paired_ab` (the generalized one), `robust_ab`, `fs8_ab`, `eval_multi` — same pinned-track inject + paired-diff scaffold; `fs8_ab`/`robust_ab` are specializations of `paired_ab`, `eval_multi` extends it to N checkpoints.
- **Plotting (4):** `plot_curves`, `plot_curve_base16`, `combined_plot`, `_curve_table` — all read `eval_curve_*.npz` + train logs/TB and render the eval-vs-train story (`_curve_table` is the text-only version of `plot_curves`).
