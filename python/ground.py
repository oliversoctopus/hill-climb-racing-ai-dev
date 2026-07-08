"""Terrain generator (port of Ground.js randomizeGround).

Produces the list of (x_px, y_px) vectors in *pixel* space (like the JS version),
plus the grass-sprite picks and the spawn Y. The Box2D bodies are built from these
vectors by the JS backend (js_backend.py _buildGroundBodies), which mirrors
Ground.js's dual-layer setup: a dirt body (collides with the chassis) and a grass
body offset up by grassThickness/SCALE (collides with wheels/person).
"""

from __future__ import annotations

import json
import random
from typing import List, Tuple

import numpy as np

from constants import (
    SCALE,
    CANVAS_WIDTH,
    CANVAS_HEIGHT,
    GROUND_DISTANCE,
    GROUND_SMOOTHNESS,
    GROUND_GRASS_THICKNESS,
    GROUND_DIFFICULTY,
    SPAWN_VECTOR_INDEX,
    SPAWN_Y_BACK_FROM_GROUND,
)

# Terrain generator: p5.js's exact noise() algorithm (see p5_noise.py), so the
# terrain distribution matches the actual Code Bullet game.
from p5_noise import P5Noise as _P5Noise


class _P5NoiseAdapter:
    """Wraps P5Noise to expose a scalar .fractal(x) + vectorized .fractal_array(xs)."""

    def __init__(self, seed: int):
        self._noise = _P5Noise(int(seed))

    def fractal(self, x: float, octaves: int = 4, persistence: float = 0.5) -> float:
        # p5 noise() already does 4-octave 0.5-falloff internally.
        return self._noise.noise(x)

    def fractal_array(self, xs: np.ndarray) -> np.ndarray:
        # Vectorized path — bitwise-identical to fractal() per element.
        return self._noise.noise_array(xs)


_NoiseClass = _P5NoiseAdapter

_perlin_state = {"gen": _NoiseClass(0)}


def _perlin(x: float) -> float:
    return _perlin_state["gen"].fractal(x)


