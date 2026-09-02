"""
metrics/compare_trackers.py
---------------------------
Honest, measured BASELINE vs ADAPTIVE A/B benchmark.

Runs the SAME scenario (same preset, same random seed, same sensor /
disturbances / gimbal physics) twice: once with the naive baseline tracker
(`core.baseline_tracker.BaselineTracker`) and once with the adaptive tracker
(`core.tracking.Tracker`).  Because only the tracking algorithm differs, the
delta between the two columns is *entirely due to the algorithm*, not the
platform.

Metrics (real, from PerformanceTracker):
  acquisition      - time to first lock
  mean error       - mean boresight pointing error while locked (deg)
  rms error        - root-mean-square pointing error while locked (deg)
  retention        - % of frames locked overall
  false locks      - sustained wrong-target lock episodes
  reacquisition    - mean time to re-lock after a disturbance-induced loss

Run:  python -m metrics.compare_trackers --trials 3 --seconds 15
"""

import argparse
import json
import os
import statistics

import config
from core.simulator import Simulator
from core.baseline_tracker import BaselineTracker
from core.tracking import Tracker
from metrics.performance import PerformanceTracker


def run(tracker_factory, preset, seed, seconds):
    sim = Simulator(preset_name=preset, seed=seed, tracker_factory=tracker_factory)
    perf = PerformanceTracker()
    frames = int(seconds / sim.dt)
    for _ in range(frames):
        sim.step()
        perf.record_frame(sim)
    st = perf.live_stats()
    st["reacq_s"] = (sum(perf.reacquisition_times) / len(perf.reacquisition_times)
                     if perf.reacquisition_times else None)
    st["reacq_n"] = len(perf.reacquisition_times)
    return st, sim.tracker.acquisition_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=15.0)
    args = ap.parse_args()

    hdr = f"{'preset':<12}{'alg':<9}{'acq':>7}{'mean°':>8}{'rms°':>8}"
    hdr += f"{'ret%':>8}{'fal':>5}{'reacq':>8}"
    print(hdr)
    print("-" * len(hdr))
    summary = []
    for preset in config.PRESET_ORDER:
        row = {}
        for name, factory in (("baseline", BaselineTracker), ("adaptive", Tracker)):
            acqs, means, rmss, rets, fals, reacqs = [], [], [], [], [], []
            for trial in range(args.trials):
                # same seed per (preset, trial) so both algos face identical runs
                st, _ = run(factory, preset, seed=trial + 1, seconds=args.seconds)
                acqs.append(st["acquisition_time_s"] or 1e9)
                means.append(st["mean_err_deg"] or 1e9)
                rmss.append(st["rms_err_deg"] or 1e9)
                rets.append(st["retention_total_pct"])
                fals.append(st["false_lock_events"])
                if st["reacq_s"] is not None:
                    reacqs.append(st["reacq_s"])
            a = statistics.mean(acqs); m = statistics.mean(means)
            r = statistics.mean(rmss); ret = statistics.mean(rets)
            f = sum(fals); rq = statistics.mean(reacqs) if reacqs else float("nan")
            row[name] = (a, m, r, ret, f, rq)
            print(f"{preset:<12}{name:<9}{a:7.2f}{m:8.3f}{r:8.3f}"
                  f"{ret:8.1f}{f:5d}{rq:8.2f}")
        summary.append((preset, row))
    print()
    print("note: identical seed per (preset, trial) -> the only difference is")
    print("      the tracking algorithm; platform sensor/physics are shared.")

    # persist the real measured table as JSON for the GUI comparison panel
    out = {}
    for preset, row in summary:
        out[preset] = {alg: dict(acq=row[alg][0], mean_deg=row[alg][1],
                                 rms_deg=row[alg][2], ret_pct=row[alg][3],
                                 false_locks=row[alg][4],
                                 reacq_s=row[alg][5]) for alg in row}
    meta = {"trials": args.trials, "seconds": args.seconds}
    json_path = os.path.join(config.LOG_DIR, "compare_summary.json")
    with open(json_path, "w") as fh:
        json.dump({"meta": meta, "results": out}, fh, indent=2)
    print(f"saved -> {json_path}")
    return summary


if __name__ == "__main__":
    main()
