// Mode table — the single source for per-mode behavior. This replaces the
// `if (mode === "...")` chains that used to be scattered across world-building,
// rendering, stats, canvas sizing, and the label/panel wiring.
//
// Each entry declares:
//   label        status-line text
//   spawn        the players to create, in order. Each: { agent:"ai"|"human",
//                color?, control?("wasd"|"arrows") }. Defaults: ai->AI_COLOR,
//                human->HUMAN_COLOR. Best of X applies its sub-pixel jitter to the
//                (single) AI player.
//   split        true => side-by-side split screen (2x-wide canvas, per-side HUD)
//   bestofxPanel true => show the Best-of-X controls panel
import {
  S, CANVAS_WIDTH, AI_COLOR, AI2_COLOR, HUMAN_COLOR, HUMAN_L_COLOR, HUMAN_R_COLOR,
} from "./state.js";

export const MODES = {
  ai: {
    label: "AI is driving",
    spawn: [{ agent: "ai" }],
    split: false, bestofxPanel: false,
  },
  human: {
    label: "Your turn — arrow keys",
    spawn: [{ agent: "human" }],
    split: false, bestofxPanel: false,
  },
  vs: {
    label: "Human vs AI — race!",
    spawn: [{ agent: "ai" }, { agent: "human" }],
    split: false, bestofxPanel: false,
  },
  hvh: {
    label: "Human vs Human — Left: WASD  ·  Right: Arrow keys  ·  same terrain, race!",
    spawn: [
      { agent: "human", color: HUMAN_L_COLOR, control: "wasd" },
      { agent: "human", color: HUMAN_R_COLOR, control: "arrows" },
    ],
    split: true, bestofxPanel: false,
  },
  bestofx: {
    label: "Best of X — set attempts then click Run",
    spawn: [{ agent: "ai" }],
    split: false, bestofxPanel: true,
  },
  // Dev mode only: the main AI vs "AI B" (a second, separately loadable model).
  aivai: {
    label: "AI vs AI (dev) — main AI vs AI B",
    spawn: [{ agent: "ai" }, { agent: "ai2", color: AI2_COLOR }],
    split: false, bestofxPanel: false,
  },
};

export function modeDef(m) { return MODES[m] || MODES.ai; }

// Default color for a spawn entry that doesn't override it.
export function spawnColor(def) {
  return def.color || (def.agent === "human" ? HUMAN_COLOR : AI_COLOR);
}

// Status-line label for the current mode.
export function modeLabel() { return modeDef(S.mode).label; }

// Total canvas width for the current mode: Human-vs-Human shows two full
// standard-width screens side by side (2x wide); every other mode is one screen.
export function stageWidth() { return modeDef(S.mode).split ? CANVAS_WIDTH * 2 : CANVAS_WIDTH; }
