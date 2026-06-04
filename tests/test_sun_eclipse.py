"""
Tests for sun_eclipse.py (SolarEclipseService).
Covers pure-logic scoring and helper methods.
"""

import pytest
import datetime
from unittest.mock import patch, MagicMock
from sun_eclipse import SolarEclipseService, SolarEclipseInfo, EclipsePoint


class TestSolarEclipseInit:
    """Tests for SolarEclipseService initialization."""

    def test_basic_init(self):
        svc = SolarEclipseService(45.0, -73.5, "America/Montreal")
        assert svc.latitude == 45.0
        assert svc.longitude == -73.5

    def test_location_object_created(self):
        svc = SolarEclipseService(0.0, 0.0, "UTC")
        assert svc.location is not None


class TestCalculateAstrophotographyScore:
    """Tests for SolarEclipseService._calculate_astrophotography_score."""

    def setup_method(self):
        self.svc = SolarEclipseService(45.0, -73.5, "America/Montreal")

    def test_not_visible_returns_zero(self):
        score, classification = self.svc._calculate_astrophotography_score(
            "Total", False, 80.0, 30.0, 120
        )
        assert score == 0.0
        assert classification == "not_visible"

    def test_total_eclipse_has_highest_base_score(self):
        # Use low altitude and short duration to avoid clamping to 10
        score_total, _ = self.svc._calculate_astrophotography_score("Total", True, 15.0, 30.0, 30)
        score_annular, _ = self.svc._calculate_astrophotography_score("Annular", True, 15.0, 30.0, 30)
        score_partial, _ = self.svc._calculate_astrophotography_score("Partial", True, 15.0, 30.0, 30)
        assert score_total > score_annular > score_partial

    def test_altitude_bonus_increases_score(self):
        score_low, _ = self.svc._calculate_astrophotography_score("Partial", True, 20.0, 30.0, 90)
        score_high, _ = self.svc._calculate_astrophotography_score("Partial", True, 80.0, 30.0, 90)
        assert score_high > score_low

    def test_duration_bonus_increases_score(self):
        score_short, _ = self.svc._calculate_astrophotography_score("Partial", True, 45.0, 30.0, 10)
        score_long, _ = self.svc._calculate_astrophotography_score("Partial", True, 45.0, 30.0, 200)
        assert score_long > score_short

    def test_score_clamped_to_0_10(self):
        score, _ = self.svc._calculate_astrophotography_score("Total", True, 90.0, 80.0, 300)
        assert 0.0 <= score <= 10.0

    def test_classification_excellent(self):
        score, classification = self.svc._calculate_astrophotography_score("Total", True, 90.0, 80.0, 300)
        assert classification == "excellent"

    def test_classification_not_visible(self):
        _, classification = self.svc._calculate_astrophotography_score("Total", False, 90.0, 80.0, 300)
        assert classification == "not_visible"

    def test_low_altitude_penalty_applied(self):
        # Use short duration to stay below the 10.0 cap
        score_5deg, _ = self.svc._calculate_astrophotography_score("Partial", True, 5.0, 20.0, 20)
        score_45deg, _ = self.svc._calculate_astrophotography_score("Partial", True, 45.0, 20.0, 20)
        assert score_45deg > score_5deg

    def test_classification_moderate(self):
        # Partial, low altitude, short duration → moderate
        score, classification = self.svc._calculate_astrophotography_score("Partial", True, 15.0, 20.0, 30)
        assert classification in ("moderate", "low", "good")


class TestGetEclipseType:
    """Tests for SolarEclipseService._get_eclipse_type."""

    def setup_method(self):
        self.svc = SolarEclipseService(45.0, -73.5, "UTC")

    def _make_eclipse_mock(self, kind_str):
        mock = MagicMock()
        mock.kind = kind_str
        return mock

    def test_total_eclipse_type(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Total"))
        assert result == "Total"

    def test_annular_eclipse_type(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Annular"))
        assert result == "Annular"

    def test_partial_eclipse_type(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Partial"))
        assert result == "Partial"

    def test_unknown_defaults_to_partial(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Unknown"))
        assert result == "Partial"


class TestFmt:
    """Tests for SolarEclipseService._fmt."""

    def test_formats_datetime_as_iso(self):
        svc = SolarEclipseService(45.0, -73.5, "UTC")
        dt = datetime.datetime(2026, 8, 12, 14, 32, 15,
                               tzinfo=datetime.timezone.utc)
        result = svc._fmt(dt)
        assert "2026-08-12" in result
        assert "14:32:15" in result


class TestCoordAttribute:
    """Tests for SolarEclipseService._coord_attribute."""

    def setup_method(self):
        self.svc = SolarEclipseService(45.0, -73.5, "UTC")

    def test_returns_none_for_missing_attribute(self):
        coord = MagicMock(spec=[])  # no attributes
        result = self.svc._coord_attribute(coord, "alt")
        assert result is None

    def test_returns_float_for_to_value_attribute(self):
        coord = MagicMock()
        coord.alt = MagicMock()
        coord.alt.to_value = MagicMock(return_value=45.3)
        result = self.svc._coord_attribute(coord, "alt")
        assert result == pytest.approx(45.3)


class TestEclipseDataclasses:
    """Tests for EclipsePoint and SolarEclipseInfo dataclasses."""

    def test_eclipse_point_creation(self):
        pt = EclipsePoint(time="14:32", altitude_deg=45.5, azimuth_deg=180.2)
        assert pt.time == "14:32"

    def test_solar_eclipse_info_creation(self):
        info = SolarEclipseInfo(
            visible=True,
            type="Partial",
            magnitude=0.45,
            obscuration_percent=45.0,
            peak_time="2026-08-12T14:32:15",
            start_time="2026-08-12T13:05:00",
            end_time="2026-08-12T16:00:00",
            peak_altitude_deg=52.3,
            peak_azimuth_deg=180.2,
            duration_minutes=174,
            astrophotography_score=6.5,
            score_classification="good",
            altitude_vs_time=[],
        )
        assert info.visible is True
        assert info.type == "Partial"
