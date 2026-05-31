"""
Server-side cache management with TTL-based expiration and config change detection.
All cache management is handled server-side only.
"""
import time
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from constants import (
    CACHE_TTL, WEATHER_CACHE_TTL, DATA_DIR_CACHE,
    CACHE_TTL_MOON_REPORT, CACHE_TTL_DARK_WINDOW, CACHE_TTL_MOON_PLANNER,
    CACHE_TTL_SUN_REPORT, CACHE_TTL_BEST_WINDOW, CACHE_TTL_SOLAR_ECLIPSE,
    CACHE_TTL_LUNAR_ECLIPSE, CACHE_TTL_HORIZON_GRAPH, CACHE_TTL_AURORA,
    CACHE_TTL_ISS_PASSES, CACHE_TTL_PLANETARY_EVENTS, CACHE_TTL_SPECIAL_PHENOMENA,
    CACHE_TTL_SOLAR_SYSTEM_EVENTS, CACHE_TTL_SIDEREAL_TIME, CACHE_TTL_SEEING_FORECAST,
    CACHE_TTL_SPACEFLIGHT_LAUNCHES, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS, CACHE_TTL_SPACEFLIGHT_EVENTS,
    CACHE_TTL_IERS,
)

# Windows-compatible file locking
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# Cache entries with timestamp for TTL tracking
_moon_report_cache = {"timestamp": 0, "data": None}
_sun_report_cache = {"timestamp": 0, "data": None}
_best_window_cache = {
    "strict": {"timestamp": 0, "data": None},
    "practical": {"timestamp": 0, "data": None},
    "illumination": {"timestamp": 0, "data": None}
}
_moon_planner_report_cache = {"timestamp": 0, "data": None}
_dark_window_report_cache = {"timestamp": 0, "data": None}
_solar_eclipse_cache = {"timestamp": 0, "data": None}
_lunar_eclipse_cache = {"timestamp": 0, "data": None}
_horizon_graph_cache = {"timestamp": 0, "data": None}
_aurora_cache = {"timestamp": 0, "data": None}
_iss_passes_cache = {"timestamp": 0, "data": None}
_planetary_events_cache = {"timestamp": 0, "data": None}
_special_phenomena_cache = {"timestamp": 0, "data": None}
_solar_system_events_cache = {"timestamp": 0, "data": None}
_sidereal_time_cache = {"timestamp": 0, "data": None}
_seeing_forecast_cache = {"timestamp": 0, "data": None}

# Spaceflight caches (Launch Library 2)
_spaceflight_launches_cache = {"timestamp": 0, "data": None}
_spaceflight_astronauts_cache = {"timestamp": 0, "data": None}
_spaceflight_events_cache = {"timestamp": 0, "data": None}

# Weather cache (separate TTL)
_weather_cache = {"timestamp": 0, "data": None}

# IERS-A Earth-orientation data cache (managed by scheduler, long TTL)
_iers_cache = {"timestamp": 0, "data": None}

# Version update check cache (separate TTL)
_version_update_cache = {"timestamp": 0, "data": None}

# Track the last known location config to detect changes
# This is loaded from disk to survive restarts
_LOCATION_CACHE_FILE = os.path.join(DATA_DIR_CACHE, 'location_cache.json')
_last_known_location_config = {
    "latitude": None,
    "longitude": None,
    "elevation": None,
    "timezone": None
}

# Shared cache file (cross-worker)
# Note: _cache_initialization_in_progress is now stored in the shared cache file
# to ensure visibility across all gunicorn worker processes
_SHARED_CACHE_FILE = os.path.join(DATA_DIR_CACHE, "astro_cache.json")
_SHARED_CACHE_LOCK = os.path.join(DATA_DIR_CACHE, "astro_cache.lock")


def _ensure_data_dir():
    """Ensure DATA_DIR exists before file operations"""
    os.makedirs(DATA_DIR_CACHE, exist_ok=True)


