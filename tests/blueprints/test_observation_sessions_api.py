"""API tests for the Observation Log blueprint (/api/observation-sessions/*)."""

import io
import os
import sys
import tempfile
import types
import uuid

import pytest

from equipment import equipment_profiles
from observation import astrodex
from observation import observation_sessions
from utils.auth import user_manager

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from blueprints import observation_sessions as observation_sessions_bp_module

_TELESCOPE_DATA = {
    'name': 'Test Refractor',
    'telescope_type': 'Refractor',
    'aperture_mm': 100,
    'focal_length_mm': 800,
}


@pytest.fixture
def isolated_storage(monkeypatch):
    """Point both Observation Log and Astrodex storage at temporary directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(
            observation_sessions, 'OBSERVATION_SESSIONS_DIR', os.path.join(tmpdir, 'observation_sessions')
        )
        monkeypatch.setattr(astrodex, 'ASTRODEX_DIR', os.path.join(tmpdir, 'astrodex'))
        monkeypatch.setattr(astrodex, 'ASTRODEX_IMAGES_DIR', os.path.join(tmpdir, 'astrodex', 'images'))
        yield tmpdir


@pytest.fixture
def client(isolated_storage):
    """Admin-authenticated test client with isolated storage."""
    app.config['TESTING'] = True
    with app.test_client() as test_client:
        user = user_manager.get_user_by_username('admin')
        assert user is not None
        with test_client.session_transaction() as session:
            session['user_id'] = user.user_id
            session['username'] = user.username
            session['role'] = user.role
        yield test_client


@pytest.fixture
def admin_user_id():
    user = user_manager.get_user_by_username('admin')
    assert user is not None
    return user.user_id


def _create_session(client, **overrides):
    payload = {'date': '2026-07-14'}
    payload.update(overrides)
    response = client.post('/api/observation-sessions', json=payload)
    assert response.status_code == 201
    return response.get_json()['data']


def _add_entry(client, session_id, **overrides):
    payload = {'name': 'M31', 'catalogue': 'Messier'}
    payload.update(overrides)
    return client.post(f'/api/observation-sessions/{session_id}/entries', json=payload)


class TestAuth:
    """Authentication and role gating."""

    def test_routes_require_login(self):
        """Every route rejects an unauthenticated caller."""
        app.config['TESTING'] = True
        with app.test_client() as anonymous:
            assert anonymous.get('/api/observation-sessions').status_code == 401
            assert anonymous.post('/api/observation-sessions', json={'date': '2026-01-01'}).status_code == 401
            response = anonymous.delete('/api/observation-sessions/x')
            assert response.status_code == 401

    def test_mutations_require_user_role(self, isolated_storage):
        """A read-only account can list sessions but not create them."""
        app.config['TESTING'] = True
        username = f'ro_{uuid.uuid4().hex[:8]}'
        user_manager.create_user(username, 'test123', 'read-only')

        with app.test_client() as read_only:
            with read_only.session_transaction() as session:
                session['username'] = username
                session['role'] = 'read-only'

            assert read_only.get('/api/observation-sessions').status_code == 200
            assert read_only.post('/api/observation-sessions', json={'date': '2026-01-01'}).status_code == 403


class TestSessionRoutes:
    """CRUD over sessions."""

    def test_list_empty(self, client):
        """An empty log still returns the envelope with zeroed stats."""
        payload = client.get('/api/observation-sessions').get_json()
        assert payload['sessions'] == []
        assert payload['stats']['total_sessions'] == 0

    def test_create_and_list(self, client):
        """A created session appears in the list, newest date first."""
        _create_session(client, date='2026-01-05')
        _create_session(client, date='2026-03-20')

        payload = client.get('/api/observation-sessions').get_json()
        dates = [session['nights'][0]['date'] for session in payload['sessions']]
        assert dates == ['2026-03-20', '2026-01-05']
        assert payload['stats']['total_sessions'] == 2

    def test_create_requires_date(self, client):
        """A session without a date is a 400."""
        response = client.post('/api/observation-sessions', json={'notes': 'undated'})
        assert response.status_code == 400
        assert 'date' in response.get_json()['error']

    def test_get_single_session(self, client):
        """A single session is returned as a bare object; unknown ids are 404."""
        session = _create_session(client)
        response = client.get(f"/api/observation-sessions/{session['id']}")
        assert response.status_code == 200
        assert response.get_json()['id'] == session['id']
        assert client.get('/api/observation-sessions/missing').status_code == 404

    def test_update_session(self, client):
        """Session ("trip") level fields are updatable through PUT."""
        session = _create_session(client)
        response = client.put(f"/api/observation-sessions/{session['id']}", json={'notes': 'clear'})
        assert response.status_code == 200
        data = response.get_json()['data']
        assert data['notes'] == 'clear'

    def test_update_night(self, client):
        """A night's conditions are updatable through its own PUT route."""
        session = _create_session(client)
        night_id = session['nights'][0]['id']
        response = client.put(
            f"/api/observation-sessions/{session['id']}/nights/{night_id}",
            json={'seeing': 2, 'transparency': 7},
        )
        assert response.status_code == 200
        data = response.get_json()['data']
        assert data['seeing'] == 2
        assert data['transparency'] == 7

    def test_update_unknown_night(self, client):
        session = _create_session(client)
        assert (
            client.put(f"/api/observation-sessions/{session['id']}/nights/missing", json={'notes': 'x'}).status_code
            == 404
        )
        assert client.put('/api/observation-sessions/missing/nights/missing', json={'notes': 'x'}).status_code == 404

    def test_add_night(self, client):
        """A second night can be added, and shows up on the session's detail view."""
        session = _create_session(client, date='2026-07-14')
        response = client.post(f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'})
        assert response.status_code == 201
        night = response.get_json()['data']
        assert night['date'] == '2026-07-15'

        stored = client.get(f"/api/observation-sessions/{session['id']}").get_json()
        assert [n['date'] for n in stored['nights']] == ['2026-07-14', '2026-07-15']

    def test_add_night_requires_date(self, client):
        session = _create_session(client)
        response = client.post(f"/api/observation-sessions/{session['id']}/nights", json={})
        assert response.status_code == 400

    def test_add_night_unknown_session(self, client):
        assert client.post('/api/observation-sessions/missing/nights', json={'date': '2026-07-15'}).status_code == 404

    def test_delete_night(self, client):
        session = _create_session(client, date='2026-07-14')
        added = client.post(
            f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'}
        ).get_json()['data']

        response = client.delete(f"/api/observation-sessions/{session['id']}/nights/{added['id']}")
        assert response.status_code == 200

        stored = client.get(f"/api/observation-sessions/{session['id']}").get_json()
        assert len(stored['nights']) == 1

    def test_delete_last_remaining_night_is_refused(self, client):
        session = _create_session(client)
        night_id = session['nights'][0]['id']
        response = client.delete(f"/api/observation-sessions/{session['id']}/nights/{night_id}")
        assert response.status_code == 400

    def test_delete_night_with_entries_is_refused(self, client):
        session = _create_session(client, date='2026-07-14')
        added = client.post(
            f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'}
        ).get_json()['data']
        _add_entry(client, session['id'], night_id=added['id'])

        response = client.delete(f"/api/observation-sessions/{session['id']}/nights/{added['id']}")
        assert response.status_code == 400

    def test_delete_unknown_night(self, client):
        session = _create_session(client)
        response = client.delete(f"/api/observation-sessions/{session['id']}/nights/missing")
        assert response.status_code == 404

    def test_delete_night_unknown_session(self, client):
        """Deleting a night from a session that doesn't exist at all is a 404, distinct
        from an unknown night on a real session."""
        response = client.delete('/api/observation-sessions/missing/nights/missing')
        assert response.status_code == 404

    def test_add_night_prefills_sqm_from_the_sessions_own_location(self, client, monkeypatch):
        """A second night inherits the session's fixed location preset SQM, the same way
        the first one does at creation."""
        preset = {
            'id': 'preset-2',
            'name': 'Dark Site',
            'latitude': 44.0,
            'longitude': 5.0,
            'elevation': 900,
            'sqm': 21.4,
        }
        monkeypatch.setattr(observation_sessions_bp_module, 'load_config', lambda: {'locations': [preset]})
        monkeypatch.setattr(observation_sessions_bp_module, 'get_locations_for_user', lambda config, user: [preset])
        monkeypatch.setattr(observation_sessions_bp_module, 'get_location_by_id', lambda config, location_id: preset)

        session = _create_session(client, date='2026-07-14', location_id='preset-2')
        response = client.post(f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'})
        assert response.status_code == 201
        assert response.get_json()['data']['sqm'] == pytest.approx(21.4)

    def test_update_unknown_session(self, client):
        """Updating an unknown session is a 404."""
        assert client.put('/api/observation-sessions/missing', json={'notes': 'x'}).status_code == 404

    def test_delete_session(self, client):
        """Deleting removes the session; deleting again is a 404."""
        session = _create_session(client)
        url = f"/api/observation-sessions/{session['id']}"
        first = client.delete(url)
        assert first.status_code == 200
        second = client.delete(url)
        assert second.status_code == 404

    def test_sessions_are_private_to_their_owner(self, client, admin_user_id):
        """Another user's session is invisible, not just unlisted."""
        other_user = str(uuid.uuid4())
        other_session = observation_sessions.create_session(other_user, 'other', {'date': '2026-05-05'})

        assert client.get('/api/observation-sessions').get_json()['sessions'] == []
        assert client.get(f"/api/observation-sessions/{other_session['id']}").status_code == 404


class TestSessionResolution:
    """Server-side resolution of location and combination references."""

    def test_unknown_combination_is_dropped(self, client):
        """A combination the user has no access to never lands on the session."""
        session = _create_session(client, combination_id='not-a-real-combination')
        assert session['combination_id'] is None
        assert session['combination_name'] is None

    def test_custom_location_label(self, client):
        """A free-text 'somewhere else' label is kept with its typed coordinates."""
        session = _create_session(
            client,
            location_name='Col du Galibier',
            location_latitude=45.06,
            location_longitude=6.4,
        )
        assert session['location_id'] is None
        assert session['location_name'] == 'Col du Galibier'
        assert session['location_latitude'] == pytest.approx(45.06)

    def test_unknown_location_id_without_label_clears_location(self, client):
        """An unresolvable preset id with no fallback label resolves to no location."""
        session = _create_session(client, location_id='nope')
        assert session['location_id'] is None
        assert session['location_name'] is None

    def test_location_untouched_when_update_omits_it(self, client):
        """Editing an unrelated field must not disturb an existing location snapshot."""
        session = _create_session(client, location_name='Backyard')
        updated = client.put(f"/api/observation-sessions/{session['id']}", json={'notes': 'x'}).get_json()['data']
        assert updated['location_name'] == 'Backyard'

    def test_sqm_prefilled_from_location_preset(self, client, monkeypatch):
        """A new session inherits the chosen preset's configured SQM when none is given."""
        preset = {
            'id': 'preset-1',
            'name': 'Dark Site',
            'latitude': 44.0,
            'longitude': 5.0,
            'elevation': 900,
            'sqm': 21.6,
        }
        monkeypatch.setattr(observation_sessions_bp_module, 'load_config', lambda: {'locations': [preset]})
        monkeypatch.setattr(observation_sessions_bp_module, 'get_locations_for_user', lambda config, user: [preset])
        monkeypatch.setattr(observation_sessions_bp_module, 'get_location_by_id', lambda config, location_id: preset)

        session = _create_session(client, location_id='preset-1')
        assert session['location_name'] == 'Dark Site'
        assert session['nights'][0]['sqm'] == pytest.approx(21.6)

    def test_moon_illumination_is_computed_on_create(self, client):
        """Unlike seeing/transparency (a same-day-only forecast), moon illumination is a
        pure ephemeris computation and is always filled in, including for past dates."""
        session = _create_session(client, date='2020-01-15')
        night = session['nights'][0]
        assert night['moon_illumination_percent'] is not None
        assert 0 <= night['moon_illumination_percent'] <= 100

    def test_moon_illumination_is_recomputed_when_a_night_date_changes(self, client):
        session = _create_session(client, date='2020-01-15')
        night_id = session['nights'][0]['id']
        original = session['nights'][0]['moon_illumination_percent']

        updated = client.put(
            f"/api/observation-sessions/{session['id']}/nights/{night_id}", json={'date': '2020-06-15'}
        ).get_json()['data']
        # Different date -> (almost certainly) a different illumination reading, and
        # never left null now that a real date is set.
        assert updated['moon_illumination_percent'] is not None
        assert updated['date'] == '2020-06-15'
        assert original is not None

    def test_custom_location_with_unparseable_coordinate_is_dropped(self, client):
        """A latitude/longitude that isn't a number is silently dropped, not a 400 -
        same low-stakes trust level as any other free-text field."""
        session = _create_session(
            client, location_name='Somewhere', location_latitude='not-a-number', location_longitude=6.4
        )
        assert session['location_latitude'] is None
        assert session['location_longitude'] == pytest.approx(6.4)

    def test_custom_location_with_out_of_range_coordinate_is_dropped(self, client):
        """A latitude outside [-90, 90] is silently dropped."""
        session = _create_session(client, location_name='Somewhere', location_latitude=999)
        assert session['location_latitude'] is None

    def test_owned_combination_id_is_resolved_with_name(self, client):
        """A combination the user owns resolves and its display name is attached."""
        scope = client.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        combo = client.post(
            '/api/equipment/combinations', json={'name': 'My Combo', 'telescope_id': scope['id']}
        ).get_json()['data']

        session = _create_session(client, combination_id=combo['id'])
        assert session['combination_id'] == combo['id']
        assert session['combination_name'] == 'My Combo'

    def test_shared_combination_id_is_resolved_with_name(self, client):
        """A combination shared by another user (via its constituent equipment) resolves
        through the shared-combinations lookup rather than the direct-ownership one."""
        owner_id = f'shared-owner-{uuid.uuid4().hex[:8]}'
        scope = equipment_profiles.create_telescope(owner_id, {**_TELESCOPE_DATA, 'is_shared': True})
        combo = equipment_profiles.create_combination(owner_id, {'name': 'Shared Combo', 'telescope_id': scope['id']})

        session = _create_session(client, combination_id=combo['id'])
        assert session['combination_id'] == combo['id']
        assert session['combination_name'] == 'Shared Combo'

    def test_falsy_combination_id_key_resolves_to_none(self, client):
        """An explicit empty combination_id (as opposed to the key being absent) still
        resolves to no combination without doing any lookup."""
        session = _create_session(client, combination_id='')
        assert session['combination_id'] is None
        assert session['combination_name'] is None

    def test_location_id_race_falls_through_to_no_location(self, client, monkeypatch):
        """If a location preset disappears between the accessibility check and the
        lookup itself (a narrow race), the session falls back to no location rather
        than raising."""
        preset = {'id': 'preset-race', 'name': 'Vanishing Site', 'latitude': 44.0, 'longitude': 5.0}
        monkeypatch.setattr(observation_sessions_bp_module, 'get_locations_for_user', lambda config, user: [preset])
        monkeypatch.setattr(observation_sessions_bp_module, 'get_location_by_id', lambda config, location_id: None)

        session = _create_session(client, location_id='preset-race')
        assert session['location_id'] is None
        assert session['location_name'] is None


class TestPrivateHelpersDirect:
    """Direct tests for small private helpers that are hard to reach end-to-end through
    the API (edge cases the routes structurally can't produce)."""

    def test_location_preset_sqm_without_location_id(self):
        assert observation_sessions_bp_module._location_preset_sqm(None) is None
        assert observation_sessions_bp_module._location_preset_sqm('') is None

    def test_location_preset_sqm_unknown_location(self, monkeypatch):
        monkeypatch.setattr(observation_sessions_bp_module, 'get_location_by_id', lambda config, location_id: None)
        assert observation_sessions_bp_module._location_preset_sqm('missing') is None

    def test_ensure_astrodex_item_for_entry_requires_a_name(self):
        assert (
            observation_sessions_bp_module._ensure_astrodex_item_for_entry(
                types.SimpleNamespace(user_id='u1', username='tester'), {'name': ''}
            )
            is None
        )

    def test_auto_link_returns_entry_unchanged_when_item_cannot_be_resolved(self):
        entry = {'id': 'e1', 'name': '', 'frame_count': 5}
        result = observation_sessions_bp_module._auto_link_astrodex_item(
            types.SimpleNamespace(user_id='u1', username='tester'), 's1', entry
        )
        assert result is entry
        assert entry.get('astrodex_item_id') is None

    def test_collect_image_paths_skips_non_dict_and_idless_entries(self):
        user = types.SimpleNamespace(user_id='u1', username='tester')
        sessions = [{'entries': [123, {'id': None}, {'notdict': True}]}]
        assert observation_sessions_bp_module._collect_image_paths(user, sessions) == {}

    def test_resolve_entry_image_path_item_not_found(self, monkeypatch):
        """The linked Astrodex item can vanish (deleted independently of the entry) -
        image resolution degrades to 'no photo' rather than raising."""
        monkeypatch.setattr(observation_sessions_bp_module.astrodex, 'get_astrodex_item', lambda *a, **k: None)
        user = types.SimpleNamespace(user_id='u1', username='tester')
        entry = {'astrodex_item_id': 'missing-item', 'astrodex_picture_id': 'pic-1'}
        assert observation_sessions_bp_module._resolve_entry_image_path(user, entry) is None

    def test_resolve_entry_image_path_picture_without_filename(self, monkeypatch):
        fake_item = {'pictures': [{'id': 'pic-1', 'filename': ''}]}
        monkeypatch.setattr(observation_sessions_bp_module.astrodex, 'get_astrodex_item', lambda *a, **k: fake_item)
        user = types.SimpleNamespace(user_id='u1', username='tester')
        entry = {'astrodex_item_id': 'item-1', 'astrodex_picture_id': 'pic-1'}
        assert observation_sessions_bp_module._resolve_entry_image_path(user, entry) is None

    def test_moon_illumination_blank_date_is_none(self):
        assert observation_sessions_bp_module._compute_moon_illumination_for_date('') is None
        assert observation_sessions_bp_module._compute_moon_illumination_for_date(None) is None

    def test_moon_illumination_unparseable_date_is_none(self):
        """A date that doesn't match the expected format degrades to no reading rather
        than raising - the caller (add/update night) never validates this field itself."""
        assert observation_sessions_bp_module._compute_moon_illumination_for_date('not-a-date') is None

    def test_attachment_download_name_keeps_display_name_that_already_has_the_extension(self):
        attachment = {'original_name': 'photo.jpg', 'display_name': 'My Photo.jpg'}
        assert observation_sessions_bp_module._attachment_download_name(attachment) == 'My Photo.jpg'

    def test_attachment_download_name_keeps_display_name_when_original_has_no_extension(self):
        attachment = {'original_name': 'README', 'display_name': 'Notes'}
        assert observation_sessions_bp_module._attachment_download_name(attachment) == 'Notes'

    def test_session_overlaps_date_range_skips_non_dict_nights(self):
        """A corrupt (non-dict) night entry surviving in storage is skipped rather than
        crashing the PDF date-range filter."""
        session = {'nights': [None, {'date': '2026-06-01'}]}
        assert observation_sessions_bp_module._session_overlaps_date_range(session, None, None) is True


class TestEntryRoutes:
    """CRUD over per-target entries."""

    def test_add_entry(self, client):
        """An entry is created with its frozen target snapshot."""
        session = _create_session(client)
        response = _add_entry(client, session['id'], type='Galaxy', constellation='Andromeda')
        assert response.status_code == 201
        entry = response.get_json()['data']
        assert entry['name'] == 'M31'
        assert entry['type'] == 'Galaxy'

    def test_add_entry_requires_name(self, client):
        """An entry without a target name is a 400."""
        session = _create_session(client)
        response = client.post(f"/api/observation-sessions/{session['id']}/entries", json={'frame_count': 5})
        assert response.status_code == 400

    def test_add_entry_unknown_session(self, client):
        """Adding to an unknown session is a 404."""
        assert _add_entry(client, 'missing').status_code == 404

    def test_add_entry_unknown_night_id_is_400(self, client):
        """A night_id that doesn't belong to the session is rejected before the write."""
        session = _create_session(client)
        response = _add_entry(client, session['id'], night_id='not-a-real-night')
        assert response.status_code == 400

    def test_add_entry_returns_404_when_storage_write_silently_fails(self, client, monkeypatch):
        """A storage-layer write failure despite an existing session (a narrow race) is
        reported the same as the session being gone, matching the create-session
        convention above."""
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'add_entry', lambda *a, **k: None)
        response = _add_entry(client, session['id'])
        assert response.status_code == 404

    def test_rating_validation(self, client):
        """A rating outside 0-5 or off the 0.5 grid is rejected with a 400."""
        session = _create_session(client)
        assert _add_entry(client, session['id'], rating=7).status_code == 400
        assert _add_entry(client, session['id'], rating=3.3).status_code == 400
        assert _add_entry(client, session['id'], rating='abc').status_code == 400
        assert _add_entry(client, session['id'], rating=3.5).status_code == 201

    def test_update_entry(self, client):
        """Actual-capture fields are updatable; a bad rating is still a 400."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']

        response = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}",
            json={'frame_count': 42, 'integration_minutes': 84, 'notes': 'good'},
        )
        assert response.status_code == 200
        assert response.get_json()['data']['frame_count'] == 42

        bad = client.put(f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'rating': 9})
        assert bad.status_code == 400

    def test_update_entry_with_a_valid_night_id_moves_it(self, client):
        """A night_id on the update payload that does belong to the session passes
        validation and the entry is moved onto that night."""
        session = _create_session(client, date='2026-07-14')
        second_night = client.post(
            f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'}
        ).get_json()['data']
        entry = _add_entry(client, session['id']).get_json()['data']

        response = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}",
            json={'night_id': second_night['id']},
        )
        assert response.status_code == 200
        assert response.get_json()['data']['night_id'] == second_night['id']

    def test_update_entry_with_valid_rating(self, client):
        """A valid rating override on PUT goes through the same validation as add, then
        proceeds to the update itself."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.put(f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'rating': 4.0})
        assert response.status_code == 200
        assert response.get_json()['data']['rating'] == pytest.approx(4.0)

    def test_update_unknown_entry(self, client):
        """Updating an unknown entry is a 404."""
        session = _create_session(client)
        assert (
            client.put(f"/api/observation-sessions/{session['id']}/entries/missing", json={'notes': 'x'}).status_code
            == 404
        )

    def test_update_entry_unknown_night_id_is_400(self, client):
        """A night_id on the update payload that doesn't belong to the session is
        rejected before the entry write."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}",
            json={'night_id': 'not-a-real-night'},
        )
        assert response.status_code == 400

    def test_update_entry_session_vanishes_when_night_id_given(self, client, monkeypatch):
        """A race where the session disappears between the entry lookup and the
        night_id check surfaces as a 404, not a crash."""
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'get_session', lambda *a, **k: None)
        response = client.put(
            '/api/observation-sessions/whatever/entries/whatever',
            json={'night_id': 'some-night'},
        )
        assert response.status_code == 404

    def test_delete_entry(self, client):
        """Deleting an entry succeeds once, then 404s."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        url = f"/api/observation-sessions/{session['id']}/entries/{entry['id']}"
        first = client.delete(url)
        assert first.status_code == 200
        second = client.delete(url)
        assert second.status_code == 404


class TestEntryCombinationResolution:
    """An entry's own optional equipment override goes through the same server-side
    resolution as the session's own combination_id (§_apply_resolved_entry_combination)."""

    def test_unknown_combination_is_dropped(self, client):
        """A combination the user has no access to never lands on the entry."""
        session = _create_session(client)
        entry = _add_entry(client, session['id'], combination_id='not-a-real-combination').get_json()['data']
        assert entry['combination_id'] is None
        assert entry['combination_name'] is None

    def test_owned_combination_id_is_resolved_with_name(self, client):
        """A combination the user owns resolves and its display name is attached,
        independent of whatever the session's own combination is."""
        scope = client.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        combo = client.post(
            '/api/equipment/combinations', json={'name': 'Dobsonian rig', 'telescope_id': scope['id']}
        ).get_json()['data']

        session = _create_session(client)
        entry = _add_entry(client, session['id'], combination_id=combo['id']).get_json()['data']
        assert entry['combination_id'] == combo['id']
        assert entry['combination_name'] == 'Dobsonian rig'

    def test_shared_combination_id_is_resolved_with_name(self, client):
        """A combination shared by another user resolves through the shared lookup."""
        owner_id = f'shared-owner-{uuid.uuid4().hex[:8]}'
        scope = equipment_profiles.create_telescope(owner_id, {**_TELESCOPE_DATA, 'is_shared': True})
        combo = equipment_profiles.create_combination(owner_id, {'name': 'Shared Combo', 'telescope_id': scope['id']})

        session = _create_session(client)
        entry = _add_entry(client, session['id'], combination_id=combo['id']).get_json()['data']
        assert entry['combination_id'] == combo['id']
        assert entry['combination_name'] == 'Shared Combo'

    def test_combination_untouched_when_update_omits_it(self, client):
        """Editing an unrelated field must not disturb an existing per-entry override."""
        scope = client.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        combo = client.post(
            '/api/equipment/combinations', json={'name': 'Dobsonian rig', 'telescope_id': scope['id']}
        ).get_json()['data']
        session = _create_session(client)
        entry = _add_entry(client, session['id'], combination_id=combo['id']).get_json()['data']

        updated = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'notes': 'x'}
        ).get_json()['data']
        assert updated['combination_id'] == combo['id']
        assert updated['combination_name'] == 'Dobsonian rig'

    def test_falsy_combination_id_clears_the_override(self, client):
        """Explicitly sending an empty combination_id clears the override back to
        "same as the session" rather than being ignored."""
        scope = client.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        combo = client.post(
            '/api/equipment/combinations', json={'name': 'Dobsonian rig', 'telescope_id': scope['id']}
        ).get_json()['data']
        session = _create_session(client)
        entry = _add_entry(client, session['id'], combination_id=combo['id']).get_json()['data']

        cleared = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'combination_id': ''}
        ).get_json()['data']
        assert cleared['combination_id'] is None
        assert cleared['combination_name'] is None


