# python/tests

Real correctness tests (as opposed to the one-off probes in `diagnostics/`).

Run them with the venv python:

```powershell
python\.venv\Scripts\python.exe python\tests\test_vectorized_ground.py
python\.venv\Scripts\python.exe python\tests\test_saverestore.py
```

- **test_vectorized_ground.py** — asserts the numpy terrain generation is
  bitwise-identical to the scalar reference (`Ground._randomize_scalar` /
  `_is_too_steep_scalar`, `P5Noise.noise` vs `noise_array`). These scalar
  reference methods exist *for this test* — do not delete them.
- **test_saverestore.py** — characterizes `JSPhysics.save_state()/restore_state()`
  fidelity (the backtracking/MPC search depends on it). Needs
  `checkpoints/seed2_resume_11611776_steps.zip`.
