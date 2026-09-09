"""
ui/theme.py  —  FSOC-PAT Deep Space Tactical visual language v2
"""
import math
import pygame


class C:
    BG       = (3, 7, 18)        # #030712 deep aerospace black
    BG_DARK  = (2, 4, 10)
    PANEL    = (8, 14, 28)       # #080e1c panel base
    PANEL_2  = (12, 20, 38)      # #0c1426 card container
    PANEL_3  = (18, 28, 52)      # #121c34 highlight panel
    CARD_BG  = (10, 18, 34)
    BORDER   = (24, 42, 72)      # subtle border
    BORDER_B = (0, 212, 255, 60) # cyan accent border
    BORDER_DIM = (18, 28, 48)

    TEXT       = (240, 248, 255) # bright crisp white
    TEXT_DIM   = (182, 212, 242) # high-contrast secondary label
    TEXT_FAINT = (142, 174, 210) # clear readable tertiary/units (boosted contrast)

    CYAN       = (0, 212, 170)   # #00d4aa tactical cyan
    CYAN_ELEC  = (0, 212, 255)   # #00d4ff electric cyan
    CYAN_DIM   = (0, 96, 140)
    CYAN_FILL  = (0, 28, 54)
    GREEN      = (0, 255, 136)   # #00ff88 emerald lock
    GREEN_DIM  = (0, 160, 64)
    GREEN_FILL = (0, 44, 20)
    AMBER      = (255, 178, 0)   # #ffb200 amber warning
    AMBER_DIM  = (160, 100, 0)
    AMBER_FILL = (54, 36, 0)
    RED        = (255, 68, 68)   # #ff4444 critical red
    RED_DIM    = (138, 22, 22)
    RED_FILL   = (58, 8, 8)
    PURPLE     = (168, 85, 247)  # #a855f7 purple
    PURPLE_DIM = (80, 38, 142)
    PURPLE_FILL= (34, 14, 66)
    TEAL       = (0, 200, 180)
    ORANGE     = (249, 115, 22)  # #f97316

    GRID = (14, 24, 44)

    STATE = {
        "SEARCHING":    (255, 178, 0),
        "TENTATIVE":    (0, 212, 255),
        "COASTING":     (0, 196, 240),
        "LOCKED":       (0, 255, 136),
        "DEGRADED_LOCK":(0, 180, 68),
        "REACQUIRING":  (168, 85, 247),
        "LOST":         (255, 68, 68),
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
    # Enforce strict readable floor of 11 to ensure all words remain comfortably legible from 60cm
    actual_size = max(11, int(round(size)))
    return pygame.font.SysFont(
        "consolas,menlo,dejavusansmono,monospace", actual_size, bold=bold)


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


def multiline_text(surf, pos, s, max_width, size=12, color=C.TEXT_DIM, bold=False, line_spacing=4, anchor="tl"):
    """
    Renders human-friendly multi-line text that wraps naturally within max_width.
    Returns (max_rendered_w, total_rendered_h).
    """
    words = s.split(" ")
    lines = []
    cur = ""
    f = font(size, bold)
    for word in words:
        test = cur + (" " if cur else "") + word
        if f.size(test)[0] <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)

    x, y = pos
    line_h = f.get_height()
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * line_spacing
    max_w = 0

    curr_y = y
    for line in lines:
        lw, _ = text(surf, (x, curr_y), line, size=size, color=color, bold=bold, anchor=anchor)
        max_w = max(max_w, lw)
        curr_y += line_h + line_spacing
    return max_w, total_h


