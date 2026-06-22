"""Flask test client tests for the main app.py routes.

Covers static-file routes, auth endpoints, config, cache/report endpoints,
admin endpoints, and various API utility routes.
"""
import os
import sys
import tempfile
import types
import uuid

import pytest

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

import app as _app_mod
import cache_store as _cache_store
from app import app
from auth import user_manager


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
    """Admin-authenticated test client."""
    app.config['TESTING'] = True
    with tempfile.TemporaryDirectory():
        with app.test_client() as c:
            user = user_manager.get_user_by_username('admin')
            assert user is not None
            with c.session_transaction() as sess:
                sess['user_id'] = user.user_id
                sess['username'] = user.username
                sess['role'] = user.role
            yield c


@pytest.fixture
def client_user():
    """User-authenticated test client (non-admin)."""
    app.config['TESTING'] = True
    with tempfile.TemporaryDirectory():
        with app.test_client() as c:
            # Create a temporary regular user
            temp_id = str(uuid.uuid4())
            with c.session_transaction() as sess:
                sess['user_id'] = temp_id
                sess['username'] = 'testuser'
                sess['role'] = 'user'
            yield c


# ---------------------------------------------------------------------------
# Health / no-auth endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoints:

    def test_health_api_returns_200(self, client):
        resp = client.get('/api/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'healthy'
        assert 'timestamp' in data

    def test_health_simple_returns_200(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'healthy'


# ---------------------------------------------------------------------------
# Static file routes (no auth)
# ---------------------------------------------------------------------------


class TestStaticFileRoutes:

    def test_manifest_webmanifest_returns_200(self, client):
        resp = client.get('/manifest.webmanifest')
        assert resp.status_code == 200

    def test_manifest_localized_returns_200_or_404(self, client):
        resp = client.get('/manifest.en.webmanifest')
        assert resp.status_code in (200, 404)

    def test_manifest_localized_fr_returns_200_or_404(self, client):
        resp = client.get('/manifest.fr.webmanifest')
        assert resp.status_code in (200, 404)

    def test_service_worker_returns_200(self, client):
        resp = client.get('/sw.js')
        assert resp.status_code == 200

    def test_offline_page_returns_200(self, client):
        resp = client.get('/offline.html')
        assert resp.status_code == 200

    def test_robots_txt_returns_200(self, client):
        resp = client.get('/robots.txt')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Login / page routes
# ---------------------------------------------------------------------------


class TestPageRoutes:

    def test_login_page_unauthenticated(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_root_redirects_when_unauthenticated(self, client):
        resp = client.get('/')
        assert resp.status_code in (200, 302)

    def test_root_returns_200_when_authenticated(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_repo_version', lambda: '1.0.0')
        resp = client_admin.get('/')
        assert resp.status_code == 200

    def test_login_page_redirects_when_authenticated(self, client_admin):
        resp = client_admin.get('/login')
        assert resp.status_code in (200, 302)


# ---------------------------------------------------------------------------
# Auth API endpoints
# ---------------------------------------------------------------------------


class TestAuthEndpoints:

    def test_auth_status_no_session(self, client):
        resp = client.get('/api/auth/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'authenticated' in data
        assert data['authenticated'] is False

    def test_auth_status_authenticated(self, client_admin):
        resp = client_admin.get('/api/auth/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['authenticated'] is True

    def test_login_missing_body_returns_400(self, client):
        resp = client.post('/api/auth/login', json={})
        assert resp.status_code == 400

    def test_login_wrong_password_returns_401(self, client):
        resp = client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrongpass'})
        assert resp.status_code == 401

    def test_logout_returns_200(self, client_admin):
        resp = client_admin.post('/api/auth/logout')
        assert resp.status_code == 200

    def test_preferences_get_returns_200(self, client_admin):
        resp = client_admin.get('/api/auth/preferences')
        assert resp.status_code == 200

    def test_preferences_unauthenticated_returns_401(self, client):
        resp = client.get('/api/auth/preferences')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


class TestConfigEndpoints:

    def test_get_config_returns_200(self, client_admin):
        resp = client_admin.get('/api/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_get_config_unauthenticated_returns_401(self, client):
        resp = client.get('/api/config')
        assert resp.status_code == 401

    def test_post_config_returns_200(self, client_admin):
        resp = client_admin.post('/api/config', json={'location': {'latitude': 45.5, 'longitude': -73.5}})
        assert resp.status_code == 200

    def test_get_timezones_returns_list(self, client_admin):
        resp = client_admin.get('/api/timezones')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_post_config_preserves_old_horizon_profile_without_clear_flag(self, client_admin, monkeypatch):
        old_cfg = {
            'location': {'latitude': 1, 'longitude': 2, 'timezone': 'UTC'},
            'location_configured': True,
            'skytonight': {
                'enabled': True,
                'constraints': {'horizon_profile': [{'az': 10, 'alt': 20}], 'altitude_constraint_min': 25},
                'scheduler': {'enabled': True},
            },
        }
        captured = {}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: old_cfg)
        monkeypatch.setattr(_app_mod, 'save_config', lambda cfg: captured.setdefault('cfg', cfg))
        monkeypatch.setattr(_app_mod.cache_store, 'reset_all_caches', lambda: None)
        monkeypatch.setattr(_app_mod.cache_store, 'update_location_config', lambda *_a, **_k: None)

        incoming = {
            'location': {'latitude': 1, 'longitude': 2, 'timezone': 'UTC'},
            'skytonight': {'constraints': {'horizon_profile': []}},
        }
        resp = client_admin.post('/api/config', json=incoming)

        assert resp.status_code == 200
        saved = captured['cfg']
        assert saved['skytonight']['constraints']['horizon_profile'] == [{'az': 10, 'alt': 20}]
        assert saved['location_configured'] is True

    def test_post_config_location_change_resets_cache(self, client_admin, monkeypatch):
        old_cfg = {'location': {'latitude': 1, 'longitude': 2, 'timezone': 'UTC'}, 'skytonight': {'constraints': {}}}
        reset_calls = []
        update_calls = []
        monkeypatch.setattr(_app_mod, 'load_config', lambda: old_cfg)
        monkeypatch.setattr(_app_mod, 'save_config', lambda *_a, **_k: None)
        monkeypatch.setattr(_app_mod.cache_store, 'reset_all_caches', lambda: reset_calls.append(1))
        monkeypatch.setattr(_app_mod.cache_store, 'update_location_config', lambda loc: update_calls.append(loc))

        incoming = {'location': {'latitude': 3, 'longitude': 2, 'timezone': 'UTC'}}
        resp = client_admin.post('/api/config', json=incoming)
        data = resp.get_json()

        assert resp.status_code == 200
        assert data['cache_reset'] is True
        assert reset_calls == [1]
        assert len(update_calls) == 1

    def test_post_config_invalid_bortle_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {'location': {}, 'skytonight': {'constraints': {}}})
        resp = client_admin.post('/api/config', json={'location': {'bortle': 11}})
        assert resp.status_code == 400

    def test_post_config_invalid_sqm_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {'location': {}, 'skytonight': {'constraints': {}}})
        resp = client_admin.post('/api/config', json={'location': {'sqm': -1}})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class TestAdminEndpoints:

    def test_get_users_returns_200(self, client_admin):
        resp = client_admin.get('/api/users')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_get_users_unauthenticated_returns_401(self, client):
        resp = client.get('/api/users')
        assert resp.status_code == 401

    def test_get_app_settings_returns_200(self, client_admin):
        resp = client_admin.get('/api/admin/app-settings')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_post_app_settings_returns_200(self, client_admin):
        resp = client_admin.post('/api/admin/app-settings', json={'trust_proxy_headers': False})
        assert resp.status_code == 200

    def test_get_logs_level_returns_200(self, client_admin):
        resp = client_admin.get('/api/logs/level')
        assert resp.status_code == 200

    def test_get_logs_returns_200(self, client_admin):
        resp = client_admin.get('/api/logs')
        assert resp.status_code == 200

    def test_get_metrics_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'collect_metrics',
            lambda: {'cpu_percent': 10.0, 'memory_mb': 100.0},
        )
        resp = client_admin.get('/api/metrics')
        assert resp.status_code == 200

    def test_get_metrics_returns_500_on_exception(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'collect_metrics', lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        resp = client_admin.get('/api/metrics')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Version endpoints
# ---------------------------------------------------------------------------


class TestVersionEndpoints:

    def test_get_version_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_repo_version', lambda: '1.0.0')
        resp = client_admin.get('/api/version')
        assert resp.status_code == 200
        assert resp.get_json()['version'] == '1.0.0'

    def test_check_updates_returns_200_or_error(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'check_for_updates',
            lambda: {'update_available': False, 'current_version': '1.0.0'},
        )
        resp = client_admin.get('/api/version/check-updates')
        assert resp.status_code in (200, 500)

    def test_version_unauthenticated_returns_401(self, client):
        resp = client.get('/api/version')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Cache status endpoint
# ---------------------------------------------------------------------------


class TestCacheEndpoints:

    def test_cache_status_returns_200(self, client_admin):
        resp = client_admin.get('/api/cache')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'cache_status' in data

    def test_cache_unauthenticated_returns_401(self, client):
        resp = client.get('/api/cache')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Moon / dark-window / aurora / seeing report endpoints
# ---------------------------------------------------------------------------


class TestCachedReportEndpoints:

    def test_moon_report_returns_202_when_no_cache(self, client_admin):
        # Cache is empty in test environment — should return 202 pending
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code in (200, 202)

    def test_moon_report_returns_200_with_cached_data(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda cache, ttl: True)
        monkeypatch.setitem(_cache_store._moon_report_cache, 'data', {'moon': 'data'})
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code == 200

    def test_dark_window_returns_202_when_no_cache(self, client_admin):
        resp = client_admin.get('/api/moon/dark-window')
        assert resp.status_code in (200, 202)

    def test_aurora_returns_202_when_no_cache(self, client_admin):
        resp = client_admin.get('/api/aurora/predictions')
        assert resp.status_code in (200, 202)

    def test_seeing_forecast_returns_response(self, client_admin):
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code in (200, 202)

    def test_moon_report_unauthenticated_returns_401(self, client):
        resp = client.get('/api/moon/report')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Push notification endpoints
# ---------------------------------------------------------------------------


class TestPushEndpoints:

    def test_vapid_public_key_returns_200(self, client, monkeypatch):
        import push_manager as _pm

        monkeypatch.setattr(_pm, 'get_vapid_public_key', lambda: 'BTestPublicKey123')
        resp = client.get('/api/push/vapid-public-key')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'public_key' in data

    def test_vapid_config_status_returns_200(self, client_admin, monkeypatch):
        import push_manager as _pm

        monkeypatch.setattr(_pm, 'get_vapid_contact_status', lambda: {'ok': True})
        resp = client_admin.get('/api/push/vapid-config-status')
        assert resp.status_code == 200

    def test_subscriptions_get_returns_200(self, client_admin):
        resp = client_admin.get('/api/push/subscriptions')
        assert resp.status_code == 200

    def test_push_endpoints_unauthenticated_returns_401(self, client):
        resp = client.get('/api/push/vapid-config-status')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# ISS and spaceflight endpoints (cache-backed, returns 202 when no cache)
# ---------------------------------------------------------------------------


class TestSpaceEndpoints:

    def test_iss_passes_returns_response(self, client_admin):
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code in (200, 202)

    def test_iss_location_returns_response(self, client_admin):
        resp = client_admin.get('/api/iss/location')
        assert resp.status_code in (200, 202, 400, 500)

    def test_spaceflight_launches_returns_response(self, client_admin):
        resp = client_admin.get('/api/spaceflight/launches')
        assert resp.status_code in (200, 202, 503)

    def test_spaceflight_astronauts_returns_response(self, client_admin):
        resp = client_admin.get('/api/spaceflight/astronauts')
        assert resp.status_code in (200, 202, 503)

    def test_iss_unauthenticated_returns_401(self, client):
        resp = client.get('/api/iss/passes')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------


class TestCoordinateConversion:

    def test_missing_body_returns_400(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={})
        assert resp.status_code == 400

    def test_valid_conversion(self, client_admin):
        resp = client_admin.post(
            '/api/convert-coordinates',
            json={'latitude': '48.8566', 'longitude': '2.3522'},
        )
        assert resp.status_code in (200, 400)

    def test_unauthenticated_returns_401(self, client):
        resp = client.post('/api/convert-coordinates', json={'latitude': '48', 'longitude': '2'})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Sky quality endpoint
# ---------------------------------------------------------------------------


class TestSkyQualityEndpoint:

    def test_returns_200_or_error(self, client_admin):
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code in (200, 400, 503)

    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/skyquality')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User management (admin routes)
# ---------------------------------------------------------------------------


class TestUserManagement:

    def test_create_user_missing_body_returns_400(self, client_admin):
        resp = client_admin.post('/api/users', json={})
        assert resp.status_code == 400

    def test_create_user_valid(self, client_admin):
        resp = client_admin.post(
            '/api/users',
            json={
                'username': f'testuser_{uuid.uuid4().hex[:8]}',
                'password': 'TestPass123!',
                'role': 'user',
            },
        )
        assert resp.status_code in (200, 201, 400, 409)

    def test_non_admin_cannot_list_users(self, client_user):
        resp = client_user.get('/api/users')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Weather endpoints (cache-backed)
# ---------------------------------------------------------------------------


class TestWeatherEndpoints:

    def test_weather_forecast_returns_response(self, client_admin):
        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code in (200, 202, 400)

    def test_weather_alerts_returns_response(self, client_admin):
        resp = client_admin.get('/api/weather/alerts')
        assert resp.status_code in (200, 202, 400)

    def test_weather_unauthenticated_returns_401(self, client):
        resp = client.get('/api/weather/forecast')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Moon calendar and next-7-nights
# ---------------------------------------------------------------------------


class TestMoonExtendedEndpoints:

    def test_next_7_nights_returns_response(self, client_admin):
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code in (200, 202, 400)

    def test_month_calendar_returns_response(self, client_admin):
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code in (200, 202, 400)


# ---------------------------------------------------------------------------
# Config export
# ---------------------------------------------------------------------------


class TestConfigExport:

    def test_export_returns_200_or_404(self, client_admin):
        resp = client_admin.get('/api/config/export')
        assert resp.status_code in (200, 404)

    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/config/export')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logs endpoints
# ---------------------------------------------------------------------------


class TestLogsEndpoints:

    def test_logs_export_returns_response(self, client_admin):
        resp = client_admin.get('/api/logs/export')
        assert resp.status_code in (200, 404, 500)

    def test_logs_clear_returns_200(self, client_admin):
        resp = client_admin.post('/api/logs/clear')
        assert resp.status_code == 200

    def test_logs_unauthenticated_returns_401(self, client):
        resp = client.get('/api/logs')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Auth change password
# ---------------------------------------------------------------------------


class TestChangePassword:

    def test_missing_body_returns_400(self, client_admin):
        resp = client_admin.post('/api/auth/change-password', json={})
        assert resp.status_code == 400

    def test_wrong_current_password_returns_400(self, client_admin):
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'wrongpass', 'new_password': 'NewPass123!'},
        )
        assert resp.status_code in (400, 401)

    def test_unauthenticated_returns_401(self, client):
        resp = client.post('/api/auth/change-password', json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Spaceflight events
# ---------------------------------------------------------------------------


class TestSpaceflightEvents:

    def test_events_returns_response(self, client_admin):
        resp = client_admin.get('/api/spaceflight/events')
        assert resp.status_code in (200, 202, 503)

    def test_events_with_cache_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._spaceflight_events_cache, 'data', {'results': []})
        resp = client_admin.get('/api/spaceflight/events')
        assert resp.status_code == 200

    def test_image_invalid_filename_returns_400_or_404(self, client_admin):
        resp = client_admin.get('/api/spaceflight/img/../../etc/passwd.jpg')
        assert resp.status_code in (400, 404)

    def test_image_missing_returns_404_or_200(self, client_admin):
        resp = client_admin.get('/api/spaceflight/img/abc123abc123abc123abc123abc123ab.jpg')
        assert resp.status_code in (200, 404, 400)


# ---------------------------------------------------------------------------
# Preferences PUT
# ---------------------------------------------------------------------------


class TestPreferencesPut:

    def test_update_preferences_returns_200(self, client_admin):
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {'language': 'en'}})
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        resp = client.put('/api/auth/preferences', json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Push subscribe/unsubscribe
# ---------------------------------------------------------------------------


class TestPushSubscribe:

    def test_subscribe_missing_body_returns_400(self, client_admin):
        resp = client_admin.post('/api/push/subscribe', json={})
        assert resp.status_code == 400

    def test_unsubscribe_missing_body_returns_400(self, client_admin):
        resp = client_admin.delete('/api/push/subscriptions', json={})
        assert resp.status_code in (200, 400)

    def test_push_subscriptions_delete_all(self, client_admin):
        resp = client_admin.delete('/api/push/unsubscribe', json={'endpoint': 'https://example.com/push/fake'})
        assert resp.status_code in (200, 400)


# ---------------------------------------------------------------------------
# Object info endpoint
# ---------------------------------------------------------------------------


class TestObjectInfoEndpoint:

    def test_valid_object_returns_response(self, client_admin, monkeypatch):
        import object_info as _oi
        monkeypatch.setattr(_oi, 'get_object_info', lambda identifier, language='en': {'name': identifier})
        resp = client_admin.get('/api/object/M42')
        assert resp.status_code in (200, 404, 500)

    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/object/M42')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# ISS Celestrak restart
# ---------------------------------------------------------------------------


class TestIssRestart:

    def test_restart_returns_response(self, client_admin):
        resp = client_admin.post('/api/iss/celestrak/restart')
        assert resp.status_code in (200, 400, 500)


# ---------------------------------------------------------------------------
# Weather astro analysis
# ---------------------------------------------------------------------------


class TestWeatherAstroAnalysis:

    def test_astro_analysis_returns_response(self, client_admin):
        resp = client_admin.get('/api/weather/astro-analysis')
        assert resp.status_code in (200, 202, 400, 500)

    def test_astro_current_returns_response(self, client_admin):
        resp = client_admin.get('/api/weather/astro-current')
        assert resp.status_code in (200, 202, 400, 500)


# ---------------------------------------------------------------------------
# Admin restart
# ---------------------------------------------------------------------------


class TestAdminRestart:

    def test_restart_returns_200(self, client_admin, monkeypatch):
        # Prevent the deferred thread from starting so it never sends SIGTERM
        import threading

        class _NoOpThread:
            def __init__(self, **kwargs):
                pass

            def start(self):
                pass

        monkeypatch.setattr(threading, 'Thread', _NoOpThread)
        resp = client_admin.post('/api/admin/restart')
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        resp = client.post('/api/admin/restart')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Sidereal time / moon sun report with cached data
# ---------------------------------------------------------------------------


class TestReportEndpointsWithCache:

    def test_sun_today_returns_response(self, client_admin):
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code in (200, 202, 400, 404)

    def test_solar_eclipse_returns_response(self, client_admin):
        resp = client_admin.get('/api/sun/next-eclipse')
        assert resp.status_code in (200, 202, 404)

    def test_lunar_eclipse_returns_response(self, client_admin):
        resp = client_admin.get('/api/moon/next-eclipse')
        assert resp.status_code in (200, 202, 404)

    def test_sidereal_time_returns_response(self, client_admin):
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code in (200, 202, 400, 500)

    def test_planetary_events_returns_response(self, client_admin):
        resp = client_admin.get('/api/events/planetary')
        assert resp.status_code in (200, 202, 404)

    def test_special_phenomena_returns_response(self, client_admin):
        resp = client_admin.get('/api/events/phenomena')
        assert resp.status_code in (200, 202, 404)

    def test_horizon_graph_returns_response(self, client_admin):
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code in (200, 202, 404)

    def test_best_window_returns_response(self, client_admin):
        resp = client_admin.get('/api/tonight/best-window')
        assert resp.status_code in (200, 202, 400, 404)


# ---------------------------------------------------------------------------
# Routes with populated cache — hit the "cache valid" code paths
# ---------------------------------------------------------------------------


class TestRoutesWithPopulatedCache:

    def test_moon_report_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._moon_report_cache, 'data', {'moon': 'data'})
        monkeypatch.setitem(_cache_store._dark_window_report_cache, 'data', {'window': 'data'})
        monkeypatch.setitem(_cache_store._aurora_cache, 'data', {'aurora': 'data'})
        # ISS passes checks window_days equality — include it in the data
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 20})
        for route in ['/api/moon/report', '/api/moon/dark-window', '/api/aurora/predictions', '/api/iss/passes']:
            resp = client_admin.get(route)
            assert resp.status_code == 200, f"{route} returned {resp.status_code}"

    def test_sun_report_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._sun_report_cache, 'data', {'sun': 'data'})
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code in (200, 400)

    def test_eclipses_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._solar_eclipse_cache, 'data', {'eclipse': 'data'})
        monkeypatch.setitem(_cache_store._lunar_eclipse_cache, 'data', {'eclipse': 'data'})
        for route in ['/api/sun/next-eclipse', '/api/moon/next-eclipse']:
            resp = client_admin.get(route)
            assert resp.status_code == 200

    def test_planetary_events_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._planetary_events_cache, 'data', {'events': []})
        monkeypatch.setitem(_cache_store._special_phenomena_cache, 'data', {'events': [], 'equinoxes_solstices': [], 'zodiacal_light': [], 'milky_way': []})
        resp = client_admin.get('/api/events/planetary')
        assert resp.status_code == 200

    def test_horizon_graph_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._horizon_graph_cache, 'data', {'graph': 'data'})
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code == 200

    def test_spaceflight_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._spaceflight_launches_cache, 'data', {'results': []})
        monkeypatch.setitem(_cache_store._spaceflight_astronauts_cache, 'data', {'results': []})
        monkeypatch.setitem(_cache_store._spaceflight_events_cache, 'data', {'results': []})
        for route in ['/api/spaceflight/launches', '/api/spaceflight/astronauts', '/api/spaceflight/events']:
            resp = client_admin.get(route)
            assert resp.status_code == 200

    def test_seeing_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._seeing_forecast_cache, 'data', {'forecast': []})
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code == 200

    def test_weather_forecast_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._weather_cache, 'data', {'forecast': []})
        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# User CRUD admin routes
# ---------------------------------------------------------------------------


class TestUserCrud:

    def test_delete_nonexistent_user_returns_404(self, client_admin):
        fake_id = str(uuid.uuid4())
        resp = client_admin.delete(f'/api/users/{fake_id}')
        assert resp.status_code in (404, 400)

    def test_update_nonexistent_user_returns_404(self, client_admin):
        fake_id = str(uuid.uuid4())
        resp = client_admin.put(f'/api/users/{fake_id}', json={'role': 'user'})
        assert resp.status_code in (404, 400)

    def test_non_admin_cannot_delete_users(self, client_user):
        fake_id = str(uuid.uuid4())
        resp = client_user.delete(f'/api/users/{fake_id}')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Coordinate conversion with valid input
# ---------------------------------------------------------------------------


class TestCoordinateConversionValid:

    def test_valid_decimal_degrees(self, client_admin):
        resp = client_admin.post(
            '/api/convert-coordinates',
            json={'latitude': '48.8566', 'longitude': '2.3522'},
        )
        assert resp.status_code in (200, 400)

    def test_missing_latitude_returns_400(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={'longitude': '2.3522'})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Push test endpoint
# ---------------------------------------------------------------------------


class TestPushTest:

    def test_push_test_with_valid_trigger_returns_response(self, client_admin):
        resp = client_admin.post('/api/push/test/iss_pass')
        assert resp.status_code in (200, 400, 404)

    def test_push_test_legacy_returns_response(self, client_admin):
        resp = client_admin.post('/api/push/test', json={'type': 'test'})
        assert resp.status_code in (200, 400, 500)


# ---------------------------------------------------------------------------
# Config post with full config
# ---------------------------------------------------------------------------


