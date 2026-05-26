"""Full-page live AI editor (Section 19f.4).

Three vertical columns:
  ROSTER  — every monster in the entity registry. ↑/↓ selects.
  ENTITY  — editable AI cells on the selected entity (+0x1C8 pursue,
            +0x324 seed, +0x29C mode, +0x410 flag, +0x624/626 timers,
            +0x62E stress, +0x334 state, size mirrors). Each row can
            be PINNED — the PinEngine writes the value back at 30 Hz
            so the engine can't clobber it.
  ACTIONS — read-only species-data ptrs (cooldown / weights / hitzones /
            actions / patterns + range scalars) plus action buttons
            (raise state literal, force flee/pursue toggle, clear pins).

The editor never calls 0x09A677F8 directly — calling a function from
the PPSSPP debugger socket requires a code-cave stub + breakpoint
swap (Section 19d.5 mechanism). Instead, the "raise state literal"
action writes the pair (+0x324, +0x326) = (literal, literal+100)
directly, achieving the same observable effect on the next AI tick.
"""

from __future__ import annotations
import math
from typing import Optional

import pygame

from .. import addresses as A, widgets as W
from ..theme import C, CANVAS_W, CANVAS_H
from .base import Layout

R_HEADER  = pygame.Rect(8, 8, CANVAS_W - 16, 60)   # +16 for motion cheat-sheet line
R_ROSTER  = pygame.Rect(8, 76, 220, 296)
R_ENTITY  = pygame.Rect(236, 76, 392, 296)
R_ACTIONS = pygame.Rect(636, 76, CANVAS_W - 644, 296)
R_PINS    = pygame.Rect(8, 380, CANVAS_W - 16, CANVAS_H - 388)


# State literals written into (+0x324, +0x326) by the 0x09A679D8 ladder
# (Section 18 / 19d.4). Pairs are (seed, seed_paired).
STATE_LITERALS = (
    ("idle/alert",      24),
    ("eat 1001",      1001),
    ("look-around 21",  21),
    ("stress 431",     431),
    ("stress 403",     403),
    ("stress 1017",   1017),
)


# Known-good preset values per editable field. Each entry: (label, value).
# Cycling on a field walks this list — typed adjust still works for ad-hoc
# values. Labels are what shows up in the tooltip + the "preset N/M" badge.
# Values marked PLAYER_PTR are filled in at write time with PLAYER_STRUCT.
_PLAYER_PTR = -1     # sentinel — resolved at write time to A.PLAYER_STRUCT
FIELD_PRESETS = {
    "pursue": (
        ("0 (no herd follow)", 0),
        ("herd→player struct", _PLAYER_PTR),
    ),
    "head_x": (
        ("0.0 (centre)",  0.0),
        ("+1.0 east",     1.0),
        ("-1.0 west",    -1.0),
        ("+0.5",          0.5),
        ("-0.5",         -0.5),
    ),
    "head_y": (
        ("0.0 (flat)",    0.0),
        ("+1.0 up",       1.0),
        ("-1.0 down",    -1.0),
    ),
    "head_z": (
        ("0.0 (centre)",  0.0),
        ("+1.0 south",    1.0),
        ("-1.0 north",   -1.0),
        ("+0.5",          0.5),
        ("-0.5",         -0.5),
    ),
    # +0x324 — engine writes the next anim-graph ID here every frame as
    # part of the wander/AI loop. Force-write nudges the NEXT anim
    # selection; the engine overwrites it on the following tick.
    # The 6 stress literals from the 0x09A679D8 ladder are still useful
    # as one-shot biases (R-key, NOT a stable pin).
    "anim_id": (
        # Observed live 2026-05-26 in slot 9 popo diagnostic.
        ("1011 walk-forward",   1011),  # the MOTION anim (with state=5)
        ("1004 eat",            1004),
        ("1005 look-around",    1005),
        ("1006 turn",           1006),
        ("1022 hit-react",      1022),
        # State-ladder literals (work as anim bias one-shots, do NOT pin)
        ("24 stress-bias",        24),
        ("1001 ladder-literal", 1001),
        ("zero (reset)",           0),
    ),
    "anim_next": (
        ("1111 (walk pair)",   1111),  # 1011 + 100
        ("1104 (eat pair)",    1104),
        ("1105 (look pair)",   1105),
        ("zero (reset)",          0),
    ),
    "state": (
        ("5 LOCOMOTION (MOVE)",  5),   # only state that produces motion
        ("1 alert (halt)",       1),
        ("2 eat (halt)",         2),
        ("10 look-around (halt)", 10),
    ),
    "mode": (
        ("0 default",          0),
        ("1",                  1),
        ("2",                  2),
        ("3",                  3),
    ),
    "stimulus": (
        ("0 none",          0x00),
        ("0x28 (observed)", 0x28),
        ("0x9C (observed)", 0x9C),
    ),
    "flag410": (
        ("0x00 cleared",   0x00),
        ("0x01 base",      0x01),
        ("0x08 (-> 1001)", 0x08),
        ("0x09 base+1001", 0x09),
        ("0x0F all-low",   0x0F),
    ),
    # +0x414 damage flag word — Section 19 damage handler writes it
    # alongside +0x322 stim + +0x2E4 HP. Exact bit meanings unknown
    # until observed on a real hit. Defaults below are guesses; observe
    # the LIVE value in the panel after attacking a popo, then add the
    # observed value to this preset list.
    "dmg_flag": (
        ("0x00 cleared", 0x00),
        ("0x01",         0x01),
        ("0x02",         0x02),
        ("0x04",         0x04),
        ("0x10",         0x10),
        ("0x40 (guess)", 0x40),
        ("0xFF all-low", 0xFF),
    ),
    "timer624": (
        ("0",                 0),
        ("3600 (120s @30)",  3600),
        ("6000 (×2/3)",      6000),
        ("9000 (300s base)", 9000),
        ("13500 (×1.5)",     13500),
        ("18000 (600s)",     18000),
    ),
    "timer626": (
        ("0",                 0),
        ("3600 (120s @30)",  3600),
        ("6000 (×2/3)",      6000),
        ("9000 (300s base)", 9000),
        ("13500 (×1.5)",     13500),
        ("18000 (600s)",     18000),
    ),
    "stress": (
        ("75 min",            75),
        ("150",              150),
        ("300",              300),
        ("450 max",          450),
    ),
    "ai_param": (
        ("0 typical",          0),
        ("1",                  1),
        ("2",                  2),
        ("5",                  5),
    ),
    "size": (
        ("0.50 tiny",       0.50),
        ("0.80 small popo", 0.80),
        ("1.00 default",    1.00),
        ("1.10 large popo", 1.10),
        ("1.30 anteka",     1.30),
        ("2.00 GIANT",      2.00),
        ("3.00 HUGE",       3.00),
    ),
}

