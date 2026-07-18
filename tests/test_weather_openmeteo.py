"""Tests for weather_openmeteo.py — rate-limit helpers and forecast functions."""
import time
from unittest.mock import MagicMock

import pytest

from weather import weather_openmeteo as wom


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

    def test_metadata_accessor_failure_falls_back_to_location(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        location = {
            'id': 'mk',
            'latitude': 19.822222,
            'longitude': 155.475,
            'timezone': 'Pacific/Honolulu',
            'name': 'Mauna Kea',
        }

        mock_response = MagicMock()
        mock_response.Latitude.side_effect = Exception("Invalid value '[ 6.95 ... ]' for")
        mock_response.Longitude.return_value = 155.475
        mock_response.Elevation.return_value = 4205.0
        mock_response.Timezone.side_effect = Exception("Invalid value '[ 6.95 ... ]' for")

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: mock_response)
        monkeypatch.setattr(wom, 'parse_hourly', lambda resp, vars, timezone_str=None: MagicMock())
        result = wom.get_hourly_forecast(location=location)

        assert result is not None
        assert result['location']['latitude'] == pytest.approx(19.822222)
        assert result['location']['timezone'] == 'Pacific/Honolulu'

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
        monkeypatch.setattr(wom.requests, 'get', lambda *a, **kw: (_ for _ in ()).throw(Exception("API down")))
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
        monkeypatch.setattr(wom.requests, 'get', lambda *a, **kw: (_ for _ in ()).throw(Exception("503 Service Unavailable")))
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}},
        )
        result = wom.get_hourly_forecast()
        assert result is None
        wom._FORECAST_LAST_FAILURE_TS = 0.0

    def test_fallback_to_core_vars_when_full_request_fails(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        mock_response = MagicMock()
        mock_response.Latitude.return_value = 19.0
        mock_response.Longitude.return_value = 155.0
        mock_response.Elevation.return_value = 4205.0
        mock_response.Timezone.return_value = "Pacific/Honolulu"

        calls = []

        def fake_fetch_weather(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise Exception("Invalid value '[ 6.95 ... ]' for")
            return mock_response

        monkeypatch.setattr(wom, 'fetch_weather', fake_fetch_weather)
        monkeypatch.setattr(wom, 'parse_hourly', lambda resp, vars, timezone_str=None: MagicMock())
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {'location': {'latitude': 19.0, 'longitude': 155.0, 'timezone': 'Pacific/Honolulu', 'name': 'MK'}},
        )

        result = wom.get_hourly_forecast()

        assert result is not None
        assert len(calls) == 2
        assert calls[1].get('use_cache') is False

    def test_fallback_to_core_when_full_parse_fails(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        mock_response = MagicMock()
        mock_response.Latitude.return_value = 19.0
        mock_response.Longitude.return_value = 155.0
        mock_response.Elevation.return_value = 4205.0
        mock_response.Timezone.return_value = "Pacific/Honolulu"

        calls = []

        def fake_fetch_weather(**kw):
            calls.append(kw)
            return mock_response

        parse_calls = {"n": 0}

        def fake_parse_hourly(resp, vars, timezone_str=None):
            parse_calls["n"] += 1
            if parse_calls["n"] == 1:
                raise Exception("Invalid value '[ 6.95 ... ]' for")
            return MagicMock()

        monkeypatch.setattr(wom, 'fetch_weather', fake_fetch_weather)
        monkeypatch.setattr(wom, 'parse_hourly', fake_parse_hourly)
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {'location': {'latitude': 19.0, 'longitude': 155.0, 'timezone': 'Pacific/Honolulu', 'name': 'MK'}},
        )

        result = wom.get_hourly_forecast()

        assert result is not None
        assert len(calls) == 2
        assert calls[1].get('use_cache') is False

    def test_fallback_to_json_when_sdk_requests_fail(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0

        calls = []

        def fake_fetch_weather(**kw):
            calls.append(kw)
            raise Exception("Invalid value '[ 6.95 ... ]' for")

        class _MockJsonResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "latitude": 19.0,
                    "longitude": 155.0,
                    "elevation": 4205.0,
                    "timezone": "Pacific/Honolulu",
                    "hourly": {
                        "time": [
                            "2026-07-16T13:00",
                            "2026-07-16T14:00",
                        ],
                        "temperature_2m": [10.0, 9.0],
                        "relative_humidity_2m": [70.0, 72.0],
                        "precipitation_probability": [20.0, 30.0],
                        "precipitation": [0.0, 0.1],
                        "rain": [0.0, 0.1],
                        "weather_code": [1, 2],
                        "visibility": [20000, 18000],
                        "wind_speed_10m": [6.9, 10.5],
                        "wind_direction_10m": [120, 150],
                        "cloud_cover": [10, 20],
                        "cloud_cover_low": [5, 10],
                        "cloud_cover_mid": [10, 15],
                        "cloud_cover_high": [0, 5],
                        "is_day": [1, 1],
                    },
                }

        monkeypatch.setattr(wom, 'fetch_weather', fake_fetch_weather)
        monkeypatch.setattr(wom.requests, 'get', lambda *a, **kw: _MockJsonResponse())
        monkeypatch.setattr(
            wom,
            'load_config',
            lambda: {'location': {'latitude': 19.0, 'longitude': 155.0, 'timezone': 'Pacific/Honolulu', 'name': 'MK'}},
        )

        result = wom.get_hourly_forecast()

        assert result is not None
        assert len(calls) == 2
        assert len(result["hourly"]) == 2


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

    def test_variable_decode_error_is_non_fatal(self):
        response = _make_parse_hourly_response(n_hours=3)
        hourly = response.Hourly.return_value

        # Simulate SDK decode crash for one variable that previously aborted the whole parse.
        hourly.Variables(8).ValuesAsNumpy.side_effect = Exception("Invalid value '[ 6.95 ... ]' for")

        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)

        assert len(result) == 3
        assert "condition" in result.columns

    def test_nested_hourly_array_is_coerced(self):
        import numpy as np

        response = _make_parse_hourly_response(n_hours=3)
        hourly = response.Hourly.return_value

        # Simulate malformed API payload for a single variable: nested array + wrong length.
        hourly.Variables(8).ValuesAsNumpy.return_value = np.array([[6.9, 10.5]])

        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)

        assert len(result) == 3
        assert result["wind_speed_10m"].iloc[2] == pytest.approx(0.0)


