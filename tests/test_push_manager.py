"""Tests for push_manager.py: VAPID key management and Web Push delivery."""

import json
import os
import sys
import types

import pytest

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')


@pytest.fixture(autouse=True)
def reset_vapid_cache():
    from utils import push_manager
    push_manager._vapid_keys = {}
    yield
    push_manager._vapid_keys = {}


def test_push_manager_handles_missing_psutil(monkeypatch):
    monkeypatch.delitem(sys.modules, 'psutil', raising=False)
    import importlib
    from utils import push_manager
    importlib.reload(push_manager)
    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}
    assert push_manager.get_vapid_public_key() == 'PUB'


# ---------------------------------------------------------------------------
# load_or_generate_vapid_keys
# ---------------------------------------------------------------------------

def test_loads_keys_from_disk(tmp_path, monkeypatch):
    from utils import push_manager

    expected = {'private_key': 'PRIV_PEM', 'public_key': 'BASE64_PUB'}
    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text(json.dumps(expected))
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == expected
    assert push_manager._vapid_keys == expected


def test_generates_and_persists_when_no_file(tmp_path, monkeypatch):
    from utils import push_manager

    vapid_file = tmp_path / 'vapid.json'
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    fake_keys = {'private_key': 'GEN_PRIV', 'public_key': 'GEN_PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys
    assert vapid_file.exists()
    assert json.loads(vapid_file.read_text()) == fake_keys


def test_regenerates_on_corrupt_file(tmp_path, monkeypatch):
    from utils import push_manager

    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text('not { valid json !!!')
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    fake_keys = {'private_key': 'NEW_PRIV', 'public_key': 'NEW_PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys


def test_regenerates_when_file_missing_required_keys(tmp_path, monkeypatch):
    from utils import push_manager

    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text(json.dumps({'public_key': 'ONLY_PUBLIC'}))  # missing private_key
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    fake_keys = {'private_key': 'REGEN_PRIV', 'public_key': 'REGEN_PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys


def test_returns_cached_keys_without_regenerating(monkeypatch):
    from utils import push_manager
    from unittest.mock import MagicMock

    push_manager._vapid_keys = {'private_key': 'CACHED', 'public_key': 'CACHED_PUB'}

    mock_generate = MagicMock(return_value={})
    monkeypatch.setattr(push_manager, '_generate_keys', mock_generate)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys['private_key'] == 'CACHED'
    mock_generate.assert_not_called()


# ---------------------------------------------------------------------------
# get_vapid_public_key
# ---------------------------------------------------------------------------

def test_get_vapid_public_key_returns_public_part():
    from utils import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'MY_PUB_KEY'}

    assert push_manager.get_vapid_public_key() == 'MY_PUB_KEY'


# ---------------------------------------------------------------------------
# send_push
# ---------------------------------------------------------------------------

def test_send_push_returns_true_on_success(monkeypatch):
    from utils import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}

    webpush_calls = []
    fake_pywebpush = types.ModuleType('pywebpush')
    fake_pywebpush.webpush = lambda **kw: webpush_calls.append(kw)
    monkeypatch.setitem(sys.modules, 'pywebpush', fake_pywebpush)

    sub = {'endpoint': 'https://push.example.com/v1/abc', 'keys': {'p256dh': 'X', 'auth': 'Y'}}
    result = push_manager.send_push(sub, {'title': 'Hello'})

    assert result is True
    assert len(webpush_calls) == 1
    assert webpush_calls[0]['subscription_info'] == sub


def test_send_push_passes_correct_vapid_claims(monkeypatch):
    from utils import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}

    calls = []
    fake_pywebpush = types.ModuleType('pywebpush')
    fake_pywebpush.webpush = lambda **kw: calls.append(kw)
    monkeypatch.setitem(sys.modules, 'pywebpush', fake_pywebpush)

    sub = {'endpoint': 'https://fcm.googleapis.com/v1/send/123', 'keys': {}}
    push_manager.send_push(sub, {'body': 'test'})

    claims = calls[0]['vapid_claims']
    assert claims['aud'] == 'https://fcm.googleapis.com'
    assert claims['sub'].startswith('mailto:')


def test_send_push_returns_false_on_delivery_error(monkeypatch):
    from utils import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}

    def _raise_subscription_expired(**kw):
        raise RuntimeError('Subscription expired')

    fake_pywebpush = types.ModuleType('pywebpush')
    fake_pywebpush.webpush = _raise_subscription_expired
    monkeypatch.setitem(sys.modules, 'pywebpush', fake_pywebpush)

    sub = {'endpoint': 'https://push.example.com/v1/dead', 'keys': {}}
    result = push_manager.send_push(sub, {'title': 'Test'})

    assert result is False


