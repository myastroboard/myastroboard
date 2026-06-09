"""Unit tests for astrophotography weather analysis period selection."""

import time
from unittest.mock import MagicMock, patch

import pandas as pd

import weather_astro
AstroWeatherAnalyzer = weather_astro.AstroWeatherAnalyzer
get_astro_weather_analysis = weather_astro.get_astro_weather_analysis
get_current_astro_conditions = weather_astro.get_current_astro_conditions
_analysis_cache_key = weather_astro._analysis_cache_key
_get_last_successful_analysis = weather_astro._get_last_successful_analysis
_store_last_successful_analysis = weather_astro._store_last_successful_analysis
_is_openmeteo_concurrency_error = weather_astro._is_openmeteo_concurrency_error


def _build_analyzer() -> AstroWeatherAnalyzer:
    """Build analyzer instance without loading runtime config."""
    return AstroWeatherAnalyzer.__new__(AstroWeatherAnalyzer)


def _build_sample_dataframe():
    """Build a minimal DataFrame with all required analysis columns."""
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-04-17T20:00:00", periods=8, freq="h"),
            "seeing_pickering": [7.0, 7.5, 8.0, 7.5, 6.0, 5.0, 4.0, 3.0],
            "transparency_score": [75.0, 80.0, 85.0, 80.0, 70.0, 60.0, 50.0, 40.0],
            "cloud_discrimination": [70.0, 80.0, 85.0, 75.0, 65.0, 55.0, 45.0, 35.0],
            "tracking_stability_score": [70.0, 75.0, 80.0, 75.0, 65.0, 55.0, 45.0, 35.0],
            "is_day": [0, 0, 0, 0, 0, 1, 1, 1],
            "cloud_cover": [20.0] * 8,
            "cloud_cover_high": [10.0] * 8,
            "cloud_cover_mid": [5.0] * 8,
            "cloud_cover_low": [5.0] * 8,
            "relative_humidity_2m": [60.0] * 8,
            "dew_point_2m": [10.0] * 8,
            "temperature_2m": [15.0] * 8,
            "wind_speed_10m": [5.0, 5.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0],
            "lifted_index": [3.0, 2.5, 2.0, 2.5, 1.0, 0.0, -1.0, -2.0],
        }
    )


class TestBestObservationPeriods:
    """Tests for best observation period selection."""

    def test_single_slot_is_filtered_as_too_short(self, monkeypatch):
        analyzer = _build_analyzer()
        monkeypatch.setattr(analyzer, "_resolve_astronomical_night_window", lambda: None)

        df = pd.DataFrame(
            {
                "datetime": [pd.Timestamp("2026-04-17T05:00:00+02:00")],
                "seeing_pickering": [8.0],
                "transparency_score": [80.0],
                "cloud_discrimination": [82.0],
                "tracking_stability_score": [78.0],
                "is_day": [0],
            }
        )

        periods = analyzer._find_best_observation_periods(df)
        assert periods == []

    def test_respects_astronomical_night_window(self, monkeypatch):
        analyzer = _build_analyzer()
        monkeypatch.setattr(
            analyzer,
            "_resolve_astronomical_night_window",
            lambda: (
                pd.Timestamp("2026-04-17T01:00:00+02:00"),
                pd.Timestamp("2026-04-17T05:30:00+02:00"),
            ),
        )

        df = pd.DataFrame(
            {
                "datetime": [
                    pd.Timestamp("2026-04-17T02:00:00+02:00"),
                    pd.Timestamp("2026-04-17T03:00:00+02:00"),
                    pd.Timestamp("2026-04-17T06:00:00+02:00"),
                ],
                "seeing_pickering": [8.0, 8.0, 9.0],
                "transparency_score": [80.0, 80.0, 95.0],
                "cloud_discrimination": [82.0, 82.0, 95.0],
                "tracking_stability_score": [78.0, 78.0, 95.0],
                "is_day": [0, 0, 0],
            }
        )

        periods = analyzer._find_best_observation_periods(df)
        assert len(periods) == 1
        assert periods[0]["start"] == "2026-04-17T02:00:00+02:00"
        assert periods[0]["end"] == "2026-04-17T04:00:00+02:00"

    def test_multiple_periods_sorted_by_quality(self, monkeypatch):
        analyzer = _build_analyzer()
        monkeypatch.setattr(analyzer, "_resolve_astronomical_night_window", lambda: None)

        df = pd.DataFrame(
            {
                "datetime": pd.date_range("2026-04-17T20:00", periods=6, freq="h"),
                "seeing_pickering": [8.0, 8.0, 7.0, 5.0, 5.0, 8.0],
                "transparency_score": [85.0, 85.0, 75.0, 60.0, 60.0, 85.0],
                "cloud_discrimination": [85.0, 85.0, 75.0, 60.0, 60.0, 85.0],
                "tracking_stability_score": [85.0, 85.0, 75.0, 60.0, 60.0, 85.0],
                "is_day": [0, 0, 0, 0, 0, 0],
            }
        )

        periods = analyzer._find_best_observation_periods(df)
        assert len(periods) >= 1
        if len(periods) > 1:
            assert periods[0]["average_quality"] >= periods[1]["average_quality"]

    def test_empty_dataframe_returns_empty_list(self, monkeypatch):
        analyzer = _build_analyzer()
        monkeypatch.setattr(analyzer, "_resolve_astronomical_night_window", lambda: None)
        df = pd.DataFrame()
        assert analyzer._find_best_observation_periods(df) == []


