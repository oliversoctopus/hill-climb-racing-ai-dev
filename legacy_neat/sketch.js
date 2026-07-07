//this is a template to add a NEAT ai to any game
//note //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
//this means that there is some information specific to the game to input here
var Vec2 = Box2D.Common.Math.b2Vec2;
var b2BodyDef = Box2D.Dynamics.b2BodyDef;
var b2Body = Box2D.Dynamics.b2Body;
var b2FixtureDef = Box2D.Dynamics.b2FixtureDef;
var b2Fixture = Box2D.Dynamics.b2Fixture;
var b2World = Box2D.Dynamics.b2World;
var b2MassData = Box2D.Collision.Shapes.b2MassData;
var b2PolygonShape = Box2D.Collision.Shapes.b2PolygonShape;
var b2CircleShape = Box2D.Collision.Shapes.b2CircleShape;
var b2EdgeChainDef = Box2D.Collision.Shapes.b2EdgeChainDef;

var b2DebugDraw = Box2D.Dynamics.b2DebugDraw;
var b2StaticBody = Box2D.Dynamics.b2Body.b2_staticBody;
var b2DynamicBody = Box2D.Dynamics.b2Body.b2_dynamicBody;
var b2RevoluteJoint = Box2D.Dynamics.Joints.b2RevoluteJoint;
var b2RevoluteJointDef = Box2D.Dynamics.Joints.b2RevoluteJointDef;

var b2PrismaticJoint = Box2D.Dynamics.Joints.b2PrismaticJoint;

var b2PrismaticJointDef = Box2D.Dynamics.Joints.b2PrismaticJointDef;

var b2FilterData = Box2D.Dynamics.b2FilterData;

var b2DistanceJoint = Box2D.Dynamics.Joints.b2DistanceJoint;
var b2DistanceJointDef = Box2D.Dynamics.Joints.b2DistanceJointDef;

var b2WeldJoint = Box2D.Dynamics.Joints.b2WeldJoint;
var b2WeldJointDef = Box2D.Dynamics.Joints.b2WeldJointDef;

//------------------------------------------GLOBALS
var SCALE = 30;
var groundBody;
var wheels = [];
var groundTemplate;

var pause = false;

var panX = 0;
var targetPanX = 0;
var maxPanSpeed = 100;
var panSpeed = 50;
var panAcc = 10;
var panY = 0;

var leftDown = false;
var rightDown = false;
var listener = new Box2D.Dynamics.b2ContactListener;
// var listener2 = new Box2D.Dynamics.b2ContactListener;

var carSprite;
var headSprite;
var CBHeadSprite;
var wheelSprite;
var shownGround = false;

var spawningY = 0;

//collisionCatagories i.e what it is


var WHEEL_CATEGORY = 0x0001;
var CHASSIS_CATEGORY = 0X0002;
var GRASS_CATEGORY = 0X0004;
var DIRT_CATEGORY = 0x0008;
var PERSON_CATEGORY = 0x0010;

//collision Masks ie. what it collides with
var WHEEL_MASK = (GRASS_CATEGORY);
var CHASSIS_MASK = (DIRT_CATEGORY);
var GRASS_MASK = (WHEEL_CATEGORY | PERSON_CATEGORY);
var DIRT_MASK = (CHASSIS_CATEGORY);
var PERSON_MASK = (GRASS_CATEGORY);

var resetCounter = 120;
var reset = false;

var p;
var p2;
var nextPanX = 0;


var nextConnectionNo = 1000;
var population;
var speed = 60;
var simSpeed = 1; //how many physics steps to run per draw frame during AI training


var showBest = false; //true if only show the best of the previous generation
var runBest = false; //true if replaying the best ever game
var humanPlaying = false; //true if the user is playing

var fightMode = false; //true when the player is fighting the best every player
var humanPlayer;


var showBrain = false;

var showBestEachGen = false;
var upToGen = 0;
var genPlayerTemp; //player

var showNothing = false;

var currentBestPlayer;
var spawnHeight = 0;
//--------------

var playersInEachWorld = [];


var grassSprites = [];

// var ground;
// var world;

