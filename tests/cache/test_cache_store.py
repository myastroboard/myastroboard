"""
Unit tests for cache store (cache_store.py)
Tests the server-side cache management system with TTL-based expiration
and the per-location cache slots introduced by v1.2 multi-location profiles.
"""

import json
import pytest
import sys
import time
import os
import uuid
from cache import cache_store
from cache import cache_store as cs
from utils.constants import CACHE_TTL, DATA_DIR_CACHE

is_cache_valid = cache_store.is_cache_valid
is_astronomical_cache_ready = cache_store.is_astronomical_cache_ready
has_location_changed = cache_store.has_location_changed
reset_all_caches = cache_store.reset_all_caches
update_location_config = cache_store.update_location_config
get_current_location_signature = cache_store.get_current_location_signature
get_cache_init_status = cache_store.get_cache_init_status
set_cache_initialization_in_progress = cache_store.set_cache_initialization_in_progress
is_cache_valid_for_today = cache_store.is_cache_valid_for_today


@pytest.fixture(autouse=True)
def reset_location_tracking_state():
    """Reset location signature tracking to avoid cross-test contamination."""
    cache_store._last_known_location_signatures.clear()

    location_cache_file = os.path.join(DATA_DIR_CACHE, 'location_cache.json')
    if os.path.exists(location_cache_file):
        os.remove(location_cache_file)

    yield


class TestLocationScopedRegistry:
    """Structure of the per-location cache registry (v1.2)."""

    def test_registry_covers_every_scoped_name(self):
        assert set(cache_store._location_caches.keys()) == set(cache_store.LOCATION_SCOPED_CACHE_TTLS.keys())

    def test_expected_names_are_scoped(self):
        for name in (
            'moon_report',
            'dark_window',
            'moon_planner',
            'sun_report',
            'best_window_strict',
            'best_window_practical',
            'best_window_illumination',
            'solar_eclipse',
            'lunar_eclipse',
            'horizon_graph',
            'aurora',
            'iss_passes',
            'css_passes',
            'planetary_events',
            'special_phenomena',
            'solar_system_events',
            'sidereal_time',
            'seeing_forecast',
            'weather_forecast',
        ):
            assert name in cache_store.LOCATION_SCOPED_CACHE_TTLS

    def test_entry_created_on_demand_with_zero_state(self):
        loc_id = str(uuid.uuid4())
        entry = cache_store.get_location_cache_entry('sun_report', loc_id)
        assert entry == {'timestamp': 0, 'data': None}
        # Same object returned on second access (mutable slot)
        assert cache_store.get_location_cache_entry('sun_report', loc_id) is entry

    def test_location_cache_key_format(self):
        assert cache_store.location_cache_key('sun_report', 'abc') == 'sun_report:abc'


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
    """Test per-preset location configuration change detection"""

    def test_get_current_location_signature(self):
        """Test location signature creation"""
        location = {"latitude": 45.5, "longitude": -73.5, "elevation": 100, "timezone": "America/Montreal"}
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
        location = {"latitude": 45.5, "longitude": -73.5, "elevation": 100, "timezone": "America/Montreal"}
        assert has_location_changed(location) is True

    @pytest.mark.parametrize(
        "field,new_value",
        [
            ("latitude", 46.5),
            ("longitude", -74.5),
            ("elevation", 200),
            ("timezone", "America/New_York"),
        ],
    )
    def test_has_location_changed_per_field(self, field, new_value):
        """Each tracked field triggers change detection independently"""
        location1 = {"latitude": 45.5, "longitude": -73.5, "elevation": 100, "timezone": "America/Montreal"}
        update_location_config(location1)

        location2 = dict(location1)
        location2[field] = new_value
        assert has_location_changed(location2) is True

    def test_has_location_changed_no_change(self):
        """Test location change detection when nothing changed"""
        location = {"latitude": 45.5, "longitude": -73.5, "elevation": 100, "timezone": "America/Montreal"}
        update_location_config(location)

        # Same location
        assert has_location_changed(location) is False

    def test_update_location_config(self):
        """Test updating tracked location config (legacy flat slot)"""
        location = {"latitude": 40.7, "longitude": -74.0, "elevation": 50, "timezone": "America/New_York"}
        update_location_config(location)

        stored = cache_store._last_known_location_signatures[cache_store._LEGACY_SIGNATURE_KEY]
        assert stored["latitude"] == 40.7
        assert stored["longitude"] == -74.0

    def test_signatures_are_independent_per_preset_id(self):
        """v1.2: each preset id tracks its own signature"""
        preset_a = {"id": "loc-a", "latitude": 1.0, "longitude": 2.0, "elevation": 3, "timezone": "UTC"}
        preset_b = {"id": "loc-b", "latitude": 9.0, "longitude": 8.0, "elevation": 7, "timezone": "UTC"}
        update_location_config(preset_a)
        assert has_location_changed(preset_a) is False
        assert has_location_changed(preset_b) is True  # never tracked

        update_location_config(preset_b)
        moved_a = dict(preset_a, latitude=1.5)
        assert has_location_changed(moved_a) is True
        assert has_location_changed(preset_b) is False  # untouched by A's change

    def test_remove_location_signature(self):
        preset = {"id": "loc-gone", "latitude": 1.0, "longitude": 2.0, "elevation": 3, "timezone": "UTC"}
        update_location_config(preset)
        assert cache_store.is_location_tracked(preset) is True
        cache_store.remove_location_signature("loc-gone")
        assert cache_store.is_location_tracked(preset) is False