class TestAutomaticAstrodexLink:
    """Item-level catalogue membership is automatic, never a button (§0 of the plan)."""

    def test_entry_with_frames_creates_astrodex_item(self, client, admin_user_id):
        """Adding an entry with frame_count > 0 registers its target in Astrodex."""
        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=30).get_json()['data']

        assert entry['astrodex_item_id']
        item = astrodex.get_astrodex_item(admin_user_id, entry['astrodex_item_id'])
        assert item is not None
        assert item['name'] == 'M31'

    def test_entry_without_frames_creates_nothing(self, client, admin_user_id):
        """No capture evidence means no automatic Astrodex registration."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']

        assert entry['astrodex_item_id'] is None
        assert astrodex.load_user_astrodex(admin_user_id).get('items') == []

    def test_update_to_positive_frame_count_links(self, client):
        """Editing frame_count up to > 0 triggers the same automatic link."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']

        updated = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'frame_count': 5}
        ).get_json()['data']
        assert updated['astrodex_item_id']

    def test_existing_astrodex_item_is_reused_not_duplicated(self, client, admin_user_id):
        """A target already in Astrodex resolves to that item instead of creating a second one."""
        existing = astrodex.create_astrodex_item(
            admin_user_id, {'name': 'M31', 'type': 'Galaxy', 'catalogue': 'Messier'}, username='admin'
        )
        assert existing is not None

        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=10).get_json()['data']

        assert entry['astrodex_item_id'] == existing['id']
        assert len(astrodex.load_user_astrodex(admin_user_id)['items']) == 1

    def test_link_is_never_auto_reversed(self, client):
        """Editing frame_count back to 0 keeps the item link - once catalogued, always catalogued."""
        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=30).get_json()['data']
        item_id = entry['astrodex_item_id']
        assert item_id

        cleared = client.put(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'frame_count': 0}
        ).get_json()['data']
        assert cleared['frame_count'] == 0
        assert cleared['astrodex_item_id'] == item_id

    def test_link_failure_does_not_break_the_route(self, client, monkeypatch):
        """An Astrodex failure degrades to an unlinked entry rather than a 500."""
        monkeypatch.setattr(
            observation_sessions_bp_module.astrodex,
            'find_item_in_astrodex',
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('boom')),
        )
        session = _create_session(client)
        response = _add_entry(client, session['id'], frame_count=10)
        assert response.status_code == 201
        assert response.get_json()['data']['astrodex_item_id'] is None

    def test_deleting_an_entry_never_touches_astrodex(self, client, admin_user_id):
        """The Astrodex link is a soft reference: removing the entry keeps the item."""
        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=30).get_json()['data']

        client.delete(f"/api/observation-sessions/{session['id']}/entries/{entry['id']}")
        assert astrodex.get_astrodex_item(admin_user_id, entry['astrodex_item_id']) is not None

    def test_deleting_a_session_never_touches_astrodex(self, client, admin_user_id):
        """Same for deleting the whole session."""
        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=30).get_json()['data']

        client.delete(f"/api/observation-sessions/{session['id']}")
        assert astrodex.get_astrodex_item(admin_user_id, entry['astrodex_item_id']) is not None

    def test_catalogue_aliases_carry_over_to_new_astrodex_item(self, client, admin_user_id):
        """A newly-created Astrodex item inherits the entry's catalogue cross-reference
        aliases, when present."""
        session = _create_session(client)
        aliases = {'Messier': 'M31', 'OpenNGC': 'NGC 224'}
        entry = _add_entry(client, session['id'], frame_count=10, catalogue_aliases=aliases).get_json()['data']

        item = astrodex.get_astrodex_item(admin_user_id, entry['astrodex_item_id'])
        assert item['external_aliases'] == aliases

    def test_create_duplicate_race_falls_back_to_re_lookup(self, client, monkeypatch):
        """If create_astrodex_item reports a duplicate that appeared between our own
        lookup and the write (a narrow race), the entry still links to that item
        instead of ending up unlinked."""
        winner = {'id': 'winner-item-id', 'name': 'M31'}
        calls = {'n': 0}

        def _fake_find(*args, **kwargs):
            calls['n'] += 1
            return winner if calls['n'] > 1 else None

        monkeypatch.setattr(observation_sessions_bp_module.astrodex, 'find_item_in_astrodex', _fake_find)
        monkeypatch.setattr(observation_sessions_bp_module.astrodex, 'create_astrodex_item', lambda *a, **k: None)

        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=10).get_json()['data']
        assert entry['astrodex_item_id'] == 'winner-item-id'


