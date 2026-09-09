"""
config.py -- Central configuration for the FSOC-PAT-Lab simulator (SIH 2026, PS 26169).

Every tunable parameter of the virtual scene, camera, sensor, disturbances,
# detection pipeline and control loop lives here in one place so that:

#   * the whole system is *configurable* (a PS requirement: "configurable
#     virtual environment"),
#   * difficulty presets can be switched live (keys 1-5),
#   * and the stress-test harness sweeps the same parameters headlessly.

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
# PS 26169 - Virtual Environment Parameters
#
# The PS's virtual "screen" is a 2000x2000 canvas the virtual camera pans
# across (initial camera position = centre of the screen).  The camera is
# 640x480 @ 4x3 deg (PS defaults), so PIXELS_PER_DEG = 160 -> the 10 px
# tracking-error spec ~ 0.0625 deg.  Both dials below are the SINGLE source
# of truth; CAM_VIEW_* / HFOV_* / FOCAL_PX derive from them.
# ---------------------------------------------------------------------------
SCREEN_SIZE_W = 2000                   # PS: min 2000x2000, user-defined
SCREEN_SIZE_H = 2000
SCREEN_CANVAS_CX = SCREEN_SIZE_W / 2.0 # virtual-screen centre == initial
SCREEN_CANVAS_CY = SCREEN_SIZE_H / 2.0 # camera position ("centre of the screen")
CAMERA_RESOLUTION_W = 640              # PS default 640x480
CAMERA_RESOLUTION_H = 480
CAMERA_FOV_H_DEG = 4.0                 # PS default: 4 deg x 3 deg
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
CAM_VIEW_W = CAMERA_RESOLUTION_W      # sensor pixels (horizontal)
CAM_VIEW_H = CAMERA_RESOLUTION_H      # sensor pixels (vertical)
HFOV_DEG = CAMERA_FOV_H_DEG           # horizontal field of view in degrees
VFOV_DEG = CAMERA_FOV_V_DEG           # vertical field of view in degrees

PIXELS_PER_DEG_X = CAM_VIEW_W / HFOV_DEG   # 640 / 4 = 160 px/deg default
PIXELS_PER_DEG_Y = CAM_VIEW_H / VFOV_DEG   # 480 / 3 = 160 px/deg default
PIXELS_PER_DEG = PIXELS_PER_DEG_X          # isotropic scalar alias

PRINCIPAL_U = CAM_VIEW_W / 2.0
PRINCIPAL_V = CAM_VIEW_H / 2.0
FOCAL_PX_X = (CAM_VIEW_W / 2.0) / __import__("math").tan(__import__("math").radians(HFOV_DEG / 2.0))
FOCAL_PX_Y = (CAM_VIEW_H / 2.0) / __import__("math").tan(__import__("math").radians(VFOV_DEG / 2.0))
FOCAL_PX = FOCAL_PX_X


def update_fov(hfov_deg, vfov_deg=None):
    """Dynamically update camera FOV and recalculate derived optical quantities independently for X and Y."""
    global HFOV_DEG, VFOV_DEG, CAMERA_FOV_H_DEG, CAMERA_FOV_V_DEG
    global PIXELS_PER_DEG_X, PIXELS_PER_DEG_Y, PIXELS_PER_DEG, FOCAL_PX_X, FOCAL_PX_Y, FOCAL_PX
    HFOV_DEG = float(max(0.5, min(20.0, hfov_deg)))
    CAMERA_FOV_H_DEG = HFOV_DEG
    if vfov_deg is not None:
        VFOV_DEG = float(max(0.5, min(20.0, vfov_deg)))
    else:
        VFOV_DEG = HFOV_DEG * (CAM_VIEW_H / CAM_VIEW_W)
    CAMERA_FOV_V_DEG = VFOV_DEG

    import math
    PIXELS_PER_DEG_X = CAM_VIEW_W / HFOV_DEG
    PIXELS_PER_DEG_Y = CAM_VIEW_H / VFOV_DEG
    PIXELS_PER_DEG = PIXELS_PER_DEG_X
    FOCAL_PX_X = (CAM_VIEW_W / 2.0) / math.tan(math.radians(HFOV_DEG / 2.0))
    FOCAL_PX_Y = (CAM_VIEW_H / 2.0) / math.tan(math.radians(VFOV_DEG / 2.0))
    FOCAL_PX = FOCAL_PX_X
    return HFOV_DEG, VFOV_DEG, PIXELS_PER_DEG_X, PIXELS_PER_DEG_Y, FOCAL_PX


def update_resolution(w, h):
    """Dynamically update sensor resolution and recalculate principal point and scales."""
    global CAM_VIEW_W, CAM_VIEW_H, CAMERA_RESOLUTION_W, CAMERA_RESOLUTION_H
    global PRINCIPAL_U, PRINCIPAL_V, PIXELS_PER_DEG_X, PIXELS_PER_DEG_Y, PIXELS_PER_DEG, FOCAL_PX_X, FOCAL_PX_Y, FOCAL_PX
    CAM_VIEW_W = int(max(160, min(3840, w)))
    CAM_VIEW_H = int(max(120, min(2160, h)))
    CAMERA_RESOLUTION_W = CAM_VIEW_W
    CAMERA_RESOLUTION_H = CAM_VIEW_H
    PRINCIPAL_U = CAM_VIEW_W / 2.0
    PRINCIPAL_V = CAM_VIEW_H / 2.0
    return update_fov(HFOV_DEG, VFOV_DEG)


def update_screen_size(w, h):
    """Dynamically update virtual screen size and center coordinates."""
    global SCREEN_SIZE_W, SCREEN_SIZE_H, SCREEN_CANVAS_CX, SCREEN_CANVAS_CY
    SCREEN_SIZE_W = int(max(500, min(10000, w)))
    SCREEN_SIZE_H = int(max(500, min(10000, h)))
    SCREEN_CANVAS_CX = SCREEN_SIZE_W / 2.0
    SCREEN_CANVAS_CY = SCREEN_SIZE_H / 2.0
    return SCREEN_SIZE_W, SCREEN_SIZE_H, SCREEN_CANVAS_CX, SCREEN_CANVAS_CY


# ---------------------------------------------------------------------------
# World / orbital geometry
# ---------------------------------------------------------------------------
BEACON_ANGULAR_RADIUS_DEG = 0.030    # HWHM of the beacon core on the sensor
BEACON_GLOW_MULT = 3.2               # glow extends this many core radii
MODULATION_FREQ_HZ = 15.0            # beacon amplitude modulation (blinking)
MODULATION_BRIGHT = 252              # bright phase of the modulation
MODULATION_DIM = 118                 # dim phase (still detectable -> robust)
# Modulation is an *implementation/design choice* for the simulated designated
# beacon signature - it is NOT an ISRO requirement.  When MODULATION_ENABLED is
# False the tracker still acquires/locks via the non-modulation evidence
# (appearance + persistence + spatial consistency + SNR + ephemeris prior) and
# all modulation checks are inert (no threshold, no penalty, no rejection).
MODULATION_ENABLED = True
# Phase tolerance of the 15 Hz sign-agreement correlators: best-of-(0..N) frame
# lags, kept exactly as the legacy hardcoded 0..2 set at the default of 2
# (phase-robust to the ~1 frame pipeline latency).
MODULATION_TOLERANCE_FRAMES = 2

# Per-run randomized ambiguity: the system is GIVEN a coarse ephemeris
# prediction (this PS's central premise) with a bias that grows with time
# (models unmodeled atmospheric drag / prediction divergence).
EPHEMERIS_START_BIAS_DEG = 0.55
EPHEMERIS_GROWTH_DEG_PER_SEC = 0.012
EPHEMERIS_MAX_BIAS_DEG = 2.6

# ---------------------------------------------------------------------------
# Pan-tilt gimbal (actuator realism)
# ---------------------------------------------------------------------------
GIMBAL_MAX_SLEW_DEG_S = 5.0          # PS default: max 5-10 deg/s, default 5
GIMBAL_MAX_TILT_DEG_S = 5.0          # PS default: max 5-10 deg/s, default 5
GIMBAL_ACCEL_DEG_S2 = 14.0            # acceleration limit (inertia)
GIMBAL_SERVO_KP = 25.0                # position gain  [1/s^2]
GIMBAL_SERVO_KD = 10.0                # velocity damping [1/s]  (= 2*sqrt(kp))
GIMBAL_LATENCY_FRAMES = 2            # measurement->command response delay
GIMBAL_STABIZATION_REJECT = 0.97     # inner-loop disturbance rejection (0-1).
                                     # Swept: 0.26 -> 0.082 deg mean pointing
                                     # error on full ADVERSARIAL at 0.97.

# ---------------------------------------------------------------------------
# Detection (Block D - front end)
# ---------------------------------------------------------------------------
TOP_HAT_RADIUS = 13                  # local-background estimation kernel
DETECTION_MEDIAN_PREFILTER = True    # 3x3 median kills salt-and-pepper spikes
                                     # before top-hat/CLOSE can fuse them into
                                     # the massive saturated regions that otherwise
                                     # swamp detection on noisy
DETECTION_ABS_THRESHOLD = 42         # signal above local background (grey levels)
DETECTION_MIN_BLOB_AREA = 5          # px^2
EXPECTED_BEACON_HUE = 8              # HSV hue (OpenCV 0-180) of the beacon core

# A blob far smaller than the beacon's known angular footprint (area_norm
# well under 1.0) cannot physically be the beacon -- it is salt-pepper or
# hot-pixel noise.  Pruning these tiny blobs is the single most powerful
# anti-decoy measure under heavy atmosphere (they are ~90% of SEVERE decoys).
MIN_BEACON_AREA_NORM = 0.10

# Persistent-blob association: give a stable ID to blobs that survive across
# frames so acquisition can "stick" to one physical object instead of flip-
# flopping between noise blobs (the #1 cause of never-locking under heavy
# atmosphere/noise).  Association done in world LOS space (deg).
TRACK_ASSOC_RADIUS_DEG = 0.12        # association radius - must be big enough
                                     # that SEVERE LOS jitter keeps the beacon on
                                     # one ID (persistence), small enough that
                                     # it never merges a near decoy into the
                                     # beacon's modulation history.
TRACK_RESCUE_RADIUS_DEG = 0.25
TRACK_MISS_TOL = 3                   # frames an ID survives while unseen
PERSISTENCE_BOOST = 1.35             # acquisition fusion multiplier for age>=2 tracks
MOD_ASSOC_K = 1.6                    # how strongly a blob's own 15 Hz modulation
                                     # score lifts its association/fusion score
                                     # (beacon blinks -> wins over static decoys)
ASSOC_TRACK_MOD_MIN = 0.55           # when a candidate's own-track area
                                     # modulation clears this, the association /
                                     # fusion boost (MOD_ASSOC_K, applied only
                                     # while modulation identity is active) kicks
                                     # in - the modulated beacon wins over static
                                     # decoys that sit around 0.5

# ---------------------------------------------------------------------------
# Estimation / tracking state machine
# ---------------------------------------------------------------------------
ACQUIRE_CONFIRM_FRAMES = 3           # temporal confirmation before lock
ACQUIRE_CONSISTENCY_PX = 14
COAST_TIMEOUT_S = 0.45               # lost frames before entering SEARCH
ASSOC_GATE_DEG = 0.30                # candidate->track association gate
# Uncertainty-aware association gate (synthetic mode, modulation on or off):
#    effective_gate = base_gate
#                   + ASSOC_UNCERTAINTY_FACTOR * sigma_px (-> deg)
#                   + ASSOC_LATENCY_MARGIN_FACTOR * motion during gimbal latency
# clamped to ASSOC_MAX_GATE_DEG.  Uses the INTERNAL uncertainty estimator (the
# HUD display cap must never gate loop behaviour).  Video mode keeps its own
# wide field-facing gate and is not clamped here.
# ---------------------------------------------------------------------------
# Authoritative Primary Tracking States (Part 2: Single Source of Truth)
# ---------------------------------------------------------------------------
STATE_SEARCHING = "SEARCHING"
STATE_CANDIDATE = "CANDIDATE"
STATE_ACQUIRING = "ACQUIRING"
STATE_LOCKED = "LOCKED"
STATE_DEGRADED_LOCK = "DEGRADED_LOCK"
STATE_COASTING = "COASTING"
STATE_REACQUIRING = "REACQUIRING"
STATE_LOST = "LOST"

ALL_TRACKING_STATES = (
    STATE_SEARCHING,
    STATE_CANDIDATE,
    STATE_ACQUIRING,
    STATE_LOCKED,
    STATE_DEGRADED_LOCK,
    STATE_COASTING,
    STATE_REACQUIRING,
    STATE_LOST,
)

# Lock qualification thresholds (Part 3 & 4)
LOCK_CONFIRM_FRAMES = 5         # consecutive frames of valid observation to achieve initial LOCKED
REACQ_CONFIRM_FRAMES = 3        # consecutive frames of valid observation to re-achieve LOCKED from REACQUIRING
LOCK_MIN_CONF = 0.70            # overall confidence must be >= this for full LOCKED
DEGRADED_ENTER_CONF = 0.55      # confidence to enter DEGRADED_LOCK from reacquisition
LOCK_HOLD_MIN_CONF = 0.45       # confidence floor to retain lock before dropping to COASTING (hysteresis)
LOCK_MAX_UNCERTAINTY_PX = 14.0  # uncertainty must be <= this for full LOCKED
LOCK_MAX_RESIDUAL_PX = 18.0     # observation-prediction residual must be <= this for full LOCKED
LOST_TIMEOUT_S = 0.35           # duration to hold LOST before resetting to SEARCHING

ASSOC_UNCERTAINTY_FACTOR = 0.5       # gate grows with internal sigma (px)
ASSOC_LATENCY_MARGIN_FACTOR = 1.0    # gate grows with predicted motion over the
                                     # GIMBAL_LATENCY_FRAMES delay (deg)
ASSOC_MAX_GATE_DEG = 0.6             # hard clamp of the effective gate (deg)
MOD_CORREL_WIN = 18                  # frames of intensity history for modulation ID
MOD_LOCK_THRESHOLD = 0.62            # correlation for beacon-lock commit (true:~0.95, decoy:<0.55)
MOD_SUSPECT_FLOOR = 0.58             # locked object below this modulation corr for
MOD_SUSPECT_DROP_FRAMES = 12         # ... this many frames -> false-lock drop to
                                     # search (was 30: a merged/decoys lock at
                                     # ~0.5 lingered for a full second).  True
                                     # beacon reads 0.75-0.89, so 12 frames of
                                     # sustained sub-floor correlation is a safe
                                     # false-lock signal while keeping fade/
                                     # occlusion relook margins (0.4 s).
ML_LOCK_THRESHOLD = 0.55             # appearance-classifier threshold
ML_FLOOR_SCORE = 0.40                # generous acquisition floor (physical footprint gate does the real pruning)
FUSION_WEIGHT_MOD = 0.55             # fusion: modulation score weight
FUSION_WEIGHT_ML = 0.45              # fusion: appearance score weight
SEARCH_GROWTH_DEG_S = 0.55           # spiral search speed (deg/s)
SEARCH_MAX_RADIUS_DEG = 3.2
ESTIMATOR_ALPHA = 0.35               # bias-tracking filter gain (lower = smoother)
ESTIMATOR_LAG_GAIN = 0.18            # extra bias-gain per deg/s of target motion
                                     # (kills lag on fast random targets, keeps
                                     # low-noise smoothing on slow ones)
ESTIMATOR_ALPHA_MAX = 0.85           # adaptive gain cap (never pure pass-through)
CONTROL_VEL_EMA = 0.6                # set-point velocity feedforward smoothing

# ---------------------------------------------------------------------------
# Adaptive Model-Vision Trust (Phase 2 novelty)
# ---------------------------------------------------------------------------
# The tracker continuously decides how much to trust the visual measurement
# versus the motion-model / ephemeris prediction, from confidence + uncertainty
# + prediction residual + disturbance level.  Decisions use hysteresis so the
# mode cannot chatter frame-to-frame.
TRUST_VISION_W_ML = 0.30             # weight of AI appearance confidence
TRUST_VISION_W_MOD = 0.25            # weight of modulation identity
TRUST_VISION_W_SNR = 0.25            # weight of measurement SNR
TRUST_VISION_W_CENTROID = 0.20       # weight of centroid stability
TRUST_MODEL_W_PRED = 0.45            # weight of prediction residual consistency
TRUST_MODEL_W_PRIOR = 0.30           # weight of prior reliability (historical)
TRUST_MODEL_W_DIST = 0.25            # weight of disturbance condition
DEGRADED_ENTER_CONF = 0.55           # enter DEGRADED_LOCK below this overall conf
DEGRADED_EXIT_CONF = 0.70            # exit DEGRADED_LOCK above this overall conf
VISION_DOMINANT_MARGIN = 0.18        # vision_trust >= model_trust + margin
MODEL_DOMINANT_MARGIN = 0.18         # model_trust >= vision_trust + margin
UNCERTAINTY_BASE_PX = 2.0            # nominal position uncertainty (px)
UNCERTAINTY_SNR_K = 8.0              # snr -> sigma scale (lower snr -> higher sigma)
# Coast growth: sigma(t) = sigma0 + k1*t + k2*t^2.  With the coefs below a
# nominal 2 px state crosses the 18 px REACQUIRE line at ~0.34 s - well
# inside COAST_TIMEOUT_S=0.45 - so the escalation COAST -> REACQUIRING ->
# (re-lock | SEARCH) is genuinely exercised instead of being dead code
# (previously growth was far too slow and REACQUIRING was unreachable).
UNCERTAINTY_COAST_GROW_S = 36.0      # coast uncertainty linear growth (px/s)
UNCERTAINTY_COAST_GROW2_S = 30.0     # cooperative growth (px/s^2)
REACQUIRE_UNCERTAINTY_PX = 18.0      # uncertainty above this -> active reacquisition
# HUD/plot display cap.  The estimator's INTERNAL sigma is unbounded (the real
# telemetry the loop acts on); only the number painted on screen is clamped so
# a long outage cannot render a silly bar.  Reacquisition logic always reads
# the internal value, so this cap never gates behaviour.
UNCERTAINTY_DISPLAY_PX_CAP = 24.0

# ---------------------------------------------------------------------------
# Predictive coast & staged reacquisition (PART 3)
# ---------------------------------------------------------------------------
# Predictive coast is a forward extrapolation of the last fused estimate:
#     x_pred = x + v * dt   (velocity lead over the estimate's smoothing time
#                            constant, plus the extra GIMBAL_LATENCY_FRAMES of
#                            transport delay so the camera keeps leading the
#                            beacon through a feedforward latency).
# It is only valid for a bounded horizon - past that the (correctly) growing,
# uncapped internal uncertainty means the belief is no longer trustworthy, so
# the tracker must escalate.  All are tunables; COAST_TIMEOUT_S (above) is the
# hard ceiling on any single predictive-coast leg.
COAST_VELOCITY_LEAD_S = 0.10        # deg/s velocity lead applied on top of the
                                    # estimate's own smoothing lag
COAST_LATENCY_LEAD = True           # add GIMBAL_LATENCY_FRAMES of transport
                                    # delay to the predictive lead
# Staged reacquisition ladder.  Once a lock is lost and BEACON becomes
# REACQUIRING, the recovery is a deterministic LEVEL 1 -> 2 -> 3 escalation,
# each with its own configurable association-gate multiplier (radii around the
# last LOS) and a per-level duration budget.  The gate widens while the ridge
# of the (already grown) internal uncertainty is respected, so on a fast or
# manoeuvring target the beacon links back at the first level that is wide
# enough - never an immediate blind sweep.  Only after the FULL ladder times
# out (~1.0 s) does the loop fall through to blind SEARCHING.  A re-observation
# at any level still runs the full appearance/modulation verification before
# LOCKED is re-committed (a widened gate never by-passes identity).
REACQ_LEVEL_GATE_MULT = [1.0, 2.2, 4.0]        # per-level assoc-gate multiplier
REACQ_LEVEL_DURATION_S = [0.30, 0.30, 0.26]    # per-level budget (sum ~0.86 s)
REACQ_LEVEL_SEARCH_SPEED = [0.20, 0.45, 1.0]   # expanding-spiral growth scale
REACQ_TIMEOUT_S = 1.0                          # hard cap on the whole ladder
REACQ_LEVELS = len(REACQ_LEVEL_GATE_MULT)      # 3 (LEVEL 1..3)
# Association gate multiplier while in REACQUIRING: replaced by the staged
# per-level multipliers (REACQ_LEVEL_GATE_MULT above, Part 3) so the gate widens
# with the recovery ladder instead of being a single fixed widen.
# (Kept for documentation/history only.)
# Model-honesty conversion: how strongly the filter's bias-CHASE RATE (deg/s)
# counts as a prediction residual (deg).  A healthy ephemeris needs only tiny,
# slow bias corrections; a corrupted prior or an unmodelled manoeuvre forces
# the bias filter to run continuously, and THAT activity is a signal the bias
# absorber cannot cancel (the absorption itself is the evidence).  A chase rate
# of, e.g., ~0.5 deg/s weighs like a ~0.4 deg residual against the 0.55 deg
# prediction scale -> model trust collapses -> VISION_DOMINANT hands the loop
# to the camera.
TRUST_CHASE_K = 0.8
# trust-story (stress_test --scenario truststory) beacon-burn acceleration
# (deg/s^2). The burn accelerates the beacon away from (and only away from)
# the ephemeris the tracker believes; the monotonic displacement forces the
# bias filter to chase the prior every frame (chase = acc*(t-7) deg/s), which
# the model-honesty conversion reads as a constant prediction failure ->
# VISION_DOMINANT holds the loop for the whole burn.  At BURN_T1 ops uploads
# the post-burn elements (the scenario re-anchors the tracker's ephemeris and
# bias), so phase D reverts to BALANCED/MODEL without any geometric step.
TRUSTSTORY_ACC = 0.8
TRUSTSTORY_BURN_T1 = 12.5
# Per-preset burn profile: harder presets get a gentler, shorter burn so the
# maximum displacement stays inside the bias absorber / association-gate reach
# -- the VISION story still holds (the chase rate keeps the model-honesty
# residual above the VISION margin the whole burn) but the loop never outruns
# itself into a coast before the state-vector heal.
TRUSTSTORY_ACC_BY_PRESET = dict(EASY=0.8, MODERATE=0.7, HARD=0.7)
TRUSTSTORY_T1_BY_PRESET = dict(EASY=12.5, MODERATE=11.5, HARD=11.5)

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
FINE_ACQUISITION_REGION_DEG = 0.0625 # PS 10 px tracking spec at 160 px/deg

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
    # ISRO benchmark preset - "RX sat downlink" conditions: benign two-axis
    # ephemeris pub track, moderate atmospheric turbulence, and a bright
    # solar-panel-glare distractor parked near the beam (the classic wrong-target
    # test for any coarse-pointer).  Solar glare is a *static* luminous blob, so
    # it maximally stresses the identity/decoy separation of the AI+modulation
    # fusion; kept out of PRESET_ORDER (not part of the 1-5 live schema).
    "ISRO_RX": dict(
        turbulence=25, vibration=10, sensor_noise=12, jerk_prob=0,
        beacon_fade=5, distractors=2, obstacles=1,
        az_amp=1.20, el_amp=0.80, speed=1.00,
        noise_types=["gaussian"],
        motion_type="straight_line",
    ),
}

PRESET_ORDER = ["EASY", "MODERATE", "HARD", "SEVERE", "ADVERSARIAL", "ISRO_RX"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "logs"
RESULTS_DIR = "logs"
SIM_DURATION_S = 120                 # default run length for the timed demo
