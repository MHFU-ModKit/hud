"""Command-line entry point for the MHFU live HUD."""

import argparse

from .app import HUDApp
from .reader import MemoryReader


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mhfu-hud",
        description="Real-time MHFU game-state HUD for PPSSPP (read-only).")
    ap.add_argument("--host", default=None,
                    help="PPSSPP debugger host (default: auto-discover)")
    ap.add_argument("--port", type=int, default=None,
                    help="PPSSPP debugger port (default: auto-discover)")
    ap.add_argument("--poll-hz", type=float, default=10.0,
                    help="memory poll rate in Hz (default: 10)")
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
