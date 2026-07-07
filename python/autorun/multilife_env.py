"""E3: MultiLifeEnv — K lives per terrain with previous-death obs markers.

Targets the measured human adaptive-retry advantage: a human reaches ~90%
completion in ~5 ADAPTIVE retries (remembering where they died) vs the AI's
67.5% in 8 i.i.d. attempts. This env gives the policy the same adaptivity:
  - the SAME terrain for `lives_per_terrain` consecutive episodes (a "trial"),
    then a fresh terrain;
  - `n_markers` extra obs dims encoding where the policy died on PREVIOUS lives
    of this trial, so it can change its micro-approach to a known-deadly spot.

Markers-only design (the minimal sound test): each life is still its own PPO
episode with the standard per-life progress reward; the ONLY cross-life channel
is the marker obs. If marker-conditioned behaviour helps, this is the cleanest
way to detect it. (Follow-up if promising: a true multi-life episode where credit
flows across lives.)

Obs layout = HillClimbEnv base obs (12-dim per-wheel) + n_markers:
  marker 0: signed distance to the NEAREST previous-death x AHEAD of the chassis,
            normalized to [-1,+1] over [0, MARK_RANGE_PX]; +1 = none ahead / far,
            close danger -> -1.
  marker 1 (if n_markers>=2): life index within the trial, life 1 -> -1, last
            life -> +1 (so the policy knows how many retries remain).

Subclasses HillClimbEnv and only overrides reset/step/_build_obs + the obs space,
leaving the champion hot-path untouched (the base env is imported unmodified).
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np
from gymnasium import spaces

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from constants import SCALE  # noqa: E402
from env import HillClimbEnv  # noqa: E402

MARK_RANGE_PX = 600.0  # 20 m: how far ahead a previous-death marker is "visible"


class MultiLifeEnv(HillClimbEnv):
    def __init__(self, *, lives_per_terrain: int = 6, n_markers: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.lives_per_terrain = max(1, int(lives_per_terrain))
        self.n_markers = max(1, int(n_markers))

        # Extend the observation space by n_markers (markers live in [-1, 1]).
        base_low = self.observation_space.low
        base_high = self.observation_space.high
        low = np.concatenate([base_low, np.full(self.n_markers, -1.0, np.float32)])
        high = np.concatenate([base_high, np.full(self.n_markers, 1.0, np.float32)])
        self.observation_space = spaces.Box(low=low, high=high, dtype=np.float32)

        self._life_in_trial = 0          # 1-based once a life has started
        self._death_positions: list[float] = []  # px, previous deaths this trial
        self._last_death_px: Optional[float] = None

    # ------------------------------------------------------------------
    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        first_ever = (self._js is None or self._ground is None)
        new_trial = first_ever or (self._life_in_trial >= self.lives_per_terrain)

        if not new_trial and self._last_death_px is not None:
            # Retry on the SAME terrain: remember where the just-ended life died.
            self._death_positions.append(float(self._last_death_px))

        if new_trial:
            self.randomize_terrain = True    # base reset() -> fresh terrain
            self._death_positions = []
            self._life_in_trial = 0
        else:
            self.randomize_terrain = False   # base reset() -> respawn same terrain

        self._life_in_trial += 1          # before super().reset() so _build_obs
        obs, info = super().reset(seed=seed, options=options)  # sees this life's index
        self._last_death_px = None
        return obs, info

    # ------------------------------------------------------------------
    def step(self, action):
        obs, reward, terminated, truncated, info = super().step(action)
        if terminated or truncated:
            self._last_death_px = float(self._max_dist_px)
        return obs, reward, terminated, truncated, info

    # ------------------------------------------------------------------
    def _build_obs(self, state: dict) -> np.ndarray:
        base = super()._build_obs(state)
        chassis_x_px = state["x"] * SCALE
        markers = np.empty(self.n_markers, dtype=np.float32)

        # marker 0: nearest previous-death AHEAD of the chassis.
        ahead = [d for d in self._death_positions if d >= chassis_x_px]
        if ahead:
            dist = min(ahead) - chassis_x_px
            markers[0] = float(np.clip(dist / MARK_RANGE_PX, 0.0, 1.0) * 2.0 - 1.0)
        else:
            markers[0] = 1.0  # none ahead -> "all clear"

        # marker 1: life index within the trial.
        if self.n_markers >= 2:
            denom = max(1, self.lives_per_terrain - 1)
            li = max(0, self._life_in_trial - 1)
            markers[1] = float(li / denom) * 2.0 - 1.0
        for j in range(2, self.n_markers):
            markers[j] = 0.0

        return np.concatenate([base, markers]).astype(np.float32)
