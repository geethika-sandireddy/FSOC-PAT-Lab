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
        # Commanded attitude (what the controller asks for).
        self.pan_cmd = 0.0
        self.tilt_cmd = 0.0
        self.vp_ff = 0.0             # commanded velocity feedforward (deg/s)
        self.vt_ff = 0.0
        # Realized attitude (what the sensor actually points at).
        self.pan = 0.0
        self.tilt = 0.0
        self.v_pan = 0.0
        self.v_tilt = 0.0
        self._latency = deque()      # (frame_index, pan, tilt)
        self._n = 0                  # frame counter for latency FIFO

        self.pan = start_pan
        self.tilt = start_tilt
        self.pan_cmd = start_pan
        self.tilt_cmd = start_tilt

        self.disturb_rng = None

    def set_disturb_rng(self, rng):
        self.disturb_rng = rng

    # ---------------- Command interface ----------------
    def command_attitude(self, pan_deg, tilt_deg, vel_ff_pan=0.0, vel_ff_tilt=0.0):
        """Queue a pointing command at the current frame index.  It takes
        effect GIMBAL_LATENCY_FRAMES frames later (FIFO, one command per
        frame - models pipeline + actuator response delay).

        vel_ff_pan/tilt: target angular-velocity feedforward (deg/s).  A PD
        position servo tracks a constant-velocity target with steady-state
        lag err = (KD/KP)*v; the feedforward term cancels that lag so the
        boresight stays on target instead of trailing it.
        """
        self._latency.append((self._n, float(pan_deg), float(tilt_deg),
                              float(vel_ff_pan), float(vel_ff_tilt)))
        self._n += 1
        if self._latency and self._latency[0][0] <= self._n - config.GIMBAL_LATENCY_FRAMES:
            _, self.pan_cmd, self.tilt_cmd, self.vp_ff, self.vt_ff = self._latency.popleft()

    # ---------------- Dynamics ----------------
    def step(self, dt, disturbance):
        """Advance the realized attitude one frame.

        The realized attitude is a *second-order follower* of the active
        setpoint (the most recently applied queued command): acceleration-
        limited slew velocity.  Platform vibration / jolts from the
        disturbance engine perturb the realized attitude; the inner
        stabilization loop rejects a configurable fraction.
        """
        # --- realized attitude slews toward the active setpoint ---
        vel_p, pan = self._follow(self.pan_cmd, self.pan, self.v_pan,
                                  config.GIMBAL_MAX_SLEW_DEG_S,
                                  config.GIMBAL_ACCEL_DEG_S2, dt, self.vp_ff)
        self.pan, self.v_pan = pan, vel_p
        vel_t, tilt = self._follow(self.tilt_cmd, self.tilt, self.v_tilt,
                                   config.GIMBAL_MAX_TILT_DEG_S,
                                   config.GIMBAL_ACCEL_DEG_S2, dt, self.vt_ff)
        self.tilt, self.v_tilt = tilt, vel_t

        # --- realized attitude: command + platform disturbance, stabilized ---
        d_pan, d_tilt = disturbance.platform_disturbance(dt)
        reject = config.GIMBAL_STABIZATION_REJECT
        self.pan += d_pan * (1.0 - reject)
        self.tilt += d_tilt * (1.0 - reject)

    @staticmethod
    def _follow(cmd, now, vel, velmax, accmax, dt, vel_ff=0.0):
        """Damped position servo (PD) with slew/accel limits + velocity
        feedforward.

        a = kp*(cmd-now) - kd*(vel - vel_ff), accel-clamped, velocity-
        clamped, position integrated.  The feedforward term cancels the
        steady-state lag a plain PD servo exhibits when tracking a moving
        target (err ~ (kd/kp)*v), so the boresight rides ON the target
        instead of trailing it.
        """
        err = cmd - now
        a = config.GIMBAL_SERVO_KP * err - config.GIMBAL_SERVO_KD * (vel - vel_ff)
        a = max(-accmax, min(accmax, a))
        v = min(velmax, max(-velmax, vel + a * dt))
        return v, now + v * dt

    # ---------------- Helpers ----------------
    def basis(self):
        return geometry.gimbal_frame(self.pan, self.tilt)

    def commanded_basis(self):
        return geometry.gimbal_frame(self.pan_cmd, self.tilt_cmd)

    def attitude(self):
        return self.pan, self.tilt

    def reacquire_velocities(self):
        return self.v_pan, self.v_tilt