"""Diff trace_js.json (from measure.html) vs trace_py.json (from measure.py).

Prints a per-quantity summary table and saves a side-by-side plot. The goal
is to make the JS↔Python physics divergence visible and measurable.

Usage:
    python compare.py
    python compare.py --plot out.png        # only generate the plot
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import List, Dict, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(name: str) -> List[Dict]:
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        sys.exit(f"missing {path} — run measure.html (JS) and measure.py (Python) first")
    with open(path) as f:
        data = json.load(f)
    return data["trace"] if isinstance(data, dict) and "trace" in data else data


# Per-quantity weight for the aggregate "physics divergence score". Lower
# weight on quantities that scale with x (since acceleration error compounds).
WEIGHTS = {
    "cx": 1.0,
    "cy": 5.0,           # vertical motion is mostly bounce — high weight
    "cangle": 50.0,      # rotation is the most subjectively felt parameter
    "cvx": 5.0,
    "cvy": 10.0,
    "comega": 5.0,
    "hx": 1.0, "hy": 5.0,
    "tx": 1.0, "ty": 5.0,
    "w0x": 1.0, "w0y": 5.0, "w0a": 0.5,
    "w1x": 1.0, "w1y": 5.0, "w1a": 0.5,
}


def summary_table(js: List[Dict], py: List[Dict]) -> Tuple[Dict[str, float], float]:
    n = min(len(js), len(py))
    keys = [k for k in js[0] if k != "tick"]
    rms: Dict[str, float] = {}
    score = 0.0
    print(f"{'quantity':<10} {'rms diff':>12} {'js final':>12} {'py final':>12}")
    print("-" * 50)
    for k in keys:
        sq = 0.0
        for t in range(n):
            d = js[t][k] - py[t][k]
            sq += d * d
        r = math.sqrt(sq / n)
        rms[k] = r
        score += WEIGHTS.get(k, 1.0) * r
        print(f"{k:<10} {r:>12.4f} {js[-1][k]:>12.3f} {py[-1][k]:>12.3f}")
    print("-" * 50)
    print(f"weighted divergence score:  {score:.2f}   (lower is closer to JS)")
    return rms, score


def plot(js: List[Dict], py: List[Dict], out_path: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plot] matplotlib not installed; skipping plot")
        return

    n = min(len(js), len(py))
    ticks = [r["tick"] for r in js[:n]]

    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True)
    panels = [
        ("cx",     "chassis x (px)"),
        ("cy",     "chassis y (px)"),
        ("cangle", "chassis angle (rad)"),
        ("cvx",    "chassis vx (m/s)"),
        ("cvy",    "chassis vy (m/s)"),
        ("comega", "chassis omega (rad/s)"),
    ]
    for ax, (key, label) in zip(axes.flat, panels):
        ax.plot(ticks, [r[key] for r in js[:n]], label="JS", color="#28a", linewidth=1.5)
        ax.plot(ticks, [r[key] for r in py[:n]], label="Py", color="#e62", linewidth=1.5, linestyle="--")
        ax.set_title(label)
        ax.axvline(30, color="gray", linestyle=":", alpha=0.5)
        ax.grid(alpha=0.3)
        ax.legend(loc="best", fontsize=8)
    axes[-1, 0].set_xlabel("tick")
    axes[-1, 1].set_xlabel("tick")
    plt.suptitle("JS (Box2D.js 2.0) vs Python (pybox2d 2.3.10)\nflat ground, 30 settle + 120 throttle ticks", fontsize=11)
    plt.tight_layout()
    plt.savefig(out_path, dpi=110)
    print(f"[plot] saved {out_path}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plot", default="trace_diff.png", help="output plot path")
    p.add_argument("--no-plot", action="store_true")
    args = p.parse_args()

    js = load("trace_js.json")
    py = load("trace_py.json")
    print(f"JS: {len(js)} ticks   Py: {len(py)} ticks\n")

    summary_table(js, py)

    if not args.no_plot:
        plot(js, py, os.path.join(ROOT, args.plot))


if __name__ == "__main__":
    main()
