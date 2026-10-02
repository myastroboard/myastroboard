"""One-shot import of the pre-1.7 JSON files: archive, verify, then delete - or touch nothing."""

import json
import os
import zipfile

import pytest
from sqlalchemy import delete, select

from db import bootstrap, engine, legacy_import, schema, users_store
from db.legacy_import import DocumentRecord, LegacySource, UnreadableDocument, read_json_file


def _users_json():
    return {
        'id-admin': {
            'user_id': 'id-admin',
            'username': 'admin',
            'password_hash': 'pbkdf2:sha256:x',
            'role': 'admin',
            'created_at': '2026-01-01T00:00:00',
            'preferences': {'language': 'fr'},
        },
        'id-bob': {
            'user_id': 'id-bob',
            'username': 'bob',
            'password_hash': 'pbkdf2:sha256:y',
            'role': 'user',
            'created_at': '2026-02-01T00:00:00',
        },
    }


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        if isinstance(data, str):
            handle.write(data)
        else:
            json.dump(data, handle)


@pytest.fixture
def empty_db():
    """The per-test database with no account in it, as on a first 1.7 start."""
    with engine.transaction() as conn:
        conn.execute(delete(schema.users))
    return None


@pytest.fixture
def notes_source(monkeypatch):
    """An extra per-user document source (notes/<uid>_notes.json) to exercise orphans and quarantine."""

    def discover(root):
        directory = os.path.join(root, 'notes')
        if not os.path.isdir(directory):
            return []
        return [
            os.path.join(directory, name)
            for name in sorted(os.listdir(directory))
            if name.endswith('_notes.json') or name.endswith('_notes.json.backup')
        ]

    def convert(path):
        data = read_json_file(path)
        if not isinstance(data, dict):
            raise UnreadableDocument('not an object')
        user_id = os.path.basename(path).split('_notes.json')[0]
        return [DocumentRecord(user_id=user_id, kind='notes', data=data)]

    from db import legacy_sources

    sources = list(legacy_sources.SOURCES) + [LegacySource('notes', discover, convert)]
    monkeypatch.setattr(legacy_sources, 'SOURCES', sources)
    return None


def _statuses():
    with engine.read() as conn:
        return {row.path: row.status for row in conn.execute(select(schema.legacy_import))}


def test_nothing_to_do_without_legacy_files(tmp_path, empty_db):
    """A data directory with no legacy file returns None and writes nothing."""
    assert legacy_import.run_if_needed(str(tmp_path)) is None
    assert not os.path.exists(tmp_path / 'backups')


def test_users_imported_archived_and_deleted(tmp_path, empty_db):
    """users.json lands in the database, is archived, verified, then removed."""
    _write(tmp_path / 'users.json', _users_json())

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and report.succeeded, report and report.failure
    assert report.imported == ['users.json'] and report.deleted == ['users.json']
    assert not (tmp_path / 'users.json').exists()
    assert users_store.get_all_users() == _users_json()
    assert _statuses() == {'users.json': 'deleted'}
    with zipfile.ZipFile(report.archive_path) as archive:
        assert json.loads(archive.read('users.json')) == _users_json()
    assert any(name.startswith('import-report-') for name in os.listdir(tmp_path / 'backups'))
    # Second start: nothing left to do
    assert legacy_import.run_if_needed(str(tmp_path)) is None


def test_invalid_users_file_fails_and_touches_nothing(tmp_path, empty_db):
    """A corrupt critical file aborts the whole import and leaves every file in place."""
    _write(tmp_path / 'users.json', '{not json')

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and not report.succeeded
    assert 'users.json' in (report.failure or '')
    assert (tmp_path / 'users.json').exists()
    assert users_store.get_all_users() == {}


def test_duplicate_usernames_fail(tmp_path, empty_db):
    """Two accounts with one username cannot be imported (the table enforces uniqueness)."""
    users = _users_json()
    users['id-bob']['username'] = 'admin'
    _write(tmp_path / 'users.json', users)
    report = legacy_import.run_if_needed(str(tmp_path))
    assert report is not None and not report.succeeded
    assert (tmp_path / 'users.json').exists()


