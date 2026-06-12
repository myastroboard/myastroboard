"""
Tests for cache_updater module.
Tests core cache update functions and exception handling.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
import types
import pandas as pd

from cache_updater import check_and_handle_config_changes


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {
        "location": {
            "latitude": 45.0,
            "longitude": -75.0,
            "timezone": "America/Toronto",
            "elevation": 100
        }
    }


class TestCheckAndHandleConfigChanges:
    """Tests for check_and_handle_config_changes function."""

    @patch("cache_updater.load_config")
    @patch("cache_updater.cache_store")
    def test_first_time_initialization(self, mock_cache_store, mock_load_config, mock_config):
        """Test first time initialization when no location is tracked."""
        mock_load_config.return_value = mock_config
        mock_cache_store._last_known_location_config = {"latitude": None, "longitude": None, "timezone": None, "elevation": None}
        
        result = check_and_handle_config_changes()
        
        assert result is False
        mock_cache_store.update_location_config.assert_called_once_with(mock_config["location"])

    @patch("cache_updater.load_config")
    @patch("cache_updater.cache_store")
    def test_location_unchanged(self, mock_cache_store, mock_load_config, mock_config):
        """Test when location hasn't changed."""
        mock_load_config.return_value = mock_config
        mock_cache_store._last_known_location_config = {
            "latitude": 45.0,
            "longitude": -75.0,
            "timezone": "America/Toronto",
            "elevation": 100
        }
        mock_cache_store.has_location_changed = Mock(return_value=False)
        
        result = check_and_handle_config_changes()
        
        assert result is False
        mock_cache_store.reset_all_caches.assert_not_called()

    @patch("cache_updater.load_config")
    @patch("cache_updater.cache_store")
    def test_location_changed(self, mock_cache_store, mock_load_config, mock_config):
        """Test when location configuration has changed."""
        mock_load_config.return_value = mock_config
        mock_cache_store._last_known_location_config = {
            "latitude": 40.0,  # Different latitude
            "longitude": -75.0,
            "timezone": "America/Toronto",
            "elevation": 100
        }
        mock_cache_store.has_location_changed = Mock(return_value=True)
        
        result = check_and_handle_config_changes()
        
        assert result is True
        mock_cache_store.reset_all_caches.assert_called_once()
        mock_cache_store.update_location_config.assert_called_once()

    @patch("cache_updater.load_config")
    @patch("cache_updater.cache_store")
    def test_missing_location_config(self, mock_cache_store, mock_load_config):
        """Test handling when location config is missing."""
        mock_load_config.return_value = {}
        
        result = check_and_handle_config_changes()
        
        assert result is False


class TestCacheUpdateFunctionsBasic:
    """Tests for basic cache update functionality."""

    @patch("cache_updater.load_config")
    @patch("cache_updater.MoonService")
    def test_update_moon_report_with_valid_config(self, mock_moon_service, mock_load_config):
        """Test moon report cache handles valid config."""
        from cache_updater import update_moon_report_cache
        
        config = {
            "location": {
                "latitude": 45.0,
                "longitude": -75.0,
                "timezone": "America/Toronto"
            }
        }
        mock_load_config.return_value = config
        mock_moon_instance = MagicMock()
        mock_moon_service.return_value = mock_moon_instance
        mock_report = MagicMock()
        mock_moon_instance.get_report.return_value = mock_report
        
        # Should complete without raising
        update_moon_report_cache()
        
        mock_moon_service.assert_called_once()

    @patch("cache_updater.load_config")
    def test_update_moon_report_without_location(self, mock_load_config):
        """Test moon report cache handles missing location gracefully."""
        from cache_updater import update_moon_report_cache
        
        mock_load_config.return_value = {}
        
        # Should not raise, just log error
        update_moon_report_cache()

    @patch("cache_updater.load_config")
    def test_update_weather_cache_missing_location(self, mock_load_config):
        """Test weather cache handles missing location."""
        from cache_updater import update_weather_cache
        
        mock_load_config.return_value = {}
        
        # Should not raise
        update_weather_cache()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.get_hourly_forecast")
    def test_update_weather_cache_success(self, mock_get_hourly_forecast, mock_cache_store):
        """Exercise weather serialization success path."""
        from cache_updater import update_weather_cache

        mock_cache_store._weather_cache = {"data": None, "timestamp": 0}
        mock_get_hourly_forecast.return_value = {
            "hourly": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-04-17T21:00:00Z", "2026-04-17T22:00:00Z"]),
                    "temperature": [10.0, 9.5],
                }
            ),
            "location": {"name": "Test"},
        }

        update_weather_cache()

        assert mock_cache_store._weather_cache["data"] is not None

    @patch("cache_updater.cache_store")
    @patch("cache_updater.get_hourly_forecast")
    def test_update_weather_cache_object_dtype_column(self, mock_get_hourly_forecast, mock_cache_store):
        """Line 334: bytes decode path for object-dtype DataFrame columns."""
        import numpy as np
        from cache_updater import update_weather_cache

        mock_cache_store._weather_cache = {"data": None, "timestamp": 0}
        # Use explicit dtype=object with bytes values to force the bytes decode branch
        mock_get_hourly_forecast.return_value = {
            "hourly": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-04-17T21:00:00Z"]),
                    "raw": pd.array([b"encoded_bytes"], dtype=object),
                }
            ),
            "location": {"name": "Test"},
        }

        update_weather_cache()

        assert mock_cache_store._weather_cache["data"] is not None
        decoded_records = mock_cache_store._weather_cache["data"]["hourly"]
        assert decoded_records[0]["raw"] == "encoded_bytes"


class TestCacheUpdateErrorHandling:
    """Tests for error handling in cache updates."""

    @patch("cache_updater.load_config")
    @patch("cache_updater.MoonService")
    def test_moon_service_exception_handling(self, mock_moon_service, mock_load_config):
        """Test that exceptions in MoonService are caught."""
        from cache_updater import update_moon_report_cache
        
        config = {
            "location": {
                "latitude": 45.0,
                "longitude": -75.0,
                "timezone": "America/Toronto"
            }
        }
        mock_load_config.return_value = config
        mock_moon_service.side_effect = Exception("Service error")
        
        # Should not raise, just log
        update_moon_report_cache()

    @patch("cache_updater.get_hourly_forecast")
    def test_weather_forecast_none_handling(self, mock_get_forecast):
        """Test weather cache handles None forecast."""
        from cache_updater import update_weather_cache
        
        mock_get_forecast.return_value = None
        
        # Should handle gracefully
        update_weather_cache()

    @patch("cache_updater.load_config")
    @patch("cache_updater.get_iss_passes_report")
    def test_iss_passes_cache_with_none_report(self, mock_get_iss, mock_load_config):
        """Test ISS passes cache handles None report."""
        from cache_updater import update_iss_passes_cache
        
        config = {
            "location": {
                "latitude": 45.0,
                "longitude": -75.0,
                "timezone": "America/Toronto",
                "elevation": 0
            }
        }
        mock_load_config.return_value = config
        mock_get_iss.return_value = None
        
        # Should handle gracefully
        update_iss_passes_cache()

    @patch("cache_updater.load_config")
    @patch("cache_updater.get_aurora_report")
    def test_aurora_cache_handles_errors(self, mock_get_aurora, mock_load_config):
        """Test aurora cache handles errors gracefully."""
        from cache_updater import update_aurora_cache
        
        config = {
            "location": {
                "latitude": 45.0,
                "longitude": -75.0,
                "timezone": "America/Toronto"
            }
        }
        mock_load_config.return_value = config
        mock_get_aurora.return_value = None
        
        # Should handle gracefully
        update_aurora_cache()


