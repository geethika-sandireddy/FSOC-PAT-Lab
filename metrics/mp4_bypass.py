"""
metrics/mp4_bypass.py
---------------------
PTZ-camera bypass (Benchmark-2 of PS 26169): takes an evaluator-supplied .mp4 video
file as the camera input instead of the virtual scene, pushes each frame through
the *real* detection -> tracking -> control pipeline (core.simulator.VideoInputSimulator),
and produces the mandatory technical performance report.

CRITICAL METRIC SEPARATION (PS 26169 Compliant):
- Metric A: Detected Centroid (x, y)
- Metric B: Optical-Axis / Frame-Centre Offset = distance(detected centroid, frame centre (W/2, H/2))
- Metric C: True Centroiding Error = distance(detected centroid, ground-truth target centroid)
  * ONLY Metric C may be called "True Centroiding Error".
  * If the evaluator MP4 has no ground truth sidecar CSV, the report explicitly states:
    "GROUND TRUTH: NOT AVAILABLE" and logs "FRAME-CENTRE OFFSET" / "OPTICAL-AXIS OFFSET".

GROUND TRUTH FLAG:
Benchmark logs explicitly state:
GROUND_TRUTH_AVAILABLE = YES / NO

Usage:
    python -m metrics.mp4_bypass --input video.mp4
    python -m metrics.mp4_bypass --input video.mp4 --output logs/report.csv
"""

import argparse
import csv
import json
import math
import os
import time

import numpy as np

import config
from core.simulator import VideoInputSimulator


