"""Direct port of p5.js's noise() function (libraries/p5.js:26926).

p5 uses *value* noise with cosine-smoothstep interpolation — NOT the gradient
Perlin we use in python/ground.py. Different algorithm, different terrain
shape character. This port matches the p5 implementation byte-for-byte so we
can benchmark our agent on terrain identical to what the original Code Bullet
game produces.
"""

from __future__ import annotations

import math
import random

import numpy as np


PERLIN_YWRAPB = 4
PERLIN_YWRAP = 1 << PERLIN_YWRAPB         # 16
PERLIN_ZWRAPB = 8
PERLIN_ZWRAP = 1 << PERLIN_ZWRAPB         # 256
PERLIN_SIZE = 4095
PERLIN_OCTAVES = 4
PERLIN_AMP_FALLOFF = 0.5


def _scaled_cosine(i: float) -> float:
    return 0.5 * (1.0 - math.cos(i * math.pi))


class P5Noise:
    """One instance per terrain. seed selects the perlin lookup table."""

    def __init__(self, seed: int):
        # p5 uses Math.random() for the perlin array; we use a seeded Python
        # RNG so we can get deterministic terrains. The CHARACTER (4 octaves,
        # cosine fade, value-noise lookups) is identical either way.
        rng = random.Random(seed)
        self.perlin = [rng.random() for _ in range(PERLIN_SIZE + 1)]
        # float64 copy for the vectorized path (same doubles, zero conversion loss)
        self._perlin_np = np.array(self.perlin, dtype=np.float64)

    def noise(self, x: float, y: float = 0.0, z: float = 0.0) -> float:
        if x < 0: x = -x
        if y < 0: y = -y
        if z < 0: z = -z

        xi = int(math.floor(x))
        yi = int(math.floor(y))
        zi = int(math.floor(z))
        xf = x - xi
        yf = y - yi
        zf = z - zi

        r = 0.0
        ampl = 0.5

        for _ in range(PERLIN_OCTAVES):
            of_ = xi + (yi << PERLIN_YWRAPB) + (zi << PERLIN_ZWRAPB)
            rxf = _scaled_cosine(xf)
            ryf = _scaled_cosine(yf)

            n1 = self.perlin[of_ & PERLIN_SIZE]
            n1 += rxf * (self.perlin[(of_ + 1) & PERLIN_SIZE] - n1)
            n2 = self.perlin[(of_ + PERLIN_YWRAP) & PERLIN_SIZE]
            n2 += rxf * (self.perlin[(of_ + PERLIN_YWRAP + 1) & PERLIN_SIZE] - n2)
            n1 += ryf * (n2 - n1)

            of_ += PERLIN_ZWRAP
            n2 = self.perlin[of_ & PERLIN_SIZE]
            n2 += rxf * (self.perlin[(of_ + 1) & PERLIN_SIZE] - n2)
            n3 = self.perlin[(of_ + PERLIN_YWRAP) & PERLIN_SIZE]
            n3 += rxf * (self.perlin[(of_ + PERLIN_YWRAP + 1) & PERLIN_SIZE] - n3)
            n2 += ryf * (n3 - n2)

            n1 += _scaled_cosine(zf) * (n2 - n1)

            r += n1 * ampl
            ampl *= PERLIN_AMP_FALLOFF
            xi <<= 1; xf *= 2
            yi <<= 1; yf *= 2
            zi <<= 1; zf *= 2
            if xf >= 1.0:
                xi += 1; xf -= 1
            if yf >= 1.0:
                yi += 1; yf -= 1
            if zf >= 1.0:
                zi += 1; zf -= 1
        return r

    def noise_array(self, xs: np.ndarray) -> np.ndarray:
        """Vectorized ``noise(x)`` for an array of x values (y = z = 0).

        BITWISE-identical to calling ``noise(x)`` per element (asserted by
        tests/test_vectorized_ground.py): with y = z = 0 the scalar
        algorithm's y/z lerp terms are ``+= 0.0 * (...)`` no-ops, so each
        octave reduces to a single table lerp — replicated here with the
        exact same FP operation order. np.cos matches math.cos bitwise
        (verified on this platform; the test would catch a divergence).
        """
        x = np.abs(np.asarray(xs, dtype=np.float64))
        xi = np.floor(x).astype(np.int64)
        xf = x - np.floor(x)

        r = np.zeros_like(x)
        ampl = 0.5
        perlin = self._perlin_np

        for _ in range(PERLIN_OCTAVES):
            rxf = 0.5 * (1.0 - np.cos(xf * math.pi))
            n1 = perlin[xi & PERLIN_SIZE]
            n1 = n1 + rxf * (perlin[(xi + 1) & PERLIN_SIZE] - n1)
            r = r + n1 * ampl
            ampl *= PERLIN_AMP_FALLOFF
            xi = xi << 1
            xf = xf * 2
            carry = xf >= 1.0
            xi = xi + carry
            xf = xf - carry
        return r
