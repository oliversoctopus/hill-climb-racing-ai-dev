"""Prototype: load JS Box2D + game classes into V8, simulate a car, time it.

If this works at a reasonable speed (>500 steps/sec), it's the path forward
for training against JS physics.

What we load (in order, mimicking measure.html's setup):
  - polyfills (p5 helpers, sketch.js globals like SCALE, collision categories)
  - libraries/Box2d.js
  - Wheel.js, Person.js, Car.js
  - Ground.js (for terrain)
Then we expose a tiny JS API:
  - setup(seed) -> builds world, ground, car
  - step(action) -> applies action (0/1/2), runs world.Step, returns obs JSON
"""

import json
import os
import sys
import time

from py_mini_racer import py_mini_racer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ----------------------------------------------------------------
# Polyfills + globals — copied from measure.html's <script> block.
# These let Car.js / Wheel.js / Person.js run outside a browser.
# ----------------------------------------------------------------
POLYFILLS = r"""
function createVector(x, y) { return { x: x, y: y }; }
function color() { return null; }
var canvas = { width: 1280, height: 720 };
var PI = Math.PI;
var TWO_PI = 2 * Math.PI;
function abs(x)   { return Math.abs(x); }
function floor(x) { return Math.floor(x); }
function min(a,b) { return Math.min(a,b); }
function max(a,b) { return Math.max(a,b); }
function map(v,a,b,c,d) { return c + (d-c) * ((v-a)/(b-a)); }
function constrain(v,lo,hi) { return Math.min(hi, Math.max(lo, v)); }

// Globals referenced inside Car/Wheel/Person but never used on the physics path.
var panX = 0, panY = 0, nextPanX = 0;
var humanPlaying = true;   // disables Car.js "no progress => dead"
var fightMode = false;
var humanPlayer = null;
var reset = false;
var SCALE = 30;

// Collision categories (same as sketch.js)
var WHEEL_CATEGORY  = 0x0001;
var CHASSIS_CATEGORY= 0x0002;
var GRASS_CATEGORY  = 0x0004;
var DIRT_CATEGORY   = 0x0008;
var PERSON_CATEGORY = 0x0010;
var WHEEL_MASK   = GRASS_CATEGORY;
var CHASSIS_MASK = DIRT_CATEGORY;
var GRASS_MASK   = WHEEL_CATEGORY | PERSON_CATEGORY;
var DIRT_MASK    = CHASSIS_CATEGORY;
var PERSON_MASK  = GRASS_CATEGORY;

// Box2D shorthands
var Vec2 = Box2D.Common.Math.b2Vec2;
var b2BodyDef = Box2D.Dynamics.b2BodyDef;
var b2Body = Box2D.Dynamics.b2Body;
var b2FixtureDef = Box2D.Dynamics.b2FixtureDef;
var b2World = Box2D.Dynamics.b2World;
var b2PolygonShape = Box2D.Collision.Shapes.b2PolygonShape;
var b2CircleShape  = Box2D.Collision.Shapes.b2CircleShape;
var b2StaticBody  = Box2D.Dynamics.b2Body.b2_staticBody;
var b2DynamicBody = Box2D.Dynamics.b2Body.b2_dynamicBody;
var b2RevoluteJointDef  = Box2D.Dynamics.Joints.b2RevoluteJointDef;
var b2PrismaticJointDef = Box2D.Dynamics.Joints.b2PrismaticJointDef;
var b2DistanceJointDef  = Box2D.Dynamics.Joints.b2DistanceJointDef;
var b2FilterData = Box2D.Dynamics.b2FilterData;
"""


