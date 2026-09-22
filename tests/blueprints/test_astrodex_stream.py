"""Route tests for the AstroDex Stream blueprint.

GET  /api/astrodex/stream/urls
GET  /api/astrodex/stream/<user_id>/<token>/current.jpg
GET  /api/astrodex/stream/shared/<token>/current.jpg
POST /api/connectors/astrodex_stream/rotate
"""

import os
import sys
import tempfile
import types
import uuid

import pytest
from PIL import Image

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from observation import astrodex
from observation import astrodex_stream
from blueprints import astrodex_stream as bp


def _cfg(**overrides):
    cfg = {
        'enabled': True,
        'display_seconds': 20,
        'transition': 'fade',
        'transition_seconds': 2,
        'aspect_ratio': '16:9',
        'label': '',
    }
    cfg.update(overrides)
    return cfg


def _app_config(astrodex_stream_cfg=None, private=False):
    return {
        'connectors': {'astrodex_stream': astrodex_stream_cfg if astrodex_stream_cfg is not None else _cfg()},
        'astrodex': {'private': private},
    }


@pytest.fixture
def env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        astrodex.ensure_astrodex_directories()
        astrodex_stream._FRAME_CACHE.clear()
        bp._rate_hits.clear()
        yield tmpdir
        astrodex_stream._FRAME_CACHE.clear()
        bp._rate_hits.clear()


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


@pytest.fixture
def client():
    from app import app as flask_app

    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def real_user():
    """A real, registered non-admin account - unlike the cookieless stream routes (which only
    need a user_id string out of the URL), /urls goes through get_current_user(), which does
    an actual UserManager lookup by username and returns None for a fabricated session."""
    from utils.auth import user_manager

    username = f"stream_test_{uuid.uuid4().hex[:8]}"
    return user_manager.create_user(username, 'password123', 'user')


@pytest.fixture
def client_user(real_user):
    from app import app as flask_app

    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = real_user.user_id
            sess['username'] = real_user.username
            sess['role'] = real_user.role
        yield c


@pytest.fixture
def client_admin():
    from app import app as flask_app
    from utils.auth import user_manager

    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        user = user_manager.get_user_by_username('admin')
        assert user is not None
        with c.session_transaction() as sess:
            sess['user_id'] = user.user_id
            sess['username'] = user.username
            sess['role'] = user.role
        yield c


def _seed_picture(uid, filename='pic.jpg'):
    item = astrodex.create_astrodex_item(uid, {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'})
    astrodex.add_picture_to_item(uid, item['id'], {'filename': filename, 'date': '2026-09-20'})
    Image.new('RGB', (2000, 1000), (60, 60, 90)).save(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, filename), 'JPEG')


class TestGetStreamUrls:

    def test_requires_login(self, env, client):
        resp = client.get('/api/astrodex/stream/urls')
        assert resp.status_code == 401

    def test_disabled_connector_reports_disabled(self, env, client_user, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(_cfg(enabled=False)))
        resp = client_user.get('/api/astrodex/stream/urls')
        assert resp.status_code == 200
        assert resp.get_json() == {'enabled': False}

    def test_enabled_and_not_private_returns_both_urls(self, env, client_user, real_user, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(private=False))
        data = client_user.get('/api/astrodex/stream/urls').get_json()
        assert data['enabled'] is True
        assert f"/api/astrodex/stream/{real_user.user_id}/" in data['personal_url']
        assert data['shared_url'] is not None
        assert '/api/astrodex/stream/shared/' in data['shared_url']

    def test_private_mode_omits_the_shared_url(self, env, client_user, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(private=True))
        data = client_user.get('/api/astrodex/stream/urls').get_json()
        assert data['enabled'] is True
        assert data['personal_url'] is not None
        assert data['shared_url'] is None


class TestPersonalStream:

    def test_serves_a_jpeg_with_a_valid_token(self, env, client, user_id, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config())
        _seed_picture(user_id)
        token = astrodex_stream.personal_token(user_id)
        resp = client.get(f'/api/astrodex/stream/{user_id}/{token}/current.jpg')
        assert resp.status_code == 200
        assert resp.mimetype == 'image/jpeg'
        assert resp.headers.get('Cache-Control') == 'no-store'

    def test_wrong_token_is_404_not_403(self, env, client, user_id, monkeypatch):
        """404, not 403: an invalid stream URL must not confirm a user_id exists."""
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config())
        resp = client.get(f'/api/astrodex/stream/{user_id}/deadbeef00000000/current.jpg')
        assert resp.status_code == 404

    def test_a_users_token_does_not_work_for_another_users_path(self, env, client, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config())
        token_for_a = astrodex_stream.personal_token('user-a')
        resp = client.get(f'/api/astrodex/stream/user-b/{token_for_a}/current.jpg')
        assert resp.status_code == 404

    def test_disabled_connector_is_404_even_with_a_valid_token(self, env, client, user_id, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(_cfg(enabled=False)))
        token = astrodex_stream.personal_token(user_id)
        resp = client.get(f'/api/astrodex/stream/{user_id}/{token}/current.jpg')
        assert resp.status_code == 404

    def test_no_session_cookie_required(self, env, client, user_id, monkeypatch):
        """Cookieless by design - Home Assistant/VLC cannot do a session login."""
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config())
        token = astrodex_stream.personal_token(user_id)
        resp = client.get(f'/api/astrodex/stream/{user_id}/{token}/current.jpg')
        assert resp.status_code == 200
        assert 'Set-Cookie' not in resp.headers or 'session' not in resp.headers.get('Set-Cookie', '')