class Ground:
    """Holds the vertex list (in pixel space) and the two Box2D static bodies."""

    def __init__(self) -> None:
        self.vectors: List[Tuple[float, float]] = []  # (x_px, y_px)
        self.grass_positions: List[int] = []  # 2 entries per vector (sprite index or -1)
        self.distance = GROUND_DISTANCE
        self.smoothness = GROUND_SMOOTHNESS
        self.grass_thickness = GROUND_GRASS_THICKNESS
        self.steepness_level = 50 + GROUND_DIFFICULTY
        self.spawning_y: float = 0.0

    # ------------------------------------------------------------------
    # Terrain generation (mirrors Ground.js randomizeGround)
    # ------------------------------------------------------------------
    def randomize(self, seed: float | None = None, difficulty: float = 0.0) -> None:
        """Generate terrain. ``difficulty=0`` (the default, and everything the live
        env/eval uses) is normal terrain.

        RETIRED EXPERIMENT: ``difficulty`` (``f``) > 0 is the reverse-curriculum
        knob (tested, no benefit — see PROJECT_STATUS / the archived trainer). It's
        kept functional because the rc_* diagnostics still exercise it, but nothing
        on the live training/eval path sets f > 0.

        ``f`` in [0, 1] raises the steepness FLOOR while the ceiling stays
        fixed at normal's hardest (250). Tracks get harder *overall* but never
        *steeper* than terrain that already occurs in normal play.

        - ``f = 0.0`` -> exactly normal: the original 130->250 steepness ramp,
          i.e. the terrain distribution the current champion was trained on AND
          what eval uses. (Special-cased so it is byte-identical to the old code.)
        - ``f = 0.5`` -> floor 190 -> 250 (starts ≈ "score-1000" hardness).
        - ``f = 1.0`` -> floor 250 -> 250: the whole track as steep as the
          game's hardest segment.

        Steepness drives both the Perlin frequency (line below) and the height
        amplitude (``max_height``); raising the floor packs more of the hard
        later-terrain bottlenecks across the whole track. A flat 500px intro
        plus a lead-in ramp (so a high floor isn't an instant wall off the
        start) keep early momentum, mimicking the normal spawn.

        Vertex computation is numpy-vectorized (the gate's reroll-until-pass
        loop made the pure-Python version ~22x7 ms per terrain); the result is
        BITWISE-identical to the scalar reference ``_randomize_scalar`` —
        asserted by ``tests/test_vectorized_ground.py``. The grass-RNG
        loop stays scalar: it consumes the global ``random`` stream with
        data-dependent branching, and vertex computation consumes none, so
        running it after the vertices preserves the exact draw sequence.
        """
        f = max(0.0, min(1.0, float(difficulty)))
        if seed is None:
            seed = random.uniform(0, 100000)
        gen = _NoiseClass(int(seed * 1000) & 0x7FFFFFFF)
        _perlin_state["gen"] = gen
        starting_point = float(seed)

        # Steepness profile. f raises the floor (130 -> 130+120f); the ceiling
        # is pinned at normal's max (250). f=0 reproduces the original
        # 130->250 ramp exactly. For f>0, after the flat intro the floor ramps
        # in over `lead_in_px` so the car has a runway before the hard terrain.
        flat_length = 500
        steep_floor = 130.0 + 120.0 * f
        steep_ceil = 250.0
        lead_in_px = 1500.0

        xs = np.arange(0, self.distance, self.smoothness, dtype=np.float64)
        if f <= 0.0:
            steep = _map(xs, 0, self.distance, 130.0, steep_ceil)
        else:
            base = _map(xs, 0, self.distance, steep_floor, steep_ceil)
            # Lead-in pulls steepness down toward 130 right after the intro,
            # easing up to the full `base` floor over lead_in_px.
            t = np.where(xs < flat_length, 0.0,
                         np.minimum(1.0, (xs - flat_length) / lead_in_px))
            steep = 130.0 + (base - 130.0) * t
        self.steepness_level = float(steep[-1])

        in_flat = xs < flat_length
        nx = np.where(in_flat, starting_point,
                      starting_point + (xs - flat_length) / (700 - steep))
        noised_y = gen.fractal_array(nx)
        height_addition = np.where(in_flat, (flat_length - xs) / 7.0, 0.0)

        max_height = 300 + _map(steep, 0, 200, 0, 350)
        min_height = 30
        ys = CANVAS_HEIGHT - _map(noised_y, 0, 1, min_height, max_height) + height_addition
        self.vectors.extend(zip(xs.tolist(), ys.tolist()))

        self._randomize_grass(len(self.vectors))
        self._append_closing_vertices()

    def _randomize_scalar(self, seed: float, difficulty: float = 0.0) -> None:
        """Pre-vectorization reference implementation (kept verbatim for the
        bitwise-equality test and for noise classes without an array path)."""
        f = max(0.0, min(1.0, float(difficulty)))
        _perlin_state["gen"] = _NoiseClass(int(seed * 1000) & 0x7FFFFFFF)
        starting_point = float(seed)

        flat_length = 500
        steep_floor = 130.0 + 120.0 * f
        steep_ceil = 250.0
        lead_in_px = 1500.0

        i = 0
        while i < self.distance:
            if f <= 0.0:
                self.steepness_level = _map(i, 0, self.distance, 130.0, steep_ceil)
            else:
                base = _map(i, 0, self.distance, steep_floor, steep_ceil)
                if i < flat_length:
                    t = 0.0
                else:
                    t = min(1.0, (i - flat_length) / lead_in_px)
                self.steepness_level = 130.0 + (base - 130.0) * t

            if i < flat_length:
                noised_y = _perlin(starting_point)
                height_addition = (flat_length - i) / 7.0
            else:
                noised_y = _perlin(starting_point + (i - flat_length) / (700 - self.steepness_level))
                height_addition = 0.0

            max_height = 300 + _map(self.steepness_level, 0, 200, 0, 350)
            min_height = 30
            y = CANVAS_HEIGHT - _map(noised_y, 0, 1, min_height, max_height) + height_addition
            self.vectors.append((float(i), float(y)))

            # 2 grass slots per vector (one at vector, one halfway to next)
            for _ in range(2):
                if random.random() < 0.05:
                    self.grass_positions.append(random.randint(0, 4))
                elif (
                    i != 0
                    and self.grass_positions
                    and self.grass_positions[-1] != -1
                    and random.random() < 0.7
                ):
                    pick = random.randint(0, 4)
                    if pick == self.grass_positions[-1]:
                        pick = random.randint(0, 4)
                    self.grass_positions.append(pick)
                else:
                    self.grass_positions.append(-1)

            i += self.smoothness

        self._append_closing_vertices()

    def _randomize_grass(self, num_vertices: int) -> None:
        """Grass sprite picks — identical RNG draws/branching to the scalar
        loop (which interleaved them per vertex; vertices consume no global
        RNG, so a separate pass sees the same stream)."""
        for idx in range(num_vertices):
            for _ in range(2):
                if random.random() < 0.05:
                    self.grass_positions.append(random.randint(0, 4))
                elif (
                    idx != 0
                    and self.grass_positions
                    and self.grass_positions[-1] != -1
                    and random.random() < 0.7
                ):
                    pick = random.randint(0, 4)
                    if pick == self.grass_positions[-1]:
                        pick = random.randint(0, 4)
                    self.grass_positions.append(pick)
                else:
                    self.grass_positions.append(-1)

    def _append_closing_vertices(self) -> None:
        # closing vertices (matches Ground.js)
        self.vectors.append((self.distance, CANVAS_HEIGHT + self.grass_thickness * 2))
        self.vectors.append((0.0, CANVAS_HEIGHT + self.grass_thickness * 2))

        self.spawning_y = self.vectors[SPAWN_VECTOR_INDEX][1] - SPAWN_Y_BACK_FROM_GROUND

    # Mirrors Ground.js isTooSteep — looks at upcoming y-deltas and rejects
    # tracks that have an immediate-uphill wall the car can't climb.
    # numpy-vectorized (the reroll-until-pass loop calls this ~22x per
    # terrain); per-window sums accumulate in the same order as the scalar
    # reference below, so the decision is bitwise-identical (asserted by
    # tests/test_vectorized_ground.py).
    def is_too_steep(self) -> bool:
        n = len(self.vectors)
        if n < 2:
            return False
        ys = np.fromiter((p[1] for p in self.vectors), dtype=np.float64, count=n)
        rises = np.maximum(0.0, ys[:-1] - ys[1:])  # rises[j] = max(0, y[j]-y[j+1])
        # Window i sums rises[i .. min(i+8, n-2)] — add the 9 shifted slices
        # sequentially (k = 0..8) to replicate the scalar accumulation order.
        m = n - 1
        acc = np.zeros(m, dtype=np.float64)
        for k in range(min(9, m)):
            acc[: m - k] += rises[k:]
        return bool(np.any(acc / SCALE > 5.0))

    def _is_too_steep_scalar(self) -> bool:
        """Pre-vectorization reference (kept for the bitwise-equality test)."""
        v = self.vectors
        n = len(v)
        for i in range(n - 1):
            total = 0.0
            end = min(i + 10, n)
            for k in range(i + 1, end):
                total += max(0.0, v[k - 1][1] - v[k][1])
            if total / SCALE > 5.0:  # JS threshold is 5 meters
                return True
        return False

    # ------------------------------------------------------------------
    # JSON IO (for terrain parity with JS playtest)
    # ------------------------------------------------------------------
    def load_json(self, path: str) -> None:
        with open(path, "r") as f:
            data = json.load(f)
        self.vectors = [(float(v["x"]), float(v["y"])) for v in data["vectors"]]
        self.grass_positions = list(data.get("grass", []))
        if "distance" in data:
            self.distance = float(data["distance"])
        if len(self.vectors) > SPAWN_VECTOR_INDEX:
            self.spawning_y = self.vectors[SPAWN_VECTOR_INDEX][1] - SPAWN_Y_BACK_FROM_GROUND

    def save_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(
                {
                    "vectors": [{"x": v[0], "y": v[1]} for v in self.vectors],
                    "grass": self.grass_positions,
                    "distance": self.distance,
                },
                f,
            )


