"""
metrics/stress_test.py
----------------------
Headless multi-trial performance sweeps - the harness that *proves* the
accuracy claims in the technical report rather than a single cherry-picked
demo run.

Runs the whole pipeline (render -> detect -> track -> control) with no
window across every difficulty preset and several random seeds and reports:

  * mean acquisition time
  * lock retention (total + visibility-normalised)
  * mean / RMS / max pointing error while tracked
  * false-lock events (must be 0 everywhere)
  * average FPS

Usage:
    python -m metrics.stress_test --trials 3 --seconds 20
"""

import argparse
import csv
import os
import statistics
import sys

import config


def run_trial(preset, seed, seconds, dt=1.0 / config.FPS):
    from core.simulator import Simulator
    from metrics.performance import PerformanceTracker

    sim = Simulator(preset_name=preset, seed=seed, dt=dt)
    perf = PerformanceTracker()

    n_frames = int(seconds / dt)
    for _ in range(n_frames):
        sim.step()
        perf.record_frame(sim)

    stats = perf.live_stats()
    return stats, perf.acquisition_time_s, perf.false_lock_events, stats["retention_visible_pct"], stats["mean_err_deg"], stats["fps"]


def summarize(results):
    out = {}
    for key, values in results.items():
        vals = [v for v in values if v is not None]
        if not vals:
            out[key] = None
            continue
        out[key] = dict(mean=statistics.mean(vals),
                        stdev=statistics.stdev(vals) if len(vals) > 1 else 0.0,
                        min=min(vals), max=max(vals))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--presets", default=",".join(config.PRESET_ORDER))
    args = ap.parse_args()

    presets = args.presets.split(",")
    os.makedirs(config.LOG_DIR, exist_ok=True)
    summary_path = os.path.join(config.LOG_DIR, "stress_test_summary.csv")

    print(f"{'preset':<12}{'acq(s)':>8}{'ret%':>7}{'vis%':>7}{'mean_deg':>9}"
          f"{'rms_deg':>9}{'max_deg':>9}{'false':>6}{'fps':>6}")
    rows = []
    for preset in presets:
        acqs, rets, viss, means, rmses, maxes, false_locks, fpss = [], [], [], [], [], [], [], []
        for seed in range(args.trials):
            stats, acq, fl, retv, mean_err, fps = run_trial(preset, seed, args.seconds)
            acqs.append(acq if acq is not None else 999.0)
            rets.append(stats["retention_total_pct"])
            viss.append(stats["retention_visible_pct"])
            means.append(stats["mean_err_deg"] if stats["mean_err_deg"] is not None else 99.0)
            rmses.append(stats["rms_err_deg"] if stats["rms_err_deg"] is not None else 99.0)
            maxes.append(stats["max_err_deg"] if stats["max_err_deg"] is not None else 99.0)
            false_locks.append(stats["false_lock_events"])
            fpss.append(stats["fps"])
        s = dict(
            preset=preset,
            acq_mean=statistics.mean(acqs), acq_min=min(acqs),
            ret_total_mean=statistics.mean(rets), ret_total_min=min(rets),
            ret_vis_mean=statistics.mean(viss), ret_vis_min=min(viss),
            err_mean_mean=statistics.mean(means), err_rms_mean=statistics.mean(rmses),
            err_max_mean=statistics.mean(maxes), err_max_max=max(maxes),
            false_lock_total=sum(false_locks),
            fps_mean=statistics.mean(fpss),
        )
        rows.append(s)
        print(f"{preset:<12}{s['acq_mean']:>8.2f}{s['ret_total_mean']:>7.1f}"
              f"{s['ret_vis_mean']:>7.1f}{s['err_mean_mean']:>9.4f}{s['err_rms_mean']:>9.4f}"
              f"{s['err_max_mean']:>9.4f}{s['false_lock_total']:>6}{s['fps_mean']:>6.1f}")

    with open(summary_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nsummary -> {summary_path}")


if __name__ == "__main__":
    main()