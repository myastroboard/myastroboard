"""
Tests for skytonight_calculator module.
Tests core calculation functions including AstroScore, altitude calculations,
and time conversions.
"""

import pytest
import numpy as np
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch
import tempfile
import os
from types import SimpleNamespace

from skytonight import skytonight_calculator as calc
_normalise = calc._normalise
_angular_separation_deg = calc._angular_separation_deg
_surface_brightness = calc._surface_brightness
_parse_localtime = calc._parse_localtime
_sample_times = calc._sample_times
compute_astro_score = calc.compute_astro_score
_horizon_floor_array = calc._horizon_floor_array
_alttime_json_path = calc._alttime_json_path
_set_progress = calc._set_progress
get_calculation_progress = calc.get_calculation_progress
_get_night_window = calc._get_night_window
_meridian_transit_fast = calc._meridian_transit_fast
_antimeridian_transit_fast = calc._antimeridian_transit_fast
_meridian_transit_time = calc._meridian_transit_time
_antimeridian_transit_time = calc._antimeridian_transit_time
_save_alttime_json = calc._save_alttime_json
_clear_alttime_files = calc._clear_alttime_files
_MoonInfo = calc._MoonInfo
_compute_target_result = calc._compute_target_result
_compute_body_result = calc._compute_body_result
_hours_to_hms = calc._hours_to_hms
_degrees_to_dms = calc._degrees_to_dms
compute_target_debug = calc.compute_target_debug
_build_body_alias_map = calc._build_body_alias_map
_find_body_entry_by_localized_name = calc._find_body_entry_by_localized_name
_get_astro_night_window = calc._get_astro_night_window
_cleanup_calculation_memory = calc._cleanup_calculation_memory
load_calculation_results = calc.load_calculation_results
run_calculations = calc.run_calculations
from skytonight.skytonight_models import SkyTonightTarget, SkyTonightCoordinates
from skytonight.skytonight_targets import normalize_object_name


class TestNormalise:
    """Tests for _normalise helper function."""

    def test_normalise_value_at_min(self):
        """Test normalizing value at minimum."""
        result = _normalise(20.0, 20.0, 90.0)
        assert result == 0.0

    def test_normalise_value_at_max(self):
        """Test normalizing value at maximum."""
        result = _normalise(90.0, 20.0, 90.0)
        assert result == 1.0

    def test_normalise_value_at_midpoint(self):
        """Test normalizing value at midpoint."""
        result = _normalise(55.0, 20.0, 90.0)
        assert 0.4 < result < 0.6  # Should be close to 0.5

    def test_normalise_value_below_min_clamps_to_zero(self):
        """Test that values below min are clamped to 0."""
        result = _normalise(10.0, 20.0, 90.0)
        assert result == 0.0

    def test_normalise_value_above_max_clamps_to_one(self):
        """Test that values above max are clamped to 1."""
        result = _normalise(100.0, 20.0, 90.0)
        assert result == 1.0

    def test_normalise_with_equal_bounds_returns_zero(self):
        """Test that equal lo and hi bounds return 0."""
        result = _normalise(50.0, 50.0, 50.0)
        assert result == 0.0


class TestAngularSeparationDeg:
    """Tests for _angular_separation_deg function."""

    def test_same_coordinates_zero_separation(self):
        """Test that same coordinates give 0 separation."""
        separation = _angular_separation_deg(0.0, 0.0, 0.0, 0.0)
        assert separation == pytest.approx(0.0, abs=1e-6)

    def test_opposite_poles_180_separation(self):
        """Test that opposite celestial poles give 180° separation."""
        separation = _angular_separation_deg(0.0, 90.0, 0.0, -90.0)
        assert separation == pytest.approx(180.0, abs=0.1)

    def test_separation_on_equator(self):
        """Test separation between two equatorial points."""
        # _angular_separation_deg expects RA in degrees (not hours)
        # Separation between (0°, 0°) and (90°, 0°) should be 90°
        separation = _angular_separation_deg(0.0, 0.0, 90.0, 0.0)
        assert 85.0 < separation < 95.0

    def test_small_separation(self):
        """Test calculation on small separations."""
        separation = _angular_separation_deg(0.0, 0.0, 0.1, 0.0)
        assert 0.0 < separation < 1.0

    def test_separation_symmetry(self):
        """Test that separation is symmetric."""
        sep1 = _angular_separation_deg(10.0, 20.0, 30.0, 40.0)
        sep2 = _angular_separation_deg(30.0, 40.0, 10.0, 20.0)
        assert sep1 == pytest.approx(sep2, rel=1e-6)


class TestSurfaceBrightness:
    """Tests for _surface_brightness function."""

    def test_returns_none_with_no_magnitude(self):
        """Test that None magnitude returns None."""
        result = _surface_brightness(None, 10.0)
        assert result is None

    def test_returns_none_with_no_size(self):
        """Test that None size returns None."""
        result = _surface_brightness(5.0, None)
        assert result is None

    def test_returns_none_with_zero_size(self):
        """Test that zero size returns None."""
        result = _surface_brightness(5.0, 0.0)
        assert result is None

    def test_returns_none_with_negative_size(self):
        """Test that negative size returns None."""
        result = _surface_brightness(5.0, -1.0)
        assert result is None

    def test_surface_brightness_calculation(self):
        """Test surface brightness calculation with valid inputs."""
        result = _surface_brightness(10.0, 5.0)
        assert result is not None
        assert isinstance(result, float)

    def test_larger_size_decreases_brightness(self):
        """Test that larger angular size decreases surface brightness."""
        sb_small = _surface_brightness(10.0, 5.0)
        sb_large = _surface_brightness(10.0, 20.0)
        assert sb_small is not None
        assert sb_large is not None
        assert sb_small < sb_large


class TestParseLocaltime:
    """Tests for _parse_localtime function."""

    def test_parse_yyyy_mm_dd_hh_mm_format(self):
        """Test parsing YYYY-MM-DD HH:MM format."""
        tz = ZoneInfo("UTC")
        result = _parse_localtime("2026-04-17 15:30", tz)
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 17
        assert result.hour == 15
        assert result.minute == 30

    def test_parse_iso_format(self):
        """Test parsing ISO format with T separator."""
        tz = ZoneInfo("UTC")
        result = _parse_localtime("2026-04-17T15:30", tz)
        assert result is not None
        assert result.year == 2026
        assert result.month == 4

    def test_parse_not_found_returns_none(self):
        """Test that 'Not found' string returns None."""
        tz = ZoneInfo("UTC")
        result = _parse_localtime("Not found", tz)
        assert result is None

    def test_parse_empty_string_returns_none(self):
        """Test that empty string returns None."""
        tz = ZoneInfo("UTC")
        result = _parse_localtime("", tz)
        assert result is None

    def test_parse_whitespace_returns_none(self):
        """Test that whitespace-only returns None."""
        tz = ZoneInfo("UTC")
        result = _parse_localtime("   ", tz)
        assert result is None

    def test_parse_invalid_format_returns_none(self):
        """Test that invalid format returns None."""
        tz = ZoneInfo("UTC")
        result = _parse_localtime("not a valid date", tz)
        assert result is None

    def test_parsed_time_has_timezone(self):
        """Test that parsed time has the correct timezone."""
        tz = ZoneInfo("America/New_York")
        result = _parse_localtime("2026-04-17 15:30", tz)
        assert result is not None
        assert result.tzinfo == tz


class TestSampleTimes:
    """Tests for _sample_times function."""

    def test_sample_times_returns_astropy_time(self):
        """Test that sample_times returns an Astropy Time object."""
        night_start = datetime(2026, 4, 17, 21, 0, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, 0, tzinfo=timezone.utc)
        
        result = _sample_times(night_start, night_end)
        
        assert result is not None
        # Astropy Time has 'size' attribute
        assert hasattr(result, 'jd')

    def test_sample_times_minimum_steps(self):
        """Test that at least minimum steps are created."""
        night_start = datetime(2026, 4, 17, 21, 0, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 17, 21, 30, 0, tzinfo=timezone.utc)  # 30 minutes
        
        result = _sample_times(night_start, night_end)
        
        assert len(result) >= calc._MIN_STEPS

    def test_sample_times_reasonable_number_for_full_night(self):
        """Test that a full night gets reasonable number of samples."""
        night_start = datetime(2026, 4, 17, 21, 0, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, 0, tzinfo=timezone.utc)  # 8 hours
        
        result = _sample_times(night_start, night_end)
        
        # 8 hours * 60 min / 15 min + 1 ≈ 33 steps
        assert 20 < len(result) < 50


class TestComputeAstroScore:
    """Tests for _compute_astro_score function."""

    def test_perfect_conditions_score_near_one(self):
        """Test score with perfect observing conditions."""
        score = compute_astro_score(
            max_altitude=80.0,
            observable_hours=6.0,
            meridian_altitude=75.0,
            moon_phase=0.0,  # New moon
            angular_distance_moon=180.0,  # Far from moon
            magnitude=8.0,
            size_arcmin=10.0,
            observable_hours_in_window=6.0,
            window_start_hour=22,
            is_messier=True,
            is_planet=False,
            is_opposition=False
        )
        
        assert score >= 0.6  # Should be quite high

    def test_poor_conditions_score_low(self):
        """Test score with poor observing conditions."""
        score = compute_astro_score(
            max_altitude=15.0,  # Too low
            observable_hours=0.5,
            meridian_altitude=10.0,
            moon_phase=1.0,  # Full moon
            angular_distance_moon=30.0,  # Close to moon
            magnitude=None,
            size_arcmin=None,
            observable_hours_in_window=0.5,
            window_start_hour=4,  # Late night
            is_messier=False,
            is_planet=False,
            is_opposition=False
        )
        
        assert score < 0.3

    def test_score_bounded_to_one(self):
        """Test that score with all bonuses is capped at 1.0."""
        score = compute_astro_score(
            max_altitude=90.0,
            observable_hours=8.0,
            meridian_altitude=90.0,
            moon_phase=0.0,
            angular_distance_moon=180.0,
            magnitude=5.0,
            size_arcmin=60.0,
            observable_hours_in_window=8.0,
            window_start_hour=21,
            is_messier=True,
            is_planet=True,
            is_opposition=True
        )
        
        assert score <= 1.0

    def test_score_bounded_to_zero(self):
        """Test that score is never negative."""
        score = compute_astro_score(
            max_altitude=0.0,
            observable_hours=0.0,
            meridian_altitude=-10.0,
            moon_phase=1.0,
            angular_distance_moon=0.0,
            magnitude=20.0,
            size_arcmin=0.5,
            observable_hours_in_window=0.0,
            window_start_hour=1,
            is_messier=False,
            is_planet=False,
            is_opposition=False
        )
        
        assert score >= 0.0

    def test_messier_bonus_applied(self):
        """Test that Messier bonus increases score."""
        base_score = compute_astro_score(
            max_altitude=45.0,
            observable_hours=3.0,
            meridian_altitude=40.0,
            moon_phase=0.3,
            angular_distance_moon=100.0,
            magnitude=10.0,
            size_arcmin=5.0,
            observable_hours_in_window=3.0,
            window_start_hour=23,
            is_messier=False,
            is_planet=False,
            is_opposition=False
        )
        
        messier_score = compute_astro_score(
            max_altitude=45.0,
            observable_hours=3.0,
            meridian_altitude=40.0,
            moon_phase=0.3,
            angular_distance_moon=100.0,
            magnitude=10.0,
            size_arcmin=5.0,
            observable_hours_in_window=3.0,
            window_start_hour=23,
            is_messier=True,
            is_planet=False,
            is_opposition=False
        )
        
        assert messier_score > base_score

    def test_opposition_bonus_for_planets(self):
        """Test that opposition bonus is applied to planets."""
        base_score = compute_astro_score(
            max_altitude=60.0,
            observable_hours=4.0,
            meridian_altitude=55.0,
            moon_phase=0.2,
            angular_distance_moon=120.0,
            magnitude=3.0,
            size_arcmin=15.0,
            observable_hours_in_window=4.0,
            window_start_hour=22,
            is_messier=False,
            is_planet=True,
            is_opposition=False
        )
        
        opposition_score = compute_astro_score(
            max_altitude=60.0,
            observable_hours=4.0,
            meridian_altitude=55.0,
            moon_phase=0.2,
            angular_distance_moon=120.0,
            magnitude=3.0,
            size_arcmin=15.0,
            observable_hours_in_window=4.0,
            window_start_hour=22,
            is_messier=False,
            is_planet=True,
            is_opposition=True
        )
        
        assert opposition_score > base_score


class TestHorizonFloorArray:
    """Tests for _horizon_floor_array function."""

    def test_empty_profile_returns_zeros(self):
        """Test that empty profile returns all zeros."""
        az_deg = np.array([0.0, 90.0, 180.0, 270.0])
        result = _horizon_floor_array(az_deg, [])
        
        assert len(result) == len(az_deg)
        assert np.all(result == 0.0)

    def test_single_profile_point(self):
        """Test with single profile point."""
        az_deg = np.array([0.0, 90.0, 180.0, 270.0])
        profile = [{"az": 180.0, "alt": 20.0}]
        
        result = _horizon_floor_array(az_deg, profile)
        
        assert len(result) == len(az_deg)
        assert np.all(result >= 0.0)
        assert np.all(result <= 90.0)

    def test_multiple_profile_points(self):
        """Test with multiple profile points."""
        az_deg = np.array([0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0])
        profile = [
            {"az": 0.0, "alt": 10.0},
            {"az": 90.0, "alt": 30.0},
            {"az": 180.0, "alt": 20.0},
            {"az": 270.0, "alt": 15.0}
        ]
        
        result = _horizon_floor_array(az_deg, profile)
        
        assert len(result) == len(az_deg)
        assert np.all(result >= 0.0)
        assert np.all(result <= 90.0)
        # Interpolation should be reasonably smooth
        assert np.all(np.diff(result) <= 20.0)  # No huge jumps

    def test_invalid_profile_returns_zeros(self):
        """Test that invalid profile returns zeros."""
        az_deg = np.array([0.0, 90.0, 180.0, 270.0])
        profile = [{"bad": "data"}]  # Missing 'az' and 'alt'
        
        result = _horizon_floor_array(az_deg, profile)
        
        assert len(result) == len(az_deg)
        assert np.all(result == 0.0)

    def test_wrap_around_handling(self):
        """Test that azimuths wrap around at 0/360."""
        az_deg = np.array([355.0, 0.0, 5.0])
        profile = [
            {"az": 350.0, "alt": 15.0},
            {"az": 10.0, "alt": 20.0}
        ]
        
        result = _horizon_floor_array(az_deg, profile)
        
        assert len(result) == len(az_deg)
        assert np.all(result >= 0.0)
        # Should interpolate smoothly across the 0° boundary


