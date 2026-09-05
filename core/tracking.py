"""
core/tracking.py
----------------
Block D (back end) - the autonomous acquisition & tracking brain.

Called once per frame (main / stress_test):

  update(candidates, t, dt)

Decision pipeline:
  1. Score candidates by fusing three independent cues:
       - appearance : AI logistic-regression classifier (ai/classifier.py)
       - modulation : sign-agreement correlation of brightness history vs
                      the known 15 Hz beacon amplitude-modulation signature
       - prior      : geometric agreement with the ephemeris prediction.
  2. Association while LOCKED / COASTING: candidate inside ASSOC_GATE of the
     current LOS estimate gets associated (nearest wins, weighted by
     predictive modulation correlation - prevents wrong-target injection).
  3. Acquisition while SEARCHING: a candidate must clear the appearance bar
     AND sit in the (time-widening) ephemeris gate; it then forms a tentative
     track that must prove **spatial consistency** (same LOS for N frames)
     and **modulation identity** (correlator score over a filled history)
     before LOCKED is committed.  That combination makes false locks
     essentially impossible.
  4. The estimator = ephemeris prior + leaky-absorbed bias + velocity
     feedforward: the control loop gets smooth feedforward plus a corrective
     term, so the residual boresight error stays a few hundredths of a
     degree.

The tracker never reads the beacon's true position.
"""

import math
from collections import deque

import config


SEARCHING = "SEARCHING"
COASTING = "COASTING"
LOCKED = "LOCKED"
TENTATIVE = "TENTATIVE"


class ModulationTrack:
    """Brightness history of the *single associated object*, sign-agreement
    correlated against the known 15 Hz beacon square-wave signature.

    The template is anchored to the ABSOLUTE frame index of every sample
    (stored alongside the intensity), so the correlation phase is locked to
    the real modulation clock rather than rotating with the sliding window.
    """

    def __init__(self, win=config.MOD_CORREL_WIN):
        self.win = win
        self.pxs = deque(maxlen=win)
        self.pys = deque(maxlen=win)
        self.values = deque(maxlen=win)
        self.frames = deque(maxlen=win)

    def reset(self):
        self.pxs.clear()
        self.pys.clear()
        self.values.clear()
        self.frames.clear()

    def push(self, u, v, intensity, frame_n):
        self.pxs.append(u)
        self.pys.append(v)
        self.values.append(max(0.0, float(intensity)))
        self.frames.append(int(frame_n))

    @staticmethod
    def _template_sign(frame_n, lag=0):
        return 1.0 if (config.MODULATION_FREQ_HZ * (frame_n - lag) / config.FPS) % 1.0 < 0.5 \
            else -1.0

    def corr(self):
        """Best sign-agreement (over 0..3 frame lags) between de-meaned
        brightness samples and the absolute-time modulation template."""
        vals = self.values
        n = len(vals)
        if n < 14:
            return 0.0
        mean_v = sum(vals) / n
        best = 0.0
        for lag in (0, 1, 2, 3):
            agree = 0.0
            for v, f in zip(vals, self.frames):
                sig = 1.0 if v > mean_v else -1.0
                agree += sig * self._template_sign(f, lag)
            c = max(0.0, min(1.0, (agree / n + 1.0) / 2.0))
            if c > best:
                best = c
        return best

    def predictive_corr(self, intensity, frame_n):
        """What corr() would be if this sample were appended to the history.
        Used during LOCKED association to score candidate objects.
        Rejects injection of wrong-target samples into the modulation track."""
        vals = self.values
        n = len(vals)
        if n < 10:
            return 0.5
        new_v = max(0.0, float(intensity))
        new_mean = (sum(vals) + new_v) / (n + 1)
        best = 0.0
        for lag in (0, 1, 2, 3):
            agree = 0.0
            for v, f in zip(vals, self.frames):
                sig = 1.0 if v > new_mean else -1.0
                agree += sig * self._template_sign(f, lag)
            sig_new = 1.0 if new_v > new_mean else -1.0
            agree += sig_new * self._template_sign(frame_n, lag)
            c = max(0.0, min(1.0, (agree / (n + 1) + 1.0) / 2.0))
            if c > best:
                best = c
        return best


