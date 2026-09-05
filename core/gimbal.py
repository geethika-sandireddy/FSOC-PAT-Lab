"""
core/gimbal.py
--------------
Block C - the virtual pan-tilt gimbal that carries the camera.

Physics modelled (all of it -- nothing teleports):
  * acceleration-limited slew velocity (inertia),
  * a fixed measurement->command latency buffer (processing + actuator lag),
  * rate-slew caps,
  * commanded vs *realized* attitude: platform vibration / jolts perturb
    the realized attitude; an inner stabilization loop rejects a fraction
    of it (real gimbal gyro-stabilization), the residual is physical
    boresight error.
  * PID position servo with INTEGRAL ACTION + anti-windup, eliminating
    steady-state error that the pure PD loop accumulated under constant
    disturbance (vibration / platform tilt / bias).

The encoder pose (realized attitude) is what the detector + tracker use to
convert measurements into world coordinates - exactly what a real gimbal's
encoders do.
"""

import math
from collections import deque

import numpy as np

import config
from core import geometry


class Gimbal:
    def __init__(self, start_pan=0.0, start_tilt=0.0):
        self.pan_cmd = 0.0
        self.tilt_cmd = 0.0
        self.pan = 0.0
        self.tilt = 0.0
        self.v_pan = 0.0
        self.v_tilt = 0.0
        self.i_pan = 0.0
        self.i_tilt = 0.0
        self._latency = deque()
        self._n = 0

        self.pan = start_pan
        self.tilt = start_tilt
        self.pan_cmd = start_pan
        self.tilt_cmd = start_tilt

        self.disturb_rng = None

    def set_disturb_rng(self, rng):
        self.disturb_rng = rng

    # ---------------- Command interface ----------------
    def command_attitude(self, pan_deg, tilt_deg):
        self._latency.append((self._n, float(pan_deg), float(tilt_deg)))
        self._n += 1
        if self._latency and self._latency[0][0] <= self._n - config.GIMBAL_LATENCY_FRAMES:
            _, self.pan_cmd, self.tilt_cmd = self._latency.popleft()

    # ---------------- Dynamics ----------------
    def step(self, dt, disturbance):
        vel_p, pan, i_pan = self._follow(
            self.pan_cmd, self.pan, self.v_pan, self.i_pan,
            config.GIMBAL_MAX_SLEW_DEG_S,
            config.GIMBAL_ACCEL_DEG_S2, dt)
        self.pan, self.v_pan, self.i_pan = pan, vel_p, i_pan

        vel_t, tilt, i_tilt = self._follow(
            self.tilt_cmd, self.tilt, self.v_tilt, self.i_tilt,
            config.GIMBAL_MAX_TILT_DEG_S,
            config.GIMBAL_ACCEL_DEG_S2, dt)
        self.tilt, self.v_tilt, self.i_tilt = tilt, vel_t, i_tilt

        d_pan, d_tilt = disturbance.platform_disturbance(dt)
        reject = config.GIMBAL_STABIZATION_REJECT
        self.pan += d_pan * (1.0 - reject)
        self.tilt += d_tilt * (1.0 - reject)

    @staticmethod
    def _follow(cmd, now, vel, integ, velmax, accmax, dt):
        """Critically-damped PID position servo with slew/accel limits
        and anti-windup integral clamping.

            a = kp*(cmd-now) + ki*integ - kd*vel    (velocity damping)

        Anti-windup (classic back-calculation): clamp the integrated error
        to INT_MAX so the integral term never grows unbounded when the
        actuator saturates (slew / accel caps).  This eliminates the
        classic integral windup that causes long settling tails after a
        large step command.
        """
        kp = config.GIMBAL_SERVO_KP
        ki = config.GIMBAL_SERVO_KI
        kd = config.GIMBAL_SERVO_KD
        imax = config.GIMBAL_SERVO_INT_MAX

        err = cmd - now

        integ = integ + err * dt
        if integ > imax:
            integ = imax
        elif integ < -imax:
            integ = -imax

        a = kp * err + ki * integ - kd * vel
        a = max(-accmax, min(accmax, a))

        v = vel + a * dt
        if v > velmax:
            v = velmax
            if integ > 0:
                integ = max(0.0, integ - 2.0 * err * dt)
        elif v < -velmax:
            v = -velmax
            if integ < 0:
                integ = min(0.0, integ - 2.0 * err * dt)

        return v, now + v * dt, integ

    # ---------------- Helpers ----------------
    def basis(self):
        return geometry.gimbal_frame(self.pan, self.tilt)

    def commanded_basis(self):
        return geometry.gimbal_frame(self.pan_cmd, self.tilt_cmd)

    def attitude(self):
        return self.pan, self.tilt

    def reacquire_velocities(self):
        return self.v_pan, self.v_tilt
