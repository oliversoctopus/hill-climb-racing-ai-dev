"""Gymnasium environment wrapping the JS physics simulation via V8.

The physics simulation is the unmodified JS Box2D.js + Wheel.js + Person.js +
Car.js code from the original browser game, executed inside a V8 isolate via
PyMiniRacer. Terrain is generated in Python (deterministic Perlin) and the
vertex list is handed to JS, which builds the static bodies and the car
using the original game classes.

Why JS physics: pybox2d 2.3.10's constraint solver allows ~30-100 mm of
wheel perpendicular drift during impacts; the JS Box2D 2.0/2.1 solver
allows only ~1-4 mm. The drift wasn't tuneable from Python (Box2D's
b2Settings constants are compile-time and SWIG just exposes read-only
rebindings). Migrating Python-side to Box2D 3.0 only halved the drift.
Running the JS physics directly via V8 gives an exact match — no drift
gap, and as a bonus the trained policy can run in the browser game
without porting concerns.

Observation (Box, float32). Base layout (before VecFrameStack), 11-dim default
(12-dim with per_wheel_obs); +GROUND_REAR_N if rear vision is re-enabled:
    0     chassis angle, wrapped through ((angle + PI) mod 2*PI) / (2*PI) -> [0, 1]
    1     on-ground (10-frame coyote)   [per_wheel: 1=rear, 2=front]
    next  chassis angular velocity, /4 clipped to [-1, 1]
    next  chassis vx, /17 clipped to [-1, 1]
    next  chassis vy, /12 clipped to [-1, 1]
    +N    ground clearance AHEAD at chassis_x + 0, 75, 150, ... px (lookahead_n
          samples, 75px apart; default 6 -> 375px/12.5m, 13 -> 900px/30m = the
          full human screen view)
    +GROUND_REAR_N  ground clearance BEHIND (DISABLED by default, GROUND_REAR_N=0)
          (all clearances: chassis_bottom_y - ground_y in meters, clipped to
           [-3, 10], mapped to [-1, 1]).

Action: same as before, Discrete(3) {0=forward, 1=reverse, 2=off}
        OR Box(-1, 1, shape=(1,)) when continuous_action=True (for SAC).

Reward: max(0, delta_x_m) — forward progress in meters, no backward penalty.

Termination: car dead (head touched ground, or chassis fell off canvas).
             Truncation: step count >= max_episode_steps.
"""

from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np
import gymnasium as gym
from gymnasium import spaces

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from constants import (  # noqa: E402
    SCALE,
    CANVAS_HEIGHT,
    SPAWN_X,
    CHASSIS_HEIGHT,
    SPAWN_Y_BACK_FROM_GROUND,
)
from ground import Ground, make_ground as _make_ground  # noqa: E402
from js_backend import JSPhysics  # noqa: E402
import obs_spec  # noqa: E402  (single source of the obs encoding; CONVENTIONS.md #4)

# Obs topology + normalization constants are single-sourced in obs_spec.py
# (CONVENTIONS.md #4); these module aliases keep existing references working.
# GROUND_LOOKAHEAD_N is the DEFAULT (per-env override via lookahead_n= /
# HCR_LOOKAHEAD_N; 6 * skip 5 * 15px = 375px/12.5m ahead, 13 = 900px/30m = the
# full human view). Rearward samples (GROUND_REAR_N) let the policy see behind
# it (escape-a-pothole vision); DISABLED (=0) for the deployed champion — the
# JS/ai_policy.js rear code stays guarded on rear_n>0, so re-enabling means
# bumping obs_spec.REAR_N and retraining.
GROUND_LOOKAHEAD_N = obs_spec.LOOKAHEAD_N
GROUND_LOOKAHEAD_SKIP = obs_spec.LOOKAHEAD_SKIP
GROUND_REAR_N = obs_spec.REAR_N
GROUND_REAR_SKIP = obs_spec.REAR_SKIP
COYOTE_FRAMES = obs_spec.COYOTE_FRAMES

