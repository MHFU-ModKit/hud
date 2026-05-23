"""Low-level pygame drawing helpers shared by the layouts."""

import math

import pygame

from .theme import C, font


def text(surface, value, pos, size=18, color=C.TEXT, bold=False,
         align="left", shadow=True):
    """Draw text. `align` is one of left / center / right. Returns its rect."""
    f = font(size, bold)
    img = f.render(str(value), True, color)
    rect = img.get_rect()
    setattr(rect, {"left": "topleft", "center": "midtop",
                   "right": "topright"}[align], pos)
    if shadow:
        sh = f.render(str(value), True, C.SHADOW)
        surface.blit(sh, (rect.x + 1, rect.y + 1))
    surface.blit(img, rect)
    return rect


def panel(surface, rect, title=None, fill=C.PANEL, border=C.PANEL_BORDER):
    """Rounded panel with an optional title bar caption."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(surface, fill, rect, border_radius=6)
    pygame.draw.rect(surface, border, rect, width=1, border_radius=6)
    if title:
        text(surface, title, (rect.x + 10, rect.y + 6), size=13,
             color=C.ACCENT, bold=True)
    return rect


def bar(surface, rect, fraction, fill, back=C.BAR_BACK, border=C.PANEL_BORDER):
    """Horizontal value bar. `fraction` is clamped to 0..1."""
    rect = pygame.Rect(rect)
    fraction = max(0.0, min(1.0, fraction))
    pygame.draw.rect(surface, back, rect, border_radius=3)
    if fraction > 0:
        fw = max(2, int(rect.width * fraction))
        pygame.draw.rect(surface, fill, (rect.x, rect.y, fw, rect.height),
                         border_radius=3)
    pygame.draw.rect(surface, border, rect, width=1, border_radius=3)


def hp_bar(surface, rect, current_frac, recov_frac, current_color,
           recov_color=C.HP_RECOV, back=C.BAR_BACK, border=C.PANEL_BORDER):
    """Layered HP bar with the recoverable (red) ceiling drawn behind the
    current (green) portion, mirroring the in-game HUD. Both fractions are
    in 0..1; `recov_frac` should be >= `current_frac`."""
    rect = pygame.Rect(rect)
    current_frac = max(0.0, min(1.0, current_frac))
    recov_frac = max(current_frac, min(1.0, recov_frac))
    pygame.draw.rect(surface, back, rect, border_radius=3)
    if recov_frac > 0:
        rw = max(2, int(rect.width * recov_frac))
        pygame.draw.rect(surface, recov_color,
                         (rect.x, rect.y, rw, rect.height), border_radius=3)
    if current_frac > 0:
        cw = max(2, int(rect.width * current_frac))
        pygame.draw.rect(surface, current_color,
                         (rect.x, rect.y, cw, rect.height), border_radius=3)
    pygame.draw.rect(surface, border, rect, width=1, border_radius=3)


def stat_block(surface, pos, label, value, size_label=12, size_value=24,
               color=C.TEXT, placeholder=False):
    """A small label-over-value stat readout. Returns the bottom y."""
    x, y = pos
    text(surface, label, (x, y), size=size_label, color=C.TEXT_DIM, bold=True)
    vcolor = C.PLACEHOLDER if placeholder else color
    r = text(surface, value, (x, y + size_label + 2), size=size_value,
             color=vcolor, bold=True)
    return r.bottom


def kv_rows(surface, pos, rows, size=14, line_h=20, key_color=C.TEXT_DIM,
            val_color=C.TEXT, key_w=120):
    """Draw (key, value) pairs as aligned rows. Returns bottom y."""
    x, y = pos
    for key, value in rows:
        text(surface, key, (x, y), size=size, color=key_color)
        text(surface, value, (x + key_w, y), size=size, color=val_color)
        y += line_h
    return y


def marker(surface, center, heading_rad, color, radius=10, selected=False):
    """A directional triangle pointing along `heading_rad` (None = dot)."""
    cx, cy = center
    if selected:
        pygame.draw.circle(surface, C.SELECT, (int(cx), int(cy)),
                           radius + 6, width=2)
    if heading_rad is None:
        pygame.draw.circle(surface, color, (int(cx), int(cy)), radius)
        pygame.draw.circle(surface, C.SHADOW, (int(cx), int(cy)), radius,
                           width=1)
        return
    # screen: +x right, +y down. heading 0 -> up.
    pts = []
    for ang_off, length in ((0, radius * 1.6), (2.4, radius),
                            (-2.4, radius)):
        a = heading_rad + ang_off
        pts.append((cx + math.sin(a) * length,
                    cy - math.cos(a) * length))
    pygame.draw.polygon(surface, color, pts)
    pygame.draw.polygon(surface, C.SHADOW, pts, width=1)


def fit_scale(src_size, box_size):
    """Largest scale that fits `src_size` inside `box_size`, preserving aspect."""
    sw, sh = src_size
    bw, bh = box_size
    if sw <= 0 or sh <= 0:
        return 1.0
    return min(bw / sw, bh / sh)


def placeholder_box(surface, rect, label="—"):
    """A hatched box standing in for data we cannot parse yet."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(surface, C.PANEL, rect, border_radius=4)
    pygame.draw.rect(surface, C.PLACEHOLDER, rect, width=1, border_radius=4)
    text(surface, label, rect.center, size=12, color=C.PLACEHOLDER,
         align="center")
