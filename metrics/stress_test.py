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
import math
import os
import statistics
import sys
import time

import config


def run_trial(preset, seed, frames, dt=1.0 / config.FPS, scenario=None):
    from core.simulator import Simulator
    from core.tracking import LOCKED, DEGRADED_LOCK
    from metrics.performance import PerformanceTracker

    sim = Simulator(preset_name=preset, seed=seed, dt=dt)
    perf = PerformanceTracker()

    # --- Phase 2 scenario hooks -------------------------------------------
    # wrongprior: the MotionModel drifts (ephemeris de facto corrupted), a
    # strong test of the Model-Vision Trust manager.  The drift is large enough
    # to genuinely outrun the adaptive observer (so the model really IS wrong)
    # but stays realistic for drag-accumulation error on a downlink arc.
    if scenario == "wrongprior":
        base_eph = sim.eph
        class _CorruptEph:
            def __init__(self, inner, seed):
                self.inner = inner
                self.drift_t0 = 4.0
                rnd = __import__("random").Random(seed)
                th = rnd.uniform(0.0, 6.28318)
                self._d = (math.cos(th), math.sin(th))
                self.drift_rate = 0.012          # deg/s, one-directional grow
                # persistent random-walk prior noise AFTER the steps: the
                # residual "unmodeled drag error" the observer cannot learn
                # out, so the trust manager must hand control to the camera.
                self.walk_k0 = int(6.0 / 1.0 / config.FPS)
                n = int(15.0 / 1.0 / config.FPS) + 2
                self._walk = [0.0] * n
                v = 0.0
                rnd2 = __import__("random").Random(seed + 777)
                for i in range(1, n):
                    v += rnd2.gauss(0.0, 0.024)
                    self._walk[i] = v
            def predict_az_el(self, t):
                az, el = self.inner.predict_az_el(t)
                if t >= self.drift_t0:
                    off = self.drift_rate * (t - self.drift_t0)
                    az += self._d[0] * off
                    el += self._d[1] * off
                # ephemeris "recalibration steps": +0.15 deg at t=6 s and a
                # further +0.20 deg at t=10 s (discontinuous prior jumps).
                _step = 0.0
                if t >= 10.0:
                    _step = 0.35
                elif t >= 6.0:
                    _step = 0.15
                k = int(t / 1.0 / config.FPS) - self.walk_k0
                if k >= 0 and k < len(self._walk):
                    az += self._d[0] * self._walk[k]
                    el += self._d[1] * self._walk[k]
                return az + self._d[0] * _step, el + self._d[1] * _step
        sim.tracker.eph = _CorruptEph(base_eph, seed)

    post_ret_locked = post_ret_visible = 0
    first_visible_lock = False
    mode_hist = {}

    for fi in range(frames):
        # dynamic: a mid-run "solar storm" ramps every disturbance 10x
        if scenario == "dynamic" and sim.t == 7.5:
            sim.disturbance.turbulence = 80
            sim.disturbance.vibration = 40
            sim.disturbance.sensor_noise = 35
            sim.disturbance.jerk_prob = 8
            sim.disturbance.beacon_fade = 55
        sim.step()
        perf.record_frame(sim)
        r = sim.last_result
        m = getattr(sim.tracker, "trust", None)
        if m is not None and r["state"] in (LOCKED, DEGRADED_LOCK):
            mode_hist[m.mode] = mode_hist.get(m.mode, 0) + 1
        # DEGRADED_LOCK still *holds* the lock on the target (the system
        # explicitly refuses to declare loss while confidence is merely low),
        # so it counts as retained exactly like LOCKED.
        if r["state"] in (LOCKED, DEGRADED_LOCK) and r["beacon_visible"]:
            first_visible_lock = True
        if first_visible_lock and r["beacon_visible"]:
            post_ret_visible += 1
            if r["state"] in (LOCKED, DEGRADED_LOCK):
                post_ret_locked += 1

    stats = perf.live_stats()
    post_ret = (post_ret_locked / post_ret_visible * 100.0) if post_ret_visible else 0.0
    return stats, post_ret, mode_hist


