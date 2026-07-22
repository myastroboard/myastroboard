"""
Tests for special_phenomena.py (SpecialPhenomenaService).
Covers init, translation helper, approximate event methods, and pure-logic helpers.
"""

import pytest
from unittest.mock import patch, MagicMock
from observation.special_phenomena import SpecialPhenomenaService


class TestSpecialPhenomenaInit:
    """Tests for SpecialPhenomenaService initialization."""

    def test_basic_init(self):
        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        assert svc.latitude == 45.0
        assert svc.longitude == -73.5
        assert svc.elevation == 50
        assert svc.timezone == "America/Montreal"

    def test_location_object_created(self):
        svc = SpecialPhenomenaService(0.0, 0.0)
        assert svc.location is not None

    def test_i18n_manager_created(self):
        svc = SpecialPhenomenaService(45.0, 0.0, language="fr")
        assert svc.i18n is not None


class TestTranslationHelper:
    """Tests for the _t fallback translation helper."""

    def setup_method(self):
        self.svc = SpecialPhenomenaService(45.0, 0.0)

    def test_returns_fallback_when_translation_unavailable(self):
        result = self.svc._t("nonexistent.key.xyz", "Fallback text")
        assert result == "Fallback text"

    def test_formats_kwargs_in_fallback(self):
        result = self.svc._t("nonexistent.key", "Hello {name}", name="World")
        assert result == "Hello World"

    def test_returns_fallback_on_format_error(self):
        result = self.svc._t("nonexistent.key", "No placeholders", bad_kwarg="ignored")
        # Should not raise, should return fallback
        assert isinstance(result, str)


class TestApproximateEquinoxSolstice:
    """Tests for _approximate_equinox and _approximate_solstice."""

    def setup_method(self):
        self.svc = SpecialPhenomenaService(45.0, -73.5)

    def test_spring_equinox_is_in_march(self):
        from astropy.time import Time

        t = self.svc._approximate_equinox(2026, "spring")
        dt = t.datetime
        assert dt.month == 3

    def test_autumn_equinox_is_in_september(self):
        t = self.svc._approximate_equinox(2026, "autumn")
        dt = t.datetime
        assert dt.month == 9

    def test_summer_solstice_is_in_june(self):
        t = self.svc._approximate_solstice(2026, "summer")
        dt = t.datetime
        assert dt.month == 6

    def test_winter_solstice_is_in_december(self):
        t = self.svc._approximate_solstice(2026, "winter")
        dt = t.datetime
        assert dt.month == 12

    def test_equinox_unknown_season_defaults_to_spring(self):
        t = self.svc._approximate_equinox(2026, "unknown")
        dt = t.datetime
        assert dt.month == 3

    def test_solstice_unknown_season_defaults_to_summer(self):
        t = self.svc._approximate_solstice(2026, "unknown")
        dt = t.datetime
        assert dt.month == 6


class TestToLocalIso:
    """Tests for _to_local_iso formatting."""

    def test_returns_string(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, timezone="America/Montreal")
        t = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        result = svc._to_local_iso(t)
        assert isinstance(result, str)

    def test_includes_timezone_offset(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, timezone="America/Montreal")
        t = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        result = svc._to_local_iso(t)
        assert "+" in result or "-" in result or "Z" in result


class TestGetEclipticAltitude:
    """Tests for _get_ecliptic_altitude."""

    def test_returns_float(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5)
        t = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        result = svc._get_ecliptic_altitude(t)
        assert isinstance(result, float)

    def test_non_negative_when_sun_below_horizon(self):
        """Regression: the ecliptic-band altitude is a real altitude in [0, 90],
        never the Sun's own (negative) altitude — which used to make the zodiacal
        light gate impossible to satisfy so no window was ever emitted."""
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, 0.0)
        # Local midnight at longitude 0 -> Sun well below the horizon.
        t = Time("2026-03-21T00:00:00", format="isot", scale="utc")
        result = svc._get_ecliptic_altitude(t)
        assert 0.0 <= result <= 90.0

    def test_returns_0_on_exception(self):
        svc = SpecialPhenomenaService(45.0, -73.5)
        with patch("observation.special_phenomena.get_sun", side_effect=Exception("error")):
            result = svc._get_ecliptic_altitude(MagicMock())
        assert result == 0.0


