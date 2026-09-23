"""
Tests for solar_system_events.py (SolarSystemEventsService).
Covers pure-logic rating methods, constants, and mocked event finders.
"""

import math
from unittest.mock import patch

import pytest

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

    def test_effective_altitude_min_defaults_to_base_constraint(self):
        # Default airmass_constraint=2.0 -> arcsin(0.5) = 30 deg, same as the base default.
        svc = SolarSystemEventsService(45.0, -73.5)
        assert svc.effective_altitude_min == pytest.approx(30.0)

    def test_effective_altitude_min_uses_stricter_airmass_floor(self):
        # airmass_constraint=1.8 -> arcsin(1/1.8) ~= 33.75 deg, stricter than the base 25.
        svc = SolarSystemEventsService(45.0, -73.5, altitude_constraint_min=25.0, airmass_constraint=1.8)
        assert svc.effective_altitude_min == pytest.approx(33.75, abs=0.05)

    def test_effective_altitude_min_uses_stricter_base_constraint(self):
        # A generous airmass_constraint gives a low altitude floor, so the base wins instead.
        svc = SolarSystemEventsService(45.0, -73.5, altitude_constraint_min=40.0, airmass_constraint=5.0)
        assert svc.effective_altitude_min == pytest.approx(40.0)

    def test_effective_altitude_min_skips_airmass_floor_when_below_one(self):
        # airmass_constraint < 1.0 is physically meaningless (airmass is always >= 1), so
        # the airmass-derived floor is skipped entirely and the base constraint alone applies.
        svc = SolarSystemEventsService(45.0, -73.5, altitude_constraint_min=40.0, airmass_constraint=0.5)
        assert svc.effective_altitude_min == pytest.approx(40.0)


class TestMeteorShowerConstants:
    """Tests for METEOR_SHOWERS class attribute."""

    def test_meteor_showers_not_empty(self):
        assert len(SolarSystemEventsService.METEOR_SHOWERS) > 0

    def test_perseids_present(self):
        assert "Perseids" in SolarSystemEventsService.METEOR_SHOWERS

    def test_geminids_present(self):
        assert "Geminids" in SolarSystemEventsService.METEOR_SHOWERS

    def test_each_shower_has_required_keys(self):
        required = {
            "peak_month",
            "peak_day_start",
            "peak_day_end",
            "radiant_ra",
            "radiant_dec",
            "zenith_hourly_rate",
            "parent_body",
            "hemisphere",
        }
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
        from datetime import date

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
        from utils import parse_iso_to_utc

        svc = SolarSystemEventsService(45.0, -73.5, timezone="America/Montreal")
        events = svc.get_solar_system_events(days_ahead=365)
        assert isinstance(events, list)
        # Sorted by absolute instant (correct across a daylight-saving offset change),
        # which need not match the lexicographic order of the local ISO strings.
        instants = [parse_iso_to_utc(e.get("peak_time") or e.get("start_time")) for e in events]
        assert instants == sorted(instants)

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

        # Force the dataset path to be skipped so the curated fallback runs.
        with patch.object(svc, "_dataset_comet_candidates", return_value=[]), patch.object(
            svc, "_build_comet_event", side_effect=ValueError("simulated build error")
        ):
            events = svc._find_comet_visibility_windows(date(2026, 1, 1), 365)
        assert events == []


class TestMeteorShowerYearBoundary:
    """A search window crossing a calendar boundary must surface next-year showers."""

    def test_mid_year_window_includes_next_year_early_shower(self):
        from datetime import date

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        # Window 2026-07-01 .. 2027-07-01 crosses into 2027.
        events = svc._find_meteor_shower_peaks(date(2026, 7, 1), 365)
        # Quadrantids peak in early January, so only the 2027 occurrence is in range.
        quadrantids = [e for e in events if e["raw_data"]["shower"] == "Quadrantids"]
        assert quadrantids, "next-year Quadrantids should appear in a mid-year 365-day window"
        assert any("2027" in e["peak_time"] for e in quadrantids)


