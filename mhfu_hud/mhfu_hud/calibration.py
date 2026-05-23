"""Tunable placement constants for mapping world coords onto images.

World->map calibration is not yet known from RE work, so the quest map
defaults to 'player_centered' mode (player pinned to the map centre, monsters
drawn relative). The user can switch to 'fixed' and dial in real coordinates
via the in-app calibration controls; values persist to calibration.json.
"""

import json
import math
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "config" / "calibration.json"

_DEFAULTS = {
    "quest_map": {
        "mode": "player_centered",   # or "fixed"
        "scale": 0.06,               # pixels per world unit
        "rot_deg": 0.0,
        "origin_x": 0.0,
        "origin_z": 0.0,
    },
    "village_marker": {
        "nx": 0.5,                   # normalised marker x on the background
        "ny": 0.62,
        "facing_offset_deg": 0.0,
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Calibration:
    """Mutable, in-memory calibration with load/save to calibration.json."""

    def __init__(self):
        self.data = dict(_DEFAULTS)
        self.load()

    def load(self):
        try:
            disk = json.loads(_PATH.read_text())
        except Exception:
            disk = {}
        self.data = _merge(_DEFAULTS, {k: v for k, v in disk.items()
                                       if not k.startswith("_")})

    def save(self):
        try:
            _PATH.write_text(json.dumps(self.data, indent=2))
            return True
        except Exception:
            return False

    @property
    def quest(self):
        return self.data["quest_map"]

    @property
    def village(self):
        return self.data["village_marker"]

    # --- world -> map projection ------------------------------------------

    def world_to_map(self, region_rect, world_x, world_z,
                     player_x, player_z):
        """Project a world (x, z) into a pixel inside `region_rect`."""
        q = self.quest
        if q["mode"] == "player_centered":
            ox, oz = player_x, player_z
        else:
            ox, oz = q["origin_x"], q["origin_z"]
        dx = world_x - ox
        dz = world_z - oz
        a = math.radians(q["rot_deg"])
        ca, sa = math.cos(a), math.sin(a)
        s = q["scale"]
        px = region_rect.centerx + (dx * ca - dz * sa) * s
        py = region_rect.centery + (dx * sa + dz * ca) * s
        return px, py
