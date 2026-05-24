"""MHFU EU (ULES01213) runtime memory addresses.

Sourced from the project's docs/agent_memory_map.md. Verified for the EU
build only — the JP build (ULJM05500) differs. Data only; no I/O here.
"""

# --- PSP user RAM bounds ---------------------------------------------------
RAM_LO = 0x08000000
RAM_HI = 0x0A000000
CODE_LO = 0x08800000   # rough .text band — used to sanity-check vtables
CODE_HI = 0x08C00000


def in_ram(value: int) -> bool:
    """True if `value` looks like a valid PSP user-RAM pointer."""
    return RAM_LO <= value < RAM_HI


def looks_like_vtable(value: int) -> bool:
    return CODE_LO <= value < CODE_HI


# --- Global scalars --------------------------------------------------------
SCREEN_STATE     = 0x08A8CA48   # u8  0=boot 1=menu/zone-load 2=intro 4=title 17=in-area
SCENE_OBJECT_PTR = 0x08A8C6E0   # u32 sub-screen disambiguator
STAMINA          = 0x08A8CB52   # u16 static stats block
MAP_SECTION      = 0x08A8DE4C   # u8  sub-section ID — see AREA_INDEX below.
                                # Piecewise-constant per *sub*-area; multiple
                                # sub-areas can share a value, so it does NOT
                                # uniquely identify the visible labelled
                                # section. Kept for diagnostics.
# u16 area-index — the real visible-section ID. Pinned 2026-05-24 by
# `tools/discover_map_section_v3.py` with within-section walks: stays
# constant across every in-section sample, flips on every gate cross,
# and yields distinct values for the 6 sections observed (basecamp=98,
# s1=99, s2=95, s4=92, s5=93, s6=100). Four mirrors at 0x090B36DA,
# 0x09999C5C, 0x09A04B6E, 0x09A44EF8 all carry the same value — confirms
# the cell is a real area variable, not random heap noise.
AREA_INDEX       = 0x08B0C7DC   # u16 visible-section index (per-quest map)
QUEST_TIMER      = 0x09A05DD0   # u32 frames remaining (60 fps)
CARVE_COUNT      = 0x09A44C86   # u8  0 alive / 2 at kill / decrements per carve
WEAPON_DRAWN     = 0x090B3A52   # u8  0 sheathed / 1 drawn
# Player HP triple, pinned 2026-05-23 by live damage-diff on popo_quest_idle.
# Adjacent recov / max share a u32 word at 0x090B385C..0x090B385F.
PLAYER_HP        = 0x090B3724   # u16 current HP (green; regenerates from
                                #     the recoverable cap a few seconds after
                                #     a hit). Reaches 0 -> cart.
PLAYER_HP_RECOV  = 0x090B385C   # u16 recoverable HP cap (red ceiling — only
                                #     drops with damage, never recovers).
PLAYER_HP_MAX    = 0x090B385E   # u16 max HP (constant unless armor / meal
                                #     changes it).
ENTITY_ARRAY     = 0x09C1213C   # u32[~21] monster entity pointers

VILLAGE_MAP_SECTION = 35
ENTITY_MAX_SLOTS = 21

# --- Player struct ---------------------------------------------------------
PLAYER_STRUCT  = 0x090BB4C0
PLAYER_VTABLE  = 0x089BAB08
OFF_P_VTABLE   = 0x000          # u32
OFF_P_POSITION = 0x080          # vec3 — local/visual frame, NOT world coords
OFF_P_ROT      = 0x090          # 3x4 f32 rotation matrix
PLAYER_STRUCT_SPAN = 0xC0       # bytes to slurp (covers vtable + pos + rot)

# --- Camera ----------------------------------------------------------------
# The camera target tracks the player's WORLD position and is the usable
# player-world-position oracle (the player-struct vec3 is a local frame).
CAM_TARGET = 0x09998D50         # vec3 look-at == player world pos
CAM_EYE    = 0x09998EC0         # vec3 camera eye
CAM_OFFSET = 0x09998E10         # vec3 eye-target offset (use for view yaw)
CAM_SPAN   = 0x180              # bytes to slurp from CAM_TARGET

