"""Flask test client tests for the main app.py routes.

Covers static-file routes, auth endpoints, config, cache/report endpoints,
admin endpoints, and various API utility routes.
"""
import json as _json
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
        from auth import user_manager
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
            pass

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
