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
     and - when MODULATION_ENABLED - **modulation identity** (correlator score
     over a filled history) before LOCKED is committed.  With modulation
     disabled (or in video mode) the appearance-classifier threshold replaces
     the modulation cross-check so tracking never depends on the beacon
     signature.  That combination makes false locks essentially impossible.
  4. The estimator = ephemeris prior + leaky-absorbed bias: the control loop
     gets smooth feedforward plus a corrective term, so the residual boresight
     error stays a few hundredths of a degree.

The tracker never reads the beacon's true position.
"""

import math
from collections import deque

import config
from core.confidence import ConfidenceState
from core.uncertainty import UncertaintyEstimator
from core.trust import (AdaptiveTrustManager, MODE_BALANCED, MODE_VISION,
                        MODE_MODEL)


SEARCHING = config.STATE_SEARCHING
CANDIDATE = config.STATE_CANDIDATE
ACQUIRING = config.STATE_ACQUIRING
LOCKED = config.STATE_LOCKED
DEGRADED_LOCK = config.STATE_DEGRADED_LOCK
COASTING = config.STATE_COASTING
REACQUIRING = config.STATE_REACQUIRING
LOST = config.STATE_LOST


class ModulationTrack:
    """Brightness history of the *single associated object*, sign-agreement
    correlated against the known 15 Hz beacon square-wave signature.

    The template is anchored to the ABSOLUTE frame index of every sample
    (stored alongside the intensity), so the correlation phase is locked to
    the real modulation clock rather than rotating with the sliding window.
    """

    def __init__(self, win=config.MOD_CORREL_WIN):
        self.win = win
        self.fps = config.FPS            # actual loop sample rate (60 live / 30 mp4)
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

    def _template_sign(self, frame_n, lag=0):
        # brightness lags the ideal clock by ~1 frame (PSF + pipeline latency);
        # corr() tests a small lag set to stay phase-robust.  The template is
        # anchored to the REAL sample rate (self.fps = 1/dt), so a 30 fps MP4
        # pipeline acquires exactly as a 60 fps live loop does.
        return 1.0 if (config.MODULATION_FREQ_HZ * (frame_n - lag) / self.fps) % 1.0 < 0.5 \
            else -1.0

    def corr(self):
        """Best sign-agreement (over 0..MODULATION_TOLERANCE_FRAMES frame lags)
        between de-meaned brightness samples and the absolute-time modulation
        template."""
        vals = self.values
        n = len(vals)
        if n < 12:
            return 0.0
        mean_v = sum(vals) / n
        best = 0.0
        for lag in range(config.MODULATION_TOLERANCE_FRAMES + 1):
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
        for lag in range(config.MODULATION_TOLERANCE_FRAMES + 1):
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
        for lag in range(config.MODULATION_TOLERANCE_FRAMES + 1):
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
        for lag in range(config.MODULATION_TOLERANCE_FRAMES + 1):
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
    def __init__(self, ephemeris_model, seed=None, video_mode=False,
                 gate_deg=config.ASSOC_GATE_DEG, cu=None, cv=None):
        self.eph = ephemeris_model
        self.cu = float(cu) if cu is not None else float(getattr(config, "CAM_VIEW_W", 640)) / 2.0
        self.cv = float(cv) if cv is not None else float(getattr(config, "CAM_VIEW_H", 480)) / 2.0
        # video_mode=True (Benchmark-2 MP4 bypass): an external video feeds the
        # coarse-pointing loop.  Its beacon has no known 15 Hz modulation clock,
        # so acquisition / lock-hold use appearance + temporal persistence
        # confidence instead of the modulation correlator.
        self.video_mode = video_mode
        # Modulation identity signalling is configurable (MODULATION_ENABLED)
        # AND never starves tracking: when it is off (or in video mode) the
        # tracker acquires/locks with appearance + persistence + spatial
        # consistency + SNR + ephemeris prior only.  use_modulation gates every
        # modulation threshold, penalty and rejection rule in one place.
        self.use_modulation = config.MODULATION_ENABLED and not video_mode
        self.gate_deg = gate_deg
        self._dt = 0.0
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

        # ---- Phase 2: unified confidence + uncertainty + adaptive trust ----
        self.phase = SEARCHING    # fine-grained phase (CANDIDATE/ACQUIRING/...)
        self.conf = ConfidenceState()
        self.unc = UncertaintyEstimator()
        self.trust = AdaptiveTrustManager()
        self.dist_level_est = 0.0      # tracker-derived disturbance condition (0-1)
        self.coast_mode = None         # last coasting mode (for GUI/metrics)
        # Part 3 staged-reacquisition state: which recovery level (1..N) the
        # tracker is on, and how long it has been actively REACQUIRING.
        self.reacq_level = 1
        self.reacq_time = 0.0
        self.vel_az = 0.0
        self.vel_el = 0.0
        self._pv_az = None
        self._pv_el = None
        self._pv_u = None
        self._pv_v = None
        self._prev_track_az = None
        self._prev_track_el = None
        self._prev_track_t = None
        self._prev_bias_r_az = None
        self._prev_bias_r_el = None
        self._prev_bias_az = None
        self._prev_bias_el = None
        self._prev_los_az = None
        self._prev_los_el = None
        # one-frame handover flag: holds the widened REACQ gate for the frame
        # immediately after a successful promotion from REACQUIRING -> LOCKED/
        # DEGRADED_LOCK so the just-associated candidate is not dropped by the
        # now-smaller LOCKED association gate on the next frame.
        self._reacq_handover = 0
        self._measurement_valid = False
        self._consecutive_valid_frames = 0
        self._reacq_confirm_frames = 0
        self._lost_time = 0.0

    @property
    def is_locked(self) -> bool:
        """True ONLY when the tracker has satisfied its actual lock criteria."""
        return self.state == LOCKED

    @property
    def is_degraded(self) -> bool:
        return self.state == DEGRADED_LOCK

    @property
    def measurement_valid(self) -> bool:
        """True if associated observation was valid this frame, False otherwise."""
        return self._measurement_valid

    @property
    def measurement_age(self) -> float:
        """Seconds since the last valid observation was associated."""
        return self.last_candidate_age

    @property
    def prediction_only(self) -> bool:
        """True if currently relying on motion model / Kalman extrapolation without valid measurement."""
        return self.state in (COASTING, REACQUIRING, LOST) or not self._measurement_valid

    # ------------------------------------------------------------------
    def reset(self, az, el):
        self.est_az, self.est_el = az, el
        self.bias_az = self.bias_el = 0.0
        self.state = SEARCHING
        self.mod.reset()
        self._tent_az = self._tent_el = None
        self._tent_frames = 0
        self._tent_id = None
        self._tent_dj = 0.0
        self.coast_time = 0.0
        self.vel_az = self.vel_el = 0.0
        self._pv_az = self._pv_el = None
        self._pv_u = self._pv_v = None
        self._prev_track_az = self._prev_track_el = None
        self._prev_track_t = None
        self._prev_bias_r_az = self._prev_bias_r_el = None
        self._prev_bias_az = self._prev_bias_el = 0.0
        self._prev_los_az = self._prev_los_el = None
        self._jit_px = 0.0
        self.last_candidate_az = None
        self.last_candidate_el = None
        self.phase = SEARCHING
        self.conf = ConfidenceState()
        self.unc = UncertaintyEstimator()
        self.trust = AdaptiveTrustManager()
        self.dist_level_est = 0.0
        self.coast_mode = None
        self.reacq_level = 1
        self.reacq_time = 0.0
        self._reacq_handover = 0
        self._measurement_valid = False
        self._consecutive_valid_frames = 0
        self._reacq_confirm_frames = 0
        self._lost_time = 0.0
        self.last_candidate_age = 1e9
        self.associated = None

    # ------------------------------------------------------------------
    def _prior_gate_deg(self, t):
        if self.video_mode:
            return self.gate_deg * 1.2
        return min(2.2, 0.55 + 0.28 * math.sqrt(t))

    @staticmethod
    def _snr_reliability(snr):
        """Bounded 0-1 measurement reliability from its SNR (the same shape the
        trust manager uses in its vision fusion), floored at 0.5 so a
        momentarily fading beacon is discounted but never catastrophically
        de-ranked against a brighter static blob that merely sits closer to the
        gate centre."""
        return max(0.5, min(1.0, snr / (snr + 10.0)))

    def _assoc_gate_deg(self):
        """Uncertainty-aware association gate (synthetic mode, modulation on or
        off alike, per config.py's documented effective_gate model):
            base_gate
            + ASSOC_UNCERTAINTY_FACTOR * internal sigma (px -> deg)
            + ASSOC_LATENCY_MARGIN_FACTOR * predicted motion during gimbal latency
        clamped to ASSOC_MAX_GATE_DEG.  Reads the INTERNAL (uncapped) sigma so
        the HUD display cap can never gate loop behaviour.  Video mode keeps its
        own wide field-facing gate without growth or clamping."""
        if self.video_mode:
            return self.gate_deg
        gate = self.gate_deg
        gate += config.ASSOC_UNCERTAINTY_FACTOR * (
            self.unc.sigma_px / config.PIXELS_PER_DEG)
        lat_s = config.GIMBAL_LATENCY_FRAMES * (getattr(self, "_dt", 0.0) or 0.0)
        speed = math.hypot(getattr(self, "vel_az", 0.0) or 0.0,
                           getattr(self, "vel_el", 0.0) or 0.0)
        gate += config.ASSOC_LATENCY_MARGIN_FACTOR * lat_s * speed
        return min(config.ASSOC_MAX_GATE_DEG, gate)

    def update(self, candidates, t, dt):
        """Returns (state, est_az, est_el, confidence)."""
        self._frame += 1
        self._dt = dt
        if dt > 0:
            self.mod.fps = 1.0 / dt      # 60 live / 30 mp4: template clock
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
            # score lifts association against static beacon-like decoys.  Only
            # while modulation identity is active - with modulation disabled a
            # meaningless (noise-driven) track_mod must never prize a blob.
            tm = getattr(c, "track_mod", 0.0)
            if self.use_modulation and tm >= config.ASSOC_TRACK_MOD_MIN:
                c.fusion_score *= 1.0 + config.MOD_ASSOC_K * (tm - 0.50)
            # combined association / reliability score used to pick the winner
            # among in-gate candidates while LOCKED/COASTING: the fused
            # appearance x prior x persistence x modulation score, discounted by
            # a bounded SNR reliability factor (a faint flickering blob cannot
            # out-rank a brighter, more stable one).
            c._assoc_score = c.fusion_score * self._snr_reliability(c.snr)

        has_track = self.est_az is not None and self.state in (LOCKED, COASTING,
                                                        DEGRADED_LOCK,
                                                        REACQUIRING)

        if has_track:
            best = None
            # Track continuity: if we are already actively tracking a target with a persistent track_id,
            # bind to that track_id so adjacent/crossing secondary targets or noise cannot steal the lock.
            if self.associated is not None:
                held_id = getattr(self.associated, "track_id", None)
                if held_id is not None:
                    ref_az = self.last_candidate_az if self.last_candidate_az is not None \
                        else getattr(self.associated, "los_az", None)
                    ref_el = self.last_candidate_el if self.last_candidate_el is not None \
                        else getattr(self.associated, "los_el", None)
                    if ref_az is not None:
                        d_best = self._assoc_gate_deg()
                        for c in candidates:
                            if getattr(c, "track_id", None) == held_id:
                                d = math.hypot(c.los_az - ref_az,
                                               c.los_el - ref_el)
                                if d < d_best:
                                    d_best, best = d, c
                    else:
                        for c in candidates:
                            if getattr(c, "track_id", None) == held_id:
                                best = c
                                break
            if best is None:
                # active REACQUIRING widens the association gate around the
                # predicted LOS so a beacon returning after a blank links the
                # moment it peeks back in (the "gate widens" documented for
                # REACQUIRING in core/control.py).  Any object caught by the
                # wider gate still has to pass the full _on_tracked
                # appearance/modulation verification before LOCKED.
                gate = self._assoc_gate_deg()
                if self.state == REACQUIRING or getattr(self, "_reacq_handover", 0) > 0:
                    gate *= config.REACQ_LEVEL_GATE_MULT[
                        max(0, min(config.REACQ_LEVELS - 1, self.reacq_level - 1))]
                    if getattr(self, "_reacq_handover", 0) > 0:
                        self._reacq_handover = 0
                best_metric = -1e9
                for c in candidates:
                    d = math.hypot(c.los_az - self.est_az, c.los_el - self.est_el)
                    if d < gate:
                        # GNN / Distance-penalized metric: strongly penalize targets far from estimated track
                        d_norm = d / max(1e-6, gate)
                        dist_factor = 1.0 / (1.0 + 4.0 * d_norm * d_norm)
                        metric = c._assoc_score * dist_factor
                        if metric > best_metric:
                            best_metric = metric
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
                best_score = -1e9
                for c in candidates:
                    if c.ml_score < config.ML_FLOOR_SCORE:
                        continue
                    d_prior = math.hypot(c.los_az - prior_az, c.los_el - prior_el)
                    if d_prior > self._prior_gate_deg(t):
                        continue
                    # Primary acquisition priority: candidate nearest to ephemeris prior
                    d_norm = d_prior / max(1e-6, self._prior_gate_deg(t))
                    score = c.fusion_score / (1.0 + 3.0 * d_norm * d_norm)
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
        """Build a tentative track: spatial consistency, then modulation ID."""
        self._measurement_valid = True
        self.candidates_seen += 1
        consistency = config.ACQUIRE_CONSISTENCY_PX / config.PIXELS_PER_DEG

        if self._tent_frames == 0:
            self._tent_az, self._tent_el = c.los_az, c.los_el
            self._tent_id = getattr(c, "track_id", None)
            self._tent_frames = 1
            self._consecutive_valid_frames = 1
            self._tent_dj = 0.0
            self.state = CANDIDATE
            self.phase = CANDIDATE
        else:
            d = math.hypot(c.los_az - self._tent_az, c.los_el - self._tent_el)
            tol_base = max(consistency, self._tent_dj * 6.0)
            if d < consistency or d < tol_base:
                self._tent_frames += 1
                self._consecutive_valid_frames += 1
                self.state = ACQUIRING
                self.phase = ACQUIRING
            elif d > consistency * 3:
                # Decoy hop / jump -> restart tentative track
                self._tent_az, self._tent_el = c.los_az, c.los_el
                self._tent_id = getattr(c, "track_id", None)
                self._tent_frames = 1
                self._consecutive_valid_frames = 1
                self.mod.reset()
                self.state = CANDIDATE
                self.phase = CANDIDATE
            self._tent_dj = 0.75 * self._tent_dj + 0.25 * d

        self._tent_az, self._tent_el = c.los_az, c.los_el
        self.mod.push(c.u, c.v, c.peak, self._frame, area=c.area)
        c.mod_score = self.mod.corr()

        self._update_conf(c, p_az, p_el)
        self.trust.update(conf=self.conf, mod_score=0.0, snr=c.snr,
                          dist_level=self.dist_level_est, visible=True,
                          mod_enabled=self.use_modulation)

        # steer the gimbal toward the tentative target so it stays in view
        self.est_az, self.est_el = c.los_az, c.los_el
        self._pv_u, self._pv_v = c.u, c.v
        self.confidence = self.conf.overall

        # Qualification for LOCKED:
        # 1. Minimum consecutive valid observation frames (config.LOCK_CONFIRM_FRAMES = 5)
        # 2. Overall confidence >= config.LOCK_MIN_CONF (0.70)
        # 3. Internal uncertainty sigma <= config.LOCK_MAX_UNCERTAINTY_PX (14.0 px)
        can_lock = (self._consecutive_valid_frames >= config.LOCK_CONFIRM_FRAMES
                    and self.conf.overall >= config.LOCK_MIN_CONF
                    and self.unc.sigma_px <= config.LOCK_MAX_UNCERTAINTY_PX)

        need_samples = int(config.MOD_CORREL_WIN * 0.8)
        if self.use_modulation:
            if len(self.mod.values) < need_samples:
                # keep gathering evidence in ACQUIRING state
                return self.state, self.est_az, self.est_el, self.confidence
            elif can_lock and (c.mod_score >= config.MOD_LOCK_THRESHOLD
                               or (c.ml_score >= 0.85 and c.mod_score >= config.MOD_SUSPECT_FLOOR)):
                self._commit(c.los_az, c.los_el, t)
                return self.state, self.est_az, self.est_el, self.confidence
            elif len(self.mod.values) >= int(config.MOD_CORREL_WIN * 1.5) and c.mod_score < config.MOD_SUSPECT_FLOOR:
                # modulation actively contradicts beacon signature (decoy frequency) -> start over
                self._reset_tentative()
                self.state = SEARCHING
                self.phase = SEARCHING
                return self.state, self.est_az, self.est_el, self.confidence
        elif self.video_mode:
            if can_lock:
                self._commit(c.los_az, c.los_el, t)
                return self.state, self.est_az, self.est_el, self.confidence
        else:
            # Synthetic beacon, modulation disabled
            if can_lock and c.ml_score >= config.ML_LOCK_THRESHOLD:
                self._commit(c.los_az, c.los_el, t)
                return self.state, self.est_az, self.est_el, self.confidence
            elif self._consecutive_valid_frames >= config.LOCK_CONFIRM_FRAMES and c.ml_score < config.ML_LOCK_THRESHOLD:
                self._reset_tentative()
                self.state = SEARCHING
                self.phase = SEARCHING
                return self.state, self.est_az, self.est_el, self.confidence

        return self.state, self.est_az, self.est_el, self.confidence

    def _reset_tentative(self):
        self._tent_frames = 0
        self._consecutive_valid_frames = 0
        self._tent_az = self._tent_el = None
        self._tent_id = None
        self.mod.reset()

    def _on_tracked(self, c, t, dt, p_az, p_el):
        self._measurement_valid = True
        prev_state = self.state
        self.candidates_seen += 1
        self.mod.push(c.u, c.v, c.peak, self._frame, area=c.area)
        c.mod_score = self.mod.corr()

        # If recovering from COASTING or actively in REACQUIRING, candidate must be confirmed
        if prev_state == COASTING:
            self.state = REACQUIRING
            self.phase = REACQUIRING
            self._reacq_confirm_frames = 1
        elif prev_state == REACQUIRING:
            self._reacq_confirm_frames += 1

        # continuous modulation verification: a locked object that STOPPED
        # matching the beacon signature is a false lock -> drop to COASTING
        if self.use_modulation and c.mod_score < config.MOD_SUSPECT_FLOOR:
            self._suspect += 1
            if self._suspect >= config.MOD_SUSPECT_DROP_FRAMES:
                self._suspect = 0
                self.mod.reset()
                self.state = COASTING
                self.phase = COASTING
                self._measurement_valid = False
                self.coast_time = 0.0
                self.reacq_level = 1
                self.reacq_time = 0.0
                self._reacq_confirm_frames = 0
                return self.state, self.est_az, self.est_el, self.confidence
        else:
            self._suspect = 0

        # ---- Phase 2 confidence + trust ----
        self._update_conf(c, p_az, p_el)
        mode = self.trust.update(conf=self.conf,
                                 mod_score=(0.0 if not self.use_modulation
                                            else self.mod.corr_area()),
                                 snr=c.snr, dist_level=self.dist_level_est,
                                 visible=True, mod_enabled=self.use_modulation)
        self.coast_mode = mode
        self.unc.observe(snr=c.snr,
                         centroid_residual_px=self._centroid_jitter_px(c),
                         pred_residual_px=getattr(self, "_resid_deg_lead", 0.0)
                         * config.PIXELS_PER_DEG)

        # State determination
        if prev_state in (COASTING, REACQUIRING):
            # Staged reacquisition confirmation: must have enough consecutive frames and confidence
            if (self._reacq_confirm_frames >= config.REACQ_CONFIRM_FRAMES
                    and self.conf.overall >= config.LOCK_MIN_CONF):
                self.state = LOCKED
                self.phase = LOCKED
                self.coast_time = 0.0
                self.reacq_time = 0.0
                self._reacq_confirm_frames = 0
                self._reacq_handover = 1
            elif (self._reacq_confirm_frames >= config.REACQ_CONFIRM_FRAMES
                    and self.conf.overall >= config.DEGRADED_ENTER_CONF):
                self.state = DEGRADED_LOCK
                self.phase = DEGRADED_LOCK
                self.coast_time = 0.0
                self.reacq_time = 0.0
                self._reacq_confirm_frames = 0
                self._reacq_handover = 1
            else:
                self.state = REACQUIRING
                self.phase = REACQUIRING
        else:
            # Already in LOCKED or DEGRADED_LOCK
            if self.conf.overall >= config.LOCK_MIN_CONF:
                self.state = LOCKED
                self.phase = LOCKED
            elif self.conf.overall >= config.LOCK_HOLD_MIN_CONF or c.ml_score >= 0.70:
                self.state = DEGRADED_LOCK
                self.phase = DEGRADED_LOCK
            else:
                # Confidence collapsed and beacon lost -> drop to COASTING
                self.state = COASTING
                self.phase = COASTING
                self._measurement_valid = False
                self.coast_time = 0.0
                self.reacq_time = 0.0
                self._reacq_confirm_frames = 0

        self.confidence = self.conf.overall
        if self.state in (LOCKED, DEGRADED_LOCK):
            self.coast_time = 0.0
            self._tent_az = self._tent_el = None
            self._tent_frames = 0
            self._tent_id = None
        r_az = c.los_az - p_az
        r_el = c.los_el - p_el
        a = config.ESTIMATOR_ALPHA
        # velocity-adaptive gain: a fast-moving target needs a faster bias
        # filter (lag scales with target speed); a slow one benefits from
        # smoothing.  The measurement itself is a sub-pixel intensity-weighted
        # centroid, so the added high-gain noise is negligible versus the
        # lag it removes (SEVERE random track: 0.30 deg -> <0.10 deg).
        if self._prev_bias_r_az is not None and dt > 0:
            v = math.hypot(c.los_az - self._prev_track_az,
                           c.los_el - self._prev_track_el) / dt
            a_vis = min(config.ESTIMATOR_ALPHA + config.ESTIMATOR_LAG_GAIN * v,
                        config.ESTIMATOR_ALPHA_MAX)
            # trust-adaptive observation gain:
            #   VISION_DOMINANT -> belief collapses toward the camera (jerk /
            #     wrong prior): give the observation the floor and follow it.
            #   MODEL_DOMINANT  -> measurement degraded (fade / noise):
            #     smooth through it instead of chasing the noise.
            #   BALANCED        -> both agree: the normal verification-tested
            #     velocity-adaptive gain is kept bit-for-bit.
            if not self.video_mode and mode == MODE_VISION:
                a = config.ESTIMATOR_ALPHA_MAX
            elif not self.video_mode and mode == MODE_MODEL:
                a = a_vis * 0.5
            else:
                a = a_vis
            # velocity feedforward cancels the remaining EMA lag on a target
            # that accelerates (random walk, jerk).  The bias' time constant is
            # (1-a)/a frames; adding 80% of the bias-requirement derivative
            # scaled by that constant peers ahead just enough to remove lag
            # without overshoot on measurement noise (sub-pixel centroid).
            lag_s = (1.0 - a) / a * dt
            dr_az = (r_az - self._prev_bias_r_az) / max(dt, 1e-6)
            dr_el = (r_el - self._prev_bias_r_el) / max(dt, 1e-6)
            self.bias_az += a * (r_az - self.bias_az) + 0.8 * dr_az * lag_s
            self.bias_el += a * (r_el - self.bias_el) + 0.8 * dr_el * lag_s
            self._prev_bias_r_az, self._prev_bias_r_el = r_az, r_el
        else:
            self.bias_az += a * (r_az - self.bias_az)
            self.bias_el += a * (r_el - self.bias_el)
        self.est_az = p_az + self.bias_az
        self.est_el = p_el + self.bias_el
        self._prev_track_az, self._prev_track_el = c.los_az, c.los_el
        # smoothed beacon velocity (deg/s) for the controller's lead / gimbal
        # transport-delay prediction.  An EMA rejects per-frame centroid
        # noise while still tracking the genuine low-frequency slew.
        if self._prev_track_t is not None and dt > 0:
            vaz = (c.los_az - self._pv_az) / dt
            vel_el = (c.los_el - self._pv_el) / dt
            av = config.CONTROL_VEL_EMA
            self.vel_az = av * vaz + (1.0 - av) * self.vel_az
            self.vel_el = av * vel_el + (1.0 - av) * self.vel_el
        self._pv_az, self._pv_el = c.los_az, c.los_el
        self._pv_u, self._pv_v = c.u, c.v
        self._prev_track_t = t
        # If we just promoted a candidate while we were actively REACQUIRING,
        # hold the widened REACQ gate for one subsequent frame so the
        # association does not immediately evaporate when the state's gate
        # multiplier is removed.
        if prev_state == REACQUIRING and self.state in (LOCKED, DEGRADED_LOCK):
            self._reacq_handover = 1
        return self.state, self.est_az, self.est_el, self.confidence

    def _commit(self, az, el, t):
        p_az, p_el = self.eph.predict_az_el(t)
        self.bias_az = az - p_az
        self.bias_el = el - p_el
        self._prev_bias_az = self.bias_az
        self._prev_bias_el = self.bias_el
        self.est_az = az
        self.est_el = el
        self.state = LOCKED
        self.phase = LOCKED
        self.acquisition_count += 1
        self.coast_time = 0.0
        self._tent_id = None
        self._consecutive_valid_frames = 0
        self._reacq_confirm_frames = 0

    # ------------------------------------------------------------------
    def _update_conf(self, c, p_az, p_el):
        """Fill the unified ConfidenceState for an observation (0-1 each).

        The disturbance condition fed to the TrustManager is *derived* from
        measurement quality (SNR, centroid flicker, model residual) -- the
        tracker never reads the true disturbance value (blind mode).
        """
        # "Is the motion-model prediction reliable?"  Two residuals are kept:
        #
        #  * _resid_deg_lead (estimator quality): the observation vs the FUSED
        #    belief (bias-absorbed estimate + velocity lead).  This is what the
        #    the uncertainty estimator and the derived disturbance estimate read:
        #    it stays small by construction, exactly because the bias filter
        #    learns the prior's static error away.  Byte-identical to the
        #    pre-manoeuvre-forward legacy behaviour.
        #
        #  * prior_resid_deg (TRUST signal, confidence.py's documented
        #    "residual between model prior and observation"): the observation
        #    vs the RAW ephemeris prediction (prior + velocity lead, NO learned
        #    bias), BARRING the magnitude the bias filter already explains.
        #    The bias is the model's own learned calibration error; a static
        #    ephemeris offset (which every preset carries, and which the
        #    estimator legitimately absorbs) should NOT be re-flagged as a
        #    failing model.  Only the part of the disagreement the bias does
        #    NOT explain -- a corrupted prior, a manoeuvre the ephemeris never
        #    knew about, a target agenda change -- collapses conf.prediction,
        #    model trust falls, and the AdaptiveTrustManager hands control to
        #    the camera (VISION_DOMINANT).
        _lead_dt = self._dt or (1.0 / config.FPS)
        if self.est_az is not None:
            _base_az, _base_el = self.est_az, self.est_el
        else:
            _base_az, _base_el = p_az + self.bias_az, p_el + self.bias_el
        resid_deg = math.hypot(c.los_az - (_base_az + self.vel_az * _lead_dt),
                               c.los_el - (_base_el + self.vel_el * _lead_dt))
        self._resid_deg_lead = resid_deg
        prior_resid_deg = math.hypot(c.los_az - (p_az + self.vel_az * _lead_dt),
                                     c.los_el - (p_el + self.vel_el * _lead_dt))
        self._prior_resid_deg = prior_resid_deg
        effective_bias = math.hypot(self.bias_az, self.bias_el)
        if self.state in (CANDIDATE, ACQUIRING) and self._tent_az is not None:
            effective_bias = math.hypot(self._tent_az - p_az, self._tent_el - p_el)
        _unexplained_deg = max(0.0, prior_resid_deg - effective_bias)
        self._unexplained_resid_deg = _unexplained_deg
        # how hard must the filter CHASE the ephemeris right now (deg/s)?
        # The bias magnitude can absorb a lot, but the rate at which the bias
        # must keep moving cannot: a static offset needs a flat bias; a
        # corrupted prior or an accelerating/slewing target keeps the bias
        # re-angling frame after frame.  That chase rate IS the proof the
        # model is wrong, so it feeds the trust-facing prediction residual.
        if self._prev_bias_az is not None and _lead_dt > 0:
            _chase = math.hypot(self.bias_az - self._prev_bias_az,
                                self.bias_el - self._prev_bias_el) / _lead_dt
        else:
            _chase = 0.0
        self._prev_bias_az, self._prev_bias_el = self.bias_az, self.bias_el
        self._prior_chase_rate = _chase
        _model_disagreement_deg = max(_unexplained_deg,
                                      config.TRUST_CHASE_K * _chase)
        if not self.use_modulation:
            # modulation disabled / video mode: modulation carries no identity
            # information, so the appearance evidence stands alone - no
            # modulation contribution and no modulation penalty.
            identity_src = c.ml_score
        else:
            # Identity = AI appearance (the trained, verified classifier) fused
            # with the continuous 15 Hz modulation evidence.  Both are needed:
            # appearance alone can be fooled by a luminous decoy, modulation
            # alone can flicker under noise (corr_area dips on uniform patches).
            # FUSION_WEIGHT_* in config.py are the single source of truth.
            identity_src = (config.FUSION_WEIGHT_ML * c.ml_score
                            + config.FUSION_WEIGHT_MOD * self.mod.corr_area())
        self.conf.update(
            identity_src=identity_src,
            snr=c.snr,
            centroid_residual_px=self._centroid_jitter_px(c),
            pred_residual_deg=_model_disagreement_deg,
            pred_scale_deg=max(0.08, self._prior_gate_deg(self.coast_time)),
            model_conf=(0.25 if self.video_mode else 1.0),
            dist_level=self.dist_level_est,
            point_err_deg=self.point_err_deg if hasattr(self, "point_err_deg") else 0.0,
            point_err_scale_deg=0.2,
            unc_sigma_px=self.unc.sigma_px)
        # derived disturbance condition for the trust manager (blind estimate)
        self.dist_level_est = max(
            0.0, min(1.0, 0.8 * (1.0 - self.conf.position)
                     + 0.2 * min(1.0, resid_deg / 0.4)))

    def _centroid_jitter_px(self, c):
        """EMA of genuine sub-pixel centroid measurement jitter.
        Uses inertial line-of-sight angles (los_az, los_el) so that gimbal slew
        correcting toward boresight is NEVER falsely penalized as jitter noise."""
        if not hasattr(self, "_prev_los_az") or self._prev_los_az is None:
            self._prev_los_az = c.los_az
            self._prev_los_el = c.los_el
            self._jit_px = 0.0
            return 0.0
        dt = getattr(self, "_dt", 1.0 / config.FPS) or (1.0 / config.FPS)
        exp_daz = (getattr(self, "vel_az", 0.0) or 0.0) * dt
        exp_del = (getattr(self, "vel_el", 0.0) or 0.0) * dt
        d_ang_deg = math.hypot((c.los_az - self._prev_los_az) - exp_daz,
                               (c.los_el - self._prev_los_el) - exp_del)
        self._prev_los_az = c.los_az
        self._prev_los_el = c.los_el
        d_px = d_ang_deg * config.PIXELS_PER_DEG
        j = getattr(self, "_jit_px", d_px)
        self._jit_px = 0.6 * d_px + 0.4 * j
        return self._jit_px

    def _coast_vel(self):
        """Effective deg/s velocity used to extrapolate the fused estimate while
        the beacon is unobserved (predictive coast).

        The smoothed *tracked* velocity (vel_az/el) already moves the belief.
        On top we add a small configurable forward lead scaled by the gimbal
        transport delay (GIMBAL_LATENCY_FRAMES) so the camera keeps riding the
        target's genuine slew instead of trailing it through the latency."""
        vaz = self.vel_az or 0.0
        vel = self.vel_el or 0.0
        if config.COAST_LATENCY_LEAD:
            lat_s = config.GIMBAL_LATENCY_FRAMES * (self._dt or (1.0 / config.FPS))
        else:
            lat_s = 0.0
        lead = config.COAST_VELOCITY_LEAD_S + lat_s
        return vaz * (1.0 + lead), vel * (1.0 + lead)

    @staticmethod
    def _reacq_level_for(t):
        """Recovery LEVEL (1..N) active after `t` seconds of REACQUIRING, from
        the cumulative per-level duration budgets (config.REACQ_LEVEL_DURATION_S)."""
        cum = 0.0
        for i, d in enumerate(config.REACQ_LEVEL_DURATION_S):
            cum += d
            if t < cum or i == config.REACQ_LEVELS - 1:
                return i + 1
        return config.REACQ_LEVELS

    def _on_miss(self, t, dt):
        self._measurement_valid = False
        self._consecutive_valid_frames = 0
        self._reacq_confirm_frames = 0

        if self.state in (LOCKED, DEGRADED_LOCK):
            # enter predictive coast on the first missed frame: without this the
            # ladder has no way to progress LOCKED -> COASTING -> REACQUIRING -> LOST
            self.state = COASTING
            self.phase = COASTING
            self.coast_time = 0.0
            self.reacq_time = 0.0

        if self.state in (COASTING, REACQUIRING):
            self.coast_time += dt
            # prediction uncertainty grows (correctly) uncapped while unobserved
            self.unc.coast(dt)
            caz, cel = self._coast_vel()
            if self.est_az is not None:
                self.est_az += caz * dt
                self.est_el += cel * dt

            # staged reacquisition ladder: once uncertainty is past credible,
            # escalate REACQUIRING LEVEL 1 -> 2 -> 3 (each a wider association
            # gate + faster expanding-spiral growth) until the whole configurable
            # ladder times out (~1 s) and the loop falls through to LOST.
            if self.state == COASTING and self.unc.reacquire_threshold_reached():
                self.state = REACQUIRING
                self.phase = REACQUIRING
                self.reacq_level = 1
                self.reacq_time = 0.0
                self.search_angle = 0.0
                self.search_radius = 0.0
            elif self.state == REACQUIRING:
                self.reacq_time += dt
                self.reacq_level = self._reacq_level_for(self.reacq_time)
                if self.reacq_time > config.REACQ_TIMEOUT_S:
                    self.state = LOST
                    self.phase = LOST
                    self._lost_time = 0.0
            elif self.state == COASTING:
                # hard ceiling on any single coast leg
                if self.coast_time > config.COAST_TIMEOUT_S:
                    self.state = LOST
                    self.phase = LOST
                    self._lost_time = 0.0

            self.coast_mode = self.trust.update_coast(False, self.unc)

        elif self.state == LOST:
            self.phase = LOST
            self._lost_time += dt
            self.unc.coast(dt)
            if self._lost_time >= config.LOST_TIMEOUT_S:
                self.state = SEARCHING
                self.phase = SEARCHING
                self.search_angle = 0.0
                self.search_radius = 0.0
                self.coast_time = 0.0
                self.reacq_time = 0.0
            self.coast_mode = self.trust.update_coast(False, self.unc)

        elif self.state in (CANDIDATE, ACQUIRING):
            self._reset_tentative()
            self.state = SEARCHING
            self.phase = SEARCHING
            self.unc.coast(dt)
            self.coast_mode = self.trust.update_coast(False, self.unc)

        else:  # SEARCHING
            self.state = SEARCHING
            self.phase = SEARCHING
            # the blind search is itself unobserved: the estimate keeps getting
            # LESS certain every frame we sweep without a hit
            self.unc.coast(dt)
            self.coast_mode = self.trust.update_coast(False, self.unc)

        self.associated = None
        return self.state, self.est_az, self.est_el, self.confidence

    # ------------------------------------------------------------------
    def search_point(self, t, dt):
        speed_scale = 1.0
        if self.state == REACQUIRING:
            # each reacquisition LEVEL sweeps faster, so a beacon missed by the
            # tight early gate is hunted with a progressively wider/faster spiral
            speed_scale = config.REACQ_LEVEL_SEARCH_SPEED[
                max(0, min(config.REACQ_LEVELS - 1, self.reacq_level - 1))]
        rate = config.SEARCH_GROWTH_DEG_S * speed_scale
        self.search_angle += rate * dt * 2.2
        self.search_radius = min(config.SEARCH_MAX_RADIUS_DEG,
                                 self.search_radius + rate * dt * 0.5)
        if self.est_az is None or self.state in (SEARCHING, LOST):
            base_az, base_el = self.eph.predict_az_el(t)
        else:
            base_az, base_el = self.est_az, self.est_el
        return (base_az + self.search_radius * math.cos(self.search_angle),
                base_el + self.search_radius * math.sin(self.search_angle))
