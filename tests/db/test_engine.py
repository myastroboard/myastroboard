"""db/engine.py - engine creation, per-connection setup and JSON serialization."""

import os

import pytest

from db import engine


class TestJsonDefault:
    def test_numpy_like_scalar_uses_item(self):
        """A value with item() but no tolist() (a numpy-like scalar) is stored as its Python value."""

        class _Scalar:
            def item(self):
                return 7

        assert engine._json_serializer({'value': _Scalar()}) == '{"value": 7}'

    def test_sets_are_sorted_lists(self):
        assert engine._json_serializer({'tags': {'b', 'a'}}) == '{"tags": ["a", "b"]}'

    def test_other_objects_are_refused(self):
        with pytest.raises(TypeError, match='object is not JSON serializable'):
            engine._json_serializer({'value': object()})


class _FakeCursor:
    def __init__(self, journal_mode):
        self.journal_mode = journal_mode
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        return self

    def fetchone(self):
        return (self.journal_mode,)

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, journal_mode):
        self.isolation_level = 'DEFERRED'
        self._cursor = _FakeCursor(journal_mode)

    def cursor(self):
        return self._cursor


class TestConnectionSetup:
    def test_missing_wal_is_logged_once(self, monkeypatch):
        """A file system that refuses WAL (network share) is reported once per process, not per connection."""
        monkeypatch.setattr(engine, '_wal_warning_logged', False)
        warnings = []
        monkeypatch.setattr(engine.logger, 'warning', warnings.append)
        for _ in range(2):
            connection = _FakeConnection('delete')
            engine._on_connect(connection, None)
            assert connection.isolation_level is None
            assert 'PRAGMA synchronous = NORMAL' in connection._cursor.statements
        assert len(warnings) == 1 and 'journal_mode=delete' in warnings[0]

    def test_foreign_keys_can_be_left_off(self):
        connection = _FakeConnection('wal')
        engine._on_connect(connection, None, enforce_foreign_keys=False)
        assert 'PRAGMA foreign_keys = OFF' in connection._cursor.statements


def test_default_engine_lives_in_the_data_directory(tmp_path, monkeypatch):
    """Without an explicit URL the engine opens DATA_DIR/myastroboard.db, creating the directory."""
    data_dir = tmp_path / 'fresh' / 'data'
    monkeypatch.setenv('DATA_DIR', str(data_dir))
    default = engine.configure_engine(None)
    try:
        assert os.path.normcase(default.url.database) == os.path.normcase(str(data_dir / engine.DATABASE_FILENAME))
        assert data_dir.is_dir()
        assert engine.get_engine() is default
    finally:
        default.dispose()
