"""
Tests for sun_eclipse.py (SolarEclipseService).
Covers pure-logic scoring and helper methods.
"""

import pytest
import datetime
from unittest.mock import patch, MagicMock
from astroweather.sun_eclipse import SolarEclipseService, SolarEclipseInfo, EclipsePoint


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

    def test_classification_moderate_threshold_path(self):
        score, classification = self.svc._calculate_astrophotography_score("Partial", True, 0.0, 5.0, 0)
        assert 3.0 <= score < 5.0
        assert classification == "moderate"

    def test_classification_low_path(self):
        score, classification = self.svc._calculate_astrophotography_score("Partial", True, 0.0, -60.0, 0)
        assert score < 3.0
        assert classification == "low"


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

    def test_falls_back_to_float_conversion(self):
        coord = MagicMock()
        coord.az = 123.4
        result = self.svc._coord_attribute(coord, "az")
        assert result == pytest.approx(123.4)

    def test_returns_none_on_attribute_or_type_errors(self):
        coord_attr_error = MagicMock()
        coord_attr_error.alt = MagicMock()
        coord_attr_error.alt.to_value = MagicMock(side_effect=AttributeError("bad attr"))

        coord_type_error = MagicMock()
        coord_type_error.alt = object()

        assert self.svc._coord_attribute(coord_attr_error, "alt") is None
        assert self.svc._coord_attribute(coord_type_error, "alt") is None


class TestSunGeometry:
    def setup_method(self):
        self.svc = SolarEclipseService(45.0, -73.5, "UTC")

    @patch("astroweather.sun_eclipse.get_sun")
    def test_get_sun_azimuth_returns_transformed_value(self, mock_get_sun):
        transformed = MagicMock()
        transformed.az = MagicMock()
        transformed.az.to_value = MagicMock(return_value=210.2)

        sun = MagicMock()
        sun.transform_to.return_value = transformed
        mock_get_sun.return_value = sun

        az = self.svc._get_sun_azimuth(datetime.datetime(2026, 8, 12, 14, 32, tzinfo=datetime.timezone.utc))
        assert az == pytest.approx(210.2)

    @patch("astroweather.sun_eclipse.get_sun")
    def test_get_sun_azimuth_defaults_to_zero_when_missing(self, mock_get_sun):
        transformed = MagicMock(spec=[])
        sun = MagicMock()
        sun.transform_to.return_value = transformed
        mock_get_sun.return_value = sun

        az = self.svc._get_sun_azimuth(datetime.datetime(2026, 8, 12, 14, 32, tzinfo=datetime.timezone.utc))
        assert az == 0.0

    @patch("astroweather.sun_eclipse.get_sun")
    def test_generate_altitude_vs_time_includes_end_point(self, mock_get_sun):
        transformed = MagicMock()
        transformed.alt = MagicMock()
        transformed.alt.to_value = MagicMock(return_value=30.04)
        transformed.az = MagicMock()
        transformed.az.to_value = MagicMock(return_value=110.06)

        sun = MagicMock()
        sun.transform_to.return_value = transformed
        mock_get_sun.return_value = sun

        start = datetime.datetime(2026, 8, 12, 13, 0, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 8, 12, 13, 10, tzinfo=datetime.timezone.utc)
        points = self.svc._generate_altitude_vs_time(start, end)

        assert len(points) == 3
        assert [p.time for p in points] == ["13:00", "13:05", "13:10"]
        assert points[0].altitude_deg == 30.0
        assert points[0].azimuth_deg == 110.1

    @patch("astroweather.sun_eclipse.get_sun")
    def test_generate_altitude_vs_time_defaults_missing_coords_to_zero(self, mock_get_sun):
        transformed = MagicMock(spec=[])
        sun = MagicMock()
        sun.transform_to.return_value = transformed
        mock_get_sun.return_value = sun

        start = datetime.datetime(2026, 8, 12, 13, 0, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 8, 12, 13, 0, tzinfo=datetime.timezone.utc)
        points = self.svc._generate_altitude_vs_time(start, end)

        assert len(points) == 1
        assert points[0].altitude_deg == 0.0
        assert points[0].azimuth_deg == 0.0