# Short tooltip strings (max ~80 char each row, two rows tops). Drawn next
# to the cursor when hovering an entity-field row.
FIELD_TOOLTIPS = {
    "pursue":   ("+0x1C8  HERD-follow target ptr (NOT player-pursue!).",
                 "Diagnostic 2026-05-26: slots 2,3 point at slots 1,2 (chain)."),
    "head_x":   ("+0x010  heading vector X-component (motion direction).",
                 "Engine reads each frame to drive position. Pin to steer."),
    "head_y":   ("+0x014  heading Y. Usually ~0 on flat terrain.",
                 "Non-zero may produce climbing/falling motion."),
    "head_z":   ("+0x018  heading vector Z-component (motion direction).",
                 "Pin head_x + head_z to a unit vec to force a heading."),
    "anim_id":  ("+0x324  next-anim ID. 1011 = walk-forward in heading dir.",
                 "1004 eat, 1005 look, 1006 turn. Pin 1011 + state=5 for motion."),
    "anim_next":("+0x326  paired 'after-next' anim ID (engine writes anim+100).",
                 "Set together with +0x324 by the state-literal ladder."),
    "state":    ("+0x334  motion GATE. 5=locomotion (the only moving state).",
                 "Pin 1/2/10 to HALT any monster. Pair with +0x1C8 for PURSUE/FLEE."),
    "mode":     ("+0x29C  output mode byte (0..3).",
                 "OUTPUT only — force-writing did not trigger ladder (19.2)."),
    "stimulus": ("+0x322  stimulus tag from damage_info.+0x3A.",
                 "Damage cascade output. Hit observed: 0xC1 (193)."),
    "flag410":  ("+0x410  condition flag word (state-literal ladder).",
                 "Bit 0x8 → state literal 1001. NOT the damage flag (see +0x414)."),
    "dmg_flag": ("+0x414  damage flag word (Section 19 cascade).",
                 "Written by damage handler alongside +0x322 + HP. Value TBD."),
    "timer624": ("+0x624  countdown timer (ticks @ 30 Hz).",
                 "Init scaled by 0x09AACCF8: ×1.5 (stat 0xA6) / ×2/3 (0xA7)."),
    "timer626": ("+0x626  countdown timer (same scaling as +0x624).",
                 "Used for the secondary stress timer."),
    "stress":   ("+0x62E  stress counter, clamped [75, 450].",
                 "Higher = more aggressive stress-response branching."),
    "ai_param": ("+0x32C  AI param. Typically 0 on idle popos.",
                 "Function not yet decoded."),
    "size":     ("Per-axis render-scale mirrors (+0x220 ×3 + +0x270).",
                 "Engine reads from these for hitbox + draw size."),
}


# Per-row spec for the entity column. Each row is one writable cell.
# (key, offset, kind, label, step, coarse_step, vmin, vmax)
# kind="size" means write all four sticky size mirrors (Section 15.16);
# offset is ignored, the four mirror offsets are used instead.
ENTITY_FIELDS = (
    ("pursue",    A.OFF_M_PURSUE_TARGET, "u32",  "+0x1C8 pursue(herd)", 0, 0, 0, 0xFFFFFFFF),
    ("state",     A.OFF_M_AI_BEHAV,      "u16",  "+0x334 state",      1, 1,   0, 0xFFFF),
    ("anim_id",   A.OFF_M_AI_324,        "u16",  "+0x324 anim id",    1, 100, 0, 0xFFFF),
    ("anim_next", A.OFF_M_AI_326,        "u16",  "+0x326 next anim",  1, 100, 0, 0xFFFF),
    ("head_x",    A.OFF_M_HEADING,       "f32",  "+0x010 head.x",    0.1, 0.5, -1.0, 1.0),
    ("head_y",    A.OFF_M_HEADING + 4,   "f32",  "+0x014 head.y",    0.1, 0.5, -1.0, 1.0),
    ("head_z",    A.OFF_M_HEADING + 8,   "f32",  "+0x018 head.z",    0.1, 0.5, -1.0, 1.0),
    ("mode",      A.OFF_M_MODE_BYTE,     "u8",   "+0x29C mode",       1, 1,   0, 3),
    ("stimulus",  A.OFF_M_STIMULUS_TAG,  "u8",   "+0x322 stim",       1, 1,   0, 0xFF),
    ("flag410",   A.OFF_M_FLAG_410,      "u32",  "+0x410 flag",       1, 8,   0, 0xFFFFFFFF),
    ("dmg_flag",  A.OFF_M_DAMAGE_FLAG,   "u32",  "+0x414 dmg flag",   1, 8,   0, 0xFFFFFFFF),
    ("timer624",  A.OFF_M_TIMER_624,     "u16",  "+0x624 timer",      10, 1000, 0, 0xFFFF),
    ("timer626",  A.OFF_M_TIMER_626,     "u16",  "+0x626 timer",      10, 1000, 0, 0xFFFF),
    ("stress",    A.OFF_M_STRESS_62E,    "u16",  "+0x62E stress",     5, 50,   75, 450),
    ("ai_param",  A.OFF_M_AI_32C,        "u16",  "+0x32C param",      1, 16,   0, 0xFFFF),
    ("size",      0,                     "size", "size mirrors",      0.05, 0.5, 0.05, 5.0),
)


