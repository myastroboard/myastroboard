"""
MyAstroBoard - Flask Backend API
Provides astronomy planning and configuration management
"""

import atexit
from datetime import timezone
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    send_file,
    send_from_directory,
    session,
    redirect,
    url_for,
    g,
    Response,
    stream_with_context,
    abort,
)
from flask_compress import Compress
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import re
import json
import uuid
import io
import time
import zipfile
import sys
from datetime import datetime, timedelta
from dataclasses import asdict
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo, available_timezones

from werkzeug.utils import secure_filename
import shutil

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from astropy.utils import iers as _iers

# Keep auto_download off; the cache scheduler downloads IERS-A to a known path
# (data/cache/iers/finals2000A.all) every 21 days via update_iers_cache().
_iers.conf.auto_download = False
_iers.conf.auto_max_age = None

# If IERS-A was previously downloaded, load it into this worker's memory from the
# known path so all Gunicorn workers benefit without any network call at startup.
try:
    from constants import IERS_CACHE_FILE as _IERS_CACHE_FILE
    from astropy.utils.iers import IERS_Auto as _IERS_Auto, IERS_A as _IERS_A, earth_orientation_table as _eot

    if os.path.exists(_IERS_CACHE_FILE):  # pragma: no branch
        _table = _IERS_A.open(_IERS_CACHE_FILE)
        _IERS_Auto.iers_table = _table  # type: ignore[assignment]
        # IERS_Auto.open() with auto_download=False always overwrites iers_table with the
        # bundled (old) table, bypassing our downloaded one. Setting earth_orientation_table
        # directly ensures coordinate transforms (get_polar_motion) use the fresh data.
        _eot.set(_table)
except Exception:  # pragma: no cover
    pass  # No file yet; scheduler will download it on first cycle

from weather_openmeteo import get_hourly_forecast
from events_aggregator import EventsAggregator
from i18n_utils import I18nManager
from txtconf_loader import get_repo_version
from repo_config import load_config, save_config
from constants import (
    DATA_DIR,
    DATA_DIR_CACHE,
    CONFIG_FILE,
    CACHE_TTL,
    WEATHER_CACHE_TTL,
    SKYTONIGHT_LOGS_DIR,
    SKYTONIGHT_SCHEDULER_STATUS_FILE,
    CACHE_TTL_MOON_PLANNER,
    CACHE_TTL_SOLAR_ECLIPSE,
    CACHE_TTL_LUNAR_ECLIPSE,
    CACHE_TTL_AURORA,
    CACHE_TTL_ISS_PASSES,
    CACHE_TTL_PLANETARY_EVENTS,
    CACHE_TTL_SPECIAL_PHENOMENA,
    CACHE_TTL_SOLAR_SYSTEM_EVENTS,
    CACHE_TTL_SPACEFLIGHT_LAUNCHES,
    CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
    CACHE_TTL_SPACEFLIGHT_EVENTS,
    CACHE_TTL_SIDEREAL_TIME,
)
from logging_config import get_logger
from version_checker import check_for_updates
from metrics_collector import collect_metrics
from skytonight_storage import (
    get_scheduler_lock_file as get_skytonight_scheduler_lock_file,
)
from on_demand_translate import translate_text_on_demand
from skytonight_calculator import load_calculation_results
from sun_phases import SunService
import moon_planner

# Cache for heavy computations
import cache_store

# Authentication
from auth import (
    user_manager,
    login_required,
    admin_required,
    user_required,
    get_current_user,
)

# Astrodex
import astrodex
import iss_passes
import plan_my_night
import skytonight_targets

# Equipment Profiles
import equipment_profiles

# Initialize logger for this module
logger = get_logger(__name__)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
TEMPLATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# Load persistent app settings (replaces SECRET_KEY / TRUST_PROXY_HEADERS /
# SESSION_COOKIE_SECURE / VAPID_CONTACT_EMAIL environment variables).
import app_settings as _app_settings

_startup_settings = _app_settings.get_app_settings()

# Configure reverse proxy support — configurable via Parameters → Advanced → Reverse proxy
if _startup_settings['trust_proxy_headers']:  # pragma: no cover
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
        x_prefix=1,
    )
    logger.info("ProxyFix middleware enabled (trust_proxy_headers=true in app_settings.json)")

# Configure session
app.secret_key = _app_settings.load_or_generate_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _startup_settings['session_cookie_secure']
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # 30 days for remember-me

CORS(app, supports_credentials=True)

# Enable gzip/brotli compression for all responses
Compress(app)

# SkyTonight Blueprint (routes + scheduler management)
from skytonight_api import skytonight_bp
from skytonight_scheduler_manager import get_or_create_skytonight_scheduler

app.register_blueprint(skytonight_bp)

# Coordinate conversion regex pattern (module-level constant)
# Matches DMS format: 48d38m36.16s or 48°38'36.16"
# Pattern: optional sign, degrees, minutes, seconds
DMS_PATTERN = re.compile(r"^([+-]?\d{1,3})[d°]\s*(\d{1,2})[m']\s*(\d{1,2}(?:\.\d{1,6})?)[s\"]?$")


# ============================================================
# API Utils
# ============================================================


@app.before_request
def log_session_restoration():
    """Log when a user session is restored from cookie"""
    # Only log for non-static routes and when session exists
    if request.endpoint and not request.endpoint.startswith('static'):
        if 'username' in session and not hasattr(g, 'session_logged'):
            # Mark that we've logged this session to avoid duplicate logs
            g.session_logged = True

            # Check if this is a cookie restoration (not a fresh login)
            if request.endpoint not in ['login', 'auth_status']:
                if not session.get('_session_restored_logged'):
                    user = get_current_user()
                    if user:
                        is_permanent = session.permanent
                        logger.info(
                            f"Session restored from cookie for user {user.username} "
                            f"(permanent: {is_permanent}, endpoint: {request.endpoint})"
                        )
                        # Log once per session to avoid request spam
                        session['_session_restored_logged'] = True


