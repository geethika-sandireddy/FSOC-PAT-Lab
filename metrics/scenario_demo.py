"""
metrics/scenario_demo.py
------------------------
The "press one button and show the whole PAT story" harness.

Runs a SCRIPTED scenario that exercises every state a real coarse-PAT
loop goes through, and prints the timeline so it can be shown (and
verbally defended) to a judging panel:

    SEARCHING  (initial acquisition)
        -> LOCKED        "BEACON ACQUIRED"
        -> [inject: beacon fade / occlusion]
        -> COASTING      "PREDICTIVE COAST"  (ephemeris prior drives pointing)
        -> SEARCHING     "LOCK LOST -> LOCAL SEARCH"
        -> LOCKED        "REACQUIRED"
        -> [remove disturbance]
        -> LOCKED        "STABLE TRACK"

A scripted disturbance (fade or occlusion) is injected at a chosen time
and later removed, so the judge sees cause -> effect -> recovery with a
measured reacquisition time.

Run:  python -m metrics.scenario_demo --preset MODERATE --inject fade
"""

import argparse
import time

import config
from core.simulator import Simulator


def run_scenario(preset, inject="fade", hold_s=4.0, total_s=30.0,
                 inject_at_s=10.0):
    sim = Simulator(preset_name=preset, seed=1)
    dt = sim.dt
    frames = int(total_s / dt)
    sim.t = 0.0

    # phase bookkeeping
    timeline = []
    state_seq = []        # (t, state)
    last_state = None
    acq_t = None
    # reacquisition = time from disturbance-induced lock-LOSS until next lock
    lost_at = None
    reacq_t = None
    injected = False
    removed = False

    for i in range(frames):
        r = sim.step()
        t = r["t"]

        # --- scripted disturbance injection: LOCKED -> (loss) -> COAST/SEARCH
        if not injected and t >= inject_at_s:
            if inject == "fade":
                sim.disturbance.beacon_fade = 85     # dim the beacon almost below detect
            else:  # occlusion / LOS-blank
                sim.scene.beacon.visible = False     # beacon ray is blocked
            injected = True

        if injected and not removed and t >= inject_at_s + hold_s:
            if inject == "fade":
                sim.disturbance.beacon_fade = 0
            else:
                sim.scene.beacon.visible = True
            removed = True

        st = sim.state
        if st != last_state:
            state_seq.append((t, st))
            if st == "LOCKED" and acq_t is None:
                acq_t = t
            # disturbance caused a loss -> mark the lock-loss instant.
            # the tracker first COASTs (ephemeris prior) then gives up to
            # SEARCH; record the moment it left LOCKED after injection.
            if injected and lost_at is None and st in ("COASTING", "SEARCHING") \
                    and last_state in ("LOCKED", "COASTING"):
                lost_at = t
            # recovered to LOCKED after that injected loss
            if st == "LOCKED" and lost_at is not None and reacq_t is None:
                reacq_t = t
            last_state = st

    # ---- print the story timeline ----
    print(f"SCENARIO: {preset} · inject={inject} @ {inject_at_s}s for {hold_s}s")
    print("state timeline (t -> state):")
    for t, st in state_seq:
        print(f"   {t:7.2f}s   {st}")
    print("-" * 46)
    if acq_t is None:
        print("initial acquisition : never locked")
    else:
        print(f"initial acquisition : {acq_t:6.2f}s")
    if lost_at is None:
        print("disturbance cause   : did not induce a lock-loss (too mild)")
    else:
        print(f"lock lost @         : {lost_at:6.2f}s  (post-injection)")
    if reacq_t is not None and lost_at is not None:
        print(f"REACQUIRED @        : {reacq_t:6.2f}s   (+{reacq_t - lost_at:.2f}s recovery)")
    else:
        print("recovery            : not re-locked before end of run")
    print()

    # quantitative gist
    n = len(state_seq)
    locked = sum(1 for _, st in state_seq if st == "LOCKED")
    return dict(acq=acq_t, reacq=reacq_t, lost_at=lost_at, states=len(state_seq),
                locked_phases=locked)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="MODERATE")
    ap.add_argument("--inject", choices=["fade", "occlude"], default="fade")
    ap.add_argument("--inject-at", type=float, default=8.0)
    ap.add_argument("--hold", type=float, default=4.0)
    ap.add_argument("--total", type=float, default=30.0)
    args = ap.parse_args()

    run_scenario(args.preset, args.inject, hold_s=args.hold,
                 total_s=args.total, inject_at_s=args.inject_at)


if __name__ == "__main__":
    main()
