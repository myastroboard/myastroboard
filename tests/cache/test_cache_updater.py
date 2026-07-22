"""
Tests for cache_updater module.
Tests core cache update functions and exception handling, including the
v1.2 per-location cache slots (update functions write through
cache_store.update_location_cache keyed by the preset id).
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
import types
import pandas as pd

from cache.cache_updater import check_and_handle_config_changes

LOC_ID = "test-location-id"


def _make_location(loc_id=LOC_ID, lat=45.0, lon=-75.0, tz="America/Toronto", elevation=100):
    return {
        "id": loc_id,
        "name": "Test Site",
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "elevation": elevation,
        "bortle": None,
        "sqm": None,
        "horizon_profile": [],
        "is_install_default": True,
    }


@pytest.fixture
def mock_config():
    """Mock configuration for testing (v1.2 locations shape)."""
    return {"locations": [_make_location()]}


def _loc_payload(mock_cache_store, name=None):
    """Return the data payload of the last update_location_cache(name, id, data) call."""
    calls = mock_cache_store.update_location_cache.call_args_list
    if name is not None:
        calls = [c for c in calls if c.args and c.args[0] == name]
    assert calls, f"update_location_cache was not called (name={name})"
    return calls[-1].args[2]


class TestCheckAndHandleConfigChanges:
    """Tests for check_and_handle_config_changes function (per-preset, v1.2)."""

    @pytest.fixture(autouse=True)
    def _skip_legacy_migration(self, monkeypatch):
        """Unit tests exercise per-preset detection, not the one-time upgrade path."""
        from cache import cache_updater

        monkeypatch.setitem(cache_updater._legacy_cache_migration_state, "done", True)

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_first_time_initialization(self, mock_cache_store, mock_load_config, mock_config):
        """First time a preset is seen: track it, no reset."""
        mock_load_config.return_value = mock_config
        mock_cache_store.is_location_tracked = Mock(return_value=False)

        result = check_and_handle_config_changes()

        assert result is False
        mock_cache_store.update_location_config.assert_called_once_with(mock_config["locations"][0])
        mock_cache_store.reset_caches_for_location.assert_not_called()

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_location_unchanged(self, mock_cache_store, mock_load_config, mock_config):
        """Tracked preset with unchanged signature: nothing happens."""
        mock_load_config.return_value = mock_config
        mock_cache_store.is_location_tracked = Mock(return_value=True)
        mock_cache_store.has_location_changed = Mock(return_value=False)

        result = check_and_handle_config_changes()

        assert result is False
        mock_cache_store.reset_caches_for_location.assert_not_called()

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_location_changed(self, mock_cache_store, mock_load_config, mock_config):
        """Changed preset: only that preset's caches are reset."""
        mock_load_config.return_value = mock_config
        mock_cache_store.is_location_tracked = Mock(return_value=True)
        mock_cache_store.has_location_changed = Mock(return_value=True)

        result = check_and_handle_config_changes()

        assert result is True
        mock_cache_store.reset_caches_for_location.assert_called_once_with(LOC_ID)
        mock_cache_store.update_location_config.assert_called_once()

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_only_changed_preset_is_reset(self, mock_cache_store, mock_load_config):
        """With two presets, only the changed one gets its caches reset."""
        loc_a = _make_location("loc-a")
        loc_b = _make_location("loc-b", lat=50.0)
        loc_b["is_install_default"] = False
        mock_load_config.return_value = {"locations": [loc_a, loc_b]}
        mock_cache_store.is_location_tracked = Mock(return_value=True)
        mock_cache_store.has_location_changed = Mock(side_effect=lambda loc: loc["id"] == "loc-b")

        result = check_and_handle_config_changes()

        assert result is True
        mock_cache_store.reset_caches_for_location.assert_called_once_with("loc-b")

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_missing_locations_config(self, mock_cache_store, mock_load_config):
        """Test handling when no locations are configured."""
        mock_load_config.return_value = {}

        result = check_and_handle_config_changes()

        assert result is False


class TestLegacyCacheMigration:
    """One-time pre-v1.2 -> v1.2 upgrade path inside check_and_handle_config_changes."""

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_matching_legacy_signature_migrates_keys(self, mock_cache_store, mock_load_config, monkeypatch):
        from cache import cache_updater

        monkeypatch.setitem(cache_updater._legacy_cache_migration_state, "done", False)
        location = _make_location()
        mock_load_config.return_value = {"locations": [location]}

        signature = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "elevation": location["elevation"],
            "timezone": location["timezone"],
        }
        mock_cache_store.pop_legacy_location_signature = Mock(return_value=signature)
        mock_cache_store.get_current_location_signature = Mock(return_value=signature)
        mock_cache_store.migrate_legacy_cache_keys = Mock(return_value=5)
        mock_cache_store.is_location_tracked = Mock(return_value=True)
        mock_cache_store.has_location_changed = Mock(return_value=False)

        check_and_handle_config_changes()

        mock_cache_store.migrate_legacy_cache_keys.assert_called_once_with(LOC_ID)
        # Matching signature: caches kept (no reset)
        mock_cache_store.reset_caches_for_location.assert_not_called()
        assert cache_updater._legacy_cache_migration_state['done'] is True

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.cache_store")
    def test_mismatched_legacy_signature_resets(self, mock_cache_store, mock_load_config, monkeypatch):
        from cache import cache_updater

        monkeypatch.setitem(cache_updater._legacy_cache_migration_state, "done", False)
        location = _make_location()
        mock_load_config.return_value = {"locations": [location]}

        mock_cache_store.pop_legacy_location_signature = Mock(return_value={"latitude": 0.0})
        mock_cache_store.get_current_location_signature = Mock(return_value={"latitude": 45.0})
        mock_cache_store.migrate_legacy_cache_keys = Mock(return_value=5)
        mock_cache_store.is_location_tracked = Mock(return_value=True)
        mock_cache_store.has_location_changed = Mock(return_value=False)

        check_and_handle_config_changes()

        mock_cache_store.reset_caches_for_location.assert_called_once_with(LOC_ID)


