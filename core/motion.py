"""
core/motion.py
--------------
Selectable target motion types required by the PS 26169:
   1. Straight Line    (default / mandatory)
  2. Circular         (mandatory)
  3. Figure of 8      (mandatory)
  4. Random           (mandatory)
  5. Spiral           (optional, PS-listed)
  6. Sinusoidal       (optional, PS-listed)
  7. Lissajous        (default orbital drift)
"""

import math
import random


def _triangle(t, period, amp):
    """Constant-velocity travel between -amp and +amp that reflects at the
    endpoints - i.e. an actual straight line back and forth, not a curve."""
    if period <= 0:
        return 0.0
    phase = (t % period) / period
    tri = 1.0 - abs(2.0 * phase - 1.0)   # 0 -> 1 -> 0, linear segments
    return -amp + 2.0 * amp * tri


def straight_line(t, speed=1.15, amp_az=1.4, amp_el=0.9):
    """Genuine straight-line motion (PS mandatory type #1): constant angular
    velocity along a line, reflecting off the travel bounds. Previously this
    used sin(), which is a curve, not a straight line - mislabeled."""
    v_az = max(speed * 0.055, 1e-6)
    v_el = max(speed * 0.035, 1e-6)
    period_az = (2.0 * amp_az) / v_az
    period_el = (2.0 * amp_el) / v_el
    az = _triangle(t, period_az, amp_az)
    el = _triangle(t, period_el, amp_el)
    return az, el


def circular(t, speed=1.15, amp_az=1.0, amp_el=1.0):
    omega = speed * 0.12
    az = amp_az * math.sin(omega * t)
    el = amp_el * math.cos(omega * t)
    return az, el


def figure_eight(t, speed=1.15, amp_az=1.2, amp_el=0.8):
    omega_x = speed * 0.10
    omega_y = speed * 0.20
    az = amp_az * math.sin(omega_x * t)
    el = amp_el * math.sin(omega_y * t)
    return az, el


def spiral(t, speed=1.15, amp_az=1.4, amp_el=1.4):
    """Archemedian spiral winding outward (optional PS type)."""
    ang = speed * 0.18 * t
    rad = (0.15 + 0.03 * t) % (amp_az * 1.4)
    az = rad * math.cos(ang)
    el = rad * math.sin(ang)
    return az, el


def sinusoidal(t, speed=1.15, amp_az=1.4, amp_el=0.9):
    """Pure sinusoidal drift (optional PS type)."""
    az = amp_az * math.sin(speed * 0.12 * t)
    el = amp_el * math.sin(speed * 0.08 * t)
    return az, el


class RandomWalk:
    """Stateful seeded random walk (efficient, deterministic)."""

    def __init__(self, speed=1.15, seed=None, amp_az=1.4, amp_el=0.9):
        self._rng = random.Random(seed if seed is not None else 42)
        self._az = 0.0
        self._el = 0.0
        self._step = speed * 0.04
        self._amp_az = amp_az
        self._amp_el = amp_el

    def __call__(self, t, speed=1.15, amp_az=1.4, amp_el=0.9):
        self._az += self._rng.uniform(-self._step, self._step)
        self._el += self._rng.uniform(-self._step, self._step)
        self._az = max(-self._amp_az, min(self._amp_az, self._az))
        self._el = max(-self._amp_el, min(self._amp_el, self._el))
        return self._az, self._el


def _make_random(speed=1.15, seed=None, amp_az=1.4, amp_el=0.9):
    return RandomWalk(speed=speed, seed=seed, amp_az=amp_az, amp_el=amp_el)


MOTION_TYPES = {
    "straight_line": straight_line,
    "circular": circular,
    "figure_eight": figure_eight,
    "random": _make_random,
    "spiral": spiral,
    "sinusoidal": sinusoidal,
}
