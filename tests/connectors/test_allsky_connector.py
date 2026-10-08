"""Unit tests for AllSkyConnector and BaseConnector."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from connectors import allsky_connector, mqtt_subscriber
from connectors.allsky_connector import AllSkyConnector, _normalize_sensor_data

# A real message of AllSky v2026.10's Publish Data module (topic "allsky", captured on the
# maintainer's install on 2026-10-08), with the variable list the connector card recommends.
REAL_PUBLISH_DATA_PAYLOAD = {
    "AS_DEWCONTROLAMBIENT": 25.09,
    "utc": 1791443507,
    "AS_DEWCONTROLDEW": 7.91,
    "AS_DEWCONTROLMARGIN": 17.18,
    "AS_DEWCONTROLHUMIDITY": 33.5,
    "AS_DEWCONTROLHEATER": False,
    "AS_DEWCONTROLLIMIT": 3.0,
    "AS_DEWCONTROLHEATERINT": 0,
    "AS_TEMPSENSOR": "DHT22",
    "AS_TEMPSENSORNAME": "Allsky",
    "AS_TEMP": 25.0,
    "AS_DEW": 7.84,
    "AS_HUMIDITY": 33.5,
    "AS_FANS_FAN_STATE1": False,
    "AS_FANS_TEMPERATURE1": 25.0,
    "AS_FANS_TEMP_LIMIT1": 35,
    "AS_DAY_OR_NIGHT": "DAY",
    "AS_EXPOSURE_US": 3831,
    "AS_GAIN": 1.0,
    "AS_MEAN": 0.43385,
    "AS_TEMPERATURE_C": 19.0,
}

CONNECTION = {"id": "c1", "name": "Home", "url": "mqtt://broker.lan:1883", "username": "u", "tls_insecure": False}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mqtt_files(tmp_path, monkeypatch):
    """The subscriber's last-message and status files live in a per-test directory."""
    monkeypatch.setattr(mqtt_subscriber, "DATA_DIR_CACHE", str(tmp_path))
    monkeypatch.setattr(mqtt_subscriber, "STATUS_FILE", str(tmp_path / "mqtt_subscriber_status.json"))


def _plant_message(payload, topic="allsky", age_seconds=10, received_at=None):
    """Store a last message for AllSky, as the subscriber would."""
    if received_at is None:
        received_at = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat(timespec="seconds")
    mqtt_subscriber._write_json(
        mqtt_subscriber.last_message_file("allsky"),
        {"topic": topic, "received_at": received_at, "payload": payload},
    )
    return received_at


def _plant_status(**state):
    mqtt_subscriber._write_json(mqtt_subscriber.STATUS_FILE, {"connectors": {"allsky": state}})


def _sensor_connector(connection=CONNECTION, **cfg):
    block = {"url": "http://allsky.local", "enabled": True, "modules": {"sensor_data": {"enabled": True}}}
    block.update(cfg)
    return AllSkyConnector(block, connection=connection)


@pytest.fixture(autouse=True)
def _clear_layout_cache():
    """The probed AllSky layout is remembered per process - never across tests."""
    allsky_connector._resolved_image_paths.clear()
    yield
    allsky_connector._resolved_image_paths.clear()


def _head_ok_for(*ok_suffixes):
    """requests.head stub: 200 for URLs ending with one of ``ok_suffixes``, 404 otherwise."""

    def _side(url, **kwargs):
        return MagicMock(status_code=200 if url.endswith(ok_suffixes) else 404)

    return _side


def _make(cfg=None):
    """Return an AllSkyConnector with the given config dict (defaults to minimal)."""
    base = {"url": "http://allsky.local", "enabled": True, "modules": {}}
    if cfg is not None:
        base.update(cfg)
    return AllSkyConnector(base)


