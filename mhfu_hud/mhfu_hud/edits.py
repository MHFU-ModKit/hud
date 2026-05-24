"""Staged-edit engine for the HUD.

Tracks user-authored edits that should be applied to monster entities
as soon as they spawn. The user creates edits in the village
(QUEST-PREP tab) before the quest starts; once the player walks into
the quest area and entities populate the registry at 0x09C1213C, the
HUD writes the per-entity overrides directly into RAM.

Edit kinds (Section 15.14):
  - SizeBySpecies   for type_byte=X: write f32 SCALE to entity+0x024
  - SizeBySlot      for registry slot=N: write f32 SCALE
  - TypeSwap        for type_byte=X: write u8 TARGET to entity+0x1E8
  - HpBySlot        for registry slot=N: write u16 HP to entity+0x2E4

The edits are stored as a small list; on every poll the apply loop
iterates the live monsters and applies any match. Each edit carries
an `applied_to: set[ptr]` so an idempotent edit doesn't keep writing
back when the user has manually further tweaked the value live.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class StagedEdit:
    """One pending edit. Each instance owns its own `applied_to` set so
    re-applying after a quest reload (when entity_ptr addresses can be
    recycled) works correctly."""
    kind: str                  # 'size_species' | 'size_slot' | 'type_swap' | 'hp_slot'
    selector_value: int        # type_byte for species/type_swap, slot index for *_slot
    new_value: float           # scale (f32) for size; otherwise u16/u8 cast to int
    enabled: bool = True
    label: str = ""            # one-line description for the UI
    applied_to: Set[int] = field(default_factory=set)

    def reset_applied(self):
        self.applied_to.clear()


class EditBank:
    """All staged edits the user has created. Lives in the HUD app, not
    the reader, so the reader stays read-only by default and writes only
    when the bank's apply() is called from the layout."""

    def __init__(self):
        self.edits: list[StagedEdit] = []
        self.enabled: bool = True   # master kill-switch

    def add(self, edit: StagedEdit):
        self.edits.append(edit)

    def remove(self, idx: int):
        if 0 <= idx < len(self.edits):
            self.edits.pop(idx)

    def toggle(self, idx: int):
        if 0 <= idx < len(self.edits):
            self.edits[idx].enabled = not self.edits[idx].enabled

    def toggle_master(self):
        self.enabled = not self.enabled

    def reset_applied(self):
        """Forget which entities have already been written to. Call
        this on quest-area entry (screen_state 17 after a load) so
        the same edits re-apply to the new entity instances."""
        for e in self.edits:
            e.reset_applied()

    def apply_to_monsters(self, client, monsters, addresses) -> int:
        """Apply enabled edits to the live monster list. Returns the
        number of writes performed."""
        if not self.enabled or client is None or not self.edits:
            return 0
        writes = 0
        for m in monsters:
            for e in self.edits:
                if not e.enabled:
                    continue
                if m.ptr in e.applied_to:
                    continue
                target_addr = None
                value_to_write = None
                if e.kind == "size_species" and m.type_byte == e.selector_value:
                    target_addr = m.ptr + addresses.OFF_M_SIZE_SCALE
                    try:
                        client.write_f32(target_addr, float(e.new_value))
                        # Mirror cells +0x220..+0x228 are derived per-frame
                        # by the engine from +0x024 (Section 14 finding) so
                        # we only need to write the source. The +0x270
                        # cached radius gets recomputed too.
                        writes += 1
                        e.applied_to.add(m.ptr)
                    except Exception:
                        pass
                elif e.kind == "size_slot" and m.slot == e.selector_value:
                    try:
                        client.write_f32(m.ptr + addresses.OFF_M_SIZE_SCALE,
                                         float(e.new_value))
                        writes += 1
                        e.applied_to.add(m.ptr)
                    except Exception:
                        pass
                elif e.kind == "type_swap" and m.type_byte == e.selector_value:
                    try:
                        client.write_u8(m.ptr + addresses.OFF_M_TYPE,
                                        int(e.new_value) & 0xFF)
                        writes += 1
                        e.applied_to.add(m.ptr)
                    except Exception:
                        pass
                elif e.kind == "hp_slot" and m.slot == e.selector_value:
                    try:
                        client.write_u16(m.ptr + addresses.OFF_M_HP,
                                         int(e.new_value) & 0xFFFF)
                        writes += 1
                        e.applied_to.add(m.ptr)
                    except Exception:
                        pass
        return writes
