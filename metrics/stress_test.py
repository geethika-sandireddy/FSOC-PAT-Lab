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


class _PhasedManoeuvreOrbit:
    """Trust-story beacon motion: a sustained out-of-eph burn.

    The beacon accelerates away from the ephemeris it believes at
    off(t) = 0.5*acc*(t - 7)^2 for 7 <= t < BURN_T1, then the burn ends and
    the beam vehicle settles on its new coasting offset (constant displacement
    from the stale ephemeris, no step).  The *monotonic* separation is what
    forces the bias filter to keep chasing the prior every frame (an asymmetric
    return would self-correct and give the bias a free pass), so the
    model-honesty residual stays above the VISION margin across the window:

      t <  7    nominal orbit               phase A - BALANCED/MODEL nominal
      7<= t< BURN_T1 beacon leaves the eph  phase C - VISION_DOMINANT: the
                with GROWING displacement     bias chases the prior at rate
                (chase = acc*(t-7) deg/s)     acc*(t-7); model prediction
                                              collapses, camera takes the loop
      t = BURN_T1 ops uploads the post-burn  phase D - heal: the tracker
                elements (eph re-anchored to  re-anchors on the new ephemeris,
                the manoeuvred trajectory,    the residual collapses, and
                bias reset); no step          BALANCED/MODEL trust returns
    """
    def __init__(self, inner, acc, t0=7.0, t1=config.TRUSTSTORY_BURN_T1):
        self.inner = inner
        self.acc = acc
        self.t0, self.t1 = t0, t1
        import math
        self._d = (math.cos(0.7), math.sin(0.7))
    def _off(self, t):
        acc, t0, t1 = self.acc, self.t0, self.t1
        if t < t0:
            return 0.0
        if t < t1:
            return 0.5 * acc * (t - t0) ** 2
        return 0.5 * acc * (t1 - t0) ** 2
    def relative_los_az_el(self, t):
        az, el = self.inner.relative_los_az_el(t)
        off = self._off(t)
        return az + self._d[0] * off, el + self._d[1] * off
    def range_km(self, t):
        return self.inner.range_km(t)


# Trust-story vision-degradation band (phase B): the measurement is degraded
# while the ephemeris is truthful, so the manager must smooth through it in
# MODEL_DOMINANT (matching the dynamic-scenario fade recipe).
TRUSTSTORY_DEGRADE = dict(beacon_fade=55, sensor_noise=35, vibration=30,
                          turbulence=20)
# The manoeuvre window (C) must see a *healthy* sensor: the whole point is
# that the camera clears the wrong-model prediction.  These mild values give
# vision_c its full weight during the burn (the beacon is still serviceable
# under the burn's own pointing stress).
TRUSTSTORY_NOMINAL = dict(beacon_fade=10, sensor_noise=10, vibration=8,
                          turbulence=20)


def run_trial(preset, seed, frames, dt=1.0 / config.FPS, scenario=None):
    from core.simulator import Simulator
    from core.tracking import LOCKED, DEGRADED_LOCK
    from metrics.performance import PerformanceTracker

    sim = Simulator(preset_name=preset, seed=seed, dt=dt)
    perf = PerformanceTracker()
    _burn_t1 = config.TRUSTSTORY_BURN_T1

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

    # truststory: a beacon manoeuvre the ephemeris never knew about.  Phase B
    # degrades the vision cue on a TRUE prior (MODEL_DOMINANT); phase C is the
    # pure manoeuvre where the raw prior prediction comes apart and the trust
    # manager hands the loop to the camera (VISION_DOMINANT).  Phase D heals.
    if scenario == "truststory":
        from core.orbital import EphemerisModel as _EphemerisModel
        _burn_acc = config.TRUSTSTORY_ACC_BY_PRESET.get(
            preset, config.TRUSTSTORY_ACC)
        _burn_t1 = config.TRUSTSTORY_T1_BY_PRESET.get(
            preset, config.TRUSTSTORY_BURN_T1)
        sim.scene.beacon.orbit = _PhasedManoeuvreOrbit(sim.scene.beacon.orbit,
                                                       _burn_acc, t1=_burn_t1)
        _eph_upload_t = _burn_t1
        _eph_upload_done = False

    post_ret_locked = post_ret_visible = 0
    first_visible_lock = False
    mode_hist = {}
    phase_hist = {ph: {} for ph in ("A", "B", "C", "D")}
    mode_transitions = []
    _prev_mode = None

    for fi in range(frames):
        # dynamic: a mid-run "solar storm" ramps every disturbance 10x
        if scenario == "dynamic" and sim.t == 7.5:
            sim.disturbance.turbulence = 80
            sim.disturbance.vibration = 40
            sim.disturbance.sensor_noise = 35
            sim.disturbance.jerk_prob = 8
            sim.disturbance.beacon_fade = 55
        # truststory phase B: vision degrade on a correct prior; restored to a
        # healthy sensor for the C manoeuvre and D heal windows.
        if scenario == "truststory":
            if 4.0 <= sim.t < 7.0:
                for _k, _v in TRUSTSTORY_DEGRADE.items():
                    setattr(sim.disturbance, _k, _v)
            elif sim.t >= 7.0:
                for _k, _v in TRUSTSTORY_NOMINAL.items():
                    setattr(sim.disturbance, _k, _v)
            # state-vector upload as the burn completes: ops presents the
            # post-burn elements, the prior realigns with the measurement,
            # and trust reverts to BALANCED/MODEL (the heal).  The bias
            # filter is re-anchored to the new elements too (bias is the
            # learned residual against the OLD ephemeris; keeping it would
            # read as a giant new prediction failure).
            if not _eph_upload_done and sim.t >= _eph_upload_t:
                sim.tracker.eph = _EphemerisModel(sim.scene.beacon.orbit,
                                                  seed=seed)
                sim.tracker.bias_az = 0.0
                sim.tracker.bias_el = 0.0
                sim.tracker._prev_bias_az = sim.tracker._prev_bias_el = None
                sim.tracker._prev_bias_r_az = sim.tracker._prev_bias_r_el = None
                _eph_upload_done = True
        sim.step()
        perf.record_frame(sim)
        r = sim.last_result
        m = getattr(sim.tracker, "trust", None)
        if m is not None and r["state"] in (LOCKED, DEGRADED_LOCK):
            mode_hist[m.mode] = mode_hist.get(m.mode, 0) + 1
            ph = ("A" if sim.t < 4.0 else "B" if sim.t < 7.0
                  else "C" if sim.t < _burn_t1 else "D")
            phase_hist[ph][m.mode] = phase_hist[ph].get(m.mode, 0) + 1
            if scenario == "truststory" and m.mode != _prev_mode:
                mode_transitions.append((round(sim.t, 2), m.mode))
                _prev_mode = m.mode
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
    return stats, post_ret, mode_hist, dict(phase_hist=phase_hist,
                                            mode_transitions=mode_transitions)


