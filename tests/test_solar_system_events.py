"""
Tests for solar_system_events.py (SolarSystemEventsService).
Covers pure-logic rating methods, constants, and mocked event finders.
"""

from unittest.mock import patch
from observation import solar_system_events as module

SolarSystemEventsService = module.SolarSystemEventsService


class TestSolarSystemEventsInit:
    """Tests for SolarSystemEventsService initialization."""

    def test_northern_hemisphere_detection(self):
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        assert svc.hemisphere == "Northern"

    def test_southern_hemisphere_detection(self):
        svc = SolarSystemEventsService(-33.9, 151.2, timezone="Australia/Sydney")
        assert svc.hemisphere == "Southern"

    def test_equator_is_northern(self):
        svc = SolarSystemEventsService(0.0, 0.0)
        assert svc.hemisphere == "Northern"

    def test_location_object_created(self):
        svc = SolarSystemEventsService(45.0, -73.5)
        assert svc.location is not None


class TestMeteorShowerConstants:
    """Tests for METEOR_SHOWERS class attribute."""

    def test_meteor_showers_not_empty(self):
        assert len(SolarSystemEventsService.METEOR_SHOWERS) > 0

    def test_perseids_present(self):
        assert "Perseids" in SolarSystemEventsService.METEOR_SHOWERS

    def test_geminids_present(self):
        assert "Geminids" in SolarSystemEventsService.METEOR_SHOWERS

    def test_each_shower_has_required_keys(self):
        required = {"peak_month", "peak_day_start", "peak_day_end",
                    "radiant_ra", "radiant_dec", "zenith_hourly_rate",
                    "parent_body", "hemisphere"}
        for name, data in SolarSystemEventsService.METEOR_SHOWERS.items():
            for key in required:
                assert key in data, f"Shower {name} missing key {key}"


class TestRateMeteorShowerImportance:
    """Tests for _rate_meteor_shower_importance."""

    def setup_method(self):
        self.svc = SolarSystemEventsService(45.0, -73.5)

    def test_zhr_50_plus_is_high(self):
        assert self.svc._rate_meteor_shower_importance(50) == "high"
        assert self.svc._rate_meteor_shower_importance(100) == "high"

    def test_zhr_20_to_49_is_medium(self):
        assert self.svc._rate_meteor_shower_importance(20) == "medium"
        assert self.svc._rate_meteor_shower_importance(40) == "medium"

    def test_zhr_below_20_is_low(self):
        assert self.svc._rate_meteor_shower_importance(10) == "low"
        assert self.svc._rate_meteor_shower_importance(1) == "low"


class TestRateCometImportance:
    """Tests for _rate_comet_importance."""

    def setup_method(self):
        self.svc = SolarSystemEventsService(45.0, -73.5)

    def test_magnitude_le_5_is_high(self):
        assert self.svc._rate_comet_importance(4.0) == "high"
        assert self.svc._rate_comet_importance(5.0) == "high"

    def test_magnitude_6_to_7_is_medium(self):
        assert self.svc._rate_comet_importance(6.0) == "medium"
        assert self.svc._rate_comet_importance(7.0) == "medium"

    def test_magnitude_above_7_is_low(self):
        assert self.svc._rate_comet_importance(8.5) == "low"

    def test_naked_eye_comet_is_high_importance(self):
        assert self.svc._rate_comet_importance(3.0) == "high"


class TestEstimateCometVisibility:
    """Tests for _estimate_comet_visibility."""

    def setup_method(self):
        self.svc = SolarSystemEventsService(45.0, -73.5)

    def test_magnitude_6_or_less_is_visible(self):
        assert self.svc._estimate_comet_visibility(6.0) is True
        assert self.svc._estimate_comet_visibility(3.0) is True

    def test_magnitude_above_6_is_not_naked_eye(self):
        assert self.svc._estimate_comet_visibility(7.0) is False


