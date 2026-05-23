#!/usr/bin/env python3
"""Live verification — connect to a running PPSSPP and dump parsed state.

Exercises the reader/parsing layer against real game memory without opening
the HUD window. Prints a few GameSnapshots and renders one frame of the
matching layout to tools/_preview/live.png.

    python tools/live_probe.py [--seconds 6] [--poll-hz 10]
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mhfu_hud.reader import MemoryReader  # noqa: E402
from mhfu_hud.state import Context  # noqa: E402

OUT = Path(__file__).resolve().parent / "_preview"


def dump(snap):
    p = snap.player
    print(f"[{time.strftime('%H:%M:%S')}] "
          f"conn={snap.connected} ctx={snap.context.value} "
          f"screen={snap.screen_state} map_sec={snap.map_section} "
          f"poll={snap.poll_latency_ms:.0f}ms  {snap.status_text}")
    if snap.context in (Context.VILLAGE, Context.QUEST):
        print(f"    player loaded={p.loaded} hp={p.hp}/{p.hp_max} "
              f"stam={p.stamina}/{p.stamina_max} drawn={p.weapon_drawn} "
              f"world={p.pos_world}")
    if snap.context == Context.QUEST:
        print(f"    quest_timer={snap.quest_timer_frames}f "
              f"carve={snap.carve_count} monsters={len(snap.monsters)}")
        for m in snap.monsters:
            print(f"      slot{m.slot} {m.name:14s} hp={m.hp:5d} "
                  f"type=0x{m.type_byte:02X} ai_behav={m.ai_behavior} "
                  f"ai324={m.ai_324} ai32c={m.ai_32c} "
                  f"pos={m.pos} ptr=0x{m.ptr:08X}")


def render_frame(snap):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    from mhfu_hud.app import HUDApp

    class _R:
        def __init__(self, s):
            self.snapshot = s

        def stop(self):
            pass

    app = HUDApp(_R(snap))
    for _ in range(2):
        app._render(snap)
        app.clock.tick(60)
    OUT.mkdir(exist_ok=True)
    pygame.image.save(app.canvas, str(OUT / "live.png"))
    pygame.quit()
    print(f"  rendered tools/_preview/live.png  (layout: {snap.context.value})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--poll-hz", type=float, default=10.0)
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    reader = MemoryReader(host=args.host, port=args.port,
                          poll_hz=args.poll_hz)
    reader.start()
    print(f"probing for {args.seconds:.0f}s …")
    last = None
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            snap = reader.snapshot
            dump(snap)
            last = snap
            time.sleep(1.0)
    finally:
        reader.stop()

    if last is not None and last.connected:
        render_frame(last)
    else:
        print("  (no live connection — skipped frame render)")


if __name__ == "__main__":
    main()