class TestCacheReset:
    """Test cache reset functionality (per-location slots, v1.2)"""

    def test_reset_all_caches_clears_every_location_slot(self):
        loc_a, loc_b = str(uuid.uuid4()), str(uuid.uuid4())
        cache_store.update_location_cache("moon_report", loc_a, {"test": "a"})
        cache_store.update_location_cache("sun_report", loc_b, {"test": "b"})

        reset_all_caches()

        assert cache_store.get_location_cache_entry("moon_report", loc_a)["data"] is None
        assert cache_store.get_location_cache_entry("moon_report", loc_a)["timestamp"] == 0
        assert cache_store.get_location_cache_entry("sun_report", loc_b)["data"] is None

    def test_reset_caches_for_location_only_touches_that_preset(self):
        loc_a, loc_b = str(uuid.uuid4()), str(uuid.uuid4())
        cache_store.update_location_cache("horizon_graph", loc_a, {"v": 1})
        cache_store.update_location_cache("horizon_graph", loc_b, {"v": 2})

        cache_store.reset_caches_for_location(loc_a)

        assert cache_store.load_location_cache("horizon_graph", loc_a)["data"] is None
        assert cache_store.load_location_cache("horizon_graph", loc_b)["data"] == {"v": 2}

    def test_reset_all_caches_skips_unrecognized_shared_keys(self):
        """A shared-cache key whose base name isn't a known scoped cache or
        spaceflight entry (e.g. leftover/foreign data) must be left untouched."""
        cache_store.update_shared_cache_entry("totally_unrelated_key", {"kept": True}, 111.0)

        reset_all_caches()

        entry = cache_store.load_shared_cache_entry("totally_unrelated_key")
        assert entry["data"] == {"kept": True}


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
        assert "locations" in status  # v1.2 per-location detail block
        assert "ttls" in status

        # Should be booleans
        assert isinstance(status["all_ready"], bool)
        assert isinstance(status["in_progress"], bool)

        # AllSky connector is not configured in the test environment - its
        # jobs must not appear as permanently "stale" for no reason.
        assert "allsky_sensor" not in status
        assert "allsky_health" not in status
        assert "allsky_sensor" not in status["ttls"]
        assert "allsky_health" not in status["ttls"]

    def test_get_cache_init_status_allsky_configured(self, monkeypatch):
        """AllSky connector fully enabled (incl. the sensor_data module toggle)
        -> both jobs appear in status and ttls."""
        monkeypatch.setattr(
            "utils.repo_config.load_config",
            lambda: {
                "connectors": {
                    "allsky": {
                        "enabled": True,
                        "url": "http://allsky.local",
                        "modules": {"sensor_data": {"enabled": True}},
                    }
                }
            },
        )
        status = get_cache_init_status()
        assert "allsky_sensor" in status
        assert "allsky_health" in status
        assert "allsky_sensor" in status["ttls"]
        assert "allsky_health" in status["ttls"]

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
        reset_all_caches()
        assert is_astronomical_cache_ready() is False

    def test_is_astronomical_cache_ready_explicit_ids(self):
        """Explicit location_ids: all-empty slots are not ready"""
        assert is_astronomical_cache_ready([str(uuid.uuid4())]) is False

    def test_is_astronomical_cache_ready_no_ids(self):
        assert is_astronomical_cache_ready([]) is False


