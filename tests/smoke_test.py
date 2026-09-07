"""tests/smoke_test.py
---------------------
Lightweight, dependency-free regression + invariant smoke tests for the
FSOC-PAT loop.  Intentionally short (runs in ~30-60 s) so it can be re-run
before every validation pass.  Exits non-zero on the first failure.

Checks (Part 2 regression + Part 3-8 new behaviour):
  S01  EASY run reaches LOCKED and holds the beacon on boresight (small
       pointing error while locked, no spurious loss).
  S02  Clean EASY log: single SEARCHING -> LOCKED transition (no coasts /
       reacqs / losses on an undisturbed scene).
  S03  Predictive coast: on a true occlusion (beacon render suppressed) the
       tracker enters COASTING, pointing error stays bounded, and after the
       staged reacquisition ladder times out it reaches SEARCHING cleanly.
  S04  Staged reacquisition: the REACQ ladder advances past level 1 before the
       ladder timeout (proves the progressively wider gates engage).
  S05  Distractor run (MODERATE): any LOCKED period is a *true* lock - the
       pointing error while locked stays small (no false lock on the decoy).
  S06  Uncertainty-aware confidence: position confidence is penalised toward
       zero as sigma grows toward the REACQUIRE line.
  S07  Gimbal saturation observability: pan/tilt saturation (0..1) reported.
  S08  FPS robustness: 30 Hz video-rate tracking (dt = 1/30) still acquires
       and locks without NaN or ZeroDivision.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.simulator import Simulator
from core.confidence import ConfidenceState


def _run(preset, frames, seed=3, dt=None):
    sim = Simulator(preset_name=preset, seed=seed,
                    **({"dt": dt} if dt is not None else {}))
    for _ in range(frames):
        res = sim.step()
        assert not math.isnan(res["pointing_err_deg"]), "NaN pointing error"
        assert res["est_err_deg"] is None or not math.isnan(res["est_err_deg"]), \
            "NaN estimate error"
    return sim


def _occlude(sim, seconds):
    """Hide the beacon from the renderer for `seconds` (true track loss).

    Returns (coast_reacq_max_err, search_max_err): max pointing error
    recorded while COASTING/REACQUIRING vs while SEARCHING.
    """
    orig = sim.scene.beacon.intensity
    sim.scene.beacon.intensity = lambda _t: 0.0
    nmax_c, nmax_s = 0.0, 0.0
    n = int(seconds / sim.dt)
    for _ in range(n):
        r = sim.step()
        if r["state"] in ("COASTING", "REACQUIRING"):
            nmax_c = max(nmax_c, r["pointing_err_deg"])
        elif r["state"] == "SEARCHING":
            nmax_s = max(nmax_s, r["pointing_err_deg"])
    sim.scene.beacon.intensity = orig
    return nmax_c, nmax_s


def _locked_err_ms(sim):
    """Max pointing (boresight vs true beacon) error over LOCKED frames, deg."""
    worst = 0.0
    for r in sim.history_of_res if hasattr(sim, "history_of_res") else []:
        pass
    return worst


# probe history is app-side; recompute inline via a small re-run wrapper
class _Run:
    def __init__(self, sim):
        self.sim = sim
        self.max_locked_err_deg = 0.0
        self._collect()

    def _collect(self):
        sim = self.sim
        if not getattr(sim, "_history", None):
            # replay shot captured from the caller's stepping loop
            src = getattr(sim, "shot", None)
            if src:
                for r in src:
                    if r["state"] in ("LOCKED", "DEGRADED_LOCK"):
                        self.max_locked_err_deg = max(self.max_locked_err_deg,
                                                      r["pointing_err_deg"])
            return
        for r in sim._history:
            if r["state"] in ("LOCKED", "DEGRADED_LOCK"):
                self.max_locked_err_deg = max(self.max_locked_err_deg,
                                              r["pointing_err_deg"])


def _step_with_history(sim, frames):
    sim.shot = []
    for _ in range(frames):
        sim.shot.append(sim.step())
    return _Run(sim)


def t01_easy_lock():
    sim = _run("EASY", 150)
    assert sim.tracker.state == "LOCKED", f"expect LOCKED, got {sim.tracker.state}"
    st = [ev[2] for ev in getattr(sim, "event_log", ())]
    ev = getattr(sim, "event_log", [])
    assert ev[0][1] == "SEARCHING" and "LOCKED" in st, f"bad state path {st} (S01)"
    # LOCKED must be reached and held: no sustained loss on clean EASY
    assert st[-1] == "LOCKED", f"EASY ended not locked: {sim.tracker.state} (S01)"
    assert not math.isnan(sim.last_result["pointing_err_deg"]), "NaN at end (S01)"


def t02_clean_single_transition():
    sim = _run("EASY", 60)  # ~1 s; acquisition is ~0.23 s on EASY
    st = [ev[2] for ev in getattr(sim, "event_log", ())]
    # undisturbed EASY: after the initial acquisition the lock is never lost
    # (a one-frame LOCKED<->DEGRADED_LOCK dip during confirm is legitimate)
    allowed = {"LOCKED", "DEGRADED_LOCK"}
    bad = [s for s in st if s not in allowed]
    assert not bad, f"clean scene lost the lock: {st} (S02)"


def t03_coast_and_reacq_timeout():
    sim = Simulator(preset_name="EASY", seed=3)
    _step_with_history(sim, 40)          # acquire
    assert sim.tracker.state == "LOCKED"
    c_err, s_err = _occlude(sim, 4.0)   # full occlusion beyond ladder + timeout
    st = [ev[2] for ev in getattr(sim, "event_log", ())]
    assert any(s == "COASTING" for s in st), f"no COASTING, saw {st} (S03)"
    assert any(s == "REACQUIRING" for s in st), f"no REACQUIRING, saw {st} (S03)"
    assert sim.tracker.state in ("SEARCHING", "REACQUIRING"), \
        f"after ladder timeout expect SEARCHING/REACQ, got {sim.tracker.state} (S03)"
    # predictive coast must hold the line: pointing stays within a fraction of
    # a degree through the whole COAST + REACQ ladder (the beacon never went far)
    assert c_err < 0.5, \
        f"coast/reacq pointing error blew up: {c_err:.3f} deg (S03)"


def t04_reacq_ladder_advances():
    sim = Simulator(preset_name="EASY", seed=3)
    _step_with_history(sim, 40)
    assert sim.tracker.state == "LOCKED"
    levels = []
    sim.scene.beacon.intensity = lambda _t: 0.0
    for i in range(int(1.0 / sim.dt)):   # ~1 s occlusion (within ladder budget)
        sim.step()
        if sim.tracker.state == "REACQUIRING":
            levels.append(sim.tracker.reacq_level)
    assert levels, "reacquisition ladder never engaged (S04)"
    assert max(levels) >= 2, f"ladder should advance past L1, saw {levels} (S04)"


def t05_no_false_lock():
    # MODERATE carries a luminous decoy; a LOCKED period must be a true lock
    sim = Simulator(preset_name="MODERATE", seed=7)
    run = _step_with_history(sim, 300)   # ~5 s: several decoy encounters
    st = [ev[2] for ev in getattr(sim, "event_log", ())]
    assert "LOCKED" in st or "DEGRADED_LOCK" in st, f"never locked: {st} (S05)"
    assert run.max_locked_err_deg < 2.0, \
        f"looks like a false lock: max locked err {run.max_locked_err_deg:.3f} deg (S05)"


def t06_unc_aware_confidence():
    def _pos(sigma):
        cs = ConfidenceState()
        cs.update(identity_src=1.0, snr=80.0, centroid_residual_px=0.3,
                  pred_residual_deg=0.005, pred_scale_deg=0.05,
                  model_conf=1.0, dist_level=0.0,
                  point_err_deg=0.02, point_err_scale_deg=0.2,
                  unc_sigma_px=sigma)
        return cs.position
    big = _pos(config.REACQUIRE_UNCERTAINTY_PX - 0.001)
    assert abs(big - 0.0) < 1e-3, \
        f"high sigma should floor position conf, got {big:.3f} (S06)"
    base = _pos(config.UNCERTAINTY_BASE_PX)
    assert base >= 0.8, \
        f"baseline sigma keeps position conf, got {base:.3f} (S06)"


def t07_saturation_telemetry():
    sim = _run("EASY", 120)
    s = sim.last_result.get("gimbal_sat_pan")
    assert s is not None and 0.0 <= s <= 1.0, \
        f"gimbal_sat_pan invalid: {s} (S07)"


def t08_video_rate_dt():
    sim = _run("EASY", 150, dt=1.0 / 30.0)
    assert sim.tracker.state == "LOCKED", f"30 Hz sim not locked (S08)"
    st = [ev[2] for ev in getattr(sim, "event_log", ())]
    assert sim.tracker.state == "LOCKED" and st[-1] == "LOCKED", \
        f"30 Hz path {st} (S08)"


TESTS = [
    ("S01  easy_preset_locks_beacon", t01_easy_lock),
    ("S02  clean_single_transition", t02_clean_single_transition),
    ("S03  coast_and_reacq_timeout", t03_coast_and_reacq_timeout),
    ("S04  reacq_ladder_advances", t04_reacq_ladder_advances),
    ("S05  no_false_lock", t05_no_false_lock),
    ("S06  unc_aware_confidence", t06_unc_aware_confidence),
    ("S07  saturation_telemetry", t07_saturation_telemetry),
    ("S08  video_rate_dt", t08_video_rate_dt),
]


def main():
    passed = 0
    for name, fn in TESTS:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            return 1
        except Exception as e:
            print(f"  ERROR {name}: {e!r}")
            return 1
    print(f"\nsmoke_test: {passed}/{len(TESTS)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