class TestGetSkytonightConditions:
    """Tests for get_skytonight_conditions (v1.2: per-location debounce)."""

    # Explicit preset payload: v1.2 signature takes the caller's active
    # location; passing it directly avoids depending on load_config().
    _LOCATION = {'id': 'wom-test-loc', 'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC', 'name': 'Test'}

    @pytest.fixture(autouse=True)
    def _clear_debounce(self, monkeypatch):
        """Isolate the per-location debounce window between tests - a success
        stored by one test must not be served to the next one."""
        monkeypatch.setattr(wom, '_SKYTONIGHT_CONDITIONS_DEBOUNCE', {})

    def test_returns_conditions_on_success(self, monkeypatch, tmp_path):
        """Cover the success path (fetch → parse → persist → debounce)."""
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
        monkeypatch.setattr(wom, 'CONDITIONS_FILE', str(tmp_path / 'conditions.json'))

        result = wom.get_skytonight_conditions(location=self._LOCATION)
        assert result is not None
        assert "temperature" in result
        assert "relative_humidity" in result
        assert "pressure" in result
        assert result["temperature"] == pytest.approx(18.5, abs=0.1)

    def test_debounce_serves_cached_result_without_refetch(self, monkeypatch, tmp_path):
        """Second call within the debounce window must NOT hit Open-Meteo again."""
        import numpy as np

        hourly = MagicMock()
        var = MagicMock()
        var.ValuesAsNumpy.return_value = np.array([10.0])
        hourly.Variables.side_effect = lambda i: var

        response = MagicMock()
        response.Hourly.return_value = hourly

        fetch_calls = []

        def counting_fetch(**kw):
            fetch_calls.append(1)
            return response

        monkeypatch.setattr(wom, 'fetch_weather', counting_fetch)
        monkeypatch.setattr(wom, 'CONDITIONS_FILE', str(tmp_path / 'conditions.json'))

        first = wom.get_skytonight_conditions(location=self._LOCATION)
        second = wom.get_skytonight_conditions(location=self._LOCATION)
        assert first is not None
        assert second == first
        assert len(fetch_calls) == 1

    def test_falls_back_to_install_default_without_location(self, monkeypatch):
        """No/invalid location argument → resolves the install default preset."""
        resolved = {}

        def fake_install_default(_config):
            resolved['called'] = True
            return dict(self._LOCATION)

        monkeypatch.setattr(wom, 'load_config', lambda: {'locations': [dict(self._LOCATION)]})
        monkeypatch.setattr(wom, 'get_install_default_location', fake_install_default)
        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: (_ for _ in ()).throw(Exception("stop here")))

        result = wom.get_skytonight_conditions()
        assert result is None  # fetch failed on purpose - we only assert resolution
        assert resolved.get('called') is True

    def test_returns_none_when_hourly_is_none(self, monkeypatch):
        """Cover the ValueError branch (hourly missing)."""
        response = MagicMock()
        response.Hourly.return_value = None

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: response)

        result = wom.get_skytonight_conditions(location=self._LOCATION)
        assert result is None

    def test_returns_none_on_fetch_exception(self, monkeypatch):
        """Cover the except branch."""
        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: (_ for _ in ()).throw(Exception("network error")))

        result = wom.get_skytonight_conditions(location=self._LOCATION)
        assert result is None

    def test_returns_none_when_hourly_variables_none(self, monkeypatch):
        """hourly not None but Variables(0) returns None → ValueError → None."""
        response = MagicMock()
        hourly = MagicMock()
        hourly.Variables.return_value = None  # all Variables(n) return None
        response.Hourly.return_value = hourly

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: response)

        result = wom.get_skytonight_conditions(location=self._LOCATION)
        assert result is None


