# AI-Based Virtual Camera Tracking System for Coarse Alignment of Mobile FSOC Terminals

**ISRO Challenge - Problem Statement ID 26169**

A real-time simulation and autonomous beam-pointing system for Free-Space Optical Communication (FSOC) terminals mounted on mobile platforms (ships, vehicles, UAVs). The system demonstrates a complete closed-loop pipeline: scene rendering, beacon detection, AI classification, modulation-based identification, state estimation, and gimbal servo control — all running at 30–48 fps on commodity hardware.

---

## Quick Start

```bash
# Install dependencies
pip install pygame-ce opencv-python numpy

# Run the mission-console GUI
python main.py

# Run headless stress test
python -m metrics.stress_test --trials 3 --seconds 15

# Train the ML classifier (pre-trained weights baked in)
python -m ai.train_classifier
```

### Keyboard Controls (GUI)

| Key | Action |
|-----|--------|
| `1`–`5` | Switch difficulty preset (EASY → ADVERSARIAL) |
| `Space` | Pause / Resume simulation |
| `R` | Reset tracker state |
| `F` | Toggle fullscreen |
| `V` | Toggle FOV grid overlay |
| `Escape` | Quit |

---

## Architecture

```
main.py                    Mission console GUI (pygame-ce 2.5.8)
├── ui/theme.py            Dark palette, fonts, rendering helpers
├── ui/widgets.py          Sliders, buttons, chips, sparklines, KPI cards
├── ui/view3d.py           Radar-style sky plot (trajectory, FOV, truth)
├── core/simulator.py      Frame loop: scene → sensor → detect → track → control
│   ├── core/scene.py      Beacon, Distractor, Obstacle objects + orbital model
│   ├── core/sensor.py     Gaussian PSF rendering, intensity history, disturbance
│   ├── core/disturbances.py  Turbulence, vibration, sensor noise, sky background
│   ├── core/detection.py  Gaussian blob detection + ML logistic-regression classifier
│   ├── core/tracking.py   State machine (SEARCHING → TENTATIVE → LOCKED → COASTING)
│   │                      Phase-robust modulation correlator, suspect-floor verifier
│   ├── core/gimbal.py     PD position servo with latency FIFO (2-frame pipeline)
│   └── core/control.py    Gimbal attitude command bridge
├── ai/classifier.py       Baked logistic-regression weights (96% train / 97% val)
├── ai/train_classifier.py Training pipeline (synthetic + augmented features)
├── metrics/performance.py CSV logging, live stats (acquisition, retention, error)
├── metrics/stress_test.py Multi-trial headless benchmark harness
└── config.py              All tunables, difficulty presets, servo parameters
```

### Core Tracking Pipeline

1. **Scene rendering** — Gaussian PSF beacon with 15 Hz amplitude modulation; distractors, obstacles, atmospheric turbulence, platform vibration.
2. **Detection** — OpenCV blob detection + ML classifier scores each candidate (appearance, SNR, centroid, area, circularity).
3. **Modulation identification** — Phase-robust sign-agreement correlator tests candidates against the known 15 Hz modulation signature over a sliding 18-frame window, maximizing over 0–2 frame lag hypotheses.
4. **Acquisition gating** — Candidates must pass the ML appearance bar AND the ephemeris prior gate; a tentative track requires spatial consistency (≤0.12° jitter for 3 frames) AND modulation correlation ≥ 0.62 before LOCKED is committed.
5. **Continuous verification** — While LOCKED, a suspect-floor monitor (corr < 0.58 for 30 consecutive frames) drops a wrong-target track back to SEARCHING.
6. **State estimation** — Ephemeris prior + leaky-absorbed bias (α = 0.35) produces smooth, low-latency boresight commands.
7. **Gimbal servo** — PD position controller (Kp = 25, Kd = 10) with slew-rate limiting (10°/s), acceleration clamping (14°/s²), and 2-frame latency FIFO.

---

## Performance Summary

Benchmarked across five difficulty presets (3 trials × 15 s each, 60 fps, pygame-ce headless):

