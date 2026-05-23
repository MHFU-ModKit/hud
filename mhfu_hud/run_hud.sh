#!/usr/bin/env bash
#
# Start the MHFU live HUD with all SDL/pygame env vars that keep it from
# fighting PPSSPP for gamepad / HID access.
#
# Why each variable matters:
#   SDL_JOYSTICK_HIDAPI=0          — disable SDL2's hidapi joystick backend.
#                                    On macOS the HUD's pygame would otherwise
#                                    race PPSSPP for IOHID reports, freezing
#                                    the gamepad at its last value.
#   SDL_JOYSTICK_DISABLE_MFI=1     — same idea for the Apple MFi backend
#                                    (gamepads claiming MFi-compatible APIs).
#   SDL_GAMECONTROLLER_IGNORE_DEVICES — if any device sneaks past, route it
#                                    to a do-nothing handler. Empty wildcard
#                                    catches everything ("0x0000/0x0000").
#   SDL_AUDIODRIVER=dummy          — HUD has no audio; skip audio init.
#   PYGAME_HIDE_SUPPORT_PROMPT=1   — silence pygame's banner.
#
# Usage:  ./run_hud.sh [extra args passed straight to run.py]
#
set -euo pipefail

HUD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${HUD_DIR}/.venv/bin/python"

if [[ ! -x "${PY}" ]]; then
    echo "[-] HUD venv missing at ${HUD_DIR}/.venv" >&2
    echo "    bootstrap with:  python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 2
fi

export SDL_JOYSTICK_HIDAPI=0
export SDL_JOYSTICK_DISABLE_MFI=1
export SDL_GAMECONTROLLER_IGNORE_DEVICES="0x0000/0x0000"
export SDL_AUDIODRIVER=dummy
export PYGAME_HIDE_SUPPORT_PROMPT=1

cd "${HUD_DIR}"
exec "${PY}" run.py "$@"