class TestFromPlan:
    """POST /api/observation-sessions/from-plan"""

    @staticmethod
    def _plan_result(state='previous'):
        return {
            'state': state,
            'plan': {
                'plan_date': '2026-08-01',
                'location_id': None,
                'location_name': 'Backyard',
                'combination_id': 'combo-1',
                'combination_name': 'Refractor',
                'entries': [
                    {'id': 'plan-1', 'name': 'M31', 'catalogue': 'Messier'},
                    {'id': 'plan-2', 'name': 'M42', 'catalogue': 'Messier'},
                ],
            },
        }

    def test_import_from_previous_plan(self, client, monkeypatch):
        """A 'previous' plan is importable - that's when logging actually happens."""
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night,
            'get_plan_with_timeline',
            lambda *args, **kwargs: self._plan_result('previous'),
        )
        response = client.post('/api/observation-sessions/from-plan', json={'combination_id': 'combo-1'})
        assert response.status_code == 201
        session = response.get_json()['data']
        assert [entry['name'] for entry in session['entries']] == ['M31', 'M42']
        assert session['imported_from_plan_combination_id'] == 'combo-1'

    def test_import_carries_planned_minutes_through_the_api(self, client, monkeypatch):
        """The plan target's scheduled duration reaches the session entry end-to-end."""
        result = self._plan_result()
        result['plan']['entries'][0]['planned_minutes'] = 90
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night, 'get_plan_with_timeline', lambda *a, **k: result
        )
        session = client.post('/api/observation-sessions/from-plan', json={}).get_json()['data']
        assert session['entries'][0]['planned_minutes'] == pytest.approx(90.0)

    def test_import_from_current_plan(self, client, monkeypatch):
        """A 'current' plan works too."""
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night,
            'get_plan_with_timeline',
            lambda *args, **kwargs: self._plan_result('current'),
        )
        assert client.post('/api/observation-sessions/from-plan', json={}).status_code == 201

    def test_no_plan_is_404(self, client, monkeypatch):
        """Only 'none' (nothing to import) is refused."""
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night,
            'get_plan_with_timeline',
            lambda *args, **kwargs: {'state': 'none', 'plan': None},
        )
        assert client.post('/api/observation-sessions/from-plan', json={}).status_code == 404

    def test_empty_plan_is_404(self, client, monkeypatch):
        """A plan with no targets has nothing to import either."""
        result = self._plan_result()
        result['plan']['entries'] = []
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night, 'get_plan_with_timeline', lambda *a, **k: result
        )
        assert client.post('/api/observation-sessions/from-plan', json={}).status_code == 404

    def test_merge_into_existing_session(self, client, monkeypatch):
        """Re-importing into the same session is idempotent."""
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night,
            'get_plan_with_timeline',
            lambda *args, **kwargs: self._plan_result(),
        )
        first = client.post('/api/observation-sessions/from-plan', json={}).get_json()['data']
        merged = client.post('/api/observation-sessions/from-plan', json={'session_id': first['id']}).get_json()['data']
        assert len(merged['entries']) == 2

    def test_merge_into_unknown_session_is_404(self, client, monkeypatch):
        """A session_id that doesn't resolve is a 404, not a silent new session."""
        monkeypatch.setattr(
            observation_sessions_bp_module.plan_my_night,
            'get_plan_with_timeline',
            lambda *args, **kwargs: self._plan_result(),
        )
        response = client.post('/api/observation-sessions/from-plan', json={'session_id': 'missing'})
        assert response.status_code == 404


