// NOTE: the show() methods in Person/Head/Torso are p5 render, used ONLY by
// legacy_neat/ (not the web AI site or training path). Kept for legacy_neat. #8.
class Person {
  constructor(x, y, personWidth, personHeight, world) {
    this.world = world;

    this.x = x;
    this.y = y;
    this.height = personHeight;
    this.width = personWidth;
    this.torso = new Torso(x, y - (personHeight / 2), personHeight, personWidth, this.world);
    this.head = new Head(x, y - (personHeight + personWidth * 1), personWidth * 1, this.world);
    const revJointDef = new b2RevoluteJointDef();
    const jointPos = new Vec2(x / SCALE, (y - personHeight) / SCALE);

    revJointDef.Initialize(this.head.body, this.torso.body, jointPos);
    // No neck limit: the head-to-torso joint doesn't exhibit the 180deg flip in practice
    // (only torso-to-chassis does, limited in Car.js). Add one here if that ever changes.
    this.headJoint = this.world.CreateJoint(revJointDef);



    const distJointDef = new b2DistanceJointDef();
    const anchorTorso = new Vec2(x / SCALE, (y) / SCALE);
    const anchorHead = new Vec2(x / SCALE, this.head.startingPosition.y / SCALE);
    distJointDef.Initialize(this.head.body, this.torso.body, anchorHead, anchorTorso);
    this.distJoint = this.world.CreateJoint(distJointDef);



  }


  show() {
    this.head.show();
    this.torso.show();
  }

}


class Head {
  constructor(x, y, r, world) {
    this.world = world;
    this.startingPosition = createVector(x, y);
    this.radius = r;
    this.id = "head";
    this.makeBody();
    this.isCB = false;
  }

  makeBody() {
    let bodyDef = new b2BodyDef();
    bodyDef.type = b2DynamicBody;


    bodyDef.position.x = this.startingPosition.x / SCALE;
    bodyDef.position.y = this.startingPosition.y / SCALE;
    bodyDef.angle = 0;

    let fixDef = new b2FixtureDef();
    fixDef.density = 0.001;
    fixDef.friction = 0.01;
    fixDef.restitution = 0.01;
    fixDef.shape = new b2CircleShape(this.radius / SCALE);

    this.body = this.world.CreateBody(bodyDef);
    this.body.SetUserData(this);

    const filtData = new b2FilterData();
    filtData.categoryBits = PERSON_CATEGORY;
    filtData.maskBits = PERSON_MASK;
    this.body.CreateFixture(fixDef).SetFilterData(filtData);

  }

  show() {
    let x = this.body.GetPosition().x * SCALE;
    let y = this.body.GetPosition().y * SCALE;
    let angle = this.body.GetAngle();
    push();


    translate(x - panX, y - panY);
    rotate(angle);
    if (this.isCB) {
      image(CBHeadSprite, -this.radius - 7, -this.radius - 15, this.radius * 3, this.radius * 3);
    } else {
      image(headSprite, -this.radius - 8, -this.radius - 15, this.radius * 3, this.radius * 3);
    }
    pop();
  }
}


class Torso {

  constructor(centerX, centerY, height, width, world) {
    this.id = "torso";
    this.world = world;
    this.width = width;
    this.height = height;
    this.startingPosition = createVector(centerX, centerY);
    this.colour = color(0, 0, 0);
    this.makeBody();


  }
  makeBody() {
    let bodyDef = new b2BodyDef();
    bodyDef.type = b2DynamicBody;
    bodyDef.position.x = this.startingPosition.x / SCALE;
    bodyDef.position.y = this.startingPosition.y / SCALE;
    bodyDef.angle = 0;

    let fixDef = new b2FixtureDef();
    fixDef.density = 0.002;
    fixDef.friction = 0.01;
    fixDef.restitution = 0.01;
    fixDef.shape = new b2PolygonShape();
    fixDef.shape.SetAsBox(this.width / 2 / SCALE, this.height / 2 / SCALE);

    this.body = this.world.CreateBody(bodyDef);
    this.body.SetUserData(this);

    const filtData = new b2FilterData();
    // filtData.groupIndex = -1;
    filtData.categoryBits = PERSON_CATEGORY;
    filtData.maskBits = PERSON_MASK;
    this.body.CreateFixture(fixDef).SetFilterData(filtData);

  }


  show() {

    let x = this.body.GetPosition().x * SCALE;
    let y = this.body.GetPosition().y * SCALE;
    let angle = this.body.GetAngle();
    push();
    translate(x - panX, y - panY);
    rotate(angle);
    // fill(60, 80, 10);
    fill(this.colour);
    // noStroke();
    stroke(0);
    strokeWeight(1);
    rectMode(CENTER);
    rect(0, 0, this.width, this.height);
    pop();

  }


}