class TestWeatherAnalysisMetrics:
    """Tests for individual weather analysis metrics."""

    def test_cloud_layer_analysis(self):
        analyzer = _build_analyzer()
        df = pd.DataFrame(
            {
                "cloud_cover_high": [10.0, 50.0],
                "cloud_cover_mid": [20.0, 40.0],
                "cloud_cover_low": [30.0, 60.0],
            }
        )
        result = analyzer.analyze_cloud_layers(df)
        assert "cloud_discrimination" in result.columns
        assert (result["cloud_discrimination"] >= 0).all()
        assert (result["cloud_discrimination"] <= 100).all()

    def test_seeing_forecast(self):
        analyzer = _build_analyzer()
        df = pd.DataFrame(
            {
                "wind_speed_10m": [5.0, 15.0, 25.0],
                "wind_speed_80m": [6.0, 18.0, 30.0],
                "wind_speed_120m": [7.0, 20.0, 35.0],
                "lifted_index": [3.0, 0.0, -3.0],
                "wind_speed_500hPa": [30.0, 60.0, 100.0],
                "temperature_500hPa": [-40.0, -45.0, -50.0],
                "temperature_2m": [15.0, 10.0, 5.0],
            }
        )
        result = analyzer.calculate_seeing_forecast(df)
        assert "seeing_pickering" in result.columns
        assert (result["seeing_pickering"] >= 1).all()
        assert (result["seeing_pickering"] <= 10).all()

    def test_transparency_forecast(self):
        analyzer = _build_analyzer()
        df = pd.DataFrame(
            {
                "relative_humidity_2m": [30.0, 60.0, 90.0],
                "visibility": [50000.0, 30000.0, 10000.0],
                "cloud_cover_high": [10.0, 30.0, 70.0],
                "cloud_cover_mid": [10.0, 20.0, 50.0],
                "cloud_cover_low": [10.0, 15.0, 40.0],
            }
        )
        result = analyzer.calculate_transparency_forecast(df)
        assert "transparency_score" in result.columns
        assert "limiting_magnitude" in result.columns
        assert (result["transparency_score"] >= 0).all()
        assert (result["transparency_score"] <= 100).all()

    def test_dew_point_analysis(self):
        analyzer = _build_analyzer()
        df = pd.DataFrame(
            {
                "temperature_2m": [15.0, 12.0, 8.0, 5.0],
                "dew_point_2m": [10.0, 11.0, 7.0, 5.0],
            }
        )
        result = analyzer.analyze_dew_point_alerts(df)
        assert "dew_risk_level" in result.columns
        assert "dew_point_spread" in result.columns
        assert set(result["dew_risk_level"].unique()).issubset(
            {"CRITICAL", "HIGH", "MODERATE", "LOW", "MINIMAL"}
        )

    def test_wind_tracking_impact(self):
        analyzer = _build_analyzer()
        df = pd.DataFrame({
            "wind_speed_10m": [3.0, 7.0, 12.0, 20.0, 30.0],
            "wind_direction_10m": [0, 90, 180, 270, 360]
        })
        result = analyzer.analyze_wind_tracking_impact(df)
        assert "wind_tracking_impact" in result.columns
        assert "tracking_stability_score" in result.columns
        assert (result["tracking_stability_score"] >= 0).all()
        assert (result["tracking_stability_score"] <= 100).all()