class TestReadSharedCacheMissingFile:
    """_read_shared_cache returns {} when shared cache file doesn't exist."""

    def test_returns_empty_dict_when_file_absent(self, monkeypatch):
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', '/nonexistent/path/astro_cache.json')
        result = cache_store._read_shared_cache()
        assert result == {}


class TestLoadSharedCacheEntryMissingKeys:
    """load_shared_cache_entry returns None when entry is a dict missing timestamp/data."""

    def test_entry_missing_timestamp(self, monkeypatch):
        monkeypatch.setattr(cache_store, '_read_shared_cache', lambda: {"mykey": {"data": "foo"}})
        result = cache_store.load_shared_cache_entry("mykey")
        assert result is None

    def test_entry_missing_data(self, monkeypatch):
        monkeypatch.setattr(cache_store, '_read_shared_cache', lambda: {"mykey": {"timestamp": 123}})
        result = cache_store.load_shared_cache_entry("mykey")
        assert result is None


class TestLoadLocationSignaturesFile:
    """_load_location_signatures reads file contents or swallows exceptions."""

    def test_legacy_flat_file_maps_to_legacy_slot(self, tmp_path, monkeypatch):

        location_data = {"latitude": 51.5, "longitude": -0.12, "elevation": 10, "timezone": "Europe/London"}
        loc_file = tmp_path / 'location_cache.json'
        loc_file.write_text(json.dumps(location_data))
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(loc_file))
        cache_store._load_location_signatures()
        legacy = cache_store._last_known_location_signatures[cache_store._LEGACY_SIGNATURE_KEY]
        assert legacy["latitude"] == 51.5
        assert legacy["timezone"] == "Europe/London"

    def test_per_id_file_shape_loads_directly(self, tmp_path, monkeypatch):

        data = {"loc-1": {"latitude": 1.0, "longitude": 2.0, "elevation": 3, "timezone": "UTC"}}
        loc_file = tmp_path / 'location_cache.json'
        loc_file.write_text(json.dumps(data))
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(loc_file))
        cache_store._load_location_signatures()
        assert cache_store._last_known_location_signatures["loc-1"]["latitude"] == 1.0

    def test_corrupted_file_swallows_exception(self, tmp_path, monkeypatch):
        loc_file = tmp_path / 'location_cache.json'
        loc_file.write_text("NOT VALID JSON {{{{")
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(loc_file))
        cache_store._load_location_signatures()  # must not raise

    def test_non_dict_json_is_ignored(self, tmp_path, monkeypatch):
        """A valid JSON array (neither the legacy nor per-id dict shape) matches
        neither branch - the loader must leave the in-memory state untouched
        rather than raising or storing a non-dict value."""

        loc_file = tmp_path / 'location_cache.json'
        loc_file.write_text(json.dumps(["not", "a", "dict"]))
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(loc_file))
        monkeypatch.setattr(cache_store, '_last_known_location_signatures', {'sentinel': True})
        cache_store._load_location_signatures()
        assert cache_store._last_known_location_signatures == {'sentinel': True}


