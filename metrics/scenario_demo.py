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
     python -m metrics.scenario_demo --preset MODERATE --inject recover

--inject recover plays the confidence/degrade -> blank -> re-acquire story:
   LOCKED -> DEGRADED_LOCK (weak signal: fade+noise+vibration+turbulence)
          -> COASTING      (predictive coast, sigma grows 2px + roughly)
          -> REACQUIRING   (sigma crosses the 18 px re-acquire line ~0.34 s in)
          -> LOCKED        (beacon reappears; widened REACQ gate + velocity
                            extrapolation re-commits directly - no SEARCH)
This is the escalation the coarse-PAT loop is designed to survive.
"""

import argparse
import time

import config
from core.simulator import Simulator


class ScriptedOccluder:
    """A scripted occluder that parks an opaque disc on the beacon LOS for an
    exact [t0, t1) window.  Outside the window it sits far off-screen where the
    dark-disc renderer (sensor.py) clips it harmlessly, so it never perturbs
    the scene except during the blank.  Duck-types core.scene.Obstacle
    (advance/crossing/az/el/radius_deg)."""

    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1
        self.az = self.el = 975.0
        self.radius_deg = 0.5

    def advance(self, t, bz, bel):
        if self.t0 <= t < self.t1:
            self.az, self.el = bz, bel
        else:
            self.az = self.el = 975.0
        return self.az, self.el

    def crossing(self, t):
        return 1.0 if self.t0 <= t < self.t1 else 0.0


# weakness band that reliably sits confidence in the DEGRADED_LOCK range
# ([0.55, 0.70) overall) WITHOUT losing lock outright
DEGRADE_LEVELS = dict(beacon_fade=65, sensor_noise=65, vibration=30, turbulence=55)


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
    occluder = ScriptedOccluder(inject_at_s, inject_at_s + hold_s)

    for i in range(frames):
        r = sim.step()
        t = r["t"]

        # --- scripted disturbance injection: LOCKED -> (loss) -> COAST/SEARCH
        if not injected and t >= inject_at_s:
            if inject == "fade":
                sim.disturbance.beacon_fade = 85     # dim the beacon almost below detect
            else:  # occlusion / LOS-blank: park a dark disc on the beam
                sim.scene.obstacles.append(occluder)
            injected = True

        if injected and not removed and t >= inject_at_s + hold_s:
            if inject == "fade":
                sim.disturbance.beacon_fade = 0
            else:
                try:
                    sim.scene.obstacles.remove(occluder)
                except ValueError:
                    pass
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


def run_recovery_story(preset="MODERATE", total_s=14.0, inject_at_s=8.0,
                       degrade_s=1.2, blank_s=0.42):
    """LOCKED -> DEGRADED_LOCK -> COASTING -> REACQUIRING -> LOCKED.

    Timeline, all deterministic (seed=1, scripted injects):
      t <  inject_at_s                       : nominal MODERATE track (LOCKED)
      [inject_at, inject_at+degrade_s)       : raised fade+noise+vibration+
                                              turbulence -> confidence sits in the
                                              DEGRADED band (DEGRADED_LOCK,
                                              flickering back to LOCKED)
      [inject_at+degrade, +blank)            : scripted occluder + deep fade ->
                                              clean LOS blank -> COASTING ->
                                              REACQUIRING (sigma crosses 18 px)
      t >= inject_at+degrade+blank           : occluder removed, nominal restored
                                              -> widened REACQ gate +
                                              velocity extrapolation re-locks
                                              DIRECTLY (no SEARCHING)
    """
    sim = Simulator(preset_name=preset, seed=1)
    sim.t = 0.0
    frames = int(total_s / sim.dt)

    occluder = ScriptedOccluder(0.0, 0.0)   # starts off; armed below
    blank_on = False
    blank_done = False
    restored = False
    event_log = []          # (t, label)
    state_seq = []          # (t, state)
    last_state = None
    acq_t = None
    blank_at = None
    reacq_enter = None
    recover_at = None       # first LOCKED after blank began

    for i in range(frames):
        t = sim.t
        # phase scheduling (checked before sim.step so sim.t reads true time)
        if not blank_on and t < inject_at_s + degrade_s:
            if t >= inject_at_s:
                for k, v in DEGRADE_LEVELS.items():
                    setattr(sim.disturbance, k, v)
                if not event_log or event_log[-1][1] != "degrade in":
                    event_log.append((t, "degrade in"))
        elif not blank_on and t >= inject_at_s + degrade_s:
            blank_on = True
            blank_at = t
            occluder.t0, occluder.t1 = t, t + blank_s
            sim.scene.obstacles.append(occluder)
            sim.disturbance.beacon_fade = 100
            sim.disturbance.sensor_noise = 90
            event_log.append((t, "LOS blank in"))
        elif blank_on and not blank_done and t >= inject_at_s + degrade_s + blank_s:
            blank_done = True
            sim.scene.obstacles.remove(occluder)
            sim.disturbance.beacon_fade = 0
            sim.disturbance.sensor_noise = 10
            event_log.append((t, "LOS restored"))

        r = sim.step()

        st = sim.state
        if st != last_state:
            state_seq.append((sim.t, st))
            if st == "LOCKED" and acq_t is None:
                acq_t = sim.t
            if st == "REACQUIRING" and reacq_enter is None and blank_on:
                reacq_enter = sim.t
            if st == "LOCKED" and blank_at is not None and recover_at is None \
                    and sim.t > blank_at:
                recover_at = sim.t
            last_state = st

    # ---- print the story ----
    print(f"RECOVERY STORY: {preset} · degrade @ {inject_at_s:.1f}s"
          f" ({degrade_s:.1f}s) · LOS blank @ {inject_at_s + degrade_s:.1f}s"
          f" ({blank_s:.2f}s)")
    print("state timeline (t -> state):")
    for t, st in state_seq:
        print(f"   {t:7.2f}s   {st}")
    print("scripted events:")
    for t, label in event_log:
        print(f"   {t:7.2f}s   {label}")
    print("-" * 46)
    if acq_t is None:
        print("initial acquisition : never locked")
    else:
        print(f"initial acquisition : {acq_t:6.2f}s")
    n_deg = sum(1 for _, st in state_seq if st == "DEGRADED_LOCK")
    print(f"DEGRADED_LOCK      : {n_deg} timeline phases")
    if blank_at is not None:
        print(f"LOS blank @        : {blank_at:6.2f}s")
    if reacq_enter is not None:
        print(f"REACQUIRING @      : {reacq_enter:6.2f}s"
              f"  (+{reacq_enter - blank_at:.2f}s after blank)")
    if recover_at is not None and blank_at is not None:
        print(f"RE-LOCKED @        : {recover_at:6.2f}s"
              f"  (+{recover_at - blank_at:.2f}s blank-to-recover)")
        # the whole point: recovered via REACQ without a SEARCH sweep
        i_reacq = next((i for i, (_, s) in enumerate(state_seq)
                        if s == "REACQUIRING"), None)
        searched = i_reacq is not None and any(
            s == "SEARCHING" for _, s in state_seq[i_reacq:])
        print(("REACQ path        : DIRECT (widened REACQ gate + velocity "
               "extrapolation)" if not searched
               else "REACQ path        : fell through to SEARCHING"))
    else:
        print("recovery           : not re-locked before end of run")
    print()

    locked = sum(1 for _, st in state_seq if st == "LOCKED")
    return dict(acq=acq_t, blank_at=blank_at, reacq=reacq_enter,
                recover=recover_at, states=len(state_seq),
                locked_phases=locked, deg_phases=n_deg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="MODERATE")
    ap.add_argument("--inject", choices=["fade", "occlude", "recover"],
                    default="fade")
    ap.add_argument("--inject-at", type=float, default=8.0)
    ap.add_argument("--hold", type=float, default=4.0)
    ap.add_argument("--total", type=float, default=30.0)
    args = ap.parse_args()

    if args.inject == "recover":
        run_recovery_story(args.preset, total_s=args.total,
                           inject_at_s=args.inject_at)
    else:
        run_scenario(args.preset, args.inject, hold_s=args.hold,
                     total_s=args.total, inject_at_s=args.inject_at)


if __name__ == "__main__":
    main()
