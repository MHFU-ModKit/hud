"""Layout base class.

A Layout draws one game-context HUD onto the fixed virtual canvas. Layouts
own their own transient UI state (e.g. which monster is selected) and may
consume key presses. They never touch the network or the snapshot producer.
"""

import pygame

from ..theme import C
from .. import widgets as W


class Layout:
    name = "base"

    def __init__(self, assets, calib):
        self.assets = assets
        self.calib = calib

    def handle_key(self, key, snapshot) -> bool:
        """Handle a pygame key constant. Return True if consumed."""
        return False

    def handle_click(self, canvas_pos, snapshot) -> bool:
        """Handle a left click in canvas coordinates. Return True if consumed."""
        return False

    def render(self, surface, snapshot):
        raise NotImplementedError

    # --- shared drawing ----------------------------------------------------

    @staticmethod
    def blit_cover(surface, image, rect):
        """Scale `image` to fully cover `rect` (cropping overflow), centred."""
        if image is None:
            pygame.draw.rect(surface, C.PANEL, rect)
            return
        iw, ih = image.get_size()
        scale = max(rect.width / iw, rect.height / ih)
        scaled = pygame.transform.smoothscale(
            image, (int(iw * scale) + 1, int(ih * scale) + 1))
        sr = scaled.get_rect(center=rect.center)
        prev = surface.get_clip()
        surface.set_clip(rect)
        surface.blit(scaled, sr)
        surface.set_clip(prev)

    @staticmethod
    def dim(surface, rect, alpha=110):
        veil = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        veil.fill((0, 0, 0, alpha))
        surface.blit(veil, rect)
