"""Route-level tests for the public demo mode (DEMO_MODE=true).

A visitor is signed in automatically on the shared demo account, reads everything,
keeps UI preferences in their own session, and every write is refused with a 403.
"""

import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from utils.auth import user_manager


@pytest.fixture
def demo_client(monkeypatch):
    """A fresh visitor on an instance running with DEMO_MODE on."""
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.delenv('DEMO_USERNAME', raising=False)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def demo_visitor(demo_client):
    """A visitor who already opened the demo, so the session is the demo account."""
    response = demo_client.get('/')
    assert response.status_code == 200
    return demo_client


def test_index_signs_a_visitor_in_on_the_demo_account(demo_client):
    """Opening the app on a demo lands in the dashboard, with the demo banner, instead of /login."""
    response = demo_client.get('/')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="demo-banner"' in page
    assert '<meta name="demo-mode" content="1">' in page
    status = demo_client.get('/api/auth/status').get_json()
    assert status['authenticated'] is True
    assert status['username'] == 'demo'
    assert status['demo_mode'] is True


def test_index_without_demo_mode_still_redirects_to_login(client, monkeypatch):
    """A normal install keeps asking for a sign-in and never shows the banner."""
    monkeypatch.delenv('DEMO_MODE', raising=False)
    response = client.get('/')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_index_falls_back_to_login_when_the_demo_account_cannot_be_made(demo_client, monkeypatch):
    """If the demo account cannot be created, the visitor gets the normal sign-in page."""
    from utils import demo_mode

    monkeypatch.setattr(demo_mode, 'get_or_create_demo_user', lambda um: None)
    response = demo_client.get('/')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_login_page_leads_into_the_demo(demo_client):
    """/login on a demo sends the visitor into the app (which signs them in)."""
    response = demo_client.get('/login')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/')


def test_login_page_with_signin_shows_the_form(demo_client):
    """/login?signin keeps the real sign-in form reachable for the maintainer."""
    response = demo_client.get('/login?signin=1')
    assert response.status_code == 200


def test_status_flag_is_false_for_another_account(client_admin, monkeypatch):
    """The maintainer signed in on the demo instance is not treated as a demo visitor."""
    monkeypatch.setenv('DEMO_MODE', 'true')
    status = client_admin.get('/api/auth/status').get_json()
    assert status['demo_mode'] is False


@pytest.mark.parametrize(
    ('method', 'path'),
    [
        ('post', '/api/astrodex/items'),
        ('delete', '/api/plan-my-night/clear'),
        ('post', '/api/locations/active'),
        ('post', '/api/push/subscribe'),
        ('post', '/api/auth/change-password'),
        ('post', '/api/translate/on-demand'),
    ],
)
def test_writes_from_the_demo_session_are_refused(demo_visitor, method, path):
    """Every write from the demo account answers the demo 403, before the route runs."""
    response = getattr(demo_visitor, method)(path, json={})
    assert response.status_code == 403
    assert response.get_json()['error'] == 'demo_read_only'


def test_reads_from_the_demo_session_work(demo_visitor):
    """Reading routes answer normally for a demo visitor."""
    response = demo_visitor.get('/api/auth/preferences')
    assert response.status_code == 200


def test_allowlisted_calculation_runs_for_the_demo_session(demo_visitor):
    """A pure calculation (coordinate conversion) is not a write and still answers."""
    response = demo_visitor.post('/api/convert-coordinates', json={})
    assert response.get_json().get('error') != 'demo_read_only'


def test_writes_from_another_account_are_not_blocked(client_admin, monkeypatch):
    """The maintainer's account keeps full write access on a demo instance."""
    monkeypatch.setenv('DEMO_MODE', 'true')
    response = client_admin.post('/api/astrodex/items', json={})
    assert (response.get_json() or {}).get('error') != 'demo_read_only'


def test_preferences_stay_in_the_visitor_session(demo_client, monkeypatch):
    """A visitor's theme choice is theirs alone: saved in their session, not on the shared account."""
    demo_client.get('/')
    demo_user = user_manager.get_user_by_username('demo')

    response = demo_client.put('/api/auth/preferences', json={'preferences': {'theme_mode': 'dark', 'bogus': 1}})
    assert response.status_code == 200
    assert response.get_json()['preferences']['theme_mode'] == 'dark'
    assert demo_client.get('/api/auth/preferences').get_json()['preferences']['theme_mode'] == 'dark'

    # The shared account itself is unchanged, and another visitor gets the default
    assert user_manager.get_user_preferences(demo_user.user_id)['theme_mode'] == 'auto'
    with app.test_client() as other:
        other.get('/')
        assert other.get('/api/auth/preferences').get_json()['preferences']['theme_mode'] == 'auto'


def test_preferences_cannot_override_server_state(demo_visitor):
    """A visitor cannot point the shared account at another location through preferences."""
    demo_visitor.put('/api/auth/preferences', json={'preferences': {'location': {'active_location_id': 'evil'}}})
    with demo_visitor.session_transaction() as sess:
        assert 'location' not in sess.get('demo_preferences', {})


def test_invalid_preferences_are_rejected_for_the_demo_session(demo_visitor):
    """Session-scoped preferences are validated exactly like stored ones."""
    response = demo_visitor.put('/api/auth/preferences', json={'preferences': {'theme_mode': 'neon'}})
    assert response.status_code == 400
    assert response.get_json()['error_key'] == 'settings.pref_invalid_theme'


def test_non_dict_preferences_are_rejected_for_the_demo_session(demo_visitor):
    """A preferences payload that is not an object is a bad request."""
    response = demo_visitor.put('/api/auth/preferences', json={'preferences': ['dark']})
    assert response.status_code == 400


def test_password_sign_in_on_the_demo_account_is_refused(demo_client):
    """The demo account is never signed in with a password, even a correct one."""
    user_manager.create_user('demo', 'known-password', 'user')
    response = demo_client.post('/api/auth/login', json={'username': 'demo', 'password': 'known-password'})
    assert response.status_code == 403
    assert response.get_json()['error_key'] == 'demo.signin_refused'


def test_default_password_sign_in_is_refused_on_a_demo(demo_client):
    """admin/admin on a public demo would hand the instance to anyone: it is refused."""
    response = demo_client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert response.status_code == 403
    assert response.get_json()['error_key'] == 'demo.signin_refused'


def test_real_account_signs_in_on_a_demo(demo_client):
    """An account with its own password signs in normally on a demo instance."""
    user_manager.create_user('maintainer', 'a-strong-password', 'admin')
    response = demo_client.post('/api/auth/login', json={'username': 'maintainer', 'password': 'a-strong-password'})
    assert response.status_code == 200
    assert response.get_json()['username'] == 'maintainer'


def test_logout_then_return_signs_in_again(demo_visitor):
    """Logging out of the demo is allowed; the next visit simply opens the demo again."""
    assert demo_visitor.post('/api/auth/logout').status_code == 200
    assert demo_visitor.get('/api/auth/status').get_json()['authenticated'] is False
    assert demo_visitor.get('/').status_code == 200
    assert demo_visitor.get('/api/auth/status').get_json()['authenticated'] is True


def test_demo_preferences_carry_no_language_until_the_visitor_picks_one(demo_visitor):
    """The browser language applies on a demo; a language picked by the visitor is then kept."""
    assert 'language' not in demo_visitor.get('/api/auth/preferences').get_json()['preferences']
    demo_visitor.put('/api/auth/preferences', json={'preferences': {'language': 'fr'}})
    assert demo_visitor.get('/api/auth/preferences').get_json()['preferences']['language'] == 'fr'
