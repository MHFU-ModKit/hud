"""Quest-prep HUD layout (Section 15.14 — staged edits).

Active when the player is in the village but a quest is queued (auto-
detected by area_index != 0 in non-quest context). Lets the user
author 'staged edits' that the HUD will apply automatically to
monster entities the moment they spawn in the quest area.

Why staged-edits + apply-on-spawn:
  Section 15.13 nailed it down: the .mib monster spawn section never
  enters RAM until quest-START — the elder menu only loads quest
  metadata (title, money, time, quest_id). So the only way to
  emulate 'pre-quest editing' is to (a) let the user author edits
  while in the village, then (b) write them into the live entity
  registry once monsters appear post-zone-load. This layout owns the
  authoring UI; the apply loop runs inside the reader thread (see
  `MemoryReader._maybe_apply_edits`).

Editor controls:
  ↑ / ↓        cycle selection (monster slot OR edit row)
  TAB          switch LIVE / QUEST-PREP (handled by app)
  S            stage a SIZE edit for the currently selected monster's
               species (uses the size value shown next to the monster)
  H            stage an HP edit
  T            stage a TYPE-SWAP edit (cycles target through known
               species types)
  +/-          tweak the new-value of the most recently staged edit
               (size by ±0.05, hp by ±10, type by ±1)
  ENTER        toggle the selected staged edit on/off
  DEL / X      remove the selected staged edit
  M            toggle master enable (auto-apply on/off)
"""

import struct

import pygame

from .. import widgets as W
from ..edits import StagedEdit
from ..theme import C, CANVAS_W, CANVAS_H
from .base import Layout

# Layout rectangles
R_HEADER  = pygame.Rect(12, 12, CANVAS_W - 24, 50)
R_ROSTER  = pygame.Rect(12, 70, 360, CANVAS_H - 70 - 50)
R_EDITS   = pygame.Rect(380, 70, CANVAS_W - 380 - 12, CANVAS_H - 70 - 50)
R_FOOTER  = pygame.Rect(12, CANVAS_H - 40, CANVAS_W - 24, 28)


SIZE_STEP = 0.05
HP_STEP = 10


