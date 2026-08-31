"""
metrics/performance.py
----------------------
The "Performance Log" mandatory deliverable plus live on-screen statistics.

Tracks, frame by frame:
  * pointing (boresight) error - degrees, the metric a laser link actually
    cares about,
  * tracker estimate error (LOS estimate vs truth),
  * acquisition time, reacquisition times,
  * lock retention (and visibility-normalised retention),
  * false-lock events - a locked track whose estimate departs far from the
    true beacon while it is visible & in FOV (should be ~0),
  * FPS, simulation duration.

Metrics are written to a CSV on exit/demand and aggregated for the stress
test.  Nothing here informs the control loop; it is pure measurement.
"""

import csv
import math
import os
import time

import config


USE_WALL_CLOCK = False  # robustness: release-mode FPS uses ticks if False


class PerformanceTracker:
    def __init__(self):
        self.start_wall = time.time()
        self.frame_count = 0
        self.acquisition_time_s = None
        self.locked_frames = 0
        self.visible_frames = 0
        self.locked_visible_frames = 0
        self.errors_deg = []           # boresight (beam) error while locked
        self.est_errors_deg = []       # estimate error while locked
        self.fps_samples = []
        self.last_tick = 0.0
        self._tick_start = time.time()
        self.was_locked = False
        self.lock_lost_at = None
        self.reacquisition_times = []
        self.lock_events = 0
        self.false_lock_events = 0
        self._false_lock_frames = 0
        self.tracking_available_frames = 0
        self.state_time = {}

    # ------------------------------------------------------------------
    def record_frame(self, sim):
        """sim: core.simulator.Simulator (just stepped)."""
        self.frame_count += 1
        r = sim.last_result

        # FPS measurement
        now = time.time()
        dt_w = now - self._tick_start
        self._tick_start = now
        if dt_w > 0:
            self.fps_samples.append(min(400.0, 1.0 / dt_w))
            rolling = self.fps_samples[-200:]
            self.last_tick = sum(rolling) / len(rolling)

        state = r["state"]
        self.state_time[state] = self.state_time.get(state, 0) + 1

        is_locked = state == "LOCKED"
        visible = r["beacon_visible"]

        if visible:
            self.visible_frames += 1
        if is_locked:
            self.locked_frames += 1
            self.tracking_available_frames += 1
            if visible:
                self.locked_visible_frames += 1
            if self.acquisition_time_s is None:
                self.acquisition_time_s = now - self.start_wall
                self.lock_events += 1
            elif not self.was_locked:
                if self.lock_events == 0:
                    self.acquisition_time_s = now - self.start_wall
                self.lock_events += 1
                if self.lock_lost_at is not None:
                    self.reacquisition_times.append(now - self.lock_lost_at)
                    self.lock_lost_at = None

            err = r["pointing_err_deg"]
            if err is not None:
                self.errors_deg.append(err)
            if r["est_err_deg"] is not None:
                self.est_errors_deg.append(r["est_err_deg"])

            # false-lock monitor: locked onto something that is NOT the beacon
            if visible and r["in_fov"]:
                if r["est_err_deg"] is not None and r["est_err_deg"] > 0.35:
                    self._false_lock_frames += 1
                else:
                    if self._false_lock_frames >= 5:
                        self.false_lock_events += 1
                    self._false_lock_frames = 0
        else:
            if self.was_locked:
                self.lock_lost_at = now

        self.was_locked = is_locked

    # ------------------------------------------------------------------
    def live_stats(self):
        n = len(self.errors_deg)
        mean_err = sum(self.errors_deg) / n if n else None
        max_err = max(self.errors_deg) if n else None
        rms = math.sqrt(sum(e * e for e in self.errors_deg) / n) if n else None
        retention_total = (self.locked_frames / self.frame_count * 100) if self.frame_count else 0.0
        retention_vis = (self.locked_visible_frames / self.visible_frames * 100) if self.visible_frames else 0.0
        return dict(
            fps=self.last_tick,
            mean_err_deg=mean_err,
            max_err_deg=max_err,
            rms_err_deg=rms,
            acquisition_time_s=self.acquisition_time_s,
            retention_total_pct=retention_total,
            retention_visible_pct=retention_vis,
            reacquisition_count=len(self.reacquisition_times),
            last_reacq_s=self.reacquisition_times[-1] if self.reacquisition_times else None,
            false_lock_events=self.false_lock_events,
            lock_events=self.lock_events,
            path="",
        )

    # ------------------------------------------------------------------
    def write_log(self, path=None, extra_info=None):
        """CSV performance report (mandatory deliverable)."""
        if path is None:
            os.makedirs(config.LOG_DIR, exist_ok=True)
            path = os.path.join(config.LOG_DIR, f"run_{int(time.time())}.csv")
        stats = self.live_stats()
        duration = time.time() - self.start_wall

        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "value"])
            if extra_info:
                for k, v in extra_info.items():
                    w.writerow([k, v])
            w.writerow(["simulation_duration_s", round(duration, 2)])
            w.writerow(["total_frames", self.frame_count])
            w.writerow(["average_fps", round(stats["fps"], 2)])
            w.writerow(["acquisition_time_s", round(stats["acquisition_time_s"], 3)
                        if stats["acquisition_time_s"] is not None else "never_locked"])
            w.writerow(["average_pointing_error_deg", round(stats["mean_err_deg"], 4)
                        if stats["mean_err_deg"] is not None else "n/a"])
            w.writerow(["rms_pointing_error_deg", round(stats["rms_err_deg"], 4)
                        if stats["rms_err_deg"] is not None else "n/a"])
            w.writerow(["max_pointing_error_deg", round(stats["max_err_deg"], 4)
                        if stats["max_err_deg"] is not None else "n/a"])
            w.writerow(["lock_retention_total_pct", round(stats["retention_total_pct"], 2)])
            w.writerow(["lock_retention_visible_pct", round(stats["retention_visible_pct"], 2)])
            w.writerow(["lock_events", self.lock_events])
            w.writerow(["reacquisition_events", stats["reacquisition_count"]])
            w.writerow(["false_lock_events", self.false_lock_events])
            w.writerow(["states", {k: round(v / max(1, self.frame_count) * 100, 1)
                                   for k, v in self.state_time.items()}])
            return path