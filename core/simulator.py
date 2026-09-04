"""
core/simulator.py
-----------------
The mission pipeline, wired end-to-end (used by the GUI and the headless
stress-test harness alike):

    Scene3D --(gimbal pose)--> VirtualSensor --(disturbances)-->
    frame --DetectionEngine--> candidates --Tracker(state machine)-->
    estimate --PointingController--> gimbal set-point --(physics)-->

All information that flows into detection/control comes from either the
rendered (and disturbed) pixels or the ephemeris prior - never ground truth.
"""

import config
from collections import deque
from core.geometry import azel_unit, sd_angle_deg
from core.scene import Scene3D
from core.gimbal import Gimbal
from core.sensor import VirtualSensor
from core.disturbances import DisturbanceEngine
from core.detection import DetectionEngine
from core.tracking import Tracker, SEARCHING, COASTING, LOCKED
from core.control import PointingController
from core.orbital import EphemerisModel


class Simulator:
    def __init__(self, preset_name="EASY", seed=None, dt=1.0 / config.FPS,
                 tracker_factory=None, platform_mode=None, atmosphere=None):
        preset = config.DIFFICULTY_PRESETS.get(preset_name, config.DIFFICULTY_PRESETS["EASY"])
        self.preset_name = preset_name
        self.preset = preset
        self.platform_mode = platform_mode
        self.atmosphere_name = atmosphere

        # Merge platform mode defaults with preset (preset overrides)
        pm = None
        if platform_mode:
            from core.platforms import PLATFORM_MODES
            pm = PLATFORM_MODES.get(platform_mode)
        if pm:
            dist = {**pm.get("disturbances", {}), **{k: v for k, v in preset.items()
                    if k in ("turbulence", "vibration", "sensor_noise", "jerk_prob", "beacon_fade")}}
        else:
            dist = preset

        self.scene = Scene3D(
            az_amp=preset["az_amp"], el_amp=preset["el_amp"],
            speed=preset["speed"],
            distractors=preset["distractors"],
            obstacles=preset["obstacles"], seed=seed,
            motion_type=preset.get("motion_type",
                                   pm.get("motion_default") if pm else None),
        )
        self.eph = EphemerisModel(self.scene.orbit, seed=seed)
        self.gimbal = Gimbal()
        self.sensor = VirtualSensor()
        self.disturbance = DisturbanceEngine(
            turbulence=dist.get("turbulence", 0),
            vibration=dist.get("vibration", 0),
            sensor_noise=dist.get("sensor_noise", 0),
            jerk_prob=dist.get("jerk_prob", 0),
            beacon_fade=dist.get("beacon_fade", 0),
            seed=seed,
        )
        self.disturbance.noise_types = preset.get("noise_types",
                                                   pm.get("noise_types", ["gaussian"]) if pm
                                                   else ["gaussian"])
        # Atmospheric condition engine
        from core.atmosphere import AtmosphereEngine
        atm = atmosphere or (pm.get("atmosphere", "CLEAR") if pm else "CLEAR")
        self.atmosphere = AtmosphereEngine(condition=atm, seed=seed)
        self.atmosphere_name = atm
        self.detector = DetectionEngine()
        if tracker_factory is None:
            self.tracker = Tracker(self.eph, seed=seed)
        else:
            self.tracker = tracker_factory(self.eph, seed=seed)
        self.controller = PointingController(self.gimbal, self.tracker)
        self.dt = dt
        self.t = 0.0
        self.frame = None
        # brightness history of the associated object (for the scope HUD)
        self.intensity_hist = deque(maxlen=240)

        # coarse pre-aim toward the ephemeris prediction
        paz, pel = self.eph.predict_az_el(0.0)
        self.gimbal.pan, self.gimbal.tilt = paz, pel
        self.gimbal.pan_cmd, self.gimbal.tilt_cmd = paz, pel
        self.tracker.reset(paz, pel)

    # ------------------------------------------------------------------
    def set_preset(self, preset_name, seed=None):
        self.__init__(preset_name, seed=seed, dt=self.dt)

    # ------------------------------------------------------------------
    @property
    def state(self):
        return self.tracker.state

    @property
    def is_locked(self):
        return self.tracker.state == LOCKED

    # ------------------------------------------------------------------
    def step(self):
        """Advance one simulation frame.  Returns a dict of measurements the
        caller turns into metrics or HUD + the (possibly disturbed) frame."""
        dt = self.dt
        self.scene.advance(dt)
        self.t += dt

        basis = self.gimbal.basis()
        frame = self.sensor.render(self.scene, self.gimbal, config.FOCAL_PX,
                                   disturbance=self.disturbance, dt=dt)
        # Apply atmospheric condition effects (haze, fog, rain, low light)
        if self.atmosphere_name != "CLEAR":
            frame = self.atmosphere.apply(frame)

        candidates = self.detector.detect(frame, basis, config.FOCAL_PX)

        state, est_az, est_el, confidence = self.tracker.update(candidates, self.t, dt)
        assoc = self.tracker.associated
        self.intensity_hist.append(assoc.peak if assoc is not None else None)

        pan, tilt = self.controller.compute_setpoint(self.t, dt)
        self.gimbal.command_attitude(pan, tilt)
        self.gimbal.step(dt, self.disturbance)

        # ----- ground-truth view (metrics only, never into the pipeline) -----
        truth_az = self.scene.beacon.az_deg
        truth_el = self.scene.beacon.el_deg
        truth_dir = azel_unit(truth_az, truth_el)
        enc_dir = azel_unit(self.gimbal.pan, self.gimbal.tilt)
        pointing_err_deg = sd_angle_deg(enc_dir, truth_dir)

        # estimate error (tracker LOS estimate vs truth)
        if est_az is not None and est_el is not None:
            est_dir = azel_unit(est_az, est_el)
            est_err_deg = sd_angle_deg(est_dir, truth_dir)
        else:
            est_err_deg = None

        occ = 0.0
        for o in self.scene.obstacles:
            occ = max(occ, o.crossing(self.scene.time))
        beacon_visible = occ < 0.55

        # is the beacon within the sensor FOV (as projected)?
        import math
        dpan = min(abs(truth_az - self.gimbal.pan), 360 - abs(truth_az - self.gimbal.pan))
        dtilt = min(abs(truth_el - self.gimbal.tilt), 360 - abs(truth_el - self.gimbal.tilt))

        self.last_result = dict(
            state=state,
            est_az=est_az, est_el=est_el,
            confidence=confidence,
            truth_az=truth_az, truth_el=truth_el,
            pointing_err_deg=pointing_err_deg,
            est_err_deg=est_err_deg,
            candidates=len(candidates),
            cand_list=candidates,
            beacon_visible=beacon_visible,
            dist_pan_deg=dpan, dist_tilt_deg=dtilt,
            in_fov=(dpan < config.HFOV_DEG / 2.0 + 0.1 and
                    dtilt < config.VFOV_DEG / 2.0 + 0.1),
            frame=frame,
            t=self.t,
        )
        return self.last_result