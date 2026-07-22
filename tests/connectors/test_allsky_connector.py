"""Unit tests for AllSkyConnector and BaseConnector."""
import sys
import os

import requests as _requests
from unittest.mock import MagicMock, patch

from connectors.allsky_connector import AllSkyConnector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make(cfg=None):
    """Return an AllSkyConnector with the given config dict (defaults to minimal)."""
    base = {"url": "http://allsky.local", "enabled": True, "modules": {}}
    if cfg is not None:
        base.update(cfg)
    return AllSkyConnector(base)


def _make_all_modules(enabled=True):
    return _make({
        "url": "http://allsky.local",
        "enabled": True,
        "modules": {s: {"enabled": enabled} for s in [
            "live_image", "sensor_data", "keogram",
            "startrails", "daily_timelapse",
        ]},
    })


# ---------------------------------------------------------------------------
# BaseConnector — __init__, is_enabled, is_module_enabled
# ---------------------------------------------------------------------------

class TestBaseConnector:

    def test_init_stores_config(self):
        cfg = {"url": "http://allsky.local", "enabled": True, "modules": {}}
        c = AllSkyConnector(cfg)
        assert c.config is cfg

    def test_base_url_strips_trailing_slash(self):
        c = _make({"url": "http://allsky.local/", "enabled": True, "modules": {}})
        assert c.base_url == "http://allsky.local"

    def test_base_url_empty_when_no_url(self):
        c = AllSkyConnector({})
        assert c.base_url == ""

    def test_is_enabled_true(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {}})
        assert c.is_enabled() is True

    def test_is_enabled_false_when_disabled(self):
        c = _make({"url": "http://allsky.local", "enabled": False, "modules": {}})
        assert c.is_enabled() is False

    def test_is_enabled_false_when_no_url(self):
        c = AllSkyConnector({"enabled": True, "modules": {}})
        assert c.is_enabled() is False

    def test_is_module_enabled_true(self):
        c = _make({"url": "http://x", "enabled": True, "modules": {"live_image": {"enabled": True}}})
        assert c.is_module_enabled("live_image") is True

    def test_is_module_enabled_false(self):
        c = _make({"url": "http://x", "enabled": True, "modules": {"live_image": {"enabled": False}}})
        assert c.is_module_enabled("live_image") is False

    def test_is_module_enabled_missing_slug(self):
        c = _make()
        assert c.is_module_enabled("nonexistent") is False


# ---------------------------------------------------------------------------
# URL builder methods
# ---------------------------------------------------------------------------

class TestUrlBuilders:

    def test_image_url_defaults(self):
        c = _make()
        assert c._image_url() == "http://allsky.local/current/tmp/image.jpg"

    def test_image_url_custom_path_and_filename(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {},
                   "image_path": "/custom/path/", "image_filename": "live.jpg"})
        assert c._image_url() == "http://allsky.local/custom/path/live.jpg"

    def test_sensor_data_url_defaults(self):
        c = _make()
        assert c._sensor_data_url() == "http://allsky.local/current/tmp/allskydata.json"

    def test_sensor_data_url_custom(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {},
                   "image_path": "data", "export_json_path": "export.json"})
        assert c._sensor_data_url() == "http://allsky.local/data/export.json"

    def test_keogram_url(self):
        c = _make()
        assert c._keogram_url("20260101") == "http://allsky.local/images/20260101/keogram/keogram-20260101.jpg"

    def test_startrails_url(self):
        c = _make()
        assert c._startrails_url("20260101") == "http://allsky.local/images/20260101/startrails/startrails-20260101.jpg"

    def test_daily_timelapse_url(self):
        c = _make()
        assert c._daily_timelapse_url("20260101") == "http://allsky.local/images/20260101/allsky-20260101.mp4"


# ---------------------------------------------------------------------------
# _force_ipv4()
# ---------------------------------------------------------------------------

