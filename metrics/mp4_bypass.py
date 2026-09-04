"""
metrics/mp4_bypass.py
---------------------
PTZ-camera bypass: takes a pre-recorded .mp4 video file as input instead of
the virtual scene, detects the beacon centroid in each frame, and computes
tracking metrics (centroiding error in pixels).

Benchmark 2 (30% of evaluation): judges provide .mp4 files with a moving
beacon spot and noise.  The software must process the video and output:
  - centroiding error (pixels from frame center) per frame
  - acquisition time, re-acquisition time, lock retention, FPS
  - automatically generated performance log (CSV)

Usage:
    python -m metrics.mp4_bypass --input video.mp4 --output logs/bypass_report.csv
    python -m metrics.mp4_bypass --input video.mp4   # prints summary to stdout
"""

import argparse
import csv
import os
import time

import cv2
import numpy as np

import config


def _detect_beacon_centroid(frame_gray, min_area=4, max_area=5000):
    """Simple blob centroid detection on a grayscale frame.
    Returns (cx, cy, area) or None if no beacon found.

    Method: adaptive threshold + contour detection (same family as our
    DetectionEngine but operating on raw pixels rather than projected coords).
    """
    blur = cv2.GaussianBlur(frame_gray, (5, 5), 1.2)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0
    h, w = frame_gray.shape[:2]
    cx_frame, cy_frame = w / 2.0, h / 2.0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        # prefer bright blobs near centre (heuristic: beacon is bright)
        intensity = float(frame_gray[int(round(cy)), int(round(cx))]) if \
            (0 <= int(round(cy)) < h and 0 <= int(round(cx)) < w) else 0
        if intensity > 80 and area > best_area:
            best = (cx, cy, area)
            best_area = area

    return best


def _centroid_error_pixels(cx, cy, w, h):
    """Distance of beacon centroid from frame centre in pixels."""
    return float(np.hypot(cx - w / 2.0, cy - h / 2.0))


