"""Database diagnostics shown on the Metrics page (db/health.py)."""

from db import documents, engine, health, migrate, users_store


def test_status_reports_schema_size_and_journal():
    status = health.database_status()
    assert status['schema_up_to_date'] is True
    assert status['schema_revision'] == migrate.head_revision()
    assert status['size'] > 0
    assert status['journal_mode'] == 'wal' and status['wal_active'] is True


def test_status_flags_an_outdated_schema(monkeypatch):
    monkeypatch.setattr(migrate, 'current_revision', lambda: None)
    status = health.database_status()
    assert status['schema_up_to_date'] is False


def test_status_flags_a_missing_wal(monkeypatch):
    with engine.transaction() as conn:
        conn.exec_driver_sql('SELECT 1')
    monkeypatch.setattr(health, 'read', _read_returning('delete'))
    status = health.database_status()
    assert status['wal_active'] is False and status['journal_mode'] == 'delete'


def _read_returning(mode):
    from contextlib import contextmanager

    class _Conn:
        def exec_driver_sql(self, _sql):
            class _Result:
                def scalar(self_inner):
                    return mode

            return _Result()

    @contextmanager
    def _read():
        yield _Conn()

    return _read


def test_integrity_check_on_a_sound_database():
    users_store.upsert_users(
        [{'user_id': 'u1', 'username': 'u1', 'password_hash': 'x', 'role': 'user', 'created_at': 'now'}]
    )
    documents.put_document('u1', 'astrodex', {'items': [{'id': 'i', 'name': 'M 31', 'pictures': [{'id': 'p'}]}]})
    assert health.integrity_check() == {'ok': True, 'problems': []}


def test_integrity_check_reports_dangling_rows():
    """A row pointing to a missing parent (written with foreign keys off) is reported."""
    documents.put_document('ghost-user', 'wishlist', {'items': [{'id': 'w', 'name': 'M 42'}]})
    result = health.integrity_check()
    assert result['ok'] is False
    assert any('wishlist_items' in problem for problem in result['problems'])