class TestForceIpv4:

    def test_replaces_hostname_with_ipv4(self):
        with patch("socket.getaddrinfo", return_value=[
            (None, None, None, None, ("1.2.3.4", 80))
        ]):
            result = AllSkyConnector._force_ipv4("http://allsky.local/image.jpg")
        assert result == "http://1.2.3.4/image.jpg"

    def test_returns_original_when_getaddrinfo_empty(self):
        with patch("socket.getaddrinfo", return_value=[]):
            result = AllSkyConnector._force_ipv4("http://allsky.local/image.jpg")
        assert result == "http://allsky.local/image.jpg"

    def test_returns_original_on_os_error(self):
        with patch("socket.getaddrinfo", side_effect=OSError("no route")):
            result = AllSkyConnector._force_ipv4("http://allsky.local/image.jpg")
        assert result == "http://allsky.local/image.jpg"


# ---------------------------------------------------------------------------
# _head()
# ---------------------------------------------------------------------------

class TestHead:

    def _head(self, cfg=None):
        return _make(cfg)._head

    def test_200_returns_true(self):
        mock_resp = MagicMock(status_code=200)
        with patch("requests.head", return_value=mock_resp):
            ok, code = _make()._head("http://x/image.jpg")
        assert ok is True
        assert code == 200

    def test_404_returns_false(self):
        mock_resp = MagicMock(status_code=404)
        with patch("requests.head", return_value=mock_resp):
            ok, code = _make()._head("http://x/missing.jpg")
        assert ok is False
        assert code == 404

    def test_405_falls_back_to_get(self):
        head_resp = MagicMock(status_code=405)
        get_resp = MagicMock(status_code=200)
        with patch("requests.head", return_value=head_resp):
            with patch("requests.get", return_value=get_resp):
                ok, code = _make()._head("http://x/image.jpg")
        assert ok is True
        assert code == 200

    def test_connection_error_returns_0(self):
        with patch("requests.head", side_effect=_requests.exceptions.ConnectionError):
            ok, code = _make()._head("http://x/image.jpg")
        assert ok is False
        assert code == 0

    def test_timeout_returns_minus1(self):
        with patch("requests.head", side_effect=_requests.exceptions.Timeout):
            ok, code = _make()._head("http://x/image.jpg")
        assert ok is False
        assert code == -1

    def test_unexpected_exception_returns_minus2(self):
        with patch("requests.head", side_effect=RuntimeError("boom")):
            ok, code = _make()._head("http://x/image.jpg")
        assert ok is False
        assert code == -2


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------

class TestHealthCheck:

    def test_no_base_url_returns_unreachable(self):
        c = AllSkyConnector({})
        result = c.health_check()
        assert result == {"reachable": False, "modules": {}}

    def test_all_200(self):
        mock_resp = MagicMock(status_code=200)
        with patch("requests.head", return_value=mock_resp):
            result = _make().health_check()
        assert result["reachable"] is True
        for slug in ["live_image", "sensor_data", "keogram", "startrails", "daily_timelapse"]:
            assert result["modules"][slug]["ok"] is True
            assert result["modules"][slug]["detail"] == "200 OK"

    def test_404_shows_hint_for_known_module(self):
        def _head_side(url, **kwargs):
            r = MagicMock(status_code=404)
            return r

        with patch("requests.head", side_effect=_head_side):
            result = _make().health_check()

        assert result["modules"]["sensor_data"]["detail"].startswith("404 —")
        assert "Export module" in result["modules"]["sensor_data"]["detail"]

    def test_404_generic_for_unknown_module(self):
        """live_image has no hint in _MODULE_404_HINTS → generic fallback."""
        def _head_side(url, **kwargs):
            return MagicMock(status_code=404)

        with patch("requests.head", side_effect=_head_side):
            result = _make().health_check()

        assert result["modules"]["live_image"]["detail"].startswith("404 —")

    def test_connection_refused_detail(self):
        with patch("requests.head", side_effect=_requests.exceptions.ConnectionError):
            result = _make().health_check()
        for v in result["modules"].values():
            assert v["detail"] == "Connection refused"
        assert result["reachable"] is False

    def test_timeout_detail(self):
        with patch("requests.head", side_effect=_requests.exceptions.Timeout):
            result = _make().health_check()
        for v in result["modules"].values():
            assert v["detail"] == "Timeout"

    def test_other_status_code(self):
        with patch("requests.head", return_value=MagicMock(status_code=500)):
            result = _make().health_check()
        for v in result["modules"].values():
            assert "HTTP 500" in v["detail"]

    def test_reachable_when_base_fails_but_module_ok(self):
        responses = iter([
            MagicMock(status_code=503),  # base URL
            MagicMock(status_code=200),  # first module
        ] + [MagicMock(status_code=404)] * 10)

        with patch("requests.head", side_effect=lambda *a, **kw: next(responses)):
            result = _make().health_check()
        assert result["reachable"] is True


