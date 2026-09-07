"""
ui/widgets.py  —  FSOC-PAT reusable controls v2
Deep-space tactical style: angled tracks, glowing accents, arc gauges.
"""
import pygame
from ui import theme as T


# ------------------------------------------------------------------ stats
def stat_row(surf, rect, label, value, value_color=T.C.TEXT, value_size=14,
              label_color=T.C.TEXT_FAINT):
    T.text(surf, (rect.x, rect.y + 1), label, 9, label_color)
    T.text(surf, (rect.right, rect.y), value, value_size, value_color,
           bold=True, anchor="tr")


def stat_val(surf, x, y, label, value, val_color=T.C.CYAN,
             lbl_size=8, val_size=22):
    """Single large value with small label above."""
    T.text(surf, (x, y), label, lbl_size, T.C.TEXT_FAINT)
    T.text(surf, (x, y + lbl_size + 2), value, val_size, val_color, bold=True)


def kpi_card(surf, rect, title, rows, sub=None):
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
def hbar(surf, rect, frac, color, label="", bg=T.C.PANEL_2):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, bg, rect)
    w = int(round(rect.w * max(0.0, min(1.0, frac))))
    if w > 0:
        # gradient: dark fill + bright leading edge
        fill = tuple(max(0, c // 2) for c in color)
        pygame.draw.rect(surf, fill, (rect.x, rect.y, w, rect.h))
        pygame.draw.line(surf, color,
                         (rect.x + w - 1, rect.y),
                         (rect.x + w - 1, rect.bottom - 1), 1)
    # tick marks at quarters
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
    T.text(surf, (rect.centerx, rect.centery), s, 14, color,
           bold=True, anchor="cc")


# ------------------------------------------------------------------ slider
class Slider:
    TRACK_H = 7
    KNOB_W  = 10
    KNOB_H  = 20

    def __init__(self, rect, label, value=0, color=T.C.CYAN,
                 fmt="{:>3d}", enabled=True):
        self.rect    = pygame.Rect(rect)
        self.label   = label
        self.value   = int(round(_clamp(value, 0, 100)))
        self.color   = color
        self.fmt     = fmt
        self.enabled = enabled
        self.dragging = False

    @property
    def frac(self):
        return self.value / 100.0

    def set_frac(self, f):
        self.value = int(round(_clamp(f * 100.0, 0, 100)))

    def hit(self, pos):
        return self.enabled and self.rect.collidepoint(pos)

    def selected_enabled(self):
        return self.enabled

    def drag_to(self, x):
        if self.enabled:
            self.set_frac((x - self.rect.x) / self.rect.w)

    def draw(self, surf, value_text=None):
        if not self.enabled:
            self._draw_disabled(surf)
            return
        lx, ly = self.rect.x, self.rect.y - 10
        T.text(surf, (lx, ly), self.label, 10, T.C.TEXT_DIM, bold=True)
        val_str = value_text if value_text is not None else self.fmt.format(self.value)
        T.text(surf, (self.rect.right, ly), val_str, 10, self.color,
               bold=True, anchor="tr")
        # track
        ty = self.rect.y + (self.rect.h - self.TRACK_H) // 2 + 6
        track = pygame.Rect(self.rect.x, ty, self.rect.w, self.TRACK_H)
        pygame.draw.rect(surf, T.C.PANEL_2, track)
        w = int(round(track.w * self.frac))
        if w:
            fill = tuple(max(0, c // 2) for c in self.color)
            pygame.draw.rect(surf, fill, (track.x, track.y, w, track.h))
            pygame.draw.line(surf, self.color,
                             (track.x + w - 1, track.y),
                             (track.x + w - 1, track.bottom - 1), 2)
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
        T.text(surf, (self.rect.x, self.rect.y - 10),
             self.label + "  N/A", 10, T.C.TEXT_FAINT, bold=True)
        ty = self.rect.y + (self.rect.h - self.TRACK_H) // 2 + 6
        track = pygame.Rect(self.rect.x, ty, self.rect.w, self.TRACK_H)
        pygame.draw.rect(surf, T.C.PANEL_2, track)
        pygame.draw.rect(surf, T.C.BORDER_DIM, track, 1)


# ------------------------------------------------------------------ button
class Button:
    def __init__(self, rect, label, color=T.C.CYAN, key=None):
        self.rect  = pygame.Rect(rect)
        self.label = label
        self.color = color
        self.key   = key

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, active_color=None):
        col  = active_color or self.color
        fill = tuple(max(0, c // 7) for c in col)
        brd  = tuple(max(0, c // 3) for c in col)
        # angled top-right corner
        r = self.rect
        pts = [(r.x, r.y), (r.right - 6, r.y), (r.right, r.y + 6),
               (r.right, r.bottom), (r.x, r.bottom)]
        pygame.draw.polygon(surf, fill, pts)
        pygame.draw.polygon(surf, brd, pts, 1)
        # top accent line
        pygame.draw.line(surf, col, (r.x + 1, r.y), (r.right - 7, r.y), 1)
        T.fit_text(surf, r, self.label, 11, col, bold=True, padding=10)


# ------------------------------------------------------------------ chip
class Chip:
    def __init__(self, rect, label, color=T.C.CYAN):
        self.rect  = pygame.Rect(rect)
        self.label = label
        self.color = color

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, selected=False, enabled=True):
        r = self.rect
        if not enabled:
            pygame.draw.rect(surf, T.C.BG, r)
            pygame.draw.rect(surf, T.C.BORDER_DIM, r, 1)
                        T.fit_text(surf, r, self.label, 10, T.C.TEXT_FAINT, padding=5)
            return
        if selected:
            fill   = tuple(max(0, c // 5) for c in self.color)
            border = self.color
            tcol   = self.color
        else:
            fill   = T.C.BG
            border = T.C.BORDER
            tcol   = T.C.TEXT_DIM
        pygame.draw.rect(surf, fill, r)
        pygame.draw.rect(surf, border, r, 1)
        if selected:
            # bright bottom bar instead of top (aerospace style: underline)
            pygame.draw.line(surf, self.color,
                             (r.x + 1, r.bottom - 1),
                             (r.right - 1, r.bottom - 1), 2)
        T.fit_text(surf, r, self.label, 10, tcol, bold=selected, padding=5)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# Keep legacy name for existing call sites
def clampf(v, lo, hi):
    return _clamp(v, lo, hi)
