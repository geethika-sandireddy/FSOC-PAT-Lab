"""
ui/view3d.py
------------
SpaceX/ISRO-grade 3D Orbital Geometry & Sky Radar Display.
Uses a true 2D Cartesian celestial coordinate projection:
  * +Azimuth (deg) -> Right (px)
  * +Elevation (deg) -> Up (px)
  * Centre (cx, cy) -> Inertial Boresight Origin (0 deg, 0 deg)

Visualizes in real-time:
  1. Concentric angular range rings (0.5 deg, 1.0 deg, 1.5 deg) with axes.
  2. Relative Orbital Trajectory (dashed cyan future track, faint past track).
  3. Dynamic Target Satellite SAT-B: moving point with pulsing lock/ping rings.
  4. Moving Camera FOV Window: 2.4 deg x 1.8 deg bounding box physically slewing across
     the sky as the pan-tilt gimbal tracks the target.
  5. Realized Boresight Crosshair: at the centre of the moving camera box.
  6. Ephemeris Coarse Prior: amber diamond showing orbital ephemeris.
  7. Ground-Truth Reference: high-contrast target truth marker.
"""

import math
import pygame
from ui import theme as T
import config

RANGE_DEG = 1.8  # radius shown = 1.8 deg of elevation/azimuth


def render(surf, rect, sim, t_now):
    """Draw the sky radar for the current sim state into rect."""
    surf.fill(T.C.BG, rect)
    pygame.draw.rect(surf, T.C.PANEL_2, rect)
    pygame.draw.rect(surf, T.C.BORDER, rect, 1)

    cx, cy = rect.centerx, rect.centery
    scale = (min(rect.w, rect.h) * 0.42) / RANGE_DEG  # px per degree

    # --- 1. Concentric Range Rings ---
    for deg in (0.5, 1.0, 1.5):
        r = int(deg * scale)
        color = (22, 38, 64) if deg % 1.0 != 0 else (34, 56, 92)
        pygame.draw.circle(surf, color, (cx, cy), r, 1)
        T.text(surf, (cx + r + 2, cy - 10), f"{deg:.1f}°", 9, T.C.TEXT_FAINT, mono=True)

    # --- 2. Crosshair Axes ---
    pygame.draw.line(surf, (20, 36, 60), (rect.x + 8, cy), (rect.right - 8, cy), 1)
    pygame.draw.line(surf, (20, 36, 60), (cx, rect.y + 8), (cx, rect.bottom - 8), 1)

    def to_radar(az, el):
        """Maps azimuth (deg) and elevation (deg) to radar pixel coords."""
        return (int(cx + az * scale), int(cy - el * scale))

    # --- 3. Trajectory Arcs (Past and Future Orbital Path) ---
    orbit = sim.scene.orbit
    dt_s = 0.15
    past, future = [], []
    for k in range(int(3.0 / dt_s)):
        t = t_now - (k + 1) * dt_s
        az, el = orbit.relative_los_az_el(t)
        past.append(to_radar(az, el))
    for k in range(int(4.0 / dt_s)):
        t = t_now + k * dt_s
        az, el = orbit.relative_los_az_el(t)
        future.append(to_radar(az, el))

    if len(past) > 1:
        pygame.draw.lines(surf, (40, 70, 100), False, past, 1)
    if len(future) > 1:
        for i in range(len(future) - 1):
            c = T.C.CYAN_DIM if (i % 4) < 2 else (22, 44, 70)
            pygame.draw.line(surf, c, future[i], future[i + 1], 1)

    # --- 4. Camera FOV Box (Physically slewing across the sky!) ---
    cam_pan = sim.gimbal.pan
    cam_tilt = sim.gimbal.tilt
    cam_pt = to_radar(cam_pan, cam_tilt)

    fw = int(config.HFOV_DEG * scale) // 2
    fh = int(config.VFOV_DEG * scale) // 2
    cam_box = pygame.Rect(cam_pt[0] - fw, cam_pt[1] - fh, fw * 2, fh * 2)

    # Glowing camera FOV box
    fov_surf = pygame.Surface((cam_box.w, cam_box.h), pygame.SRCALPHA)
    fov_surf.fill((0, 180, 255, 18))
    surf.blit(fov_surf, cam_box.topleft)
    pygame.draw.rect(surf, (40, 140, 210), cam_box, 1)
    T.text(surf, (cam_box.x + 4, cam_box.y + 3), "CAM FOV", 9, (60, 160, 230), bold=True)

    # Realized Gimbal Boresight (Reticle at center of moving camera)
    bx, by = cam_pt
    pygame.draw.circle(surf, T.C.CYAN_ELEC, (bx, by), 4, 1)
    pygame.draw.line(surf, T.C.CYAN_ELEC, (bx - 7, by), (bx + 7, by), 1)
    pygame.draw.line(surf, T.C.CYAN_ELEC, (bx, by - 7), (bx, by + 7), 1)

    # --- 5. Ephemeris Coarse Prior (Amber diamond) ---
    p_az, p_el = sim.eph.predict_az_el(t_now)
    epx = to_radar(p_az, p_el)
    ex, ey = epx
    pygame.draw.polygon(surf, T.C.AMBER, [(ex, ey - 4), (ex + 4, ey), (ex, ey + 4), (ex - 4, ey)], 1)

    # --- 6. Target Beacon Satellite SAT-B (Physically moving in orbit!) ---
    truth_az = sim.last_result.get("truth_az", 0.0)
    truth_el = sim.last_result.get("truth_el", 0.0)
    tx, ty = to_radar(truth_az, truth_el)

    st = sim.last_result.get("state", "SEARCHING")
    is_locked = st in ("LOCKED", "DEGRADED_LOCK")
    t_col = T.C.GREEN if is_locked else (T.C.AMBER if st == "SEARCHING" else T.C.CYAN_ELEC)

    p = T.pulse(2.0)
    pygame.draw.circle(surf, t_col, (tx, ty), 3)
    pygame.draw.circle(surf, t_col, (tx, ty), int(6 + 2 * p), 1)
    T.text(surf, (tx + 8, ty - 6), "SAT-B", 10, t_col, bold=True)

    # --- 7. Tracker Estimated LOS ---
    est_az = sim.last_result.get("est_az")
    est_el = sim.last_result.get("est_el")
    if est_az is not None and est_el is not None:
        esx, esy = to_radar(est_az, est_el)
        pygame.draw.circle(surf, (0, 220, 130), (esx, esy), 2)

    # --- 8. Header & Legend ---
    T.text(surf, (rect.x + 8, rect.y + 6), "3D ORBITAL RADAR (SKY PLOT)", 10.5, T.C.CYAN_ELEC, bold=True)

    leg_y = rect.bottom - 16
    T.text(surf, (rect.x + 8, leg_y), "PRIOR", 9.5, T.C.AMBER, bold=True)
    T.text(surf, (rect.x + 58, leg_y), "+ BORESIGHT", 9.5, T.C.CYAN_ELEC, bold=True)
    T.text(surf, (rect.x + 134, leg_y), "[ ] CAM FOV", 9.5, (60, 160, 230), bold=True)
    T.text(surf, (rect.x + 208, leg_y), "* SAT-B", 9.5, t_col, bold=True)
