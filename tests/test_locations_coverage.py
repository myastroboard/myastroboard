"""
Multi-location profiles (v1.2) - gap coverage.

Complements test_locations.py: targets the remaining uncovered arcs found by
the coverage report (defensive branches, error handlers, edge inputs) so the
v1.2 modules reach full line coverage.
"""

import json
import os
import sys
import time
import types
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend'))

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

import app as _app_mod
from blueprints import locations as _locations_mod
from blueprints import weather as _weather_mod
from cache import cache_store
from utils.repo_config import (
    _ensure_locations,
    get_active_location,
    get_install_default_location,
    get_location_by_id,
    get_locations_for_user,
    get_scheduler_locations,
    get_user_location_prefs,
    new_location_preset,
)


class _FakeUser:
    def __init__(self, preferences=None, admin=False):
        self.preferences = preferences or {}
        self._admin = admin
        self.user_id = str(uuid.uuid4())
        self.username = 'fake'

    def is_admin(self):
        return self._admin


# client_admin comes from tests/conftest.py (real admin user id in session)


# ---------------------------------------------------------------------------
# repo_config edge arcs
# ---------------------------------------------------------------------------


class TestRepoConfigEdgeArcs:
    def test_new_location_preset_non_dict_base_keeps_defaults(self):
        preset = new_location_preset(base='not-a-dict')
        assert preset['name'] == 'Paris'
        assert preset['id']

    def test_ensure_locations_drops_non_dict_entries(self):
        config = {
            'locations': ['junk', {'name': 'Real', 'latitude': 1, 'longitude': 2,
                                   'timezone': 'UTC', 'is_install_default': True}],
        }
        changed = _ensure_locations(config)
        assert changed is True
        assert all(isinstance(p, dict) for p in config['locations'])
        assert len(config['locations']) == 1

    def test_ensure_locations_attaches_orphan_horizon_to_existing_default(self):
        # Already-migrated presets + a leftover global horizon (e.g. config
        # written by an older intermediate build) -> attach to install default.
        config = {
            'locations': [
                {'id': 'a', 'name': 'A', 'latitude': 1, 'longitude': 2, 'timezone': 'UTC',
                 'horizon_profile': [], 'is_install_default': False},
                {'id': 'b', 'name': 'B', 'latitude': 3, 'longitude': 4, 'timezone': 'UTC',
                 'horizon_profile': [], 'is_install_default': True},
            ],
            'skytonight': {'constraints': {'horizon_profile': [{'az': 0, 'alt': 12}]}},
        }
        changed = _ensure_locations(config)
        assert changed is True
        assert config['locations'][1]['horizon_profile'] == [{'az': 0, 'alt': 12}]
        assert 'horizon_profile' not in config['skytonight']['constraints']

    def test_ensure_locations_attaches_orphan_horizon_to_first_without_flag(self):
        # No preset flagged install default: horizon goes to the first preset,
        # and the flag invariant promotes that same first preset afterwards.
        config = {
            'locations': [
                {'id': 'a', 'name': 'A', 'latitude': 1, 'longitude': 2, 'timezone': 'UTC',
                 'horizon_profile': []},
            ],
            'skytonight': {'constraints': {'horizon_profile': [{'az': 90, 'alt': 8}]}},
        }
        _ensure_locations(config)
        assert config['locations'][0]['horizon_profile'] == [{'az': 90, 'alt': 8}]
        assert config['locations'][0]['is_install_default'] is True

    def test_get_location_by_id_none_and_unknown(self):
        config = {'locations': [{'id': 'x', 'name': 'X'}]}
        assert get_location_by_id(config, None) is None
        assert get_location_by_id(config, 'ghost') is None

    def test_install_default_falls_back_to_first_when_unflagged(self):
        config = {'locations': [{'id': 'x', 'name': 'X'}, {'id': 'y', 'name': 'Y'}]}
        assert get_install_default_location(config)['id'] == 'x'

    def test_user_prefs_non_dict_location_block_normalized(self):
        user = _FakeUser(preferences={'location': 'garbage'})
        prefs = get_user_location_prefs(user)
        assert prefs['attributed_location_ids'] == []
        assert prefs['default_location_id'] is None

    def test_get_locations_for_user_empty_config(self):
        assert get_locations_for_user({}, _FakeUser()) == []

    def test_get_locations_for_user_without_attribution_gets_install_default(self):
        config = {
            'locations': [
                {'id': 'a', 'name': 'A', 'is_install_default': True},
                {'id': 'b', 'name': 'B', 'is_install_default': False},
            ]
        }
        accessible = get_locations_for_user(config, _FakeUser())
        assert [loc['id'] for loc in accessible] == ['a']

    def test_scheduler_locations_includes_active_and_default_pointers(self, monkeypatch):
        from utils import auth as auth_module

        config = {
            'locations': [
                {'id': 'a', 'name': 'A', 'is_install_default': True},
                {'id': 'b', 'name': 'B', 'is_install_default': False},
                {'id': 'c', 'name': 'C', 'is_install_default': False},
                {'id': 'd', 'name': 'D', 'is_install_default': False},
            ]
        }
        user = _FakeUser(preferences={'location': {
            'attributed_location_ids': [],
            'active_location_id': 'b',
            'default_location_id': 'c',
            'order': [],
        }})
        stub_manager = types.SimpleNamespace(users={user.user_id: user})
        monkeypatch.setattr(auth_module, 'user_manager', stub_manager)

        ids = {loc['id'] for loc in get_scheduler_locations(config)}
        assert ids == {'a', 'b', 'c'}  # install default + active + default; 'd' unused

    def test_active_location_no_config_returns_default_location(self):
        location = get_active_location({}, None)
        assert location['name'] == 'Paris'


