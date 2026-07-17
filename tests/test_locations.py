"""
Multi-location profiles (v1.2) tests.

Covers:
- config migration (legacy singular location -> locations[] + horizon move)
- the get_active_location() resolver fallback chain and attribution rules
- per-location cache slots, per-preset invalidation and legacy key migration
- UserManager location preference helpers (attribution, cleanup, login reset)
- the /api/locations* admin CRUD + attribution + switcher endpoints
"""

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend'))

import cache_store
import repo_config
from repo_config import (
    _ensure_locations,
    get_active_location,
    get_all_locations,
    get_install_default_location,
    get_locations_for_user,
    get_scheduler_locations,
    new_location_preset,
)
from config_defaults import DEFAULT_LOCATION


class _FakeUser:
    """Duck-typed stand-in for auth.User (resolver only needs these two members)."""

    def __init__(self, preferences=None, admin=False):
        self.preferences = preferences or {}
        self._admin = admin
        self.user_id = str(uuid.uuid4())
        self.username = 'fake'

    def is_admin(self):
        return self._admin


def _make_config(n_locations=1):
    config = {'locations': [], 'skytonight': {'constraints': {}}}
    for i in range(n_locations):
        preset = new_location_preset(
            base={
                'name': f'Site {i}',
                'latitude': 40.0 + i,
                'longitude': 2.0 + i,
                'elevation': 100 + i,
                'timezone': 'Europe/Paris',
            },
            is_install_default=(i == 0),
        )
        config['locations'].append(preset)
    return config


# ---------------------------------------------------------------------------
# Migration (_ensure_locations)
# ---------------------------------------------------------------------------


class TestEnsureLocationsMigration:
    def test_legacy_location_becomes_install_default_preset(self):
        config = {
            'location': {
                'name': 'Lyon',
                'latitude': 45.75,
                'longitude': 4.85,
                'elevation': 200,
                'timezone': 'Europe/Paris',
                'bortle': 6,
                'sqm': None,
            }
        }
        changed = _ensure_locations(config)
        assert changed is True
        assert 'location' not in config
        locations = config['locations']
        assert len(locations) == 1
        preset = locations[0]
        assert preset['name'] == 'Lyon'
        assert preset['is_install_default'] is True
        assert preset['bortle'] == 6
        assert preset['id']

    def test_legacy_horizon_profile_moves_onto_preset(self):
        config = {
            'location': dict(DEFAULT_LOCATION),
            'skytonight': {'constraints': {'altitude_constraint_min': 25, 'horizon_profile': [{'az': 0, 'alt': 12}]}},
        }
        _ensure_locations(config)
        assert config['locations'][0]['horizon_profile'] == [{'az': 0, 'alt': 12}]
        assert 'horizon_profile' not in config['skytonight']['constraints']
        assert config['skytonight']['constraints']['altitude_constraint_min'] == 25

    def test_brand_new_install_seeds_default_location(self):
        config = {}
        _ensure_locations(config)
        assert len(config['locations']) == 1
        assert config['locations'][0]['name'] == DEFAULT_LOCATION['name']
        assert config['locations'][0]['is_install_default'] is True

    def test_exactly_one_install_default_enforced(self):
        config = _make_config(3)
        config['locations'][1]['is_install_default'] = True  # two defaults
        changed = _ensure_locations(config)
        assert changed is True
        defaults = [p for p in config['locations'] if p['is_install_default']]
        assert len(defaults) == 1

    def test_no_default_promotes_first(self):
        config = _make_config(2)
        for preset in config['locations']:
            preset['is_install_default'] = False
        _ensure_locations(config)
        assert config['locations'][0]['is_install_default'] is True

    def test_idempotent_when_already_migrated(self):
        config = _make_config(2)
        assert _ensure_locations(config) is False

    def test_backfills_missing_ids(self):
        config = {'locations': [{'name': 'X', 'latitude': 1, 'longitude': 2, 'timezone': 'UTC'}]}
        _ensure_locations(config)
        assert config['locations'][0]['id']
        assert config['locations'][0]['is_install_default'] is True

    def test_migration_attributes_location_to_existing_users(self, monkeypatch):
        """A real pre-v1.2 install had exactly one location every user
        implicitly used - migrating it must attribute it to everyone that
        already exists, not leave them all suddenly unattributed."""
        import auth as auth_module

        calls = []

        class _FakeManager:
            users = {'u1': object(), 'u2': object()}

            def set_location_attribution(self, location_id, user_ids):
                calls.append((location_id, sorted(user_ids)))

        monkeypatch.setattr(auth_module, 'user_manager', _FakeManager())

        config = {'location': dict(DEFAULT_LOCATION)}
        _ensure_locations(config)

        assert len(calls) == 1
        location_id, user_ids = calls[0]
        assert location_id == config['locations'][0]['id']
        assert user_ids == ['u1', 'u2']

    def test_brand_new_install_also_attributes_to_existing_users(self, monkeypatch):
        """No prior `location` key at all - still attribute explicitly to
        whoever exists (typically just the bootstrap admin). Don't rely on
        admin-bypass alone: that only covers reads, not every future
        consumer of attribution data."""
        import auth as auth_module

        calls = []

        class _FakeManager:
            users = {'u1': object()}

            def set_location_attribution(self, location_id, user_ids):
                calls.append((location_id, user_ids))

        monkeypatch.setattr(auth_module, 'user_manager', _FakeManager())

        config = {}
        _ensure_locations(config)

        assert calls == [(config['locations'][0]['id'], ['u1'])]

    def test_migration_succeeds_even_if_attribution_fails(self, monkeypatch):
        """Best-effort: the migration itself (config.json) must not be lost
        just because attributing it to users.json failed for some reason."""
        import auth as auth_module

        class _FailingManager:
            users = {'u1': object()}

            def set_location_attribution(self, location_id, user_ids):
                raise RuntimeError('boom')

        monkeypatch.setattr(auth_module, 'user_manager', _FailingManager())

        config = {'location': dict(DEFAULT_LOCATION)}
        changed = _ensure_locations(config)

        assert changed is True
        assert len(config['locations']) == 1