GROUND_CLEARANCE_MIN = obs_spec.CLEARANCE_MIN_M
GROUND_CLEARANCE_MAX = obs_spec.CLEARANCE_MAX_M

# ---- In-episode "nudge" (exploration perturbation) ----
# Occasionally kick the chassis with a small, recoverable velocity perturbation
# DURING an episode (not just at spawn like spawn_jitter), so the policy sees a
# broader state distribution and must learn to recover/continue from being
# knocked off its trajectory. Modeled as environment dynamics noise (the agent
# observes the post-nudge state and acts) so PPO stays on-policy. All off by
# default (nudge_prob=0) -> byte-identical to the champion recipe.
NUDGE_GRACE_TICKS = 30    # ~1s: suppress the death penalty for this many ticks
                          # after a nudge so a nudge-caused death isn't charged to
                          # the policy (cf. the over-caution the death-penalty
                          # experiments showed). Also blocks back-to-back nudges.
NUDGE_LINEAR_FRAC = 1.0   # peak |linear vx/vy| nudge (m/s) = NUDGE_LINEAR_FRAC * nudge_mag


@dataclass
class EnvConfig:
    """Resolved environment configuration. Values come from constructor kwargs,
    then HCR_* env vars OVERRIDE them (env wins — this is what lets SubprocVecEnv
    workers inherit config without pickling it through the process boundary). An
    override that actually changes a value is logged, so it isn't silent. Single
    source of the env config surface (CONVENTIONS.md #5)."""

    per_wheel_obs: bool = obs_spec.PER_WHEEL
    reward_shaping: bool = True
    death_penalty: float = 50.0
    lookahead_n: int = obs_spec.LOOKAHEAD_N
    spawn_jitter: float = 0.0
    nudge_prob: float = 0.0
    nudge_mag: float = 0.5
    difficulty_max: float = 0.0
    difficulty_override: Optional[float] = None   # HCR_DIFFICULTY only (no kwarg)

    # (attr, env_var, parse_env_string, normalize). `normalize` runs on the
    # resolved value from EITHER source, matching the old `self.x = max(...)`.
    _SPEC = [
        ("per_wheel_obs",       "HCR_PER_WHEEL",      lambda s: s == "1", None),
        ("reward_shaping",      "HCR_REWARD_SHAPING", lambda s: s == "1", None),
        ("death_penalty",       "HCR_DEATH_PENALTY",  float,              float),
        ("lookahead_n",         "HCR_LOOKAHEAD_N",    int,                lambda v: max(1, int(v))),
        ("spawn_jitter",        "HCR_SPAWN_JITTER",   float,              lambda v: max(0.0, float(v))),
        ("nudge_prob",          "HCR_NUDGE_PROB",     float,              lambda v: max(0.0, float(v))),
        ("nudge_mag",           "HCR_NUDGE_MAG",      float,              lambda v: max(0.0, float(v))),
        ("difficulty_max",      "HCR_DIFFICULTY_MAX", float,              lambda v: max(0.0, min(1.0, float(v)))),
        ("difficulty_override", "HCR_DIFFICULTY",     float,              lambda v: max(0.0, min(1.0, float(v)))),
    ]

    @classmethod
    def resolve(cls, **kwargs) -> "EnvConfig":
        cfg = cls(**kwargs)
        overrides = []
        for attr, env_var, parse, normalize in cls._SPEC:
            raw = os.environ.get(env_var)
            before = getattr(cfg, attr)
            if raw is not None:
                try:
                    setattr(cfg, attr, parse(raw))
                except (ValueError, TypeError):
                    pass   # unparseable env var -> keep the kwarg/default
            val = getattr(cfg, attr)
            if normalize is not None and val is not None:
                val = normalize(val)
                setattr(cfg, attr, val)
            if raw is not None and val != before:
                overrides.append(f"{env_var}={val!r} (kwarg/default {before!r})")
        if overrides:
            print("[env] HCR override: " + ", ".join(overrides), file=sys.stderr)
        return cfg


