*** Begin Patch
*** Update File: core/tracking.py
@@
-                gate = self._assoc_gate_deg()
-                # Apply widened REACQ gate if currently REACQUIRING OR if we are in the
-                # single-frame handover immediately after a successful REACQUIRING promotion.
-                if self.state == REACQUIRING or getattr(self, "_reacq_handover", 0) > 0:
-                    # staged reacquisition: the association gate widens with the
-                    # current recovery LEVEL (1..N) around the predicted LOS.  A
-                    # widened gate never by-passes identity - _on_tracked still
-                    # runs the full appearance/modulation verification before
-                    # LOCKED is re-committed.
-                    gate *= config.REACQ_LEVEL_GATE_MULT[
-                        max(0, min(config.REACQ_LEVELS - 1, self.reacq_level - 1))]
-                    # consume the handover if it was the cause (only one frame)
-                    if getattr(self, "_reacq_handover", 0) > 0 and self.state != REACQUIRING:
-                        self._reacq_handover = 0
+                gate = self._assoc_gate_deg()
+                # Apply widened REACQ gate if currently REACQUIRING OR if we are in the
+                # single-frame handover immediately after a successful REACQUIRING promotion.
+                if self.state == REACQUIRING or getattr(self, "_reacq_handover", 0) > 0:
+                    # staged reacquisition: the association gate widens with the
+                    # current recovery LEVEL (1..N) around the predicted LOS.  A
+                    # widened gate never by-passes identity - _on_tracked still
+                    # runs the full appearance/modulation verification before
+                    # LOCKED is re-committed.
+                    gate *= config.REACQ_LEVEL_GATE_MULT[
+                        max(0, min(config.REACQ_LEVELS - 1, self.reacq_level - 1))]
+                    # consume the handover if it was the cause (only one frame)
+                    if getattr(self, "_reacq_handover", 0) > 0 and self.state != REACQUIRING:
+                        self._reacq_handover = 0
*** End Patch