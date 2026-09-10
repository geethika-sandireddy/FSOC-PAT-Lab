"""
core/scene.py
-------------
Block A - the virtual 3D world: starfield, Satellite B's beacon with its
modulated signature, decoy distractors, and occluding obstacles.

Everything here is *world geometry*; core/sensor.py projects it into the
camera at the current gimbal attitude.  Detectors only ever see the
projected (and disturbed) sensor image - never these world coordinates.
"""

import math
import random

import numpy as np

import config
from core import geometry


class Starfield:
    def __init__(self, num, seed=7):
        rng = random.Random(seed)
        self.dirs = []
        self.mags = []
        for _ in range(num):
            az = rng.uniform(-180, 180)
            el = rng.uniform(-85, 85)
            d = geometry.azel_unit(az, el)
            mag = rng.uniform(0.15, 1.0)
            self.dirs.append(d)
            self.mags.append(mag)
        self.dirs = np.array(self.dirs, dtype=np.float64)
        self.mags = np.array(self.mags, dtype=np.float64)


class Beacon:
    """Satellite B's optical beacon (PS 26169: target shape/size configurable)."""

    def __init__(self, orbit_model, seed=None, shape="SQUARE", size_px=10, size_py=10,
                 phase_offset=0.0, target_id="TARGET-01"):
        self.target_id = target_id
        self.orbit = orbit_model
        self.motion_model = getattr(orbit_model, "_motion_type", "straight_line")
        self.az_deg = 0.0
        self.el_deg = 0.0
        self.vel_az = 0.0
        self.vel_el = 0.0
        self.range_km = 1000.0
        self.pos = (0.0, 0.0, 1000.0)
        self._time = -abs(phase_offset)   # delayed start: enters later in a run
        self.visible = True
        self.shape = shape          # PS: Square (default), Circle, Spot, Ellipse
        self.size_px = size_px      # PS: 5-20 pixels, default 10
        self.size_py = size_py

    def advance(self, dt):
        self._time += dt
        prev_az, prev_el = self.az_deg, self.el_deg
        self.az_deg, self.el_deg = self.orbit.relative_los_az_el(self._time)
        if dt > 0:
            self.vel_az = (self.az_deg - prev_az) / dt
            self.vel_el = (self.el_deg - prev_el) / dt
        self.range_km = self.orbit.range_km(self._time)
        q = geometry.azel_unit(self.az_deg, self.el_deg)
        r = self.range_km * 1000.0
        self.pos = (q[0] * r, q[1] * r, q[2] * r)
        return self.pos

    @property
    def trajectory(self):
        """Return reference to underlying physical orbital motion model."""
        return self.orbit

    @property
    def time(self):
        return self._time

    def intensity(self, t):
        """Beacon amplitude-modulated (blinking) signature used for ID."""
        phase = math.fmod(config.MODULATION_FREQ_HZ * t, 1.0)
        return config.MODULATION_BRIGHT if phase < 0.5 else config.MODULATION_DIM


class Distractor:
    """A decoy that *looks* beacon-like but has a different modulation and
    hue - tests appearance + modulation discrimination."""

    def __init__(self, anchor_az, anchor_el, rng, seed_idx):
        self.anchor_az = anchor_az
        self.anchor_el = anchor_el
        self.az = anchor_az
        self.el = anchor_el
        self.omega = rng.uniform(0.12, 0.35)
        self.amp = rng.uniform(0.15, 0.5)
        self.phase = rng.uniform(0, 6.283)
        self.speed = rng.uniform(0.6, 1.4)
        self.mod_freq = rng.choice([0.0, 3.0, 8.0])          # decoy modulation
        self.mod_depth = rng.uniform(40, 140)
        self.radius_deg = rng.uniform(0.025, 0.05)
        self.hue = rng.choice([18, 25, 45, 95, 130, 175])    # off-hue decoys
        self._t = seed_idx * 1.3

    def advance(self, dt, anchor_az, anchor_el):
        self._t += dt
        self.az = anchor_az + self.amp * math.cos(self.omega * self._t + self.phase)
        self.el = anchor_el + 0.6 * self.amp * math.sin(0.8 * self.omega * self._t + self.phase)
        return self.az, self.el

    def intensity(self):
        if self.mod_freq <= 0:
            return 170.0
        phase = math.fmod(self.mod_freq * self._t, 1.0)
        base = 170.0
        return base - self.mod_depth * (0.5 if phase < 0.5 else -0.5 if phase < 0.55 else 0.0)


