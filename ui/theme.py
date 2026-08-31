"""
ui/theme.py
-----------
Mission-console visual language: dark aerospace palette, a small set of
monospace fonts, and tiny drawing helpers so every widget shares one look.
"""

import pygame


# ---------------------------------------------------------------- palette
class C:
    BG = (10, 12, 18)            # main background
    PANEL = (16, 20, 30)
    PANEL_2 = (22, 28, 40)
    BORDER = (42, 52, 72)
    TEXT = (208, 218, 232)
    TEXT_DIM = (120, 132, 152)
    TEXT_FAINT = (70, 80, 98)

    CYAN = (72, 220, 255)
    CYAN_DIM = (46, 128, 160)
    GREEN = (90, 235, 150)
    GREEN_DIM = (52, 128, 92)
    AMBER = (255, 196, 86)
    AMBER_DIM = (150, 110, 40)
    RED = (255, 96, 96)
    PURPLE = (190, 130, 255)

    GRID = (30, 38, 54)

    STATE = {
        "SEARCHING": AMBER,
        "COASTING": CYAN,
        "LOCKED": GREEN,
        "LOST": RED,
    }


# ---------------------------------------------------------------- fonts
def _font(size, bold=False):
    return pygame.font.SysFont("consolas,menlo,dejavusansmono,monospace",
                               size, bold=bold)


_FONTS = {}
_FONTS_B = {}


def font(size, bold=False):
    cache = _FONTS_B if bold else _FONTS
    f = cache.get(size)
    if f is None:
        f = _font(size, bold)
        cache[size] = f
    return f


# ---------------------------------------------------------------- drawing
def text(surf, pos, s, size=13, color=C.TEXT, bold=False, anchor="tl"):
    """Draw text; anchor tl/tr/bl/br/cc for quick layout."""
    img = font(size, bold).render(s, True, color)
    r = img.get_rect()
    x, y = pos
    if "r" in anchor:
        x -= r.w
    elif "c" in anchor:
        x -= r.w // 2
    if "b" in anchor:
        y -= r.h
    elif anchor.endswith("c"):
        y -= r.h // 2
    surf.blit(img, (x, y))
    return r.w, r.h


def panel(surf, rect, fill=C.PANEL, border=C.BORDER):
    pygame.draw.rect(surf, fill, rect)
    pygame.draw.rect(surf, border, rect, 1)


def hdr(surf, text, rect, color=C.CYAN):
    """Section header with accent tick."""
    pygame.draw.rect(surf, color, (rect.x, rect.y, 3, rect.h))
    text(surf, (rect.x + 9, rect.y + rect.h // 2 - 7), text, 11, C.TEXT_DIM)