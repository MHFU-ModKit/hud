"""Village HUD layout.

A village background image with the hunter's position/heading drawn on top,
plus the vitals panel and raw readouts. World->background mapping is not
known, so the marker uses a configurable normalised position (calibration
mode: arrows move it, [ ] rotate the heading offset, S saves).
"""

import math

import pygame

from .. import panels, widgets as W
from ..theme import C, CANVAS_W, CANVAS_H
from .base import Layout


class VillageLayout(Layout):
    name = "village"

    def __init__(self, assets, calib):
        super().__init__(assets, calib)
        self.calib_mode = False

    def handle_key(self, key, snapshot) -> bool:
        v = self.calib.village
        if key == pygame.K_c:
            self.calib_mode = not self.calib_mode
            return True
        if not self.calib_mode:
            return False
        step = 0.01
        if key == pygame.K_LEFT:
            v["nx"] = max(0.0, v["nx"] - step)
        elif key == pygame.K_RIGHT:
            v["nx"] = min(1.0, v["nx"] + step)
        elif key == pygame.K_UP:
            v["ny"] = max(0.0, v["ny"] - step)
        elif key == pygame.K_DOWN:
            v["ny"] = min(1.0, v["ny"] + step)
        elif key == pygame.K_LEFTBRACKET:
            v["facing_offset_deg"] -= 5
        elif key == pygame.K_RIGHTBRACKET:
            v["facing_offset_deg"] += 5
        elif key == pygame.K_s:
            self.calib.save()
        else:
            return False
        return True

    def render(self, surface, snapshot):
        full = pygame.Rect(0, 0, CANVAS_W, CANVAS_H)
        self.blit_cover(surface, self.assets.background("village"), full)
        self.dim(surface, full, 96)

        W.text(surface, "POKKE VILLAGE", (16, 8), size=14, color=C.ACCENT,
               bold=True)

        self._marker(surface, snapshot.player)
        panels.draw_vitals(surface, (12, 28, 300, 86), snapshot.player)
        self._time_panel(surface, (748, 28, 200, 86))
        self._info_panel(surface, (12, 392, 320, 140), snapshot)
        panels.draw_raw_strip(surface, (344, 476, 604, 56), snapshot)

        if self.calib_mode:
            self._calib_hint(surface)

    # --- pieces ------------------------------------------------------------

    def _marker(self, surface, player):
        v = self.calib.village
        cx = v["nx"] * CANVAS_W
        cy = v["ny"] * CANVAS_H
        heading = None
        if player.facing_rad is not None:
            heading = player.facing_rad + math.radians(v["facing_offset_deg"])
        # soft glow under the marker
        glow = pygame.Surface((60, 60), pygame.SRCALPHA)
        pygame.draw.circle(glow, (96, 184, 236, 70), (30, 30), 26)
        surface.blit(glow, (cx - 30, cy - 30))
        W.marker(surface, (cx, cy), heading, C.PLAYER, radius=12)
        W.text(surface, "YOU", (cx, cy + 18), size=11, color=C.PLAYER,
               bold=True, align="center")

    def _time_panel(self, surface, rect):
        W.panel(surface, rect, title="TIME")
        W.placeholder_box(surface, (rect[0] + 12, rect[1] + 30,
                                    rect[2] - 24, 44), "no quest clock here")

    def _info_panel(self, surface, rect, snapshot):
        W.panel(surface, rect, title="HUNTER")
        p = snapshot.player
        wp, lp = p.pos_world, p.pos_local
        facing = ("—" if p.facing_rad is None
                  else f"{math.degrees(p.facing_rad):.0f}° (approx)")
        weapon = ("—" if p.weapon_drawn is None
                  else ("drawn" if p.weapon_drawn else "sheathed"))
        rows = [
            ("World X/Z", f"{wp.x:.0f}, {wp.z:.0f}"),
            ("World Y", f"{wp.y:.0f}"),
            ("Local pos", f"{lp.x:.0f}, {lp.y:.0f}, {lp.z:.0f}"),
            ("Facing", facing),
            ("Weapon", weapon),
            ("Map section", snapshot.map_section),
        ]
        W.kv_rows(surface, (rect[0] + 12, rect[1] + 28), rows, size=13,
                  line_h=18, key_w=110)

    def _calib_hint(self, surface):
        box = pygame.Rect(CANVAS_W // 2 - 230, CANVAS_H - 70, 460, 40)
        W.panel(surface, box, fill=C.PANEL_HI, border=C.ACCENT)
        W.text(surface, "CALIBRATION — arrows: move marker   [ ]: heading   "
               "S: save   C: exit", box.move(0, 0).inflate(-20, -16).topleft,
               size=12, color=C.ACCENT)
