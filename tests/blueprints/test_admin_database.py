"""Database block of the admin Metrics page."""


def test_metrics_include_the_database_status():
    from utils import metrics_collector

    status = metrics_collector._database_status()
    assert status['schema_up_to_date'] is True
    assert status['journal_mode'] == 'wal'


def test_metrics_survive_a_database_error(monkeypatch):
    from db import health
    from utils import metrics_collector

    def _boom():
        raise OSError('db gone')

    monkeypatch.setattr(health, 'database_status', _boom)
    assert metrics_collector._database_status() is None


def test_integrity_check_route(client_admin):
    body = client_admin.post('/api/admin/database/integrity-check').get_json()
    assert body['ok'] is True


def test_integrity_check_error_is_500(client_admin, monkeypatch):
    from db import health

    def _boom():
        raise OSError('disk')

    monkeypatch.setattr(health, 'integrity_check', _boom)
    assert client_admin.post('/api/admin/database/integrity-check').status_code == 500


def test_integrity_check_is_admin_only(client_user):
    assert client_user.post('/api/admin/database/integrity-check').status_code in (401, 403)
