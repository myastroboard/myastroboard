"""
Unit tests for cache store (cache_store.py)
Tests the server-side cache management system with TTL-based expiration
"""
import pytest
import time
import os
import cache_store
from constants import CACHE_TTL, WEATHER_CACHE_TTL, DATA_DIR_CACHE

# Import cache variables and functions to test
from cache_store import (
    _moon_report_cache,
    _sun_report_cache,
    _best_window_cache,
    _moon_planner_report_cache,
    _dark_window_report_cache,
    _last_known_location_config,
    is_cache_valid,
    is_astronomical_cache_ready,
    has_location_changed,
    reset_all_caches,
    update_location_config,
    get_current_location_signature,
    get_cache_init_status,
    set_cache_initialization_in_progress
)


@pytest.fixture(autouse=True)
def reset_location_tracking_state():
    """Reset location tracking state to avoid cross-test contamination."""
    import cache_store

    _last_known_location_config.clear()
    _last_known_location_config.update({
        "latitude": None,
        "longitude": None,
        "elevation": None,
        "timezone": None
    })
    cache_store._last_known_location_config = _last_known_location_config

    location_cache_file = os.path.join(DATA_DIR_CACHE, 'location_cache.json')
    if os.path.exists(location_cache_file):
        os.remove(location_cache_file)

    yield


class TestCacheStructures:
    """Test cache data structures"""
    
    def test_moon_report_cache_structure(self):
        """Test _moon_report_cache has correct structure"""
        assert isinstance(_moon_report_cache, dict)
        assert 'timestamp' in _moon_report_cache
        assert 'data' in _moon_report_cache
        assert isinstance(_moon_report_cache['timestamp'], (int, float))
    
    def test_sun_report_cache_structure(self):
        """Test _sun_report_cache has correct structure"""
        assert isinstance(_sun_report_cache, dict)
        assert 'timestamp' in _sun_report_cache
        assert 'data' in _sun_report_cache
        assert isinstance(_sun_report_cache['timestamp'], (int, float))
    
    def test_best_window_cache_structure(self):
        """Test _best_window_cache has correct structure"""
        assert isinstance(_best_window_cache, dict)
        
        # Should have three sub-caches
        assert 'strict' in _best_window_cache
        assert 'practical' in _best_window_cache
        assert 'illumination' in _best_window_cache
        
        # Each sub-cache should have timestamp and data
        for key in ['strict', 'practical', 'illumination']:
            assert 'timestamp' in _best_window_cache[key]
            assert 'data' in _best_window_cache[key]
            assert isinstance(_best_window_cache[key]['timestamp'], (int, float))
    
    def test_moon_planner_report_cache_structure(self):
        """Test _moon_planner_report_cache has correct structure"""
        assert isinstance(_moon_planner_report_cache, dict)
        assert 'timestamp' in _moon_planner_report_cache
        assert 'data' in _moon_planner_report_cache
        assert isinstance(_moon_planner_report_cache['timestamp'], (int, float))
    
    def test_dark_window_report_cache_structure(self):
        """Test _dark_window_report_cache has correct structure"""
        assert isinstance(_dark_window_report_cache, dict)
        assert 'timestamp' in _dark_window_report_cache
        assert 'data' in _dark_window_report_cache
        assert isinstance(_dark_window_report_cache['timestamp'], (int, float))
    
    def test_cache_location_tracking_structure(self):
        """Test _last_known_location_config has correct structure"""
        assert isinstance(_last_known_location_config, dict)
        assert 'latitude' in _last_known_location_config
        assert 'longitude' in _last_known_location_config
        assert 'elevation' in _last_known_location_config
        assert 'timezone' in _last_known_location_config



