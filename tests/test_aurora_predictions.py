"""
Tests for aurora_predictions.py
Covers AuroraService pure-logic methods and mocked HTTP calls.
"""

import pytest
from unittest.mock import patch, MagicMock
from aurora_predictions import AuroraService


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

    @patch("aurora_predictions.requests.get")
    def test_parses_new_dict_format(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"Kp": "3.33"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result == pytest.approx(3.33)

    @patch("aurora_predictions.requests.get")
    def test_parses_legacy_list_format(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [["2026-01-01 00:00:00", "5.00"]]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = self.svc.fetch_current_kp_index()
        assert result == pytest.approx(5.0)

    @patch("aurora_predictions.requests.get")
    def test_returns_none_on_request_exception(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("timeout")
        result = self.svc.fetch_current_kp_index()
        assert result is None

    @patch("aurora_predictions.requests.get")
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

    @patch("aurora_predictions.requests.get")
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

    @patch("aurora_predictions.requests.get")
    def test_returns_none_on_request_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("network error")
        result = self.svc.fetch_kp_forecast()
        assert result is None

    @patch("aurora_predictions.requests.get")
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
