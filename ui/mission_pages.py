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

    def update_from_sim(self, sim_result, stress_mgr=None):
        """Synchronize real-time simulator measurements and inject stress test faults."""
        t = sim_result.get("t", 0.0)
        ptg_deg = sim_result.get("pointing_err_deg", 0.001)
        # Convert degrees to microradians (1 deg = 17453.3 µrad)
        live_ptg_urad = max(0.5, ptg_deg * 17453.3)
        # Smooth with previous
        self.pointing_error_urad = round(0.85 * self.pointing_error_urad + 0.15 * live_ptg_urad, 2)

        conf = sim_result.get("confidence", 0.95)
        state = sim_result.get("state", "ESTABLISHED" if sim_result.get("state") == "LOCKED" else sim_result.get("state", "ESTABLISHED"))

        # Apply stress test beam misalignment if active
        if stress_mgr and stress_mgr.scenarios["beam_mis"]["active"]:
            self.pointing_error_urad = round(self.pointing_error_urad + 42.0 * stress_mgr.scenarios["beam_mis"]["level"], 2)

        # Atmospheric loss based on visibility (Kim / Kruse model)
        q = 1.6 if self.visibility_km > 50 else (1.3 if self.visibility_km > 6 else 0.585 * (self.visibility_km ** (1/3)))
        beta = (3.91 / max(0.1, self.visibility_km)) * ((self.wavelength_nm / 550.0) ** (-q))
        atm_loss = round(beta * self.distance_km, 2)

        # Apply stress test atmospheric degradation if active
        if stress_mgr and stress_mgr.scenarios["atm_deg"]["active"]:
            atm_loss += round(18.5 * stress_mgr.scenarios["atm_deg"]["level"], 2)

        # Geometric loss (free-space divergence loss)
        geo_loss = round(20.0 * math.log10(max(1.0, self.distance_km * 1000.0 * (self.beam_divergence_mrad * 1e-3) / 0.1)), 1)
        geo_loss = max(10.0, min(65.0, geo_loss))

        # Pointing loss
        div_rad = max(1e-6, self.beam_divergence_mrad * 1e-3)
        err_rad = self.pointing_error_urad * 1e-6
        ptg_loss = round(min(45.0, 4.34 * ((2.0 * err_rad / div_rad) ** 2)), 2)

        total_loss = round(atm_loss + geo_loss + ptg_loss, 2)
        rx_power = round(max(-65.0, min(40.0, self.tx_power_dbm - total_loss)), 2)

        # Signal-to-Noise Ratio (dB)
        base_snr = 85.0 - total_loss * 0.8
        jitter = (math.sin(t * 1.5) * 0.4) + (math.cos(t * 3.7) * 0.2)
        snr = max(0.0, round(base_snr + jitter, 2))

        # Apply turbulence burst if active
        if stress_mgr and stress_mgr.scenarios["turb_burst"]["active"]:
            lvl = stress_mgr.scenarios["turb_burst"]["level"]
            scint = (math.sin(t * 14.0) * 5.2 + math.cos(t * 26.0) * 3.4) * lvl
            rx_power = round(rx_power + scint, 2)
            snr = max(2.0, round(snr + scint * 1.1, 2))

        # Apply signal interruption if active
        if stress_mgr and stress_mgr.scenarios["sig_intr"]["active"]:
            rx_power = -65.0
            snr = 1.8
            state = "SIGNAL LOSS"

        # Apply false lock condition if active
        if stress_mgr and stress_mgr.scenarios["false_lock"]["active"]:
            state = "FALSE LOCK"
        elif (stress_mgr and (stress_mgr.scenarios["atm_deg"]["active"] or stress_mgr.scenarios["beam_mis"]["active"])) and state != "SIGNAL LOSS":
            state = "DEGRADED"

        link_margin = round(rx_power - self.rx_sensitivity_dbm, 2)

        # Bit Error Rate (BER)
        if state == "SIGNAL LOSS":
            ber = 0.5
            ber_str = "0.50 (LOST)"
        elif state == "FALSE LOCK":
            ber = 1.2e-4
            ber_str = "1.20e-04"
        elif snr > 40.0:
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
        if state == "SIGNAL LOSS":
            stability = 0.0
        elif state == "FALSE LOCK":
            stability = 44.5
        elif stress_mgr and stress_mgr.scenarios["turb_burst"]["active"]:
            stability = min(99.9, max(40.0, round(conf * 72.0 + (math.cos(t * 12.0) * 8.0), 1)))
        else:
            stability = min(99.9, max(50.0, round(conf * 98.0 + (math.cos(t * 2.0) * 0.8), 1)))

        # Propagation delay (tau = d / c)
        prop_delay_us = round((self.distance_km * 1000.0) / (3e8) * 1e6, 2)

        if stress_mgr:
            stress_mgr.record_rx_power(rx_power)

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

    def update_rect(self, rect):
        self.rect = pygame.Rect(rect)
        old_vals = {k: s.value for k, s in self.sliders.items()}
        self.setup_sliders()
        for k, v in old_vals.items():
            if k in self.sliders:
                self.sliders[k].value = v

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
# PAGE 4: STRESS TEST (Hardware-in-the-Loop Fault Injection & Verification)
# ---------------------------------------------------------------------------
class StressTestManager:
    """
    Manages the 5 interactive Stress Test Scenarios and Real-time Oscilloscope.
    Faithfully reproduces Screenshot 1 layout and behavior.
    """
    def __init__(self):
        self.scenarios = {
            "atm_deg": {
                "name": "Atmospheric Degradation",
                "severity": "WARNING",
                "desc": "Progressively increases atmospheric loss to simulate fog, haze, or precipitation. Loss increases until link margin is exhausted.",
                "tags": ["Increasing ATM loss", "Decreasing RX power", "Rising BER", "Potential link degradation"],
                "active": False,
                "timer": 0.0,
                "duration": 10.0,
                "level": 0.0,
                "button_rect": pygame.Rect(0, 0, 0, 0),
            },
            "beam_mis": {
                "name": "Beam Misalignment",
                "severity": "WARNING",
                "desc": "Introduces progressive pointing error simulating gimbal drift, vibration, or platform instability.",
                "tags": ["Increasing pointing error", "Higher pointing loss", "Reduced RX power", "Tracking deviation"],
                "active": False,
                "timer": 0.0,
                "duration": 10.0,
                "level": 0.0,
                "button_rect": pygame.Rect(0, 0, 0, 0),
            },
            "turb_burst": {
                "name": "Turbulence Burst",
                "severity": "WARNING",
                "desc": "Triggers high-frequency atmospheric turbulence causing rapid scintillation and beam wander.",
                "tags": ["Rapid power fluctuations", "BER spikes", "Tracking instability", "Potential link drop"],
                "active": False,
                "timer": 0.0,
                "duration": 10.0,
                "level": 0.0,
                "button_rect": pygame.Rect(0, 0, 0, 0),
            },
            "sig_intr": {
                "name": "Signal Interruption",
                "severity": "CRITICAL",
                "desc": "Periodic link blockage simulating cloud passage, bird strike, or transient obstruction.",
                "tags": ["Link loss events", "CRITICAL alerts", "SNR collapse", "BER saturation"],
                "active": False,
                "timer": 0.0,
                "duration": 8.0,
                "level": 0.0,
                "button_rect": pygame.Rect(0, 0, 0, 0),
            },
            "false_lock": {
                "name": "False Lock Condition",
                "severity": "CRITICAL",
                "desc": "Forces a false carrier lock state where the receiver believes acquisition has occurred but BER or alignment confidence fails validation.",
                "tags": ["Carrier false alarm", "BER mismatch", "Anomaly asserted", "Rejection loop"],
                "active": False,
                "timer": 0.0,
                "duration": 10.0,
                "level": 0.0,
                "button_rect": pygame.Rect(0, 0, 0, 0),
            },
        }
        self.demo_step = 0
        self.demo_rects = []
        self.rx_power_history = deque(maxlen=120)
        for _ in range(120):
            self.rx_power_history.append(-11.5)

    def trigger(self, key, events_list=None):
        if key in self.scenarios:
            sc = self.scenarios[key]
            sc["active"] = not sc["active"]
            if sc["active"]:
                sc["timer"] = sc["duration"]
                sc["level"] = 1.0
                if events_list is not None:
                    ts = time.strftime("%H:%M:%S UTC", time.gmtime())
                    sev = sc["severity"]
                    subsys = "FAULT-INJ"
                    msg = f"Stress scenario TRIGGERED: {sc['name']} active ({sc['duration']:.0f}s duration)"
                    events_list.insert(0, (ts, sev, subsys, msg))
            else:
                sc["timer"] = 0.0
                sc["level"] = 0.0
                if events_list is not None:
                    ts = time.strftime("%H:%M:%S UTC", time.gmtime())
                    events_list.insert(0, (ts, "INFO", "FAULT-INJ", f"Stress scenario CLEARED: {sc['name']} back to nominal"))

    def clear_all(self, events_list=None):
        any_active = any(sc["active"] for sc in self.scenarios.values())
        for sc in self.scenarios.values():
            sc["active"] = False
            sc["timer"] = 0.0
            sc["level"] = 0.0
        self.demo_step = 0
        if any_active and events_list is not None:
            ts = time.strftime("%H:%M:%S UTC", time.gmtime())
            events_list.insert(0, (ts, "INFO", "FAULT-INJ", "All stress scenarios CLEARED. System recovered to nominal state."))

    def run_demo_step(self, step_idx, events_list=None):
        self.demo_step = step_idx
        if step_idx == 1:
            self.clear_all(events_list)
        elif step_idx == 2:
            self.clear_all(events_list)
            self.trigger("atm_deg", events_list)
        elif step_idx == 3:
            self.clear_all(events_list)
            self.trigger("beam_mis", events_list)
            self.trigger("turb_burst", events_list)
        elif step_idx == 4:
            self.clear_all(events_list)
            self.trigger("false_lock", events_list)
        elif step_idx == 5:
            self.clear_all(events_list)

    def update(self, dt, opt: OpticalLinkModel, events_list=None):
        for key, sc in self.scenarios.items():
            if sc["active"]:
                sc["timer"] -= dt
                if sc["timer"] <= 0.0:
                    sc["active"] = False
                    sc["timer"] = 0.0
                    sc["level"] = 0.0
                    if events_list is not None:
                        ts = time.strftime("%H:%M:%S UTC", time.gmtime())
                        events_list.insert(0, (ts, "INFO", "FAULT-INJ", f"Stress scenario TIMEOUT: {sc['name']} auto-cleared"))

    def record_rx_power(self, val):
        self.rx_power_history.append(val)

    def handle_click(self, pos, events_list=None):
        for key, sc in self.scenarios.items():
            if sc["button_rect"].collidepoint(pos):
                self.trigger(key, events_list)
                return True
        for idx, r in enumerate(self.demo_rects):
            if r.collidepoint(pos):
                self.run_demo_step(idx + 1, events_list)
                return True
        return False