class TestSaveLocationSignaturesException:
    """_save_location_signatures swallows write exceptions silently."""

    def test_save_exception_is_silently_ignored(self, monkeypatch):
        import builtins

        original_open = builtins.open

        def raising_open(path, mode='r', **kwargs):
            if 'w' in mode and 'location_cache' in str(path):
                raise PermissionError("no write access")
            return original_open(path, mode, **kwargs)

        monkeypatch.setattr(builtins, 'open', raising_open)
        cache_store._save_location_signatures()  # must not propagate the exception


class TestHasLocationChangedNoneConfig:
    """has_location_changed returns True when new config is None."""

    def test_none_config_treated_as_changed(self):
        result = has_location_changed(None)
        assert result is True


class TestUpdateLocationConfigNone:
    """update_location_config is a no-op when signature is None."""

    def test_none_config_leaves_state_unchanged(self):
        before = dict(cache_store._last_known_location_signatures)
        update_location_config(None)
        assert cache_store._last_known_location_signatures == before


class TestIsCacheValidForToday:
    """is_cache_valid_for_today checks both TTL and calendar date."""

    def test_fresh_cache_from_today_is_valid(self):

        cache_entry = {"timestamp": time.time(), "data": {"some": "data"}}
        assert is_cache_valid_for_today(cache_entry, 3600) is True

    def test_expired_cache_is_invalid(self):

        cache_entry = {"timestamp": time.time() - 7200, "data": {"some": "data"}}
        assert is_cache_valid_for_today(cache_entry, 3600) is False

    def test_fresh_cache_valid_with_explicit_timezone(self):
        cache_entry = {"timestamp": time.time(), "data": {"some": "data"}}
        assert is_cache_valid_for_today(cache_entry, 3600, tz_name="Europe/Paris") is True

    def test_unknown_timezone_falls_back_to_server_local(self):
        cache_entry = {"timestamp": time.time(), "data": {"some": "data"}}
        # An unresolvable timezone must not raise; it degrades to the server day boundary.
        assert is_cache_valid_for_today(cache_entry, 3600, tz_name="Not/AZone") is True

    def test_stale_day_cache_is_invalid(self, monkeypatch):

        yesterday_ts = time.time() - 86400
        cache_entry = {"timestamp": yesterday_ts, "data": {"some": "data"}}
        # Use a large TTL so it would pass TTL check but fail date check
        assert is_cache_valid_for_today(cache_entry, 200000) is False


class TestReadSharedCacheCorrupt:
    """Corrupted shared cache file returns empty dict."""

    def test_corrupt_json_returns_empty(self, tmp_path, monkeypatch):

        bad_file = tmp_path / "bad_cache.json"
        bad_file.write_text("{ broken json <<<", encoding="utf-8")
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(bad_file))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "astro.lock"))
        result = cache_store._read_shared_cache()
        assert result == {}


class TestUpdateAndLoadSharedCacheEntry:
    """update_shared_cache_entry / load_shared_cache_entry roundtrips."""

    def test_update_then_load_roundtrip(self, tmp_path, monkeypatch):

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "cache.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "cache.lock"))
        ts = time.time()
        cache_store.update_shared_cache_entry("test_key", {"value": 42}, ts)
        entry = cache_store.load_shared_cache_entry("test_key")
        assert entry is not None
        assert entry["data"]["value"] == 42
        assert entry["timestamp"] == ts

    def test_load_missing_key_returns_none(self, tmp_path, monkeypatch):

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "cache2.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "cache2.lock"))
        result = cache_store.load_shared_cache_entry("no_such_key")
        assert result is None

    def test_load_entry_not_dict_returns_none(self, tmp_path, monkeypatch):

        cache_file = tmp_path / "cache3.json"
        cache_file.write_text(json.dumps({"test_key": "not_a_dict"}), encoding="utf-8")
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "cache3.lock"))
        result = cache_store.load_shared_cache_entry("test_key")
        assert result is None

    def test_load_entry_missing_timestamp_returns_none(self, tmp_path, monkeypatch):

        cache_file = tmp_path / "cache4.json"
        cache_file.write_text(json.dumps({"test_key": {"data": 42}}), encoding="utf-8")
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "cache4.lock"))
        result = cache_store.load_shared_cache_entry("test_key")
        assert result is None


