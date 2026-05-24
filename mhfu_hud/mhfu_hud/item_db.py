"""Item ID → display name + icon-slug mapping for the in-quest bag.

Pinned by reverse-engineering work on the bag at `0x090B39A8`. Each slot
is `{ item_id u16, count u8, flags u8 }`; this table maps that u16 to
the wiki display name and the slug under `assets/items/`. Extend as
more IDs are confirmed (a slot's ID is "confirmed" once the in-game
item bar / chest tile has been screenshot-matched to the value).

Confirmed (2026-05-24):
- 0x0040 → Paintball. `bag_one_paintball` save shows slot 0 =
  `0x00010040` and the in-game bag has exactly one paintball.

Unconfirmed but observed on real saves (counts / contexts in
`docs/agent_memory_map.md` "Player Inventory"):
- 0x0016, 0x002B, 0x005D, 0x0090, 0x0094, 0x00A2, 0x00A3, 0x00A7,
  0x00B1, 0x00B9, 0x014A, 0x0154, 0x0156, 0x01A9, 0x01AB
"""

# id (u16) -> (display_name, icon_slug)
ITEM_NAMES = {
    0x0040: ("Paintball", "paintball"),     # confirmed 2026-05-24
}


def identify(item_id: int):
    """Return (display_name, icon_slug) for an item ID.

    Falls back to `("0xNNNN", None)` for unknown IDs so the HUD still
    renders the slot with a useful hex placeholder.
    """
    if item_id == 0:
        return ("", None)
    hit = ITEM_NAMES.get(item_id)
    if hit:
        return hit
    return (f"0x{item_id:04X}", None)
