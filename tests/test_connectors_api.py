"""Tests for the connector API endpoints (app.py routes).

Covers every branch of all five connector routes:
  GET /api/connectors
  GET /api/connectors/allsky/status
  GET /api/connectors/allsky/health
  GET /api/connectors/allsky/urls
  GET /api/connectors/allsky/proxy
"""
import os
import sys
import time
import types

import pytest
import requests as _requests
from unittest.mock import MagicMock, patch

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from cache import cache_store


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_CFG_ALLSKY_ENABLED = {
    "url": "http://allsky.local",
    "enabled": True,
    "modules": {
        "live_image":  {"enabled": True},
        "sensor_data": {"enabled": True},
    },
}

_CFG_ALLSKY_URL_ONLY = {
    "url": "http://allsky.local",
    "enabled": False,
    "modules": {},
}

_CFG_ALLSKY_NO_SENSOR = {
    "url": "http://allsky.local",
    "enabled": True,
    "modules": {
        "sensor_data": {"enabled": False},
    },
}


def _config(allsky_cfg=None):
    return {"connectors": {"allsky": allsky_cfg} if allsky_cfg else {}}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_allsky_caches():
    """Reset connector caches before each test."""
    cache_store._allsky_sensor_cache.update({"timestamp": 0, "data": None})
    cache_store._allsky_health_cache.update({"timestamp": 0, "data": None})
    yield
    cache_store._allsky_sensor_cache.update({"timestamp": 0, "data": None})
    cache_store._allsky_health_cache.update({"timestamp": 0, "data": None})


# ---------------------------------------------------------------------------
# GET /api/connectors
# ---------------------------------------------------------------------------

