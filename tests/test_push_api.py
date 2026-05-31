"""Tests for push notification API routes and User model push_subscriptions round-trip."""

import sys
import types

import pytest

backend_path = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app  # type: ignore[import-not-found]
from auth import User, user_manager  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_admin():
    app.config['TESTING'] = True
    with app.test_client() as c:
        admin = user_manager.get_user_by_username('admin')
        assert admin is not None
        with c.session_transaction() as sess:
            sess['user_id'] = admin.user_id
            sess['username'] = admin.username
            sess['role'] = admin.role
        yield c


@pytest.fixture
def push_user():
    """Isolated regular user with no push subscriptions."""
    existing = user_manager.get_user_by_username('_push_api_test')
    if existing:
        admin = user_manager.get_user_by_username('admin')
        try:
            user_manager.delete_user(existing.user_id, current_user_id=admin.user_id)
        except Exception:
            pass
    u = user_manager.create_user('_push_api_test', 'pw123', 'user')
    yield u
    admin = user_manager.get_user_by_username('admin')
    try:
        user_manager.delete_user(u.user_id, current_user_id=admin.user_id)
    except Exception:
        pass


@pytest.fixture
def client_push_user(push_user):
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = push_user.user_id
            sess['username'] = push_user.username
            sess['role'] = push_user.role
        yield c, push_user


# ---------------------------------------------------------------------------
# GET /api/push/vapid-public-key
# ---------------------------------------------------------------------------

def test_vapid_public_key_endpoint_returns_key(client_admin, monkeypatch):
    import push_manager
    monkeypatch.setattr(push_manager, 'get_vapid_public_key', lambda: 'FAKE_BASE64_PUBLIC_KEY')

    resp = client_admin.get('/api/push/vapid-public-key')

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['public_key'] == 'FAKE_BASE64_PUBLIC_KEY'


def test_vapid_public_key_endpoint_no_auth_required(monkeypatch):
    import push_manager
    monkeypatch.setattr(push_manager, 'get_vapid_public_key', lambda: 'ANON_KEY')

    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.get('/api/push/vapid-public-key')

    assert resp.status_code == 200


def test_vapid_public_key_endpoint_returns_503_on_error(client_admin, monkeypatch):
    import push_manager

    def boom():
        raise RuntimeError('VAPID not configured')

    monkeypatch.setattr(push_manager, 'get_vapid_public_key', boom)

    resp = client_admin.get('/api/push/vapid-public-key')

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/push/subscribe
# ---------------------------------------------------------------------------

_SAMPLE_SUB = {
    'endpoint': 'https://fcm.googleapis.com/v1/send/test-token',
    'keys': {'p256dh': 'BASE64_P256DH', 'auth': 'BASE64_AUTH'},
}


def _get_push_user(user):
    """Reload the user object to pick up changes saved during a request."""
    return user_manager.get_user_by_id(user.user_id)


def test_subscribe_adds_subscription(client_push_user):
    client, user = client_push_user

    resp = client.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})

    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'subscribed'
    refreshed = _get_push_user(user)
    assert any(s['endpoint'] == _SAMPLE_SUB['endpoint'] for s in refreshed.push_subscriptions)


def test_subscribe_deduplicates_same_endpoint(client_push_user):
    client, user = client_push_user

    client.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})
    client.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})

    refreshed = _get_push_user(user)
    matching = [s for s in refreshed.push_subscriptions if s['endpoint'] == _SAMPLE_SUB['endpoint']]
    assert len(matching) == 1


def test_subscribe_stores_keys_and_endpoint(client_push_user):
    client, user = client_push_user

    client.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})

    refreshed = _get_push_user(user)
    stored = next(s for s in refreshed.push_subscriptions if s['endpoint'] == _SAMPLE_SUB['endpoint'])
    assert stored['keys'] == _SAMPLE_SUB['keys']
    assert 'created_at' in stored


def test_subscribe_requires_authentication():
    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})
    assert resp.status_code in (401, 302)


def test_subscribe_rejects_missing_subscription(client_push_user):
    client, _ = client_push_user
    resp = client.post('/api/push/subscribe', json={})
    assert resp.status_code == 400


def test_subscribe_rejects_subscription_without_endpoint(client_push_user):
    client, _ = client_push_user
    resp = client.post('/api/push/subscribe', json={'subscription': {'keys': {'p256dh': 'X'}}})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/push/unsubscribe
# ---------------------------------------------------------------------------