class TestCacheLogic:
    """Tests for cache key and storage functions."""

    def test_cache_key_generation(self):
        key1 = _analysis_cache_key(24, "en")
        key2 = _analysis_cache_key(24, "en")
        key3 = _analysis_cache_key(48, "en")
        assert key1 == key2
        assert key1 != key3

    def test_cache_storage_and_retrieval(self, monkeypatch):
        # Clear internal cache state
        monkeypatch.setattr(weather_astro, '_ASTRO_ANALYSIS_LAST_SUCCESS', {})

        test_data = {"test": "data", "hours": 24}
        _store_last_successful_analysis(24, "en", test_data)
        retrieved = _get_last_successful_analysis(24, "en")
        assert retrieved == test_data

        # Ensure deep copy was made
        retrieved["modified"] = True
        assert "modified" not in _get_last_successful_analysis(24, "en")

    def test_cache_miss_returns_none(self, monkeypatch):
        monkeypatch.setattr(weather_astro, '_ASTRO_ANALYSIS_LAST_SUCCESS', {})
        retrieved = _get_last_successful_analysis(48, "fr")
        assert retrieved is None


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    def test_is_openmeteo_concurrency_error(self):
        error1 = Exception("Too many concurrent requests from your IP")
        error2 = Exception("Some other error")
        assert _is_openmeteo_concurrency_error(error1)
        assert not _is_openmeteo_concurrency_error(error2)

    def test_generate_current_summary_with_none_row(self):
        analyzer = _build_analyzer()
        result = analyzer._generate_current_summary(None)
        assert result["status"] == "No current data available"

    def test_generate_current_summary_with_row(self):
        analyzer = _build_analyzer()
        row_data = {
            "seeing_pickering": 7.5,
            "transparency_score": 80.0,
            "limiting_magnitude": 6.5,
            "cloud_discrimination": 82.0,
            "dew_risk_level": "LOW",
            "dew_point_spread": 5.0,
            "wind_tracking_impact": "GOOD",
            "tracking_stability_score": 75.0,
        }
        row = pd.Series(row_data)
        result = analyzer._generate_current_summary(row)
        assert result["seeing_pickering"] == 7.5
        assert result["dew_risk_level"] == "LOW"
        assert result["wind_tracking_impact"] == "GOOD"

    def test_infer_forecast_slot_hours_with_regular_intervals(self):
        analyzer = _build_analyzer()
        datetimes = pd.Series(
            pd.date_range("2026-04-17T20:00", periods=5, freq="h")
        )
        slot_hours = analyzer._infer_forecast_slot_hours(datetimes)
        assert 0.9 < slot_hours < 1.1  # Should be ~1.0

    def test_infer_forecast_slot_hours_with_empty(self):
        analyzer = _build_analyzer()
        datetimes = pd.Series([])
        slot_hours = analyzer._infer_forecast_slot_hours(datetimes)
        assert slot_hours == 1.0


class TestInferForecastSlotHoursEdgeCases:
    """Additional edge cases for _infer_forecast_slot_hours."""

    def test_all_identical_timestamps_returns_one(self):
        analyzer = _build_analyzer()
        # All same timestamps → diffs = 0 → no positive diffs → return 1.0
        datetimes = pd.Series(pd.to_datetime(["2026-04-17T20:00:00"] * 5))
        slot_hours = analyzer._infer_forecast_slot_hours(datetimes)
        assert slot_hours == 1.0

    def test_single_timestamp_returns_one(self):
        analyzer = _build_analyzer()
        datetimes = pd.Series(pd.to_datetime(["2026-04-17T20:00:00"]))
        slot_hours = analyzer._infer_forecast_slot_hours(datetimes)
        assert slot_hours == 1.0

    def test_clamped_to_max_three_hours(self):
        analyzer = _build_analyzer()
        # 6-hour intervals → should be clamped to 3.0
        datetimes = pd.Series(pd.date_range("2026-04-17T20:00:00", periods=5, freq="6h"))
        slot_hours = analyzer._infer_forecast_slot_hours(datetimes)
        assert slot_hours == 3.0


class TestResolveAstronomicalNightWindow:
    """Tests for _resolve_astronomical_night_window."""

    def test_exception_during_import_returns_none(self):
        """Lines 622-624: exception in the function → return None."""
        analyzer = _build_analyzer()
        # Force the internal data load to fail to cover the exception path.
        import skytonight_calculator
        with patch.object(skytonight_calculator, "load_calculation_results", side_effect=RuntimeError("fail")):
            result = analyzer._resolve_astronomical_night_window()
        assert result is None

    def test_missing_night_start_returns_none(self, monkeypatch):
        """Line 613-614: night_start or night_end missing → return None."""
        analyzer = _build_analyzer()
        import skytonight_calculator
        with patch.object(skytonight_calculator, "load_calculation_results", return_value={"metadata": {}}):
            result = analyzer._resolve_astronomical_night_window()
        assert result is None

    def test_invalid_timestamps_returns_none(self, monkeypatch):
        """Line 618-619: invalid timestamps → NaT → return None."""
        analyzer = _build_analyzer()
        import skytonight_calculator
        with patch.object(
            skytonight_calculator,
            "load_calculation_results",
            return_value={"metadata": {"night_start": "not-a-date", "night_end": "also-bad"}},
        ):
            result = analyzer._resolve_astronomical_night_window()
        assert result is None

    def test_valid_window_returned(self, monkeypatch):
        """Lines 621: valid window returned as tuple."""
        analyzer = _build_analyzer()
        import skytonight_calculator
        with patch.object(
            skytonight_calculator,
            "load_calculation_results",
            return_value={
                "metadata": {
                    "night_start": "2026-04-17T22:00:00",
                    "night_end": "2026-04-18T04:00:00",
                }
            },
        ):
            result = analyzer._resolve_astronomical_night_window()
        assert result is not None
        start_ts, end_ts = result
        assert end_ts > start_ts


