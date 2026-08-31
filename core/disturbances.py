"""
core/disturbances.py
--------------------
The four independently-controllable disturbance channels required by the
PS (atmospheric turbulence, platform vibration, sensor noise, sudden
jerks).  Each has a clean 0-100 % level dial, swept by the stress-test
harness and adjusted live from the GUI sliders.

Vibration + jerks perturb the GIMBAL ATTITUDE (platform motion actually
moves the line of sight); turbulence + sensor noise corrupt the IMAGE
(what the detector has to look at).  Both genuinely degrade tracking.
"""

import math
import random

import cv2
import numpy as np

import config


class DisturbanceEngine:
    def __init__(self, turbulence=0, vibration=0, sensor_noise=0,
                 jerk_prob=0, seed=None):
        self.turbulence = turbulence
        self.vibration = vibration
        self.sensor_noise = sensor_noise
        self.jerk_prob = jerk_prob
        self._seed = seed
        self._rng = random.Random(seed)
        self._np = np.random.default_rng(seed)
        self._t = 0.0
        # stateful random walk for vibration
        self._vib_pan = 0.0
        self._vib_tilt = 0.0
        self._blur_sigma = 0.0
        self._maps = None
        self._maps_h = 0
        self._maps_w = 0
        self._f64 = None
        self._f32 = None
        self._acc = None
        self._out = None

    # ------------------------------------------------------------- platform
    def platform_disturbance(self, dt):
        """Returns (d_pan_deg, d_tilt_deg) perturbation of realized attitude
        this frame, from vibration random-walk plus occasional jerks."""
        if self.vibration <= 0 and self.jerk_prob <= 0:
            return 0.0, 0.0

        amp = (self.vibration / 100.0) * config.VIBRATION_MAX_DEG_S
        step = amp * dt
        self._vib_pan += self._rng.uniform(-step, step)
        self._vib_tilt += self._rng.uniform(-step, step)
        # keep the walk bounded
        lim = amp * 25.0
        self._vib_pan = max(-lim, min(lim, self._vib_pan))
        self._vib_tilt = max(-lim, min(lim, self._vib_tilt))

        jerk_pan = jerk_tilt = 0.0
        if self.jerk_prob > 0 and self._rng.uniform(0, 100) < self.jerk_prob:
            mag = config.JERK_MAX_MAGNITUDE_DEG * self._rng.uniform(0.4, 1.0)
            ang = self._rng.uniform(0, 2 * math.pi)
            jerk_pan = mag * math.cos(ang)
            jerk_tilt = mag * math.sin(ang)

        return self._vib_pan + jerk_pan, self._vib_tilt + jerk_tilt

    # -------------------------------------------------------------- image
    def apply(self, frame_bgr, dt):
        """Apply turbulence (warp + blur) and sensor noise to an 8-bit BGR
        frame - this is exactly what the detector sees."""
        self._t += dt
        img = frame_bgr

        if self.turbulence > 0:
            img = self._turbulence(img)
        if self.sensor_noise > 0:
            img = self._sensor_noise(img)
        return img

    def _turbulence(self, frame):
        h, w = frame.shape[:2]
        strength = (self.turbulence / 100.0) * config.TURBULENCE_MAX_PX
        # Pre-computed base grids (float32) at 1/4 resolution - the warp field
        # is spatially smooth, so we evaluate it cheaply and upscale the maps.
        if self._maps is None or self._maps_h != h or self._maps_w != w:
            ds = 4
            hh = (h + ds - 1) // ds * ds
            ww = (w + ds - 1) // ds * ds
            yy, xx = np.mgrid[0:hh:ds, 0:ww:ds].astype(np.float32)
            self._maps = (yy, xx)
            self._maps_h, self._maps_w = h, w
        yy, xx = self._maps
        k1 = 60.0
        k2 = 19.0
        shift_x = strength * (np.sin(2 * np.pi * yy / k1 + self._t * 1.1) *
                              0.6 + np.cos(2 * np.pi * xx / k2 + self._t * 0.7) * 0.4)
        shift_y = strength * (np.cos(2 * np.pi * yy / k1 + self._t * 1.1) *
                              0.6 + np.sin(2 * np.pi * xx / k2 + self._t * 0.7) * 0.4)
        map_x = cv2.resize(xx + shift_x, (w, h), interpolation=cv2.INTER_LINEAR)
        map_y = cv2.resize(yy + shift_y, (w, h), interpolation=cv2.INTER_LINEAR)
        remapped = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
        blur = (self.turbulence / 100.0) * config.TURBULENCE_BLUR_MAX
        if blur > 0.2:
            k = int(round(blur * 3.0)) * 2 + 1
            remapped = cv2.GaussianBlur(remapped, (k, k), blur)
        return remapped

    def _sensor_noise(self, frame):
        sigma = (self.sensor_noise / 100.0) * config.SENSOR_NOISE_MAX_SIGMA
        n_hot = int((self.sensor_noise / 100.0) * config.SENSOR_HOTPIXEL_MAX)
        h, w = frame.shape[:2]
        sh = frame.shape
        if self._f64 is None or self._f64.shape != sh:
            self._f64 = np.empty(sh, np.float64)
            self._f32 = np.empty(sh, np.float32)
            self._acc = np.empty(sh, np.float32)
            self._out = np.empty(sh, np.uint8)
        if sigma > 0:
            self._np.standard_normal(sh, dtype=np.float32, out=self._f32)
            self._f32 *= sigma
        else:
            self._f32.fill(0.0)
        self._acc[:] = frame                       # uint8 -> float32 (reused)
        np.add(self._acc, self._f32, out=self._acc)
        if n_hot > 0:
            ys = self._np.integers(0, h, n_hot)
            xs = self._np.integers(0, w, n_hot)
            val = self._np.integers(0, 2, n_hot) * 255
            self._acc[ys, xs, :] = val[:, None]
        np.clip(self._acc, 0, 255, out=self._acc)
        self._out[:] = self._acc                   # float32 -> uint8 (reused)
        return self._out