"""
main.py
-------
The FSOC-PAT mission console (SIH 2026 · PS 26169).

  * left  : virtual camera HUD - the disturbed sensor pixels, reticle,
            detected candidates, active track brackets, acquisition badge;
  * bottom: live telemetry table + brightness-modulation scope (proves the
            15 Hz beacon ID), error strip;
  * right : preset chips, relative-LOS sky plot, KPI cards, four disturbance
            sliders, pointing-error sparkline, PAUSE / RESET / SCREENSHOT.

Keyboard:  1-5  pick difficulty preset
           SPACE pause/resume     R reset run (new random seed)
           S    screenshot -> logs\\shot_*.png     V toggle fov grid
           ESC  quit

Headless self-test:   python main.py --frames 200 --preset HARD
"""

import argparse
import math
import os
import statistics
import sys
import time
from collections import deque

import pygame
import numpy as np

import config
from core.simulator import Simulator
from core.geometry import azel_unit, sd_angle_deg, project_point_into_camera
from core.platforms import atmosphere_allowed, disturbance_kind_label
from metrics.performance import PerformanceTracker
from ui import theme as T
from ui import widgets as W
from ui import view3d


APP_W, APP_H = 1600, 900
CAM_W, CAM_H = config.CAM_VIEW_W, config.CAM_VIEW_H
CAM_SCALE = 1.6
DISPLAY_CAP = 60

# states that hold a lock on the true target (a lock is still a lock even
# when confidence drops into the DEGRADED band); the HUD treats these as
# "TRACKING" so a degraded lock never renders as search/coast.
LOCKED_STATES = ("LOCKED", "DEGRADED_LOCK")


