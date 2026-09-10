"""tests/test_ps_compliance.py
----------------------------
Comprehensive automated verification suite for SIH26169 (Part 2) PS parameter compliance.

Verifies:
1. Virtual screen geometry (default 2000x2000, dynamic custom canvas).
2. Camera specifications (640x480 resolution, >=30 Hz frame rate).
3. Configurable FOV (default 4 deg x 3 deg, dynamic FOV updates focal scale).
4. Initial camera boresight pointing at virtual screen center.
5. Target configuration (default 10x10 px square, range 5-20 px, shapes SQUARE/CIRCLE/SPOT, multiple targets 1-5).
6. Target initial position (random or user-defined az/el).
7. Motion profiles (straight_line, circular, figure_eight, random, spiral, sinusoidal).
8. Gimbal rate limits (default 5.0 deg/s max pan/tilt slew strictly enforced).
9. Platform modes (SAT-SAT vacuum path vs UAV-SAT/UAV-UAV atmospheric links).
10. Noise & disturbance engine (Gaussian, Salt & Pepper, Poisson, Jitter).
11. Real-time parameter dynamic updates reaching backend simulator.
"""

import math
import os
import sys
import unittest
import numpy as np

# Add repository root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.simulator import Simulator
from core.platforms import SATELLITE_SATELLITE, UAV_SATELLITE, UAV_UAV, atmosphere_allowed


