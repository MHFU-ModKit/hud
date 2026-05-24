"""Quest-prep HUD layout (Section 15.19 — species picker).

Two panels:
  LEFT  — SPECIES picker. List of every monster species known to the
          HUD (confirmed type bytes + named-but-TBD entries). User
          picks any species; pressing ENTER stages a size_species
          edit for it at value 1.0.
  RIGHT — STAGED EDITS. The bank entries — each shows the species,
          its target value, applied count, enabled flag. The reader
          thread auto-applies them to every matching entity the
          moment one spawns.

Why a picker instead of a roster: while in village (the time the
user wants to author edits) the entity registry is empty, so the
previous 'pick a live monster' design couldn't be used. Section
15.18 also hit a wall trying to load the actual spawn list from
the .mib file (see docs/QUEST_EDITING.md for the dig). The picker
side-steps that: you tell the HUD which species you EXPECT to see
in the upcoming quest, the edit fires when the engine actually
spawns one.

Editor controls (Section 15.19):
  ←/→          switch panel focus (PICKER ↔ EDITS)
  ↑/↓          cycle within focused panel
  PgUp/PgDn    jump 10 rows (long species list)
  ENTER        on PICKER: stage size_species edit for selected species
               on EDITS: toggle the selected edit on/off
  +/-          on EDITS: adjust the staged value (size ±0.05)
  X / DEL      on EDITS: remove the selected edit
  T            on EDITS: cycle edit kind size → type_swap → hp → size
  M            master enable/disable auto-apply
  B            on PICKER: bind a custom type-byte (hex) to selected
                          species. Useful for entries whose primary
                          byte is None (TBD).
"""

import pygame

from .. import widgets as W
from ..edits import StagedEdit
from ..monster_db import PICKER_SPECIES, TYPE_NAMES
from ..theme import C, CANVAS_W, CANVAS_H
from .base import Layout

R_HEADER = pygame.Rect(12, 12, CANVAS_W - 24, 50)
R_PICKER = pygame.Rect(12, 70, 360, CANVAS_H - 70 - 50)
R_EDITS  = pygame.Rect(380, 70, CANVAS_W - 380 - 12, CANVAS_H - 70 - 50)
R_FOOTER = pygame.Rect(12, CANVAS_H - 40, CANVAS_W - 24, 28)

SIZE_STEP = 0.05
HP_STEP = 10
EDIT_KINDS = ["size_species", "type_swap", "hp_slot"]