| Preset | Acquisition | Retention | Mean Error | RMS Error | Max Error | False Locks | FPS |
|--------|------------|-----------|------------|-----------|-----------|-------------|-----|
| **EASY** | 0.37 s | 98.6% | 0.029° | 0.045° | 0.360° | 0 | 40 |
| **MODERATE** | 0.41 s | 87.8% | 0.189° | 0.234° | 0.538° | 2 | 34 |
| **HARD** | 1.68 s | 82.3% | 0.264° | 0.305° | 0.654° | 3 | 35 |
| **SEVERE** | 1.09 s | 88.3% | 0.297° | 0.341° | 0.732° | 3 | 31 |
| **ADVERSARIAL** | 1.40 s | 94.1% | 0.444° | 0.498° | 0.899° | 6 | 32 |

**Key results (hero preset — EASY):**
- Acquisition in < 0.4 s (< 22 frames)
- Boresight error: 0.029° mean (105 arcseconds) — well within coarse-alignment spec
- Zero false-lock events; 98.6% tracking retention
- Sustained 40 fps real-time throughput

---

## Difficulty Presets

| Parameter | EASY | MODERATE | HARD | SEVERE | ADVERSARIAL |
|-----------|------|----------|------|--------|-------------|
| Turbulence | 5 | 20 | 40 | 65 | 85 |
| Vibration | 2 | 8 | 18 | 32 | 45 |
| Sensor noise | 5 | 10 | 18 | 28 | 38 |
| Platform jerk (%) | 0 | 1 | 3 | 6 | 9 |
| Distractors | 0 | 1 | 2 | 4 | 4 |
| Obstacles | 0 | 1 | 2 | 3 | 4 |
| Orbit amplitude (°) | 1.0 | 1.4 | 1.8 | 2.2 | 2.6 |
| Orbit speed | 1.0× | 1.15× | 1.35× | 1.65× | 2.0× |

---

## Project Structure

```
.
├── config.py              Central configuration
├── main.py                GUI entry point
├── core/
│   ├── __init__.py
│   ├── scene.py           Scene objects and orbital model
│   ├── sensor.py          Camera sensor with PSF rendering
│   ├── disturbances.py    Atmospheric + platform disturbances
│   ├── detection.py       Blob detection and ML classification
│   ├── tracking.py        Acquisition and tracking state machine
│   ├── gimbal.py          Gimbal dynamics and servo control
│   ├── control.py         Control bridge
│   ├── geometry.py        Math utilities
│   ├── orbital.py         Relative orbit model
│   └── simulator.py       Simulation frame loop
├── ai/
│   ├── classifier.py      ML classifier (baked weights)
│   └── train_classifier.py Classifier training script
├── ui/
│   ├── __init__.py
│   ├── theme.py           Dark theme palette and fonts
│   ├── widgets.py         UI widgets (sliders, buttons, charts)
│   └── view3d.py          Radar sky plot
├── metrics/
│   ├── __init__.py
│   ├── performance.py     Performance tracker and CSV logger
│   └── stress_test.py     Multi-trial benchmark harness
└── logs/                  Screenshots and benchmark logs
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pygame-ce` | ≥ 2.5 | Real-time GUI, rendering |
| `opencv-python` | ≥ 4.8 | Blob detection, image processing |
| `numpy` | ≥ 1.24 | Numerical computation |
| Python | ≥ 3.10 | Runtime |

---

## ISRO Challenge Alignment

| ISRO Requirement | Our Solution |
|------------------|--------------|
| Real-time coarse pointing | Closed-loop 30–48 fps pipeline |
| Mobile platform compensation | Relative orbital model + disturbance engine |
| Robust beacon tracking | Multi-stage acquisition: ML + modulation + spatial consistency |
| Low residual error | 0.029° mean (EASY), 0.189° (MODERATE) |
| Disturbance rejection | Tuned PD servo with latency compensation |
| Edge-deployable | Pure Python, no GPU required |

---

## License

Developed for the ISRO SIH 2026 challenge.
