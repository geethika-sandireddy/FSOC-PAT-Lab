"""tests/test_state_truth.py
--------------------------
Forensic state-truth automated verification suite for SIH26169.
Verifies Cases A through M:
  A. no target -> SEARCHING
  B. weak blob -> CANDIDATE/SEARCHING, never LOCKED
  C. one valid observation -> CANDIDATE (not LOCKED)
  D. consecutive valid observations -> LOCKED (requires 5 frames)
  E. target disappears -> LOCKED drops immediately to COASTING -> REACQUIRING -> LOST -> SEARCHING
  F. decoy appears -> must not falsely lock (fails modulation)
  G. wrong candidate -> no LOCKED
  H. stale measurement -> no LOCKED, measurement_age grows
  I. prediction-only frames -> prediction_only True, not falsely counted as measured lock
  J. reacquisition -> REACQUIRING, then LOCKED only after validation (3 frames)
  K. reset -> SEARCHING
  L. UI telemetry state exactly matches backend state
  M. no GT leakage
"""

import ast
import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.orbital import EphemerisModel, RelativeOrbitModel
from core.tracking import (
    Tracker,
    SEARCHING,
    CANDIDATE,
    ACQUIRING,
    LOCKED,
    DEGRADED_LOCK,
    COASTING,
    REACQUIRING,
    LOST,
)
from core.simulator import Simulator
from ui.mission_pages import OpticalLinkModel
from metrics.performance import PerformanceTracker
from server import _build_telemetry


class MockCandidate:
    """Synthetic candidate blob adhering to DetectionEngine interface."""
    def __init__(self, u=320.0, v=240.0, los_az=0.0, los_el=0.0,
                 ml_score=0.92, snr=25.0, peak=240.0, area=100.0, track_id=1):
        self.x = u
        self.y = v
        self.u = u
        self.v = v
        self.los_az = los_az
        self.los_el = los_el
        self.ml_score = ml_score
        self.snr = snr
        self.peak = peak
        self.area = area
        self.track_id = track_id
        self.circularity = 0.95
        self.track_age = 5
        self.mod_score = 0.0
        self.prior_score = 1.0
        self.fusion_score = ml_score
        self._assoc_score = ml_score


