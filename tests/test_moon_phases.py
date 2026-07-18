"""Unit tests for moon_phases.py pure-logic methods."""

import sys
import os
import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from astroweather.moon_phases import MoonService


@staticmethod
def _make_service():
    return MoonService(48.85, 2.35, 'Europe/Paris')


class TestPhaseName:
    """Cover all _phase_name branches (lines 140-165)."""

    def setup_method(self):
        self.svc = MoonService(48.85, 2.35, 'Europe/Paris')

    def test_new_moon_near_zero(self):
        assert self.svc._phase_name(5.0) == "New Moon"

    def test_waxing_crescent(self):
        assert self.svc._phase_name(45.0) == "Waxing Crescent"

    def test_first_quarter(self):
        assert self.svc._phase_name(95.0) == "First Quarter"

    def test_waxing_gibbous(self):
        # Line 155: angle in [100, 170), waxing=True
        name = self.svc._phase_name(135.0)
        assert name == "Waxing Gibbous"

    def test_full_moon(self):
        name = self.svc._phase_name(180.0)
        assert name == "Full Moon"

    def test_waning_gibbous(self):
        # Lines 158-159: angle in [190, 260), waxing=False
        name = self.svc._phase_name(220.0)
        assert name == "Waning Gibbous"

    def test_last_quarter(self):
        # Lines 160-161: angle in [260, 280), waxing=False
        name = self.svc._phase_name(270.0)
        assert name == "Last Quarter"

    def test_waning_crescent(self):
        # Lines 162-163: angle >= 280, waxing=False
        name = self.svc._phase_name(320.0)
        assert name == "Waning Crescent"

    def test_angle_at_boundary_170(self):
        # angle=170 → just below full moon threshold (170 < 190 → "Full Moon" branch? No: 170 < 190 so Full Moon)
        # Actually: angle=170: 170 >= 170 so NOT in `angle < 170` → falls to `angle < 190` → Full Moon
        name = self.svc._phase_name(170.0)
        assert name == "Full Moon"

    def test_angle_at_boundary_100(self):
        # angle=100: < 170 → waxing → Waxing Gibbous (also covers line 155)
        assert self.svc._phase_name(100.0) == "Waxing Gibbous"


class TestFmt:
    """Cover _fmt method branches (line 173: astro_time_obj is None)."""

    def setup_method(self):
        self.svc = MoonService(48.85, 2.35, 'Europe/Paris')

    def test_fmt_none_returns_not_found(self):
        # Line 173
        result = self.svc._fmt(None)
        assert result == "Not found"

    def test_fmt_with_time_object(self):
        # _fmt with a real-ish time object (mock .Utc())
        mock_time = MagicMock()
        mock_utc = datetime.datetime(2026, 6, 1, 20, 0, 0)
        mock_time.Utc.return_value = mock_utc

        result = self.svc._fmt(mock_time)
        assert isinstance(result, str)
        assert '2026' in result


class TestFmtTime:
    """Cover _fmt_time method (line 184: naive datetime gets tzinfo attached)."""

    def setup_method(self):
        self.svc = MoonService(48.85, 2.35, 'Europe/Paris')

    def test_fmt_time_naive_datetime_attaches_tzinfo(self):
        # Line 184: dt_local.tzinfo is None → dt_local.replace(tzinfo=self.timezone)
        naive_dt = datetime.datetime(2026, 6, 1, 22, 0, 0)
        result = self.svc._fmt_time(naive_dt)
        assert isinstance(result, str)
        assert '2026' in result

    def test_fmt_time_aware_datetime_preserves_tzinfo(self):
        aware_dt = datetime.datetime(2026, 6, 1, 22, 0, 0, tzinfo=ZoneInfo('Europe/Paris'))
        result = self.svc._fmt_time(aware_dt)
        assert '2026' in result