class TestParseHourlyAllVariablesFail:
    """Lines 123-127: every hourly variable fails to decode -> ValueError."""

    def test_raises_when_every_variable_decode_fails(self):
        response = _make_parse_hourly_response(n_hours=3)
        hourly = response.Hourly.return_value
        for i in range(len(_FULL_HOURLY_VARS)):
            hourly.Variables(i).ValuesAsNumpy.side_effect = Exception("decode failure")

        with pytest.raises(ValueError, match="Unable to decode"):
            wom.parse_hourly(response, _FULL_HOURLY_VARS)


class TestParseHourlyLongerArrayTruncated:
    """Line 150: a variable longer than expected_len is truncated, not padded."""

    def test_longer_array_is_truncated(self):
        import numpy as np

        response = _make_parse_hourly_response(n_hours=3)
        hourly = response.Hourly.return_value
        hourly.Variables(8).ValuesAsNumpy.return_value = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        result = wom.parse_hourly(response, _FULL_HOURLY_VARS)

        assert len(result) == 3
        assert result["wind_speed_10m"].tolist() == [1.0, 2.0, 3.0]


class TestFetchWeatherJson:
    """Tests for fetch_weather_json — the plain-HTTP fallback (line 262)."""

    def test_raises_when_hourly_payload_missing(self, monkeypatch):
        class _MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"latitude": 1.0, "longitude": 2.0}  # no 'hourly' key

        monkeypatch.setattr(wom.requests, 'get', lambda *a, **kw: _MockResponse())
        with pytest.raises(ValueError, match="missing hourly payload"):
            wom.fetch_weather_json(1.0, 2.0, "UTC", ["temperature_2m"])

    def test_raises_when_payload_not_a_dict(self, monkeypatch):
        class _MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return ["not", "a", "dict"]

        monkeypatch.setattr(wom.requests, 'get', lambda *a, **kw: _MockResponse())
        with pytest.raises(ValueError, match="missing hourly payload"):
            wom.fetch_weather_json(1.0, 2.0, "UTC", ["temperature_2m"])


class TestParseHourlyJson:
    """Tests for parse_hourly_json — the plain-HTTP fallback parser."""

    _CORE_VARS = [
        "temperature_2m", "relative_humidity_2m", "precipitation_probability",
        "precipitation", "rain", "weather_code", "visibility", "wind_speed_10m",
        "wind_direction_10m", "cloud_cover", "cloud_cover_low", "cloud_cover_mid",
        "cloud_cover_high", "is_day",
    ]

    def _payload(self, n_hours=2, **overrides):
        base: dict = {
            "time": [f"2026-06-04T{h:02d}:00" for h in range(n_hours)],
        }
        for name in self._CORE_VARS:
            base[name] = [1.0] * n_hours
        base.update(overrides)
        return {"hourly": base}

    def test_raises_when_time_series_missing(self):
        with pytest.raises(ValueError, match="hourly time series is missing"):
            wom.parse_hourly_json({"hourly": {}}, self._CORE_VARS)

    def test_raises_when_time_series_empty_list(self):
        with pytest.raises(ValueError, match="hourly time series is missing"):
            wom.parse_hourly_json({"hourly": {"time": []}}, self._CORE_VARS)

    def test_raises_when_timestamps_unparseable(self):
        payload = self._payload(n_hours=2, time=["not-a-date", "also-not-a-date"])
        with pytest.raises(ValueError, match="unable to parse hourly timestamps"):
            wom.parse_hourly_json(payload, self._CORE_VARS)

    def test_shorter_field_is_padded_with_nan(self):
        payload = self._payload(n_hours=3)
        payload["hourly"]["temperature_2m"] = [10.0, 11.0]  # shorter than the 3-hour time series

        result = wom.parse_hourly_json(payload, self._CORE_VARS)

        assert len(result) == 3
        assert result["temperature_2m"].isna().iloc[-1]

    def test_longer_field_is_truncated(self):
        payload = self._payload(n_hours=2)
        payload["hourly"]["temperature_2m"] = [10.0, 11.0, 12.0, 13.0]  # longer than the 2-hour time series

        result = wom.parse_hourly_json(payload, self._CORE_VARS)

        assert len(result) == 2
        assert result["temperature_2m"].tolist() == [10.0, 11.0]

    def test_returns_dataframe_with_derived_metrics(self):
        payload = self._payload(n_hours=2)
        result = wom.parse_hourly_json(payload, self._CORE_VARS)
        for col in ("condition", "seeing", "transparency", "cloudless"):
            assert col in result.columns


