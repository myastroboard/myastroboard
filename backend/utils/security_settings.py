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
import json
import os

from utils.logging_config import get_logger

logger = get_logger(__name__)

_DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
_SECURITY_SETTINGS_FILE = os.path.join(_DATA_DIR, 'security_settings.json')

# Loopback is always trusted and is never written to the file, so clearing the
# configured list can never lock an admin out of local access.
ALWAYS_TRUSTED_NETWORKS = ('127.0.0.0/8', '::1/128')

_DEFAULTS: dict = {
    "trusted_networks": [],
    "two_factor_enabled": False,
}

_cache: dict | None = None


def normalize_network(value) -> str:
    """Return the canonical CIDR form of a network or bare IP.

    ``ipaddress.ip_network(..., strict=False)`` accepts both IPv4 and IPv6 and both
    ``192.168.1.0/24`` and a bare ``192.168.1.5``. Storing the normalized string keeps
    ``192.168.1.5/24`` and ``192.168.1.0/24`` from landing in the list as two entries.

    Raises ValueError when the value cannot be parsed as a network.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid trusted network: {value!r}")
    return str(ipaddress.ip_network(value.strip(), strict=False))


def normalize_networks(values) -> list[str]:
    """Normalize a list of networks, dropping duplicates and preserving order."""
    if not isinstance(values, (list, tuple)):
        raise ValueError("trusted_networks must be a list")

    normalized: list[str] = []
    for value in values:
        candidate = normalize_network(value)
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


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


def load_security_settings() -> dict:
    """Load settings from disk and merge with defaults. Updates the module cache."""
    global _cache
    settings = dict(_DEFAULTS)
    if os.path.exists(_SECURITY_SETTINGS_FILE):
        try:
            with open(_SECURITY_SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            for key in _DEFAULTS:
                if key in saved:
                    settings[key] = saved[key]
            logger.debug("Security settings loaded from disk")
        except Exception as e:
            logger.warning(f"Could not read security_settings.json, using defaults: {e}")

    # A hand-edited file must never make the whole instance unusable: coerce the
    # shape here rather than raising, and let the save endpoint do strict validation.
    if not isinstance(settings['trusted_networks'], list):
        logger.warning("security_settings.json: trusted_networks is not a list, ignoring it")
        settings['trusted_networks'] = []
    else:
        settings['trusted_networks'] = [str(entry) for entry in settings['trusted_networks'] if isinstance(entry, str)]
    settings['two_factor_enabled'] = bool(settings['two_factor_enabled'])

    # Documented cascade: 2FA cannot stay on without a configured trusted network.
    if settings['two_factor_enabled'] and not settings['trusted_networks']:
        logger.warning("security_settings.json has two_factor_enabled without any trusted network, treating it as off")
        settings['two_factor_enabled'] = False

    _cache = settings
    return settings


def save_security_settings(settings: dict) -> None:
    """Persist settings to disk and update the module cache."""
    global _cache
    merged = dict(_DEFAULTS)
    for key in _DEFAULTS:
        if key in settings:
            merged[key] = settings[key]
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_SECURITY_SETTINGS_FILE, 'w') as f:
        json.dump(merged, f, indent=2)
    _cache = merged
    logger.info(
        f"Security settings saved (trusted_networks={len(merged['trusted_networks'])}, "
        f"two_factor_enabled={merged['two_factor_enabled']})"
    )


def get_security_settings() -> dict:
    """Return cached settings, loading from disk if the cache is cold."""
    if _cache is None:
        return load_security_settings()
    return _cache


def reload_security_settings() -> dict:
    """Force a reload from disk (call after external file changes)."""
    global _cache
    _cache = None
    return load_security_settings()
