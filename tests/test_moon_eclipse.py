"""Tests for backend moon_eclipse.py."""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from astroweather.moon_eclipse import EclipsePoint, LunarEclipseInfo, LunarEclipseService


class _Peak:
    def __init__(self, dt: datetime.datetime):
        self._dt = dt

    def Utc(self):
        return self._dt


class _Eclipse:
    def __init__(
        self,
        *,
        kind: str,
        peak: datetime.datetime,
        sd_partial: int,
        sd_total: int,
        sd_penum: int,
        obscuration: float = 1.0,
    ):
        self.kind = kind
        self.peak = _Peak(peak)
        self.sd_partial = sd_partial
        self.sd_total = sd_total
        self.sd_penum = sd_penum
        self.obscuration = obscuration


class TestLunarEclipseInit:
    def test_init_sets_fields(self):
        svc = LunarEclipseService(latitude=48.0, longitude=2.0, timezone="Europe/Paris")
        assert svc.latitude == 48.0
        assert svc.longitude == 2.0
        assert svc.location is not None
        assert svc.observer is not None


class TestFormattingAndTypes:
    def setup_method(self):
        self.svc = LunarEclipseService(latitude=48.0, longitude=2.0, timezone="UTC")

    def test_fmt_uses_iso_seconds(self):
        dt = datetime.datetime(2026, 9, 18, 22, 45, 30, tzinfo=datetime.timezone.utc)
        assert self.svc._fmt(dt) == "2026-09-18T22:45:30+00:00"

    def test_get_eclipse_type_covers_all_paths(self):
        total = MagicMock()
        total.kind = "EclipseKind.Total"
        partial = MagicMock()
        partial.kind = "EclipseKind.Partial"
        penumbral = MagicMock()
        penumbral.kind = "EclipseKind.Penumbral"

        assert self.svc._get_eclipse_type(total) == "Total"
        assert self.svc._get_eclipse_type(partial) == "Partial"
        assert self.svc._get_eclipse_type(penumbral) == "Penumbral"


class TestCoordinateHelpers:
    def setup_method(self):
        self.svc = LunarEclipseService(latitude=48.0, longitude=2.0, timezone="UTC")

    def test_coord_attribute_returns_none_when_missing(self):
        assert self.svc._coord_attribute(MagicMock(spec=[]), "alt") is None

    def test_coord_attribute_prefers_to_value(self):
        coord = MagicMock()
        coord.alt = MagicMock()
        coord.alt.to_value = MagicMock(return_value=45.3)
        assert self.svc._coord_attribute(coord, "alt") == pytest.approx(45.3)

    def test_coord_attribute_falls_back_to_float_cast(self):
        coord = MagicMock()
        coord.az = 120.4
        assert self.svc._coord_attribute(coord, "az") == pytest.approx(120.4)

    def test_coord_attribute_handles_bad_values(self):
        coord_type_error = MagicMock()
        coord_type_error.alt = object()

        coord_attr_error = MagicMock()
        coord_attr_error.alt = MagicMock()
        coord_attr_error.alt.to_value = MagicMock(side_effect=AttributeError("broken"))

        assert self.svc._coord_attribute(coord_type_error, "alt") is None
        assert self.svc._coord_attribute(coord_attr_error, "alt") is None

    @patch("astroweather.moon_eclipse.get_body")
    def test_get_moon_altitude_azimuth_uses_coord_values(self, mock_get_body):
        transformed = MagicMock()
        transformed.alt = MagicMock()
        transformed.alt.to_value = MagicMock(return_value=20.2)
        transformed.az = MagicMock()
        transformed.az.to_value = MagicMock(return_value=181.8)

        body = MagicMock()
        body.transform_to.return_value = transformed
        mock_get_body.return_value = body

        alt, az = self.svc._get_moon_altitude_azimuth(
            datetime.datetime(2026, 9, 18, 22, 45, tzinfo=datetime.timezone.utc)
        )
        assert alt == pytest.approx(20.2)
        assert az == pytest.approx(181.8)

    @patch("astroweather.moon_eclipse.get_body")
    def test_get_moon_altitude_azimuth_defaults_to_zero_when_missing(self, mock_get_body):
        transformed = MagicMock(spec=[])
        body = MagicMock()
        body.transform_to.return_value = transformed
        mock_get_body.return_value = body

        alt, az = self.svc._get_moon_altitude_azimuth(
            datetime.datetime(2026, 9, 18, 22, 45, tzinfo=datetime.timezone.utc)
        )
        assert alt == 0.0
        assert az == 0.0

    @patch("astroweather.moon_eclipse.get_body")
    def test_generate_altitude_vs_time_points_include_end_time(self, mock_get_body):
        transformed = MagicMock()
        transformed.alt = MagicMock()
        transformed.alt.to_value = MagicMock(return_value=10.04)
        transformed.az = MagicMock()
        transformed.az.to_value = MagicMock(return_value=100.06)

        body = MagicMock()
        body.transform_to.return_value = transformed
        mock_get_body.return_value = body

        start = datetime.datetime(2026, 9, 18, 20, 0, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 9, 18, 20, 10, tzinfo=datetime.timezone.utc)
        points = self.svc._generate_altitude_vs_time(start, end)

        assert len(points) == 3
        assert [p.time for p in points] == ["20:00", "20:05", "20:10"]
        assert points[0].altitude_deg == 10.0
        assert points[0].azimuth_deg == 100.1

    @patch("astroweather.moon_eclipse.get_body")
    def test_generate_altitude_vs_time_handles_missing_coordinates(self, mock_get_body):
        transformed = MagicMock(spec=[])
        body = MagicMock()
        body.transform_to.return_value = transformed
        mock_get_body.return_value = body

        start = datetime.datetime(2026, 9, 18, 20, 0, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 9, 18, 20, 0, tzinfo=datetime.timezone.utc)
        points = self.svc._generate_altitude_vs_time(start, end)

        assert len(points) == 1
        assert points[0].altitude_deg == 0.0
        assert points[0].azimuth_deg == 0.0