class TestAttachPicture:
    """POST .../entries/<entry_id>/astrodex-picture - the manual half of the linkage."""

    def test_attach_picture_creates_item_and_picture(self, client, admin_user_id):
        """Attaching resolves the item (creating it if needed) and stores both ids."""
        session = _create_session(client, location_name='Backyard')
        entry = _add_entry(
            client, session['id'], frame_count=20, sub_exposure_seconds=180, integration_minutes=60
        ).get_json()['data']

        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['astrodex_item_id']
        assert payload['astrodex_picture_id']

        item = astrodex.get_astrodex_item(admin_user_id, payload['astrodex_item_id'])
        picture = item['pictures'][0]
        assert picture['filename'] == 'photo.jpg'
        assert picture['date'] == '2026-07-14'
        # frames/exposition_time/integration_minutes are plain numbers (v1.3+), carried
        # straight over from the entry's own frame_count/sub_exposure_seconds/integration_minutes.
        assert picture['frames'] == 20
        assert picture['exposition_time'] == 180
        assert picture['integration_minutes'] == 60
        assert picture['location_name'] == 'Backyard'

        stored = client.get(f"/api/observation-sessions/{session['id']}").get_json()
        assert stored['entries'][0]['astrodex_picture_id'] == payload['astrodex_picture_id']

    def test_attach_picture_without_frame_count(self, client):
        """A photo can be attached before any numbers were logged."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        assert entry['astrodex_item_id'] is None

        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert response.status_code == 200
        assert response.get_json()['astrodex_item_id']

    def test_attach_picture_requires_filename(self, client):
        """A body without a filename is a 400."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture", json={}
        )
        assert response.status_code == 400

    def test_attach_picture_unknown_targets(self, client):
        """Unknown session or entry ids are 404s."""
        session = _create_session(client)
        assert (
            client.post(
                f"/api/observation-sessions/{session['id']}/entries/missing/astrodex-picture",
                json={'filename': 'x.jpg'},
            ).status_code
            == 404
        )
        assert (
            client.post(
                '/api/observation-sessions/missing/entries/missing/astrodex-picture', json={'filename': 'x.jpg'}
            ).status_code
            == 404
        )

    def test_attach_picture_rejects_bad_rating_override(self, client):
        """An explicit rating override is validated like everywhere else."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'rating': 42},
        )
        assert response.status_code == 400

    def test_attach_picture_prefers_the_entry_own_combination_over_the_session(self, client, admin_user_id):
        """When a target was shot with different equipment than the session's own
        default, attaching its photo must carry that override, not the session's."""
        scope = client.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        session_combo = client.post(
            '/api/equipment/combinations', json={'name': 'Session default rig', 'telescope_id': scope['id']}
        ).get_json()['data']
        entry_combo = client.post(
            '/api/equipment/combinations', json={'name': 'Swapped-in rig', 'telescope_id': scope['id']}
        ).get_json()['data']

        session = _create_session(client, combination_id=session_combo['id'])
        entry = _add_entry(client, session['id'], combination_id=entry_combo['id']).get_json()['data']

        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert response.status_code == 200
        item = astrodex.get_astrodex_item(admin_user_id, response.get_json()['astrodex_item_id'])
        assert item['pictures'][0]['combination_id'] == entry_combo['id']


