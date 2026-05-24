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

# Ordered list for the QUEST-PREP species picker (Section 15.19).
# Each entry: (display_name, primary_type_byte). Primary = the byte the
# user-staged 'size_species' edit will key off. For Popo we use 0x46
# (the most-common idle byte); a parallel edit for 0x48 (combat state)
# can be staged manually if needed.
#
# Species without a confirmed type byte are included with a None byte
# so the picker can display them; the user can then either pick one
# of the confirmed entries or input a custom byte via the X-byte
# editor. Best-effort labels from MH series knowledge.
PICKER_SPECIES = [
    # confirmed (from runtime RE)
    ("Bullfango",  0x05),
    ("Vespoid",    0x13),
    ("Giaprey",    0x23),
    ("Blango",     0x3D),
    ("Anteka",     0x45),
    ("Popo",       0x46),
    ("Tigrex",     0x4B),
    # known small monsters in the game — type bytes TBD; user can
    # supply a custom byte via 'B' hotkey if they want to test these
    ("Velociprey", None),
    ("Velocidrome", None),
    ("Genprey",    None),
    ("Gendrome",   None),
    ("Ioprey",     None),
    ("Iodrome",    None),
    ("Giadrome",   None),
    ("Hornetaur",  None),
    ("Bulldrome",  None),
    ("Felyne",     None),
    ("Melynx",     None),
    ("Conga",      None),
    ("Remobra",    None),
    ("Cephalos",   None),
    # known large monsters
    ("Yian Kut-Ku", None),
    ("Yian Garuga", None),
    ("Khezu",      None),
    ("Rathian",    None),
    ("Rathalos",   None),
    ("Cephadrome", None),
    ("Diablos",    None),
    ("Monoblos",   None),
    ("Plesioth",   None),
    ("Gravios",    None),
    ("Basarios",   None),
    ("Daimyo Hermitaur", None),
    ("Shogun Ceanataur", None),
    ("Congalala",  None),
    ("Blangonga",  None),
    ("Kirin",      None),
    ("Gypceros",   None),
    ("Lao-Shan Lung", None),
    ("Shen Gaoren", None),
    ("Rajang",     None),
    ("Nargacuga",  None),
    ("Akantor",    None),
    ("Ukanlos",    None),
    ("Espinas",    None),
    ("Berukyurosu", None),
]

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
