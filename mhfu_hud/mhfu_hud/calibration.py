"""World->image projection for each map, plus mutable tuning state.

Per-map projection now uses a thin-plate-spline fit over a table of
hand-placed anchors (world XZ -> native-image pixel XY). The snowy mountains
map ships with 21 anchors taken from in-game entry/exit point coordinates
captured against MHFU EU. Maps without anchors fall back to a simple
"player_centered" projection so the hunter stays pinned at the map center.

The HUD layout calls `world_to_image` to get a pixel inside the *native* map
image; it then transforms that into screen coordinates using the same scale
and centering it already applies when blitting the map.
"""

import json
import math
from pathlib import Path
from typing import Optional, Tuple, List

_PATH = Path(__file__).resolve().parent.parent / "config" / "calibration.json"

# --- defaults --------------------------------------------------------------

# Per-map anchor sets. Each entry: world (x, z) -> native-image pixel (px, py).
# Captured 2026-05-23 from in-game entry/exit point coordinates the user
# walked to using saves 2..6 in MHFU EU. Pixel positions read off the
# yellow letter labels (A..V, no N) painted on the printable map source at
# `/tmp/snowy_mountains.png` (native size 803x654).
_SNOW_ANCHORS = [
    # (world_x, world_z, image_x, image_y)
    (15168, 14540, 567, 605),  # A
    (13200, 14810, 543, 589),  # B
    (18490, 12600, 376, 589),  # C
    (12490, 12500, 106, 589),  # D
    (11210,  8300, 277, 530),  # E
    (14500, 11290, 529, 494),  # F
    (14000,  6010, 314, 490),  # G
    (17324,  6605, 566, 418),  # H
    (12245,  9924, 357, 335),  # I
    ( 8415,  8267, 171, 384),  # J
    ( 6276,  8645, 283, 324),  # K
    (11632,  4040, 485, 388),  # L
    ( 8745, 13524, 306, 383),  # M
    ( 5517,  7415, 429, 201),  # O
    (11724,  5055, 363, 272),  # P
    (13490, 10750, 215, 185),  # Q
    ( 6099, 11931, 454, 267),  # R
    ( 7184,  8262, 314,  36),  # S
    (13245,  6076, 214, 102),  # T
    (10764,  4011, 530, 131),  # U
    (15268,  6540, 425,  28),  # V
    # 2026-05-24 — added 4 new entries the user captured to cover the
    # 2↔3 / 2↔7 gates. Pixel positions identified by image-diff against
    # the unmodified asset; OCR-verified except X (visually confirmed —
    # tesseract mistook the X-stroke for A).
    ( 6510, 11800, 155, 423),  # W  2→3 (lands in s3)
    ( 6777,  7989,  32, 491),  # X  3→2 (lands in s2)
    (13625,  6185, 143, 476),  # Y  7→2 (lands in s2)
    (10585, 15983, 177, 271),  # Z  2→7 (lands in s7)
]

# Per-anchor section labels for snowy_mountains, observed via
# tools/discover_map_section_v2.py on 2026-05-23:
#   save popo_quest_start  ends at C → s1
#   save edge_s1_to_s2     starts E (in s1), ends D → s2
#   save edge_s1_to_s4     starts G (in s1), ends F → s4
#   save edge_s4_to_s5     starts L (in s4), ends M → s5
#   save edge_s5_to_s6     starts P (in s5), ends O → s6
# Anchors A, B, H, I, J, K, Q, R, S, T, U, V are not yet sectioned and
# default to None (HUD shows "?").
_SNOW_ANCHOR_SECTIONS = {
    (15168, 14540): None, # A
    (13200, 14810): None, # B
    (18490, 12600): 1,    # C
    (12490, 12500): 2,    # D
    (11210,  8300): 1,    # E
    (14500, 11290): 4,    # F
    (14000,  6010): 1,    # G
    (17324,  6605): None, # H
    (12245,  9924): None, # I
    ( 8415,  8267): None, # J
    ( 6276,  8645): None, # K
    (11632,  4040): 4,    # L
    ( 8745, 13524): 5,    # M
    ( 5517,  7415): 6,    # O
    (11724,  5055): 5,    # P
    (13490, 10750): None, # Q
    ( 6099, 11931): None, # R
    ( 7184,  8262): None, # S
    (13245,  6076): None, # T
    (10764,  4011): None, # U
    (15268,  6540): None, # V
    # 2026-05-24 additions from user's 2↔3 / 2↔7 gate observations.
    ( 6510, 11800): 3,    # W  enters section 3
    ( 6777,  7989): 2,    # X  enters section 2
    (13625,  6185): 2,    # Y  enters section 2
    (10585, 15983): 7,    # Z  enters section 7
}

