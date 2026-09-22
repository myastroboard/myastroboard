"""Flask test client tests for the authentication blueprint.

Covers the full login state machine introduced with two-factor authentication and
local/global account scopes: /api/auth/login, /api/auth/login/verify-2fa,
/api/auth/2fa/*, /api/auth/security-settings and DELETE /api/users/<id>/2fa.
"""

import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app
from blueprints import auth as auth_bp_mod
from utils import auth as auth_mod
from utils import security_settings as security_settings_mod
from utils.auth import user_manager

# A client address that is never inside the loopback ranges nor the LAN block the
# tests configure, so it exercises the "untrusted network" arcs.
UNTRUSTED_IP = '203.0.113.5'
TRUSTED_LAN = '192.168.1.0/24'
TRUSTED_IP = '192.168.1.42'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Unauthenticated test client."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def client_admin():
    """Admin-authenticated test client (the bootstrap admin account)."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        admin = user_manager.get_user_by_username('admin')
        assert admin is not None
        with c.session_transaction() as sess:
            sess['user_id'] = admin.user_id
            sess['username'] = admin.username
            sess['role'] = admin.role
        yield c


@pytest.fixture
def security_settings():
    """Drive the module cache directly so no security_settings.json is written.

    Returns a setter; the cache is restored afterwards so tests stay independent.
    """
    original = security_settings_mod._cache

    def configure(trusted_networks=None, two_factor_enabled=False):
        security_settings_mod._cache = {
            'trusted_networks': list(trusted_networks or []),
            'two_factor_enabled': two_factor_enabled,
        }
        return security_settings_mod._cache

    configure()
    yield configure
    security_settings_mod._cache = original


@pytest.fixture
def make_user():
    """Create throwaway accounts and remove them again after the test."""
    created = []

    def _make(password='test-password', role=auth_mod.ROLE_USER, account_scope=None, with_totp=False):
        username = f"pytest-{uuid.uuid4().hex[:10]}"
        user = user_manager.create_user(username, password, role, account_scope)
        secret = None
        if with_totp:
            secret = user_manager.start_totp_setup(user.user_id).totp_secret
            user_manager.confirm_totp_setup(user.user_id, pyotp.TOTP(secret).now())
            user = user_manager.get_user_by_id(user.user_id)
        created.append(user.user_id)
        return user, password, secret

    yield _make

    for user_id in created:
        try:
            user_manager.delete_user(user_id)
        except ValueError:
            pass  # already removed by the test itself


def login(client, username, password, remote_addr=UNTRUSTED_IP, remember_me=False):
    return client.post(
        '/api/auth/login',
        json={'username': username, 'password': password, 'remember_me': remember_me},
        environ_base={'REMOTE_ADDR': remote_addr},
    )


# ---------------------------------------------------------------------------
# Regression baseline: nothing changes while both features are untouched
# ---------------------------------------------------------------------------


class TestLoginUnchanged:
    def test_plain_login_still_succeeds(self, client, security_settings, make_user):
        user, password, _ = make_user()

        resp = login(client, user.username, password)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['username'] == user.username
        assert data['role'] == auth_mod.ROLE_USER
        assert 'using_default_password' in data

    def test_plain_login_sets_the_session(self, client, security_settings, make_user):
        user, password, _ = make_user()

        login(client, user.username, password)

        assert client.get('/api/auth/status').get_json()['authenticated'] is True

    def test_wrong_password_still_returns_401(self, client, security_settings, make_user):
        user, _, _ = make_user()

        resp = login(client, user.username, 'not-the-password')

        assert resp.status_code == 401
        assert resp.get_json()['error_key'] == 'auth.invalid_credentials'

    def test_missing_credentials_still_returns_400(self, client, security_settings):
        resp = client.post('/api/auth/login', json={})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.enter_username_password'

    def test_user_without_2fa_is_not_challenged(self, client, security_settings, make_user):
        """The instance switch alone must not challenge accounts that never opted in."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user()

        assert login(client, user.username, password).get_json()['status'] == 'success'

    def test_remember_me_still_makes_the_session_permanent(self, client, security_settings, make_user):
        user, password, _ = make_user()

        login(client, user.username, password, remember_me=True)

        with client.session_transaction() as sess:
            assert sess.permanent is True


# ---------------------------------------------------------------------------
# Login-time 2FA challenge
# ---------------------------------------------------------------------------