def run_bypass(input_path, output_path=None, truth_path=None, verbose=True):
    """Process an MP4 through the real coarse-pointing loop."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    # Check for truth CSV sidecar: explicit parameter or <video>_truth.csv
    truth_csv = truth_path
    if not truth_csv:
        cand = os.path.splitext(input_path)[0] + "_truth.csv"
        if os.path.isfile(cand):
            truth_csv = cand

    sim = VideoInputSimulator(input_path, truth_csv=truth_csv)
    gt_available = sim.ground_truth_available

    t0 = time.time()
    while True:
        res = sim.step()
        if res is None:
            break
    wall = time.time() - t0

    total_frames = sim.total_frames
    processed_frames = sim.frame_idx
    fps_proc = processed_frames / wall if wall > 0 else 0.0

    locked_frames = sim.locked_frames
    lost_frames = sim.lost_frames
    lock_retention_pct = (locked_frames / processed_frames * 100.0) if processed_frames > 0 else 0.0
    target_loss_pct = (lost_frames / processed_frames * 100.0) if processed_frames > 0 else 0.0

    # Metric B: Optical-axis / Frame-centre offset
    optical_offsets_px = np.array([e[1] for e in sim.optical_offset_log if e[1] is not None])
    optical_offsets_deg = np.array([e[2] for e in sim.optical_offset_log if e[2] is not None])

    # Metric C: True centroiding error (only if GT available)
    if gt_available and len(sim.true_err_log) > 0:
        true_errs_px = np.array([e[1] for e in sim.true_err_log if e[1] is not None])
        true_errs_deg = np.array([e[2] for e in sim.true_err_log if e[2] is not None])
    else:
        true_errs_px = np.array([])
        true_errs_deg = np.array([])

    reacq_times = sim.reacq_times
    mean_reacq = float(np.mean(reacq_times)) if len(reacq_times) > 0 else None
    max_reacq = float(np.max(reacq_times)) if len(reacq_times) > 0 else None

    # Compile structured results dictionary
    stats = {
        "ground_truth_available": "YES" if gt_available else "NO",
        "input_file": os.path.basename(input_path),
        "video_resolution": f"{sim.video_w}x{sim.video_h}",
        "video_fps": float(sim.video_fps),
        "video_duration_s": float(total_frames / sim.video_fps) if sim.video_fps > 0 else 0.0,
        "total_frames": total_frames,
        "processed_frames": processed_frames,
        "processing_time_s": float(wall),
        "processing_fps": float(fps_proc),
        "acquisition_time_s": float(sim.acquisition_time_s) if sim.acquisition_time_s is not None else None,
        "locked_frames": locked_frames,
        "lost_frames": lost_frames,
        "lock_retention_pct": float(lock_retention_pct),
        "target_loss_pct": float(target_loss_pct),
        "reacquisition_attempts": sim.reacq_attempts,
        "successful_reacquisitions": sim.reacq_successes,
        "mean_reacquisition_time_s": mean_reacq,
        "max_reacquisition_time_s": max_reacq,
        "false_lock_events": sim.false_lock_events,
        # Metric B: Frame-Centre / Optical-Axis Offset
        "optical_axis_offset_mean_px": float(np.mean(optical_offsets_px)) if optical_offsets_px.size else 0.0,
        "optical_axis_offset_rms_px": float(np.sqrt(np.mean(optical_offsets_px ** 2))) if optical_offsets_px.size else 0.0,
        "optical_axis_offset_max_px": float(np.max(optical_offsets_px)) if optical_offsets_px.size else 0.0,
        "optical_axis_offset_mean_deg": float(np.mean(optical_offsets_deg)) if optical_offsets_deg.size else 0.0,
        "optical_axis_offset_max_deg": float(np.max(optical_offsets_deg)) if optical_offsets_deg.size else 0.0,
        # Metric C: True Centroid Error (Explicitly N/A if no GT)
        "true_centroid_error_mean_px": float(np.mean(true_errs_px)) if true_errs_px.size else None,
        "true_centroid_error_rms_px": float(np.sqrt(np.mean(true_errs_px ** 2))) if true_errs_px.size else None,
        "true_centroid_error_max_px": float(np.max(true_errs_px)) if true_errs_px.size else None,
        "true_centroid_error_mean_deg": float(np.mean(true_errs_deg)) if true_errs_deg.size else None,
        "true_centroid_error_max_deg": float(np.max(true_errs_deg)) if true_errs_deg.size else None,
    }

    if verbose:
        print(f"\n{'='*70}")
        print(f"  FSOC-PAT BENCHMARK-2 EVALUATION REPORT  ::  {os.path.basename(input_path)}")
        print(f"{'='*70}")
        print(f"  GROUND_TRUTH_AVAILABLE: {stats['ground_truth_available']}")
        if not gt_available:
            print("  [NOTE] Evaluator video has no ground-truth sidecar CSV.")
            print("         Offset from image centre is reported as OPTICAL-AXIS OFFSET.")
            print("         True centroiding error is marked N/A per PS evaluation standards.")
        print(f"  Video: {sim.video_w}x{sim.video_h} @ {sim.video_fps:.1f} FPS, "
              f"{total_frames} frames ({stats['video_duration_s']:.1f}s)")
        print(f"  Processing Time: {wall:.2f}s  |  Throughput: {fps_proc:.1f} FPS "
              f"({'PASS: >=20 FPS' if fps_proc >= 20.0 else 'WARN: <20 FPS'})")
        print(f"{'-'*70}")
        print(f"  Acquisition Time:          "
              f"{stats['acquisition_time_s']:.3f} s  "
              f"({'PASS: <=2.0s' if stats['acquisition_time_s'] and stats['acquisition_time_s'] <= 2.0 else 'FAIL'})"
              if stats["acquisition_time_s"] is not None
              else "  Acquisition Time:          NEVER LOCKED (FAIL)")
        print(f"  Lock Retention:            {lock_retention_pct:.1f}% ({locked_frames}/{processed_frames} frames)")
        print(f"  Target Loss:               {target_loss_pct:.1f}% "
              f"({'PASS: <5%' if target_loss_pct < 5.0 else 'HIGH LOSS'})")
        print(f"  Re-acquisitions:           {sim.reacq_successes}/{sim.reacq_attempts} successful"
              + (f"  (mean {mean_reacq:.3f} s, max {max_reacq:.3f} s)" if mean_reacq else " (no reacq events)"))
        print(f"{'-'*70}")
        print(f"  [METRIC B] OPTICAL-AXIS OFFSET (Frame Centre):")
        print(f"    Mean: {stats['optical_axis_offset_mean_px']:.2f} px ({stats['optical_axis_offset_mean_deg']:.4f}°)")
        print(f"    RMS:  {stats['optical_axis_offset_rms_px']:.2f} px")
        print(f"    Max:  {stats['optical_axis_offset_max_px']:.2f} px ({stats['optical_axis_offset_max_deg']:.4f}°)")

        print(f"  [METRIC C] TRUE CENTROIDING ERROR (vs Evaluator Ground Truth):")
        if gt_available and true_errs_px.size:
            print(f"    Mean: {stats['true_centroid_error_mean_px']:.2f} px ({stats['true_centroid_error_mean_deg']:.4f}°) "
                  f"({'PASS: <=10 px' if stats['true_centroid_error_mean_px'] <= 10.0 else 'FAIL'})")
            print(f"    RMS:  {stats['true_centroid_error_rms_px']:.2f} px")
            print(f"    Max:  {stats['true_centroid_error_max_px']:.2f} px ({stats['true_centroid_error_max_deg']:.4f}°)")
        else:
            print("    GROUND TRUTH: NOT AVAILABLE (True error cannot be calculated)")
        print(f"{'='*70}\n")

    # Generate output logs (CSV and JSON)
    if output_path is None:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        base = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(config.LOG_DIR, f"benchmark_{base}_{int(time.time())}.csv")

    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value", "unit"])
        w.writerow(["GROUND_TRUTH_AVAILABLE", stats["ground_truth_available"], "flag"])
        w.writerow(["input_file", stats["input_file"], "filename"])
        w.writerow(["video_resolution", stats["video_resolution"], "pixels"])
        w.writerow(["video_fps", round(stats["video_fps"], 2), "Hz"])
        w.writerow(["total_frames", stats["total_frames"], "frames"])
        w.writerow(["processed_frames", stats["processed_frames"], "frames"])
        w.writerow(["processing_fps", round(stats["processing_fps"], 2), "fps"])
        w.writerow(["processing_time_s", round(stats["processing_time_s"], 3), "seconds"])
        w.writerow(["acquisition_time_s", round(stats["acquisition_time_s"], 3) if stats["acquisition_time_s"] is not None else "never_locked", "seconds"])
        w.writerow(["lock_retention_pct", round(stats["lock_retention_pct"], 2), "%"])
        w.writerow(["target_loss_pct", round(stats["target_loss_pct"], 2), "%"])
        w.writerow(["locked_frames", stats["locked_frames"], "frames"])
        w.writerow(["lost_frames", stats["lost_frames"], "frames"])
        w.writerow(["reacquisition_attempts", stats["reacquisition_attempts"], "count"])
        w.writerow(["successful_reacquisitions", stats["successful_reacquisitions"], "count"])
        w.writerow(["mean_reacquisition_s", round(stats["mean_reacquisition_time_s"], 3) if stats["mean_reacquisition_time_s"] is not None else "n/a", "seconds"])
        w.writerow(["optical_axis_offset_mean_px", round(stats["optical_axis_offset_mean_px"], 2), "pixels"])
        w.writerow(["optical_axis_offset_rms_px", round(stats["optical_axis_offset_rms_px"], 2), "pixels"])
        w.writerow(["optical_axis_offset_max_px", round(stats["optical_axis_offset_max_px"], 2), "pixels"])
        w.writerow(["optical_axis_offset_mean_deg", round(stats["optical_axis_offset_mean_deg"], 4), "degrees"])
        w.writerow(["true_centroid_error_mean_px", round(stats["true_centroid_error_mean_px"], 2) if stats["true_centroid_error_mean_px"] is not None else "N/A", "pixels"])
        w.writerow(["true_centroid_error_rms_px", round(stats["true_centroid_error_rms_px"], 2) if stats["true_centroid_error_rms_px"] is not None else "N/A", "pixels"])
        w.writerow(["true_centroid_error_max_px", round(stats["true_centroid_error_max_px"], 2) if stats["true_centroid_error_max_px"] is not None else "N/A", "pixels"])
        w.writerow(["true_centroid_error_mean_deg", round(stats["true_centroid_error_mean_deg"], 4) if stats["true_centroid_error_mean_deg"] is not None else "N/A", "degrees"])

    json_path = os.path.splitext(output_path)[0] + ".json"
    with open(json_path, "w") as jf:
        json.dump(stats, jf, indent=2)

    if verbose:
        print(f"  CSV Report -> {output_path}")
        print(f"  JSON Report -> {json_path}\n")

    return stats


def main():
    ap = argparse.ArgumentParser(
        description="Benchmark-2: process MP4 through the real coarse-pointing loop")
    ap.add_argument("--input", "-i", required=True,
                    help="Path to input .mp4 video file")
    ap.add_argument("--truth", "-t", default=None,
                    help="Optional path to ground-truth CSV file (default: <input>_truth.csv)")
    ap.add_argument("--output", "-o", default=None,
                    help="Output CSV path (auto-generated if omitted)")
    args = ap.parse_args()
    run_bypass(args.input, args.output, truth_path=args.truth)


if __name__ == "__main__":
    main()