def test_send_push_serializes_payload_as_json(monkeypatch):
    from utils import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}

    calls = []
    fake_pywebpush = types.ModuleType('pywebpush')
    fake_pywebpush.webpush = lambda **kw: calls.append(kw)
    monkeypatch.setitem(sys.modules, 'pywebpush', fake_pywebpush)

    payload = {'title': 'Aurora Alert', 'body': 'Kp 7.0'}
    sub = {'endpoint': 'https://push.example.com/abc', 'keys': {}}
    push_manager.send_push(sub, payload)

    sent_data = json.loads(calls[0]['data'])
    assert sent_data == payload


# ---------------------------------------------------------------------------
# _pem_to_raw_b64
# ---------------------------------------------------------------------------

def test_pem_to_raw_b64_converts_key(monkeypatch):
    """convert PEM EC key to raw base64url scalar."""
    from utils import push_manager
    from unittest.mock import MagicMock

    fake_key = MagicMock()
    fake_key.private_numbers.return_value.private_value = 12345678901234567890123456789012

    fake_loader = MagicMock(return_value=fake_key)
    fake_serialization = MagicMock()
    fake_serialization.load_pem_private_key = fake_loader

    fake_crypto_mod = types.ModuleType('cryptography.hazmat.primitives.serialization')
    fake_crypto_mod.load_pem_private_key = fake_loader

    monkeypatch.setitem(sys.modules, 'cryptography.hazmat.primitives.serialization', fake_crypto_mod)

    result = push_manager._pem_to_raw_b64("-----BEGIN EC PRIVATE KEY-----\nFAKE\n-----END EC PRIVATE KEY-----")

    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# _generate_keys
# ---------------------------------------------------------------------------

def test_generate_keys_returns_base64_key_pair(monkeypatch):
    """_generate_keys produces private_key and public_key."""
    from utils import push_manager
    from unittest.mock import MagicMock

    fake_vapid = MagicMock()
    fake_vapid.private_key.private_numbers.return_value.private_value = int.from_bytes(b'\x01' * 32, 'big')
    fake_pub_bytes = b'\x04' + b'\x02' * 64  # uncompressed point: 65 bytes
    fake_vapid.public_key.public_bytes.return_value = fake_pub_bytes

    fake_vapid_cls = MagicMock(return_value=fake_vapid)
    fake_vapid_module = types.ModuleType('py_vapid')
    fake_vapid_module.Vapid = fake_vapid_cls

    fake_encoding = MagicMock()
    fake_public_format = MagicMock()
    fake_serialization_mod = types.ModuleType('cryptography.hazmat.primitives.serialization')
    fake_serialization_mod.Encoding = fake_encoding
    fake_serialization_mod.PublicFormat = fake_public_format

    monkeypatch.setitem(sys.modules, 'py_vapid', fake_vapid_module)
    monkeypatch.setitem(sys.modules, 'cryptography.hazmat.primitives.serialization', fake_serialization_mod)

    keys = push_manager._generate_keys()

    assert 'private_key' in keys
    assert 'public_key' in keys
    assert isinstance(keys['private_key'], str)
    assert isinstance(keys['public_key'], str)


# ---------------------------------------------------------------------------
# load_or_generate_vapid_keys — additional branches
# ---------------------------------------------------------------------------

def test_load_warns_when_vapid_contact_email_empty(tmp_path, monkeypatch):
    """empty vapid_contact_email → warning emitted once."""
    from utils import push_manager
    from utils import app_settings

    push_manager._VAPID_CONTACT_WARNING_EMITTED = False
    vapid_file = tmp_path / 'vapid.json'
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))
    monkeypatch.setattr(
        app_settings,
        'get_app_settings',
        lambda: {'vapid_contact_email': '', 'trust_proxy_headers': False, 'session_cookie_secure': False},
    )

    fake_keys = {'private_key': 'P', 'public_key': 'K'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    warnings_logged = []
    monkeypatch.setattr(push_manager.logger, 'warning', lambda msg, *a, **kw: warnings_logged.append(msg))

    push_manager.load_or_generate_vapid_keys()

    assert push_manager._VAPID_CONTACT_WARNING_EMITTED is True
    assert any('VAPID contact email' in w for w in warnings_logged)
    push_manager._VAPID_CONTACT_WARNING_EMITTED = False


def test_load_migrates_pem_private_key_to_raw_b64(tmp_path, monkeypatch):
    """PEM private key in file gets migrated to raw base64url."""
    from utils import push_manager

    pem_keys = {
        'private_key': '-----BEGIN EC PRIVATE KEY-----\nDUMMY\n-----END EC PRIVATE KEY-----',
        'public_key': 'BASE64_PUBLIC',
    }
    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text(json.dumps(pem_keys))
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))
    monkeypatch.setattr(push_manager, '_pem_to_raw_b64', lambda pem: 'CONVERTED_RAW_B64')

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys['private_key'] == 'CONVERTED_RAW_B64'
    saved = json.loads(vapid_file.read_text())
    assert saved['private_key'] == 'CONVERTED_RAW_B64'


