"""
core/detection.py
-----------------
Block D (front end) - detects beacon candidates in the *disturbed sensor
frame* using genuine image processing:

  1. Luminance top-hat: subtracts the local background (rolling-ball style)
     so only compact *bright* objects survive (dim stars and nebula vanish).
  2. Connected-component analysis on the thresholded residual.
  3. For every blob: intensity-weighted sub-pixel centroid (the standard
     technique behind star-tracker accuracy), plus appearance features:
     area, compactness, peak-SNR, hue-distance from the beacon hue.
  4. Returns candidates with a fusion score (appearance classifier + the
     modulation correlator lives in core/tracking.py; this module owns the
     per-frame geometric/appearance measurement).

Nothing here knows the target's true world position - it sees pixels only.
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

    # ------------------------------------------------------------------
    def detect(self, frame_bgr, gimbal_basis, focal_px):
        """Detect bright candidate blobs in the sensor frame.

        Returns a list of Candidate objects, sorted by appearance-score.
        Each Candidate carries its measurement in *view-local pixels* AND
        its implied world LOS (az, el) via the encoder pose (gimbal_basis).
        """
        grey = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        # ---- top-hat: local background subtraction ----
        kernel = max(3, config.TOP_HAT_RADIUS * 2 + 1)
        bg = cv2.morphologyEx(grey, cv2.MORPH_OPEN, np.ones((kernel, kernel), np.uint8))
        residual = cv2.subtract(grey, bg)

        thr = config.DETECTION_ABS_THRESHOLD
        mask = (residual > thr).astype(np.uint8)
        # small cleanup: closing bridges turbulence-fragmented blobs
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
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

            # ---- sub-pixel intensity-weighted centroid (double pass) ----
            win = sub * seg
            s = win.sum()
            if s < 1e-3:
                continue
            yy, xx = np.mgrid[y0:y0 + h, x0:x0 + w].astype(np.float32)
            cx = float((win * xx).sum() / s)
            cy = float((win * yy).sum() / s)

            peak = float(sub.max())
            local_bg = float(bg[y0 + h // 2, x0 + w // 2]) if (y0 + h // 2) < bg.shape[0] and (x0 + w // 2) < bg.shape[1] else float(bg.max())
            bg_value = max(1.0, local_bg)
            snr = peak / bg_value

            # ---- appearance features ----
            perimeter = 0.0
            cnt, _ = cv2.findContours(seg.astype(np.uint8), cv2.RETR_EXTERNAL,
                                      cv2.CHAIN_APPROX_SIMPLE)
            if cnt:
                perimeter = cv2.arcLength(cnt[0], True)
            circularity = min(1.0, 4 * math.pi * area / (perimeter ** 2 + 1e-6))

            bbox_px = config.BEACON_ANGULAR_RADIUS_DEG * 2 * config.PIXELS_PER_DEG
            expected_area = math.pi * (bbox_px / 2.0) ** 2
            area_norm = min(3.0, area / max(1.0, expected_area))

            # hue distance from the beacon hue
            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            segpix = hsv[y0:y0 + h, x0:x0 + w, 0][seg > 0]
            hue_val = float(np.median(segpix)) if segpix.size else 0.0
            hue_dist, hue_dist_n = _hue_distance(hue_val, config.EXPECTED_BEACON_HUE)

            # ---- appearance score via the AI classifier ----
            ml = score_features([area_norm, circularity, snr, hue_dist_n])

            cand = Candidate(
                x=cx, y=cy, u=cx, v=cy,
                area=area, peak=peak, snr=snr,
                circularity=circularity, area_norm=area_norm,
                hue_dist=hue_dist, hue_dist_n=hue_dist_n,
                hue=hue_val, ml_score=ml,
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