def test_unsubscribe_removes_existing_subscription(client_push_user):
    client, user = client_push_user
    client.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})

    resp = client.delete('/api/push/unsubscribe', json={'endpoint': _SAMPLE_SUB['endpoint']})

    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'unsubscribed'
    refreshed = _get_push_user(user)
    assert not any(s['endpoint'] == _SAMPLE_SUB['endpoint'] for s in refreshed.push_subscriptions)


def test_unsubscribe_is_idempotent_for_missing_endpoint(client_push_user):
    client, _ = client_push_user

    resp = client.delete('/api/push/unsubscribe', json={'endpoint': 'https://push.example.com/gone'})

    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'unsubscribed'


def test_unsubscribe_only_removes_matching_endpoint(client_push_user):
    client, user = client_push_user
    other_sub = dict(_SAMPLE_SUB, endpoint='https://push.example.com/keeper')
    client.post('/api/push/subscribe', json={'subscription': _SAMPLE_SUB})
    client.post('/api/push/subscribe', json={'subscription': other_sub})

    client.delete('/api/push/unsubscribe', json={'endpoint': _SAMPLE_SUB['endpoint']})

    refreshed = _get_push_user(user)
    remaining = [s['endpoint'] for s in refreshed.push_subscriptions]
    assert 'https://push.example.com/keeper' in remaining
    assert _SAMPLE_SUB['endpoint'] not in remaining


def test_unsubscribe_requires_authentication():
    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.delete('/api/push/unsubscribe', json={'endpoint': 'https://push.example.com/x'})
    assert resp.status_code in (401, 302)


def test_unsubscribe_rejects_missing_endpoint_field(client_push_user):
    client, _ = client_push_user
    resp = client.delete('/api/push/unsubscribe', json={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# User model - push_subscriptions round-trip
# ---------------------------------------------------------------------------

def test_user_defaults_push_subscriptions_to_empty_list():
    u = User('alice', 'hash', 'user')
    assert u.push_subscriptions == []


def test_user_init_rejects_non_list_push_subscriptions():
    u = User('alice', 'hash', 'user', push_subscriptions='invalid')
    assert u.push_subscriptions == []


def test_user_to_dict_includes_push_subscriptions():
    subs = [{'endpoint': 'https://push.example.com/abc', 'keys': {'p256dh': 'X', 'auth': 'Y'}}]
    u = User('alice', 'hash', 'user', push_subscriptions=subs)

    d = u.to_dict()

    assert d['push_subscriptions'] == subs


def test_user_from_dict_restores_push_subscriptions():
    subs = [{'endpoint': 'https://push.example.com/abc', 'keys': {'p256dh': 'X', 'auth': 'Y'}}]
    data = {
        'user_id': 'uid-1',
        'username': 'alice',
        'password_hash': 'hash',
        'role': 'user',
        'push_subscriptions': subs,
    }

    u = User.from_dict(data)

    assert u.push_subscriptions == subs


def test_user_from_dict_defaults_push_subscriptions_to_empty_list():
    data = {
        'user_id': 'uid-2',
        'username': 'bob',
        'password_hash': 'hash',
        'role': 'user',
    }

    u = User.from_dict(data)

    assert u.push_subscriptions == []


def test_user_round_trip_preserves_push_subscriptions():
    subs = [
        {'endpoint': 'https://push.example.com/1', 'keys': {'p256dh': 'A', 'auth': 'B'}, 'created_at': '2026-01-01T00:00:00'},
        {'endpoint': 'https://push.example.com/2', 'keys': {'p256dh': 'C', 'auth': 'D'}, 'created_at': '2026-02-01T00:00:00'},
    ]
    original = User('charlie', 'hash', 'user', push_subscriptions=subs)

    restored = User.from_dict(original.to_dict())

    assert restored.push_subscriptions == subs


def test_user_manager_persists_push_subscriptions(tmp_path, monkeypatch):
    import auth

    users_file = tmp_path / 'users.json'
    monkeypatch.setattr(auth, 'USERS_FILE', str(users_file))

    mgr = auth.UserManager()
    user = mgr.create_user('dave', 'pw', 'user')
    user.push_subscriptions = [{'endpoint': 'https://push.example.com/dave', 'keys': {}}]
    mgr.save_users()

    mgr2 = auth.UserManager()
    loaded = mgr2.get_user_by_id(user.user_id)
    assert loaded is not None
    assert loaded.push_subscriptions == user.push_subscriptions