class TestAttachments:
    """POST/GET/DELETE .../attachments - generic files, unrelated to the entry ->
    Astrodex picture link above."""

    def test_upload_download_and_delete_round_trip(self, client):
        session = _create_session(client)

        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'fake image bytes'), 'guiding-graph.jpg')},
            content_type='multipart/form-data',
        )
        assert upload.status_code == 201
        attachment = upload.get_json()['data']
        assert attachment['original_name'] == 'guiding-graph.jpg'
        assert attachment['filename'].endswith('.jpg')

        stored = client.get(f"/api/observation-sessions/{session['id']}").get_json()
        assert [a['id'] for a in stored['attachments']] == [attachment['id']]

        download = client.get(f"/api/observation-sessions/attachments/{attachment['filename']}")
        assert download.status_code == 200
        assert download.data == b'fake image bytes'

        deletion = client.delete(f"/api/observation-sessions/{session['id']}/attachments/{attachment['id']}")
        assert deletion.status_code == 200

        after_delete = client.get(f"/api/observation-sessions/attachments/{attachment['filename']}")
        assert after_delete.status_code == 403  # metadata gone -> ownership check fails closed

    def test_upload_accepts_pdf_txt_and_word(self, client):
        session = _create_session(client)
        for filename, allowed in [
            ('notes.pdf', True),
            ('notes.txt', True),
            ('notes.doc', True),
            ('notes.docx', True),
            ('notes.exe', False),
        ]:
            response = client.post(
                f"/api/observation-sessions/{session['id']}/attachments",
                data={'file': (io.BytesIO(b'data'), filename)},
                content_type='multipart/form-data',
            )
            assert response.status_code == (201 if allowed else 400)

    def test_upload_no_file_is_400(self, client):
        session = _create_session(client)
        response = client.post(f"/api/observation-sessions/{session['id']}/attachments")
        assert response.status_code == 400

    def test_upload_empty_filename_is_400(self, client):
        session = _create_session(client)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), '')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400

    def test_upload_no_extension_is_400(self, client):
        session = _create_session(client)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'noext')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400

    def test_upload_unknown_session_is_404(self, client):
        response = client.post(
            '/api/observation-sessions/missing/attachments',
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 404

    def test_download_unknown_filename_is_403(self, client):
        """Never uploaded (or by someone else) - ownership check fails closed, same 403
        as a real file the caller doesn't own, not a 404 that would confirm existence."""
        assert client.get('/api/observation-sessions/attachments/never-uploaded.jpg').status_code == 403

    def test_download_requires_login_only_not_user_role(self, client):
        """The serving route is @login_required (a read), unlike upload/delete which are
        @user_required - matches the astrodex.py image-serving convention."""
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']
        assert client.get(f"/api/observation-sessions/attachments/{upload['filename']}").status_code == 200

    def test_delete_unknown_attachment_is_404(self, client):
        session = _create_session(client)
        response = client.delete(f"/api/observation-sessions/{session['id']}/attachments/missing")
        assert response.status_code == 404

    def test_download_content_disposition_uses_original_name_not_storage_uuid(self, client):
        """The saved filename should be the human-readable original name, not the
        regenerated `{uuid}.{ext}` storage key that's the last segment of the URL."""
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'guiding-graph.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']

        download = client.get(f"/api/observation-sessions/attachments/{upload['filename']}")
        disposition = download.headers.get('Content-Disposition', '')
        assert 'guiding-graph.jpg' in disposition
        assert upload['filename'] not in disposition

    def test_rename_sets_display_name_used_in_list_and_download(self, client):
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'guiding-graph.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']

        rename = client.put(
            f"/api/observation-sessions/{session['id']}/attachments/{upload['id']}",
            json={'name': 'My Guiding Graph'},
        )
        assert rename.status_code == 200
        assert rename.get_json()['data']['display_name'] == 'My Guiding Graph'

        stored = client.get(f"/api/observation-sessions/{session['id']}").get_json()
        assert stored['attachments'][0]['display_name'] == 'My Guiding Graph'

        # No extension in the custom name -> the real one is reattached for the download.
        download = client.get(f"/api/observation-sessions/attachments/{upload['filename']}")
        assert 'My Guiding Graph.jpg' in download.headers.get('Content-Disposition', '')

    def test_rename_blank_clears_display_name(self, client):
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'guiding-graph.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']
        client.put(
            f"/api/observation-sessions/{session['id']}/attachments/{upload['id']}",
            json={'name': 'My Guiding Graph'},
        )

        cleared = client.put(
            f"/api/observation-sessions/{session['id']}/attachments/{upload['id']}",
            json={'name': '   '},
        )
        assert cleared.status_code == 200
        assert cleared.get_json()['data']['display_name'] is None

    def test_rename_unknown_attachment_is_404(self, client):
        session = _create_session(client)
        response = client.put(
            f"/api/observation-sessions/{session['id']}/attachments/missing",
            json={'name': 'x'},
        )
        assert response.status_code == 404

    def test_rename_unknown_session_is_404(self, client):
        response = client.put(
            '/api/observation-sessions/missing/attachments/also-missing',
            json={'name': 'x'},
        )
        assert response.status_code == 404


