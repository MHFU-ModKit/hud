"""Asset discovery and pygame surface loading, with a scale cache.

Images live under assets/ (fetched by tools/fetch_assets.py):
  assets/monsters/      monster icons + manifest.json (slug -> filename)
  assets/maps/          per-location resource maps + manifest.json
  assets/backgrounds/   village background(s)
Missing assets resolve to None; callers fall back to drawn placeholders.
"""

import json
from pathlib import Path

import pygame

_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = _ROOT / "assets"
MONSTERS_DIR = ASSETS_DIR / "monsters"
MAPS_DIR = ASSETS_DIR / "maps"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"


def _load_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


class AssetLibrary:
    """Lazy image loader. Construct after pygame.display has been created so
    convert_alpha() has a display format to convert to."""

    def __init__(self):
        self._raw: dict = {}        # key -> Surface | None
        self._scaled: dict = {}     # (key, w, h) -> Surface
        self._monster_manifest = _load_manifest(MONSTERS_DIR / "manifest.json")
        self._map_manifest = _load_manifest(MAPS_DIR / "manifest.json")

    # --- loading -----------------------------------------------------------

    def _load(self, key: str, path: Path):
        if key in self._raw:
            return self._raw[key]
        surf = None
        if path and path.is_file():
            try:
                surf = pygame.image.load(str(path)).convert_alpha()
            except Exception:
                surf = None
        self._raw[key] = surf
        return surf

    def monster_icon(self, slug):
        if not slug:
            return None
        fname = self._monster_manifest.get(slug, f"{slug}.png")
        return self._load(f"mon:{slug}", MONSTERS_DIR / fname)

    def map_image(self, slug):
        if not slug:
            return None
        fname = self._map_manifest.get(slug, f"{slug}.png")
        return self._load(f"map:{slug}", MAPS_DIR / fname)

    def background(self, name="village"):
        for ext in (".png", ".jpg", ".jpeg"):
            p = BACKGROUNDS_DIR / f"{name}{ext}"
            if p.is_file():
                return self._load(f"bg:{name}", p)
        return None

    # --- scaling cache -----------------------------------------------------

    def scaled(self, surf, size):
        """Return `surf` scaled to `size` (w, h), cached by identity+size."""
        if surf is None:
            return None
        w, h = int(size[0]), int(size[1])
        if w <= 0 or h <= 0:
            return None
        key = (id(surf), w, h)
        cached = self._scaled.get(key)
        if cached is None:
            cached = pygame.transform.smoothscale(surf, (w, h))
            self._scaled[key] = cached
        return cached

    def has_assets(self) -> bool:
        return ASSETS_DIR.is_dir() and any(ASSETS_DIR.rglob("*.png"))

    def map_slugs(self):
        """Available map slugs — from the manifest, else from .png filenames."""
        slugs = [k for k in self._map_manifest.keys() if not k.startswith("_")]
        if not slugs and MAPS_DIR.is_dir():
            slugs = sorted(p.stem for p in MAPS_DIR.glob("*.png"))
        return slugs

    def monster_slugs(self):
        """Available monster icon slugs."""
        slugs = [k for k in self._monster_manifest.keys()
                 if not k.startswith("_")]
        if not slugs and MONSTERS_DIR.is_dir():
            slugs = sorted(p.stem for p in MONSTERS_DIR.glob("*.png"))
        return slugs