class TestAlttimeJsonPath:
    """Tests for _alttime_json_path function."""

    def test_sanitizes_target_id(self):
        """Test that target ID is sanitized."""
        result = _alttime_json_path("M 31 (Andromeda)")
        
        assert "_alttime.json" in result
        assert " " not in result.split("/")[-1]  # No spaces in filename

    def test_lowercase_conversion(self):
        """Test that path uses lowercase."""
        result = _alttime_json_path("M31")
        
        assert "m31_alttime.json" in result.lower()

    def test_valid_characters_preserved(self):
        """Test that valid characters are preserved."""
        result = _alttime_json_path("NGC-224_test")
        
        assert "_alttime.json" in result


class TestComputeTargetResult:
    """Tests for _compute_target_result function."""

    @patch("skytonight.skytonight_calculator._meridian_transit_fast")
    @patch("skytonight.skytonight_calculator._compute_altaz_series")
    def test_compute_target_result_returns_dict(self, mock_altaz, mock_transit):
        """Test that compute_target_result returns a dict when valid."""
        # This is a complex function that depends on many parameters
        # This test is a placeholder for basic structure verification
        pass


class TestComputeBodyAltazSeries:
    """Tests for body altitude calculations."""

    @patch("skytonight.skytonight_calculator.get_body")
    def test_compute_body_altaz_with_moon(self, mock_get_body):
        """Test altitude computation for moon (solar system body)."""
        # Mock the astropy get_body function
        # This test verifies the function handles celestial bodies correctly
        pass


class TestProgressAndNightWindow:
    def test_set_and_get_progress(self):
        _set_progress("phase-a", 3, 10)
        progress = get_calculation_progress()
        assert progress["phase"] == "phase-a"
        assert progress["phase_processed"] == 3
        assert progress["phase_total"] == 10

    @patch("skytonight.skytonight_calculator.SunService")
    def test_get_night_window_today(self, mock_sun_service):
        fake = MagicMock()
        fake.get_today_report.return_value = SimpleNamespace(
            nautical_dusk="2026-04-17 21:00",
            nautical_dawn="2026-04-18 05:00",
        )
        mock_sun_service.return_value = fake

        window = _get_night_window(45.0, -75.0, "UTC")
        assert window is not None
        assert window[0] < window[1]

    @patch("skytonight.skytonight_calculator.SunService")
    def test_get_night_window_tomorrow_fallback(self, mock_sun_service):
        fake = MagicMock()
        fake.get_today_report.return_value = SimpleNamespace(
            nautical_dusk="2026-04-18 21:00",
            nautical_dawn="2026-04-18 05:00",
        )
        fake.get_tomorrow_report.return_value = SimpleNamespace(
            nautical_dusk="2026-04-18 21:00",
            nautical_dawn="2026-04-19 05:00",
        )
        mock_sun_service.return_value = fake

        window = _get_night_window(45.0, -75.0, "UTC")
        assert window is not None
        assert window[0] < window[1]


class TestTransitHelpers:
    def test_meridian_transit_fast_crossing(self):
        times = [datetime(2026, 4, 17, 21, 0), datetime(2026, 4, 17, 21, 15), datetime(2026, 4, 17, 21, 30)]
        lst = np.array([4.8, 5.1, 5.4])
        out = _meridian_transit_fast(5.0, lst, times)
        assert out == "21:15"

    def test_antimeridian_transit_fast_crossing(self):
        times = [datetime(2026, 4, 17, 21, 0), datetime(2026, 4, 17, 21, 15), datetime(2026, 4, 17, 21, 30)]
        lst = np.array([16.8, 17.2, 17.5])
        out = _antimeridian_transit_fast(5.0, lst, times)
        assert out == "21:15"

    def test_meridian_transit_fast_no_crossing(self):
        times = [datetime(2026, 4, 17, 21, 0), datetime(2026, 4, 17, 21, 15)]
        lst = np.array([7.0, 7.2])
        out = _meridian_transit_fast(5.0, lst, times)
        assert out is None

    @patch("skytonight.skytonight_calculator.EarthLocation")
    @patch("skytonight.skytonight_calculator.Time")
    def test_meridian_transit_time_crossing(self, mock_time, mock_location):
        sequence = iter([4.8, 5.2])

        class _FakeTime:
            def sidereal_time(self, *_args, **_kwargs):
                return SimpleNamespace(hour=next(sequence))

        mock_time.side_effect = lambda *args, **kwargs: _FakeTime()
        mock_location.return_value = SimpleNamespace(lon=0)

        start = datetime(2026, 4, 17, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        out = _meridian_transit_time(5.0, start, end, 45.0, -75.0)
        assert out == "00:15"

    @patch("skytonight.skytonight_calculator.EarthLocation")
    @patch("skytonight.skytonight_calculator.Time")
    def test_antimeridian_transit_time_crossing(self, mock_time, mock_location):
        sequence = iter([16.8, 17.2])

        class _FakeTime:
            def sidereal_time(self, *_args, **_kwargs):
                return SimpleNamespace(hour=next(sequence))

        mock_time.side_effect = lambda *args, **kwargs: _FakeTime()
        mock_location.return_value = SimpleNamespace(lon=0)

        start = datetime(2026, 4, 17, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        out = _antimeridian_transit_time(5.0, start, end, 45.0, -75.0)
        assert out == "00:15"


class TestAlttimeAndMoonInfo:
    def test_save_and_clear_alttime_files(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with patch.object(calc, 'get_alttime_dir', lambda *_a, **_k: tmp):
                times = [datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)]
                ok = _save_alttime_json(
                    target_id="m31",
                    name="M31",
                    times=None,
                    altitudes=np.array([45.0]),
                    night_start=times[0],
                    night_end=times[0] + timedelta(hours=1),
                    constraints={"altitude_constraint_min": 20, "altitude_constraint_max": 80},
                    precomputed_times_iso=["2026-04-17T21:00:00"],
                )
                assert ok is True

                # Create extra files and clear only *_alttime.json
                with open(os.path.join(tmp, "foo_alttime.json"), "w", encoding="utf-8") as f:
                    f.write("{}")
                with open(os.path.join(tmp, "keep.txt"), "w", encoding="utf-8") as f:
                    f.write("x")

                _clear_alttime_files()

                assert os.path.exists(os.path.join(tmp, "keep.txt"))
                assert not os.path.exists(os.path.join(tmp, "foo_alttime.json"))

    @patch("skytonight.skytonight_calculator.get_body")
    @patch("skytonight.skytonight_calculator.moon_illumination")
    def test_moon_info_computation(self, mock_illum, mock_get_body):
        mock_illum.return_value = 0.33
        fake_body = SimpleNamespace(
            ra=SimpleNamespace(deg=100.0),
            dec=SimpleNamespace(deg=-20.0),
        )
        mock_get_body.return_value = fake_body

        times = [object(), object(), object()]
        location = object()
        info = _MoonInfo(times, location)
        assert info.phase == 0.33
        assert info.ra_deg == 100.0
        assert info.dec_deg == -20.0


class TestTargetAndBodyResultBuilders:
    def test_compute_target_result_success(self):
        target = SimpleNamespace(
            target_id="m31",
            preferred_name="M31",
            catalogue_names={"Messier": "M31"},
            category="deep_sky",
            object_type="galaxy",
            constellation="Andromeda",
            magnitude=4.5,
            size_arcmin=30.0,
            coordinates=SimpleNamespace(ra_hours=0.7, dec_degrees=41.3),
            source_catalogues=["Messier"],
            metadata={},
        )
        moon = SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=10.0)
        constraints = {
            "altitude_constraint_min": 20,
            "altitude_constraint_max": 80,
            "moon_separation_min": 10,
            "size_constraint_min": 5,
            "size_constraint_max": 300,
            "fraction_of_time_observable_threshold": 0.2,
            "moon_separation_use_illumination": False,
            "airmass_constraint": 2.0,
        }
        alt = np.array([25.0, 30.0, 45.0, 35.0], dtype=np.float32)
        az = np.array([100.0, 120.0, 150.0, 180.0], dtype=np.float32)
        times_local = [
            datetime(2026, 4, 17, 21, 0),
            datetime(2026, 4, 17, 21, 15),
            datetime(2026, 4, 17, 21, 30),
            datetime(2026, 4, 17, 21, 45),
        ]
        lst = np.array([0.5, 0.7, 0.9, 1.1])

        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=alt,
            location=object(),
            moon=moon,
            constraints=constraints,
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0,
            lon=-75.0,
            az_values=az,
            lst_hours=lst,
            times_local=times_local,
        )

        assert result is not None
        assert result["target_id"] == "m31"
        assert result["observation"]["max_altitude"] == 45.0

    def test_compute_target_result_filters_on_size(self):
        target = SimpleNamespace(
            target_id="x",
            preferred_name="X",
            catalogue_names={},
            category="deep_sky",
            object_type="nebula",
            constellation="Ori",
            magnitude=5.0,
            size_arcmin=1.0,
            coordinates=SimpleNamespace(ra_hours=1.0, dec_degrees=10.0),
            source_catalogues=[],
            metadata={},
        )
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        constraints = {
            "size_constraint_min": 5,
            "size_constraint_max": 300,
            "fraction_of_time_observable_threshold": 0.0,
        }
        res = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([30.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=constraints,
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 17, 23, 0),
            lat=45.0,
            lon=-75.0,
            az_values=np.array([50.0, 60.0]),
            lst_hours=np.array([1.0, 1.2]),
            times_local=[datetime(2026, 4, 17, 21, 0), datetime(2026, 4, 17, 21, 15)],
        )
        assert res is None

    @patch("skytonight.skytonight_calculator._compute_body_altaz_series")
    @patch("skytonight.skytonight_calculator._antimeridian_transit_time")
    @patch("skytonight.skytonight_calculator._meridian_transit_time")
    def test_compute_body_result_success(self, mock_meridian, mock_antimeridian, mock_series):
        target = SimpleNamespace(
            target_id="jupiter",
            preferred_name="Jupiter",
            catalogue_names={"SolarSystem": "Jupiter"},
            category="solar_system",
            object_type="planet",
            magnitude=-2.0,
            source_catalogues=["SolarSystem"],
            metadata={},
        )
        mock_series.return_value = (
            np.array([30.0, 50.0, 40.0], dtype=np.float32),
            np.array([100.0, 140.0, 160.0], dtype=np.float32),
            1.5,
            12.0,
        )
        mock_meridian.return_value = "22:00"
        mock_antimeridian.return_value = "04:00"

        moon = SimpleNamespace(phase=0.1, ra_deg=20.0, dec_deg=5.0)
        res, alt, az = _compute_body_result(
            target=target,
            times=[object(), object(), object()],
            location=object(),
            moon=moon,
            constraints={"altitude_constraint_min": 20, "airmass_constraint": 2.0},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0,
            lon=-75.0,
        )

        assert res is not None
        assert res["target_id"] == "jupiter"
        assert alt is not None and az is not None

    def test_hours_and_degrees_formatters(self):
        assert "h" in _hours_to_hms(1.5)
        assert "\u00b0" in _degrees_to_dms(-12.5)


# ---------------------------------------------------------------------------
# Helpers shared by TestComputeTargetDebug
# ---------------------------------------------------------------------------

_DEBUG_NIGHT_START = datetime(2026, 5, 28, 21, 0, 0, tzinfo=timezone.utc)
_DEBUG_NIGHT_END   = datetime(2026, 5, 29,  5, 0, 0, tzinfo=timezone.utc)  # 8-hour night


def _debug_config(**constraint_overrides):
    # v1.2: horizon_profile lives on the location preset, not in constraints
    horizon_profile = constraint_overrides.pop('horizon_profile', [])
    constraints = {
        'altitude_constraint_min': 30,
        'altitude_constraint_max': 80,
        'airmass_constraint': 2.0,
        'size_constraint_min': 10,
        'size_constraint_max': 300,
        'moon_separation_min': 45,
        'fraction_of_time_observable_threshold': 0.5,
        'moon_separation_use_illumination': False,
    }
    constraints.update(constraint_overrides)
    return {
        'locations': [
            {
                'id': 'debug-loc',
                'name': 'Debug Site',
                'latitude': 48.0,
                'longitude': 2.0,
                'elevation': 100.0,
                'timezone': 'UTC',
                'is_install_default': True,
                'horizon_profile': horizon_profile,
            }
        ],
        'skytonight': {'constraints': constraints},
    }


def _debug_dso(preferred_name='NGC 224', size_arcmin=50.0, ra_hours=0.71, dec_degrees=41.3):
    return SkyTonightTarget(
        target_id='dso-test',
        category='deep_sky',
        object_type='Galaxy',
        preferred_name=preferred_name,
        catalogue_names={'OpenNGC': preferred_name},
        constellation='Andromeda',
        magnitude=3.4,
        size_arcmin=size_arcmin,
        coordinates=SkyTonightCoordinates(ra_hours=ra_hours, dec_degrees=dec_degrees),
        source_catalogues=['OpenNGC'],
    )


def _debug_body(preferred_name='Jupiter', object_type='Planet'):
    return SkyTonightTarget(
        target_id=f'body-{preferred_name.lower()}',
        category='bodies',
        object_type=object_type,
        preferred_name=preferred_name,
        catalogue_names={'Bodies': preferred_name},
        source_catalogues=['Bodies'],
        metadata={'source': 'builtin-solar-system'},
    )