var otherWorld; // for human, gen replay, species, best
var worlds = [];
var grounds = [];
var numberOfWorlds = 50;
var playersPerWorld = 15;


var skySprite;
var darknessSprite;
var difficulty = 50;

listener.BeginContact = function(contact) {
  let world = contact.GetFixtureA().GetBody().GetWorld();
  if (reset) {
    return;
  }
  if (contact.GetFixtureA().GetBody().GetUserData().id == "head") {
    if (contact.GetFixtureB().GetBody().GetUserData().id == "ground") {

      if (contact.GetFixtureA().GetBody().GetJointList() == null) {
        return;
      }
      let car = contact.GetFixtureA().GetBody().GetJointList().other.GetJointList().other.GetUserData(); //i think that is the grossest code i have ever written

      world.DestroyJoint(car.distJoint);
      world.DestroyJoint(car.person.distJoint);
      world.DestroyJoint(car.revJoint);
      world.DestroyJoint(car.person.headJoint);
      car.player.kindaDead = true;
    }
  }

  if (contact.GetFixtureB().GetBody().GetUserData().id == "head") {
    if (contact.GetFixtureA().GetBody().GetUserData().id == "ground") {

      if (contact.GetFixtureB().GetBody().GetJointList() == null) {
        return;
      }
      let car = contact.GetFixtureB().GetBody().GetJointList().other.GetJointList().other.GetUserData(); //i think that is the grossest code i have ever written
      world.DestroyJoint(car.distJoint);
      world.DestroyJoint(car.person.distJoint);
      world.DestroyJoint(car.revJoint);
      world.DestroyJoint(car.person.headJoint);
      car.player.kindaDead = true;
    }
  }

  if (contact.GetFixtureA().GetBody().GetUserData().id == "wheel") {
    if (contact.GetFixtureB().GetBody().GetUserData().id == "ground") {
      contact.GetFixtureA().GetBody().GetUserData().onGround = true;
    }
  }

  if (contact.GetFixtureB().GetBody().GetUserData().id == "wheel") {
    if (contact.GetFixtureA().GetBody().GetUserData().id == "ground") {

      contact.GetFixtureB().GetBody().GetUserData().onGround = true;

    }
  }
}

//
// listener2.BeginContact = function(contact) {
//
//
// }
listener.EndContact = function(contact) {

  if (contact.GetFixtureA().GetBody().GetUserData().id == "wheel") {
    if (contact.GetFixtureB().GetBody().GetUserData().id == "ground") {

      contact.GetFixtureA().GetBody().GetUserData().onGround = false;
    }
  }

  if (contact.GetFixtureB().GetBody().GetUserData().id == "wheel") {
    if (contact.GetFixtureA().GetBody().GetUserData().id == "ground") {

      contact.GetFixtureB().GetBody().GetUserData().onGround = false;

    }
  }
}


//--------------------------------------------------------------------------------------------------------------------------------------------------
function preload() {
  CBHeadSprite = loadImage("Pics/CBHead3.png");
  headSprite = loadImage("Pics/headLarge.png");
  skySprite = loadImage("Pics/sky.png");
  darknessSprite = loadImage("Pics/darkness.png");

  carSprite = loadImage("Pics/car.png");
  wheelSprite = loadImage("Pics/wheel2.png");
  grassSprites.push(loadImage("Pics/grass.png"));
  grassSprites.push(loadImage("Pics/grass2.png"));
  grassSprites.push(loadImage("Pics/grass3.png"));
  grassSprites.push(loadImage("Pics/grass4.png"));
  grassSprites.push(loadImage("Pics/grass5.png"));


}

