"""
config.py -- Central configuration for the FSOC-PAT-Lab simulator (SIH 2026, PS 169).

Every tunable parameter of the virtual scene, camera, sensor, disturbances,
detection pipeline and control loop lives here in one place so that:

  * the whole system is *configurable* (a PS requirement: "configurable
    virtual environment"),
  * difficulty presets can be switched live (keys 1-5),
  * and the stress-test harness sweeps the same parameters headlessly.

All angular units are DEGREES unless explicitly stated.
"""

# ---------------------------------------------------------------------------
# Window / UI
# ---------------------------------------------------------------------------
LOGICAL_WIDTH = 1600
LOGICAL_HEIGHT = 900
WINDOW_DEFAULT_W = 1580
WINDOW_DEFAULT_H = 900
FPS = 60

# ---------------------------------------------------------------------------
# Virtual camera sensor (the "eye" of Satellite A)
# ---------------------------------------------------------------------------
CAM_VIEW_W = 800                     # sensor pixels (horizontal)
CAM_VIEW_H = 450                     # sensor pixels (vertical)
HFOV_DEG = 2.4                       # horizontal field of view in degrees
PIXELS_PER_DEG = CAM_VIEW_W / HFOV_DEG
VFOV_DEG = CAM_VIEW_H / PIXELS_PER_DEG

PRINCIPAL_U = CAM_VIEW_W / 2.0
PRINCIPAL_V = CAM_VIEW_H / 2.0
FOCAL_PX = (CAM_VIEW_W / 2.0) / __import__("math").tan(__import__("math").radians(HFOV_DEG / 2.0))

# ---------------------------------------------------------------------------
# World / orbital geometry
# ---------------------------------------------------------------------------
BEACON_ANGULAR_RADIUS_DEG = 0.030    # HWHM of the beacon core on the sensor
BEACON_GLOW_MULT = 3.2               # glow extends this many core radii
MODULATION_FREQ_HZ = 15.0            # beacon amplitude modulation (blinking)
MODULATION_BRIGHT = 252              # bright phase of the modulation
MODULATION_DIM = 118                 # dim phase (still detectable -> robust)

# Per-run randomized ambiguity: the system is GIVEN a coarse ephemeris
# prediction (this PS's central premise) with a bias that grows with time
# (models unmodeled atmospheric drag / prediction divergence).
EPHEMERIS_START_BIAS_DEG = 0.55
EPHEMERIS_GROWTH_DEG_PER_SEC = 0.012
EPHEMERIS_MAX_BIAS_DEG = 2.6

# ---------------------------------------------------------------------------
# Pan-tilt gimbal (actuator realism)
# ---------------------------------------------------------------------------
GIMBAL_MAX_SLEW_DEG_S = 10.0          # max allowable slew velocity (deg/s)
GIMBAL_MAX_TILT_DEG_S = 8.0
GIMBAL_ACCEL_DEG_S2 = 14.0            # acceleration limit (inertia)
GIMBAL_SERVO_KP = 25.0                # position gain  [1/s^2]
GIMBAL_SERVO_KD = 10.0                # velocity damping [1/s]  (= 2*sqrt(kp))
GIMBAL_LATENCY_FRAMES = 2            # measurement->command response delay
GIMBAL_STABIZATION_REJECT = 0.80     # inner-loop disturbance rejection (0-1)

# ---------------------------------------------------------------------------
# Detection (Block D - front end)
# ---------------------------------------------------------------------------
TOP_HAT_RADIUS = 13                  # local-background estimation kernel
DETECTION_ABS_THRESHOLD = 42         # signal above local background (grey levels)
DETECTION_MIN_BLOB_AREA = 5          # px^2
EXPECTED_BEACON_HUE = 8              # HSV hue (OpenCV 0-180) of the beacon core

