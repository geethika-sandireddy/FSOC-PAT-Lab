"""
core/sensor.py
--------------
Block C (front end) - the software rasterizer: projects the 3D world from
the gimbal attitude into a sensor image, applies the PSF + disturbances,
and returns the pixel array the detector reads.

Split into a cheap **scene pass** (rays -> pixel intensity) and a separate
**disturbance pass** (turbulence / noise).  The rendered frame is normal
BGR uint8, nothing encoded - the detector is a pure consumer of pixels.
"""

import math

import numpy as np

import config
from core import geometry


# ---------------------------------------------------------------------------
# Radial "sprite" kernels, precomputed once
# ---------------------------------------------------------------------------
def _make_glow_kernel(radius_px):
    r = int(math.ceil(radius_px))
    size = 2 * r + 1
    ys, xs = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    d2 = (xs ** 2 + ys ** 2) / (radius_px ** 2)
    core = np.exp(-4.0 * d2)                 # compact core
    halo = 0.45 * np.exp(-0.55 * d2)         # broad halo
    return (core + halo), xs, ys


_BEACON_CORE = config.BEACON_ANGULAR_RADIUS_DEG * config.PIXELS_PER_DEG
_GLOW_R = int(math.ceil(_BEACON_CORE * config.BEACON_GLOW_MULT))
_BEACON_KERNEL, _BX, _BY = _make_glow_kernel(_BEACON_CORE)
_BEACON_HALO_R = _GLOW_R
_BEACON_HALO_SZ = [_GLOW_R]
_DISTRACTOR_KERNEL, _DX, _DY = _make_glow_kernel(5.0)


def _draw_sprite(frame, cx, cy, kernel, intensity):
    """Add a radial glow sprite centered at (cx, cy) into the BGR frame.

    Sub-pixel correct: each kernel sample rounds to its nearest pixel and
    contributions accumulate across samples (np.add.at), so the rendered
    intensity centroid matches the requested sub-pixel centre.
    """
    k = kernel.shape[0] // 2
    h, w = frame.shape[:2]
    ii, jj = np.indices(kernel.shape)                  # (row, col) in kernel
    px = cx + (jj - k)                                  # float pixel columns
    py = cy + (ii - k)                                  # float pixel rows
    pxi = np.rint(px).astype(np.intp)
    pyi = np.rint(py).astype(np.intp)
    on = (pxi >= 0) & (pxi < w) & (pyi >= 0) & (pyi < h)
    amp = kernel * intensity
    np.add.at(frame, (pyi[on], pxi[on], slice(None)), amp[on][..., None])


