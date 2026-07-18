"""Shared filesystem helpers for SkyTonight runtime state.

Since v1.2 the calculation results are stored **per location preset**:
``SKYTONIGHT_CALCULATIONS_DIR/<location_id>/<file>.json``. Pre-v1.2 flat
result/alttime files are deleted at container startup (see entrypoint.sh);
a location with no results yet simply gets picked up by the next scheduler run.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Optional

from utils.constants import (
    SKYTONIGHT_CALCULATIONS_DIR,
    SKYTONIGHT_CATALOGUES_DIR,
    SKYTONIGHT_DATASET_FILE,
    SKYTONIGHT_DIR,
    SKYTONIGHT_LOGS_DIR,
    SKYTONIGHT_OUTPUT_DIR,
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


# ---------------------------------------------------------------------------
# Per-location calculation results (v1.2)
# ---------------------------------------------------------------------------

# Basenames of the per-location result files inside <calculations>/<location_id>/.
_RESULTS_BASENAME = 'calculation_results.json'
_DSO_BASENAME = 'dso_results.json'
_BODIES_BASENAME = 'bodies_results.json'
_COMETS_BASENAME = 'comets_results.json'
_SKYMAP_BASENAME = 'skymap_data.json'


def _default_location_id() -> Optional[str]:
    """Resolve the install default preset id (lazy import - avoids a cycle)."""
    try:
        from utils.repo_config import load_config, get_install_default_location

        return get_install_default_location(load_config()).get('id')
    except Exception:
        return None


def _resolve_location_id(location_id: Optional[str]) -> Optional[str]:
    return location_id or _default_location_id()


def get_location_results_dir(location_id: Optional[str] = None) -> str:
    """Return (and create) the calculations directory for a location preset."""
    resolved = _resolve_location_id(location_id)
    path = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, resolved) if resolved else SKYTONIGHT_CALCULATIONS_DIR
    ensure_directory_exists(path)
    return path


def get_results_file(location_id: Optional[str] = None) -> str:
    """Return the path to the SkyTonight calculation results summary for a location."""
    return os.path.join(get_location_results_dir(location_id), _RESULTS_BASENAME)


def get_dso_results_file(location_id: Optional[str] = None) -> str:
    return os.path.join(get_location_results_dir(location_id), _DSO_BASENAME)


def get_bodies_results_file(location_id: Optional[str] = None) -> str:
    return os.path.join(get_location_results_dir(location_id), _BODIES_BASENAME)


def get_comets_results_file(location_id: Optional[str] = None) -> str:
    return os.path.join(get_location_results_dir(location_id), _COMETS_BASENAME)


def get_skymap_file(location_id: Optional[str] = None) -> str:
    return os.path.join(get_location_results_dir(location_id), _SKYMAP_BASENAME)


def get_alttime_dir(location_id: Optional[str] = None) -> str:
    """Return (and create) the per-location directory for *_alttime.json files."""
    resolved = _resolve_location_id(location_id)
    path = os.path.join(SKYTONIGHT_OUTPUT_DIR, resolved) if resolved else SKYTONIGHT_OUTPUT_DIR
    ensure_directory_exists(path)
    return path


def _safe_location_dir(base_dir: str, location_id: str) -> str:
    """Resolve *location_id* under *base_dir* and verify it doesn't escape it.

    location_id is always a server-generated UUID (see
    repo_config.new_location_preset), but this is re-verified here rather than
    trusted from the caller: CodeQL (CWE-022) requires the sanitizer to be
    called directly at each file operation's call site. Raises ValueError if
    the resolved path would escape base_dir.
    """
    base_real = os.path.realpath(base_dir)
    resolved = os.path.realpath(os.path.join(base_dir, location_id))
    try:
        inside_base_dir = os.path.commonpath([base_real, resolved]) == base_real
    except ValueError:
        inside_base_dir = False
    if not inside_base_dir:
        raise ValueError(f'Path outside {base_dir!r}: {location_id!r}')
    return resolved


def drop_location_results(location_id: str) -> bool:
    """Delete a preset's calculation results and alttime outputs.

    Called when a preset is removed or its coordinates change; the scheduler
    notices the missing results on its next poll and recomputes.
    """
    if not location_id:
        return False
    dropped = False
    for base_dir in (SKYTONIGHT_CALCULATIONS_DIR, SKYTONIGHT_OUTPUT_DIR):
        try:
            path = _safe_location_dir(base_dir, location_id)
        except ValueError:
            continue
        if not os.path.isdir(path):
            continue
        try:
            shutil.rmtree(path)
            dropped = True
        except OSError:
            continue
    return dropped


def has_calculation_results(location_id: Optional[str] = None) -> bool:
    """Return True if all calculations are complete (summary exists and not in-progress)."""
    results_file = get_results_file(location_id)
    if not (os.path.isfile(results_file) and os.path.getsize(results_file) > 0):
        return False
    data = load_json_file(results_file, default={})
    return not bool(data.get('metadata', {}).get('in_progress', False))


def has_bodies_results(location_id: Optional[str] = None) -> bool:
    """Return True if solar body calculation results are available."""
    path = get_bodies_results_file(location_id)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def has_comets_results(location_id: Optional[str] = None) -> bool:
    """Return True if comet calculation results are available."""
    path = get_comets_results_file(location_id)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def has_dso_results(location_id: Optional[str] = None) -> bool:
    """Return True if deep-sky object calculation results are available."""
    path = get_dso_results_file(location_id)
    return os.path.isfile(path) and os.path.getsize(path) > 0
