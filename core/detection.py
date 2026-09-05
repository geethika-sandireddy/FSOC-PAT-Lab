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
from collections import deque as _deque

import cv2
import numpy as np

import config
from core import geometry
from ai.classifier import score_features


def _mod_template_sign(frame_n, lag=0):
    """+1/-1 of the known beacon square-wave at an absolute frame index."""
    return 1.0 if (config.MODULATION_FREQ_HZ * (frame_n - lag) / config.FPS) % 1.0 < 0.5 \
        else -1.0


class DetectionEngine:
    def __init__(self):
        self.last_mask = None
        self._tracks = []          # persistent blob tracks across frames
        self._track_seq = 0
        self._frame = 0

    def _associate(self, cand):
        """Persistent-blob association in world LOS space.

        Matches a freshly-detected blob to the nearest surviving track within
        TRACK_ASSOC_RADIUS_DEG, otherwise spawns a new track.  Popping/bloom
        noise blobs flicker and get new IDs; the real beacon keeps one ID, so
        the tracker can reliably "stick" to it across frames.  Each track also
        keeps its own brightness history so it can self-score HOW WELL IT
        BLINKS at the beacon modulation frequency (the discriminator that
        appearance cannot provide against beacon-like distractors).
        """
        best_d = 1e9
        best_i = -1
        for i, tr in enumerate(self._tracks):
            if tr["claimed"]:
                continue
            d = math.hypot(cand.los_az - tr["az"], cand.los_el - tr["el"])
            if d < config.TRACK_ASSOC_RADIUS_DEG and d < best_d:
                best_d, best_i = d, i
        if best_i >= 0:
            tr = self._tracks[best_i]
            tr["az"], tr["el"] = cand.los_az, cand.los_el
            tr["miss"] = 0
            tr["age"] += 1
            tr["claimed"] = True
            tr["hist"].append((self._frame, cand.peak, cand.area))
            cand.track_id = tr["id"]
            cand.track_age = tr["age"]
        else:
            # Rescue relink: a blob that hopped outside the tight association
            # radius (SEVERE LOS jitter) still belongs to the *nearest* recent
            # track when it lands within the wider rescue radius - we adopt
            # that track instead of fragmenting IDs (which would reset the
            # beacon's modulation history and persistence evidence).
            adopted = -1
            best_r = config.TRACK_RESCUE_RADIUS_DEG
            for i, tr in enumerate(self._tracks):
                d = math.hypot(cand.los_az - tr["az"], cand.los_el - tr["el"])
                if d < best_r:
                    best_r, adopted = d, i
            hist = _deque(maxlen=config.MOD_CORREL_WIN)
            if adopted >= 0:
                tr = self._tracks[adopted]
                tr["az"], tr["el"] = cand.los_az, cand.los_el
                tr["miss"] = 0
                tr["age"] += 1
                tr["claimed"] = True
                tr["hist"].append((self._frame, cand.peak, cand.area))
                cand.track_id = tr["id"]
                cand.track_age = tr["age"]
                cand.track_mod = self._track_mod_corr(tr["hist"])
                return
            # true new object
            self._track_seq += 1
            cand.track_id = self._track_seq
            cand.track_age = 1
            # inherit the modulation history of the nearest recently-seen track
            # so an ID reseed does NOT reset the blink evidence
            for tr in self._tracks:
                if tr["miss"] <= config.TRACK_MISS_TOL and \
                        math.hypot(cand.los_az - tr["az"], cand.los_el - tr["el"]) < \
                        config.TRACK_ASSOC_RADIUS_DEG:
                    hist.extend(tr["hist"])
                    break
            hist.append((self._frame, cand.peak, cand.area))
            self._tracks.append(dict(
                id=self._track_seq, az=cand.los_az, el=cand.los_el,
                age=1, miss=0, claimed=True, hist=hist))
        cand.track_mod = self._track_mod_corr(self._tracks[best_i]["hist"] if best_i >= 0
                                              else self._tracks[-1]["hist"])

    @staticmethod
    def _track_mod_corr(hist):
        """Sign-agreement of a track's PEAK brightness history against the
        known 15 Hz beacon square-wave template, best of 0..2 frame lags
        (phase robust).  A beacon track agrees strongly; a static distractor
        / noise blob wanders around 0.5.  Returns 0.0 until enough samples
        have accumulated on one persistent blob track."""
        n = len(hist)
        if n < 8:
            return 0.0
        vals = [float(v[1]) for v in hist]
        frames = [v[0] for v in hist]
        mean_v = sum(vals) / n
        best = 0.0
        for lag in (0, 1, 2):
            agree = 0.0
            for v, f in zip(vals, frames):
                sig = 1.0 if v > mean_v else -1.0
                agree += sig * _mod_template_sign(f, lag)
            c = max(0.0, min(1.0, (agree / n + 1.0) / 2.0))
            if c > best:
                best = c
        return best

    def _prune_tracks(self):
        """Age out tracks that have gone unseen for longer than TOL frames."""
        self._tracks = [tr for tr in self._tracks if tr["miss"] <= config.TRACK_MISS_TOL]
        for tr in self._tracks:
            tr["miss"] += 1

    # ------------------------------------------------------------------
    def reset(self):
        self._tracks = []
        self._track_seq = 0

    # ------------------------------------------------------------------
    def detect(self, frame_bgr, gimbal_basis, focal_px,
               cu=config.PRINCIPAL_U, cv=config.PRINCIPAL_V):
        """Detect bright candidate blobs in the sensor frame.

        Returns a list of Candidate objects, sorted by appearance-score.
        Each Candidate carries its measurement in *view-local pixels* AND
        its implied world LOS (az, el) via the encoder pose (gimbal_basis).

        cu / cv default to the virtual-camera principal point; video-mode
        (Benchmark-2) callers pass the input video's own centre so an
        arbitrary-resolution MP4 maps to LOS correctly.
        """
        self._frame += 1
        for tr in self._tracks:
            tr["claimed"] = False
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
        pending = []
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

            # ---- physical footprint prefilter: a blob far smaller than the
            # beacon's known angular footprint is hot-pixel / salt-pepper
            # noise, not the terminal's beacon.  Prune before spending any
            # more compute on it. ----
            bbox_px = config.BEACON_ANGULAR_RADIUS_DEG * 2 * config.PIXELS_PER_DEG
            expected_area = math.pi * (bbox_px / 2.0) ** 2
            if area < config.MIN_BEACON_AREA_NORM * expected_area:
                continue

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
                cu=cu, cv=cv)
            pending.append(cand)

        # Track-ID assignment must be deterministic regardless of the (build-,
        # thread-, run-dependent) connected-component numbering.  When several
        # blobs compete for one persistent track in a frame, the physically
        # right claim is the blob CLOSEST to that track's last known position
        # (a beacon cannot jump, so hops belong to noise).  Sorting by that
        # proximity before associating makes ID ownership both reproducible and
        # beacon-favoured.
        tracks = self._tracks
        pending.sort(
            key=lambda c: (min(
                (math.hypot(c.los_az - tr["az"], c.los_el - tr["el"])
                 for tr in tracks), default=1e9), -c.area))
        for cand in pending:
            self._associate(cand)
            candidates.append(cand)

        self._prune_tracks()
        # Deterministic ordering.  Appearance scores frequently TIE between
        # the beacon and bright hot-pixel noise (both cap at ~1.0), and plain
        # sort is not stable across OpenCV's run-varying component numbering.
        # Break equal scores by AREA (a physical, run-independent quantity) so
        # the brightest largest blob - the beacon - is always first; acquisition
        # then favours it, and the result reproduces exactly across runs.
        candidates.sort(key=lambda c: (c.ml_score, c.area), reverse=True)
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
                 "_mod_predictive", "_assoc_score", "track_id", "track_age",
                 "track_mod")

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
        self.track_id = None
        self.track_age = 0
        self.track_mod = 0.0