# ---------------------------------------------------------------------------
# Resolver (get_active_location) + helpers
# ---------------------------------------------------------------------------


class TestActiveLocationResolver:
    def test_no_user_returns_install_default(self):
        config = _make_config(3)
        assert get_active_location(config, None)['id'] == config['locations'][0]['id']

    def test_empty_config_returns_default_location(self):
        location = get_active_location({'locations': []}, None)
        assert location['name'] == DEFAULT_LOCATION['name']

    def test_user_without_attribution_falls_back_to_install_default(self):
        config = _make_config(3)
        user = _FakeUser(preferences={'location': {'attributed_location_ids': []}})
        assert get_active_location(config, user)['id'] == config['locations'][0]['id']

    def test_active_id_wins_when_attributed(self):
        config = _make_config(3)
        target = config['locations'][2]['id']
        user = _FakeUser(
            preferences={
                'location': {
                    'attributed_location_ids': [config['locations'][1]['id'], target],
                    'active_location_id': target,
                }
            }
        )
        assert get_active_location(config, user)['id'] == target

    def test_active_id_ignored_when_not_attributed(self):
        config = _make_config(3)
        stranger = config['locations'][2]['id']
        mine = config['locations'][1]['id']
        user = _FakeUser(
            preferences={
                'location': {
                    'attributed_location_ids': [mine],
                    'active_location_id': stranger,  # not attributed -> ignored
                    'default_location_id': mine,
                }
            }
        )
        assert get_active_location(config, user)['id'] == mine

    def test_default_id_used_when_no_active(self):
        config = _make_config(3)
        mine = config['locations'][1]['id']
        user = _FakeUser(
            preferences={'location': {'attributed_location_ids': [mine], 'default_location_id': mine}}
        )
        assert get_active_location(config, user)['id'] == mine

    def test_dangling_ids_are_ignored(self):
        config = _make_config(2)
        user = _FakeUser(
            preferences={
                'location': {
                    'attributed_location_ids': ['deleted-id', config['locations'][1]['id']],
                    'active_location_id': 'deleted-id',
                    'default_location_id': 'deleted-id',
                }
            }
        )
        # deleted ids never resolve; falls to first attributed that exists
        assert get_active_location(config, user)['id'] == config['locations'][1]['id']

    def test_admin_bypasses_attribution(self):
        config = _make_config(3)
        target = config['locations'][2]['id']
        admin = _FakeUser(
            preferences={'location': {'attributed_location_ids': [], 'active_location_id': target}}, admin=True
        )
        assert get_active_location(config, admin)['id'] == target

    def test_get_locations_for_user_orders_by_preference(self):
        config = _make_config(3)
        ids = [p['id'] for p in config['locations']]
        user = _FakeUser(
            preferences={
                'location': {'attributed_location_ids': [ids[0], ids[2]], 'order': [ids[2], ids[0]]}
            }
        )
        result = [p['id'] for p in get_locations_for_user(config, user)]
        assert result == [ids[2], ids[0]]

    def test_get_locations_for_admin_returns_all(self):
        config = _make_config(3)
        admin = _FakeUser(admin=True)
        assert len(get_locations_for_user(config, admin)) == 3

    def test_install_default_helper(self):
        config = _make_config(3)
        config['locations'][1]['is_install_default'] = True
        config['locations'][0]['is_install_default'] = False
        assert get_install_default_location(config)['id'] == config['locations'][1]['id']

    def test_scheduler_locations_bounded(self, monkeypatch):
        config = _make_config(4)
        ids = [p['id'] for p in config['locations']]

        class _FakeManager:
            users = {
                'u1': _FakeUser(preferences={'location': {'attributed_location_ids': [ids[1]]}}),
                'u2': _FakeUser(preferences={'location': {'active_location_id': ids[2]}}),
            }

        import auth as auth_module

        monkeypatch.setattr(auth_module, 'user_manager', _FakeManager())
        scheduled = {p['id'] for p in get_scheduler_locations(config)}
        # install default + attributed + someone's active; NOT the unused ids[3]
        assert scheduled == {ids[0], ids[1], ids[2]}

    def test_scheduler_locations_admin_sees_every_preset(self, monkeypatch):
        """An admin bypasses attribution (like get_active_location) - even a
        preset nobody has ever selected must stay scheduler-tracked, so its
        metrics don't sit permanently stale just because no one is using it
        as their active location right now."""
        config = _make_config(4)
        ids = [p['id'] for p in config['locations']]

        class _FakeManager:
            users = {
                'admin': _FakeUser(admin=True),
                'u1': _FakeUser(preferences={'location': {'attributed_location_ids': [ids[1]]}}),
            }

        import auth as auth_module

        monkeypatch.setattr(auth_module, 'user_manager', _FakeManager())
        scheduled = {p['id'] for p in get_scheduler_locations(config)}
        assert scheduled == set(ids)