def _make_all_modules(enabled=True):
    return _make(
        {
            "url": "http://allsky.local",
            "enabled": True,
            "modules": {
                s: {"enabled": enabled}
                for s in [
                    "live_image",
                    "sensor_data",
                    "keogram",
                    "startrails",
                    "daily_timelapse",
                ]
            },
        }
    )


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
        assert c._image_url() == "http://allsky.local/current/image.jpg"

    def test_image_url_custom_path_and_filename(self):
        c = _make(
            {
                "url": "http://allsky.local",
                "enabled": True,
                "modules": {},
                "image_path": "/custom/path/",
                "image_filename": "live.jpg",
            }
        )
        assert c._image_url() == "http://allsky.local/custom/path/live.jpg"

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
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 80))]):
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
        for slug in ["live_image", "keogram", "startrails", "daily_timelapse"]:
            assert result["modules"][slug]["ok"] is True
            assert result["modules"][slug]["detail"] == "200 OK"
        # Sensor data is not an HTTP file any more: its line says what MQTT brought
        assert result["modules"]["sensor_data"] == {"ok": False, "detail": "No MQTT connection chosen"}

    def test_404_shows_hint_for_known_module(self):
        def _head_side(url, **kwargs):
            r = MagicMock(status_code=404)
            return r

        with patch("requests.head", side_effect=_head_side):
            result = _make().health_check()

        assert result["modules"]["live_image"]["detail"].startswith("404 —")
        assert "current/tmp/" in result["modules"]["live_image"]["detail"]

    def test_404_generic_for_unknown_module(self, monkeypatch):
        """A module without an entry in _MODULE_404_HINTS gets the generic hint."""
        monkeypatch.delitem(allsky_connector._MODULE_404_HINTS, "keogram")

        with patch("requests.head", return_value=MagicMock(status_code=404)):
            result = _make().health_check()

        assert result["modules"]["keogram"]["detail"] == "404 — File not found on AllSky server"

    def test_connection_refused_detail(self):
        with patch("requests.head", side_effect=_requests.exceptions.ConnectionError):
            result = _make().health_check()
        for slug, v in result["modules"].items():
            if slug != "sensor_data":
                assert v["detail"] == "Connection refused"
        assert result["reachable"] is False

    def test_timeout_detail(self):
        with patch("requests.head", side_effect=_requests.exceptions.Timeout):
            result = _make().health_check()
        for slug, v in result["modules"].items():
            if slug != "sensor_data":
                assert v["detail"] == "Timeout"

    def test_other_status_code(self):
        with patch("requests.head", return_value=MagicMock(status_code=500)):
            result = _make().health_check()
        for slug, v in result["modules"].items():
            if slug != "sensor_data":
                assert "HTTP 500" in v["detail"]

    def test_reachable_when_base_fails_but_module_ok(self):
        responses = iter(
            [
                MagicMock(status_code=503),  # base URL
                MagicMock(status_code=200),  # first module
            ]
            + [MagicMock(status_code=404)] * 10
        )

        with patch("requests.head", side_effect=lambda *a, **kw: next(responses)):
            result = _make().health_check()
        assert result["reachable"] is True


# ---------------------------------------------------------------------------
# get_module_urls()
# ---------------------------------------------------------------------------


class TestGetModuleUrls:
    @pytest.fixture(autouse=True)
    def _layout_probe_ok(self):
        """Every layout probe answers 200, so the configured image_path is kept."""
        with patch("requests.head", return_value=MagicMock(status_code=200)):
            yield

    def test_empty_when_no_modules_enabled(self):
        c = _make()
        assert c.get_module_urls() == {}

    def test_live_image_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {"live_image": {"enabled": True}}})
        with patch("requests.head", side_effect=_head_ok_for("/current/image.jpg")):
            urls = c.get_module_urls()
        assert "live_image" in urls
        assert urls["live_image"] == "http://allsky.local/current/image.jpg"

    def test_keogram_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {"keogram": {"enabled": True}}})
        urls = c.get_module_urls(date_str="20260101")
        assert urls["keogram"] == "http://allsky.local/images/20260101/keogram/keogram-20260101.jpg"

    def test_startrails_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {"startrails": {"enabled": True}}})
        urls = c.get_module_urls(date_str="20260101")
        assert "startrails" in urls

    def test_daily_timelapse_included_when_enabled(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {"daily_timelapse": {"enabled": True}}})
        urls = c.get_module_urls(date_str="20260101")
        assert "daily_timelapse" in urls

    def test_all_modules_enabled(self):
        c = _make_all_modules(enabled=True)
        urls = c.get_module_urls(date_str="20260101")
        assert sorted(urls) == ["daily_timelapse", "keogram", "live_image", "startrails"]  # sensor data: MQTT

    def test_date_defaults_to_last_night_when_not_provided(self):
        c = _make({"url": "http://allsky.local", "enabled": True, "modules": {"keogram": {"enabled": True}}})
        urls = c.get_module_urls()
        assert "keogram" in urls
        assert "/images/" in urls["keogram"] and "/keogram/keogram-" in urls["keogram"]


