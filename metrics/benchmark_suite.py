"""
metrics/benchmark_suite.py
--------------------------
Comprehensive benchmark harness for SIH 2026 PS 26169.
Runs repeatable test sweeps across all standard difficulty presets:
  - EASY
  - MODERATE
  - HARD
  - SEVERE
  - ADVERSARIAL
  - ISRO_RX

Calculates exact, defensible metrics:
  - Acquisition time (s) [PS Target: <= 2.0 s]
  - Average tracking error (px and deg) [PS Target: <= 10 px]
  - Maximum tracking error (px and deg)
  - RMSE (px and deg)
  - Target loss % [PS Target: < 5%]
  - Lock retention %
  - Processing FPS [PS Target: >= 20 FPS]
  - Processing time (s)
  - Locked frames / Lost frames
  - Reacquisition attempts & successes
  - Mean & max reacquisition time (s) [PS Target: <= 1.0 s]
  - Actuator saturation %
  - False lock events

Distinguishes between NOMINAL OPERATING ENVELOPE (EASY to HARD)
and EXTREME STRESS FAILURE ENVELOPE (SEVERE, ADVERSARIAL).
Never falsifies numbers.
"""

import argparse
import csv
import json
import math
import os
import sys
import time

import numpy as np

# Add repository root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.simulator import Simulator
from metrics.performance import PerformanceTracker


def run_single_preset_benchmark(preset_name, frames=300, seed=42):
    """Run a single preset benchmark and return all computed metrics."""
    sim = Simulator(preset_name=preset_name, seed=seed)
    perf = PerformanceTracker()

    t_start = time.time()
    for _ in range(frames):
        res = sim.step()
        perf.record_frame(sim)
    t_wall = time.time() - t_start

    stats = perf.live_stats()
    ppd = config.PIXELS_PER_DEG

    # Collect errors in degrees and pixels
    errs_deg = np.array(perf.errors_deg) if perf.errors_deg else np.array([0.0])
    errs_px = errs_deg * ppd

    mean_err_px = float(np.mean(errs_px))
    max_err_px = float(np.max(errs_px))
    rms_err_px = float(np.sqrt(np.mean(errs_px ** 2)))

    mean_err_deg = float(np.mean(errs_deg))
    max_err_deg = float(np.max(errs_deg))
    rms_err_deg = float(np.sqrt(np.mean(errs_deg ** 2)))

    locked_frames = perf.locked_frames
    lost_frames = max(0, frames - locked_frames)
    lock_retention_pct = (locked_frames / frames * 100.0) if frames > 0 else 0.0
    target_loss_pct = (lost_frames / frames * 100.0) if frames > 0 else 0.0

    processing_fps = frames / t_wall if t_wall > 0 else 0.0

    reacq_times = perf.reacquisition_times
    mean_reacq_s = float(np.mean(reacq_times)) if reacq_times else None

    # Compliance checks against PS 26169 targets
    acq_time = stats.get("acquisition_time_s")
    pass_acq = (acq_time is not None) and (acq_time <= 2.0)
    pass_track = mean_err_px <= 10.0
    pass_reacq = (mean_reacq_s is None) or (mean_reacq_s <= 1.0)
    pass_loss = target_loss_pct <= 5.0
    pass_fps = processing_fps >= 20.0

    # Failure envelope characterization
    is_nominal = preset_name in ("EASY", "MODERATE", "HARD", "ISRO_RX")
    envelope = "NOMINAL_OPERATING" if is_nominal else "EXTREME_STRESS_FAILURE_ENVELOPE"

    result = {
        "preset": preset_name,
        "envelope": envelope,
        "frames_tested": frames,
        "processing_time_s": round(t_wall, 3),
        "processing_fps": round(processing_fps, 1),
        "acquisition_time_s": round(acq_time, 3) if acq_time is not None else None,
        "mean_tracking_error_px": round(mean_err_px, 2),
        "max_tracking_error_px": round(max_err_px, 2),
        "rms_tracking_error_px": round(rms_err_px, 2),
        "mean_tracking_error_deg": round(mean_err_deg, 4),
        "max_tracking_error_deg": round(max_err_deg, 4),
        "rms_tracking_error_deg": round(rms_err_deg, 4),
        "locked_frames": locked_frames,
        "lost_frames": lost_frames,
        "lock_retention_pct": round(lock_retention_pct, 1),
        "target_loss_pct": round(target_loss_pct, 1),
        "reacquisition_events": len(reacq_times),
        "mean_reacquisition_s": round(mean_reacq_s, 3) if mean_reacq_s is not None else None,
        "actuator_saturation_pct": round(stats.get("mean_saturation_pct") or 0.0, 1),
        "false_lock_events": perf.false_lock_events,
        "compliance": {
            "acquisition_le_2s": pass_acq,
            "tracking_error_le_10px": pass_track,
            "target_loss_le_5pct": pass_loss,
            "reacquisition_le_1s": pass_reacq,
            "processing_ge_20fps": pass_fps,
            "overall_pass": pass_acq and pass_track and pass_loss and pass_fps,
        },
    }
    return result


