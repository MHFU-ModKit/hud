"""In-quest HUD layout.

A location resource-map fills the centre; loaded entities are projected onto
it. The player is pinned to the map centre (player_centered calibration);
monsters are drawn relative. TAB / [ ] cycle the selected monster, ENTER
opens its detail page. C enters calibration mode (scale / rotate / save).
"""

import math

import pygame

from .. import panels, widgets as W
from ..theme import C, CANVAS_W, CANVAS_H
from .base import Layout

# --- layout rectangles on the 960x544 virtual canvas -----------------------
R_VITALS  = pygame.Rect(12, 12, 300, 86)
R_TIMER   = pygame.Rect(748, 12, 200, 86)
R_ROSTER  = pygame.Rect(12, 110, 200, 278)
R_SHARP   = pygame.Rect(12, 396, 200, 78)
R_MAP     = pygame.Rect(224, 110, 510, 364)
R_DETAIL  = pygame.Rect(746, 110, 202, 364)
R_RAW     = pygame.Rect(12, 484, 936, 48)

MARKER_PX = 40


class QuestLayout(Layout):
    name = "quest"

    def __init__(self, assets, calib):
        super().__init__(assets, calib)
        self.selected = 0
        self.detail_open = False
        self.calib_mode = False
        self.map_slug = "snowy_mountains"
        self._maps = self.assets.map_slugs() or ["snowy_mountains"]
        if self.map_slug not in self._maps:
            self._maps.insert(0, self.map_slug)
        self._marker_hits = []   # [(rect, monster_index)] for click hit-test

    # --- input -------------------------------------------------------------

    def handle_key(self, key, snapshot) -> bool:
        n = len(snapshot.monsters)
        if key in (pygame.K_TAB, pygame.K_RIGHTBRACKET):
            if n:
                self.selected = (self.selected + 1) % n
            return True
        if key == pygame.K_LEFTBRACKET:
            if n:
                self.selected = (self.selected - 1) % n
            return True
        if key == pygame.K_RETURN:
            self.detail_open = not self.detail_open
            return True
        if key == pygame.K_c:
            self.calib_mode = not self.calib_mode
            return True
        if key == pygame.K_m:
            i = self._maps.index(self.map_slug) if self.map_slug in self._maps else -1
            self.map_slug = self._maps[(i + 1) % len(self._maps)]
            return True
        if self.calib_mode:
            return self._calib_key(key)
        return False

    def _calib_key(self, key) -> bool:
        q = self.calib.quest
        if key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            q["scale"] *= 1.1
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            q["scale"] /= 1.1
        elif key == pygame.K_COMMA:
            q["rot_deg"] -= 5
        elif key == pygame.K_PERIOD:
            q["rot_deg"] += 5
        elif key == pygame.K_t:
            q["mode"] = ("fixed" if q["mode"] == "player_centered"
                         else "player_centered")
        elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            d = {pygame.K_LEFT: (-50, 0), pygame.K_RIGHT: (50, 0),
                 pygame.K_UP: (0, -50), pygame.K_DOWN: (0, 50)}[key]
            q["origin_x"] += d[0]
            q["origin_z"] += d[1]
        elif key == pygame.K_s:
            self.calib.save()
        else:
            return False
        return True

    def handle_click(self, pos, snapshot) -> bool:
        for rect, idx in self._marker_hits:
            if rect.collidepoint(pos):
                self.selected = idx
                return True
        # roster rows
        if R_ROSTER.collidepoint(pos):
            row_h = 42
            idx = (pos[1] - (R_ROSTER.y + 26)) // row_h
            if 0 <= idx < len(snapshot.monsters):
                self.selected = int(idx)
                return True
        return False

    # --- render ------------------------------------------------------------

    def render(self, surface, snapshot):
        surface.fill(C.BG_QUEST)
        monsters = snapshot.monsters
        if monsters:
            self.selected %= len(monsters)
        else:
            self.selected = 0

        panels.draw_vitals(surface, R_VITALS, snapshot.player)
        self._timer_panel(surface, snapshot)
        self._map_panel(surface, snapshot)
        self._roster_panel(surface, snapshot)
        self._sharpness_panel(surface)
        self._detail_panel(surface, snapshot)
        panels.draw_raw_strip(surface, R_RAW, snapshot)

        if self.detail_open and monsters:
            self._detail_overlay(surface, monsters[self.selected],
                                 snapshot.player)
        if self.calib_mode:
            self._calib_hint(surface)

    # --- panels ------------------------------------------------------------

    def _timer_panel(self, surface, snapshot):
        W.panel(surface, R_TIMER, title="QUEST TIME")
        frames = snapshot.quest_timer_frames
        running = 0 < frames < 60 * 60 * 100
        W.text(surface, panels.fmt_timer(frames) if running else "--:--",
               (R_TIMER.centerx, R_TIMER.y + 28), size=34,
               color=C.TEXT if running else C.PLACEHOLDER, bold=True,
               align="center")
        W.text(surface, f"{frames} frames", (R_TIMER.centerx, R_TIMER.y + 66),
               size=11, color=C.TEXT_FAINT, align="center")

    def _sharpness_panel(self, surface):
        W.panel(surface, R_SHARP, title="SHARPNESS")
        W.placeholder_box(surface, (R_SHARP.x + 12, R_SHARP.y + 30,
                                    R_SHARP.w - 24, 18), "")
        W.text(surface, "not parsed yet", (R_SHARP.centerx, R_SHARP.y + 52),
               size=11, color=C.PLACEHOLDER, align="center")

    def _map_panel(self, surface, snapshot):
        W.panel(surface, R_MAP, fill=C.BG)
        W.text(surface, f"MAP — {self.map_slug.replace('_', ' ').title()}",
               (R_MAP.x + 10, R_MAP.y + 6), size=12, color=C.ACCENT, bold=True)
        q = self.calib.quest
        W.text(surface, f"{q['mode']}  x{q['scale']:.3f}  {q['rot_deg']:.0f}°",
               (R_MAP.right - 10, R_MAP.y + 6), size=11, color=C.TEXT_FAINT,
               align="right")

        img_box = pygame.Rect(R_MAP.x + 6, R_MAP.y + 24,
                              R_MAP.w - 12, R_MAP.h - 30)
        img = self.assets.map_image(self.map_slug)
        if img:
            scale = W.fit_scale(img.get_size(), img_box.size)
            scaled = self.assets.scaled(
                img, (img.get_width() * scale, img.get_height() * scale))
            surface.blit(scaled, scaled.get_rect(center=img_box.center))
        else:
            W.placeholder_box(surface, img_box,
                              f"map image missing — run fetch_assets.py")

        self._draw_entities(surface, img_box, snapshot)

    def _draw_entities(self, surface, box, snapshot):
        self._marker_hits = []
        prev_clip = surface.get_clip()
        surface.set_clip(box)
        player = snapshot.player
        px, pz = player.pos_world.x, player.pos_world.z

        # monsters
        for idx, m in enumerate(snapshot.monsters):
            mx, my = self.calib.world_to_map(box, m.pos.x, m.pos.z, px, pz)
            mx = max(box.left + 6, min(box.right - 6, mx))
            my = max(box.top + 6, min(box.bottom - 6, my))
            sel = (idx == self.selected)
            self._blit_monster(surface, m, (mx, my), sel)
            self._marker_hits.append(
                (pygame.Rect(mx - 22, my - 22, 44, 44), idx))

        # player at centre / projected
        ppx, ppy = self.calib.world_to_map(box, px, player.pos_world.z,
                                           px, pz)
        W.marker(surface, (ppx, ppy), player.facing_rad, C.PLAYER, radius=11)

        surface.set_clip(prev_clip)
        if not snapshot.monsters:
            W.text(surface, "no monsters loaded", box.center, size=14,
                   color=C.TEXT_FAINT, align="center")

    def _blit_monster(self, surface, m, center, selected):
        cx, cy = int(center[0]), int(center[1])
        ring = C.SELECT if selected else C.MONSTER
        pygame.draw.circle(surface, (0, 0, 0, 120), (cx, cy), 21)
        pygame.draw.circle(surface, ring, (cx, cy), 21, width=2)
        icon = self.assets.monster_icon(m.icon_slug)
        if icon:
            scaled = self.assets.scaled(icon, (MARKER_PX, MARKER_PX))
            surface.blit(scaled, scaled.get_rect(center=(cx, cy)))
        else:
            pygame.draw.circle(surface, C.MONSTER_DIM, (cx, cy), 17)
            W.text(surface, m.name[:1], (cx, cy - 8), size=18,
                   color=C.TEXT, bold=True, align="center")
        if selected:
            W.text(surface, m.name, (cx, cy - 34), size=12, color=C.SELECT,
                   bold=True, align="center")

    def _roster_panel(self, surface, snapshot):
        W.panel(surface, R_ROSTER, title="MONSTERS")
        monsters = snapshot.monsters
        if not monsters:
            W.text(surface, "none loaded", (R_ROSTER.x + 12, R_ROSTER.y + 34),
                   size=13, color=C.TEXT_FAINT)
            return
        row_h = 42
        for i, m in enumerate(monsters):
            ry = R_ROSTER.y + 26 + i * row_h
            if ry + row_h > R_ROSTER.bottom:
                break
            row = pygame.Rect(R_ROSTER.x + 6, ry, R_ROSTER.w - 12, row_h - 4)
            if i == self.selected:
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=4)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=4)
            icon = self.assets.monster_icon(m.icon_slug)
            if icon:
                surface.blit(self.assets.scaled(icon, (30, 30)),
                             (row.x + 4, row.y + 4))
            W.text(surface, m.name, (row.x + 40, row.y + 4), size=13,
                   color=C.TEXT, bold=True)
            W.text(surface, f"slot {m.slot}", (row.x + 40, row.y + 21),
                   size=10, color=C.TEXT_FAINT)
            hp_max = max(1, m.hp_max)
            W.bar(surface, (row.x + 96, row.y + 22, row.w - 104, 8),
                  m.hp / hp_max, C.MONSTER)
            W.text(surface, str(m.hp), (row.right - 6, row.y + 4), size=12,
                   color=C.TEXT, align="right")

    def _detail_panel(self, surface, snapshot):
        W.panel(surface, R_DETAIL, title="DETAIL")
        monsters = snapshot.monsters
        if not monsters:
            W.text(surface, "select a monster", (R_DETAIL.x + 12,
                   R_DETAIL.y + 34), size=12, color=C.TEXT_FAINT)
            W.text(surface, "TAB / [ ] to cycle", (R_DETAIL.x + 12,
                   R_DETAIL.y + 52), size=11, color=C.TEXT_FAINT)
            return
        m = monsters[self.selected]
        x = R_DETAIL.x + 12
        icon = self.assets.monster_icon(m.icon_slug)
        if icon:
            surface.blit(self.assets.scaled(icon, (64, 64)),
                         (R_DETAIL.centerx - 32, R_DETAIL.y + 28))
        else:
            W.placeholder_box(surface, (R_DETAIL.centerx - 32, R_DETAIL.y + 28,
                                        64, 64), "no icon")
        W.text(surface, m.name, (R_DETAIL.centerx, R_DETAIL.y + 96), size=16,
               color=C.SELECT, bold=True, align="center")

        hp_max = max(1, m.hp_max)
        W.bar(surface, (x, R_DETAIL.y + 122, R_DETAIL.w - 24, 14),
              m.hp / hp_max, C.MONSTER)
        W.text(surface, f"HP {m.hp}", (R_DETAIL.centerx, R_DETAIL.y + 124),
               size=11, color=C.TEXT, bold=True, align="center")

        dist = self._distance(m, snapshot.player)
        rows = [
            ("Slot", m.slot),
            ("Pointer", f"0x{m.ptr:08X}"),
            ("Type byte", f"0x{m.type_byte:02X}"),
            ("Entity ID", f"0x{m.entity_id:02X}"),
            ("AI behavior", m.ai_behavior),
            ("AI 0x324", m.ai_324),
            ("AI 0x32C", m.ai_32c),
            ("World X", f"{m.pos.x:.0f}"),
            ("World Y", f"{m.pos.y:.0f}"),
            ("World Z", f"{m.pos.z:.0f}"),
            ("Dist", "—" if dist is None else f"{dist:.0f}"),
        ]
        W.kv_rows(surface, (x, R_DETAIL.y + 148), rows, size=12, line_h=18,
                  key_w=92)
        W.text(surface, "ENTER: full detail page", (R_DETAIL.centerx,
               R_DETAIL.bottom - 22), size=10, color=C.TEXT_FAINT,
               align="center")

    # --- overlays ----------------------------------------------------------

    def _detail_overlay(self, surface, m, player):
        self.dim(surface, pygame.Rect(0, 0, CANVAS_W, CANVAS_H), 170)
        box = pygame.Rect(CANVAS_W // 2 - 280, CANVAS_H // 2 - 200, 560, 400)
        W.panel(surface, box, fill=C.PANEL_HI, border=C.SELECT)
        W.text(surface, f"{m.name}  —  MONSTER DETAIL", (box.x + 20, box.y + 14),
               size=18, color=C.SELECT, bold=True)

        icon = self.assets.monster_icon(m.icon_slug)
        if icon:
            surface.blit(self.assets.scaled(icon, (140, 140)),
                         (box.x + 24, box.y + 50))
        else:
            W.placeholder_box(surface, (box.x + 24, box.y + 50, 140, 140),
                              "no icon")

        hp_max = max(1, m.hp_max)
        W.bar(surface, (box.x + 24, box.y + 204, 140, 16), m.hp / hp_max,
              C.MONSTER)
        W.text(surface, f"HP  {m.hp} / {hp_max}", (box.x + 24, box.y + 226),
               size=12, color=C.TEXT)

        dist = self._distance(m, player)
        rows = [
            ("Display name", m.name),
            ("Registry slot", m.slot),
            ("Entity pointer", f"0x{m.ptr:08X}"),
            ("Type byte (+0x1E8)", f"0x{m.type_byte:02X}  (unreliable)"),
            ("Entity ID (+0x1E4)", f"0x{m.entity_id:02X}"),
            ("AI behavior (+0x334)", m.ai_behavior),
            ("AI param (+0x324)", m.ai_324),
            ("AI param (+0x32C)", m.ai_32c),
            ("World position", f"{m.pos.x:.1f}, {m.pos.y:.1f}, {m.pos.z:.1f}"),
            ("Distance to player", "—" if dist is None else f"{dist:.0f} units"),
        ]
        W.kv_rows(surface, (box.x + 190, box.y + 56), rows, size=13,
                  line_h=24, key_w=180)
        W.text(surface, "placeholder fields appear once their offsets are "
               "reverse-engineered", (box.x + 20, box.bottom - 44), size=11,
               color=C.TEXT_FAINT)
        W.text(surface, "ENTER / ESC: close", (box.right - 20, box.bottom - 24),
               size=11, color=C.TEXT_DIM, align="right")

    def _calib_hint(self, surface):
        box = pygame.Rect(CANVAS_W // 2 - 300, CANVAS_H - 96, 600, 56)
        W.panel(surface, box, fill=C.PANEL_HI, border=C.ACCENT)
        W.text(surface, "MAP CALIBRATION", (box.x + 16, box.y + 8), size=12,
               color=C.ACCENT, bold=True)
        W.text(surface, "+/-: scale   , .: rotate   T: mode   "
               "arrows: origin (fixed)   S: save   C: exit",
               (box.x + 16, box.y + 28), size=12, color=C.TEXT)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _distance(m, player):
        if not player.loaded:
            return None
        dx = m.pos.x - player.pos_world.x
        dz = m.pos.z - player.pos_world.z
        return math.hypot(dx, dz)