# ---------------------------------------------------------------------------
# cache_store edge arcs
# ---------------------------------------------------------------------------


class TestCacheStoreEdgeArcs:
    def test_sync_all_from_shared_full_matrix(self, monkeypatch):
        loc = str(uuid.uuid4())
        # Future timestamp so a concurrent background refresh (app import starts
        # cache threads) can never look "newer" and clobber the assertion window.
        now = time.time() + 3600
        shared = {
            'spaceflight_launches': {'timestamp': now, 'data': {'launches': [1]}},
            'iers': 'not-a-dict',  # global entry with junk shape -> skipped
            f'sun_report:{loc}': {'timestamp': now, 'data': {'sun': 1}},
            f'sun_report:{loc}-older': {'timestamp': 0, 'data': None},  # data None -> skipped
            f'unknown_cache:{loc}': {'timestamp': now, 'data': {'x': 1}},  # unknown name -> skipped
            'plainkey': {'timestamp': now, 'data': {'y': 1}},  # no colon -> skipped
            f'moon_report:{loc}': 'junk-entry',  # keyed entry non-dict -> skipped
        }
        # Bypass the shared file: background cache threads do read-modify-write
        # cycles on it and could clobber seeded entries mid-test. The matrix
        # under test is the sync loop, which reads via _read_shared_cache().
        monkeypatch.setattr(cache_store, '_read_shared_cache', lambda: json.loads(json.dumps(shared)))

        cache_store._sync_all_from_shared()
        assert cache_store._spaceflight_launches_cache['data'] == {'launches': [1]}
        assert cache_store.get_location_cache_entry('sun_report', loc)['data'] == {'sun': 1}

    def test_sync_keyed_entry_older_than_memory_not_applied(self, tmp_path, monkeypatch):
        loc = str(uuid.uuid4())
        entry = cache_store.get_location_cache_entry('sun_report', loc)
        entry['data'] = {'fresh': True}
        entry['timestamp'] = time.time() + 3600

        shared = {f'sun_report:{loc}': {'timestamp': 1.0, 'data': {'stale': True}}}
        cache_file = tmp_path / 'older.json'
        cache_file.write_text(json.dumps(shared), encoding='utf-8')
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'older.lock'))

        cache_store._sync_all_from_shared()
        assert entry['data'] == {'fresh': True}

    def test_is_astronomical_cache_ready_true_when_all_valid(self, tmp_path, monkeypatch):
        loc = str(uuid.uuid4())
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'ready.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'ready.lock'))
        now = time.time()
        for name in cache_store._READINESS_LOCATION_CACHES:
            entry = cache_store.get_location_cache_entry(name, loc)
            entry['data'] = {'ok': True}
            entry['timestamp'] = now
        for global_entry in (
            cache_store._spaceflight_launches_cache,
            cache_store._spaceflight_astronauts_cache,
            cache_store._spaceflight_events_cache,
        ):
            global_entry['data'] = {'ok': True}
            global_entry['timestamp'] = now

        assert cache_store.is_astronomical_cache_ready([loc]) is True

    def test_is_astronomical_cache_ready_false_when_spaceflight_stale(self, tmp_path, monkeypatch):
        loc = str(uuid.uuid4())
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'notready.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'notready.lock'))
        now = time.time()
        for name in cache_store._READINESS_LOCATION_CACHES:
            entry = cache_store.get_location_cache_entry(name, loc)
            entry['data'] = {'ok': True}
            entry['timestamp'] = now
        cache_store._spaceflight_launches_cache['data'] = None
        cache_store._spaceflight_launches_cache['timestamp'] = 0

        assert cache_store.is_astronomical_cache_ready([loc]) is False

    def test_is_astronomical_cache_ready_false_without_locations(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'noloc.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'noloc.lock'))
        assert cache_store.is_astronomical_cache_ready([]) is False

    def test_get_cache_init_status_without_locations(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'status.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'status.lock'))
        status = cache_store.get_cache_init_status(location_ids=[])
        assert status['all_ready'] is False
        assert status['locations'] == {}
        assert status['sun_report'] is False  # primary_id None -> every slot False

    def test_remove_location_signature_unknown_id_is_noop(self):
        saves = []
        original = cache_store._save_location_signatures
        cache_store._save_location_signatures = lambda: saves.append(1)
        try:
            cache_store.remove_location_signature('ghost-' + uuid.uuid4().hex)
        finally:
            cache_store._save_location_signatures = original
        assert saves == []

    def test_load_location_signatures_corrupt_file_ignored(self, tmp_path, monkeypatch):
        bad = tmp_path / 'location_cache.json'
        bad.write_text('{corrupt json', encoding='utf-8')
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(bad))
        cache_store._load_location_signatures()  # must not raise

    def test_execution_metrics_missing_last_run_at(self, monkeypatch):
        monkeypatch.setattr(cache_store, 'get_cache_metrics', lambda: {'jobx': {'last_success': True}})
        assert cache_store._is_execution_metrics_valid('jobx', 60) is False


# ---------------------------------------------------------------------------
# auth location-pref edge arcs
# ---------------------------------------------------------------------------


class TestAuthLocationEdgeArcs:
    @pytest.fixture
    def manager(self, tmp_path, monkeypatch):
        from utils import auth as auth_module

        users_file = str(tmp_path / 'users.json')
        monkeypatch.setattr(auth_module, 'USERS_FILE', users_file)
        manager = auth_module.UserManager()
        return manager

    def test_validate_location_id_key_non_string_rejected(self, manager):
        ok, msg = manager.validate_user_preferences({'location': {'default_location_id': 123}})
        assert ok is False
        assert 'default_location_id' in msg

    def test_validate_location_non_dict_rejected(self, manager):
        ok, msg = manager.validate_user_preferences({'location': 'junk'})
        assert ok is False

    def test_validate_location_list_key_non_list_rejected(self, manager):
        ok, msg = manager.validate_user_preferences({'location': {'order': 'not-a-list'}})
        assert ok is False

    def test_prefs_block_non_dict_location_normalized(self, manager):
        user = manager.create_user(f'edge_{uuid.uuid4().hex[:8]}', 'password123', 'user')
        user.preferences['location'] = 'garbage'
        block = manager._get_location_prefs_block(user)
        assert block['attributed_location_ids'] == []

    def test_set_location_prefs_unknown_user_raises(self, manager):
        with pytest.raises(ValueError, match='User not found'):
            manager.set_user_location_prefs('ghost-user', active_location_id='x')

    def test_set_location_prefs_invalid_value_raises(self, manager):
        user = manager.create_user(f'edge_{uuid.uuid4().hex[:8]}', 'password123', 'user')
        with pytest.raises(ValueError):
            manager.set_user_location_prefs(user.user_id, attributed_location_ids=[123])

    def test_reset_active_location_unknown_user_is_noop(self, manager):
        manager.reset_active_location_on_login('ghost-user')  # must not raise

    def test_attribution_noop_when_already_consistent(self, manager):
        user = manager.create_user(f'edge_{uuid.uuid4().hex[:8]}', 'password123', 'user')
        manager.set_location_attribution('loc-1', [user.user_id])
        # Second identical call: user already holds loc-1 -> no state change
        manager.set_location_attribution('loc-1', [user.user_id])
        prefs = get_user_location_prefs(manager.get_user_by_id(user.user_id))
        assert prefs['attributed_location_ids'].count('loc-1') == 1


# ---------------------------------------------------------------------------
# push_scheduler / astrodex / plan_my_night helper edge arcs
# ---------------------------------------------------------------------------


class TestHelperEdgeArcs:
    def test_push_with_location_interpolates_for_multi(self, monkeypatch):
        from utils import push_scheduler

        captured = {}

        def fake_t(user, key, **kwargs):
            captured['key'] = key
            captured['kwargs'] = kwargs
            return f"{kwargs['body']} at {kwargs['location_name']}"

        monkeypatch.setattr(push_scheduler, '_t', fake_t)
        user = _FakeUser()
        result = push_scheduler._with_location(user, 'Darkness begins', 'Dark Site', True)
        assert result == 'Darkness begins at Dark Site'
        assert captured['key'] == 'push_location_suffix'

    def test_push_with_location_multi_but_no_name(self):
        from utils import push_scheduler

        user = _FakeUser()
        assert push_scheduler._with_location(user, 'Body', None, True) == 'Body'

    def test_astrodex_count_skips_non_astrodex_and_corrupt_files(self, tmp_path, monkeypatch):
        """Location lives on pictures, not items (v1.2) - count_pictures_for_location
        walks each item's pictures list, tolerating junk items/pictures."""
        from observation import astrodex as astrodex_module

        monkeypatch.setattr(astrodex_module, 'ASTRODEX_DIR', str(tmp_path))
        (tmp_path / 'notes.txt').write_text('not astrodex', encoding='utf-8')
        (tmp_path / 'u1_astrodex.json').write_text('{corrupt', encoding='utf-8')
        (tmp_path / 'u2_astrodex.json').write_text(
            json.dumps({'items': [
                {'pictures': [{'location_id': 'L1'}, 'junk-picture']},
                'junk-item',
                {'pictures': [{'location_id': 'other'}]},
                {'pictures': [{'location_id': 'L1'}]},
            ]}),
            encoding='utf-8',
        )
        assert astrodex_module.count_pictures_for_location('L1') == 2

    def test_plan_helpers_skip_junk_and_handle_errors(self, tmp_path, monkeypatch):
        from observation import plan_my_night

        monkeypatch.setattr(plan_my_night, 'PLAN_DIR', str(tmp_path))

        # Skipped: backups, tmp, corrupted-marker, non-json
        (tmp_path / 'a.json.backup').write_text('{}', encoding='utf-8')
        (tmp_path / 'b.corrupted.json').write_text('{}', encoding='utf-8')
        (tmp_path / 'c.tmp').write_text('{}', encoding='utf-8')
        (tmp_path / 'readme.txt').write_text('x', encoding='utf-8')
        # Unreadable plan file -> _plan_references_location returns False
        (tmp_path / 'u1.json').write_text('{corrupt', encoding='utf-8')
        # Non-dict payload
        (tmp_path / 'u2.json').write_text('[1, 2]', encoding='utf-8')
        # Real pinned plan
        (tmp_path / 'u3.json').write_text(
            json.dumps({'plan': {'location_id': 'L9', 'targets': []}}), encoding='utf-8'
        )

        assert plan_my_night.count_plans_for_location('') == 0
        assert plan_my_night.delete_plans_for_location('') == 0
        assert plan_my_night.count_plans_for_location('L9') == 1

        # os.remove failure is logged, not raised
        monkeypatch.setattr(plan_my_night.os, 'remove',
                            lambda *_a: (_ for _ in ()).throw(OSError('locked')))
        assert plan_my_night.delete_plans_for_location('L9') == 0


# ---------------------------------------------------------------------------
# /api/locations* error handlers + validation edges
# ---------------------------------------------------------------------------


class TestLocationsApiErrorArcs:
    def _raise(self, *_a, **_k):
        raise RuntimeError('boom')

    def test_all_route_exception_handlers_return_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_locations_mod, 'load_config', self._raise)
        assert client_admin.get('/api/locations').status_code == 500
        assert client_admin.post('/api/locations', json={}).status_code == 500
        assert client_admin.put('/api/locations/x', json={}).status_code == 500
        assert client_admin.delete('/api/locations/x').status_code == 500
        assert client_admin.get('/api/locations/x/references').status_code == 500
        assert client_admin.post('/api/locations/x/attribute', json={'user_ids': []}).status_code == 500
        assert client_admin.get('/api/locations/mine').status_code == 500
        assert client_admin.post('/api/locations/active', json={'location_id': 'x'}).status_code == 500

    def test_validate_payload_edges(self):
        validate = _locations_mod._validate_location_payload
        assert validate('junk')[1] is not None                      # non-dict payload
        assert validate({'name': 'X', 'latitude': None, 'longitude': 2,
                         'elevation': 0, 'timezone': 'UTC'})[1] is not None  # lat not a number
        assert validate({'name': 'X', 'latitude': 1, 'longitude': 2,
                         'elevation': 'high', 'timezone': 'UTC'})[1] is not None  # bad elevation
        assert validate({'name': 'X', 'latitude': 1, 'longitude': 2,
                         'elevation': None, 'timezone': 'UTC'})[1] is not None  # elevation explicitly None
        cleaned, err = validate({'bortle': None, 'sqm': None}, partial=True)
        assert err is None and cleaned == {'bortle': None, 'sqm': None}  # explicit nulls kept
        cleaned, err = validate({'horizon_profile': None}, partial=True)
        assert err is None and cleaned['horizon_profile'] == []     # None horizon -> []
        assert validate({'horizon_profile': 'flat'}, partial=True)[1] is not None  # non-list horizon

    def test_put_unknown_location_returns_404(self, client_admin):
        resp = client_admin.put('/api/locations/ghost-id', json={'name': 'X'})
        assert resp.status_code == 404

    def test_put_invalid_payload_returns_400(self, client_admin):
        listed = client_admin.get('/api/locations').get_json()
        loc_id = listed['locations'][0]['id']
        resp = client_admin.put(f'/api/locations/{loc_id}', json={'latitude': 'north'})
        assert resp.status_code == 400

    def test_references_unknown_location_returns_404(self, client_admin):
        assert client_admin.get('/api/locations/ghost/references').status_code == 404

    def test_delete_unknown_location_returns_404(self, client_admin):
        assert client_admin.delete('/api/locations/ghost').status_code == 404

    def test_delete_invalid_plans_mode_returns_400(self, client_admin):
        resp = client_admin.post('/api/locations', json={
            'name': 'Del Mode', 'latitude': 1, 'longitude': 2, 'elevation': 0, 'timezone': 'UTC',
        })
        loc_id = resp.get_json()['location']['id']
        try:
            bad = client_admin.delete(f'/api/locations/{loc_id}?plans=maybe')
            assert bad.status_code == 400
        finally:
            client_admin.delete(f'/api/locations/{loc_id}')

    def test_attribute_unknown_location_returns_404(self, client_admin):
        resp = client_admin.post('/api/locations/ghost/attribute', json={'user_ids': []})
        assert resp.status_code == 404

    def test_attribute_non_list_user_ids_returns_400(self, client_admin):
        listed = client_admin.get('/api/locations').get_json()
        loc_id = listed['locations'][0]['id']
        resp = client_admin.post(f'/api/locations/{loc_id}/attribute', json={'user_ids': 'all'})
        assert resp.status_code == 400

    def test_set_active_non_string_location_id_returns_400(self, client_admin):
        resp = client_admin.post('/api/locations/active', json={'location_id': 123})
        assert resp.status_code == 400

    def test_login_survives_location_reset_failure(self, monkeypatch):
        """A failing active-location reset must never block a login (warning only)."""
        from app import app as flask_app
        from utils.auth import user_manager

        username = f'loginedge_{uuid.uuid4().hex[:8]}'
        user = user_manager.create_user(username, 'password123', 'user')
        monkeypatch.setattr(user_manager, 'reset_active_location_on_login', self._raise)

        flask_app.config['TESTING'] = True
        try:
            client = flask_app.test_client()
            resp = client.post('/api/auth/login', json={'username': username, 'password': 'password123'})
            assert resp.status_code == 200
        finally:
            try:
                user_manager.delete_user(user.user_id)
            except Exception:
                pass

    def test_moon_calendar_warm_cache_and_computed_paths(self, client_admin, monkeypatch):
        from utils.repo_config import load_config

        loc_id = get_install_default_location(load_config()).get('id')

        # Warm per-location slot -> served directly
        monkeypatch.setitem(
            _weather_mod._moon_calendar_cache, loc_id,
            {'timestamp': time.time(), 'data': {'nights': [{'date': '2030-01-01'}]}},
        )
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code == 200
        assert resp.get_json()['nights'][0]['date'] == '2030-01-01'

        # Cold slot -> computed via MoonPlanner (stubbed) and cached
        monkeypatch.setitem(_weather_mod._moon_calendar_cache, loc_id, {'timestamp': 0, 'data': None})

        class _StubPlanner:
            def __init__(self, *_a, **_k):
                pass

            def next_n_nights(self, n):
                return [
                    {
                        'date': f'2030-01-{i + 1:02d}',
                        'moon': {'illumination_percent': 42.0},
                        'dark_hours': {'strict': 6.5},
                        'astrophoto_score': 0.8,
                    }
                    for i in range(n)
                ]

        monkeypatch.setattr(_app_mod.moon_planner, 'MoonPlanner', _StubPlanner)
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code == 200
        assert len(resp.get_json()['nights']) == 30