class TestAdditionalCachePaths:
    """Extra branch coverage for cache updater services."""

    @patch("cache_updater.cache_store")
    def test_update_spaceflight_events_prunes_using_shared_cache_entries(self, mock_cache_store):
        from cache_updater import update_spaceflight_events_cache

        mock_cache_store._spaceflight_events_cache = {"data": None, "timestamp": 0}

        fake_prune = MagicMock()
        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value={"results": []}),
            prune_image_cache=fake_prune,
        )

        mock_cache_store.load_shared_cache_entry.side_effect = lambda key: {
            "spaceflight_launches": {
                "data": {"upcoming": {"results": [{"image_url": "/api/spaceflight/img/launch.jpg"}]}}
            },
            "spaceflight_astronauts": {
                "data": {"astronauts_in_space": {"results": [{"profile_image": "/api/spaceflight/img/astro.jpg"}]}}
            },
            "spaceflight_events": {
                "data": {"results": [{"image_url": "/api/spaceflight/img/event.jpg"}]}
            },
        }.get(key)

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()

        fake_prune.assert_called_once()
        active_images = fake_prune.call_args.args[0]
        assert "/api/spaceflight/img/launch.jpg" in active_images
        assert "/api/spaceflight/img/astro.jpg" in active_images
        assert "/api/spaceflight/img/event.jpg" in active_images

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    def test_update_planetary_events_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache_updater import update_planetary_events_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._planetary_events_cache = {"data": None, "timestamp": 0}

        fake_service = MagicMock()
        fake_service.get_planetary_events.return_value = [{"name": "Conjunction"}]
        fake_module = types.SimpleNamespace(PlanetaryEventsService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"planetary_events": fake_module}):
            update_planetary_events_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    def test_update_special_phenomena_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache_updater import update_special_phenomena_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._special_phenomena_cache = {"data": None, "timestamp": 0}

        fake_service = MagicMock()
        fake_service.get_special_phenomena.return_value = [{"name": "Equinox"}]
        fake_module = types.SimpleNamespace(SpecialPhenomenaService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"special_phenomena": fake_module}):
            update_special_phenomena_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    def test_update_solar_system_events_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache_updater import update_solar_system_events_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._solar_system_events_cache = {"data": None, "timestamp": 0}

        fake_service = MagicMock()
        fake_service.get_solar_system_events.return_value = [{"name": "Perseids"}]
        fake_module = types.SimpleNamespace(SolarSystemEventsService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"solar_system_events": fake_module}):
            update_solar_system_events_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    def test_update_sidereal_time_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache_updater import update_sidereal_time_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._sidereal_time_cache = {"data": None, "timestamp": 0}

        fake_service = MagicMock()
        fake_service.get_current_sidereal_info.return_value = {"lst": "12:00"}
        fake_service.get_hourly_sidereal_times.return_value = [{"hour": 0, "lst": "10:00"}]
        fake_module = types.SimpleNamespace(SiderealTimeService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"sidereal_time": fake_module}):
            update_sidereal_time_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.MoonService")
    @patch("cache_updater.load_config")
    def test_update_dark_window_cache_success(self, mock_load_config, mock_moon_service, mock_cache_store, mock_config):
        from cache_updater import update_dark_window_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._dark_window_report_cache = {"data": None, "timestamp": 0}

        report = types.SimpleNamespace(
            next_dark_night_start="2026-04-17T22:00:00",
            next_dark_night_end="2026-04-18T03:00:00",
        )
        mock_moon_service.return_value.get_report.return_value = report

        update_dark_window_cache()
        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.MoonPlanner")
    @patch("cache_updater.load_config")
    def test_update_moon_planner_cache_success(self, mock_load_config, mock_planner, mock_cache_store, mock_config):
        from cache_updater import update_moon_planner_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._moon_planner_report_cache = {"data": None, "timestamp": 0}
        mock_planner.return_value.next_7_nights.return_value = [{"date": "2026-04-17", "dark_hours": 6.0}]

        update_moon_planner_cache()
        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.SunService")
    @patch("cache_updater.load_config")
    def test_update_sun_report_cache_success(self, mock_load_config, mock_sun, mock_cache_store, mock_config):
        from cache_updater import update_sun_report_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._sun_report_cache = {"data": None, "timestamp": 0}
        # Provide astronomical_dusk/dawn so _next_astronomical_dusk_utc can run
        report = types.SimpleNamespace(
            sunrise="06:00", sunset="20:00",
            astronomical_dusk="Not found", astronomical_dawn="Not found",
        )
        mock_sun.return_value.get_today_report.return_value = report
        mock_sun.return_value.get_tomorrow_report.return_value = report

        update_sun_report_cache()
        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.AstroTonightService")
    @patch("cache_updater.load_config")
    def test_update_best_window_cache_success(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        from cache_updater import update_best_window_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._best_window_cache = {
            "strict": {"data": None, "timestamp": 0},
            "practical": {"data": None, "timestamp": 0},
            "illumination": {"data": None, "timestamp": 0},
        }
        window = types.SimpleNamespace(start="21:00", end="23:00", score=80)
        mock_service.return_value.best_windows_all_modes.return_value = {
            "strict": window,
            "practical": window,
            "illumination": window,
        }

        update_best_window_cache()
        assert mock_cache_store.update_shared_cache_entry.call_count == 3


class TestFullInitialization:
    """Coverage for fully_initialize_caches control-flow."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.update_weather_cache")
    @patch("cache_updater.update_best_window_cache")
    @patch("cache_updater.update_sidereal_time_cache")
    @patch("cache_updater.update_solar_system_events_cache")
    @patch("cache_updater.update_special_phenomena_cache")
    @patch("cache_updater.update_planetary_events_cache")
    @patch("cache_updater.update_iss_passes_cache")
    @patch("cache_updater.update_aurora_cache")
    @patch("cache_updater.update_horizon_graph_cache")
    @patch("cache_updater.update_lunar_eclipse_cache")
    @patch("cache_updater.update_solar_eclipse_cache")
    @patch("cache_updater.update_sun_report_cache")
    @patch("cache_updater.update_moon_planner_cache")
    @patch("cache_updater.update_moon_caches")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_caches_success(
        self,
        _check,
        _moon_caches,
        _planner,
        _sun,
        _solar,
        _lunar,
        _horizon,
        _aurora,
        _iss,
        _planetary,
        _special,
        _solsys,
        _sidereal,
        _best,
        _weather,
        mock_load_config,
        mock_cache_store,
    ):
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        # Force all caches to be stale so jobs_to_run is populated
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.sync_cache_from_shared.return_value = None

        fully_initialize_caches()

        assert mock_cache_store.set_cache_initialization_in_progress.call_count >= 2

    @patch("cache_updater.cache_store")
    @patch("cache_updater.update_weather_cache")
    @patch("cache_updater.update_best_window_cache")
    @patch("cache_updater.update_sidereal_time_cache")
    @patch("cache_updater.update_solar_system_events_cache")
    @patch("cache_updater.update_special_phenomena_cache")
    @patch("cache_updater.update_planetary_events_cache")
    @patch("cache_updater.update_iss_passes_cache")
    @patch("cache_updater.update_aurora_cache")
    @patch("cache_updater.update_horizon_graph_cache")
    @patch("cache_updater.update_lunar_eclipse_cache")
    @patch("cache_updater.update_solar_eclipse_cache")
    @patch("cache_updater.update_sun_report_cache")
    @patch("cache_updater.update_moon_planner_cache")
    @patch("cache_updater.update_dark_window_cache")
    @patch("cache_updater.update_moon_report_cache")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_caches_continues_on_single_failure(
        self,
        _check,
        _moon,
        _dark,
        _planner,
        _sun,
        _solar,
        _lunar,
        _horizon,
        _aurora,
        _iss,
        _planetary,
        _special,
        _solsys,
        _sidereal,
        _best,
        _weather,
        mock_cache_store,
    ):
        from cache_updater import fully_initialize_caches

        _planetary.side_effect = RuntimeError("boom")

        fully_initialize_caches()

        # Final reset call must still happen
        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache_updater.cache_store")
    @patch("cache_updater.update_weather_cache")
    @patch("cache_updater.update_best_window_cache")
    @patch("cache_updater.update_sidereal_time_cache")
    @patch("cache_updater.update_solar_system_events_cache")
    @patch("cache_updater.update_special_phenomena_cache")
    @patch("cache_updater.update_planetary_events_cache")
    @patch("cache_updater.update_iss_passes_cache")
    @patch("cache_updater.update_aurora_cache")
    @patch("cache_updater.update_horizon_graph_cache")
    @patch("cache_updater.update_lunar_eclipse_cache")
    @patch("cache_updater.update_solar_eclipse_cache")
    @patch("cache_updater.update_sun_report_cache")
    @patch("cache_updater.update_moon_planner_cache")
    @patch("cache_updater.update_moon_caches")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_parallel_failure_and_sequential_moon_report(
        self,
        _check, _moon_caches, _planner, _sun, _solar, _lunar,
        _horizon, _aurora, _iss, _planetary, _special, _solsys,
        _sidereal, _best, _weather, mock_cache_store,
    ):
        """Lines 1310-1313 (parallel failure), 1338 (moon_report success mirrors dark_window)."""
        from cache_updater import fully_initialize_caches

        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store.record_cache_execution = MagicMock()
        # Make a parallel job fail
        _aurora.side_effect = RuntimeError("aurora down")

        fully_initialize_caches()

        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache_updater.cache_store")
    @patch("cache_updater.update_weather_cache")
    @patch("cache_updater.update_best_window_cache")
    @patch("cache_updater.update_sidereal_time_cache")
    @patch("cache_updater.update_solar_system_events_cache")
    @patch("cache_updater.update_special_phenomena_cache")
    @patch("cache_updater.update_planetary_events_cache")
    @patch("cache_updater.update_iss_passes_cache")
    @patch("cache_updater.update_aurora_cache")
    @patch("cache_updater.update_horizon_graph_cache")
    @patch("cache_updater.update_lunar_eclipse_cache")
    @patch("cache_updater.update_solar_eclipse_cache")
    @patch("cache_updater.update_sun_report_cache")
    @patch("cache_updater.update_moon_planner_cache")
    @patch("cache_updater.update_moon_caches")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_sequential_non_moon_report_failure(
        self,
        _check, _moon_caches, _planner, _sun, _solar, _lunar,
        _horizon, _aurora, _iss, _planetary, _special, _solsys,
        _sidereal, _best, _weather, mock_cache_store,
    ):
        """Line 1344->1346: sequential non-moon_report job fails → False branch of if job_name=='moon_report'."""
        from cache_updater import fully_initialize_caches

        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store.record_cache_execution = MagicMock()
        # Make a non-moon_report sequential job fail
        _planetary.side_effect = RuntimeError("planetary down")

        fully_initialize_caches()

        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)


# ---------------------------------------------------------------------------
# Additional tests to increase cache_updater branch/statement coverage
# ---------------------------------------------------------------------------

class TestNextAstronomicalDuskUtc:
    """Tests for _next_astronomical_dusk_utc helper."""

    def test_returns_dusk_when_valid_and_future(self):
        """Returns ISO string when dusk is in the future."""
        from cache_updater import _next_astronomical_dusk_utc
        from datetime import datetime as _dt, timezone, timedelta
        import types

        future_dusk = (_dt.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        report = types.SimpleNamespace(astronomical_dusk=future_dusk)
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is not None
        assert "T" in result

    def test_returns_none_when_all_dusk_not_found(self):
        """Returns None when all reports have 'Not found' dusk."""
        from cache_updater import _next_astronomical_dusk_utc
        import types

        report = types.SimpleNamespace(astronomical_dusk="Not found")
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is None

    def test_returns_none_when_dusk_is_empty(self):
        """Returns None when dusk is an empty string."""
        from cache_updater import _next_astronomical_dusk_utc
        import types

        report = types.SimpleNamespace(astronomical_dusk="")
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is None

    def test_returns_none_when_dusk_in_past(self):
        """Returns None when dusk is already in the past."""
        from cache_updater import _next_astronomical_dusk_utc
        from datetime import datetime as _dt, timezone, timedelta
        import types

        past_dusk = (_dt.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        report = types.SimpleNamespace(astronomical_dusk=past_dusk)
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is None

    def test_skips_bad_dusk_string_and_continues(self):
        """Bad dusk string is skipped and the loop continues to the next report."""
        from cache_updater import _next_astronomical_dusk_utc
        from datetime import datetime as _dt, timezone, timedelta
        import types

        bad_report = types.SimpleNamespace(astronomical_dusk="not-a-valid-datetime")
        future_dusk = (_dt.now(timezone.utc) + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S")
        good_report = types.SimpleNamespace(astronomical_dusk=future_dusk)
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = bad_report
        sun_service.get_tomorrow_report.return_value = good_report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is not None


class TestUpdateMoonCachesAdditional:
    """Additional tests for update_moon_caches."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.MoonService")
    @patch("cache_updater.load_config")
    def test_update_moon_caches_with_bytes_value(self, mock_load_config, mock_moon_service, mock_cache_store):
        """MoonService report values that are bytes are decoded."""
        from cache_updater import update_moon_caches

        config = {"location": {"latitude": 45.0, "longitude": -75.0, "timezone": "UTC"}}
        mock_load_config.return_value = config
        mock_cache_store._moon_report_cache = {"data": None, "timestamp": 0}
        mock_cache_store._dark_window_report_cache = {"data": None, "timestamp": 0}

        import types
        report = types.SimpleNamespace(
            some_bytes_field=b"encoded_value",
            next_dark_night_start="22:00",
            next_dark_night_end="04:00",
        )
        mock_moon_service.return_value.get_report.return_value = report

        update_moon_caches()
        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.MoonService")
    def test_update_moon_caches_with_direct_config(self, mock_moon_service, mock_cache_store):
        """Config passed directly avoids calling load_config."""
        from cache_updater import update_moon_caches

        config = {"location": {"latitude": 48.0, "longitude": 2.0, "timezone": "Europe/Paris"}}
        mock_cache_store._moon_report_cache = {"data": None, "timestamp": 0}
        mock_cache_store._dark_window_report_cache = {"data": None, "timestamp": 0}

        import types
        report = types.SimpleNamespace(next_dark_night_start="21:00", next_dark_night_end="03:00")
        mock_moon_service.return_value.get_report.return_value = report

        update_moon_caches(config=config)
        mock_moon_service.assert_called_once_with(latitude=48.0, longitude=2.0, timezone="Europe/Paris")


