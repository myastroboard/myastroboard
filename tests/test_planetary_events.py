"""
Tests for planetary_events.py (PlanetaryEventsService).
Covers pure-logic rating, constants, and vectorized find_runs helper.
"""

import numpy as np
from planetary_events import PlanetaryEventsService, PLANETS


class TestPlanetaryEventsConstants:
    """Tests for module-level constants."""

    def test_planets_dict_contains_seven_planets(self):
        assert len(PLANETS) == 7

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


class TestPlanetaryHelperMethods:
    """Tests for _angular_separation, _get_elongation, _is_event_visible, _is_planet_visible."""

    def setup_method(self):
        self.svc = PlanetaryEventsService(45.0, -73.5, timezone="America/Montreal")
        from astropy.time import Time
        self.t = Time("2026-06-21T02:00:00", format="isot", scale="utc")

    # --- _angular_separation ---
    def test_angular_separation_returns_float(self):
        result = self.svc._angular_separation("Jupiter", "Saturn", self.t)
        assert isinstance(result, float)

    def test_angular_separation_returns_inf_on_exception(self):
        from unittest.mock import patch
        with patch("planetary_events.get_body", side_effect=Exception("fail")):
            result = self.svc._angular_separation("Jupiter", "Saturn", self.t)
        assert result == float('inf')

    # --- _get_elongation ---
    def test_get_elongation_returns_float(self):
        result = self.svc._get_elongation("Jupiter", self.t)
        assert isinstance(result, float)

    def test_get_elongation_returns_zero_on_exception(self):
        from unittest.mock import patch
        with patch("planetary_events.get_body", side_effect=Exception("fail")):
            result = self.svc._get_elongation("Jupiter", self.t)
        assert result == 0.0

    # --- _is_event_visible ---
    def test_is_event_visible_returns_bool(self):
        result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert isinstance(result, bool)

    def test_is_event_visible_returns_false_on_exception(self):
        from unittest.mock import patch
        with patch("planetary_events.get_body", side_effect=Exception("fail")):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert result is False

    def test_is_event_visible_returns_false_when_planet_is_none(self):
        from unittest.mock import patch
        with patch("planetary_events.get_body", return_value=None):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert result is False

    # --- _is_planet_visible ---
    def test_is_planet_visible_returns_bool(self):
        result = self.svc._is_planet_visible("Jupiter", self.t)
        assert isinstance(result, bool)

    def test_is_planet_visible_returns_false_on_exception(self):
        from unittest.mock import patch
        with patch("planetary_events.get_body", side_effect=Exception("fail")):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert result is False

    def test_is_planet_visible_returns_false_when_none(self):
        from unittest.mock import patch
        with patch("planetary_events.get_body", return_value=None):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert result is False


class TestGetPlanetaryEventsExceptionPath:
    """Test get_planetary_events exception handling."""

    def test_returns_empty_list_on_exception(self):
        svc = PlanetaryEventsService(45.0, -73.5)
        from unittest.mock import patch
        with patch.object(svc, "_find_conjunctions", side_effect=Exception("boom")):
            result = svc.get_planetary_events(days_ahead=30)
        assert result == []

    def test_find_conjunctions_exception_in_loop_swallowed(self):
        """Exception inside conjunction iteration is caught per-planet-pair."""
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import patch, MagicMock
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 12, 31, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 365)
        # Patch separation to raise for all calls
        for body in svc._coords:
            obj = svc._coords[body]
            if hasattr(obj, 'separation'):
                mock = MagicMock()
                mock.separation.side_effect = Exception("sep fail")
                svc._coords[body] = mock
        events = svc._find_conjunctions(now, end)
        assert isinstance(events, list)