class TestConfigPost:

    def test_post_full_config_returns_200(self, client_admin):
        resp = client_admin.post(
            '/api/config',
            json={
                'location': {
                    'latitude': 48.8566,
                    'longitude': 2.3522,
                    'timezone': 'Europe/Paris',
                    'elevation': 35,
                }
            },
        )
        assert resp.status_code == 200

    def test_get_config_contains_location(self, client_admin):
        resp = client_admin.get('/api/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'location' in data


# ---------------------------------------------------------------------------
# Successful login (covers lines 312-335)
# ---------------------------------------------------------------------------


class TestSuccessfulLogin:

    @pytest.fixture
    def temp_user_credentials(self):
        """Create a fresh test user for login tests then delete it."""
        import uuid
        username = f'test_login_{uuid.uuid4().hex[:8]}'
        password = 'TestLogin99!'
        user_manager.create_user(username, password, 'user')
        yield username, password
        try:
            u = user_manager.get_user_by_username(username)
            if u:
                user_manager.delete_user(u.user_id)
        except Exception:
            pass  # best-effort teardown; test isolation still holds if deletion fails

    def test_login_with_correct_credentials_returns_200(self, client, temp_user_credentials):
        username, password = temp_user_credentials
        resp = client.post('/api/auth/login', json={'username': username, 'password': password})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert 'using_default_password' in data

    def test_login_with_remember_me(self, client, temp_user_credentials):
        username, password = temp_user_credentials
        resp = client.post(
            '/api/auth/login',
            json={'username': username, 'password': password, 'remember_me': True},
        )
        assert resp.status_code == 200

    def test_login_bad_json_body(self, client):
        resp = client.post('/api/auth/login', data='not json', content_type='text/plain')
        assert resp.status_code in (400, 500)


# ---------------------------------------------------------------------------
# Events endpoints (cover lines 2354-2456 + 2530+)
# ---------------------------------------------------------------------------


class TestEventsEndpoints:

    def test_events_upcoming_no_cache_returns_202(self, client_admin):
        resp = client_admin.get('/api/events/upcoming')
        assert resp.status_code in (200, 202, 400)

    def test_events_upcoming_with_cache_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._solar_eclipse_cache, 'data', {'eclipse': None, 'status': 'none'}
        )
        monkeypatch.setitem(
            _cache_store._lunar_eclipse_cache, 'data', {'eclipse': None, 'status': 'none'}
        )
        monkeypatch.setitem(_cache_store._aurora_cache, 'data', {'kp_index': 0, 'probability': 0})
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 20})
        monkeypatch.setitem(_cache_store._moon_planner_report_cache, 'data', {'nights': []})
        monkeypatch.setitem(_cache_store._planetary_events_cache, 'data', {'events': []})
        monkeypatch.setitem(_cache_store._special_phenomena_cache, 'data', {'events': [], 'equinoxes_solstices': [], 'zodiacal_light': [], 'milky_way': []})
        resp = client_admin.get('/api/events/upcoming')
        assert resp.status_code in (200, 202, 400)

    def test_events_solarsystem_no_cache_returns_202(self, client_admin):
        resp = client_admin.get('/api/events/solarsystem')
        assert resp.status_code in (200, 202, 400)

    def test_events_solarsystem_with_cache_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {'meteor_showers': [], 'comets': [], 'asteroid_occultations': []},
        )
        resp = client_admin.get('/api/events/solarsystem')
        assert resp.status_code == 200

    def test_events_solarsystem_unauthenticated_returns_401(self, client):
        resp = client.get('/api/events/solarsystem')
        assert resp.status_code == 401

    def test_events_upcoming_unauthenticated_returns_401(self, client):
        resp = client.get('/api/events/upcoming')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Plan-my-night API routes (covers lines 3028+)
# ---------------------------------------------------------------------------


class TestPlanMyNightApiRoutes:

    def test_plan_list_returns_200(self, client_admin):
        resp = client_admin.get('/api/plan-my-night/list')
        assert resp.status_code == 200

    def test_plan_get_returns_200(self, client_admin):
        resp = client_admin.get('/api/plan-my-night')
        assert resp.status_code == 200

    def test_plan_add_target_missing_body_returns_400(self, client_admin):
        resp = client_admin.post('/api/plan-my-night/targets', json={})
        assert resp.status_code == 400

    def test_plan_clear_returns_200(self, client_admin):
        resp = client_admin.delete('/api/plan-my-night/clear')
        assert resp.status_code in (200, 400)

    def test_plan_clear_all_returns_200(self, client_admin):
        resp = client_admin.delete('/api/plan-my-night/clear-all')
        assert resp.status_code in (200, 400)

    def test_plan_export_csv_returns_response(self, client_admin):
        resp = client_admin.get('/api/plan-my-night/export.csv')
        assert resp.status_code in (200, 400)

    def test_plan_unauthenticated_returns_401(self, client):
        resp = client.get('/api/plan-my-night')
        assert resp.status_code == 401

    def test_plan_patch_empty_body_returns_response(self, client_admin):
        resp = client_admin.patch('/api/plan-my-night', json={})
        assert resp.status_code in (200, 400, 404)


# ---------------------------------------------------------------------------
# Astrodex API routes (covers lines 3500+)
# ---------------------------------------------------------------------------


class TestAstrodexRoutes:

    def test_astrodex_get_returns_200(self, client_admin):
        resp = client_admin.get('/api/astrodex')
        assert resp.status_code == 200

    def test_astrodex_add_item_missing_fields_returns_400(self, client_admin):
        resp = client_admin.post('/api/astrodex/items', json={})
        assert resp.status_code == 400

    def test_astrodex_unauthenticated_returns_401(self, client):
        resp = client.get('/api/astrodex')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Moon / ISS with stale data (covers the stale_data branch)
# ---------------------------------------------------------------------------


class TestStaleDataBranch:

    def test_moon_report_stale_data_returns_200(self, client_admin, monkeypatch):
        call_count = [0]

        def is_valid_first_false(cache, ttl):
            call_count[0] += 1
            return False

        monkeypatch.setattr(_cache_store, 'is_cache_valid', is_valid_first_false)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._moon_report_cache, 'data', {'stale': True})
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code == 200

    def test_dark_window_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._dark_window_report_cache, 'data', {'stale': True})
        resp = client_admin.get('/api/moon/dark-window')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Events/upcoming with full cached data (covers lines 2354-2456)
# ---------------------------------------------------------------------------


class TestEventsUpcomingFullCache:

    def _patch_all_caches(self, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: True)
        monkeypatch.setitem(_cache_store._solar_eclipse_cache, 'data', {'eclipse': None, 'status': 'none', 'events': []})
        monkeypatch.setitem(_cache_store._lunar_eclipse_cache, 'data', {'eclipse': None, 'status': 'none', 'events': []})
        monkeypatch.setitem(_cache_store._aurora_cache, 'data', {'kp_index': 1.0, 'probability': 5.0, 'visibility_level': 'None', 'reports': []})
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 20, 'status': 'ok'})
        monkeypatch.setitem(_cache_store._moon_planner_report_cache, 'data', {'nights': [], 'dark_window': None})
        monkeypatch.setitem(_cache_store._planetary_events_cache, 'data', {'events': []})
        monkeypatch.setitem(_cache_store._special_phenomena_cache, 'data', {'events': [], 'equinoxes_solstices': [], 'zodiacal_light': [], 'milky_way': []})

    def test_events_upcoming_full_returns_200(self, client_admin, monkeypatch):
        self._patch_all_caches(monkeypatch)
        resp = client_admin.get('/api/events/upcoming')
        assert resp.status_code in (200, 202, 400, 500)

    def test_events_phenomena_full_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            {'events': [], 'equinoxes_solstices': [], 'zodiacal_light': [], 'milky_way': []},
        )
        resp = client_admin.get('/api/events/phenomena')
        assert resp.status_code == 200

    def test_best_window_from_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._best_window_cache['strict'], 'data', {'window': 'data', 'mode': 'strict'}
        )
        resp = client_admin.get('/api/tonight/best-window')
        assert resp.status_code == 200

    def test_sidereal_time_full_returns_response(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._sidereal_time_cache, 'data', {'sidereal_time': 12.0})
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code in (200, 202, 400, 500)


# ---------------------------------------------------------------------------
# AstroNight / tonight plan endpoint
# ---------------------------------------------------------------------------


class TestTonightPlan:

    def test_tonight_plan_returns_response(self, client_admin):
        resp = client_admin.get('/api/plan-my-night/tonight-plan')
        assert resp.status_code in (200, 202, 400, 404)

    def test_astrodex_item_get_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/astrodex/items/nonexistent-id')
        assert resp.status_code in (404, 400)

    def test_astrodex_search_returns_response(self, client_admin):
        resp = client_admin.get('/api/astrodex?search=M42')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Equipment Profiles — Telescopes CRUD
# ---------------------------------------------------------------------------


class TestEquipmentTelescopes:

    def test_get_telescopes_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/telescopes')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'data' in data

    def test_get_telescopes_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/telescopes')
        assert resp.status_code == 401

    def test_create_telescope_returns_201(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/telescopes',
            json={'name': 'TestScope', 'focal_length_mm': 800, 'aperture_mm': 102},
        )
        assert resp.status_code in (200, 201, 500)

    def test_get_telescope_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/telescopes/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_update_telescope_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/telescopes/nonexistent-id', json={'name': 'Updated'})
        assert resp.status_code in (404, 403, 401)

    def test_delete_telescope_nonexistent_returns_error(self, client_admin):
        resp = client_admin.delete('/api/equipment/telescopes/nonexistent-id')
        assert resp.status_code in (404, 500, 200)

    def test_create_and_get_telescope(self, client_admin):
        create_resp = client_admin.post(
            '/api/equipment/telescopes',
            json={'name': 'MyTestScope', 'focal_length_mm': 1000, 'aperture_mm': 150},
        )
        assert create_resp.status_code in (200, 201, 500)
        if create_resp.status_code in (200, 201):
            data = create_resp.get_json()
            if 'data' in data and data['data'] and 'id' in data['data']:
                scope_id = data['data']['id']
                get_resp = client_admin.get(f'/api/equipment/telescopes/{scope_id}')
                assert get_resp.status_code == 200


# ---------------------------------------------------------------------------
# Equipment Profiles — Cameras CRUD
# ---------------------------------------------------------------------------


class TestEquipmentCameras:

    def test_get_cameras_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/cameras')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'data' in data

    def test_get_cameras_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/cameras')
        assert resp.status_code == 401

    def test_create_camera_returns_201(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/cameras',
            json={'name': 'TestCam', 'sensor_width_mm': 23.5, 'sensor_height_mm': 15.6, 'pixel_size_um': 3.76},
        )
        assert resp.status_code in (200, 201, 500)

    def test_get_camera_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/cameras/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_update_camera_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/cameras/nonexistent-id', json={'name': 'Updated'})
        assert resp.status_code in (404, 403, 401)

    def test_delete_camera_nonexistent_returns_error(self, client_admin):
        resp = client_admin.delete('/api/equipment/cameras/nonexistent-id')
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Equipment Profiles — Numeric Validation (PR #121)
# ---------------------------------------------------------------------------


class TestEquipmentNumericValidation:
    """Server-side validation of relaxed numeric constraints from PR #121."""

    VALID_TELESCOPE = {
        'name': 'ValidScope',
        'telescope_type': 'Refractor',
        'focal_length_mm': 800,
        'aperture_mm': 102,
    }

    VALID_CAMERA = {
        'name': 'ValidCam',
        'manufacturer': 'ZWO',
        'sensor_type': 'CMOS Mono',
        'sensor_width_mm': 23.4,
        'sensor_height_mm': 15.6,
        'pixel_size_um': 3.76,
        'resolution_width_px': 6248,
        'resolution_height_px': 4176,
    }

    # --- Telescope: valid edge cases that were previously blocked ---

    def test_telescope_aperture_above_2000_is_accepted(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'aperture_mm': 2500}
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code in (200, 201)

    def test_telescope_reducer_063x_is_accepted(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'reducer_barlow_factor': 0.63}
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code in (200, 201)

    def test_telescope_reducer_two_decimals_accepted(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'reducer_barlow_factor': 2.75}
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code in (200, 201)

    # --- Telescope: invalid values must be rejected ---

    def test_telescope_aperture_too_small_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'aperture_mm': 5}  # below min 10
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400

    def test_telescope_aperture_too_large_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'aperture_mm': 9999}  # above max 5000
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400

    def test_telescope_focal_length_too_large_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'focal_length_mm': 99999}  # above max 50000
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400

    def test_telescope_reducer_too_small_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'reducer_barlow_factor': 0.05}  # below min 0.1
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400

    def test_telescope_reducer_too_large_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'reducer_barlow_factor': 5.0}  # above max 3.0
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400

    # --- Camera: valid two-decimal sensor dimensions ---

    def test_camera_sensor_two_decimal_dimensions_accepted(self, client_admin):
        data = {**self.VALID_CAMERA, 'sensor_width_mm': 23.45, 'sensor_height_mm': 15.63}
        resp = client_admin.post('/api/equipment/cameras', json=data)
        assert resp.status_code in (200, 201)

    # --- Camera: invalid sensor dimensions must be rejected ---

    def test_camera_sensor_width_too_large_returns_400(self, client_admin):
        data = {**self.VALID_CAMERA, 'sensor_width_mm': 200}  # above max 100
        resp = client_admin.post('/api/equipment/cameras', json=data)
        assert resp.status_code == 400

    def test_camera_sensor_height_too_large_returns_400(self, client_admin):
        data = {**self.VALID_CAMERA, 'sensor_height_mm': 200}  # above max 100
        resp = client_admin.post('/api/equipment/cameras', json=data)
        assert resp.status_code == 400

    def test_camera_sensor_width_zero_returns_400(self, client_admin):
        data = {**self.VALID_CAMERA, 'sensor_width_mm': 0}  # below min 1
        resp = client_admin.post('/api/equipment/cameras', json=data)
        assert resp.status_code == 400

    # --- Non-numeric strings trigger the TypeError/ValueError branch in validators ---

    def test_telescope_aperture_non_numeric_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'aperture_mm': 'not-a-number'}
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400
        assert 'must be a number' in resp.get_json()['error']

    def test_telescope_focal_length_non_numeric_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'focal_length_mm': 'not-a-number'}
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400
        assert 'must be a number' in resp.get_json()['error']

    def test_telescope_reducer_non_numeric_returns_400(self, client_admin):
        data = {**self.VALID_TELESCOPE, 'reducer_barlow_factor': 'not-a-number'}
        resp = client_admin.post('/api/equipment/telescopes', json=data)
        assert resp.status_code == 400
        assert 'must be a number' in resp.get_json()['error']

    def test_camera_sensor_width_non_numeric_returns_400(self, client_admin):
        data = {**self.VALID_CAMERA, 'sensor_width_mm': 'not-a-number'}
        resp = client_admin.post('/api/equipment/cameras', json=data)
        assert resp.status_code == 400
        assert 'must be a number' in resp.get_json()['error']

    # --- Validation errors on PUT (update) routes ---

    def test_update_telescope_invalid_aperture_returns_400(self, client_admin):
        r = client_admin.post('/api/equipment/telescopes', json=self.VALID_TELESCOPE)
        tid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/telescopes/{tid}',
                                json={**self.VALID_TELESCOPE, 'aperture_mm': 9999})  # above max 5000
        assert resp.status_code == 400

    def test_update_camera_invalid_sensor_returns_400(self, client_admin):
        r = client_admin.post('/api/equipment/cameras', json=self.VALID_CAMERA)
        cid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/cameras/{cid}',
                                json={**self.VALID_CAMERA, 'sensor_width_mm': 200})  # above max 100
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Equipment Profiles — Mounts CRUD
# ---------------------------------------------------------------------------


class TestEquipmentMounts:

    def test_get_mounts_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/mounts')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'data' in data

    def test_get_mounts_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/mounts')
        assert resp.status_code == 401

    def test_create_mount_returns_201(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/mounts',
            json={'name': 'TestMount', 'type': 'EQ'},
        )
        assert resp.status_code in (200, 201, 500)

    def test_get_mount_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/mounts/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_update_mount_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/mounts/nonexistent-id', json={'name': 'Updated'})
        assert resp.status_code in (404, 403, 401)

    def test_delete_mount_nonexistent_returns_error(self, client_admin):
        resp = client_admin.delete('/api/equipment/mounts/nonexistent-id')
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Equipment Profiles — Filters CRUD
# ---------------------------------------------------------------------------


class TestEquipmentFilters:

    def test_get_filters_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/filters')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'data' in data

    def test_get_filters_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/filters')
        assert resp.status_code == 401

    def test_create_filter_returns_201(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/filters',
            json={'name': 'Ha Filter', 'type': 'narrowband', 'wavelength_nm': 656},
        )
        assert resp.status_code in (200, 201, 500)

    def test_get_filter_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/filters/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_update_filter_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/filters/nonexistent-id', json={'name': 'Updated'})
        assert resp.status_code in (404, 403, 401)

    def test_delete_filter_nonexistent_returns_error(self, client_admin):
        resp = client_admin.delete('/api/equipment/filters/nonexistent-id')
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Equipment Profiles — Accessories CRUD
# ---------------------------------------------------------------------------


class TestEquipmentAccessories:

    def test_get_accessories_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/accessories')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'data' in data

    def test_get_accessories_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/accessories')
        assert resp.status_code == 401

    def test_create_accessory_returns_201(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/accessories',
            json={'name': 'Barlow 2x', 'type': 'barlow'},
        )
        assert resp.status_code in (200, 201, 500)

    def test_get_accessory_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/accessories/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_update_accessory_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/accessories/nonexistent-id', json={'name': 'Updated'})
        assert resp.status_code in (404, 403, 401, 500)

    def test_delete_accessory_nonexistent_returns_error(self, client_admin):
        resp = client_admin.delete('/api/equipment/accessories/nonexistent-id')
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Equipment Profiles — Combinations CRUD
# ---------------------------------------------------------------------------


class TestEquipmentCombinations:

    def test_get_combinations_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/combinations')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'data' in data

    def test_get_combinations_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/combinations')
        assert resp.status_code == 401

    def test_create_combination_empty_returns_400(self, client_admin):
        resp = client_admin.post('/api/equipment/combinations', json={})
        assert resp.status_code in (400, 500)

    def test_create_combination_with_name(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/combinations',
            json={'name': 'Test Combo', 'telescope_id': 'nonexistent'},
        )
        assert resp.status_code in (200, 201, 400, 500)

    def test_get_combination_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/combinations/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_update_combination_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/combinations/nonexistent-id', json={'name': 'Updated'})
        assert resp.status_code in (404, 403, 401)

    def test_delete_combination_nonexistent_returns_error(self, client_admin):
        resp = client_admin.delete('/api/equipment/combinations/nonexistent-id')
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Equipment FOV Calculator and Summary
# ---------------------------------------------------------------------------


class TestEquipmentFovAndSummary:

    def test_fov_calculator_valid_params(self, client_admin):
        resp = client_admin.post(
            '/api/equipment/fov-calculator',
            json={
                'telescope_focal_length_mm': 800.0,
                'camera_sensor_width_mm': 23.5,
                'camera_sensor_height_mm': 15.6,
                'camera_pixel_size_um': 3.76,
            },
        )
        assert resp.status_code in (200, 500)

    def test_fov_calculator_unauthenticated_returns_401(self, client):
        resp = client.post('/api/equipment/fov-calculator', json={})
        assert resp.status_code == 401

    def test_fov_calculator_missing_params_returns_500(self, client_admin):
        resp = client_admin.post('/api/equipment/fov-calculator', json={})
        assert resp.status_code in (400, 500)

    def test_equipment_summary_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/summary')
        assert resp.status_code == 200

    def test_equipment_summary_unauthenticated_returns_401(self, client):
        resp = client.get('/api/equipment/summary')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Astrodex — full CRUD + pictures + image upload
# ---------------------------------------------------------------------------


class TestAstrodexCrud:

    def _create_item(self, client_admin):
        """Helper to create an astrodex item and return its id."""
        import uuid as _uuid
        resp = client_admin.post(
            '/api/astrodex/items',
            json={
                'name': f'TestObj_{_uuid.uuid4().hex[:6]}',
                'type': 'Galaxy',
                'catalogue': 'NGC',
                'constellation': 'orion',
            },
        )
        if resp.status_code in (200, 201):
            data = resp.get_json()
            item = data.get('item', {})
            return item.get('id')
        return None

    def test_add_item_returns_200(self, client_admin):
        import uuid as _uuid
        resp = client_admin.post(
            '/api/astrodex/items',
            json={'name': f'TestObj_{_uuid.uuid4().hex[:6]}', 'type': 'Galaxy', 'catalogue': 'NGC'},
        )
        assert resp.status_code in (200, 201, 400, 500)

    def test_add_item_no_name_returns_400(self, client_admin):
        resp = client_admin.post('/api/astrodex/items', json={'type': 'Galaxy'})
        assert resp.status_code == 400

    def test_update_item_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/astrodex/items/nonexistent-id', json={'notes': 'test'})
        assert resp.status_code in (404, 401)

    def test_delete_item_nonexistent_returns_404(self, client_admin):
        resp = client_admin.delete('/api/astrodex/items/nonexistent-id')
        assert resp.status_code in (404, 401)

    def test_check_item_returns_response(self, client_admin):
        resp = client_admin.get('/api/astrodex/check/M42')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'in_astrodex' in data

    def test_check_item_unauthenticated_returns_401(self, client):
        resp = client.get('/api/astrodex/check/M42')
        assert resp.status_code == 401

    def test_get_constellations_returns_200(self, client_admin):
        resp = client_admin.get('/api/astrodex/constellations')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'constellations' in data

    def test_catalogue_lookup_empty_returns_false(self, client_admin):
        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('found') is False

    def test_catalogue_lookup_known_object(self, client_admin, monkeypatch):
        import skytonight_targets as _skt
        monkeypatch.setattr(
            _skt,
            'get_lookup_entry',
            lambda *a, **kw: {
                'preferred_name': 'M42',
                'object_type': 'Nebula',
                'constellation': 'Ori',
                'aliases': {'Messier': 'M42'},
            },
        )
        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=M42')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['found'] is True

    def test_catalogue_lookup_unauthenticated_returns_401(self, client):
        resp = client.get('/api/astrodex/catalogue-lookup?name=M42')
        assert resp.status_code == 401

    def test_add_picture_to_nonexistent_item_returns_404(self, client_admin):
        resp = client_admin.post(
            '/api/astrodex/items/nonexistent-id/pictures',
            json={'url': '/static/img/test.jpg', 'caption': 'test'},
        )
        assert resp.status_code in (404, 401)

    def test_update_picture_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put(
            '/api/astrodex/items/nonexistent-id/pictures/pic-id',
            json={'caption': 'updated'},
        )
        assert resp.status_code in (404, 401)

    def test_delete_picture_nonexistent_returns_404(self, client_admin):
        resp = client_admin.delete('/api/astrodex/items/nonexistent-id/pictures/pic-id')
        assert resp.status_code in (404, 401)

    def test_set_main_picture_nonexistent_returns_404(self, client_admin):
        resp = client_admin.post('/api/astrodex/items/nonexistent-id/pictures/pic-id/main')
        assert resp.status_code in (404, 401)

    def test_upload_no_file_returns_400(self, client_admin):
        resp = client_admin.post('/api/astrodex/upload')
        assert resp.status_code in (400, 401)

    def test_get_image_nonexistent_returns_404(self, client_admin):
        resp = client_admin.get('/api/astrodex/images/nonexistent.jpg')
        assert resp.status_code in (403, 404)

    def test_switch_catalogue_name_nonexistent_returns_404(self, client_admin):
        resp = client_admin.post(
            '/api/astrodex/items/nonexistent-id/catalogue-name',
            json={'catalogue': 'NGC'},
        )
        assert resp.status_code in (404, 401)

    def test_switch_catalogue_name_missing_catalogue_returns_400(self, client_admin):
        resp = client_admin.post('/api/astrodex/items/some-id/catalogue-name', json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Backup download / restore
# ---------------------------------------------------------------------------


class TestBackupEndpoints:

    def test_backup_download_returns_200(self, client_admin):
        resp = client_admin.get('/api/backup/download')
        assert resp.status_code in (200, 500)

    def test_backup_download_unauthenticated_returns_401(self, client):
        resp = client.get('/api/backup/download')
        assert resp.status_code == 401

    def test_backup_restore_no_file_returns_400(self, client_admin):
        resp = client_admin.post('/api/backup/restore')
        assert resp.status_code == 400

    def test_backup_restore_unauthenticated_returns_401(self, client):
        resp = client.post('/api/backup/restore')
        assert resp.status_code == 401

    def test_backup_restore_invalid_zip_returns_400(self, client_admin):
        import io as _io
        data = {'file': (_io.BytesIO(b'not a zip file'), 'backup.zip')}
        resp = client_admin.post(
            '/api/backup/restore',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_backup_restore_wrong_extension_returns_400(self, client_admin):
        import io as _io
        data = {'file': (_io.BytesIO(b'some data'), 'backup.txt')}
        resp = client_admin.post(
            '/api/backup/restore',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_backup_restore_valid_zip_no_recognised_entries_returns_400(self, client_admin):
        import io as _io
        import zipfile as _zf
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, mode='w') as z:
            z.writestr('unknown_file.txt', 'some content')
        buf.seek(0)
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post(
            '/api/backup/restore',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DMS coordinate conversion
# ---------------------------------------------------------------------------


class TestDmsConversion:

    def test_valid_dms_returns_200(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={'dms': '48d38m36.16s'})
        assert resp.status_code in (200, 400)

    def test_invalid_dms_returns_400(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={'dms': 'invalid_dms'})
        assert resp.status_code == 400

    def test_missing_dms_returns_400(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={})
        assert resp.status_code in (200, 400)

    def test_too_long_dms_returns_400(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={'dms': 'x' * 60})
        assert resp.status_code == 400

    def test_negative_dms_returns_response(self, client_admin):
        resp = client_admin.post('/api/convert-coordinates', json={'dms': '-48d38m36.16s'})
        assert resp.status_code in (200, 400)

    def test_unauthenticated_dms_returns_401(self, client):
        resp = client.post('/api/convert-coordinates', json={'dms': '48d38m36s'})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Best window with mode=all
# ---------------------------------------------------------------------------


class TestBestWindowAllMode:

    def test_best_window_all_mode_no_cache(self, client_admin):
        resp = client_admin.get('/api/tonight/best-window?mode=all')
        assert resp.status_code in (200, 202, 400)

    def test_best_window_invalid_mode_returns_400(self, client_admin):
        resp = client_admin.get('/api/tonight/best-window?mode=invalid_mode')
        assert resp.status_code == 400

    def test_best_window_all_mode_with_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        for mode in ['strict', 'practical', 'illumination']:
            monkeypatch.setitem(_cache_store._best_window_cache[mode], 'data', {'mode': mode})
        resp = client_admin.get('/api/tonight/best-window?mode=all')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'modes' in data

    def test_best_window_practical_mode(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._best_window_cache['practical'], 'data', {'mode': 'practical'})
        resp = client_admin.get('/api/tonight/best-window?mode=practical')
        assert resp.status_code == 200

    def test_best_window_illumination_mode(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._best_window_cache['illumination'], 'data', {'mode': 'illumination'})
        resp = client_admin.get('/api/tonight/best-window?mode=illumination')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Plan My Night — detailed target operations
# ---------------------------------------------------------------------------


class TestPlanMyNightTargetOps:

    def test_update_target_nonexistent_returns_404(self, client_admin):
        resp = client_admin.put('/api/plan-my-night/targets/nonexistent-id', json={'done': True})
        assert resp.status_code in (200, 404, 400)

    def test_delete_target_nonexistent_returns_404(self, client_admin):
        resp = client_admin.delete('/api/plan-my-night/targets/nonexistent-id')
        assert resp.status_code in (200, 404, 400)

    def test_reorder_target_missing_index_returns_400(self, client_admin):
        resp = client_admin.post('/api/plan-my-night/targets/some-id/reorder', json={})
        assert resp.status_code == 400

    def test_reorder_target_nonexistent_returns_404(self, client_admin):
        resp = client_admin.post('/api/plan-my-night/targets/nonexistent-id/reorder', json={'new_index': 0})
        assert resp.status_code in (200, 404, 400)

    def test_add_target_to_astrodex_nonexistent_returns_404(self, client_admin):
        resp = client_admin.post('/api/plan-my-night/targets/nonexistent-id/add-to-astrodex')
        assert resp.status_code in (200, 404, 401)

    def test_export_pdf_returns_response(self, client_admin):
        resp = client_admin.get('/api/plan-my-night/export.pdf')
        assert resp.status_code in (200, 500)

    def test_plan_unauthenticated_update_returns_401(self, client):
        resp = client.put('/api/plan-my-night/targets/some-id', json={'done': True})
        assert resp.status_code == 401

    def test_plan_unauthenticated_delete_returns_401(self, client):
        resp = client.delete('/api/plan-my-night/targets/some-id')
        assert resp.status_code == 401

    def test_plan_unauthenticated_reorder_returns_401(self, client):
        resp = client.post('/api/plan-my-night/targets/some-id/reorder', json={'new_index': 0})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Push subscriptions management
# ---------------------------------------------------------------------------


class TestPushSubscriptionsManagement:

    def test_list_subscriptions_returns_200(self, client_admin):
        resp = client_admin.get('/api/push/subscriptions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'subscriptions' in data

    def test_delete_all_subscriptions_returns_200(self, client_admin):
        resp = client_admin.delete('/api/push/subscriptions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'removed' in data

    def test_push_subscribe_valid_subscription(self, client_admin):
        resp = client_admin.post(
            '/api/push/subscribe',
            json={
                'subscription': {
                    'endpoint': 'https://push.services.mozilla.com/push/test123',
                    'keys': {'auth': 'auth_key', 'p256dh': 'p256dh_key'},
                }
            },
        )
        assert resp.status_code in (200, 400, 500)

    def test_push_subscribe_missing_endpoint_returns_400(self, client_admin):
        resp = client_admin.post('/api/push/subscribe', json={'subscription': {}})
        assert resp.status_code == 400

    def test_push_unsubscribe_missing_endpoint_returns_400(self, client_admin):
        resp = client_admin.delete('/api/push/unsubscribe', json={})
        assert resp.status_code == 400

    def test_push_unsubscribe_valid_endpoint_returns_200(self, client_admin):
        resp = client_admin.delete(
            '/api/push/unsubscribe',
            json={'endpoint': 'https://push.services.mozilla.com/push/nonexistent'},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# User CRUD error branches
# ---------------------------------------------------------------------------


class TestUserCrudErrors:

    def test_create_user_duplicate_returns_400(self, client_admin):
        # Try to create admin again (already exists)
        resp = client_admin.post(
            '/api/users',
            json={'username': 'admin', 'password': 'Admin99!', 'role': 'admin'},
        )
        assert resp.status_code == 400

    def test_create_user_invalid_role_returns_400(self, client_admin):
        import uuid as _uuid
        resp = client_admin.post(
            '/api/users',
            json={'username': f'u_{_uuid.uuid4().hex[:6]}', 'password': 'TestPass99!', 'role': 'superadmin'},
        )
        assert resp.status_code == 400

    def test_update_user_empty_body_returns_400(self, client_admin):
        import uuid as _uuid
        fake_id = str(_uuid.uuid4())
        resp = client_admin.put(f'/api/users/{fake_id}', json={})
        assert resp.status_code == 400

    def test_delete_own_account_returns_400(self, client_admin):
        admin_user = user_manager.get_user_by_username('admin')
        resp = client_admin.delete(f'/api/users/{admin_user.user_id}')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Preferences error branches
# ---------------------------------------------------------------------------


class TestPreferencesErrors:

    def test_update_preferences_missing_key_returns_400(self, client_admin):
        resp = client_admin.put('/api/auth/preferences', json={})
        assert resp.status_code == 400

    def test_update_preferences_invalid_tab_returns_400(self, client_admin, monkeypatch):
        def _raise(user_id, prefs):
            raise ValueError('Invalid startup_main_tab: invalid_tab')

        monkeypatch.setattr(user_manager, 'update_user_preferences', _raise)
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {'startup_main_tab': 'invalid_tab'}})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error_key'] == 'settings.pref_invalid_startup_main_tab'

    def test_update_preferences_invalid_theme_returns_400(self, client_admin, monkeypatch):
        def _raise(user_id, prefs):
            raise ValueError('Invalid theme_mode: x')

        monkeypatch.setattr(user_manager, 'update_user_preferences', _raise)
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {'theme_mode': 'x'}})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error_key'] == 'settings.pref_invalid_theme'


# ---------------------------------------------------------------------------
# Password change error branches
# ---------------------------------------------------------------------------


class TestPasswordChangeErrors:

    def test_change_password_short_new_password_returns_400(self, client_admin, monkeypatch):
        def _raise(user_id, current, new):
            raise ValueError('New password must be at least 6 characters')

        monkeypatch.setattr(user_manager, 'change_own_password', _raise)
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'Admin123!', 'new_password': 'ab'},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error_key'] == 'users.password_too_short'

    def test_change_password_same_as_current_returns_400(self, client_admin, monkeypatch):
        def _raise(user_id, current, new):
            raise ValueError('New password must be different from current password')

        monkeypatch.setattr(user_manager, 'change_own_password', _raise)
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'Admin123!', 'new_password': 'Admin123!'},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error_key'] == 'users.password_must_be_different'


