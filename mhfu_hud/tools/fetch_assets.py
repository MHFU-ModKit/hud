#!/usr/bin/env python3
"""Prefetch HUD image assets from the Monster Hunter Fandom wiki.

Downloads, into mhfu_hud/assets/:
  backgrounds/village.png   the village artwork (fixed URL)
  maps/snowy_mountains.png  the Snowy Mountains resource map (fixed URL)
  maps/<location>.png       best-effort resource maps for other locations
  monsters/<slug>.png       monster icons scraped from the MHFU monster list

All images are normalised to PNG via Pillow (handles webp/gif/jpg sources).
Each directory gets a manifest.json (slug -> filename). Network failures are
logged and skipped — the HUD falls back to drawn placeholders.

Usage:
    python tools/fetch_assets.py            # full fetch
    python tools/fetch_assets.py --quick    # only the two fixed-URL assets
    python tools/fetch_assets.py --no-maps  # skip per-location map scraping
"""

import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow is required:  pip install pillow")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
WIKI = "https://monsterhunter.fandom.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Fixed-URL assets the user supplied directly.
VILLAGE_BG = ("https://static.wikia.nocookie.net/monsterhunter/images/a/ab/"
              "VillageBG4.png/revision/latest?cb=20100929071921")
SNOWY_MAP = ("https://static.wikia.nocookie.net/monsterhunter/images/7/7d/"
             "Monster_hunter_freedom_2_mountains.png/revision/latest"
             "?cb=20070916101540")

# MHFU / MHP2G hunting locations to attempt resource-map scraping for.
LOCATIONS = [
    "Snowy Mountains", "Desert", "Swamp", "Jungle", "Volcano",
    "Forest and Hills", "Old Jungle", "Great Forest", "Volcanic Belt",
    "Tower", "Castle Schrade", "Town", "Fortress", "Battlefield",
]


# --------------------------------------------------------------------------
# networking
# --------------------------------------------------------------------------

def http_get(url, retries=4, timeout=25):
    """Fetch a URL, returning bytes. Retries with backoff; raises on failure."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                       # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"GET failed ({last}): {url}")


def save_image(data, path, max_side=None):
    """Normalise image bytes to PNG (RGBA) at `path`, optionally downscaled."""
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGBA")
    if max_side and max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * ratio)),
                          max(1, int(img.height * ratio))), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return img.size


# --------------------------------------------------------------------------
# wikia URL handling
# --------------------------------------------------------------------------

def wikia_full(url, width=None):
    """Rewrite a wikia thumbnail URL to the original (or a fixed width)."""
    # .../images/a/ab/Name.png/revision/latest/scale-to-width-down/120?cb=..
    m = re.match(r"(https://static\.wikia\.nocookie\.net/[^?]+?"
                 r"/revision/latest)", url)
    base = m.group(1) if m else url.split("?")[0]
    cb = ""
    if "cb=" in url:
        cb = "?cb=" + url.split("cb=")[1].split("&")[0]
    if width:
        return f"{base}/scale-to-width-down/{width}{cb}"
    return base + cb


def wikia_filename(url):
    """Extract the source filename from a wikia image URL."""
    m = re.search(r"/images/\w/\w\w/([^/?]+)", url)
    return urllib.parse.unquote(m.group(1)) if m else ""


# --------------------------------------------------------------------------
# HTML scraping
# --------------------------------------------------------------------------

class TokenParser(HTMLParser):
    """Collects, in document order, monster-page links and content images."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []           # ('a', href, text) | ('img', url, alt)
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a":
            href = d.get("href", "")
            if href.startswith("/wiki/") and ":" not in href[6:]:
                self._href = href
                self._text = []
        elif tag == "img":
            url = d.get("data-src") or d.get("src") or ""
            if "static.wikia.nocookie.net" in url and "/images/" in url:
                self.tokens.append(("img", url, d.get("alt", "")))

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.tokens.append(("a", self._href, "".join(self._text).strip()))
            self._href = None
            self._text = []


def slugify(name):
    name = re.sub(r"\(.*?\)", "", name)
    out = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return out.strip("_")


