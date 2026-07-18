"""
Tests for aurora_predictions.py
Covers AuroraService pure-logic methods and mocked HTTP calls.
"""

import pytest
from unittest.mock import patch, MagicMock
from astroweather import aurora_predictions
from astroweather.aurora_predictions import AuroraService


@pytest.fixture(autouse=True)
def _reset_kp_cache():
    """fetch_current_kp_index()/fetch_kp_forecast() now share a module-level
    cache across locations (see aurora_predictions.py) - reset it before every
    test so each test's own requests.get mock is actually exercised instead of
    a previous test's cached value being returned."""
    aurora_predictions._kp_index_cache['value'] = None
    aurora_predictions._kp_index_cache['timestamp'] = 0.0
    aurora_predictions._kp_forecast_cache['value'] = None
    aurora_predictions._kp_forecast_cache['timestamp'] = 0.0
    yield


class TestCalculateAuroraProbability:
    """Tests for the calculate_aurora_probability pure-math method."""

    def setup_method(self):
        self.service = AuroraService(latitude=65.0, longitude=25.0, timezone_str="UTC")

    def test_deep_inside_oval_high_kp(self):
        """Latitude well poleward of oval edge → deep inside branch."""
        # abs_lat=65, aurora_edge = 67 - 9*3.5 = 35.5, distance_from_edge = 29.5 >= 10
        svc = AuroraService(65.0, 25.0, "UTC")
        prob = svc.calculate_aurora_probability(9.0)
        assert prob == pytest.approx(25 + 9 * 7, abs=1)

    def test_inside_near_edge(self):
        """Latitude just inside oval edge → middle branch."""
        # aurora_edge = 67 - 5*3.5 = 49.5; abs_lat=53; distance = 3.5, in [0,10)
        svc = AuroraService(53.0, 0.0, "UTC")
        prob = svc.calculate_aurora_probability(5.0)
        assert prob == pytest.approx(15 + 5 * 6, abs=1)

    def test_just_outside_edge(self):
        """Latitude just outside oval edge (distance in [-5, 0)) → third branch."""
        # aurora_edge = 67 - 4*3.5 = 53; abs_lat=51; distance = -2 → in [-5,0)
        svc = AuroraService(51.0, 0.0, "UTC")
        prob = svc.calculate_aurora_probability(4.0)
        assert prob == pytest.approx(5 + 4 * 4, abs=1)

    def test_far_outside_edge_returns_zero_for_low_kp(self):
        """Far equatorward at low Kp → probability is 0."""
        svc = AuroraService(20.0, 0.0, "UTC")
        prob = svc.calculate_aurora_probability(1.0)
        assert prob == 0.0

    def test_far_outside_edge_positive_for_high_kp(self):
        """Far equatorward but high Kp → positive probability."""
        svc = AuroraService(20.0, 0.0, "UTC")
        prob = svc.calculate_aurora_probability(8.0)
        assert prob > 0

    def test_probability_clamped_to_100(self):
        """Probability must never exceed 100."""
        svc = AuroraService(80.0, 0.0, "UTC")
        prob = svc.calculate_aurora_probability(9.0)
        assert prob <= 100.0

    def test_probability_clamped_to_zero(self):
        """Probability must never be negative."""
        svc = AuroraService(0.0, 0.0, "UTC")
        prob = svc.calculate_aurora_probability(0.0)
        assert prob >= 0.0

    def test_southern_hemisphere_uses_abs_latitude(self):
        """Southern hemisphere observer mirrors northern hemisphere."""
        north = AuroraService(65.0, 0.0, "UTC")
        south = AuroraService(-65.0, 0.0, "UTC")
        assert north.calculate_aurora_probability(5.0) == south.calculate_aurora_probability(5.0)


