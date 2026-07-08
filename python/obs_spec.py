"""Single source of truth for the PPO observation encoding and policy topology.

The obs vector the policy consumes is built in TWO runtimes that must agree
bit-for-bit, or the model sees out-of-distribution input:
  - training / eval : python/env.py       HillClimbEnv._build_obs
  - browser         : web/ai_policy.js    PpoOnnxAgent  (via web/policy_meta.json)

To keep them in sync, the normalization constants and topology live HERE.
`export_onnx.py` serializes this module to `web/policy_meta.json` next to the
ONNX model; `web/ai_policy.js` loads that JSON and validates it fail-closed.
See CONVENTIONS.md #4.

Conventions: meters are the internal spatial unit (#1); angles are radians (#2).
"""
from __future__ import annotations

from constants import CHASSIS_HEIGHT

# --- Topology --------------------------------------------------------------
# PER_WHEEL / REAR_N are fixed for the deployed champion. A checkpoint's actual
# LOOKAHEAD_N is recovered from its obs width at export time, so the lookahead-13
# experiment exports correctly without editing this file.
PER_WHEEL = True          # 2 grounded bits (rear + front) vs 1 legacy bit
LOOKAHEAD_N = 6           # forward ground samples (default; per-env override HCR_LOOKAHEAD_N)
LOOKAHEAD_SKIP = 5        # vertices between samples (5 * 15px smoothness = 75px)
REAR_N = 0                # rearward samples (disabled; see env.py GROUND_REAR_N note)
REAR_SKIP = 5
N_STACK = 4               # VecFrameStack depth (SB3)

# --- Normalization (fixed; IDENTICAL in Python and JS) ---------------------
COYOTE_FRAMES = 10        # keep grounded=1 for this many ticks after liftoff
ANG_VEL_SCALE = 4.0       # ang_vel (rad/s) / this, then clip to [-1, 1]
VX_SCALE = 17.0           # vx (m/s)        / this, then clip to [-1, 1]
VY_SCALE = 12.0           # vy (m/s)        / this, then clip to [-1, 1]
CLEARANCE_MIN_M = -3.0    # ground-clearance clip (meters), then mapped to [-1, 1]
CLEARANCE_MAX_M = 10.0
CHASSIS_HEIGHT_PX = CHASSIS_HEIGHT   # chassis-bottom reference for clearance


def base_dims(per_wheel: bool = PER_WHEEL) -> int:
    """Non-ground obs dims: angle + grounded(1 or 2) + angvel + vx + vy."""
    return 6 if per_wheel else 5


def n_obs(per_wheel: bool = PER_WHEEL,
          lookahead_n: int = LOOKAHEAD_N,
          rear_n: int = REAR_N) -> int:
    """Single-frame obs width (before VecFrameStack)."""
    return base_dims(per_wheel) + lookahead_n + rear_n


def to_dict(per_wheel: bool = PER_WHEEL,
            lookahead_n: int = LOOKAHEAD_N,
            rear_n: int = REAR_N,
            n_stack: int = N_STACK) -> dict:
    """Serialize the obs spec for web/policy_meta.json (consumed by ai_policy.js).
    `n_obs` is one frame; `input_width` is the stacked ONNX input width."""
    no = n_obs(per_wheel, lookahead_n, rear_n)
    return {
        "schema": 1,
        "per_wheel": per_wheel,
        "lookahead_n": lookahead_n,
        "lookahead_skip": LOOKAHEAD_SKIP,
        "rear_n": rear_n,
        "rear_skip": REAR_SKIP,
        "n_stack": n_stack,
        "coyote_frames": COYOTE_FRAMES,
        "ang_vel_scale": ANG_VEL_SCALE,
        "vx_scale": VX_SCALE,
        "vy_scale": VY_SCALE,
        "clearance_min_m": CLEARANCE_MIN_M,
        "clearance_max_m": CLEARANCE_MAX_M,
        "chassis_height_px": CHASSIS_HEIGHT_PX,
        "n_obs": no,
        "input_width": no * n_stack,
    }
