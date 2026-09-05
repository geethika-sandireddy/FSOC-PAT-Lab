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

    def compute_setpoint(self, t, dt):
        """Return (pan_deg, tilt_deg) set-point for this frame."""
        st = self.tracker.state

        if st == "SEARCHING" and self.tracker.last_candidate_age < 0.35 \
                and self.tracker.last_candidate_az is not None:
            # a promising candidate exists: chase it while confirming
            self.pan = self.tracker.last_candidate_az
            self.tilt = self.tracker.last_candidate_el
        elif st in ("LOCKED", "COASTING") and self.tracker.est_az is not None:
            self.pan = self.tracker.est_az
            self.tilt = self.tracker.est_el
        else:
            # blind expanding-spiral search
            az, el = self.tracker.search_point(t, dt)
            self.pan = az
            self.tilt = el

        # slew-shaping happens in the gimbal; here we just clamp sanity
        self.pan = max(-30.0, min(30.0, self.pan))
        self.tilt = max(-30.0, min(30.0, self.tilt))
        self.gimbal.command_attitude(self.pan, self.tilt,
                                     *self._target_velocity(self.pan, self.tilt, dt))
        return self.pan, self.tilt