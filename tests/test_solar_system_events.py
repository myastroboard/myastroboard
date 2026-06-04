"""
Tests for solar_system_events.py (SolarSystemEventsService).
Covers pure-logic rating methods, constants, and mocked event finders.
"""

import pytest
from unittest.mock import patch, MagicMock
from solar_system_events import SolarSystemEventsService


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
