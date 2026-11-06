// Bridge from classic-script globals into ES-module scope.
//
// The physics classes (Car/Wheel/Person/Ground), the Box2D handles, the p5 noise
// seeder, and the AI-policy factory are all declared in classic <script>s. They
// have to stay classic: the SAME physics files are loaded verbatim into V8 for
// training (python/js_backend.py) and by legacy_neat/, neither of which has an ES
// module loader or a `window`. Top-level `class`/`const` in a classic script live
// in the global LEXICAL environment, invisible to module scope, so index.html
// publishes exactly what the app needs onto `window.HCR` in a one-line classic
// shim (right after the physics scripts). We re-export it here as normal module
// bindings.
const H = window.HCR || {};

export const Car = H.Car;
export const Ground = H.Ground;
export const Box2D = H.Box2D;
export const Vec2 = H.Vec2;
export const b2World = H.b2World;
export const b2StaticBody = H.b2StaticBody;
export const perlinSeed = H.perlinSeed;   // p5-noise permutation seeder (_perlinSeed)
export const AiPolicy = H.AiPolicy;        // { PpoOnnxAgent, ConstantForwardAgent, ACT }

// Ground-edge collision filters. These are `var`s in index.html's compat shim, so
// (unlike the lexical class/const bindings above) they land on `window` directly —
// no HCR entry needed. The Open/Close Exit cheat uses them to rebuild the underworld's
// right wall exactly as Ground.setBodies() made it.
export const DIRT_MASK = window.DIRT_MASK, DIRT_CATEGORY = window.DIRT_CATEGORY;
export const GRASS_MASK = window.GRASS_MASK, GRASS_CATEGORY = window.GRASS_CATEGORY;

// Ground.js reads/writes `spawningY` and `grassSprites` as window globals; a bare
// `spawningY = x` in a module would create a module-local instead, hence accessors.
export function getSpawningY() { return window.spawningY; }
export function setSpawningY(v) { window.spawningY = v; }
export function setGrassSprites(v) { window.grassSprites = v; }