class App:
    def __init__(self, preset="EASY", seed=None, fullscreen=False,
                 platform_mode=None, atmosphere=None,
                 motion_type=None, target_shape=None, target_size=None,
                 num_targets=None, target_initial=None,
                 video_path=None, video_seed=None):
        pygame.init()
        flags = pygame.FULLSCREEN | pygame.SCALED if fullscreen else 0
        self.screen = pygame.display.set_mode((APP_W, APP_H),
                                              flags=(flags if fullscreen else 0))
        pygame.display.set_caption("FSOC-PAT Coarse-Pointing Tracker  ·  SIH 2026 PS 26169")
        self.clock = pygame.time.Clock()

        self.preset = preset
        self.platform_mode = platform_mode or "SATELLITE_SATELLITE"
        self.atmosphere = atmosphere or "CLEAR"
        from core.platforms import atmosphere_allowed
        if not atmosphere_allowed(self.platform_mode) and self.atmosphere != "CLEAR":
            self.atmosphere = "CLEAR"
        self.motion_override = motion_type
        self.shape_override = target_shape
        self.size_override = target_size
        self.targets_override = num_targets
        self.initial_override = target_initial
        self.video_path = video_path
        self.video_done = False
        self.video_seed = video_seed
        if video_path:
            from core.simulator import VideoInputSimulator
            truth = os.path.splitext(video_path)[0] + "_truth.csv"
            self.sim = VideoInputSimulator(
                video_path, seed=video_seed,
                truth_csv=truth if os.path.isfile(truth) else None)
            self.video_mode = True
        else:
            self.sim = Simulator(preset_name=preset, seed=seed,
                                 platform_mode=self.platform_mode,
                                 atmosphere=self.atmosphere,
                                 motion_type=self.motion_override,
                                 target_shape=self.shape_override,
                                 target_size=self.size_override,
                                 num_targets=self.targets_override,
                                 target_initial=self.initial_override)
            self.video_mode = False
        self.perf = PerformanceTracker()
        self.paused = False
        self.show_fov_grid = True
        self.eph_pred_az = None
        self.eph_pred_el = None
        # presentation modes
        self.show_gt = False        # ground-truth / evaluation-only overlays
        self.show_diag = False      # expandable diagnostics section
        self.compare = self._load_compare()   # baseline-vs-adaptive benchmark

        self.error_spark = deque(maxlen=1800)
        self.sliders = {
            "turbulence": W.Slider((1296, 600, 282, 22), "TURBULENCE",
                                   self.sim.preset.get("turbulence", 0), T.C.PURPLE,
                                   enabled=atmosphere_allowed(self.platform_mode)),
            "vibration": W.Slider((1296, 628, 282, 22), "VIBRATION",
                                  self.sim.preset.get("vibration", 0), T.C.AMBER),
            "sensor_noise": W.Slider((1296, 656, 282, 22), "SENSOR NOISE",
                                     self.sim.preset.get("sensor_noise", 0), T.C.RED),
            "jerk_prob": W.Slider((1296, 684, 282, 22), "JERK PROB",
                                  self.sim.preset.get("jerk_prob", 0), T.C.CYAN),
            "beacon_fade": W.Slider((1296, 712, 282, 22), "BEACON FADE",
                                    self.sim.preset.get("beacon_fade", 0), T.C.AMBER_DIM),
        }
        self.chips = {}
        # scenario chips live in the top header, right of the title
        xs = 320
        for name in config.PRESET_ORDER:
            self.chips[name] = W.Chip((xs, 12, 72, 26), name, T.C.CYAN)
            xs += 78
        # platform-mode chips (PS 26169: Sat-Sat, UAV-Sat, UAV-UAV) + atmosphere
        self.platform_chips = {}
        pm_x = 650
        for pm in ["SATELLITE_SATELLITE", "UAV_SATELLITE", "UAV_UAV"]:
            label = {"SATELLITE_SATELLITE": "SAT-SAT",
                     "UAV_SATELLITE": "UAV-SAT",
                     "UAV_UAV": "UAV-UAV"}[pm]
            self.platform_chips[pm] = W.Chip((pm_x, 12, 72, 26), label, T.C.GREEN)
            pm_x += 78
        self.atmos_chips = {}
        at_x = 990
        for atm in ["CLEAR", "HAZE", "FOG", "RAIN", "LOW_LIGHT"]:
            self.atmos_chips[atm] = W.Chip((at_x, 12, 66, 26), atm, T.C.AMBER)
            at_x += 72
        self.buttons = {
            "PAUSE": W.Button((1296, 772, 92, 30), "PAUSE", T.C.AMBER),
            "RESET": W.Button((1396, 772, 92, 30), "RESET", T.C.CYAN),
            "SHOT": W.Button((1296, 806, 92, 30), "SHOT", T.C.GREEN),
            "GT": W.Button((1396, 806, 92, 30), "GT OFF", T.C.PURPLE),
            "DIAG": W.Button((1296, 840, 92, 30), "DIAGNOSTICS ›", T.C.TEXT_FAINT),
            "LOAD_VIDEO": W.Button((1396, 840, 196, 30), "LOAD MP4 ▶", T.C.AMBER),
        }
        self._screenshot_n = 0

        # chunky HUD sprites
        self._hud_ready = False
        self._cam_surf = None
        self._ret = pygame.Rect(0, 0, CAM_W, CAM_H)

    # ------------------------------------------------------------------
    def _atmosphere_allowed(self):
        from core.platforms import atmosphere_allowed
        return atmosphere_allowed(self.platform_mode)

    def _platform_label(self):
        return {"SATELLITE_SATELLITE": "SAT-SAT",
                "UAV_SATELLITE": "UAV-SAT",
                "UAV_UAV": "UAV-UAV"}.get(self.platform_mode, self.platform_mode)

    def _platform_atm_default(self):
        from core.platforms import PLATFORM_MODES
        pm = PLATFORM_MODES.get(self.platform_mode, {})
        return pm.get("atmosphere", "CLEAR")

    def _select_platform(self, pm):
        """Switch platform mode, re-deriving the atmosphere so the scenario
        gate is respected immediately (SAT-SAT drops to CLEAR; a UAV link
        picks up the platform's own default weather)."""
        self.platform_mode = pm
        from core.platforms import atmosphere_allowed
        if not atmosphere_allowed(pm):
            self.atmosphere = "CLEAR"
        elif self.atmosphere == "CLEAR":
            self.atmosphere = self._platform_atm_default()
        self.sliders["turbulence"].enabled = atmosphere_allowed(pm)
        self._reset()

    def sync_sliders(self):
        for key, s in self.sliders.items():
            s.value = self.sim.disturbance.__getattribute__(key)

    def apply_sliders(self):
        d = self.sim.disturbance
        if self.sliders["turbulence"].enabled:
            d.turbulence = int(self.sliders["turbulence"].value)
        else:
            d.turbulence = 0
        d.vibration = int(self.sliders["vibration"].value)
        d.sensor_noise = int(self.sliders["sensor_noise"].value)
        d.jerk_prob = int(self.sliders["jerk_prob"].value)
        d.beacon_fade = int(self.sliders["beacon_fade"].value)

    # ------------------------------------------------------------------
    def run(self):
        running = True
        while running:
            dt_w = self.clock.tick(DISPLAY_CAP) / 1000.0
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    running = self._key(ev.key)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    self._mouse_down(ev.pos, ev.button)
                elif ev.type == pygame.MOUSEBUTTONUP:
                    for s in self.sliders.values():
                        s.dragging = False
                elif ev.type == pygame.MOUSEMOTION:
                    self._mouse_move(ev.pos, ev.buttons)

            if not self.paused and not self.video_done:
                res = self.sim.step()
                if res is None:           # video ended
                    self.video_done = True
                    self._draw()
                    pygame.display.flip()
                    break
                self.perf.record_frame(self.sim)
                if res["state"] in LOCKED_STATES:
                    self.error_spark.append(res["pointing_err_deg"])
                # synthetic-ephemeris prediction at current time (coarse prior)
                self.eph_pred_az, self.eph_pred_el = self.sim.eph.predict_az_el(res["t"])
            self.apply_sliders()
            self._draw()
            pygame.display.flip()
        self._final_report()
        pygame.quit()

    # -------------------------------------------------------------- events
    def _key(self, key):
        if pygame.K_ESCAPE == key:
            return False
        if pygame.K_SPACE == key:
            self.paused = not self.paused
            self.buttons["PAUSE"].label = "RESUME" if self.paused else "PAUSE"
        elif pygame.K_r == key:
            self._reset()
        elif pygame.K_s == key:
            self._screenshot()
        elif pygame.K_l == key:
            self._load_video()
        elif pygame.K_v == key:
            self.show_fov_grid = not self.show_fov_grid
        elif pygame.K_f == key:
            try:
                pygame.display.toggle_fullscreen()
            except Exception:
                pass
        elif pygame.K_1 <= key <= pygame.K_5:
            name = config.PRESET_ORDER[key - pygame.K_1]
            self.preset = name
            self._reset(name)
        elif pygame.K_6 <= key <= pygame.K_8:
            pm = list(self.platform_chips.keys())[key - pygame.K_6]
            if pm != self.platform_mode:
                self._select_platform(pm)
        elif pygame.K_a == key:
            allowed = [n for n in self.atmos_chips if n == "CLEAR" or self._atmosphere_allowed()]
            if allowed:
                idx = (allowed.index(self.atmosphere) + 1) % len(allowed)
                self.atmosphere = allowed[idx]
                self._reset()
        return True

    def _mouse_down(self, pos, button):
        for name, b in self.buttons.items():
            if button == 1 and b.hit(pos):
                if name == "PAUSE":
                    self.paused = not self.paused
                    b.label = "RESUME" if self.paused else "PAUSE"
                elif name == "RESET":
                    self._reset()
                elif name == "SHOT":
                    self._screenshot()
                elif name == "GT":
                    self.show_gt = not self.show_gt
                    b.label = "GT ON" if self.show_gt else "GT OFF"
                elif name == "DIAG":
                    self.show_diag = not self.show_diag
                    b.label = "DIAGNOSTICS ‹" if self.show_diag else "DIAGNOSTICS ›"
                elif name == "LOAD_VIDEO":
                    self._load_video()
                return
        for name, c in self.chips.items():
            if button == 1 and c.hit(pos):
                self.preset = name
                self._reset(name)
                return
        for name, c in self.platform_chips.items():
            if button == 1 and c.hit(pos):
                self._select_platform(name)
                return
        for name, c in self.atmos_chips.items():
            if button == 1 and c.hit(pos):
                if not self._atmosphere_allowed() and name != "CLEAR":
                    return
                self.atmosphere = name
                self._reset()
                return
        for s in self.sliders.values():
            if button == 1 and s.hit(pos):
                s.dragging = True
                s.drag_to(pos[0])

    def _mouse_move(self, pos, buttons):
        for s in self.sliders.values():
            if s.dragging and buttons[0]:
                s.drag_to(pos[0])

    def _reset(self, name=None):
        if self.video_mode:
            # restart the video from frame 0
            from core.simulator import VideoInputSimulator
            truth = os.path.splitext(self.video_path)[0] + "_truth.csv"
            self.sim = VideoInputSimulator(
                self.video_path, seed=self.video_seed,
                truth_csv=truth if os.path.isfile(truth) else None)
            self.video_done = False
            self.perf = PerformanceTracker()
            self.error_spark.clear()
            self.sync_sliders()
            self.paused = False
            self.buttons["PAUSE"].label = "PAUSE"
            return
        self.sim = Simulator(preset_name=name or self.preset, seed=None,
                             platform_mode=self.platform_mode,
                             atmosphere=self.atmosphere,
                             motion_type=self.motion_override,
                             target_shape=self.shape_override,
                             target_size=self.size_override,
                             num_targets=self.targets_override,
                             target_initial=self.initial_override)
        self.perf = PerformanceTracker()
        self.error_spark.clear()
        self.sync_sliders()
        self.paused = False
        self.buttons["PAUSE"].label = "PAUSE"

    def _screenshot(self):
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self._screenshot_n += 1
        path = os.path.join(config.LOG_DIR, f"shot_{self.preset.lower()}_{self._screenshot_n}.png")
        pygame.image.save(self.screen, path)
        print(f"screenshot -> {path}", flush=True)

    def _load_video(self):
        """Benchmark-2: choose an .mp4 and run it through the real
        coarse-pointing loop (PTZ bypass).  Shows the OS file picker."""
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Load Benchmark-2 video (.mp4)",
                filetypes=[("MP4 video", "*.mp4"),
                           ("Video files", "*.mp4;*.avi"), ("All files", "*.*")])
            root.destroy()
        except Exception as ex:      # no display single-choice fallback
            print(f"file dialog unavailable ({ex}); pass --video path instead")
            return
        if not path:
            return
        self.video_path = path
        from core.simulator import VideoInputSimulator
        truth = os.path.splitext(path)[0] + "_truth.csv"
        try:
            self.sim = VideoInputSimulator(
                path, seed=self.video_seed,
                truth_csv=truth if os.path.isfile(truth) else None)
        except Exception as ex:
            print(f"cannot open video: {ex}")
            return
        self.video_mode = True
        self.video_done = False
        self.preset = "VIDEO"
        self.perf = PerformanceTracker()
        self.error_spark.clear()
        self.sync_sliders()
        self.paused = False
        self.buttons["PAUSE"].label = "PAUSE"
        print(f"video loaded -> {path} "
              f"({self.sim.video_w}x{self.sim.video_h} @ "
              f"{self.sim.video_fps:.1f} fps)")
        # show the first frame immediately
        try:
            res = self.sim.step()
            if res is not None:
                self.perf.record_frame(self.sim)
        except Exception as ex:
            print(f"video step error: {ex}")

    def _final_report(self):
        st = self.perf.live_stats()
        p = os.path.join(config.LOG_DIR, f"run_{int(time.time())}.csv")
        extra = {"preset": self.preset}
        if self.video_mode:
            extra["input_video"] = os.path.basename(self.video_path)
            errs = [e[1] for e in self.sim.centroid_err_log]
            if errs:
                import numpy as np
                extra["centroiding_error_mean_px"] = round(float(np.mean(errs)), 2)
                extra["centroiding_error_rms_px"] = round(
                    float(np.sqrt(np.mean(np.array(errs) ** 2))), 2)
                extra["centroiding_error_p95_px"] = round(
                    float(np.percentile(errs, 95)), 2)
                extra["centroiding_error_max_px"] = round(float(np.max(errs)), 2)
                extra["centroiding_frames"] = len(errs)
            extra["reacquisition_count_video"] = len(self.sim.reacq_times)
            extra["video_false_lock_events"] = self.sim.false_lock_events
        self.perf.write_log(p, extra_info=extra)
        print(f"performance log -> {p}")


    # ---------------------------------------------------------------- draw
    def _draw(self):
        s = self.screen
        s.fill(T.C.BG)
        self._draw_header(s)
        self._draw_camera(s)
        self._draw_bottom(s)
        self._draw_panel(s)
        self._draw_footer(s)

    # ------------------------------------------------------------------
    # camera hero view geometry: fills left area below header, above strip
    CAM_X0, CAM_X1 = 8, 1276
    CAM_Y0, CAM_Y1 = 56, 676
    def _frame_dims(self):
        if self.video_mode:
            s = self.sim
            return s.video_w, s.video_h
        return CAM_W, CAM_H

    def _cam_scale(self):
        w, h = self._frame_dims()
        return min((self.CAM_X1 - self.CAM_X0) / w,
                   (self.CAM_Y1 - self.CAM_Y0) / h)

    def _cam_dest(self):
        sc = self._cam_scale()
        w, h = self._frame_dims()
        dw, dh = int(w * sc), int(h * sc)
        x = self.CAM_X0 + (self.CAM_X1 - self.CAM_X0 - dw) // 2
        y = self.CAM_Y0 + (self.CAM_Y1 - self.CAM_Y0 - dh) // 2
        return pygame.Rect(x, y, dw, dh)

    def _draw_header(self, surf):
        # ── background ──────────────────────────────────────────────
        pygame.draw.rect(surf, T.C.PANEL, (0, 0, APP_W, 48))
        pygame.draw.line(surf, T.C.BORDER, (0, 47), (APP_W, 47), 1)
        pygame.draw.line(surf, T.C.BORDER_B, (0, 0), (APP_W, 0), 1)

        # ── system ID block ──────────────────────────────────────────
        pygame.draw.rect(surf, T.C.BG, (0, 0, 168, 48))
        pygame.draw.line(surf, T.C.BORDER, (168, 0), (168, 47), 1)
        T.text(surf, (10, 8), "FSOC-PAT", 15, T.C.CYAN, bold=True)
        T.text(surf, (10, 27), "OPTICAL TRACK CONSOLE", 7, T.C.TEXT_FAINT)
        T.text(surf, (10, 38), "PS 26169 · SIH 2026", 7, T.C.TEXT_FAINT)

        # ── live state block ──────────────────────────────────────────
        res = self.sim.last_result
        st = res.get("state", "SEARCHING")
        st_col = T.C.STATE.get(st, T.C.CYAN)
        st_fill = T.C.STATE_FILL.get(st, (0, 30, 50))
        pygame.draw.rect(surf, st_fill, (174, 0, 128, 48))
        pygame.draw.line(surf, st_col, (174, 0), (174, 47), 2)
        pygame.draw.line(surf, T.C.BORDER, (302, 0), (302, 47), 1)
        T.text(surf, (238, 9), "TRACK STATE", 7, st_col, anchor="cc")
        T.text(surf, (238, 24), st, 13, st_col, bold=True, anchor="cc")
        r_dot_col = T.C.RED if self.paused else T.C.GREEN
        pygame.draw.circle(surf, r_dot_col, (176, 40), 3)
        T.text(surf, (182, 37), "PAUSED" if self.paused else "RUNNING", 7, r_dot_col)

        # ── key metrics ───────────────────────────────────────────────
        elapsed = res.get("t", 0.0)
        err = res.get("pointing_err_deg", 0.0)
        ec = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else              (T.C.AMBER if err < 0.30 else T.C.RED)
        conf = res.get("confidence", 0.0)
        fps = self.clock.get_fps()

        def _metric(surf, x, label, value, vcol):
            pygame.draw.line(surf, T.C.BORDER, (x, 6), (x, 41), 1)
            T.text(surf, (x + 8, 8), label, 7, T.C.TEXT_FAINT)
            T.text(surf, (x + 8, 20), value, 13, vcol, bold=True)

        _metric(surf, 308, "ELAPSED", f"{elapsed:7.1f} s", T.C.TEXT)
        _metric(surf, 388, "POINT ERR", f"{err*1000:6.1f} mdeg", ec)
        _metric(surf, 476, "CONFIDENCE", f"{conf:.2f}", T.C.CYAN)
        fps_col = T.C.GREEN if fps >= 25 else T.C.AMBER
        T.text(surf, (APP_W - 12, 8), f"{fps:.0f} FPS", 9, fps_col, bold=True, anchor="tr")
        T.text(surf, (APP_W - 12, 22), "ISRO · COARSE PAT", 7, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (APP_W - 12, 34), f"{self._platform_label()}", 7, T.C.TEXT_FAINT, anchor="tr")

        # ── chip groups ───────────────────────────────────────────────
        first_chip_x = min(c.rect.x for c in self.chips.values())
        T.text(surf, (first_chip_x, 1), "SCENARIO", 7, T.C.TEXT_FAINT)
        for name, c in self.chips.items():
            c.draw(surf, selected=(name == self.preset))
        pm0 = min(c.rect.x for c in self.platform_chips.values())
        pygame.draw.line(surf, T.C.BORDER, (pm0 - 6, 6), (pm0 - 6, 41), 1)
        T.text(surf, (pm0, 1), "PLATFORM", 7, T.C.TEXT_FAINT)
        for name, c in self.platform_chips.items():
            c.draw(surf, selected=(name == self.platform_mode))
        at0 = min(c.rect.x for c in self.atmos_chips.values())
        pygame.draw.line(surf, T.C.BORDER, (at0 - 6, 6), (at0 - 6, 41), 1)
        T.text(surf, (at0, 1), "ATMOSPHERE", 7, T.C.TEXT_FAINT)
        for name, c in self.atmos_chips.items():
            enabled = (name == "CLEAR" or self._atmosphere_allowed())
            c.draw(surf, selected=(name == self.atmosphere), enabled=enabled)
    def _draw_footer(self, surf):
        if self.video_mode:
            T.text(surf, (8, APP_H - 16),
                   "SPACE pause · R restart video · S shot · L load MP4 · V FOV grid",
                   9, T.C.TEXT_FAINT)
            return
        T.text(surf, (8, APP_H - 16),
               "SPACE pause · R reset · S shot · 1-5 scenario · 6-8 platform · A atmosphere · F fullscreen · V FOV grid",
               9, T.C.TEXT_FAINT)

    def _draw_camera(self, surf):
        frame = self.sim.last_result.get("frame")
        cam = self._frame_to_surf(frame)
        # draw HUD in native camera space, then scale up as one clean image
        self._draw_hud(cam)
        fw, fh = self._frame_dims()
        scaled = pygame.transform.smoothscale(cam, (int(fw * self._cam_scale()),
                                                    int(fh * self._cam_scale())))
        dest = self._cam_dest()
        surf.blit(scaled, dest.topleft)
        _vp_st = self.sim.last_result.get("state", "SEARCHING")
        _vp_col = T.C.STATE.get(_vp_st, T.C.BORDER)
        pygame.draw.rect(surf, _vp_col, dest, 1)
        self._draw_pat_stepper(surf, dest)
        self._draw_camera_story(surf, dest)

    def _frame_to_surf(self, frame):
        if frame is None:
            fw, fh = self._frame_dims()
            s = pygame.Surface((fw, fh))
            s.fill((0, 0, 0))
            return s
        img = np.ascontiguousarray(frame[:, :, ::-1])
        return pygame.surfarray.make_surface(img)

    def _draw_pat_stepper(self, surf, dest):
        """PAT pipeline stages with completed/active/pending states."""
        res = self.sim.last_result
        st = res["state"]
        steps = ["PREDICT", "POINT", "SEARCH", "TRACK", "LOCK"]
        idx = {"SEARCHING": 2, "REACQUIRING": 2, "COASTING": 3,
               "LOCKED": 4, "DEGRADED_LOCK": 4}.get(st, 0)
        act_col = T.C.STATE.get(st, T.C.CYAN)
        box = pygame.Rect(dest.x + 8, dest.y + 8, dest.w - 16, 28)
        pygame.draw.rect(surf, T.C.BG, box)
        pygame.draw.rect(surf, T.C.BORDER, box, 1)
        n = len(steps)
        seg_w = box.w // n
        x = box.x
        for i, step in enumerate(steps):
            seg = pygame.Rect(x, box.y, seg_w - 1, box.h)
            done = i < idx
            active = i == idx
            if active:
                pygame.draw.rect(surf, tuple(c // 7 for c in act_col), seg)
                pygame.draw.rect(surf, act_col, (seg.x, seg.bottom - 3, seg.w, 3))
                text_col, fs = act_col, 10
            elif done:
                pygame.draw.rect(surf, T.C.PANEL_2, seg)
                pygame.draw.rect(surf, T.C.BORDER_B, (seg.x, seg.bottom - 1, seg.w, 1))
                text_col, fs = T.C.TEXT_DIM, 9
            else:
                text_col, fs = T.C.TEXT_FAINT, 9
            T.text(surf, (seg.centerx, seg.centery - 1), step, fs,
                   text_col, bold=active, anchor="cc")
            if i < n - 1:
                mx = x + seg_w - 1
                pygame.draw.line(surf, T.C.BORDER, (mx, box.y+4), (mx, box.bottom-4), 1)
            x += seg_w
        ann = {"COASTING": ("COAST", T.C.CYAN), "REACQUIRING": ("RE-ACQ", T.C.PURPLE),
               "LOST": ("LOST", T.C.RED)}.get(st)
        if ann:
            self._stepper_badge(surf, box, ann[0], ann[1])

    def _stepper_badge(self, surf, box, label, col):
        max_right = 1272
        avail = max_right - (box.right + 8)
        w = max(56, min(120, avail))
        r = pygame.Rect(box.right + 8, box.y, w, box.h)
        pygame.draw.rect(surf, tuple(c // 7 for c in col), r)
        pygame.draw.rect(surf, col, r, 1)
        pygame.draw.rect(surf, col, (r.x, r.y, 2, r.h))
        T.text(surf, (r.centerx + 2, r.centery), label, 9, col, bold=True, anchor="cc")

    def _draw_camera_story(self, surf, dest):
        """Right-edge FOV/beacon story: OUTSIDE FOV → ACQUISITION WINDOW →
        BEACON ACQUIRED → LOCKED. Big, single-purpose status for judges."""
        res = self.sim.last_result
        st = res["state"]
        if not res["in_fov"]:
            label, col = "OUTSIDE FOV", T.C.TEXT_FAINT
        elif st == "SEARCHING":
            label, col = "ACQUISITION WINDOW", T.C.AMBER
        elif st == "COASTING":
            label, col = "BEACON LOST · PREDICTIVE COAST", T.C.CYAN
        elif st == "LOCKED":
            label, col = "BEACON ACQUIRED · LOCKED", T.C.GREEN
        elif st == "DEGRADED_LOCK":
            label, col = "BEACON HELD · DEGRADED LOCK", T.C.GREEN_DIM
        elif st == "REACQUIRING":
            label, col = "BEACON LOST · RE-ACQUIRING", T.C.PURPLE
        else:
            label, col = "SEARCHING", T.C.AMBER
        r = pygame.Rect(dest.x + 8, dest.bottom - 34, dest.w - 8, 26)
        fill = T.C.STATE_FILL.get(res["state"], (0, 16, 26))
        pygame.draw.rect(surf, fill, r)
        pygame.draw.rect(surf, T.C.BORDER, r, 1)
        pygame.draw.rect(surf, col, (r.x, r.y, 3, r.h))
        T.text(surf, (r.x + 10, r.centery), label, 11, col, bold=True, anchor="cc")
        # Acquisition time in strip
        acq_t = self.perf.live_stats().get("acquisition_time_s")
        if acq_t:
            T.text(surf, (r.right - 8, r.centery), f"ACQ {acq_t:.2f}s",
                   9, T.C.TEXT_DIM, anchor="rc")
        # Hero pointing error overlay (app-space, top-right of camera)
        err = res["pointing_err_deg"]
        ec = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else \
             (T.C.AMBER if err < 0.30 else T.C.RED)
        T.text(surf, (dest.right - 10, dest.y + 44), "POINTING ERROR",
               8, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (dest.right - 10, dest.y + 56),
               f"{err * 1000:6.1f} mdeg", 28, ec, bold=True, anchor="tr")

    def _draw_hud(self, cam):
        """Draw overlays in native 800x450 camera space, then the whole
        surface is scaled up at blit time.

        The overlays tell the judging story:
          * the ACTIVE TRACK (what A's tracker is locked onto) is ringed and
            labelled "SAT-B BEACON";
          * the SYNTHETIC-EPHEMERIS PREDICTION (the coarse prior A was given)
            is shown as a dashed marker, so you can SEE the prior vs. the
            detected truth;
          * the optical BORESIGHT reticle + crosshair show the LOS the
            gimbal/beam actually points along, with the live pointing error
            under it.
        """
        r = cam.get_rect()
        cx, cy = r.centerx, r.centery
        res = self.sim.last_result

        # figure out the primary "locked beacon" anchor point (if any) up
        # front, so other HUD labels can steer clear of it instead of
        # printing text on top of each other when the boresight and the
        # tracked beacon are close together (e.g. right after acquisition).
        assoc = self.sim.tracker.associated
        beacon_anchor = None
        if assoc is not None and res["state"] in LOCKED_STATES:
            beacon_anchor = (int(assoc.u), int(assoc.v))

        def _label_clear(pt, min_dist=34, *others):
            """True if pt is far enough from beacon_anchor and any other
            already-placed anchors that a text label here won't collide."""
            for o in (beacon_anchor,) + others:
                if o is not None:
                    if (pt[0] - o[0]) ** 2 + (pt[1] - o[1]) ** 2 < min_dist ** 2:
                        return False
            return True

        if self.show_fov_grid:
            grid_col = (26, 40, 58)
            pygame.draw.line(cam, grid_col, (cx, r.top), (cx, r.bottom), 1)
            pygame.draw.line(cam, grid_col, (r.left, cy), (r.right, cy), 1)
            # corner FOV boundary marks
            for cax, cay, dxa, dya in (
                (r.left+2,r.top+2,1,1),(r.right-2,r.top+2,-1,1),
                (r.left+2,r.bottom-2,1,-1),(r.right-2,r.bottom-2,-1,-1)):
                pygame.draw.line(cam,(46,66,88),(cax,cay),(cax+dxa*14,cay),1)
                pygame.draw.line(cam,(46,66,88),(cax,cay),(cax,cay+dya*14),1)
            # subtle range reference rings (quarter and half FOV radius)
            rng = min(r.w, r.h) // 4
            for rr in (rng, rng * 2):
                pygame.draw.circle(cam, (20, 34, 50), (cx, cy), rr, 1)

        # ---- optical boresight reticle ----
        bp = self._est_pixel(self.sim.gimbal.pan, self.sim.gimbal.tilt)
        if bp is not None:
            bx, by = bp
            rc = (65, 125, 165)  # muted steel-blue
            gap, arm = 10, 36
            pygame.draw.line(cam, rc, (bx-gap-arm, by), (bx-gap, by), 1)
            pygame.draw.line(cam, rc, (bx+gap, by), (bx+gap+arm, by), 1)
            pygame.draw.line(cam, rc, (bx, by-gap-arm), (bx, by-gap), 1)
            pygame.draw.line(cam, rc, (bx, by+gap), (bx, by+gap+arm), 1)
            pygame.draw.circle(cam, rc, (bx, by), 14, 1)
            pygame.draw.circle(cam, rc, (bx, by), 4, 1)
            for dx, dy in ((0,-1),(0,1),(-1,0),(1,0)):
                pygame.draw.line(cam, rc,
                    (bx+dx*20, by+dy*20), (bx+dx*26, by+dy*26), 1)
            if _label_clear((bx, by)):
                pan_deg = self.sim.gimbal.pan
                tilt_deg = self.sim.gimbal.tilt
                T.text(cam, (bx+50, by-18), "BST", 7, rc, anchor="tl")
                T.text(cam, (bx+50, by-9),
                       f"Az{pan_deg:+.1f}° El{tilt_deg:+.1f}°", 6, rc, anchor="tl")

        # ---- tracked / candidate overlays ----
        for i, c in enumerate(res.get("cand_list", [])):
            cu, cv = int(c.u), int(c.v)
            cand_col = (0, 80, 110)
            arm = 5
            for sx, sy in ((-1,-1),(-1,1),(1,-1),(1,1)):
                pygame.draw.line(cam, cand_col,
                    (cu + sx*8, cv + sy*8), (cu + sx*(8-arm), cv + sy*8), 1)
                pygame.draw.line(cam, cand_col,
                    (cu + sx*8, cv + sy*8), (cu + sx*8, cv + sy*(8-arm)), 1)
        if assoc is not None and res["state"] in LOCKED_STATES:
            apx, apy = int(assoc.u), int(assoc.v)
            is_degraded = res["state"] == "DEGRADED_LOCK"
            ring_col = T.C.AMBER if is_degraded else T.C.GREEN
            # outer ring (thinner on degraded to signal reduced confidence)
            pygame.draw.circle(cam, ring_col, (apx, apy), 18, 1)
            # corner tracking brackets
            _bracket(cam, (apx, apy), ring_col, 24, 1)
            # center dot
            pygame.draw.circle(cam, ring_col, (apx, apy), 2)
            # cap lines at cardinal points
            for ddx, ddy in ((-1,0),(1,0),(0,-1),(0,1)):
                pygame.draw.line(cam, ring_col,
                    (apx+ddx*18, apy+ddy*18), (apx+ddx*24, apy+ddy*24), 1)
            # label
            lbl = "BCN·DEG" if is_degraded else "BCN·LCK"
            T.text(cam, (apx+28, apy-15), lbl, 8, ring_col, bold=True, anchor="tl")
            T.text(cam, (apx+28, apy-5), f"{res['pointing_err_deg']*1000:.1f}m°",
                   7, ring_col, anchor="tl")
        elif assoc is not None:
            _bracket(cam, (int(assoc.u), int(assoc.v)), T.C.GREEN, 13, 2)
        # if coasting (estimate exists but no associated blob), mark est LOS
        elif res.get("est_az") is not None and res["state"] not in LOCKED_STATES:
            p = self._est_pixel(res["est_az"], res["est_el"])
            if p is not None:
                pygame.draw.circle(cam, T.C.CYAN, p, 7, 1)

        # ---- synthetic-ephemeris PRIOR marker (coarse pre-aim reference) ----
        paz = self.eph_pred_az if hasattr(self, "eph_pred_az") else None
        if paz is not None:
            pp = self._est_pixel(paz, self.eph_pred_el)
            if pp is not None:
                px, py = pp
                # dashed diamond = the predicted (not yet detected) position
                for k in range(0, 360, 30):
                    a1 = math.radians(k)
                    a2 = math.radians(k + 12)
                    pygame.draw.line(cam, T.C.AMBER,
                                     (px + 9 * math.cos(a1), py + 9 * math.sin(a1)),
                                     (px + 9 * math.cos(a2), py + 9 * math.sin(a2)), 1)
                if _label_clear((px, py), 34, bp):
                    T.text(cam, (px, py - 20), "SYNTH-EPHEMERIS PRED", 8, T.C.AMBER, anchor="cc")

        # ---- search acquisition overlay ----
        if res["state"] in ("SEARCHING", "REACQUIRING"):
            search_col = T.C.AMBER if res["state"] == "SEARCHING" else T.C.PURPLE
            t = self.sim.tracker
            sa = getattr(t, "search_angle", 0.0)
            se = getattr(t, "search_radius", 0.05)
            base_az = getattr(t, "est_az", None) or res["truth_az"]
            base_el = getattr(t, "est_el", None) or res["truth_el"]
            # spiral search dots
            for k in range(14):
                a = sa + k * 0.55
                rr = se * (1 + k / 14.0)
                p = self._est_pixel(base_az + rr * np.cos(a), base_el + rr * np.sin(a))
                if p is not None:
                    pygame.draw.circle(cam, search_col, p, 1)
            # search area ring at the search-radius boundary
            center_p = self._est_pixel(base_az, base_el)
            if center_p is not None:
                focal, cu, cv, vw, vh = self._cam_space()
                px_per_rad = focal
                ring_r = int(se * px_per_rad)
                if 4 < ring_r < 400:
                    pygame.draw.circle(cam, tuple(c // 3 for c in search_col),
                                       center_p, ring_r, 1)

        # ---- occluded banner ----
        if not res["beacon_visible"]:
            occ_r = pygame.Rect(r.centerx - 80, r.bottom - 50, 160, 14)
            pygame.draw.rect(cam, (50, 8, 8), occ_r)
            pygame.draw.rect(cam, T.C.RED, occ_r, 1)
            T.text(cam, (r.centerx, occ_r.centery), "OCCLUDED", 9, T.C.RED, anchor="cc")

        # ── HUD overlays (all in native camera space) ───────────────
        st = res["state"]
        col = T.C.STATE.get(st, T.C.CYAN)
        tr = self.sim.tracker

        # Phase-2 trust bars: top-left, compact 2-row stack
        tm = getattr(tr, "trust", None)
        dy = 8
        if tm is not None:
            W.hbar(cam, (8, dy, 80, 4), tm.vision_trust, T.C.CYAN)
            T.text(cam, (92, dy - 1), f"VIS {tm.vision_trust:.2f}", 7, (60, 140, 160))
            dy += 7
            W.hbar(cam, (8, dy, 80, 4), tm.model_trust, T.C.PURPLE)
            T.text(cam, (92, dy - 1), f"MDL {tm.model_trust:.2f}", 7, (100, 70, 160))
            sigma = getattr(getattr(tr, "unc", None), "display_sigma_px", None)  # noqa
            if sigma is not None:
                dy += 7
                T.text(cam, (8, dy), f"σ {sigma:.1f}px", 7, (50, 70, 90))

        # Bottom-left: state chip + confidence strip
        chip_h = 20
        chip_r = pygame.Rect(6, r.h - chip_h - 8, 120, chip_h)
        fill = T.C.STATE_FILL.get(st, (0, 20, 32))
        pygame.draw.rect(cam, fill, chip_r)
        pygame.draw.rect(cam, tuple(c // 2 for c in col), chip_r, 1)
        pygame.draw.rect(cam, col, (chip_r.x, chip_r.y, 3, chip_r.h))
        T.text(cam, (chip_r.x + 10, chip_r.centery), st, 10, col, bold=True, anchor="cc")
        conf_val = res.get("confidence", 0.0)
        W.hbar(cam, (chip_r.x, chip_r.bottom + 2, chip_r.w, 3), conf_val, col)
        T.text(cam, (chip_r.right + 4, chip_r.centery),
               f"{conf_val:.2f}", 8, col, anchor="cc")

        # Eval time: top-right
        T.text(cam, (r.right - 6, 8), f"t={res['t']:6.1f}s", 7, (40, 60, 80), anchor="tr")

        # ---- GROUND TRUTH (evaluation-only, hidden in normal operation) ----
        # The algorithm never receives truth; this is display-only and clearly
        # labelled so the demo cannot look like it is given the answer.
        if self.show_gt:
            gp = self._est_pixel(res["truth_az"], res["truth_el"])
            if gp is not None:
                gx, gy = gp
                pygame.draw.circle(cam, T.C.PURPLE, (gx, gy), 5, 1)
                pygame.draw.line(cam, T.C.PURPLE, (gx-8, gy), (gx+8, gy), 1)
                pygame.draw.line(cam, T.C.PURPLE, (gx, gy-8), (gx, gy+8), 1)
            bw = 220
            brect = pygame.Rect(r.centerx - bw//2, 2, bw, 12)
            pygame.draw.rect(cam, (40, 10, 60), brect)
            pygame.draw.rect(cam, T.C.PURPLE, brect, 1)
            T.text(cam, (r.centerx, 8), "GROUND TRUTH  ·  EVAL ONLY",
                   7, T.C.PURPLE, anchor="cc")

    def _cam_space(self):
        """Camera pixel-space constants for the *active* source: the
        synthetic virtual camera (config) or the input video (its own
        geometry) in Benchmark-2 bypass mode."""
        if self.video_mode:
            s = self.sim
            return (s.focal_px, s.cu, s.cv, s.video_w, s.video_h)
        return (config.FOCAL_PX, config.PRINCIPAL_U, config.PRINCIPAL_V,
                CAM_W, CAM_H)

    def _est_pixel(self, az, el):
        """Project an az/el LOS into camera pixels using the realized pose."""
        if az is None or el is None:
            return None
        focal, cu, cv, vw, vh = self._cam_space()
        d = azel_unit(az, el)
        basis = self.sim.gimbal.basis()
        p = project_point_into_camera(d, (0, 0, 0), basis, focal, cu, cv)
        if p is None:
            return None
        u, v = p
        if 0 <= u < vw and 0 <= v < vh:
            return (int(u), int(v))
        return None

    # ---------------------------------------------------------------- bottom
    # ------------------------------------------------------------------
    # bottom strip: LIVE POINTING-ERROR graph (left) + CAMERA/ACTUATOR (right)
    def _draw_bottom(self, surf):
        pygame.draw.rect(surf, T.C.PANEL, (8, 680, 1268, 214))
        pygame.draw.line(surf, T.C.BORDER_B, (8, 680), (1276, 680), 1)
        pygame.draw.line(surf, T.C.BORDER, (730, 684), (730, 892), 1)
        err_box = pygame.Rect(44, 688, 672, 196)
        self._draw_error_graph(surf, err_box)
        self._draw_camera_panel(surf, pygame.Rect(742, 688, 520, 196))

    def _draw_error_graph(self, surf, box):
        T.text(surf, (box.x, box.y), "ANGULAR POINTING ERROR", 10, T.C.TEXT_DIM)
        T.text(surf, (box.x + 182, box.y + 1), "deg", 7, T.C.TEXT_FAINT)
        T.text(surf, (box.right, box.y), "target <0.0625°",
               7, T.C.TEXT_FAINT, anchor="tr")
        plot = pygame.Rect(box.x + 28, box.y + 14, box.w - 28, box.h - 16)
        pygame.draw.rect(surf, T.C.BG, plot)
        pygame.draw.rect(surf, T.C.BORDER, plot, 1)
        # target acquisition band
        _bound = plot.bottom - int(plot.h * (config.FINE_ACQUISITION_REGION_DEG / 0.5))
        pygame.draw.rect(surf, (6, 22, 14), (plot.x, _bound, plot.w, plot.bottom - _bound))
        pygame.draw.line(surf, T.C.GREEN_DIM, (plot.x, _bound), (plot.right, _bound), 1)
        # engineering gridlines with Y-axis labels
        T.text(surf, (plot.x - 2, plot.bottom - 4), "0", 7, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (plot.x - 2, plot.y), "0.5", 7, T.C.TEXT_FAINT, anchor="tr")
        for deg, col in ((0.1,T.C.GRID),(0.2,T.C.GRID),(0.3,T.C.GRID),(0.4,T.C.GRID)):
            yy = plot.bottom - int(plot.h * (deg / 0.5))
            pygame.draw.line(surf, col, (plot.x, yy), (plot.right, yy), 1)
            T.text(surf, (plot.x - 2, yy - 4), f"{deg:.1f}", 7, T.C.TEXT_FAINT, anchor="tr")
        # series (degrees), clamped to 0..0.5
        series = [max(0.0, min(0.5, e)) for e in self.error_spark]
        n = len(series)
        if n > 1:
            pts = []
            for i, v in enumerate(series):
                xx = int(plot.x + plot.w * i / (n - 1))
                yy = int(plot.bottom - plot.h * (v / 0.5))
                pts.append((xx, yy))
            # filled area under curve
            if len(pts) >= 2:
                fill_pts = [pts[0]] + pts + [(pts[-1][0], plot.bottom), (pts[0][0], plot.bottom)]
                area = pygame.Surface((plot.w, plot.h), pygame.SRCALPHA)
                local = [(p[0] - plot.x, p[1] - plot.y) for p in fill_pts]
                pygame.draw.polygon(area, (50, 240, 140, 30), local)
                surf.blit(area, (plot.x, plot.y))
            prev = None
            for p in pts:
                if prev is not None:
                    pygame.draw.line(surf, T.C.GREEN, prev, p, 2)
                prev = p
        # "ACQ TARGET" band label
        T.text(surf, (plot.right - 2, _bound - 1), "ACQ TARGET", 7, T.C.GREEN_DIM, anchor="br")
        # Current value: NOW marker
        if series:
            cur_v = series[-1]
            now_x = plot.right - 1
            now_y = int(plot.bottom - plot.h * (cur_v / 0.5))
            cur_col = T.C.GREEN if cur_v < config.FINE_ACQUISITION_REGION_DEG else                       (T.C.AMBER if cur_v < 0.30 else T.C.RED)
            pygame.draw.line(surf, tuple(c // 4 for c in cur_col),
                             (now_x, plot.y), (now_x, plot.bottom), 1)
            pygame.draw.circle(surf, cur_col, (now_x, now_y), 3)
            T.text(surf, (now_x - 4, now_y - 10), f"{cur_v*1000:.0f}", 8,
                   cur_col, bold=True, anchor="tr")
        # Disturbance: beacon occluded marker
        if not self.sim.last_result["beacon_visible"]:
            pygame.draw.rect(surf, (48, 14, 14), (plot.right - 3, plot.y, 3, plot.h))
        self._draw_state_timeline(surf, plot)

    def _draw_state_timeline(self, surf, plot):
        """Horizontal rails of PAT state colour across the tracking window.

        Each run spans the recorded [t0, t1) from sim.event_log in its
        state colour (COAST/REACQ/LOCK/DEGRADED/LOST).  A dim cyan run is
        the predictive-coast span, so the operator sees *why* the error is
        flat even with no anchor blob.
        """
        tmax = max(0.001, self.sim.last_result.get("t", 0.0))
        ev = list(getattr(self.sim, "event_log", ()))
        y = plot.bottom - 8
        band = pygame.Rect(plot.x, y, plot.w, 7)
        pygame.draw.rect(surf, T.C.BG, band)
        runs = []
        if ev:
            runs.append((0.0, ev[0][0], ev[0][1]))
            for i, e in enumerate(ev):
                t1 = ev[i + 1][0] if i + 1 < len(ev) else tmax
                if t1 > e[0]:
                    runs.append((e[0], t1, e[2]))
        else:
            runs.append((0.0, tmax, getattr(self.sim.tracker, "state", "SEARCHING")))
        for t0, t1, st in runs:
            x0 = plot.x + plot.w * (t0 / tmax)
            x1 = plot.x + plot.w * (min(t1, tmax) / tmax)
            if x1 <= x0:
                continue
            col = T.C.STATE.get(st, T.C.STATE["SEARCHING"])
            if st == "COASTING":
                col = T.C.STATE["REACQUIRING"]
            if st == "SEARCHING":
                col = T.C.AMBER_DIM
            pygame.draw.rect(surf, col, (int(x0), y, int(x1 - x0), 7))
        pygame.draw.rect(surf, T.C.BORDER, band, 1)
        T.text(surf, (plot.x - 2, y + 3), "STATE", 7, T.C.TEXT_FAINT, anchor="tr")

    def _draw_camera_panel(self, surf, box):
        res = self.sim.last_result
        T.text(surf, (box.x, box.y), "GIMBAL / ACTUATOR", 9, T.C.TEXT_FAINT)
        pygame.draw.line(surf, T.C.BORDER, (box.x, box.y + 12), (box.x + 200, box.y + 12), 1)
        x = box.x + 8
        y = box.y + 18
        kpis = [
            ("AZIMUTH",   f"{self.sim.gimbal.pan:+.2f}°",  T.C.CYAN),
            ("ELEVATION", f"{self.sim.gimbal.tilt:+.2f}°", T.C.CYAN),
            ("H-FOV",     f"{config.HFOV_DEG:.1f}°",       T.C.TEXT_DIM),
            ("MODE",      "COARSE PAT",                     T.C.TEXT_DIM),
        ]
        for _ in range(2):
            group = kpis[:2] if x == box.x + 8 else kpis[2:]
            for i, (lab, val, vcol) in enumerate(group):
                ly = y + i * 26
                T.text(surf, (x, ly), lab, 8, T.C.TEXT_FAINT)
                T.text(surf, (x, ly + 10), val, 13, vcol, bold=True)
            x += 200
        # slew / latency row
        T.text(surf, (box.x + 14, y + 52), "If tracking, gimbal is slewed to keep B in FOV", 9, T.C.TEXT_FAINT)

        # actuator saturation readout (0..1 per axis) - physical-limits honesty:
        # when SAT > 0 the target motion exceeds the gimbal slew capability, so
        # a residual pointing error there is an actuator limit, not a tracker bug.
        sp, st_ = res.get("gimbal_sat_pan", 0.0), res.get("gimbal_sat_tilt", 0.0)
        sat = max(sp, st_)
        s_col = T.C.GREEN if sat <= 0.05 else (T.C.AMBER if sat < 0.5 else T.C.RED)
        T.text(surf, (box.x + 14, y + 66), "GIMBAL SATURATION", 9, T.C.TEXT_FAINT)
        T.text(surf, (box.x + 150, y + 66), f"P {sp * 100:3.0f}%  T {st_ * 100:3.0f}%",
               11, s_col, bold=(sat > 0.05))

        # ---- A -> beam -> B alignment mini-diagram (right of the numbers) ----
        self._draw_beam_strip(surf, pygame.Rect(box.right - 220, box.y + 22, 208, box.h - 30))

    def _draw_beam_strip(self, surf, box):
        cx = box.centerx
        ay = box.bottom - 16
        by = box.y + 30
        err = self.sim.last_result["pointing_err_deg"]
        col = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else \
              (T.C.AMBER if err < 0.30 else T.C.RED)
        # beam cone + line
        pygame.draw.polygon(surf, (24, 60, 80),
                            [(cx - 6, ay), (box.x + 2, by), (box.right - 2, by)])
        pygame.draw.line(surf, col, (cx, ay), (cx, by), 2)
        # SAT-A (observer) at bottom
        pygame.draw.rect(surf, T.C.CYAN, (cx - 10, ay - 8, 20, 10), 1)
        T.text(surf, (cx, ay + 10), "SAT-A", 8, T.C.CYAN, bold=True, anchor="cc")
        # SAT-B beacon at top
        pygame.draw.circle(surf, T.C.RED, (cx, by), 6)
        pygame.draw.circle(surf, T.C.RED, (cx, by), 10, 1)
        T.text(surf, (cx, by - 16), "SAT-B", 8, T.C.RED, bold=True, anchor="cc")
        # pointing-error readout sits beside the beam line, at mid-height -
        # it used to sit right on top of the "SAT-A" label at the bottom.
        mid_y = (ay + by) // 2
        T.text(surf, (box.right - 2, mid_y - 7), "ERR", 7, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (box.right - 2, mid_y + 3), f"{err * 1000:.1f} mdeg", 11, col,
               bold=True, anchor="tr")

    def _load_compare(self):
        """Load the last measured baseline-vs-adaptive benchmark (if any)."""
        try:
            p = os.path.join(config.LOG_DIR, "compare_summary.json")
            if not os.path.exists(p):
                return None
            import json
            with open(p) as fh:
                return json.load(fh)
        except Exception:
            return None

    # ---------------------------------------------------------------- right panel
    def _draw_panel(self, surf):
        pygame.draw.rect(surf, T.C.BG, (1280, 48, 320, APP_H - 48))
        pygame.draw.line(surf, T.C.BORDER_B, (1280, 48), (1280, APP_H), 1)
        pygame.draw.line(surf, T.C.BORDER, (1282, 48), (1282, APP_H), 1)
        self._panel_mission(surf)
        self._panel_geometry(surf)
        self._panel_performance(surf)
        self._panel_comparison(surf)
        self._panel_disturbances(surf)
        self._panel_controls(surf)

    def _panel_mission(self, surf):
        x, y, w, h = 1288, 56, 304, 78
        T.panel(surf, pygame.Rect(x, y, w, h))
        T.text(surf, (x + 10, y + 5), "MISSION", 8, T.C.TEXT_FAINT)
        pygame.draw.line(surf, T.C.BORDER, (x + 8, y + 17), (x + w - 8, y + 17), 1)
        res = self.sim.last_result
        st = res["state"]
        lock = st in LOCKED_STATES
        if self.video_mode:
            rows = [
                ("Source", "INPUT VIDEO (PTZ bypassed)"),
                ("Mode", "Benchmark-2 · video feed"),
                ("Status", "TRACKING" if st in LOCKED_STATES else
                           ("ACQUIRING" if st == "SEARCHING" else "COAST")),
            ]
            yy = y + 22
            col = T.C.GREEN if lock else T.C.STATE[st]
            for lab, val in rows:
                T.text(surf, (x + 12, yy), lab, 10, T.C.TEXT_FAINT)
                T.text(surf, (x + 96, yy), val, 11,
                       col if lab == "Status" else T.C.TEXT,
                       bold=(lab == "Status"))
                yy += 16
            return
        rows = [
            ("Scenario", self.preset),
            ("Link", self._platform_label() + "  ·  " + (self.atmosphere or "CLEAR")),
            ("Path", disturbance_kind_label(self.platform_mode)
                     + ("  (weather off)" if not self._atmosphere_allowed() else "")),
            ("Status", "TRACKING" if st in LOCKED_STATES else
                       ("SEARCH" if st == "SEARCHING" else "COAST")),
        ]
        yy = y + 22
        col = T.C.GREEN if lock else T.C.STATE[st]
        for lab, val in rows:
            T.text(surf, (x + 12, yy), lab, 10, T.C.TEXT_FAINT)
            on = T.C.GREEN_DIM if lab == "Path" and not self._atmosphere_allowed() \
                else (col if lab == "Status" else T.C.TEXT)
            T.text(surf, (x + 96, yy), val, 10, on, bold=(lab == "Status"))
            yy += 14

    def _panel_geometry(self, surf):
        g = pygame.Rect(1288, 140, 304, 148)
        if self.video_mode:
            # Benchmark-2: the panel shows live centroiding status instead of
            # the synthetic 3D mission geometry.
            T.panel(surf, g)
            T.text(surf, (g.x + 10, g.y + 6), "VIDEO BYPASS  (Benchmark-2)",
                   10, T.C.TEXT_DIM)
            res = self.sim.last_result
            stat = self.perf.live_stats()
            rows = [
                ("Input", os.path.basename(self.video_path)[:26]),
                ("Acq", (f"{stat['acquisition_time_s']:.2f}s"
                         if stat["acquisition_time_s"] is not None else "--")),
                ("Retention", f"{stat['retention_total_pct']:.1f}%"),
                ("Centroid err", (f"{res.get('centroid_err_px', 0):.1f} px"
                                  if res is not None else "--")),
            ]
            yy = g.y + 22
            for lab, val in rows:
                T.text(surf, (g.x + 12, yy), lab, 10, T.C.TEXT_FAINT)
                T.text(surf, (g.x + 86, yy), val, 11, T.C.TEXT, bold=(lab == "Centroid err"))
                yy += 24
            return
        view3d.render(surf, g, self.sim, self.sim.t)
        T.text(surf, (g.right - 6, g.y - 2), "B approaching A's FOV", 9, T.C.TEXT_FAINT, anchor="tr")

    def _panel_performance(self, surf):
        x, y, w, h = 1288, 292, 304, 110
        res = self.sim.last_result
        st = self.perf.live_stats()
        err = res["pointing_err_deg"]
        ec = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else              (T.C.AMBER if err < 0.30 else T.C.RED)
        T.panel(surf, pygame.Rect(x, y, w, h), accent=ec)
        T.text(surf, (x + 14, y + 6), "PAT PERFORMANCE", 10, T.C.TEXT_DIM)
        chip_r = pygame.Rect(x + 10, y + 20, w - 20, 36)
        pygame.draw.rect(surf, tuple(c // 8 for c in ec), chip_r, border_radius=2)
        pygame.draw.rect(surf, tuple(c // 3 for c in ec), chip_r, 1, border_radius=2)
        T.text(surf, (x + 16, y + 22), "POINTING ERROR", 7, ec)
        T.text(surf, (x + 16, y + 30), f"{err * 1000:6.1f} mdeg", 22, ec, bold=True)
        acq = st["acquisition_time_s"]
        acq_s = f"{acq:.2f}s" if acq else "--"
        reacq = st["last_reacq_s"]
        reacq_s = f"{reacq:.2f}s" if reacq else f"{st['reacquisition_count']}ev"
        ret_pct = st["retention_total_pct"]
        ret_col = T.C.GREEN if ret_pct >= 95 else (T.C.AMBER if ret_pct >= 80 else T.C.RED)
        cols = [("ACQ", acq_s, T.C.CYAN), ("RET", f"{ret_pct:.1f}%", ret_col), ("REACQ", reacq_s, T.C.PURPLE)]
        xx = x + 12
        for lab, val, vc in cols:
            T.text(surf, (xx, y + 62), lab, 8, T.C.TEXT_FAINT)
            T.text(surf, (xx, y + 73), val, 14, vc, bold=True)
            xx += 92
        if self.show_diag:
            diag = (f"mean {st['mean_err_deg']*1000:.0f} · rms {st['rms_err_deg']*1000:.0f} "
                    f"· max {st['max_err_deg']*1000:.0f} mdeg · fps {st['fps']:.0f}")
            T.text(surf, (x + 12, y + 98), diag, 8, T.C.TEXT_FAINT)
        else:
            T.text(surf, (x + 12, y + 98), "DIAGNOSTICS › (click)", 8, T.C.TEXT_FAINT)

    def _panel_comparison(self, surf):
        x, y, w, h = 1288, 408, 304, 158
        T.panel(surf, pygame.Rect(x, y, w, h))
        T.text(surf, (x + 10, y + 6), "TRACKING COMPARISON", 10, T.C.CYAN)
        T.text(surf, (x + w - 10, y + 6), "measured · A/B", 8, T.C.TEXT_FAINT, anchor="tr")
        if self.compare is None:
            T.text(surf, (x + 12, y + 40), "run benchmark to populate:", 9, T.C.TEXT_FAINT)
            T.text(surf, (x + 12, y + 54), "python -m metrics.compare_trackers", 9, T.C.CYAN)
            T.text(surf, (x + 12, y + 76), "shows BASELINE (naive) vs ADAPTIVE on", 9, T.C.TEXT_FAINT)
            T.text(surf, (x + 12, y + 90), "identical scenarios.", 9, T.C.TEXT_FAINT)
            return
        res = self.compare.get("results", {})
        row = res.get(self.preset)
        if not row:
            T.text(surf, (x + 12, y + 40), "no data for " + self.preset, 9, T.C.TEXT_FAINT)
            return
        # column headers
        cx = [x + 96, x + 156, x + 214, x + 260]
        hdr_cols = [(cx[0], "ACQ"), (cx[1], "MEAN°"), (cx[2], "RET%"), (cx[3], "FAL")]
        T.text(surf, (x + 12, y + 22), "", 9)
        for xx, lab in hdr_cols:
            T.text(surf, (xx, y + 22), lab, 8, T.C.TEXT_FAINT)
        # BASIC row (dim)
        base = row.get("baseline", {})
        T.text(surf, (x + 12, y + 40), "BASELINE", 9, T.C.TEXT_DIM)
        T.text(surf, (cx[0], y + 40), f"{base.get('acq',0):.2f}s", 9, T.C.TEXT_DIM)
        T.text(surf, (cx[1], y + 40), f"{base.get('mean_deg',0):.3f}", 9, T.C.TEXT_DIM)
        T.text(surf, (cx[2], y + 40), f"{base.get('ret_pct',0):.0f}", 9, T.C.TEXT_DIM)
        T.text(surf, (cx[3], y + 40), f"{base.get('false_locks',0)}", 9, T.C.RED)
        # ADAPTIVE row (highlight)
        ada = row.get("adaptive", {})
        T.text(surf, (x + 12, y + 58), "ADAPTIVE", 9, T.C.GREEN, bold=True)
        T.text(surf, (cx[0], y + 58), f"{ada.get('acq',0):.2f}s", 9, T.C.TEXT)
        T.text(surf, (cx[1], y + 58), f"{ada.get('mean_deg',0):.3f}", 9, T.C.GREEN, bold=True)
        T.text(surf, (cx[2], y + 58), f"{ada.get('ret_pct',0):.0f}", 9, T.C.TEXT)
        T.text(surf, (cx[3], y + 58), f"{ada.get('false_locks',0)}", 9, T.C.GREEN, bold=True)
        # divider + takeaway
        pygame.draw.line(surf, T.C.BORDER, (x + 10, y + 76), (x + w - 10, y + 76), 1)
        T.text(surf, (x + 12, y + 84), "False locks: baseline can't reject distractors;", 8, T.C.TEXT_FAINT)
        T.text(surf, (x + 12, y + 96), "it locks the brightest blob, whatever it is.", 8, T.C.TEXT_FAINT)
        T.text(surf, (x + 12, y + 112), "Adaptive verifies 15 Hz modulation + ephemeris", 8, T.C.TEXT_FAINT)
        T.text(surf, (x + 12, y + 124), "before LOCK - near-zero false locks, lower error.", 8, T.C.TEXT_FAINT)
        T.text(surf, (x + 12, y + 142), "Re-run: python -m metrics.compare_trackers", 8, T.C.TEXT_FAINT)

    def _panel_disturbances(self, surf):
        x, y, w, h = 1288, 572, 304, 174
        T.panel(surf, pygame.Rect(x, y, w, h))
        kind = disturbance_kind_label(self.platform_mode)
        T.text(surf, (x + 10, y + 5), f"DISTURBANCES · {kind}", 9, T.C.TEXT_FAINT)
        note = ("N/A · vacuum" if not self._atmosphere_allowed() else "active")
        T.text(surf, (x + w - 8, y + 5), note, 7, T.C.TEXT_FAINT, anchor="tr")
        pygame.draw.line(surf, T.C.BORDER, (x + 8, y + 16), (x + w - 8, y + 16), 1)
        for key, s in self.sliders.items():
            s.draw(surf)
            unit = config.DISTURBANCE_UNITS.get(key, (None, ""))[1]
            if unit:
                T.text(surf, (s.rect.right, s.rect.y - 8), unit, 7, T.C.TEXT_FAINT, anchor="tr")

    def _panel_controls(self, surf):
        x, y, w, h = 1288, 756, 304, 138
        T.panel(surf, pygame.Rect(x, y, w, h))
        T.text(surf, (x + 10, y + 5), "CONTROLS", 9, T.C.TEXT_FAINT)
        pygame.draw.line(surf, T.C.BORDER, (x + 8, y + 16), (x + w - 8, y + 16), 1)
        for b in self.buttons.values():
            b.draw(surf)


def _bracket(surf, center, color, r, th):
    x, y = center
    L = r
    for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        pygame.draw.line(surf, color, (x + dx * r, y + dy * L), (x + dx * r, y + dy * (r - L // 2)), th)
        pygame.draw.line(surf, color, (x + dx * r, y + dy * L), (x + dx * (r - L // 2), y + dy * L), th)


def headless_selftest(frames, preset, platform=None, atmosphere=None,
                      motion_type=None, target_shape=None, target_size=None,
                      num_targets=None, target_initial=None):
    print(f"headless self-test: preset={preset} frames={frames}")
    sim = Simulator(preset_name=preset, seed=1,
                    platform_mode=platform, atmosphere=atmosphere,
                    motion_type=motion_type,
                    target_shape=target_shape, target_size=target_size,
                    num_targets=num_targets, target_initial=target_initial)
    perf = PerformanceTracker()
    t0 = time.time()
    for _ in range(frames):
        sim.step()
        perf.record_frame(sim)
    wall = time.time() - t0
    st = perf.live_stats()
    print(f"state={sim.state} acq={st['acquisition_time_s']} "
          f"retention={st['retention_total_pct']:.1f}% "
          f"mean_err={st['mean_err_deg']} rms={st['rms_err_deg']} "
          f"fps={frames / wall:.1f} false_lock={st['false_lock_events']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="EASY")
    ap.add_argument("--frames", type=int, default=0, help="headless self-test frame count")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--platform", default=None,
                    choices=["SATELLITE_SATELLITE", "UAV_SATELLITE", "UAV_UAV"],
                    help="FSOC platform mode (PS 26169)")
    ap.add_argument("--atmosphere", default=None,
                    choices=["CLEAR", "HAZE", "FOG", "RAIN", "LOW_LIGHT"],
                    help="atmospheric condition (PS 26169)")
    ap.add_argument("--motion", default=None,
                    choices=["straight_line", "circular", "figure_eight",
                             "random", "spiral", "sinusoidal"],
                    help="target motion type (PS: selectable, at least four)")
    ap.add_argument("--shape", default=None,
                    choices=["SQUARE", "CIRCLE", "SPOT"],
                    help="target shape (PS: user-defined, default Square)")
    ap.add_argument("--size", type=int, default=None,
                    help="target size in pixels (PS: 5-20, default 10)")
    ap.add_argument("--targets", type=int, default=None,
                    help="number of targets (PS: 1 mandatory, multiple optional)")
    ap.add_argument("--initial", default=None,
                    choices=["RANDOM", "CENTER"],
                    help="initial target location (PS: user-defined, default Random)")
    ap.add_argument("--video", default=None,
                    help="Benchmark-2: path to an .mp4 that drives the "
                         "coarse-pointing loop (bypasses the virtual PTZ). "
                         "A <video>_truth.csv sidecar enables ground-truth "
                         "centroiding-error evaluation.")
    ap.add_argument("--video-seed", type=int, default=None,
                    help="RNG seed for the video-mode tracker (reproducible "
                         "demo); omit for random behaviour per run.")
    args = ap.parse_args()

    if args.frames > 0:
        headless_selftest(args.frames, args.preset.upper(),
                          args.platform, args.atmosphere,
                          args.motion, args.shape, args.size,
                          args.targets, args.initial)
        return

    app = App(preset=args.preset.upper(), fullscreen=args.fullscreen,
              platform_mode=args.platform, atmosphere=args.atmosphere,
              motion_type=args.motion, target_shape=args.shape,
              target_size=args.size, num_targets=args.targets,
              target_initial=args.initial, video_path=args.video,
              video_seed=args.video_seed)
    app.run()


if __name__ == "__main__":
    main()