class TestUpdateSolarEclipseCache:
    """Tests for update_solar_eclipse_cache."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.SolarEclipseService")
    @patch("cache_updater.load_config")
    def test_solar_eclipse_none_response(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When eclipse is None, response has null solar_eclipse field."""
        from cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._solar_eclipse_cache = {"data": None, "timestamp": 0}
        mock_service.return_value.get_next_eclipse.return_value = None

        update_solar_eclipse_cache()

        stored_data = mock_cache_store._solar_eclipse_cache["data"]
        assert stored_data["solar_eclipse"] is None
        assert "message" in stored_data

    @patch("cache_updater.cache_store")
    @patch("cache_updater.SolarEclipseService")
    @patch("cache_updater.load_config")
    def test_solar_eclipse_with_eclipse_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When eclipse is available, response has eclipse dict."""
        from cache_updater import update_solar_eclipse_cache
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._solar_eclipse_cache = {"data": None, "timestamp": 0}

        eclipse = types.SimpleNamespace(type="Total", peak_time="2026-08-12T14:00:00", altitude_vs_time=[])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_solar_eclipse_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.SolarEclipseService")
    @patch("cache_updater.load_config")
    def test_solar_eclipse_with_altitude_vs_time(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """altitude_vs_time EclipsePoint objects are converted to dicts."""
        from cache_updater import update_solar_eclipse_cache
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._solar_eclipse_cache = {"data": None, "timestamp": 0}

        point = types.SimpleNamespace(time="14:00", altitude=45.0)
        eclipse = types.SimpleNamespace(type="Partial", peak_time="2026-08-12T14:00:00", altitude_vs_time=[point])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_solar_eclipse_cache()

        stored = mock_cache_store._solar_eclipse_cache["data"]
        assert stored["solar_eclipse"]["altitude_vs_time"] == [{"time": "14:00", "altitude": 45.0}]

    @patch("cache_updater.load_config")
    def test_solar_eclipse_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully (no raise)."""
        from cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = {}
        update_solar_eclipse_cache()  # Should not raise

    @patch("cache_updater.SolarEclipseService")
    @patch("cache_updater.load_config")
    def test_solar_eclipse_service_exception(self, mock_load_config, mock_service, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("service error")

        update_solar_eclipse_cache()  # Should not raise


class TestUpdateLunarEclipseCache:
    """Tests for update_lunar_eclipse_cache."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.LunarEclipseService")
    @patch("cache_updater.load_config")
    def test_lunar_eclipse_none_response(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When lunar eclipse is None, response has null field."""
        from cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._lunar_eclipse_cache = {"data": None, "timestamp": 0}
        mock_service.return_value.get_next_eclipse.return_value = None

        update_lunar_eclipse_cache()

        stored = mock_cache_store._lunar_eclipse_cache["data"]
        assert stored["lunar_eclipse"] is None

    @patch("cache_updater.cache_store")
    @patch("cache_updater.LunarEclipseService")
    @patch("cache_updater.load_config")
    def test_lunar_eclipse_with_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When lunar eclipse available, result has eclipse dict."""
        from cache_updater import update_lunar_eclipse_cache
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._lunar_eclipse_cache = {"data": None, "timestamp": 0}

        eclipse = types.SimpleNamespace(type="Total", peak_time="2025-09-07T02:00:00", altitude_vs_time=[])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_lunar_eclipse_cache()
        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    @patch("cache_updater.LunarEclipseService")
    @patch("cache_updater.load_config")
    def test_lunar_eclipse_with_altitude_vs_time(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """altitude_vs_time EclipsePoint objects are converted to dicts."""
        from cache_updater import update_lunar_eclipse_cache
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._lunar_eclipse_cache = {"data": None, "timestamp": 0}

        point = types.SimpleNamespace(time="02:00", altitude=30.0)
        eclipse = types.SimpleNamespace(type="Partial", peak_time="2025-09-07T02:00:00", altitude_vs_time=[point])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_lunar_eclipse_cache()

        stored = mock_cache_store._lunar_eclipse_cache["data"]
        assert stored["lunar_eclipse"]["altitude_vs_time"] == [{"time": "02:00", "altitude": 30.0}]

    @patch("cache_updater.load_config")
    def test_lunar_eclipse_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = {}
        update_lunar_eclipse_cache()

    @patch("cache_updater.LunarEclipseService")
    @patch("cache_updater.load_config")
    def test_lunar_eclipse_service_exception(self, mock_load_config, mock_service, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("service error")

        update_lunar_eclipse_cache()


class TestUpdateHorizonGraphCache:
    """Tests for update_horizon_graph_cache."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.HorizonGraphService")
    @patch("cache_updater.load_config")
    def test_horizon_graph_none_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When horizon_data is None, response has null field."""
        from cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._horizon_graph_cache = {"data": None, "timestamp": 0}
        mock_service.return_value.get_horizon_data.return_value = None

        update_horizon_graph_cache()

        stored = mock_cache_store._horizon_graph_cache["data"]
        assert stored["horizon_data"] is None

    @patch("cache_updater.cache_store")
    @patch("cache_updater.HorizonGraphService")
    @patch("cache_updater.load_config")
    def test_horizon_graph_with_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When horizon_data available, sun/moon point objects are converted to dicts."""
        from cache_updater import update_horizon_graph_cache
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._horizon_graph_cache = {"data": None, "timestamp": 0}

        sun_point = types.SimpleNamespace(time="12:00", altitude=60.0)
        moon_point = types.SimpleNamespace(time="22:00", altitude=30.0)
        horizon_data = types.SimpleNamespace(sun_data=[sun_point], moon_data=[moon_point])
        mock_service.return_value.get_horizon_data.return_value = horizon_data

        update_horizon_graph_cache()

        stored = mock_cache_store._horizon_graph_cache["data"]
        assert stored["horizon_data"]["sun_data"] == [{"time": "12:00", "altitude": 60.0}]
        assert stored["horizon_data"]["moon_data"] == [{"time": "22:00", "altitude": 30.0}]

    @patch("cache_updater.load_config")
    def test_horizon_graph_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = {}
        update_horizon_graph_cache()

    @patch("cache_updater.HorizonGraphService")
    @patch("cache_updater.load_config")
    def test_horizon_graph_service_exception(self, mock_load_config, mock_service, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("service error")

        update_horizon_graph_cache()


class TestUpdateAuroraCache:
    """Tests for update_aurora_cache."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.get_aurora_report")
    @patch("cache_updater.load_config")
    def test_aurora_cache_success(self, mock_load_config, mock_get_aurora, mock_cache_store, mock_config):
        """Successful aurora report is stored in cache."""
        from cache_updater import update_aurora_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._aurora_cache = {"data": None, "timestamp": 0}
        mock_get_aurora.return_value = {"forecast": [{"kp_index": 5}]}

        update_aurora_cache()

        assert mock_cache_store._aurora_cache["data"] == {"forecast": [{"kp_index": 5}]}
        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.get_aurora_report")
    @patch("cache_updater.load_config")
    def test_aurora_cache_none_report_raises_value_error(self, mock_load_config, mock_get_aurora, mock_config):
        """None aurora report raises ValueError that is caught."""
        from cache_updater import update_aurora_cache

        mock_load_config.return_value = mock_config
        mock_get_aurora.return_value = None

        update_aurora_cache()  # Should not raise

    @patch("cache_updater.load_config")
    def test_aurora_cache_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_aurora_cache

        mock_load_config.return_value = {}
        update_aurora_cache()


class TestUpdateIssPassesCache:
    """Tests for update_iss_passes_cache."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.get_iss_passes_report")
    @patch("cache_updater.load_config")
    def test_iss_passes_success(self, mock_load_config, mock_get_iss, mock_cache_store, mock_config):
        """Successful ISS report is stored in cache."""
        from cache_updater import update_iss_passes_cache

        mock_load_config.return_value = mock_config
        mock_cache_store._iss_passes_cache = {"data": None, "timestamp": 0}
        mock_get_iss.return_value = {"passes": [{"peak_time": "2026-04-17T21:00:00"}]}

        update_iss_passes_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.get_iss_passes_report")
    @patch("cache_updater.load_config")
    def test_iss_passes_service_exception(self, mock_load_config, mock_get_iss, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_iss_passes_cache

        mock_load_config.return_value = mock_config
        mock_get_iss.side_effect = RuntimeError("network error")

        update_iss_passes_cache()  # Should not raise

    @patch("cache_updater.load_config")
    def test_iss_passes_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_iss_passes_cache

        mock_load_config.return_value = {}
        update_iss_passes_cache()


class TestUpdatePlanetaryEventsCache:
    """Tests for update_planetary_events_cache."""

    @patch("cache_updater.load_config")
    def test_planetary_events_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_planetary_events_cache

        mock_load_config.return_value = {}
        update_planetary_events_cache()

    @patch("cache_updater.load_config")
    def test_planetary_events_service_exception(self, mock_load_config, mock_config):
        """Service import exception is caught and logged."""
        from cache_updater import update_planetary_events_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            PlanetaryEventsService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"planetary_events": broken_module}):
            update_planetary_events_cache()  # Should not raise


