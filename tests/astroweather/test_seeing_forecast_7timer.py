"""Unit tests for 7Timer atmospheric seeing forecast service."""

from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import pytest
import requests

from astroweather.seeing_forecast_7timer import (
    SeeingForecastService,
    get_seeing_forecast,
    SEEING_SCALE,
    TRANSPARENCY_SCALE,
    CLOUDCOVER_SCALE,
    WIND_SPEED_SCALE,
    _decode_rh2m_percent,
    _quality_label,
    _quality_component,
)


def _astro_point(timepoint, seeing=2, transparency=5, cloudcover=2, wind_speed=2, rh2m=4, prec_type="none"):
    """Build one 7Timer ASTRO dataseries entry with every field the real API returns."""
    return {
        "timepoint": timepoint,
        "seeing": seeing,
        "transparency": transparency,
        "cloudcover": cloudcover,
        "lifted_index": 2,
        "rh2m": rh2m,
        "wind10m": {"direction": "NW", "speed": wind_speed},
        "temp2m": 10,
        "prec_type": prec_type,
    }


class TestScaleDecodeHelpers:
    """Unit tests for the standalone decode/scoring helpers."""

    def test_seeing_scale_mapping(self):
        """Test SEEING_SCALE has all required entries."""
        assert len(SEEING_SCALE) == 8
        assert SEEING_SCALE[1]["label"] == "Excellent"
        assert "Perfect" in SEEING_SCALE[1]["conditions"]
        assert SEEING_SCALE[8]["label"] == "Bad"
        assert "Unsuitable" in SEEING_SCALE[8]["conditions"]

    def test_transparency_scale_mapping(self):
        """TRANSPARENCY_SCALE covers the real 1-8 7Timer range (not a 1-5 scale)."""
        assert len(TRANSPARENCY_SCALE) == 8
        assert TRANSPARENCY_SCALE[1]["label"] == "Very Poor"
        assert TRANSPARENCY_SCALE[8]["label"] == "Excellent"

    def test_cloudcover_scale_mapping(self):
        """CLOUDCOVER_SCALE covers the 1-9 7Timer range."""
        assert len(CLOUDCOVER_SCALE) == 9
        assert CLOUDCOVER_SCALE[1]["label"] == "Clear"
        assert CLOUDCOVER_SCALE[9]["label"] == "Overcast"

    def test_wind_speed_scale_mapping(self):
        """WIND_SPEED_SCALE covers the 1-8 7Timer range."""
        assert len(WIND_SPEED_SCALE) == 8
        assert WIND_SPEED_SCALE[1]["label"] == "Calm"
        assert WIND_SPEED_SCALE[8]["label"] == "Hurricane"

    def test_decode_rh2m_percent_boundaries(self):
        """rh2m code -4 (0-5%) and 16 (100%) decode to the documented midpoints."""
        assert _decode_rh2m_percent(-4) == pytest.approx(2.5)
        assert _decode_rh2m_percent(16) == pytest.approx(100.0, abs=0.01)

    def test_decode_rh2m_percent_invalid_returns_none(self):
        """Non-numeric rh2m values are handled gracefully."""
        assert _decode_rh2m_percent("bad") is None
        assert _decode_rh2m_percent(None) is None

    def test_quality_component_best_and_worst(self):
        """1 (best) maps to 10, N (worst) maps to 0, on an 8-point scale."""
        assert _quality_component(1, 8) == pytest.approx(10.0)
        assert _quality_component(8, 8) == pytest.approx(0.0)

    def test_quality_component_none_value(self):
        """Missing raw value contributes 0 quality rather than raising."""
        assert _quality_component(None, 8) == 0.0

    def test_quality_label_thresholds(self):
        """Quality labels match the night-score-timeline bins (>=8/6/4/2)."""
        assert _quality_label(9) == "Excellent"
        assert _quality_label(7) == "Good"
        assert _quality_label(5) == "Fair"
        assert _quality_label(3) == "Poor"
        assert _quality_label(1) == "Bad"