def _debug_dataset(target):
    norm = normalize_object_name(target.preferred_name)
    return {
        'targets': [target],
        'lookup': {f'preferred::{norm}': {'target_id': target.target_id}},
    }


class TestComputeTargetDebug:
    """Tests for compute_target_debug \u2014 verifies constraint checks, body/Moon exemptions,
    and horizon_active flag without performing real astronomical computations."""

    ALT_HIGH = np.array([35.0, 45.0, 60.0, 55.0, 40.0], dtype=float)  # all \u2265 alt_min
    ALT_LOW  = np.array([ 5.0, 10.0, 15.0, 10.0,  5.0], dtype=float)  # all < alt_min
    AZ_5     = np.array([100.0, 120.0, 150.0, 180.0, 200.0], dtype=float)

    def _run(self, target, config, alt_deg, *, is_body=False,
             az_deg=None, moon_ra=100.0, moon_dec=-10.0):
        """Run compute_target_debug with all heavy dependencies mocked."""
        az = az_deg if az_deg is not None else self.AZ_5[:len(alt_deg)]
        dataset = _debug_dataset(target)
        moon = SimpleNamespace(phase=0.2, ra_deg=moon_ra, dec_deg=moon_dec)
        mock_times = MagicMock()
        mock_times.to_datetime.return_value = [
            _DEBUG_NIGHT_START + timedelta(minutes=i * 15) for i in range(len(alt_deg))
        ]

        p_ds    = patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset)
        p_night = patch('skytonight.skytonight_calculator._get_night_window',
                        return_value=(_DEBUG_NIGHT_START, _DEBUG_NIGHT_END))
        p_astro = patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None)
        p_loc   = patch('skytonight.skytonight_calculator.EarthLocation')
        p_moon  = patch('skytonight.skytonight_calculator._MoonInfo', return_value=moon)
        p_times = patch('skytonight.skytonight_calculator._sample_times', return_value=mock_times)
        if is_body:
            p_altaz = patch('skytonight.skytonight_calculator._compute_body_altaz_series',
                            return_value=(alt_deg, az, 1.5, 12.0))
        else:
            p_altaz = patch('skytonight.skytonight_calculator._compute_altaz_series',
                            return_value=(alt_deg, az))

        with p_ds, p_night, p_astro, p_loc, p_moon, p_times, p_altaz:
            return compute_target_debug(target.preferred_name, config=config)

    # ------------------------------------------------------------------ lookup

    def test_unknown_name_returns_not_found(self):
        config = _debug_config()
        with patch('skytonight.skytonight_calculator.load_targets_dataset',
                   return_value={'targets': [], 'lookup': {}}):
            result = compute_target_debug('ZZZ_NoSuchObject_xyz', config=config)
        assert result == {'found': False}

    def test_found_flag_is_true_for_known_target(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        assert result['found'] is True

    # ------------------------------------------------------------------ night

    def test_no_night_window_returns_no_night(self):
        target = _debug_dso()
        config = _debug_config()
        dataset = _debug_dataset(target)
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window', return_value=None):
            result = compute_target_debug(target.preferred_name, config=config)
        assert result['overall'] == 'no_night'
        assert result['found'] is True

    # ------------------------------------------------------------------ coordinates

    def test_non_body_without_coordinates_returns_no_coordinates(self):
        target = SkyTonightTarget(
            target_id='dso-nocoords',
            category='deep_sky',
            object_type='Galaxy',
            preferred_name='NoCoords',
            catalogue_names={},
            source_catalogues=[],
        )
        config = _debug_config()
        dataset = _debug_dataset(target)
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window',
                   return_value=(_DEBUG_NIGHT_START, _DEBUG_NIGHT_END)):
            result = compute_target_debug('NoCoords', config=config)
        assert result['overall'] == 'no_coordinates'

    # ------------------------------------------------------------------ DSO size checks

    def test_dso_too_small_is_filtered(self):
        target = _debug_dso(size_arcmin=3.0)      # below size_constraint_min=10
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        assert result['overall'] == 'filtered'
        size_check = next(c for c in result['checks'] if c['name'] == 'size_min')
        assert size_check['passed'] is False

    def test_dso_too_large_is_filtered(self):
        target = _debug_dso(size_arcmin=500.0)    # above size_constraint_max=300
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        assert result['overall'] == 'filtered'
        size_check = next(c for c in result['checks'] if c['name'] == 'size_max')
        assert size_check['passed'] is False

    def test_dso_within_size_range_passes_size_checks(self):
        target = _debug_dso(size_arcmin=50.0)     # 10 \u2264 50 \u2264 300 \u2192 both pass
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        size_min_check = next(c for c in result['checks'] if c['name'] == 'size_min')
        size_max_check = next(c for c in result['checks'] if c['name'] == 'size_max')
        assert size_min_check['passed'] is True
        assert size_max_check['passed'] is True

    # ------------------------------------------------------------------ moon separation

    def test_dso_too_close_to_moon_is_filtered(self):
        # Moon placed at same position as target \u2192 separation \u2248 0\u00b0 < min 45\u00b0
        target = _debug_dso(ra_hours=0.71, dec_degrees=41.3)
        result = self._run(target, _debug_config(), self.ALT_HIGH,
                           moon_ra=0.71 * 15, moon_dec=41.3)
        assert result['overall'] == 'filtered'
        sep_check = next(c for c in result['checks'] if c['name'] == 'moon_separation')
        assert sep_check['passed'] is False

    def test_dso_far_from_moon_passes_separation(self):
        # Moon at (100\u00b0, -10\u00b0) is ~96\u00b0 away from target at (10.65\u00b0, 41.3\u00b0) \u2192 > 45\u00b0 min
        target = _debug_dso(ra_hours=0.71, dec_degrees=41.3)
        result = self._run(target, _debug_config(), self.ALT_HIGH,
                           moon_ra=100.0, moon_dec=-10.0)
        sep_check = next((c for c in result['checks'] if c['name'] == 'moon_separation'), None)
        if sep_check is not None:
            assert sep_check['passed'] is True

    # ------------------------------------------------------------------ altitude

    def test_dso_never_above_min_altitude_is_filtered(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_LOW)   # max=15 < 30
        assert result['overall'] == 'filtered'
        alt_check = next(c for c in result['checks'] if c['name'] == 'max_altitude')
        assert alt_check['passed'] is False

    def test_dso_reaches_min_altitude_passes(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_HIGH)  # max=60 \u2265 30
        alt_check = next(c for c in result['checks'] if c['name'] == 'max_altitude')
        assert alt_check['passed'] is True

    # ------------------------------------------------------------------ observable fraction

    def test_dso_zero_observable_fraction_is_filtered(self):
        # All steps below alt_min \u2192 fraction=0, hours=0 \u2192 both thresholds fail
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_LOW)
        frac_check = next(c for c in result['checks'] if c['name'] == 'observable_fraction')
        assert frac_check['passed'] is False

    def test_dso_passing_all_checks_is_visible(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        assert result['overall'] == 'visible'
        assert all(c['passed'] for c in result['checks']
                   if not (c.get('note') or '').startswith('No size'))

    # ------------------------------------------------------------------ body checks

    def test_body_skips_size_and_moon_separation_checks(self):
        target = _debug_body('Jupiter', 'Planet')
        result = self._run(target, _debug_config(), self.ALT_HIGH, is_body=True)
        check_names = {c['name'] for c in result['checks']}
        assert 'size_min' not in check_names
        assert 'size_max' not in check_names
        assert 'moon_separation' not in check_names

    def test_body_observable_fraction_uses_low_threshold(self):
        # 1 out of 5 steps above alt_min = 20 % \u2014 fails DSO threshold (50 %) but
        # passes body threshold (5 %).
        alt = np.array([5.0, 5.0, 35.0, 5.0, 5.0], dtype=float)
        target = _debug_body('Jupiter', 'Planet')
        result = self._run(target, _debug_config(), alt, is_body=True)
        frac_check = next(c for c in result['checks'] if c['name'] == 'observable_fraction')
        assert frac_check['threshold'] == pytest.approx(0.05)
        assert frac_check['min_observable_hours'] is None  # no hours threshold for bodies

    # ------------------------------------------------------------------ Moon exemptions

    def test_moon_always_passes_max_altitude_check(self):
        target = _debug_body('Moon', 'Moon')
        result = self._run(target, _debug_config(), self.ALT_LOW, is_body=True)
        alt_check = next(c for c in result['checks'] if c['name'] == 'max_altitude')
        assert alt_check['passed'] is True

    def test_moon_always_passes_observable_fraction_check(self):
        target = _debug_body('Moon', 'Moon')
        result = self._run(target, _debug_config(), self.ALT_LOW, is_body=True)
        frac_check = next(c for c in result['checks'] if c['name'] == 'observable_fraction')
        assert frac_check['passed'] is True

    # ------------------------------------------------------------------ horizon_active flag

    def test_horizon_active_false_when_no_profile(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(horizon_profile=[]), self.ALT_HIGH)
        assert result['constraints']['horizon_active'] is False

    def test_horizon_active_true_when_profile_configured(self):
        profile = [{'az': 0.0, 'alt': 10.0}, {'az': 180.0, 'alt': 15.0}]
        target = _debug_dso()
        result = self._run(target, _debug_config(horizon_profile=profile), self.ALT_HIGH)
        assert result['constraints']['horizon_active'] is True

    # ------------------------------------------------------------------ response shape

    def test_response_contains_required_keys(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        for key in ('found', 'target', 'night_window', 'checks', 'overall', 'constraints', 'alttime'):
            assert key in result, f"Missing key: {key}"

    def test_checks_contain_value_and_threshold(self):
        target = _debug_dso()
        result = self._run(target, _debug_config(), self.ALT_HIGH)
        for check in result['checks']:
            assert 'name' in check
            assert 'passed' in check


class TestBodyAliasMap:
    """Tests for the i18n-based body alias reverse map helpers."""

    def setup_method(self):
        # Reset the module-level cache so each test starts fresh.
        calc._body_alias_map_cache = None

    def test_build_body_alias_map_returns_nonempty_dict(self):
        alias_map = _build_body_alias_map()
        assert isinstance(alias_map, dict)
        assert len(alias_map) > 0

    def test_build_body_alias_map_maps_french_moon_to_moon(self):
        alias_map = _build_body_alias_map()
        # 'lune' is the normalized form of the French name 'Lune'
        assert alias_map.get('lune') == 'Moon'

    def test_find_body_entry_returns_none_for_unknown_name(self):
        fake_lookup = {'preferred::moon': {'target_id': 'body-moon'}}
        result = _find_body_entry_by_localized_name('xyz_nonexistent_zzz', fake_lookup)
        assert result is None

    def test_find_body_entry_resolves_canonical_name_via_lookup(self):
        # Seed cache with a known mapping so we don't rely on i18n file I/O.
        calc._body_alias_map_cache = {'lune': 'Moon'}
        lookup = {
            'preferred::moon': {'target_id': 'body-moon'},
            'alias::moon': {'target_id': 'body-moon'},
        }
        result = _find_body_entry_by_localized_name('lune', lookup)
        assert result is not None
        assert result['target_id'] == 'body-moon'


# ---------------------------------------------------------------------------
# Additional tests to improve branch/line coverage
# ---------------------------------------------------------------------------


class TestSaveAlttimeJsonBranches:
    """Cover _save_alttime_json optional-field branches."""

    def test_save_alttime_with_astro_night_and_azimuth(self):
        """Covers astro_night_start/end + az_degrees branches."""
        import tempfile
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with patch.object(calc, 'get_alttime_dir', lambda *_a, **_k: tmp):
                night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
                night_end = night_start + timedelta(hours=8)
                ok = _save_alttime_json(
                    target_id='ngc-test',
                    name='NGC Test',
                    times=None,
                    altitudes=np.array([35.0, 45.0]),
                    night_start=night_start,
                    night_end=night_end,
                    constraints={'altitude_constraint_min': 20, 'altitude_constraint_max': 80},
                    precomputed_times_iso=['2026-04-17T21:00:00', '2026-04-17T21:15:00'],
                    az_degrees=np.array([100.0, 120.0]),
                    astro_night_start=night_start + timedelta(minutes=30),
                    astro_night_end=night_end - timedelta(minutes=30),
                )
                assert ok is True

    def test_save_alttime_with_horizon_profile(self):
        """Covers horizon_profile branch in _save_alttime_json."""
        import tempfile
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with patch.object(calc, 'get_alttime_dir', lambda *_a, **_k: tmp):
                night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
                ok = _save_alttime_json(
                    target_id='ngc-horizon',
                    name='NGC Horizon',
                    times=None,
                    altitudes=np.array([35.0]),
                    night_start=night_start,
                    night_end=night_start + timedelta(hours=6),
                    constraints={
                        'altitude_constraint_min': 20,
                        'altitude_constraint_max': 80,
                        'horizon_profile': [{'az': 0.0, 'alt': 10.0}, {'az': 180.0, 'alt': 15.0}],
                    },
                    precomputed_times_iso=['2026-04-17T21:00:00'],
                )
                assert ok is True

    def test_save_alttime_exception_returns_false(self):
        """Covers exception handler branch."""
        with patch('skytonight.skytonight_calculator.get_alttime_dir', side_effect=RuntimeError('disk full')):
            ok = _save_alttime_json(
                target_id='fail',
                name='Fail',
                times=None,
                altitudes=np.array([30.0]),
                night_start=datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc),
                night_end=datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc),
                constraints={},
                precomputed_times_iso=['2026-04-17T21:00:00'],
            )
            assert ok is False

    def test_save_alttime_with_times_object(self):
        """Covers the else branch where times is not None."""
        import tempfile
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with patch.object(calc, 'get_alttime_dir', lambda *_a, **_k: tmp):
                night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
                # Create a fake times object whose to_datetime() returns list of datetimes
                fake_times = MagicMock()
                fake_dt_list = [
                    datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc),
                    datetime(2026, 4, 17, 21, 15, tzinfo=timezone.utc),
                ]
                # to_datetime should return objects with strftime
                fake_times.to_datetime.return_value = fake_dt_list
                ok = _save_alttime_json(
                    target_id='m42',
                    name='M42',
                    times=fake_times,
                    altitudes=np.array([40.0, 45.0]),
                    night_start=night_start,
                    night_end=night_start + timedelta(hours=6),
                    constraints={'altitude_constraint_min': 20, 'altitude_constraint_max': 80},
                    precomputed_times_iso=None,  # Force the times branch
                )
                assert ok is True


