"""
ui/view3d.py
------------
A compact polar "sky plot" for the side panel: azimuth around, elevation
rings - the classic radar PPI format.  Draws, for the CURRENT run:

  * elevation rings + fixed references,
  * the predictor's future trajectory arc (dashed cyan) and past arc (dim),
  * ephemeris (prior) target (amber diamond) with its bias crescent,
  * tracker LOS estimate (green dot) and the realized boresight reticle,
  * ground-truth beacon (small white cross) - clearly labelled as the
    "reference" measurement that the ML simulator exposes for validation.

Every quantity comes from the sim objects; nothing here feeds the control
pipeline (it is display-only telemetry).
"""

import math
import pygame

from ui import theme as T


RANGE_DEG = 3.4   # radius shown = 3.4 deg of elevation


def _pg_to_polar(px, py, rect, range_deg=RANGE_DEG):
    return pygame.max(1, int(rect.w / (2 * range_deg)))


def render(surf, rect, sim, t_now):
    """Draw the sky plot for the current sim state into rect."""
    surf.fill(T.C.BG, rect)
    pygame.draw.rect(surf, T.C.PANEL, rect)
    pygame.draw.rect(surf, T.C.BORDER, rect, 1)

    cx, cy = rect.centerx, rect.centery
    scale = rect.w / (2 * RANGE_DEG)          # px per degree

    # --- elevation rings ---
    for deg in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        r = int(deg * scale)
        color = T.C.GRID if deg % 1.0 else T.C.BORDER
        pygame.draw.circle(surf, color, (cx, cy), r, 1)
    pygame.draw.line(surf, T.C.GRID, (rect.x, cy), (rect.right, cy))

    # --- angular axes (azimuth spokes) ---
    for deg in range(0, 360, 30):
        a = math.radians(deg)
        r = int(3.2 * scale)
        pygame.draw.line(surf, T.C.GRID,
                         (cx + r * math.cos(a) * 0.05, cy + r * math.sin(a) * 0.05),
                         (cx + r * math.cos(a), cy + r * math.sin(a)), 1)

    # --- trajectory arcs (from the exact relative-orbit model) ---
    orbit = sim.scene.orbit
    dt_s = 0.25
    past = []
    future = []
    for k in range(int(5.0 / dt_s)):
        t = t_now - (k + 1) * dt_s
        az, el = orbit.relative_los_az_el(t)
        past.append(_pp(az, el, rect, scale))
    for k in range(int(6.0 / dt_s)):
        t = t_now + k * dt_s
        az, el = orbit.relative_los_az_el(t)
        future.append(_pp(az, el, rect, scale))

    if len(past) > 1:
        pygame.draw.lines(surf, T.C.TEXT_FAINT, False, past, 1)
    if len(future) > 1:
        for i in range(len(future) - 1):
            c = T.C.CYAN_DIM if (i % 8) < 4 else T.C.PANEL
            pygame.draw.line(surf, c, future[i], future[i + 1], 1)

    # --- ephemeris (prior) target ---
    p_az, p_el = sim.eph.predict_az_el(t_now)
    ppx = _pp(p_az, p_el, rect, scale)
    _diamond(surf, ppx, T.C.AMBER, 5)

    # bias vector tip (where the beacon really is, per the bias model)
    b_az, b_el = sim.eph.bias_deg(t_now)
    tpx = _pp(p_az + b_az, p_el + b_el, rect, scale)

    # --- tracker estimate ---
    est = sim.last_result.get("est_az")
    if est is not None:
        epx = _pp(est, sim.last_result["est_el"], rect, scale)
        pygame.draw.circle(surf, T.C.GREEN, epx, 3)
        pygame.draw.circle(surf, T.C.GREEN, epx, 6, 1)

    # --- realized boresight reticle ---
    bx = _pp(sim.gimbal.pan, sim.gimbal.tilt, rect, scale)
    _cross(surf, bx, T.C.CYAN, 5)

    # --- ground-truth reference ---
    _cross(surf, tpx, T.C.TEXT, 3)

    # --- FOV window marker (the 2.4 x 1.35 deg gate) ---
    fw = int(config_HFOV() * scale) // 2
    fh = int(config_VFOV() * scale) // 2
    pygame.draw.rect(surf, T.C.CYAN_DIM, (bx[0] - fw, bx[1] - fh, fw * 2, fh * 2), 1)

    # legend
    T.text(surf, (rect.x + 6, rect.y + 5), "relative-LOS sky plot", 9, T.C.TEXT_FAINT)
    _legend(surf, rect)


def config_HFOV():
    import config
    return config.HFOV_DEG


def config_VFOV():
    import config
    return config.VFOV_DEG


def _pp(az, el, rect, scale):
    """azimuth (deg) -> polar angle; elevation (deg) -> radius."""
    cx, cy = rect.centerx, rect.centery
    a = math.radians(az)
    r = max(0.0, min(el, RANGE_DEG)) * scale
    return (int(cx + r * math.cos(a)), int(cy + r * math.sin(a)))


def _diamond(surf, pos, color, r):
    x, y = pos
    pygame.draw.polygon(surf, color, [(x, y - r), (x + r, y), (x, y + r), (x - r, y)])


def _cross(surf, pos, color, r):
    x, y = pos
    pygame.draw.line(surf, color, (x - r, y), (x + r, y), 1)
    pygame.draw.line(surf, color, (x, y - r), (x, y + r), 1)


def _legend(surf, rect):
    items = [("ephem prior", T.C.AMBER), ("est LOS", T.C.GREEN),
             ("boresight", T.C.CYAN), ("true (ref)", T.C.TEXT)]
    x = rect.x + 6
    y = rect.bottom - 16
    for label, col in items:
        x = _legend_item(surf, x, y, label, col)

def _legend_item(surf, x, y, label, col):
    pygame.draw.rect(surf, col, (x, y + 4, 8, 3))
    T.text(surf, (x + 12, y), label, 9, col)
    return x + 12 + T.font(9).size(label)[0] + 10