def aggregate(preset, trials, frames, scenario=None):
    acqs, rets, estm, estp, ptm, strikes, fls, fpss = ([], [], [], [], [], [], [], [])
    p2 = []
    for seed in trials:
        stats, ret, mode_hist, extra = run_trial(preset, seed, frames,
                                                 scenario=scenario)
        acqs.append(stats["acquisition_time_s"] if stats["acquisition_time_s"] is not None else 999.0)
        rets.append(ret)
        estm.append(stats["est_err_mean_deg"] if stats["est_err_mean_deg"] is not None else 99.0)
        estp.append(stats["est_err_p95_deg"] if stats["est_err_p95_deg"] is not None else 99.0)
        ptm.append(stats["mean_err_deg"] if stats["mean_err_deg"] is not None else 99.0)
        strikes.append(stats["strike_frames"])
        fls.append(stats["false_lock_events"])
        fpss.append(stats["fps"])
        phases = {}
        for ph, hist in extra["phase_hist"].items():
            tot = float(sum(hist.values()))
            if tot:
                phases[ph] = {k: round(v / tot * 100.0) for k, v in hist.items()}
        p2.append(dict(
            seed=seed,
            trust_vision_mean_pct=stats.get("mean_vision_trust_pct"),
            trust_model_mean_pct=stats.get("mean_model_trust_pct"),
            uncertainty_mean_px=stats.get("mean_uncertainty_px"),
            uncertainty_max_px=stats.get("max_uncertainty_px"),
            trust_modes=mode_hist,
            trust_phases=phases,
            mode_transitions=extra.get("mode_transitions"),
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
    ap.add_argument("--frames", type=int, default=900,
                    help="frames per seed (default 900 = 15 s at 60 Hz; "
                         "truststory needs >= 840 to reach the heal phase)")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="first seed (seeds = base .. base+trials-1, default 0)")
    ap.add_argument("--presets", default=",".join(config.PRESET_ORDER))
    ap.add_argument("--scenario", default="none",
                    choices=("none", "wrongprior", "dynamic", "truststory"),
                    help="stress scenario "
                         "(none = canonical, wrongprior/dynamic = Phase 2, "
                         "truststory = Phase 1 trust-manager vignette)")
    ap.add_argument("--tag", default=None,
                    help="filename suffix (e.g. --tag v2 -> *_v2.csv/json)")
    ap.add_argument("--burn-t1", type=float, default=None,
                    help="truststory burn-end time in s (default config.BURN_T1)")
    args = ap.parse_args()

    if args.burn_t1 is not None:
        config.TRUSTSTORY_BURN_T1 = args.burn_t1

    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    seeds = list(range(args.seed_base, args.seed_base + args.trials))
    os.makedirs(config.LOG_DIR, exist_ok=True)
    _tag = "_" + args.scenario if args.scenario != "none" else ""
    if args.tag:
        _tag += "_" + args.tag
    csv_path = os.path.join(config.LOG_DIR, f"stress_test_summary{_tag}.csv")
    json_path = os.path.join(config.LOG_DIR, f"benchmark_summary{_tag}.json")
    p2_path = os.path.join(config.LOG_DIR, f"phase2_trust_summary{_tag}.json")

    print(f"benchmark: presets={presets} seeds={seeds} frames={args.frames} "
          f"scenario={args.scenario} tag={args.tag}")
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