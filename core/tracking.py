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
     current LOS estimate gets associated (nearest wins).
  3. Acquisition while SEARCHING: a candidate must clear the appearance bar
     AND sit in the (time-widening) ephemeris gate; it then forms a tentative
     track that must prove **spatial consistency** (same LOS for N frames)
     and **modulation identity** (correlator score over a filled history)
     before LOCKED is committed.  That combination makes false locks
     essentially impossible.
  4. The estimator = ephemeris prior + leaky-absorbed bias: the control loop
     gets smooth feedforward plus a corrective term, so the residual boresight
     error stays a few hundredths of a degree.

The tracker never reads the beacon's true position.
"""

import math
from collections import deque

import config


SEARCHING = "SEARCHING"
COASTING = "COASTING"
LOCKED = "LOCKED"


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
        self.areas = deque(maxlen=win)

    def reset(self):
        self.pxs.clear()
        self.pys.clear()
        self.values.clear()
        self.frames.clear()
        self.areas.clear()

    def push(self, u, v, intensity, frame_n, area=None):
        self.pxs.append(u)
        self.pys.append(v)
        self.values.append(max(0.0, float(intensity)))
        self.areas.append(float(area) if area is not None else float(intensity))
        self.frames.append(int(frame_n))

    @staticmethod
    def _template_sign(frame_n, lag=0):
        # brightness lags the ideal clock by ~1 frame (PSF + pipeline latency);
        # corr() tests a small lag set to stay phase-robust.
        return 1.0 if (config.MODULATION_FREQ_HZ * (frame_n - lag) / config.FPS) % 1.0 < 0.5 \
            else -1.0

    def corr(self):
        """Best sign-agreement (over 0..2 frame lags) between de-meaned
        brightness samples and the absolute-time modulation template."""
        vals = self.values
        n = len(vals)
        if n < 12:
            return 0.0
        mean_v = sum(vals) / n
        best = 0.0
        for lag in (0, 1, 2):
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
        Used during LOCKED association to score candidate objects."""
        vals = self.values
        n = len(vals)
        if n < 8:
            return 0.0
        new_v = max(0.0, float(intensity))
        new_mean = (sum(vals) + new_v) / (n + 1)
        best = 0.0
        for lag in (0, 1, 2):
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

    @staticmethod
    def _blend(sign_agree, depth):
        """0-1 blend of the cadence (sign agreement) and the amplitude (depth)
        evidence.  Depth >=40 px of area swings is treated as fully decisive."""
        return 0.6 * sign_agree + 0.4 * min(1.0, max(0.0, depth) / 40.0)

    def corr_area(self):
        """Continuous AREA-based modulation score of the tracker's history.
        The tracker holds one object through detection ID reseeds, so this
        is the stable 'am I locked onto a true 15 Hz blinker' signal, where
        per-candidate detector tracks under noise can flicker."""
        areas = list(self.areas)
        n = len(areas)
        if n < 8:
            return 0.0
        mean_a = sum(areas) / n
        best_agree, best_depth = 0.0, 0.0
        for lag in (0, 1, 2):
            agree = 0.0
            hi, lo = [], []
            for a, f in zip(areas, self.frames):
                sig = 1.0 if a > mean_a else -1.0
                agree += sig * self._template_sign(f, lag)
                (hi if self._template_sign(f, lag) > 0 else lo).append(a)
            if hi and lo:
                best_depth = max(best_depth, (sum(hi) / len(hi)) - (sum(lo) / len(lo)))
            best_agree = max(best_agree, max(0.0, (agree / n + 1.0) / 2.0))
        return self._blend(best_agree, best_depth)

    def predictive_area(self, area, frame_n):
        """What corr_area() would be if this candidate's AREA were appended."""
        areas = list(self.areas)
        n = len(areas)
        if n < 8:
            return 0.0
        new_a = max(0.0, float(area))
        mean_a = (sum(areas) + new_a) / (n + 1)
        best_agree, best_depth = 0.0, 0.0
        n_ext = n + 1
        for lag in (0, 1, 2):
            agree = 0.0
            hi, lo = [], []
            for a, f in zip(areas, self.frames):
                sig = 1.0 if a > mean_a else -1.0
                agree += sig * self._template_sign(f, lag)
                (hi if self._template_sign(f, lag) > 0 else lo).append(a)
            sig_n = 1.0 if new_a > mean_a else -1.0
            agree += sig_n * self._template_sign(frame_n, lag)
            (hi if self._template_sign(frame_n, lag) > 0 else lo).append(new_a)
            if hi and lo:
                best_depth = max(best_depth, (sum(hi) / len(hi)) - (sum(lo) / len(lo)))
            best_agree = max(best_agree, max(0.0, (agree / n_ext + 1.0) / 2.0))
        return self._blend(best_agree, best_depth)


