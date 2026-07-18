"""Branch coverage tests for sun_phases.py."""

import datetime
from unittest.mock import patch

import numpy as np

from astroweather.sun_phases import SunService, SunAstroInfo


class _FakeAlt:
    def __init__(self, deg):
        self.deg = deg


class _FakeTransformed:
    def __init__(self, deg):
        self.alt = _FakeAlt(deg)


class _FakeSun:
    def __init__(self, deg):
        self._deg = deg

    def transform_to(self, _frame):
        return _FakeTransformed(self._deg)


class _FakeSunArray:
    def __init__(self, alts):
        self._alts = alts

    def transform_to(self, _frame):
        return _FakeTransformed(np.asarray(self._alts))


class TestSunServiceBranches:
    def test_fmt_none_returns_not_found(self):
        svc = SunService(45.5, -73.5, "UTC")
        assert svc._fmt(None) == "Not found"

    @patch("astroweather.sun_phases.get_sun")
    def test_compute_day_handles_no_crossings(self, mock_get_sun):
        svc = SunService(45.5, -73.5, "UTC")

        # Sun always high above all thresholds -> no up/down threshold crossings.
        mock_get_sun.return_value = _FakeSunArray(np.full(289, 30.0))

        report = svc._compute_day(datetime.date(2026, 6, 5))

        assert isinstance(report, SunAstroInfo)
        assert report.sunrise == "Not found"
        assert report.sunset == "Not found"
        assert report.civil_dawn == "Not found"
        assert report.civil_dusk == "Not found"
        assert report.nautical_dawn == "Not found"
        assert report.nautical_dusk == "Not found"
        assert report.astronomical_dawn == "Not found"
        assert report.astronomical_dusk == "Not found"
        assert report.true_night_hours == 0

    @patch("astroweather.sun_phases.get_sun")
    def test_sun_altitude_uses_astropy_path(self, mock_get_sun):
        svc = SunService(45.5, -73.5, "UTC")
        mock_get_sun.return_value = _FakeSun(12.34)

        dt = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        altitude = svc._sun_altitude(dt)

        assert altitude == 12.34
