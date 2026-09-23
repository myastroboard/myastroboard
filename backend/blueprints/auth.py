"""Authentication + user management Blueprint.

Routes: /api/auth/*, /api/users/*
"""

import time
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock

from flask import Blueprint, request, jsonify, session

from utils import security_settings as _security_settings
from utils.auth import ALLOWED_ACCOUNT_SCOPES, user_manager, login_required, admin_required, get_current_user
from utils.logging_config import get_logger

logger = get_logger(__name__)

auth_bp = Blueprint('auth', __name__)

# Pending-2FA window. A 6-digit code is a far smaller search space than a password,
# so OTP verification is throttled even though password login is not (that gap is
# documented in docs/AUTHENTICATION.md and belongs to a reverse proxy).
PENDING_2FA_TTL_SECONDS = 300
PENDING_2FA_MAX_ATTEMPTS = 5

_PENDING_2FA_KEYS = (
    'pending_2fa_user_id',
    'pending_2fa_remember_me',
    'pending_2fa_expires_at',
)

# Server-side OTP attempt counter, keyed by user_id and independent of the session
# cookie: a counter that only lives in the session (as pending_2fa_attempts used to)
# resets to zero on every fresh /api/auth/login call, which an attacker who already
# knows the password can issue at will - trivially defeating the throttle. Windowed
# the same way as astrodex_stream.py's rate limiter (same accepted multi-worker
# trade-off: gunicorn -w N gives each worker its own count, so the real ceiling is
# PENDING_2FA_MAX_ATTEMPTS per worker rather than truly global - still bounded, and
# consistent with how this codebase already rate-limits elsewhere).
_otp_attempts_lock = Lock()
_otp_attempts: dict = {}


def _otp_attempts_exceeded(user_id: str) -> bool:
    now = time.time()
    with _otp_attempts_lock:
        hits = _otp_attempts.get(user_id)
        if not hits:
            return False
        while hits and hits[0] <= now - PENDING_2FA_TTL_SECONDS:
            hits.popleft()
        return len(hits) >= PENDING_2FA_MAX_ATTEMPTS


def _record_otp_failure(user_id: str) -> None:
    now = time.time()
    with _otp_attempts_lock:
        hits = _otp_attempts.setdefault(user_id, deque())
        while hits and hits[0] <= now - PENDING_2FA_TTL_SECONDS:
            hits.popleft()
        hits.append(now)
        if len(_otp_attempts) > 512:
            for key in [k for k, v in _otp_attempts.items() if not v]:
                _otp_attempts.pop(key, None)


def _clear_otp_attempts(user_id: str) -> None:
    with _otp_attempts_lock:
        _otp_attempts.pop(user_id, None)


def _eq(message):
    """Predicate builder: exact match against a ValueError's str()."""
    return lambda text: text == message


def _prefix_suffix(prefix, suffix=''):
    """Predicate builder: match a ValueError whose str() carries dynamic content
    (a user id, a username) between a known prefix and suffix."""
    return lambda text: text.startswith(prefix) and text.endswith(suffix)


def _resolve_error_key(exc: ValueError, rules, default: str) -> str:
    """Map a ValueError to an i18n error_key via an ordered list of (predicate, key)
    pairs, tried in order against str(exc). Falls back to *default* when nothing
    matches (e.g. after a future wording change in utils/auth.py) - the generic
    message still explains the failure, just less specifically, rather than raising."""
    text = str(exc)
    for predicate, key in rules:
        if predicate(text):
            return key
    return default


# ============================================================
# Authentication API
# ============================================================


def _clear_pending_2fa():
    """Drop every pending-2FA marker from the session."""
    for key in _PENDING_2FA_KEYS:
        session.pop(key, None)