# ---------------------------------------------------------------------------
# Per-location cache slots (cache_store)
# ---------------------------------------------------------------------------


class TestLocationScopedCaches:
    def test_roundtrip_update_and_load(self):
        loc_id = str(uuid.uuid4())
        cache_store.update_location_cache('sun_report', loc_id, {'x': 1})
        entry = cache_store.load_location_cache('sun_report', loc_id)
        assert entry['data'] == {'x': 1}
        assert cache_store.is_cache_valid(entry, 3600)

    def test_unknown_cache_name_raises(self):
        with pytest.raises(KeyError):
            cache_store.get_location_cache_entry('nope', 'x')

    def test_reset_caches_for_location_is_isolated(self):
        loc_a, loc_b = str(uuid.uuid4()), str(uuid.uuid4())
        cache_store.update_location_cache('moon_report', loc_a, {'a': 1})
        cache_store.update_location_cache('moon_report', loc_b, {'b': 2})

        cache_store.reset_caches_for_location(loc_a)

        entry_a = cache_store.load_location_cache('moon_report', loc_a)
        entry_b = cache_store.load_location_cache('moon_report', loc_b)
        assert entry_a['data'] is None
        assert entry_b['data'] == {'b': 2}

    def test_drop_location_caches_removes_slots_and_signature(self):
        loc_id = str(uuid.uuid4())
        cache_store.update_location_cache('aurora', loc_id, {'kp': 3})
        cache_store.update_location_config({'id': loc_id, 'latitude': 1, 'longitude': 2, 'elevation': 3, 'timezone': 'UTC'})

        cache_store.drop_location_caches(loc_id)

        assert loc_id not in cache_store._location_caches['aurora']
        entry = cache_store.load_shared_cache_entry(cache_store.location_cache_key('aurora', loc_id))
        assert entry is None
        assert loc_id not in cache_store._last_known_location_signatures

    def test_migrate_legacy_cache_keys(self):
        loc_id = str(uuid.uuid4())
        # Simulate a pre-v1.2 plain key in the shared file
        cache_store.update_shared_cache_entry('horizon_graph', {'legacy': True}, 123.0)

        migrated = cache_store.migrate_legacy_cache_keys(loc_id)

        assert migrated >= 1
        assert cache_store.load_shared_cache_entry('horizon_graph') is None
        keyed = cache_store.load_shared_cache_entry(cache_store.location_cache_key('horizon_graph', loc_id))
        assert keyed is not None and keyed['data'] == {'legacy': True}

    def test_signature_change_detection_per_preset(self):
        preset = {'id': str(uuid.uuid4()), 'latitude': 45.0, 'longitude': 3.0, 'elevation': 10, 'timezone': 'UTC'}
        assert cache_store.has_location_changed(preset) is True  # never tracked
        cache_store.update_location_config(preset)
        assert cache_store.has_location_changed(preset) is False
        assert cache_store.is_location_tracked(preset) is True

        moved = dict(preset, latitude=46.0)
        assert cache_store.has_location_changed(moved) is True

        # Another preset's tracking is independent
        other = {'id': str(uuid.uuid4()), 'latitude': 1.0, 'longitude': 1.0, 'elevation': 0, 'timezone': 'UTC'}
        assert cache_store.has_location_changed(other) is True

    def test_legacy_flat_signature_slot_still_works(self):
        flat = {'latitude': 45.0, 'longitude': 3.0, 'elevation': 10, 'timezone': 'UTC'}
        cache_store.update_location_config(flat)
        assert cache_store.has_location_changed(flat) is False
        assert cache_store.pop_legacy_location_signature() is not None
        assert cache_store.pop_legacy_location_signature() is None


