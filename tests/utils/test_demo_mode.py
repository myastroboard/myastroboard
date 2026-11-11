"""Unit tests for utils/demo_mode.py: the DEMO_MODE switch, the write guard and the demo account."""

import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from utils import demo_mode
from utils.auth import ROLE_USER, user_manager


@pytest.fixture
def demo_on(monkeypatch):
    """Run the test with DEMO_MODE on and the default demo username."""
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.delenv('DEMO_USERNAME', raising=False)


@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', ' yes ', 'on'])
def test_is_demo_mode_accepts_truthy_values(monkeypatch, value):
    """Every usual spelling of "on" turns demo mode on."""
    monkeypatch.setenv('DEMO_MODE', value)
    assert demo_mode.is_demo_mode() is True


@pytest.mark.parametrize('value', ['', '0', 'false', 'off', 'no', 'maybe'])
def test_is_demo_mode_rejects_other_values(monkeypatch, value):
    """Anything else, including an unset variable, keeps demo mode off."""
    monkeypatch.setenv('DEMO_MODE', value)
    assert demo_mode.is_demo_mode() is False


def test_is_demo_mode_off_when_unset(monkeypatch):
    """A normal install, without the variable, is never a demo."""
    monkeypatch.delenv('DEMO_MODE', raising=False)
    assert demo_mode.is_demo_mode() is False


def test_demo_username_defaults_and_override(monkeypatch):
    """The demo account is 'demo' unless DEMO_USERNAME names another one."""
    monkeypatch.delenv('DEMO_USERNAME', raising=False)
    assert demo_mode.demo_username() == 'demo'
    monkeypatch.setenv('DEMO_USERNAME', '  showcase ')
    assert demo_mode.demo_username() == 'showcase'
    monkeypatch.setenv('DEMO_USERNAME', '   ')
    assert demo_mode.demo_username() == 'demo'


def test_is_demo_username_ignores_case(demo_on):
    """Sign-in usernames are case-insensitive, so the demo account check is too."""
    assert demo_mode.is_demo_username('Demo')
    assert not demo_mode.is_demo_username('admin')
    assert not demo_mode.is_demo_username(None)


def test_is_demo_session_requires_demo_mode_and_demo_account(monkeypatch):
    """Only the demo account's session, with demo mode on, counts as a demo session."""
    monkeypatch.delenv('DEMO_USERNAME', raising=False)
    with app.test_request_context('/'):
        from flask import session

        session['username'] = 'demo'
        monkeypatch.setenv('DEMO_MODE', 'false')
        assert demo_mode.is_demo_session() is False
        monkeypatch.setenv('DEMO_MODE', 'true')
        assert demo_mode.is_demo_session() is True
        session['username'] = 'admin'
        assert demo_mode.is_demo_session() is False


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'OPTIONS'])
def test_blocked_demo_write_lets_reads_through(demo_on, method):
    """Reading is never blocked, whatever the endpoint."""
    with app.test_request_context('/'):
        from flask import session

        session['username'] = 'demo'
        assert demo_mode.blocked_demo_write(method, 'astrodex.add_astrodex_item') is False


def test_blocked_demo_write_blocks_writes_from_demo_session(demo_on):
    """A write from the demo session is blocked, an allowlisted calculation is not."""
    with app.test_request_context('/'):
        from flask import session

        session['username'] = 'demo'
        assert demo_mode.blocked_demo_write('POST', 'astrodex.add_astrodex_item') is True
        assert demo_mode.blocked_demo_write('DELETE', 'plan_my_night.clear_plan_my_night') is True
        assert demo_mode.blocked_demo_write('POST', 'equipment.calculate_fov') is False


def test_blocked_demo_write_leaves_other_accounts_alone(demo_on):
    """The maintainer's own account keeps writing on a demo instance."""
    with app.test_request_context('/'):
        from flask import session

        session['username'] = 'admin'
        assert demo_mode.blocked_demo_write('POST', 'astrodex.add_astrodex_item') is False


def test_allowed_write_endpoints_all_exist():
    """Every allowlisted endpoint names a real route, so a rename cannot silently block it."""
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    missing = demo_mode.DEMO_ALLOWED_WRITE_ENDPOINTS - endpoints
    assert not missing, f"Unknown endpoints in DEMO_ALLOWED_WRITE_ENDPOINTS: {sorted(missing)}"


def test_demo_read_only_response_shape():
    """Blocked writes answer 403 with the code and translation key the frontend reads."""
    with app.test_request_context('/'):
        response, status = demo_mode.demo_read_only_response()
    assert status == 403
    body = response.get_json()
    assert body['error'] == 'demo_read_only'
    assert body['error_key'] == 'demo.read_only'