class TestFindMeteorShowerPeaks:
    """Tests for _find_meteor_shower_peaks with various scenarios."""

    def test_southern_observer_skips_northern_only_showers(self):
        svc = SolarSystemEventsService(-33.9, 151.2, timezone="Australia/Sydney")
        from datetime import date, timedelta
        start_date = date(2026, 1, 1)
        events = svc._find_meteor_shower_peaks(start_date, 365)
        # Events for Southern-only showers should be filtered; Perseids (Northern) excluded
        event_names = [e["raw_data"]["shower"] for e in events]
        assert "Perseids" not in event_names

    def test_both_hemisphere_showers_visible_from_north(self):
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        from datetime import date
        start_date = date(2026, 1, 1)
        events = svc._find_meteor_shower_peaks(start_date, 365)
        event_names = {e["raw_data"]["shower"] for e in events}
        # Perseids (Northern only) should be included from Northern observer
        assert "Perseids" in event_names

    def test_event_has_required_keys(self):
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        from datetime import date
        start_date = date(2026, 1, 1)
        events = svc._find_meteor_shower_peaks(start_date, 365)
        if events:
            e = events[0]
            for key in ("event_type", "title", "peak_time", "zenith_hourly_rate", "raw_data"):
                assert key in e

    def test_score_within_0_to_10(self):
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        from datetime import date
        events = svc._find_meteor_shower_peaks(date(2026, 1, 1), 365)
        for e in events:
            assert 0.0 <= e["score"] <= 10.0


class TestFindCometVisibilityWindows:
    """Tests for _find_comet_visibility_windows."""

    def test_returns_list(self):
        svc = SolarSystemEventsService(45.0, -73.5)
        from datetime import date
        events = svc._find_comet_visibility_windows(date(2026, 1, 1), 365)
        assert isinstance(events, list)

    def test_comet_events_have_required_keys(self):
        svc = SolarSystemEventsService(45.0, -73.5)
        from datetime import date
        events = svc._find_comet_visibility_windows(date(2026, 1, 1), 365)
        for e in events:
            assert "event_type" in e
            assert e["event_type"] == "Comet Appearance"
            assert "magnitude" in e

    def test_no_comet_events_when_date_range_too_early(self):
        """When date range is before any comet perihelion, no events should be returned."""
        svc = SolarSystemEventsService(45.0, -73.5)
        from datetime import date
        # Use a date range long before any known comets
        events = svc._find_comet_visibility_windows(date(2000, 1, 1), 10)
        assert isinstance(events, list)
        # Should find no comets (none have perihelion around 2000-01-01)
        assert len(events) == 0


class TestGetSolarSystemEvents:
    """Tests for the main get_solar_system_events method."""

    def test_returns_sorted_list(self):
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        events = svc.get_solar_system_events(days_ahead=365)
        assert isinstance(events, list)
        # Should be sorted by peak_time or start_time
        times = [e.get("peak_time", e.get("start_time")) for e in events]
        assert times == sorted(times)

    def test_returns_empty_on_exception(self):
        """When an exception occurs internally, returns empty list."""
        svc = SolarSystemEventsService(45.0, -73.5)
        with patch.object(svc, "_find_meteor_shower_peaks", side_effect=Exception("boom")):
            events = svc.get_solar_system_events()
        assert events == []

    def test_contains_event_types(self):
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        events = svc.get_solar_system_events(days_ahead=400)
        event_types = {e["event_type"] for e in events}
        # Should have at least meteor showers or comets
        assert len(event_types) >= 1


class TestFindAsteroidOccultations:
    """Tests for _find_asteroid_occultations."""

    def test_returns_empty_list(self):
        svc = SolarSystemEventsService(45.0, -73.5)
        from datetime import date
        events = svc._find_asteroid_occultations(date(2026, 1, 1), 365)
        assert events == []

    def test_returns_list_type(self):
        svc = SolarSystemEventsService(45.0, -73.5)
        from datetime import date
        events = svc._find_asteroid_occultations(date(2026, 6, 1), 30)
        assert isinstance(events, list)


