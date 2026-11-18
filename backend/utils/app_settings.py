"""
Persistent application settings manager.

Settings are stored in the database (``settings`` table, key ``app_settings``) and survive
container rebuilds. The SECRET_KEY is stored separately (key ``secret_key``; generated once,
never changes).

This replaces the following environment variables that were previously required in docker-compose:
  SECRET_KEY, TRUST_PROXY_HEADERS, SESSION_COOKIE_SECURE, VAPID_CONTACT_EMAIL
"""

import os
import secrets
from urllib.parse import urlsplit

from db import settings_store
from utils.json_settings_store import get_settings_revision, load_json_settings, save_json_settings
from utils.logging_config import VALID_LOG_LEVELS, get_logger

logger = get_logger(__name__)

APP_SETTINGS_KEY = 'app_settings'
SECRET_KEY_KEY = 'secret_key'

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
    # The operator's privacy notice (GDPR Art. 13): an address of their own, or a text served at
    # /privacy. Linked from the login page, the footer and My settings -> Security when set.
    "privacy_notice_url": "",
    "privacy_notice_text": "",
}

PRIVACY_NOTICE_TEXT_MAX_LENGTH = 20000

LOG_RETENTION_MAX_DAYS = 3650

_cache: dict | None = None
_cache_revision: int | None = None


def _read_secret_key() -> str | None:
    value = settings_store.get_setting(SECRET_KEY_KEY)
    return value.strip() if isinstance(value, str) and value.strip() else None


def load_or_generate_secret_key() -> str:
    """Return the persistent SECRET_KEY, generating and saving it on first call.

    Generation runs in one write transaction, so every gunicorn worker ends up with the
    same key (a worker signing sessions with its own key would log users out at random).
    """
    _warn_deprecated_env_vars()

    try:
        key = _read_secret_key()
        if key:
            logger.debug("SECRET_KEY loaded from the database")
            return key

        def _generate(current):
            if isinstance(current, str) and current.strip():
                return None, current.strip()
            fresh = secrets.token_hex(32)
            return fresh, fresh

        key = settings_store.modify_setting(SECRET_KEY_KEY, _generate)
        logger.info("New SECRET_KEY generated and saved")
        return key
    except Exception as e:
        logger.error(f"Failed to persist SECRET_KEY: {e}")
        return secrets.token_hex(32)


def load_app_settings() -> dict:
    """Load settings from the database and merge with defaults. Updates the module cache."""
    global _cache, _cache_revision
    revision = get_settings_revision(APP_SETTINGS_KEY)
    settings = load_json_settings(APP_SETTINGS_KEY, _DEFAULTS, 'App settings')
    _cache = settings
    _cache_revision = revision
    return settings


def save_app_settings(settings: dict) -> None:
    """Persist settings and update the module cache."""
    global _cache, _cache_revision
    merged = save_json_settings(APP_SETTINGS_KEY, _DEFAULTS, settings, 'App settings')
    _cache = merged
    _cache_revision = get_settings_revision(APP_SETTINGS_KEY)


def get_app_settings() -> dict:
    """Return cached settings, reloading when cold or when another worker saved.

    The revision check keeps a long-lived worker process (`gunicorn -w N`) from serving a
    stale cache forever once warm - the same multi-worker sync UserManager does
    via `_reload_users_if_changed()`.
    """
    if _cache is None or get_settings_revision(APP_SETTINGS_KEY) != _cache_revision:
        return load_app_settings()
    return _cache


def normalize_log_retention_days(value, fallback: int = _DEFAULTS["log_retention_days"]) -> int:
    """Coerce ``value`` to a whole number of days in [0, LOG_RETENTION_MAX_DAYS], or ``fallback``."""
    if isinstance(value, bool):
        return fallback
    try:
        days = int(value)
    except TypeError, ValueError:
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


def normalize_privacy_notice_url(value) -> str | None:
    """An ``http(s)://`` address (path, query and anchor allowed), ``""`` when blank, None when invalid."""
    text = value.strip() if isinstance(value, str) else ''
    if not text:
        return ''
    try:
        parts = urlsplit(text)
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        return None
    if any(char.isspace() or ord(char) < 32 for char in text):
        return None
    return text


def normalize_privacy_notice_text(value) -> str | None:
    """The notice text with line breaks kept and other control characters removed; None when too long."""
    text = value if isinstance(value, str) else ''
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = ''.join(char for char in text if char in '\n\t' or ord(char) >= 32).strip()
    return text if len(text) <= PRIVACY_NOTICE_TEXT_MAX_LENGTH else None


def get_privacy_notice() -> dict:
    """``{'url', 'text'}`` as saved (validated; an invalid stored value counts as unset)."""
    settings = get_app_settings()
    return {
        'url': normalize_privacy_notice_url(settings.get('privacy_notice_url')) or '',
        'text': normalize_privacy_notice_text(settings.get('privacy_notice_text')) or '',
    }


def privacy_notice_link(base: str = '') -> str | None:
    """Where the "Privacy notice" links point: the operator's address, else /privacy, else None."""
    notice = get_privacy_notice()
    if notice['url']:
        return notice['url']
    if notice['text']:
        return f'{base}/privacy'
    return None


def reload_app_settings() -> dict:
    """Force a reload from the database (call after a restore)."""
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
            "These settings are now managed through the admin UI (App settings -> Configuration). "
            "Please remove them from your docker-compose file."
        )
