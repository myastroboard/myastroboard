"""
Tests for planetary_events.py (PlanetaryEventsService).
Covers pure-logic rating, constants, and vectorized find_runs helper.
"""

import pytest
import numpy as np
from planetary_events import PlanetaryEventsService, PLANETS, PLANET_SYMBOLS


class TestPlanetaryEventsConstants:
    """Tests for module-level constants."""

    def test_planets_dict_contains_seven_planets(self):
        assert len(PLANETS) == 7

    def test_planet_symbols_has_all_planets(self):
        for planet in PLANETS:
            assert planet in PLANET_SYMBOLS

    def test_outer_planets_have_opposition(self):
        outer = ["Mars", "Jupiter", "Saturn", "Uranus", "Neptune"]
        for planet in outer:
            assert PLANETS[planet]["has_opposition"] is True

    def test_inner_planets_have_no_opposition(self):
        for planet in ["Mercury", "Venus"]:
            assert PLANETS[planet]["has_opposition"] is False


class TestPlanetaryEventsInit:
    """Tests for PlanetaryEventsService initialization."""

    def test_basic_init(self):
        svc = PlanetaryEventsService(45.0, -73.5, 50, "America/Montreal")
        assert svc.latitude == 45.0
        assert svc.longitude == -73.5

    def test_location_object_created(self):
        svc = PlanetaryEventsService(0.0, 0.0)
        assert svc.location is not None


class TestFindRuns:
    """Tests for the static _find_runs helper."""

    def test_single_run(self):
        arr = np.array([False, True, True, True, False])
        runs = PlanetaryEventsService._find_runs(arr)
        assert len(runs) == 1
        start, end = runs[0]
        assert start == 1
        assert end == 4

    def test_multiple_runs(self):
        arr = np.array([True, True, False, True, False])
        runs = PlanetaryEventsService._find_runs(arr)
        assert len(runs) == 2

    def test_no_runs(self):
        arr = np.array([False, False, False])
        runs = PlanetaryEventsService._find_runs(arr)
        assert len(runs) == 0

    def test_all_true(self):
        arr = np.array([True, True, True])
        runs = PlanetaryEventsService._find_runs(arr)
        assert len(runs) == 1

    def test_single_element_true(self):
        arr = np.array([True])
        runs = PlanetaryEventsService._find_runs(arr)
        assert len(runs) == 1


class TestRateImportance:
    """Tests for _rate_importance."""

    def setup_method(self):
        self.svc = PlanetaryEventsService(45.0, -73.5)

    def test_close_major_planet_conjunction_is_high(self):
        result = self.svc._rate_importance("Jupiter", "Saturn", 0.3)
        assert result == "high"

    def test_moderate_separation_is_medium(self):
        result = self.svc._rate_importance("Mercury", "Venus", 1.0)
        assert result == "medium"

    def test_wide_separation_is_low(self):
        result = self.svc._rate_importance("Mercury", "Mars", 3.0)
        assert result == "low"

    def test_close_minor_planets_is_medium(self):
        result = self.svc._rate_importance("Mercury", "Mars", 0.3)
        assert result == "medium"


class TestToLocalIso:
    """Tests for _to_local_iso formatting."""

    def test_returns_string(self):
        from astropy.time import Time
        svc = PlanetaryEventsService(45.0, -73.5, timezone="America/Montreal")
        t = Time("2026-06-21T12:00:00", format="isot", scale="utc")
        result = svc._to_local_iso(t)
        assert isinstance(result, str)


class TestPrefetchCoords:
    """Tests for _prefetch_coords vectorized caching."""

    def test_prefetch_stores_t_arr(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 10)
        assert hasattr(svc, "_t_arr")
        assert len(svc._t_arr) >= 1

    def test_prefetch_stores_all_planet_coords(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 5)
        for planet in list(PLANETS.keys()) + ["sun"]:
            assert planet in svc._coords


class TestFindConjunctionsAndOppositions:
    """Tests for _find_conjunctions and _find_oppositions with real data."""

    def test_find_conjunctions_returns_list(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 12, 31, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 365)
        events = svc._find_conjunctions(now, end)
        assert isinstance(events, list)

    def test_find_conjunctions_returns_empty_without_prefetch(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        # No _prefetch_coords call → _coords and _t_arr are None
        events = svc._find_conjunctions(now, end)
        assert events == []

    def test_find_oppositions_returns_empty_without_prefetch(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        events = svc._find_oppositions(now, end)
        assert events == []

    def test_find_elongations_returns_empty_without_prefetch(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        events = svc._find_elongations(now, end)
        assert events == []

    def test_find_retrograde_returns_empty_without_prefetch(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        events = svc._find_retrograde_periods(now, end)
        assert events == []

    def test_get_planetary_events_returns_list(self):
        """Full integration test with real calculations over 30 days."""
        svc = PlanetaryEventsService(45.0, -73.5)
        events = svc.get_planetary_events(days_ahead=30)
        assert isinstance(events, list)

    def test_find_oppositions_returns_list_with_prefetch(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 12, 31, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 365)
        events = svc._find_oppositions(now, end)
        assert isinstance(events, list)

    def test_find_retrograde_returns_list_with_prefetch(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 12, 31, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 365)
        events = svc._find_retrograde_periods(now, end)
        assert isinstance(events, list)