class TestClearAlttimeFilesEdgeCases:
    """Cover _clear_alttime_files exception path."""

    def test_clear_alttime_files_handles_remove_error(self):
        """Covers the inner except block when os.remove fails."""
        import tempfile
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            # Create an alttime JSON file
            fname = os.path.join(tmp, 'test_alttime.json')
            with open(fname, 'w') as f:
                f.write('{}')
            with patch.object(calc, 'get_alttime_dir', lambda *_a, **_k: tmp):
                with patch('os.remove', side_effect=PermissionError('no permission')):
                    # Should not raise; silently swallows the error
                    _clear_alttime_files()

    def test_clear_alttime_files_outer_exception(self):
        """Covers the outer except block."""
        with patch('skytonight.skytonight_calculator.get_alttime_dir', side_effect=OSError('fail')):
            _clear_alttime_files()  # must not raise


class TestGetAstroNightWindow:
    """Cover _get_astro_night_window branches."""

    @patch('skytonight.skytonight_calculator.SunService')
    def test_get_astro_night_window_today(self, mock_sun_service):
        from types import SimpleNamespace
        fake = MagicMock()
        fake.get_today_report.return_value = SimpleNamespace(
            astronomical_dusk='2026-04-17 22:00',
            astronomical_dawn='2026-04-18 04:00',
        )
        mock_sun_service.return_value = fake
        window = _get_astro_night_window(45.0, -75.0, 'UTC')
        assert window is not None
        assert window[0] < window[1]

    @patch('skytonight.skytonight_calculator.SunService')
    def test_get_astro_night_window_falls_back_to_tomorrow(self, mock_sun_service):
        from types import SimpleNamespace
        fake = MagicMock()
        # Today: dawn <= dusk (forces fallback to tomorrow)
        fake.get_today_report.return_value = SimpleNamespace(
            astronomical_dusk='2026-04-18 22:00',
            astronomical_dawn='2026-04-18 04:00',
        )
        fake.get_tomorrow_report.return_value = SimpleNamespace(
            astronomical_dusk='2026-04-18 22:00',
            astronomical_dawn='2026-04-19 04:00',
        )
        mock_sun_service.return_value = fake
        window = _get_astro_night_window(45.0, -75.0, 'UTC')
        assert window is not None

    @patch('skytonight.skytonight_calculator.SunService')
    def test_get_astro_night_window_returns_none_when_unavailable(self, mock_sun_service):
        from types import SimpleNamespace
        fake = MagicMock()
        fake.get_today_report.return_value = SimpleNamespace(
            astronomical_dusk='Not found',
            astronomical_dawn='Not found',
        )
        fake.get_tomorrow_report.return_value = SimpleNamespace(
            astronomical_dusk='Not found',
            astronomical_dawn='Not found',
        )
        mock_sun_service.return_value = fake
        window = _get_astro_night_window(45.0, -75.0, 'UTC')
        assert window is None


class TestGetNightWindowEdgeCases:
    """Cover remaining _get_night_window branches."""

    @patch('skytonight.skytonight_calculator.SunService')
    def test_get_night_window_returns_none_when_tomorrow_also_fails(self, mock_sun_service):
        from types import SimpleNamespace
        fake = MagicMock()
        # Force dawn <= dusk today (triggers tomorrow lookup)
        fake.get_today_report.return_value = SimpleNamespace(
            nautical_dusk='2026-04-18 22:00',
            nautical_dawn='2026-04-18 04:00',
        )
        # Tomorrow also bad
        fake.get_tomorrow_report.return_value = SimpleNamespace(
            nautical_dusk='Not found',
            nautical_dawn='Not found',
        )
        mock_sun_service.return_value = fake
        window = _get_night_window(45.0, -75.0, 'UTC')
        assert window is None

    @patch('skytonight.skytonight_calculator.SunService')
    def test_get_night_window_none_when_today_none(self, mock_sun_service):
        from types import SimpleNamespace
        fake = MagicMock()
        fake.get_today_report.return_value = SimpleNamespace(
            nautical_dusk=None,
            nautical_dawn=None,
        )
        mock_sun_service.return_value = fake
        window = _get_night_window(45.0, -75.0, 'UTC')
        assert window is None


class TestMoonInfoExceptionPath:
    """Cover _MoonInfo._compute exception branch."""

    def test_moon_info_graceful_on_exception(self):
        with patch('skytonight.skytonight_calculator.moon_illumination', side_effect=RuntimeError('ephemeris fail')):
            times = [object()]
            info = _MoonInfo(times, object())
            # phase defaults to 0.0 on error
            assert info.phase == 0.0
            assert info.ra_deg is None
            assert info.dec_deg is None


class TestMeridianTransitExceptionPaths:
    """Cover exception paths in meridian/antimeridian transit functions."""

    def test_meridian_transit_fast_exception(self):
        """Covers exception in _meridian_transit_fast."""
        # Pass bad data that will cause an exception inside numpy operations
        result = _meridian_transit_fast(5.0, None, [])  # type: ignore
        assert result is None

    def test_antimeridian_transit_fast_exception(self):
        """Covers exception in _antimeridian_transit_fast."""
        result = _antimeridian_transit_fast(5.0, None, [])  # type: ignore
        assert result is None

    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator.Time')
    def test_meridian_transit_time_exception(self, mock_time, mock_location):
        """Covers exception handler in _meridian_transit_time."""
        mock_time.side_effect = Exception('time broken')
        start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        result = _meridian_transit_time(5.0, start, end, 45.0, -75.0)
        assert result is None

    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator.Time')
    def test_antimeridian_transit_time_exception(self, mock_time, mock_location):
        """Covers exception handler in _antimeridian_transit_time."""
        mock_time.side_effect = Exception('time broken')
        start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        result = _antimeridian_transit_time(5.0, start, end, 45.0, -75.0)
        assert result is None


class TestComputeTargetResultEdgeCases:
    """Cover uncovered branches in _compute_target_result."""

    def _base_target(self):
        from types import SimpleNamespace
        return SimpleNamespace(
            target_id='m42',
            preferred_name='M42',
            catalogue_names={'Messier': 'M42'},
            category='deep_sky',
            object_type='nebula',
            constellation='Orion',
            magnitude=4.0,
            size_arcmin=65.0,
            coordinates=SimpleNamespace(ra_hours=5.58, dec_degrees=-5.39),
            source_catalogues=['Messier'],
            metadata={},
        )

    def _base_constraints(self, **overrides):
        c = {
            'altitude_constraint_min': 20,
            'altitude_constraint_max': 80,
            'moon_separation_min': 45,
            'size_constraint_min': 5,
            'size_constraint_max': 300,
            'fraction_of_time_observable_threshold': 0.2,
            'moon_separation_use_illumination': False,
            'airmass_constraint': 2.0,
        }
        c.update(overrides)
        return c

    def test_returns_none_when_coordinates_is_none(self):
        from types import SimpleNamespace
        target = self._base_target()
        target.coordinates = None
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([30.0, 40.0]),
            location=object(),
            moon=SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None),
            constraints=self._base_constraints(),
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is None

    def test_returns_none_when_too_few_steps(self):
        from types import SimpleNamespace
        target = self._base_target()
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0]),  # Only 1 step < _MIN_STEPS=2
            location=object(),
            moon=SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None),
            constraints=self._base_constraints(),
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is None

    def test_moon_separation_illumination_mode(self):
        """Covers the moon_use_illum branch."""
        from types import SimpleNamespace
        target = self._base_target()
        # Moon at same position as target → will fail moon separation
        moon = SimpleNamespace(phase=0.8, ra_deg=5.58 * 15.0, dec_deg=-5.39)
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=self._base_constraints(moon_separation_use_illumination=True),
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        # With 80% illumination → effective min sep = 80°; target near moon → filtered
        assert result is None

    def test_north_to_east_ccw_azimuth(self):
        """Covers north_to_east_ccw branch for azimuth computation."""
        from types import SimpleNamespace
        target = self._base_target()
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=self._base_constraints(north_to_east_ccw=True),
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
            az_values=np.array([90.0, 120.0, 150.0, 180.0]),
        )
        assert result is not None
        # azimuth should be CCW: (360 - az_cw) % 360
        # peak at idx 2 → az_cw=150 → CCW = (360-150)%360 = 210
        assert result['observation']['azimuth'] == 210.0

    def test_fallback_az_computation_without_az_values(self):
        """Covers the else branch computing az from SkyCoord when az_values is None."""
        from types import SimpleNamespace
        target = self._base_target()
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)

        # Provide a fake times array that supports slicing
        mock_times = MagicMock()
        mock_slice = MagicMock()
        mock_times.__getitem__ = MagicMock(return_value=mock_slice)

        with patch('skytonight.skytonight_calculator.SkyCoord') as mock_skycoord, \
             patch('skytonight.skytonight_calculator.AltAz') as mock_altaz:
            mock_altaz_inst = MagicMock()
            mock_altaz_inst.az.deg = [120.0]
            mock_coord_inst = MagicMock()
            mock_coord_inst.transform_to.return_value = mock_altaz_inst
            mock_skycoord.return_value = mock_coord_inst

            result = _compute_target_result(
                target=target,
                times=mock_times,
                altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
                location=object(),
                moon=moon,
                constraints=self._base_constraints(),
                night_start=datetime(2026, 4, 17, 21, 0),
                night_end=datetime(2026, 4, 18, 5, 0),
                lat=45.0, lon=-75.0,
                az_values=None,  # Force the fallback branch
                lst_hours=np.array([0.5, 0.7, 0.9, 1.1]),
                times_local=[
                    datetime(2026, 4, 17, 21, 0),
                    datetime(2026, 4, 17, 21, 15),
                    datetime(2026, 4, 17, 21, 30),
                    datetime(2026, 4, 17, 21, 45),
                ],
            )
        assert result is not None

    def test_horizon_profile_applies_floor(self):
        """Covers horizon_profile branch in observable fraction."""
        from types import SimpleNamespace
        target = self._base_target()
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        # Profile sets very high floor → target never visible → returns None
        profile = [{'az': 0.0, 'alt': 80.0}, {'az': 180.0, 'alt': 80.0}, {'az': 360.0, 'alt': 80.0}]
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=self._base_constraints(
                horizon_profile=profile,
                fraction_of_time_observable_threshold=0.5,
            ),
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
            az_values=np.array([90.0, 120.0, 150.0, 180.0]),
        )
        assert result is None

    def test_preferred_name_order_applied(self):
        """Covers preferred_name_order branch in result building."""
        from types import SimpleNamespace
        target = self._base_target()
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=self._base_constraints(),
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
            az_values=np.array([90.0, 120.0, 150.0, 180.0]),
            preferred_name_order=['Messier'],
        )
        assert result is not None
        # preferred_name_order=['Messier'] → picks from catalogue_names['Messier'] = 'M42'
        assert result['preferred_name'] == 'M42'

    def test_rise_set_times_without_times_local(self):
        """Covers the else branch for rise/set time when times_local is None."""
        from types import SimpleNamespace
        target = self._base_target()
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        # No times_local → use timedelta arithmetic
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=self._base_constraints(),
            night_start=datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc),
            night_end=datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc),
            lat=45.0, lon=-75.0,
            az_values=np.array([90.0, 120.0, 150.0, 180.0]),
            lst_hours=None,
            times_local=None,  # Forces the fallback code path
        )
        assert result is not None
        obs = result['observation']
        assert obs['rise_time'] is not None
        assert obs['set_time'] is not None

    def test_sqm_applies_light_pollution_factor(self):
        """Covers the sqm branch in compute_astro_score via _compute_target_result."""
        from types import SimpleNamespace
        target = self._base_target()
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(),
            moon=moon,
            constraints=self._base_constraints(),
            night_start=datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc),
            night_end=datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc),
            lat=45.0, lon=-75.0,
            az_values=np.array([90.0, 120.0, 150.0, 180.0]),
            sqm=21.5,  # Triggers the sqm branch in compute_astro_score
        )
        assert result is not None
        assert 0.0 <= result['astro_score'] <= 1.0


