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
    name: str = "Unknown"
    icon_slug: Optional[str] = None
    hp_max: int = 0                 # running max observed this session


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
    map_section: int = -1
    scene_object_ptr: int = 0
    context: Context = Context.DISCONNECTED
    # gameplay
    quest_timer_frames: int = 0
    carve_count: int = 0
    player: PlayerHUD = field(default_factory=PlayerHUD)
    monsters: List[MonsterHUD] = field(default_factory=list)
    camera_target: Vec3 = field(default_factory=Vec3)
    camera_offset: Vec3 = field(default_factory=Vec3)