def _map(x: float, a: float, b: float, c: float, d: float) -> float:
    if b == a:
        return c
    return c + (d - c) * ((x - a) / (b - a))


def make_ground(seed: float | None, difficulty: float = 0.0) -> "Ground":
    """Build a terrain at the given difficulty ``f``, retrying seeds that come
    out impassably steep. ``f=0`` (default) is normal; higher ``f`` raises the
    steepness floor (reverse curriculum). See ``Ground.randomize``.

    The reroll loop matches the real game (sketch.js:234): reroll until
    ``is_too_steep()`` passes. The gate rejects ~97% of raw maps (~33 rerolls
    on average at f=0), so it is the DEFINING filter of the game's terrain
    distribution — the old 10-reroll cap accepted a too-steep map ~73% of the
    time and made our terrain much steeper than the actual game. The 1000-cap
    is a safety net for high ``difficulty`` (raised steepness floor): at f=0
    it is never hit (~22 rolls avg, ~160 ms); at f=1.0 the pass rate drops to
    ~0.2%, so a map averages ~2 s and ~13% of calls exhaust the cap and return
    a too-steep map anyway (measured 2026-06-06).
    """
    attempts = 0
    cur_seed = float(seed) if seed is not None else None
    while True:
        ground = Ground()
        ground.randomize(seed=cur_seed, difficulty=difficulty)
        if not ground.is_too_steep():
            return ground
        attempts += 1
        cur_seed = None  # reroll
        if attempts >= 1000:
            return ground  # safety net (high-difficulty only) — see docstring
