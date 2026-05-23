#!/usr/bin/env python3
"""HP-cell diagnostic — watch memory regions for HP-like changes.

Polls candidate memory regions while you play. Any u16 that changes is a
candidate; the real player-HP cell should DROP when you take a hit and RISE
when you heal. Take a few hits (and maybe a potion) during the window.

    python tools/hp_probe.py [seconds]
"""

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mhfu_hud.ppsspp import PPSSPPClient, PPSSPPError  # noqa: E402

# (label, base, size) — regions to sweep for u16 changes.
REGIONS = [
    ("heap_player_block", 0x090B3800, 0x1000),
    ("player_structs",    0x090BA600, 0x1200),
    ("static_stamina",    0x08A8CA00, 0x0400),
]
HP_ADDR = 0x090B3724     # current HP (green bar); pinned 2026-05-23
STAM_ADDR = 0x08A8CB52   # current HUD 'stamina' cell


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 28.0
    c = PPSSPPClient()
    c.connect()
    print(f"connected {c.host}:{c.port} — watching {secs:.0f}s. "
          f"Take some hits / heal now.\n")

    stats = {}            # (label, addr) -> [min, max, first, last]
    samples = 0
    start = time.monotonic()
    end = start + secs
    next_log = start
    while time.monotonic() < end:
        for label, base, size in REGIONS:
            try:
                buf = c.read_memory(base, size)
            except PPSSPPError as e:
                print("read error:", e)
                c.close()
                return
            for off in range(0, len(buf) - 1, 2):
                v = buf[off] | (buf[off + 1] << 8)
                key = (label, base + off)
                s = stats.get(key)
                if s is None:
                    stats[key] = [v, v, v, v]
                else:
                    if v < s[0]:
                        s[0] = v
                    if v > s[1]:
                        s[1] = v
                    s[3] = v
        samples += 1
        if time.monotonic() >= next_log:
            try:
                hp = c.read_u16(HP_ADDR)
                st = c.read_u16(STAM_ADDR)
            except PPSSPPError:
                hp = st = -1
            print(f"  t+{time.monotonic()-start:5.1f}s  "
                  f"HUD-HP(0x{HP_ADDR:08X})={hp:<5d} "
                  f"HUD-STA(0x{STAM_ADDR:08X})={st}")
            next_log += 2.0
        time.sleep(0.2)
    c.close()

    print(f"\n{samples} samples. Changed u16 cells in plausible HP range "
          f"(1..2000):\n")
    rows = []
    for (label, addr), (mn, mx, first, last) in stats.items():
        if mn == mx or not (1 <= mx <= 2000):
            continue
        rows.append((label, addr, mn, mx, first, last, last - first))
    # net decrease first (damage), then widest swing
    rows.sort(key=lambda r: (r[6], -(r[3] - r[2])))
    for label, addr, mn, mx, first, last, delta in rows[:70]:
        flag = ""
        if addr == HP_ADDR:
            flag = "   <== current HUD 'HP'"
        elif addr == STAM_ADDR:
            flag = "   <== current HUD 'stamina'"
        print(f"  0x{addr:08X} [{label:18s}] min={mn:5d} max={mx:5d} "
              f"first={first:5d} last={last:5d} delta={delta:+d}{flag}")
    if not rows:
        print("  (nothing changed — no damage taken during the window?)")


if __name__ == "__main__":
    main()
