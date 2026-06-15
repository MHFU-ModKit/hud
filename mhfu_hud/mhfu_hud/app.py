"""Pygame application — window, main loop, layout switching, scaling.

Layouts render onto a fixed virtual canvas (CANVAS_W x CANVAS_H); the app
letterbox-scales that canvas to the real window so the HUD keeps its design
proportions at any size. The window cannot shrink below the canvas size.
"""

import pygame

from . import panels, widgets as W
from .ai_pin import PinEngine
from .assets import AssetLibrary
from .calibration import Calibration
from .layouts import AIModLayout, QuestLayout, QuestPrepLayout, VillageLayout
from .state import Context
from .theme import C, CANVAS_W, CANVAS_H

WINDOW_TITLE = "MHFU Live HUD"
GAMEPLAY = {Context.VILLAGE, Context.QUEST}

# Tab modes. The HUD shows ONE tab at a time. LIVE follows the snapshot
# context, QUEST_PREP is the village spawn-editor, AI_MOD is the live AI
# editor. TAB cycles forward through TABS; auto-switch toggles between
# LIVE and QUEST_PREP on context changes but leaves AI_MOD alone (the
# user pin-locks AI_MOD by hitting TAB to reach it).
TAB_LIVE = "live"
TAB_QUEST_PREP = "quest_prep"
TAB_AI_MOD = "ai_mod"
TABS = (TAB_LIVE, TAB_QUEST_PREP, TAB_AI_MOD)