class VirtualSensor:
    """Renders the 3D world from the gimbal's realized attitude."""

    def __init__(self):
        self.w = config.CAM_VIEW_W
        self.h = config.CAM_VIEW_H
        # faint space background gradient + nebula tint (static)
        yy = np.linspace(0, 1, self.h)[:, None]
        neb = np.linspace(0.0, 0.6, 1)[None, :]
        bg = np.zeros((self.h, self.w, 3), np.float32)
        bg[..., 0] = (3 + 6 * yy)
        bg[..., 1] = (6 + 4 * yy) + neb
        bg[..., 2] = (14 + 10 * yy)
        self.background = bg

    def render(self, scene, gimbal, focal_px, disturbance=None, dt=1.0 / 60.0):
        """Return a BGR frame (uint8) as seen from the gimbal through the
        disturbance engine (turbulence + sensor noise already applied).

        scene : Scene3D  |  gimbal : Gimbal  |  disturbance : DisturbanceEngine
        """
        frame = np.copy(self.background)
        cam_pos = (0.0, 0.0, 0.0)
        right, up, fwd = gimbal.basis()
        basis = (right, up, fwd)
        focal = focal_px
        cu, cv = config.PRINCIPAL_U, config.PRINCIPAL_V

        # --- starfield (dim background features, project per frame) ---
        # vectorized projection of all star directions into the sensor
        dirs = scene.stars.dirs
        qx = dirs @ right
        qy = dirs @ up
        qz = dirs @ fwd
        in_front = qz > 1e-6
        us = cu + focal * (qx / qz)
        vs = cv - focal * (qy / qz)
        in_view = in_front & (us >= 0) & (us < self.w) & (vs >= 0) & (vs < self.h)
        if in_view.any():
            sxs = us[in_view].astype(int)
            sys_ = vs[in_view].astype(int)
            bright = (scene.stars.mags[in_view] ** 2.2) * 26.0
            frame[sys_, sxs, :] += bright[..., None]

        # --- distractors (decoy sprites) ---
        for d in scene.distractors:
            pos = geometry.azel_to_vec(d.az, d.el, 8.0e5)
            pix = geometry.project_point_into_camera(pos, cam_pos, basis, focal, cu, cv)
            if pix is None:
                continue
            u, v = pix
            if -60 <= u < self.w + 60 and -60 <= v < self.h + 60:
                amp = d.intensity()
                _draw_sprite(frame, u, v, _DISTRACTOR_KERNEL, amp)
                # tint decoy hue
                px, py_ = int(round(u)), int(round(v))
                if 0 <= px < self.w and 0 <= py_ < self.h:
                    r, g, b = _hue_to_bgr(d.hue)
                    scale = 1.0
                    frame[py_, px, 0] += r * scale
                    frame[py_, px, 1] += g * scale
                    frame[py_, px, 2] += b * scale

        # --- beacon ---
        b = scene.beacon
        pix = geometry.project_point_into_camera(b.pos, cam_pos, basis, focal, cu, cv)
        occ = 0.0
        for o in scene.obstacles:
            cover = o.crossing(scene.time)
            if cover > 0:
                opos = geometry.azel_to_vec(o.az, o.el, 8.0e5)
                opix = geometry.project_point_into_camera(opos, cam_pos, basis, focal, cu, cv)
                if opix is not None:
                    r_ob = o.radius_deg * config.PIXELS_PER_DEG
                    dist_beacon = math.hypot(opix[0] - (pix[0] if pix else 0.0),
                                             opix[1] - (pix[1] if pix else 0.0))
                    if dist_beacon < r_ob * 2.2:
                        occ = max(occ, cover)
        b.visible = True
        if pix is not None:
            u, v = pix
            # modulation amplitude
            amp = b.intensity(b.time)
            if occ > 0.0:
                # obstacle partially covers -> dim & occlude proportionally
                amp *= max(0.0, 1.0 - occ)
                if occ > 0.55:
                    amp = 0.0
            if amp > 8:
                _draw_sprite(frame, u, v, _BEACON_KERNEL, amp)
                core_tint = 0.9
                px0, py0 = int(round(u)), int(round(v))
                if 0 <= px0 < self.w and 0 <= py0 < self.h:
                    frame[py0, px0, 0] += 12 * core_tint
                    frame[py0, px0, 2] += 30 * core_tint

        # --- obstacles (dark occluders over the scene, correct depth) ---
        for o in scene.obstacles:
            opos = geometry.azel_to_vec(o.az, o.el, 8.0e5)
            opix = geometry.project_point_into_camera(opos, cam_pos, basis, focal, cu, cv)
            if opix is None:
                continue
            u, v = opix
            r_ob = o.radius_deg * config.PIXELS_PER_DEG
            _draw_dark_disc(frame, u, v, r_ob)

        # --- disturbances ---
        if disturbance is not None:
            frame = disturbance.apply(frame, dt)
            if frame.dtype == np.uint8:
                return frame
        return np.clip(frame, 0, 255).astype(np.uint8)


def _hue_to_bgr(hue_deg):
    """Approximate BGR from an HSV hue (for decoy tinting only)."""
    h = hue_deg
    s = 0.55
    v = 1.0
    hp = h / 60.0
    c = v * s
    x = c * (1 - abs(hp % 2 - 1))
    if hp < 1:
        r, g, b = c, x, 0
    elif hp < 2:
        r, g, b = x, c, 0
    elif hp < 3:
        r, g, b = 0, c, x
    elif hp < 4:
        r, g, b = 0, x, c
    elif hp < 5:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    m = v - c
    return (int((b + m) * 120), int((g + m) * 120), int((r + m) * 120))


def _draw_dark_disc(frame, cx, cy, radius):
    """Draw an opaque dark occlusion disc (blended multiply) - represents
    debris/obstacle covering the light path."""
    r = max(2, int(math.ceil(radius)))
    h, w = frame.shape[:2]
    x0 = max(0, int(math.floor(cx)) - r)
    x1 = min(w, int(math.ceil(cx)) + r)
    y0 = max(0, int(math.floor(cy)) - r)
    y1 = min(h, int(math.ceil(cy)) + r)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    inside = d2 <= radius ** 2
    window = frame[y0:y1, x0:x1].astype(np.float32)
    window[inside] *= 0.10
    frame[y0:y1, x0:x1] = np.clip(window, 0, 255).astype(np.uint8)