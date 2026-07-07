"""Localize the source of the SPONTANEOUS counterclockwise chassis rotation.

Background (user report): with NO key pressed and the wheels barely spinning,
the chassis develops a slow angular velocity "from 0" — e.g. when coasting off
the end of a track. The motor (stalled or stuck-on) and the driver ragdoll are
ruled out (ragdoll mass ~0.002 kg vs chassis ~5+ kg); see the plan file.

Leading hypothesis: the rim->chassis suspension *distance* joint is configured at
frequencyHz=70 / dampingRatio=25 (Wheel.js:53-54). At a 1/30 s step, 70 Hz is far
past the solver's stability range, so the over-stiff spring can inject a small
impulse each step; because the chassis is front-heavy/asymmetric the left/right
residuals don't cancel and leak a net torque into the chassis.

This script measures it directly using the SAME JS physics that runs in the
browser/training (js_backend.JSPhysics), with the motor OFF the whole time:

  * Per tick it logs chassis angular velocity and each wheel's PRISMATIC reaction
    torque (GetReactionTorque = inv_dt*m_impulse.y = the exact rotational torque
    the suspension transmits rim->chassis), plus the revolute (motor-joint)
    reaction torque (should be ~0 with the motor off) and motor-enabled state.
  * It runs three motor-off scenarios: settle-at-rest, coast (initial velocity),
    and drive-then-coast (calibrates the "flip-over" sign, then cuts the motor).
  * It A/Bs the STOCK suspension against a stability-corrected one (freq 10,
    damping 1) injected as a patched Wheel.js string into a separate V8 context
    -- no repo file is modified.

Read-only: writes nothing except stdout. Run:
  python\\.venv\\Scripts\\python.exe python\\diagnostics\\torque_probe.py [track_seed]
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from py_mini_racer import py_mini_racer  # noqa: E402

import js_backend as JB  # noqa: E402
from ground import make_ground  # noqa: E402
from constants import SPAWN_X  # noqa: E402
import random  # noqa: E402

INV_DT = 30.0  # js_backend steps at 1/30 s

# JS injected into a backend's context: a per-tick probe + a coast helper.
_PROBE_JS = r"""
function _rt(j) { return j ? j.GetReactionTorque(%(inv_dt)s) : 0.0; }
function probe() {
  var c = _car.chassisBody;
  var w0 = _car.wheels[0], w1 = _car.wheels[1];
  return JSON.stringify({
    ang_vel: c.GetAngularVelocity(),
    angle:   c.GetAngle(),
    x: c.GetPosition().x, y: c.GetPosition().y,
    vx: c.GetLinearVelocity().x,
    motor0: !!w0.joint.m_enableMotor, motor1: !!w1.joint.m_enableMotor,
    wheel_w0: w0.body.GetAngularVelocity(), wheel_w1: w1.body.GetAngularVelocity(),
    rev0: _rt(w0.joint),     rev1: _rt(w1.joint),       // motor-joint angular reaction (~0 when off)
    pris0: _rt(w0.prisJoint), pris1: _rt(w1.prisJoint),  // suspension rotational torque into chassis
    on0: (w0.onGround === true), on1: (w1.onGround === true),
    dead: !!_car.player.kindaDead
  });
}
// Give the WHOLE car a forward velocity (motor stays off) so it coasts over
// terrain and off the end -- reproduces "coasting, no input" dynamically.
function setCoast(vx) {
  var bs = [_car.chassisBody, _car.wheels[0].body, _car.wheels[0].rimBody,
            _car.wheels[1].body, _car.wheels[1].rimBody,
            _car.person.torso.body, _car.person.head.body];
  for (var i = 0; i < bs.length; i++) {
    var v = bs[i].GetLinearVelocity();
    bs[i].SetLinearVelocity(new Vec2(vx, v.y));
    bs[i].SetAwake(true);
  }
}
""" % {"inv_dt": INV_DT}


def make_backend(patched: bool = False, no_line226: bool = False):
    """A JSPhysics with optionally-patched physics source.

    `patched`    : soften the suspension distance joint (freq 70->10, damp 25->1).
    `no_line226` : remove Car.js:226 `chassisBody.ApplyTorque(-this.rotationTorque)`
                   -- the hand-added forward-only chassis torque.
    Bypasses JSPhysics.__init__ so we can swap source; everything else is
    byte-identical to the real backend.
    """
    wheel_src = JB._read("Wheel.js")
    if patched:
        before = wheel_src
        wheel_src = wheel_src.replace("distJointDef.frequencyHz = 70;",
                                      "distJointDef.frequencyHz = 10;")
        wheel_src = wheel_src.replace("distJointDef.dampingRatio = 25;",
                                      "distJointDef.dampingRatio = 1;")
        assert wheel_src != before, "patch did not match Wheel.js suspension lines"

    car_src = JB._read("Car.js")
    if no_line226:
        before = car_src
        car_src = car_src.replace("this.chassisBody.ApplyTorque(-this.rotationTorque);",
                                  "/* line226 removed for probe */")
        assert car_src != before, "patch did not match Car.js line 226"

    ctx = py_mini_racer.MiniRacer()
    ctx.eval(JB._read("libraries/Box2d.js"))
    ctx.eval(JB._POLYFILLS)
    ctx.eval(wheel_src)
    ctx.eval(JB._read("Person.js"))
    ctx.eval(car_src)
    ctx.eval(JB._DRIVER)
    ctx.eval(_PROBE_JS)

    phys = JB.JSPhysics.__new__(JB.JSPhysics)
    phys.ctx = ctx
    return phys


def flat_track_with_edge(ground_y=500.0, spawn_x=150.0, edge_x=1500.0, step_px=10.0):
    """A minimal flat track that simply STOPS at edge_x (no closing wall), so a
    car coasting past edge_x drives off into empty space. Returns (verts,
    spawn_x, spawn_y)."""
    verts = [(float(x), ground_y) for x in
             np.arange(0.0, edge_x + step_px, step_px)]
    spawn_y = ground_y - 70.0   # chassis center ~ wheel+chassis above ground
    return verts, spawn_x, spawn_y


def run_offedge(phys, coast_vx=15.0, n_ticks=500, settle=40):
    """Flat track, motor OFF the whole time. Settle, launch forward, coast off
    the edge. Returns rows; airborne ticks are where on0==on1==False."""
    verts, sx, sy = flat_track_with_edge()
    phys.build_world(verts, sx, sy)
    for _ in range(settle):
        phys.step(2)
    phys.ctx.eval(f"setCoast({float(coast_vx)})")
    rows = []
    for t in range(n_ticks):
        phys.step(2)
        r = probe(phys); r["t"] = t
        rows.append(r)
        if r["y"] > 30.0:   # fell well below the track (meters) -> done
            break
    return rows


def airborne_drift(rows):
    """Mean chassis ang_vel over the airborne phase (both wheels off ground)."""
    air = [r["ang_vel"] for r in rows if not r["on0"] and not r["on1"]]
    if len(air) < 5:
        return float("nan"), 0
    return float(np.mean(air)), len(air)


def probe(phys) -> dict:
    import json
    return json.loads(phys.ctx.eval("probe()"))


def run_scenario(phys, ground, name, n_ticks, coast_vx=None,
                 drive_ticks=0):
    """Step the world for n_ticks. Motor OFF except for an optional initial
    `drive_ticks` of forward (action 0) to calibrate the flip-over sign; the
    rest is action 2 (off). Returns per-tick arrays."""
    phys.build_world(ground.vectors, SPAWN_X, ground.spawning_y)
    if coast_vx is not None:
        # let it settle one tick on the ground, then launch
        phys.step(2)
        phys.ctx.eval(f"setCoast({float(coast_vx)})")

    rows = []
    for t in range(n_ticks):
        act = 0 if t < drive_ticks else 2   # 0=forward, 2=off
        phys.step(act)
        p = probe(phys)
        p["t"] = t
        p["act"] = act
        rows.append(p)
        if p["dead"]:
            break
    return rows


def _off_rows(rows, off_from):
    return [r for r in rows if r["t"] >= off_from
            and not r["motor0"] and not r["motor1"]]


def drift(rows, off_from=0, window=150):
    """Persistent late-window mean chassis ang_vel over the motor-off portion --
    a steady DC bias, not a landing transient. Negative = flip-over direction."""
    off = _off_rows(rows, off_from)
    if len(off) < 5:
        return float("nan")
    av = np.array([r["ang_vel"] for r in off])
    return float(av[-min(window, len(av)):].mean())


def summarize(rows, label, off_from=0):
    """Print stats over the MOTOR-OFF portion (t >= off_from)."""
    off = _off_rows(rows, off_from)
    if not off:
        print(f"  {label}: no motor-off ticks captured")
        return None
    av = np.array([r["ang_vel"] for r in off])
    pris = np.array([r["pris0"] + r["pris1"] for r in off])
    rev = np.array([abs(r["rev0"]) + abs(r["rev1"]) for r in off])
    print(f"  {label}: ticks={len(off)}  late-drift={drift(rows, off_from):+.4f}  "
          f"max|av|={np.abs(av).max():.4f}  mean av={av.mean():+.4f}")
    print(f"      suspension torque sum (prismatic): "
          f"mean={pris.mean():+.4f}  max|.|={np.abs(pris).max():.3f}   "
          f"|motor-joint reaction| max={rev.max():.4g}")
    return drift(rows, off_from)


def coast_sweep(seeds):
    """Scenario B across many pinned tracks: late-window drift, stock vs patched.
    Each backend is rebuilt per track via build_world (no cross-track state)."""
    stock = make_backend(patched=False)
    patched = make_backend(patched=True)
    s_drift, p_drift = [], []
    for sd in seeds:
        random.seed(sd)
        g = make_ground(None, difficulty=0.0)
        s_drift.append(drift(run_scenario(stock, g, "B", 900, coast_vx=12.0)))
        p_drift.append(drift(run_scenario(patched, g, "B", 900, coast_vx=12.0)))
    s = np.array(s_drift)
    p = np.array(p_drift)
    print(f"=== coast sweep: {len(seeds)} tracks, motor OFF, late-window drift ===")
    print(f"  STOCK   drift: mean={s.mean():+.4f}  |mean|={np.abs(s).mean():.4f}  "
          f"per-track={np.round(s, 3).tolist()}")
    print(f"  PATCHED drift: mean={p.mean():+.4f}  |mean|={np.abs(p).mean():.4f}  "
          f"per-track={np.round(p, 3).tolist()}")
    print(f"  STOCK |drift| > PATCHED |drift| on {int((np.abs(s) > np.abs(p)).sum())}"
          f"/{len(seeds)} tracks")
    print(f"  mean |drift| reduction: "
          f"{100*(1 - np.abs(p).mean()/max(np.abs(s).mean(),1e-9)):.0f}%\n")


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 987_000
    print(f"[torque_probe] pinned track seed={seed}, difficulty=0.0, motor OFF")
    print(f"  hypothesis: over-stiff suspension (Wheel.js freq=70/damp=25) leaks "
          f"a net torque into the asymmetric chassis.\n")

    random.seed(seed)
    ground = make_ground(None, difficulty=0.0)

    stock = make_backend(patched=False)
    patched = make_backend(patched=True)

    # --- Calibrate the flip-over sign: drive forward briefly, read ang_vel sign ---
    cal = run_scenario(stock, ground, "calib", n_ticks=40, drive_ticks=40)
    drive_av = np.mean([r["ang_vel"] for r in cal[-15:]])
    flip_sign = "+" if drive_av > 0 else "-"
    print(f"[calibration] driving forward -> chassis ang_vel ~ {drive_av:+.3f} "
          f"(this '{flip_sign}' sign is the 'flips the car' direction)\n")

    scenarios = [
        # (name, n_ticks, coast_vx, drive_ticks, off_from)
        ("A. settle at rest (off from spawn)",      900, None, 0,  0),
        ("B. coast forward, motor off",             900, 12.0, 0,  0),
        ("C. drive 120t then cut motor & coast",    900, None, 120, 120),
    ]

    for name, n, vx, dr, off_from in scenarios:
        print(f"=== {name} ===")
        rs_stock = run_scenario(stock, ground, name, n, coast_vx=vx, drive_ticks=dr)
        rs_patch = run_scenario(patched, ground, name, n, coast_vx=vx, drive_ticks=dr)
        f_stock = summarize(rs_stock, "STOCK   (freq70/damp25)", off_from)
        f_patch = summarize(rs_patch, "PATCHED (freq10/damp1) ", off_from)
        if f_stock is not None and f_patch is not None:
            print(f"      => |ang_vel| stock={abs(f_stock):.4f}  "
                  f"patched={abs(f_patch):.4f}  "
                  f"reduction={100*(1-abs(f_patch)/max(abs(f_stock),1e-9)):.0f}%")
        print()

    # Robustness: late-window drift across many pinned tracks (scenario B).
    coast_sweep([seed + 1000 * k for k in range(8)])

    # --- Report #2: coast OFF THE EDGE with the motor off (the literal scenario) ---
    print("=== off-edge: coast off a cliff, motor OFF -- airborne chassis rotation ===")
    for vx in (8.0, 15.0):
        s_rows = run_offedge(make_backend(), coast_vx=vx)
        p_rows = run_offedge(make_backend(patched=True), coast_vx=vx)
        sd, sn = airborne_drift(s_rows)
        pd, pn = airborne_drift(p_rows)
        print(f"  coast_vx={vx:>4}:  STOCK airborne ang_vel mean={sd:+.4f} (n={sn})   "
              f"PATCHED mean={pd:+.4f} (n={pn})")
    print()

    # --- Report #1: how much of the forward-flip is Car.js:226 vs motor reaction? ---
    print("=== forward-hold flip: stock Car.js vs line-226 removed (hold forward) ===")
    random.seed(seed)
    g226 = make_ground(None, difficulty=0.0)
    for label, be in (("STOCK Car.js   ", make_backend()),
                      ("no line226     ", make_backend(no_line226=True))):
        rows = run_scenario(be, g226, "fwd", n_ticks=120, drive_ticks=120)
        av = np.array([r["ang_vel"] for r in rows])
        print(f"  {label}: ang_vel after 120t fwd: mean(last30)={av[-30:].mean():+.3f}  "
              f"max|av|={np.abs(av).max():.3f}")
    print()

    print("Read: if STOCK builds a nonzero chassis ang_vel with the motor off and "
          "the PATCHED suspension removes/shrinks it, the over-stiff distance "
          "joint is the source. The prismatic torque sum is the rim->chassis "
          "channel carrying it; the motor-joint reaction should stay ~0.")


if __name__ == "__main__":
    main()
