# AI-Based Virtual Camera Tracking System for Coarse Alignment of Mobile FSOC Terminals

**ISRO Challenge - Problem Statement ID 26169**

A real-time simulation and autonomous beam-pointing system for Free-Space Optical Communication (FSOC) terminals mounted on mobile platforms (ships, vehicles, UAVs). The system demonstrates a complete closed-loop pipeline: scene rendering, beacon detection, AI classification, modulation-based identification, state estimation, and gimbal servo control — all running at 30–59 fps on commodity hardware, with a Benchmark-2 MP4 bypass for grader-supplied videos.

---

## Quick Start

```bash
# Install dependencies
pip install pygame-ce opencv-python numpy

# Run the mission-console GUI
python main.py

# Run headless stress test
python -m metrics.stress_test --trials 3 --seconds 15

# Run the acquire → lose → coast → reacquire recovery demo (ideal for a judging panel)
python -m metrics.scenario_demo --preset MODERATE --inject occlude

# Benchmark a grader-supplied MP4 (Benchmark-2 bypass)
python -m metrics.mp4_bypass -i path/to/video.mp4

# Generate a synthetic benchmark video with selectable noise (gaussian / salt_pepper / poisson)
python -m metrics.synthetic_video --out logs/classB.mp4 --noise gaussian,salt_pepper

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
│   ├── core/disturbances.py  Turbulence, vibration, sensor noise, sky background,
│   │                      beacon fade; each control carries a physical-unit hint
│   ├── core/detection.py  Gaussian blob detection + ML logistic-regression classifier
│   ├── core/tracking.py   State machine (SEARCHING → TENTATIVE → LOCKED → COASTING)
│   │                      Phase-robust modulation correlator, suspect-floor verifier
│   ├── core/gimbal.py     PD position servo with latency FIFO (2-frame pipeline)
│   └── core/control.py    Gimbal attitude command bridge
├── ai/classifier.py       Baked logistic-regression weights (96% train / 97% val)
├── ai/train_classifier.py Training pipeline (synthetic + augmented features)
├── metrics/performance.py CSV logging, live stats (acquisition, retention, error, reacquisition, false-lock)
├── metrics/stress_test.py Multi-trial headless benchmark harness
├── metrics/scenario_demo.py Scripted acquire/lose/coast/reacquire recovery demo
└── config.py              All tunables, difficulty presets, servo parameters
```

### Core Tracking Pipeline

1. **Scene rendering** — PS virtual-scene semantics: the world is a configurable 2000×2000 "screen" canvas; the pan-tilt camera (640×480, 4°×3° — the PS defaults) starts at the canvas centre and views it through a moving viewport crop. A 15 Hz amplitude-modulated beacon, distractors, obstacles, atmospheric turbulence and platform vibration are stamped into the crop.
2. **Detection** — A 3×3 median pre-filter kills salt-and-pepper spikes before they can fuse (via morphological close) into saturation regions; a top-hat local-background subtraction then yields candidate blobs. Each candidate is scored by an ML logistic-regression classifier (appearance, SNR, area, circularity).
3. **Modulation identification** — Phase-robust sign-agreement correlator tests candidates against the known 15 Hz modulation signature over a sliding 18-frame window, maximizing over 0–2 frame lag hypotheses.
4. **Acquisition gating** — Candidates must pass the ML appearance bar AND the ephemeris prior gate; a tentative track requires spatial consistency for 3 frames (speed-tolerant jitter budget) AND modulation correlation ≥ 0.62 before LOCKED is committed.
5. **Continuous verification** — While LOCKED, a suspect-floor monitor (corr < 0.58 for 12 consecutive frames) drops a wrong-target track back to SEARCHING.
6. **Sub-pixel centroiding** — The stuck target is centroided over the pixels inside the beacon's angular core radius around the blob's intensity centroid, giving sub-pixel LoS accuracy while clipping the glow halo and decoy/occlusion mass that drags full-blob centroids off-target.
7. **State estimation** — Ephemeris prior + velocity-adaptive leaky bias (α = 0.35, gain-to-0.85 under fast motion) plus measured-velocity feedforward produces smooth, low-latency boresight commands.
8. **Gimbal servo** — PD position controller (Kp = 25, Kd = 10) with slew-rate limiting (5°/s — the PS default; user-range 5–10), acceleration clamping (14°/s²), and 2-frame latency FIFO.