class TestCachedLocationScore:
    """_cached_location_score: best-effort sky-widget switcher score, never a live fetch."""

    def test_returns_none_when_no_forecast_cached(self, monkeypatch):
        monkeypatch.setattr(cache_store, 'load_location_cache', lambda name, loc_id: {'data': None})
        assert _locations_mod._cached_location_score('loc-cold') is None

    def test_returns_none_when_hourly_list_empty(self, monkeypatch):
        monkeypatch.setattr(cache_store, 'load_location_cache', lambda name, loc_id: {'data': {'hourly': []}})
        assert _locations_mod._cached_location_score('loc-empty') is None

    def test_returns_none_when_condition_missing(self, monkeypatch):
        monkeypatch.setattr(
            cache_store, 'load_location_cache',
            lambda name, loc_id: {'data': {'hourly': [{'temperature_2m': 12.0}]}},
        )
        assert _locations_mod._cached_location_score('loc-nocond') is None

    def test_converts_condition_to_0_10_scale(self, monkeypatch):
        monkeypatch.setattr(
            cache_store, 'load_location_cache',
            lambda name, loc_id: {'data': {'hourly': [{'condition': 87.3}]}},
        )
        assert _locations_mod._cached_location_score('loc-warm') == pytest.approx(8.7)

    def test_returns_none_on_unexpected_exception(self, monkeypatch):
        def _raise(name, loc_id):
            raise RuntimeError('cache file corrupt')

        monkeypatch.setattr(cache_store, 'load_location_cache', _raise)
        assert _locations_mod._cached_location_score('loc-boom') is None


