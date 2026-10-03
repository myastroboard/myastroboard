"""SQLite engine, connection setup and transaction helpers.

One engine per process (each gunicorn worker builds its own after the fork). SQLite
gives every worker the same view of the data, and a write transaction opened with
``BEGIN IMMEDIATE`` (see :func:`transaction`) serializes read-modify-write cycles
across workers - what ``interprocess_lock`` + ``.tmp``/``os.replace`` did for the JSON
files.
"""

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.engine import Connection, Engine, create_engine

from db import schema
from utils.logging_config import get_logger

logger = get_logger(__name__)

DATABASE_FILENAME = 'myastroboard.db'
# Writers wait this long for another worker's write transaction before failing.
BUSY_TIMEOUT_MS = 10000

_engine: Engine | None = None
_engine_url: str | None = None
_engine_mutex = threading.Lock()
_local = threading.local()
_wal_warning_logged = False


def data_dir() -> str:
    """The data directory, resolved on each call so tests that repoint DATA_DIR are honoured."""
    from utils import constants

    return os.environ.get('DATA_DIR', constants.DATA_DIR)


def database_path() -> str:
    """Absolute path of the SQLite database file."""
    return os.path.join(data_dir(), DATABASE_FILENAME)


def _json_default(value: Any) -> Any:
    """Serialize the non-JSON scalars that reach the stores (numpy numbers and arrays, sets)."""
    if hasattr(value, 'tolist'):
        return value.tolist()
    if hasattr(value, 'item'):
        return value.item()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')


def _json_serializer(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _connect_listener(enforce_foreign_keys: bool):
    def _listener(dbapi_connection, connection_record) -> None:
        _on_connect(dbapi_connection, connection_record, enforce_foreign_keys)

    return _listener


def _on_connect(dbapi_connection, _connection_record, enforce_foreign_keys: bool = True) -> None:
    """Per-connection SQLite setup."""
    # Let SQLAlchemy's "begin" event below emit BEGIN itself (the sqlite3 module's own
    # implicit transactions cannot do BEGIN IMMEDIATE).
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
        cursor.execute(f"PRAGMA foreign_keys = {'ON' if enforce_foreign_keys else 'OFF'}")
        mode = cursor.execute('PRAGMA journal_mode = WAL').fetchone()
        global _wal_warning_logged
        if mode and str(mode[0]).lower() != 'wal' and not _wal_warning_logged:
            # WAL needs shared memory; network file systems (NFS, SMB) refuse it.
            _wal_warning_logged = True
            logger.warning(
                f"SQLite WAL mode unavailable (journal_mode={mode[0]}); is the data directory on a network share?"
            )
        cursor.execute('PRAGMA synchronous = NORMAL')
    finally:
        cursor.close()


def _on_begin(conn: Connection) -> None:
    mode = conn.get_execution_options().get('sqlite_begin', 'DEFERRED')
    conn.exec_driver_sql(f'BEGIN {mode}')


def _build_engine(url: str, enforce_foreign_keys: bool = True) -> Engine:
    # The default queue pool reuses connections (and their PRAGMA setup) across requests.
    # Each gunicorn worker builds its engine after the fork, so no pooled connection is
    # ever shared between processes.
    engine = create_engine(url, pool_size=5, max_overflow=10, json_serializer=_json_serializer)
    event.listen(engine, 'connect', _connect_listener(enforce_foreign_keys))
    event.listen(engine, 'begin', _on_begin)
    return engine


def get_engine() -> Engine:
    """The process-wide engine, created on first use."""
    global _engine, _engine_url
    with _engine_mutex:
        if _engine is None:
            path = database_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _engine_url = f'sqlite:///{path}'
            _engine = _build_engine(_engine_url)
        return _engine


def configure_engine(url: str | None, enforce_foreign_keys: bool = True) -> Engine:
    """Replace the engine (tests point it at a temporary database). ``None`` resets to the default.

    ``enforce_foreign_keys=False`` exists for the test suite only, where most tests store
    documents for made-up user ids; the application always enforces them.
    """
    global _engine, _engine_url
    with _engine_mutex:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_url = None
        if url is not None:
            _engine_url = url
            _engine = _build_engine(url, enforce_foreign_keys)
    if url is None:
        return get_engine()
    assert _engine is not None
    return _engine


def _current_connection() -> Connection | None:
    return getattr(_local, 'connection', None)


@contextmanager
def transaction() -> Iterator[Connection]:
    """A write transaction (``BEGIN IMMEDIATE``); commits on success, rolls back on error.

    Re-entrant within a thread: a nested call joins the outer transaction, so a helper
    that writes can be called both on its own and inside a larger read-modify-write.
    """
    outer = _current_connection()
    if outer is not None:
        yield outer
        return
    engine = get_engine()
    with engine.connect().execution_options(sqlite_begin='IMMEDIATE') as conn:
        _local.connection = conn
        try:
            with conn.begin():
                yield conn
        finally:
            _local.connection = None


@contextmanager
def read() -> Iterator[Connection]:
    """A read-only snapshot (deferred transaction). Joins the thread's open transaction, if any."""
    outer = _current_connection()
    if outer is not None:
        yield outer
        return
    engine = get_engine()
    with engine.connect() as conn:
        with conn.begin():
            yield conn


def bump_revision(conn: Connection, store: str) -> int:
    """Increment ``store``'s revision inside the caller's write transaction and return it."""
    table = schema.store_revisions
    conn.exec_driver_sql(
        'INSERT INTO store_revisions (store, revision) VALUES (?, 1) '
        'ON CONFLICT(store) DO UPDATE SET revision = revision + 1',
        (store,),
    )
    return int(conn.execute(select(table.c.revision).where(table.c.store == store)).scalar_one())


def get_revision(store: str) -> int:
    """Current revision of ``store`` (0 when it was never written)."""
    table = schema.store_revisions
    with read() as conn:
        value = conn.execute(select(table.c.revision).where(table.c.store == store)).scalar()
    return int(value or 0)