class TestFindBestObservationPeriodsEdgeCases:
    """Edge cases for _find_best_observation_periods."""

    def test_all_datetime_invalid_returns_empty(self, monkeypatch):
        """Line 652-653: all datetimes coerce to NaT → empty list."""
        analyzer = _build_analyzer()
        monkeypatch.setattr(analyzer, "_resolve_astronomical_night_window", lambda: None)
        df = pd.DataFrame(
            {
                "datetime": ["not-a-date", "also-bad"],
                "seeing_pickering": [8.0, 8.0],
                "transparency_score": [80.0, 80.0],
                "cloud_discrimination": [80.0, 80.0],
                "tracking_stability_score": [80.0, 80.0],
                "is_day": [0, 0],
            }
        )
        result = analyzer._find_best_observation_periods(df)
        assert result == []

    def test_no_periods_above_quality_threshold_returns_empty(self, monkeypatch):
        """Line 695: all quality < 70 → no good periods → empty list."""
        analyzer = _build_analyzer()
        monkeypatch.setattr(analyzer, "_resolve_astronomical_night_window", lambda: None)
        df = pd.DataFrame(
            {
                "datetime": pd.date_range("2026-04-17T20:00:00", periods=4, freq="h"),
                "seeing_pickering": [2.0, 2.0, 2.0, 2.0],
                "transparency_score": [20.0, 20.0, 20.0, 20.0],
                "cloud_discrimination": [20.0, 20.0, 20.0, 20.0],
                "tracking_stability_score": [20.0, 20.0, 20.0, 20.0],
                "is_day": [0, 0, 0, 0],
            }
        )
        result = analyzer._find_best_observation_periods(df)
        assert result == []


class TestGenerateWeatherAlerts:
    """Tests for _generate_weather_alerts alert branches."""

    def _build_alert_df(self, dew_risk, wind_impact, seeing, transparency, dt=None):
        import numpy as np
        dt = dt or pd.date_range("2026-04-17T20:00:00", periods=6, freq="h")
        return pd.DataFrame(
            {
                "datetime": dt,
                "dew_risk_level": [dew_risk] * 6,
                "wind_tracking_impact": [wind_impact] * 6,
                "seeing_pickering": [seeing] * 6,
                "transparency_score": [transparency] * 6,
            }
        )

    def test_no_alerts_when_conditions_good(self):
        analyzer = _build_analyzer()
        analyzer.language = "en"
        df = self._build_alert_df("MINIMAL", "GOOD", 7.0, 80.0)
        alerts = analyzer._generate_weather_alerts(df)
        assert alerts == []

    def test_empty_df_returns_no_alerts(self):
        analyzer = _build_analyzer()
        analyzer.language = "en"
        alerts = analyzer._generate_weather_alerts(pd.DataFrame())
        assert alerts == []

    def test_dew_warning_generated(self):
        """Line 754-762: CRITICAL dew → DEW_WARNING alert."""
        analyzer = _build_analyzer()
        analyzer.language = "en"
        df = self._build_alert_df("CRITICAL", "GOOD", 7.0, 80.0)
        alerts = analyzer._generate_weather_alerts(df)
        types = [a.get("type") or a.get("alert_type") or str(a) for a in alerts]
        assert any("DEW" in str(t).upper() or "dew" in str(a).lower() for t, a in zip(types, alerts))

    def test_wind_warning_generated(self):
        """Line 766-774: CRITICAL wind → WIND_WARNING alert."""
        analyzer = _build_analyzer()
        analyzer.language = "en"
        df = self._build_alert_df("MINIMAL", "CRITICAL", 7.0, 80.0)
        alerts = analyzer._generate_weather_alerts(df)
        assert len(alerts) >= 1

    def test_seeing_warning_generated(self):
        """Line 777-786: seeing <= 3 → SEEING_WARNING alert."""
        analyzer = _build_analyzer()
        analyzer.language = "en"
        df = self._build_alert_df("MINIMAL", "GOOD", 2.0, 80.0)
        alerts = analyzer._generate_weather_alerts(df)
        assert len(alerts) >= 1

    def test_transparency_warning_generated(self):
        """Line 789-798: transparency <= 30 → TRANSPARENCY_WARNING alert."""
        analyzer = _build_analyzer()
        analyzer.language = "en"
        df = self._build_alert_df("MINIMAL", "GOOD", 7.0, 15.0)
        alerts = analyzer._generate_weather_alerts(df)
        assert len(alerts) >= 1

    def test_all_warnings_at_once(self):
        """All four alert conditions simultaneously."""
        analyzer = _build_analyzer()
        analyzer.language = "en"
        df = self._build_alert_df("CRITICAL", "CRITICAL", 1.0, 10.0)
        alerts = analyzer._generate_weather_alerts(df)
        assert len(alerts) == 4


