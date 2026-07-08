"""V8-based JS physics backend.

Loads the original Box2D.js + Wheel.js + Person.js + Car.js into an embedded
V8 engine via PyMiniRacer, exposes a small Python API for setting up a world,
applying actions, and reading observation state. The whole physics simulation
runs in JavaScript using the exact same code that powers the browser game —
no more pybox2d-vs-Box2D.js fidelity issues.

Public API:
    backend = JSPhysics()
    backend.build_world(vertices_px, spawning_y_px)   # one-time per terrain
    backend.step(action)                              # advance one tick
    backend.state()                                   # returns dict
    backend.reset_car()                               # respawn without rebuilding terrain

state() returns:
    x, y           : chassis position (meters)
    vx, vy         : chassis linear velocity (m/s)
    angle          : chassis angle (rad)
    ang_vel        : chassis angular velocity (rad/s)
    on_ground_now  : bool (any wheel touching ground this tick)
    ground_samples : list of ground y-positions (METERS) ahead of chassis
    dead           : bool (head-ground contact or fell off canvas)
    max_x          : meters, monotonically increasing — used for score
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional, Tuple

from py_mini_racer import py_mini_racer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ----------------------------------------------------------------
# Polyfills + global setup mirroring measure.html.
# These let the unmodified Wheel.js / Person.js / Car.js classes run
# inside V8 without p5.js or a browser.
# ----------------------------------------------------------------
_POLYFILLS = r"""
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

// Globals Car.js etc. reference but never affect physics on the training path.
var panX = 0, panY = 0, nextPanX = 0;
var humanPlaying = true;     // disables Car.js's no-progress death
var fightMode = false;
var humanPlayer = null;
var reset = false;
var SCALE = 30;
var difficulty = 50;
var grassSprites = { length: 5 };   // Ground.js only reads .length

