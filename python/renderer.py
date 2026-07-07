"""pygame renderer.

Draws from a render-state dict produced by the JS backend (see
js_backend.JSPhysics.render_state()). The dict carries world-pixel-space
geometry for the chassis polygons, wheel circles, torso box, and head
circle. The renderer doesn't know anything about Box2D or pybox2d.

Coordinate system mirrors JS: pixel-space, y-down. Camera follows the car
by a pan offset subtracted from world coords before drawing.
"""

from __future__ import annotations

import math
from typing import Iterable

import pygame

from constants import CANVAS_WIDTH, CANVAS_HEIGHT

SKY = (135, 206, 235)
DIRT = (88, 35, 0)
GRASS_DARK = (0, 100, 0)
GRASS_LIGHT = (0, 140, 0)
CHASSIS_COLOR = (50, 50, 50)
CHASSIS_OUTLINE = (255, 80, 80)
WHEEL_COLOR = (20, 20, 20)
RIM_COLOR = (180, 180, 180)
TORSO_COLOR = (60, 90, 200)
HEAD_COLOR = (240, 200, 160)
TEXT_COLOR = (255, 255, 255)


def _rotate_rect_corners(cx, cy, w, h, angle):
    """Return the 4 world-pixel corners of a rectangle centered at (cx, cy),
    width w, height h, rotated by angle (radians)."""
    hw, hh = w / 2.0, h / 2.0
    c, s = math.cos(angle), math.sin(angle)
    local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [(cx + c * lx - s * ly, cy + s * lx + c * ly) for lx, ly in local]


class Renderer:
    def __init__(self, width: int = CANVAS_WIDTH, height: int = CANVAS_HEIGHT,
                 *, title: str = "Hill Climb (Python+JS)"):
        pygame.init()
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.font = pygame.font.SysFont("consolas", 18)
        self.big_font = pygame.font.SysFont("consolas", 26, bold=True)
        self.width = width
        self.height = height
        self.pan_x = 0.0
        self.pan_y = 0.0

    # ----------------------------------------------------------------
    def update_camera(self, car_x_px: float, starting_x_px: float) -> None:
        target = max(0.0, car_x_px - starting_x_px)
        if abs(target - self.pan_x) > 400:
            self.pan_x = target
        else:
            self.pan_x += (target - self.pan_x) * 0.25

    def snap_camera(self) -> None:
        self.pan_x = 0.0

    def w2s(self, x_px: float, y_px: float) -> tuple[int, int]:
        return int(x_px - self.pan_x), int(y_px - self.pan_y)

    # ----------------------------------------------------------------
    def draw_frame(self, ground, render_state: dict, score: int,
                   sim_speed: int = 1, on_ground: bool = False, *,
                   debug_lines: Iterable[str] = ()) -> None:
        self.screen.fill(SKY)
        self._draw_ground(ground)
        if render_state:
            self._draw_car(render_state)
        self._draw_hud(score, sim_speed, on_ground, debug_lines=debug_lines)
        pygame.display.flip()

    # ----------------------------------------------------------------
    def _draw_ground(self, ground) -> None:
        verts = ground.vectors
        if len(verts) < 3:
            return

        x_left = self.pan_x - 50
        x_right = self.pan_x + self.width + 50

        pts_top = []
        for vx, vy in verts[:-2]:  # last two verts are the closing box corners
            if vx < x_left:
                continue
            if vx > x_right:
                break
            pts_top.append(self.w2s(vx, vy))

        if len(pts_top) >= 2:
            poly = pts_top + [(pts_top[-1][0], self.height), (pts_top[0][0], self.height)]
            pygame.draw.polygon(self.screen, DIRT, poly)
            pygame.draw.lines(self.screen, GRASS_DARK, False, pts_top, 6)
            pts_above = [(x, y - 4) for x, y in pts_top]
            pygame.draw.lines(self.screen, GRASS_LIGHT, False, pts_above, 3)

    def _draw_car(self, rs: dict) -> None:
        # Chassis polygons (already in world pixel coords)
        for poly in rs.get("chassis_polys", ()):
            screen_pts = [self.w2s(x, y) for x, y in poly]
            if len(screen_pts) >= 3:
                pygame.draw.polygon(self.screen, CHASSIS_COLOR, screen_pts)
                pygame.draw.polygon(self.screen, CHASSIS_OUTLINE, screen_pts, 2)

        # Wheels: circle + half-radius rim + a single rotation spoke
        for w in rs.get("wheels", ()):
            sx, sy = self.w2s(w["x_px"], w["y_px"])
            r = max(1, int(w["radius_px"]))
            pygame.draw.circle(self.screen, WHEEL_COLOR, (sx, sy), r)
            pygame.draw.circle(self.screen, RIM_COLOR, (sx, sy), max(1, r // 2))
            angle = w["angle"]
            ex = sx + int(math.cos(angle) * r)
            ey = sy + int(math.sin(angle) * r)
            pygame.draw.line(self.screen, RIM_COLOR, (sx, sy), (ex, ey), 2)

        # Torso (rotated rect)
        t = rs.get("torso")
        if t is not None:
            corners = _rotate_rect_corners(
                t["x_px"], t["y_px"], t["width_px"], t["height_px"], t["angle"]
            )
            screen_pts = [self.w2s(x, y) for x, y in corners]
            pygame.draw.polygon(self.screen, TORSO_COLOR, screen_pts)
            pygame.draw.polygon(self.screen, (0, 0, 0), screen_pts, 1)

        # Head (circle)
        h = rs.get("head")
        if h is not None:
            sx, sy = self.w2s(h["x_px"], h["y_px"])
            r = max(1, int(h["radius_px"]))
            pygame.draw.circle(self.screen, HEAD_COLOR, (sx, sy), r)
            pygame.draw.circle(self.screen, (0, 0, 0), (sx, sy), r, 1)

    def _draw_hud(self, score: int, sim_speed: int, on_ground: bool,
                  *, debug_lines: Iterable[str] = ()) -> None:
        lines = [
            f"Score: {score}",
            f"Sim:   {sim_speed}x",
            f"Ground: {'YES' if on_ground else 'AIR'}",
            "",
            "Arrow keys: drive   R: reset   ESC: quit",
            *debug_lines,
        ]
        y = 20
        for ln in lines:
            surf = self.font.render(ln, True, TEXT_COLOR)
            self.screen.blit(surf, (20, y))
            y += 22

    # ----------------------------------------------------------------
    def close(self) -> None:
        pygame.quit()
