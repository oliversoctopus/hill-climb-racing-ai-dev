# Autonomous session run log

Started: **2026-06-08 09:00:59 −05:00**. User away for a week; full autonomy, no
permission gates. Mandate: run helpful experiments, stop when out of things to
try, then write SUMMARY.md + CLEANUP.md and report the stop wall-clock time.

Machine: 16 logical cores, 32 GB RAM (21 GB free at start). Known unfixable
kernel memory leak ~100 MB/h, no reboot possible → front-load value, expect
possible WinError 1450 late. Heavy jobs run in background; keep ≤2 concurrent.

Champion baseline (deployed): `checkpoints/base_a_8000000_steps.zip`,
200-ep det seed-42 mean **1367.5**.

## Guardrails (self-imposed)
- Do NOT overwrite live `ai_policy.onnx` / browser deployment. Export candidates
  with distinct names; recommend deploy in SUMMARY.
- Do NOT prune training checkpoints. Delete only my own scratch/smoke outputs.
- Never touch `python/archive/`, physics/Car.js, pybox2d.
- Eval rigor: paired A/B on identical tracks for cross-model claims; 200-ep
  confirms; winner's-curse control = replicate any "win" on a FRESH track set.

## Planned experiments (priority order, front-loaded)
- **E1 best-of-K deployment curve** (champion only, no training): completion &
  mean-score vs K jittered attempts. Informs the browser deploy rec. → status:
- **E2 multi-seed champion search**: seeds 2/3/4, default recipe, 8M each;
  paired A/B vs champion; replicate any winner on fresh tracks. → status:
- **E3 multi-life death-marker**: K lives/terrain + previous-death obs markers,
  reward across lives. Targets the measured human adaptive-retry gap (90% in 5
  adaptive vs AI 67.5% in 8 i.i.d.). Build+smoke+train+eval. → status:
- **E4 RecurrentPPO/LSTM to completion** (user OK'd): 8M, ~9h, A/B vs champion.
  → status:
- **E5 (if machine healthy) frame-stack-8** PPO: cheap temporal-context lever.
  → status:

## Event log
- 09:00 −05:00  session start; oriented; plan locked.
- 09:03 −05:00  launched E2 seed2 training (bg) + E1 best_of_k (bg). NOTE: first
  launch used `nohup &` which double-backgrounded (lost completion notify) and a
  blanket python-kill was (correctly) denied; left the orphans running and armed
  per-job `until`-loop waiters keyed on the final artifact file. Lesson: launch
  the python DIRECTLY as run_in_background (no nohup/&) so the tool tracks it.
- 09:0x −05:00  E1 status: running. E2 seed2 status: training.
- 09:1x −05:00  E3 infra written + smoke-PASSED (multilife_env.py terrain
  grouping + both markers correct after fixing a life-index off-by-one).
  Files: multilife_env.py, train_multilife.py, smoke_multilife.py,
  multilife_eval.py. Will train after CPU frees.
- Awaiting: E1 best_of_k (15/60) and E2 seed2 (720k/8M, fps~2050) completion.

### E1 RESULT (best-of-K, champion base_a, 60 pinned tracks) — DONE
K=1 20.0% / 1476 ; K=2 33.3% / 1607 ; K=5 56.7% / 1757 ; K=8 65.0% / 1795 ;
K=10 70.0% / 1811 ; K=16 70.0% / 1820 (completion% / oracle mean score).
- Best-of-K is the cheapest deploy win; K≈8 is the knee (65%/1795), plateau ~70%.
- HARD ~30% ceiling even at K=16 chaos rerolls -> the residual E3 targets.
- Caveat: K=1 mean 1476 here > the documented 1367.5 because this is a
  different (60 pinned) track set than eval.py's 200-ep seed-42 series; use the
  SCALING, not the absolute, for cross-set claims.
- 09:2x −05:00 launched ml_dbg (300k, n-envs 4) to debug the E3 eval harness
  while seed2 finishes.
- 09:3x −05:00 E3 eval harness VALIDATED on ml_dbg (300k throwaway): champ +
  multilife both run; markers-changed-behaviour=100% (death-marker obs alters
  actions — life2 diverges from life1 with NO jitter); even the weak debug
  policy's no-jitter oracle climbs across lives (1218->1459). Mechanism works.
  ml_dbg is a smoke artifact -> mark for cleanup.
- Concurrency decision: run heavy PPO jobs SEQUENTIALLY (two 8-worker jobs only
  timeshare the 8 physical cores -> no speedup, more wall-clock => more leak).
  LSTM (low core use) may overlap a PPO job later.
- seed2 @3.75M/8M ep_rew~400, healthy. Waiting for it, then launch E3 full 8M.
- 10:05 −05:00 E2 seed2 DONE (62 min, final ep_rew~437). Launched in parallel:
  E3 full 8M `ml6` (lives=6, markers=2, 8 workers, the long pole) + seed2 paired
  A/B vs champion (200 eps det, seed 42, single-env -> fits spare cores).
  NOTE: eval.py stdout is block-buffered to file; rely on tracked-process exit,
  not log peeking. (Future: add `python -u` for eval launches.)
- Queue after these: read seed2 A/B; after ml6, run multilife_eval (real E3
  test) + launch seed3; then seed4; then E4 LSTM (may overlap a PPO run).

### E2 seed2 RESULT (paired A/B vs champion, 200 eps det, seed 42) — DONE
seed2 1434.6 vs champion 1411.3; paired diff **+23.3**, 95% CI [-55,+101],
p=0.56, per-track wins 101–99. **WASH** — seed luck is not a lever (matches the
project's ±60 noise floor). (champion=1411 here vs documented 1367.5 = different
track set; the paired +23 is the valid number.)
- 10:1x −05:00 ml6 solo fps 2674 (~half the 16 logical cores) -> launched seed3
  concurrently (hyperthread headroom = net throughput win). NOTE/lesson: cwd is
  `python/` (an early `cd python` persisted) -> use cwd-relative paths
  (`train.py`, `autorun/...`), NOT `python/...`. First seed3 launch failed exit1
  on the doubled path (no stray files); relaunched OK.
- Plan: if seed3 also washes, SKIP seed4 (champion is seed-robust); spend the
  budget on E3/E4 instead.
- Now running: ml6 (E3, ~40min left) + seed3 (E2).
- 11:17 −05:00 E3 ml6 DONE (71 min, final ep_rew~411). Launched real
  multilife_eval (ml6 vs champion best-of-K, 60 tracks, K=8) concurrent w/ seed3.
- seed3 @4.6M/8M, healthy. (Lesson: stop sleep-polling; rely on tracked-task
  completion notifications.)
- 11:45 −05:00 E2 seed3 DONE (85 min, slowed by ml6 overlap). Launched seed3 A/B
  vs champion.
- 11:4x −05:00 E4 LSTM (RecurrentPPO, seed 1, 8M) LAUNCHED — the ~9h long pole;
  overlaps the light evals. Now running: ml6_eval (46/60), seed3_ab, lstm.

### E3 ml6 RESULT (lives=6, markers=2; eval 60 tracks, K up to 8) — NEGATIVE
completion% @K=8: champ **65.0** / ml_nojit **40.0** / ml_jit **55.0**.
oracle@K=8: champ 1794.6 / ml_nojit 1695.8 / ml_jit 1747.1. K=1: champ 20% /
ml 10% (base policy WEAKER). markers-changed-behaviour=100% but ml_nojit
plateaus at 40% by K=4 (fixed alt repertoire, not rich exploration).
**Verdict: adaptive death-markers LOSE to free best-of-K at every K.** Likely
causes: (1) terrain-diversity dilution (6 retry-lives/terrain) weakened the base
driver; (2) marker adaptivity saturates. champ best-of-K reproduced E1 exactly
=> eval is deterministic/sound.
- 12:0x −05:00 probe: launched `ml3` (lives=3, markers=2, seed 8, n-envs 4) on
  the LSTM's spare cores to test the terrain-dilution hypothesis. n-envs 4 (vs
  champ recipe 8) is a confound, so it's exploratory: a clear WIN would be
  re-run clean; a loss confirms E3 negative. Better than idling cores 9h.

### E2 CONCLUSION (seeds) — WASH, not a lever
seed2 +23.3 (p=0.56), seed3 −32.0 (p=0.46), both vs champion, 200-ep paired.
Two clean washes => champion (seed 1) is seed-robust; skip seed4 (picking the max
of more seeds = winner's-curse noise). No deployable model from seed search.
- 12:1x −05:00 KILLED ml3 probe: LSTM dropped to ~175 fps under its 4 workers.
  Sequential is cheaper (LSTM solo ~12h then ml3 clean n-envs8 ~1.2h <
  oversubscribed concurrent). LSTM runs SOLO now. Will run ml3-clean AFTER LSTM.
  This machine's LSTM ~175 fps -> ~12h for 8M (the reason the prior session
  balked at CPU LSTM). Armed bounded safety waiter (wake by ~14h even on hang).
