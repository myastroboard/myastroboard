"""Shared filesystem helpers for SkyTonight runtime state.

Since v1.2 the calculation results are stored **per location preset**:
``SKYTONIGHT_CALCULATIONS_DIR/<location_id>/<file>.json``. The legacy flat
files (pre-multi-location) are migrated once into the install default
preset's directory so existing installs keep their results after upgrade.
"""

from __future__ import annotations

import os
import shutil
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
    SKYTONIGHT_SKYMAP_FILE,
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

# Legacy flat files (single-location era) mapped to their per-location basename.
_LEGACY_RESULT_FILES = {
    SKYTONIGHT_RESULTS_FILE: _RESULTS_BASENAME,
    SKYTONIGHT_DSO_RESULTS_FILE: _DSO_BASENAME,
    SKYTONIGHT_BODIES_RESULTS_FILE: _BODIES_BASENAME,
    SKYTONIGHT_COMETS_RESULTS_FILE: _COMETS_BASENAME,
    SKYTONIGHT_SKYMAP_FILE: _SKYMAP_BASENAME,
}


def _default_location_id() -> Optional[str]:
    """Resolve the install default preset id (lazy import - avoids a cycle)."""
    try:
        from repo_config import load_config, get_install_default_location

        return get_install_default_location(load_config()).get('id')
    except Exception:
        return None


def _resolve_location_id(location_id: Optional[str]) -> Optional[str]:
    return location_id or _default_location_id()


def _legacy_alttime_files() -> list:
    """Flat *_alttime.json files left in the outputs root by pre-v1.2 runs."""
    try:
        return [
            os.path.join(SKYTONIGHT_OUTPUT_DIR, name)
            for name in os.listdir(SKYTONIGHT_OUTPUT_DIR)
            if name.endswith('_alttime.json')
        ]
    except OSError:
        return []


def migrate_legacy_results(location_id: Optional[str] = None) -> bool:
    """Move the pre-v1.2 flat result/alttime files into the install default's directories.

    Idempotent and cheap when there is nothing to migrate. Returns True when at
    least one file was moved.
    """
    legacy_alttimes = _legacy_alttime_files()
    if not any(os.path.isfile(path) for path in _LEGACY_RESULT_FILES) and not legacy_alttimes:
        return False
    target_id = _resolve_location_id(location_id)
    if not target_id:
        return False

    target_dir = os.path.join(SKYTONIGHT_CALCULATIONS_DIR, target_id)
    ensure_directory_exists(target_dir)
    moved = False
    for legacy_path, basename in _LEGACY_RESULT_FILES.items():
        if not os.path.isfile(legacy_path):
            continue
        destination = os.path.join(target_dir, basename)
        try:
            if not os.path.isfile(destination):
                shutil.move(legacy_path, destination)
            else:
                os.remove(legacy_path)
            moved = True
        except OSError:
            continue  # best-effort: a locked file just stays behind

    if legacy_alttimes:
        alttime_dir = os.path.join(SKYTONIGHT_OUTPUT_DIR, target_id)
        ensure_directory_exists(alttime_dir)
        for legacy_path in legacy_alttimes:
            destination = os.path.join(alttime_dir, os.path.basename(legacy_path))
            try:
                if not os.path.isfile(destination):
                    shutil.move(legacy_path, destination)
                else:
                    os.remove(legacy_path)
                moved = True
            except OSError:
                continue  # best-effort: a locked file just stays behind
    return moved


def get_location_results_dir(location_id: Optional[str] = None) -> str:
    """Return (and create) the calculations directory for a location preset."""
    resolved = _resolve_location_id(location_id)
    migrate_legacy_results(resolved)
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
    migrate_legacy_results(resolved)
    path = os.path.join(SKYTONIGHT_OUTPUT_DIR, resolved) if resolved else SKYTONIGHT_OUTPUT_DIR
    ensure_directory_exists(path)
    return path


def drop_location_results(location_id: str) -> bool:
    """Delete a preset's calculation results and alttime outputs.

    Called when a preset is removed or its coordinates change; the scheduler
    notices the missing results on its next poll and recomputes.
    """
    if not location_id:
        return False
    dropped = False
    for path in (
        os.path.join(SKYTONIGHT_CALCULATIONS_DIR, location_id),
        os.path.join(SKYTONIGHT_OUTPUT_DIR, location_id),
    ):
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