class TestSyncCacheFromShared:
    """sync_cache_from_shared (still used by global caches)."""

    def test_sync_updates_in_memory_entry(self, tmp_path, monkeypatch):

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "sync.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "sync.lock"))
        ts = time.time()
        cache_store.update_shared_cache_entry("spaceflight_launches", {"count": 3}, ts)
        local_entry = {"timestamp": 0, "data": None}
        result = cache_store.sync_cache_from_shared("spaceflight_launches", local_entry)
        assert result is True
        assert local_entry["data"] == {"count": 3}
        assert local_entry["timestamp"] == ts

    def test_sync_returns_false_when_no_data(self, tmp_path, monkeypatch):

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "sync2.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "sync2.lock"))
        local_entry = {"timestamp": 0, "data": None}
        result = cache_store.sync_cache_from_shared("nonexistent_key", local_entry)
        assert result is False


class TestSyncAllFromShared:
    """_sync_all_from_shared hydrates location slots from keyed entries."""

    def test_keyed_entries_hydrate_registry(self, tmp_path, monkeypatch):

        loc_id = str(uuid.uuid4())
        shared = {
            f"sun_report:{loc_id}": {"timestamp": time.time(), "data": {"sun": True}},
            "spaceflight_launches": {"timestamp": time.time(), "data": {"launches": []}},
        }
        cache_file = tmp_path / "syncall.json"
        cache_file.write_text(json.dumps(shared), encoding="utf-8")
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "syncall.lock"))

        cache_store._sync_all_from_shared()

        assert cache_store.get_location_cache_entry("sun_report", loc_id)["data"] == {"sun": True}
        assert cache_store._spaceflight_launches_cache["data"] == {"launches": []}


class TestGetCacheStatusProgressPercent:
    """progress_percent calculation when total_steps > 0."""

    def test_progress_percent_computed_from_shared_cache(self, tmp_path, monkeypatch):

        shared = {
            "_cache_in_progress": {
                "status": True,
                "current_step": 3,
                "total_steps": 10,
                "step_name": "computing",
            }
        }
        cache_file = tmp_path / "status_cache.json"
        cache_file.write_text(json.dumps(shared), encoding="utf-8")
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "status.lock"))
        result = cache_store.get_cache_init_status()
        assert result.get("in_progress") is True
        assert result.get("progress_percent") == 30


class TestLoadLocationSignaturesFileAbsent:
    """_load_location_signatures is a no-op when file doesn't exist."""

    def test_missing_file_leaves_state_unchanged(self, tmp_path, monkeypatch):

        absent_path = str(tmp_path / "nonexistent_location.json")
        monkeypatch.setattr(cs, '_LOCATION_CACHE_FILE', absent_path)
        before = dict(cache_store._last_known_location_signatures)
        cache_store._load_location_signatures()
        assert cache_store._last_known_location_signatures == before


class TestCacheInitStatusNoCacheInProgress:
    """get_cache_init_status with no _cache_in_progress in shared cache."""

    def test_no_cache_in_progress_key(self, tmp_path, monkeypatch):

        shared = {"some_other_key": {"timestamp": 0, "data": None}}
        cache_file = tmp_path / "no_progress.json"
        cache_file.write_text(json.dumps(shared), encoding="utf-8")
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "no_progress.lock"))
        result = cache_store.get_cache_init_status()
        assert result.get("in_progress") is False
        assert result.get("progress_percent") == 0