def _finish_login(user, remember_me):
    """Set the authenticated session and build the login response.

    Shared tail of the password-only flow and the OTP-verified flow, so both end
    up with exactly the same session state and response shape.
    """
    # Set session to permanent BEFORE setting session data
    # This ensures the cookie is created with the correct expiration
    session.permanent = bool(remember_me)

    session['user_id'] = user.user_id
    session['username'] = user.username
    session['role'] = user.role
    _clear_pending_2fa()

    # Fresh login: the user's default location becomes the active one
    # (a mid-session switch from a previous session never survives login)
    try:
        user_manager.reset_active_location_on_login(user.user_id)
    except Exception as loc_reset_error:
        logger.warning(f"Could not reset active location on login: {loc_reset_error}")

    # Log successful login with remember_me status
    logger.info(
        f"Successful login for user {user.username!r} "
        + f"(remember_me: {remember_me}, permanent_session: {session.permanent})"
    )

    return jsonify(
        {
            'status': 'success',
            'user_id': user.user_id,
            'username': user.username,
            'role': user.role,
            'using_default_password': user.is_using_default_password(),
        }
    )


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """Login endpoint.

    Network and 2FA checks run only AFTER the password is confirmed: probing them
    first would let an attacker learn about an account without valid credentials.
    """
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        remember_me = data.get('remember_me', False)

        if not username or not password:
            logger.warning("Login attempt with missing credentials")
            return (
                jsonify({'error': 'Username and password required', 'error_key': 'auth.enter_username_password'}),
                400,
            )

        user = user_manager.authenticate(username, password)
        if not user:
            logger.warning(f"Failed login attempt for username: {username!r}")
            return jsonify({'error': 'Invalid credentials', 'error_key': 'auth.invalid_credentials'}), 401

        # request.remote_addr already resolves the real client IP behind a trusted
        # reverse proxy (ProxyFix, wired in app.py from trust_proxy_headers).
        client_ip = request.remote_addr
        settings = _security_settings.get_security_settings()
        configured_networks = settings.get('trusted_networks') or []
        client_is_trusted = _security_settings.is_client_ip_trusted(client_ip, settings)

        # 1. Local/global scope. With no configured network, "local" is undefined,
        #    so the restriction stays off rather than locking the account out entirely.
        if user.is_local_account() and configured_networks and not client_is_trusted:
            logger.warning(f"Local account {username!r} login blocked from untrusted network {client_ip!r}")
            return (
                jsonify(
                    {
                        'error': 'This account can only sign in from a trusted network',
                        'error_key': 'auth.local_account_network_restricted',
                    }
                ),
                403,
            )

        # 2. Two-factor. A trusted network skips the OTP step entirely.
        if settings.get('two_factor_enabled') and user.totp_enabled and not client_is_trusted:
            # Pending state only - 'username' stays unset, so every @login_required
            # route remains locked until the code is verified. The attempt counter
            # itself lives server-side (see _otp_attempts above), not in the session:
            # a session-only counter resets every time this endpoint is called again,
            # which an attacker who already has the password could do at will.
            session.permanent = False
            _clear_pending_2fa()
            session['pending_2fa_user_id'] = user.user_id
            session['pending_2fa_remember_me'] = bool(remember_me)
            session['pending_2fa_expires_at'] = (
                datetime.now(timezone.utc) + timedelta(seconds=PENDING_2FA_TTL_SECONDS)
            ).isoformat()
            logger.info(f"Password accepted for user {username!r} from {client_ip!r}, awaiting 2FA code")
            return jsonify({'status': '2fa_required'})

        return _finish_login(user, remember_me)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Internal server error', 'error_key': 'auth.internal_server_error'}), 500


