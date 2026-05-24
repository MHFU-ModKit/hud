"""Monster type-byte -> display name -> icon-slug mapping.

The entity +0x1E8 type byte is known unreliable: it varies by state (a Popo
reads 0x46 or 0x48). So this table is best-effort. Confirmed entries come
from docs/agent_memory_map.md; unknown bytes fall back to a generic label
and no icon. Extend TYPE_NAMES as more type bytes are pinned.
"""

# Confirmed in reverse-engineering work. The type byte at +0x1E8 varies
# by AI state (Popo reads 0x46 OR 0x48), so multiple bytes can map to the
# same species. Add new pairings here as they are observed.
TYPE_NAMES = {
    0x05: "Bullfango",   # confirmed 2026-05-24
    0x13: "Vespoid",     # confirmed 2026-05-24
    0x23: "Giaprey",     # confirmed 2026-05-24, snowy mountains
    0x3D: "Blango",      # confirmed 2026-05-24, snowy mountains
    0x45: "Anteka",      # confirmed 2026-05-24, snowy mountains
    0x46: "Popo",
    0x48: "Popo",
    0x4B: "Tigrex",      # confirmed 2026-05-24
}

# Display name -> preferred icon-asset slug. The asset fetcher writes a
# manifest mapping slug -> filename; this just maps names whose slug differs
# from a plain slugify (most do not, so the table stays small).
NAME_TO_SLUG = {
    "Popo": "popo",
    "Anteka": "anteka",
    "Giaprey": "giaprey",
    "Vespoid": "vespoid",
    "Bullfango": "bullfango",
    "Blango": "blango",
    "Tigrex": "tigrex",
}


def slugify(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_'":
            out.append("_")
    return "_".join(filter(None, "".join(out).split("_")))


def identify(type_byte: int):
    """Return (display_name, icon_slug). icon_slug is None when unknown."""
    name = TYPE_NAMES.get(type_byte)
    if name is None:
        return f"Unknown 0x{type_byte:02X}", None
    return name, NAME_TO_SLUG.get(name, slugify(name))