class QuestPrepLayout(Layout):
    name = "quest_prep"

    def __init__(self, assets, calib, reader=None):
        super().__init__(assets, calib)
        self.reader = reader
        self.zone = "picker"
        self.selected_species = 0
        self.selected_edit = 0
        # Custom type-byte overrides for picker entries with None
        # primary. Keyed by species index. User-set via 'B' hotkey.
        self.custom_bytes: dict[int, int] = {}
        # 'B' hotkey input mode — the next hex digit pair becomes
        # the custom byte for `self.selected_species`.
        self._binding_input = None  # None | "" | "X" (first nibble entered)

    # --- input ----------------------------------------------------------

    def handle_key(self, key, snapshot) -> bool:
        bank = self.reader.edit_bank if self.reader else None
        if key == pygame.K_LEFT:
            self.zone = "picker"
            return True
        if key == pygame.K_RIGHT:
            self.zone = "edits"
            return True
        if self.zone == "picker":
            return self._picker_key(key, snapshot, bank)
        return self._edits_key(key, snapshot, bank)

    def _picker_key(self, key, snapshot, bank) -> bool:
        n = len(PICKER_SPECIES)
        # 'B' bind-byte mode: accept 2 hex digits then commit
        if self._binding_input is not None:
            ch = pygame.key.name(key)
            if len(ch) == 1 and ch in "0123456789abcdef":
                self._binding_input += ch
                if len(self._binding_input) == 2:
                    val = int(self._binding_input, 16)
                    self.custom_bytes[self.selected_species] = val
                    self._binding_input = None
                return True
            if key == pygame.K_ESCAPE:
                self._binding_input = None
                return True
            return True
        if key == pygame.K_UP:
            self.selected_species = (self.selected_species - 1) % n
            return True
        if key == pygame.K_DOWN:
            self.selected_species = (self.selected_species + 1) % n
            return True
        if key == pygame.K_PAGEUP:
            self.selected_species = (self.selected_species - 10) % n
            return True
        if key == pygame.K_PAGEDOWN:
            self.selected_species = (self.selected_species + 10) % n
            return True
        if key == pygame.K_RETURN:
            if bank is None:
                return True
            tb = self._effective_type_byte(self.selected_species)
            if tb is None:
                return True  # silently ignore until user binds a byte
            name, _ = PICKER_SPECIES[self.selected_species]
            bank.add(StagedEdit(
                kind="size_species",
                selector_value=tb,
                new_value=1.0,
                label=f"size {name} (type 0x{tb:02X}) → 1.00",
            ))
            self.selected_edit = len(bank.edits) - 1
            self.zone = "edits"
            return True
        if key == pygame.K_b:
            self._binding_input = ""
            return True
        if key == pygame.K_m and bank is not None:
            bank.toggle_master()
            return True
        return False

    def _edits_key(self, key, snapshot, bank) -> bool:
        if bank is None or not bank.edits:
            if key == pygame.K_m and bank is not None:
                bank.toggle_master()
                return True
            return False
        n = len(bank.edits)
        if key == pygame.K_UP:
            self.selected_edit = (self.selected_edit - 1) % n
            return True
        if key == pygame.K_DOWN:
            self.selected_edit = (self.selected_edit + 1) % n
            return True
        e = bank.edits[self.selected_edit]
        if key == pygame.K_RETURN:
            bank.toggle(self.selected_edit)
            return True
        if key in (pygame.K_DELETE, pygame.K_x):
            bank.remove(self.selected_edit)
            if self.selected_edit >= len(bank.edits):
                self.selected_edit = max(0, len(bank.edits) - 1)
            return True
        if key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            if e.kind in ("size_species", "size_slot"):
                e.new_value = round(e.new_value + SIZE_STEP, 3)
            elif e.kind == "hp_slot":
                e.new_value += HP_STEP
            elif e.kind == "type_swap":
                e.new_value = float((int(e.new_value) + 1) & 0xFF)
            e.reset_applied()
            self._refresh_label(e)
            return True
        if key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            if e.kind in ("size_species", "size_slot"):
                e.new_value = round(max(0.1, e.new_value - SIZE_STEP), 3)
            elif e.kind == "hp_slot":
                e.new_value = max(1, e.new_value - HP_STEP)
            elif e.kind == "type_swap":
                e.new_value = float((int(e.new_value) - 1) & 0xFF)
            e.reset_applied()
            self._refresh_label(e)
            return True
        if key == pygame.K_t:
            cur = EDIT_KINDS.index(e.kind) if e.kind in EDIT_KINDS else 0
            e.kind = EDIT_KINDS[(cur + 1) % len(EDIT_KINDS)]
            e.reset_applied()
            self._refresh_label(e)
            return True
        if key == pygame.K_m:
            bank.toggle_master()
            return True
        return False

    # --- helpers --------------------------------------------------------

    def _effective_type_byte(self, idx: int):
        name, byte = PICKER_SPECIES[idx]
        if byte is not None:
            return byte
        return self.custom_bytes.get(idx)

    def _refresh_label(self, edit: StagedEdit):
        name = TYPE_NAMES.get(edit.selector_value,
                                f"0x{edit.selector_value:02X}")
        if edit.kind == "size_species":
            edit.label = (f"size {name} (type 0x{edit.selector_value:02X})"
                          f" → {edit.new_value:.2f}")
        elif edit.kind == "type_swap":
            tgt = int(edit.new_value) & 0xFF
            tgt_name = TYPE_NAMES.get(tgt, f"0x{tgt:02X}")
            edit.label = (f"type {name} (0x{edit.selector_value:02X}) → "
                          f"{tgt_name} (0x{tgt:02X})")
        elif edit.kind == "hp_slot":
            edit.label = f"hp slot {edit.selector_value} → {int(edit.new_value)}"

    # --- render ---------------------------------------------------------

    def render(self, surface, snapshot):
        surface.fill(C.BG)
        bank = self.reader.edit_bank if self.reader else None
        self._header(surface, snapshot, bank)
        self._picker(surface, bank)
        self._edits(surface, bank)
        self._footer(surface)

    def _header(self, surface, snapshot, bank):
        W.panel(surface, R_HEADER)
        W.text(surface,
               "QUEST PREP — species picker + staged edits",
               (R_HEADER.x + 12, R_HEADER.y + 6), size=16,
               color=C.ACCENT, bold=True)
        master = "ON" if (bank and bank.enabled) else "OFF"
        n_edits = len(bank.edits) if bank else 0
        W.text(surface,
               f"ctx={snapshot.context.value}   area_index={snapshot.area_index}   "
               f"AUTO-APPLY: {master}   {n_edits} edits queued",
               (R_HEADER.x + 12, R_HEADER.y + 28), size=12,
               color=C.TEXT_DIM)

    def _picker(self, surface, bank):
        title = "SPECIES" + (" (selected)" if self.zone == "picker" else "")
        W.panel(surface, R_PICKER, title=title)
        # 'B' input mode banner
        if self._binding_input is not None:
            W.text(surface,
                   f"BIND CUSTOM BYTE: 0x{self._binding_input}__   "
                   f"(hex digits; ESC cancel)",
                   (R_PICKER.x + 12, R_PICKER.y + 30), size=12,
                   color=C.WARN, bold=True)
        row_h = 14
        # Compute visible window (12 rows)
        n = len(PICKER_SPECIES)
        max_rows = (R_PICKER.h - 50) // row_h
        start = max(0, min(self.selected_species - max_rows // 2,
                           n - max_rows))
        for i in range(start, min(n, start + max_rows)):
            name, primary_byte = PICKER_SPECIES[i]
            bind_byte = self.custom_bytes.get(i)
            eff = primary_byte if primary_byte is not None else bind_byte
            y = R_PICKER.y + 50 + (i - start) * row_h
            row = pygame.Rect(R_PICKER.x + 4, y, R_PICKER.w - 8, row_h - 1)
            if i == self.selected_species and self.zone == "picker":
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=2)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=2)
            if eff is not None:
                byte_str = (f"0x{eff:02X}" if primary_byte is not None
                            else f"0x{eff:02X}*")
                color = C.TEXT if primary_byte is not None else C.WARN
            else:
                byte_str = "  ? "
                color = C.PLACEHOLDER
            W.text(surface, byte_str,
                   (row.x + 6, row.y + 1), size=11, color=color, bold=True)
            W.text(surface, name,
                   (row.x + 56, row.y + 1), size=11, color=C.TEXT)

    def _edits(self, surface, bank):
        title = "STAGED EDITS" + (" (selected)" if self.zone == "edits"
                                  else "")
        W.panel(surface, R_EDITS, title=title)
        if bank is None or not bank.edits:
            W.text(surface,
                   "no edits queued — focus PICKER (←), select species, "
                   "ENTER to stage",
                   (R_EDITS.x + 12, R_EDITS.y + 34), size=12,
                   color=C.TEXT_FAINT)
            return
        row_h = 22
        for i, e in enumerate(bank.edits):
            y = R_EDITS.y + 30 + i * row_h
            row = pygame.Rect(R_EDITS.x + 4, y, R_EDITS.w - 8, row_h - 2)
            if i == self.selected_edit and self.zone == "edits":
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=3)
            mark = "[x]" if e.enabled else "[ ]"
            mark_color = C.OK if e.enabled else C.TEXT_FAINT
            W.text(surface, mark,
                   (row.x + 8, row.y + 4), size=12, color=mark_color,
                   bold=True)
            W.text(surface, e.label,
                   (row.x + 38, row.y + 4), size=12, color=C.TEXT)
            W.text(surface,
                   f"applied {len(e.applied_to)}",
                   (row.right - 8, row.y + 4), size=11, color=C.TEXT_FAINT,
                   align="right")

    def _footer(self, surface):
        W.text(surface,
               "←/→ panel   ↑/↓ select   PgUp/Dn jump 10   "
               "ENTER stage/toggle   +/- value   T kind   "
               "X remove   B bind byte   M master",
               (R_FOOTER.x + 4, R_FOOTER.y + 6), size=11,
               color=C.TEXT_FAINT)
