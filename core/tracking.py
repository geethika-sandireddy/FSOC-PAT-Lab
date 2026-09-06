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
from core.confidence import ConfidenceState
from core.uncertainty import UncertaintyEstimator
from core.trust import (AdaptiveTrustManager, MODE_BALANCED, MODE_VISION,
                        MODE_MODEL)


SEARCHING = "SEARCHING"
COASTING = "COASTING"
LOCKED = "LOCKED"
DEGRADED_LOCK = "DEGRADED_LOCK"
REACQUIRING = "REACQUIRING"

# fine-grained phases (subset of states; phases live inside SEARCHING and the
# tracked states).  These name the acquisition sub-steps visible in the GUI.
CANDIDATE = "CANDIDATE"
ACQUIRING = "ACQUIRING"


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
    def __init__(self, ephemeris_model, seed=None, video_mode=False,
                 gate_deg=config.ASSOC_GATE_DEG):
        self.eph = ephemeris_model
        # video_mode=True (Benchmark-2 MP4 bypass): an external video feeds the
        # coarse-pointing loop.  Its beacon has no known 15 Hz modulation clock,
        # so acquisition / lock-hold use appearance + temporal persistence
        # confidence instead of the modulation correlator.  The strict
        # modulation gate stays fully active in the synthetic scene mode.
        self.video_mode = video_mode
        self.gate_deg = gate_deg
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
        self.phase = SEARCHING
        self.conf = ConfidenceState()
        self.unc = UncertaintyEstimator()
        self.trust = AdaptiveTrustManager()
        self.dist_level_est = 0.0
        self.coast_mode = None

    # ------------------------------------------------------------------
    def _prior_gate_deg(self, t):
        if self.video_mode:
            return self.gate_deg * 1.2
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

        has_track = self.est_az is not None and self.state in (LOCKED, COASTING,
                                                        DEGRADED_LOCK,
                                                        REACQUIRING)

        if has_track:
            # prefer the true 15 Hz blinker: the fused mod boost in the score
            # loop gives a persistent area-modulated blob a strong edge over
            # static beacon-like decoys without ever wrong-restricting (all
            # candidates remain eligible, so no coast-loss when mod dips).
            # Video mode (Benchmark-2): the DetectionEngine's own persistent
            # track IDs are the identity - bind to the last associated ID so a
            # high-scoring noise blob cannot steal a lock once the beacon is
            # being tracked.
            best = None
            if self.video_mode and self.associated is not None:
                held_id = getattr(self.associated, "track_id", None)
                if held_id is not None:
                    # The DetectionEngine guarantees at most one candidate per
                    # track ID per frame, so the held ID already names the
                    # beacon.  Among candidates that share it (defensive), keep
                    # the one closest to the beacon's last-known position - a
                    # beacon cannot hop tens of pixels in one frame, so this is
                    # both the physically correct choice and fully independent
                    # of detection component ordering.
                    ref_az = self.last_candidate_az if self.last_candidate_az is not None \
                        else getattr(self.associated, "los_az", None)
                    ref_el = self.last_candidate_el if self.last_candidate_el is not None \
                        else getattr(self.associated, "los_el", None)
                    if ref_az is not None:
                        d_best = self.gate_deg
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
                for c in candidates:
                    d = math.hypot(c.los_az - self.est_az, c.los_el - self.est_el)
                    if d < self.gate_deg:
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
        self.phase = CANDIDATE if self._tent_frames == 0 else ACQUIRING
        self._update_conf(c, p_az, p_el)
        self.trust.update(conf=self.conf, mod_score=0.0, snr=c.snr,
                          dist_level=self.dist_level_est, visible=True)

        if self._tent_frames == 0:
            self._tent_az, self._tent_el = c.los_az, c.los_el
            self._tent_id = getattr(c, "track_id", None)
            self._tent_frames = 1
            self._tent_dj = 0.0
        else:
            d = math.hypot(c.los_az - self._tent_az, c.los_el - self._tent_el)
            # a fast target (e.g. SEVERE random walk) moves MORE than the
            # 14 px consistency gate per frame once the search re-engages;
            # an absolute restart then resets the tentative track forever and
            # re-acquisition dies.  Judge consistency against the object's own
            # recent jump (rolling) - slow spatial check for decoys is retained
            # by the base gate, the modulation cross-check still gates commit.
            tol_base = max(consistency, self._tent_dj * 6.0)
            if d < consistency:
                self._tent_frames += 1
            elif d < tol_base:
                self._tent_frames += 1       # fast-but-continuous: tolerate
            elif d > consistency * 3:
                # object jumped beyond what its own motion explains -> decoy
                # hop -> restart the tentative track
                self._tent_az, self._tent_el = c.los_az, c.los_el
                self._tent_id = getattr(c, "track_id", None)
                self._tent_frames = 1
                self.mod.reset()
            # else: minor jitter, keep counting spaces
            self._tent_dj = 0.75 * self._tent_dj + 0.25 * d
        self._tent_az, self._tent_el = c.los_az, c.los_el
        self.mod.push(c.u, c.v, c.peak, self._frame, area=c.area)
        c.mod_score = self.mod.corr()

        # steer the gimbal toward the tentative target so it stays in view
        self.est_az, self.est_el = c.los_az, c.los_el
        self._pv_u, self._pv_v = c.u, c.v

        # enough temporally-consistent frames AND enough modulation samples
        need_samples = int(config.MOD_CORREL_WIN * 0.8)
        if self._tent_frames >= config.ACQUIRE_CONFIRM_FRAMES:
            if not self.video_mode and len(self.mod.values) < need_samples:
                # keep gathering evidence (spatial consistency already proven)
                pass
            elif self.video_mode:
                # external-video beacon: appearance + spatial consistency over
                # ACQUIRE_CONFIRM_FRAMES is enough - no modulation clock to test
                self._commit(c.los_az, c.los_el, t)
                return self.state, self.est_az, self.est_el, max(0.5, c.ml_score)
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
        # (video mode has no modulation clock, so it relies on the persistent,
        # bright associated blob as the beacon identity).
        if not self.video_mode and c.mod_score < config.MOD_SUSPECT_FLOOR:
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
        self.phase = LOCKED
        # ---- Phase 2 confidence + trust (this is what the manager consumes) ----
        self._update_conf(c, p_az, p_el)
        mode = self.trust.update(conf=self.conf,
                                 mod_score=(0.0 if self.video_mode
                                            else self.mod.corr_area()),
                                 snr=c.snr, dist_level=self.dist_level_est,
                                 visible=True)
        self.coast_mode = mode
        self.unc.observe(snr=c.snr,
                         centroid_residual_px=self._centroid_jitter_px(c),
                         pred_residual_px=getattr(self, "_resid_deg_lead", 0.0)
                         * config.PIXELS_PER_DEG)
        # ---- DEGRADED_LOCK banding (design zones: 0.55-0.70 -> DEGRADED_LOCK
        # hold, >=0.70 -> full LOCKED; below 0.55 left untouched: the existing
        # suspect/coast machinery owns the transition out of the lock) ----
        if self.conf.overall >= config.DEGRADED_EXIT_CONF:
            self.state = LOCKED
        elif self.conf.overall >= config.DEGRADED_ENTER_CONF:
            self.state = DEGRADED_LOCK
        self.confidence = self.conf.overall
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
        return self.state, self.est_az, self.est_el, self.confidence

    def _commit(self, az, el, t):
        p_az, p_el = self.eph.predict_az_el(t)
        self.bias_az = az - p_az
        self.bias_el = el - p_el
        self.est_az = az
        self.est_el = el
        self.state = LOCKED
        self.phase = LOCKED
        self.acquisition_count += 1
        self.coast_time = 0.0
        self._tent_id = None

    # ------------------------------------------------------------------
    def _update_conf(self, c, p_az, p_el):
        """Fill the unified ConfidenceState for an observation (0-1 each).

        The disturbance condition fed to the TrustManager is *derived* from
        measurement quality (SNR, centroid flicker, model residual) -- the
        tracker never reads the true disturbance value (blind mode).
        """
        # "Is the motion-model prediction reliable?"  The model predicts THIS frame
        # from the ephemeris prior plus the learned bias (the belief state): if
        # the beacon arrives where tracked, the model is right.  Systematic
        # ephemeris offsets are learned away (bias), so this grades transient
        # disagreement - a hard manoeuvre, a corrupted prior, an unmodelled
        # disturbance - not static calibration error.  A small velocity lead
        # (same extrapolation the controller uses to coast) removes the moving
        # target's steady slew from the residual.
        if self.est_az is not None:
            _base_az, _base_el = self.est_az, self.est_el
        else:
            _base_az, _base_el = p_az + self.bias_az, p_el + self.bias_el
        _lead_dt = 1.0 / config.FPS
        resid_deg = math.hypot(c.los_az - (_base_az + self.vel_az * _lead_dt),
                               c.los_el - (_base_el + self.vel_el * _lead_dt))
        self._resid_deg_lead = resid_deg
        if self.video_mode:
            identity_src = c.ml_score
        else:
            # Identity = AI appearance (the trained, verified classifier) fused
            # with the continuous 15 Hz modulation evidence.  Both are needed:
            # appearance alone can be fooled by a luminous decoy, modulation
            # alone can flicker under noise (corr_area dips on uniform patches).
            identity_src = 0.6 * c.ml_score + 0.4 * self.mod.corr_area()
        self.conf.update(
            identity_src=identity_src,
            snr=c.snr,
            centroid_residual_px=self._centroid_jitter_px(c),
            pred_residual_deg=resid_deg,
            pred_scale_deg=max(0.08, self._prior_gate_deg(self.coast_time)),
            model_conf=(0.25 if self.video_mode else 1.0),
            dist_level=self.dist_level_est,
            point_err_deg=self.point_err_deg if hasattr(self, "point_err_deg") else 0.0,
            point_err_scale_deg=0.2)
        # derived disturbance condition for the trust manager (blind estimate)
        self.dist_level_est = max(
            0.0, min(1.0, 0.8 * (1.0 - self.conf.position)
                     + 0.2 * min(1.0, resid_deg / 0.4)))

    def _centroid_jitter_px(self, c):
        """EMA of per-frame centroid displacement in the camera pixel plane -
        a direct measurement of how stable the blob centroid is."""
        if self._pv_u is None:
            self._jit_px = 0.0
            return 0.0
        d_px = math.hypot(c.u - self._pv_u, c.v - self._pv_v)
        j = getattr(self, "_jit_px", d_px)
        self._jit_px = 0.6 * d_px + 0.4 * j
        return self._jit_px

    def _on_miss(self, t, dt):
        if self.state in (LOCKED, DEGRADED_LOCK, COASTING, REACQUIRING):
            self.coast_time += dt
            # prediction uncertainty grows while unobserved
            self.unc.coast(dt)
            if self.coast_time > config.COAST_TIMEOUT_S:
                self.state = SEARCHING
                self.phase = SEARCHING
                self.search_angle = 0.0
                self.search_radius = 0.0
            elif self.unc.reacquire_threshold_reached():
                # uncertainty beyond credibility -> stop following the model,
                # actively search (from the predicted position, expanding)
                self.state = REACQUIRING
                self.phase = REACQUIRING
            else:
                # predictive coast: extrapolate the estimate with the smoothed
                # velocity so the gimbal keeps riding the last known motion
                if self.est_az is not None:
                    self.est_az += self.vel_az * dt
                    self.est_el += self.vel_el * dt
                self.state = COASTING
                self.phase = COASTING
            self.coast_mode = self.trust.update_coast(False, self.unc)
        else:
            self.phase = SEARCHING
            self.coast_mode = self.trust.update_coast(False, self.unc)
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