class _TimeWrapper:
    def __init__(self, dt):
        self._dt = dt

    def Utc(self):
        return self._dt


class _Event:
    def __init__(self, dt):
        self.time = _TimeWrapper(dt)


class _Peak:
    def __init__(self, dt, altitude):
        self.time = _TimeWrapper(dt)
        self.altitude = altitude


class _Eclipse:
    def __init__(self, *, kind, peak_dt, peak_altitude, start_dt, end_dt, obscuration):
        self.kind = kind
        self.peak = _Peak(peak_dt, peak_altitude)
        self.partial_begin = _Event(start_dt)
        self.partial_end = _Event(end_dt)
        self.obscuration = obscuration


class TestGetNextEclipse:
    def setup_method(self):
        self.svc = SolarEclipseService(45.0, -73.5, "UTC")

    @patch("astroweather.sun_eclipse.SearchLocalSolarEclipse", return_value=None)
    def test_returns_none_when_no_eclipse_found(self, _mock_search):
        assert self.svc.get_next_eclipse() is None

    @patch.object(SolarEclipseService, "_generate_altitude_vs_time")
    @patch.object(SolarEclipseService, "_get_sun_azimuth")
    @patch("astroweather.sun_eclipse.SearchLocalSolarEclipse")
    def test_get_next_eclipse_total_path(self, mock_search, mock_az, mock_alttime):
        peak_naive_utc = datetime.datetime(2026, 8, 12, 14, 32, 15)
        start_naive_utc = datetime.datetime(2026, 8, 12, 13, 5, 0)
        end_naive_utc = datetime.datetime(2026, 8, 12, 15, 59, 0)

        mock_search.return_value = _Eclipse(
            kind="EclipseKind.Total",
            peak_dt=peak_naive_utc,
            peak_altitude=52.345,
            start_dt=start_naive_utc,
            end_dt=end_naive_utc,
            obscuration=0.98765,
        )
        mock_az.return_value = 180.245
        mock_alttime.return_value = [
            EclipsePoint(time="13:05", altitude_deg=10.0, azimuth_deg=90.0),
            EclipsePoint(time="14:35", altitude_deg=52.3, azimuth_deg=180.2),
        ]

        info = self.svc.get_next_eclipse()

        assert isinstance(info, SolarEclipseInfo)
        assert info.visible is True
        assert info.type == "Total"
        assert info.magnitude == 0.9877
        assert info.obscuration_percent == 98.8
        assert info.peak_altitude_deg == 52.34
        assert info.peak_azimuth_deg == 180.25
        assert info.duration_minutes == 174
        assert info.score_classification == "excellent"
        assert len(info.altitude_vs_time) == 2

    @patch.object(SolarEclipseService, "_generate_altitude_vs_time")
    @patch.object(SolarEclipseService, "_get_sun_azimuth")
    @patch("astroweather.sun_eclipse.SearchLocalSolarEclipse")
    def test_get_next_eclipse_non_visible_clamps_negative_altitude(
        self,
        mock_search,
        mock_az,
        mock_alttime,
    ):
        peak_naive_utc = datetime.datetime(2026, 8, 12, 14, 32, 15)
        start_naive_utc = datetime.datetime(2026, 8, 12, 13, 5, 0)
        end_naive_utc = datetime.datetime(2026, 8, 12, 13, 45, 0)

        mock_search.return_value = _Eclipse(
            kind="EclipseKind.Annular",
            peak_dt=peak_naive_utc,
            peak_altitude=-4.0,
            start_dt=start_naive_utc,
            end_dt=end_naive_utc,
            obscuration=0.42,
        )
        mock_az.return_value = 240.0
        mock_alttime.return_value = [EclipsePoint(time="13:05", altitude_deg=0.0, azimuth_deg=240.0)]

        info = self.svc.get_next_eclipse()

        assert isinstance(info, SolarEclipseInfo)
        assert info.type == "Annular"
        assert info.visible is False
        assert info.peak_altitude_deg == 0.0
        assert info.astrophotography_score == 0.0
        assert info.score_classification == "not_visible"


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