class TestLoginTwoFactorChallenge:
    def test_challenge_returned_from_an_untrusted_network(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)

        resp = login(client, user.username, password)

        assert resp.status_code == 200
        assert resp.get_json() == {'status': '2fa_required'}

    def test_pending_state_is_not_an_authenticated_session(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)

        login(client, user.username, password)

        assert client.get('/api/auth/status').get_json()['authenticated'] is False
        assert client.get('/api/auth/preferences').status_code == 401

    def test_pending_session_is_never_permanent(self, client, security_settings, make_user):
        """The 30-day cookie only applies once the code has been verified."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)

        login(client, user.username, password, remember_me=True)

        with client.session_transaction() as sess:
            assert sess.permanent is False
            assert sess['pending_2fa_remember_me'] is True

    def test_challenge_skipped_from_a_trusted_network(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)

        resp = login(client, user.username, password, remote_addr=TRUSTED_IP)

        assert resp.get_json()['status'] == 'success'

    def test_challenge_skipped_from_localhost(self, client, security_settings, make_user):
        """Loopback is always trusted, even though it is never in the stored list."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)

        resp = login(client, user.username, password, remote_addr='127.0.0.1')

        assert resp.get_json()['status'] == 'success'

    def test_no_challenge_when_the_instance_switch_is_off(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=False)
        user, password, _ = make_user(with_totp=True)

        assert login(client, user.username, password).get_json()['status'] == 'success'

    def test_wrong_password_never_reveals_the_challenge(self, client, security_settings, make_user):
        """Network/2FA state must not be probeable without valid credentials."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, _, _ = make_user(with_totp=True)

        resp = login(client, user.username, 'wrong')

        assert resp.status_code == 401
        with client.session_transaction() as sess:
            assert 'pending_2fa_user_id' not in sess


# ---------------------------------------------------------------------------
# /api/auth/login/verify-2fa
# ---------------------------------------------------------------------------


class TestVerifyTwoFactor:
    def test_correct_code_completes_the_login(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password)

        resp = client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['username'] == user.username
        assert client.get('/api/auth/status').get_json()['authenticated'] is True

    def test_pending_markers_are_cleared_on_success(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password)

        client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        with client.session_transaction() as sess:
            for key in auth_bp_mod._PENDING_2FA_KEYS:
                assert key not in sess

    def test_remember_me_is_carried_across_the_two_steps(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password, remember_me=True)

        client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        with client.session_transaction() as sess:
            assert sess.permanent is True

    def test_wrong_code_is_rejected_and_counted(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)
        login(client, user.username, password)

        resp = client.post('/api/auth/login/verify-2fa', json={'code': '000000'})

        assert resp.status_code == 401
        assert resp.get_json()['error_key'] == 'auth.invalid_otp_code'
        with client.session_transaction() as sess:
            assert sess['pending_2fa_attempts'] == 1
        assert client.get('/api/auth/status').get_json()['authenticated'] is False

    def test_too_many_attempts_abandons_the_pending_state(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password)

        for _ in range(auth_bp_mod.PENDING_2FA_MAX_ATTEMPTS):
            assert client.post('/api/auth/login/verify-2fa', json={'code': '000000'}).status_code == 401

        resp = client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        assert resp.status_code == 429
        assert resp.get_json()['error_key'] == 'auth.otp_too_many_attempts'
        with client.session_transaction() as sess:
            assert 'pending_2fa_user_id' not in sess

    def test_expired_pending_state_is_rejected(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password)

        with client.session_transaction() as sess:
            sess['pending_2fa_expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

        resp = client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.otp_session_expired'

    def test_unparseable_expiry_is_treated_as_expired(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password)

        with client.session_transaction() as sess:
            sess['pending_2fa_expires_at'] = 'not-a-timestamp'

        resp = client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.otp_session_expired'

    def test_without_any_pending_state_is_rejected(self, client, security_settings):
        resp = client.post('/api/auth/login/verify-2fa', json={'code': '123456'})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.otp_session_expired'

    def test_pending_user_whose_2fa_was_removed_meanwhile(self, client, security_settings, make_user):
        """An admin clearing the user's 2FA mid-flow must invalidate the pending state."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, secret = make_user(with_totp=True)
        login(client, user.username, password)

        user_manager.disable_totp(user.user_id)

        resp = client.post('/api/auth/login/verify-2fa', json={'code': pyotp.TOTP(secret).now()})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.otp_session_expired'

    def test_a_fresh_login_overwrites_a_stale_pending_state(self, client, security_settings, make_user):
        """Backing out of the OTP step needs no server call: logging in again resets it."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        challenged, challenged_password, _ = make_user(with_totp=True)
        plain, plain_password, _ = make_user()

        login(client, challenged.username, challenged_password)
        resp = login(client, plain.username, plain_password)

        assert resp.get_json()['status'] == 'success'
        with client.session_transaction() as sess:
            assert 'pending_2fa_user_id' not in sess


# ---------------------------------------------------------------------------
# Local vs. global account scope
# ---------------------------------------------------------------------------


class TestAccountScopeAtLogin:
    def test_local_account_blocked_from_an_untrusted_network(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN])
        user, password, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_LOCAL)

        resp = login(client, user.username, password)

        assert resp.status_code == 403
        assert resp.get_json()['error_key'] == 'auth.local_account_network_restricted'
        assert client.get('/api/auth/status').get_json()['authenticated'] is False

    def test_local_account_allowed_from_a_trusted_network(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN])
        user, password, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_LOCAL)

        resp = login(client, user.username, password, remote_addr=TRUSTED_IP)

        assert resp.get_json()['status'] == 'success'

    def test_local_account_allowed_from_localhost(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN])
        user, password, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_LOCAL)

        assert login(client, user.username, password, remote_addr='127.0.0.1').get_json()['status'] == 'success'

    def test_local_account_allowed_anywhere_with_no_configured_network(
        self, client, security_settings, make_user
    ):
        """Documented fallback: without a configured network, "local" is undefined, so
        enforcing it would be a silent full lockout."""
        security_settings([])
        user, password, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_LOCAL)

        assert login(client, user.username, password).get_json()['status'] == 'success'

    def test_global_account_is_never_restricted(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN])
        user, password, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_GLOBAL)

        assert login(client, user.username, password).get_json()['status'] == 'success'

    def test_scope_block_takes_priority_over_the_2fa_challenge(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_LOCAL, with_totp=True)

        resp = login(client, user.username, password)

        assert resp.status_code == 403
        with client.session_transaction() as sess:
            assert 'pending_2fa_user_id' not in sess


# ---------------------------------------------------------------------------
# Self-service enrolment
# ---------------------------------------------------------------------------


class TestSelfServiceTwoFactor:
    @pytest.fixture
    def enrolled_client(self, client, security_settings, make_user):
        """A logged-in account with 2FA available but not yet enabled."""
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user()
        login(client, user.username, password, remote_addr=TRUSTED_IP)
        return client, user, password

    def test_setup_confirm_disable_round_trip(self, enrolled_client):
        client, user, password = enrolled_client

        setup = client.post('/api/auth/2fa/setup')
        assert setup.status_code == 200
        body = setup.get_json()
        assert body['secret']
        assert body['otpauth_uri'].startswith('otpauth://totp/')

        # Persisted but not active until confirmed.
        assert user_manager.get_user_by_id(user.user_id).totp_enabled is False

        confirm = client.post('/api/auth/2fa/confirm', json={'code': pyotp.TOTP(body['secret']).now()})
        assert confirm.status_code == 200
        assert user_manager.get_user_by_id(user.user_id).totp_enabled is True

        disable = client.post('/api/auth/2fa/disable', json={'password': password})
        assert disable.status_code == 200
        refreshed = user_manager.get_user_by_id(user.user_id)
        assert refreshed.totp_enabled is False
        assert refreshed.totp_secret is None

    def test_status_reports_availability_and_own_state(self, enrolled_client):
        client, user, _ = enrolled_client

        before = client.get('/api/auth/status').get_json()
        assert before['two_factor_available'] is True
        assert before['totp_enabled'] is False

        secret = client.post('/api/auth/2fa/setup').get_json()['secret']
        client.post('/api/auth/2fa/confirm', json={'code': pyotp.TOTP(secret).now()})

        after = client.get('/api/auth/status').get_json()
        assert after['totp_enabled'] is True
        assert after['totp_confirmed_at'] is not None

    def test_confirm_with_a_wrong_code_is_rejected(self, enrolled_client):
        client, user, _ = enrolled_client
        client.post('/api/auth/2fa/setup')

        resp = client.post('/api/auth/2fa/confirm', json={'code': '000000'})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.invalid_otp_code'
        assert user_manager.get_user_by_id(user.user_id).totp_enabled is False

    def test_confirm_without_a_code_is_rejected(self, enrolled_client):
        client, _, _ = enrolled_client
        client.post('/api/auth/2fa/setup')

        resp = client.post('/api/auth/2fa/confirm', json={})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'auth.invalid_otp_code'

    def test_confirm_before_setup_is_rejected(self, enrolled_client):
        client, _, _ = enrolled_client

        resp = client.post('/api/auth/2fa/confirm', json={'code': '123456'})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'settings.2fa_setup_not_started'

    def test_disable_with_a_wrong_password_is_rejected(self, enrolled_client):
        client, user, _ = enrolled_client
        secret = client.post('/api/auth/2fa/setup').get_json()['secret']
        client.post('/api/auth/2fa/confirm', json={'code': pyotp.TOTP(secret).now()})

        resp = client.post('/api/auth/2fa/disable', json={'password': 'wrong'})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.current_password_incorrect'
        assert user_manager.get_user_by_id(user.user_id).totp_enabled is True

    def test_disable_without_a_password_is_rejected(self, enrolled_client):
        client, _, _ = enrolled_client

        resp = client.post('/api/auth/2fa/disable', json={})

        assert resp.status_code == 400

    def test_setup_refused_when_the_instance_switch_is_off(self, client, security_settings, make_user):
        security_settings([TRUSTED_LAN], two_factor_enabled=False)
        user, password, _ = make_user()
        login(client, user.username, password, remote_addr=TRUSTED_IP)

        resp = client.post('/api/auth/2fa/setup')

        assert resp.status_code == 403
        assert resp.get_json()['error_key'] == 'settings.2fa_not_available'

    def test_endpoints_require_a_session(self, client, security_settings):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)

        assert client.post('/api/auth/2fa/setup').status_code == 401
        assert client.post('/api/auth/2fa/confirm', json={'code': '123456'}).status_code == 401
        assert client.post('/api/auth/2fa/disable', json={'password': 'x'}).status_code == 401


# ---------------------------------------------------------------------------
# Admin: forced 2FA removal and account scope
# ---------------------------------------------------------------------------


class TestAdminUserTwoFactor:
    def test_admin_can_clear_a_users_2fa(self, client_admin, security_settings, make_user):
        user, _, _ = make_user(with_totp=True)

        resp = client_admin.delete(f'/api/users/{user.user_id}/2fa')

        assert resp.status_code == 200
        refreshed = user_manager.get_user_by_id(user.user_id)
        assert refreshed.totp_enabled is False
        assert refreshed.totp_secret is None

    def test_clearing_2fa_lets_the_user_sign_in_with_a_password_alone(
        self, client, security_settings, make_user
    ):
        security_settings([TRUSTED_LAN], two_factor_enabled=True)
        user, password, _ = make_user(with_totp=True)
        assert login(client, user.username, password).get_json()['status'] == '2fa_required'

        # One client throughout: two interleaved test clients would fight over Flask's
        # preserved request context. Switch this one's session to the admin instead.
        admin = user_manager.get_user_by_username('admin')
        with client.session_transaction() as sess:
            sess['user_id'] = admin.user_id
            sess['username'] = admin.username
            sess['role'] = admin.role
        assert client.delete(f'/api/users/{user.user_id}/2fa').status_code == 200

        assert login(client, user.username, password).get_json()['status'] == 'success'

    def test_unknown_user_returns_400(self, client_admin, security_settings):
        resp = client_admin.delete('/api/users/does-not-exist/2fa')

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.user_not_found'

    def test_requires_admin(self, client, security_settings, make_user):
        target, _, _ = make_user(with_totp=True)
        actor, actor_password, _ = make_user()
        login(client, actor.username, actor_password)

        assert client.delete(f'/api/users/{target.user_id}/2fa').status_code == 403

    def test_list_users_reports_scope_and_2fa(self, client_admin, security_settings, make_user):
        user, _, _ = make_user(account_scope=auth_mod.ACCOUNT_SCOPE_LOCAL, with_totp=True)

        entry = next(u for u in client_admin.get('/api/users').get_json() if u['user_id'] == user.user_id)

        assert entry['account_scope'] == auth_mod.ACCOUNT_SCOPE_LOCAL
        assert entry['totp_enabled'] is True
        assert 'totp_secret' not in entry

    def test_update_user_accepts_account_scope(self, client_admin, security_settings, make_user):
        user, _, _ = make_user()

        resp = client_admin.put(f'/api/users/{user.user_id}', json={'account_scope': 'local'})

        assert resp.status_code == 200
        assert resp.get_json()['user']['account_scope'] == 'local'
        assert user_manager.get_user_by_id(user.user_id).account_scope == 'local'

    def test_update_user_rejects_an_unknown_scope(self, client_admin, security_settings, make_user):
        user, _, _ = make_user()

        resp = client_admin.put(f'/api/users/{user.user_id}', json={'account_scope': 'interstellar'})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.invalid_account_scope'

    def test_create_user_accepts_account_scope(self, client_admin, security_settings):
        username = f"pytest-{uuid.uuid4().hex[:10]}"
        try:
            resp = client_admin.post(
                '/api/users',
                json={'username': username, 'password': 'test-password', 'role': 'user', 'account_scope': 'local'},
            )

            assert resp.status_code == 200
            assert resp.get_json()['user']['account_scope'] == 'local'
        finally:
            created = user_manager.get_user_by_username(username)
            if created:
                user_manager.delete_user(created.user_id)

    def test_create_user_rejects_an_unknown_scope(self, client_admin, security_settings):
        resp = client_admin.post(
            '/api/users',
            json={
                'username': f"pytest-{uuid.uuid4().hex[:10]}",
                'password': 'test-password',
                'role': 'user',
                'account_scope': 'galactic',
            },
        )

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.invalid_account_scope'


# ---------------------------------------------------------------------------
# Admin: /api/auth/security-settings
# ---------------------------------------------------------------------------


class TestSecuritySettingsApi:
    @pytest.fixture(autouse=True)
    def isolated_settings_file(self, tmp_path, monkeypatch):
        """Never touch the real data directory while exercising the save endpoint."""
        monkeypatch.setattr(security_settings_mod, '_DATA_DIR', str(tmp_path))
        monkeypatch.setattr(
            security_settings_mod, '_SECURITY_SETTINGS_FILE', str(tmp_path / 'security_settings.json')
        )
        monkeypatch.setattr(security_settings_mod, '_cache', None)
        yield
        security_settings_mod._cache = None

    def test_get_returns_defaults_and_the_implicit_networks(self, client_admin):
        body = client_admin.get('/api/auth/security-settings').get_json()

        assert body['trusted_networks'] == []
        assert body['two_factor_enabled'] is False
        assert '127.0.0.0/8' in body['always_trusted_networks']
        assert '::1/128' in body['always_trusted_networks']

    def test_save_normalizes_and_dedupes_networks(self, client_admin):
        resp = client_admin.post(
            '/api/auth/security-settings',
            json={'trusted_networks': ['192.168.1.5/24', '192.168.1.0/24', '10.0.0.1'], 'two_factor_enabled': False},
        )

        assert resp.status_code == 200
        assert resp.get_json()['trusted_networks'] == ['192.168.1.0/24', '10.0.0.1/32']

    def test_save_rejects_an_invalid_network(self, client_admin):
        resp = client_admin.post(
            '/api/auth/security-settings',
            json={'trusted_networks': ['192.168.1.0/24', 'not-a-network'], 'two_factor_enabled': False},
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body['error_key'] == 'settings.invalid_trusted_network'
        assert body['invalid_entry'] == 'not-a-network'

    def test_save_rejects_a_non_list(self, client_admin):
        resp = client_admin.post('/api/auth/security-settings', json={'trusted_networks': '192.168.1.0/24'})

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'settings.invalid_trusted_network'

    def test_cannot_enable_2fa_without_a_trusted_network(self, client_admin):
        resp = client_admin.post(
            '/api/auth/security-settings', json={'trusted_networks': [], 'two_factor_enabled': True}
        )

        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'settings.2fa_requires_trusted_network'

    def test_removing_the_last_network_silently_disables_2fa(self, client_admin):
        client_admin.post(
            '/api/auth/security-settings',
            json={'trusted_networks': [TRUSTED_LAN], 'two_factor_enabled': True},
        )

        resp = client_admin.post(
            '/api/auth/security-settings', json={'trusted_networks': [], 'two_factor_enabled': True}
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['trusted_networks'] == []
        assert body['two_factor_enabled'] is False

    def test_save_then_get_round_trip(self, client_admin):
        client_admin.post(
            '/api/auth/security-settings',
            json={'trusted_networks': [TRUSTED_LAN], 'two_factor_enabled': True},
        )

        body = client_admin.get('/api/auth/security-settings').get_json()

        assert body['trusted_networks'] == [TRUSTED_LAN]
        assert body['two_factor_enabled'] is True

    def test_partial_payload_keeps_the_untouched_field(self, client_admin):
        client_admin.post(
            '/api/auth/security-settings',
            json={'trusted_networks': [TRUSTED_LAN], 'two_factor_enabled': True},
        )

        resp = client_admin.post('/api/auth/security-settings', json={'two_factor_enabled': False})

        assert resp.get_json()['trusted_networks'] == [TRUSTED_LAN]

    def test_requires_admin(self, client, make_user):
        user, password, _ = make_user()
        login(client, user.username, password)

        assert client.get('/api/auth/security-settings').status_code == 403
        assert client.post('/api/auth/security-settings', json={}).status_code == 403

    def test_requires_a_session(self, client):
        assert client.get('/api/auth/security-settings').status_code == 401
        assert client.post('/api/auth/security-settings', json={}).status_code == 401