class Tracker:
    def __init__(self, ephemeris_model, seed=None):
        self.eph = ephemeris_model
        self.state = SEARCHING
        self.est_az = None
        self.est_el = None
        self.bias_az = 0.0
        self.bias_el = 0.0
        self.last_r_az = 0.0
        self.last_r_el = 0.0
        self.confidence = 0.0
        self.mod = ModulationTrack()
        self._tent_az = None
        self._tent_el = None
        self._tent_frames = 0
        self._tent_miss = 0
        self.coast_time = 0.0
        self.search_angle = 0.0
        self.search_radius = 0.0
        self.acquisition_count = 0
        self.candidates_seen = 0
        self.last_candidate_age = 1e9
        self.last_candidate_az = None
        self.last_candidate_el = None
        self.associated = None
        self._frame = 0
        self._suspect = 0
        self._prior_az_prev = None
        self._prior_el_prev = None

    # ------------------------------------------------------------------
    def reset(self, az, el):
        self.est_az, self.est_el = az, el
        self.bias_az = self.bias_el = 0.0
        self.state = SEARCHING
        self.mod.reset()
        self._tent_az = self._tent_el = None
        self._tent_frames = 0
        self._tent_miss = 0
        self.coast_time = 0.0
        self._suspect = 0
        self._prior_az_prev = None
        self._prior_el_prev = None

    # ------------------------------------------------------------------
    def _prior_gate_deg(self, t):
        return min(config.EPHEMERIS_MAX_BIAS_DEG,
                   config.EPHEMERIS_START_BIAS_DEG
                   + config.EPHEMERIS_GROWTH_DEG_PER_SEC * t * 4.0)

    def update(self, candidates, t, dt):
        """Returns (state, est_az, est_el, confidence)."""
        self._frame += 1
        prior_az, prior_el = self.eph.predict_az_el(t)

        for c in candidates:
            c.mod_score = 0.0
            d_prior = math.hypot(c.los_az - prior_az, c.los_el - prior_el)
            c.prior_score = max(0.0, 1.0 - d_prior / 4.5)
            c.fusion_score = (config.FUSION_WEIGHT_ML * c.ml_score
                              + config.FUSION_WEIGHT_PRIOR * c.prior_score)

        has_track = self.est_az is not None and self.state in (LOCKED, COASTING, TENTATIVE)

        if has_track:
            best = None
            best_score = -1.0
            tentative = self.state == TENTATIVE
            assoc_gate = config.ASSOC_GATE_DEG if not tentative else max(config.ASSOC_GATE_DEG, 0.60)
            w_mod = 0.60 if not tentative else 0.20
            w_ml = 0.25 if not tentative else 0.40
            w_prior = 0.15 if not tentative else 0.25
            w_dist = 0.05 if not tentative else 0.15
            for c in candidates:
                d = math.hypot(c.los_az - self.est_az, c.los_el - self.est_el)
                if d < assoc_gate:
                    if tentative:
                        pred_corr = max(0.5, self.mod.predictive_corr(c.peak, self._frame))
                    else:
                        pred_corr = self.mod.predictive_corr(c.peak, self._frame)
                    c._assoc_score = (w_ml * c.ml_score
                                      + w_prior * c.prior_score
                                      + w_mod * pred_corr
                                      - w_dist * d)
                    if c._assoc_score > best_score:
                        best_score = c._assoc_score
                        best = c
            if best is not None:
                self.last_candidate_age = 0.0
                self.last_candidate_az, self.last_candidate_el = best.los_az, best.los_el
                self.associated = best
                if tentative:
                    return self._on_tentative(best, t, dt, prior_az, prior_el)
                else:
                    return self._on_tracked(best, t, dt, prior_az, prior_el)
        else:
            best = None
            best_score = -1.0
            prior_gate = self._prior_gate_deg(t)
            bore_az = self.est_az if self.est_az is not None else prior_az
            bore_el = self.est_el if self.est_el is not None else prior_el
            bore_gate = max(config.HFOV_DEG * 0.6, 1.2)
            mod_hist = len(self.mod.values) >= 8
            for c in candidates:
                if c.ml_score < config.ML_LOCK_THRESHOLD:
                    continue
                d_prior = math.hypot(c.los_az - prior_az, c.los_el - prior_el)
                d_bore = math.hypot(c.los_az - bore_az, c.los_el - bore_el)
                in_prior = d_prior <= prior_gate
                in_bore = d_bore <= bore_gate
                if not (in_prior or in_bore):
                    continue
                local_score = max(0.0, 1.0 - d_bore / (bore_gate + 0.1))
                prior_sc = max(0.0, 1.0 - d_prior / (prior_gate + 0.1))
                gate_sc = max(local_score, prior_sc)
                if mod_hist:
                    raw_mod = max(0.0, self.mod.predictive_corr(c.peak, self._frame))
                else:
                    raw_mod = 0.5
                score = (0.25 * c.ml_score
                         + 0.30 * gate_sc
                         + 0.15 * c.prior_score
                         + 0.30 * raw_mod)
                if score > best_score:
                    best_score = score
                    best = c
            if best is not None:
                self.last_candidate_age = 0.0
                self.last_candidate_az, self.last_candidate_el = best.los_az, best.los_el
                self.associated = best
                return self._on_tentative(best, t, dt, prior_az, prior_el)

        self.last_candidate_age += dt
        self.associated = None
        return self._on_miss(t, dt)

    # ------------------------------------------------------------------
    def _on_tentative(self, c, t, dt, p_az, p_el):
        """Build a tentative track: spatial consistency, then modulation ID.

        Spatial consistency is measured AGAINST THE FIRST SEEN POSITION of
        the tentative track (not against the previous frame).  This rejects
        gradual walking of the candidate due to turbulence fragmenting the
        blob or distractors being nearby.
        """
        self.candidates_seen += 1
        consistency = config.ACQUIRE_CONSISTENCY_PX / config.PIXELS_PER_DEG

        self._tent_miss = 0
        if self._tent_frames == 0:
            self._tent_az, self._tent_el = c.los_az, c.los_el
            self._tent_frames = 1
        else:
            d = math.hypot(c.los_az - self._tent_az, c.los_el - self._tent_el)
            if d < consistency:
                self._tent_frames += 1
            elif d > consistency * 3:
                self._tent_az, self._tent_el = c.los_az, c.los_el
                self._tent_frames = 1
                self.mod.reset()

        self.mod.push(c.u, c.v, c.peak, self._frame)
        raw_corr = self.mod.corr()
        c.mod_score = raw_corr

        self.est_az, self.est_el = c.los_az, c.los_el
        self.state = TENTATIVE

        need_samples = int(config.MOD_CORREL_WIN * 0.50)
        if self._tent_frames >= config.ACQUIRE_CONFIRM_FRAMES:
            if len(self.mod.values) < need_samples:
                pass
            elif raw_corr >= config.MOD_LOCK_THRESHOLD:
                self._commit(c.los_az, c.los_el, t)
                return self.state, self.est_az, self.est_el, raw_corr
            else:
                self._tent_frames = 0
                self._tent_miss = 0
                self._tent_az = self._tent_el = None
                self.mod.reset()
                self.state = SEARCHING
                return SEARCHING, self.est_az, self.est_el, self.confidence
        return TENTATIVE, self.est_az, self.est_el, self.confidence

    def _on_tracked(self, c, t, dt, p_az, p_el):
        self.candidates_seen += 1

        pred_corr = self.mod.predictive_corr(c.peak, self._frame)

        if pred_corr >= 0.50:
            self.mod.push(c.u, c.v, c.peak, self._frame)
        elif self.state == COASTING and pred_corr >= 0.38:
            self.mod.push(c.u, c.v, c.peak, self._frame)
        # else: candidate is suspicious - do NOT corrupt modulation track.
        #       Still update pointing estimate, but mark as suspect.

        c.mod_score = self.mod.corr()

        if c.mod_score < config.MOD_SUSPECT_FLOOR:
            self._suspect += 1
            if self._suspect >= config.MOD_SUSPECT_DROP_FRAMES:
                self._suspect = 0
                self.mod.reset()
                self.state = SEARCHING
                self.search_angle = 0.0
                self.search_radius = 0.0
                return SEARCHING, self.est_az, self.est_el, self.confidence
        else:
            self._suspect = max(0, self._suspect - 2)

        self.confidence = c.mod_score
        self.state = LOCKED
        self.coast_time = 0.0
        self._tent_az = self._tent_el = None
        self._tent_frames = 0

        r_az = c.los_az - p_az
        r_el = c.los_el - p_el

        a = config.ESTIMATOR_ALPHA
        g = config.ESTIMATOR_GAMMA

        dr_az = r_az - self.last_r_az
        dr_el = r_el - self.last_r_el

        self.bias_az += a * (r_az - self.bias_az) + g * dr_az
        self.bias_el += a * (r_el - self.bias_el) + g * dr_el

        self.last_r_az = r_az
        self.last_r_el = r_el

        if self._prior_az_prev is not None:
            v_az = (p_az - self._prior_az_prev) / max(dt, 1e-6)
            v_el = (p_el - self._prior_el_prev) / max(dt, 1e-6)
            self.est_az = p_az + self.bias_az + g * v_az * dt
            self.est_el = p_el + self.bias_el + g * v_el * dt
        else:
            self.est_az = p_az + self.bias_az
            self.est_el = p_el + self.bias_el

        self._prior_az_prev = p_az
        self._prior_el_prev = p_el

        return self.state, self.est_az, self.est_el, self.confidence

    def _commit(self, az, el, t):
        p_az, p_el = self.eph.predict_az_el(t)
        self.bias_az = az - p_az
        self.bias_el = el - p_el
        self.last_r_az = self.bias_az
        self.last_r_el = self.bias_el
        self.est_az = az
        self.est_el = el
        self.state = LOCKED
        self.acquisition_count += 1
        self.coast_time = 0.0
        self._suspect = 0

    def _on_miss(self, t, dt):
        if self.state == TENTATIVE:
            self._tent_miss += 1
            if self._tent_miss > 8:
                self._tent_frames = 0
                self._tent_miss = 0
                self._tent_az = self._tent_el = None
                self.mod.reset()
                self.state = SEARCHING
                self.est_az = None
                self.est_el = None
                self.coast_time = 0.0
        elif self.state in (LOCKED, COASTING):
            self.coast_time += dt
            if self.coast_time > config.COAST_TIMEOUT_S:
                self.state = SEARCHING
                self.search_angle = 0.0
                self.search_radius = 0.0
            else:
                self.state = COASTING
                p_az, p_el = self.eph.predict_az_el(t)
                if self._prior_az_prev is not None:
                    v_az = (p_az - self._prior_az_prev) / max(dt, 1e-6)
                    v_el = (p_el - self._prior_el_prev) / max(dt, 1e-6)
                    g = config.ESTIMATOR_GAMMA
                    self.est_az = p_az + self.bias_az + g * v_az * dt
                    self.est_el = p_el + self.bias_el + g * v_el * dt
                else:
                    self.est_az = p_az + self.bias_az
                    self.est_el = p_el + self.bias_el
                self._prior_az_prev = p_az
                self._prior_el_prev = p_el
        self.associated = None
        return self.state, self.est_az, self.est_el, self.confidence

    # ------------------------------------------------------------------
    def search_point(self, t, dt):
        rate = config.SEARCH_GROWTH_DEG_S
        self.search_angle += rate * dt * 2.2
        self.search_radius = min(config.SEARCH_MAX_RADIUS_DEG,
                                 self.search_radius + rate * dt * 0.5)
        if self.est_az is None:
            base_az, base_el = self.eph.predict_az_el(t)
        else:
            base_az, base_el = self.est_az, self.est_el
        return (base_az + self.search_radius * math.cos(self.search_angle),
                base_el + self.search_radius * math.sin(self.search_angle))
