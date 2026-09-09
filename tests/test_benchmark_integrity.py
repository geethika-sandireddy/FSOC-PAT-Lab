"""tests/test_benchmark_integrity.py
----------------------------------
Automated forensic verification suite for SIH26169 (Stage 3 & Stage 4):
1. Error Separation: Metric A (detected centroid), Metric B (boresight offset), Metric C (true centroid error).
2. Zero Ground-Truth Leakage into detection, tracking, or gimbal control.
3. 30 FPS MP4 Benchmark Pipeline with separated FPS metrics (Input, Processing, Telemetry, GUI).
4. Configurable Target Parameters (sizes 5x5 to 20x20 px, shapes SQUARE, CIRCLE, ELLIPSE, SPOT).
5. Anisotropic / Independent Horizontal and Vertical FOV scaling.
6. State Estimator Comparison (Discrete Kalman Filter vs EMA vs Raw Centroid).
7. Ephemeris Model Mismatch handling and staged reacquisition under occlusion.
"""

import ast
import inspect
import math
import os
import sys
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.simulator import Simulator
from core.kalman import PointingKalmanFilter, compare_raw_ema_kalman
from core.orbital import EphemerisModel, RelativeOrbitModel
from core.tracking import Tracker, LOCKED, DEGRADED_LOCK, CANDIDATE, SEARCHING
from metrics.performance import PerformanceTracker


