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
                                   self.sim.preset.get("turbulence", 0), T.C.PURPLE),
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
    def sync_sliders(self):
        for key, s in self.sliders.items():
            s.value = self.sim.disturbance.__getattribute__(key)

    def apply_sliders(self):
        d = self.sim.disturbance
        d.turbulence = int(self.sliders["turbulence"].value)
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
                self.platform_mode = pm
                self._reset()
        elif pygame.K_a == key:
            names = list(self.atmos_chips.keys())
            idx = (names.index(self.atmosphere) + 1) % len(names)
            self.atmosphere = names[idx]
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
                self.platform_mode = name
                self._reset()
                return
        for name, c in self.atmos_chips.items():
            if button == 1 and c.hit(pos):
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
        # --- layered header background ---
        pygame.draw.rect(surf, T.C.BG, (0, 0, APP_W, 48))
        pygame.draw.rect(surf, T.C.PANEL, (0, 0, APP_W, 46))
        # cyan accent top stripe
        pygame.draw.rect(surf, T.C.CYAN, (0, 0, APP_W, 2))
        pygame.draw.line(surf, T.C.BORDER_B, (0, 47), (APP_W, 47), 1)

        # title block
        pygame.draw.rect(surf, T.C.PANEL_2, (0, 2, 175, 44))
        pygame.draw.line(surf, T.C.BORDER_B, (175, 2), (175, 46), 1)
        T.text(surf, (10, 7), "FSOC-PAT", 17, T.C.CYAN, bold=True)
        T.text(surf, (10, 28), "MISSION CONTROL", 8, T.C.TEXT_DIM)

        # live state badge
        res = self.sim.last_result
        st = res.get("state", "SEARCHING")
        st_col = T.C.STATE.get(st, T.C.CYAN)
        st_fill = T.C.STATE_FILL.get(st, (0, 30, 50))
        badge_r = pygame.Rect(182, 8, 110, 30)
        pygame.draw.rect(surf, st_fill, badge_r, border_radius=3)
        pygame.draw.rect(surf, st_col, badge_r, 1, border_radius=3)
        T.text(surf, (badge_r.centerx, badge_r.centery), st, 12, st_col,
               bold=True, anchor="cc")

        # mission elapsed time
        elapsed = res.get("t", 0.0)
        T.text(surf, (302, 5), "ELAPSED", 7, T.C.TEXT_FAINT)
        T.text(surf, (302, 15), f"{elapsed:8.2f} s", 14, T.C.TEXT, bold=True)

        # pointing error quick readout
        err = res.get("pointing_err_deg", 0.0)
        ec = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else (T.C.AMBER if err < 0.30 else T.C.RED)
        T.text(surf, (400, 5), "POINT ERR", 7, T.C.TEXT_FAINT)
        T.text(surf, (400, 15), f"{err * 1000:6.1f} mdeg", 14, ec, bold=True)

        # scenario chips - label sits on its own line above the chip row so
        # it never collides with the first chip's border/text
        first_chip_x = min(c.rect.x for c in self.chips.values())
        T.text(surf, (first_chip_x, 2), "SCENARIO", 8, T.C.TEXT_FAINT)
        for name, c in self.chips.items():
            c.draw(surf, selected=(name == self.preset))
        # platform mode chips
        pm0 = min(c.rect.x for c in self.platform_chips.values())
        T.text(surf, (pm0, 2), "PLATFORM", 8, T.C.TEXT_FAINT)
        for name, c in self.platform_chips.items():
            sel = (name == self.platform_mode)
            c.draw(surf, selected=sel)
        # atmosphere chips
        at0 = min(c.rect.x for c in self.atmos_chips.values())
        T.text(surf, (at0, 2), "ATMOSPHERE", 8, T.C.TEXT_FAINT)
        for name, c in self.atmos_chips.items():
            c.draw(surf, selected=(name == self.atmosphere))
        # SIH label
        T.text(surf, (APP_W - 12, 8), "SIH 2026", 11, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (APP_W - 12, 24), "PS 26169", 9, T.C.TEXT_FAINT, anchor="tr")

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
        pygame.draw.rect(surf, T.C.BORDER, dest, 1)
        # PAT state stepper + crosshair callouts live in the app-space overlay
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
        """Horizontal PAT state-machine strip: PREDICT → POINT → SEARCH →
        ACQUIRE → TRACK → LOCK, with the active stage highlighted and the
        loss/reacquire branch shown when coasting/searching."""
        res = self.sim.last_result
        st = res["state"]
        steps = ["PREDICT", "POINT", "SEARCH", "TRACK", "LOCK"]
        idx = {"SEARCHING": 2, "REACQUIRING": 2, "COASTING": 3,
               "LOCKED": 4, "DEGRADED_LOCK": 4}.get(st, 0)
        box = pygame.Rect(dest.x + 8, dest.y + 8, dest.w - 16, 30)
        pygame.draw.rect(surf, (8, 12, 20), box)
        pygame.draw.rect(surf, T.C.BORDER, box, 1)
        n = len(steps)
        widths = [box.w / n] * n
        x = box.x
        for i, (step, w) in enumerate(zip(steps, widths)):
            active = i == idx
            col = T.C.STATE[st] if active else T.C.TEXT_FAINT
            if active:
                pygame.draw.rect(surf, tuple(c // 5 for c in col),
                                 (x, box.y, w - 1, box.h))
            T.text(surf, (x + w / 2, box.centery), step, 11,
                   col, bold=active, anchor="cc")
            if i < n - 1:
                pygame.draw.line(surf, T.C.BORDER, (x + w, box.y + 4),
                                 (x + w, box.bottom - 4), 1)
            x += w
        # loss / reacquire flash when coasting or re-searching
        if st == "COASTING":
            self._stepper_badge(surf, box, "PREDICTIVE COAST", T.C.CYAN)
        elif st == "SEARCHING":
            self._stepper_badge(surf, box, "SEARCHING / LOST", T.C.AMBER)
        elif st == "REACQUIRING":
            self._stepper_badge(surf, box, "RE-ACQUIRING · SEARCH", T.C.PURPLE)

    def _stepper_badge(self, surf, box, label, col):
        # keep the badge clear of the right sidebar (starts at x=1280) -
        # a fixed 170px width ran text like "SEARCHING / LOST" straight
        # into the sidebar and got clipped by it.
        max_right = 1272
        avail = max_right - (box.right + 8)
        w = max(60, min(170, avail))
        r = pygame.Rect(box.right + 8, box.y, w, box.h)
        pygame.draw.rect(surf, tuple(c // 5 for c in col), r)
        pygame.draw.rect(surf, col, r, 1)
        font_size = 11 if w >= 150 else 9
        T.text(surf, (r.centerx, r.centery), label, font_size, col, bold=True, anchor="cc")

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
        r = pygame.Rect(dest.x + 8, dest.bottom - 38, dest.w - 8, 30)
        fill = T.C.STATE_FILL.get(res["state"], (0, 20, 30))
        pygame.draw.rect(surf, fill, r, border_radius=2)
        pygame.draw.rect(surf, col, r, 1, border_radius=2)
        pygame.draw.rect(surf, col, (r.x, r.y, 4, r.h), border_radius=1)
        T.text(surf, (r.x + 14, r.centery), label, 13, col, bold=True, anchor="cc")
        # live pointing error, giant, bottom-right of the camera
        err = res["pointing_err_deg"]
        ec = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else \
             (T.C.AMBER if err < 0.30 else T.C.RED)
        T.text(surf, (dest.right - 12, dest.y + 46), "POINTING ERROR", 9, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (dest.right - 12, dest.y + 58), f"{err * 1000:7.1f} mdeg", 26, ec, bold=True, anchor="tr")

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
            pygame.draw.line(cam, (40, 60, 80), (cx, r.top), (cx, r.bottom), 1)
            pygame.draw.line(cam, (40, 60, 80), (r.left, cy), (r.right, cy), 1)

        # ---- optical boresight reticle (Sat A beam LOS) ----
        bp = self._est_pixel(self.sim.gimbal.pan, self.sim.gimbal.tilt)
        if bp is not None:
            bx, by = bp
            reticle_col = (80, 160, 220)
            T.draw_glow(cam, (bx, by), 20, reticle_col, alpha=40)
            pygame.draw.circle(cam, reticle_col, (bx, by), 12, 1)
            pygame.draw.circle(cam, reticle_col, (bx, by), 4, 1)
            pygame.draw.line(cam, reticle_col, (bx - 22, by), (bx - 14, by), 1)
            pygame.draw.line(cam, reticle_col, (bx + 14, by), (bx + 22, by), 1)
            pygame.draw.line(cam, reticle_col, (bx, by - 22), (bx, by - 14), 1)
            pygame.draw.line(cam, reticle_col, (bx, by + 14), (bx, by + 22), 1)
            if _label_clear((bx, by)):
                T.text(cam, (bx, by - 28), "OPTICAL BORESIGHT", 8, reticle_col, anchor="cc")

        # ---- tracked / candidate overlays ----
        for i, c in enumerate(res.get("cand_list", [])):
            # distractors / un-locked candidates stay in dim cyan boxes
            col = T.C.CYAN_DIM
            box = pygame.Rect(int(c.u) - 8, int(c.v) - 8, 16, 16)
            pygame.draw.rect(cam, col, box, 1)
        if assoc is not None and res["state"] in LOCKED_STATES:
            apx, apy = int(assoc.u), int(assoc.v)
            # bright tracking ring + glow on the detected beacon
            ring_col = T.C.GREEN if res["state"] == "LOCKED" else T.C.GREEN_DIM
            T.draw_glow(cam, (apx, apy), 26, ring_col, alpha=70)
            pygame.draw.circle(cam, ring_col, (apx, apy), 14, 2)
            pygame.draw.circle(cam, ring_col, (apx, apy), 20, 1)
            pygame.draw.circle(cam, ring_col, (apx, apy), 26, 1)
            _bracket(cam, (apx, apy), ring_col, 30, 2)
            pygame.draw.line(cam, ring_col, (apx - 32, apy), (apx - 20, apy), 2)
            pygame.draw.line(cam, ring_col, (apx + 20, apy), (apx + 32, apy), 2)
            pygame.draw.line(cam, ring_col, (apx, apy - 32), (apx, apy - 20), 2)
            pygame.draw.line(cam, ring_col, (apx, apy + 20), (apx, apy + 32), 2)
            T.text(cam, (apx, apy - 36), "SAT-B BEACON", 9, ring_col, bold=True, anchor="cc")
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
        if res["state"] == "SEARCHING":
            t = self.sim.tracker
            sa, se = t.search_angle, t.search_radius
            base = (t.est_az if t.est_az is not None else res["truth_az"],
                    t.est_el if t.est_el is not None else res["truth_el"])
            for k in range(14):
                a = sa + k * 0.55
                rr = se * (1 + k / 14.0)
                p = self._est_pixel(base[0] + rr * np.cos(a), base[1] + rr * np.sin(a))
                if p is not None:
                    pygame.draw.circle(cam, T.C.AMBER, p, 1)

        # ---- occluded banner ----
        if not res["beacon_visible"]:
            T.text(cam, (r.centerx, 12), "-- OCCLUDED --", 13, T.C.RED, anchor="cc")

        # ---- state badge + confidence ----
        st = res["state"]
        col = T.C.STATE.get(st, T.C.CYAN)
        fill = T.C.STATE_FILL.get(st, (0, 30, 50))
        badge = pygame.Rect(10, 10, 130, 34)
        pygame.draw.rect(cam, fill, badge, border_radius=3)
        pygame.draw.rect(cam, col, badge, 2, border_radius=3)
        T.draw_glow(cam, (badge.x + 3, badge.centery), 12, col, alpha=30)
        T.text(cam, (badge.x + 10, badge.y + 5), "STATE", 7, col)
        T.text(cam, (badge.centerx, badge.y + 19), st, 13, col, bold=True, anchor="cc")
        W.hbar(cam, (10, 50, 130, 5), res["confidence"], col)
        T.text(cam, (10, 58), f"CONF {res['confidence']:.2f}", 7, col)

        # ---- Phase 2 model-vision trust diagnostics (compact stack) ----
        # Part 3 renders the adaptive trust as a dual bar (VISION vs MODEL)
        # plus the live internal uncertainty and operating mode, and the phase /
        # derived-disturbance readout below it.
        tr = self.sim.tracker
        cf = getattr(tr, "conf", None)
        if cf is not None:
            snap = cf.snapshot()
            T.text(cam, (10, 48),
                   f"ID {snap['identity']:.2f}  POS {snap['position']:.2f}  "
                   f"PRED {snap['prediction']:.2f}  PT {snap['pointing']:.2f}",
                   8, T.C.TEXT_FAINT)
            tm = getattr(tr, "trust", None)
            if tm is not None:
                # VISION-trust bar (cyan) and MODEL-trust bar (purple), each
                # 0..1, with the current operating mode at the right edge
                W.hbar(cam, (10, 58, 92, 5), tm.vision_trust, T.C.CYAN)
                T.text(cam, (106, 55), f"VL {tm.vision_trust:.2f}",
                       8, T.C.TEXT_FAINT)
                W.hbar(cam, (10, 66, 92, 5), tm.model_trust, T.C.PURPLE)
                T.text(cam, (106, 63), f"ML {tm.model_trust:.2f}",
                       8, T.C.TEXT_FAINT)
                T.text(cam, (10, 74),
                       f"sigma {getattr(tr.unc, 'display_sigma_px', 0.0):.1f}px  "
                       f"[{tm.mode}]", 8, T.C.TEXT_FAINT)
            T.text(cam, (10, 86),
                   f"ph {getattr(tr, 'phase', res['state'])}  "
                   f"dist {getattr(tr, 'dist_level_est', 0.0):.2f}",
                   8, T.C.TEXT_FAINT)

        # ---- scenario / eval time (small, unobtrusive) ----
        T.text(cam, (r.right - 10, 6), f"t={res['t']:6.2f}s", 9, T.C.TEXT_FAINT, anchor="tr")

        # ---- GROUND TRUTH (evaluation-only, hidden in normal operation) ----
        # The algorithm never receives truth; this is display-only and clearly
        # labelled so the demo cannot look like it is given the answer.
        if self.show_gt:
            gp = self._est_pixel(res["truth_az"], res["truth_el"])
            if gp is not None:
                gx, gy = gp
                pygame.draw.circle(cam, T.C.PURPLE, (gx, gy), 5, 1)
                pygame.draw.line(cam, T.C.PURPLE, (gx - 7, gy), (gx + 7, gy), 1)
                pygame.draw.line(cam, T.C.PURPLE, (gx, gy - 7), (gx, gy + 7), 1)
            T.text(cam, (r.centerx, 4 ), "GROUND TRUTH · EVALUATION ONLY",
                   9, T.C.PURPLE, anchor="cc")

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
        pygame.draw.line(surf, T.C.BORDER, (8, 680), (1276, 680), 1)

        # ---- LIVE ANGULAR POINTING ERROR (the one meaningful graph) ----
        err_box = pygame.Rect(20, 690, 700, 192)
        self._draw_error_graph(surf, err_box)

        # ---- CAMERA / ACTUATOR + A->B beam ----
        self._draw_camera_panel(surf, pygame.Rect(740, 690, 524, 192))

    def _draw_error_graph(self, surf, box):
        T.text(surf, (box.x, box.y), "ANGULAR POINTING ERROR  (°)", 11, T.C.TEXT_DIM)
        T.text(surf, (box.right, box.y), "0.00 here = perfect coarse alignment",
               9, T.C.TEXT_FAINT, anchor="tr")
        plot = pygame.Rect(box.x, box.y + 18, box.w, box.h - 22)
        pygame.draw.rect(surf, T.C.PANEL_2, plot)
        pygame.draw.rect(surf, T.C.BORDER, plot, 1)
        # fine-acquisition band (green target region < 0.1 deg)
        _bound = plot.bottom - int(plot.h * (config.FINE_ACQUISITION_REGION_DEG / 0.5))
        pygame.draw.rect(surf, (14, 34, 24), (plot.x, _bound, plot.w, plot.bottom - _bound))
        # gridlines (0.1, 0.2, 0.3 deg)
        for deg, col in ((0.1, T.C.GREEN_DIM), (0.2, T.C.GRID), (0.3, T.C.GRID)):
            yy = plot.bottom - int(plot.h * (deg / 0.5))
            pygame.draw.line(surf, col, (plot.x, yy), (plot.right, yy), 1)
            T.text(surf, (plot.x + 4, yy - 7), f"{deg:.1f}", 8, T.C.TEXT_FAINT)
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
        # disturbance events: mark track-loss (beacon invisible) in red
        if not self.sim.last_result["beacon_visible"]:
            pygame.draw.rect(surf, (60, 20, 20), (plot.right - 3, plot.y, 3, plot.h))
        # Part 3: mission state rails from the event journal (event_log).
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
        T.text(surf, (plot.x, y - 9), "STATE", 7, T.C.TEXT_FAINT)

    def _draw_camera_panel(self, surf, box):
        res = self.sim.last_result
        T.text(surf, (box.x, box.y), "CAMERA / ACTUATOR", 11, T.C.TEXT_DIM)
        x = box.x + 14
        y = box.y + 24
        rows = [
            ("AZIMUTH", f"{self.sim.gimbal.pan:+.2f}°"),
            ("ELEVATION", f"{self.sim.gimbal.tilt:+.2f}°"),
            ("FOV", f"{config.HFOV_DEG:.1f}°"),
            ("MODE", "COARSE PAT"),
        ]
        for _ in range(2):
            for i, (lab, val) in enumerate(rows[0:2] if x == box.x + 14 else rows[2:4]):
                ly = y + i * 22
                T.text(surf, (x, ly), lab, 9, T.C.TEXT_FAINT)
                T.text(surf, (x + 92, ly), val, 12, T.C.TEXT)
            x += 210
        # slew / latency row
        T.text(surf, (box.x + 14, y + 52), "If tracking, gimbal is slewed to keep B in FOV", 9, T.C.TEXT_FAINT)

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
        T.text(surf, (box.right - 2, (ay + by) // 2), f"{err * 1000:6.1f} mdeg", 11, col,
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
        pygame.draw.rect(surf, T.C.PANEL, (1280, 48, 320, APP_H - 48))
        pygame.draw.line(surf, T.C.BORDER, (1280, 48), (1280, APP_H), 1)
        self._panel_mission(surf)
        self._panel_geometry(surf)
        self._panel_performance(surf)
        self._panel_comparison(surf)
        self._panel_disturbances(surf)
        self._panel_controls(surf)

    def _panel_mission(self, surf):
        x, y, w, h = 1288, 56, 304, 78
        T.panel(surf, pygame.Rect(x, y, w, h))
        T.text(surf, (x + 10, y + 6), "MISSION", 10, T.C.TEXT_DIM)
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
        pm_label = {"SATELLITE_SATELLITE": "SAT-SAT",
                    "UAV_SATELLITE": "UAV-SAT", "UAV_UAV": "UAV-UAV"}.get(
                        self.platform_mode, self.platform_mode)
        rows = [
            ("Observer", "SAT-A"),
            ("Target", "SAT-B  (optical beacon)"),
            ("Link", pm_label + "  ·  " + (self.atmosphere or "CLEAR")),
            ("Status", "TRACKING" if st in LOCKED_STATES else
                       ("SEARCH" if st == "SEARCHING" else "COAST")),
        ]
        yy = y + 22
        col = T.C.GREEN if lock else T.C.STATE[st]
        for lab, val in rows:
            T.text(surf, (x + 12, yy), lab, 10, T.C.TEXT_FAINT)
            T.text(surf, (x + 96, yy), val, 11, col if lab == "Status" else T.C.TEXT, bold=(lab == "Status"))
            yy += 14

    def _panel_geometry(self, surf):
        g = pygame.Rect(1288, 140, 304, 146)
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
        x, y, w, h = 1288, 572, 304, 172
        T.panel(surf, pygame.Rect(x, y, w, h))
        T.text(surf, (x + 10, y + 6), "DISTURBANCES  (active scenario)", 9, T.C.TEXT_DIM)
        for key, s in self.sliders.items():
            s.draw(surf)
            unit = config.DISTURBANCE_UNITS.get(key, (None, ""))[1]
            if unit:
                # drawn on the label's own line, right-aligned - drawing it
                # underneath the track used to collide with the next
                # slider's label above it.
                T.text(surf, (s.rect.right, s.rect.y - 6), unit, 8, T.C.TEXT_FAINT, anchor="tr")

    def _panel_controls(self, surf):
        x, y, w, h = 1288, 756, 304, 138
        T.panel(surf, pygame.Rect(x, y, w, h))
        T.text(surf, (x + 10, y + 6), "CONTROLS", 9, T.C.TEXT_DIM)
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