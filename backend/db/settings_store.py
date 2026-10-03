"""Install-wide settings (``settings`` table): one JSON value per key.

Replaces the singleton JSON files (config.json, app_settings.json, ...). Every write
bumps the ``setting:<key>`` store revision in the same transaction.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from db import schema
from db.engine import bump_revision, get_revision, read, transaction

_table = schema.settings


def _store(key: str) -> str:
    return f'setting:{key}'


def get_setting(key: str) -> Any | None:
    """The stored value, or ``None`` when the key was never written."""
    with read() as conn:
        return conn.execute(select(_table.c.data).where(_table.c.key == key)).scalar()


def put_setting(key: str, value: Any) -> None:
    """Insert or replace the value of ``key``."""
    stmt = insert(_table).values(key=key, data=value, updated_at=datetime.now(UTC).isoformat())
    stmt = stmt.on_conflict_do_update(
        index_elements=[_table.c.key], set_={'data': stmt.excluded.data, 'updated_at': stmt.excluded.updated_at}
    )
    with transaction() as conn:
        conn.execute(stmt)
        bump_revision(conn, _store(key))


def modify_setting[T](key: str, mutate: Callable[[Any | None], tuple[Any | None, T]]) -> T:
    """Atomic read-modify-write; ``mutate(current) -> (new_value or None to keep, result)``."""
    with transaction():
        new_value, result = mutate(get_setting(key))
        if new_value is not None:
            put_setting(key, new_value)
        return result


def setting_revision(key: str) -> int:
    """Revision of ``key``, for per-process caches."""
    return get_revision(_store(key))