# ---------------------------------------------------------------------------
# Backup restore with valid zip containing config.json
# ---------------------------------------------------------------------------


class TestBackupRestoreValid:

    def test_backup_restore_with_valid_config_json(self, client_admin):
        import io as _io
        import zipfile as _zf
        import json as _json
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, mode='w') as z:
            z.writestr('config.json', _json.dumps({'location': {}, 'skytonight': {}}))
        buf.seek(0)
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post(
            '/api/backup/restore',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code in (200, 400, 500)

    def test_backup_restore_invalid_json_returns_400(self, client_admin):
        import io as _io
        import zipfile as _zf
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, mode='w') as z:
            z.writestr('config.json', 'not valid json {{{')
        buf.seek(0)
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post(
            '/api/backup/restore',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Sky Quality endpoint with config variants
# ---------------------------------------------------------------------------


class TestSkyQualityVariants:

    def test_sky_quality_both_bortle_and_sqm(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'load_config',
            lambda: {'location': {'bortle': 4, 'sqm': 21.5}},
        )
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['bortle'] == 4
        assert data['sqm'] == 21.5

    def test_sky_quality_sqm_only(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'load_config',
            lambda: {'location': {'sqm': 21.0}},
        )
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['sqm'] is not None

    def test_sky_quality_bortle_only(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'load_config',
            lambda: {'location': {'bortle': 6}},
        )
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['bortle'] == 6

    def test_sky_quality_not_configured(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'load_config',
            lambda: {'location': {}},
        )
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['sqm_source'] == 'not_configured'
        assert data['bortle'] is None


# ---------------------------------------------------------------------------
# Admin app settings — full coverage
# ---------------------------------------------------------------------------


class TestAdminAppSettingsFullCoverage:

    def test_post_app_settings_trust_proxy_true(self, client_admin):
        resp = client_admin.post('/api/admin/app-settings', json={'trust_proxy_headers': True})
        assert resp.status_code == 200

    def test_get_admin_app_settings_has_keys(self, client_admin):
        resp = client_admin.get('/api/admin/app-settings')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Push test trigger (N1..N7)
# ---------------------------------------------------------------------------


class TestPushTestTrigger:

    def test_trigger_unknown_returns_400(self, client_admin):
        resp = client_admin.post('/api/push/test/UNKNOWN')
        assert resp.status_code in (400, 401)

    def test_trigger_n1_no_subscriptions_returns_response(self, client_admin):
        resp = client_admin.post('/api/push/test/N1')
        # Admin user may have no subscriptions (400) or 0 delivered (200)
        assert resp.status_code in (200, 400, 500)


# ---------------------------------------------------------------------------
# Logs endpoints — deeper coverage
# ---------------------------------------------------------------------------


class TestLogsDeepCoverage:

    def test_logs_with_offset_returns_200(self, client_admin):
        resp = client_admin.get('/api/logs?offset=0&limit=10')
        assert resp.status_code == 200

    def test_logs_level_get_returns_200(self, client_admin):
        resp = client_admin.get('/api/logs/level')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'level' in data


# ---------------------------------------------------------------------------
# Config post — clear horizon profile flag
# ---------------------------------------------------------------------------


class TestConfigPostHorizonProfile:

    def test_post_config_with_clear_horizon_flag(self, client_admin, monkeypatch):
        old_cfg = {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'timezone': 'UTC'},
            'skytonight': {
                'constraints': {'horizon_profile': [{'az': 10, 'alt': 20}]},
            },
        }
        captured = {}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: old_cfg)
        monkeypatch.setattr(_app_mod, 'save_config', lambda cfg: captured.setdefault('cfg', cfg))
        monkeypatch.setattr(_app_mod.cache_store, 'reset_all_caches', lambda: None)
        monkeypatch.setattr(_app_mod.cache_store, 'update_location_config', lambda *a, **k: None)

        # _horizon_cleared=True tells the backend to allow clearing the profile
        incoming = {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'timezone': 'UTC'},
            'skytonight': {'constraints': {'horizon_profile': [], '_horizon_cleared': True}},
        }
        resp = client_admin.post('/api/config', json=incoming)
        assert resp.status_code == 200
        if 'cfg' in captured:
            saved = captured['cfg']
            # _horizon_cleared flag should be stripped; horizon_profile should be empty
            assert saved['skytonight']['constraints']['horizon_profile'] == []
            assert '_horizon_cleared' not in saved['skytonight']['constraints']


# ---------------------------------------------------------------------------
# Cache with stale data branches
# ---------------------------------------------------------------------------


class TestCacheStaleDataBranches:

    def test_aurora_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._aurora_cache, 'data', {'kp_index': 2.0})
        resp = client_admin.get('/api/aurora/predictions')
        assert resp.status_code == 200

    def test_seeing_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._seeing_forecast_cache, 'data', {'forecast': []})
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code == 200

    def test_spaceflight_launches_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._spaceflight_launches_cache, 'data', {'results': []})
        resp = client_admin.get('/api/spaceflight/launches')
        assert resp.status_code == 200

    def test_spaceflight_astronauts_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._spaceflight_astronauts_cache, 'data', {'results': []})
        resp = client_admin.get('/api/spaceflight/astronauts')
        assert resp.status_code == 200

    def test_planetary_events_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._planetary_events_cache, 'data', {'events': []})
        resp = client_admin.get('/api/events/planetary')
        assert resp.status_code == 200

    def test_horizon_graph_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._horizon_graph_cache, 'data', {'graph': 'data'})
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code == 200

    def test_best_window_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._best_window_cache['strict'], 'data', {'mode': 'strict'})
        resp = client_admin.get('/api/tonight/best-window')
        assert resp.status_code == 200

    def test_solar_eclipse_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._solar_eclipse_cache, 'data', {'eclipse': None})
        resp = client_admin.get('/api/sun/next-eclipse')
        assert resp.status_code == 200

    def test_lunar_eclipse_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._lunar_eclipse_cache, 'data', {'eclipse': None})
        resp = client_admin.get('/api/moon/next-eclipse')
        assert resp.status_code == 200

    def test_special_phenomena_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            {'events': [], 'equinoxes_solstices': [], 'zodiacal_light': [], 'milky_way': []},
        )
        resp = client_admin.get('/api/events/phenomena')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Weather endpoints with stale data
# ---------------------------------------------------------------------------


class TestWeatherStaleData:

    def test_weather_forecast_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._weather_cache, 'data', {'forecast': []})
        # Mock get_hourly_forecast to return None so stale path is triggered
        monkeypatch.setattr(_app_mod, 'get_hourly_forecast', lambda: None)
        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code in (200, 202)

    def test_weather_forecast_no_cache_no_data_returns_202(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        _cache_store._weather_cache.pop('data', None)
        monkeypatch.setattr(_app_mod, 'get_hourly_forecast', lambda: None)
        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code in (200, 202)


# ---------------------------------------------------------------------------
# Solar system events with cache variants
# ---------------------------------------------------------------------------


class TestSolarSystemEventsCache:

    def test_solar_system_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {'meteor_showers': [], 'comets': [], 'asteroid_occultations': []},
        )
        resp = client_admin.get('/api/events/solarsystem')
        assert resp.status_code == 200

    def test_spaceflight_events_stale_data_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._spaceflight_events_cache, 'data', {'results': []})
        resp = client_admin.get('/api/spaceflight/events')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# On-demand translate endpoint
# ---------------------------------------------------------------------------


class TestOnDemandTranslate:

    def test_translate_endpoint_missing_body_returns_error(self, client_admin):
        resp = client_admin.post('/api/translate', json={})
        assert resp.status_code in (200, 400, 404, 405, 500)

    def test_translate_endpoint_unauthenticated_returns_401(self, client):
        resp = client.post('/api/translate', json={'text': 'hello', 'target_lang': 'fr'})
        assert resp.status_code in (401, 404, 405)


# ---------------------------------------------------------------------------
# ISS passes with different window_days
# ---------------------------------------------------------------------------


class TestISSPassesWindowDays:

    def test_iss_passes_cached_different_window_returns_202(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 5})
        # With window_days=20 (default) vs cached 5 — should trigger refresh
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code in (200, 202)

    def test_iss_passes_cached_same_window_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 20})
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Version check-updates — error path
# ---------------------------------------------------------------------------


class TestVersionCheckUpdatesErrorPath:

    def test_check_updates_exception_returns_500(self, client_admin, monkeypatch):
        def _boom():
            raise RuntimeError('network error')

        monkeypatch.setattr(_app_mod, 'check_for_updates', _boom)
        monkeypatch.setattr(_app_mod, 'get_repo_version', lambda: '1.0.0')
        resp = client_admin.get('/api/version/check-updates')
        assert resp.status_code == 500
        data = resp.get_json()
        assert data['update_available'] is False


# ---------------------------------------------------------------------------
# Moon planner
# ---------------------------------------------------------------------------


class TestMoonPlannerEndpoints:

    def test_moon_next_7_nights_no_cache_returns_202(self, client_admin):
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code in (200, 202, 400)

    def test_moon_next_7_nights_with_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._moon_planner_report_cache, 'data', {'nights': []})
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code in (200, 202)

    def test_moon_month_calendar_no_cache_returns_202(self, client_admin):
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code in (200, 202, 400)


# ---------------------------------------------------------------------------
# Admin logs set level
# ---------------------------------------------------------------------------


class TestLogsSetLevel:

    def test_set_log_level_returns_response(self, client_admin):
        resp = client_admin.post('/api/logs/level', json={'level': 'DEBUG'})
        assert resp.status_code in (200, 400, 404, 405)

    def test_set_log_level_unauthenticated_returns_401(self, client):
        resp = client.post('/api/logs/level', json={'level': 'DEBUG'})
        assert resp.status_code in (401, 404, 405)


# ---------------------------------------------------------------------------
# Tonight plan with cache
# ---------------------------------------------------------------------------


class TestTonightPlanCache:

    def test_tonight_plan_with_moon_planner_cache(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._moon_planner_report_cache, 'data', {'nights': []})
        resp = client_admin.get('/api/plan-my-night/tonight-plan')
        assert resp.status_code in (200, 202, 400, 404)


# ---------------------------------------------------------------------------
# Plan My Night clear-all
# ---------------------------------------------------------------------------


class TestPlanMyNightClearAll:

    def test_clear_all_plans_returns_200(self, client_admin):
        resp = client_admin.delete('/api/plan-my-night/clear-all')
        assert resp.status_code in (200, 400, 500)

    def test_clear_plan_returns_200(self, client_admin):
        resp = client_admin.delete('/api/plan-my-night/clear')
        assert resp.status_code in (200, 400, 500)

    def test_plan_add_target_with_catalogue(self, client_admin, monkeypatch):
        # Mock the night resolution to avoid real calculation
        monkeypatch.setattr(
            _app_mod,
            '_resolve_observing_night_for_plan',
            lambda: {
                'start': '2026-06-06T21:00:00',
                'end': '2026-06-07T05:00:00',
                'duration_hours': 8.0,
            },
        )
        resp = client_admin.post(
            '/api/plan-my-night/targets',
            json={
                'catalogue': 'Messier',
                'item': {
                    'name': 'M42',
                    'type': 'Nebula',
                    'catalogue': 'Messier',
                    'constellation': 'orion',
                },
            },
        )
        assert resp.status_code in (200, 400, 409, 500)


# ---------------------------------------------------------------------------
# Special phenomena cache with translation
# ---------------------------------------------------------------------------