@app.after_request
def set_cache_headers(response):
    """Set long-term cache headers for versioned static assets."""
    if request.endpoint == 'static' or request.path.startswith('/static/'):
        # In development/debug, always bypass browser cache so frontend changes are visible immediately.
        in_debug_mode = (
            app.debug or os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('FLASK_ENV') == 'development'
        )
        if in_debug_mode:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response

        # Versioned assets (e.g. ?v=1.2.3) are content-addressed - safe to cache for 1 year
        if request.args.get('v'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        elif request.path.startswith('/static/ico/'):
            # Icon files are frequently replaced with same filenames across releases.
            # Force revalidation for unversioned icon URLs to avoid stale homescreen/app icons.
            response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        else:
            # Unversioned static assets get a short cache with revalidation
            response.headers['Cache-Control'] = 'public, max-age=3600, must-revalidate'
    return response


@app.route('/')
def index():
    """Render main dashboard or redirect to login"""
    if 'username' not in session:
        return redirect(url_for('login_page'))

    # Get version for cache busting
    version = get_repo_version()

    return render_template('index.html', version=version)


@app.route('/login')
def login_page():
    """Render login page - redirect to dashboard if already authenticated"""
    if 'username' in session:
        return redirect(url_for('index'))
    # Get version for cache busting
    version = get_repo_version()

    return render_template('login.html', version=version)


@app.route('/manifest.webmanifest')
def web_manifest():
    """Serve PWA web manifest (English / default)"""
    response = send_from_directory(STATIC_DIR, 'manifest.webmanifest', mimetype='application/manifest+json')
    response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response


@app.route('/manifest.<lang>.webmanifest')
def web_manifest_localized(lang):
    """Serve localized PWA web manifest"""
    allowed = {'fr', 'es', 'de', 'it', 'pt'}
    if lang not in allowed:
        return '', 404
    response = send_from_directory(STATIC_DIR, f'manifest.{lang}.webmanifest', mimetype='application/manifest+json')
    response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response


@app.route('/sw.js')
def service_worker():
    """Serve service worker from root scope for full-app coverage"""
    response = send_from_directory(STATIC_DIR, 'sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@app.route('/offline.html')
def offline_page():
    """Serve offline fallback page used by service worker"""
    return send_from_directory(STATIC_DIR, 'offline.html')


@app.route('/robots.txt')
def robots_txt():
    """Serve robots.txt from root path"""
    response = send_from_directory(STATIC_DIR, 'robots.txt', mimetype='text/plain')
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


# ============================================================
# Authentication API
# ============================================================


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login endpoint"""
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
        if user:
            # Set session to permanent BEFORE setting session data
            # This ensures the cookie is created with the correct expiration
            session.permanent = remember_me

            session['user_id'] = user.user_id
            session['username'] = user.username
            session['role'] = user.role

            # Check if using default password
            using_default_password = user.is_using_default_password()

            # Log successful login with remember_me status
            logger.info(
                f"Successful login for user {username} "
                + f"(remember_me: {remember_me}, permanent_session: {session.permanent})"
            )

            return jsonify(
                {
                    'status': 'success',
                    'user_id': user.user_id,
                    'username': user.username,
                    'role': user.role,
                    'using_default_password': using_default_password,
                }
            )
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            return jsonify({'error': 'Invalid credentials', 'error_key': 'auth.invalid_credentials'}), 401
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Internal server error', 'error_key': 'auth.internal_server_error'}), 500


@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """Logout endpoint"""
    username = session.get('username')
    was_permanent = session.permanent
    session.clear()

    logger.info(f"User {username} logged out (was_permanent: {was_permanent})")

    # session.clear() handles cookie removal properly
    return jsonify({'status': 'success'})


@app.route('/api/auth/status', methods=['GET'])
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
                }
            )
    return jsonify({'authenticated': False})


@app.route('/api/auth/change-password', methods=['POST'])
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


@app.route('/api/auth/preferences', methods=['GET'])
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


@app.route('/api/auth/preferences', methods=['PUT'])
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

        logger.warning(f"Preference update rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error updating preferences for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# Web Push API
# ============================================================


@app.route('/api/push/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    """Return the VAPID public key needed by the browser to subscribe."""
    try:
        from push_manager import get_vapid_public_key as _get_key

        return jsonify({'public_key': _get_key()})
    except Exception as e:
        logger.error(f"Failed to get VAPID public key: {e}")
        return jsonify({'error': 'Push not available'}), 503


@app.route('/api/push/vapid-config-status', methods=['GET'])
@login_required
def get_vapid_config_status():
    """Return whether the VAPID contact email is properly configured."""
    try:
        from push_manager import get_vapid_contact_status

        return jsonify(get_vapid_contact_status())
    except Exception as e:
        logger.error(f"Failed to get VAPID config status: {e}")
        return jsonify({'ok': False, 'reason': 'error'}), 500


@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    """Store a push subscription for the current user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        data = request.json or {}
        subscription = data.get('subscription')
        if not isinstance(subscription, dict) or not subscription.get('endpoint'):
            return jsonify({'error': 'Invalid subscription object'}), 400

        endpoint = subscription['endpoint']
        existing = current_user.push_subscriptions
        if not any(s.get('endpoint') == endpoint for s in existing):
            from datetime import datetime as _dt

            existing.append(
                {
                    'endpoint': endpoint,
                    'keys': subscription.get('keys', {}),
                    'created_at': _dt.now().isoformat(),
                }
            )
            user_manager.save_users()
            logger.info(f"Push subscription added for user {current_user.username}")

        return jsonify({'status': 'subscribed'})
    except Exception as e:
        logger.error(f"Error storing push subscription: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/push/subscriptions', methods=['GET'])
@login_required
def push_list_subscriptions():
    """List push subscriptions for the current user (safe summary, no full endpoints)."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        def _provider(endpoint):
            from urllib.parse import urlparse

            try:
                host = urlparse(endpoint).hostname or ''
            except Exception:  # pragma: no cover  # urlparse is robust; can't raise on string input
                host = ''
            if host == 'web.push.apple.com' or host.endswith('.push.apple.com'):
                return 'apple'
            if host == 'fcm.googleapis.com' or host.endswith('.googleapis.com'):
                return 'google'
            if host == 'push.services.mozilla.com' or host.endswith('.mozilla.com'):
                return 'mozilla'
            return 'other'

        subs = [
            {
                'index': i,
                'provider': _provider(s.get('endpoint', '')),
                'created_at': s.get('created_at', ''),
                'endpoint_tail': s.get('endpoint', '')[-20:],
            }
            for i, s in enumerate(current_user.push_subscriptions)
        ]
        return jsonify({'subscriptions': subs})
    except Exception as e:
        logger.error(f"Error listing push subscriptions: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/push/subscriptions', methods=['DELETE'])
@login_required
def push_delete_all_subscriptions():
    """Remove all server-side push subscriptions for the current user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        count = len(current_user.push_subscriptions)
        current_user.push_subscriptions = []
        user_manager.save_users()
        logger.info(f"All {count} push subscription(s) removed for {current_user.username}")
        return jsonify({'removed': count})
    except Exception as e:
        logger.error(f"Error removing push subscriptions: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/push/test/<trigger_id>', methods=['POST'])
@login_required
def push_test_trigger(trigger_id):
    """Fire a realistic test push for a specific trigger (N1–N7), bypassing condition checks."""
    _TRIGGER_PAYLOADS = {
        'N1': ('push_n1_title', 'push_n1_body', {'minutes': 14}, '/#astrodex/plan-my-night', 'normal'),
        'N2': ('push_n2_title', 'push_n2_body', {'name': 'M42', 'minutes': 4}, '/#astrodex/plan-my-night', 'normal'),
        'N3': ('push_n3_title', 'push_n3_solar_body', {'minutes': 8}, '/#spaceflight/iss', 'high'),
        'N4': ('push_n4_title', 'push_n4_body', {'minutes': 28}, '/#forecast-astro/moon', 'normal'),
        'N5': ('push_n5_title', 'push_n5_body', {'minutes': 22}, '/#forecast-astro/sun', 'normal'),
        'N6': (
            'push_n6_title',
            'push_n6_body',
            {'minutes': 18, 'time': '23:45'},
            '/#forecast-astro/astro-weather',
            'normal',
        ),
        'N7': ('push_n7_title', 'push_n7_body', {'kp': '6.3', 'visibility': 'Good'}, '/#forecast-astro/aurora', 'high'),
    }
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401
        if trigger_id not in _TRIGGER_PAYLOADS:
            return jsonify({'error': f'Unknown trigger. Valid: {list(_TRIGGER_PAYLOADS)}'}), 400
        if not current_user.push_subscriptions:
            return jsonify({'error': 'No push subscriptions for this user'}), 400

        from push_manager import send_push
        from i18n_utils import get_translated_message

        lang = current_user.preferences.get('language', 'en')

        def t(key, **params):
            return get_translated_message(f'settings.{key}', language=lang, **params)

        title_key, body_key, body_params, url, urgency = _TRIGGER_PAYLOADS[trigger_id]
        payload = {
            'title': t(title_key),
            'body': t(body_key, **body_params),
            'icon': '/static/ico/android/launchericon-192x192.png',
            'badge': '/static/ico/android/launchericon-72x72.png',
            'tag': f'{trigger_id}-test',
            'data': {'url': url},
        }

        n = len(current_user.push_subscriptions)
        delivered = 0
        dead_endpoints = []
        for sub in current_user.push_subscriptions:
            ok = send_push(
                {'endpoint': sub['endpoint'], 'keys': sub.get('keys', {})}, payload, ttl=300, urgency=urgency
            )
            if ok:
                delivered += 1
            else:
                dead_endpoints.append(sub['endpoint'])

        if dead_endpoints:
            current_user.push_subscriptions = [
                s for s in current_user.push_subscriptions if s.get('endpoint') not in dead_endpoints
            ]
            user_manager.save_users()

        logger.info(
            f"Test push [{trigger_id}] for {current_user.username}: {delivered}/{n} delivered — {payload['body']}"
        )
        return jsonify(
            {
                'trigger': trigger_id,
                'delivered': delivered,
                'total': n,
                'title': payload['title'],
                'body': payload['body'],
            }
        )
    except Exception as e:
        logger.error(f"Error sending test push [{trigger_id}]: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/push/test', methods=['POST'])
@login_required
def push_test():
    """Send an immediate test push to the current user (all subscriptions)."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401
        if not current_user.push_subscriptions:
            return jsonify({'error': 'No push subscriptions for this user'}), 400

        from push_manager import send_push

        n = len(current_user.push_subscriptions)
        delivered = 0
        dead_endpoints = []
        for sub in current_user.push_subscriptions:
            ok = send_push(
                {'endpoint': sub['endpoint'], 'keys': sub.get('keys', {})},
                {
                    'title': 'MyAstroBoard test',
                    'body': 'Push notifications are working!',
                    'icon': '/static/ico/android/launchericon-192x192.png',
                    'badge': '/static/ico/android/launchericon-72x72.png',
                    'tag': 'push-test',
                    'data': {'url': '/#my-settings/notifications'},
                },
                ttl=60,
                urgency='high',
            )
            if ok:
                delivered += 1
            else:
                dead_endpoints.append(sub['endpoint'])
        if dead_endpoints:
            current_user.push_subscriptions = [
                s for s in current_user.push_subscriptions if s.get('endpoint') not in dead_endpoints
            ]
            user_manager.save_users()
            logger.info(f"Removed {len(dead_endpoints)} dead subscription(s) for {current_user.username}")
        logger.info(f"Test push for {current_user.username}: {delivered}/{n} delivered")
        return jsonify({'delivered': delivered, 'total': n, 'cleaned': len(dead_endpoints)})
    except Exception:
        logger.error("Error sending test push", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/push/unsubscribe', methods=['DELETE'])
@login_required
def push_unsubscribe():
    """Remove a push subscription for the current user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required'}), 401

        data = request.json or {}
        endpoint = data.get('endpoint')
        if not endpoint:
            return jsonify({'error': 'endpoint is required'}), 400

        before = len(current_user.push_subscriptions)
        current_user.push_subscriptions = [s for s in current_user.push_subscriptions if s.get('endpoint') != endpoint]
        if len(current_user.push_subscriptions) < before:
            user_manager.save_users()
            logger.info(f"Push subscription removed for user {current_user.username}")

        return jsonify({'status': 'unsubscribed'})
    except Exception as e:
        logger.error(f"Error removing push subscription: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# User Management API (Admin only)
# ============================================================


@app.route('/api/users', methods=['GET'])
@admin_required
def list_users():
    """List all users (admin only)"""
    users = user_manager.list_users()
    return jsonify(users)


@app.route('/api/users', methods=['POST'])
@admin_required
def create_user():
    """Create a new user (admin only)"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')

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

        user = user_manager.create_user(username, password, role)
        return jsonify(
            {'status': 'success', 'user': {'username': user.username, 'role': user.role, 'created_at': user.created_at}}
        )
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.invalid_input'

        if error_text.startswith('User ') and error_text.endswith('already exists'):
            error_key = 'users.username_already_exists'
        elif error_text.startswith('Invalid role'):
            error_key = 'users.invalid_role'

        logger.warning(f"User creation failed: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/users/<user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update a user (admin only)"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')

        if not username and not password and not role:
            return (
                jsonify({'error': 'Username, password or role required', 'error_key': 'users.required_update_payload'}),
                400,
            )

        logger.info(f"Updating user {user_id}, available users: {list(user_manager.users.keys())}")
        user = user_manager.update_user(user_id, username, password, role)
        return jsonify(
            {'status': 'success', 'user': {'user_id': user.user_id, 'username': user.username, 'role': user.role}}
        )
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.invalid_input'

        if error_text.startswith('User with ID ') and error_text.endswith(' not found'):
            error_key = 'users.user_not_found'
        elif error_text.startswith('Username ') and error_text.endswith(' already taken'):
            error_key = 'users.username_already_taken'
        elif error_text.startswith('Invalid role'):
            error_key = 'users.invalid_role'

        logger.warning(f"User update failed for user_id {user_id}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/users/<user_id>', methods=['DELETE'])
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


@app.route('/api/config', methods=['GET'])
@login_required
def get_config_api():
    """Get current configuration"""
    config = load_config()
    return jsonify(config)


@app.route('/api/config', methods=['POST'])
@admin_required
def update_config_api():
    """
    Update configuration.
    Automatically detects and handles location changes (latitude, longitude, elevation, timezone).
    Triggers cache reset when location parameters are modified.
    """
    config = request.json

    # Load old config to detect changes
    old_config = load_config()
    old_location = old_config.get('location', {})
    new_location = config.get('location', {})

    # Check if location parameters have changed
    location_changed = (
        old_location.get('latitude') != new_location.get('latitude')
        or old_location.get('longitude') != new_location.get('longitude')
        or old_location.get('elevation') != new_location.get('elevation')
        or old_location.get('timezone') != new_location.get('timezone')
    )

    # Ensure Astrodex config exists with defaults
    if 'astrodex' not in config:
        config['astrodex'] = {"private": False}

    # Migrate legacy top-level 'constraints' → skytonight.constraints
    legacy_constraints = config.pop('constraints', None)

    # Ensure SkyTonight block exists; deep-merge partial incoming skytonight
    # with the full existing skytonight config so that settings not controlled
    # by the settings UI (scheduler, datasets, preferred_name_order …) are
    # never silently discarded.
    old_skytonight = old_config.get('skytonight') if isinstance(old_config, dict) else None
    if not isinstance(old_skytonight, dict):
        old_skytonight = {}

    incoming_skytonight = config.get('skytonight')
    if not isinstance(incoming_skytonight, dict):
        config['skytonight'] = dict(old_skytonight)
    else:
        merged_st = dict(old_skytonight)
        for _k, _v in incoming_skytonight.items():
            if isinstance(_v, dict) and isinstance(merged_st.get(_k), dict):
                merged_st[_k] = {**merged_st[_k], **_v}
            else:
                merged_st[_k] = _v
        config['skytonight'] = merged_st

    # Protect horizon_profile from accidental data-loss: only allow an empty
    # array to overwrite a non-empty saved profile when the frontend explicitly
    # sent the _horizon_cleared flag (user pressed the Clear button).
    new_constraints = config['skytonight'].get('constraints', {})
    incoming_constraints_raw = (
        (incoming_skytonight or {}).get('constraints', {}) if isinstance(incoming_skytonight, dict) else {}
    )
    horizon_cleared = bool(incoming_constraints_raw.get('_horizon_cleared', False))
    old_horizon = old_skytonight.get('constraints', {}).get('horizon_profile', [])
    new_horizon = new_constraints.get('horizon_profile', [])
    if not horizon_cleared and not new_horizon and old_horizon:
        new_constraints['horizon_profile'] = old_horizon
    # Always strip the internal flag before saving to disk
    new_constraints.pop('_horizon_cleared', None)

    # Apply migrated legacy constraints when skytonight.constraints was absent
    if legacy_constraints and not config['skytonight'].get('constraints'):
        config['skytonight']['constraints'] = legacy_constraints

    config['skytonight']['enabled'] = True

    # Validate light pollution fields
    _bortle_val = new_location.get('bortle')
    _sqm_val = new_location.get('sqm')
    if _bortle_val is not None:
        try:
            _b = int(_bortle_val)
            if not (1 <= _b <= 9):
                raise ValueError()
            new_location['bortle'] = _b
        except (TypeError, ValueError):
            return jsonify({"error": "location.bortle must be an integer between 1 and 9"}), 400
    if _sqm_val is not None:
        try:
            _s = float(_sqm_val)
            if _s <= 0:
                raise ValueError()
            new_location['sqm'] = _s
        except (TypeError, ValueError):
            return jsonify({"error": "location.sqm must be a positive float (mag/arcsec²)"}), 400
    config['location'] = new_location

    # Preserve location_configured flag if not explicitly provided
    if 'location_configured' not in config:
        config['location_configured'] = old_config.get('location_configured', False)

    # Save the new config
    save_config(config)

    # If location changed, reset astronomical caches immediately
    if location_changed:
        logger.warning("Location parameters changed! Resetting astronomical caches immediately.")
        cache_store.reset_all_caches()
        cache_store.update_location_config(new_location)

    return jsonify(
        {
            "status": "success",
            "config": config,
            "cache_reset": location_changed,
            "message": "Configuration updated" + (" and cache reset" if location_changed else ""),
        }
    )


@app.route('/api/connectors', methods=['GET'])
@login_required
def list_connectors_api():
    """List all available connectors with their installed/enabled state."""
    from connectors import REGISTRY
    config = load_config()
    connectors_cfg = config.get("connectors", {})
    result = []
    for name, cls in REGISTRY.items():
        cfg = connectors_cfg.get(name, {})
        result.append({
            "name": name,
            "label": cls.label,
            "description": cls.description,
            "min_version": cls.min_version,
            "homepage": cls.homepage,
            "modules": cls.MODULES,
            "installed": bool(cfg.get("url")),
            "enabled": bool(cfg.get("enabled")) and bool(cfg.get("url")),
            "config": cfg,
        })
    return jsonify(result)


@app.route('/api/connectors/allsky/status', methods=['GET'])
@login_required
def allsky_status_api():
    """Return cached AllSky sensor data (allskydata.json)."""
    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return jsonify({"error": "AllSky connector not configured"}), 404
    if not allsky_cfg.get("modules", {}).get("sensor_data", {}).get("enabled"):
        return jsonify({"error": "sensor_data module not enabled"}), 404

    data = cache_store._allsky_sensor_cache.get("data")
    if data is None:
        from connectors.allsky_connector import AllSkyConnector
        data = AllSkyConnector(allsky_cfg).fetch_sensor_data()
        cache_store._allsky_sensor_cache["data"] = data
        import time
        cache_store._allsky_sensor_cache["timestamp"] = time.time()
    return jsonify(data)


@app.route('/api/connectors/allsky/health', methods=['GET'])
@login_required
def allsky_health_api():
    """Run a per-module health check against the AllSky instance."""
    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("url"):
        return jsonify({"reachable": False, "modules": {}, "error": "AllSky URL not configured"}), 200

    import time
    cached = cache_store._allsky_health_cache
    if cached.get("data") and (time.time() - cached.get("timestamp", 0)) < 120:
        return jsonify(cached["data"])

    from connectors.allsky_connector import AllSkyConnector
    result = AllSkyConnector(allsky_cfg).health_check()
    cache_store._allsky_health_cache["data"] = result
    cache_store._allsky_health_cache["timestamp"] = time.time()
    return jsonify(result)


@app.route('/api/connectors/allsky/urls', methods=['GET'])
@login_required
def allsky_urls_api():
    """Return proxy URLs for all enabled AllSky modules.

    Returns /api/connectors/allsky/proxy?module=<slug> paths so the browser
    never contacts AllSky directly — works behind a reverse proxy / HTTPS.
    """
    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return jsonify({"error": "AllSky connector not configured"}), 404

    date_str = request.args.get("date")
    from connectors.allsky_connector import AllSkyConnector
    direct_urls = AllSkyConnector(allsky_cfg).get_module_urls(date_str=date_str)

    date_suffix = f"&date={date_str}" if date_str else ""
    proxy_urls = {
        module: f"/api/connectors/allsky/proxy?module={module}{date_suffix}"
        for module in direct_urls
    }
    return jsonify(proxy_urls)


@app.route('/api/connectors/allsky/proxy', methods=['GET'])
@login_required
def allsky_proxy_api():
    """Proxy an AllSky resource through the backend.

    The browser requests /api/connectors/allsky/proxy?module=<slug>[&date=YYYYMMDD].
    The backend fetches the real AllSky URL and streams it back, so the browser
    only ever talks to MyAstroBoard — no mixed-content or local-network issues.
    Range requests (video seeking) are forwarded transparently.
    """
    module = request.args.get("module")
    if not module:
        return jsonify({"error": "module parameter required"}), 400

    config = load_config()
    allsky_cfg = config.get("connectors", {}).get("allsky", {})
    if not allsky_cfg.get("enabled") or not allsky_cfg.get("url"):
        return abort(503)

    date_str = request.args.get("date")
    from connectors.allsky_connector import AllSkyConnector
    import requests as _req

    direct_urls = AllSkyConnector(allsky_cfg).get_module_urls(date_str=date_str)
    target_url = direct_urls.get(module)
    if not target_url:
        return abort(404)

    upstream_headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        upstream_headers["Range"] = range_header

    try:
        r = _req.get(target_url, timeout=15, stream=True, headers=upstream_headers)
    except _req.exceptions.Timeout:
        logger.warning("AllSky proxy timeout for module %s", module)
        return abort(504)
    except _req.exceptions.RequestException as exc:
        logger.warning("AllSky proxy error for module %s: %s", module, exc)
        return abort(502)

    proxy_headers = {"Content-Type": r.headers.get("Content-Type", "application/octet-stream")}
    for hdr in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if hdr in r.headers:
            proxy_headers[hdr] = r.headers[hdr]

    return Response(
        stream_with_context(r.iter_content(chunk_size=16384)),
        status=r.status_code,
        headers=proxy_headers,
    )


@app.route('/api/admin/app-settings', methods=['GET'])
@admin_required
def get_app_settings_api():
    """Return current persistent app settings (excludes secret key)."""
    settings = _app_settings.get_app_settings()
    return jsonify(
        {
            'vapid_contact_email': settings.get('vapid_contact_email', ''),
            'trust_proxy_headers': settings.get('trust_proxy_headers', False),
            'session_cookie_secure': settings.get('session_cookie_secure', False),
        }
    )


@app.route('/api/admin/app-settings', methods=['POST'])
@admin_required
def update_app_settings_api():
    """Update persistent app settings. Returns requires_restart=True when proxy settings changed."""
    data = request.get_json(silent=True) or {}
    old_settings = _app_settings.get_app_settings()

    new_settings = {
        'vapid_contact_email': str(
            data.get('vapid_contact_email', old_settings.get('vapid_contact_email', ''))
        ).strip(),
        'trust_proxy_headers': bool(data.get('trust_proxy_headers', old_settings.get('trust_proxy_headers', False))),
        'session_cookie_secure': bool(
            data.get('session_cookie_secure', old_settings.get('session_cookie_secure', False))
        ),
    }

    _app_settings.save_app_settings(new_settings)

    # SESSION_COOKIE_SECURE can be applied live without restart
    app.config['SESSION_COOKIE_SECURE'] = new_settings['session_cookie_secure']

    # trust_proxy_headers requires restart (ProxyFix is applied to wsgi_app at startup)
    requires_restart = new_settings['trust_proxy_headers'] != old_settings.get('trust_proxy_headers', False)

    logger.info(
        f"App settings updated by {session.get('username', '?')}: "
        f"vapid_email={'set' if new_settings['vapid_contact_email'] else 'empty'}, "
        f"trust_proxy={new_settings['trust_proxy_headers']}, "
        f"session_secure={new_settings['session_cookie_secure']}"
    )
    return jsonify({'status': 'success', 'requires_restart': requires_restart})


@app.route('/api/admin/restart', methods=['POST'])
@admin_required
def restart_app_api():
    """Gracefully restart the container process. Docker restart policy handles the relaunch."""
    import signal as _signal
    import threading
    import time

    # Capture session data before leaving the request context — threads have no context.
    username = session.get('username', '?')

    def _deferred_restart():  # pragma: no cover
        time.sleep(1.5)
        logger.info(f"Container restart requested by {username} via admin UI")
        if os.path.exists('/.dockerenv'):
            # Inside Docker: kill PID 1 (gunicorn master / container entrypoint) so the
            # container exits and Docker's restart policy brings it back up.
            # Killing only the current worker PID would just cause gunicorn to replace it.
            os.kill(1, _signal.SIGTERM)
        else:
            # Local / non-Docker run: kill the current process directly.
            os.kill(os.getpid(), _signal.SIGTERM)

    threading.Thread(target=_deferred_restart, daemon=True).start()
    return jsonify({'status': 'restarting'})


@app.route('/api/metrics', methods=['GET'])
@admin_required
def get_system_metrics():
    """
    Get comprehensive system metrics including:
    - Container/VM detection with environment info
    - CPU, memory, swap, and disk information
    - Detailed disk space per folder with gauges
    - Environment process list with CPU/memory/uptime insights
    - Network statistics
    - Platform information
    """
    try:
        metrics = collect_metrics()
        return jsonify(metrics)
    except Exception:
        logger.error("Error getting system metrics")
        return jsonify({'error': 'Failed to retrieve system metrics'}), 500


@app.route('/api/config/export', methods=['GET'])
@admin_required
def export_config_api():
    """Download the raw CONFIG_FILE JSON"""
    try:
        if not os.path.isfile(CONFIG_FILE):
            return jsonify({"error": "Config file not found"}), 404

        return send_file(CONFIG_FILE, mimetype="application/json", as_attachment=True, download_name="config.json")

    except Exception as e:
        logger.error(f"Error exporting config: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/skyquality', methods=['GET'])
@login_required
def get_sky_quality_api():
    """
    Return the configured sky quality (Bortle / SQM) for the current location.

    When neither bortle nor sqm is configured, sqm_source is "not_configured"
    and all numeric fields are null - the LP integration is inactive.
    """
    from sky_quality import (
        bortle_to_sqm,
        sqm_to_bortle,
        light_pollution_factor,
        BORTLE_DESCRIPTIONS,
    )

    config = load_config()
    location = config.get('location', {})
    raw_sqm = location.get('sqm')
    raw_bortle = location.get('bortle')

    sqm: Optional[float] = None
    bortle: Optional[int] = None
    sqm_source: str = "not_configured"

    if raw_sqm is not None and raw_bortle is not None:
        # Both provided (e.g. read from lightpollutionmap.info): trust as-is.
        # Do not re-derive bortle from sqm - the two values come from the same
        # source and may use different boundary tables.
        try:
            sqm = float(raw_sqm)
            bortle = int(raw_bortle)
            sqm_source = "user_measured"
        except (TypeError, ValueError):
            pass  # malformed config value — leave sqm/bortle as None, endpoint returns 404
    elif raw_sqm is not None:
        try:
            sqm = float(raw_sqm)
            bortle = sqm_to_bortle(sqm)
            sqm_source = "user_measured"
        except (TypeError, ValueError):
            pass  # malformed config value — leave sqm/bortle as None
    elif raw_bortle is not None:
        try:
            bortle = int(raw_bortle)
            sqm = bortle_to_sqm(bortle)
            sqm_source = "bortle_midpoint"
        except (TypeError, ValueError):
            pass  # malformed config value — leave sqm/bortle as None

    if sqm is not None and bortle is not None:
        return jsonify(
            {
                "bortle": bortle,
                "sqm": round(sqm, 2),
                "sqm_source": sqm_source,
                "light_pollution_factor": light_pollution_factor(sqm),
                "description": BORTLE_DESCRIPTIONS.get(bortle, ""),
            }
        )

    return jsonify(
        {
            "bortle": None,
            "sqm": None,
            "sqm_source": "not_configured",
            "light_pollution_factor": None,
            "description": None,
        }
    )


@app.route('/api/backup/download', methods=['GET'])
@admin_required
def backup_download_api():
    """
    Create and stream a ZIP archive containing key user data files:
      - data/config.json
      - data/users.json
      - data/astrodex/  (full directory)
      - data/equipments/ (full directory)
    The archive is built in memory so no temporary file is left on disk.
    """
    # Evolutive list: each entry is (source_path, archive_name, is_dir)
    BACKUP_ENTRIES = [
        (os.path.join(DATA_DIR, 'config.json'), 'config.json', False),
        (os.path.join(DATA_DIR, 'users.json'), 'users.json', False),
        (os.path.join(DATA_DIR, 'app_settings.json'), 'app_settings.json', False),
        (os.path.join(DATA_DIR, 'astrodex'), 'astrodex', True),
        (os.path.join(DATA_DIR, 'equipments'), 'equipments', True),
    ]
    try:
        buf = io.BytesIO()
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        zip_filename = f"myastroboard_backup_{timestamp}.zip"

        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for source_path, arc_name, is_dir in BACKUP_ENTRIES:
                if is_dir:
                    if os.path.isdir(source_path):
                        for root, _dirs, files in os.walk(source_path):
                            for fname in files:
                                full_path = os.path.join(root, fname)
                                rel = os.path.relpath(full_path, os.path.dirname(source_path))
                                zf.write(full_path, rel)
                else:
                    if os.path.isfile(source_path):
                        zf.write(source_path, arc_name)

        buf.seek(0)
        logger.info(f"Backup archive created: {zip_filename}")
        return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=zip_filename)
    except Exception as e:
        logger.error(f"Error creating backup archive: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/backup/restore', methods=['POST'])
@admin_required
def backup_restore_api():
    """
    Restore user data from a previously created backup ZIP archive.
    The ZIP must contain the files/folders produced by /api/backup/download.
    Supported top-level entries: config.json, users.json, astrodex/, equipments/
    Unknown entries are silently ignored (forward-compatible).

    Validation performed before any write:
      1. Extension must be .zip
      2. Must be a valid ZIP magic
      3. Must contain at least one recognised entry
      4. JSON files (config.json, users.json) must be valid JSON

    No size cap is enforced: Astrodex portfolios containing many large
    astrophotography images can legitimately exceed hundreds of MB.  The
    endpoint is admin-only and operates on the user's own data.

    Restore is atomic per directory:
      - astrodex/ and equipments/ are cleared before the new files are written
        so stale files from the previous state do not survive the restore.
      - config.json and users.json are written directly (they are complete files).
    """
    # Evolutive allow-list: archive paths that are accepted during restore
    # Format: normalized_prefix -> destination base path
    # Entries whose value is a directory will have that directory cleared first.
    RESTORE_ALLOWED_PREFIXES = {
        'config.json': os.path.join(DATA_DIR, 'config.json'),
        'users.json': os.path.join(DATA_DIR, 'users.json'),
        'app_settings.json': os.path.join(DATA_DIR, 'app_settings.json'),
        'astrodex': os.path.join(DATA_DIR, 'astrodex'),
        'equipments': os.path.join(DATA_DIR, 'equipments'),
    }
    # Directories that must be cleared before restoring their contents
    RESTORE_CLEAR_DIRS = {'astrodex', 'equipments'}
    # JSON files whose content must be valid JSON
    RESTORE_VALIDATE_JSON = {'config.json', 'users.json', 'app_settings.json'}

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    upload = request.files['file']
    if not upload.filename or not upload.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Uploaded file must be a .zip archive'}), 400

    try:
        raw = upload.read()
        buf = io.BytesIO(raw)
        if not zipfile.is_zipfile(buf):
            return jsonify({'error': 'File is not a valid ZIP archive'}), 400
        buf.seek(0)

        # --- Phase 1: validation (no writes yet) ---
        recognised_entries = []  # (info, top_prefix, arc_path, rel_parts)
        json_blobs = {}  # arc_path -> bytes  (only for JSON-validated files)

        with zipfile.ZipFile(buf, 'r') as zf:
            for info in zf.infolist():
                arc_path = info.filename.replace('\\', '/').lstrip('/')

                if arc_path.endswith('/'):
                    continue  # directory entry

                # Match against allow-list; sanitize each path component with secure_filename
                # so no tainted data from the ZIP flows into the destination path.
                top_prefix = None
                rel_parts = []
                for prefix in RESTORE_ALLOWED_PREFIXES:
                    if arc_path == prefix or arc_path.startswith(prefix + '/'):
                        top_prefix = prefix
                        rel = arc_path[len(prefix) :].lstrip('/')
                        if rel:
                            parts = [secure_filename(p) for p in rel.split('/') if p]
                            if not all(parts):  # reject if any component empty after sanitization
                                top_prefix = None
                                continue
                            rel_parts = parts
                        break

                if top_prefix is None:
                    continue  # silently skip unrecognised entries

                # Validate JSON content before accepting
                if arc_path in RESTORE_VALIDATE_JSON:
                    blob = zf.read(info.filename)
                    try:
                        json.loads(blob)
                    except Exception:
                        return jsonify({'error': f'{arc_path} is not valid JSON - archive may be corrupt'}), 400
                    json_blobs[arc_path] = blob

                recognised_entries.append((info, top_prefix, arc_path, rel_parts))

        if not recognised_entries:
            return (
                jsonify(
                    {
                        'error': 'Archive contains no recognised backup entries '
                        '(expected config.json, users.json, app_settings.json, astrodex/ or equipments/)'
                    }
                ),
                400,
            )

        # --- Phase 2: clear target directories ---
        buf.seek(0)
        cleared_dirs = set()
        for _info, top_prefix, _arc_path, _rel_parts in recognised_entries:
            if top_prefix in RESTORE_CLEAR_DIRS and top_prefix not in cleared_dirs:
                # Derive target_dir from the static allowlist (breaks the user-data taint chain)
                target_dir = os.path.abspath(RESTORE_ALLOWED_PREFIXES[top_prefix])
                if os.path.isdir(target_dir):
                    shutil.rmtree(target_dir)
                os.makedirs(target_dir, exist_ok=True)
                cleared_dirs.add(top_prefix)
                logger.info(f"Restore: cleared directory {target_dir}")

        # --- Phase 3: write files ---
        restored_files = []
        skipped_files = []

        with zipfile.ZipFile(buf, 'r') as zf:
            for info, top_prefix, arc_path, rel_parts in recognised_entries:
                # Reconstruct destination entirely from trusted sources - no tainted data used
                base_dest = os.path.abspath(RESTORE_ALLOWED_PREFIXES[top_prefix])
                safe_dest = os.path.join(base_dest, *rel_parts) if rel_parts else base_dest
                os.makedirs(os.path.dirname(safe_dest), exist_ok=True)

                if arc_path in json_blobs:
                    # Already read and validated - write directly
                    with open(safe_dest, 'wb') as dst:
                        dst.write(json_blobs[arc_path])
                else:
                    with zf.open(info) as src, open(safe_dest, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                restored_files.append(arc_path)

        # Reload app_settings cache if it was part of the restore
        if any('app_settings.json' in f for f in restored_files):
            _app_settings.reload_app_settings()
            app.config['SESSION_COOKIE_SECURE'] = _app_settings.get_app_settings()['session_cookie_secure']

        logger.info(
            f"Backup restore completed: {len(restored_files)} files restored, "
            f"{len(skipped_files)} skipped, dirs cleared: {sorted(cleared_dirs)}"
        )
        return jsonify(
            {
                'status': 'success',
                'restored': len(restored_files),
                'skipped': len(skipped_files),
                'message': f'{len(restored_files)} file(s) restored successfully',
            }
        )

    except Exception as e:  # pragma: no cover
        logger.error(f"Error restoring backup: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/logs/export', methods=['GET'])
@admin_required
def logs_export_api():
    """
    Create and stream a ZIP archive of log files:
      - data/myastroboard.log (and rotated variants *.log.1 … *.log.5)
      - data/skytonight/logs/ (full directory)
    Built in memory - no temporary file left on disk.
    """
    # Evolutive list: each entry is (source_path, archive_folder, is_dir)
    LOG_EXPORT_ENTRIES = [
        (os.path.join(DATA_DIR, 'myastroboard.log'), 'logs', False),
        (SKYTONIGHT_LOGS_DIR, 'skytonight/logs', True),
        (SKYTONIGHT_SCHEDULER_STATUS_FILE, 'skytonight/runtime', False),
    ]
    try:
        buf = io.BytesIO()
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        zip_filename = f"myastroboard_logs_{timestamp}.zip"

        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for source_path, arc_folder, is_dir in LOG_EXPORT_ENTRIES:
                if is_dir:
                    if os.path.isdir(source_path):
                        for root, _dirs, files in os.walk(source_path):
                            for fname in files:
                                full_path = os.path.join(root, fname)
                                rel = os.path.relpath(full_path, source_path)
                                zf.write(full_path, os.path.join(arc_folder, rel))
                else:
                    # Include rotated log files (e.g. myastroboard.log.1 … .5)
                    base_dir = os.path.dirname(source_path)
                    base_name = os.path.basename(source_path)
                    candidates = [source_path] + [os.path.join(base_dir, f"{base_name}.{i}") for i in range(1, 6)]
                    for candidate in candidates:
                        if os.path.isfile(candidate):
                            zf.write(candidate, os.path.join(arc_folder, os.path.basename(candidate)))

        buf.seek(0)
        logger.info(f"Log export archive created: {zip_filename}")
        return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=zip_filename)
    except Exception as e:
        logger.error(f"Error creating log export archive: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/logs/level', methods=['GET'])
@admin_required
def get_log_level_api():
    """Return the current active log level for the file handler"""
    from logging_config import get_current_log_level

    return jsonify({'level': get_current_log_level()})


@app.route('/api/logs', methods=['GET'])
@admin_required
def get_logs_api():
    """Get application logs"""
    try:
        log_file = os.path.join(DATA_DIR, 'myastroboard.log')

        # Read log file if it exists
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = f.readlines()

            # Get parameters
            limit = int(request.args.get('limit', 500))
            level = request.args.get('level', 'all').upper()
            offset = int(request.args.get('offset', 0))

            # Filter by level if specified
            if level != 'ALL':
                filtered_logs = []
                for log_line in logs:
                    if level in log_line:
                        filtered_logs.append(log_line.strip())
                logs = filtered_logs
            else:
                logs = [log.strip() for log in logs]

            # Apply pagination (limit=0 means return all)
            total_logs = len(logs)
            if limit <= 0:
                paginated_logs = logs
            else:
                start_idx = max(0, total_logs - limit - offset)
                end_idx = total_logs - offset
                paginated_logs = logs[start_idx:end_idx] if end_idx > start_idx else []

            return jsonify(
                {
                    "status": "success",
                    "logs": paginated_logs,
                    "total": total_logs,
                    "showing": len(paginated_logs),
                    "offset": offset,
                }
            )
        else:
            return jsonify(
                {
                    "status": "success",
                    "logs": [],
                    "total": 0,
                    "showing": 0,
                    "offset": 0,
                    "message": "No log file found yet",
                }
            )
    except Exception as e:  # pragma: no cover
        logger.error(f"Error reading logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/logs/clear", methods=["POST"])
@admin_required
def clear_logs_api():
    """Clear application log file"""
    try:
        log_file = os.path.join(DATA_DIR, "myastroboard.log")

        # If the file exists, clear it
        if os.path.exists(log_file):
            open(log_file, "w").close()

        return jsonify({"status": "success", "message": "Logs cleared"})

    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/convert-coordinates', methods=['POST'])
@login_required
def convert_coordinates_api():
    """Convert DMS coordinates to decimal"""
    try:
        data = request.json
        dms_str = data.get('dms', '')

        if not isinstance(dms_str, str) or len(dms_str) > 50:
            logger.warning(f"Invalid DMS input: {dms_str}")
            return jsonify({"status": "error", "message": "Invalid input"}), 400

        # Use module-level DMS_PATTERN constant
        match = DMS_PATTERN.match(dms_str.strip())

        if match:
            degrees = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))

            # Convert to decimal
            decimal = abs(degrees) + minutes / 60 + seconds / 3600
            if degrees < 0:
                decimal = -decimal

            # Validate reasonable ranges (lat: -90 to 90, lon: -180 to 180)
            # Note: We don't know if this is lat or lon, so we use wider range
            if decimal < -180 or decimal > 180:
                return jsonify({"status": "error", "message": "Coordinate value out of valid range (-180 to 180)"}), 400

            return jsonify({"status": "success", "decimal": round(decimal, 6), "dms": dms_str})
        else:
            return jsonify({"status": "error", "message": "Invalid DMS format. Use format like: 48d38m36.16s"}), 400

    except Exception as e:  # pragma: no cover
        logger.error(f"Error converting coordinates: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/timezones', methods=['GET'])
@login_required
def get_timezones_api():
    now = datetime.now(timezone.utc)
    result = []

    for tz in sorted(available_timezones()):
        if not (tz.startswith("posix/") or tz.startswith("right/") or tz == "localtime"):
            local_time = now.astimezone(ZoneInfo(tz))
            offset = local_time.strftime('%z')

            result.append({"name": tz, "offset": offset})

    return jsonify(result)


@app.route('/api/health', methods=['GET'])
def health_api():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route('/health', methods=['GET'])
def health_simple_api():
    """Simple health check endpoint for Docker healthcheck"""
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route('/api/cache', methods=['GET'])
@login_required
def cache_health_api():
    """
    Cache status endpoint - purely informational.
    Returns whether caches are currently valid based on TTL.
    All cache management is server-side only.
    """
    status = cache_store.get_cache_init_status()
    return jsonify(
        {
            "cache_status": status["all_ready"],
            "in_progress": status["in_progress"],
            "current_step": status.get("current_step", 0),
            "total_steps": status.get("total_steps", 0),
            "step_name": status.get("step_name", ""),
            "progress_percent": status.get("progress_percent", 0),
            "details": status,
        }
    )


@app.route('/api/version', methods=['GET'])
@login_required
def get_version_api():
    """Get application version"""
    version = get_repo_version()
    version = version.strip()
    return jsonify({"version": version})


@app.route('/api/version/check-updates', methods=['GET'])
@login_required
def check_updates_api():
    """
    Check for available updates from GitHub.
    Uses server-side caching to respect GitHub API rate limits.
    Cache TTL: 4 hours
    """
    try:
        update_info = check_for_updates()
        return jsonify(update_info)
    except Exception:
        logger.error("Error in check updates API")
        return (
            jsonify(
                {
                    "current_version": get_repo_version().strip(),
                    "update_available": False,
                    "error": "Internal server error",
                }
            ),
            500,
        )


# ============================================================
# API Weather
# ============================================================


# ============================================================
# API Weather
# ============================================================


@app.route('/api/weather/forecast', methods=['GET'])
@login_required
def get_hourly_forecast_api():
    """Get hourly weather forecast"""
    try:
        cache_store.sync_cache_from_shared("weather_forecast", cache_store._weather_cache)

        # Serve from app cache if valid - avoids a live API call on every page load
        if cache_store.is_cache_valid(cache_store._weather_cache, WEATHER_CACHE_TTL):
            return jsonify(cache_store._weather_cache["data"])

        # Cache miss or stale: fetch live (requests_cache SQLite deduplicates across workers)
        forecast = get_hourly_forecast()
        if forecast is None:
            # Serve stale cache rather than returning an error
            if cache_store._weather_cache.get("data"):
                logger.warning("[WARNING] Weather API unavailable, serving stale cache")
                return jsonify(cache_store._weather_cache["data"])
            return (
                jsonify(
                    {"status": "pending", "message": "Weather data is temporarily unavailable. Please retry shortly."}
                ),
                202,
            )

        df = forecast["hourly"].copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(lambda x: x.decode() if isinstance(x, bytes) else x)
        hourly_json = json.loads(df.to_json(orient="records"))
        location = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in forecast["location"].items()}
        response_payload = {"location": location, "hourly": hourly_json}

        # Keep cache status/metrics consistent even when this endpoint performs
        # an on-demand refresh outside the scheduler cycle.
        now_ts = time.time()
        cache_store._weather_cache["data"] = response_payload
        cache_store._weather_cache["timestamp"] = now_ts
        cache_store.update_shared_cache_entry(
            "weather_forecast",
            cache_store._weather_cache["data"],
            cache_store._weather_cache["timestamp"],
        )

        return jsonify(response_payload)

    except Exception as e:
        logger.error(f"Error getting hourly forecast: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/weather/astro-analysis', methods=['GET'])
@login_required
def get_astro_weather_analysis_api():
    """Get comprehensive astrophotography weather analysis"""
    try:
        from weather_astro import get_astro_weather_analysis

        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        # Get optional hours parameter (default 24)
        hours = request.args.get('hours', 24, type=int)
        hours = min(max(hours, 1), 72)  # Limit between 1-72 hours

        analysis = get_astro_weather_analysis(hours, language=language)
        if analysis is None:
            return (
                jsonify(
                    {
                        "status": "pending",
                        "message": (
                            "Astrophotography weather analysis is temporarily unavailable. Please retry shortly."
                        ),
                    }
                ),
                202,
            )

        return jsonify(analysis)

    except Exception as e:
        logger.error(f"Error getting astro weather analysis: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/weather/astro-current', methods=['GET'])
@login_required
def get_current_astro_conditions_api():
    """Get current astrophotography conditions summary"""
    try:
        from weather_astro import get_current_astro_conditions

        conditions = get_current_astro_conditions()
        if conditions is None:
            return jsonify({"error": "Failed to fetch current astrophotography conditions"}), 500

        return jsonify(conditions)

    except Exception as e:
        logger.error(f"Error getting current astro conditions: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/weather/alerts', methods=['GET'])
@login_required
def get_weather_alerts_api():
    """Get weather alerts for astrophotography"""
    try:
        from weather_astro import get_astro_weather_analysis

        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        analysis = get_astro_weather_analysis(6, language=language)  # Next 6 hours for alerts
        if analysis is None:
            return jsonify({"alerts": [], "status": "pending"}), 200

        return jsonify(
            {
                "alerts": analysis.get("weather_alerts", []),
                "generated_at": analysis.get("generated_at"),
                "location": analysis.get("location"),
            }
        )

    except Exception as e:
        logger.error(f"Error getting weather alerts: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# API Moon & Sun
# ============================================================


@app.route("/api/moon/report", methods=["GET"])
@login_required
def get_moon_report_api():
    """Return astrophotography-grade Moon report from scheduler-managed cache."""
    try:
        if cache_store.is_cache_valid(cache_store._moon_report_cache, CACHE_TTL):
            return jsonify(cache_store._moon_report_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("moon_report", cache_store._moon_report_cache):
            if cache_store.is_cache_valid(cache_store._moon_report_cache, CACHE_TTL):
                return jsonify(cache_store._moon_report_cache["data"])

        # Avoid synchronous recomputation in request path: moon calculations can
        # exceed gunicorn timeout on small hosts and cause worker restart loops.
        stale_data = cache_store._moon_report_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not ready yet (scheduler will refresh in background).
        return (
            jsonify({"status": "pending", "message": "Moon report cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Moon report cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/moon/dark-window", methods=["GET"])
@login_required
def get_next_dark_window_api():
    """Return next astronomical moonless dark window from scheduler-managed cache."""
    try:
        if cache_store.is_cache_valid(cache_store._dark_window_report_cache, CACHE_TTL):
            return jsonify(cache_store._dark_window_report_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("dark_window", cache_store._dark_window_report_cache):
            if cache_store.is_cache_valid(cache_store._dark_window_report_cache, CACHE_TTL):
                return jsonify(cache_store._dark_window_report_cache["data"])

        # Avoid synchronous recomputation in request path: moon calculations can
        # exceed gunicorn timeout on small hosts and cause worker restart loops.
        stale_data = cache_store._dark_window_report_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not ready yet (scheduler will refresh in background).
        return (
            jsonify({"status": "pending", "message": "Dark window cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Dark Window cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/moon/next-7-nights", methods=["GET"])
@login_required
def get_next_7_nights_api():
    """Return Moon Planner next 7 nights report, from cache only"""
    try:
        if cache_store.is_cache_valid(cache_store._moon_planner_report_cache, CACHE_TTL):
            return jsonify(cache_store._moon_planner_report_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("moon_planner", cache_store._moon_planner_report_cache):
            if cache_store.is_cache_valid(cache_store._moon_planner_report_cache, CACHE_TTL):
                return jsonify(cache_store._moon_planner_report_cache["data"])

        stale_data = cache_store._moon_planner_report_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify({"status": "pending", "message": "Moon Planner cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Moon Planner cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


_moon_calendar_cache: dict = {"timestamp": 0, "data": None}
_MOON_CALENDAR_TTL = 3600  # 1 hour - recompute once per hour at most


@app.route("/api/moon/month-calendar", methods=["GET"])
@login_required
def get_moon_month_calendar_api():
    """Return next 30 nights moon/darkness data for the Plan My Night calendar widget."""
    try:
        import time as _time

        now = _time.time()
        if _moon_calendar_cache["data"] and (now - _moon_calendar_cache["timestamp"]) < _MOON_CALENDAR_TTL:
            return jsonify(_moon_calendar_cache["data"])

        cfg = load_config()
        location = cfg.get("location", {})
        lat = location.get("latitude")
        lon = location.get("longitude")
        tz = location.get("timezone", cfg.get("timezone", "UTC"))
        if lat is None or lon is None:
            return jsonify({"error": "Location not configured"}), 400

        planner = moon_planner.MoonPlanner(float(lat), float(lon), tz)
        nights = planner.next_n_nights(30)
        result = {
            "nights": [
                {
                    "date": n["date"],
                    "illumination_percent": n["moon"]["illumination_percent"],
                    "strict_hours": n["dark_hours"]["strict"],
                    "astrophoto_score": n["astrophoto_score"],
                }
                for n in nights
            ]
        }
        _moon_calendar_cache["data"] = result
        _moon_calendar_cache["timestamp"] = now
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error computing moon month calendar: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/aurora/predictions", methods=["GET"])
@login_required
def get_aurora_predictions_api():
    """Return Aurora Borealis predictions report, from cache only"""
    try:
        if cache_store.is_cache_valid(cache_store._aurora_cache, CACHE_TTL):
            return jsonify(cache_store._aurora_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("aurora", cache_store._aurora_cache):
            if cache_store.is_cache_valid(cache_store._aurora_cache, CACHE_TTL):
                return jsonify(cache_store._aurora_cache["data"])

        stale_data = cache_store._aurora_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not available
        return (
            jsonify(
                {"status": "pending", "message": "Aurora predictions cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Aurora predictions cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/seeing-forecast", methods=["GET"])
@login_required
def get_seeing_forecast_api():
    """Return atmospheric seeing forecast for planetary imaging, from cache only"""
    try:
        if cache_store.is_cache_valid(cache_store._seeing_forecast_cache, CACHE_TTL):
            return jsonify(cache_store._seeing_forecast_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("seeing_forecast", cache_store._seeing_forecast_cache):
            if cache_store.is_cache_valid(cache_store._seeing_forecast_cache, CACHE_TTL):
                return jsonify(cache_store._seeing_forecast_cache["data"])

        stale_data = cache_store._seeing_forecast_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not available
        return (
            jsonify(
                {"status": "pending", "message": "Seeing forecast cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Seeing forecast cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/object/<path:identifier>', methods=['GET'])
@login_required
def get_object_info_api(identifier):
    """Return metadata, image URL and localized description for a deep-sky object.

    Query parameters:
      lang  (str, optional) - Wikipedia language code, default 'en'

    Response (200):
    {
      "id": "NGC 2632",
      "name": "Praesepe",
      "aliases": ["M44", "Beehive Cluster", ...],
      "type": "Open Cluster",
      "coordinates": {"ra": 130.1, "dec": 19.67},
      "description": "...",
      "description_title": "Beehive Cluster",
      "image": {"url": "...", "credit": "DSS2 / SkyView (NASA GSFC)"}
    }

    If the object is not found, returns 404 with {"error": "not_found"}.
    If the identifier is invalid, returns 400 with {"error": "invalid_identifier"}.
    """
    from object_info import is_safe_identifier as _oi_safe, get_object_info as _oi_get

    lang = request.args.get('lang', 'en', type=str)
    # Sanitize lang to a safe value
    lang = str(lang).strip()[:8]

    # Validate identifier characters before any processing
    if not _oi_safe(identifier):
        return jsonify({'error': 'invalid_identifier'}), 400

    try:
        data = _oi_get(identifier, lang=lang)
    except Exception as exc:
        logger.error(f'Error fetching object info for {identifier!r}: {exc}')
        return jsonify({'error': 'Internal server error'}), 500

    error = data.get('error')
    if error == 'invalid_identifier':
        return jsonify(data), 400
    # not_found is a normal outcome (Moon, comets, personal objects not in SIMBAD)
    # return 200 so browsers don't log a console error
    return jsonify(data)


@app.route("/api/iss/passes", methods=["GET"])
@login_required
def get_iss_passes_api():
    """Return ISS passes report, from cache only"""
    try:

        def _with_celestrak_status(payload: Dict[str, Any]) -> Dict[str, Any]:
            merged = dict(payload)
            merged["celestrak_status"] = iss_passes.get_celestrak_status()
            merged["tle_source"] = iss_passes.get_iss_tle_source_info()
            return merged

        days = request.args.get("days", default=20, type=int)
        days = max(1, min(days, 30))

        if cache_store.is_cache_valid(cache_store._iss_passes_cache, CACHE_TTL_ISS_PASSES):
            cached_data = cache_store._iss_passes_cache["data"]
            if isinstance(cached_data, dict) and cached_data.get("window_days") == days:
                return jsonify(_with_celestrak_status(cached_data))

        if cache_store.sync_cache_from_shared("iss_passes", cache_store._iss_passes_cache):
            if cache_store.is_cache_valid(cache_store._iss_passes_cache, CACHE_TTL_ISS_PASSES):
                cached_data = cache_store._iss_passes_cache["data"]
                if isinstance(cached_data, dict) and cached_data.get("window_days") == days:
                    return jsonify(_with_celestrak_status(cached_data))

        return (
            jsonify({"status": "pending", "message": "ISS passes cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting ISS passes cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/iss/location", methods=["GET"])
@login_required
def get_iss_location_api():
    """Return current ISS ground position and ±50-minute orbit track, computed from cached TLE."""
    try:
        config = load_config()
        location = config.get("location", {})
        lat = location.get("latitude")
        lon = location.get("longitude")
        elev = float(location.get("elevation", 0) or 0)
        position = iss_passes.get_current_position(
            latitude=float(lat) if lat is not None else None,
            longitude=float(lon) if lon is not None else None,
            elevation_m=elev,
        )
        return jsonify(position)
    except RuntimeError:
        logger.exception("Runtime error computing ISS location")
        return jsonify({'error': 'Service temporarily unavailable'}), 503
    except Exception as exc:
        logger.error(f"Error computing ISS location: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/iss/celestrak/restart", methods=["POST"])
@login_required
def restart_iss_celestrak_crawl_api():
    """Clear Celestrak block flag after explicit operator confirmation in UI."""
    try:
        status = iss_passes.clear_celestrak_block_flag()
        return jsonify(
            {
                "status": "ok",
                "message": "Celestrak block flag cleared. Next crawl may query Celestrak again.",
                "celestrak_status": status,
            }
        )
    except Exception as exc:
        logger.error(f"Error resetting Celestrak block flag: {exc}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/spaceflight/launches", methods=["GET"])
@login_required
def get_spaceflight_launches_api():
    """Return upcoming and past launches from the Launch Library 2 cache."""
    try:
        if cache_store.is_cache_valid(cache_store._spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES):
            return jsonify(cache_store._spaceflight_launches_cache["data"])
        cache_store.sync_cache_from_shared("spaceflight_launches", cache_store._spaceflight_launches_cache)
        if cache_store.is_cache_valid(cache_store._spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES):
            return jsonify(cache_store._spaceflight_launches_cache["data"])

        stale_data = cache_store._spaceflight_launches_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return jsonify({"error": "cache_not_ready"}), 503
    except Exception as exc:
        logger.error(f"Error fetching spaceflight launches: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/spaceflight/astronauts", methods=["GET"])
@login_required
def get_spaceflight_astronauts_api():
    """Return ISS crew and astronauts in space from the Launch Library 2 cache."""
    try:
        if cache_store.is_cache_valid(cache_store._spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS):
            return jsonify(cache_store._spaceflight_astronauts_cache["data"])
        cache_store.sync_cache_from_shared("spaceflight_astronauts", cache_store._spaceflight_astronauts_cache)
        if cache_store.is_cache_valid(cache_store._spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS):
            return jsonify(cache_store._spaceflight_astronauts_cache["data"])

        stale_data = cache_store._spaceflight_astronauts_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return jsonify({"error": "cache_not_ready"}), 503
    except Exception as exc:
        logger.error(f"Error fetching spaceflight astronauts: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/spaceflight/events", methods=["GET"])
@login_required
def get_spaceflight_events_api():
    """Return upcoming space events from the Launch Library 2 cache."""
    try:
        if cache_store.is_cache_valid(cache_store._spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS):
            return jsonify(cache_store._spaceflight_events_cache["data"])
        cache_store.sync_cache_from_shared("spaceflight_events", cache_store._spaceflight_events_cache)
        if cache_store.is_cache_valid(cache_store._spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS):
            return jsonify(cache_store._spaceflight_events_cache["data"])

        stale_data = cache_store._spaceflight_events_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return jsonify({"error": "cache_not_ready"}), 503
    except Exception as exc:
        logger.error(f"Error fetching spaceflight events: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/spaceflight/img/<filename>", methods=["GET"])
@login_required
def spaceflight_image(filename):
    """Serve a locally cached spaceflight/astronaut image.
    If the image file is missing but a .url sidecar exists, re-download it
    on the fly so stale cache entries pointing to deleted files self-heal.
    """
    if not re.match(r'^[a-f0-9]{32}\.(jpg|jpeg|png|webp|gif)$', filename):
        return jsonify({"error": "Invalid filename"}), 400
    img_dir = os.path.realpath(os.path.join(DATA_DIR_CACHE, 'spaceflight_images'))
    local_path = os.path.realpath(os.path.join(img_dir, filename))
    # Prevent path traversal: resolved path must be inside img_dir
    if not local_path.startswith(img_dir + os.sep):  # pragma: no cover  # regex above prevents path traversal
        return jsonify({"error": "Invalid filename"}), 400
    if not os.path.exists(local_path):
        sidecar = local_path + '.url'
        if os.path.exists(sidecar):
            try:
                with open(sidecar, 'r', encoding='utf-8') as sf:
                    original_url = sf.read().strip()
                import requests as _req

                resp = _req.get(original_url, timeout=15, stream=True)
                resp.raise_for_status()
                os.makedirs(img_dir, exist_ok=True)
                with open(local_path, 'wb') as fh:
                    for chunk in resp.iter_content(chunk_size=8192):
                        fh.write(chunk)
                logger.info("Re-downloaded missing spaceflight image: %s", filename)
            except Exception as exc:
                logger.warning("Could not re-download spaceflight image %s: %s", filename, exc)
                return jsonify({"error": "Image unavailable"}), 404
        else:
            return jsonify({"error": "Image not found"}), 404
    return send_from_directory(img_dir, filename, max_age=86400)


@app.route("/api/spaceflight/launch/<launch_id>/vidurls", methods=["GET"])
@login_required
def get_spaceflight_launch_vidurls(launch_id):
    """Return live video URLs for a specific launch from the LL2 detail endpoint.
    Results are cached in-process for 5 minutes to protect the free-tier rate limit.
    Only call this for launches where webcast_live=true."""
    if not re.match(r'^[0-9a-f-]{36}$', launch_id):
        return jsonify({"error": "Invalid launch ID"}), 400
    try:
        from spaceflight_tracker import get_launch_vidurls

        vidurls = get_launch_vidurls(launch_id)
        return jsonify({"vidURLs": vidurls})
    except Exception as exc:
        logger.error(f"Error fetching vidURLs for launch {launch_id}: {exc}")
        return jsonify({"vidURLs": []}), 200


@app.route("/api/translate/on-demand", methods=["POST"])
@login_required
def translate_on_demand_api():
    """Translate dynamic third-party text for non-English users on demand."""
    try:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text") or "").strip()
        target_lang = str(payload.get("target_lang") or "").split(",")[0].split("-")[0].lower().strip()
        source_lang = str(payload.get("source_lang") or "en").split(",")[0].split("-")[0].lower().strip()

        if not text:
            return jsonify({"error": "missing_text"}), 400
        if len(text) > 5000:
            return jsonify({"error": "text_too_long"}), 400

        supported_languages = set(I18nManager.get_supported_languages())
        if target_lang not in supported_languages:
            return jsonify({"error": "unsupported_target_language"}), 400

        result = translate_text_on_demand(
            text=text,
            source_lang=source_lang or "en",
            target_lang=target_lang,
        )
        return jsonify(result), 200

    except Exception as exc:
        logger.error(f"Error translating on demand: {exc}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/sun/today", methods=["GET"])
@login_required
def get_sun_today_api():
    """Return Sun today report, from cache only"""
    try:
        if cache_store.is_cache_valid(cache_store._sun_report_cache, CACHE_TTL):
            return jsonify(cache_store._sun_report_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("sun_report", cache_store._sun_report_cache):
            if cache_store.is_cache_valid(cache_store._sun_report_cache, CACHE_TTL):
                return jsonify(cache_store._sun_report_cache["data"])

        stale_data = cache_store._sun_report_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify({"status": "pending", "message": "Sun report cache is not ready yet. Please try again shortly."}),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Sun report cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/sun/next-eclipse", methods=["GET"])
@login_required
def get_solar_eclipse_api():
    """Return next solar eclipse, from cache only"""
    try:
        if cache_store.is_cache_valid(cache_store._solar_eclipse_cache, CACHE_TTL):
            return jsonify(cache_store._solar_eclipse_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("solar_eclipse", cache_store._solar_eclipse_cache):
            if cache_store.is_cache_valid(cache_store._solar_eclipse_cache, CACHE_TTL):
                return jsonify(cache_store._solar_eclipse_cache["data"])

        stale_data = cache_store._solar_eclipse_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify(
                {"status": "pending", "message": "Solar eclipse cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Solar Eclipse cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/moon/next-eclipse", methods=["GET"])
@login_required
def get_lunar_eclipse_api():
    """Return next lunar eclipse, from cache only"""
    try:
        if cache_store.is_cache_valid(cache_store._lunar_eclipse_cache, CACHE_TTL):
            return jsonify(cache_store._lunar_eclipse_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("lunar_eclipse", cache_store._lunar_eclipse_cache):
            if cache_store.is_cache_valid(cache_store._lunar_eclipse_cache, CACHE_TTL):
                return jsonify(cache_store._lunar_eclipse_cache["data"])

        stale_data = cache_store._lunar_eclipse_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache non disponible
        return (
            jsonify(
                {"status": "pending", "message": "Lunar eclipse cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Lunar Eclipse cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/events/upcoming", methods=["GET"])
@login_required
def get_upcoming_events_api():
    """Return aggregated upcoming astronomical events (eclipses, auroras, planetary, phenomena, solar system events)"""
    try:
        config = load_config()
        location = config.get("location", {})
        latitude = location.get("latitude", 0)
        longitude = location.get("longitude", 0)
        user_timezone = location.get("timezone", "UTC")

        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        # Get cached event data
        solar_eclipse_data = None
        lunar_eclipse_data = None
        aurora_data = None
        iss_passes_data = None
        moon_phases_data = None
        planetary_events_data = None
        special_phenomena_data = None
        solar_system_events_data = None

        # Try to get solar eclipse data
        if cache_store.is_cache_valid(cache_store._solar_eclipse_cache, CACHE_TTL_SOLAR_ECLIPSE):
            solar_eclipse_data = cache_store._solar_eclipse_cache.get("data")
        elif cache_store.sync_cache_from_shared("solar_eclipse", cache_store._solar_eclipse_cache):
            if cache_store.is_cache_valid(cache_store._solar_eclipse_cache, CACHE_TTL_SOLAR_ECLIPSE):
                solar_eclipse_data = cache_store._solar_eclipse_cache.get("data")

        # Try to get lunar eclipse data
        if cache_store.is_cache_valid(cache_store._lunar_eclipse_cache, CACHE_TTL_LUNAR_ECLIPSE):
            lunar_eclipse_data = cache_store._lunar_eclipse_cache.get("data")
        elif cache_store.sync_cache_from_shared("lunar_eclipse", cache_store._lunar_eclipse_cache):
            if cache_store.is_cache_valid(cache_store._lunar_eclipse_cache, CACHE_TTL_LUNAR_ECLIPSE):
                lunar_eclipse_data = cache_store._lunar_eclipse_cache.get("data")

        # Try to get aurora data
        if cache_store.is_cache_valid(cache_store._aurora_cache, CACHE_TTL_AURORA):
            aurora_data = cache_store._aurora_cache.get("data")
        elif cache_store.sync_cache_from_shared("aurora", cache_store._aurora_cache):
            if cache_store.is_cache_valid(cache_store._aurora_cache, CACHE_TTL_AURORA):
                aurora_data = cache_store._aurora_cache.get("data")

        # Try to get ISS passes data
        if cache_store.is_cache_valid(cache_store._iss_passes_cache, CACHE_TTL_ISS_PASSES):
            iss_passes_data = cache_store._iss_passes_cache.get("data")
        elif cache_store.sync_cache_from_shared("iss_passes", cache_store._iss_passes_cache):
            if cache_store.is_cache_valid(cache_store._iss_passes_cache, CACHE_TTL_ISS_PASSES):
                iss_passes_data = cache_store._iss_passes_cache.get("data")

        # Try to get moon phases data
        if cache_store.is_cache_valid(cache_store._moon_planner_report_cache, CACHE_TTL_MOON_PLANNER):
            moon_phases_data = cache_store._moon_planner_report_cache.get("data")
        elif cache_store.sync_cache_from_shared("moon_planner", cache_store._moon_planner_report_cache):
            if cache_store.is_cache_valid(cache_store._moon_planner_report_cache, CACHE_TTL_MOON_PLANNER):
                moon_phases_data = cache_store._moon_planner_report_cache.get("data")

        # Try to get planetary events data
        if cache_store.is_cache_valid(cache_store._planetary_events_cache, CACHE_TTL_PLANETARY_EVENTS):
            planetary_events_data = cache_store._planetary_events_cache.get("data")
        elif cache_store.sync_cache_from_shared("planetary_events", cache_store._planetary_events_cache):
            if cache_store.is_cache_valid(cache_store._planetary_events_cache, CACHE_TTL_PLANETARY_EVENTS):
                planetary_events_data = cache_store._planetary_events_cache.get("data")

        # Try to get special phenomena data
        if cache_store.is_cache_valid(cache_store._special_phenomena_cache, CACHE_TTL_SPECIAL_PHENOMENA):
            special_phenomena_data = cache_store._special_phenomena_cache.get("data")
        elif cache_store.sync_cache_from_shared("special_phenomena", cache_store._special_phenomena_cache):
            if cache_store.is_cache_valid(cache_store._special_phenomena_cache, CACHE_TTL_SPECIAL_PHENOMENA):
                special_phenomena_data = cache_store._special_phenomena_cache.get("data")

        # Try to get solar system events data
        if cache_store.is_cache_valid(cache_store._solar_system_events_cache, CACHE_TTL_SOLAR_SYSTEM_EVENTS):
            solar_system_events_data = cache_store._solar_system_events_cache.get("data")
        elif cache_store.sync_cache_from_shared("solar_system_events", cache_store._solar_system_events_cache):
            if cache_store.is_cache_valid(cache_store._solar_system_events_cache, CACHE_TTL_SOLAR_SYSTEM_EVENTS):
                solar_system_events_data = cache_store._solar_system_events_cache.get("data")

        if special_phenomena_data:
            special_phenomena_data = _translate_special_phenomena_events(special_phenomena_data, language)

        # Translate solar system events if needed
        if solar_system_events_data and language != "en":
            solar_system_events_data = _translate_solar_system_events(solar_system_events_data, language)

        # Aggregate events
        aggregator = EventsAggregator(latitude, longitude, user_timezone, language=language)
        events = aggregator.aggregate_all_events(
            solar_eclipse_data=solar_eclipse_data,
            lunar_eclipse_data=lunar_eclipse_data,
            aurora_data=aurora_data,
            iss_passes_data=iss_passes_data,
            moon_phases_data=moon_phases_data,
            planetary_events_data=planetary_events_data,
            special_phenomena_data=special_phenomena_data,
            solar_system_events_data=solar_system_events_data,
        )

        return jsonify(events)

    except Exception as e:
        logger.error(f"Error aggregating upcoming events: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/events/planetary", methods=["GET"])
@login_required
def get_planetary_events_api():
    """Return planetary events (conjunctions, oppositions, elongations, retrograde motion)"""
    try:
        if cache_store.is_cache_valid(cache_store._planetary_events_cache, CACHE_TTL):
            return jsonify(cache_store._planetary_events_cache["data"])

        # Try shared cache first
        if cache_store.sync_cache_from_shared("planetary_events", cache_store._planetary_events_cache):
            if cache_store.is_cache_valid(cache_store._planetary_events_cache, CACHE_TTL):
                return jsonify(cache_store._planetary_events_cache["data"])

        stale_data = cache_store._planetary_events_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        return (
            jsonify(
                {
                    "status": "pending",
                    "message": "Planetary events cache is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error retrieving planetary events: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/events/phenomena", methods=["GET"])
@login_required
def get_special_phenomena_api():
    """Return special phenomena (equinoxes, solstices, zodiacal light, Milky Way visibility)"""
    try:
        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        if cache_store.is_cache_valid(cache_store._special_phenomena_cache, CACHE_TTL):
            data = cache_store._special_phenomena_cache["data"]
            return jsonify(_translate_special_phenomena_events(data, language))

        # Try shared cache first
        if cache_store.sync_cache_from_shared("special_phenomena", cache_store._special_phenomena_cache):
            if cache_store.is_cache_valid(cache_store._special_phenomena_cache, CACHE_TTL):
                data = cache_store._special_phenomena_cache["data"]
                return jsonify(_translate_special_phenomena_events(data, language))

        stale_data = cache_store._special_phenomena_cache.get("data")
        if stale_data:
            return jsonify(_translate_special_phenomena_events(stale_data, language))

        return (
            jsonify(
                {
                    "status": "pending",
                    "message": "Special phenomena cache is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error retrieving special phenomena: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/events/solarsystem", methods=["GET"])
@login_required
def get_solar_system_events_api():
    """Return solar system events (meteor showers, comets, asteroid occultations) with language support"""
    try:
        # Get language parameter from request
        requested_language = request.args.get("lang") or request.headers.get("Accept-Language", "en")
        requested_language = requested_language.split(",")[0].split("-")[0].lower()
        supported_languages = I18nManager.get_supported_languages()
        language = requested_language if requested_language in supported_languages else "en"

        if cache_store.is_cache_valid(cache_store._solar_system_events_cache, CACHE_TTL):
            data = cache_store._solar_system_events_cache["data"]
            return jsonify(_translate_solar_system_events(data, language))

        # Try shared cache first
        if cache_store.sync_cache_from_shared("solar_system_events", cache_store._solar_system_events_cache):
            if cache_store.is_cache_valid(cache_store._solar_system_events_cache, CACHE_TTL):
                data = cache_store._solar_system_events_cache["data"]
                return jsonify(_translate_solar_system_events(data, language))

        stale_data = cache_store._solar_system_events_cache.get("data")
        if stale_data:
            return jsonify(_translate_solar_system_events(stale_data, language))

        return (
            jsonify(
                {
                    "status": "pending",
                    "message": "Solar system events cache is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error retrieving solar system events: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _translate_solar_system_events(data: Dict[str, Any], language: str) -> Dict[str, Any]:
    """
    Translate solar system event descriptions based on language

    Args:
        data: Solar system events cache data
        language: Target language code

    Returns:
        Data with translated event descriptions
    """
    if language == "en":
        # English is default, no translation needed
        return data

    # Create a copy to avoid modifying cache
    translated_data = data.copy() if isinstance(data, dict) else {"events": []}
    events = translated_data.get("events", [])

    if not isinstance(events, list):
        return translated_data

    # Translate each event's title and description
    i18n = I18nManager(language)
    translated_events = []

    for event in events:
        if not isinstance(event, dict):
            translated_events.append(event)
            continue

        translated_event = event.copy()
        event_type = event.get("event_type", "")

        try:
            # Translate based on event type
            if event_type == "Meteor Shower":
                raw_data = event.get("raw_data", {})
                shower_name = raw_data.get("shower", "")
                zenith_hourly_rate = event.get("zenith_hourly_rate", "")
                parent_body = event.get("parent_body", "")

                if shower_name and zenith_hourly_rate and parent_body:
                    title = i18n.t('events_api.solar_system.meteor_shower_title', shower_name=shower_name)
                    description = i18n.t(
                        'events_api.solar_system.meteor_shower_description',
                        zenith_hourly_rate=zenith_hourly_rate,
                        parent_body=parent_body,
                    )
                    translated_event["title"] = title
                    translated_event["description"] = description

            elif event_type == "Comet Appearance":
                magnitude = event.get("magnitude", "")
                visibility = event.get("equipment_needed", "")
                raw_data = event.get("raw_data", {})
                comet_name = raw_data.get("comet", "")

                if comet_name and magnitude and visibility:
                    title = i18n.t('events_api.solar_system.comet_title', comet_name=comet_name)
                    description = i18n.t(
                        'events_api.solar_system.comet_description', magnitude=magnitude, visibility=visibility
                    )
                    translated_event["title"] = title
                    translated_event["description"] = description

            elif event_type == "Asteroid Occultation":
                title = i18n.t('events_api.solar_system.asteroid_occultation_title')
                description = i18n.t('events_api.solar_system.asteroid_occultation_description')
                translated_event["title"] = title
                translated_event["description"] = description

        except Exception as e:
            logger.debug(f"Error translating solar system event: {e}")

        translated_events.append(translated_event)

    translated_data["events"] = translated_events
    return translated_data


def _translate_special_phenomena_events(data: Dict[str, Any], language: str) -> Dict[str, Any]:
    """Translate special phenomena events that are cached with localized strings."""
    translated_data = data.copy() if isinstance(data, dict) else {"events": []}
    events = translated_data.get("events", [])

    if not isinstance(events, list):
        return translated_data

    i18n = I18nManager(language)
    translated_events = []

    def _t(key: str, fallback: str, **kwargs: Any) -> str:
        translated = i18n.t(key, **kwargs)
        if translated and translated != key:
            return translated
        if kwargs:
            try:
                return fallback.format(**kwargs)
            except Exception:
                return fallback
        return fallback

    for event in events:
        if not isinstance(event, dict):
            translated_events.append(event)
            continue

        translated_event = event.copy()

        try:
            event_type = str(event.get("event_type", ""))
            raw_data = event.get("raw_data", {}) if isinstance(event.get("raw_data"), dict) else {}
            event_key = str(raw_data.get("event", "")).strip().lower()

            if event_key == "spring_equinox":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.spring_equinox_title',
                    str(event.get("title", "Vernal Equinox (Spring)")),
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.spring_equinox_description',
                    str(
                        event.get(
                            "description",
                            "First day of spring. Equal day and night length. Sun directly above equator.",
                        )
                    ),
                )
            elif event_key == "summer_solstice":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.summer_solstice_title', str(event.get("title", "Summer Solstice"))
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.summer_solstice_description',
                    str(
                        event.get("description", "First day of summer. Longest day of the year in Northern Hemisphere.")
                    ),
                )
            elif event_key == "autumn_equinox":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.autumn_equinox_title',
                    str(event.get("title", "Autumnal Equinox (Fall)")),
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.autumn_equinox_description',
                    str(
                        event.get(
                            "description",
                            "First day of autumn. Equal day and night length. Sun directly above equator.",
                        )
                    ),
                )
            elif event_key == "winter_solstice":
                translated_event["title"] = _t(
                    'events_api.special_phenomena.winter_solstice_title', str(event.get("title", "Winter Solstice"))
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.winter_solstice_description',
                    str(
                        event.get(
                            "description", "First day of winter. Shortest day of the year in Northern Hemisphere."
                        )
                    ),
                )
            elif event_key == "zodiacal_light":
                viewing_raw = str(event.get("viewing_type", "")).strip().lower()
                if viewing_raw == "morning":
                    viewing_label = _t('events_api.special_phenomena.zodiacal_viewing_morning', 'Morning')
                else:
                    viewing_label = _t('events_api.special_phenomena.zodiacal_viewing_evening', 'Evening')

                translated_event["title"] = _t(
                    'events_api.special_phenomena.zodiacal_light_title',
                    str(event.get("title", "Zodiacal Light Visible ({viewing_type})")),
                    viewing_type=viewing_label,
                )
                translated_event["description"] = _t(
                    'events_api.special_phenomena.zodiacal_light_description',
                    str(
                        event.get(
                            "description",
                            "Faint cone of light from interplanetary dust visible during twilight."
                            " Best viewed in dark skies.",
                        )
                    ),
                )
                translated_event["viewing_type"] = viewing_label
            elif event_type == "Milky Way Core Visibility":
                gc_altitude = event.get("galactic_center_altitude")

                if gc_altitude is None:
                    gc_altitude = raw_data.get("galactic_center_altitude")
                if gc_altitude is None:
                    gc_altitude = raw_data.get("gc_altitude")

                if gc_altitude is not None:
                    altitude_text = f"{float(gc_altitude):.0f}"
                    translated_event["title"] = _t(
                        'events_api.special_phenomena.milky_way_title',
                        str(event.get("title", "Milky Way Core Visible")),
                    )
                    translated_event["description"] = _t(
                        'events_api.special_phenomena.milky_way_description',
                        str(
                            event.get(
                                "description",
                                "Galactic center visible at {gc_altitude}° altitude."
                                " Excellent night for wide-field astrophotography.",
                            )
                        ),
                        gc_altitude=altitude_text,
                    )
        except Exception as e:  # pragma: no cover
            logger.debug(f"Error translating special phenomenon event: {e}")

        translated_events.append(translated_event)

    translated_data["events"] = translated_events
    return translated_data


@app.route("/api/astro/sidereal-time", methods=["GET"])
@login_required
def get_sidereal_time_api():
    """Return sidereal time information for observation planning.

    `current` is always computed live (a few ms) so it is never stale.
    `hourly_forecast` is served from the scheduler cache (day-sensitive TTL).
    """
    try:
        config = load_config()
        location = config.get("location") if config else None
        if not location:
            return jsonify({'error': 'Location not configured'}), 400

        from sidereal_time import SiderealTimeService

        svc = SiderealTimeService(
            latitude=location["latitude"],
            longitude=location["longitude"],
            elevation=location.get("elevation", 0),
            timezone=location.get("timezone", "UTC"),
        )

        # current - always fresh, no cache needed
        current_info = svc.get_current_sidereal_info()

        # hourly_forecast - from scheduler cache (day-sensitive, refreshed at day change)
        hourly_forecast = None
        cached = cache_store._sidereal_time_cache
        if not cache_store.is_cache_valid_for_today(cached, CACHE_TTL_SIDEREAL_TIME):
            cache_store.sync_cache_from_shared("sidereal_time", cached)
        if cache_store.is_cache_valid_for_today(cached, CACHE_TTL_SIDEREAL_TIME) and cached.get("data"):
            hourly_forecast = cached["data"].get("hourly_forecast")

        return jsonify(
            {
                "location": location,
                "current": current_info,
                "hourly_forecast": hourly_forecast,
                "units": {
                    "sidereal_time": "hours (0-24, where 24h = 1 sidereal day = 23h56m4s solar time)",
                    "coordinates": "degrees",
                    "elevation": "meters",
                },
            }
        )

    except Exception as e:
        logger.error(f"Error retrieving sidereal time: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/astro/horizon-graph", methods=["GET"])
@login_required
def get_horizon_graph_api():
    """Return sun and moon horizon positions for current day"""
    try:
        if cache_store.is_cache_valid(cache_store._horizon_graph_cache, CACHE_TTL):
            return jsonify(cache_store._horizon_graph_cache["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared("horizon_graph", cache_store._horizon_graph_cache):
            if cache_store.is_cache_valid(cache_store._horizon_graph_cache, CACHE_TTL):
                return jsonify(cache_store._horizon_graph_cache["data"])

        stale_data = cache_store._horizon_graph_cache.get("data")
        if stale_data:
            return jsonify(stale_data)

        # Cache not available
        return (
            jsonify(
                {"status": "pending", "message": "Horizon graph cache is not ready yet. Please try again shortly."}
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Horizon Graph cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route("/api/tonight/best-window", methods=["GET"])
@login_required
def best_window_api():
    """
    Return best observation window for tonight, from cache only
    Modes: strict, practical, illumination
    """
    try:
        mode = request.args.get("mode", "strict")
        modes = ["strict", "practical", "illumination"]

        if mode == "all":
            results = {}
            missing_modes = []

            for current_mode in modes:
                cache_entry = cache_store._best_window_cache[current_mode]
                if cache_store.is_cache_valid(cache_entry, CACHE_TTL):
                    results[current_mode] = cache_entry["data"]
                    continue

                # Try shared cache first (other worker may have computed)
                if cache_store.sync_cache_from_shared(f"best_window_{current_mode}", cache_entry):
                    if cache_store.is_cache_valid(cache_entry, CACHE_TTL):
                        results[current_mode] = cache_entry["data"]
                        continue

                # Serve stale data when available instead of recomputing inline.
                if cache_entry.get("data") is not None:
                    results[current_mode] = cache_entry["data"]
                    continue

                missing_modes.append(current_mode)

            for current_mode in missing_modes:
                results[current_mode] = {
                    "status": "pending",
                    "message": (
                        f"Best window cache for mode '{current_mode}' is not ready yet. " "Please try again shortly."
                    ),
                }

            return jsonify({"modes": results})

        if mode not in modes:
            return jsonify({"error": "Invalid mode"}), 400

        cache_entry = cache_store._best_window_cache[mode]

        if cache_store.is_cache_valid(cache_entry, CACHE_TTL):
            return jsonify(cache_entry["data"])

        # Try shared cache first (other worker may have computed)
        if cache_store.sync_cache_from_shared(f"best_window_{mode}", cache_entry):
            if cache_store.is_cache_valid(cache_entry, CACHE_TTL):
                return jsonify(cache_entry["data"])

        # Serve stale cache when available instead of triggering a heavy inline
        # recomputation that can exceed gunicorn timeout on small hosts.
        if cache_entry.get("data") is not None:
            return jsonify(cache_entry["data"])

        # Cache non disponible
        return (
            jsonify(
                {
                    "status": "pending",
                    "message": f"Best window cache for mode '{mode}' is not ready yet. Please try again shortly.",
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Error getting Best Window cache: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# Astrodex API
# ============================================================


def _resolve_observing_night_for_plan() -> Optional[dict]:
    """Return the nautical night window for Plan My Night.

    Uses nautical dusk/dawn (sun at -12 deg) so the observing session starts
    when bright stars, planets and clusters become visible, before full
    astronomical darkness.  Falls back to SkyTonight calculation metadata
    (astronomical window) when the location is not configured or the sun
    service fails.
    """
    try:
        config = load_config()
        location = config.get('location', {})
        lat = location.get('latitude')
        lon = location.get('longitude')
        tz_name = location.get('timezone')
        if lat is not None and lon is not None and tz_name:
            tz = ZoneInfo(str(tz_name))
            sun_service = SunService(latitude=float(lat), longitude=float(lon), timezone=str(tz_name))

            def _parse(time_str: str) -> Optional[datetime]:
                text = str(time_str or '').strip()
                if not text or text == 'Not found':
                    return None
                try:
                    return datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=tz)
                except ValueError:
                    return None

            report = sun_service.get_today_report()
            dusk = _parse(report.nautical_dusk)
            dawn = _parse(report.nautical_dawn)

            if dusk is None or dawn is None or dawn <= dusk:
                report_tomorrow = sun_service.get_tomorrow_report()
                dusk = _parse(report_tomorrow.nautical_dusk)
                dawn = _parse(report_tomorrow.nautical_dawn)

            if dusk is not None and dawn is not None and dawn > dusk:
                duration_hours = (dawn - dusk).total_seconds() / 3600.0
                return {
                    'start': dusk.isoformat(),
                    'end': dawn.isoformat(),
                    'duration_hours': round(duration_hours, 2),
                }
    except Exception as error:
        logger.error(f'Error resolving observing night for plan: {error}')

    # Fallback: use SkyTonight calculation metadata (astronomical window)
    try:
        calc = load_calculation_results()
        metadata = calc.get('metadata') or {}
        night_start = metadata.get('night_start')
        night_end = metadata.get('night_end')
        if not night_start or not night_end:
            return None
        start_dt = datetime.fromisoformat(night_start)
        end_dt = datetime.fromisoformat(night_end)
        duration_hours = (end_dt - start_dt).total_seconds() / 3600.0
        return {
            'start': night_start,
            'end': night_end,
            'duration_hours': round(duration_hours, 2),
        }
    except Exception as error:
        logger.error(f'Error resolving fallback night for plan: {error}')
    return None


def _enrich_plan_entries_with_astrodex_status(plan_payload: dict, user_id: str) -> dict:
    """Attach Astrodex presence flag to each plan entry for UI actions."""
    if not isinstance(plan_payload, dict):
        return plan_payload

    plan = plan_payload.get('plan')
    if not isinstance(plan, dict):
        return plan_payload

    entries = plan.get('entries', [])
    if not isinstance(entries, list):
        return plan_payload

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        item_name = str(entry.get('name') or entry.get('target_name') or '').strip()
        catalogue = str(entry.get('catalogue') or '').strip()
        if item_name:
            entry['in_astrodex'] = astrodex.is_item_in_astrodex(user_id, item_name, catalogue)
        else:
            entry['in_astrodex'] = False

    return plan_payload


def _parse_duration_minutes(value: object) -> int:
    text = str(value or '').strip()
    if not text:
        return 0

    parts = text.split(':')
    if len(parts) != 2:
        return 0

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return 0

    if hours < 0 or minutes < 0 or minutes > 59:
        return 0

    return (hours * 60) + minutes


def _format_minutes_hhmm(minutes: int) -> str:
    safe = max(0, int(minutes))
    return f"{safe // 60}h{safe % 60:02d}"


def _compute_plan_fill_metrics(plan: dict) -> dict:
    entries = plan.get('entries', []) if isinstance(plan, dict) else []
    if not isinstance(entries, list):
        entries = []

    planned_minutes = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        planned_raw = entry.get('planned_minutes')
        try:
            planned_minutes += max(0, int(str(planned_raw)))
            continue
        except (TypeError, ValueError):
            pass  # planned_minutes is not a plain integer — fall through to duration string parse
        planned_minutes += _parse_duration_minutes(entry.get('planned_duration'))

    night_start = plan_my_night._parse_datetime(plan.get('night_start')) if isinstance(plan, dict) else None
    night_end = plan_my_night._parse_datetime(plan.get('night_end')) if isinstance(plan, dict) else None
    night_minutes = 0
    if night_start and night_end and night_end > night_start:
        night_minutes = int((night_end - night_start).total_seconds() // 60)
    # Subtract start delay - usable observing window is shorter
    start_delay = max(0, int(plan.get('start_delay_minutes') or 0)) if isinstance(plan, dict) else 0
    night_minutes = max(0, night_minutes - start_delay)

    fill_percent = (planned_minutes / night_minutes) * 100.0 if night_minutes > 0 else 0.0
    overflow_minutes = max(0, planned_minutes - night_minutes)

    return {
        'planned_minutes': planned_minutes,
        'night_minutes': night_minutes,
        'fill_percent': fill_percent,
        'overflow_minutes': overflow_minutes,
    }


def _resolve_requested_language() -> str:
    requested_language = request.args.get('lang') or request.headers.get('Accept-Language', 'en')
    requested_language = str(requested_language).split(',')[0].split('-')[0].lower()
    supported_languages = I18nManager.get_supported_languages()
    return requested_language if requested_language in supported_languages else 'en'


@app.route('/api/plan-my-night/list', methods=['GET'])
@login_required
def list_plan_my_night():
    """Return per-telescope plan summaries for the telescope selector UI."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        import equipment_profiles as _ep

        telescopes_data = _ep.load_user_telescopes(user.user_id)
        own = [{**t, 'is_own': True, 'owner_username': None} for t in telescopes_data.get('items', [])]
        shared = [{**t, 'is_own': False} for t in _ep.load_all_shared_equipment('telescopes', user.user_id)]
        all_telescopes = own + shared
        states = plan_my_night.get_all_plan_states(user.user_id, user.username, all_telescopes)
        return jsonify({'status': 'success', 'plans': states, 'telescope_count': len(all_telescopes)})
    except Exception as error:
        logger.error(f'Error listing plans: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night', methods=['GET'])
@login_required
def get_plan_my_night():
    """Get the current user's Plan My Night payload."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_id = request.args.get('telescope_id') or None
        plan_payload = plan_my_night.get_plan_with_timeline(user.user_id, user.username, telescope_id=telescope_id)
        plan_payload = _enrich_plan_entries_with_astrodex_status(plan_payload, user.user_id)
        return jsonify(
            {
                'role': user.role,
                'can_edit': user.is_admin() or user.is_user(),
                **plan_payload,
            }
        )
    except Exception as error:
        logger.error(f'Error loading Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/targets', methods=['POST'])
@user_required
def add_target_to_plan_my_night():
    """Add a target to Plan My Night, creating the plan on first add."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        item_raw = data.get('item')
        item = dict(item_raw) if isinstance(item_raw, dict) else {}
        catalogue = str(data.get('catalogue') or item.get('catalogue') or '').strip()
        if not catalogue:
            return jsonify({'error': 'Catalogue is required'}), 400

        astro_night = _resolve_observing_night_for_plan()
        start_value = astro_night.get('start') if astro_night else None
        end_value = astro_night.get('end') if astro_night else None
        duration_hours = astro_night.get('duration_hours', 0.0) if astro_night else 0.0

        if not start_value or not end_value:
            return jsonify({'error': 'Night window unavailable'}), 409

        telescope_id = data.get('telescope_id') or None
        telescope_name = str(data.get('telescope_name') or '').strip() or None

        success, reason, payload, entry = plan_my_night.create_or_add_target(
            user_id=user.user_id,
            username=user.username,
            item_data=item,
            catalogue=catalogue,
            night_start=start_value,
            night_end=end_value,
            duration_hours=duration_hours,
            telescope_id=telescope_id,
            telescope_name=telescope_name,
        )

        if not success:
            if reason == 'previous_plan_locked':
                return jsonify({'error': 'Plan belongs to previous night'}), 409
            if reason == 'invalid_night_window':
                return jsonify({'error': 'Invalid night window'}), 409
            return jsonify({'error': 'Failed to add target'}), 500

        return jsonify(
            {
                'status': 'success',
                'reason': reason,
                'entry': entry,
                'plan': plan_my_night.get_plan_with_timeline(user.user_id, user.username, telescope_id=telescope_id),
            }
        )
    except Exception as error:
        logger.error(f'Error adding target to Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night', methods=['PATCH'])
@user_required
def patch_plan_my_night():
    """Update plan-level metadata (e.g. start_delay_minutes)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json or {}
        telescope_id = updates.pop('telescope_id', None) or None
        updated = plan_my_night.update_plan_meta(user.user_id, user.username, updates, telescope_id=telescope_id)
        if updated is None:
            return jsonify({'error': 'Plan not found or locked'}), 404

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(user.user_id, user.username, telescope_id=telescope_id),
            }
        )
    except Exception as error:
        logger.error(f'Error patching Plan My Night meta: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/targets/<entry_id>', methods=['PUT'])
@user_required
def update_plan_my_night_target(entry_id):
    """Update target planned duration or done status."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json or {}
        telescope_id = updates.pop('telescope_id', None) or None
        updated = plan_my_night.update_target(user.user_id, user.username, entry_id, updates, telescope_id=telescope_id)
        if not updated:
            return jsonify({'error': 'Target not found or plan locked'}), 404

        return jsonify(
            {
                'status': 'success',
                'entry': updated,
                'plan': plan_my_night.get_plan_with_timeline(user.user_id, user.username, telescope_id=telescope_id),
            }
        )
    except Exception as error:
        logger.error(f'Error updating Plan My Night target {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/targets/<entry_id>/reorder', methods=['POST'])
@user_required
def reorder_plan_my_night_target(entry_id):
    """Reorder plan targets within the current night timeline."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        new_index = data.get('new_index')
        if new_index is None:
            return jsonify({'error': 'new_index is required'}), 400
        telescope_id = data.get('telescope_id') or None

        success = plan_my_night.reorder_target(
            user.user_id, user.username, entry_id, int(new_index), telescope_id=telescope_id
        )
        if not success:
            return jsonify({'error': 'Failed to reorder target'}), 404

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(user.user_id, user.username, telescope_id=telescope_id),
            }
        )
    except Exception as error:
        logger.error(f'Error reordering Plan My Night target {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/targets/<entry_id>', methods=['DELETE'])
@user_required
def delete_plan_my_night_target(entry_id):
    """Delete a target from the active plan."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_id = request.args.get('telescope_id') or None
        success = plan_my_night.remove_target(user.user_id, user.username, entry_id, telescope_id=telescope_id)
        if not success:
            return jsonify({'error': 'Target not found or plan locked'}), 404

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(user.user_id, user.username, telescope_id=telescope_id),
            }
        )
    except Exception as error:
        logger.error(f'Error deleting Plan My Night target {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/clear', methods=['DELETE'])
@user_required
def clear_plan_my_night():
    """Clear current plan so a new night plan can be created."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_id = request.args.get('telescope_id') or None
        if not plan_my_night.clear_plan(user.user_id, user.username, telescope_id=telescope_id):
            return jsonify({'error': 'Failed to clear plan'}), 500

        return jsonify({'status': 'success'})
    except Exception as error:
        logger.error(f'Error clearing Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/clear-all', methods=['DELETE'])
@user_required
def clear_all_plans_my_night():
    """Clear all per-telescope plans for the current user."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        deleted = plan_my_night.clear_all_plans(user.user_id)
        return jsonify({'status': 'success', 'deleted': deleted})
    except Exception as error:
        logger.error(f'Error clearing all plans: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/targets/<entry_id>/add-to-astrodex', methods=['POST'])
@user_required
def add_plan_target_to_astrodex(entry_id):
    """Add an existing plan target to Astrodex if not already present."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        plan_payload = plan_my_night.get_plan_with_timeline(user.user_id, user.username)
        plan = plan_payload.get('plan') or {}
        entry = next((candidate for candidate in plan.get('entries', []) if candidate.get('id') == entry_id), None)
        if not entry:
            # Try searching across all plans if not found in default
            for file_path in plan_my_night.get_all_plan_files(user.user_id):
                tid = None
                fname = os.path.basename(file_path)
                if fname != f'{user.user_id}_plan_my_night.json':
                    tid = fname.replace(f'{user.user_id}_plan_', '').replace('.json', '')
                sub_payload = plan_my_night.load_user_plan(user.user_id, user.username, telescope_id=tid)
                sub_plan = sub_payload.get('plan') or {}
                candidate = next((e for e in sub_plan.get('entries', []) if e.get('id') == entry_id), None)
                if candidate:
                    entry = candidate
                    break
        if not entry:
            return jsonify({'error': 'Target not found'}), 404

        item_name = entry.get('name', '')
        catalogue = entry.get('catalogue', '')
        if astrodex.is_item_in_astrodex(user.user_id, item_name, catalogue):
            return jsonify({'status': 'success', 'reason': 'already_in_astrodex'})

        item_data = {
            'name': item_name,
            'type': entry.get('type', 'Unknown'),
            'catalogue': catalogue,
            'constellation': entry.get('constellation', ''),
            'notes': entry.get('notes', ''),
        }

        created_item = astrodex.create_astrodex_item(user.user_id, item_data, user.username)
        if not created_item:
            return jsonify({'error': 'Failed to create Astrodex item'}), 500

        return jsonify({'status': 'success', 'reason': 'created'})
    except Exception as error:
        logger.error(f'Error adding plan target to Astrodex {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/export.csv', methods=['GET'])
@login_required
def export_plan_my_night_csv():
    """Export the current plan as CSV."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = plan_my_night.get_plan_with_timeline(
            user.user_id, user.username, telescope_id=request.args.get('telescope_id') or None
        )
        language = _resolve_requested_language()
        i18n = I18nManager(language)
        csv_labels = {
            'order': i18n.t('plan_my_night.export_csv_order'),
            'name': i18n.t('plan_my_night.export_csv_name'),
            'catalogue': i18n.t('plan_my_night.export_csv_catalogue'),
            'target_name': i18n.t('plan_my_night.export_csv_target_name'),
            'type': i18n.t('plan_my_night.export_csv_type'),
            'constellation': i18n.t('plan_my_night.export_csv_constellation'),
            'ra': i18n.t('plan_my_night.export_csv_ra'),
            'dec': i18n.t('plan_my_night.export_csv_dec'),
            'mag': i18n.t('plan_my_night.export_csv_mag'),
            'size': i18n.t('plan_my_night.export_csv_size'),
            'observable_pct': i18n.t('plan_my_night.export_csv_observable_pct'),
            'planned_minutes': i18n.t('plan_my_night.export_csv_planned_minutes'),
            'timeline_start': i18n.t('plan_my_night.export_csv_timeline_start'),
            'timeline_end': i18n.t('plan_my_night.export_csv_timeline_end'),
            'done': i18n.t('plan_my_night.export_csv_done'),
            'done_yes': i18n.t('plan_my_night.export_csv_done_yes'),
            'done_no': i18n.t('plan_my_night.export_csv_done_no'),
        }
        csv_content = plan_my_night.serialize_plan_csv(payload, csv_labels)
        buffer = io.BytesIO(csv_content.encode('utf-8'))

        _plan_meta = payload.get('plan') or {}
        _csv_date = (_plan_meta.get('plan_date') or '').replace('-', '') or 'unknown'
        _csv_scope = re.sub(r'[^\w\-]', '_', (_plan_meta.get('telescope_name') or '').strip()) or None
        _csv_name = f'plan-my-night_{_csv_date}_{_csv_scope}.csv' if _csv_scope else f'plan-my-night_{_csv_date}.csv'

        return send_file(buffer, as_attachment=True, mimetype='text/csv', download_name=_csv_name)
    except Exception as error:
        logger.error(f'Error exporting Plan My Night CSV: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/plan-my-night/export.pdf', methods=['GET'])
@login_required
def export_plan_my_night_pdf():
    """Export the current plan as a polished, print-friendly PDF."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        language = _resolve_requested_language()
        i18n = I18nManager(language)
        payload = plan_my_night.get_plan_with_timeline(
            user.user_id,
            user.username,
            telescope_id=request.args.get('telescope_id') or None,
        )
        metrics = _compute_plan_fill_metrics(payload.get('plan') or {})
        buffer = plan_my_night.generate_plan_pdf(payload, metrics, i18n)

        plan = payload.get('plan')
        _pdf_date = (plan.get('plan_date') or '').replace('-', '') if plan else 'unknown'
        _pdf_scope = re.sub(r'[^\w\-]', '_', (plan.get('telescope_name') or '').strip()) if plan else None
        _pdf_name = f'plan-my-night_{_pdf_date}_{_pdf_scope}.pdf' if _pdf_scope else f'plan-my-night_{_pdf_date}.pdf'

        return send_file(buffer, as_attachment=True, mimetype='application/pdf', download_name=_pdf_name)
    except Exception as error:
        logger.error(f'Error exporting Plan My Night PDF: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex', methods=['GET'])
@login_required
def get_astrodex():
    """Get user's astrodex collection"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        config = load_config()
        private_mode = bool(config.get('astrodex', {}).get('private', False))
        users = user_manager.list_users()
        usernames_by_id = {
            user_entry.get('user_id', ''): user_entry.get('username', 'unknown')
            for user_entry in users
            if user_entry.get('user_id')
        }

        astrodex_data = astrodex.get_visible_astrodex(
            current_user_id=user_id,
            current_username=user.username,
            private_mode=private_mode,
            usernames_by_id=usernames_by_id,
        )

        return jsonify(
            {
                'items': astrodex_data.get('items', []),
                'stats': astrodex_data.get('stats', {}),
                'created_at': astrodex_data.get('created_at'),
                'updated_at': astrodex_data.get('updated_at'),
                'private_mode': astrodex_data.get('private_mode', private_mode),
                'current_user_id': user_id,
            }
        )
    except Exception as e:
        logger.error(f"Error getting astrodex: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items', methods=['POST'])
@user_required
def add_astrodex_item():
    """Add item to user's astrodex"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id or not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        item_data = request.json

        if not item_data.get('name'):
            return jsonify({'error': 'Item name is required'}), 400

        # Check if item already exists (exact name or catalogue aliases)
        if astrodex.is_item_in_astrodex(user_id, item_data['name'], item_data.get('catalogue', '')):
            return jsonify({'error': 'Item already exists in Astrodex'}), 400

        new_item = astrodex.create_astrodex_item(user_id, item_data, user.username)

        if new_item:
            return jsonify({'status': 'success', 'item': new_item})
        else:
            return jsonify({'error': 'Failed to create item'}), 500
    except Exception as e:
        logger.error(f"Error adding astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>/catalogue-name', methods=['POST'])
@user_required
def switch_astrodex_item_catalogue_name(item_id):
    """Switch Astrodex item displayed name to a catalogue-specific alias."""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        target_catalogue = data.get('catalogue', '')

        if not target_catalogue:
            return jsonify({'error': 'Target catalogue is required'}), 400

        updated_item = astrodex.switch_item_catalogue_name(user_id, item_id, target_catalogue)
        if updated_item:
            return jsonify({'status': 'success', 'item': updated_item})

        return jsonify({'error': 'Item not found'}), 404
    except ValueError as e:
        logger.warning(f"Value error switching astrodex item catalogue name: {e}")
        return jsonify({'error': 'Invalid input'}), 400
    except Exception as e:
        logger.error(f"Error switching astrodex item catalogue name: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>', methods=['GET'])
@login_required
def get_astrodex_item_api(item_id):
    """Get a specific astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        item = astrodex.get_astrodex_item(user_id, item_id)

        if item:
            return jsonify(item)
        else:
            return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error getting astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>', methods=['PUT'])
@user_required
def update_astrodex_item_api(item_id):
    """Update an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json

        updated_item = astrodex.update_astrodex_item(user_id, item_id, updates)

        if updated_item:
            return jsonify({'status': 'success', 'item': updated_item})
        else:
            return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error updating astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>', methods=['DELETE'])
@user_required
def delete_astrodex_item_api(item_id):
    """Delete an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if astrodex.delete_astrodex_item(user_id, item_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting astrodex item: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>/pictures', methods=['POST'])
@user_required
def add_picture_to_astrodex_item(item_id):
    """Add a picture to an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        picture_data = request.json

        new_picture = astrodex.add_picture_to_item(user_id, item_id, picture_data)

        if new_picture:
            return jsonify({'status': 'success', 'picture': new_picture})
        else:
            return jsonify({'error': 'Item not found or failed to add picture'}), 404
    except Exception as e:
        logger.error(f"Error adding picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>/pictures/<picture_id>', methods=['PUT'])
@user_required
def update_picture_api(item_id, picture_id):
    """Update a picture in an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json

        updated_picture = astrodex.update_picture(user_id, item_id, picture_id, updates)

        if updated_picture:
            return jsonify({'status': 'success', 'picture': updated_picture})
        else:
            return jsonify({'error': 'Picture not found'}), 404
    except Exception as e:
        logger.error(f"Error updating picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>/pictures/<picture_id>', methods=['DELETE'])
@user_required
def delete_picture_api(item_id, picture_id):
    """Delete a picture from an astrodex item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if astrodex.delete_picture(user_id, item_id, picture_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Picture not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/items/<item_id>/pictures/<picture_id>/main', methods=['POST'])
@user_required
def set_main_picture_api(item_id, picture_id):
    """Set a picture as the main picture for an item"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        if astrodex.set_main_picture(user_id, item_id, picture_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Picture not found'}), 404
    except Exception as e:
        logger.error(f"Error setting main picture: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/upload', methods=['POST'])
@user_required
def upload_astrodex_image():
    """Upload an image for astrodex safely"""
    try:
        if 'file' not in request.files:
            logger.warning("No file part in the request")
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file or not file.filename:
            logger.warning("No file selected for upload")
            return jsonify({'error': 'No file selected'}), 400

        # Strict extension validation
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

        original_filename = secure_filename(file.filename)
        if '.' not in original_filename:
            logger.warning(f"File name does not have an extension: {original_filename}")
            return jsonify({'error': 'Invalid file name'}), 400

        file_ext = original_filename.rsplit('.', 1)[1].lower()
        if file_ext not in allowed_extensions:
            logger.warning(f"Invalid file type: {file_ext}")
            return jsonify({'error': 'Invalid file type'}), 400

        # Validate user
        try:
            user = get_current_user()
            user_id = user.user_id if user else None
            if not user_id:  # pragma: no cover
                logger.warning("User not authenticated for file upload")
                return jsonify({'error': 'User not authenticated'}), 401

        except (TypeError, ValueError):  # pragma: no cover
            logger.warning("Invalid user ID")
            return jsonify({'error': 'Invalid user ID'}), 400

        # Generate safe unique filename
        unique_filename = f"{user_id}_{uuid.uuid4()}.{file_ext}"

        # Ensure directory exists
        astrodex.ensure_astrodex_directories()

        base_dir = os.path.abspath(astrodex.ASTRODEX_IMAGES_DIR)
        file_path = os.path.normpath(os.path.join(base_dir, unique_filename))

        # Confinement check (anti path traversal)
        if not file_path.startswith(base_dir):  # pragma: no cover
            logger.warning(f"Attempted path traversal attack: {file_path}")
            return jsonify({'error': 'Invalid file path'}), 400

        # Save file
        file.save(file_path)

        return jsonify({'status': 'success', 'filename': unique_filename})

    except Exception:
        logger.exception("Error uploading astrodex image")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/images/<filename>', methods=['GET'])
@login_required
def get_astrodex_image(filename):
    """Serve an astrodex image"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        config = load_config()
        private_mode = bool(config.get('astrodex', {}).get('private', False))
        users = user_manager.list_users()
        usernames_by_id = {
            user_entry.get('user_id', ''): user_entry.get('username', 'unknown')
            for user_entry in users
            if user_entry.get('user_id')
        }

        if not astrodex.can_user_view_image(user_id, filename, private_mode, usernames_by_id):
            return jsonify({'error': 'Image not accessible'}), 403

        return send_from_directory(astrodex.ASTRODEX_IMAGES_DIR, filename)
    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return jsonify({'error': 'Image not found'}), 404


@app.route('/api/astrodex/check/<item_name>', methods=['GET'])
@login_required
def check_item_in_astrodex(item_name):
    """Check if an item is in user's astrodex"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401
        is_in_astrodex = astrodex.is_item_in_astrodex(user_id, item_name)

        return jsonify({'in_astrodex': is_in_astrodex})
    except Exception as e:
        logger.error(f"Error checking astrodex: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/constellations', methods=['GET'])
@login_required
def get_constellations():
    """Get list of constellation names"""
    try:
        constellations = astrodex.get_constellations_list()
        return jsonify({'constellations': constellations})
    except Exception as e:
        logger.error(f"Error getting constellations: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/astrodex/catalogue-lookup', methods=['GET'])
@login_required
def astrodex_catalogue_lookup():
    """Look up a celestial object by name in the SkyTonight catalogue dataset.

    Returns basic object metadata (type, constellation, catalogue names) so the
    Astrodex manual-add form can be pre-filled when the entered name is known.
    """
    try:
        from constellation import Constellation
        import re as _re

        # Build a one-time abbr→full-name mapping (e.g. 'Cnc' -> 'Cancer',
        # 'UMa' -> 'Ursa Major').  c.name is the Python enum member name
        # (e.g. 'UrsaMajor') so we apply the same humanize() logic used in
        # astrodex.get_constellations_list() to insert spaces before capitals.
        def _humanize(name: str) -> str:
            return _re.sub(r'(?<!^)(?=[A-Z])', ' ', name)

        _abbr_to_name = {c.abbr: _humanize(c.name) for c in Constellation}

        name = request.args.get('name', '').strip()
        if not name:
            return jsonify({'found': False})

        # get_lookup_entry requires a non-empty catalogue; searching via the
        # 'alias' key covers all catalogue names and common aliases since the
        # lookup table registers every target under alias::<normalised_name>.
        entry = skytonight_targets.get_lookup_entry('alias', name)
        if entry:
            raw_constellation = entry.get('constellation') or ''
            full_constellation = (_abbr_to_name.get(raw_constellation, raw_constellation) or '').lower()
            return jsonify(
                {
                    'found': True,
                    'preferred_name': entry.get('preferred_name', ''),
                    'object_type': entry.get('object_type', ''),
                    'constellation': full_constellation,
                    'catalogue_names': entry.get('aliases', {}),
                }
            )

        # Fallback: query SIMBAD TAP to support extended catalogs (HIP, HD, SAO, TYC…)
        from object_info import (
            resolve_identifier_for_catalogue_lookup,
            build_catalogue_names_from_aliases,
            is_safe_identifier,
        )

        if is_safe_identifier(name):
            simbad = resolve_identifier_for_catalogue_lookup(name)
            if simbad:
                catalogue_names = build_catalogue_names_from_aliases(name, simbad['aliases'])
                # preferred_name: the typed identifier if it maps to a known catalog,
                # otherwise the best sorted alias, otherwise the typed identifier as-is.
                if any(v == name for v in catalogue_names.values()):
                    preferred_name = name
                else:
                    preferred_name = simbad['aliases'][0] if simbad['aliases'] else name
                return jsonify(
                    {
                        'found': True,
                        'preferred_name': preferred_name,
                        'object_type': simbad['object_type'],
                        'constellation': simbad['constellation'],
                        'catalogue_names': catalogue_names,
                    }
                )

        return jsonify({'found': False})
    except Exception as e:
        logger.error(f"Error in catalogue lookup: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# Equipment Profiles API
# ============================================================


# Telescopes
@app.route('/api/equipment/telescopes', methods=['GET'])
@user_required
def get_telescopes():
    """Get user's telescope profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_telescopes(user_id)
        shared = equipment_profiles.load_all_shared_equipment('telescopes', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting telescopes: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/telescopes', methods=['POST'])
@user_required
def create_telescope():
    """Create a new telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_data = request.json
        new_telescope = equipment_profiles.create_telescope(user_id, telescope_data)

        if new_telescope:
            return jsonify({'status': 'success', 'data': new_telescope}), 201
        else:
            return jsonify({'error': 'Failed to create telescope'}), 500
    except Exception as e:
        logger.error(f"Error creating telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/telescopes/<telescope_id>', methods=['GET'])
@user_required
def get_telescope(telescope_id):
    """Get a specific telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope = equipment_profiles.get_telescope(user_id, telescope_id)

        if telescope:
            return jsonify(telescope)
        else:
            return jsonify({'error': 'Telescope not found'}), 404
    except Exception as e:
        logger.error(f"Error getting telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/telescopes/<telescope_id>', methods=['PUT'])
@user_required
def update_telescope(telescope_id):
    """Update a telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        telescope_data = request.json
        shared = equipment_profiles.load_all_shared_equipment('telescopes', user_id)
        if any(t['id'] == telescope_id for t in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_telescope = equipment_profiles.update_telescope(user_id, telescope_id, telescope_data)

        if updated_telescope:
            return jsonify({'status': 'success', 'data': updated_telescope})
        else:
            return jsonify({'error': 'Telescope not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/telescopes/<telescope_id>', methods=['DELETE'])
@user_required
def delete_telescope(telescope_id):
    """Delete a telescope profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success = equipment_profiles.delete_telescope(user_id, telescope_id)

        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to delete telescope'}), 500
    except Exception as e:
        logger.error(f"Error deleting telescope: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Cameras
@app.route('/api/equipment/cameras', methods=['GET'])
@user_required
def get_cameras():
    """Get user's camera profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_cameras(user_id)
        shared = equipment_profiles.load_all_shared_equipment('cameras', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting cameras: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/cameras', methods=['POST'])
@user_required
def create_camera():
    """Create a new camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        camera_data = request.json
        new_camera = equipment_profiles.create_camera(user_id, camera_data)

        if new_camera:
            return jsonify({'status': 'success', 'data': new_camera}), 201
        else:
            return jsonify({'error': 'Failed to create camera'}), 500
    except Exception as e:
        logger.error(f"Error creating camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/cameras/<camera_id>', methods=['GET'])
@user_required
def get_camera(camera_id):
    """Get a specific camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        camera = equipment_profiles.get_camera(user_id, camera_id)

        if camera:
            return jsonify(camera)
        else:
            return jsonify({'error': 'Camera not found'}), 404
    except Exception as e:
        logger.error(f"Error getting camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/cameras/<camera_id>', methods=['PUT'])
@user_required
def update_camera(camera_id):
    """Update a camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        camera_data = request.json
        shared = equipment_profiles.load_all_shared_equipment('cameras', user_id)
        if any(c['id'] == camera_id for c in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_camera = equipment_profiles.update_camera(user_id, camera_id, camera_data)

        if updated_camera:
            return jsonify({'status': 'success', 'data': updated_camera})
        else:
            return jsonify({'error': 'Camera not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/cameras/<camera_id>', methods=['DELETE'])
@user_required
def delete_camera(camera_id):
    """Delete a camera profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success = equipment_profiles.delete_camera(user_id, camera_id)

        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to delete camera'}), 500
    except Exception as e:
        logger.error(f"Error deleting camera: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Mounts
@app.route('/api/equipment/mounts', methods=['GET'])
@user_required
def get_mounts():
    """Get user's mount profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_mounts(user_id)
        shared = equipment_profiles.load_all_shared_equipment('mounts', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting mounts: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/mounts', methods=['POST'])
@user_required
def create_mount():
    """Create a new mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        mount_data = request.json
        new_mount = equipment_profiles.create_mount(user_id, mount_data)

        if new_mount:
            return jsonify({'status': 'success', 'data': new_mount}), 201
        else:
            return jsonify({'error': 'Failed to create mount'}), 500
    except Exception as e:
        logger.error(f"Error creating mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/mounts/<mount_id>', methods=['GET'])
@user_required
def get_mount(mount_id):
    """Get a specific mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        mount = equipment_profiles.get_mount(user_id, mount_id)

        if mount:
            return jsonify(mount)
        else:
            return jsonify({'error': 'Mount not found'}), 404
    except Exception as e:
        logger.error(f"Error getting mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/mounts/<mount_id>', methods=['PUT'])
@user_required
def update_mount(mount_id):
    """Update a mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        mount_data = request.json
        shared = equipment_profiles.load_all_shared_equipment('mounts', user_id)
        if any(m['id'] == mount_id for m in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_mount = equipment_profiles.update_mount(user_id, mount_id, mount_data)

        if updated_mount:
            return jsonify({'status': 'success', 'data': updated_mount})
        else:
            return jsonify({'error': 'Mount not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/mounts/<mount_id>', methods=['DELETE'])
@user_required
def delete_mount(mount_id):
    """Delete a mount profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success = equipment_profiles.delete_mount(user_id, mount_id)

        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to delete mount'}), 500
    except Exception as e:
        logger.error(f"Error deleting mount: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Filters
@app.route('/api/equipment/filters', methods=['GET'])
@user_required
def get_filters():
    """Get user's filter profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_filters(user_id)
        shared = equipment_profiles.load_all_shared_equipment('filters', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting filters: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/filters', methods=['POST'])
@user_required
def create_filter():
    """Create a new filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        filter_data = request.json
        new_filter = equipment_profiles.create_filter(user_id, filter_data)

        if new_filter:
            return jsonify({'status': 'success', 'data': new_filter}), 201
        else:
            return jsonify({'error': 'Failed to create filter'}), 500
    except Exception as e:
        logger.error(f"Error creating filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/filters/<filter_id>', methods=['GET'])
@user_required
def get_filter(filter_id):
    """Get a specific filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        filter_obj = equipment_profiles.get_filter(user_id, filter_id)

        if filter_obj:
            return jsonify(filter_obj)
        else:
            return jsonify({'error': 'Filter not found'}), 404
    except Exception as e:
        logger.error(f"Error getting filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/filters/<filter_id>', methods=['PUT'])
@user_required
def update_filter(filter_id):
    """Update a filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        filter_data = request.json
        shared = equipment_profiles.load_all_shared_equipment('filters', user_id)
        if any(f['id'] == filter_id for f in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_filter = equipment_profiles.update_filter(user_id, filter_id, filter_data)

        if updated_filter:
            return jsonify({'status': 'success', 'data': updated_filter})
        else:
            return jsonify({'error': 'Filter not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/filters/<filter_id>', methods=['DELETE'])
@user_required
def delete_filter(filter_id):
    """Delete a filter profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success = equipment_profiles.delete_filter(user_id, filter_id)

        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to delete filter'}), 500
    except Exception as e:
        logger.error(f"Error deleting filter: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Accessories
@app.route('/api/equipment/accessories', methods=['GET'])
@user_required
def get_accessories():
    """Get user's accessory profiles"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_accessories(user_id)
        shared = equipment_profiles.load_all_shared_equipment('accessories', user_id)
        return jsonify(
            {
                'data': data.get('items', []),
                'shared_from_others': shared,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting accessories: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/accessories', methods=['POST'])
@user_required
def create_accessory():
    """Create a new accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessory_data = request.json
        new_accessory = equipment_profiles.create_accessory(user_id, accessory_data)

        if new_accessory:
            return jsonify({'status': 'success', 'data': new_accessory}), 201
        else:
            return jsonify({'error': 'Failed to create accessory'}), 500
    except Exception as e:
        logger.error(f"Error creating accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/accessories/<accessory_id>', methods=['GET'])
@user_required
def get_accessory(accessory_id):
    """Get a specific accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessory = equipment_profiles.get_accessory(user_id, accessory_id)

        if accessory:
            return jsonify(accessory)
        else:
            return jsonify({'error': 'Accessory not found'}), 404
    except Exception as e:
        logger.error(f"Error getting accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/accessories/<accessory_id>', methods=['PUT'])
@user_required
def update_accessory(accessory_id):
    """Update an accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        accessory_data = request.json
        shared = equipment_profiles.load_all_shared_equipment('accessories', user_id)
        if any(a['id'] == accessory_id for a in shared):
            return jsonify({'error': 'Cannot modify shared equipment owned by another user'}), 403
        updated_accessory = equipment_profiles.update_accessory(user_id, accessory_id, accessory_data)

        if updated_accessory:
            return jsonify({'status': 'success', 'data': updated_accessory})
        else:
            return jsonify({'error': 'Failed to update accessory'}), 500
    except Exception as e:
        logger.error(f"Error updating accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/accessories/<accessory_id>', methods=['DELETE'])
@user_required
def delete_accessory(accessory_id):
    """Delete an accessory profile"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success = equipment_profiles.delete_accessory(user_id, accessory_id)

        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to delete accessory'}), 500
    except Exception as e:
        logger.error(f"Error deleting accessory: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Equipment Combinations
@app.route('/api/equipment/combinations', methods=['GET'])
@user_required
def get_combinations():
    """Get user's equipment combinations"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = equipment_profiles.load_user_combinations(user_id)
        items_with_status = []
        for combo in data.get('items', []):
            status = equipment_profiles.compute_combination_share_status(combo, user_id)
            items_with_status.append({**combo, **status})
        shared_with_status = equipment_profiles.load_all_shared_combinations(user_id)
        return jsonify(
            {
                'data': items_with_status,
                'shared_from_others': shared_with_status,
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        )
    except Exception as e:
        logger.error(f"Error getting combinations: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/combinations', methods=['POST'])
@user_required
def create_combination():
    """Create a new equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_data = request.json
        new_combination = equipment_profiles.create_combination(user_id, combination_data)

        if new_combination:
            return jsonify({'status': 'success', 'data': new_combination}), 201
        else:
            return (
                jsonify({'error': 'Failed to create combination. At minimum a telescope or camera must be selected.'}),
                400,
            )
    except Exception as e:
        logger.error(f"Error creating combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/combinations/<combination_id>', methods=['GET'])
@user_required
def get_combination(combination_id):
    """Get a specific equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination = equipment_profiles.get_combination(user_id, combination_id)

        if combination:
            status = equipment_profiles.compute_combination_share_status(combination, user_id)
            return jsonify({**combination, **status})
        else:
            return jsonify({'error': 'Combination not found'}), 404
    except Exception as e:
        logger.error(f"Error getting combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/combinations/<combination_id>', methods=['PUT'])
@user_required
def update_combination(combination_id):
    """Update an equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_data = request.json
        updated_combination = equipment_profiles.update_combination(user_id, combination_id, combination_data)

        if updated_combination:
            return jsonify({'status': 'success', 'data': updated_combination})
        else:
            return jsonify({'error': 'Combination not found or update failed'}), 404
    except Exception as e:
        logger.error(f"Error updating combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/equipment/combinations/<combination_id>', methods=['DELETE'])
@user_required
def delete_combination(combination_id):
    """Delete an equipment combination"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        success = equipment_profiles.delete_combination(user_id, combination_id)

        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to delete combination'}), 500
    except Exception as e:
        logger.error(f"Error deleting combination: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# FOV Calculator (standalone endpoint)
@app.route('/api/equipment/fov-calculator', methods=['POST'])
@user_required
def calculate_fov():
    """Calculate Field of View for given parameters"""
    try:
        data = request.json

        fov_calculation = equipment_profiles.calculate_fov(
            telescope_focal_length_mm=float(data['telescope_focal_length_mm']),
            camera_sensor_width_mm=float(data['camera_sensor_width_mm']),
            camera_sensor_height_mm=float(data['camera_sensor_height_mm']),
            camera_pixel_size_um=float(data['camera_pixel_size_um']),
            seeing_arcsec=float(data.get('seeing_arcsec', 2.0)),
        )

        return jsonify(asdict(fov_calculation))
    except Exception as e:
        logger.error(f"Error calculating FOV: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Equipment Summary
@app.route('/api/equipment/summary', methods=['GET'])
@user_required
def get_equipment_summary():
    """Get summary of all user equipment"""
    try:
        user = get_current_user()
        user_id = user.user_id if user else None
        if not user_id:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        summary = equipment_profiles.get_all_equipment_summary(user_id)
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Error getting equipment summary: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# Scheduler Management
# ============================================================


def get_or_create_cache_scheduler():
    """Get the cache scheduler instance, creating it if necessary"""
    if 'cache_scheduler' not in app.config:
        logger.debug("Creating cache scheduler instance...")
        try:
            from cache_scheduler import CacheScheduler

            cache_scheduler = CacheScheduler()
            # Store the instance regardless of whether it started
            # (it may already be running in another process)
            app.config['cache_scheduler'] = cache_scheduler
            if cache_scheduler.start():
                logger.debug("Cache scheduler created and started successfully.")
            else:
                logger.debug("Cache scheduler not started - already running in another process.")
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to create cache scheduler: {e}")
            return None
    return app.config.get('cache_scheduler')


# ============================================================
# Application Startup Initialization
# ============================================================

# Initialize cache scheduler FIRST so its cache_ready_event can be passed to
# the SkyTonight scheduler, ensuring DSO calculations run on warm caches.
try:
    logger.info("Initializing cache scheduler on application startup...")
    get_or_create_cache_scheduler()
except Exception as e:  # pragma: no cover
    logger.error(f"Failed to initialize cache scheduler on startup: {e}", exc_info=True)

try:
    logger.info('Initializing SkyTonight scheduler on application startup...')
    _cache_sched = app.config.get('cache_scheduler')
    get_or_create_skytonight_scheduler(
        app, cache_ready_event=_cache_sched.cache_ready_event if _cache_sched is not None else None
    )
except Exception as e:  # pragma: no cover
    logger.error(f'Failed to initialize SkyTonight scheduler on startup: {e}', exc_info=True)

try:
    logger.info('Initializing push notification scheduler on application startup...')
    import push_scheduler as _push_scheduler

    _push_scheduler.start()
    # Generate VAPID keys early so the first /api/push/vapid-public-key request is instant
    from push_manager import load_or_generate_vapid_keys as _init_vapid

    _init_vapid()
except Exception as e:  # pragma: no cover
    logger.error(f'Failed to initialize push scheduler on startup: {e}', exc_info=True)


# Ensure schedulers are stopped when the worker exits
# (covers gunicorn workers that never reach the __main__ finally block)
def _stop_schedulers_on_exit():  # pragma: no cover
    skytonight_scheduler = app.config.get('skytonight_scheduler')
    if skytonight_scheduler:
        try:
            skytonight_scheduler.stop()
        except Exception as e:  # pragma: no cover
            logger.warning(f'Error stopping SkyTonight scheduler on exit: {e}')
    cache_scheduler = app.config.get('cache_scheduler')
    if cache_scheduler:
        try:
            cache_scheduler.stop()
        except Exception as e:  # pragma: no cover
            logger.warning(f"Error stopping cache scheduler on exit: {e}")
    try:
        import push_scheduler as _ps

        _ps.stop()
    except Exception as e:  # pragma: no cover
        logger.warning(f"Error stopping push scheduler on exit: {e}")


atexit.register(_stop_schedulers_on_exit)

# Handle SIGTERM explicitly so cleanup runs even when gunicorn forces a fast
# worker shutdown (atexit is not guaranteed to fire on SIGTERM in all workers).
try:
    import signal as _signal

    def _sigterm_handler(signum, frame):  # pragma: no cover
        _stop_schedulers_on_exit()
        # Restore default handler and re-raise so gunicorn can complete its shutdown.
        _signal.signal(_signal.SIGTERM, _signal.SIG_DFL)
        os.kill(os.getpid(), _signal.SIGTERM)

    _signal.signal(_signal.SIGTERM, _sigterm_handler)
except Exception:  # pragma: no cover
    pass  # Signal registration is best-effort (e.g. not the main thread)

# (moved cache scheduler startup above; this block is intentionally empty)

# ============================================================

if __name__ == '__main__':  # pragma: no cover
    # Running directly with Flask development server
    in_debug_mode = os.environ.get('FLASK_DEBUG') == '1'

    try:
        # Run Flask app
        app.run(host='0.0.0.0', port=5000, debug=in_debug_mode, use_reloader=in_debug_mode)
    finally:
        # Ensure scheduler stops gracefully on shutdown
        skytonight_scheduler = app.config.get('skytonight_scheduler')
        if skytonight_scheduler:
            skytonight_scheduler.stop()
            logger.info('SkyTonight scheduler stopped.')

            skytonight_lock_file = app.config.get('skytonight_scheduler_lock_file')
            if skytonight_lock_file:
                try:
                    skytonight_lock_file.close()
                    os.unlink(get_skytonight_scheduler_lock_file())
                    logger.info('SkyTonight scheduler lock file cleaned up.')
                except Exception as e:
                    logger.warning(f'Failed to clean up SkyTonight lock file: {e}')

        scheduler = app.config.get('scheduler')
        if scheduler:
            scheduler.stop()
            logger.info("Scheduler stopped.")

            # Clean up lock file if we have it
            lock_file = app.config.get('scheduler_lock_file')
            if lock_file:
                try:
                    lock_file.close()
                    os.unlink(os.path.join(DATA_DIR_CACHE, 'scheduler.lock'))
                    logger.info("Scheduler lock file cleaned up.")
                except Exception as e:
                    logger.warning(f"Failed to clean up lock file: {e}")

        cache_scheduler = app.config.get('cache_scheduler')
        if cache_scheduler:
            cache_scheduler.stop()
            logger.info("Cache scheduler stopped.")
