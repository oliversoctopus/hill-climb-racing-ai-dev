# Archive

Retired code kept for reference. **Do NOT delete this folder or anything in it
unless the user explicitly says so.**

- `train_reverse_curriculum.py` — train.py as of 2026-06-06, before the CLI
  cleanup: contains the reverse-curriculum machinery (`--reverse-curriculum`,
  `--rc-fmax-cap`, `--rc-warmup-frac`, `--rc-ramp-frac`) and the opt-in
  `--per-wheel` / `--reward-shaping` flags. The curriculum tested as no benefit
  (PROJECT_STATUS experiment log); the LR/entropy decay it gated is now
  always-on in train.py.
- `train_sac.py` — SAC trainer. Tested 2026-05: wasted effort (the motor is
  on/off, so SAC's continuous action space buys nothing). eval.py's SAC
  support (`--algo`/`--ab-algo`) was removed at the same time.
- `planner.py` — retired test-time MPC/planning overlay on the frozen policy
  (receding-horizon rollouts in the JS sim). Tested 2026-06-16: NO benefit —
  chaos defeats foresight at every horizon (H=90 hurt completion 50%→17%). Moved
  here 2026-07-07 (was `python/planner.py`); its paths were repointed to `ROOT`
  so it still runs via `python archive/planner.py`.
- `curriculum.py` — support module for the (retired) bottleneck-spawn curriculum:
  a per-worker terrain pool biasing spawns toward where cars die. Imported by
  nothing on the live path; kept with its sibling `train_reverse_curriculum.py`.
- `run_rc_ab.sh`, `run_nodecay.sh`, `run_p5_sweep.py` — launchers for the
  reverse-curriculum A/B, the no-decay control, and the May 2026 flag sweep
  (results in PROJECT_STATUS). They invoke retired train.py flags, so they
  error against today's train.py — historical records only.

Old command lines map to the new train.py as:
`--per-wheel --reward-shaping --reverse-curriculum --rc-fmax-cap 0.0` ≡ (no flags — all default now).
