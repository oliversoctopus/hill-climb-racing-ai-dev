"""Bitwise-equality test: vectorized terrain generation vs the scalar reference.

The numpy paths (P5Noise.noise_array, Ground.randomize, Ground.is_too_steep)
must produce EXACTLY the same doubles/decisions as the pure-Python originals
(Ground._randomize_scalar / _is_too_steep_scalar) — same vertices, same grass
RNG stream, same spawning_y, same gate verdicts. Any platform/numpy change
that breaks FP parity (e.g. a SIMD cos that differs from math.cos) fails here.

Run:  python\\.venv\\Scripts\\python.exe python\\tests\\test_vectorized_ground.py
"""
import os, sys, random

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from p5_noise import P5Noise  # noqa: E402
from ground import Ground  # noqa: E402


def test_noise_array(n_seeds=20, n_x=5000):
    rng = random.Random(123)
    for _ in range(n_seeds):
        seed = rng.randrange(0, 2**31)
        pn = P5Noise(seed)
        # cover the actual usage range: starting_point ~U(0,100000) + offsets
        xs = np.array([rng.uniform(0, 100050) for _ in range(n_x)])
        vec = pn.noise_array(xs)
        for j in range(n_x):
            s = pn.noise(float(xs[j]))
            assert s == float(vec[j]), (
                f"noise mismatch seed={seed} x={xs[j]!r}: scalar={s!r} vec={vec[j]!r}")
    print(f"[ok] noise_array bitwise == noise  ({n_seeds} tables x {n_x} xs)")


def test_randomize(n_seeds=30, fvals=(0.0, 0.35, 0.7, 1.0)):
    checked_gate = 0
    for s in range(n_seeds):
        for f in fvals:
            terrain_seed = 1.0 + s * 97.13
            random.seed(s * 7919)        # grass RNG stream
            g_vec = Ground(); g_vec.randomize(seed=terrain_seed, difficulty=f)
            random.seed(s * 7919)
            g_ref = Ground(); g_ref._randomize_scalar(seed=terrain_seed, difficulty=f)

            assert len(g_vec.vectors) == len(g_ref.vectors)
            for a, b in zip(g_vec.vectors, g_ref.vectors):
                assert a[0] == b[0] and a[1] == b[1], (
                    f"vertex mismatch seed={s} f={f}: {a!r} vs {b!r}")
            assert g_vec.grass_positions == g_ref.grass_positions, (
                f"grass mismatch seed={s} f={f}")
            assert g_vec.spawning_y == g_ref.spawning_y
            assert g_vec.steepness_level == g_ref.steepness_level

            assert g_vec.is_too_steep() == g_vec._is_too_steep_scalar(), (
                f"gate mismatch seed={s} f={f}")
            checked_gate += 1
    print(f"[ok] randomize bitwise == scalar  ({n_seeds} seeds x {len(fvals)} f) "
          f"+ {checked_gate} gate verdicts")


def test_seedless_rng_stream(n=10):
    # seed=None draws the terrain seed from the global RNG before grass —
    # the vectorized path must consume the exact same stream.
    for s in range(n):
        random.seed(s)
        g_vec = Ground(); g_vec.randomize(seed=None, difficulty=0.0)
        random.seed(s)
        drawn = random.uniform(0, 100000)
        g_ref = Ground(); g_ref._randomize_scalar(seed=drawn, difficulty=0.0)
        assert g_vec.vectors == g_ref.vectors, f"seedless vertex mismatch s={s}"
        assert g_vec.grass_positions == g_ref.grass_positions
    print(f"[ok] seed=None path consumes identical RNG stream  ({n} streams)")


if __name__ == "__main__":
    test_noise_array()
    test_randomize()
    test_seedless_rng_stream()
    print("ALL PASS — vectorized terrain is bitwise-identical to the scalar reference")
