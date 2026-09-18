"""
MyAstroBoard - Flask Backend API
Provides astronomy planning and configuration management
"""

import atexit
from flask import (
    Flask,
    request,
    render_template,
    send_from_directory,
    session,
    redirect,
    url_for,
    g,
    Response,
)
from flask_compress import Compress
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import sys
from datetime import timedelta

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
    from utils.constants import IERS_CACHE_FILE as _IERS_CACHE_FILE
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

from utils.txtconf_loader import get_repo_version
from utils.constants import DATA_DIR_CACHE
from utils.logging_config import get_logger
from skytonight.skytonight_storage import get_scheduler_lock_file as get_skytonight_scheduler_lock_file

# Authentication
# user_manager is unused directly by this module but kept as a test-patching seam,
# same reason as the re-exports below (monkeypatch.setattr(app.user_manager, ...)).
from utils.auth import get_current_user, user_manager  # noqa: F401

# Domain modules re-exported here (not used directly by this module) because the test
# suite patches them via monkeypatch.setattr(app.<module>, ...) - a stable seam even
# though the actual route logic that calls them now lives in backend/blueprints/*.py.
from observation import astrodex  # noqa: F401
from cache import cache_store  # noqa: F401
from space import css_passes  # noqa: F401
from equipment import equipment_profiles  # noqa: F401
from space import iss_passes  # noqa: F401
from astroweather import moon_planner  # noqa: F401
from observation import plan_my_night

# Declares the re-exports above as intentional (not dead code) for static analysis -
# their only consumers are tests doing monkeypatch.setattr(app.<name>, ...).
__all__ = [
    "app",
    "user_manager",
    "astrodex",
    "cache_store",
    "css_passes",
    "equipment_profiles",
    "iss_passes",
    "moon_planner",
    "plan_my_night",
]

# Initialize logger for this module
logger = get_logger(__name__)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
TEMPLATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# Load persistent app settings (replaces SECRET_KEY / TRUST_PROXY_HEADERS /
# SESSION_COOKIE_SECURE / VAPID_CONTACT_EMAIL environment variables).
from utils import app_settings as _app_settings

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

# SkyTonight scheduler management (routes now live in blueprints.skytonight_api)
from skytonight.skytonight_scheduler_manager import get_or_create_skytonight_scheduler

# Domain Blueprints (see backend/blueprints/)
from blueprints.skytonight_api import skytonight_bp
from blueprints.auth import auth_bp
from blueprints.push import push_bp
from blueprints.locations import locations_bp
from blueprints.connectors import connectors_bp
from blueprints.connectors_allsky import connectors_allsky_bp
from blueprints.connectors_myastroshine import connectors_myastroshine_bp
from blueprints.connectors_mqtt import connectors_mqtt_bp
from blueprints.admin import admin_bp
from blueprints.misc import misc_bp
from blueprints.weather import weather_bp
from blueprints.tracking import tracking_bp
from blueprints.astronomy import astronomy_bp
from blueprints.plan_my_night import plan_my_night_bp
from blueprints.astrodex import astrodex_bp
from blueprints.equipment import equipment_bp
from blueprints.observation_sessions import observation_sessions_bp
from blueprints.session_analytics import session_analytics_bp

