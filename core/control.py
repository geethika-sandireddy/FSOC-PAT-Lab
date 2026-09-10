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
        """Simple reachability test (keeps for future RAR integration).

        Returns a tuple (feasible_pan, feasible_tilt, reachable) where reachable
        is True if the target setpoint is reachable within one frame's max slew
        given the current gimbal velocities and configured GIMBAL_MAX_* limits.
        The controller does not override actuator physics; this merely reports
        feasibility so higher-level logic can choose an intermediate setpoint.
        """
        gm = self.gimbal
        frame_dt = dt or (1.0 / config.FPS)
        max_pan = getattr(gm, "max_pan_deg_s", config.GIMBAL_MAX_SLEW_DEG_S)
        max_tilt = getattr(gm, "max_tilt_deg_s", config.GIMBAL_MAX_TILT_DEG_S)

        # maximum delta achievable in one frame at max slew
        max_dp = max_pan * frame_dt
        max_dt = max_tilt * frame_dt

        # signed angular deltas
        dpan = self._short_ang_diff(target_pan, gm.pan)
        dtilt = self._short_ang_diff(target_tilt, gm.tilt)

        feasible_pan = gm.pan + max(-max_dp, min(max_dp, dpan))
        feasible_tilt = gm.tilt + max(-max_dt, min(max_dt, dtilt))
        reachable = (abs(dpan) <= max_dp + 1e-9) and (abs(dtilt) <= max_dt + 1e-9)
        return feasible_pan, feasible_tilt, reachable

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
            # Minimal predictive lead: command the short-horizon predicted LOS
            pred_az, pred_el, horizon = self._predict_los(self.tracker.est_az, self.tracker.est_el, dt)

            # Respect reachability: prefer commanded predicted LOS only if the
            # gimbal can physically get there within one frame's max slew. If
            # not reachable, command a feasible intermediate setpoint toward the
            # predicted LOS that respects the gimbal's slew limits. When the
            # predicted LOS is very close to the mechanical FOV limit prefer a
            # slightly more conservative inward bias to keep the beacon farther
            # inside the FOV when possible.
            feasible_pan, feasible_tilt, reachable = self._rar_reachability_check(pred_az, pred_el, dt)
            if reachable:
                self.pan = pred_az
                self.tilt = pred_el
            else:
                # Use the feasible step the reachability helper computed. This
                # is rate-limited and physically achievable by the gimbal.
                self.pan = feasible_pan
                self.tilt = feasible_tilt
                # nudge slightly toward boresight if the predicted LOS is near
                # the sanity clamp boundary so we keep the beacon more inside
                # the FOV when approaching a hard limit.
                clamp_deg = 30.0
                inward_thresh = 0.9 * clamp_deg
                if abs(pred_az) > inward_thresh:
                    # move a small fraction toward center (0.98 * feasible)
                    self.pan = 0.98 * self.pan
                if abs(pred_el) > inward_thresh:
                    self.tilt = 0.98 * self.tilt
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