# ---------------------------------------------------------------------------
# UserManager location preference helpers
# ---------------------------------------------------------------------------


class TestUserManagerLocationPrefs:
    @pytest.fixture
    def manager(self):
        from auth import user_manager

        user_manager._reload_users_if_changed()
        return user_manager

    @pytest.fixture
    def temp_user(self, manager):
        username = f'locuser_{uuid.uuid4().hex[:8]}'
        user = manager.create_user(username, 'password123', 'user')
        yield user
        try:
            manager.delete_user(user.user_id)
        except Exception:
            pass

    def test_set_user_location_prefs(self, manager, temp_user):
        block = manager.set_user_location_prefs(temp_user.user_id, default_location_id='loc-1')
        assert block['default_location_id'] == 'loc-1'
        stored = manager.get_user_by_id(temp_user.user_id).preferences['location']
        assert stored['default_location_id'] == 'loc-1'

    def test_set_user_location_prefs_unknown_key_rejected(self, manager, temp_user):
        with pytest.raises(ValueError):
            manager.set_user_location_prefs(temp_user.user_id, nope=True)

    def test_attribution_add_and_remove(self, manager, temp_user):
        manager.set_location_attribution('loc-A', [temp_user.user_id])
        prefs = manager.get_user_by_id(temp_user.user_id).preferences['location']
        assert 'loc-A' in prefs['attributed_location_ids']

        manager.set_location_attribution('loc-A', [])
        prefs = manager.get_user_by_id(temp_user.user_id).preferences['location']
        assert 'loc-A' not in prefs['attributed_location_ids']

    def test_cleanup_location_references(self, manager, temp_user):
        manager.set_location_attribution('loc-B', [temp_user.user_id])
        manager.set_user_location_prefs(
            temp_user.user_id, default_location_id='loc-B', active_location_id='loc-B', order=['loc-B']
        )

        manager.cleanup_location_references('loc-B', 'loc-default')

        prefs = manager.get_user_by_id(temp_user.user_id).preferences['location']
        assert 'loc-B' not in prefs['attributed_location_ids']
        assert prefs['default_location_id'] == 'loc-default'
        assert prefs['active_location_id'] == 'loc-default'
        assert 'loc-B' not in prefs['order']

    def test_reset_active_location_on_login(self, manager, temp_user):
        manager.set_user_location_prefs(
            temp_user.user_id, default_location_id='loc-home', active_location_id='loc-away'
        )
        manager.reset_active_location_on_login(temp_user.user_id)
        prefs = manager.get_user_by_id(temp_user.user_id).preferences['location']
        assert prefs['active_location_id'] == 'loc-home'

    def test_location_prefs_validation(self, manager):
        ok, _ = manager.validate_user_preferences({'location': {'attributed_location_ids': ['a'], 'order': []}})
        assert ok
        bad, msg = manager.validate_user_preferences({'location': {'attributed_location_ids': [1]}})
        assert not bad and 'attributed_location_ids' in msg
        bad2, msg2 = manager.validate_user_preferences({'location': 'nope'})
        assert not bad2 and 'location' in msg2