class TestComputeBodyResultEdgeCases:
    """Cover uncovered branches in _compute_body_result."""

    def _base_body_target(self, name='Jupiter', obj_type='Planet'):
        from types import SimpleNamespace
        return SimpleNamespace(
            target_id=f'body-{name.lower()}',
            preferred_name=name,
            catalogue_names={'Bodies': name},
            category='bodies',
            object_type=obj_type,
            magnitude=-2.0,
            source_catalogues=['Bodies'],
            metadata={},
        )

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    @patch('skytonight.skytonight_calculator._antimeridian_transit_time')
    @patch('skytonight.skytonight_calculator._meridian_transit_time')
    def test_body_result_with_north_to_east_ccw(self, mock_mer, mock_antimer, mock_series):
        """Covers north_to_east_ccw branch for body azimuth."""
        mock_series.return_value = (
            np.array([25.0, 40.0, 35.0]),
            np.array([90.0, 120.0, 150.0]),
            5.0, 20.0,
        )
        mock_mer.return_value = '22:00'
        mock_antimer.return_value = '04:00'
        target = self._base_body_target()
        from types import SimpleNamespace
        moon = SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object(), object(), object()],
            location=object(),
            moon=moon,
            constraints={'altitude_constraint_min': 20, 'airmass_constraint': 2.0, 'north_to_east_ccw': True},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is not None
        # CCW azimuth: peak at idx 1 → az_cw=120 → CCW = (360-120)%360 = 240
        assert result['observation']['azimuth'] == 240.0

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    def test_body_result_returns_none_when_series_raises(self, mock_series):
        """Covers exception path in _compute_body_result."""
        mock_series.side_effect = RuntimeError('ephemeris broken')
        target = self._base_body_target()
        from types import SimpleNamespace
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object()],
            location=object(),
            moon=moon,
            constraints={'altitude_constraint_min': 20, 'airmass_constraint': 2.0},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is None
        assert alt is None
        assert az is None

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    @patch('skytonight.skytonight_calculator._antimeridian_transit_time')
    @patch('skytonight.skytonight_calculator._meridian_transit_time')
    def test_body_result_moon_always_included_below_alt(self, mock_mer, mock_antimer, mock_series):
        """Covers is_moon always-included logic."""
        # Moon alt below alt_min all night → but still returned
        mock_series.return_value = (
            np.array([5.0, 8.0, 3.0]),   # all below alt_min=20
            np.array([90.0, 120.0, 150.0]),
            5.0, 20.0,
        )
        mock_mer.return_value = None
        mock_antimer.return_value = None
        target = self._base_body_target('Moon', 'Moon')
        from types import SimpleNamespace
        moon = SimpleNamespace(phase=0.05, ra_deg=None, dec_deg=None)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object(), object(), object()],
            location=object(),
            moon=moon,
            constraints={'altitude_constraint_min': 20, 'airmass_constraint': 2.0},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is not None  # Moon always returned

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    @patch('skytonight.skytonight_calculator._antimeridian_transit_time')
    @patch('skytonight.skytonight_calculator._meridian_transit_time')
    @patch('skytonight.skytonight_calculator.get_body')
    def test_body_result_opposition_detected(self, mock_get_body, mock_mer, mock_antimer, mock_series):
        """Covers is_opposition detection branch and solar elongation."""
        from types import SimpleNamespace as NS
        mock_series.return_value = (
            np.array([50.0, 60.0, 55.0]),
            np.array([90.0, 120.0, 150.0]),
            12.0, -10.0,
        )
        mock_mer.return_value = '22:00'
        mock_antimer.return_value = '04:00'
        # Sun at opposite direction: ra ≈ 0 degrees vs target at 12h*15=180 degrees → ~180° separation
        sun_coord = NS(ra=NS(deg=0.0), dec=NS(deg=0.0))
        mock_get_body.return_value = sun_coord

        target = self._base_body_target('Mars', 'Planet')
        moon = NS(phase=0.2, ra_deg=10.0, dec_deg=5.0)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object(), object(), object()],
            location=object(),
            moon=moon,
            constraints={'altitude_constraint_min': 20, 'airmass_constraint': 2.0},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is not None
        assert result['solar_elongation_deg'] is not None

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    def test_body_result_returns_none_for_too_few_steps(self, mock_series):
        """Covers early return when total_steps < _MIN_STEPS."""
        mock_series.return_value = (
            np.array([50.0]),   # Only 1 step
            np.array([90.0]),
            5.0, 20.0,
        )
        target = self._base_body_target()
        from types import SimpleNamespace
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object()],
            location=object(),
            moon=moon,
            constraints={'altitude_constraint_min': 20, 'airmass_constraint': 2.0},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is None

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    @patch('skytonight.skytonight_calculator._antimeridian_transit_time')
    @patch('skytonight.skytonight_calculator._meridian_transit_time')
    def test_body_result_with_horizon_profile(self, mock_mer, mock_antimer, mock_series):
        """Covers horizon_profile branch in _compute_body_result."""
        mock_series.return_value = (
            np.array([50.0, 60.0, 55.0]),
            np.array([90.0, 120.0, 150.0]),
            5.0, 20.0,
        )
        mock_mer.return_value = '22:00'
        mock_antimer.return_value = '04:00'
        target = self._base_body_target()
        from types import SimpleNamespace
        moon = SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object(), object(), object()],
            location=object(),
            moon=moon,
            constraints={
                'altitude_constraint_min': 20,
                'airmass_constraint': 2.0,
                'horizon_profile': [{'az': 0.0, 'alt': 10.0}, {'az': 180.0, 'alt': 10.0}],
            },
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is not None


class TestCleanupCalculationMemory:
    """Cover _cleanup_calculation_memory."""

    def test_cleanup_clears_all_lists(self):
        a = [1, 2]
        b = [3, 4]
        c = [5]
        d = [6]
        e = [7]
        f = [8]
        ti = ['2026-01-01']
        tl = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        _cleanup_calculation_memory(
            deep_sky_results=a,
            bodies_results=b,
            comets_results=c,
            skymap_entries=d,
            all_targets=e,
            dso_targets_with_coords=f,
            times_iso_list=ti,
            times_local=tl,
        )
        assert a == []
        assert b == []
        assert ti == []
        assert tl == []

    def test_cleanup_handles_none_optional_lists(self):
        # Should not raise when times_iso_list/times_local are None
        _cleanup_calculation_memory(
            deep_sky_results=[],
            bodies_results=[],
            comets_results=[],
            skymap_entries=[],
            all_targets=[],
            dso_targets_with_coords=[],
            times_iso_list=None,
            times_local=None,
        )


class TestLoadCalculationResults:
    """Cover load_calculation_results."""

    def test_load_calculation_results_merges_files(self):
        meta = {'metadata': {'calculated_at': '2026-01-01', 'counts': {}}}
        dso = {'metadata': {}, 'deep_sky': [{'target_id': 'ngc1'}]}
        bodies = {'metadata': {}, 'bodies': [{'target_id': 'jupiter'}]}
        comets = {'metadata': {}, 'comets': []}
        with patch('skytonight.skytonight_calculator.load_json_file', side_effect=[meta, dso, bodies, comets]):
            result = load_calculation_results()
        assert result['metadata']['calculated_at'] == '2026-01-01'
        assert result['deep_sky'] == [{'target_id': 'ngc1'}]
        assert result['bodies'] == [{'target_id': 'jupiter'}]
        assert result['comets'] == []

    def test_load_calculation_results_falls_back_to_dso_metadata(self):
        # Summary file has no metadata → should fall back to dso_file metadata
        meta = {}
        dso = {'metadata': {'from': 'dso'}, 'deep_sky': []}
        bodies = {'metadata': {}, 'bodies': []}
        comets = {'metadata': {}, 'comets': []}
        with patch('skytonight.skytonight_calculator.load_json_file', side_effect=[meta, dso, bodies, comets]):
            result = load_calculation_results()
        assert result['metadata'] == {'from': 'dso'}


class TestRunCalculationsNoNight:
    """Cover run_calculations when _get_night_window returns None."""

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.load_config')
    @patch('skytonight.skytonight_calculator._get_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator.save_json_file')
    def test_run_calculations_no_night_returns_no_night_found(
        self, mock_save, mock_night, mock_config, mock_dirs
    ):
        mock_config.return_value = {
            'location': {'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC'},
            'skytonight': {},
        }
        result = run_calculations()
        assert result['night_found'] is False
        assert result['counts'] == {'deep_sky': 0, 'bodies': 0, 'comets': 0}
        # Should have saved 4 empty files (bodies, comets, dso, main)
        assert mock_save.call_count >= 4


class TestRunCalculationsWithData:
    """Cover run_calculations with a minimal dataset."""

    def _make_dso_target(self):
        from skytonight.skytonight_models import SkyTonightTarget, SkyTonightCoordinates
        return SkyTonightTarget(
            target_id='dso-1',
            category='deep_sky',
            object_type='Galaxy',
            preferred_name='Test Galaxy',
            catalogue_names={'OpenNGC': 'Test Galaxy'},
            constellation='Orion',
            magnitude=8.0,
            size_arcmin=30.0,
            coordinates=SkyTonightCoordinates(ra_hours=5.5, dec_degrees=45.0),
            source_catalogues=['OpenNGC'],
        )

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.save_json_file')
    @patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator._clear_alttime_files')
    @patch('skytonight.skytonight_calculator._MoonInfo')
    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator._sample_times')
    @patch('skytonight.skytonight_calculator._get_night_window')
    @patch('skytonight.skytonight_calculator.load_targets_dataset')
    @patch('skytonight.skytonight_calculator.load_config')
    def test_run_calculations_with_empty_dataset(
        self, mock_config, mock_dataset, mock_night, mock_times,
        mock_location, mock_moon, mock_clear, mock_astro, mock_save, mock_dirs
    ):
        """Cover run_calculations through the no-targets path."""
        from types import SimpleNamespace

        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)

        mock_config.return_value = {
            'location': {'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC'},
            'skytonight': {},
        }
        mock_dataset.return_value = {'targets': [], 'lookup': {}}
        mock_night.return_value = (night_start, night_end)

        mock_times_obj = MagicMock()
        mock_times_obj.__len__ = MagicMock(return_value=33)
        mock_times_obj.sidereal_time.return_value = MagicMock(hour=np.zeros(33))
        mock_times_obj.to_datetime.return_value = [
            night_start + timedelta(minutes=i * 15) for i in range(33)
        ]
        mock_times.return_value = mock_times_obj

        moon_inst = SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0)
        mock_moon.return_value = moon_inst

        result = run_calculations()
        assert result['night_found'] is True
        assert result['counts'] == {'deep_sky': 0, 'bodies': 0, 'comets': 0}

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.save_json_file')
    @patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator._clear_alttime_files')
    @patch('skytonight.skytonight_calculator._MoonInfo')
    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator._sample_times')
    @patch('skytonight.skytonight_calculator._get_night_window')
    @patch('skytonight.skytonight_calculator.load_targets_dataset')
    @patch('skytonight.skytonight_calculator.load_config')
    def test_run_calculations_with_sqm_from_bortle(
        self, mock_config, mock_dataset, mock_night, mock_times,
        mock_location, mock_moon, mock_clear, mock_astro, mock_save, mock_dirs
    ):
        """Cover the sqm/bortle derivation path."""
        from types import SimpleNamespace

        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)

        mock_config.return_value = {
            'location': {
                'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC',
                'bortle': 5,  # triggers the bortle → sqm path
            },
            'skytonight': {},
        }
        mock_dataset.return_value = {'targets': [], 'lookup': {}}
        mock_night.return_value = (night_start, night_end)

        mock_times_obj = MagicMock()
        mock_times_obj.__len__ = MagicMock(return_value=2)
        mock_times_obj.sidereal_time.return_value = MagicMock(hour=np.zeros(2))
        mock_times_obj.to_datetime.return_value = [night_start, night_end]
        mock_times.return_value = mock_times_obj

        moon_inst = SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0)
        mock_moon.return_value = moon_inst

        result = run_calculations()
        assert result['night_found'] is True

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.save_json_file')
    @patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator._clear_alttime_files')
    @patch('skytonight.skytonight_calculator._compute_body_result')
    @patch('skytonight.skytonight_calculator._MoonInfo')
    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator._sample_times')
    @patch('skytonight.skytonight_calculator._get_night_window')
    @patch('skytonight.skytonight_calculator.load_targets_dataset')
    @patch('skytonight.skytonight_calculator.load_config')
    def test_run_calculations_with_body_target(
        self, mock_config, mock_dataset, mock_night, mock_times,
        mock_location, mock_moon, mock_body_result, mock_clear, mock_astro, mock_save, mock_dirs
    ):
        """Cover the bodies loop in run_calculations."""
        from types import SimpleNamespace

        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)

        mock_config.return_value = {
            'location': {'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC'},
            'skytonight': {},
        }
        body = self._make_body_target()
        mock_dataset.return_value = {'targets': [body], 'lookup': {}}
        mock_night.return_value = (night_start, night_end)

        mock_times_obj = MagicMock()
        mock_times_obj.__len__ = MagicMock(return_value=2)
        mock_times_obj.sidereal_time.return_value = MagicMock(hour=np.zeros(2))
        mock_times_obj.to_datetime.return_value = [night_start, night_end]
        mock_times.return_value = mock_times_obj

        moon_inst = SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0)
        mock_moon.return_value = moon_inst

        alt_arr = np.array([35.0, 45.0])
        az_arr = np.array([90.0, 120.0])
        body_result_dict = {
            'target_id': 'body-jupiter',
            'preferred_name': 'Jupiter',
            'astro_score': 0.7,
            'object_type': 'Planet',
            'constellation': '',
        }
        mock_body_result.return_value = (body_result_dict, alt_arr, az_arr)

        result = run_calculations()
        assert result['night_found'] is True
        assert result['counts']['bodies'] == 1

    def _make_body_target(self):
        from skytonight.skytonight_models import SkyTonightTarget
        return SkyTonightTarget(
            target_id='body-jupiter',
            category='bodies',
            object_type='Planet',
            preferred_name='Jupiter',
            catalogue_names={'Bodies': 'Jupiter'},
            source_catalogues=['Bodies'],
            metadata={'source': 'builtin-solar-system'},
        )


class TestComputeAstroScoreWithSqm:
    """Cover the sqm branch in compute_astro_score."""

    def test_sqm_branch_with_known_object_type(self):
        """Covers sqm + object_type → object_lp_factor call."""
        with patch('weather.sky_quality.object_lp_factor', return_value=0.8) as mock_lp:
            score = compute_astro_score(
                max_altitude=60.0,
                observable_hours=4.0,
                meridian_altitude=55.0,
                moon_phase=0.2,
                angular_distance_moon=90.0,
                magnitude=8.0,
                size_arcmin=20.0,
                observable_hours_in_window=4.0,
                window_start_hour=22,
                is_messier=False,
                is_planet=False,
                is_opposition=False,
                sqm=20.5,
                object_type='Galaxy',
            )
            assert 0.0 <= score <= 1.0
            mock_lp.assert_called_once()