class TestQualityScoreFormula:
    """Tests for SeeingForecastService._compute_quality_score."""

    def test_best_conditions_score_near_ten(self):
        """Best seeing/transparency/cloud/wind values combine to a near-10 score.

        Note transparency is inverted relative to the others (8=best, not 1).
        """
        score = SeeingForecastService._compute_quality_score(1, 8, 1, 1, "none")
        assert score == pytest.approx(10.0)

    def test_worst_conditions_score_near_zero(self):
        """Worst seeing/transparency/cloud/wind values combine to a near-0 score."""
        score = SeeingForecastService._compute_quality_score(8, 1, 9, 8, "none")
        assert score == pytest.approx(0.0, abs=0.01)

    def test_precipitation_vetoes_score(self):
        """Active rain/snow multiplies an otherwise-good score down to ~10% of its value."""
        clear_score = SeeingForecastService._compute_quality_score(1, 1, 1, 1, "none")
        rain_score = SeeingForecastService._compute_quality_score(1, 1, 1, 1, "rain")
        snow_score = SeeingForecastService._compute_quality_score(1, 1, 1, 1, "snow")
        assert rain_score == pytest.approx(clear_score * 0.1, abs=0.05)
        assert snow_score == pytest.approx(clear_score * 0.1, abs=0.05)

    def test_score_is_clipped_to_valid_range(self):
        """Score never leaves [0, 10] regardless of inputs."""
        score = SeeingForecastService._compute_quality_score(1, 1, 1, 1, "none")
        assert 0.0 <= score <= 10.0


