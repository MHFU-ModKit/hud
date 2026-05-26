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
QUEST_TIMER      = 0x09A05DD0   # u32 frames remaining (30 fps game-logic
                                # rate — PSP runs MH logic at 30 Hz even
                                # though display refreshes at 60 Hz).
                                # Verified 2026-05-24 by slot-9 menu save:
                                # cell read 89880 → 89880/30 = 2996 s =
                                # 49:56 matching the in-game "VerblZeit".
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

# --- Weapon sharpness (Section 16, pinned 2026-05-24) ----------------------
# Discovered by diffing three saves at different sharpness states:
# `sharpness_max` (slot 10) / `sharpness_mid_tier` (slot 9) /
# `sharpness_lowest_tier` (slot 8). The diff hunted u16 cells satisfying
# val10 > val9 > val8 across the 128 KiB player heap region — exactly ONE
# aligned u16 matched: 0x090B4532 with values 150 / 80 / 50, the textbook
# pattern for "max yellow / just-into-orange / just-into-red" on a
# yellow-base weapon. Max-sharpness u16 found at 0x090B3A4C (= 150,
# constant across all three saves). Current tier u8 found at 0x090B3A32
# (2 / 1 / 0 across the three saves — index into red / orange / yellow /
# green / blue / white / purple).
#
# Note: 0x090B4532 was listed in earlier notes as a "wrong HP guess that
# stayed at 149 through ten body-checks" — that observation actually
# CONFIRMS sharpness, because body-checks don't consume sharpness.
SHARPNESS_CURRENT = 0x090B4532  # u16 — current units, decremented per hit
SHARPNESS_MAX     = 0x090B3A4C  # u16 — weapon ceiling, only changes on
                                #       equip / whetstone full-restore
SHARPNESS_TIER    = 0x090B3A32  # u8  — 0=red 1=orange 2=yellow 3=green
                                #       4=blue 5=white 6=purple
SHARPNESS_TIER_NAMES = (
    "Red", "Orange", "Yellow", "Green", "Blue", "White", "Purple",
)

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
# Per-entity scale multiplier (f32). Pinned 2026-05-24 (Section 14)
# at five mirroring offsets: +0x024 + +0x220 + +0x224 + +0x228 + +0x270.
# Section 15.16 (2026-05-24) found a critical asymmetry between them:
#   +0x024  REVERTS within 50 ms when written live. The engine re-derives
#           this cell every frame from another source. Writing it gives
#           only a brief visual flicker.
#   +0x220, +0x224, +0x228 (per-axis render scale vec3) — STICK on write.
#   +0x270 (cached radius) — STICKS on write.
# Practical layout: READ from +0x220 (any of the sticky cells works;
# they share the value at spawn), WRITE the four sticky cells to
# actually change the visible size. OFF_M_SIZE_SCALE retained for
# back-compat with code that just wants ANY representative read.
OFF_M_SIZE_SCALE = 0x220        # f32 — read here (stable, render-active)
OFF_M_SIZE_SOURCE_VOLATILE = 0x024  # do NOT write — engine re-derives
OFF_M_SIZE_SCALE_X = 0x220      # write all four to commit a size change
OFF_M_SIZE_SCALE_Y = 0x224
OFF_M_SIZE_SCALE_Z = 0x228
OFF_M_SIZE_CACHED_RADIUS = 0x270
# AI cells pinned in Sections 18-19 (see CLAUDE.md). All offsets are from
# the entity ptr. Reads always cover up to 0x700 so the AI panel sees every
# documented field in a single region slurp (one PPSSPP round-trip).
OFF_M_HEADING       = 0x010     # vec3 unit-ish heading (rotates toward target)
OFF_M_TRANSFORM_TX  = 0x040     # transform translation row (x,y,z,1)
OFF_M_FRAME_COUNTER = 0x092     # u8  per-entity frame counter
OFF_M_ANIM_PTR      = 0x0B8     # u32 currently-playing anim
OFF_M_BUSY_BITS     = 0x0BC     # u32 flag word — bit 0 = event-busy
OFF_M_ACTION_COUNT  = 0x1A2     # u16 loop bound (engine-only)
OFF_M_SPECIES_TBL   = 0x1AC     # u32 species data ptr (set per area)
OFF_M_PURSUE_TARGET = 0x1C8     # u32 — non-NULL = PURSUE, NULL = FLEE
OFF_M_HERD_RALLY    = 0x1214    # vec3 herd rally world position
OFF_M_HERD_MEMBERS  = 0x1220    # u32[20] herd-member entity ptrs
OFF_M_MODE_BYTE     = 0x29C     # u8 output mode (0..3) — NOT a trigger
OFF_M_STIMULUS_TAG  = 0x322     # u8 written by damage handler
OFF_M_AI_326        = 0x326     # u16 paired "next seed"
OFF_M_FLAG_410      = 0x410     # u32 condition flag word (bit 0x8 = state 1001)
OFF_M_DAMAGE_FLAG   = 0x414     # u32 flag word written by damage handler
                                # (Section 19 cascade — separate from +0x410)
