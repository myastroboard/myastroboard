"""Tests for weather_openmeteo.py — rate-limit helpers and forecast functions."""
import time
from unittest.mock import MagicMock

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

    def test_transient_error_logs_warning(self, monkeypatch):
        """Covers line 278: transient API error branch."""
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: (_ for _ in ()).throw(Exception("503 Service Unavailable")))
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )
        result = wom.get_hourly_forecast()
        assert result is None
        wom._FORECAST_LAST_FAILURE_TS = 0.0


# ---------------------------------------------------------------------------
# Shared helpers for parse_hourly tests
# ---------------------------------------------------------------------------

_FULL_HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "precipitation_probability", "precipitation", "rain", "weather_code",
    "visibility", "wind_speed_10m", "wind_direction_10m",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "lifted_index", "sunshine_duration", "is_day", "uv_index", "surface_pressure",
]


def _make_parse_hourly_response(n_hours: int = 3, humidity: float = 65.0):
    """Build a minimal mock response for parse_hourly."""
    import numpy as np
    import pandas as pd

    hourly = MagicMock()
    start_ts = int(pd.Timestamp("2026-06-04T00:00:00", tz="UTC").timestamp())
    hourly.Time.return_value = start_ts
    hourly.Interval.return_value = 3600

    defaults = {
        "temperature_2m": np.full(n_hours, 15.0),
        "relative_humidity_2m": np.full(n_hours, humidity),
        "dew_point_2m": np.full(n_hours, 8.0),
        "precipitation_probability": np.full(n_hours, 10.0),
        "precipitation": np.zeros(n_hours),
        "rain": np.zeros(n_hours),
        "weather_code": np.ones(n_hours),
        "visibility": np.full(n_hours, 20000.0),
        "wind_speed_10m": np.full(n_hours, 5.0),
        "wind_direction_10m": np.full(n_hours, 180.0),
        "cloud_cover": np.full(n_hours, 20.0),
        "cloud_cover_low": np.full(n_hours, 5.0),
        "cloud_cover_mid": np.full(n_hours, 10.0),
        "cloud_cover_high": np.zeros(n_hours),
        "lifted_index": np.full(n_hours, 3.0),
        "sunshine_duration": np.full(n_hours, 1800.0),
        "is_day": np.ones(n_hours),
        "uv_index": np.full(n_hours, 2.0),
        "surface_pressure": np.full(n_hours, 1013.0),
    }

    var_mocks = []
    for name in _FULL_HOURLY_VARS:
        v = MagicMock()
        v.ValuesAsNumpy.return_value = defaults[name]
        var_mocks.append(v)

    hourly.Variables.side_effect = lambda i: var_mocks[i]
    response = MagicMock()
    response.Hourly.return_value = hourly
    return response


class TestFetchWeather:
    """Tests for fetch_weather — covers lines 95 and 106."""

    def test_use_cache_false_calls_fresh_client(self, monkeypatch):
        """Cover line 95: create_fresh_weather_client path."""
        mock_response = MagicMock()
        mock_client = MagicMock()
        mock_client.weather_api.return_value = [mock_response]
        monkeypatch.setattr(wom, 'create_fresh_weather_client', lambda: mock_client)
        result = wom.fetch_weather(45.5, -73.5, "UTC", ["temperature_2m"], use_cache=False)
        assert result is mock_response
        mock_client.weather_api.assert_called_once()

    def test_use_cache_true_calls_cached_client(self, monkeypatch):
        """Cover line 93 and line 106."""
        mock_response = MagicMock()
        mock_client = MagicMock()
        mock_client.weather_api.return_value = [mock_response]
        monkeypatch.setattr(wom, 'create_weather_client', lambda: mock_client)
        result = wom.fetch_weather(45.5, -73.5, "UTC", ["temperature_2m"], use_cache=True)
        assert result is mock_response