class TestAttachmentsSurviveBackupRestore:
    """data/observation_sessions/ is already a full recursive entry in admin.py's
    BACKUP_ENTRIES/RESTORE_ALLOWED_PREFIXES, so the new attachments/ subdirectory needs
    zero backup/restore code changes - confirmed here with a genuine round trip rather
    than just assumed (the plan's own explicit instruction for this milestone)."""

    def test_attachment_survives_a_backup_restore_round_trip(self, client, monkeypatch, isolated_storage):
        import zipfile

        from blueprints import admin as admin_bp_module

        monkeypatch.setattr(admin_bp_module, 'DATA_DIR', isolated_storage)

        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'guiding data'), 'guide.txt')},
            content_type='multipart/form-data',
        ).get_json()['data']

        backup = client.get('/api/backup/download')
        assert backup.status_code == 200
        with zipfile.ZipFile(io.BytesIO(backup.data)) as zip_file:
            names = zip_file.namelist()
            assert any(name.endswith(f"attachments/{upload['filename']}") for name in names)

        # Simulate data loss, then restore from the backup just downloaded.
        file_path = os.path.join(observation_sessions.attachments_dir(), upload['filename'])
        os.remove(file_path)
        assert not os.path.exists(file_path)

        restore = client.post(
            '/api/backup/restore',
            data={'file': (io.BytesIO(backup.data), 'backup.zip')},
            content_type='multipart/form-data',
        )
        assert restore.status_code == 200
        assert os.path.exists(file_path)
        with open(file_path, 'rb') as file_obj:
            assert file_obj.read() == b'guiding data'