class TestComputeAstroScoreTimeBonusBranches:
    """Cover the remaining time_bonus branches in compute_astro_score."""

    def test_time_bonus_early_morning_window(self):
        """Covers the 1 < window_start_hour <= 3 branch."""
        score = compute_astro_score(
            max_altitude=50.0,
            observable_hours=3.0,
            meridian_altitude=45.0,
            moon_phase=0.1,
            angular_distance_moon=120.0,
            magnitude=9.0,
            size_arcmin=15.0,
            observable_hours_in_window=3.0,
            window_start_hour=2,  # triggers 0.5 time_bonus
            is_messier=False,
            is_planet=False,
            is_opposition=False,
        )
        assert 0.0 <= score <= 1.0

    def test_time_bonus_daytime_window(self):
        """Covers the else branch (time_bonus=0) when window_start_hour is 4-20."""
        score = compute_astro_score(
            max_altitude=50.0,
            observable_hours=3.0,
            meridian_altitude=45.0,
            moon_phase=0.1,
            angular_distance_moon=120.0,
            magnitude=9.0,
            size_arcmin=15.0,
            observable_hours_in_window=3.0,
            window_start_hour=10,  # triggers time_bonus=0.0
            is_messier=False,
            is_planet=False,
            is_opposition=False,
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Targeted branch coverage additions
# ---------------------------------------------------------------------------


class TestComputeTargetResultWindowStartHourFallback:
    """window_start_hour = night_start.hour when first_obs_idx is None."""

    def test_no_observable_steps_sets_window_start_to_night_start(self):
        """alt_max < alt_min → no obs steps; frac_threshold=0 bypasses early return."""
        target = SimpleNamespace(
            target_id='m42', preferred_name='M42', catalogue_names={'Messier': 'M42'},
            category='deep_sky', object_type='nebula', constellation='Orion',
            magnitude=4.0, size_arcmin=65.0,
            coordinates=SimpleNamespace(ra_hours=5.58, dec_degrees=-5.39),
            source_catalogues=['Messier'], metadata={},
        )
        constraints = {
            'altitude_constraint_min': 60,
            'altitude_constraint_max': 10,  # alt_max < alt_min → in_window_mask all False
            'fraction_of_time_observable_threshold': 0,  # bypass fraction check
            'moon_separation_min': 45,
            'size_constraint_min': 5,
            'size_constraint_max': 300,
            'moon_separation_use_illumination': False,
            'airmass_constraint': 2.0,
        }
        altaz_values = np.array([65.0, 70.0, 68.0, 66.0, 65.0])
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=altaz_values,
            location=object(),
            moon=moon,
            constraints=constraints,
            night_start=night_start,
            night_end=night_end,
            lat=45.0, lon=-75.0,
        )
        # Must not raise; result may be None or a dict
        assert result is None or isinstance(result, dict)


class TestRunCalculationsSqmBortle:
    """Cover exception branches for sqm/bortle parsing in run_calculations."""

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.load_config')
    @patch('skytonight.skytonight_calculator._get_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator.save_json_file')
    def test_sqm_bad_value_is_swallowed(self, mock_save, mock_night, mock_config, mock_dirs):
        """sqm='bad' triggers TypeError/ValueError, swallowed by except."""
        mock_config.return_value = {
            'location': {
                'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC',
                'sqm': 'notAFloat',
            },
            'skytonight': {},
        }
        result = run_calculations()
        assert result['night_found'] is False

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.load_config')
    @patch('skytonight.skytonight_calculator._get_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator.save_json_file')
    def test_bortle_bad_value_is_swallowed(self, mock_save, mock_night, mock_config, mock_dirs):
        """bortle='bad' (with no sqm) triggers except in bortle branch."""
        mock_config.return_value = {
            'location': {
                'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC',
                'bortle': 'notInt',
            },
            'skytonight': {},
        }
        result = run_calculations()
        assert result['night_found'] is False


class TestRunCalculationsDictTargetFromDictException:
    """dict-based target that fails from_dict is silently skipped."""

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.save_json_file')
    @patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator._clear_alttime_files')
    @patch('skytonight.skytonight_calculator._MoonInfo')
    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator._sample_times')
    @patch('skytonight.skytonight_calculator._get_night_window')
    @patch('skytonight.skytonight_calculator.load_targets_dataset')
    @patch('skytonight.skytonight_calculator.load_config')
    def test_dict_target_from_dict_exception_is_skipped(
        self, mock_config, mock_dataset, mock_night, mock_times,
        mock_location, mock_moon, mock_clear, mock_astro, mock_save, mock_dirs
    ):
        """Dataset contains a malformed dict target → from_dict raises, target is skipped."""
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        mock_config.return_value = {
            'location': {'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC'},
            'skytonight': {},
        }
        # Provide a bad dict that cannot be converted to SkyTonightTarget
        mock_dataset.return_value = {
            'targets': [{'this_key_does_not_exist': True}],
            'lookup': {},
        }
        mock_night.return_value = (night_start, night_end)
        mock_times.return_value = MagicMock()
        mock_moon.return_value = SimpleNamespace(phase=0.5, ra_deg=None, dec_deg=None)
        mock_location.return_value = object()
        result = run_calculations()
        # Should complete without error; no targets processed
        assert result is not None


class TestRunCalculationsCometAltazException:
    """comet altaz computation exception causes continue."""

    @patch('skytonight.skytonight_calculator.ensure_skytonight_directories')
    @patch('skytonight.skytonight_calculator.save_json_file')
    @patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None)
    @patch('skytonight.skytonight_calculator._clear_alttime_files')
    @patch('skytonight.skytonight_calculator._MoonInfo')
    @patch('skytonight.skytonight_calculator.EarthLocation')
    @patch('skytonight.skytonight_calculator._sample_times')
    @patch('skytonight.skytonight_calculator._get_night_window')
    @patch('skytonight.skytonight_calculator.load_targets_dataset')
    @patch('skytonight.skytonight_calculator.load_config')
    def test_comet_altaz_exception_is_swallowed(
        self, mock_config, mock_dataset, mock_night, mock_times,
        mock_location, mock_moon, mock_clear, mock_astro, mock_save, mock_dirs
    ):
        """Comet with bad coords: _compute_altaz_series raises, target is skipped."""
        from skytonight.skytonight_models import SkyTonightTarget, SkyTonightCoordinates
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        comet = SkyTonightTarget(
            target_id='comet-1',
            category='comets',
            object_type='Comet',
            preferred_name='Comet Test',
            catalogue_names={},
            source_catalogues=['comets'],
            coordinates=SkyTonightCoordinates(ra_hours=6.0, dec_degrees=20.0),
        )
        mock_config.return_value = {
            'location': {'latitude': 45.0, 'longitude': -75.0, 'timezone': 'UTC'},
            'skytonight': {},
        }
        mock_dataset.return_value = {'targets': [comet], 'lookup': {}}
        mock_night.return_value = (night_start, night_end)
        mock_times.return_value = MagicMock()
        mock_moon.return_value = SimpleNamespace(phase=0.5, ra_deg=None, dec_deg=None)
        mock_location.return_value = object()
        with patch('skytonight.skytonight_calculator._compute_altaz_series',
                   side_effect=RuntimeError('altaz failed for comet')):
            result = run_calculations()
        assert result is not None


class TestBodyAliasMapBranchCoverage:
    """: branches in _build_body_alias_map."""

    def setup_method(self):
        calc._body_alias_map_cache = None

    def test_non_string_localized_name_is_skipped(self):
        """continue when localized_name is not a str or is empty."""
        with patch('utils.i18n_utils.I18nManager') as MockI18n:
            mock_mgr = MagicMock()
            # Return a namespace where some values are non-str or empty
            mock_mgr.get_namespace.return_value = {
                'moon': 123,         # non-str → skip
                'sun': '',           # empty str → skip
                'mars': '  ',        # whitespace only → skip
                'jupiter': 'Jupiter',  # valid
            }
            MockI18n.return_value = mock_mgr
            result = _build_body_alias_map()
        assert isinstance(result, dict)

    def test_get_namespace_exception_is_swallowed(self):
        """exception from get_namespace is swallowed per lang."""
        with patch('utils.i18n_utils.I18nManager') as MockI18n:
            mock_mgr = MagicMock()
            mock_mgr.get_namespace.side_effect = Exception('i18n broken')
            MockI18n.return_value = mock_mgr
            result = _build_body_alias_map()
        # Should return empty dict without raising
        assert isinstance(result, dict)


class TestComputeTargetDebugExtraBranches:
    """Cover additional branches in compute_target_debug."""

    def _run_with_dataset(self, dataset, name, config_overrides=None):
        config = {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'elevation': 100.0, 'timezone': 'UTC'},
            'skytonight': {'constraints': {
                'altitude_constraint_min': 30,
                'altitude_constraint_max': 80,
                'airmass_constraint': 2.0,
                'size_constraint_min': 10,
                'size_constraint_max': 300,
                'moon_separation_min': 45,
                'fraction_of_time_observable_threshold': 0.5,
                'moon_separation_use_illumination': False,
                'horizon_profile': [],
                **(config_overrides or {}),
            }},
        }
        return compute_target_debug(name, config=config)

    def test_lookup_fallback_iteration_matches_custom_prefix(self):
        """ + 1617→1616: lookup key with custom prefix found via iteration."""
        target = _debug_dso()
        norm = normalize_object_name(target.preferred_name)
        dataset = {
            'targets': [target],
            # Use a non-standard prefix so preferred:: and alias:: lookups miss.
            # Include a non-matching entry FIRST so the loop continues (1617→1616 branch)
            'lookup': {
                'other::some_other_name': {'target_id': 'other'},  # won't match → loop continues
                f'custom::{norm}': {'target_id': target.target_id},  # matches → break
            },
        }
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        alt_arr = np.array([35.0, 45.0, 60.0, 55.0, 40.0])
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window', return_value=(night_start, night_end)), \
             patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None), \
             patch('skytonight.skytonight_calculator.EarthLocation'), \
             patch('skytonight.skytonight_calculator._MoonInfo',
                   return_value=SimpleNamespace(phase=0.2, ra_deg=100.0, dec_deg=-10.0)), \
             patch('skytonight.skytonight_calculator._sample_times', return_value=MagicMock(
                 to_datetime=lambda **kw: [night_start + timedelta(minutes=i * 15) for i in range(5)])), \
             patch('skytonight.skytonight_calculator._compute_altaz_series', return_value=(alt_arr, alt_arr)):
            result = self._run_with_dataset(dataset, target.preferred_name)
        assert result['found'] is True

    def test_lookup_entry_target_id_not_in_all_targets_returns_not_found(self):
        """entry points to a target_id that doesn't match any target in all_targets."""
        dataset = {
            'targets': [],  # empty — no target with target_id 'missing-target'
            'lookup': {'preferred::ngc224': {'target_id': 'missing-target'}},
        }
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window',
                   return_value=(
                       datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc),
                       datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc),
                   )):
            result = self._run_with_dataset(dataset, 'NGC 224')
        assert result == {'found': False}

    def test_altaz_computation_exception_returns_error(self):
        """altaz computation exception returns found=True with overall='error'."""
        target = _debug_dso()
        dataset = _debug_dataset(target)
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window', return_value=(night_start, night_end)), \
             patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None), \
             patch('skytonight.skytonight_calculator.EarthLocation'), \
             patch('skytonight.skytonight_calculator._MoonInfo',
                   return_value=SimpleNamespace(phase=0.2, ra_deg=None, dec_deg=None)), \
             patch('skytonight.skytonight_calculator._sample_times', return_value=MagicMock()), \
             patch('skytonight.skytonight_calculator._compute_altaz_series',
                   side_effect=RuntimeError('altaz boom')):
            result = self._run_with_dataset(dataset, target.preferred_name)
        assert result['found'] is True
        assert result['overall'] == 'error'

    def test_dso_without_size_data_skips_size_filter(self):
        """DSO with size_arcmin=None gets 'No size data, filter skipped' check."""
        target = _debug_dso(size_arcmin=None)
        dataset = _debug_dataset(target)
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        alt_arr = np.array([35.0, 45.0, 60.0, 55.0, 40.0])
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window', return_value=(night_start, night_end)), \
             patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None), \
             patch('skytonight.skytonight_calculator.EarthLocation'), \
             patch('skytonight.skytonight_calculator._MoonInfo',
                   return_value=SimpleNamespace(phase=0.2, ra_deg=100.0, dec_deg=-10.0)), \
             patch('skytonight.skytonight_calculator._sample_times', return_value=MagicMock(
                 to_datetime=lambda **kw: [night_start + timedelta(minutes=i * 15) for i in range(5)])), \
             patch('skytonight.skytonight_calculator._compute_altaz_series', return_value=(alt_arr, alt_arr)):
            result = self._run_with_dataset(dataset, target.preferred_name)
        assert result['found'] is True
        check_names = [c['name'] for c in result.get('checks', [])]
        assert 'size_min' in check_names
        size_check = next(c for c in result['checks'] if c['name'] == 'size_min')
        assert size_check.get('note') == 'No size data, filter skipped'

    def test_moon_use_illum_true_uses_phase_for_threshold(self):
        """moon_use_illum=True sets effective_min_sep to moon.phase * 100."""
        target = _debug_dso()
        dataset = _debug_dataset(target)
        night_start = datetime(2026, 4, 17, 21, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        alt_arr = np.array([35.0, 45.0, 60.0, 55.0, 40.0])
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window', return_value=(night_start, night_end)), \
             patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None), \
             patch('skytonight.skytonight_calculator.EarthLocation'), \
             patch('skytonight.skytonight_calculator._MoonInfo',
                   return_value=SimpleNamespace(phase=0.8, ra_deg=100.0, dec_deg=-10.0)), \
             patch('skytonight.skytonight_calculator._sample_times', return_value=MagicMock(
                 to_datetime=lambda **kw: [night_start + timedelta(minutes=i * 15) for i in range(5)])), \
             patch('skytonight.skytonight_calculator._compute_altaz_series', return_value=(alt_arr, alt_arr)):
            result = self._run_with_dataset(dataset, target.preferred_name,
                                            config_overrides={'moon_separation_use_illumination': True})
        assert result['found'] is True
        moon_check = next((c for c in result.get('checks', []) if c['name'] == 'moon_separation'), None)
        if moon_check:
            # threshold should be moon.phase * 100 = 80.0
            assert abs(moon_check['threshold'] - 80.0) < 1.0


