// Coordinate/sign helpers.
//
// World space is y-DOWN: larger y = lower on screen. That makes clearance/altitude
// sign errors easy to introduce, so the two sign conventions live here, named, in
// one place instead of as bare subtractions scattered through render + sim.
import { CANVAS_HEIGHT, SCALE } from "./state.js";
import { T } from "./tune.js";

// Height of a point above the ground line directly below it, in whatever unit the
// inputs are (meters or px, as long as they match). Positive = the point is ABOVE
// the ground; y-down means groundY > pointY when airborne.
export function altitudeAbove(groundY, pointY) {
  return groundY - pointY;
}

// The fall-off kill line as a fixed WORLD level, in meters. The camera never pans
// vertically (screen y = world y * SCALE — the death test is chassis y*30 > 720), so the
// bottom-of-screen death line sits at a constant world altitude regardless of where the
// car is along the track. That makes it a natural "sea level" zero for an absolute
// altimeter that reads the car's true elevation rather than its clearance over the hill
// directly below it.
export const KILL_LINE_M = CANVAS_HEIGHT / SCALE;   // 24 m

// Height of a point (world meters, y-down) above the fixed kill-line level. Positive =
// above the death line, i.e. the vertical margin before the point falls off the bottom.
export function altitudeAboveKillLine(pointY) {
  return KILL_LINE_M - pointY;
}

// A car has fallen off the world once its chassis drops below the bottom of the
// screen (the death line the policy was trained against — chassis y*30 > 720).
// Argument is in PIXELS. The physics playground can push the line deeper (default 24 m).
export function isBelowKillLine(yPx) {
  return yPx > T.killLineM * SCALE;
}
