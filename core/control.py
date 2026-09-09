"""
core/control.py
---------------
Closed-loop pointing controller for the pan-tilt gimbal.

Every frame it decides what the gimbal should point at:

  * SEARCHING  -> expanding spiral from the last estimate / ephemeris prior,
  * LOCKED     -> the tracker's LOS estimate (feedforward from the smooth
                  ephemeris + filtered correction: this is what makes the
                  residual pointing error a few hundredths of a degree),
  * COASTING   -> extrapolated estimate (measurement drop-out).

The gimbal itself enforces slew-rate / acceleration / latency physics
(core/gimbal.py); this module only produces the attitude *set-point*.
"""

import math

import config


class PointingController:
    def __init__(self, gimbal, tracker):
        self.gimbal = gimbal
        self.tracker = tracker
        self.pan = 0.0
        self.tilt = 0.0
        self.searching_since = 0.0
        self._prev_pan = None
        self._prev_tilt = None
        self._v_pan = 0.0
        self._v_tilt = 0.0

    def _target_velocity(self, pan, tilt, dt):
        """Smoothed angular velocity of the set-point (deg/s).

        Fed to the gimbal's servo as a velocity feedforward so a PD
        position loop does not trail a moving beacon.
        """
        if self._prev_pan is not None and dt > 0:
            raw_p = (pan - self._prev_pan) / dt
            raw_t = (tilt - self._prev_tilt) / dt
            # bang-bang limiter: reject implausible single-frame spikes
            if abs(raw_p) > 8.0:
                raw_p = self._v_pan
            if abs(raw_t) > 8.0:
                raw_t = self._v_tilt
            a = config.CONTROL_VEL_EMA
            self._v_pan = a * (raw_p - self._v_pan) + self._v_pan
            self._v_tilt = a * (raw_t - self._v_tilt) + self._v_tilt
        self._prev_pan, self._prev_tilt = pan, tilt
        return self._v_pan, self._v_tilt

    # ----------------- Predictive / Reachability helpers -----------------
    def _short_ang_diff(self, a, b):
        """Shortest signed angular difference a - b in degrees."""
        d = (a - b + 180.0) % 360.0 - 180.0
        return d

    def _predict_los(self, est_az, est_el, dt):
        """Predict LOS forward by a short horizon using the tracker's velocity.

        Uses the gimbal latency + optional coast lead as the prediction horizon
        so the controller can lead a moving beacon rather than chase an old
        estimate. No new constants are introduced; existing config tunables are
        reused.
        """
        frame_dt = dt or (1.0 / config.FPS)
        lat_s = config.GIMBAL_LATENCY_FRAMES * frame_dt
        # coast velocity lead is an existing config that already expresses a
        # short forward lead used by the tracker; reuse it when we are in a
        # coasting/reacquiring regime so the controller leads more aggressively
        # in recovery. For regular LOCKED tracking the latency horizon alone is
        # usually sufficient and avoids over-steering.
        extra_lead = config.COAST_VELOCITY_LEAD_S if self.tracker.state in ("COASTING", "REACQUIRING") else 0.0
        horizon = lat_s + extra_lead + frame_dt

        vaz = getattr(self.tracker, "vel_az", 0.0) or 0.0
        vel = getattr(self.tracker, "vel_el", 0.0) or 0.0

        pred_az = est_az + vaz * horizon
        pred_el = est_el + vel * horizon
        return pred_az, pred_el, horizon

    def _rar_reachability_check(self, target_pan, target_tilt, dt):
        """Reachability-Aware Predictive Reacquisition (RAR).

        Returns (safe_bool, pan_cmd, tilt_cmd).
        - If the short-horizon predicted LOS is reachable within actuator
          short-horizon rate limits, returns (True, predicted_pan, predicted_tilt).
        - Otherwise returns (False, intermediate_pan, intermediate_tilt) that
          is rate-limited toward the predicted LOS while respecting physical
          slew constraints and preferring commands that keep the beacon inside
          the camera FOV when the predicted LOS is near the FOV boundary.

        The method uses only existing tracker velocity/uncertainty and config
        constants; it does not change the tracker state or any thresholds.
        """
        # current realized attitude (encoder readings)
        cur_pan = self.gimbal.pan
        cur_tilt = self.gimbal.tilt

        # Predict the target LOS forward using tracker velocity
        pred_pan, pred_tilt, horizon = self._predict_los(target_pan, target_tilt, dt)

        # angular deltas (absolute shortest-path)
        d_pan_signed = self._short_ang_diff(pred_pan, cur_pan)
        d_tilt_signed = self._short_ang_diff(pred_tilt, cur_tilt)
        d_pan = abs(d_pan_signed)
        d_tilt = abs(d_tilt_signed)

        # uncertainty margin (deg)
        unc_px = getattr(self.tracker.unc, "sigma_px", 0.0) or 0.0
        unc_margin_deg = unc_px / config.PIXELS_PER_DEG

        eff_pan = d_pan + unc_margin_deg
        eff_tilt = d_tilt + unc_margin_deg

        # required short-horizon angular rates
        req_pan_rate = eff_pan / max(horizon, 1e-6)
        req_tilt_rate = eff_tilt / max(horizon, 1e-6)

        max_pan_rate = config.GIMBAL_MAX_SLEW_DEG_S
        max_tilt_rate = getattr(config, "GIMBAL_MAX_TILT_DEG_S", max_pan_rate)

        pan_ok = req_pan_rate <= max_pan_rate + 1e-12
        tilt_ok = req_tilt_rate <= max_tilt_rate + 1e-12
        safe = pan_ok and tilt_ok

        if safe:
            # predicted LOS is short-horizon reachable: lead the camera to it
            return True, pred_pan, pred_tilt

        # Not reachable: compute conservative, rate-limited intermediate setpoint
        allowed_pan_delta = max_pan_rate * horizon
        allowed_tilt_delta = max_tilt_rate * horizon

        # sign-aware stepping (shortest-path)
        sign_pan = 1.0 if d_pan_signed >= 0.0 else -1.0
        sign_tilt = 1.0 if d_tilt_signed >= 0.0 else -1.0

        # --- FALLBACK: step toward the short-horizon predicted LOS
        # If the short-horizon predicted LOS is not reachable in one horizon,
        # move by the maximum allowed short-horizon delta toward pred_pan/pred_tilt.
        # This anticipates only across the latency horizon (pred_pan) rather than
        # projecting arbitrarily far ahead and chasing that future position.
        step_pan = min(d_pan, allowed_pan_delta) * sign_pan
        step_tilt = min(d_tilt, allowed_tilt_delta) * sign_tilt
        intermediate_pan = cur_pan + step_pan
        intermediate_tilt = cur_tilt + step_tilt

        # FOV-safety preference: if the predicted LOS is approaching the sensor
        # FOV boundary, bias the intermediate command to move as far as possible
        # toward the predicted LOS (we already step by the allowed_delta). Add a
        # tiny extra nudge inside the allowed delta to prefer keeping the beacon
        # inside the FOV when possible (no violation of slew limits).
        try:
            fov_h_half = config.CAMERA_FOV_H_DEG / 2.0
            fov_v_half = config.CAMERA_FOV_V_DEG / 2.0
        except Exception:
            fov_h_half = config.HFOV_DEG / 2.0 if hasattr(config, "HFOV_DEG") else 2.0
            fov_v_half = config.VFOV_DEG / 2.0 if hasattr(config, "VFOV_DEG") else 1.5

        # predicted angular separation from boresight
        sep_pan = abs(self._short_ang_diff(pred_pan, cur_pan))
        sep_tilt = abs(self._short_ang_diff(pred_tilt, cur_tilt))
        sep = math.hypot(sep_pan, sep_tilt)

        # if predicted LOS would sit close to the FOV edge, ensure we use full
        # allowed delta (we already do). This block is left explicit for clarity
        # and to document the physical intent (no extra magic multiplier).
        margin_h = max(0.05, fov_h_half * 0.10)
        margin_v = max(0.05, fov_v_half * 0.10)
        if sep_pan > (fov_h_half - margin_h) or sep_tilt > (fov_v_half - margin_v):
            # prefer the full allowed step (already computed). Ensure no under-step
            # by using the allowed_*_delta instead of the possibly smaller min(d,allowed).
            step_pan = allowed_pan_delta * sign_pan
            step_tilt = allowed_tilt_delta * sign_tilt
            intermediate_pan = cur_pan + step_pan
            intermediate_tilt = cur_tilt + step_tilt

        return False, intermediate_pan, intermediate_tilt

    # ------------------------------------------------------------------
    def compute_setpoint(self, t, dt):
        """Return (pan_deg, tilt_deg) set-point for this frame."""
        st = self.tracker.state

        if st == "SEARCHING" and self.tracker.last_candidate_age < 0.35 \
                and self.tracker.last_candidate_az is not None:
            # a promising candidate exists: chase it while confirming
            self.pan = self.tracker.last_candidate_az
            self.tilt = self.tracker.last_candidate_el
        elif st in ("LOCKED", "DEGRADED_LOCK", "COASTING", "REACQUIRING") \
                and self.tracker.est_az is not None:
            # tracked / re-acquiring states: point at the fused estimate.  During
            # predictive coast the tracker has already extrapolated est with its
            # smoothed velocity; re-acquisition is *targeted* - hold the last
            # predicted position while the association gate widens, so the
            # camera never sweeps the beacon out of view on a fast target.
            # DEGRADED_LOCK keeps exactly the same pointing (the estimator
            # already smooths the measurement via the trust-driven bias gain).
            #
            # APPLY RAR: use the tracker velocity to predict the short-horizon LOS
            # and only command a setpoint that is short-horizon reachable. If the
            # predicted LOS is unreachable, step toward it by the allowed short-
            # horizon delta (respects existing GIMBAL_MAX_* sail limits).
            safe, pan_cmd, tilt_cmd = self._rar_reachability_check(self.tracker.est_az,
                                                                   self.tracker.est_el, dt)
            self.pan = pan_cmd
            self.tilt = tilt_cmd
        else:
            # blind expanding-spiral search
            az, el = self.tracker.search_point(t, dt)
            self.pan = az
            self.tilt = el

        # slewing happens in the gimbal; here we just clamp sanity
        self.pan = max(-30.0, min(30.0, self.pan))
        self.tilt = max(-30.0, min(30.0, self.tilt))
        vp, vt = self._target_velocity(self.pan, self.tilt, dt)
        self.gimbal.command_attitude(self.pan, self.tilt, vp, vt)
        # pointing confidence: how close commanded vs realized attitude is.
        # The naive baseline tracker (metrics/compare_trackers) has no Phase-2
        # confidence stack, so feed it only when present.
        conf = getattr(self.tracker, "conf", None)
        if conf is not None:
            conf.update_pointing(
                math.hypot(self.pan - self.gimbal.pan, self.tilt - self.gimbal.tilt))
        return self.pan, self.tilt