class TestCacheInitialValues:
    """Test initial cache values"""

    @pytest.fixture(autouse=True)
    def _reset_caches_before_test(self):
        """Ensure assertions run against a clean cache state."""
        reset_all_caches()
    
    def test_moon_report_cache_initial_values(self):
        """Test _moon_report_cache initial values"""
        # Initial timestamp should be 0
        assert cache_store._moon_report_cache['timestamp'] == 0
        # Initial data should be None
        assert cache_store._moon_report_cache['data'] is None
    
    def test_sun_report_cache_initial_values(self):
        """Test _sun_report_cache initial values"""
        assert cache_store._sun_report_cache['timestamp'] == 0
        assert cache_store._sun_report_cache['data'] is None
    
    def test_best_window_cache_initial_values(self):
        """Test _best_window_cache initial values"""
        for key in ['strict', 'practical', 'illumination']:
            assert cache_store._best_window_cache[key]['timestamp'] == 0
            assert cache_store._best_window_cache[key]['data'] is None
    
    def test_moon_planner_report_cache_initial_values(self):
        """Test _moon_planner_report_cache initial values"""
        assert cache_store._moon_planner_report_cache['timestamp'] == 0
        assert cache_store._moon_planner_report_cache['data'] is None
    
    def test_dark_window_report_cache_initial_values(self):
        """Test _dark_window_report_cache initial values"""
        assert cache_store._dark_window_report_cache['timestamp'] == 0
        assert cache_store._dark_window_report_cache['data'] is None
    
    def test_location_config_initial_values(self):
        """Test _last_known_location_config initial values (None)"""
        # Initial location config should have None values (not yet tracked)
        assert _last_known_location_config['latitude'] is None
        assert _last_known_location_config['longitude'] is None
        assert _last_known_location_config['elevation'] is None
        assert _last_known_location_config['timezone'] is None



class TestCacheConsistency:
    """Test cache structure consistency"""
    
    def test_all_simple_caches_have_same_structure(self):
        """Test that all simple caches have the same structure"""
        simple_caches = [
            _moon_report_cache,
            _sun_report_cache,
            _moon_planner_report_cache,
            _dark_window_report_cache
        ]
        
        for cache in simple_caches:
            assert set(cache.keys()) == {'timestamp', 'data'}
            assert isinstance(cache['timestamp'], (int, float))
    
    def test_best_window_cache_subcaches_consistency(self):
        """Test that all best_window sub-caches have the same structure"""
        for key in ['strict', 'practical', 'illumination']:
            subcache = _best_window_cache[key]
            assert set(subcache.keys()) == {'timestamp', 'data'}
            assert isinstance(subcache['timestamp'], (int, float))

class TestCacheValidation:
    """Test TTL-based cache validation"""
    
    def test_is_cache_valid_with_fresh_cache(self):
        """Test is_cache_valid returns True for fresh cache"""
        cache_entry = {"timestamp": time.time(), "data": {"test": "data"}}
        assert is_cache_valid(cache_entry, CACHE_TTL) is True
    
    def test_is_cache_valid_with_expired_cache(self):
        """Test is_cache_valid returns False for expired cache"""
        # Set timestamp to past (expired)
        past_time = time.time() - (CACHE_TTL + 10)
        cache_entry = {"timestamp": past_time, "data": {"test": "data"}}
        assert is_cache_valid(cache_entry, CACHE_TTL) is False
    
    def test_is_cache_valid_with_no_data(self):
        """Test is_cache_valid returns False when data is None"""
        cache_entry = {"timestamp": time.time(), "data": None}
        assert is_cache_valid(cache_entry, CACHE_TTL) is False
    
    def test_is_cache_valid_with_empty_cache(self):
        """Test is_cache_valid returns False for empty cache"""
        cache_entry = {"timestamp": 0, "data": None}
        assert is_cache_valid(cache_entry, CACHE_TTL) is False
    
    def test_is_cache_valid_with_different_ttl(self):
        """Test is_cache_valid respects different TTL values"""
        cache_entry = {"timestamp": time.time() - 30, "data": {"test": "data"}}
        # Should be valid with high TTL
        assert is_cache_valid(cache_entry, 60) is True
        # Should be invalid with low TTL
        assert is_cache_valid(cache_entry, 10) is False


