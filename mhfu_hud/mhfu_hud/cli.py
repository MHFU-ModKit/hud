"""Command-line entry point for the MHFU live HUD."""

import argparse
import os

# Belt-and-suspenders: stop SDL2 from spinning up its HID joystick driver
# even if a future code path accidentally calls pygame.init(). Must be set
# before SDL is imported (i.e. before `from .app import HUDApp`). See
# app.py for the primary fix (selective pygame subsystem init).
os.environ.setdefault("SDL_JOYSTICK_HIDAPI", "0")
os.environ.setdefault("SDL_JOYSTICK_DISABLE_MFI", "1")
# Quiet pygame's import banner.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from .app import HUDApp                                    # noqa: E402
from .reader import MemoryReader                           # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mhfu-hud",
        description="Real-time MHFU game-state HUD for PPSSPP (read-only).")
    ap.add_argument("--host", default=None,
                    help="PPSSPP debugger host (default: auto-discover)")
    ap.add_argument("--port", type=int, default=None,
                    help="PPSSPP debugger port (default: auto-discover)")
    ap.add_argument("--poll-hz", type=float, default=3.0,
                    help="memory poll rate in Hz (default: 3 — higher rates "
                         "hitch the emulator)")
    ap.add_argument("--fullscreen", action="store_true",
                    help="start in fullscreen")
    args = ap.parse_args(argv)

    reader = MemoryReader(host=args.host, port=args.port,
                          poll_hz=args.poll_hz)
    reader.start()
    try:
        HUDApp(reader, fullscreen=args.fullscreen).run()
    finally:
        reader.stop()


if __name__ == "__main__":
    main()
