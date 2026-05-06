"""
Tests for cache_updater module.
Tests core cache update functions and exception handling.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
import time
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
        mock_sun.return_value.get_today_report.return_value = types.SimpleNamespace(sunrise="06:00", sunset="20:00")

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
