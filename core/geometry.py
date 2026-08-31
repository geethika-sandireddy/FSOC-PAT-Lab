"""
core/geometry.py
----------------
Minimal, dependency-free 3D geometry used across the whole simulator:

  * a simple XYZ vector type built on plain tuples (fast, no allocations
    beyond the numpy path where it matters),
  * rotation matrices for yaw (pan) about Y and pitch (tilt) about X,
  * the line-of-sight direction for an (azimuth, elevation) pair,
  * a pinhole-camera projection for the virtual sensor,
  * projection helpers reused by the external 3D mission view.

Conventions
-----------
World frame (right-handed):
    +X  right, +Y  up, +Z  forward (Satellite A boresight nominal).
azimuth is rotation about +Y (positive = to the right),
elevation is rotation about +X (positive = upwards).
"""

import math

import numpy as np


def azel_unit(az_deg, el_deg):
    """Unit forward vector for an (azimuth, elevation) in degrees."""
    az = math.radians(az_deg)
    el = math.radians(el_deg)
    ce = math.cos(el)
    return (ce * math.sin(az), math.sin(el), ce * math.cos(az))


def azel_to_vec(az_deg, el_deg, r):
    """3D point at range r along a given (az, el) direction."""
    fx, fy, fz = azel_unit(az_deg, el_deg)
    return (r * fx, r * fy, r * fz)


def vec_to_azel(x, y, z):
    """Convert a 3D direction into (azimuth_deg, elevation_deg)."""
    az = math.degrees(math.atan2(x, z))                  # az about +Y
    el = math.degrees(math.atan2(y, math.hypot(x, z)))   # el about +X
    return az, el


def rot_y(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def rot_x(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def gimbal_frame(pan_deg, tilt_deg):
    """Camera basis [right, up, forward] for a pan-tilt gimbal.

    forward follows the (az, el) direction; right is perpendicular to the
    world-up and points to the camera's right; up completes the right-handed
    frame (tilted slightly *backward* for a camera pitched upward).
    """
    fwd = np.array(azel_unit(pan_deg, tilt_deg), dtype=np.float64)
    world_up = np.array([0.0, 1.0, 0.0])
    right = np.cross(world_up, fwd)
    n = math.sqrt(right[0] ** 2 + right[1] ** 2 + right[2] ** 2)
    if n < 1e-12:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / n
    up = np.cross(fwd, right)
    return right, up, fwd


def project_point_into_camera(world_pos, cam_pos, cam_basis, focal_px, cu, cv):
    """Project a world point into the pinhole sensor.

    Returns (u, v) sensor pixel coordinates, or None if the point lies
    behind the camera.  cam_basis = (right, up, forward) column vectors.
    """
    dx = world_pos[0] - cam_pos[0]
    dy = world_pos[1] - cam_pos[1]
    dz = world_pos[2] - cam_pos[2]
    right, up, fwd = cam_basis
    qx = right[0] * dx + right[1] * dy + right[2] * dz
    qy = up[0] * dx + up[1] * dy + up[2] * dz
    qz = fwd[0] * dx + fwd[1] * dy + fwd[2] * dz
    if qz <= 1e-6:
        return None
    u = cu + focal_px * (qx / qz)
    v = cv - focal_px * (qy / qz)
    return u, v


def project_point_into_camera_frame(world_pos, cam_pos, cam_basis):
    dx = world_pos[0] - cam_pos[0]
    dy = world_pos[1] - cam_pos[1]
    dz = world_pos[2] - cam_pos[2]
    right, up, fwd = cam_basis
    return (right[0] * dx + right[1] * dy + right[2] * dz,
            up[0] * dx + up[1] * dy + up[2] * dz,
            fwd[0] * dx + fwd[1] * dy + fwd[2] * dz)


def ray_to_azel(px, py, focal_px, cam_basis, cu=0.0, cv=0.0):
    """Invert projection: turn a sensor pixel into a world LOS (az, el).

    This is how the detection+tracking feed converts a measured pixel offset
    into the *world* LOS that the control loop points at - the measurement
    is physically grounded (uses only the pixel plus the encoder pose).
    """
    right, up, fwd = cam_basis
    dwx = (px - cu) / focal_px
    dwy = (cv - py) / focal_px
    n = dwx * right + dwy * up + fwd
    nlen = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
    n = n / nlen
    return vec_to_azel(n[0], n[1], n[2])


def sd_angle_deg(a, b):
    """Signed small angle between two normalized directions (deg)."""
    return math.degrees(math.acos(max(-1.0, min(1.0,
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))))