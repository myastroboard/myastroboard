"""
Shared pytest fixtures and configuration for all tests
"""

import os
import signal
import sys
import tempfile


def pytest_sessionfinish(session, exitstatus):
    """Reset SIGTERM to a clean exit before pytest tears down.

    app.py registers a SIGTERM handler that re-raises the signal with the
    default handler restored. On Windows, the default SIGTERM handler exits
    with code 15. This hook replaces it with a clean sys.exit(0) so the
    test suite always exits with the real pass/fail code.
    """
    try:
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    except OSError, ValueError:
        pass  # signal registration unsupported in this environment (e.g. non-main thread)


# Force matplotlib non-GUI backend before any test imports matplotlib or a module
# that indirectly triggers it. Without this, the Tk backend can be loaded in the
# main thread and then Tcl/Tk objects get destroyed in background threads (jplephem
# ThreadPoolExecutor), causing fatal crashes on Windows. Optional: some CI jobs (e.g.
# the changelog-entry gate) install only `pytest`, with no scientific stack at all -
# conftest.py must still be importable there, same reasoning as the ImportError
# guards on the backend-module imports further down this file.
try:
    import matplotlib

    matplotlib.use('Agg')
except ImportError:
    pass

# Set up environment variables BEFORE any imports from backend
# This prevents permission errors when modules try to create directories
if 'DATA_DIR' not in os.environ:
    os.environ['DATA_DIR'] = tempfile.gettempdir()
if 'OUTPUT_DIR' not in os.environ:
    os.environ['OUTPUT_DIR'] = tempfile.gettempdir()
if 'CONFIG_DIR' not in os.environ:
    os.environ['CONFIG_DIR'] = tempfile.gettempdir()
if 'LOG_LEVEL' not in os.environ:
    os.environ['LOG_LEVEL'] = 'ERROR'
if 'CONSOLE_LOG_LEVEL' not in os.environ:
    os.environ['CONSOLE_LOG_LEVEL'] = 'ERROR'
# SECRET_KEY is no longer an env var — it's auto-generated in DATA_DIR/secret_key.txt


def _clean_stale_test_state():
    """Delete app-generated state files left in the temp root by previous runs.

    Backend modules are imported at pytest collection time (before any fixture
    can re-point DATA_DIR), so CONFIG_FILE & co. bind to the directory set
    above - and their files persist across runs. Since v1.2, load_config()
    persists the location migration (sticky preset ids), which turns leftover
    state into cross-run test pollution. This runs at conftest import time,
    BEFORE backend modules load that state into memory. Cheap-to-regenerate
    files only; expensive downloads (skyfield/IERS ephemeris, object images)
    are kept so runs stay fast.
    """
    data_root = os.environ['DATA_DIR']
    for name in ('config.json', 'users.json', 'secret_key.txt', 'app_settings.json'):
        try:
            os.remove(os.path.join(data_root, name))
        except OSError:
            pass  # file may not exist from a prior run; nothing to clean up
    cache_dir = os.path.join(data_root, 'cache')
    for name in ('astro_cache.json', 'astro_cache.lock', 'location_cache.json'):
        try:
            os.remove(os.path.join(cache_dir, name))
        except OSError:
            pass  # file may not exist from a prior run; nothing to clean up


_clean_stale_test_state()

import json
import shutil

import pytest

# Add backend to Python path
backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, backend_path)


# ---------------------------------------------------------------------------
# Database: every test runs on its own copy of a template database.
#
# The template is built here, at conftest import time - before the backend modules
# are imported during collection, since some of them read the database on import
# (utils.auth creates the default admin then). Whatever those imports write lands in
# the template, so each test starts from the "freshly started app" state.
# ---------------------------------------------------------------------------

_TEMPLATE_DB_PATH = os.path.join(tempfile.mkdtemp(prefix='myastroboard_test_db_'), 'template.db')
_template_db_bytes = None

try:
    from db import bootstrap as _db_bootstrap
    from db import engine as _db_engine
    from db import migrate as _db_migrate