function setup() {
  window.canvas = createCanvas(1280, 720);
  canvas.parent("canvas");
  frameRate(30); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<FRAME RATE


  groundTemplate = new Ground();
  groundTemplate.randomizeGround();

  while (groundTemplate.isTooSteep()) {
    groundTemplate = new Ground();
    groundTemplate.randomizeGround();
  }


  for (var i = 0; i < numberOfWorlds; i++) {
    let tempWorld = new b2World(new Vec2(0, 10), true);
    let tempGround = new Ground(tempWorld);
    tempGround.cloneFrom(groundTemplate);
    tempGround.setBodies(tempWorld);
    tempWorld.SetContactListener(listener);
    // tempWorld.SetContactListener(listener2);

    grounds.push(tempGround);
    worlds.push(tempWorld);
    playersInEachWorld.push(0);
  }

  otherWorld = new b2World(new Vec2(0, 10), true);
  let tempGround = new Ground(otherWorld);
  tempGround.cloneFrom(groundTemplate);
  tempGround.setBodies(otherWorld);
  otherWorld.SetContactListener(listener);

  //
  // ground = new Ground(world);
  // ground.cloneFrom(groundTemplate);
  // ground.setBodies(world); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
  // world.SetContactListener(listener);

  population = new Population();
  humanPlayer = new Player(true);
  currentBestPlayer = population.players[0];

}
//--------------------------------------------------------------------------------------------------------------------------------------------------------
function draw() {

  if (pause) {
    return;
  }
  shownGround = false;
  drawToScreen();
  nextPanX = -100;


  // world.Step(1 / 30, 10, 10);

  if (showBestEachGen) { //show the best of each gen
    if (!genPlayerTemp.dead) { //if current gen player is not dead then update it
      otherWorld.Step(1 / 30, 10, 10);
      genPlayerTemp.look();
      genPlayerTemp.think();
      genPlayerTemp.update();
      if (!showNothing) genPlayerTemp.show();
    } else { //if dead move on to the next generation
      upToGen++;
      if (upToGen >= population.genPlayers.length) { //if at the end then return to the start and stop doing it
        upToGen = 0;
        showBestEachGen = false;
      } else { //if not at the end then get the next generation
        genPlayerTemp = population.genPlayers[upToGen].cloneForReplay();
        genPlayerTemp.addToWorld();
      }
    }
  } else
  if (humanPlaying) { //if the user is controling the ship[
    if (!humanPlayer.dead) { //if the player isnt dead then move and show the player based on input
      otherWorld.Step(1 / 30, 10, 10);

      humanPlayer.update();
      if (!showNothing) humanPlayer.show();
      humanPlayer.look();

    } else { //once done return to ai
      humanPlaying = false;
    }
  } else
  if (runBest) { // if replaying the best ever game
    if (!population.bestPlayer.dead) { //if best player is not dead
      otherWorld.Step(1 / 30, 10, 10);

      population.bestPlayer.look();
      population.bestPlayer.think();
      population.bestPlayer.update();
      if (!showNothing) population.bestPlayer.show();
    } else { //once dead
      runBest = false; //stop replaying it
      population.bestPlayer = population.bestPlayer.cloneForReplay(); //reset the best player so it can play again
    }
  } else if (fightMode) {
    if (!population.bestPlayer.dead || !humanPlayer.dead) {
      otherWorld.Step(1 / 30, 10, 10);
      humanPlayer.update();
      if (!showNothing) humanPlayer.show();
      population.bestPlayer.look();
      population.bestPlayer.think();
      population.bestPlayer.update();
      if (!showNothing) population.bestPlayer.show();
    } else {
      fightMode = false;
      population.bestPlayer = population.bestPlayer.cloneForReplay();
    }
  } else { //if just evolving normally
    for (var step = 0; step < simSpeed; step++) {
      if (!population.done()) { //if any players are alive then update them
        population.stepWorldsInBatch();
        var isLastStep = (step === simSpeed - 1);
        population.updateAlive(isLastStep);
      } else { //all dead
        //genetic algorithm
        population.naturalSelection();
        currentBestPlayer = population.players[0];
        panX = 0;
        nextPanX = 0;
        targetPanX = 0;
        break; //only run one natural selection per draw frame
      }
    }
  }

  targetPanX = nextPanX;
  let tempMult = 1;
  if (abs(targetPanX - panX) > 20 * panSpeed) {
    tempMult = 5; //floor(abs(targetPanX - panX) / 60);
    console.log(tempMult);
  }
  if (abs(targetPanX - panX) < panSpeed * tempMult) {
    panX = targetPanX;

  } else if (targetPanX - panX < 0) {
    panX -= panSpeed * tempMult;

  } else {
    panX += panSpeed * tempMult;
  }

  if (!showNothing) {
    if (!shownGround) {
      grounds[0].show();
    }
    if (panX < 0) {
      image(darknessSprite, -panX, 400);
    } else {
      image(darknessSprite, 0, 400);
    }
  }

}