# ---------------------------------------------------------------------------
# fetch_sensor_data()
# ---------------------------------------------------------------------------


class TestFetchSensorData:
    def test_returns_empty_when_module_disabled(self):
        _plant_message({"AS_TEMPERATURE_C": 12.5})
        assert _make().fetch_sensor_data() == {}

    def test_returns_the_last_message_normalised_with_its_receive_time(self):
        """The real Publish Data payload comes back with DAY_OR_NIGHT and _received_at added."""
        received_at = _plant_message(REAL_PUBLISH_DATA_PAYLOAD)
        result = _sensor_connector().fetch_sensor_data()
        assert result["AS_TEMP"] == 25.0
        assert result["AS_DEWCONTROLHEATER"] is False
        assert result["DAY_OR_NIGHT"] == "DAY"
        assert result["_received_at"] == received_at
        assert {k: v for k, v in result.items() if k not in ("DAY_OR_NIGHT", "_received_at")} == (
            REAL_PUBLISH_DATA_PAYLOAD
        )

    def test_empty_until_a_message_arrives(self):
        assert _sensor_connector().fetch_sensor_data() == {}

    def test_stale_message_is_not_shown(self):
        """Readings older than MQTT_STALE_AFTER_SECONDS are dropped rather than shown as current."""
        _plant_message({"AS_TEMPERATURE_C": 12.5}, age_seconds=AllSkyConnector.MQTT_STALE_AFTER_SECONDS + 60)
        assert _sensor_connector().fetch_sensor_data() == {}

    def test_message_from_another_topic_is_ignored(self):
        """After a topic change, the message kept for the old one no longer counts."""
        _plant_message({"AS_TEMPERATURE_C": 12.5}, topic="old/topic")
        assert _sensor_connector(mqtt_topic="allsky").fetch_sensor_data() == {}

    def test_unreadable_receive_time_is_ignored(self):
        _plant_message({"AS_TEMPERATURE_C": 12.5}, received_at="not a date")
        assert _sensor_connector().fetch_sensor_data() == {}

    def test_naive_receive_time_is_read_as_utc(self):
        naive = (datetime.now(UTC) - timedelta(seconds=5)).replace(tzinfo=None).isoformat(timespec="seconds")
        _plant_message({"AS_TEMPERATURE_C": 12.5}, received_at=naive)
        assert _sensor_connector().fetch_sensor_data()["AS_TEMPERATURE_C"] == 12.5

    def test_prefix_less_keys_are_normalised(self):
        """A variable listed without AS_ (as the old v2026 Export wrote it) reads the same."""
        _plant_message({"TEMPERATURE_C": 12.5, "DAY_OR_NIGHT": "NIGHT"})
        result = _sensor_connector().fetch_sensor_data()
        assert result["AS_TEMPERATURE_C"] == 12.5
        assert result["DAY_OR_NIGHT"] == "NIGHT"


# ---------------------------------------------------------------------------
# MQTT configuration and subscriptions
# ---------------------------------------------------------------------------