class Obstacle:
    """Opaque debris disc that genuinely occludes the line of sight when it
    crosses the beacon path (tests track-through-loss)."""

    def __init__(self, rng, seed_idx):
        self.cross_t0 = 5.0 + seed_idx * 7.0 + rng.uniform(0, 2.0)
        self.period = 22.0 + rng.uniform(0, 10.0)
        self.radius_deg = rng.uniform(0.08, 0.16)
        self.speed = 0.30 + rng.uniform(0.0, 0.25)
        self.seed = seed_idx
        self.az = self.el = 0.0

    def advance(self, t, beacon_az, beacon_el):
        """Track near the beacon path, crossing in front periodically."""
        local_t = t - self.cross_t0
        along = math.fmod(local_t + t * self.speed, self.period)
        frac = 2.0 * along / self.period - 1.0                # -1..1
        perp = math.sin(2.0 * math.pi * frac * 0.5)
        # swerve across the beacon LOS
        self.az = beacon_az + 0.5 * frac * 0.7 + 0.15 * math.sin(0.5 * t)
        self.el = beacon_el + perp * self.radius_deg * 1.1
        return self.az, self.el

    def crossing(self, t):
        """Return how much of the beacon's LOS the obstacle currently covers."""
        local_t = t - self.cross_t0
        along = math.fmod(local_t + t * self.speed, self.period)
        frac = 2.0 * along / self.period - 1.0
        dist = abs(frac) if abs(frac) <= 1.0 else 1.0
        # sharp coverage peaking mid-crossing
        cover = max(0.0, 1.0 - dist * 6.0)
        return cover