class QuestPrepLayout(Layout):
    name = "quest_prep"

    def __init__(self, assets, calib, reader=None):
        super().__init__(assets, calib)
        self.reader = reader
        # `selection_zone` toggles between roster (monster slot) and
        # edits list with TAB-equivalent. Default left = roster.
        self.zone = "roster"      # 'roster' | 'edits'
        self.selected_monster = 0
        self.selected_edit = 0

    # --- input -----------------------------------------------------------

    def handle_key(self, key, snapshot) -> bool:
        bank = self.reader.edit_bank if self.reader else None
        if key == pygame.K_LEFT:
            self.zone = "roster"
            return True
        if key == pygame.K_RIGHT:
            self.zone = "edits"
            return True
        if key == pygame.K_UP:
            if self.zone == "roster":
                if snapshot.monsters:
                    self.selected_monster = (self.selected_monster - 1) \
                                            % len(snapshot.monsters)
            else:
                if bank and bank.edits:
                    self.selected_edit = (self.selected_edit - 1) \
                                         % len(bank.edits)
            return True
        if key == pygame.K_DOWN:
            if self.zone == "roster":
                if snapshot.monsters:
                    self.selected_monster = (self.selected_monster + 1) \
                                            % len(snapshot.monsters)
            else:
                if bank and bank.edits:
                    self.selected_edit = (self.selected_edit + 1) \
                                         % len(bank.edits)
            return True
        if key == pygame.K_m:
            if bank:
                bank.toggle_master()
            return True
        if bank is None:
            return False
        # Add / modify edits
        if key == pygame.K_s and self.zone == "roster":
            m = self._cur_monster(snapshot)
            if m is not None:
                bank.add(StagedEdit(
                    kind="size_species",
                    selector_value=m.type_byte,
                    new_value=float(m.size_scale or 1.0),
                    label=f"size {m.name} (type 0x{m.type_byte:02X})"
                          f" → {m.size_scale or 1.0:.2f}",
                ))
                self.selected_edit = len(bank.edits) - 1
                self.zone = "edits"
            return True
        if key == pygame.K_h and self.zone == "roster":
            m = self._cur_monster(snapshot)
            if m is not None:
                bank.add(StagedEdit(
                    kind="hp_slot",
                    selector_value=m.slot,
                    new_value=float(m.hp),
                    label=f"HP slot {m.slot} ({m.name}) → {m.hp}",
                ))
                self.selected_edit = len(bank.edits) - 1
                self.zone = "edits"
            return True
        if key == pygame.K_t and self.zone == "roster":
            m = self._cur_monster(snapshot)
            if m is not None:
                bank.add(StagedEdit(
                    kind="type_swap",
                    selector_value=m.type_byte,
                    new_value=float((m.type_byte + 1) & 0xFF),
                    label=f"type 0x{m.type_byte:02X} → "
                          f"0x{(m.type_byte + 1) & 0xFF:02X}",
                ))
                self.selected_edit = len(bank.edits) - 1
                self.zone = "edits"
            return True
        # Adjust the value of the selected edit
        if self.zone == "edits" and bank.edits:
            e = bank.edits[self.selected_edit]
            if key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                if e.kind in ("size_species", "size_slot"):
                    e.new_value = round(e.new_value + SIZE_STEP, 3)
                elif e.kind == "hp_slot":
                    e.new_value += HP_STEP
                elif e.kind == "type_swap":
                    e.new_value = float((int(e.new_value) + 1) & 0xFF)
                e.reset_applied()  # re-apply with new value next poll
                return True
            if key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                if e.kind in ("size_species", "size_slot"):
                    e.new_value = round(max(0.1, e.new_value - SIZE_STEP), 3)
                elif e.kind == "hp_slot":
                    e.new_value = max(1, e.new_value - HP_STEP)
                elif e.kind == "type_swap":
                    e.new_value = float((int(e.new_value) - 1) & 0xFF)
                e.reset_applied()
                return True
            if key == pygame.K_RETURN:
                bank.toggle(self.selected_edit)
                return True
            if key in (pygame.K_DELETE, pygame.K_x):
                bank.remove(self.selected_edit)
                if self.selected_edit >= len(bank.edits):
                    self.selected_edit = max(0, len(bank.edits) - 1)
                return True
        return False

    def _cur_monster(self, snapshot):
        monsters = snapshot.monsters
        if not monsters:
            return None
        idx = self.selected_monster % len(monsters)
        return monsters[idx]

    # --- render ----------------------------------------------------------

    def render(self, surface, snapshot):
        surface.fill(C.BG)
        bank = self.reader.edit_bank if self.reader else None
        self._header(surface, snapshot, bank)
        self._roster(surface, snapshot)
        self._edits(surface, bank)
        self._footer(surface)

    def _header(self, surface, snapshot, bank):
        W.panel(surface, R_HEADER)
        ai = snapshot.area_index
        ctx = snapshot.context.value
        title = "QUEST PREP — staged edits, applied on quest entry"
        W.text(surface, title, (R_HEADER.x + 12, R_HEADER.y + 6),
               size=16, color=C.ACCENT, bold=True)
        master = "ON " if (bank and bank.enabled) else "OFF"
        n_edits = len(bank.edits) if bank else 0
        W.text(surface,
               f"ctx={ctx}   area_index={ai}   "
               f"ss={snapshot.screen_state}   "
               f"AUTO-APPLY: {master}   {n_edits} edits queued",
               (R_HEADER.x + 12, R_HEADER.y + 28), size=12,
               color=C.TEXT_DIM)

    def _roster(self, surface, snapshot):
        title = "ROSTER" + (" (selected)" if self.zone == "roster" else "")
        W.panel(surface, R_ROSTER, title=title)
        monsters = snapshot.monsters
        if not monsters:
            W.text(surface, "(no live monsters — apply will trigger "
                   "automatically once the quest spawns them)",
                   (R_ROSTER.x + 12, R_ROSTER.y + 34), size=12,
                   color=C.TEXT_FAINT)
            return
        row_h = 28
        for i, m in enumerate(monsters):
            y = R_ROSTER.y + 30 + i * row_h
            row = pygame.Rect(R_ROSTER.x + 4, y, R_ROSTER.w - 8, row_h - 2)
            if i == self.selected_monster and self.zone == "roster":
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=3)
            size_str = f"{m.size_scale:.2f}×" if m.size_scale is not None \
                       else "?"
            W.text(surface,
                   f"slot {m.slot}  {m.name:14s}  hp={m.hp:4d}  "
                   f"size={size_str}  type=0x{m.type_byte:02X}",
                   (row.x + 8, row.y + 6), size=12, color=C.TEXT)

    def _edits(self, surface, bank):
        title = "STAGED EDITS" + (" (selected)" if self.zone == "edits"
                                  else "")
        W.panel(surface, R_EDITS, title=title)
        if bank is None or not bank.edits:
            W.text(surface,
                   "(no edits staged — focus the roster (←) and press "
                   "S/H/T to stage)",
                   (R_EDITS.x + 12, R_EDITS.y + 34), size=12,
                   color=C.TEXT_FAINT)
            return
        row_h = 24
        for i, e in enumerate(bank.edits):
            y = R_EDITS.y + 30 + i * row_h
            row = pygame.Rect(R_EDITS.x + 4, y, R_EDITS.w - 8, row_h - 2)
            if i == self.selected_edit and self.zone == "edits":
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=3)
            mark = "[x]" if e.enabled else "[ ]"
            applied = len(e.applied_to)
            mark_color = C.OK if e.enabled else C.TEXT_FAINT
            W.text(surface, mark,
                   (row.x + 8, row.y + 4), size=12, color=mark_color,
                   bold=True)
            W.text(surface, e.label,
                   (row.x + 36, row.y + 4), size=12, color=C.TEXT)
            W.text(surface, f"applied to {applied} entit{'y' if applied==1 else 'ies'}",
                   (row.right - 8, row.y + 4), size=11, color=C.TEXT_FAINT,
                   align="right")

    def _footer(self, surface):
        W.text(surface,
               "←/→ panel   ↑/↓ select   S size  H hp  T type-swap   "
               "+/- adjust   ENTER toggle   X remove   M master",
               (R_FOOTER.x + 4, R_FOOTER.y + 6), size=11, color=C.TEXT_FAINT)
