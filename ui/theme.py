"""
ui/theme.py
-----------
Mission-console visual language: dark aerospace palette, a small set of
monospace fonts, and tiny drawing helpers so every widget shares one look.
"""

import pygame


# ---------------------------------------------------------------- palette
class C:
    BG       = (6, 8, 14)             # near-black space background
    PANEL    = (12, 16, 26)
    PANEL_2  = (18, 24, 38)
    PANEL_3  = (24, 32, 50)           # raised card surface
    BORDER   = (38, 50, 72)
    BORDER_B = (60, 80, 110)          # bright border / divider

    TEXT       = (215, 225, 240)
    TEXT_DIM   = (130, 145, 168)
    TEXT_FAINT = (68, 80, 100)

    CYAN      = (0, 220, 255)
    CYAN_DIM  = (0, 110, 145)
    CYAN_FILL = (0, 40, 60)
    GREEN     = (50, 240, 140)
    GREEN_DIM = (30, 130, 80)
    GREEN_FILL= (10, 50, 28)
    AMBER     = (255, 200, 60)
    AMBER_DIM = (160, 115, 30)
    RED       = (255, 80, 80)
    RED_DIM   = (120, 30, 30)
    PURPLE    = (180, 120, 255)
    PURPLE_DIM= (80, 45, 140)
    TEAL      = (0, 200, 180)

    GRID = (22, 32, 50)

    STATE = {
        "SEARCHING":    AMBER,
        "TENTATIVE":    CYAN,
        "COASTING":     CYAN,
        "LOCKED":       GREEN,
        "DEGRADED_LOCK":GREEN_DIM,
        "REACQUIRING":  PURPLE,
        "LOST":         RED,
    }

    STATE_FILL = {
        "SEARCHING":    (80, 60, 0),
        "TENTATIVE":    (0, 50, 60),
        "COASTING":     (0, 50, 60),
        "LOCKED":       (0, 50, 20),
        "DEGRADED_LOCK":(10, 40, 20),
        "REACQUIRING":  (50, 20, 80),
        "LOST":         (60, 10, 10),
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


def panel(surf, rect, fill=C.PANEL, border=C.BORDER, accent=None):
    """Draw a card panel; accent draws a 3px colored left-edge bar."""
    pygame.draw.rect(surf, fill, rect, border_radius=2)
    pygame.draw.rect(surf, border, rect, 1, border_radius=2)
    if accent:
        bar = pygame.Rect(rect.x, rect.y + 2, 3, rect.h - 4)
        pygame.draw.rect(surf, accent, bar, border_radius=1)


def hdr(surf, label, rect, color=C.CYAN):
    """Section header with accent tick."""
    pygame.draw.rect(surf, color, (rect.x, rect.y, 3, rect.h))
    text(surf, (rect.x + 9, rect.y + rect.h // 2 - 7), label, 11, C.TEXT_DIM)


def draw_glow(surf, center, radius, color, alpha=60):
    """Draw a soft radial glow using an alpha-blended surface."""
    size = radius * 2 + 4
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    for r in range(radius, 0, -1):
        a = int(alpha * (1 - r / radius) ** 1.5)
        c = (*color, max(0, min(255, a)))
        pygame.draw.circle(glow, c, (size // 2, size // 2), r)
    surf.blit(glow, (center[0] - size // 2, center[1] - size // 2),
              special_flags=pygame.BLEND_RGBA_ADD)


def state_badge(surf, rect, state_label, state_str):
    """Draw a filled rounded state badge."""
    col = C.STATE.get(state_str, C.CYAN)
    fill = C.STATE_FILL.get(state_str, (0, 30, 50))
    pygame.draw.rect(surf, fill, rect, border_radius=3)
    pygame.draw.rect(surf, col, rect, 1, border_radius=3)
    text(surf, (rect.centerx, rect.centery - 8), state_label, 8, C.TEXT_FAINT,
         anchor="cc")
    text(surf, (rect.centerx, rect.centery + 4), state_str, 12, col, bold=True,
         anchor="cc")


def kpi_row(surf, x, y, label, value, val_color=C.TEXT, size_val=16):
    """Draw a label + large value pair."""
    text(surf, (x, y), label, 8, C.TEXT_FAINT)
    text(surf, (x, y + 10), value, size_val, val_color, bold=True)
