"""Legacy obs design variants for evaluating historical checkpoints.

env.py was reverted to the 11-dim baseline because the larger obs designs
turned out to evaluate worse. But we still want to be able to load and
fairly evaluate the historical checkpoints that were trained against
those obs shapes (ppo_obs17, ppo_obs20, sac_first). This module keeps
the deleted obs code alive — but confined to diagnostics, so the main
codebase stays clean.

Mapping from historical run name → class here:
    ppo_obs17 (single 17, stacked 68)  → HillClimbEnv17Dim
    ppo_obs20 (single 20, stacked 80)  → HillClimbEnv20Dim
    sac_first (single 20, stacked 80)  → HillClimbEnv20Dim with continuous_action=True
"""

from __future__ import annotations

import bisect
import math
import os
import sys

import numpy as np
from gymnasium import spaces

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from env import HillClimbEnv  # noqa: E402
from constants import SCALE, CHASSIS_HEIGHT  # noqa: E402

# Same clearance mapping as env.py.
_GROUND_CLEARANCE_MIN = -3.0
_GROUND_CLEARANCE_MAX = 10.0
_CLEAR_CENTER = 0.5 * (_GROUND_CLEARANCE_MAX + _GROUND_CLEARANCE_MIN)
_CLEAR_HALF = 0.5 * (_GROUND_CLEARANCE_MAX - _GROUND_CLEARANCE_MIN)


def _base_obs_first5(env: HillClimbEnv) -> tuple:
    """Compute the first 5 obs dims (angle, on-ground, ang vel, vx, vy)
    without invoking the parent's full _get_obs (which would also do
    ground sampling we'd just throw away)."""
    car = env.car
    a = car.chassis_body.angle
    while a < 0.0:
        a += 2.0 * math.pi
    a = (a + math.pi) % (2.0 * math.pi)
    obs_angle = a / (2.0 * math.pi)

    on_ground_now = car.wheels[0].on_ground or car.wheels[1].on_ground
    env.last_grounded += 1
    if on_ground_now:
        env.last_grounded = 0
        obs_grounded = 1.0
    else:
        # COYOTE_FRAMES is 10 in env.py; keep that constant here.
        obs_grounded = 1.0 if env.last_grounded < 10 else 0.0

    av = car.chassis_body.angularVelocity
    obs_av = max(-1.0, min(1.0, av / 4.0))
    lv = car.chassis_body.linearVelocity
    obs_vx = max(-1.0, min(1.0, lv.x / 17.0))
    obs_vy = max(-1.0, min(1.0, lv.y / 12.0))
    return (obs_angle, obs_grounded, obs_av, obs_vx, obs_vy)


def _clearance_to_obs(pos_y_px: float, chassis_bottom_y_m: float) -> float:
    c = pos_y_px / SCALE - chassis_bottom_y_m
    c = max(_GROUND_CLEARANCE_MIN, min(_GROUND_CLEARANCE_MAX, c))
    return (c - _CLEAR_CENTER) / _CLEAR_HALF


class HillClimbEnv11DimDelta(HillClimbEnv):
    """5 base + 6 forward ground samples encoded as JS-style delta-from-first.

    The original ppo_hcr / ppo_fixed / ppo_stack checkpoints were trained
    against an env whose ground-sample encoding mirrored JS Player.look():
        inputs[i] = (positions[i] - positions[0]) / 100
    rather than the current env.py's absolute-clearance encoding. Evaluating
    those checkpoints against current env.py gives them a ~30 score (vs
    their historical ~990) because the input distribution they see at
    inference is completely different from what they trained on.

    No clip: matches JS exactly. Values can sit outside [-1, 1] in theory,
    but the JS divisor of 100 keeps typical terrain in that range.
    """

    LOOKAHEAD_N = 6
    LOOKAHEAD_SKIP = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        n_dim = 5 + self.LOOKAHEAD_N
        low = np.full(n_dim, -1.0, dtype=np.float32)
        low[0] = 0.0
        low[1] = 0.0
        # Delta encoding can exceed ±1 in extreme terrain; relax the bounds.
        low[5:] = -10.0
        high = np.ones(n_dim, dtype=np.float32)
        high[5:] = 10.0
        self.observation_space = spaces.Box(low=low, high=high, dtype=np.float32)

    def _get_obs(self) -> np.ndarray:
        base = _base_obs_first5(self)
        chassis_pos_m = self.car.chassis_body.position
        positions = self.ground.get_positions(
            chassis_pos_m.x, self.LOOKAHEAD_N, self.LOOKAHEAD_SKIP
        )
        # Delta from first sample, divided by 100 (pixels). JS-style.
        first_y = positions[0] if positions else 0.0
        samples = []
        for i in range(self.LOOKAHEAD_N):
            y_px = positions[i] if i < len(positions) else positions[-1]
            samples.append((y_px - first_y) / 100.0)
        return np.array([*base, *samples], dtype=np.float32)