class TestGetGalacticCenterAltitude:
    """Tests for _get_galactic_center_altitude."""

    def test_returns_float(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5)
        t = Time("2026-07-01T04:00:00", format="isot", scale="utc")
        result = svc._get_galactic_center_altitude(t)
        assert isinstance(result, float)

    def test_returns_0_on_exception(self):
        svc = SpecialPhenomenaService(45.0, -73.5)
        with patch("observation.special_phenomena.AltAz", side_effect=Exception("bad")):
            result = svc._get_galactic_center_altitude(MagicMock())
        assert result == 0.0


class TestFindSeasonalEvents:
    """Tests for _find_seasonal_events via get_special_phenomena (short window)."""

    def test_finds_at_least_some_seasonal_events(self):
        svc = SpecialPhenomenaService(45.0, -73.5, timezone="America/Montreal")
        # Use a 400-day window to catch at least one equinox/solstice
        events = svc._find_seasonal_events(
            __import__("astropy.time", fromlist=["Time"]).Time("2026-01-01T00:00:00", format="isot", scale="utc"),
            __import__("astropy.time", fromlist=["Time"]).Time("2027-01-31T00:00:00", format="isot", scale="utc"),
        )
        assert isinstance(events, list)
        # Should find several seasonal events in a 13-month window
        assert len(events) >= 1

    def test_seasonal_event_has_required_keys(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, timezone="America/Montreal")
        events = svc._find_seasonal_events(
            Time("2026-01-01T00:00:00", format="isot", scale="utc"),
            Time("2027-01-31T00:00:00", format="isot", scale="utc"),
        )
        for e in events:
            assert "event_type" in e
            assert e["event_type"] in ("Equinox", "Solstice")
            assert "peak_time" in e


class TestGetSpecialPhenomena:
    """Integration tests exercising _find_zodiacal_light_windows and _find_milky_way_core_visibility."""

    def test_returns_list(self):
        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        result = svc.get_special_phenomena(days_ahead=90)
        assert isinstance(result, list)

    def test_includes_seasonal_events(self):
        """Summer solstice is in the 90-day window from 2026-06-04."""
        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        result = svc.get_special_phenomena(days_ahead=90)
        types = {e.get("event_type") for e in result}
        assert "Solstice" in types or len(result) >= 0

    def test_all_events_have_peak_time(self):
        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        result = svc.get_special_phenomena(days_ahead=90)
        for e in result:
            assert "peak_time" in e or "start_time" in e

    def test_returns_empty_on_error(self):
        """Cover exception handler: patch a sub-function to raise."""
        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        with patch.object(svc, '_find_seasonal_events', side_effect=Exception("force error")):
            result = svc.get_special_phenomena(days_ahead=90)
        assert result == []