# ---------------------------------------------------------------------------
# airmass_constr < 1.0 in _compute_target_result
# ---------------------------------------------------------------------------

class TestComputeTargetResultAirmassLow:
    """airmass_constr < 1.0 → skip airmass-derived alt floor."""

    def test_airmass_below_1_skips_floor_calculation(self):
        target = SimpleNamespace(
            target_id='m42', preferred_name='M42',
            catalogue_names={'Messier': 'M42'},
            category='deep_sky', object_type='nebula',
            constellation='Orion', magnitude=4.0, size_arcmin=65.0,
            coordinates=SimpleNamespace(ra_hours=5.58, dec_degrees=-5.39),
            source_catalogues=['Messier'], metadata={},
        )
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result = _compute_target_result(
            target=target, times=None,
            altaz_values=np.array([35.0, 45.0, 50.0, 40.0]),
            location=object(), moon=moon,
            constraints={
                'altitude_constraint_min': 20, 'altitude_constraint_max': 80,
                'moon_separation_min': 45, 'size_constraint_min': 5,
                'size_constraint_max': 300,
                'fraction_of_time_observable_threshold': 0.2,
                'moon_separation_use_illumination': False,
                'airmass_constraint': 0.5,
            },
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# max_altitude < alt_min when fraction check is bypassed
# ---------------------------------------------------------------------------

class TestComputeTargetResultMaxAltFilter:
    """max_altitude < alt_min returns None when frac_threshold=0 bypasses ."""

    def test_max_altitude_below_alt_min_returns_none(self):
        target = SimpleNamespace(
            target_id='m42', preferred_name='M42',
            catalogue_names={'Messier': 'M42'},
            category='deep_sky', object_type='nebula',
            constellation='Orion', magnitude=4.0, size_arcmin=65.0,
            coordinates=SimpleNamespace(ra_hours=5.58, dec_degrees=-5.39),
            source_catalogues=['Messier'], metadata={},
        )
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        # frac_threshold=0.0 means fraction check is False → don't return early
        # all altitudes < alt_min=30 → max_altitude=28 < 30 → return None
        result = _compute_target_result(
            target=target, times=None,
            altaz_values=np.array([25.0, 28.0, 27.0, 24.0]),
            location=object(), moon=moon,
            constraints={
                'altitude_constraint_min': 30, 'altitude_constraint_max': 80,
                'moon_separation_min': 45, 'size_constraint_min': 5,
                'size_constraint_max': 300,
                'fraction_of_time_observable_threshold': 0.0,
                'moon_separation_use_illumination': False,
                'airmass_constraint': 2.0,
            },
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is None


# ---------------------------------------------------------------------------
# airmass_constr < 1.0 in _compute_body_result
# ---------------------------------------------------------------------------

class TestComputeBodyResultAirmassLow:
    """airmass_constr < 1.0 → skip airmass-derived alt floor for bodies."""

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    @patch('skytonight.skytonight_calculator._antimeridian_transit_time')
    @patch('skytonight.skytonight_calculator._meridian_transit_time')
    def test_airmass_below_1_skips_floor_calculation(self, mock_mer, mock_antimer, mock_series):
        mock_series.return_value = (
            np.array([35.0, 45.0, 55.0, 50.0, 40.0]),
            np.array([100.0, 110.0, 120.0, 130.0, 140.0]),
            5.0, 20.0,
        )
        mock_mer.return_value = '22:00'
        mock_antimer.return_value = '04:00'
        target = SimpleNamespace(
            target_id='body-jupiter', preferred_name='Jupiter',
            catalogue_names={'Bodies': 'Jupiter'},
            category='bodies', object_type='Planet',
            magnitude=-2.0, source_catalogues=['Bodies'], metadata={},
        )
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object()] * 5,
            location=object(), moon=moon,
            constraints={
                'altitude_constraint_min': 20,
                'airmass_constraint': 0.5,
                'north_to_east_ccw': False,
            },
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is not None


# ---------------------------------------------------------------------------
#  in run_calculations
# ---------------------------------------------------------------------------

class TestRunCalculationsMiscBranches:
    """Cover non-dict/non-target skip and body with None altitudes."""

    def _setup(self, monkeypatch):
        night_start = datetime(2026, 5, 28, 21, 0, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 5, 28, 22, 0, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(calc, '_get_night_window', lambda *a: (night_start, night_end))
        monkeypatch.setattr(calc, '_get_astro_night_window', lambda *a: None)
        monkeypatch.setattr(calc, '_clear_alttime_files', lambda *_a, **_k: None)
        monkeypatch.setattr(calc, 'save_json_file', lambda *a, **kw: None)
        mock_times = MagicMock()
        mock_times.__len__ = MagicMock(return_value=2)
        mock_times.sidereal_time.return_value = MagicMock(hour=np.zeros(2))
        mock_times.to_datetime.return_value = [night_start, night_end]
        monkeypatch.setattr(calc, '_sample_times', lambda *a: mock_times)
        monkeypatch.setattr(calc, '_MoonInfo',
                            lambda *a: SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0))
        monkeypatch.setattr(calc, 'EarthLocation', MagicMock())

    _CONFIG = {
        'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC'},
        'skytonight': {'constraints': {}},
    }

    def test_non_dict_non_target_in_dataset_is_skipped(self, monkeypatch):
        """raw is a string (not SkyTonightTarget, not dict) → skip."""
        self._setup(monkeypatch)
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': ['not-a-target'], 'lookup': {}})
        result = run_calculations(self._CONFIG)
        assert result['counts'] == {'deep_sky': 0, 'bodies': 0, 'comets': 0}

    def test_malformed_dict_in_dataset_is_skipped(self, monkeypatch):
        """from_dict raises ValueError for invalid magnitude → except+pass."""
        self._setup(monkeypatch)
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [{'magnitude': 'bad'}], 'lookup': {}})
        result = run_calculations(self._CONFIG)
        assert result['counts'] == {'deep_sky': 0, 'bodies': 0, 'comets': 0}

    def test_body_with_none_alt_skips_skymap_and_alttime(self, monkeypatch):
        """_compute_body_result returns (result, None, None)."""
        self._setup(monkeypatch)
        from skytonight.skytonight_models import SkyTonightTarget as ST
        body = ST(
            target_id='body-jupiter', category='bodies', object_type='Planet',
            preferred_name='Jupiter', catalogue_names={'Bodies': 'Jupiter'},
            source_catalogues=['Bodies'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [body], 'lookup': {}})
        body_result_dict = {
            'target_id': 'body-jupiter', 'preferred_name': 'Jupiter',
            'astro_score': 0.7, 'object_type': 'Planet', 'constellation': '',
        }
        monkeypatch.setattr(calc, '_compute_body_result',
                            lambda *a, **kw: (body_result_dict, None, None))
        result = run_calculations(self._CONFIG)
        assert result['counts']['bodies'] == 1


# ---------------------------------------------------------------------------
# normalize_object_name returns '' for a localized planet name
# ---------------------------------------------------------------------------

class TestBuildBodyAliasMapNormFalsy:
    """norm is '' → entry is skipped."""

    def test_empty_norm_skips_entry(self):
        from utils import i18n_utils

        class _FakeI18n:
            def __init__(self, lang):
                pass

            def get_namespace(self, ns):
                if ns == 'planets':
                    return {'moon': '---'}  # '---' → normalize_object_name → ''
                return {}

        orig_cache = calc._body_alias_map_cache
        try:
            calc._body_alias_map_cache = None
            with patch.object(i18n_utils, 'I18nManager', _FakeI18n), \
                 patch.object(i18n_utils, 'SUPPORTED_LANGUAGES', ['en']):
                result = _build_body_alias_map()
        finally:
            calc._body_alias_map_cache = orig_cache

        assert '' not in result


# ---------------------------------------------------------------------------
# compute_target_debug with config=None calls load_config()
# airmass_constraint < 1.0 → skip effective_alt_min update
# astro_night_start/end not None → written to alttime
# ---------------------------------------------------------------------------

class TestComputeTargetDebugExtraCoverage:
    """Cover the remaining missed branches/lines in compute_target_debug."""

    def test_config_none_calls_load_config(self, monkeypatch):
        """config=None → load_config() is called to get the config."""
        monkeypatch.setattr(calc, 'load_config', lambda: {
            'location': {'latitude': 48.0, 'longitude': 2.0, 'elevation': 100.0, 'timezone': 'UTC'},
            'skytonight': {'constraints': {}},
        })
        with patch('skytonight.skytonight_calculator.load_targets_dataset',
                   return_value={'targets': [], 'lookup': {}}):
            result = compute_target_debug('UnknownXYZ', config=None)
        assert result == {'found': False}

    def test_airmass_below_1_skips_floor_update(self):
        """airmass < 1.0 → effective_alt_min stays at alt_min."""
        target = _debug_dso()
        config = _debug_config(airmass_constraint=0.5)
        dataset = _debug_dataset(target)
        alt_arr = np.array([35.0, 45.0, 60.0, 55.0, 40.0])
        az_arr = np.array([100.0, 120.0, 150.0, 180.0, 200.0])
        mock_times = MagicMock()
        mock_times.to_datetime.return_value = [
            _DEBUG_NIGHT_START + timedelta(minutes=i * 15) for i in range(5)
        ]
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window',
                   return_value=(_DEBUG_NIGHT_START, _DEBUG_NIGHT_END)), \
             patch('skytonight.skytonight_calculator._get_astro_night_window', return_value=None), \
             patch('skytonight.skytonight_calculator.EarthLocation'), \
             patch('skytonight.skytonight_calculator._MoonInfo',
                   return_value=SimpleNamespace(phase=0.2, ra_deg=100.0, dec_deg=-10.0)), \
             patch('skytonight.skytonight_calculator._sample_times', return_value=mock_times), \
             patch('skytonight.skytonight_calculator._compute_altaz_series', return_value=(alt_arr, az_arr)):
            result = compute_target_debug(target.preferred_name, config=config)
        assert result['found'] is True
        # effective_alt_min should equal alt_min (30) because airmass < 1.0 skips the update
        assert result['constraints']['effective_alt_min'] == 30.0

    def test_astro_night_start_end_included_in_alttime(self):
        """astro window non-None → alttime includes night_astro_start/end."""
        target = _debug_dso()
        config = _debug_config()
        dataset = _debug_dataset(target)
        night_start = _DEBUG_NIGHT_START
        night_end = _DEBUG_NIGHT_END
        astro_start = night_start + timedelta(minutes=30)
        astro_end = night_end - timedelta(minutes=30)
        alt_arr = np.array([35.0, 45.0, 60.0, 55.0, 40.0])
        az_arr = np.array([100.0, 120.0, 150.0, 180.0, 200.0])
        mock_times = MagicMock()
        mock_times.to_datetime.return_value = [
            night_start + timedelta(minutes=i * 15) for i in range(5)
        ]
        with patch('skytonight.skytonight_calculator.load_targets_dataset', return_value=dataset), \
             patch('skytonight.skytonight_calculator._get_night_window',
                   return_value=(night_start, night_end)), \
             patch('skytonight.skytonight_calculator._get_astro_night_window',
                   return_value=(astro_start, astro_end)), \
             patch('skytonight.skytonight_calculator.EarthLocation'), \
             patch('skytonight.skytonight_calculator._MoonInfo',
                   return_value=SimpleNamespace(phase=0.2, ra_deg=100.0, dec_deg=-10.0)), \
             patch('skytonight.skytonight_calculator._sample_times', return_value=mock_times), \
             patch('skytonight.skytonight_calculator._compute_altaz_series', return_value=(alt_arr, az_arr)):
            result = compute_target_debug(target.preferred_name, config=config)
        assert result['found'] is True
        assert 'night_astro_start' in result['alttime']
        assert 'night_astro_end' in result['alttime']


# ---------------------------------------------------------------------------
# _compute_altaz_series body (needs real astropy call to cover)
# _compute_body_altaz_series body
# ---------------------------------------------------------------------------


class TestAltazSeriesFunctions:
    """Cover the bodies of _compute_altaz_series and _compute_body_altaz_series."""

    def test_compute_altaz_series_calls_skycoord_altaz(self):
        """SkyCoord + AltAz transform path."""
        mock_altaz = MagicMock()
        mock_altaz.alt.deg = np.array([30.0, 40.0, 50.0])
        mock_altaz.az.deg = np.array([100.0, 110.0, 120.0])
        mock_coord = MagicMock()
        mock_coord.transform_to.return_value = mock_altaz

        with patch.object(calc, 'SkyCoord', return_value=mock_coord), \
             patch.object(calc, 'AltAz', return_value=MagicMock()):
            alt, az = calc._compute_altaz_series(5.0, 30.0, MagicMock(), MagicMock())

        np.testing.assert_array_equal(alt, np.array([30.0, 40.0, 50.0]))
        np.testing.assert_array_equal(az, np.array([100.0, 110.0, 120.0]))

    def test_compute_body_altaz_series_calls_get_body(self):
        """get_body + AltAz transform path."""
        times = MagicMock()
        times.__len__ = MagicMock(return_value=3)

        mock_altaz = MagicMock()
        mock_altaz.alt.deg = np.array([35.0, 45.0, 55.0])
        mock_altaz.az.deg = np.array([180.0, 190.0, 200.0])

        mock_mid_coord = MagicMock()
        mock_mid_coord.ra.hour = 6.0
        mock_mid_coord.dec.deg = 22.0

        mock_body_coord = MagicMock()
        mock_body_coord.transform_to.return_value = mock_altaz

        with patch.object(calc, 'AltAz', return_value=MagicMock()), \
             patch.object(calc, 'get_body', side_effect=lambda n, t, loc: mock_body_coord if t is times else mock_mid_coord):
            # Patch times indexing for mid_coord lookup
            times.__getitem__ = MagicMock(return_value=MagicMock())
            mock_body_coord.transform_to.return_value = mock_altaz
            mid_body = MagicMock()
            mid_body.ra.hour = 6.0
            mid_body.dec.deg = 22.0

            def _get_body(name, t, loc):
                if t is times:
                    return mock_body_coord
                return mid_body

            with patch.object(calc, 'get_body', side_effect=_get_body):
                alt, az, ra_mid, dec_mid = calc._compute_body_altaz_series('Jupiter', times, MagicMock())

        np.testing.assert_array_equal(alt, np.array([35.0, 45.0, 55.0]))
        assert isinstance(ra_mid, float)


