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
MAP_SECTION      = 0x08A8DE4C   # u8  current area id (village=35, snow sub-areas 0..3)
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
MONSTER_STRUCT_SPAN = 0x3C0     # bytes to slurp per monster
MONSTER_VTABLE_SMALL = 0x089BC560
