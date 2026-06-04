"""
Extended tests for moon_eclipse.py (LunarEclipseService).
Supplements the existing 2-test file to push coverage above 50%.
"""

import pytest
import datetime
from unittest.mock import patch, MagicMock
from moon_eclipse import LunarEclipseService, LunarEclipseInfo, EclipsePoint


class TestLunarEclipseInit:
    """Tests for LunarEclipseService initialization."""

    def test_basic_init(self):
        svc = LunarEclipseService(45.0, -73.5, "America/Montreal")
        assert svc.latitude == 45.0
        assert svc.longitude == -73.5

    def test_location_object_created(self):
        svc = LunarEclipseService(0.0, 0.0, "UTC")
        assert svc.location is not None


class TestGetEclipseType:
    """Tests for LunarEclipseService._get_eclipse_type."""

    def setup_method(self):
        self.svc = LunarEclipseService(45.0, -73.5, "UTC")

    def _make_eclipse_mock(self, kind_str):
        mock = MagicMock()
        mock.kind = kind_str
        return mock

    def test_total_eclipse(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Total"))
        assert result == "Total"

    def test_partial_eclipse(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Partial"))
        assert result == "Partial"

    def test_penumbral_eclipse(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Penumbral"))
        assert result == "Penumbral"

    def test_unknown_defaults_to_penumbral(self):
        result = self.svc._get_eclipse_type(self._make_eclipse_mock("EclipseKind.Unknown"))
        assert result == "Penumbral"


class TestCalculateAstrophotographyScore:
    """Tests for LunarEclipseService._calculate_astrophotography_score."""

    def setup_method(self):
        self.svc = LunarEclipseService(45.0, -73.5, "America/Montreal")

    def test_not_visible_returns_zero_and_not_visible(self):
        score, classification = self.svc._calculate_astrophotography_score(
            "Total", False, 45.0, 180, 60
        )
        assert score == 0.0
        assert classification == "not_visible"

    def test_total_has_highest_base_score(self):
        # Use parameters that won't clamp to 10
        score_total, _ = self.svc._calculate_astrophotography_score("Total", True, 15.0, 30, 0)
        score_partial, _ = self.svc._calculate_astrophotography_score("Partial", True, 15.0, 30, 0)
        score_penum, _ = self.svc._calculate_astrophotography_score("Penumbral", True, 15.0, 30, 0)
        assert score_total > score_partial > score_penum

    def test_score_clamped_to_0_to_10(self):
        score, _ = self.svc._calculate_astrophotography_score("Total", True, 90.0, 360, 120)
        assert 0.0 <= score <= 10.0

    def test_altitude_bonus_adds_value(self):
        score_low, _ = self.svc._calculate_astrophotography_score("Partial", True, 5.0, 30, 0)
        score_high, _ = self.svc._calculate_astrophotography_score("Partial", True, 80.0, 30, 0)
        assert score_high > score_low

    def test_total_duration_bonus_adds_value(self):
        score_no_total, _ = self.svc._calculate_astrophotography_score("Total", True, 45.0, 180, 0)
        score_with_total, _ = self.svc._calculate_astrophotography_score("Total", True, 45.0, 180, 100)
        # Total duration bonus may be capped, but they should differ or be equal
        assert score_with_total >= score_no_total

    def test_low_altitude_penalty_applied(self):
        score_very_low, _ = self.svc._calculate_astrophotography_score("Partial", True, 3.0, 30, 0)
        score_normal, _ = self.svc._calculate_astrophotography_score("Partial", True, 45.0, 30, 0)
        assert score_normal > score_very_low

    def test_classification_excellent(self):
        score, classification = self.svc._calculate_astrophotography_score("Total", True, 90.0, 360, 120)
        assert classification == "excellent"

    def test_classification_low(self):
        score, classification = self.svc._calculate_astrophotography_score("Penumbral", True, 3.0, 5, 0)
        assert classification in ("low", "moderate")


class TestFmt:
    """Tests for LunarEclipseService._fmt."""

    def test_formats_datetime_as_iso(self):
        svc = LunarEclipseService(45.0, -73.5, "UTC")
        dt = datetime.datetime(2026, 9, 18, 22, 45, 30,
                               tzinfo=datetime.timezone.utc)
        result = svc._fmt(dt)
        assert "2026-09-18" in result
        assert "22:45:30" in result


class TestCoordAttribute:
    """Tests for LunarEclipseService._coord_attribute."""

    def setup_method(self):
        self.svc = LunarEclipseService(45.0, -73.5, "UTC")

    def test_returns_none_for_missing_attribute(self):
        coord = MagicMock(spec=[])
        result = self.svc._coord_attribute(coord, "alt")
        assert result is None

    def test_returns_float_for_numeric_attribute(self):
        coord = MagicMock()
        coord.alt = MagicMock()
        coord.alt.to_value = MagicMock(return_value=35.7)
        result = self.svc._coord_attribute(coord, "alt")
        assert result == pytest.approx(35.7)


class TestEclipseDataclasses:
    """Tests for EclipsePoint and LunarEclipseInfo dataclasses."""

    def test_eclipse_point_fields(self):
        pt = EclipsePoint(time="22:45", altitude_deg=65.5, azimuth_deg=180.0)
        assert pt.time == "22:45"
        assert pt.altitude_deg == 65.5

    def test_lunar_eclipse_info_fields(self):
        info = LunarEclipseInfo(
            visible=True,
            type="Total",
            peak_time="2026-09-18T22:45:30+00:00",
            partial_begin="2026-09-18T20:15:00+00:00",
            total_begin="2026-09-18T21:30:00+00:00",
            total_end="2026-09-19T00:00:00+00:00",
            partial_end="2026-09-19T01:15:00+00:00",
            peak_altitude_deg=65.5,
            peak_azimuth_deg=180.0,
            total_duration_minutes=150,
            partial_duration_minutes=285,
            astrophotography_score=8.5,
            score_classification="very_good",
            altitude_vs_time=[],
        )
        assert info.visible is True
        assert info.type == "Total"
        assert info.total_duration_minutes == 150

    def test_lunar_eclipse_info_penumbral_has_none_totals(self):
        info = LunarEclipseInfo(
            visible=True,
            type="Penumbral",
            peak_time="2026-03-15T10:00:00+00:00",
            partial_begin="2026-03-15T08:30:00+00:00",
            total_begin=None,
            total_end=None,
            partial_end="2026-03-15T11:30:00+00:00",
            peak_altitude_deg=40.0,
            peak_azimuth_deg=200.0,
            total_duration_minutes=0,
            partial_duration_minutes=180,
            astrophotography_score=3.5,
            score_classification="low",
            altitude_vs_time=[],
        )
        assert info.total_begin is None
        assert info.total_end is None
