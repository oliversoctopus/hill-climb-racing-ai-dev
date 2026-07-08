"""Curriculum support: a per-worker terrain pool that biases episode spawns
toward 'bottleneck' sections of the track.

Two ideas, combined:

1. **Empirical bottleneck detection (the reliable signal).** A bottleneck is,
   operationally, a place where cars actually die or stall. The env reports the
   x-position of every termination (head-crash, fell-off, or the 500-tick
   no-progress stall) and we accumulate it into a per-terrain histogram. Over
   repeated exposure that histogram concentrates on the spots this policy can't
   get past — which is exactly where we want more training. It is adaptive: a
   spot that's a wall at 2M steps stops attracting spawns once the car learns
   to clear it.

2. **Geometric prior (cold-start only).** The histogram is empty the first time
   a terrain is seen, so we seed spawn weights with a cheap geometric score
   (the same uphill-rise-over-a-window measure Ground.is_too_steep uses). It is
   only a prior: as real failure data arrives it dominates the geometry.

Because spawn-biasing needs to revisit the *same* track from different points,
terrains are reused from a small rolling pool rather than regenerated every
episode. New terrains enter the pool at the *current* curriculum difficulty, so
as difficulty anneals up the pool's terrains get harder and the easy early ones
age out.

The pool lives inside each HillClimbEnv (one per SubprocVecEnv worker); there is
no cross-process shared state.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

import numpy as np

from constants import SCALE, GROUND_SMOOTHNESS, SPAWN_X
from ground import make_ground

# Vertex index closest to the normal spawn x (where eval/the real game start),
# so 'full-track' pool episodes begin from the same place eval measures from.
_START_INDEX = max(0, int(round(SPAWN_X / GROUND_SMOOTHNESS)))

# Window (in vertices) over which we sum upcoming uphill rise for the geometric
# prior. 10 vertices = 150px = 5m, matching Ground.is_too_steep's horizon.
_GEOM_WINDOW = 10


def geometric_difficulty(vectors: List[Tuple[float, float]]) -> np.ndarray:
    """Per-vertex geometric hardness in [0, 1].

    For each vertex, sum the upcoming *uphill* rise (in meters) over the next
    ~9 segments — the same quantity Ground.is_too_steep thresholds on. A tall
    cumulative rise ahead means a steep wall; the exit wall of an awkward
    pothole shows up here too (you must climb out of it). Normalized to [0, 1]
    so it is comparable across terrains and against failure counts.
    """
    n = len(vectors)
    ys = np.fromiter((v[1] for v in vectors), dtype=np.float64, count=n)
    score = np.zeros(n, dtype=np.float64)
    for i in range(n - 1):
        total = 0.0
        end = min(i + _GEOM_WINDOW, n)
        prev = ys[i]
        for k in range(i + 1, end):
            d = prev - ys[k]          # y decreasing == terrain rising == uphill
            if d > 0.0:
                total += d
            prev = ys[k]
        score[i] = total / SCALE      # meters of rise
    m = float(score.max())
    if m > 0.0:
        score /= m
    return score


class Terrain:
    """One pooled track: its vectors, the geometric prior, and the running
    failure histogram (indexed by vertex)."""

    __slots__ = ("ground", "vectors", "n", "geom", "fail", "episodes")

    def __init__(self, ground) -> None:
        self.ground = ground
        self.vectors = ground.vectors
        self.n = len(self.vectors)
        self.geom = geometric_difficulty(self.vectors)
        self.fail = np.zeros(self.n, dtype=np.float64)
        self.episodes = 0

    def record_failure(self, x_px: float) -> None:
        """Tally a death/stall at world-x ``x_px`` onto the nearest vertex."""
        idx = int(round(x_px / GROUND_SMOOTHNESS))
        if 0 <= idx < self.n:
            self.fail[idx] += 1.0


class TerrainPool:
    """A small rolling pool of reused terrains with bottleneck-biased spawns."""

    def __init__(
        self,
        seed_base: int,
        *,
        pool_size: int = 12,
        refresh_every: int = 40,
        bottleneck_prob: float = 0.6,
        approach_px: float = 180.0,
        fail_weight: float = 1.0,
    ) -> None:
        self.pool_size = max(1, pool_size)
        self.refresh_every = max(1, refresh_every)
        self.bottleneck_prob = float(bottleneck_prob)
        # How far *before* a detected bottleneck to drop the car, so it gets a
        # short run-up and practices the approach + the obstacle, not just the
        # obstacle from a dead stop. In vertices.
        self.approach = max(1, int(round(approach_px / GROUND_SMOOTHNESS)))
        self.fail_weight = float(fail_weight)
        self._rng = random.Random(seed_base)
        self._entries: List[Terrain] = []
        self._episodes = 0

    def reseed(self, seed: int) -> None:
        """Reset the pool for a fresh deterministic sequence (env got a new seed)."""
        self._rng = random.Random(seed)
        self._entries = []
        self._episodes = 0

    # ------------------------------------------------------------------
    def _new_terrain(self, difficulty: float) -> Terrain:
        seed = self._rng.uniform(1.0, 1_000_000.0)
        return Terrain(make_ground(seed, difficulty))

    def select(self, difficulty: float) -> Tuple[Terrain, int]:
        """Pick a terrain (growing/refreshing the pool as needed) and a spawn
        vertex index. New terrains are built at the current difficulty."""
        if len(self._entries) < self.pool_size:
            self._entries.append(self._new_terrain(difficulty))
        elif self._episodes % self.refresh_every == 0:
            # Retire the oldest, add one at the current (higher) difficulty.
            self._entries.pop(0)
            self._entries.append(self._new_terrain(difficulty))
        self._episodes += 1

        entry = self._rng.choice(self._entries)
        entry.episodes += 1
        return entry, self._sample_spawn(entry)

    # ------------------------------------------------------------------
    def _sample_spawn(self, entry: Terrain) -> int:
        """Choose a spawn vertex. With prob (1 - bottleneck_prob) spawn at the
        normal start so the policy keeps learning the full track; otherwise pick
        a hard spot weighted by (geometric prior + failure history) and back off
        by ``approach`` vertices for a run-up."""
        start = _START_INDEX
        if self._rng.random() >= self.bottleneck_prob:
            return start

        n = entry.n
        lo = start + self.approach
        hi = n - 30  # stay clear of the closing/wrap vertices at the tail
        if hi <= lo:
            return start

        weights = entry.geom[lo:hi] + self.fail_weight * entry.fail[lo:hi]
        total = float(weights.sum())
        if total <= 1e-9:
            return start  # nothing hard yet (e.g. easy early-difficulty terrain)

        r = self._rng.random() * total
        acc = 0.0
        target = lo
        for j in range(lo, hi):
            acc += float(weights[j - lo])
            if acc >= r:
                target = j
                break

        spawn = max(start, target - self.approach)
        # Nudge to the locally flattest vertex nearby so the car lands cleanly
        # instead of materializing on a slope and tipping over immediately.
        a = max(start, spawn - 3)
        b = min(n - 1, spawn + 4)
        best, best_v = spawn, float(entry.geom[spawn])
        for j in range(a, b):
            v = float(entry.geom[j])
            if v < best_v:
                best, best_v = j, v
        return best