class TestRecordCacheExecution:
    """record_cache_execution + get_cache_metrics."""

    def test_record_then_get_metrics(self, tmp_path, monkeypatch):

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "metricache_store.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "metricache_store.lock"))
        cache_store.record_cache_execution("moon_report", 1.234, True)
        metrics = cache_store.get_cache_metrics()
        assert "moon_report" in metrics
        assert metrics["moon_report"]["last_success"] is True
        assert metrics["moon_report"]["last_duration_s"] == 1.234

    def test_second_record_updates_existing_metrics(self, tmp_path, monkeypatch):

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "metrics2.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "metrics2.lock"))
        cache_store.record_cache_execution("sun_report", 0.5, True)
        cache_store.record_cache_execution("sun_report", 1.0, False)  # updates existing _cache_metrics
        metrics = cache_store.get_cache_metrics()
        assert metrics["sun_report"]["last_success"] is False
        assert metrics["sun_report"]["last_duration_s"] == 1.0


class TestIsExecutionMetricsValid:
    """Tests for _is_execution_metrics_valid — allsky validity uses shared execution metrics."""

    def test_returns_false_when_no_metrics_for_job(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "ev1.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "ev1.lock"))
        assert cache_store._is_execution_metrics_valid("allsky_sensor", 300) is False

    def test_returns_false_when_last_success_is_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "ev2.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "ev2.lock"))
        cache_store.record_cache_execution("allsky_sensor", 0.1, False)
        assert cache_store._is_execution_metrics_valid("allsky_sensor", 300) is False

    def test_returns_true_when_recent_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "ev3.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "ev3.lock"))
        cache_store.record_cache_execution("allsky_sensor", 0.1, True)
        assert cache_store._is_execution_metrics_valid("allsky_sensor", 300) is True

    def test_returns_false_when_success_but_expired(self, tmp_path, monkeypatch):
        from datetime import datetime, timezone, timedelta

        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "ev4.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "ev4.lock"))
        cache_store.record_cache_execution("allsky_sensor", 0.1, True)
        # Manually backdate the last_run_at to simulate expiry

        with open(str(tmp_path / "ev4.json")) as f:
            data = json.load(f)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        data["_cache_metrics"]["allsky_sensor"]["last_run_at"] = old_ts
        with open(str(tmp_path / "ev4.json"), "w") as f:
            json.dump(data, f)
        assert cache_store._is_execution_metrics_valid("allsky_sensor", 300) is False

    def test_returns_false_when_last_run_at_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "ev5.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "ev5.lock"))
        cache_store.record_cache_execution("allsky_sensor", 0.1, True)

        with open(str(tmp_path / "ev5.json")) as f:
            data = json.load(f)
        del data["_cache_metrics"]["allsky_sensor"]["last_run_at"]
        with open(str(tmp_path / "ev5.json"), "w") as f:
            json.dump(data, f)
        assert cache_store._is_execution_metrics_valid("allsky_sensor", 300) is False

    def test_returns_false_when_last_run_at_unparseable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, '_SHARED_CACHE_FILE', str(tmp_path / "ev6.json"))
        monkeypatch.setattr(cs, '_SHARED_CACHE_LOCK', str(tmp_path / "ev6.lock"))
        cache_store.record_cache_execution("allsky_sensor", 0.1, True)

        with open(str(tmp_path / "ev6.json")) as f:
            data = json.load(f)
        data["_cache_metrics"]["allsky_sensor"]["last_run_at"] = "not-a-valid-timestamp"
        with open(str(tmp_path / "ev6.json"), "w") as f:
            json.dump(data, f)
        assert cache_store._is_execution_metrics_valid("allsky_sensor", 300) is False