# ----------------------------------------------------------------
# Tiny driver: build a world with flat ground + a car, run N steps.
# Only exposes JSON-serializable values back to Python.
# ----------------------------------------------------------------
DRIVER = r"""
var _world = null;
var _car = null;

function setupFlat() {
  _world = new b2World(new Vec2(0, 10), false);

  // Flat ground: a single thick box well below the spawn so we can land on it.
  var gbd = new b2BodyDef();
  gbd.type = b2StaticBody;
  gbd.position = new Vec2(0, 25);
  var ground = _world.CreateBody(gbd);
  var gfix = new b2FixtureDef();
  var gshape = new b2PolygonShape();
  gshape.SetAsBox(100, 0.5);
  gfix.shape = gshape;
  gfix.friction = 0.99;
  gfix.restitution = 0.1;
  var gfilt = new b2FilterData();
  gfilt.categoryBits = GRASS_CATEGORY | DIRT_CATEGORY;
  gfilt.maskBits = WHEEL_CATEGORY | CHASSIS_CATEGORY | PERSON_CATEGORY;
  ground.CreateFixture(gfix).SetFilterData(gfilt);

  // Car at world (350, 500). Player arg is a dummy — Car only reads
  // shirtColor* (cosmetic) and .dead (no-op when humanPlaying=true).
  var dummyPlayer = { shirtColorR: 128, shirtColorG: 128, shirtColorB: 128, dead: false };
  _car = new Car(350, 500, _world, dummyPlayer);
}

function step(action) {
  // action: 0=forward, 1=reverse, 2=off
  if (action === 0) { _car.motorOn(true); }
  else if (action === 1) { _car.motorOn(false); }
  else { _car.motorOff(); }
  _world.Step(1.0/30.0, 10, 10);
  _world.ClearForces();
}

function obs() {
  var c = _car.chassisBody;
  var p = c.GetPosition();
  var v = c.GetLinearVelocity();
  return JSON.stringify({
    x: p.x, y: p.y,
    vx: v.x, vy: v.y,
    angle: c.GetAngle(),
    angVel: c.GetAngularVelocity()
  });
}
"""


def _read(rel):
    # Physics JS is single-sourced in web/ (see js_backend.py); read it from there.
    with open(os.path.join(ROOT, "web", rel), "r", encoding="utf-8") as f:
        return f.read()


def main():
    ctx = py_mini_racer.MiniRacer()

    t0 = time.time()
    ctx.eval(_read("libraries/Box2d.js"))
    print(f"  loaded Box2d.js in {(time.time()-t0)*1000:.1f}ms")

    ctx.eval(POLYFILLS)
    print("  polyfills installed")

    for src in ("Wheel.js", "Person.js", "Car.js"):
        t0 = time.time()
        ctx.eval(_read(src))
        print(f"  loaded {src} in {(time.time()-t0)*1000:.1f}ms")

    ctx.eval(DRIVER)
    print("  driver installed")

    print()
    print("--- Smoke test: setup flat scene, observe behavior ---")
    ctx.eval("setupFlat()")
    print(f"  initial obs: {ctx.eval('obs()')}")

    # Just settle (no motor) — see if it lands upright
    for i in range(30):
        ctx.eval("step(2)")  # action 2 = motor off
        if i in (0, 5, 10, 20, 29):
            print(f"  settle  t={i:>3d}: {ctx.eval('obs()')}")

    # Now apply forward throttle
    print()
    print("--- forward throttle ---")
    for i in range(100):
        ctx.eval("step(0)")  # action 0 = forward
        if i in (0, 5, 10, 20, 50, 99):
            print(f"  forward t={i:>3d}: {ctx.eval('obs()')}")

    # Time 1000 steps
    N = 1000
    t0 = time.time()
    for _ in range(N):
        ctx.eval("step(0)")
    dt = time.time() - t0
    steps_per_sec = N / dt
    print(f"  {N} steps in {dt*1000:.0f}ms -> {steps_per_sec:.0f} steps/sec  ({dt/N*1e6:.0f}us/step)")
    print(f"  final obs (after {5 + N} ticks): {ctx.eval('obs()')}")

    # Time with obs read every step (more realistic)
    t0 = time.time()
    for _ in range(N):
        ctx.eval("step(0)")
        ctx.eval("obs()")  # JSON serialize + return
    dt = time.time() - t0
    print(f"  {N} steps + obs in {dt*1000:.0f}ms -> {N/dt:.0f} steps/sec  ({dt/N*1e6:.0f}us/step)")

    # Time with .call() instead of .eval() — does it help?
    try:
        t0 = time.time()
        for _ in range(N):
            ctx.call("step", 0)
        dt = time.time() - t0
        print(f"  {N} ctx.call('step', 0) in {dt*1000:.0f}ms -> {N/dt:.0f} steps/sec  ({dt/N*1e6:.0f}us/step)")
    except Exception as e:
        print(f"  ctx.call() not supported or failed: {e}")


if __name__ == "__main__":
    main()
