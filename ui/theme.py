"""
ui/theme.py  —  FSOC-PAT Deep Space Tactical visual language v2
"""
import math
import pygame


class C:
    BG       = (2, 4, 10)
    PANEL    = (8, 13, 26)
    PANEL_2  = (14, 22, 42)
    PANEL_3  = (22, 34, 60)
    BORDER   = (28, 44, 72)
    BORDER_B = (48, 76, 118)
    BORDER_DIM = (18, 26, 44)

    TEXT       = (212, 228, 248)
    TEXT_DIM   = (146, 181, 216)
    TEXT_FAINT = (104, 132, 166)

    CYAN      = (0, 210, 255)
    CYAN_DIM  = (0, 96, 140)
    CYAN_FILL = (0, 28, 54)
    GREEN     = (0, 255, 100)
    GREEN_DIM = (0, 160, 64)
    GREEN_FILL= (0, 44, 20)
    AMBER     = (255, 178, 0)
    AMBER_DIM = (160, 100, 0)
    AMBER_FILL= (54, 36, 0)
    RED       = (255, 46, 46)
    RED_DIM   = (138, 22, 22)
    RED_FILL  = (58, 8, 8)
    PURPLE    = (162, 80, 255)
    PURPLE_DIM= (80, 38, 142)
    PURPLE_FILL=(34, 14, 66)
    TEAL      = (0, 200, 180)

    GRID = (16, 28, 48)

    STATE = {
        "SEARCHING":    (255, 178, 0),
        "TENTATIVE":    (0, 210, 255),
        "COASTING":     (0, 196, 240),
        "LOCKED":       (0, 255, 100),
        "DEGRADED_LOCK":(0, 180, 68),
        "REACQUIRING":  (162, 80, 255),
        "LOST":         (255, 46, 46),
    }

    STATE_FILL = {
        "SEARCHING":    (54, 38, 0),
        "TENTATIVE":    (0, 34, 56),
        "COASTING":     (0, 30, 52),
        "LOCKED":       (0, 52, 22),
        "DEGRADED_LOCK":(0, 40, 18),
        "REACQUIRING":  (42, 16, 72),
        "LOST":         (64, 8, 8),
    }


# ---------------------------------------------------------------- fonts
def _font(size, bold=False):
    size = max(9, int(round(size * 1.12)))
    return pygame.font.SysFont(
        "consolas,menlo,dejavusansmono,monospace", size, bold=bold)


_FONTS, _FONTS_B = {}, {}


def font(size, bold=False):
    cache = _FONTS_B if bold else _FONTS
    f = cache.get(size)
    if f is None:
        f = _font(size, bold)
        cache[size] = f
    return f


# ---------------------------------------------------------------- text
def text(surf, pos, s, size=13, color=C.TEXT, bold=False, anchor="tl"):
    img = font(size, bold).render(s, True, color)
    r = img.get_rect()
    x, y = pos
    # Horizontal
    if anchor in ("tr", "br", "rc"):
        x -= r.w
    elif anchor in ("cc", "tc", "bc"):
        x -= r.w // 2
    # anchor "tl", "bl", "lc" → x unchanged (left-aligned)
    # Vertical
    if anchor in ("bl", "br", "bc"):
        y -= r.h
    elif anchor in ("cc", "lc", "rc"):
        y -= r.h // 2
    # anchor "tl", "tr", "tc" → y unchanged (top-aligned)
    surf.blit(img, (x, y))
    return r.w, r.h


def fit_text(surf, rect, s, size=13, color=C.TEXT, bold=False,
             padding=8, anchor="cc"):
    """Render readable text that stays inside a compact UI rectangle."""
    max_width = max(1, rect.w - padding * 2)
    draw_size = size
    while draw_size > 9 and font(draw_size, bold).size(s)[0] > max_width:
        draw_size -= 1
    text(surf, (rect.centerx, rect.centery), s, draw_size, color,
         bold=bold, anchor=anchor)


# ---------------------------------------------------------------- panels
def panel(surf, rect, fill=C.PANEL, border=C.BORDER, accent=None, radius=3):
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    pygame.draw.rect(surf, border, rect, 1, border_radius=radius)
    if accent:
        bar = pygame.Rect(rect.x + 1, rect.y + 4, 3, rect.h - 8)
        pygame.draw.rect(surf, accent, bar, border_radius=1)