// Collision categories — exact copy from sketch.js.
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
# Driver — exposes the small JS API the Python side calls.
# We build the ground from a vertex list Python provides (so we don't need
# to polyfill p5.noise here), then build the Car using the unmodified
# Car/Wheel/Person classes.
# ----------------------------------------------------------------
_DRIVER = r"""
var _world = null;
var _car = null;
var _ground = null;        // a plain object with .vectors + .getPositions for ground sampling
var _spawnX = 0;
var _spawnY = 0;
var _maxX = 0;
var _planning = false;     // when true, a lethal head-ground contact flags death
                           // WITHOUT destroying joints, so an in-place restore
                           // stays valid across search branches (see setPlanning).
                           // Default false => training/eval/browser are byte-identical.

function _makeContactListener(world) {
  var listener = new Box2D.Dynamics.b2ContactListener;
  listener.BeginContact = function(contact) {
    var udA = contact.GetFixtureA().GetBody().GetUserData();
    var udB = contact.GetFixtureB().GetBody().GetUserData();
    if (!udA || !udB) return;

    // head touches ground => destroy joints (car splits) + mark dead
    function killViaHead(headBody) {
      if (headBody.GetJointList() == null) return;
      // exact gross code from sketch.js: head -> head_joint.other -> torso -> torso_joint.other -> chassis (Car)
      var car = headBody.GetJointList().other.GetJointList().other.GetUserData();
      if (!car) return;
      if (_planning) { if (car.player) car.player.kindaDead = true; return; }
      try { _world.DestroyJoint(car.distJoint); } catch(e) {}
      try { _world.DestroyJoint(car.person.distJoint); } catch(e) {}
      try { _world.DestroyJoint(car.revJoint); } catch(e) {}
      try { _world.DestroyJoint(car.person.headJoint); } catch(e) {}
      if (car.player) car.player.kindaDead = true;
    }
    if (udA.id == "head" && udB.id == "ground") killViaHead(contact.GetFixtureA().GetBody());
    if (udB.id == "head" && udA.id == "ground") killViaHead(contact.GetFixtureB().GetBody());

    // wheel-ground => onGround=true
    if (udA.id == "wheel" && udB.id == "ground") udA.onGround = true;
    if (udB.id == "wheel" && udA.id == "ground") udB.onGround = true;
  };
  listener.EndContact = function(contact) {
    var udA = contact.GetFixtureA().GetBody().GetUserData();
    var udB = contact.GetFixtureB().GetBody().GetUserData();
    if (!udA || !udB) return;
    if (udA.id == "wheel" && udB.id == "ground") udA.onGround = false;
    if (udB.id == "wheel" && udA.id == "ground") udB.onGround = false;
  };
  world.SetContactListener(listener);
}

function _buildGroundBodies(world, vertices_px) {
  // vertices_px is a JS array of [x_px, y_px] pairs.
  // Following Ground.js: two static bodies (dirt + grass), edge fixtures
  // along consecutive vertices, grass offset upward by grassThickness/SCALE.
  var grassThickness = 5;
  var gd = new b2BodyDef();
  gd.type = b2StaticBody;
  gd.position = new Vec2(0, 0);
  var dirt = world.CreateBody(gd);
  var grass = world.CreateBody(gd);
  dirt.SetUserData({id: "ground"});
  grass.SetUserData({id: "ground"});

  // Convert to meter-space Vec2s once.
  var verts = [];
  for (var i = 0; i < vertices_px.length; i++) {
    verts.push(new Vec2(vertices_px[i][0] / SCALE, vertices_px[i][1] / SCALE));
  }
  // Store on a fake ground object so we can do lookahead reads later.
  _ground = { vectors: verts, getPositions: null };
  _ground.getPositions = function(x_m, n, skip) {
    var out = [];
    for (var i = 0; i < this.vectors.length; i++) {
      if (this.vectors[i].x >= x_m) {
        for (var j = 0; j < Math.min(skip * n, this.vectors.length - i); j += skip) {
          out.push(this.vectors[i + j].y);  // meters (CONVENTIONS.md #1; matches Ground.js)
        }
        break;
      }
    }
    if (out.length === 0) {
      out.push(this.vectors.length > 0 ? this.vectors[this.vectors.length-1].y : 0);
    }
    while (out.length < n) out.push(out[out.length - 1]);
    return out;
  };
  // Mirror of getPositions, but walking BACKWARD from the chassis x. Returns n
  // ground y-positions (pixel space) behind the car at -skip, -2*skip, ...
  // vertices (closest-behind first). Lets the policy see whether there's room
  // to back up — needed to escape awkward potholes.
  _ground.getRear = function(x_m, n, skip) {
    var idx = -1;
    for (var i = 0; i < this.vectors.length; i++) {
      if (this.vectors[i].x >= x_m) { idx = i; break; }
    }
    if (idx < 0) idx = this.vectors.length - 1;
    var out = [];
    for (var k = 1; k <= n; k++) {
      var j = idx - k * skip;
      if (j < 0) j = 0;
      out.push(this.vectors[j].y);  // meters, matches getPositions
    }
    return out;
  };

  function addEdge(body, a, b, category, mask) {
    var fix = new b2FixtureDef();
    fix.friction = 0.99;
    fix.restitution = 0.1;
    fix.shape = new b2PolygonShape();
    fix.shape.SetAsEdge(a, b);
    var filt = new b2FilterData();
    filt.categoryBits = category;
    filt.maskBits = mask;
    body.CreateFixture(fix).SetFilterData(filt);
  }

  var gth = grassThickness / SCALE;
  for (var i = 1; i < verts.length; i++) {
    var a = verts[i-1], b = verts[i];
    addEdge(dirt, a, b, DIRT_CATEGORY, DIRT_MASK);
    addEdge(grass,
      new Vec2(a.x, a.y - gth),
      new Vec2(b.x, b.y - gth),
      GRASS_CATEGORY, GRASS_MASK);
  }
}

function buildWorld(vertices_px, spawnX_px, spawnY_px) {
  _world = new b2World(new Vec2(0, 10), false);
  _makeContactListener(_world);
  _buildGroundBodies(_world, vertices_px);
  _spawnX = spawnX_px;
  _spawnY = spawnY_px;
  var dummyPlayer = { shirtColorR: 128, shirtColorG: 128, shirtColorB: 128, dead: false, kindaDead: false };
  _car = new Car(spawnX_px, spawnY_px, _world, dummyPlayer);
  _maxX = _car.chassisBody.GetPosition().x;
}

function step(action) {
  if (!_car || _car.player.kindaDead) {
    // car is dead — still step the world so contacts settle, but skip motor.
    _world.Step(1.0/30.0, 10, 10);
    _world.ClearForces();
    return;
  }
  if (action === 0) _car.motorOn(true);
  else if (action === 1) _car.motorOn(false);
  else _car.motorOff();
  _world.Step(1.0/30.0, 10, 10);
  _world.ClearForces();
  var x = _car.chassisBody.GetPosition().x;
  if (x > _maxX) _maxX = x;
}

function setPlanning(flag) { _planning = !!flag; }

function setSpawn(x_px, y_px) {
  // Move the respawn point without rebuilding the terrain. The next resetCar()
  // (or buildWorld) drops the car here. Used by the curriculum to spawn the car
  // at different points of the SAME pooled track.
  _spawnX = x_px;
  _spawnY = y_px;
}

function resetCar() {
  // Tear down old car, create a new one. Terrain stays.
  if (_car) {
    // Destroy joints first (defensive — they may already be gone if dead).
    try { _world.DestroyJoint(_car.distJoint); } catch(e) {}
    try { _world.DestroyJoint(_car.revJoint); } catch(e) {}
    try { if (_car.person && _car.person.distJoint) _world.DestroyJoint(_car.person.distJoint); } catch(e) {}
    try { if (_car.person && _car.person.headJoint) _world.DestroyJoint(_car.person.headJoint); } catch(e) {}
    try { if (_car.wheels) for (var i = 0; i < _car.wheels.length; i++) {
      if (_car.wheels[i].joint) _world.DestroyJoint(_car.wheels[i].joint);
      if (_car.wheels[i].prisJoint) _world.DestroyJoint(_car.wheels[i].prisJoint);
      if (_car.wheels[i].distJoint) _world.DestroyJoint(_car.wheels[i].distJoint);
    } } catch(e) {}
    // Destroy bodies (children first, chassis last is safest).
    try { _world.DestroyBody(_car.person.head.body); } catch(e) {}
    try { _world.DestroyBody(_car.person.torso.body); } catch(e) {}
    try { if (_car.wheels) for (var i = 0; i < _car.wheels.length; i++) {
      if (_car.wheels[i].body) _world.DestroyBody(_car.wheels[i].body);
      if (_car.wheels[i].rimBody) _world.DestroyBody(_car.wheels[i].rimBody);
    } } catch(e) {}
    try { _world.DestroyBody(_car.chassisBody); } catch(e) {}
  }
  var dummyPlayer = { shirtColorR: 128, shirtColorG: 128, shirtColorB: 128, dead: false, kindaDead: false };
  _car = new Car(_spawnX, _spawnY, _world, dummyPlayer);
  _maxX = _car.chassisBody.GetPosition().x;
}

function state(lookaheadN, lookaheadSkip, rearN, rearSkip) {
  var c = _car.chassisBody;
  var p = c.GetPosition();
  var v = c.GetLinearVelocity();
  var rearG  = (_car.wheels[0].onGround === true);
  var frontG = (_car.wheels[1].onGround === true);
  var samples = _ground.getPositions(p.x, lookaheadN || 6, lookaheadSkip || 5);
  var rear = (rearN && rearN > 0) ? _ground.getRear(p.x, rearN, rearSkip || 5) : [];
  return JSON.stringify({
    x: p.x, y: p.y,
    vx: v.x, vy: v.y,
    angle: c.GetAngle(),
    ang_vel: c.GetAngularVelocity(),
    on_ground_now: rearG || frontG,
    on_ground_rear: rearG,
    on_ground_front: frontG,
    ground_samples: samples,
    ground_samples_rear: rear,
    dead: !!_car.player.kindaDead,
    max_x: _maxX
  });
}

function stepAndState(action, lookaheadN, lookaheadSkip, rearN, rearSkip) {
  // Combined call so per-step Python -> JS overhead is paid once, not twice.
  // The training loop calls this hundreds of thousands of times.
  step(action);
  return state(lookaheadN, lookaheadSkip, rearN, rearSkip);
}

function renderState() {
  // Returns everything the Python renderer needs to draw the car: chassis
  // polygons (world pixel coords), wheels (position + angle + radius), torso
  // (center + angle + size), head (center + radius). Called only when
  // rendering, not during training.
  var cb = _car.chassisBody;
  var cpos = cb.GetPosition();
  var cang = cb.GetAngle();
  var ccos = Math.cos(cang), csin = Math.sin(cang);

  // Car.js stores each fixture's local-METER-space vertex list in `this.shapes`
  // (Car.js divides each vertex by SCALE before pushing — see Car.js lines 44-47).
  // So we rotate+translate in meter-space, THEN multiply by SCALE for pixel output.
  var polys = [];
  for (var i = 0; i < _car.shapes.length; i++) {
    var src = _car.shapes[i];
    var out = [];
    for (var j = 0; j < src.length; j++) {
      var lp = src[j];                  // already meters
      var wxm = ccos*lp.x - csin*lp.y + cpos.x;
      var wym = csin*lp.x + ccos*lp.y + cpos.y;
      out.push([wxm * SCALE, wym * SCALE]);
    }
    polys.push(out);
  }

  var wheels = [];
  for (var i = 0; i < _car.wheels.length; i++) {
    var w = _car.wheels[i];
    var p = w.body.GetPosition();
    wheels.push({
      x_px: p.x * SCALE,
      y_px: p.y * SCALE,
      angle: w.body.GetAngle(),
      radius_px: w.radius
    });
  }

  var torsoBody = _car.person.torso.body;
  var tp = torsoBody.GetPosition();
  var torso = {
    x_px: tp.x * SCALE, y_px: tp.y * SCALE,
    angle: torsoBody.GetAngle(),
    width_px: _car.person.torso.width,
    height_px: _car.person.torso.height
  };

  var headBody = _car.person.head.body;
  var hp = headBody.GetPosition();
  var head = {
    x_px: hp.x * SCALE,
    y_px: hp.y * SCALE,
    angle: headBody.GetAngle(),
    radius_px: _car.person.head.radius
  };

  return JSON.stringify({
    chassis_polys: polys,
    wheels: wheels,
    torso: torso,
    head: head,
    dead: !!_car.player.kindaDead
  });
}

// ---- save / restore for test-time search (MPC) ----------------------------
// Snapshot every dynamic body's pose + velocity, plus the wheel onGround flags,
// motor state and progress. This does NOT touch the solver/joints/torque — it
// only reads and (on restore) writes b2Body transforms, so the unmodified
// physics is untouched and browser parity holds.
//
// Restore is meant to be used on a FRESH car (resetCar() first) so death-
// destroyed joints are rebuilt: the Car constructor bakes joint local-anchors
// identically at spawn, so teleporting each body to its saved (pos, angle)
// re-satisfies every joint. (Restoring in-place into a still-alive car also
// works and is slightly cheaper; see test_saverestore.py for the divergence.)
function _dynBodies() {
  return [_car.chassisBody,
          _car.wheels[0].body, _car.wheels[0].rimBody,
          _car.wheels[1].body, _car.wheels[1].rimBody,
          _car.person.torso.body, _car.person.head.body];
}

function saveState() {
  var bs = _dynBodies();
  var arr = [];
  for (var i = 0; i < bs.length; i++) {
    var b = bs[i];
    var p = b.GetPosition(), v = b.GetLinearVelocity();
    arr.push([p.x, p.y, b.GetAngle(), v.x, v.y, b.GetAngularVelocity()]);
  }
  return JSON.stringify({
    bodies: arr,
    og0: !!_car.wheels[0].onGround,
    og1: !!_car.wheels[1].onGround,
    motorState: _car.motorState,
    maxX: _maxX,
    dead: !!_car.player.kindaDead
  });
}

function restoreState(s) {
  var st = (typeof s === "string") ? JSON.parse(s) : s;
  var bs = _dynBodies();
  for (var i = 0; i < bs.length; i++) {
    var r = st.bodies[i], b = bs[i];
    b.SetPositionAndAngle(new Vec2(r[0], r[1]), r[2]);
    b.SetLinearVelocity(new Vec2(r[3], r[4]));
    b.SetAngularVelocity(r[5]);
    b.SetAwake(true);
  }
  _car.wheels[0].onGround = st.og0;
  _car.wheels[1].onGround = st.og1;
  _car.motorState = st.motorState;
  _maxX = st.maxX;
  _car.player.kindaDead = st.dead;
}

// ---- training / test-time "nudge": add a small velocity perturbation ---------
// Adds a small impulse to the chassis velocity (linear) + angular velocity.
// Uses the SAME velocity-write path as restoreState (SetLinearVelocity /
// SetAngularVelocity), so the solver / joints / torque are never touched ->
// browser parity holds. Only the chassis is kicked; the joints propagate it to
// the wheels / person over the following ticks (a realistic bump, not a teleport).
// No-op on a dead car.
function nudge(dvx, dvy, dav) {
  if (!_car || _car.player.kindaDead) return;
  var c = _car.chassisBody;
  var v = c.GetLinearVelocity();
  c.SetLinearVelocity(new Vec2(v.x + dvx, v.y + dvy));
  c.SetAngularVelocity(c.GetAngularVelocity() + dav);
  c.SetAwake(true);
}
"""


