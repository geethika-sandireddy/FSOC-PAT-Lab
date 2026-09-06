"""
metrics/stress_test.py
----------------------
Headless multi-trial performance sweeps - the single canonical benchmark
command that reproduces every performance number in the README and the
technical report (docs/TECHNICAL_REPORT.md, Section 9.2), and writes them as
`logs/stress_test_summary.csv` + `logs/benchmark_summary.json`.

Metric definitions (identical to the report):

  * Acquisition        - sim time until the FIRST visible LOCKED frame.
  * Post-lock retention - locked-frames / visible-frames counted only AFTER
                          the first visible lock (startup acquisition
                          excluded), matching the PS "target loss" definition.
  * Est err            - tracker LoS *estimate* error vs truth while locked.
  * Point err          - k* gimbal boresight residual while locked (includes
                          the 5 deg/s slew limit + 2-frame latency).
  * Strike frames      - locked frames whose est err exceeds 0.35 deg
                          (stricter than the wrong-target threshold).
  * False locks        - sustained wrong-target holds (locked, visible, est
                          err > 0.35 for 5 consecutive frames).

Usage:
    python -m metrics.stress_test                 # reproduces report numbers
    python -m metrics.stress_test --seed-base 2026 --trials 5 --frames 300
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time

import config


def run_trial(preset, seed, frames, dt=1.0 / config.FPS):
    from core.simulator import Simulator
    from metrics.performance import PerformanceTracker

    sim = Simulator(preset_name=preset, seed=seed, dt=dt)
    perf = PerformanceTracker()

    post_ret_locked = post_ret_visible = 0
    first_visible_lock = False

    for _ in range(frames):
        sim.step()
        perf.record_frame(sim)
        r = sim.last_result
        if r["state"] == "LOCKED" and r["beacon_visible"]:
            first_visible_lock = True
        if first_visible_lock and r["beacon_visible"]:
            post_ret_visible += 1
            if r["state"] == "LOCKED":
                post_ret_locked += 1

    stats = perf.live_stats()
    post_ret = (post_ret_locked / post_ret_visible * 100.0) if post_ret_visible else 0.0
    return stats, post_ret


def aggregate(preset, trials, frames):
    acqs, rets, estm, estp, ptm, strikes, fls, fpss = ([], [], [], [], [], [], [], [])
    for seed in trials:
        stats, ret = run_trial(preset, seed, frames)
        acqs.append(stats["acquisition_time_s"] if stats["acquisition_time_s"] is not None else 999.0)
        rets.append(ret)
        estm.append(stats["est_err_mean_deg"] if stats["est_err_mean_deg"] is not None else 99.0)
        estp.append(stats["est_err_p95_deg"] if stats["est_err_p95_deg"] is not None else 99.0)
        ptm.append(stats["mean_err_deg"] if stats["mean_err_deg"] is not None else 99.0)
        strikes.append(stats["strike_frames"])
        fls.append(stats["false_lock_events"])
        fpss.append(stats["fps"])
    return dict(
        acq_min=min(acqs), acq_max=max(acqs),
        ret_min=min(rets), ret_max=max(rets),
        est_mean_min=min(estm), est_mean_max=max(estm),
        est_p95_max=max(estp),
        point_mean_min=min(ptm), point_mean_max=max(ptm),
        strike_max=max(strikes),
        false_lock_total=sum(fls),
        fps_min=min(fpss), fps_max=max(fpss),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3,
                    help="independent seeds per preset (default 3 = report)")
    ap.add_argument("--frames", type=int, default=450,
                    help="frames per seed (default 450 = 15 s at 30 Hz)")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="first seed (seeds = base .. base+trials-1, default 0)")
    ap.add_argument("--presets", default=",".join(config.PRESET_ORDER))
    args = ap.parse_args()

    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    seeds = list(range(args.seed_base, args.seed_base + args.trials))
    os.makedirs(config.LOG_DIR, exist_ok=True)
    csv_path = os.path.join(config.LOG_DIR, "stress_test_summary.csv")
    json_path = os.path.join(config.LOG_DIR, "benchmark_summary.json")

    print(f"benchmark: presets={presets} seeds={seeds} frames={args.frames}")
    header = ("preset acq_min acq_max ret_min ret_max est_mn_min est_mn_max "
              "est_p95_max pt_min pt_max strike fl fps_min fps_max")
    print(header)
    rows = []
    for preset in presets:
        row = dict(preset=preset)
        row.update(aggregate(preset, seeds, args.frames))
        rows.append(row)
        print(f"{preset:<12}{row['acq_min']:>7.2f}{row['acq_max']:>7.2f}"
              f"{row['ret_min']:>7.1f}{row['ret_max']:>7.1f}"
              f"{row['est_mean_min']:>9.4f}{row['est_mean_max']:>9.4f}"
              f"{row['est_p95_max']:>9.4f}{row['point_mean_min']:>7.4f}"
              f"{row['point_mean_max']:>7.4f}{row['strike_max']:>6}"
              f"{row['false_lock_total']:>4}{row['fps_min']:>6.1f}{row['fps_max']:>6.1f}")

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    wall = time.time()
    summary = dict(
        commit=os.popen("git rev-parse --short HEAD").read().strip() if os.path.isdir(".git") else "n/a",
        generated=time.strftime("%Y-%m-%d %H:%M:%S"),
        presets=presets,
        seeds=seeds,
        frames_per_trial=args.frames,
        camera_resolution=f"{config.CAM_VIEW_W}x{config.CAM_VIEW_H}",
        fov_deg=f"{config.CAMERA_FOV_H_DEG}x{config.CAMERA_FOV_V_DEG}",
        pixels_per_deg=config.PIXELS_PER_DEG,
        gimbal_slew_deg_s=config.GIMBAL_MAX_SLEW_DEG_S,
        gimbal_tilt_deg_s=config.GIMBAL_MAX_TILT_DEG_S,
        results=rows,
    )
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nsummary -> {csv_path}")
    print(f"metadata -> {json_path}")


if __name__ == "__main__":
    main()