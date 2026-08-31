# User Manual: AI-Based Virtual Camera Tracking System

**ISRO SIH 2026 — Problem Statement 26169**

---

## 1. Installation

### Prerequisites

- Python 3.10 or later
- pip package manager

### Install Dependencies

```bash
pip install pygame-ce opencv-python numpy
```

### Verify Installation

```bash
python main.py --frames 60 --preset EASY
```

If successful, you should see output like:

```
pygame-ce 2.5.8 (SDL 2.x.x, Python 3.x.x)
headless self-test: preset=EASY frames=60
state=LOCKED acq=0.38s retention=85.6% mean_err=0.086° rms=0.127° fps=37.1 false_lock=0
```

---

## 2. Running the GUI

### Launch

```bash
python main.py
```

The mission-console GUI opens in an 1600×900 window with a dark aerospace theme.

### GUI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  AI-FSOC PAT Mission Console                              [EASY]  │
│                                                                     │
│  ┌─────────────────────────────────┐  ┌───────────────────────┐    │
│  │                                 │  │ Chips: CAM INERTIAL   │    │
│  │     Camera View (800×450)       │  │ TRACKING   GOOD       │    │
│  │     ┌─────┐  ┌─────┐           │  │                        │    │
│  │     │guide│  │brack│           │  │  ┌──────────────────┐  │    │
│  │     │box  │  │ets  │           │  │  │                  │  │    │
│  │     └─────┘  └─────┘           │  │  │  Sky Plot (radar) │  │    │
│  │     ● beacon  ◆ distractor     │  │  │                  │  │    │
│  │                                 │  │  └──────────────────┘  │    │
│  └─────────────────────────────────┘  │                        │    │
│                                       │  KPI: ERR   0.029°    │    │
│  ┌─────────────────────────────────┐  │         ACQ  0.37s    │    │
│  │ Bottom: Pan/Tilt/Err telemetry  │  │         FPS  40       │    │
│  │ + scope + association badge     │  │                        │    │
│  └─────────────────────────────────┘  │  Sliders: turbulence  │    │
│                                       │  vibration, noise, etc │    │
│                                       │                        │    │
│                                       │  [ Pause ] [ Reset ]   │    │
│                                       └───────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Camera View

The main camera view shows:

- **Beacon**: Bright white circle with alternating brightness (15 Hz modulation)
- **Distractors**: Dimmer colored circles (steady, 3 Hz, or 8 Hz modulation)
- **Obstacles**: Dark discs that periodically occlude the beacon
- **Guide box**: White rectangle showing the gimbal's current boresight position
- **Tracking bracket**: Green (LOCKED) or yellow (TENTATIVE) bracket around the associated candidate
- **Scope line**: Thin line from guide box to the estimated boresight position
- **Association badge**: Upper-right corner shows acquisition state and mod correlation

### Bottom Telemetry Bar

Displays real-time gimbal state:
- **Pan/Tilt**: Current gimbal angles in degrees
- **Error**: Boresight error (truth − estimated)
- **Association**: Tracking state and modulation correlation

### Right Panel

- **Status chips**: One-word status for each subsystem (CAM, INERTIAL, TRACKING, LATENCY)
- **Sky plot**: Radar-style azimuth-elevation display with trajectory history, ephemeris prediction, estimate, truth, and FOV cone
- **KPI cards**: Key performance indicators (error, acquisition time, FPS)
- **Sliders**: Live difficulty parameters (reset required for some)
- **Buttons**: Pause, Reset

---

## 3. Keyboard Controls

| Key | Action | Notes |
|-----|--------|-------|
| `1` | Switch to EASY preset | No turbulence, no distractors |
| `2` | Switch to MODERATE preset | Light turbulence, 1 distractor |
| `3` | Switch to HARD preset | Moderate turbulence, 2 distractors |
| `4` | Switch to SEVERE preset | Heavy turbulence, 4 distractors |
| `5` | Switch to ADVERSARIAL preset | Extreme conditions, 4 distractors |
| `Space` | Pause / Resume | Freezes the simulation |
| `R` | Reset tracker | Clears track state, re-acquires |
| `F` | Toggle fullscreen | Switches between windowed and fullscreen |
| `V` | Toggle FOV grid | Shows/hides field-of-view grid overlay |
| `Escape` | Quit | Exits the application |