# ---------------------------------------------------------------------------
# API endpoints (/api/locations*)
# ---------------------------------------------------------------------------


class TestLocationsAPI:
    def _payload(self, name='API Site'):
        return {
            'name': name,
            'latitude': 43.6,
            'longitude': 1.44,
            'elevation': 150,
            'timezone': 'Europe/Paris',
            'bortle': 5,
        }

    def test_list_requires_admin(self, client_user):
        assert client_user.get('/api/locations').status_code == 403

    def test_crud_cycle(self, client_admin):
        # Create
        resp = client_admin.post('/api/locations', json=self._payload('CRUD Site'))
        assert resp.status_code == 201, resp.get_json()
        created = resp.get_json()['location']
        loc_id = created['id']
        assert created['is_install_default'] is False

        try:
            # List
            listed = client_admin.get('/api/locations').get_json()
            assert any(loc['id'] == loc_id for loc in listed['locations'])
            assert listed['max_locations'] >= 1

            # Update
            upd = client_admin.put(f'/api/locations/{loc_id}', json={'name': 'Renamed Site', 'bortle': 3})
            assert upd.status_code == 200
            assert upd.get_json()['location']['name'] == 'Renamed Site'
            # Renaming must not rotate the id
            assert upd.get_json()['location']['id'] == loc_id

            # Coordinate change resets that preset's caches (cache_reset flag)
            upd2 = client_admin.put(f'/api/locations/{loc_id}', json={'latitude': 44.0})
            assert upd2.status_code == 200
            assert upd2.get_json()['cache_reset'] is True

            # References check
            refs = client_admin.get(f'/api/locations/{loc_id}/references').get_json()
            assert refs['location_id'] == loc_id
            assert refs['is_install_default'] is False
        finally:
            # Delete
            deleted = client_admin.delete(f'/api/locations/{loc_id}')
            assert deleted.status_code == 200

        listed_after = client_admin.get('/api/locations').get_json()
        assert not any(loc['id'] == loc_id for loc in listed_after['locations'])

    def test_create_location_attributes_to_existing_users(self, client_admin):
        """New locations are attributed to everyone by default - an admin can
        manually exclude specific users afterward, rather than having to
        attribute each location by hand (e.g. an astro club with 100+ users)."""
        from auth import user_manager

        other_user = user_manager.create_user(f'loc_attr_{uuid.uuid4().hex[:8]}', 'password123', 'user')
        try:
            expected_total = len(user_manager.users)
            resp = client_admin.post('/api/locations', json=self._payload('Attribution Site'))
            assert resp.status_code == 201, resp.get_json()
            created = resp.get_json()['location']
            loc_id = created['id']
            # total_users lets the admin UI show "N attributed, M excluded"
            # instead of naming every user.
            assert created['total_users'] == expected_total
            assert len(created['attributed_to']) == expected_total

            try:
                refreshed = user_manager.get_user_by_id(other_user.user_id)
                assert loc_id in refreshed.preferences['location']['attributed_location_ids']
            finally:
                client_admin.delete(f'/api/locations/{loc_id}')
        finally:
            user_manager.delete_user(other_user.user_id)

    def test_delete_orphan_mode_skips_plan_cascade(self, client_admin, monkeypatch):
        """?plans=orphan must report 0 deleted plans and never call the
        cascade-delete helper (the default 'cascade' mode is covered by
        test_crud_cycle's plain DELETE above)."""
        resp = client_admin.post('/api/locations', json=self._payload('Orphan Site'))
        assert resp.status_code == 201
        loc_id = resp.get_json()['location']['id']

        cascade_calls = []
        monkeypatch.setattr(
            'plan_my_night.delete_plans_for_location',
            lambda location_id: cascade_calls.append(location_id) or 0,
        )

        deleted = client_admin.delete(f'/api/locations/{loc_id}?plans=orphan')
        assert deleted.status_code == 200
        body = deleted.get_json()
        assert body['plans_mode'] == 'orphan'
        assert body['deleted_plans'] == 0
        assert cascade_calls == []

    def test_create_validates_payload(self, client_admin):
        bad = client_admin.post('/api/locations', json={'name': '', 'latitude': 1, 'longitude': 2, 'timezone': 'UTC'})
        assert bad.status_code == 400
        bad_tz = client_admin.post(
            '/api/locations',
            json={'name': 'X', 'latitude': 1, 'longitude': 2, 'elevation': 0, 'timezone': 'Not/AZone'},
        )
        assert bad_tz.status_code == 400
        bad_lat = client_admin.post(
            '/api/locations',
            json={'name': 'X', 'latitude': 120, 'longitude': 2, 'elevation': 0, 'timezone': 'UTC'},
        )
        assert bad_lat.status_code == 400

    def test_max_locations_enforced(self, client_admin):
        from constants import MAX_LOCATIONS

        created = []
        try:
            while True:
                listed = client_admin.get('/api/locations').get_json()
                if len(listed['locations']) >= MAX_LOCATIONS:
                    break
                resp = client_admin.post('/api/locations', json=self._payload(f'Fill {uuid.uuid4().hex[:6]}'))
                assert resp.status_code == 201
                created.append(resp.get_json()['location']['id'])

            over = client_admin.post('/api/locations', json=self._payload('One Too Many'))
            assert over.status_code == 400
            assert over.get_json().get('error_key') == 'locations.max_reached'
        finally:
            for loc_id in created:
                client_admin.delete(f'/api/locations/{loc_id}')

    def test_cannot_delete_install_default(self, client_admin):
        listed = client_admin.get('/api/locations').get_json()
        default = next(loc for loc in listed['locations'] if loc['is_install_default'])
        resp = client_admin.delete(f"/api/locations/{default['id']}")
        assert resp.status_code == 400
        assert resp.get_json().get('error_key') == 'locations.cannot_delete_default'

    def test_promote_install_default_is_atomic(self, client_admin):
        resp = client_admin.post('/api/locations', json=self._payload('Promotable'))
        assert resp.status_code == 201
        loc_id = resp.get_json()['location']['id']
        listed = client_admin.get('/api/locations').get_json()
        old_default = next(loc for loc in listed['locations'] if loc['is_install_default'])

        try:
            promoted = client_admin.put(f'/api/locations/{loc_id}', json={'is_install_default': True})
            assert promoted.status_code == 200

            listed = client_admin.get('/api/locations').get_json()
            defaults = [loc for loc in listed['locations'] if loc['is_install_default']]
            assert len(defaults) == 1 and defaults[0]['id'] == loc_id
        finally:
            # Restore the previous default, then clean up
            client_admin.put(f"/api/locations/{old_default['id']}", json={'is_install_default': True})
            client_admin.delete(f'/api/locations/{loc_id}')

    def test_attribute_and_mine_and_active(self, client_admin):
        from auth import user_manager

        username = f'apiuser_{uuid.uuid4().hex[:8]}'
        user = user_manager.create_user(username, 'password123', 'user')
        resp = client_admin.post('/api/locations', json=self._payload('Attributed Site'))
        loc_id = resp.get_json()['location']['id']
        # A dedicated second preset, not the shared install default - new
        # locations attribute to everyone by default now, so exercising the
        # "rejected" path needs a preset this user was explicitly excluded
        # from (an admin's deliberate choice), and mutating the install
        # default's attribution here would leak into every other test.
        other_resp = client_admin.post('/api/locations', json=self._payload('Other Site'))
        other_id = other_resp.get_json()['location']['id']

        try:
            attr = client_admin.post(f'/api/locations/{loc_id}/attribute', json={'user_ids': [user.user_id]})
            assert attr.status_code == 200
            assert any(u['user_id'] == user.user_id for u in attr.get_json()['location']['attributed_to'])

            # Log in as that user through a session-faked client.
            # NOTE: no `with` block - nesting a second context-managed test
            # client inside the client_admin fixture corrupts Flask's request
            # context stack at teardown.
            from app import app as flask_app

            flask_app.config['TESTING'] = True
            user_client = flask_app.test_client()
            with user_client.session_transaction() as sess:
                sess['user_id'] = user.user_id
                sess['username'] = user.username
                sess['role'] = user.role

            mine = user_client.get('/api/locations/mine').get_json()
            mine_ids = {loc['id'] for loc in mine['locations']}
            assert loc_id in mine_ids

            # Switch active to the attributed preset
            switched = user_client.post('/api/locations/active', json={'location_id': loc_id})
            assert switched.status_code == 200
            assert switched.get_json()['active_location_id'] == loc_id

            # Non-attributed preset is rejected - explicitly exclude this user
            # first, since it's attributed to everyone by default.
            excl = client_admin.post(f'/api/locations/{other_id}/attribute', json={'user_ids': []})
            assert excl.status_code == 200
            rejected = user_client.post('/api/locations/active', json={'location_id': other_id})
            assert rejected.status_code == 403
        finally:
            client_admin.delete(f'/api/locations/{loc_id}')
            client_admin.delete(f'/api/locations/{other_id}')
            try:
                user_manager.delete_user(user.user_id)
            except Exception:
                pass

    def test_attribute_unknown_user_rejected(self, client_admin):
        listed = client_admin.get('/api/locations').get_json()
        loc_id = listed['locations'][0]['id']
        resp = client_admin.post(f'/api/locations/{loc_id}/attribute', json={'user_ids': ['ghost-user']})
        assert resp.status_code == 400

    def test_config_shim_exposes_active_location(self, client_admin):
        config = client_admin.get('/api/config').get_json()
        assert 'location' in config
        assert config['location'].get('id')
        assert 'locations' in config

    def test_legacy_config_post_updates_install_default(self, client_admin):
        listed = client_admin.get('/api/locations').get_json()
        default = next(loc for loc in listed['locations'] if loc['is_install_default'])
        original_name = default['name']

        resp = client_admin.post('/api/config', json={'location': {'name': 'Wizard Site'}})
        assert resp.status_code == 200

        try:
            listed = client_admin.get('/api/locations').get_json()
            renamed = next(loc for loc in listed['locations'] if loc['id'] == default['id'])
            assert renamed['name'] == 'Wizard Site'
        finally:
            client_admin.post('/api/config', json={'location': {'name': original_name}})


