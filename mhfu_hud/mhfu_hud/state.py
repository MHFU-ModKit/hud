"""Snapshot dataclasses describing one polled frame of game state.

The reader thread produces a GameSnapshot; the pygame thread consumes it.
A snapshot is plain data and is published by atomic reference swap — the
reader builds a fresh object each cycle and never mutates a live one, so it
is safe to hand across threads.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


@dataclass(frozen=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __repr__(self) -> str:
        return f"({self.x:.1f}, {self.y:.1f}, {self.z:.1f})"


class Context(Enum):
    """Which HUD layout the current game state calls for."""
    DISCONNECTED = "disconnected"   # no PPSSPP / lost connection
    BOOT = "boot"                   # connected, no game / logos
    MENU = "menu"                   # title / main menu
    LOADING = "loading"             # zone transition in progress
    VILLAGE = "village"             # in a village hub
    QUEST = "quest"                 # in a quest / hunting area


@dataclass
class SpeciesData:
    """One per-species entry from SPECIES_TABLE_BASE (0x09BB87C0, stride 0x1D0).
    Read on-demand from the AI_MOD layout, NOT the poll loop — entries don't
    move during a quest, so a one-shot read per type byte is enough."""
    type_byte: int = 0
    entry_addr: int = 0
    cooldown_ptr: int = 0
    weights_ptr: int = 0
    hitzones_ptr: int = 0
    actions_ptr: int = 0
    patterns_ptr: int = 0
    range_params: list = field(default_factory=list)    # 12 floats
    scalars: list = field(default_factory=list)         # 4 floats
    raw: bytes = b""                                    # full 0xD0-byte slice


@dataclass
class MonsterAI:
    """Extended AI block fields populated from the monster region read.
    All fields are read-only diagnostic snapshots; writes go through
    the PinEngine, not this dataclass. Field names mirror the offsets
    documented in CLAUDE.md / docs/POPO_AI_STRUCTURE.md."""
    heading: Vec3 = field(default_factory=Vec3)         # +0x010 vec3
    frame_counter: int = 0                              # +0x092 u8
    anim_ptr: int = 0                                   # +0x0B8 u32
    busy_bits: int = 0                                  # +0x0BC u32
    action_count: int = 0                               # +0x1A2 u16
    species_tbl_ptr: int = 0                            # +0x1AC u32
    pursue_target: int = 0                              # +0x1C8 u32 — non-NULL = pursue
    herd_rally: Vec3 = field(default_factory=Vec3)      # +0x1214 vec3
    herd_members: list = field(default_factory=list)    # +0x1220 u32[20]
    mode_byte: int = 0                                  # +0x29C u8 (0..3)
    stimulus_tag: int = 0                               # +0x322 u8
    seed: int = 0                                       # +0x324 u16
    seed_paired: int = 0                                # +0x326 u16
    ai_param: int = 0                                   # +0x32C u16
    state_byte: int = 0                                 # +0x334 u16 — {1,2,5,10}
    flag_410: int = 0                                   # +0x410 u32
    damage_flag: int = 0                                # +0x414 u32 — damage handler output
    timer_624: int = 0                                  # +0x624 u16
    timer_626: int = 0                                  # +0x626 u16
    stress_62E: int = 0                                 # +0x62E u16 — [75, 450]
    action_list_ptr: int = 0                            # +0x640 u32 — dynamic for type 0x3A
    flee_flag: int = 0                                  # +0x6D8 u8 OUTPUT


@dataclass(frozen=True)
class AIDecision:
    """One AI pick captured from the PRX ai_publish table.

    `cached_at_poll` tags the poll at which we last saw the publish
    table's serial change for this entity. When the game is paused
    (Draw ptr == 0 / frame counter not advancing) the engine stops
    deciding, so the PRX serial freezes — the HUD keeps showing the
    last observed value rather than blanking. `paused` records whether
    the entity is currently considered frozen so the UI can flag it.
    """
    vt8_input: int = 0           # u16
    engine_value: int = 0        # u32 — id (small-shape) OR ptr (true-big)
    serial: int = 0              # PRX-side global serial at last update
    cached_at_poll: int = 0      # HUD poll# when we latched this entry
    paused: bool = False         # True = Draw ptr 0 / frame counter stalled


@dataclass
class MonsterHUD:
    slot: int
    ptr: int
    entity_id: int
    type_byte: int
    pos: Vec3
    hp: int
    ai_behavior: int
    ai_324: int
    ai_32c: int
    vtable: int = 0
    # "small" / "big" / "unknown" — classified by vtable
    # (`addresses.monster_category`). Big monsters get a dedicated roster
    # section + larger map marker; small monsters cluster under the
    # current section.
    category: str = "small"
    name: str = "Unknown"
    icon_slug: Optional[str] = None
    hp_max: int = 0                 # running max observed this session
    # Per-entity scale multiplier (f32 at +0x024). Set when monster
    # spawns; popos in {0.8, 1.1}, antekas uniformly 1.3, Tigrex 0.9 —
    # see addresses.OFF_M_SIZE_SCALE for the discovery notes. Renders
    # next to HP / name in the monster panels.
    size_scale: Optional[float] = None
    ai: Optional[MonsterAI] = None  # populated when the AI block is parsed
    # Engine's currently-bound Draw pointer (entity+0x008). 0 means
    # paused or not-currently-rendered; the AI-decision panel uses this
    # plus the publish-table serial to decide whether to display the
    # live read or the last cached pick.
    draw_ptr: int = 0
    # Last AI pick published by the PRX ai_publish mod. None when the
    # PRX hasn't been seen yet (no magic at AI_PUBLISH_BASE) OR when
    # the entity has not yet had a vt[8] decision since spawn.
    last_ai: Optional[AIDecision] = None
    # Short rolling history of decisions for the AI_DIAG panel.
    ai_history: list = field(default_factory=list)   # newest-last


@dataclass(frozen=True)
class BagSlot:
    """One slot of the in-quest player bag.

    Layout: u32 LE at `BAG_BASE + idx*4` = { item_id u16, count u8, flags u8 }.
    Empty slots read as raw=0, item_id=0, count=0.
    """
    idx: int
    item_id: int
    count: int
    flags: int

    @property
    def empty(self) -> bool:
        return self.item_id == 0 and self.count == 0


@dataclass
class PlayerHUD:
    loaded: bool = False
    pos_world: Vec3 = field(default_factory=Vec3)   # camera-target frame
    pos_local: Vec3 = field(default_factory=Vec3)   # player-struct frame
    facing_rad: Optional[float] = None              # approx — from rot matrix
    hp: Optional[int] = None              # current green HP
    hp_recov: Optional[int] = None        # recoverable cap (red bar ceiling)
    hp_max: int = 0                       # max HP
    stamina: Optional[int] = None
    stamina_max: int = 0
    weapon_drawn: Optional[bool] = None
    # Sharpness (Section 16 — pinned 2026-05-24). `sharpness` is the live
    # unit counter, `sharpness_max` the weapon's ceiling, `sharpness_tier`
    # the index into addresses.SHARPNESS_TIER_NAMES (0=red .. 6=purple).
    sharpness: Optional[int] = None
    sharpness_max: Optional[int] = None
    sharpness_tier: Optional[int] = None
    # Full in-quest bag (Section 12 — pinned 2026-05-24). 24 entries
    # always present; empty slots have item_id=0, count=0.
    bag: List["BagSlot"] = field(default_factory=list)


@dataclass
class GameSnapshot:
    # connection / meta
    connected: bool = False
    status_text: str = "starting…"
    game_title: str = ""
    poll_latency_ms: float = 0.0
    poll_count: int = 0
    timestamp: float = 0.0
    # raw oracles
    screen_state: int = -1
    map_section: int = -1                # raw byte at 0x08A8DE4C — sub-section
    area_index: int = -1                 # u16 at 0x08B0C7DC — the real
                                         # visible-section index. Maps to
                                         # the labelled section via the
                                         # learnt table (see Calibration).
    scene_object_ptr: int = 0
    context: Context = Context.DISCONNECTED
    # Tracked visible section. Primary source: area_index lookup. Falls
    # back to gate-detected anchor snap when area_index is unmapped.
    tracked_section: Optional[int] = None
    tracked_section_source: str = "init"  # "area_index"|"transition"|"override"|"init"
    # gameplay
    quest_timer_frames: int = 0
    carve_count: int = 0
    player: PlayerHUD = field(default_factory=PlayerHUD)
    monsters: List[MonsterHUD] = field(default_factory=list)
    camera_target: Vec3 = field(default_factory=Vec3)
    camera_offset: Vec3 = field(default_factory=Vec3)