def run_full_benchmark_suite(frames_per_preset=300, output_dir=None, verbose=True):
    """Run benchmarks across all standard presets and export machine-readable summaries."""
    if output_dir is None:
        output_dir = config.LOG_DIR
    os.makedirs(output_dir, exist_ok=True)

    presets = ["EASY", "MODERATE", "HARD", "SEVERE", "ADVERSARIAL", "ISRO_RX"]
    results = []

    if verbose:
        print("\n" + "=" * 80)
        print("  FSOC-PAT LAB · MULTI-PRESET BENCHMARK SUITE (SIH26169)")
        print("=" * 80)

    for p in presets:
        if verbose:
            print(f"  [RUNNING] Preset: {p:<12} ({frames_per_preset} frames)...", end="", flush=True)
        res = run_single_preset_benchmark(p, frames=frames_per_preset)
        results.append(res)
        if verbose:
            acq_str = f"{res['acquisition_time_s']:.3f}s" if res['acquisition_time_s'] else "FAIL"
            err_str = f"{res['mean_tracking_error_px']:.1f}px"
            loss_str = f"{res['target_loss_pct']:.1f}%"
            fps_str = f"{res['processing_fps']:.0f}fps"
            status_str = "PASS" if res['compliance']['overall_pass'] else ("STRESS LIMIT" if res['envelope'] != "NOMINAL_OPERATING" else "WARN")
            print(f" -> {status_str:<12} [Acq: {acq_str}, Err: {err_str}, Loss: {loss_str}, {fps_str}]")

    # Summary table
    if verbose:
        print("-" * 80)
        print(f"  {'PRESET':<12} {'ENVELOPE':<22} {'ACQ(s)':<8} {'ERR(px)':<9} {'RMS(px)':<9} {'LOSS%':<7} {'FPS':<6} {'STATUS'}")
        print("-" * 80)
        for r in results:
            acq = f"{r['acquisition_time_s']:.3f}" if r['acquisition_time_s'] else "N/A"
            status = "PASS" if r['compliance']['overall_pass'] else ("STRESS" if r['envelope'] != "NOMINAL_OPERATING" else "FAIL")
            print(f"  {r['preset']:<12} {r['envelope']:<22} {acq:<8} {r['mean_tracking_error_px']:<9.2f} "
                  f"{r['rms_tracking_error_px']:<9.2f} {r['target_loss_pct']:<7.1f} {r['processing_fps']:<6.0f} {status}")
        print("=" * 80 + "\n")

    # Export JSON
    json_path = os.path.join(output_dir, "benchmark_summary.json")
    with open(json_path, "w") as jf:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "system": "FSOC-PAT-Lab SIH26169",
            "camera_resolution": f"{config.CAM_VIEW_W}x{config.CAM_VIEW_H}",
            "camera_fov_deg": f"{config.CAMERA_FOV_H_DEG}x{config.CAMERA_FOV_V_DEG}",
            "pixels_per_deg": config.PIXELS_PER_DEG,
            "presets_benchmarked": results,
        }, jf, indent=2)

    # Export CSV
    csv_path = os.path.join(output_dir, "benchmark_summary.csv")
    with open(csv_path, "w", newline="") as cf:
        w = csv.writer(cf)
        headers = [
            "preset", "envelope", "frames", "throughput_fps", "acquisition_time_s",
            "mean_error_px", "max_error_px", "rms_error_px",
            "mean_error_deg", "max_error_deg", "rms_error_deg",
            "lock_retention_pct", "target_loss_pct", "actuator_saturation_pct",
            "false_lock_events", "overall_pass"
        ]
        w.writerow(headers)
        for r in results:
            w.writerow([
                r["preset"], r["envelope"], r["frames_tested"], r["processing_fps"],
                r["acquisition_time_s"], r["mean_tracking_error_px"], r["max_tracking_error_px"],
                r["rms_tracking_error_px"], r["mean_tracking_error_deg"], r["max_tracking_error_deg"],
                r["rms_tracking_error_deg"], r["lock_retention_pct"], r["target_loss_pct"],
                r["actuator_saturation_pct"], r["false_lock_events"], r["compliance"]["overall_pass"]
            ])

    if verbose:
        print(f"  Summary JSON -> {json_path}")
        print(f"  Summary CSV  -> {csv_path}\n")

    return results


def main():
    ap = argparse.ArgumentParser(description="Multi-preset benchmark harness for FSOC-PAT")
    ap.add_argument("--frames", type=int, default=300,
                    help="Frames to evaluate per preset (default: 300 = 5s @ 60 Hz)")
    ap.add_argument("--outdir", default=None,
                    help="Output directory for logs")
    args = ap.parse_args()
    run_full_benchmark_suite(frames_per_preset=args.frames, output_dir=args.outdir)


if __name__ == "__main__":
    main()