class TestSharedStream:

    def test_serves_a_jpeg_when_not_private(self, env, client, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(private=False))
        token = astrodex_stream.shared_token()
        resp = client.get(f'/api/astrodex/stream/shared/{token}/current.jpg')
        assert resp.status_code == 200
        assert resp.mimetype == 'image/jpeg'

    def test_404_when_the_board_is_private_even_with_a_valid_token(self, env, client, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(private=True))
        token = astrodex_stream.shared_token()
        resp = client.get(f'/api/astrodex/stream/shared/{token}/current.jpg')
        assert resp.status_code == 404

    def test_a_stale_shared_url_becomes_404_the_moment_private_mode_is_turned_on(self, env, client, monkeypatch):
        """The 'private' check happens per-request, not baked into the token at mint time -
        so flipping the admin setting takes effect immediately, without rotating any keys."""
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(private=False))
        token = astrodex_stream.shared_token()
        assert client.get(f'/api/astrodex/stream/shared/{token}/current.jpg').status_code == 200

        monkeypatch.setattr(bp, 'load_config', lambda: _app_config(private=True))
        assert client.get(f'/api/astrodex/stream/shared/{token}/current.jpg').status_code == 404


class TestRateLimit:

    def test_returns_429_past_the_limit(self, env, client, user_id, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config())
        monkeypatch.setattr(bp, '_RATE_LIMIT', 3)
        token = astrodex_stream.personal_token(user_id)
        url = f'/api/astrodex/stream/{user_id}/{token}/current.jpg'
        statuses = [client.get(url).status_code for _ in range(4)]
        assert statuses == [200, 200, 200, 429]


class TestRotate:

    def test_requires_admin(self, env, client_user):
        resp = client_user.post('/api/connectors/astrodex_stream/rotate')
        assert resp.status_code == 403

    def test_admin_rotation_invalidates_existing_urls(self, env, client_admin, client, user_id, monkeypatch):
        monkeypatch.setattr(bp, 'load_config', lambda: _app_config())
        old_token = astrodex_stream.personal_token(user_id)
        resp = client_admin.post('/api/connectors/astrodex_stream/rotate')
        assert resp.status_code == 200

        stale = client.get(f'/api/astrodex/stream/{user_id}/{old_token}/current.jpg')
        assert stale.status_code == 404

        new_token = astrodex_stream.personal_token(user_id)
        fresh = client.get(f'/api/astrodex/stream/{user_id}/{new_token}/current.jpg')
        assert fresh.status_code == 200
