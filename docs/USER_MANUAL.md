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
state=LOCKED acq=0.23s retention=94.6% mean_err=0.034° rms=0.06° fps=40.0 false_lock=0
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

### Layout — aerospace console

The interface is organised around the coarse-PAT story, not stacked debug numbers:

```
┌───────────────────────────────────────────────────────────┬───────────┐
│ HEADER: FSOC-PAT LAB · PS 26169 · SCENARIO chips          │  MISSION  │
├───────────────────────────────────────┬───────────────────┤───────────┤
│                                       │  MISSION GEOMETRY │           │
│       MAIN CAMERA VIEW  (dominant)    │  (relative-LOS    │  PAT      │
│       + PAT STATE stepper overlay     │   sky plot)       │  PERF     │
│       + FOV/beacon story banner       │                   │───────────┤
│       + POINTING ERROR (hero, bottom) │  EPHEMERIS pred   │  DISTURBS │
├───────────────────────────────────────┤  vs detected      │           │
│ LIVE ANGULAR POINTING ERROR graph  +  │                   │───────────┤
│ CAMERA/ACTUATOR readout + A→B beam    │  CONTROLS         │  CONTROLS │
└───────────────────────────────────────┴───────────────────┴───────────┘
```

### Camera View (dominant, left/centre)

The main camera/FOV view fills the majority of the screen and shows:

- **Beacon**: Bright white circle with alternating brightness (15 Hz modulation), labelled **SAT-B BEACON**
- **Distractors**: Dimmer colored circles (steady, 3 Hz, or 8 Hz modulation)
- **Obstacles**: Dark discs that periodically occlude the beacon
- **Optical boresight reticle**: Fixed crosshair at the gimbal's commanded boresight (blue)
- **Tracking reticle + ring**: Green ring + crosshair placed on the **locked** SAT-B beacon
- **Synth-ephemeris prior marker**: Dashed amber diamond showing where the propagator predicts SAT-B should be (yellow = predicted)
- **PAT state stepper** (top overlay): `PREDICT → POINT → SEARCH → TRACK → LOCK` with the active stage highlighted; shows `PREDICTIVE COAST` or `SEARCHING / LOST` on loss
- **FOV / beacon story banner** (bottom overlay): `OUTSIDE FOV → ACQUISITION WINDOW → BEACON ACQUIRED · LOCKED`
- **POINTING ERROR** (hero, bottom-right): the live boresight error in **millidegrees (mdeg)** in large type, colour-coded (green < 0.10°, amber < 0.30°, red otherwise)

Color semantics are consistent: **green = detected/locked target**, **yellow = predicted/ephemeris**, **blue = boresight/FOV**, **red = warning/lost**.

### Bottom Strip

- **ANGULAR POINTING ERROR** — a single live graph (in degrees) with a shaded fine-acquisition band (< 0.10°), so a disturbance and the controller's recovery are clearly visible. Right side shows a **CAMERA / ACTUATOR** readout (Azimuth, Elevation, FOV, MODE) and an **A → beam → B** alignment mini-diagram with the live mdeg error.

### Right Column (stacked cards)

- **MISSION**: Observer `SAT-A`, Target `SAT-B (optical beacon)`, Mode `COARSE ALIGNMENT`, live Status
- **MISSION GEOMETRY**: enlarged relative-LOS sky plot (orbit trajectory, ephemeris prior in amber, estimate in green, boresight, FOV gate, ground-truth)
- **PAT PERFORMANCE**: large **POINTING ERROR** hero, plus ACQUISITION / RETENTION / REACQUISITION primaries; expandable **DIAGNOSTICS** line (mean/RMS/max error, confidence, FPS) via the Diagnostics button
- **EPHEMERIS PREDICTION vs DETECTION**: predicted (amber) vs detected (green) with the current ephemeris bias in degrees
- **DISTURBANCES**: compact sliders (turbulence, vibration, sensor noise, jerk, beacon fade), each with a physical-unit hint
- **CONTROLS**: Pause, Reset, Screenshot, **GT ON/OFF** (ground-truth evaluation overlay), **DIAGNOSTICS** toggle

