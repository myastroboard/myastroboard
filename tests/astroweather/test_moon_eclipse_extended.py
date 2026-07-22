"""
Extended tests for moon_eclipse.py (LunarEclipseService).

Supplements test_moon_eclipse.py with scenarios not already covered there
(a Partial-kind eclipse through get_next_eclipse(), plus the EclipsePoint /
LunarEclipseInfo dataclass shapes) rather than re-testing the same paths.
"""

import datetime
from unittest.mock import patch

from astroweather.moon_eclipse import LunarEclipseService, LunarEclipseInfo, EclipsePoint


class _Peak:
    def __init__(self, dt: datetime.datetime):
        self._dt = dt

    def Utc(self):
        return self._dt


class _Eclipse:
    def __init__(self, *, kind, peak, sd_partial, sd_total, sd_penum, obscuration=1.0):
        self.kind = kind
        self.peak = _Peak(peak)
        self.sd_partial = sd_partial
        self.sd_total = sd_total
        self.sd_penum = sd_penum
        self.obscuration = obscuration


class TestGetNextEclipsePartialKind:
    """A Partial eclipse (sd_partial > 0, sd_total == 0) through get_next_eclipse().

    test_moon_eclipse.py's TestGetNextEclipse only exercises the Total and
    Penumbral end-to-end paths; this covers the remaining Partial-kind path,
    which also takes the sd_partial > 0 branch (as opposed to the sd_penum
    fallback already covered by the Penumbral case there).
    """

    def setup_method(self):
        self.svc = LunarEclipseService(latitude=48.0, longitude=2.0, timezone="UTC")

    @patch.object(LunarEclipseService, "_generate_altitude_vs_time")
    @patch.object(LunarEclipseService, "_get_moon_altitude_azimuth")
    @patch("astroweather.moon_eclipse.SearchLunarEclipse")
    def test_get_next_eclipse_partial_kind_has_no_total_phase(
        self, mock_search, mock_peak_alt_az, mock_generate
    ):
        peak_naive_utc = datetime.datetime(2026, 6, 20, 3, 30, 0)
        mock_search.return_value = _Eclipse(
            kind="EclipseKind.Partial",
            peak=peak_naive_utc,
            sd_partial=50,
            sd_total=0,
            sd_penum=90,
            obscuration=0.35,
        )
        mock_peak_alt_az.return_value = (40.0, 200.0)
        mock_generate.return_value = [EclipsePoint(time="03:00", altitude_deg=35.0, azimuth_deg=195.0)]

        info = self.svc.get_next_eclipse()

        assert isinstance(info, LunarEclipseInfo)
        assert info.type == "Partial"
        assert info.visible is True
        assert info.total_begin is None
        assert info.total_end is None
        assert info.total_duration_minutes == 0
        # Uses sd_partial (50), not sd_penum (90), since sd_partial > 0
        assert info.partial_duration_minutes == 100
        assert info.obscuration_percent == 35.0


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
            obscuration_percent=100.0,
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
            obscuration_percent=0.0,
            astrophotography_score=3.5,
            score_classification="low",
            altitude_vs_time=[],
        )
        assert info.total_begin is None
        assert info.total_end is None


class TestCalculateAstrophotographyScoreExtra:
    """Score-shape behaviors not already covered by test_moon_eclipse.py's TestScoring."""

    def setup_method(self):
        self.svc = LunarEclipseService(45.0, -73.5, "America/Montreal")

    def test_total_has_highest_base_score(self):
        score_total, _ = self.svc._calculate_astrophotography_score("Total", True, 15.0, 30, 0)
        score_partial, _ = self.svc._calculate_astrophotography_score("Partial", True, 15.0, 30, 0)
        score_penum, _ = self.svc._calculate_astrophotography_score("Penumbral", True, 15.0, 30, 0)
        assert score_total > score_partial > score_penum

    def test_score_clamped_to_0_to_10(self):
        score, _ = self.svc._calculate_astrophotography_score("Total", True, 90.0, 360, 120)
        assert 0.0 <= score <= 10.0

    def test_total_duration_bonus_adds_value(self):
        score_no_total, _ = self.svc._calculate_astrophotography_score("Total", True, 45.0, 180, 0)
        score_with_total, _ = self.svc._calculate_astrophotography_score("Total", True, 45.0, 180, 100)
        assert score_with_total >= score_no_total
