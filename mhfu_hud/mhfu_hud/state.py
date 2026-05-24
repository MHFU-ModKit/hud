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
