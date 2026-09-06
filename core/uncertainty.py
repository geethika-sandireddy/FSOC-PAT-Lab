"""
core/uncertainty.py
--------------------
Position uncertainty of the tracker's estimate, in px (and deg).

Confidence answers "how much do I believe this measurement?"; uncertainty
answers "how wrong could my estimate be?".  Three contributions:

  1. Measurement uncertainty   - from SNR and centroid flicker at the moment
     of observation (a noisy, dim, flickering blob -> big sigma),
  2. Residual uncertainty      - observation-vs-prediction disagreement widens
     the spread (the target may be manoeuvring),
  3. Coast growth              - while the beacon is out, uncertainty grows
     super-linearly with time; beyond REACQUIRE_UNCERTAINTY_PX the trust
     manager stops blindly following the model and demands active
     re-acquisition.

Exposed values are a single sigma_px (or sigma_deg) per frame, low-passed so
the GUI and the controller see a smooth number.
"""

import math

import config


class UncertaintyEstimator:
    def __init__(self):
        self.sigma_px = config.UNCERTAINTY_BASE_PX
        self.sigma_deg = config.UNCERTAINTY_BASE_PX / config.PIXELS_PER_DEG
        self.coast_time = 0.0
        self._coast_sigma0 = config.UNCERTAINTY_BASE_PX

    # ------------------------------------------------------------------
    def observe(self, *, snr, centroid_residual_px, pred_residual_px):
        """Update uncertainty from a live observation (measurement noise +
        motion-model mismatch)."""
        self.coast_time = 0.0
        sig = config.UNCERTAINTY_BASE_PX * (1.0 + self._snr_penalty(snr))
        sig = max(sig, centroid_residual_px * 0.75)
        sig = max(sig, pred_residual_px * 0.50)
        sig = min(24.0, sig)                     # hard cap: never report absurd
        # smooth (no chattering display/control input)
        self.sigma_px = 0.7 * sig + 0.3 * min(24.0, self.sigma_px)
        self.sigma_deg = self.sigma_px / config.PIXELS_PER_DEG
        return self.sigma_px, self.sigma_deg

    def _snr_penalty(self, snr):
        # snr 20 -> +0.5x sigma; snr 5 -> +2.5x; saturated for very dim blobs
        k = config.UNCERTAINTY_SNR_K
        return max(0.0, min(4.0, k / max(1e-6, snr)))

    # ------------------------------------------------------------------
    def coast(self, dt):
        """Grow uncertainty while the beacon is unobserved.

        sigma(t) = sigma0 + k1*t + k2*t^2   (matching the spec'd growth:
        0.0s->~2px, 0.5s->~5px, 1.0s->~10px, 1.5s->~18px, 2.0s->~30px).
        """
        if self.coast_time == 0.0:
            self._coast_sigma0 = self.sigma_px
        self.coast_time += dt
        t = self.coast_time
        grow = config.UNCERTAINTY_COAST_GROW_S
        grow2 = config.UNCERTAINTY_COAST_GROW2_S
        sig = self._coast_sigma0 + grow * t + grow2 * t * t
        self.sigma_px = sig
        self.sigma_deg = sig / config.PIXELS_PER_DEG
        return self.sigma_px, self.sigma_deg

    def reacquire_threshold_reached(self):
        return self.sigma_px >= config.REACQUIRE_UNCERTAINTY_PX

    # ------------------------------------------------------------------
    def snapshot(self):
        return dict(sigma_px=round(self.sigma_px, 2),
                    sigma_deg=round(self.sigma_deg, 4),
                    coast_time=round(self.coast_time, 3))