"""
core/detection.py
-----------------
Block D (front end) - detects beacon candidates in the *disturbed sensor
frame* using genuine image processing:

  1. Luminance top-hat: subtracts the local background (rolling-ball style)
     so only compact *bright* objects survive (dim stars and nebula vanish).
  2. Adaptive thresholding on the residual: the DETECTION_ABS_THRESHOLD is
     applied as a floor, but the threshold is locally raised by the 80th
     percentile of the residual histogram, so noise-dominated frames
     (heavy turbulence + sensor noise) don't flood the candidate list.
  3. Connected-component analysis on the thresholded residual.
  4. For every blob: intensity-weighted sub-pixel centroid (the standard
     technique behind star-tracker accuracy), plus appearance features:
     area, compactness, peak-SNR, hue-distance from the beacon hue.
  5. Appearance-classifier score via the baked logistic-regression weights
     (ai/classifier.py).  Output is sorted by score descending.

The DETECTION_ABS_THRESHOLD was lowered from 42 to 26 so the dim-phase
beacon at 60% fade (peak ~80 DN, local bg ~15 DN) still passes.  An
adaptive cap prevents hot-pixel noise in SEVERE/ADVERSARIAL frames from
creating thousands of tiny candidates.
"""

import math

import cv2
import numpy as np

import config
from core import geometry
from ai.classifier import score_features


class DetectionEngine:
    def __init__(self):
        self.last_mask = None
        self._no_tint = np.zeros(3, dtype=np.float32)

    # ------------------------------------------------------------------
    def detect(self, frame_bgr, gimbal_basis, focal_px):
        grey = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        kernel = max(3, config.TOP_HAT_RADIUS * 2 + 1)
        bg = cv2.morphologyEx(grey, cv2.MORPH_OPEN, np.ones((kernel, kernel), np.uint8))
        residual = cv2.subtract(grey, bg)

        abs_thr = config.DETECTION_ABS_THRESHOLD

        nz = residual[residual > 4]
        adaptive = abs_thr
        if nz.size >= 512:
            p90 = float(np.percentile(nz, 90))
            p60 = float(np.percentile(nz, 60))
            adaptive = min(max(abs_thr, int(p60 * 0.5 + 8)), max(abs_thr + 18, int(p90 * 0.55)))

        thr = max(abs_thr, min(adaptive, abs_thr + 22))
        mask = (residual > thr).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        self.last_mask = mask

        num, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)

        candidates = []
        for i in range(1, num):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < config.DETECTION_MIN_BLOB_AREA:
                continue
            x0 = int(stats[i, cv2.CC_STAT_LEFT])
            y0 = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            if w < 1 or h < 1:
                continue

            sub = grey[y0:y0 + h, x0:x0 + w].astype(np.float32)
            seg = mask[y0:y0 + h, x0:x0 + w].astype(np.float32)

            win = sub * seg
            s = win.sum()
            if s < 1e-3:
                continue
            yy, xx = np.mgrid[y0:y0 + h, x0:x0 + w].astype(np.float32)
            cx = float((win * xx).sum() / s)
            cy = float((win * yy).sum() / s)

            peak = float(sub.max())
            bg_sub = bg[y0:y0 + h, x0:x0 + w]
            if bg_sub.size == 0:
                local_bg = float(bg.mean())
            else:
                local_bg = float(np.median(bg_sub))
            bg_value = max(1.0, local_bg)

            res_sub = residual[y0:y0 + h, x0:x0 + w]
            res_sig = float(res_sub[seg > 0].mean()) if (seg > 0).any() else 0.0
            sigma_n = max(0.5, float(grey.std()) * 0.35)
            snr = max(0.1, (peak + res_sig) / (bg_value + sigma_n * 1.5))

            perimeter = 0.0
            cnt, _ = cv2.findContours(seg.astype(np.uint8), cv2.RETR_EXTERNAL,
                                      cv2.CHAIN_APPROX_SIMPLE)
            if cnt:
                perimeter = cv2.arcLength(cnt[0], True)
            circularity = min(1.0, 4 * math.pi * area / (perimeter ** 2 + 1e-6))

            bbox_px = config.BEACON_ANGULAR_RADIUS_DEG * 2 * config.PIXELS_PER_DEG
            expected_area = math.pi * (bbox_px / 2.0) ** 2
            area_norm = min(3.0, area / max(1.0, expected_area))

            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            segpix = hsv[y0:y0 + h, x0:x0 + w, 0][seg > 0]
            satpix = hsv[y0:y0 + h, x0:x0 + w, 1][seg > 0]
            if segpix.size:
                weights = satpix.astype(np.float32) + 1.0
                hue_val = float(np.average(segpix, weights=weights))
            else:
                hue_val = float(config.EXPECTED_BEACON_HUE)
            hue_dist, hue_dist_n = _hue_distance(hue_val, config.EXPECTED_BEACON_HUE)

            peak_normalized = min(1.0, peak / 255.0)

            ml = score_features([area_norm, circularity, snr, hue_dist_n])

            cand = Candidate(
                x=cx, y=cy, u=cx, v=cy,
                area=area, peak=peak, snr=snr,
                circularity=circularity, area_norm=area_norm,
                hue_dist=hue_dist, hue_dist_n=hue_dist_n,
                hue=hue_val, ml_score=ml,
                peak_normalized=peak_normalized,
            )
            cand.los_az, cand.los_el = geometry.ray_to_azel(
                cx, cy, focal_px, gimbal_basis,
                cu=config.PRINCIPAL_U, cv=config.PRINCIPAL_V)
            candidates.append(cand)

        candidates.sort(key=lambda c: c.ml_score, reverse=True)
        return candidates


def _hue_distance(h, ref_h):
    """Circular distance in OpenCV hue space (0-180), normalized to 0-1."""
    d = abs(h - ref_h)
    d = min(d, 180.0 - d)
    return d, min(1.0, d / 90.0)


class Candidate:
    """A per-frame detection candidate with both pixel and world-loose forms."""

    __slots__ = ("x", "y", "u", "v", "area", "peak", "snr", "circularity",
                 "area_norm", "hue_dist", "hue_dist_n", "hue", "ml_score",
                 "peak_normalized",
                 "los_az", "los_el", "mod_score", "fusion_score", "prior_score",
                 "_mod_predictive", "_assoc_score")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.los_az = None
        self.los_el = None
        self.mod_score = 0.0
        self.fusion_score = 0.0
        self.prior_score = 0.0
        self._mod_predictive = 0.0
        self._assoc_score = 0.0
