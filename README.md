<p align="center">
  <img src="misc/banner.svg" width="720" alt="MHFU-HUD">
</p>

# MHFU ModKit — live HUD

A standalone, real-time game-state monitor for **Monster Hunter Freedom Unite** running under
**PPSSPP**. Start it next to the emulator; it attaches over PPSSPP's debugger WebSocket, polls
memory, parses the live game state, and renders it in a HUD-style window — hunter, monsters,
map, items — plus a writable AI editor panel.

It is **strictly read-only** by default: memory reads only, no input injection, no breakpoints.
Debugger reads do not pause emulation; polling runs at ~10 Hz in a background thread.

## Setup

```bash
git clone https://github.com/MHFU-ModKit/hud.git
cd hud/mhfu_hud
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/fetch_assets.py      # one-time: map / background / monster-icon images
```

In PPSSPP: **Settings > Tools > Developer Tools** — enable *Allow remote debugger*.

## Run

```bash
.venv/bin/python run.py            # or:  .venv/bin/python -m mhfu_hud
```

The HUD auto-discovers PPSSPP; start order does not matter. The full guide — panels, the
calibration file, the AI editor and what it writes — is [`mhfu_hud/README.md`](mhfu_hud/README.md).

The artwork it draws with is Capcom's, hosted on the Monster Hunter Fandom wiki; `fetch_assets.py`
downloads it to your machine and nothing of it is in this repository.

## No game data is included

This repository contains **no game files, no extracted assets, no artwork** — not the ISO, not
decrypted archives, not models or textures, not dumped tables. All of it is gitignored and is
reproduced from your own legally obtained copy of the game (see the `formats` repo's
`docs/ASSETS.md`). Everything targets **MHFU EU (ULES01213)**; addresses will not line up with a
JP or NA build.

## About this repository

`hud` is one of the [MHFU-ModKit](https://github.com/MHFU-ModKit) repositories. They are cut
from one upstream research repository and re-published from it, so they move in lockstep — a
file that appears in two of them is the same file at the same commit. Pull requests are welcome
here; an accepted one is applied upstream and comes back in the next export, which is why
`main` only takes changes through PRs. Issues are welcome for bugs, questions and findings alike.

The siblings:

- [`framework`](https://github.com/MHFU-ModKit/framework) — the runtime mod framework: one PRX, many mods, hot-reloaded Lua
- [`example-mods`](https://github.com/MHFU-ModKit/example-mods) — Lua mods and port manifests to learn from and drop on a memory stick
- [`monster-editor`](https://github.com/MHFU-ModKit/monster-editor) — the desktop editor for ported monsters
- [`blender-addon`](https://github.com/MHFU-ModKit/blender-addon) — import, edit and export big monsters in Blender
- [`formats`](https://github.com/MHFU-ModKit/formats) — the file-format library, ISO extraction and the MHP3rd→MHFU porter

## License

[MIT](LICENSE). Not affiliated with or endorsed by Capcom. Monster Hunter is a trademark of
Capcom Co., Ltd.
