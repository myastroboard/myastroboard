"""
Manage configuration loading and saving
"""

from copy import deepcopy

from constants import CONFIG_FILE
from config_defaults import DEFAULT_CONFIG
from utils import load_json_file, save_json_file, safe_file_exists


def _merge_defaults(config, defaults):
    """Recursively merge missing default keys into a config payload."""
    if not isinstance(defaults, dict):
        return deepcopy(defaults)

    merged = deepcopy(defaults)
    if not isinstance(config, dict):
        return merged

    for key, value in config.items():
        default_value = merged.get(key)
        if isinstance(value, dict) and isinstance(default_value, dict):
            merged[key] = _merge_defaults(value, default_value)
        else:
            merged[key] = value

    return merged


def load_config():
    """Load configuration from file"""
    if not safe_file_exists(CONFIG_FILE):
        # No config file yet — brand-new install, keep location_configured=False
        return deepcopy(DEFAULT_CONFIG)
    raw = load_json_file(CONFIG_FILE, {})
    merged = _merge_defaults(raw, DEFAULT_CONFIG)
    # Strip legacy top-level 'constraints' key - constraints live exclusively
    # under skytonight.constraints from now on.
    merged.pop('constraints', None)
    # Existing installs pre-date the location_configured flag; treat them as configured
    if 'location_configured' not in raw:
        merged['location_configured'] = True
    return merged


def save_config(config):
    """Save configuration to file"""
    return save_json_file(CONFIG_FILE, config)