# ---------------------------------------------------------------------------
# Plan My Night / Astrodex location tagging helpers
# ---------------------------------------------------------------------------


class TestLocationTaggingHelpers:
    def test_plan_pinned_location_and_cascade_delete(self, temp_dir, monkeypatch):
        import plan_my_night

        monkeypatch.setattr(plan_my_night, 'PLAN_DIR', temp_dir)
        user_id = str(uuid.uuid4())
        loc_id = str(uuid.uuid4())

        success, reason, payload, entry = plan_my_night.create_or_add_target(
            user_id=user_id,
            username='tagger',
            item_data={'name': 'M31'},
            catalogue='Messier',
            night_start='2030-01-01T18:00:00+00:00',
            night_end='2030-01-02T06:00:00+00:00',
            duration_hours=12.0,
            location_id=loc_id,
            location_name='Tag Site',
        )
        assert success, reason
        assert payload['plan']['location_id'] == loc_id
        assert payload['plan']['location_name'] == 'Tag Site'

        assert plan_my_night.count_plans_for_location(loc_id) == 1
        assert plan_my_night.count_plans_for_location('other') == 0
        assert plan_my_night.delete_plans_for_location(loc_id) == 1
        assert plan_my_night.count_plans_for_location(loc_id) == 0

    def test_astrodex_picture_location_snapshot(self, temp_dir, monkeypatch):
        """Location lives on pictures, not items (v1.2) - the same object can
        be re-photographed from different sites across sessions, so an item
        itself never carries a single frozen location."""
        import astrodex as astrodex_module

        monkeypatch.setattr(astrodex_module, 'ASTRODEX_DIR', temp_dir)
        monkeypatch.setattr(astrodex_module, 'ASTRODEX_IMAGES_DIR', os.path.join(temp_dir, 'images'))
        user_id = str(uuid.uuid4())
        loc_id = str(uuid.uuid4())

        item = astrodex_module.create_astrodex_item(
            user_id, {'name': 'NGC 7000', 'catalogue': 'OpenNGC'}, 'tagger',
        )
        assert item is not None
        assert 'location_id' not in item
        assert 'location_name' not in item

        picture = astrodex_module.add_picture_to_item(
            user_id, item['id'], {'filename': 'ngc7000.jpg', 'location_id': loc_id, 'location_name': 'Snap Site'},
        )
        assert picture is not None
        assert picture['location_id'] == loc_id
        assert picture['location_name'] == 'Snap Site'

        assert astrodex_module.count_pictures_for_location(loc_id) == 1
        assert astrodex_module.count_pictures_for_location('other') == 0


