"""
Public demo mode (DEMO_MODE=true).

Turns an instance into a public, read-only showcase: every visitor is signed in
automatically on one shared demo account, and every request that would change
stored data is refused. The instance stays a normal MyAstroBoard otherwise: the
scheduler, caches and calculations keep running, so the sky shown is tonight's.

Only the demo account's session is restricted. Another account signed in on the
same instance (the maintainer preparing the demo data from the local network)
behaves normally; see docs/DEMO_MODE.md for the recommended account setup.
"""

import os
import secrets

from flask import jsonify, session

from utils.logging_config import get_logger

logger = get_logger(__name__)

DEMO_MODE_ENV = 'DEMO_MODE'
DEMO_USERNAME_ENV = 'DEMO_USERNAME'
DEFAULT_DEMO_USERNAME = 'demo'

# Session key holding the visitor's own UI preferences (theme, language, density...).
# The demo account is shared by every visitor, so a visitor's choices live in their
# own session cookie instead of on the account.
DEMO_PREFERENCES_SESSION_KEY = 'demo_preferences'

# Preference keys a visitor may not override, even in their own session: they hold
# server-side state (location attribution) or would subscribe the shared account.
DEMO_LOCKED_PREFERENCE_KEYS = frozenset({'location', 'notifications', 'mqtt_publish_enabled'})

SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

# Non-GET endpoints a demo visitor may still call: signing in and out, the session-scoped
# preferences, and pure calculations that store nothing.
DEMO_ALLOWED_WRITE_ENDPOINTS = frozenset(
    {
        'auth.login',
        'auth.verify_login_2fa',
        'auth.logout',
        'auth.update_own_preferences',
        'equipment.calculate_fov',
        'misc.convert_coordinates_api',
        'skytonight.get_skytonight_combination_recommendations_api',
    }
)

DEMO_READ_ONLY_ERROR = 'demo_read_only'
DEMO_READ_ONLY_ERROR_KEY = 'demo.read_only'


def is_demo_mode() -> bool:
    """True when the instance runs as a public demo (``DEMO_MODE`` env var)."""
    return os.environ.get(DEMO_MODE_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


def demo_username() -> str:
    """Username of the shared demo account (``DEMO_USERNAME``, default ``demo``)."""
    return os.environ.get(DEMO_USERNAME_ENV, '').strip() or DEFAULT_DEMO_USERNAME


def is_demo_username(username) -> bool:
    """True when ``username`` names the demo account (case-insensitive, like sign-in)."""
    return bool(username) and str(username).strip().lower() == demo_username().lower()


def is_demo_session() -> bool:
    """True when demo mode is on and the current session is the demo account."""
    return is_demo_mode() and is_demo_username(session.get('username'))


def get_or_create_demo_user(user_manager):
    """Return the demo account, creating it on first use.

    The account gets the ``user`` role so the visitor sees the full interface (the
    write guard, not the role, keeps it read-only), an unusable random password
    (it is only ever signed in automatically), and a completed first-run wizard.
    Two workers creating it at once is harmless: the loser reads the winner's row.
    """
    from utils.auth import ROLE_USER  # lazy: utils.auth imports nothing from here, keep it that way

    username = demo_username()
    user = user_manager.get_user_by_username(username)
    if user:
        return user
    try:
        user_manager.create_user(username, secrets.token_urlsafe(32), ROLE_USER)
        logger.info(f"Demo mode: created the demo account {username!r}")
    except ValueError:
        pass  # created by another worker in the meantime
    user = user_manager.get_user_by_username(username)
    if user:
        try:
            user_manager.update_user_preferences(user.user_id, {'wizard': {'completed': True, 'skipped': False}})
        except ValueError as e:
            logger.warning(f"Demo mode: could not mark the wizard as done for {username!r}: {e}")
    return user


def sign_in_demo_visitor(user_manager):
    """Sign the current visitor in on the demo account. Returns the user, or None.

    Writes the session directly instead of going through the login route: a visit is
    not a sign-in, so neither ``last_login`` nor the active location are touched (they
    would otherwise be rewritten on every new visitor).
    """
    user = get_or_create_demo_user(user_manager)
    if not user:
        logger.error("Demo mode: the demo account is missing and could not be created")
        return None
    session.clear()
    session.permanent = False
    session['user_id'] = user.user_id
    session['username'] = user.username
    session['role'] = user.role
    return user


def demo_read_only_response():
    """The 403 every blocked demo write receives (the frontend shows the translated key)."""
    return (
        jsonify(
            {
                'error': DEMO_READ_ONLY_ERROR,
                'error_key': DEMO_READ_ONLY_ERROR_KEY,
                'message': 'This is a read-only demo: changes are not saved.',
            }
        ),
        403,
    )


def blocked_demo_write(method, endpoint) -> bool:
    """True when a request must be refused because it would write from the demo session."""
    if method in SAFE_METHODS or endpoint in DEMO_ALLOWED_WRITE_ENDPOINTS:
        return False
    return is_demo_session()


def session_preferences() -> dict:
    """The visitor's own preference overrides, kept in their session cookie."""
    stored = session.get(DEMO_PREFERENCES_SESSION_KEY)
    return dict(stored) if isinstance(stored, dict) else {}


def visitor_preferences(account_preferences: dict) -> dict:
    """What a demo visitor sees: the demo account's preferences, overlaid with their own.

    The account's language is dropped: a shared account must not impose its language,
    so the visitor keeps their browser's language until they pick one themselves.
    """
    merged = dict(account_preferences)
    merged.pop('language', None)
    merged.update(session_preferences())
    return merged


def store_session_preferences(preferences: dict) -> dict:
    """Merge ``preferences`` (already validated) into the session overrides and return them."""
    overrides = session_preferences()
    overrides.update({k: v for k, v in preferences.items() if k not in DEMO_LOCKED_PREFERENCE_KEYS})
    session[DEMO_PREFERENCES_SESSION_KEY] = overrides
    return overrides