//---------------------------------------------------------------------------------------------------------------------------------------------------------
//draws the display screen
function drawToScreen() {
  if (showNothing) {
    background(0);
    fill(255);
    noStroke();
    textAlign(CENTER, CENTER);
    textSize(30);
    text("Rendering disabled (press N to re-enable)", width / 2, height / 2 - 60);
    textSize(20);
    if (population) {
      var totalBatches = ceil(numberOfWorlds / population.worldsPerBatch);
      var currentBatch = min(population.batchNo + 1, totalBatches);
      var liveBest = max(
        population.bestScore || 0,
        population.globalBestScore || 0,
        currentBestPlayer ? currentBestPlayer.score : 0
      );
      text("Gen: " + population.gen + "   Batch: " + currentBatch + " / " + totalBatches, width / 2, height / 2 - 20);
      text("Best score: " + liveBest, width / 2, height / 2 + 10);
      text("Sim speed: " + simSpeed + "x", width / 2, height / 2 + 40);
      textSize(14);
      text("+/- to change sim speed", width / 2, height / 2 + 70);
    }
    return;
  }
  image(skySprite, 0, 0);
  drawBrain();
  writeInfo();
}
//-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
function drawBrain() { //show the brain of whatever genome is currently showing
  var startX = 600; //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
  var startY = 10;
  var w = 600;
  var h = 300;

  if (runBest) {
    population.bestPlayer.brain.drawGenome(startX, startY, w, h);
  } else
  if (humanPlaying) {
    showBrain = false;
  } else if (showBestEachGen) {
    genPlayerTemp.brain.drawGenome(startX, startY, w, h);
  } else if (!fightMode) {
    currentBestPlayer.brain.drawGenome(startX, startY, w, h);
  }
}
//-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
//writes info about the current player
function writeInfo() {
  fill(255);
  stroke(255);
  strokeWeight(1);
  textAlign(LEFT);
  textSize(30);
  if (showBestEachGen) {
    text("Score: " + genPlayerTemp.score, 50, 50); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
    text("Gen: " + (genPlayerTemp.gen + 1), 50, 100);
  } else
  if (humanPlaying) {
    text("Score: " + humanPlayer.score, 100, 50); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
    humanPlayer.look();
    // text("vision[0]: " + humanPlayer.vision[0], 100, 100);
    // text("vision[1]: " + humanPlayer.vision[1], 100, 150);
    // text("vision[2]: " + humanPlayer.vision[2], 100, 200);
    //
    // text("vision[3]: " + humanPlayer.vision[3], 100, 250);
    // text("vision[4]: " + humanPlayer.vision[4], 100, 300);
    // text("vision[5]: " + humanPlayer.vision[5], 100, 350);
    // text("vision[6]: " + humanPlayer.vision[6], 700, 100);
    // text("vision[7]: " + humanPlayer.vision[7], 700, 150);
    // text("vision[8]: " + humanPlayer.vision[8], 700, 200);
    // text("vision[9]: " + humanPlayer.vision[9], 700, 250);
    // text("vision[10]: " + humanPlayer.vision[10], 700, 300);
  } else
  if (runBest) {
    text("Score: " + population.bestPlayer.score, 650, 50); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
    text("Gen: " + population.gen, 1150, 50);
  } else {
    if (showBest) {
      text("Score: " + population.players[0].score, 50, 50); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
      text("Gen: " + population.gen, 50, 100);
      var totalBatches = ceil(numberOfWorlds / population.worldsPerBatch);
      var currentBatch = min(population.batchNo + 1, totalBatches);
      text("Batch: " + currentBatch + " / " + totalBatches, 50, 150);
      // text("Species: " + population.species.length, 50, 150);
      // text("Global Best Score: " + population.globalBestScore, 50, 200);
    } else if (fightMode) {
      text("Your Score: " + humanPlayer.score, 100, 50);
      text("Enemy Score: " + population.bestPlayer.score, 850, 50);
    } else {
      text("Score: " + currentBestPlayer.score, 50, 50); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
      text("Gen: " + population.gen, 300, 50);
      var totalBatches = ceil(numberOfWorlds / population.worldsPerBatch);
      var currentBatch = min(population.batchNo + 1, totalBatches);
      text("Batch: " + currentBatch + " / " + totalBatches, 500, 50);
      text("Speed: " + simSpeed + "x", 850, 50);

      // text("Species: " + population.species.length, 50, 150);
      // text("Global Best Score: " + population.globalBestScore, 50, 200);
      // text("Species: " + population.species.length, 50, canvas.height / 2 + 300);
      // text("Global Best Score: /" + max(population.bestScore, currentBestPlayer.score), 50, canvas.height / 2 + 200);
    }
  }
}