---

## 4. Running Headless Benchmarks

### Single Preset

```bash
python main.py --frames 120 --preset MODERATE
```

Runs 120 frames without a display and prints summary statistics.

### Multi-Trial Stress Test

```bash
python -m metrics.stress_test --trials 3 --seconds 15
```

Runs 3 independent trials of 15 seconds each for all 5 difficulty presets. Results are printed in a formatted table and saved to `logs/stress_test_summary.csv`.

### Custom Parameters

```bash
python -m metrics.stress_test --trials 5 --seconds 30
```

Available options:
- `--trials N`: Number of independent trials per preset (default: 3)
- `--seconds S`: Duration of each trial in seconds (default: 15)

---

## 5. Understanding the Metrics

### Acquisition Time

Time (in seconds) from simulation start until the tracker first reaches LOCKED state. Lower is better. Affected by:
- Turbulence level (higher = slower)
- Number of distractors (more = slower)
- Platform motion speed (faster = slower)

### Retention (%)

Percentage of frames where the beacon is visible AND the tracker is in LOCKED state. Higher is better. Affected by:
- Obstacle frequency (more occlusion = lower retention)
- Turbulence (can cause temporary loss)
- False-lock drops (suspect-floor reverts)

### Mean/RMS/Max Error

Boresight error in degrees between the true beacon position and the tracker's estimate. Lower is better. Affected by:
- Turbulence (causes centroid jitter)
- Distractors (can bias the estimate during blends)
- Gimbal servo accuracy

### False Locks

Number of episodes where the tracker is LOCKED but the boresight error exceeds 0.35° for 5+ consecutive frames while the beacon is visible. Lower is better. Caused by:
- Distractor blobs within the association gate
- Beacon dim-phase allowing distractor dominance

### FPS

Frames per second of the simulation loop. Higher is better. Affected by:
- Disturbance complexity (more objects = slower)
- Detection count (more candidates = slower tracking)

---

## 6. Adjusting Difficulty

### Preset Parameters

The five presets escalate all disturbance parameters simultaneously:

| Preset | Turbulence | Vibration | Noise | Jerk | Distractors | Obstacles |
|--------|-----------|-----------|-------|------|-------------|-----------|
| EASY | 5 | 2 | 5 | 0% | 0 | 0 |
| MODERATE | 20 | 8 | 10 | 1% | 1 | 1 |
| HARD | 40 | 18 | 18 | 3% | 2 | 2 |
| SEVERE | 65 | 32 | 28 | 6% | 4 | 3 |
| ADVERSARIAL | 85 | 45 | 38 | 9% | 4 | 4 |

### Live Slider Adjustments

Some parameters can be adjusted live using the sliders on the right panel. Changes take effect on the next frame for visual parameters (turbulence, vibration, noise) but require a tracker reset (`R` key) for tracking-related parameters.

---

## 7. Troubleshooting

### Low FPS (< 25)

- Close other applications
- Switch to EASY preset (fewer objects, less disturbance)
- Ensure you're using `pygame-ce` (not `pygame`): `pip install pygame-ce`

### Beacon Not Detected

- Check that the beacon is within the camera FOV (800×450 px, HFOV 2.4°)
- At higher difficulty levels, the beacon may be occluded by obstacles — wait for re-acquisition
- If stuck in SEARCHING, press `R` to reset the tracker

### False Locks

- At HARD and above, occasional false-lock events are expected under extreme conditions
- The system self-recovers within 0.3–0.5 seconds via the suspect-floor monitor
- Switch to a lower difficulty preset for cleaner tracking

### GUI Not Displaying

- Ensure `pygame-ce` is installed: `pip install pygame-ce`
- On some systems, set the SDL video driver: `set SDL_VIDEODRIVER=directx`

---

## 8. File Output

### Logs Directory

All output is saved to the `logs/` directory:

- `stress_test_summary.csv`: Benchmark results (one row per preset)
- `run_*.csv`: Per-frame performance logs from GUI sessions
- `shot_*.png`: GUI screenshots

### CSV Format

Performance logs include columns: `frame, state, est_err_deg, truth_az, truth_el, est_az, est_el, confidence, beacon_visible, fps`.

---

*Developed for ISRO SIH 2026 — Problem Statement 26169*
