"""Database diagnostics for the admin Metrics page."""

import os
from typing import Any

from db import migrate
from db.engine import get_engine, read
from utils.logging_config import get_logger

logger = get_logger(__name__)

# integrity_check stops after this many problems; enough to tell "damaged" from "sound"
_INTEGRITY_MAX_ERRORS = 20


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def database_status() -> dict[str, Any]:
    """Schema version, size and journal mode - cheap enough for the Metrics auto-refresh."""
    path = str(get_engine().url.database or '')
    current = migrate.current_revision()
    head = migrate.head_revision()
    with read() as conn:
        journal_mode = str(conn.exec_driver_sql('PRAGMA journal_mode').scalar() or '').lower()
    return {
        'schema_revision': current,
        'schema_head': head,
        'schema_up_to_date': current == head,
        'size': _file_size(path),
        'wal_size': _file_size(path + '-wal'),
        'journal_mode': journal_mode,
        # WAL needs shared memory: when SQLite refused it, data/ is most likely on a network share
        'wal_active': journal_mode == 'wal',
    }


def integrity_check() -> dict[str, Any]:
    """Run SQLite's ``integrity_check``: ``{'ok': bool, 'problems': [...]}``."""
    with read() as conn:
        rows = [str(row[0]) for row in conn.exec_driver_sql(f'PRAGMA integrity_check({_INTEGRITY_MAX_ERRORS})')]
        foreign_keys = conn.exec_driver_sql('PRAGMA foreign_key_check').all()
    problems = [row for row in rows if row != 'ok']
    problems += [f'foreign key: {row[0]} row {row[1]} -> {row[2]}' for row in foreign_keys[:_INTEGRITY_MAX_ERRORS]]
    if problems:
        logger.error(f"Database integrity check found {len(problems)} problem(s): {problems[:3]}")
    else:
        logger.info("Database integrity check: ok")
    return {'ok': not problems, 'problems': problems}
