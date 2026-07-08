"""Cross-runtime obs parity (CONVENTIONS.md #9): the observation vector is built
by two independent implementations that MUST compute the same thing —
  python/env.py       HillClimbEnv._build_obs   (training / eval)
  web/ai_policy.js    PpoOnnxAgent._buildObs     (browser)
Their normalization constants are single-sourced via web/policy_meta.json, but
the FORMULAS are hand-mirrored, so this test loads ai_policy.js in V8 and checks
that both produce byte-identical obs for a range of controlled physical states.
It also serves as a syntax/exports check on ai_policy.js.

Run:  python\\.venv\\Scripts\\python.exe python\\tests\\test_obs_parity.py
"""
import os, sys, json

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # python/
REPO = os.path.dirname(ROOT)                      # repo root
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from py_mini_racer import py_mini_racer  # noqa: E402
import env as E  # noqa: E402

META = json.load(open(os.path.join(REPO, "web", "policy_meta.json"), encoding="utf-8"))
AI_JS = open(os.path.join(REPO, "web", "ai_policy.js"), encoding="utf-8").read()

# Controlled states: (y_m, vx, vy, angle, ang_vel, rear_grounded, front_grounded,
# ground_samples_m). Chosen to exercise: nominal, negative/ wrapped angle,
# airborne (both off), and velocity clipping.
CASES = [
    (5.0,  3.0, -1.5,  0.2,  0.5, True,  False, [6.0, 6.2, 6.5, 7.0, 5.0, 4.0]),
    (8.0, -2.0,  0.0, -1.3, -3.0, False, True,  [9.0, 8.5, 8.0, 7.5, 7.0, 6.5]),
    (3.0, 40.0, 30.0,  6.5,  9.0, False, False, [3.1, 3.0, 2.9, 2.8, 2.7, 2.6]),
    (10.0, 0.1, 0.1,   0.0,  0.0, True,  True,  [12.0, 11.0, 4.0, 20.0, 1.0, 5.0]),
]


def _py_obs(case):
    y, vx, vy, angle, av, rear, front, ground = case
    e = E.HillClimbEnv(per_wheel_obs=True, lookahead_n=META["lookahead_n"])
    e.last_grounded_rear = 0
    e.last_grounded_front = 0
    state = {"angle": angle, "ang_vel": av, "vx": vx, "vy": vy, "y": y,
             "on_ground_now": rear or front, "on_ground_rear": rear, "on_ground_front": front,
             "ground_samples": ground, "ground_samples_rear": []}
    return np.asarray(e._build_obs(state), dtype=np.float32)


def _js_ctx():
    ctx = py_mini_racer.MiniRacer()
    ctx.eval("var window = {};\n" + AI_JS + """
    function __obsCase(metaJson, caseJson) {
      var meta = JSON.parse(metaJson), s = JSON.parse(caseJson);
      var a = new window.AiPolicy.PpoOnnxAgent("x");
      a.meta = meta;
      a._obsScratch = new Float32Array(meta.n_obs);
      a._lastGroundedRear = 0; a._lastGroundedFront = 0; a._frameStack = [];
      var ctx = {scale: 30,
        car: {chassisBody: {
          GetPosition:        function(){ return {x: 0.0, y: s.y}; },
          GetLinearVelocity:  function(){ return {x: s.vx, y: s.vy}; },
          GetAngle:           function(){ return s.angle; },
          GetAngularVelocity: function(){ return s.av; }},
          wheels: [{onGround: s.rear}, {onGround: s.front}]},
        ground: {getPositions: function(x, n, skip){ return s.ground.slice(0, n); }}};
      return JSON.stringify(Array.prototype.slice.call(a._buildObs(ctx)));
    }
    """)
    return ctx


def main():
    ctx = _js_ctx()
    n_fail = 0
    for i, case in enumerate(CASES):
        y, vx, vy, angle, av, rear, front, ground = case
        py = _py_obs(case)
        js_json = ctx.call("__obsCase", json.dumps(META),
                           json.dumps({"y": y, "vx": vx, "vy": vy, "angle": angle,
                                       "av": av, "rear": rear, "front": front, "ground": ground}))
        js = np.asarray(json.loads(js_json), dtype=np.float32)
        d = float(np.abs(py - js).max()) if py.shape == js.shape else float("inf")
        ok = py.shape == js.shape == (META["n_obs"],) and d == 0.0
        print(f"  case {i}: shape py{py.shape}/js{js.shape}  max|py-js|={d:.3e}  {'OK' if ok else 'FAIL'}")
        if not ok:
            n_fail += 1
    if n_fail:
        sys.exit(f"[test_obs_parity] {n_fail}/{len(CASES)} cases FAILED — "
                 f"ai_policy.js._buildObs diverged from env.py._build_obs")
    print(f"[test_obs_parity] ALL PASS — JS _buildObs == Python _build_obs on {len(CASES)} states")


if __name__ == "__main__":
    main()