class TestMetadataAccessorFailures:
    """Longitude/Elevation decode failures (lines 385-387, 391-392) - mirrors the
    existing Latitude-failure test above."""

    def test_longitude_decode_failure_falls_back_to_location(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        location = {
            'id': 'test-loc', 'latitude': 45.5, 'longitude': -73.5,
            'timezone': 'UTC', 'name': 'Test',
        }

        mock_response = MagicMock()
        mock_response.Latitude.return_value = 45.5
        mock_response.Longitude.side_effect = Exception("Invalid value for longitude")
        mock_response.Elevation.return_value = 50.0
        mock_response.Timezone.return_value = "UTC"

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: mock_response)
        monkeypatch.setattr(wom, 'parse_hourly', lambda resp, vars, timezone_str=None: MagicMock())

        result = wom.get_hourly_forecast(location=location)

        assert result is not None
        assert result['location']['longitude'] == pytest.approx(-73.5)

    def test_elevation_decode_failure_falls_back_to_none(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        location = {
            'id': 'test-loc', 'latitude': 45.5, 'longitude': -73.5,
            'timezone': 'UTC', 'name': 'Test',
        }

        mock_response = MagicMock()
        mock_response.Latitude.return_value = 45.5
        mock_response.Longitude.return_value = -73.5
        mock_response.Elevation.side_effect = Exception("Invalid value for elevation")
        mock_response.Timezone.return_value = "UTC"

        monkeypatch.setattr(wom, 'fetch_weather', lambda **kw: mock_response)
        monkeypatch.setattr(wom, 'parse_hourly', lambda resp, vars, timezone_str=None: MagicMock())

        result = wom.get_hourly_forecast(location=location)

        assert result is not None
        assert result['location']['elevation'] is None


class TestCoreFallbackConcurrencyReraise:
    """Line 451: a concurrency error on the core-variable retry must propagate,
    not fall through to the JSON fallback.

    Note this is a DIFFERENT trigger than a concurrency error on the *full*
    request: that one re-raises immediately (line 431) and never reaches the
    core retry at all. To exercise line 451 specifically, the full request
    must fail with a non-concurrency error (so it falls through to the core
    retry), and the core retry itself must then hit the concurrency limit.
    """

    def test_concurrency_error_on_core_retry_propagates(self, monkeypatch):
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        wom._GLOBAL_CONCURRENCY_TS = 0.0
        location = {
            'id': 'test-loc', 'latitude': 45.5, 'longitude': -73.5,
            'timezone': 'UTC', 'name': 'Test',
        }

        calls = []

        def fake_fetch_weather(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise Exception("Invalid value for some field")  # non-concurrency -> falls through
            raise Exception("Too many concurrent requests")  # concurrency error on the core retry

        json_calls = []
        monkeypatch.setattr(wom.requests, 'get', lambda *a, **kw: json_calls.append(1))
        monkeypatch.setattr(wom, 'fetch_weather', fake_fetch_weather)

        result = wom.get_hourly_forecast(location=location)

        assert result is None
        assert len(calls) == 2  # full request (non-concurrency), then core retry (concurrency)
        assert json_calls == []  # never reached the JSON fallback
        assert wom._GLOBAL_CONCURRENCY_TS > 0
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        wom._GLOBAL_CONCURRENCY_TS = 0.0
        wom._FORECAST_LAST_FAILURE_TS = 0.0
        wom._GLOBAL_CONCURRENCY_TS = 0.0


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