def fit_text(surf, rect, s, size=12, color=C.TEXT, bold=False,
             padding=6, anchor="cc"):
    """Render readable text that stays inside a UI rectangle with clean bounds."""
    rect = pygame.Rect(rect)
    max_width = max(1, rect.w - padding * 2)
    draw_size = max(11, size)
    f = font(draw_size, bold)
    tw, th = f.size(s)
    while draw_size > 11 and tw > max_width:
        draw_size -= 1
        f = font(draw_size, bold)
        tw, th = f.size(s)
    display_str = s
    if tw > max_width and len(s) > 4:
        while len(display_str) > 3 and font(draw_size, bold).size(display_str + "…")[0] > max_width:
            display_str = display_str[:-1]
        display_str += "…"
    text(surf, (rect.centerx, rect.centery), display_str, draw_size, color,
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
    pygame.draw.rect(surf, color, (x, y, 4, 16), border_radius=1)
    text(surf, (x + 10, y - 1), label, 12, C.TEXT_DIM, bold=True)
    if panel_w:
        pygame.draw.line(surf, C.BORDER, (x, y + 20), (x + panel_w, y + 20), 1)


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
    pygame.draw.rect(surf, color, (rect.x, rect.y, 4, rect.h))
    text(surf, (rect.x + 10, rect.y + rect.h // 2 - 8), label, 13, C.TEXT_DIM, bold=True)


def state_badge(surf, rect, state_label, state_str):
    col = C.STATE.get(state_str, C.CYAN)
    fill = C.STATE_FILL.get(state_str, (0, 30, 50))
    pygame.draw.rect(surf, fill, rect, border_radius=3)
    pygame.draw.rect(surf, col, rect, 1, border_radius=3)
    text(surf, (rect.centerx, rect.centery - 10), state_label, 11, C.TEXT_FAINT,
         anchor="cc")
    text(surf, (rect.centerx, rect.centery + 4), state_str, 14, col, bold=True,
         anchor="cc")


def kpi_row(surf, x, y, label, value, val_color=C.TEXT, size_val=18):
    text(surf, (x, y), label, 12, C.TEXT_FAINT)
    text(surf, (x, y + 14), value, size_val, val_color, bold=True)


# ---------------------------------------------------------------- SpaceX cards & gauges
def card(surf, rect, fill=C.CARD_BG, border=C.BORDER, radius=4, accent=None):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    pygame.draw.rect(surf, border, rect, 1, border_radius=radius)
    if accent:
        pygame.draw.rect(surf, accent, (rect.x, rect.y, 4, rect.h), border_top_left_radius=radius, border_bottom_left_radius=radius)


def section_title(surf, x, y, title, accent=C.CYAN_ELEC):
    pygame.draw.rect(surf, accent, (x, y + 1, 4, 16), border_radius=1)
    text(surf, (x + 10, y - 1), title, 14, C.TEXT, bold=True)


def draw_metric_card(surf, rect, label, value, unit="", sub="", color=C.CYAN_ELEC, warn=False):
    rect = pygame.Rect(rect)
    border_col = C.RED if warn else C.BORDER
    card(surf, rect, fill=C.PANEL_2, border=border_col)
    text(surf, (rect.x + 12, rect.y + 7), label.upper(), 11, C.TEXT_DIM, bold=True)
    vw, vh = text(surf, (rect.x + 12, rect.y + 22), value, 22, color, bold=True)
    if unit:
        text(surf, (rect.x + 16 + vw, rect.y + 28), unit, 12, C.TEXT_DIM)
    if sub:
        text(surf, (rect.x + 12, rect.y + 48), sub, 11, C.TEXT_FAINT)


def draw_circular_arc_gauge(surf, cx, cy, radius, pct, color=C.CYAN_ELEC, label="", stroke=6):
    """Circular arc gauge with center value and bottom label matching Figma Image 5."""
    # Background circle arc (240 degrees, open at bottom)
    start_deg = 150
    sweep_deg = 240
    total_segs = 48
    segs = max(1, int(round(clamp(pct / 100.0, 0.0, 1.0) * total_segs)))

    def _pt(deg, r):
        rad = math.radians(deg)
        return (cx + r * math.cos(rad), cy + r * math.sin(rad))

    # Dark background arc
    for i in range(total_segs):
        p1 = _pt(start_deg + sweep_deg * i / total_segs, radius)
        p2 = _pt(start_deg + sweep_deg * (i + 1) / total_segs, radius)
        pygame.draw.line(surf, C.PANEL_3, p1, p2, stroke)

    # Active glowing arc
    for i in range(segs):
        p1 = _pt(start_deg + sweep_deg * i / total_segs, radius)
        p2 = _pt(start_deg + sweep_deg * (i + 1) / total_segs, radius)
        pygame.draw.line(surf, color, p1, p2, stroke)

    # Center percentage
    text(surf, (cx, cy - 2), f"{int(round(pct))}%", 22, color, bold=True, anchor="cc")
    # Bottom label
    if label:
        text(surf, (cx, cy + radius + 14), label, 11, C.TEXT_DIM, bold=True, anchor="cc")


def draw_hbar_labelled(surf, rect, frac, color, label, val_str="", bg=C.PANEL):
    rect = pygame.Rect(rect)
    text(surf, (rect.x, rect.y - 14), label, 11, C.TEXT_DIM)
    if val_str:
        text(surf, (rect.right, rect.y - 14), val_str, 11, color, bold=True, anchor="tr")
    pygame.draw.rect(surf, bg, rect, border_radius=2)
    w = int(round(rect.w * clamp(frac, 0.0, 1.0)))
    if w > 0:
        pygame.draw.rect(surf, color, (rect.x, rect.y, w, rect.h), border_radius=2)
    pygame.draw.rect(surf, C.BORDER, rect, 1, border_radius=2)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))
