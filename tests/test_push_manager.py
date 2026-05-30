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