class TestSkyTonightPerLocationBranchGaps:
    """Targeted arcs for the per-location SkyTonight refactor's helper functions."""

    def test_any_location_missing_results_exception_falls_back_to_default_check(self, monkeypatch):
        from skytonight import skytonight_scheduler as sched_mod

        def _raise(config):
            raise RuntimeError('config unavailable')

        # The function does `from utils.repo_config import get_scheduler_locations` lazily
        # inside its try block, which re-reads repo_config's current attribute at
        # call time - patch it there to force the except arc.
        from utils import repo_config as _repo_config_mod

        monkeypatch.setattr(_repo_config_mod, 'get_scheduler_locations', _raise)
        monkeypatch.setattr(sched_mod, 'has_calculation_results', lambda *_a, **_k: True)

        assert sched_mod._any_location_missing_results({}) is False

    def test_compute_target_debug_uses_explicit_location_without_fallback(self, monkeypatch):
        """Line 1731 false branch: a valid location dict is passed directly and
        must NOT be replaced by the install-default fallback lookup."""
        from skytonight import skytonight_calculator as calc_mod

        install_default_calls = []
        monkeypatch.setattr(
            calc_mod, 'load_targets_dataset',
            lambda: {'targets': []},
        )
        explicit_location = {
            'id': 'explicit-loc', 'latitude': 10.0, 'longitude': 20.0,
            'elevation': 5.0, 'timezone': 'UTC', 'horizon_profile': [],
        }

        def _track_install_default(config):
            install_default_calls.append(config)
            return {'latitude': 0.0, 'longitude': 0.0, 'timezone': 'UTC'}

        from utils import repo_config as _repo_config_mod2
        monkeypatch.setattr(_repo_config_mod2, 'get_install_default_location', _track_install_default)

        result = calc_mod.compute_target_debug(
            'ZZZ_NoSuch', config={'skytonight': {'constraints': {}}}, location=explicit_location,
        )

        assert result.get('found') is False
        assert install_default_calls == []  # the explicit location was used, not the fallback