class TestMeteorShowerActivityWindow:
    """Meteor showers span their full IMO activity window, not just peak ± 2 days."""

    def test_perseids_window_spans_weeks(self):
        from datetime import date, datetime

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        events = svc._find_meteor_shower_peaks(date(2026, 1, 1), 365)
        perseids = next(e for e in events if e["raw_data"]["shower"] == "Perseids")
        start = datetime.fromisoformat(perseids["start_time"])
        end = datetime.fromisoformat(perseids["end_time"])
        peak = datetime.fromisoformat(perseids["peak_time"])
        assert (end - start).days >= 30  # ~38-day real window, not the old 4-day span
        assert start <= peak <= end

    def test_quadrantids_window_wraps_year_boundary(self):
        from datetime import date, datetime

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        # Quadrantids peak early January 2027 within a mid-2026 + 365-day window.
        events = svc._find_meteor_shower_peaks(date(2026, 7, 1), 365)
        quad = next(e for e in events if e["raw_data"]["shower"] == "Quadrantids")
        start = datetime.fromisoformat(quad["start_time"])
        end = datetime.fromisoformat(quad["end_time"])
        assert start.month == 12  # activity opens the previous December
        assert end.month == 1  # and closes in January
        assert start < end


class TestCometDatasetSource:
    """Comet events come from the live MPC-fed dataset, not a hardcoded year list."""

    def test_uses_dataset_comets_when_available(self, monkeypatch):
        import skytonight.skytonight_targets as targets_mod
        from datetime import date

        fake_dataset = {
            "targets": [
                {
                    "category": "comets",
                    "preferred_name": "C/2026 X1 (Test)",
                    "magnitude": 5.0,
                    "metadata": {"perihelion_date": "2026-08-15"},
                },
                {
                    "category": "comets",
                    "preferred_name": "Faint Comet",
                    "magnitude": 18.0,  # fainter than the notable cutoff -> excluded
                    "metadata": {"perihelion_date": "2026-08-15"},
                },
                {
                    "category": "deep_sky",
                    "preferred_name": "M31",
                    "magnitude": 3.4,
                    "metadata": {},
                },
            ]
        }
        monkeypatch.setattr(targets_mod, "load_targets_dataset", lambda *a, **k: fake_dataset)

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        events = svc._find_comet_visibility_windows(date(2026, 8, 1), 60)

        names = [e["raw_data"]["comet"] for e in events]
        assert "C/2026 X1 (Test)" in names
        assert "Faint Comet" not in names
        assert "M31" not in names
        assert all(e["event_type"] == "Comet Appearance" for e in events)
        assert all(e["raw_data"]["source"] == "dataset" for e in events)

    def test_falls_back_to_curated_when_dataset_empty(self, monkeypatch):
        import skytonight.skytonight_targets as targets_mod
        from datetime import date

        monkeypatch.setattr(targets_mod, "load_targets_dataset", lambda *a, **k: {"targets": []})
        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        events = svc._find_comet_visibility_windows(date(2026, 1, 1), 365)
        assert events  # curated 2026 comets overlap the full-year window
        assert all(e["raw_data"]["source"] == "curated" for e in events)


class TestDatasetCometCandidates:
    """Tests for _dataset_comet_candidates directly."""

    def test_returns_empty_when_dataset_unavailable(self, monkeypatch):
        import skytonight.skytonight_targets as targets_mod

        def _raise(*a, **k):
            raise RuntimeError("dataset not built yet")

        monkeypatch.setattr(targets_mod, "load_targets_dataset", _raise)
        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        assert svc._dataset_comet_candidates() == []

    def test_skips_candidate_with_unparseable_perihelion(self, monkeypatch):
        import skytonight.skytonight_targets as targets_mod

        fake_dataset = {
            "targets": [
                {
                    "category": "comets",
                    "preferred_name": "Bad Date Comet",
                    "magnitude": 5.0,
                    "metadata": {"perihelion_date": "not-a-date"},
                },
            ]
        }
        monkeypatch.setattr(targets_mod, "load_targets_dataset", lambda *a, **k: fake_dataset)
        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        assert svc._dataset_comet_candidates() == []

    def test_carries_target_id_through(self, monkeypatch):
        import skytonight.skytonight_targets as targets_mod

        fake_dataset = {
            "targets": [
                {
                    "target_id": "comet-10ptempel",
                    "category": "comets",
                    "preferred_name": "10P/Tempel",
                    "magnitude": 5.0,
                    "metadata": {"perihelion_date": "2026-08-15"},
                },
            ]
        }
        monkeypatch.setattr(targets_mod, "load_targets_dataset", lambda *a, **k: fake_dataset)
        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        candidates = svc._dataset_comet_candidates()
        assert len(candidates) == 1
        assert candidates[0]["target_id"] == "comet-10ptempel"


