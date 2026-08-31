"""
ui/widgets.py
-------------
Reusable in-panel controls: sliders, stat rows / KPI cards, sparkline,
progress-ish bars, toggle buttons, preset chips.
All drawing is immediate-mode on a pygame Surface (no retained state),
except sliders which need hit-testing, handled via App.handle_event.
"""

import pygame

from ui import theme as T


# ------------------------------------------------------------------ stats
def stat_row(surf, rect, label, value, value_color=T.C.TEXT, value_size=15,
              label_color=T.C.TEXT_DIM):
    T.text(surf, (rect.x, rect.y), label, 12, label_color)
    T.text(surf, (rect.right, rect.y), value, value_size, value_color, anchor="tr")


def kpi_card(surf, rect, title, rows, sub=None):
    """rect : pygame.Rect ; rows : dict label->(value_str, color)."""
    T.panel(surf, rect)
    T.text(surf, (rect.x + 10, rect.y + 7), title, 11, T.C.TEXT_DIM)
    y = rect.y + 24
    for label, (val, col) in rows.items():
        T.text(surf, (rect.x + 12, y), label, 12, T.C.TEXT_DIM)
        T.text(surf, (rect.right - 12, y), val, 13, col, anchor="tr")
        y += 17
    return y


# ------------------------------------------------------------------ bars
def hbar(surf, rect, frac, color, min_frac_color=None, label="", bg=T.C.PANEL_2):
    """Horizontal value bar (0..1)."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, bg, rect)
    w = int(round(rect.w * max(0.0, min(1.0, frac))))
    if w > 0:
        pygame.draw.rect(surf, color, (rect.x, rect.y, w, rect.h))
    pygame.draw.rect(surf, T.C.BORDER, rect, 1)
    if label:
        T.text(surf, (rect.x + 4, rect.y - 1), label, 10, T.C.TEXT_DIM)


def badge(surf, rect, s, color):
    pygame.draw.rect(surf, tuple(max(0, c // 5) for c in color), rect)
    pygame.draw.rect(surf, color, rect, 1)
    T.text(surf, (rect.centerx, rect.centery), s, 16, color, bold=True, anchor="cc")


# ------------------------------------------------------------------ gauge
def state_gauge(surf, state):
    """Nothing fancy - state badge + confidence handled by the caller;
    kept as a namespace for future meters."""
    return None


# ------------------------------------------------------------------ sparkline
def sparkline(surf, rect, series, color=T.C.CYAN, band=None, min_v=0.0, max_v=1.0):
    """series : list[float].  band : optional (low, high) to shade a target band."""
    if band:
        band_r = pygame.Rect(rect.x, rect.y + int(rect.h * (band[1] / (max_v - min_v) or 1)),
                             rect.w, max(1, int(rect.h * (band[1] - band[0]) / (max_v - min_v))))
        band_r = pygame.Rect(rect.x, band_r.top, rect.w, band_r.h)
        pygame.draw.rect(surf, T.C.PANEL_2, band_r)
    xs = [rect.x + rect.w * i / max(1, len(series) - 1) for i in range(len(series))]
    pts = []
    for x, v in zip(xs, series):
        yy = rect.bottom - rect.h * (v - min_v) / (max_v - min_v)
        pts.append((int(x), int(max(rect.top, min(rect.bottom, yy)))))
    if len(pts) > 1:
        pygame.draw.lines(surf, T.C.BORDER, False, pts, 1)
        pygame.draw.lines(surf, color, False, pts, 2)


# ------------------------------------------------------------------ slider
class Slider:
    """Drag-to-set 0..100 control.

    handle_event returns 'changed' bool; GUI polls .value after events.
    """

    def __init__(self, rect, label, value=0, color=T.C.CYAN, fmt="{:>3d}"):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.value = clampf(value, 0, 100)
        self.color = color
        self.fmt = fmt
        self.dragging = False

    @property
    def frac(self):
        return self.value / 100.0

    def set_frac(self, f):
        self.value = clampf(f * 100.0, 0, 100)

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def drag_to(self, x):
        self.set_frac((x - self.rect.x) / self.rect.w)

    def draw(self, surf, value_text=None):
        T.text(surf, (self.rect.x, self.rect.y - 6), self.label, 11, T.C.TEXT_DIM)
        track = pygame.Rect(self.rect.x, self.rect.y + 14, self.rect.w, 8)
        pygame.draw.rect(surf, T.C.PANEL_2, track)
        w = int(round(track.w * self.frac))
        if w:
            pygame.draw.rect(surf, self.color, (track.x, track.y, w, track.h))
        pygame.draw.rect(surf, T.C.BORDER, track, 1)
        knob = pygame.Rect(track.x + w - 4, track.y - 3, 9, 14)
        pygame.draw.rect(surf, T.C.TEXT, knob)
        T.text(surf, (track.right, track.y - 5),
               value_text if value_text is not None else self.fmt.format(self.value),
               11, T.C.TEXT, anchor="tr")


# ------------------------------------------------------------------ button
class Button:
    def __init__(self, rect, label, color=T.C.CYAN, key=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color
        self.key = key

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, active_color=None):
        col = active_color or self.color
        pygame.draw.rect(surf, tuple(max(0, c // 4) for c in col), self.rect)
        pygame.draw.rect(surf, col, self.rect, 1)
        T.text(surf, (self.rect.centerx, self.rect.centery), self.label, 12, col,
               bold=True, anchor="cc")


# ------------------------------------------------------------------ chips
class Chip:
    """Preset selector chip (multi-state pick is handled by the app)."""

    def __init__(self, rect, label, color=T.C.CYAN):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, selected=False):
        col = self.color if selected else T.C.TEXT_DIM
        fill = tuple(max(0, c // 3) for c in self.color) if selected else T.C.PANEL_2
        pygame.draw.rect(surf, fill, self.rect)
        pygame.draw.rect(surf, col, self.rect, 1)
        T.text(surf, (self.rect.centerx, self.rect.centery), self.label, 11, col,
               bold=selected, anchor="cc")


def clampf(v, lo, hi):
    return max(lo, min(hi, v))