class TestMqttConfig:
    def test_declares_a_connection_and_publish_data_defaults(self):
        assert AllSkyConnector.CONNECTION_FIELD == "mqtt_connection_id"
        assert AllSkyConnector.CONFIG_FIELDS["mqtt_topic"] == "allsky"
        assert "export_json_path" not in AllSkyConnector.CONFIG_FIELDS

    def test_topic_defaults_to_allsky(self):
        assert _make().mqtt_topic() == "allsky"
        assert _make({"mqtt_topic": "  "}).mqtt_topic() == "allsky"
        assert _make({"mqtt_topic": " obs/allsky "}).mqtt_topic() == "obs/allsky"

    @pytest.mark.parametrize(
        "topic, error",
        [
            ("allsky", None),
            ("observatory/allsky", None),
            ("", "topic required"),
            ("allsky/#", "topic must not contain + or # (an exact topic, no wildcard)"),
            ("+/allsky", "topic must not contain + or # (an exact topic, no wildcard)"),
            ("a\x00b", "topic must not contain + or # (an exact topic, no wildcard)"),
            ("t" * 257, "topic must be at most 256 characters"),
        ],
    )
    def test_topic_validation(self, topic, error):
        assert AllSkyConnector.topic_error(topic) == error

    def test_validate_config_checks_the_topic_and_accepts_the_default(self):
        assert AllSkyConnector.validate_config({"mqtt_topic": "allsky/#"}) is not None
        assert AllSkyConnector.validate_config({"mqtt_topic": ""}) is None  # blank = the default
        assert AllSkyConnector.validate_config({}) is None

    def test_subscribes_to_its_topic_when_enabled_with_a_connection(self):
        assert _sensor_connector(mqtt_topic="obs/allsky").mqtt_subscriptions() == ["obs/allsky"]

    @pytest.mark.parametrize(
        "connector",
        [
            lambda: _sensor_connector(connection=None),
            lambda: _sensor_connector(enabled=False),
            lambda: _sensor_connector(modules={"sensor_data": {"enabled": False}}),
            lambda: _sensor_connector(mqtt_topic="allsky/#"),
        ],
    )
    def test_no_subscription_otherwise(self, connector):
        """No connection, connector or module off, or an unusable topic: nothing to listen to."""
        assert connector().mqtt_subscriptions() == []

    def test_client_id_is_the_configured_one(self):
        assert _make({"client_id": " sky-1 "}).mqtt_client_id() == "sky-1"
        assert _make().mqtt_client_id() == ""


class TestSensorHealth:
    def test_fresh_message_is_ok(self):
        _plant_message({"AS_TEMP": 20}, age_seconds=30)
        health = _sensor_connector()._sensor_health()
        assert health["ok"] is True
        assert health["detail"].startswith("Last message ") and health["detail"].endswith(" on allsky")

    def test_no_message_points_at_publish_data(self):
        health = _sensor_connector()._sensor_health()
        assert health == {
            "ok": False,
            "detail": "No message received on allsky yet - check AllSky's Publish Data module",
        }

    def test_stale_message_points_at_the_periodic_jobs(self):
        _plant_message({"AS_TEMP": 20}, age_seconds=3600)
        health = _sensor_connector()._sensor_health()
        assert health["ok"] is False
        assert health["detail"] == ("Last message 60 min ago on allsky - is AllSky still capturing images?")

    def test_subscriber_error_or_disconnection_is_appended(self):
        _plant_status(connected=False, last_error="broker refused the connection: Not authorized")
        assert (
            _sensor_connector()._sensor_health()["detail"].endswith("(broker refused the connection: Not authorized)")
        )
        _plant_status(connected=False, last_error=None)
        assert _sensor_connector()._sensor_health()["detail"].endswith("(not connected to the broker)")

    def test_health_check_carries_the_sensor_line(self):
        _plant_message({"AS_TEMP": 20})
        with patch("requests.head", return_value=MagicMock(status_code=200)):
            result = _sensor_connector().health_check()
        assert result["modules"]["sensor_data"]["ok"] is True
        assert "url" not in result["modules"]["sensor_data"]


# ---------------------------------------------------------------------------
# _normalize_sensor_data()
# ---------------------------------------------------------------------------


class TestNormalizeSensorData:
    def test_legacy_payload_unchanged(self):
        data = {"AS_TEMPERATURE_C": "12.5", "AS_GAIN": "100", "DAY_OR_NIGHT": "NIGHT", "ALLSKY_VERSION": "v2024.12"}
        result = _normalize_sensor_data(data)
        for key, value in data.items():
            assert result[key] == value

    def test_unprefixed_keys_get_as_alias(self):
        result = _normalize_sensor_data({"TEMPERATURE_C": 3.2, "sEXPOSURE": "1/250", "DEWCONTROLHUMIDITY": 81})
        assert result["AS_TEMPERATURE_C"] == 3.2
        assert result["AS_sEXPOSURE"] == "1/250"
        assert result["AS_DEWCONTROLHUMIDITY"] == 81

    def test_existing_as_key_wins_over_alias(self):
        result = _normalize_sensor_data({"GAIN": 1, "AS_GAIN": 2})
        assert result["AS_GAIN"] == 2

    def test_allsky_keys_not_prefixed(self):
        result = _normalize_sensor_data({"ALLSKY_VERSION": "v2026.10.01"})
        assert "AS_ALLSKY_VERSION" not in result

    def test_day_or_night_from_prefixed_key(self):
        assert _normalize_sensor_data({"AS_DAY_OR_NIGHT": "DAY"})["DAY_OR_NIGHT"] == "DAY"

    def test_null_values_kept(self):
        """v2026 writes null for a requested variable it cannot find; the UI skips nulls."""
        result = _normalize_sensor_data({"DEWCONTROLHEATER": None})
        assert result["AS_DEWCONTROLHEATER"] is None

    @pytest.mark.parametrize("payload", [None, [], "text", 42])
    def test_non_dict_payload_gives_empty(self, payload):
        assert _normalize_sensor_data(payload) == {}


