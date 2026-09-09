"""
ui/mission_pages.py — SpaceX / ISRO Mission Control pages rendered natively in Pygame CE.
Faithfully reproduces Figma designs:
  - Overview: Image 2
  - Telemetry: Image 1
  - Simulation: Images 3 & 4
  - False Lock: Image 5
  - Event Log: Filterable log & subsystem health
"""

import math
import time
from collections import deque
import pygame
import numpy as np

from ui import theme as T
from ui.theme import C


# ---------------------------------------------------------------------------
# Physical Optical Link Model & State
# ---------------------------------------------------------------------------
class OpticalLinkModel:
    """Computes realistic FSOC optical link budget and telemetry values."""

    def __init__(self):
        # Configurable transmitter & link parameters
        self.tx_power_dbm = 30.0       # 0 .. 40 dBm
        self.wavelength_nm = 1550.0    # 800 .. 1600 nm
        self.distance_km = 5.0         # 0.1 .. 50 km
        self.data_rate_gbps = 10.0     # 0.1 .. 100 Gbps
        self.rx_sensitivity_dbm = -50.0  # -70 .. -20 dBm

        # Optical system parameters
        self.beam_divergence_mrad = 1.5  # 0.1 .. 5.0 mrad
        self.pointing_error_urad = 1.64  # 0 .. 100 µrad

        # Atmospheric conditions
        self.visibility_km = 15.0      # 0.1 .. 50 km
        self.turbulence_cn2 = 2.0e-15  # 0.01e-15 .. 20.0e-15

        # Environmental readouts
        self.temperature_c = 22.6
        self.humidity_pct = 58.0
        self.wind_speed_ms = 4.0

        # Rolling history for charts
        self.history = deque(maxlen=120)
        self._last_t = 0.0

    def update_from_sim(self, sim_result):
        """Synchronize real-time simulator measurements."""
        t = sim_result.get("t", 0.0)
        ptg_deg = sim_result.get("pointing_err_deg", 0.001)
        # Convert degrees to microradians (1 deg = 17453.3 µrad)
        live_ptg_urad = max(0.5, ptg_deg * 17453.3)
        # Smooth with previous
        self.pointing_error_urad = round(0.85 * self.pointing_error_urad + 0.15 * live_ptg_urad, 2)

        conf = sim_result.get("confidence", 0.95)
        state = sim_result.get("state", "LOCKED")

        # Atmospheric loss based on visibility (Kim / Kruse model)
        q = 1.6 if self.visibility_km > 50 else (1.3 if self.visibility_km > 6 else 0.585 * (self.visibility_km ** (1/3)))
        beta = (3.91 / max(0.1, self.visibility_km)) * ((self.wavelength_nm / 550.0) ** (-q))
        atm_loss = round(beta * self.distance_km, 2)

        # Geometric loss (free-space divergence loss)
        geo_loss = round(20.0 * math.log10(max(1.0, self.distance_km * 1000.0 * (self.beam_divergence_mrad * 1e-3) / 0.1)), 1)
        geo_loss = max(10.0, min(65.0, geo_loss))

        # Pointing loss
        div_rad = max(1e-6, self.beam_divergence_mrad * 1e-3)
        err_rad = self.pointing_error_urad * 1e-6
        ptg_loss = round(4.34 * ((2.0 * err_rad / div_rad) ** 2), 2)

        total_loss = round(atm_loss + geo_loss + ptg_loss, 2)
        rx_power = round(self.tx_power_dbm - total_loss, 2)
        link_margin = round(rx_power - self.rx_sensitivity_dbm, 2)

        # Signal-to-Noise Ratio (dB)
        base_snr = 85.0 - total_loss * 0.8
        jitter = (math.sin(t * 1.5) * 0.4) + (math.cos(t * 3.7) * 0.2)
        snr = max(0.0, round(base_snr + jitter, 2))

        # Bit Error Rate (BER)
        if snr > 40.0:
            ber = 1.0e-15
            ber_str = "1.00e-15"
        elif snr > 20.0:
            ber = 1.0e-12
            ber_str = "<1e-12"
        elif snr > 12.0:
            ber = 1.0e-8
            ber_str = "1.00e-08"
        else:
            ber = 1.0e-4
            ber_str = "1.00e-04"

        # Tracking stability
        stability = min(99.9, max(50.0, round(conf * 98.0 + (math.cos(t * 2.0) * 0.8), 1)))

        # Propagation delay (tau = d / c)
        prop_delay_us = round((self.distance_km * 1000.0) / (3e8) * 1e6, 2)

        point = {
            "t": round(t, 2),
            "rx_power": rx_power,
            "link_margin": link_margin,
            "snr": snr,
            "ber": ber,
            "ber_str": ber_str,
            "atm_loss": atm_loss,
            "geo_loss": geo_loss,
            "ptg_loss": ptg_loss,
            "total_loss": total_loss,
            "pointing_error_urad": self.pointing_error_urad,
            "stability": stability,
            "prop_delay_us": prop_delay_us,
            "state": state,
        }

        if abs(t - self._last_t) >= 0.08:
            self.history.append(point)
            self._last_t = t

        return point