except ImportError:  # minimal CI jobs (changelog gate) run without the backend dependencies
    _db_engine = None
else:
    _db_migrate.upgrade_to_head(_db_engine.configure_engine(f'sqlite:///{_TEMPLATE_DB_PATH}'))
    # The legacy JSON import is exercised by its own tests, never against the shared temp root.
    _db_bootstrap._ready = True


def _template_db() -> bytes:
    """The template database, checkpointed into a single file, read once."""
    global _template_db_bytes
    if _template_db_bytes is None:
        assert _db_engine is not None
        with _db_engine.get_engine().connect() as conn:
            conn.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
        _db_engine.configure_engine(f'sqlite:///{_TEMPLATE_DB_PATH}').dispose()
        with open(_TEMPLATE_DB_PATH, 'rb') as handle:
            _template_db_bytes = handle.read()
    return _template_db_bytes


@pytest.fixture(autouse=True)
def isolated_database(tmp_path_factory):
    """Point the engine at a fresh copy of the template database for this test.

    Foreign keys are off here: most tests store documents for made-up user ids. Tests
    about account deletion and its cascade use the ``enforce_foreign_keys`` fixture.
    """
    if _db_engine is None:
        yield None
        return
    # Its own directory, not tmp_path: tests that inspect tmp_path must not find the database there
    db_path = tmp_path_factory.mktemp('db') / 'myastroboard.db'
    db_path.write_bytes(_template_db())
    _db_engine.configure_engine(f'sqlite:///{db_path}', enforce_foreign_keys=False)
    try:
        from utils.auth import user_manager

        user_manager.invalidate_cache()
    except ImportError:
        pass  # backend not importable in this CI job
    yield str(db_path)
    _db_engine.configure_engine(f'sqlite:///{_TEMPLATE_DB_PATH}').dispose()


