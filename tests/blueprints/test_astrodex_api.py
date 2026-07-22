"""API tests for Astrodex catalogue alias switching."""
import os
import sys
import tempfile
import types
import uuid

import pytest

from observation import astrodex  # type: ignore[import-not-found]
from skytonight import skytonight_targets  # type: ignore[import-not-found]
from utils.auth import user_manager  # type: ignore[import-not-found]

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app  # type: ignore[import-not-found]
from blueprints import astrodex as astrodex_bp_module  # type: ignore[import-not-found]


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        user = user_manager.get_user_by_username('admin')
        assert user is not None
        with client.session_transaction() as session:
            session['user_id'] = user.user_id
            session['username'] = user.username
            session['role'] = user.role
        yield client


def _fake_alias_entry(catalogue: str, object_name: str) -> dict:
    entry = {
        'group_id': 'OBJ000001',
        'aliases': {
            'GaryImm': 'M81',
            'OpenNGC': 'NGC 3031'
        }
    }

    if catalogue == 'GaryImm' and object_name == 'M81':
        return entry
    if catalogue == 'OpenNGC' and object_name == 'NGC 3031':
        return entry
    return {}


def test_switch_catalogue_name_api(client, monkeypatch):
    """Test switching displayed name via API endpoint."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', _fake_alias_entry)

        user = user_manager.get_user_by_username('admin')
        item = astrodex.create_astrodex_item(
            user.user_id,
            {'name': 'M81', 'type': 'Galaxy', 'catalogue': 'GaryImm'},
            username=user.username
        )
        assert item is not None

        response = client.post(
            f"/api/astrodex/items/{item['id']}/catalogue-name",
            json={'catalogue': 'OpenNGC'}
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['status'] == 'success'
        assert payload['item']['name'] == 'NGC 3031'
        assert payload['item']['catalogue'] == 'OpenNGC'


def test_switch_catalogue_name_api_missing_catalogue(client):
    """Test missing catalogue field is rejected."""
    response = client.post('/api/astrodex/items/bad-id/catalogue-name', json={})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['error'] == 'Target catalogue is required'


def test_get_astrodex_public_mode_includes_other_users_items(client, monkeypatch):
    """Public mode should expose shared view with non-owned items."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        monkeypatch.setattr(astrodex_bp_module, 'load_config', lambda: {'astrodex': {'private': False}})

        admin_user = user_manager.get_user_by_username('admin')
        assert admin_user is not None

        other_username = f"user_{uuid.uuid4().hex[:8]}"
        other_user = user_manager.create_user(other_username, 'test123', 'user')

        admin_item = astrodex.create_astrodex_item(
            admin_user.user_id,
            {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'},
            username=admin_user.username
        )
        assert admin_item is not None

        other_item = astrodex.create_astrodex_item(
            other_user.user_id,
            {'name': 'M42', 'type': 'Nebula', 'catalogue': 'Messier'},
            username=other_user.username
        )
        assert other_item is not None

        response = client.get('/api/astrodex')
        assert response.status_code == 200
        payload = response.get_json()

        assert payload['private_mode'] is False
        items = payload['items']
        assert len(items) >= 2
        assert any(item.get('is_owned_by_current_user') is True for item in items)
        assert any(item.get('is_owned_by_current_user') is False for item in items)


def test_get_astrodex_private_mode_hides_other_users_items(client, monkeypatch):
    """Private mode should return only current user astrodex."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        monkeypatch.setattr(astrodex_bp_module, 'load_config', lambda: {'astrodex': {'private': True}})

        admin_user = user_manager.get_user_by_username('admin')
        assert admin_user is not None

        other_username = f"user_{uuid.uuid4().hex[:8]}"
        other_user = user_manager.create_user(other_username, 'test123', 'user')

        admin_item = astrodex.create_astrodex_item(
            admin_user.user_id,
            {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'},
            username=admin_user.username
        )
        assert admin_item is not None

        other_item = astrodex.create_astrodex_item(
            other_user.user_id,
            {'name': 'M42', 'type': 'Nebula', 'catalogue': 'Messier'},
            username=other_user.username
        )
        assert other_item is not None

        response = client.get('/api/astrodex')
        assert response.status_code == 200
        payload = response.get_json()

        assert payload['private_mode'] is True
        items = payload['items']
        assert len(items) == 1
        assert items[0].get('is_owned_by_current_user') is True


def test_get_astrodex_map_shared_mode_includes_other_users_coordinates(client, monkeypatch):
    """map_private=False should expose every user's geotagged pictures with real coordinates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        monkeypatch.setattr(astrodex_bp_module, 'load_config', lambda: {'astrodex': {'map_private': False}})

        admin_user = user_manager.get_user_by_username('admin')
        assert admin_user is not None

        other_username = f"user_{uuid.uuid4().hex[:8]}"
        other_user = user_manager.create_user(other_username, 'test123', 'user')

        admin_item = astrodex.create_astrodex_item(
            admin_user.user_id,
            {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'},
            username=admin_user.username
        )
        assert admin_item is not None
        astrodex.add_picture_to_item(admin_user.user_id, admin_item['id'], {
            'filename': 'admin_pic.jpg', 'latitude': 45.1, 'longitude': 5.2,
        })

        other_item = astrodex.create_astrodex_item(
            other_user.user_id,
            {'name': 'M42', 'type': 'Nebula', 'catalogue': 'Messier'},
            username=other_user.username
        )
        assert other_item is not None
        astrodex.add_picture_to_item(other_user.user_id, other_item['id'], {
            'filename': 'other_pic.jpg', 'latitude': 48.8, 'longitude': 2.3,
        })

        response = client.get('/api/astrodex/map')
        assert response.status_code == 200
        payload = response.get_json()

        assert payload['map_private'] is False
        points = payload['points']
        assert len(points) == 2
        by_owner = {p['owner_username']: p for p in points}
        assert by_owner[admin_user.username]['latitude'] == 45.1
        assert by_owner[other_user.username]['latitude'] == 48.8
        assert by_owner[other_user.username]['is_owned_by_current_user'] is False


def test_get_astrodex_map_private_mode_hides_other_users_points(client, monkeypatch):
    """map_private=True should return only the current user's own geotagged pictures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        monkeypatch.setattr(astrodex_bp_module, 'load_config', lambda: {'astrodex': {'map_private': True}})

        admin_user = user_manager.get_user_by_username('admin')
        assert admin_user is not None

        other_username = f"user_{uuid.uuid4().hex[:8]}"
        other_user = user_manager.create_user(other_username, 'test123', 'user')

        admin_item = astrodex.create_astrodex_item(
            admin_user.user_id,
            {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'},
            username=admin_user.username
        )
        assert admin_item is not None
        astrodex.add_picture_to_item(admin_user.user_id, admin_item['id'], {
            'filename': 'admin_pic.jpg', 'latitude': 45.1, 'longitude': 5.2,
        })

        other_item = astrodex.create_astrodex_item(
            other_user.user_id,
            {'name': 'M42', 'type': 'Nebula', 'catalogue': 'Messier'},
            username=other_user.username
        )
        assert other_item is not None
        astrodex.add_picture_to_item(other_user.user_id, other_item['id'], {
            'filename': 'other_pic.jpg', 'latitude': 48.8, 'longitude': 2.3,
        })

        response = client.get('/api/astrodex/map')
        assert response.status_code == 200
        payload = response.get_json()

        assert payload['map_private'] is True
        points = payload['points']
        assert len(points) == 1
        assert points[0]['owner_username'] == admin_user.username


def test_get_astrodex_map_internal_error_returns_500(client, monkeypatch):
    """An unexpected exception building the map payload is caught and returns a generic 500."""
    def _raise(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(astrodex_bp_module.astrodex, 'get_astrodex_map_points', _raise)

    response = client.get('/api/astrodex/map')
    assert response.status_code == 500
    assert response.get_json()['error'] == 'Internal server error'


def test_add_astrodex_item_duplicate_returns_409_with_existing_item(client, monkeypatch):
    """Adding a duplicate object returns 409 with the existing item's id and name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')

        user = user_manager.get_user_by_username('admin')
        existing = astrodex.create_astrodex_item(
            user.user_id,
            {'name': 'M42', 'type': 'Nebula', 'catalogue': ''},
            username=user.username,
        )
        assert existing is not None

        response = client.post(
            '/api/astrodex/items',
            json={'name': 'M42', 'type': 'Nebula', 'catalogue': ''},
        )
        assert response.status_code == 409
        payload = response.get_json()
        assert payload['error'] == 'duplicate'
        assert payload['existing_item']['id'] == existing['id']
        assert payload['existing_item']['name'] == 'M42'


def test_get_astrodex_image_private_mode_blocks_other_user_images(client, monkeypatch):
    """In private mode, image endpoint must reject images not owned by current user."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        astrodex.ensure_astrodex_directories()
        monkeypatch.setattr(astrodex_bp_module, 'load_config', lambda: {'astrodex': {'private': True}})

        admin_user = user_manager.get_user_by_username('admin')
        assert admin_user is not None

        other_username = f"user_{uuid.uuid4().hex[:8]}"
        other_user = user_manager.create_user(other_username, 'test123', 'user')

        admin_item = astrodex.create_astrodex_item(
            admin_user.user_id,
            {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'},
            username=admin_user.username
        )
        assert admin_item is not None

        other_item = astrodex.create_astrodex_item(
            other_user.user_id,
            {'name': 'M42', 'type': 'Nebula', 'catalogue': 'Messier'},
            username=other_user.username
        )
        assert other_item is not None

        astrodex.add_picture_to_item(admin_user.user_id, admin_item['id'], {'filename': 'own.jpg'})
        astrodex.add_picture_to_item(other_user.user_id, other_item['id'], {'filename': 'other.jpg'})

        own_image = os.path.join(astrodex.ASTRODEX_IMAGES_DIR, 'own.jpg')
        other_image = os.path.join(astrodex.ASTRODEX_IMAGES_DIR, 'other.jpg')
        with open(own_image, 'wb') as file_obj:
            file_obj.write(b'img')
        with open(other_image, 'wb') as file_obj:
            file_obj.write(b'img')

        own_response = client.get('/api/astrodex/images/own.jpg')
        own_response.get_data()
        own_response.close()
        assert own_response.status_code == 200

        other_response = client.get('/api/astrodex/images/other.jpg')
        other_response.get_data()
        other_response.close()
        assert other_response.status_code == 403


def test_resolve_picture_location_snapshot_falls_through_on_lookup_miss(monkeypatch):
    """Defensive branch: location_id resolves as accessible but a direct lookup
    still misses (e.g. a race with a concurrent delete) - must fall through to
    the custom-label/empty path rather than crash."""
    fake_user = types.SimpleNamespace(user_id='u1')
    monkeypatch.setattr(astrodex_bp_module, 'load_config', lambda: {'locations': []})
    monkeypatch.setattr(astrodex_bp_module, 'get_locations_for_user', lambda config, user: [{'id': 'loc-1'}])
    monkeypatch.setattr(astrodex_bp_module, 'get_location_by_id', lambda config, loc_id: None)

    result = astrodex_bp_module._resolve_picture_location_snapshot('loc-1', fake_user)

    assert result == astrodex_bp_module._EMPTY_PICTURE_LOCATION