def render_stress_test_page(surf, rect, stress_mgr: StressTestManager, opt: OpticalLinkModel, hist_pt: dict):
    """
    Renders Stress Test Fault Injection & Validation console matching Screenshot 1:
    - Top header: STRESS SCENARIO CONTROL
    - Left column: 5 Stress Scenarios (Atmospheric Degradation, Beam Misalignment, Turbulence Burst, Signal Interruption, False Lock)
    - Right column: SYSTEM RESPONSE metrics, RX POWER — LIVE oscilloscope, DEMO SEQUENCE guide
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h

    hdr_h = 36
    hdr_rect = pygame.Rect(x0, y0, w, hdr_h)
    T.card(surf, hdr_rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 14, y0 + 10, "STRESS SCENARIO CONTROL", C.CYAN_ELEC)
    tw_hdr, _ = T.font(14, bold=True).size("STRESS SCENARIO CONTROL")
    T.text(surf, (x0 + 24 + tw_hdr + 24, y0 + 11), "DYNAMIC FAULT INJECTION · REAL-TIME SYSTEM VERIFICATION", 11, C.TEXT_FAINT)

    main_y = y0 + hdr_h + 10
    main_h = h - hdr_h - 10
    left_w = int(w * 0.71)
    right_x = x0 + left_w + 12
    right_w = w - left_w - 12

    # Left Column: 5 Scenario Cards
    keys = ["atm_deg", "beam_mis", "turb_burst", "sig_intr", "false_lock"]
    card_gap = 8
    card_h = (main_h - 4 * card_gap) // 5

    icons = {
        "atm_deg": "≈",
        "beam_mis": "⨁",
        "turb_burst": "≋",
        "sig_intr": "⊘",
        "false_lock": "⚠",
    }

    mouse_pos = pygame.mouse.get_pos()

    for i, key in enumerate(keys):
        sc = stress_mgr.scenarios[key]
        cy = main_y + i * (card_h + card_gap)
        c_rect = pygame.Rect(x0, cy, left_w, card_h)

        is_act = sc["active"]
        border_col = C.RED if (is_act and sc["severity"] == "CRITICAL") else (C.AMBER if is_act else C.BORDER)
        bg_col = (26, 12, 16) if (is_act and sc["severity"] == "CRITICAL") else ((28, 22, 10) if is_act else C.PANEL)

        T.card(surf, c_rect, fill=bg_col, border=border_col)

        if is_act:
            accent_col = C.RED if sc["severity"] == "CRITICAL" else C.AMBER
            pygame.draw.rect(surf, accent_col, (x0, cy, 4, card_h), border_top_left_radius=4, border_bottom_left_radius=4)

        top_y = cy + 10
        icon_str = icons.get(key, "•")
        icon_col = C.RED if sc["severity"] == "CRITICAL" else C.AMBER
        T.text(surf, (x0 + 16, top_y), icon_str, 15, icon_col, bold=True)

        T.text(surf, (x0 + 38, top_y), sc["name"], 13, C.TEXT, bold=True)
        tw_name, _ = T.font(13, bold=True).size(sc["name"])

        badge_w, badge_h = 76, 20
        badge_x = x0 + 38 + tw_name + 12
        badge_bg = (48, 12, 12) if sc["severity"] == "CRITICAL" else (48, 32, 8)
        badge_border = C.RED if sc["severity"] == "CRITICAL" else C.AMBER
        pygame.draw.rect(surf, badge_bg, (badge_x, top_y, badge_w, badge_h), border_radius=2)
        pygame.draw.rect(surf, badge_border, (badge_x, top_y, badge_w, badge_h), 1, border_radius=2)
        T.text(surf, (badge_x + badge_w // 2, top_y + 3), sc["severity"], 11, badge_border, bold=True, anchor="tc")

        # Right Trigger Button
        btn_w, btn_h = 100, 32
        btn_x = x0 + left_w - btn_w - 16
        btn_y = top_y - 2
        btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)
        sc["button_rect"] = btn_rect

        if is_act:
            btn_bg = (70, 20, 20) if sc["severity"] == "CRITICAL" else (70, 48, 12)
            btn_border = C.RED if sc["severity"] == "CRITICAL" else C.AMBER
            btn_lbl = f"ACTIVE {sc['timer']:.0f}s"
            btn_col = C.TEXT
        else:
            is_btn_hov = btn_rect.collidepoint(mouse_pos)
            btn_bg = (14, 30, 56) if is_btn_hov else (8, 18, 34)
            btn_border = C.CYAN_ELEC if is_btn_hov else (0, 140, 210)
            btn_lbl = "TRIGGER"
            btn_col = C.CYAN_ELEC

        pygame.draw.rect(surf, btn_bg, btn_rect, border_radius=3)
        pygame.draw.rect(surf, btn_border, btn_rect, 1, border_radius=3)
        T.text(surf, (btn_rect.centerx, btn_rect.centery), btn_lbl, 11, btn_col, bold=True, anchor="cc")

        # Middle Description
        desc_y = top_y + 28
        max_desc_w = left_w - btn_w - 60
        T.multiline_text(surf, (x0 + 16, desc_y), sc["desc"], max_desc_w, size=11, color=C.TEXT_DIM, line_spacing=3)

        # Bottom row: Tags pills
        tags_y = cy + card_h - 26
        tag_x = x0 + 16
        for tag in sc["tags"]:
            tw, th = T.font(11).size(tag)
            tag_rect = pygame.Rect(tag_x, tags_y, tw + 16, 20)
            if tag_rect.right < btn_x + btn_w:
                pygame.draw.rect(surf, (12, 18, 30), tag_rect, border_radius=3)
                pygame.draw.rect(surf, (22, 34, 54), tag_rect, 1, border_radius=3)
                T.text(surf, (tag_x + 8, tags_y + 3), tag, 11, C.TEXT_FAINT)
                tag_x += tw + 22

    # Right Column
    # Card 1: SYSTEM RESPONSE
    resp_h = 180
    resp_rect = pygame.Rect(right_x, main_y, right_w, resp_h)
    T.card(surf, resp_rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 14, main_y + 10, "SYSTEM RESPONSE", C.CYAN_ELEC)

    st = hist_pt.get("state", "ESTABLISHED")
    st_col = C.GREEN if st == "ESTABLISHED" else (C.AMBER if st == "DEGRADED" else C.RED)

    resp_metrics = [
        ("Link State", st, st_col),
        ("RX Power", f"{hist_pt.get('rx_power', -11.5):.1f} dBm", C.CYAN_ELEC),
        ("SNR", f"{hist_pt.get('snr', 73.5):.1f} dB", C.CYAN_ELEC),
        ("BER", hist_pt.get("ber_str", "1.00e-15"), C.GREEN if "15" in hist_pt.get("ber_str", "") or "12" in hist_pt.get("ber_str", "") else C.AMBER),
        ("Link Margin", f"{hist_pt.get('link_margin', 38.5):.1f} dB", C.CYAN_ELEC),
    ]

    ry = main_y + 36
    r_step = (resp_h - 44) // len(resp_metrics)
    for lbl, val, col in resp_metrics:
        T.text(surf, (right_x + 16, ry), lbl, 11, C.TEXT_FAINT)
        T.text(surf, (right_x + right_w - 16, ry), val, 12, col, bold=True, anchor="tr")
        ry += r_step

    # Card 2: RX POWER — LIVE (Oscilloscope Strip Chart)
    osc_y = main_y + resp_h + 10
    osc_h = 160
    osc_rect = pygame.Rect(right_x, osc_y, right_w, osc_h)
    T.card(surf, osc_rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 14, osc_y + 10, "RX POWER — LIVE", C.CYAN_ELEC)

    plot_r = pygame.Rect(right_x + 14, osc_y + 36, right_w - 28, osc_h - 48)
    pygame.draw.rect(surf, (6, 11, 22), plot_r, border_radius=2)
    pygame.draw.rect(surf, (20, 32, 54), plot_r, 1, border_radius=2)

    grid_levels = [(-10, C.BORDER), (-30, (14, 24, 40)), (-50, (60, 16, 20))]
    for g_val, g_col in grid_levels:
        gy = plot_r.bottom - int(plot_r.h * (g_val + 70.0) / 70.0)
        pygame.draw.line(surf, g_col, (plot_r.x, gy), (plot_r.right, gy), 1)
        T.text(surf, (plot_r.x + 4, gy - 12), f"{g_val}dBm", 11, C.TEXT_FAINT)

    sens_y = plot_r.bottom - int(plot_r.h * (-50.0 + 70.0) / 70.0)
    pygame.draw.line(surf, C.RED, (plot_r.x, sens_y), (plot_r.right, sens_y), 1)
    T.text(surf, (plot_r.right - 4, sens_y - 12), "RX SENSITIVITY (-50dBm)", 11, C.RED, anchor="tr")

    hist = list(stress_mgr.rx_power_history)
    if len(hist) >= 2:
        pts = []
        n = len(hist)
        for idx, p_val in enumerate(hist):
            px = plot_r.x + int(plot_r.w * idx / (n - 1))
            norm_val = max(0.0, min(1.0, (p_val + 70.0) / 70.0))
            py = plot_r.bottom - int(plot_r.h * norm_val)
            pts.append((px, py))
        wave_col = C.CYAN_ELEC if hist[-1] > -30.0 else (C.AMBER if hist[-1] > -50.0 else C.RED)
        pygame.draw.lines(surf, wave_col, False, pts, 2)
        pygame.draw.circle(surf, wave_col, pts[-1], 3)

    # Card 3: DEMO SEQUENCE
    demo_y = osc_y + osc_h + 10
    demo_h = main_h - (resp_h + 10 + osc_h + 10)
    demo_rect = pygame.Rect(right_x, demo_y, right_w, demo_h)
    T.card(surf, demo_rect, fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 14, demo_y + 10, "DEMO SEQUENCE", C.CYAN_ELEC)

    demo_steps = [
        ("1. Start with nominal state — show judge ESTABLISHED link", C.GREEN),
        ("2. Trigger Atmospheric Degradation — watch SNR fall", C.AMBER),
        ("3. Observe DEGRADED → alert sequence", C.AMBER),
        ("4. Trigger False Lock — demonstrate detection", C.RED),
        ("5. Clear stress — show system recovery", C.CYAN_ELEC),
    ]

    stress_mgr.demo_rects = []
    dy = demo_y + 36
    step_spacing = max(24, (demo_h - 46) // len(demo_steps))
    for s_idx, (s_txt, s_col) in enumerate(demo_steps):
        s_step_r = pygame.Rect(right_x + 10, dy, right_w - 20, max(22, step_spacing - 4))
        stress_mgr.demo_rects.append(s_step_r)
        is_step_hov = s_step_r.collidepoint(mouse_pos)
        if is_step_hov:
            pygame.draw.rect(surf, (16, 26, 44), s_step_r, border_radius=2)
        T.text(surf, (right_x + 14, dy + 2), s_txt, 11, s_col, bold=True)
        dy += step_spacing


# ---------------------------------------------------------------------------
# PAGE 5: FALSE LOCK (Figma Image 5 / Screenshot 3)
# ---------------------------------------------------------------------------
def render_false_lock_page(surf, rect, sim, perf, opt: OpticalLinkModel, hist_pt: dict):
    """
    Renders False Lock validation page matching Screenshot 3:
    - Top Banner: LOCK VALID (or FALSE LOCK ALERT) with checkmark/cross & timestamp
    - Left Column:
      * LOCK CONFIDENCE METRICS (3 Arc Gauges: 94%, 95%, 100%)
      * DETECTION ALGORITHM list (5 detection algorithm sub-cards)
    - Right Column:
      * LOCK VALIDATION CRITERIA (5 PASS/FAIL verification rows with thresholds)
      * FALSE LOCK SIGNATURES (3 signature anomaly sub-cards)
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h
    is_false_lock = (hist_pt.get("state") == "FALSE LOCK")

    # 1. Top Banner
    ban_h = 62
    ban_bg = (34, 10, 14) if is_false_lock else (4, 24, 22)
    ban_border = C.RED if is_false_lock else (0, 180, 110)
    T.card(surf, (x0, y0, w, ban_h), fill=ban_bg, border=ban_border, radius=4)

    if is_false_lock:
        pygame.draw.circle(surf, C.RED, (x0 + 34, y0 + ban_h // 2), 16, 2)
        T.text(surf, (x0 + 34, y0 + ban_h // 2), "!", 16, C.RED, bold=True, anchor="cc")
        T.text(surf, (x0 + 64, y0 + 12), "FALSE LOCK DETECTED", 15, C.RED, bold=True)
        sub = "Carrier false acquisition detected. Uncorrected bit errors exceed nominal threshold. Initiating auto-rejection."
        T.text(surf, (x0 + 64, y0 + 34), sub, 11, C.TEXT_DIM)
    else:
        pygame.draw.circle(surf, C.GREEN, (x0 + 34, y0 + ban_h // 2), 16, 2)
        pygame.draw.line(surf, C.GREEN, (x0 + 27, y0 + ban_h // 2), (x0 + 32, y0 + ban_h // 2 + 6), 2)
        pygame.draw.line(surf, C.GREEN, (x0 + 32, y0 + ban_h // 2 + 6), (x0 + 42, y0 + ban_h // 2 - 5), 2)
        T.text(surf, (x0 + 64, y0 + 12), "LOCK VALID", 15, C.GREEN, bold=True)
        sub = "All lock validation criteria satisfied. Carrier acquisition confirmed with acceptable BER, SNR, and alignment confidence."
        T.text(surf, (x0 + 64, y0 + 34), sub, 11, C.TEXT_DIM)

    # UTC Timestamp right
    ts_str = time.strftime("%Y-%m-%dT%H:%M:%S UTC", time.gmtime())
    T.text(surf, (x0 + w - 16, y0 + 24), ts_str, 11, C.TEXT_FAINT, anchor="tr")

    # 2. Main Content: Left Column (46% width) & Right Column (54% width)
    main_y = y0 + ban_h + 12
    main_h = h - ban_h - 16
    left_w = int(w * 0.46)
    right_x = x0 + left_w + 14
    right_w = w - left_w - 14

    # ── LEFT CARD 1: LOCK CONFIDENCE METRICS ───────────────────────
    card1_h = max(230, int(main_h * 0.46))
    T.card(surf, (x0, main_y, left_w, card1_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 16, main_y + 12, "LOCK CONFIDENCE METRICS", C.CYAN_ELEC)

    gauge_y = main_y + card1_h // 2 - 12
    gauge_gap = left_w // 3
    g_cx1 = x0 + gauge_gap // 2
    g_cx2 = x0 + gauge_gap + gauge_gap // 2
    g_cx3 = x0 + gauge_gap * 2 + gauge_gap // 2

    val_lock = 42.0 if is_false_lock else 94.0
    val_align = 48.0 if is_false_lock else 95.0
    val_cons = 35.0 if is_false_lock else 100.0
    col_lock = C.RED if is_false_lock else C.CYAN_ELEC

    T.draw_circular_arc_gauge(surf, g_cx1, gauge_y, 36, val_lock, col_lock, "OVERALL LOCK", stroke=5)
    T.draw_circular_arc_gauge(surf, g_cx2, gauge_y, 36, val_align, col_lock, "ALIGNMENT", stroke=5)
    T.draw_circular_arc_gauge(surf, g_cx3, gauge_y, 36, val_cons, col_lock, "CONSISTENCY", stroke=5)

    exp_txt = "Lock validated against BER, SNR, alignment deviation, and tracking stability thresholds"
    T.text(surf, (x0 + left_w // 2, main_y + card1_h - 22), exp_txt, 11, C.TEXT_FAINT, anchor="tc")

    # Card 2 (Bottom Left): DETECTION ALGORITHM (5 Cards matching Screenshot 3)
    card2_y = main_y + card1_h + 12
    card2_h = main_h - card1_h - 12
    T.card(surf, (x0, card2_y, left_w, card2_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, x0 + 16, card2_y + 12, "DETECTION ALGORITHM", C.CYAN_ELEC)

    algos = [
        ("BER Threshold Monitor", "Continuous BER measurement against acquisition validity window"),
        ("Alignment Confidence Engine", "Pointing error vs. beam divergence ratio analysis"),
        ("Signal Consistency Checker", "Power stability and carrier frequency validation"),
        ("Multi-parameter Correlation", "Cross-correlation of BER, SNR, pointing, and tracking metrics"),
        ("Anomaly State Machine", "State transition monitoring for false-lock pattern recognition"),
    ]

    ay = card2_y + 36
    sub_card_h = (card2_h - 48) // len(algos)
    for name, desc in algos:
        sc_r = pygame.Rect(x0 + 14, ay, left_w - 28, max(36, sub_card_h - 6))
        pygame.draw.rect(surf, (10, 18, 32), sc_r, border_radius=3)
        pygame.draw.rect(surf, (20, 32, 52), sc_r, 1, border_radius=3)

        pygame.draw.circle(surf, C.CYAN_ELEC, (sc_r.x + 14, sc_r.y + 14), 3)
        T.text(surf, (sc_r.x + 26, sc_r.y + 6), name, 11, C.TEXT, bold=True)
        T.text(surf, (sc_r.x + 26, sc_r.y + 22), desc, 11, C.TEXT_FAINT)
        ay += sub_card_h

    # ── RIGHT CARD 1: LOCK VALIDATION CRITERIA ─────────────────────
    rcard1_h = card1_h
    T.card(surf, (right_x, main_y, right_w, rcard1_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 16, main_y + 12, "LOCK VALIDATION CRITERIA", C.CYAN_ELEC)

    criteria = [
        ("FAIL" if is_false_lock else "PASS", "Alignment confidence sufficient", "Excessive pointing error invalidates lock confidence", f"{hist_pt.get('pointing_error_urad', 1.69):.2f} µrad", "thr: < 30 µrad"),
        ("FAIL" if is_false_lock else "PASS", "Tracking stability acceptable", "Unstable tracking with claimed lock is a false-lock indicator", f"{hist_pt.get('stability', 95.7):.1f} %", "thr: > 60 %"),
        ("FAIL" if is_false_lock else "PASS", "False-lock state not asserted", "Explicit false-lock detection from anomaly correlation engine", "ASSERTED" if is_false_lock else "CLEAR", "thr: CLEAR"),
        ("FAIL" if is_false_lock else "PASS", "BER within valid-lock threshold", "High BER with apparent carrier lock indicates false acquisition", hist_pt.get("ber_str", "1.00e-15"), "thr: < 1e-6"),
        ("PASS", "SNR above minimum", "Low SNR with claimed lock suggests carrier false alarm", f"{hist_pt.get('snr', 73.6):.1f} dB", "thr: ≥ 8 dB"),
    ]

    row_y = main_y + 36
    row_step = max(38, (rcard1_h - 46) // len(criteria))
    for status, c_title, c_desc, c_val, c_thr in criteria:
        stat_col = C.RED if status == "FAIL" else C.GREEN
        stat_bg = (48, 12, 12) if status == "FAIL" else (0, 48, 28)

        pygame.draw.rect(surf, stat_bg, (right_x + 14, row_y + 2, 48, 22), border_radius=2)
        T.text(surf, (right_x + 38, row_y + 5), status, 11, stat_col, bold=True, anchor="tc")

        T.text(surf, (right_x + 70, row_y), c_title, 11, C.TEXT, bold=True)
        T.text(surf, (right_x + 70, row_y + 18), c_desc, 11, C.TEXT_FAINT)

        T.text(surf, (right_x + right_w - 16, row_y), c_val, 11, stat_col, bold=True, anchor="tr")
        T.text(surf, (right_x + right_w - 16, row_y + 18), c_thr, 11, C.TEXT_FAINT, anchor="tr")

        pygame.draw.line(surf, (14, 22, 38), (right_x + 14, row_y + row_step - 2), (right_x + right_w - 16, row_y + row_step - 2), 1)
        row_y += row_step

    # Card 4 (Bottom Right): FALSE LOCK SIGNATURES (3 Cards matching Screenshot 3)
    rcard2_y = main_y + rcard1_h + 12
    rcard2_h = main_h - rcard1_h - 12
    T.card(surf, (right_x, rcard2_y, right_w, rcard2_h), fill=C.PANEL, border=C.BORDER)
    T.section_title(surf, right_x + 16, rcard2_y + 12, "FALSE LOCK SIGNATURES", C.CYAN_ELEC)

    signatures = [
        ("Type I: BER Mismatch", "BER exceeds 1e-6 threshold while carrier lock indicator is asserted. Indicates receiver ADC threshold misalignment or noise floor shift."),
        ("Type II: Alignment Confidence Failure", "Pointing error exceeds valid-lock envelope (30 µrad) while receiver claims tracking. Often caused by platform vibration or gimbal backlash."),
        ("Type III: Carrier Noise Lock", "High SNR-apparent acquisition with degraded BER indicates receiver locked to noise floor artifact rather than signal carrier."),
    ]

    sy = rcard2_y + 36
    sig_card_h = (rcard2_h - 48) // len(signatures)
    for title, desc in signatures:
        s_r = pygame.Rect(right_x + 14, sy, right_w - 28, max(46, sig_card_h - 8))
        pygame.draw.rect(surf, (10, 18, 32), s_r, border_radius=3)
        pygame.draw.rect(surf, (20, 32, 52), s_r, 1, border_radius=3)

        T.text(surf, (s_r.x + 16, s_r.y + 8), title, 12, C.TEXT, bold=True)
        T.multiline_text(surf, (s_r.x + 16, s_r.y + 26), desc, s_r.w - 32, size=11, color=C.TEXT_DIM, line_spacing=2)
        sy += sig_card_h


# ---------------------------------------------------------------------------
# PAGE 6: EVENT LOG (Filterable Log & Diagnostics matching Screenshot 2)
# ---------------------------------------------------------------------------
def render_event_log_page(surf, rect, sim, perf, opt: OpticalLinkModel, events_list):
    """
    Renders filterable Event Log and Diagnostics timeline matching Screenshot 2:
    - 4 KPI cards at top (TOTAL EVENTS, CRITICAL, WARNING, INFO)
    - Severity Legend banner (CRITICAL, WARNING, INFO)
    - Filterable event table with empty state or active event rows
    """
    x0, y0, w, h = rect.x, rect.y, rect.w, rect.h

    # 1. 4 KPI Cards at top
    kpi_h = 68
    kpi_gap = 12
    kpi_w = (w - 3 * kpi_gap) // 4

    tot_events = len(events_list)
    crit_events = sum(1 for e in events_list if e[1] == "CRITICAL")
    warn_events = sum(1 for e in events_list if e[1] == "WARNING")
    info_events = sum(1 for e in events_list if e[1] == "INFO")

    kpis = [
        ("TOTAL EVENTS", str(tot_events), C.CYAN_ELEC),
        ("CRITICAL", str(crit_events), C.RED),
        ("WARNING", str(warn_events), C.AMBER),
        ("INFO", str(info_events), C.CYAN_ELEC),
    ]

    for i, (lbl, val, col) in enumerate(kpis):
        kr = pygame.Rect(x0 + i * (kpi_w + kpi_gap), y0, kpi_w, kpi_h)
        T.card(surf, kr, fill=C.PANEL, border=C.BORDER)
        T.text(surf, (kr.x + 14, kr.y + 10), lbl, 11, C.TEXT_FAINT, bold=True)
        T.text(surf, (kr.x + 14, kr.y + 28), val, 24, col, bold=True)

    # 2. Status Legend Banner
    leg_y = y0 + kpi_h + 10
    leg_h = 34
    leg_rect = pygame.Rect(x0, leg_y, w, leg_h)
    T.card(surf, leg_rect, fill=C.PANEL, border=C.BORDER)

    leg_items = [
        (C.RED, "CRITICAL", "Immediate intervention required"),
        (C.AMBER, "WARNING", "Potential degradation — monitor"),
        (C.GREEN, "INFO", "Nominal operational information"),
    ]
    lx = x0 + 20
    for dot_col, title, desc in leg_items:
        pygame.draw.circle(surf, dot_col, (lx, leg_y + leg_h // 2), 4)
        lx += 12
        tw_t, _ = T.text(surf, (lx, leg_y + leg_h // 2 - 7), title, 11, dot_col, bold=True)
        lx += tw_t + 6
        tw_d, _ = T.text(surf, (lx, leg_y + leg_h // 2 - 7), f"— {desc}", 11, C.TEXT_FAINT)
        lx += tw_d + 32

    # 3. Main Event Log Table Card
    tbl_y = leg_y + leg_h + 10
    tbl_h = h - (kpi_h + 10 + leg_h + 10)
    tbl_rect = pygame.Rect(x0, tbl_y, w, tbl_h)
    T.card(surf, tbl_rect, fill=C.PANEL, border=C.BORDER)

    # Table Header
    th_y = tbl_y + 10
    pygame.draw.rect(surf, (14, 22, 40), (x0 + 12, th_y, w - 24, 30), border_radius=2)
    T.text(surf, (x0 + 24, th_y + 7), "LEVEL", 11, C.TEXT_FAINT, bold=True)
    T.text(surf, (x0 + 140, th_y + 7), "TIMESTAMP", 11, C.TEXT_FAINT, bold=True)
    T.text(surf, (x0 + 280, th_y + 7), "SUBSYSTEM", 11, C.TEXT_FAINT, bold=True)
    T.text(surf, (x0 + 420, th_y + 7), "EVENT DETAILS & THRESHOLD CROSSING", 11, C.TEXT_FAINT, bold=True)

    if tot_events == 0:
        center_y = tbl_y + tbl_h // 2
        center_x = x0 + w // 2
        pygame.draw.circle(surf, (20, 36, 54), (center_x, center_y - 20), 22, 2)
        pygame.draw.line(surf, (0, 180, 110), (center_x - 8, center_y - 20), (center_x - 2, center_y - 14), 2)
        pygame.draw.line(surf, (0, 180, 110), (center_x - 2, center_y - 14), (center_x + 8, center_y - 26), 2)
        T.text(surf, (center_x, center_y + 14), "NO ACTIVE EVENTS", 13, C.TEXT_DIM, bold=True, anchor="cc")
        T.text(surf, (center_x, center_y + 34), "All systems nominal", 11, C.TEXT_FAINT, anchor="cc")
    else:
        row_y = th_y + 38
        for ev in events_list:
            if row_y > tbl_y + tbl_h - 26:
                break
            ts, level, subsys, msg = ev

            col_map = {
                "CRITICAL": (C.RED, (48, 8, 8)),
                "WARNING": (C.AMBER, (48, 32, 0)),
                "INFO": (C.GREEN, (0, 36, 18)),
            }
            text_col, bg_col = col_map.get(level, (C.TEXT_DIM, (16, 24, 38)))

            pygame.draw.rect(surf, bg_col, (x0 + 24, row_y, 82, 22), border_radius=2)
            pygame.draw.rect(surf, text_col, (x0 + 24, row_y, 82, 22), 1, border_radius=2)
            T.text(surf, (x0 + 65, row_y + 3), level, 10, text_col, bold=True, anchor="tc")

            T.text(surf, (x0 + 140, row_y + 4), ts, 11, C.TEXT_FAINT)
            T.text(surf, (x0 + 280, row_y + 4), subsys, 11, C.TEXT_DIM, bold=True)

            max_msg_w = w - 440
            T.multiline_text(surf, (x0 + 420, row_y + 4), msg, max_msg_w, size=11, color=C.TEXT, line_spacing=2)

            pygame.draw.line(surf, (14, 20, 34), (x0 + 12, row_y + 26), (x0 + w - 12, row_y + 26), 1)
            row_y += 32
