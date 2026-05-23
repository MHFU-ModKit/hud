"""MHFU live HUD — a standalone real-time game-state monitor for PPSSPP.

Runs beside PPSSPP, attaches over the debugger WebSocket, polls memory
read-only, and renders the parsed state in a pygame HUD. It never injects
input or writes memory, so it cannot influence gameplay.
"""

__version__ = "0.1.0"
