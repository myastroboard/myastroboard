"""
Instance security settings manager (trusted networks + global 2FA switch).

Settings are stored in DATA_DIR/security_settings.json and survive container rebuilds.
This mirrors utils/app_settings.py (same _DEFAULTS / load_ / save_ / get_ / reload_ shape),
deliberately kept out of data/config.json: the two validation rules below are stateful
(old list vs. new list) and would not fit the generic /api/config merge handler.

The file is intentionally excluded from /api/backup/download and /api/config/export:
trusted network ranges are host/deployment-specific, same reasoning as trust_proxy_headers.

Two features consume the trusted-network list, for opposite purposes:
  - two-factor authentication trusts a network to SKIP the OTP step,
  - "local" accounts trust a network to ALLOW the login at all.
They share this data source only; their business logic stays independent.
"""

import ipaddress
import os

from utils.json_settings_store import get_file_mtime, load_json_settings, save_json_settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

_DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
_SECURITY_SETTINGS_FILE = os.path.join(_DATA_DIR, 'security_settings.json')

# Loopback is always trusted and is never written to the file, so clearing the
# configured list can never lock an admin out of local access.
ALWAYS_TRUSTED_NETWORKS = ('127.0.0.0/8', '::1/128')

# A "trusted network" in this app is meant to be a home/office LAN, at most - anything
# broader than this is almost certainly a typo (a dropped digit turning /24 into /2) and
# gets a log warning so it doesn't fail silently. Not a hard limit: a real admin choice
# to trust something this broad is still honored, just called out.
_UNUSUALLY_BROAD_PREFIX = {4: 8, 6: 32}

_DEFAULTS: dict = {
    "trusted_networks": [],
    "two_factor_enabled": False,
}

_cache: dict | None = None
_cache_mtime: float | None = None


