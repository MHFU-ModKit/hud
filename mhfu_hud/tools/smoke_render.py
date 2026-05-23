#!/usr/bin/env python3
"""Offline render check — draws each layout with synthetic data to PNGs.

No PPSSPP needed. Useful for previewing the HUD and for catching draw-time
crashes. Output goes to tools/_preview/.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from mhfu_hud.app import HUDApp  # noqa: E402
from mhfu_hud.state import (Context, GameSnapshot, MonsterHUD,  # noqa: E402
                            PlayerHUD, Vec3)

OUT = Path(__file__).resolve().parent / "_preview"


class FakeReader:
    def __init__(self, snap):
        self.snapshot = snap

    def stop(self):
        pass


def quest_snapshot():
    player = PlayerHUD(
        loaded=True, pos_world=Vec3(18324, 320, 12833),
        pos_local=Vec3(5, 156, -2), facing_rad=0.6,
        hp=74, hp_recov=88, hp_max=100,
        stamina=214, stamina_max=320, weapon_drawn=True)
    monsters = [
        MonsterHUD(slot=1, ptr=0x090BD530, entity_id=0x01, type_byte=0x46,
                   pos=Vec3(15500, 0, 10700), hp=102, ai_behavior=5,
                   ai_324=2, ai_32c=9, name="Popo", icon_slug="popo",
                   hp_max=102),
        MonsterHUD(slot=2, ptr=0x090C1F90, entity_id=0x02, type_byte=0x46,
                   pos=Vec3(16200, 0, 13900), hp=88, ai_behavior=2,
                   ai_324=2, ai_32c=4, name="Popo", icon_slug="popo",
                   hp_max=102),
        MonsterHUD(slot=3, ptr=0x090C69F0, entity_id=0x03, type_byte=0x99,
                   pos=Vec3(20100, 0, 11800), hp=300, ai_behavior=10,
                   ai_324=1, ai_32c=0, name="Unknown 0x99", icon_slug=None,
                   hp_max=300),
    ]
    return GameSnapshot(
        connected=True, context=Context.QUEST, game_title="MHFU (ULES01213)",
        status_text="ok", screen_state=17, map_section=1,
        scene_object_ptr=0x08A8C6E0, quest_timer_frames=60 * 60 * 35,
        carve_count=0, player=player, monsters=monsters,
        camera_target=Vec3(18324, 320, 12833), poll_latency_ms=11.0,
        poll_count=421)


def village_snapshot():
    player = PlayerHUD(
        loaded=True, pos_world=Vec3(120, 40, -380), pos_local=Vec3(1, 2, 3),
        facing_rad=1.2, hp=150, hp_max=150, stamina=320, stamina_max=320,
        weapon_drawn=False)
    return GameSnapshot(
        connected=True, context=Context.VILLAGE, game_title="MHFU",
        status_text="ok", screen_state=17, map_section=35, player=player,
        poll_latency_ms=9.0, poll_count=120)


def disconnected_snapshot():
    return GameSnapshot(connected=False, context=Context.DISCONNECTED,
                        status_text="waiting for PPSSPP debugger (attempt 3)…")


def render(app, name, snap):
    for _ in range(2):                 # 2 frames so fps/clock settle
        app._render(snap)
        app.clock.tick(60)
    OUT.mkdir(exist_ok=True)
    pygame.image.save(app.canvas, str(OUT / f"{name}.png"))
    print(f"  ✓ {name}.png")


def main():
    print("rendering previews →", OUT)
    # one pygame session — quitting between renders would invalidate fonts
    app = HUDApp(FakeReader(disconnected_snapshot()))
    render(app, "quest", quest_snapshot())
    render(app, "village", village_snapshot())
    render(app, "disconnected", disconnected_snapshot())
    pygame.quit()
    print("done.")


if __name__ == "__main__":
    main()
