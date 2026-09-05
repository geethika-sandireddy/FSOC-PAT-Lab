"""
metrics/synthetic_video.py
--------------------------
Generate PS 26169 Benchmark-2-style .mp4 test videos: a 640x480 @ 30 fps
video (or any size) with a moving beacon spot and selectable noise, so the
team can validate the MP4-bypass path (and regenerate challenge videos).

Usage:
    python -m metrics.synthetic_video --output logs/bench_video.mp4 \
        --width 640 --height 480 --fps 30 --seconds 20 \
        --motion figure_eight --noise gaussian,salt_pepper
"""

import argparse
import csv
import cv2
import numpy as np
import os

import config


def _motion_path(motion, t, W, H, speed=1.0):
    """Return beacon pixel center (x, y) for a motion type at time t."""
    cx, cy = W / 2.0, H / 2.0
    amp_x = W * 0.35
    amp_y = H * 0.3
    if motion == "straight_line":
        x = cx + amp_x * np.sin(speed * 0.5 * t)
        y = cy + amp_y * np.sin(speed * 0.3 * t + 0.5)
    elif motion == "circular":
        x = cx + amp_x * np.sin(speed * 0.6 * t)
        y = cy + amp_y * np.cos(speed * 0.6 * t)
    elif motion == "figure_eight":
        x = cx + amp_x * np.sin(speed * 0.5 * t)
        y = cy + amp_y * np.sin(speed * 1.0 * t)
    elif motion == "random":
        # deterministic pseudo-random wander
        x = cx + amp_x * np.sin(speed * 0.4 * t + 1.7 * np.sin(0.9 * t))
        y = cy + amp_y * np.sin(speed * 0.7 * t + 0.3 * np.sin(1.3 * t))
    else:  # spiral
        ang = speed * 0.8 * t
        rad = min(amp_x, amp_y) * (0.2 + 0.8 * (t % 8.0) / 8.0)
        x = cx + rad * np.cos(ang)
        y = cy + rad * np.sin(ang)
    return x, y


def _apply_noise(frame, noise_types, noise_level=20, seed=0):
    """Add PS-mandated noise types to a grayscale-looking color frame."""
    rng = np.random.default_rng(seed)
    h, w = frame.shape[:2]
    out = frame.astype(np.float32)

    if "gaussian" in noise_types:
        sigma = noise_level * 0.5
        out += rng.standard_normal((h, w, 1)) * sigma

    if "salt_pepper" in noise_types:
        density = 0.05
        n = int(density * h * w)
        ys = rng.integers(0, h, n)
        xs = rng.integers(0, w, n)
        half = n // 2
        out[ys[:half], xs[:half], :] = 0
        out[ys[half:], xs[half:], :] = 255

    if "poisson" in noise_types:
        sig = np.sqrt(np.clip(out, 1, 255)) * 0.4
        out += rng.standard_normal((h, w, 1)) * sig

    return np.clip(out, 0, 255).astype(np.uint8)


def generate(output, width=640, height=480, fps=30, seconds=20,
             motion="figure_eight", noise=("gaussian",), beacon_size=10,
             brightness=200, background=15):
    """Generate an MP4 with a moving beacon + noise.

    Also writes a ground-truth sidecar CSV (same base name, ``_truth.csv``)
    with the *exact* beacon pixel centroid per frame -- the "predefined
    error values" Benchmark-2 evaluators compare against.  Columns:
    frame, t, bx, by.
    """
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    truth_csv = os.path.splitext(output)[0] + "_truth.csv"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output, fourcc, fps, (width, height))

    n_frames = int(seconds * fps)
    rng = np.random.default_rng(0)

    truth_rows = []
    for i in range(n_frames):
        t = i / fps
        # plain background (dark space-like + faint gradient)
        frame = np.full((height, width, 3), background, np.uint8)
        yy = np.linspace(0, 12, height)[:, None].astype(np.uint8)
        frame += np.repeat(yy, width, axis=1)[..., None]

        # beacon spot at its pixel position
        x, y = _motion_path(motion, t, width, height)
        truth_rows.append((i, t, x, y))
        xi, yi = int(round(x)), int(round(y))
        bs = beacon_size
        x0, y0 = max(0, xi - bs // 2), max(0, yi - bs // 2)
        x1, y1 = min(width, xi + bs // 2 + 1), min(height, yi + bs // 2 + 1)
        frame[y0:y1, x0:x1] = brightness

        # optional faint glow around the beacon
        r = bs * 2
        yy2, xx2 = np.mgrid[-r:r + 1, -r:r + 1]
        dist = xx2 ** 2 + yy2 ** 2
        glow = (r * r - dist) / (r * r)
        glow[glow < 0] = 0
        gy0, gy1 = max(0, yi - r), min(height, yi + r + 1)
        gx0, gx1 = max(0, xi - r), min(width, xi + r + 1)
        gh, gw = gy1 - gy0, gx1 - gx0
        sub_glow = glow[:gh, :gw] * 60
        frame[gy0:gy1, gx0:gx1] += sub_glow[..., None].astype(np.uint8)

        # noise
        if noise:
            frame = _apply_noise(frame, list(noise), seed=i)

        writer.write(frame)

    writer.release()

    with open(truth_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "t", "bx", "by"])
        w.writerows(truth_rows)

    print(f"  generated: {output} ({width}x{height} @ {fps}fps, "
          f"{seconds}s, {n_frames} frames, motion={motion}, noise={noise})")
    print(f"  truth CSV : {truth_csv} ({len(truth_rows)} rows)")
    return output, truth_csv


def main():
    ap = argparse.ArgumentParser(description="Generate PS benchmark MP4")
    ap.add_argument("--output", "-o", default=None)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--motion", default="figure_eight",
                    choices=["straight_line", "circular", "figure_eight",
                             "random", "spiral"])
    ap.add_argument("--noise", default="gaussian",
                    help="comma list: gaussian,salt_pepper,poisson")
    ap.add_argument("--beacon-size", type=int, default=10)
    args = ap.parse_args()
    out = args.output or os.path.join(
        config.LOG_DIR, f"bench_{args.motion}.mp4")
    generate(out, args.width, args.height, args.fps, args.seconds,
             args.motion, args.noise.split(","), args.beacon_size)


if __name__ == "__main__":
    main()
