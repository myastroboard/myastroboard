"""
Default configuration constants for SkyTonight
Centralized location for all default configuration values
"""

from copy import deepcopy

# Default location configuration
DEFAULT_LOCATION = {
    "name": "Paris",
    "latitude": 48.866669,
    "longitude": 2.33333,
    "elevation": 35,
    "timezone": "Europe/Paris",
    "bortle": None,   # int 1–9, or null (light pollution integration inactive)
    "sqm": None,      # float mag/arcsec², user-measured; takes priority over bortle
}

# Default feature flags
DEFAULT_ASTRODEX = {
    "private": False
}


# Default constraint values
DEFAULT_CONSTRAINTS = {
    "altitude_constraint_min": 30,
    "altitude_constraint_max": 80,
    "airmass_constraint": 2,
    "size_constraint_min": 0,
    "size_constraint_max": 300,
    "moon_separation_min": 45,
    "moon_separation_use_illumination": True,
    "fraction_of_time_observable_threshold": 0.5,
    "north_to_east_ccw": False,
    "horizon_profile": [],
}


DEFAULT_SKYTONIGHT_SCHEDULER = {
    "mode": "fallback-6h",
    "server_time_valid": False,
    "next_run": None,
    "last_run": None,
}


DEFAULT_SKYTONIGHT_DATASETS = {
    "catalogues": {
        "deep_sky": True,
        "bodies": True,
        "comets": True,
    },
    "comets": {
        "source": "mpc+jpl",
        "auto_update": True,
    },
}


DEFAULT_SKYTONIGHT = {
    "enabled": True,
    "constraints_always_enabled": True,
    "preferred_name_order": ["OpenNGC", "Messier", "OpenIC", "Caldwell"],
    "constraints": deepcopy(DEFAULT_CONSTRAINTS),
    "scheduler": deepcopy(DEFAULT_SKYTONIGHT_SCHEDULER),
    "datasets": deepcopy(DEFAULT_SKYTONIGHT_DATASETS),
}

# Default complete configuration
DEFAULT_CONFIG = {
    "location": DEFAULT_LOCATION,
    "location_configured": False,
    "min_altitude": 30,
    "astrodex": DEFAULT_ASTRODEX,
    "skytonight": DEFAULT_SKYTONIGHT,
}