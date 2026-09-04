"""
core/atmosphere.py
------------------
Atmospheric condition image effects (PS 26169: "Clear, Haze, Fog, Rain,
Low light").  Applied to the sensor frame after rendering, modifying
contrast, brightness, blur, veil scattering, rain streaks, and gain.

Each condition is a simple, fast image-space operation — no 3D ray-marching.
"""

import numpy as np
import cv2


class AtmosphereEngine:
    def __init__(self, condition="CLEAR", seed=None):
        self.condition = condition
        self._rng = np.random.default_rng(seed)
        self._streak_cache = None
        self._streak_h = 0
        self._streak_w = 0

    def apply(self, frame):
        """Apply atmospheric effect to a BGR uint8 frame in-place where possible."""
        from core.platforms import ATMOSPHERIC_CONDITIONS
        params = ATMOSPHERIC_CONDITIONS.get(self.condition,
                                            ATMOSPHERIC_CONDITIONS["CLEAR"])
        if self.condition == "CLEAR":
            return frame

        img = frame.astype(np.float32)

        # 1. Contrast reduction (multiply pixel range around midpoint)
        mid = 128.0
        img = (img - mid) * params["contrast"] + mid

        # 2. Brightness / gain adjustment
        img *= params["gain"] * params["brightness"]

        # 3. Veil scattering (alpha-blend toward gray haze)
        if params["veil"] > 0:
            veil_color = np.array([180.0, 190.0, 200.0])  # slight blue haze
            img = img * (1.0 - params["veil"]) + veil_color * params["veil"]

        np.clip(img, 0, 255, out=img)
        frame_out = img.astype(np.uint8)

        # 4. Blur (haze / fog scattering)
        if params["blur"] > 0:
            k = params["blur"] * 2 + 1
            frame_out = cv2.GaussianBlur(frame_out, (k, k), params["blur"])

        # 5. Rain streaks (vertical bright lines)
        if params["streaks"] > 0:
            frame_out = self._apply_rain(frame_out, params["streaks"])

        return frame_out

    def _apply_rain(self, frame, num_streaks):
        """Draw semi-transparent vertical rain streaks."""
        h, w = frame.shape[:2]
        if self._streak_cache is None or self._streak_h != h or self._streak_w != w:
            self._streak_cache = np.zeros((h, w), np.float32)
            self._streak_h, self._streak_w = h, w

        streaks = self._streak_cache
        streaks[:] = 0

        xs = self._rng.integers(0, w, num_streaks)
        lengths = self._rng.integers(15, 50, num_streaks)
        for i in range(num_streaks):
            x = int(xs[i])
            length = int(lengths[i])
            y_start = self._rng.integers(0, max(1, h - length))
            brightness = self._rng.uniform(100, 200)
            thickness = self._rng.choice([1, 1, 2])
            cv2.line(streaks, (x, y_start), (x, y_start + length),
                     float(brightness), thickness)

        # blend streaks additively
        streak3 = np.stack([streaks, streaks, streaks], axis=-1)
        result = frame.astype(np.float32) + streak3 * 0.3
        np.clip(result, 0, 255, out=result)
        return result.astype(np.uint8)