OFF_M_TIMER_624     = 0x624     # u16 countdown timer (scaled by 0x09AACCF8)
OFF_M_TIMER_626     = 0x626     # u16 countdown timer
OFF_M_STRESS_62E    = 0x62E     # u16 stress counter clamped [75, 450]
OFF_M_ACTION_LIST   = 0x640     # u32 per-entity action list ptr
OFF_M_FLEE_FLAG     = 0x6D8     # u8 OUTPUT only — game-written
MONSTER_STRUCT_SPAN = 0x700     # bytes to slurp per monster (covers AI block)
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


# --- AI engine globals (Section 19) ---------------------------------------
# Per-species data table — entries are 0x1D0 bytes, indexed by entity+0x1E8.
# Verified entries: Anteka 0x45 -> 0x09BC04D0, Popo 0x46 -> 0x09BC06A0,
# Tigrex 0x4B -> 0x09BC0FB0. The type-0 entry is a default / dead-area
# template; real per-species CODE override happens via vtable[2]/vt[6].
SPECIES_TABLE_BASE = 0x09BB87C0
SPECIES_TABLE_STRIDE = 0x1D0

# Species data block offsets (within one 0x1D0-byte entry, Section 19e.1).
# All five "data ptrs" point into per-species data blocks, NOT into code
# (Section 19d.1 verified by disasm).
OFF_SD_COOLDOWN      = 0x00    # u32 cooldown-timer table ptr
OFF_SD_WEIGHTS       = 0x04    # u32 probability-weights ptr
OFF_SD_HITZONES      = 0x08    # u32 hitzone damage multipliers ptr
OFF_SD_ACTIONS       = 0x0C    # u32 action descriptor list ptr
OFF_SD_RANGE_PARAMS  = 0x20    # 0x30 bytes of range-param floats (12 floats)
OFF_SD_SCALARS       = 0x60    # 0x10 bytes — 4 scalar floats
OFF_SD_PATTERNS      = 0x70    # u32 attack-pattern / hitbox-volume ptr
OFF_SD_HITBOX        = 0x80    # 0x50 bytes hitbox data
SPECIES_DATA_SPAN    = 0xD0    # bytes we actually read per entry (rounded)

# Engine APIs and dispatchers — wraps + patches operate on these.
ADDR_RAISE_EVENT      = 0x09A677F8   # raise_event(entity, 0, event_id, 0)
ADDR_STATE_LADDER     = 0x09A679D8   # IF/ELSE state-literal writer
ADDR_PROB_LOOKUP_VT8  = 0x08865254   # vtable[8] shared probability lookup
ADDR_AI_DISPATCHER    = 0x09AC5400   # main per-tick dispatcher
ADDR_AI_DISPATCHER_3A = 0x09AC5200   # alt dispatcher for type 0x3A
ADDR_TYPE_3A_ACTLIST  = 0x09BD38F0   # runtime-mutable action-list pool (type 0x3A)
ADDR_TIMER_SCALE      = 0x09AACCF8   # entity-stat scaling helper

# Event ID set observed in popo_ovl_A (Section 19b/c).
EVENT_IDS_OBSERVED = (0x2, 0x3, 0x4, 0x6, 0x8, 0xA, 0xC)

# Big-monster type bytes (Section 14 + 19g.3 list). Type 0x3A is the boss
# class with the alt dispatcher + runtime-mutable +0x640 action list.
TYPE_BYTES_BIG = (0x3A, 0x4B)


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
