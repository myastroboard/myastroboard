"""Bring the database up to date before the application touches any data.

Called once per process at the top of ``app.py``, before the modules that load data at
import time (``utils.auth`` builds the user manager then). Under a cross-process lock,
so with two gunicorn workers the first one upgrades the schema and imports the legacy
JSON files while the second waits, then finds nothing left to do.

When the legacy import fails, the process stays in *maintenance mode*: every request
gets a 503 page (see ``app.py``), the legacy files are left untouched, and the
operator can go back to the previous release without losing anything.
"""

import threading

from db.engine import database_path
from utils.file_lock import interprocess_lock
from utils.logging_config import get_logger

logger = get_logger(__name__)

_state_mutex = threading.Lock()
_ready = False
_maintenance_reason: str | None = None


def ensure_database_ready() -> bool:
    """Upgrade the schema and run the legacy import if needed; False means maintenance mode."""
    global _ready, _maintenance_reason
    with _state_mutex:
        if _ready:
            return _maintenance_reason is None
        from db import legacy_import, migrate

        with interprocess_lock(database_path() + '.migrate.lock'):
            migrate.upgrade_to_head()
            report = legacy_import.run_if_needed()
        if report is not None and not report.succeeded:
            _maintenance_reason = report.failure
            logger.error(f"Legacy data import failed, starting in maintenance mode: {report.failure}")
        _ready = True
        return _maintenance_reason is None


def maintenance_reason() -> str | None:
    """Why the instance is in maintenance mode, or None when it is serving normally."""
    return _maintenance_reason


def is_maintenance() -> bool:
    """True when the legacy import failed and the app must not serve data."""
    return _maintenance_reason is not None


def reset_for_tests() -> None:
    """Forget the bootstrap state (tests run several bootstraps in one process)."""
    global _ready, _maintenance_reason
    with _state_mutex:
        _ready = False
        _maintenance_reason = None