class TestStateTruth(unittest.TestCase):
    """Rigorous verification of the 8-state tracking truth machine."""

    def setUp(self):
        self.orbit = RelativeOrbitModel(motion_type="straight_line", seed=42)
        self.eph = EphemerisModel(self.orbit, seed=42)

    def _make_candidate(self, t, ml_score=0.95, snr=25.0, peak=240.0, area=100.0, track_id=1):
        p_az, p_el = self.eph.predict_az_el(t)
        return MockCandidate(
            los_az=p_az, los_el=p_el,
            ml_score=ml_score, snr=snr, peak=peak, area=area, track_id=track_id
        )

    # ------------------------------------------------------------------
    # Case A: no target -> SEARCHING
    # ------------------------------------------------------------------
    def test_case_A_no_target_searching(self):
        tracker = Tracker(self.eph, video_mode=False)
        tracker.reset(0.0, 0.0)
        st, az, el, conf = tracker.update([], t=0.0, dt=1.0/60.0)
        self.assertEqual(st, SEARCHING)
        self.assertEqual(tracker.state, SEARCHING)
        self.assertFalse(tracker.is_locked)
        self.assertFalse(tracker.measurement_valid)
        self.assertTrue(tracker.prediction_only)

    # ------------------------------------------------------------------
    # Case B: weak blob -> CANDIDATE/SEARCHING, never LOCKED
    # ------------------------------------------------------------------
    def test_case_B_weak_blob_never_locked(self):
        tracker = Tracker(self.eph, video_mode=False)
        tracker.reset(0.0, 0.0)
        for frame in range(20):
            t = frame * 1.0/60.0
            p_az, p_el = self.eph.predict_az_el(t)
            weak = MockCandidate(los_az=p_az, los_el=p_el, ml_score=0.20, snr=3.0)
            st, _, _, _ = tracker.update([weak], t=t, dt=1.0/60.0)
            self.assertIn(st, (SEARCHING, CANDIDATE))
            self.assertNotEqual(st, LOCKED)
            self.assertFalse(tracker.is_locked)

    # ------------------------------------------------------------------
    # Case C: one valid observation -> not LOCKED
    # ------------------------------------------------------------------
    def test_case_C_one_valid_observation_not_locked(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)
        c = self._make_candidate(0.0, ml_score=0.95)
        st, _, _, _ = tracker.update([c], t=0.0, dt=1.0/30.0)
        self.assertEqual(st, CANDIDATE)
        self.assertFalse(tracker.is_locked)
        self.assertTrue(tracker.measurement_valid)
        self.assertFalse(tracker.prediction_only)

    # ------------------------------------------------------------------
    # Case D: consecutive valid observations -> LOCKED
    # ------------------------------------------------------------------
    def test_case_D_consecutive_valid_observations_locked(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        # Frame 1 -> CANDIDATE
        c0 = self._make_candidate(0.0, ml_score=0.95)
        st, _, _, _ = tracker.update([c0], t=0.0, dt=1.0/30.0)
        self.assertEqual(st, CANDIDATE)
        self.assertFalse(tracker.is_locked)

        # Frame 2-4 -> ACQUIRING
        for i in range(1, 4):
            t = i * 1.0/30.0
            ci = self._make_candidate(t, ml_score=0.95)
            st, _, _, _ = tracker.update([ci], t=t, dt=1.0/30.0)
            self.assertEqual(st, ACQUIRING)
            self.assertFalse(tracker.is_locked)

        # Frame 5 -> reaches LOCK_CONFIRM_FRAMES (5) -> LOCKED
        t4 = 4 * 1.0/30.0
        c4 = self._make_candidate(t4, ml_score=0.95)
        st, _, _, _ = tracker.update([c4], t=t4, dt=1.0/30.0)
        self.assertEqual(st, LOCKED)
        self.assertTrue(tracker.is_locked)
        self.assertTrue(tracker.measurement_valid)
        self.assertFalse(tracker.prediction_only)

    # ------------------------------------------------------------------
    # Case E: target disappears -> LOCKED must eventually drop
    # ------------------------------------------------------------------
    def test_case_E_target_disappears_locked_drops(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        for i in range(6):
            t = i * 1.0/30.0
            ci = self._make_candidate(t, ml_score=0.95)
            tracker.update([ci], t=t, dt=1.0/30.0)
        self.assertEqual(tracker.state, LOCKED)
        self.assertTrue(tracker.is_locked)

        # First missing frame -> IMMEDIATE lock drop to COASTING
        st, _, _, _ = tracker.update([], t=0.20, dt=1.0/30.0)
        self.assertEqual(st, COASTING)
        self.assertFalse(tracker.is_locked)
        self.assertFalse(tracker.measurement_valid)
        self.assertTrue(tracker.prediction_only)

        # Sustained absence -> transitions COASTING -> REACQUIRING -> LOST -> SEARCHING
        states_seen = set()
        for i in range(120):
            st, _, _, _ = tracker.update([], t=0.20 + (i+1)*1.0/30.0, dt=1.0/30.0)
            states_seen.add(st)
            self.assertFalse(tracker.is_locked)

        self.assertIn(LOST, states_seen)
        self.assertIn(SEARCHING, states_seen)
        self.assertEqual(tracker.state, SEARCHING)

    # ------------------------------------------------------------------
    # Case F: decoy appears -> must not falsely lock
    # ------------------------------------------------------------------
    def test_case_F_decoy_appears_no_false_lock(self):
        tracker = Tracker(self.eph, video_mode=False)
        tracker.reset(0.0, 0.0)

        # Decoy has static/flat brightness (mod_score will fail 15 Hz template)
        for i in range(40):
            t = i * 1.0/60.0
            p_az, p_el = self.eph.predict_az_el(t)
            decoy = MockCandidate(los_az=p_az, los_el=p_el, ml_score=0.88, peak=100.0, area=50.0)
            st, _, _, _ = tracker.update([decoy], t=t, dt=1.0/60.0)
            self.assertNotEqual(st, LOCKED)
            self.assertFalse(tracker.is_locked)

    # ------------------------------------------------------------------
    # Case G: wrong candidate / erratic jump -> no LOCKED
    # ------------------------------------------------------------------
    def test_case_G_wrong_candidate_erratic_jump(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        for i in range(20):
            hop_candidate = MockCandidate(los_az=(i % 2) * 5.0, los_el=float(i), ml_score=0.90)
            st, _, _, _ = tracker.update([hop_candidate], t=i * 1.0/30.0, dt=1.0/30.0)
            self.assertNotEqual(st, LOCKED)
            self.assertFalse(tracker.is_locked)

    # ------------------------------------------------------------------
    # Case H: stale measurement -> no LOCKED
    # ------------------------------------------------------------------
    def test_case_H_stale_measurement_no_locked(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        for i in range(6):
            t = i * 1.0/30.0
            ci = self._make_candidate(t, ml_score=0.95)
            tracker.update([ci], t=t, dt=1.0/30.0)
        self.assertTrue(tracker.is_locked)

        for i in range(10):
            tracker.update([], t=0.20 + i * 1.0/30.0, dt=1.0/30.0)

        self.assertFalse(tracker.is_locked)
        self.assertGreater(tracker.measurement_age, 0.30)
        self.assertFalse(tracker.measurement_valid)

    # ------------------------------------------------------------------
    # Case I: prediction-only frames -> not falsely counted as measured lock
    # ------------------------------------------------------------------
    def test_case_I_prediction_only_frames(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        for i in range(6):
            t = i * 1.0/30.0
            ci = self._make_candidate(t, ml_score=0.95)
            tracker.update([ci], t=t, dt=1.0/30.0)
        self.assertTrue(tracker.is_locked)
        self.assertFalse(tracker.prediction_only)

        tracker.update([], t=0.25, dt=1.0/30.0)
        self.assertTrue(tracker.prediction_only)
        self.assertFalse(tracker.is_locked)
        self.assertFalse(tracker.measurement_valid)

    # ------------------------------------------------------------------
    # Case J: reacquisition -> REACQUIRING, then LOCKED only after validation
    # ------------------------------------------------------------------
    def test_case_J_reacquisition_validation(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        for i in range(6):
            t = i * 1.0/30.0
            ci = self._make_candidate(t, ml_score=0.95)
            tracker.update([ci], t=t, dt=1.0/30.0)
        self.assertEqual(tracker.state, LOCKED)

        tracker.update([], t=0.20, dt=1.0/30.0)
        tracker.update([], t=0.23, dt=1.0/30.0)
        self.assertEqual(tracker.state, COASTING)

        # Target reappears:
        c1 = self._make_candidate(0.26, ml_score=0.95)
        st1, _, _, _ = tracker.update([c1], t=0.26, dt=1.0/30.0)
        self.assertEqual(st1, REACQUIRING)
        self.assertFalse(tracker.is_locked)

        c2 = self._make_candidate(0.30, ml_score=0.95)
        st2, _, _, _ = tracker.update([c2], t=0.30, dt=1.0/30.0)
        self.assertEqual(st2, REACQUIRING)
        self.assertFalse(tracker.is_locked)

        c3 = self._make_candidate(0.33, ml_score=0.95)
        st3, _, _, _ = tracker.update([c3], t=0.33, dt=1.0/30.0)
        self.assertEqual(st3, LOCKED)
        self.assertTrue(tracker.is_locked)

    # ------------------------------------------------------------------
    # Case K: reset -> SEARCHING
    # ------------------------------------------------------------------
    def test_case_K_reset_searching(self):
        tracker = Tracker(self.eph, video_mode=True)
        tracker.reset(0.0, 0.0)

        for i in range(6):
            t = i * 1.0/30.0
            ci = self._make_candidate(t, ml_score=0.95)
            tracker.update([ci], t=t, dt=1.0/30.0)
        self.assertTrue(tracker.is_locked)

        tracker.reset(0.0, 0.0)
        self.assertEqual(tracker.state, SEARCHING)
        self.assertFalse(tracker.is_locked)
        self.assertTrue(tracker.prediction_only)
        self.assertFalse(tracker.measurement_valid)

    # ------------------------------------------------------------------
    # Case L: UI telemetry state exactly matches backend state
    # ------------------------------------------------------------------
    def test_case_L_telemetry_state_matches_backend(self):
        sim = Simulator(preset_name="EASY", dt=1.0/60.0, seed=42)
        res = sim.step()
        opt = OpticalLinkModel()
        perf = PerformanceTracker()
        perf.record_frame(sim)

        class MockStress:
            scenarios = {}
            def record_rx_power(self, p): pass

        telem = _build_telemetry(res, sim, perf, opt, MockStress(), 60.0)

        self.assertEqual(telem["state"], sim.tracker.state)
        self.assertEqual(telem["tracking_state"], sim.tracker.state)
        self.assertEqual(telem["is_locked"], sim.tracker.is_locked)
        self.assertEqual(telem["measurement_valid"], sim.tracker.measurement_valid)
        self.assertEqual(telem["prediction_only"], sim.tracker.prediction_only)

        self.assertIn("boresight_error_px", telem)
        self.assertIn("centroid_error_px", telem)
        if telem["boresight_error_px"] is not None and telem["centroid_error_px"] is not None:
            self.assertTrue(isinstance(telem["boresight_error_px"], (int, float)))
            self.assertTrue(isinstance(telem["centroid_error_px"], (int, float)))

    # ------------------------------------------------------------------
    # Case M: no ground truth leakage in tracker, detector, or controller
    # ------------------------------------------------------------------
    def test_case_M_no_gt_leakage(self):
        modules_to_audit = [
            "core.tracking",
            "core.detection",
            "core.control",
        ]

        forbidden_names = {
            "truth_az", "truth_el", "truth_dir", "beacon_truth", "gt_x", "gt_y",
            "true_centroid_err_px", "true_centroid_err_deg", "ground_truth"
        }

        for mod_name in modules_to_audit:
            mod = sys.modules.get(mod_name)
            if mod is None:
                __import__(mod_name)
                mod = sys.modules[mod_name]

            source = inspect.getsource(mod)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.assertNotIn(
                        node.id, forbidden_names,
                        f"Ground truth leakage found in {mod_name}: variable '{node.id}'"
                    )
                elif isinstance(node, ast.Attribute):
                    self.assertNotIn(
                        node.attr, forbidden_names,
                        f"Ground truth leakage found in {mod_name}: attribute '{node.attr}'"
                    )


if __name__ == "__main__":
    unittest.main()
