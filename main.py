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


class App:
    def __init__(self, preset="EASY", seed=None, fullscreen=False):
        pygame.init()
        flags = pygame.FULLSCREEN | pygame.SCALED if fullscreen else 0
        self.screen = pygame.display.set_mode((APP_W, APP_H),
                                              flags=(flags if fullscreen else 0))
        pygame.display.set_caption("FSOC-PAT Coarse-Pointing Tracker  ·  SIH 2026 PS 26169")
        self.clock = pygame.time.Clock()

        self.preset = preset
        self.sim = Simulator(preset_name=preset, seed=seed)
        self.perf = PerformanceTracker()
        self.paused = False
        self.show_fov_grid = True
        self.eph_pred_az = None
        self.eph_pred_el = None

        self.error_spark = deque(maxlen=900)
        self.sliders = {
            "turbulence": W.Slider((1332, 424, 240, 26), "TURBULENCE",
                                   self.sim.preset.get("turbulence", 0), T.C.PURPLE),
            "vibration": W.Slider((1332, 452, 240, 26), "VIBRATION",
                                  self.sim.preset.get("vibration", 0), T.C.AMBER),
            "sensor_noise": W.Slider((1332, 480, 240, 26), "SENSOR NOISE",
                                     self.sim.preset.get("sensor_noise", 0), T.C.RED),
            "jerk_prob": W.Slider((1332, 508, 240, 26), "JERK PROB",
                                  self.sim.preset.get("jerk_prob", 0), T.C.CYAN),
            "beacon_fade": W.Slider((1332, 536, 240, 26), "BEACON FADE",
                                    self.sim.preset.get("beacon_fade", 0), T.C.AMBER_DIM),
        }
        self.chips = {}
        xs = 10
        for name in config.PRESET_ORDER:
            self.chips[name] = W.Chip((xs, 40, 57, 24), name[:4], T.C.CYAN)
            xs += 62
        self.buttons = {
            "PAUSE": W.Button((10, 680, 96, 30), "PAUSE", T.C.AMBER),
            "RESET": W.Button((114, 680, 96, 30), "RESET", T.C.CYAN),
            "SHOT": W.Button((218, 680, 96, 30), "SHOT", T.C.GREEN),
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

            if not self.paused:
                res = self.sim.step()
                self.perf.record_frame(self.sim)
                if res["state"] == "LOCKED":
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
                return
        for name, c in self.chips.items():
            if button == 1 and c.hit(pos):
                self.preset = name
                self._reset(name)
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
        self.sim = Simulator(preset_name=name or self.preset, seed=None)
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

    def _final_report(self):
        st = self.perf.live_stats()
        p = os.path.join(config.LOG_DIR, f"run_{int(time.time())}.csv")
        extra = {"preset": self.preset}
        self.perf.write_log(p, extra_info=extra)
        print(f"performance log -> {p}")


    # ---------------------------------------------------------------- draw
    def _draw(self):
        s = self.screen
        s.fill(T.C.BG)
        self._draw_camera(s)
        self._draw_bottom(s)
        self._draw_panel(s)

    def _draw_camera(self, surf):
        frame = self.sim.last_result.get("frame")
        cam = self._frame_to_surf(frame)
        self._draw_hud(cam)
        scaled = pygame.transform.smoothscale(cam, (int(CAM_W * CAM_SCALE),
                                                    int(CAM_H * CAM_SCALE)))
        surf.blit(scaled, (0, 0))

    def _frame_to_surf(self, frame):
        if frame is None:
            s = pygame.Surface((CAM_W, CAM_H))
            s.fill((0, 0, 0))
            return s
        img = np.ascontiguousarray(frame[:, :, ::-1])
        return pygame.surfarray.make_surface(img)

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

        if self.show_fov_grid:
            pygame.draw.line(cam, (40, 60, 80), (cx, r.top), (cx, r.bottom), 1)
            pygame.draw.line(cam, (40, 60, 80), (r.left, cy), (r.right, cy), 1)

        # ---- optical boresight reticle (Sat A beam LOS) ----
        bp = self._est_pixel(self.sim.gimbal.pan, self.sim.gimbal.tilt)
        if bp is not None:
            bx, by = bp
            pygame.draw.circle(cam, (120, 160, 200), (bx, by), 10, 1)
            pygame.draw.line(cam, (120, 160, 200), (bx - 18, by), (bx - 6, by), 1)
            pygame.draw.line(cam, (120, 160, 200), (bx + 6, by), (bx + 18, by), 1)
            pygame.draw.line(cam, (120, 160, 200), (bx, by - 18), (bx, by - 6), 1)
            pygame.draw.line(cam, (120, 160, 200), (bx, by + 6), (bx, by + 18), 1)
            T.text(cam, (bx, by - 24), "OPTICAL BORESIGHT", 8, (120, 160, 200), anchor="cc")

        # ---- tracked / candidate overlays ----
        for i, c in enumerate(res.get("cand_list", [])):
            # distractors / un-locked candidates stay in dim cyan boxes
            col = T.C.CYAN_DIM
            box = pygame.Rect(int(c.u) - 8, int(c.v) - 8, 16, 16)
            pygame.draw.rect(cam, col, box, 1)
        assoc = self.sim.tracker.associated
        if assoc is not None and res["state"] == "LOCKED":
            apx, apy = int(assoc.u), int(assoc.v)
            # bright tracking ring + crosshair on the detected beacon
            pygame.draw.circle(cam, T.C.GREEN, (apx, apy), 14, 2)
            pygame.draw.circle(cam, T.C.GREEN, (apx, apy), 18, 1)
            _bracket(cam, (apx, apy), T.C.GREEN, 22, 2)
            pygame.draw.line(cam, T.C.GREEN, (apx - 24, apy), (apx - 18, apy), 2)
            pygame.draw.line(cam, T.C.GREEN, (apx + 18, apy), (apx + 24, apy), 2)
            pygame.draw.line(cam, T.C.GREEN, (apx, apy - 24), (apx, apy - 18), 2)
            pygame.draw.line(cam, T.C.GREEN, (apx, apy + 18), (apx, apy + 24), 2)
            T.text(cam, (apx, apy - 28), "SAT-B BEACON", 9, T.C.GREEN, bold=True, anchor="cc")
        elif assoc is not None:
            _bracket(cam, (int(assoc.u), int(assoc.v)), T.C.GREEN, 13, 2)
        # if coasting (estimate exists but no associated blob), mark est LOS
        elif res.get("est_az") is not None and res["state"] != "LOCKED":
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
        col = T.C.STATE[st]
        badge = pygame.Rect(10, 10, 110, 22)
        pygame.draw.rect(cam, tuple(c // 6 for c in col), badge)
        pygame.draw.rect(cam, col, badge, 1)
        T.text(cam, (badge.centerx, badge.centery), st, 13, col, bold=True, anchor="cc")
        W.hbar(cam, (10, 36, 110, 6), res["confidence"], T.C.STATE[st])
        T.text(cam, (124, 36), "conf", 8, T.C.TEXT_FAINT)

        # ---- top-right readouts ----
        T.text(cam, (r.right - 10, 10), f"t={res['t']:6.2f}s", 10, T.C.TEXT, anchor="tr")
        T.text(cam, (r.right - 10, 22), f"pt.err {res['pointing_err_deg'] * 1000:7.1f} mdeg",
               10, T.C.TEXT, anchor="tr")
        T.text(cam, (r.right - 10, 34),
               f"bx {res['truth_az']:+.3f}  {res['truth_el']:+.3f}", 9, T.C.TEXT_DIM, anchor="tr")

        # ---- headline SAT-B status banner ----
        self._headline_banner(cam, r)

    def _headline_banner(self, cam, r):
        """Judge-facing headline: the coarse-alignment story in one glance."""
        res = self.sim.last_result
        st = res["state"]
        col = T.C.STATE[st]
        status = {"SEARCHING": "SEARCHING", "COASTING": "PREDICTIVE COAST",
                  "LOCKED": "TRACKING", "LOST": "LOST"}[st]
        banner = pygame.Rect(r.x + 140, r.y + 6, r.w - 280, 40)
        pygame.draw.rect(cam, (8, 12, 20), banner)
        pygame.draw.rect(cam, T.C.BORDER, banner, 1)

        # left: SAT B status
        T.text(cam, (banner.x + 10, banner.y + 5), "SAT-B STATUS", 9, T.C.TEXT_FAINT)
        T.text(cam, (banner.x + 10, banner.y + 17), status, 15, col, bold=True)
        # mid: pointing error (angle between beam LOS and true LOS)
        err = res["pointing_err_deg"]
        T.text(cam, (banner.x + 150, banner.y + 5), "POINTING ERROR", 9, T.C.TEXT_FAINT)
        T.text(cam, (banner.x + 150, banner.y + 17), f"{err * 1000:6.1f} mdeg", 15, col, bold=True)
        # mp: link readiness
        ready = err < config.FINE_ACQUISITION_REGION_DEG
        T.text(cam, (banner.x + 300, banner.y + 5), "COARSE LINK", 9, T.C.TEXT_FAINT)
        T.text(cam, (banner.x + 300, banner.y + 17),
               "READY" if ready else "TUNING", 13,
               T.C.GREEN if ready else T.C.AMBER, bold=True)
        # right: acquisition + reacquisition
        st2 = self.perf.live_stats()
        acq = st2["acquisition_time_s"]
        acq_s = f"{acq:.2f}s" if acq else "--"
        reacq = st2["last_reacq_s"]
        reacq_s = f"{reacq:.2f}s" if reacq else f"{st2['reacquisition_count']} ev"
        T.text(cam, (banner.right - 10, banner.y + 5), "ACQ · REACQ", 9, T.C.TEXT_FAINT, anchor="tr")
        T.text(cam, (banner.right - 10, banner.y + 17),
               f"{acq_s} · {reacq_s}", 12, T.C.CYAN, bold=True, anchor="tr")

    def _est_pixel(self, az, el):
        """Project an az/el LOS into camera pixels using the realized pose."""
        if az is None or el is None:
            return None
        d = azel_unit(az, el)
        basis = self.sim.gimbal.basis()
        p = project_point_into_camera(d, (0, 0, 0), basis, config.FOCAL_PX,
                                      config.PRINCIPAL_U, config.PRINCIPAL_V)
        if p is None:
            return None
        u, v = p
        if 0 <= u < CAM_W and 0 <= v < CAM_H:
            return (int(u), int(v))
        return None

    # ---------------------------------------------------------------- bottom
    def _draw_bottom(self, surf):
        pygame.draw.rect(surf, T.C.PANEL, (0, 720, APP_W, 180))
        pygame.draw.line(surf, T.C.BORDER, (0, 720), (APP_W, 720), 2)
        res = self.sim.last_result
        st = res["state"]
        col = T.C.STATE[st]

        # telemetry columns
        x = 18
        T.text(surf, (x, 734), "STATE TRACKER: " + st, 13, col, bold=True)
        est = res.get("est_az")
        y = 756
        if est is not None:
            T.text(surf, (x, y), f"est  az {est:+.4f}   el {res['est_el']:+.4f}  (deg)", 11, T.C.TEXT)
        else:
            T.text(surf, (x, y), "est  az ---   el ---      (deg)", 11, T.C.TEXT_FAINT)
        y += 17
        T.text(surf, (x, y), f"true az {res['truth_az']:+.4f}   el {res['truth_el']:+.4f}  (ref)", 11, T.C.TEXT_DIM)
        y += 17
        T.text(surf, (x, y), f"bias az {self.sim.eph.bias_deg(res['t'])[0]:+.3f}   el {self.sim.eph.bias_deg(res['t'])[1]:+.3f}", 11, T.C.AMBER)

        x2 = 400
        T.text(surf, (x2, 734), "POINTING", 11, T.C.TEXT_DIM)
        T.text(surf, (x2, 754), f"error {res['pointing_err_deg'] * 1000:8.1f} mdeg", 13, col, bold=True)
        T.text(surf, (x2, 774), f"est err {res['est_err_deg'] * 1000 if res['est_err_deg'] else 0.0:8.1f} mdeg",
               11, T.C.TEXT)
        T.text(surf, (x2, 792), f"mod score {self.sim.tracker.associated.mod_score:.2f}"
               if self.sim.tracker.associated else "mod score ---", 11, T.C.TEXT)
        T.text(surf, (x2, 810), f"cands {res['candidates']}  ·  FOV {'IN' if res['in_fov'] else 'LOST'}", 11, T.C.TEXT_DIM)

        # modulation scope
        self._draw_scope(surf, (700, 730))
        # A -> beam -> B link scenario strip (right of the scope)
        self._draw_link(surf, (1060, 722))

    def _draw_link(self, surf, pos):
        """Side-view SAT-A -> OPTICAL BORESIGHT -> SAT-B diagram with live
        pointing error and coarse-alignment (LINK READY) status."""
        x, y = pos
        w, h = 520, 162
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surf, T.C.PANEL, box)
        pygame.draw.rect(surf, T.C.BORDER, box, 1)
        T.text(surf, (x + 10, y + 6), "LINK SCENARIO  ·  SATELLITE A → OPTICAL BORESIGHT → SATELLITE B",
               9, T.C.TEXT_FAINT)

        # layout
        ax = x + 70            # SAT A anchor (bottom-left of diagram)
        ay = y + 96
        bx = x + w - 70        # SAT B end
        by = y + 40

        # boresight beam: line from A through the current pointing direction.
        # draw a subtle cone representing the coarse FOV.
        err = self.sim.last_result["pointing_err_deg"]
        beam_col = T.C.GREEN if err < config.FINE_ACQUISITION_REGION_DEG else \
                   (T.C.AMBER if err < 0.30 else T.C.RED)

        # cone / beam
        cone_w = int((config.HFOV_DEG / 2.0) * 8)
        pygame.draw.polygon(surf, (24, 60, 80),
                            [(ax, ay), (bx, by - cone_w), (bx, by + cone_w)])
        pygame.draw.line(surf, beam_col, (ax, ay), (bx, by), 3)

        # SAT A icon
        pygame.draw.rect(surf, T.C.CYAN, (ax - 14, ay - 7, 28, 14), 1)
        T.text(surf, (ax, ay + 16), "SAT-A", 10, T.C.CYAN, bold=True, anchor="cc")

        # SAT B beacon icon (at the end of the beam)
        pygame.draw.circle(surf, T.C.RED, (bx, by), 7)
        pygame.draw.circle(surf, T.C.RED, (bx, by), 11, 1)
        T.text(surf, (bx, by - 22), "SAT-B", 10, T.C.RED, bold=True, anchor="cc")

        # pointing error readout under the beam
        err_label = f"POINTING ERROR   {err * 1000:6.1f} mdeg"
        T.text(surf, (x + w // 2, y + 108), err_label, 13, beam_col, bold=True, anchor="cc")

        # coarse-alignment status (link-ready threshold)
        link_ready = err < config.FINE_ACQUISITION_REGION_DEG
        badge = pygame.Rect(x + w - 150, y + 28, 134, 24)
        linkcol = T.C.GREEN if link_ready else T.C.AMBER
        pygame.draw.rect(surf, tuple(c // 4 for c in linkcol), badge)
        pygame.draw.rect(surf, linkcol, badge, 1)
        T.text(surf, (badge.centerx, badge.centery),
               "LINK READY" if link_ready else "COARSE TUNING",
               12, linkcol, bold=True, anchor="cc")
        T.text(surf, (x + w - 83, y + 54), f"{err * 1000:6.1f} mdeg", 10,
               T.C.TEXT, anchor="cc")

        # beam angle annotation
        bl = x + 60
        T.text(surf, (bl, y + 56), f"boresight {self.sim.gimbal.pan:+.2f}° "
                                    f"{self.sim.gimbal.tilt:+.2f}°", 9, T.C.TEXT_DIM)

    def _draw_scope(self, surf, pos):
        x, y = pos
        w, h = 360, 120
        T.text(surf, (x, y - 2), "ASSOCIATED OBJECT · BRIGHTNESS vs 15 Hz MOD TEMPLATE",
               9, T.C.TEXT_FAINT)
        box = pygame.Rect(x, y + 12, w, h)
        pygame.draw.rect(surf, T.C.PANEL_2, box)
        pygame.draw.rect(surf, T.C.BORDER, box, 1)
        hist = list(self.sim.intensity_hist)
        n = len(hist)
        if n > 1:
            vals = [v for v in hist if v is not None]
            vmax = max(vals + [1.0])
            pts = []
            for i, v in enumerate(hist):
                yy = box.bottom - 4 - (box.h - 8) * (v / vmax if v else 0.0)
                xx = box.x + 3 + (box.w - 6) * i / (n - 1)
                pts.append((int(xx), int(yy)))
            pygame.draw.lines(surf, T.C.GREEN, False, pts, 1)
            # template top (nominal rms midpoint)
            mid = box.bottom - 4 - (box.h - 8) * 0.5
            pygame.draw.line(surf, (60, 80, 100), (box.x + 2, mid), (box.right - 2, mid), 1)

    # ---------------------------------------------------------------- panel
    def _draw_panel(self, surf):
        pygame.draw.rect(surf, T.C.PANEL, (1280, 0, 320, APP_H))
        pygame.draw.line(surf, T.C.BORDER, (1280, 0), (1280, APP_H), 2)

        self._draw_panel_header(surf)
        self._draw_panel_kpi(surf)
        self._draw_panel_sliders(surf)
        self._draw_panel_spark(surf)
        for b in self.buttons.values():
            b.draw(surf)
        T.text(surf, (1280 + 10, 872), "space pause · R reset · S shot · 1-5 preset", 8, T.C.TEXT_FAINT)

    def _draw_panel_header(self, surf):
        x = 1288
        T.text(surf, (x, 12), "PRESET", 11, T.C.TEXT_DIM)
        for name, c in self.chips.items():
            c.draw(surf, selected=(name == self.preset))
        view3d.render(surf, pygame.Rect(1288, 74, 304, 178), self.sim, self.sim.t)

    def _draw_panel_kpi(self, surf):
        st = self.perf.live_stats()
        res = self.sim.last_result
        lock_col = T.C.GREEN if res["state"] == "LOCKED" else T.C.AMBER
        reacq = st["last_reacq_s"]
        rows = {
            "state": (res["state"], lock_col),
            "confidence": (f"{res['confidence']:.2f}", T.C.TEXT),
            "acquisition": (f"{st['acquisition_time_s']:.2f}s" if st["acquisition_time_s"] else "---", T.C.TEXT),
            "reacquisition": (f"{reacq:.2f}s" if reacq else f"{st['reacquisition_count']} evts", T.C.TEXT),
            "mean err": (f"{st['mean_err_deg'] * 1000:.0f} mdeg" if st["mean_err_deg"] else "---", T.C.TEXT),
            "rms err": (f"{st['rms_err_deg'] * 1000:.0f} mdeg" if st["rms_err_deg"] else "---", T.C.TEXT),
            "max err": (f"{st['max_err_deg'] * 1000:.0f} mdeg" if st["max_err_deg"] else "---", T.C.TEXT),
            "retention": (f"{st['retention_total_pct']:.1f}%", T.C.TEXT),
            "actual fps": (f"{st['fps']:.0f}", T.C.CYAN),
        }
        W.kpi_card(surf, pygame.Rect(1288, 262, 304, 158), "PERFORMANCE", rows)

    def _draw_panel_sliders(self, surf):
        # physical unit hints ("what this dial's % means") under each slider
        for key, s in self.sliders.items():
            s.draw(surf)
            unit = config.DISTURBANCE_UNITS.get(key, (None, ""))[1]
            if unit:
                T.text(surf, (s.rect.x, s.rect.y + 28), unit, 8, T.C.TEXT_FAINT)

    def _draw_panel_spark(self, surf):
        T.text(surf, (1290, 588), "POINTING ERROR (mdeg, scale 0..400)", 9, T.C.TEXT_FAINT)
        rect = pygame.Rect(1288, 600, 304, 72)
        pygame.draw.rect(surf, T.C.PANEL_2, rect)
        series = [max(0.0, min(0.4, e)) for e in self.error_spark]
        W.sparkline(surf, rect, series, T.C.GREEN, band=(0.0, 0.05), max_v=0.4)


def _bracket(surf, center, color, r, th):
    x, y = center
    L = r
    for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        pygame.draw.line(surf, color, (x + dx * r, y + dy * L), (x + dx * r, y + dy * (r - L // 2)), th)
        pygame.draw.line(surf, color, (x + dx * r, y + dy * L), (x + dx * (r - L // 2), y + dy * L), th)


def headless_selftest(frames, preset):
    print(f"headless self-test: preset={preset} frames={frames}")
    sim = Simulator(preset_name=preset, seed=1)
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
    args = ap.parse_args()

    if args.frames > 0:
        headless_selftest(args.frames, args.preset.upper())
        return

    app = App(preset=args.preset.upper(), fullscreen=args.fullscreen)
    app.run()


if __name__ == "__main__":
    main()