// NOTE: setShirt(), show() and update() below are used ONLY by legacy_neat/ (the
// p5 NEAT game). The web AI site (index.html) renders itself, and the training
// path (js_backend.py) calls the physics API directly — neither calls these.
// Kept for legacy_neat; don't rely on them here.
class Car {
  constructor(x, y, world, player) {
    this.world = world;
    this.player = player;
    this.wheels = [];
    this.startingPosition = createVector(x, y);
    this.id = "car";
    this.chassisWidth = 125;
    this.chassisHeight = 40;
    this.wheelSize = 17;
    this.dead = false;
    this.changeCount = 0;
    this.number = 0;

    this.changeDiff = 0;
    this.shapes = [];
    this.carDensity = 1;
    this.carRestitution = 0.01;
    this.maxDistance = 0;
    this.motorState = 0; //-1 is back and 1 is forward

    // //console.log(this.world);

    const bodyDef = new b2BodyDef();
    bodyDef.type = b2DynamicBody;
    bodyDef.position.x = x / SCALE;
    bodyDef.position.y = y / SCALE;
    bodyDef.angle = 0;

    const fixDef = new b2FixtureDef();
    fixDef.density = this.carDensity;
    fixDef.friction = 0.5;
    fixDef.restitution = this.carRestitution;
    fixDef.shape = new b2PolygonShape();

    let vectors = [];
    vectors.push(new Vec2(-this.chassisWidth / 2, 0 - this.chassisHeight / 2));
    vectors.push(new Vec2(this.chassisWidth / 4 + 5, 0 - this.chassisHeight / 2));

    vectors.push(new Vec2(this.chassisWidth / 2, 0 - this.chassisHeight / 2 + 5));
    vectors.push(new Vec2(this.chassisWidth / 2, this.chassisHeight / 2));
    vectors.push(new Vec2(-this.chassisWidth / 2, this.chassisHeight / 2));
    for (const vect of vectors) {
      vect.x /= SCALE;
      vect.y /= SCALE;
    }

    fixDef.shape.SetAsArray(vectors, vectors.length);
    this.shapes.push(vectors);



    // fixDef.shape.SetAsBox(this.chassisWidth / 2 / SCALE, this.chassisHeight / 2 / SCALE);
    this.chassisBody = this.world.CreateBody(bodyDef);

    const filtData = new b2FilterData();
    // filtData.groupIndex = -1;
    filtData.categoryBits = CHASSIS_CATEGORY;
    filtData.maskBits = CHASSIS_MASK;


    this.chassisBody.CreateFixture(fixDef).SetFilterData(filtData);
    //
    const fixDef2 = new b2FixtureDef();
    fixDef2.density = this.carDensity;
    fixDef2.friction = 0.5;
    fixDef2.restitution = this.carRestitution;
    fixDef2.shape = new b2PolygonShape();
    // fixDef2.shape.SetAsBox(10 / SCALE, 100 / SCALE);

    const vectors2 = [];
    vectors2.push(new Vec2(this.chassisWidth / 4, 0 - this.chassisHeight / 2));
    vectors2.push(new Vec2(this.chassisWidth / 4 - 15, 0 - this.chassisHeight / 2 - 20));
    vectors2.push(new Vec2(this.chassisWidth / 4 - 5, 0 - this.chassisHeight / 2 - 20));
    vectors2.push(new Vec2(this.chassisWidth / 4 + 10, 0 - this.chassisHeight / 2));
    for (const vect of vectors2) {
      vect.x /= SCALE;
      vect.y /= SCALE;
    }
    fixDef2.shape.SetAsArray(vectors2, vectors2.length);
    this.chassisBody.CreateFixture(fixDef2).SetFilterData(filtData);
    this.shapes.push(vectors2);

    const fixDef3 = new b2FixtureDef();
    fixDef3.density = this.carDensity;
    fixDef3.friction = 0.1;
    fixDef3.restitution = 0.1;
    fixDef3.shape = new b2PolygonShape();
    // fixDef2.shape.SetAsBox(10 / SCALE, 100 / SCALE);

    const vectors3 = [];
    vectors3.push(new Vec2(this.chassisWidth / 2, 0 - this.chassisHeight / 2 + 5));
    vectors3.push(new Vec2(this.chassisWidth / 2 + 5, 0 - this.chassisHeight / 2 + 8));
    vectors3.push(new Vec2(this.chassisWidth / 2 + 5, this.chassisHeight / 2 - 5));
    vectors3.push(new Vec2(this.chassisWidth / 2, this.chassisHeight / 2));
    for (const vect of vectors3) {
      vect.x /= SCALE;
      vect.y /= SCALE;
    }
    fixDef3.shape.SetAsArray(vectors3, vectors3.length);
    this.chassisBody.CreateFixture(fixDef3).SetFilterData(filtData);
    this.shapes.push(vectors3);

    this.wheels.push(new Wheel(x - this.chassisWidth / 2 + this.wheelSize * 1.2, y + this.chassisHeight / 2 + this.wheelSize / 4, this.wheelSize, this.chassisBody, this.world));
    this.wheels.push(new Wheel(x + this.chassisWidth / 2 - this.wheelSize * 1.2, y + this.chassisHeight / 2 + this.wheelSize / 4, this.wheelSize, this.chassisBody, this.world));

    this.person = new Person(x, y, 15, 30, this.world); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<person
    this.person.torso.colour = color(this.player.shirtColorR, this.player.shirtColorG, this.player.shirtColorB);
    const revJointDef = new b2RevoluteJointDef();
    const jointPos = new Vec2(x / SCALE, y / SCALE);
    revJointDef.Initialize(this.person.torso.body, this.chassisBody, jointPos);
    // Angular limit: a distance joint only fixes the torso DISTANCE, not which side it
    // sits on, so a hard impact could push the driver into a second stable equilibrium
    // hanging 180deg below the car (and never climb back out). The limit must sit INSIDE
    // the upright basin of attraction, or the ragdoll just rests against the wall in the
    // flip basin (what +/-90 did). The basin is ASYMMETRIC (rest is tilted ~-19.7deg,
    // since the distance-joint anchor is offset forward): measured edges are jointAngle
    // -71.6deg (torso tipping FORWARD) and +105.5deg (tipping BACK). We take a 1deg
    // margin inside each -> [-70.6deg, +104.5deg]. See PROJECT_STATUS for the measurement.
    revJointDef.enableLimit = true;
    revJointDef.lowerAngle = -70.6 * Math.PI / 180;   // forward edge -71.6deg, 1deg margin
    revJointDef.upperAngle = 104.5 * Math.PI / 180;   // back edge +105.5deg, 1deg margin
    this.revJoint = this.world.CreateJoint(revJointDef);

    const distJointDef = new b2DistanceJointDef();
    const anchorPerson = new Vec2(x / SCALE, (y - this.person.height * 2 / 3) / SCALE);
    const anchorCar = new Vec2((x + this.chassisWidth / 2) / SCALE, (y - this.chassisHeight / 2) / SCALE);
    distJointDef.Initialize(this.person.torso.body, this.chassisBody, anchorPerson, anchorCar);
    distJointDef.frequencyHz = 5;
    distJointDef.dampingRatio = 0.1;
    distJointDef.length *= 1.1;
    this.distJoint = this.world.CreateJoint(distJointDef);

    this.chassisBody.SetAngularDamping(0.1);

    this.rotationTorque = 2;

    this.chassisBody.SetUserData(this);

  }
  setShirt() {
    this.person.torso.colour = color(this.player.shirtColorR, this.player.shirtColorG, this.player.shirtColorB);
  }

