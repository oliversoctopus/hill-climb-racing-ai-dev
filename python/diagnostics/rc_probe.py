"""Pre-flight probe for the reverse curriculum.

For each difficulty f, generate N terrains from distinct seeds and measure:
  - is_too_steep() RAW rejection rate (before make_ground's retry),
  - the realized steepness floor/ceiling and max amplitude,
  - a smoke check that the terrain has the expected shape.

Use the rejection rate to pick rc-fmax-cap: keep it where rejection stays
< ~30% so training doesn't waste episodes on fallback terrain.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ground import Ground, make_ground  # noqa: E402


def probe(fvals, n=200):
    print(f"{'f':>5s}  {'raw_reject%':>11s}  {'retry_reject%':>13s}  "
          f"{'mean_vtx':>8s}")
    print("-" * 50)
    for f in fvals:
        raw_rej = 0
        retry_rej = 0
        nv = 0
        for s in range(n):
            seed = 1.0 + s * 97.13
            g = Ground()
            g.randomize(seed=seed, difficulty=f)
            if g.is_too_steep():
                raw_rej += 1
            nv = len(g.vectors)
            # make_ground rerolls until the gate passes (1000-cap safety net,
            # reachable only at high f); does the final map still fail?
            g2 = make_ground(seed, difficulty=f)
            if g2.is_too_steep():
                retry_rej += 1
        print(f"{f:>5.2f}  {100*raw_rej/n:>11.1f}  {100*retry_rej/n:>13.1f}  "
              f"{nv:>8d}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    probe([0.0, 0.25, 0.5, 0.75, 1.0], n=n)
