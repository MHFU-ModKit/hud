"""Pygame application — window, main loop, layout switching, scaling.

Layouts render onto a fixed virtual canvas (CANVAS_W x CANVAS_H); the app
letterbox-scales that canvas to the real window so the HUD keeps its design
proportions at any size. The window cannot shrink below the canvas size.
"""

import pygame

from . import panels, widgets as W
from .assets import AssetLibrary
from .calibration import Calibration
from .layouts import QuestLayout, VillageLayout
from .state import Context
from .theme import C, CANVAS_W, CANVAS_H

WINDOW_TITLE = "MHFU Live HUD"
GAMEPLAY = {Context.VILLAGE, Context.QUEST}

_HELP = [
    ("F1", "toggle this help"),
    ("F2 / F3 / F4", "layout: auto / force village / force quest"),
    ("F11", "toggle fullscreen"),
    ("ESC", "close overlay, or quit"),
    ("", ""),
    ("TAB  or  ]", "select next monster (quest)"),
    ("[", "select previous monster (quest)"),
    ("ENTER", "open / close monster detail page"),
    ("M", "cycle map image (quest)"),
    ("", ""),
    ("C", "toggle calibration mode"),
    ("+  /  -", "calib: map scale"),
    (",  /  .", "calib: map rotation"),
    ("T", "calib: player-centered / fixed mode"),
    ("arrows", "calib: nudge map origin or village marker"),
    ("S", "calib: save calibration.json"),
]


class HUDApp:
    def __init__(self, reader, fullscreen=False):
        self.reader = reader
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)
        self._windowed_size = (CANVAS_W, CANVAS_H)
        self.fullscreen = fullscreen
        self._make_window(self._windowed_size, fullscreen)
        self.canvas = pygame.Surface((CANVAS_W, CANVAS_H)).convert()
        self.clock = pygame.time.Clock()
        self.assets = AssetLibrary()
        self.calib = Calibration()
        self.layouts = {
            Context.VILLAGE: VillageLayout(self.assets, self.calib),
            Context.QUEST: QuestLayout(self.assets, self.calib),
        }
        self.forced = None          # Context or None (= auto)
        self.show_help = False
        self.running = True
        self._blit_off = (0, 0)
        self._blit_scale = 1.0

    # --- window ------------------------------------------------------------

    def _make_window(self, size, fullscreen):
        if fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            w = max(CANVAS_W, size[0])
            h = max(CANVAS_H, size[1])
            self.screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)

    def _toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self._make_window(self._windowed_size, self.fullscreen)

    # --- loop --------------------------------------------------------------

    def run(self):
        while self.running:
            snap = self.reader.snapshot
            self._handle_events(snap)
            self._render(snap)
            self.clock.tick(60)
        pygame.quit()

    def _context(self, snap):
        return self.forced if self.forced is not None else snap.context

    def _handle_events(self, snap):
        ctx = self._context(snap)
        layout = self.layouts.get(ctx)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.VIDEORESIZE and not self.fullscreen:
                self._windowed_size = (ev.w, ev.h)
                self._make_window(self._windowed_size, False)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if layout is not None:
                    layout.handle_click(self._to_canvas(ev.pos), snap)
            elif ev.type == pygame.KEYDOWN:
                self._handle_key(ev.key, snap, layout)

    def _handle_key(self, key, snap, layout):
        if key == pygame.K_F1:
            self.show_help = not self.show_help
            return
        if key == pygame.K_F2:
            self.forced = None
            return
        if key == pygame.K_F3:
            self.forced = Context.VILLAGE
            return
        if key == pygame.K_F4:
            self.forced = Context.QUEST
            return
        if key == pygame.K_F11:
            self._toggle_fullscreen()
            return
        if self.show_help and key == pygame.K_ESCAPE:
            self.show_help = False
            return
        # give the active layout first refusal (it may consume ESC to close
        # an overlay); only quit on ESC if nothing else wanted it
        if layout is not None and layout.handle_key(key, snap):
            return
        if key == pygame.K_ESCAPE:
            self.running = False

    # --- render ------------------------------------------------------------

    def _render(self, snap):
        ctx = self._context(snap)
        layout = self.layouts.get(ctx)
        show_layout = layout is not None and (
            self.forced is not None or (snap.connected and ctx in GAMEPLAY))
        if show_layout:
            layout.render(self.canvas, snap)
        else:
            panels.draw_status_screen(self.canvas, snap)
        self._status_pill(snap, ctx)
        if self.show_help:
            self._draw_help()
        self._present()

    def _status_pill(self, snap, ctx):
        dot = C.OK if snap.connected else C.ERR
        pygame.draw.circle(self.canvas, dot, (CANVAS_W // 2 - 142, 9), 5)
        parts = [ctx.value.upper()]
        if self.forced is not None:
            parts.append("[FORCED]")
        parts.append(f"{self.clock.get_fps():.0f}fps")
        parts.append(f"poll {snap.poll_latency_ms:.0f}ms")
        parts.append("F1 help")
        W.text(self.canvas, "  ·  ".join(parts), (CANVAS_W // 2 - 128, 2),
               size=12, color=C.TEXT_DIM)

    def _draw_help(self):
        veil = pygame.Surface((CANVAS_W, CANVAS_H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 200))
        self.canvas.blit(veil, (0, 0))
        box = pygame.Rect(CANVAS_W // 2 - 260, 70, 520, 404)
        W.panel(self.canvas, box, fill=C.PANEL_HI, border=C.ACCENT)
        W.text(self.canvas, "MHFU LIVE HUD — CONTROLS", (box.x + 20, box.y + 16),
               size=18, color=C.ACCENT, bold=True)
        y = box.y + 52
        for keys, desc in _HELP:
            if keys:
                W.text(self.canvas, keys, (box.x + 24, y), size=13,
                       color=C.SELECT, bold=True)
                W.text(self.canvas, desc, (box.x + 200, y), size=13,
                       color=C.TEXT)
            y += 21
        W.text(self.canvas, "read-only — the HUD never injects input or "
               "writes memory", (box.x + 20, box.bottom - 30), size=11,
               color=C.TEXT_FAINT)

    def _present(self):
        ww, wh = self.screen.get_size()
        self._blit_scale = min(ww / CANVAS_W, wh / CANVAS_H)
        sw = int(CANVAS_W * self._blit_scale)
        sh = int(CANVAS_H * self._blit_scale)
        self._blit_off = ((ww - sw) // 2, (wh - sh) // 2)
        self.screen.fill((0, 0, 0))
        self.screen.blit(pygame.transform.smoothscale(self.canvas, (sw, sh)),
                         self._blit_off)
        pygame.display.flip()

    def _to_canvas(self, win_pos):
        ox, oy = self._blit_off
        s = self._blit_scale or 1.0
        return ((win_pos[0] - ox) / s, (win_pos[1] - oy) / s)