class TestAstrodexBacklink:
    """GET /api/astrodex reverse-links each item/picture back to the session that logged it."""

    def test_item_with_no_session_has_empty_backlink(self, client, admin_user_id):
        """An Astrodex item never touched by Observation Log shows no backlink."""
        astrodex.create_astrodex_item(
            admin_user_id, {'name': 'M13', 'type': 'Cluster', 'catalogue': 'Messier'}, username='admin'
        )
        items = client.get('/api/astrodex').get_json()['items']
        item = next(i for i in items if i['name'] == 'M13')
        assert item['observation_sessions'] == []

    def test_entry_with_frame_count_backlinks_the_item(self, client):
        """Auto-linking an entry (frame_count > 0) makes the item show which session did it."""
        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=30).get_json()['data']

        items = client.get('/api/astrodex').get_json()['items']
        item = next(i for i in items if i['id'] == entry['astrodex_item_id'])
        assert [match['session_id'] for match in item['observation_sessions']] == [session['id']]
        assert item['observation_sessions'][0]['session_date'] == session['nights'][0]['date']
        assert item['observation_sessions'][0]['entry_id'] == entry['id']

    def test_attached_picture_backlinks_that_specific_picture(self, client):
        """Attaching a picture links that exact photo, not just the parent item."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        attach = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        ).get_json()

        items = client.get('/api/astrodex').get_json()['items']
        item = next(i for i in items if i['id'] == attach['astrodex_item_id'])
        picture = next(p for p in item['pictures'] if p['id'] == attach['astrodex_picture_id'])
        assert picture['observation_session']['session_id'] == session['id']
        # own_pictures is a separate deepcopy the frontend actually renders from -
        # it must carry the same backlink, not just the raw 'pictures' list.
        own_picture = next(p for p in item['own_pictures'] if p['id'] == attach['astrodex_picture_id'])
        assert own_picture['observation_session']['session_id'] == session['id']

    def test_two_nights_on_the_same_target_both_appear(self, client):
        """A target logged in two different sessions accumulates two backlink matches."""
        session_a = _create_session(client, date='2026-07-10')
        entry_a = _add_entry(client, session_a['id'], frame_count=10).get_json()['data']
        session_b = _create_session(client, date='2026-07-14')
        _add_entry(client, session_b['id'], frame_count=15).get_json()

        items = client.get('/api/astrodex').get_json()['items']
        item = next(i for i in items if i['id'] == entry_a['astrodex_item_id'])
        assert {match['session_id'] for match in item['observation_sessions']} == {session_a['id'], session_b['id']}

    def test_attach_picture_rejects_bad_exposition_time_override(self, client):
        """An explicit exposition_time override must be a whole number of seconds."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'exposition_time': '120x30s'},
        )
        assert response.status_code == 400

    def test_attach_picture_rejects_negative_exposition_time(self, client):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'exposition_time': -5},
        )
        assert response.status_code == 400

    def test_attach_picture_rejects_non_numeric_frames(self, client):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'frames': 'many'},
        )
        assert response.status_code == 400

    def test_attach_picture_rejects_negative_frames(self, client):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'frames': -3},
        )
        assert response.status_code == 400

    def test_attach_picture_rejects_non_numeric_integration_minutes(self, client):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'integration_minutes': 'a lot'},
        )
        assert response.status_code == 400

    def test_attach_picture_rejects_negative_integration_minutes(self, client):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg', 'integration_minutes': -10},
        )
        assert response.status_code == 400

    def test_attach_picture_returns_500_when_item_cannot_be_resolved(self, client, monkeypatch):
        """A resolution failure (e.g. Astrodex write error) surfaces as a 500 rather than
        silently attaching to nothing."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module, '_ensure_astrodex_item_for_entry', lambda user, entry: None)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert response.status_code == 500

    def test_attach_picture_returns_500_when_astrodex_write_fails(self, client, monkeypatch):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.astrodex, 'add_picture_to_item', lambda *a, **k: None)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert response.status_code == 500


class TestExportPdf:
    """GET .../export.pdf (one session) and GET /api/observation-sessions/export.pdf (all)."""

    def test_routes_require_login(self):
        app.config['TESTING'] = True
        with app.test_client() as anonymous:
            assert anonymous.get('/api/observation-sessions/x/export.pdf').status_code == 401
            assert anonymous.get('/api/observation-sessions/export.pdf').status_code == 401

    def test_unknown_session_is_404(self, client):
        assert client.get('/api/observation-sessions/missing/export.pdf').status_code == 404

    def test_per_session_pdf(self, client):
        """A session with a plain (photo-less) entry still exports a valid PDF."""
        session = _create_session(client)
        _add_entry(client, session['id'], frame_count=10)

        response = client.get(f"/api/observation-sessions/{session['id']}/export.pdf")
        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'
        assert response.data.startswith(b'%PDF')

    def test_per_session_pdf_with_attached_photo(self, client):
        """The entry's attached Astrodex photo is resolved to a real file and embedded."""
        from PIL import Image

        session = _create_session(client)
        entry = _add_entry(client, session['id'], frame_count=20).get_json()['data']

        os.makedirs(astrodex.ASTRODEX_IMAGES_DIR, exist_ok=True)
        Image.new('RGB', (80, 60), color='red').save(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, 'photo.jpg'))
        attach = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert attach.status_code == 200

        response = client.get(f"/api/observation-sessions/{session['id']}/export.pdf")
        assert response.status_code == 200
        assert response.data.startswith(b'%PDF')

    def test_per_session_pdf_ignores_missing_image_file(self, client):
        """A picture record whose file vanished from disk degrades to a placeholder, not a 500."""
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'never-written.jpg'},
        )

        response = client.get(f"/api/observation-sessions/{session['id']}/export.pdf")
        assert response.status_code == 200
        assert response.data.startswith(b'%PDF')

    def test_global_pdf_with_no_sessions(self, client):
        """An empty log still produces a valid (cover-only) PDF, not an error."""
        response = client.get('/api/observation-sessions/export.pdf')
        assert response.status_code == 200
        assert response.data.startswith(b'%PDF')

    def test_global_pdf_with_date_range_and_order(self, client):
        _create_session(client, date='2026-01-01')
        _create_session(client, date='2026-06-01')

        response = client.get('/api/observation-sessions/export.pdf?from_date=2026-01-01&to_date=2026-12-31&order=desc')
        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'
        assert response.data.startswith(b'%PDF')

    def test_global_pdf_range_excludes_out_of_window_sessions(self, client, monkeypatch):
        """from_date/to_date actually filter which sessions are rendered, not just
        labelled - on both sides of the window."""
        _create_session(client, date='2025-01-01')
        _create_session(client, date='2026-06-01')
        _create_session(client, date='2027-01-01')

        captured = {}
        original = observation_sessions_bp_module.observation_sessions.generate_sessions_pdf

        def _capture(sessions, *args, **kwargs):
            captured['count'] = len(sessions)
            return original(sessions, *args, **kwargs)

        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'generate_sessions_pdf', _capture)

        response = client.get('/api/observation-sessions/export.pdf?from_date=2026-01-01&to_date=2026-12-31')
        assert response.status_code == 200
        assert captured['count'] == 1

    def test_global_pdf_other_users_sessions_are_never_included(self, client, admin_user_id):
        """Only the caller's own sessions are exported."""
        other_user = str(uuid.uuid4())
        observation_sessions.create_session(other_user, 'other', {'date': '2026-05-05'})
        _create_session(client, date='2026-01-01')

        response = client.get('/api/observation-sessions/export.pdf')
        assert response.status_code == 200
        assert response.data.startswith(b'%PDF')


