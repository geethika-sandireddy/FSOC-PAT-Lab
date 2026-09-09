"""
ui/theme.py — FSOC-PAT SpaceX / NASA / ISRO Deep Space Mission Control Theme v3
Optimized for high-contrast presentation visibility from 10+ feet away.
"""
import math
import pygame


class C:
    # Deep space obsidian palette
    BG          = (4, 8, 18)         # #040812 deep space obsidian
    BG_DARK     = (2, 5, 12)
    PANEL       = (9, 16, 32)        # #091020 panel base
    PANEL_2     = (14, 24, 46)       # #0e182e card container
    PANEL_3     = (20, 34, 62)       # #14223e card highlight / inactive track
    CARD_BG     = (11, 20, 38)
    BORDER      = (28, 48, 82)       # visible card border
    BORDER_B    = (0, 230, 255, 80)  # glowing cyan border
    BORDER_DIM  = (20, 34, 58)

    # High-contrast readable typography palette
    TEXT        = (255, 255, 255)    # 100% pure crisp white for headers/values
    TEXT_DIM    = (195, 218, 245)    # high-contrast bright slate for labels
    TEXT_FAINT  = (145, 175, 210)    # clear readable secondary text / units
    TEXT_MUTED  = (110, 140, 175)

    # Mission status colors (high luminosity)
    CYAN        = (0, 225, 200)      # tactical cyan
    CYAN_ELEC   = (0, 235, 255)      # electric neon cyan
    CYAN_DIM    = (0, 110, 160)
    CYAN_FILL   = (0, 32, 64)
    GREEN       = (0, 255, 140)      # #00ff8c emerald lock
    GREEN_DIM   = (0, 175, 80)
    GREEN_FILL  = (0, 48, 24)
    AMBER       = (255, 185, 0)      # #ffb900 solar warning amber
    AMBER_DIM   = (175, 115, 0)
    AMBER_FILL  = (58, 40, 0)
    RED         = (255, 55, 85)      # #ff3755 critical alarm coral
    RED_DIM     = (150, 25, 40)
    RED_FILL    = (64, 10, 16)
    PURPLE      = (175, 95, 255)     # #af5fff aerospace violet
    PURPLE_DIM  = (95, 45, 160)
    PURPLE_FILL = (38, 16, 72)
    TEAL        = (0, 215, 195)
    ORANGE      = (255, 120, 30)

    GRID        = (16, 28, 52)

    STATE = {
        "SEARCHING":     (255, 185, 0),
        "TENTATIVE":     (0, 235, 255),
        "COASTING":      (0, 210, 250),
        "LOCKED":        (0, 255, 140),
        "DEGRADED_LOCK": (0, 195, 80),
        "REACQUIRING":   (175, 95, 255),
        "LOST":          (255, 55, 85),
    }

    STATE_FILL = {
        "SEARCHING":     (58, 40, 0),
        "TENTATIVE":     (0, 38, 64),
        "COASTING":      (0, 34, 58),
        "LOCKED":        (0, 56, 26),
        "DEGRADED_LOCK": (0, 44, 20),
        "REACQUIRING":   (46, 18, 80),
        "LOST":          (70, 10, 18),
    }


# ---------------------------------------------------------------- High-Visibility Typography
# Uses bold neo-grotesque sans-serif fonts by default for 10ft judge readability
def _font(size, bold=True):
    actual_size = max(12, int(round(size)))
    # Prioritize heavy, high-contrast system fonts on Windows/Linux/Mac
    return pygame.font.SysFont(
        "segoeui,bahnschrift,trebuchetms,arial,helvetica,sans-serif",
        actual_size, bold=bold)


def _font_mono(size, bold=True):
    actual_size = max(12, int(round(size)))
    return pygame.font.SysFont(
        "consolas,segoeui,monospace",
        actual_size, bold=bold)


_FONTS, _FONTS_B, _FONTS_MONO = {}, {}, {}


def font(size, bold=True):
    cache = _FONTS_B if bold else _FONTS
    f = cache.get(size)
    if f is None:
        f = _font(size, bold)
        cache[size] = f
    return f