# ---------------------------------------------------------------------------
# _compute_target_result with non-deep_sky target
# ---------------------------------------------------------------------------


class TestComputeTargetResultNonDSO:
    """Cover category != 'deep_sky' skips size filter."""

    def test_bodies_target_skips_size_filter(self):
        target = SimpleNamespace(
            target_id='body-jupiter', preferred_name='Jupiter',
            catalogue_names={'Bodies': 'Jupiter'},
            category='bodies',
            object_type='Planet',
            constellation='Tau',
            magnitude=-2.0,
            size_arcmin=None,
            coordinates=SimpleNamespace(ra_hours=5.0, dec_degrees=22.0),
            source_catalogues=['Bodies'],
            metadata={},
        )
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        constraints = {
            'altitude_constraint_min': 10,
            'altitude_constraint_max': 80,
            'moon_separation_min': 30,
            'size_constraint_min': 5,
            'size_constraint_max': 300,
            'fraction_of_time_observable_threshold': 0.2,
            'moon_separation_use_illumination': False,
            'airmass_constraint': 2.0,
            'north_to_east_ccw': False,
        }
        alt = np.array([30.0, 40.0, 50.0, 45.0], dtype=np.float32)
        az = np.array([100.0, 120.0, 150.0, 180.0], dtype=np.float32)
        lst = np.array([5.0, 5.1, 5.2, 5.3])
        times_local = [
            datetime(2026, 4, 17, 21, i * 15) for i in range(4)
        ]

        result = _compute_target_result(
            target=target,
            times=None,
            altaz_values=alt,
            location=object(),
            moon=moon,
            constraints=constraints,
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
            az_values=az,
            lst_hours=lst,
            times_local=times_local,
        )
        assert result is not None
        assert result['target_id'] == 'body-jupiter'


# ---------------------------------------------------------------------------
# _compute_body_result returns (None, None, None) when fraction < threshold
# ---------------------------------------------------------------------------


class TestComputeBodyResultLowFraction:
    """Cover observable_fraction < _BODIES_MIN_FRACTION → return None."""

    @patch('skytonight.skytonight_calculator._compute_body_altaz_series')
    @patch('skytonight.skytonight_calculator._antimeridian_transit_time')
    @patch('skytonight.skytonight_calculator._meridian_transit_time')
    def test_all_altitudes_below_min_returns_none(self, mock_mer, mock_antimer, mock_series):
        mock_series.return_value = (
            np.array([5.0, 3.0, 2.0, 1.0, 4.0]),  # all below alt_min=30
            np.array([100.0, 110.0, 120.0, 130.0, 140.0]),
            5.0, 20.0,
        )
        mock_mer.return_value = None
        mock_antimer.return_value = None
        target = SimpleNamespace(
            target_id='body-jupiter', preferred_name='Jupiter',
            catalogue_names={'Bodies': 'Jupiter'},
            category='bodies', object_type='Planet',
            magnitude=-2.0, source_catalogues=['Bodies'], metadata={},
        )
        moon = SimpleNamespace(phase=0.1, ra_deg=None, dec_deg=None)
        result, alt, az = _compute_body_result(
            target=target,
            times=[object()] * 5,
            location=object(), moon=moon,
            constraints={'altitude_constraint_min': 30, 'airmass_constraint': 2.0, 'north_to_east_ccw': False},
            night_start=datetime(2026, 4, 17, 21, 0),
            night_end=datetime(2026, 4, 18, 5, 0),
            lat=45.0, lon=-75.0,
        )
        assert result is None
        assert alt is None
        assert az is None


# ---------------------------------------------------------------------------
# body_result is None
# comet result not None → appended and alttime saved
# DSO batch processing (n_dso_batch > 0)
# ---------------------------------------------------------------------------


class TestRunCalcMissingBranches:
    """Cover missing branches in run_calculations: body None, comet result, DSO batch."""

    def _setup(self, monkeypatch):
        night_start = datetime(2026, 5, 28, 21, 0, 0, tzinfo=timezone.utc)
        night_end = datetime(2026, 5, 28, 22, 0, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(calc, 'ensure_skytonight_directories', lambda: None)
        monkeypatch.setattr(calc, '_get_night_window', lambda *a: (night_start, night_end))
        monkeypatch.setattr(calc, '_get_astro_night_window', lambda *a: None)
        monkeypatch.setattr(calc, '_clear_alttime_files', lambda *_a, **_k: None)
        monkeypatch.setattr(calc, 'save_json_file', lambda *a, **kw: None)
        mock_times = MagicMock()
        mock_times.__len__ = MagicMock(return_value=2)
        mock_times.sidereal_time.return_value = MagicMock(hour=np.zeros(2))
        mock_times.to_datetime.return_value = [night_start, night_end]
        monkeypatch.setattr(calc, '_sample_times', lambda *a: mock_times)
        monkeypatch.setattr(calc, '_MoonInfo',
                            lambda *a: SimpleNamespace(phase=0.2, ra_deg=10.0, dec_deg=5.0))
        monkeypatch.setattr(calc, 'EarthLocation', MagicMock())
        return night_start, night_end, mock_times

    _CONFIG = {
        'location': {'latitude': 45.5, 'longitude': -73.5, 'timezone': 'UTC'},
        'skytonight': {'constraints': {}},
    }

    def test_body_result_none_skips_append(self, monkeypatch):
        """_compute_body_result returns (None, None, None) → skip."""
        self._setup(monkeypatch)
        body = SkyTonightTarget(
            target_id='body-jupiter', category='bodies', object_type='Planet',
            preferred_name='Jupiter', catalogue_names={'Bodies': 'Jupiter'},
            source_catalogues=['Bodies'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [body], 'lookup': {}})
        monkeypatch.setattr(calc, '_compute_body_result',
                            lambda *a, **kw: (None, None, None))
        result = run_calculations(self._CONFIG)
        assert result['counts']['bodies'] == 0

    def test_comet_result_not_none_appended(self, monkeypatch):
        """comet with non-None result → appended to comets_results."""
        self._setup(monkeypatch)
        comet = SkyTonightTarget(
            target_id='comet-c2023', category='comets', object_type='comet',
            preferred_name='C/2023 A1',
            coordinates=SkyTonightCoordinates(ra_hours=6.0, dec_degrees=20.0),
            source_catalogues=['comets'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [comet], 'lookup': {}})
        comet_alt = np.array([45.0, 50.0], dtype=np.float32)
        comet_az = np.array([120.0, 130.0], dtype=np.float32)
        monkeypatch.setattr(calc, '_compute_altaz_series',
                            lambda *a, **kw: (comet_alt, comet_az))
        comet_result_dict = {
            'target_id': 'comet-c2023', 'preferred_name': 'C/2023 A1',
            'astro_score': 0.6, 'object_type': 'comet', 'constellation': '',
        }
        monkeypatch.setattr(calc, '_compute_target_result',
                            lambda *a, **kw: comet_result_dict)
        monkeypatch.setattr(calc, '_save_alttime_json', lambda *a, **kw: None)
        result = run_calculations(self._CONFIG)
        assert result['counts']['comets'] == 1

    def test_dso_batch_processing(self, monkeypatch):
        """n_dso_batch > 0 → batch AltAz and per-target scoring."""
        self._setup(monkeypatch)
        dso = SkyTonightTarget(
            target_id='dso-m31', category='deep_sky', object_type='galaxy',
            preferred_name='M31', magnitude=4.5, size_arcmin=30.0,
            coordinates=SkyTonightCoordinates(ra_hours=0.7, dec_degrees=41.3),
            source_catalogues=['Messier'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [dso], 'lookup': {}})

        n_dso = 1
        mock_altaz_batch = MagicMock()
        mock_altaz_batch.alt.deg = np.full(n_dso, 45.0, dtype=np.float32)
        mock_altaz_batch.az.deg = np.full(n_dso, 120.0, dtype=np.float32)
        mock_coord = MagicMock()
        mock_coord.transform_to.return_value = mock_altaz_batch
        monkeypatch.setattr(calc, 'SkyCoord', MagicMock(return_value=mock_coord))
        monkeypatch.setattr(calc, 'AltAz', MagicMock(return_value=MagicMock()))

        dso_result_dict = {
            'target_id': 'dso-m31', 'preferred_name': 'M31',
            'astro_score': 0.8, 'object_type': 'galaxy', 'constellation': 'Andromeda',
        }
        monkeypatch.setattr(calc, '_compute_target_result',
                            lambda *a, **kw: dso_result_dict)
        monkeypatch.setattr(calc, '_save_alttime_json', lambda *a, **kw: None)
        result = run_calculations(self._CONFIG)
        assert result['counts']['deep_sky'] == 1

    def test_comet_result_none_skips_append(self, monkeypatch):
        """comet _compute_target_result returns None → skip append."""
        self._setup(monkeypatch)
        comet = SkyTonightTarget(
            target_id='comet-none', category='comets', object_type='comet',
            preferred_name='C/2023 X1',
            coordinates=SkyTonightCoordinates(ra_hours=3.0, dec_degrees=10.0),
            source_catalogues=['comets'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [comet], 'lookup': {}})
        comet_alt = np.array([45.0, 50.0], dtype=np.float32)
        comet_az = np.array([120.0, 130.0], dtype=np.float32)
        monkeypatch.setattr(calc, '_compute_altaz_series',
                            lambda *a, **kw: (comet_alt, comet_az))
        monkeypatch.setattr(calc, '_compute_target_result', lambda *a, **kw: None)
        result = run_calculations(self._CONFIG)
        assert result['counts']['comets'] == 0

    def test_dso_result_none_skips_append(self, monkeypatch):
        """DSO _compute_target_result returns None → skip append."""
        self._setup(monkeypatch)
        dso = SkyTonightTarget(
            target_id='dso-none', category='deep_sky', object_type='galaxy',
            preferred_name='NGC 0001', magnitude=12.0, size_arcmin=5.0,
            coordinates=SkyTonightCoordinates(ra_hours=1.0, dec_degrees=20.0),
            source_catalogues=['NGC'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [dso], 'lookup': {}})
        mock_altaz_batch = MagicMock()
        mock_altaz_batch.alt.deg = np.full(1, 45.0, dtype=np.float32)
        mock_altaz_batch.az.deg = np.full(1, 120.0, dtype=np.float32)
        mock_coord = MagicMock()
        mock_coord.transform_to.return_value = mock_altaz_batch
        monkeypatch.setattr(calc, 'SkyCoord', MagicMock(return_value=mock_coord))
        monkeypatch.setattr(calc, 'AltAz', MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(calc, '_compute_target_result', lambda *a, **kw: None)
        monkeypatch.setattr(calc, '_save_alttime_json', lambda *a, **kw: None)
        result = run_calculations(self._CONFIG)
        assert result['counts']['deep_sky'] == 0

    def test_dso_log_interval_fires(self, monkeypatch):
        """patch _DSO_LOG_INTERVAL to 1 so debug log fires on first DSO."""
        self._setup(monkeypatch)
        dso = SkyTonightTarget(
            target_id='dso-log', category='deep_sky', object_type='galaxy',
            preferred_name='NGC 0002', magnitude=11.0, size_arcmin=8.0,
            coordinates=SkyTonightCoordinates(ra_hours=2.0, dec_degrees=30.0),
            source_catalogues=['NGC'], metadata={},
        )
        monkeypatch.setattr(calc, 'load_targets_dataset',
                            lambda: {'targets': [dso], 'lookup': {}})
        mock_altaz_batch = MagicMock()
        mock_altaz_batch.alt.deg = np.full(1, 45.0, dtype=np.float32)
        mock_altaz_batch.az.deg = np.full(1, 120.0, dtype=np.float32)
        mock_coord = MagicMock()
        mock_coord.transform_to.return_value = mock_altaz_batch
        monkeypatch.setattr(calc, 'SkyCoord', MagicMock(return_value=mock_coord))
        monkeypatch.setattr(calc, 'AltAz', MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(calc, '_DSO_LOG_INTERVAL', 1)
        monkeypatch.setattr(calc, '_compute_target_result', lambda *a, **kw: None)
        monkeypatch.setattr(calc, '_save_alttime_json', lambda *a, **kw: None)
        result = run_calculations(self._CONFIG)
        assert result['counts']['deep_sky'] == 0


# ---------------------------------------------------------------------------
# Merged from former test_locations_coverage.py (TestSkyTonightPerLocationBranchGaps)
# ---------------------------------------------------------------------------


def test_compute_target_debug_uses_explicit_location_without_fallback(monkeypatch):
    """False branch: a valid location dict is passed directly and
    must NOT be replaced by the install-default fallback lookup."""
    from skytonight import skytonight_calculator as calc_mod

    install_default_calls = []
    monkeypatch.setattr(
        calc_mod, 'load_targets_dataset',
        lambda: {'targets': []},
    )
    explicit_location = {
        'id': 'explicit-loc', 'latitude': 10.0, 'longitude': 20.0,
        'elevation': 5.0, 'timezone': 'UTC', 'horizon_profile': [],
    }

    def _track_install_default(config):
        install_default_calls.append(config)
        return {'latitude': 0.0, 'longitude': 0.0, 'timezone': 'UTC'}

    from utils import repo_config as _repo_config_mod2
    monkeypatch.setattr(_repo_config_mod2, 'get_install_default_location', _track_install_default)

    result = calc_mod.compute_target_debug(
        'ZZZ_NoSuch', config={'skytonight': {'constraints': {}}}, location=explicit_location,
    )

    assert result.get('found') is False
    assert install_default_calls == []  # the explicit location was used, not the fallback
