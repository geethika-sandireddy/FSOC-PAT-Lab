"""
main.py  —  FSOC-PAT Tactical Optical Acquisition Console  ·  SIH 2026 · PS 26169

Layout (1600 × 900):
  Header    : y   0 .. 60   — system ID, state chip, live metrics, scenario chips
  Camera    : x   0 ..1076  y 60 ..760  — 1076×700 sensor viewport
  Right panel: x 1080 ..1596  y 60 ..760  — 516×700 telemetry column
  Bottom    : y 760 ..900   — PAT pipeline stepper + error graph + beam strip

Keyboard:
  1-5  scenario preset   SPACE pause/resume   R reset   S screenshot
  6-8  platform mode     A cycle atmosphere   V FOV grid   F fullscreen
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
import config
from core.simulator import Simulator
from core.geometry import azel_unit, sd_angle_deg, project_point_into_camera
from core.platforms import atmosphere_allowed, disturbance_kind_label
from metrics.performance import PerformanceTracker
from ui import theme as T
from ui import widgets as W
from ui import view3d
from ui.mission_pages import (
    OpticalLinkModel,
    SimulationPageManager,
    render_overview_page,
    render_telemetry_page,
    render_false_lock_page,
    render_event_log_page,
)


APP_W, APP_H = 1600, 900
CAM_W, CAM_H = config.CAM_VIEW_W, config.CAM_VIEW_H
DISPLAY_CAP  = 60

LOCKED_STATES = ("LOCKED", "DEGRADED_LOCK")

# ── Layout constants ────────────────────────────────────────────────────────
SIDEBAR_W = 160
HDR_H     = 56
BTM_Y     = 740
BTM_H     = APP_H - BTM_Y          # 160
CAM_X0, CAM_X1 = SIDEBAR_W + 4, SIDEBAR_W + 1044  # 164 .. 1204 (w: 1040)
CAM_Y0, CAM_Y1 = HDR_H + 4, BTM_Y                 # 60 .. 740 (h: 680)
PNL_X0, PNL_X1 = SIDEBAR_W + 1052, APP_W - 6       # 1212 .. 1594 (w: 382)
PNL_W   = PNL_X1 - PNL_X0                         # 382
PNL_INN = PNL_X0 + 6                              # 1218
PNL_IW  = PNL_W - 12                              # 370


class App:
    # camera region class attrs (used by _cam_scale / _cam_dest)
    CAM_X0, CAM_X1 = CAM_X0, CAM_X1
    CAM_Y0, CAM_Y1 = CAM_Y0, CAM_Y1

    def __init__(self, preset="EASY", seed=None, fullscreen=True,
                 platform_mode=None, atmosphere=None,
                 motion_type=None, target_shape=None, target_size=None,
                 num_targets=None, target_initial=None,
                 video_path=None, video_seed=None):
        pygame.init()
        self.fullscreen = bool(fullscreen)
        flags = pygame.FULLSCREEN if self.fullscreen else 0
        self.screen = pygame.display.set_mode(
            (0, 0) if self.fullscreen else (APP_W, APP_H), flags)
        self.canvas = pygame.Surface((APP_W, APP_H)).convert()
        self._display_rect = pygame.Rect(0, 0, APP_W, APP_H)
        pygame.display.set_caption(
            "FSOC-PAT Mission Control Console  ·  SIH 2026 · PS 26169")
        self.clock = pygame.time.Clock()

        # SpaceX Navigation System
        self.SIDEBAR_TABS = [
            ("VIRTUAL ENV", "ENV", "01"),
            ("OVERVIEW",    "OVR", "02"),
            ("TELEMETRY",   "TEL", "03"),
            ("SIMULATION",  "SIM", "04"),
            ("FALSE LOCK",  "FLK", "05"),
            ("EVENT LOG",   "EVT", "06"),
        ]
        self.active_tab = 0  # 0: VIRTUAL ENV (Default on launch!)
        self.opt_model = OpticalLinkModel()
        self.sim_page_mgr = SimulationPageManager(
            pygame.Rect(SIDEBAR_W + 16, HDR_H + 12, APP_W - SIDEBAR_W - 32, APP_H - HDR_H - 24)
        )
        self.events_list = [
            (time.strftime("%H:%M:%S UTC", time.gmtime()), "INFO", "OPT-LINK", "Carrier acquisition confirmed. Coarse alignment loop ACTIVE"),
            (time.strftime("%H:%M:%S UTC", time.gmtime()), "INFO", "TRACKER", "State transition: SEARCHING -> LOCKED (pointing error <= 10 px)"),
            (time.strftime("%H:%M:%S UTC", time.gmtime()), "INFO", "GIMBAL", "PD servo converged: Pan slew 0.12 deg/s, Tilt slew -0.04 deg/s"),
            (time.strftime("%H:%M:%S UTC", time.gmtime()), "INFO", "CLASSIF", "Beacon spot classified: circularity 0.94, SNR 73.4 dB, corr > 0.62"),
            (time.strftime("%H:%M:%S UTC", time.gmtime()), "INFO", "SUBSYS", "All 6 optical subsystems report nominal health"),
        ]
        self._last_state = "SEARCHING"
        self.hdr_pause_rect = pygame.Rect(APP_W - 86, 12, 74, 32)

        self.preset        = preset
        self.platform_mode = platform_mode or "SATELLITE_SATELLITE"
        self.atmosphere    = atmosphere or "CLEAR"
        from core.platforms import atmosphere_allowed
        if not atmosphere_allowed(self.platform_mode) and self.atmosphere != "CLEAR":
            self.atmosphere = "CLEAR"
        self.motion_override  = motion_type
        self.shape_override   = target_shape
        self.size_override    = target_size
        self.targets_override = num_targets
        self.initial_override = target_initial
        self.video_path       = video_path
        self.video_done       = False
        self.video_seed       = video_seed

        if video_path:
            from core.simulator import VideoInputSimulator
            truth = os.path.splitext(video_path)[0] + "_truth.csv"
            self.sim = VideoInputSimulator(
                video_path, seed=video_seed,
                truth_csv=truth if os.path.isfile(truth) else None)
            self.video_mode = True
        else:
            self.sim = Simulator(
                preset_name=preset, seed=seed,
                platform_mode=self.platform_mode,
                atmosphere=self.atmosphere,
                motion_type=self.motion_override,
                target_shape=self.shape_override,
                target_size=self.size_override,
                num_targets=self.targets_override,
                target_initial=self.initial_override)
            self.video_mode = False

        self.perf       = PerformanceTracker()
        self.paused     = False
        self.show_fov_grid = True
        self.eph_pred_az   = None
        self.eph_pred_el   = None
        self.show_gt    = False
        self.show_diag  = False
        self.compare    = self._load_compare()
        self.error_spark = deque(maxlen=1800)
        self._scanline_surf = None   # created lazily on first camera draw

        # ── Sliders (right panel disturbances section) ──────────────────
        _sx, _sw = PNL_INN + 2, PNL_IW - 4
        self.sliders = {
            "turbulence":  W.Slider((_sx, 588, _sw, 20), "TURBULENCE",
                                    self.sim.preset.get("turbulence", 0), T.C.PURPLE,
                                    enabled=atmosphere_allowed(self.platform_mode)),
            "vibration":   W.Slider((_sx, 616, _sw, 20), "VIBRATION",
                                    self.sim.preset.get("vibration", 0), T.C.AMBER),
            "sensor_noise": W.Slider((_sx, 644, _sw, 20), "SENSOR NOISE",
                                     self.sim.preset.get("sensor_noise", 0), T.C.RED),
            "jerk_prob":   W.Slider((_sx, 672, _sw, 20), "JERK PROB",
                                    self.sim.preset.get("jerk_prob", 0), T.C.CYAN),
            "beacon_fade": W.Slider((_sx, 700, _sw, 20), "BEACON FADE",
                                    self.sim.preset.get("beacon_fade", 0), T.C.AMBER_DIM),
        }

        # ── Buttons (right panel controls section) ──────────────────────
        bw, bh, bx0 = 118, 26, PNL_INN + 2
        self.buttons = {
            "PAUSE":      W.Button((bx0,       736, bw, bh), "PAUSE",  T.C.AMBER),
            "RESET":      W.Button((bx0 + 122, 736, bw, bh), "RESET",  T.C.CYAN),
            "SHOT":       W.Button((bx0 + 244, 736, bw, bh), "SHOT",   T.C.GREEN),
            "GT":         W.Button((bx0,       768, bw, bh), "GT OFF", T.C.PURPLE),
            "DIAG":       W.Button((bx0 + 122, 768, bw, bh), "DIAG",   T.C.TEXT_DIM),
            "LOAD_VIDEO": W.Button((bx0 + 244, 768, bw, bh), "LOAD MP4", T.C.AMBER),
        }
        self._screenshot_n = 0

        # ── Header chips ────────────────────────────────────────────────
        self.chips = {}
        xs = SIDEBAR_W + 680
        for name in config.PRESET_ORDER:
            self.chips[name] = W.Chip((xs, 14, 58, 26), name, T.C.CYAN)
            xs += 62

        self.platform_chips = {}
        px = SIDEBAR_W + 1000
        for pm in ["SATELLITE_SATELLITE", "UAV_SATELLITE", "UAV_UAV"]:
            lbl = {"SATELLITE_SATELLITE": "SAT-SAT",
                   "UAV_SATELLITE": "UAV-SAT",
                   "UAV_UAV": "UAV-UAV"}[pm]
            self.platform_chips[pm] = W.Chip((px, 14, 68, 26), lbl, T.C.GREEN)
            px += 72

        self.atmos_chips = {}
        ax = SIDEBAR_W + 1224
        for atm in ["CLEAR", "HAZE", "FOG", "RAIN", "LOW_LIGHT"]:
            self.atmos_chips[atm] = W.Chip((ax, 14, 56, 26), atm, T.C.AMBER)
            ax += 60

    # ------------------------------------------------------------------
    def _atmosphere_allowed(self):
        from core.platforms import atmosphere_allowed
        return atmosphere_allowed(self.platform_mode)

    def _platform_label(self):
        return {"SATELLITE_SATELLITE": "SAT-SAT",
                "UAV_SATELLITE":       "UAV-SAT",
                "UAV_UAV":             "UAV-UAV"}.get(self.platform_mode, self.platform_mode)

    def _platform_atm_default(self):
        from core.platforms import PLATFORM_MODES
        pm = PLATFORM_MODES.get(self.platform_mode, {})
        return pm.get("atmosphere", "CLEAR")

    def _select_platform(self, pm):
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
        d.vibration    = int(self.sliders["vibration"].value)
        d.sensor_noise = int(self.sliders["sensor_noise"].value)
        d.jerk_prob    = int(self.sliders["jerk_prob"].value)
        d.beacon_fade  = int(self.sliders["beacon_fade"].value)

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
                    self._mouse_down(self._logical_mouse_pos(ev.pos), ev.button)
                elif ev.type == pygame.MOUSEBUTTONUP:
                    for s in self.sliders.values():
                        s.dragging = False
                    self.sim_page_mgr.handle_mouse_up()
                elif ev.type == pygame.MOUSEMOTION:
                    self._mouse_move(self._logical_mouse_pos(ev.pos), ev.buttons)

            if not self.paused and not self.video_done:
                res = self.sim.step()
                if res is None:
                    self.video_done = True
                    self._draw()
                    pygame.display.flip()
                    break
                self.perf.record_frame(self.sim)
                if res["state"] in LOCKED_STATES:
                    self.error_spark.append(res["pointing_err_deg"])
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
        elif pygame.K_TAB == key:
            self.active_tab = (self.active_tab + 1) % len(self.SIDEBAR_TABS)
        elif pygame.K_F1 <= key <= pygame.K_F6:
            self.active_tab = key - pygame.K_F1
        elif pygame.K_r == key:
            self._reset()
        elif pygame.K_s == key:
            self._screenshot()
        elif pygame.K_l == key:
            self._load_video()
        elif pygame.K_v == key:
            self.show_fov_grid = not self.show_fov_grid
        elif pygame.K_f == key:
            self._toggle_fullscreen()
        elif self.active_tab == 0:
            if pygame.K_1 <= key <= pygame.K_5:
                name = config.PRESET_ORDER[key - pygame.K_1]
                self.preset = name
                self._reset(name)
            elif pygame.K_6 <= key <= pygame.K_8:
                pm = list(self.platform_chips.keys())[key - pygame.K_6]
                if pm != self.platform_mode:
                    self._select_platform(pm)
            elif pygame.K_a == key:
                allowed = [n for n in self.atmos_chips
                           if n == "CLEAR" or self._atmosphere_allowed()]
                if allowed:
                    idx = (allowed.index(self.atmosphere) + 1) % len(allowed)
                    self.atmosphere = allowed[idx]
                    self._reset()
        elif 0 <= key - pygame.K_1 < len(self.SIDEBAR_TABS):
            self.active_tab = key - pygame.K_1
        return True

    def _logical_mouse_pos(self, pos):
        """Map a physical display coordinate into the logical UI canvas."""
        if self._display_rect.w <= 0 or self._display_rect.h <= 0:
            return pos
        x = (pos[0] - self._display_rect.x) * APP_W / self._display_rect.w
        y = (pos[1] - self._display_rect.y) * APP_H / self._display_rect.h
        return int(x), int(y)

    def _toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        flags = pygame.FULLSCREEN if self.fullscreen else 0
        self.screen = pygame.display.set_mode(
            (0, 0) if self.fullscreen else (APP_W, APP_H), flags)
        self._scanline_surf = None

    def _present_canvas(self):
        """Scale the fixed mission-console canvas into the current display."""
        dw, dh = self.screen.get_size()
        scale = min(dw / APP_W, dh / APP_H)
        scaled_size = (max(1, int(APP_W * scale)), max(1, int(APP_H * scale)))
        self._display_rect = pygame.Rect(
            (dw - scaled_size[0]) // 2,
            (dh - scaled_size[1]) // 2,
            scaled_size[0], scaled_size[1])
        self.screen.fill(T.C.BG)
        scaled = pygame.transform.smoothscale(self.canvas, scaled_size)
        self.screen.blit(scaled, self._display_rect.topleft)

    def _mouse_down(self, pos, button):
        # 1. Check sidebar tabs
        if button == 1 and pos[0] < SIDEBAR_W:
            for i in range(len(self.SIDEBAR_TABS)):
                tab_rect = pygame.Rect(0, 66 + i * 56, SIDEBAR_W, 52)
                if tab_rect.collidepoint(pos):
                    self.active_tab = i
                    return

        # 2. Check top header pause toggle
        if button == 1 and hasattr(self, "hdr_pause_rect") and self.hdr_pause_rect.collidepoint(pos):
            self.paused = not self.paused
            self.buttons["PAUSE"].label = "RESUME" if self.paused else "PAUSE"
            return

        # 3. Handle active view controls
        if self.active_tab == 0:
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
                        b.label = "DIAG ‹" if self.show_diag else "DIAG"
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
        elif self.active_tab == 3:
            self.sim_page_mgr.handle_mouse_down(pos)

    def _mouse_move(self, pos, buttons):
        if self.active_tab == 0:
            for s in self.sliders.values():
                if s.dragging and buttons[0]:
                    s.drag_to(pos[0])
        elif self.active_tab == 3:
            self.sim_page_mgr.handle_mouse_move(pos, buttons)

    def _reset(self, name=None):
        if self.video_mode:
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
        self.sim = Simulator(
            preset_name=name or self.preset, seed=None,
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
        path = os.path.join(
            config.LOG_DIR,
            f"shot_{self.preset.lower()}_{self._screenshot_n}.png")
        pygame.image.save(self.screen, path)
        print(f"screenshot -> {path}", flush=True)

    def _load_video(self):
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Load Benchmark-2 video (.mp4)",
                filetypes=[("MP4 video", "*.mp4"),
                           ("Video files", "*.mp4;*.avi"),
                           ("All files", "*.*")])
            root.destroy()
        except Exception as ex:
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
        self.video_mode  = True
        self.video_done  = False
        self.preset      = "VIDEO"
        self.perf        = PerformanceTracker()
        self.error_spark.clear()
        self.sync_sliders()
        self.paused = False
        self.buttons["PAUSE"].label = "PAUSE"
        print(f"video loaded -> {path} "
              f"({self.sim.video_w}x{self.sim.video_h} @ {self.sim.video_fps:.1f} fps)")
        try:
            res = self.sim.step()
            if res is not None:
                self.perf.record_frame(self.sim)
        except Exception as ex:
            print(f"video step error: {ex}")

    def _final_report(self):
        st = self.perf.live_stats()
        p  = os.path.join(config.LOG_DIR, f"run_{int(time.time())}.csv")
        extra = {"preset": self.preset}
        if self.video_mode:
            extra["input_video"] = os.path.basename(self.video_path)
            errs = [e[1] for e in self.sim.centroid_err_log]
            if errs:
                extra["centroiding_error_mean_px"]  = round(float(np.mean(errs)), 2)
                extra["centroiding_error_rms_px"]   = round(
                    float(np.sqrt(np.mean(np.array(errs) ** 2))), 2)
                extra["centroiding_error_p95_px"]   = round(
                    float(np.percentile(errs, 95)), 2)
                extra["centroiding_error_max_px"]   = round(float(np.max(errs)), 2)
                extra["centroiding_frames"]          = len(errs)
            extra["reacquisition_count_video"] = len(self.sim.reacq_times)
            extra["video_false_lock_events"]   = self.sim.false_lock_events
        self.perf.write_log(p, extra_info=extra)
        print(f"performance log -> {p}")

    # ================================================================ DRAW
    def _draw(self):
        s = self.canvas
        s.fill(T.C.BG)

        # Update physical optical link model from live sim step
        res = self.sim.last_result
        hist_pt = self.opt_model.update_from_sim(res)

        # Record state change events
        cur_st = res.get("state", "SEARCHING")
        if cur_st != self._last_state:
            ts_str = time.strftime("%H:%M:%S UTC", time.gmtime())
            lvl = "INFO" if cur_st in LOCKED_STATES else ("WARNING" if cur_st in ("COASTING", "REACQUIRING") else "CRITICAL")
            self.events_list.insert(0, (ts_str, lvl, "TRACKER", f"State transition: {self._last_state} -> {cur_st} (error: {res.get('pointing_err_deg', 0)*1000:.1f} mdeg)"))
            if len(self.events_list) > 100:
                self.events_list.pop()
            self._last_state = cur_st

        # 1. Left Navigation Sidebar
        self._draw_sidebar(s)

        # 2. Top Mission Control Header
        self._draw_mission_header(s, hist_pt)

        # 3. Main Active Content View
        if self.active_tab == 0:
            # VIRTUAL ENVIRONMENT (Camera Viewport + HUD + Controls)
            self._draw_bg_grid(s)
            self._draw_camera(s)
            self._draw_panel(s)
            self._draw_bottom(s)
            self._draw_footer(s)
        elif self.active_tab == 1:
            # OVERVIEW (Figma Image 2)
            page_rect = pygame.Rect(SIDEBAR_W + 12, HDR_H + 12, APP_W - SIDEBAR_W - 24, APP_H - HDR_H - 24)
            render_overview_page(s, page_rect, self.sim, self.perf, self.opt_model, hist_pt)
        elif self.active_tab == 2:
            # TELEMETRY (Figma Image 1)
            page_rect = pygame.Rect(SIDEBAR_W + 12, HDR_H + 12, APP_W - SIDEBAR_W - 24, APP_H - HDR_H - 24)
            render_telemetry_page(s, page_rect, self.sim, self.perf, self.opt_model, hist_pt)
        elif self.active_tab == 3:
            # SIMULATION (Figma Images 3 & 4)
            self.sim_page_mgr.apply_to_model(self.opt_model)
            self.sim_page_mgr.draw(s, self.opt_model, hist_pt)
        elif self.active_tab == 4:
            # FALSE LOCK (Figma Image 5)
            page_rect = pygame.Rect(SIDEBAR_W + 12, HDR_H + 12, APP_W - SIDEBAR_W - 24, APP_H - HDR_H - 24)
            render_false_lock_page(s, page_rect, self.sim, self.perf, self.opt_model, hist_pt)
        elif self.active_tab == 5:
            # EVENT LOG
            page_rect = pygame.Rect(SIDEBAR_W + 12, HDR_H + 12, APP_W - SIDEBAR_W - 24, APP_H - HDR_H - 24)
            render_event_log_page(s, page_rect, self.sim, self.perf, self.opt_model, self.events_list)

        self._present_canvas()

    def _draw_sidebar(self, surf):
        pygame.draw.rect(surf, (8, 14, 26), (0, 0, SIDEBAR_W, APP_H))
        pygame.draw.line(surf, (20, 36, 62), (SIDEBAR_W - 1, 0), (SIDEBAR_W - 1, APP_H), 1)

        # Brand header at top of sidebar
        pygame.draw.rect(surf, (12, 20, 38), (0, 0, SIDEBAR_W, HDR_H))
        pygame.draw.line(surf, (20, 36, 62), (0, HDR_H - 1), (SIDEBAR_W, HDR_H - 1), 1)
        T.text(surf, (14, 10), "FSOC", 16, T.C.CYAN_ELEC, bold=True)
        T.text(surf, (14, 28), "PAT LAB · ISRO", 8, T.C.TEXT_DIM, bold=True)
        T.text(surf, (14, 40), "SIH 2026 · PS 26169", 7, T.C.TEXT_FAINT)

        # Tabs
        mouse_pos = self._logical_mouse_pos(pygame.mouse.get_pos())
        for i, (name, abbr, num) in enumerate(self.SIDEBAR_TABS):
            tab_y = 66 + i * 56
            tab_rect = pygame.Rect(0, tab_y, SIDEBAR_W, 52)
            is_active = (i == self.active_tab)
            is_hover = tab_rect.collidepoint(mouse_pos)

            if is_active:
                pygame.draw.rect(surf, (0, 32, 60), tab_rect)
                pygame.draw.rect(surf, T.C.CYAN_ELEC, (0, tab_y, 3, 52))
                title_col = T.C.CYAN_ELEC
                badge_col = T.C.CYAN_ELEC
            elif is_hover:
                pygame.draw.rect(surf, (14, 22, 40), tab_rect)
                title_col = T.C.TEXT
                badge_col = T.C.TEXT_DIM
            else:
                title_col = T.C.TEXT_DIM
                badge_col = T.C.TEXT_FAINT

            # Badge number
            T.text(surf, (14, tab_y + 11), num, 7, badge_col, bold=True)
            # Label
            T.text(surf, (32, tab_y + 10), name, 9, title_col, bold=True)
            # Abbr subtext
            T.text(surf, (32, tab_y + 26), abbr, 7, badge_col)

        # Bottom stats
        fps = self.clock.get_fps()
        fps_col = T.C.GREEN if fps >= 25 else T.C.AMBER
        T.text(surf, (14, APP_H - 42), f"FPS: {fps:.0f}", 9, fps_col, bold=True)
        T.text(surf, (14, APP_H - 26), "NATIVE DESKTOP", 7, T.C.TEXT_FAINT)
        T.text(surf, (14, APP_H - 14), "ISRO PAT CONSOLE", 7, T.C.TEXT_FAINT)

    def _draw_mission_header(self, surf, hist_pt):
        hdr_w = APP_W - SIDEBAR_W
        pygame.draw.rect(surf, (6, 12, 24), (SIDEBAR_W, 0, hdr_w, HDR_H))
        pygame.draw.line(surf, (20, 36, 62), (SIDEBAR_W, HDR_H - 1), (APP_W, HDR_H - 1), 1)

        # Cyan top accent line
        pygame.draw.rect(surf, T.C.CYAN, (SIDEBAR_W, 0, hdr_w, 2))

        # Title
        T.text(surf, (SIDEBAR_W + 16, 10), "FSOC MISSION CONTROL", 13, T.C.CYAN_ELEC, bold=True)
        T.text(surf, (SIDEBAR_W + 16, 28), "FREE-SPACE OPTICAL COMMS · PAT LAB · ISRO SIH 2026", 8, T.C.TEXT_FAINT)

        # Link State badge
        st = hist_pt.get("state", "ESTABLISHED")
        st_col = T.C.STATE.get(st, T.C.GREEN)
        badge_x = SIDEBAR_W + 350
        pygame.draw.rect(surf, (0, 32, 24), (badge_x, 10, 136, 36), border_radius=3)
        pygame.draw.rect(surf, T.C.BORDER, (badge_x, 10, 136, 36), 1, border_radius=3)
        T.text(surf, (badge_x + 10, 13), "LINK STATE", 7, T.C.TEXT_FAINT, bold=True)

        # Pulsing indicator dot
        p_alpha = int(180 + 75 * math.sin(time.time() * 5.0))
        dot_col = (0, min(255, p_alpha), 120) if st in LOCKED_STATES else st_col
        pygame.draw.circle(surf, dot_col, (badge_x + 16, 31), 4)
        T.text(surf, (badge_x + 26, 25), st, 9, st_col, bold=True)

        # Header live telemetry values
        def _h_val(x, lbl, val, unit, col=T.C.GREEN):
            T.text(surf, (x, 12), lbl, 7, T.C.TEXT_FAINT, bold=True)
            vw, vh = T.text(surf, (x, 25), val, 11, col, bold=True)
            if unit:
                T.text(surf, (x + vw + 3, 28), unit, 8, T.C.TEXT_DIM)

        _h_val(badge_x + 150, "RX POWER", f"{hist_pt.get('rx_power', -11.4):.1f}", "dBm", T.C.CYAN_ELEC)
        _h_val(badge_x + 235, "SNR", f"{hist_pt.get('snr', 73.6):.1f}", "dB", T.C.GREEN)
        _h_val(badge_x + 310, "MARGIN", f"{hist_pt.get('link_margin', 38.6):.1f}", "dB", T.C.GREEN)
        _h_val(badge_x + 395, "TRACKING", f"{int(round(hist_pt.get('stability', 96)))}", "%", T.C.CYAN_ELEC)

        # If in VIRTUAL ENV tab, draw scenario/platform/atmosphere chips!
        if self.active_tab == 0:
            for name, c in self.chips.items():
                c.draw(surf, selected=(name == self.preset))
            for name, c in self.platform_chips.items():
                c.draw(surf, selected=(name == self.platform_mode))
            for name, c in self.atmos_chips.items():
                enabled = (name == "CLEAR" or self._atmosphere_allowed())
                c.draw(surf, selected=(name == self.atmosphere), enabled=enabled)

        # UTC Clock
        utc_str = time.strftime("%Y-%m-%d  %H:%M:%S", time.gmtime())
        T.text(surf, (APP_W - 120, 13), "UTC", 7, T.C.TEXT_FAINT, anchor="tc")
        T.text(surf, (APP_W - 120, 26), utc_str, 9, T.C.TEXT, bold=True, anchor="tc")

        # PAUSE Button
        self.hdr_pause_rect = pygame.Rect(APP_W - 78, 12, 68, 32)
        btn_col = T.C.AMBER
        pygame.draw.rect(surf, (40, 24, 0), self.hdr_pause_rect, border_radius=2)
        pygame.draw.rect(surf, btn_col, self.hdr_pause_rect, 1, border_radius=2)
        pause_label = "RESUME" if self.paused else "PAUSE"
        T.text(surf, (self.hdr_pause_rect.centerx, self.hdr_pause_rect.centery - 5), pause_label, 8, btn_col, bold=True, anchor="cc")

    # ---------------------------------------------------------------- background grid
    def _draw_bg_grid(self, surf):
        col = (8, 15, 27)
        for x in range(SIDEBAR_W, APP_W, 120):
            pygame.draw.line(surf, col, (x, HDR_H), (x, BTM_Y), 1)
        for y in range(HDR_H, BTM_Y, 80):
            pygame.draw.line(surf, col, (SIDEBAR_W, y), (CAM_X1, y), 1)

    def _draw_footer(self, surf):
        T.text(surf, (SIDEBAR_W + 12, APP_H - 14),
               "TAB cycle view  ·  1-5 preset  ·  SPACE pause  ·  R reset  ·  S screenshot  ·  V FOV grid  ·  F fullscreen",
               8, T.C.TEXT_FAINT)

    # ---------------------------------------------------------------- camera
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

    def _draw_camera(self, surf):
        frame = self.sim.last_result.get("frame")
        cam   = self._frame_to_surf(frame)
        self._draw_hud(cam)
        fw, fh = self._frame_dims()
        sc = self._cam_scale()
        scaled = pygame.transform.smoothscale(cam, (int(fw * sc), int(fh * sc)))
        dest   = self._cam_dest()
        surf.blit(scaled, dest.topleft)

        # A restrained overlay keeps the viewport readable at projector distance.
        if (self._scanline_surf is None or
                self._scanline_surf.get_size() != (dest.w, dest.h)):
            self._scanline_surf = pygame.Surface((dest.w, dest.h), pygame.SRCALPHA)
            for yl in range(0, dest.h, 8):
                pygame.draw.line(self._scanline_surf, (0, 0, 0, 8),
                                 (0, yl), (dest.w, yl), 1)
        surf.blit(self._scanline_surf, dest.topleft)

        # State-reactive viewport border with glow
        st     = self.sim.last_result.get("state", "SEARCHING")
        vp_col = T.C.STATE.get(st, T.C.BORDER)
        # Pulsing glow on lock
        if st in LOCKED_STATES:
            p = T.pulse(1.5)
            gc = tuple(int(c * (0.4 + 0.6 * p)) for c in vp_col)
            pygame.draw.rect(surf, gc,      dest, 2)
            pygame.draw.rect(surf, T.C.BG,  pygame.Rect(dest.x - 2, dest.y - 2,
                                                         dest.w + 4, dest.h + 4), 1)
        elif st == "LOST":
            p = T.pulse(4.0)
            gc = tuple(int(c * (0.3 + 0.7 * p)) for c in vp_col)
            pygame.draw.rect(surf, gc, dest, 2)
        else:
            pygame.draw.rect(surf, vp_col, dest, 1)

        # Corner brackets around camera
        self._draw_corner_brackets(surf, dest, vp_col, 20, 2)
        self._draw_camera_story(surf, dest)

    def _frame_to_surf(self, frame):
        if frame is None:
            fw, fh = self._frame_dims()
            s = pygame.Surface((fw, fh))
            s.fill((0, 0, 0))
            return s
        img = np.ascontiguousarray(frame[:, :, ::-1])
        return pygame.surfarray.make_surface(img)

    @staticmethod
    def _draw_corner_brackets(surf, rect, color, arm, th=1):
        """Four-corner L-brackets around a rect."""
        for cx, cy, sx, sy in (
            (rect.x,     rect.y,      1,  1),
            (rect.right, rect.y,     -1,  1),
            (rect.x,     rect.bottom, 1, -1),
            (rect.right, rect.bottom,-1, -1),
        ):
            pygame.draw.line(surf, color,
                             (cx, cy), (cx + sx * arm, cy), th)
            pygame.draw.line(surf, color,
                             (cx, cy), (cx, cy + sy * arm), th)

    def _draw_camera_story(self, surf, dest):
        """Slim status strip at bottom of camera."""
        res = self.sim.last_result
        st  = res["state"]
        if not res["in_fov"]:
            label, col = "OUTSIDE FIELD OF VIEW", T.C.TEXT_FAINT
        elif st == "SEARCHING":
            label, col = "ACQUISITION WINDOW · SCANNING", T.C.AMBER
        elif st == "COASTING":
            label, col = "PREDICTIVE COAST · BEACON LOST", T.C.CYAN
        elif st == "LOCKED":
            label, col = "BEACON ACQUIRED · LOCKED", T.C.GREEN
        elif st == "DEGRADED_LOCK":
            label, col = "DEGRADED LOCK · CONFIDENCE LOW", T.C.GREEN_DIM
        elif st == "REACQUIRING":
            label, col = "BEACON LOST · RE-ACQUIRING", T.C.PURPLE
        else:
            label, col = "SEARCHING", T.C.AMBER

        r    = pygame.Rect(dest.x, dest.bottom - 30, dest.w, 30)
        fill = T.C.STATE_FILL.get(st, (0, 16, 26))
        # semi-transparent overlay
        ovl  = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        ovl.fill((*fill, 210))
        surf.blit(ovl, r.topleft)
        pygame.draw.rect(surf, col, (r.x, r.y, 4, r.h))
        pygame.draw.line(surf, col, (r.x, r.y), (r.right, r.y), 1)
        T.fit_text(surf, pygame.Rect(r.x + 10, r.y + 3, r.w - 20, r.h - 6),
               label, 11, col, bold=True, padding=2)

        acq_t = self.perf.live_stats().get("acquisition_time_s")
        if acq_t:
            T.text(surf, (r.right - 10, r.centery),
                   f"ACQ {acq_t:.2f}s", 9, T.C.TEXT_DIM, anchor="rc")

    # ---------------------------------------------------------------- HUD (native camera space)
    def _draw_hud(self, cam):
        r  = cam.get_rect()
        cx, cy = r.centerx, r.centery
        res = self.sim.last_result
        st  = res["state"]
        col = T.C.STATE.get(st, T.C.CYAN)

        # ── FOV reference grid ──────────────────────────────────────
        if self.show_fov_grid:
            gc = (22, 38, 58)
            pygame.draw.line(cam, gc, (cx, r.top), (cx, r.bottom), 1)
            pygame.draw.line(cam, gc, (r.left, cy), (r.right, cy), 1)
            # corner survey marks
            for cax, cay, dxa, dya in (
                (r.left+2, r.top+2, 1, 1),    (r.right-2, r.top+2, -1, 1),
                (r.left+2, r.bottom-2, 1, -1), (r.right-2, r.bottom-2, -1, -1),
            ):
                pygame.draw.line(cam, (44, 68, 94), (cax, cay), (cax + dxa*16, cay), 1)
                pygame.draw.line(cam, (44, 68, 94), (cax, cay), (cax, cay + dya*16), 1)
            rng = min(r.w, r.h) // 4
            for rr in (rng, rng * 2):
                pygame.draw.circle(cam, (18, 32, 52), (cx, cy), rr, 1)

        # ── beacon anchor (for label collision avoidance) ───────────
        assoc = self.sim.tracker.associated
        beacon_anchor = None
        if assoc is not None and st in LOCKED_STATES:
            beacon_anchor = (int(assoc.u), int(assoc.v))

        def _clear(pt, min_d=36, *others):
            for o in (beacon_anchor,) + others:
                if o is not None:
                    if (pt[0]-o[0])**2 + (pt[1]-o[1])**2 < min_d**2:
                        return False
            return True

        # ── Optical boresight reticle (mil-spec style) ──────────────
        bp = self._est_pixel(self.sim.gimbal.pan, self.sim.gimbal.tilt)
        if bp is not None:
            bx, by = bp
            rc  = (60, 120, 165)    # muted steel-blue
            rc2 = (40, 90, 130)
            gap, arm = 12, 40
            # gap crosshair
            pygame.draw.line(cam, rc, (bx - gap - arm, by), (bx - gap, by), 1)
            pygame.draw.line(cam, rc, (bx + gap, by),       (bx + gap + arm, by), 1)
            pygame.draw.line(cam, rc, (bx, by - gap - arm), (bx, by - gap), 1)
            pygame.draw.line(cam, rc, (bx, by + gap),       (bx, by + gap + arm), 1)
            # outer ring
            pygame.draw.circle(cam, rc2, (bx, by), 20, 1)
            # inner ring
            pygame.draw.circle(cam, rc, (bx, by), 8, 1)
            # center dot
            pygame.draw.circle(cam, rc, (bx, by), 2)
            # cardinal tick marks at 45°
            for ang in range(0, 360, 45):
                a = math.radians(ang)
                x1 = bx + int(22 * math.cos(a))
                y1 = by + int(22 * math.sin(a))
                x2 = bx + int(28 * math.cos(a))
                y2 = by + int(28 * math.sin(a))
                pygame.draw.line(cam, rc, (x1, y1), (x2, y2), 1)
            if _clear((bx, by)):
                T.text(cam, (bx + 52, by - 18), "BST",
                       7, rc, anchor="tl")
                T.text(cam, (bx + 52, by - 8),
                       f"Az{self.sim.gimbal.pan:+.1f}° El{self.sim.gimbal.tilt:+.1f}°",
                       6, rc, anchor="tl")

        # ── Candidate detections ─────────────────────────────────────
        for c in res.get("cand_list", []):
            cu, cv = int(c.u), int(c.v)
            arm = 6
            cand_col = (0, 72, 110)
            for sx, sy in ((-1,-1), (-1,1), (1,-1), (1,1)):
                pygame.draw.line(cam, cand_col,
                                 (cu+sx*9, cv+sy*9), (cu+sx*(9-arm), cv+sy*9), 1)
                pygame.draw.line(cam, cand_col,
                                 (cu+sx*9, cv+sy*9), (cu+sx*9, cv+sy*(9-arm)), 1)

        # ── Active track ring + brackets ─────────────────────────────
        if assoc is not None and st in LOCKED_STATES:
            apx, apy  = int(assoc.u), int(assoc.v)
            degraded  = (st == "DEGRADED_LOCK")
            ring_col  = T.C.AMBER_DIM if degraded else T.C.GREEN
            # Pulsing outer ring
            p = T.pulse(1.8)
            outer_r = 22 + int(4 * p)
            pygame.draw.circle(cam, ring_col, (apx, apy), outer_r, 1)
            pygame.draw.circle(cam, ring_col, (apx, apy), 16, 1)
            pygame.draw.circle(cam, ring_col, (apx, apy), 3)
            # Cardinal extension lines
            for ddx, ddy in ((-1,0),(1,0),(0,-1),(0,1)):
                pygame.draw.line(cam, ring_col,
                                 (apx+ddx*outer_r, apy+ddy*outer_r),
                                 (apx+ddx*(outer_r+8), apy+ddy*(outer_r+8)), 1)
            _bracket_cam(cam, (apx, apy), ring_col, outer_r + 10, 2)
            lbl = "BCN·DEG" if degraded else "BCN·LOCK"
            T.text(cam, (apx + 34, apy - 18), lbl,
                   9, ring_col, bold=True, anchor="tl")
            T.text(cam, (apx + 34, apy - 6),
                   f"{res['pointing_err_deg']*1000:.1f}m°",
                   8, ring_col, anchor="tl")
        elif assoc is not None:
            _bracket_cam(cam, (int(assoc.u), int(assoc.v)), T.C.GREEN, 14, 2)
        elif res.get("est_az") is not None and st not in LOCKED_STATES:
            p = self._est_pixel(res["est_az"], res["est_el"])
            if p is not None:
                pygame.draw.circle(cam, T.C.CYAN, p, 8, 1)

        # ── Synthetic ephemeris prior marker ─────────────────────────
        paz = getattr(self, "eph_pred_az", None)
        if paz is not None:
            pp = self._est_pixel(paz, self.eph_pred_el)
            if pp is not None:
                px, py = pp
                for k in range(0, 360, 30):
                    a1, a2 = math.radians(k), math.radians(k + 12)
                    pygame.draw.line(cam, T.C.AMBER,
                                     (px + 10*math.cos(a1), py + 10*math.sin(a1)),
                                     (px + 10*math.cos(a2), py + 10*math.sin(a2)), 1)
                if _clear((px, py), 36, bp):
                    T.text(cam, (px, py - 22), "SYNTH-EPH PRED",
                           7, T.C.AMBER, anchor="cc")

        # ── Search / reacquisition overlay ───────────────────────────
        if st in ("SEARCHING", "REACQUIRING"):
            search_col = T.C.AMBER if st == "SEARCHING" else T.C.PURPLE
            tr = self.sim.tracker
            sa = getattr(tr, "search_angle", 0.0)
            se = getattr(tr, "search_radius", 0.05)
            base_az = getattr(tr, "est_az", None) or res["truth_az"]
            base_el = getattr(tr, "est_el", None) or res["truth_el"]
            for k in range(16):
                a  = sa + k * 0.55
                rr = se * (1 + k / 16.0)
                p  = self._est_pixel(base_az + rr * np.cos(a),
                                     base_el + rr * np.sin(a))
                if p is not None:
                    pygame.draw.circle(cam, search_col, p, 2)
            cp = self._est_pixel(base_az, base_el)
            if cp is not None:
                focal, cu, cv, vw, vh = self._cam_space()
                ring_r = int(se * focal)
                if 4 < ring_r < 400:
                    pygame.draw.circle(cam, tuple(c // 3 for c in search_col),
                                       cp, ring_r, 1)

        # ── Occluded banner ──────────────────────────────────────────
        if not res["beacon_visible"]:
            occ_r = pygame.Rect(r.centerx - 90, r.bottom - 56, 180, 16)
            pygame.draw.rect(cam, (48, 8, 8), occ_r)
            pygame.draw.rect(cam, T.C.RED, occ_r, 1)
            T.text(cam, (r.centerx, occ_r.centery),
                   "BEACON OCCLUDED", 9, T.C.RED, anchor="cc")

        # ── Phase-2 trust bars (top-left) ────────────────────────────
        tr = self.sim.tracker
        tm = getattr(tr, "trust", None)
        dy = 8
        if tm is not None:
            W.hbar(cam, (8, dy, 90, 4), tm.vision_trust, T.C.CYAN)
            T.text(cam, (102, dy - 1), f"VIS {tm.vision_trust:.2f}", 7, (50, 130, 160))
            dy += 8
            W.hbar(cam, (8, dy, 90, 4), tm.model_trust, T.C.PURPLE)
            T.text(cam, (102, dy - 1), f"MDL {tm.model_trust:.2f}", 7, (90, 60, 150))
            sigma = getattr(getattr(tr, "unc", None), "display_sigma_px", None)
            if sigma is not None:
                dy += 8
                T.text(cam, (8, dy), f"σ {sigma:.1f}px", 7, (46, 68, 90))

        # ── State chip + confidence bar (bottom-left) ─────────────────
        chip_h = 22
        chip_r = pygame.Rect(6, r.h - chip_h - 36, 128, chip_h)
        fill   = T.C.STATE_FILL.get(st, (0, 20, 32))
        pygame.draw.rect(cam, fill, chip_r)
        pygame.draw.rect(cam, tuple(c // 2 for c in col), chip_r, 1)
        pygame.draw.rect(cam, col, (chip_r.x, chip_r.y, 3, chip_r.h))
        T.text(cam, (chip_r.x + 10, chip_r.centery), st, 10, col,
               bold=True, anchor="lc")
        conf_val = res.get("confidence", 0.0)
        W.hbar(cam, (chip_r.x, chip_r.bottom + 2, chip_r.w, 3), conf_val, col)
        T.text(cam, (chip_r.right + 4, chip_r.centery),
               f"{conf_val:.2f}", 8, col, anchor="lc")

        # ── Elapsed time (top-right) ─────────────────────────────────
        T.text(cam, (r.right - 6, 6), f"t={res['t']:6.1f}s",
               7, (38, 58, 82), anchor="tr")

        # ── Ground truth (eval-only, hidden) ─────────────────────────
        if self.show_gt:
            gp = self._est_pixel(res["truth_az"], res["truth_el"])
            if gp is not None:
                gx, gy = gp
                pygame.draw.circle(cam, T.C.PURPLE, (gx, gy), 6, 1)
                pygame.draw.line(cam, T.C.PURPLE, (gx-10, gy), (gx+10, gy), 1)
                pygame.draw.line(cam, T.C.PURPLE, (gx, gy-10), (gx, gy+10), 1)
            bw = 240
            brect = pygame.Rect(r.centerx - bw//2, 2, bw, 14)
            pygame.draw.rect(cam, (40, 10, 60), brect)
            pygame.draw.rect(cam, T.C.PURPLE, brect, 1)
            T.text(cam, (r.centerx, 9), "GROUND TRUTH  ·  EVAL ONLY",
                   7, T.C.PURPLE, anchor="cc")

    def _cam_space(self):
        if self.video_mode:
            s = self.sim
            return (s.focal_px, s.cu, s.cv, s.video_w, s.video_h)
        return (config.FOCAL_PX, config.PRINCIPAL_U, config.PRINCIPAL_V,
                CAM_W, CAM_H)

    def _est_pixel(self, az, el):
        if az is None or el is None:
            return None
        focal, cu, cv, vw, vh = self._cam_space()
        d     = azel_unit(az, el)
        basis = self.sim.gimbal.basis()
        p = project_point_into_camera(d, (0, 0, 0), basis, focal, cu, cv)
        if p is None:
            return None
        u, v = p
        if 0 <= u < vw and 0 <= v < vh:
            return (int(u), int(v))
        return None

    # ================================================================ BOTTOM STRIP
    def _draw_bottom(self, surf):
        by = BTM_Y
        bh = BTM_H - 16   # leave room for footer text
        # Bottom strip covers camera-side only (right panel extends to APP_H)
        bw = PNL_X0
        pygame.draw.rect(surf, T.C.PANEL, (0, by, bw, bh))
        pygame.draw.line(surf, T.C.BORDER_B, (0, by),     (bw, by),     1)
        pygame.draw.line(surf, T.C.BORDER,   (0, by + 1), (bw, by + 1), 1)

        # PAT pipeline stepper (camera-side width)
        self._draw_pat_stepper(surf, pygame.Rect(4, by + 4, bw - 8, 32))

        # Error graph left portion
        graph_rect = pygame.Rect(44, by + 42, 660, bh - 48)
        self._draw_error_graph(surf, graph_rect)

        # Camera / actuator panel right of graph
        panel_rect = pygame.Rect(718, by + 42, bw - 726, bh - 48)
        self._draw_camera_panel(surf, panel_rect)

    # ---------------------------------------------------------------- PAT pipeline
    def _draw_pat_stepper(self, surf, box):
        res  = self.sim.last_result
        st   = res["state"]
        steps = ["PREDICT", "POINT", "SEARCH", "ACQUIRE", "LOCK"]
        idx  = {"SEARCHING": 2, "REACQUIRING": 2, "COASTING": 3,
                "TENTATIVE": 3, "LOCKED": 4, "DEGRADED_LOCK": 4}.get(st, 0)
        act_col = T.C.STATE.get(st, T.C.CYAN)

        pygame.draw.rect(surf, T.C.PANEL_2, box)
        pygame.draw.rect(surf, T.C.BORDER,  box, 1)

        n = len(steps)
        seg_w = box.w // n
        x = box.x
        for i, step in enumerate(steps):
            seg    = pygame.Rect(x, box.y, seg_w - 1, box.h)
            done   = i < idx
            active = i == idx

            if active:
                pygame.draw.rect(surf, tuple(c // 8 for c in act_col), seg)
                # animated bottom bar
                pygame.draw.rect(surf, act_col,
                                 (seg.x, seg.bottom - 3, seg.w, 3))
                text_col, fs = act_col, 10
            elif done:
                pygame.draw.rect(surf, T.C.PANEL_3, seg)
                pygame.draw.rect(surf, T.C.GREEN_DIM,
                                 (seg.x, seg.bottom - 2, seg.w, 2))
                text_col, fs = T.C.TEXT_DIM, 9
            else:
                text_col, fs = T.C.TEXT_FAINT, 9

            T.text(surf, (seg.centerx, seg.centery - 1), step, fs,
                   text_col, bold=active, anchor="cc")
            if i < n - 1:
                mx = x + seg_w - 1
                pygame.draw.line(surf, T.C.BORDER,
                                 (mx, box.y + 4), (mx, box.bottom - 4), 1)
            x += seg_w

        # Annotation badge for special states
        ann = {"COASTING": ("COAST", T.C.CYAN), "REACQUIRING": ("RE-ACQ", T.C.PURPLE),
               "LOST": ("LOST", T.C.RED)}.get(st)
        if ann:
            avail = APP_W - (box.right + 10)
            bw    = max(64, min(130, avail))
            r     = pygame.Rect(box.right + 6, box.y, bw, box.h)
            pygame.draw.rect(surf, tuple(c // 7 for c in ann[1]), r)
            pygame.draw.rect(surf, ann[1], r, 1)
            pygame.draw.rect(surf, ann[1], (r.x, r.y, 2, r.h))
            T.text(surf, (r.centerx + 2, r.centery), ann[0],
                   9, ann[1], bold=True, anchor="cc")

    # ---------------------------------------------------------------- error graph
    def _draw_error_graph(self, surf, box):
        T.text(surf, (box.x, box.y), "ANGULAR POINTING ERROR", 11, T.C.TEXT_DIM, bold=True)
        T.text(surf, (box.x + 194, box.y + 1), "deg", 9, T.C.TEXT_FAINT)
        T.text(surf, (box.right, box.y), "target < 0.0625°",
               7, T.C.TEXT_FAINT, anchor="tr")

        plot = pygame.Rect(box.x + 32, box.y + 16, box.w - 32, box.h - 18)
        pygame.draw.rect(surf, T.C.BG, plot)
        pygame.draw.rect(surf, T.C.BORDER, plot, 1)

        # Target acquisition band
        _bound = plot.bottom - int(plot.h * (config.FINE_ACQUISITION_REGION_DEG / 0.5))
        pygame.draw.rect(surf, (4, 22, 12),
                         (plot.x, _bound, plot.w, plot.bottom - _bound))
        pygame.draw.line(surf, T.C.GREEN_DIM, (plot.x, _bound), (plot.right, _bound), 1)

        # Grid lines + Y labels
        T.text(surf, (plot.x - 4, plot.bottom - 5), "0",   7, T.C.TEXT_FAINT, anchor="tr")
        T.text(surf, (plot.x - 4, plot.y + 1),      "0.5", 7, T.C.TEXT_FAINT, anchor="tr")
        for deg in (0.1, 0.2, 0.3, 0.4):
            yy = plot.bottom - int(plot.h * (deg / 0.5))
            pygame.draw.line(surf, T.C.GRID, (plot.x, yy), (plot.right, yy), 1)
            T.text(surf, (plot.x - 4, yy - 4), f"{deg:.1f}",
                   7, T.C.TEXT_FAINT, anchor="tr")

        # Error series
        series = [max(0.0, min(0.5, e)) for e in self.error_spark]
        n = len(series)
        if n > 1:
            pts = []
            for i, v in enumerate(series):
                xx = int(plot.x + plot.w * i / (n - 1))
                yy = int(plot.bottom - plot.h * (v / 0.5))
                pts.append((xx, yy))
            # Filled area
            fill_pts = ([pts[0]]
                        + pts
                        + [(pts[-1][0], plot.bottom), (pts[0][0], plot.bottom)])
            area = pygame.Surface((plot.w, plot.h), pygame.SRCALPHA)
            local = [(p[0] - plot.x, p[1] - plot.y) for p in fill_pts]
            pygame.draw.polygon(area, (0, 255, 100, 25), local)
            surf.blit(area, (plot.x, plot.y))
            # Line
            prev = None
            for p in pts:
                if prev:
                    pygame.draw.line(surf, T.C.GREEN, prev, p, 2)
                prev = p

        T.text(surf, (plot.right - 4, _bound - 2), "ACQ TARGET",
               7, T.C.GREEN_DIM, anchor="br")

        # NOW marker
        if series:
            cur_v  = series[-1]
            now_x  = plot.right - 1
            now_y  = int(plot.bottom - plot.h * (cur_v / 0.5))
            cur_col = (T.C.GREEN if cur_v < config.FINE_ACQUISITION_REGION_DEG
                       else (T.C.AMBER if cur_v < 0.30 else T.C.RED))
            pygame.draw.line(surf, tuple(c // 4 for c in cur_col),
                             (now_x, plot.y), (now_x, plot.bottom), 1)
            pygame.draw.circle(surf, cur_col, (now_x, now_y), 4)
            T.text(surf, (now_x - 6, now_y - 12),
                   f"{cur_v*1000:.0f}", 9, cur_col, bold=True, anchor="tr")

        if not self.sim.last_result["beacon_visible"]:
            pygame.draw.rect(surf, (50, 14, 14),
                             (plot.right - 4, plot.y, 4, plot.h))

        self._draw_state_timeline(surf, plot)

    def _draw_state_timeline(self, surf, plot):
        tmax = max(0.001, self.sim.last_result.get("t", 0.0))
        ev   = list(getattr(self.sim, "event_log", ()))
        y    = plot.bottom - 8
        band = pygame.Rect(plot.x, y, plot.w, 7)
        pygame.draw.rect(surf, T.C.BG, band)
        runs = []
        if ev:
            runs.append((0.0, ev[0][0], ev[0][1]))
            for i, e in enumerate(ev):
                t1 = ev[i+1][0] if i+1 < len(ev) else tmax
                if t1 > e[0]:
                    runs.append((e[0], t1, e[2]))
        else:
            runs.append((0.0, tmax,
                         getattr(self.sim.tracker, "state", "SEARCHING")))
        for t0, t1, s in runs:
            x0 = plot.x + plot.w * (t0 / tmax)
            x1 = plot.x + plot.w * (min(t1, tmax) / tmax)
            if x1 <= x0:
                continue
            scol = T.C.STATE.get(s, T.C.STATE["SEARCHING"])
            if s == "COASTING":
                scol = T.C.STATE["REACQUIRING"]
            if s == "SEARCHING":
                scol = T.C.AMBER_DIM
            pygame.draw.rect(surf, scol, (int(x0), y, int(x1-x0), 7))
        pygame.draw.rect(surf, T.C.BORDER, band, 1)
        T.text(surf, (plot.x - 4, y + 3), "STATE", 7, T.C.TEXT_FAINT, anchor="tr")

    # ---------------------------------------------------------------- camera panel
    def _draw_camera_panel(self, surf, box):
        res = self.sim.last_result
        T.text(surf, (box.x, box.y), "GIMBAL / ACTUATOR", 11, T.C.TEXT_DIM, bold=True)
        pygame.draw.line(surf, T.C.BORDER, (box.x, box.y + 13), (box.x + 220, box.y + 13), 1)

        y, x = box.y + 20, box.x + 10
        kpis = [
            ("AZIMUTH",   f"{self.sim.gimbal.pan:+.2f}°",  T.C.CYAN),
            ("ELEVATION", f"{self.sim.gimbal.tilt:+.2f}°", T.C.CYAN),
        ]
        for lab, val, vcol in kpis:
            T.text(surf, (x, y),      lab, 9,  T.C.TEXT_DIM, bold=True)
            T.text(surf, (x, y + 11), val, 15, vcol, bold=True)
            x += 140

        x = box.x + 10
        kpis2 = [
            ("H-FOV",  f"{config.HFOV_DEG:.1f}°", T.C.TEXT_DIM),
            ("MODE",   "COARSE PAT",                T.C.TEXT_DIM),
        ]
        for lab, val, vcol in kpis2:
            T.text(surf, (x, y + 30),     lab, 9,  T.C.TEXT_DIM, bold=True)
            T.text(surf, (x, y + 41),     val, 12, vcol, bold=False)
            x += 180

        sp  = res.get("gimbal_sat_pan", 0.0)
        st_ = res.get("gimbal_sat_tilt", 0.0)
        sat = max(sp, st_)
        s_col = T.C.GREEN if sat <= 0.05 else (T.C.AMBER if sat < 0.5 else T.C.RED)
        T.text(surf, (box.x + 10, y + 64), "GIMBAL SATURATION", 9, T.C.TEXT_DIM, bold=True)
        T.text(surf, (box.x + 150, y + 64),
               f"P {sp*100:3.0f}%  T {st_*100:3.0f}%", 11, s_col, bold=(sat > 0.05))

        self._draw_beam_strip(surf, pygame.Rect(box.right - 140, box.y + 10, 130, box.h - 14))

    def _draw_beam_strip(self, surf, box):
        cx = box.centerx
        ay = box.bottom - 20
        by = box.y + 30
        err = self.sim.last_result["pointing_err_deg"]
        col = (T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG
               else (T.C.AMBER if err < 0.30 else T.C.RED))
        pygame.draw.polygon(surf, (20, 56, 80),
                            [(cx-7, ay), (box.x+4, by), (box.right-4, by)])
        pygame.draw.line(surf, col, (cx, ay), (cx, by), 2)
        pygame.draw.rect(surf, T.C.CYAN, (cx-11, ay-9, 22, 11), 1)
        T.text(surf, (cx, ay + 12), "SAT-A", 9, T.C.CYAN, bold=True, anchor="cc")
        pygame.draw.circle(surf, T.C.RED, (cx, by), 7)
        pygame.draw.circle(surf, T.C.RED, (cx, by), 12, 1)
        T.text(surf, (cx, by - 18), "SAT-B", 9, T.C.RED, bold=True, anchor="cc")
        mid_y = (ay + by) // 2
        T.text(surf, (box.right - 4, mid_y - 10), "POINT ERR", 8, T.C.TEXT_DIM,
               bold=True, anchor="tr")
        T.text(surf, (box.right - 4, mid_y + 2), f"{err*1000:.1f} mdeg",
               12, col, bold=True, anchor="tr")

    # ================================================================ RIGHT PANEL
    def _draw_panel(self, surf):
        # Panel background — extends full height to APP_H (controls sit below camera strip)
        pnl_full_h = APP_H - HDR_H
        pygame.draw.rect(surf, T.C.BG,    (PNL_X0, HDR_H, PNL_W, pnl_full_h))
        pygame.draw.line(surf, T.C.BORDER_B, (PNL_X0, HDR_H), (PNL_X0, APP_H), 2)
        pygame.draw.line(surf, T.C.BORDER,   (PNL_X0 + 2, HDR_H), (PNL_X0 + 2, APP_H), 1)

        # Subtle background grid for right panel
        for gx in range(PNL_X0 + 60, PNL_X1, 60):
            pygame.draw.line(surf, (8, 14, 28), (gx, HDR_H), (gx, APP_H), 1)

        self._panel_state(surf)
        self._panel_mission(surf)
        self._panel_performance(surf)
        self._panel_geometry(surf)
        self._panel_disturbances(surf)
        self._panel_controls(surf)

    # ── State ─────────────────────────────────────────────────────────────────
    def _panel_state(self, surf):
        x, y, w, h = PNL_INN, 66, PNL_IW, 108
        res  = self.sim.last_result
        st   = res.get("state", "SEARCHING")
        col  = T.C.STATE.get(st, T.C.CYAN)
        fill = T.C.STATE_FILL.get(st, (0, 30, 50))
        r    = pygame.Rect(x, y, w, h)
        T.angled_panel(surf, r, fill=fill, border=col, cut=14, accent=None)
        # Left accent stripe
        pygame.draw.rect(surf, col, (x + 1, y + 4, 4, h - 8), border_radius=2)

        # State name in large text
        T.text(surf, (x + w // 2, y + 13), "TRACK STATE", 10, col,
               bold=True, anchor="cc")
        # Large state text — scale down if long
        fs = 28 if len(st) <= 7 else (22 if len(st) <= 12 else 16)
        T.text(surf, (x + w // 2, y + 32), st, fs, col, bold=True, anchor="cc")

        # Confidence arc gauge
        conf = res.get("confidence", 0.0)
        arc_cx = x + w - 44
        arc_cy = y + 60
        T.arc_gauge(surf, (arc_cx, arc_cy), 28, conf, col, T.C.PANEL_3, width=5)
        T.text(surf, (arc_cx, arc_cy), f"{conf:.2f}", 11, col, bold=True, anchor="cc")
        # Status / timing row
        stat_y = y + h - 20
        pygame.draw.line(surf, col, (x + 8, stat_y - 4), (x + w - 8, stat_y - 4), 1)
        run_col = T.C.AMBER if self.paused else col
        pygame.draw.circle(surf, run_col, (x + 14, stat_y + 4), 3)
        T.text(surf, (x + 20, stat_y),
               "PAUSED" if self.paused else "RUNNING", 10, run_col, bold=True)
        T.text(surf, (x + w - 8, stat_y),
             f"t = {res.get('t', 0.0):.1f}s", 10, T.C.TEXT_DIM, anchor="tr")

    # ── Mission ────────────────────────────────────────────────────────────────
    def _panel_mission(self, surf):
        x, y, w, h = PNL_INN, 178, PNL_IW, 74
        r = pygame.Rect(x, y, w, h)
        T.panel(surf, r)
        T.section_hdr(surf, x + 8, y + 6, "MISSION", panel_w=w - 16)
        res = self.sim.last_result
        st  = res["state"]
        lock = st in LOCKED_STATES

        if self.video_mode:
            rows = [("Source", "INPUT VIDEO (PTZ bypassed)"),
                    ("Mode",   "Benchmark-2 · video feed"),
                    ("Status", "TRACKING" if lock else st[:8])]
        else:
            rows = [
                ("Scenario", self.preset),
                ("Link",     self._platform_label() + "  ·  " + (self.atmosphere or "CLEAR")),
                ("Status",   "TRACKING" if lock else st[:10]),
            ]
        yy  = y + 26
        col = T.C.GREEN if lock else T.C.STATE.get(st, T.C.CYAN)
        for lab, val in rows:
            T.text(surf, (x + 12, yy), lab, 10, T.C.TEXT_DIM, bold=True)
            is_status = (lab == "Status")
            value_size = 11 if is_status else 10
            value_color = col if is_status else T.C.TEXT
            T.text(surf, (x + 100, yy), val, value_size,
                   value_color, bold=is_status)
            yy += 16

    # ── Performance ────────────────────────────────────────────────────────────
    def _panel_performance(self, surf):
        x, y, w, h = PNL_INN, 256, PNL_IW, 136
        res = self.sim.last_result
        st  = self.perf.live_stats()
        err = res["pointing_err_deg"]
        ec  = (T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG
               else (T.C.AMBER if err < 0.30 else T.C.RED))
        r   = pygame.Rect(x, y, w, h)
        T.angled_panel(surf, r, T.C.PANEL, T.C.BORDER, cut=12, accent=None)
        pygame.draw.rect(surf, ec, (x + 1, y + 4, 4, h - 8), border_radius=2)
        T.section_hdr(surf, x + 10, y + 6, "PAT PERFORMANCE", color=ec, panel_w=w - 16)

        # Hero pointing error box
        err_r = pygame.Rect(x + 8, y + 26, w - 16, 44)
        pygame.draw.rect(surf, tuple(c // 8 for c in ec), err_r, border_radius=2)
        pygame.draw.rect(surf, tuple(c // 3 for c in ec), err_r, 1, border_radius=2)
        T.text(surf, (x + 16, y + 28), "POINTING ERROR", 9, ec, bold=True)
        T.text(surf, (x + 16, y + 38), f"{err*1000:6.1f}", 26, ec, bold=True)
        T.text(surf, (x + 16 + 120, y + 52), "m°", 9, ec)

        # KPI trio
        acq  = st["acquisition_time_s"]
        acq_s = f"{acq:.2f}s" if acq else "--"
        reacq = st["last_reacq_s"]
        reacq_s = f"{reacq:.2f}s" if reacq else f"{st['reacquisition_count']}ev"
        ret_pct = st["retention_total_pct"]
        ret_col = T.C.GREEN if ret_pct >= 95 else (T.C.AMBER if ret_pct >= 80 else T.C.RED)
        cols_data = [("ACQ", acq_s, T.C.CYAN), ("RET", f"{ret_pct:.1f}%", ret_col),
                     ("REACQ", reacq_s, T.C.PURPLE)]
        xx = x + 12
        col_w = (w - 24) // 3
        for lab, val, vc in cols_data:
            T.text(surf, (xx, y + 78),  lab, 9,  T.C.TEXT_DIM, bold=True)
            T.text(surf, (xx, y + 90),  val, 14, vc, bold=True)
            xx += col_w

        if self.show_diag:
            diag = (f"mean {st['mean_err_deg']*1000:.0f}  rms {st['rms_err_deg']*1000:.0f}"
                    f"  max {st['max_err_deg']*1000:.0f}  fps {st['fps']:.0f}")
            T.text(surf, (x + 12, y + 118), diag, 8, T.C.TEXT_FAINT)
        else:
            fps = st.get("fps", self.clock.get_fps())
            fps_col = T.C.GREEN if fps >= 25 else T.C.AMBER
            T.text(surf, (x + w - 8, y + 118),
                   f"{fps:.0f} fps", 9, fps_col, bold=True, anchor="tr")

    # ── Orbit / Video geometry ─────────────────────────────────────────────────
    def _panel_geometry(self, surf):
        x, y, w, h = PNL_INN, 396, PNL_IW, 118
        g = pygame.Rect(x, y, w, h)
        if self.video_mode:
            T.panel(surf, g)
            T.section_hdr(surf, x + 8, y + 6, "VIDEO BYPASS  (Benchmark-2)",
                          color=T.C.TEXT_DIM, panel_w=w - 16)
            res  = self.sim.last_result
            stat = self.perf.live_stats()
            rows = [
                ("Input", os.path.basename(self.video_path)[:28]),
                ("Acq",   f"{stat['acquisition_time_s']:.2f}s"
                           if stat["acquisition_time_s"] is not None else "--"),
                ("Retention", f"{stat['retention_total_pct']:.1f}%"),
                ("Centroid",  f"{res.get('centroid_err_px', 0):.1f} px"
                               if res is not None else "--"),
            ]
            yy = y + 26
            for lab, val in rows:
                T.text(surf, (x + 12, yy),  lab, 9, T.C.TEXT_FAINT)
                T.text(surf, (x + 96, yy),  val, 10, T.C.TEXT)
                yy += 22
            return
        view3d.render(surf, g, self.sim, self.sim.t)
        T.text(surf, (g.right - 6, g.y + 2), "B approaching A FOV",
               8, T.C.TEXT_FAINT, anchor="tr")

    # ── Comparison ──────────────────────────────────────────────────────────────
    def _panel_comparison_small(self, surf, x, y, w):
        if self.compare is None:
            return
        res = self.compare.get("results", {})
        row = res.get(self.preset)
        if not row:
            return
        ada  = row.get("adaptive", {})
        base = row.get("baseline", {})
        T.text(surf, (x, y), "ADAPTIVE vs BASELINE", 8, T.C.TEXT_FAINT)
        cx = [x + 150, x + 230, x + 300]
        for xx, lbl in zip(cx, ["ACQ", "RET%", "FAL"]):
            T.text(surf, (xx, y), lbl, 7, T.C.TEXT_FAINT)
        y2 = y + 12
        T.text(surf, (x, y2), "ADAPTIVE", 8, T.C.GREEN, bold=True)
        T.text(surf, (cx[0], y2), f"{ada.get('acq', 0):.2f}s", 8, T.C.TEXT)
        T.text(surf, (cx[1], y2), f"{ada.get('ret_pct', 0):.0f}", 8, T.C.TEXT)
        T.text(surf, (cx[2], y2), f"{ada.get('false_locks', 0)}", 8, T.C.GREEN)
        y3 = y + 24
        T.text(surf, (x, y3), "BASELINE", 8, T.C.TEXT_DIM)
        T.text(surf, (cx[0], y3), f"{base.get('acq', 0):.2f}s", 8, T.C.TEXT_DIM)
        T.text(surf, (cx[1], y3), f"{base.get('ret_pct', 0):.0f}", 8, T.C.TEXT_DIM)
        T.text(surf, (cx[2], y3), f"{base.get('false_locks', 0)}", 8, T.C.RED)

    # ── Disturbances ──────────────────────────────────────────────────────────
    def _panel_disturbances(self, surf):
        x, y, w, h = PNL_INN, 518, PNL_IW, 214
        r = pygame.Rect(x, y, w, h)
        T.panel(surf, r)
        kind = disturbance_kind_label(self.platform_mode)
        T.section_hdr(surf, x + 8, y + 6, f"DISTURBANCES  ·  {kind}",
                      color=T.C.AMBER, panel_w=w - 16)
        note = "N/A (vacuum)" if not self._atmosphere_allowed() else "active"
        T.text(surf, (x + w - 10, y + 6), note, 7, T.C.TEXT_FAINT, anchor="tr")
        for key, s in self.sliders.items():
            s.draw(surf)
            unit = config.DISTURBANCE_UNITS.get(key, (None, ""))[1]
            if unit:
                T.text(surf, (s.rect.right, s.rect.y - 10), unit,
                       7, T.C.TEXT_FAINT, anchor="tr")

    # ── Controls ──────────────────────────────────────────────────────────────
    def _panel_controls(self, surf):
        x, y, w, h = PNL_INN, 736, PNL_IW, 68
        r = pygame.Rect(x, y, w, h)
        T.panel(surf, r)
        T.section_hdr(surf, x + 8, y + 4, "CONTROLS", panel_w=w - 16)
        for b in self.buttons.values():
            b.draw(surf)

    def _load_compare(self):
        try:
            p = os.path.join(config.LOG_DIR, "compare_summary.json")
            if not os.path.exists(p):
                return None
            import json
            with open(p) as fh:
                return json.load(fh)
        except Exception:
            return None


# ── helpers ───────────────────────────────────────────────────────────────────
def _bracket_cam(surf, center, color, r, th):
    """Corner brackets on the camera surface."""
    x, y = center
    L    = r
    for dx, dy in ((1,1), (-1,1), (1,-1), (-1,-1)):
        pygame.draw.line(surf, color,
                         (x+dx*r, y+dy*L), (x+dx*r, y+dy*(r-L//2)), th)
        pygame.draw.line(surf, color,
                         (x+dx*r, y+dy*L), (x+dx*(r-L//2), y+dy*L), th)


# ── headless self-test ────────────────────────────────────────────────────────
def headless_selftest(frames, preset, platform=None, atmosphere=None,
                      motion_type=None, target_shape=None, target_size=None,
                      num_targets=None, target_initial=None):
    print(f"headless self-test: preset={preset} frames={frames}")
    sim  = Simulator(preset_name=preset, seed=1,
                     platform_mode=platform, atmosphere=atmosphere,
                     motion_type=motion_type, target_shape=target_shape,
                     target_size=target_size, num_targets=num_targets,
                     target_initial=target_initial)
    perf = PerformanceTracker()
    t0   = time.time()
    for _ in range(frames):
        sim.step()
        perf.record_frame(sim)
    wall = time.time() - t0
    st   = perf.live_stats()
    print(f"state={sim.state} acq={st['acquisition_time_s']} "
          f"retention={st['retention_total_pct']:.1f}% "
          f"mean_err={st['mean_err_deg']} rms={st['rms_err_deg']} "
          f"fps={frames/wall:.1f} false_lock={st['false_lock_events']}")


# ── entry point ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset",     default="EASY")
    ap.add_argument("--frames",     type=int, default=0)
    ap.add_argument("--fullscreen", action="store_true", default=True,
                    help="start in fullscreen (default)")
    ap.add_argument("--windowed", action="store_false", dest="fullscreen",
                    help="start in a 1600x900 window")
    ap.add_argument("--platform",   default=None,
                    choices=["SATELLITE_SATELLITE", "UAV_SATELLITE", "UAV_UAV"])
    ap.add_argument("--atmosphere", default=None,
                    choices=["CLEAR", "HAZE", "FOG", "RAIN", "LOW_LIGHT"])
    ap.add_argument("--motion",     default=None,
                    choices=["straight_line", "circular", "figure_eight",
                             "random", "spiral", "sinusoidal"])
    ap.add_argument("--shape",      default=None,
                    choices=["SQUARE", "CIRCLE", "SPOT"])
    ap.add_argument("--size",       type=int, default=None)
    ap.add_argument("--targets",    type=int, default=None)
    ap.add_argument("--initial",    default=None, choices=["RANDOM", "CENTER"])
    ap.add_argument("--video",      default=None)
    ap.add_argument("--video-seed", type=int, default=None)
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