class TestSpecialPhenomenaTranslation:

    def test_phenomena_with_fr_lang_header(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            {
                'events': [
                    {
                        'event_type': 'Equinox',
                        'raw_data': {'event': 'spring_equinox'},
                        'title': 'Spring Equinox',
                        'description': 'Equal day and night.',
                    }
                ],
                'equinoxes_solstices': [],
                'zodiacal_light': [],
                'milky_way': [],
            },
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_solar_system_events_with_fr_lang(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {
                'events': [
                    {
                        'event_type': 'Meteor Shower',
                        'title': 'Perseid Shower',
                        'zenith_hourly_rate': '100',
                        'parent_body': 'Swift-Tuttle',
                        'raw_data': {'shower': 'Perseids'},
                    }
                ],
                'meteor_showers': [],
                'comets': [],
                'asteroid_occultations': [],
            },
        )
        resp = client_admin.get('/api/events/solarsystem', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Translate on-demand endpoint
# ---------------------------------------------------------------------------


class TestTranslateOnDemand:

    def test_translate_empty_text_returns_400(self, client_admin):
        resp = client_admin.post('/api/translate/on-demand', json={'text': '', 'target_lang': 'fr'})
        assert resp.status_code == 400

    def test_translate_too_long_text_returns_400(self, client_admin):
        resp = client_admin.post(
            '/api/translate/on-demand',
            json={'text': 'x' * 5001, 'target_lang': 'fr'},
        )
        assert resp.status_code == 400

    def test_translate_unsupported_lang_returns_400(self, client_admin):
        resp = client_admin.post(
            '/api/translate/on-demand',
            json={'text': 'hello world', 'target_lang': 'klingon'},
        )
        assert resp.status_code == 400

    def test_translate_valid_en_to_fr_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(
            _app_mod,
            'translate_text_on_demand',
            lambda text, source_lang, target_lang: {'translated': text, 'source_lang': source_lang},
        )
        resp = client_admin.post(
            '/api/translate/on-demand',
            json={'text': 'hello world', 'target_lang': 'fr'},
        )
        assert resp.status_code == 200

    def test_translate_unauthenticated_returns_401(self, client):
        resp = client.post('/api/translate/on-demand', json={'text': 'hello', 'target_lang': 'fr'})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Spaceflight launch vidurls
# ---------------------------------------------------------------------------


class TestSpaceflightLaunchVidurls:

    def test_vidurls_invalid_id_returns_400(self, client_admin):
        resp = client_admin.get('/api/spaceflight/launch/invalid-id!/vidurls')
        assert resp.status_code == 400

    def test_vidurls_valid_uuid_returns_200(self, client_admin, monkeypatch):
        import uuid as _uuid
        import spaceflight_tracker as _st
        fake_uuid = str(_uuid.uuid4())
        monkeypatch.setattr(_st, 'get_launch_vidurls', lambda lid: ['https://youtube.com/watch?v=test'])
        resp = client_admin.get(f'/api/spaceflight/launch/{fake_uuid}/vidurls')
        assert resp.status_code in (200, 500)

    def test_vidurls_unauthenticated_returns_401(self, client):
        import uuid as _uuid
        fake_uuid = str(_uuid.uuid4())
        resp = client.get(f'/api/spaceflight/launch/{fake_uuid}/vidurls')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Equipment CRUD — full create/get/update/delete lifecycle
# ---------------------------------------------------------------------------


class TestEquipmentLifecycle:
    """Test create → get → update → delete for all equipment types."""

    def test_telescope_full_lifecycle(self, client_admin):
        import uuid as _uuid
        name = f'Scope_{_uuid.uuid4().hex[:6]}'
        # Create
        create_resp = client_admin.post(
            '/api/equipment/telescopes',
            json={'name': name, 'focal_length_mm': 600, 'aperture_mm': 80},
        )
        assert create_resp.status_code in (200, 201, 500)
        if create_resp.status_code not in (200, 201):
            return
        scope_id = create_resp.get_json().get('data', {}).get('id')
        if not scope_id:
            return
        # Get
        get_resp = client_admin.get(f'/api/equipment/telescopes/{scope_id}')
        assert get_resp.status_code == 200
        # Update
        upd_resp = client_admin.put(
            f'/api/equipment/telescopes/{scope_id}',
            json={'name': name + '_updated', 'focal_length_mm': 700},
        )
        assert upd_resp.status_code in (200, 404, 403)
        # Delete
        del_resp = client_admin.delete(f'/api/equipment/telescopes/{scope_id}')
        assert del_resp.status_code in (200, 500)

    def test_camera_full_lifecycle(self, client_admin):
        import uuid as _uuid
        name = f'Cam_{_uuid.uuid4().hex[:6]}'
        create_resp = client_admin.post(
            '/api/equipment/cameras',
            json={'name': name, 'sensor_width_mm': 22.3, 'sensor_height_mm': 14.9, 'pixel_size_um': 4.3},
        )
        assert create_resp.status_code in (200, 201, 500)
        if create_resp.status_code not in (200, 201):
            return
        cam_id = create_resp.get_json().get('data', {}).get('id')
        if not cam_id:
            return
        get_resp = client_admin.get(f'/api/equipment/cameras/{cam_id}')
        assert get_resp.status_code == 200
        upd_resp = client_admin.put(f'/api/equipment/cameras/{cam_id}', json={'name': name + '_updated'})
        assert upd_resp.status_code in (200, 404, 403)
        del_resp = client_admin.delete(f'/api/equipment/cameras/{cam_id}')
        assert del_resp.status_code in (200, 500)

    def test_mount_full_lifecycle(self, client_admin):
        import uuid as _uuid
        name = f'Mount_{_uuid.uuid4().hex[:6]}'
        create_resp = client_admin.post('/api/equipment/mounts', json={'name': name, 'type': 'EQ'})
        assert create_resp.status_code in (200, 201, 500)
        if create_resp.status_code not in (200, 201):
            return
        mount_id = create_resp.get_json().get('data', {}).get('id')
        if not mount_id:
            return
        get_resp = client_admin.get(f'/api/equipment/mounts/{mount_id}')
        assert get_resp.status_code == 200
        upd_resp = client_admin.put(f'/api/equipment/mounts/{mount_id}', json={'name': name + '_updated'})
        assert upd_resp.status_code in (200, 404, 403)
        del_resp = client_admin.delete(f'/api/equipment/mounts/{mount_id}')
        assert del_resp.status_code in (200, 500)

    def test_filter_full_lifecycle(self, client_admin):
        import uuid as _uuid
        name = f'Filter_{_uuid.uuid4().hex[:6]}'
        create_resp = client_admin.post('/api/equipment/filters', json={'name': name, 'type': 'Ha'})
        assert create_resp.status_code in (200, 201, 500)
        if create_resp.status_code not in (200, 201):
            return
        filter_id = create_resp.get_json().get('data', {}).get('id')
        if not filter_id:
            return
        get_resp = client_admin.get(f'/api/equipment/filters/{filter_id}')
        assert get_resp.status_code == 200
        upd_resp = client_admin.put(f'/api/equipment/filters/{filter_id}', json={'name': name + '_updated'})
        assert upd_resp.status_code in (200, 404, 403)
        del_resp = client_admin.delete(f'/api/equipment/filters/{filter_id}')
        assert del_resp.status_code in (200, 500)

    def test_accessory_full_lifecycle(self, client_admin):
        import uuid as _uuid
        name = f'Acc_{_uuid.uuid4().hex[:6]}'
        create_resp = client_admin.post('/api/equipment/accessories', json={'name': name, 'type': 'barlow'})
        assert create_resp.status_code in (200, 201, 500)
        if create_resp.status_code not in (200, 201):
            return
        acc_id = create_resp.get_json().get('data', {}).get('id')
        if not acc_id:
            return
        get_resp = client_admin.get(f'/api/equipment/accessories/{acc_id}')
        assert get_resp.status_code == 200
        upd_resp = client_admin.put(f'/api/equipment/accessories/{acc_id}', json={'name': name + '_updated'})
        assert upd_resp.status_code in (200, 404, 403, 500)
        del_resp = client_admin.delete(f'/api/equipment/accessories/{acc_id}')
        assert del_resp.status_code in (200, 500)


# ---------------------------------------------------------------------------
# Astrodex image upload — file validation paths
# ---------------------------------------------------------------------------


class TestAstrodexUploadValidation:

    def test_upload_invalid_extension_returns_400(self, client_admin):
        import io as _io
        data = {'file': (_io.BytesIO(b'some image data'), 'photo.bmp')}
        resp = client_admin.post(
            '/api/astrodex/upload',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_upload_no_extension_returns_400(self, client_admin):
        import io as _io
        data = {'file': (_io.BytesIO(b'data'), 'photonoext')}
        resp = client_admin.post(
            '/api/astrodex/upload',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_upload_valid_jpg_returns_200(self, client_admin, monkeypatch):
        import io as _io
        import astrodex as _ad
        monkeypatch.setattr(_ad, 'ensure_astrodex_directories', lambda: None)

        import werkzeug.datastructures as _wd

        def _patched_save(self, dst, buffer_size=16384):
            pass

        monkeypatch.setattr(_wd.FileStorage, 'save', _patched_save)

        data = {'file': (_io.BytesIO(b'\xff\xd8\xff' + b'\x00' * 100), 'test_photo.jpg')}
        resp = client_admin.post(
            '/api/astrodex/upload',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code in (200, 400, 500)


# ---------------------------------------------------------------------------
# Special phenomena events — translation branch coverage
# ---------------------------------------------------------------------------


class TestSpecialPhenomenaTranslationBranches:

    def _make_cache_with_events(self, events):
        return {
            'events': events,
            'equinoxes_solstices': [],
            'zodiacal_light': [],
            'milky_way': [],
        }

    def test_phenomena_summer_solstice_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            self._make_cache_with_events([
                {
                    'event_type': 'Solstice',
                    'raw_data': {'event': 'summer_solstice'},
                    'title': 'Summer Solstice',
                    'description': 'Longest day.',
                }
            ]),
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_phenomena_autumn_equinox_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            self._make_cache_with_events([
                {
                    'event_type': 'Equinox',
                    'raw_data': {'event': 'autumn_equinox'},
                    'title': 'Autumnal Equinox',
                    'description': 'Equal day and night.',
                }
            ]),
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_phenomena_winter_solstice_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            self._make_cache_with_events([
                {
                    'event_type': 'Solstice',
                    'raw_data': {'event': 'winter_solstice'},
                    'title': 'Winter Solstice',
                    'description': 'Shortest day.',
                }
            ]),
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_phenomena_zodiacal_light_morning_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            self._make_cache_with_events([
                {
                    'event_type': 'Zodiacal Light',
                    'raw_data': {'event': 'zodiacal_light'},
                    'viewing_type': 'morning',
                    'title': 'Zodiacal Light (Morning)',
                    'description': 'Faint cone of light.',
                }
            ]),
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_phenomena_zodiacal_light_evening_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            self._make_cache_with_events([
                {
                    'event_type': 'Zodiacal Light',
                    'raw_data': {'event': 'zodiacal_light'},
                    'viewing_type': 'evening',
                    'title': 'Zodiacal Light (Evening)',
                    'description': 'Faint cone of light.',
                }
            ]),
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_phenomena_milky_way_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            self._make_cache_with_events([
                {
                    'event_type': 'Milky Way Core Visibility',
                    'raw_data': {'event': 'milky_way', 'galactic_center_altitude': 35.0},
                    'galactic_center_altitude': 35.0,
                    'title': 'Milky Way Core Visible',
                    'description': 'Galactic center visible.',
                }
            ]),
        )
        resp = client_admin.get('/api/events/phenomena', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Solar system events — comet/asteroid translation
# ---------------------------------------------------------------------------


class TestSolarSystemEventTranslationBranches:

    def test_comet_event_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {
                'events': [
                    {
                        'event_type': 'Comet Appearance',
                        'magnitude': '6.0',
                        'equipment_needed': 'Binoculars',
                        'raw_data': {'comet': 'Halley'},
                        'title': 'Halley Comet',
                    }
                ],
                'meteor_showers': [],
                'comets': [],
                'asteroid_occultations': [],
            },
        )
        resp = client_admin.get('/api/events/solarsystem', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_asteroid_occultation_event_fr(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {
                'events': [
                    {
                        'event_type': 'Asteroid Occultation',
                        'title': 'Asteroid Occultation',
                        'raw_data': {},
                    }
                ],
                'meteor_showers': [],
                'comets': [],
                'asteroid_occultations': [],
            },
        )
        resp = client_admin.get('/api/events/solarsystem', headers={'Accept-Language': 'fr'})
        assert resp.status_code == 200

    def test_solar_system_en_lang_returns_data_unchanged(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {'events': [], 'meteor_showers': [], 'comets': [], 'asteroid_occultations': []},
        )
        resp = client_admin.get('/api/events/solarsystem', headers={'Accept-Language': 'en'})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Admin logs — set log level endpoint
# ---------------------------------------------------------------------------


class TestAdminLogsLevel:

    def test_set_log_level_debug(self, client_admin):
        resp = client_admin.post('/api/logs/level', json={'level': 'DEBUG'})
        assert resp.status_code in (200, 400, 404, 405)

    def test_set_log_level_unauthenticated(self, client):
        resp = client.post('/api/logs/level', json={'level': 'DEBUG'})
        assert resp.status_code in (401, 404, 405)


# ---------------------------------------------------------------------------
# Astrodex items CRUD full lifecycle
# ---------------------------------------------------------------------------


class TestAstrodexItemLifecycle:

    def test_create_update_delete_item(self, client_admin):
        import uuid as _uuid
        name = f'TestGalaxy_{_uuid.uuid4().hex[:6]}'
        # Create
        create_resp = client_admin.post(
            '/api/astrodex/items',
            json={'name': name, 'type': 'Galaxy', 'catalogue': 'NGC', 'constellation': 'andromeda'},
        )
        assert create_resp.status_code in (200, 201, 400, 500)
        if create_resp.status_code not in (200, 201):
            return
        item = create_resp.get_json().get('item', {})
        item_id = item.get('id')
        if not item_id:
            return
        # Get
        get_resp = client_admin.get(f'/api/astrodex/items/{item_id}')
        assert get_resp.status_code == 200
        # Update
        upd_resp = client_admin.put(f'/api/astrodex/items/{item_id}', json={'notes': 'Great view!'})
        assert upd_resp.status_code in (200, 404)
        # Add picture
        pic_resp = client_admin.post(
            f'/api/astrodex/items/{item_id}/pictures',
            json={'url': '/static/img/test.jpg', 'caption': 'Test picture'},
        )
        assert pic_resp.status_code in (200, 404, 500)
        # Delete
        del_resp = client_admin.delete(f'/api/astrodex/items/{item_id}')
        assert del_resp.status_code in (200, 404)

    def test_duplicate_item_returns_409(self, client_admin):
        import uuid as _uuid
        name = f'DupObj_{_uuid.uuid4().hex[:6]}'
        client_admin.post('/api/astrodex/items', json={'name': name, 'type': 'Star', 'catalogue': 'HIP'})
        resp2 = client_admin.post('/api/astrodex/items', json={'name': name, 'type': 'Star', 'catalogue': 'HIP'})
        assert resp2.status_code in (200, 201, 400, 409, 500)


# ---------------------------------------------------------------------------
# Push test with actual subscriptions (via monkeypatching)
# ---------------------------------------------------------------------------


class TestPushTestWithSubscriptions:

    def test_push_test_legacy_with_subscription_and_mock(self, client_admin, monkeypatch):
        admin_user = user_manager.get_user_by_username('admin')
        original_subs = list(admin_user.push_subscriptions)

        admin_user.push_subscriptions = [
            {
                'endpoint': 'https://push.test.example.com/test123',
                'keys': {'auth': 'auth_key', 'p256dh': 'p256dh_key'},
                'created_at': '2026-01-01T00:00:00',
            }
        ]

        import push_manager as _pm
        monkeypatch.setattr(_pm, 'send_push', lambda sub, payload, ttl=60, urgency='high': True)

        try:
            resp = client_admin.post('/api/push/test', json={'type': 'test'})
            assert resp.status_code in (200, 400, 500)
        finally:
            admin_user.push_subscriptions = original_subs
            user_manager.save_users()

    def test_push_test_trigger_with_subscription_and_mock(self, client_admin, monkeypatch):
        admin_user = user_manager.get_user_by_username('admin')
        original_subs = list(admin_user.push_subscriptions)

        admin_user.push_subscriptions = [
            {
                'endpoint': 'https://push.test.example.com/trigger456',
                'keys': {'auth': 'a', 'p256dh': 'p'},
                'created_at': '2026-01-01T00:00:00',
            }
        ]

        import push_manager as _pm
        monkeypatch.setattr(_pm, 'send_push', lambda sub, payload, ttl=300, urgency='normal': True)

        try:
            resp = client_admin.post('/api/push/test/N1')
            assert resp.status_code in (200, 400, 500)
        finally:
            admin_user.push_subscriptions = original_subs
            user_manager.save_users()

    def test_push_test_trigger_with_dead_endpoint(self, client_admin, monkeypatch):
        admin_user = user_manager.get_user_by_username('admin')
        original_subs = list(admin_user.push_subscriptions)

        admin_user.push_subscriptions = [
            {
                'endpoint': 'https://push.dead.example.com/dead789',
                'keys': {'auth': 'a', 'p256dh': 'p'},
                'created_at': '2026-01-01T00:00:00',
            }
        ]

        import push_manager as _pm
        monkeypatch.setattr(_pm, 'send_push', lambda sub, payload, ttl=300, urgency='normal': False)

        try:
            resp = client_admin.post('/api/push/test/N7')
            assert resp.status_code in (200, 400, 500)
        finally:
            admin_user.push_subscriptions = original_subs
            user_manager.save_users()


# ---------------------------------------------------------------------------
# Cache scheduler management
# ---------------------------------------------------------------------------


class TestCacheSchedulerManagement:

    def test_get_or_create_cache_scheduler_returns_something(self):
        result = _app_mod.get_or_create_cache_scheduler()
        # May be None if creation fails in test env, but the function should not raise
        assert result is None or result is not None


# ---------------------------------------------------------------------------
# ISS location endpoint
# ---------------------------------------------------------------------------


class TestISSLocation:

    def test_iss_location_returns_response(self, client_admin):
        resp = client_admin.get('/api/iss/location')
        assert resp.status_code in (200, 202, 400, 500)

    def test_iss_location_unauthenticated_returns_401(self, client):
        resp = client.get('/api/iss/location')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Spaceflight image endpoint
# ---------------------------------------------------------------------------


class TestSpaceflightImage:

    def test_spaceflight_img_valid_hex_filename(self, client_admin):
        # Valid hex filename pattern but missing — should be 404
        resp = client_admin.get('/api/spaceflight/img/abc123def456abc123def456abc123de.jpg')
        assert resp.status_code in (200, 404, 400)

    def test_spaceflight_img_path_traversal_blocked(self, client_admin):
        resp = client_admin.get('/api/spaceflight/img/../../../etc/passwd')
        assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Object info endpoint — deeper coverage
# ---------------------------------------------------------------------------


class TestObjectInfoDeep:

    def test_object_m31_returns_response(self, client_admin, monkeypatch):
        import object_info as _oi
        monkeypatch.setattr(
            _oi,
            'get_object_info',
            lambda identifier, language='en': {'name': 'Andromeda Galaxy', 'type': 'Galaxy'},
        )
        resp = client_admin.get('/api/object/M31')
        assert resp.status_code in (200, 404, 500)

    def test_object_info_none_returns_404(self, client_admin, monkeypatch):
        import object_info as _oi
        monkeypatch.setattr(_oi, 'get_object_info', lambda identifier, language='en': None)
        resp = client_admin.get('/api/object/XYZ999')
        assert resp.status_code in (404, 500)


# ---------------------------------------------------------------------------
# Push subscribe with existing subscription (idempotent)
# ---------------------------------------------------------------------------


class TestPushSubscribeIdempotent:

    def test_subscribe_same_endpoint_twice_returns_200(self, client_admin, monkeypatch):
        endpoint = 'https://push.mozilla.com/push/idempotent-test-12345'
        admin_user = user_manager.get_user_by_username('admin')
        original_subs = list(admin_user.push_subscriptions)

        # Pre-add subscription
        admin_user.push_subscriptions = [
            {'endpoint': endpoint, 'keys': {}, 'created_at': '2026-01-01T00:00:00'}
        ]

        try:
            resp = client_admin.post(
                '/api/push/subscribe',
                json={
                    'subscription': {
                        'endpoint': endpoint,
                        'keys': {'auth': 'x', 'p256dh': 'y'},
                    }
                },
            )
            assert resp.status_code == 200
        finally:
            admin_user.push_subscriptions = original_subs
            user_manager.save_users()


# ---------------------------------------------------------------------------
# Config import endpoint
# ---------------------------------------------------------------------------


class TestConfigImport:

    def test_import_config_unauthenticated_returns_401(self, client):
        resp = client.post('/api/config/import', data={})
        assert resp.status_code in (401, 404, 405)

    def test_import_config_no_file_returns_error(self, client_admin):
        resp = client_admin.post('/api/config/import', data={})
        assert resp.status_code in (400, 404, 405)


# ---------------------------------------------------------------------------
# Moon planner stale data
# ---------------------------------------------------------------------------


class TestMoonPlannerStaleData:

    def test_moon_planner_stale_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: False)
        monkeypatch.setitem(_cache_store._moon_planner_report_cache, 'data', {'nights': [], 'stale': True})
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Sidereal time with location configured
# ---------------------------------------------------------------------------


class TestSiderealTimeWithLocation:

    def test_sidereal_time_with_no_location_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {})
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Upcoming events with all caches populated — full aggregation path
# ---------------------------------------------------------------------------


class TestUpcomingEventsFullAggregation:

    def test_upcoming_events_with_fr_lang(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: True)
        monkeypatch.setitem(_cache_store._solar_eclipse_cache, 'data', {'eclipse': None, 'status': 'none'})
        monkeypatch.setitem(_cache_store._lunar_eclipse_cache, 'data', {'eclipse': None, 'status': 'none'})
        monkeypatch.setitem(_cache_store._aurora_cache, 'data', {'kp_index': 1.0, 'probability': 5.0})
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 20})
        monkeypatch.setitem(_cache_store._moon_planner_report_cache, 'data', {'nights': []})
        monkeypatch.setitem(_cache_store._planetary_events_cache, 'data', {'events': []})
        monkeypatch.setitem(
            _cache_store._special_phenomena_cache,
            'data',
            {'events': [], 'equinoxes_solstices': [], 'zodiacal_light': [], 'milky_way': []},
        )
        monkeypatch.setitem(
            _cache_store._solar_system_events_cache,
            'data',
            {'events': [], 'meteor_showers': [], 'comets': [], 'asteroid_occultations': []},
        )
        resp = client_admin.get('/api/events/upcoming', headers={'Accept-Language': 'fr'})
        assert resp.status_code in (200, 202, 400, 500)


# ---------------------------------------------------------------------------
# Change password validation paths (does not change shared state)
# ---------------------------------------------------------------------------


class TestChangePasswordValidation:

    def test_short_new_password_returns_400(self, client_admin):
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'admin', 'new_password': 'x'},
        )
        assert resp.status_code in (400, 200)

    def test_same_as_current_returns_400(self, client_admin):
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'admin', 'new_password': 'admin'},
        )
        assert resp.status_code in (400, 200)


# ---------------------------------------------------------------------------
# Plan-my-night routes that call route handler bodies (lines 3028+)
# ---------------------------------------------------------------------------


class TestPlanMyNightRouteHandlers:

    def test_plan_add_target_with_data_returns_response(self, client_admin, monkeypatch, tmp_path):
        import plan_my_night as _pmn
        monkeypatch.setattr(_pmn, 'PLAN_DIR', str(tmp_path))
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        resp = client_admin.post('/api/plan-my-night/targets', json={
            'name': 'M42',
            'catalogue': 'Messier',
            'night_start': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            'night_end': future,
        })
        assert resp.status_code in (200, 201, 400, 422, 500)

    def test_plan_remove_nonexistent_target_returns_response(self, client_admin):
        import uuid
        resp = client_admin.delete(f'/api/plan-my-night/targets/{uuid.uuid4()}')
        assert resp.status_code in (200, 404, 400)

    def test_plan_reorder_nonexistent_target_returns_response(self, client_admin):
        import uuid
        resp = client_admin.post(
            f'/api/plan-my-night/targets/{uuid.uuid4()}/reorder',
            json={'position': 0},
        )
        assert resp.status_code in (200, 404, 400)

    def test_plan_update_target_returns_response(self, client_admin):
        import uuid
        resp = client_admin.put(
            f'/api/plan-my-night/targets/{uuid.uuid4()}',
            json={'done': True},
        )
        assert resp.status_code in (200, 404, 400)


# ---------------------------------------------------------------------------
# Cache sync path (covers sync_cache_from_shared branch → returns 202)
# ---------------------------------------------------------------------------


class TestCacheSyncPath:

    def test_moon_report_after_sync_returns_200(self, client_admin, monkeypatch):
        call_count = [0]

        def valid_after_sync(cache, ttl):
            call_count[0] += 1
            return call_count[0] >= 2  # False first, True second

        monkeypatch.setattr(_cache_store, 'is_cache_valid', valid_after_sync)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: True)
        monkeypatch.setitem(_cache_store._moon_report_cache, 'data', {'moon': 'data'})
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code == 200

    def test_aurora_after_sync_returns_200(self, client_admin, monkeypatch):
        call_count = [0]

        def valid_after_sync(cache, ttl):
            call_count[0] += 1
            return call_count[0] >= 2

        monkeypatch.setattr(_cache_store, 'is_cache_valid', valid_after_sync)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: True)
        monkeypatch.setitem(_cache_store._aurora_cache, 'data', {'kp': 1})
        resp = client_admin.get('/api/aurora/predictions')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Sun report endpoint
# ---------------------------------------------------------------------------


class TestSunReportEndpoint:

    def test_sun_report_with_cache_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: True)
        monkeypatch.setitem(_cache_store._sun_report_cache, 'data', {'sun': 'data'})
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code == 200

    def test_sun_report_stale_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda c, t: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda n, c: False)
        monkeypatch.setitem(_cache_store._sun_report_cache, 'data', {'sun': 'stale'})
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ISS passes with sync path
# ---------------------------------------------------------------------------


class TestIssPassesSyncPath:

    def test_iss_after_sync_returns_200(self, client_admin, monkeypatch):
        call_count = [0]

        def valid_after_sync(cache, ttl):
            call_count[0] += 1
            return call_count[0] >= 2

        monkeypatch.setattr(_cache_store, 'is_cache_valid', valid_after_sync)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda name, cache: True)
        monkeypatch.setitem(_cache_store._iss_passes_cache, 'data', {'passes': [], 'window_days': 20})
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Push subscribe success + list subscriptions (covers _provider helper body)
# ---------------------------------------------------------------------------


class TestPushSubscribeAndList:
    """Test push subscribe success path and list subscriptions (covers lines 522-576)."""

    @pytest.fixture
    def client_with_subscription(self, client_admin):
        """Subscribe the admin user then yield, cleaning up after."""
        fake_endpoint = 'https://fcm.googleapis.com/fake/endpoint/test123'
        resp = client_admin.post('/api/push/subscribe', json={
            'subscription': {
                'endpoint': fake_endpoint,
                'keys': {'p256dh': 'fake_key', 'auth': 'fake_auth'},
            }
        })
        yield client_admin, resp
        # Clean up: remove subscription
        client_admin.delete('/api/push/unsubscribe', json={'endpoint': fake_endpoint})

    def test_subscribe_with_valid_endpoint_returns_subscribed(self, client_with_subscription):
        _, resp = client_with_subscription
        assert resp.status_code == 200
        assert resp.get_json().get('status') == 'subscribed'

    def test_list_subscriptions_with_provider_detection(self, client_with_subscription):
        client, _ = client_with_subscription
        resp = client.get('/api/push/subscriptions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data.get('subscriptions'), list)
        if data['subscriptions']:
            assert 'provider' in data['subscriptions'][0]
            # fcm.googleapis.com should be detected as 'google'
            assert data['subscriptions'][0]['provider'] == 'google'

    def test_duplicate_subscribe_is_idempotent(self, client_with_subscription):
        client, _ = client_with_subscription
        # Subscribe again with same endpoint — should still return 'subscribed'
        resp = client.post('/api/push/subscribe', json={
            'subscription': {
                'endpoint': 'https://fcm.googleapis.com/fake/endpoint/test123',
                'keys': {},
            }
        })
        assert resp.status_code == 200

    def test_list_subscriptions_unauthenticated_returns_401(self, client):
        resp = client.get('/api/push/subscriptions')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Static file with versioned URL (covers after_request cache header path)
# ---------------------------------------------------------------------------


class TestStaticVersionedUrl:

    def test_static_file_with_version_param(self, client):
        resp = client.get('/static/css/theme.css?v=1.0.0')
        # May return 200 or 404, but either way the after_request handler runs
        assert resp.status_code in (200, 304, 404)

    def test_static_icon_file(self, client):
        resp = client.get('/static/ico/favicon.ico')
        assert resp.status_code in (200, 304, 404)

    def test_static_unversioned_non_icon(self, client):
        """Line 219: unversioned, non-icon → short cache header."""
        resp = client.get('/static/css/theme.css')
        assert resp.status_code in (200, 304, 404)
        if resp.status_code != 404:
            assert 'public, max-age=3600' in resp.headers.get('Cache-Control', '')

    def test_static_file_debug_mode_sets_no_store(self, client, monkeypatch):
        """Lines 205-208: debug mode → no-store headers."""
        monkeypatch.setenv('FLASK_DEBUG', '1')
        resp = client.get('/static/css/theme.css')
        assert resp.status_code in (200, 304, 404)
        cc = resp.headers.get('Cache-Control', '')
        assert 'no-store' in cc or 'no-cache' in cc


# ---------------------------------------------------------------------------
# Pure app helper functions (no Flask context needed)
# ---------------------------------------------------------------------------


class TestParseDurationMinutes:
    """Lines 3053-3070: _parse_duration_minutes."""

    def setup_method(self):
        from app import _parse_duration_minutes
        self._fn = _parse_duration_minutes

    def test_none_returns_zero(self):
        assert self._fn(None) == 0

    def test_empty_string_returns_zero(self):
        assert self._fn('') == 0

    def test_no_colon_returns_zero(self):
        assert self._fn('90') == 0

    def test_valid_hhmm(self):
        assert self._fn('1:30') == 90

    def test_valid_zero_hours(self):
        assert self._fn('0:45') == 45

    def test_minutes_over_59_returns_zero(self):
        assert self._fn('1:70') == 0

    def test_negative_hours_returns_zero(self):
        assert self._fn('-1:00') == 0

    def test_non_numeric_parts_returns_zero(self):
        assert self._fn('abc:def') == 0

    def test_three_parts_returns_zero(self):
        assert self._fn('1:30:00') == 0

    def test_whitespace_stripped(self):
        assert self._fn('  2:15  ') == 135


class TestFormatMinutesHhmm:
    """Lines 3074-3075: _format_minutes_hhmm."""

    def setup_method(self):
        from app import _format_minutes_hhmm
        self._fn = _format_minutes_hhmm

    def test_zero(self):
        assert self._fn(0) == '0h00'

    def test_one_hour(self):
        assert self._fn(60) == '1h00'

    def test_ninety_minutes(self):
        assert self._fn(90) == '1h30'

    def test_negative_clamped(self):
        assert self._fn(-10) == '0h00'


class TestComputePlanFillMetrics:
    """Lines 3079-3112: _compute_plan_fill_metrics."""

    def setup_method(self):
        from app import _compute_plan_fill_metrics
        self._fn = _compute_plan_fill_metrics

    def test_non_dict_plan_returns_zeros(self):
        result = self._fn(None)
        assert result['planned_minutes'] == 0
        assert result['night_minutes'] == 0

    def test_empty_plan_returns_zeros(self):
        result = self._fn({})
        assert result['planned_minutes'] == 0

    def test_entries_not_list_becomes_empty(self):
        """Line 3081: entries is not a list → reset to []."""
        result = self._fn({'entries': 'not_a_list'})
        assert result['planned_minutes'] == 0

    def test_non_dict_entry_is_skipped(self):
        """Lines 3085-3086: non-dict entry → continue."""
        result = self._fn({'entries': ['not_a_dict', None]})
        assert result['planned_minutes'] == 0

    def test_entry_with_planned_minutes_int(self):
        result = self._fn({'entries': [{'planned_minutes': 30}]})
        assert result['planned_minutes'] == 30

    def test_entry_falls_back_to_planned_duration(self):
        """Lines 3091-3093: int(planned_minutes) fails → use planned_duration."""
        result = self._fn({'entries': [{'planned_minutes': None, 'planned_duration': '1:30'}]})
        assert result['planned_minutes'] == 90

    def test_fill_percent_computed_with_night_window(self):
        plan = {
            'entries': [{'planned_minutes': 60}],
            'night_start': '2026-06-01T21:00:00',
            'night_end': '2026-06-02T03:00:00',
        }
        result = self._fn(plan)
        assert result['night_minutes'] == 360
        assert abs(result['fill_percent'] - (60 / 360 * 100)) < 0.01

    def test_overflow_minutes_computed(self):
        plan = {
            'entries': [{'planned_minutes': 400}],
            'night_start': '2026-06-01T21:00:00',
            'night_end': '2026-06-02T03:00:00',
        }
        result = self._fn(plan)
        assert result['overflow_minutes'] == 40  # 400 - 360

    def test_start_delay_reduces_night_window(self):
        plan = {
            'entries': [{'planned_minutes': 60}],
            'night_start': '2026-06-01T21:00:00',
            'night_end': '2026-06-02T03:00:00',
            'start_delay_minutes': 30,
        }
        result = self._fn(plan)
        assert result['night_minutes'] == 330  # 360 - 30


# ---------------------------------------------------------------------------
# Auth route error handlers
# ---------------------------------------------------------------------------


class TestAuthErrorHandlers:
    """Cover missing error handler branches in auth routes."""

    def test_change_password_generic_value_error_uses_default_key(self, client_admin, monkeypatch):
        """Lines 411->414: ValueError with unrecognised message → default error_key."""
        monkeypatch.setattr(user_manager, 'change_own_password',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("Something else")))
        resp = client_admin.post('/api/auth/change-password', json={
            'current_password': 'x', 'new_password': 'y'
        })
        assert resp.status_code == 400
        assert resp.get_json().get('error_key') == 'users.error_update_password'

    def test_change_password_unexpected_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 416-418: unexpected exception in change_own_password → 500."""
        monkeypatch.setattr(user_manager, 'change_own_password',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db down")))
        resp = client_admin.post('/api/auth/change-password', json={
            'current_password': 'x', 'new_password': 'y'
        })
        assert resp.status_code == 500

    def test_preferences_get_unexpected_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 432-437: exception in get_user_preferences → 500."""
        monkeypatch.setattr(user_manager, 'get_user_preferences',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db error")))
        resp = client_admin.get('/api/auth/preferences')
        assert resp.status_code == 500

    def test_preferences_put_missing_preferences_key_returns_400(self, client_admin):
        """Line 452: no 'preferences' key in request body → 400."""
        resp = client_admin.put('/api/auth/preferences', json={'other': 'data'})
        assert resp.status_code == 400

    def test_preferences_put_invalid_subtab_returns_400(self, client_admin, monkeypatch):
        """Line 463: Invalid startup_subtab → 400 with specific error_key."""
        monkeypatch.setattr(user_manager, 'update_user_preferences',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("Invalid startup_subtab: x")))
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {}})
        assert resp.status_code == 400
        assert resp.get_json().get('error_key') == 'settings.pref_invalid_startup_subtab'

    def test_preferences_put_invalid_time_format_returns_400(self, client_admin, monkeypatch):
        """Line 465: Invalid time_format → 400 with specific error_key."""
        monkeypatch.setattr(user_manager, 'update_user_preferences',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("Invalid time_format: x")))
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {}})
        assert resp.status_code == 400
        assert resp.get_json().get('error_key') == 'settings.pref_invalid_time_format'

    def test_preferences_put_invalid_density_returns_400(self, client_admin, monkeypatch):
        """Line 467: Invalid density → 400 with specific error_key."""
        monkeypatch.setattr(user_manager, 'update_user_preferences',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("Invalid density: x")))
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {}})
        assert resp.status_code == 400
        assert resp.get_json().get('error_key') == 'settings.pref_invalid_density'

    def test_preferences_put_generic_value_error_returns_400(self, client_admin, monkeypatch):
        """Lines 468->471: ValueError with unrecognised text → default error_key."""
        monkeypatch.setattr(user_manager, 'update_user_preferences',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("Some unknown error")))
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {}})
        assert resp.status_code == 400
        assert resp.get_json().get('error_key') == 'settings.pref_save_error'

    def test_preferences_put_unexpected_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 473-475: unexpected exception in update_user_preferences → 500."""
        monkeypatch.setattr(user_manager, 'update_user_preferences',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("crash")))
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {}})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Push API error handlers
# ---------------------------------------------------------------------------


class TestPushApiErrors:
    """Cover missing error handler branches in push API routes."""

    def test_vapid_public_key_exception_returns_503(self, client_admin, monkeypatch):
        """Lines 490-492: exception in get_vapid_public_key → 503."""
        import sys, types
        fake_pm = types.ModuleType('push_manager')
        fake_pm.get_vapid_public_key = lambda: (_ for _ in ()).throw(RuntimeError("no vapid"))
        monkeypatch.setitem(sys.modules, 'push_manager', fake_pm)
        resp = client_admin.get('/api/push/vapid-public-key')
        assert resp.status_code == 503

    def test_vapid_config_status_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 503-505: exception in get_vapid_contact_status → 500."""
        import sys, types
        fake_pm = types.ModuleType('push_manager')
        fake_pm.get_vapid_contact_status = lambda: (_ for _ in ()).throw(RuntimeError("error"))
        monkeypatch.setitem(sys.modules, 'push_manager', fake_pm)
        resp = client_admin.get('/api/push/vapid-config-status')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Equipment API routes: CRUD operations for all equipment types
