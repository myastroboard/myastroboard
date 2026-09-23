"""Tests for app_settings.py: secret key generation and persistent app settings."""

import json

import pytest


@pytest.fixture(autouse=True)
def reset_app_settings_cache():
    """Clear the module-level cache (and its mtime marker) before and after each test."""
    from utils import app_settings

    app_settings._cache = None
    app_settings._cache_mtime = None
    yield
    app_settings._cache = None
    app_settings._cache_mtime = None


def _set_cache(monkeypatch, cache: dict):
    """Stub app_settings._cache directly and neutralize the mtime staleness check, so
    get_app_settings() returns exactly this dict regardless of what (if anything) is
    really on disk - several tests below use this to stub a settings value without
    writing a real file. Without neutralizing the check, get_app_settings() would see
    the stub's mtime (None) not match the real file's and immediately reload past it."""
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_file_mtime', lambda _path: 'frozen')
    app_settings._cache = cache
    app_settings._cache_mtime = 'frozen'


# ---------------------------------------------------------------------------
# load_or_generate_secret_key
# ---------------------------------------------------------------------------


def test_secret_key_generated_on_first_run(tmp_path, monkeypatch):
    from utils import app_settings

    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_SECRET_KEY_FILE', str(tmp_path / 'secret_key.txt'))

    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64  # token_hex(32) = 64 hex chars
    assert (tmp_path / 'secret_key.txt').exists()
    assert (tmp_path / 'secret_key.txt').read_text().strip() == key


def test_secret_key_persists_across_calls(tmp_path, monkeypatch):
    from utils import app_settings

    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_SECRET_KEY_FILE', str(tmp_path / 'secret_key.txt'))

    key1 = app_settings.load_or_generate_secret_key()
    key2 = app_settings.load_or_generate_secret_key()

    assert key1 == key2


def test_secret_key_loads_existing_file(tmp_path, monkeypatch):
    from utils import app_settings

    key_file = tmp_path / 'secret_key.txt'
    key_file.write_text('aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899')
    monkeypatch.setattr(app_settings, '_SECRET_KEY_FILE', str(key_file))

    key = app_settings.load_or_generate_secret_key()

    assert key == 'aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899'


# ---------------------------------------------------------------------------
# load_app_settings / get_app_settings
# ---------------------------------------------------------------------------


def test_app_settings_defaults_when_no_file(tmp_path, monkeypatch):
    from utils import app_settings

    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(tmp_path / 'app_settings.json'))

    settings = app_settings.load_app_settings()

    assert settings['vapid_contact_email'] == ''
    assert settings['trust_proxy_headers'] is False
    assert settings['session_cookie_secure'] is False


def test_app_settings_loads_from_disk(tmp_path, monkeypatch):
    from utils import app_settings

    settings_file = tmp_path / 'app_settings.json'
    settings_file.write_text(
        json.dumps(
            {
                'vapid_contact_email': 'admin@example.com',
                'trust_proxy_headers': True,
                'session_cookie_secure': True,
            }
        )
    )
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(settings_file))

    settings = app_settings.load_app_settings()

    assert settings['vapid_contact_email'] == 'admin@example.com'
    assert settings['trust_proxy_headers'] is True
    assert settings['session_cookie_secure'] is True


def test_app_settings_merges_missing_keys(tmp_path, monkeypatch):
    """Partial file should be merged with defaults."""
    from utils import app_settings

    settings_file = tmp_path / 'app_settings.json'
    settings_file.write_text(json.dumps({'vapid_contact_email': 'test@test.com'}))
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(settings_file))

    settings = app_settings.load_app_settings()

    assert settings['vapid_contact_email'] == 'test@test.com'
    assert settings['trust_proxy_headers'] is False  # default
    assert settings['session_cookie_secure'] is False  # default


def test_get_app_settings_uses_cache(tmp_path, monkeypatch):
    from utils import app_settings

    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(tmp_path / 'no_file.json'))
    app_settings._cache = {
        'vapid_contact_email': 'cached@test.com',
        'trust_proxy_headers': True,
        'session_cookie_secure': False,
    }
    # Simulate "this cache matches what's on disk right now" - get_app_settings() also
    # compares the file's mtime against this marker, not just whether _cache is warm.
    app_settings._cache_mtime = None  # 'no_file.json' does not exist -> mtime is None too

    settings = app_settings.get_app_settings()

    assert settings['vapid_contact_email'] == 'cached@test.com'


def test_get_app_settings_reloads_when_file_changes_on_disk(tmp_path, monkeypatch):
    """Multi-worker sync: a cache that no longer matches the file's mtime is stale,
    not just a cache that's cold - the exact bug this mtime check closes."""
    from utils import app_settings

    settings_file = tmp_path / 'app_settings.json'
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(settings_file))
    app_settings.save_app_settings({'vapid_contact_email': 'first@test.com'})

    # Pretend this worker's cache predates the file (another worker saved since).
    app_settings._cache_mtime = 0

    settings = app_settings.get_app_settings()

    assert settings['vapid_contact_email'] == 'first@test.com'
    assert app_settings._cache_mtime != 0


# ---------------------------------------------------------------------------
# save_app_settings
# ---------------------------------------------------------------------------


def test_save_app_settings_writes_file(tmp_path, monkeypatch):
    from utils import app_settings

    settings_file = tmp_path / 'app_settings.json'
    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(settings_file))

    app_settings.save_app_settings(
        {
            'vapid_contact_email': 'save@example.com',
            'trust_proxy_headers': True,
            'session_cookie_secure': False,
        }
    )

    saved = json.loads(settings_file.read_text())
    assert saved['vapid_contact_email'] == 'save@example.com'
    assert saved['trust_proxy_headers'] is True


