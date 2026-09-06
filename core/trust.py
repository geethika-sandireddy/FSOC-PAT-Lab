"""
core/trust.py
--------------
Adaptive Model-Vision Trust Manager -- the Phase 2 centrepiece.

The estimator's job is to fuse two complementary cues:

  * VISION  : the camera measurement (detection + AI classification +
              modulation identity + centroid accuracy), and
  * MODEL   : the predicted motion (ephemeris / kinematic extrapolation).

A conventional filter fixes one trust model and keeps it.  This manager
instead re-estimates, every frame, how much each cue deserves to be believed
-- from Identity/Position/Prediction confidence, the prediction residual, the
measurement SNR, and the disturbance condition -- and then picks an operating
mode:

  * BALANCED        - vision and model agree: use both (default, low gain).
  * VISION_DOMINANT - prediction and observation disagree (manoeuvre, wrong
                      prior): trust the eyes, raise observation gain.
  * MODEL_DOMINANT  - measurement degraded (fade, noise, occlusion) but the
                      model is sound: smooth through it, low observation gain.
  * COAST           - beacon unobserved: predictive coast, uncertainty grows.
  * REACQUIRE       - coast uncertainty became too large: stop blindly
                      following the model; active search / re-acquisition.

Switching uses soft margins plus a debounce so the mode cannot rattle
frame-to-frame (hysteresis: enter < exit, persist N frames).
"""

import config

MODE_BALANCED = "BALANCED"
MODE_VISION = "VISION_DOMINANT"
MODE_MODEL = "MODEL_DOMINANT"
MODE_COAST = "COAST"
MODE_REACQUIRE = "REACQUIRE"


class AdaptiveTrustManager:
    def __init__(self):
        self.mode = MODE_BALANCED
        self.vision_trust = 0.5
        self.model_trust = 0.5
        self.blend_w = 0.5            # vision share used by the estimator (0-1)
        self.prior_reliability = 0.6  # EMA of how often the model has agreed
        self._debounce = 0
        self._goal_mode = MODE_BALANCED
        self.samples = 0

    # ------------------------------------------------------------------
    @staticmethod
    def _snr_norm(snr):
        return min(1.0, snr / (snr + 10.0))

    def update(self, *, conf, mod_score, snr, dist_level, visible):
        self.samples += 1

        identity = conf.identity if visible else 0.0
        mod_n = max(0.0, min(1.0, mod_score)) if visible else 0.0
        snr_n = self._snr_norm(snr) if visible else 0.0
        centroid_stab = conf.position if visible else 0.0

        wv = (config.TRUST_VISION_W_ML + config.TRUST_VISION_W_MOD
              + config.TRUST_VISION_W_SNR + config.TRUST_VISION_W_CENTROID)
        vision = (config.TRUST_VISION_W_ML * identity
                  + config.TRUST_VISION_W_MOD * mod_n
                  + config.TRUST_VISION_W_SNR * snr_n
                  + config.TRUST_VISION_W_CENTROID * centroid_stab) / wv

        wm = (config.TRUST_MODEL_W_PRED + config.TRUST_MODEL_W_PRIOR
              + config.TRUST_MODEL_W_DIST)
        dist_c = 1.0 - max(0.0, min(1.0, dist_level))
        model = (config.TRUST_MODEL_W_PRED * conf.prediction
                 + config.TRUST_MODEL_W_PRIOR * self.prior_reliability
                 + config.TRUST_MODEL_W_DIST * dist_c) / wm

        # persistent reliability of the motion model (for the explanation, and
        # as its own slowly-adapting term)
        self.prior_reliability = 0.9 * self.prior_reliability + 0.1 * conf.prediction

        self.vision_trust = max(0.0, min(1.0, vision))
        self.model_trust = max(0.0, min(1.0, model))

        # decide the operating mode (with hysteresis / debounce)
        if not visible:
            goal = MODE_COAST
        else:
            margin = config.VISION_DOMINANT_MARGIN
            if self.vision_trust >= self.model_trust + margin:
                goal = MODE_VISION
            elif self.model_trust >= self.vision_trust + margin:
                goal = MODE_MODEL
            else:
                goal = MODE_BALANCED
        self._switch(goal)

        # vision share for the estimator: mode-driven, smooth
        if self.mode == MODE_VISION:
            self.blend_w = 0.85
        elif self.mode == MODE_MODEL:
            self.blend_w = 0.30
        elif self.mode == MODE_COAST:
            self.blend_w = 0.5
        else:  # BALANCED: fine-tune continuously by trust separation
            self.blend_w = max(0.4, min(0.6,
                                        0.5 + (self.vision_trust - self.model_trust)))

        return self.mode

    # ------------------------------------------------------------------
    def update_coast(self, visible, uncertainty):
        """While the beacon is unobserved, escalate COAST -> REACQUIRE as the
        prediction uncertainty grows past its credibility limit."""
        if visible:
            self._switch(MODE_BALANCED)
            return self.mode
        if uncertainty.reacquire_threshold_reached():
            self._switch(MODE_REACQUIRE)
        else:
            self._switch(MODE_COAST)
        return self.mode

    def _switch(self, goal):
        """Debounced mode change (hysteresis: persistent N frames)."""
        if goal == self._goal_mode:
            self._debounce += 1
        else:
            self._goal_mode = goal
            self._debounce = 0
        if self._debounce >= 2:
            self.mode = goal
        # note: mode = MODE_REACQUIRE is intentionally sticky until the
        # beacon is seen again or the search times out at the tracker level.

    # ------------------------------------------------------------------
    def snapshot(self):
        return dict(mode=self.mode,
                    vision_trust=round(self.vision_trust, 3),
                    model_trust=round(self.model_trust, 3),
                    blend_w=round(self.blend_w, 3),
                    prior_reliability=round(self.prior_reliability, 3))