class TestParseHourly:
    """Tests for parse_hourly — covers lines 112-203."""

    def test_returns_dataframe(self):
        import pandas as pd
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        assert isinstance(result, pd.DataFrame)

    def test_has_cloudless_columns(self):
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        for col in ("cloudless", "cloudless_low", "cloudless_mid", "cloudless_high"):
            assert col in result.columns

    def test_has_derived_metrics(self):
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        for col in ("condition", "seeing", "transparency", "calm", "fog"):
            assert col in result.columns

    def test_cloudless_is_complement_of_cloud_cover(self):
        import numpy as np
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        assert np.allclose(result["cloudless"].values, 100 - result["cloud_cover"].values)

    def test_timezone_conversion_to_local(self):
        """Cover the tz_convert branch (line 137)."""
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS, timezone_str="America/Montreal")
        assert "date" in result.columns

    def test_invalid_timezone_keeps_utc(self):
        """Cover the ZoneInfoNotFoundError branch (line 138-139)."""
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS, timezone_str="Invalid/Zone")
        assert "date" in result.columns

    def test_utc_timezone_no_conversion(self):
        """Cover the 'if timezone_str and timezone_str != UTC' false branch."""
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS, timezone_str="UTC")
        assert "date" in result.columns

    def test_none_timezone_kept_as_utc(self):
        """Cover timezone_str=None path."""
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS, timezone_str=None)
        assert "date" in result.columns

    def test_fog_high_humidity(self):
        """Cover fog mask1 branch: relative_humidity > 90."""
        response = _make_parse_hourly_response(humidity=95.0)
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        assert all(result["fog"] > 0)

    def test_fog_medium_humidity(self):
        """Cover fog mask2 branch: relative_humidity in (80, 90]."""
        response = _make_parse_hourly_response(humidity=85.0)
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        assert all(result["fog"] > 0)

    def test_row_count_matches_n_hours(self):
        response = _make_parse_hourly_response(n_hours=6)
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        assert len(result) == 6

    def test_condition_values_are_0_to_100(self):
        response = _make_parse_hourly_response()
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)
        assert result["condition"].between(0, 100).all()


class TestGetSkytonightConditions:
    """Tests for get_skytonight_conditions — covers lines 292-338."""

    def test_returns_conditions_on_success(self, monkeypatch, tmp_path):
        """Cover success path (lines 292-334)."""
        import numpy as np

        hourly = MagicMock()
        t_var = MagicMock()
        t_var.ValuesAsNumpy.return_value = np.array([18.5])
        h_var = MagicMock()
        h_var.ValuesAsNumpy.return_value = np.array([65.0])
        p_var = MagicMock()
        p_var.ValuesAsNumpy.return_value = np.array([101300.0])
        hourly.Variables.side_effect = lambda i: [t_var, h_var, p_var][i]

        response = MagicMock()
        response.Hourly.return_value = hourly

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: response)
        monkeypatch.setattr(
            wom, 'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )
        monkeypatch.setattr(wom, 'CONDITIONS_FILE', str(tmp_path / 'conditions.json'))

        result = wom.get_skytonight_conditions()
        assert result is not None
        assert "temperature" in result
        assert "relative_humidity" in result
        assert "pressure" in result
        assert result["temperature"] == pytest.approx(18.5, abs=0.1)

    def test_returns_none_when_hourly_is_none(self, monkeypatch):
        """Cover the ValueError branch (line 308-309)."""
        response = MagicMock()
        response.Hourly.return_value = None

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: response)
        monkeypatch.setattr(
            wom, 'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )

        result = wom.get_skytonight_conditions()
        assert result is None

    def test_returns_none_on_fetch_exception(self, monkeypatch):
        """Cover the except branch (line 336-338)."""
        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: (_ for _ in ()).throw(Exception("network error")))
        monkeypatch.setattr(
            wom, 'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )

        result = wom.get_skytonight_conditions()
        assert result is None

    def test_returns_none_when_hourly_variables_none(self, monkeypatch):
        """Line 317: hourly not None but Variables(0) returns None → ValueError → None."""
        response = MagicMock()
        hourly = MagicMock()
        hourly.Variables.return_value = None  # all Variables(n) return None
        response.Hourly.return_value = hourly

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: response)
        monkeypatch.setattr(
            wom, 'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )

        result = wom.get_skytonight_conditions()
        assert result is None


class TestParseHourlyTimezoneExceptionBranch:
    """Lines 142-143: outer except in parse_hourly timezone conversion."""

    def test_generic_exception_in_tz_convert_keeps_utc(self, monkeypatch):
        """Lines 142-143: non-ZoneInfoNotFoundError in inner block → outer except."""
        response = _make_parse_hourly_response()
        # Patch zoneinfo.ZoneInfo to raise a generic Exception (not ZoneInfoNotFoundError)
        # so it propagates out of the inner try (which only catches ZoneInfoNotFoundError)
        # and is caught by the outer except at line 142.
        monkeypatch.setattr('zoneinfo.ZoneInfo', lambda tz: (_ for _ in ()).throw(Exception("zoneinfo fail")))
        result = wom.parse_hourly(response, _FULL_HOURLY_VARS, timezone_str="America/Montreal")
        assert result is not None  # falls back to UTC, still returns dataframe