class TestUpdateSpecialPhenomenaCache:
    """Tests for update_special_phenomena_cache."""

    @patch("cache_updater.load_config")
    def test_special_phenomena_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_special_phenomena_cache

        mock_load_config.return_value = {}
        update_special_phenomena_cache()

    @patch("cache_updater.load_config")
    def test_special_phenomena_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_special_phenomena_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            SpecialPhenomenaService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"special_phenomena": broken_module}):
            update_special_phenomena_cache()  # Should not raise


class TestUpdateSolarSystemEventsCache:
    """Tests for update_solar_system_events_cache."""

    @patch("cache_updater.load_config")
    def test_solar_system_events_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_solar_system_events_cache

        mock_load_config.return_value = {}
        update_solar_system_events_cache()

    @patch("cache_updater.load_config")
    def test_solar_system_events_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_solar_system_events_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            SolarSystemEventsService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"solar_system_events": broken_module}):
            update_solar_system_events_cache()  # Should not raise


class TestUpdateSiderealTimeCache:
    """Tests for update_sidereal_time_cache."""

    @patch("cache_updater.load_config")
    def test_sidereal_time_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_sidereal_time_cache

        mock_load_config.return_value = {}
        update_sidereal_time_cache()

    @patch("cache_updater.load_config")
    def test_sidereal_time_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_sidereal_time_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            SiderealTimeService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"sidereal_time": broken_module}):
            update_sidereal_time_cache()  # Should not raise


