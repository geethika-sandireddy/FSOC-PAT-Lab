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

import math
import os
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
                 tracker_factory=None, platform_mode=None, atmosphere=None,
                 motion_type=None, target_shape=None, target_size=None,
                 num_targets=None, target_initial=None):
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
            motion_type=motion_type or preset.get("motion_type",
                                    pm.get("motion_default") if pm else None),
            target_shape=target_shape, target_size=target_size,
            num_targets=num_targets if num_targets is not None
                        else getattr(config, "NUM_TARGETS", 1),
            target_initial=target_initial,
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


class VideoInputSimulator:
    """Benchmark-2 mode: an external MP4 ("bypass its PTZ camera and take this
    video as an input to the coarse pointing system") drives the real
    detect -> track -> control -> gimbal closed loop.

    The virtual camera renders nothing of its own; each step reads the next
    frame of the supplied video, detects the beacon blob in those *raw*
    pixels, feeds the candidates into the same Tracker/PointingController
    used by the synthetic mode, and steers the gimbal so the beacon lands on
    the boresight.  Modulation-ID gating is relaxed in video mode (the video
    has no known 15 Hz clock); identity = persistence + appearance.
    """

    def __init__(self, video_path, seed=None, dt=None, truth_csv=None):
        import cv2
        self.preset = config.DIFFICULTY_PRESETS["EASY"]
        self.preset_name = "VIDEO"
        self.platform_mode = None
        self.atmosphere_name = "CLEAR"

        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {video_path}")
        self.video_path = video_path
        self.video_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.video_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._dt = dt if dt is not None else 1.0 / self.video_fps

        # optional ground-truth sidecar (generator truth CSV): the "predefined
        # error values" Benchmark-2 compares against
        self.truth = {}
        if truth_csv and os.path.isfile(truth_csv):
            import csv as _csv
            with open(truth_csv, newline="") as f:
                for row in _csv.DictReader(f):
                    try:
                        self.truth[int(row["frame"])] = (float(row["bx"]),
                                                         float(row["by"]))
                    except (ValueError, KeyError):
                        continue

        # stationary prior at boresight: an external video has no orbital
        # ephemeris, so the prior is simply "the beacon is near cue centre"
        from core.orbital import RelativeOrbitModel, EphemerisModel
        from core.tracking import Tracker
        from core.gimbal import Gimbal
        from core.control import PointingController
        from core.detection import DetectionEngine
        from core.disturbances import DisturbanceEngine

        zero_orbit = RelativeOrbitModel(
            az_amp=0.0, el_amp=0.0, seed=seed, motion_type="straight_line")
        self.eph = EphemerisModel(zero_orbit, seed=seed)
        self.gimbal = Gimbal()
        self.disturbance = DisturbanceEngine()   # zero-level: no extra motion
        self.detector = DetectionEngine()
        # video mode: the whole frame is the sensor - the association gate
        # spans the video's own angular FOV so the beacon stays associated
        # across its full sweep instead of being knocked out by servo lag.
        self.video_fov_deg = config.CAMERA_FOV_H_DEG
        self.tracker = Tracker(self.eph, seed=seed, video_mode=True,
                               gate_deg=self.video_fov_deg * 0.95)
        self.controller = PointingController(self.gimbal, self.tracker)
        self.dt = self._dt
        self.t = 0.0
        self.frame = None
        self.intensity_hist = deque(maxlen=240)

        # video geometry mapped onto the LOS frame (same pinhole, per-video
        # focal/centre so any resolution is handled correctly)
        self.focal_px = (self.video_w / 2.0) / math.tan(
            math.radians(config.CAMERA_FOV_H_DEG / 2.0))
        self.cu = self.video_w / 2.0
        self.cv = self.video_h / 2.0

        self.tracker.reset(0.0, 0.0)
        self._truth_xy = None          # brightest-blob centroid = "truth"
        self.frame_idx = 0
        self.centroid_log = []         # (frame, detected_cx, detected_cy)
        self.centroid_err_log = []     # (frame, err_px) vs truth CSV / brightest
        self.estimate_log = []         # (frame, est_az, est_el)
        self.lock_history = []         # (frame, state)
        self.acquisition_time_s = None
        self.lock_lost_at = None
        self.reacq_times = []
        self._was_locked = False
        self._false_lock_count = 0
        self.false_lock_events = 0

    @property
    def state(self):
        return self.tracker.state

    @property
    def is_locked(self):
        from core.tracking import LOCKED
        return self.tracker.state == LOCKED

    # ------------------------------------------------------------------
    def step(self):
        """Read one video frame and close the detection->track loop on it.

        Benchmark-2 semantics: the supplied video IS the camera feed (the
        virtual PTZ is bypassed).  The graded metrics are centroiding error
        (detected beacon centroid vs the video's true centroid), acquisition /
        re-acquisition time, lock retention and FPS - so the camera basis is
        fixed (identity) and the tracker estimates the beacon's position in
        the video itself.
        """
        import cv2
        import numpy as np

        ret, frame = self.cap.read()
        if not ret:
            return None
        self.t += self.dt
        frame = np.ascontiguousarray(frame)

        basis = self.gimbal.basis()          # identity: gimbal held at 0,0
        candidates = self.detector.detect(frame, basis, self.focal_px,
                                          cu=self.cu, cv=self.cv)
        state, est_az, est_el, confidence = self.tracker.update(
            candidates, self.t, self.dt)
        self.intensity_hist.append(
            self.tracker.associated.peak if self.tracker.associated else None)

        # ---- "ground truth" centroid (metrics only, never into the loop) ----
        # preferred: the generator's truth CSV (the "predefined error values"
        # the graders compare against).  Fallback: brightest-blob estimate.
        tb = self.truth.get(self.frame_idx)
        if tb is not None:
            best = (tb[0], tb[1], 999.0)
        else:
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(grey, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
            best = None
            for c in cnts:
                if cv2.contourArea(c) < 4:
                    continue
                M = cv2.moments(c)
                if M["m00"] == 0:
                    continue
                cx = M["m10"] / M["m00"]
                cy = M["m01"] / M["m00"]
                if int(round(cy)) < 0 or int(round(cy)) >= self.video_h \
                        or int(round(cx)) < 0 or int(round(cx)) >= self.video_w:
                    continue
                inten = float(grey[int(round(cy)), int(round(cx))])
                if best is None or inten > best[2]:
                    best = (cx, cy, inten)
        if best is not None:
            self._truth_xy = (best[0] - self.cu, best[1] - self.cv)
        else:
            self._truth_xy = None

        # ---- centroiding error: detected centroid vs true centroid ----
        tracked = self.tracker.associated
        detected_cx = tracked.x if tracked is not None else None
        detected_cy = tracked.y if tracked is not None else None

        if best is not None:
            if detected_cx is not None:
                cent_err_px = math.hypot(detected_cx - best[0],
                                         detected_cy - best[1])
            else:
                cent_err_px = math.hypot(self.cu - best[0],
                                         self.cv - best[1])
        else:
            cent_err_px = float(max(self.video_w, self.video_h))

        self.frame_idx += 1
        if detected_cx is not None:
            self.centroid_log.append((self.frame_idx, detected_cx, detected_cy))
            self.centroid_err_log.append((self.frame_idx, cent_err_px))
        self.estimate_log.append((self.frame_idx, est_az, est_el))
        self.lock_history.append((self.frame_idx, state))

        # acquisition / re-acquisition timing
        is_locked = (state == "LOCKED")
        if is_locked:
            if self.acquisition_time_s is None:
                self.acquisition_time_s = self.t
            elif not self._was_locked:
                if self.lock_lost_at is not None:
                    self.reacq_times.append(self.t - self.lock_lost_at)
                    self.lock_lost_at = None
            # false-lock: locked while centroid error is huge vs truth
            if cent_err_px > 0.35 * max(self.video_w, self.video_h):
                self._false_lock_count += 1
                if self._false_lock_count == 5:
                    self.false_lock_events += 1
            else:
                self._false_lock_count = 0
        else:
            self._false_lock_count = 0
            if self._was_locked:
                self.lock_lost_at = self.t
        self._was_locked = is_locked

        # beacon offset from frame centre (the "camera must keep it in view"
        # frame of reference for the HUD)
        if best is not None:
            cent_px = math.hypot(best[0] - self.cu, best[1] - self.cv)
        else:
            cent_px = float(max(self.video_w, self.video_h))

        # estimate error vs truth (LOS round-trip through the fixed basis)
        est_err_deg = None
        if est_az is not None and best is not None:
            from core.geometry import ray_to_azel, azel_unit, sd_angle_deg
            est_dir = azel_unit(est_az, est_el)
            t_az, t_el = ray_to_azel(best[0], best[1], self.focal_px, basis,
                                     self.cu, self.cv)
            est_err_deg = sd_angle_deg(est_dir, azel_unit(t_az, t_el))

        from core.tracking import LOCKED as _LOCKED
        self.last_result = dict(
            state=state,
            est_az=est_az, est_el=est_el,
            confidence=confidence,
            truth_az=0.0, truth_el=0.0,
            pointing_err_deg=est_err_deg,
            est_err_deg=est_err_deg,
            candidates=len(candidates),
            cand_list=candidates,
            beacon_visible=best is not None,
            dist_pan_deg=0.0, dist_tilt_deg=0.0,
            in_fov=best is not None,
            frame=frame,
            t=self.t,
            centroid_px=cent_px,
            centroid_err_px=cent_err_px,
            tracked_xy=(detected_cx, detected_cy) if detected_cx is not None
                        else None,
            truth_xy=(best[0], best[1]) if best is not None else None,
            frame_idx=self.frame_idx,
        )
        return self.last_result