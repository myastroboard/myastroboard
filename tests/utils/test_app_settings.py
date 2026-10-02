"""Tests for app_settings.py: secret key generation and persistent app settings."""

import pytest

from db import settings_store
from tests.db_helpers import delete_setting


@pytest.fixture(autouse=True)
def reset_app_settings_cache():
    """Clear the module-level cache (and its revision marker) before and after each test."""
    from utils import app_settings

    app_settings._cache = None
    app_settings._cache_revision = None
    yield
    app_settings._cache = None
    app_settings._cache_revision = None


def _set_cache(monkeypatch, cache: dict):
    """Stub app_settings._cache directly and neutralize the revision staleness check, so
    get_app_settings() returns exactly this dict regardless of what is really stored -
    several tests below use this to stub a settings value without writing it. Without
    neutralizing the check, get_app_settings() would see the stub's revision not match
    the stored one and immediately reload past it."""
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_settings_revision', lambda _key: 'frozen')
    app_settings._cache = cache
    app_settings._cache_revision = 'frozen'


# ---------------------------------------------------------------------------
# load_or_generate_secret_key
# ---------------------------------------------------------------------------


def test_secret_key_generated_on_first_run():
    from utils import app_settings

    delete_setting('secret_key')

    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64  # token_hex(32) = 64 hex chars
    assert settings_store.get_setting('secret_key') == key


def test_secret_key_persists_across_calls():
    from utils import app_settings

    key1 = app_settings.load_or_generate_secret_key()
    key2 = app_settings.load_or_generate_secret_key()

    assert key1 == key2


def test_secret_key_loads_existing_value():
    from utils import app_settings

    settings_store.put_setting('secret_key', 'aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899')

    key = app_settings.load_or_generate_secret_key()

    assert key == 'aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899'


def test_secret_key_regenerated_when_value_blank():
    """A blank stored key is replaced by a new one."""
    from utils import app_settings

    settings_store.put_setting('secret_key', '   ')

    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64
    assert settings_store.get_setting('secret_key') == key


def test_secret_key_generation_converges_on_the_first_writer(monkeypatch):
    """A worker that lost the race adopts the key the other worker stored, not its own."""
    from utils import app_settings

    delete_setting('secret_key')
    monkeypatch.setattr(app_settings, '_read_secret_key', lambda: None)  # looked before the other worker wrote
    settings_store.put_setting('secret_key', 'f' * 64)

    assert app_settings.load_or_generate_secret_key() == 'f' * 64


def test_secret_key_storage_failure_still_returns_key(monkeypatch):
    """A database failure yields a working (unpersisted) key rather than a crash."""
    from utils import app_settings

    def _boom(*_args, **_kwargs):
        raise OSError('read-only fs')

    monkeypatch.setattr(app_settings.settings_store, 'get_setting', _boom)
    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64


# ---------------------------------------------------------------------------
# load_app_settings / get_app_settings
# ---------------------------------------------------------------------------


def test_app_settings_defaults_when_never_saved():
    from utils import app_settings

    delete_setting('app_settings')

    settings = app_settings.load_app_settings()

    assert settings['vapid_contact_email'] == ''
    assert settings['trust_proxy_headers'] is False
    assert settings['session_cookie_secure'] is False


def test_app_settings_loads_stored_values():
    from utils import app_settings

    settings_store.put_setting(
        'app_settings',
        {
            'vapid_contact_email': 'admin@example.com',
            'trust_proxy_headers': True,
            'session_cookie_secure': True,
        },
    )

    settings = app_settings.load_app_settings()

    assert settings['vapid_contact_email'] == 'admin@example.com'
    assert settings['trust_proxy_headers'] is True
    assert settings['session_cookie_secure'] is True


def test_app_settings_merges_missing_keys():
    """A partial stored value is merged with defaults."""
    from utils import app_settings

    settings_store.put_setting('app_settings', {'vapid_contact_email': 'test@test.com'})

    settings = app_settings.load_app_settings()

    assert settings['vapid_contact_email'] == 'test@test.com'
    assert settings['trust_proxy_headers'] is False  # default
    assert settings['session_cookie_secure'] is False  # default


def test_get_app_settings_uses_cache():
    from utils import app_settings

    app_settings.load_app_settings()
    app_settings._cache = {
        'vapid_contact_email': 'cached@test.com',
        'trust_proxy_headers': True,
        'session_cookie_secure': False,
    }

    settings = app_settings.get_app_settings()

    assert settings['vapid_contact_email'] == 'cached@test.com'


def test_get_app_settings_reloads_when_another_worker_saved():
    """Multi-worker sync: a cache older than the stored revision is stale, not just a cold cache."""
    from utils import app_settings

    app_settings.save_app_settings({'vapid_contact_email': 'first@test.com'})
    # Another worker saves behind this worker's back
    settings_store.put_setting('app_settings', {'vapid_contact_email': 'second@test.com'})

    settings = app_settings.get_app_settings()

    assert settings['vapid_contact_email'] == 'second@test.com'


def test_load_app_settings_wrong_shape_uses_defaults():
    """A stored value that is not an object falls back to the defaults."""
    from utils import app_settings

    settings_store.put_setting('app_settings', ['not', 'an', 'object'])

    settings = app_settings.load_app_settings()

    assert settings == dict(app_settings._DEFAULTS)


# ---------------------------------------------------------------------------
# save_app_settings
# ---------------------------------------------------------------------------


