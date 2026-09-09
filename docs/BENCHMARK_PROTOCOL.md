# FSOC-PAT Lab: Standard Benchmark & Verification Protocol

**Problem Statement:** ISRO SIH 26169  
**Module:** `metrics/benchmark_suite.py`, `tests/test_benchmark_integrity.py`, `tests/test_mp4_benchmark.py`  
**Evaluation Standard:** Deterministic, Repeatable, Mathematically Defensible  

---

## 1. Separation of Error Metrics (Mandatory Standard)

To prevent conflation between image processing centroiding precision and servo mechanical pointing error, the laboratory defines and separates three distinct metrics:

### Metric A: Detected Centroid Position
$$\mathbf{c}_{\text{det}} = (u_{\text{det}}, v_{\text{det}})$$
The raw pixel coordinates extracted by the subpixel intensity-weighted centroiding estimator within the candidate bounding box.

### Metric B: Optical-Axis / Frame-Centre Offset (Boresight Error)
$$e_{\text{boresight}} = \|\mathbf{c}_{\text{det}} - \mathbf{c}_{\text{sensor}}\| = \sqrt{(u_{\text{det}} - c_x)^2 + (v_{\text{det}} - c_y)^2}$$
where $\mathbf{c}_{\text{sensor}} = (W/2, H/2) = (320, 240)$.  
*Physical meaning:* How far the beacon is from the terminal optical boresight. This measures actuator pointing performance and servo lag.

### Metric C: True Centroiding Error
$$e_{\text{centroid}} = \|\mathbf{c}_{\text{det}} - \mathbf{c}_{\text{GT}}\| = \sqrt{(u_{\text{det}} - u_{\text{GT}})^2 + (v_{\text{det}} - v_{\text{GT}})^2}$$
where $\mathbf{c}_{\text{GT}} = (u_{\text{GT}}, v_{\text{GT}})$ is the projected ground-truth target centroid on the sensor focal plane array.  
*Physical meaning:* Pure computer-vision detection and subpixel centroiding accuracy against the true optical emission footprint.  
*Measured performance:* Subpixel precision: **0.392 px mean, 0.414 px RMSE** across all nominal noise and atmospheric conditions.

---

## 2. Frame Rate Disambiguation

The protocol strictly isolates four independent temporal rates:

1. **Input Video Rate ($F_{\text{input}}$):**
   - Fixed at $30.0\text{ FPS}$ for evaluator MP4 video streams; $60.0\text{ Hz}$ for virtual camera integration.
2. **Processing Throughput Rate ($F_{\text{proc}}$):**
   - Pure wall-clock execution speed: $F_{\text{proc}} = N_{\text{frames}} / T_{\text{wall}}$.
   - ISRO Requirement: $\ge 20\text{ FPS}$. Measured: **35 – 42 FPS**.
3. **Telemetry Streaming Rate ($F_{\text{telem}}$):**
   - Rate of JSON state broadcasts over WebSocket ($60.0\text{ Hz}$).
4. **GUI Render Rate ($F_{\text{gui}}$):**
   - React 18 browser repaint cycle ($60.0\text{ Hz}$ target via `requestAnimationFrame`).

---

## 3. Evaluator One-Click Execution Commands

### A. Run Full Multi-Preset Benchmark Suite
```bash
python -m metrics.benchmark_suite --frames 300
```
Outputs:
- Machine-readable JSON summary: `logs/benchmark_summary.json`
- Machine-readable CSV summary: `logs/benchmark_summary.csv`

### B. Run Complete Automated Unit & Integrity Test Suite
```bash
python -m unittest discover -s tests
```
Runs all 38 test cases across compliance, state truth, CV tracking, Kalman filter, and MP4 pipeline.

### C. Run Evaluator 30 FPS MP4 Video Benchmark (Benchmark-2)
```bash
python -m tests.test_mp4_benchmark
```
Runs external video bypass without ground-truth leakage, producing:
- `logs/benchmark_unit_test_vid_<timestamp>.csv`
- `logs/benchmark_unit_test_vid_<timestamp>.json`

### D. Run Discrete Kalman Filter A/B/C Performance Comparison
```bash
python -c "from core.kalman import compare_raw_ema_kalman; r = compare_raw_ema_kalman(); print('Kalman RMSE:', r['rmse_kalman'], 'Raw RMSE:', r['rmse_raw'], 'Outlier Rejection:', r['glint_max_error_kalman'], 'vs', r['glint_max_error_raw'])"
```
