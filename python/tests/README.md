# python/tests

Correctness tests and doc checks (the one-off probes live in `diagnostics/`). `run.py` runs all of them; each also runs on its own.

```powershell
python\.venv\Scripts\python.exe python\tests\run.py
```

- **test_vectorized_ground.py** — asserts the numpy terrain generation is bitwise-identical to the scalar reference (`Ground._randomize_scalar` / `_is_too_steep_scalar`, `P5Noise.noise` vs `noise_array`). These scalar reference methods exist *for this test* — do not delete them.
- **test_saverestore.py** — characterizes `JSPhysics.save_state()/restore_state()` fidelity (the backtracking/MPC search depends on it). Needs `checkpoints/seed2_resume_11611776_steps.zip`.
- **test_obs_parity.py** — loads `web/ai_policy.js` in V8 and asserts its `_buildObs` produces byte-identical obs to `env.py._build_obs` (the obs formula is hand-mirrored across the two runtimes).
- **doc_refs.py**: every `CONVENTIONS` / `PROJECT_STATUS` / `CLAUDE.md` *Heading* pointer names a real heading, nothing cites a rule by number, code never points at `CLAUDE.md`, and backticked paths in the reference docs exist.
- **voice.py**: the writing rules. Filler phrases are banned in docs and comments; phrases with real uses (em-dash, "rather than", "simply"/"just", …) are capped per thousand words of each doc. Reference docs carry no narrated history, `CLAUDE.md` stays under 1,500 words, and it and `CONVENTIONS.md` carry no dates. Comment blocks over 2 lines, docstrings over 10, and dates or measured figures in comments are flagged on lines changed since HEAD (`--all-lines` for the whole repo).
- **`../unwrap_md.py`**: Markdown is one line per paragraph.