class TestSeeingForecastService:
    """Test seeing forecast service from 7Timer."""

    @pytest.fixture
    def service(self):
        """Create a service instance for testing."""
        return SeeingForecastService(
            latitude=48.866667,
            longitude=2.333333,
            timezone_str="Europe/Paris"
        )

    def test_service_initialization(self, service):
        """Test service initializes with correct parameters."""
        assert service.latitude == 48.866667
        assert service.longitude == 2.333333
        assert service.timezone_str == "Europe/Paris"

    def test_find_best_window_empty_list(self, service):
        """Test _find_best_window returns None for empty list."""
        result = service._find_best_window([], metric_key="seeing", threshold=3, higher_is_better=False)
        assert result is None

    def test_find_best_window_no_good_seeing(self, service):
        """Test _find_best_window returns None when no good seeing found."""
        now_utc = datetime.now(timezone.utc)

        forecast_list = [
            {"time": now_utc.isoformat(), "seeing": 4, "description": "Poor", "conditions": "Poor conditions"},
            {"time": (now_utc + timedelta(hours=2)).isoformat(), "seeing": 5, "description": "Very Poor", "conditions": "Unsuitable"},
        ]

        result = service._find_best_window(forecast_list, metric_key="seeing", threshold=3, higher_is_better=False)
        assert result is None

    def test_find_best_window_with_good_seeing(self, service):
        """Test _find_best_window finds excellent/good seeing window."""
        now_utc = datetime.now(timezone.utc)

        forecast_list = [
            {"time": (now_utc).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=2)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=4)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=6)).isoformat(), "seeing": 4, "description": "Poor", "conditions": "Poor conditions"},
        ]

        result = service._find_best_window(forecast_list, metric_key="seeing", threshold=3, higher_is_better=False)

        assert result is not None
        assert result["seeing"] == 1  # Minimum seeing in window
        assert result["duration_hours"] == 9  # 3 intervals * 3 hours each
        assert "Excellent" in result["description"]

    def test_find_best_window_multiple_windows(self, service):
        """Test _find_best_window selects longest window."""
        now_utc = datetime.now(timezone.utc)

        # Short good window (2 hours), then longer good window (6 hours)
        forecast_list = [
            {"time": (now_utc).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=2)).isoformat(), "seeing": 4, "description": "Poor", "conditions": "Poor"},
            {"time": (now_utc + timedelta(hours=4)).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=6)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=8)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=10)).isoformat(), "seeing": 5, "description": "Very Poor", "conditions": "Unsuitable"},
        ]

        result = service._find_best_window(forecast_list, metric_key="seeing", threshold=3, higher_is_better=False)

        assert result is not None
        assert result["duration_hours"] == 9  # Longer window wins

    def test_find_best_window_composite_quality_score(self, service):
        """The composite window uses quality_score >= threshold (higher is better)."""
        now_utc = datetime.now(timezone.utc)

        forecast_list = [
            {"time": now_utc.isoformat(), "quality_score": 3.0},
            {"time": (now_utc + timedelta(hours=3)).isoformat(), "quality_score": 7.0},
            {"time": (now_utc + timedelta(hours=6)).isoformat(), "quality_score": 8.0},
            {"time": (now_utc + timedelta(hours=9)).isoformat(), "quality_score": 2.0},
        ]

        result = service._find_best_window(forecast_list, metric_key="quality_score", threshold=6, higher_is_better=True)

        assert result is not None
        assert result["quality_score"] == 8.0  # Best (highest) value tracked in the window
        assert result["quality_label"] == "Excellent"  # >= 8 threshold
        assert result["duration_hours"] == 6

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_tonight_seeing_success(self, mock_get, service):
        """Test successful fetch from 7Timer API."""
        now_utc = datetime.now(timezone.utc)
        # Use an init time 1 hour in the future so all timepoints (3h, 6h, 9h from init) are ahead of now
        init_time = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [
                _astro_point(3, seeing=2),
                _astro_point(6, seeing=2),
                _astro_point(9, seeing=3),
            ]
        }
        mock_get.return_value = mock_response

        result = service.fetch_tonight_seeing()

        assert result is not None
        assert "location" in result
        assert "now" in result
        assert "now_quality_score" in result
        assert "now_quality_label" in result
        assert "forecast" in result
        assert "best_window" in result
        assert "best_seeing_window" in result
        assert result["location"]["latitude"] == 48.866667
        assert len(result["forecast"]) >= 1

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_tonight_seeing_api_error(self, mock_get, service):
        """Test fetch handles API errors gracefully."""
        mock_get.side_effect = requests.RequestException("API unavailable")

        result = service.fetch_tonight_seeing()

        assert result is None

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_tonight_seeing_invalid_response(self, mock_get, service):
        """Test fetch handles invalid API response."""
        mock_response = Mock()
        mock_response.json.return_value = {"invalid": "format"}
        mock_get.return_value = mock_response

        result = service.fetch_tonight_seeing()

        assert result is None

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_tonight_seeing_empty_dataseries(self, mock_get, service):
        """Test fetch handles empty dataseries."""
        now_utc = datetime.now(timezone.utc)
        init_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": []
        }
        mock_get.return_value = mock_response

        result = service.fetch_tonight_seeing()

        assert result is None

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_tonight_seeing_builds_correct_params(self, mock_get, service):
        """Test fetch sends correct parameters to API."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": "2024011500",
            "dataseries": [_astro_point(3)]
        }
        mock_get.return_value = mock_response

        service.fetch_tonight_seeing()

        # Verify the API was called
        mock_get.assert_called_once()
        call_args = mock_get.call_args

        # Check parameters
        assert call_args[1]["params"]["lat"] == 48.866667
        assert call_args[1]["params"]["lon"] == 2.333333
        assert call_args[1]["params"]["product"] == "astro"
        assert call_args[1]["params"]["output"] == "json"
        assert call_args[1]["timeout"] == 10

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_tonight_seeing_decodes_all_fields(self, mock_get, service):
        """Each forecast point exposes every decoded 7Timer field, not just seeing."""
        now_utc = datetime.now(timezone.utc)
        init_time = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [_astro_point(3, seeing=1, transparency=8, cloudcover=1, wind_speed=1, rh2m=0, prec_type="none")],
        }
        mock_get.return_value = mock_response

        result = service.fetch_tonight_seeing()
        point = result["forecast"][0]

        assert point["transparency"] == 8
        assert point["transparency_label"] == "Excellent"
        assert point["cloudcover"] == 1
        assert point["cloudcover_label"] == "Clear"
        assert point["wind_speed_class"] == 1
        assert point["wind_label"] == "Calm"
        assert point["wind_direction"] == "NW"
        assert point["humidity_percent"] == pytest.approx(22.5)
        assert point["lifted_index"] == 2
        assert point["prec_type"] == "none"
        assert point["quality_score"] == pytest.approx(10.0)
        assert point["quality_label"] == "Excellent"


class TestGetSeeingForecastWrapper:
    """Test top-level wrapper function."""

    @patch.object(SeeingForecastService, 'fetch_tonight_seeing')
    def test_get_seeing_forecast_success(self, mock_fetch):
        """Test wrapper calls service correctly."""
        mock_forecast = {
            "now": 2,
            "forecast": [],
            "best_window": None
        }
        mock_fetch.return_value = mock_forecast

        result = get_seeing_forecast(45.5, -73.5, "America/Montreal")

        assert result == mock_forecast
        mock_fetch.assert_called_once()

    @patch.object(SeeingForecastService, 'fetch_tonight_seeing')
    def test_get_seeing_forecast_failure(self, mock_fetch):
        """Test wrapper handles service failures."""
        mock_fetch.return_value = None

        result = get_seeing_forecast(45.5, -73.5, "America/Montreal")

        assert result is None

    def test_get_seeing_forecast_creates_service_with_correct_params(self):
        """Test wrapper creates service with correct parameters."""
        with patch.object(SeeingForecastService, 'fetch_tonight_seeing', return_value=None):
            get_seeing_forecast(48.5, 2.5, "Europe/Paris")

            # If no exception, the service was created correctly


class TestSeeingForecastBranchCoverage:
    """Targeted tests for uncovered branches in seeing_forecast_7timer.py."""

    @pytest.fixture
    def service(self):
        return SeeingForecastService(48.866667, 2.333333, "Europe/Paris")

    def test_find_best_window_improves_within_window(self, service):
        """Second consecutive good point has lower seeing."""
        now_utc = datetime.now(timezone.utc)
        forecast_list = [
            {"time": now_utc.isoformat(), "seeing": 3, "description": "OK", "conditions": "OK"},
            {"time": (now_utc + timedelta(hours=3)).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=6)).isoformat(), "seeing": 5, "description": "Poor", "conditions": "Bad"},
        ]
        result = service._find_best_window(forecast_list, metric_key="seeing", threshold=3, higher_is_better=False)
        assert result is not None
        assert result["seeing"] == 1  # lower seeing was tracked

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_bad_init_string_uses_fallback(self, mock_get, service):
        """Malformed init string falls back to requested_init."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": "BADFORMAT",
            "dataseries": [_astro_point(3)],
        }
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        # Should succeed with fallback init time
        assert result is not None

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_bad_timepoint_is_skipped(self, mock_get, service):
        """Bad timepoint/seeing values are skipped via continue."""
        now_utc = datetime.now(timezone.utc)
        init_time = now_utc.replace(minute=0, second=0, microsecond=0)
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [
                {**_astro_point("bad", seeing=2), "timepoint": "bad"},   # bad timepoint -> skip
                {**_astro_point(3), "seeing": "bad"},                    # bad seeing -> skip
                _astro_point(6, seeing=2),                               # valid
            ],
        }
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        assert result is not None
        # Only the valid entry should be in forecast
        assert any(p["seeing"] == 2 for p in result.get("forecast", []))

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_out_of_range_seeing_skipped(self, mock_get, service):
        """Seeing values outside 1-8 are skipped."""
        now_utc = datetime.now(timezone.utc)
        init_time = now_utc.replace(minute=0, second=0, microsecond=0)
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [
                _astro_point(3, seeing=-9999),   # out of range -> skip
                _astro_point(6, seeing=9),        # out of range -> skip
                _astro_point(9, seeing=2),        # valid
            ],
        }
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        assert result is not None
        # Only valid entry should appear
        valid_points = [p for p in result.get("forecast", []) if p["seeing"] in (2,)]
        assert len(valid_points) >= 1

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_all_seeing_out_of_range_returns_empty_struct(self, mock_get, service):
        """When all seeing values are out of range, returns empty forecast struct."""
        now_utc = datetime.now(timezone.utc)
        init_time = now_utc.replace(minute=0, second=0, microsecond=0)
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [
                _astro_point(3, seeing=-9999),
                _astro_point(6, seeing=0),
            ],
        }
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        assert result is not None
        assert result["forecast"] == []
        assert result["now"] is None
        assert result["best_window"] is None
        assert result["best_seeing_window"] is None

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_fetch_generic_exception_returns_none(self, mock_get, service):
        """Generic Exception during processing returns None."""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("bad JSON")
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        assert result is None