app.register_blueprint(skytonight_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(push_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(connectors_bp)
app.register_blueprint(connectors_allsky_bp)
app.register_blueprint(connectors_myastroshine_bp)
app.register_blueprint(connectors_mqtt_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(misc_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(tracking_bp)
app.register_blueprint(astronomy_bp)
app.register_blueprint(plan_my_night_bp)
app.register_blueprint(astrodex_bp)
app.register_blueprint(equipment_bp)
app.register_blueprint(observation_sessions_bp)
app.register_blueprint(session_analytics_bp)


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
            if request.endpoint not in ['auth.login', 'auth.auth_status']:
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

    seo_indexable = bool(_app_settings.get_app_settings().get('search_engine_indexing', False))

    return render_template('login.html', version=version, seo_indexable=seo_indexable)


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


_ROBOTS_TXT_INDEXABLE = (
    "User-agent: *\n"
    "Allow: /login\n"
    "Allow: /static/\n"
    "Disallow: /api/\n"
    "Disallow: /data/\n"
    "Disallow: /offline.html\n"
    "Disallow: /sw.js\n"
    "Disallow: /manifest.webmanifest\n"
    "Disallow: /manifest.fr.webmanifest\n"
    "Disallow: /manifest.es.webmanifest\n"
    "Disallow: /manifest.de.webmanifest\n"
    "Disallow: /manifest.it.webmanifest\n"
    "Disallow: /manifest.pt.webmanifest\n"
)
_ROBOTS_TXT_PRIVATE = "User-agent: *\nDisallow: /\n"


@app.route('/robots.txt')
def robots_txt():
    """Serve robots.txt - only allows crawling /login when an admin has
    opted in via Parameters -> Advanced -> Privacy (search_engine_indexing).
    Private (Disallow: /) by default so self-hosted instances are not
    crawlable out of the box."""
    indexable = bool(_app_settings.get_app_settings().get('search_engine_indexing', False))
    content = _ROBOTS_TXT_INDEXABLE if indexable else _ROBOTS_TXT_PRIVATE
    response = Response(content, mimetype='text/plain')
    response.headers['Cache-Control'] = 'public, max-age=3600, must-revalidate'
    return response


# ============================================================
# Scheduler Management
# ============================================================


def get_or_create_cache_scheduler():
    """Get the cache scheduler instance, creating it if necessary"""
    if 'cache_scheduler' not in app.config:
        logger.debug("Creating cache scheduler instance...")
        try:
            from cache.cache_scheduler import CacheScheduler

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

try:
    _purged_plan_count = plan_my_night.purge_legacy_telescope_plans()
    if _purged_plan_count:
        logger.info(  # pragma: no cover - depends on real legacy files existing before this module's first import
            f'Purged {_purged_plan_count} legacy telescope-keyed plan file(s) on startup'
        )
except Exception as e:  # pragma: no cover
    logger.error(f'Failed to purge legacy plan files on startup: {e}', exc_info=True)

# The three schedulers below spawn real, persistent background threads that keep
# running - and keep overwriting shared in-memory caches - for the life of the
# process. Test modules import this file at pytest collection time (before any
# fixture can intervene), so left unguarded these threads race live against
# whatever a test just monkeypatched, causing order-dependent failures far from
# the scheduler code itself. Tests that exercise these functions directly (e.g.
# TestCacheSchedulerManagement) call get_or_create_cache_scheduler() /
# get_or_create_skytonight_scheduler() / push_scheduler.start() themselves and
# are unaffected by skipping the auto-start below.
_AUTOSTART_SCHEDULERS = 'pytest' not in sys.modules

if _AUTOSTART_SCHEDULERS:  # pragma: no cover - never true while imported under pytest
    # Connector credentials moved out of config.json (v1.6): move any that a previous
    # version stored there into the sidecar before the next backup can ship them.
    # A one-shot config rewrite; guarded like the schedulers so the test suite's shared
    # config file is never rewritten at import time.
    try:
        from utils.connector_secrets import migrate_all_legacy_secrets as _migrate_secrets
        from utils.repo_config import load_config as _load_config_for_secrets, save_config as _save_config_for_secrets

        _startup_config = _load_config_for_secrets()
        if _migrate_secrets(_startup_config):
            _save_config_for_secrets(_startup_config)
            logger.info('Connector credentials migrated from config.json to the secrets sidecar')
    except Exception as e:
        logger.error(f'Failed to migrate connector credentials on startup: {e}', exc_info=True)

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
        from utils import push_scheduler as _push_scheduler

        _push_scheduler.start()
    except Exception as e:  # pragma: no cover
        logger.error(f'Failed to initialize push scheduler on startup: {e}', exc_info=True)

    try:
        # Idle until the MQTT connector is enabled in Parameters -> Connectors; then it keeps
        # the broker connection and publishes on its own interval (see connectors/mqtt_publisher.py).
        logger.info('Initializing MQTT publisher on application startup...')
        from connectors import mqtt_publisher as _mqtt_publisher

        _mqtt_publisher.start()
    except Exception as e:  # pragma: no cover
        logger.error(f'Failed to initialize MQTT publisher on startup: {e}', exc_info=True)

try:
    # Generate VAPID keys early so the first /api/push/vapid-public-key request is instant.
    # A one-shot file write, not a recurring thread, so this stays unconditional.
    from utils.push_manager import load_or_generate_vapid_keys as _init_vapid

    _init_vapid()
except Exception as e:  # pragma: no cover
    logger.error(f'Failed to generate VAPID keys on startup: {e}', exc_info=True)

try:
    # Warm the system-metrics disk-usage cache in the background so the first
    # Parameters -> Metrics page load isn't blocked on a cold recursive scan
    # (slow on Docker-Desktop-on-Windows bind mounts).
    from utils.metrics_collector import prime_disk_space_details_cache as _prime_metrics_cache

    _prime_metrics_cache()
except Exception as e:  # pragma: no cover
    logger.error(f'Failed to prime metrics disk-usage cache on startup: {e}', exc_info=True)


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
        from utils import push_scheduler as _ps

        _ps.stop()
    except Exception as e:  # pragma: no cover
        logger.warning(f"Error stopping push scheduler on exit: {e}")
    try:
        from connectors import mqtt_publisher as _mp

        _mp.stop()
    except Exception as e:
        logger.warning(f"Error stopping MQTT publisher on exit: {e}")


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