def test_get_or_create_demo_user_creates_a_regular_account_once(demo_on):
    """The demo account is created on first use as a 'user' with the wizard done, then reused."""
    assert user_manager.get_user_by_username('demo') is None
    user = demo_mode.get_or_create_demo_user(user_manager)
    assert user is not None
    assert user.role == ROLE_USER
    assert user_manager.get_user_preferences(user.user_id)['wizard'] == {'completed': True, 'skipped': False}

    again = demo_mode.get_or_create_demo_user(user_manager)
    assert again.user_id == user.user_id


def test_get_or_create_demo_user_keeps_an_existing_account(demo_on):
    """An account the maintainer prepared keeps its role and preferences."""
    prepared = user_manager.create_user('demo', 'prepared-password', 'read-only')
    user = demo_mode.get_or_create_demo_user(user_manager)
    assert user.user_id == prepared.user_id
    assert user.role == 'read-only'


def test_get_or_create_demo_user_survives_a_concurrent_creation(demo_on, monkeypatch):
    """When another worker creates the account first, the existing row is returned."""
    created = user_manager.create_user('demo', 'other-worker', ROLE_USER)
    calls = {'n': 0}
    real_lookup = user_manager.get_user_by_username

    def lookup_missing_first(username):
        calls['n'] += 1
        return None if calls['n'] == 1 else real_lookup(username)

    monkeypatch.setattr(user_manager, 'get_user_by_username', lookup_missing_first)
    user = demo_mode.get_or_create_demo_user(user_manager)
    assert user.user_id == created.user_id


def test_get_or_create_demo_user_returns_none_when_creation_fails(demo_on, monkeypatch):
    """No account and no way to create one leaves the visitor on the sign-in page."""
    monkeypatch.setattr(user_manager, 'get_user_by_username', lambda username: None)

    def refuse(*args, **kwargs):
        raise ValueError('refused')

    monkeypatch.setattr(user_manager, 'create_user', refuse)
    assert demo_mode.get_or_create_demo_user(user_manager) is None
    with app.test_request_context('/'):
        assert demo_mode.sign_in_demo_visitor(user_manager) is None


def test_get_or_create_demo_user_tolerates_a_wizard_update_failure(demo_on, monkeypatch):
    """A failure to mark the wizard as done does not prevent the demo from opening."""

    def refuse(*args, **kwargs):
        raise ValueError('refused')

    monkeypatch.setattr(user_manager, 'update_user_preferences', refuse)
    assert demo_mode.get_or_create_demo_user(user_manager) is not None


def test_sign_in_demo_visitor_sets_a_session_without_touching_the_account(demo_on):
    """A visit fills the session but does not stamp last_login on the shared account."""
    user = demo_mode.get_or_create_demo_user(user_manager)
    before = user_manager.get_user_by_id(user.user_id).last_login
    with app.test_request_context('/'):
        from flask import session

        session['stale'] = 'value'
        signed_in = demo_mode.sign_in_demo_visitor(user_manager)
        assert signed_in.user_id == user.user_id
        assert session['username'] == 'demo'
        assert session['role'] == user.role
        assert 'stale' not in session
        assert session.permanent is False
    assert user_manager.get_user_by_id(user.user_id).last_login == before


def test_session_preferences_merge_and_lock_server_state():
    """Visitor overrides accumulate in the session, minus the keys that hold server state."""
    with app.test_request_context('/'):
        assert demo_mode.session_preferences() == {}
        demo_mode.store_session_preferences({'theme_mode': 'dark', 'location': {'active_location_id': 'x'}})
        stored = demo_mode.store_session_preferences({'density': 'compact', 'notifications': {}})
        assert stored == {'theme_mode': 'dark', 'density': 'compact'}
        assert demo_mode.session_preferences() == stored


def test_session_preferences_ignores_a_corrupt_session_value():
    """A non-dict value in the session is treated as no override at all."""
    with app.test_request_context('/'):
        from flask import session

        session[demo_mode.DEMO_PREFERENCES_SESSION_KEY] = 'garbage'
        assert demo_mode.session_preferences() == {}


def test_visitor_preferences_drop_the_account_language_until_the_visitor_picks_one():
    """A shared account does not impose its language; the visitor's own choice wins."""
    account = {'language': 'en', 'theme_mode': 'auto'}
    with app.test_request_context('/'):
        assert demo_mode.visitor_preferences(account) == {'theme_mode': 'auto'}
        demo_mode.store_session_preferences({'language': 'fr', 'theme_mode': 'dark'})
        assert demo_mode.visitor_preferences(account) == {'language': 'fr', 'theme_mode': 'dark'}
    assert account == {'language': 'en', 'theme_mode': 'auto'}