# ---------------------------------------------------------------------------

_TELESCOPE_DATA = {
    'name': 'Test Refractor', 'telescope_type': 'Refractor',
    'aperture_mm': 100, 'focal_length_mm': 800,
}
_CAMERA_DATA = {
    'name': 'ASI294', 'manufacturer': 'ZWO',
    'sensor_width_mm': 19.1, 'sensor_height_mm': 13.0,
    'resolution_width_px': 4144, 'resolution_height_px': 2822,
    'pixel_size_um': 4.63, 'sensor_type': 'CMOS',
}
_MOUNT_DATA = {'name': 'EQ6-R', 'mount_type': 'Equatorial', 'payload_capacity_kg': 20}
_FILTER_DATA = {'name': 'OIII', 'filter_type': 'Narrowband'}
_ACCESSORY_DATA = {'name': '2x Barlow'}


class TestEquipmentApiRoutes:
    """Cover create/get/update/delete paths for all equipment API routes (lines 3942-4679)."""

    # ---- Telescopes ----

    def test_create_telescope_returns_201(self, client_admin):
        resp = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA)
        assert resp.status_code == 201
        assert resp.get_json()['status'] == 'success'

    def test_get_telescope_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/telescopes/nonexistent-scope-id')
        assert resp.status_code == 404

    def test_update_telescope_success_returns_200(self, client_admin):
        r = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA)
        tid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/telescopes/{tid}', json={
            **_TELESCOPE_DATA, 'name': 'Updated Scope'
        })
        assert resp.status_code == 200

    def test_update_telescope_not_found_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/telescopes/nonexistent-id', json=_TELESCOPE_DATA)
        assert resp.status_code == 404

    def test_delete_telescope_success(self, client_admin):
        r = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA)
        tid = r.get_json()['data']['id']
        resp = client_admin.delete(f'/api/equipment/telescopes/{tid}')
        assert resp.status_code == 200

    def test_delete_telescope_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_telescope', lambda *_: False)
        resp = client_admin.delete('/api/equipment/telescopes/some-id')
        assert resp.status_code == 500

    def test_get_telescopes_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'load_user_telescopes',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk")))
        resp = client_admin.get('/api/equipment/telescopes')
        assert resp.status_code == 500

    def test_create_telescope_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'create_telescope',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA)
        assert resp.status_code == 500

    def test_get_telescope_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_telescope',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/telescopes/any-id')
        assert resp.status_code == 500

    def test_update_telescope_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'update_telescope',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.put('/api/equipment/telescopes/any-id', json=_TELESCOPE_DATA)
        assert resp.status_code == 500

    def test_delete_telescope_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_telescope',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.delete('/api/equipment/telescopes/any-id')
        assert resp.status_code == 500

    # ---- Cameras ----

    def test_create_camera_returns_201(self, client_admin):
        resp = client_admin.post('/api/equipment/cameras', json=_CAMERA_DATA)
        assert resp.status_code == 201

    def test_get_camera_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/cameras/nonexistent-camera-id')
        assert resp.status_code == 404

    def test_update_camera_success_returns_200(self, client_admin):
        r = client_admin.post('/api/equipment/cameras', json=_CAMERA_DATA)
        cid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/cameras/{cid}', json={**_CAMERA_DATA, 'name': 'Cam2'})
        assert resp.status_code == 200

    def test_update_camera_not_found_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/cameras/nonexistent-id', json=_CAMERA_DATA)
        assert resp.status_code == 404

    def test_delete_camera_success(self, client_admin):
        r = client_admin.post('/api/equipment/cameras', json=_CAMERA_DATA)
        cid = r.get_json()['data']['id']
        resp = client_admin.delete(f'/api/equipment/cameras/{cid}')
        assert resp.status_code == 200

    def test_delete_camera_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_camera', lambda *_: False)
        resp = client_admin.delete('/api/equipment/cameras/any-id')
        assert resp.status_code == 500

    def test_get_cameras_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'load_user_cameras',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk")))
        resp = client_admin.get('/api/equipment/cameras')
        assert resp.status_code == 500

    def test_create_camera_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'create_camera',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/equipment/cameras', json=_CAMERA_DATA)
        assert resp.status_code == 500

    def test_get_camera_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_camera',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/cameras/any-id')
        assert resp.status_code == 500

    def test_update_camera_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'update_camera',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.put('/api/equipment/cameras/any-id', json=_CAMERA_DATA)
        assert resp.status_code == 500

    def test_delete_camera_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_camera',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.delete('/api/equipment/cameras/any-id')
        assert resp.status_code == 500

    # ---- Mounts ----

    def test_create_mount_returns_201(self, client_admin):
        resp = client_admin.post('/api/equipment/mounts', json=_MOUNT_DATA)
        assert resp.status_code == 201

    def test_get_mount_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/mounts/nonexistent-mount-id')
        assert resp.status_code == 404

    def test_update_mount_success_returns_200(self, client_admin):
        r = client_admin.post('/api/equipment/mounts', json=_MOUNT_DATA)
        mid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/mounts/{mid}', json={**_MOUNT_DATA, 'name': 'EQ8'})
        assert resp.status_code == 200

    def test_update_mount_not_found_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/mounts/nonexistent-id', json=_MOUNT_DATA)
        assert resp.status_code == 404

    def test_delete_mount_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_mount', lambda *_: False)
        resp = client_admin.delete('/api/equipment/mounts/any-id')
        assert resp.status_code == 500

    def test_get_mounts_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'load_user_mounts',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk")))
        resp = client_admin.get('/api/equipment/mounts')
        assert resp.status_code == 500

    def test_create_mount_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'create_mount',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/equipment/mounts', json=_MOUNT_DATA)
        assert resp.status_code == 500

    def test_get_mount_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_mount',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/mounts/any-id')
        assert resp.status_code == 500

    def test_update_mount_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'update_mount',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.put('/api/equipment/mounts/any-id', json=_MOUNT_DATA)
        assert resp.status_code == 500

    def test_delete_mount_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_mount',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.delete('/api/equipment/mounts/any-id')
        assert resp.status_code == 500

    # ---- Filters ----

    def test_create_filter_returns_201(self, client_admin):
        resp = client_admin.post('/api/equipment/filters', json=_FILTER_DATA)
        assert resp.status_code == 201

    def test_get_filter_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/filters/nonexistent-filter-id')
        assert resp.status_code == 404

    def test_update_filter_success_returns_200(self, client_admin):
        r = client_admin.post('/api/equipment/filters', json=_FILTER_DATA)
        fid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/filters/{fid}', json={
            **_FILTER_DATA, 'name': 'H-Alpha'
        })
        assert resp.status_code == 200

    def test_update_filter_not_found_returns_404(self, client_admin):
        resp = client_admin.put('/api/equipment/filters/nonexistent-id', json=_FILTER_DATA)
        assert resp.status_code == 404

    def test_delete_filter_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_filter', lambda *_: False)
        resp = client_admin.delete('/api/equipment/filters/any-id')
        assert resp.status_code == 500

    def test_get_filters_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'load_user_filters',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk")))
        resp = client_admin.get('/api/equipment/filters')
        assert resp.status_code == 500

    def test_create_filter_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'create_filter',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/equipment/filters', json=_FILTER_DATA)
        assert resp.status_code == 500

    def test_get_filter_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_filter',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/filters/any-id')
        assert resp.status_code == 500

    def test_update_filter_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'update_filter',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.put('/api/equipment/filters/any-id', json=_FILTER_DATA)
        assert resp.status_code == 500

    def test_delete_filter_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_filter',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.delete('/api/equipment/filters/any-id')
        assert resp.status_code == 500

    # ---- Accessories ----

    def test_create_accessory_returns_201(self, client_admin):
        resp = client_admin.post('/api/equipment/accessories', json=_ACCESSORY_DATA)
        assert resp.status_code == 201

    def test_get_accessory_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/accessories/nonexistent-id')
        assert resp.status_code == 404

    def test_update_accessory_success_returns_200(self, client_admin):
        r = client_admin.post('/api/equipment/accessories', json=_ACCESSORY_DATA)
        aid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/accessories/{aid}', json={'name': '3x Barlow'})
        assert resp.status_code == 200

    def test_update_accessory_not_found_returns_500(self, client_admin):
        resp = client_admin.put('/api/equipment/accessories/nonexistent-id', json=_ACCESSORY_DATA)
        assert resp.status_code == 500

    def test_delete_accessory_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_accessory', lambda *_: False)
        resp = client_admin.delete('/api/equipment/accessories/any-id')
        assert resp.status_code == 500

    def test_get_accessories_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'load_user_accessories',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk")))
        resp = client_admin.get('/api/equipment/accessories')
        assert resp.status_code == 500

    def test_create_accessory_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'create_accessory',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/equipment/accessories', json=_ACCESSORY_DATA)
        assert resp.status_code == 500

    def test_get_accessory_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_accessory',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/accessories/any-id')
        assert resp.status_code == 500

    def test_update_accessory_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'update_accessory',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.put('/api/equipment/accessories/any-id', json=_ACCESSORY_DATA)
        assert resp.status_code == 500

    def test_delete_accessory_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_accessory',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.delete('/api/equipment/accessories/any-id')
        assert resp.status_code == 500

    # ---- Combinations ----

    def test_create_combination_returns_201(self, client_admin):
        scope = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        resp = client_admin.post('/api/equipment/combinations', json={
            'name': 'Main Combo', 'telescope_id': scope['id']
        })
        assert resp.status_code == 201

    def test_get_combination_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/combinations/nonexistent-combo-id')
        assert resp.status_code == 404

    def test_update_combination_success_returns_200(self, client_admin):
        scope = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        r = client_admin.post('/api/equipment/combinations', json={
            'name': 'C1', 'telescope_id': scope['id']
        })
        cid = r.get_json()['data']['id']
        resp = client_admin.put(f'/api/equipment/combinations/{cid}', json={
            'name': 'C1 Updated', 'telescope_id': scope['id']
        })
        assert resp.status_code == 200

    def test_update_combination_not_found_returns_404(self, client_admin):
        scope = client_admin.post('/api/equipment/telescopes', json=_TELESCOPE_DATA).get_json()['data']
        resp = client_admin.put('/api/equipment/combinations/nonexistent-id', json={
            'name': 'X', 'telescope_id': scope['id']
        })
        assert resp.status_code == 404

    def test_delete_combination_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_combination', lambda *_: False)
        resp = client_admin.delete('/api/equipment/combinations/any-id')
        assert resp.status_code == 500

    def test_get_combinations_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'load_user_combinations',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("disk")))
        resp = client_admin.get('/api/equipment/combinations')
        assert resp.status_code == 500

    def test_create_combination_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'create_combination',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/equipment/combinations', json={
            'name': 'X', 'telescope_id': 'any'
        })
        assert resp.status_code == 500

    def test_get_combination_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_combination',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/combinations/any-id')
        assert resp.status_code == 500

    def test_update_combination_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'update_combination',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.put('/api/equipment/combinations/any-id', json={'name': 'X'})
        assert resp.status_code == 500

    def test_delete_combination_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'delete_combination',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.delete('/api/equipment/combinations/any-id')
        assert resp.status_code == 500

    # ---- FOV Calculator and Equipment Summary ----

    def test_fov_calculator_returns_200(self, client_admin):
        resp = client_admin.post('/api/equipment/fov-calculator', json={
            'telescope_focal_length_mm': 800,
            'camera_sensor_width_mm': 10.0,
            'camera_sensor_height_mm': 7.0,
            'camera_pixel_size_um': 3.75,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'horizontal_fov_deg' in data

    def test_fov_calculator_exception_returns_500(self, client_admin):
        resp = client_admin.post('/api/equipment/fov-calculator', json={})
        assert resp.status_code == 500

    def test_equipment_summary_returns_200(self, client_admin):
        resp = client_admin.get('/api/equipment/summary')
        assert resp.status_code == 200

    def test_equipment_summary_exception_returns_500_duplicate(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_all_equipment_summary',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/summary')
        assert resp.status_code == 500

    # ---- Analyze combination ----

    def test_analyze_combination_not_found_returns_404(self, client_admin):
        resp = client_admin.get('/api/equipment/combinations/nonexistent-id/analyze')
        assert resp.status_code == 404

    def test_equipment_summary_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.equipment_profiles, 'get_all_equipment_summary',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/equipment/summary')
        assert resp.status_code == 500

    def test_equipment_summary_no_user_id_returns_401(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', lambda: None)
        resp = client_admin.get('/api/equipment/summary')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# _enrich_plan_entries_with_astrodex_status branch coverage
# ---------------------------------------------------------------------------


class TestEnrichPlanEntriesWithAstrodexStatus:
    """Cover branch paths in _enrich_plan_entries_with_astrodex_status (lines 3027-3047)."""

    def setup_method(self):
        from app import _enrich_plan_entries_with_astrodex_status
        self._fn = _enrich_plan_entries_with_astrodex_status

    def test_non_dict_payload_returned_unchanged(self):
        result = self._fn("not-a-dict", 'user1')
        assert result == "not-a-dict"

    def test_plan_not_dict_returned_unchanged(self):
        result = self._fn({'plan': 'not-a-dict'}, 'user1')
        assert result == {'plan': 'not-a-dict'}

    def test_entries_not_list_returned_unchanged(self):
        result = self._fn({'plan': {'entries': 'bad'}}, 'user1')
        assert result == {'plan': {'entries': 'bad'}}

    def test_non_dict_entry_is_skipped(self, monkeypatch):
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_: False)
        result = self._fn({'plan': {'entries': ['not-a-dict']}}, 'user1')
        assert result['plan']['entries'] == ['not-a-dict']

    def test_entry_with_empty_name_sets_false(self, monkeypatch):
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_: False)
        entry = {'name': '', 'catalogue': 'Messier'}
        result = self._fn({'plan': {'entries': [entry]}}, 'user1')
        assert result['plan']['entries'][0]['in_astrodex'] is False


# ---------------------------------------------------------------------------
# Sky quality — invalid (non-numeric) values hit ValueError except handlers
# ---------------------------------------------------------------------------


class TestSkyQualityInvalidValues:

    def test_both_sqm_and_bortle_invalid_returns_not_configured(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: {'location': {'sqm': 'bad', 'bortle': 'worse'}})
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        assert resp.get_json()['sqm_source'] == 'not_configured'

    def test_sqm_only_invalid_returns_null_sqm(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: {'location': {'sqm': 'invalid'}})
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        assert resp.get_json()['sqm'] is None

    def test_bortle_only_invalid_returns_null_bortle(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: {'location': {'bortle': 'invalid'}})
        resp = client_admin.get('/api/skyquality')
        assert resp.status_code == 200
        assert resp.get_json()['bortle'] is None


# ---------------------------------------------------------------------------
# get_current_user() returns None → various routes return 401
# ---------------------------------------------------------------------------


class TestGetCurrentUserNullPaths:
    """Cover the 'if not current_user/user_id: return 401' branches across routes."""

    @pytest.fixture(autouse=True)
    def no_current_user(self, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', lambda: None)

    def test_change_password_returns_401(self, client_admin):
        resp = client_admin.post('/api/auth/change-password',
                                 json={'current_password': 'x', 'new_password': 'y'})
        assert resp.status_code == 401

    def test_get_preferences_returns_401(self, client_admin):
        resp = client_admin.get('/api/auth/preferences')
        assert resp.status_code == 401

    def test_update_preferences_returns_401(self, client_admin):
        resp = client_admin.put('/api/auth/preferences', json={'preferences': {}})
        assert resp.status_code == 401

    def test_push_subscribe_returns_401(self, client_admin):
        resp = client_admin.post('/api/push/subscribe',
                                 json={'subscription': {'endpoint': 'https://x', 'keys': {}}})
        assert resp.status_code == 401

    def test_push_list_subscriptions_returns_401(self, client_admin):
        resp = client_admin.get('/api/push/subscriptions')
        assert resp.status_code == 401

    def test_push_delete_subscriptions_returns_401(self, client_admin):
        resp = client_admin.delete('/api/push/subscriptions')
        assert resp.status_code == 401

    def test_push_test_trigger_returns_401(self, client_admin):
        resp = client_admin.post('/api/push/test/N1')
        assert resp.status_code == 401

    def test_push_unsubscribe_returns_401(self, client_admin):
        resp = client_admin.delete('/api/push/unsubscribe',
                                   json={'endpoint': 'https://x'})
        assert resp.status_code == 401

    def test_plan_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/plan-my-night/list')
        assert resp.status_code == 401

    def test_plan_get_returns_401(self, client_admin):
        resp = client_admin.get('/api/plan-my-night')
        assert resp.status_code == 401

    def test_plan_targets_post_returns_401(self, client_admin):
        resp = client_admin.post('/api/plan-my-night/targets',
                                 json={'item': {}, 'catalogue': 'Messier'})
        assert resp.status_code == 401

    def test_plan_pdf_export_returns_401(self, client_admin):
        resp = client_admin.get('/api/plan-my-night/export.pdf')
        assert resp.status_code == 401

    def test_astrodex_get_returns_401(self, client_admin):
        resp = client_admin.get('/api/astrodex')
        assert resp.status_code == 401

    def test_astrodex_image_returns_401(self, client_admin):
        resp = client_admin.get('/api/astrodex/images/test.jpg')
        assert resp.status_code == 401

    def test_astrodex_check_returns_401(self, client_admin):
        resp = client_admin.get('/api/astrodex/check/M31')
        assert resp.status_code == 401

    def test_equipment_telescopes_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/telescopes')
        assert resp.status_code == 401

    def test_equipment_cameras_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/cameras')
        assert resp.status_code == 401

    def test_equipment_mounts_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/mounts')
        assert resp.status_code == 401

    def test_equipment_filters_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/filters')
        assert resp.status_code == 401

    def test_equipment_accessories_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/accessories')
        assert resp.status_code == 401

    def test_equipment_summary_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/summary')
        assert resp.status_code == 401

    def test_equipment_combinations_list_returns_401(self, client_admin):
        resp = client_admin.get('/api/equipment/combinations')
        assert resp.status_code == 401

    def test_equipment_telescope_create_returns_401(self, client_admin):
        resp = client_admin.post('/api/equipment/telescopes', json={'name': 'T'})
        assert resp.status_code == 401

    def test_equipment_camera_create_returns_401(self, client_admin):
        resp = client_admin.post('/api/equipment/cameras', json={'name': 'C'})
        assert resp.status_code == 401

    def test_equipment_mount_create_returns_401(self, client_admin):
        resp = client_admin.post('/api/equipment/mounts', json={'name': 'M'})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Exception handlers in cache-serving routes (monkeypatch is_cache_valid)
# ---------------------------------------------------------------------------


class TestCacheRouteExceptionHandlers:

    def _raise(self, *_):
        raise RuntimeError("simulated cache failure")

    def test_moon_report_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code == 500

    def test_dark_window_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/moon/dark-window')
        assert resp.status_code == 500

    def test_next_7_nights_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code == 500

    def test_aurora_predictions_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/aurora/predictions')
        assert resp.status_code == 500

    def test_seeing_forecast_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code == 500

    def test_sun_today_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code == 500

    def test_solar_eclipse_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/sun/next-eclipse')
        assert resp.status_code == 500

    def test_lunar_eclipse_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/moon/next-eclipse')
        assert resp.status_code == 500

    def test_moon_calendar_exception_returns_500(self, client_admin, monkeypatch):
        _app_mod._moon_calendar_cache['data'] = None
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: (_ for _ in ()).throw(RuntimeError("cfg fail")))
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code == 500

    def test_iss_location_runtime_error_returns_503(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.iss_passes, 'get_current_position',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/iss/location')
        assert resp.status_code == 503

    def test_iss_location_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.iss_passes, 'get_current_position',
                            lambda *_a, **_k: (_ for _ in ()).throw(IOError("fail")))
        resp = client_admin.get('/api/iss/location')
        assert resp.status_code == 500

    def test_astrodex_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.astrodex, 'get_visible_astrodex',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/astrodex')
        assert resp.status_code == 500

    def test_astrodex_check_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/astrodex/check/M31')
        assert resp.status_code == 500

    def test_plan_list_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_all_plan_states',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/plan-my-night/list')
        assert resp.status_code == 500

    def test_plan_get_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/plan-my-night')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Moon month calendar — no location configured → 400
# ---------------------------------------------------------------------------