class TestSeeingForecastRemainingBranches:
    """Cover remaining branches in _find_best_window and field parsing."""

    @pytest.fixture
    def service(self):
        return SeeingForecastService(48.866667, 2.333333, "Europe/Paris")

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_none_timepoint_skipped(self, mock_get, service):
        """data point with None timepoint -> skip (if body not entered)."""
        now_utc = datetime.now(timezone.utc)
        init_time = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [
                {**_astro_point(None, seeing=2), "timepoint": None},  # timepoint is None -> skip
                _astro_point(3, seeing=2),                             # valid
            ],
        }
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        assert result is not None
        assert len(result.get("forecast", [])) == 1

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_missing_optional_fields_default_gracefully(self, mock_get, service):
        """A dataseries entry missing the new optional fields still parses (only seeing required)."""
        now_utc = datetime.now(timezone.utc)
        init_time = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [{"timepoint": 3, "seeing": 2}],
        }
        mock_get.return_value = mock_response
        result = service.fetch_tonight_seeing()
        assert result is not None
        point = result["forecast"][0]
        assert point["seeing"] == 2
        assert point["transparency"] is None
        assert point["transparency_label"] == "Unknown"
        assert point["prec_type"] == "none"
        assert point["quality_score"] is not None

    def test_find_best_window_shorter_mid_window_does_not_replace(self, service):
        """mid-scan window shorter than best -> False branch."""
        now_utc = datetime.now(timezone.utc)
        # Window 1: 4 good points (12h) -> best_duration=12
        # Bad seeing (closes window 1)
        # Window 2: 1 good point (3h) -> 3 > 12 is False -> doesn't replace best
        # Bad seeing (closes window 2)
        forecast_list = [
            {"time": now_utc.isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=3)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=6)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=9)).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=12)).isoformat(), "seeing": 5, "description": "Poor", "conditions": "Bad"},
            {"time": (now_utc + timedelta(hours=15)).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=18)).isoformat(), "seeing": 5, "description": "Poor", "conditions": "Bad"},
        ]
        result = service._find_best_window(forecast_list, metric_key="seeing", threshold=3, higher_is_better=False)
        assert result is not None
        assert result["duration_hours"] == 12  # window 1 wins

    def test_find_best_window_shorter_end_window(self, service):
        """end-of-list window shorter than best -> False branch."""
        now_utc = datetime.now(timezone.utc)
        # Window 1: 4 good points (12h) -> best_duration=12 (closes via bad seeing)
        # Window 2: 1 good point (3h) at end -> 3 > 12 is False -> doesn't replace best
        forecast_list = [
            {"time": now_utc.isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=3)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=6)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
            {"time": (now_utc + timedelta(hours=9)).isoformat(), "seeing": 1, "description": "Excellent", "conditions": "Perfect"},
            {"time": (now_utc + timedelta(hours=12)).isoformat(), "seeing": 5, "description": "Poor", "conditions": "Bad"},
            {"time": (now_utc + timedelta(hours=15)).isoformat(), "seeing": 2, "description": "Good", "conditions": "Very good"},
        ]
        result = service._find_best_window(forecast_list, metric_key="seeing", threshold=3, higher_is_better=False)
        assert result is not None
        assert result["duration_hours"] == 12  # window 1 wins, end window (3h) doesn't replace