def normalize_network(value) -> str:
    """Return the canonical CIDR form of a network or bare IP.

    ``ipaddress.ip_network(..., strict=False)`` accepts both IPv4 and IPv6 and both
    ``192.168.1.0/24`` and a bare ``192.168.1.5``. Storing the normalized string keeps
    ``192.168.1.5/24`` and ``192.168.1.0/24`` from landing in the list as two entries.

    Raises ValueError when the value cannot be parsed as a network.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid trusted network: {value!r}")
    normalized = str(ipaddress.ip_network(value.strip(), strict=False))
    _warn_if_unusually_broad(normalized)
    return normalized


def normalize_networks(values) -> list[str]:
    """Normalize a list of networks, dropping duplicates and preserving order."""
    if not isinstance(values, (list, tuple)):
        raise ValueError("trusted_networks must be a list")

    normalized: list[str] = []
    for value in values:
        candidate = normalize_network(value)  # already warns on an unusually broad entry
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _warn_if_unusually_broad(network_str: str) -> None:
    """Log a warning for a trusted network broader than a plausible home/office LAN.

    Not a rejection - an admin may have a genuine reason - but a dropped digit (/24
    silently becoming /2) should show up somewhere an admin reviewing the log would
    notice, rather than quietly making every login on that IP version bypass 2FA and
    the local-account restriction.
    """
    try:
        network = ipaddress.ip_network(network_str, strict=False)
    except ValueError:
        return
    threshold = _UNUSUALLY_BROAD_PREFIX.get(network.version)
    if threshold is not None and network.prefixlen < threshold:
        logger.warning(
            f"Trusted network {network_str} covers an unusually large address range "
            f"(/{network.prefixlen}) - double-check this wasn't a typo"
        )


def client_ip_is_trusted(client_ip, networks) -> bool:
    """Return True when *client_ip* falls inside any network of *networks*.

    An unparseable or missing client IP is never trusted. Individual unparseable
    entries in *networks* are skipped rather than raising: the list is validated on
    save, so a bad entry here means a hand-edited file and must not break login.
    """
    if not client_ip:
        return False

    try:
        address = ipaddress.ip_address(str(client_ip).strip())
    except ValueError:
        logger.warning(f"Could not parse client IP for trusted-network check: {client_ip!r}")
        return False

    # An IPv4-mapped IPv6 address (e.g. "::ffff:192.168.1.50", which some dual-stack
    # socket layers surface for what is really an IPv4 connection) parses as an
    # IPv6Address and would otherwise fail the version check below against every
    # IPv4 trusted network. Compare it as the IPv4 address it represents instead.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped

    for entry in networks or ():
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            logger.warning(f"Skipping unparseable trusted network entry: {entry!r}")
            continue
        if address.version == network.version and address in network:
            return True

    return False


def get_effective_trusted_networks(settings: dict | None = None) -> list[str]:
    """Configured trusted networks unioned with the always-trusted loopback ranges."""
    if settings is None:
        settings = get_security_settings()
    configured = settings.get('trusted_networks') or []
    effective: list[str] = list(ALWAYS_TRUSTED_NETWORKS)
    for entry in configured:
        if entry not in effective:
            effective.append(entry)
    return effective


def is_client_ip_trusted(client_ip, settings: dict | None = None) -> bool:
    """Convenience wrapper: check *client_ip* against the effective trusted networks."""
    return client_ip_is_trusted(client_ip, get_effective_trusted_networks(settings))


def _coerce_and_enforce_cascade(settings: dict) -> dict:
    """Normalize a raw settings dict's shape and enforce the 2FA/network invariant.

    A hand-edited file (or any other future writer that bypasses the API's own
    validation) must never make the whole instance unusable or leave an inconsistent
    pair on disk: coerce the shape defensively here rather than raising, and enforce
    the same "2FA requires a network" cascade that update_security_settings_api()
    enforces on the write path, so it holds no matter who wrote the file.
    """
    if not isinstance(settings.get('trusted_networks'), list):
        logger.warning("security_settings.json: trusted_networks is not a list, ignoring it")
        settings['trusted_networks'] = []
    else:
        settings['trusted_networks'] = [str(entry) for entry in settings['trusted_networks'] if isinstance(entry, str)]
    settings['two_factor_enabled'] = bool(settings.get('two_factor_enabled'))

    # Documented cascade: 2FA cannot stay on without a configured trusted network.
    if settings['two_factor_enabled'] and not settings['trusted_networks']:
        logger.warning("Refusing two_factor_enabled=true with an empty trusted_networks list, forcing it off")
        settings['two_factor_enabled'] = False

    return settings


def load_security_settings() -> dict:
    """Load settings from disk and merge with defaults. Updates the module cache."""
    global _cache, _cache_mtime
    settings = load_json_settings(_SECURITY_SETTINGS_FILE, _DEFAULTS, 'Security settings')
    settings = _coerce_and_enforce_cascade(settings)
    _cache = settings
    _cache_mtime = get_file_mtime(_SECURITY_SETTINGS_FILE)
    return settings


def save_security_settings(settings: dict) -> None:
    """Persist settings to disk and update the module cache.

    Note: this is a defensive backstop, not the primary UX - update_security_settings_api()
    already rejects an attempt to newly enable 2FA with no trusted network outright (a
    clearer error for the admin than a silent no-op). This only guarantees that no
    caller, now or in the future, can ever persist the inconsistent pair to disk.
    """
    global _cache, _cache_mtime
    merged = dict(_DEFAULTS)
    for key in _DEFAULTS:
        if key in settings:
            merged[key] = settings[key]
    merged = _coerce_and_enforce_cascade(merged)
    merged = save_json_settings(_SECURITY_SETTINGS_FILE, _DEFAULTS, merged, 'Security settings')
    _cache = merged
    _cache_mtime = get_file_mtime(_SECURITY_SETTINGS_FILE)


def get_security_settings() -> dict:
    """Return cached settings, reloading when cold or when the file changed on disk.

    The mtime check keeps a long-lived worker process (`gunicorn -w N`) from serving a
    stale cache forever once warm - the same multi-worker sync UserManager already does
    for users.json via `_reload_users_if_changed()`.
    """
    if _cache is None or get_file_mtime(_SECURITY_SETTINGS_FILE) != _cache_mtime:
        return load_security_settings()
    return _cache


def reload_security_settings() -> dict:
    """Force a reload from disk (call after external file changes)."""
    global _cache
    _cache = None
    return load_security_settings()