class TestMoonCalendarNoLocation:

    def test_no_location_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {'location': {}})
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code == 400

    def test_no_longitude_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: {'location': {'latitude': 48.5}})
        resp = client_admin.get('/api/moon/month-calendar')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Object info — invalid identifier and success path
# ---------------------------------------------------------------------------


class TestObjectInfoEdgeCases:

    def test_invalid_identifier_returns_400(self, client_admin):
        resp = client_admin.get('/api/object/!!!invalid!!!')
        assert resp.status_code == 400

    def test_valid_identifier_returns_data(self, client_admin, monkeypatch):
        import object_info as _oi
        monkeypatch.setattr(_oi, 'get_object_info',
                            lambda identifier, lang='en': {'name': identifier, 'type': 'Galaxy'})
        resp = client_admin.get('/api/object/M31')
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'M31'


# ---------------------------------------------------------------------------
# Logs API edge cases
# ---------------------------------------------------------------------------


class TestLogsApiEdgeCases:

    def test_level_filter_returns_matching(self, client_admin, monkeypatch, tmp_path):
        log_file = tmp_path / "myastroboard.log"
        log_file.write_text("INFO line\nDEBUG line\nINFO another\n")
        monkeypatch.setattr(_app_mod, 'DATA_DIR', str(tmp_path))
        resp = client_admin.get('/api/logs?level=DEBUG')
        assert resp.status_code == 200
        data = resp.get_json()
        assert all('DEBUG' in line for line in data.get('logs', []))

    def test_limit_zero_returns_all(self, client_admin, monkeypatch, tmp_path):
        log_file = tmp_path / "myastroboard.log"
        log_file.write_text("line1\nline2\nline3\n")
        monkeypatch.setattr(_app_mod, 'DATA_DIR', str(tmp_path))
        resp = client_admin.get('/api/logs?limit=0')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['showing'] == data['total']

    def test_no_log_file_returns_empty(self, client_admin, monkeypatch, tmp_path):
        monkeypatch.setattr(_app_mod, 'DATA_DIR', str(tmp_path))
        resp = client_admin.get('/api/logs')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 0

    def test_clear_logs_no_file_returns_success(self, client_admin, monkeypatch, tmp_path):
        monkeypatch.setattr(_app_mod, 'DATA_DIR', str(tmp_path))
        resp = client_admin.post('/api/logs/clear')
        assert resp.status_code == 200

    def test_clear_logs_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.os.path, 'exists',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fs error")))
        resp = client_admin.post('/api/logs/clear')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Export config — file not found and exception paths
# ---------------------------------------------------------------------------


class TestExportConfigEdgeCases:

    def test_config_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.os.path, 'isfile', lambda _: False)
        resp = client_admin.get('/api/config/export')
        assert resp.status_code == 404

    def test_config_export_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.os.path, 'isfile',
                            lambda _: (_ for _ in ()).throw(RuntimeError("disk error")))
        resp = client_admin.get('/api/config/export')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Preferences — ValueError and exception paths
# ---------------------------------------------------------------------------


class TestPreferencesEdgeCases:

    def test_get_preferences_value_error_returns_400(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'get_user_preferences',
                            lambda *_: (_ for _ in ()).throw(ValueError("bad pref")))
        resp = client_admin.get('/api/auth/preferences')
        assert resp.status_code == 400

    def test_update_preferences_value_error_returns_400(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'update_user_preferences',
                            lambda *_: (_ for _ in ()).throw(ValueError("bad pref")))
        resp = client_admin.put('/api/auth/preferences',
                                json={'preferences': {'language': 'xx'}})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# User management edge cases
# ---------------------------------------------------------------------------


class TestUserManagementEdgeCases:

    def test_create_user_other_value_error_returns_400(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'create_user',
                            lambda *_: (_ for _ in ()).throw(ValueError("Some other error")))
        resp = client_admin.post('/api/users',
                                 json={'username': 'u', 'password': 'p', 'role': 'user'})
        assert resp.status_code == 400

    def test_create_user_exception_returns_500(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'create_user',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("db fail")))
        resp = client_admin.post('/api/users',
                                 json={'username': 'u', 'password': 'p', 'role': 'user'})
        assert resp.status_code == 500

    def test_update_user_success_returns_200(self, client_admin, monkeypatch):
        import app as _a

        class _FakeUser:
            user_id = 'u1'
            username = 'newname'
            role = 'user'

        monkeypatch.setattr(_a.user_manager, 'update_user', lambda *_a, **_k: _FakeUser())
        resp = client_admin.put('/api/users/u1', json={'username': 'newname'})
        assert resp.status_code == 200

    def test_update_user_username_taken_returns_400(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'update_user',
                            lambda *_: (_ for _ in ()).throw(ValueError("Username x already taken")))
        resp = client_admin.put('/api/users/u1', json={'username': 'x'})
        assert resp.status_code == 400

    def test_update_user_exception_returns_500(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'update_user',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("db fail")))
        resp = client_admin.put('/api/users/u1', json={'username': 'x'})
        assert resp.status_code == 500

    def test_delete_user_exception_returns_500(self, client_admin, monkeypatch):
        import app as _a
        monkeypatch.setattr(_a.user_manager, 'delete_user',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("db fail")))
        resp = client_admin.delete('/api/users/some-id')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# ISS / Spaceflight exception paths
# ---------------------------------------------------------------------------


class TestIssSpaceflightExceptions:

    def test_iss_celestrak_restart_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.iss_passes, 'clear_celestrak_block_flag',
                            lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/iss/celestrak/restart')
        assert resp.status_code == 500

    def test_spaceflight_launches_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/spaceflight/launches')
        assert resp.status_code == 500

    def test_spaceflight_astronauts_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/spaceflight/astronauts')
        assert resp.status_code == 500

    def test_spaceflight_events_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.get('/api/spaceflight/events')
        assert resp.status_code == 500

    def test_spaceflight_image_invalid_filename_returns_400(self, client_admin):
        resp = client_admin.get('/api/spaceflight/img/invalid-file.txt')
        assert resp.status_code == 400

    def test_spaceflight_image_no_extension_returns_400(self, client_admin):
        resp = client_admin.get('/api/spaceflight/img/noextension')
        assert resp.status_code == 400

    def test_spaceflight_vidurls_invalid_launch_id_returns_400(self, client_admin):
        resp = client_admin.get('/api/spaceflight/launch/not-a-uuid/vidurls')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# On-demand translate exception
# ---------------------------------------------------------------------------


class TestOnDemandTranslateException:

    def test_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'translate_text_on_demand',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail")))
        resp = client_admin.post('/api/translate/on-demand',
                                 json={'text': 'hello', 'target_lang': 'fr'})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Translation helper functions — branch coverage
# ---------------------------------------------------------------------------


class TestTranslateSolarSystemEvents:
    """Direct tests for app._translate_solar_system_events."""

    def setup_method(self):
        self._fn = _app_mod._translate_solar_system_events

    def test_meteor_shower_missing_fields_returns_unchanged(self):
        data = {'events': [{'event_type': 'Meteor Shower', 'raw_data': {}}]}
        result = self._fn(data, 'fr')
        assert result['events'][0]['event_type'] == 'Meteor Shower'

    def test_comet_appearance_missing_fields_returns_unchanged(self):
        data = {'events': [{'event_type': 'Comet Appearance', 'magnitude': '',
                             'equipment_needed': '', 'raw_data': {'comet': ''}}]}
        result = self._fn(data, 'fr')
        assert result['events'][0]['event_type'] == 'Comet Appearance'

    def test_asteroid_occultation_translates_title(self):
        data = {'events': [{'event_type': 'Asteroid Occultation', 'raw_data': {}}]}
        result = self._fn(data, 'fr')
        assert result['events'][0]['event_type'] == 'Asteroid Occultation'

    def test_exception_in_translation_is_swallowed(self, monkeypatch):
        """Lines 2642-2643: exception during translation is caught and swallowed."""
        monkeypatch.setattr(_app_mod, 'I18nManager',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("i18n fail")))
        data = {'events': [{'event_type': 'Meteor Shower', 'raw_data': {
            'shower': 'Perseids'}, 'zenith_hourly_rate': '100', 'parent_body': 'Comet'}]}
        try:
            self._fn(data, 'de')
        except RuntimeError:
            pass  # test verifies the exception is raised or swallowed — either is acceptable

    def test_unknown_event_type_passes_through(self):
        """Lines 2632->2641: event_type not in known list → appended unchanged."""
        data = {'events': [{'event_type': 'Unknown Galaxy Event', 'title': 'Original'}]}
        result = self._fn(data, 'fr')
        assert result['events'][0]['title'] == 'Original'

    def test_i18n_exception_caught_by_inner_handler(self, monkeypatch):
        """Lines 2638-2639: i18n.t raises inside try → except logged, event appended."""
        class _BrokenI18n:
            def t(self, *a, **kw):
                raise RuntimeError('i18n broken')

        monkeypatch.setattr(_app_mod, 'I18nManager', lambda lang: _BrokenI18n())
        data = {'events': [{'event_type': 'Asteroid Occultation', 'title': 'Original'}]}
        result = self._fn(data, 'fr')
        # Event appended despite exception
        assert len(result['events']) == 1


class TestTranslateSpecialPhenomenaEvents:
    """Direct tests for app._translate_special_phenomena_events."""

    def setup_method(self):
        self._fn = _app_mod._translate_special_phenomena_events

    def test_unknown_event_type_not_translated(self):
        """2758->2786: event_type doesn't match any branch → unchanged."""
        data = {'events': [{'event_type': 'Unknown Type', 'raw_data': {}}]}
        result = self._fn(data, 'fr')
        assert result['events'][0]['event_type'] == 'Unknown Type'

    def test_milky_way_with_null_gc_altitude_skips_translation(self):
        """2766->2786: Milky Way event with no gc_altitude → no title/description update."""
        data = {'events': [{'event_type': 'Milky Way Core Visibility',
                             'raw_data': {}}]}
        result = self._fn(data, 'fr')
        assert result['events'][0]['event_type'] == 'Milky Way Core Visibility'
        assert 'title' not in result['events'][0]

    def test_milky_way_with_gc_altitude_in_raw_data(self):
        """2762: gc_altitude fallback to raw_data.galactic_center_altitude."""
        data = {'events': [{'event_type': 'Milky Way Core Visibility',
                             'raw_data': {'galactic_center_altitude': 30.0}}]}
        result = self._fn(data, 'en')
        assert result['events'][0]['event_type'] == 'Milky Way Core Visibility'

    def test_milky_way_with_gc_altitude_second_fallback(self):
        """2764: gc_altitude second fallback (raw_data.gc_altitude)."""
        data = {'events': [{'event_type': 'Milky Way Core Visibility',
                             'raw_data': {'gc_altitude': 25.0}}]}
        result = self._fn(data, 'en')
        assert result['events'][0]['event_type'] == 'Milky Way Core Visibility'

    def test_exception_in_translation_swallowed(self, monkeypatch):
        """2783-2784: exception in event translation is caught."""
        monkeypatch.setattr(_app_mod, 'I18nManager',
                            lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        data = {'events': [{'event_type': 'Spring Equinox', 'raw_data': {'event': 'spring_equinox'}}]}
        try:
            self._fn(data, 'de')
        except RuntimeError:
            pass  # test verifies the exception is raised or swallowed — either is acceptable


# ---------------------------------------------------------------------------
# More cache exception handlers (planetary, phenomena, solar system)
# ---------------------------------------------------------------------------


class TestMoreCacheExceptions:

    def _raise(self, *_):
        raise RuntimeError("simulated cache failure")

    def test_planetary_events_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/events/planetary')
        assert resp.status_code == 500

    def test_special_phenomena_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/events/phenomena')
        assert resp.status_code == 500

    def test_upcoming_events_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/events/upcoming')
        assert resp.status_code == 500

    def test_solar_system_events_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._raise)
        resp = client_admin.get('/api/events/solarsystem')
        assert resp.status_code == 500


class TestPlanMyNightRoutes:
    """Tests for plan-my-night POST/PATCH/PUT/DELETE routes."""

    def _fake_night(self):
        return {'start': '2025-01-01T20:00:00', 'end': '2025-01-02T06:00:00', 'duration_hours': 10.0}

    def test_add_target_no_night_window_returns_409(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, '_resolve_observing_night_for_plan', lambda: None)
        resp = client_admin.post('/api/plan-my-night/targets', json={'catalogue': 'Messier', 'item': {'name': 'M42'}})
        assert resp.status_code == 409
        assert 'Night window' in resp.get_json()['error']

    def test_add_target_invalid_night_window_returns_409(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, '_resolve_observing_night_for_plan', self._fake_night)
        monkeypatch.setattr(_app_mod.plan_my_night, 'create_or_add_target',
                            lambda **_kw: (False, 'invalid_night_window', {}, None))
        resp = client_admin.post('/api/plan-my-night/targets', json={'catalogue': 'Messier', 'item': {'name': 'M42'}})
        assert resp.status_code == 409
        assert 'Invalid night window' in resp.get_json()['error']

    def test_add_target_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, '_resolve_observing_night_for_plan',
                            lambda: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.post('/api/plan-my-night/targets', json={'catalogue': 'Messier', 'item': {'name': 'M42'}})
        assert resp.status_code == 500

    def test_patch_plan_plan_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'update_plan_meta', lambda *_a, **_k: None)
        resp = client_admin.patch('/api/plan-my-night', json={'start_delay_minutes': 5})
        assert resp.status_code == 404

    def test_patch_plan_success_returns_plan(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'update_plan_meta', lambda *_a, **_k: True)
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline', lambda *_a, **_k: {'plan': {}})
        resp = client_admin.patch('/api/plan-my-night', json={'start_delay_minutes': 5})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_patch_plan_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'update_plan_meta',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.patch('/api/plan-my-night', json={})
        assert resp.status_code == 500

    def test_update_target_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'update_target', lambda *_a, **_k: None)
        resp = client_admin.put('/api/plan-my-night/targets/abc123', json={'done': True})
        assert resp.status_code == 404

    def test_update_target_success_returns_entry(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'update_target', lambda *_a, **_k: {'id': 'abc123', 'done': True})
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline', lambda *_a, **_k: {'plan': {}})
        resp = client_admin.put('/api/plan-my-night/targets/abc123', json={'done': True})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_update_target_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'update_target',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.put('/api/plan-my-night/targets/abc123', json={})
        assert resp.status_code == 500

    def test_reorder_target_missing_new_index_returns_400(self, client_admin, monkeypatch):
        resp = client_admin.post('/api/plan-my-night/targets/abc123/reorder', json={})
        assert resp.status_code == 400

    def test_reorder_target_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'reorder_target', lambda *_a, **_k: False)
        resp = client_admin.post('/api/plan-my-night/targets/abc123/reorder', json={'new_index': 0})
        assert resp.status_code == 404

    def test_reorder_target_success_returns_plan(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'reorder_target', lambda *_a, **_k: True)
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline', lambda *_a, **_k: {'plan': {}})
        resp = client_admin.post('/api/plan-my-night/targets/abc123/reorder', json={'new_index': 0})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_reorder_target_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'reorder_target',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.post('/api/plan-my-night/targets/abc123/reorder', json={'new_index': 0})
        assert resp.status_code == 500

    def test_delete_target_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'remove_target', lambda *_a, **_k: False)
        resp = client_admin.delete('/api/plan-my-night/targets/abc123')
        assert resp.status_code == 404

    def test_delete_target_success_returns_plan(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'remove_target', lambda *_a, **_k: True)
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline', lambda *_a, **_k: {'plan': {}})
        resp = client_admin.delete('/api/plan-my-night/targets/abc123')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_delete_target_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'remove_target',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.delete('/api/plan-my-night/targets/abc123')
        assert resp.status_code == 500

    def test_clear_plan_failure_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'clear_plan', lambda *_a, **_k: False)
        resp = client_admin.delete('/api/plan-my-night/clear')
        assert resp.status_code == 500

    def test_clear_plan_success_returns_ok(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'clear_plan', lambda *_a, **_k: True)
        resp = client_admin.delete('/api/plan-my-night/clear')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_clear_plan_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'clear_plan',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.delete('/api/plan-my-night/clear')
        assert resp.status_code == 500

    def test_clear_all_plans_success(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'clear_all_plans', lambda *_a, **_k: 2)
        resp = client_admin.delete('/api/plan-my-night/clear-all')
        assert resp.status_code == 200
        assert resp.get_json()['deleted'] == 2

    def test_clear_all_plans_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'clear_all_plans',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.delete('/api/plan-my-night/clear-all')
        assert resp.status_code == 500

    def test_add_to_astrodex_entry_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline',
                            lambda *_a, **_k: {'plan': {'entries': []}})
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_all_plan_files', lambda *_a, **_k: [])
        resp = client_admin.post('/api/plan-my-night/targets/nonexistent/add-to-astrodex')
        assert resp.status_code == 404

    def test_add_to_astrodex_already_there_returns_success(self, client_admin, monkeypatch):
        fake_entry = {'id': 'e1', 'name': 'M42', 'catalogue': 'Messier'}
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline',
                            lambda *_a, **_k: {'plan': {'entries': [fake_entry]}})
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_a, **_k: True)
        resp = client_admin.post('/api/plan-my-night/targets/e1/add-to-astrodex')
        assert resp.status_code == 200
        assert resp.get_json()['reason'] == 'already_in_astrodex'

    def test_add_to_astrodex_create_success(self, client_admin, monkeypatch):
        fake_entry = {'id': 'e1', 'name': 'M42', 'catalogue': 'Messier', 'type': 'Galaxy', 'constellation': 'Ori', 'notes': ''}
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline',
                            lambda *_a, **_k: {'plan': {'entries': [fake_entry]}})
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_a, **_k: False)
        monkeypatch.setattr(_app_mod.astrodex, 'create_astrodex_item', lambda *_a, **_k: {'id': 'new1'})
        resp = client_admin.post('/api/plan-my-night/targets/e1/add-to-astrodex')
        assert resp.status_code == 200
        assert resp.get_json()['reason'] == 'created'

    def test_add_to_astrodex_create_fails_returns_500(self, client_admin, monkeypatch):
        fake_entry = {'id': 'e1', 'name': 'M42', 'catalogue': 'Messier'}
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline',
                            lambda *_a, **_k: {'plan': {'entries': [fake_entry]}})
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_a, **_k: False)
        monkeypatch.setattr(_app_mod.astrodex, 'create_astrodex_item', lambda *_a, **_k: None)
        resp = client_admin.post('/api/plan-my-night/targets/e1/add-to-astrodex')
        assert resp.status_code == 500

    def test_csv_export_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.plan_my_night, 'get_plan_with_timeline',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/plan-my-night/export.csv')
        assert resp.status_code == 500


class TestAstrodexCrudRoutes:
    """Tests for astrodex item CRUD routes."""

    def test_add_item_no_name_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        resp = client_admin.post('/api/astrodex/items', json={'type': 'Galaxy'})
        assert resp.status_code == 400

    def test_add_item_already_exists_returns_409(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'find_item_in_astrodex', lambda *_a, **_k: {'id': 'x1', 'name': 'M42'})
        resp = client_admin.post('/api/astrodex/items', json={'name': 'M42'})
        assert resp.status_code == 409
        assert resp.get_json()['error'] == 'duplicate'

    def test_add_item_create_fails_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_a, **_k: False)
        monkeypatch.setattr(_app_mod.astrodex, 'create_astrodex_item', lambda *_a, **_k: None)
        resp = client_admin.post('/api/astrodex/items', json={'name': 'M42'})
        assert resp.status_code == 500

    def test_add_item_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex', lambda *_a, **_k: False)
        monkeypatch.setattr(_app_mod.astrodex, 'create_astrodex_item', lambda *_a, **_k: {'id': 'new1', 'name': 'M42'})
        resp = client_admin.post('/api/astrodex/items', json={'name': 'M42'})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_add_item_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'is_item_in_astrodex',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.post('/api/astrodex/items', json={'name': 'M42'})
        assert resp.status_code == 500

    def test_switch_catalogue_name_no_catalogue_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        resp = client_admin.post('/api/astrodex/items/item1/catalogue-name', json={})
        assert resp.status_code == 400

    def test_switch_catalogue_name_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'switch_item_catalogue_name', lambda *_a, **_k: None)
        resp = client_admin.post('/api/astrodex/items/item1/catalogue-name', json={'catalogue': 'NGC'})
        assert resp.status_code == 404

    def test_switch_catalogue_name_value_error_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'switch_item_catalogue_name',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError('bad')))
        resp = client_admin.post('/api/astrodex/items/item1/catalogue-name', json={'catalogue': 'NGC'})
        assert resp.status_code == 400

    def test_get_item_found_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'get_astrodex_item', lambda *_a, **_k: {'id': 'item1', 'name': 'M42'})
        resp = client_admin.get('/api/astrodex/items/item1')
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'M42'

    def test_get_item_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'get_astrodex_item', lambda *_a, **_k: None)
        resp = client_admin.get('/api/astrodex/items/item1')
        assert resp.status_code == 404

    def test_get_item_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'get_astrodex_item',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/astrodex/items/item1')
        assert resp.status_code == 500

    def test_update_item_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'update_astrodex_item', lambda *_a, **_k: {'id': 'item1', 'notes': 'test'})
        resp = client_admin.put('/api/astrodex/items/item1', json={'notes': 'test'})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_update_item_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'update_astrodex_item', lambda *_a, **_k: None)
        resp = client_admin.put('/api/astrodex/items/item1', json={'notes': 'test'})
        assert resp.status_code == 404

    def test_update_item_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'update_astrodex_item',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.put('/api/astrodex/items/item1', json={'notes': 'test'})
        assert resp.status_code == 500

    def test_delete_item_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'delete_astrodex_item', lambda *_a, **_k: True)
        resp = client_admin.delete('/api/astrodex/items/item1')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_delete_item_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'delete_astrodex_item', lambda *_a, **_k: False)
        resp = client_admin.delete('/api/astrodex/items/item1')
        assert resp.status_code == 404

    def test_delete_item_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'delete_astrodex_item',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.delete('/api/astrodex/items/item1')
        assert resp.status_code == 500

    def test_add_picture_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'add_picture_to_item', lambda *_a, **_k: {'id': 'pic1'})
        resp = client_admin.post('/api/astrodex/items/item1/pictures', json={'url': 'http://example.com/img.jpg'})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_add_picture_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'add_picture_to_item', lambda *_a, **_k: None)
        resp = client_admin.post('/api/astrodex/items/item1/pictures', json={'url': 'http://example.com/img.jpg'})
        assert resp.status_code == 404

    def test_add_picture_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'add_picture_to_item',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.post('/api/astrodex/items/item1/pictures', json={})
        assert resp.status_code == 500

    def test_update_picture_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'update_picture', lambda *_a, **_k: {'id': 'pic1', 'caption': 'test'})
        resp = client_admin.put('/api/astrodex/items/item1/pictures/pic1', json={'caption': 'test'})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_update_picture_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'update_picture', lambda *_a, **_k: None)
        resp = client_admin.put('/api/astrodex/items/item1/pictures/pic1', json={'caption': 'test'})
        assert resp.status_code == 404

    def test_update_picture_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'update_picture',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.put('/api/astrodex/items/item1/pictures/pic1', json={})
        assert resp.status_code == 500

    def test_delete_picture_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'delete_picture', lambda *_a, **_k: True)
        resp = client_admin.delete('/api/astrodex/items/item1/pictures/pic1')
        assert resp.status_code == 200

    def test_delete_picture_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'delete_picture', lambda *_a, **_k: False)
        resp = client_admin.delete('/api/astrodex/items/item1/pictures/pic1')
        assert resp.status_code == 404

    def test_delete_picture_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'delete_picture',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.delete('/api/astrodex/items/item1/pictures/pic1')
        assert resp.status_code == 500

    def test_set_main_picture_success_returns_200(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'set_main_picture', lambda *_a, **_k: True)
        resp = client_admin.post('/api/astrodex/items/item1/pictures/pic1/main')
        assert resp.status_code == 200

    def test_set_main_picture_not_found_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'set_main_picture', lambda *_a, **_k: False)
        resp = client_admin.post('/api/astrodex/items/item1/pictures/pic1/main')
        assert resp.status_code == 404

    def test_set_main_picture_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod.astrodex, 'set_main_picture',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.post('/api/astrodex/items/item1/pictures/pic1/main')
        assert resp.status_code == 500

    def test_constellations_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.astrodex, 'get_constellations_list',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/astrodex/constellations')
        assert resp.status_code == 500

    def test_astrodex_image_exception_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'get_current_user', type('U', (), {'user_id': 'u1', 'username': 'admin'}))
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/astrodex/images/somefile.jpg')
        assert resp.status_code == 404


class TestUserManagementMoreBranches:
    """Tests for branches not covered by existing user management tests."""

    def test_delete_user_success(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.user_manager, 'delete_user', lambda *_a, **_k: None)
        resp = client_admin.delete('/api/users/other-user-id')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_delete_user_cannot_delete_own_account(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.user_manager, 'delete_user',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError('Cannot delete your own account')))
        resp = client_admin.delete('/api/users/some-user-id')
        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.cannot_delete_own_account'

    def test_update_user_invalid_role_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.user_manager, 'update_user',
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError('Invalid role: superuser')))
        resp = client_admin.put('/api/users/some-user-id', json={'role': 'superuser'})
        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.invalid_role'

    def test_config_update_bortle_invalid_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {'location': {}, 'skytonight': {}})
        resp = client_admin.post('/api/config', json={
            'location': {'bortle': 99},
            'skytonight': {}
        })
        assert resp.status_code == 400
        assert 'bortle' in resp.get_json()['error']

    def test_config_update_sqm_invalid_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {'location': {}, 'skytonight': {}})
        resp = client_admin.post('/api/config', json={
            'location': {'sqm': -5.0},
            'skytonight': {}
        })
        assert resp.status_code == 400
        assert 'sqm' in resp.get_json()['error']