- Remaining queue (post-LSTM): A/B LSTM vs champion; ml3 clean (n-envs 8) + eval;
  optional E5 frame-stack-8; then SUMMARY.md + CLEANUP.md + stop-time.
- 19:12 −05:00 E4 LSTM DONE: full 8M in 7.4h (~300 fps once solo). Final
  ep_rew_mean **303** (BELOW champ ~376 / seeds ~437) — early warning. Launched
  LSTM A/B vs champion + clean ml3 (n-envs 8) concurrently. Both healthy.
  (ml3_1 tb dir is from the killed probe -> cleanup.)

### E4 LSTM RESULT (paired A/B vs champion, 200 eps det) — NEGATIVE (decisive)
LSTM 964.3 vs champion 1411.3; paired diff **−447.0**, 95% CI [−535,−359],
p<0.0001, champion wins **158/200**. RecurrentPPO (single-frame) is FAR worse
than the frame-stacked MLP. Completing the run confirms the prior session's
abort instinct. Lesson: added temporal memory (LSTM) HURTS this task; the
explicit 4-frame stack + MLP is better. => deprioritize E5 frame-stack-8
(same temporal-memory direction, low prior).
- 19:3x −05:00 checking whether ai_play.html already does Best-of-X (to make the
  E1 deployment rec accurate). ml3-clean still training.

### DEPLOYMENT FINDING (E1 applied to the actual browser)
ai_play.html ALREADY has "Best of X (AI)" mode: deterministic argmax
(ai_policy.js:60) + ±1px spawn jitter, default X=10, range 1-200. So E1's curve
applies directly: **X=10 default is already near-optimal** (knee 8-10, hard ~70%
plateau by K=10). No best-of-X change needed. Residual ~30% needs a better
policy — which E2/E3/E4 did NOT deliver.
- 19:4x −05:00 launched E6 best_of_k_stoch (champion, 60 tracks): can STOCHASTIC
  sampling break the 70% argmax ceiling? (det_jit vs stoch_jit vs stoch_nojit).
  If yes -> deployable (add sampling to ai_policy.js). Concurrent w/ ml3-clean.
- 20:0x −05:00 E3 ml3-clean DONE; launched ml3 multilife_eval (repeated the
  `&`-double-background slip -> launcher fired early; orphan eval running, armed a
  log waiter). NOTE: multilife_eval overwrites multilife_eval_results.npz, so
  ml6's npz is gone (its TABLE is preserved in ml6_eval.log). Pending: E6 +
  ml3_eval.

### E6 RESULT (stochastic vs deterministic best-of-K, champion, 60 tracks) — NEGATIVE
completion@K: det_jit 65.0(K8)/70.0(K10-16); stoch_jit 55.0/66.7; stoch_nojit
58.3/66.7. **Deterministic+jitter (current deploy) wins at every K; ~70% ceiling
not broken.** No deployment change. (stoch_nojit ~67% confirms sampling & jitter
are interchangeable diversity sources, same fundamental ceiling.)

### E3 ml3 RESULT (lives=3, n-envs 8; eval 60 tracks, K up to 8) — NEGATIVE (deploy), nuance
completion@K=8: champ **65.0** / ml_nojit 48.3 / ml_jit 53.3. BUT K=1: champ 20.0
/ ml 26.7 (lives=3 RECOVERED the base policy — terrain-dilution hypothesis
CONFIRMED; ml6 lives=6 was 10%). ml_nojit plateaus 48.3% by K=4.
**Verdict: markers help SINGLE-SHOT (26.7 vs 20, weak n=60) but LOSE under the
deployed best-of-X (53 vs 65), because marker-conditioning cuts the trajectory
diversity best-of-X exploits.** Champion stays best for deployment.
- 20:1x −05:00 All headline levers done & negative/wash except E1 (deploy
  characterization). Doing one last untested lever: E5 frame-stack-8 (explicit
  temporal context, opposite end from the failed LSTM). Then wrap up.