class TestSeeingForecastIntegration:
    """Integration tests for seeing forecast with cache."""

    @patch('astroweather.seeing_forecast_7timer.requests.get')
    def test_forecast_response_structure(self, mock_get):
        """Test the complete response structure is correct."""
        now_utc = datetime.now(timezone.utc)
        init_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        mock_response = Mock()
        mock_response.json.return_value = {
            "init": init_time.strftime("%Y%m%d%H"),
            "dataseries": [
                _astro_point(3, seeing=1),
                _astro_point(6, seeing=2),
                _astro_point(9, seeing=2),
                _astro_point(12, seeing=3),
            ]
        }
        mock_get.return_value = mock_response

        service = SeeingForecastService(45.5, -73.5, "America/Montreal")
        result = service.fetch_tonight_seeing()

        assert result is not None
        assert "location" in result
        assert isinstance(result["location"], dict)
        assert result["location"]["latitude"] == 45.5
        assert result["location"]["longitude"] == -73.5
        assert result["location"]["timezone"] == "America/Montreal"

        assert "now" in result
        assert isinstance(result["now"], int) or result["now"] is None

        assert "now_description" in result
        assert isinstance(result["now_description"], str)

        assert "now_quality_score" in result
        assert "now_quality_label" in result

        assert "forecast" in result
        assert isinstance(result["forecast"], list)

        for point in result["forecast"]:
            assert "time" in point
            assert "seeing" in point
            assert "description" in point
            assert "conditions" in point
            assert "transparency" in point
            assert "transparency_label" in point
            assert "cloudcover" in point
            assert "cloudcover_label" in point
            assert "wind_speed_class" in point
            assert "wind_label" in point
            assert "wind_direction" in point
            assert "humidity_percent" in point
            assert "lifted_index" in point
            assert "prec_type" in point
            assert "quality_score" in point
            assert "quality_label" in point

        assert "best_window" in result
        if result["best_window"]:
            assert "start" in result["best_window"]
            assert "quality_score" in result["best_window"]
            assert "quality_label" in result["best_window"]
            assert "duration_hours" in result["best_window"]

        assert "best_seeing_window" in result
        if result["best_seeing_window"]:
            assert "start" in result["best_seeing_window"]
            assert "seeing" in result["best_seeing_window"]
            assert "description" in result["best_seeing_window"]
            assert "duration_hours" in result["best_seeing_window"]

        assert "updated_at" in result
