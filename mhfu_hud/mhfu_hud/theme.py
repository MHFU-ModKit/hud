"""Colours, fonts and canvas sizing for the HUD.

Layouts are drawn against a fixed virtual canvas (CANVAS_W x CANVAS_H, the
PSP's 2x resolution) and the app scales that canvas to the real window. So
layout code can use absolute coordinates without caring about window size.
"""

import pygame

# Virtual canvas — 2x PSP native (480x272). Roughly PPSSPP's default window.
CANVAS_W = 960
CANVAS_H = 544


class C:
    """Palette. Monster-Hunter-ish: dark slate panels, warm amber accents."""
    BG            = (10, 12, 16)
    BG_QUEST      = (16, 18, 22)
    PANEL         = (26, 30, 38)
    PANEL_HI      = (34, 39, 49)
    PANEL_BORDER  = (62, 70, 86)
    TEXT          = (230, 232, 237)
    TEXT_DIM      = (132, 140, 154)
    TEXT_FAINT    = (84, 90, 102)
    ACCENT        = (235, 196, 92)
    HP_HIGH       = (96, 200, 104)
    HP_MID        = (228, 192, 80)
    HP_LOW        = (224, 78, 66)
    HP_RECOV      = (212, 96, 88)    # red bar — recoverable, behind green
    STAMINA       = (236, 214, 110)
    BAR_BACK      = (38, 42, 50)
    MONSTER       = (224, 96, 88)
    MONSTER_DIM   = (120, 64, 62)
    PLAYER        = (96, 184, 236)
    SELECT        = (255, 222, 120)
    OK            = (110, 200, 120)
    WARN          = (228, 168, 72)
    ERR           = (226, 86, 78)
    PLACEHOLDER   = (96, 102, 116)
    SHADOW        = (0, 0, 0)


_MONO_CANDIDATES = "menlo,monaco,dejavusansmono,consolas,couriernew,monospace"
_fonts: dict = {}


def font(size: int, bold: bool = False) -> pygame.font.Font:
    """Cached monospace font at a given pixel size."""
    key = (size, bold)
    f = _fonts.get(key)
    if f is None:
        try:
            f = pygame.font.SysFont(_MONO_CANDIDATES, size, bold=bold)
        except Exception:
            f = pygame.font.Font(None, size)
        _fonts[key] = f
    return f


def hp_color(fraction: float):
    """Bar colour by remaining-HP fraction."""
    if fraction <= 0.2:
        return C.HP_LOW
    if fraction <= 0.5:
        return C.HP_MID
    return C.HP_HIGH
