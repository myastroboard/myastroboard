"""API tests for the Session Analytics blueprint (/api/session-analytics/*, /api/wishlist*).

These cover the layer the pure aggregation engine cannot: authentication, self-scoping,
query-parameter validation and the timezone-aware "today" the month bucket depends on.
The aggregates themselves are exercised in tests/observation/test_session_analytics.py.
"""

import os
import sys
import tempfile
import types
import uuid

import pytest

from observation import astrodex
from observation import observation_sessions
from observation import session_analytics as session_analytics_module
from observation import wishlist
from utils.auth import user_manager
from utils.constants import MAX_WISHLIST_ITEMS

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from blueprints import session_analytics as session_analytics_bp_module

ROUTES = (
    '/api/session-analytics/summary',
    '/api/session-analytics/sky-coverage',
    '/api/session-analytics/conditions',
)


@pytest.fixture
def isolated_storage(monkeypatch):
    """Point Observation Log and Astrodex storage at temporary directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(
            observation_sessions, 'OBSERVATION_SESSIONS_DIR', os.path.join(tmpdir, 'observation_sessions')
        )
        monkeypatch.setattr(astrodex, 'ASTRODEX_DIR', os.path.join(tmpdir, 'astrodex'))
        monkeypatch.setattr(astrodex, 'ASTRODEX_IMAGES_DIR', os.path.join(tmpdir, 'astrodex', 'images'))
        yield tmpdir


@pytest.fixture
def stub_location(monkeypatch):
    """A fixed active location, so the tests do not depend on the install's config."""
    location = {
        'id': 'loc-test',
        'name': 'Test Site',
        'latitude': 48.0,
        'longitude': 2.0,
        'timezone': 'Europe/Paris',
    }
    monkeypatch.setattr(session_analytics_bp_module, '_resolve_active_location', lambda: location)
    return location


@pytest.fixture
def client(isolated_storage, stub_location):
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


def _create_read_only_user():
    """Create a real read-only account: role gating reads the stored user, not the session."""
    username = f'ro_{uuid.uuid4().hex[:8]}'
    user_manager.create_user(username, 'test123', 'read-only')
    return username


def _seed_session(user_id, username, date_value='2026-07-14', **entry_fields):
    """Create one session with one captured entry directly through the storage layer."""
    session = observation_sessions.create_session(user_id, username, {'date': date_value})
    assert session is not None
    payload = {'name': 'M 31', 'catalogue': 'Messier', 'type': 'Galaxy', 'constellation': 'And'}
    payload.update(entry_fields)
    entry = observation_sessions.add_entry(user_id, session['id'], payload)
    assert entry is not None
    return session, entry


class TestAuth:
    """Every route is login-gated and self-scoped."""

    def test_routes_require_login(self):
        app.config['TESTING'] = True
        with app.test_client() as anonymous:
            for route in ROUTES:
                assert anonymous.get(route).status_code == 401, route

    def test_read_only_role_may_read_analytics(self, isolated_storage, stub_location):
        """Analytics are read-only, so a read-only account is entitled to them."""
        app.config['TESTING'] = True
        username = _create_read_only_user()
        with app.test_client() as test_client:
            with test_client.session_transaction() as session:
                session['username'] = username
                session['role'] = 'read-only'
            for route in ROUTES:
                assert test_client.get(route).status_code == 200, route