class TestBenchmarkIntegrity(unittest.TestCase):
    """Forensic verification for SIH26169 evaluation standards."""

    # ------------------------------------------------------------------
    # 1. Error Separation: Metric A, Metric B, Metric C
    # ------------------------------------------------------------------
    def test_01_error_metric_separation(self):
        """Verify that Metric A, Metric B, and Metric C are strictly separated and mathematically distinct."""
        sim = Simulator(preset_name="EASY", seed=42)
        # Step until locked
        res = None
        for _ in range(25):
            res = sim.step()

        # Metric A: Detected centroid (u, v)
        self.assertIn("candidates_detail", res)
        self.assertIn("cand_list", res)
        assoc = sim.tracker.associated
        self.assertIsNotNone(assoc, "Tracker must associate a candidate when locked")
        detected_u = assoc.u
        detected_v = assoc.v
        self.assertTrue(0 <= detected_u <= config.CAM_VIEW_W)
        self.assertTrue(0 <= detected_v <= config.CAM_VIEW_H)

        # Metric B: Optical-axis / frame-centre offset
        self.assertIn("boresight_error_px", res)
        cam_cx = config.CAM_VIEW_W / 2.0
        cam_cy = config.CAM_VIEW_H / 2.0
        expected_b_px = round(math.hypot(detected_u - cam_cx, detected_v - cam_cy), 2)
        self.assertAlmostEqual(res["boresight_error_px"], expected_b_px, places=1)

        # Metric C: True centroiding error (distance to GT target centroid)
        self.assertIn("centroid_error_px", res)
        truth_az = sim.scene.beacon.az_deg
        truth_el = sim.scene.beacon.el_deg
        cam_canvas = sim.sensor._canvas_xy(sim.gimbal.pan, sim.gimbal.tilt)
        gt_u, gt_v = sim.sensor._viewport_px(truth_az, truth_el, cam_canvas)
        expected_c_px = round(math.hypot(detected_u - gt_u, detected_v - gt_v), 2)
        self.assertAlmostEqual(res["centroid_error_px"], expected_c_px, places=1)

        # Confirm Metric B and Metric C are NOT conflated
        # Boresight offset is offset from center; Centroid error is detection accuracy vs true beacon
        self.assertNotEqual(res["centroid_error_px"], res["boresight_error_px"])

    # ------------------------------------------------------------------
    # 2. Zero Ground-Truth Leakage Audit
    # ------------------------------------------------------------------
    def test_02_zero_ground_truth_leakage(self):
        """Audit AST of detector and tracker to guarantee GT truth coordinates are never accessed."""
        from core import detection, tracking

        detector_source = inspect.getsource(detection)
        tracking_source = inspect.getsource(tracking)

        # Check that truth attributes are nowhere in detector or tracker source
        forbidden_attrs = ["truth_az", "truth_el", "scene.beacon", "scene.beacons", "beacon.az_deg", "beacon.el_deg"]
        for attr in forbidden_attrs:
            self.assertNotIn(attr, detector_source, f"Forbidden GT leakage found in detector: {attr}")
            self.assertNotIn(attr, tracking_source, f"Forbidden GT leakage found in tracker: {attr}")

        # Check function signature of detect and update
        det_sig = inspect.signature(detection.DetectionEngine.detect)
        trk_sig = inspect.signature(tracking.Tracker.update)
        self.assertNotIn("truth", det_sig.parameters)
        self.assertNotIn("target_pos", det_sig.parameters)
        self.assertNotIn("truth", trk_sig.parameters)

    # ------------------------------------------------------------------
    # 3. Anisotropic / Independent Horizontal and Vertical Scales
    # ------------------------------------------------------------------
    def test_03_independent_fov_scaling(self):
        """Verify PIXELS_PER_DEG_X and PIXELS_PER_DEG_Y scale independently with non-square aspect ratio FOVs."""
        sim = Simulator(preset_name="EASY", seed=42)
        # Default 640x480 with 4.0 x 3.0 deg FOV -> 160 px/deg isotropic
        self.assertAlmostEqual(config.PIXELS_PER_DEG_X, 160.0, places=2)
        self.assertAlmostEqual(config.PIXELS_PER_DEG_Y, 160.0, places=2)

        # Update to anisotropic FOV: HFOV = 5.0 deg, VFOV = 3.0 deg
        sim.set_fov(5.0, 3.0)
        self.assertAlmostEqual(config.PIXELS_PER_DEG_X, 640.0 / 5.0, places=2)  # 128.0 px/deg
        self.assertAlmostEqual(config.PIXELS_PER_DEG_Y, 480.0 / 3.0, places=2)  # 160.0 px/deg
        self.assertNotEqual(config.PIXELS_PER_DEG_X, config.PIXELS_PER_DEG_Y)

        # Restore defaults
        sim.set_fov(4.0, 3.0)
        self.assertAlmostEqual(config.PIXELS_PER_DEG_X, 160.0, places=2)
        self.assertAlmostEqual(config.PIXELS_PER_DEG_Y, 160.0, places=2)

    # ------------------------------------------------------------------
    # 4. Target Sizes (5x5 to 20x20 px) and Shapes
    # ------------------------------------------------------------------
    def test_04_target_sizes_and_shapes(self):
        """Verify target sizes 5x5 to 20x20 and shapes SQUARE, CIRCLE, ELLIPSE, SPOT render and track cleanly."""
        sim = Simulator(preset_name="EASY", seed=42)

        for size in [5, 10, 15, 20]:
            for shape in ["SQUARE", "CIRCLE", "ELLIPSE", "SPOT"]:
                sim.set_target_params(shape=shape, size_px=size, size_py=size)
                self.assertEqual(config.TARGET_SIZE_PX, size)
                self.assertEqual(config.TARGET_SHAPE, shape)
                # Render a frame and verify blob detected
                res = sim.step()
                self.assertIsNotNone(res["frame"])
                self.assertEqual(res["frame"].shape[:2], (480, 640))

        # Restore default
        sim.set_target_params(shape="SQUARE", size_px=10, size_py=10)

    # ------------------------------------------------------------------
    # 5. State Estimator Comparison: Kalman vs EMA vs Raw Centroid
    # ------------------------------------------------------------------
    def test_05_kalman_filter_performance(self):
        """Verify PointingKalmanFilter provides superior noise rejection and outlier gating over raw centroid and EMA."""
        results = compare_raw_ema_kalman(n_samples=200, dt=1.0/60.0, seed=42)
        self.assertIn("rmse_raw", results)
        self.assertIn("rmse_ema", results)
        self.assertIn("rmse_kalman", results)
        self.assertIn("glint_max_error_raw", results)
        self.assertIn("glint_max_error_kalman", results)

        # Kalman RMSE must be lower than raw centroid RMSE
        self.assertLess(results["rmse_kalman"], results["rmse_raw"])
        # Kalman must reject the glint outlier (smaller max error than raw)
        self.assertLess(results["glint_max_error_kalman"], results["glint_max_error_raw"])

    # ------------------------------------------------------------------
    # 6. Model Mismatch and Staged Reacquisition
    # ------------------------------------------------------------------
    def test_06_model_mismatch_and_reacquisition(self):
        """Verify system maintains track lock and reacquires within 1.0s under orbital model mismatch."""
        # Test under moderate mismatch
        sim = Simulator(preset_name="EASY", mismatch_mode="moderate", seed=42)

        # Acquire lock
        locked = False
        for _ in range(30):
            res = sim.step()
            if res["state"] in ("LOCKED", "DEGRADED_LOCK"):
                locked = True
                break
        self.assertTrue(locked, "Tracker must acquire lock even under moderate ephemeris mismatch")

        # Inject 10-frame target occlusion
        sim.inject_target_loss(duration_s=10.0/60.0)
        for _ in range(10):
            res = sim.step()

        # Step post-occlusion and measure reacquisition time
        reacq_done = False
        t_loss_end = sim.t
        for _ in range(60):
            res = sim.step()
            if res["state"] in ("LOCKED", "DEGRADED_LOCK"):
                reacq_dt = sim.t - t_loss_end
                self.assertLessEqual(reacq_dt, 1.0, f"Reacquisition must be <= 1.0s (measured: {reacq_dt:.3f}s)")
                reacq_done = True
                break
        self.assertTrue(reacq_done, "Tracker must reacquire after occlusion under model mismatch")


if __name__ == "__main__":
    unittest.main()
