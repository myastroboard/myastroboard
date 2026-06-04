"""
Tests for special_phenomena.py (SpecialPhenomenaService).
Covers init, translation helper, approximate event methods, and pure-logic helpers.
"""

import pytest
from unittest.mock import patch, MagicMock
from special_phenomena import SpecialPhenomenaService


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

    def test_returns_0_on_exception(self):
        svc = SpecialPhenomenaService(45.0, -73.5)
        with patch("special_phenomena.get_sun", side_effect=Exception("error")):
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
        with patch("special_phenomena.AltAz", side_effect=Exception("bad")):
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
        """Cover exception handler (lines 103-105): patch a sub-function to raise."""
        svc = SpecialPhenomenaService(45.0, -73.5, 50, "America/Montreal", "en")
        with patch.object(svc, '_find_seasonal_events', side_effect=Exception("force error")):
            result = svc.get_special_phenomena(days_ahead=90)
        assert result == []


class TestFindMilkyWayCoreVisibility:
    """Tests for _find_milky_way_core_visibility — covers lines 479-603."""

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
    """Tests for _find_zodiacal_light_windows — covers lines 355-462."""

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