class TestListConnectors:

    def test_requires_login(self, client):
        resp = client.get('/api/connectors')
        assert resp.status_code == 401

    def test_returns_list(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]['name'] == 'allsky'

    def test_connector_not_installed_when_no_url(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['installed'] is False
        assert data[0]['enabled'] is False

    def test_connector_installed_not_enabled(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_URL_ONLY)):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['installed'] is True
        assert data[0]['enabled'] is False

    def test_connector_installed_and_enabled(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert data[0]['installed'] is True
        assert data[0]['enabled'] is True

    def test_response_includes_homepage(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors')
        data = resp.get_json()
        assert 'homepage' in data[0]
        assert 'github.com/AllskyTeam' in data[0]['homepage']


# ---------------------------------------------------------------------------
# GET /api/connectors/allsky/status
# ---------------------------------------------------------------------------

class TestAllSkyStatus:

    def test_requires_login(self, client):
        resp = client.get('/api/connectors/allsky/status')
        assert resp.status_code == 401

    def test_404_when_not_configured(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors/allsky/status')
        assert resp.status_code == 404

    def test_404_when_enabled_false(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_URL_ONLY)):
            resp = client_user.get('/api/connectors/allsky/status')
        assert resp.status_code == 404

    def test_404_when_sensor_module_disabled(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_NO_SENSOR)):
            resp = client_user.get('/api/connectors/allsky/status')
        assert resp.status_code == 404

    def test_returns_cached_data(self, client_user):
        cached_data = {"AS_TEMPERATURE_C": 12.5, "ALLSKY_VERSION": "v2024.12"}
        cache_store._allsky_sensor_cache["data"] = cached_data
        cache_store._allsky_sensor_cache["timestamp"] = time.time()

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            resp = client_user.get('/api/connectors/allsky/status')
        assert resp.status_code == 200
        assert resp.get_json() == cached_data

    def test_fetches_when_cache_empty(self, client_user):
        fresh_data = {"AS_TEMPERATURE_C": 8.0}
        mock_connector = MagicMock()
        mock_connector.fetch_sensor_data.return_value = fresh_data

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/status')
        assert resp.status_code == 200
        assert resp.get_json() == fresh_data
        assert cache_store._allsky_sensor_cache["data"] == fresh_data


# ---------------------------------------------------------------------------
# GET /api/connectors/allsky/health
# ---------------------------------------------------------------------------

class TestAllSkyHealth:

    def test_requires_login(self, client):
        resp = client.get('/api/connectors/allsky/health')
        assert resp.status_code == 401

    def test_200_no_url_configured(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors/allsky/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['reachable'] is False
        assert 'error' in data

    def test_returns_cached_when_fresh(self, client_user):
        health_data = {"reachable": True, "modules": {"live_image": {"ok": True, "detail": "200 OK"}}}
        cache_store._allsky_health_cache["data"] = health_data
        cache_store._allsky_health_cache["timestamp"] = time.time()  # just now

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            resp = client_user.get('/api/connectors/allsky/health')
        assert resp.status_code == 200
        assert resp.get_json() == health_data

    def test_fetches_when_cache_stale(self, client_user):
        fresh_health = {"reachable": True, "modules": {}}
        mock_connector = MagicMock()
        mock_connector.health_check.return_value = fresh_health

        cache_store._allsky_health_cache["data"] = None
        cache_store._allsky_health_cache["timestamp"] = 0  # stale

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/health')
        assert resp.status_code == 200
        assert resp.get_json() == fresh_health
        assert cache_store._allsky_health_cache["data"] == fresh_health

    def test_fetches_when_cache_older_than_300s(self, client_user):
        stale_data = {"reachable": False, "modules": {}}
        fresh_health = {"reachable": True, "modules": {}}
        mock_connector = MagicMock()
        mock_connector.health_check.return_value = fresh_health

        cache_store._allsky_health_cache["data"] = stale_data
        cache_store._allsky_health_cache["timestamp"] = time.time() - 400  # 400s old → stale

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/health')
        assert resp.get_json() == fresh_health

    # POST — quick URL probe (test button, no save required)

    def test_post_requires_login(self, client):
        resp = client.post('/api/connectors/allsky/health',
                           json={"url": "http://192.168.1.1"})
        assert resp.status_code == 401

    def test_post_400_when_no_url(self, client_user):
        resp = client_user.post('/api/connectors/allsky/health', json={})
        assert resp.status_code == 400

    def test_post_reachable_true_on_200(self, client_user):
        mock_resp = MagicMock(status_code=200)
        with patch('requests.head', return_value=mock_resp):
            resp = client_user.post('/api/connectors/allsky/health',
                                    json={"url": "http://192.168.1.1"})
        assert resp.status_code == 200
        assert resp.get_json()["reachable"] is True

    def test_post_reachable_false_on_connection_error(self, client_user):
        with patch('requests.head', side_effect=_requests.exceptions.ConnectionError):
            resp = client_user.post('/api/connectors/allsky/health',
                                    json={"url": "http://192.168.1.1"})
        assert resp.status_code == 200
        assert resp.get_json()["reachable"] is False

    def test_post_falls_back_to_get_on_405(self, client_user):
        head_resp = MagicMock(status_code=405)
        get_resp = MagicMock(status_code=200)
        with patch('requests.head', return_value=head_resp):
            with patch('requests.get', return_value=get_resp):
                resp = client_user.post('/api/connectors/allsky/health',
                                        json={"url": "http://192.168.1.1"})
        assert resp.get_json()["reachable"] is True

    def test_post_400_when_invalid_scheme(self, client_user):
        resp = client_user.post('/api/connectors/allsky/health', json={"url": "ftp://192.168.1.1"})
        assert resp.status_code == 400
        assert "http" in resp.get_json()["error"]

    def test_post_400_when_no_hostname(self, client_user):
        resp = client_user.post('/api/connectors/allsky/health', json={"url": "http://"})
        assert resp.status_code == 400
        assert "host" in resp.get_json()["error"]

    def test_post_400_when_loopback(self, client_user):
        resp = client_user.post('/api/connectors/allsky/health', json={"url": "http://127.0.0.1"})
        assert resp.status_code == 400
        assert "not allowed" in resp.get_json()["error"]

    def test_post_400_when_link_local(self, client_user):
        resp = client_user.post('/api/connectors/allsky/health', json={"url": "http://169.254.169.254"})
        assert resp.status_code == 400
        assert "not allowed" in resp.get_json()["error"]

    def test_post_400_when_unresolvable_host(self, client_user):
        import socket
        with patch('socket.getaddrinfo', side_effect=socket.gaierror):
            resp = client_user.post('/api/connectors/allsky/health',
                                    json={"url": "http://nonexistent.invalid"})
        assert resp.status_code == 400
        assert "resolve" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# GET /api/connectors/allsky/urls
# ---------------------------------------------------------------------------

class TestAllSkyUrls:

    def test_requires_login(self, client):
        resp = client.get('/api/connectors/allsky/urls')
        assert resp.status_code == 401

    def test_404_when_not_configured(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors/allsky/urls')
        assert resp.status_code == 404

    def test_404_when_enabled_false(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_URL_ONLY)):
            resp = client_user.get('/api/connectors/allsky/urls')
        assert resp.status_code == 404

    def test_returns_proxy_urls(self, client_user):
        direct = {"live_image": "http://allsky.local/current/tmp/image.jpg"}
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = direct

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/urls')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'live_image' in data
        assert '/api/connectors/allsky/proxy?module=live_image' == data['live_image']

    def test_date_param_forwarded(self, client_user):
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = {}

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/urls?date=20260101')
        assert resp.status_code == 200
        mock_connector.get_module_urls.assert_called_once_with(date_str='20260101')

    def test_proxy_url_includes_date_suffix(self, client_user):
        direct = {"keogram": "http://allsky.local/keograms/keogram-20260101.jpg"}
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = direct

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/urls?date=20260101')
        data = resp.get_json()
        assert data['keogram'] == '/api/connectors/allsky/proxy?module=keogram&date=20260101'


# ---------------------------------------------------------------------------
# GET /api/connectors/allsky/proxy
# ---------------------------------------------------------------------------

class TestAllSkyProxy:

    def test_requires_login(self, client):
        resp = client.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 401

    def test_400_when_no_module_param(self, client_user):
        resp = client_user.get('/api/connectors/allsky/proxy')
        assert resp.status_code == 400

    def test_503_when_not_configured(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config()):
            resp = client_user.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 503

    def test_503_when_enabled_false(self, client_user):
        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_URL_ONLY)):
            resp = client_user.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 503

    def test_404_when_module_not_found(self, client_user):
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = {}  # module absent

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                resp = client_user.get('/api/connectors/allsky/proxy?module=keogram')
        assert resp.status_code == 404

    def test_proxies_content_successfully(self, client_user):
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = {
            "live_image": "http://allsky.local/current/tmp/image.jpg"
        }

        mock_upstream = MagicMock()
        mock_upstream.status_code = 200
        mock_upstream.headers = {"Content-Type": "image/jpeg", "Content-Length": "12345"}
        mock_upstream.iter_content.return_value = iter([b"fake-image-data"])

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                with patch('requests.get', return_value=mock_upstream):
                    resp = client_user.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 200
        assert b"fake-image-data" in resp.data

    def test_504_on_timeout(self, client_user):
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = {
            "live_image": "http://allsky.local/current/tmp/image.jpg"
        }

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                with patch('requests.get', side_effect=_requests.exceptions.Timeout):
                    resp = client_user.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 504

    def test_502_on_connection_error(self, client_user):
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = {
            "live_image": "http://allsky.local/current/tmp/image.jpg"
        }

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                with patch('requests.get', side_effect=_requests.exceptions.ConnectionError("refused")):
                    resp = client_user.get('/api/connectors/allsky/proxy?module=live_image')
        assert resp.status_code == 502

    def test_range_header_forwarded(self, client_user):
        mock_connector = MagicMock()
        mock_connector.get_module_urls.return_value = {
            "live_image": "http://allsky.local/current/tmp/image.jpg"
        }

        mock_upstream = MagicMock()
        mock_upstream.status_code = 206
        mock_upstream.headers = {
            "Content-Type": "image/jpeg",
            "Content-Range": "bytes 0-1023/12345",
            "Accept-Ranges": "bytes",
        }
        mock_upstream.iter_content.return_value = iter([b"partial"])

        captured = {}

        def _fake_get(url, timeout, stream, headers):
            captured['headers'] = headers
            return mock_upstream

        with patch('blueprints.connectors.load_config', return_value=_config(_CFG_ALLSKY_ENABLED)):
            with patch('connectors.allsky_connector.AllSkyConnector', return_value=mock_connector):
                with patch('requests.get', side_effect=_fake_get):
                    resp = client_user.get(
                        '/api/connectors/allsky/proxy?module=live_image',
                        headers={"Range": "bytes=0-1023"},
                    )
        assert resp.status_code == 206
        assert captured['headers'].get('Range') == 'bytes=0-1023'