def test_crashed_save_backup_is_imported(tmp_path, empty_db):
    """A users.json.backup left alone by a 1.6 save that crashed mid-way is used and cleaned up."""
    _write(tmp_path / 'users.json.backup', _users_json())

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and report.succeeded
    assert set(users_store.get_all_users()) == {'id-admin', 'id-bob'}
    assert not (tmp_path / 'users.json.backup').exists()


def test_sidecars_archived_and_removed(tmp_path, empty_db):
    """.tmp leftovers are archived with their file and deleted after the import."""
    _write(tmp_path / 'users.json', _users_json())
    _write(tmp_path / 'users.json.tmp', 'partial')

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and report.succeeded
    assert not (tmp_path / 'users.json.tmp').exists()
    with zipfile.ZipFile(report.archive_path) as archive:
        assert 'users.json.tmp' in archive.namelist()


def test_orphans_and_unreadable_documents_are_quarantined(tmp_path, empty_db, notes_source):
    """Orphan or unreadable per-user files are moved aside; the rest is imported."""
    _write(tmp_path / 'users.json', _users_json())
    _write(tmp_path / 'notes' / 'id-bob_notes.json', {'text': 'hello'})
    _write(tmp_path / 'notes' / 'id-ghost_notes.json', {'text': 'orphan'})
    _write(tmp_path / 'notes' / 'id-admin_notes.json', '[broken')

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and report.succeeded, report and report.failure
    assert report.orphaned == ['notes/id-ghost_notes.json']
    assert report.unreadable == ['notes/id-admin_notes.json']
    assert (tmp_path / 'backups' / 'orphans' / 'notes' / 'id-ghost_notes.json').exists()
    assert (tmp_path / 'backups' / 'unreadable' / 'notes' / 'id-admin_notes.json').exists()
    assert not (tmp_path / 'notes' / 'id-bob_notes.json').exists()
    from db import documents

    assert documents.get_document('id-bob', 'notes') == {'text': 'hello'}


def test_verification_mismatch_rolls_back(tmp_path, empty_db, monkeypatch):
    """When a record does not read back identical, nothing is committed nor deleted."""
    _write(tmp_path / 'users.json', _users_json())
    monkeypatch.setattr(legacy_import, '_read_back', lambda record: {'different': True})

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and not report.succeeded
    assert 'differs' in (report.failure or '')
    assert (tmp_path / 'users.json').exists()
    assert users_store.get_all_users() == {}
    assert _statuses() == {}


def test_failed_deletion_is_finished_on_next_start(tmp_path, empty_db, monkeypatch):
    """Data committed but a file not deleted: the next start verifies and deletes it."""
    _write(tmp_path / 'users.json', _users_json())
    real_remove = os.remove

    def failing_remove(path):
        if str(path).endswith('users.json'):
            raise PermissionError('locked')
        real_remove(path)

    monkeypatch.setattr(legacy_import.os, 'remove', failing_remove)
    report = legacy_import.run_if_needed(str(tmp_path))
    assert report is not None and report.succeeded and report.delete_errors
    assert _statuses() == {'users.json': 'imported'}

    monkeypatch.setattr(legacy_import.os, 'remove', real_remove)
    report = legacy_import.run_if_needed(str(tmp_path))
    assert report is not None and report.succeeded
    assert not (tmp_path / 'users.json').exists()
    assert _statuses() == {'users.json': 'deleted'}


def test_file_changed_after_import_fails(tmp_path, empty_db):
    """A legacy file that differs from what was already imported is not silently re-imported."""
    _write(tmp_path / 'users.json', _users_json())
    with engine.transaction() as conn:
        legacy_import._record_status(conn, 'users.json', 'not-the-same-hash', 'imported')

    report = legacy_import.run_if_needed(str(tmp_path))

    assert report is not None and not report.succeeded
    assert 'changed after it was imported' in (report.failure or '')
    assert (tmp_path / 'users.json').exists()


