"""Tests for weather_openmeteo.py — rate-limit helpers and forecast functions."""
import time
from unittest.mock import MagicMock, patch

import pytest

import weather_openmeteo as wom


class TestRateLimitHelpers:

    def test_is_rate_limited_false_by_default(self):
        wom._GLOBAL_CONCURRENCY_TS = 0.0
        assert wom.is_openmeteo_rate_limited() is False

    def test_record_sets_timestamp(self):
        wom._GLOBAL_CONCURRENCY_TS = 0.0
        wom.record_openmeteo_rate_limit()
        assert wom._GLOBAL_CONCURRENCY_TS > 0
        assert wom.is_openmeteo_rate_limited() is True

    def test_clear_resets_timestamp(self):
        wom.record_openmeteo_rate_limit()
        wom.clear_openmeteo_rate_limit()
        assert wom._GLOBAL_CONCURRENCY_TS == 0.0
        assert wom.is_openmeteo_rate_limited() is False

    def test_is_concurrency_error_detected(self):
        exc = Exception("Too many concurrent requests")
        assert wom._is_openmeteo_concurrency_error(exc) is True

    def test_is_transient_error_detected(self):
        exc = Exception("503 Service Unavailable")
        assert wom._is_openmeteo_transient_error(exc) is True

    def test_is_transient_error_false_for_other(self):
        exc = Exception("Something completely different")
        assert wom._is_openmeteo_transient_error(exc) is False


class TestGetHourlyForecastCooldowns:

    def test_returns_none_during_failure_cooldown(self):
        wom._FORECAST_LAST_FAILURE_TS = time.time()  # just failed
        result = wom.get_hourly_forecast()
        assert result is None
        wom._FORECAST_LAST_FAILURE_TS = 0.0  # reset

    def test_returns_none_when_lock_held(self):
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        wom._FORECAST_LOCK.acquire()
        try:
            result = wom.get_hourly_forecast()
            assert result is None
        finally:
            wom._FORECAST_LOCK.release()

    def test_timezone_none_defaults_to_utc(self, monkeypatch):
        """Covers line 264: timezone_str = 'UTC' when Timezone() returns None."""
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        mock_response = MagicMock()
        mock_response.Latitude.return_value = 45.5
        mock_response.Longitude.return_value = -73.5
        mock_response.Elevation.return_value = 50.0
        mock_response.Timezone.return_value = None  # triggers line 264

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: mock_response)
        monkeypatch.setattr(wom, 'parse_hourly', lambda resp, vars, timezone_str=None: MagicMock())
        monkeypatch.setattr(
            wom, 'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )
        result = wom.get_hourly_forecast()
        assert result is not None

    def test_returns_data_when_fetch_succeeds(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        mock_response = MagicMock()
        mock_response.Latitude.return_value = 45.5
        mock_response.Longitude.return_value = -73.5
        mock_response.Elevation.return_value = 50.0
        mock_response.Timezone.return_value = b'America/Montreal'

        hourly_mock = MagicMock()
        hourly_mock.Time.return_value = 0
        hourly_mock.TimeEnd.return_value = 3600
        hourly_mock.Interval.return_value = 3600
        hourly_mock.Variables.return_value = MagicMock(ValuesAsNumpy=lambda: [])
        mock_response.Hourly.return_value = hourly_mock

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: mock_response)
        monkeypatch.setattr(wom, 'parse_hourly', lambda resp, vars, timezone_str=None: MagicMock())
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {
                'location': {
                    'latitude': 45.5,
                    'longitude': -73.5,
                    'timezone': 'America/Montreal',
                    'name': 'Test',
                }
            },
        )
        result = wom.get_hourly_forecast()
        assert result is not None
        assert 'location' in result

    def test_concurrency_error_triggers_rate_limit(self, monkeypatch):
        """Covers line 275: record_openmeteo_rate_limit() on concurrency error."""
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        wom._GLOBAL_CONCURRENCY_TS = 0.0

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: (_ for _ in ()).throw(Exception("Too many concurrent requests")))
        monkeypatch.setattr(
            wom, 'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )
        result = wom.get_hourly_forecast()
        assert result is None
        assert wom._GLOBAL_CONCURRENCY_TS > 0  # rate limit was recorded
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        wom._GLOBAL_CONCURRENCY_TS = 0.0

    def test_fetch_failure_sets_failure_timestamp(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: (_ for _ in ()).throw(Exception("API down")))
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {
                'location': {
                    'latitude': 45.5,
                    'longitude': -73.5,
                    'timezone': 'UTC',
                    'name': 'Test',
                }
            },
        )
        result = wom.get_hourly_forecast()
        assert result is None
        assert wom._FORECAST_LAST_FAILURE_TS > 0
        wom._FORECAST_LAST_FAILURE_TS = 0.0
