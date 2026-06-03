"""
Persistent application settings manager.

Settings are stored in DATA_DIR/app_settings.json and survive container rebuilds.
The SECRET_KEY is stored separately in DATA_DIR/secret_key.txt (generated once, never changes).

This replaces the following environment variables that were previously required in docker-compose:
  SECRET_KEY, TRUST_PROXY_HEADERS, SESSION_COOKIE_SECURE, VAPID_CONTACT_EMAIL
"""
import json
import os
import secrets

from logging_config import get_logger

logger = get_logger(__name__)

_DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
_SECRET_KEY_FILE = os.path.join(_DATA_DIR, 'secret_key.txt')
_APP_SETTINGS_FILE = os.path.join(_DATA_DIR, 'app_settings.json')

_DEFAULTS: dict = {
    "vapid_contact_email": "",
    "trust_proxy_headers": False,
    "session_cookie_secure": False,
}

_cache: dict | None = None


def load_or_generate_secret_key() -> str:
    """Return the persistent SECRET_KEY, generating and saving it on first call."""
    _warn_deprecated_env_vars()

    os.makedirs(_DATA_DIR, exist_ok=True)
    if os.path.exists(_SECRET_KEY_FILE):
        try:
            with open(_SECRET_KEY_FILE, 'r') as f:
                key = f.read().strip()
            if key:
                logger.debug("SECRET_KEY loaded from data directory")
                return key
        except Exception as e:
            logger.warning(f"Could not read secret_key.txt, regenerating: {e}")

    key = secrets.token_hex(32)
    try:
        with open(_SECRET_KEY_FILE, 'w') as f:
            f.write(key)
        logger.info(f"New SECRET_KEY generated and saved to {_SECRET_KEY_FILE}")
    except Exception as e:
        logger.error(f"Failed to persist SECRET_KEY to disk: {e}")

    return key


def load_app_settings() -> dict:
    """Load settings from disk and merge with defaults. Updates the module cache."""
    global _cache
    settings = dict(_DEFAULTS)
    if os.path.exists(_APP_SETTINGS_FILE):
        try:
            with open(_APP_SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            for key in _DEFAULTS:
                if key in saved:
                    settings[key] = saved[key]
            logger.debug("App settings loaded from disk")
        except Exception as e:
            logger.warning(f"Could not read app_settings.json, using defaults: {e}")
    _cache = settings
    return settings


def save_app_settings(settings: dict) -> None:
    """Persist settings to disk and update the module cache."""
    global _cache
    merged = dict(_DEFAULTS)
    for key in _DEFAULTS:
        if key in settings:
            merged[key] = settings[key]
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_APP_SETTINGS_FILE, 'w') as f:
        json.dump(merged, f, indent=2)
    _cache = merged
    logger.info("App settings saved")


def get_app_settings() -> dict:
    """Return cached settings, loading from disk if the cache is cold."""
    if _cache is None:
        return load_app_settings()
    return _cache


def reload_app_settings() -> dict:
    """Force a reload from disk (call after external file changes)."""
    global _cache
    _cache = None
    return load_app_settings()


def _warn_deprecated_env_vars() -> None:
    """Log a one-time warning if legacy env vars are detected."""
    deprecated = [v for v in ('SECRET_KEY', 'TRUST_PROXY_HEADERS', 'SESSION_COOKIE_SECURE', 'VAPID_CONTACT_EMAIL')
                  if os.environ.get(v)]
    if deprecated:
        logger.warning(
            f"Deprecated environment variables detected and ignored: {', '.join(deprecated)}. "
            "These settings are now managed through the admin UI (Parameters → Advanced). "
            "Please remove them from your docker-compose file."
        )