---

## Performance Summary

Synthetic-mode results below come from headless runs of **3 seeds × 450 frames × 5 presets** at 30 Hz with the full closed loop (deterministic seeds; identical-binary results across restarts). The camera is the PS default 640×480 @ 4°×3°, so **160 px/°** and the ≤ 10 px tracking spec ≈ 0.0625°. *est err* is the tracker LoS estimate error — the honest CV metric; *pointing err* is the k* gimbal boresight residual (encoder truth vs pointing LOS), bounded on SEVERE by the physics of the 5°/s slew (PS default) and 2-frame latency rather than by the algorithm. *False-lock strikes* counts frames where the tracker is LOCKED with est err > 0.35°.

| Preset | Acquire (s) | Retain (post-lock) | Est err mean | Point err mean | Strike frames | FPS |
|--------|------------|--------------------|--------------|----------------|---------------|-----|
| **EASY** | 0.47 | 100% | 0.013° (2.1 px) | 0.026° (4.2 px) | 0 | 58–59 |
| **MODERATE** | 0.47–0.93 | 96.8–100% | 0.013° (2.1 px); s2 wrong-lock tail 0.114° | 0.019–0.123° | 0–86 | 52–53 |
| **HARD** | 0.47–0.93 | 100% | 0.015–0.017° (2.4–2.7 px) | 0.027–0.040° | 0 | 32 |
| **SEVERE** | 0.80–1.20 | 96.6–100% | 0.098–0.158° (16–25 px, occlusion episodes) | 0.244–0.302° | 19–60 | 31 |
| **ADVERSARIAL** | 0.47–0.93 | 100% | 0.028–0.032° (4.6–5.1 px) | 0.047–0.053° | 0–1 | 31 |

**Key results**
- EASY/HARD/ADVERSARIAL sustain **100% post-lock retention** in every seed and stay **2–5 px** of the true beacon — an order of magnitude inside the ≤ 10 px spec. The only tails are MODERATE seed-2 (a decoy wrong-lock episode, self-recovered via the suspect-floor monitor) and the beyond-design-basis SEVERE preset.
- Real-time ≥ 20 fps holds on the **worst** preset (30.6 fps on ADVERSARIAL/SEVERE, 58 on EASY) — at the PS's own 640×480 camera.

**Benchmark-2 MP4 bypass** (grader-supplied videos, figure-eight 30 Hz synth, 640×480): after a 3×3 median pre-filter against salt-and-pepper, both a Gaussian-only and a 10 % salt-and-pepper MP4 track the true beacon with sub-2 px error, 0 false locks, and instant (< 0.15 s) acquisition:

| Video | Err mean (px) | p95 (px) | Max (px) | Retention | False locks |
|-------|--------------|----------|----------|-----------|-------------|
| Gaussian-only | 0.62 | 1.10 | 1.57 | 99.7% | 0 |
| 10 % salt-and-pepper | 0.78 | 1.48 | 2.18 | 99.7% | 0 |

---

## Difficulty Presets

| Parameter | EASY | MODERATE | HARD | SEVERE | ADVERSARIAL |
|-----------|------|----------|------|--------|-------------|
| Turbulence | 5 | 20 | 40 | 65 | 85 |
| Vibration | 2 | 8 | 18 | 32 | 45 |
| Sensor noise | 5 | 10 | 18 | 28 | 38 |
| Platform jerk (%) | 0 | 1 | 3 | 6 | 9 |
| Beacon fade (%) | 0 | 10 | 30 | 45 | 60 |
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
| Real-time coarse pointing | Closed-loop 30–59 fps pipeline |
| Mobile platform compensation | Relative orbital model + disturbance engine |
| Robust beacon tracking | Multi-stage acquisition: ML + modulation + spatial consistency |
| Low residual error | 2 px mean (EASY), sub-2 px on Benchmark-2 MP4s |
| Disturbance rejection | Tuned PD servo with latency compensation |
| Edge-deployable | Pure Python, no GPU required |

---

## License

Developed for the ISRO SIH 2026 challenge.