@pytest.fixture
def enforce_foreign_keys(isolated_database):
    """This test's database with foreign keys enforced, as in production."""
    _db_engine.configure_engine(f'sqlite:///{isolated_database}', enforce_foreign_keys=True)
    yield isolated_database


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables before any tests run"""
    # Create temporary directories for testing
    test_data_dir = tempfile.mkdtemp(prefix="test_data_")
    test_output_dir = tempfile.mkdtemp(prefix="test_output_")
    test_config_dir = tempfile.mkdtemp(prefix="test_config_")

    # Set environment variables
    os.environ['DATA_DIR'] = test_data_dir
    os.environ['OUTPUT_DIR'] = test_output_dir
    os.environ['CONFIG_DIR'] = test_config_dir
    os.environ['LOG_LEVEL'] = 'ERROR'
    os.environ['CONSOLE_LOG_LEVEL'] = 'ERROR'

    yield {'data_dir': test_data_dir, 'output_dir': test_output_dir, 'config_dir': test_config_dir}

    # Cleanup temporary directories
    shutil.rmtree(test_data_dir, ignore_errors=True)
    shutil.rmtree(test_output_dir, ignore_errors=True)
    shutil.rmtree(test_config_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_login_throttle():
    """Clear the in-memory password sign-in failure counters around each test.

    They are process-wide and keyed by client IP, so failed logins from earlier tests
    (all from the test client's address) would otherwise throttle later ones.
    """
    try:
        from blueprints import auth as auth_bp_module
    except ImportError:
        yield
        return
    auth_bp_module._login_failures_by_account.clear()
    auth_bp_module._login_failures_by_ip.clear()
    yield
    auth_bp_module._login_failures_by_account.clear()
    auth_bp_module._login_failures_by_ip.clear()


@pytest.fixture(autouse=True)
def reset_app_settings_module_cache():
    """Reset the app_settings module-level cache between tests."""
    try:
        from utils import app_settings

        app_settings._cache = None
    except ImportError:
        pass  # app_settings not available in all test configurations
    yield
    try:
        from utils import app_settings

        app_settings._cache = None
    except ImportError:
        pass  # app_settings not available in all test configurations


@pytest.fixture
def temp_dir():
    """Create a temporary directory for a test"""
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def temp_file():
    """Create a temporary file for a test"""
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except FileNotFoundError:
        pass  # already removed by the test itself


@pytest.fixture
def sample_config():
    """Return a sample configuration dictionary matching the current DEFAULT_CONFIG structure (v1.2)."""
    return {
        "locations": [
            {
                "id": "sample-loc-1",
                "name": "Test Location",
                "latitude": 45.5,
                "longitude": -73.5,
                "elevation": 50,
                "timezone": "America/Montreal",
                "bortle": None,
                "sqm": None,
                "horizon_profile": [],
                "is_install_default": True,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "location_configured": True,
        "min_altitude": 25,
        "astrodex": {"private": False},
        "skytonight": {
            "enabled": True,
            "constraints_always_enabled": True,
            "preferred_name_order": ["OpenNGC", "Messier"],
            "constraints": {
                "altitude_constraint_min": 25,
                "altitude_constraint_max": 75,
                "airmass_constraint": 2,
                "size_constraint_min": 10,
                "size_constraint_max": 300,
                "moon_separation_min": 30,
                "moon_separation_use_illumination": True,
                "fraction_of_time_observable_threshold": 0.5,
                "north_to_east_ccw": False,
            },
            "scheduler": {
                "mode": "fallback-6h",
                "server_time_valid": False,
                "next_run": None,
                "last_run": None,
            },
            "datasets": {
                "catalogues": {"deep_sky": True, "bodies": True, "comets": True},
                "comets": {"source": "mpc+jpl", "auto_update": True},
            },
        },
    }


@pytest.fixture
def sample_json_file(temp_file, sample_config):
    """Create a temporary JSON file with sample config"""
    with open(temp_file, 'w') as f:
        json.dump(sample_config, f)
    return temp_file


@pytest.fixture
def mock_catalogues_file(temp_dir):
    """Create a mock catalogues.json file"""
    catalogues_path = os.path.join(temp_dir, 'catalogues.json')
    with open(catalogues_path, 'w') as f:
        json.dump({"generated_at": "2026-02-23T00:00:00Z", "catalogues": ["Messier", "Herschel400", "OpenNGC"]}, f)
    return catalogues_path


@pytest.fixture
def sample_coordinates():
    """Return sample coordinate data for testing"""
    return [
        {"dms": "48d38m36.16s", "decimal": 48.64337777777778},
        {"dms": "2d20m14.025s", "decimal": 2.337229166666667},
        {"dms": "-45d30m0s", "decimal": -45.5},
        {"dms": "0d0m0s", "decimal": 0.0},
    ]


# ---------------------------------------------------------------------------
# Shared Flask test-client fixtures (used by test_app_routes and
# test_coverage_paths; kept here so both modules can access them without
# importing from each other).
# ---------------------------------------------------------------------------

import tempfile as _tmpfile
import types as _types
import uuid as _uuid

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = _types.ModuleType('psutil')


@pytest.fixture
def client():
    """Unauthenticated Flask test client."""
    from app import app as _flask_app

    _flask_app.config['TESTING'] = True
    with _flask_app.test_client() as c:
        yield c


@pytest.fixture
def client_admin():
    """Admin-authenticated Flask test client."""
    from app import app as _flask_app
    from utils.auth import user_manager as _um

    _flask_app.config['TESTING'] = True
    with _tmpfile.TemporaryDirectory():
        with _flask_app.test_client() as c:
            user = _um.get_user_by_username('admin')
            assert user is not None
            with c.session_transaction() as sess:
                sess['user_id'] = user.user_id
                sess['username'] = user.username
                sess['role'] = user.role
            yield c


@pytest.fixture
def client_user():
    """Regular-user (non-admin) Flask test client."""
    from app import app as _flask_app

    _flask_app.config['TESTING'] = True
    with _tmpfile.TemporaryDirectory():
        with _flask_app.test_client() as c:
            temp_id = str(_uuid.uuid4())
            with c.session_transaction() as sess:
                sess['user_id'] = temp_id
                sess['username'] = 'testuser'
                sess['role'] = 'user'
            yield c