class TestGetProbabilityLevel:
    """Tests for the get_probability_level branch logic."""

    def setup_method(self):
        self.svc = AuroraService(45.0, 0.0, "UTC")

    def test_very_low(self):
        assert self.svc.get_probability_level(5) == "Very Low"

    def test_low(self):
        assert self.svc.get_probability_level(15) == "Low"

    def test_moderate(self):
        assert self.svc.get_probability_level(30) == "Moderate"

    def test_high(self):
        assert self.svc.get_probability_level(60) == "High"

    def test_very_high(self):
        assert self.svc.get_probability_level(90) == "Very High"

    def test_boundary_exactly_10(self):
        assert self.svc.get_probability_level(10) == "Low"

    def test_boundary_exactly_25(self):
        assert self.svc.get_probability_level(25) == "Moderate"

    def test_boundary_exactly_75(self):
        assert self.svc.get_probability_level(75) == "Very High"


class TestGetAuroraScore:
    """Tests for get_aurora_score return structure."""

    def setup_method(self):
        self.svc = AuroraService(55.0, 10.0, "Europe/Paris")

    def test_returns_dict_with_required_keys(self):
        result = self.svc.get_aurora_score(5.0)
        assert isinstance(result, dict)
        for key in ("kp_index", "probability", "probability_level", "visibility_level",
                    "visibility_description", "observer_latitude", "timestamp"):
            assert key in result

    def test_kp_below_3_gives_none_visibility(self):
        result = self.svc.get_aurora_score(2.0)
        assert result["visibility_level"] == "None"

    def test_kp_7_gives_excellent_visibility(self):
        result = self.svc.get_aurora_score(7.0)
        assert result["visibility_level"] == "Excellent"

    def test_kp_8_gives_severe_storm(self):
        result = self.svc.get_aurora_score(8.0)
        assert result["visibility_level"] == "Severe Storm"

    def test_kp_max_is_9(self):
        result = self.svc.get_aurora_score(6.0)
        assert result["kp_index_max"] == 9

    def test_best_viewing_window_present(self):
        result = self.svc.get_aurora_score(5.0)
        assert "best_viewing_window" in result
        assert "start_hour" in result["best_viewing_window"]

    def test_color_description_green_always_present(self):
        result = self.svc.get_aurora_score(1.0)
        assert "green" in result["color_description"]

    def test_color_description_blue_only_for_severe(self):
        low_result = self.svc.get_aurora_score(3.0)
        high_result = self.svc.get_aurora_score(9.0)
        assert "blue_purple" not in low_result["color_description"]
        assert "blue_purple" in high_result["color_description"]

    def test_forecast_timestamp_is_parsed(self):
        result = self.svc.get_aurora_score(4.0, forecast_timestamp="2026-01-15T20:00:00")
        assert result["timestamp"] is not None


