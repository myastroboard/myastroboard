"""
Connector credentials store - the SECRET_FIELDS of every BaseConnector, kept out of config.json.

Credentials used to live in ``config.json -> connectors.<name>``. That file is shipped
verbatim by the backup ZIP (``/api/backup/download``) and by ``/api/config/export``, so a
broker password or an API token would travel with every backup. They now live in a sidecar,
``DATA_DIR/connectors_secrets.json``::

    {"mqtt": {"password": "..."}, "myastroshine": {"token": "...", "signing_secret": "..."}}

which is deliberately absent from the backup allow-lists, like ``secret_key.txt`` and
``vapid.json``. A backup restored on a fresh host therefore needs the connector credentials
re-entered once - the same rule those two files already follow.

``merge_secrets`` is what a connector is constructed with: the config block overlaid with the
sidecar values. A value still sitting in ``config.json`` (an install upgraded but not yet
migrated) keeps working through that fallback; ``migrate_legacy_secrets`` moves it over and
strips it from the config, once, at startup and on every save.
"""

import json
import os
import threading
from typing import Any, Dict, Iterable, Optional

from utils.file_lock import interprocess_lock
from utils.constants import DATA_DIR
from utils.logging_config import get_logger

logger = get_logger(__name__)

_SECRETS_FILE = os.path.join(DATA_DIR, 'connectors_secrets.json')
_lock = threading.Lock()


def _secrets_path() -> str:
    """The sidecar path, resolved at call time so tests can re-point the module attribute."""
    return _SECRETS_FILE


def _read_all() -> Dict[str, Dict[str, str]]:
    path = _secrets_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not read connector secrets file {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: Dict[str, Dict[str, str]] = {}
    for name, values in data.items():
        if isinstance(values, dict):
            cleaned[str(name)] = {str(k): str(v) for k, v in values.items() if isinstance(v, str) and v}
    return cleaned


def _write_all(data: Dict[str, Dict[str, str]]) -> bool:
    """Atomic write (tmp + replace) with owner-only permissions where the OS honours them."""
    path = _secrets_path()
    tmp_path = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass  # Windows / exotic filesystems: best effort, the file is still outside backups
        os.replace(tmp_path, path)
        return True
    except OSError as exc:
        logger.error(f"Could not write connector secrets file {path}: {exc}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def load_secrets(name: str) -> Dict[str, str]:
    """The stored credentials of one connector (``{}`` when none)."""
    with _lock:
        return dict(_read_all().get(name, {}))


def save_secrets(name: str, values: Dict[str, Any]) -> bool:
    """Merge *values* into the connector's stored credentials.

    A blank value removes the key; nothing else in the file is touched. The
    read-merge-write runs under a cross-process lock: every gunicorn worker
    migrates legacy secrets at startup, so two workers routinely write at once.
    """
    try:
        with _lock, interprocess_lock(_secrets_path() + '.lock'):
            data = _read_all()
            current = dict(data.get(name, {}))
            for key, value in values.items():
                text = str(value or '').strip()
                if text:
                    current[key] = text
                else:
                    current.pop(key, None)
            if current:
                data[name] = current
            else:
                data.pop(name, None)
            return _write_all(data)
    except OSError as exc:
        logger.error(f"Could not lock connector secrets file {_secrets_path()}: {exc}")
        return False


def merge_secrets(name: str, cfg: Optional[Dict[str, Any]], secret_fields: Iterable[str]) -> Dict[str, Any]:
    """The connector's config block with its credentials overlaid from the sidecar.

    The sidecar wins whenever it holds a value; otherwise a legacy value still present in the
    config block is kept, so an un-migrated install keeps working.
    """
    merged = dict(cfg or {})
    stored = load_secrets(name)
    for field in secret_fields:
        value = stored.get(field)
        if value:
            merged[field] = value
    return merged


def migrate_legacy_secrets(name: str, secret_fields: Iterable[str], config: Dict[str, Any]) -> bool:
    """Move credentials still stored in ``config["connectors"][name]`` into the sidecar.

    Returns True when *config* was modified (the caller is then expected to persist it).
    Idempotent: a config block without secret values is left untouched. A value already in the
    sidecar wins over the legacy one, which is simply dropped.
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
        logger.info(f"Moved {len(legacy)} credential(s) of connector '{name}' out of config.json")

    for field in present:
        block.pop(field, None)
    return True


def migrate_all_legacy_secrets(config: Dict[str, Any], registry: Optional[Dict[str, Any]] = None) -> bool:
    """Run ``migrate_legacy_secrets`` for every registered connector; True when *config* changed.

    Called once at application startup (``app.py``) so an upgraded install stops carrying
    credentials in config.json before its next backup, without waiting for a save.
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