# --- Monster entity (offsets from entity_ptr; small-monster layout) --------
OFF_M_VTABLE    = 0x000         # u32
OFF_M_ENTITY_ID = 0x1E4         # u8
OFF_M_TYPE      = 0x1E8         # u8  (unreliable — varies by state)
OFF_M_POSITION  = 0x200         # vec3 world coords (== camera-target frame)
OFF_M_HP        = 0x2E4         # u16
OFF_M_AI_324    = 0x324         # u16
OFF_M_AI_32C    = 0x32C         # u16
OFF_M_AI_BEHAV  = 0x334         # u16
OFF_M_DAMAGE_Q  = 0x3B8         # u32
# Per-entity scale multiplier (f32). Pinned 2026-05-24 (Section 14) by
# diffing 3 popo loads (edge_to_s1, edge_to_s7) against 3 anteka loads
# (edge_to_s6): popos read {0.8, 1.1} per entity (variable), antekas all
# read 1.3 (uniform), Tigrex reads 0.9 (tigrex_s6 dump). Five offsets
# mirror the same value — 0x024, 0x220, 0x224, 0x228, 0x270. 0x024 is
# the canonical source (earliest in struct, set at spawn from quest
# data); 0x220..0x228 looks like the per-axis render-scale vec3
# (x=y=z=scale); 0x270 is likely a cached bounding-sphere radius. HUD
# reads 0x024 as the displayed "Size" value.
OFF_M_SIZE_SCALE = 0x024        # f32 per-entity scale multiplier
MONSTER_STRUCT_SPAN = 0x3C0     # bytes to slurp per monster
# Small-monster vtables. Each *species* in the small class has its own
# vtable — Popo and Anteka share the registry / offset layout but
# different vtable. Add new ones as they are observed live (Velociprey,
# Giaprey, Vespoid, etc.).
MONSTER_VTABLES_SMALL = {
    0x089BC560: "small_popo",      # Popo / Velociprey-class — pinned earlier
    0x089BC074: "small_anteka",    # Anteka — pinned 2026-05-24 Section 14
}
# Back-compat alias — the old single-value name still resolves to the
# Popo vtable so older scripts keep working.
MONSTER_VTABLE_SMALL = 0x089BC560

# Big-monster vtables. Big monsters share the same entity registry
# (0x09C1213C) as small monsters but use distinct classes per species.
# Verified 2026-05-24 by `tools/scan_big_monster.py` on `tigrex_s6` save:
# Tigrex appears in registry slot 1 with vtable below + type byte 0x4B.
# More vtables (Khezu, Kut-Ku, Plesioth, etc.) will be added as those
# species are encountered.
MONSTER_VTABLE_BIG = {
    0x089BB69C: "Tigrex",       # pinned 2026-05-24 — tigrex_s6 save
}


def monster_category(vtable: int) -> str:
    """Classify a monster entity by vtable.

    Returns:
      "small" — small_monster class (Popo, Anteka, Velociprey-class…),
      "big"   — confirmed large-monster vtable (Tigrex, …),
      "unknown" — entity that doesn't match either pool; treat as small
                  in UI but flag for follow-up.
    """
    if vtable in MONSTER_VTABLES_SMALL:
        return "small"
    if vtable in MONSTER_VTABLE_BIG:
        return "big"
    return "unknown"


# --- Player inventory (in-quest bag) — pinned 2026-05-24 -------------------
# Bag base in the player heap (same region as HP triple, stamina, draw flag).
# 24 slots × 4 bytes; each slot is a u32 LE laid out as
#     { item_id: u16, count: u8, flags: u8 }
# An empty slot reads as 0x00000000. Verified by diffing `bag_empty`
# (every slot = 0) against `bag_one_paintball` (slot 0 = 0x00010040,
# i.e. item_id 0x0040 = paintball, count = 1, flags = 0). Cross-checked
# on chest_step2 which shows 17 of the 24 slots populated with known
# small-int IDs (0x002B, 0x0040, 0x0090, 0x0094, 0x0156, etc.) and
# stack counts 1..5.
#
# The earlier `0x08A903E1` candidate (drop-meat test in basecamp) was
# a false positive — that cell sits in the chest's UI display buffer,
# which slides 104 bytes per chest pull. `bag_empty` reads 0 there and
# `bag_one_paintball` reads 3 — so it can't be a bag count.
BAG_BASE = 0x090B39A8
BAG_SLOT_COUNT = 24
BAG_SLOT_STRIDE = 4
BAG_SPAN = BAG_SLOT_COUNT * BAG_SLOT_STRIDE   # 96 bytes