def font_mono(size, bold=True):
    f = _FONTS_MONO.get(size)
    if f is None:
        f = _font_mono(size, bold)
        _FONTS_MONO[size] = f
    return f


# ---------------------------------------------------------------- Text rendering
def text(surf, pos, s, size=13, color=C.TEXT, bold=True, anchor="tl", mono=False):
    f = font_mono(size, bold) if mono else font(size, bold)
    img = f.render(str(s), True, color)
    r = img.get_rect()
    x, y = pos
    # Horizontal alignment
    if anchor in ("tr", "br", "rc"):
        x -= r.w
    elif anchor in ("cc", "tc", "bc"):
        x -= r.w // 2
    # Vertical alignment
    if anchor in ("bl", "br", "bc"):
        y -= r.h
    elif anchor in ("cc", "lc", "rc"):
        y -= r.h // 2
    surf.blit(img, (x, y))
    return r.w, r.h


def multiline_text(surf, pos, s, max_width, size=13, color=C.TEXT_DIM, bold=False, line_spacing=4, anchor="tl"):
    """Renders multi-line text that wraps cleanly within max_width with high legibility."""
    words = str(s).split(" ")
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
    max_w = 0
    curr_y = y
    for line in lines:
        lw, _ = text(surf, (x, curr_y), line, size=size, color=color, bold=bold, anchor=anchor)
        max_w = max(max_w, lw)
        curr_y += line_h + line_spacing
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * line_spacing
    return max_w, total_h


def fit_text(surf, rect, s, size=13, color=C.TEXT, bold=True, padding=6, anchor="cc"):
    """Render readable text that strictly stays inside rect without overflow."""
    rect = pygame.Rect(rect)
    max_width = max(1, rect.w - padding * 2)
    draw_size = max(12, size)
    f = font(draw_size, bold)
    tw, th = f.size(str(s))
    while draw_size > 12 and tw > max_width:
        draw_size -= 1
        f = font(draw_size, bold)
        tw, th = f.size(str(s))
    display_str = str(s)
    if tw > max_width and len(display_str) > 4:
        while len(display_str) > 3 and font(draw_size, bold).size(display_str + "…")[0] > max_width:
            display_str = display_str[:-1]
        display_str += "…"
    text(surf, (rect.centerx, rect.centery), display_str, draw_size, color, bold=bold, anchor=anchor)


# ---------------------------------------------------------------- Panels & Cards
def card(surf, rect, fill=C.CARD_BG, border=C.BORDER, radius=5, accent=None):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    pygame.draw.rect(surf, border, rect, 1, border_radius=radius)
    if accent:
        pygame.draw.rect(surf, accent, (rect.x, rect.y, 4, rect.h),
                         border_top_left_radius=radius, border_bottom_left_radius=radius)


def panel(surf, rect, fill=C.PANEL, border=C.BORDER, accent=None, radius=4):
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    pygame.draw.rect(surf, border, rect, 1, border_radius=radius)
    if accent:
        bar = pygame.Rect(rect.x + 1, rect.y + 4, 3, rect.h - 8)
        pygame.draw.rect(surf, accent, bar, border_radius=1)


def section_title(surf, x, y, title, accent=C.CYAN_ELEC):
    """Bold aerospace section title with cyan indicator."""
    pygame.draw.rect(surf, accent, (x, y + 2, 4, 18), border_radius=2)
    text(surf, (x + 12, y), title.upper(), 15, C.TEXT, bold=True)


def section_hdr(surf, x, y, title, color=C.CYAN_ELEC, panel_w=0):
    """Backward-compatible alias for section titles."""
    return section_title(surf, x, y, title, color)


