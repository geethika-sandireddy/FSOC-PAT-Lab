"""
core/kalman.py
--------------
Discrete-time Linear Kalman Filter for Line-of-Sight (LOS) angular tracking
in Mobile Free Space Optical Communication (FSOC) Terminals.

State vector:
    x = [azimuth_deg, elevation_deg, velocity_az_deg_s, velocity_el_deg_s]^T

Measurement vector:
    z = [measured_az_deg, measured_el_deg]^T

Features:
  - Variable sample time dt handling (variable FPS).
  - Discrete Continuous White Noise Acceleration (CWNA) process noise Q(dt).
  - Measurement noise R dynamically scaled by candidate SNR.
  - Mahalanobis distance innovation gating (chi-squared outlier rejection).
  - Numerically stable Joseph form covariance update:
      P = (I - K*H)*P*(I - K*H)^T + K*R*K^T
  - Systematic A/B comparison against Raw centroid and Exponential Moving Average (EMA).
"""

import math
from typing import Optional, Tuple, Dict, Any, List
import numpy as np


class KalmanFilter2D:
    """4-state Kalman Filter for 2D line-of-sight tracking."""

    def __init__(
        self,
        q_accel: float = 1.2,           # Spectral density of acceleration noise (deg/s^2)^2
        r_meas_base: float = 0.04,      # Base measurement standard deviation (deg)
        gate_threshold_chi2: float = 9.21,  # 99% confidence gate for 2-DOF (chi2(2, 0.99) = 9.21)
        init_pos_sigma: float = 0.5,    # Initial position uncertainty (deg)
        init_vel_sigma: float = 2.0,    # Initial velocity uncertainty (deg/s)
    ):
        self.q_accel = float(q_accel)
        self.r_meas_base = float(r_meas_base)
        self.gate_threshold_chi2 = float(gate_threshold_chi2)

        # State vector: [az, el, vel_az, vel_el]
        self.x = np.zeros(4, dtype=np.float64)

        # Error covariance matrix P (4x4)
        self.P = np.diag([
            init_pos_sigma ** 2,
            init_pos_sigma ** 2,
            init_vel_sigma ** 2,
            init_vel_sigma ** 2,
        ]).astype(np.float64)

        # Measurement matrix H (2x4)
        self.H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ], dtype=np.float64)

        self.initialized = False
        self.last_t: Optional[float] = None
        self.outlier_count = 0
        self.update_count = 0

        # Telemetry / diagnostics
        self.last_innovation = np.zeros(2, dtype=np.float64)
        self.last_mahalanobis_sq = 0.0
        self.last_gated = False

    def reset(self, az: float = 0.0, el: float = 0.0, vel_az: float = 0.0, vel_el: float = 0.0):
        """Reset state vector and reinitialize covariance."""
        self.x = np.array([az, el, vel_az, vel_el], dtype=np.float64)
        self.P = np.diag([0.05 ** 2, 0.05 ** 2, 1.0 ** 2, 1.0 ** 2]).astype(np.float64)
        self.initialized = True
        self.last_t = None
        self.outlier_count = 0
        self.update_count = 0
        self.last_innovation = np.zeros(2, dtype=np.float64)
        self.last_mahalanobis_sq = 0.0
        self.last_gated = False

    def _state_transition(self, dt: float) -> np.ndarray:
        """Constant-velocity state transition matrix F(dt)."""
        return np.array([
            [1.0, 0.0, dt,  0.0],
            [0.0, 1.0, 0.0, dt ],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

    def _process_noise(self, dt: float) -> np.ndarray:
        """Continuous White Noise Acceleration (CWNA) discrete Q(dt)."""
        dt2 = dt * dt
        dt3 = dt2 * dt
        q = self.q_accel
        q_pos = (dt3 / 3.0) * q
        q_pos_vel = (dt2 / 2.0) * q
        q_vel = dt * q

        return np.array([
            [q_pos,     0.0,       q_pos_vel, 0.0      ],
            [0.0,       q_pos,     0.0,       q_pos_vel],
            [q_pos_vel, 0.0,       q_vel,     0.0      ],
            [0.0,       q_pos_vel, 0.0,       q_vel    ],
        ], dtype=np.float64)

    def predict(self, dt: float) -> Tuple[float, float]:
        """Kalman time update (prediction) step."""
        if not self.initialized:
            return 0.0, 0.0

        dt = max(1e-4, float(dt))
        F = self._state_transition(dt)
        Q = self._process_noise(dt)

        # State extrapolation: x_pred = F * x
        self.x = F @ self.x

        # Covariance extrapolation: P_pred = F * P * F^T + Q
        self.P = F @ self.P @ F.T + Q

        return float(self.x[0]), float(self.x[1])

    def update(
        self,
        z_az: float,
        z_el: float,
        snr: float = 20.0,
        override_r: Optional[float] = None,
    ) -> Tuple[float, float, bool]:
        """Kalman measurement update with Mahalanobis gating.

        Returns: (est_az, est_el, accepted)
        """
        if not self.initialized:
            self.reset(z_az, z_el)
            return z_az, z_el, True

        z = np.array([z_az, z_el], dtype=np.float64)

        # Scale measurement noise dynamically by SNR: R_eff = R_base * (1 + 8 / (snr + 1))
        if override_r is not None:
            r_val = float(override_r)
        else:
            snr_clamped = max(1.0, float(snr))
            r_scale = 1.0 + 8.0 / snr_clamped
            r_val = (self.r_meas_base * r_scale) ** 2

        R = np.diag([r_val, r_val]).astype(np.float64)

        # Innovation (measurement residual): y = z - H * x
        y = z - self.H @ self.x
        self.last_innovation = y

        # Innovation covariance: S = H * P * H^T + R
        S = self.H @ self.P @ self.H.T + R
        det_S = S[0, 0] * S[1, 1] - S[0, 1] * S[1, 0]
        if det_S <= 1e-12:
            inv_S = np.diag([1.0 / max(1e-6, S[0, 0]), 1.0 / max(1e-6, S[1, 1])])
        else:
            inv_S = np.linalg.inv(S)

        # Mahalanobis gating: D_M^2 = y^T * inv(S) * y
        d_mahalanobis_sq = float(y.T @ inv_S @ y)
        self.last_mahalanobis_sq = d_mahalanobis_sq

        if d_mahalanobis_sq > self.gate_threshold_chi2:
            # Outlier rejected: skip measurement update, retain prediction
            self.outlier_count += 1
            self.last_gated = True
            return float(self.x[0]), float(self.x[1]), False

        self.last_gated = False

        # Optimal Kalman gain: K = P * H^T * inv(S)
        K = self.P @ self.H.T @ inv_S

        # State update: x = x + K * y
        self.x = self.x + K @ y

        # Joseph form covariance update: P = (I - K*H)*P*(I - K*H)^T + K*R*K^T
        I = np.eye(4, dtype=np.float64)
        IKH = I - K @ self.H
        self.P = IKH @ self.P @ IKH.T + K @ R @ K.T

        self.update_count += 1
        return float(self.x[0]), float(self.x[1]), True

    @property
    def est_az(self) -> float:
        return float(self.x[0])

    @property
    def est_el(self) -> float:
        return float(self.x[1])

    @property
    def vel_az(self) -> float:
        return float(self.x[2])

    @property
    def vel_el(self) -> float:
        return float(self.x[3])

    @property
    def sigma_pos(self) -> float:
        """Position standard deviation in degrees."""
        return float(math.sqrt(max(0.0, (self.P[0, 0] + self.P[1, 1]) / 2.0)))


def compare_raw_ema_kalman(
    t_span: Optional[np.ndarray] = None,
    true_az: Optional[np.ndarray] = None,
    true_el: Optional[np.ndarray] = None,
    n_samples: int = 200,
    dt: float = 1.0 / 60.0,
    noise_sigma_deg: float = 0.05,
    outlier_prob: float = 0.04,
    outlier_scale_deg: float = 0.8,
    seed: int = 42,
) -> Dict[str, Any]:
    """Empirical A/B/C comparison: Raw Centroid vs EMA vs Kalman Filter.

    Simulates realistic tracking on noisy moving targets with sensor noise
    and spurious glint/outlier spikes.
    """
    rng = np.random.RandomState(seed)
    if t_span is None or isinstance(t_span, int):
        n = int(t_span) if isinstance(t_span, int) else n_samples
        t_span = np.linspace(0.0, n * dt, n)
        true_az = 0.5 * np.sin(0.4 * t_span)
        true_el = 0.3 * np.cos(0.3 * t_span)
    else:
        n = len(t_span)

    # Generate noisy measurements
    meas_az = true_az + rng.normal(0.0, noise_sigma_deg, n)
    meas_el = true_el + rng.normal(0.0, noise_sigma_deg, n)

    # Inject spurious glint/outliers
    outlier_mask = rng.uniform(0.0, 1.0, n) < outlier_prob
    meas_az[outlier_mask] += rng.uniform(-outlier_scale_deg, outlier_scale_deg, np.sum(outlier_mask))
    meas_el[outlier_mask] += rng.uniform(-outlier_scale_deg, outlier_scale_deg, np.sum(outlier_mask))

    # 1. Raw Centroid (direct measurements)
    raw_az = meas_az.copy()
    raw_el = meas_el.copy()

    # 2. Exponential Moving Average (EMA) with alpha = 0.30
    alpha = 0.30
    ema_az = np.zeros(n)
    ema_el = np.zeros(n)
    ema_az[0] = meas_az[0]
    ema_el[0] = meas_el[0]
    for i in range(1, n):
        ema_az[i] = alpha * meas_az[i] + (1.0 - alpha) * ema_az[i - 1]
        ema_el[i] = alpha * meas_el[i] + (1.0 - alpha) * ema_el[i - 1]

    # 3. Kalman Filter
    kf = KalmanFilter2D(q_accel=1.5, r_meas_base=noise_sigma_deg, gate_threshold_chi2=9.21)
    kf.reset(meas_az[0], meas_el[0])
    kal_az = np.zeros(n)
    kal_el = np.zeros(n)
    kal_az[0] = meas_az[0]
    kal_el[0] = meas_el[0]

    for i in range(1, n):
        dt = t_span[i] - t_span[i - 1]
        kf.predict(dt)
        kf.update(meas_az[i], meas_el[i], snr=20.0)
        kal_az[i] = kf.est_az
        kal_el[i] = kf.est_el

    def compute_stats(est_az, est_el):
        err = np.hypot(est_az - true_az, est_el - true_el)
        return {
            "mean_deg": float(np.mean(err)),
            "median_deg": float(np.median(err)),
            "rmse_deg": float(np.sqrt(np.mean(err ** 2))),
            "p95_deg": float(np.percentile(err, 95)),
            "max_deg": float(np.max(err)),
        }

    raw_s = compute_stats(raw_az, raw_el)
    ema_s = compute_stats(ema_az, ema_el)
    kal_s = compute_stats(kal_az, kal_el)

    return {
        "n_samples": n,
        "outlier_count": int(np.sum(outlier_mask)),
        "raw": raw_s,
        "ema": ema_s,
        "kalman": kal_s,
        "rmse_raw": raw_s["rmse_deg"],
        "rmse_ema": ema_s["rmse_deg"],
        "rmse_kalman": kal_s["rmse_deg"],
        "glint_max_error_raw": raw_s["max_deg"],
        "glint_max_error_kalman": kal_s["max_deg"],
    }


# Class alias for nomenclature flexibility
PointingKalmanFilter = KalmanFilter2D