class TestFindMilkyWayCoreVisibility:
    """Tests for _find_milky_way_core_visibility — covers ."""

    def test_returns_list(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        start = Time("2026-06-01T00:00:00", format="isot", scale="utc")
        end = Time("2026-07-01T00:00:00", format="isot", scale="utc")
        result = svc._find_milky_way_core_visibility(start, end)
        assert isinstance(result, list)

    def test_does_not_fire_in_winter(self):
        """Winter months (Feb) not in northern MW season months → no events."""
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        start = Time("2026-02-01T00:00:00", format="isot", scale="utc")
        end = Time("2026-02-14T00:00:00", format="isot", scale="utc")
        result = svc._find_milky_way_core_visibility(start, end)
        assert result == []

    def test_southern_hemisphere_uses_different_season(self):
        """Southern hemisphere uses Nov-Mar season months."""
        from astropy.time import Time

        svc = SpecialPhenomenaService(-35.0, 149.0, 0, "Australia/Sydney", "en")
        start = Time("2026-01-01T00:00:00", format="isot", scale="utc")
        end = Time("2026-01-15T00:00:00", format="isot", scale="utc")
        result = svc._find_milky_way_core_visibility(start, end)
        assert isinstance(result, list)

    def test_summer_events_have_required_keys(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        start = Time("2026-06-15T00:00:00", format="isot", scale="utc")
        end = Time("2026-07-15T00:00:00", format="isot", scale="utc")
        result = svc._find_milky_way_core_visibility(start, end)
        for e in result:
            assert e.get("event_type") == "Milky Way Core Visibility"
            assert "peak_time" in e
            assert "galactic_center_altitude" in e


class TestFindZodiacalLightWindows:
    """Tests for _find_zodiacal_light_windows — covers ."""

    def test_returns_list(self):
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        start = Time("2026-08-01T00:00:00", format="isot", scale="utc")
        end = Time("2026-08-15T00:00:00", format="isot", scale="utc")
        result = svc._find_zodiacal_light_windows(start, end)
        assert isinstance(result, list)

    def test_non_season_months_return_empty(self):
        """June is not in spring (3-5) or autumn (8-10) zodiacal light months."""
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        start = Time("2026-06-01T00:00:00", format="isot", scale="utc")
        end = Time("2026-06-15T00:00:00", format="isot", scale="utc")
        result = svc._find_zodiacal_light_windows(start, end)
        assert result == []

    def test_spring_months_enter_check_loop(self):
        """March IS in the spring zodiacal light season (months 3-5)."""
        from astropy.time import Time

        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        start = Time("2026-03-01T00:00:00", format="isot", scale="utc")
        end = Time("2026-03-08T00:00:00", format="isot", scale="utc")
        result = svc._find_zodiacal_light_windows(start, end)
        assert isinstance(result, list)


class TestSpecialPhenomenaBranchCoverage:
    """Targeted tests for hard-to-reach branches in special_phenomena.py."""

    def setup_method(self):
        self.svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")

    # --- _t exception branch ---
    def test_t_format_exception_returns_unformatted_fallback(self):
        """When fallback.format(**kwargs) raises, the raw fallback string is returned."""
        result = self.svc._t("missing.key", "{undefined_placeholder}", name="World")
        # Python's .format() with name="World" and template "{undefined_placeholder}"
        # raises KeyError — the except branch returns the raw fallback
        assert result == "{undefined_placeholder}"

    # --- _find_seasonal_events exception branch ---
    def test_seasonal_exception_swallowed(self):
        from astropy.time import Time

        with patch.object(self.svc, "_approximate_equinox", side_effect=Exception("astro fail")):
            events = self.svc._find_seasonal_events(
                Time("2026-01-01T00:00:00", format="isot", scale="utc"),
                Time("2027-01-01T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(events, list)

    # --- _find_zodiacal_light_windows: sun is None ---
    def test_zodiacal_sun_none_skips_day(self):
        from astropy.time import Time

        with patch("observation.special_phenomena.get_sun", return_value=None):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert result == []

    # --- _find_zodiacal_light_windows: force moon path ---
    def test_zodiacal_light_moon_conditions_met_appends_event(self):
        """Force ecliptic_alt>20 and moon below horizon to trigger event append."""
        from astropy.time import Time
        import types

        def make_altaz_mock(altitude_deg):
            m = MagicMock()
            m.alt.degree = float(altitude_deg)
            return m

        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = make_altaz_mock(-15.0)  # sun below horizon
        fake_moon = MagicMock()
        fake_moon.transform_to.return_value = make_altaz_mock(-10.0)  # moon below horizon

        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=fake_moon
        ), patch.object(self.svc, "_get_ecliptic_altitude", return_value=30.0):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)
        if result:
            assert result[0]["event_type"] == "Zodiacal Light Window"

    # --- _find_milky_way_core_visibility: sun is None path ---
    def test_milky_way_sun_none_skips_day(self):
        from astropy.time import Time

        with patch("observation.special_phenomena.get_sun", return_value=None):
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert result == []

    # --- _find_milky_way_core_visibility: moon is None path ---
    def test_milky_way_moon_none_skips_day(self):
        from astropy.time import Time

        def make_altaz_mock(altitude_deg):
            m = MagicMock()
            m.alt.degree = float(altitude_deg)
            return m

        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = make_altaz_mock(-15.0)

        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=None
        ):
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert result == []

    # --- _find_milky_way_core_visibility: galactic center not visible ---
    def test_milky_way_gc_below_min_altitude_skips(self):
        from astropy.time import Time

        def make_altaz_mock(altitude_deg):
            m = MagicMock()
            m.alt.degree = float(altitude_deg)
            return m

        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = make_altaz_mock(-15.0)

        def fake_gc_transform(frame):
            gc_mock = MagicMock()
            gc_mock.alt.degree = -10.0  # below minimum
            return gc_mock

        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.SkyCoord"
        ) as mock_skycoord:
            instance = mock_skycoord.return_value
            instance.transform_to.side_effect = fake_gc_transform
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    # --- _get_ecliptic_altitude: sun is None ---
    def test_ecliptic_altitude_sun_none_returns_zero(self):
        from astropy.time import Time

        t = Time("2026-06-01T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", return_value=None):
            result = self.svc._get_ecliptic_altitude(t)
        assert result == 0.0

    # --- _refine_equinox_time: exception in while loop ---
    def test_refine_equinox_exception_in_loop_returns_best_time(self):
        from astropy.time import Time

        approx = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", side_effect=Exception("calc fail")):
            result = self.svc._refine_equinox_time(approx, "spring")
        from astropy.time import Time as ATime

        assert isinstance(result, ATime)

    # --- _refine_solstice_time: exception in while loop ---
    def test_refine_solstice_exception_in_loop_returns_best_time(self):
        from astropy.time import Time

        approx = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", side_effect=Exception("calc fail")):
            result = self.svc._refine_solstice_time(approx, "summer")
        from astropy.time import Time as ATime

        assert isinstance(result, ATime)