# The physics JS is single-sourced in web/ (the deployed static site is its own git
# repo and must be self-contained, so the one canonical copy lives there and the
# training path reads it from there — no root duplicate to drift out of sync).
_WEB = os.path.join(ROOT, "web")


def _read(rel: str) -> str:
    with open(os.path.join(_WEB, rel), "r", encoding="utf-8") as f:
        return f.read()


class JSPhysics:
    """Wraps a V8 instance loaded with the unmodified JS physics classes."""

    def __init__(self):
        self.ctx = py_mini_racer.MiniRacer()
        self.ctx.eval(_read("libraries/Box2d.js"))
        self.ctx.eval(_POLYFILLS)
        self.ctx.eval(_read("Wheel.js"))
        self.ctx.eval(_read("Person.js"))
        self.ctx.eval(_read("Car.js"))
        self.ctx.eval(_DRIVER)

    def build_world(self, vertices_px: List[Tuple[float, float]],
                    spawn_x_px: float, spawn_y_px: float) -> None:
        verts_json = json.dumps([[float(x), float(y)] for x, y in vertices_px])
        self.ctx.eval(f"buildWorld({verts_json}, {float(spawn_x_px)}, {float(spawn_y_px)})")

    def set_spawn(self, spawn_x_px: float, spawn_y_px: float) -> None:
        """Move the respawn point without rebuilding terrain (curriculum spawns)."""
        self.ctx.eval(f"setSpawn({float(spawn_x_px)}, {float(spawn_y_px)})")

    def set_planning(self, flag: bool) -> None:
        """Toggle planning mode: a lethal head-ground contact flags death without
        destroying joints, so in-place restore_state() stays valid across search
        branches. Off by default; only the MPC planner turns it on."""
        self.ctx.eval(f"setPlanning({'true' if flag else 'false'})")

    def reset_car(self) -> None:
        self.ctx.eval("resetCar()")

    def step(self, action: int) -> None:
        self.ctx.eval(f"step({int(action)})")

    def state(self, lookahead_n: int = 6, lookahead_skip: int = 5,
              rear_n: int = 0, rear_skip: int = 5) -> dict:
        return json.loads(self.ctx.eval(
            f"state({int(lookahead_n)}, {int(lookahead_skip)}, {int(rear_n)}, {int(rear_skip)})"
        ))

    def step_and_state(self, action: int, lookahead_n: int = 6, lookahead_skip: int = 5,
                       rear_n: int = 0, rear_skip: int = 5) -> dict:
        """Step + observe in one JS boundary crossing. Cuts per-step overhead ~50%."""
        return json.loads(self.ctx.eval(
            f"stepAndState({int(action)}, {int(lookahead_n)}, {int(lookahead_skip)}, "
            f"{int(rear_n)}, {int(rear_skip)})"
        ))

    def render_state(self) -> dict:
        """Fetch render data: chassis polys, wheels, torso, head. Only call when drawing."""
        return json.loads(self.ctx.eval("renderState()"))

    def save_state(self) -> str:
        """Snapshot the car's dynamic state (poses, velocities, onGround, motor,
        progress) as a JSON string, for test-time search / MPC. See restore_state."""
        return self.ctx.eval("saveState()")

    def restore_state(self, state_json: str) -> None:
        """Restore a snapshot from save_state(). Call reset_car() first if the
        scratch car may have died (head-ground contact destroys joints); on a
        fresh car the baked joint anchors re-satisfy after the teleport."""
        # state_json is the exact string from save_state(); json.dumps wraps it as
        # a JS string literal so the JSON survives the eval boundary, then
        # restoreState JSON.parses it back.
        self.ctx.eval(f"restoreState({json.dumps(state_json)})")

    def nudge(self, dvx: float, dvy: float, dav: float) -> None:
        """Add a small velocity (dvx, dvy m/s) + angular-velocity (dav rad/s)
        perturbation to the chassis — a training / test-time 'nudge'. Same
        velocity-write path as restore_state, so the solver/joints/torque stay
        untouched and browser parity holds. No-op on a dead car."""
        self.ctx.eval(f"nudge({float(dvx)}, {float(dvy)}, {float(dav)})")