class HillClimbEnv17Dim(HillClimbEnv):
    """5 base + 12 forward point samples at chassis_x + 0, 75, …, 825 px.

    Matches the ppo_obs17 checkpoint. After VecFrameStack(4) the policy sees 68 dims.
    """

    LOOKAHEAD_N = 12
    LOOKAHEAD_SKIP = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        n_dim = 5 + self.LOOKAHEAD_N
        low = np.full(n_dim, -1.0, dtype=np.float32)
        low[0] = 0.0
        low[1] = 0.0
        high = np.ones(n_dim, dtype=np.float32)
        self.observation_space = spaces.Box(low=low, high=high, dtype=np.float32)

    def _get_obs(self) -> np.ndarray:
        base = _base_obs_first5(self)
        chassis_pos_m = self.car.chassis_body.position
        positions = self.ground.get_positions(
            chassis_pos_m.x, self.LOOKAHEAD_N, self.LOOKAHEAD_SKIP
        )
        chassis_bottom_y = chassis_pos_m.y + CHASSIS_HEIGHT / SCALE
        samples = []
        for i in range(self.LOOKAHEAD_N):
            y_px = positions[i] if i < len(positions) else positions[-1]
            samples.append(_clearance_to_obs(y_px, chassis_bottom_y))
        return np.array([*base, *samples], dtype=np.float32)


# Segment edges for the 20-dim design (chassis-relative, meters).
# 3 rear + 12 forward with variable density. 16 edges → 15 segments.
_SEGMENT_EDGES_M = (
    -15.0, -7.5, -2.5,
    0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 17.0, 22.0, 28.0, 35.0, 45.0,
)


def _min_y_in_segments(ground, edges_px):
    """Local replica of the deleted Ground.get_min_y_in_segments — only
    used by HillClimbEnv20Dim, so it lives here instead of in ground.py."""
    v = ground.vectors
    n_main = max(0, len(v) - 2)  # exclude the two closing polygon vertices
    if n_main == 0:
        return [0.0] * max(0, len(edges_px) - 1)
    xs = [v[i][0] for i in range(n_main)]
    out = []
    for k in range(len(edges_px) - 1):
        lo, hi = edges_px[k], edges_px[k + 1]
        start = bisect.bisect_right(xs, lo)
        end = bisect.bisect_right(xs, hi)
        if start >= end:
            idx = min(max(0, start), n_main - 1)
            out.append(v[idx][1])
            continue
        min_y = v[start][1]
        for j in range(start + 1, end):
            if v[j][1] < min_y:
                min_y = v[j][1]
        out.append(min_y)
    return out


class HillClimbEnv20Dim(HillClimbEnv):
    """5 base + 15 segments (3 rear + 12 variable-density forward) via min-y pooling.

    Matches ppo_obs20 (discrete) and sac_first (continuous; pass
    continuous_action=True). After VecFrameStack(4) the policy sees 80 dims.
    """

    N_SEGMENTS = len(_SEGMENT_EDGES_M) - 1  # 15

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        n_dim = 5 + self.N_SEGMENTS
        low = np.full(n_dim, -1.0, dtype=np.float32)
        low[0] = 0.0
        low[1] = 0.0
        high = np.ones(n_dim, dtype=np.float32)
        self.observation_space = spaces.Box(low=low, high=high, dtype=np.float32)

    def _get_obs(self) -> np.ndarray:
        base = _base_obs_first5(self)
        chassis_pos_m = self.car.chassis_body.position
        chassis_x_px = chassis_pos_m.x * SCALE
        edges_px = [chassis_x_px + e * SCALE for e in _SEGMENT_EDGES_M]
        min_ys = _min_y_in_segments(self.ground, edges_px)
        chassis_bottom_y = chassis_pos_m.y + CHASSIS_HEIGHT / SCALE
        samples = []
        for i in range(self.N_SEGMENTS):
            y_px = min_ys[i] if i < len(min_ys) else min_ys[-1]
            samples.append(_clearance_to_obs(y_px, chassis_bottom_y))
        return np.array([*base, *samples], dtype=np.float32)