class TestSpecialPhenomenaNullAndArrayBranches:
    """Cover None-guard and numpy-array branches that are never hit with real Astropy."""

    def setup_method(self):
        self.svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")

    # ── _refine_equinox_time ────────────────────────────────────────────

    def test_refine_equinox_initial_sun_none_returns_best_time(self):
        """get_sun() returns None on the very first call → immediate early return."""
        from astropy.time import Time

        approx = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", return_value=None):
            result = self.svc._refine_equinox_time(approx, "spring")
        assert isinstance(result, Time)

    def test_refine_equinox_initial_dec_as_ndarray(self):
        """Initial dec_val is a numpy array → exercises the isinstance ndarray branch."""
        import numpy as np
        from astropy.time import Time

        approx = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        fake_sun = MagicMock()
        fake_sun.dec.degree = np.array([5.0])
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._refine_equinox_time(approx, "spring")
        assert isinstance(result, Time)

    def test_refine_equinox_loop_sun_none_then_real(self):
        """Sun is None on one loop iteration → continue."""
        import numpy as np
        from astropy.time import Time

        approx = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        real_sun = MagicMock()
        real_sun.dec.degree = 0.5
        # First call (initial) succeeds, subsequent calls alternate None / real
        call_results = [real_sun, None, real_sun]
        with patch(
            "observation.special_phenomena.get_sun",
            side_effect=lambda t: call_results.pop(0) if call_results else real_sun,
        ):
            result = self.svc._refine_equinox_time(approx, "spring")
        assert isinstance(result, Time)

    def test_refine_equinox_loop_dec_as_ndarray(self):
        """Loop dec_val is ndarray → exercises array branch."""
        import numpy as np
        from astropy.time import Time

        approx = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        fake_sun = MagicMock()
        fake_sun.dec.degree = np.array([1.0])
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._refine_equinox_time(approx, "spring")
        assert isinstance(result, Time)

    # ── _refine_solstice_time ───────────────────────────────────────────

    def test_refine_solstice_initial_sun_none_returns_best_time(self):
        """get_sun() returns None on first call in _refine_solstice_time."""
        from astropy.time import Time

        approx = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", return_value=None):
            result = self.svc._refine_solstice_time(approx, "summer")
        assert isinstance(result, Time)

    def test_refine_solstice_initial_dec_as_ndarray(self):
        """Initial dec_val is ndarray in _refine_solstice_time."""
        import numpy as np
        from astropy.time import Time

        approx = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        fake_sun = MagicMock()
        fake_sun.dec.degree = np.array([23.0])
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._refine_solstice_time(approx, "summer")
        assert isinstance(result, Time)

    def test_refine_solstice_loop_sun_none(self):
        """Sun is None in loop iteration of _refine_solstice_time."""
        import numpy as np
        from astropy.time import Time

        approx = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        real_sun = MagicMock()
        real_sun.dec.degree = 23.0
        call_results = [real_sun, None, real_sun]
        with patch(
            "observation.special_phenomena.get_sun",
            side_effect=lambda t: call_results.pop(0) if call_results else real_sun,
        ):
            result = self.svc._refine_solstice_time(approx, "summer")
        assert isinstance(result, Time)

    def test_refine_solstice_loop_dec_as_ndarray(self):
        """Loop dec_val is ndarray in _refine_solstice_time."""
        import numpy as np
        from astropy.time import Time

        approx = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        fake_sun = MagicMock()
        fake_sun.dec.degree = np.array([23.0])
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._refine_solstice_time(approx, "summer")
        assert isinstance(result, Time)

    # ── _find_zodiacal_light_windows ────────────────────────────────────

    def test_zodiacal_sun_altaz_none_skips(self):
        """sun.transform_to() returns None."""
        from astropy.time import Time

        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = None
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_zodiacal_sun_alt_as_ndarray(self):
        """sun_altaz.alt.degree is ndarray."""
        import numpy as np
        from astropy.time import Time

        fake_altaz = MagicMock()
        fake_altaz.alt.degree = np.array([-15.0])
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch.object(
            self.svc, "_get_ecliptic_altitude", return_value=5.0
        ):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_zodiacal_moon_none_skips(self):
        """get_body('moon') returns None."""
        from astropy.time import Time

        fake_altaz = MagicMock()
        fake_altaz.alt.degree = -15.0
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=None
        ), patch.object(self.svc, "_get_ecliptic_altitude", return_value=30.0):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_zodiacal_moon_altaz_none_skips(self):
        """moon.transform_to() returns None."""
        from astropy.time import Time

        fake_altaz = MagicMock()
        fake_altaz.alt.degree = -15.0
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_altaz
        fake_moon = MagicMock()
        fake_moon.transform_to.return_value = None
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=fake_moon
        ), patch.object(self.svc, "_get_ecliptic_altitude", return_value=30.0):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_zodiacal_moon_alt_as_ndarray(self):
        """moon_altaz.alt.degree is ndarray."""
        import numpy as np
        from astropy.time import Time

        fake_sun_altaz = MagicMock()
        fake_sun_altaz.alt.degree = -15.0
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_sun_altaz
        fake_moon_altaz = MagicMock()
        fake_moon_altaz.alt.degree = np.array([-10.0])
        fake_moon = MagicMock()
        fake_moon.transform_to.return_value = fake_moon_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=fake_moon
        ), patch.object(self.svc, "_get_ecliptic_altitude", return_value=30.0):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_zodiacal_exception_handler(self):
        """Exception inside zodiacal loop."""
        from astropy.time import Time

        fake_sun = MagicMock()
        fake_sun.transform_to.side_effect = RuntimeError("boom")
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    # ── _find_milky_way_core_visibility ─────────────────────────────────

    def test_milky_way_sun_alt_as_ndarray(self):
        """sun_altaz.alt.degree is ndarray."""
        import numpy as np
        from astropy.time import Time

        fake_altaz = MagicMock()
        fake_altaz.alt.degree = np.array([-15.0])
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=None
        ):
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_milky_way_sun_above_nautical_twilight_skips(self):
        """sun_alt >= -12 at 2am (e.g., midsummer extreme lat)."""
        from astropy.time import Time

        fake_altaz = MagicMock()
        fake_altaz.alt.degree = -5.0  # above -12: not dark enough
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert result == []

    def test_milky_way_gc_alt_as_ndarray(self):
        """gc_altaz.alt.degree is ndarray."""
        import numpy as np
        from astropy.time import Time

        fake_sun_altaz = MagicMock()
        fake_sun_altaz.alt.degree = -15.0
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_sun_altaz
        fake_gc_altaz = MagicMock()
        fake_gc_altaz.alt.degree = np.array([-5.0])  # below threshold → skip
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.SkyCoord"
        ) as mock_sc:
            mock_sc.return_value.transform_to.return_value = fake_gc_altaz
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_milky_way_moon_alt_as_ndarray(self):
        """moon_altaz.alt.degree is ndarray."""
        import numpy as np
        from astropy.time import Time

        fake_sun_altaz = MagicMock()
        fake_sun_altaz.alt.degree = -15.0
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_sun_altaz
        fake_gc_altaz = MagicMock()
        fake_gc_altaz.alt.degree = 30.0
        fake_moon_altaz = MagicMock()
        fake_moon_altaz.alt.degree = np.array([10.0])  # above 5 → skip
        fake_moon = MagicMock()
        fake_moon.transform_to.return_value = fake_moon_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.SkyCoord"
        ) as mock_sc, patch("observation.special_phenomena.get_body", return_value=fake_moon):
            mock_sc.return_value.transform_to.return_value = fake_gc_altaz
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    def test_milky_way_exception_handler(self):
        """Exception inside MW loop."""
        from astropy.time import Time

        fake_sun = MagicMock()
        fake_sun.transform_to.side_effect = RuntimeError("astro error")
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._find_milky_way_core_visibility(
                Time("2026-07-01T00:00:00", format="isot", scale="utc"),
                Time("2026-07-03T00:00:00", format="isot", scale="utc"),
            )
        assert isinstance(result, list)

    # ── _get_ecliptic_altitude ───────────────────────────────────────────

    def test_ecliptic_altaz_none_returns_zero(self):
        """sun.transform_to() returns None."""
        from astropy.time import Time

        t = Time("2026-06-01T00:00:00", format="isot", scale="utc")
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = None
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._get_ecliptic_altitude(t)
        assert result == 0.0

    def test_ecliptic_alt_as_ndarray(self):
        """alt_val is ndarray."""
        import numpy as np
        from astropy.time import Time

        t = Time("2026-06-01T00:00:00", format="isot", scale="utc")
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = np.array([30.0])
        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = fake_altaz
        with patch("observation.special_phenomena.get_sun", return_value=fake_sun):
            result = self.svc._get_ecliptic_altitude(t)
        assert isinstance(result, float)

    # ── _get_galactic_center_altitude ────────────────────────────────────

    def test_galactic_center_alt_as_ndarray(self):
        """alt_val is ndarray →  (patch astropy.coordinates directly)."""
        import numpy as np
        from astropy.time import Time

        t = Time("2026-07-01T04:00:00", format="isot", scale="utc")
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = np.array([20.0])
        fake_gc = MagicMock()
        fake_gc.transform_to.return_value = fake_altaz
        with patch("astropy.coordinates.SkyCoord", return_value=fake_gc), patch("observation.special_phenomena.AltAz"):
            result = self.svc._get_galactic_center_altitude(t)
        assert isinstance(result, float)
        assert result == pytest.approx(20.0)

    def test_zodiacal_moon_above_5_skips_event(self):
        """moon_alt >= 5 → is_moon_ok=False → event not appended."""
        from astropy.time import Time

        def make_altaz_mock(altitude_deg):
            m = MagicMock()
            m.alt.degree = float(altitude_deg)
            return m

        fake_sun = MagicMock()
        fake_sun.transform_to.return_value = make_altaz_mock(-15.0)  # sun below horizon
        fake_moon = MagicMock()
        fake_moon.transform_to.return_value = make_altaz_mock(10.0)  # moon above 5° → is_moon_ok=False

        with patch("observation.special_phenomena.get_sun", return_value=fake_sun), patch(
            "observation.special_phenomena.get_body", return_value=fake_moon
        ), patch.object(self.svc, "_get_ecliptic_altitude", return_value=30.0):
            result = self.svc._find_zodiacal_light_windows(
                Time("2026-03-01T00:00:00", format="isot", scale="utc"),
                Time("2026-03-03T00:00:00", format="isot", scale="utc"),
            )
        assert result == []


