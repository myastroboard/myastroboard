"""API tests for the My Progress blueprint (v1.9): year in review, badges, challenges.

These cover what the pure engines cannot: authentication, self-scoping, parameter
validation, the "badges seen" preference round trip and the fallbacks of the default
year. The aggregates themselves are tested in tests/observation/.
"""

import sys
import types
import uuid

import pytest

from observation import astrodex, observation_sessions
from utils.auth import user_manager

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from blueprints import progress as progress_module

LOCATION = {
    'id': 'loc-test',
    'name': 'Test Site',
    'latitude': 48.0,
    'longitude': 2.0,
    'timezone': 'Europe/Paris',
    'horizon_profile': [],
}

READ_ROUTES = (
    '/api/session-analytics/year-review',
    '/api/achievements',
    '/api/achievements/challenges',
    '/api/achievements/missing-tonight?catalogue=Messier',
)


@pytest.fixture
def stub_location(monkeypatch):
    monkeypatch.setattr(progress_module, '_resolve_active_location', lambda: LOCATION)
    return LOCATION


@pytest.fixture
def stub_challenges(monkeypatch):
    """Keep the ephemeris out of the route tests: the engines have their own tests."""
    seen = {}

    def seasonal(location, today, captured):
        seen['seasonal'] = captured
        return {'season': 'autumn', 'hemisphere': 'north', 'sampled_nights': [], 'challenges': []}

    def marathon(location, today, captured):
        return {'year': today.year + 1, 'reachable': 100, 'total': 109, 'sequence': []}

    def missing(catalogue, location, today, captured, limit=12):
        seen['missing'] = (catalogue, set(captured), limit)
        return [{'target_id': 'dso-x', 'name': 'M 1', 'observable_hours': 3.0}]

    monkeypatch.setattr(progress_module.challenges, 'seasonal_challenges', seasonal)
    monkeypatch.setattr(progress_module.challenges, 'messier_marathon', marathon)
    monkeypatch.setattr(progress_module.challenges, 'missing_tonight', missing)
    return seen


def _login(test_client, username):
    user = user_manager.get_user_by_username(username)
    assert user is not None
    with test_client.session_transaction() as session:
        session['user_id'] = user.user_id
        session['username'] = user.username
        session['role'] = user.role
    return user


@pytest.fixture
def client(stub_location, stub_challenges):
    app.config['TESTING'] = True
    with app.test_client() as test_client:
        _login(test_client, 'admin')
        yield test_client


@pytest.fixture
def admin_user_id():
    user = user_manager.get_user_by_username('admin')
    assert user is not None
    return user.user_id


def _seed(user_id, username, day, name='M 31', **fields):
    session = observation_sessions.create_session(user_id, username, {'date': day})
    assert session is not None
    payload = {'name': name, 'catalogue': 'Messier', 'type': 'Galaxy', 'constellation': 'And'}
    payload.update(fields)
    entry = observation_sessions.add_entry(user_id, session['id'], payload)
    assert entry is not None
    return session


class TestAuth:
    def test_routes_require_login(self):
        app.config['TESTING'] = True
        with app.test_client() as anonymous:
            for route in READ_ROUTES:
                assert anonymous.get(route).status_code == 401, route
            assert anonymous.post('/api/achievements/seen', json={'ids': []}).status_code == 401

    def test_read_only_account_may_read_and_mark_seen(self, stub_location, stub_challenges):
        app.config['TESTING'] = True
        username = f'ro_{uuid.uuid4().hex[:8]}'
        user_manager.create_user(username, 'test123', 'read-only')
        with app.test_client() as test_client:
            _login(test_client, username)
            for route in READ_ROUTES:
                assert test_client.get(route).status_code == 200, route
            assert test_client.post('/api/achievements/seen', json={'ids': ['first_galaxy']}).status_code == 200