class TestPlanetaryFindMethodExceptionHandlers:
    """Cover per-planet exception handlers in _find_oppositions,
    _find_elongations, and _find_retrograde_periods."""

    def _make_svc_with_bad_coords(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import MagicMock
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 12, 31, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 365)
        # Replace every coord with a mock that raises on separation/ra.degree
        bad = MagicMock()
        bad.separation.side_effect = Exception("boom")
        bad.ra.degree = MagicMock(side_effect=Exception("boom"))
        for body in list(svc._coords.keys()):
            svc._coords[body] = bad
        return svc, now, end

    def test_find_oppositions_exception_per_planet_swallowed(self):
        svc, now, end = self._make_svc_with_bad_coords()
        result = svc._find_oppositions(now, end)
        assert isinstance(result, list)

    def test_find_elongations_exception_per_planet_swallowed(self):
        svc, now, end = self._make_svc_with_bad_coords()
        result = svc._find_elongations(now, end)
        assert isinstance(result, list)

    def test_find_retrograde_exception_per_planet_swallowed(self):
        from astropy.time import Time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        svc = PlanetaryEventsService(45.0, -73.5)
        now = Time(datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
        end = Time(datetime(2026, 12, 31, 0, 0, tzinfo=ZoneInfo("UTC")))
        svc._prefetch_coords(now, 365)

        class _BadRa:
            @property
            def degree(self):
                raise Exception("boom ra.degree")

        class _BadCoords:
            ra = _BadRa()

        for body in list(svc._coords.keys()):
            svc._coords[body] = _BadCoords()

        result = svc._find_retrograde_periods(now, end)
        assert isinstance(result, list)


class TestPlanetaryHelperArrayBranches:
    """Cover numpy-array and complex branches in helper methods."""

    def setup_method(self):
        self.svc = PlanetaryEventsService(45.0, -73.5, timezone="America/Montreal")
        from astropy.time import Time
        self.t = Time("2026-06-21T02:00:00", format="isot", scale="utc")

    def test_angular_separation_ndarray_branch(self):
        """sep.degree is ndarray → line 309."""
        from unittest.mock import patch, MagicMock
        fake_sep = MagicMock()
        fake_sep.degree = np.array([5.0])
        fake_body = MagicMock()
        fake_body.separation.return_value = fake_sep
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._angular_separation("Jupiter", "Saturn", self.t)
        assert isinstance(result, float)

    def test_angular_separation_complex_branch(self):
        """sep.degree is complex → line 311."""
        from unittest.mock import patch, MagicMock
        fake_sep = MagicMock()
        fake_sep.degree = complex(5.0, 0.0)
        fake_body = MagicMock()
        fake_body.separation.return_value = fake_sep
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._angular_separation("Jupiter", "Saturn", self.t)
        assert isinstance(result, float)

    def test_get_elongation_ndarray_branch(self):
        """elong_val is ndarray → line 328."""
        from unittest.mock import patch, MagicMock
        fake_elong = MagicMock()
        fake_elong.degree = np.array([45.0])
        fake_body = MagicMock()
        fake_body.separation.return_value = fake_elong
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._get_elongation("Jupiter", self.t)
        assert isinstance(result, float)

    def test_get_elongation_complex_branch(self):
        """elong_val is complex → line 330."""
        from unittest.mock import patch, MagicMock
        fake_elong = MagicMock()
        fake_elong.degree = complex(45.0, 0.0)
        fake_body = MagicMock()
        fake_body.separation.return_value = fake_elong
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._get_elongation("Jupiter", self.t)
        assert isinstance(result, float)

    def test_is_event_visible_altaz_none_returns_false(self):
        """p1.transform_to() returns None → line 350."""
        from unittest.mock import patch, MagicMock
        fake_body = MagicMock()
        fake_body.transform_to.return_value = None
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert result is False

    def test_is_event_visible_alt1_ndarray(self):
        """alt1_val is ndarray → line 357."""
        from unittest.mock import patch, MagicMock
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = np.array([30.0])
        fake_body = MagicMock()
        fake_body.transform_to.return_value = fake_altaz
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert isinstance(result, bool)

    def test_is_event_visible_alt1_complex(self):
        """alt1_val is complex → line 359."""
        from unittest.mock import patch, MagicMock
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = complex(30.0, 0.0)
        fake_body = MagicMock()
        fake_body.transform_to.return_value = fake_altaz
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert isinstance(result, bool)

    def test_is_event_visible_alt2_ndarray(self):
        """alt2_val is ndarray → line 364."""
        from unittest.mock import patch, MagicMock
        fake_altaz1 = MagicMock()
        fake_altaz1.alt.degree = 30.0
        fake_altaz2 = MagicMock()
        fake_altaz2.alt.degree = np.array([25.0])
        calls = [0]
        def transform_side_effect(frame):
            calls[0] += 1
            return fake_altaz1 if calls[0] == 1 else fake_altaz2
        fake_body = MagicMock()
        fake_body.transform_to.side_effect = transform_side_effect
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert isinstance(result, bool)

    def test_is_event_visible_alt2_complex(self):
        """alt2_val is complex → line 366."""
        from unittest.mock import patch, MagicMock
        fake_altaz1 = MagicMock()
        fake_altaz1.alt.degree = 30.0
        fake_altaz2 = MagicMock()
        fake_altaz2.alt.degree = complex(25.0, 0.0)
        calls = [0]
        def transform_side_effect(frame):
            calls[0] += 1
            return fake_altaz1 if calls[0] == 1 else fake_altaz2
        fake_body = MagicMock()
        fake_body.transform_to.side_effect = transform_side_effect
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._is_event_visible("Jupiter", "Saturn", self.t)
        assert isinstance(result, bool)

    def test_is_planet_visible_altaz_none_returns_false(self):
        """altaz is None → line 383."""
        from unittest.mock import patch, MagicMock
        fake_body = MagicMock()
        fake_body.transform_to.return_value = None
        with patch("planetary_events.get_body", return_value=fake_body):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert result is False

    def test_is_planet_visible_sun_obj_none_returns_false(self):
        """sun_obj is None → line 388."""
        from unittest.mock import patch, MagicMock
        fake_planet = MagicMock()
        fake_planet.transform_to.return_value = MagicMock()
        calls = [0]
        def get_body_side(name, *args, **kwargs):
            calls[0] += 1
            if name == 'sun':
                return None
            return fake_planet
        with patch("planetary_events.get_body", side_effect=get_body_side):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert result is False

    def test_is_planet_visible_elong_ndarray(self):
        """elong_val is ndarray → line 393."""
        from unittest.mock import patch, MagicMock
        fake_elong = MagicMock()
        fake_elong.degree = np.array([45.0])
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = 30.0
        fake_planet = MagicMock()
        fake_planet.transform_to.return_value = fake_altaz
        fake_planet.separation.return_value = fake_elong
        fake_sun = MagicMock()
        def get_body_side(name, *args, **kwargs):
            return fake_sun if name == 'sun' else fake_planet
        with patch("planetary_events.get_body", side_effect=get_body_side):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert isinstance(result, bool)

    def test_is_planet_visible_elong_complex(self):
        """elong_val is complex → line 395."""
        from unittest.mock import patch, MagicMock
        fake_elong = MagicMock()
        fake_elong.degree = complex(45.0, 0.0)
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = 30.0
        fake_planet = MagicMock()
        fake_planet.transform_to.return_value = fake_altaz
        fake_planet.separation.return_value = fake_elong
        fake_sun = MagicMock()
        def get_body_side(name, *args, **kwargs):
            return fake_sun if name == 'sun' else fake_planet
        with patch("planetary_events.get_body", side_effect=get_body_side):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert isinstance(result, bool)

    def test_is_planet_visible_alt_ndarray(self):
        """alt_val is ndarray → line 401."""
        from unittest.mock import patch, MagicMock
        fake_elong = MagicMock()
        fake_elong.degree = 45.0
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = np.array([30.0])
        fake_planet = MagicMock()
        fake_planet.transform_to.return_value = fake_altaz
        fake_planet.separation.return_value = fake_elong
        fake_sun = MagicMock()
        def get_body_side(name, *args, **kwargs):
            return fake_sun if name == 'sun' else fake_planet
        with patch("planetary_events.get_body", side_effect=get_body_side):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert isinstance(result, bool)

    def test_is_planet_visible_alt_complex(self):
        """alt_val is complex → line 403."""
        from unittest.mock import patch, MagicMock
        fake_elong = MagicMock()
        fake_elong.degree = 45.0
        fake_altaz = MagicMock()
        fake_altaz.alt.degree = complex(30.0, 0.0)
        fake_planet = MagicMock()
        fake_planet.transform_to.return_value = fake_altaz
        fake_planet.separation.return_value = fake_elong
        fake_sun = MagicMock()
        def get_body_side(name, *args, **kwargs):
            return fake_sun if name == 'sun' else fake_planet
        with patch("planetary_events.get_body", side_effect=get_body_side):
            result = self.svc._is_planet_visible("Jupiter", self.t)
        assert isinstance(result, bool)