@pytest.mark.skipif(sys.platform != "win32", reason="_msvcrt_lock is only defined on Windows")
class TestMsvcrtLock:
    """_msvcrt_lock retries transient OSError from msvcrt.locking a few times before giving up."""

    def test_succeeds_on_first_try(self, monkeypatch):
        calls = []
        monkeypatch.setattr(cs.msvcrt, "locking", lambda *a: calls.append(a))
        cs._msvcrt_lock(fileno=7)
        assert len(calls) == 1

    def test_retries_then_succeeds(self, monkeypatch):
        attempts = {"n": 0}

        def _flaky_locking(fileno, mode, nbytes):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OSError("pretend deadlock timeout")

        monkeypatch.setattr(cs.msvcrt, "locking", _flaky_locking)
        monkeypatch.setattr(cs.time, "sleep", lambda *_: None)
        cs._msvcrt_lock(fileno=7)
        assert attempts["n"] == 3

    def test_raises_after_exhausting_all_attempts(self, monkeypatch):
        def _always_fails(fileno, mode, nbytes):
            raise OSError("pretend deadlock timeout")

        monkeypatch.setattr(cs.msvcrt, "locking", _always_fails)
        monkeypatch.setattr(cs.time, "sleep", lambda *_: None)
        with pytest.raises(OSError):
            cs._msvcrt_lock(fileno=7)


# ---------------------------------------------------------------------------
# Merged from former test_coverage_edge_cases.py
# ---------------------------------------------------------------------------