class TestYearReview:
    def test_empty_account(self, client):
        payload = client.get('/api/session-analytics/year-review').get_json()
        assert payload['has_data'] is False
        assert payload['available_years'] == []
        assert len(payload['today']) == 10

    def test_logged_year(self, client, admin_user_id):
        _seed(admin_user_id, 'admin', '2025-08-02', frame_count=10, integration_minutes=100.0)
        payload = client.get('/api/session-analytics/year-review?year=2025').get_json()
        assert payload['year'] == 2025
        assert payload['has_data'] is True
        assert payload['totals']['integration_minutes'] == pytest.approx(100.0)
        assert payload['target_of_year']['name'] == 'M 31'

    def test_default_year_falls_back_to_the_latest_year_with_data(self, client, admin_user_id):
        _seed(admin_user_id, 'admin', '2019-08-02', frame_count=10, integration_minutes=100.0)
        payload = client.get('/api/session-analytics/year-review').get_json()
        assert payload['year'] == 2019

    def test_an_explicit_year_is_kept_even_without_data(self, client, admin_user_id):
        _seed(admin_user_id, 'admin', '2019-08-02', frame_count=10, integration_minutes=100.0)
        payload = client.get('/api/session-analytics/year-review?year=2020').get_json()
        assert payload['year'] == 2020
        assert payload['has_data'] is False
        assert payload['available_years'] == [2019]

    def test_invalid_year_is_rejected(self, client):
        assert client.get('/api/session-analytics/year-review?year=abc').status_code == 400
        assert client.get('/api/session-analytics/year-review?year=99999').status_code == 400

    def test_another_users_log_is_never_included(self, client):
        _seed('someone-else', 'someone-else', '2025-08-02', frame_count=40, integration_minutes=600.0)
        payload = client.get('/api/session-analytics/year-review?year=2025').get_json()
        assert payload['has_data'] is False


class TestAchievements:
    def test_empty_account(self, client):
        payload = client.get('/api/achievements').get_json()
        assert payload['enabled'] is True
        assert payload['summary']['earned'] == 0
        assert payload['next_within_reach'] == []
        assert payload['groups'][0] == 'firsts'

    def test_logged_capture_earns_a_badge_announced_once(self, client, admin_user_id):
        _seed(admin_user_id, 'admin', '2026-01-10', frame_count=10, integration_minutes=60.0)
        payload = client.get('/api/achievements').get_json()
        first = next(badge for badge in payload['badges'] if badge['id'] == 'first_galaxy')
        assert first['earned'] is True
        assert first['earned_on'] == '2026-01-10'
        assert first['new'] is True
        assert 'first_galaxy' in payload['summary']['new_ids']

        response = client.post('/api/achievements/seen', json={'ids': ['first_galaxy', 'not-a-badge']})
        assert response.status_code == 200
        assert response.get_json()['seen'] == ['first_galaxy']

        again = client.get('/api/achievements').get_json()
        assert next(badge for badge in again['badges'] if badge['id'] == 'first_galaxy')['new'] is False
        assert user_manager.get_user_preferences(admin_user_id)['achievements_seen'] == ['first_galaxy']

    def test_seen_ids_accumulate(self, client, admin_user_id):
        client.post('/api/achievements/seen', json={'ids': ['first_galaxy']})
        client.post('/api/achievements/seen', json={'ids': ['first_nebula']})
        assert user_manager.get_user_preferences(admin_user_id)['achievements_seen'] == [
            'first_galaxy',
            'first_nebula',
        ]

    def test_seen_requires_a_list(self, client):
        assert client.post('/api/achievements/seen', json={'ids': 'first_galaxy'}).status_code == 400
        assert client.post('/api/achievements/seen', json={}).status_code == 400

    def test_disabled_preference_is_reported(self, client, admin_user_id):
        user_manager.update_user_preferences(admin_user_id, {'achievements_enabled': False})
        assert client.get('/api/achievements').get_json()['enabled'] is False

    def test_astrodex_item_counts_as_a_capture(self, client, admin_user_id):
        astrodex.create_astrodex_item(admin_user_id, {'name': 'M 42', 'type': 'Nebula'}, username='admin')
        payload = client.get('/api/achievements').get_json()
        assert payload['objects_captured'] == 1


class TestChallenges:
    def test_challenges_receive_the_captured_set(self, client, admin_user_id, stub_challenges):
        _seed(admin_user_id, 'admin', '2026-01-10', frame_count=10)
        payload = client.get('/api/achievements/challenges').get_json()
        assert payload['location_id'] == LOCATION['id']
        assert payload['seasonal']['season'] == 'autumn'
        assert payload['marathon']['reachable'] == 100
        assert len(stub_challenges['seasonal']) == 1

    def test_an_ephemeris_failure_leaves_the_other_half(self, client, monkeypatch):
        def broken(*_args, **_kwargs):
            raise RuntimeError('no ephemeris')

        monkeypatch.setattr(progress_module.challenges, 'messier_marathon', broken)
        payload = client.get('/api/achievements/challenges').get_json()
        assert payload['marathon'] is None
        assert payload['seasonal'] is not None


class TestMissingTonight:
    def test_known_catalogue(self, client, stub_challenges):
        payload = client.get('/api/achievements/missing-tonight?catalogue=Caldwell&limit=500').get_json()
        assert payload['catalogue'] == 'Caldwell'
        assert payload['targets'][0]['name'] == 'M 1'
        assert stub_challenges['missing'][2] == 30

    def test_unknown_catalogue_is_rejected(self, client):
        assert client.get('/api/achievements/missing-tonight?catalogue=OpenNGC').status_code == 400
        assert client.get('/api/achievements/missing-tonight').status_code == 400

    def test_invalid_limit_is_rejected(self, client):
        assert client.get('/api/achievements/missing-tonight?catalogue=Messier&limit=x').status_code == 400


