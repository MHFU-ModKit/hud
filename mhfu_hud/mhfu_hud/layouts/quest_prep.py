"""Quest-prep HUD layout (Section 15.5).

Active when the player is still in the village but has already talked
to the quest giver and selected a quest — at that point the engine
prefetches the map / spawn data so we can preview (and eventually
modify) the spawn list before the quest actually starts.

Display strategy:
  - Header strip: which quest is loaded (where known), what map.
  - Spawn-record list: every 64-byte record in the spawn block; flag
    populated vs empty; show the bytes that look like type / size.
  - Hint footer: which keys edit, plus a 'discovery WIP' caveat for
    fields whose offsets inside the 64-byte record are not yet pinned.

This is read-only in its first pass — once the field offsets inside
the 64-byte record are pinned (size_mod, monster_type, etc.) the
editor keys will write directly to memory.
"""

import struct

import pygame

from .. import widgets as W
from ..theme import C, CANVAS_W, CANVAS_H
from .base import Layout


# Spawn block — discovered in Section 15.4 via diff of the three
# quest_prep saves. Records are 64 bytes; first u32 is a header tag.
SPAWN_BLOCK_BASE = 0x09A0B600
SPAWN_BLOCK_SPAN = 0x400           # 16 records = 1024 bytes
SPAWN_RECORD_SIZE = 0x40
SPAWN_RECORD_COUNT = SPAWN_BLOCK_SPAN // SPAWN_RECORD_SIZE

# Header u32 values observed:
#   0x10000003  empty / default slot
#   0x10000000  populated slot (carries monster spawn data)
HEADER_EMPTY = 0x10000003
HEADER_POPULATED = 0x10000000

R_HEADER  = pygame.Rect(12, 12, CANVAS_W - 24, 56)
R_LEGEND  = pygame.Rect(12, 76, CANVAS_W - 24, 28)
R_LIST    = pygame.Rect(12, 112, CANVAS_W - 24, CANVAS_H - 112 - 56)
R_FOOTER  = pygame.Rect(12, CANVAS_H - 40, CANVAS_W - 24, 28)


class QuestPrepLayout(Layout):
    name = "quest_prep"

    def __init__(self, assets, calib, reader=None):
        super().__init__(assets, calib)
        self.reader = reader
        self.selected = 0       # which record row is hovered

    def handle_key(self, key, snapshot) -> bool:
        # Cycle the selected spawn record. Editing keys (write into
        # memory) come in a follow-up once the field offsets are
        # pinned.
        if key == pygame.K_DOWN:
            self.selected = (self.selected + 1) % SPAWN_RECORD_COUNT
            return True
        if key == pygame.K_UP:
            self.selected = (self.selected - 1) % SPAWN_RECORD_COUNT
            return True
        return False

    def render(self, surface, snapshot):
        surface.fill(C.BG)
        self._header(surface, snapshot)
        self._legend(surface)
        self._records(surface, snapshot)
        self._footer(surface)

    # --- subpanels ---------------------------------------------------------

    def _header(self, surface, snapshot):
        W.panel(surface, R_HEADER)
        W.text(surface, "QUEST PREP — pre-quest spawn editor",
               (R_HEADER.x + 12, R_HEADER.y + 8), size=16,
               color=C.ACCENT, bold=True)
        ai = snapshot.area_index
        ctx = snapshot.context.value
        W.text(surface,
               f"context={ctx}   area_index={ai}   "
               f"screen_state={snapshot.screen_state}",
               (R_HEADER.x + 12, R_HEADER.y + 32), size=12,
               color=C.TEXT_DIM)

    def _legend(self, surface):
        W.text(surface,
               f"spawn block 0x{SPAWN_BLOCK_BASE:08X} .. "
               f"0x{SPAWN_BLOCK_BASE + SPAWN_BLOCK_SPAN:08X}  "
               f"({SPAWN_RECORD_COUNT} records × 0x40 bytes)",
               (R_LEGEND.x + 4, R_LEGEND.y + 4), size=12, color=C.TEXT)
        W.text(surface,
               "header 0x10000003 = empty   header 0x10000000 = populated",
               (R_LEGEND.x + 4, R_LEGEND.y + 18), size=11,
               color=C.TEXT_FAINT)

    def _records(self, surface, snapshot):
        W.panel(surface, R_LIST, title="SPAWN RECORDS")
        # Pull the block from the live game on-demand. Reader holds
        # the connection; we go through reader._client only when it's
        # present. Falls back to "block not available" if not.
        block = self._read_block()
        row_h = (R_LIST.h - 28) // SPAWN_RECORD_COUNT
        for i in range(SPAWN_RECORD_COUNT):
            y = R_LIST.y + 28 + i * row_h
            row = pygame.Rect(R_LIST.x + 4, y, R_LIST.w - 8, row_h - 2)
            if i == self.selected:
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=3)
            addr = SPAWN_BLOCK_BASE + i * SPAWN_RECORD_SIZE
            if block is None:
                W.text(surface, f"#{i:02d}  0x{addr:08X}  "
                       f"(spawn block not read yet)",
                       (row.x + 8, row.y + 4), size=11,
                       color=C.TEXT_FAINT)
                continue
            rec = block[i * SPAWN_RECORD_SIZE:(i + 1) * SPAWN_RECORD_SIZE]
            header = struct.unpack_from("<I", rec, 0)[0]
            if header == HEADER_EMPTY:
                label, label_color = "EMPTY", C.TEXT_FAINT
            elif header == HEADER_POPULATED:
                label, label_color = "POPULATED", C.OK
            else:
                label, label_color = f"hdr=0x{header:08X}", C.WARN
            # First 16 bytes summary — gives the user enough to see
            # which records have monster-type-byte (0x4B = Tigrex,
            # 0x46/0x48 = Popo, 0x45 = Anteka) without dumping all 64.
            hex16 = " ".join(f"{rec[j]:02X}" for j in range(16))
            W.text(surface, f"#{i:02d}  0x{addr:08X}  ",
                   (row.x + 8, row.y + 4), size=11, color=C.TEXT)
            W.text(surface, label,
                   (row.x + 168, row.y + 4), size=11, color=label_color,
                   bold=True)
            W.text(surface, hex16,
                   (row.x + 260, row.y + 4), size=11, color=C.TEXT_DIM)

    def _footer(self, surface):
        W.text(surface,
               "↑ / ↓  select record    TAB  back to LIVE    "
               "edit keys arriving once size/type field offsets are pinned",
               (R_FOOTER.x + 4, R_FOOTER.y + 6), size=11, color=C.TEXT_FAINT)

    # --- helpers -----------------------------------------------------------

    def _read_block(self):
        """Return the 1 KiB spawn block from live RAM, or None."""
        if self.reader is None or self.reader._client is None:
            return None
        try:
            return self.reader._client.read_memory(SPAWN_BLOCK_BASE,
                                                   SPAWN_BLOCK_SPAN)
        except Exception:
            return None
