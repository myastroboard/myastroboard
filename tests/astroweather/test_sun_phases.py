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


class TestSunsetAltitudeConvention:
    """Sunset/sunrise use the standard -0.833° centre altitude with interpolation."""

    def test_standard_altitude_constant(self):
        from astroweather.sun_phases import SUN_STANDARD_ALTITUDE

        assert SUN_STANDARD_ALTITUDE == -0.833

    @patch("astroweather.sun_phases.get_sun")
    def test_sunset_crosses_standard_altitude_with_interpolation(self, mock_get_sun):
        from astroweather.sun_phases import SUN_STANDARD_ALTITUDE

        svc = SunService(45.0, 0.0, "UTC")  # UTC so local == UTC for easy comparison
        n = 289  # noon -> next noon at 5-min steps (inclusive)
        alts = np.linspace(5.0, -5.0, n)  # Sun descends monotonically across the window
        mock_get_sun.return_value = _FakeSunArray(alts)

        report = svc._compute_day(datetime.date(2026, 6, 5))

        # Analytic crossing of the standard altitude, interpolated between samples.
        deg_per_sample = 10.0 / (n - 1)
        idx = (5.0 - SUN_STANDARD_ALTITUDE) / deg_per_sample
        start_utc = datetime.datetime(2026, 6, 5, 12, 0, tzinfo=datetime.timezone.utc)
        expected = start_utc + datetime.timedelta(minutes=idx * 5)
        got = datetime.datetime.strptime(report.sunset, "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)

        # Interpolation should land within a minute of the analytic crossing (the old
        # snap-to-next-sample behaviour would have been up to 5 minutes late).
        assert abs((got - expected).total_seconds()) < 120
