"""Probe whether tweaking pybox2d's solver tolerances actually changes anything."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import Box2D
from wheel_drift_test import run_drop_test, build_wheel_joint_rig, build_3joint_rig


CASES = [
    ("b2WheelJoint freq=6 damp=0.8",
     lambda w, c: build_wheel_joint_rig(w, c, freq=6.0, damp=0.8)),
    ("b2WheelJoint freq=70 damp=25",
     lambda w, c: build_wheel_joint_rig(w, c, freq=70.0, damp=25.0)),
    ("3-joint rim=0.2",
     lambda w, c: build_3joint_rig(w, c, rim_density=0.2)),
    ("3-joint rim=1.0",
     lambda w, c: build_3joint_rig(w, c, rim_density=1.0)),
]


def banner(s):
    print()
    print("=" * 80)
    print(s)
    print("=" * 80)
    print(f"  linearSlop={Box2D.b2_linearSlop:.5f}  baumgarte={Box2D.b2_baumgarte:.3f}  "
          f"maxLinearCorrection={Box2D.b2_maxLinearCorrection:.4f}")


def sweep(angular_kick: float):
    for label, builder in CASES:
        r = run_drop_test(builder, angular_kick=angular_kick)
        mm = r['max_drift_m'] * 1000
        fm = r['final_drift_m'] * 1000
        print(f"  {label:<36s}  max={mm:6.1f}mm  final={fm:6.1f}mm")


def main():
    banner("Defaults (slop=5mm, baumgarte=0.2)")
    sweep(angular_kick=500.0)

    Box2D.b2_linearSlop = 0.0005
    Box2D.b2_baumgarte  = 0.5
    Box2D.b2_maxLinearCorrection = 0.01
    banner("Tightened (slop=0.5mm, baumgarte=0.5, maxCorrection=10mm)")
    sweep(angular_kick=500.0)

    Box2D.b2_linearSlop = 0.00005
    Box2D.b2_baumgarte  = 0.9
    Box2D.b2_maxLinearCorrection = 0.005
    banner("Very tight (slop=0.05mm, baumgarte=0.9, maxCorrection=5mm)")
    sweep(angular_kick=500.0)


if __name__ == "__main__":
    main()
