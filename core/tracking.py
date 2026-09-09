*** Begin Patch
*** Update File: core/tracking.py
@@
     def __init__(self, ephemeris_model, seed=None, video_mode=False,
                  gate_deg=config.ASSOC_GATE_DEG):
@@
         self.reacq_level = 1
         self.reacq_time = 0.0
+        # one-frame handover flag: holds the widened REACQ gate for the frame
+        # immediately after a successful promotion from REACQUIRING -> LOCKED/
+        # DEGRADED_LOCK so the just-associated candidate is not dropped by the
+        # now-smaller LOCKED association gate on the next frame.
+        self._reacq_handover = 0
@@
     def _on_tracked(self, c, t, dt, p_az, p_el):
+        prev_state = self.state
         self.candidates_seen += 1
@@
         self._prev_track_t = t
+        # If we just promoted a candidate while we were actively REACQUIRING,
+        # hold the widened REACQ gate for one subsequent frame so the
+        # association does not immediately evaporate when the state's gate
+        # multiplier is removed.
+        if prev_state == REACQUIRING and self.state in (LOCKED, DEGRADED_LOCK):
+            self._reacq_handover = 1
         return self.state, self.est_az, self.est_el, self.confidence
*** End Patch
