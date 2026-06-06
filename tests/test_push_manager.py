"""Tests for push_manager.py: VAPID key management and Web Push delivery."""

import json
import sys
import types

import pytest

backend_path = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')


@pytest.fixture(autouse=True)
def reset_vapid_cache():
    import push_manager
    push_manager._vapid_keys = {}
    yield
    push_manager._vapid_keys = {}


# ---------------------------------------------------------------------------
# load_or_generate_vapid_keys
# ---------------------------------------------------------------------------

def test_loads_keys_from_disk(tmp_path, monkeypatch):
    import push_manager

    expected = {'private_key': 'PRIV_PEM', 'public_key': 'BASE64_PUB'}
    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text(json.dumps(expected))
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == expected
    assert push_manager._vapid_keys == expected


def test_generates_and_persists_when_no_file(tmp_path, monkeypatch):
    import push_manager

    vapid_file = tmp_path / 'vapid.json'
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    fake_keys = {'private_key': 'GEN_PRIV', 'public_key': 'GEN_PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys
    assert vapid_file.exists()
    assert json.loads(vapid_file.read_text()) == fake_keys


def test_regenerates_on_corrupt_file(tmp_path, monkeypatch):
    import push_manager

    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text('not { valid json !!!')
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    fake_keys = {'private_key': 'NEW_PRIV', 'public_key': 'NEW_PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys


def test_regenerates_when_file_missing_required_keys(tmp_path, monkeypatch):
    import push_manager

    vapid_file = tmp_path / 'vapid.json'
    vapid_file.write_text(json.dumps({'public_key': 'ONLY_PUBLIC'}))  # missing private_key
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))

    fake_keys = {'private_key': 'REGEN_PRIV', 'public_key': 'REGEN_PUB'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys == fake_keys


def test_returns_cached_keys_without_regenerating(monkeypatch):
    import push_manager

    push_manager._vapid_keys = {'private_key': 'CACHED', 'public_key': 'CACHED_PUB'}

    generate_called = []
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: generate_called.append(1) or {})

    keys = push_manager.load_or_generate_vapid_keys()

    assert keys['private_key'] == 'CACHED'
    assert not generate_called


# ---------------------------------------------------------------------------
# get_vapid_public_key
# ---------------------------------------------------------------------------

def test_get_vapid_public_key_returns_public_part():
    import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'MY_PUB_KEY'}

    assert push_manager.get_vapid_public_key() == 'MY_PUB_KEY'


# ---------------------------------------------------------------------------
# send_push
# ---------------------------------------------------------------------------

def test_send_push_returns_true_on_success(monkeypatch):
    import push_manager

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
    import push_manager

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
    import push_manager

    push_manager._vapid_keys = {'private_key': 'PRIV', 'public_key': 'PUB'}

    fake_pywebpush = types.ModuleType('pywebpush')
    fake_pywebpush.webpush = lambda **kw: (_ for _ in ()).throw(RuntimeError('Subscription expired'))
    monkeypatch.setitem(sys.modules, 'pywebpush', fake_pywebpush)

    sub = {'endpoint': 'https://push.example.com/v1/dead', 'keys': {}}
    result = push_manager.send_push(sub, {'title': 'Test'})

    assert result is False


def test_send_push_serializes_payload_as_json(monkeypatch):
    import push_manager

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
# _pem_to_raw_b64 (lines 44-48)
# ---------------------------------------------------------------------------

def test_pem_to_raw_b64_converts_key(monkeypatch):
    """Lines 44-48: convert PEM EC key to raw base64url scalar."""
    import push_manager
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
# _generate_keys (lines 53-67)
# ---------------------------------------------------------------------------

def test_generate_keys_returns_base64_key_pair(monkeypatch):
    """Lines 53-67: _generate_keys produces private_key and public_key."""
    import push_manager
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
    """Lines 76->82: empty vapid_contact_email → warning emitted once."""
    import push_manager
    import app_settings

    push_manager._VAPID_CONTACT_WARNING_EMITTED = False
    vapid_file = tmp_path / 'vapid.json'
    monkeypatch.setattr(push_manager, '_VAPID_FILE', str(vapid_file))
    app_settings._cache = {'vapid_contact_email': '', 'trust_proxy_headers': False, 'session_cookie_secure': False}

    fake_keys = {'private_key': 'P', 'public_key': 'K'}
    monkeypatch.setattr(push_manager, '_generate_keys', lambda: fake_keys)

    warnings_logged = []
    monkeypatch.setattr(push_manager.logger, 'warning', lambda msg, *a, **kw: warnings_logged.append(msg))

    push_manager.load_or_generate_vapid_keys()

    assert push_manager._VAPID_CONTACT_WARNING_EMITTED is True
    assert any('VAPID contact email' in w for w in warnings_logged)
    push_manager._VAPID_CONTACT_WARNING_EMITTED = False


def test_load_migrates_pem_private_key_to_raw_b64(tmp_path, monkeypatch):
    """Lines 92-95: PEM private key in file gets migrated to raw base64url."""
    import push_manager

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
    """Lines 108-109: exception writing VAPID keys → error logged, keys still returned."""
    import push_manager
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
