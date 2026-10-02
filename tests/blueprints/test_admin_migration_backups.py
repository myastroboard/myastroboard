"""Admin routes for the 1.7 upgrade archive in data/backups/."""

import os
import zipfile


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    backups = tmp_path / 'backups'
    (backups / 'orphans' / 'observation_sessions').mkdir(parents=True)
    with zipfile.ZipFile(backups / 'pre-1.7-20261002T000000Z.zip', 'w') as archive:
        archive.writestr('users.json', '{}')
    (backups / 'import-report-20261002T000000Z.txt').write_text('Result: SUCCESS\n', encoding='utf-8')
    (backups / 'orphans' / 'observation_sessions' / 'x_sessions.json').write_text('{}', encoding='utf-8')
    return backups


def test_summary(client_admin, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    body = client_admin.get('/api/admin/migration-backups').get_json()
    assert body['exists'] is True
    assert body['archives'][0]['name'] == 'pre-1.7-20261002T000000Z.zip'
    assert body['orphans'] == 1


def test_summary_when_nothing_left(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    assert client_admin.get('/api/admin/migration-backups').get_json()['exists'] is False


def test_report_download(client_admin, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    resp = client_admin.get('/api/admin/migration-backups/report')
    assert resp.status_code == 200
    assert b'Result: SUCCESS' in resp.data


def test_report_missing_is_404(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    assert client_admin.get('/api/admin/migration-backups/report').status_code == 404


def test_delete(client_admin, tmp_path, monkeypatch):
    backups = _seed(tmp_path, monkeypatch)
    resp = client_admin.delete('/api/admin/migration-backups')
    assert resp.status_code == 200
    assert resp.get_json()['removed'] == 3
    assert not os.path.exists(backups)


def test_errors_are_500(client_admin, monkeypatch):
    from db import legacy_import

    def _boom(*_args, **_kwargs):
        raise OSError('disk')

    monkeypatch.setattr(legacy_import, 'migration_backups_summary', _boom)
    monkeypatch.setattr(legacy_import, 'latest_report_path', _boom)
    monkeypatch.setattr(legacy_import, 'delete_migration_backups', _boom)
    assert client_admin.get('/api/admin/migration-backups').status_code == 500
    assert client_admin.get('/api/admin/migration-backups/report').status_code == 500
    assert client_admin.delete('/api/admin/migration-backups').status_code == 500


def test_non_admin_is_refused(client_user, tmp_path, monkeypatch):
    backups = _seed(tmp_path, monkeypatch)
    assert client_user.get('/api/admin/migration-backups').status_code in (401, 403)
    assert client_user.delete('/api/admin/migration-backups').status_code in (401, 403)
    assert backups.exists()