class TestCuratedCometCandidates:
    """Tests for _curated_comet_candidates directly."""

    def test_skips_entry_with_invalid_date_fields(self, monkeypatch):
        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        monkeypatch.setattr(
            svc,
            "NOTABLE_COMETS",
            {
                "Bad Comet": {
                    "perihelion_month": 13,  # invalid month -> ValueError
                    "perihelion_day": 1,
                    "perihelion_year": 2026,
                    "magnitude": 8.0,
                    "visibility": "binoculars",
                },
                "Good Comet": {
                    "perihelion_month": 6,
                    "perihelion_day": 1,
                    "perihelion_year": 2026,
                    "magnitude": 8.0,
                    "visibility": "binoculars",
                },
            },
        )
        candidates = svc._curated_comet_candidates()
        assert [c["name"] for c in candidates] == ["Good Comet"]

    def test_skips_entry_missing_required_key(self, monkeypatch):
        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        monkeypatch.setattr(
            svc,
            "NOTABLE_COMETS",
            {"Incomplete Comet": {"perihelion_month": 6, "perihelion_year": 2026}},  # missing perihelion_day
        )
        assert svc._curated_comet_candidates() == []


class TestParsePerihelion:
    """Tests for the static _parse_perihelion helper."""

    def test_none_value_returns_none(self):
        assert SolarSystemEventsService._parse_perihelion(None) is None

    def test_empty_string_returns_none(self):
        assert SolarSystemEventsService._parse_perihelion("") is None

    def test_unparseable_string_returns_none(self):
        assert SolarSystemEventsService._parse_perihelion("not-a-date") is None

    def test_valid_date_string_parses(self):
        result = SolarSystemEventsService._parse_perihelion("2026-08-15")
        assert result is not None
        assert result.year == 2026 and result.month == 8 and result.day == 15


class TestEquipmentLabel:
    """Tests for the static _equipment_label helper."""

    def test_none_magnitude_defaults_to_telescope(self):
        assert SolarSystemEventsService._equipment_label(None) == "telescope"

    def test_bright_magnitude_is_naked_eye(self):
        assert SolarSystemEventsService._equipment_label(3.0) == "naked_eye_possible"

    def test_moderate_magnitude_is_binoculars(self):
        assert SolarSystemEventsService._equipment_label(8.0) == "binoculars"

    def test_faint_magnitude_is_telescope(self):
        assert SolarSystemEventsService._equipment_label(15.0) == "telescope"


_FULL_ELEMENTS_METADATA = {
    'q': 1.417738,
    'e': 0.537452,
    'omega': 117.7975,
    'Omega': 195.4681,
    'inclination': 12.0272,
    'perihelion_year': 2026,
    'perihelion_month': 8,
    'perihelion_day': 2.1151,
    'slope': 10.0,
}


class TestExtractOrbitalElements:
    """Tests for the static _extract_orbital_elements helper."""

    def test_full_metadata_returns_all_elements(self):
        elements = SolarSystemEventsService._extract_orbital_elements(_FULL_ELEMENTS_METADATA)
        assert elements is not None
        assert elements['q'] == pytest.approx(1.417738)
        assert elements['perihelion_year'] == 2026
        assert elements['perihelion_month'] == 8
        assert elements['perihelion_day'] == pytest.approx(2.1151)
        assert elements['slope'] == pytest.approx(10.0)

    def test_missing_key_returns_none(self):
        incomplete = {k: v for k, v in _FULL_ELEMENTS_METADATA.items() if k != 'slope'}
        assert SolarSystemEventsService._extract_orbital_elements(incomplete) is None

    def test_unparseable_value_returns_none(self):
        bad = dict(_FULL_ELEMENTS_METADATA, q='not-a-number')
        assert SolarSystemEventsService._extract_orbital_elements(bad) is None

    def test_curated_style_metadata_returns_none(self):
        # Curated fallback comets only carry name/magnitude/perihelion_date.
        assert SolarSystemEventsService._extract_orbital_elements({'perihelion_date': '2026-08-15'}) is None