def test_archive_failure_stops_before_import(tmp_path, empty_db, monkeypatch):
    """No verified archive, no import."""
    _write(tmp_path / 'users.json', _users_json())

    def broken_archive(root, files):
        raise legacy_import.LegacyImportError('disk full')

    monkeypatch.setattr(legacy_import, '_write_archive', broken_archive)
    report = legacy_import.run_if_needed(str(tmp_path))
    assert report is not None and not report.succeeded
    assert users_store.get_all_users() == {}
    assert (tmp_path / 'users.json').exists()


class TestBootstrap:
    def test_failed_import_enters_maintenance(self, tmp_path, empty_db, monkeypatch):
        """A failed import keeps the process in maintenance mode."""
        monkeypatch.setenv('DATA_DIR', str(tmp_path))
        _write(tmp_path / 'users.json', '{not json')
        bootstrap.reset_for_tests()
        try:
            assert bootstrap.ensure_database_ready() is False
            assert bootstrap.is_maintenance()
            assert 'users.json' in (bootstrap.maintenance_reason() or '')
        finally:
            bootstrap.reset_for_tests()
            bootstrap._ready = True

    def test_successful_import_serves_normally(self, tmp_path, empty_db, monkeypatch):
        """A clean import leaves the process ready and not in maintenance."""
        monkeypatch.setenv('DATA_DIR', str(tmp_path))
        _write(tmp_path / 'users.json', _users_json())
        bootstrap.reset_for_tests()
        try:
            assert bootstrap.ensure_database_ready() is True
            assert not bootstrap.is_maintenance()
            assert set(users_store.get_all_users()) == {'id-admin', 'id-bob'}
        finally:
            bootstrap.reset_for_tests()
            bootstrap._ready = True


class TestMigrationBackups:
    """What the import leaves in data/backups/, as shown and deleted from the admin page."""

    def _import(self, tmp_path, notes_source):
        _write(tmp_path / 'users.json', _users_json())
        _write(tmp_path / 'notes' / 'id-ghost_notes.json', {'text': 'orphan'})
        report = legacy_import.run_if_needed(str(tmp_path))
        assert report is not None and report.succeeded
        return report

    def test_summary_lists_archive_report_and_files_set_aside(self, tmp_path, empty_db, notes_source):
        self._import(tmp_path, notes_source)

        summary = legacy_import.migration_backups_summary(str(tmp_path))

        assert summary['exists'] is True
        assert len(summary['archives']) == 1 and summary['archives'][0]['name'].startswith('pre-1.7-')
        assert summary['archives'][0]['size'] > 0
        assert len(summary['reports']) == 1
        assert (summary['orphans'], summary['unreadable']) == (1, 0)
        assert summary['total_size'] >= summary['archives'][0]['size']
        assert legacy_import.latest_report_path(str(tmp_path)).endswith('.txt')

    def test_nothing_to_show_without_backups(self, tmp_path):
        summary = legacy_import.migration_backups_summary(str(tmp_path))
        assert summary['exists'] is False and summary['archives'] == []
        assert legacy_import.latest_report_path(str(tmp_path)) is None

    def test_delete_removes_only_the_import_entries(self, tmp_path, empty_db, notes_source):
        self._import(tmp_path, notes_source)
        operator_file = tmp_path / 'backups' / 'my-own-copy.zip'
        operator_file.write_bytes(b'kept')

        removed = legacy_import.delete_migration_backups(str(tmp_path))

        assert removed == 3  # archive, report, the orphan
        assert sorted(os.listdir(tmp_path / 'backups')) == ['my-own-copy.zip']
        assert legacy_import.migration_backups_summary(str(tmp_path))['exists'] is False

    def test_delete_removes_the_folder_once_empty(self, tmp_path, empty_db, notes_source):
        self._import(tmp_path, notes_source)
        legacy_import.delete_migration_backups(str(tmp_path))
        assert not (tmp_path / 'backups').exists()