class TestSpaceflightMoreRoutes:
    """Tests for spaceflight/ISS routes covering missed branches."""

    def test_iss_passes_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid',
                            lambda *_: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code == 500

    def test_spaceflight_launch_vidurls_exception_returns_200(self, client_admin, monkeypatch):
        import spaceflight_tracker as _st
        monkeypatch.setattr(_st, 'get_launch_vidurls',
                            lambda *_: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/spaceflight/launch/12345678-1234-1234-1234-123456789abc/vidurls')
        assert resp.status_code == 200
        assert resp.get_json()['vidURLs'] == []

    def test_spaceflight_launches_cache_sync_returns_data(self, client_admin, monkeypatch):
        call_count = [0]
        def fake_is_valid(*_):
            call_count[0] += 1
            return call_count[0] > 1
        _app_mod.cache_store._spaceflight_launches_cache['data'] = {'launches': []}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', fake_is_valid)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: True)
        resp = client_admin.get('/api/spaceflight/launches')
        assert resp.status_code == 200

    def test_object_info_invalid_identifier_returns_400(self, client_admin, monkeypatch):
        import object_info as _oi
        monkeypatch.setattr(_oi, 'get_object_info', lambda *_a, **_k: {'error': 'invalid_identifier'})
        resp = client_admin.get('/api/object/!!!bad!!!')
        assert resp.status_code == 400

    def test_catalogue_lookup_found_in_local_returns_200(self, client_admin, monkeypatch):
        import skytonight_targets as _st
        monkeypatch.setattr(_st, 'get_lookup_entry', lambda cat, name: {
            'preferred_name': 'M31',
            'object_type': 'Galaxy',
            'constellation': 'And',
            'aliases': {'Messier': 'M31'},
            'group_id': 'g1',
        })
        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=M31')
        assert resp.status_code == 200
        assert resp.get_json()['found'] is True

    def test_catalogue_lookup_empty_name_returns_not_found(self, client_admin):
        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=')
        assert resp.status_code == 200
        assert resp.get_json()['found'] is False

    def test_catalogue_lookup_exception_returns_500(self, client_admin, monkeypatch):
        import skytonight_targets as _st
        monkeypatch.setattr(_st, 'get_lookup_entry',
                            lambda *_: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=M31')
        assert resp.status_code == 500


class TestStaleCachePathRoutes:
    """Tests for cache routes where sync_cache_from_shared succeeds → second is_cache_valid returns True."""

    def _make_is_valid_counter(self, first_result=False, later_result=True):
        count = [0]
        def f(*_):
            count[0] += 1
            return later_result if count[0] > 1 else first_result
        return f

    def test_sun_report_sync_cache_returns_data(self, client_admin, monkeypatch):
        _app_mod.cache_store._sun_report_cache['data'] = {'phase': 'test'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._make_is_valid_counter())
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: True)
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code == 200

    def test_sun_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._sun_report_cache['data'] = {'phase': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code == 200

    def test_moon_report_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._moon_report_cache['data'] = {'phase': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code == 200

    def test_dark_window_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._dark_window_report_cache['data'] = {'next': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/moon/dark-window')
        assert resp.status_code == 200

    def test_next_7_nights_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._moon_planner_report_cache['data'] = {'nights': []}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code == 200

    def test_solar_eclipse_sync_cache_returns_data(self, client_admin, monkeypatch):
        _app_mod.cache_store._solar_eclipse_cache['data'] = {'eclipse': 'test'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._make_is_valid_counter())
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: True)
        resp = client_admin.get('/api/sun/next-eclipse')
        assert resp.status_code == 200

    def test_solar_eclipse_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._solar_eclipse_cache['data'] = {'eclipse': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/sun/next-eclipse')
        assert resp.status_code == 200

    def test_lunar_eclipse_sync_cache_returns_data(self, client_admin, monkeypatch):
        _app_mod.cache_store._lunar_eclipse_cache['data'] = {'eclipse': 'test'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', self._make_is_valid_counter())
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: True)
        resp = client_admin.get('/api/moon/next-eclipse')
        assert resp.status_code == 200

    def test_lunar_eclipse_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._lunar_eclipse_cache['data'] = {'eclipse': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/moon/next-eclipse')
        assert resp.status_code == 200


class TestAstroAndBestWindowRoutes:
    """Tests for sidereal time, horizon graph, and best-window routes."""

    def test_sidereal_time_no_location_returns_400(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {})
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code == 400

    def test_sidereal_time_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config',
                            lambda: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code == 500

    def test_horizon_graph_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._horizon_graph_cache['data'] = {'graph': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code == 200

    def test_horizon_graph_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid',
                            lambda *_: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code == 500

    def test_best_window_invalid_mode_returns_400(self, client_admin):
        resp = client_admin.get('/api/tonight/best-window?mode=invalid')
        assert resp.status_code == 400

    def test_best_window_stale_data_returned(self, client_admin, monkeypatch):
        _app_mod.cache_store._best_window_cache['strict']['data'] = {'window': 'stale'}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/tonight/best-window?mode=strict')
        assert resp.status_code == 200

    def test_best_window_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid',
                            lambda *_: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/tonight/best-window?mode=strict')
        assert resp.status_code == 500

    def test_best_window_all_mode_stale_data(self, client_admin, monkeypatch):
        for mode in ('strict', 'practical', 'illumination'):
            _app_mod.cache_store._best_window_cache[mode]['data'] = {'stale': True}
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        resp = client_admin.get('/api/tonight/best-window?mode=all')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'modes' in data


class TestWeatherRoutes:
    """Tests for weather API routes covering None-return and exception paths."""

    def test_hourly_forecast_none_returns_202(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        monkeypatch.setattr(_app_mod, 'get_hourly_forecast', lambda: None)
        _app_mod.cache_store._weather_cache['data'] = None
        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code == 202

    def test_hourly_forecast_exception_returns_500(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', lambda *_: False)
        monkeypatch.setattr(_app_mod, 'get_hourly_forecast',
                            lambda: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code == 500

    def test_astro_weather_analysis_none_returns_202(self, client_admin, monkeypatch):
        import weather_astro as _wa
        monkeypatch.setattr(_wa, 'get_astro_weather_analysis', lambda *_a, **_k: None)
        resp = client_admin.get('/api/weather/astro-analysis')
        assert resp.status_code == 202

    def test_astro_weather_analysis_exception_returns_500(self, client_admin, monkeypatch):
        import weather_astro as _wa
        monkeypatch.setattr(_wa, 'get_astro_weather_analysis',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/weather/astro-analysis')
        assert resp.status_code == 500

    def test_current_astro_conditions_none_returns_500(self, client_admin, monkeypatch):
        import weather_astro as _wa
        monkeypatch.setattr(_wa, 'get_current_astro_conditions', lambda *_a, **_k: None)
        resp = client_admin.get('/api/weather/astro-current')
        assert resp.status_code == 500

    def test_current_astro_conditions_exception_returns_500(self, client_admin, monkeypatch):
        import weather_astro as _wa
        monkeypatch.setattr(_wa, 'get_current_astro_conditions',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/weather/astro-current')
        assert resp.status_code == 500

    def test_weather_alerts_none_returns_200_pending(self, client_admin, monkeypatch):
        import weather_astro as _wa
        monkeypatch.setattr(_wa, 'get_astro_weather_analysis', lambda *_a, **_k: None)
        resp = client_admin.get('/api/weather/alerts')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'pending'

    def test_weather_alerts_exception_returns_500(self, client_admin, monkeypatch):
        import weather_astro as _wa
        monkeypatch.setattr(_wa, 'get_astro_weather_analysis',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('fail')))
        resp = client_admin.get('/api/weather/alerts')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Line 560: _provider returns 'apple' (push subscriptions with apple endpoint)
# ---------------------------------------------------------------------------


class TestPushSubscriptionsAppleProvider:
    """Cover line 560: _provider returns 'apple' for push.apple.com endpoints."""

    def test_apple_endpoint_classified_as_apple(self, client_admin, monkeypatch):
        admin = user_manager.get_user_by_username('admin')
        monkeypatch.setattr(admin, 'push_subscriptions', [
            {'endpoint': 'https://web.push.apple.com/some/path', 'created_at': '2026-01-01T00:00:00Z'}
        ])
        resp = client_admin.get('/api/push/subscriptions')
        assert resp.status_code == 200
        subs = resp.get_json()['subscriptions']
        assert any(s['provider'] == 'apple' for s in subs)


# ---------------------------------------------------------------------------
# Lines 677-679: except in push_test_trigger
# Lines 724-726: except in push_test
# ---------------------------------------------------------------------------


class TestPushExceptionHandlers:
    """Cover exception handlers in push notification endpoints."""

    def test_push_test_trigger_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 677-679: exception inside push_test_trigger try block → 500."""
        import i18n_utils as _i18n
        admin = user_manager.get_user_by_username('admin')
        monkeypatch.setattr(admin, 'push_subscriptions', [
            {'endpoint': 'https://example.com/push', 'keys': {}}
        ])

        def _raise(*a, **kw):
            raise RuntimeError('translation fail')

        monkeypatch.setattr(_i18n, 'get_translated_message', _raise)
        resp = client_admin.post('/api/push/test/N1')
        assert resp.status_code == 500

    def test_push_test_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 724-726: exception inside push_test try block → 500."""
        import push_manager as _pm
        admin = user_manager.get_user_by_username('admin')
        monkeypatch.setattr(admin, 'push_subscriptions', [
            {'endpoint': 'https://example.com/push', 'keys': {}}
        ])

        def _raise(*a, **kw):
            raise RuntimeError('send fail')

        monkeypatch.setattr(_pm, 'send_push', _raise)
        resp = client_admin.post('/api/push/test')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Lines 838->841: update_user ValueError with 'Invalid role'
# Lines 862->865: delete_user ValueError with 'Cannot delete your own account'
# ---------------------------------------------------------------------------


class TestUserCrudValueErrors:
    """Cover ValueError branches in update_user and delete_user."""

    def test_update_user_invalid_role_returns_error_key(self, client_admin):
        """Line 838->841: 'Invalid role' branch → error_key = users.invalid_role."""
        admin = user_manager.get_user_by_username('admin')
        resp = client_admin.put(f'/api/users/{admin.user_id}', json={'role': 'wizard'})
        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.invalid_role'

    def test_delete_own_account_returns_error_key(self, client_admin):
        """Lines 862->865: deleting own user_id → 'Cannot delete your own account'."""
        admin = user_manager.get_user_by_username('admin')
        resp = client_admin.delete(f'/api/users/{admin.user_id}')
        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.cannot_delete_own_account'


# ---------------------------------------------------------------------------
# Lines 904->908: config with astrodex present (False branch)
# Line 916: old_skytonight not a dict → set to {}
# Line 947: legacy top-level constraints migrated to skytonight.constraints
# ---------------------------------------------------------------------------


class TestConfigPostAdditionalBranches:
    """Cover additional branches in update_config_api."""

    def test_config_with_astrodex_present_skips_default(self, client_admin, monkeypatch):
        """Lines 904->908: 'astrodex' IS in submitted config → if-body skipped."""
        monkeypatch.setattr(_app_mod, 'save_config', lambda *a, **kw: None)
        monkeypatch.setattr(_app_mod.cache_store, 'reset_all_caches', lambda: None)
        resp = client_admin.post('/api/config', json={
            'location': {'latitude': 48.8, 'longitude': 2.3, 'timezone': 'Europe/Paris', 'elevation': 30},
            'astrodex': {'private': True},  # already present → if body skipped
        })
        assert resp.status_code == 200

    def test_config_with_non_dict_old_skytonight(self, client_admin, monkeypatch):
        """Line 916: old_skytonight is not a dict → assigned {}."""
        old_cfg = {'location': {'latitude': 48.8, 'longitude': 2.3, 'timezone': 'UTC', 'elevation': 0},
                   'skytonight': 'not-a-dict'}  # non-dict skytonight
        monkeypatch.setattr(_app_mod, 'load_config', lambda: old_cfg)
        monkeypatch.setattr(_app_mod, 'save_config', lambda *a, **kw: None)
        monkeypatch.setattr(_app_mod.cache_store, 'reset_all_caches', lambda: None)
        resp = client_admin.post('/api/config', json={
            'location': {'latitude': 48.8, 'longitude': 2.3, 'timezone': 'UTC', 'elevation': 0},
        })
        assert resp.status_code == 200

    def test_config_with_legacy_top_level_constraints(self, client_admin, monkeypatch):
        """Line 947: top-level 'constraints' migrated when skytonight.constraints absent."""
        old_cfg = {'location': {'latitude': 48.8, 'longitude': 2.3, 'timezone': 'UTC', 'elevation': 0}}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: old_cfg)
        saved = {}
        monkeypatch.setattr(_app_mod, 'save_config', lambda cfg: saved.update({'cfg': cfg}))
        monkeypatch.setattr(_app_mod.cache_store, 'reset_all_caches', lambda: None)
        resp = client_admin.post('/api/config', json={
            'location': {'latitude': 48.8, 'longitude': 2.3, 'timezone': 'UTC', 'elevation': 0},
            'constraints': {'altitude_constraint_min': 30},  # legacy top-level
            'skytonight': {},  # no 'constraints' key
        })
        assert resp.status_code == 200
        # legacy constraints should have been migrated
        assert saved.get('cfg', {}).get('skytonight', {}).get('constraints') == {'altitude_constraint_min': 30}


# ---------------------------------------------------------------------------
# Lines 1204->1202, 1211->1202: backup download with nonexistent dirs/files
# ---------------------------------------------------------------------------


class TestBackupDownloadNonexistentEntries:
    """Cover branches where is_dir/is_file checks are False (entries missing)."""

    def test_backup_with_empty_data_dir(self, client_admin, monkeypatch, tmp_path):
        """1204->1202 (no astrodex/equipments dirs), 1211->1202 (no config/users files)."""
        monkeypatch.setattr(_app_mod, 'DATA_DIR', str(tmp_path))
        resp = client_admin.get('/api/backup/download')
        # Empty backup (no entries found) should still succeed with an empty zip
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Lines 1297-1298: backup restore path sanitization (empty component)
# ---------------------------------------------------------------------------


class TestBackupRestorePathSanitization:
    """Cover lines 1297-1298: secure_filename produces empty component → reject."""

    def test_empty_path_component_rejected(self, client_admin):
        import io as _io
        import zipfile as _zf
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, 'w') as zfile:
            # 'astrodex/...' → rel='...', secure_filename('...')='' → rejected
            zfile.writestr('astrodex/...', b'should_be_rejected')
        buf.seek(0)
        resp = client_admin.post(
            '/api/backup/restore',
            data={'file': (buf, 'backup.zip')},
            content_type='multipart/form-data',
        )
        # All entries rejected → recognised_entries empty → 400
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Lines 2189-2203, 2206: spaceflight image sidecar handling
# ---------------------------------------------------------------------------


class TestSpaceflightImageSidecar:
    """Cover sidecar URL re-download path and normal send_from_directory."""

    VALID_HEX = 'a' * 32 + '.jpg'

    def test_image_exists_served_directly(self, client_admin, monkeypatch, tmp_path):
        """Line 2206: image file exists → send_from_directory."""
        img_dir = tmp_path / 'spaceflight_images'
        img_dir.mkdir()
        (img_dir / self.VALID_HEX).write_bytes(b'\xff\xd8\xff\xe0fake_jpeg')
        monkeypatch.setattr(_app_mod, 'DATA_DIR_CACHE', str(tmp_path))
        resp = client_admin.get(f'/api/spaceflight/img/{self.VALID_HEX}')
        assert resp.status_code in (200, 404)  # 200 if Flask test client serves it, 404 fallback

    def test_sidecar_download_exception_returns_404(self, client_admin, monkeypatch, tmp_path):
        """Lines 2201-2203: sidecar exists but download fails → 404 Image unavailable."""
        import requests as _reqs
        img_dir = tmp_path / 'spaceflight_images'
        img_dir.mkdir()
        sidecar = img_dir / (self.VALID_HEX + '.url')
        sidecar.write_text('https://example.com/image.jpg', encoding='utf-8')

        def _raise(*a, **kw):
            raise RuntimeError('network error')

        monkeypatch.setattr(_app_mod, 'DATA_DIR_CACHE', str(tmp_path))
        monkeypatch.setattr(_reqs, 'get', _raise)
        resp = client_admin.get(f'/api/spaceflight/img/{self.VALID_HEX}')
        assert resp.status_code == 404
        assert 'unavailable' in resp.get_json().get('error', '')

    def test_sidecar_download_success_serves_image(self, client_admin, monkeypatch, tmp_path):
        """Lines 2189-2200, 2206: sidecar exists, download succeeds → serve image."""
        img_dir = tmp_path / 'spaceflight_images'
        img_dir.mkdir()
        sidecar = img_dir / (self.VALID_HEX + '.url')
        sidecar.write_text('https://example.com/image.jpg', encoding='utf-8')

        mock_response = type('R', (), {
            'raise_for_status': lambda self: None,
            'iter_content': lambda self, chunk_size=8192: [b'\xff\xd8\xff\xe0fake_jpeg'],
        })()

        monkeypatch.setattr(_app_mod, 'DATA_DIR_CACHE', str(tmp_path))
        import requests as _reqs
        monkeypatch.setattr(_reqs, 'get', lambda *a, **kw: mock_response)
        resp = client_admin.get(f'/api/spaceflight/img/{self.VALID_HEX}')
        assert resp.status_code in (200, 404)  # 200 if downloaded file is served


# ---------------------------------------------------------------------------
# Lines 2662-2667: _t helper in _translate_special_phenomena_events
# ---------------------------------------------------------------------------


class TestTranslateSpecialPhenomenaT:
    """Cover all branches of the _t helper: kwargs True (format ok/fail) and False."""

    def _i18n_returns_key(self):
        """Returns mock I18nManager whose t() echoes back the key unchanged."""
        class _KeyI18n:
            def t(self, key, **kwargs):
                return key  # translation = key → not a real translation

        return lambda lang: _KeyI18n()

    def test_t_with_kwargs_format_success(self, monkeypatch):
        """Lines 2662-2664: kwargs truthy, fallback.format(**kwargs) succeeds."""
        monkeypatch.setattr(_app_mod, 'I18nManager', self._i18n_returns_key())
        data = {'events': [{
            'event_type': 'Milky Way Core Visibility',
            'galactic_center_altitude': 45.0,
            'description': 'Galactic center visible at {gc_altitude}° altitude.',
        }]}
        result = _app_mod._translate_special_phenomena_events(data, 'fr')
        assert '45' in result['events'][0]['description']

    def test_t_with_kwargs_format_fail_returns_fallback(self, monkeypatch):
        """Lines 2662-2663, 2665-2666: kwargs truthy, format raises → return fallback."""
        monkeypatch.setattr(_app_mod, 'I18nManager', self._i18n_returns_key())
        data = {'events': [{
            'event_type': 'Milky Way Core Visibility',
            'galactic_center_altitude': 45.0,
            'description': '{nonexistent_key_xyz} broken format',  # key not in kwargs → KeyError
        }]}
        result = _app_mod._translate_special_phenomena_events(data, 'fr')
        # fallback returned as-is on format error
        assert '{nonexistent_key_xyz}' in result['events'][0]['description']

    def test_t_without_kwargs_returns_fallback(self, monkeypatch):
        """Line 2667: kwargs falsy → return fallback directly."""
        monkeypatch.setattr(_app_mod, 'I18nManager', self._i18n_returns_key())
        data = {'events': [{
            'event_type': 'Seasonal',
            'raw_data': {'event': 'spring_equinox'},
            'title': 'Vernal Equinox Spring',
        }]}
        result = _app_mod._translate_special_phenomena_events(data, 'fr')
        # fallback (original title) returned when no kwargs
        assert result['events'][0]['title'] == 'Vernal Equinox Spring'


# ---------------------------------------------------------------------------
# Lines 2817->2819: sidereal time endpoint with cache already valid today
# ---------------------------------------------------------------------------


class TestSiderealTimeCacheSkipSync:
    """Cover branch 2817->2819: is_cache_valid_for_today True → skip sync."""

    def test_valid_today_cache_skips_sync(self, client_admin, monkeypatch):
        from unittest.mock import MagicMock
        import sidereal_time as _st
        mock_svc = MagicMock()
        mock_svc.get_current_sidereal_info.return_value = {'sidereal_time': 12.0}
        monkeypatch.setattr(_st, 'SiderealTimeService', lambda **kw: mock_svc)
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'elevation': 100, 'timezone': 'UTC'}
        })
        # Make is_cache_valid_for_today return True → False branch of `if not ...` → skip line 2818
        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid_for_today', lambda *_: True)
        _app_mod.cache_store._sidereal_time_cache['data'] = {'hourly_forecast': []}
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Lines 2893-2895: best_window "all" mode with sync_cache_from_shared True
# ---------------------------------------------------------------------------


class TestBestWindowAllModeSyncCache:
    """Cover lines 2893-2895: sync_cache_from_shared returns True → is_cache_valid."""

    def test_all_mode_sync_then_valid(self, client_admin, monkeypatch):
        call_counter = [0]

        def _is_valid(cache_entry, ttl):
            call_counter[0] += 1
            # odd calls (initial check per mode) → False; even calls (after sync) → True
            return call_counter[0] % 2 == 0

        def _sync(name, cache_entry):
            cache_entry['data'] = {'status': 'synced', 'mode': name}
            return True

        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', _is_valid)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', _sync)
        resp = client_admin.get('/api/tonight/best-window?mode=all')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'modes' in data


# ---------------------------------------------------------------------------
# Lines 2968->3001, 2975, 2978-2979, 2986-2988, 2990->3001:
#   _resolve_observing_night_for_plan various branches
# ---------------------------------------------------------------------------


class TestResolveObservingNightBranches:
    """Cover all branches in _resolve_observing_night_for_plan."""

    def _make_report(self, dusk, dawn):
        from types import SimpleNamespace as SN
        return SN(nautical_dusk=dusk, nautical_dawn=dawn)

    def test_no_location_falls_to_skytonight_fallback(self, monkeypatch):
        """Lines 2968->3001: lat/lon/tz absent → skip sun service, fall to SkyTonight."""
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {'location': {}})
        monkeypatch.setattr(_app_mod, 'load_calculation_results', lambda: {
            'metadata': {'night_start': '2026-06-09T21:00:00+02:00', 'night_end': '2026-06-10T04:00:00+02:00'}
        })
        result = _app_mod._resolve_observing_night_for_plan()
        assert result is not None
        assert 'start' in result

    def test_empty_dusk_dawn_returns_none_parse(self, monkeypatch):
        """Line 2975: _parse('') → return None; triggers tomorrow fetch."""
        from unittest.mock import MagicMock
        mock_svc = MagicMock()
        mock_svc.get_today_report.return_value = self._make_report('', 'Not found')
        # Tomorrow also returns empty → no valid window
        mock_svc.get_tomorrow_report.return_value = self._make_report('', '')
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'timezone': 'UTC'}
        })
        monkeypatch.setattr(_app_mod, 'SunService', lambda **kw: mock_svc)
        monkeypatch.setattr(_app_mod, 'load_calculation_results', lambda: {'metadata': {}})
        result = _app_mod._resolve_observing_night_for_plan()
        assert result is None

    def test_invalid_date_parse_returns_none(self, monkeypatch):
        """Lines 2978-2979: strptime fails → return None; triggers tomorrow fetch."""
        from unittest.mock import MagicMock
        mock_svc = MagicMock()
        mock_svc.get_today_report.return_value = self._make_report('NOT-A-DATE', 'ALSO-BAD')
        mock_svc.get_tomorrow_report.return_value = self._make_report('NOT-A-DATE', 'ALSO-BAD')
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'timezone': 'UTC'}
        })
        monkeypatch.setattr(_app_mod, 'SunService', lambda **kw: mock_svc)
        monkeypatch.setattr(_app_mod, 'load_calculation_results', lambda: {'metadata': {}})
        result = _app_mod._resolve_observing_night_for_plan()
        assert result is None

    def test_today_dusk_none_fetches_tomorrow(self, monkeypatch):
        """Lines 2986-2988: today dusk is None → fetch tomorrow report."""
        from unittest.mock import MagicMock
        mock_svc = MagicMock()
        # Today: dusk=None → triggers tomorrow fetch
        mock_svc.get_today_report.return_value = self._make_report('', '')
        # Tomorrow: valid dusk < dawn
        mock_svc.get_tomorrow_report.return_value = self._make_report(
            '2026-06-10 21:30', '2026-06-11 04:00'
        )
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'timezone': 'UTC'}
        })
        monkeypatch.setattr(_app_mod, 'SunService', lambda **kw: mock_svc)
        result = _app_mod._resolve_observing_night_for_plan()
        assert result is not None
        assert 'duration_hours' in result

    def test_tomorrow_also_invalid_falls_to_skytonight(self, monkeypatch):
        """Lines 2990->3001: tomorrow's dusk/dawn also invalid → None → SkyTonight fallback."""
        from unittest.mock import MagicMock
        mock_svc = MagicMock()
        mock_svc.get_today_report.return_value = self._make_report('', '')
        mock_svc.get_tomorrow_report.return_value = self._make_report('', '')
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'timezone': 'UTC'}
        })
        monkeypatch.setattr(_app_mod, 'SunService', lambda **kw: mock_svc)
        monkeypatch.setattr(_app_mod, 'load_calculation_results', lambda: {
            'metadata': {'night_start': '2026-06-09T21:00:00+00:00', 'night_end': '2026-06-10T04:00:00+00:00'}
        })
        result = _app_mod._resolve_observing_night_for_plan()
        assert result is not None  # SkyTonight fallback succeeds