def draw_metric_card(surf, rect, label, value, unit="", sub="", color=C.CYAN_ELEC, warn=False):
    """Large, high-contrast metric card visible from 10+ feet."""
    rect = pygame.Rect(rect)
    border_col = C.RED if warn else C.BORDER
    card(surf, rect, fill=C.PANEL_2, border=border_col, radius=5)
    # Label at top
    text(surf, (rect.x + 14, rect.y + 9), label.upper(), 12, C.TEXT_DIM, bold=True)
    # Huge bold value
    vw, vh = text(surf, (rect.x + 14, rect.y + 28), str(value), 26, color, bold=True, mono=True)
    # Unit
    if unit:
        text(surf, (rect.x + 18 + vw, rect.y + 36), unit, 13, C.TEXT_FAINT, bold=True)
    # Subtext
    if sub:
        text(surf, (rect.x + 14, rect.bottom - 18), sub, 12, C.TEXT_MUTED, bold=False)


def draw_pill_badge(surf, rect, text_str, color=C.GREEN, bg=None):
    """Sleek glowing pill badge for state/lock status."""
    rect = pygame.Rect(rect)
    fill = bg or (*color[:3], 36) if len(color) == 4 else (color[0] // 5, color[1] // 5, color[2] // 5)
    pygame.draw.rect(surf, fill, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surf, color, rect, 1, border_radius=rect.h // 2)
    text(surf, (rect.centerx, rect.centery), text_str, 12, color, bold=True, anchor="cc")


def draw_circular_arc_gauge(surf, cx, cy, radius, pct, color=C.CYAN_ELEC, label="", stroke=7):
    """High-contrast 240-degree circular arc gauge with center value."""
    start_deg = 150
    sweep_deg = 240
    total_segs = 48
    segs = max(1, int(round(clamp(pct / 100.0, 0.0, 1.0) * total_segs)))

    def _pt(deg, r):
        rad = math.radians(deg)
        return (cx + r * math.cos(rad), cy + r * math.sin(rad))

    # Background track
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
    text(surf, (cx, cy - 2), f"{int(round(pct))}%", 24, color, bold=True, anchor="cc", mono=True)
    # Bottom label
    if label:
        text(surf, (cx, cy + radius + 16), label.upper(), 12, C.TEXT_DIM, bold=True, anchor="cc")


def arc_gauge(surf, center, radius, frac, color, bg_color=C.PANEL_3, width=4):
    """Draw a circular arc gauge centered at center with fractional progress frac (0..1)."""
    cx, cy = center
    start_deg = 150
    sweep_deg = 240
    total_segs = 36
    segs = max(1, int(round(clamp(frac, 0.0, 1.0) * total_segs)))

    def _pt(deg, r):
        rad = math.radians(deg)
        return (cx + r * math.cos(rad), cy + r * math.sin(rad))

    for i in range(total_segs):
        p1 = _pt(start_deg + sweep_deg * i / total_segs, radius)
        p2 = _pt(start_deg + sweep_deg * (i + 1) / total_segs, radius)
        pygame.draw.line(surf, bg_color, p1, p2, width)

    for i in range(segs):
        p1 = _pt(start_deg + sweep_deg * i / total_segs, radius)
        p2 = _pt(start_deg + sweep_deg * (i + 1) / total_segs, radius)
        pygame.draw.line(surf, color, p1, p2, width)


def draw_hbar_labelled(surf, rect, frac, color, label, val_str="", bg=C.PANEL):
    rect = pygame.Rect(rect)
    text(surf, (rect.x, rect.y - 16), label.upper(), 12, C.TEXT_DIM, bold=True)
    if val_str:
        text(surf, (rect.right, rect.y - 16), val_str, 13, color, bold=True, anchor="tr", mono=True)
    pygame.draw.rect(surf, bg, rect, border_radius=3)
    w = int(round(rect.w * clamp(frac, 0.0, 1.0)))
    if w > 0:
        pygame.draw.rect(surf, color, (rect.x, rect.y, w, rect.h), border_radius=3)
    pygame.draw.rect(surf, C.BORDER, rect, 1, border_radius=3)


def pulse(speed=2.0):
    return (math.sin(pygame.time.get_ticks() / 1000.0 * speed * math.pi) + 1) / 2


def clamp(v, lo, hi):
    return max(lo, min(hi, v))