class Scene3D:
    """Aggregates the world and owns the random-authority for reproducibility."""

    def __init__(self, az_amp=1.4, el_amp=0.9, speed=1.15, distractors=0,
                 obstacles=0, seed=None, motion_type=None,
                 target_shape=None, target_size=None, num_targets=1,
                 target_initial=None):
        self.rng = random.Random(seed)
        from core.orbital import RelativeOrbitModel
        self.orbit = RelativeOrbitModel(az_amp=az_amp, el_amp=el_amp,
                                        speed=speed, seed=seed,
                                        motion_type=motion_type,
                                        initial=target_initial or
                                        getattr(config, "TARGET_INITIAL", "RANDOM"))
        shape = target_shape or getattr(config, "TARGET_SHAPE", "SQUARE")
        tsize = target_size or getattr(config, "TARGET_SIZE_PX", 10)
        self.num_targets = max(1, int(num_targets))
        # designated primary target (index 0) - everything downstream (ephemeris,
        # tracker, metrics) tracks THIS one.  Extra targets get phase-delayed
        # separate orbits so they are additional independent sky objects.
        self.beacon = Beacon(self.orbit, seed=seed,
                             shape=shape, size_px=tsize, size_py=tsize,
                             target_id="TARGET-01")
        self.beacons = [self.beacon]
        for i in range(1, self.num_targets):
            extra_orbit = RelativeOrbitModel(az_amp=az_amp, el_amp=el_amp,
                                             speed=speed, seed=(seed or 7) * 31 + i,
                                             motion_type="random",
                                             initial="RANDOM")
            extra = Beacon(extra_orbit, seed=(seed or 7) + i,
                           shape=shape, size_px=tsize, size_py=tsize,
                           phase_offset=0.0, target_id=f"TARGET-{i+1:02d}")
            self.beacons.append(extra)
        self.stars = Starfield(config.NUM_STARS, seed=seed)
        self.distractors = []
        self.obstacles = []
        self.distractor_count = distractors
        self.set_distractors(distractors, reset=False)
        self.set_obstacles(obstacles)
        self._t = 0.0

    def set_distractors(self, count, reset=True):
        if reset or len(self.distractors) < count:
            self.distractors = []
            for i in range(count):
                self.distractors.append(Distractor(0.0, 0.0, self.rng, i))

    def set_obstacles(self, count):
        self.obstacles = []
        for i in range(count):
            self.obstacles.append(Obstacle(self.rng, i))

    def advance(self, dt):
        self._t += dt
        for b in self.beacons:
            b.advance(dt)
        bz, bel = self.beacon.az_deg, self.beacon.el_deg
        for d in self.distractors:
            d.advance(dt, bz, bel)
        for o in self.obstacles:
            o.advance(self._t, bz, bel)
    def set_motion_type(self, motion_type):
        """Update target motion type dynamically (PS 26169: straight_line, circular, figure_eight, random, etc.)."""
        from core.orbital import RelativeOrbitModel
        self.orbit = RelativeOrbitModel(
            az_amp=self.orbit.az_amp, el_amp=self.orbit.el_amp,
            speed=self.orbit.speed,
            motion_type=motion_type,
            initial=self.orbit.initial,
            user_pos=getattr(self.orbit, "_user_pos", None)
        )
        self.beacon.orbit = self.orbit

    def set_target_params(self, shape=None, size_px=None, size_py=None, count=None, initial=None):
        """Dynamically update target shape (SQUARE/CIRCLE/ELLIPSE/SPOT), size (5-20 px), count (1-5), or initial pos."""
        if shape is not None:
            self.beacon.shape = str(shape).upper()
            config.TARGET_SHAPE = self.beacon.shape
        if size_px is not None:
            sz = int(max(5, min(20, size_px)))
            sz_y = int(max(5, min(20, size_py))) if size_py is not None else sz
            self.beacon.size_px = sz
            self.beacon.size_py = sz_y
            config.TARGET_SIZE_PX = sz
            config.TARGET_SIZE_PY = sz_y
        if initial is not None:
            from core.orbital import RelativeOrbitModel
            self.orbit = RelativeOrbitModel(
                az_amp=self.orbit.az_amp, el_amp=self.orbit.el_amp,
                speed=self.orbit.speed,
                motion_type=self.orbit._motion_type,
                initial=initial
            )
            self.beacon.orbit = self.orbit
        if count is not None:
            count = max(1, min(5, int(count)))
            self.num_targets = count
            from core.orbital import RelativeOrbitModel
            self.beacons = [self.beacon]
            for i in range(1, count):
                extra_orbit = RelativeOrbitModel(
                    az_amp=self.orbit.az_amp, el_amp=self.orbit.el_amp,
                    speed=self.orbit.speed, seed=31 * i + 7,
                    motion_type="random", initial="RANDOM")
                extra = Beacon(extra_orbit, shape=self.beacon.shape,
                               size_px=self.beacon.size_px, size_py=self.beacon.size_py,
                               target_id=f"TARGET-{i+1:02d}")
                self.beacons.append(extra)

    def set_primary_target(self, target_idx):
        """Designate which target is primary (PS Item 8 Multi-Target Handover)."""
        idx = max(0, min(len(self.beacons) - 1, int(target_idx)))
        self.beacon = self.beacons[idx]
        return idx, self.beacon.target_id

    @property
    def targets(self):
        return self.beacons

    @property
    def active_target_idx(self):
        return self.beacons.index(self.beacon) if self.beacon in self.beacons else 0

    @property
    def time(self):
        return self._t