class TestFindMeteorShowerPeaksEdgeCases:
    """Additional edge cases for _find_meteor_shower_peaks."""

    def test_no_events_when_range_excludes_all_peaks(self):
        """A very narrow date range excluding all peaks returns empty list."""
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        from datetime import date
        # February has no meteor shower peaks in the METEOR_SHOWERS data
        events = svc._find_meteor_shower_peaks(date(2026, 2, 1), 5)
        assert isinstance(events, list)
        assert len(events) == 0

    def test_southern_only_shower_excluded_for_northern_observer(self):
        """A Southern-hemisphere-only shower should be skipped for Northern observer."""
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        orig = svc.METEOR_SHOWERS.copy()
        svc.METEOR_SHOWERS = {
            'TestSouthern': {
                'peak_month': 6,
                'peak_day_start': 1,
                'peak_day_end': 10,
                'radiant_ra': 0,
                'radiant_dec': -60,
                'zenith_hourly_rate': 10,
                'parent_body': 'test',
                'hemisphere': 'Southern',
            }
        }
        from datetime import date
        try:
            events = svc._find_meteor_shower_peaks(date(2026, 1, 1), 365)
            assert len(events) == 0
        finally:
            svc.METEOR_SHOWERS = orig


class TestIsRadiantVisible:
    """Tests for _is_radiant_visible."""

    def test_returns_bool(self):
        from astropy.time import Time
        svc = SolarSystemEventsService(45.0, -73.5)
        t = Time("2026-08-12T02:00:00", format="isot", scale="utc")
        result = svc._is_radiant_visible(48, 58, t)
        assert isinstance(result, bool)

    def test_returns_false_on_exception(self):
        from astropy.time import Time
        svc = SolarSystemEventsService(45.0, -73.5)
        t = Time("2026-08-12T02:00:00", format="isot", scale="utc")
        with patch("observation.solar_system_events.SkyCoord", side_effect=Exception("bad")):
            result = svc._is_radiant_visible(48, 58, t)
        assert result is False

    def test_altaz_none_returns_false(self):
        """if altaz is None → return False."""
        import numpy as np
        from astropy.time import Time
        from astropy.coordinates import SkyCoord

        svc = SolarSystemEventsService(45.0, -73.5)
        t = Time("2026-08-12T02:00:00", format="isot", scale="utc")

        with patch.object(SkyCoord, 'transform_to', return_value=None):
            result = svc._is_radiant_visible(48, 58, t)
        assert result is False

    def test_ndarray_altitude_branch(self):
        """alt_val is ndarray → float(np.real(...)) extraction."""
        import numpy as np
        from astropy.time import Time
        from astropy.coordinates import SkyCoord
        from unittest.mock import MagicMock

        svc = SolarSystemEventsService(45.0, -73.5)
        t = Time("2026-08-12T02:00:00", format="isot", scale="utc")

        def patched_transform(self_coord, frame):
            mock_altaz = MagicMock()
            mock_alt = MagicMock()
            mock_alt.degree = np.array([45.0])  # ndarray → triggers 
            mock_altaz.alt = mock_alt
            return mock_altaz

        with patch.object(SkyCoord, 'transform_to', patched_transform):
            result = svc._is_radiant_visible(48, 58, t)
        assert isinstance(result, bool)


class TestMeteorShowerExceptionHandler:
    """Cover  (exception in meteor shower loop)."""

    def test_exception_in_shower_loop_is_swallowed(self):
        """exception inside the per-shower try block is caught and logged."""
        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        from datetime import date

        # Patch _is_radiant_visible to raise for the first shower processed
        original_is_radiant = svc._is_radiant_visible
        call_count = [0]

        def raising_is_radiant(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated radiant error")
            return original_is_radiant(*args, **kwargs)

        svc._is_radiant_visible = raising_is_radiant
        # Must not raise; exception is swallowed by except block
        events = svc._find_meteor_shower_peaks(date(2026, 8, 1), 365)
        assert isinstance(events, list)


class TestCometExceptionHandler:
    """Cover  (exception in comet visibility loop)."""

    def test_exception_in_comet_loop_is_swallowed(self):
        """exception inside the per-comet try block is caught and logged."""
        from datetime import date

        svc = SolarSystemEventsService(45.0, -73.5)

        # Patch timedelta to raise on first call (inside the comet loop)
        original_timedelta = module.timedelta
        call_count = [0]

        def raising_timedelta(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise ValueError("simulated timedelta error")
            return original_timedelta(*args, **kwargs)

        with patch.object(module, 'timedelta', raising_timedelta):
            events = svc._find_comet_visibility_windows(date(2026, 1, 1), 365)
        assert isinstance(events, list)