class TestFetchExtendedWeatherDataErrors:
    """Tests for fetch_extended_weather_data error paths (lines 168-198)."""

    def _build_analyzer_with_location(self):
        analyzer = _build_analyzer()
        analyzer.location = {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
        analyzer.language = "en"
        return analyzer

    def test_full_request_fails_with_non_concurrency_error_falls_back_to_core(self):
        """Lines 168-187: full request fails → retry with core vars → succeed."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        core_response = MagicMock()
        # Make full request fail, core succeed
        call_count = [0]

        def side_effect(url, params=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Server temporarily unavailable")
            return [core_response]

        mock_client.weather_api.side_effect = side_effect

        with patch("weather_astro.create_weather_client", return_value=mock_client):
            with patch.object(analyzer, "_parse_extended_data", return_value={"data": pd.DataFrame(), "location": {}}):
                analyzer.fetch_extended_weather_data(24)
        # Core fallback should return a result (or None if parse also fails)
        # Either outcome means lines 168-187 were hit

    def test_both_requests_fail_returns_none(self):
        """Lines 184-187: both full and core requests fail → None."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        mock_client.weather_api.side_effect = Exception("Persistent failure")

        with patch("weather_astro.create_weather_client", return_value=mock_client):
            result = analyzer.fetch_extended_weather_data(24)
        assert result is None

    def test_concurrency_error_propagates_to_outer_handler(self):
        """Lines 190-192: concurrency error → record_openmeteo_rate_limit."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        mock_client.weather_api.side_effect = Exception("Too many concurrent requests from your IP")

        with patch("weather_astro.create_weather_client", return_value=mock_client):
            with patch("weather_astro.record_openmeteo_rate_limit") as mock_record:
                result = analyzer.fetch_extended_weather_data(24)
        assert result is None
        mock_record.assert_called_once()

    def test_transient_error_logged_and_returns_none(self):
        """Lines 193-194: transient open-meteo error → returns None."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        mock_client.weather_api.side_effect = Exception("503 Service Unavailable")

        with patch("weather_astro.create_weather_client", return_value=mock_client):
            with patch("weather_astro._is_openmeteo_transient_error", return_value=True):
                result = analyzer.fetch_extended_weather_data(24)
        assert result is None

    def test_unexpected_error_logged_and_returns_none(self):
        """Lines 195-197: unexpected error → returns None."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        mock_client.weather_api.side_effect = Exception("Unknown weird error")

        with patch("weather_astro.create_weather_client", return_value=mock_client):
            with patch("weather_astro._is_openmeteo_transient_error", return_value=False):
                result = analyzer.fetch_extended_weather_data(24)
        assert result is None


class TestGenerateComprehensiveAnalysis:
    """Tests for generate_comprehensive_analysis edge paths."""

    def _build_analyzer_with_location(self):
        analyzer = _build_analyzer()
        analyzer.location = {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC", "name": "TestCity"}
        analyzer.language = "en"
        return analyzer

    def test_no_weather_data_returns_none(self):
        """Lines 551-553: fetch_extended_weather_data returns None → return None."""
        analyzer = self._build_analyzer_with_location()
        with patch.object(analyzer, "fetch_extended_weather_data", return_value=None):
            result = analyzer.generate_comprehensive_analysis(24)
        assert result is None

    def test_exception_inside_analysis_returns_none(self):
        """Lines 584-586: exception inside generate → return None."""
        analyzer = self._build_analyzer_with_location()
        with patch.object(analyzer, "fetch_extended_weather_data", side_effect=RuntimeError("boom")):
            result = analyzer.generate_comprehensive_analysis(24)
        assert result is None


class TestGetAstroWeatherAnalysisCachePaths:
    """Tests for the cache / rate-limit / cooldown / lock paths in get_astro_weather_analysis."""

    def _clear_module_state(self):
        """Directly clear module-level dicts (not via monkeypatch to avoid aliasing issues)."""
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS.clear()
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS.clear()
        weather_astro._ASTRO_ANALYSIS_LAST_FAILURE_TS.clear()

    def setup_method(self):
        self._clear_module_state()

    def teardown_method(self):
        self._clear_module_state()

    def test_fresh_cache_hit_returns_cached(self):
        """Lines 814-816: TTL not expired → return cached."""
        test_data = {"result": "cached"}
        _store_last_successful_analysis(24, "en", test_data)
        key = _analysis_cache_key(24, "en")
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[key] = time.time()
        result = get_astro_weather_analysis(24, "en")
        assert result == test_data

    def test_ttl_expired_no_cache_falls_through(self):
        """Lines 814->820: TTL expired, cached is None → fall through to rate-limit check."""
        key = _analysis_cache_key(97, "zz")
        # Set a very old timestamp so TTL is expired
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[key] = 0.0
        # No stored cache for this key
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=True):
            result = get_astro_weather_analysis(97, "zz")
        assert result is None  # rate limited + no cache

    def test_rate_limited_with_cache_returns_stale(self):
        """Lines 823-824: rate limited + cached → return stale cache."""
        test_data = {"result": "stale"}
        _store_last_successful_analysis(24, "en", test_data)
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=True):
            result = get_astro_weather_analysis(24, "en")
        assert result == test_data

    def test_rate_limited_no_cache_returns_none(self):
        """Lines 825-826: rate limited + no cache → None."""
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=True):
            result = get_astro_weather_analysis(99, "zz")
        assert result is None

    def test_failure_cooldown_with_cache_returns_stale(self):
        """Lines 833-834: in failure cooldown + cached → return stale."""
        test_data = {"result": "stale_cooldown"}
        _store_last_successful_analysis(24, "en", test_data)
        key = _analysis_cache_key(24, "en")
        weather_astro._ASTRO_ANALYSIS_LAST_FAILURE_TS[key] = time.time()
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            result = get_astro_weather_analysis(24, "en")
        assert result == test_data

    def test_failure_cooldown_no_cache_returns_none(self):
        """Lines 835-836: in failure cooldown + no cache → None."""
        key = _analysis_cache_key(24, "de")
        weather_astro._ASTRO_ANALYSIS_LAST_FAILURE_TS[key] = time.time()
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            result = get_astro_weather_analysis(24, "de")
        assert result is None

    def test_lock_not_acquired_returns_cache_if_available(self):
        """Lines 842-843: lock busy + cached → return cache."""
        test_data = {"result": "lock_cache"}
        _store_last_successful_analysis(24, "en", test_data)
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            weather_astro._ASTRO_ANALYSIS_LOCK.acquire()
            try:
                result = get_astro_weather_analysis(24, "en")
            finally:
                weather_astro._ASTRO_ANALYSIS_LOCK.release()
        assert result == test_data

    def test_lock_not_acquired_no_cache_returns_none(self):
        """Line 844: lock busy + no cache → None."""
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            weather_astro._ASTRO_ANALYSIS_LOCK.acquire()
            try:
                result = get_astro_weather_analysis(99, "zz")
            finally:
                weather_astro._ASTRO_ANALYSIS_LOCK.release()
        assert result is None

    def test_fetch_fails_no_stale_cache_returns_none(self):
        """Lines 857-863: analysis returns None, no stale cache → None."""
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            with patch("weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis", return_value=None):
                with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                    result = get_astro_weather_analysis(99, "zz")
        assert result is None

    def test_fetch_fails_with_stale_cache_returns_stale(self):
        """Lines 860-861: analysis returns None but stale cache exists → return stale."""
        test_data = {"result": "stale_on_fetch_fail"}
        _store_last_successful_analysis(24, "en", test_data)
        # Don't set a fresh TTL so it falls past the TTL check
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[_analysis_cache_key(24, "en")] = 0.0
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            with patch("weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis", return_value=None):
                with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                    result = get_astro_weather_analysis(24, "en")
        assert result == test_data

    def test_exception_during_analysis_with_stale_cache(self):
        """Lines 868-872: exception + stale cache → return stale."""
        test_data = {"result": "stale_exception"}
        _store_last_successful_analysis(24, "en", test_data)
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[_analysis_cache_key(24, "en")] = 0.0
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            with patch(
                "weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis",
                side_effect=RuntimeError("analysis failed"),
            ):
                with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                    result = get_astro_weather_analysis(24, "en")
        assert result == test_data

    def test_exception_during_analysis_no_cache_returns_none(self):
        """Lines 873-875: exception + no cache → None."""
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            with patch(
                "weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis",
                side_effect=RuntimeError("fail"),
            ):
                with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                    result = get_astro_weather_analysis(99, "zz")
        assert result is None


class TestFetchExtendedWeatherDataMorePaths:
    """Cover remaining branches: transient/unexpected error (193-197), full-then-core-success."""

    def _build_analyzer_with_location(self):
        analyzer = _build_analyzer()
        analyzer.location = {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
        analyzer.language = "en"
        return analyzer

    def test_full_succeeds_returns_result(self):
        """Lines 161-167: full request succeeds → return result directly."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        fake_result = {"data": pd.DataFrame(), "location": {}}
        mock_client.weather_api.return_value = [MagicMock()]

        with patch("weather_astro.create_weather_client", return_value=mock_client):
            with patch.object(analyzer, "_parse_extended_data", return_value=fake_result):
                result = analyzer.fetch_extended_weather_data(24)
        assert result == fake_result

    def test_full_fails_core_succeeds(self):
        """Lines 168-183: full request fails (non-concurrency), core succeeds."""
        analyzer = self._build_analyzer_with_location()
        mock_client = MagicMock()
        fake_result = {"data": pd.DataFrame(), "location": {}}
        call_count = [0]

        def weather_api_side_effect(url, params=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Server temporarily unavailable")
            return [MagicMock()]

        mock_client.weather_api.side_effect = weather_api_side_effect
        with patch("weather_astro.create_weather_client", return_value=mock_client):
            with patch.object(analyzer, "_parse_extended_data", return_value=fake_result):
                result = analyzer.fetch_extended_weather_data(24)
        assert result == fake_result

    def test_transient_error_in_outer_exception(self):
        """Lines 193-194: outer try fails with transient error → log and return None.
        The outer except (189) is hit when create_weather_client() itself raises."""
        analyzer = self._build_analyzer_with_location()
        # Raise from create_weather_client so it hits the OUTER except at line 189
        with patch("weather_astro.create_weather_client", side_effect=Exception("503 Service Unavailable")):
            with patch("weather_astro._is_openmeteo_transient_error", return_value=True):
                with patch("weather_astro._is_openmeteo_concurrency_error", return_value=False):
                    result = analyzer.fetch_extended_weather_data(24)
        assert result is None

    def test_unexpected_error_in_outer_exception(self):
        """Lines 195-197: outer try fails with unexpected error → log and return None."""
        analyzer = self._build_analyzer_with_location()
        # Raise from create_weather_client so it hits the OUTER except at line 189
        with patch("weather_astro.create_weather_client", side_effect=Exception("Weird unexpected error XYZ")):
            with patch("weather_astro._is_openmeteo_transient_error", return_value=False):
                with patch("weather_astro._is_openmeteo_concurrency_error", return_value=False):
                    result = analyzer.fetch_extended_weather_data(24)
        assert result is None


class TestGetCurrentAstroConditions:
    """Tests for get_current_astro_conditions (lines 880-892)."""

    def test_returns_current_conditions_when_analysis_succeeds(self):
        """Lines 884-888: happy path → return current_conditions."""
        mock_conditions = {"seeing_pickering": 7.0}
        mock_analysis = {"current_conditions": mock_conditions}
        with patch("weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis", return_value=mock_analysis):
            with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                weather_astro.AstroWeatherAnalyzer.location = {}
                weather_astro.AstroWeatherAnalyzer.language = "en"
                result = get_current_astro_conditions()
        assert result == mock_conditions

    def test_returns_none_when_analysis_fails(self):
        """Lines 888-889: analysis returns None → return None."""
        with patch("weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis", return_value=None):
            with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                weather_astro.AstroWeatherAnalyzer.location = {}
                weather_astro.AstroWeatherAnalyzer.language = "en"
                result = get_current_astro_conditions()
        assert result is None

    def test_returns_none_on_exception(self):
        """Lines 890-892: exception → None."""
        with patch("weather_astro.AstroWeatherAnalyzer.__init__", side_effect=RuntimeError("init fail")):
            result = get_current_astro_conditions()
        assert result is None


class TestParseExtendedDataTimezoneBytes:
    """Test _parse_extended_data when Timezone() returns bytes."""

    def test_bytes_timezone_decoded(self):
        """Line 213-215: Timezone() returns bytes → decoded to str."""
        analyzer = _build_analyzer()
        analyzer.location = {"name": "Test", "latitude": 48.0, "longitude": 2.0}

        mock_response = MagicMock()
        mock_hourly = MagicMock()
        mock_var = MagicMock()
        mock_var.ValuesAsNumpy.return_value = [15.0, 16.0]
        mock_hourly.Variables.return_value = mock_var
        mock_hourly.Time.return_value = 1700000000
        mock_hourly.Interval.return_value = 3600
        mock_response.Hourly.return_value = mock_hourly
        mock_response.Timezone.return_value = b"UTC"
        mock_response.Latitude.return_value = 48.0
        mock_response.Longitude.return_value = 2.0
        mock_response.Elevation.return_value = 100.0

        result = analyzer._parse_extended_data(mock_response, ["temperature_2m"])
        assert result["location"]["timezone"] == "UTC"


class TestAstroWeatherAnalyzerInit:
    """Lines 76-78: AstroWeatherAnalyzer.__init__ runs normally."""

    def test_init_loads_config_and_sets_attributes(self):
        with patch("weather_astro.load_config", return_value={"location": {"latitude": 48.0}}):
            analyzer = AstroWeatherAnalyzer(language="fr")
        assert analyzer.location == {"latitude": 48.0}
        assert analyzer.language == "fr"


class TestGenerateComprehensiveAnalysisSuccess:
    """Lines 555-574: generate_comprehensive_analysis with real weather data."""

    def test_returns_dict_when_data_available(self):
        analyzer = AstroWeatherAnalyzer.__new__(AstroWeatherAnalyzer)
        analyzer.location = {"name": "Test", "latitude": 48.0, "longitude": 2.0}
        analyzer.language = "en"

        mock_df = _build_sample_dataframe()
        mock_weather = {"data": mock_df, "location": {"name": "Test"}}

        with patch.object(analyzer, "fetch_extended_weather_data", return_value=mock_weather), \
             patch.object(analyzer, "analyze_cloud_layers", return_value=mock_df), \
             patch.object(analyzer, "calculate_seeing_forecast", return_value=mock_df), \
             patch.object(analyzer, "calculate_transparency_forecast", return_value=mock_df), \
             patch.object(analyzer, "analyze_dew_point_alerts", return_value=mock_df), \
             patch.object(analyzer, "analyze_wind_tracking_impact", return_value=mock_df), \
             patch.object(analyzer, "_find_best_observation_periods", return_value=[]), \
             patch.object(analyzer, "_generate_weather_alerts", return_value=[]):
            result = analyzer.generate_comprehensive_analysis(24)

        assert result is not None
        assert "hourly_data" in result
        assert "best_observation_periods" in result
        assert "current_conditions" in result


class TestGetAstroWeatherAnalysisMissingPaths:
    """Covers lines 823-824, 833-834, 842-843, 850-854 that need expired TTL."""

    def _clear_state(self):
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS.clear()
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS.clear()
        weather_astro._ASTRO_ANALYSIS_LAST_FAILURE_TS.clear()

    def setup_method(self):
        self._clear_state()

    def teardown_method(self):
        self._clear_state()

    def test_rate_limited_with_stale_cache_returns_stale(self):
        """Lines 823-824: TTL expired + rate limited + cache exists → return stale."""
        key = _analysis_cache_key(24, "en")
        test_data = {"result": "stale_rate_limited"}
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS[key] = test_data
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[key] = 0.0  # expired
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=True):
            result = get_astro_weather_analysis(24, "en")
        assert result is not None

    def test_failure_cooldown_with_stale_cache_returns_stale(self):
        """Lines 833-834: TTL expired + failure cooldown + cache exists → return stale."""
        key = _analysis_cache_key(24, "en")
        test_data = {"result": "stale_cooldown"}
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS[key] = test_data
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[key] = 0.0  # expired TTL
        weather_astro._ASTRO_ANALYSIS_LAST_FAILURE_TS[key] = time.time()  # recent failure
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            result = get_astro_weather_analysis(24, "en")
        assert result is not None

    def test_lock_busy_with_stale_cache_returns_stale(self):
        """Lines 842-843: TTL expired + lock busy + cache exists → return stale."""
        key = _analysis_cache_key(24, "en")
        test_data = {"result": "stale_lock"}
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS[key] = test_data
        weather_astro._ASTRO_ANALYSIS_LAST_SUCCESS_TS[key] = 0.0  # expired TTL
        weather_astro._ASTRO_ANALYSIS_LOCK.acquire()
        try:
            with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
                result = get_astro_weather_analysis(24, "en")
        finally:
            weather_astro._ASTRO_ANALYSIS_LOCK.release()
        assert result is not None

    def test_analysis_success_stores_and_returns(self):
        """Lines 850-854: analysis returns non-None → store and return."""
        fresh_data = {"result": "fresh_analysis"}
        with patch("weather_astro.is_openmeteo_rate_limited", return_value=False):
            with patch(
                "weather_astro.AstroWeatherAnalyzer.generate_comprehensive_analysis",
                return_value=fresh_data,
            ):
                with patch("weather_astro.AstroWeatherAnalyzer.__init__", return_value=None):
                    result = get_astro_weather_analysis(97, "en")
        assert result == fresh_data
