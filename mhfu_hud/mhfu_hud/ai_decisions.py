"""Per-species AI action / vt8_input decoder.

Loads `framework/prx/include/mhfu/ai_actions.h` at import time and parses
out the `<SPECIES>_ACTION_*` and `TIGREX_VT8_INPUT_*` / `TIGREX_VT8_PROBE_*`
macros into per-monster-type lookup dicts. Keeps the HUD in sync with the
PRX without a build step — regenerate ai_actions.h, restart the HUD.

Two AI classes (see CLAUDE.md / docs/AI_SCRIPTING_ENGINE.md §32h):

- small-mon-shape (POPO 0x46, ANTEKA 0x45, GIADROME 0x4D): vt[8] returns a
  u16 action ID. Decode by looking up the engine_value in the species'
  action dict.

- true-big-mon (TIGREX 0x4B): vt[8] returns a per-run POINTER. The
  STABLE key is the vt8_input — decode by looking up vt8_input in
  TIGREX_VT8_INPUT_* (or _PROBE_*) macros, and show engine_value as the
  raw observed pointer.

Output of `decode(monster_type, vt8_input, engine_value)`:
  DecodedAction(label, hex, monster_name, ai_class, ptr_or_id)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Optional

# ---------------------------------------------------------------------------

MON_ANTEKA   = 0x45
MON_POPO     = 0x46
MON_TIGREX   = 0x4B
MON_GIADROME = 0x4D

MONSTER_NAMES = {
    MON_ANTEKA:   "ANTEKA",
    MON_POPO:     "POPO",
    MON_TIGREX:   "TIGREX",
    MON_GIADROME: "GIADROME",
}

# species that use vt[8] returning a u16 action ID
SMALL_SHAPE_TYPES = {MON_POPO, MON_ANTEKA, MON_GIADROME}
# species whose vt[8] returns a per-run pointer; STABLE input is vt8_input
TRUE_BIG_TYPES    = {MON_TIGREX}

_AI_ACTIONS_H = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "framework", "prx", "include", "mhfu", "ai_actions.h"))


@dataclass(frozen=True)
class DecodedAction:
    """One AI decision, fully decoded for display."""
    monster_type: int
    monster_name: str
    ai_class: str            # "small-shape" | "true-big" | "unknown"
    vt8_input: int           # u16 — stable key
    engine_value: int        # u32 — id (small-shape) OR ptr (true-big)
    # Pretty label for the primary identifier (per ai_class):
    #   small-shape -> the action macro name (POPO_ACTION_0x0060)
    #   true-big    -> the input macro name (TIGREX_VT8_INPUT_0x04B1)
    # Falls back to a hex placeholder when no macro matches.
    label: str
    is_known: bool           # True if a macro matched

    @property
    def short(self) -> str:
        """One-line display."""
        if self.ai_class == "true-big":
            return f"{self.label}  →  0x{self.engine_value:08X}"
        if self.ai_class == "small-shape":
            return f"{self.label}  (0x{self.engine_value:04X})"
        return (f"type=0x{self.monster_type:02X}  in=0x{self.vt8_input:04X}  "
                f"val=0x{self.engine_value:08X}")


# ---------------------------------------------------------------------------
# Parser

_ACTION_RE = re.compile(
    r"#define\s+(?P<species>[A-Z]+)_ACTION_0x(?P<id>[0-9A-Fa-f]+)\s+"
    r"0x[0-9A-Fa-f]+u")
_TIGREX_IN_RE = re.compile(
    r"#define\s+(?P<name>TIGREX_VT8_(?:INPUT|PROBE)_0x(?P<val>[0-9A-Fa-f]+))"
    r"\s+0x[0-9A-Fa-f]+u")
# Friendly aliases: `#define TIGREX_<NAME>  0x????u`, where <NAME> is anything
# other than `VT8_INPUT_*` / `VT8_PROBE_*`. Maps the u16 input value to the
# alias suffix (no TIGREX_ prefix).
_TIGREX_ALIAS_RE = re.compile(
    r"#define\s+TIGREX_(?!VT8_)(?P<name>[A-Z0-9_]+)\s+"
    r"0x(?P<val>[0-9A-Fa-f]+)u")


def _parse_header(path: str):
    """Return ({type_byte: {action_id_int: macro_name}},
                {input_int: macro_name},
                {input_int: friendly_alias})."""
    actions: Dict[int, Dict[int, str]] = {
        MON_POPO: {}, MON_ANTEKA: {}, MON_GIADROME: {}, MON_TIGREX: {},
    }
    tigrex_inputs: Dict[int, str] = {}
    tigrex_aliases: Dict[int, str] = {}
    if not os.path.isfile(path):
        return actions, tigrex_inputs, tigrex_aliases
    species_to_type = {
        "POPO":     MON_POPO,
        "ANTEKA":   MON_ANTEKA,
        "GIADROME": MON_GIADROME,
        "TIGREX":   MON_TIGREX,   # currently empty list in the header
    }
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            m = _ACTION_RE.match(s)
            if m:
                sp = m.group("species")
                if sp in species_to_type:
                    aid = int(m.group("id"), 16)
                    actions[species_to_type[sp]][aid] = f"{sp}_ACTION_0x{aid:04X}"
                continue
            m = _TIGREX_IN_RE.match(s)
            if m:
                v = int(m.group("val"), 16)
                tigrex_inputs[v] = m.group("name")
                continue
            m = _TIGREX_ALIAS_RE.match(s)
            if m:
                v = int(m.group("val"), 16)
                tigrex_aliases[v] = f"TIGREX_{m.group('name')}"
    return actions, tigrex_inputs, tigrex_aliases


_ACTIONS, _TIGREX_INPUTS, _TIGREX_ALIASES = _parse_header(_AI_ACTIONS_H)


def monster_name(monster_type: int) -> str:
    return MONSTER_NAMES.get(monster_type, f"0x{monster_type:02X}")


def ai_class(monster_type: int) -> str:
    if monster_type in SMALL_SHAPE_TYPES:
        return "small-shape"
    if monster_type in TRUE_BIG_TYPES:
        return "true-big"
    return "unknown"


def decode(monster_type: int, vt8_input: int,
           engine_value: int) -> DecodedAction:
    """Decode one publish-table entry into a labelled DecodedAction."""
    cls = ai_class(monster_type)
    name = monster_name(monster_type)
    if cls == "small-shape":
        actions = _ACTIONS.get(monster_type, {})
        label = actions.get(engine_value & 0xFFFF)
        if label is None:
            label = f"{name}_ACTION_0x{engine_value & 0xFFFF:04X}"
            known = False
        else:
            known = True
    elif cls == "true-big":
        key = vt8_input & 0xFFFF
        alias = _TIGREX_ALIASES.get(key)
        if alias is not None:
            label = alias
            known = True
        else:
            label = _TIGREX_INPUTS.get(key)
            if label is None:
                label = f"TIGREX_VT8_INPUT_0x{key:04X}"
                known = False
            else:
                known = True
    else:
        label = f"UNKNOWN_0x{vt8_input & 0xFFFF:04X}"
        known = False
    return DecodedAction(
        monster_type=monster_type, monster_name=name, ai_class=cls,
        vt8_input=vt8_input & 0xFFFF, engine_value=engine_value,
        label=label, is_known=known,
    )


def is_supported_monster(monster_type: int) -> bool:
    return monster_type in SMALL_SHAPE_TYPES or monster_type in TRUE_BIG_TYPES


def known_action_count(monster_type: int) -> int:
    if monster_type == MON_TIGREX:
        return len(_TIGREX_INPUTS)
    return len(_ACTIONS.get(monster_type, {}))