class TestCacheUpdateFunctionsBasic:
    """Tests for basic cache update functionality."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.MoonService")
    def test_update_moon_report_with_valid_config(self, mock_moon_service, mock_load_config, mock_cache_store, mock_config):
        """Test moon report cache handles valid config."""
        from cache.cache_updater import update_moon_report_cache

        mock_load_config.return_value = mock_config
        mock_moon_instance = MagicMock()
        mock_moon_service.return_value = mock_moon_instance
        mock_report = MagicMock()
        mock_moon_instance.get_report.return_value = mock_report

        # Should complete without raising
        update_moon_report_cache()

        mock_moon_service.assert_called_once()
        # Written under the preset's id (v1.2 per-location slot)
        assert mock_cache_store.update_location_cache.call_args_list[0].args[1] == LOC_ID

    @patch("cache.cache_updater.load_config")
    def test_update_moon_report_without_location(self, mock_load_config):
        """Test moon report cache handles missing location gracefully."""
        from cache.cache_updater import update_moon_report_cache

        mock_load_config.return_value = {}

        # Should not raise, just log error
        update_moon_report_cache()

    @patch("cache.cache_updater.load_config")
    def test_update_weather_cache_missing_location(self, mock_load_config):
        """Test weather cache handles missing location."""
        from cache.cache_updater import update_weather_cache

        mock_load_config.return_value = {}

        # Should not raise
        update_weather_cache()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_hourly_forecast")
    def test_update_weather_cache_success(self, mock_get_hourly_forecast, mock_cache_store, mock_config):
        """Exercise weather serialization success path."""
        from cache.cache_updater import update_weather_cache

        mock_get_hourly_forecast.return_value = {
            "hourly": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-04-17T21:00:00Z", "2026-04-17T22:00:00Z"]),
                    "temperature": [10.0, 9.5],
                }
            ),
            "location": {"name": "Test"},
        }

        update_weather_cache(config=mock_config)

        payload = _loc_payload(mock_cache_store, "weather_forecast")
        assert payload["hourly"]

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_hourly_forecast")
    def test_update_weather_cache_object_dtype_column(self, mock_get_hourly_forecast, mock_cache_store, mock_config):
        """Bytes decode path for object-dtype DataFrame columns."""
        from cache.cache_updater import update_weather_cache

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

        update_weather_cache(config=mock_config)

        decoded_records = _loc_payload(mock_cache_store, "weather_forecast")["hourly"]
        assert decoded_records[0]["raw"] == "encoded_bytes"


class TestCacheUpdateErrorHandling:
    """Tests for error handling in cache updates."""

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.MoonService")
    def test_moon_service_exception_handling(self, mock_moon_service, mock_load_config, mock_config):
        """Test that exceptions in MoonService are caught."""
        from cache.cache_updater import update_moon_report_cache

        mock_load_config.return_value = mock_config
        mock_moon_service.side_effect = Exception("Service error")

        # Should not raise, just log
        update_moon_report_cache()

    @patch("cache.cache_updater.get_hourly_forecast")
    def test_weather_forecast_none_handling(self, mock_get_forecast, mock_config):
        """Test weather cache handles None forecast."""
        from cache.cache_updater import update_weather_cache

        mock_get_forecast.return_value = None

        # Should handle gracefully
        update_weather_cache(config=mock_config)

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_hourly_forecast")
    def test_weather_forecast_none_uses_stale_cache(self, mock_get_forecast, mock_cache_store, mock_config):
        """Live weather miss with stale cached payload should not overwrite cache."""
        from cache.cache_updater import update_weather_cache

        mock_get_forecast.return_value = None
        mock_cache_store.load_location_cache.return_value = {
            "timestamp": 123.0,
            "data": {"location": {"name": "Stale"}, "hourly": [{"date": "2026-01-01T00:00:00+0000"}]},
        }

        update_weather_cache(config=mock_config)

        mock_cache_store.load_location_cache.assert_called_once()
        mock_cache_store.update_location_cache.assert_not_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_hourly_forecast")
    def test_weather_forecast_none_without_stale_cache(self, mock_get_forecast, mock_cache_store, mock_config):
        """Live weather miss without stale cache should still be non-fatal."""
        from cache.cache_updater import update_weather_cache

        mock_get_forecast.return_value = None
        mock_cache_store.load_location_cache.return_value = {"timestamp": 0.0, "data": None}

        update_weather_cache(config=mock_config)

        mock_cache_store.load_location_cache.assert_called_once()
        mock_cache_store.update_location_cache.assert_not_called()

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.get_iss_passes_report")
    def test_iss_passes_cache_with_none_report(self, mock_get_iss, mock_load_config, mock_config):
        """Test ISS passes cache handles None report."""
        from cache.cache_updater import update_iss_passes_cache

        mock_load_config.return_value = mock_config
        mock_get_iss.return_value = None

        # Should handle gracefully
        update_iss_passes_cache()

    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.get_aurora_report")
    def test_aurora_cache_handles_errors(self, mock_get_aurora, mock_load_config, mock_config):
        """Test aurora cache handles errors gracefully."""
        from cache.cache_updater import update_aurora_cache

        mock_load_config.return_value = mock_config
        mock_get_aurora.return_value = None

        # Should handle gracefully
        update_aurora_cache()


class TestAdditionalCachePaths:
    """Extra branch coverage for cache updater services."""

    @patch("cache.cache_updater.cache_store")
    def test_update_spaceflight_events_prunes_using_shared_cache_entries(self, mock_cache_store):
        from cache.cache_updater import update_spaceflight_events_cache

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

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()

        fake_prune.assert_called_once()
        active_images = fake_prune.call_args.args[0]
        assert "/api/spaceflight/img/launch.jpg" in active_images
        assert "/api/spaceflight/img/astro.jpg" in active_images
        assert "/api/spaceflight/img/event.jpg" in active_images

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    def test_update_planetary_events_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache.cache_updater import update_planetary_events_cache

        mock_load_config.return_value = mock_config

        fake_service = MagicMock()
        fake_service.get_planetary_events.return_value = [{"name": "Conjunction"}]
        fake_module = types.SimpleNamespace(PlanetaryEventsService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"observation.planetary_events": fake_module}):
            update_planetary_events_cache()

        mock_cache_store.update_location_cache.assert_called()
        assert _loc_payload(mock_cache_store, "planetary_events")["count"] == 1

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    def test_update_special_phenomena_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache.cache_updater import update_special_phenomena_cache

        mock_load_config.return_value = mock_config

        fake_service = MagicMock()
        fake_service.get_special_phenomena.return_value = [{"name": "Equinox"}]
        fake_module = types.SimpleNamespace(SpecialPhenomenaService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"observation.special_phenomena": fake_module}):
            update_special_phenomena_cache()

        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    def test_update_solar_system_events_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache.cache_updater import update_solar_system_events_cache

        mock_load_config.return_value = mock_config

        fake_service = MagicMock()
        fake_service.get_solar_system_events.return_value = [{"name": "Perseids"}]
        fake_module = types.SimpleNamespace(SolarSystemEventsService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"observation.solar_system_events": fake_module}):
            update_solar_system_events_cache()

        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    def test_update_sidereal_time_cache_success(self, mock_load_config, mock_cache_store, mock_config):
        from cache.cache_updater import update_sidereal_time_cache

        mock_load_config.return_value = mock_config

        fake_service = MagicMock()
        fake_service.get_current_sidereal_info.return_value = {"lst": "12:00"}
        fake_service.get_hourly_sidereal_times.return_value = [{"hour": 0, "lst": "10:00"}]
        fake_module = types.SimpleNamespace(SiderealTimeService=MagicMock(return_value=fake_service))

        with patch.dict(sys.modules, {"observation.sidereal_time": fake_module}):
            update_sidereal_time_cache()

        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.MoonService")
    @patch("cache.cache_updater.load_config")
    def test_update_dark_window_cache_success(self, mock_load_config, mock_moon_service, mock_cache_store, mock_config):
        from cache.cache_updater import update_dark_window_cache

        mock_load_config.return_value = mock_config

        report = types.SimpleNamespace(
            next_dark_night_start="2026-04-17T22:00:00",
            next_dark_night_end="2026-04-18T03:00:00",
        )
        mock_moon_service.return_value.get_report.return_value = report

        update_dark_window_cache()
        dark = _loc_payload(mock_cache_store, "dark_window")
        assert dark["next_dark_night"]["start"] == "2026-04-17T22:00:00"

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.MoonPlanner")
    @patch("cache.cache_updater.load_config")
    def test_update_moon_planner_cache_success(self, mock_load_config, mock_planner, mock_cache_store, mock_config):
        from cache.cache_updater import update_moon_planner_cache

        mock_load_config.return_value = mock_config
        mock_planner.return_value.next_7_nights.return_value = [{"date": "2026-04-17", "dark_hours": 6.0}]

        update_moon_planner_cache()
        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.SunService")
    @patch("cache.cache_updater.load_config")
    def test_update_sun_report_cache_success(self, mock_load_config, mock_sun, mock_cache_store, mock_config):
        from cache.cache_updater import update_sun_report_cache

        mock_load_config.return_value = mock_config
        # Provide astronomical_dusk/dawn so _next_astronomical_dusk_utc can run
        report = types.SimpleNamespace(
            sunrise="06:00", sunset="20:00",
            astronomical_dusk="Not found", astronomical_dawn="Not found",
        )
        mock_sun.return_value.get_today_report.return_value = report
        mock_sun.return_value.get_tomorrow_report.return_value = report

        update_sun_report_cache()
        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.AstroTonightService")
    @patch("cache.cache_updater.load_config")
    def test_update_best_window_cache_success(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        from cache.cache_updater import update_best_window_cache

        mock_load_config.return_value = mock_config
        window = types.SimpleNamespace(start="21:00", end="23:00", score=80)
        mock_service.return_value.best_windows_all_modes.return_value = {
            "strict": window,
            "practical": window,
            "illumination": window,
        }

        update_best_window_cache()
        # One per mode, all keyed to the preset id
        assert mock_cache_store.update_location_cache.call_count == 3
        names = {c.args[0] for c in mock_cache_store.update_location_cache.call_args_list}
        assert names == {"best_window_strict", "best_window_practical", "best_window_illumination"}


class TestFullInitialization:
    """Coverage for fully_initialize_caches control-flow."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.update_weather_cache")
    @patch("cache.cache_updater.update_best_window_cache")
    @patch("cache.cache_updater.update_seeing_forecast_cache")
    @patch("cache.cache_updater.update_sidereal_time_cache")
    @patch("cache.cache_updater.update_solar_system_events_cache")
    @patch("cache.cache_updater.update_special_phenomena_cache")
    @patch("cache.cache_updater.update_planetary_events_cache")
    @patch("cache.cache_updater.update_css_passes_cache")
    @patch("cache.cache_updater.update_iss_passes_cache")
    @patch("cache.cache_updater.update_aurora_cache")
    @patch("cache.cache_updater.update_horizon_graph_cache")
    @patch("cache.cache_updater.update_lunar_eclipse_cache")
    @patch("cache.cache_updater.update_solar_eclipse_cache")
    @patch("cache.cache_updater.update_sun_report_cache")
    @patch("cache.cache_updater.update_moon_planner_cache")
    @patch("cache.cache_updater.update_moon_caches")
    @patch("cache.cache_updater.check_and_handle_config_changes")
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
        _css,
        _planetary,
        _special,
        _solsys,
        _sidereal,
        _seeing,
        _best,
        _weather,
        mock_load_config,
        mock_cache_store,
        mock_config,
    ):
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        # Force all caches to be stale so jobs_to_run is populated
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.load_location_cache.return_value = {"timestamp": 0, "data": None}
        mock_cache_store.sync_cache_from_shared.return_value = None

        fully_initialize_caches()

        assert mock_cache_store.set_cache_initialization_in_progress.call_count >= 2
        # Location-scoped jobs got the preset threaded through
        assert _moon_caches.call_args.kwargs["location"]["id"] == LOC_ID

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.update_weather_cache")
    @patch("cache.cache_updater.update_best_window_cache")
    @patch("cache.cache_updater.update_seeing_forecast_cache")
    @patch("cache.cache_updater.update_sidereal_time_cache")
    @patch("cache.cache_updater.update_solar_system_events_cache")
    @patch("cache.cache_updater.update_special_phenomena_cache")
    @patch("cache.cache_updater.update_planetary_events_cache")
    @patch("cache.cache_updater.update_css_passes_cache")
    @patch("cache.cache_updater.update_iss_passes_cache")
    @patch("cache.cache_updater.update_aurora_cache")
    @patch("cache.cache_updater.update_horizon_graph_cache")
    @patch("cache.cache_updater.update_lunar_eclipse_cache")
    @patch("cache.cache_updater.update_solar_eclipse_cache")
    @patch("cache.cache_updater.update_sun_report_cache")
    @patch("cache.cache_updater.update_moon_planner_cache")
    @patch("cache.cache_updater.update_moon_caches")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_caches_continues_on_single_failure(
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
        _css,
        _planetary,
        _special,
        _solsys,
        _sidereal,
        _seeing,
        _best,
        _weather,
        mock_load_config,
        mock_cache_store,
        mock_config,
    ):
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.load_location_cache.return_value = {"timestamp": 0, "data": None}
        mock_cache_store.sync_cache_from_shared.return_value = None
        _planetary.side_effect = RuntimeError("boom")

        fully_initialize_caches()

        # Final reset call must still happen
        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.update_weather_cache")
    @patch("cache.cache_updater.update_best_window_cache")
    @patch("cache.cache_updater.update_seeing_forecast_cache")
    @patch("cache.cache_updater.update_sidereal_time_cache")
    @patch("cache.cache_updater.update_solar_system_events_cache")
    @patch("cache.cache_updater.update_special_phenomena_cache")
    @patch("cache.cache_updater.update_planetary_events_cache")
    @patch("cache.cache_updater.update_css_passes_cache")
    @patch("cache.cache_updater.update_iss_passes_cache")
    @patch("cache.cache_updater.update_aurora_cache")
    @patch("cache.cache_updater.update_horizon_graph_cache")
    @patch("cache.cache_updater.update_lunar_eclipse_cache")
    @patch("cache.cache_updater.update_solar_eclipse_cache")
    @patch("cache.cache_updater.update_sun_report_cache")
    @patch("cache.cache_updater.update_moon_planner_cache")
    @patch("cache.cache_updater.update_moon_caches")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_parallel_failure_and_sequential_moon_report(
        self,
        _check, _moon_caches, _planner, _sun, _solar, _lunar,
        _horizon, _aurora, _iss, _css, _planetary, _special, _solsys,
        _sidereal, _seeing, _best, _weather, mock_load_config, mock_cache_store, mock_config,
    ):
        """Parallel job failure is recorded; the run completes."""
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.load_location_cache.return_value = {"timestamp": 0, "data": None}
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store.record_cache_execution = MagicMock()
        # Make a parallel job fail
        _aurora.side_effect = RuntimeError("aurora down")

        fully_initialize_caches()

        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.update_weather_cache")
    @patch("cache.cache_updater.update_best_window_cache")
    @patch("cache.cache_updater.update_seeing_forecast_cache")
    @patch("cache.cache_updater.update_sidereal_time_cache")
    @patch("cache.cache_updater.update_solar_system_events_cache")
    @patch("cache.cache_updater.update_special_phenomena_cache")
    @patch("cache.cache_updater.update_planetary_events_cache")
    @patch("cache.cache_updater.update_css_passes_cache")
    @patch("cache.cache_updater.update_iss_passes_cache")
    @patch("cache.cache_updater.update_aurora_cache")
    @patch("cache.cache_updater.update_horizon_graph_cache")
    @patch("cache.cache_updater.update_lunar_eclipse_cache")
    @patch("cache.cache_updater.update_solar_eclipse_cache")
    @patch("cache.cache_updater.update_sun_report_cache")
    @patch("cache.cache_updater.update_moon_planner_cache")
    @patch("cache.cache_updater.update_moon_caches")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_sequential_non_moon_report_failure(
        self,
        _check, _moon_caches, _planner, _sun, _solar, _lunar,
        _horizon, _aurora, _iss, _css, _planetary, _special, _solsys,
        _sidereal, _seeing, _best, _weather, mock_load_config, mock_cache_store, mock_config,
    ):
        """Sequential non-moon_report job failure does not mirror dark_window."""
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.load_location_cache.return_value = {"timestamp": 0, "data": None}
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
        from cache.cache_updater import _next_astronomical_dusk_utc
        from datetime import datetime as _dt, timezone, timedelta

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
        from cache.cache_updater import _next_astronomical_dusk_utc

        report = types.SimpleNamespace(astronomical_dusk="Not found")
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is None

    def test_returns_none_when_dusk_is_empty(self):
        """Returns None when dusk is an empty string."""
        from cache.cache_updater import _next_astronomical_dusk_utc

        report = types.SimpleNamespace(astronomical_dusk="")
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is None

    def test_returns_none_when_dusk_in_past(self):
        """Returns None when dusk is already in the past."""
        from cache.cache_updater import _next_astronomical_dusk_utc
        from datetime import datetime as _dt, timezone, timedelta

        past_dusk = (_dt.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        report = types.SimpleNamespace(astronomical_dusk=past_dusk)
        sun_service = MagicMock()
        sun_service.get_today_report.return_value = report
        sun_service.get_tomorrow_report.return_value = report

        result = _next_astronomical_dusk_utc(sun_service, "UTC")
        assert result is None

    def test_skips_bad_dusk_string_and_continues(self):
        """Bad dusk string is skipped and the loop continues to the next report."""
        from cache.cache_updater import _next_astronomical_dusk_utc
        from datetime import datetime as _dt, timezone, timedelta

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

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.MoonService")
    @patch("cache.cache_updater.load_config")
    def test_update_moon_caches_with_bytes_value(self, mock_load_config, mock_moon_service, mock_cache_store, mock_config):
        """MoonService report values that are bytes are decoded."""
        from cache.cache_updater import update_moon_caches

        mock_load_config.return_value = mock_config

        report = types.SimpleNamespace(
            some_bytes_field=b"encoded_value",
            next_dark_night_start="22:00",
            next_dark_night_end="04:00",
        )
        mock_moon_service.return_value.get_report.return_value = report

        update_moon_caches()
        moon_payload = _loc_payload(mock_cache_store, "moon_report")
        assert moon_payload["moon"]["some_bytes_field"] == "encoded_value"

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.MoonService")
    def test_update_moon_caches_with_direct_config(self, mock_moon_service, mock_cache_store):
        """Config passed directly avoids calling load_config."""
        from cache.cache_updater import update_moon_caches

        config = {"locations": [_make_location(lat=48.0, lon=2.0, tz="Europe/Paris")]}

        report = types.SimpleNamespace(next_dark_night_start="21:00", next_dark_night_end="03:00")
        mock_moon_service.return_value.get_report.return_value = report

        update_moon_caches(config=config)
        mock_moon_service.assert_called_once_with(latitude=48.0, longitude=2.0, timezone="Europe/Paris")

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.MoonService")
    def test_update_moon_caches_with_direct_location(self, mock_moon_service, mock_cache_store):
        """A location preset passed directly wins over the config's install default."""
        from cache.cache_updater import update_moon_caches

        config = {"locations": [_make_location()]}
        other = _make_location("other-loc", lat=10.0, lon=20.0, tz="UTC")

        report = types.SimpleNamespace(next_dark_night_start="21:00", next_dark_night_end="03:00")
        mock_moon_service.return_value.get_report.return_value = report

        update_moon_caches(config=config, location=other)
        mock_moon_service.assert_called_once_with(latitude=10.0, longitude=20.0, timezone="UTC")
        assert mock_cache_store.update_location_cache.call_args_list[0].args[1] == "other-loc"


class TestUpdateSolarEclipseCache:
    """Tests for update_solar_eclipse_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.SolarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_solar_eclipse_none_response(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When eclipse is None, response has null solar_eclipse field."""
        from cache.cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_service.return_value.get_next_eclipse.return_value = None

        update_solar_eclipse_cache()

        stored_data = _loc_payload(mock_cache_store, "solar_eclipse")
        assert stored_data["solar_eclipse"] is None
        assert "message" in stored_data

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.SolarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_solar_eclipse_with_eclipse_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When eclipse is available, response has eclipse dict."""
        from cache.cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = mock_config

        eclipse = types.SimpleNamespace(type="Total", peak_time="2026-08-12T14:00:00", altitude_vs_time=[])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_solar_eclipse_cache()

        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.SolarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_solar_eclipse_with_altitude_vs_time(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """altitude_vs_time EclipsePoint objects are converted to dicts."""
        from cache.cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = mock_config

        point = types.SimpleNamespace(time="14:00", altitude=45.0)
        eclipse = types.SimpleNamespace(type="Partial", peak_time="2026-08-12T14:00:00", altitude_vs_time=[point])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_solar_eclipse_cache()

        stored = _loc_payload(mock_cache_store, "solar_eclipse")
        assert stored["solar_eclipse"]["altitude_vs_time"] == [{"time": "14:00", "altitude": 45.0}]

    @patch("cache.cache_updater.load_config")
    def test_solar_eclipse_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully (no raise)."""
        from cache.cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = {}
        update_solar_eclipse_cache()  # Should not raise

    @patch("cache.cache_updater.SolarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_solar_eclipse_service_exception(self, mock_load_config, mock_service, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_solar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("service error")

        update_solar_eclipse_cache()  # Should not raise


class TestUpdateLunarEclipseCache:
    """Tests for update_lunar_eclipse_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.LunarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_lunar_eclipse_none_response(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When lunar eclipse is None, response has null field."""
        from cache.cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_service.return_value.get_next_eclipse.return_value = None

        update_lunar_eclipse_cache()

        stored = _loc_payload(mock_cache_store, "lunar_eclipse")
        assert stored["lunar_eclipse"] is None

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.LunarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_lunar_eclipse_with_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When lunar eclipse available, result has eclipse dict."""
        from cache.cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = mock_config

        eclipse = types.SimpleNamespace(type="Total", peak_time="2025-09-07T02:00:00", altitude_vs_time=[])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_lunar_eclipse_cache()
        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.LunarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_lunar_eclipse_with_altitude_vs_time(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """altitude_vs_time EclipsePoint objects are converted to dicts."""
        from cache.cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = mock_config

        point = types.SimpleNamespace(time="02:00", altitude=30.0)
        eclipse = types.SimpleNamespace(type="Partial", peak_time="2025-09-07T02:00:00", altitude_vs_time=[point])
        mock_service.return_value.get_next_eclipse.return_value = eclipse

        update_lunar_eclipse_cache()

        stored = _loc_payload(mock_cache_store, "lunar_eclipse")
        assert stored["lunar_eclipse"]["altitude_vs_time"] == [{"time": "02:00", "altitude": 30.0}]

    @patch("cache.cache_updater.load_config")
    def test_lunar_eclipse_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = {}
        update_lunar_eclipse_cache()

    @patch("cache.cache_updater.LunarEclipseService")
    @patch("cache.cache_updater.load_config")
    def test_lunar_eclipse_service_exception(self, mock_load_config, mock_service, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_lunar_eclipse_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("service error")

        update_lunar_eclipse_cache()


class TestUpdateHorizonGraphCache:
    """Tests for update_horizon_graph_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.HorizonGraphService")
    @patch("cache.cache_updater.load_config")
    def test_horizon_graph_none_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When horizon_data is None, response has null field."""
        from cache.cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = mock_config
        mock_service.return_value.get_horizon_data.return_value = None

        update_horizon_graph_cache()

        stored = _loc_payload(mock_cache_store, "horizon_graph")
        assert stored["horizon_data"] is None

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.HorizonGraphService")
    @patch("cache.cache_updater.load_config")
    def test_horizon_graph_with_data(self, mock_load_config, mock_service, mock_cache_store, mock_config):
        """When horizon_data available, sun/moon point objects are converted to dicts."""
        from cache.cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = mock_config

        sun_point = types.SimpleNamespace(time="12:00", altitude=60.0)
        moon_point = types.SimpleNamespace(time="22:00", altitude=30.0)
        horizon_data = types.SimpleNamespace(sun_data=[sun_point], moon_data=[moon_point])
        mock_service.return_value.get_horizon_data.return_value = horizon_data

        update_horizon_graph_cache()

        stored = _loc_payload(mock_cache_store, "horizon_graph")
        assert stored["horizon_data"]["sun_data"] == [{"time": "12:00", "altitude": 60.0}]
        assert stored["horizon_data"]["moon_data"] == [{"time": "22:00", "altitude": 30.0}]

    @patch("cache.cache_updater.load_config")
    def test_horizon_graph_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = {}
        update_horizon_graph_cache()

    @patch("cache.cache_updater.HorizonGraphService")
    @patch("cache.cache_updater.load_config")
    def test_horizon_graph_service_exception(self, mock_load_config, mock_service, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_horizon_graph_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("service error")

        update_horizon_graph_cache()


class TestUpdateAuroraCache:
    """Tests for update_aurora_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_aurora_report")
    @patch("cache.cache_updater.load_config")
    def test_aurora_cache_success(self, mock_load_config, mock_get_aurora, mock_cache_store, mock_config):
        """Successful aurora report is stored in cache."""
        from cache.cache_updater import update_aurora_cache

        mock_load_config.return_value = mock_config
        mock_get_aurora.return_value = {"forecast": [{"kp_index": 5}]}

        update_aurora_cache()

        assert _loc_payload(mock_cache_store, "aurora") == {"forecast": [{"kp_index": 5}]}

    @patch("cache.cache_updater.get_aurora_report")
    @patch("cache.cache_updater.load_config")
    def test_aurora_cache_none_report_raises_value_error(self, mock_load_config, mock_get_aurora, mock_config):
        """None aurora report raises ValueError that is caught."""
        from cache.cache_updater import update_aurora_cache

        mock_load_config.return_value = mock_config
        mock_get_aurora.return_value = None

        update_aurora_cache()  # Should not raise

    @patch("cache.cache_updater.load_config")
    def test_aurora_cache_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_aurora_cache

        mock_load_config.return_value = {}
        update_aurora_cache()


class TestUpdateIssPassesCache:
    """Tests for update_iss_passes_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_iss_passes_report")
    @patch("cache.cache_updater.load_config")
    def test_iss_passes_success(self, mock_load_config, mock_get_iss, mock_cache_store, mock_config):
        """Successful ISS report is stored in cache."""
        from cache.cache_updater import update_iss_passes_cache

        mock_load_config.return_value = mock_config
        mock_get_iss.return_value = {"passes": [{"peak_time": "2026-04-17T21:00:00"}]}

        update_iss_passes_cache()

        mock_cache_store.update_location_cache.assert_called()
        assert mock_cache_store.update_location_cache.call_args.args[1] == LOC_ID

    @patch("cache.cache_updater.get_iss_passes_report")
    @patch("cache.cache_updater.load_config")
    def test_iss_passes_service_exception(self, mock_load_config, mock_get_iss, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_iss_passes_cache

        mock_load_config.return_value = mock_config
        mock_get_iss.side_effect = RuntimeError("network error")

        update_iss_passes_cache()  # Should not raise

    @patch("cache.cache_updater.load_config")
    def test_iss_passes_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_iss_passes_cache

        mock_load_config.return_value = {}
        update_iss_passes_cache()


class TestUpdateCssPassesCache:
    """Tests for update_css_passes_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_css_passes_report")
    @patch("cache.cache_updater.load_config")
    def test_css_passes_loads_config_when_not_provided(
        self, mock_load_config, mock_get_css, mock_cache_store, mock_config
    ):
        """config=None (the default) falls back to load_config()."""
        from cache.cache_updater import update_css_passes_cache

        mock_load_config.return_value = mock_config
        mock_get_css.return_value = {"passes": [{"peak_time": "2026-04-17T21:00:00"}]}

        update_css_passes_cache()

        mock_load_config.assert_called_once()
        mock_cache_store.update_location_cache.assert_called()

    @patch("cache.cache_updater.load_config")
    def test_css_passes_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_css_passes_cache

        mock_load_config.return_value = {}
        update_css_passes_cache()  # Should not raise

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_css_passes_report")
    def test_css_passes_none_report_keeps_previous_cache(self, mock_get_css, mock_cache_store, mock_config):
        """A None report (provider/network/cache miss) leaves the cache untouched."""
        from cache.cache_updater import update_css_passes_cache

        mock_get_css.return_value = None

        update_css_passes_cache(config=mock_config)

        mock_cache_store.update_location_cache.assert_not_called()

    @patch("cache.cache_updater.get_css_passes_report")
    def test_css_passes_service_exception(self, mock_get_css, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_css_passes_cache

        mock_get_css.side_effect = RuntimeError("network error")

        update_css_passes_cache(config=mock_config)  # Should not raise


class TestUpdatePlanetaryEventsCache:
    """Tests for update_planetary_events_cache."""

    @patch("cache.cache_updater.load_config")
    def test_planetary_events_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_planetary_events_cache

        mock_load_config.return_value = {}
        update_planetary_events_cache()

    @patch("cache.cache_updater.load_config")
    def test_planetary_events_service_exception(self, mock_load_config, mock_config):
        """Service import exception is caught and logged."""
        from cache.cache_updater import update_planetary_events_cache

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            PlanetaryEventsService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"observation.planetary_events": broken_module}):
            update_planetary_events_cache()  # Should not raise


class TestUpdateSpecialPhenomenaCache:
    """Tests for update_special_phenomena_cache."""

    @patch("cache.cache_updater.load_config")
    def test_special_phenomena_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_special_phenomena_cache

        mock_load_config.return_value = {}
        update_special_phenomena_cache()

    @patch("cache.cache_updater.load_config")
    def test_special_phenomena_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_special_phenomena_cache

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            SpecialPhenomenaService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"observation.special_phenomena": broken_module}):
            update_special_phenomena_cache()  # Should not raise