@auth_bp.route('/api/auth/login/verify-2fa', methods=['POST'])
def verify_login_2fa():
    """Second login step: verify the OTP code against the pending session state."""
    try:
        data = request.json or {}
        code = str(data.get('code') or '').strip()

        pending_user_id = session.get('pending_2fa_user_id')
        expires_at = session.get('pending_2fa_expires_at')
        if not pending_user_id or not expires_at:
            return jsonify({'error': 'No pending verification', 'error_key': 'auth.otp_session_expired'}), 400

        try:
            expired = datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at)
        except ValueError:
            expired = True
        if expired:
            _clear_pending_2fa()
            logger.warning("2FA verification rejected: pending session expired")
            return jsonify({'error': 'Verification expired', 'error_key': 'auth.otp_session_expired'}), 400

        user = user_manager.get_user_by_id(pending_user_id)
        if not user or not user.totp_enabled:
            _clear_pending_2fa()
            logger.warning("2FA verification rejected: pending user no longer eligible")
            return jsonify({'error': 'No pending verification', 'error_key': 'auth.otp_session_expired'}), 400

        # Re-check the local-account/trusted-network restriction, not just the OTP
        # code: an admin could have switched this account to 'local' from an
        # untrusted network while this pending login was in flight, and that must
        # take effect immediately rather than only on the user's next full login.
        client_ip = request.remote_addr
        settings = _security_settings.get_security_settings()
        if user.is_local_account() and settings.get('trusted_networks'):
            if not _security_settings.is_client_ip_trusted(client_ip, settings):
                _clear_pending_2fa()
                logger.warning(
                    f"Local account {user.username!r} 2FA verification blocked from untrusted network {client_ip!r}"
                )
                return (
                    jsonify(
                        {
                            'error': 'This account can only sign in from a trusted network',
                            'error_key': 'auth.local_account_network_restricted',
                        }
                    ),
                    403,
                )

        if _otp_attempts_exceeded(user.user_id):
            _clear_pending_2fa()
            logger.warning(f"2FA verification abandoned after too many failed attempts for user {user.username!r}")
            return jsonify({'error': 'Too many attempts', 'error_key': 'auth.otp_too_many_attempts'}), 429

        if not user.verify_totp(code):
            _record_otp_failure(user.user_id)
            logger.warning(f"Invalid 2FA code for user {user.username!r} from {request.remote_addr!r}")
            return jsonify({'error': 'Invalid code', 'error_key': 'auth.invalid_otp_code'}), 401

        _clear_otp_attempts(user.user_id)
        return _finish_login(user, session.get('pending_2fa_remember_me', False))
    except Exception as e:
        logger.error(f"2FA verification error: {e}")
        return jsonify({'error': 'Internal server error', 'error_key': 'auth.internal_server_error'}), 500


@auth_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """Logout endpoint"""
    username = session.get('username')
    was_permanent = session.permanent
    session.clear()

    logger.info(f"User {username} logged out (was_permanent: {was_permanent})")

    # session.clear() handles cookie removal properly
    return jsonify({'status': 'success'})