### METHODOLOGY FINDING — eval.py --ab is ~UNPAIRED at f=0
make_ground rerolls ~22-33x (97% too-steep rejection); each reroll draws a fresh
seed from the GLOBAL random stream (ground.py:443->161). So eval.py --ab's env_a
and env_b sit at different global-stream positions => DIFFERENT terrain, despite
same --seed. Tell: my A/B sd_diff ≈ 560-630 ≈ √2×430 (single-policy std) = the
unpaired signature (no terrain cancellation). Conclusions still valid (unpaired
mean test is fine): seed washes stay washes, LSTM stays decisively worse. But
for TRUE pairing use the pinned-track inject method (E1/E3/E6/fs8_ab do this).
Worth flagging in PROJECT_STATUS.
- 20:2x −05:00 fs8 training (obs 96 confirmed), fps~1782. fs8_ab.py ready
  (pinned-track TRUE-paired, n=120). Waiting on fs8 train.

### E5 fs8 RESULT (frame-stack-8 vs champion, 120 pinned tracks, TRUE paired) — NEGATIVE
fs8 1296.9 vs champion 1409.3; paired diff **−112.4**, 95% CI [−207,−17],
p=0.021, champion wins 67–51. sd_diff 526 (< 600 => real pairing). More explicit
temporal context HURTS; frame-stack-4 is the sweet spot. Consistent with E4 LSTM.

## SESSION COMPLETE — 2026-06-08 21:59:46 −05:00 (~13h)
All 6 experiments done; **none beat the champion**. Deliverables:
PROJECT_STATUS.md + CLAUDE.md updated (experiment log, live levers, gotcha #10
corollary). Deleted smoke/scratch (ml_dbg ckpts, tb/ml_dbg_1, tb/ml3_1). Machine
quiescent, 0 python procs, ~1.9GB consumed (leak, expected). Recommendation:
keep champion + Best-of-X X=10 (already near-optimal); ~70% completion is a hard
chaos ceiling. Highest-upside untried idea: true multi-life episode (credit
across lives). No checkpoints pruned (per instruction) — see CLEANUP for recs.

## 2026-06-15 follow-up — compute vs decay (user Qs)
Hypothesis: the eval ceiling is set by the DECAY schedule completing, not raw
compute. Tests:
- **Q2 compressed-decay**: `dec4m` (--timesteps 4M) + `dec2m` (2M), seed 1, decay
  auto-compressed into the run length. A/B vs champion on pinned tracks. Does a
  shorter run with matched decay reach the same ~1410 ceiling?
- **Q1 resume hold-low**: patched train.py with `--resume-hold-low` (opt-in;
  default reset-high behavior preserved) -> holds LR/ent at 1e-4/0.003 constant.
  Resume seed2_final (+4M, the strongest-tracking 8M run) -> does constant-low
  past convergence help/wash/drift?
- Deliverable: all eval-vs-train curves in one figure.
- 2026-06-15 launched dec4m+dec2m (chained). Resume after.

### Q2 RESULT — compressed decay does NOT reach the 8M ceiling (compute floor)
120-track paired A/B vs champion (1409): dec4m(4M) **1267, −142.5 p=.009**;
dec2m(2M) **1211, −198.6 p=.0006**. With base16(16M)≈champion(8M) wash, eval is a
SATURATION curve: 2M 1211 -> 4M 1267 -> 8M ~1410 -> 16M ~1410 (plateau).
=> compute matters UP TO ~8M (decay-compression can't substitute); beyond 8M
wasted. Hypothesis "decay not compute" is half-right (only above the ~8M knee).
Note: dec4m train reward 394 > champion 376 but eval 142 LOWER — compressed
anneal inflates the training curve on an undertrained policy (cross-run
dissociation again).
- Running: seed2_resume (Q1 hold-low +4M) + base16 120-track A/B (for the plot).

### Q1 RESULT — resume hold-low (+4M const-low) = WASH
seed2_resume vs seed2(8M): −11 p=.82; vs champion: +5 p=.93; train reward drifted
437→418. Churns at the ceiling, no gain. (Ordinary --resume would reset high →
likely degrade; --resume-hold-low avoided that and still no help.)

### FINAL (2026-06-15): compute-vs-decay study complete
Saturation curve (120 pinned tracks): 2M 1211 / 4M 1267 / 8M 1409 / 16M 1421;
resume-12M-holdlow 1414. The ~1410 ceiling = reached at ~8M, robust everywhere
(policy×chaos limit, not schedule). Docs updated (PROJECT_STATUS compute-vs-decay
section, CLAUDE). Figure compute_vs_decay.png. New infra: paired_ab.py,
combined_plot.py, train.py --resume-hold-low flag.