# ---------------------------------------------------------------------------
# get_module_urls()
# ---------------------------------------------------------------------------

class TestGetModuleUrls:

    def test_empty_when_no_modules_enabled(self):
        c = _make()
        assert c.get_module_urls() == {}

    def test_live_image_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True,
                   "modules": {"live_image": {"enabled": True}}})
        urls = c.get_module_urls()
        assert "live_image" in urls
        assert urls["live_image"] == "http://allsky.local/current/tmp/image.jpg"

    def test_sensor_data_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True,
                   "modules": {"sensor_data": {"enabled": True}}})
        urls = c.get_module_urls()
        assert "sensor_data" in urls

    def test_keogram_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True,
                   "modules": {"keogram": {"enabled": True}}})
        urls = c.get_module_urls(date_str="20260101")
        assert urls["keogram"] == "http://allsky.local/images/20260101/keogram/keogram-20260101.jpg"

    def test_startrails_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True,
                   "modules": {"startrails": {"enabled": True}}})
        urls = c.get_module_urls(date_str="20260101")
        assert "startrails" in urls

    def test_daily_timelapse_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True,
                   "modules": {"daily_timelapse": {"enabled": True}}})
        urls = c.get_module_urls(date_str="20260101")
        assert "daily_timelapse" in urls

    def test_all_modules_enabled(self):
        c = _make_all_modules(enabled=True)
        urls = c.get_module_urls(date_str="20260101")
        assert len(urls) == 5  # live_image, sensor_data, keogram, startrails, daily_timelapse

    def test_date_defaults_to_last_night_when_not_provided(self):
        c = _make({"url": "http://allsky.local", "enabled": True,
                   "modules": {"keogram": {"enabled": True}}})
        urls = c.get_module_urls()
        assert "keogram" in urls
        assert "/images/" in urls["keogram"] and "/keogram/keogram-" in urls["keogram"]


# ---------------------------------------------------------------------------
# fetch_sensor_data()
# ---------------------------------------------------------------------------

class TestFetchSensorData:

    def _sensor_enabled(self):
        return _make({"url": "http://allsky.local", "enabled": True,
                      "modules": {"sensor_data": {"enabled": True}}})

    def test_returns_empty_when_module_disabled(self):
        c = _make()  # sensor_data not enabled
        assert c.fetch_sensor_data() == {}

    def test_returns_json_on_success(self):
        data = {"AS_TEMPERATURE_C": 12.5, "ALLSKY_VERSION": "v2024.12"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = data
        with patch("requests.get", return_value=mock_resp):
            result = self._sensor_enabled().fetch_sensor_data()
        assert result == data

    def test_returns_empty_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = _requests.exceptions.HTTPError("404")
        with patch("requests.get", return_value=mock_resp):
            result = self._sensor_enabled().fetch_sensor_data()
        assert result == {}

    def test_returns_empty_on_connection_error(self):
        with patch("requests.get", side_effect=_requests.exceptions.ConnectionError):
            result = self._sensor_enabled().fetch_sensor_data()
        assert result == {}

    def test_returns_empty_on_timeout(self):
        with patch("requests.get", side_effect=_requests.exceptions.Timeout):
            result = self._sensor_enabled().fetch_sensor_data()
        assert result == {}

    def test_returns_empty_on_unexpected_error(self):
        with patch("requests.get", side_effect=RuntimeError("unexpected")):
            result = self._sensor_enabled().fetch_sensor_data()
        assert result == {}
