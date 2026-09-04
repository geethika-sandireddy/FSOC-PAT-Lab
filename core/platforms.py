"""
core/platforms.py
-----------------
Platform mode profiles required by PS 26169:
  - Satellite-Satellite  (orbital, vacuum, no atmosphere)
  - UAV-Satellite        (mixed dynamics, moderate atmosphere)
  - UAV-UAV              (wind-dominated, heavy atmosphere)

Each mode defines default disturbance levels, dynamic parameters, and
atmospheric conditions.  Users can override any parameter.
"""

PLATFORM_MODES = {
    "SATELLITE_SATELLITE": {
        "description": "LEO/MEO satellite-to-satellite FSOC link (vacuum)",
        "range_km": 1000.0,
        "az_amp": 1.4, "el_amp": 0.9, "speed": 1.15,
        "disturbances": {
            "turbulence": 0,       # no atmosphere
            "vibration": 5,        # reaction-wheel jitter
            "sensor_noise": 5,     # thermal noise only
            "jerk_prob": 1,        # occasional slew correction
            "beacon_fade": 0,      # no atmospheric scintillation
        },
        "atmosphere": "CLEAR",
        "motion_default": "straight_line",
        "gimbal_max_pan": 10.0, "gimbal_max_tilt": 8.0,
        "target_speed_mult": 1.0,
        "noise_types": ["gaussian"],
    },
    "UAV_SATELLITE": {
        "description": "UAV-to-satellite FSOC link (atmosphere + orbital)",
        "range_km": 500.0,
        "az_amp": 2.0, "el_amp": 1.2, "speed": 1.5,
        "disturbances": {
            "turbulence": 25,      # atmospheric scintillation
            "vibration": 15,       # engine + wind vibration
            "sensor_noise": 10,    # moderate
            "jerk_prob": 3,        # wind gusts
            "beacon_fade": 20,     # atmospheric signal fade
        },
        "atmosphere": "HAZE",
        "motion_default": "figure_eight",
        "gimbal_max_pan": 8.0, "gimbal_max_tilt": 6.0,
        "target_speed_mult": 1.3,
        "noise_types": ["gaussian", "poisson"],
    },
    "UAV_UAV": {
        "description": "UAV-to-UAV FSOC link (heavy atmosphere, wind)",
        "range_km": 50.0,
        "az_amp": 3.0, "el_amp": 2.0, "speed": 2.0,
        "disturbances": {
            "turbulence": 50,      # strong atmospheric effects
            "vibration": 30,       # heavy wind + engine
            "sensor_noise": 20,    # more noise at range
            "jerk_prob": 6,        # wind gusts
            "beacon_fade": 35,     # signal degradation
        },
        "atmosphere": "HAZE",
        "motion_default": "circular",
        "gimbal_max_pan": 6.0, "gimbal_max_tilt": 5.0,
        "target_speed_mult": 1.8,
        "noise_types": ["gaussian", "salt_pepper", "poisson"],
    },
}

ATMOSPHERIC_CONDITIONS = {
    "CLEAR":   {"contrast": 1.0, "brightness": 1.0, "blur": 0, "veil": 0.0,
                "streaks": 0, "gain": 1.0, "description": "Clear sky (baseline)"},
    "HAZE":    {"contrast": 0.75, "brightness": 1.05, "blur": 1, "veil": 0.15,
                "streaks": 0, "gain": 1.0, "description": "Light haze (scattering)"},
    "FOG":     {"contrast": 0.45, "brightness": 1.10, "blur": 3, "veil": 0.35,
                "streaks": 0, "gain": 0.9, "description": "Moderate fog (heavy scattering)"},
    "RAIN":    {"contrast": 0.80, "brightness": 0.90, "blur": 1, "veil": 0.05,
                "streaks": 12, "gain": 1.0, "description": "Rain (droplet streaks)"},
    "LOW_LIGHT": {"contrast": 0.60, "brightness": 0.35, "blur": 0, "veil": 0.0,
                  "streaks": 0, "gain": 2.5, "description": "Low light (night ops)"},
}
