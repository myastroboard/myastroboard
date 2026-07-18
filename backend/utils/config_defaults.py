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
    "bortle": None,  # int 1–9, or null (light pollution integration inactive)
    "sqm": None,  # float mag/arcsec², user-measured; takes priority over bortle
}

# Location preset fields added by the multi-location model (v1.2) on top of
# the base DEFAULT_LOCATION shape. Every preset in config["locations"] carries
# these; "id" is a server-generated uuid4 string, immutable for the preset's life.
LOCATION_PRESET_EXTRA_FIELDS = {
    "id": None,
    "horizon_profile": [],  # per-preset custom horizon (moved from skytonight.constraints)
    "is_install_default": False,  # exactly one preset carries True at all times
    "created_at": None,
    "updated_at": None,
}

# Default feature flags
DEFAULT_ASTRODEX = {"private": False, "map_private": False}


# Default constraint values
# NOTE (v1.2): horizon_profile is deliberately NOT part of the default
# constraints anymore - it lives on each location preset
# (LOCATION_PRESET_EXTRA_FIELDS). Keeping it here would re-inject the legacy
# key on every load_config() merge and force a config re-save each load.
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

DEFAULT_ALLSKY_CONNECTOR = {
    "enabled": False,
    "url": "",
    "label": "My AllSky Camera",
    "image_path": "current/tmp",
    "image_filename": "image.jpg",
    "export_json_path": "allskydata.json",
    "modules": {
        "live_image": {"enabled": True},
        "sensor_data": {"enabled": False},
        "keogram": {"enabled": True},
        "startrails": {"enabled": False},
        "daily_timelapse": {"enabled": False},
    },
}

DEFAULT_CONNECTORS = {
    "allsky": deepcopy(DEFAULT_ALLSKY_CONNECTOR),
}

# Default complete configuration
# NOTE (v1.2): the legacy singular "location" key is no longer part of the
# default shape - location presets live in the "locations" list. A pre-v1.2
# config that still contains "location" is migrated (and the key dropped) by
# repo_config._ensure_locations() on first load after upgrade. Brand-new
# installs get their first preset seeded from DEFAULT_LOCATION by the same
# function.
DEFAULT_CONFIG = {
    "locations": [],
    "location_configured": False,
    "min_altitude": 30,
    "astrodex": DEFAULT_ASTRODEX,
    "skytonight": DEFAULT_SKYTONIGHT,
    "connectors": DEFAULT_CONNECTORS,
}