class TestExceptionHandling:
    """Every route's top-level except-clause: an unexpected storage-layer error becomes
    a 500 rather than propagating."""

    @staticmethod
    def _raise(*args, **kwargs):
        raise RuntimeError('boom')

    def test_list_sessions_500(self, client, monkeypatch):
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'load_user_sessions', self._raise)
        assert client.get('/api/observation-sessions').status_code == 500

    def test_get_session_500(self, client, monkeypatch):
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'get_session', self._raise)
        assert client.get('/api/observation-sessions/x').status_code == 500

    def test_create_session_failure_returns_500(self, client, monkeypatch):
        """create_session() returning None (as opposed to raising) is also a 500."""
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'create_session', lambda *a, **k: None)
        response = client.post('/api/observation-sessions', json={'date': '2026-01-01'})
        assert response.status_code == 500

    def test_create_session_exception_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'create_session', self._raise)
        response = client.post('/api/observation-sessions', json={'date': '2026-01-01'})
        assert response.status_code == 500

    def test_update_session_500(self, client, monkeypatch):
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'update_session', self._raise)
        response = client.put(f"/api/observation-sessions/{session['id']}", json={'notes': 'x'})
        assert response.status_code == 500

    def test_delete_session_500(self, client, monkeypatch):
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'delete_session', self._raise)
        response = client.delete(f"/api/observation-sessions/{session['id']}")
        assert response.status_code == 500

    def test_from_plan_500(self, client, monkeypatch):
        monkeypatch.setattr(observation_sessions_bp_module.plan_my_night, 'get_plan_with_timeline', self._raise)
        response = client.post('/api/observation-sessions/from-plan', json={})
        assert response.status_code == 500

    def test_add_night_storage_failure_returns_500(self, client, monkeypatch):
        """add_night() returning nothing (as opposed to raising) is also a 500."""
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'add_night', lambda *a, **k: None)
        response = client.post(f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'})
        assert response.status_code == 500

    def test_add_night_500(self, client, monkeypatch):
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'add_night', self._raise)
        response = client.post(f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'})
        assert response.status_code == 500

    def test_update_night_500(self, client, monkeypatch):
        session = _create_session(client)
        night_id = session['nights'][0]['id']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'update_night', self._raise)
        response = client.put(f"/api/observation-sessions/{session['id']}/nights/{night_id}", json={'notes': 'x'})
        assert response.status_code == 500

    def test_delete_night_500(self, client, monkeypatch):
        session = _create_session(client, date='2026-07-14')
        added = client.post(
            f"/api/observation-sessions/{session['id']}/nights", json={'date': '2026-07-15'}
        ).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'get_session', self._raise)
        response = client.delete(f"/api/observation-sessions/{session['id']}/nights/{added['id']}")
        assert response.status_code == 500

    def test_upload_attachment_storage_race_returns_500_and_cleans_up_the_saved_file(self, client, monkeypatch):
        """If the metadata write fails after the file was already saved to disk (a
        narrow race), the orphaned file is removed - and a failure during that
        best-effort cleanup still surfaces the original 500, not a crash."""
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'add_attachment', lambda *a, **k: None)

        def _raise_oserror(*args, **kwargs):
            raise OSError('cannot remove')

        monkeypatch.setattr(observation_sessions_bp_module.os, 'remove', _raise_oserror)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 500

    def test_upload_attachment_500(self, client, monkeypatch):
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'add_attachment', self._raise)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 500

    def test_download_attachment_500(self, client, monkeypatch):
        """An unexpected failure while resolving ownership is reported the same as a
        genuinely missing file, not a 500 that would hint at server internals."""
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'get_user_sessions', self._raise)
        response = client.get(f"/api/observation-sessions/attachments/{upload['filename']}")
        assert response.status_code == 404

    def test_rename_attachment_500(self, client, monkeypatch):
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'rename_attachment', self._raise)
        response = client.put(
            f"/api/observation-sessions/{session['id']}/attachments/{upload['id']}", json={'name': 'x'}
        )
        assert response.status_code == 500

    def test_delete_attachment_500(self, client, monkeypatch):
        session = _create_session(client)
        upload = client.post(
            f"/api/observation-sessions/{session['id']}/attachments",
            data={'file': (io.BytesIO(b'data'), 'a.jpg')},
            content_type='multipart/form-data',
        ).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'delete_attachment', self._raise)
        response = client.delete(f"/api/observation-sessions/{session['id']}/attachments/{upload['id']}")
        assert response.status_code == 500

    def test_add_entry_500(self, client, monkeypatch):
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'add_entry', self._raise)
        response = client.post(f"/api/observation-sessions/{session['id']}/entries", json={'name': 'M31'})
        assert response.status_code == 500

    def test_update_entry_500(self, client, monkeypatch):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'update_entry', self._raise)
        response = client.put(f"/api/observation-sessions/{session['id']}/entries/{entry['id']}", json={'notes': 'x'})
        assert response.status_code == 500

    def test_delete_entry_500(self, client, monkeypatch):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'delete_entry', self._raise)
        response = client.delete(f"/api/observation-sessions/{session['id']}/entries/{entry['id']}")
        assert response.status_code == 500

    def test_attach_picture_500(self, client, monkeypatch):
        session = _create_session(client)
        entry = _add_entry(client, session['id']).get_json()['data']
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'get_session', self._raise)
        response = client.post(
            f"/api/observation-sessions/{session['id']}/entries/{entry['id']}/astrodex-picture",
            json={'filename': 'photo.jpg'},
        )
        assert response.status_code == 500

    def test_per_session_export_pdf_500(self, client, monkeypatch):
        session = _create_session(client)
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'generate_session_pdf', self._raise)
        response = client.get(f"/api/observation-sessions/{session['id']}/export.pdf")
        assert response.status_code == 500

    def test_global_export_pdf_500(self, client, monkeypatch):
        monkeypatch.setattr(observation_sessions_bp_module.observation_sessions, 'get_user_sessions', self._raise)
        response = client.get('/api/observation-sessions/export.pdf')
        assert response.status_code == 500