# ---------------------------------------------------------------------------
# Estimation / tracking state machine
# ---------------------------------------------------------------------------
ACQUIRE_CONFIRM_FRAMES = 3           # temporal confirmation before lock
ACQUIRE_CONSISTENCY_PX = 14
COAST_TIMEOUT_S = 0.45               # lost frames before entering SEARCH
ASSOC_GATE_DEG = 0.30                # candidate->track association gate
MOD_CORREL_WIN = 18                  # frames of intensity history for modulation ID
MOD_LOCK_THRESHOLD = 0.62            # correlation for beacon-lock commit (true:~0.95, decoy:<0.55)
MOD_SUSPECT_FLOOR = 0.58             # locked object below this modulation corr for
MOD_SUSPECT_DROP_FRAMES = 30         # ... this many frames -> false-lock drop to search
ML_LOCK_THRESHOLD = 0.55             # appearance-classifier threshold
FUSION_WEIGHT_MOD = 0.55             # fusion: modulation score weight
FUSION_WEIGHT_ML = 0.45              # fusion: appearance score weight
SEARCH_GROWTH_DEG_S = 0.55           # spiral search speed (deg/s)
SEARCH_MAX_RADIUS_DEG = 3.2
ESTIMATOR_ALPHA = 0.35               # bias-tracking filter gain (lower = smoother)

# ---------------------------------------------------------------------------
# Disturbance engine (each 0-100, independently controllable)
# ---------------------------------------------------------------------------
TURBULENCE_MAX_PX = 9.0              # max warp displacement at 100%
TURBULENCE_BLUR_MAX = 1.4            # gaussian blur sigma at 100%
SENSOR_NOISE_MAX_SIGMA = 22.0        # additive gaussian sigma at 100%
SENSOR_HOTPIXEL_MAX = 45             # hot pixels per frame at 100%
VIBRATION_MAX_DEG_S = 0.55           # random-walk drift rate at 100% (deg/s)
JERK_MAX_MAGNITUDE_DEG = 0.9         # max jerk step magnitude

# ---------------------------------------------------------------------------
# Scene content
# ---------------------------------------------------------------------------
NUM_STARS = 650
DISTRACTOR_SPAWN_RADIUS_DEG = 0.9    # decoys roam within this of the beacon path
OBSTACLE_SPEED_FRACTION = 0.5        # obstacle crossing speed relative to beacon

# ---------------------------------------------------------------------------
# Performance metric defaults
# ---------------------------------------------------------------------------
TARGET_MEAN_ERROR_DEG = 0.050        # what the report calls "excellent"
FINE_ACQUISITION_REGION_DEG = 0.100  # coarse stage must park the beacon inside this

# ---------------------------------------------------------------------------
# Difficulty presets (switched live with keys 1-5)
# ---------------------------------------------------------------------------
DIFFICULTY_PRESETS = {
    "EASY": dict(
        turbulence=5, vibration=2, sensor_noise=5, jerk_prob=0,
        distractors=0, obstacles=0,
        az_amp=1.00, el_amp=0.60, speed=1.0,
    ),
    "MODERATE": dict(
        turbulence=20, vibration=8, sensor_noise=10, jerk_prob=1,
        distractors=1, obstacles=1,
        az_amp=1.40, el_amp=0.90, speed=1.15,
    ),
    "HARD": dict(
        turbulence=40, vibration=18, sensor_noise=18, jerk_prob=3,
        distractors=2, obstacles=2,
        az_amp=1.80, el_amp=1.10, speed=1.35,
    ),
    "SEVERE": dict(
        turbulence=65, vibration=32, sensor_noise=28, jerk_prob=6,
        distractors=4, obstacles=3,
        az_amp=2.20, el_amp=1.30, speed=1.65,
    ),
    "ADVERSARIAL": dict(
        turbulence=85, vibration=45, sensor_noise=38, jerk_prob=9,
        distractors=4, obstacles=4,
        az_amp=2.60, el_amp=1.60, speed=2.00,
    ),
}

PRESET_ORDER = ["EASY", "MODERATE", "HARD", "SEVERE", "ADVERSARIAL"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "logs"
RESULTS_DIR = "logs"
SIM_DURATION_S = 120                 # default run length for the timed demo