# ---------------------------------------------------------------------------
# load_config end-to-end migration (file-backed)
# ---------------------------------------------------------------------------


class TestLoadConfigMigration:
    def test_load_config_migrates_and_persists_once(self, temp_dir, monkeypatch):
        config_file = os.path.join(temp_dir, 'config.json')
        monkeypatch.setattr(repo_config, 'CONFIG_FILE', config_file)

        legacy = {
            'location': {
                'name': 'Old Town',
                'latitude': 47.2,
                'longitude': -1.55,
                'elevation': 20,
                'timezone': 'Europe/Paris',
                'bortle': None,
                'sqm': 21.2,
            },
            'skytonight': {'enabled': True, 'constraints': {'horizon_profile': [{'az': 90, 'alt': 20}]}},
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(legacy, f)

        config = repo_config.load_config()
        assert 'location' not in config
        assert config['locations'][0]['name'] == 'Old Town'
        assert config['locations'][0]['sqm'] == 21.2
        assert config['locations'][0]['horizon_profile'] == [{'az': 90, 'alt': 20}]
        first_id = config['locations'][0]['id']

        # Persisted: a second load returns the same id without re-migrating
        config2 = repo_config.load_config()
        assert config2['locations'][0]['id'] == first_id

        # The on-disk file no longer carries the legacy key
        with open(config_file, 'r', encoding='utf-8') as f:
            on_disk = json.load(f)
        assert 'location' not in on_disk
        assert on_disk['locations'][0]['id'] == first_id
