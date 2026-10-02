"""db/manage.py - the operator command line (recovery without editing data files)."""

import pytest

from db import manage
from utils import auth


@pytest.fixture
def account():
    return auth.user_manager.create_user('stargazer', 'old-password', auth.ROLE_USER)


def test_status(capsys):
    assert manage.main(['status']) == 0
    out = capsys.readouterr().out
    assert 'Schema revision' in out and 'Accounts:' in out


def test_list_users(capsys, account):
    assert manage.main(['list-users']) == 0
    assert 'stargazer' in capsys.readouterr().out


def test_reset_password_generates_one(capsys, account):
    assert manage.main(['reset-password', 'stargazer']) == 0
    new_password = capsys.readouterr().out.strip().rsplit(' ', 1)[-1]
    auth.user_manager.invalidate_cache()
    assert auth.user_manager.get_user_by_username('stargazer').check_password(new_password)


def test_reset_password_with_explicit_value(capsys, account):
    assert manage.main(['reset-password', 'stargazer', '--password', 'brand-new-pw']) == 0
    assert 'brand-new-pw' not in capsys.readouterr().out
    auth.user_manager.invalidate_cache()
    assert auth.user_manager.get_user_by_username('stargazer').check_password('brand-new-pw')


def test_reset_password_rejects_short_value(account):
    with pytest.raises(SystemExit):
        manage.main(['reset-password', 'stargazer', '--password', 'abc'])


def test_disable_2fa(capsys, account):
    auth.user_manager.start_totp_setup(account.user_id)
    assert manage.main(['disable-2fa', 'stargazer']) == 0
    auth.user_manager.invalidate_cache()
    user = auth.user_manager.get_user_by_username('stargazer')
    assert user.totp_secret is None and not user.totp_enabled


def test_unknown_account(account):
    with pytest.raises(SystemExit, match='No account'):
        manage.main(['disable-2fa', 'nobody'])


def test_refuses_to_run_in_maintenance(monkeypatch):
    from db import bootstrap

    monkeypatch.setattr(bootstrap, 'ensure_database_ready', lambda: False)
    monkeypatch.setattr(bootstrap, 'maintenance_reason', lambda: 'users.json is corrupt')
    with pytest.raises(SystemExit, match='maintenance'):
        manage.main(['status'])


def test_status_reports_the_legacy_import(capsys):
    from db import engine, legacy_import

    with engine.transaction() as conn:
        legacy_import._record_status(conn, 'users.json', 'abc', 'deleted')
    assert manage.main(['status']) == 0
    assert 'Legacy JSON import: 1 deleted' in capsys.readouterr().out