class TestCoordAltitudeDeg:
    """Cover _coord_altitude_deg edge cases (lines 247, 252, 256)."""

    def setup_method(self):
        self.svc = MoonService(48.85, 2.35, 'Europe/Paris')

    def test_none_coord_returns_none(self):
        # Line 247: coord is None
        from astropy.coordinates import AltAz
        from astropy.time import Time
        from astropy.coordinates import EarthLocation
        import astropy.units as u
        t = Time('2026-06-01T20:00:00', format='isot', scale='utc')
        frame = AltAz(obstime=t, location=self.svc.location)
        result = self.svc._coord_altitude_deg(None, frame)
        assert result is None

    def test_coord_alt_none_returns_none(self):
        # Line 252: transformed.alt is None
        from astropy.coordinates import AltAz
        from astropy.time import Time
        import astropy.units as u
        t = Time('2026-06-01T20:00:00', format='isot', scale='utc')
        frame = AltAz(obstime=t, location=self.svc.location)

        mock_coord = MagicMock()
        mock_transformed = MagicMock()
        mock_coord.transform_to.return_value = mock_transformed
        # Make alt property return None
        type(mock_transformed).alt = property(lambda self: None)

        result = self.svc._coord_altitude_deg(mock_coord, frame)
        assert result is None

    def test_coord_alt_value_none_returns_none(self):
        # Line 256: alt.to_value returns None (no to_value attribute)
        from astropy.coordinates import AltAz
        from astropy.time import Time
        t = Time('2026-06-01T20:00:00', format='isot', scale='utc')
        frame = AltAz(obstime=t, location=self.svc.location)

        mock_coord = MagicMock()
        mock_transformed = MagicMock()
        mock_coord.transform_to.return_value = mock_transformed
        # alt has no to_value attribute
        mock_alt = MagicMock(spec=[])  # empty spec → hasattr(alt, 'to_value') is False
        type(mock_transformed).alt = property(lambda self: mock_alt)

        result = self.svc._coord_altitude_deg(mock_coord, frame)
        assert result is None


class TestNextAstronomicalDarkWindow:
    """Cover lines 199, 208, 216 in _next_astronomical_dark_window closures."""

    def test_refine_exhausts_when_coord_alt_returns_none(self):
        """
        Lines 199 (_is_dark_moonless returns None), 208 (_refine_first_true exhausts),
        and 216 (_refine_first_false exhausts) are reached when _coord_altitude_deg
        always returns None during fine-grained refinement.

        The coarse grid is mocked so that the first 3 slots are 'dark' and the rest are not,
        forcing one call to _refine_first_true and one call to _refine_first_false.
        """
        import numpy as np
        from unittest.mock import MagicMock, patch

        n_coarse = int((10 * 24 * 60) / 15)  # 960 points (10 days × 15-min grid)
        sun_alts = np.full(n_coarse, 5.0)
        sun_alts[:3] = -20.0  # first 3 slots → astronomical night
        moon_alts = np.full(n_coarse, -5.0)  # moon always below horizon

        def _make_alt_mock(alts_array):
            alt_mock = MagicMock()
            alt_mock.to_value.return_value = alts_array
            transformed = MagicMock()
            transformed.alt = alt_mock
            coord = MagicMock()
            coord.transform_to.return_value = transformed
            return coord

        svc = MoonService(48.85, 2.35, 'Europe/Paris')
        start = datetime.datetime(2026, 1, 1, 22, 0, 0, tzinfo=ZoneInfo('Europe/Paris'))

        with patch('astroweather.moon_phases.AstroTime', return_value=MagicMock()), \
             patch('astroweather.moon_phases.AltAz', return_value=MagicMock()), \
             patch('astroweather.moon_phases.get_sun', return_value=_make_alt_mock(sun_alts)), \
             patch('astroweather.moon_phases.get_body', return_value=_make_alt_mock(moon_alts)), \
             patch.object(MoonService, '_coord_altitude_deg', return_value=None):
            result = svc._next_astronomical_dark_window(start)

        assert isinstance(result, tuple)
        assert len(result) == 2
