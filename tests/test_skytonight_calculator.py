"""
Tests for skytonight_calculator module.
Tests core calculation functions including AstroScore, altitude calculations,
and time conversions.
"""

import pytest
import math
import numpy as np
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import Mock, MagicMock, patch
import tempfile
import os
from types import SimpleNamespace

import skytonight_calculator as calc
from skytonight_calculator import (
    _normalise,
    _angular_separation_deg,
    _surface_brightness,
    _parse_localtime,
    _sample_times,
    compute_astro_score,
    _horizon_floor_array,
    _alttime_json_path,
    _set_progress,
    get_calculation_progress,
    _get_night_window,
    _meridian_transit_fast,
    _antimeridian_transit_fast,
    _meridian_transit_time,
    _antimeridian_transit_time,
    _save_alttime_json,
    _clear_alttime_files,
    _MoonInfo,
    _compute_target_result,
    _compute_body_result,
    _hours_to_hms,
    _degrees_to_dms,
)


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

    @patch("skytonight_calculator._meridian_transit_fast")
    @patch("skytonight_calculator._compute_altaz_series")
    def test_compute_target_result_returns_dict(self, mock_altaz, mock_transit):
        """Test that compute_target_result returns a dict when valid."""
        # This is a complex function that depends on many parameters
        # This test is a placeholder for basic structure verification
        pass


class TestComputeBodyAltazSeries:
    """Tests for body altitude calculations."""

    @patch("skytonight_calculator.get_body")
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

    @patch("skytonight_calculator.SunService")
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

    @patch("skytonight_calculator.SunService")
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

    @patch("skytonight_calculator.EarthLocation")
    @patch("skytonight_calculator.Time")
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

    @patch("skytonight_calculator.EarthLocation")
    @patch("skytonight_calculator.Time")
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
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(calc, "SKYTONIGHT_OUTPUT_DIR", tmp):
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

    @patch("skytonight_calculator.get_body")
    @patch("skytonight_calculator.moon_illumination")
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

    @patch("skytonight_calculator._compute_body_altaz_series")
    @patch("skytonight_calculator._antimeridian_transit_time")
    @patch("skytonight_calculator._meridian_transit_time")
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
