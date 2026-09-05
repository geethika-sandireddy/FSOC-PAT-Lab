"""
config.py -- Central configuration for the FSOC-PAT-Lab simulator (SIH 2026, PS 26169).

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
# PS 26169 - Virtual Environment Parameters (user-configurable)
# ---------------------------------------------------------------------------
SCREEN_SIZE_W = 2000                   # PS: min 2000x2000, user-defined
SCREEN_SIZE_H = 2000
CAMERA_RESOLUTION_W = 640              # PS default: 640x480
CAMERA_RESOLUTION_H = 480
CAMERA_FOV_H_DEG = 4.0                 # PS default: 4° x 3°
CAMERA_FOV_V_DEG = 3.0
CAMERA_UPDATE_HZ = 60                  # PS min: 30 Hz
CAMERA_TYPE = "MONOCHROME"             # PS: Monochrome (optional: Colour)

# Target parameters (PS 26169)
TARGET_SHAPE = "SQUARE"                # PS default: Square (optional: Circle, Spot)
TARGET_SIZE_PX = 10                    # PS default: 10x10 pixels
TARGET_SIZE_PY = 10
TARGET_INITIAL = "RANDOM"              # PS default: Random (optional: Center)
NUM_TARGETS = 1                        # PS: 1 mandatory, multiple optional
MAX_TARGETS = 5                        # optional: up to 5

# Camera motion constraints (PS 26169)
CAMERA_MAX_PAN_DEG_S = 5.0            # PS default: 5 °/s (range 5-10)
CAMERA_MAX_TILT_DEG_S = 5.0           # PS default: 5 °/s (range 5-10)

# ---------------------------------------------------------------------------
# Virtual camera sensor (the "eye" of the terminal)
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
EPHEMERIS_START_BIAS_DEG = 0.60
EPHEMERIS_GROWTH_DEG_PER_SEC = 0.030
EPHEMERIS_MAX_BIAS_DEG = 3.0

# ---------------------------------------------------------------------------
# Pan-tilt gimbal (actuator realism)
# ---------------------------------------------------------------------------
GIMBAL_MAX_SLEW_DEG_S = 5.0           # PS 26169 default 5 deg/s
GIMBAL_MAX_TILT_DEG_S = 5.0
GIMBAL_ACCEL_DEG_S2 = 18.0            # acceleration limit (inertia)
GIMBAL_SERVO_KP = 32.0                # position gain  [1/s^2]
GIMBAL_SERVO_KI = 0.80                # integral gain (eliminates steady-state err)
GIMBAL_SERVO_KD = 16.0                # velocity damping [1/s]  (critically damped)
GIMBAL_SERVO_INT_MAX = 0.15           # integral anti-windup clamp (deg)
GIMBAL_LATENCY_FRAMES = 2            # measurement->command response delay
GIMBAL_STABIZATION_REJECT = 0.92     # inner-loop disturbance rejection (0-1)

# ---------------------------------------------------------------------------
# Detection (Block D - front end)
# ---------------------------------------------------------------------------
TOP_HAT_RADIUS = 13                  # local-background estimation kernel
DETECTION_ABS_THRESHOLD = 20         # signal above local background (grey levels) - lower for fade robustness
DETECTION_MIN_BLOB_AREA = 2          # px^2 - smaller for faded beacon core
EXPECTED_BEACON_HUE = 8              # HSV hue (OpenCV 0-180) of the beacon core

# ---------------------------------------------------------------------------
# Estimation / tracking state machine
# ---------------------------------------------------------------------------
ACQUIRE_CONFIRM_FRAMES = 3           # temporal confirmation before lock
ACQUIRE_CONSISTENCY_PX = 22          # px tolerance during spatial consistency check
COAST_TIMEOUT_S = 1.10               # lost frames before entering SEARCH - longer for obstacles
ASSOC_GATE_DEG = 0.55                # candidate->track association gate - wider to survive turbulence fragmenting
MOD_CORREL_WIN = 26                  # frames of intensity history - longer window = more robust
MOD_LOCK_THRESHOLD = 0.64            # correlation for beacon-lock commit (true:~0.95, decoy:<0.55)
MOD_SUSPECT_FLOOR = 0.56             # locked object below this modulation corr for
MOD_SUSPECT_DROP_FRAMES = 4         # ... this many frames -> false-lock drop to search (must be <5 to beat the metric threshold)
ML_LOCK_THRESHOLD = 0.20           # appearance-classifier threshold - lower for fade robustness
FUSION_WEIGHT_MOD = 0.65             # fusion: modulation score weight
FUSION_WEIGHT_ML = 0.15              # fusion: appearance score weight
FUSION_WEIGHT_PRIOR = 0.20           # fusion: ephemeris prior weight
SEARCH_MIN_RAW_MOD = 0.20            # minimum RAW mod correlation for SEARCHING candidate filter (must be robust with few samples)
SEARCH_GROWTH_DEG_S = 1.25           # spiral search speed (deg/s) - faster acquisition
SEARCH_MAX_RADIUS_DEG = 4.5
ESTIMATOR_ALPHA = 0.42               # bias-tracking filter gain - faster lock-on
ESTIMATOR_GAMMA = 0.08               # velocity-feedforward gain (predictive)

# ---------------------------------------------------------------------------
# Disturbance engine (each 0-100, independently controllable)
#
# Each dial maps LINEARLY to a physically meaningful maximum, so the slider
# value means something a PAT engineer can reason about (see table below).
# ---------------------------------------------------------------------------
TURBULENCE_MAX_PX = 9.0              # 100% -> ~9 px RMS image warp displacement
TURBULENCE_BLUR_MAX = 1.4            # .. + gaussian blur sigma (px)
SENSOR_NOISE_MAX_SIGMA = 22.0        # 100% -> additive Gaussian sigma = 22 DN
SENSOR_HOTPIXEL_MAX = 45             # .. + hot white pixels per frame
VIBRATION_MAX_DEG_S = 0.55           # 100% -> platform LOS random-walk drift deg/s
JERK_MAX_MAGNITUDE_DEG = 0.9         # .. -> jerk step magnitude up to 0.9 deg
JERK_PROB = 9.0                      # 100% -> jerk probability / 1000 frames
BEACON_FADE_MAX = 0.85               # 100% -> beacon RMS intensity drops to ~15%

# Human-readable units for the GUI sliders (what "5" means for each dial).
DISTURBANCE_UNITS = {
    "turbulence":   ("TURBULENCE",   "px RMS warp / blur"),
    "vibration":    ("VIBRATION",    "deg/s LOS drift"),
    "sensor_noise": ("SENSOR NOISE", "sigma DN + hot px"),
    "jerk_prob":    ("JERK PROB",    "jerk % per 1000 fr"),
    "beacon_fade":  ("BEACON FADE",  "% RMS intensity drop"),
}

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
        beacon_fade=0, distractors=0, obstacles=0,
        az_amp=1.00, el_amp=0.60, speed=1.0,
        noise_types=["gaussian"],
        motion_type="straight_line",
    ),
    "MODERATE": dict(
        turbulence=20, vibration=8, sensor_noise=10, jerk_prob=1,
        beacon_fade=10, distractors=1, obstacles=1,
        az_amp=1.40, el_amp=0.90, speed=1.15,
        noise_types=["gaussian", "salt_pepper"],
        motion_type="figure_eight",
    ),
    "HARD": dict(
        turbulence=40, vibration=18, sensor_noise=18, jerk_prob=3,
        beacon_fade=30, distractors=2, obstacles=2,
        az_amp=1.80, el_amp=1.10, speed=1.35,
        noise_types=["gaussian", "poisson"],
        motion_type="circular",
    ),
    "SEVERE": dict(
        turbulence=65, vibration=32, sensor_noise=28, jerk_prob=6,
        beacon_fade=45, distractors=4, obstacles=3,
        az_amp=2.20, el_amp=1.30, speed=1.65,
        noise_types=["gaussian", "salt_pepper", "poisson"],
        motion_type="random",
    ),
    "ADVERSARIAL": dict(
        turbulence=85, vibration=45, sensor_noise=38, jerk_prob=9,
        beacon_fade=60, distractors=4, obstacles=4,
        az_amp=2.60, el_amp=1.60, speed=2.00,
        noise_types=["gaussian", "salt_pepper", "poisson"],
        motion_type="figure_eight",
    ),
}

PRESET_ORDER = ["EASY", "MODERATE", "HARD", "SEVERE", "ADVERSARIAL"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "logs"
RESULTS_DIR = "logs"
SIM_DURATION_S = 120                 # default run length for the timed demo