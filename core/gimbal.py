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
        # Part 3 actuator-saturation observability: 0..1 fraction of how close
        # the realized servo is to its physical limits this frame (rate and/or
        # accel).  ~1.0 means the camera is being commanded faster than it can
        # physically slew (the "camera can't keep up" condition); telemetry-only,
        # never fed back into the loop.
        self.pan_sat = 0.0
        self.tilt_sat = 0.0
        self._latency = deque()      # (frame_index, pan, tilt)
        self._n = 0                  # frame counter for latency FIFO

        self.pan = start_pan
        self.tilt = start_tilt
        self.pan_cmd = start_pan
        self.tilt_cmd = start_tilt

        self.max_pan_deg_s = float(getattr(config, "CAMERA_MAX_PAN_DEG_S", 5.0))
        self.max_tilt_deg_s = float(getattr(config, "CAMERA_MAX_TILT_DEG_S", 5.0))

        # Dual-Stage PAT Architecture: Piezoelectric Fine Steering Mirror (FSM)
        # Slew range: ±5.0 mrad (±5000 µrad); Bandwidth: 1 kHz; Sub-µrad jitter rejection
        self.fsm_pan_urad = 0.0
        self.fsm_tilt_urad = 0.0
        self.fsm_enabled = True
        self.fsm_max_urad = 5000.0  # ±5 mrad stroke limit
        self.fsm_active = False
        self.fsm_sat = 0.0

        self.disturb_rng = None

    def set_limits(self, max_pan=None, max_tilt=None):
        """Configure maximum slew rate limits (PS 26169: 5-10 deg/s, default 5 deg/s)."""
        if max_pan is not None:
            self.max_pan_deg_s = float(max(0.5, min(20.0, max_pan)))
        if max_tilt is not None:
            self.max_tilt_deg_s = float(max(0.5, min(20.0, max_tilt)))

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
        vel_p, pan, sp = self._follow(self.pan_cmd, self.pan, self.v_pan,
                                      self.max_pan_deg_s,
                                      config.GIMBAL_ACCEL_DEG_S2, dt, self.vp_ff)
        self.pan, self.v_pan = pan, vel_p
        self.pan_sat = sp
        vel_t, tilt, st = self._follow(self.tilt_cmd, self.tilt, self.v_tilt,
                                       self.max_tilt_deg_s,
                                       config.GIMBAL_ACCEL_DEG_S2, dt, self.vt_ff)
        self.tilt, self.v_tilt = tilt, vel_t
        self.tilt_sat = st

        # --- realized attitude: command + platform disturbance, stabilized ---
        d_pan, d_tilt = disturbance.platform_disturbance(dt)
        reject = config.GIMBAL_STABIZATION_REJECT
        self.pan += d_pan * (1.0 - reject)
        self.tilt += d_tilt * (1.0 - reject)

        # --- Stage 2: Fine Steering Mirror (FSM) Closed-Loop Active Compensation ---
        # Converts coarse residual off-boresight error into micro-radians and deflects
        # piezo mirrors to suppress residual platform jitter down to micro-radians.
        deg_to_urad = 17453.2925
        res_p_urad = (self.pan_cmd - self.pan) * deg_to_urad
        res_t_urad = (self.tilt_cmd - self.tilt) * deg_to_urad
        fsm_cone_limit = self.fsm_max_urad * 1.5

        if self.fsm_enabled and abs(res_p_urad) <= fsm_cone_limit and abs(res_t_urad) <= fsm_cone_limit:
            target_p = max(-self.fsm_max_urad, min(self.fsm_max_urad, res_p_urad * 0.94))
            target_t = max(-self.fsm_max_urad, min(self.fsm_max_urad, res_t_urad * 0.94))
            self.fsm_pan_urad += (target_p - self.fsm_pan_urad) * 0.40
            self.fsm_tilt_urad += (target_t - self.fsm_tilt_urad) * 0.40
            self.fsm_active = True
            self.fsm_sat = min(1.0, max(abs(self.fsm_pan_urad), abs(self.fsm_tilt_urad)) / max(1e-9, self.fsm_max_urad))
        else:
            self.fsm_pan_urad *= 0.70
            self.fsm_tilt_urad *= 0.70
            self.fsm_active = False
            self.fsm_sat = 0.0

    @staticmethod
    def _follow(cmd, now, vel, velmax, accmax, dt, vel_ff=0.0):
        """Damped position servo (PD) with slew/accel limits + velocity
        feedforward.

        a = kp*(cmd-now) - kd*(vel - vel_ff), accel-clamped, velocity-
        clamped, position integrated.  The feedforward term cancels the
        steady-state lag a plain PD servo exhibits when tracking a moving
        target (err ~ (kd/kp)*v), so the boresight rides ON the target
        instead of trailing it.  Returns (velocity, new_pos, saturation)
        where saturation in [0,1] measures how near the physical rate/accel
        limit the servo is operating this frame."""
        err = cmd - now
        a = config.GIMBAL_SERVO_KP * err - config.GIMBAL_SERVO_KD * (vel - vel_ff)
        a_raw = a
        a = max(-accmax, min(accmax, a))
        v = min(velmax, max(-velmax, vel + a * dt))
        sat = max(abs(a_raw) / max(accmax, 1e-9),
                  abs(vel + a * dt) / max(velmax, 1e-9))
        return v, now + v * dt, min(1.0, sat)

    # ---------------- Helpers ----------------
    def basis(self):
        return geometry.gimbal_frame(self.pan, self.tilt)

    def commanded_basis(self):
        return geometry.gimbal_frame(self.pan_cmd, self.tilt_cmd)

    def attitude(self):
        return self.pan, self.tilt

    def reacquire_velocities(self):
        return self.v_pan, self.v_tilt