class TestUpdateSeeingForecastCache:
    """Tests for update_seeing_forecast_cache."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    def test_seeing_forecast_with_none_data(self, mock_load_config, mock_cache_store, mock_config):
        """When seeing_data is None, response has null field with message."""
        from cache_updater import update_seeing_forecast_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._seeing_forecast_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(get_seeing_forecast=MagicMock(return_value=None))
        with patch.dict(sys.modules, {"seeing_forecast_7timer": fake_module}):
            update_seeing_forecast_cache()

        stored = mock_cache_store._seeing_forecast_cache["data"]
        assert stored["seeing_forecast"] is None
        assert "message" in stored

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    def test_seeing_forecast_with_valid_data(self, mock_load_config, mock_cache_store, mock_config):
        """When seeing_data available, it is stored with units."""
        from cache_updater import update_seeing_forecast_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        mock_cache_store._seeing_forecast_cache = {"data": None, "timestamp": 0}
        seeing_data = {"hourly": [{"time": "2026-04-17T22:00:00Z", "seeing": 1}]}
        fake_module = types.SimpleNamespace(get_seeing_forecast=MagicMock(return_value=seeing_data))

        with patch.dict(sys.modules, {"seeing_forecast_7timer": fake_module}):
            update_seeing_forecast_cache()

        stored = mock_cache_store._seeing_forecast_cache["data"]
        assert stored["seeing_forecast"] == seeing_data
        assert "units" in stored

    @patch("cache_updater.load_config")
    def test_seeing_forecast_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache_updater import update_seeing_forecast_cache

        mock_load_config.return_value = {}
        update_seeing_forecast_cache()

    @patch("cache_updater.load_config")
    def test_seeing_forecast_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache_updater import update_seeing_forecast_cache
        import sys
        import types

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(get_seeing_forecast=MagicMock(side_effect=RuntimeError("timeout")))

        with patch.dict(sys.modules, {"seeing_forecast_7timer": broken_module}):
            update_seeing_forecast_cache()  # Should not raise


class TestUpdateSpaceflightLaunchesCache:
    """Tests for update_spaceflight_launches_cache."""

    @patch("cache_updater.cache_store")
    def test_launches_success_with_both_results(self, mock_cache_store):
        """Both upcoming and past launches are stored."""
        from cache_updater import update_spaceflight_launches_cache
        import sys
        import types

        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(return_value={"count": 1, "results": [{"name": "Falcon 9"}]}),
            get_past_launches=MagicMock(return_value={"count": 1, "results": [{"name": "Atlas V"}]}),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_launches_cache()

        stored = mock_cache_store._spaceflight_launches_cache["data"]
        assert stored["upcoming"]["count"] == 1
        assert stored["past"]["count"] == 1

    @patch("cache_updater.cache_store")
    def test_launches_with_none_upcoming_uses_fallback(self, mock_cache_store):
        """None upcoming falls back to empty dict."""
        from cache_updater import update_spaceflight_launches_cache
        import sys
        import types

        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(return_value=None),
            get_past_launches=MagicMock(return_value={"count": 1, "results": []}),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_launches_cache()

        stored = mock_cache_store._spaceflight_launches_cache["data"]
        assert stored["upcoming"] == {"count": 0, "results": []}

    @patch("cache_updater.cache_store")
    def test_launches_both_none_returns_early(self, mock_cache_store):
        """Both None returns early without storing."""
        from cache_updater import update_spaceflight_launches_cache
        import sys
        import types

        mock_cache_store._spaceflight_launches_cache = {"data": "old_data", "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(return_value=None),
            get_past_launches=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_launches_cache()

        # Cache was not updated
        assert mock_cache_store.update_shared_cache_entry.call_count == 0

    def test_launches_service_exception(self):
        """Service exception is caught and logged."""
        from cache_updater import update_spaceflight_launches_cache
        import sys
        import types

        broken_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(side_effect=RuntimeError("network error")),
            get_past_launches=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": broken_module}):
            update_spaceflight_launches_cache()  # Should not raise


class TestUpdateSpaceflightAstronautsCache:
    """Tests for update_spaceflight_astronauts_cache."""

    @patch("cache_updater.cache_store")
    def test_astronauts_success(self, mock_cache_store):
        """Successful astronaut data is stored in cache."""
        from cache_updater import update_spaceflight_astronauts_cache
        import sys
        import types

        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value={"count": 7, "results": []}),
            get_astronauts_in_space=MagicMock(return_value={"count": 7, "results": []}),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    def test_astronauts_both_none_returns_early(self, mock_cache_store):
        """Both None returns early without storing."""
        from cache_updater import update_spaceflight_astronauts_cache
        import sys
        import types

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value=None),
            get_astronauts_in_space=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        assert mock_cache_store.update_shared_cache_entry.call_count == 0

    @patch("cache_updater.cache_store")
    def test_astronauts_none_iss_crew_uses_fallback(self, mock_cache_store):
        """None iss_crew falls back to empty dict."""
        from cache_updater import update_spaceflight_astronauts_cache
        import sys
        import types

        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value=None),
            get_astronauts_in_space=MagicMock(return_value={"count": 3, "results": []}),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        stored = mock_cache_store._spaceflight_astronauts_cache["data"]
        assert stored["iss_crew"] == {}


class TestUpdateSpaceflightEventsCache:
    """Tests for update_spaceflight_events_cache edge cases."""

    @patch("cache_updater.cache_store")
    def test_events_none_returns_early(self, mock_cache_store):
        """None events returns early without storing."""
        from cache_updater import update_spaceflight_events_cache
        import sys
        import types

        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()

        assert mock_cache_store.update_shared_cache_entry.call_count == 0

    @patch("cache_updater.cache_store")
    def test_prune_exception_is_caught(self, mock_cache_store):
        """Exception during image prune is caught and logged."""
        from cache_updater import update_spaceflight_events_cache
        import sys
        import types

        mock_cache_store._spaceflight_events_cache = {"data": None, "timestamp": 0}
        mock_cache_store.load_shared_cache_entry.side_effect = RuntimeError("db error")

        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value={"results": []}),
            prune_image_cache=MagicMock(),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()  # Should not raise

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache_updater.cache_store")
    def test_collect_images_ignores_non_prefix_strings(self, mock_cache_store):
        """Line 977->exit: _collect_images skips strings not starting with /api/spaceflight/img/."""
        from cache_updater import update_spaceflight_events_cache

        mock_cache_store._spaceflight_events_cache = {"data": None, "timestamp": 0}

        fake_prune = MagicMock()
        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value={"results": []}),
            prune_image_cache=fake_prune,
        )

        mock_cache_store.load_shared_cache_entry.side_effect = lambda key: {
            "spaceflight_launches": {
                "data": {
                    "name": "Mission X",  # non-prefix string → hits 977->exit
                    "image_url": "/api/spaceflight/img/launch.jpg",
                }
            },
            "spaceflight_astronauts": None,
            "spaceflight_events": None,
        }.get(key)

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()

        fake_prune.assert_called_once()
        active_images = fake_prune.call_args.args[0]
        assert "/api/spaceflight/img/launch.jpg" in active_images
        assert "Mission X" not in active_images


class TestUpdateIersCacheAdditional:
    """Tests for update_iers_cache."""

    def test_iers_exception_is_caught(self):
        """Exception during IERS download is caught and logged."""
        from cache_updater import update_iers_cache

        # Patch requests to simulate a download error
        with patch("cache_updater.cache_store"):
            with patch("requests.get", side_effect=ConnectionError("no network")):
                update_iers_cache()  # Should not raise


class TestMissingLocationAndExceptionPaths:
    """Cover missing-location and exception branches for each cache update function."""

    @patch("cache_updater.load_config")
    def test_moon_planner_missing_location(self, mock_load_config):
        """update_moon_planner_cache handles missing location gracefully."""
        from cache_updater import update_moon_planner_cache

        mock_load_config.return_value = {}
        update_moon_planner_cache()  # Should not raise

    @patch("cache_updater.MoonPlanner")
    @patch("cache_updater.load_config")
    def test_moon_planner_exception(self, mock_load_config, mock_planner, mock_config):
        """update_moon_planner_cache exception is caught and logged."""
        from cache_updater import update_moon_planner_cache

        mock_load_config.return_value = mock_config
        mock_planner.side_effect = RuntimeError("planner error")
        update_moon_planner_cache()  # Should not raise

    @patch("cache_updater.load_config")
    def test_sun_report_missing_location(self, mock_load_config):
        """update_sun_report_cache handles missing location gracefully."""
        from cache_updater import update_sun_report_cache

        mock_load_config.return_value = {}
        update_sun_report_cache()  # Should not raise

    @patch("cache_updater.SunService")
    @patch("cache_updater.load_config")
    def test_sun_report_exception(self, mock_load_config, mock_sun, mock_config):
        """update_sun_report_cache exception is caught and logged."""
        from cache_updater import update_sun_report_cache

        mock_load_config.return_value = mock_config
        mock_sun.side_effect = RuntimeError("sun error")
        update_sun_report_cache()  # Should not raise

    @patch("cache_updater.load_config")
    def test_best_window_missing_location(self, mock_load_config):
        """update_best_window_cache handles missing location gracefully."""
        from cache_updater import update_best_window_cache

        mock_load_config.return_value = {}
        update_best_window_cache()  # Should not raise

    @patch("cache_updater.AstroTonightService")
    @patch("cache_updater.load_config")
    def test_best_window_exception(self, mock_load_config, mock_service, mock_config):
        """update_best_window_cache exception is caught and logged."""
        from cache_updater import update_best_window_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("best window error")
        update_best_window_cache()  # Should not raise

    @patch("cache_updater.get_hourly_forecast")
    def test_weather_cache_exception(self, mock_forecast):
        """update_weather_cache exception during serialization is caught."""
        from cache_updater import update_weather_cache

        # Raise during forecast fetch
        mock_forecast.side_effect = RuntimeError("serialization error")
        update_weather_cache()  # Should not raise

    @patch("cache_updater.cache_store")
    @patch("cache_updater.get_hourly_forecast")
    def test_weather_cache_with_bytes_location(self, mock_forecast, mock_cache_store):
        """update_weather_cache handles bytes values in location dict."""
        from cache_updater import update_weather_cache

        mock_cache_store._weather_cache = {"data": None, "timestamp": 0}
        mock_forecast.return_value = {
            "hourly": __import__("pandas").DataFrame({"date": __import__("pandas").to_datetime(["2026-04-17T21:00:00Z"]), "temp": [10.0]}),
            "location": {"name": b"Paris", "country": "France"},
        }

        update_weather_cache()
        stored = mock_cache_store._weather_cache["data"]
        assert stored["location"]["name"] == "Paris"

    def test_spaceflight_astronauts_exception(self):
        """update_spaceflight_astronauts_cache exception is caught."""
        from cache_updater import update_spaceflight_astronauts_cache
        import sys
        import types

        broken_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(side_effect=RuntimeError("network error")),
            get_astronauts_in_space=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": broken_module}):
            update_spaceflight_astronauts_cache()  # Should not raise

    def test_spaceflight_events_outer_exception(self):
        """update_spaceflight_events_cache outer exception is caught."""
        from cache_updater import update_spaceflight_events_cache
        import sys
        import types

        broken_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(side_effect=RuntimeError("outer error")),
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": broken_module}):
            update_spaceflight_events_cache()  # Should not raise

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_moon_report_mirrors_dark_window_on_failure(
        self, _check, mock_load_config, mock_cache_store
    ):
        """Exception in moon_report job also records dark_window failure."""
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        with patch("cache_updater.update_moon_caches", side_effect=RuntimeError("moon fail")):
            fully_initialize_caches()

        # record_cache_execution for both "moon_report" and "dark_window" with False
        calls = [str(c) for c in mock_cache_store.record_cache_execution.call_args_list]
        assert any("dark_window" in c for c in calls)


class TestFullyInitializeCachesAdditional:
    """Additional tests for fully_initialize_caches control flow."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_all_caches_valid_skips_all_jobs(self, _check, mock_load_config, mock_cache_store):
        """When all caches are valid, no jobs are run."""
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        # All caches valid
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.sync_cache_from_shared.return_value = None

        fully_initialize_caches()

        # set_cache_initialization_in_progress(False) must still be called in finally
        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_spaceflight_image_integrity_forces_refetch(self, _check, mock_load_config, mock_cache_store):
        """Missing spaceflight images force timestamp=0 to trigger refetch."""
        from cache_updater import fully_initialize_caches
        import sys
        import types

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.sync_cache_from_shared.return_value = None

        # Simulate cache entry with data
        launches_cache = {"data": {"upcoming": {}}, "timestamp": 999999}
        mock_cache_store._spaceflight_launches_cache = launches_cache
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_tracker = types.SimpleNamespace(
            spaceflight_cache_images_intact=MagicMock(return_value=False)
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_tracker}):
            fully_initialize_caches()

        # Timestamp should have been zeroed, forcing a refetch
        assert launches_cache["timestamp"] == 0

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_spaceflight_image_integrity_intact_skips_reset(self, _check, mock_load_config, mock_cache_store):
        """Branch 1286->1293: images are intact so timestamp is NOT reset."""
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.sync_cache_from_shared.return_value = None

        original_ts = 999999
        launches_cache = {"data": {"upcoming": {}}, "timestamp": original_ts}
        mock_cache_store._spaceflight_launches_cache = launches_cache
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_tracker = types.SimpleNamespace(
            spaceflight_cache_images_intact=MagicMock(return_value=True)  # images are intact
        )

        with patch.dict(sys.modules, {"spaceflight_tracker": fake_tracker}):
            fully_initialize_caches()

        # Timestamp must NOT have been reset since images are intact
        assert launches_cache["timestamp"] == original_ts

    @patch("astropy.utils.iers.IERS_Auto.iers_table", new=None)
    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_only_sequential_jobs_skips_parallel_block(self, _check, mock_load_config, mock_cache_store):
        """Lines 1279->1289 and 1289->1324: when parallel is empty both branches are taken."""
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        # All day_sensitive=False jobs valid (skipped) → no parallel jobs
        mock_cache_store.is_cache_valid.return_value = True
        # All day_sensitive=True jobs stale → sequential-only jobs_to_run
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.sync_cache_from_shared.return_value = None
        # Prevent spaceflight image-integrity check from importing spaceflight_tracker
        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fully_initialize_caches()  # Should complete without error

        # Only sequential jobs ran → set_cache_initialization_in_progress(False) must be called
        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache_updater.update_iers_cache", side_effect=RuntimeError("iers pre-download failed"))
    @patch("astropy.utils.iers.IERS_Auto.iers_table", new=None)
    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_iers_pre_parallel_exception_is_caught(self, _check, mock_load_config, mock_cache_store, _iers_fn):
        """Lines 1284-1285: exception in pre-parallel IERS download is caught and logged."""
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        # All day_sensitive=False jobs stale → iers is in parallel → pre-download fires
        mock_cache_store.is_cache_valid.return_value = False
        # Skip day_sensitive=True jobs to keep test fast
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fully_initialize_caches()  # Should not raise despite iers failure

        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_iers_table_loaded_and_fresh_skips_predownload(self, _check, mock_load_config, mock_cache_store):
        """Branch 1357->1374: iers_table is loaded and not near expiry → pre-download skipped."""
        from cache_updater import fully_initialize_caches
        from unittest.mock import MagicMock

        mock_load_config.return_value = {"location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}}
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        # Mock a loaded, fresh IERS table (far future MJD → not near expiry)
        mock_table = MagicMock()
        mock_table.__getitem__ = MagicMock(return_value=MagicMock(max=MagicMock(return_value=99999.0)))

        with patch("astropy.utils.iers.IERS_Auto.iers_table", new=mock_table):
            fully_initialize_caches()

        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)