def _player_struct_ptr_const() -> int:
    """The pursue target for the 'force pursue' button writes the player
    struct address into +0x1C8. The engine just treats this as 'pursue
    a non-NULL target' (Section 19.x verified)."""
    return A.PLAYER_STRUCT


class AIModLayout(Layout):
    name = "ai_mod"

    def __init__(self, assets, calib, reader=None, pin_engine=None):
        super().__init__(assets, calib)
        self.reader = reader
        self.pins = pin_engine
        # Focus zone — drives which column ↑/↓ + ENTER act on.
        self.focus = "fields"          # "roster" | "fields" | "actions"
        self.sel_entity = 0            # index into snapshot.monsters
        self.sel_field = 0             # index into ENTITY_FIELDS
        self.sel_action = 0            # index into ACTION_ROWS (computed)
        self.literal_idx = 0           # index into STATE_LITERALS
        # Working values shown in the editor. These are the user's
        # intended write values; pressing SPACE pins them. + / - adjusts.
        # Keyed by (entity_ptr, field_key). Initialised on first view of
        # a field from the live cell so the UI starts at the real value.
        self._values: dict[tuple[int, str], int | float] = {}
        # Current preset index per (entity_ptr, field_key). Initialised
        # lazily — first ,/. press starts at index 0 unless the live
        # value matches an existing preset, in which case it snaps to that.
        self._preset_idx: dict[tuple[int, str], int] = {}
        # Species data cache — keyed by type_byte. One-shot read on first
        # observation; species table entries don't move during a quest.
        self._species_cache: dict[int, dict] = {}
        # Mouse position in canvas coords, updated by handle_motion. Used
        # by _entity to figure out which field row a tooltip should attach to.
        self._mouse_canvas: Optional[tuple[float, float]] = None

    # --- input ----------------------------------------------------------

    def handle_key(self, key, snap) -> bool:
        monsters = snap.monsters
        # Focus cycling — LEFT / RIGHT walks the three columns.
        if key == pygame.K_LEFT:
            self.focus = {"actions": "fields", "fields": "roster",
                          "roster": "actions"}[self.focus]
            return True
        if key == pygame.K_RIGHT:
            self.focus = {"roster": "fields", "fields": "actions",
                          "actions": "roster"}[self.focus]
            return True
        # X — clear all pins (works from any focus).
        if key == pygame.K_x and self.pins is not None:
            self.pins.clear()
            return True
        if not monsters:
            # Nothing selectable; let the key fall through (e.g. TAB
            # to top-level tab cycle).
            return False
        # Roster column
        if self.focus == "roster":
            return self._roster_key(key, monsters)
        # Field column
        if self.focus == "fields":
            return self._fields_key(key, monsters)
        # Actions column
        return self._actions_key(key, monsters)

    def _roster_key(self, key, monsters) -> bool:
        n = len(monsters)
        if key == pygame.K_UP:
            self.sel_entity = (self.sel_entity - 1) % n
            return True
        if key == pygame.K_DOWN:
            self.sel_entity = (self.sel_entity + 1) % n
            return True
        if key == pygame.K_RETURN:
            self.focus = "fields"
            return True
        if key == pygame.K_RIGHTBRACKET:
            self.sel_entity = (self.sel_entity + 1) % n
            return True
        if key == pygame.K_LEFTBRACKET:
            self.sel_entity = (self.sel_entity - 1) % n
            return True
        return False

    def _fields_key(self, key, monsters) -> bool:
        if not (0 <= self.sel_entity < len(monsters)):
            return False
        m = monsters[self.sel_entity]
        n = len(ENTITY_FIELDS)
        if key == pygame.K_UP:
            self.sel_field = (self.sel_field - 1) % n
            return True
        if key == pygame.K_DOWN:
            self.sel_field = (self.sel_field + 1) % n
            return True
        spec = ENTITY_FIELDS[self.sel_field]
        fkey, off, kind, _label, step, coarse, vmin, vmax = spec
        mods = pygame.key.get_mods()
        big = bool(mods & (pygame.KMOD_SHIFT | pygame.KMOD_CTRL))
        if key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self._adjust_field(m, spec, +(coarse if big else step))
            return True
        if key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._adjust_field(m, spec, -(coarse if big else step))
            return True
        if key in (pygame.K_SPACE, pygame.K_RETURN):
            self._toggle_pin(m, spec)
            return True
        # F — force flee/pursue toggle on selected entity (only meaningful
        # for the pursue field; still works from any field row).
        if key == pygame.K_f:
            self._force_pursue_toggle(m)
            return True
        # R — raise the currently-selected state literal on this entity.
        if key == pygame.K_r:
            self._raise_state_literal(m)
            return True
        # , / .  cycle the per-FIELD preset on the selected row (focus=fields).
        # The state-literal cycle stays on the ACTIONS column (see below)
        # so the two cycles don't fight when both columns want input.
        if key == pygame.K_PERIOD:
            self._cycle_preset(m, spec, +1)
            return True
        if key == pygame.K_COMMA:
            self._cycle_preset(m, spec, -1)
            return True
        return False

    def _actions_key(self, key, monsters) -> bool:
        if not (0 <= self.sel_entity < len(monsters)):
            return False
        m = monsters[self.sel_entity]
        if key == pygame.K_UP:
            self.sel_action = (self.sel_action - 1) % self.ACTION_COUNT
            return True
        if key == pygame.K_DOWN:
            self.sel_action = (self.sel_action + 1) % self.ACTION_COUNT
            return True
        if key == pygame.K_PERIOD:
            self.literal_idx = (self.literal_idx + 1) % len(STATE_LITERALS)
            return True
        if key == pygame.K_COMMA:
            self.literal_idx = (self.literal_idx - 1) % len(STATE_LITERALS)
            return True
        if key in (pygame.K_RETURN, pygame.K_SPACE):
            return self._fire_action(m)
        if key == pygame.K_r:
            self._raise_state_literal(m)
            return True
        if key == pygame.K_f:
            self._force_pursue_toggle(m)
            return True
        return False

    # --- editor mutations ------------------------------------------------

    def _value_for(self, m, spec):
        """Current working value for (entity, field). Initialises from
        the live snapshot on first access."""
        fkey = spec[0]
        kind = spec[2]
        k = (m.ptr, fkey)
        if k in self._values:
            return self._values[k]
        v = self._live_value(m, spec)
        self._values[k] = v
        return v

    @staticmethod
    def _live_value(m, spec):
        """Pull the current live value for a field from the AI snapshot."""
        fkey = spec[0]
        ai = m.ai
        if ai is None:
            return 0
        if fkey == "pursue":    return ai.pursue_target
        if fkey == "anim_id":   return ai.seed
        if fkey == "anim_next": return ai.seed_paired
        if fkey == "state":     return ai.state_byte
        if fkey == "mode":      return ai.mode_byte
        if fkey == "stimulus":  return ai.stimulus_tag
        if fkey == "flag410":   return ai.flag_410
        if fkey == "dmg_flag":  return ai.damage_flag
        if fkey == "timer624":  return ai.timer_624
        if fkey == "timer626":  return ai.timer_626
        if fkey == "stress":    return ai.stress_62E
        if fkey == "ai_param":  return ai.ai_param
        if fkey == "size":      return float(m.size_scale or 1.0)
        if fkey == "head_x":    return float(ai.heading.x)
        if fkey == "head_y":    return float(ai.heading.y)
        if fkey == "head_z":    return float(ai.heading.z)
        return 0

    def _adjust_field(self, m, spec, delta):
        fkey, off, kind, _label, step, coarse, vmin, vmax = spec
        if kind == "size":
            v = float(self._value_for(m, spec)) + float(delta)
            v = max(float(vmin), min(float(vmax), v))
            self._values[(m.ptr, fkey)] = round(v, 4)
        else:
            v = int(self._value_for(m, spec)) + int(delta)
            v = max(int(vmin), min(int(vmax), v))
            self._values[(m.ptr, fkey)] = v
        # If pinned, push the new value into the pin so the writer
        # immediately enforces it.
        pin_key = self._pin_key(m, spec)
        if self.pins is not None and self.pins.has(pin_key):
            self.pins.update_value(pin_key, self._values[(m.ptr, fkey)])

    def _pin_key(self, m, spec) -> str:
        """Stable key used by the PinEngine for this (entity, field)."""
        return f"ent_{m.slot}_{spec[0]}"

    def _cycle_preset(self, m, spec, delta: int):
        """Walk the preset list for the selected field by +/- 1.
        Wraps around. Resolves _PLAYER_PTR sentinel to PLAYER_STRUCT
        at write time. Updates the cached value AND any active pin."""
        fkey = spec[0]
        presets = FIELD_PRESETS.get(fkey)
        if not presets:
            return
        key = (m.ptr, fkey)
        cur = self._preset_idx.get(key)
        if cur is None:
            # First cycle for this (entity, field) — try to snap to the
            # preset that matches the live value so the user steps from
            # "wherever the game is right now" rather than always 0.
            live = self._live_value(m, spec)
            cur = -1
            for i, (_lbl, v) in enumerate(presets):
                if self._resolve_preset_value(v, m) == live:
                    cur = i
                    break
            # If no exact match, start at -1 so +1 lands on 0.
        nxt = (cur + delta) % len(presets)
        self._preset_idx[key] = nxt
        label, raw = presets[nxt]
        v = self._resolve_preset_value(raw, m)
        self._values[key] = v
        pin_key = self._pin_key(m, spec)
        if self.pins is not None and self.pins.has(pin_key):
            self.pins.update_value(pin_key, v)

    @staticmethod
    def _resolve_preset_value(raw, m):
        """_PLAYER_PTR sentinel → live player-struct address. Everything
        else passes through unchanged."""
        if raw == _PLAYER_PTR:
            return _player_struct_ptr_const()
        return raw

    def _current_preset_info(self, m, spec):
        """Return (idx, total, label) for the selected field — used by
        the entity panel to render a "preset N/M" badge on the active row."""
        fkey = spec[0]
        presets = FIELD_PRESETS.get(fkey)
        if not presets:
            return None
        idx = self._preset_idx.get((m.ptr, fkey))
        if idx is None:
            return (-1, len(presets), "—")
        label, _v = presets[idx]
        return (idx, len(presets), label)

    # --- mouse hover -----------------------------------------------------

    def handle_motion(self, canvas_pos, snapshot) -> bool:
        """App forwards MOUSEMOTION events here. Store the position;
        render() figures out tooltip placement on the next frame."""
        self._mouse_canvas = canvas_pos
        return False

    def _toggle_pin(self, m, spec):
        if self.pins is None:
            return
        pin_key = self._pin_key(m, spec)
        if self.pins.has(pin_key):
            self.pins.unpin(pin_key)
            return
        fkey, off, kind, label, *_ = spec
        v = self._value_for(m, spec)
        if kind == "size":
            addrs = [m.ptr + A.OFF_M_SIZE_SCALE_X,
                     m.ptr + A.OFF_M_SIZE_SCALE_Y,
                     m.ptr + A.OFF_M_SIZE_SCALE_Z,
                     m.ptr + A.OFF_M_SIZE_CACHED_RADIUS]
            self.pins.pin(pin_key, "size", m.ptr, float(v), addrs=addrs,
                          label=f"slot{m.slot} size×{v:.2f}")
        else:
            self.pins.pin(pin_key, kind, m.ptr + off, v,
                          label=f"slot{m.slot} {label}")

    def _force_pursue_toggle(self, m):
        """Toggle pursue/flee on the selected entity. Writes once, then
        also nudges the cached UI value to match — leaves any existing
        pin alone so the user can fire-and-forget."""
        if self.pins is None:
            return
        # Read live; flip
        live = m.ai.pursue_target if m.ai else 0
        new = 0 if live != 0 else _player_struct_ptr_const()
        self.pins.oneshot_write(m.ptr + A.OFF_M_PURSUE_TARGET, "u32", new)
        self._values[(m.ptr, "pursue")] = new
        # Update the existing pin value if one is in place.
        pin_key = self._pin_key(m, ("pursue",))
        if self.pins.has(pin_key):
            self.pins.update_value(pin_key, new)

    def _raise_state_literal(self, m):
        """Write the (+0x324, +0x326) pair to the selected literal.
        Mirrors what the 0x09A679D8 ladder does on its 'fire' branch.
        Effect lands on the next AI tick (typically within one frame)."""
        if self.pins is None:
            return
        _name, lit = STATE_LITERALS[self.literal_idx]
        self.pins.oneshot_multi(
            [m.ptr + A.OFF_M_AI_324, m.ptr + A.OFF_M_AI_326],
            "u16",
            lit & 0xFFFF)
        # Sync cached values so the UI matches the wire.
        self._values[(m.ptr, "seed")] = lit & 0xFFFF
        self._values[(m.ptr, "seed_pair")] = (lit + 100) & 0xFFFF
        # The 0x09A679D8 ladder actually writes seed+100 to +0x326. Do
        # the same so behaviour matches the documented ladder exactly.
        self.pins.oneshot_write(m.ptr + A.OFF_M_AI_326, "u16",
                                (lit + 100) & 0xFFFF)

    # Order MUST match the labels list in _actions() render. Adjust both
    # together when adding rows.
    ACTION_COUNT = 6

    def _fire_action(self, m) -> bool:
        idx = self.sel_action
        if idx == 0:
            self._pin_aim(m, toward=True)
            return True
        if idx == 1:
            self._pin_aim(m, toward=False)
            return True
        if idx == 2:
            self._oneshot_aim(m, toward=True)
            return True
        if idx == 3:
            self._raise_state_literal(m)
            return True
        if idx == 4:
            self._force_pursue_toggle(m)
            return True
        if idx == 5:
            if self.pins is not None:
                self.pins.clear()
            return True
        return False

    def _pin_aim(self, m, toward: bool):
        """Install a heading_track pin that recomputes the unit vector
        from popo to (or away from) the player every write tick. Stable
        target-tracking despite engine resets — the resolver reads live
        positions each time the writer runs."""
        if self.pins is None or self.reader is None:
            return
        client_get = lambda: self.reader._client
        popo_ptr = m.ptr
        sign = +1 if toward else -1

        def resolver():
            c = client_get()
            if c is None:
                return (0.0, 0.0)
            # Read current positions live so the pin tracks moving target.
            popo_pos = c.read_memory(popo_ptr + A.OFF_M_POSITION, 12)
            player_pos = c.read_memory(A.CAM_TARGET, 12)
            import struct as _s
            px, _py, pz = _s.unpack("<fff", popo_pos)
            lx, _ly, lz = _s.unpack("<fff", player_pos)
            dx = (lx - px) * sign
            dz = (lz - pz) * sign
            import math as _m
            mag = _m.hypot(dx, dz)
            if mag < 1e-3:
                return (0.0, 0.0)
            return (dx / mag, dz / mag)

        pin_key = f"ent_{m.slot}_aim"
        label = (f"slot{m.slot} AIM→player" if toward
                 else f"slot{m.slot} AIM←away")
        self.pins.pin(pin_key, "heading_track", popo_ptr, (0.0, 0.0),
                      label=label, entity_addr=popo_ptr,
                      resolver=resolver,
                      heading_offset=A.OFF_M_HEADING)

    def _oneshot_aim(self, m, toward: bool):
        """Single write of heading toward/away player — no pin."""
        if self.pins is None or self.reader is None:
            return
        c = self.reader._client
        if c is None:
            return
        import struct as _s, math as _m
        popo_pos = c.read_memory(m.ptr + A.OFF_M_POSITION, 12)
        player_pos = c.read_memory(A.CAM_TARGET, 12)
        px, _py, pz = _s.unpack("<fff", popo_pos)
        lx, _ly, lz = _s.unpack("<fff", player_pos)
        dx, dz = lx - px, lz - pz
        if not toward:
            dx, dz = -dx, -dz
        mag = _m.hypot(dx, dz)
        if mag < 1e-3:
            return
        ux, uz = dx / mag, dz / mag
        c.write_memory(m.ptr + A.OFF_M_HEADING,
                       _s.pack("<fff", ux, 0.0, uz))

    # --- render ---------------------------------------------------------

    def render(self, surface, snap):
        surface.fill(C.BG)
        self._header(surface, snap)
        self._roster(surface, snap)
        self._entity(surface, snap)
        self._actions(surface, snap)
        self._pins_panel(surface)
        self._footer(surface)
        # Tooltip last — overlays everything else.
        self._draw_tooltip(surface)

    def _draw_tooltip(self, surface):
        """Render the field tooltip when the mouse is hovering a row."""
        if self._mouse_canvas is None:
            return
        rects = getattr(self, "_row_rects", None) or []
        mx, my = self._mouse_canvas
        hit_spec = None
        for rect, spec in rects:
            if rect.collidepoint(mx, my):
                hit_spec = spec
                break
        if hit_spec is None:
            return
        fkey = hit_spec[0]
        lines = FIELD_TOOLTIPS.get(fkey)
        if not lines:
            return
        # Box-sizing: longest line drives width; line count + padding height.
        # Drawn at cursor +14,+14, snapped inside the canvas.
        f = __import__("mhfu_hud.theme", fromlist=["font"]).font(11, False)
        line_w = max(f.size(s)[0] for s in lines)
        pad_x, pad_y, line_h = 8, 5, 14
        w = line_w + pad_x * 2
        h = pad_y * 2 + line_h * len(lines)
        tip = pygame.Rect(int(mx) + 14, int(my) + 14, w, h)
        if tip.right > CANVAS_W - 4:
            tip.right = int(mx) - 6
        if tip.bottom > CANVAS_H - 4:
            tip.bottom = int(my) - 6
        # Semi-opaque backdrop + accent border.
        veil = pygame.Surface((tip.w, tip.h), pygame.SRCALPHA)
        veil.fill((10, 14, 22, 230))
        surface.blit(veil, tip.topleft)
        pygame.draw.rect(surface, C.ACCENT, tip, width=1, border_radius=4)
        ty = tip.y + pad_y
        for i, line in enumerate(lines):
            col = C.ACCENT if i == 0 else C.TEXT
            W.text(surface, line, (tip.x + pad_x, ty),
                   size=11, color=col, bold=(i == 0))
            ty += line_h

    def _header(self, surface, snap):
        W.panel(surface, R_HEADER, fill=C.PANEL_HI, border=C.ACCENT)
        monsters = snap.monsters
        if monsters and 0 <= self.sel_entity < len(monsters):
            m = monsters[self.sel_entity]
            cat_chip = ("[BIG]" if m.category == "big" else "[small]")
            W.text(surface,
                   f"AI MOD — {m.name}  slot {m.slot}  type 0x{m.type_byte:02X}  "
                   f"vt 0x{m.vtable:08X}  {cat_chip}",
                   (R_HEADER.x + 12, R_HEADER.y + 4), size=15,
                   color=C.SELECT, bold=True)
        else:
            W.text(surface, "AI MOD — no monster selected",
                   (R_HEADER.x + 12, R_HEADER.y + 4), size=15,
                   color=C.PLACEHOLDER, bold=True)
        n_pins = self.pins.count() if self.pins else 0
        wr = self.pins.writes_total if self.pins else 0
        errs = self.pins.errors_total if self.pins else 0
        W.text(surface,
               f"ctx={snap.context.value}  area={snap.area_index}  "
               f"sec={snap.tracked_section}  ·  PINS={n_pins} "
               f"writes={wr} errors={errs}  (3 Hz)",
               (R_HEADER.x + 12, R_HEADER.y + 24), size=11,
               color=C.TEXT_DIM)
        # 2026-05-26 — engine rotates heading every game frame from 5
        # functions in popo_ovl_B (0x09B91xxx-0x09B9A4xx). PPSSPP JIT
        # caches them; memory.write patches don't stick. 3 Hz polling
        # produces brief direction nudges (visible flicker) but engine
        # reasserts. Deterministic patch needs PRX-side hook (popo_growth
        # pattern). See memory: heading-rotators-jit-blocked.
        W.text(surface,
               "MOTION (best-effort, polling fights engine): pin "
               "state=5 + anim_id=1011 + heading_x/z. Expect flicker — "
               "see docs for PRX-patch path.",
               (R_HEADER.x + 12, R_HEADER.bottom - 14), size=10,
               color=C.ACCENT)

    def _roster(self, surface, snap):
        sel = (self.focus == "roster")
        W.panel(surface, R_ROSTER, title="ROSTER" + (" *" if sel else ""))
        monsters = snap.monsters
        if not monsters:
            W.text(surface, "no monsters loaded",
                   (R_ROSTER.x + 12, R_ROSTER.y + 32), size=12,
                   color=C.PLACEHOLDER)
            return
        row_h = 32
        y = R_ROSTER.y + 26
        for idx, m in enumerate(monsters):
            if y + row_h > R_ROSTER.bottom:
                break
            row = pygame.Rect(R_ROSTER.x + 4, y, R_ROSTER.w - 8, row_h - 2)
            picked = (idx == self.sel_entity)
            if picked:
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface,
                                 C.SELECT if sel else C.ACCENT,
                                 row, width=1, border_radius=3)
            big = (m.category == "big")
            W.text(surface,
                   f"{m.name[:14]:<14}  s{m.slot}",
                   (row.x + 8, row.y + 2), size=11,
                   color=C.WARN if big else C.TEXT, bold=True)
            W.text(surface,
                   f"type 0x{m.type_byte:02X}  hp {m.hp}",
                   (row.x + 8, row.y + 16), size=10, color=C.TEXT_FAINT)
            y += row_h

    def _entity(self, surface, snap):
        sel = (self.focus == "fields")
        title = "ENTITY EDIT" + (" *" if sel else "")
        W.panel(surface, R_ENTITY, title=title)
        monsters = snap.monsters
        if not (monsters and 0 <= self.sel_entity < len(monsters)):
            W.text(surface, "select an entity (←)",
                   (R_ENTITY.x + 12, R_ENTITY.y + 32), size=12,
                   color=C.PLACEHOLDER)
            return
        m = monsters[self.sel_entity]
        row_h = 22
        y = R_ENTITY.y + 26
        # Walk-build the field rows. _row_rects feeds the hover detection
        # below so the tooltip can find which field the mouse is over.
        self._row_rects: list[tuple[pygame.Rect, tuple]] = []
        for idx, spec in enumerate(ENTITY_FIELDS):
            if y + row_h > R_ENTITY.bottom - 14:
                break
            row = pygame.Rect(R_ENTITY.x + 4, y, R_ENTITY.w - 8, row_h - 2)
            self._row_rects.append((row, spec))
            picked = (idx == self.sel_field and sel)
            if picked:
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=3)
            fkey, off, kind, label, *_ = spec
            pinned = (self.pins is not None
                      and self.pins.has(self._pin_key(m, spec)))
            mark = "[●]" if pinned else "[ ]"
            mark_c = C.OK if pinned else C.TEXT_FAINT
            W.text(surface, mark, (row.x + 6, row.y + 3), size=11,
                   color=mark_c, bold=True)
            W.text(surface, label, (row.x + 34, row.y + 3), size=11,
                   color=C.TEXT)
            live = self._live_value(m, spec)
            target = self._value_for(m, spec)
            live_s = self._fmt_value(kind, live)
            tgt_s = self._fmt_value(kind, target)
            W.text(surface, f"live {live_s}",
                   (row.x + 168, row.y + 3), size=11, color=C.TEXT_FAINT)
            tgt_c = C.SELECT if pinned else C.TEXT
            W.text(surface, f"→ {tgt_s}",
                   (row.right - 8, row.y + 3), size=11, color=tgt_c,
                   bold=True, align="right")
            # Preset badge below the selected row — shows current preset
            # index out of total + label, so the user can step through
            # known-good values with ,/. without remembering them.
            if picked:
                info = self._current_preset_info(m, spec)
                if info is not None:
                    pidx, ptotal, plabel = info
                    badge_y = row.y + row_h - 4
                    pidx_s = "—" if pidx < 0 else str(pidx + 1)
                    W.text(surface,
                           f"  preset {pidx_s}/{ptotal}: {plabel}  ",
                           (row.x + 34, badge_y), size=10, color=C.ACCENT)
            y += row_h
        # Footer-ish hint inside the panel — saves a help line below.
        W.text(surface,
               "SPACE pin   +/- raw   ,/. cycle preset   R lit   F pursue",
               (R_ENTITY.x + 8, R_ENTITY.bottom - 14), size=10,
               color=C.TEXT_FAINT)

    @staticmethod
    def _fmt_value(kind, v) -> str:
        if kind == "size":
            return f"{float(v):.3f}×"
        if kind == "u32":
            return f"0x{int(v) & 0xFFFFFFFF:08X}"
        if kind == "u16":
            return f"{int(v) & 0xFFFF}"
        if kind == "u8":
            return f"{int(v) & 0xFF}"
        return str(v)

    def _actions(self, surface, snap):
        sel = (self.focus == "actions")
        title = "SPECIES / ACTIONS" + (" *" if sel else "")
        W.panel(surface, R_ACTIONS, title=title)
        monsters = snap.monsters
        if not (monsters and 0 <= self.sel_entity < len(monsters)):
            return
        m = monsters[self.sel_entity]
        # Species data — read on demand, cache by type byte.
        sd = self._species_data_for(m)
        x = R_ACTIONS.x + 10
        y = R_ACTIONS.y + 26
        if sd is None:
            W.text(surface, "species data unavailable",
                   (x, y), size=11, color=C.PLACEHOLDER)
        else:
            W.text(surface,
                   f"entry 0x{sd['addr']:08X}  ({sd['span']} B)",
                   (x, y), size=10, color=C.TEXT_FAINT)
            y += 14
            rows = [
                ("cool +0x00", f"0x{sd['cooldown']:08X}"),
                ("wts  +0x04", f"0x{sd['weights']:08X}"),
                ("hz   +0x08", f"0x{sd['hitzones']:08X}"),
                ("act  +0x0C", f"0x{sd['actions']:08X}"),
                ("pat  +0x70", f"0x{sd['patterns']:08X}"),
            ]
            W.kv_rows(surface, (x, y), rows, size=10, line_h=14, key_w=66)
            y += 14 * len(rows) + 4
            # Range + scalars in two columns to fit beneath the species
            # ptr block without colliding with the action-button strip.
            col_w = (R_ACTIONS.w - 24) // 2
            y_floats = y
            W.text(surface, "range (+0x20..)", (x, y_floats), size=10,
                   color=C.ACCENT, bold=True)
            yy = y_floats + 12
            for i, fv in enumerate(sd['range'][:6]):
                W.text(surface, f"f{i:02d} {fv:+8.2f}",
                       (x, yy), size=10, color=C.TEXT_FAINT)
                yy += 11
            W.text(surface, "scalars (+0x60..)",
                   (x + col_w, y_floats), size=10, color=C.ACCENT, bold=True)
            yy = y_floats + 12
            for i, fv in enumerate(sd['scalars'][:4]):
                W.text(surface, f"s{i:02d} {fv:+8.2f}",
                       (x + col_w, yy), size=10, color=C.TEXT_FAINT)
                yy += 11

        # Action buttons (bottom of column). Order MUST match _fire_action.
        actions = (
            "PIN AIM → player  (heading track)",
            "PIN AIM ← away    (heading track)",
            "1-shot AIM → player (single write)",
            f"Raise lit: {STATE_LITERALS[self.literal_idx][0]}",
            "Force pursue toggle (herd ptr)",
            "Clear ALL pins",
        )
        ay = R_ACTIONS.bottom - 8 - 20 * len(actions)
        for i, label in enumerate(actions):
            row = pygame.Rect(R_ACTIONS.x + 4, ay, R_ACTIONS.w - 8, 18)
            picked = (i == self.sel_action and sel)
            if picked:
                pygame.draw.rect(surface, C.PANEL_HI, row, border_radius=3)
                pygame.draw.rect(surface, C.SELECT, row, width=1,
                                 border_radius=3)
            W.text(surface, f"[{i+1}] {label}",
                   (row.x + 6, row.y + 2), size=11,
                   color=C.SELECT if picked else C.TEXT, bold=picked)
            ay += 20
        # Big-monster extras
        if m.type_byte == 0x3A:
            W.text(surface,
                   "type 0x3A: alt dispatcher  ·  +0x640 runtime-mutable",
                   (R_ACTIONS.x + 6, R_ACTIONS.y + 4), size=10,
                   color=C.WARN, bold=True)

    def _species_data_for(self, m) -> Optional[dict]:
        """One-shot read of the per-species data entry. Cached by type
        byte so the AI_MOD tab does not poke the debugger socket every
        frame."""
        tb = m.type_byte
        cached = self._species_cache.get(tb)
        if cached is not None:
            return cached
        if self.reader is None or self.reader._client is None:
            return None
        addr = A.SPECIES_TABLE_BASE + tb * A.SPECIES_TABLE_STRIDE
        try:
            buf = self.reader._client.read_memory(addr, A.SPECIES_DATA_SPAN)
        except Exception:
            return None
        if not buf or len(buf) < 0x70:
            return None
        import struct
        cooldown = struct.unpack_from("<I", buf, A.OFF_SD_COOLDOWN)[0]
        weights  = struct.unpack_from("<I", buf, A.OFF_SD_WEIGHTS)[0]
        hitzones = struct.unpack_from("<I", buf, A.OFF_SD_HITZONES)[0]
        actions  = struct.unpack_from("<I", buf, A.OFF_SD_ACTIONS)[0]
        patterns = struct.unpack_from("<I", buf, A.OFF_SD_PATTERNS)[0]
        rng = list(struct.unpack_from("<12f", buf, A.OFF_SD_RANGE_PARAMS))
        scl = list(struct.unpack_from("<4f", buf, A.OFF_SD_SCALARS))
        entry = {
            "addr": addr,
            "span": len(buf),
            "cooldown": cooldown,
            "weights": weights,
            "hitzones": hitzones,
            "actions": actions,
            "patterns": patterns,
            "range": rng,
            "scalars": scl,
            "raw": buf,
        }
        self._species_cache[tb] = entry
        return entry

    def _pins_panel(self, surface):
        W.panel(surface, R_PINS, title="ACTIVE PINS (writer 3 Hz)")
        if self.pins is None:
            return
        pins = self.pins.snapshot()
        if not pins:
            W.text(surface,
                   "no pins active  —  reads / writes are zero-overhead",
                   (R_PINS.x + 12, R_PINS.y + 32), size=11,
                   color=C.TEXT_FAINT)
            return
        cols = 2
        per_col = (len(pins) + cols - 1) // cols
        col_w = (R_PINS.w - 20) // cols
        row_h = 16
        for i, p in enumerate(pins):
            ci = i // per_col
            ri = i % per_col
            x = R_PINS.x + 10 + ci * col_w
            y = R_PINS.y + 28 + ri * row_h
            kind_s = p.kind
            if kind_s == "size":
                val_s = f"size×{float(p.value):.2f}"
                addr_s = f"+0x{A.OFF_M_SIZE_SCALE_X:03X}…(x4)"
            elif kind_s == "heading_track":
                val_s = "live→target"
                addr_s = f"+0x{p.heading_offset:03X} vec3"
            elif kind_s == "vec3":
                val_s = "vec3"
                addr_s = f"0x{p.addr:08X}"
            else:
                if kind_s == "f32":
                    val_s = f"{float(p.value):+.3f}"
                else:
                    val_s = f"0x{int(p.value):X}"
                addr_s = f"0x{p.addr:08X}"
            err = p.last_error[:24] if p.last_error else ""
            err_c = C.ERR if err else C.OK
            W.text(surface, "●", (x, y), size=11, color=err_c, bold=True)
            W.text(surface,
                   f"{p.label or p.key}  {addr_s}  {kind_s}  {val_s}",
                   (x + 12, y), size=10, color=C.TEXT)
            if err:
                W.text(surface, err, (x + col_w - 10, y), size=9,
                       color=C.ERR, align="right")

    def _footer(self, surface):
        W.text(surface,
               "←/→ column  ↑/↓ row  SPACE pin  +/- value  R raise lit  "
               "F pursue toggle  X clear  ,/. cycle literal",
               (10, CANVAS_H - 14), size=10, color=C.TEXT_FAINT)