_HELP = [
    ("F1", "toggle this help"),
    ("F2 / F3 / F4", "layout: auto / force village / force quest"),
    ("F11", "toggle fullscreen"),
    ("ESC", "close overlay, or quit"),
    ("TAB", "cycle tabs LIVE → QUEST-PREP → AI-MOD"),
    ("", ""),
    ("B", "toggle bag panel (quest)"),
    ("] / [", "select next / previous monster (quest)"),
    ("+ / -", "live edit selected monster size (±0.05)"),
    ("PgUp / PgDn", "live edit selected monster type byte (±1)"),
    ("ENTER", "open / close monster detail page"),
    ("TAB", "in monster detail: cycle STATS → AI-DIAG → AI-ACTIONS"),
    ("M", "cycle map image (quest)"),
    ("", ""),
    ("↑ ↓ ← →", "navigate quest-prep panels + rows"),
    ("S / H / T", "stage size / hp / type-swap edit"),
    ("+ / -", "adjust selected staged edit"),
    ("ENTER", "toggle edit on/off"),
    ("X / DEL", "remove staged edit"),
    ("M", "master enable auto-apply"),
    ("", ""),
    ("] / [", "AI-MOD: cycle entity"),
    ("↑ / ↓", "AI-MOD: cycle field"),
    ("← / →", "AI-MOD: switch column (entity / species / actions)"),
    ("SPACE", "AI-MOD: toggle pin on selected field"),
    ("+ / -", "AI-MOD: adjust selected value"),
    ("R", "AI-MOD: raise state literal (writes seed pair)"),
    ("F", "AI-MOD: force flee / pursue toggle on selected entity"),
    ("X", "AI-MOD: clear all pins"),
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
        # NB: NOT `pygame.init()`. That calls SDL_Init(SDL_INIT_EVERYTHING),
        # which brings up the joystick / game-controller subsystems. On
        # macOS that races PPSSPP for IOHID gamepad reports — PPSSPP then
        # freezes the controller at its last value (and never sees a fresh
        # event, even on physical disconnect). We only need video + fonts.
        pygame.display.init()
        pygame.font.init()
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
            Context.QUEST: QuestLayout(self.assets, self.calib,
                                       reader=self.reader),
        }
        self.quest_prep = QuestPrepLayout(self.assets, self.calib,
                                          reader=self.reader)
        # PinEngine — owns the 30 Hz write-back thread used by the AI
        # editor. Sleeps when no pins are active, so the read-only HUD
        # path costs nothing extra.
        self.pin_engine = PinEngine(
            client_provider=lambda: self.reader._client)
        self.pin_engine.start()
        self.ai_mod = AIModLayout(self.assets, self.calib,
                                  reader=self.reader,
                                  pin_engine=self.pin_engine)
        self.forced = None          # Context or None (= auto)
        # Tab state — LIVE follows context, QUEST_PREP is the spawn
        # editor, AI_MOD is the live AI editor. `_tab_user_pinned` is
        # set whenever the user presses TAB so auto-switch leaves their
        # choice alone until the next context change.
        self.tab = TAB_LIVE
        self._tab_user_pinned = False
        self._last_quest_prep_eligible = False
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
        try:
            while self.running:
                snap = self.reader.snapshot
                self._handle_events(snap)
                self._render(snap)
                self.clock.tick(60)
        finally:
            # Always stop the pin engine on app exit so the daemon thread
            # doesn't keep hammering writes against a torn-down reader.
            self.pin_engine.stop()
            pygame.quit()

    def _context(self, snap):
        return self.forced if self.forced is not None else snap.context

    def _handle_events(self, snap):
        self._maybe_auto_switch_tab(snap)
        layout = self._active_layout(snap)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.VIDEORESIZE and not self.fullscreen:
                self._windowed_size = (ev.w, ev.h)
                self._make_window(self._windowed_size, False)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if layout is not None:
                    layout.handle_click(self._to_canvas(ev.pos), snap)
            elif ev.type == pygame.MOUSEMOTION:
                if layout is not None:
                    layout.handle_motion(self._to_canvas(ev.pos), snap)
            elif ev.type == pygame.KEYDOWN:
                self._handle_key(ev.key, snap, layout)

    def _quest_prep_eligible(self, snap) -> bool:
        """Heuristic: in village context (or boot/menu/loading) with a
        non-zero area_index — the engine prefetches the quest's area
        index even before the hunter walks out of the village, so a
        nonzero value while still in village means a quest is queued."""
        if snap.context == Context.QUEST:
            return False
        return snap.area_index not in (0, -1)

    def _maybe_auto_switch_tab(self, snap):
        """Auto-flip to QUEST_PREP on the FRAME the prep state becomes
        true (and back to LIVE when it lapses), but only if the user
        has not manually pinned a tab. Once the player enters the
        quest, the pin clears so manual choices reset."""
        eligible = self._quest_prep_eligible(snap)
        if snap.context == Context.QUEST:
            # Reset pin on quest entry so the next prep-cycle starts fresh
            self._tab_user_pinned = False
        if not self._tab_user_pinned:
            if eligible and not self._last_quest_prep_eligible:
                self.tab = TAB_QUEST_PREP
            elif not eligible and self._last_quest_prep_eligible:
                self.tab = TAB_LIVE
        self._last_quest_prep_eligible = eligible

    def _active_layout(self, snap):
        """Layout currently driving keys + click hits.

        Top-level tab decides: AI_MOD and QUEST_PREP both overlay the
        context-driven layouts and own input fully while active.
        """
        if self.tab == TAB_AI_MOD:
            return self.ai_mod
        if self.tab == TAB_QUEST_PREP:
            return self.quest_prep
        ctx = self._context(snap)
        return self.layouts.get(ctx)

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
        # Give the layout first chance at TAB — the quest detail page
        # consumes TAB to cycle its STATS / AI-DIAG sub-pages. If the
        # layout doesn't take it, fall through to the global tab cycle.
        if layout is not None and layout.handle_key(key, snap):
            return
        if key == pygame.K_TAB:
            i = TABS.index(self.tab) if self.tab in TABS else 0
            self.tab = TABS[(i + 1) % len(TABS)]
            self._tab_user_pinned = True
            return
        if key == pygame.K_ESCAPE:
            self.running = False

    # --- render ------------------------------------------------------------

    def _render(self, snap):
        if self.tab == TAB_AI_MOD:
            self.ai_mod.render(self.canvas, snap)
            self._status_pill(snap, self._context(snap))
        elif self.tab == TAB_QUEST_PREP:
            self.quest_prep.render(self.canvas, snap)
            self._status_pill(snap, self._context(snap))
        else:
            ctx = self._context(snap)
            layout = self.layouts.get(ctx)
            show_layout = layout is not None and (
                self.forced is not None or
                (snap.connected and ctx in GAMEPLAY))
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
        # Tab indicator — visible regardless of which tab is active
        # so the user always knows what TAB does next.
        if self.tab == TAB_AI_MOD:
            n_pins = self.pin_engine.count()
            parts.append(f"[AI-MOD{f' {n_pins}p' if n_pins else ''}]")
        elif self.tab == TAB_QUEST_PREP:
            parts.append("[PREP]")
        else:
            parts.append("[LIVE]")
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