class TestPresetsAndCatalogues:
    def test_dark_site_badge_from_the_location_preset(self, client, admin_user_id, monkeypatch):
        """Sessions store only the preset id; its Bortle class comes from the configuration."""
        session = _seed(admin_user_id, 'admin', '2026-01-10', frame_count=10)
        observation_sessions.update_session(admin_user_id, session['id'], {'location_id': 'loc-dark'})
        monkeypatch.setattr(progress_module, 'get_all_locations', lambda config: [{'id': 'loc-dark', 'bortle': 2}])
        payload = client.get('/api/achievements').get_json()
        assert next(badge for badge in payload['badges'] if badge['id'] == 'dark_site')['earned'] is True

    def test_unreadable_presets_only_cost_the_dark_site_badge(self, client, admin_user_id, monkeypatch):
        _seed(admin_user_id, 'admin', '2026-01-10', frame_count=10)

        def broken(_config):
            raise RuntimeError('no config')

        monkeypatch.setattr(progress_module, 'get_all_locations', broken)
        response = client.get('/api/achievements')
        assert response.status_code == 200
        assert next(badge for badge in response.get_json()['badges'] if badge['id'] == 'first_galaxy')['earned']

    def test_catalogue_rows_carry_picture_filenames(self, client, admin_user_id, monkeypatch):
        _seed(admin_user_id, 'admin', '2026-01-10', frame_count=10)
        monkeypatch.setattr(progress_module.achievements, 'catalogue_totals', lambda: {'Messier': 3})
        rows = client.get('/api/achievements').get_json()['catalogues']
        assert rows[0]['catalogue'] == 'Messier'
        assert rows[0]['captured'] == 1
        assert isinstance(rows[0]['pictures'], list)


class TestDemoMode:
    def test_seen_badges_stay_in_the_visitor_session(self, client, admin_user_id, monkeypatch):
        """The demo account is shared: a visitor's seen badges never reach the account."""
        stored = {}
        monkeypatch.setattr(progress_module._demo_mode, 'is_demo_session', lambda: True)
        monkeypatch.setattr(progress_module._demo_mode, 'visitor_preferences', lambda prefs: {**prefs, **stored})
        monkeypatch.setattr(progress_module._demo_mode, 'store_session_preferences', stored.update)
        response = client.post('/api/achievements/seen', json={'ids': ['first_galaxy']})
        assert response.get_json()['seen'] == ['first_galaxy']
        assert stored == {'achievements_seen': ['first_galaxy']}
        assert user_manager.get_user_preferences(admin_user_id)['achievements_seen'] == []

    def test_nothing_is_written_when_nothing_is_new(self, client, monkeypatch):
        client.post('/api/achievements/seen', json={'ids': ['first_galaxy']})

        def must_not_write(*_args, **_kwargs):
            raise AssertionError('preferences written although nothing changed')

        monkeypatch.setattr(progress_module.user_manager, 'update_user_preferences', must_not_write)
        response = client.post('/api/achievements/seen', json={'ids': ['first_galaxy']})
        assert response.status_code == 200


class TestServerErrors:
    @pytest.mark.parametrize(
        ('method', 'route'),
        [
            ('get', '/api/session-analytics/year-review'),
            ('get', '/api/achievements'),
            ('get', '/api/achievements/challenges'),
            ('get', '/api/achievements/missing-tonight?catalogue=Messier'),
        ],
    )
    def test_unexpected_failure_returns_500(self, client, monkeypatch, method, route):
        def broken(_user):
            raise RuntimeError('storage down')

        monkeypatch.setattr(progress_module, '_user_facts', broken)
        response = getattr(client, method)(route)
        assert response.status_code == 500
        assert response.get_json() == {'error': 'Internal server error'}

    def test_seen_failure_returns_500(self, client, monkeypatch):
        def broken(_user):
            raise RuntimeError('storage down')

        monkeypatch.setattr(progress_module, '_user_preferences', broken)
        assert client.post('/api/achievements/seen', json={'ids': []}).status_code == 500

    def test_seasonal_failure_leaves_the_marathon(self, client, monkeypatch):
        def broken(*_args, **_kwargs):
            raise RuntimeError('no ephemeris')

        monkeypatch.setattr(progress_module.challenges, 'seasonal_challenges', broken)
        payload = client.get('/api/achievements/challenges').get_json()
        assert payload['seasonal'] is None
        assert payload['marathon'] is not None