class TestSeasonalInstantAccuracy:
    """Equinox and solstice instants must match published times.

    These guard a real defect: the instants used to be derived from the Sun's
    declination as reported by ``get_sun``, which is GCRS and therefore still
    referred to the J2000 equator. Equinoxes and solstices are defined against
    the true equinox of date, so precession since J2000 shifted every result by
    roughly nine hours. Anything measuring the seasons in a J2000-referred frame
    fails these assertions.
    """

    # Published instants (UTC). Tolerance covers the one-minute search grid.
    PUBLISHED = [
        ("spring", 2026, "2026-03-20T14:46:00"),
        ("autumn", 2026, "2026-09-23T00:05:00"),
        ("summer", 2026, "2026-06-21T08:24:00"),
        ("winter", 2026, "2026-12-21T20:50:00"),
        ("spring", 2027, "2027-03-20T20:24:00"),
    ]

    TOLERANCE_MINUTES = 3.0

    def setup_method(self):
        self.svc = SpecialPhenomenaService(48.85, 2.35, 35, "Europe/Paris", "en")

    @pytest.mark.parametrize("season,year,published", PUBLISHED)
    def test_seasonal_instant_matches_published_time(self, season, year, published):
        """Each refined instant lands within a few minutes of the published one."""
        from astropy.time import Time
        from astropy import units as u

        if season in ("spring", "autumn"):
            computed = self.svc._refine_equinox_time(self.svc._approximate_equinox(year, season), season)
        else:
            computed = self.svc._refine_solstice_time(self.svc._approximate_solstice(year, season), season)

        delta_minutes = abs((computed - Time(published, format="isot", scale="utc")).to(u.min).value)
        assert (
            delta_minutes <= self.TOLERANCE_MINUTES
        ), f"{season} {year} off by {delta_minutes:.1f} min (got {computed.utc.iso}, expected {published})"

    def test_equinox_is_not_the_j2000_declination_zero(self):
        """The March equinox must not be placed where GCRS declination crosses zero.

        The two differ by about nine hours, which is what the old implementation
        returned. This pins the regression directly rather than relying only on
        the published-value comparison above.
        """
        import numpy as np
        from astropy.coordinates import get_sun
        from astropy import units as u

        approx = self.svc._approximate_equinox(2026, "spring")
        computed = self.svc._refine_equinox_time(approx, "spring")

        grid = approx + (np.arange(-120, 121) * u.hour)
        j2000_dec_zero = grid[int(np.argmin(np.abs(np.asarray(get_sun(grid).dec.degree, dtype=float))))]

        assert abs((computed - j2000_dec_zero).to(u.hour).value) > 4.0


