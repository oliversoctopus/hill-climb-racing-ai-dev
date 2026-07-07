"""Manual-play entrypoint. Drive the JS physics with arrow keys.

The simulation runs the actual JS Wheel.js/Car.js/Person.js code via
PyMiniRacer/V8. Terrain is generated in Python (deterministic Perlin)
and handed to JS as a vertex list.

Usage:
    python play.py                       # random terrain
    python play.py --seed 42             # deterministic terrain
    python play.py --episodes 5          # reset 5 times then quit
    python play.py --random-terrain      # new terrain each reset (default: same terrain)

Controls:
    RIGHT     drive forward
    LEFT      reverse
    R         respawn / next terrain
    +/-       sim speed (1..8x)
    ESC / Q   quit
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from env import HillClimbEnv  # noqa: E402
from constants import FRAME_RATE  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--episodes", type=int, default=100,
                        help="Quit after this many episodes (default: ~unlimited).")
    parser.add_argument("--random-terrain", action="store_true",
                        help="Generate fresh terrain each reset (default: reuse same terrain).")
    parser.add_argument("--max-steps", type=int, default=20000)
    args = parser.parse_args()

    env = HillClimbEnv(
        seed=args.seed,
        max_episode_steps=args.max_steps,
        render_mode="human",
        randomize_terrain=args.random_terrain,
    )

    clock = pygame.time.Clock()
    sim_speed = 1
    running = True
    episode = 0
    print("[play] LEFT/RIGHT to drive, R to reset, +/- to change sim speed, ESC to quit")

    while running and episode < args.episodes:
        env.reset()
        env.render(sim_speed=sim_speed)  # initialize pygame video
        ep_steps = 0
        t0 = time.time()
        done = False
        last_info = {"score": 0}

        while not done and running:
            # Read keyboard state for THIS frame, then apply that action
            # sim_speed times per render.
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    elif ev.key == pygame.K_r:
                        done = True
                    elif ev.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                        sim_speed = min(sim_speed + 1, 8)
                    elif ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                        sim_speed = max(sim_speed - 1, 1)

            keys = pygame.key.get_pressed()
            if keys[pygame.K_RIGHT]:
                action = 0  # forward
            elif keys[pygame.K_LEFT]:
                action = 1  # reverse
            else:
                action = 2  # off

            for _ in range(sim_speed):
                obs, r, term, trunc, info = env.step(action)
                ep_steps += 1
                last_info = info
                if term or trunc:
                    done = True
                    break

            env.render(sim_speed=sim_speed)
            clock.tick(FRAME_RATE)

        dt = time.time() - t0
        print(f"  ep{episode}: steps={ep_steps}  score={last_info.get('score', 0)}  wall={dt:.1f}s")
        episode += 1

    env.close()


if __name__ == "__main__":
    main()