class TestApparentMagnitude:
    """Tests for the static _apparent_magnitude helper."""

    def test_returns_none_for_non_positive_r_au(self):
        assert SolarSystemEventsService._apparent_magnitude(5.0, 10.0, 0.0, 0.5) is None

    def test_returns_none_for_non_positive_delta_au(self):
        assert SolarSystemEventsService._apparent_magnitude(5.0, 10.0, 1.4, 0.0) is None

    def test_computes_brightness_law(self):
        result = SolarSystemEventsService._apparent_magnitude(5.0, 10.0, 1.4, 0.5)
        expected = 5.0 + 5.0 * math.log10(0.5) + 2.5 * 10.0 * math.log10(1.4)
        assert result == pytest.approx(expected)


class TestComputeTrueBrightnessPeak:
    """Tests for _compute_true_brightness_peak."""

    def _candidate(self, orbital_elements=None, magnitude=5.0):
        return {'name': 'Test Comet', 'magnitude': magnitude, 'orbital_elements': orbital_elements}

    def test_returns_none_without_orbital_elements(self):
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=6)
        assert svc._compute_true_brightness_peak(self._candidate(None), start, end) is None

    def test_returns_none_without_magnitude(self):
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=6)
        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=None)
        assert svc._compute_true_brightness_peak(candidate, start, end) is None

    def test_peak_follows_geocentric_minimum_not_perihelion(self, monkeypatch):
        """Earth's closest approach a day after perihelion should pull the
        computed peak away from perihelion itself - this is the scenario a
        real apparition (e.g. 10P/Tempel 2026) can show in practice."""
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        perihelion = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
        start = perihelion - timedelta(days=3)
        end = perihelion + timedelta(days=3)
        closest_earth_day = (perihelion + timedelta(days=1)).date()

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            r_au = 1.4  # roughly constant heliocentric distance over a week
            delta_au = 0.40 if obs_time.date() == closest_earth_day else 0.60
            return (None, 0.0, r_au, delta_au)  # dec=0 -> always overhead at the equator

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        result = svc._compute_true_brightness_peak(candidate, start, end)

        assert result is not None
        peak_date, peak_magnitude, max_transit_altitude = result
        assert peak_date.date() == closest_earth_day
        expected = round(5.0 + 5.0 * math.log10(0.40) + 2.5 * 10.0 * math.log10(1.4), 1)
        assert peak_magnitude == pytest.approx(expected)
        # svc latitude is 45, dec=0 -> transit altitude = 90 - |45 - 0| = 45.
        assert max_transit_altitude == pytest.approx(45.0)

    def test_max_transit_altitude_is_the_window_wide_maximum(self, monkeypatch):
        """The altitude tracked is the best day in the whole window, independent
        of which day happens to be the brightest."""
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=3)
        best_altitude_day = (start + timedelta(days=2)).date()

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            # Constant brightness (so the "peak day" is arbitrary/first), but
            # declination approaches the observer's latitude (45) on day 2,
            # which should produce the highest transit altitude of the window.
            dec_deg = 45.0 if obs_time.date() == best_altitude_day else -10.0
            return (None, dec_deg, 1.4, 0.5)

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        result = svc._compute_true_brightness_peak(candidate, start, end)

        assert result is not None
        _, _, max_transit_altitude = result
        assert max_transit_altitude == pytest.approx(90.0)  # dec == lat -> straight overhead

    def test_days_with_failed_propagation_are_skipped(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=2)

        def fake_comet_ra_dec(*args, **kwargs):
            raise ValueError("simulated propagation failure")

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        assert svc._compute_true_brightness_peak(candidate, start, end) is None

    def test_returns_none_when_skytonight_comets_import_fails(self, monkeypatch):
        import sys
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=2)

        # Setting the module to None in sys.modules makes any import of it raise
        # ImportError, simulating an environment where the module can't be loaded.
        monkeypatch.setitem(sys.modules, 'skytonight.skytonight_comets', None)

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        assert svc._compute_true_brightness_peak(candidate, start, end) is None

    def test_days_with_missing_distance_data_are_skipped(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=2)
        missing_data_day = start.date()

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            if obs_time.date() == missing_data_day:
                return (None, 0.0, None, None)
            return (None, 0.0, 1.4, 0.5)

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        result = svc._compute_true_brightness_peak(candidate, start, end)
        assert result is not None

    def test_days_with_no_declination_skip_altitude_tracking(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            return (None, None, 1.4, 0.5)  # declination unknown, but distance data present

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        # Magnitude is computed every day, but max_transit_altitude never gets set since
        # declination is never known, so the function's final all-or-nothing guard fires.
        assert svc._compute_true_brightness_peak(candidate, start, end) is None

    def test_days_with_non_positive_distance_skip_magnitude(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        bad_magnitude_day = start.date()

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            if obs_time.date() == bad_magnitude_day:
                return (None, 0.0, 0.0, 0.5)  # r_au non-positive -> magnitude computation fails
            return (None, 0.0, 1.4, 0.5)

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = self._candidate(_FULL_ELEMENTS_METADATA, magnitude=5.0)
        result = svc._compute_true_brightness_peak(candidate, start, end)
        assert result is not None


class TestBuildCometEventUsesBrightnessPeak:
    """Integration: _build_comet_event should prefer the true brightness peak."""

    def test_peak_time_shifts_away_from_perihelion_when_earth_is_closer_later(self, monkeypatch):
        from datetime import date, datetime, timedelta, timezone

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        perihelion = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
        closest_earth_day = (perihelion + timedelta(days=1)).date()

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            r_au = 1.4
            delta_au = 0.40 if obs_time.date() == closest_earth_day else 0.60
            return (None, 0.0, r_au, delta_au)  # dec=0 -> well above any altitude floor at lat=0

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = {
            'name': '10P/Tempel',
            'perihelion': perihelion,
            'magnitude': 5.0,
            'equipment': None,
            'orbital_elements': _FULL_ELEMENTS_METADATA,
            'target_id': 'comet-10ptempel',
        }
        event = svc._build_comet_event(candidate, date(2026, 7, 1), date(2026, 9, 1), source='dataset')

        assert event is not None
        peak_time = datetime.fromisoformat(event['peak_time'])
        assert peak_time.date() == closest_earth_day
        # Solar perihelion is still reported separately, untouched.
        assert event['perihelion_date'].startswith('2026-08-02')
        assert event['magnitude'] != 5.0  # now the computed apparent magnitude, not raw H
        assert event['altitude_limited'] is False
        assert event['target_id'] == 'comet-10ptempel'

    def test_altitude_limited_when_target_never_clears_the_site_floor(self, monkeypatch):
        """Reproduces the 10P/Tempel case: a real, notable comet that never
        rises high enough above a specific site's horizon to be observed."""
        from datetime import date, datetime, timezone

        # altitude_constraint_min=25, airmass_constraint=1.8 -> effective floor ~33.75 deg
        svc = SolarSystemEventsService(
            48.64, 5.51, timezone="Europe/Paris", altitude_constraint_min=25.0, airmass_constraint=1.8
        )
        perihelion = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)

        def fake_comet_ra_dec(q, e, omega, Omega, incl, py, pm, pd, obs_time, earth_helio):
            # dec=-24.7 near latitude 48.64 -> max transit altitude ~16.7 deg, well under the floor.
            return (None, -24.7, 1.42, 0.41)

        monkeypatch.setattr('skytonight.skytonight_comets._comet_ra_dec', fake_comet_ra_dec)
        monkeypatch.setattr('skytonight.skytonight_comets._get_earth_heliocentric', lambda obs_time: (1.0, 0.0, 0.0))

        candidate = {
            'name': '10P/Tempel',
            'perihelion': perihelion,
            'magnitude': 5.0,
            'equipment': None,
            'orbital_elements': _FULL_ELEMENTS_METADATA,
        }
        event = svc._build_comet_event(candidate, date(2026, 7, 1), date(2026, 9, 1), source='dataset')

        assert event is not None
        assert event['altitude_limited'] is True

    def test_falls_back_to_perihelion_without_orbital_elements(self):
        from datetime import date, datetime

        svc = SolarSystemEventsService(45.0, 0.0, timezone="UTC")
        perihelion = SolarSystemEventsService._parse_perihelion('2026-08-15')
        candidate = {
            'name': 'Curated Comet',
            'perihelion': perihelion,
            'magnitude': 8.0,
            'equipment': None,
            'orbital_elements': None,
        }
        event = svc._build_comet_event(candidate, date(2026, 7, 1), date(2026, 9, 1), source='curated')

        assert event is not None
        peak_time = datetime.fromisoformat(event['peak_time'])
        assert peak_time.date() == perihelion.date()
        assert event['magnitude'] == 8.0
        # Unknown (no orbital elements) defaults to "not flagged" rather than assumed limited.
        assert event['altitude_limited'] is False
        # Curated fallback comets have no SkyTonight target_id (no altitude graph button).
        assert event['target_id'] is None