def test_save_app_settings_updates_cache(tmp_path, monkeypatch):
    from utils import app_settings

    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(tmp_path / 'app_settings.json'))

    app_settings.save_app_settings({'vapid_contact_email': 'new@test.com'})

    assert app_settings._cache is not None
    assert app_settings._cache['vapid_contact_email'] == 'new@test.com'


# ---------------------------------------------------------------------------
# reload_app_settings
# ---------------------------------------------------------------------------


def test_reload_clears_cache_and_rereads(tmp_path, monkeypatch):
    from utils import app_settings

    settings_file = tmp_path / 'app_settings.json'
    settings_file.write_text(json.dumps({'vapid_contact_email': 'v1@test.com'}))
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(settings_file))

    app_settings.load_app_settings()
    assert app_settings._cache['vapid_contact_email'] == 'v1@test.com'

    # Update file on disk
    settings_file.write_text(json.dumps({'vapid_contact_email': 'v2@test.com'}))

    settings = app_settings.reload_app_settings()
    assert settings['vapid_contact_email'] == 'v2@test.com'


# ---------------------------------------------------------------------------
# get_vapid_claims_email (in push_manager)
# ---------------------------------------------------------------------------


def test_get_vapid_claims_email_with_email(tmp_path, monkeypatch):
    from utils import app_settings
    from utils import push_manager

    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(tmp_path / 'no_file.json'))
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
    from utils import app_settings
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
    from utils import app_settings
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
    from utils import app_settings
    from utils import push_manager

    _set_cache(monkeypatch, {'vapid_contact_email': '', 'trust_proxy_headers': False, 'session_cookie_secure': False})

    status = push_manager.get_vapid_contact_status()

    assert status['ok'] is False
    assert status['reason'] == 'not_set'


def test_vapid_contact_status_invalid_domain(monkeypatch):
    from utils import app_settings
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {'vapid_contact_email': 'admin@localhost', 'trust_proxy_headers': False, 'session_cookie_secure': False},
    )

    status = push_manager.get_vapid_contact_status()

    assert status['ok'] is False
    assert status['reason'] == 'invalid_domain'


def test_vapid_contact_status_valid(monkeypatch):
    from utils import app_settings
    from utils import push_manager

    _set_cache(
        monkeypatch,
        {'vapid_contact_email': 'admin@mysite.com', 'trust_proxy_headers': False, 'session_cookie_secure': False},
    )

    status = push_manager.get_vapid_contact_status()

    assert status['ok'] is True


# ---------------------------------------------------------------------------
# load_or_generate_secret_key — edge-case branches
# ---------------------------------------------------------------------------


def test_secret_key_regenerated_when_file_empty(tmp_path, monkeypatch):
    """file exists but stripped key is empty → regenerate."""
    from utils import app_settings

    key_file = tmp_path / 'secret_key.txt'
    key_file.write_text('   ')  # whitespace only → strip() gives ''
    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_SECRET_KEY_FILE', str(key_file))

    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64  # newly generated 32-byte hex


def test_secret_key_read_exception_regenerates(tmp_path, monkeypatch):
    """PermissionError reading key file → regenerate."""
    from utils import app_settings
    import builtins

    key_file = tmp_path / 'secret_key.txt'
    key_file.write_text('EXISTING')
    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_SECRET_KEY_FILE', str(key_file))

    real_open = builtins.open

    def mock_open(path, mode='r', *args, **kw):
        # Deny only the read of the secret-key file itself. A call-count-based
        # gate is order-dependent: in a full-suite run an unrelated open() (e.g.
        # a log-handler write) can absorb the failure before the read happens.
        if str(path) == str(key_file) and 'r' in mode and 'w' not in mode:
            raise PermissionError("denied by test")
        return real_open(path, mode, *args, **kw)

    monkeypatch.setattr(builtins, 'open', mock_open)
    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64


def test_secret_key_write_exception_still_returns_key(tmp_path, monkeypatch):
    """PermissionError writing key file → key returned from memory."""
    from utils import app_settings
    import builtins

    # No key file → skip to generate path
    monkeypatch.setattr(app_settings, '_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app_settings, '_SECRET_KEY_FILE', str(tmp_path / 'secret_key.txt'))

    real_open = builtins.open

    def mock_open(path, *args, **kw):
        mode = args[0] if args else kw.get('mode', 'r')
        if 'w' in str(mode):
            raise PermissionError("read-only fs")
        return real_open(path, *args, **kw)

    monkeypatch.setattr(builtins, 'open', mock_open)
    key = app_settings.load_or_generate_secret_key()

    assert len(key) == 64  # generated but not persisted


def test_load_app_settings_json_exception_uses_defaults(tmp_path, monkeypatch):
    """malformed JSON in settings file → return defaults."""
    from utils import app_settings

    settings_file = tmp_path / 'app_settings.json'
    settings_file.write_text('{ INVALID JSON }}}')
    monkeypatch.setattr(app_settings, '_APP_SETTINGS_FILE', str(settings_file))

    settings = app_settings.load_app_settings()

    assert settings == dict(app_settings._DEFAULTS)


def test_warn_deprecated_env_vars_logs_warning(monkeypatch):
    """deprecated env var present → warning is logged."""
    from utils import app_settings

    monkeypatch.setenv('SECRET_KEY', 'old_key_in_env')
    logged = []
    monkeypatch.setattr(app_settings.logger, 'warning', lambda msg, *a, **kw: logged.append(msg))

    app_settings._warn_deprecated_env_vars()

    assert logged
    assert 'Deprecated' in logged[0]