class Tracker:
    def __init__(self, ephemeris_model, seed=None):
        self.eph = ephemeris_model
        self.state = SEARCHING
        self.est_az = None
        self.est_el = None
        self.bias_az = 0.0
        self.bias_el = 0.0
        self.confidence = 0.0
        self.mod = ModulationTrack()
        self._tent_az = None          # tentative track LOS while acquiring
        self._tent_el = None
        self._tent_frames = 0
        self._tent_id = None          # persistent blob ID held during acquisition
        self.coast_time = 0.0
        self.search_angle = 0.0
        self.search_radius = 0.0
        self.acquisition_count = 0
        self.candidates_seen = 0
        self.last_candidate_age = 1e9
        self.last_candidate_az = None
        self.last_candidate_el = None
        self.associated = None        # candidate associated this frame (or None)
        self._frame = 0
        self._suspect = 0         # consecutive low-modulation associated frames

    # ------------------------------------------------------------------
    def reset(self, az, el):
        self.est_az, self.est_el = az, el
        self.bias_az = self.bias_el = 0.0
        self.state = SEARCHING
        self.mod.reset()
        self._tent_az = self._tent_el = None
        self._tent_frames = 0
        self._tent_id = None
        self.coast_time = 0.0

    # ------------------------------------------------------------------
    def _prior_gate_deg(self, t):
        return min(2.2, 0.55 + 0.28 * math.sqrt(t))

    def update(self, candidates, t, dt):
        """Returns (state, est_az, est_el, confidence)."""
        self._frame += 1
        prior_az, prior_el = self.eph.predict_az_el(t)

        for c in candidates:
            c.mod_score = 0.0
            c.prior_score = max(0.0, 1.0 - math.hypot(c.los_az - prior_az,
                                                      c.los_el - prior_el) / 3.0)
            # persistent (previously-seen) blobs get a fusion edge so acquisition
            # sticks to one physical object instead of hopping between noise blobs
            c.fusion_score = c.ml_score * c.prior_score
            if getattr(c, "track_age", 0) >= 2:
                c.fusion_score *= config.PERSISTENCE_BOOST
            # a blob that actually blinks at the beacon's 15 Hz modulation is
            # overwhelmingly likely to BE the beacon: its own-track peak-mod
            # score caps association/fusion against static beacon-like decoys.
            tm = getattr(c, "track_mod", 0.0)
            if tm >= 0.60:
                c.fusion_score *= 1.0 + config.MOD_ASSOC_K * (tm - 0.50)

        has_track = self.est_az is not None and self.state in (LOCKED, COASTING)

        if has_track:
            # prefer the true 15 Hz blinker: the fused mod boost in the score
            # loop gives a persistent area-modulated blob a strong edge over
            # static beacon-like decoys without ever wrong-restricting (all
            # candidates remain eligible, so no coast-loss when mod dips).
            best = None
            for c in candidates:
                d = math.hypot(c.los_az - self.est_az, c.los_el - self.est_el)
                if d < config.ASSOC_GATE_DEG:
                    if best is None or c.fusion_score > best.fusion_score:
                        best = c
            if best is not None:
                self.last_candidate_age = 0.0
                self.last_candidate_az, self.last_candidate_el = best.los_az, best.los_el
                self.associated = best
                return self._on_tracked(best, t, dt, prior_az, prior_el)
        else:
            # acquisition: best candidate that clears appearance + prior gate.
            # Once a tentative object has been chosen we *hold it by track_id* so
            # modulation history accumulates on ONE physical object; a fresh
            # blob only takes over if the held object is gone or obviously worse.
            best = None
            if self._tent_id is not None and self._tent_frames > 0:
                held = None
                for c in candidates:
                    if getattr(c, "track_id", None) == self._tent_id:
                        held = c
                        break
                if held is not None:
                    best = held
            if best is None:
                for c in candidates:
                    if c.ml_score < config.ML_FLOOR_SCORE:
                        continue
                    if math.hypot(c.los_az - prior_az, c.los_el - prior_el) > self._prior_gate_deg(t):
                        continue
                    if best is None or c.fusion_score > best.fusion_score:
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
        """Build a tentative track: spatial consistency, then modulation ID."""
        self.candidates_seen += 1
        consistency = config.ACQUIRE_CONSISTENCY_PX / config.PIXELS_PER_DEG

        if self._tent_frames == 0:
            self._tent_az, self._tent_el = c.los_az, c.los_el
            self._tent_id = getattr(c, "track_id", None)
            self._tent_frames = 1
        else:
            d = math.hypot(c.los_az - self._tent_az, c.los_el - self._tent_el)
            if d < consistency:
                self._tent_frames += 1
            elif d > consistency * 3:
                # object jumped >> expect -> restart the tentative track
                self._tent_az, self._tent_el = c.los_az, c.los_el
                self._tent_id = getattr(c, "track_id", None)
                self._tent_frames = 1
                self.mod.reset()
            # else: minor jitter, keep counting spaces
        self._tent_az, self._tent_el = c.los_az, c.los_el
        self.mod.push(c.u, c.v, c.peak, self._frame, area=c.area)
        c.mod_score = self.mod.corr()

        # steer the gimbal toward the tentative target so it stays in view
        self.est_az, self.est_el = c.los_az, c.los_el

        # enough temporally-consistent frames AND enough modulation samples
        need_samples = int(config.MOD_CORREL_WIN * 0.8)
        if self._tent_frames >= config.ACQUIRE_CONFIRM_FRAMES:
            if len(self.mod.values) < need_samples:
                # keep gathering evidence (spatial consistency already proven)
                pass
            elif c.mod_score >= config.MOD_LOCK_THRESHOLD:
                self._commit(c.los_az, c.los_el, t)
                return self.state, self.est_az, self.est_el, c.mod_score
            else:
                # modulation fails -> not the real beacon, start over
                self._tent_frames = 0
                self._tent_az = self._tent_el = None
                self._tent_id = None
                self.mod.reset()
        return SEARCHING, self.est_az, self.est_el, self.confidence

    def _on_tracked(self, c, t, dt, p_az, p_el):
        self.candidates_seen += 1
        self.mod.push(c.u, c.v, c.peak, self._frame, area=c.area)
        c.mod_score = self.mod.corr()
        # continuous modulation verification: a locked object that STOPPED
        # matching the beacon signature is a false lock -> drop back to search
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
            self._suspect = 0
        self.confidence = c.mod_score
        self.state = LOCKED
        self.coast_time = 0.0
        self._tent_az = self._tent_el = None
        self._tent_frames = 0
        self._tent_id = None
        r_az = c.los_az - p_az
        r_el = c.los_el - p_el
        a = config.ESTIMATOR_ALPHA
        self.bias_az += a * (r_az - self.bias_az)
        self.bias_el += a * (r_el - self.bias_el)
        self.est_az = p_az + self.bias_az
        self.est_el = p_el + self.bias_el
        return self.state, self.est_az, self.est_el, self.confidence

    def _commit(self, az, el, t):
        p_az, p_el = self.eph.predict_az_el(t)
        self.bias_az = az - p_az
        self.bias_el = el - p_el
        self.est_az = az
        self.est_el = el
        self.state = LOCKED
        self.acquisition_count += 1
        self.coast_time = 0.0
        self._tent_id = None

    def _on_miss(self, t, dt):
        if self.state in (LOCKED, COASTING):
            self.coast_time += dt
            if self.coast_time > config.COAST_TIMEOUT_S:
                self.state = SEARCHING
                self.search_angle = 0.0
                self.search_radius = 0.0
            else:
                self.state = COASTING
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