### Ground-Truth / Evaluation Separation

By default the operational view shows **only** what the algorithm sees (ephemeris prediction, camera observation, estimated state, tracking result). Press **GT** (purple button) to overlay the **GROUND TRUTH · EVALUATION ONLY** marker for benchmarking — it is clearly labelled so the demo never looks like it is handed the answer.

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
| `R` | Reset tracker | Clears track state, re-acquires (video mode: restart video) |
| `S` | Screenshot | Saves `logs/shot_*.png` of the full window |
| `L` | Load MP4 | Benchmark-2 file picker (video bypass mode) |
| `F` | Toggle fullscreen | Switches between windowed and fullscreen |
| `V` | Toggle FOV grid | Shows/hides field-of-view grid overlay |
| `Escape` | Quit | Exits the application |

---

## 4. Benchmark-2: Video Input (PTZ Bypass)

Benchmark-2 of PS 26169 supplies `.mp4` files with a moving beacon spot and
noise. The software must **bypass its virtual PTZ camera and take the video as
the input** to the coarse-pointing system.

### Load a video in the GUI

Click the **LOAD MP4** button (bottom-right) or press `L`. Pick any `.mp4`.
The app switches to *VIDEO BYPASS* mode: each video frame is pushed through the
real detection → tracking → gimbal pipeline, and the live centroiding error,
lock state, retention and acquisition time are shown in the right-hand panels.

### Load a video from the command line

```bash
python main.py --video path/to/video.mp4
```

If a ground-truth sidecar `<video>_truth.csv` exists next to the video (columns
`frame,t,bx,by` — emitted automatically by the generator below), the GUI and
the report compute **centroiding error against the predefined truth**, exactly
as the evaluators compare. Without ground truth, error is measured from the
frame centre.

### Generate your own benchmark videos

```bash
python -m metrics.synthetic_video --output logs/bench.mp4 \
    --width 640 --height 480 --fps 30 --seconds 20 \
    --motion figure_eight --noise gaussian,salt_pepper
```

This writes `logs/bench.mp4` **and** `logs/bench_truth.csv`.

### Headless Benchmark-2 report

```bash
python -m metrics.mp4_bypass --input logs/bench.mp4 --output logs/bypass.csv
```

Runs the whole video through the real loop and writes the mandatory
performance log (centroiding error mean/RMS/p95/max, acquisition time, lock
retention, re-acquisition, false locks, processing FPS).

### Sample result (figure-8, 10 s, 640×480, Gaussian noise)

```
Acquisition time:         0.10 – 0.27 s    (PS spec ≤ 2 s)
Lock retention:           97.7 – 99.3 %    (PS spec ≥ 95 %)
Centroiding err, p95:     ≈ 0.9 px         (PS spec ≤ 10 px)
Centroiding err, mean:    0.5 – 4.0 px
Re-acquisitions:          0
False locks:              0
Processing:               60+ fps (GUI) / 134 fps (headless)
```

The run-to-run range is produced by the few pre-lock SEARCHING frames; every
locked frame tracks at sub-1 px p95 err. Pass `--video-seed N` for a
reproducible tracker RNG.

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

| Preset | Turbulence | Vibration | Noise | Jerk | Fade | Distractors | Obstacles |
|--------|-----------|-----------|-------|------|------|-------------|-----------|
| EASY | 5 | 2 | 5 | 0% | 0% | 0 | 0 |
| MODERATE | 20 | 8 | 10 | 1% | 10% | 1 | 1 |
| HARD | 40 | 18 | 18 | 3% | 30% | 2 | 2 |
| SEVERE | 65 | 32 | 28 | 6% | 45% | 4 | 3 |
| ADVERSARIAL | 85 | 45 | 38 | 9% | 60% | 4 | 4 |

### Live Slider Adjustments

Some parameters can be adjusted live using the sliders on the right panel. Changes take effect on the next frame for visual parameters (turbulence, vibration, sensor noise, beacon fade, jerk) but require a tracker reset (`R` key) for tracking-related thresholds. Each slider is annotated with its **physical unit** under the knob so a judge can interpret what is actually being changed.

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
