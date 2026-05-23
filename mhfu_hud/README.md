# MHFU Live HUD

A standalone, real-time game-state monitor for **Monster Hunter Freedom
Unite** running under **PPSSPP**. Start it next to the emulator; it attaches
over PPSSPP's debugger WebSocket, polls memory, parses the live game state,
and renders it in a HUD-style window.

It is a **separate project** from the `mhfu_bot` reverse-engineering toolkit
in `../src/` — it ships its own copy of the debugger protocol and its own
venv. It shares nothing at runtime.

## Safety: it cannot influence gameplay

The HUD is **strictly read-only**. Its PPSSPP client (`mhfu_hud/ppsspp.py`)
exposes memory *reads* only — no input injection, no breakpoints, no memory
writes. Debugger memory reads do not pause emulation. Polling runs in a
background thread at ~10 Hz with batched region reads, so it adds no
perceptible stutter and never sends a stray button press.

## Setup

```bash
cd mhfu_hud
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# one-time: prefetch map / background / monster-icon images
.venv/bin/python tools/fetch_assets.py
```

In PPSSPP: **Settings > Tools > Developer Tools** — enable *Allow remote
debugger* (and *Remote debugger on startup* is convenient).

## Run

```bash
.venv/bin/python run.py            # or:  .venv/bin/python -m mhfu_hud
```

The HUD auto-discovers PPSSPP (no fixed port needed). Start order does not
matter — it waits for PPSSPP and reconnects if the emulator restarts.

Options:

```
--host HOST     PPSSPP debugger host   (default: auto-discover)
--port PORT     PPSSPP debugger port   (default: auto-discover)
--poll-hz HZ    memory poll rate       (default: 10)
--fullscreen    start fullscreen
```

## Layouts

The HUD switches layout automatically from the game state:

- **Village** — village background art with the hunter's position/heading,
  vitals panel, raw oracles.
- **Quest** — the location resource-map centred and large, with loaded
  entities projected onto it; vitals, quest timer, monster roster, a
  per-monster detail panel, and a full detail page.
- **Status screen** — shown when disconnected / in menus / loading.

Data that has not been reverse-engineered yet (sharpness, max-HP cap, item
pouch, …) renders as a labelled placeholder rather than a fake value.

## Controls

| Key | Action |
|-----|--------|
| `F1` | toggle help |
| `F2` / `F3` / `F4` | layout: auto / force village / force quest |
| `F11` | fullscreen |
| `ESC` | close overlay, else quit |
| `TAB` / `]` | select next monster |
| `[` | select previous monster |
| `ENTER` | open/close monster detail page |
| `M` | cycle the quest map image |
| `C` | calibration mode |
| `+` `-` `,` `.` `T` arrows `S` | calibrate (scale / rotate / mode / nudge / save) |

Click a monster marker or roster row to select it.

## Map calibration

The world-coordinate → map-pixel transform is not yet known from RE work, so
the quest map defaults to **player-centered** mode: the hunter is pinned to
the map centre and monsters are drawn relative to them (radar style). Press
`C`, then `+`/`-`/`,`/`.` to dial in scale and rotation; `T` switches to
**fixed** mode where arrows nudge a world origin. `S` saves to
`config/calibration.json`.

## Architecture

```
run.py / -m mhfu_hud      entry point
mhfu_hud/
  ppsspp.py     standalone read-only PPSSPP debugger WebSocket client
  addresses.py  MHFU EU memory addresses + struct offsets
  reader.py     background polling thread -> GameSnapshot
  state.py      snapshot dataclasses (thread-handoff data)
  monster_db.py monster type-byte -> name -> icon mapping
  calibration.py world->image projection, persisted tunables
  assets.py     image loading + scale cache
  theme.py / widgets.py / panels.py   drawing primitives
  app.py        pygame window, main loop, layout switching, scaling
  layouts/      village.py, quest.py  (extend Layout in base.py)
tools/
  fetch_assets.py  prefetch wiki images
  smoke_render.py  offline layout preview -> tools/_preview/*.png
```

The reader thread and the pygame thread communicate by atomic snapshot
hand-off — the reader publishes a fresh immutable `GameSnapshot` each cycle.

## Extending

- **New layout**: subclass `layouts/base.Layout`, register it in
  `app.HUDApp.layouts`.
- **New parsed field**: add the address to `addresses.py`, read it in
  `reader._poll`, add it to the relevant `state.py` dataclass, draw it.
- **New monster**: add its type byte to `monster_db.TYPE_NAMES`; the icon is
  resolved from `assets/monsters/<slug>.png`.

Memory addresses are for **MHFU EU (ULES01213)** and come from
`../docs/agent_memory_map.md`.
