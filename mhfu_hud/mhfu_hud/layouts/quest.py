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
R_PLAYER  = pygame.Rect(318, 12, 424, 86)
R_TIMER   = pygame.Rect(748, 12, 200, 86)
R_ROSTER  = pygame.Rect(12, 110, 200, 278)
R_SHARP   = pygame.Rect(12, 396, 200, 78)
R_MAP     = pygame.Rect(224, 110, 510, 364)
R_DETAIL  = pygame.Rect(746, 110, 202, 222)
R_BAG     = pygame.Rect(746, 338, 202, 136)
R_RAW     = pygame.Rect(12, 484, 936, 48)

# Icon sizes — halved from the original 40 px to keep the markers from
# swamping smaller map sections at typical HUD scale.
MARKER_PX = 20
MARKER_RING_R = 12
PLAYER_MARKER_R = 9


class QuestLayout(Layout):
    name = "quest"

    DETAIL_SUBTABS = ("stats", "ai_diag")

    def __init__(self, assets, calib, reader=None):
        super().__init__(assets, calib)
        self.reader = reader        # may be None in smoke tests
        self.selected = 0
        self.detail_open = False
        # When the detail overlay is open, TAB cycles its sub-page rather
        # than the top-level app tabs. "stats" shows the legacy kv-rows
        # readout; "ai_diag" shows the read-only AI panel from
        # docs/POPO_AI_STRUCTURE.md §19f.4.
        self.detail_subtab = "stats"
        self.calib_mode = False
        # Bag visibility: default ON; press B to toggle. When hidden,
        # DETAIL expands into the bag rect so the full monster info is
        # visible (previously the bag was clipping detail rows past
        # "Entity ID"). User-driven from Section 15 layout fix.
        self.bag_visible = True
        self.map_slug = "snowy_mountains"
        self._maps = self.assets.map_slugs() or ["snowy_mountains"]
        if self.map_slug not in self._maps:
            self._maps.insert(0, self.map_slug)
        self._marker_hits = []   # [(rect, monster_index)] for click hit-test
        # blit metadata for the current map image, populated by _map_panel
        # so _draw_entities can map native-image pixels back to screen pixels.
        self._map_blit = None    # (rect, scale)  rect is on-screen, scale = px/native

    # --- input -------------------------------------------------------------

    def handle_key(self, key, snapshot) -> bool:
        n = len(snapshot.monsters)
        # TAB sub-page cycling only kicks in WHILE the monster detail
        # overlay is open. Otherwise TAB falls through to the app and
        # cycles top-level tabs (LIVE / QUEST_PREP / AI_MOD).
        if key == pygame.K_TAB and self.detail_open:
            i = self.DETAIL_SUBTABS.index(self.detail_subtab)
            self.detail_subtab = self.DETAIL_SUBTABS[
                (i + 1) % len(self.DETAIL_SUBTABS)]
            return True
        if key == pygame.K_RIGHTBRACKET:
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
        if key == pygame.K_b:
            # Toggle bag visibility — when hidden, the DETAIL panel
            # expands into the freed rect so all monster fields show.
            self.bag_visible = not self.bag_visible
            return True
        if key == pygame.K_c:
            self.calib_mode = not self.calib_mode
            return True
        if key == pygame.K_m:
            i = self._maps.index(self.map_slug) if self.map_slug in self._maps else -1
            self.map_slug = self._maps[(i + 1) % len(self._maps)]
            return True
        # Calibration shortcuts get priority — many of them (= / - / , / .)
        # would otherwise be eaten by the monster-edit keys below.
        if self.calib_mode:
            return self._calib_key(key)
        # --- live monster editor — Section 15.7 stopgap --------------
        # Spawn-time editing (modify spawn before quest) is gated on
        # the pre-quest spawn-list discovery; that hit a hard limit.
        # Meanwhile the per-entity scale + type byte ARE writable on a
        # live monster (verified via PPSSPP write_memory). These keys
        # apply to the SELECTED monster (cycle with [ ]).
        if n and 0 <= self.selected < n and self.reader is not None \
                and self.reader._client is not None:
            m = snapshot.monsters[self.selected]
            if self._edit_key(key, m):
                return True
        return False

    # Per-entity write helpers — only invoked from explicit key edits
    # in the QUEST tab. Bumps scale +0x024 (f32) and type byte +0x1E8
    # (u8) on the selected monster. Each press is one write; no
    # accidental drift.
    SIZE_STEP_FINE = 0.05
    SIZE_STEP_COARSE = 0.2
    SIZE_MIN = 0.1
    SIZE_MAX = 5.0

    def _edit_key(self, key, m) -> bool:
        from .. import addresses as A
        from ..edits import _write_size
        c = self.reader._client
        if key == pygame.K_EQUALS or key == pygame.K_PLUS \
                or key == pygame.K_KP_PLUS:
            new = (m.size_scale or 1.0) + self.SIZE_STEP_FINE
            new = min(self.SIZE_MAX, new)
            try:
                _write_size(c, m.ptr, new, A)
            except Exception:
                pass
            return True
        if key == pygame.K_MINUS or key == pygame.K_KP_MINUS:
            new = max(self.SIZE_MIN,
                      (m.size_scale or 1.0) - self.SIZE_STEP_FINE)
            try:
                _write_size(c, m.ptr, new, A)
            except Exception:
                pass
            return True
        # Coarse +/- with shift held — pygame.key.get_mods checks
        # the modifier state at the moment of the press.
        if key == pygame.K_GREATER or key == pygame.K_PERIOD:
            new = min(self.SIZE_MAX,
                      (m.size_scale or 1.0) + self.SIZE_STEP_COARSE)
            try:
                _write_size(c, m.ptr, new, A)
            except Exception:
                pass
            return True
        if key == pygame.K_LESS or key == pygame.K_COMMA:
            new = max(self.SIZE_MIN,
                      (m.size_scale or 1.0) - self.SIZE_STEP_COARSE)
            try:
                _write_size(c, m.ptr, new, A)
            except Exception:
                pass
            return True
        # Type-byte cycle: PgDown / PgUp ± 1 to the +0x1E8 byte. The
        # byte controls *what species* the engine renders/animates,
        # though changing it on a live entity can leave a stale
        # vtable + animation set — useful for visual experiments, not
        # for stable swaps.
        if key == pygame.K_PAGEUP:
            new = (m.type_byte + 1) & 0xFF
            try:
                c.write_u8(m.ptr + A.OFF_M_TYPE, new)
            except Exception:
                pass
            return True
        if key == pygame.K_PAGEDOWN:
            new = (m.type_byte - 1) & 0xFF
            try:
                c.write_u8(m.ptr + A.OFF_M_TYPE, new)
            except Exception:
                pass
            return True
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
        # Player-marker heading tuning — works in TPS mode too.
        elif key == pygame.K_h:
            q["facing_offset_deg"] = (float(q.get("facing_offset_deg",
                                                  0.0)) - 5.0)
        elif key == pygame.K_j:
            q["facing_offset_deg"] = (float(q.get("facing_offset_deg",
                                                  0.0)) + 5.0)
        elif key == pygame.K_f:
            q["facing_flip"] = not bool(q.get("facing_flip", False))
        elif key == pygame.K_s:
            self.calib.save()
        # Manual section override: 1-8 set, 0 clears + re-snaps next gate.
        elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                     pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8):
            if self.reader is not None:
                self.reader.set_section_override(int(pygame.key.name(key)))
        elif key == pygame.K_0:
            if self.reader is not None:
                self.reader.reset_section_tracking()
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
        self._player_panel(surface, snapshot)
        self._timer_panel(surface, snapshot)
        self._map_panel(surface, snapshot)
        self._roster_panel(surface, snapshot)
        self._sharpness_panel(surface, snapshot)
        # Pick the detail rect on the fly: when bag is hidden, detail
        # eats the bag's rect too. _detail_panel + _bag_panel read this
        # via self._detail_rect / self._bag_rect.
        if self.bag_visible:
            self._detail_rect = R_DETAIL
            self._bag_rect = R_BAG
        else:
            self._detail_rect = pygame.Rect(
                R_DETAIL.x, R_DETAIL.y,
                R_DETAIL.w, R_BAG.bottom - R_DETAIL.y)
            self._bag_rect = None
        self._detail_panel(surface, snapshot)
        if self.bag_visible:
            self._bag_panel(surface, snapshot)
        panels.draw_raw_strip(surface, R_RAW, snapshot)

        if self.detail_open and monsters:
            self._detail_overlay(surface, monsters[self.selected],
                                 snapshot.player)
        if self.calib_mode:
            self._calib_hint(surface)

    # --- panels ------------------------------------------------------------

    def _player_panel(self, surface, snapshot):
        """World coords + facing for the player — used to calibrate map
        anchors against in-game positions."""
        W.panel(surface, R_PLAYER, title="PLAYER")
        p = snapshot.player
        loaded = p.loaded and p.pos_world is not None
        x = R_PLAYER.x + 12
        y0 = R_PLAYER.y + 26
        col = R_PLAYER.x + 156
        col2 = R_PLAYER.x + 296
        if not loaded:
            W.text(surface, "not loaded", (x, y0 + 14), size=13,
                   color=C.PLACEHOLDER)
            return
        wp = p.pos_world
        # Heading: facing_rad is best-effort from the rotation matrix; 0 rad
        # points along +Z by our convention. Show degrees as a compass
        # bearing (0 = N, 90 = E, ...) for ease of reading.
        if p.facing_rad is not None:
            deg = (math.degrees(p.facing_rad) + 360.0) % 360.0
            heading_str = f"{deg:5.1f}°"
        else:
            heading_str = "  —"
        W.stat_block(surface, (x, y0), "WORLD X", f"{wp.x:.0f}",
                     size_value=20)
        W.stat_block(surface, (col, y0), "WORLD Z", f"{wp.z:.0f}",
                     size_value=20)
        W.stat_block(surface, (col2, y0), "WORLD Y", f"{wp.y:.0f}",
                     size_value=20)
        # Row 2 underneath: heading + map section, for calibration context.
        sub_y = y0 + 44
        W.text(surface, "HEADING", (x, sub_y), size=10,
               color=C.TEXT_DIM, bold=True)
        W.text(surface, heading_str, (x + 60, sub_y - 1), size=13,
               color=C.TEXT, bold=True)
        W.text(surface, "MAP SEC", (col, sub_y), size=10,
               color=C.TEXT_DIM, bold=True)
        # Tracked section is updated only on gate transitions, so it
        # stays steady while the hunter walks inside one section. The
        # raw byte at 0x08A8DE4C is shown muted alongside — it's a
        # sub-section ID with cross-section collisions (see
        # tools/discover_map_section_v2.py / 2026-05-23).
        sec = snapshot.tracked_section
        sec_s = "?" if sec is None else str(sec)
        W.text(surface, sec_s, (col + 60, sub_y - 1), size=13,
               color=C.TEXT, bold=True)
        W.text(surface,
               f"({snapshot.tracked_section_source}, "
               f"idx {snapshot.area_index}, sub {snapshot.map_section})",
               (col + 80, sub_y - 1), size=11, color=C.TEXT_FAINT,
               bold=False)

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

    # Sharpness-tier colors. Indexed by addresses.SHARPNESS_TIER (0..6).
    # MH tier order: red < orange < yellow < green < blue < white < purple.
    _SHARP_TIER_COLOR = (
        (220,  64,  56),    # red
        (228, 132,  44),    # orange
        (232, 200,  72),    # yellow
        (108, 196,  92),    # green
        ( 86, 156, 232),    # blue
        (228, 232, 240),    # white
        (188, 116, 220),    # purple
    )

    def _sharpness_panel(self, surface, snapshot):
        W.panel(surface, R_SHARP, title="SHARPNESS")
        p = snapshot.player
        cur, mx, tier = p.sharpness, p.sharpness_max, p.sharpness_tier
        bar_rect = (R_SHARP.x + 12, R_SHARP.y + 32, R_SHARP.w - 24, 18)
        if cur is None or mx is None or mx <= 0:
            W.placeholder_box(surface, bar_rect, "")
            label = ("not loaded" if not p.loaded else
                     "no live read")
            W.text(surface, label,
                   (R_SHARP.centerx, R_SHARP.y + 56),
                   size=11, color=C.PLACEHOLDER, align="center")
            return
        # Bar — coloured by tier; segments above the current tier are
        # rendered as muted fill so you can see headroom even if you've
        # used a tier of sharpness. Simpler "single-colour current bar
        # over a dark back" works fine without a per-tier breakdown.
        frac = cur / mx
        idx = tier if tier is not None and 0 <= tier < 7 else 2
        color = self._SHARP_TIER_COLOR[idx]
        W.bar(surface, bar_rect, frac, color)
        # Tier name + numeric. Tier could be None during a transient
        # zone-load — fall back to "?" rather than crash.
        from .. import addresses as A
        tier_name = (A.SHARPNESS_TIER_NAMES[tier]
                     if tier is not None and 0 <= tier < 7 else "?")
        W.text(surface, tier_name,
               (R_SHARP.x + 14, R_SHARP.y + 54),
               size=14, color=color, bold=True)
        W.text(surface, f"{cur} / {mx}",
               (R_SHARP.right - 14, R_SHARP.y + 54),
               size=14, color=C.TEXT, bold=True, align="right")

    def _map_panel(self, surface, snapshot):
        W.panel(surface, R_MAP, fill=C.BG)
        W.text(surface, f"MAP — {self.map_slug.replace('_', ' ').title()}",
               (R_MAP.x + 10, R_MAP.y + 6), size=12, color=C.ACCENT, bold=True)

        # Status line — gate-tracked section + projection mode.
        sec = snapshot.tracked_section
        src = snapshot.tracked_section_source
        if sec is not None:
            n = len(self.calib._section_anchors(self.map_slug, sec))
            mode = ("affine" if n >= 3 else
                    "2-anchor" if n == 2 else
                    "1-anchor" if n == 1 else
                    "no anchors")
            status = f"sec {sec} ({src})  {mode}"
        else:
            q = self.calib.quest
            status = f"sec ?  ({q['mode']}  x{q['scale']:.3f})"
        W.text(surface, status, (R_MAP.right - 10, R_MAP.y + 6), size=11,
               color=C.TEXT_FAINT, align="right")

        img_box = pygame.Rect(R_MAP.x + 6, R_MAP.y + 24,
                              R_MAP.w - 12, R_MAP.h - 30)
        img = self.assets.map_image(self.map_slug)
        self._map_blit = None
        if img:
            scale = W.fit_scale(img.get_size(), img_box.size)
            scaled = self.assets.scaled(
                img, (img.get_width() * scale, img.get_height() * scale))
            blit_rect = scaled.get_rect(center=img_box.center)
            surface.blit(scaled, blit_rect)
            self._map_blit = (blit_rect, scale)
        else:
            W.placeholder_box(surface, img_box,
                              f"map image missing — run fetch_assets.py")

        self._draw_entities(surface, img_box, snapshot)

    def _native_to_screen(self, img_x, img_y):
        """Native-image pixel -> on-screen pixel using the current blit."""
        if not self._map_blit:
            return None
        rect, scale = self._map_blit
        return rect.left + img_x * scale, rect.top + img_y * scale

    def _project(self, box, world_x, world_z, player_x, player_z,
                 section=None):
        """On-screen pixel for a world (x, z). When a tracked section is
        known we project through that section's local anchors only —
        world coords are NOT globally comparable across sections, so the
        old slug-wide TPS gave wrong answers when the hunter walked
        deep into one section. Falls back to player_centered if no
        section is known and no anchors apply."""
        if self._map_blit and section is not None:
            img_xy = self.calib.world_to_image_section(
                self.map_slug, section, world_x, world_z)
            if img_xy is not None:
                return self._native_to_screen(*img_xy)
        return self.calib.world_to_map(box, world_x, world_z,
                                       player_x, player_z)

    def _draw_entities(self, surface, box, snapshot):
        self._marker_hits = []
        prev_clip = surface.get_clip()
        surface.set_clip(box)
        player = snapshot.player
        px, pz = player.pos_world.x, player.pos_world.z
        section = snapshot.tracked_section

        # monsters — drawn at their absolute world position within the
        # current section's local coord frame. They only move on the HUD
        # when the monster moves in-game, not when the player turns.
        hit_r = MARKER_RING_R + 6
        for idx, m in enumerate(snapshot.monsters):
            mx, my = self._project(box, m.pos.x, m.pos.z, px, pz,
                                   section=section)
            mx = max(box.left + 4, min(box.right - 4, mx))
            my = max(box.top + 4, min(box.bottom - 4, my))
            sel = (idx == self.selected)
            self._blit_monster(surface, m, (mx, my), sel)
            self._marker_hits.append(
                (pygame.Rect(mx - hit_r, my - hit_r, 2 * hit_r, 2 * hit_r),
                 idx))

        # player marker — pinned to the player's *world* position, oriented
        # to the player character's heading (not the camera yaw).
        ppx, ppy = self._project(box, px, pz, px, pz, section=section)
        ppx = max(box.left + 4, min(box.right - 4, ppx))
        ppy = max(box.top + 4, min(box.bottom - 4, ppy))
        heading = self._player_heading(player)
        W.marker(surface, (ppx, ppy), heading, C.PLAYER,
                 radius=PLAYER_MARKER_R)

        surface.set_clip(prev_clip)
        if not snapshot.monsters:
            W.text(surface, "no monsters loaded", box.center, size=14,
                   color=C.TEXT_FAINT, align="center")

    def _player_heading(self, player):
        """Map-frame heading for the player triangle, with the calibration
        offset / flip applied. None if the player struct has not loaded
        (the marker degrades to a flat dot)."""
        if player.facing_rad is None:
            return None
        q = self.calib.quest
        h = player.facing_rad
        if q.get("facing_flip"):
            h = -h
        h += math.radians(float(q.get("facing_offset_deg", 0.0)))
        return h

    def _blit_monster(self, surface, m, center, selected):
        cx, cy = int(center[0]), int(center[1])
        big = (m.category == "big")
        # Big monsters render at 1.6× the small marker — they should
        # dominate the map at a glance, matching the in-game minimap
        # behavior.
        r = int(MARKER_RING_R * (1.6 if big else 1.0))
        icon_px = int(MARKER_PX * (1.6 if big else 1.0))
        ring = C.SELECT if selected else (C.WARN if big else C.MONSTER)
        pygame.draw.circle(surface, (0, 0, 0, 120), (cx, cy), r)
        pygame.draw.circle(surface, ring, (cx, cy), r, width=2)
        icon = self.assets.monster_icon(m.icon_slug)
        if icon:
            scaled = self.assets.scaled(icon, (icon_px, icon_px))
            surface.blit(scaled, scaled.get_rect(center=(cx, cy)))
        else:
            pygame.draw.circle(surface, C.MONSTER_DIM, (cx, cy), r - 2)
            W.text(surface, m.name[:1], (cx, cy - 7), size=14,
                   color=C.TEXT, bold=True, align="center")
        if selected or big:
            W.text(surface, m.name, (cx, cy - r - 10), size=11,
                   color=C.SELECT if selected else C.WARN, bold=True,
                   align="center")

    def _roster_panel(self, surface, snapshot):
        W.panel(surface, R_ROSTER, title="MONSTERS")
        monsters = snapshot.monsters
        if not monsters:
            W.text(surface, "none loaded", (R_ROSTER.x + 12, R_ROSTER.y + 34),
                   size=13, color=C.TEXT_FAINT)
            return
        # Group big first, small second. Big monsters paint with a small
        # "BIG" tag chip + the SELECT colour ring; small render plain.
        # `self.selected` indexes into snapshot.monsters as polled — keep
        # the same indices so click hit-tests stay correct, just reorder
        # the render order so big monsters get top billing.
        big_idxs = [i for i, m in enumerate(monsters) if m.category == "big"]
        small_idxs = [i for i, m in enumerate(monsters) if m.category != "big"]
        ordered = big_idxs + small_idxs
        row_h = 42
        y = R_ROSTER.y + 26
        for group_label, group in (("BIG", big_idxs), ("SMALL", small_idxs)):
            if not group:
                continue
            W.text(surface, group_label, (R_ROSTER.x + 12, y - 2), size=10,
                   color=C.ACCENT, bold=True)
            y += 12
            for i in group:
                m = monsters[i]
                if y + row_h > R_ROSTER.bottom:
                    break
                row = pygame.Rect(R_ROSTER.x + 6, y, R_ROSTER.w - 12,
                                  row_h - 4)
                if i == self.selected:
                    pygame.draw.rect(surface, C.PANEL_HI, row,
                                     border_radius=4)
                    pygame.draw.rect(surface, C.SELECT, row, width=1,
                                     border_radius=4)
                icon = self.assets.monster_icon(m.icon_slug)
                if icon:
                    surface.blit(self.assets.scaled(icon, (30, 30)),
                                 (row.x + 4, row.y + 4))
                W.text(surface, m.name, (row.x + 40, row.y + 4), size=13,
                       color=C.TEXT, bold=True)
                # slot + size chip on the second line. Size is the
                # per-entity scale multiplier pinned 2026-05-24
                # (addresses.OFF_M_SIZE_SCALE).
                size_str = ("?" if m.size_scale is None
                            else f"{m.size_scale:.2f}×")
                W.text(surface, f"slot {m.slot}  ·  size {size_str}",
                       (row.x + 40, row.y + 21),
                       size=10, color=C.TEXT_FAINT)
                hp_max = max(1, m.hp_max)
                W.bar(surface, (row.x + 96, row.y + 22, row.w - 104, 8),
                      m.hp / hp_max, C.MONSTER)
                W.text(surface, str(m.hp), (row.right - 6, row.y + 4),
                       size=12, color=C.TEXT, align="right")
                y += row_h
            y += 4

    def _bag_panel(self, surface, snapshot):
        """24-slot in-quest bag rendered as a 6×4 grid.

        Known item IDs (via `item_db.identify`) render with their wiki
        icon; unknown IDs fall back to a `0xNNNN` hex chip. Stack count
        prints in the bottom-right of every filled cell. Empty slots
        stay dim.

        Live-update note: the polled bag is the IN-QUEST bag at
        BAG_BASE (`0x090B39A8`, pinned 2026-05-24). It updates when
        you consume / pick up items during a quest. While still in the
        village it is the "prefetched" bag staged for the next quest;
        consuming items at the village item-box does NOT touch this
        cell (that's a different heap address). The header shows the
        live poll number so it is obvious whether the reader is
        actually polling.
        """
        from .. import item_db
        W.panel(surface, self._bag_rect, title="BAG")
        # Live-poll indicator: small chip showing the current poll
        # number so the user can confirm the reader is alive even when
        # bag contents look static (e.g. in village or with the bag
        # not yet allocated). Watch this number tick up while playing.
        W.text(surface, f"poll #{snapshot.poll_count}",
               (self._bag_rect.right - 8, self._bag_rect.y + 6),
               size=10, color=C.TEXT_FAINT, align="right")
        bag = snapshot.player.bag
        cols = 6
        rows = 4
        pad = 6
        slot_w = (R_BAG.w - (cols + 1) * pad) // cols
        slot_h = (R_BAG.h - 22 - (rows + 1) * pad) // rows
        for i in range(cols * rows):
            r = i // cols
            cc = i % cols
            x = R_BAG.x + pad + cc * (slot_w + pad)
            y = R_BAG.y + 22 + pad + r * (slot_h + pad)
            cell = pygame.Rect(x, y, slot_w, slot_h)
            slot = bag[i] if i < len(bag) else None
            if slot is None or slot.empty:
                pygame.draw.rect(surface, C.PANEL, cell, border_radius=3)
                pygame.draw.rect(surface, C.PANEL_HI, cell, width=1,
                                 border_radius=3)
                continue
            pygame.draw.rect(surface, C.PANEL_HI, cell, border_radius=3)
            pygame.draw.rect(surface, C.ACCENT, cell, width=1,
                             border_radius=3)
            _name, slug = item_db.identify(slot.item_id)
            icon = self.assets.item_icon(slug) if slug else None
            if icon is not None:
                # leave room at the bottom for the count chip
                icon_size = min(slot_w - 8, slot_h - 16)
                scaled = self.assets.scaled(icon, (icon_size, icon_size))
                surface.blit(scaled, scaled.get_rect(
                    center=(cell.centerx, cell.y + 4 + icon_size // 2)))
            else:
                # unknown ID — show the hex placeholder in the upper half
                W.text(surface, f"0x{slot.item_id:03X}",
                       (cell.centerx, cell.y + 4),
                       size=10, color=C.TEXT, bold=True, align="center")
            # count chip — bottom-right corner with a faint dark plate
            chip = pygame.Rect(cell.right - 22, cell.bottom - 14, 20, 12)
            pygame.draw.rect(surface, (0, 0, 0, 180), chip, border_radius=2)
            W.text(surface, f"×{slot.count}",
                   (chip.centerx, chip.y - 1),
                   size=11, color=C.SELECT, bold=True, align="center")

    def _detail_panel(self, surface, snapshot):
        W.panel(surface, self._detail_rect, title="DETAIL")
        monsters = snapshot.monsters
        if not monsters:
            W.text(surface, "select a monster", (self._detail_rect.x + 12,
                   self._detail_rect.y + 34), size=12, color=C.TEXT_FAINT)
            W.text(surface, "[ ] to cycle  ·  B toggles bag",
                   (self._detail_rect.x + 12,
                   self._detail_rect.y + 52), size=11, color=C.TEXT_FAINT)
            return
        m = monsters[self.selected]
        x = self._detail_rect.x + 12
        icon = self.assets.monster_icon(m.icon_slug)
        if icon:
            surface.blit(self.assets.scaled(icon, (64, 64)),
                         (self._detail_rect.centerx - 32, self._detail_rect.y + 28))
        else:
            W.placeholder_box(surface, (self._detail_rect.centerx - 32, self._detail_rect.y + 28,
                                        64, 64), "no icon")
        W.text(surface, m.name, (self._detail_rect.centerx, self._detail_rect.y + 96), size=16,
               color=C.SELECT, bold=True, align="center")

        hp_max = max(1, m.hp_max)
        W.bar(surface, (x, self._detail_rect.y + 122, self._detail_rect.w - 24, 14),
              m.hp / hp_max, C.MONSTER)
        W.text(surface, f"HP {m.hp}", (self._detail_rect.centerx, self._detail_rect.y + 124),
               size=11, color=C.TEXT, bold=True, align="center")

        dist = self._distance(m, snapshot.player)
        size_str = "?" if m.size_scale is None else f"{m.size_scale:.3f}×"
        rows = [
            ("Slot", m.slot),
            ("Pointer", f"0x{m.ptr:08X}"),
            ("Type byte", f"0x{m.type_byte:02X}"),
            ("Entity ID", f"0x{m.entity_id:02X}"),
            ("Size scale", size_str),
            ("AI behavior", m.ai_behavior),
            ("AI 0x324", m.ai_324),
            ("AI 0x32C", m.ai_32c),
            ("World X", f"{m.pos.x:.0f}"),
            ("World Y", f"{m.pos.y:.0f}"),
            ("World Z", f"{m.pos.z:.0f}"),
            ("Dist", "—" if dist is None else f"{dist:.0f}"),
        ]
        W.kv_rows(surface, (x, self._detail_rect.y + 148), rows, size=12, line_h=18,
                  key_w=92)
        W.text(surface, "+/- size  ·  PgUp/Dn type  ·  ENTER detail",
               (self._detail_rect.centerx,
                self._detail_rect.bottom - 22), size=10, color=C.TEXT_FAINT,
               align="center")

    # --- overlays ----------------------------------------------------------

    def _detail_overlay(self, surface, m, player):
        self.dim(surface, pygame.Rect(0, 0, CANVAS_W, CANVAS_H), 170)
        box = pygame.Rect(CANVAS_W // 2 - 280, CANVAS_H // 2 - 200, 560, 400)
        W.panel(surface, box, fill=C.PANEL_HI, border=C.SELECT)
        # Sub-tab indicator + tabs label. Title font shrunk + hint moved
        # to the panel footer so they don't collide on narrow names.
        tab_str = "STATS" if self.detail_subtab == "stats" else "AI DIAG"
        W.text(surface, f"{m.name}  —  {tab_str}",
               (box.x + 20, box.y + 14), size=18, color=C.SELECT, bold=True)
        W.text(surface, "TAB switch  ·  ENTER/ESC close",
               (box.right - 20, box.bottom - 24), size=11, color=C.TEXT_DIM,
               align="right")

        if self.detail_subtab == "stats":
            self._detail_subtab_stats(surface, box, m, player)
        else:
            self._detail_subtab_ai(surface, box, m)

    def _detail_subtab_stats(self, surface, box, m, player):
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
        size_str = ("?" if m.size_scale is None
                    else f"{m.size_scale:.4f}  (×base)")
        rows = [
            ("Display name", m.name),
            ("Registry slot", m.slot),
            ("Entity pointer", f"0x{m.ptr:08X}"),
            ("Type byte (+0x1E8)", f"0x{m.type_byte:02X}  (unreliable)"),
            ("Entity ID (+0x1E4)", f"0x{m.entity_id:02X}"),
            ("Size scale (+0x024)", size_str),
            ("AI behavior (+0x334)", m.ai_behavior),
            ("AI param (+0x324)", m.ai_324),
            ("AI param (+0x32C)", m.ai_32c),
            ("World position", f"{m.pos.x:.1f}, {m.pos.y:.1f}, {m.pos.z:.1f}"),
            ("Distance to player", "—" if dist is None else f"{dist:.0f} units"),
        ]
        W.kv_rows(surface, (box.x + 190, box.y + 56), rows, size=13,
                  line_h=24, key_w=180)
        W.text(surface, "TAB to AI DIAG  ·  AI-MOD tab for live edit",
               (box.x + 20, box.bottom - 44), size=11, color=C.TEXT_FAINT)

    def _detail_subtab_ai(self, surface, box, m):
        """Read-only AI diagnostic panel — Section 19f.4. Pulls fields from
        the per-entity MonsterAI snapshot the reader builds every poll."""
        ai = m.ai
        if ai is None:
            W.text(surface, "no AI snapshot available — reader has not yet "
                   "parsed this entity",
                   (box.x + 24, box.y + 60), size=12, color=C.PLACEHOLDER)
            return
        pursue_str = ("FLEE  (+0x1C8 == 0)" if ai.pursue_target == 0
                      else f"PURSUE  -> 0x{ai.pursue_target:08X}")
        flee_str = "1 (engine: fleeing)" if ai.flee_flag else "0"
        busy_str = "BUSY" if (ai.busy_bits & 0x1) else "free"
        mode_str = f"{ai.mode_byte}  (0..3 output mode)"
        # Section 19e.3 — bit 0x8 of +0x410 → state 1001.
        flag_bits = []
        for bit in (0x1, 0x2, 0x4, 0x8, 0x10, 0x20, 0x40, 0x80):
            if ai.flag_410 & bit:
                flag_bits.append(f"0x{bit:02X}")
        flag_bits_s = ", ".join(flag_bits) if flag_bits else "—"

        x0 = box.x + 24
        x1 = box.x + 290
        y0 = box.y + 50
        # Left column — direction + identity
        rows_left = [
            ("Pos (x,y,z)", f"{m.pos.x:.0f}, {m.pos.y:.0f}, {m.pos.z:.0f}"),
            ("Heading", f"{ai.heading.x:+.2f}, {ai.heading.y:+.2f}, "
                        f"{ai.heading.z:+.2f}"),
            ("Anim ptr (+0xB8)", f"0x{ai.anim_ptr:08X}"),
            ("Busy bits (+0xBC)", f"0x{ai.busy_bits:08X}  ({busy_str})"),
            ("Frame ctr (+0x092)", ai.frame_counter),
            ("Action cnt (+0x1A2)", ai.action_count),
            ("Species tbl (+0x1AC)", f"0x{ai.species_tbl_ptr:08X}"),
            ("Pursue (+0x1C8)", pursue_str),
            ("Action list (+0x640)", f"0x{ai.action_list_ptr:08X}"),
            ("Flee flag (+0x6D8)", flee_str),
            ("Herd members", len(ai.herd_members)),
        ]
        W.kv_rows(surface, (x0, y0), rows_left, size=12, line_h=20, key_w=140)
        # Right column — state + ladder conditions
        rows_right = [
            ("Seed (+0x324)", ai.seed),
            ("Seed pair (+0x326)", ai.seed_paired),
            ("Stimulus (+0x322)", f"0x{ai.stimulus_tag:02X}"),
            ("State (+0x334)", f"{ai.state_byte}  (1/2/5/10)"),
            ("Mode (+0x29C)", mode_str),
            ("Flag (+0x410)", f"0x{ai.flag_410:08X}"),
            ("  bits set", flag_bits_s),
            ("Dmg flag (+0x414)", f"0x{ai.damage_flag:08X}"),
            ("Timer (+0x624)", f"{ai.timer_624}  ticks"),
            ("Timer (+0x626)", f"{ai.timer_626}  ticks"),
            ("Stress (+0x62E)", f"{ai.stress_62E}  [75..450]"),
            ("AI param (+0x32C)", ai.ai_param),
        ]
        W.kv_rows(surface, (x1, y0), rows_right, size=12, line_h=20, key_w=140)
        # Big-monster note — type 0x3A has dynamic +0x640
        if m.type_byte == 0x3A:
            W.text(surface,
                   "type 0x3A  ·  alt dispatcher  ·  +0x640 is runtime-mutable",
                   (box.x + 20, box.bottom - 60), size=11, color=C.WARN,
                   bold=True)
        W.text(surface, "read-only here  —  use AI-MOD tab to pin / edit",
               (box.x + 20, box.bottom - 44), size=11, color=C.TEXT_FAINT)

    def _calib_hint(self, surface):
        box = pygame.Rect(CANVAS_W // 2 - 320, CANVAS_H - 116, 640, 76)
        W.panel(surface, box, fill=C.PANEL_HI, border=C.ACCENT)
        W.text(surface, "MAP CALIBRATION", (box.x + 16, box.y + 8), size=12,
               color=C.ACCENT, bold=True)
        W.text(surface, "+/-: scale   , .: rotate   T: mode   "
               "arrows: origin (fixed)",
               (box.x + 16, box.y + 26), size=12, color=C.TEXT)
        q = self.calib.quest
        flip_s = "ON" if q.get("facing_flip") else "off"
        W.text(surface,
               f"H/J: heading offset ({q.get('facing_offset_deg', 0):.0f}°)  "
               f"F: flip ({flip_s})   1-8: set section   0: re-snap   "
               f"S: save   C: exit",
               (box.x + 16, box.y + 46), size=12, color=C.TEXT)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _distance(m, player):
        if not player.loaded:
            return None
        dx = m.pos.x - player.pos_world.x
        dz = m.pos.z - player.pos_world.z
        return math.hypot(dx, dz)
