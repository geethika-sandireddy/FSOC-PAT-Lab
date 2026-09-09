"""
core/orbital.py
---------------
Relative line-of-sight trajectory of Satellite B (the beacon) as seen from
Satellite A, expressed directly in the gimbal angular frame.

HONESTY NOTE (report-relevant)
------------------------------
This is NOT a TLE/SGP4 propagator.  Real ISRO ephemeris is not public at
this fidelity, and claiming otherwise would be dishonest.  What the model
does capture - in the exact degrees/arc-seconds regime this PS is about -
is the *shape* of the real problem:

  * along-track drift (different orbital angular rates, ~ uniform / linear
    azimuth drift superposed on a sinusoid),
  * cross-track separation (different orbital plane inclinations, low
    frequency elevation oscillation),
  * a slowly-varying range profile.

The trajectory is deliberately exactly known FOR THE EPHEMERIS MACHINE:
the *prior* the system is given is truth + a slowly growing bias.  The
vision pipeline never sees the truth directly - it only sees rendered
sensor pixels (see core/sensor.py) - so the uncertainty that PAT systems
face is reproduced faithfully.

If you later obtain public TLE data you can swap `relative_los_az_el(t)`
for a real SGP4 call; nothing else in the pipeline changes.
"""

import math
import random

import config
from core.motion import MOTION_TYPES


class RelativeOrbitModel:
    def __init__(self, az_amp=1.4, el_amp=0.9, speed=1.15, seed=None,
                 motion_type=None, initial="RANDOM", user_pos=None):
        """initial: "RANDOM" (PS default) -> beacon appears anywhere in the
        scene; "CENTER" -> beacon starts at the gimbal boresight (0,0);
        (az, el) tuple or user_pos -> user-defined initial coordinates."""
        rnd = random.Random(seed)
        self.az_amp = az_amp
        self.el_amp = el_amp
        self.speed = speed
        self.initial = initial
        self._user_pos = None

        if user_pos is not None and isinstance(user_pos, (tuple, list)) and len(user_pos) >= 2:
            self._user_pos = (float(user_pos[0]), float(user_pos[1]))
        elif isinstance(initial, (tuple, list)) and len(initial) >= 2:
            self._user_pos = (float(initial[0]), float(initial[1]))
        elif initial == "CENTER":
            self._user_pos = (0.0, 0.0)

        # PS-mandated selectable motion type (straight_line, circular, figure_eight, random)
        self._motion_type = motion_type
        if motion_type is not None and motion_type in MOTION_TYPES:
            factory = MOTION_TYPES[motion_type]
            if motion_type == "random":
                self._motion_fn = factory(speed=speed, seed=seed,
                                          amp_az=az_amp, amp_el=el_amp)
            else:
                self._motion_fn = None  # use direct call
            self._is_custom = True
        else:
            self._is_custom = False
            self._motion_fn = None
        # Parameterised relative-motion model (see module docstring).
        if self._user_pos is not None:
            self.az_omega = rnd.uniform(0.090, 0.120) * speed      # rad/s
            self.el_omega = rnd.uniform(0.045, 0.070) * speed      # rad/s
            self.az_phase = 0.0
            self.el_phase = 0.0
        else:
            self.az_omega = rnd.uniform(0.090, 0.120) * speed      # rad/s
            self.el_omega = rnd.uniform(0.045, 0.070) * speed      # rad/s
            self.az_phase = rnd.uniform(-0.4, 0.4)
            self.el_phase = rnd.uniform(0.0, 6.283)
        self.range_base = 1000.0                                # km
        self.range_var = rnd.uniform(180.0, 320.0)
        self.range_omega = rnd.uniform(0.03, 0.06)

        self._offset_az = 0.0
        self._offset_el = 0.0
        if self._user_pos is not None:
            r0_az, r0_el = self._compute_raw(0.0)
            self._offset_az = self._user_pos[0] - r0_az
            self._offset_el = self._user_pos[1] - r0_el

    def _compute_raw(self, t):
        if self._is_custom:
            if self._motion_fn is not None:
                return self._motion_fn(t)
            fn = MOTION_TYPES[self._motion_type]
            return fn(t, speed=self.speed, amp_az=self.az_amp,
                      amp_el=self.el_amp)
        az = self.az_amp * math.sin(self.az_omega * t + self.az_phase)
        el = self.el_amp * math.sin(self.el_omega * t + self.el_phase)
        return az, el

    def relative_los_az_el(self, t):
        az, el = self._compute_raw(t)
        return az + self._offset_az, el + self._offset_el

    def range_km(self, t):
        return self.range_base + self.range_var * math.sin(self.range_omega * t)


class EphemerisModel:
    """Wraps a RelativeOrbitModel and produces the coarse prediction the
    ground segment would hand Satellite A.  The prediction carries a
    fixed-direction bias whose MAGNITUDE grows with elapsed sim time,
    capped - the real effect of unmodeled drag on a long-running
    propagator."""

    def __init__(self, orbit, seed=None, mismatch_mode="matched"):
        rnd = random.Random(seed)
        self.orbit = orbit
        self.mismatch_mode = str(mismatch_mode).lower()
        angle = rnd.uniform(0.0, 2.0 * math.pi)
        self._dir = (math.cos(angle), math.sin(angle))
        self._mismatch_seed = seed or 42

    def _bias_deg(self, t):
        start = config.EPHEMERIS_START_BIAS_DEG
        rate = config.EPHEMERIS_GROWTH_DEG_PER_SEC
        cap = config.EPHEMERIS_MAX_BIAS_DEG
        mag = min(start + rate * t, cap)
        return (self._dir[0] * mag, self._dir[1] * mag)

    def predict_az_el(self, t):
        az, el = self.orbit.relative_los_az_el(t)
        # Deliberate model mismatch injection (PS Section 7 validation)
        if self.mismatch_mode == "small":
            az += 0.04 * math.sin(0.5 * t)
            el += 0.03 * math.cos(0.4 * t)
        elif self.mismatch_mode == "moderate":
            az += 0.08 * math.sin(0.8 * t)
            el += 0.06 * math.cos(0.7 * t)
        elif self.mismatch_mode == "large":
            az += 0.14 * math.sin(1.2 * t)
            el += 0.10 * math.cos(1.0 * t)

        b_az, b_el = self._bias_deg(t)
        return az + b_az, el + b_el

    def bias_deg(self, t):
        return self._bias_deg(t)