//--------------------------------------------------------------------------------------------------------------------------------------------------

function exitAllSpecialModes() {
  //destroy any bodies the special-mode players still own in otherWorld
  if ((humanPlaying || fightMode) && humanPlayer && humanPlayer.car && !humanPlayer.dead) {
    try { humanPlayer.removePlayerFromWorld(); } catch (e) {}
    humanPlayer.dead = true;
  }
  if ((runBest || fightMode) && population && population.bestPlayer && population.bestPlayer.car && !population.bestPlayer.dead) {
    try { population.bestPlayer.removePlayerFromWorld(); } catch (e) {}
    population.bestPlayer.dead = true;
  }
  if (showBestEachGen && genPlayerTemp && genPlayerTemp.car && !genPlayerTemp.dead) {
    try { genPlayerTemp.removePlayerFromWorld(); } catch (e) {}
    genPlayerTemp.dead = true;
  }

  //rebuild the carless replay templates so the next mode entry starts clean
  if (population && population.bestPlayer) {
    population.bestPlayer = population.bestPlayer.cloneForReplay();
  }
  if (humanPlayer) {
    humanPlayer = humanPlayer.cloneForReplay();
  }

  humanPlaying = false;
  runBest = false;
  fightMode = false;
  showBestEachGen = false;

  //restore currentBestPlayer to a live training player so the HUD/brain display is sane
  if (population && population.players && population.players.length > 0) {
    currentBestPlayer = population.players[0];
    for (var ii = 1; ii < population.players.length; ii++) {
      if (!population.players[ii].dead && population.players[ii].score > currentBestPlayer.score) {
        currentBestPlayer = population.players[ii];
      }
    }
  }

  panX = 0;
  nextPanX = 0;
  targetPanX = 0;
  leftDown = false;
  rightDown = false;
}

