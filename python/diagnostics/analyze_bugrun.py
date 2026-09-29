"""Analyze a bug-run recording exported from ai_play.html's Bug-probe panel.

The browser tool records the human car's full state every tick (chassis pose +
angular velocity, per-wheel motor-enabled state + spin + on-ground, the motor
joint and suspension reaction torques, key/action, and the zero-G flag), plus
any moments you flagged with the "Flag unusual" button.

This reads that JSON and, around each flag (and over the whole run), reports the
signature of the spontaneous rotation: did chassis angular velocity grow while
the motor was OFF / wheels OFF the ground / under zero-G? That distinguishes a
pure joint/solver artifact from a contact/drivetrain effect.

Usage:
  python\\.venv\\Scripts\\python.exe python\\diagnostics\\analyze_bugrun.py <hcr_bugrun_*.json>
"""
import json
import sys


def fmt_row(r):
    return (f"  t={r['tick']:>6}  act={r['act']}  keys={'R' if r['keyR'] else '-'}"
            f"{'L' if r['keyL'] else '-'}  zeroG={'Y' if r['zeroG'] else '.'}  "
            f"on={'1' if r['on0'] else '0'}{'1' if r['on1'] else '0'}  "
            f"motor={'1' if r['motor0'] else '0'}{'1' if r['motor1'] else '0'}  "
            f"angVel={r['angVel']:+.4f}  wheelW=({r['wheelW0']:+.2f},{r['wheelW1']:+.2f})  "
            f"prisSum={r['pris0'] + r['pris1']:+.3f}  revSum={r['rev0'] + r['rev1']:+.4g}")


def segments_motoroff_spin(ticks, thresh=0.05):
    """Find runs where |angVel| exceeds thresh while BOTH motors are off."""
    segs, cur = [], None
    for r in ticks:
        spinning = (abs(r["angVel"]) > thresh) and not r["motor0"] and not r["motor1"]
        if spinning and cur is None:
            cur = [r, r]
        elif spinning:
            cur[1] = r
        elif cur is not None:
            segs.append(cur); cur = None
    if cur is not None:
        segs.append(cur)
    return segs


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    ticks = data.get("ticks", [])
    flags = meta.get("flags", [])
    print(f"[analyze_bugrun] {sys.argv[1]}")
    print(f"  mode={meta.get('mode')}  frame_rate={meta.get('frame_rate')}  "
          f"ticks={len(ticks)}  flags={len(flags)}  "
          f"ground_verts={len(data.get('ground', []))}")
    if not ticks:
        print("  no ticks recorded."); return
    by_tick = {r["tick"]: i for i, r in enumerate(ticks)}

    # Overall: how much rotation happens with the motor off, and under zero-G?
    off = [r for r in ticks if not r["motor0"] and not r["motor1"]]
    zg = [r for r in ticks if r["zeroG"]]
    zg_off = [r for r in zg if not r["motor0"] and not r["motor1"]]
    def stats(rows, name):
        if not rows:
            print(f"  {name}: (none)"); return
        av = [abs(r["angVel"]) for r in rows]
        pr = [r["pris0"] + r["pris1"] for r in rows]
        print(f"  {name}: n={len(rows)}  max|angVel|={max(av):.4f}  "
              f"mean|angVel|={sum(av)/len(av):.4f}  "
              f"prisSum mean={sum(pr)/len(pr):+.3f}")
    print("\n--- overall ---")
    stats(ticks, "all ticks      ")
    stats(off, "motor-OFF ticks")
    stats(zg, "zero-G ticks   ")
    stats(zg_off, "zero-G & off   ")

    # The decisive test: under zero-G with no motor, does the chassis spin up
    # from rest? (pure joint/solver artifact). Show the zero-G angVel envelope.
    if zg_off:
        first, last = zg_off[0], zg_off[-1]
        print(f"\n  ZERO-G + motor-off envelope: angVel {first['angVel']:+.4f} "
              f"(t={first['tick']}) -> {last['angVel']:+.4f} (t={last['tick']})  "
              f"max|.|={max(abs(r['angVel']) for r in zg_off):.4f}")
        print("  => if this grows from ~0, the spin is a pure joint/solver artifact "
              "(no gravity, no ground).")

    # Motor-off spin segments.
    segs = segments_motoroff_spin(ticks)
    print(f"\n--- motor-off spin segments (|angVel|>0.05, both motors off): "
          f"{len(segs)} ---")
    for s in segs[:8]:
        a, b = s
        dur = b["tick"] - a["tick"] + 1
        print(f"  t={a['tick']}..{b['tick']} ({dur} ticks)  "
              f"angVel {a['angVel']:+.3f}->{b['angVel']:+.3f}  "
              f"on-ground={'Y' if (a['on0'] or a['on1']) else 'N'}  "
              f"zeroG={'Y' if a['zeroG'] else 'N'}")

    # Windows around each flag.
    for fi, fl in enumerate(flags):
        ft = fl.get("tick")
        idx = by_tick.get(ft)
        print(f"\n--- flag #{fi+1} at tick {ft} ---")
        if idx is None:
            print("  (tick not in buffer — recording may have wrapped)"); continue
        lo, hi = max(0, idx - 45), min(len(ticks), idx + 15)
        for r in ticks[lo:hi]:
            mark = "  <== FLAG" if r["tick"] == ft else ""
            print(fmt_row(r) + mark)


if __name__ == "__main__":
    main()