class TestFetchCurrentKpIndex:
    """Tests for fetch_current_kp_index with mocked HTTP."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.requests.get")
    def test_parses_new_dict_format(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"Kp": "3.33"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result == pytest.approx(3.33)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_parses_legacy_list_format(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [["2026-01-01 00:00:00", "5.00"]]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result == pytest.approx(5.0)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_returns_none_on_request_exception(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("timeout")
        result = self.svc.fetch_current_kp_index()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_returns_none_on_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result is None


class TestFetchKpForecast:
    """Tests for fetch_kp_forecast with mocked HTTP."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.requests.get")
    def test_parses_new_dict_format(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"time_tag": "2026-01-01T00:00:00", "kp": "3.0"},
            {"time_tag": "2026-01-01T03:00:00", "kp": "4.0"},
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["kp"] == 3.0

    @patch("astroweather.aurora_predictions.requests.get")
    def test_returns_none_on_request_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("network error")
        result = self.svc.fetch_kp_forecast()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_parses_legacy_list_format_with_header(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["time_tag", "Kp"],
            ["2026-01-01 00:00:00", "2.67"],
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert result[0]["kp"] == pytest.approx(2.67)


class TestKpDataSharedAcrossLocations:
    """Kp index/forecast have no location dimension - a second AuroraService
    instance (a different observer location) must reuse the first instance's
    fetch instead of hitting NOAA again, within the cache TTL."""

    @patch("astroweather.aurora_predictions.requests.get")
    def test_current_kp_fetched_once_for_two_locations(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"Kp": "4.0"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        paris = AuroraService(48.85, 2.35, "Europe/Paris")
        tokyo = AuroraService(35.68, 139.69, "Asia/Tokyo")

        assert paris.fetch_current_kp_index() == pytest.approx(4.0)
        assert tokyo.fetch_current_kp_index() == pytest.approx(4.0)
        assert mock_get.call_count == 1

    @patch("astroweather.aurora_predictions.requests.get")
    def test_kp_forecast_fetched_once_for_two_locations(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"time_tag": "2026-01-01T00:00:00", "kp": "3.0"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        paris = AuroraService(48.85, 2.35, "Europe/Paris")
        tokyo = AuroraService(35.68, 139.69, "Asia/Tokyo")

        assert paris.fetch_kp_forecast() is not None
        assert tokyo.fetch_kp_forecast() is not None
        assert mock_get.call_count == 1

    @patch("astroweather.aurora_predictions.requests.get")
    def test_current_kp_refetched_after_ttl_expires(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"Kp": "4.0"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        svc = AuroraService(48.85, 2.35, "Europe/Paris")
        assert svc.fetch_current_kp_index() == pytest.approx(4.0)
        assert mock_get.call_count == 1

        aurora_predictions._kp_index_cache['timestamp'] -= aurora_predictions.CACHE_TTL_AURORA + 1
        assert svc.fetch_current_kp_index() == pytest.approx(4.0)
        assert mock_get.call_count == 2


class TestFetchCurrentKpIndexEdgeCases:
    """Additional edge-case tests for fetch_current_kp_index."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.requests.get")
    def test_raw_none_when_latest_neither_dict_nor_list(self, mock_get):
        """Line 64: latest element is neither dict nor list → raw = None → return None."""
        mock_resp = MagicMock()
        # List with a scalar element — not dict, not list
        mock_resp.json.return_value = ["invalid_scalar"]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_value_error_on_unparseable_kp(self, mock_get):
        """Lines 71-72: float() raises ValueError on bad Kp string."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"Kp": "not_a_number"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_general_exception_returns_none(self, mock_get):
        """Lines 77-79: non-requests Exception inside fetch → return None."""
        mock_resp = MagicMock()
        # Make json() raise a generic exception (not RequestException)
        mock_resp.json.side_effect = RuntimeError("unexpected json failure")
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_legacy_list_too_short_returns_none(self, mock_get):
        """Line 64 via list branch: list element with len <= 1 → raw = None."""
        mock_resp = MagicMock()
        # Single-element list inside the outer list (not len > 1)
        mock_resp.json.return_value = [["only_one_element"]]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result is None


class TestFetchKpForecastEdgeCases:
    """Additional edge-case tests for fetch_kp_forecast."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.requests.get")
    def test_none_kp_row_is_skipped(self, mock_get):
        """Lines 100, 103-104: row with kp=None is skipped via continue."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"time_tag": "2026-01-01T00:00:00", "kp": None},
            {"time_tag": "2026-01-01T03:00:00", "kp": "3.0"},
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        # Only the second entry (kp=3.0) should survive
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kp"] == pytest.approx(3.0)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_unparseable_kp_row_is_skipped(self, mock_get):
        """Lines 103-104: float() raises on bad kp → continue."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"time_tag": "2026-01-01T00:00:00", "kp": "bad"},
            {"time_tag": "2026-01-01T03:00:00", "kp": "5.0"},
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kp"] == pytest.approx(5.0)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_legacy_list_format_full_path(self, mock_get):
        """Lines 106-122: legacy list-of-lists with header row."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["time_tag", "Kp"],
            ["2026-01-01 00:00:00", "1.33"],
            ["2026-01-01 03:00:00", "2.00"],
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["timestamp"] == "2026-01-01 00:00:00"
        assert result[1]["kp"] == pytest.approx(2.0)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_legacy_list_short_row_skipped(self, mock_get):
        """Line 113-114: legacy row too short for kp_idx → continue."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["time_tag", "Kp"],
            [],  # too short
            ["2026-01-01 03:00:00", "4.0"],
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kp"] == pytest.approx(4.0)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_legacy_list_bad_kp_value_skipped(self, mock_get):
        """Lines 117-118: float() raises on bad kp in legacy format → continue."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["time_tag", "Kp"],
            ["2026-01-01 00:00:00", "not_a_float"],
            ["2026-01-01 03:00:00", "2.0"],
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["kp"] == pytest.approx(2.0)

    @patch("astroweather.aurora_predictions.requests.get")
    def test_general_exception_returns_none(self, mock_get):
        """Lines 129-131: non-requests Exception inside fetch_kp_forecast → return None."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = RuntimeError("unexpected failure")
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_returns_none_when_all_kp_values_none(self, mock_get):
        """forecast_data stays empty → return None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"time_tag": "2026-01-01T00:00:00", "kp": None},
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert result is None


class TestGetAuroraScoreEdgeCases:
    """Edge cases for get_aurora_score timezone / timestamp handling."""

    def setup_method(self):
        self.svc = AuroraService(55.0, 10.0, "Europe/Paris")

    def test_invalid_forecast_timestamp_falls_back_to_now(self):
        """Lines 232-234/235-236: bad timestamp string → fallback to now."""
        result = self.svc.get_aurora_score(4.0, forecast_timestamp="not-a-date")
        assert result["timestamp"] is not None
        assert isinstance(result["timestamp"], str)

    def test_invalid_timezone_falls_back_to_utc(self):
        """Lines 226-227: ZoneInfo raises → tzinfo = timezone.utc."""
        svc = AuroraService(55.0, 10.0, "Invalid/Timezone")
        result = svc.get_aurora_score(4.0)
        assert result["timestamp"] is not None

    def test_kp_3_to_4_gives_very_low_visibility(self):
        """Line 203-204: kp in [3,4) → 'Very Low'."""
        result = self.svc.get_aurora_score(3.5)
        assert result["visibility_level"] == "Very Low"

    def test_kp_4_to_5_gives_low_visibility(self):
        """Lines 205-206: kp in [4,5) → 'Low'."""
        result = self.svc.get_aurora_score(4.5)
        assert result["visibility_level"] == "Low"

    def test_kp_5_to_6_gives_moderate_visibility(self):
        """Lines 208-209: kp in [5,6) → 'Moderate'."""
        result = self.svc.get_aurora_score(5.5)
        assert result["visibility_level"] == "Moderate"

    def test_kp_6_to_7_gives_good_visibility(self):
        """Lines 211-212: kp in [6,7) → 'Good'."""
        result = self.svc.get_aurora_score(6.5)
        assert result["visibility_level"] == "Good"

    def test_forecast_timestamp_naive_gets_utc_set(self):
        """Lines 231-234: naive ISO timestamp → replace tzinfo=UTC → convert."""
        result = self.svc.get_aurora_score(5.0, forecast_timestamp="2026-06-01T20:00:00")
        assert result["timestamp"] is not None


class TestGetDetailedReport:
    """Tests for get_detailed_report (lines 297-388)."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_current_kp_none_uses_forecast_fallback(self, mock_forecast, mock_current):
        """Lines 303-323: current_kp is None → use forecast entries as fallback."""
        mock_current.return_value = None
        mock_forecast.return_value = [
            {"timestamp": "2026-01-01T00:00:00", "kp": 4.5},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        assert report["current"]["kp_index"] == pytest.approx(4.5)

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_current_kp_none_forecast_also_none_uses_default(self, mock_forecast, mock_current):
        """Lines 320-323: both current and forecast None → default Kp=3.0."""
        mock_current.return_value = None
        mock_forecast.return_value = None
        report = self.svc.get_detailed_report()
        assert report is not None
        assert report["current"]["kp_index"] == pytest.approx(3.0)

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_current_kp_none_forecast_all_none_kp_values(self, mock_forecast, mock_current):
        """Lines 305-320: forecast entries have no valid kp → still falls back to 3.0."""
        mock_current.return_value = None
        # Forecast with entries that have non-numeric or None kp
        mock_forecast.return_value = [
            {"timestamp": "2026-01-01T00:00:00", "kp": None},
            {"timestamp": "2026-01-01T03:00:00"},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        assert report["current"]["kp_index"] == pytest.approx(3.0)

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_report_includes_forecast_entries(self, mock_forecast, mock_current):
        """Lines 353-383: forecast entries after now are appended to report."""
        from datetime import datetime, timezone, timedelta
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        mock_current.return_value = 3.0
        mock_forecast.return_value = [
            {"timestamp": future_ts, "kp": 4.0},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        assert len(report["forecast"]) >= 1

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_report_skips_past_forecast_entries(self, mock_forecast, mock_current):
        """Lines 367-376: past forecast timestamps are skipped."""
        mock_current.return_value = 3.0
        mock_forecast.return_value = [
            {"timestamp": "2000-01-01T00:00:00", "kp": 4.0},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        assert len(report["forecast"]) == 0

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_forecast_with_invalid_timezone_falls_back(self, mock_forecast, mock_current):
        """Lines 356-361: invalid timezone in forecast → tzinfo = UTC."""
        svc = AuroraService(60.0, 25.0, "Invalid/Zone")
        from datetime import datetime, timezone, timedelta
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        mock_current.return_value = 3.0
        mock_forecast.return_value = [{"timestamp": future_ts, "kp": 3.0}]
        report = svc.get_detailed_report()
        assert report is not None

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    def test_outer_exception_returns_none(self, mock_current):
        """Lines 386-388: outer Exception in get_detailed_report → None."""
        mock_current.side_effect = RuntimeError("catastrophic failure")
        report = self.svc.get_detailed_report()
        assert report is None

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_forecast_entry_with_bad_timestamp_skipped(self, mock_forecast, mock_current):
        """Lines 367-376 continue: unparseable forecast timestamp → skip entry."""
        mock_current.return_value = 3.0
        mock_forecast.return_value = [
            {"timestamp": "not-a-date", "kp": 4.0},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        assert len(report["forecast"]) == 0

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_report_structure_complete(self, mock_forecast, mock_current):
        """Lines 297-388: happy path report structure validation."""
        mock_current.return_value = 5.0
        mock_forecast.return_value = None
        report = self.svc.get_detailed_report()
        assert report is not None
        assert "timestamp" in report
        assert "location" in report
        assert "current" in report
        assert "forecast" in report
        assert report["location"]["latitude"] == 60.0
        assert report["location"]["timezone"] == "UTC"


class TestFetchKpForecastMoreBranches:
    """Cover remaining legacy-list branches in fetch_kp_forecast."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.requests.get")
    def test_legacy_list_no_kp_column_returns_none(self, mock_get):
        """Lines 106->124, 111->124: header without 'Kp' → kp_idx=None → skip inner loop."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["time_tag", "NoKpHere"],
            ["2026-01-01 00:00:00", "1.5"],
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert result is None

    @patch("astroweather.aurora_predictions.requests.get")
    def test_legacy_list_no_time_tag_column_timestamp_empty(self, mock_get):
        """Line 120->122: header without 'time_tag' → time_idx=None → timestamp stays ''."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["Kp"],  # no 'time_tag'
            ["3.0"],
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert isinstance(result, list)
        assert result[0]["timestamp"] == ""
        assert result[0]["kp"] == pytest.approx(3.0)


class TestGetDetailedReportMoreBranches:
    """Cover remaining branches in get_detailed_report."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_forecast_fallback_kp_with_bad_float_entry(self, mock_forecast, mock_current):
        """Lines 313-314: entry with non-numeric kp in fallback → ValueError → continue."""
        mock_current.return_value = None
        # reversed() starts from the last entry; put valid at index 0 so the last
        # entry (iterated first) is invalid → hits the except branch, then continues to valid.
        mock_forecast.return_value = [
            {"timestamp": "2026-01-01T00:00:00", "kp": 5.0},
            {"timestamp": "2026-01-01T03:00:00", "kp": "not_a_float"},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        # Should ultimately use the valid entry (5.0)
        assert report["current"]["kp_index"] == pytest.approx(5.0)

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_forecast_entry_with_no_timestamp_skipped(self, mock_forecast, mock_current):
        """Lines 367->365: entry without timestamp string → skip."""
        from datetime import datetime, timezone, timedelta
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        mock_current.return_value = 3.0
        mock_forecast.return_value = [
            {"kp": 4.0},  # no 'timestamp' key
            {"timestamp": future_ts, "kp": 5.0},
        ]
        report = self.svc.get_detailed_report()
        assert report is not None
        # Only the entry with a valid future timestamp should appear in forecast
        assert len(report["forecast"]) == 1

    @patch("astroweather.aurora_predictions.AuroraService.fetch_current_kp_index")
    @patch("astroweather.aurora_predictions.AuroraService.fetch_kp_forecast")
    def test_forecast_tz_aware_timestamp_handled(self, mock_forecast, mock_current):
        """Lines 370->372: tz-aware ISO timestamp → tzinfo already set → skip replace."""
        from datetime import datetime, timezone, timedelta
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        mock_current.return_value = 3.0
        mock_forecast.return_value = [{"timestamp": future_ts, "kp": 4.0}]
        report = self.svc.get_detailed_report()
        assert report is not None
        assert len(report["forecast"]) == 1


class TestGetAuroraScoreTzAwareForecastTimestamp:
    """Cover line 232->234 in get_aurora_score."""

    def test_tz_aware_forecast_timestamp_skips_replace(self):
        """Lines 232->234: dt_utc.tzinfo is not None → branch NOT taken."""
        from datetime import datetime, timezone, timedelta
        svc = AuroraService(55.0, 10.0, "Europe/Paris")
        aware_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = svc.get_aurora_score(4.0, forecast_timestamp=aware_ts)
        assert result["timestamp"] is not None


class TestFetchKpForecastUnmatchedFormat:
    """Line 106->124: data is neither list-of-dicts nor list-of-lists."""

    def setup_method(self):
        self.svc = AuroraService(60.0, 25.0, "UTC")

    @patch("astroweather.aurora_predictions.requests.get")
    def test_unmatched_data_format_returns_none(self, mock_get):
        """Line 106->124: data is list of scalars → neither elif branch taken → returns None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [42, 43, 44]  # list of ints: not dicts, not lists
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_kp_forecast()
        assert result is None


class TestGetAuroraReport:
    """Tests for the module-level get_aurora_report convenience function."""

    @patch("astroweather.aurora_predictions.AuroraService.get_detailed_report")
    def test_delegates_to_service(self, mock_report):
        from astroweather.aurora_predictions import get_aurora_report
        mock_report.return_value = {"mocked": True}
        result = get_aurora_report(55.0, 10.0, "Europe/Paris")
        assert result == {"mocked": True}
        mock_report.assert_called_once()

    @patch("astroweather.aurora_predictions.AuroraService.get_detailed_report")
    def test_returns_none_on_failure(self, mock_report):
        from astroweather.aurora_predictions import get_aurora_report
        mock_report.return_value = None
        result = get_aurora_report(55.0, 10.0, "UTC")
        assert result is None
