"""
Persistent application settings manager.

Settings are stored in DATA_DIR/app_settings.json and survive container rebuilds.
The SECRET_KEY is stored separately in DATA_DIR/secret_key.txt (generated once, never changes).

This replaces the following environment variables that were previously required in docker-compose:
  SECRET_KEY, TRUST_PROXY_HEADERS, SESSION_COOKIE_SECURE, VAPID_CONTACT_EMAIL
"""

import os
import secrets
from urllib.parse import urlsplit

from utils.json_settings_store import get_file_mtime, load_json_settings, save_json_settings
from utils.logging_config import VALID_LOG_LEVELS, get_logger

logger = get_logger(__name__)

_DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
_SECRET_KEY_FILE = os.path.join(_DATA_DIR, 'secret_key.txt')
_APP_SETTINGS_FILE = os.path.join(_DATA_DIR, 'app_settings.json')

_DEFAULTS: dict = {
    "vapid_contact_email": "",
    "trust_proxy_headers": False,
    "session_cookie_secure": False,
    "search_engine_indexing": False,
    # Days a log line is kept (usernames and IP addresses are personal data); 0 = size-based rotation only
    "log_retention_days": 90,
    # Log file / console levels; the LOG_LEVEL / CONSOLE_LOG_LEVEL environment variables win when set
    "log_level": "INFO",
    "console_log_level": "WARNING",
    # Address other software reaches this instance at (Astrodex stream, MyAstroShine return
    # address); "" = derived from the request. Required under HA ingress, whose URL needs an HA login.
    "external_base_url": "",
}

LOG_RETENTION_MAX_DAYS = 3650

_cache: dict | None = None
_cache_mtime: float | None = None


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
    global _cache, _cache_mtime
    settings = load_json_settings(_APP_SETTINGS_FILE, _DEFAULTS, 'App settings')
    _cache = settings
    _cache_mtime = get_file_mtime(_APP_SETTINGS_FILE)
    return settings


def save_app_settings(settings: dict) -> None:
    """Persist settings to disk and update the module cache."""
    global _cache, _cache_mtime
    merged = save_json_settings(_APP_SETTINGS_FILE, _DEFAULTS, settings, 'App settings')
    _cache = merged
    _cache_mtime = get_file_mtime(_APP_SETTINGS_FILE)


def get_app_settings() -> dict:
    """Return cached settings, reloading when cold or when the file changed on disk.

    The mtime check keeps a long-lived worker process (`gunicorn -w N`) from serving a
    stale cache forever once warm - the same multi-worker sync UserManager already does
    for users.json via `_reload_users_if_changed()`.
    """
    if _cache is None or get_file_mtime(_APP_SETTINGS_FILE) != _cache_mtime:
        return load_app_settings()
    return _cache


def normalize_log_retention_days(value, fallback: int = _DEFAULTS["log_retention_days"]) -> int:
    """Coerce ``value`` to a whole number of days in [0, LOG_RETENTION_MAX_DAYS], or ``fallback``."""
    if isinstance(value, bool):
        return fallback
    try:
        days = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(days, 0), LOG_RETENTION_MAX_DAYS)


def get_log_retention_days() -> int:
    """Current log retention in days (0 = disabled); registered as the logging retention provider."""
    return normalize_log_retention_days(get_app_settings().get("log_retention_days"))


def normalize_log_level(value, fallback: str) -> str:
    """Upper-cased log level name when valid (DEBUG ... CRITICAL), else ``fallback``."""
    name = str(value).strip().upper() if isinstance(value, str) else ''
    return name if name in VALID_LOG_LEVELS else fallback


def get_log_levels() -> tuple:
    """``(file_level, console_level)`` chosen in the UI; registered as the logging level provider."""
    settings = get_app_settings()
    return (
        normalize_log_level(settings.get("log_level"), _DEFAULTS["log_level"]),
        normalize_log_level(settings.get("console_log_level"), _DEFAULTS["console_log_level"]),
    )


def normalize_external_base_url(value) -> str | None:
    """``http(s)://host[:port][/path]`` without trailing slash, ``""`` when blank, None when invalid."""
    text = value.strip() if isinstance(value, str) else ''
    if not text:
        return ''
    try:
        parts = urlsplit(text)
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.query or parts.fragment:
        return None
    if parts.username or parts.password:
        return None
    return text.rstrip('/')


def get_external_base_url() -> str:
    """Saved external base URL (validated), or ``""`` when unset."""
    return normalize_external_base_url(get_app_settings().get("external_base_url")) or ''


def reload_app_settings() -> dict:
    """Force a reload from disk (call after external file changes)."""
    global _cache
    _cache = None
    return load_app_settings()


def _warn_deprecated_env_vars() -> None:
    """Log a one-time warning if legacy env vars are detected."""
    deprecated = [
        v
        for v in ('SECRET_KEY', 'TRUST_PROXY_HEADERS', 'SESSION_COOKIE_SECURE', 'VAPID_CONTACT_EMAIL')
        if os.environ.get(v)
    ]
    if deprecated:
        logger.warning(
            f"Deprecated environment variables detected and ignored: {', '.join(deprecated)}. "
            "These settings are now managed through the admin UI (Parameters → Advanced). "
            "Please remove them from your docker-compose file."
        )
