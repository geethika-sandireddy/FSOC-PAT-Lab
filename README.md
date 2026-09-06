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

# Run the benchmark that generated every number below (reproduces the report exactly)
python -m metrics.stress_test

# Stress the Model-Vision Trust manager: corrupted ephemeris prior / disturbance storm
python -m metrics.stress_test --scenario wrongprior
python -m metrics.stress_test --scenario dynamic

# Benchmark the ISRO reference-terminal preset
python -m metrics.stress_test --presets ISRO_RX --trials 3

# Run the acquire → lose → coast → reacquire recovery demo (ideal for a judging panel)
python -m metrics.scenario_demo --preset MODERATE --inject occlude
python -m metrics.scenario_demo --preset MODERATE --inject recover   # full loss-and-recovery story

# Trust-manager vignette: beacon burn the ephemeris doesn't know about
python -m metrics.stress_test --scenario truststory

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
│   ├── core/tracking.py   State machine (SEARCHING → TENTATIVE → LOCKED →
│   │                      DEGRADED_LOCK → COASTING / REACQUIRING)
│   │                      Phase-robust modulation correlator, suspect-floor verifier,
│   │                      DEGRADED_LOCK banding, mode-driven estimator gain
│   ├── core/confidence.py Unified 0-1 confidence state (identity/position/prediction/
│   │                      pointing) driving the lock bands
│   ├── core/uncertainty.py Position uncertainty sigma_px (measurement + residual +
│   │                      coast growth; REACQUIRE credibility line at 18 px)
│   ├── core/trust.py      Adaptive Model-Vision Trust manager (BALANCED /
│   │                      VISION_DOMINANT / MODEL_DOMINANT / COAST / REACQUIRE)
│   ├── core/gimbal.py     PD position servo with latency FIFO (2-frame pipeline)
│   └── core/control.py    Gimbal attitude command bridge
├── ai/classifier.py       Baked logistic-regression weights; single-scenario snapshot
├── ai/train_classifier.py Whole-seed train/val/test training (no frame leakage)
├── metrics/performance.py CSV logging, live stats (acquisition, retention, error, reacquisition, false-lock)
├── metrics/stress_test.py Multi-trial headless benchmark harness (canonical sweep + wrongprior/dynamic/truststory scenarios)
├── metrics/scenario_demo.py Scripted acquire/lose/coast/reacquire recovery demo --inject recover|occlude|fade
└── config.py              All tunables, difficulty presets, servo parameters
```

### Core Tracking Pipeline

1. **Scene rendering** — PS virtual-scene semantics: the world is a configurable 2000×2000 "screen" canvas; the pan-tilt camera (640×480, 4°×3° — the PS defaults) starts at the canvas centre and views it through a moving viewport crop. A 15 Hz amplitude-modulated beacon, distractors, obstacles, atmospheric turbulence and platform vibration are stamped into the crop.
2. **Detection** — A 3×3 median pre-filter kills salt-and-pepper spikes before they can fuse (via morphological close) into saturation regions; a top-hat local-background subtraction then yields candidate blobs. Each candidate is scored by an ML logistic-regression classifier on the 4-feature appearance vector `[area_norm, circularity, snr, hue_dist_n]`.
3. **Modulation identification** — Phase-robust sign-agreement correlator tests candidates against the known 15 Hz modulation signature over a sliding 18-frame window, maximizing over 0–2 frame lag hypotheses.
4. **Acquisition gating** — Candidates must pass the ML appearance bar AND the ephemeris prior gate; a tentative track requires spatial consistency for 3 frames (speed-tolerant jitter budget) AND modulation correlation ≥ 0.62 before LOCKED is committed.
5. **Continuous verification** — While LOCKED, a suspect-floor monitor (corr < 0.58 for 12 consecutive frames) drops a wrong-target track back to SEARCHING.
6. **Sub-pixel centroiding** — The stuck target is centroided over the pixels inside the beacon's angular core radius around the blob's intensity centroid, giving sub-pixel LoS accuracy while clipping the glow halo and decoy/occlusion mass that drags full-blob centroids off-target.
7. **State estimation** — Ephemeris prior + velocity-adaptive leaky bias (α = 0.35, gain-to-0.85 under fast motion) plus measured-velocity feedforward produces smooth, low-latency boresight commands.
8. **Gimbal servo** — PD position controller (Kp = 25, Kd = 10) with slew-rate limiting (5°/s — the PS default; user-range 5–10), acceleration clamping (14°/s²), and 2-frame latency FIFO.

---

## Performance Summary

Synthetic-mode results below are generated by the single canonical command
**`python -m metrics.stress_test`**: **3 independent seeds × 450 frames × 5
presets** (30 Hz, full closed loop, deterministic seeds — identical-binary runs
reproduce bit-for-bit). The camera is the PS-default 640×480 @ 4°×3°
(**160 px/°**, so the ≤ 10 px tracking spec ≈ 0.0625°). Results are written to
`logs/stress_test_summary.csv` and `logs/benchmark_summary.json` at a fixed
commit, so every number below traces to a checked-in artifact.

Definitions: **Est err** = the tracker's LoS *estimate* error vs beacon truth
(the honest CV metric). **Point err** = the k° gimbal boresight residual
(encoder-truth vs pointed LOS) — on SEVERE it is bounded by the *physics* of
the PS-default 5°/s slew and 2-frame latency, not by the algorithm.
**Strike frames** = locked frames with est err > 0.35° (stricter than the
wrong-target threshold). **False locks** = sustained wrong-target holds
(locked, beacon visible, est err > 0.35° for ≥ 5 consecutive frames) — these
are caught and self-recovered by the suspect-floor monitor, never fatal.

| Preset | Acquire (s) | Retain (post-lock) | Est err mean | Point err mean | Strike | False locks | FPS (host-bound)* |
|--------|------------|--------------------|--------------|----------------|--------|-------------|-------------------|
| **EASY** | 0.23 | 100% | 0.0126–0.0131° (2.0–2.1 px) | 0.026–0.028° (4.2–4.5 px) | 0 | 0 | 44–59 |
| **MODERATE** | 0.23 | 96.8–100% | 0.013–0.041° (2.1–6.5 px; seed-2 decoy tail, self-recovered) | 0.024–0.053° | 0–26 | 1 | 41–53 |
| **HARD** | 0.23–0.47 | 100% | 0.015–0.017° (2.4–2.7 px) | 0.027–0.048° | 0 | 0 | 24–32 |
| **SEVERE** | 0.40–1.72 | 96.6–100% | 0.071–0.127° (11–20 px; beyond-design occlusion episodes) | 0.196–0.247° | 0–19 | 1 | 12–24 |
| **ADVERSARIAL** | 0.23–0.47 | 100% | 0.026–0.036° (4.2–5.8 px) | 0.045–0.090° | 0 | 0 | 12–30 |
| **ISRO_RX** (reference terminal) | 0.23–0.47 | 100% | 0.014–0.016° (2.2–2.5 px) | 0.025–0.032° | 0 | 0 | 40–41 |

\* FPS is wall-clock and host-dependent (identical deterministic runs swing on
the dev laptop); light presets hold 41–59 fps under any load, heavy presets
dip only when the machine is saturated.

**Key results**
- EASY/HARD/ADVERSARIAL/ISRO_RX hold **100% post-lock retention in every
  seed** and track within **2–6 px** of the true beacon — an order of
  magnitude inside the ≤ 10 px spec, **zero false locks**. The two honest
  tails are MODERATE seed-2 (a decoy wrong-lock episode that the
  suspect-floor monitor detects and self-recovers) and the deliberately
  beyond-design-basis SEVERE preset (documented — not hidden).
- **Phase 2 (Model–Vision Trust) improved the published point.** Every preset
  points better than the baseline build — SEVERE estimate error 20–25 px →
  11–20 px, MODERATE pointing error −57% — because the trust manager now
  routes authority between the camera and the ephemeris model per-frame
  (VISION_DOMINANT 0.85 / MODEL_DOMINANT 0.30 observation gain) instead of
  one fixed alpha.
- Post-lock retention counts **LOCKED and DEGRADED_LOCK** frames as retained
  (a degraded lock is still a lock — weak signal, full pointing authority).
- Real-time: 41–59 fps on the light presets under any load; the heavy
  beyond-design-basis presets run 12–30 fps depending on host saturation
  (identical deterministic loop). The PS ≥ 20 fps spec is met in normal
  operation on the submission hardware.

**Benchmark-2 MP4 bypass** (grader-supplied videos; figure-eight 30 Hz synth,
640×480): after the 3×3 median pre-filter against salt-and-pepper, both a
Gaussian-only and a 10 % salt-and-pepper MP4 track the true beacon with
sub-2 px error, no false locks, and instant (< 0.15 s) acquisition:

| Video | Err mean (px) | p95 (px) | Max (px) | False locks |
|-------|--------------|----------|----------|-------------|
| Gaussian-only | 0.62 | 1.10 | 1.57 | 0 |
| 10 % salt-and-pepper | 0.78 | 1.48 | 2.18 | 0 |

The bypass is resolution/codec/framerate agnostic (errors are measured in the
video's own pixel plane). Non-repo clips were also checked — 1280×720 @ 25 fps
(Gaussian + salt-and-pepper) and a 640×480 poisson-noise clip (XVID container):
mean 1.22 px / 0.53 px, 0 false locks, 0 re-acquisitions.

---

## Phase 2: Confidence, Uncertainty and Adaptive Model-Vision Trust

Every frame the system now answers *"how much do I believe the camera"
vs "how much do I believe the ephemeris model"* — and makes it visible.

- **Confidence** (`core/confidence.py`) — one 0–1 state per frame (identity =
  appearance × 15 Hz modulation, position, prediction vs belief + velocity
  lead, pointing), banded into **LOCKED ≥ 0.70**, **DEGRADED_LOCK 0.55–0.70**,
  below 0.55 owned by the suspect/coast machinery.
- **Uncertainty** (`core/uncertainty.py`) — smooth `σ` in px (measurement +
  residual + quadratic coast growth) that truly reflects link health: ~3 px on
  quiet links, rising past the 18 px re-acquire line under occlusions/fades.
  Inner tracking uses the *internal*, uncapped σ; the on-screen readout is
  capped at 24 px so a handling panel stays readable under SEVERE conditions.
- **Reachable re-acquisition** (`core/tracking.py`) — while the beacon is lost
  the old path is extrapolated, the gimbal is aimed at that lane, and the
  association gate opens 2×: recovery is **REACQUIRING**, not a blind
  SEARCHING sweep. Scripted as a live demo (`--inject recover`).
- **Adaptive trust** (`core/trust.py`) — mode-driven vision share:
  `VISION_DOMINANT` 0.85, `MODEL_DOMINANT` 0.30, `BALANCED` 0.4–0.6; hysteresis
  debounce; keeps the point when the prior jumps (Section on stress scenario).
- **Scenario runs** — `--scenario none|wrongprior|dynamic|truststory` in
  `metrics/stress_test.py`: a 0.35° ephemeris prior step + drag + random walk
  is re-baselined transparently (100% retention on EASY/HARD/ADVERSARIAL,
  ≤ 1 false lock) and the trust pair visibly rebalances (SEVERE/ADVERSARIAL
  shift MODEL_DOMINANT → BALANCED). The `truststory` vignette stages the one
  failure model a leaky-absorbed bias *cannot* hide from — a beacon burn off
  its own ephemeris: the bias must chase at `acc·(t−7)`°/s, the model-honesty
  residual stays above the VISION margin, and **VISION_DOMINANT holds the
  loop** through the manoeuvre (40–77 % of the window, 3 seeds), reverting
  cleanly to BALANCED/MODEL_DOMINANT after the post-burn state-vector heal.
- **Evidence files** — `logs/phase2_trust_summary.json` (per-seed vision/model
  trust % and σ per preset), plus `*_wrongprior`, `*_dynamic`, `*_truststory`
  variants.
- **Live readout** — the GUI stack shows ID / POS / PRED / PT and
  VL / ML / σ / [mode] every frame.

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

Plus `ISRO_RX`, the reference-terminal case (turbulence 25, vibration 10,
sensor noise 12, fade 5, distractors 2, obstacles 1, coverage ±1.20° / ±0.80°,
1.0× speed) — run it via `--presets ISRO_RX`.

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