  show() {
    //show chassis
    let x = this.chassisBody.GetPosition().x * SCALE;
    let y = this.chassisBody.GetPosition().y * SCALE;
    let angle = this.chassisBody.GetAngle();
    this.person.show();
    for (const i of this.wheels) {
      i.show();
    }
    push();
    translate(x - panX, y - panY);
    rotate(angle);
    // fill(0, 0, 0);
    // noStroke();
    // // rectMode(CENTER);
    // // rect(0, 0, this.chassisWidth, this.chassisHeight);
    // fill(0, 0, 0);
    //
    // for (var s of this.shapes) {
    //   beginShape();
    //   for (var v of s) {
    //     vertex(v.x * SCALE, v.y * SCALE);
    //   }
    //   endShape(CLOSE);
    //
    // }

    image(carSprite, -this.chassisWidth / 2 - 7, -this.chassisHeight - 20, this.chassisWidth + 23, this.chassisHeight * 2 + 10);
    fill(255, 255, 0, 20);

    // noStroke();
    // rect(-10, -2, 20, 20);
    // fill(255, 0, 0);
    textAlign(CENTER, CENTER);
    textSize(15);
    stroke(255, 255, 255, 20);
    strokeWeight(1);
    // text(this.number, 0, 7);
    pop();

    const tempPanX = x - this.startingPosition.x;
    if (nextPanX < tempPanX && (!fightMode || this.player == humanPlayer || humanPlayer.dead)) {
      nextPanX = tempPanX;
    }

    // panY = y - canvas.height / 2;


  }