def aggregate(preset, trials, frames, scenario=None):
    acqs, rets, estm, estp, ptm, strikes, fls, fpss = ([], [], [], [], [], [], [], [])
    p2 = []
    for seed in trials:
        stats, ret, mode_hist = run_trial(preset, seed, frames, scenario=scenario)
        acqs.append(stats["acquisition_time_s"] if stats["acquisition_time_s"] is not None else 999.0)
        rets.append(ret)
        estm.append(stats["est_err_mean_deg"] if stats["est_err_mean_deg"] is not None else 99.0)
        estp.append(stats["est_err_p95_deg"] if stats["est_err_p95_deg"] is not None else 99.0)
        ptm.append(stats["mean_err_deg"] if stats["mean_err_deg"] is not None else 99.0)
        strikes.append(stats["strike_frames"])
        fls.append(stats["false_lock_events"])
        fpss.append(stats["fps"])
        p2.append(dict(
            seed=seed,
            trust_vision_mean_pct=stats.get("mean_vision_trust_pct"),
            trust_model_mean_pct=stats.get("mean_model_trust_pct"),
            uncertainty_mean_px=stats.get("mean_uncertainty_px"),
            uncertainty_max_px=stats.get("max_uncertainty_px"),
            trust_modes=mode_hist,
        ))
    return dict(
        acq_min=min(acqs), acq_max=max(acqs),
        ret_min=min(rets), ret_max=max(rets),
        est_mean_min=min(estm), est_mean_max=max(estm),
        est_p95_max=max(estp),
        point_mean_min=min(ptm), point_mean_max=max(ptm),
        strike_max=max(strikes),
        false_lock_total=sum(fls),
        fps_min=min(fpss), fps_max=max(fpss),
    ), p2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3,
                    help="independent seeds per preset (default 3 = report)")
    ap.add_argument("--frames", type=int, default=450,
                    help="frames per seed (default 450 = 15 s at 30 Hz)")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="first seed (seeds = base .. base+trials-1, default 0)")
    ap.add_argument("--presets", default=",".join(config.PRESET_ORDER))
    ap.add_argument("--scenario", default="none",
                    choices=("none", "wrongprior", "dynamic"),
                    help="Phase 2 stress scenario (default none = canonical)")
    args = ap.parse_args()

    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    seeds = list(range(args.seed_base, args.seed_base + args.trials))
    os.makedirs(config.LOG_DIR, exist_ok=True)
    _tag = "_" + args.scenario if args.scenario != "none" else ""
    csv_path = os.path.join(config.LOG_DIR, f"stress_test_summary{_tag}.csv")
    json_path = os.path.join(config.LOG_DIR, f"benchmark_summary{_tag}.json")
    p2_path = os.path.join(config.LOG_DIR, f"phase2_trust_summary{_tag}.json")

    print(f"benchmark: presets={presets} seeds={seeds} frames={args.frames} "
          f"scenario={args.scenario}")
    header = ("preset acq_min acq_max ret_min ret_max est_mn_min est_mn_max "
              "est_p95_max pt_min pt_max strike fl fps_min fps_max")
    print(header)
    rows = []
    p2rows = {}
    for preset in presets:
        agg, p2 = aggregate(preset, seeds, args.frames, scenario=args.scenario)
        row = dict(preset=preset)
        row.update(agg)
        rows.append(row)
        p2rows[preset] = p2
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
        scenario=args.scenario,
        camera_resolution=f"{config.CAM_VIEW_W}x{config.CAM_VIEW_H}",
        fov_deg=f"{config.CAMERA_FOV_H_DEG}x{config.CAMERA_FOV_V_DEG}",
        pixels_per_deg=config.PIXELS_PER_DEG,
        gimbal_slew_deg_s=config.GIMBAL_MAX_SLEW_DEG_S,
        gimbal_tilt_deg_s=config.GIMBAL_MAX_TILT_DEG_S,
        results=rows,
    )
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    if args.scenario != "none" or p2rows:
        p2 = dict(
            commit=summary["commit"],
            generated=summary["generated"],
            scenario=args.scenario,
            rows=p2rows,
        )
        with open(p2_path, "w") as f:
            json.dump(p2, f, indent=2)
        print(f"phase2 trust/uncertainty -> {p2_path}")

    print(f"\nsummary -> {csv_path}")
    print(f"metadata -> {json_path}")


if __name__ == "__main__":
    main()