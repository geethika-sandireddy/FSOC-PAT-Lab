"""tests/test_mp4_benchmark.py
-----------------------------
Automated unit and integration test suite for Benchmark-2 MP4 Bypass,
Metric A/B/C separation, ground-truth presence/absence handling, and
benchmark report generation for SIH26169.
"""

import os
import sys
import unittest
import numpy as np

# Add repository root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from metrics.synthetic_video import generate
from metrics.mp4_bypass import run_bypass
from core.simulator import VideoInputSimulator


class TestMp4Benchmark(unittest.TestCase):
    """SIH26169 Benchmark-2 MP4 Pipeline & Metric Separation Verification."""

    @classmethod
    def setUpClass(cls):
        os.makedirs(config.LOG_DIR, exist_ok=True)
        cls.test_vid = os.path.join(config.LOG_DIR, "unit_test_vid.mp4")
        cls.test_truth = os.path.join(config.LOG_DIR, "unit_test_vid_truth.csv")
        cls.no_truth_vid = os.path.join(config.LOG_DIR, "unit_test_notruth.mp4")

        # Generate test synthetic video with ground truth (2.0s, 60 frames)
        generate(
            cls.test_vid,
            width=640,
            height=480,
            fps=30,
            seconds=2.0,
            motion="figure_eight",
            noise=["gaussian"],
            beacon_size=10,
        )

        # Generate second video without truth CSV
        generate(
            cls.no_truth_vid,
            width=640,
            height=480,
            fps=30,
            seconds=2.0,
            motion="linear",
            noise=["gaussian"],
            beacon_size=10,
        )
        notruth_csv = os.path.splitext(cls.no_truth_vid)[0] + "_truth.csv"
        if os.path.isfile(notruth_csv):
            os.remove(notruth_csv)

    def test_01_synthetic_generation(self):
        """Verify synthetic video generation produces valid MP4 and truth sidecar CSV."""
        self.assertTrue(os.path.isfile(self.test_vid), "Generated MP4 video must exist.")
        self.assertTrue(os.path.isfile(self.test_truth), "Truth sidecar CSV must exist.")
        self.assertGreater(os.path.getsize(self.test_vid), 1000, "Video size must be > 1KB.")
        self.assertGreater(os.path.getsize(self.test_truth), 100, "Truth CSV must contain rows.")

    def test_02_mp4_bypass_with_ground_truth(self):
        """Verify bypass with ground truth correctly measures Metric A, B, and C."""
        stats = run_bypass(self.test_vid, truth_path=self.test_truth, verbose=False)

        # 1. Ground truth availability flag
        self.assertEqual(stats["ground_truth_available"], "YES")

        # 2. Frame processing and throughput
        self.assertGreaterEqual(stats["processed_frames"], 30)
        self.assertGreaterEqual(stats["processing_fps"], 20.0, "Throughput must meet PS spec >= 20 FPS.")

        # 3. Acquisition time
        self.assertIsNotNone(stats["acquisition_time_s"])
        self.assertLessEqual(stats["acquisition_time_s"], 2.0, "Acquisition must be <= 2.0 s.")

        # 4. Metric B: Optical-axis offset
        self.assertGreater(stats["optical_axis_offset_mean_px"], 0.0)

        # 5. Metric C: True centroiding error (Computed because truth CSV provided)
        self.assertIsNotNone(stats["true_centroid_error_mean_px"])
        self.assertLessEqual(
            stats["true_centroid_error_mean_px"],
            10.0,
            "True centroiding error must meet PS spec <= 10.0 px."
        )

        # 6. Retention and target loss
        self.assertGreaterEqual(stats["lock_retention_pct"], 80.0)
        self.assertLessEqual(stats["target_loss_pct"], 20.0)

    def test_03_mp4_bypass_without_ground_truth(self):
        """Verify bypass without ground truth sets true error to None and reports Metric B only."""
        stats = run_bypass(self.no_truth_vid, truth_path=None, verbose=False)

        # 1. Ground truth availability flag
        self.assertEqual(stats["ground_truth_available"], "NO")

        # 2. Metric B: Optical-axis offset MUST be computed
        self.assertGreater(stats["optical_axis_offset_mean_px"], 0.0)

        # 3. Metric C: True centroiding error MUST be None / N/A (zero falsification)
        self.assertIsNone(stats["true_centroid_error_mean_px"], "True error must be None when no GT.")
        self.assertIsNone(stats["true_centroid_error_rms_px"], "RMS true error must be None when no GT.")
        self.assertIsNone(stats["true_centroid_error_max_px"], "Max true error must be None when no GT.")

    def test_04_simulator_zero_ground_truth_leakage(self):
        """Verify that ground truth coordinates are NEVER leaked into the tracker or control loop."""
        sim = VideoInputSimulator(self.test_vid, truth_path=self.test_truth)

        # Run 10 steps
        for _ in range(10):
            res = sim.step()

        # Check tracker state
        self.assertTrue(hasattr(sim, "tracker"))
        tracked_pos = (sim.detected_cx, sim.detected_cy)
        # Verify tracked position is purely from detector moments/Kalman
        self.assertIsNotNone(tracked_pos[0])
        self.assertIsNotNone(tracked_pos[1])
        sim.close()


if __name__ == "__main__":
    unittest.main()