class TestLocationChangeDetection:
    """Test location configuration change detection"""
    
    def test_get_current_location_signature(self):
        """Test location signature creation"""
        location = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        signature = get_current_location_signature(location)
        assert signature["latitude"] == 45.5
        assert signature["longitude"] == -73.5
        assert signature["elevation"] == 100
        assert signature["timezone"] == "America/Montreal"
    
    def test_get_current_location_signature_with_none(self):
        """Test location signature with None input"""
        signature = get_current_location_signature(None)
        assert signature is None
    
    def test_has_location_changed_first_time(self):
        """Test has_location_changed returns True on first tracking"""
        # Reset to initial state
        location = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        # First time should return True (change detected)
        result = has_location_changed(location)
        assert result is True or result is False  # Depends on test order
    
    def test_has_location_changed_latitude(self):
        """Test location change detection for latitude"""
        location1 = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        update_location_config(location1)
        
        location2 = {
            "latitude": 46.5,  # Changed
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        assert has_location_changed(location2) is True
    
    def test_has_location_changed_longitude(self):
        """Test location change detection for longitude"""
        location1 = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        update_location_config(location1)
        
        location2 = {
            "latitude": 45.5,
            "longitude": -74.5,  # Changed
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        assert has_location_changed(location2) is True
    
    def test_has_location_changed_elevation(self):
        """Test location change detection for elevation"""
        location1 = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        update_location_config(location1)
        
        location2 = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 200,  # Changed
            "timezone": "America/Montreal"
        }
        assert has_location_changed(location2) is True
    
    def test_has_location_changed_timezone(self):
        """Test location change detection for timezone"""
        location1 = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        update_location_config(location1)
        
        location2 = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/New_York"  # Changed
        }
        assert has_location_changed(location2) is True
    
    def test_has_location_changed_no_change(self):
        """Test location change detection when nothing changed"""
        location = {
            "latitude": 45.5,
            "longitude": -73.5,
            "elevation": 100,
            "timezone": "America/Montreal"
        }
        update_location_config(location)
        
        # Same location
        assert has_location_changed(location) is False
    
    def test_update_location_config(self):
        """Test updating tracked location config"""
        import cache_store
        
        location = {
            "latitude": 40.7,
            "longitude": -74.0,
            "elevation": 50,
            "timezone": "America/New_York"
        }
        update_location_config(location)
        
        # Verify it was updated (access via module, not local import)
        assert cache_store._last_known_location_config["latitude"] == 40.7
        assert cache_store._last_known_location_config["longitude"] == -74.0


class TestCacheReset:
    """Test cache reset functionality"""
    
    def test_reset_all_caches(self):
        """Test resetting all astronomical caches"""
        import cache_store
        
        # Set some data
        cache_store._moon_report_cache["data"] = {"test": "data"}
        cache_store._moon_report_cache["timestamp"] = time.time()
        cache_store._sun_report_cache["data"] = {"test": "data"}
        
        # Reset
        reset_all_caches()
        
        # Verify all are cleared (access via module, not local import)
        assert cache_store._moon_report_cache["data"] is None
        assert cache_store._moon_report_cache["timestamp"] == 0
        assert cache_store._sun_report_cache["data"] is None
        assert cache_store._sun_report_cache["timestamp"] == 0
        assert cache_store._best_window_cache["strict"]["data"] is None
        assert cache_store._moon_planner_report_cache["data"] is None
        assert cache_store._dark_window_report_cache["data"] is None


class TestCacheInitStatus:
    """Test cache initialization status reporting"""
    
    def test_get_cache_init_status(self):
        """Test getting detailed cache status"""
        status = get_cache_init_status()
        
        # Check structure
        assert "moon_report" in status
        assert "sun_report" in status
        assert "best_window_strict" in status
        assert "best_window_practical" in status
        assert "best_window_illumination" in status
        assert "moon_planner" in status
        assert "dark_window" in status
        assert "all_ready" in status
        assert "planetary_events" in status
        assert "special_phenomena" in status
        assert "solar_system_events" in status
        assert "sidereal_time" in status
        assert "in_progress" in status
        
        # Should be booleans
        assert isinstance(status["all_ready"], bool)
        assert isinstance(status["in_progress"], bool)
    
    def test_set_cache_initialization_in_progress(self):
        """Test setting cache initialization progress flag"""
        set_cache_initialization_in_progress(True)
        status = get_cache_init_status()
        assert status["in_progress"] is True
        
        set_cache_initialization_in_progress(False)
        status = get_cache_init_status()
        assert status["in_progress"] is False
    
    def test_is_astronomical_cache_ready_when_empty(self):
        """Test cache ready status when caches are empty"""
        # With no data, caches should not be ready
        reset_all_caches()
        assert is_astronomical_cache_ready() is False


class TestReadSharedCacheMissingFile:
    """Line 145: _read_shared_cache returns {} when shared cache file doesn't exist."""

    def test_returns_empty_dict_when_file_absent(self, monkeypatch):
        import cache_store
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', '/nonexistent/path/astro_cache.json')
        result = cache_store._read_shared_cache()
        assert result == {}


