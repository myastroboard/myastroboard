"""Shared filesystem helpers for SkyTonight runtime state."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from constants import (
    SKYTONIGHT_BODIES_RESULTS_FILE,
    SKYTONIGHT_CALCULATIONS_DIR,
    SKYTONIGHT_CATALOGUES_DIR,
    SKYTONIGHT_COMETS_RESULTS_FILE,
    SKYTONIGHT_DATASET_FILE,
    SKYTONIGHT_DIR,
    SKYTONIGHT_DSO_RESULTS_FILE,
    SKYTONIGHT_LOGS_DIR,
    SKYTONIGHT_OUTPUT_DIR,
    SKYTONIGHT_RESULTS_FILE,
    SKYTONIGHT_RUNTIME_DIR,
    SKYTONIGHT_SCHEDULER_LOCK_FILE,
    SKYTONIGHT_SCHEDULER_STATUS_FILE,
    SKYTONIGHT_SCHEDULER_TRIGGER_FILE,
)
from utils import ensure_directory_exists, load_json_file, save_json_file, slugify_location_name


def ensure_skytonight_directories(location_name: Optional[str] = None) -> Dict[str, str]:
    """Ensure the SkyTonight shared directory layout exists."""
    directories = {
        'root': SKYTONIGHT_DIR,
        'catalogues': SKYTONIGHT_CATALOGUES_DIR,
        'calculations': SKYTONIGHT_CALCULATIONS_DIR,
        'outputs': SKYTONIGHT_OUTPUT_DIR,
        'logs': SKYTONIGHT_LOGS_DIR,
        'runtime': SKYTONIGHT_RUNTIME_DIR,
    }

    for path in directories.values():
        ensure_directory_exists(path)

    if location_name:
        location_root = get_location_directory(location_name)
        directories['location'] = location_root
        directories['location_logs'] = os.path.join(location_root, 'logs')
        directories['location_outputs'] = os.path.join(location_root, 'outputs')
        directories['location_runtime'] = os.path.join(location_root, 'runtime')
        for key in ('location', 'location_logs', 'location_outputs', 'location_runtime'):
            ensure_directory_exists(directories[key])

    return directories


def get_location_directory(location_name: str) -> str:
    """Return the root SkyTonight directory for a specific observing location."""
    slug = slugify_location_name(location_name)
    return os.path.join(SKYTONIGHT_DIR, slug)


def get_dataset_file() -> str:
    return SKYTONIGHT_DATASET_FILE


def get_scheduler_status_file() -> str:
    ensure_skytonight_directories()
    return SKYTONIGHT_SCHEDULER_STATUS_FILE


def get_scheduler_trigger_file() -> str:
    ensure_skytonight_directories()
    return SKYTONIGHT_SCHEDULER_TRIGGER_FILE


def get_scheduler_lock_file() -> str:
    ensure_skytonight_directories()
    return SKYTONIGHT_SCHEDULER_LOCK_FILE


def load_scheduler_status(default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return load_json_file(get_scheduler_status_file(), default=default or {})


def save_scheduler_status(payload: Dict[str, Any]) -> bool:
    return save_json_file(get_scheduler_status_file(), payload)


def append_scheduler_log(message: str, file_name: str = 'scheduler.log', max_entries: int = 5) -> str:
    ensure_skytonight_directories()
    log_path = os.path.join(SKYTONIGHT_LOGS_DIR, file_name)
    with open(log_path, 'a', encoding='utf-8') as file_obj:
        file_obj.write(message)
        if not message.endswith('\n'):
            file_obj.write('\n')
    _trim_log_file(log_path, max_entries)
    return log_path


def _trim_log_file(log_path: str, max_lines: int) -> None:
    """Keep only the last *max_lines* non-empty lines in *log_path*."""
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = [line for line in f.readlines() if line.strip()]
        if len(lines) > max_lines:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.writelines(lines[-max_lines:])
    except Exception:
        pass  # log rotation is best-effort; failure must not abort the caller


def get_results_file() -> str:
    """Return the path to the SkyTonight calculation results cache file."""
    ensure_skytonight_directories()
    return SKYTONIGHT_RESULTS_FILE


def has_calculation_results() -> bool:
    """Return True if all calculations are complete (metadata summary file exists and not in-progress)."""
    if not (os.path.isfile(SKYTONIGHT_RESULTS_FILE) and os.path.getsize(SKYTONIGHT_RESULTS_FILE) > 0):
        return False
    data = load_json_file(SKYTONIGHT_RESULTS_FILE, default={})
    return not bool(data.get('metadata', {}).get('in_progress', False))


def has_bodies_results() -> bool:
    """Return True if solar body calculation results are available."""
    return os.path.isfile(SKYTONIGHT_BODIES_RESULTS_FILE) and os.path.getsize(SKYTONIGHT_BODIES_RESULTS_FILE) > 0


def has_comets_results() -> bool:
    """Return True if comet calculation results are available."""
    return os.path.isfile(SKYTONIGHT_COMETS_RESULTS_FILE) and os.path.getsize(SKYTONIGHT_COMETS_RESULTS_FILE) > 0


def has_dso_results() -> bool:
    """Return True if deep-sky object calculation results are available."""
    return os.path.isfile(SKYTONIGHT_DSO_RESULTS_FILE) and os.path.getsize(SKYTONIGHT_DSO_RESULTS_FILE) > 0