# ---------------------------------------------------------------------------
# update_allsky_sensor_cache
# ---------------------------------------------------------------------------


class TestUpdateAllskySensorCache:
    """Tests for update_allsky_sensor_cache (lines 1059-1076)."""

    def test_returns_early_when_config_is_none_and_allsky_not_in_config(self):
        """When load_config returns no allsky key, function returns without updating cache."""
        import cache_store as cs
        from cache_updater import update_allsky_sensor_cache

        with patch("cache_updater.load_config", return_value={}):
            before_ts = cs._allsky_sensor_cache["timestamp"]
            update_allsky_sensor_cache()
            assert cs._allsky_sensor_cache["timestamp"] == before_ts

    def test_returns_early_when_allsky_disabled(self):
        """enabled=False → return without touching cache."""
        from cache_updater import update_allsky_sensor_cache
        cfg = {"connectors": {"allsky": {"enabled": False, "url": "http://allsky.local", "modules": {}}}}
        import cache_store as cs
        before_ts = cs._allsky_sensor_cache["timestamp"]
        update_allsky_sensor_cache(config=cfg)
        assert cs._allsky_sensor_cache["timestamp"] == before_ts

    def test_returns_early_when_no_url(self):
        """enabled but no url → return without touching cache."""
        from cache_updater import update_allsky_sensor_cache
        cfg = {"connectors": {"allsky": {"enabled": True, "url": "", "modules": {}}}}
        import cache_store as cs
        before_ts = cs._allsky_sensor_cache["timestamp"]
        update_allsky_sensor_cache(config=cfg)
        assert cs._allsky_sensor_cache["timestamp"] == before_ts

    def test_returns_early_when_sensor_module_disabled(self):
        """sensor_data module disabled → return without touching cache."""
        from cache_updater import update_allsky_sensor_cache
        cfg = {"connectors": {"allsky": {
            "enabled": True,
            "url": "http://allsky.local",
            "modules": {"sensor_data": {"enabled": False}},
        }}}
        import cache_store as cs
        before_ts = cs._allsky_sensor_cache["timestamp"]
        update_allsky_sensor_cache(config=cfg)
        assert cs._allsky_sensor_cache["timestamp"] == before_ts

    def test_updates_cache_when_connector_enabled(self):
        """All conditions met → fetch sensor data and update cache."""
        from cache_updater import update_allsky_sensor_cache
        import cache_store as cs

        cfg = {"connectors": {"allsky": {
            "enabled": True,
            "url": "http://allsky.local",
            "modules": {"sensor_data": {"enabled": True}},
        }}}
        sensor_data = {"AS_TEMPERATURE_C": 15.2}
        mock_connector = MagicMock()
        mock_connector.fetch_sensor_data.return_value = sensor_data

        with patch("connectors.allsky_connector.AllSkyConnector", return_value=mock_connector):
            update_allsky_sensor_cache(config=cfg)

        assert cs._allsky_sensor_cache["data"] == sensor_data
        assert cs._allsky_sensor_cache["timestamp"] > 0

    def test_uses_load_config_when_no_config_arg(self):
        """config=None triggers load_config() call."""
        from cache_updater import update_allsky_sensor_cache
        cfg = {"connectors": {"allsky": {
            "enabled": True,
            "url": "http://allsky.local",
            "modules": {"sensor_data": {"enabled": True}},
        }}}
        mock_connector = MagicMock()
        mock_connector.fetch_sensor_data.return_value = {}

        with patch("cache_updater.load_config", return_value=cfg):
            with patch("connectors.allsky_connector.AllSkyConnector", return_value=mock_connector):
                update_allsky_sensor_cache()  # no config arg

        mock_connector.fetch_sensor_data.assert_called_once()


class TestFullyInitializeCachesAllskyJob:
    """Test that allsky job is added to cache_jobs when connector is properly configured."""

    @patch("cache_updater.cache_store")
    @patch("cache_updater.load_config")
    @patch("cache_updater.check_and_handle_config_changes")
    def test_allsky_job_added_when_enabled(self, _check, mock_load_config, mock_cache_store):
        """Line 1260: allsky job appended when connector enabled with sensor_data module."""
        from cache_updater import fully_initialize_caches

        mock_load_config.return_value = {
            "location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"},
            "connectors": {"allsky": {
                "enabled": True,
                "url": "http://allsky.local",
                "modules": {"sensor_data": {"enabled": True}},
            }},
        }
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}
        mock_cache_store._allsky_sensor_cache = {"data": None, "timestamp": 0}

        fully_initialize_caches()  # must run without error

        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)