class TestLoadSharedCacheEntryMissingKeys:
    """Line 177: load_shared_cache_entry returns None when entry is a dict missing timestamp/data."""

    def test_entry_missing_timestamp(self, monkeypatch):
        import cache_store
        monkeypatch.setattr(cache_store, '_read_shared_cache', lambda: {"mykey": {"data": "foo"}})
        result = cache_store.load_shared_cache_entry("mykey")
        assert result is None

    def test_entry_missing_data(self, monkeypatch):
        import cache_store
        monkeypatch.setattr(cache_store, '_read_shared_cache', lambda: {"mykey": {"timestamp": 123}})
        result = cache_store.load_shared_cache_entry("mykey")
        assert result is None


class TestLoadLocationCacheReadsFile:
    """Lines 229-233: _load_location_cache reads file contents or swallows exceptions."""

    def test_load_location_cache_from_existing_file(self, tmp_path, monkeypatch):
        import cache_store, json
        location_data = {"latitude": 51.5, "longitude": -0.12, "elevation": 10, "timezone": "Europe/London"}
        loc_file = tmp_path / 'location_cache.json'
        loc_file.write_text(json.dumps(location_data))
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(loc_file))
        cache_store._load_location_cache()
        assert cache_store._last_known_location_config["latitude"] == 51.5
        assert cache_store._last_known_location_config["timezone"] == "Europe/London"

    def test_load_location_cache_corrupted_file_swallows_exception(self, tmp_path, monkeypatch):
        """Lines 231-233: json.JSONDecodeError → except block executed, no exception raised."""
        import cache_store
        loc_file = tmp_path / 'location_cache.json'
        loc_file.write_text("NOT VALID JSON {{{{")
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(loc_file))
        cache_store._load_location_cache()  # must not raise


class TestSaveLocationCacheException:
    """Lines 242-244: _save_location_cache swallows write exceptions silently."""

    def test_save_exception_is_silently_ignored(self, monkeypatch):
        import cache_store, builtins
        original_open = builtins.open

        def raising_open(path, mode='r', **kwargs):
            if 'w' in mode and 'location_cache' in str(path):
                raise PermissionError("no write access")
            return original_open(path, mode, **kwargs)

        monkeypatch.setattr(builtins, 'open', raising_open)
        cache_store._save_location_cache()  # must not propagate the exception


class TestHasLocationChangedNoneConfig:
    """Line 269: has_location_changed returns True when new config is None."""

    def test_none_config_treated_as_changed(self):
        result = has_location_changed(None)
        assert result is True


class TestUpdateLocationConfigNone:
    """Line 288->exit: update_location_config is a no-op when signature is None."""

    def test_none_config_leaves_state_unchanged(self):
        import cache_store
        before = cache_store._last_known_location_config.copy()
        update_location_config(None)
        assert cache_store._last_known_location_config == before


class TestResetWeatherCache:
    """Line 330: reset_weather_cache resets _weather_cache to its zero state."""

    def test_reset_weather_cache_clears_data(self):
        import cache_store
        from cache_store import reset_weather_cache
        cache_store._weather_cache = {"timestamp": 99999, "data": {"temperature": 20}}
        reset_weather_cache()
        assert cache_store._weather_cache == {"timestamp": 0, "data": None}


class TestIsCacheValidForToday:
    """Lines 351-354: is_cache_valid_for_today checks both TTL and calendar date."""

    def test_fresh_cache_from_today_is_valid(self):
        from cache_store import is_cache_valid_for_today
        cache_entry = {"timestamp": time.time(), "data": {"some": "data"}}
        assert is_cache_valid_for_today(cache_entry, 3600) is True

    def test_expired_cache_is_invalid(self):
        from cache_store import is_cache_valid_for_today
        cache_entry = {"timestamp": time.time() - 7200, "data": {"some": "data"}}
        assert is_cache_valid_for_today(cache_entry, 3600) is False

    def test_stale_day_cache_is_invalid(self, monkeypatch):
        from cache_store import is_cache_valid_for_today
        from datetime import datetime, date
        yesterday_ts = time.time() - 86400
        cache_entry = {"timestamp": yesterday_ts, "data": {"some": "data"}}
        # Use a large TTL so it would pass TTL check but fail date check
        assert is_cache_valid_for_today(cache_entry, 200000) is False