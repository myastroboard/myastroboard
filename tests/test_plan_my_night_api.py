"""API tests for Plan My Night feature."""

import os
import sys
import tempfile
import types
from datetime import datetime, timedelta

import pytest

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

import app as app_module  # type: ignore[import-not-found]
from observation import astrodex  # type: ignore[import-not-found]
from observation import plan_my_night  # type: ignore[import-not-found]
from blueprints import plan_my_night as plan_my_night_bp_module  # type: ignore[import-not-found]
from skytonight import skytonight_targets  # type: ignore[import-not-found]
app = app_module.app
from utils.auth import user_manager  # type: ignore[import-not-found]


@pytest.fixture
def client_admin(monkeypatch):
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        plan_my_night.PLAN_DIR = os.path.join(tmpdir, 'projects')
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        astrodex.ensure_astrodex_directories()

        now = datetime.now().replace(second=0, microsecond=0)
        astro_night = {
            'start': (now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'),
            'end': (now + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M'),
            'duration_hours': 6.0,
        }
        monkeypatch.setattr(plan_my_night_bp_module, '_resolve_observing_night_for_plan', lambda: astro_night)

        with app.test_client() as test_client:
            user = user_manager.get_user_by_username('admin')
            assert user is not None
            with test_client.session_transaction() as session:
                session['user_id'] = user.user_id
                session['username'] = user.username
                session['role'] = user.role
            yield test_client


@pytest.fixture
def client_read_only(monkeypatch):
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        plan_my_night.PLAN_DIR = os.path.join(tmpdir, 'projects')

        read_only = user_manager.get_user_by_username('readonly_plan_test')
        if not read_only:
            read_only = user_manager.create_user('readonly_plan_test', 'test123', 'read-only')

        with app.test_client() as test_client:
            with test_client.session_transaction() as session:
                session['user_id'] = read_only.user_id
                session['username'] = read_only.username
                session['role'] = read_only.role
            yield test_client


def _sample_target(name='M42'):
    return {
        'item': {
            'name': name,
            'id': name,
            'type': 'Nebula',
            'constellation': 'orion',
            'foto': 0.91,
            'source_type': 'report',
        },
        'catalogue': 'Messier',
    }


def test_add_target_creates_plan(client_admin):
    response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert response.status_code == 200

    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['reason'] == 'added'

    get_response = client_admin.get('/api/plan-my-night')
    assert get_response.status_code == 200

    plan_payload = get_response.get_json()
    assert plan_payload['state'] == 'current'
    assert plan_payload['plan'] is not None
    assert len(plan_payload['plan']['entries']) == 1


def test_read_only_cannot_add_target(client_read_only):
    response = client_read_only.post('/api/plan-my-night/targets', json=_sample_target())
    assert response.status_code == 403


def test_previous_plan_blocks_new_add(client_admin):
    user = user_manager.get_user_by_username('admin')
    assert user is not None

    now = datetime.now().replace(second=0, microsecond=0)
    payload = {
        'user_id': user.user_id,
        'username': user.username,
        'plan': {
            'plan_date': (now - timedelta(days=1)).date().isoformat(),
            'night_start': (now - timedelta(days=1, hours=8)).astimezone().isoformat(),
            'night_end': (now - timedelta(days=1, hours=2)).astimezone().isoformat(),
            'duration_hours': 6.0,
            'entries': [
                {
                    'id': 'entry-old',
                    'name': 'M31',
                    'catalogue': 'Messier',
                    'planned_minutes': 60,
                    'planned_duration': '01:00',
                    'done': False,
                }
            ],
        }
    }
    saved = plan_my_night.save_user_plan(user.user_id, payload, username=user.username)
    assert saved is True

    response = client_admin.post('/api/plan-my-night/targets', json=_sample_target('M51'))
    assert response.status_code == 409


def test_export_csv(client_admin):
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200

    export_response = client_admin.get('/api/plan-my-night/export.csv')
    assert export_response.status_code == 200
    assert export_response.mimetype == 'text/csv'
    body = export_response.data.decode('utf-8')
    assert 'order,name,catalogue' in body
    assert 'M42' in body


def test_add_target_uses_skytonight_group_dedup(client_admin, monkeypatch):
    """Equivalent aliases should not create duplicate plan entries."""

    def fake_lookup_entry(catalogue, object_name, force_reload=False, dataset_file=None):
        entry = {
            'group_id': 'DSO-0001',
            'aliases': {
                'Messier': 'M 81',
                'OpenNGC': 'NGC 3031',
            },
        }
        if catalogue in {'Messier', 'OpenNGC'} and object_name in {'M 81', 'NGC 3031'}:
            return entry
        return {}

    monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup_entry)

    first_response = client_admin.post('/api/plan-my-night/targets', json={
        'item': {'name': 'M 81', 'id': 'M 81', 'type': 'Galaxy', 'source_type': 'report'},
        'catalogue': 'Messier',
    })
    assert first_response.status_code == 200
    assert first_response.get_json()['reason'] == 'added'

    second_response = client_admin.post('/api/plan-my-night/targets', json={
        'item': {'name': 'NGC 3031', 'id': 'NGC 3031', 'type': 'Galaxy', 'source_type': 'report'},
        'catalogue': 'OpenNGC',
    })
    assert second_response.status_code == 200
    assert second_response.get_json()['reason'] == 'already_in_plan'


def test_add_target_with_combination_id(client_admin):
    telescope = client_admin.post('/api/equipment/telescopes', json={
        'name': 'T1', 'telescope_type': 'Refractor', 'aperture_mm': 100, 'focal_length_mm': 1000,
    }).get_json()['data']
    combo = client_admin.post('/api/equipment/combinations', json={
        'name': 'My Combo', 'telescope_id': telescope['id'],
    }).get_json()['data']

    target = _sample_target()
    target['combination_id'] = combo['id']
    target['combination_name'] = combo['name']
    response = client_admin.post('/api/plan-my-night/targets', json=target)
    assert response.status_code == 200

    get_response = client_admin.get(f"/api/plan-my-night?combination_id={combo['id']}")
    assert get_response.status_code == 200
    plan_payload = get_response.get_json()
    assert plan_payload['plan']['combination_id'] == combo['id']
    assert plan_payload['plan']['combination_name'] == combo['name']


def test_list_plan_my_night_returns_combination_count(client_admin):
    # equipment_profiles.EQUIPMENT_DIR isn't isolated per-test by this fixture (only
    # PLAN_DIR/ASTRODEX_DIR are), so the admin user's combinations accumulate across
    # tests in this module - assert this combo is present rather than an absolute count.
    telescope = client_admin.post('/api/equipment/telescopes', json={
        'name': 'T2', 'telescope_type': 'Refractor', 'aperture_mm': 80, 'focal_length_mm': 600,
    }).get_json()['data']
    client_admin.post('/api/equipment/combinations', json={
        'name': 'Combo A', 'telescope_id': telescope['id'],
    })

    response = client_admin.get('/api/plan-my-night/list')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['combination_count'] >= 1
    assert any(p['combination_name'] == 'Combo A' for p in payload['plans'])


def test_optimize_returns_404_without_plan(client_admin):
    response = client_admin.get('/api/plan-my-night/optimize')
    assert response.status_code == 404


def test_optimize_returns_preview(client_admin):
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200

    response = client_admin.get('/api/plan-my-night/optimize')
    assert response.status_code == 200

    payload = response.get_json()
    assert payload['status'] == 'success'
    assert len(payload['preview']) == 1
    # No alttime_file on a manually-added item -> never observable this way.
    assert payload['preview'][0]['warnings'] == ['never_observable']
    assert 'start_delay_minutes' in payload
    assert 'order' in payload


def test_optimize_blocked_on_previous_plan(client_admin):
    user = user_manager.get_user_by_username('admin')
    assert user is not None

    now = datetime.now().replace(second=0, microsecond=0)
    payload = {
        'user_id': user.user_id,
        'username': user.username,
        'plan': {
            'plan_date': (now - timedelta(days=1)).date().isoformat(),
            'night_start': (now - timedelta(days=1, hours=8)).astimezone().isoformat(),
            'night_end': (now - timedelta(days=1, hours=2)).astimezone().isoformat(),
            'duration_hours': 6.0,
            'entries': [
                {
                    'id': 'entry-old',
                    'name': 'M31',
                    'catalogue': 'Messier',
                    'planned_minutes': 60,
                    'planned_duration': '01:00',
                    'done': False,
                }
            ],
        }
    }
    saved = plan_my_night.save_user_plan(user.user_id, payload, username=user.username)
    assert saved is True

    response = client_admin.get('/api/plan-my-night/optimize')
    assert response.status_code == 409


def test_read_only_cannot_view_optimize(client_read_only):
    response = client_read_only.get('/api/plan-my-night/optimize')
    assert response.status_code == 403


def test_optimize_apply_reorders_and_sets_delay(client_admin):
    add_first = client_admin.post('/api/plan-my-night/targets', json=_sample_target('M42'))
    assert add_first.status_code == 200
    add_second = client_admin.post('/api/plan-my-night/targets', json=_sample_target('M43'))
    assert add_second.status_code == 200

    preview = client_admin.get('/api/plan-my-night/optimize')
    assert preview.status_code == 200
    preview_payload = preview.get_json()

    apply_response = client_admin.post('/api/plan-my-night/optimize/apply', json={
        'order': preview_payload['order'],
        'start_delay_minutes': preview_payload['start_delay_minutes'],
    })
    assert apply_response.status_code == 200
    apply_payload = apply_response.get_json()
    assert apply_payload['status'] == 'success'
    entries = apply_payload['plan']['plan']['entries']
    assert [e['id'] for e in entries] == preview_payload['order']


def test_optimize_apply_rejects_stale_order(client_admin):
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200

    response = client_admin.post('/api/plan-my-night/optimize/apply', json={
        'order': ['does-not-exist'],
        'start_delay_minutes': 0,
    })
    assert response.status_code == 409


def test_optimize_apply_requires_order(client_admin):
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200

    response = client_admin.post('/api/plan-my-night/optimize/apply', json={'start_delay_minutes': 0})
    assert response.status_code == 400


def test_optimize_returns_404_when_compute_returns_none(client_admin, monkeypatch):
    """Deeper checks inside compute_optimized_schedule (e.g. corrupted night
    bounds) can return None even though a plan with entries exists and isn't
    in 'previous' state - the blueprint must still surface a 404, not a 500."""
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200

    monkeypatch.setattr(plan_my_night_bp_module.plan_my_night, 'compute_optimized_schedule', lambda *a, **kw: None)

    response = client_admin.get('/api/plan-my-night/optimize')
    assert response.status_code == 404


def test_optimize_exception_returns_500(client_admin, monkeypatch):
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200

    def _boom(*a, **kw):
        raise RuntimeError('boom')

    monkeypatch.setattr(plan_my_night_bp_module.plan_my_night, 'compute_optimized_schedule', _boom)

    response = client_admin.get('/api/plan-my-night/optimize')
    assert response.status_code == 500


def test_optimize_apply_exception_returns_500(client_admin, monkeypatch):
    add_response = client_admin.post('/api/plan-my-night/targets', json=_sample_target())
    assert add_response.status_code == 200
    preview = client_admin.get('/api/plan-my-night/optimize')
    preview_payload = preview.get_json()

    def _boom(*a, **kw):
        raise RuntimeError('boom')

    monkeypatch.setattr(plan_my_night_bp_module.plan_my_night, 'apply_optimized_schedule', _boom)

    response = client_admin.post('/api/plan-my-night/optimize/apply', json={
        'order': preview_payload['order'],
        'start_delay_minutes': preview_payload['start_delay_minutes'],
    })
    assert response.status_code == 500