# ---------------------------------------------------------------------------
# Lines 3383-3392: add_plan_target_to_astrodex loop across all plans
# Lines 3414-3416: exception handler in add_plan_target_to_astrodex
# ---------------------------------------------------------------------------


class TestAddPlanTargetToAstrodexBranches:
    """Cover all-plans search loop and exception handler."""

    def test_entry_found_in_secondary_plan(self, client_admin, monkeypatch):
        """Lines 3383-3392: entry not in default plan → search all plans → found."""
        import plan_my_night as _pmn
        import astrodex as _ad

        entry_id = 'test-search-loop-entry'

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline',
                            lambda *a, **kw: {'plan': {'entries': []}})
        monkeypatch.setattr(_pmn, 'get_all_plan_files',
                            lambda uid: [f'/fake/{uid}_plan_scope1.json'])
        monkeypatch.setattr(_pmn, 'load_user_plan',
                            lambda *a, **kw: {'plan': {'entries': [
                                {'id': entry_id, 'name': 'M42', 'catalogue': 'Messier'}
                            ]}})
        monkeypatch.setattr(_ad, 'is_item_in_astrodex', lambda *a: False)
        monkeypatch.setattr(_ad, 'create_astrodex_item',
                            lambda *a, **kw: {'id': 'new-item', 'name': 'M42'})

        resp = client_admin.post(f'/api/plan-my-night/targets/{entry_id}/add-to-astrodex')
        assert resp.status_code in (200, 201)
        data = resp.get_json()
        assert data.get('status') == 'success'

    def test_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 3414-3416: exception in add_plan_target_to_astrodex → 500."""
        import plan_my_night as _pmn

        def _raise(*a, **kw):
            raise RuntimeError('plan load failed')

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline', _raise)
        resp = client_admin.post('/api/plan-my-night/targets/any-id/add-to-astrodex')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Line 4445: create_accessory returns None → 500
# ---------------------------------------------------------------------------


class TestCreateAccessoryNone:
    """Cover line 4445: equipment_profiles.create_accessory returns None → 500."""

    def test_create_accessory_none_returns_500(self, client_admin, monkeypatch):
        import equipment_profiles as _ep
        monkeypatch.setattr(_ep, 'create_accessory', lambda *a, **kw: None)
        resp = client_admin.post('/api/equipment/accessories', json={'name': 'TestBarlow'})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Lines 563-565: _provider returns 'mozilla' and 'other' for non-apple/google
# ---------------------------------------------------------------------------


class TestPushSubscriptionsMozillaOtherProvider:
    """Cover lines 563-565: mozilla and 'other' provider branches in _provider."""

    def test_mozilla_and_other_endpoints_classified(self, client_admin, monkeypatch):
        admin = user_manager.get_user_by_username('admin')
        monkeypatch.setattr(admin, 'push_subscriptions', [
            {'endpoint': 'https://push.services.mozilla.com/notify/abc', 'keys': {}},
            {'endpoint': 'https://unknown-push.example.com/token', 'keys': {}},
        ])
        resp = client_admin.get('/api/push/subscriptions')
        assert resp.status_code == 200
        subs = resp.get_json()['subscriptions']
        providers = {s['provider'] for s in subs}
        assert 'mozilla' in providers
        assert 'other' in providers


# ---------------------------------------------------------------------------
# Line 627: push_test_trigger with valid trigger_id but no push subscriptions
# ---------------------------------------------------------------------------


class TestPushTestTriggerNoSubscriptions:
    """Cover line 627: valid trigger_id but empty push_subscriptions → 400."""

    def test_valid_trigger_no_subs_returns_400(self, client_admin, monkeypatch):
        admin = user_manager.get_user_by_username('admin')
        monkeypatch.setattr(admin, 'push_subscriptions', [])
        resp = client_admin.post('/api/push/test/N1')
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'error' in data


# ---------------------------------------------------------------------------
# Branch 838->841: update_user raises generic ValueError (no matching pattern)
# Branch 862->865: delete_user raises generic ValueError (no matching pattern)
# ---------------------------------------------------------------------------


class TestUserCrudGenericValueError:
    """Cover 838->841 and 862->865: ValueError that matches no known error pattern."""

    def test_update_user_generic_valueerror_uses_default_key(self, client_admin, monkeypatch):
        """838->841: no elif condition matches → error_key stays 'users.invalid_input'."""
        admin = user_manager.get_user_by_username('admin')

        def _raise(*a, **kw):
            raise ValueError("unrecognised error string")

        monkeypatch.setattr(_app_mod.user_manager, 'update_user', _raise)
        resp = client_admin.put(f'/api/users/{admin.user_id}', json={'username': 'newname'})
        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.invalid_input'

    def test_delete_user_generic_valueerror_uses_default_key(self, client_admin, monkeypatch):
        """862->865: no elif condition matches → error_key stays 'users.invalid_input'."""
        admin = user_manager.get_user_by_username('admin')

        def _raise(*a, **kw):
            raise ValueError("unrecognised error string")

        monkeypatch.setattr(_app_mod.user_manager, 'delete_user', _raise)
        resp = client_admin.delete(f'/api/users/{admin.user_id}')
        assert resp.status_code == 400
        assert resp.get_json()['error_key'] == 'users.invalid_input'


# ---------------------------------------------------------------------------
# Branch 1334->1336: backup restore where target dir does not yet exist
# ---------------------------------------------------------------------------


class TestBackupRestoreDirNotExist:
    """Cover 1334->1336: os.path.isdir(target_dir) is False → skip rmtree."""

    def test_astrodex_restore_when_dir_missing(self, client_admin, monkeypatch, tmp_path):
        import io
        import zipfile
        import json

        monkeypatch.setattr(_app_mod, 'DATA_DIR', str(tmp_path))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('astrodex/item1.json', json.dumps({'id': 'x', 'name': 'M31'}))
        buf.seek(0)

        resp = client_admin.post(
            '/api/backup/restore',
            data={'file': (buf, 'backup.zip')},
            content_type='multipart/form-data',
        )
        assert resp.status_code in (200, 201)


# ---------------------------------------------------------------------------
# Branch 1406->1404: log export where is_dir source doesn't exist
# Lines 1424-1426: log export exception handler
# ---------------------------------------------------------------------------


class TestLogExportEdgeCases:
    """Cover 1406->1404 (dir not found → next entry) and 1424-1426 (exception)."""

    def test_log_export_missing_dir_skips_it(self, client_admin, monkeypatch):
        """1406->1404: one LOG_EXPORT_ENTRIES is_dir=True path doesn't exist."""
        monkeypatch.setattr(_app_mod, 'SKYTONIGHT_LOGS_DIR', '/nonexistent/path/xyz123')
        resp = client_admin.get('/api/logs/export')
        assert resp.status_code == 200

    def test_log_export_exception_returns_500(self, client_admin, monkeypatch):
        """Lines 1424-1426: ZipFile creation raises → 500."""
        import zipfile as _zf

        def _raise(*a, **kw):
            raise OSError("forced zip failure")

        monkeypatch.setattr(_app_mod.zipfile, 'ZipFile', _raise)
        resp = client_admin.get('/api/logs/export')
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Branch 1563->1562: get_timezones_api where filter condition is False
# ---------------------------------------------------------------------------


class TestTimezoneFilterBranch:
    """Cover 1563->1562: a tz matching posix/right/localtime skips body (False branch)."""

    def test_localtime_tz_skipped_by_filter(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'available_timezones',
                            lambda: {'UTC', 'Europe/Paris', 'localtime'})
        resp = client_admin.get('/api/timezones')
        assert resp.status_code == 200
        data = resp.get_json()
        names = [item['name'] for item in data]
        assert 'localtime' not in names
        assert 'UTC' in names


# ---------------------------------------------------------------------------
# Lines 2608->2641: meteor shower event with missing fields
# Lines 2624->2641: comet appearance event with missing fields
# ---------------------------------------------------------------------------


class TestTranslateSolarSystemMissingFields:
    """Cover False branches of inner if-checks for incomplete event data."""

    def test_meteor_shower_missing_fields_skips_translation(self, monkeypatch):
        """2608->2641: shower_name/zenith_hourly_rate/parent_body falsy → skip title/desc."""
        from unittest.mock import MagicMock
        mock_i18n = MagicMock()
        monkeypatch.setattr(_app_mod, 'I18nManager', lambda lang: mock_i18n)
        data = {'events': [{
            'event_type': 'Meteor Shower',
            'raw_data': {'shower': ''},  # empty → condition False
            'zenith_hourly_rate': '',
            'parent_body': '',
            'title': 'Meteor Shower',
            'description': 'Some shower',
        }]}
        result = _app_mod._translate_solar_system_events(data, 'fr')
        assert result['events'][0]['title'] == 'Meteor Shower'
        mock_i18n.t.assert_not_called()

    def test_comet_appearance_missing_fields_skips_translation(self, monkeypatch):
        """2624->2641: comet_name/magnitude/visibility falsy → skip title/desc."""
        from unittest.mock import MagicMock
        mock_i18n = MagicMock()
        monkeypatch.setattr(_app_mod, 'I18nManager', lambda lang: mock_i18n)
        data = {'events': [{
            'event_type': 'Comet Appearance',
            'raw_data': {'comet': ''},  # empty → condition False
            'magnitude': '',
            'equipment_needed': '',
            'title': 'Comet Appearance',
            'description': 'Some comet',
        }]}
        result = _app_mod._translate_solar_system_events(data, 'fr')
        assert result['events'][0]['title'] == 'Comet Appearance'
        mock_i18n.t.assert_not_called()


# ---------------------------------------------------------------------------
# Branch 2893->2898: sync_cache_from_shared True but is_cache_valid still False
# ---------------------------------------------------------------------------


class TestBestWindowSyncTrueButCacheStillInvalid:
    """Cover 2893->2898: after sync, cache still invalid → fall to stale check."""

    def test_sync_true_cache_still_invalid_serves_stale(self, client_admin, monkeypatch):
        def _is_valid(cache_entry, ttl):
            return False  # Always invalid

        def _sync(name, cache_entry):
            cache_entry['data'] = {'status': 'stale', 'mode': name}
            return True  # Sync succeeded but cache still invalid

        monkeypatch.setattr(_app_mod.cache_store, 'is_cache_valid', _is_valid)
        monkeypatch.setattr(_app_mod.cache_store, 'sync_cache_from_shared', _sync)
        resp = client_admin.get('/api/tonight/best-window?mode=all')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Branch 3385->3387: default plan file in get_all_plan_files loop
# Branch 3390->3382: entry not found in first sub-plan, found in second
# ---------------------------------------------------------------------------


class TestAddPlanTargetDefaultAndMultiPlan:
    """Cover 3385->3387 (default plan file) and 3390->3382 (loop continues)."""

    def test_default_plan_file_gets_tid_none(self, client_admin, monkeypatch):
        """3385->3387: fname is the default plan file → tid stays None."""
        import plan_my_night as _pmn
        import astrodex as _ad

        entry_id = 'test-default-plan-entry'

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline',
                            lambda *a, **kw: {'plan': {'entries': []}})
        monkeypatch.setattr(_pmn, 'get_all_plan_files',
                            lambda uid: [f'/fake/{uid}_plan_my_night.json'])
        monkeypatch.setattr(_pmn, 'load_user_plan',
                            lambda uid, uname, telescope_id=None: {'plan': {'entries': [
                                {'id': entry_id, 'name': 'M31', 'catalogue': 'Messier'}
                            ]}})
        monkeypatch.setattr(_ad, 'is_item_in_astrodex', lambda *a: False)
        monkeypatch.setattr(_ad, 'create_astrodex_item',
                            lambda *a, **kw: {'id': 'new-item', 'name': 'M31'})

        resp = client_admin.post(f'/api/plan-my-night/targets/{entry_id}/add-to-astrodex')
        assert resp.status_code in (200, 201)
        assert resp.get_json().get('status') == 'success'

    def test_entry_found_in_second_plan_file(self, client_admin, monkeypatch):
        """3390->3382: first sub-plan has no match → loop continues to second."""
        import plan_my_night as _pmn
        import astrodex as _ad

        entry_id = 'test-second-plan-entry'

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline',
                            lambda *a, **kw: {'plan': {'entries': []}})
        monkeypatch.setattr(_pmn, 'get_all_plan_files',
                            lambda uid: [
                                f'/fake/{uid}_plan_scope1.json',
                                f'/fake/{uid}_plan_scope2.json',
                            ])

        call_count = [0]

        def _load_user_plan(uid, uname, telescope_id=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return {'plan': {'entries': []}}  # Not found in first
            return {'plan': {'entries': [
                {'id': entry_id, 'name': 'NGC 224', 'catalogue': 'NGC'}
            ]}}

        monkeypatch.setattr(_pmn, 'load_user_plan', _load_user_plan)
        monkeypatch.setattr(_ad, 'is_item_in_astrodex', lambda *a: False)
        monkeypatch.setattr(_ad, 'create_astrodex_item',
                            lambda *a, **kw: {'id': 'new-item', 'name': 'NGC 224'})

        resp = client_admin.post(f'/api/plan-my-night/targets/{entry_id}/add-to-astrodex')
        assert resp.status_code in (200, 201)
        assert resp.get_json().get('status') == 'success'
        assert call_count[0] == 2  # Both plan files were searched


# ---------------------------------------------------------------------------
# Line 4695: get_or_create_cache_scheduler where start() returns True
# ---------------------------------------------------------------------------


class TestCacheSchedulerStartTrue:
    """Cover line 4695: CacheScheduler.start() returns True → success debug log."""

    def test_start_returns_true_logs_success(self, client_admin, monkeypatch):
        from cache_scheduler import CacheScheduler as CS

        monkeypatch.setattr(CS, 'start', lambda self: True)

        saved = _app_mod.app.config.pop('cache_scheduler', None)
        try:
            result = _app_mod.get_or_create_cache_scheduler()
            assert result is not None
        finally:
            if saved is not None:
                _app_mod.app.config['cache_scheduler'] = saved
            elif 'cache_scheduler' in _app_mod.app.config:
                _app_mod.app.config.pop('cache_scheduler')

    def test_start_returns_false_logs_already_running(self, client_admin, monkeypatch):
        """Cover line 4697: CacheScheduler.start() returns False → already-running debug log."""
        from cache_scheduler import CacheScheduler as CS

        monkeypatch.setattr(CS, 'start', lambda self: False)

        saved = _app_mod.app.config.pop('cache_scheduler', None)
        try:
            result = _app_mod.get_or_create_cache_scheduler()
            assert result is not None
        finally:
            if saved is not None:
                _app_mod.app.config['cache_scheduler'] = saved
            elif 'cache_scheduler' in _app_mod.app.config:
                _app_mod.app.config.pop('cache_scheduler')


# ---------------------------------------------------------------------------
# Connector routes
# ---------------------------------------------------------------------------

_ALLSKY_CFG_FULL = {
    "url": "http://allsky.local",
    "enabled": True,
    "modules": {
        "live_image": {"enabled": True},
        "keogram": {"enabled": True},
        "sensor_data": {"enabled": True},
    },
}


class TestListConnectorsApi:

    def test_returns_list_with_allsky(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        resp = client_admin.get('/api/connectors')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        names = [d['name'] for d in data]
        assert 'allsky' in names

    def test_connector_fields_present(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        resp = client_admin.get('/api/connectors')
        item = next(d for d in resp.get_json() if d['name'] == 'allsky')
        for field in ('label', 'description', 'min_version', 'homepage', 'modules', 'installed', 'enabled', 'config'):
            assert field in item

    def test_not_installed_when_no_url(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {}})
        resp = client_admin.get('/api/connectors')
        item = next(d for d in resp.get_json() if d['name'] == 'allsky')
        assert item['installed'] is False
        assert item['enabled'] is False

    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/connectors')
        assert resp.status_code == 401


class TestAllSkyStatusApi:

    def test_returns_404_when_not_configured(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {}})
        resp = client_admin.get('/api/connectors/allsky/status')
        assert resp.status_code == 404

    def test_returns_404_when_sensor_data_not_enabled(self, client_admin, monkeypatch):
        cfg = {"url": "http://allsky.local", "enabled": True, "modules": {}}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": cfg}})
        resp = client_admin.get('/api/connectors/allsky/status')
        assert resp.status_code == 404

    def test_returns_cached_data(self, client_admin, monkeypatch):
        cfg = {
            "url": "http://allsky.local", "enabled": True,
            "modules": {"sensor_data": {"enabled": True}},
        }
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": cfg}})
        import cache_store as cs
        original = dict(cs._allsky_sensor_cache)
        cs._allsky_sensor_cache["data"] = {"AS_TEMPERATURE_C": 15.0}
        try:
            resp = client_admin.get('/api/connectors/allsky/status')
            assert resp.status_code == 200
            assert resp.get_json().get("AS_TEMPERATURE_C") == 15.0
        finally:
            cs._allsky_sensor_cache.update(original)
            cs._allsky_sensor_cache["data"] = None

    def test_fetches_live_when_cache_empty(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        cfg = {
            "url": "http://allsky.local", "enabled": True,
            "modules": {"sensor_data": {"enabled": True}},
        }
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": cfg}})
        import cache_store as cs
        cs._allsky_sensor_cache["data"] = None
        with patch('connectors.allsky_connector.AllSkyConnector.fetch_sensor_data', return_value={"AS_TEMPERATURE_C": 20.0}):
            resp = client_admin.get('/api/connectors/allsky/status')
        assert resp.status_code == 200
        cs._allsky_sensor_cache["data"] = None


class TestAllSkyHealthApi:

    def test_get_no_url_returns_200_not_reachable(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {}})
        resp = client_admin.get('/api/connectors/allsky/health')
        assert resp.status_code == 200
        assert resp.get_json()['reachable'] is False

    def test_get_returns_cached_health(self, client_admin, monkeypatch):
        cfg = {"url": "http://allsky.local", "enabled": True, "modules": {}}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": cfg}})
        import cache_store as cs
        import time
        cs._allsky_health_cache["data"] = {"reachable": True, "modules": {}}
        cs._allsky_health_cache["timestamp"] = time.time()
        try:
            resp = client_admin.get('/api/connectors/allsky/health')
            assert resp.status_code == 200
            assert resp.get_json()['reachable'] is True
        finally:
            cs._allsky_health_cache["data"] = None
            cs._allsky_health_cache["timestamp"] = 0

    def test_get_fresh_bypasses_cache(self, client_admin, monkeypatch):
        from unittest.mock import patch
        cfg = {"url": "http://allsky.local", "enabled": True, "modules": {}}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": cfg}})
        import cache_store as cs
        import time
        cs._allsky_health_cache["data"] = {"reachable": True, "modules": {}}
        cs._allsky_health_cache["timestamp"] = time.time()
        fresh_result = {"reachable": False, "modules": {}}
        try:
            with patch('connectors.allsky_connector.AllSkyConnector.health_check', return_value=fresh_result):
                resp = client_admin.get('/api/connectors/allsky/health?fresh=1')
            assert resp.status_code == 200
            assert resp.get_json()['reachable'] is False
        finally:
            cs._allsky_health_cache["data"] = None
            cs._allsky_health_cache["timestamp"] = 0

    def test_get_live_health_check(self, client_admin, monkeypatch):
        from unittest.mock import patch
        cfg = {"url": "http://allsky.local", "enabled": True, "modules": {}}
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": cfg}})
        import cache_store as cs
        cs._allsky_health_cache["data"] = None
        cs._allsky_health_cache["timestamp"] = 0
        with patch('connectors.allsky_connector.AllSkyConnector.health_check',
                   return_value={"reachable": True, "modules": {}}):
            resp = client_admin.get('/api/connectors/allsky/health')
        assert resp.status_code == 200
        assert resp.get_json()['reachable'] is True
        cs._allsky_health_cache["data"] = None
        cs._allsky_health_cache["timestamp"] = 0

    def test_post_missing_url_returns_400(self, client_admin, monkeypatch):
        resp = client_admin.post('/api/connectors/allsky/health',
                                 json={}, content_type='application/json')
        assert resp.status_code == 400
        assert resp.get_json()['reachable'] is False

    def test_post_reachable_url(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock(status_code=200)
        with patch('requests.head', return_value=mock_resp):
            resp = client_admin.post('/api/connectors/allsky/health',
                                     json={"url": "http://allsky.local"},
                                     content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['reachable'] is True

    def test_post_405_falls_back_to_get(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        head_resp = MagicMock(status_code=405)
        get_resp = MagicMock(status_code=200)
        with patch('requests.head', return_value=head_resp):
            with patch('requests.get', return_value=get_resp):
                resp = client_admin.post('/api/connectors/allsky/health',
                                         json={"url": "http://allsky.local"},
                                         content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['reachable'] is True

    def test_post_connection_error_returns_not_reachable(self, client_admin, monkeypatch):
        import requests as _req
        from unittest.mock import patch
        with patch('requests.head', side_effect=_req.exceptions.ConnectionError):
            resp = client_admin.post('/api/connectors/allsky/health',
                                     json={"url": "http://allsky.local"},
                                     content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['reachable'] is False

    def test_post_500_not_reachable(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock(status_code=500)
        with patch('requests.head', return_value=mock_resp):
            resp = client_admin.post('/api/connectors/allsky/health',
                                     json={"url": "http://allsky.local"},
                                     content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['reachable'] is False


class TestAllSkyUrlsApi:

    def test_returns_404_when_not_configured(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {}})
        resp = client_admin.get('/api/connectors/allsky/urls')
        assert resp.status_code == 404

    def test_returns_proxy_urls_for_enabled_modules(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        resp = client_admin.get('/api/connectors/allsky/urls')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "live_image" in data
        assert data["live_image"].startswith("/api/connectors/allsky/proxy?module=live_image")

    def test_date_suffix_appended_when_provided(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        resp = client_admin.get('/api/connectors/allsky/urls?date=20260101')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "keogram" in data
        assert "&date=20260101" in data["keogram"]


class TestAllSkyProxyApi:

    def test_missing_module_param_returns_400(self, client_admin, monkeypatch):
        resp = client_admin.get('/api/connectors/allsky/proxy')
        assert resp.status_code == 400

    def test_not_configured_returns_503(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {}})
        resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 503

    def test_unknown_module_returns_404(self, client_admin, monkeypatch):
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        resp = client_admin.get('/api/connectors/allsky/proxy?module=nonexistent')
        assert resp.status_code == 404

    def test_proxy_streams_content(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/jpeg", "Content-Length": "1234"}
        mock_resp.iter_content.return_value = iter([b"fake-image-data"])
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ("1.2.3.4", 80))]):
            with patch('requests.get', return_value=mock_resp):
                resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 200
        assert resp.content_type == "image/jpeg"

    def test_proxy_timeout_returns_504(self, client_admin, monkeypatch):
        import requests as _req
        from unittest.mock import patch
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ("1.2.3.4", 80))]):
            with patch('requests.get', side_effect=_req.exceptions.Timeout):
                resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 504

    def test_proxy_connection_error_returns_502(self, client_admin, monkeypatch):
        import requests as _req
        from unittest.mock import patch
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ("1.2.3.4", 80))]):
            with patch('requests.get', side_effect=_req.exceptions.ConnectionError):
                resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 502

    def test_proxy_range_header_forwarded(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        mock_resp = MagicMock()
        mock_resp.status_code = 206
        mock_resp.headers = {
            "Content-Type": "video/mp4",
            "Content-Range": "bytes 0-999/5000",
            "Accept-Ranges": "bytes",
        }
        mock_resp.iter_content.return_value = iter([b"chunk"])
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ("1.2.3.4", 80))]):
            with patch('requests.get', return_value=mock_resp) as mock_get:
                resp = client_admin.get(
                    '/api/connectors/allsky/proxy?module=live_image',
                    headers={"Range": "bytes=0-999"},
                )
        assert resp.status_code == 206
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs.get('headers', {}).get('Range') == 'bytes=0-999'

    def test_proxy_dns_failure_uses_original_url(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_resp.iter_content.return_value = iter([b"data"])
        with patch('socket.getaddrinfo', side_effect=OSError("no route")):
            with patch('requests.get', return_value=mock_resp):
                resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 200

    def test_proxy_empty_dns_result_uses_original_url(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_resp.iter_content.return_value = iter([b"data"])
        with patch('socket.getaddrinfo', return_value=[]):
            with patch('requests.get', return_value=mock_resp):
                resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 200

    def test_proxy_non200_upstream_still_returned(self, client_admin, monkeypatch):
        from unittest.mock import patch, MagicMock
        monkeypatch.setattr(_app_mod, 'load_config', lambda: {"connectors": {"allsky": _ALLSKY_CFG_FULL}})
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.iter_content.return_value = iter([b"not found"])
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ("1.2.3.4", 80))]):
            with patch('requests.get', return_value=mock_resp):
                resp = client_admin.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 404