def test_cache_store_default_status_location_ids_handles_exception(monkeypatch):
    from cache import cache_store

    monkeypatch.setattr("utils.repo_config.load_config", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cache_store._default_status_location_ids() == []


def test_cache_store_default_status_location_ids_falls_through_when_no_ids(monkeypatch):
    """No exception, but every scheduler location lacks a truthy id -> falls
    through the `if ids:` check to the trailing `return []` (not the except arc)."""
    from cache import cache_store

    monkeypatch.setattr("utils.repo_config.load_config", lambda: {})
    monkeypatch.setattr("utils.repo_config.get_scheduler_locations", lambda config: [{'name': 'no-id-here'}])
    assert cache_store._default_status_location_ids() == []


def test_cache_store_allsky_job_availability_handles_exception(monkeypatch):
    from cache import cache_store

    monkeypatch.setattr("utils.repo_config.load_config", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cache_store._allsky_job_availability() == (False, False)


# ---------------------------------------------------------------------------
# Merged from former test_locations_coverage.py
# ---------------------------------------------------------------------------

class TestCacheStoreEdgeArcs:
    def test_sync_all_from_shared_full_matrix(self, monkeypatch):
        loc = str(uuid.uuid4())
        # Future timestamp so a concurrent background refresh (app import starts
        # cache threads) can never look "newer" and clobber the assertion window.
        now = time.time() + 3600
        shared = {
            'spaceflight_launches': {'timestamp': now, 'data': {'launches': [1]}},
            'iers': 'not-a-dict',  # global entry with junk shape -> skipped
            f'sun_report:{loc}': {'timestamp': now, 'data': {'sun': 1}},
            f'sun_report:{loc}-older': {'timestamp': 0, 'data': None},  # data None -> skipped
            f'unknown_cache:{loc}': {'timestamp': now, 'data': {'x': 1}},  # unknown name -> skipped
            'plainkey': {'timestamp': now, 'data': {'y': 1}},  # no colon -> skipped
            f'moon_report:{loc}': 'junk-entry',  # keyed entry non-dict -> skipped
        }
        # Bypass the shared file: background cache threads do read-modify-write
        # cycles on it and could clobber seeded entries mid-test. The matrix
        # under test is the sync loop, which reads via _read_shared_cache().
        monkeypatch.setattr(cache_store, '_read_shared_cache', lambda: json.loads(json.dumps(shared)))

        cache_store._sync_all_from_shared()
        assert cache_store._spaceflight_launches_cache['data'] == {'launches': [1]}
        assert cache_store.get_location_cache_entry('sun_report', loc)['data'] == {'sun': 1}

    def test_sync_keyed_entry_older_than_memory_not_applied(self, tmp_path, monkeypatch):
        loc = str(uuid.uuid4())
        entry = cache_store.get_location_cache_entry('sun_report', loc)
        entry['data'] = {'fresh': True}
        entry['timestamp'] = time.time() + 3600

        shared = {f'sun_report:{loc}': {'timestamp': 1.0, 'data': {'stale': True}}}
        cache_file = tmp_path / 'older.json'
        cache_file.write_text(json.dumps(shared), encoding='utf-8')
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(cache_file))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'older.lock'))

        cache_store._sync_all_from_shared()
        assert entry['data'] == {'fresh': True}

    def test_is_astronomical_cache_ready_true_when_all_valid(self, tmp_path, monkeypatch):
        loc = str(uuid.uuid4())
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'ready.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'ready.lock'))
        now = time.time()
        for name in cache_store._READINESS_LOCATION_CACHES:
            entry = cache_store.get_location_cache_entry(name, loc)
            entry['data'] = {'ok': True}
            entry['timestamp'] = now
        for global_entry in (
            cache_store._spaceflight_launches_cache,
            cache_store._spaceflight_astronauts_cache,
            cache_store._spaceflight_events_cache,
        ):
            global_entry['data'] = {'ok': True}
            global_entry['timestamp'] = now

        assert cache_store.is_astronomical_cache_ready([loc]) is True

    def test_is_astronomical_cache_ready_false_when_spaceflight_stale(self, tmp_path, monkeypatch):
        loc = str(uuid.uuid4())
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'notready.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'notready.lock'))
        now = time.time()
        for name in cache_store._READINESS_LOCATION_CACHES:
            entry = cache_store.get_location_cache_entry(name, loc)
            entry['data'] = {'ok': True}
            entry['timestamp'] = now
        cache_store._spaceflight_launches_cache['data'] = None
        cache_store._spaceflight_launches_cache['timestamp'] = 0

        assert cache_store.is_astronomical_cache_ready([loc]) is False

    def test_is_astronomical_cache_ready_false_without_locations(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'noloc.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'noloc.lock'))
        assert cache_store.is_astronomical_cache_ready([]) is False

    def test_get_cache_init_status_without_locations(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_FILE', str(tmp_path / 'status.json'))
        monkeypatch.setattr(cache_store, '_SHARED_CACHE_LOCK', str(tmp_path / 'status.lock'))
        status = cache_store.get_cache_init_status(location_ids=[])
        assert status['all_ready'] is False
        assert status['locations'] == {}
        assert status['sun_report'] is False  # primary_id None -> every slot False

    def test_remove_location_signature_unknown_id_is_noop(self):
        saves = []
        original = cache_store._save_location_signatures
        cache_store._save_location_signatures = lambda: saves.append(1)
        try:
            cache_store.remove_location_signature('ghost-' + uuid.uuid4().hex)
        finally:
            cache_store._save_location_signatures = original
        assert saves == []

    def test_load_location_signatures_corrupt_file_ignored(self, tmp_path, monkeypatch):
        bad = tmp_path / 'location_cache.json'
        bad.write_text('{corrupt json', encoding='utf-8')
        monkeypatch.setattr(cache_store, '_LOCATION_CACHE_FILE', str(bad))
        cache_store._load_location_signatures()  # must not raise

    def test_execution_metrics_missing_last_run_at(self, monkeypatch):
        monkeypatch.setattr(cache_store, 'get_cache_metrics', lambda: {'jobx': {'last_success': True}})
        assert cache_store._is_execution_metrics_valid('jobx', 60) is False