class TestScoring:
    def setup_method(self):
        self.svc = LunarEclipseService(latitude=48.0, longitude=2.0, timezone="UTC")

    def test_not_visible_returns_zero(self):
        score, classification = self.svc._calculate_astrophotography_score(
            eclipse_type="Total",
            visible=False,
            peak_altitude=45.0,
            partial_duration_minutes=120,
            total_duration_minutes=80,
        )
        assert score == 0.0
        assert classification == "not_visible"

    def test_case_and_whitespace_are_normalized(self):
        padded = self.svc._calculate_astrophotography_score(
            eclipse_type="  Partial  ",
            visible=True,
            peak_altitude=45.0,
            partial_duration_minutes=110,
            total_duration_minutes=0,
        )
        normalized = self.svc._calculate_astrophotography_score(
            eclipse_type="partial",
            visible=True,
            peak_altitude=45.0,
            partial_duration_minutes=110,
            total_duration_minutes=0,
        )
        assert padded == normalized

    def test_classifications_cover_all_buckets(self):
        excellent = self.svc._calculate_astrophotography_score("total", True, 90.0, 180, 100)
        very_good = self.svc._calculate_astrophotography_score("partial", True, 15.0, 180, 0)
        good = self.svc._calculate_astrophotography_score("partial", True, 10.0, 30, 0)
        moderate = self.svc._calculate_astrophotography_score("penumbral", True, 45.0, 150, 0)
        low = self.svc._calculate_astrophotography_score("penumbral", True, 10.0, 30, 0)

        assert excellent[1] == "excellent"
        assert very_good[1] == "very_good"
        assert good[1] == "good"
        assert moderate[1] == "moderate"
        assert low[1] == "low"

    def test_low_altitude_penalty_decreases_score(self):
        low_alt = self.svc._calculate_astrophotography_score("partial", True, 5.0, 60, 0)
        high_alt = self.svc._calculate_astrophotography_score("partial", True, 45.0, 60, 0)
        assert high_alt[0] > low_alt[0]


class TestGetNextEclipse:
    def setup_method(self):
        self.svc = LunarEclipseService(latitude=48.0, longitude=2.0, timezone="UTC")

    @patch("astroweather.moon_eclipse.SearchLunarEclipse", return_value=None)
    def test_get_next_eclipse_returns_none_when_no_eclipse(self, _mock_search):
        assert self.svc.get_next_eclipse() is None

    @patch.object(LunarEclipseService, "_generate_altitude_vs_time")
    @patch.object(LunarEclipseService, "_get_moon_altitude_azimuth")
    @patch("astroweather.moon_eclipse.SearchLunarEclipse")
    def test_get_next_eclipse_total_phase_path(
        self,
        mock_search,
        mock_peak_alt_az,
        mock_generate,
    ):
        peak_naive_utc = datetime.datetime(2026, 9, 18, 22, 45, 30)
        mock_search.return_value = _Eclipse(
            kind="EclipseKind.Total",
            peak=peak_naive_utc,
            sd_partial=60,
            sd_total=30,
            sd_penum=80,
            obscuration=1.0,
        )
        mock_peak_alt_az.return_value = (55.55, 182.45)
        mock_generate.return_value = [
            EclipsePoint(time="21:45", altitude_deg=30.0, azimuth_deg=150.0),
            EclipsePoint(time="22:45", altitude_deg=55.6, azimuth_deg=182.4),
        ]

        info = self.svc.get_next_eclipse()

        assert isinstance(info, LunarEclipseInfo)
        assert info.type == "Total"
        assert info.visible is True
        assert info.total_begin is not None
        assert info.total_end is not None
        assert info.partial_duration_minutes == 120
        assert info.total_duration_minutes == 60
        assert info.peak_altitude_deg == 55.55
        assert info.peak_azimuth_deg == 182.45
        assert info.obscuration_percent == 100.0
        assert len(info.altitude_vs_time) == 2

    @patch.object(LunarEclipseService, "_generate_altitude_vs_time")
    @patch.object(LunarEclipseService, "_get_moon_altitude_azimuth")
    @patch("astroweather.moon_eclipse.SearchLunarEclipse")
    def test_get_next_eclipse_penumbral_fallback_and_not_visible(
        self,
        mock_search,
        mock_peak_alt_az,
        mock_generate,
    ):
        peak_naive_utc = datetime.datetime(2026, 3, 14, 1, 0, 0)
        mock_search.return_value = _Eclipse(
            kind="EclipseKind.Penumbral",
            peak=peak_naive_utc,
            sd_partial=0,
            sd_total=0,
            sd_penum=45,
            obscuration=0.0,
        )
        mock_peak_alt_az.return_value = (-2.0, 220.0)
        mock_generate.return_value = [EclipsePoint(time="00:15", altitude_deg=0.0, azimuth_deg=220.0)]

        info = self.svc.get_next_eclipse()

        assert isinstance(info, LunarEclipseInfo)
        assert info.type == "Penumbral"
        assert info.visible is False
        assert info.obscuration_percent == 0.0
        assert info.total_begin is None
        assert info.total_end is None
        assert info.partial_duration_minutes == 90
        assert info.total_duration_minutes == 0
        assert info.astrophotography_score == 0.0
        assert info.score_classification == "not_visible"
