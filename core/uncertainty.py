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

Two values are exposed per frame:

  * sigma_px / sigma_deg        - INTERNAL uncertainty, low-passed so the
    controller and the reacquisition logic see a smooth number.  It is
    deliberately UNBOUNDED: during a long outage the belief genuinely keeps
    degrading (it must, or the 18 px REACQUIRE escalation would never trip),
    and no display cap is allowed to gate the loop.
  * display_sigma_px            - the value painted on the HUD / plotted in
    benchmarks, clamped to ``UNCERTAINTY_DISPLAY_PX_CAP`` so a colour bar or
    text field stays readable.  Purely cosmetic; the loop never reads it.
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
    @property
    def display_sigma_px(self):
        """HUD-safe sigma (clamped).  Telemetry only - never gates behaviour."""
        return min(config.UNCERTAINTY_DISPLAY_PX_CAP, self.sigma_px)

    @property
    def display_sigma_deg(self):
        return self.display_sigma_px / config.PIXELS_PER_DEG

    # ------------------------------------------------------------------
    def observe(self, *, snr, centroid_residual_px, pred_residual_px):
        """Update uncertainty from a live observation (measurement noise +
        motion-model mismatch)."""
        self.coast_time = 0.0
        sig = config.UNCERTAINTY_BASE_PX * (1.0 + self._snr_penalty(snr))
        sig = max(sig, centroid_residual_px * 0.75)
        sig = max(sig, min(sig * 2.0, pred_residual_px * 0.20))
        # smooth (no chattering display/control input); the INTERNAL value is
        # kept without a cap - a violent manoeuvre or corrupt prior may push
        # it far past the HUD clamp and that is the truth the loop needs.
        self.sigma_px = 0.7 * sig + 0.3 * self.sigma_px
        self.sigma_deg = self.sigma_px / config.PIXELS_PER_DEG
        return self.sigma_px, self.sigma_deg

    def _snr_penalty(self, snr):
        # snr 20 -> +0.5x sigma; snr 5 -> +2.5x; saturated for very dim blobs
        k = config.UNCERTAINTY_SNR_K
        return max(0.0, min(4.0, k / max(1e-6, snr)))

    # ------------------------------------------------------------------
    def coast(self, dt):
        """Grow uncertainty while the beacon is unobserved.

        sigma(t) = sigma0 + k1*t + k2*t^2   (with current config:
        ~0.0s -> ~2px, 0.25s -> ~13px, 0.35s -> ~18px (REACQ line),
        0.45s -> ~24px, 1.0s -> ~68px).  The 18 px re-acquire line is crossed
        ~0.34 s after a nominal lock is lost, i.e. while COASTING is still
        allowed and before COAST_TIMEOUT_S forces SEARCH - the escalation
        COAST -> REACQUIRING is real and observable.
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
                    display_sigma_px=round(self.display_sigma_px, 2),
                    sigma_deg=round(self.sigma_deg, 4),
                    coast_time=round(self.coast_time, 3))