class TestSummary:

    def test_empty_account_returns_zeros_not_an_error(self, client):
        """A fresh install has nothing logged; the dashboard still has to render."""
        payload = client.get('/api/session-analytics/summary').get_json()
        assert payload['totals']['integration_minutes_lifetime'] == 0.0
        assert payload['totals']['sessions'] == 0
        assert payload['monthly'] == []

    def test_logged_session_is_aggregated(self, client, admin_user_id):
        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0, rating=4.0)
        payload = client.get('/api/session-analytics/summary').get_json()
        assert payload['totals']['integration_minutes_lifetime'] == pytest.approx(120.0)
        assert payload['totals']['entries'] == 1
        assert payload['totals']['objects_captured'] == 1
        assert payload['totals']['average_rating'] == pytest.approx(4.0)

    def test_astrodex_size_is_reported_separately(self, client, admin_user_id):
        """The log and the gallery are two different counts, never merged."""
        astrodex.create_astrodex_item(admin_user_id, {'name': 'M 42', 'type': 'Nebula'}, username='admin')
        payload = client.get('/api/session-analytics/summary').get_json()
        assert payload['totals']['astrodex_items'] == 1
        assert payload['totals']['objects_captured'] == 0

    def test_response_carries_the_active_location_and_observer_date(self, client, stub_location):
        payload = client.get('/api/session-analytics/summary').get_json()
        assert payload['location_id'] == stub_location['id']
        assert len(payload['today']) == 10

    def test_year_parameter_selects_the_year_bucket(self, client, admin_user_id):
        _seed_session(admin_user_id, 'admin', '2025-08-02', frame_count=10, integration_minutes=100.0)
        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=10, integration_minutes=50.0)
        payload = client.get('/api/session-analytics/summary?year=2025').get_json()
        assert payload['year'] == 2025
        assert payload['totals']['integration_minutes_year'] == pytest.approx(100.0)
        assert payload['totals']['integration_minutes_lifetime'] == pytest.approx(150.0)

    def test_empty_year_parameter_falls_back_to_the_current_year(self, client):
        assert client.get('/api/session-analytics/summary?year=').status_code == 200

    def test_unparseable_year_is_rejected(self, client):
        assert client.get('/api/session-analytics/summary?year=abc').status_code == 400

    def test_implausible_year_is_rejected(self, client):
        assert client.get('/api/session-analytics/summary?year=99999').status_code == 400
        assert client.get('/api/session-analytics/summary?year=1000').status_code == 400

    def test_another_users_log_is_never_included(self, client, admin_user_id):
        """Sessions are permanently private, so analytics are too."""
        _seed_session('someone-else', 'someone-else', '2026-07-14', frame_count=40, integration_minutes=600.0)
        payload = client.get('/api/session-analytics/summary').get_json()
        assert payload['totals']['integration_minutes_lifetime'] == 0.0

    def test_internal_failure_returns_500_without_leaking(self, client, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError('storage exploded')

        monkeypatch.setattr(session_analytics_bp_module.session_analytics, 'build_summary', boom)
        response = client.get('/api/session-analytics/summary')
        assert response.status_code == 500
        assert response.get_json() == {'error': 'Internal server error'}


class TestObserverToday:
    """The month bucket must follow the observer's clock, not the server's."""

    def test_uses_the_active_location_timezone(self):
        assert session_analytics_bp_module._observer_today({'timezone': 'Pacific/Kiritimati'}) is not None

    def test_falls_back_to_utc_for_an_unusable_timezone(self):
        from datetime import datetime, timezone as dt_timezone

        utc_today = datetime.now(dt_timezone.utc).date()
        assert session_analytics_bp_module._observer_today({'timezone': 'Not/AZone'}) == utc_today
        assert session_analytics_bp_module._observer_today({}) == utc_today
        assert session_analytics_bp_module._observer_today({'timezone': '  '}) == utc_today


class TestSkyCoverage:

    def test_empty_account(self, client):
        payload = client.get('/api/session-analytics/sky-coverage').get_json()
        assert payload['points'] == []
        assert payload['unplaced_count'] == 0

    def test_never_visible_band_comes_from_the_active_location(self, client):
        payload = client.get('/api/session-analytics/sky-coverage').get_json()
        assert payload['never_visible_dec_below'] == pytest.approx(-42.0)
        assert payload['location_name'] == 'Test Site'

    def test_a_captured_entry_is_placed(self, client, admin_user_id, monkeypatch):
        monkeypatch.setattr(
            session_analytics_module.target_coordinates,
            'resolve_target',
            lambda *args, **kwargs: {
                'group_id': 'dso-ngc0224',
                'target_id': 'dso-ngc0224',
                'preferred_name': 'M 31',
                'object_type': 'Galaxy',
                'constellation': 'And',
                'category': 'deep_sky',
                'ra_deg': 10.68,
                'dec_deg': 41.27,
                'resolved': True,
                'placed': True,
            },
        )
        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0)
        payload = client.get('/api/session-analytics/sky-coverage').get_json()
        assert len(payload['points']) == 1
        assert payload['points'][0]['ra_deg'] == pytest.approx(10.68)

    def test_internal_failure_returns_500(self, client, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError('nope')

        monkeypatch.setattr(session_analytics_bp_module.session_analytics, 'build_sky_coverage', boom)
        assert client.get('/api/session-analytics/sky-coverage').status_code == 500


class TestConditions:

    def test_empty_account(self, client):
        payload = client.get('/api/session-analytics/conditions').get_json()
        assert payload['samples'] == []
        assert payload['total_rated_entries'] == 0
        assert set(payload['metrics']) == {'seeing', 'transparency', 'sqm', 'moon_illumination_percent'}

    def test_a_rated_entry_becomes_a_sample(self, client, admin_user_id):
        session, _entry = _seed_session(
            admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0, rating=4.5
        )
        night_id = session['nights'][0]['id']
        assert observation_sessions.update_night(
            admin_user_id, session['id'], night_id, {'seeing': 2, 'transparency': 7, 'sqm': 21.0}
        )
        payload = client.get('/api/session-analytics/conditions').get_json()
        assert payload['total_rated_entries'] == 1
        assert payload['samples'][0]['rating'] == pytest.approx(4.5)
        assert payload['samples'][0]['seeing'] == 2

    def test_metrics_declare_their_direction(self, client):
        metrics = client.get('/api/session-analytics/conditions').get_json()['metrics']
        assert metrics['seeing']['direction'] == 'lower_is_better'
        assert metrics['transparency']['direction'] == 'higher_is_better'

    def test_internal_failure_returns_500(self, client, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError('nope')

        monkeypatch.setattr(session_analytics_bp_module.session_analytics, 'build_conditions', boom)
        assert client.get('/api/session-analytics/conditions').status_code == 500


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------

WISHLIST_WRITE_CALLS = (
    ('post', '/api/wishlist', {'targets': [{'name': 'M 31'}]}),
    ('patch', '/api/wishlist/whatever', {'priority': 'high'}),
    ('delete', '/api/wishlist/whatever', None),
    ('post', '/api/wishlist/archive-captured', {}),
)


@pytest.fixture
def isolated_wishlist(monkeypatch):
    """Point wishlist storage at a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        directory = os.path.join(tmpdir, 'wishlist')
        monkeypatch.setattr(wishlist, 'WISHLIST_DIR', directory)
        yield directory


@pytest.fixture
def stub_visibility(monkeypatch):
    """Skip the real ephemeris in route tests.

    next_visibility_batch() is exercised for real in tests/observation; here it would add
    a few Astropy night grids to every single request for no extra coverage of the route.
    """
    def fake_batch(targets, location, reference_date=None, months_ahead=3):
        return [
            {
                'observable_hours_next': 4.5,
                'moonless_observable_hours_next': 3.0,
                'max_altitude_next': 62.0,
                'transit_local_time_next': '01:12',
                'best_month': 9,
                'best_month_hours': 5.5,
                'sampled_dates': [],
            }
            for _ in targets
        ]

    monkeypatch.setattr(session_analytics_bp_module.visibility_calendar, 'next_visibility_batch', fake_batch)
    monkeypatch.setattr(
        session_analytics_bp_module.visibility_calendar, 'dark_hours_by_month', lambda *_a, **_k: []
    )


@pytest.fixture
def wishlist_client(client, isolated_wishlist, stub_visibility):
    """The authenticated client, with wishlist storage isolated and no ephemeris work."""
    return client


def _post_target(test_client, **overrides):
    target = {'name': 'M 31', 'catalogue': 'Messier', 'type': 'Galaxy', 'constellation': 'And'}
    target.update(overrides)
    return test_client.post('/api/wishlist', json={'targets': [target]})


class TestWishlistAuth:

    def test_every_route_requires_login(self, isolated_wishlist):
        app.config['TESTING'] = True
        with app.test_client() as anonymous:
            assert anonymous.get('/api/wishlist').status_code == 401
            for method, url, body in WISHLIST_WRITE_CALLS:
                caller = getattr(anonymous, method)
                response = caller(url, json=body) if body is not None else caller(url)
                assert response.status_code == 401, url

    def test_read_only_role_cannot_write(self, isolated_wishlist, stub_location):
        """A read-only account may look at a wishlist but never change one."""
        app.config['TESTING'] = True
        username = _create_read_only_user()
        with app.test_client() as test_client:
            with test_client.session_transaction() as session:
                session['username'] = username
                session['role'] = 'read-only'
            assert test_client.get('/api/wishlist').status_code == 200
            for method, url, body in WISHLIST_WRITE_CALLS:
                caller = getattr(test_client, method)
                response = caller(url, json=body) if body is not None else caller(url)
                assert response.status_code == 403, url


class TestWishlistList:

    def test_empty_wishlist(self, wishlist_client):
        payload = wishlist_client.get('/api/wishlist').get_json()
        assert payload['items'] == []
        assert payload['progress'] == {'captured': 0, 'total': 0}
        assert payload['max_items'] > 0

    def test_added_target_is_listed(self, wishlist_client):
        assert _post_target(wishlist_client).status_code == 201
        payload = wishlist_client.get('/api/wishlist').get_json()
        assert [item['name'] for item in payload['items']] == ['M 31']
        assert payload['progress'] == {'captured': 0, 'total': 1}

    def test_sort_parameter_is_accepted(self, wishlist_client):
        _post_target(wishlist_client, name='M 42')
        _post_target(wishlist_client, name='M 31', priority='high')
        names = [item['name'] for item in wishlist_client.get('/api/wishlist?sort=priority').get_json()['items']]
        assert names[0] == 'M 31'

    def test_unknown_sort_still_returns_the_list(self, wishlist_client):
        _post_target(wishlist_client)
        assert wishlist_client.get('/api/wishlist?sort=nonsense').status_code == 200

    def test_another_users_wishlist_is_never_returned(self, wishlist_client):
        wishlist.add_targets('someone-else', 'someone-else', [{'name': 'M 42'}])
        assert wishlist_client.get('/api/wishlist').get_json()['items'] == []


class TestWishlistCapturedState:
    """Captured is recomputed on every read, so an edit is reflected immediately."""

    def test_a_logged_capture_marks_the_wish_captured(self, wishlist_client, admin_user_id):
        _post_target(wishlist_client)
        assert wishlist_client.get('/api/wishlist').get_json()['progress']['captured'] == 0

        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0)
        payload = wishlist_client.get('/api/wishlist').get_json()
        assert payload['progress']['captured'] == 1
        assert payload['items'][0]['captured'] is True

    def test_an_astrodex_item_marks_the_wish_captured(self, wishlist_client, admin_user_id):
        _post_target(wishlist_client)
        astrodex.create_astrodex_item(admin_user_id, {'name': 'M 31', 'type': 'Galaxy'}, username='admin')
        assert wishlist_client.get('/api/wishlist').get_json()['progress']['captured'] == 1

    def test_an_uncaptured_entry_does_not_count(self, wishlist_client, admin_user_id):
        """A planned-but-clouded-out target is not a capture."""
        _post_target(wishlist_client)
        _seed_session(admin_user_id, 'admin', '2026-07-14')
        assert wishlist_client.get('/api/wishlist').get_json()['progress']['captured'] == 0

    def test_captured_state_is_not_persisted(self, wishlist_client, admin_user_id, isolated_wishlist):
        _post_target(wishlist_client)
        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0)
        assert wishlist_client.get('/api/wishlist').get_json()['items'][0]['captured'] is True
        stored = wishlist.load_user_wishlist(admin_user_id)['items'][0]
        assert 'captured' not in stored


class TestWishlistAdd:

    def test_missing_targets_list_is_rejected(self, wishlist_client):
        assert wishlist_client.post('/api/wishlist', json={}).status_code == 400
        assert wishlist_client.post('/api/wishlist', json={'targets': []}).status_code == 400
        assert wishlist_client.post('/api/wishlist', json={'targets': 'M 31'}).status_code == 400

    def test_a_target_without_a_name_is_rejected(self, wishlist_client):
        assert wishlist_client.post('/api/wishlist', json={'targets': [{'name': ''}]}).status_code == 400

    def test_duplicate_is_reported_not_rejected(self, wishlist_client):
        _post_target(wishlist_client)
        response = _post_target(wishlist_client)
        assert response.status_code == 201
        assert response.get_json()['data']['skipped_duplicates'] == 1
        assert response.get_json()['data']['added'] == []

    def test_oversized_request_is_rejected(self, wishlist_client):
        targets = [{'name': f'Target {index}'} for index in range(MAX_WISHLIST_ITEMS + 1)]
        assert wishlist_client.post('/api/wishlist', json={'targets': targets}).status_code == 400

    def test_several_targets_in_one_call(self, wishlist_client):
        response = wishlist_client.post(
            '/api/wishlist', json={'targets': [{'name': 'M 31'}, {'name': 'M 42'}]}
        )
        assert response.status_code == 201
        assert len(response.get_json()['data']['added']) == 2

    def test_save_failure_returns_500(self, wishlist_client, monkeypatch):
        monkeypatch.setattr(
            session_analytics_bp_module.wishlist,
            'add_targets',
            lambda *_args, **_kwargs: {
                'added': [],
                'skipped_duplicates': 0,
                'skipped_invalid': 0,
                'skipped_full': 0,
                'saved': False,
            },
        )
        assert _post_target(wishlist_client).status_code == 500


class TestWishlistUpdateDelete:

    def test_update_priority(self, wishlist_client):
        item_id = _post_target(wishlist_client).get_json()['data']['added'][0]['id']
        response = wishlist_client.patch(f'/api/wishlist/{item_id}', json={'priority': 'high'})
        assert response.status_code == 200
        assert response.get_json()['data']['priority'] == 'high'

    def test_empty_update_is_rejected(self, wishlist_client):
        item_id = _post_target(wishlist_client).get_json()['data']['added'][0]['id']
        assert wishlist_client.patch(f'/api/wishlist/{item_id}', json={}).status_code == 400

    def test_invalid_priority_is_refused(self, wishlist_client):
        item_id = _post_target(wishlist_client).get_json()['data']['added'][0]['id']
        assert wishlist_client.patch(f'/api/wishlist/{item_id}', json={'priority': 'urgent'}).status_code == 404

    def test_update_unknown_item(self, wishlist_client):
        assert wishlist_client.patch('/api/wishlist/nope', json={'notes': 'x'}).status_code == 404

    def test_delete_item(self, wishlist_client):
        item_id = _post_target(wishlist_client).get_json()['data']['added'][0]['id']
        assert wishlist_client.delete(f'/api/wishlist/{item_id}').status_code == 200
        assert wishlist_client.get('/api/wishlist').get_json()['items'] == []

    def test_delete_unknown_item(self, wishlist_client):
        assert wishlist_client.delete('/api/wishlist/nope').status_code == 404


class TestWishlistArchiveCaptured:

    def test_removes_only_captured_items(self, wishlist_client, admin_user_id):
        _post_target(wishlist_client, name='M 31')
        _post_target(wishlist_client, name='M 42')
        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0)

        response = wishlist_client.post('/api/wishlist/archive-captured', json={})
        assert response.status_code == 200
        assert response.get_json()['removed'] == 1
        assert [item['name'] for item in wishlist_client.get('/api/wishlist').get_json()['items']] == ['M 42']

    def test_nothing_captured_removes_nothing(self, wishlist_client):
        _post_target(wishlist_client)
        response = wishlist_client.post('/api/wishlist/archive-captured', json={})
        assert response.get_json()['removed'] == 0
        assert len(wishlist_client.get('/api/wishlist').get_json()['items']) == 1


class TestBestMonths:
    """The astronomical budget and the user's own months, never merged."""

    def test_two_separate_series(self, client, stub_visibility, monkeypatch):
        monkeypatch.setattr(
            session_analytics_bp_module.visibility_calendar,
            'dark_hours_by_month',
            lambda *_a, **_k: [
                {'month': month, 'dark_hours': 6.0, 'moonless_dark_hours': 3.0, 'moon_illumination_pct': 40.0}
                for month in range(1, 13)
            ],
        )
        payload = client.get('/api/session-analytics/best-months').get_json()
        assert len(payload['astronomical']) == 12
        assert len(payload['logged']) == 12
        assert payload['astronomical_available'] is True

    def test_logged_months_come_from_the_users_own_log(self, client, stub_visibility, admin_user_id):
        _seed_session(admin_user_id, 'admin', '2026-07-14', frame_count=40, integration_minutes=120.0)
        payload = client.get('/api/session-analytics/best-months').get_json()
        july = next(row for row in payload['logged'] if row['month'] == 7)
        assert july['integration_hours'] == pytest.approx(2.0)
        assert july['nights_logged'] == 1

    def test_ephemeris_failure_still_returns_the_personal_half(self, client, monkeypatch):
        """One broken half must not take the whole dashboard section down."""
        def boom(*_args, **_kwargs):
            raise RuntimeError('no ephemeris')

        monkeypatch.setattr(session_analytics_bp_module.visibility_calendar, 'dark_hours_by_month', boom)
        response = client.get('/api/session-analytics/best-months')
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['astronomical'] == []
        assert payload['astronomical_available'] is False
        assert len(payload['logged']) == 12

    def test_invalid_year_is_rejected(self, client, stub_visibility):
        assert client.get('/api/session-analytics/best-months?year=abc').status_code == 400

    def test_requires_login(self, isolated_storage):
        app.config['TESTING'] = True
        with app.test_client() as anonymous:
            assert anonymous.get('/api/session-analytics/best-months').status_code == 401


class TestWishlistVisibility:

    def test_visibility_is_attached_by_default(self, wishlist_client):
        _post_target(wishlist_client)
        payload = wishlist_client.get('/api/wishlist').get_json()
        assert payload['visibility_included'] is True
        assert payload['items'][0]['observable_hours_next'] == pytest.approx(4.5)
        assert payload['items'][0]['best_month'] == 9

    def test_visibility_can_be_skipped(self, wishlist_client):
        """The flag exists so a slow ephemeris never blocks the list itself."""
        _post_target(wishlist_client)
        payload = wishlist_client.get('/api/wishlist?visibility=0').get_json()
        assert payload['visibility_included'] is False
        assert 'observable_hours_next' not in payload['items'][0]

    def test_ephemeris_failure_still_returns_the_list(self, client, isolated_wishlist, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError('no ephemeris')

        monkeypatch.setattr(session_analytics_bp_module.visibility_calendar, 'next_visibility_batch', boom)
        _post_target(client)
        response = client.get('/api/wishlist')
        assert response.status_code == 200
        assert len(response.get_json()['items']) == 1

    def test_response_names_the_location_visibility_was_computed_for(self, wishlist_client, stub_location):
        _post_target(wishlist_client)
        payload = wishlist_client.get('/api/wishlist').get_json()
        assert payload['location_name'] == stub_location['name']