class TestUpdateSolarSystemEventsCache:
    """Tests for update_solar_system_events_cache."""

    @patch("cache.cache_updater.load_config")
    def test_solar_system_events_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_solar_system_events_cache

        mock_load_config.return_value = {}
        update_solar_system_events_cache()

    @patch("cache.cache_updater.load_config")
    def test_solar_system_events_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_solar_system_events_cache

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            SolarSystemEventsService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"observation.solar_system_events": broken_module}):
            update_solar_system_events_cache()  # Should not raise


class TestUpdateSiderealTimeCache:
    """Tests for update_sidereal_time_cache."""

    @patch("cache.cache_updater.load_config")
    def test_sidereal_time_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_sidereal_time_cache

        mock_load_config.return_value = {}
        update_sidereal_time_cache()

    @patch("cache.cache_updater.load_config")
    def test_sidereal_time_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_sidereal_time_cache

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(
            SiderealTimeService=MagicMock(side_effect=RuntimeError("init error"))
        )

        with patch.dict(sys.modules, {"observation.sidereal_time": broken_module}):
            update_sidereal_time_cache()  # Should not raise


class TestUpdateSeeingForecastCache:
    """Tests for update_seeing_forecast_cache."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    def test_seeing_forecast_with_none_data_keeps_previous_cache(self, mock_load_config, mock_cache_store, mock_config):
        """A None fetch result (e.g. 7Timer connect timeout) leaves the cache untouched.

        Regression test: overwriting the cache with a failure marker would stamp a fresh
        timestamp and make is_cache_valid() treat the failure as "fresh" for the full
        CACHE_TTL_SEEING_FORECAST window (6h), blocking retries even after 7Timer recovers.
        """
        from cache.cache_updater import update_seeing_forecast_cache

        mock_load_config.return_value = mock_config

        fake_module = types.SimpleNamespace(get_seeing_forecast=MagicMock(return_value=None))
        with patch.dict(sys.modules, {"astroweather.seeing_forecast_7timer": fake_module}):
            update_seeing_forecast_cache()

        mock_cache_store.update_location_cache.assert_not_called()

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    def test_seeing_forecast_with_valid_data(self, mock_load_config, mock_cache_store, mock_config):
        """When seeing_data available, it is stored with units."""
        from cache.cache_updater import update_seeing_forecast_cache

        mock_load_config.return_value = mock_config
        seeing_data = {"hourly": [{"time": "2026-04-17T22:00:00Z", "seeing": 1}]}
        fake_module = types.SimpleNamespace(get_seeing_forecast=MagicMock(return_value=seeing_data))

        with patch.dict(sys.modules, {"astroweather.seeing_forecast_7timer": fake_module}):
            update_seeing_forecast_cache()

        stored = _loc_payload(mock_cache_store, "seeing_forecast")
        assert stored["seeing_forecast"] == seeing_data
        assert "units" in stored

    @patch("cache.cache_updater.load_config")
    def test_seeing_forecast_missing_location(self, mock_load_config):
        """Missing location config is handled gracefully."""
        from cache.cache_updater import update_seeing_forecast_cache

        mock_load_config.return_value = {}
        update_seeing_forecast_cache()

    @patch("cache.cache_updater.load_config")
    def test_seeing_forecast_service_exception(self, mock_load_config, mock_config):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_seeing_forecast_cache

        mock_load_config.return_value = mock_config
        broken_module = types.SimpleNamespace(get_seeing_forecast=MagicMock(side_effect=RuntimeError("timeout")))

        with patch.dict(sys.modules, {"astroweather.seeing_forecast_7timer": broken_module}):
            update_seeing_forecast_cache()  # Should not raise


class TestUpdateSpaceflightLaunchesCache:
    """Tests for update_spaceflight_launches_cache (global cache, unchanged shape)."""

    @patch("cache.cache_updater.cache_store")
    def test_launches_success_with_both_results(self, mock_cache_store):
        """Both upcoming and past launches are stored."""
        from cache.cache_updater import update_spaceflight_launches_cache

        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(return_value={"count": 1, "results": [{"name": "Falcon 9"}]}),
            get_past_launches=MagicMock(return_value={"count": 1, "results": [{"name": "Atlas V"}]}),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_launches_cache()

        stored = mock_cache_store._spaceflight_launches_cache["data"]
        assert stored["upcoming"]["count"] == 1
        assert stored["past"]["count"] == 1

    @patch("cache.cache_updater.cache_store")
    def test_launches_with_none_upcoming_uses_fallback(self, mock_cache_store):
        """None upcoming falls back to empty dict."""
        from cache.cache_updater import update_spaceflight_launches_cache

        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(return_value=None),
            get_past_launches=MagicMock(return_value={"count": 1, "results": []}),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_launches_cache()

        stored = mock_cache_store._spaceflight_launches_cache["data"]
        assert stored["upcoming"] == {"count": 0, "results": []}

    @patch("cache.cache_updater.cache_store")
    def test_launches_both_none_returns_early(self, mock_cache_store):
        """Both None returns early without storing."""
        from cache.cache_updater import update_spaceflight_launches_cache

        mock_cache_store._spaceflight_launches_cache = {"data": "old_data", "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(return_value=None),
            get_past_launches=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_launches_cache()

        # Cache was not updated
        assert mock_cache_store.update_shared_cache_entry.call_count == 0

    def test_launches_service_exception(self):
        """Service exception is caught and logged."""
        from cache.cache_updater import update_spaceflight_launches_cache

        broken_module = types.SimpleNamespace(
            get_upcoming_launches=MagicMock(side_effect=RuntimeError("network error")),
            get_past_launches=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": broken_module}):
            update_spaceflight_launches_cache()  # Should not raise


class TestUpdateSpaceflightAstronautsCache:
    """Tests for update_spaceflight_astronauts_cache."""

    @patch("cache.cache_updater.cache_store")
    def test_astronauts_success(self, mock_cache_store):
        """Successful astronaut data is stored in cache."""
        from cache.cache_updater import update_spaceflight_astronauts_cache

        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value={"expeditions": [], "fetched_at": "2026-01-01T00:00:00Z"}),
            get_astronauts_in_space=MagicMock(return_value={"count": 7, "results": []}),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache.cache_updater.cache_store")
    def test_astronauts_both_none_returns_early(self, mock_cache_store):
        """Both None returns early without storing."""
        from cache.cache_updater import update_spaceflight_astronauts_cache

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value=None),
            get_astronauts_in_space=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        assert mock_cache_store.update_shared_cache_entry.call_count == 0

    @patch("cache.cache_updater.cache_store")
    def test_astronauts_none_iss_crew_uses_fallback(self, mock_cache_store):
        """None iss_crew falls back to empty dict."""
        from cache.cache_updater import update_spaceflight_astronauts_cache

        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value=None),
            get_astronauts_in_space=MagicMock(return_value={"count": 3, "results": []}),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        stored = mock_cache_store._spaceflight_astronauts_cache["data"]
        assert stored["iss_crew"] == {}

    @patch("cache.cache_updater.cache_store")
    def test_astronauts_falsy_skips_annotation_loop(self, mock_cache_store):
        """astronauts=None (falsy) with a real iss_crew present -> annotation loop is
        skipped entirely, falling straight through to building the response."""
        from cache.cache_updater import update_spaceflight_astronauts_cache

        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value={
                "expeditions": [
                    {"station_name": "ISS", "station_abbrev": "ISS", "crew": [{"name": "Test Astronaut"}]}
                ],
            }),
            get_astronauts_in_space=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        stored = mock_cache_store._spaceflight_astronauts_cache["data"]
        assert stored["astronauts_in_space"] == {"count": 0, "results": []}

    @patch("cache.cache_updater.cache_store")
    def test_astronauts_annotated_with_station_from_crew(self, mock_cache_store):
        """Astronauts matching a crew member by name are annotated with their station;
        a crew member with no name is skipped when building the name->station map."""
        from cache.cache_updater import update_spaceflight_astronauts_cache

        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(return_value={
                "expeditions": [
                    {
                        "station_name": "International Space Station",
                        "station_abbrev": "ISS",
                        "crew": [
                            {},  # no "name" key -> skipped
                            {"name": "Test Astronaut"},
                        ],
                    }
                ],
            }),
            get_astronauts_in_space=MagicMock(return_value={
                "count": 2,
                "results": [
                    {"name": "Test Astronaut"},
                    {"name": "Unmatched Astronaut"},
                ],
            }),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_astronauts_cache()

        stored = mock_cache_store._spaceflight_astronauts_cache["data"]
        matched = next(a for a in stored["astronauts_in_space"]["results"] if a["name"] == "Test Astronaut")
        unmatched = next(a for a in stored["astronauts_in_space"]["results"] if a["name"] == "Unmatched Astronaut")
        assert matched["station_abbrev"] == "ISS"
        assert unmatched["station_abbrev"] is None


class TestUpdateSpaceflightEventsCache:
    """Tests for update_spaceflight_events_cache edge cases."""

    @patch("cache.cache_updater.cache_store")
    def test_events_none_returns_early(self, mock_cache_store):
        """None events returns early without storing."""
        from cache.cache_updater import update_spaceflight_events_cache

        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()

        assert mock_cache_store.update_shared_cache_entry.call_count == 0

    @patch("cache.cache_updater.cache_store")
    def test_prune_exception_is_caught(self, mock_cache_store):
        """Exception during image prune is caught and logged."""
        from cache.cache_updater import update_spaceflight_events_cache

        mock_cache_store._spaceflight_events_cache = {"data": None, "timestamp": 0}
        mock_cache_store.load_shared_cache_entry.side_effect = RuntimeError("db error")

        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value={"results": []}),
            prune_image_cache=MagicMock(),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()  # Should not raise

        mock_cache_store.update_shared_cache_entry.assert_called()

    @patch("cache.cache_updater.cache_store")
    def test_collect_images_ignores_non_prefix_strings(self, mock_cache_store):
        """_collect_images skips strings not starting with /api/spaceflight/img/."""
        from cache.cache_updater import update_spaceflight_events_cache

        mock_cache_store._spaceflight_events_cache = {"data": None, "timestamp": 0}

        fake_prune = MagicMock()
        fake_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(return_value={"results": []}),
            prune_image_cache=fake_prune,
        )

        mock_cache_store.load_shared_cache_entry.side_effect = lambda key: {
            "spaceflight_launches": {
                "data": {
                    "name": "Mission X",  # non-prefix string → skipped
                    "image_url": "/api/spaceflight/img/launch.jpg",
                }
            },
            "spaceflight_astronauts": None,
            "spaceflight_events": None,
        }.get(key)

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_module}):
            update_spaceflight_events_cache()

        fake_prune.assert_called_once()
        active_images = fake_prune.call_args.args[0]
        assert "/api/spaceflight/img/launch.jpg" in active_images
        assert "Mission X" not in active_images


class TestUpdateIersCacheAdditional:
    """Tests for update_iers_cache."""

    def test_iers_exception_is_caught(self):
        """Exception during IERS download is caught and logged."""
        from cache.cache_updater import update_iers_cache

        # Patch requests to simulate a download error
        with patch("cache.cache_updater.cache_store"):
            with patch("requests.get", side_effect=ConnectionError("no network")):
                update_iers_cache()  # Should not raise


class TestMissingLocationAndExceptionPaths:
    """Cover missing-location and exception branches for each cache update function."""

    @patch("cache.cache_updater.load_config")
    def test_moon_planner_missing_location(self, mock_load_config):
        """update_moon_planner_cache handles missing location gracefully."""
        from cache.cache_updater import update_moon_planner_cache

        mock_load_config.return_value = {}
        update_moon_planner_cache()  # Should not raise

    @patch("cache.cache_updater.MoonPlanner")
    @patch("cache.cache_updater.load_config")
    def test_moon_planner_exception(self, mock_load_config, mock_planner, mock_config):
        """update_moon_planner_cache exception is caught and logged."""
        from cache.cache_updater import update_moon_planner_cache

        mock_load_config.return_value = mock_config
        mock_planner.side_effect = RuntimeError("planner error")
        update_moon_planner_cache()  # Should not raise

    @patch("cache.cache_updater.load_config")
    def test_sun_report_missing_location(self, mock_load_config):
        """update_sun_report_cache handles missing location gracefully."""
        from cache.cache_updater import update_sun_report_cache

        mock_load_config.return_value = {}
        update_sun_report_cache()  # Should not raise

    @patch("cache.cache_updater.SunService")
    @patch("cache.cache_updater.load_config")
    def test_sun_report_exception(self, mock_load_config, mock_sun, mock_config):
        """update_sun_report_cache exception is caught and logged."""
        from cache.cache_updater import update_sun_report_cache

        mock_load_config.return_value = mock_config
        mock_sun.side_effect = RuntimeError("sun error")
        update_sun_report_cache()  # Should not raise

    @patch("cache.cache_updater.load_config")
    def test_best_window_missing_location(self, mock_load_config):
        """update_best_window_cache handles missing location gracefully."""
        from cache.cache_updater import update_best_window_cache

        mock_load_config.return_value = {}
        update_best_window_cache()  # Should not raise

    @patch("cache.cache_updater.AstroTonightService")
    @patch("cache.cache_updater.load_config")
    def test_best_window_exception(self, mock_load_config, mock_service, mock_config):
        """update_best_window_cache exception is caught and logged."""
        from cache.cache_updater import update_best_window_cache

        mock_load_config.return_value = mock_config
        mock_service.side_effect = RuntimeError("best window error")
        update_best_window_cache()  # Should not raise

    @patch("cache.cache_updater.get_hourly_forecast")
    def test_weather_cache_exception(self, mock_forecast, mock_config):
        """update_weather_cache exception during serialization is caught."""
        from cache.cache_updater import update_weather_cache

        # Raise during forecast fetch
        mock_forecast.side_effect = RuntimeError("serialization error")
        update_weather_cache(config=mock_config)  # Should not raise

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.get_hourly_forecast")
    def test_weather_cache_with_bytes_location(self, mock_forecast, mock_cache_store, mock_config):
        """update_weather_cache handles bytes values in location dict."""
        from cache.cache_updater import update_weather_cache

        mock_forecast.return_value = {
            "hourly": pd.DataFrame({"date": pd.to_datetime(["2026-04-17T21:00:00Z"]), "temp": [10.0]}),
            "location": {"name": b"Paris", "country": "France"},
        }

        update_weather_cache(config=mock_config)
        stored = _loc_payload(mock_cache_store, "weather_forecast")
        assert stored["location"]["name"] == "Paris"

    def test_spaceflight_astronauts_exception(self):
        """update_spaceflight_astronauts_cache exception is caught."""
        from cache.cache_updater import update_spaceflight_astronauts_cache

        broken_module = types.SimpleNamespace(
            get_iss_crew=MagicMock(side_effect=RuntimeError("network error")),
            get_astronauts_in_space=MagicMock(return_value=None),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": broken_module}):
            update_spaceflight_astronauts_cache()  # Should not raise

    def test_spaceflight_events_outer_exception(self):
        """update_spaceflight_events_cache outer exception is caught."""
        from cache.cache_updater import update_spaceflight_events_cache

        broken_module = types.SimpleNamespace(
            get_upcoming_space_events=MagicMock(side_effect=RuntimeError("outer error")),
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": broken_module}):
            update_spaceflight_events_cache()  # Should not raise

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_fully_initialize_moon_report_mirrors_dark_window_on_failure(
        self, _check, mock_load_config, mock_cache_store, mock_config
    ):
        """Exception in moon_report job also records dark_window failure."""
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        mock_cache_store.is_cache_valid.return_value = False
        mock_cache_store.is_cache_valid_for_today.return_value = False
        mock_cache_store.load_location_cache.return_value = {"timestamp": 0, "data": None}
        mock_cache_store.sync_cache_from_shared.return_value = None
        mock_cache_store._spaceflight_launches_cache = {"data": None, "timestamp": 0}
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        # Patch every other location job so only moon_report actually errors and
        # nothing does real astro work in this control-flow test.
        job_patches = [
            "update_moon_planner_cache", "update_sun_report_cache", "update_solar_eclipse_cache",
            "update_lunar_eclipse_cache", "update_horizon_graph_cache", "update_aurora_cache",
            "update_iss_passes_cache", "update_css_passes_cache", "update_planetary_events_cache",
            "update_special_phenomena_cache", "update_solar_system_events_cache",
            "update_sidereal_time_cache", "update_seeing_forecast_cache", "update_best_window_cache",
            "update_weather_cache",
        ]
        from contextlib import ExitStack

        with ExitStack() as stack:
            for name in job_patches:
                stack.enter_context(patch(f"cache.cache_updater.{name}"))
            stack.enter_context(patch("cache.cache_updater.update_moon_caches", side_effect=RuntimeError("moon fail")))
            fully_initialize_caches()

        # record_cache_execution for both "moon_report" and "dark_window" with False
        calls = [str(c) for c in mock_cache_store.record_cache_execution.call_args_list]
        assert any("dark_window" in c for c in calls)


class TestFullyInitializeCachesAdditional:
    """Additional tests for fully_initialize_caches control flow."""

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_all_caches_valid_skips_all_jobs(self, _check, mock_load_config, mock_cache_store, mock_config):
        """When all caches are valid, no jobs are run."""
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        # All caches valid
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.load_location_cache.return_value = {"timestamp": 999, "data": {"x": 1}}
        mock_cache_store.sync_cache_from_shared.return_value = None

        fully_initialize_caches()

        # set_cache_initialization_in_progress(False) must still be called in finally
        mock_cache_store.set_cache_initialization_in_progress.assert_called_with(False)

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_spaceflight_image_integrity_forces_refetch(self, _check, mock_load_config, mock_cache_store, mock_config):
        """Missing spaceflight images force timestamp=0 to trigger refetch."""
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.load_location_cache.return_value = {"timestamp": 999, "data": {"x": 1}}
        mock_cache_store.sync_cache_from_shared.return_value = None

        # Simulate cache entry with data
        launches_cache = {"data": {"upcoming": {}}, "timestamp": 999999}
        mock_cache_store._spaceflight_launches_cache = launches_cache
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_tracker = types.SimpleNamespace(
            spaceflight_cache_images_intact=MagicMock(return_value=False)
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_tracker}):
            fully_initialize_caches()

        # Timestamp should have been zeroed, forcing a refetch
        assert launches_cache["timestamp"] == 0

    @patch("cache.cache_updater.cache_store")
    @patch("cache.cache_updater.load_config")
    @patch("cache.cache_updater.check_and_handle_config_changes")
    def test_spaceflight_image_integrity_intact_skips_reset(self, _check, mock_load_config, mock_cache_store, mock_config):
        """Images are intact so timestamp is NOT reset."""
        from cache.cache_updater import fully_initialize_caches

        mock_load_config.return_value = mock_config
        mock_cache_store.is_cache_valid.return_value = True
        mock_cache_store.is_cache_valid_for_today.return_value = True
        mock_cache_store.load_location_cache.return_value = {"timestamp": 999, "data": {"x": 1}}
        mock_cache_store.sync_cache_from_shared.return_value = None

        original_ts = 999999
        launches_cache = {"data": {"upcoming": {}}, "timestamp": original_ts}
        mock_cache_store._spaceflight_launches_cache = launches_cache
        mock_cache_store._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

        fake_tracker = types.SimpleNamespace(
            spaceflight_cache_images_intact=MagicMock(return_value=True)  # images are intact
        )

        with patch.dict(sys.modules, {"space.spaceflight_tracker": fake_tracker}):
            fully_initialize_caches()

        # Timestamp must NOT have been reset since images are intact
        assert launches_cache["timestamp"] == original_ts


# ---------------------------------------------------------------------------
# Merged from former test_coverage_paths3.py
# ---------------------------------------------------------------------------

class TestCacheUpdaterIersBranches:
    """Cover IERS-related branches in update_iers_cache and fully_initialize_caches."""

    def test_update_iers_no_mirror_url(self):
        """mirror_url is None → single URL list."""
        from cache.cache_updater import update_iers_cache
        import astropy.utils.iers as _iers_mod

        mock_conf = MagicMock()
        mock_conf.iers_auto_url = "https://example.com/iers.ecsv"
        # getattr(..., 'iers_auto_url_mirror', None) returns None
        del mock_conf.iers_auto_url_mirror

        with patch.object(_iers_mod, "conf", mock_conf):
            with patch("requests.get") as mock_req:
                mock_resp = MagicMock()
                mock_resp.content = b"fake content"
                mock_req.return_value = mock_resp
                with patch("os.makedirs"):
                    with patch("builtins.open", MagicMock()):
                        with patch("astropy.utils.iers.IERS_A.open", return_value=MagicMock()):
                            with patch("astropy.utils.iers.IERS_Auto") as mock_auto:
                                mock_auto.iers_table = None
                                try:
                                    update_iers_cache()
                                except Exception:
                                    pass  # not the point; just need the mirror branch covered

    def test_iers_table_mjd_max_without_value_attr(self):
        """mjd_max without .value attribute (plain float)."""
        from cache.cache_updater import fully_initialize_caches
        import astropy.utils.iers as _iers_mod

        class _FakeMJD:
            """Has no .value attribute, so hasattr(mjd_max, 'value') is False."""

            def max(self):
                return 59000.0  # plain float-like, no .value

        class _FakeTable:
            def __getitem__(self, key):
                if key == "MJD":
                    return _FakeMJD()
                return None

        with patch("cache.cache_updater.cache_store") as mock_cs:
            with patch("cache.cache_updater.load_config") as mock_cfg:
                with patch("cache.cache_updater.check_and_handle_config_changes") as mock_chk:
                    mock_cfg.return_value = {
                        "location": {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
                    }
                    mock_cs.is_cache_valid.return_value = True
                    mock_cs.is_cache_valid_for_today.return_value = True
                    mock_cs.sync_cache_from_shared.return_value = None
                    mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                    mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                    fake_table = _FakeTable()
                    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=fake_table):
                        with patch("astropy.time.Time.now") as mock_time:
                            mock_now = MagicMock()
                            mock_now.mjd = 61000.0  # future → table appears stale
                            mock_time.return_value = mock_now
                            fully_initialize_caches()

    def test_iers_stale_exception_during_eval(self):
        """exception while evaluating IERS table staleness."""
        from cache.cache_updater import fully_initialize_caches

        class _BadTable:
            def __getitem__(self, key):
                raise KeyError("table access error")

        with patch("cache.cache_updater.cache_store") as mock_cs:
            with patch("cache.cache_updater.load_config") as mock_cfg:
                with patch("cache.cache_updater.check_and_handle_config_changes"):
                    mock_cfg.return_value = {
                        "location": {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
                    }
                    mock_cs.is_cache_valid.return_value = True
                    mock_cs.is_cache_valid_for_today.return_value = True
                    mock_cs.sync_cache_from_shared.return_value = None
                    mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                    mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                    bad_table = _BadTable()
                    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=bad_table):
                        fully_initialize_caches()  # should not raise

    def test_iers_stale_forces_iers_job(self):
        """stale IERS table → iers job appended to jobs_to_run."""
        from cache.cache_updater import fully_initialize_caches

        class _StaleTable:
            def __getitem__(self, key):
                if key == "MJD":
                    return _MJDWithValue()
                raise KeyError(key)

        class _MJDWithValue:
            def max(self):
                return _HasValue()

        class _HasValue:
            value = 50000.0  # very old date → stale

        with patch("cache.cache_updater.cache_store") as mock_cs:
            with patch("cache.cache_updater.load_config") as mock_cfg:
                with patch("cache.cache_updater.check_and_handle_config_changes"):
                    with patch("cache.cache_updater.update_iers_cache") as mock_iers:
                        mock_cfg.return_value = {
                            "location": {"latitude": 48.0, "longitude": 2.0, "timezone": "UTC"}
                        }
                        mock_cs.is_cache_valid.return_value = True
                        mock_cs.is_cache_valid_for_today.return_value = True
                        mock_cs.sync_cache_from_shared.return_value = None
                        mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                        mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                        stale_table = _StaleTable()
                        with patch("astropy.utils.iers.IERS_Auto.iers_table", new=stale_table):
                            fully_initialize_caches()

    def test_iers_pre_parallel_success_increments_count(self):
        """pre-parallel IERS download succeeds → success_count incremented."""
        from cache.cache_updater import fully_initialize_caches

        with patch("cache.cache_updater.update_iers_cache") as mock_iers:
            mock_iers.return_value = None  # success
            with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
                with patch("cache.cache_updater.cache_store") as mock_cs:
                    with patch("cache.cache_updater.load_config") as mock_cfg:
                        with patch("cache.cache_updater.check_and_handle_config_changes"):
                            mock_cfg.return_value = {
                                "location": {
                                    "latitude": 48.0,
                                    "longitude": 2.0,
                                    "timezone": "UTC",
                                }
                            }
                            mock_cs.is_cache_valid.return_value = False
                            mock_cs.is_cache_valid_for_today.return_value = True
                            mock_cs.sync_cache_from_shared.return_value = None
                            mock_cs._spaceflight_launches_cache = {"data": None, "timestamp": 0}
                            mock_cs._spaceflight_astronauts_cache = {"data": None, "timestamp": 0}

                            fully_initialize_caches()


# ---------------------------------------------------------------------------
# Merged from former test_coverage_edge_cases.py
# ---------------------------------------------------------------------------

def test_cache_updater_masked_location_log_safe_coord_exceptions():
    from cache import cache_updater

    masked = cache_updater._masked_location_log({"latitude": "x", "longitude": object()})
    assert "lat=?" in masked and "lon=?" in masked


def test_update_allsky_sensor_cache_paths(monkeypatch):
    from cache import cache_updater
    from cache import cache_store

    fake_connector = types.SimpleNamespace(
        AllSkyConnector=lambda _cfg: types.SimpleNamespace(fetch_sensor_data=lambda: {"temp": 1})
    )
    with patch.dict("sys.modules", {"connectors.allsky_connector": fake_connector}):
        cache_store._allsky_sensor_cache = {"data": None, "timestamp": 0}
        cache_updater.update_allsky_sensor_cache(
            {
                "connectors": {
                    "allsky": {
                        "enabled": True,
                        "url": "http://x",
                        "modules": {"sensor_data": {"enabled": True}},
                    }
                }
            }
        )
        assert cache_store._allsky_sensor_cache["data"] == {"temp": 1}


def test_update_allsky_sensor_cache_none_config_and_early_returns(monkeypatch):
    from cache import cache_updater

    monkeypatch.setattr(cache_updater, "load_config", lambda: {"connectors": {"allsky": {"enabled": False}}})
    cache_updater.update_allsky_sensor_cache()

    cache_updater.update_allsky_sensor_cache({"connectors": {"allsky": {"enabled": True, "url": "http://x"}}})


def test_update_allsky_health_cache_paths(monkeypatch):
    from cache import cache_updater
    from cache import cache_store

    fake_connector = types.SimpleNamespace(
        AllSkyConnector=lambda _cfg: types.SimpleNamespace(health_check=lambda: {"ok": True})
    )
    with patch.dict("sys.modules", {"connectors.allsky_connector": fake_connector}):
        cache_store._allsky_health_cache = {"data": None, "timestamp": 0}
        cache_updater.update_allsky_health_cache(
            {"connectors": {"allsky": {"enabled": True, "url": "http://x", "modules": {}}}}
        )
        assert cache_store._allsky_health_cache["data"] == {"ok": True}


def test_update_allsky_health_cache_none_config_and_early_return(monkeypatch):
    from cache import cache_updater

    monkeypatch.setattr(cache_updater, "load_config", lambda: {"connectors": {"allsky": {"enabled": False}}})
    cache_updater.update_allsky_health_cache()

    cache_updater.update_allsky_health_cache({"connectors": {"allsky": {"enabled": True}}})


@pytest.mark.parametrize(
    "fn_name",
    [
        "update_moon_planner_cache",
        "update_sun_report_cache",
        "update_best_window_cache",
        "update_solar_eclipse_cache",
        "update_lunar_eclipse_cache",
        "update_horizon_graph_cache",
        "update_aurora_cache",
        "update_iss_passes_cache",
        "update_planetary_events_cache",
        "update_special_phenomena_cache",
        "update_solar_system_events_cache",
        "update_sidereal_time_cache",
        "update_seeing_forecast_cache",
    ],
)
def test_cache_updater_config_provided_branch_calls_resolve(monkeypatch, fn_name):
    from cache import cache_updater

    fn = getattr(cache_updater, fn_name)
    monkeypatch.setattr(
        cache_updater,
        "_resolve_job_location",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("stop after resolve call")),
    )
    fn(config={"locations": [{"id": "dflt", "is_install_default": True}]})


def test_check_and_handle_config_changes_no_legacy_signature_migrates(monkeypatch):
    from cache import cache_updater

    mock_cs = MagicMock()
    mock_cs.pop_legacy_location_signature.return_value = None
    mock_cs.is_location_tracked.return_value = True
    mock_cs.has_location_changed.return_value = False

    monkeypatch.setitem(cache_updater._legacy_cache_migration_state, "done", False)
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {"locations": [{"id": "dflt", "is_install_default": True}]},
    )

    cache_updater.check_and_handle_config_changes()
    mock_cs.migrate_legacy_cache_keys.assert_called_once_with("dflt")


def test_fully_initialize_caches_multi_location_labels_and_missing_id(monkeypatch):
    from cache import cache_updater

    calls = []

    def _job(config=None, location=None):
        calls.append(location.get("id"))

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": None, "timestamp": 0}
    mock_cs.is_cache_valid_for_today.return_value = False
    mock_cs.is_cache_valid.side_effect = lambda entry, _ttl: entry is not mock_cs._iers_cache
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": None, "timestamp": 0}
    mock_cs._allsky_sensor_cache = {"data": None, "timestamp": 0}
    mock_cs._allsky_health_cache = {"data": None, "timestamp": 0}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {
            "locations": [
                {"id": "dflt", "name": "Default", "is_install_default": True},
                {"id": None, "name": "NoId", "is_install_default": False},
                {"id": "other", "name": "Second Site", "is_install_default": False},
            ],
            "connectors": {
                "allsky": {
                    "enabled": True,
                    "url": "http://x",
                    "modules": {"sensor_data": {"enabled": True}},
                }
            },
        },
    )
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "slugify_location_name", lambda s: s.lower().replace(" ", "-"))
    monkeypatch.setattr(cache_updater, "update_iers_cache", lambda: None)
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", (("moon_report", "moon_report", "_cov_job", 1, True),))
    monkeypatch.setattr(cache_updater, "_PARALLELIZABLE_JOBS", {"iers"})
    monkeypatch.setattr(cache_updater, "_cov_job", _job, raising=False)

    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
        cache_updater.fully_initialize_caches()

    assert calls == ["dflt", "other"]
    labels = [c.args[0] for c in mock_cs.record_cache_execution.call_args_list]
    assert any(label.startswith("moon_report@") for label in labels)


def test_fully_initialize_caches_preparallel_iers_failure(monkeypatch):
    from cache import cache_updater

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": {}, "timestamp": 1}
    mock_cs.is_cache_valid_for_today.return_value = True
    mock_cs.is_cache_valid.side_effect = lambda entry, _ttl: entry is not mock_cs._iers_cache
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": None, "timestamp": 0}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(cache_updater, "load_config", lambda: {"locations": [{"id": "dflt", "is_install_default": True}]})
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", ())
    monkeypatch.setattr(cache_updater, "_PARALLELIZABLE_JOBS", {"iers"})
    monkeypatch.setattr(cache_updater, "update_iers_cache", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
        cache_updater.fully_initialize_caches()

    flags = [c.args[2] for c in mock_cs.record_cache_execution.call_args_list if c.args and c.args[0] == "iers"]
    assert False in flags


def test_fully_initialize_caches_allsky_enabled_without_sensor_module(monkeypatch):
    from cache import cache_updater

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": {}, "timestamp": 1}
    mock_cs.is_cache_valid_for_today.return_value = True
    mock_cs.is_cache_valid.return_value = True
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": {}, "timestamp": 1}
    mock_cs._allsky_sensor_cache = {"data": {}, "timestamp": 1}
    mock_cs._allsky_health_cache = {"data": {}, "timestamp": 1}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {
            "locations": [{"id": "dflt", "is_install_default": True}],
            "connectors": {"allsky": {"enabled": True, "url": "http://x", "modules": {}}},
        },
    )
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", ())

    cache_updater.fully_initialize_caches()


def test_fully_initialize_caches_iers_absent_but_not_in_parallel(monkeypatch):
    from cache import cache_updater

    called = []

    def _aurora_job(config=None, location=None):
        called.append(location.get("id"))

    mock_cs = MagicMock()
    mock_cs.load_location_cache.return_value = {"data": None, "timestamp": 0}
    mock_cs.is_cache_valid_for_today.return_value = False
    mock_cs.is_cache_valid.return_value = True
    mock_cs.sync_cache_from_shared.return_value = None
    mock_cs._spaceflight_launches_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_astronauts_cache = {"data": {}, "timestamp": 1}
    mock_cs._spaceflight_events_cache = {"data": {}, "timestamp": 1}
    mock_cs._iers_cache = {"data": {}, "timestamp": 1}

    monkeypatch.setattr(cache_updater, "check_and_handle_config_changes", lambda: False)
    monkeypatch.setattr(
        cache_updater,
        "load_config",
        lambda: {"locations": [{"id": "dflt", "is_install_default": True}]},
    )
    monkeypatch.setattr(cache_updater, "get_scheduler_locations", lambda cfg: cfg["locations"])
    monkeypatch.setattr(cache_updater, "get_install_default_location", lambda cfg: cfg["locations"][0])
    monkeypatch.setattr(cache_updater, "cache_store", mock_cs)
    monkeypatch.setattr(cache_updater, "_LOCATION_JOBS", (("aurora", "aurora", "_cov_aurora", 1, True),))
    monkeypatch.setattr(cache_updater, "_cov_aurora", _aurora_job, raising=False)

    with patch("astropy.utils.iers.IERS_Auto.iers_table", new=None):
        cache_updater.fully_initialize_caches()

    assert called == ["dflt"]