def test_save_app_settings_stores_value():
    from utils import app_settings

    app_settings.save_app_settings(
        {
            'vapid_contact_email': 'save@example.com',
            'trust_proxy_headers': True,
            'session_cookie_secure': False,
        }
    )

    saved = settings_store.get_setting('app_settings')
    assert saved['vapid_contact_email'] == 'save@example.com'
    assert saved['trust_proxy_headers'] is True


def test_save_app_settings_updates_cache():
    from utils import app_settings

    app_settings.save_app_settings({'vapid_contact_email': 'new@test.com'})

    assert app_settings._cache is not None
    assert app_settings._cache['vapid_contact_email'] == 'new@test.com'


# ---------------------------------------------------------------------------
# reload_app_settings
# ---------------------------------------------------------------------------


def test_reload_clears_cache_and_rereads():
    from utils import app_settings

    settings_store.put_setting('app_settings', {'vapid_contact_email': 'v1@test.com'})
    app_settings.load_app_settings()
    assert app_settings._cache['vapid_contact_email'] == 'v1@test.com'

    settings_store.put_setting('app_settings', {'vapid_contact_email': 'v2@test.com'})

    settings = app_settings.reload_app_settings()
    assert settings['vapid_contact_email'] == 'v2@test.com'


# ---------------------------------------------------------------------------
# get_vapid_claims_email (in push_manager)
# ---------------------------------------------------------------------------


def test_get_vapid_claims_email_with_email(monkeypatch):
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {
            'vapid_contact_email': 'push@mysite.com',
            'trust_proxy_headers': False,
            'session_cookie_secure': False,
        },
    )

    email = push_manager.get_vapid_claims_email()

    assert email == 'mailto:push@mysite.com'


def test_get_vapid_claims_email_already_has_mailto(tmp_path, monkeypatch):
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {
            'vapid_contact_email': 'mailto:already@set.com',
            'trust_proxy_headers': False,
            'session_cookie_secure': False,
        },
    )

    email = push_manager.get_vapid_claims_email()

    assert email == 'mailto:already@set.com'


def test_get_vapid_claims_email_empty_returns_default(tmp_path, monkeypatch):
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {
            'vapid_contact_email': '',
            'trust_proxy_headers': False,
            'session_cookie_secure': False,
        },
    )

    email = push_manager.get_vapid_claims_email()

    assert email == 'mailto:admin@localhost'


# ---------------------------------------------------------------------------
# get_vapid_contact_status (in push_manager)
# ---------------------------------------------------------------------------


def test_vapid_contact_status_not_set(monkeypatch):
    from utils import push_manager

    _set_cache(monkeypatch, {'vapid_contact_email': '', 'trust_proxy_headers': False, 'session_cookie_secure': False})

    status = push_manager.get_vapid_contact_status()

    assert status['ok'] is False
    assert status['reason'] == 'not_set'


def test_vapid_contact_status_invalid_domain(monkeypatch):
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {'vapid_contact_email': 'admin@localhost', 'trust_proxy_headers': False, 'session_cookie_secure': False},
    )

    status = push_manager.get_vapid_contact_status()

    assert status['ok'] is False
    assert status['reason'] == 'invalid_domain'


def test_vapid_contact_status_valid(monkeypatch):
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {'vapid_contact_email': 'admin@mysite.com', 'trust_proxy_headers': False, 'session_cookie_secure': False},
    )

    status = push_manager.get_vapid_contact_status()

    assert status['ok'] is True


def test_warn_deprecated_env_vars_logs_warning(monkeypatch):
    """deprecated env var present → warning is logged."""
    from utils import app_settings

    monkeypatch.setenv('SECRET_KEY', 'old_key_in_env')
    logged = []
    monkeypatch.setattr(app_settings.logger, 'warning', lambda msg, *a, **kw: logged.append(msg))

    app_settings._warn_deprecated_env_vars()

    assert logged
    assert 'Deprecated' in logged[0]


class TestLogRetentionDays:
    @pytest.mark.parametrize(
        'value, expected',
        [(30, 30), ('45', 45), (0, 0), (-5, 0), (99999, 3650), ('abc', 90), (None, 90), (True, 90)],
    )
    def test_normalize(self, value, expected):
        from utils import app_settings

        assert app_settings.normalize_log_retention_days(value) == expected

    def test_default_is_90_days(self, monkeypatch):
        from utils import app_settings

        _set_cache(monkeypatch, {})
        assert app_settings.get_log_retention_days() == 90

    def test_reads_saved_value(self, monkeypatch):
        from utils import app_settings

        _set_cache(monkeypatch, {'log_retention_days': 14})
        assert app_settings.get_log_retention_days() == 14


class TestLogLevels:
    @pytest.mark.parametrize(
        'value, expected',
        [
            ('debug', 'DEBUG'),
            (' Warning ', 'WARNING'),
            ('CRITICAL', 'CRITICAL'),
            ('verbose', 'INFO'),
            (None, 'INFO'),
            (10, 'INFO'),
        ],
    )
    def test_normalize(self, value, expected):
        from utils import app_settings

        assert app_settings.normalize_log_level(value, 'INFO') == expected

    def test_defaults_are_info_file_and_warning_console(self, monkeypatch):
        from utils import app_settings

        _set_cache(monkeypatch, {})
        assert app_settings.get_log_levels() == ('INFO', 'WARNING')

    def test_reads_saved_values_and_ignores_invalid_ones(self, monkeypatch):
        from utils import app_settings

        _set_cache(monkeypatch, {'log_level': 'debug', 'console_log_level': 'nonsense'})
        assert app_settings.get_log_levels() == ('DEBUG', 'WARNING')