class TestPSCompliance(unittest.TestCase):
    """SIH26169 PS Parameter Compliance Tests."""

    def test_01_screen_geometry(self):
        """PS Requirement: 2000x2000 virtual screen, user-defined canvas size support."""
        # Default screen size check
        self.assertEqual(config.SCREEN_SIZE_W, 2000)
        self.assertEqual(config.SCREEN_SIZE_H, 2000)
        self.assertEqual(config.SCREEN_CANVAS_CX, 1000)
        self.assertEqual(config.SCREEN_CANVAS_CY, 1000)

        # Dynamic screen update
        sim = Simulator(preset_name="EASY", seed=42)
        sim.set_screen_size(2400, 1800)
        self.assertEqual(config.SCREEN_SIZE_W, 2400)
        self.assertEqual(config.SCREEN_SIZE_H, 1800)
        self.assertEqual(config.SCREEN_CANVAS_CX, 1200)
        self.assertEqual(config.SCREEN_CANVAS_CY, 900)

        # Restore default
        sim.set_screen_size(2000, 2000)
        self.assertEqual(config.SCREEN_SIZE_W, 2000)
        self.assertEqual(config.SCREEN_SIZE_H, 2000)

    def test_02_camera_specs(self):
        """PS Requirement: 640x480 sensor, update rate >= 30 Hz."""
        sim = Simulator(preset_name="EASY", dt=1.0/30.0, seed=42)
        res = sim.step()

        # Resolution check
        frame = res["frame"]
        self.assertEqual(frame.shape[:2], (480, 640), "Camera resolution must be 640x480")

        # 30 Hz stepping stability
        for _ in range(30):
            step_res = sim.step()
            self.assertFalse(math.isnan(step_res["pointing_err_deg"]))
        self.assertAlmostEqual(sim.dt, 1.0/30.0, places=4)

        # 60 Hz stepping stability
        sim60 = Simulator(preset_name="EASY", dt=1.0/60.0, seed=42)
        for _ in range(60):
            step_res = sim60.step()
            self.assertFalse(math.isnan(step_res["pointing_err_deg"]))
        self.assertAlmostEqual(sim60.dt, 1.0/60.0, places=4)

    def test_03_configurable_fov(self):
        """PS Requirement: User-defined FOV with default 4 deg x 3 deg."""
        sim = Simulator(preset_name="EASY", seed=42)
        
        # Verify defaults
        self.assertEqual(config.CAMERA_FOV_H_DEG, 4.0)
        self.assertEqual(config.CAMERA_FOV_V_DEG, 3.0)
        self.assertAlmostEqual(config.PIXELS_PER_DEG, 640.0 / 4.0, places=2)

        # Configure new FOV
        h, v = sim.set_fov(6.0, 4.5)
        self.assertEqual(h, 6.0)
        self.assertEqual(v, 4.5)
        self.assertEqual(config.CAMERA_FOV_H_DEG, 6.0)
        self.assertEqual(config.CAMERA_FOV_V_DEG, 4.5)
        self.assertAlmostEqual(config.PIXELS_PER_DEG, 640.0 / 6.0, places=2)

        # Step with new FOV
        res = sim.step()
        self.assertIsNotNone(res)

        # Reset to 4x3
        sim.set_fov(4.0, 3.0)
        self.assertEqual(config.CAMERA_FOV_H_DEG, 4.0)

    def test_04_initial_camera_center(self):
        """PS Requirement: Camera center must initially point to center of virtual screen."""
        from core.gimbal import Gimbal
        from core.sensor import VirtualSensor
        g = Gimbal(start_pan=0.0, start_tilt=0.0)
        self.assertEqual(g.pan, 0.0)
        self.assertEqual(g.tilt, 0.0)

        # When pointing at (0, 0), the camera boresight maps to the virtual screen center (1000, 1000)
        cx, cy = VirtualSensor._canvas_xy(g.pan, g.tilt)
        self.assertEqual((cx, cy), (1000.0, 1000.0))

    def test_05_target_parameters(self):
        """PS Requirement: Target size 5-20 px (default 10x10 square), shapes, multiple targets."""
        sim = Simulator(preset_name="EASY", seed=42)

        # Default size and shape
        self.assertEqual(sim.scene.beacon.shape, "SQUARE")
        self.assertEqual(sim.scene.beacon.size_px, 10)

        # Dynamic update: CIRCLE, 16px, 3 targets
        sim.set_target_params(shape="CIRCLE", size_px=16, count=3, initial="CENTER")
        self.assertEqual(sim.scene.beacon.shape, "CIRCLE")
        self.assertEqual(sim.scene.beacon.size_px, 16)
        self.assertEqual(len(sim.scene.beacons), 3)

        # Dynamic update: SPOT, 8px, 1 target
        sim.set_target_params(shape="SPOT", size_px=8, count=1)
        self.assertEqual(sim.scene.beacon.shape, "SPOT")
        self.assertEqual(sim.scene.beacon.size_px, 8)
        self.assertEqual(len(sim.scene.beacons), 1)

    def test_06_target_initial_position(self):
        """PS Requirement: Initial target position random or user-defined (az, el)."""
        # Center initial position
        sim_center = Simulator(preset_name="EASY", seed=42)
        sim_center.set_target_params(initial="CENTER")
        # At center (t=0), azimuth and elevation are approximately 0
        az0, el0 = sim_center.scene.beacon.orbit.relative_los_az_el(0.0)
        self.assertAlmostEqual(az0, 0.0, places=2)
        self.assertAlmostEqual(el0, 0.0, places=2)

        # Custom user position: (1.5 deg az, -0.8 deg el)
        sim_custom = Simulator(preset_name="EASY", seed=42)
        sim_custom.set_target_params(initial=(1.5, -0.8))
        az_u, el_u = sim_custom.scene.beacon.orbit.relative_los_az_el(0.0)
        self.assertAlmostEqual(az_u, 1.5, places=2)
        self.assertAlmostEqual(el_u, -0.8, places=2)

    def test_07_motion_profiles(self):
        """PS Requirement: Straight line, circular, figure-8, random, spiral, sinusoidal."""
        profiles = ["straight_line", "circular", "figure_eight", "random", "spiral", "sinusoidal"]
        for p in profiles:
            sim = Simulator(preset_name="EASY", seed=42)
            sim.set_motion_type(p)
            self.assertEqual(sim.scene.beacon.orbit._motion_type, p)
            # Step 10 frames, ensure trajectory is valid
            for _ in range(10):
                res = sim.step()
                self.assertFalse(math.isnan(res["pointing_err_deg"]))
                self.assertFalse(math.isinf(res["pointing_err_deg"]))

    def test_08_gimbal_rate_limits(self):
        """PS Requirement: Default Pan/Tilt 5 deg/s speed limit strictly enforced."""
        sim = Simulator(preset_name="EASY", seed=42)
        self.assertEqual(sim.gimbal.max_pan_deg_s, 5.0)
        self.assertEqual(sim.gimbal.max_tilt_deg_s, 5.0)

        # Command a far-away setpoint to induce maximal slew demand
        for _ in range(30):
            sim.gimbal.command_attitude(sim.gimbal.pan + 20.0, sim.gimbal.tilt + 20.0)
            sim.gimbal.step(sim.dt, sim.disturbance)
            # Gimbal rate must never exceed configured 5.0 deg/s
            self.assertLessEqual(abs(sim.gimbal.v_pan), 5.001)
            self.assertLessEqual(abs(sim.gimbal.v_tilt), 5.001)

        # Custom gimbal limit update
        sim.set_gimbal_limits(max_pan=8.0, max_tilt=7.0)
        self.assertEqual(sim.gimbal.max_pan_deg_s, 8.0)
        self.assertEqual(sim.gimbal.max_tilt_deg_s, 7.0)
        for _ in range(30):
            sim.gimbal.command_attitude(sim.gimbal.pan + 20.0, sim.gimbal.tilt + 20.0)
            sim.gimbal.step(sim.dt, sim.disturbance)
            self.assertLessEqual(abs(sim.gimbal.v_pan), 8.001)
            self.assertLessEqual(abs(sim.gimbal.v_tilt), 7.001)

    def test_09_platform_modes_and_vacuum_gating(self):
        """PS Requirement: SAT-SAT (vacuum path) vs UAV-SAT/UAV-UAV."""
        sim = Simulator(preset_name="EASY", seed=42)

        # SAT-SAT: Vacuum path disallows terrestrial weather
        sim.set_platform_mode("SATELLITE_SATELLITE")
        self.assertFalse(sim.atmosphere_allowed)
        self.assertEqual(sim.atmosphere_name, "CLEAR")

        # Attempt to set RAIN on SAT-SAT -> must be rejected / kept CLEAR
        sim.set_atmosphere("RAIN")
        self.assertEqual(sim.atmosphere_name, "CLEAR", "Weather must be disallowed in SAT-SAT vacuum link")

        # UAV-SAT: Atmospheric link allows weather
        sim.set_platform_mode("UAV_SATELLITE")
        self.assertTrue(sim.atmosphere_allowed)
        sim.set_atmosphere("RAIN")
        self.assertEqual(sim.atmosphere_name, "RAIN")

        # UAV-UAV: Allows fog
        sim.set_platform_mode("UAV_UAV")
        self.assertTrue(sim.atmosphere_allowed)
        sim.set_atmosphere("FOG")
        self.assertEqual(sim.atmosphere_name, "FOG")

    def test_10_disturbances_and_noise_types(self):
        """PS Requirement: Gaussian, Salt & Pepper, Poisson noise, camera jitter."""
        sim = Simulator(preset_name="EASY", seed=42)

        # Test noise toggling
        sim.set_noise_types(["salt_pepper", "poisson"])
        self.assertIn("salt_pepper", sim.disturbance.noise_types)
        self.assertIn("poisson", sim.disturbance.noise_types)

        # Step with noises active
        res = sim.step()
        self.assertIsNotNone(res)
        self.assertEqual(res["frame"].shape[:2], (480, 640))

        # Test jitter & vibration injection
        sim.disturbance.vibration = 25
        sim.disturbance.jerk_prob = 5
        j_p, j_t = sim.disturbance.platform_disturbance(0.1)
        self.assertIsInstance(j_p, float)
        self.assertIsInstance(j_t, float)

    def test_11_multi_target_locking_and_handover(self):
        """PS Requirement Item 8: Multi-Target (1 to 5) tracking lock stability and handover."""
        # 1. Verify stable locking across 1, 3, 5 targets
        for count in [1, 3, 5]:
            sim = Simulator(preset_name="MODERATE", seed=42)
            sim.scene.set_target_params(count=count)
            states = [sim.step()["state"] for _ in range(80)]
            locked_count = sum(1 for s in states if s == "LOCKED")
            self.assertGreaterEqual(locked_count, 60, f"Failed locking with count={count}")
            self.assertEqual(states[-1], "LOCKED")

        # 2. Verify clean target handover between multiple targets
        sim = Simulator(preset_name="MODERATE", seed=42)
        sim.scene.set_target_params(count=3)
        # Lock on TARGET-01
        for _ in range(40):
            sim.step()
        self.assertEqual(sim.tracker.state, "LOCKED")
        self.assertEqual(sim.scene.beacon.target_id, "TARGET-01")

        # Handover to TARGET-02
        idx, tid = sim.set_primary_target(1)
        self.assertEqual(tid, "TARGET-02")
        for _ in range(40):
            sim.step()
        self.assertEqual(sim.tracker.state, "LOCKED")
        self.assertEqual(sim.scene.beacon.target_id, "TARGET-02")


if __name__ == "__main__":
    unittest.main()