# ---------------------------------------------------------------------------
# Interactive Slider Component for Simulation Page
# ---------------------------------------------------------------------------
class SimSlider:
    def __init__(self, rect, label, subtext, v_min, v_max, v_cur, unit, badge_text="CTRL", fmt="{:.1f}"):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.subtext = subtext
        self.v_min = v_min
        self.v_max = v_max
        self.value = v_cur
        self.unit = unit
        self.badge_text = badge_text
        self.fmt = fmt
        self.dragging = False

    @property
    def frac(self):
        return (self.value - self.v_min) / max(1e-6, (self.v_max - self.v_min))

    def set_frac(self, f):
        f = max(0.0, min(1.0, f))
        self.value = self.v_min + f * (self.v_max - self.v_min)

    def hit(self, pos):
        # Hit either the label area or the track
        expanded = pygame.Rect(self.rect.x, self.rect.y - 10, self.rect.w, self.rect.h + 24)
        return expanded.collidepoint(pos)

    def drag_to(self, x):
        track_x = self.rect.x
        track_w = self.rect.w
        self.set_frac((x - track_x) / max(1, track_w))

    def draw(self, surf):
        # Label & subtext
        T.text(surf, (self.rect.x, self.rect.y - 30), self.label, 12, C.TEXT, bold=True)
        T.text(surf, (self.rect.x, self.rect.y - 15), self.subtext, 10, C.TEXT_FAINT)

        # Right side: Badge + Value (dynamically spaced to prevent collision)
        val_str = f"{self.fmt.format(self.value)} {self.unit}"
        val_w, _ = T.font(12, bold=True).size(val_str)
        badge_w, badge_h = 42, 18
        badge_x = self.rect.right - val_w - badge_w - 14
        badge_y = self.rect.y - 26
        pygame.draw.rect(surf, (0, 36, 68), (badge_x, badge_y, badge_w, badge_h), border_radius=2)
        pygame.draw.rect(surf, C.CYAN_ELEC, (badge_x, badge_y, badge_w, badge_h), 1, border_radius=2)
        T.text(surf, (badge_x + badge_w // 2, badge_y + 2), self.badge_text, 9, C.CYAN_ELEC, bold=True, anchor="tc")

        T.text(surf, (self.rect.right, self.rect.y - 28), val_str, 12, C.TEXT, bold=True, anchor="tr")

        # Track background
        track_h = 8
        pygame.draw.rect(surf, (16, 26, 44), (self.rect.x, self.rect.y, self.rect.w, track_h), border_radius=3)

        # Filled active bar
        fill_w = int(round(self.rect.w * self.frac))
        if fill_w > 0:
            pygame.draw.rect(surf, C.CYAN, (self.rect.x, self.rect.y, fill_w, track_h), border_radius=3)

        # Knob
        kx = self.rect.x + fill_w
        ky = self.rect.y + track_h // 2
        pygame.draw.circle(surf, C.CYAN_ELEC, (kx, ky), 7)
        pygame.draw.circle(surf, (255, 255, 255), (kx, ky), 2)

        # Range limits below track
        min_str = f"{self.fmt.format(self.v_min)} {self.unit}"
        max_str = f"{self.fmt.format(self.v_max)} {self.unit}"
        T.text(surf, (self.rect.x, self.rect.y + 11), min_str, 10, C.TEXT_FAINT)
        T.text(surf, (self.rect.right, self.rect.y + 11), max_str, 10, C.TEXT_FAINT, anchor="tr")


# ---------------------------------------------------------------------------
# PAGE 1: OVERVIEW (Figma Image 2)
# ---------------------------------------------------------------------------
def render_overview_page(surf, rect, sim, perf, opt: OpticalLinkModel, hist_pt: dict):
    """
    Renders Overview dashboard matching Figma Image 2:
    - 6 Top KPI Cards
    - Optical Link Tx -> Rx Visualization with Animated Beam & Loss Budget
    - Subsystem Health Matrix (green indicators)
    - Link Quality History Chart
    - Environment Telemetry Matrix
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h

    # 1. Top KPI Row (6 Cards across full width)
    kpi_w = (w - 10 * 5) // 6
    kpi_h = 74
    kpis = [
        ("LINK STATE", hist_pt.get("state", "ESTABLISHED"), "", f"5 km · 1550 nm · {hist_pt.get('prop_delay_us', 16.7):.1f} µs", C.GREEN),
        ("RX OPTICAL POWER", f"{hist_pt.get('rx_power', -11.4):.1f}", "dBm", f"TX {opt.tx_power_dbm:.0f} dBm · sens {opt.rx_sensitivity_dbm:.0f} dBm", C.CYAN_ELEC),
        ("SIGNAL / NOISE RATIO", f"{hist_pt.get('snr', 73.6):.1f}", "dB", "threshold ≥ 8 dB", C.GREEN),
        ("LINK MARGIN", f"{hist_pt.get('link_margin', 38.6):.1f}", "dB", "threshold ≥ 5 dB", C.GREEN),
        ("POINTING ERROR", f"{hist_pt.get('pointing_error_urad', 1.50):.2f}", "µrad", f"beam div {opt.beam_divergence_mrad:.1f} mrad", C.CYAN_ELEC),
        ("LOCK CONFIDENCE", f"{hist_pt.get('stability', 95.0):.1f}", "%", f"tracking {int(round(hist_pt.get('stability', 95)))}%", C.CYAN_ELEC),
    ]

    for i, (label, val, unit, sub, col) in enumerate(kpis):
        kx = x0 + i * (kpi_w + 10)
        T.card(surf, (kx, y0, kpi_w, kpi_h), fill=C.CARD_BG, border=C.BORDER)
        T.text(surf, (kx + 10, y0 + 8), label, 10, C.TEXT_FAINT, bold=True)
        vw, vh = T.text(surf, (kx + 10, y0 + 24), val, 20, col, bold=True)
        if unit:
            T.text(surf, (kx + 14 + vw, y0 + 30), unit, 11, C.TEXT_DIM)
        if sub:
            T.text(surf, (kx + 10, y0 + 52), sub, 10, C.TEXT_FAINT)

    # 2. Middle Section: OPTICAL LINK VISUALIZATION (matching Image 2)
    vis_y = y0 + kpi_h + 12
    vis_h = 168
    T.card(surf, (x0, vis_y, w, vis_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 14, vis_y + 10, "OPTICAL LINK VISUALIZATION", C.CYAN_ELEC)

    # Right side status badge
    st_text = "● " + hist_pt.get("state", "ESTABLISHED")
    T.text(surf, (x0 + w - 16, vis_y + 10), st_text, 13, C.GREEN, bold=True, anchor="tr")

    # TX Node (left) and RX Node (right)
    tx_node_x = x0 + 230
    rx_node_x = x0 + w - 230
    beam_y = vis_y + 54

    # TX Box
    pygame.draw.rect(surf, (14, 28, 54), (tx_node_x - 36, beam_y - 18, 52, 34), border_radius=3)
    pygame.draw.rect(surf, C.CYAN_ELEC, (tx_node_x - 36, beam_y - 18, 52, 34), 1, border_radius=3)
    T.text(surf, (tx_node_x - 10, beam_y - 9), "TX", 12, C.CYAN_ELEC, bold=True, anchor="cc")
    T.text(surf, (tx_node_x - 10, beam_y + 22), f"{opt.tx_power_dbm:.0f} dBm", 11, C.TEXT_FAINT, anchor="tc")

    # RX Aperture Circle
    pygame.draw.circle(surf, (14, 38, 48), (rx_node_x + 10, beam_y), 19)
    pygame.draw.circle(surf, C.GREEN, (rx_node_x + 10, beam_y), 19, 1)
    pygame.draw.circle(surf, C.CYAN, (rx_node_x + 10, beam_y), 7)
    T.text(surf, (rx_node_x + 10, beam_y - 7), "RX", 11, C.GREEN, bold=True, anchor="cc")
    T.text(surf, (rx_node_x + 10, beam_y + 22), f"{hist_pt.get('rx_power', -11.4):.1f} dBm", 11, C.TEXT_FAINT, anchor="tc")

    # Glowing Laser Beam connecting TX -> RX
    p_alpha = int(180 + 75 * math.sin(time.time() * 6.0))
    pygame.draw.line(surf, (0, 60, 40), (tx_node_x + 18, beam_y), (rx_node_x - 10, beam_y), 6)
    pygame.draw.line(surf, C.GREEN, (tx_node_x + 18, beam_y), (rx_node_x - 10, beam_y), 2)
    pygame.draw.circle(surf, (255, 255, 255), (tx_node_x + 18, beam_y), 3)

    # Distance label in center of beam
    cx = (tx_node_x + rx_node_x) // 2
    pygame.draw.rect(surf, (8, 14, 28), (cx - 30, beam_y - 11, 60, 22), border_radius=2)
    pygame.draw.rect(surf, C.BORDER, (cx - 30, beam_y - 11, 60, 22), 1, border_radius=2)
    T.text(surf, (cx, beam_y - 2), f"{opt.distance_km:.1f} km", 11, C.TEXT_DIM, bold=True, anchor="cc")

    # Sub-bar inside Optical Link Box
    sub_y = vis_y + 96
    mini_w = (w - 28 - 10 * 3) // 4
    mini_metrics = [
        ("RX POWER", f"{hist_pt.get('rx_power', -11.4):.1f} dBm", C.TEXT),
        ("SNR", f"{hist_pt.get('snr', 73.6):.1f} dB", C.TEXT),
        ("BER", hist_pt.get("ber_str", "<1e-12"), C.TEXT),
        ("LINK MARGIN", f"{hist_pt.get('link_margin', 38.6):.1f} dB", C.TEXT),
    ]
    for mi, (ml, mv, mc) in enumerate(mini_metrics):
        mx = x0 + 14 + mi * (mini_w + 10)
        pygame.draw.rect(surf, (12, 18, 32), (mx, sub_y, mini_w, 30), border_radius=2)
        T.text(surf, (mx + 8, sub_y + 4), ml, 10, C.TEXT_FAINT)
        T.text(surf, (mx + 8, sub_y + 15), mv, 13, mc, bold=True)

    # Loss budget text & Tracking stability bar at bottom of card
    loss_y = vis_y + 138
    loss_txt = f"LOSS BUDGET    ATM {hist_pt.get('atm_loss', 1.5):.1f} dB    GEO {hist_pt.get('geo_loss', 40.0):.1f} dB    PTG {hist_pt.get('ptg_loss', 0.0):.1f} dB    TOTAL {hist_pt.get('total_loss', 41.5):.1f} dB"
    T.text(surf, (x0 + 16, loss_y), loss_txt, 11, C.TEXT_FAINT, bold=True)

    # Tracking stability progress bar
    stab_val = hist_pt.get("stability", 96.5)
    T.text(surf, (x0 + w - 260, loss_y), "TRACKING STABILITY", 10, C.TEXT_FAINT, bold=True)
    bar_x = x0 + w - 130
    pygame.draw.rect(surf, (14, 24, 40), (bar_x, loss_y + 1, 70, 8), border_radius=2)
    pygame.draw.rect(surf, C.GREEN, (bar_x, loss_y + 1, int(70 * (stab_val / 100.0)), 8), border_radius=2)
    T.text(surf, (x0 + w - 16, loss_y - 2), f"{stab_val:.1f}%", 11, C.GREEN, bold=True, anchor="tr")

    # 3. Third Row: Metric Readout Strips (7 items across width)
    strip_y = vis_y + vis_h + 10
    strip_h = 52
    strip_w = (w - 10 * 6) // 7
    strips = [
        ("BIT ERROR RATE", hist_pt.get("ber_str", "<1e-12"), "thr: < 1e-6", C.TEXT),
        ("ATM LOSS", f"{hist_pt.get('atm_loss', 1.5):.1f} dB", f"vis {opt.visibility_km:.0f} km", C.GREEN),
        ("GEOMETRIC LOSS", f"{hist_pt.get('geo_loss', 40.0):.1f} dB", f"dist {opt.distance_km:.0f} km", C.TEXT),
        ("POINTING LOSS", f"{hist_pt.get('ptg_loss', 0.0):.1f} dB", f"div {opt.beam_divergence_mrad:.1f} mrad", C.TEXT),
        ("DATA RATE", f"{opt.data_rate_gbps:.0f} Gbps", f"λ {opt.wavelength_nm:.0f} nm", C.CYAN_ELEC),
        ("TEMPERATURE", f"{opt.temperature_c:.1f} °C", f"hum {opt.humidity_pct:.0f}%", C.TEXT),
        ("WIND SPEED", f"{opt.wind_speed_ms:.1f} m/s", "dir 045°", C.TEXT),
    ]
    for si, (s_label, s_val, s_sub, s_col) in enumerate(strips):
        sx = x0 + si * (strip_w + 10)
        T.card(surf, (sx, strip_y, strip_w, strip_h), fill=C.CARD_BG, border=C.BORDER)
        T.text(surf, (sx + 8, strip_y + 5), s_label, 10, C.TEXT_FAINT, bold=True)
        T.text(surf, (sx + 8, strip_y + 19), s_val, 14, s_col, bold=True)
        T.text(surf, (sx + 8, strip_y + 36), s_sub, 10, C.TEXT_FAINT)

    # 4. Bottom Row: 3 Columns
    # Left: Subsystem Health (width 260)
    # Center: Link Quality Recent History (flex width)
    # Right: Environment Matrix (width 220)
    bot_y = strip_y + strip_h + 10
    bot_h = h - (bot_y - y0) - 6

    # Subsystem Health Panel
    sh_w = 260
    T.card(surf, (x0, bot_y, sh_w, bot_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 12, bot_y + 10, "SUBSYSTEM HEALTH", C.CYAN_ELEC)

    subsystems = [
        ("Transmitter", f"{opt.tx_power_dbm:.0f} dBm", C.GREEN),
        ("Receiver", f"{hist_pt.get('rx_power', -11.4):.1f} dBm", C.GREEN),
        ("Optical Link", "NOMINAL", C.GREEN),
        ("Beam Alignment", f"{hist_pt.get('pointing_error_urad', 1.5):.1f} µrad", C.GREEN),
        ("Tracking Loop", f"{int(round(hist_pt.get('stability', 97)))}%", C.GREEN),
        ("Lock Detector", "CLEAR", C.GREEN),
    ]
    sub_row_y = bot_y + 34
    for s_name, s_val, s_col in subsystems:
        pygame.draw.circle(surf, s_col, (x0 + 18, sub_row_y + 8), 4)
        T.text(surf, (x0 + 28, sub_row_y + 2), s_name, 11, C.TEXT_DIM, bold=True)
        T.text(surf, (x0 + sh_w - 14, sub_row_y + 2), s_val, 11, s_col, bold=True, anchor="tr")
        sub_row_y += 22

    # Right: Environment Panel
    env_w = 230
    env_x = x0 + w - env_w
    T.card(surf, (env_x, bot_y, env_w, bot_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, env_x + 12, bot_y + 10, "ENVIRONMENT", C.CYAN_ELEC)

    env_items = [
        ("Temperature", f"{opt.temperature_c:.1f} °C"),
        ("Humidity", f"{opt.humidity_pct:.0f} %"),
        ("Wind Speed", f"{opt.wind_speed_ms:.1f} m/s"),
        ("Visibility", f"{opt.visibility_km:.0f} km"),
        ("Turbulence", f"{opt.turbulence_cn2:.2e}"),
        ("Wavelength", f"{opt.wavelength_nm:.0f} nm"),
        ("Distance", f"{opt.distance_km:.1f} km"),
        ("Delay", f"{hist_pt.get('prop_delay_us', 16.7):.1f} µs"),
    ]
    env_row_y = bot_y + 32
    for e_name, e_val in env_items:
        T.text(surf, (env_x + 14, env_row_y + 2), e_name, 10, C.TEXT_FAINT)
        T.text(surf, (env_x + env_w - 14, env_row_y + 2), e_val, 11, C.TEXT, bold=True, anchor="tr")
        env_row_y += 20

    # Center: Link Quality Recent History Chart
    ch_x = x0 + sh_w + 10
    ch_w = env_x - ch_x - 10
    T.card(surf, (ch_x, bot_y, ch_w, bot_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, ch_x + 12, bot_y + 10, "LINK QUALITY — RECENT HISTORY", C.CYAN_ELEC)

    # Chart Legend - right-aligned to prevent collision with section title
    leg_x = max(ch_x + 280, ch_x + ch_w - 240)
    pygame.draw.line(surf, C.GREEN, (leg_x, bot_y + 16), (leg_x + 12, bot_y + 16), 2)
    T.text(surf, (leg_x + 16, bot_y + 10), "SNR", 10, C.TEXT_FAINT, bold=True)
    pygame.draw.line(surf, C.CYAN_ELEC, (leg_x + 56, bot_y + 16), (leg_x + 68, bot_y + 16), 2)
    T.text(surf, (leg_x + 72, bot_y + 10), "BER (inv)", 10, C.TEXT_FAINT, bold=True)
    pygame.draw.line(surf, C.AMBER, (leg_x + 144, bot_y + 16), (leg_x + 156, bot_y + 16), 1)
    T.text(surf, (leg_x + 160, bot_y + 10), "SNR threshold", 10, C.TEXT_FAINT, bold=True)

    # Draw chart grid & lines
    plot_rect = pygame.Rect(ch_x + 14, bot_y + 36, ch_w - 28, bot_h - 48)
    pygame.draw.rect(surf, (6, 11, 22), plot_rect)
    pygame.draw.rect(surf, C.BORDER, plot_rect, 1)

    # Grid ticks
    for gy in range(plot_rect.y + 20, plot_rect.bottom, 24):
        pygame.draw.line(surf, (14, 24, 42), (plot_rect.x, gy), (plot_rect.right, gy), 1)

    # Render rolling curves from opt.history
    pts = list(opt.history)
    if len(pts) >= 2:
        snr_pts = []
        ber_pts = []
        n = len(pts)
        for idx, p in enumerate(pts):
            px = plot_rect.x + int(plot_rect.w * idx / (n - 1))
            # SNR: map 40..85 dB to plot height
            s_frac = (p.get("snr", 73.0) - 40.0) / 45.0
            py_snr = plot_rect.bottom - int(plot_rect.h * max(0.05, min(0.95, s_frac)))
            snr_pts.append((px, py_snr))

            # BER inv curve
            b_val = 15.0 if p.get("ber", 1e-15) <= 1e-14 else (12.0 if p.get("ber", 1e-12) <= 1e-11 else 8.0)
            b_frac = b_val / 16.0
            py_ber = plot_rect.bottom - int(plot_rect.h * max(0.1, min(0.9, b_frac)))
            ber_pts.append((px, py_ber))

        if len(snr_pts) >= 2:
            pygame.draw.lines(surf, C.GREEN, False, snr_pts, 2)
        if len(ber_pts) >= 2:
            pygame.draw.lines(surf, C.CYAN_ELEC, False, ber_pts, 1)

    # Threshold dashed line
    thr_y = plot_rect.bottom - int(plot_rect.h * 0.22)
    for tx in range(plot_rect.x, plot_rect.right, 8):
        pygame.draw.line(surf, C.AMBER, (tx, thr_y), (tx + 4, thr_y), 1)


# ---------------------------------------------------------------------------
# PAGE 2: TELEMETRY (Figma Image 1)
# ---------------------------------------------------------------------------
def render_telemetry_page(surf, rect, sim, perf, opt: OpticalLinkModel, hist_pt: dict):
    """
    Renders Telemetry dashboard matching Figma Image 1:
    - 2x2 Grid of High-Precision Graphs:
      1. OPTICAL POWER — RX vs MARGIN
      2. BIT ERROR RATE — LOG SCALE (with 1e-3, 1e-6 threshold lines)
      3. SIGNAL-TO-NOISE RATIO (with 15 dB nom, 8 dB min lines)
      4. POINTING ERROR & ATMOSPHERIC LOSS (dual axis)
    - Bottom Table: CURRENT TELEMETRY VALUES (12-metric grid)
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h

    # 2x2 grid dimensions
    table_h = 148
    grid_h = h - table_h - 14
    cell_w = (w - 12) // 2
    cell_h = (grid_h - 12) // 2

    # Chart 1: OPTICAL POWER — RX vs MARGIN (Top-Left)
    c1_rect = pygame.Rect(x0, y0, cell_w, cell_h)
    _draw_telemetry_chart_card(
        surf, c1_rect, "OPTICAL POWER — RX vs MARGIN",
        y_labels=["45dBm", "30dBm", "15dBm", "0dBm"],
        series=[
            ("rx", C.CYAN_ELEC, [(i, -11.4 + 0.3 * math.sin(i * 0.1)) for i in range(40)], False),
            ("margin", C.TEAL, [(i, 38.4 + 0.2 * math.cos(i * 0.15)) for i in range(40)], True),
        ],
        dashed_lines=[(38, C.CYAN_DIM, "38dB")],
        fill_base=True
    )

    # Chart 2: BIT ERROR RATE — LOG SCALE (Top-Right)
    c2_rect = pygame.Rect(x0 + cell_w + 12, y0, cell_w, cell_h)
    _draw_telemetry_chart_card(
        surf, c2_rect, "BIT ERROR RATE — LOG SCALE",
        y_labels=["1e-2", "1e-7", "1e-11"],
        series=[
            ("ber", C.CYAN_ELEC, [(i, 1.0) for i in range(40)], False),
        ],
        dashed_lines=[
            (82, C.RED, "1e-3 (max)"),
            (68, C.AMBER, "1e-6 (nom)"),
        ],
    )

    # Chart 3: SIGNAL-TO-NOISE RATIO (Bottom-Left)
    c3_rect = pygame.Rect(x0, y0 + cell_h + 12, cell_w, cell_h)
    _draw_telemetry_chart_card(
        surf, c3_rect, "SIGNAL-TO-NOISE RATIO",
        y_labels=["80dB", "60dB", "40dB", "20dB"],
        series=[
            ("snr", C.GREEN, [(i, 73.4 + 0.4 * math.sin(i * 0.2)) for i in range(40)], False),
        ],
        dashed_lines=[
            (28, C.CYAN_DIM, "15dB nom"),
            (16, C.AMBER, "8dB min"),
        ],
    )

    # Chart 4: POINTING ERROR & ATMOSPHERIC LOSS (Bottom-Right, Dual Axis)
    c4_rect = pygame.Rect(x0 + cell_w + 12, y0 + cell_h + 12, cell_w, cell_h)
    # Generate smooth oscillating curve for pointing error
    t_now = time.time()
    pe_pts = [(i, 4.8 + 1.2 * math.sin((i * 0.2) + t_now * 1.5)) for i in range(40)]
    _draw_dual_axis_chart_card(
        surf, c4_rect, "POINTING ERROR & ATMOSPHERIC LOSS",
        left_labels=["8µr", "6µr", "4µr", "2µr"],
        right_labels=["1.6dB", "1.2dB", "0.8dB", "0.4dB"],
        curve_pts=pe_pts,
        atm_loss_val=hist_pt.get("atm_loss", 1.47),
    )

    # 5. Bottom Panel: CURRENT TELEMETRY VALUES (matching Image 1)
    tbl_rect = pygame.Rect(x0, y0 + grid_h + 10, w, table_h)
    T.card(surf, tbl_rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 16, tbl_rect.y + 12, "CURRENT TELEMETRY VALUES", C.CYAN_ELEC)

    # 12 Metrics in 4 columns x 3 rows
    grid_metrics = [
        # Col 1
        ("RX Optical Power", f"{hist_pt.get('rx_power', -11.65):.2f} dBm", C.CYAN_ELEC),
        ("Link Margin", f"{hist_pt.get('link_margin', 38.35):.2f} dB", C.CYAN_ELEC),
        ("Temperature", f"{opt.temperature_c:.1f} °C", C.TEXT),

        # Col 2
        ("TX Optical Power", f"{opt.tx_power_dbm:.1f} dBm", C.CYAN_ELEC),
        ("Atmospheric Loss", f"{hist_pt.get('atm_loss', 1.47):.2f} dB", C.CYAN_ELEC),
        ("Humidity", f"{opt.humidity_pct:.0f} %", C.TEXT),

        # Col 3
        ("Bit Error Rate", hist_pt.get("ber_str", "1.00e-15"), C.CYAN_ELEC),
        ("Pointing Error", f"{hist_pt.get('pointing_error_urad', 1.64):.2f} µrad", C.CYAN_ELEC),
        ("Wind Speed", f"{opt.wind_speed_ms:.1f} m/s", C.TEXT),

        # Col 4
        ("Signal-to-Noise", f"{hist_pt.get('snr', 73.35):.2f} dB", C.CYAN_ELEC),
        ("Tracking Stability", f"{hist_pt.get('stability', 95.8):.1f} %", C.CYAN_ELEC),
        ("Propagation Delay", f"{hist_pt.get('prop_delay_us', 16.68):.2f} µs", C.TEXT),
    ]

    col_w = (w - 32) // 4
    for idx, (lbl, val, col) in enumerate(grid_metrics):
        ci = idx // 3
        ri = idx % 3
        item_x = x0 + 20 + ci * col_w
        item_y = tbl_rect.y + 44 + ri * 32
        T.text(surf, (item_x, item_y), lbl, 11, C.TEXT_FAINT)
        T.text(surf, (item_x + col_w - 24, item_y), val, 13, col, bold=True, anchor="tr")


def _draw_telemetry_chart_card(surf, rect, title, y_labels, series, dashed_lines=None, fill_base=False):
    T.card(surf, rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, rect.x + 14, rect.y + 10, title, C.CYAN_ELEC)

    # Plot area
    plot = pygame.Rect(rect.x + 60, rect.y + 36, rect.w - 80, rect.h - 52)
    pygame.draw.rect(surf, (6, 11, 22), plot)
    pygame.draw.rect(surf, (18, 30, 52), plot, 1)

    # Y-axis labels
    n_labels = len(y_labels)
    for i, yl in enumerate(y_labels):
        ly = plot.y + int(plot.h * i / max(1, (n_labels - 1)))
        T.text(surf, (plot.x - 8, ly - 6), yl, 10, C.TEXT_FAINT, anchor="tr")
        pygame.draw.line(surf, (12, 22, 38), (plot.x, ly), (plot.right, ly), 1)

    # Dashed threshold lines
    if dashed_lines:
        for val_pct, color, tag in dashed_lines:
            dy = plot.bottom - int(plot.h * (val_pct / 100.0))
            if plot.y <= dy <= plot.bottom:
                for dx in range(plot.x, plot.right, 8):
                    pygame.draw.line(surf, color, (dx, dy), (dx + 4, dy), 1)
                T.text(surf, (plot.right - 90, dy - 10), tag, 10, color, bold=True)

    # Optional shaded baseline area (like Optical Power chart in Figma Image 1)
    if fill_base:
        shade_rect = pygame.Rect(plot.x, plot.bottom - 24, plot.w, 24)
        pygame.draw.rect(surf, (0, 36, 48), shade_rect)
        pygame.draw.line(surf, C.CYAN, (plot.x, plot.bottom - 24), (plot.right, plot.bottom - 24), 1)

    # Plot lines
    for name, col, pts, is_top in series:
        if pts:
            screen_pts = []
            for px_i, val in pts:
                sx = plot.x + int(plot.w * (px_i / max(1, len(pts) - 1)))
                if is_top:
                    sy = plot.y + 18
                else:
                    sy = plot.bottom - 24
                screen_pts.append((sx, sy))
            if len(screen_pts) >= 2:
                pygame.draw.lines(surf, col, False, screen_pts, 2)


def _draw_dual_axis_chart_card(surf, rect, title, left_labels, right_labels, curve_pts, atm_loss_val):
    T.card(surf, rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, rect.x + 14, rect.y + 10, title, C.CYAN_ELEC)

    plot = pygame.Rect(rect.x + 56, rect.y + 36, rect.w - 108, rect.h - 64)
    pygame.draw.rect(surf, (6, 11, 22), plot)
    pygame.draw.rect(surf, (18, 30, 52), plot, 1)

    # Left Y-axis (Pointing error µrad)
    for i, yl in enumerate(left_labels):
        ly = plot.y + int(plot.h * i / max(1, len(left_labels) - 1))
        T.text(surf, (plot.x - 8, ly - 6), yl, 10, C.TEXT_FAINT, anchor="tr")
        pygame.draw.line(surf, (12, 22, 38), (plot.x, ly), (plot.right, ly), 1)

    # Right Y-axis (ATM loss dB)
    for i, yl in enumerate(right_labels):
        ly = plot.y + int(plot.h * i / max(1, len(right_labels) - 1))
        T.text(surf, (plot.right + 8, ly - 6), yl, 10, C.PURPLE, anchor="tl")

    # Draw Yellow Oscillating Curve for Pointing Error
    if curve_pts:
        screen_pts = []
        for i, pe_val in curve_pts:
            sx = plot.x + int(plot.w * (i / max(1, len(curve_pts) - 1)))
            # Map 2 .. 8 µrad to height
            frac = (pe_val - 2.0) / 6.0
            sy = plot.bottom - int(plot.h * max(0.05, min(0.95, frac)))
            screen_pts.append((sx, sy))
        if len(screen_pts) >= 2:
            pygame.draw.lines(surf, C.AMBER, False, screen_pts, 2)

    # Draw Purple Dashed Line for Atmospheric Loss
    # Map 0.4 .. 1.6 dB
    atm_frac = (atm_loss_val - 0.4) / 1.2
    atm_y = plot.bottom - int(plot.h * max(0.1, min(0.9, atm_frac)))
    for dx in range(plot.x, plot.right, 8):
        pygame.draw.line(surf, C.PURPLE, (dx, atm_y), (dx + 4, atm_y), 2)

    # Bottom Legend (dynamically spaced to prevent collision)
    leg_y = rect.bottom - 22
    l1_text = "Pointing error (µrad) – left axis"
    tw1, _ = T.font(10, bold=True).size(l1_text)
    pygame.draw.line(surf, C.AMBER, (plot.x, leg_y + 6), (plot.x + 16, leg_y + 6), 2)
    T.text(surf, (plot.x + 22, leg_y), l1_text, 10, C.TEXT_FAINT, bold=True)

    l2_x = plot.x + 22 + tw1 + 24
    pygame.draw.line(surf, C.PURPLE, (l2_x, leg_y + 6), (l2_x + 16, leg_y + 6), 2)
    T.text(surf, (l2_x + 22, leg_y), "ATM loss (dB) – right axis", 10, C.PURPLE, bold=True)


# ---------------------------------------------------------------------------
# PAGE 3: SIMULATION (Figma Images 3 & 4)
# ---------------------------------------------------------------------------
class SimulationPageManager:
    """Manages sliders and layout for the Simulation & Link Budget page."""

    def __init__(self, rect):
        self.rect = pygame.Rect(rect)
        self.sliders = {}
        self.setup_sliders()

    def setup_sliders(self):
        w = self.rect.w
        left_w = int(w * 0.62)
        sx = self.rect.x + 20
        sw = left_w - 40

        # Transmitter & Link Parameters (p1_h = 356)
        # Title is at y0 + 12. First slider label at y_start - 30.
        y_start = self.rect.y + 66
        row_gap = 56
        self.sliders["tx_power"] = SimSlider((sx, y_start, sw, 10), "TX Optical Power", "Laser output power", 0.0, 40.0, 30.0, "dBm", "CTRL", "{:.1f}")
        self.sliders["wavelength"] = SimSlider((sx, y_start + row_gap, sw, 10), "Wavelength", "Operating wavelength", 800.0, 1600.0, 1550.0, "nm", "CTRL", "{:.0f}")
        self.sliders["distance"] = SimSlider((sx, y_start + row_gap * 2, sw, 10), "Link Distance", "Transmitter-receiver separation", 0.1, 50.0, 5.0, "km", "CTRL", "{:.1f}")
        self.sliders["data_rate"] = SimSlider((sx, y_start + row_gap * 3, sw, 10), "Data Rate", "Target channel throughput", 0.1, 100.0, 10.0, "Gbps", "CTRL", "{:.1f}")
        self.sliders["rx_sensitivity"] = SimSlider((sx, y_start + row_gap * 4, sw, 10), "RX Sensitivity", "Minimum detectable power", -70.0, -20.0, -50.0, "dBm", "CTRL", "{:.1f}")

        # Optical System Box
        p1_h = 356
        p2_y = self.rect.y + p1_h + 12
        y_opt = p2_y + 66
        self.sliders["beam_div"] = SimSlider((sx, y_opt, sw, 10), "Beam Divergence", "Half-angle beam spread", 0.1, 5.0, 1.5, "mrad", "CTRL", "{:.1f}")
        self.sliders["pointing_err"] = SimSlider((sx, y_opt + row_gap, sw, 10), "Pointing Error", "Static alignment offset", 0.0, 100.0, 5.0, "µrad", "CTRL", "{:.0f}")

        # Atmospheric Conditions Box
        p2_h = 160
        p3_y = p2_y + p2_h + 12
        y_atm = p3_y + 66
        self.sliders["visibility"] = SimSlider((sx, y_atm, sw, 10), "Atmospheric Visibility", "Meteorological optical range", 0.1, 50.0, 15.0, "km", "ENV", "{:.1f}")
        self.sliders["turbulence"] = SimSlider((sx, y_atm + row_gap, sw, 10), "Turbulence Strength (Cn²)", "Index of refraction structure", 0.01, 20.0, 2.00, "×10⁻¹⁵", "ENV", "{:.2f}")

    def apply_to_model(self, opt: OpticalLinkModel):
        opt.tx_power_dbm = self.sliders["tx_power"].value
        opt.wavelength_nm = self.sliders["wavelength"].value
        opt.distance_km = self.sliders["distance"].value
        opt.data_rate_gbps = self.sliders["data_rate"].value
        opt.rx_sensitivity_dbm = self.sliders["rx_sensitivity"].value
        opt.beam_divergence_mrad = self.sliders["beam_div"].value
        opt.visibility_km = self.sliders["visibility"].value
        opt.turbulence_cn2 = self.sliders["turbulence"].value * 1e-15

    def handle_mouse_down(self, pos):
        for s in self.sliders.values():
            if s.hit(pos):
                s.dragging = True
                s.drag_to(pos[0])
                return True
        return False

    def handle_mouse_up(self):
        for s in self.sliders.values():
            s.dragging = False

    def handle_mouse_move(self, pos, buttons):
        if buttons[0]:
            for s in self.sliders.values():
                if s.dragging:
                    s.drag_to(pos[0])
                    return True
        return False

    def draw(self, surf, opt: OpticalLinkModel, hist_pt: dict):
        x0, y0, w, h = self.rect.x, self.rect.y, self.rect.w, self.rect.h
        left_w = int(w * 0.62)
        right_x = x0 + left_w + 14
        right_w = w - left_w - 14

        # ── LEFT COLUMN ─────────────────────────────────────────────
        # Section 1: TRANSMITTER & LINK PARAMETERS Box
        p1_h = 356
        T.card(surf, (x0, y0, left_w, p1_h), fill=C.PANEL, border=C.BORDER)
        T.section_title(surf, x0 + 16, y0 + 12, "TRANSMITTER & LINK PARAMETERS", C.CYAN_ELEC)

        self.sliders["tx_power"].draw(surf)
        self.sliders["wavelength"].draw(surf)
        self.sliders["distance"].draw(surf)
        self.sliders["data_rate"].draw(surf)
        self.sliders["rx_sensitivity"].draw(surf)

        # Section 2: OPTICAL SYSTEM Box
        p2_y = y0 + p1_h + 12
        p2_h = 160
        T.card(surf, (x0, p2_y, left_w, p2_h), fill=C.PANEL, border=C.BORDER)
        T.section_title(surf, x0 + 16, p2_y + 12, "OPTICAL SYSTEM", C.CYAN_ELEC)
        self.sliders["beam_div"].draw(surf)
        self.sliders["pointing_err"].draw(surf)

        # Section 3: ATMOSPHERIC CONDITIONS Box
        p3_y = p2_y + p2_h + 12
        p3_h = 160
        T.card(surf, (x0, p3_y, left_w, p3_h), fill=C.PANEL, border=C.BORDER)
        T.section_title(surf, x0 + 16, p3_y + 12, "ATMOSPHERIC CONDITIONS", C.CYAN_ELEC)
        self.sliders["visibility"].draw(surf)
        self.sliders["turbulence"].draw(surf)

        # ── RIGHT COLUMN ────────────────────────────────────────────
        # 1. SYSTEM RESPONSE Readouts Card
        sr_h = 280
        T.card(surf, (right_x, y0, right_w, sr_h), fill=C.PANEL, border=C.BORDER)
        T.section_title(surf, right_x + 14, y0 + 12, "SYSTEM RESPONSE", C.CYAN_ELEC)

        sys_resp = [
            ("RX Optical Power", f"{hist_pt.get('rx_power', -11.62):.2f} dBm"),
            ("Bit Error Rate", hist_pt.get("ber_str", "1.00e-15")),
            ("Signal-to-Noise Ratio", f"{hist_pt.get('snr', 73.38):.2f} dB"),
            ("Link Margin", f"{hist_pt.get('link_margin', 38.38):.2f} dB"),
            ("Atmospheric Loss", f"{hist_pt.get('atm_loss', 1.47):.2f} dB"),
            ("Geometric Loss", f"{hist_pt.get('geo_loss', 40.00):.2f} dB"),
            ("Pointing Loss", f"{hist_pt.get('ptg_loss', 0.00):.2f} dB"),
            ("Total Optical Loss", f"{hist_pt.get('total_loss', 41.47):.2f} dB"),
        ]
        sr_y = y0 + 40
        for s_lbl, s_v in sys_resp:
            T.text(surf, (right_x + 16, sr_y), s_lbl, 11, C.TEXT_FAINT)
            T.text(surf, (right_x + right_w - 16, sr_y), s_v, 12, C.CYAN_ELEC, bold=True, anchor="tr")
            sr_y += 28

        # 2. LINK BUDGET BREAKDOWN (Horizontal Bars)
        lb_y = y0 + sr_h + 12
        lb_h = 210
        T.card(surf, (right_x, lb_y, right_w, lb_h), fill=C.PANEL, border=C.BORDER)
        T.section_title(surf, right_x + 14, lb_y + 12, "LINK BUDGET BREAKDOWN", C.CYAN_ELEC)

        bars = [
            ("TX Power", f"{opt.tx_power_dbm:.1f} dBm", opt.tx_power_dbm / 40.0, C.CYAN_ELEC),
            ("ATM Loss", f"-{hist_pt.get('atm_loss', 1.5):.1f} dBm", hist_pt.get('atm_loss', 1.5) / 10.0, C.ORANGE),
            ("Geo Loss", f"-{hist_pt.get('geo_loss', 40.0):.1f} dBm", hist_pt.get('geo_loss', 40.0) / 60.0, C.PURPLE),
            ("Pointing Loss", f"-{hist_pt.get('ptg_loss', 0.0):.1f} dBm", max(0.05, hist_pt.get('ptg_loss', 0.0) / 10.0), (236, 72, 153)),
            ("RX Power", f"{hist_pt.get('rx_power', -11.6):.1f} dBm", max(0.05, (hist_pt.get('rx_power', -11.6) + 50.0) / 50.0), C.TEAL),
        ]
        by = lb_y + 46
        bar_w = right_w - 32
        for b_lbl, b_val_str, b_frac, b_col in bars:
            T.text(surf, (right_x + 16, by - 14), b_lbl, 11, C.TEXT_FAINT)
            T.text(surf, (right_x + right_w - 16, by - 14), b_val_str, 11, C.TEXT, bold=True, anchor="tr")
            # Bar track
            pygame.draw.rect(surf, (14, 22, 38), (right_x + 16, by, bar_w, 6), border_radius=2)
            # Bar fill
            fw = int(round(bar_w * max(0.02, min(1.0, b_frac))))
            pygame.draw.rect(surf, b_col, (right_x + 16, by, fw, 6), border_radius=2)
            by += 32

        # 3. CAUSE — EFFECT Card
        ce_y = lb_y + lb_h + 12
        ce_h = 140
        T.card(surf, (right_x, ce_y, right_w, ce_h), fill=C.PANEL, border=C.BORDER)
        T.section_title(surf, right_x + 14, ce_y + 12, "CAUSE — EFFECT", C.CYAN_ELEC)

        explanation = (
            "Adjust TX Power, Distance, or Visibility to observe immediate "
            "changes in RX Power, BER, and Link Margin. Higher turbulence "
            "increases fading, while pointing offset degrades optical flux."
        )
        words = explanation.split(" ")
        lines = []
        cur_line = ""
        for w_word in words:
            test_line = cur_line + (" " if cur_line else "") + w_word
            if len(test_line) > 38:
                lines.append(cur_line)
                cur_line = w_word
            else:
                cur_line = test_line
        if cur_line:
            lines.append(cur_line)

        ey = ce_y + 40
        for line_str in lines:
            T.text(surf, (right_x + 16, ey), line_str, 11, C.TEXT_DIM)
            ey += 22


# ---------------------------------------------------------------------------
# PAGE 4: FALSE LOCK (Figma Image 5)
# ---------------------------------------------------------------------------
def render_false_lock_page(surf, rect, sim, perf, opt: OpticalLinkModel, hist_pt: dict):
    """
    Renders False Lock validation page matching Figma Image 5:
    - Top Banner: LOCK VALID with checkmark & timestamp
    - Left Column:
      * LOCK CONFIDENCE METRICS (3 Arc Gauges: 94%, 95%, 100%)
      * DETECTION ALGORITHM list
    - Right Column:
      * LOCK VALIDATION CRITERIA (5 PASS verification rows with thresholds)
      * FALSE LOCK SIGNATURES
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h

    # 1. Top Banner: LOCK VALID Notification
    ban_h = 62
    T.card(surf, (x0, y0, w, ban_h), fill=(4, 24, 22), border=(0, 180, 110), radius=4)

    # Checkmark icon
    pygame.draw.circle(surf, C.GREEN, (x0 + 34, y0 + ban_h // 2), 16, 2)
    pygame.draw.line(surf, C.GREEN, (x0 + 27, y0 + ban_h // 2), (x0 + 32, y0 + ban_h // 2 + 6), 2)
    pygame.draw.line(surf, C.GREEN, (x0 + 32, y0 + ban_h // 2 + 6), (x0 + 42, y0 + ban_h // 2 - 5), 2)

    # Title & Subtitle
    T.text(surf, (x0 + 64, y0 + 12), "LOCK VALID", 15, C.GREEN, bold=True)
    sub = "All lock validation criteria satisfied. Carrier acquisition confirmed with acceptable BER, SNR, and alignment confidence."
    T.text(surf, (x0 + 64, y0 + 34), sub, 11, C.TEXT_DIM)

    # UTC Timestamp right
    ts_str = time.strftime("%Y-%m-%dT%H:%M:%S UTC", time.gmtime())
    T.text(surf, (x0 + w - 16, y0 + 24), ts_str, 11, C.TEXT_FAINT, anchor="tr")

    # 2. Main Content: Left Column (44% width) & Right Column (56% width)
    main_y = y0 + ban_h + 14
    main_h = h - ban_h - 18
    left_w = int(w * 0.44)
    right_x = x0 + left_w + 14
    right_w = w - left_w - 14

    # ── LEFT CARD 1: LOCK CONFIDENCE METRICS ───────────────────────
    card1_h = max(260, int(main_h * 0.52))
    T.card(surf, (x0, main_y, left_w, card1_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 16, main_y + 12, "LOCK CONFIDENCE METRICS", C.CYAN_ELEC)

    # 3 Circular Arc Gauges
    gauge_y = main_y + card1_h // 2 - 12
    gauge_gap = left_w // 3
    g_cx1 = x0 + gauge_gap // 2
    g_cx2 = x0 + gauge_gap + gauge_gap // 2
    g_cx3 = x0 + gauge_gap * 2 + gauge_gap // 2

    # Draw Gauges
    T.draw_circular_arc_gauge(surf, g_cx1, gauge_y, 36, 94.0, C.CYAN_ELEC, "OVERALL LOCK", stroke=5)
    T.draw_circular_arc_gauge(surf, g_cx2, gauge_y, 36, 95.0, C.CYAN_ELEC, "ALIGNMENT", stroke=5)
    T.draw_circular_arc_gauge(surf, g_cx3, gauge_y, 36, 100.0, C.CYAN_ELEC, "CONSISTENCY", stroke=5)

    # Explanatory text below gauges
    exp_txt = "Lock validated against BER, SNR, alignment deviation, and tracking stability thresholds"
    T.text(surf, (x0 + left_w // 2, main_y + card1_h - 22), exp_txt, 10, C.TEXT_FAINT, anchor="tc")

    # Card 2 (Bottom Left): DETECTION ALGORITHM
    card2_y = main_y + card1_h + 12
    card2_h = main_h - card1_h - 12
    T.card(surf, (x0, card2_y, left_w, card2_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 16, card2_y + 12, "DETECTION ALGORITHMS & THRESHOLDS", C.CYAN_ELEC)

    algos = [
        ("BER Threshold Gate", "Nominal lock gate: BER < 1.00e-06 with continuous parity checks", C.GREEN),
        ("Spatial Gating Filter", "Angular FOV boundary: error <= 30 µrad radius gate", C.GREEN),
        ("Temporal Correlation Engine", "Circularity > 0.85, temporal correlation index > 0.60", C.GREEN),
    ]
    ay = card2_y + 38
    for name, desc, col in algos:
        pygame.draw.circle(surf, col, (x0 + 20, ay + 6), 4)
        T.text(surf, (x0 + 32, ay), name, 11, col, bold=True)
        T.text(surf, (x0 + 32, ay + 17), desc, 10, C.TEXT_FAINT)
        ay += 44

    # ── RIGHT CARD 1: LOCK VALIDATION CRITERIA ─────────────────────
    rcard1_h = card1_h
    T.card(surf, (right_x, main_y, right_w, rcard1_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 16, main_y + 12, "LOCK VALIDATION CRITERIA", C.CYAN_ELEC)

    criteria = [
        ("PASS", "BER within valid-lock threshold", "High BER with apparent carrier lock indicates false acquisition", "1.00e-15", "thr: < 1e-6"),
        ("PASS", "SNR above minimum", "Low SNR with claimed lock suggests carrier false alarm", f"{hist_pt.get('snr', 73.4):.1f} dB", "thr: ≥ 8 dB"),
        ("PASS", "Alignment confidence sufficient", "Excessive pointing error invalidates lock confidence", f"{hist_pt.get('pointing_error_urad', 1.68):.2f} µrad", "thr: < 30 µrad"),
        ("PASS", "Tracking stability acceptable", "Unstable tracking with claimed lock is a false-lock indicator", f"{hist_pt.get('stability', 95.6):.1f} %", "thr: > 60 %"),
        ("PASS", "False-lock state not asserted", "Explicit false-lock detection from anomaly correlation engine", "CLEAR", "thr: CLEAR"),
    ]

    row_y = main_y + 36
    row_step = max(42, (rcard1_h - 48) // len(criteria))
    for status, c_title, c_desc, c_val, c_thr in criteria:
        pygame.draw.rect(surf, (0, 48, 28), (right_x + 16, row_y + 2, 44, 20), border_radius=2)
        T.text(surf, (right_x + 38, row_y + 4), status, 10, C.GREEN, bold=True, anchor="tc")

        T.text(surf, (right_x + 68, row_y), c_title, 11, C.TEXT, bold=True)
        T.text(surf, (right_x + 68, row_y + 17), c_desc, 10, C.TEXT_FAINT)

        T.text(surf, (right_x + right_w - 16, row_y), c_val, 11, C.GREEN, bold=True, anchor="tr")
        T.text(surf, (right_x + right_w - 16, row_y + 17), c_thr, 10, C.TEXT_FAINT, anchor="tr")

        pygame.draw.line(surf, (14, 22, 38), (right_x + 16, row_y + row_step - 2), (right_x + right_w - 16, row_y + row_step - 2), 1)
        row_y += row_step

    # Card 4 (Bottom Right): FALSE LOCK SIGNATURES
    rcard2_y = main_y + rcard1_h + 12
    rcard2_h = main_h - rcard1_h - 12
    T.card(surf, (right_x, rcard2_y, right_w, rcard2_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 16, rcard2_y + 12, "FALSE LOCK SIGNATURES & ANOMALIES", C.CYAN_ELEC)

    signatures = [
        ("TYPE I", "BER Mismatch Anomaly", "High optical SNR detected but bit stream produces uncorrectable frame errors", C.AMBER),
        ("TYPE II", "Specular Reflector Clutter", "Strong optical return without authentic carrier phase/polarization correlation", C.RED),
        ("TYPE III", "Unstable Centroid Wander", "High-frequency spot vibration exceeding gimbal bandwidth limits", C.PURPLE),
    ]
    sy = rcard2_y + 38
    for tag, title, desc, tag_col in signatures:
        pygame.draw.rect(surf, tuple(c // 6 for c in tag_col), (right_x + 16, sy, 58, 20), border_radius=2)
        pygame.draw.rect(surf, tag_col, (right_x + 16, sy, 58, 20), 1, border_radius=2)
        T.text(surf, (right_x + 45, sy + 3), tag, 9, tag_col, bold=True, anchor="tc")
        T.text(surf, (right_x + 82, sy), title, 11, C.TEXT, bold=True)
        T.text(surf, (right_x + 82, sy + 17), desc, 10, C.TEXT_FAINT)
        sy += 44


# ---------------------------------------------------------------------------
# PAGE 5: EVENT LOG
# ---------------------------------------------------------------------------
def render_event_log_page(surf, rect, sim, perf, opt: OpticalLinkModel, events_list):
    """
    Renders filterable Event Log and Diagnostics timeline.
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h

    T.card(surf, (x0, y0, w, h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 16, y0 + 14, "SYSTEM EVENT & DIAGNOSTIC LOG", C.CYAN_ELEC)

    # Subtitle (dynamically placed after section title)
    tw_title, _ = T.font(13, bold=True).size("SYSTEM EVENT & DIAGNOSTIC LOG")
    T.text(surf, (x0 + 16 + tw_title + 16, y0 + 14), "AUTONOMOUS PAT PIPELINE LOG · UTC TIMESTAMPED", 10, C.TEXT_FAINT)

    # Table Header
    th_y = y0 + 44
    pygame.draw.rect(surf, (14, 22, 40), (x0 + 16, th_y, w - 32, 28), border_radius=2)
    T.text(surf, (x0 + 26, th_y + 6), "TIME (UTC)", 11, C.TEXT_FAINT, bold=True)
    T.text(surf, (x0 + 150, th_y + 6), "SEVERITY", 11, C.TEXT_FAINT, bold=True)
    T.text(surf, (x0 + 260, th_y + 6), "SUBSYSTEM", 11, C.TEXT_FAINT, bold=True)
    T.text(surf, (x0 + 410, th_y + 6), "EVENT DETAILS & THRESHOLD CROSSING", 11, C.TEXT_FAINT, bold=True)

    # Rows
    row_y = th_y + 36
    for ev in events_list:
        if row_y > y0 + h - 26:
            break
        ts, level, subsys, msg = ev

        col_map = {
            "CRITICAL": (C.RED, (48, 8, 8)),
            "WARNING": (C.AMBER, (48, 32, 0)),
            "INFO": (C.GREEN, (0, 36, 18)),
        }
        text_col, bg_col = col_map.get(level, (C.TEXT_DIM, (16, 24, 38)))

        T.text(surf, (x0 + 26, row_y + 4), ts, 11, C.TEXT_FAINT)

        # Severity Badge
        pygame.draw.rect(surf, bg_col, (x0 + 148, row_y, 74, 22), border_radius=2)
        pygame.draw.rect(surf, text_col, (x0 + 148, row_y, 74, 22), 1, border_radius=2)
        T.text(surf, (x0 + 185, row_y + 3), level, 10, text_col, bold=True, anchor="tc")

        T.text(surf, (x0 + 260, row_y + 4), subsys, 11, C.TEXT_DIM, bold=True)
        T.text(surf, (x0 + 410, row_y + 4), msg, 11, C.TEXT)

        pygame.draw.line(surf, (14, 20, 34), (x0 + 16, row_y + 26), (x0 + w - 16, row_y + 26), 1)
        row_y += 32