@contextmanager
def _cache_file_read_lock():
    """Cross-platform SHARED lock - multiple concurrent readers allowed."""
    _ensure_data_dir()
    lock_file = open(_SHARED_CACHE_LOCK, "a+")
    try:
        if sys.platform == "win32":
            # msvcrt has no native shared lock; fall back to exclusive on Windows.
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        yield
    finally:
        try:
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


@contextmanager
def _cache_file_write_lock():
    """Cross-platform EXCLUSIVE lock - for writes only."""
    _ensure_data_dir()
    lock_file = open(_SHARED_CACHE_LOCK, "a+")
    try:
        if sys.platform == "win32":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


# Keep the old name as an alias so any external callers are unaffected.
_cache_file_lock = _cache_file_write_lock


def _read_shared_cache():
    """Read shared cache file safely"""
    _ensure_data_dir()
    if not os.path.exists(_SHARED_CACHE_FILE):
        return {}
    try:
        with open(_SHARED_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        # If file is corrupted, ignore and treat as empty
        return {}


def _write_shared_cache(shared_cache):
    """Write shared cache file safely"""
    _ensure_data_dir()
    with open(_SHARED_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(shared_cache, f, indent=2, ensure_ascii=False)


def update_shared_cache_entry(key, data, timestamp):
    """Update a single shared cache entry"""
    with _cache_file_write_lock():
        shared_cache = _read_shared_cache()
        shared_cache[key] = {"timestamp": timestamp, "data": data}
        _write_shared_cache(shared_cache)


def load_shared_cache_entry(key):
    """Load a single cache entry from shared cache"""
    with _cache_file_read_lock():
        shared_cache = _read_shared_cache()
        entry = shared_cache.get(key)
        if not isinstance(entry, dict):
            return None
        if "timestamp" not in entry or "data" not in entry:
            return None
        return entry


def sync_cache_from_shared(key, cache_entry):
    """Sync in-memory cache entry from shared cache file"""
    entry = load_shared_cache_entry(key)
    if not entry or entry.get("data") is None:
        return False
    cache_entry["data"] = entry.get("data")
    cache_entry["timestamp"] = entry.get("timestamp", 0)
    return True


def _write_all_astronomical_caches_to_shared():
    """Persist all astronomical caches to shared file"""
    with _cache_file_write_lock():
        shared_cache = _read_shared_cache()
        shared_cache.update({
            "moon_report": _moon_report_cache,
            "sun_report": _sun_report_cache,
            "moon_planner": _moon_planner_report_cache,
            "dark_window": _dark_window_report_cache,
            "best_window_strict": _best_window_cache["strict"],
            "best_window_practical": _best_window_cache["practical"],
            "best_window_illumination": _best_window_cache["illumination"],
            "solar_eclipse": _solar_eclipse_cache,
            "lunar_eclipse": _lunar_eclipse_cache,
            "horizon_graph": _horizon_graph_cache,
            "aurora": _aurora_cache,
            "iss_passes": _iss_passes_cache,
            "planetary_events": _planetary_events_cache,
            "special_phenomena": _special_phenomena_cache,
            "solar_system_events": _solar_system_events_cache,
            "sidereal_time": _sidereal_time_cache,
            "seeing_forecast": _seeing_forecast_cache,
            "spaceflight_launches": _spaceflight_launches_cache,
            "spaceflight_astronauts": _spaceflight_astronauts_cache,
            "spaceflight_events": _spaceflight_events_cache,
            "iers": _iers_cache,
        })
        _write_shared_cache(shared_cache)


def _load_location_cache():
    """Load persisted location config from disk"""
    global _last_known_location_config
    try:
        _ensure_data_dir()
        if os.path.exists(_LOCATION_CACHE_FILE):
            with open(_LOCATION_CACHE_FILE, 'r') as f:
                _last_known_location_config = json.load(f)
    except Exception:
        # If loading fails, keep the default None values
        pass


def _save_location_cache():
    """Persist location config to disk"""
    try:
        _ensure_data_dir()
        with open(_LOCATION_CACHE_FILE, 'w') as f:
            json.dump(_last_known_location_config, f, indent=2, ensure_ascii=False)
    except Exception:
        # Not critical if save fails, just means next restart might trigger false positive
        pass


# Load persisted location on module import
_load_location_cache()


def get_current_location_signature(location_config):
    """Create a signature of location parameters for change detection"""
    if not location_config:
        return None
    return {
        "latitude": location_config.get("latitude"),
        "longitude": location_config.get("longitude"),
        "elevation": location_config.get("elevation"),
        "timezone": location_config.get("timezone")
    }


def has_location_changed(new_location_config):
    """Check if location parameters have changed"""
    current_signature = get_current_location_signature(new_location_config)
    
    # If current signature is None (invalid config), consider it as changed
    if current_signature is None:
        return True
    
    # If last config was not set, location has "changed" (first time)
    if _last_known_location_config["latitude"] is None:
        return True
    
    # Compare current signature with last known
    return (
        _last_known_location_config["latitude"] != current_signature["latitude"] or
        _last_known_location_config["longitude"] != current_signature["longitude"] or
        _last_known_location_config["elevation"] != current_signature["elevation"] or
        _last_known_location_config["timezone"] != current_signature["timezone"]
    )


def update_location_config(new_location_config):
    """Update the tracked location config and persist to disk"""
    global _last_known_location_config
    signature = get_current_location_signature(new_location_config)
    if signature:
        _last_known_location_config = signature.copy()
        _save_location_cache()


def reset_all_caches():
    """Reset all astronomical caches (called when location changes)"""
    global _moon_report_cache, _sun_report_cache, _best_window_cache
    global _moon_planner_report_cache, _dark_window_report_cache
    global _solar_eclipse_cache, _lunar_eclipse_cache, _horizon_graph_cache, _aurora_cache, _iss_passes_cache
    global _planetary_events_cache, _special_phenomena_cache, _solar_system_events_cache, _sidereal_time_cache, _seeing_forecast_cache
    global _spaceflight_launches_cache, _spaceflight_astronauts_cache, _spaceflight_events_cache

    _moon_report_cache = {"timestamp": 0, "data": None}
    _sun_report_cache = {"timestamp": 0, "data": None}
    _best_window_cache = {
        "strict": {"timestamp": 0, "data": None},
        "practical": {"timestamp": 0, "data": None},
        "illumination": {"timestamp": 0, "data": None}
    }
    _moon_planner_report_cache = {"timestamp": 0, "data": None}
    _dark_window_report_cache = {"timestamp": 0, "data": None}
    _solar_eclipse_cache = {"timestamp": 0, "data": None}
    _lunar_eclipse_cache = {"timestamp": 0, "data": None}
    _horizon_graph_cache = {"timestamp": 0, "data": None}
    _aurora_cache = {"timestamp": 0, "data": None}
    _iss_passes_cache = {"timestamp": 0, "data": None}
    _planetary_events_cache = {"timestamp": 0, "data": None}
    _special_phenomena_cache = {"timestamp": 0, "data": None}
    _solar_system_events_cache = {"timestamp": 0, "data": None}
    _sidereal_time_cache = {"timestamp": 0, "data": None}
    _seeing_forecast_cache = {"timestamp": 0, "data": None}
    _spaceflight_launches_cache = {"timestamp": 0, "data": None}
    _spaceflight_astronauts_cache = {"timestamp": 0, "data": None}
    _spaceflight_events_cache = {"timestamp": 0, "data": None}
    _write_all_astronomical_caches_to_shared()


def reset_weather_cache():
    """Reset weather cache (can be called independently)"""
    global _weather_cache
    _weather_cache = {"timestamp": 0, "data": None}


def is_cache_valid(cache_entry, ttl_seconds):
    """Check if a cache entry is still valid based on TTL"""
    if not cache_entry or cache_entry["data"] is None:
        return False
    
    current_time = time.time()
    elapsed = current_time - cache_entry["timestamp"]
    
    return elapsed < ttl_seconds


def is_cache_valid_for_today(cache_entry, ttl_seconds):
    """Like is_cache_valid, but also invalidates when the local calendar day has changed.

    Use this for caches that are computed for 'today' (sun report, horizon graph,
    moon report, etc.) - a 6h TTL would otherwise serve stale day-N data well into
    day N+1 if the cache was last populated late in the evening.
    """
    if not is_cache_valid(cache_entry, ttl_seconds):
        return False
    cache_date = datetime.fromtimestamp(cache_entry["timestamp"]).date()
    return cache_date == datetime.today().date()


def _sync_all_from_shared():
    """Read astro_cache.json ONCE and sync all in-memory caches in a single pass."""
    with _cache_file_read_lock():
        shared = _read_shared_cache()

    mapping = {
        "moon_report":              _moon_report_cache,
        "sun_report":               _sun_report_cache,
        "moon_planner":             _moon_planner_report_cache,
        "dark_window":              _dark_window_report_cache,
        "best_window_strict":       _best_window_cache["strict"],
        "best_window_practical":    _best_window_cache["practical"],
        "best_window_illumination": _best_window_cache["illumination"],
        "solar_eclipse":            _solar_eclipse_cache,
        "lunar_eclipse":            _lunar_eclipse_cache,
        "horizon_graph":            _horizon_graph_cache,
        "aurora":                   _aurora_cache,
        "iss_passes":               _iss_passes_cache,
        "planetary_events":         _planetary_events_cache,
        "special_phenomena":        _special_phenomena_cache,
        "solar_system_events":      _solar_system_events_cache,
        "sidereal_time":            _sidereal_time_cache,
        "seeing_forecast":          _seeing_forecast_cache,
        "spaceflight_launches":     _spaceflight_launches_cache,
        "spaceflight_astronauts":   _spaceflight_astronauts_cache,
        "spaceflight_events":       _spaceflight_events_cache,
        "weather_forecast":         _weather_cache,
        "iers":                     _iers_cache,
    }
    for key, cache_entry in mapping.items():
        entry = shared.get(key)
        if isinstance(entry, dict) and entry.get("data") is not None:
            cache_entry["data"]      = entry["data"]
            cache_entry["timestamp"] = entry.get("timestamp", 0)
    return shared


def is_astronomical_cache_ready():
    """Check if all astronomical caches are valid and ready"""
    _sync_all_from_shared()
    all_valid = (
        is_cache_valid(_moon_report_cache, CACHE_TTL_MOON_REPORT) and
        is_cache_valid(_sun_report_cache, CACHE_TTL_SUN_REPORT) and
        is_cache_valid(_best_window_cache["strict"], CACHE_TTL_BEST_WINDOW) and
        is_cache_valid(_moon_planner_report_cache, CACHE_TTL_MOON_PLANNER) and
        is_cache_valid(_dark_window_report_cache, CACHE_TTL_DARK_WINDOW) and
        is_cache_valid(_solar_eclipse_cache, CACHE_TTL_SOLAR_ECLIPSE) and
        is_cache_valid(_lunar_eclipse_cache, CACHE_TTL_LUNAR_ECLIPSE) and
        is_cache_valid(_horizon_graph_cache, CACHE_TTL_HORIZON_GRAPH) and
        is_cache_valid(_aurora_cache, CACHE_TTL_AURORA) and
        is_cache_valid(_iss_passes_cache, CACHE_TTL_ISS_PASSES) and
        is_cache_valid(_planetary_events_cache, CACHE_TTL_PLANETARY_EVENTS) and
        is_cache_valid(_special_phenomena_cache, CACHE_TTL_SPECIAL_PHENOMENA) and
        is_cache_valid(_solar_system_events_cache, CACHE_TTL_SOLAR_SYSTEM_EVENTS) and
        is_cache_valid(_sidereal_time_cache, CACHE_TTL_SIDEREAL_TIME) and
        is_cache_valid(_seeing_forecast_cache, CACHE_TTL_SEEING_FORECAST) and
        is_cache_valid(_spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES) and
        is_cache_valid(_spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS) and
        is_cache_valid(_spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS)
    )
    return all_valid


def get_cache_init_status():
    """Get detailed cache initialization status"""
    shared_cache = _sync_all_from_shared()

    # Read in_progress status from shared cache for cross-worker visibility
    in_progress = False
    current_step = 0
    total_steps = 0
    step_name = ""
    progress_percent = 0
    
    if "_cache_in_progress" in shared_cache:
        progress_info = shared_cache["_cache_in_progress"]
        in_progress = progress_info.get("status", False)
        current_step = progress_info.get("current_step", 0)
        total_steps = progress_info.get("total_steps", 0)
        step_name = progress_info.get("step_name", "")
        if total_steps > 0:
            progress_percent = int((current_step / total_steps) * 100)
    
    return {
        "moon_report": is_cache_valid(_moon_report_cache, CACHE_TTL_MOON_REPORT),
        "sun_report": is_cache_valid(_sun_report_cache, CACHE_TTL_SUN_REPORT),
        "best_window_strict": is_cache_valid(_best_window_cache["strict"], CACHE_TTL_BEST_WINDOW),
        "best_window_practical": is_cache_valid(_best_window_cache["practical"], CACHE_TTL_BEST_WINDOW),
        "best_window_illumination": is_cache_valid(_best_window_cache["illumination"], CACHE_TTL_BEST_WINDOW),
        "moon_planner": is_cache_valid(_moon_planner_report_cache, CACHE_TTL_MOON_PLANNER),
        "dark_window": is_cache_valid(_dark_window_report_cache, CACHE_TTL_DARK_WINDOW),
        "solar_eclipse": is_cache_valid(_solar_eclipse_cache, CACHE_TTL_SOLAR_ECLIPSE),
        "lunar_eclipse": is_cache_valid(_lunar_eclipse_cache, CACHE_TTL_LUNAR_ECLIPSE),
        "horizon_graph": is_cache_valid(_horizon_graph_cache, CACHE_TTL_HORIZON_GRAPH),
        "aurora": is_cache_valid(_aurora_cache, CACHE_TTL_AURORA),
        "iss_passes": is_cache_valid(_iss_passes_cache, CACHE_TTL_ISS_PASSES),
        "planetary_events": is_cache_valid(_planetary_events_cache, CACHE_TTL_PLANETARY_EVENTS),
        "special_phenomena": is_cache_valid(_special_phenomena_cache, CACHE_TTL_SPECIAL_PHENOMENA),
        "solar_system_events": is_cache_valid(_solar_system_events_cache, CACHE_TTL_SOLAR_SYSTEM_EVENTS),
        "sidereal_time": is_cache_valid(_sidereal_time_cache, CACHE_TTL_SIDEREAL_TIME),
        "seeing_forecast": is_cache_valid(_seeing_forecast_cache, CACHE_TTL_SEEING_FORECAST),
        "spaceflight_launches": is_cache_valid(_spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES),
        "spaceflight_astronauts": is_cache_valid(_spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS),
        "spaceflight_events": is_cache_valid(_spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS),
        "weather_forecast": is_cache_valid(_weather_cache, WEATHER_CACHE_TTL),
        "iers": is_cache_valid(_iers_cache, CACHE_TTL_IERS),
        "all_ready": (
            is_cache_valid(_moon_report_cache, CACHE_TTL_MOON_REPORT) and
            is_cache_valid(_sun_report_cache, CACHE_TTL_SUN_REPORT) and
            is_cache_valid(_best_window_cache["strict"], CACHE_TTL_BEST_WINDOW) and
            is_cache_valid(_moon_planner_report_cache, CACHE_TTL_MOON_PLANNER) and
            is_cache_valid(_dark_window_report_cache, CACHE_TTL_DARK_WINDOW) and
            is_cache_valid(_solar_eclipse_cache, CACHE_TTL_SOLAR_ECLIPSE) and
            is_cache_valid(_lunar_eclipse_cache, CACHE_TTL_LUNAR_ECLIPSE) and
            is_cache_valid(_horizon_graph_cache, CACHE_TTL_HORIZON_GRAPH) and
            is_cache_valid(_aurora_cache, CACHE_TTL_AURORA) and
            is_cache_valid(_iss_passes_cache, CACHE_TTL_ISS_PASSES) and
            is_cache_valid(_planetary_events_cache, CACHE_TTL_PLANETARY_EVENTS) and
            is_cache_valid(_special_phenomena_cache, CACHE_TTL_SPECIAL_PHENOMENA) and
            is_cache_valid(_solar_system_events_cache, CACHE_TTL_SOLAR_SYSTEM_EVENTS) and
            is_cache_valid(_sidereal_time_cache, CACHE_TTL_SIDEREAL_TIME) and
            is_cache_valid(_seeing_forecast_cache, CACHE_TTL_SEEING_FORECAST) and
            is_cache_valid(_spaceflight_launches_cache, CACHE_TTL_SPACEFLIGHT_LAUNCHES) and
            is_cache_valid(_spaceflight_astronauts_cache, CACHE_TTL_SPACEFLIGHT_ASTRONAUTS) and
            is_cache_valid(_spaceflight_events_cache, CACHE_TTL_SPACEFLIGHT_EVENTS)
        ),
        "in_progress": in_progress,
        "current_step": current_step,
        "total_steps": total_steps,
        "step_name": step_name,
        "progress_percent": progress_percent,
        "ttls": {
            "moon_report": CACHE_TTL_MOON_REPORT,
            "dark_window": CACHE_TTL_DARK_WINDOW,
            "moon_planner": CACHE_TTL_MOON_PLANNER,
            "sun_report": CACHE_TTL_SUN_REPORT,
            "best_window": CACHE_TTL_BEST_WINDOW,
            "solar_eclipse": CACHE_TTL_SOLAR_ECLIPSE,
            "lunar_eclipse": CACHE_TTL_LUNAR_ECLIPSE,
            "horizon_graph": CACHE_TTL_HORIZON_GRAPH,
            "aurora": CACHE_TTL_AURORA,
            "iss_passes": CACHE_TTL_ISS_PASSES,
            "planetary_events": CACHE_TTL_PLANETARY_EVENTS,
            "special_phenomena": CACHE_TTL_SPECIAL_PHENOMENA,
            "solar_system_events": CACHE_TTL_SOLAR_SYSTEM_EVENTS,
            "sidereal_time": CACHE_TTL_SIDEREAL_TIME,
            "seeing_forecast": CACHE_TTL_SEEING_FORECAST,
            "spaceflight_launches": CACHE_TTL_SPACEFLIGHT_LAUNCHES,
            "spaceflight_astronauts": CACHE_TTL_SPACEFLIGHT_ASTRONAUTS,
            "spaceflight_events": CACHE_TTL_SPACEFLIGHT_EVENTS,
            "weather_forecast": WEATHER_CACHE_TTL,
            "iers": CACHE_TTL_IERS,
        },
        "execution_metrics": get_cache_metrics(),
    }


def set_cache_initialization_in_progress(value, current_step=0, total_steps=0, step_name=""):
    """Set the cache initialization progress flag in shared cache for cross-worker visibility"""
    with _cache_file_write_lock():
        shared_cache = _read_shared_cache()
        shared_cache["_cache_in_progress"] = {
            "status": value,
            "timestamp": time.time(),
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name
        }
        _write_shared_cache(shared_cache)


def record_cache_execution(job_name, duration_seconds, success):
    """Persist per-job execution timing and result to shared cache for metrics reporting."""
    with _cache_file_write_lock():
        shared = _read_shared_cache()
        if "_cache_metrics" not in shared:
            shared["_cache_metrics"] = {}
        shared["_cache_metrics"][job_name] = {
            "last_run_at": datetime.now().isoformat(),
            "last_duration_s": round(duration_seconds, 3),
            "last_success": success,
        }
        _write_shared_cache(shared)


def get_cache_metrics():
    """Return per-job execution metrics from shared cache."""
    shared = _read_shared_cache()
    return shared.get("_cache_metrics", {})