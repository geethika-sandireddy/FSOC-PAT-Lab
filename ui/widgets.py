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
def stat_row(surf, rect, label, value, value_color=T.C.TEXT, value_size=14,
              label_color=T.C.TEXT_FAINT):
    T.text(surf, (rect.x, rect.y + 1), label, 9, label_color)
    T.text(surf, (rect.right, rect.y), value, value_size, value_color,
           bold=True, anchor="tr")


def kpi_card(surf, rect, title, rows, sub=None):
    """rect : pygame.Rect ; rows : dict label->(value_str, color)."""
    T.panel(surf, rect)
    pygame.draw.rect(surf, T.C.BORDER_B, (rect.x, rect.y, rect.w, 1))
    T.text(surf, (rect.x + 8, rect.y + 6), title, 9, T.C.TEXT_DIM)
    y = rect.y + 22
    for label, (val, col) in rows.items():
        T.text(surf, (rect.x + 10, y + 1), label, 8, T.C.TEXT_FAINT)
        T.text(surf, (rect.right - 10, y), val, 13, col, bold=True, anchor="tr")
        y += 18
    return y


# ------------------------------------------------------------------ bars
def hbar(surf, rect, frac, color, min_frac_color=None, label="", bg=T.C.PANEL_2):
    """Horizontal value bar (0..1) with engineering tick marks."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, bg, rect)
    w = int(round(rect.w * max(0.0, min(1.0, frac))))
    if w > 0:
        pygame.draw.rect(surf, color, (rect.x, rect.y, w, rect.h))
    # quarter tick marks
    for t in (0.25, 0.5, 0.75):
        tx = rect.x + int(rect.w * t)
        pygame.draw.line(surf, T.C.PANEL_3,
                         (tx, rect.y + 1), (tx, rect.bottom - 1), 1)
    pygame.draw.rect(surf, T.C.BORDER, rect, 1)
    if label:
        T.text(surf, (rect.x + 4, rect.y - 1), label, 9, T.C.TEXT_DIM)


def badge(surf, rect, s, color):
    pygame.draw.rect(surf, tuple(max(0, c // 6) for c in color), rect)
    pygame.draw.rect(surf, color, rect, 1)
    T.text(surf, (rect.centerx, rect.centery), s, 14, color, bold=True, anchor="cc")


# ------------------------------------------------------------------ gauge
def state_gauge(surf, state):
    return None


# ------------------------------------------------------------------ sparkline
def sparkline(surf, rect, series, color=T.C.CYAN, band=None, min_v=0.0, max_v=1.0):
    """series : list[float].  band : optional (low, high) to shade a target band."""
    if band:
        band_r = pygame.Rect(rect.x, rect.y + int(rect.h * (band[1] / (max_v - min_v) or 1)),
                             rect.w, max(1, int(rect.h * (band[1] - band[0]) / (max_v - min_v))))
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
    """Drag-to-set 0..100 control."""

    TRACK_H = 6
    KNOB_W = 7
    KNOB_H = 14

    def __init__(self, rect, label, value=0, color=T.C.CYAN, fmt="{:>3d}",
                 enabled=True):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.value = int(round(clampf(value, 0, 100)))
        self.color = color
        self.fmt = fmt
        self.enabled = enabled
        self.dragging = False

    @property
    def frac(self):
        return self.value / 100.0

    def set_frac(self, f):
        self.value = int(round(clampf(f * 100.0, 0, 100)))

    def hit(self, pos):
        return self.selected_enabled() and self.rect.collidepoint(pos)

    def selected_enabled(self):
        return self.enabled

    def drag_to(self, x):
        if not self.enabled:
            return
        self.set_frac((x - self.rect.x) / self.rect.w)

    def draw(self, surf, value_text=None):
        if not self.enabled:
            self._draw_disabled(surf, value_text)
            return
        # label + value on same row
        lx, ly = self.rect.x, self.rect.y - 8
        T.text(surf, (lx, ly), self.label, 9, T.C.TEXT_DIM)
        val_str = value_text if value_text is not None else self.fmt.format(self.value)
        T.text(surf, (self.rect.right, ly), val_str, 9, T.C.TEXT, bold=True, anchor="tr")
        # track
        ty = self.rect.y + (self.rect.h - self.TRACK_H) // 2 + 6
        track = pygame.Rect(self.rect.x, ty, self.rect.w, self.TRACK_H)
        pygame.draw.rect(surf, T.C.PANEL_2, track)
        w = int(round(track.w * self.frac))
        if w:
            # subtle gradient feel: slightly darker fill, bright front edge
            pygame.draw.rect(surf, tuple(max(0, c // 2) for c in self.color),
                             (track.x, track.y, w, track.h))
            pygame.draw.line(surf, self.color,
                             (track.x + w - 1, track.y),
                             (track.x + w - 1, track.bottom - 1), 1)
        # tick marks at 25 / 50 / 75
        for t in (0.25, 0.5, 0.75):
            tx = track.x + int(track.w * t)
            pygame.draw.line(surf, T.C.BORDER,
                             (tx, track.y), (tx, track.bottom), 1)
        pygame.draw.rect(surf, T.C.BORDER, track, 1)
        # knob
        kx = track.x + w - self.KNOB_W // 2
        knob = pygame.Rect(kx, ty - (self.KNOB_H - self.TRACK_H) // 2,
                           self.KNOB_W, self.KNOB_H)
        pygame.draw.rect(surf, T.C.PANEL_3, knob)
        pygame.draw.rect(surf, T.C.TEXT_DIM, knob, 1)

    def _draw_disabled(self, surf, value_text=None):
        T.text(surf, (self.rect.x, self.rect.y - 8),
               self.label + "  (N/A)", 9, T.C.TEXT_FAINT)
        ty = self.rect.y + (self.rect.h - self.TRACK_H) // 2 + 6
        track = pygame.Rect(self.rect.x, ty, self.rect.w, self.TRACK_H)
        pygame.draw.rect(surf, T.C.PANEL_2, track)
        pygame.draw.rect(surf, T.C.BORDER_DIM, track, 1)
        T.text(surf, (self.rect.right, self.rect.y - 8),
               "0", 9, T.C.TEXT_FAINT, anchor="tr")


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
        fill = tuple(max(0, c // 6) for c in col)
        pygame.draw.rect(surf, fill, self.rect)
        pygame.draw.rect(surf, tuple(max(0, c // 3) for c in col), self.rect, 1)
        # accent top edge
        pygame.draw.line(surf, col,
                         (self.rect.x + 1, self.rect.y),
                         (self.rect.right - 1, self.rect.y), 1)
        T.text(surf, (self.rect.centerx, self.rect.centery), self.label, 10,
               col, bold=True, anchor="cc")


# ------------------------------------------------------------------ chips
class Chip:
    """Preset selector chip."""

    def __init__(self, rect, label, color=T.C.CYAN):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, selected=False, enabled=True):
        if not enabled:
            pygame.draw.rect(surf, T.C.BG, self.rect)
            pygame.draw.rect(surf, T.C.BORDER_DIM, self.rect, 1)
            T.text(surf, (self.rect.centerx, self.rect.centery),
                   self.label, 9, T.C.TEXT_FAINT, anchor="cc")
            return
        if selected:
            fill = tuple(max(0, c // 4) for c in self.color)
            border = self.color
            text_col = self.color
        else:
            fill = T.C.BG
            border = T.C.BORDER
            text_col = T.C.TEXT_DIM
        pygame.draw.rect(surf, fill, self.rect)
        pygame.draw.rect(surf, border, self.rect, 1)
        if selected:
            # accent top bar
            pygame.draw.line(surf, self.color,
                             (self.rect.x, self.rect.y),
                             (self.rect.right - 1, self.rect.y), 2)
        T.text(surf, (self.rect.centerx, self.rect.centery), self.label, 9,
               text_col, bold=selected, anchor="cc")


def clampf(v, lo, hi):
    return max(lo, min(hi, v))
