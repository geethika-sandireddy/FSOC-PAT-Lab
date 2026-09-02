"""
core/baseline_tracker.py
------------------------
A deliberately NAIVE baseline tracker for honest A/B comparison against the
adaptive tracker (`core/tracking.py`).

This baseline represents "what a simple camera-based centroid tracker would
do" and intentionally does NONE of the things that make the adaptive system
robust:

  * NO synthetic-ephemeris prediction / prior gating,
  * NO AI appearance classification (ignores candidate.ml_score),
  * NO modulation (15 Hz beacon) identity verification,
  * NO spatial-consistency tentative track,
  * NO false-lock suspect monitor.

It simply grabs the *brightest* blob on each frame and latches onto it.
Because it cannot tell the modulated beacon apart from a bright distractor
(or a turbulence flash), it suffers exactly the failure modes the adaptive
system is designed to defeat: fast but *wrong* locks, high pointing error,
and no self-recovery after losing the beacon.

It reuses the SAME platform physics (gimbal, disturbances, detector) so the
benchmark measures the *tracking algorithm's* contribution, not the sensor.
The interface is identical to core.tracking.Tracker (state, est_az/el,
.associated, last_candidate_*, .reset/.update/.search_point, acquisition_count)
so it drops into the same Simulator control loop unchanged.
"""

import config

SEARCHING = "SEARCHING"
COASTING = "COASTING"
LOCKED = "LOCKED"


class BaselineTracker:
    def __init__(self, ephemeris_model, seed=None):
        self.eph = ephemeris_model
        self.state = SEARCHING
        self.est_az = None
        self.est_el = None
        self.confidence = 0.0
        self.associated = None
        self.last_candidate_age = 1e9
        self.last_candidate_az = None
        self.last_candidate_el = None
        self.coast_time = 0.0
        self.search_angle = 0.0
        self.search_radius = 0.0
        self.acquisition_count = 0
        self._coast = 0.0

    def reset(self, az, el):
        self.est_az, self.est_el = az, el
        self.state = SEARCHING
        self.associated = None
        self._coast = 0.0

    # ------------------------------------------------------------------
    def update(self, candidates, t, dt):
        if candidates:
            # brightest blob first (naive: no appearance / modulation gate)
            best = max(candidates, key=lambda c: c.peak)
            self.last_candidate_age = 0.0
            self.last_candidate_az, self.last_candidate_el = best.los_az, best.los_el
            self.associated = best
            if self.state != LOCKED:
                # naive acquisition: ANY blob locks it in immediately
                self.state = LOCKED
                self.acquisition_count += 1
                self._coast = 0.0
            self.est_az, self.est_el = best.los_az, best.los_el
            self.confidence = getattr(best, "ml_score", 0.5)
            return self.state, self.est_az, self.est_el, self.confidence
        # no contact: brief coast then give up and search
        self.associated = None
        self._coast += dt
        if self.state == LOCKED and self._coast < config.COAST_TIMEOUT_S:
            self.state = COASTING
        else:
            self.state = SEARCHING
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
        return (base_az + self.search_radius * __import__("math").cos(self.search_angle),
                base_el + self.search_radius * __import__("math").sin(self.search_angle))
