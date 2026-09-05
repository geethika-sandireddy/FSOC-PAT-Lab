"""
metrics/mp4_bypass.py
---------------------
PTZ-camera bypass (Benchmark-2 of PS 26169): takes a pre-recorded .mp4 video
file as the camera input instead of the virtual scene, pushes each frame
through the *real* detection -> tracking -> control pipeline
(core.simulator.VideoInputSimulator), and produces the mandatory
centroiding/performance report.

The graded metrics are computed against the generator's ground-truth sidecar
(``<video>_truth.csv``,  columns frame,t,bx,by) when present - those are the
"predefined error values" the judges compare against.  Without ground truth
the report still logs the system's own centroid + error from frame centre.

Usage:
    python -m metrics.mp4_bypass --input video.mp4                # summary
    python -m metrics.mp4_bypass --input video.mp4 --output log.csv
"""

import argparse
import csv
import os
import time

import numpy as np

import config
from core.simulator import VideoInputSimulator


def run_bypass(input_path, output_path=None, verbose=True):
    """Process an MP4 through the real coarse-pointing loop."""
    truth_csv = os.path.splitext(input_path)[0] + "_truth.csv"
    if not os.path.isfile(truth_csv):
        truth_csv = None

    sim = VideoInputSimulator(input_path, truth_csv=truth_csv)
    t0 = time.time()
    while True:
        res = sim.step()
        if res is None:
            break
    wall = time.time() - t0

    total_frames = sim.total_frames
    locked = [s for (_, s) in sim.lock_history].count("LOCKED")

    errs = np.array([e[1] for e in sim.centroid_err_log])
    locked_errs = np.array([
        e[1] for e in sim.centroid_err_log
        if sim.lock_history[e[0] - 1][1] == "LOCKED"]) if sim.lock_history \
        else errs

    stats = dict(
        fps=total_frames / wall if wall > 0 else 0.0,
        video_fps=sim.video_fps,
        width=sim.video_w,
        height=sim.video_h,
        total_frames=total_frames,
        acquisition_time_s=sim.acquisition_time_s,
        retention_total_pct=(locked / total_frames * 100) if total_frames else 0.0,
        centroid_mean_px=float(np.mean(errs)) if errs.size else 0.0,
        centroid_rms_px=float(np.sqrt(np.mean(errs ** 2))) if errs.size else 0.0,
        centroid_p95_px=float(np.percentile(errs, 95)) if errs.size else 0.0,
        centroid_max_px=float(np.max(errs)) if errs.size else 0.0,
        locked_centroid_mean_px=(
            float(np.mean(locked_errs)) if locked_errs.size else 0.0),
        locked_centroid_p95_px=(
            float(np.percentile(locked_errs, 95)) if locked_errs.size else 0.0),
        reacquisition_count=len(sim.reacq_times),
        mean_reacq_s=(float(np.mean(sim.reacq_times))
                      if sim.reacq_times else None),
        false_lock_events=sim.false_lock_events,
        used_ground_truth=truth_csv is not None,
    )

    if verbose:
        print(f"\n{'='*60}")
        print(f"  MP4 BYPASS (Benchmark-2)  ::  {os.path.basename(input_path)}")
        print(f"{'='*60}")
        print(f"  Video: {sim.video_w}x{sim.video_h} @ {sim.video_fps:.1f} fps, "
              f"{total_frames} frames ({total_frames/sim.video_fps:.1f}s)")
        print(f"  Ground truth: {'YES (' + os.path.basename(truth_csv) + ')'
              if truth_csv else 'not supplied (frame-centre error logged)'}")
        print(f"  Processing: {wall:.2f}s wall, {stats['fps']:.0f} fps")
        print(f"  {'-'*60}")
        print(f"  Acquisition time:        "
              f"{stats['acquisition_time_s']:.3f}s"
              if stats["acquisition_time_s"]
              else "  Acquisition time:        NEVER LOCKED")
        print(f"  Lock retention:          {stats['retention_total_pct']:.1f}%")
        print(f"  Centroiding err (all):   mean {stats['centroid_mean_px']:.2f} px   "
              f"RMS {stats['centroid_rms_px']:.2f}   "
              f"p95 {stats['centroid_p95_px']:.2f}   max {stats['centroid_max_px']:.2f}")
        print(f"  Centroiding err (locked):mean {stats['locked_centroid_mean_px']:.2f} px   "
              f"p95 {stats['locked_centroid_p95_px']:.2f}")
        print(f"  Re-acquisitions:         {stats['reacquisition_count']}"
              + (f"  (mean {stats['mean_reacq_s']:.3f}s)"
                 if stats["mean_reacq_s"] else ""))
        print(f"  False locks:             {stats['false_lock_events']}")
        print(f"{'='*60}")

    if output_path is None:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        output_path = os.path.join(config.LOG_DIR,
                                   f"bypass_{int(time.time())}.csv")
    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["input_file", os.path.basename(input_path)])
        w.writerow(["video_resolution", f"{sim.video_w}x{sim.video_h}"])
        w.writerow(["video_fps", round(sim.video_fps, 2)])
        w.writerow(["total_frames", total_frames])
        w.writerow(["processing_fps", round(stats["fps"], 2)])
        w.writerow(["ground_truth_used", "yes" if truth_csv else "no"])
        w.writerow(["acquisition_time_s",
                    round(stats["acquisition_time_s"], 3)
                    if stats["acquisition_time_s"] else "never_locked"])
        w.writerow(["centroiding_error_mean_px", round(stats["centroid_mean_px"], 2)])
        w.writerow(["centroiding_error_rms_px", round(stats["centroid_rms_px"], 2)])
        w.writerow(["centroiding_error_p95_px", round(stats["centroid_p95_px"], 2)])
        w.writerow(["centroiding_error_max_px", round(stats["centroid_max_px"], 2)])
        w.writerow(["centroiding_error_locked_mean_px",
                    round(stats["locked_centroid_mean_px"], 2)])
        w.writerow(["centroiding_error_locked_p95_px",
                    round(stats["locked_centroid_p95_px"], 2)])
        w.writerow(["lock_retention_pct", round(stats["retention_total_pct"], 2)])
        w.writerow(["reacquisition_count", stats["reacquisition_count"]])
        w.writerow(["mean_reacquisition_s",
                    round(stats["mean_reacq_s"], 3) if stats["mean_reacq_s"] else "n/a"])
        w.writerow(["false_lock_events", stats["false_lock_events"]])
    if verbose:
        print(f"  Performance log -> {output_path}")
    return stats


def main():
    ap = argparse.ArgumentParser(
        description="Benchmark-2: process MP4 through the real coarse-pointing loop")
    ap.add_argument("--input", "-i", required=True,
                    help="Path to input .mp4 video file")
    ap.add_argument("--output", "-o", default=None,
                    help="Output CSV path (auto-generated if omitted)")
    args = ap.parse_args()
    run_bypass(args.input, args.output)


if __name__ == "__main__":
    main()