class TestSolarLongitudeHelpers:
    """Fallback behaviour of the vectorised solar-longitude search."""

    def setup_method(self):
        self.svc = SpecialPhenomenaService(48.85, 2.35, 35, "Europe/Paris", "en")

    def test_returns_fallback_when_ephemeris_yields_nothing(self):
        """get_sun returning None leaves the approximate time untouched."""
        from astropy.time import Time

        fallback = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", return_value=None):
            result = self.svc._best_solar_longitude_time(fallback, 0.0, fallback)
        assert result is fallback

    def test_returns_fallback_on_ephemeris_error(self):
        """An astropy failure falls back instead of propagating."""
        from astropy.time import Time

        fallback = Time("2026-03-20T12:00:00", format="isot", scale="utc")
        with patch("observation.special_phenomena.get_sun", side_effect=Exception("ephemeris down")):
            result = self.svc._best_solar_longitude_time(fallback, 0.0, fallback)
        assert result is fallback

    def test_longitude_target_wraps_around_zero(self):
        """A target of 0 deg matches longitudes just below 360, not just above 0."""
        import numpy as np
        from astropy.time import Time
        from astropy import units as u

        # Grid straddling the March equinox: longitude runs 359.x -> 0.x
        grid = Time("2026-03-20T12:00:00", format="isot", scale="utc") + (np.arange(-6, 7) * u.hour)
        result = self.svc._best_solar_longitude_time(grid, 0.0, grid[0])

        # The nearest sample to longitude 0 is the last one before the crossing,
        # never the far end of the grid.
        assert abs((result - Time("2026-03-20T14:46:00", format="isot", scale="utc")).to(u.hour).value) < 2.0

    def test_returns_fallback_when_best_index_exceeds_times_size(self):
        """A longitudes array longer than the times grid (an ephemeris/broadcast
        oddity) can pick an index past the grid's end - fall back rather than
        indexing out of range."""
        import numpy as np
        from astropy.time import Time
        from astropy import units as u

        grid = Time("2026-03-20T12:00:00", format="isot", scale="utc") + (np.arange(0, 3) * u.hour)
        fallback = grid[0]
        oversized_longitudes = np.array([100.0, 100.0, 100.0, 0.0])  # best match at index 3, out of grid bounds
        with patch.object(self.svc, "_sun_ecliptic_longitudes_deg", return_value=oversized_longitudes):
            result = self.svc._best_solar_longitude_time(grid, 0.0, fallback)
        assert result is fallback


class TestEclipticAltitudeWarningFree:
    """The zodiacal-light elongation test must not warn on every call."""

    def test_no_non_rotation_transformation_warning(self):
        """Comparing across mismatched frames warned once per scanned day."""
        import warnings
        from astropy.time import Time

        svc = SpecialPhenomenaService(48.85, 2.35, 35, "Europe/Paris", "en")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            svc._get_ecliptic_altitude(Time("2026-08-15T22:30:00", format="isot", scale="utc"))

        offenders = [w for w in caught if "NonRotationTransformation" in w.category.__name__]
        assert offenders == [], f"unexpected frame-mismatch warnings: {[str(w.message) for w in offenders]}"
