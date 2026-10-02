"""Shared storage for the small admin-managed settings dicts.

``utils/app_settings.py`` and ``utils/security_settings.py`` each persist a small
settings dict, merged against a defaults dict, with a module-level cache in front of
it. The dicts live in the ``settings`` table (one key each, see ``db/settings_store.py``);
this module holds the shared load/merge/save logic so a fix applies to both.

Each caller keeps its own module-level ``_cache`` / ``_cache_revision`` variables and its
own ``load_/save_/get_/reload_`` wrapper functions rather than sharing a stateful
object - existing tests reset a module's cache by setting ``<module>._cache = None``
directly, and that contract is preserved by keeping the cache in the calling module.
"""

from db import settings_store
from utils.logging_config import get_logger

logger = get_logger(__name__)


def load_json_settings(key: str, defaults: dict, label: str) -> dict:
    """Read setting *key*, merge its known keys over *defaults*.

    A missing value, a value of the wrong shape, or any read error falls back to the
    defaults (with a warning) rather than raising - a damaged settings value must not
    make the whole instance unusable.
    """
    settings = dict(defaults)
    try:
        saved = settings_store.get_setting(key)
    except Exception as e:
        logger.warning(f"Could not read {label}, using defaults: {e}")
        return settings
    if saved is None:
        return settings
    if not isinstance(saved, dict):
        logger.warning(f"{label} are not an object, using defaults")
        return settings
    for name in defaults:
        if name in saved:
            settings[name] = saved[name]
    logger.debug(f"{label} loaded")
    return settings


def save_json_settings(key: str, defaults: dict, settings: dict, label: str) -> dict:
    """Merge *settings* over *defaults* and store the result under *key*."""
    merged = dict(defaults)
    for name in defaults:
        if name in settings:
            merged[name] = settings[name]
    settings_store.put_setting(key, merged)
    logger.info(f"{label} saved")
    return merged


def get_settings_revision(key: str) -> int | None:
    """Revision of setting *key*, or None when it cannot be read (forces a reload next time)."""
    try:
        return settings_store.setting_revision(key)
    except Exception:
        return None