def scrape_monsters():
    """Return {slug: (display_name, image_url)} from the MHFU monster list."""
    print("· scraping MHFU:_Monsters …")
    html = http_get(f"{WIKI}/wiki/MHFU:_Monsters").decode("utf-8", "replace")
    p = TokenParser()
    p.feed(html)
    toks = p.tokens

    found = {}
    for i, tok in enumerate(toks):
        if tok[0] != "img":
            continue
        _, url, alt = tok
        # pair this image with the nearest monster-page link
        best, best_dist = None, 99
        for j in range(max(0, i - 3), min(len(toks), i + 4)):
            if toks[j][0] == "a" and toks[j][2]:
                d = abs(j - i)
                if d < best_dist:
                    best, best_dist = toks[j], d
        name = ""
        if best:
            name = best[2] or urllib.parse.unquote(best[1].split("/wiki/")[1])
        if not name or len(name) > 40:
            name = re.sub(r"\.\w+$", "", wikia_filename(url))
        slug = slugify(name)
        if slug and slug not in found and not _is_ui_image(url):
            found[slug] = (name.replace("_", " ").strip(), url)
    return found


def _is_ui_image(url):
    fn = wikia_filename(url).lower()
    return any(k in fn for k in ("site-logo", "wordmark", "favicon",
                                 "badge", "icon-", "ui_", "navibar",
                                 "logo", "frontier", "wiki-background"))


def scrape_location_map(location):
    """Best-effort: find the resource-map image URL on a location's page."""
    try:
        html = http_get(f"{WIKI}/wiki/{location.replace(' ', '_')}")
        html = html.decode("utf-8", "replace")
    except Exception as e:                           # noqa: BLE001
        print(f"  ! {location}: {e}")
        return None
    p = TokenParser()
    p.feed(html)
    candidates = []
    for tok in p.tokens:
        if tok[0] != "img":
            continue
        fn = wikia_filename(tok[1]).lower()
        if any(k in fn for k in ("freedom", "_map", "map_", "portable")):
            candidates.append(tok[1])
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def write_manifest(directory, mapping):
    (directory / "manifest.json").write_text(json.dumps(mapping, indent=2))


def fetch_fixed():
    print("· fixed-URL assets …")
    ok = {}
    try:
        size = save_image(http_get(VILLAGE_BG),
                          ASSETS / "backgrounds" / "village.png")
        print(f"  ✓ village background {size}")
        ok["village_bg"] = True
    except Exception as e:                           # noqa: BLE001
        print(f"  ! village background failed: {e}")
    try:
        size = save_image(http_get(SNOWY_MAP),
                          ASSETS / "maps" / "snowy_mountains.png")
        print(f"  ✓ snowy_mountains map {size}")
        ok["snowy_map"] = True
    except Exception as e:                           # noqa: BLE001
        print(f"  ! snowy_mountains map failed: {e}")
    return ok


def fetch_monsters():
    try:
        found = scrape_monsters()
    except Exception as e:                           # noqa: BLE001
        print(f"  ! monster scrape failed: {e}")
        return
    print(f"· {len(found)} monster icons found — downloading …")
    manifest = {}
    for n, (slug, (name, url)) in enumerate(sorted(found.items()), 1):
        try:
            data = http_get(wikia_full(url, width=256))
            save_image(data, ASSETS / "monsters" / f"{slug}.png",
                       max_side=256)
            manifest[slug] = f"{slug}.png"
            print(f"  ✓ [{n}/{len(found)}] {name}")
        except Exception as e:                       # noqa: BLE001
            print(f"  ! [{n}/{len(found)}] {name}: {e}")
    write_manifest(ASSETS / "monsters", manifest)
    print(f"· monsters manifest: {len(manifest)} icons")


def fetch_maps():
    print("· per-location resource maps …")
    manifest = {"snowy_mountains": "snowy_mountains.png"}
    for loc in LOCATIONS:
        slug = slugify(loc)
        if slug == "snowy_mountains":
            continue
        url = scrape_location_map(loc)
        if not url:
            print(f"  - {loc}: no map image found")
            continue
        try:
            save_image(http_get(wikia_full(url)),
                       ASSETS / "maps" / f"{slug}.png")
            manifest[slug] = f"{slug}.png"
            print(f"  ✓ {loc}")
        except Exception as e:                       # noqa: BLE001
            print(f"  ! {loc}: {e}")
    write_manifest(ASSETS / "maps", manifest)
    print(f"· maps manifest: {len(manifest)} maps")


def main():
    ap = argparse.ArgumentParser(description="Prefetch HUD image assets.")
    ap.add_argument("--quick", action="store_true",
                    help="only the two fixed-URL assets")
    ap.add_argument("--no-maps", action="store_true",
                    help="skip per-location map scraping")
    ap.add_argument("--no-monsters", action="store_true",
                    help="skip monster icon scraping")
    args = ap.parse_args()

    ASSETS.mkdir(exist_ok=True)
    fetch_fixed()
    if args.quick:
        print("done (quick mode).")
        return
    if not args.no_monsters:
        fetch_monsters()
    if not args.no_maps:
        fetch_maps()
    print("done.")


if __name__ == "__main__":
    main()
