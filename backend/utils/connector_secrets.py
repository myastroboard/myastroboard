"""
Connector credentials store - the SECRET_FIELDS of every BaseConnector, kept out of the config.

Credentials used to live in ``config -> connectors.<name>``. The config is shipped verbatim
by the backup ZIP (``/api/backup/download``) and by ``/api/config/export``, so a broker
password or an API token would travel with every backup. They now live apart, in the
``connectors_secrets`` setting::

    {"mqtt": {"password": "..."}, "myastroshine": {"token": "...", "signing_secret": "..."}}

which is deliberately absent from the backup and export, like the secret key and the VAPID
keys. A backup restored on a fresh host therefore needs the connector credentials re-entered
once - the same rule those two already follow.

``merge_secrets`` is what a connector is constructed with: the config block overlaid with the
stored values. A value still sitting in the config (an install upgraded but not yet migrated)
keeps working through that fallback; ``migrate_legacy_secrets`` moves it over and strips it
from the config, once, at startup and on every save.
"""

from collections.abc import Iterable
from typing import Any

from db import settings_store
from utils.logging_config import get_logger

logger = get_logger(__name__)

SECRETS_KEY = 'connectors_secrets'


def _clean(data: Any) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for name, values in data.items():
        if isinstance(values, dict):
            cleaned[str(name)] = {str(k): str(v) for k, v in values.items() if isinstance(v, str) and v}
    return cleaned


def _read_all() -> dict[str, dict[str, str]]:
    try:
        return _clean(settings_store.get_setting(SECRETS_KEY))
    except Exception as exc:
        logger.warning(f"Could not read connector secrets: {exc}")
        return {}


def secrets_revision() -> int:
    """Revision of the stored credentials (change detector for long-running publishers)."""
    return settings_store.setting_revision(SECRETS_KEY)


def load_secrets(name: str) -> dict[str, str]:
    """The stored credentials of one connector (``{}`` when none)."""
    return dict(_read_all().get(name, {}))


def save_secrets(name: str, values: dict[str, Any]) -> bool:
    """Merge *values* into the connector's stored credentials.

    A blank value removes the key; nothing else is touched. The read-merge-write is one
    transaction: every gunicorn worker migrates legacy secrets at startup, so two workers
    routinely write at once.
    """

    def _merge(current):
        data = _clean(current)
        merged = dict(data.get(name, {}))
        for key, value in values.items():
            text = str(value or '').strip()
            if text:
                merged[key] = text
            else:
                merged.pop(key, None)
        if merged:
            data[name] = merged
        else:
            data.pop(name, None)
        return data, True

    try:
        return settings_store.modify_setting(SECRETS_KEY, _merge)
    except Exception as exc:
        logger.error(f"Could not store connector secrets: {exc}")
        return False


def merge_secrets(name: str, cfg: dict[str, Any] | None, secret_fields: Iterable[str]) -> dict[str, Any]:
    """The connector's config block with its credentials overlaid from the secrets store.

    The stored value wins whenever it holds a value; otherwise a legacy value still present in the
    config block is kept, so an un-migrated install keeps working.
    """
    merged = dict(cfg or {})
    stored = load_secrets(name)
    for field in secret_fields:
        value = stored.get(field)
        if value:
            merged[field] = value
    return merged


def migrate_legacy_secrets(name: str, secret_fields: Iterable[str], config: dict[str, Any]) -> bool:
    """Move credentials still stored in ``config["connectors"][name]`` into the secrets store.

    Returns True when *config* was modified (the caller is then expected to persist it).
    Idempotent: a config block without secret values is left untouched. A value already in the
    secrets store wins over the legacy one, which is simply dropped.
    """
    connectors_cfg = config.get('connectors')
    if not isinstance(connectors_cfg, dict):
        return False
    block = connectors_cfg.get(name)
    if not isinstance(block, dict):
        return False

    fields = list(secret_fields)
    legacy = {field: str(block.get(field) or '').strip() for field in fields if block.get(field)}
    present = [field for field in fields if field in block]
    if not present:
        return False

    if legacy:
        stored = load_secrets(name)
        to_store = {field: value for field, value in legacy.items() if value and not stored.get(field)}
        if to_store and not save_secrets(name, to_store):
            # Never strip a credential from the config when it could not be stored elsewhere.
            return False
        logger.info(f"Moved {len(legacy)} credential(s) of connector '{name}' out of the config")

    for field in present:
        block.pop(field, None)
    return True


def migrate_all_legacy_secrets(config: dict[str, Any], registry: dict[str, Any] | None = None) -> bool:
    """Run ``migrate_legacy_secrets`` for every registered connector; True when *config* changed.

    Called once at application startup (``app.py``) so an upgraded install stops carrying
    credentials in the config before its next backup, without waiting for a save.
    """
    if registry is None:
        # Lazy: utils/ must not depend on the connectors package at import time.
        from connectors import REGISTRY as registry  # noqa: N811 - constant re-exported under a local name

    changed = False
    for name, cls in registry.items():
        fields = tuple(getattr(cls, 'SECRET_FIELDS', ()) or ())
        if fields and migrate_legacy_secrets(name, fields, config):
            changed = True
    return changed