def run_bypass(input_path, output_path=None, verbose=True):
    """Process an MP4 video file and compute tracking metrics.

    Returns a dict of metrics identical in structure to live_stats().
    """
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {input_path}")

    fps_vid = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    dt = 1.0 / fps_vid
    errors_px = []
    locked_frames = 0
    visible_frames = 0
    acquisition_time = None
    reacq_times = []
    lock_lost_at = None
    was_locked = False
    lock_events = 0
    false_lock_events = 0
    _false_lock_count = 0
    frame_idx = 0
    t0 = time.time()

    # PS thresholds (convert from config to pixels)
    lock_threshold_px = config.FINE_ACQUISITION_REGION_DEG * config.PIXELS_PER_DEG
    false_lock_threshold_px = 0.35 * config.PIXELS_PER_DEG

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t_frame = frame_idx * dt
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        det = _detect_beacon_centroid(gray)
        visible = det is not None
        visible_frames += 1

        if visible:
            cx, cy, area = det
            err_px = _centroid_error_pixels(cx, cy, width, height)
            errors_px.append(err_px)

            # lock logic: beacon detected and within threshold
            is_locked = err_px < lock_threshold_px
            if is_locked:
                locked_frames += 1
                if acquisition_time is None:
                    acquisition_time = t_frame
                    lock_events += 1
                elif not was_locked:
                    # re-acquisition
                    if lock_lost_at is not None:
                        reacq_times.append(t_frame - lock_lost_at)
                        lock_lost_at = None
                    lock_events += 1
                # false-lock check (centroid far from centre but "locked")
                if err_px > false_lock_threshold_px:
                    _false_lock_count += 1
                    if _false_lock_count == 5:
                        false_lock_events += 1
                else:
                    _false_lock_count = 0
            else:
                _false_lock_count = 0
                if was_locked:
                    lock_lost_at = t_frame
        else:
            _false_lock_count = 0
            is_locked = False
            errors_px.append(float(width))  # worst-case error when lost
            if was_locked:
                lock_lost_at = t_frame

        was_locked = is_locked if visible else False
        frame_idx += 1

    cap.release()
    wall = time.time() - t0

    n = len(errors_px)
    mean_err_px = float(np.mean(errors_px)) if n else 0.0
    rms_err_px = float(np.sqrt(np.mean(np.array(errors_px) ** 2))) if n else 0.0
    max_err_px = float(np.max(errors_px)) if n else 0.0
    sorted_errs = sorted(errors_px)
    p95_err_px = sorted_errs[int(n * 0.95) - 1] if n > 0 else 0.0
    ret_pct = (locked_frames / total_frames * 100) if total_frames else 0.0
    success_pct = (locked_frames / visible_frames * 100) if visible_frames else 0.0
    mean_reacq = float(np.mean(reacq_times)) if reacq_times else None
    mean_err_deg = mean_err_px / config.PIXELS_PER_DEG
    rms_err_deg = rms_err_px / config.PIXELS_PER_DEG
    p95_err_deg = p95_err_px / config.PIXELS_PER_DEG

    stats = dict(
        fps=total_frames / wall if wall > 0 else 0.0,
        mean_err_deg=mean_err_deg,
        max_err_deg=max_err_px / config.PIXELS_PER_DEG,
        rms_err_deg=rms_err_deg,
        p95_err_deg=p95_err_deg,
        mean_err_px=mean_err_px,
        p95_err_px=p95_err_px,
        max_err_px=max_err_px,
        acquisition_time_s=acquisition_time,
        retention_total_pct=ret_pct,
        success_rate_pct=success_pct,
        reacquisition_count=len(reacq_times),
        mean_reacq_s=mean_reacq,
        last_reacq_s=reacq_times[-1] if reacq_times else None,
        false_lock_events=false_lock_events,
        lock_events=lock_events,
    )

    if verbose:
        print(f"\n{'='*56}")
        print(f"  MP4 BYPASS RESULTS  ({os.path.basename(input_path)})")
        print(f"{'='*56}")
        print(f"  Video: {width}x{height} @ {fps_vid:.1f} fps, "
              f"{total_frames} frames ({total_frames/fps_vid:.1f}s)")
        print(f"  Processing: {wall:.2f}s wall, {stats['fps']:.0f} fps")
        print(f"{'─'*56}")
        print(f"  Acquisition time:    {acquisition_time:.3f}s" if acquisition_time
              else "  Acquisition time:    NEVER LOCKED")
        print(f"  Retention:           {ret_pct:.1f}%")
        print(f"  Success rate:        {success_pct:.1f}%")
        print(f"  Mean centroid error: {mean_err_px:.1f} px  ({mean_err_deg:.4f} deg)")
        print(f"  P95 centroid error:  {p95_err_px:.1f} px  ({p95_err_deg:.4f} deg)")
        print(f"  Max centroid error:  {max_err_px:.1f} px")
        print(f"  Lock events:         {lock_events}")
        print(f"  Re-acquisitions:     {len(reacq_times)}"
              + (f"  (mean {mean_reacq:.3f}s)" if mean_reacq else ""))
        print(f"  False locks:         {false_lock_events}")
        print(f"{'='*56}")

    # --- auto-generated performance log (mandatory deliverable) ---
    if output_path is None:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        output_path = os.path.join(config.LOG_DIR,
                                   f"bypass_{int(time.time())}.csv")
    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["input_file", os.path.basename(input_path)])
        w.writerow(["video_resolution", f"{width}x{height}"])
        w.writerow(["video_fps", round(fps_vid, 2)])
        w.writerow(["total_frames", total_frames])
        w.writerow(["processing_fps", round(stats["fps"], 2)])
        w.writerow(["acquisition_time_s",
                     round(acquisition_time, 3) if acquisition_time else "never_locked"])
        w.writerow(["centroiding_error_mean_px", round(mean_err_px, 2)])
        w.writerow(["centroiding_error_mean_deg", round(mean_err_deg, 4)])
        w.writerow(["centroiding_error_p95_px", round(p95_err_px, 2)])
        w.writerow(["centroiding_error_p95_deg", round(p95_err_deg, 4)])
        w.writerow(["centroiding_error_max_px", round(max_err_px, 2)])
        w.writerow(["centroiding_error_rms_px", round(rms_err_px, 2)])
        w.writerow(["lock_retention_pct", round(ret_pct, 2)])
        w.writerow(["tracking_success_pct", round(success_pct, 2)])
        w.writerow(["lock_events", lock_events])
        w.writerow(["reacquisition_count", len(reacq_times)])
        w.writerow(["mean_reacquisition_s",
                     round(mean_reacq, 3) if mean_reacq else "n/a"])
        w.writerow(["false_lock_events", false_lock_events])

    if verbose:
        print(f"  Performance log -> {output_path}")

    return stats


def main():
    ap = argparse.ArgumentParser(
        description="PTZ bypass: process MP4 video with beacon tracking")
    ap.add_argument("--input", "-i", required=True,
                    help="Path to input .mp4 video file")
    ap.add_argument("--output", "-o", default=None,
                    help="Output CSV path (auto-generated if omitted)")
    args = ap.parse_args()
    run_bypass(args.input, args.output)


if __name__ == "__main__":
    main()