@auth_bp.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Get authentication status"""
    if 'username' in session:
        user = get_current_user()
        if user:
            return jsonify(
                {
                    'authenticated': True,
                    'user_id': user.user_id,
                    'username': user.username,
                    'role': user.role,
                    'using_default_password': user.is_using_default_password(),
                    # Exposed here so My Settings -> Security can render the 2FA panel
                    # without needing admin access to read security_settings.json.
                    'two_factor_available': bool(_security_settings.get_security_settings().get('two_factor_enabled')),
                    'totp_enabled': user.totp_enabled,
                    'totp_confirmed_at': user.totp_confirmed_at,
                    'account_scope': user.account_scope,
                }
            )
    return jsonify({'authenticated': False})


# ============================================================
# Two-factor authentication - self-service (My Settings -> Security)
# ============================================================


@auth_bp.route('/api/auth/2fa/setup', methods=['POST'])
@login_required
def start_two_factor_setup():
    """Generate a fresh, unconfirmed TOTP secret for the current user."""
    try:
        if not _security_settings.get_security_settings().get('two_factor_enabled'):
            return (
                jsonify({'error': 'Two-factor authentication is disabled', 'error_key': 'settings.2fa_not_available'}),
                403,
            )

        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        user = user_manager.start_totp_setup(current_user.user_id)
        return jsonify({'status': 'success', 'secret': user.totp_secret, 'otpauth_uri': user.get_totp_uri()})
    except ValueError as e:
        error_key = _resolve_error_key(
            e,
            [(_eq('Two-factor authentication is already enabled'), 'settings.2fa_already_enabled')],
            'settings.2fa_setup_error',
        )
        logger.warning(f"2FA setup rejected for user {session.get('username')!r}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error starting 2FA setup for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/2fa/confirm', methods=['POST'])
@login_required
def confirm_two_factor_setup():
    """Activate 2FA for the current user after verifying a generated code."""
    try:
        data = request.json or {}
        code = str(data.get('code') or '').strip()

        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        if not code:
            return jsonify({'error': 'Code is required', 'error_key': 'auth.invalid_otp_code'}), 400

        user_manager.confirm_totp_setup(current_user.user_id, code)
        return jsonify({'status': 'success'})
    except ValueError as e:
        error_key = _resolve_error_key(
            e,
            [
                (_eq('Invalid two-factor code'), 'auth.invalid_otp_code'),
                (_eq('Two-factor setup has not been started'), 'settings.2fa_setup_not_started'),
            ],
            'settings.2fa_setup_error',
        )
        logger.warning(f"2FA confirmation rejected for user {session.get('username')!r}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error confirming 2FA for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/2fa/disable', methods=['POST'])
@login_required
def disable_two_factor():
    """Turn 2FA off for the current user after re-authenticating with their password."""
    try:
        data = request.json or {}
        password = data.get('password') or ''

        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        if not password:
            return (
                jsonify({'error': 'Password is required', 'error_key': 'users.current_password_incorrect'}),
                400,
            )

        user_manager.disable_totp(current_user.user_id, password)
        return jsonify({'status': 'success'})
    except ValueError as e:
        error_key = _resolve_error_key(
            e,
            [(_eq('Current password is incorrect'), 'users.current_password_incorrect')],
            'settings.2fa_setup_error',
        )
        logger.warning(f"2FA disable rejected for user {session.get('username')!r}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error disabling 2FA for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# Instance security settings (admin only)
# ============================================================


@auth_bp.route('/api/auth/security-settings', methods=['GET'])
@admin_required
def get_security_settings_api():
    """Return the trusted networks and the instance-wide 2FA switch."""
    settings = _security_settings.get_security_settings()
    return jsonify(
        {
            'trusted_networks': list(settings.get('trusted_networks') or []),
            'two_factor_enabled': bool(settings.get('two_factor_enabled')),
            'always_trusted_networks': list(_security_settings.ALWAYS_TRUSTED_NETWORKS),
        }
    )


@auth_bp.route('/api/auth/security-settings', methods=['POST'])
@admin_required
def update_security_settings_api():
    """Save the trusted networks and the instance-wide 2FA switch."""
    try:
        data = request.json or {}
        old_settings = _security_settings.get_security_settings()

        raw_networks = data.get('trusted_networks', old_settings.get('trusted_networks') or [])
        if not isinstance(raw_networks, list):
            return (
                jsonify({'error': 'trusted_networks must be a list', 'error_key': 'settings.invalid_trusted_network'}),
                400,
            )

        networks = []
        for raw_entry in raw_networks:
            try:
                normalized = _security_settings.normalize_network(raw_entry)
            except ValueError:
                # Not logging the entry itself - it's already returned to the same
                # admin who submitted it in the response below, and this list is
                # admin-managed config, not something worth echoing into the log.
                logger.warning("Security settings rejected: invalid trusted network entry")
                return (
                    jsonify(
                        {
                            'error': f"Invalid trusted network: {raw_entry}",
                            'error_key': 'settings.invalid_trusted_network',
                            'invalid_entry': str(raw_entry),
                        }
                    ),
                    400,
                )
            if normalized not in networks:
                networks.append(normalized)

        two_factor_enabled = bool(data.get('two_factor_enabled', old_settings.get('two_factor_enabled', False)))

        if two_factor_enabled and not networks:
            was_enabled = bool(old_settings.get('two_factor_enabled'))
            if not was_enabled:
                # Turning 2FA on without a trusted network is rejected outright.
                return (
                    jsonify(
                        {
                            'error': 'At least one trusted network is required to enable two-factor authentication',
                            'error_key': 'settings.2fa_requires_trusted_network',
                        }
                    ),
                    400,
                )
            # Documented cascade: removing the last network also turns 2FA off.
            two_factor_enabled = False
            logger.warning("Last trusted network removed: two-factor authentication disabled instance-wide")

        _security_settings.save_security_settings(
            {'trusted_networks': networks, 'two_factor_enabled': two_factor_enabled}
        )
        logger.info(
            f"Security settings updated by {session.get('username', '?')}: "
            f"{len(networks)} trusted network(s), two_factor_enabled={two_factor_enabled}"
        )
        return jsonify(
            {
                'status': 'success',
                'trusted_networks': networks,
                'two_factor_enabled': two_factor_enabled,
            }
        )
    except Exception as e:
        logger.error(f"Error saving security settings: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@login_required
def change_own_password():
    """Change password for currently authenticated user only."""
    try:
        data = request.json or {}
        current_password = data.get('current_password')
        new_password = data.get('new_password')

        if not current_password or not new_password:
            return (
                jsonify(
                    {
                        'error': 'Current password and new password are required',
                        'error_key': 'users.password_change_missing_fields',
                    }
                ),
                400,
            )

        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        user_manager.change_own_password(current_user.user_id, current_password, new_password)

        return jsonify({'status': 'success'})
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.error_update_password'

        if error_text == 'Current password is incorrect':
            error_key = 'users.current_password_incorrect'
        elif error_text == 'New password must be at least 6 characters':
            error_key = 'users.password_too_short'
        elif error_text == 'New password must be different from current password':
            error_key = 'users.password_must_be_different'

        logger.warning(f"Password change rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error changing password for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/preferences', methods=['GET'])
@login_required
def get_own_preferences():
    """Get UI customization preferences for the currently authenticated user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        preferences = user_manager.get_user_preferences(current_user.user_id)
        return jsonify({'preferences': preferences})
    except ValueError as e:
        logger.warning(f"Preference fetch rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': 'settings.pref_save_error'}), 400
    except Exception as e:
        logger.error(f"Error reading preferences for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/preferences', methods=['PUT'])
@login_required
def update_own_preferences():
    """Update UI customization preferences for the currently authenticated user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        data = request.json or {}
        preferences = data.get('preferences')
        if preferences is None:
            return jsonify({'error': 'Preferences are required', 'error_key': 'settings.pref_save_error'}), 400

        updated = user_manager.update_user_preferences(current_user.user_id, preferences)
        return jsonify({'status': 'success', 'preferences': updated})
    except ValueError as e:
        error_text = str(e)
        error_key = 'settings.pref_save_error'

        if error_text.startswith('Invalid startup_main_tab'):
            error_key = 'settings.pref_invalid_startup_main_tab'
        elif error_text.startswith('Invalid startup_subtab'):
            error_key = 'settings.pref_invalid_startup_subtab'
        elif error_text.startswith('Invalid time_format'):
            error_key = 'settings.pref_invalid_time_format'
        elif error_text.startswith('Invalid density'):
            error_key = 'settings.pref_invalid_density'
        elif error_text.startswith('Invalid theme_mode'):
            error_key = 'settings.pref_invalid_theme'
        elif error_text.startswith('Invalid experience_level'):
            error_key = 'settings.pref_invalid_experience_level'
        elif error_text.startswith('Invalid wizard'):
            error_key = 'settings.pref_invalid_wizard'

        logger.warning(f"Preference update rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error updating preferences for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# User Management API (Admin only)
# ============================================================


@auth_bp.route('/api/users', methods=['GET'])
@admin_required
def list_users():
    """List all users (admin only)"""
    users = user_manager.list_users()
    return jsonify(users)


@auth_bp.route('/api/users', methods=['POST'])
@admin_required
def create_user():
    """Create a new user (admin only)"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')
        account_scope = data.get('account_scope')

        if not username or not password or not role:
            return (
                jsonify(
                    {
                        'error': 'Username, password, and role required',
                        'error_key': 'users.required_username_password_role',
                    }
                ),
                400,
            )

        if account_scope is not None and account_scope not in ALLOWED_ACCOUNT_SCOPES:
            return jsonify({'error': 'Invalid account scope', 'error_key': 'users.invalid_account_scope'}), 400

        # Matches minlength="6" on #new-password and the same rule self-service password
        # changes enforce (change_own_password) - admin-created accounts must not be weaker.
        if len(password) < 6:
            return (
                jsonify({'error': 'Password must be at least 6 characters', 'error_key': 'users.password_too_short'}),
                400,
            )

        user = user_manager.create_user(username, password, role, account_scope)
        return jsonify(
            {
                'status': 'success',
                'user': {
                    'username': user.username,
                    'role': user.role,
                    'created_at': user.created_at,
                    'account_scope': user.account_scope,
                },
            }
        )
    except ValueError as e:
        error_key = _resolve_error_key(
            e,
            [
                (_prefix_suffix('User ', 'already exists'), 'users.username_already_exists'),
                (lambda t: t.startswith('Invalid role'), 'users.invalid_role'),
                (lambda t: t.startswith('Invalid account scope'), 'users.invalid_account_scope'),
            ],
            'users.invalid_input',
        )
        logger.warning(f"User creation failed: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/users/<user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update a user (admin only)"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')
        account_scope = data.get('account_scope')

        if not username and not password and not role and not account_scope:
            return (
                jsonify(
                    {
                        'error': 'Username, password, role or account scope required',
                        'error_key': 'users.required_update_payload',
                    }
                ),
                400,
            )

        if password and len(password) < 6:
            return (
                jsonify({'error': 'Password must be at least 6 characters', 'error_key': 'users.password_too_short'}),
                400,
            )

        logger.info(f"Updating user {user_id}, available users: {list(user_manager.users.keys())}")
        user = user_manager.update_user(user_id, username, password, role, account_scope)
        return jsonify(
            {
                'status': 'success',
                'user': {
                    'user_id': user.user_id,
                    'username': user.username,
                    'role': user.role,
                    'account_scope': user.account_scope,
                },
            }
        )
    except ValueError as e:
        error_key = _resolve_error_key(
            e,
            [
                (_prefix_suffix('User with ID ', ' not found'), 'users.user_not_found'),
                (_prefix_suffix('Username ', ' already taken'), 'users.username_already_taken'),
                (lambda t: t.startswith('Invalid role'), 'users.invalid_role'),
                (lambda t: t.startswith('Invalid account scope'), 'users.invalid_account_scope'),
            ],
            'users.invalid_input',
        )
        logger.warning(f"User update failed for user_id {user_id}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/users/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user (admin only)"""
    try:
        current_user_id = session.get('user_id')
        user_manager.delete_user(user_id, current_user_id)
        return jsonify({'status': 'success'})
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.invalid_input'

        if error_text.startswith('User with ID ') and error_text.endswith(' not found'):
            error_key = 'users.user_not_found'
        elif error_text == 'Cannot delete your own account':
            error_key = 'users.cannot_delete_own_account'

        logger.warning(f"User deletion failed for user_id {user_id}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/users/<user_id>/2fa', methods=['DELETE'])
@admin_required
def admin_disable_user_2fa(user_id):
    """Clear a user's two-factor state (admin only).

    The recovery path for a lost authenticator: no password check, admin
    authority is the check. An admin manages their own 2FA from My Settings.
    """
    try:
        user = user_manager.disable_totp(user_id)
        logger.info(f"2FA cleared for user {user.username} by admin {session.get('username', '?')}")
        return jsonify({'status': 'success'})
    except ValueError as e:
        error_key = _resolve_error_key(e, [(_eq('User not found'), 'users.user_not_found')], 'users.invalid_input')
        logger.warning(f"Admin 2FA disable failed for user_id {user_id}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error disabling 2FA for user {user_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500
