"""HUD layouts — one per game context, all extending the Layout base."""

from .base import Layout
from .quest import QuestLayout
from .village import VillageLayout

__all__ = ["Layout", "QuestLayout", "VillageLayout"]