# ---------------------------------------------------------------------------
# AllSky layout detection (current/ vs legacy current/tmp/)
# ---------------------------------------------------------------------------


class TestLayoutDetection:
    def _live(self, image_path=None):
        cfg = {"url": "http://allsky.local", "enabled": True, "modules": {"live_image": {"enabled": True}}}
        if image_path is not None:
            cfg["image_path"] = image_path
        return _make(cfg)

    def test_new_layout_with_new_default(self):
        with patch("requests.head", side_effect=_head_ok_for("/current/image.jpg")):
            urls = self._live().get_module_urls()
        assert urls["live_image"] == "http://allsky.local/current/image.jpg"

    def test_legacy_allsky_with_new_default_falls_back(self):
        """AllSky v2024.12 serves the live image under current/tmp/ only."""
        with patch("requests.head", side_effect=_head_ok_for("/current/tmp/image.jpg")):
            urls = self._live().get_module_urls()
        assert urls["live_image"] == "http://allsky.local/current/tmp/image.jpg"

    def test_upgraded_allsky_with_legacy_saved_path(self):
        """A config saved before v2026 keeps image_path=current/tmp; the new layout is still found."""
        with patch("requests.head", side_effect=_head_ok_for("/current/image.jpg")):
            urls = self._live("current/tmp").get_module_urls()
        assert urls["live_image"] == "http://allsky.local/current/image.jpg"

    def test_legacy_allsky_with_legacy_saved_path_probes_once(self):
        with patch("requests.head", side_effect=_head_ok_for("/current/tmp/image.jpg")) as head:
            urls = self._live("current/tmp").get_module_urls()
        assert urls["live_image"] == "http://allsky.local/current/tmp/image.jpg"
        assert head.call_count == 1

    def test_custom_path_is_not_probed(self):
        with patch("requests.head") as head:
            urls = self._live("/my/folder/").get_module_urls()
        assert urls["live_image"] == "http://allsky.local/my/folder/image.jpg"
        head.assert_not_called()

    def test_nothing_reachable_keeps_configured_path(self):
        with patch("requests.head", side_effect=_requests.exceptions.ConnectionError):
            urls = self._live("current/tmp").get_module_urls()
        assert urls["live_image"] == "http://allsky.local/current/tmp/image.jpg"

    def test_resolution_is_cached(self):
        connector = self._live()
        with patch("requests.head", side_effect=_head_ok_for("/current/tmp/image.jpg")) as head:
            connector.get_module_urls()
            calls = head.call_count
            connector.get_module_urls()
            _make(connector.config).get_module_urls()
        assert head.call_count == calls

    def test_cache_expires(self):
        connector = self._live()
        with patch("requests.head", side_effect=_head_ok_for("/current/tmp/image.jpg")) as head:
            connector.get_module_urls()
            calls = head.call_count
            with patch("connectors.allsky_connector.time.time", return_value=10**12):
                connector.get_module_urls()
        assert head.call_count > calls

    def test_health_check_reports_fallback_url(self):
        with patch("requests.head", side_effect=_head_ok_for("/current/tmp/image.jpg")):
            result = self._live().health_check()
        assert result["modules"]["live_image"]["ok"] is True
        assert result["modules"]["live_image"]["url"] == "http://allsky.local/current/tmp/image.jpg"

    def test_health_check_reprobes_despite_cache(self):
        connector = self._live()
        with patch("requests.head", side_effect=_head_ok_for("/current/tmp/image.jpg")):
            connector.get_module_urls()
        with patch("requests.head", side_effect=_head_ok_for("/current/image.jpg")):
            result = connector.health_check()
            urls = connector.get_module_urls()
        assert result["modules"]["live_image"]["url"] == "http://allsky.local/current/image.jpg"
        assert urls["live_image"] == "http://allsky.local/current/image.jpg"