def angled_panel(surf, rect, fill=C.PANEL, border=C.BORDER, cut=12, accent=None):
    """Panel with bevelled top-right and bottom-left corners."""
    r = rect
    pts = [
        (r.x, r.y),
        (r.right - cut, r.y),
        (r.right, r.y + cut),
        (r.right, r.bottom),
        (r.x + cut, r.bottom),
        (r.x, r.bottom - cut),
    ]
    pygame.draw.polygon(surf, fill, pts)
    pygame.draw.polygon(surf, border, pts, 1)
    if accent:
        pygame.draw.line(surf, accent, (r.x + 1, r.y + 4), (r.x + 1, r.bottom - 4), 3)


# ---------------------------------------------------------------- section header
def section_hdr(surf, x, y, label, color=C.CYAN, panel_w=None):
    """Accent tick + section label + optional full-width underline."""
    pygame.draw.rect(surf, color, (x, y, 3, 14), border_radius=1)
    text(surf, (x + 8, y), label, 9, C.TEXT_DIM)
    if panel_w:
        pygame.draw.line(surf, C.BORDER, (x, y + 16), (x + panel_w, y + 16), 1)


# ---------------------------------------------------------------- glow + pulse
def draw_glow(surf, center, radius, color, alpha=50):
    size = radius * 2 + 4
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    for r in range(radius, 0, -1):
        a = int(alpha * (1 - r / radius) ** 2)
        c = (*color, max(0, min(255, a)))
        pygame.draw.circle(glow, c, (size // 2, size // 2), r)
    surf.blit(glow, (center[0] - size // 2, center[1] - size // 2),
              special_flags=pygame.BLEND_RGBA_ADD)


def pulse(speed=2.0):
    """0..1 sinusoidal pulse keyed to real time."""
    return (math.sin(pygame.time.get_ticks() / 1000.0 * speed * math.pi) + 1) / 2


# ---------------------------------------------------------------- arc gauge
def arc_gauge(surf, center, radius, frac, color, bg=C.PANEL_3, width=5):
    """270-degree arc gauge: 0=bottom-left 1=bottom-right."""
    cx, cy = center
    start_a = 135.0   # degrees, measured from +x CCW (pygame convention)
    sweep   = 270.0
    segs = max(1, int(frac * 60))
    total_segs = 60

    def _pt(deg, r=radius):
        rad = math.radians(deg)
        return (cx + r * math.cos(rad), cy + r * math.sin(rad))

    # background arc
    for i in range(total_segs):
        p1 = _pt(start_a + sweep * i / total_segs)
        p2 = _pt(start_a + sweep * (i + 1) / total_segs)
        pygame.draw.line(surf, bg, p1, p2, width)

    # foreground arc
    col = color
    for i in range(segs):
        p1 = _pt(start_a + sweep * i / total_segs)
        p2 = _pt(start_a + sweep * (i + 1) / total_segs)
        pygame.draw.line(surf, col, p1, p2, width)

    # end cap dot
    if frac > 0.02:
        ep = _pt(start_a + sweep * frac)
        pygame.draw.circle(surf, col, (int(ep[0]), int(ep[1])), width // 2 + 1)


# ---------------------------------------------------------------- legacy helpers
def hdr(surf, label, rect, color=C.CYAN):
    pygame.draw.rect(surf, color, (rect.x, rect.y, 3, rect.h))
    text(surf, (rect.x + 9, rect.y + rect.h // 2 - 7), label, 11, C.TEXT_DIM)


def state_badge(surf, rect, state_label, state_str):
    col = C.STATE.get(state_str, C.CYAN)
    fill = C.STATE_FILL.get(state_str, (0, 30, 50))
    pygame.draw.rect(surf, fill, rect, border_radius=3)
    pygame.draw.rect(surf, col, rect, 1, border_radius=3)
    text(surf, (rect.centerx, rect.centery - 8), state_label, 8, C.TEXT_FAINT,
         anchor="cc")
    text(surf, (rect.centerx, rect.centery + 4), state_str, 12, col, bold=True,
         anchor="cc")


def kpi_row(surf, x, y, label, value, val_color=C.TEXT, size_val=16):
    text(surf, (x, y), label, 8, C.TEXT_FAINT)
    text(surf, (x, y + 10), value, size_val, val_color, bold=True)