class HillClimbEnv(gym.Env):
    """Single-env training env. One physics tick per step()."""

    metadata = {"render_modes": [None, "human"]}

    def __init__(
        self,
        *,
        max_episode_steps: int = 2000,
        render_mode: Optional[str] = None,
        seed: Optional[int] = None,
        randomize_terrain: bool = False,
        continuous_action: bool = False,
        per_wheel_obs: bool = True,     # 12-dim obs (rear+front grounded) vs 11-dim legacy
        reward_shaping: bool = True,    # +0.01/tick survival + -death_penalty on death
        death_penalty: float = 50.0,    # reward subtracted on death (incl. stuck-timeout)
        difficulty_max: float = 0.0,    # reverse-curriculum cap f_max; per-episode f~U(0,f_max)
        lookahead_n: int = GROUND_LOOKAHEAD_N,  # forward ground samples (75px apart)
        spawn_jitter: float = 0.0,      # +-px uniform spawn perturbation per episode
                                        # (robustness training: learn wide-basin
                                        # trajectories that survive the same +-1px
                                        # eval jitter). 0 = byte-identical to before.
        nudge_prob: float = 0.0,        # per-tick probability of an in-episode nudge
                                        # (exploration perturbation; see NUDGE_* above).
                                        # 0 = off = byte-identical to before.
        nudge_mag: float = 0.5,         # peak |angular-velocity| nudge (rad/s); the
                                        # linear vx/vy kick scales with it.
    ):
        super().__init__()

        # Resolve config: constructor kwargs, then HCR_* env vars override them
        # (env wins; changes are logged). Single source: EnvConfig (CONVENTIONS.md #5).
        cfg = EnvConfig.resolve(
            per_wheel_obs=per_wheel_obs,
            reward_shaping=reward_shaping,
            death_penalty=death_penalty,
            lookahead_n=lookahead_n,
            spawn_jitter=spawn_jitter,
            nudge_prob=nudge_prob,
            nudge_mag=nudge_mag,
            difficulty_max=difficulty_max,
        )
        self.cfg = cfg
        self.per_wheel_obs = cfg.per_wheel_obs
        self.reward_shaping = cfg.reward_shaping
        self.death_penalty = cfg.death_penalty
        self.lookahead_n = cfg.lookahead_n
        self.spawn_jitter = cfg.spawn_jitter
        self.nudge_prob = cfg.nudge_prob
        self.nudge_mag = cfg.nudge_mag
        # Fixed-difficulty override (pins every episode's f; HCR_DIFFICULTY only,
        # no kwarg). None = sample normally.
        self._difficulty_override: Optional[float] = cfg.difficulty_override

        if self.per_wheel_obs:
            # angle + 2 per-wheel + 3 vel/angvel + N ground ahead + rear ground
            n_dim = 6 + self.lookahead_n + GROUND_REAR_N
            low = np.full(n_dim, -1.0, dtype=np.float32)
            low[0] = 0.0
            low[1] = 0.0   # rear-wheel grounded
            low[2] = 0.0   # front-wheel grounded
        else:
            # angle + 1 grounded + 3 vel/angvel + N ground ahead + rear ground
            n_dim = 5 + self.lookahead_n + GROUND_REAR_N
            low = np.full(n_dim, -1.0, dtype=np.float32)
            low[0] = 0.0
            low[1] = 0.0
        high = np.ones(n_dim, dtype=np.float32)
        self.observation_space = spaces.Box(low=low, high=high, dtype=np.float32)

        self.continuous_action = continuous_action
        if continuous_action:
            self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)
        else:
            self.action_space = spaces.Discrete(3)

        self.max_episode_steps = max_episode_steps
        self.render_mode = render_mode
        self._init_seed = seed
        self.randomize_terrain = randomize_terrain
        self._terrain_episode = 0

        # Lazy: V8 instance is created on first reset() (so SubprocVecEnv
        # workers don't all hammer JS load in __init__).
        self._js: Optional[JSPhysics] = None
        self._ground: Optional[Ground] = None
        self.steps = 0
        self.last_grounded_rear = 0
        self.last_grounded_front = 0
        self.prev_chassis_x_m = 0.0
        self._max_dist_px = 0.0
        self._renderer = None

        # Stuck-timeout: matches old Python env behavior (500 ticks without
        # a new 50px milestone => dead). Implemented here because JS Car.update()
        # already disables its no-progress check when humanPlaying=true.
        self._stuck_change_count = 0

        # ---- Reverse-curriculum state ----
        # f_max is the current ceiling of the difficulty range; each episode
        # draws f ~ U(0, f_max). The callback raises f_max over training. f=0 is
        # normal, so f_max=0 (the default, and eval) means pure-normal terrain.
        self._f_max = cfg.difficulty_max
        # f used to build THIS episode's terrain (sampled in reset()).
        self._difficulty = 0.0
        # Per-episode difficulty RNG, seeded deterministically per worker so a
        # given seed reproduces the same f-sequence.
        f_seed = (self._init_seed if self._init_seed is not None else 0)
        self._f_rng = random.Random((int(f_seed) * 2654435761 + 12345) & 0x7FFFFFFF)
        # Independent per-episode spawn-jitter RNG (deterministic per worker so a
        # given seed reproduces the same jitter sequence).
        self._jitter_rng = random.Random((int(f_seed) * 40503 + 99991) & 0x7FFFFFFF)
        self._cur_dx = 0.0
        self._cur_dy = 0.0
        # Independent per-worker nudge RNG (deterministic so a given seed
        # reproduces the same nudge sequence).
        self._nudge_rng = random.Random((int(f_seed) * 27644437 + 1299709) & 0x7FFFFFFF)
        # Ticks remaining in the post-nudge grace window (death penalty suppressed
        # + new nudges blocked). 0 = not in a window.
        self._nudge_grace = 0
        self._nudges_this_ep = 0
        # Where the car was dropped this episode (px). Progress/score measured
        # relative to this (always SPAWN_X now — no mid-track spawns).
        self._spawn_x_px = float(SPAWN_X)

    # ------------------------------------------------------------------
    def set_difficulty_max(self, f_max: float) -> None:
        """Set the reverse-curriculum ceiling f_max in [0, 1]. Called by the
        training callback each rollout (via VecEnv.env_method) to expand the
        difficulty range over the run. Each episode then draws f ~ U(0, f_max)."""
        self._f_max = max(0.0, min(1.0, float(f_max)))

    def get_difficulty_max(self) -> float:
        return self._f_max

    def get_difficulty(self) -> float:
        """The f used for the current episode's terrain."""
        return self._difficulty

    def _sample_difficulty(self) -> float:
        """Draw this episode's difficulty f. Fixed override (HCR_DIFFICULTY)
        pins it; otherwise f ~ U(0, f_max)."""
        if self._difficulty_override is not None:
            return self._difficulty_override
        if self._f_max <= 0.0:
            return 0.0
        return self._f_rng.uniform(0.0, self._f_max)

    # ------------------------------------------------------------------
    def _generate_seed(self) -> Optional[float]:
        """Return a deterministic terrain seed for the current episode."""
        if self._init_seed is None:
            return None
        import random as _random
        # Multiply by a large prime + episode index so siblings (different
        # _terrain_episode under the same _init_seed) get well-separated seeds.
        rng = _random.Random(self._init_seed * 1000003 + self._terrain_episode)
        return rng.uniform(1.0, 1_000_000.0)

    def _build_for_episode(self, regen_terrain: bool):
        if self._js is None:
            self._js = JSPhysics()
        # Per-episode spawn position, optionally jittered by +-spawn_jitter px.
        # dx/dy are sampled in reset(); both 0 when spawn_jitter == 0.
        spawn_x = float(SPAWN_X) + self._cur_dx
        if regen_terrain or self._ground is None:
            seed = self._generate_seed() if self._terrain_episode > 0 else (
                float(self._init_seed) if self._init_seed is not None else None
            )
            self._ground = _make_ground(seed, self._difficulty)
            self._js.build_world(self._ground.vectors, spawn_x,
                                 self._ground.spawning_y + self._cur_dy)
        else:
            # Reuse terrain, respawn the car. Only override the spawn when jitter
            # is ACTIVE; otherwise leave _spawnX as-is so an external set_spawn()
            # (the eval / Best-of-X harnesses' jitter trick) still controls the
            # respawn point. (Calling set_spawn unconditionally here silently
            # broke those harnesses.)
            if self.spawn_jitter > 0.0:
                self._js.set_spawn(spawn_x, self._ground.spawning_y + self._cur_dy)
            self._js.reset_car()
        self._spawn_x_px = spawn_x

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        if seed is not None:
            self._init_seed = seed
            # New seed sequence — reset the episode counter so we get a
            # deterministic series.
            self._terrain_episode = 0
            self._ground = None  # force terrain rebuild
            # Reseed the per-episode difficulty RNG for a reproducible f-sequence.
            self._f_rng = random.Random((int(seed) * 2654435761 + 12345) & 0x7FFFFFFF)

        # Sample this episode's spawn jitter (0 when spawn_jitter == 0, so the
        # spawn is exactly SPAWN_X / spawning_y as before).
        if self.spawn_jitter > 0.0:
            self._cur_dx = self._jitter_rng.uniform(-self.spawn_jitter, self.spawn_jitter)
            self._cur_dy = self._jitter_rng.uniform(-self.spawn_jitter, self.spawn_jitter)
        else:
            self._cur_dx = 0.0
            self._cur_dy = 0.0

        # Decide: first build, regen terrain, or respawn. Sample this episode's
        # difficulty f ~ U(0, f_max) whenever we (re)generate terrain.
        if self._js is None or self._ground is None:
            # First time in this worker — full build.
            self._difficulty = self._sample_difficulty()
            self._build_for_episode(regen_terrain=True)
        elif self.randomize_terrain:
            self._terrain_episode += 1
            self._difficulty = self._sample_difficulty()
            self._build_for_episode(regen_terrain=True)
        else:
            # Fixed-terrain mode — just respawn the car (keep same f/terrain).
            self._build_for_episode(regen_terrain=False)

        self.steps = 0
        self.last_grounded_rear = 0
        self.last_grounded_front = 0
        self._max_dist_px = self._spawn_x_px
        self._stuck_change_count = 0
        self._nudge_grace = 0
        self._nudges_this_ep = 0

        state = self._js.state(self.lookahead_n, GROUND_LOOKAHEAD_SKIP,
                               GROUND_REAR_N, GROUND_REAR_SKIP)
        self.prev_chassis_x_m = state["x"]
        return self._build_obs(state), {}

    # ------------------------------------------------------------------
    def step(self, action):
        # Discrete action in the JS layer: 0=forward, 1=reverse, 2=off.
        # For continuous: deadband [-0.1, 0.1] -> off, sign picks direction.
        # The JS Car.motorOn() applies full motor torque regardless of
        # magnitude (the JS class doesn't support throttle scaling), so
        # the continuous action loses its torque-magnitude dimension here.
        # If the SAC experiments matter, motorOn() in Car.js would need a
        # tweak to honor a torque scale; for now we just use sign.
        if self.continuous_action:
            throttle = float(np.asarray(action).reshape(-1)[0])
            if abs(throttle) < 0.1:
                act = 2
            elif throttle > 0:
                act = 0
            else:
                act = 1
        else:
            act = int(action)

        # Optional in-episode "nudge" (exploration perturbation). With small
        # per-tick probability we step, then add a small recoverable velocity
        # kick, so the policy must observe and continue from being knocked off
        # its trajectory. The nudge is part of the env transition (PPO stays
        # on-policy). Gates: only while grounded (recoverable) and outside an
        # existing grace window (no compounding); the death penalty is then
        # suppressed for NUDGE_GRACE_TICKS so a nudge-caused death isn't charged
        # to the policy. Default (nudge_prob=0) skips this entirely.
        do_nudge = (
            self.nudge_prob > 0.0
            and self._nudge_grace == 0
            and self.last_grounded_rear < COYOTE_FRAMES
            and self._nudge_rng.random() < self.nudge_prob
        )
        if do_nudge:
            self._js.step(act)
            m = self.nudge_mag
            dav = self._nudge_rng.uniform(-m, m)
            dvx = self._nudge_rng.uniform(-m, m) * NUDGE_LINEAR_FRAC
            dvy = self._nudge_rng.uniform(-m, m) * NUDGE_LINEAR_FRAC
            self._js.nudge(dvx, dvy, dav)
            state = self._js.state(self.lookahead_n, GROUND_LOOKAHEAD_SKIP,
                                   GROUND_REAR_N, GROUND_REAR_SKIP)
            self._nudge_grace = NUDGE_GRACE_TICKS
            self._nudges_this_ep += 1
        else:
            state = self._js.step_and_state(act, self.lookahead_n, GROUND_LOOKAHEAD_SKIP,
                                            GROUND_REAR_N, GROUND_REAR_SKIP)
            if self._nudge_grace > 0:
                self._nudge_grace -= 1
        self.steps += 1
        x_m = state["x"]
        reward = max(0.0, float(x_m - self.prev_chassis_x_m))
        self.prev_chassis_x_m = x_m

        # Track max distance for score + stuck timeout.
        x_px = x_m * SCALE
        self._stuck_change_count += 1
        if x_px > self._max_dist_px:
            self._max_dist_px = x_px
            # JS Car.js resets the stuck counter on every multiple of 50 px crossed.
            # We mirror that behavior here so the timeout matches Python old env.
            if int(self._max_dist_px) % 50 == 0:
                self._stuck_change_count = 0

        # Termination: dead (head hit ground or fell off canvas) or stuck.
        dead = bool(state["dead"]) or (state["y"] * SCALE > CANVAS_HEIGHT)
        if self._stuck_change_count > 500:
            dead = True

        terminated = dead
        truncated = self.steps >= self.max_episode_steps

        # Reward shaping (only when enabled): per-tick survival bonus + death penalty.
        if self.reward_shaping:
            reward += 0.01
            # Suppress the death penalty inside a post-nudge grace window: a
            # death right after a nudge isn't the policy's fault (a nudge on this
            # tick set grace > 0, covering same-tick nudge-into-wall deaths too).
            if terminated and self._nudge_grace == 0:
                reward -= self.death_penalty

        info = {
            "max_distance_px": self._max_dist_px,
            # Distance from this episode's spawn (handles mid-track spawns).
            "score": max(0, int((self._max_dist_px - self._spawn_x_px) / 10)),
            "nudges": self._nudges_this_ep,
        }
        return self._build_obs(state), reward, terminated, truncated, info

    # ------------------------------------------------------------------
    def _build_obs(self, state: dict) -> np.ndarray:
        """Build the normalized observation. Shape depends on per_wheel_obs:
        11-dim (single grounded bit) or 12-dim (rear + front)."""
        # [0] angle wrapped to [0, 1]
        a = state["angle"]
        while a < 0.0:
            a += 2.0 * math.pi
        a = (a + math.pi) % (2.0 * math.pi)
        obs_angle = a / (2.0 * math.pi)

        # Groundedness with 10-frame coyote
        if self.per_wheel_obs:
            self.last_grounded_rear += 1
            if state.get("on_ground_rear", state["on_ground_now"]):
                self.last_grounded_rear = 0
            obs_rear = 1.0 if self.last_grounded_rear < COYOTE_FRAMES else 0.0

            self.last_grounded_front += 1
            if state.get("on_ground_front", state["on_ground_now"]):
                self.last_grounded_front = 0
            obs_front = 1.0 if self.last_grounded_front < COYOTE_FRAMES else 0.0
        else:
            self.last_grounded_rear += 1
            if state["on_ground_now"]:
                self.last_grounded_rear = 0
                obs_grounded = 1.0
            else:
                obs_grounded = 1.0 if self.last_grounded_rear < COYOTE_FRAMES else 0.0

        # ang vel, linear velocity
        obs_av = max(-1.0, min(1.0, state["ang_vel"] / obs_spec.ANG_VEL_SCALE))
        obs_vx = max(-1.0, min(1.0, state["vx"] / obs_spec.VX_SCALE))
        obs_vy = max(-1.0, min(1.0, state["vy"] / obs_spec.VY_SCALE))

        # lookahead_n ground clearance samples ahead
        chassis_bottom_y_m = state["y"] + CHASSIS_HEIGHT / SCALE
        clearance_center = 0.5 * (GROUND_CLEARANCE_MAX + GROUND_CLEARANCE_MIN)
        clearance_half = 0.5 * (GROUND_CLEARANCE_MAX - GROUND_CLEARANCE_MIN)
        positions_m = state["ground_samples"]   # meters (js_backend getPositions)
        ground_samples = []
        for i in range(self.lookahead_n):
            pos_m = positions_m[i] if i < len(positions_m) else positions_m[-1]
            c = pos_m - chassis_bottom_y_m
            c = max(GROUND_CLEARANCE_MIN, min(GROUND_CLEARANCE_MAX, c))
            ground_samples.append((c - clearance_center) / clearance_half)

        # Rearward samples (same clearance encoding). Empty if the JS layer
        # wasn't asked for them; pad with the nearest value for safety.
        rear_m = state.get("ground_samples_rear", [])   # meters
        rear_samples = []
        for i in range(GROUND_REAR_N):
            if rear_m:
                pos_m = rear_m[i] if i < len(rear_m) else rear_m[-1]
            else:
                pos_m = positions_m[0]  # fall back to the under-chassis sample
            c = pos_m - chassis_bottom_y_m
            c = max(GROUND_CLEARANCE_MIN, min(GROUND_CLEARANCE_MAX, c))
            rear_samples.append((c - clearance_center) / clearance_half)

        if self.per_wheel_obs:
            return np.array(
                [obs_angle, obs_rear, obs_front, obs_av, obs_vx, obs_vy,
                 *ground_samples, *rear_samples],
                dtype=np.float32,
            )
        return np.array(
            [obs_angle, obs_grounded, obs_av, obs_vx, obs_vy,
             *ground_samples, *rear_samples],
            dtype=np.float32,
        )

    # ------------------------------------------------------------------
    def render(self, sim_speed: int = 1):
        if self.render_mode != "human":
            return None
        if self._renderer is None:
            from renderer import Renderer  # lazy
            self._renderer = Renderer(title="Hill Climb (JS physics)")
        # Pull fresh geometry from JS each frame.
        rs = self._js.render_state()
        # Camera follows the chassis.
        chassis_x_px = rs["chassis_polys"][0][0][0] if rs.get("chassis_polys") else SPAWN_X
        # Better: read chassis center from the last state() (cheap to recompute).
        st = self._js.state(self.lookahead_n, GROUND_LOOKAHEAD_SKIP)
        car_x_px = st["x"] * SCALE
        self._renderer.update_camera(car_x_px, SPAWN_X)
        score = max(0, int((self._max_dist_px - SPAWN_X) / 10))
        self._renderer.draw_frame(self._ground, rs, score=score,
                                  sim_speed=sim_speed,
                                  on_ground=st["on_ground_now"])

    def close(self):
        # MiniRacer cleans up its V8 isolate on GC.
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._js = None