def test_save_vapid_keys_disk_error_logs_and_returns_keys(tmp_path, monkeypatch):
    """exception writing VAPID keys → error logged, keys still returned."""
    from utils import push_manager
    import builtins

    vapid_file = tmp_path / 'vapid.json'
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))
    fake_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    real_open = builtins.open

    def mock_open(path, *args, **kw):
        mode = args[0] if args else kw.get('mode', 'r')
        if str(path) == str(vapid_file) and 'w' in str(mode):
            raise PermissionError("read-only filesystem")
        return real_open(path, *args, **kw)

    monkeypatch.setattr(builtins, 'open', mock_open)
    errors_logged = []
    monkeypatch.setattr(push_manager.logger, 'error', lambda msg, *a, **kw: errors_logged.append(msg))

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys
    assert errors_logged


def test_vapid_contact_email_configured_skips_warning(tmp_path, monkeypatch):
    """VAPID contact email IS set → skip the warning block."""
    from utils import push_manager
    from utils import app_settings

    push_manager._VAPID_CONTACT_WARNING_EMITTED = False

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'admin@example.com'})

    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text(json.dumps({'private_key': 'PRIV', 'public_key': 'PUB'}))
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys.get('private_key') == 'PRIV'
    assert not push_manager._VAPID_CONTACT_WARNING_EMITTED


# ---------------------------------------------------------------------------
# get_vapid_claims_email — branch where email already starts with mailto:/https://
# ---------------------------------------------------------------------------

def test_get_vapid_claims_email_already_has_mailto_prefix(monkeypatch):
    """Email already prefixed with 'mailto:' is returned unchanged."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'mailto:admin@example.com'})
    result = push_manager.get_vapid_claims_email()
    assert result == 'mailto:admin@example.com'


def test_get_vapid_claims_email_already_has_https_prefix(monkeypatch):
    """Email starting with 'https://' is returned unchanged (URL contact form)."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'https://example.com/contact'})
    result = push_manager.get_vapid_claims_email()
    assert result == 'https://example.com/contact'


def test_get_vapid_claims_email_plain_address_gets_mailto_prefix(monkeypatch):
    """Plain email address is prefixed with 'mailto:'."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'user@example.com'})
    result = push_manager.get_vapid_claims_email()
    assert result == 'mailto:user@example.com'


def test_get_vapid_claims_email_empty_returns_default(monkeypatch):
    """Empty contact email falls back to the default mailto:admin@localhost."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': ''})
    result = push_manager.get_vapid_claims_email()
    assert result == 'mailto:admin@localhost'


# ---------------------------------------------------------------------------
# get_vapid_contact_status
# ---------------------------------------------------------------------------

def test_get_vapid_contact_status_not_set(monkeypatch):
    """Empty contact email reports not_set."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': ''})
    result = push_manager.get_vapid_contact_status()
    assert result == {'ok': False, 'reason': 'not_set'}


def test_get_vapid_contact_status_localhost_domain(monkeypatch):
    """localhost domain is rejected as invalid."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'admin@localhost'})
    result = push_manager.get_vapid_contact_status()
    assert result['ok'] is False
    assert result['reason'] == 'invalid_domain'


def test_get_vapid_contact_status_example_domain(monkeypatch):
    """example.com domain is rejected as invalid."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'admin@example.com'})
    result = push_manager.get_vapid_contact_status()
    assert result['ok'] is False
    assert result['reason'] == 'invalid_domain'


def test_get_vapid_contact_status_valid_email(monkeypatch):
    """Valid production email domain returns ok=True."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'admin@mysite.com'})
    result = push_manager.get_vapid_contact_status()
    assert result == {'ok': True}


def test_get_vapid_contact_status_mailto_prefixed_valid(monkeypatch):
    """get_vapid_contact_status strips 'mailto:' prefix before checking domain."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'mailto:admin@mysite.com'})
    result = push_manager.get_vapid_contact_status()
    assert result == {'ok': True}


def test_get_vapid_contact_status_subdomain_of_bad(monkeypatch):
    """Domain ending with .local is treated as invalid."""
    from utils import push_manager
    from utils import app_settings

    monkeypatch.setattr(app_settings, 'get_app_settings', lambda: {'vapid_contact_email': 'admin@server.local'})
    result = push_manager.get_vapid_contact_status()
    assert result['ok'] is False