  update() {

    let x = this.chassisBody.GetPosition().x * SCALE;
    let y = this.chassisBody.GetPosition().y * SCALE;
    this.changeCount++;

    if (x > this.maxDistance) {
      this.maxDistance = x;
      if (floor(this.maxDistance) % 50 == 0) {
        this.changeCount = 0;
      }
    } else {
      if (this.changeCount > 250) {

        if (!humanPlaying) {
          this.player.dead = true;
        }
      }
    }

    if (!this.dead && y > canvas.height) {
      this.dead = true;
      this.player.dead = true;
      // reset = true;
      // resetCounter = 10;
    }

  }



  motorOn(forward) {
    const motorSpeed = 13;
    this.wheels[0].joint.EnableMotor(true);
    this.wheels[1].joint.EnableMotor(true);
    const oldState = this.motorState;
    if (forward) {
      this.motorState = 1;
      this.wheels[0].joint.SetMotorSpeed(-motorSpeed * PI);
      this.wheels[1].joint.SetMotorSpeed(-motorSpeed * PI);

      this.chassisBody.ApplyTorque(-this.rotationTorque);


    } else {
      this.motorState = -1;
      this.wheels[0].joint.SetMotorSpeed(motorSpeed * PI);
      this.wheels[1].joint.SetMotorSpeed(motorSpeed * PI);

      // this.chassisBody.ApplyTorque(this.rotationTorque);

    }
    if (oldState + this.motorState == 0) {
      if (oldState == 1) {
        this.applyTorque(this.motorState * -1);
      }
      // this.chassisBody.ApplyTorque(this.motorState * (-1) * this.rotationTorque);
    }
    // this.chassisBody.ApplyTorque(this.motorState * (-1) * this.rotationTorque);
    // //console.log(this.wheels[0].joint);
    this.wheels[0].joint.SetMaxMotorTorque(700);
    this.wheels[1].joint.SetMaxMotorTorque(350);
    // //console.log(this.wheels[0].rimBody.GetAngle() - this.chassisBody.GetAngle());
  }

  applyTorque(direction) {
    this.chassisBody.ApplyTorque(direction * this.rotationTorque);
  }
  motorOff() {
    switch (this.motorState) {
      case 1:
        this.chassisBody.ApplyTorque(this.motorState * this.rotationTorque);
        break;
    }
    this.motorState = 0;

    this.wheels[0].joint.EnableMotor(false);
    this.wheels[1].joint.EnableMotor(false);
  }

  // Every dynamic body that makes up the vehicle, in a STABLE order: chassis, both
  // wheels + their rims, then the driver's torso & head. A read-only inventory so
  // callers (renderer's whole-vehicle CoM/speed math; the save-scum search's
  // snapshot / teardown) don't hard-code the body list. The search pairs saved
  // poses back to bodies by index, so the order must not change.
  bodies() {
    return [this.chassisBody,
            this.wheels[0].body, this.wheels[0].rimBody,
            this.wheels[1].body, this.wheels[1].rimBody,
            this.person.torso.body, this.person.head.body];
  }

  // Remove every joint and body this car owns from `world`. Used by the save-scum
  // search to rebuild a fresh car at a rewind point (the constructor re-bakes the
  // joint anchors, so a following teleport re-satisfies them). Each destroy is
  // guarded because a death may already have destroyed some joints (a head-ground
  // hit splits the car by destroying its joints — see index.html's contact listener).
  destroy(world) {
    try { world.DestroyJoint(this.distJoint); } catch (e) {}
    try { world.DestroyJoint(this.revJoint); } catch (e) {}
    try { if (this.person?.distJoint) world.DestroyJoint(this.person.distJoint); } catch (e) {}
    try { if (this.person?.headJoint) world.DestroyJoint(this.person.headJoint); } catch (e) {}
    try {
      for (let i = 0; i < this.wheels.length; i++) {
        const w = this.wheels[i];
        if (w.joint) world.DestroyJoint(w.joint);
        if (w.prisJoint) world.DestroyJoint(w.prisJoint);
        if (w.distJoint) world.DestroyJoint(w.distJoint);
      }
    } catch (e) {}
    const bs = this.bodies();
    for (let j = 0; j < bs.length; j++) { try { world.DestroyBody(bs[j]); } catch (e) {} }
  }

}