function keyPressed() {
  switch ((key || '').toUpperCase()) {
    case ' ':
      //toggle showBest
      showBest = !showBest;
      break;
    case 'F':
      if (population.gen != 1) {
        var wasFightMode = fightMode;
        exitAllSpecialModes();
        if (!wasFightMode) {
          fightMode = true;
          humanPlayer = humanPlayer.cloneForReplay();
          population.bestPlayer = population.bestPlayer.cloneForReplay();
          humanPlayer.addToWorld();
          population.bestPlayer.addToWorld();
        }
      }
      break;
    case 'B': //run the best
      if (population.gen != 1) {
        var wasRunBest = runBest;
        exitAllSpecialModes();
        if (!wasRunBest) {
          runBest = true;
          population.bestPlayer = population.bestPlayer.cloneForReplay();
          population.bestPlayer.addToWorld();
        }
      }
      break;
    case 'G': //show generations
      if (population.gen != 1 && population.genPlayers.length > 0) {
        var wasShowBestEachGen = showBestEachGen;
        exitAllSpecialModes();
        if (!wasShowBestEachGen) {
          showBestEachGen = true;
          upToGen = 0;
          genPlayerTemp = population.genPlayers[upToGen].cloneForReplay();
          genPlayerTemp.addToWorld();
        }
      }
      break;
    case 'N': //show absolutely nothing in order to speed up computation
      showNothing = !showNothing;
      break;
    case 'P': //play
      var wasPlaying = humanPlaying;
      exitAllSpecialModes();
      if (!wasPlaying) {
        humanPlaying = true;
        humanPlayer = humanPlayer.cloneForReplay();
        humanPlayer.addToWorld();
      }
      break;


    case 'S':
      pause = !pause;
      break;
  }
  //speed controls and any of the arrow keys
  switch (keyCode) {
    case 187: //  = / +  on US layouts
    case 107: //  numpad +
      simSpeed = min(simSpeed + 1, 50);
      break;
    case 189: //  - / _  on US layouts
    case 109: //  numpad -
      simSpeed = max(simSpeed - 1, 1);
      break;
    case UP_ARROW: //the only time up/ down / left is used is to control the player
      //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
      break;
    case DOWN_ARROW:
      //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
      break;
    case LEFT_ARROW:
      leftDown = true;
      humanPlayer.car.motorOn(false);
      break;
    case RIGHT_ARROW: //right is used to move through the generations
      if (showBestEachGen) { //if showing the best player each generation then move on to the next generation
        upToGen++;
        if (upToGen >= population.genPlayers.length) { //if reached the current generation then exit out of the showing generations mode
          if (genPlayerTemp && genPlayerTemp.car && !genPlayerTemp.dead) {
            try { genPlayerTemp.removePlayerFromWorld(); } catch (e) {}
            genPlayerTemp.dead = true;
          }
          showBestEachGen = false;
        } else {
          if (genPlayerTemp && genPlayerTemp.car && !genPlayerTemp.dead) {
            try { genPlayerTemp.removePlayerFromWorld(); } catch (e) {}
            genPlayerTemp.dead = true;
          }
          genPlayerTemp = population.genPlayers[upToGen].cloneForReplay();
          genPlayerTemp.addToWorld();

        }
      } else if (humanPlaying || fightMode) { //if the user is playing then move player right
        rightDown = true;
        humanPlayer.car.motorOn(true);
      }
      break;
  }
}

function keyReleased() {
  if (humanPlaying || fightMode) {
    switch (keyCode) {
      case RIGHT_ARROW:
        rightDown = false;
        if (leftDown) {
          humanPlayer.car.motorOn(false);
        } else {
          humanPlayer.car.motorOff();
        }
        break;
      case LEFT_ARROW:
        leftDown = false;
        if (rightDown) {
          humanPlayer.car.motorOn(true);
        } else {
          humanPlayer.car.motorOff();
        }
        break;
    }
  }
}

function clearWorlds() {
  for (var i = 0; i < playersInEachWorld.length; i++) {
    playersInEachWorld[i] = 0;
  }
}

function getFreeWorld() {
  for (var i = 0; i < playersInEachWorld.length; i++) {
    if (playersInEachWorld[i] < playersPerWorld) {
      playersInEachWorld[i]++;
      return (worlds[i]);
    }
  }

  return (worlds[0]);
}

function newWorlds() {
  console.log("New WOrld");
  console.log(groundTemplate.vectors);
  groundTemplate = new Ground();
  groundTemplate.randomizeGround();


  while (groundTemplate.isTooSteep()) {
    groundTemplate = new Ground();
    groundTemplate.randomizeGround();
  }
  console.log(groundTemplate.vectors);

  grounds = [];
  worlds = [];
  playersInEachWorld = [];
  for (var i = 0; i < numberOfWorlds; i++) {
    let tempWorld = new b2World(new Vec2(0, 10), true);
    let tempGround = new Ground(tempWorld);
    tempGround.cloneFrom(groundTemplate);
    tempGround.setBodies(tempWorld);
    tempWorld.SetContactListener(listener);
    // tempWorld.SetContactListener(listener2);

    grounds.push(tempGround);
    worlds.push(tempWorld);
    playersInEachWorld.push(0);
  }

  otherWorld = new b2World(new Vec2(0, 10), true);
  let tempGround = new Ground(otherWorld);
  tempGround.cloneFrom(groundTemplate);
  tempGround.setBodies(otherWorld);
  otherWorld.SetContactListener(listener);

  population.bestScore = 0; //the score of the best ever player
  population.globalBestScore = 0;


  //
  // ground = new Ground(world);
  // ground.cloneFrom(groundTemplate);
  // ground.setBodies(world); //<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<replace
  // world.SetContactListener(listener);
}