_DEFAULTS = {
    "quest_map": {
        # legacy player_centered fallback for maps without an anchor table
        "mode": "player_centered",
        "scale": 0.06,
        "rot_deg": 0.0,
        "origin_x": 0.0,
        "origin_z": 0.0,
        # facing-direction tweaks: applied to the player marker triangle
        "facing_offset_deg": 0.0,
        "facing_flip": False,
    },
    "village_marker": {
        "nx": 0.5,
        "ny": 0.62,
        "facing_offset_deg": 0.0,
    },
    # Native image dimensions per map slug. Used by the HUD to map the
    # projected native pixel back onto the on-screen scaled blit.
    "map_native": {
        "snowy_mountains": [803, 654],
    },
    "map_anchors": {
        "snowy_mountains": _SNOW_ANCHORS,
    },
    "anchor_sections": {
        # serialised as a list of (world_x, world_z, section_or_null) triples
        # so JSON can round-trip it.
        "snowy_mountains": [
            (x, z, _SNOW_ANCHOR_SECTIONS.get((x, z)))
            for x, z, _, _ in _SNOW_ANCHORS
        ],
    },
    # Learnt area_index → labelled section for each map. Seeded from
    # tools/discover_map_section_v3.py 2026-05-24. The HUD adds new
    # entries at runtime when a gate transition lands on a known anchor
    # and the area_index is novel. `basecamp` is stored as null because
    # it isn't one of the numbered sections 1..8.
    "area_index_map": {
        "snowy_mountains": {
            "98": None,    # basecamp
            "99": 1,
            "95": 2,
            "92": 4,
            "93": 5,
            "100": 6,
        },
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


# --- thin-plate-spline projector ------------------------------------------

def _tps_u(r2: float) -> float:
    """Thin-plate basis. r2 == squared distance; U(r) = r^2 * log(r)."""
    if r2 <= 1e-12:
        return 0.0
    return r2 * 0.5 * math.log(r2)   # log(r) = 0.5 * log(r^2)


class _TPS:
    """Solves and evaluates a 2D->2D thin-plate spline.

    Inputs are N control points (world x, world z) mapped to N outputs
    (pixel x, pixel y). Two independent splines are fit (one per output
    dimension). Pure Python / stdlib; N is small (~21) so cost is trivial.
    """

    def __init__(self, anchors: List[Tuple[float, float, float, float]]):
        self.anchors = anchors
        n = len(anchors)
        # Build the (n+3) x (n+3) system: [K P; P^T 0] * [w; a] = [y; 0]
        size = n + 3
        K = [[0.0] * size for _ in range(size)]
        for i in range(n):
            xi, zi, _, _ = anchors[i]
            for j in range(n):
                xj, zj, _, _ = anchors[j]
                dx, dz = xi - xj, zi - zj
                K[i][j] = _tps_u(dx * dx + dz * dz)
            # P columns on the right
            K[i][n + 0] = 1.0
            K[i][n + 1] = xi
            K[i][n + 2] = zi
            # P^T rows on the bottom
            K[n + 0][i] = 1.0
            K[n + 1][i] = xi
            K[n + 2][i] = zi
        # bottom-right 3x3 is zeros (already).

        # Solve for px and py simultaneously by linear elimination.
        ypx = [a[2] for a in anchors] + [0.0, 0.0, 0.0]
        ypy = [a[3] for a in anchors] + [0.0, 0.0, 0.0]
        self.wpx = _solve(K, ypx)
        self.wpy = _solve(K, ypy)

    def evaluate(self, x: float, z: float) -> Tuple[float, float]:
        n = len(self.anchors)
        sx = self.wpx[n + 0] + self.wpx[n + 1] * x + self.wpx[n + 2] * z
        sy = self.wpy[n + 0] + self.wpy[n + 1] * x + self.wpy[n + 2] * z
        for i, (xi, zi, _, _) in enumerate(self.anchors):
            dx, dz = x - xi, z - zi
            u = _tps_u(dx * dx + dz * dz)
            sx += self.wpx[i] * u
            sy += self.wpy[i] * u
        return sx, sy


def _solve(A: List[List[float]], b: List[float]) -> List[float]:
    """Gauss-Jordan with partial pivoting. Mutates a fresh copy."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        # pivot
        pivot = col
        best = abs(M[col][col])
        for r in range(col + 1, n):
            if abs(M[r][col]) > best:
                best = abs(M[r][col])
                pivot = r
        if best < 1e-12:
            # singular — return zeros rather than blow up the HUD
            return [0.0] * n
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
        # normalize the row
        inv = 1.0 / M[col][col]
        for k in range(col, n + 1):
            M[col][k] *= inv
        # eliminate other rows
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            if f == 0.0:
                continue
            for k in range(col, n + 1):
                M[r][k] -= f * M[col][k]
    return [M[i][n] for i in range(n)]


# --- public API ------------------------------------------------------------

class Calibration:
    """Mutable, in-memory calibration with load/save to calibration.json."""

    def __init__(self):
        self.data = dict(_DEFAULTS)
        self._tps_cache: dict = {}
        self.load()

    def load(self):
        try:
            disk = json.loads(_PATH.read_text())
        except Exception:
            disk = {}
        self.data = _merge(_DEFAULTS, {k: v for k, v in disk.items()
                                       if not k.startswith("_")})
        self._tps_cache.clear()

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

    # --- per-map projection -------------------------------------------------

    def has_anchors(self, map_slug: str) -> bool:
        anchors = (self.data.get("map_anchors") or {}).get(map_slug)
        return bool(anchors) and len(anchors) >= 4

    def map_native_size(self, map_slug: str) -> Optional[Tuple[int, int]]:
        sz = (self.data.get("map_native") or {}).get(map_slug)
        if sz and len(sz) == 2:
            return int(sz[0]), int(sz[1])
        return None

    def _tps(self, map_slug: str) -> Optional[_TPS]:
        if map_slug in self._tps_cache:
            return self._tps_cache[map_slug]
        anchors = (self.data.get("map_anchors") or {}).get(map_slug)
        if not anchors or len(anchors) < 4:
            return None
        tps = _TPS([(float(x), float(z), float(px), float(py))
                    for x, z, px, py in anchors])
        self._tps_cache[map_slug] = tps
        return tps

    def world_to_image(self, map_slug: str, world_x: float,
                       world_z: float) -> Optional[Tuple[float, float]]:
        """Project a world (x, z) into native-image pixels. None if no
        anchors are registered for this map."""
        tps = self._tps(map_slug)
        if tps is None:
            return None
        return tps.evaluate(world_x, world_z)

    def section_from_world(self, map_slug: str, world_x: float,
                           world_z: float,
                           max_dist: float = 2500.0
                           ) -> Tuple[Optional[int], float]:
        """Best-effort section ID derived from world coords by snapping to
        the nearest registered entry-point anchor.

        Returns (section_or_none, distance_to_nearest_anchor). The HUD only
        treats this as authoritative right after a gate transition — when
        the hunter is standing on a spawn point — because each section has
        its own local coord frame and world coords are NOT globally
        comparable (verified by the user: walking inside one section
        otherwise registers as crossing into neighbours).

        Returns (None, dist) if the nearest anchor is unlabelled OR farther
        than `max_dist` world units (probably not a real spawn match)."""
        anchors = (self.data.get("map_anchors") or {}).get(map_slug)
        sec_table = (self.data.get("anchor_sections") or {}).get(map_slug)
        if not anchors or not sec_table:
            return None, float("inf")
        sec_map = {(int(round(x)), int(round(z))): s
                   for (x, z, s) in sec_table}
        best = (float("inf"), None)
        for x, z, *_ in anchors:
            d2 = (world_x - x) ** 2 + (world_z - z) ** 2
            if d2 < best[0]:
                sec = sec_map.get((int(round(x)), int(round(z))))
                best = (d2, sec)
        dist = best[0] ** 0.5
        if dist > max_dist:
            return None, dist
        return best[1], dist

    # --- per-section projection (local-coord aware) -----------------------

    def _section_anchors(self, slug, section):
        anchors = (self.data.get("map_anchors") or {}).get(slug, [])
        sec_table = (self.data.get("anchor_sections") or {}).get(slug, [])
        lookup = {(int(round(x)), int(round(z))): s for x, z, s in sec_table}
        out = []
        for x, z, px, py in anchors:
            if lookup.get((int(round(x)), int(round(z)))) == section:
                out.append((float(x), float(z), float(px), float(py)))
        return out

    # Fallback scale (image-px per world-unit) when a section has too few
    # anchors to derive scale on its own. Median across all 21 snow anchors
    # under the global TPS fit was ~0.030 px/unit; use that as a default.
    _FALLBACK_SECTION_SCALE = 0.030

    def _section_affine(self, slug, section):
        """Per-section affine cached on first use. Returns (Mx, My) or None
        if the section has <3 anchors."""
        key = (slug, section, "aff")
        if key in self._tps_cache:
            return self._tps_cache[key]
        anchors = self._section_anchors(slug, section)
        if len(anchors) < 3:
            self._tps_cache[key] = None
            return None
        # least-squares affine: P = a*x + b*z + t
        n = len(anchors)
        A = [[a[0], a[1], 1.0] for a in anchors]
        px = [a[2] for a in anchors]
        py = [a[3] for a in anchors]
        AT = list(zip(*A))
        ATA = [[sum(AT[i][k] * A[k][j] for k in range(n)) for j in range(3)]
               for i in range(3)]
        ATbx = [sum(AT[i][k] * px[k] for k in range(n)) for i in range(3)]
        ATby = [sum(AT[i][k] * py[k] for k in range(n)) for i in range(3)]
        Mx = _solve([row[:] for row in ATA], ATbx)
        My = _solve([row[:] for row in ATA], ATby)
        self._tps_cache[key] = (Mx, My)
        return Mx, My

    def world_to_image_section(self, slug: str,
                                section: Optional[int],
                                world_x: float, world_z: float
                                ) -> Optional[Tuple[float, float]]:
        """Project world (x, z) into native-image pixels using only the
        anchors in `section`'s local coord frame.

        - 3+ anchors → least-squares affine.
        - 2 anchors  → translation + 1-D scale through the anchor pair.
        - 1 anchor   → place at the anchor pixel + (delta * fallback_scale).
        - 0 anchors / section=None → return None (caller falls back).
        """
        if section is None:
            return None
        anchors = self._section_anchors(slug, section)
        n = len(anchors)
        if n >= 3:
            Mx, My = self._section_affine(slug, section)
            return (Mx[0] * world_x + Mx[1] * world_z + Mx[2],
                    My[0] * world_x + My[1] * world_z + My[2])
        if n == 2:
            ax, az, apx, apy = anchors[0]
            bx, bz, bpx, bpy = anchors[1]
            dwx, dwz = bx - ax, bz - az
            dw2 = dwx * dwx + dwz * dwz
            if dw2 == 0:
                return apx, apy
            dpx, dpy = bpx - apx, bpy - apy
            # decompose: pixel delta along the anchor-pair direction
            # uses the unit-vector scale; orthogonal direction reuses the
            # same scalar magnitude (no rotation info available beyond
            # the single axis).
            scale = ((dpx * dpx + dpy * dpy) / dw2) ** 0.5
            return (apx + (world_x - ax) * scale,
                    apy + (world_z - az) * scale)
        if n == 1:
            ax, az, apx, apy = anchors[0]
            s = self._FALLBACK_SECTION_SCALE
            return apx + (world_x - ax) * s, apy + (world_z - az) * s
        return None

    # --- area_index -> labelled section lookup -----------------------------

    def section_from_area_index(self, slug: str, area_index: int):
        """Return (section, found). section is the labelled section ID
        (int) or None when the area_index is registered as basecamp.
        found indicates whether the lookup hit at all — if False, the
        caller should fall back to the gate-snap heuristic."""
        table = (self.data.get("area_index_map") or {}).get(slug) or {}
        key = str(int(area_index))
        if key not in table:
            return None, False
        return table[key], True

    def learn_area_index(self, slug: str, area_index: int,
                          section) -> bool:
        """Record a new (area_index → section) mapping in-memory. Returns
        True if a new entry was added, False if the value was already
        registered. Save with .save() to persist."""
        table = self.data.setdefault("area_index_map", {})
        smap = table.setdefault(slug, {})
        key = str(int(area_index))
        if key in smap:
            return False
        smap[key] = section
        return True

    def section_centroid_pixel(self, slug: str,
                                section: Optional[int]
                                ) -> Optional[Tuple[float, float]]:
        """Average of the section's anchor pixels — useful as a fallback
        marker position when projection is too uncertain."""
        if section is None:
            return None
        anchors = self._section_anchors(slug, section)
        if not anchors:
            return None
        return (sum(a[2] for a in anchors) / len(anchors),
                sum(a[3] for a in anchors) / len(anchors))

    # --- world -> map projection (legacy player_centered fallback) ---------

    def world_to_map(self, region_rect, world_x, world_z,
                     player_x, player_z):
        """Project a world (x, z) into a pixel inside `region_rect`. Used
        only when the active map has no anchors (player_centered fallback)."""
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
