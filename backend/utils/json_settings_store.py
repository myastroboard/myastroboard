"""Shared file I/O for small admin-managed JSON settings files.

``utils/app_settings.py`` and ``utils/security_settings.py`` each persist a small
settings dict to ``DATA_DIR/*.json``, merged against a defaults dict, with a
module-level cache in front of the file. Before this module existed they each
hand-rolled an identical copy of the load/merge/exception-handling and
save/merge/write logic; it is extracted here so a fix to the mechanism (the
mtime check below, for one) applies to every settings file at once.

Each caller keeps its own module-level ``_cache`` / ``_cache_mtime`` variables and its
own ``load_/save_/get_/reload_`` wrapper functions rather than sharing a stateful
object - existing tests reset a module's cache by setting ``<module>._cache = None``
directly, and that contract is preserved by keeping the cache in the calling module.
"""

import json
import os

from utils.logging_config import get_logger

logger = get_logger(__name__)


def load_json_settings(file_path: str, defaults: dict, label: str) -> dict:
    """Read *file_path*, merge its known keys over *defaults*.

    A missing file, invalid JSON, or any other read error falls back to the defaults
    (with a warning) rather than raising - a hand-edited or momentarily-missing
    settings file must not make the whole instance unusable.
    """
    settings = dict(defaults)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                saved = json.load(f)
            for key in defaults:
                if key in saved:
                    settings[key] = saved[key]
            logger.debug(f"{label} loaded from disk")
        except Exception as e:
            logger.warning(f"Could not read {file_path}, using defaults: {e}")
    return settings


def save_json_settings(file_path: str, defaults: dict, settings: dict, label: str) -> dict:
    """Merge *settings* over *defaults* and write the result to *file_path*."""
    merged = dict(defaults)
    for key in defaults:
        if key in settings:
            merged[key] = settings[key]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(merged, f, indent=2)
    logger.info(f"{label} saved")
    return merged


def get_file_mtime(file_path: str) -> float | None:
    """Return *file_path*'s mtime, or None when it does not exist or cannot be read."""
    try:
        return os.path.getmtime(file_path) if os.path.exists(file_path) else None
    except OSError:
        return None
